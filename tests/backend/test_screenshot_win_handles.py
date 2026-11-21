"""64-bit GDI ownership regression; no game, focus change, or desktop grab."""
import ctypes
import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows capture API')


def test_capture_uses_pointer_sized_handles_and_deselects_bitmap(monkeypatch):
    from shared.ingame import screenshot_win as shot
    assert shot._u32.GetDC.restype is shot.wt.HDC
    assert shot._gdi.CreateCompatibleDC.restype is shot.wt.HDC
    assert shot._gdi.CreateCompatibleBitmap.restype is shot.wt.HBITMAP
    calls=[]
    dc, memory, bitmap, old = 0xF0000011,0xE0000022,0xD0000033,0xC0000044
    selected=[old]
    def rect(hwnd, pointer):
        value=ctypes.cast(pointer,ctypes.POINTER(shot.wt.RECT)).contents
        value.right=value.bottom=2
        return 1
    def select(handle, obj):
        assert handle==memory
        prior=selected[0];selected[0]=obj;calls.append(('select',obj));return prior
    def bits(handle,obj,start,height,buffer,*args):
        assert handle==memory and obj==bitmap and selected[0]!=bitmap
        ctypes.memset(buffer,127,16)
        return height
    def delete(obj):
        assert selected[0]!=obj
        calls.append(('delete',obj));return 1
    monkeypatch.setattr(shot,'_u32',SimpleNamespace(GetClientRect=rect,GetDC=lambda _:dc,
                        PrintWindow=lambda hwnd,handle,flags:handle==memory,
                        ReleaseDC=lambda hwnd,handle:calls.append(('release',handle))))
    monkeypatch.setattr(shot,'_gdi',SimpleNamespace(CreateCompatibleDC=lambda h:memory if h==dc else None,
                        CreateCompatibleBitmap=lambda h,w,t:bitmap if h==dc else None,
                        SelectObject=select,GetDIBits=bits,DeleteObject=delete,
                        DeleteDC=lambda h:calls.append(('delete_dc',h))))
    assert shot._printwindow_grab(123).size==(2,2)
    assert calls==[('select',bitmap),('select',old),('delete',bitmap),('delete_dc',memory),('release',dc)]


def test_fresh_capture_waits_for_new_render_between_black_reads(monkeypatch):
    from devtools import frameshot as fs
    calls=[]
    images=iter([None,None,b'new-png'])
    def capture(*args,**kwargs):
        assert kwargs['tries']==1
        calls.append('capture');return next(images)
    monkeypatch.setattr(fs.shot,'capture_via_printwindow',capture)
    monkeypatch.setattr(fs.framestep,'wait_render_frames',lambda *a,**kw:calls.append('render') or 1)
    assert fs.Fresh().grab(object(),SimpleNamespace(pid=1))==(b'new-png',True)
    assert calls==['render','capture','render','capture','render','capture']


def test_black_capture_still_fails_at_deadline(monkeypatch):
    from devtools import frameshot as fs
    monkeypatch.setattr(fs.shot,'capture_via_printwindow',lambda *a,**kw:None)
    monkeypatch.setattr(fs.framestep,'wait_render_frames',lambda *a,**kw:1)
    assert fs.Fresh().grab(object(),SimpleNamespace(pid=1),deadline=0)==(None,False)


def test_failed_capture_teardown_still_releases_owned_dolphin(monkeypatch):
    from devtools import frameshot as fs
    calls=[]
    session=fs.Session.__new__(fs.Session)
    session.boot=SimpleNamespace(pid=123,run_dir='owned',terminate=lambda:calls.append('terminate'))
    session.p=SimpleNamespace(close=lambda:calls.append('pad'))
    session.log=lambda message:calls.append(message)
    def failed(pid):raise RuntimeError('capture teardown')
    monkeypatch.setattr(fs.shot,'close_capture',failed)
    assert session.close(keep=True)=='owned'
    assert 'pad' in calls and 'terminate' in calls


def test_wgc_waits_for_compositor_timestamp_not_callback_delivery(monkeypatch):
    import threading
    import time
    from PIL import Image
    from shared.ingame import screenshot_wgc
    capture=screenshot_wgc.WindowCapture.__new__(screenshot_wgc.WindowCapture)
    capture.condition=threading.Condition();capture.closed=False
    capture.timespan=0;capture.image=Image.new('RGB',(2,2),'red')
    monkeypatch.setattr(screenshot_wgc.time,'perf_counter_ns',lambda:10000)
    delivered=threading.Event()
    def frames():
        time.sleep(.01)
        with capture.condition:
            capture.timespan=99;capture.condition.notify_all()
        delivered.set()
        time.sleep(.02)
        with capture.condition:
            capture.image=Image.new('RGB',(2,2),'green')
            capture.timespan=101;capture.condition.notify_all()
    thread=threading.Thread(target=frames);thread.start()
    result=capture.next_frame();thread.join()
    assert delivered.is_set() and result.getpixel((0,0))==(0,128,0)


def test_a_screen_grab_is_refused_when_another_window_covers_the_game(monkeypatch):
    """The focus fallback grabs a screen area: if Dolphin is behind another app (a browser), that area shows the
    other app, which must never come back as a game frame."""
    from PIL import Image
    from shared.ingame import screenshot_win as shot
    grabbed = []
    monkeypatch.setattr(shot, '_ensure_dpi_aware', lambda: None)
    monkeypatch.setattr(shot, '_client_rect_for_pid', lambda pid: (100, 100, 740, 580))
    monkeypatch.setattr(shot, '_foreground', lambda pid: None)
    monkeypatch.setattr(shot.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(shot, 'ImageGrab', SimpleNamespace(
        grab=lambda bbox=None: grabbed.append(bbox) or Image.new('RGB', (640, 480))))
    monkeypatch.setattr(shot, '_pid_at', lambda x, y: 4242 if x < 600 else 999)    # a window over the right side
    assert shot.capture_png(4242) is None and grabbed == []
    monkeypatch.setattr(shot, '_pid_at', lambda x, y: 4242)
    assert shot.capture_png(4242)[:8] == b'\x89PNG\r\n\x1a\n' and grabbed == [(100, 100, 740, 580)]
