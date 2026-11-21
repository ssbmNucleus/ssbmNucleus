"""
screenshot_x11.py -- Linux implementation of the Dolphin window capture.

Grabs the pixels of Dolphin's own X11 window (found by _NET_WM_PID) with
XGetImage. Under a compositor -- every Wayland session including WSLg, and any
composited X desktop -- each window keeps its own backing buffer, so this
returns real frame content even when the window is occluded or in the
background, matching the PrintWindow guarantee the Windows path relies on.
Pure ctypes against libX11; no python-xlib, no new dependencies.

The function names mirror screenshot_win so the dispatcher can re-export
either module unchanged: capture_via_printwindow is the primary path (the
name is historical), capture_png the fallback (here: the same X grab, minus
the black-frame retry loop).
"""

import ctypes
import io
import os
import sys
import time

try:
    from PIL import Image  # bundled with the backend (Pillow)
except Exception:  # pragma: no cover - PIL is expected to be present
    Image = None

# ---------------------------------------------------------------------------
# libX11 via ctypes
# ---------------------------------------------------------------------------
try:
    # X11 is Linux-only; on macOS this raises at import (see melee_mem).
    _x11 = ctypes.CDLL("libX11.so.6") if sys.platform.startswith("linux") else None
except OSError:  # no X libs (pure headless server) -- captures just return None
    _x11 = None

_Atom = ctypes.c_ulong
_Window = ctypes.c_ulong

if _x11 is not None:
    _x11.XOpenDisplay.restype = ctypes.c_void_p
    _x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    _x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    _x11.XDefaultRootWindow.restype = _Window
    _x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    _x11.XInternAtom.restype = _Atom
    _x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    _x11.XQueryTree.restype = ctypes.c_int
    _x11.XQueryTree.argtypes = [
        ctypes.c_void_p, _Window, ctypes.POINTER(_Window), ctypes.POINTER(_Window),
        ctypes.POINTER(ctypes.POINTER(_Window)), ctypes.POINTER(ctypes.c_uint),
    ]
    _x11.XFree.argtypes = [ctypes.c_void_p]
    _x11.XGetWindowProperty.restype = ctypes.c_int
    _x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, _Window, _Atom, ctypes.c_long, ctypes.c_long,
        ctypes.c_int, _Atom, ctypes.POINTER(_Atom), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int),
        ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p), ("root", _Window),
        ("c_class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


class _XImage(ctypes.Structure):
    pass


_XImage._fields_ = [
    ("width", ctypes.c_int), ("height", ctypes.c_int),
    ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
    ("data", ctypes.c_void_p),
    ("byte_order", ctypes.c_int), ("bitmap_unit", ctypes.c_int),
    ("bitmap_bit_order", ctypes.c_int), ("bitmap_pad", ctypes.c_int),
    ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int),
    ("bits_per_pixel", ctypes.c_int),
    ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong),
    ("blue_mask", ctypes.c_ulong),
    ("obdata", ctypes.c_void_p),
    # struct funcs (function-pointer table)
    ("f_create_image", ctypes.c_void_p),
    ("f_destroy_image", ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_XImage))),
    ("f_get_pixel", ctypes.c_void_p),
    ("f_put_pixel", ctypes.c_void_p),
    ("f_sub_image", ctypes.c_void_p),
    ("f_add_pixel", ctypes.c_void_p),
]

if _x11 is not None:
    _x11.XGetWindowAttributes.restype = ctypes.c_int
    _x11.XGetWindowAttributes.argtypes = [
        ctypes.c_void_p, _Window, ctypes.POINTER(_XWindowAttributes)]
    _x11.XGetImage.restype = ctypes.POINTER(_XImage)
    _x11.XGetImage.argtypes = [
        ctypes.c_void_p, _Window, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int,
    ]

_ZPixmap = 2
_AllPlanes = ctypes.c_ulong(-1).value
_IsViewable = 2


