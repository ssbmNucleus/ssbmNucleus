"""The model import tools in the app (randall/model_import/tools/service.py) and their routes
(randall/routes/model_import_tools.py): the states the Settings card and the import card show, the download job, Cancel
and Remove. The downloads are tiny fake pieces served from 127.0.0.1 (the assembly tests' server and entry)."""
import json
import threading
import time

import pytest
from flask import Flask

from core import jobs
from randall.model_import.tools import assemble, service
from randall.routes.model_import_tools import model_import_tools_bp
from tests.backend.test_model_import_tools_assemble import _entry, server  # noqa: F401  (server is a fixture)

KEY = 'win-x64'      # the fake entry has the Windows layout; the service is told this is that computer


@pytest.fixture(autouse=True)
def tools_home(tmp_path, monkeypatch):
    """Jobs, the manifest (the installer's resources) and the install, all under tmp_path."""
    import core.config
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(core.config, 'RESOURCES_DIR', tmp_path / 'resources')
    monkeypatch.setenv(service.ROOT_ENV, str(tmp_path / 'data' / 'tools' / 'model-import'))
    monkeypatch.setenv('NO_PROXY', '*')
    monkeypatch.setattr(service, 'platform_key', lambda: KEY)
    monkeypatch.setattr(assemble, 'check_space', lambda root, files, free=None: None)  # never the real disk
    monkeypatch.setattr(service, '_imports', 0)
    return tmp_path


def _manifest(tmp_path, entry):
    path = tmp_path / 'resources' / service.MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema': 1, 'platforms': {KEY: entry}}), encoding='utf-8')
    return entry


