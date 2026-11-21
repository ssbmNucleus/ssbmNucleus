"""
screenshot.py -- capture Dolphin's render output as a PNG.

PRIMARY path: PrintWindow(PW_RENDERFULLCONTENT) on Dolphin's render window. This
asks Windows/DWM for the window's own pixels, so it captures the actual emulated
frame even when the window is OCCLUDED, in the BACKGROUND, or not focused -- the
exact failure mode of a plain desktop grab, and the reason the throwaway test
Dolphin (which never takes the foreground) used to screenshot whatever was on top
of it. Pure stdlib ctypes (user32 + gdi32) + Pillow; no Node/PowerShell/ffmpeg.

FALLBACK path: a desktop-region grab of the window's client rect via PIL
ImageGrab (the old behaviour) -- only if PrintWindow comes back empty/black.

Dolphin's own "Take Screenshot" hotkey and "Dump Frames" were both evaluated and
rejected: on this Ishiiruka/Slippi build hotkeys don't fire over the input pipe
(they need real window focus) and frame dumps need a runtime menu toggle + AVI
decoding -- PrintWindow needs neither.
"""

import ctypes
import ctypes.wintypes as wt
import io
import os
import time

try:
    from PIL import ImageGrab, Image  # bundled with the backend (Pillow)
except Exception:  # pragma: no cover - PIL is expected to be present
    ImageGrab = None
    Image = None

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi = ctypes.WinDLL("gdi32", use_last_error=True)

# ctypes defaults to a signed 32-bit return value. GDI handles are pointer-sized
# even when their current numeric value happens to fit in 32 bits; sign-extending
# a high-bit handle makes later capture calls fail with ERROR_DC_NOT_FOUND.
_u32.GetDC.argtypes = [wt.HWND]
_u32.GetDC.restype = wt.HDC
_u32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
_u32.ReleaseDC.restype = ctypes.c_int
_u32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
_u32.GetClientRect.restype = wt.BOOL
_u32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
_u32.PrintWindow.restype = wt.BOOL
_gdi.CreateCompatibleDC.argtypes = [wt.HDC]
_gdi.CreateCompatibleDC.restype = wt.HDC
_gdi.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
_gdi.CreateCompatibleBitmap.restype = wt.HBITMAP
_gdi.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
_gdi.SelectObject.restype = wt.HANDLE
_gdi.DeleteObject.argtypes = [wt.HANDLE]
_gdi.DeleteObject.restype = wt.BOOL
_gdi.DeleteDC.argtypes = [wt.HDC]
_gdi.DeleteDC.restype = wt.BOOL
_gdi.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                         ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
_gdi.GetDIBits.restype = ctypes.c_int

_dpi_aware = False


def _ensure_dpi_aware():
    """Make this process DPI-aware so GetClientRect returns the window's TRUE
    physical pixel size. Without this, on a scaled display (e.g. 150%/200%) the
    DPI-virtualised client rect is smaller than the render, and PrintWindow -- which
    copies 1:1 -- captures only the top-left corner. Best-effort, set once; safe in
    the headless backend (no windows of our own)."""
    global _dpi_aware
    if _dpi_aware:
        return
    _dpi_aware = True
    for attempt in (
        lambda: _u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),  # PER_MONITOR_V2
        lambda: ctypes.WinDLL("shcore").SetProcessDpiAwareness(2),        # PER_MONITOR
        lambda: _u32.SetProcessDPIAware(),                                # system-DPI
    ):
        try:
            if attempt():
                return
        except Exception:
            continue

_EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

PW_CLIENTONLY = 0x00000001        # client area only (no title bar / borders)
PW_RENDERFULLCONTENT = 0x00000002  # force a real render of GPU-composited content
# Both together give a clean client-area grab of Dolphin's render window. Either
# alone is wrong here: RENDERFULLCONTENT alone includes the title bar; CLIENTONLY
# alone returns an all-black frame for the GPU surface.
PW_FLAGS = PW_CLIENTONLY | PW_RENDERFULLCONTENT


