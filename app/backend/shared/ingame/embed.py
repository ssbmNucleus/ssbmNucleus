"""Owned Dolphin window discovery and presentation.

Test in Game and Watch replay capture the retained subprocess's exact render
HWND into an Electron video. Only after its first decoded frame may its visible
native windows be moved behind the app; capture never resizes or parks them.
Slippi batch mode can still show a separate GUI shell, which is not a render
target. For the playback Dolphin that shell carries the seek bar, so its
registration asks for it back on Pop out (`show_gui`). The older
physical-pixel overlay helpers remain for parking a dying window and for a
renderer without the Electron capture.
"""

import os
import threading
import uuid

_lock = threading.Lock()
_active_pid = None
_active_process = None
_active_session = None
_active_show_gui = False
# hwnd -> (left, top) before 'behind' first moved it, for this session only:
# a `show_gui` Pop out puts the windows back where Dolphin opened them
_original_pos = {}

if os.name == "nt":
    import ctypes
    from ctypes import wintypes as wt

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _u32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    _u32.GetWindowLongW.restype = ctypes.c_long
    _u32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
    _u32.SetWindowLongW.restype = ctypes.c_long
    _u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _u32.SetWindowPos.restype = wt.BOOL
    _u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    _u32.GetWindowRect.restype = wt.BOOL
    _u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wt.DWORD
    _u32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _u32.GetClassNameW.restype = ctypes.c_int

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
_CHROME = WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOMOVE = 0x0002


def set_active(pid, process=None, show_gui=False):
    """Called by DolphinBoot.launch() and the replay playback launch: this pid's
    render window is the one the frontend may embed. `show_gui`: Pop out also
    brings back the process's GUI shell (the playback seek bar)."""
    global _active_pid, _active_process, _active_session, _active_show_gui
    with _lock:
        _active_pid = pid
        _active_process = process
        _active_session = uuid.uuid4().hex
        _active_show_gui = bool(show_gui)
        _original_pos.clear()


def clear_active(pid=None):
    """Forget the active pid (on terminate/cleanup). With a pid, only clears if
    it still matches -- a stale cleanup must not unregister a newer boot."""
    global _active_pid, _active_process, _active_session, _active_show_gui
    with _lock:
        if pid is None or _active_pid == pid:
            _active_pid = None
            _active_process = None
            _active_session = None
            _active_show_gui = False
            _original_pos.clear()


def get_active():
    with _lock:
        return _active_pid


def session_for(pid):
    """The capture session registered for `pid`, or None when another Dolphin
    (or none) holds the slot. No window discovery: cheap enough for a status poll."""
    with _lock:
        return _active_session if pid and _active_pid == pid else None


def _render_hwnd(pid):
    # screenshot.py became a platform dispatcher in the Linux port and only
    # re-exports the public capture functions — the window heuristics live in
    # screenshot_win. Embedding is Windows-only, so import it directly.
    from . import screenshot_win as _ss
    _ss._ensure_dpi_aware()
    cands = _ss._render_candidates(pid)
    return cands[0] if cands else None


def _strip_chrome(hwnd):
    style = _u32.GetWindowLongW(hwnd, GWL_STYLE)
    bare = style & ~_CHROME
    if bare != style:
        _u32.SetWindowLongW(hwnd, GWL_STYLE, bare)
        _u32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                          SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE
                          | SWP_NOZORDER | SWP_NOACTIVATE)


def position_pid(pid, x, y, width, height):
    """Pin `pid`'s Dolphin render window to the given PHYSICAL-pixel screen
    rect, borderless, above the app, without activating it. Returns
    {"found": bool} -- False until the render window exists (the frontend
    keeps polling while a build/boot is still in progress). Works for any
    Dolphin-family process (test engine, Slippi playback)."""
    if os.name != "nt" or not pid:
        return {"found": False}
    hwnd = _render_hwnd(pid)
    if not hwnd:
        return {"found": False}
    _strip_chrome(hwnd)
    _u32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), int(width), int(height),
                      SWP_NOACTIVATE | SWP_SHOWWINDOW)
    return {"found": True}


