"""Play's routes (play/routes/play.py): what the Play page reads, the window-only key on everything
that starts a program or changes the shelf, ids that are only looked up, covers, and the gate."""
from tests.paths import BACKEND
import io
import sys
import time

import pytest
from flask import Flask

sys.path.insert(0, str(BACKEND))

from core import jobs  # noqa: E402
from play import client, launch, shelf  # noqa: E402
from play.routes.play import play_bp  # noqa: E402
from tests.backend.test_play_shelf import fake_client, fake_plugin, stub_info  # noqa: E402

UI_KEY = 'window-only-key'
WINDOW = {'X-Nucleus-UI-Key': UI_KEY}


@pytest.fixture
def play(tmp_path, monkeypatch):
    root = tmp_path / 'play'
    monkeypatch.setattr(shelf, 'play_root', lambda: root)
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    monkeypatch.setattr(launch, 'retail_iso', lambda: None)
    monkeypatch.setattr(launch, 'recorded_iso', lambda: None)
    stub_info(monkeypatch)
    return root


@pytest.fixture
def web(play):
    app = Flask(__name__)
    app.register_blueprint(play_bp)
    return app.test_client()


def _entry(name='Test game'):
    entry_id, folder = shelf.reserve()
    (folder / shelf.DISC_FILE).write_bytes(b'disc')
    return shelf.add({'id': entry_id, 'name': name, 'disc': {'kind': 'owned'},
                      'targets': {'mu': {'available': True}}, 'engine': 'source'})


def test_the_shelf(web):
    data = web.get('/api/play/shelf').get_json()
    assert data['success'] is True
    assert [e['id'] for e in data['entries']] == ['retail', 'vanilla']
    assert data['client'] == {'set': False, 'source': None, 'valid': False, 'error': None, 'folder': ''}
    assert data['managed']['state'] == 'not_installed' and data['managed']['installed'] is None
    assert data['retailIso'] == {'set': False, 'missing': None}
    assert data['running'] is None
    assert data['platform']['supported'] is (sys.platform == 'win32')


def test_the_shelf_names_a_recorded_disc_that_is_gone(web, monkeypatch, tmp_path):
    gone = tmp_path / 'moved' / 'Melee.iso'
    monkeypatch.setattr(launch, 'recorded_iso', lambda: gone)
    assert web.get('/api/play/shelf').get_json()['retailIso'] == {'set': False, 'missing': str(gone)}
    # Still there (only retail_iso's own check failed to find it): nothing is named.
    gone.parent.mkdir()
    gone.write_bytes(b'')
    assert web.get('/api/play/shelf').get_json()['retailIso'] == {'set': False, 'missing': None}
    # In use: nothing is missing.
    monkeypatch.setattr(launch, 'retail_iso', lambda: gone)
    assert web.get('/api/play/shelf').get_json()['retailIso'] == {'set': True, 'missing': None}


WINDOW_ONLY = [
    ('post', '/api/play/client', {'folder': 'C:\\MU'}),
    ('post', '/api/play/client/verify', {'folder': 'C:\\MU'}),
    ('post', '/api/play/launch/retail', {}),
    ('post', '/api/play/settings-window', {}),
    ('post', '/api/play/replay', {'path': 'C:\\Replays\\Game.slp'}),
    ('post', '/api/play/reveal/retail', {}),
    ('patch', '/api/play/shelf/retail', {'name': 'x'}),
    ('delete', '/api/play/shelf/retail', None),
    ('post', '/api/play/shelf/retail/cover', None),
    ('post', '/api/play/client/managed/check', {'force': True}),
    ('post', '/api/play/client/managed/install', {}),
    ('post', '/api/play/client/managed/update', {}),
    ('post', '/api/play/client/managed/cancel', {}),
]


@pytest.mark.parametrize('method,url,body', WINDOW_ONLY)
def test_only_the_window_starts_or_changes_anything(web, monkeypatch, method, url, body):
    started = []
    monkeypatch.setattr(launch, 'start', lambda command: started.append(command))
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: started.append(a))
    call = getattr(web, method)
    assert call(url, json=body).status_code == 403                                     # the token alone
    assert call(url, json=body, headers={'X-Nucleus-UI-Key': 'wrong'}).status_code == 403
    agent = call(url, json=body, headers={**WINDOW, 'X-Nucleus-Agent': 'mcp'})
    assert agent.status_code == 403 and agent.get_json()['code'] == 'automation_caller'
    monkeypatch.delenv('NUCLEUS_UI_APPROVAL_KEY')
    assert call(url, json=body, headers=WINDOW).status_code == 503                    # no key: fail closed
    assert started == []
    assert shelf.read_settings() == {}


