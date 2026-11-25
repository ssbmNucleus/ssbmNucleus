"""The request-path gate (core/path_safety.local_path): every path a request or a tool argument names is a plain
absolute path on this computer before anything opens or runs it.

The 11-22 review found ``\\??\\UNC\\host@SSL\\DavWWWRoot\\x.iso`` passing ``is_network_path`` (and not looking
absolute to pathlib) while Windows' CreateFileW opens it as a WebDAV share: an AI tool argument reached it through
the in-game test's vanilla ISO path. The reviewer's inputs are the cases below.
"""
import json
import os
import subprocess
import sys

import pytest

from tests.gated import needs
from tests.paths import BACKEND

sys.path.insert(0, str(BACKEND))

from core import path_safety  # noqa: E402
from core.path_safety import NotLocalPath, is_network_path, local_path, request_path_refusal  # noqa: E402

B = chr(92)

#: The reviewer's inputs (assistant/t_path.py, me/t_ps.py, assistant/t_ntprefix.py) and their mixed-slash forms.
NETWORK = [
    B * 2 + 'host' + B + 'share' + B + 'x.zip',
    '//host/share/x.zip',
    B * 2 + '?' + B + 'UNC' + B + 'host' + B + 'share' + B + 'x.zip',
    B + '??' + B + 'UNC' + B + 'host' + B + 'share' + B + 'x.zip',
    B + '??' + B + 'UNC' + B + 'host@SSL' + B + 'DavWWWRoot' + B + 'x.iso',
    B + '??' + B + 'C:' + B + 'Windows' + B + 'win.ini',
    B * 2 + '.' + B + 'pipe' + B + 'x',
    B * 2 + '.' + B + 'C:' + B + 'x',
    B * 2 + '?' + B + 'C:' + B + 'x',
    ' ' + B * 2 + 'host' + B + 'share' + B + 'x',
    '"' + B * 2 + 'host' + B + 'share' + B + 'x"',
    B + '/host/share/x',
    '/??/UNC/host/share/x',
    B + '/??' + B + 'UNC' + B + 'host' + B + 'x',
    'file://host/s/x',
    '\u3000' + B * 2 + 'host' + B + 'share' + B + 'x',
    B * 2 + 'host@SSL' + B + 'DavWWWRoot' + B + 'x',
]
NOT_A_PLAIN_PATH = [
    '\u200b' + B * 2 + 'host' + B + 'share' + B + 'x',   # not absolute: a relative name
    'file:///C:/x.iso', 'FILE:C:/x', 'relative' + B + 'x.iso', '.' + B + 'x', B + 'x', 'C:x.iso', '',
    '   ', 'C:' + B + 'a\x00b', 'C:' + B + 'a\nb', 'C:' + B + 'x' * 5000, None, 12, ['C:/x'],
]


@pytest.mark.parametrize('value', NETWORK)
def test_network_and_device_paths_are_refused(value):
    assert is_network_path(value), value
    with pytest.raises(NotLocalPath) as refused:
        local_path(value, field='vanillaIsoPath')
    assert refused.value.reason == 'network'
    assert 'network path' in str(refused.value) and 'vanillaIsoPath' in str(refused.value)
    for posix in (True, False):
        with pytest.raises(NotLocalPath):
            local_path(value, posix=posix)


@pytest.mark.parametrize('value', NOT_A_PLAIN_PATH)
def test_relative_empty_and_odd_paths_are_refused(value):
    for posix in (True, False):
        with pytest.raises(NotLocalPath):
            local_path(value, posix=posix)


@pytest.mark.parametrize('value, expected', [
    ('C:' + B + 'Users' + B + 'x' + B + 'a.zip', 'C:' + B + 'Users' + B + 'x' + B + 'a.zip'),
    ('e:/Games/Melee.iso', 'e:/Games/Melee.iso'),
    ('  "C:' + B + 'Games' + B + 'Melee.iso"  ', 'C:' + B + 'Games' + B + 'Melee.iso'),   # Explorer's Copy as path
    ('Z:' + B + 'mapped' + B + 'drive.iso', 'Z:' + B + 'mapped' + B + 'drive.iso'),   # the user's own choice
])
def test_drive_letter_paths_pass_on_every_platform(value, expected):
    assert local_path(value, posix=False) == expected
    assert local_path(value, posix=True) == expected


def test_posix_absolute_paths_pass_only_where_they_mean_this_computer():
    assert local_path('/home/me/Melee.iso', posix=True) == '/home/me/Melee.iso'
    with pytest.raises(NotLocalPath):
        local_path('/home/me/Melee.iso', posix=False)       # on Windows "/x" is drive-relative
    with pytest.raises(NotLocalPath):
        local_path(B + 'home' + B + 'me', posix=True)        # a backslash is not a POSIX root
    with pytest.raises(NotLocalPath):
        local_path('//host/share', posix=True)


