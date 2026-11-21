"""Interactive preflight uses synthetic files/processes and never starts a job."""
import threading
import types

from flask import Flask
import pytest

from core import jobs
import projects.routes.test_in_game as tig
import projects.install.test_inputs as test_inputs
import shared.ingame.boot as boot


ROUTES = [
    ('start', {}),
    ('costume', {'character': 'Fox', 'skinId': 'skin'}),
    ('custom-character', {'slug': 'synthetic'}),
    ('custom-character-skin', {'slug': 'synthetic', 'costumeIndex': 0}),
    ('custom-stage', {'slug': 'synthetic'}),
    ('stage-skin', {'stageCode': 'GrNBa', 'stageFolder': 'bf', 'variantId': 'synthetic'}),
]


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    iso = tmp_path / 'synthetic.iso'
    iso.write_bytes(b'fixture, not a real ISO')
    (tmp_path / 'Fox').mkdir()
    (tmp_path / 'Fox' / 'skin.zip').write_bytes(b'fixture, not a real ZIP')
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(test_inputs, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(tig, '_paired_nana_zip', lambda *args: None)
    started = []

    class DeferredThread:
        def __init__(self, target, args=(), name=None, daemon=None):
            self.target = target

        def start(self):
            started.append(self.target)  # Deliberately do not execute ISO/Dolphin work.

    monkeypatch.setattr(jobs, 'threading', types.SimpleNamespace(
        Thread=DeferredThread, Event=threading.Event))
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(tig.test_in_game_bp)
    return app.test_client(), tmp_path, started, {
        'isoPath': str(iso), 'vanillaIsoPath': str(iso), 'slippiDolphinPath': 'synthetic/Dolphin.exe'}


@pytest.mark.parametrize('route,extra', ROUTES)
def test_open_dolphin_rejected_before_job_or_output_directories(scenario, monkeypatch, route, extra):
    client, storage, started, body = scenario
    monkeypatch.setattr(boot, 'dolphin_running', lambda: ['synthetic-pid'])
    response = client.post(f'/api/mex/test-in-game/{route}', json={**body, **extra})
    assert response.status_code == 409
    assert response.json['code'] == 'dolphin_open'
    assert response.json['dolphinOpen'] is True
    assert 'start the test again' in response.json['error']
    assert not started
    assert not (storage / 'test-runs').exists()
    assert not (storage / 'test-builds').exists()
    assert jobs.list_jobs(kind=tig.INGAME_KIND) == []


@pytest.mark.parametrize('route,extra', ROUTES)
def test_clear_preflight_starts_normal_job_and_reserves_slot(scenario, monkeypatch, route, extra):
    client, _storage, started, body = scenario
    monkeypatch.setattr(boot, 'dolphin_running', lambda: [])
    response = client.post(f'/api/mex/test-in-game/{route}', json={**body, **extra})
    assert response.status_code == 200
    assert response.json['success'] is True
    assert len(started) == 1
    assert jobs.active_job(tig.INGAME_KIND).id == response.json['jobId']


def test_existing_test_conflict_keeps_its_slot_and_does_not_scan_processes(scenario, monkeypatch):
    client, _storage, started, body = scenario
    running = tig._start_ingame_job(lambda job: None, label='Capture')
    monkeypatch.setattr(boot, 'dolphin_running', lambda: pytest.fail('Existing slot must win before process scan'))
    response = client.post('/api/mex/test-in-game/start', json=body)
    assert response.status_code == 409
    assert 'already running' in response.json['error']
    assert response.json['jobId'] == running
    assert jobs.active_job(tig.INGAME_KIND).id == running
    assert len(started) == 1


def test_unexpected_detector_error_releases_claimed_slot(scenario, monkeypatch):
    client, _storage, started, body = scenario

    def fail():
        raise RuntimeError('synthetic scan failure')

    monkeypatch.setattr(boot, 'dolphin_running', fail)
    with pytest.raises(RuntimeError, match='synthetic scan failure'):
        client.post('/api/mex/test-in-game/start', json=body)
    assert jobs.list_jobs(kind=tig.INGAME_KIND) == []
    assert not started
