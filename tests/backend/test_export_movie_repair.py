"""The shared UI/Randall exporter repairs old stripped projects before writing."""
from contextlib import nullcontext
from pathlib import Path

import pytest

import core.state as core_state
import projects.install.export_job as export_mod
from core import jobs, movie_stubs


@pytest.mark.parametrize('texture_pack', [False, True])
def test_shared_export_repairs_movies_in_the_project_it_writes(
        tmp_path, monkeypatch, texture_pack):
    import mexcli.project
    import shared.rendering.csp_pool
    from projects.install import fsm_patcher
    from shared.vanilla_extract import vanilla_refs

    project = tmp_path / 'chosen' / 'project.mexproj'
    files = project.parent / 'files'
    files.mkdir(parents=True)
    project.write_text('{}')
    (files / 'MvEndWolf.mth').write_bytes(b'custom movie')
    output = tmp_path / 'output'
    repaired = []
    written_from = []

    def repair(directory, *, vanilla_iso):
        assert vanilla_iso == tmp_path / 'vanilla.iso'
        directory = Path(directory)
        repaired.append(directory)
        (directory / 'MvEndMario.mth').write_bytes(b'restored movie')
        return {'restored': ['MvEndMario.mth'], 'unresolved': []}

    class Manager:
        def __init__(self, project_path, **kwargs):
            self.project_path = Path(project_path)

        def list_fighters(self):
            return []

        def recompile_csps(self):
            return {}

        def export_iso(self, destination, *args):
            written_files = self.project_path.parent / 'files'
            written_from.append(self.project_path.parent)
            assert repaired == [written_files]
            assert (written_files / 'MvEndMario.mth').read_bytes() == b'restored movie'
            assert (written_files / 'MvEndWolf.mth').read_bytes() == b'custom movie'
            assert (written_files != files) == texture_pack
            Path(destination).write_bytes(b'exported disc')
            return {'success': True}

    monkeypatch.setattr(export_mod, 'OUTPUT_PATH', output)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(core_state, 'get_socketio', lambda: None)
    monkeypatch.setattr(export_mod, 'ensure_required_gecko_codes', lambda path: None)
    monkeypatch.setattr(fsm_patcher, 'apply_project_fsm', lambda *args: 0)
    monkeypatch.setattr(movie_stubs, 'restore_missing_movies', repair)
    monkeypatch.setattr(vanilla_refs, 'known_vanilla_iso', lambda: tmp_path / 'vanilla.iso')
    monkeypatch.setattr(mexcli.project, 'MexManager', Manager)
    monkeypatch.setattr(shared.rendering.csp_pool, 'active_pool', lambda **kwargs: nullcontext())
    monkeypatch.setattr(export_mod, 'slippi_user_dir', lambda path: tmp_path / 'dolphin')

    result = export_mod.run_export_job(
        {'filename': 'test.iso', 'texturePackMode': texture_pack,
         'slippiDolphinPath': str(tmp_path / 'dolphin')},
        background=False, project_path=project, mex_manager=Manager(project))
    record = export_mod.export_job(result['artifactId'])
    assert record['status'] == 'done', record
    assert Path(record['result']['path']).read_bytes() == b'exported disc'
    assert (files / 'MvEndMario.mth').exists() != texture_pack
    # texture-pack mode's project copy was the job's; its end removed it
    assert record['owned'] == {}
    assert written_from[0].exists() != texture_pack
