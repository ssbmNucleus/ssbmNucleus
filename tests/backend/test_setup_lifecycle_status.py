"""First-run setup runs as a core/jobs.py job: verification included, one at a
time, its record the only status, and a temp project a dead setup left behind
removed at the next start."""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

import pytest
from flask import Flask

from core import jobs
import shared.routes.setup as setup


@pytest.fixture
def ordinary_tmp():
    root = Path(__file__).parent / '.tmp-setup-lifecycle'
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    assert path.parent.resolve() == root.resolve()
    shutil.rmtree(path)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    app = Flask(__name__)
    app.register_blueprint(setup.setup_bp)
    return app.test_client()


def _wait(job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = jobs.get(job_id)
        if record['status'] in jobs.FINAL and record.get('ended_at'):
            return record
        time.sleep(0.005)
    raise AssertionError(f'setup job did not finish: {jobs.get(job_id)}')


def _fake_engine(monkeypatch, run_setup):
    class FakeSetup:
        def __init__(self, *_args):
            pass

        def check_setup_needed(self):
            return {'complete': False, 'reason': 'test', 'details': 'test'}

    FakeSetup.run_setup = lambda self, iso_path, progress, on_temp_dir=None: run_setup(
        progress, on_temp_dir)
    monkeypatch.setattr(setup, 'FirstRunSetup', FakeSetup)
    monkeypatch.setattr(setup, 'record_vanilla_iso', lambda _path: None)


def test_a_start_without_an_iso_starts_no_job(client):
    response = client.post('/api/mex/setup/start', json={})
    assert response.status_code == 400
    assert jobs.list_jobs(kind=setup.SETUP_KIND) == []


def test_verification_runs_in_the_job_so_leaving_never_loses_the_setup(
        client, ordinary_tmp, monkeypatch):
    """F-H-2: the start returns before the ISO is hashed; a second start gets
    the running job's id to follow instead of a bare failure."""
    hashing = threading.Event()
    release = threading.Event()

    def slow_verify(_path):
        hashing.set()
        assert release.wait(timeout=5)
        return {'valid': True}

    def run_setup(progress, _on_temp_dir):
        progress('copying_stages', 75, 'Copying stages', 3, 4)
        return {'success': True, 'message': 'Done', 'characters': 25, 'stages': 29}

    iso = ordinary_tmp / 'vanilla.iso'
    iso.write_bytes(b'test')
    _fake_engine(monkeypatch, run_setup)
    monkeypatch.setattr(setup, 'verify_iso_file', slow_verify)

    first = client.post('/api/mex/setup/start', json={'isoPath': str(iso)})
    assert first.status_code == 200
    job_id = first.get_json()['jobId']
    assert hashing.wait(timeout=5)
    record = jobs.get(job_id)
    assert record['status'] == 'running' and record['extra']['phase'] == 'verifying'

    second = client.post('/api/mex/setup/start', json={'isoPath': str(iso)})
    assert second.status_code == 409
    assert second.get_json()['jobId'] == job_id

    release.set()
    record = _wait(job_id)
    assert record['status'] == 'done'
    assert record['result'] == {'message': 'Done', 'characters': 25, 'stages': 29,
                                'isoPath': str(iso)}
    assert 'setupState' not in client.get('/api/mex/setup/status').get_json()


def test_the_engines_complete_phase_is_not_the_jobs_end(client, ordinary_tmp, monkeypatch):
    """F-H-3: 'complete' progress arrives while the engine still cleans up; only
    the job's final status (which carries the ISO path) ends it."""
    cleaning = threading.Event()
    release = threading.Event()

    def run_setup(progress, _on_temp_dir):
        progress('complete', 100, 'Setup complete!', 100, 100)
        cleaning.set()
        assert release.wait(timeout=5)
        return {'success': True, 'message': 'Done', 'characters': 1, 'stages': 1}

    iso = ordinary_tmp / 'vanilla.iso'
    iso.write_bytes(b'test')
    _fake_engine(monkeypatch, run_setup)
    monkeypatch.setattr(setup, 'verify_iso_file', lambda _path: {'valid': True})

    job_id = client.post('/api/mex/setup/start', json={'isoPath': str(iso)}).get_json()['jobId']
    assert cleaning.wait(timeout=5)
    record = jobs.get(job_id)
    assert record['status'] == 'running' and record['result'] is None
    release.set()
    assert _wait(job_id)['result']['isoPath'] == str(iso)


def test_a_failed_step_fails_the_job_and_removes_its_temp_project(
        client, ordinary_tmp, monkeypatch):
    temp = ordinary_tmp / 'nucleus_setup_x'

    def run_setup(_progress, on_temp_dir):
        temp.mkdir()
        on_temp_dir(temp)
        # The engine's own cleanup did not get to run.
        return {'success': False, 'error': 'mexcli create failed'}

    iso = ordinary_tmp / 'vanilla.iso'
    iso.write_bytes(b'test')
    _fake_engine(monkeypatch, run_setup)
    monkeypatch.setattr(setup, 'verify_iso_file', lambda _path: {'valid': True})

    record = _wait(client.post('/api/mex/setup/start', json={'isoPath': str(iso)}).get_json()['jobId'])
    assert record['status'] == 'failed' and record['error'] == 'mexcli create failed'
    assert record['owned'] == {}
    assert not temp.exists()


def test_a_setup_nucleus_died_in_is_interrupted_and_its_temp_project_removed(
        client, ordinary_tmp):
    """F-H-4 after a relaunch: the record says interrupted (shown once), and the
    extracted ISO it left in the temp folder is gone."""
    temp = ordinary_tmp / 'nucleus_setup_dead'
    (temp / 'files').mkdir(parents=True)
    root = jobs._root()
    root.mkdir(parents=True)
    (root / 'dead.json').write_text(json.dumps({
        'id': 'dead', 'kind': setup.SETUP_KIND, 'label': 'First-time setup',
        'status': 'running', 'owned': {'temp': str(temp)},
        'owner': {'pid': 999999, 'created': 1.0}, 'created_at': time.time()}), encoding='utf-8')

    recovered = jobs.recover_interrupted()
    assert [r['id'] for r in recovered] == ['dead']
    record = jobs.get('dead')
    assert record['status'] == 'interrupted' and record['owned'] == {} and not record['seen']
    assert not temp.exists()


def test_the_iso_extraction_dies_with_the_backend(ordinary_tmp, monkeypatch):
    """A crash must not leave MexCLI writing into the temp project the next
    start removes: the extraction is tied to the backend (core.child_procs)."""
    from shared.vanilla_extract import first_run_setup

    class _Done:
        stdout, returncode = iter(()), 0

        def wait(self):
            return 0

    tied = []
    monkeypatch.setattr(first_run_setup.subprocess, 'Popen', lambda *a, **k: _Done())
    monkeypatch.setattr(first_run_setup, 'own', lambda proc: tied.append(proc) or proc)
    engine = first_run_setup.FirstRunSetup(ordinary_tmp / 'project', ordinary_tmp / 'mexcli.exe',
                                           storage_path=ordinary_tmp / 'storage')
    engine._extract_iso('vanilla.iso', ordinary_tmp)
    assert len(tied) == 1 and isinstance(tied[0], _Done)


def test_the_engine_hands_its_temp_project_to_the_job_before_extracting(ordinary_tmp, monkeypatch):
    """The job owns the folder from the moment it exists, so a crash during the
    1-2 minute extraction still has it removed at the next start."""
    import tempfile
    from shared.vanilla_extract import first_run_setup
    monkeypatch.setattr(tempfile, 'tempdir', str(ordinary_tmp))
    engine = first_run_setup.FirstRunSetup(ordinary_tmp / 'project', ordinary_tmp / 'mexcli.exe',
                                           storage_path=ordinary_tmp / 'storage')
    monkeypatch.setattr(engine, '_copy_bundled_sheik_assets', lambda: None)
    monkeypatch.setattr(engine, '_copy_bundled_sounds', lambda: None)
    order = []

    def extract(iso_path, temp_dir, progress=None):
        order.append(('extract', temp_dir, temp_dir.is_dir()))
        return {'success': False, 'error': 'mexcli create failed'}
    monkeypatch.setattr(engine, '_extract_iso', extract)

    result = engine.run_setup('vanilla.iso', on_temp_dir=lambda path: order.append(('owned', path)))
    assert result == {'success': False, 'error': 'mexcli create failed'}
    (step1, owned), (step2, extracted_into, existed) = order
    assert (step1, step2) == ('owned', 'extract')
    assert owned == extracted_into and existed
    assert owned.name.startswith('nucleus_setup_')
    assert not owned.exists()          # the engine's own cleanup still ran


def test_setup_cleanup_only_removes_its_own_temp_project(ordinary_tmp):
    mine = ordinary_tmp / 'nucleus_setup_abc'
    (mine / 'files').mkdir(parents=True)
    other = ordinary_tmp / 'My Project'
    other.mkdir()
    named_but_not_temp = ordinary_tmp / 'nucleus_setup_kept'
    named_but_not_temp.mkdir()
    assert setup._clean_setup('temp', str(mine)) is None
    assert setup._clean_setup('temp', str(other)) is None
    assert setup._clean_setup('upload', str(named_but_not_temp)) is None
    assert setup._clean_setup('temp', str(ordinary_tmp / 'nucleus_setup_gone')) is None
    assert not mine.exists()
    assert other.exists() and named_but_not_temp.exists()
