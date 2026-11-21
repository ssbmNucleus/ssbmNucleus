"""save_iso lifecycle guards (bugreport-968a8ba8).

A real 0.7.2 user looped on raw FileNotFoundError 500s from /export/save:
the build writes output/<filename> in place over minutes, the viewer freezes
the timestamped filename when the export modal opens (so a restarted export
rebuilds the SAME file), and save_iso had no idea whether the file it was
copying was finished, mid-write, or from a build that died. These tests pin
the fix: the export's job record (core/jobs.py) is consulted before the copy,
a verification step so a dead build can't finish as done, and clear errors
(plus one retry) around the destination write.
"""
from tests.paths import REPO
import inspect
import io
import shutil
import threading
import uuid
from pathlib import Path

import pytest
from flask import Flask

import core.state as core_state
import projects.install.export_job as export_mod
from core import jobs, playable_iso
from projects.install.export_job import _raise_if_export_failed
from projects.routes.export import export_bp
from shared.routes.jobs import jobs_bp


class _RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None):
        self.events.append((event, data))


@pytest.fixture
def export_client(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'artifacts').mkdir()
    monkeypatch.setattr(export_mod, 'OUTPUT_PATH', output)
    # job records are module-global and on disk; isolate each test
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    sock = _RecordingSocket()
    monkeypatch.setattr(core_state, 'get_socketio', lambda: sock)
    # no real waiting between copy retries
    monkeypatch.setattr(export_mod.time, 'sleep', lambda s: None)
    app = Flask(__name__)
    app.register_blueprint(export_bp)
    app.register_blueprint(jobs_bp)
    client = app.test_client()
    client.output = output
    client.events = sock.events
    client.dest_dir = tmp_path / 'dest'
    client.dest_dir.mkdir()
    return client


def save(client, filename='game.iso', destination=None, artifact_id='artifact-1'):
    if destination is None:
        destination = str(client.dest_dir / filename)
    return client.post('/api/mex/export/save',
                       json={'artifactId': artifact_id, 'filename': filename,
                             'destination': destination})


def finish_export(artifact_id='artifact-1', result=None, error=None):
    """Record an export job that ended done (with `result`) or failed (`error`)."""
    def run(job):
        if error:
            raise RuntimeError(error)
        return result
    return jobs.run_inline(export_mod.EXPORT_KIND, run, job_id=artifact_id)


def building_export(artifact_id='artifact-1'):
    """An export job this process is still running."""
    job = jobs.Job(export_mod.EXPORT_KIND, job_id=artifact_id)
    job.status = 'running'
    jobs._jobs[job.id] = job
    return job


def complete_artifact(client, data=b'data', artifact_id='artifact-1'):
    path = client.output / 'artifacts' / f'{artifact_id}.iso'
    path.write_bytes(data)
    finish_export(artifact_id, result={'path': str(path), 'filename': 'game.iso'})
    return path


def test_export_progress_is_the_job_record(export_client):
    job = building_export()
    job.progress(0.37, 'Writing ISO…')

    resp = export_client.get('/api/jobs/artifact-1')
    assert resp.status_code == 200
    record = resp.get_json()['job']
    assert record['kind'] == 'iso_export'
    assert record['status'] == 'running'
    assert record['progress'] == pytest.approx(0.37)
    assert record['detail'] == 'Writing ISO…'
    # one event, and it always names its job
    assert export_client.events
    assert all(name == 'job' and data['id'] == 'artifact-1'
               for name, data in export_client.events)
    # the export's own status route is gone
    assert export_client.get('/api/mex/export/status/artifact-1').status_code == 404


