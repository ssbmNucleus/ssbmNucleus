"""Optional native regression for preservation of a source fighter's mode assets.

Set NUCLEUS_MODE_BASE_PROJECT to a vanilla .mexproj, NUCLEUS_MODE_SOURCE_FIGHTER
to the original fighter JSON, and NUCLEUS_MODE_FIGHTER_ZIP to its scanned ZIP.
The JSON's project files/ directory supplies the independent source bytes.
Only the copied base project and temporary vault are modified. No game assets
are checked in. This verifies import/save preservation, not live game modes.
"""
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from core.config import MEXCLI_PATH

pytestmark = pytest.mark.slow


def _asset(variable):
    raw = os.environ.get(variable)
    if not raw:
        pytest.skip(f'{variable} not supplied (requires local lawful game assets)')
    path = Path(raw).resolve()
    assert path.is_file(), f'{variable} is not a file: {path}'
    return path


def _cli(*args):
    result = subprocess.run([str(MEXCLI_PATH), *map(str, args)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-3000:] + result.stdout[-3000:]
    return result


@pytest.mark.parametrize('install_path', ['cli', 'nucleus'])
def test_source_single_player_assets_survive_import_save_reopen(
        tmp_path, monkeypatch, install_path):
    if not Path(MEXCLI_PATH).is_file():
        pytest.skip('Repository-pinned MexCLI is not installed')
    base = _asset('NUCLEUS_MODE_BASE_PROJECT')
    original = _asset('NUCLEUS_MODE_SOURCE_FIGHTER')
    package = _asset('NUCLEUS_MODE_FIGHTER_ZIP')
    source = json.loads(original.read_text(encoding='utf-8-sig'))
    source_files = original.parents[2] / 'files'
    symbol_fields = ('demoWait', 'demoResult', 'demoIntro', 'demoEnding')
    archive_fields = ('demoFile', 'rstAnimFile', 'animFile')
    media_fields = ('endClassicFile', 'endAdventureFile', 'endAllStarFile', 'endMovieFile')
    standalone_demos = [source_files / f"{source['files'][field]}.dat"
                        for field in ('demoIntro', 'demoEnding')]
    standalone_demos = [path for path in standalone_demos if path.is_file()]
    with zipfile.ZipFile(package) as archive:
        packaged = json.loads(archive.read('fighter.json'))
        assert packaged['name'] == source['name']
        for field in symbol_fields:
            assert source['files'][field], f'Source must have a valid {field} control'
            assert packaged['files'][field] == source['files'][field]
        for group, fields in [('files', archive_fields), ('media', media_fields)]:
            for field in fields:
                name = source[group][field]
                assert name and Path(name).name == name
                assert archive.read(packaged[group][field]) == (source_files / name).read_bytes()
        for demo in standalone_demos:
            assert archive.read(demo.name) == demo.read_bytes()

    project_dir = tmp_path / 'project'
    shutil.copytree(base.parent, project_dir)
    project = project_dir / base.name
    before = {p.name for p in (project_dir / 'data/fighters').glob('*.json')}
    if install_path == 'cli':
        _cli('add-fighter', project, package)
    else:
        from projects.routes import custom_characters as routes
        vault = tmp_path / 'vault' / 'custom_characters'
        fighter_dir = vault / 'mode-control'
        fighter_dir.mkdir(parents=True)
        shutil.copy2(package, fighter_dir / 'fighter.zip')
        monkeypatch.setattr(routes, 'CUSTOM_CHARACTERS_PATH', vault)
        monkeypatch.setattr(routes, 'PROJECT_ROOT', tmp_path)
        monkeypatch.setattr(routes, 'get_current_project_path', lambda: project)
        monkeypatch.setattr(routes, '_read_metadata', lambda: {'custom_characters': []})
        monkeypatch.setattr(routes, 'reload_mex_manager', lambda: None)
        app = Flask(__name__)
        with app.test_request_context(method='POST', json={'slug': 'mode-control'}):
            response = routes.install_custom_character()
        body, status = response if isinstance(response, tuple) else (response, 200)
        assert status == 200 and body.get_json()['success'], body.get_json()

    assert len(list((project_dir / 'data/fighters').glob('*.json'))) == len(before) + 1
    for command in ('save', 'open'):
        _cli(command, project)
        installed = [json.loads(p.read_text(encoding='utf-8-sig'))
                     for p in (project_dir / 'data/fighters').glob('*.json')]
        matches = [fighter for fighter in installed if fighter['name'] == source['name']]
        assert len(matches) == 1, 'Use a base without this custom fighter'
        fighter = matches[0]
        for field in symbol_fields:
            assert fighter['files'][field] == source['files'][field]
        for group, fields in [('files', archive_fields), ('media', media_fields)]:
            for field in fields:
                filename = fighter[group][field]
                assert filename and Path(filename).name == filename
                assert (project_dir / 'files' / filename).read_bytes() == (
                    source_files / source[group][field]).read_bytes()
        for demo in standalone_demos:
            assert (project_dir / 'files' / demo.name).read_bytes() == demo.read_bytes()
