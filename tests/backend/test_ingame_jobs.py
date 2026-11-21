"""In-game tests and captures run as the one `ingame` job (core/jobs.py): a
failed setup ends the job, the client names its capture's job, and the job owns
the Dolphin it launched. The only real process here is a sleeping Python this
test starts and closes by its own pid; nothing boots Dolphin."""
import base64
import json
import os
import subprocess
import sys
import threading
import time
import types
import uuid
from pathlib import Path

import psutil
import pytest
from flask import Flask

from core import jobs
import projects.routes.test_in_game as tig
import shared.ingame.capture as cap
import shared.ingame.runner as runner
from mexcli.project import MexExportCancelled
from projects.install import test_build
from shared.ingame import boot, embed

CLOSED = 'The test Dolphin it opened was closed.'


@pytest.fixture(autouse=True)
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    return tmp_path / 'jobs'


@pytest.fixture(autouse=True)
def shots(tmp_path, monkeypatch):
    monkeypatch.setattr(tig, 'SHOTS_ROOT', tmp_path / 'shots')
    return tmp_path / 'shots'


@pytest.fixture(autouse=True)
def no_real_dolphin(monkeypatch):
    """Test in Game refuses while ANY Dolphin runs on the machine (boot.dolphin_running reads the process list), so
    a real Dolphin elsewhere on the PC (a harness pool slot) made /start answer without a jobId. A test that wants
    one open sets its own."""
    monkeypatch.setattr(boot, 'dolphin_running', lambda: [])


@pytest.fixture
def client(tmp_path):
    vanilla = tmp_path / 'vanilla.iso'
    vanilla.write_bytes(b'synthetic ISO')
    app = Flask(__name__)
    app.register_blueprint(tig.test_in_game_bp)
    return app.test_client(), {'vanillaIsoPath': str(vanilla), 'slippiDolphinPath': 'synthetic/Dolphin.exe'}


@pytest.fixture
def sleeper():
    """A stand-in for a launched Dolphin: a process of a known executable."""
    exe = getattr(sys, '_base_executable', None) or sys.executable
    proc = subprocess.Popen([exe, '-c', 'import time; time.sleep(60)'])
    yield proc, exe
    if proc.poll() is None:  # ours, by pid
        proc.kill()
        proc.wait(timeout=5)


def _finished(job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while not (jobs.get(job_id) or {}).get('ended_at'):
        assert time.monotonic() < deadline, jobs.get(job_id)
        time.sleep(0.01)
    return jobs.get(job_id)


STAGE = {'stageCode': 'GrNBa', 'stageFolder': 'battlefield', 'variantId': 'v'}
CAPTURE = '/api/mex/test-in-game/capture-stage-screenshot'


def test_a_capture_whose_setup_fails_ends_failed_and_frees_the_slot(client, tmp_path, monkeypatch):
    """F-A-4: the scratch folders are made inside the job, so a storage failure
    fails that job instead of holding the one-test slot until restart."""
    http, paths = client
    storage = tmp_path / 'storage'
    storage.write_bytes(b'a file where the storage folder should be')
    monkeypatch.setattr(tig, 'STORAGE_PATH', storage)

    response = http.post(CAPTURE, json={**paths, **STAGE})
    assert response.status_code == 200
    record = _finished(response.json['jobId'])
    assert record['status'] == 'failed' and record['error']
    assert jobs.active_job(tig.INGAME_KIND) is None
    again = http.post('/api/mex/test-in-game/capture-pause-screenshot', json={**paths, 'modId': 'm'})
    assert again.status_code == 200
    assert _finished(again.json['jobId'])['status'] == 'failed'


def test_a_capture_runs_under_the_id_its_panel_chose_and_its_result_is_the_jobs(
        client, tmp_path, monkeypatch):
    """F-A-6, F-A-10: the panel names the job before it posts, so its result is
    found by that id after a lost response or a dropped socket, and no other
    capture's result can stand in for it."""
    http, paths = client
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path / 'storage')

    def build(vanilla, stage_code, stage_folder, variant_id, out_iso, **_kwargs):
        Path(out_iso).parent.mkdir(parents=True, exist_ok=True)
        Path(out_iso).write_bytes(b'test ISO')
        return {'stage': 'battlefield', 'button': 'X'}

    monkeypatch.setattr(test_build, 'build_stage_skin_iso', build)
    monkeypatch.setattr(cap, 'capture_stage', lambda *a, **k: {'ok': True, 'png': b'PNG'})
    job_id = str(uuid.uuid4())

    response = http.post(CAPTURE, json={**paths, **STAGE, 'jobId': job_id})
    assert response.json['jobId'] == job_id
    record = _finished(job_id)
    assert record['status'] == 'done'
    shot = f'/api/mex/test-in-game/shots/{job_id}/shot.png'
    assert record['result'] == {'screenshot': shot, 'stageFolder': 'battlefield', 'variantId': 'v'}
    assert http.get(shot).data == b'PNG'
    assert not list((tmp_path / 'storage' / 'test-builds').glob('*.iso'))
    assert http.post(CAPTURE, json={**paths, **STAGE, 'jobId': job_id}).status_code == 400
    assert http.post(CAPTURE, json={**paths, **STAGE, 'jobId': 'not-a-uuid'}).status_code == 400


