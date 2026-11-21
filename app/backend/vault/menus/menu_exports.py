"""
Cached HSDRawViewer exports for the "Currently in MEX" file checks.

A check decodes a game file's pictures with an existing export mode
(`--hud-textures export`, `--pause-screen export`, ...) and compares them
with menu_pixels. An export takes seconds, so the output directory is kept
under the temp folder, keyed by the file's path, mtime and size: the next
check of an unchanged file reuses it, a changed file gets a fresh export and
its old copies are removed. Never raises; None when the export fails.
"""

import hashlib
import logging
import shutil
import tempfile
import threading
from pathlib import Path

from vault.menus.hsd import _run_hsd_cli

logger = logging.getLogger(__name__)

CACHE_DIR_NAME = 'nucleus_menu_checks'
MAX_CACHED_EXPORTS = 24
DONE_MARKER = '.complete'

_locks = {}
_locks_guard = threading.Lock()


def cache_root():
    return Path(tempfile.gettempdir()) / CACHE_DIR_NAME


def file_sig(path):
    """[mtime_ns, size] of a file, or None."""
    try:
        st = Path(path).stat()
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def _lock_for(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _evict(root, keep):
    try:
        dirs = sorted((d for d in root.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs[keep:]:
            shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def cached_export(mode, path, timeout=300):
    """Directory holding `HSDRawViewer <mode> export <path> <dir>` output for
    the file as it is now, or None when the file is missing or the export
    failed. `mode` is the CLI flag, e.g. '--hud-textures'."""
    path = Path(path)
    sig = file_sig(path)
    if sig is None:
        return None
    try:
        ident = hashlib.sha1(f'{mode}|{path.resolve()}'.lower().encode('utf-8')).hexdigest()[:16]
    except OSError:
        return None
    root = cache_root()
    target = root / f'{ident}_{sig[0]}_{sig[1]}'
    with _lock_for(ident):
        if (target / DONE_MARKER).is_file():
            return target
        try:
            root.mkdir(parents=True, exist_ok=True)
            for old in root.glob(f'{ident}_*'):
                shutil.rmtree(old, ignore_errors=True)
            work = root / f'{ident}_{sig[0]}_{sig[1]}.tmp'
            shutil.rmtree(work, ignore_errors=True)
            result = _run_hsd_cli([mode, 'export', str(path), str(work)], timeout=timeout)
            if result is None or not work.is_dir():
                shutil.rmtree(work, ignore_errors=True)
                return None
            if file_sig(path) != sig:
                # changed while exporting: don't cache a mix
                shutil.rmtree(work, ignore_errors=True)
                return None
            (work / DONE_MARKER).write_text('ok', encoding='utf-8')
            work.rename(target)
        except Exception as e:
            logger.warning(f'Menu check export {mode} of {path.name} failed: {e}')
            return None
    _evict(root, MAX_CACHED_EXPORTS)
    return target if (target / DONE_MARKER).is_file() else None
