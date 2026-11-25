"""The game client Play installs and keeps up to date (play/managed.py): install, update, the
switch, and every failure leaving the version that worked in place. The feed is served by a
stand-in session, signed with a throwaway key; the client is the stand-in client of the shelf tests,
whose --print-info is stubbed. Everything runs in a temporary data folder."""
from tests.paths import BACKEND
import hashlib
import io
import json
import sys
import threading
import time
import zipfile

import pytest
from flask import Flask

sys.path.insert(0, str(BACKEND))

from core import jobs  # noqa: E402
from play import client, client_feed, launch, managed, routing, shelf  # noqa: E402
from play.routes.play import play_bp  # noqa: E402
from tests.backend.test_play_client_feed import HOST, Key, Reply, Session, make_feed  # noqa: E402
from tests.backend.test_play_shelf import fake_client, stub_info  # noqa: E402

UI_KEY = 'window-only-key'
WINDOW = {'X-Nucleus-UI-Key': UI_KEY}
#: What a release build's --print-info adds (the client's NUCLEUS_PUBLIC_BUILD).
RELEASE_BUILD = {'public_build': True, 'game_public_build': True}


def stub_release(monkeypatch, **changes):
    """stub_info for a release build of the client (the only kind Play installs)."""
    return stub_info(monkeypatch, **{**RELEASE_BUILD, **changes})


