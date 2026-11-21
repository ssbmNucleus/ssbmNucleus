import json
from pathlib import Path

import pytest
from flask import Flask
from shared.routes import viewer
from core import viewer_tools
from shared.vanilla_extract.first_run_setup import FirstRunSetup
from shared.vanilla_extract import vanilla_refs


@pytest.mark.parametrize('extension', ['dat', 'usd'])
def test_setup_resolves_region_placeholder_for_character_bank(tmp_path, extension):
    setup = FirstRunSetup(tmp_path / 'app', tmp_path / 'mexcli.exe', storage_path=tmp_path / 'storage')
    setup.VANILLA_FIGHTER_COUNT = 1
    project = tmp_path / 'source'
    (project / 'data/fighters').mkdir(parents=True)
    (project / 'files').mkdir()
    (project / 'data/fighters/000.json').write_text(json.dumps({
        'name': 'C. Falcon', 'files': {}, 'costumes': [{'name': 'Red', 'file': {'fileName': 'PlCaRe.'}}]}))
    (project / f'files/PlCaRe.{extension}').write_bytes(b'red-falcon')
    result = setup._copy_character_assets(project)
    assert result['success'], result
    assert (setup.vanilla_dir / 'C. Falcon/PlCaRe/PlCaRe.dat').read_bytes() == b'red-falcon'


def test_existing_portrait_only_folder_is_recovered_for_creator(tmp_path, monkeypatch):
    folder = tmp_path / 'vanilla/C. Falcon/PlCaRe'
    folder.mkdir(parents=True)
    (folder / 'csp.png').write_bytes(b'portrait')
    reference = tmp_path / 'reference.dat'
    reference.write_bytes(b'red-falcon')
    monkeypatch.setattr(viewer, 'VANILLA_ASSETS_DIR', tmp_path / 'vanilla')
    monkeypatch.setattr(viewer_tools, 'VANILLA_ASSETS_DIR', tmp_path / 'vanilla')
    calls = []
    def recover(name, **kwargs):
        calls.append(name)
        return reference
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', recover)
    app = Flask(__name__)
    app.register_blueprint(viewer.viewer_bp)
    response = app.test_client().get('/api/mex/vanilla/costumes/C.%20Falcon')
    assert response.json['costumes'][0]['code'] == 'PlCaRe'
    assert response.json['costumes'][0]['hasCsp']
    assert viewer.find_vanilla_costume_file('C. Falcon', 'PlCaRe') == reference
    assert calls == ['PlCaRe.dat', 'PlCaRe.dat']
