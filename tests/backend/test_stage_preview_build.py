"""Selected stage bytes load without controller holds in manual preview ISOs."""
from pathlib import Path
import zipfile

import pytest

import projects.install.test_build as builds


@pytest.mark.parametrize('code,extension', [('GrNBa', '.dat'), ('GrPs', '.usd')])
@pytest.mark.parametrize('manual', [False, True])
def test_only_manual_preview_replaces_default_stage(tmp_path, monkeypatch, code, extension, manual):
    source = tmp_path / 'vault' / 'stage'
    source.mkdir(parents=True)
    archive = source / 'skin.zip'
    selected = b'synthetic selected stage bytes'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('stage' + extension, selected)
    original_archive = archive.read_bytes()

    framework = tmp_path / 'app' / 'utility' / 'DynamicAlternateStages'
    framework.mkdir(parents=True)
    (framework / (code + extension)).write_bytes(b'synthetic DAS loader')
    project = tmp_path / 'project'
    files = project / 'files'
    files.mkdir(parents=True)
    (files / (code + extension)).write_bytes(b'original vanilla stage')
    monkeypatch.setattr(builds, 'DAS_STORAGE_PATH', source.parent)
    monkeypatch.setattr(builds, 'BASE_PATH', tmp_path / 'app')
    monkeypatch.setattr(builds, 'create_temp_project', lambda *_a, **_k: (project, project / 'test.mex'))
    monkeypatch.setattr(builds, 'MexManager', lambda *_a: object())
    exported = {}

    def export(*_args):
        exported.update({str(p.relative_to(files)): p.read_bytes()
                         for p in files.rglob('*') if p.is_file()})

    monkeypatch.setattr(builds, '_export', export)
    result = builds.build_stage_skin_iso('synthetic.iso', code, 'stage', 'skin',
                                         str(tmp_path / 'output.iso'), default_variant=manual)
    default = str(Path(code) / 'vanilla.dat')
    alternate = str(Path(code) / 'NucleusTestSkin(X).dat')
    assert exported[code + extension] == b'synthetic DAS loader'
    if manual:
        assert exported[default] == selected
        assert alternate not in exported
        assert result['button'] is None
    else:
        assert exported[default] == b'original vanilla stage'
        assert exported[alternate] == selected
        assert result['button'] == 'X'
    assert archive.read_bytes() == original_archive
    assert not project.exists()