def test_choosing_the_melee_unlocked_folder(web, tmp_path):
    folder = fake_client(tmp_path / 'MU')
    verified = web.post('/api/play/client/verify', json={'folder': str(folder)}, headers=WINDOW).get_json()
    assert verified['valid'] is True and verified['engines']['compat'] is True
    assert shelf.read_settings() == {}           # verify does not save
    saved = web.post('/api/play/client', json={'folder': str(folder)}, headers=WINDOW).get_json()
    assert saved['client']['valid'] is True
    assert web.get('/api/play/client').get_json()['client']['folder'] == str(folder.resolve())
    bad = web.post('/api/play/client', json={'folder': str(tmp_path)}, headers=WINDOW)
    assert bad.status_code == 400 and 'melee_source.exe' in bad.get_json()['error']
    share = web.post('/api/play/client', json={'folder': '\\\\host\\share\\MU'}, headers=WINDOW)
    assert share.status_code == 400
    assert shelf.read_settings()['clientFolder'] == str(folder.resolve())
    cleared = web.post('/api/play/client', json={'folder': ''}, headers=WINDOW).get_json()
    assert cleared['client']['set'] is False


def test_launching_says_what_is_missing(web, monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'supported', lambda: True)
    reply = web.post('/api/play/launch/retail', json={}, headers=WINDOW)
    assert reply.status_code == 400 and reply.get_json()['error'] == client.NOT_INSTALLED
    assert web.post('/api/play/launch/nope', json={}, headers=WINDOW).status_code == 404
    assert web.post('/api/play/launch/retail', json={'target': 'wii'}, headers=WINDOW).status_code == 400
    monkeypatch.setattr(client, 'supported', lambda: False)
    reply = web.post('/api/play/launch/retail', json={}, headers=WINDOW)
    assert reply.status_code == 400 and reply.get_json()['error'] == 'Nucleus Unlocked is Windows only for now.'


def test_launching_starts_the_verified_game(web, monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'supported', lambda: True)
    folder = fake_client(tmp_path / 'MU').resolve()
    client.save(str(folder))
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'')
    monkeypatch.setattr(launch, 'retail_iso', lambda: iso)
    monkeypatch.setattr(launch, 'check_retail_iso', lambda iso: None)
    monkeypatch.setattr(launch, 'slippi_folders', lambda: (None, None))
    monkeypatch.setattr(launch, 'tracker_replay_folder', lambda: None)
    started = []

    class Done:
        pid = 4242

        def poll(self):
            return 0
    monkeypatch.setattr(launch, 'start', lambda command: started.append(command) or Done())
    monkeypatch.setattr(launch, 'find_successor', lambda *a: None)
    reply = web.post('/api/play/launch/vanilla', json={'target': 'mu', 'exe': 'C:\\evil.exe'}, headers=WINDOW)
    assert reply.status_code == 200
    job_id = reply.get_json()['job_id']
    deadline = time.time() + 10
    while jobs.get(job_id)['status'] not in ('done', 'failed') and time.time() < deadline:
        time.sleep(0.05)
    record = jobs.get(job_id)
    assert record['status'] == 'done' and record['params'] == {'entryId': 'vanilla', 'target': 'mu'}
    assert started[0].args[0] == str(folder / 'melee_source.exe')
    assert 'C:\\evil.exe' not in started[0].args


def test_renaming_and_removing(web):
    entry = _entry()
    reply = web.patch(f"/api/play/shelf/{entry['id']}", json={'name': 'New name', 'description': 'About it'},
                      headers=WINDOW)
    assert reply.get_json()['entry']['name'] == 'New name'
    assert web.patch('/api/play/shelf/retail', json={'name': 'x'}, headers=WINDOW).status_code == 400
    assert web.patch('/api/play/shelf/..%2F..%2Fx', json={'name': 'x'}, headers=WINDOW).status_code == 404
    assert web.delete('/api/play/shelf/vanilla', headers=WINDOW).status_code == 400
    assert web.delete(f"/api/play/shelf/{entry['id']}", headers=WINDOW).get_json()['success'] is True
    assert web.delete(f"/api/play/shelf/{entry['id']}", headers=WINDOW).status_code == 404


def test_a_running_game_is_not_removed(web, monkeypatch):
    entry = _entry()
    monkeypatch.setattr(launch, 'running_entry', lambda: entry['id'])
    assert web.delete(f"/api/play/shelf/{entry['id']}", headers=WINDOW).status_code == 409
    assert shelf.find(entry['id']) is not None