def test_a_boot_tells_the_code_running_it_which_dolphin_it_launched(tmp_path, monkeypatch):
    monkeypatch.setenv('MELEE_DOLPHIN_LOCK', '0')
    monkeypatch.setattr(boot.subprocess, 'Popen', lambda *a, **k: types.SimpleNamespace(pid=4242))
    monkeypatch.setattr(embed, 'set_active', lambda *a, **k: None)
    dolphin = boot.DolphinBoot(str(tmp_path / 'test.iso'), 'synthetic', tmp_path)
    dolphin.exe, dolphin.user_dir = str(tmp_path / 'Dolphin.exe'), tmp_path / 'User'
    launched = []
    token = boot.ON_LAUNCH.set(lambda pid, exe: launched.append((pid, exe)))
    try:
        dolphin.launch()
    finally:
        boot.ON_LAUNCH.reset(token)
    assert launched == [(4242, dolphin.exe)]


def test_a_job_that_leaves_its_dolphin_open_has_it_closed_when_it_ends(sleeper):
    """F-A-5: the job owns the Dolphin it launched (pid + executable)."""
    proc, exe = sleeper

    def run(job):
        boot.ON_LAUNCH.get()(proc.pid, exe)  # what DolphinBoot.launch() does
        raise RuntimeError('the engine failed without closing Dolphin')

    record = _finished(tig._start_ingame_job(run, label='Costume test'))
    assert record['status'] == 'failed'
    assert proc.wait(timeout=10) is not None
    assert record['owned'] == {} and record['notes'] == [CLOSED]


def test_cleanup_leaves_a_pid_that_is_no_longer_that_dolphin(sleeper, tmp_path):
    proc, exe = sleeper
    created = psutil.Process(proc.pid).create_time()
    name = f'dolphin:{proc.pid}'
    other_exe = {'pid': proc.pid, 'exe': str(tmp_path / 'Dolphin.exe'), 'created': created}
    reused = {'pid': proc.pid, 'exe': exe, 'created': created - 60}
    assert tig._clean_ingame(name, other_exe) is None
    assert tig._clean_ingame(name, reused) is None
    assert proc.poll() is None
    assert tig._clean_ingame(name, {'pid': proc.pid, 'exe': exe, 'created': created}) == CLOSED
    assert proc.wait(timeout=10) is not None
    assert tig._clean_ingame(name, {'pid': proc.pid, 'exe': exe, 'created': created}) is None