def client_release(version, *, exe=None):
    """(zip, sidecar bytes, sidecar) of a stand-in client folder (fake_client) as client_release.py packs it."""
    files = {
        client.SOURCE_EXE: exe or (b'MZ ' + ' '.join(client.LAUNCH_OPTIONS).encode() + f' {version}'.encode()),
        client.GAME_DLL: b'MZ game ' + version.encode(),
        'Sys/codes.ini': b'[codes]\n',
    }
    name = client_feed.PACKAGE_NAME.format(version=version)
    sidecar = {'format': 1, 'kind': client_feed.MANIFEST_KIND, 'name': name, 'version': version,
               'git_commit': '81447d35c0ffee81447d35c0ffee81447d35c0f', 'git_dirty': False,
               'notes': [], 'print_info': {'version': version, 'engine': 'source', **RELEASE_BUILD},
               'files': [{'path': p, 'size': len(d), 'sha256': hashlib.sha256(d).hexdigest()}
                         for p, d in sorted(files.items())]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(f'{name}/{path}', data)
        archive.writestr(f'{name}/{client_feed.INNER_MANIFEST}', json.dumps(sidecar).encode())
    data = buffer.getvalue()
    sidecar['zip'] = {'name': f'{name}.zip', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return data, json.dumps(sidecar).encode(), sidecar


class Server:
    """The releases site, as a stand-in session: publish() puts a release and its signed feed up."""

    def __init__(self, key):
        self.key, self.routes = key, {}
        self.session = Session(self.routes)

    def publish(self, version, *, min_app='0.9.3', zip_bytes=None, feed_changes=None, sign=True):
        data, sidecar_bytes, sidecar = client_release(version)
        feed = make_feed(data, sidecar_bytes, sidecar, min_app=min_app)
        for field, value in (feed_changes or {}).items():
            feed['platforms'][client_feed.PLATFORM_KEY][field] = value
        name = sidecar['name']
        self.routes[f'{HOST}/{name}.zip'] = zip_bytes if zip_bytes is not None else data
        self.routes[f'{HOST}/{name}.manifest.json'] = sidecar_bytes
        signed = self.key.sign(feed) if sign else feed
        self.routes[client_feed.CLIENT_FEED_URL] = json.dumps(signed).encode()
        return data


@pytest.fixture
def server(tmp_path, monkeypatch):
    root = tmp_path / 'data' / 'play'
    monkeypatch.setattr(shelf, 'play_root', lambda: root)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(client, 'supported', lambda: True)
    monkeypatch.setenv('NUCLEUS_APP_VERSION', '0.9.3')
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    monkeypatch.delenv(client_feed.TEST_FEED_ENV, raising=False)
    monkeypatch.delenv(client_feed.TEST_KEY_ENV, raising=False)
    monkeypatch.setattr(managed, '_checked', {'at': None, 'offer': None, 'error': None})
    stub_release(monkeypatch, version='1.0.7')
    key = Key()
    site = Server(key)
    # The production origin and paths, a throwaway key: what a test may sign is never the real key.
    monkeypatch.setattr(client_feed, 'production_source', key.source)
    monkeypatch.setattr(managed, 'make_fetcher', lambda src: client_feed.Fetcher(src, session=site.session))
    return site


def _wait(job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record and record['status'] in ('done', 'failed', 'cancelled'):
            return record
        time.sleep(0.02)
    raise AssertionError(f'job {job_id} did not end')


def _install(action='install'):
    return _wait(managed.start(action))


def _leftovers():
    root = managed.managed_root()
    return sorted(str(p.relative_to(root)) for sub in (managed.STAGING_DIR, managed.DOWNLOADS_DIR)
                  for p in (root / sub).glob('*'))


def _versions():
    folder = managed.managed_root() / managed.VERSIONS_DIR
    return sorted(p.name.split('-')[0] for p in folder.iterdir()) if folder.is_dir() else []


# --------------------------------------------------------------------------- install

def test_nothing_installed_says_so(server):
    status = managed.status()
    assert status['state'] == 'not_installed' and status['installed'] is None and status['job'] is None
    assert client.configured() is None
    with pytest.raises(client.ClientError, match='not installed yet'):
        client.require()


def test_install_downloads_checks_unpacks_and_switches(server, monkeypatch):
    server.publish('1.0.7')
    record = _install()
    assert record['status'] == 'done', record
    assert record['result'] == {'outcome': 'installed', 'version': '1.0.7'}
    status = managed.status()
    assert status['state'] == 'installed' and status['installed']['version'] == '1.0.7'
    folder = client.require()
    assert folder.parent == managed.managed_root() / managed.VERSIONS_DIR
    assert (folder / client.SOURCE_EXE).is_file() and (folder / 'Sys' / 'codes.ini').read_bytes() == b'[codes]\n'
    assert client.status()['source'] == 'managed' and client.status()['valid'] is True
    # Beside Play's data, never inside it; nothing left in staging or downloads.
    assert shelf.play_root().resolve() not in folder.parents
    assert _leftovers() == []
    # Saves, settings and the disc are Play's own: the install wrote nothing there but the --print-info
    # answer client.check_folder keeps for every client it checks.
    assert sorted(p.name for p in shelf.play_root().iterdir()) == ['client-info.json']


def test_the_feed_is_checked_before_any_download(server):
    server.publish('1.0.7', sign=False)
    record = _install()
    assert record['status'] == 'failed' and 'not signed' in record['error']
    assert server.session.asked == [server.session.asked[0]] and 'latest.json' in server.session.asked[0]
    status = managed.status()
    assert status['state'] == 'failed' and 'not signed' in status['error'] and status['errorAction'] == 'install'


def test_a_download_that_is_not_the_one_the_feed_names_installs_nothing(server):
    good = server.publish('1.0.7')
    server.publish('1.0.7', zip_bytes=good[:-1] + bytes([good[-1] ^ 1]))
    record = _install()
    assert record['status'] == 'failed' and 'SHA-256' in record['error']
    assert managed.status()['installed'] is None and _versions() == [] and _leftovers() == []


def test_an_app_too_old_for_the_client_is_told_to_update_first(server, monkeypatch):
    server.publish('1.0.7', min_app='0.9.4')
    record = _install()
    assert record['status'] == 'failed'
    assert 'needs SSBM Nucleus 0.9.4 or newer' in record['error']
    assert len(server.session.asked) == 1 and _versions() == []
    # Prerelease tags do not count against it.
    monkeypatch.setenv('NUCLEUS_APP_VERSION', '0.9.4-play-preview.1')
    assert _install()['status'] == 'done'


def test_a_client_that_says_another_version_is_not_switched_to(server, monkeypatch):
    server.publish('1.0.7')
    stub_release(monkeypatch, version='1.0.6')
    record = _install()
    assert record['status'] == 'failed' and 'says it is version 1.0.6, not 1.0.7' in record['error']
    assert managed.status()['installed'] is None and _versions() == [] and _leftovers() == []


def test_a_client_that_fails_its_check_is_not_switched_to(server, monkeypatch):
    server.publish('1.0.7')
    stub_release(monkeypatch, version='1.0.7', no_dialogs=False)
    record = _install()
    assert record['status'] == 'failed' and 'did not pass its check' in record['error']
    assert _versions() == []


@pytest.mark.parametrize('said', [
    {'public_build': True, 'game_public_build': False},
    {'public_build': False, 'game_public_build': True},
    {'public_build': True, 'game_public_build': None},     # the library could not be read
    {},                                                      # a client that does not say (older than the field)
])
def test_a_development_build_is_never_installed(server, monkeypatch, said):
    server.publish('1.0.7')
    stub_info(monkeypatch, version='1.0.7', **said)
    record = _install()
    assert record['status'] == 'failed'
    assert 'did not pass its check' in record['error'] and 'development build' in record['error']
    assert managed.status()['installed'] is None and _versions() == [] and _leftovers() == []


def test_a_hand_picked_folder_may_be_a_development_build_the_installed_one_may_not(server, monkeypatch, tmp_path):
    server.publish('1.0.7')
    assert _install()['status'] == 'done'
    installed = client.require()
    # The same client turns out not to be a release build (its answer is asked again).
    (shelf.play_root() / client.INFO_CACHE_FILE).unlink()
    stub_info(monkeypatch, version='1.0.7', public_build=False, game_public_build=False)
    with pytest.raises(client.ClientError, match='development build'):
        client.require()
    status = client.status()
    assert status['source'] == 'managed' and status['valid'] is False and 'development build' in status['error']
    # A developer's own folder is any build they made.
    mine = fake_client(tmp_path / 'MyBuild').resolve()
    shelf.write_settings(clientFolder=str(mine))
    assert client.require() == mine and client.status()['valid'] is True
    assert client.verify(str(installed))['valid'] is True        # as a hand-picked folder it would do too


# --------------------------------------------------------------------------- update

def test_an_update_switches_only_once_the_new_one_passed(server, monkeypatch):
    server.publish('1.0.7')
    assert _install()['status'] == 'done'
    old = client.require()
    server.publish('1.0.8')
    status = managed.check(force=True)
    assert status['updateAvailable'] is True and status['available']['version'] == '1.0.8'
    stub_release(monkeypatch, version='1.0.8')
    record = _install('update')
    assert record['status'] == 'done' and record['result'] == {'outcome': 'installed', 'version': '1.0.8'}
    assert managed.status()['installed']['version'] == '1.0.8' and managed.status()['updateAvailable'] is False
    assert client.require() != old
    # The old one goes once nothing runs from it.
    managed.purge()
    assert _versions() == ['1.0.8'] and not old.exists()
    # Nothing newer: an update says so and downloads nothing.
    asked = len(server.session.asked)
    assert _install('update')['result'] == {'outcome': 'current', 'version': '1.0.8'}
    assert len(server.session.asked) == asked + 1


def test_a_failed_update_leaves_the_old_version_active(server, monkeypatch):
    server.publish('1.0.7')
    assert _install()['status'] == 'done'
    old = client.require()
    good = server.publish('1.0.8')
    server.publish('1.0.8', zip_bytes=good + b'tail')
    record = _install('update')
    assert record['status'] == 'failed'
    status = managed.status()
    assert status['state'] == 'installed' and status['installed']['version'] == '1.0.7'
    assert status['error'] and status['errorAction'] == 'update'
    assert client.require() == old and (old / client.SOURCE_EXE).is_file()
    assert _versions() == ['1.0.7'] and _leftovers() == []
    # The next good try clears the reason.
    server.publish('1.0.8')
    stub_release(monkeypatch, version='1.0.8')
    assert _install('update')['status'] == 'done' and managed.status()['error'] is None


def test_an_update_waits_for_the_game_to_close(server, monkeypatch):
    server.publish('1.0.7')
    assert _install()['status'] == 'done'
    old = client.require()
    server.publish('1.0.8')
    stub_release(monkeypatch, version='1.0.8')
    running = {'now': True}
    monkeypatch.setattr(managed, '_session_running', lambda: running['now'])
    record = _install('update')
    assert record['result'] == {'outcome': 'pending', 'version': '1.0.8'}
    status = managed.status()
    assert status['installed']['version'] == '1.0.7' and status['pending']['version'] == '1.0.8'
    assert client.require() == old
    managed.purge()
    assert _versions() == ['1.0.7', '1.0.8']             # nothing removed while a game runs
    running['now'] = False
    assert managed.status()['installed']['version'] == '1.0.8' and managed.status()['pending'] is None
    assert client.require() != old


def test_update_needs_an_installed_client(server):
    with pytest.raises(managed.InstallError, match='not installed yet'):
        managed.start('update')
    with pytest.raises(managed.InstallError):
        managed.start('delete')


# --------------------------------------------------------------------------- cancel, one at a time

def test_cancel_stops_the_download_and_leaves_nothing(server):
    data = server.publish('1.0.7')
    reached, go = threading.Event(), threading.Event()

    def slow(at):
        if at:
            reached.set()
            go.wait(10)
    server.routes[f'{HOST}/NucleusClient-1.0.7-win64.zip'] = Reply(
        200, data, {'Content-Length': str(len(data))}, chunk=max(1, len(data) // 4), on_chunk=slow)
    job_id = managed.start('install')
    assert reached.wait(10)
    with pytest.raises(jobs.JobBusy):
        managed.start('install')
    status = managed.status()
    assert status['state'] == 'installing' and status['job']['phase'] == 'downloading'
    assert managed.cancel() is True
    go.set()
    record = _wait(job_id)
    assert record['status'] == 'cancelled'
    assert managed.status()['state'] == 'not_installed' and managed.status()['error'] is None
    assert _leftovers() == [] and _versions() == []
    assert managed.cancel() is False


def test_cancel_returns_at_once_while_the_server_sends_nothing(server):
    # The server stops sending partway: the Cancel must not wait for it (or for the read timeout).
    data = server.publish('1.0.7')
    reached, go = threading.Event(), threading.Event()

    def stall(at):
        if at:
            reached.set()
            go.wait(20)
    server.routes[f'{HOST}/NucleusClient-1.0.7-win64.zip'] = Reply(
        200, data, {'Content-Length': str(len(data))}, chunk=max(1, len(data) // 4), on_chunk=stall)
    job_id = managed.start('install')
    try:
        assert reached.wait(10)
        asked = time.monotonic()
        assert managed.cancel() is True
        record = _wait(job_id, timeout=5)
        assert record['status'] == 'cancelled'
        assert time.monotonic() - asked < 1.5
        status = managed.status()
        assert status['state'] == 'not_installed' and status['error'] is None
        assert _leftovers() == [] and _versions() == []       # the partial download is gone already
    finally:
        go.set()
    readers = [t for t in threading.enumerate() if t.name == 'client-download-reader']
    for reader in readers:
        reader.join(5)
        assert not reader.is_alive()                          # the abandoned reader ended on its own


# --------------------------------------------------------------------------- what wins, what runs

def test_a_hand_picked_folder_wins_over_the_installed_client(server, tmp_path):
    server.publish('1.0.7')
    assert _install()['status'] == 'done'
    mine = fake_client(tmp_path / 'MyBuild').resolve()
    shelf.write_settings(clientFolder=str(mine))
    assert client.require() == mine and client.status()['source'] == 'folder'
    shelf.write_settings(clientFolder=None)
    assert client.status()['source'] == 'managed'


def test_the_built_in_games_never_run_on_the_compatibility_engine(server, tmp_path):
    game = fake_client(tmp_path / 'MU').resolve()
    for entry_id in ('retail', 'vanilla'):
        entry = {**shelf.get(entry_id), 'engine': shelf.ENGINE_COMPAT, 'engineChoice': shelf.ENGINE_COMPAT}
        assert routing.effective_engine(entry, game)[0] == shelf.ENGINE_SOURCE
        command = launch.build_command(client_folder=game, entry=entry, retail_iso=tmp_path / 'm.iso',
                                       play_root=shelf.play_root(), data_dir=shelf.play_root() / 'data' / entry_id,
                                       engine=shelf.ENGINE_COMPAT)
        assert command.args[0] == str(game / client.SOURCE_EXE)


def test_a_feed_that_cannot_be_read_is_a_plain_check_error(server):
    status = managed.check(force=True)
    assert status['checkError'] == 'The download server answered HTTP 404. Try again later.'
    assert status['available'] is None and status['state'] == 'not_installed'


def test_startup_tidies_what_a_crash_left(server):
    root = managed.managed_root()
    (root / managed.STAGING_DIR / ('a' * 32)).mkdir(parents=True)
    (root / managed.DOWNLOADS_DIR).mkdir(parents=True)
    (root / managed.DOWNLOADS_DIR / ('b' * 32 + '.zip')).write_bytes(b'partial')
    (root / managed.VERSIONS_DIR / '1.0.5-0123abcd').mkdir(parents=True)
    managed.startup()
    assert _leftovers() == [] and _versions() == []


# --------------------------------------------------------------------------- the routes

@pytest.fixture
def web(server):
    app = Flask(__name__)
    app.register_blueprint(play_bp)
    return app.test_client()


def test_the_routes(web, server):
    server.publish('1.0.7')
    assert web.get('/api/play/client/managed').get_json()['managed']['state'] == 'not_installed'
    checked = web.post('/api/play/client/managed/check', json={'force': True}, headers=WINDOW).get_json()
    assert checked['managed']['available']['version'] == '1.0.7'
    started = web.post('/api/play/client/managed/install', json={}, headers=WINDOW).get_json()
    record = _wait(started['job_id'])
    assert record['status'] == 'done'
    shelf_answer = web.get('/api/play/shelf').get_json()
    assert shelf_answer['managed']['installed']['version'] == '1.0.7'
    assert shelf_answer['client']['source'] == 'managed' and shelf_answer['client']['valid'] is True
    assert web.post('/api/play/client/managed/cancel', json={}, headers=WINDOW).get_json()['cancelled'] is False
    refused = web.post('/api/play/client/managed/update', json={}, headers={'X-Nucleus-UI-Key': 'wrong'})
    assert refused.status_code == 403
