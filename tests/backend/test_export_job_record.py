"""The ISO export is an `iso_export` job (core/jobs.py): its record is the one
place its progress and outcome live, and it owns its half-written ISO and
texture-pack mode's project copy until it ends."""
from contextlib import nullcontext
from pathlib import Path

import pytest

import core.state as core_state
import projects.install.export_job as export_mod
from core import critical_ops, jobs


class _RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None):
        self.events.append((event, data))


@pytest.fixture
def exporter(tmp_path, monkeypatch):
    """run_export_job against a fake MexCLI manager, with records under tmp_path."""
    import mexcli.project
    import shared.rendering.csp_pool
    from core import movie_stubs
    from projects.install import fsm_patcher
    from shared.vanilla_extract import vanilla_refs

    project = tmp_path / 'build' / 'project.mexproj'
    (project.parent / 'files').mkdir(parents=True)
    project.write_text('{}')
    sock = _RecordingSocket()

    class Manager:
        fail_with = None

        def __init__(self, project_path, **kwargs):
            self.project_path = Path(project_path)

        def list_fighters(self):
            return []

        def recompile_csps(self):
            return {}

        def export_iso(self, destination, progress_callback=None, *args):
            if progress_callback:
                progress_callback(40, 'Writing ISO')
            Path(destination).write_bytes(b'half a disc')
            if Manager.fail_with:
                raise RuntimeError(Manager.fail_with)
            Path(destination).write_bytes(b'exported disc')
            return {'success': True}

    monkeypatch.setattr(export_mod, 'OUTPUT_PATH', tmp_path / 'output')
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(core_state, 'get_socketio', lambda: sock)
    monkeypatch.setattr(export_mod, 'ensure_required_gecko_codes', lambda path: None)
    monkeypatch.setattr(fsm_patcher, 'apply_project_fsm', lambda *args: 0)
    monkeypatch.setattr(movie_stubs, 'restore_missing_movies',
                        lambda directory, **kwargs: {'restored': [], 'unresolved': []})
    monkeypatch.setattr(vanilla_refs, 'known_vanilla_iso', lambda: None)
    monkeypatch.setattr(mexcli.project, 'MexManager', Manager)
    monkeypatch.setattr(shared.rendering.csp_pool, 'active_pool', lambda **kwargs: nullcontext())
    monkeypatch.setattr(export_mod, 'slippi_user_dir', lambda path: tmp_path / 'dolphin')

    def run(**options):
        return export_mod.run_export_job(
            {'filename': 'game.iso', **options}, background=False,
            project_path=project, mex_manager=Manager(project))

    run.Manager = Manager
    run.events = sock.events
    run.artifacts = tmp_path / 'output' / 'artifacts'
    return run


def test_a_finished_export_is_a_done_record_with_its_artifact(exporter):
    started = exporter()
    record = export_mod.export_job(started['artifactId'])
    assert record['status'] == 'done'
    assert record['progress'] == 1.0
    assert record['result']['filename'] == 'game.iso'
    assert Path(record['result']['path']) == exporter.artifacts / f"{started['artifactId']}.iso"
    assert Path(record['result']['path']).read_bytes() == b'exported disc'
    assert record['owned'] == {}
    # progress went out as the export's own job events
    assert any(name == 'job' and data['id'] == started['artifactId'] and data['progress'] == 0.4
               for name, data in exporter.events)


@pytest.mark.parametrize('texture_pack', [False, True])
def test_a_failed_export_is_a_failed_record_and_leaves_nothing(exporter, texture_pack):
    # F-G-1: a build that dies is a failed record carrying the error, which is
    # what the window reads; its half-written ISO and project copy are gone.
    exporter.Manager.fail_with = 'CSS heap overflow'
    started = exporter(texturePackMode=texture_pack, slippiDolphinPath='dolphin')
    record = export_mod.export_job(started['artifactId'])
    assert record['status'] == 'failed'
    assert 'CSS heap overflow' in record['error']
    assert record['owned'] == {}
    assert list(exporter.artifacts.iterdir()) == []
    assert critical_ops.active_ops() == []


def test_export_cleanup_after_a_death_removes_only_its_own_files(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(core_state, 'get_socketio', lambda: None)
    staging = tmp_path / 'build_dead.part.iso'
    staging.write_bytes(b'half a disc')
    temp_project = tmp_path / 'nucleus_texexport_abc'
    (temp_project / 'files').mkdir(parents=True)
    not_ours = tmp_path / 'game.iso'
    not_ours.write_bytes(b'somebody else')

    job = jobs.Job(export_mod.EXPORT_KIND, job_id='build_dead')
    job.status = 'running'
    job.owned = {'staging': str(staging), 'temp_project': str(temp_project),
                 'other': str(not_ours)}
    record = job.snapshot()
    record['owner'] = {'pid': 999999999, 'created': 1.0}
    jobs._write(record)

    assert [r['id'] for r in jobs.recover_interrupted()] == ['build_dead']
    assert export_mod.export_job('build_dead')['status'] == 'interrupted'
    assert not staging.exists()
    assert not temp_project.exists()
    assert not_ours.read_bytes() == b'somebody else'


def test_an_export_holds_shutdown_while_it_writes_and_lets_go_after(exporter, monkeypatch):
    """A window closed mid-build must not kill the backend under a half-written ISO."""
    held = []
    real_export = exporter.Manager.export_iso

    def export_iso(self, destination, progress_callback=None, *args):
        held.append(critical_ops.active_ops())
        return real_export(self, destination, progress_callback, *args)
    monkeypatch.setattr(exporter.Manager, 'export_iso', export_iso)
    exporter()
    assert held == [['ISO export']]
    assert critical_ops.active_ops() == []


@pytest.mark.parametrize('fail_with', [None, 'CSS heap overflow'])
def test_delivery_reads_the_export_outcome_from_its_job_record(exporter, monkeypatch, tmp_path, fail_with):
    """Randall's delivery runs the same export inline and reports what its
    record says: complete with the artifact, or failed with the error."""
    import mexcli.project
    from randall.delivery import deliver_steps
    monkeypatch.setattr(mexcli.project, 'MexManager',
                        lambda cli, path: exporter.Manager(path))
    exporter.Manager.fail_with = fail_with
    project = tmp_path / 'build' / 'project.mexproj'
    outcome = deliver_steps._default_export({'path': str(project)}, {'filename': 'game.iso'})
    record = export_mod.export_job(outcome['artifactId'])
    if fail_with:
        assert record['status'] == 'failed'
        assert outcome['state'] == 'failed' and fail_with in outcome['error']
        assert outcome['path'] is None
    else:
        assert record['status'] == 'done'
        assert outcome['state'] == 'complete' and outcome['error'] is None
        assert Path(outcome['path']) == exporter.artifacts / f"{outcome['artifactId']}.iso"
        assert Path(outcome['path']).read_bytes() == b'exported disc'
        assert outcome['filename'] == 'game.iso'