def position(x, y, width, height):
    """position_pid for the active TEST Dolphin (see set_active)."""
    return position_pid(get_active(), x, y, width, height)


def park_pid(pid):
    """Move `pid`'s Dolphin render window offscreen (placeholder hidden /
    panel unmounted / about to be terminated -- a dying GL window flashes
    black wherever it sits, so callers park before killing). Stays
    visible-but-offscreen so PrintWindow screenshots keep working."""
    if os.name != "nt" or not pid:
        return {"found": False}
    hwnd = _render_hwnd(pid)
    if not hwnd:
        return {"found": False}
    _u32.SetWindowPos(hwnd, HWND_NOTOPMOST, -32000, -32000, 0, 0,
                      SWP_NOSIZE | SWP_NOACTIVATE)
    return {"found": True}


def park(pid=None):
    """park_pid, defaulting to the active TEST Dolphin."""
    return park_pid(pid if pid is not None else get_active())


def popout_pid(pid):
    """Detach `pid`'s Dolphin render window from the embed: give it back its
    normal chrome (title bar, sizing frame), drop always-on-top, and bring it
    forward as a regular desktop window the user can move/resize/close."""
    if os.name != "nt" or not pid:
        return {"found": False}
    hwnd = _render_hwnd(pid)
    if not hwnd:
        return {"found": False}
    return _popout_hwnd(hwnd)


def _raise(hwnd):
    """In front of every normal window, the foreground app's too, without
    activating it: a topmost round trip. A plain SetWindowPos cannot pass the
    foreground window, and Windows may refuse SetForegroundWindow from here."""
    _u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    _u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def _popout_hwnd(hwnd):
    """Restore one previously validated render handle, without rediscovery."""
    style = _u32.GetWindowLongW(hwnd, GWL_STYLE)
    _u32.SetWindowLongW(hwnd, GWL_STYLE, style | _CHROME)
    _raise(hwnd)
    # if it was parked offscreen, bring it somewhere visible first
    r = wt.RECT()
    parked = _u32.GetWindowRect(hwnd, ctypes.byref(r)) and r.left <= -30000
    if parked:
        _u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 120, 120, 968, 758,
                          SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    else:
        _u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                          SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE
                          | SWP_SHOWWINDOW)
    try:
        _u32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return {"found": True}


def _capture_hwnd(pid):
    """Use the existing render discovery, excluding dialogs and the GUI shell."""
    from . import screenshot_win as screenshots
    hwnd = _render_hwnd(pid)
    if not hwnd or not screenshots._memo_valid(pid, hwnd) or screenshots._child_count(hwnd):
        return None
    class_name = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, class_name, len(class_name))
    if class_name.value == '#32770':
        return None
    return hwnd


def capture_target():
    """Read-only identity of the retained test subprocess's current render HWND."""
    if os.name != 'nt':
        return {'supported': False, 'found': False}
    with _lock:
        pid, process, session = _active_pid, _active_process, _active_session
    # A PID alone is insufficient: after it exits Windows may reuse that PID.
    if process is None or process.pid != pid or process.poll() is not None:
        return {'supported': True, 'found': False}
    hwnd = _capture_hwnd(pid)
    with _lock:
        if process is not _active_process or session != _active_session or process.poll() is not None:
            return {'supported': True, 'found': False}
    if not hwnd:
        return {'supported': True, 'found': False}
    return {'supported': True, 'found': True, 'pid': pid,
            'sessionId': session, 'hwnd': str(hwnd), 'client': _client_geometry(hwnd)}


def _client_geometry(hwnd):
    """Where the game sits inside the captured window, so a preview can leave
    Dolphin's title bar and borders out. Read-only, presentation only: None
    when it cannot be measured (the preview then shows the whole window)."""
    try:
        from .screenshot_wgc import client_box
        x, y, width, height, frame_width, frame_height = client_box(hwnd)
    except Exception:
        return None
    if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > frame_width or y + height > frame_height:
        return None
    return {'x': x, 'y': y, 'width': width, 'height': height,
            'frameWidth': frame_width, 'frameHeight': frame_height}