def _finish(job_id, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        record = jobs.get(job_id)
        if record and record['status'] not in jobs.ACTIVE:
            return record
        assert time.monotonic() < deadline, f'the download job did not end: {record}'
        time.sleep(0.02)


def _client():
    app = Flask(__name__)
    app.register_blueprint(model_import_tools_bp)
    return app.test_client()


def test_a_computer_the_manifest_does_not_name_is_unsupported(tools_home, monkeypatch):
    _manifest(tools_home, {'blender': {}, 'python': {}, 'wheels': []})
    monkeypatch.setattr(service, 'platform_key', lambda: 'linux-riscv64')
    view = service.status()
    assert view['state'] == 'unsupported' and view['supported'] is False and view['platform'] == 'linux-riscv64'
    assert service.need()['state'] == 'unsupported' and service.installed() is None
    with pytest.raises(service.Unsupported):
        service.start()
    reply = _client().post('/api/assistant/model-import-tools/start')
    assert reply.status_code == 400 and reply.json['success'] is False


def test_no_manifest_at_all_is_unsupported_not_a_crash(tools_home):
    assert service.status()['state'] == 'unsupported'


def test_not_installed_says_what_downloads_from_where_and_how_big(tools_home, server):
    entry = _manifest(tools_home, _entry(server))
    view = service.status()
    assert view['state'] == 'not_installed' and view['supported'] and view['job'] is None
    total = entry['blender']['size'] + entry['python']['size'] + sum(w['size'] for w in entry['wheels'])
    assert view['download_bytes'] == total == view['needed_bytes']
    assert view['disk_estimated'] is True and view['disk_bytes'] > total
    names = [p['name'] for p in view['pieces']]
    assert names == ['blender', 'python', 'wheels'] and not any(p['installed'] for p in view['pieces'])
    assert view['pieces'][0]['label'] == 'Blender 4.3.2' and view['pieces'][0]['source'] == 'download.blender.org'
    assert view['pieces'][1]['source'] == 'python.org'
    assert 'tinypkg 1.0' in view['pieces'][2]['label'] and view['pieces'][2]['source'].startswith('PyPI')
    sources = ['download.blender.org', 'python.org', 'PyPI (files.pythonhosted.org)']
    assert service.need() == {'state': 'not_installed', 'download_bytes': total, 'needed_bytes': total,
                              'disk_bytes': view['disk_bytes'], 'sources': sources}


def test_the_import_names_where_this_platforms_python_comes_from(tools_home, server):
    """0.9.0 build 3 smoke: the import's words named python.org on macOS and Linux too. need() names the pieces'
    sources as the Settings card does: python-build-standalone where the manifest pins a standalone Python."""
    entry = _entry(server)
    entry['python']['kind'] = 'standalone'
    _manifest(tools_home, entry)
    assert service.need()['sources'] == ['download.blender.org', 'python-build-standalone (GitHub)',
                                         'PyPI (files.pythonhosted.org)']
    assert [p['source'] for p in service.status()['pieces']] == service.need()['sources']
    assert service.sources([{'source': 'a'}, {'source': 'a'}, {'source': ''}, {}]) == ['a']


def test_the_download_job_installs_them_and_the_import_finds_them(tools_home, server):
    entry = _manifest(tools_home, _entry(server))
    job_id = service.start()
    record = _finish(job_id)
    assert record['status'] == 'done', record
    assert record['kind'] == service.KIND
    view = service.status()
    assert view['state'] == 'installed' and view['needed_bytes'] == 0
    assert view['disk_estimated'] is False and view['disk_bytes'] > 0, 'measured once installed'
    assert all(p['installed'] for p in view['pieces'])
    assert service.need() is None
    found = service.installed()
    root = service.tools_root()
    assert found == {'python': assemble.python_exe(root, entry), 'blender': assemble.blender_exe(root, entry)}
    assert found['python'].is_file() and found['blender'].is_file()


def test_an_update_is_needed_when_the_pins_move_and_the_old_tools_are_cleaned_after(tools_home, server):
    _manifest(tools_home, _entry(server))
    assert _finish(service.start())['status'] == 'done'
    old_blender = service.installed()['blender']
    _manifest(tools_home, _entry(server, version='4.3.3', tiny='1.1'))
    assert service.status()['state'] == 'update_needed'
    assert service.need()['state'] == 'update_needed' and service.installed() is None
    assert _finish(service.start())['status'] == 'done'
    assert service.status()['state'] == 'installed'
    assert not old_blender.exists(), "the old version's folders go once the new ones are in"


def test_a_failed_download_is_shown_with_its_error_and_can_be_started_again(tools_home, server):
    entry = _entry(server)
    entry['blender']['sha256'] = '0' * 64
    _manifest(tools_home, entry)
    record = _finish(service.start())
    assert record['status'] == 'failed' and record['error']
    view = service.status()
    assert view['state'] == 'failed' and view['error'] and view['job']['id'] == record['id']
    assert service.need()['state'] == 'not_installed', 'the import says "download them", not "failed"'
    assert _client().post('/api/assistant/model-import-tools/start').status_code == 200


def test_one_download_at_a_time_cancel_stops_it_and_remove_waits(tools_home, server, monkeypatch):
    _manifest(tools_home, _entry(server))
    gate, started = threading.Event(), threading.Event()
    real = assemble.assemble

    def slow(root, pinned, **kwargs):
        started.set()
        while not kwargs['cancelled']():
            gate.wait(0.02)
        raise assemble.Cancelled()
    monkeypatch.setattr(assemble, 'assemble', slow)
    client = _client()
    first = client.post('/api/assistant/model-import-tools/start')
    assert first.status_code == 200 and started.wait(10)
    second = client.post('/api/assistant/model-import-tools/start')
    assert second.status_code == 409 and second.json['job_id'] == first.json['job_id']
    view = client.get('/api/assistant/model-import-tools').json['tools']
    assert view['state'] == 'downloading' and view['job']['id'] == first.json['job_id']
    assert service.need()['state'] == 'downloading'
    busy = client.post('/api/assistant/model-import-tools/remove')
    assert busy.status_code == 409 and 'downloading' in busy.json['error']
    assert client.post('/api/assistant/model-import-tools/cancel').json['cancelled'] is True
    assert _finish(first.json['job_id'])['status'] == 'cancelled'
    assert client.post('/api/assistant/model-import-tools/cancel').json['cancelled'] is False
    monkeypatch.setattr(assemble, 'assemble', real)
    assert service.status()['state'] == 'not_installed', 'a cancel is not a failure (and this one kept no part)'


def _cancel_part_way(item, monkeypatch, blocks=2):
    """Download ``item`` as the job does and Cancel it after ``blocks`` blocks of 64 bytes: the part stays on disk
    (assemble.fetch keeps it for a resume). -> bytes kept."""
    monkeypatch.setattr(assemble, 'CHUNK', 64)
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) > blocks + 1                  # the loop top, the blocks, then Cancel
    with pytest.raises(assemble.Cancelled):
        assemble.fetch(service.tools_root(), 'Blender 4.3.2', item, cancelled=cancelled)
    return blocks * 64