def test_covers(web):
    from PIL import Image
    entry = _entry()
    assert web.get(f"/api/play/shelf/{entry['id']}/cover").status_code == 404
    picture = io.BytesIO()
    Image.new('RGB', (64, 32), (1, 2, 3)).save(picture, format='GIF')
    reply = web.post(f"/api/play/shelf/{entry['id']}/cover", headers=WINDOW,
                     data={'cover': (io.BytesIO(picture.getvalue()), 'cover.gif')}, content_type='multipart/form-data')
    assert reply.get_json()['entry']['hasCover'] is True
    served = web.get(f"/api/play/shelf/{entry['id']}/cover")
    assert served.status_code == 200 and served.mimetype == 'image/png'
    assert served.data.startswith(b'\x89PNG')
    bad = web.post(f"/api/play/shelf/{entry['id']}/cover", headers=WINDOW,
                   data={'cover': (io.BytesIO(b'<html>'), 'x.html')}, content_type='multipart/form-data')
    assert bad.status_code == 400
    assert web.get('/api/play/shelf/retail/cover').status_code == 404


def test_account_line_has_name_and_code_only(web, monkeypatch):
    import tracker.store.identity as identity
    monkeypatch.setattr(identity, 'get_netplay_identity',
                        lambda: {'displayName': 'Fox', 'connectCode': 'FOX#123', 'uid': 'u'})
    data = web.get('/api/play/account').get_json()
    assert data == {'success': True, 'signedIn': True, 'displayName': 'Fox', 'connectCode': 'FOX#123'}
    monkeypatch.setattr(identity, 'get_netplay_identity', lambda: {})
    assert web.get('/api/play/account').get_json()['signedIn'] is False


def test_reveal_opens_the_entry_data_folder(web, monkeypatch):
    opened = []
    monkeypatch.setattr('subprocess.Popen', lambda args, **k: opened.append(args))
    assert web.post('/api/play/reveal/retail', headers=WINDOW).status_code == 200
    assert opened[0][-1].endswith('retail') and shelf.data_dir({'id': 'retail'}).is_dir()
    assert web.post('/api/play/reveal/..', headers=WINDOW).status_code == 404


def test_the_gate_closes_play(monkeypatch):
    from core import gates
    monkeypatch.setenv('NUCLEUS_PLAY', '0')
    assert gates.enabled('play') is False
    monkeypatch.setenv('NUCLEUS_PLAY', '1')
    assert gates.enabled('play') is True
    assert 'NUCLEUS_PLAY' in gates.packaged_off_env()


# --------------------------------------------------------------------------- replays from Tracker

class _Index:
    """tracker.store.indexer.connect's stand-in: knows the replays in `paths`."""
    def __init__(self, paths):
        self.paths, self.closed = set(paths), 0

    def close(self):
        self.closed += 1


@pytest.fixture
def indexed(monkeypatch, tmp_path):
    from tracker.store import games, indexer, slp_meta
    index = _Index([])
    monkeypatch.setattr(indexer, 'connect', lambda: index)
    monkeypatch.setattr(games, '_validate_indexed_path',
                        lambda conn, path: path if path in conn.paths else None)
    checked = []
    monkeypatch.setattr(slp_meta, 'peppi_refusal', lambda path: checked.append(path) or None)
    index.checked = checked
    return index


