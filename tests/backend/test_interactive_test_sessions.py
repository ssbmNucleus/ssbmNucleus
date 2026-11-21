"""Exercise HTTP/job lifecycle with fake ISO builders and no emulator processes."""
from collections import OrderedDict
from pathlib import Path
import threading
import types
from uuid import uuid4

from flask import Flask
import pytest

from core import jobs
import projects.routes.test_in_game as tig
import projects.install.test_inputs as test_inputs
import shared.ingame.boot as boot
import shared.ingame.runner as runner
import projects.install.test_build as builds


@pytest.fixture
def job(tmp_path, monkeypatch):
    iso = tmp_path / 'base.iso'
    iso.write_bytes(b'synthetic ISO')
    (tmp_path / 'Fox').mkdir()
    (tmp_path / 'Fox' / 'skin.zip').write_bytes(b'synthetic ZIP')
    monkeypatch.setattr(tig, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(test_inputs, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(tig, '_active_test_session', None)
    monkeypatch.setattr(tig, '_test_sessions', OrderedDict())
    monkeypatch.setattr(tig, '_cancelled_test_ids', OrderedDict())
    monkeypatch.setattr(tig, '_paired_nana_zip', lambda *_: None)
    monkeypatch.setattr(boot, 'dolphin_running', lambda: [])
    pending, events, calls = [], [], []

    class DeferredThread:
        def __init__(self, target, args=(), name=None, daemon=None):
            self.target, self.args = target, args

        def start(self):
            pending.append(lambda: self.target(*self.args))

    monkeypatch.setattr(jobs, 'threading', types.SimpleNamespace(
        Thread=DeferredThread, Event=threading.Event))
    monkeypatch.setattr(tig, 'get_socketio', lambda: types.SimpleNamespace(
        emit=lambda name, payload: events.append((name, payload))))

    def build(*args, **kwargs):
        calls.append(('build', kwargs))
        Path(kwargs['out_iso']).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs['out_iso']).write_bytes(b'test ISO')
        return 2

    def run(**kwargs):
        calls.append(('run', kwargs))
        return {'interactive': kwargs.get('interactive', False), 'success': True,
                'pass': True, 'verdict': 'stopped', 'reason': 'Session ended.'}

    monkeypatch.setattr(builds, 'build_single_costume_iso', build)
    monkeypatch.setattr(runner, 'run_test', run)
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(tig.test_in_game_bp)
    client = app.test_client()
    body = {'isoPath': str(iso), 'vanillaIsoPath': str(iso),
            'slippiDolphinPath': 'synthetic/Dolphin.exe', 'character': 'Fox', 'skinId': 'skin',
            'interactive': True, 'sessionId': str(uuid4())}
    return types.SimpleNamespace(client=client, body=body, pending=pending,
                                 events=events, calls=calls, storage=tmp_path)


def idle():
    return jobs.active_job(tig.INGAME_KIND) is None


def start(job, route='costume', **extra):
    return job.client.post(f'/api/mex/test-in-game/{route}', json={**job.body, **extra})


def status(job, session_id=None):
    return job.client.get('/api/mex/test-in-game/status',
                          query_string={'sessionId': session_id or job.body['sessionId']}).json


def stop(job, session_id=None):
    return job.client.post('/api/mex/test-in-game/stop',
                           json={'sessionId': session_id or job.body['sessionId']})


def test_stop_before_worker_prevents_build_and_launch(job):
    response = start(job)
    assert response.json['sessionId'] == job.body['sessionId']
    assert status(job)['running']
    assert stop(job).json['stopRequested']
    job.pending.pop()()
    assert not job.calls
    final = status(job)
    assert not final['running']
    assert final['lastEvent']['event'] == 'test_complete'
    assert final['lastEvent']['payload']['verdict'] == 'stopped'
    assert final['lastEvent']['payload']['success']
    assert idle()


def test_stop_during_build_finishes_build_but_never_launches(job, monkeypatch):
    def build(**kwargs):
        Path(kwargs['out_iso']).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs['out_iso']).write_bytes(b'partial fixture')
        assert stop(job).status_code == 200
        return 3

    monkeypatch.setattr(builds, 'build_single_costume_iso', build)
    start(job)
    job.pending.pop()()
    assert not job.calls
    assert not list((job.storage / 'test-builds').glob('*.iso'))
    assert status(job)['lastEvent']['payload']['verdict'] == 'stopped'


def test_stop_during_export_kills_the_export_and_reports_stopped(job, monkeypatch):
    """The build sees the session's stop check (projects.install.test_build.STOP_CHECK)
    and the export raises MexExportCancelled the moment Stop lands -- the job
    reports 'stopped' without ever launching, and the partial ISO is removed."""
    from mexcli.project import MexExportCancelled

    def build(**kwargs):
        Path(kwargs['out_iso']).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs['out_iso']).write_bytes(b'partial export')
        should_stop = builds.STOP_CHECK.get()
        assert callable(should_stop) and not should_stop()
        assert stop(job).status_code == 200
        assert should_stop(), 'Stop must be visible to the build in progress'
        raise MexExportCancelled('ISO export stopped on request')

    monkeypatch.setattr(builds, 'build_single_costume_iso', build)
    start(job)
    job.pending.pop()()
    assert not job.calls
    assert not list((job.storage / 'test-builds').glob('*.iso'))
    assert status(job)['lastEvent']['payload']['verdict'] == 'stopped'
    assert builds.STOP_CHECK.get() is None, 'stop check must not leak past the job'


