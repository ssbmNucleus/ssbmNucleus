"""The library passes do their CPU work in ONE worker process, never in the
process that serves requests.

The replay index, the combo extraction and the vault derive all walk .slp
files in pure Python. Run in the serving process they hold the GIL and the
disk for as long as the pass lasts, and every API call the UI makes queues
behind them -- measured on the live app during a vault sync: /stats went from
0.2s to 10-18s for the whole multi-hour run. It is worse than it sounds,
because the Tracker pages poll on 2s timers: once a poll takes longer than its
interval the requests pile up, and Chromium's six-connections-per-origin cap
means the NEXT thing the user clicks is not slow, it is not sent at all. That
is what made "Watch" sit on "Loading..." (the options call itself measures
~0ms). The combo pass is the one that bites now: combos._ensure_frame_basis
re-queues the whole library the first time a new build runs.

One worker, not a pool: pass throughput matters much less than the app staying
usable, and a single child keeps the memory cost of the spawn re-import to one
copy. The worker also drops to below-normal priority, so even on a busy
machine a background pass never outranks a request someone is waiting on.

Spawn-safe for the frozen build: app.py calls freeze_support() first thing
and skips its launch side effects under __mp_main__ (the py7zr fork-bomb and
the ~90-runaway-backends lessons).

The worker is also where untrusted bytes are parsed. Replays come from any
folder, download or vault pull, and peppi_py (Rust) dies outright on some
crafted .slp files: a stack overflow on deeply nested metadata, gigabytes
allocated for a raw length past the end of the file. In the serving process
that is the whole backend gone, so (security review, 2026-11):

  - Nothing falls back to running in the serving process. A worker that
    cannot start raises WorkerUnavailable, and no new one is tried for
    COOLDOWN seconds; the pass stops and the next pass tries again.
  - Every call has a timeout (DEFAULT_TIMEOUT). A worker that dies or runs
    past it is killed, and the call raises ScanFailed. A fresh worker is then
    started and pinged: when it answers, the file was to blame.
  - That file -- the call's first argument, by path, size and mtime -- is
    quarantined (scan_quarantine.json beside nucleome.db, the newest
    QUARANTINE_MAX kept), so the next pass refuses it at once with
    ScanFailed instead of crashing a fresh worker on it. A changed file is a
    new key and is read again.
  - Calls take turns in the shared worker, first come first served, so the
    call that was running is always the one a crash belongs to.

    result = scan_pool.run(module_level_fn, path, *more_args)

`fn` must be importable by name in a spawned child and its arguments and
result must pickle. Prefer functions that RETURN their errors; an exception
raised in the child crosses back intact and is raised here unchanged.

Set NUCLEUS_SCAN_INPROC=1 to keep everything inline (tests, debugging).
"""
import atexit
import json
import logging
import multiprocessing
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0      # seconds one call may take, the spawn included
PING_TIMEOUT = 60.0          # a fresh worker answering after a failure
COOLDOWN = 60.0              # no new worker this long after one could not start
QUARANTINE_MAX = 500
# None = scan_quarantine.json beside the replay index (indexer.DB_PATH)
QUARANTINE_PATH = None

_pool = None
_unavailable_until = 0.0
_lock = threading.Lock()     # guards _pool / _unavailable_until
_in_worker = False           # set in the children by _init_worker


class ScanFailed(Exception):
    """The file crashed or hung a worker -- now, or before (it is
    quarantined). Nothing of it was read."""

    def __init__(self, message, path=None):
        super().__init__(message)
        self.path = path


class WorkerUnavailable(RuntimeError):
    """No worker process could be started, so nothing ran. Not the file's
    fault: a pass should stop and try again later, not record a failure."""


# One class DOWN from whatever the backend itself is running at — not a fixed
# BELOW_NORMAL. Measured 2026-09-11: the backend is already BELOW_NORMAL when
# launched from run.bat (the class is inherited, and the worker inherits it
# too), so pinning the worker to BELOW_NORMAL would have left it exactly level
# with the requests it is supposed to yield to.
_NEXT_PRIORITY_DOWN = {
    0x00000080: 0x00000020,   # HIGH          -> NORMAL
    0x00000020: 0x00004000,   # NORMAL        -> BELOW_NORMAL
    0x00004000: 0x00000040,   # BELOW_NORMAL  -> IDLE
    0x00000040: 0x00000040,   # IDLE          -> IDLE
}


