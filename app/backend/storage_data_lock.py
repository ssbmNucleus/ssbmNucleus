"""Lifetime, per-data-root lock shared by managed backends and relocation.

No application imports or configuration side effects. Keep the returned lock
alive for the entire backend lifetime. The marker is never unlinked: replacing
it could let two processes lock different inodes under the same path.
"""
import os
from pathlib import Path
import stat


LOCK_FILENAME = '.nucleus-data.lock'


class DataRootBusyError(RuntimeError):
    pass


class DataRootLock:
    def __init__(self, stream, windows_lock=None):
        self._stream = stream
        self._windows_lock = windows_lock

    def close(self):
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            if os.name == 'nt':
                import ctypes
                import msvcrt
                kernel, overlapped = self._windows_lock
                if not kernel.UnlockFileEx(msvcrt.get_osfhandle(stream.fileno()), 0, 1, 0,
                                           ctypes.byref(overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _lock_windows(stream, exclusive):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                    ('hEvent', wintypes.HANDLE)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    kernel.LockFileEx.restype = wintypes.BOOL
    kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    kernel.UnlockFileEx.restype = wintypes.BOOL
    overlapped = OVERLAPPED()
    flags = 1 | (2 if exclusive else 0)  # FAIL_IMMEDIATELY | optional EXCLUSIVE_LOCK
    if not kernel.LockFileEx(msvcrt.get_osfhandle(stream.fileno()), flags, 0, 1, 0,
                             ctypes.byref(overlapped)):
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel, overlapped


def acquire_data_root_lock(root, *, exclusive=True):
    """Nonblocking lease: exclusive for relocation, shared for backend lifetime.

    Shared leases let normal and nested headless backends coexist. An exclusive
    migration lease requires every shared consumer to have exited. No marker
    byte is written: both platforms allow a range lock beyond a zero-byte EOF.
    """
    root = Path(root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('The managed data root must be an existing absolute directory.')
    marker = root / LOCK_FILENAME
    for path in (marker, *marker.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('The managed data root cannot contain symbolic links or reparse points.')
    descriptor = os.open(marker, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    stream = os.fdopen(descriptor, 'r+b', buffering=0)
    try:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('The data-root lock marker is not a regular file.')
        windows_lock = None
        if os.name == 'nt':
            windows_lock = _lock_windows(stream, exclusive)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                        | fcntl.LOCK_NB)
        return DataRootLock(stream, windows_lock)
    except (BlockingIOError, PermissionError, OSError) as exc:
        stream.close()
        raise DataRootBusyError(
            'This data folder is in use by another Nucleus backend or relocation. '
            'Close other Nucleus tools and retry; no data location was changed.') from exc
    except Exception:
        stream.close()
        raise
