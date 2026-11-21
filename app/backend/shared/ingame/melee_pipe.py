r"""
melee_pipe.py -- send controller input to Slippi Dolphin's controller pipe from
Python, for closed-loop (memory-feedback) control.

Holds ONE persistent connection open (libmelee's model). Dolphin reads every
FLUSH batch from a live connection and HOLDS the last input until the next, so
a held tilt/press persists until you change it. This is essential for
closed-loop control: a fresh connection per frame churns connect/close and
desyncs Dolphin's controller -- inputs stop registering. A single open
connection avoids that.

Windows: Dolphin exposes a named pipe \\.\pipe\slippibot<N>; opened/written
with raw kernel32 via ctypes (CreateFileW / WriteFile / CloseHandle) so the
packaged backend needs NO extra installs (no pywin32).

Linux: Dolphin's Pipe input backend instead READS a plain FIFO at
<UserDir>/Pipes/slippibot<N>. The FIFO must exist before Dolphin scans
controllers (boot.py mkfifo's it into the throwaway user dir and calls
set_pipe_dir()); the writer side here opens it O_WRONLY|O_NONBLOCK, which
fails with ENXIO until Dolphin has the read end open -- that maps 1:1 onto
the Windows "pipe not up yet, retry" flow.

Buttons: A B X Y Z L R START D_UP D_DOWN D_LEFT D_RIGHT. Sticks 0.0-1.0, 0.5
center; control stick y=0.0 DOWN, y=1.0 UP (libmelee's convention -- verified
in-match: y=1.0 + B is an UP-B), x=0.0 LEFT, x=1.0 RIGHT. The closed-loop
cursor code (melee_css/melee_sss) is unaffected by the labels -- it steers by
feedback -- but open-loop in-match inputs MUST use this mapping.
"""

import errno
import os
import time

BUTTONS = ["A", "B", "X", "Y", "Z", "L", "R", "START",
           "D_UP", "D_DOWN", "D_LEFT", "D_RIGHT"]

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wt

    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    # CreateFile error codes seen while Slippi Dolphin is (re-)arming the pipe.
    ERROR_FILE_NOT_FOUND = 2     # the pipe isn't present this instant (being recreated)
    ERROR_PIPE_BUSY = 231        # the pipe exists but every instance is busy

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateFileW.restype = wt.HANDLE
    _k32.CreateFileW.argtypes = [
        wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE,
    ]
    _k32.WriteFile.restype = wt.BOOL
    _k32.WriteFile.argtypes = [
        wt.HANDLE, wt.LPCVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.LPVOID,
    ]
    _k32.CloseHandle.restype = wt.BOOL
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _k32.WaitNamedPipeW.restype = wt.BOOL
    _k32.WaitNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD]
else:
    _k32 = None

# Linux: directory holding the slippibot FIFOs. The harness points this at its
# throwaway Dolphin user dir's Pipes/ folder (boot.py); the default covers a
# user's real netplay install for ad-hoc use.
_PIPE_DIR = os.path.join(os.path.expanduser("~"), ".config", "SlippiOnline", "Pipes")


def set_pipe_dir(path):
    """(Linux) point the module at the Pipes/ dir of the Dolphin user dir in
    use. No-op on Windows, where the pipe namespace is global."""
    global _PIPE_DIR
    _PIPE_DIR = str(path)


def _fifo_path(port):
    return os.path.join(_PIPE_DIR, f"slippibot{port}")


# Windows: the prefix of the pipes THIS process's Dolphin serves. Stock Slippi
# Dolphin creates \\.\pipe\slippibot1..4 for itself whatever its config says,
# and the names are machine-wide: a second stock Dolphin gets none, and writes
# meant for it land in the first. A per-slot COPY of the exe serves names of
# its own (dolphin_lock.slot_kit); boot.py points this module at the prefix of
# the slot it holds. One Dolphin per process, as with _PIPE_DIR.
STOCK_PIPE_PREFIX = "slippibot"
_PIPE_PREFIX = STOCK_PIPE_PREFIX


def set_pipe_prefix(prefix=STOCK_PIPE_PREFIX):
    """(Windows) name the pipes this process drives: `<prefix><port>`."""
    global _PIPE_PREFIX
    _PIPE_PREFIX = str(prefix)


def pipe_prefix():
    return _PIPE_PREFIX


def pipe_path(port):
    """(Windows) the full name of this process's controller pipe `port`."""
    return "\\\\.\\pipe\\" + f"{_PIPE_PREFIX}{port}"


def ensure_fifo(port=1):
    """(Linux) create the slippibot<port> FIFO if missing. Dolphin's pipe input
    backend only picks up pipes that exist when it scans, so the harness calls
    this BEFORE booting Dolphin. Returns the fifo path. No-op on Windows."""
    if IS_WINDOWS:
        return None
    os.makedirs(_PIPE_DIR, exist_ok=True)
    path = _fifo_path(port)
    if not os.path.exists(path):
        os.mkfifo(path)
    return path