def test_a_cancelled_download_is_paused_with_what_came_down_and_resumes(tools_home, server, monkeypatch):
    """0.9.0 build 3 smoke: Cancel at 168 MB showed "Not installed" and "Download (609 MB)" under "about 779 MB". The
    part is kept and Download resumes it, so the status says paused, with what is in and what is left."""
    entry = _manifest(tools_home, _entry(server))
    total = entry['blender']['size'] + entry['python']['size'] + sum(w['size'] for w in entry['wheels'])
    assert service.status()['downloaded_bytes'] == 0
    kept = _cancel_part_way(entry['blender'], monkeypatch)
    view = service.status()
    assert view['state'] == 'paused' and view['job'] is None and view['error'] is None
    assert view['download_bytes'] == total
    assert (view['downloaded_bytes'], view['needed_bytes']) == (kept, total - kept)
    assert not any(p['installed'] for p in view['pieces'])
    assert _client().get('/api/assistant/model-import-tools').json['tools']['state'] == 'paused'
    # The import's needs_tools reply keeps its states: nothing is installed, and what is left is the size.
    assert service.need() == {'state': 'not_installed', 'download_bytes': total, 'needed_bytes': total - kept,
                              'disk_bytes': view['disk_bytes'], 'sources': service.sources(view['pieces'])}
    # Resume: the same download carries on from the part.
    record = _finish(service.start())
    assert record['status'] == 'done', record
    assert ('blender-4.3.2-windows-x64.zip', f'bytes={kept}-') in server.state.requests
    after = service.status()
    assert after['state'] == 'installed' and (after['downloaded_bytes'], after['needed_bytes']) == (0, 0)


def test_a_paused_update_is_still_an_update_to_the_import(tools_home, server, monkeypatch):
    first = _manifest(tools_home, _entry(server))
    assert _finish(service.start())['status'] == 'done'
    # Only Blender moves. The first entry's Python and wheels stay as pinned: a fake archive built again a second
    # later has other zip timestamps, so another sha256.
    moved = _manifest(tools_home, dict(first, blender=_entry(server, version='4.3.3')['blender']))
    kept = _cancel_part_way(moved['blender'], monkeypatch, blocks=1)
    view = service.status()
    assert view['state'] == 'paused' and view['downloaded_bytes'] == kept
    assert view['needed_bytes'] == moved['blender']['size'] - kept, 'only Blender moved; the runtime is current'
    assert [p['installed'] for p in view['pieces']] == [False, True, True]
    assert service.need()['state'] == 'update_needed'


def test_remove_deletes_them_but_not_while_an_import_runs_on_them(tools_home, server):
    _manifest(tools_home, _entry(server))
    assert _finish(service.start())['status'] == 'done'
    client = _client()
    service.import_started()
    try:
        busy = client.post('/api/assistant/model-import-tools/remove')
        assert busy.status_code == 409 and 'import is running' in busy.json['error']
        assert service.status()['state'] == 'installed'
    finally:
        service.import_ended()
    reply = client.post('/api/assistant/model-import-tools/remove')
    assert reply.status_code == 200 and reply.json['removed'] is True
    assert reply.json['tools']['state'] == 'not_installed' and service.installed() is None
    assert not service.tools_root().exists()
    again = client.post('/api/assistant/model-import-tools/remove')
    assert again.status_code == 200 and again.json['removed'] is False


def test_the_import_counter_never_goes_below_zero():
    service.import_ended()
    assert service.import_running() is False
    service.import_started()
    assert service.import_running() is True
    service.import_ended()
    assert service.import_running() is False


def test_the_job_kind_cleans_up_what_a_dead_process_left(tools_home, monkeypatch):
    staging = tools_home / 'staging-left'
    (staging / 'x').mkdir(parents=True)
    (tools_home / 'staging-left.raw').mkdir()
    service._clean('staging', str(staging))
    assert not staging.exists() and not (tools_home / 'staging-left.raw').exists()
    detached = []
    monkeypatch.setattr(assemble, 'detach', detached.append)
    service._clean('mount', '/Volumes/blender-x')
    assert detached == ['/Volumes/blender-x']
