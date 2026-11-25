"""The one way the backend hands a .slp to peppi_py: slp_guard.read_slippi.

peppi_py is Rust, and a crafted replay can make it overflow its stack (deeply
nested metadata) or allocate gigabytes (a raw length past the end of the
file). Neither raises: the process it runs in dies. In the serving process
that is the whole backend, and replays come from any folder, download or
vault pull. So, before peppi_py sees a file:

  1. slp_meta.peppi_refusal checks the bytes for the shapes known to do that
     (size, raw length, metadata size and nesting), in every process.
  2. Outside the scan worker (a request, a sync thread), the file is parsed
     in the worker first (scan_pool.run, with PROBE_TIMEOUT). A file that
     crashes or hangs the worker is quarantined there and refused here, so
     this process only parses a file a worker has already parsed: the same
     path, size and mtime. Those are remembered, so it is once per file.
  Inside the worker (scan_pool.in_worker) step 2 is skipped: the worker is
  the isolation, and the scan pool quarantines a file that kills it.

A refused file raises UnsafeReplay, an ordinary Exception, which the callers
already treat as a replay that will not parse.

NUCLEUS_SCAN_INPROC=1 (tests) skips step 2 like the worker does.
"""
import logging
import threading
from collections import OrderedDict

from . import scan_pool, slp_meta

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 60.0
_GOOD_MAX = 4096

_good = OrderedDict()            # file keys a worker parsed without dying
_good_lock = threading.Lock()


class UnsafeReplay(Exception):
    """peppi_py was not run on this file; the message says why."""


def probe(path):
    """Run in the scan worker: parse the file once. True however peppi_py
    took it -- an ordinary error is a corrupt file, which the caller's own
    parse reports the same way. Only dying or hanging (the scan pool sees
    those) refuses a file."""
    from peppi_py import read_slippi
    try:
        read_slippi(path)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:                                     # noqa: BLE001
        pass
    return True


def _known_good(key):
    with _good_lock:
        if key in _good:
            _good.move_to_end(key)
            return True
    return False


def _remember(key):
    with _good_lock:
        _good[key] = True
        _good.move_to_end(key)
        while len(_good) > _GOOD_MAX:
            _good.popitem(last=False)


def refusal(path):
    """Why peppi_py must not parse `path` in this process, or None."""
    why = slp_meta.peppi_refusal(path)
    if why:
        return why
    if scan_pool.in_worker() or scan_pool.inproc():
        return None
    key = scan_pool.file_key(path)
    if key is None:
        return "the file could not be read"
    if _known_good(key):
        return None
    try:
        scan_pool.run(probe, path, timeout=PROBE_TIMEOUT)
    except scan_pool.ScanFailed as e:
        return str(e)
    except scan_pool.WorkerUnavailable as e:
        return f"it was not read because {e}"
    _remember(key)
    return None


def read_slippi(path, **kwargs):
    """peppi_py.read_slippi(path, **kwargs) once the file passed refusal();
    raises UnsafeReplay when it did not."""
    why = refusal(path)
    if why:
        logger.info("slp_guard: not parsing %s: %s", path, why)
        raise UnsafeReplay(why)
    import peppi_py             # looked up per call, so a test's stand-in is used
    return peppi_py.read_slippi(path, **kwargs)
