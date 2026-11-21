"""
screenshot.py -- capture Dolphin's render output as a PNG (platform dispatch).

Windows (screenshot_win): PrintWindow(PW_RENDERFULLCONTENT) -- captures the
emulated frame even when the window is occluded/backgrounded.

Linux (screenshot_x11): XGetImage on Dolphin's own X window. Under a
compositor (every Wayland session incl. WSLg, and any composited X desktop)
each window keeps its own buffer, so this reads real frame content for
occluded/background windows too -- the same guarantee PrintWindow gives.

Public surface either way: capture_via_printwindow(pid, max_width, tries) and
capture_png(pid, max_width), both returning PNG bytes or None.
"""

import os

if os.name == "nt":
    from .screenshot_win import (  # noqa: F401
        capture_png,
        capture_via_printwindow,
        _foreground,
    )
    if os.environ.get('NUCLEUS_DOLPHIN_CAPTURE') == 'wgc':
        from .screenshot_wgc import capture as capture_via_printwindow
else:
    from .screenshot_x11 import (  # noqa: F401
        capture_png,
        capture_via_printwindow,
        _foreground,
    )


def close_capture(pid):
    if os.name == "nt" and os.environ.get("NUCLEUS_DOLPHIN_CAPTURE") == "wgc":
        from .screenshot_wgc import close
        close(pid)
