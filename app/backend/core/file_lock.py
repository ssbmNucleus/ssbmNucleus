"""One cross-process advisory lock, for the small files two Nucleus windows share.

`core.build_transaction` already locks a build directory this way. This is the
same idea for an ordinary settings file: an exclusive byte lock on a marker
beside it, held across a read-modify-write so a second process cannot interleave
and lose somebody's edit. It is deliberately tiny and has no journal -- a lost
settings edit is a nuisance, not a corrupted build.

Ordering rule for anything that takes more than one of the app's locks:

    build lock / mexcli_lock   FIRST
    settings lock              SECOND

Designation used to take the settings lock and then reach for `mexcli_lock` to
look a project up, while a delivery held `mexcli_lock` and then wanted the
settings lock. That is a deadlock with two windows open, and the fix is the
order above: resolve everything that needs the build locks before touching
settings.
"""
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_SUFFIX = '.lock'


class LockBusy(RuntimeError):
    """Another process holds this lock."""


def _take(stream):
    if os.name == 'nt':
        import ctypes
        import ctypes.wintypes
        import msvcrt

        class _Overlapped(ctypes.Structure):
            _fields_ = [('Internal', ctypes.wintypes.LPVOID),
                        ('InternalHigh', ctypes.wintypes.LPVOID),
                        ('Offset', ctypes.wintypes.DWORD),
                        ('OffsetHigh', ctypes.wintypes.DWORD),
                        ('Pointer', ctypes.wintypes.LPVOID),
                        ('hEvent', ctypes.wintypes.HANDLE)]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        overlapped = _Overlapped()
        handle = msvcrt.get_osfhandle(stream.fileno())
        # LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY
        if not kernel.LockFileEx(handle, 0x00000002 | 0x00000001, 0, 1, 0,
                                 ctypes.byref(overlapped)):
            raise BlockingIOError(ctypes.get_last_error(), 'locked')
        return kernel, overlapped
    import fcntl
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return None


def _release(stream, token):
    try:
        if os.name == 'nt' and token is not None:
            import ctypes
            import msvcrt
            kernel, overlapped = token
            kernel.UnlockFileEx(msvcrt.get_osfhandle(stream.fileno()), 0, 1, 0,
                                ctypes.byref(overlapped))
        elif os.name != 'nt':
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


@contextmanager
def exclusive(path, *, timeout=15.0):
    """Hold an exclusive cross-process lock on `<path>.lock` for this block.

    Raises:
        LockBusy: another process still holds it after `timeout`.
    """
    marker = Path(str(path) + LOCK_SUFFIX)
    marker.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(marker, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    stream = os.fdopen(descriptor, 'r+b', buffering=0)
    try:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise LockBusy(f'{marker} is not a regular file')
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            try:
                token = _take(stream)
                break
            except (BlockingIOError, PermissionError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise LockBusy(
                        'Another Nucleus window is changing this at the same time. '
                        'Nothing was written; try again in a moment.') from exc
                time.sleep(0.05)
    except BaseException:
        stream.close()
        raise
    try:
        yield
    finally:
        _release(stream, token)