def present_capture(session_id, hwnd, mode, owner_hwnd=None, owner_pid=None):
    """After a captured frame arrives, keep only our windows behind the app.

    No resize, offscreen parking or minimization: legacy Dolphin must keep
    rendering its GPU surface. Error dialogs remain visible for diagnosis.
    """
    target = capture_target()
    if not target.get('found') or target['sessionId'] != session_id or target['hwnd'] != str(hwnd):
        return {'found': False}
    with _lock:
        process = _active_process
        if (process is None or process.pid != target['pid'] or
                _active_session != session_id or process.poll() is not None or
                _capture_hwnd(target['pid']) != int(target['hwnd'])):
            return {'found': False}
        return _present_capture_target(target, mode, owner_hwnd, owner_pid)


def _gui_shells(pid, render):
    """The same-process GUI frames beside the render window (Slippi's batch-mode
    CFrame: toolbar, empty render area, seek bar). Never error dialogs."""
    from . import screenshot_win as screenshots
    for gui, _title, _width, _height in screenshots._pid_windows(pid):
        if gui == render or not screenshots._child_count(gui):
            continue
        class_name = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(gui, class_name, len(class_name))
        if class_name.value != '#32770':
            yield gui


def _remember(hwnd):
    """Where `hwnd` sat before 'behind' first moved it (kept for the session)."""
    if hwnd in _original_pos:
        return
    rect = wt.RECT()
    if _u32.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.left > -30000:
        _original_pos[hwnd] = (rect.left, rect.top)


def _restore(hwnd):
    pos = _original_pos.get(hwnd)
    if pos:
        _u32.SetWindowPos(hwnd, None, pos[0], pos[1], 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def _present_capture_target(target, mode, owner_hwnd, owner_pid):
    # The active-session lock is retained through all presentation mutations.
    if mode == 'separate':
        render = int(target['hwnd'])
        if not _active_show_gui:
            return _popout_hwnd(render)
        # The user's real Dolphin: every window back where Dolphin opened it,
        # in front of the app, the GUI shell with the seek bar first and the
        # game on top of it.
        guis = list(_gui_shells(target['pid'], render))
        for hwnd in (render, *guis):
            _restore(hwnd)
        for gui in guis:
            _raise(gui)
        return _popout_hwnd(render)
    if mode != 'behind':
        raise ValueError('Unknown capture presentation mode')
    try:
        owner = int(owner_hwnd)
        expected_owner = int(owner_pid)
    except (TypeError, ValueError):
        raise ValueError('A valid owner window is required')
    actual_owner = wt.DWORD()
    if not owner or not _u32.GetWindowThreadProcessId(owner, ctypes.byref(actual_owner)) or actual_owner.value != expected_owner:
        return {'found': False}
    rect = wt.RECT()
    if not _u32.GetWindowRect(owner, ctypes.byref(rect)) or rect.left <= -30000:
        return {'found': True}  # Main app is minimized; don't move Dolphin offscreen.
    render = int(target['hwnd'])
    _remember(render)
    # Remove any legacy topmost bit before placing the render behind main.
    _u32.SetWindowPos(render, HWND_NOTOPMOST, 0, 0, 0, 0,
                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    ok = _u32.SetWindowPos(render, owner, rect.left + 20, rect.top + 40, 0, 0,
                           SWP_NOSIZE | SWP_NOACTIVATE)
    # -b exits when the game closes; it does not suppress every Slippi CFrame.
    # Keep that same-process GUI behind the render too, never hide error dialogs.
    for gui in _gui_shells(target['pid'], render):
        _remember(gui)
        _u32.SetWindowPos(gui, HWND_NOTOPMOST, 0, 0, 0, 0,
                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        _u32.SetWindowPos(gui, render, rect.left + 20, rect.top + 40, 0, 0,
                          SWP_NOSIZE | SWP_NOACTIVATE)
    return {'found': bool(ok)}
