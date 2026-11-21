"""A tool the user's AI runs over MCP that saves to the vault tells the window, which reads the vault again
(randall/mcp/window.vault_changed); and a Stage Lab save's vault picture is the whole stage from the game camera,
not the camera the AI last zoomed to (found while recording the 0.9.0 launch video, 11-19)."""
import pytest

from core import state
from randall.mcp import build_tools, randall_tools, window
from randall.recolor import stage_lab


class Socket:
    def __init__(self):
        self.sent = []

    def emit(self, event, payload):
        self.sent.append((event, payload))


@pytest.fixture
def socket(monkeypatch):
    fake = Socket()
    monkeypatch.setattr(state, 'get_socketio', lambda: fake)
    return fake


def test_only_a_reply_that_says_the_vault_changed_tells_the_window(socket):
    window.vault_changed('stage_lab', {'success': True, 'vault_changed': True})
    window.vault_changed('search_vault', {'items': []})
    window.vault_changed('download_website_mod', {'vault_changed': False})
    window.vault_changed('stage_lab', None)
    assert socket.sent == [(window.VAULT_EVENT, {'tool': 'stage_lab'})]


def test_a_window_without_a_socket_never_fails_the_call(monkeypatch):
    monkeypatch.setattr(state, 'get_socketio', lambda: None)
    window.vault_changed('stage_lab', {'vault_changed': True})

    def broken():
        raise RuntimeError('no server yet')
    monkeypatch.setattr(state, 'get_socketio', broken)
    window.vault_changed('stage_lab', {'vault_changed': True})


def test_a_randall_tool_that_saved_tells_the_window(socket, monkeypatch):
    monkeypatch.setattr(randall_tools, '_run', lambda name, arguments, app: {'success': True, 'vault_changed': True})
    result = randall_tools.call('stage_lab', {'session_id': 's', 'action': 'save', 'name': 'Ruby'}, app=None)
    assert not result['isError']
    assert socket.sent == [(window.VAULT_EVENT, {'tool': 'stage_lab'})]


def test_a_build_tool_that_imported_tells_the_window(socket, monkeypatch):
    name = next(iter(build_tools._RUN))
    monkeypatch.setitem(build_tools._RUN, name, lambda arguments, app: {'imported_count': 1, 'vault_changed': True})
    build_tools.call(name, {}, app=None)
    assert socket.sent == [(window.VAULT_EVENT, {'tool': name})]


class Viewer:
    def __init__(self, camera):
        self.camera = dict(camera)
        self.shot_from = []

    def set_camera(self, rot_x, rot_y, scale, x, y):
        self.camera = {'rotX': rot_x, 'rotY': rot_y, 'scale': scale, 'x': x, 'y': y}

    def grab_frame(self):
        self.shot_from.append(dict(self.camera))
        return b'png'


GAME = {'rotX': 10.0, 'rotY': 0.0, 'scale': 1.0, 'x': 0.0, 'y': 0.0}
UNDERSIDE = {'rotX': -80.0, 'rotY': 45.0, 'scale': 4.0, 'x': 12.0, 'y': -30.0}


def test_the_vault_picture_is_the_game_camera_and_the_ai_keeps_its_view():
    viewer = Viewer(UNDERSIDE)
    item = {'viewer': viewer, 'home_camera': dict(GAME)}
    assert stage_lab._vault_picture(item) == b'png'
    assert viewer.shot_from == [GAME]
    assert viewer.camera == UNDERSIDE


def test_a_session_still_at_its_own_camera_is_shot_as_it_is():
    viewer = Viewer(GAME)
    stage_lab._vault_picture({'viewer': viewer, 'home_camera': dict(GAME)})
    assert viewer.shot_from == [GAME] and viewer.camera == GAME
    older = Viewer(UNDERSIDE)            # an item from before the home camera was kept: as before
    stage_lab._vault_picture({'viewer': older})
    assert older.shot_from == [UNDERSIDE]