def _window_pid(dpy, win, net_wm_pid):
    actual_type = _Atom(0)
    actual_format = ctypes.c_int(0)
    nitems = ctypes.c_ulong(0)
    bytes_after = ctypes.c_ulong(0)
    prop = ctypes.POINTER(ctypes.c_ubyte)()
    status = _x11.XGetWindowProperty(
        dpy, win, net_wm_pid, 0, 1, 0, 6,  # XA_CARDINAL == 6
        ctypes.byref(actual_type), ctypes.byref(actual_format),
        ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop))
    if status != 0 or not prop or nitems.value < 1:
        return None
    pid = ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong)).contents.value
    _x11.XFree(prop)
    return int(pid)


def _iter_tree(dpy, win, out, depth=0):
    if depth > 12:
        return
    root = _Window(0)
    parent = _Window(0)
    children = ctypes.POINTER(_Window)()
    n = ctypes.c_uint(0)
    if not _x11.XQueryTree(dpy, win, ctypes.byref(root), ctypes.byref(parent),
                           ctypes.byref(children), ctypes.byref(n)):
        return
    try:
        for i in range(n.value):
            child = children[i]
            out.append(child)
            _iter_tree(dpy, child, out, depth + 1)
    finally:
        if children:
            _x11.XFree(children)


def _render_window_for_pid(dpy, pid):
    """The largest viewable window belonging to `pid` -- Dolphin's render
    window dwarfs its menus/dialogs, so area is a reliable discriminator."""
    net_wm_pid = _x11.XInternAtom(dpy, b"_NET_WM_PID", 1)
    if not net_wm_pid:
        return None
    wins = []
    _iter_tree(dpy, _x11.XDefaultRootWindow(dpy), wins)
    best, best_area = None, 0
    for w in wins:
        if _window_pid(dpy, w, net_wm_pid) != pid:
            continue
        attrs = _XWindowAttributes()
        if not _x11.XGetWindowAttributes(dpy, w, ctypes.byref(attrs)):
            continue
        if attrs.map_state != _IsViewable:
            continue
        area = attrs.width * attrs.height
        if attrs.width >= 160 and attrs.height >= 120 and area > best_area:
            best, best_area = w, area
    return best


def _grab_window(dpy, win):
    """XGetImage the window -> PIL Image, or None."""
    attrs = _XWindowAttributes()
    if not _x11.XGetWindowAttributes(dpy, win, ctypes.byref(attrs)):
        return None
    w, h = attrs.width, attrs.height
    if w <= 0 or h <= 0:
        return None
    img_p = _x11.XGetImage(dpy, win, 0, 0, w, h, _AllPlanes, _ZPixmap)
    if not img_p:
        return None
    try:
        img = img_p.contents
        if img.bits_per_pixel != 32 or not img.data:
            return None
        stride = img.bytes_per_line
        raw = ctypes.string_at(img.data, stride * h)
        return Image.frombuffer("RGB", (w, h), raw, "raw", "BGRX", stride, 1)
    finally:
        try:
            img_p.contents.f_destroy_image(img_p)
        except Exception:
            pass


def _looks_blank(img):
    """True for the all-black (or single-color) frames a not-yet-rendering
    window returns; mirrors the Windows path's black-frame rejection."""
    extrema = img.convert("L").getextrema()
    return extrema[1] - extrema[0] < 8


def _encode_png(img, max_width):
    if max_width and img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _capture_once(pid):
    if _x11 is None or Image is None:
        return None
    dpy = _x11.XOpenDisplay(None)
    if not dpy:
        return None
    try:
        win = _render_window_for_pid(dpy, int(pid))
        if win is None:
            return None
        return _grab_window(dpy, win)
    finally:
        _x11.XCloseDisplay(dpy)


def capture_via_printwindow(pid, max_width=960, tries=10):
    """Primary capture: X grab of Dolphin's render window, retrying past the
    all-black frames a window shows before its first real present. Returns PNG
    bytes or None. (Name kept from the Windows module for the dispatcher.)"""
    last = None
    for _ in range(max(1, tries)):
        img = _capture_once(pid)
        if img is not None:
            last = img
            if not _looks_blank(img):
                return _encode_png(img, max_width)
        time.sleep(0.15)
    return _encode_png(last, max_width) if last is not None else None


def capture_png(pid=None, max_width=640):
    """Fallback capture: single X grab, no blank-frame retry."""
    img = _capture_once(pid)
    if img is None:
        return None
    return _encode_png(img, max_width)


def _foreground(pid):  # parity stub; X11 focus games are not needed here
    return False