def _deprioritise():
    """Drop the worker below the backend in the OS scheduler."""
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
            k32.GetPriorityClass.restype = ctypes.c_uint
            k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.SetPriorityClass.restype = ctypes.c_int
            me = k32.GetCurrentProcess()
            # inherited from the backend, so this IS the backend's class
            want = _NEXT_PRIORITY_DOWN.get(k32.GetPriorityClass(me), 0x00000040)
            k32.SetPriorityClass(me, want)
        else:
            # nice is relative and inherited, so this is already "below the
            # parent" on POSIX
            os.nice(10)
    except Exception:                                         # noqa: BLE001
        logger.debug("scan_pool: could not lower worker priority", exc_info=True)


def _init_worker(ppid):
    """ProcessPoolExecutor initializer, run once in the child."""
    global _in_worker
    _in_worker = True
    from core.child_procs import worker_watchdog
    # the watchdog is the worker's only tie to us: a dead backend otherwise
    # leaves it blocked on the call queue forever
    worker_watchdog(ppid)
    _deprioritise()


def in_worker():
    """True inside a scan worker (shared or burst): already isolated."""
    return _in_worker


def inproc():
    return os.environ.get("NUCLEUS_SCAN_INPROC") == "1"


def _shutdown():
    """Registered when the pool is first built, so it runs BEFORE
    concurrent.futures' own atexit join (atexit is LIFO) and the backend does
    not wait on a queue of work it is about to abandon."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


_atexit_registered = False


def _new_pool(workers):
    from concurrent.futures import ProcessPoolExecutor
    return ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_init_worker, initargs=(os.getpid(),))


def _kill(pool):
    """End a pool's processes now (our own children, by handle), whatever
    they are doing, and drop its queued work."""
    procs = list((getattr(pool, "_processes", None) or {}).values())
    for proc in procs:
        try:
            proc.kill()
        except Exception:                                     # noqa: BLE001
            pass
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:                                         # noqa: BLE001
        pass
    for proc in procs:
        try:
            proc.join(5)
        except Exception:                                     # noqa: BLE001
            pass


def _shared_pool():
    """The shared worker pool, started when there is none (or it broke)."""
    global _pool, _unavailable_until, _atexit_registered
    with _lock:
        if _pool is not None and not getattr(_pool, "_broken", False):
            return _pool
        if _pool is not None:
            _kill(_pool)
            _pool = None
        wait = _unavailable_until - time.monotonic()
        if wait > 0:
            raise WorkerUnavailable(
                f"the replay worker could not start; trying again in {wait:.0f}s")
        try:
            _pool = _new_pool(1)
        except (OSError, RuntimeError, ValueError) as e:
            _unavailable_until = time.monotonic() + COOLDOWN
            raise WorkerUnavailable(f"the replay worker could not start: {e}") from e
        if not _atexit_registered:
            atexit.register(_shutdown)
            _atexit_registered = True
        return _pool


def _discard(pool):
    global _pool
    with _lock:
        if _pool is pool:
            _pool = None
    _kill(pool)


def _cool_down():
    global _unavailable_until
    with _lock:
        _unavailable_until = time.monotonic() + COOLDOWN


def _worker_answers():
    """After a failure: does a fresh worker start and answer? When it does it
    stays the shared worker; when not, no new one is tried for COOLDOWN."""
    from concurrent.futures import TimeoutError as FuturesTimeout
    from concurrent.futures.process import BrokenProcessPool
    try:
        pool = _shared_pool()
    except WorkerUnavailable:
        return False
    try:
        pool.submit(os.getpid).result(timeout=PING_TIMEOUT)
        return True
    except (BrokenProcessPool, FuturesTimeout, OSError, RuntimeError):
        logger.warning("scan_pool: a fresh replay worker did not answer", exc_info=True)
        _discard(pool)
        _cool_down()
        return False


# --- one call at a time ---------------------------------------------------

class _Turns:
    """A first-come-first-served lock. threading.Lock is not fair, and a pass
    that runs file after file would otherwise starve a request waiting to
    read one file."""

    def __init__(self):
        self._cond = threading.Condition()
        self._issued = 0
        self._serving = 0

    def __enter__(self):
        with self._cond:
            ticket = self._issued
            self._issued += 1
            while ticket != self._serving:
                self._cond.wait()
        return self

    def __exit__(self, *exc):
        with self._cond:
            self._serving += 1
            self._cond.notify_all()
        return False


_turns = _Turns()


# --- quarantine -----------------------------------------------------------

_q_lock = threading.Lock()
_q_cache = {"path": None, "stamp": None, "entries": []}


def quarantine_path():
    if QUARANTINE_PATH is not None:
        return Path(QUARANTINE_PATH)
    from . import indexer
    return Path(indexer.DB_PATH).with_name("scan_quarantine.json")


def file_key(path):
    """(path, size, mtime_ns) of a file, or None when `path` is not one."""
    if not isinstance(path, (str, os.PathLike)):
        return None
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (os.path.normcase(os.path.abspath(os.fspath(path))), st.st_size, st.st_mtime_ns)


def _entries():
    """The quarantine list, re-read when the file changed."""
    store = quarantine_path()
    try:
        st = store.stat()
        stamp = (st.st_size, st.st_mtime_ns)
    except OSError:
        stamp = None
    if _q_cache["path"] == store and _q_cache["stamp"] == stamp:
        return _q_cache["entries"]
    entries = []
    if stamp is not None:
        try:
            data = json.loads(store.read_text(encoding="utf-8"))
            entries = [e for e in data.get("files", []) if isinstance(e, dict)]
        except (OSError, ValueError, AttributeError):
            logger.warning("scan_pool: unreadable quarantine list %s", store, exc_info=True)
    _q_cache.update(path=store, stamp=stamp, entries=entries)
    return entries


def quarantined(key):
    """The quarantine entry for a file key, or None."""
    if key is None:
        return None
    with _q_lock:
        for entry in _entries():
            if (entry.get("path"), entry.get("size"), entry.get("mtime_ns")) == key:
                return entry
    return None


def _quarantine(key, fn, what):
    entry = {"path": key[0], "size": key[1], "mtime_ns": key[2], "what": what,
             "task": getattr(fn, "__qualname__", str(fn)),
             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    logger.warning("scan_pool: quarantined %s: it %s (%s)", key[0], what, entry["task"])
    with _q_lock:
        entries = [e for e in _entries()
                   if (e.get("path"), e.get("size"), e.get("mtime_ns")) != key]
        entries = (entries + [entry])[-QUARANTINE_MAX:]
        store = quarantine_path()
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            tmp = store.with_name(store.name + ".tmp")
            tmp.write_text(json.dumps({"files": entries}, indent=1), encoding="utf-8")
            os.replace(tmp, store)
            st = store.stat()
            _q_cache.update(path=store, stamp=(st.st_size, st.st_mtime_ns), entries=entries)
        except OSError:
            # still refused for this session
            logger.warning("scan_pool: could not save the quarantine list", exc_info=True)
            _q_cache.update(path=store, entries=entries)


def _refused(key, args):
    entry = quarantined(key)
    if entry is None:
        return None
    return ScanFailed(f"{os.path.basename(key[0])} was not read: it {entry.get('what')} "
                      f"before (quarantined {entry.get('at')})", args[0])


def _key_of(args):
    return file_key(args[0]) if args else None


# --- the shared worker ----------------------------------------------------

def run(fn, *args, timeout=None):
    """Run `fn(*args)` in the shared worker process, at most `timeout`
    seconds (DEFAULT_TIMEOUT). Raises ScanFailed when the file (the first
    argument) crashed or hung the worker, now or before, and
    WorkerUnavailable when no worker could start. Never runs `fn` here."""
    if inproc() or _in_worker:
        return fn(*args)
    key = _key_of(args)
    refused = _refused(key, args)
    if refused:
        raise refused
    with _turns:
        return _run_turn(fn, args, key, timeout or DEFAULT_TIMEOUT)


def _run_turn(fn, args, key, timeout):
    from concurrent.futures import TimeoutError as FuturesTimeout
    from concurrent.futures.process import BrokenProcessPool
    name = getattr(fn, "__name__", fn)
    future = None
    for attempt in (1, 2):
        pool = _shared_pool()
        try:
            future = pool.submit(fn, *args)
            break
        except (OSError, RuntimeError) as e:
            # the worker died between calls, or a process could not be
            # created: not this file. One fresh try, then a cool-down.
            _discard(pool)
            if attempt == 2:
                _cool_down()
                raise WorkerUnavailable(f"the replay worker could not start: {e}") from e
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        what, done = f"ran past {timeout:g} seconds", " and was stopped"
    except BrokenProcessPool:
        what, done = "crashed the replay worker", ""
    _discard(pool)
    if not _worker_answers():
        raise WorkerUnavailable(f"the replay worker stopped on {name} and no new one started")
    path = args[0] if args else None
    if key is not None:
        _quarantine(key, fn, what)
    label = os.path.basename(os.fspath(path)) if key is not None else name
    raise ScanFailed(f"{label} {what}{done}", path)


# --- bursts ---------------------------------------------------------------

class _Shared:
    """A burst that has no pool of its own: every job goes through run(),
    the shared worker. Same interface as _Burst."""

    workers = 1

    def submit(self, fn, *args):
        return _Done(run, fn, *args)


class _Done:
    """Deferred run(): computed on .result(), so a shared burst still does
    its work lazily and in the order it is consumed."""

    def __init__(self, runner, fn, *args):
        self._call = (runner, fn, args)

    def result(self):
        runner, fn, args = self._call
        return runner(fn, *args)

    def cancel(self):
        return True


class _Job:
    def __init__(self, burst_pool, future, fn, args):
        self._burst, self._future, self._fn, self._args = burst_pool, future, fn, args

    def result(self):
        from concurrent.futures import CancelledError
        from concurrent.futures import TimeoutError as FuturesTimeout
        from concurrent.futures.process import BrokenProcessPool
        f = self._future
        if f.done() and not f.cancelled():
            exc = f.exception()
            if exc is None:
                return f.result()
            if not isinstance(exc, BrokenProcessPool):
                raise exc
            self._burst.condemn("a worker crashed")
        elif not self._burst.condemned:
            try:
                return f.result(timeout=self._burst.timeout)
            except FuturesTimeout:
                self._burst.condemn("a job ran past its time")
            except BrokenProcessPool:
                self._burst.condemn("a worker crashed")
            except CancelledError:
                pass
        # A burst worker died or hung, and with several running there is no
        # telling which file did it: each unfinished job runs again alone in
        # the shared worker, which can tell (and quarantines that one).
        return run(self._fn, *self._args)

    def cancel(self):
        return self._future.cancel()


class _Burst:
    def __init__(self, pool, workers, timeout):
        self._pool, self.workers, self.timeout = pool, workers, timeout
        self.condemned = False

    def condemn(self, why):
        if not self.condemned:
            self.condemned = True
            logger.warning("scan_pool: burst stopped (%s); the rest go through the "
                           "shared worker one at a time", why)
            _kill(self._pool)

    def submit(self, fn, *args):
        if self.condemned or quarantined(_key_of(args)):
            return _Done(run, fn, *args)
        try:
            return _Job(self, self._pool.submit(fn, *args), fn, args)
        except RuntimeError:
            # submit after a broken pool raises BrokenProcessPool (a
            # RuntimeError)
            self.condemn("its pool broke")
            return _Done(run, fn, *args)


class burst:
    """A TEMPORARY pool of `workers` processes for one throughput-bound pass.

        with scan_pool.burst(4) as pool:
            jobs = [pool.submit(fn, path) for path in paths]
            for job in jobs:
                value = job.result()

    Exists for the vault upload (bug-report: a 44k-game library took ~15h at
    ~1.1 s/game, almost all of it deriving one game at a time in the single
    shared worker). It keeps every rule the shared worker has -- spawn
    context, the parent watchdog, one priority class BELOW the backend, and
    NOTHING runs in the serving process -- it only runs more than one child,
    and only for as long as the `with` block lasts: on exit the children are
    shut down, so the app's steady state is still one worker.

    A job that crashes or outlasts `timeout` stops the burst: its children
    are killed and every unfinished job runs again through run(), one at a
    time, which finds the file that did it. job.result() raises what run()
    raises (ScanFailed, WorkerUnavailable).

    workers <= 1 or NUCLEUS_SCAN_INPROC=1 degrade to the shared worker via
    run(), so callers need no second code path.
    """

    def __init__(self, workers, timeout=None):
        self.workers = max(1, int(workers or 1))
        self.timeout = timeout or DEFAULT_TIMEOUT
        self._pool = None

    def __enter__(self):
        if self.workers <= 1 or inproc():
            return _Shared()
        try:
            self._pool = _new_pool(self.workers)
        except (OSError, RuntimeError, ValueError):
            logger.warning("scan_pool: burst pool unavailable", exc_info=True)
            return _Shared()
        return _Burst(self._pool, self.workers, self.timeout)

    def __exit__(self, *exc):
        pool, self._pool = self._pool, None
        if pool is not None:
            # never wait on derives nobody will read (a cancelled sync); the
            # watchdog covers a backend that exits before these do
            pool.shutdown(wait=False, cancel_futures=True)
        return False