class _POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


_u32.WindowFromPoint.argtypes = [_POINT]
_u32.WindowFromPoint.restype = wt.HWND


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def _client_rect_for_pid(pid):
    """Screen-space (left, top, right, bottom) of the CLIENT area (no title bar /
    borders) of `pid`'s RENDER window, or None.

    Goes through _render_candidates rather than "largest window owned by pid":
    the GUI shell is a comparable size, so a largest-wins search could hand back
    the toolbar+log window and the desktop-crop below would then screenshot the
    UI as if it were a game frame."""
    hwnd = next(iter(_render_candidates(pid)), None) if pid else None
    if not hwnd:
        return None
    r = wt.RECT()
    _u32.GetClientRect(hwnd, ctypes.byref(r))
    tl, br = _POINT(0, 0), _POINT(r.right, r.bottom)
    _u32.ClientToScreen(hwnd, ctypes.byref(tl))
    _u32.ClientToScreen(hwnd, ctypes.byref(br))
    return (tl.x, tl.y, br.x, br.y)


def _window_rect_for_pid(pid):
    """Return (left, top, right, bottom) of `pid`'s RENDER window, or None.
    Restricted to _render_candidates for the same reason as
    _client_rect_for_pid."""
    allowed = set(_render_candidates(pid)) if pid else set()
    best = {"area": 0, "rect": None}

    def _cb(hwnd, _lparam):
        if not _u32.IsWindowVisible(hwnd) or hwnd not in allowed:
            return True
        wpid = wt.DWORD(0)
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        r = wt.RECT()
        if not _u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return True
        w = r.right - r.left
        h = r.bottom - r.top
        if w <= 0 or h <= 0:
            return True
        area = w * h
        if area > best["area"]:
            best["area"] = area
            best["rect"] = (r.left, r.top, r.right, r.bottom)
        return True

    _u32.EnumWindows(_EnumWindowsProc(_cb), 0)
    return best["rect"]


def _foreground(pid):
    """Best-effort: bring the Dolphin window forward so the grab isn't of
    whatever is occluding it. Harmless if it fails."""
    try:
        rect = None

        def _cb(hwnd, _lparam):
            nonlocal rect
            wpid = wt.DWORD(0)
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid and _u32.IsWindowVisible(hwnd):
                _u32.SetForegroundWindow(hwnd)
                rect = True
                return False
            return True

        _u32.EnumWindows(_EnumWindowsProc(_cb), 0)
    except Exception:
        pass


def _pid_at(x, y):
    """The process that owns the window at screen point (x, y), or None."""
    hwnd = _u32.WindowFromPoint(_POINT(int(x), int(y)))
    if not hwnd:
        return None
    wpid = wt.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    return wpid.value


def _shows_only(pid, bbox, tries=3):
    """True when the middle and four inner corners of bbox all show a window of `pid`: then a screen grab of bbox
    is the game's own pixels. False when another window covers any of them (the browser or chat the user is
    reading while Dolphin sits behind it), so the grab is refused instead of returning that window dressed up as
    a game frame. Tried a few times: the focus request just made can take a moment to land."""
    left, top, right, bottom = bbox
    w, h = right - left, bottom - top
    points = [(left + w * fx, top + h * fy)
              for fx, fy in ((0.5, 0.5), (0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9))]
    for attempt in range(tries):
        if all(_pid_at(x, y) == pid for x, y in points):
            return True
        if attempt + 1 < tries:
            time.sleep(0.05)
    return False