def test_the_default_follows_the_platform():
    if os.name == 'nt':
        with pytest.raises(NotLocalPath):
            local_path('/home/me/x')
    else:
        assert local_path('/home/me/x') == '/home/me/x'


def test_a_request_is_checked_on_its_path_keys_only():
    bad = B + '??' + B + 'UNC' + B + 'host@SSL' + B + 'DavWWWRoot' + B + 'x.iso'
    assert request_path_refusal({'slippiPath': 'C:/Slippi', 'vanillaIsoPath': ''}, {'kitPath': None}) is None
    assert request_path_refusal({'name': bad, 'folder': bad}) is None          # not a path key
    key, refused = request_path_refusal(None, {'isoPath': 'C:/ok.iso'}, {'vanillaIsoPath': bad})
    assert key == 'vanillaIsoPath' and refused.reason == 'network'
    key, refused = request_path_refusal({'gccBin': 'mingw/bin'})
    assert key == 'gccBin' and refused.reason == 'form'
    assert set(path_safety.REQUEST_PATH_KEYS) >= {'kitPath', 'gccBin', 'destination', 'slippiPath',
                                                  'vanillaIsoPath', 'slippiDolphinPath', 'isoPath'}


def test_the_in_game_test_settings_go_through_the_gate():
    from randall.delivery import game_tests
    bad = B + '??' + B + 'UNC' + B + 'host@SSL' + B + 'DavWWWRoot' + B + 'x.iso'
    with pytest.raises(ValueError, match='network path'):
        game_tests.settings({'vanillaIsoPath': bad, 'slippiDolphinPath': ''})
    with pytest.raises(ValueError):
        game_tests.settings({'vanillaIsoPath': 'C:/x.iso', 'slippiDolphinPath': 'relative/Dolphin'})
    assert game_tests.settings({'vanillaIsoPath': '"C:/x.iso"', 'slippiDolphinPath': ''}) == {
        'vanillaIsoPath': 'C:/x.iso', 'slippiDolphinPath': ''}


@needs('play')
def test_play_uses_the_same_gate():
    from play import client
    for value in NETWORK:
        with pytest.raises(client.ClientError, match='not on this computer'):
            client.local_path(value)
    with pytest.raises(client.ClientError, match='on one of your drives'):
        client.local_path('/home/me/MU')                    # Play runs on Windows: drive letters only
    assert str(client.local_path('"C:/Games/MU"')) == str(client.local_path('C:/Games/MU'))


BOOT = r'''
import json, sys
import app
flask_app = app.app
flask_app.testing = True                                   # the token check is tested elsewhere
web = flask_app.test_client()
bad = sys.argv[1]
out = {}
r = web.post('/api/mex/settings/slippi-path/verify', json={'slippiPath': bad})
out['json'] = [r.status_code, r.get_json()]
r = web.get('/api/mex/texture-pack/stats', query_string={'slippiPath': bad})
out['query'] = [r.status_code, r.get_json()]
r = web.post('/api/mex/bundle/export', data={'vanillaIsoPath': bad, 'exportedIsoPath': 'C:/x.iso'})
out['form'] = [r.status_code, r.get_json()]
r = web.post('/api/mex/settings/slippi-path/verify', json={'slippiPath': 'C:/no/such/folder/anywhere'})
out['local'] = [r.status_code, r.get_json()]
print('GATE ' + json.dumps(out))
'''


def test_the_app_refuses_a_path_key_that_is_not_local_before_any_route(tmp_path):
    """The real app's before_request hook (app.py refuse_nonlocal_request_paths), booted in a child."""
    data = tmp_path / 'data'
    data.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('NUCLEUS_') and k != 'PYTHONPATH'}
    env.update({'PYTHONPATH': str(BACKEND), 'NUCLEUS_DATA_ROOT': str(data), 'NUCLEUS_ALLOW_DEV_DATA_ROOT': '1',
                'NUCLEUS_WORKER': '1'})
    bad = B + '??' + B + 'UNC' + B + 'host@SSL' + B + 'DavWWWRoot' + B + 'x'
    result = subprocess.run([sys.executable, '-c', BOOT, bad], cwd=BACKEND, env=env, capture_output=True,
                            text=True, timeout=180)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    out = json.loads(next(line for line in result.stdout.splitlines() if line.startswith('GATE '))[5:])
    for case in ('json', 'query', 'form'):
        status, body = out[case]
        assert status == 400 and body['code'] == 'not_a_local_path', (case, out[case])
        assert 'network path' in body['error']
    assert out['form'][1]['field'] == 'vanillaIsoPath'
    status, body = out['local']
    assert (body or {}).get('code') != 'not_a_local_path', out['local']   # a plain local path reaches the route
