import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from flask import Flask
from projects.routes import costumes as c
import projects.install.project_fighters as project_fighters
from projects.routes import project as p


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    project = tmp_path / 'project.mexproj'
    project.write_text('{}')
    fighter_json = tmp_path / 'fighter.json'
    fighter_json.write_text(json.dumps({'name': 'Fox', 'costumes': [
        {'file': {'fileName': 'PlFxOr.dat'}}, {'file': {'fileName': 'PlFxNr.dat'}}]}))
    vault = tmp_path / 'storage'
    vault.mkdir()
    archive = vault / 'skin.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('PlFxGrMod.dat', b'costume-payload')
        z.writestr('csp.png', b'portrait')
    monkeypatch.setattr(c, 'STORAGE_PATH', vault)
    monkeypatch.setattr(c, 'get_current_project_path', lambda: project)
    monkeypatch.setattr(c, 'prepare_install_zip', lambda *args: None)
    monkeypatch.setattr(c, 'load_metadata', lambda: {})
    monkeypatch.setattr(c, 'reload_mex_manager', lambda: None)
    monkeypatch.setattr(p, 'find_fighter_json_by_name', lambda name: (fighter_json, json.loads(fighter_json.read_text())))
    monkeypatch.setattr(project_fighters, 'find_fighter_json_by_name', lambda name: (fighter_json, json.loads(fighter_json.read_text())))
    calls = []
    def run(command, project_arg, manifest_path):
        manifest = json.loads(Path(manifest_path).read_text())
        with zipfile.ZipFile(manifest[0]['path']) as z:
            dat = next(n for n in z.namelist() if n.lower().endswith('.dat'))
            assert z.read(dat) == b'costume-payload'
            assert z.read('csp.png') == b'portrait'
        calls.append(manifest)
        return {'success': True}
    monkeypatch.setattr(c, 'get_mex_manager', lambda: SimpleNamespace(_run_command=run))
    app = Flask(__name__)
    app.register_blueprint(c.costumes_bp)
    return app.test_client(), archive, fighter_json, calls


def test_replacement_uses_original_identity_after_reorder_and_preserves_vault(fixture):
    client, archive, fighter_json, calls = fixture
    original = archive.read_bytes()
    endpoint = '/api/mex/replace-vanilla/Fox/0'
    context = client.get(endpoint).json
    assert context['target']['color'] == 'Or'
    response = client.post(endpoint, json={'version': context['version'], 'costumePath': str(archive)})
    assert response.status_code == 200, response.json
    assert calls[0][0]['index'] == 0
    assert calls[0][0]['expectedFile'] == 'PlFxOr.dat'
    assert calls[0][0]['visibilityIndex'] == 3  # source green visibility, not destination orange
    assert archive.read_bytes() == original


def test_stale_slot_does_not_replace_new_occupant(fixture):
    client, archive, fighter_json, calls = fixture
    endpoint = '/api/mex/replace-vanilla/Fox/0'
    context = client.get(endpoint).json
    data = json.loads(fighter_json.read_text())
    data['costumes'].reverse()
    fighter_json.write_text(json.dumps(data))
    assert client.post(endpoint, json={'version': context['version'], 'costumePath': str(archive)}).status_code == 409
    assert not calls


def test_non_vault_path_is_rejected(fixture):
    client, archive, fighter_json, calls = fixture
    endpoint = '/api/mex/replace-vanilla/Fox/0'
    context = client.get(endpoint).json
    assert client.post(endpoint, json={'version': context['version'], 'costumePath': str(fighter_json)}).status_code == 400
    assert not calls


def test_red_region_placeholder_and_replacement_identity():
    assert c.vanilla_replacement_target('C. Falcon', {'fileName': 'PlCaRe.'})['color'] == 'Re'
    assert c.vanilla_replacement_target('C. Falcon', {'fileName': 'PlCaBuMod_2.dat', 'replacesVanillaFile': 'PlCaRe.'})['color'] == 'Re'
    assert c.vanilla_replacement_target('C. Falcon', {'fileName': 'PlCaBuMod.dat'}) is None


def test_paired_nana_changes_invalidate_popo_selection(tmp_path, monkeypatch):
    project = tmp_path / 'project.mexproj'
    project.write_text('{}')
    popo, nana = tmp_path / 'popo.json', tmp_path / 'nana.json'
    popo.write_text(json.dumps({'costumes': [{'file': {'fileName': 'PlPpNr.dat'}}]}))
    nana.write_text(json.dumps({'costumes': [{'file': {'fileName': 'PlNnNr.dat'}}]}))
    monkeypatch.setattr(c, 'get_current_project_path', lambda: project)
    def find(name):
        path = popo if name == 'Ice Climbers' else nana
        return path, json.loads(path.read_text())
    monkeypatch.setattr(p, 'find_fighter_json_by_name', find)
    monkeypatch.setattr(project_fighters, 'find_fighter_json_by_name', find)
    before = c._replacement_context('Ice Climbers', 0)[3]
    nana.write_text(json.dumps({'costumes': [{'file': {'fileName': 'PlNnYe.dat'}}]}))
    assert c._replacement_context('Ice Climbers', 0)[3] != before


@pytest.mark.parametrize('dat_name, visibility', [
    ('PlFxGrMod.dat', 3),   # a vanilla colour keeps its own visibility lookup
    ('plfxgrmod.dat', 3),   # ... whatever casing the mod shipped its DAT in
    ('PlFxWh.dat', 1),      # Fox never shipped white: take the Or slot's lookup
])
def test_modded_colours_and_casings_are_accepted(fixture, dat_name, visibility):
    client, archive, _, calls = fixture
    other = archive.parent / 'other.zip'
    with zipfile.ZipFile(other, 'w') as z:
        z.writestr(dat_name, b'costume-payload')
        z.writestr('csp.png', b'portrait')
    endpoint = '/api/mex/replace-vanilla/Fox/0'
    context = client.get(endpoint).json
    response = client.post(endpoint, json={'version': context['version'], 'costumePath': str(other)})
    assert response.status_code == 200, response.json
    assert calls[0][0]['visibilityIndex'] == visibility


def test_another_fighters_costume_is_still_rejected(fixture):
    client, archive, _, calls = fixture
    other = archive.parent / 'marth.zip'
    with zipfile.ZipFile(other, 'w') as z:
        z.writestr('PlMsRe.dat', b'costume-payload')
    endpoint = '/api/mex/replace-vanilla/Fox/0'
    context = client.get(endpoint).json
    response = client.post(endpoint, json={'version': context['version'], 'costumePath': str(other)})
    assert response.status_code == 400
    assert 'does not match Fox' in response.json['error']
    assert not calls