def test_the_next_start_closes_a_dolphin_a_dead_backends_job_left_open(sleeper, job_dir):
    """F-A-5 after a crash: startup recovery marks the job interrupted and
    closes the Dolphin it owned."""
    proc, exe = sleeper
    owned = {f'dolphin:{proc.pid}': {'pid': proc.pid, 'exe': exe,
                                     'created': psutil.Process(proc.pid).create_time()}}
    job_dir.mkdir(parents=True)
    (job_dir / 'dead.json').write_text(json.dumps({
        'id': 'dead', 'kind': tig.INGAME_KIND, 'label': 'Costume test', 'status': 'running',
        'owned': owned, 'owner': {'pid': 999999, 'created': 1.0}, 'created_at': time.time()}),
        encoding='utf-8')

    [record] = jobs.recover_interrupted()
    assert record['status'] == 'interrupted' and record['owned'] == {}
    assert record['notes'] == [CLOSED]
    assert proc.wait(timeout=10) is not None


# ---- a Cancel from the jobs list -------------------------------------------------

def _dolphin_owned(job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while not any(name.startswith('dolphin:') for name in (jobs.get(job_id) or {}).get('owned') or {}):
        assert time.monotonic() < deadline, jobs.get(job_id)
        time.sleep(0.01)


def test_cancel_closes_an_automated_tests_dolphin_and_ends_it_cancelled(
        client, sleeper, tmp_path, monkeypatch):
    """The runner has no stop point while Dolphin runs: Cancel closes the
    Dolphin the job owns, and what the runner then saw is not a verdict."""
    http, _paths = client
    proc, exe = sleeper
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path / 'storage')
    monkeypatch.setattr(boot, 'dolphin_running', lambda: False)
    iso = tmp_path / 'built.iso'
    iso.write_bytes(b'ISO')

    def run_test(**_kwargs):
        boot.ON_LAUNCH.get()(proc.pid, exe)      # what DolphinBoot.launch() does
        proc.wait(timeout=20)                    # watching until Dolphin goes
        return {'verdict': 'crashed', 'pass': False, 'reason': 'Dolphin exited.'}
    monkeypatch.setattr(runner, 'run_test', run_test)

    job_id = http.post('/api/mex/test-in-game/start',
                       json={'isoPath': str(iso), 'slippiDolphinPath': exe}).json['jobId']
    _dolphin_owned(job_id)
    assert jobs.cancel(job_id) is True
    record = _finished(job_id)
    assert record['status'] == 'cancelled' and not record['error'] and record['result'] is None
    assert proc.poll() is not None and record['owned'] == {}


def test_cancel_during_the_build_stops_the_export_before_any_dolphin(tmp_path, monkeypatch):
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path / 'storage')
    monkeypatch.setattr(runner, 'run_test', lambda **_k: pytest.fail('booted after a Cancel'))
    building = threading.Event()

    def build(progress, log):
        building.set()
        should_stop = test_build.STOP_CHECK.get()   # what the MexCLI export polls
        deadline = time.monotonic() + 10
        while not should_stop():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        raise MexExportCancelled('stopped')

    job_id = tig._start_ingame_job(
        lambda job: tig._run_build_test(job, None, tmp_path / 'test.iso', 'synthetic', 9, build,
                                        remove_iso=True, runner_options=None, build_message='Building'),
        label='Costume test')
    assert building.wait(10)
    jobs.cancel(job_id)
    assert _finished(job_id)['status'] == 'cancelled'


def test_cancel_stops_an_interactive_session_as_its_stop_does(monkeypatch):
    session = tig._TestSession('session-1')
    monkeypatch.setitem(tig._test_sessions, 'session-1', session)
    tig._cancel_ingame(types.SimpleNamespace(id='session-1', snapshot=lambda: {'owned': {}}))
    assert session.stop_event.is_set()


def test_a_dolphin_that_launches_after_cancel_is_closed_at_once(sleeper):
    proc, exe = sleeper
    launch = threading.Event()

    def run(job):
        launch.wait(5)
        boot.ON_LAUNCH.get()(proc.pid, exe)
        proc.wait(timeout=10)
        job.check_stop()

    job_id = tig._start_ingame_job(run, label='Costume test')
    jobs.cancel(job_id)
    launch.set()
    assert _finished(job_id)['status'] == 'cancelled'
    assert proc.poll() is not None


# ---- screenshots are files the record names ----------------------------------

