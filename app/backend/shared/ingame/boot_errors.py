"""Read known graphics-failure dialogs belonging to our retained Dolphin process.

Slippi's DX11 device-creation failures use MessageBox rather than the logger.
RAM and the controller pipe can already exist while that dialog blocks boot.
This module observes it; it never dismisses dialogs or changes windows.
"""

import os


class DolphinGraphicsError(RuntimeError):
    pass


def graphics_dialog_error(title, body):
    """Recognize renderer failures, never normal game/window titles."""
    title_lower = title.lower()
    body_lower = body.lower()
    if not ("dolphin" in title_lower and "backend" in title_lower):
        return None
    if not any(word in title_lower for word in ("direct3d", "opengl", "vulkan")):
        return None
    if not any(word in body_lower for word in ("failed", "could not", "cannot", "not supported")):
        return None
    detail = " ".join(body.split())[:400]
    return (
        f"Dolphin could not start its graphics renderer ({title}): {detail} "
        "The in-game test did not run. This message alone does not establish "
        "that the graphics card is unsupported. Check the video backend in "
        "Slippi's graphics settings, then retry."
    )


def read_graphics_failure(pid):
    if os.name != "nt" or not pid:
        return None
    return next((error for title, body in _owned_dialogs(pid)
                 if (error := graphics_dialog_error(title, body))), None)


def _owned_dialogs(pid):
    # Kept lazy so importing boot on other platforms has no Win32 dependency.
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wt.LPARAM]
    user32.EnumChildWindows.argtypes = [wt.HWND, callback_type, wt.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.SendMessageTimeoutW.argtypes = [
        wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wt.LPARAM
    dialogs = []

    def window_text(hwnd, class_name=False):
        buf = ctypes.create_unicode_buffer(512)
        getter = user32.GetClassNameW if class_name else user32.GetWindowTextW
        getter(hwnd, buf, len(buf))
        return buf.value

    def belongs(hwnd):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        return owner.value == pid

    def visit(hwnd, _):
        if len(dialogs) >= 4:
            return False
        if not belongs(hwnd) or not user32.IsWindowVisible(hwnd):
            return True
        if window_text(hwnd, class_name=True) != "#32770":
            return True
        title = window_text(hwnd)
        if "backend" not in title.lower() or "dolphin" not in title.lower():
            return True
        parts = []

        def child(child_hwnd, _):
            if len(parts) >= 8:
                return False
            if not belongs(child_hwnd) or window_text(child_hwnd, class_name=True) != "Static":
                return True
            buf = ctypes.create_unicode_buffer(1024)
            result = ctypes.c_size_t()
            # Cross-process control text needs WM_GETTEXT; bound a hung UI's wait.
            if user32.SendMessageTimeoutW(child_hwnd, 0x000D, len(buf),
                                          ctypes.addressof(buf), 0x0002, 50,
                                          ctypes.byref(result)):
                parts.append(buf.value)
            else:
                parts.append("")
            return True

        user32.EnumChildWindows(hwnd, callback_type(child), 0)
        dialogs.append((title, " ".join(parts)))
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return dialogs