def test_queued_export_captures_request_project_before_ui_switch(export_client, monkeypatch, tmp_path):
    current = {'path': tmp_path / 'first.mexproj', 'manager': object()}
    first = dict(current)
    queued = []
    monkeypatch.setattr(export_mod, 'get_current_project_path', lambda: current['path'])
    monkeypatch.setattr(export_mod, 'get_mex_manager', lambda: current['manager'])
    class DeferredThread:
        def __init__(self, target=None, args=(), **kwargs): queued.append(args)
        def start(self): pass
    monkeypatch.setattr(jobs.threading, 'Thread', DeferredThread)
    response = export_client.post('/api/mex/export/start', json={'filename': 'test.iso'})
    assert response.status_code == 200
    artifact_id = response.get_json()['artifactId']
    assert jobs.get(artifact_id)['status'] == 'queued'
    current.update(path=tmp_path / 'second.mexproj', manager=object())
    # Inspect the queued job's captured inputs without launching any native
    # executable. Both the path and manager must refer to the first project.
    job, fn, critical = queued[0]
    assert job.id == artifact_id
    assert critical is True
    captured = inspect.getclosurevars(fn).nonlocals
    assert captured['export_project_path'] == first['path']
    assert captured['export_manager'] is first['manager']


def test_failed_export_is_answered_as_a_record_not_an_error(export_client):
    # F-G-1: the old status route answered a failed build with success=false,
    # which the window's API client threw away as a failed request.
    finish_export(error='MexCLI failed')

    failed = export_client.get('/api/jobs/artifact-1')
    assert failed.status_code == 200
    body = failed.get_json()
    assert body['success'] is True
    assert body['job']['status'] == 'failed'
    assert body['job']['error'] == 'MexCLI failed'

    missing = export_client.get('/api/jobs/unknown')
    assert missing.status_code == 404
    assert missing.get_json()['success'] is False


def test_socket_delivery_failure_does_not_change_terminal_state(
        export_client, monkeypatch):
    class BrokenSocket:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError('connection lost')

    monkeypatch.setattr(core_state, 'get_socketio', lambda: BrokenSocket())
    finish_export(result={'path': 'x'})

    record = export_mod.export_job('artifact-1')
    assert record['status'] == 'done'
    assert record['error'] is None


def test_save_while_building_returns_409_not_500(export_client):
    # the file EXISTS mid-build (GCILib writes it in place) — existence must not
    # be treated as done
    building_export()

    resp = save(export_client)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['success'] is False
    assert body['status'] == 'running'
    assert 'still building' in body['error']
    # and nothing was written to the destination
    assert list(export_client.dest_dir.iterdir()) == []


def test_save_after_failed_build_surfaces_build_error(export_client):
    finish_export(error='MexCLI reported an export error')

    resp = save(export_client)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['status'] == 'failed'
    assert 'MexCLI reported an export error' in body['error']


def test_save_reads_a_finished_export_from_its_record_on_disk(export_client):
    complete_artifact(export_client, b'finished iso bytes')
    jobs._jobs.clear()   # another process, or after this one's memory is gone

    resp = save(export_client)
    assert resp.status_code == 200
    assert (export_client.dest_dir / 'game.iso').read_bytes() == b'finished iso bytes'


def test_save_unknown_file_gets_actionable_404(export_client):
    resp = save(export_client, filename='never-exported.iso')
    assert resp.status_code == 404
    assert 'Run the export again' in resp.get_json()['error']