def capture_png(pid=None, max_width=640):
    """Capture the Dolphin window (by pid) and return PNG bytes, downscaled to
    max_width so it travels cheaply over the websocket. Returns None if capture
    isn't possible (no PIL / headless)."""
    if ImageGrab is None:
        return None
    _ensure_dpi_aware()
    # Prefer the client area (no title bar / borders); fall back to the whole window.
    bbox = (_client_rect_for_pid(pid) or _window_rect_for_pid(pid)) if pid else None
    if pid and not bbox:
        # Never grab the whole desktop for a specific pid -- that returns
        # whatever happens to be on screen (other apps, the wallpaper) dressed
        # up as a game frame. No render window located => report failure.
        return None
    if bbox:
        _foreground(pid)
        if not _shows_only(pid, bbox):
            return None
    try:
        img = ImageGrab.grab(bbox=bbox) if bbox else ImageGrab.grab()
    except Exception:
        return None
    return _encode_png(img, max_width)


# PNG deflate level for capture. Level 6 (Pillow's default) spends ~55 ms of
# CPU per 1280x960 frame; level 1 spends ~10 ms for ~15 % more bytes. These are
# throwaway evidence frames on a local disk, so the trade is strictly good --
# and PNG stays LOSSLESS at every level, so no pixel a reviewer might judge is
# affected. Override with NUCLEUS_CAPTURE_PNG_LEVEL.
try:
    PNG_LEVEL = int(os.environ.get("NUCLEUS_CAPTURE_PNG_LEVEL", "1"))
except ValueError:
    PNG_LEVEL = 1