def test_a_tests_screenshots_are_files_its_record_names_not_images_in_it(client, shots, tmp_path):
    """A record stays in memory, goes to disk and to every GET /api/jobs."""
    http, _paths = client
    uri = 'data:image/png;base64,' + base64.b64encode(b'PNG').decode()
    payload = tig._shots_to_files('job-1', {'screenshot': uri, 'verdict': 'healthy',
                                            'checks': [{'label': 'a', 'screenshot': uri}, {'label': 'b'}]})
    assert payload == {'screenshot': '/api/mex/test-in-game/shots/job-1/shot.png', 'verdict': 'healthy',
                       'checks': [{'label': 'a', 'screenshot': '/api/mex/test-in-game/shots/job-1/check-0.png'},
                                  {'label': 'b'}]}
    assert http.get(payload['checks'][0]['screenshot']).data == b'PNG'
    assert http.get('/api/mex/test-in-game/shots/job-1/missing.png').status_code == 404
    (tmp_path / 'secret.png').write_bytes(b'SECRET')
    escape = http.get('/api/mex/test-in-game/shots/%2E%2E/secret.png')
    assert escape.status_code in (400, 404) and escape.data != b'SECRET'


def test_only_the_newest_jobs_screenshots_are_kept(shots):
    for i in range(tig.SHOTS_KEPT + 3):
        tig._save_shot(f'job-{i}', 'shot', b'PNG')
        os.utime(shots / f'job-{i}', (1_700_000_000 + i, 1_700_000_000 + i))
    kept = {p.name for p in shots.iterdir()}
    assert len(kept) == tig.SHOTS_KEPT
    assert {'job-0', 'job-1', 'job-2'}.isdisjoint(kept) and f'job-{tig.SHOTS_KEPT + 2}' in kept


# ---- a Cancel reaches work that has no Dolphin yet ----------------------------

def _one_skin_build(vanilla, stage_code, stage_folder, variant_id, out_iso, **_kwargs):
    Path(out_iso).parent.mkdir(parents=True, exist_ok=True)
    Path(out_iso).write_bytes(b'test ISO')
    return {'stage': 'battlefield', 'button': 'X'}


def test_cancel_reaches_an_automated_test_still_queued_for_dolphin(client, tmp_path, monkeypatch):
    """Queued behind the Dolphin lock there is no Dolphin to close: the run has
    the job's stop, which ends that queue (DolphinBoot.launch polls it)."""
    http, paths = client
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path / 'storage')
    iso = tmp_path / 'built.iso'
    iso.write_bytes(b'ISO')
    queued = threading.Event()

    def run_test(stop_event=None, **_kwargs):
        queued.set()
        assert stop_event.wait(10)
        return {'verdict': 'error', 'pass': False, 'reason': 'DolphinBootCancelled: stopped'}
    monkeypatch.setattr(runner, 'run_test', run_test)

    job_id = http.post('/api/mex/test-in-game/start',
                       json={'isoPath': str(iso), 'slippiDolphinPath': paths['slippiDolphinPath']}).json['jobId']
    assert queued.wait(10)
    jobs.cancel(job_id)
    record = _finished(job_id)
    assert record['status'] == 'cancelled' and record['result'] is None and not record['error']


def test_a_cancelled_capture_ends_cancelled_not_failed(client, tmp_path, monkeypatch):
    http, paths = client
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path / 'storage')
    monkeypatch.setattr(test_build, 'build_stage_skin_iso', _one_skin_build)
    capturing = threading.Event()

    def capture(*_a, stop_event=None, **_k):
        capturing.set()
        assert stop_event.wait(10)
        return {'ok': False, 'png': None, 'reason': 'DolphinBootCancelled: stopped'}
    monkeypatch.setattr(cap, 'capture_stage', capture)

    job_id = str(uuid.uuid4())
    http.post(CAPTURE, json={**paths, **STAGE, 'jobId': job_id})
    assert capturing.wait(10)
    jobs.cancel(job_id)
    record = _finished(job_id)
    assert record['status'] == 'cancelled' and not record['error']
    assert not list((tmp_path / 'storage' / 'test-builds').glob('*.iso'))
