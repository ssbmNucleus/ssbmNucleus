from tests.paths import BACKEND
import sys
import zipfile
from pathlib import Path

from flask import Flask


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import projects.routes.costumes as costumes_module
import vault.routes.das as das_module
import projects.routes.das as das_project_routes
import shared.vanilla_extract.vanilla_refs as vanilla_refs


def test_ice_climbers_reset_manifest_includes_nana(monkeypatch, tmp_path):
    def fake_package(_temp_dir, character, color, slot):
        return {
            'path': f'{character}-{color}.zip',
            'name': color,
            'visibilityIndex': slot,
        }

    monkeypatch.setattr(
        costumes_module, '_build_vanilla_costume_package', fake_package)

    manifest, affected = costumes_module._build_vanilla_reset_manifest(
        tmp_path, 'Ice Climbers')

    assert affected == ['Ice Climbers', 'Nana']
    assert [entry['fighter'] for entry in manifest['fighters']] == [
        'Ice Climbers', 'Nana']
    assert len(manifest['fighters'][0]['costumes']) == 4
    assert len(manifest['fighters'][1]['costumes']) == 4
    assert manifest['fighters'][0]['redCostumeIndex'] == 3
    assert 'redCostumeIndex' not in manifest['fighters'][1]


def test_nana_package_uses_paired_popo_art(monkeypatch, tmp_path):
    vanilla_root = tmp_path / 'vanilla'
    nana = vanilla_root / 'Nana' / 'PlNnYe'
    popo = vanilla_root / 'Ice Climbers' / 'PlPpGr'
    nana.mkdir(parents=True)
    popo.mkdir(parents=True)
    nana.joinpath('PlNnYe.dat').write_bytes(b'nana-model')
    popo.joinpath('csp.png').write_bytes(b'paired-csp')
    popo.joinpath('stock.png').write_bytes(b'paired-stock')
    monkeypatch.setattr(
        costumes_module, 'VANILLA_ASSETS_DIR', vanilla_root)

    package = costumes_module._build_vanilla_costume_package(
        tmp_path, 'Nana', 'Ye', 1)

    with zipfile.ZipFile(package['path']) as archive:
        assert archive.read('PlNnYe.dat') == b'nana-model'
        assert archive.read('csp.png') == b'paired-csp'
        assert archive.read('stock.png') == b'paired-stock'


def test_zelda_reset_endpoint_runs_one_paired_command(monkeypatch):
    recorded = {}

    class FakeMex:
        def reset_vanilla_costumes(self, manifest):
            recorded['manifest'] = manifest
            return {'success': True, 'totalRestored': 10}

    def fake_manifest(_temp_dir, requested):
        assert requested == 'Zelda'
        return {
            'fighters': [
                {'fighter': 'Zelda', 'costumes': [{'path': 'z.zip'}]},
                {'fighter': 'Sheik', 'costumes': [{'path': 's.zip'}]},
            ],
        }, ['Zelda', 'Sheik']

    monkeypatch.setattr(
        costumes_module, '_build_vanilla_reset_manifest', fake_manifest)
    monkeypatch.setattr(costumes_module, 'get_mex_manager', FakeMex)
    monkeypatch.setattr(
        costumes_module, 'reload_mex_manager',
        lambda: recorded.setdefault('reloaded', True))

    app = Flask(__name__)
    app.register_blueprint(costumes_module.costumes_bp)
    response = app.test_client().post(
        '/api/mex/restore-vanilla-costumes',
        json={'fighter': 'Zelda'})

    assert response.status_code == 200
    assert response.get_json()['affectedFighters'] == ['Zelda', 'Sheik']
    assert [entry['fighter'] for entry in recorded['manifest']['fighters']] == [
        'Zelda', 'Sheik']
    assert recorded['reloaded'] is True


def test_hidden_nana_cannot_be_reset_without_ice_climbers():
    app = Flask(__name__)
    app.register_blueprint(costumes_module.costumes_bp)

    response = app.test_client().post(
        '/api/mex/restore-vanilla-costumes',
        json={'fighter': 'Nana'})

    assert response.status_code == 400


def test_das_restore_vanilla_is_additive_and_idempotent(
        monkeypatch, tmp_path):
    project_files = tmp_path / 'project' / 'files'
    stage_folder = project_files / 'GrNBa'
    stage_folder.mkdir(parents=True)
    project_files.joinpath('GrNBa.dat').write_bytes(b'das-loader')
    stage_folder.joinpath('Imported.dat').write_bytes(b'imported-stage')
    vanilla = tmp_path / 'GrNBa.dat'
    vanilla.write_bytes(b'pristine-vanilla')

    monkeypatch.setattr(
        das_project_routes, 'get_project_files_dir', lambda: project_files)
    monkeypatch.setattr(
        vanilla_refs, 'ensure_vanilla_ref',
        lambda name: vanilla if name == 'GrNBa.dat' else None)

    app = Flask(__name__)
    app.register_blueprint(das_module.das_bp)
    client = app.test_client()

    first = client.post(
        '/api/mex/das/restore-vanilla', json={'stageCode': 'GrNBa'})
    assert first.status_code == 200
    assert first.get_json()['alreadyPresent'] is False
    assert stage_folder.joinpath('vanilla.dat').read_bytes() == b'pristine-vanilla'
    assert stage_folder.joinpath('Imported.dat').read_bytes() == b'imported-stage'

    vanilla.write_bytes(b'changed-source')
    second = client.post(
        '/api/mex/das/restore-vanilla', json={'stageCode': 'GrNBa'})
    assert second.status_code == 200
    assert second.get_json()['alreadyPresent'] is True
    assert stage_folder.joinpath('vanilla.dat').read_bytes() == b'pristine-vanilla'


def test_das_restore_requires_installed_framework(monkeypatch, tmp_path):
    project_files = tmp_path / 'project' / 'files'
    project_files.mkdir(parents=True)
    monkeypatch.setattr(
        das_project_routes, 'get_project_files_dir', lambda: project_files)

    app = Flask(__name__)
    app.register_blueprint(das_module.das_bp)
    response = app.test_client().post(
        '/api/mex/das/restore-vanilla', json={'stageCode': 'GrNBa'})

    assert response.status_code == 409
    assert response.get_json()['success'] is False