def _replay(tmp_path, name='Game_20261122T235023.slp'):
    path = tmp_path / 'Slippi' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{U\x03raw')
    return path


def test_watching_a_tracker_replay_in_melee_unlocked(web, monkeypatch, tmp_path, indexed):
    monkeypatch.setattr(client, 'supported', lambda: True)
    folder = fake_client(tmp_path / 'MU').resolve()
    client.save(str(folder))
    status = web.get('/api/play/replay').get_json()
    assert status['available'] is False and 'SysPlayback' in status['reason']
    (folder / client.SYS_PLAYBACK_DIR).mkdir()
    assert 'Melee ISO' in web.get('/api/play/replay').get_json()['reason']
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'')
    monkeypatch.setattr(launch, 'retail_iso', lambda: iso)
    monkeypatch.setattr(launch, 'check_retail_iso', lambda iso: None)
    assert web.get('/api/play/replay').get_json() == {'success': True, 'available': True, 'reason': None}

    replay = _replay(tmp_path)
    indexed.paths.add(str(replay))
    work = shelf.play_root() / shelf.DATA_DIR / launch.REPLAY_WORK_DIR
    (work / 'Replays').mkdir(parents=True)
    (work / 'Replays' / 'Game_old.slp').write_bytes(b'an earlier recording')
    (work / 'Replays' / 'notes.txt').write_text('kept')
    started = []

    class Done:
        pid = 4343

        def poll(self):
            return 4                         # the viewer was closed
    monkeypatch.setattr(launch, 'start', lambda command: started.append(command) or Done())
    monkeypatch.setattr(launch, 'find_successor', lambda *a: None)
    reply = web.post('/api/play/replay', json={'path': str(replay)}, headers=WINDOW)
    assert reply.status_code == 200, reply.get_json()
    job_id = reply.get_json()['job_id']
    deadline = time.time() + 10
    while jobs.get(job_id)['status'] not in ('done', 'failed') and time.time() < deadline:
        time.sleep(0.05)
    record = jobs.get(job_id)
    assert record['status'] == 'done', record.get('error')
    assert record['params'] == {'entryId': None, 'replay': True, 'file': replay.name}
    assert record['result']['outcome'] == 'quit'
    [command] = started
    args = command.args
    assert args[0] == str(folder / 'melee_source.exe') and command.replay is True
    assert args[args.index('--replay') + 1] == str(replay)
    assert args[args.index('--sys-dir') + 1] == str(folder / 'SysPlayback')
    assert args[args.index('--replay-dir') + 1] == str(work / 'Replays')
    assert args[args.index('--fighters-dir') + 1] == 'none' and '--no-dialogs' in args
    assert indexed.checked == [str(replay)] and indexed.closed == 1
    assert sorted(p.name for p in (work / 'Replays').iterdir()) == ['notes.txt']    # old recordings cleared
    assert launch.running_entry() is None


def test_only_an_indexed_local_replay_is_watched(web, monkeypatch, tmp_path, indexed):
    from tracker.store import slp_meta
    monkeypatch.setattr(client, 'supported', lambda: True)
    folder = fake_client(tmp_path / 'MU').resolve()
    (folder / client.SYS_PLAYBACK_DIR).mkdir()
    client.save(str(folder))
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'')
    monkeypatch.setattr(launch, 'retail_iso', lambda: iso)
    started = []
    monkeypatch.setattr(launch, 'start', lambda command: started.append(command))
    replay = _replay(tmp_path)

    def refused(body):
        reply = web.post('/api/play/replay', json=body, headers=WINDOW)
        return reply.status_code, reply.get_json()['error']

    assert refused({}) == (400, 'Say which replay to watch.')
    assert refused({'path': str(replay)}) == (404, 'That replay is not in Tracker.')       # not indexed
    share = '\\\\host\\share\\Game.slp'
    indexed.paths.update({share, str(tmp_path / 'Slippi' / 'notes.txt')})
    status, error = refused({'path': share})
    assert status == 400 and 'not on this computer' in error
    (tmp_path / 'Slippi' / 'notes.txt').write_text('x')
    assert refused({'path': str(tmp_path / 'Slippi' / 'notes.txt')}) == (400, 'That is not a replay file.')
    indexed.paths.add(str(replay))
    monkeypatch.setattr(slp_meta, 'peppi_refusal', lambda path: 'the raw event length is negative')
    assert refused({'path': str(replay)}) == (400, 'That replay cannot be played: the raw event length is negative.')
    assert started == []


def test_replay_shape_checks_are_slp_metas(tmp_path):
    """The real slp_meta checks (not the fixture's stand-in) refuse a file that is not a replay."""
    from tracker.store import slp_meta
    junk = tmp_path / 'junk.slp'
    junk.write_bytes(b'not a replay at all' * 4)
    assert slp_meta.peppi_refusal(str(junk)) == 'the file is not a Slippi replay'


def test_the_shelf_says_where_the_game_settings_come_from(web, tmp_path, monkeypatch):
    monkeypatch.setattr(client, 'supported', lambda: True)
    folder = fake_client(tmp_path / 'MU').resolve()
    client.save(str(folder))
    assert web.get('/api/play/shelf').get_json()['gameSettings'] == {'exists': False, 'seededAt': None,
                                                                     'canSeed': False}
    (folder / 'port-settings.ini').write_text('[Audio]\nvolume=3\n', encoding='utf-8')
    assert web.get('/api/play/shelf').get_json()['gameSettings'] == {'exists': False, 'seededAt': None,
                                                                     'canSeed': True}
    assert shelf.seed_game_settings(folder) is True
    seeded = web.get('/api/play/shelf').get_json()['gameSettings']
    assert seeded['exists'] is True and seeded['canSeed'] is False and seeded['seededAt'] > 0
