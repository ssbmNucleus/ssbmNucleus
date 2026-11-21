from tests.paths import REPO
import shutil
import uuid
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from projects.routes import mod_export


@pytest.fixture
def export_dirs():
    parent = REPO / 'app' / 'scratch' / 'mod-export-tests'
    parent.mkdir(parents=True, exist_ok=True)
    child = parent / str(uuid.uuid4())
    child.mkdir()
    try:
        storage = child / 'storage'
        output = child / 'output'
        storage.mkdir()
        output.mkdir()
        yield storage, output
    finally:
        resolved = child.resolve()
        if resolved.parent == parent.resolve() and resolved.name:
            shutil.rmtree(resolved, ignore_errors=True)


def _client(monkeypatch, storage, output):
    monkeypatch.setattr(mod_export, 'STORAGE_PATH', storage)
    monkeypatch.setattr(mod_export, 'OUTPUT_PATH', output)
    monkeypatch.setattr(mod_export, 'load_metadata', lambda default=None: default)
    app = Flask(__name__)
    app.register_blueprint(mod_export.mod_export_bp)
    return app.test_client()


def test_costume_export_retains_gaw_color_sidecar(export_dirs, monkeypatch):
    storage, output = export_dirs
    char_dir = storage / 'MrGameAndWatch'
    char_dir.mkdir()
    with zipfile.ZipFile(char_dir / 'green.zip', 'w') as archive:
        archive.writestr('PlGwNr.dat', b'costume')
        archive.writestr('gaw.json', b'{"fill":"#11223344","outline":"#55667788"}')
        archive.writestr('notes.txt', b'not package data')

    response = _client(monkeypatch, storage, output).post(
        '/api/mex/storage/costumes/export',
        json={'character': 'MrGameAndWatch', 'skinId': 'green', 'colorName': 'Green'},
    )

    assert response.status_code == 200
    exported = output / 'mod_exports' / response.get_json()['filename']
    with zipfile.ZipFile(exported) as archive:
        assert archive.read('PlGwNr.dat') == b'costume'
        assert archive.read('gaw.json').startswith(b'{"fill"')
        assert 'notes.txt' not in archive.namelist()


@pytest.mark.parametrize('base_name', ['Stadium.dat', 'Stadium.usd'])
def test_stadium_export_retains_base_and_complete_transformation_bundle(
        export_dirs, monkeypatch, base_name):
    storage, output = export_dirs
    stage_dir = storage / 'das' / 'pokemon_stadium'
    stage_dir.mkdir(parents=True)
    stem = Path(base_name).stem
    with zipfile.ZipFile(stage_dir / 'variant.zip', 'w') as archive:
        archive.writestr(base_name, b'base')
        for index in range(1, 5):
            archive.writestr(f'{stem}/GrPs{index}.dat', f'form-{index}'.encode())
        archive.writestr('screenshot.png', b'image')

    response = _client(monkeypatch, storage, output).post(
        '/api/mex/storage/stages/export',
        json={'stageCode': 'GrPs', 'stageName': 'Pokemon Stadium',
              'variantId': 'variant', 'variantName': 'Variant'},
    )

    assert response.status_code == 200
    exported = output / 'mod_exports' / response.get_json()['filename']
    with zipfile.ZipFile(exported) as archive:
        assert archive.read(base_name) == b'base'
        for index in range(1, 5):
            assert archive.read(f'{stem}/GrPs{index}.dat') == f'form-{index}'.encode()


def test_stadium_export_does_not_publish_partial_form_set(export_dirs, monkeypatch):
    storage, output = export_dirs
    stage_dir = storage / 'das' / 'pokemon_stadium'
    stage_dir.mkdir(parents=True)
    with zipfile.ZipFile(stage_dir / 'variant.zip', 'w') as archive:
        archive.writestr('Stadium.dat', b'base')
        archive.writestr('Stadium/GrPs1.dat', b'one')
        archive.writestr('Stadium/GrPs2.dat', b'two')

    response = _client(monkeypatch, storage, output).post(
        '/api/mex/storage/stages/export',
        json={'stageCode': 'GrPs', 'variantId': 'variant'},
    )

    exported = output / 'mod_exports' / response.get_json()['filename']
    with zipfile.ZipFile(exported) as archive:
        assert archive.namelist() == ['Stadium.dat']
