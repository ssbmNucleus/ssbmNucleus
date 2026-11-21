#!/usr/bin/env python3
"""Desktop screen grab for states the renderer cannot screenshot itself:
the embedded Dolphin window, the browser's "open link" prompt, SmartScreen.

    grab.py <out.png> --bbox X Y W H          # screen pixels
    grab.py <out.png> --window "<title substring>" [--pad N]

--window finds a top-level window whose title contains the substring (Windows
only) and grabs its rectangle. Prints the JSON bbox used.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time

from PIL import ImageGrab


def find_window(title_part: str, timeout: float = 15.0):
    if sys.platform != "win32":
        sys.exit("--window is Windows-only")
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if not n:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part.lower() in buf.value.lower():
                rect = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
                found.append(hwnd)
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        if found:
            import ctypes.wintypes as wt
            r = wt.RECT()
            user32.GetWindowRect(found[0], ctypes.byref(r))
            return found[0], (r.left, r.top, r.right - r.left, r.bottom - r.top)
        time.sleep(0.4)
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--bbox", nargs=4, type=int)
    ap.add_argument("--window")
    ap.add_argument("--pad", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=15.0)
    a = ap.parse_args()
    if a.window:
        hwnd, box = find_window(a.window, a.timeout)
        if not box:
            sys.exit(f"[grab] no window titled *{a.window}*")
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.4)
        except Exception:
            pass
        x, y, w, h = box
    elif a.bbox:
        x, y, w, h = a.bbox
    else:
        sys.exit("need --bbox or --window")
    x, y, w, h = x - a.pad, y - a.pad, w + 2 * a.pad, h + 2 * a.pad
    im = ImageGrab.grab(bbox=(max(0, x), max(0, y), x + w, y + h), all_screens=True)
    im.save(a.out)
    print(json.dumps({"x": x, "y": y, "w": w, "h": h, "size": im.size}))


if __name__ == "__main__":
    main()
