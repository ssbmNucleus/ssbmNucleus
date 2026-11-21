"""Opt-in GPU window capture for native QA; targets one verified render HWND.

PrintWindow can succeed yet return black RGB on hardware-accelerated windows.
Graphics Capture receives that window's compositor surface without focusing it
or reading the desktop. Requires the optional windows-capture package.
"""
import ctypes
import threading
import time

from PIL import Image

from . import screenshot_win as win


def client_box(hwnd):
    """The render client area inside the window's compositor bounds.

    Graphics Capture (and Electron's window capture, which uses it) delivers
    the DWM extended frame bounds: title bar and borders included. Returns
    (x, y, width, height, frame_width, frame_height) in physical pixels, the
    client rectangle measured from that frame's top-left corner.
    """
    bounds=win.wt.RECT()
    dwm=ctypes.WinDLL('dwmapi',use_last_error=True)
    dwm.DwmGetWindowAttribute.argtypes=[win.wt.HWND,win.wt.DWORD,ctypes.c_void_p,win.wt.DWORD]
    dwm.DwmGetWindowAttribute.restype=ctypes.c_long
    if dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(bounds),ctypes.sizeof(bounds)):
        raise RuntimeError('No compositor window bounds')
    rect=win.wt.RECT()
    if not win._u32.GetClientRect(hwnd,ctypes.byref(rect)):
        raise RuntimeError('No render client rectangle')
    point=win.wt.POINT(0,0)
    win._u32.ClientToScreen.argtypes=[win.wt.HWND,ctypes.POINTER(win.wt.POINT)]
    win._u32.ClientToScreen.restype=win.wt.BOOL
    if not win._u32.ClientToScreen(hwnd,ctypes.byref(point)):
        raise RuntimeError('No render client origin')
    return (point.x-bounds.left,point.y-bounds.top,rect.right-rect.left,rect.bottom-rect.top,
            bounds.right-bounds.left,bounds.bottom-bounds.top)


def client_crop(hwnd, image):
    x,y,width,height,frame_width,frame_height=client_box(hwnd)
    if image.size!=(frame_width,frame_height):
        raise RuntimeError('Captured surface differs from verified window bounds')
    if x<0 or y<0 or x+width>image.width or y+height>image.height:
        raise RuntimeError('Render client lies outside captured window')
    return image.crop((x,y,x+width,y+height))


class WindowCapture:
    """One compositor subscription for the render window's entire lifetime."""
    def __init__(self,pid,hwnd):
        from windows_capture import WindowsCapture
        self.pid,self.hwnd=pid,hwnd
        self.condition=threading.Condition()
        self.serial=0
        self.timespan=0
        self.image=None
        self.closed=False
        self.session=WindowsCapture(cursor_capture=False,draw_border=False,
                                   secondary_window=False,monitor_index=None,window_hwnd=hwnd)
        @self.session.event
        def on_frame_arrived(frame,control):
            image=Image.fromarray(frame.frame_buffer[:,:,[2,1,0]].copy())
            with self.condition:
                self.image=image
                self.serial+=1
                self.timespan=frame.timespan
                self.condition.notify_all()
        @self.session.event
        def on_closed():
            with self.condition:
                self.closed=True
                self.condition.notify_all()
        self.control=self.session.start_free_threaded()

    def next_frame(self):
        with self.condition:
            # WinRT SystemRelativeTime is the compositor QPC in 100 ns units.
            # A newly delivered callback can still contain a queued OLD surface.
            requested=time.perf_counter_ns()//100
            if not self.condition.wait_for(lambda:self.timespan>requested or self.closed,timeout=3):
                return None
            return self.image.copy() if self.timespan>requested else None

    def close(self):
        if not self.control.is_finished():self.control.stop()
        self.control.wait()


_sessions={}


def close(pid):
    session=_sessions.pop(pid,None)
    if session is not None:session.close()


def capture(pid,max_width=960,tries=10):
    win._ensure_dpi_aware()
    candidates=win._render_candidates(pid)
    if len(candidates)!=1:return None
    hwnd=candidates[0]
    if not win._memo_valid(pid,hwnd):return None
    session=_sessions.get(pid)
    if session is not None and (session.hwnd!=hwnd or session.closed):
        close(pid);session=None
    if session is None:
        session=WindowCapture(pid,hwnd)
        _sessions[pid]=session
    image=session.next_frame()
    if image is None or not win._memo_valid(pid,hwnd):return None
    image=client_crop(hwnd,image)
    if image.convert('L').getextrema()[1]==0:return None
    return win._encode_png(image,max_width)