def _encode_png(img, max_width):
    """Downscale to max_width (if wider) and return PNG bytes."""
    if img.width > max_width:
        h = int(img.height * (max_width / img.width))
        img = img.resize((max_width, max(1, h)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", compress_level=PNG_LEVEL)
    return buf.getvalue()


def _pid_windows(pid):
    """All visible top-level windows owned by `pid` with a non-empty client area,
    as (hwnd, title, width, height)."""
    out = []

    def _cb(hwnd, _lparam):
        if not _u32.IsWindowVisible(hwnd):
            return True
        wpid = wt.DWORD(0)
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        r = wt.RECT()
        if not _u32.GetClientRect(hwnd, ctypes.byref(r)):
            return True
        w, h = r.right - r.left, r.bottom - r.top
        if w <= 0 or h <= 0:
            return True
        n = _u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _u32.GetWindowTextW(hwnd, buf, n + 1)
        out.append((hwnd, buf.value, w, h))
        return True

    _u32.EnumWindows(_EnumWindowsProc(_cb), 0)
    return out


def _child_count(hwnd):
    """Number of child windows `hwnd` owns."""
    n = [0]

    def _cb(_c, _l):
        n[0] += 1
        return True

    try:
        _u32.EnumChildWindows(hwnd, _EnumWindowsProc(_cb), 0)
    except Exception:
        return 0
    return n[0]


_HWND_MEMO = {}     # pid -> hwnd, revalidated on every use


def _memo_valid(pid, hwnd):
    """The memoised hwnd is only reusable while it is still a live, visible,
    non-zero-size window owned by the SAME pid. Anything else (Dolphin
    recreating its render window on a video-backend change, pid reuse) falls
    back to the full search -- the memo may never be the reason a capture
    silently targets the wrong window."""
    if not hwnd or not _u32.IsWindow(hwnd) or not _u32.IsWindowVisible(hwnd):
        return False
    wpid = wt.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    if wpid.value != pid:
        return False
    r = wt.RECT()
    if not _u32.GetClientRect(hwnd, ctypes.byref(r)):
        return False
    return (r.right - r.left) > 0 and (r.bottom - r.top) > 0


def _render_candidates(pid):
    """Dolphin's RENDER window(s) owned by `pid`, best candidate first.

    Memoised per pid: the full search is an EnumWindows over every top-level
    window on the desktop plus an EnumChildWindows per candidate, and a batch
    calls this once per capture (416 times in the 2026-07-30 run). The memo is
    revalidated against the pid every call, so it can only ever save the SEARCH,
    never change the answer.

    Discriminator is CHILDLESSNESS, not the title. On Slippi (Faster Melee
    3.6.4) BOTH the render window and the GUI are top-level 'wxWindowNR' whose
    titles start 'Faster Melee - Slippi ...' -- so a title-based filter either
    keeps both or (if it rejects "slippi"/" - ") throws away the real render
    window too. Measured live: render = 0 children, 1280x960; GUI = 14 children
    (toolbar, statusbar, log, listview), 1548x732.

    GUI windows are NEVER returned. Letting one through is what produced
    frameshot's Dolphin-UI PNGs: the render surface's PrintWindow occasionally
    comes back black, and the caller then walked on to the next candidate --
    the GUI -- and happily returned a picture of the toolbar and log panel.
    Returning nothing instead lets the caller retry inside its deadline.
    """
    memo = _HWND_MEMO.get(pid)
    if memo and _memo_valid(pid, memo):
        return [memo]
    wins = _pid_windows(pid)
    exact = [w for w in wins if w[1].strip().lower() == "dolphin"]
    if exact:
        exact.sort(key=lambda w: w[2] * w[3], reverse=True)
        out = [w[0] for w in exact]
    else:
        others = [w for w in wins if _child_count(w[0]) == 0]
        others.sort(key=lambda w: w[2] * w[3], reverse=True)
        out = [w[0] for w in others]
    if out:
        _HWND_MEMO[pid] = out[0]
    else:
        _HWND_MEMO.pop(pid, None)
    return out


def _printwindow_grab(hwnd):
    """PrintWindow(PW_RENDERFULLCONTENT) the window's client area into a PIL image,
    or None. Returns None for an all-black grab (PrintWindow occasionally yields a
    black frame for a GPU surface -- the caller then tries the next window / the
    desktop fallback)."""
    r = wt.RECT()
    if not _u32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = _u32.GetDC(hwnd)
    if not hdc:
        return None
    mdc = _gdi.CreateCompatibleDC(hdc)
    bmp = _gdi.CreateCompatibleBitmap(hdc, w, h)
    previous = None
    try:
        if not mdc or not bmp:
            return None
        previous = _gdi.SelectObject(mdc, bmp)
        if not previous or previous == wt.HANDLE(-1).value:
            previous = None
            return None
        if not _u32.PrintWindow(hwnd, mdc, PW_FLAGS):
            return None
        # GetDIBits and DeleteObject require the bitmap to be deselected.
        _gdi.SelectObject(mdc, previous)
        previous = None
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h   # top-down
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        buf = ctypes.create_string_buffer(w * h * 4)
        if not _gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0):
            return None
        img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
        if img.convert("L").getextrema()[1] == 0:   # all black -> reject
            return None
        return img
    finally:
        if previous:
            _gdi.SelectObject(mdc, previous)
        if bmp:
            _gdi.DeleteObject(bmp)
        if mdc:
            _gdi.DeleteDC(mdc)
        _u32.ReleaseDC(hwnd, hdc)


def capture_via_printwindow(pid, max_width=960, tries=10):
    """Capture Dolphin's render output via PrintWindow -- the window's OWN pixels,
    so it works while the window is occluded / backgrounded / unfocused. Returns
    PNG bytes (downscaled to max_width), or None if it couldn't get a non-black
    frame (caller falls back to the desktop grab).

    Retries because PrintWindow on an occluded GPU (flip-model) window often
    returns a BLACK frame on the first call(s) until DWM re-composites it -- a
    short retry reliably lands a real frame without needing to steal focus."""
    if Image is None or not pid:
        return None
    _ensure_dpi_aware()
    for attempt in range(max(1, tries)):
        for hwnd in _render_candidates(pid):
            try:
                img = _printwindow_grab(hwnd)   # returns None for an all-black grab
            except Exception:
                img = None
            if img is not None:
                return _encode_png(img, max_width)
        # Every candidate came back black. Drop the memo so the next attempt
        # re-runs the FULL window search: the memo must never be able to pin us
        # to a window that has stopped producing frames.
        _HWND_MEMO.pop(pid, None)
        if attempt + 1 < max(1, tries):
            time.sleep(0.06)
    return None