def test_stop_during_the_test_base_build_reports_stopped(job, monkeypatch):
    from projects.install.pristine_base import BuildStopped

    def build(**kwargs):
        assert stop(job).status_code == 200
        assert builds.STOP_CHECK.get()()
        raise BuildStopped('Test stopped while the test project was being prepared.')

    monkeypatch.setattr(builds, 'build_single_costume_iso', build)
    start(job)
    job.pending.pop()()
    assert not job.calls
    assert status(job)['lastEvent']['payload']['verdict'] == 'stopped'


def test_build_progress_only_rises_and_log_lines_keep_the_bar(job, monkeypatch):
    def build(**kwargs):
        kwargs['progress_cb'](0, 'Preparing the test base… 0s')
        kwargs['progress_cb'](40, 'Copying the test base… 100%')
        kwargs['log']('Importing the Fox costume…')
        kwargs['progress_cb'](10, 'a late, lower report')
        Path(kwargs['out_iso']).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs['out_iso']).write_bytes(b'test ISO')
        return 2

    monkeypatch.setattr(builds, 'build_single_costume_iso', build)
    start(job)
    job.pending.pop()()
    building = [payload['percentage'] for name, payload in job.events
                if name == 'test_progress' and payload.get('stage') == 'building']
    assert building == [3, 6, 19, 19, 19]


def test_export_helper_aborts_before_starting_when_stop_is_set():
    from mexcli.project import MexExportCancelled
    calls = []
    fake_mex = types.SimpleNamespace(project_path='x',
                                     export_iso=lambda *a, **k: calls.append((a, k)))
    token = builds.STOP_CHECK.set(lambda: True)
    try:
        with pytest.raises(MexExportCancelled):
            builds._export(fake_mex, 'unused.iso', None, lambda m: None)
    finally:
        builds.STOP_CHECK.reset(token)
    assert not calls


def test_export_helper_hands_the_stop_check_to_mexcli(tmp_path):
    seen = {}

    def export_iso(out, progress, *rest, should_stop=None):
        seen['should_stop'] = should_stop
        Path(out).write_bytes(b'iso')

    fake_mex = types.SimpleNamespace(project_path=str(tmp_path), export_iso=export_iso)
    check = lambda: False
    token = builds.STOP_CHECK.set(check)
    try:
        builds._export(fake_mex, str(tmp_path / 'out.iso'), None, lambda m: None)
    finally:
        builds.STOP_CHECK.reset(token)
    assert seen['should_stop'] is check


def test_playing_snapshot_stop_signal_and_terminal_are_scoped(job, monkeypatch):
    def run(**kwargs):
        assert kwargs['interactive'] is True
        assert isinstance(kwargs['stop_event'], threading.Event)
        kwargs['on_interactive_state']({'phase': 'playing', 'controllerPort': 1,
                                        'message': 'Use controller port 1.'})
        snapshot = status(job)
        assert snapshot['status']['stage'] == 'playing'
        assert snapshot['status']['controllerPort'] == 1
        assert stop(job, str(uuid4())).status_code == 404
        assert not kwargs['stop_event'].is_set()
        assert stop(job).status_code == 200
        assert kwargs['stop_event'].is_set()
        return {'interactive': True, 'success': True, 'verdict': 'stopped', 'reason': 'Stopped.'}

    monkeypatch.setattr(runner, 'run_test', run)
    start(job)
    job.pending.pop()()
    assert all(payload['sessionId'] == job.body['sessionId'] for _, payload in job.events)
    sequences = [payload['sequence'] for _, payload in job.events]
    assert sequences == list(range(1, len(sequences) + 1))
    final = status(job)
    assert final['lastEvent']['payload']['success']
    assert not final['running']
    assert stop(job).json['running'] is False


def test_stale_stop_cannot_stop_new_session_and_id_reuse_is_rejected(job):
    old_id = job.body['sessionId']
    start(job)
    job.pending.pop()()
    assert start(job).status_code == 409
    new_id = str(uuid4())
    assert start(job, sessionId=new_id).status_code == 200
    assert stop(job, old_id).status_code == 200
    assert status(job, new_id)['stopRequested'] is False
    assert status(job, new_id)['running']
    job.pending.pop()()