def pipe_open(port=1):
    """Try to open the slippibot<port> pipe for writing ONCE (non-blocking).
    Returns a handle/fd, or None if the pipe isn't ready this instant (Dolphin's
    input plugin not up, or mid re-arm). Used by the boot code to probe
    pipe-readiness / pick a free pipe index without creating a Pipe object. To
    actually open a pipe for driving, prefer pipe_open_wait (it rides over the
    transient gaps)."""
    if IS_WINDOWS:
        path = pipe_path(port)
        h = _k32.CreateFileW(path, GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE_VALUE:
            return None
        return h
    # Linux: O_NONBLOCK write-open of a FIFO fails with ENXIO until a reader
    # (Dolphin) has the other end open -- exactly the readiness signal we want.
    try:
        return os.open(_fifo_path(port), os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return None


def pipe_close(handle):
    """Close a handle/fd returned by pipe_open (platform-appropriate)."""
    if handle is None:
        return
    if IS_WINDOWS:
        _k32.CloseHandle(handle)
    else:
        os.close(handle)


def pipe_open_wait(port=1, timeout=12.0, alive=None, poll=0.12):
    r"""Open the slippibot<port> pipe for writing, RETRYING across the brief
    windows where the pipe is momentarily unavailable.

    Slippi Dolphin tears the pipe down and re-arms it whenever it refreshes
    controllers -- notably around game boot and stage load. A single-shot open
    that lands in that window fails (Windows: ERROR_FILE_NOT_FOUND/PIPE_BUSY;
    Linux: ENXIO, no reader yet) even though Dolphin is perfectly healthy.
    Retry with a short backoff until the pipe opens, `timeout` seconds elapse,
    or `alive()` (if given) reports Dolphin has exited. Returns a handle/fd, or
    None on timeout / dead Dolphin."""
    deadline = time.time() + timeout
    if IS_WINDOWS:
        path = pipe_path(port)
        while True:
            h = _k32.CreateFileW(path, GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
            if h and h != INVALID_HANDLE_VALUE:
                return h
            err = ctypes.get_last_error()
            if alive is not None and not alive():
                return None                      # Dolphin died -- stop waiting
            if time.time() >= deadline:
                return None
            if err == ERROR_PIPE_BUSY:
                _k32.WaitNamedPipeW(path, 500)   # block (<=0.5s) for a free instance
            else:
                time.sleep(poll)                 # not up yet -- brief backoff, retry
    else:
        path = _fifo_path(port)
        while True:
            try:
                return os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as e:
                if e.errno not in (errno.ENXIO, errno.ENOENT):
                    raise
            if alive is not None and not alive():
                return None
            if time.time() >= deadline:
                return None
            time.sleep(poll)


def pipe_in_use(port):
    """True if a slippibot<port> pipe currently has a Dolphin attached (another
    instance owns it). Used to pick a pipe index that won't collide with the
    user's own running Slippi. On Linux each harness run gets its own user dir
    (and thus its own Pipes/ namespace), so this only guards the shared default
    dir."""
    h = pipe_open(port)
    if h is None:
        return False
    pipe_close(h)
    return True


class Pipe:
    def __init__(self, port=1, open_timeout=12.0, alive=None):
        """open_timeout: seconds to keep retrying the initial open across
        Dolphin's pipe re-arm windows (see pipe_open_wait). alive: optional
        callable -> bool; when it returns False the open/reconnect bails
        immediately instead of waiting out the timeout on a dead Dolphin."""
        self.port = port
        self.path = pipe_path(port) if IS_WINDOWS else _fifo_path(port)
        self._open_timeout = open_timeout
        self._alive = alive
        self._h = None
        self._open()

    def _open(self, timeout=None):
        t = self._open_timeout if timeout is None else timeout
        h = pipe_open_wait(self.port, timeout=t, alive=self._alive)
        if h is None:
            raise OSError(f"open({self.path}) timed out (Dolphin pipe not available)")
        self._h = h

    def _write(self, data):
        if IS_WINDOWS:
            import ctypes
            import ctypes.wintypes as wt
            written = wt.DWORD(0)
            buf = ctypes.create_string_buffer(data, len(data))
            ok = _k32.WriteFile(self._h, buf, len(data), ctypes.byref(written), None)
            return bool(ok)
        try:
            os.write(self._h, data)
            return True
        except OSError:
            return False

    def frame(self, lines):
        """Write one input frame to the persistent connection (reconnect if the
        handle has gone stale, e.g. Dolphin re-armed the pipe on a controller
        refresh). The reconnect retries briefly so a re-arm mid-run doesn't drop
        the frame, but stays bounded so a genuinely dead Dolphin fails fast."""
        data = ("\n".join(lines) + "\n").encode("ascii")
        try:
            if not self._write(data):
                raise OSError("pipe write failed")
        except Exception:
            self.close()
            self._open(timeout=3.0)
            self._write(data)

    def close(self):
        if self._h is not None:
            try:
                pipe_close(self._h)
            except Exception:
                pass
            self._h = None

    # --- buttons -------------------------------------------------------------
    def press(self, btn):
        self.frame([f"PRESS {btn}", "FLUSH"])

    def release(self, btn):
        self.frame([f"RELEASE {btn}", "FLUSH"])

    def tap(self, btn, hold=0.05):
        self.press(btn)
        time.sleep(hold)
        self.release(btn)

    # --- sticks --------------------------------------------------------------
    def main(self, x, y):
        self.frame([f"SET MAIN {x:.3f} {y:.3f}", "FLUSH"])

    def c(self, x, y):
        self.frame([f"SET C {x:.3f} {y:.3f}", "FLUSH"])

    def center(self):
        self.frame(["SET MAIN 0.5 0.5", "FLUSH"])

    def tilt(self, x, y, hold):
        """Tilt the control stick, hold, then re-center."""
        self.main(x, y)
        time.sleep(hold)
        self.center()

    def neutral(self):
        lines = [f"RELEASE {b}" for b in BUTTONS]
        lines += ["SET MAIN 0.5 0.5", "SET C 0.5 0.5", "SET L 0", "SET R 0", "FLUSH"]
        self.frame(lines)
