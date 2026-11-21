"""Bounded retries for transient Windows file locks.

Windows Defender's real-time scan and the search indexer open a file the moment
it is written or renamed, usually without FILE_SHARE_DELETE, and hold it for a
few milliseconds. An operation on that path inside that window fails even
though nothing is wrong:

  * os.replace onto a destination the scanner holds fails with
    ERROR_ACCESS_DENIED (winerror 5 -- MoveFileEx's answer for a destination
    open without delete sharing), ERROR_SHARING_VIOLATION (32) or
    ERROR_LOCK_VIOLATION (33);
  * open() for a rewrite, a copy onto the path, or an unlink fails with
    PermissionError [Errno 13] -- the CRT folds 5/32/33 into EACCES and drops
    the Windows code.

These helpers retry exactly those errors, on Windows only, for a bounded time
(DEFAULT_TIMEOUT, sleeping 10 ms growing to 100 ms between attempts). Any other
error is raised at once. A lock that outlasts the deadline re-raises the LAST
error unchanged. On Windows a permanent denial -- an ACL, a read-only file, a
directory opened as a file -- reports the same errno 13 / winerror 5 as a
scanner's lock, so it still surfaces, but only after the ~2 s bound. Elsewhere
both helpers are one plain call.

This is a top-level package, not part of `core`, on purpose: importing `core`
runs core.config (which repoints TEMP and may take the data-root lease), and
standalone tools that write files must not pay for that. Keep it stdlib-only
and free of import-time side effects.

Precedent: vault/routes/menus/helpers._run_hsd_cli (retries HSDRawViewer's
"being used by another process").
"""
import errno
import os
import time

# The retry is Windows-only. Tests patch this to exercise it on any OS.
IS_WINDOWS = os.name == 'nt'

# ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
TRANSIENT_WINERRORS = frozenset({5, 32, 33})

DEFAULT_TIMEOUT = 2.0
_FIRST_DELAY = 0.01
_MAX_DELAY = 0.1


def is_transient_lock(exc):
    """True for the errors a scanner or indexer holding a file produces.

    Win32 calls (os.replace, os.unlink) carry `winerror`; CRT calls (open) carry
    only errno EACCES, which is how a sharing violation surfaces there.
    """
    winerror = getattr(exc, 'winerror', None)
    if winerror is not None:
        return winerror in TRANSIENT_WINERRORS
    return isinstance(exc, PermissionError) and exc.errno == errno.EACCES


def _retry(operation, timeout):
    deadline = time.monotonic() + timeout
    delay = _FIRST_DELAY
    while True:
        try:
            return operation()
        except OSError as exc:
            if not is_transient_lock(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, _MAX_DELAY)


def replace(src, dst, *, timeout=DEFAULT_TIMEOUT):
    """os.replace(src, dst), retried while a scanner briefly holds either file.

    On Windows a transient lock (winerror 5/32/33) is retried for up to
    `timeout` seconds and then the last error is re-raised unchanged. A failed
    attempt leaves both files where they were, so a retry is always safe.
    Elsewhere this is exactly os.replace.
    """
    if not IS_WINDOWS:
        os.replace(src, dst)
        return
    _retry(lambda: os.replace(src, dst), timeout)


def retry_locked(fn, *args, timeout=DEFAULT_TIMEOUT, **kwargs):
    """Return fn(*args, **kwargs), retried on Windows while its file is locked.

    Only for an operation that is safe to repeat WHOLE: a write that truncates
    and rewrites (open 'w'/'wb', Path.write_bytes/write_text), a copy onto a
    path (shutil.copyfile/copy2), an unlink. Never wrap an append, or a
    multi-step operation that may have done part of its work before it failed:
    the retry would repeat or interleave that part.

    `timeout` is consumed here and never passed to `fn`. Elsewhere than Windows
    this is one plain call.
    """
    if not IS_WINDOWS:
        return fn(*args, **kwargs)
    return _retry(lambda: fn(*args, **kwargs), timeout)