def test_worker_failure_releases_slot_and_keeps_error_for_reconnect(job, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError('synthetic build failure')

    monkeypatch.setattr(builds, 'build_single_costume_iso', fail)
    start(job)
    job.pending.pop()()
    final = status(job)
    assert not final['running']
    assert final['lastEvent']['event'] == 'test_error'
    assert final['lastEvent']['payload']['error'] == 'synthetic build failure'
    record = jobs.get(job.body['sessionId'])
    assert record['status'] == 'failed' and record['error'] == 'synthetic build failure'
    assert idle()


def test_automatic_callers_keep_original_runner_contract_and_iso(job):
    response = start(job, route='start', interactive=False)
    assert response.status_code == 200 and 'sessionId' not in response.json
    job.pending.pop()()
    kwargs = next(value for kind, value in job.calls if kind == 'run')
    assert 'interactive' not in kwargs          # the automated flow, not a playable preview
    # The job's own stop, so a Cancel ends the run's Dolphin waits; not a session's.
    assert not kwargs['stop_event'].is_set()
    assert Path(job.body['isoPath']).read_bytes() == b'synthetic ISO'
    # No session, so no session events: the job record is the result.
    assert not job.events
    record = jobs.get(response.json['jobId'])
    assert record['status'] == 'done' and record['result']['verdict'] == 'stopped'


@pytest.mark.parametrize('extra', [{'sessionId': 'bad'}, {'sessionId': []}, {'interactive': 'true'}])
def test_bad_session_options_do_not_claim_slot(job, extra):
    # An empty list is invalid too, rather than silently becoming a new UUID.
    assert start(job, **extra).status_code == 400
    assert idle()
    assert not job.pending


def test_unknown_status_and_missing_stop_never_target_global_job(job):
    assert status(job)['lastEvent'] is None
    assert not status(job)['running']
    assert job.client.post('/api/mex/test-in-game/stop', json={}).status_code == 400
    capture = tig._start_ingame_job(lambda _job: None, label='Capture')
    assert stop(job).status_code == 404
    # A capture holds the slot but is not an interactive session.
    assert jobs.active_job(tig.INGAME_KIND).id == capture


def test_late_progress_cannot_replace_terminal_snapshot(job):
    start(job)
    job.pending.pop()()
    before = status(job)
    session = tig._test_sessions[job.body['sessionId']]
    tig._emit_test(tig.get_socketio(), session, 'test_progress', {'stage': 'playing'})
    assert status(job) == before


def test_pending_stop_rejects_a_late_start_without_building(job):
    response = job.client.post('/api/mex/test-in-game/stop', json={
        'sessionId': job.body['sessionId'], 'cancelPending': True})
    assert response.json['running'] is False
    assert status(job)['lastEvent']['payload']['verdict'] == 'stopped'
    assert start(job).status_code == 409
    assert not job.pending
    assert idle()


def test_pending_stop_during_process_preflight_prevents_late_worker(job, monkeypatch):
    def scanning():
        response = job.client.post('/api/mex/test-in-game/stop', json={
            'sessionId': job.body['sessionId'], 'cancelPending': True})
        assert response.json['running'] is False
        return []

    monkeypatch.setattr(boot, 'dolphin_running', scanning)
    assert start(job).status_code == 409
    assert not job.pending
    assert idle()


def test_pending_cancellation_history_is_bounded_without_evicting_active_job(job):
    start(job)
    for _ in range(270):
        response = job.client.post('/api/mex/test-in-game/stop', json={
            'sessionId': str(uuid4()), 'cancelPending': True})
        assert response.json['running'] is False
    assert len(tig._test_sessions) == 16
    assert len(tig._cancelled_test_ids) == 256
    assert status(job)['running']
    assert not status(job)['stopRequested']
    job.pending.pop()()


@pytest.mark.parametrize('route,extra,builder,manifest_key', [
    ('custom-character', {'slug': 'sample'}, 'build_custom_character_iso', 'character'),
    ('custom-character-skin', {'slug': 'sample', 'costumeIndex': 2, 'skinId': None},
     'build_custom_character_iso', 'character'),
    ('custom-stage', {'slug': 'sample'}, 'build_custom_stage_iso', 'customStage'),
    ('stage-skin', {'stageCode': 'GrNBa', 'stageFolder': 'battlefield', 'variantId': 'sample'},
     'build_stage_skin_iso', 'das'),
])
def test_all_mod_routes_pass_the_interactive_contract(job, monkeypatch, route, extra, builder, manifest_key):
    seen = []

    def build(*args, **kwargs):
        seen.append(kwargs)
        return {'name': 'Sample', 'colorIndex': 2, 'cssIcon': {'fighter': 26},
                'sssIcon': {'stageId': 40}, 'stage': 'battlefield', 'button': None}

    monkeypatch.setattr(builds, builder, build)
    assert start(job, route=route, **extra).status_code == 200
    job.pending.pop()()
    run = next(value for kind, value in job.calls if kind == 'run')
    assert run['interactive']
    assert manifest_key in run['manifest']
    if manifest_key == 'das':
        assert seen[0]['default_variant']
        assert run['manifest']['das']['defaultVariant']