def test_save_success_after_complete(export_client):
    complete_artifact(export_client, b'finished iso bytes')

    resp = save(export_client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['bytes'] == len(b'finished iso bytes')
    dest = Path(body['path'])
    assert dest.read_bytes() == b'finished iso bytes'
    assert list(dest.parent.glob(f'{dest.name}.*.part')) == []


def test_save_without_registry_entry_is_rejected(export_client):
    (export_client.output / 'game.iso').write_bytes(b'data')

    resp = save(export_client)
    assert resp.status_code == 404


def test_save_retries_transient_destination_failure(export_client, monkeypatch):
    # the report shows the identical save failing with FileNotFoundError then
    # succeeding 23s later — one retry must absorb that
    complete_artifact(export_client)

    real_copy = shutil.copyfile
    calls = {'n': 0}

    def flaky_copy(src, dst):
        calls['n'] += 1
        if calls['n'] == 1:
            raise FileNotFoundError(2, 'No such file or directory', str(dst))
        return real_copy(src, dst)

    monkeypatch.setattr(export_mod.shutil, 'copyfile', flaky_copy)
    resp = save(export_client)
    assert resp.status_code == 200
    assert calls['n'] == 2


def test_save_persistent_destination_failure_explains_itself(export_client, monkeypatch):
    complete_artifact(export_client)

    def blocked_copy(src, dst):
        raise PermissionError(13, 'Access is denied', str(dst))

    monkeypatch.setattr(export_mod.shutil, 'copyfile', blocked_copy)
    resp = save(export_client)
    assert resp.status_code == 500
    err = resp.get_json()['error']
    assert 'antivirus' in err
    assert 'different folder' in err


def test_save_source_vanished_mid_copy_explains_itself(export_client, monkeypatch):
    # export restarted with the same name after the state check: the source can
    # vanish under the copy
    src = complete_artifact(export_client)

    def vanishing_copy(_src, dst):
        src.unlink(missing_ok=True)
        raise FileNotFoundError(2, 'No such file or directory', str(_src))

    monkeypatch.setattr(export_mod.shutil, 'copyfile', vanishing_copy)
    resp = save(export_client)
    assert resp.status_code == 500
    assert 'disappeared' in resp.get_json()['error']


def test_save_missing_destination_dir_still_400(export_client):
    complete_artifact(export_client)
    resp = save(export_client,
                destination=str(export_client.dest_dir / 'nope' / 'game.iso'))
    assert resp.status_code == 400


# ---- a Save whose ownership marker failed to write can be retried (F-G-9) ----

def _fail_final_markers(monkeypatch, times):
    """Make the final ownership-marker write (the one after the replace) fail
    `times` times; every other marker write goes through."""
    real_write = playable_iso.write_marker
    failures = {'left': times}

    def write_marker(output_path, payload):
        final = 'pending_digest' not in payload and 'superseded_at' not in payload
        if final and failures['left'] > 0:
            failures['left'] -= 1
            raise PermissionError(13, 'Access is denied', str(output_path))
        return real_write(output_path, payload)

    monkeypatch.setattr(playable_iso, 'write_marker', write_marker)
    return failures


def test_a_failed_final_marker_is_finished_by_the_save_retry(export_client, monkeypatch):
    dest = export_client.dest_dir / 'game.iso'
    dest.write_bytes(b'the old game')
    playable_iso.write_marker(dest, {'output_digest': playable_iso.digest_file(dest)})
    complete_artifact(export_client, b'the new game')
    _fail_final_markers(monkeypatch, times=1)

    resp = save(export_client)

    assert resp.status_code == 200
    assert dest.read_bytes() == b'the new game'
    marker = playable_iso.read_marker(dest)
    assert marker['output_digest'] == playable_iso.digest_file(dest)
    assert 'pending_digest' not in marker
    # The retry only finished the marker: the one previous copy is the old game.
    previous = list(export_client.dest_dir.glob('game.previous-*.iso'))
    assert [p.read_bytes() for p in previous] == [b'the old game']
    assert playable_iso.produced_by_nucleus(previous[0])


def test_a_save_that_failed_on_its_marker_can_be_saved_again(export_client, monkeypatch):
    complete_artifact(export_client, b'the new game')
    failures = _fail_final_markers(monkeypatch, times=2)

    first = save(export_client)
    assert first.status_code == 500
    dest = export_client.dest_dir / 'game.iso'
    assert dest.read_bytes() == b'the new game'
    # The copy that landed is still ours, not a foreign file Save refuses.
    assert playable_iso.produced_by_nucleus(dest)

    assert failures['left'] == 0
    again = save(export_client)
    assert again.status_code == 200
    assert 'pending_digest' not in playable_iso.read_marker(dest)


def test_a_failed_replace_puts_the_old_marker_back(export_client, monkeypatch):
    dest = export_client.dest_dir / 'game.iso'
    dest.write_bytes(b'the old game')
    playable_iso.write_marker(dest, {'output_digest': playable_iso.digest_file(dest),
                                     'source': 'export_save'})
    complete_artifact(export_client, b'the new game')
    real_replace = playable_iso.file_retry.replace

    def replace(src, dst):
        if Path(dst) == dest:
            raise PermissionError(13, 'Access is denied', str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(playable_iso.file_retry, 'replace', replace)
    resp = save(export_client)

    assert resp.status_code == 500
    assert dest.read_bytes() == b'the old game'
    marker = playable_iso.read_marker(dest)
    assert 'pending_digest' not in marker
    assert marker['output_digest'] == playable_iso.digest_file(dest)


# ---- _raise_if_export_failed: a dead build must not finish as done ----

def test_export_error_dict_raises(tmp_path):
    iso = tmp_path / 'out.iso'
    iso.write_bytes(b'x')
    with pytest.raises(RuntimeError, match='CSS heap overflow'):
        _raise_if_export_failed(
            {'success': False, 'status': 'error', 'error': 'CSS heap overflow'}, iso)


def test_export_success_but_no_iso_raises(tmp_path):
    with pytest.raises(RuntimeError, match='no ISO'):
        _raise_if_export_failed({'success': True}, tmp_path / 'missing.iso')


def test_export_success_but_empty_iso_raises(tmp_path):
    iso = tmp_path / 'out.iso'
    iso.write_bytes(b'')
    with pytest.raises(RuntimeError, match='no ISO'):
        _raise_if_export_failed({'success': True}, iso)


def test_export_genuine_success_passes(tmp_path):
    iso = tmp_path / 'out.iso'
    iso.write_bytes(b'iso')
    _raise_if_export_failed({'success': True, 'status': 'completed'}, iso)


# ---- mexcli.project: MexCLI error JSON with exit code 0 must raise ----

class FakeProcess:
    def __init__(self, stdout_lines, returncode):
        self.stdout = iter(stdout_lines)
        self.stderr = None
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def mex(monkeypatch):
    from mexcli import project
    parent = REPO / 'app' / 'scratch' / 'mexcli-project-tests'
    parent.mkdir(parents=True, exist_ok=True)
    child = parent / str(uuid.uuid4())
    child.mkdir()
    try:
        cli = child / 'mexcli.exe'
        cli.write_bytes(b'')
        proj = child / 'proj.mexproj'
        proj.write_text('{}')
        yield project, project.MexManager(str(cli), str(proj))
    finally:
        resolved = child.resolve()
        if resolved.parent == parent.resolve() and resolved.name:
            shutil.rmtree(resolved, ignore_errors=True)


def test_mexcli_project_error_json_with_exit_zero_raises(mex, monkeypatch):
    project, manager = mex
    fake = FakeProcess(
        ['{"status": "error", "success": false, "error": "export blew up"}\n'],
        returncode=0)
    monkeypatch.setattr(project.subprocess, 'Popen',
                        lambda *a, **kw: fake)
    with pytest.raises(project.MexManagerError, match='export blew up'):
        manager.export_iso('out.iso')


def test_mexcli_project_nonzero_exit_prefers_json_error(mex, monkeypatch):
    project, manager = mex
    fake = FakeProcess(
        ['{"status": "error", "success": false, "error": "export blew up"}\n'],
        returncode=1)
    monkeypatch.setattr(project.subprocess, 'Popen',
                        lambda *a, **kw: fake)
    with pytest.raises(project.MexManagerError, match='export blew up'):
        manager.export_iso('out.iso')


def test_mexcli_project_clean_success_unchanged(mex, monkeypatch):
    project, manager = mex
    fake = FakeProcess(
        ['{"status": "completed", "success": true, "outputPath": "out.iso"}\n'],
        returncode=0)
    monkeypatch.setattr(project.subprocess, 'Popen',
                        lambda *a, **kw: fake)
    result = manager.export_iso('out.iso')
    assert result['success'] is True


def test_mexcli_export_process_is_handed_to_on_spawn(mex, monkeypatch):
    # The app ties it to the backend (app.py sets on_spawn to child_procs.own),
    # so a crash does not leave MexCLI writing the ISO.
    project, manager = mex
    fake = FakeProcess(
        ['{"status": "completed", "success": true, "outputPath": "out.iso"}\n'],
        returncode=0)
    monkeypatch.setattr(project.subprocess, 'Popen', lambda *a, **kw: fake)
    spawned = []
    monkeypatch.setattr(project, 'on_spawn', spawned.append)
    manager.export_iso('out.iso')
    assert spawned == [fake]


def test_mexcli_project_drains_stderr_while_streaming_stdout(mex, monkeypatch):
    project, manager = mex
    stderr_drained = threading.Event()

    class ConcurrentFake(FakeProcess):
        def __init__(self):
            super().__init__([], 0)

            def stdout_lines():
                assert stderr_drained.wait(1)
                yield '{"status":"completed","success":true}\n'

            self.stdout = stdout_lines()
            class Stderr:
                sent = False

                def read(self, _size):
                    if self.sent:
                        return ''
                    self.sent = True
                    stderr_drained.set()
                    return 'debug output\n'

            self.stderr = Stderr()

    monkeypatch.setattr(project.subprocess, 'Popen', lambda *a, **kw: ConcurrentFake())
    assert manager.export_iso('out.iso')['success'] is True
    assert stderr_drained.is_set()


def test_mexcli_project_bad_callback_and_json_array_do_not_stop_drain(mex, monkeypatch):
    project, manager = mex
    fake = FakeProcess([
        '["valid", "but not a result object"]\n',
        '{"status":"progress","percentage":25,"message":"working"}\n',
        '{"status":"completed","success":true,"outputPath":"out.iso"}\n',
    ], 0)
    fake.stderr = io.StringIO('')
    monkeypatch.setattr(project.subprocess, 'Popen', lambda *a, **kw: fake)

    def broken_callback(_percentage, _message):
        raise RuntimeError('display disconnected')

    result = manager.export_iso('out.iso', progress_callback=broken_callback)
    assert result['success'] is True
    assert result['outputPath'] == 'out.iso'


def test_mexcli_project_pipe_reader_failure_is_not_reported_as_success(mex, monkeypatch):
    project, manager = mex

    class BrokenStdout:
        def __iter__(self):
            raise OSError('pipe broke')

    class RunningFake(FakeProcess):
        def __init__(self):
            super().__init__([], None)
            self.terminated = False

        def wait(self, timeout=None):
            if not self.terminated:
                raise project.subprocess.TimeoutExpired('mexcli', timeout)
            self.returncode = -1
            return self.returncode

        def terminate(self):
            self.terminated = True

    fake = RunningFake()
    fake.stdout = BrokenStdout()
    fake.stderr = io.StringIO('')
    monkeypatch.setattr(project.subprocess, 'Popen', lambda *a, **kw: fake)
    with pytest.raises(project.MexManagerError, match='stdout reader failed: pipe broke'):
        manager.export_iso('out.iso')
    assert fake.terminated is True


def test_mexcli_project_timeout_stops_only_owned_process(mex, monkeypatch):
    project, manager = mex

    class TimedOutFake(FakeProcess):
        def __init__(self):
            super().__init__([], None)
            self.stderr = io.StringIO('')
            self.terminated = False
            self.killed = False

        def wait(self, timeout=None):
            if not self.terminated:
                raise project.subprocess.TimeoutExpired('mexcli', timeout)
            self.returncode = -1
            return self.returncode

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    fake = TimedOutFake()
    monkeypatch.setattr(project.subprocess, 'Popen', lambda *a, **kw: fake)
    monkeypatch.setattr(project, 'MEXCLI_EXPORT_TIMEOUT_SECONDS', 0.01)
    with pytest.raises(project.MexManagerError, match='timed out'):
        manager.export_iso('out.iso')
    assert fake.terminated is True
    assert fake.killed is False


def test_mexcli_project_recovers_a_pretty_printed_error(mex, monkeypatch):
    """0.8.7 shipped an export that died with an indented error JSON. The
    line-by-line reader parsed none of it, so every user saw the [DEBUG] stderr
    chatter instead of "the file is being used by another process"."""
    project, manager = mex
    fake = FakeProcess([
        '{"status":"progress","percentage":100,"message":"Done!"}\n',
        '{\n',
        '  "success": false,\n',
        '  "status": "error",\n',
        '  "error": "Failed to export ISO: in use by another process"\n',
        '}\n',
    ], returncode=1)
    fake.stderr = io.StringIO('[DEBUG] Workspace saved with compressed CSPs\n')
    monkeypatch.setattr(project.subprocess, 'Popen', lambda *a, **kw: fake)
    with pytest.raises(project.MexManagerError,
                       match='in use by another process'):
        manager.export_iso('out.iso')
