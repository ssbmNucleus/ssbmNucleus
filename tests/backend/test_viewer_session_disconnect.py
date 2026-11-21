"""A viewer session whose socket reader ended is not alive (F-C-2): the lab
reopens it instead of serving the last frame forever."""
import threading

import pytest

from shared.rendering import session as viewer_session
from shared.rendering.session import ViewerSession, ViewerSessionError


class _DeadSocket:
    def recv_data(self):
        raise ConnectionResetError('socket closed')


class _Running:
    def poll(self):
        return None


def _session():
    s = ViewerSession.__new__(ViewerSession)
    s.closed = False
    s.disconnected = False
    s.ws = _DeadSocket()
    s.process = _Running()
    s._replies = {}
    s._replies_lock = threading.Lock()
    s._frame = b'old-jpeg'
    s._frame_seq = 3
    s._frame_cond = threading.Condition()
    return s


def test_a_reader_that_ends_marks_the_session_dead_and_wakes_waiters():
    s = _session()
    waiter = [threading.Event(), None]
    s._replies['frameReady'] = waiter
    s._read_loop()
    assert s.disconnected and waiter[0].is_set()
    assert s.alive() is False
    with pytest.raises(ViewerSessionError):
        s.grab_frame(fresh=1, timeout=0.5)


class _SilentSocket:
    """Accepts sends; never answers. Its reader ends when ``drop`` is set."""

    def __init__(self):
        self.sent = []
        self.drop = threading.Event()

    def send(self, data):
        self.sent.append(data)

    def recv_data(self):
        self.drop.wait(5)
        raise ConnectionResetError('socket closed')


def test_a_command_waiting_for_its_reply_fails_at_once_when_the_socket_drops():
    """F-C-2: a request in flight is woken by the reader's end and fails as a
    closed connection, instead of waiting out its whole timeout."""
    import time
    s = _session()
    s.ws = _SilentSocket()
    s._send_lock = threading.Lock()
    s._request_lock = threading.Lock()
    reader = threading.Thread(target=s._read_loop, daemon=True)
    reader.start()
    errors = []

    def ask():
        try:
            s._request({'type': 'getCamera'}, 'camera', timeout=20)
        except ViewerSessionError as e:
            errors.append(str(e))
    asker = threading.Thread(target=ask, daemon=True)
    started = time.monotonic()
    asker.start()
    while not s.ws.sent and time.monotonic() - started < 5:
        time.sleep(0.01)
    s.ws.drop.set()
    asker.join(10)
    assert not asker.is_alive()
    assert time.monotonic() - started < 10, 'woken by the drop, not the 20 s timeout'
    assert errors == ['the viewer connection closed']
    assert s._replies == {}
