from tests.paths import REPO
import io
import json
import shutil
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from flask import Flask

from vault.routes import custom_stages
from vault.importing import custom_stage_package as stage_package


@pytest.fixture
def custom_stage_vault():
    parent = REPO / 'app' / 'scratch' / 'custom-stage-export-tests'
    parent.mkdir(parents=True, exist_ok=True)
    child = parent / str(uuid.uuid4())
    child.mkdir()
    try:
        yield child
    finally:
        resolved = child.resolve()
        if resolved.parent == parent.resolve() and resolved.name:
            shutil.rmtree(resolved, ignore_errors=True)


def test_export_serializes_current_name_playlist_and_audio_without_losing_package_fields(
        custom_stage_vault, monkeypatch):
    slug = 'battle-city'
    stage_dir = custom_stage_vault / slug
    stage_dir.mkdir()
    original_json = {
        'name': 'Old title',
        'fileName': 'BattleCity.dat',
        'additionalFiles': ['BattleEffect.usd'],
        'assets': {'icon': 'sss/icon_048', 'banner': 'sss/banner_048'},
        'futureField': {'preserve': True},
        'playlist': {'entries': [{'musicID': 91, 'chanceToPlay': 1}]},
    }
    (stage_dir / 'stage.json').write_text(json.dumps(original_json), encoding='utf-8')
    with zipfile.ZipFile(stage_dir / 'stage.zip', 'w') as archive:
        archive.writestr('stage.json', json.dumps(original_json))
        archive.writestr('BattleCity.dat', b'stage-data')
        archive.writestr('BattleEffect.usd', b'effect-data')
        archive.writestr('icon.png', b'icon-data')
    (stage_dir / 'music_0.hps').write_bytes(b'first-track')
    (stage_dir / 'music_1.hps').write_bytes(b'second-track')

    entry = {
        'slug': slug,
        'name': 'Edited title',
        'playlist': [
            {'name': 'First song', 'chance': 75},
            {'name': 'Second song', 'chance': 25},
        ],
    }
    monkeypatch.setattr(custom_stages, 'CUSTOM_STAGES_PATH', custom_stage_vault)
    monkeypatch.setattr(custom_stages, '_read_metadata',
                        lambda: {'custom_stages': [entry]})
    app = Flask(__name__)
    app.register_blueprint(custom_stages.custom_stages_bp)

    response = app.test_client().get(f'/api/mex/custom-stages/{slug}/export')

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as exported:
        stage_json = json.loads(exported.read('stage.json'))
        assert exported.read('BattleCity.dat') == b'stage-data'
        assert exported.read('BattleEffect.usd') == b'effect-data'
        assert exported.read('icon.png') == b'icon-data'
        assert exported.read('music_0.hps') == b'first-track'
        assert exported.read('music_1.hps') == b'second-track'

    assert stage_json['name'] == 'Edited title'
    assert stage_json['fileName'] == 'BattleCity.dat'
    assert stage_json['additionalFiles'] == ['BattleEffect.usd']
    assert stage_json['assets'] == original_json['assets']
    assert stage_json['futureField'] == {'preserve': True}
    assert stage_json['playlist']['entries'] == [
        {'musicID': 0, 'chanceToPlay': 75,
         'name': 'First song', 'fileName': 'music_0.hps'},
        {'musicID': 1, 'chanceToPlay': 25,
         'name': 'Second song', 'fileName': 'music_1.hps'},
    ]

    # Re-import hydrates the editable vault state and a second export retains it.
    imported_root = custom_stage_vault / 'reimported'
    imported_root.mkdir()
    captured_metadata = {'custom_stages': []}

    @contextmanager
    def metadata_tx(**_kwargs):
        yield captured_metadata

    monkeypatch.setattr(stage_package, 'CUSTOM_STAGES_PATH', imported_root)
    monkeypatch.setattr(stage_package, 'metadata_transaction', metadata_tx)
    imported = stage_package.import_custom_stage_zip_bytes(response.data, 'fallback')
    assert imported['name'] == 'Edited title'
    assert imported['playlist'] == [
        {'name': 'First song', 'chance': 75},
        {'name': 'Second song', 'chance': 25},
    ]
    assert (imported_root / imported['slug'] / 'music_0.hps').read_bytes() == b'first-track'

    repeated = custom_stages._serialize_custom_stage_export(
        imported_root / imported['slug'], imported)
    with zipfile.ZipFile(repeated) as archive:
        repeated_json = json.loads(archive.read('stage.json'))
        assert archive.read('music_1.hps') == b'second-track'
        assert repeated_json['name'] == 'Edited title'
        assert repeated_json['futureField'] == {'preserve': True}
        assert repeated_json['playlist']['entries'][1]['chanceToPlay'] == 25


def test_import_rejects_unsafe_portable_music_reference_before_vault_write(
        custom_stage_vault, monkeypatch):
    package = io.BytesIO()
    stage_json = {
        'name': 'Unsafe',
        'fileName': 'Stage.dat',
        'playlist': {'entries': [{
            'musicID': 0, 'chanceToPlay': 50,
            'name': 'Escape', 'fileName': '../escape.hps',
        }]},
    }
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('stage.json', json.dumps(stage_json))
        archive.writestr('Stage.dat', b'stage')
        archive.writestr('../escape.hps', b'audio')
    destination = custom_stage_vault / 'destination'
    destination.mkdir()
    monkeypatch.setattr(stage_package, 'CUSTOM_STAGES_PATH', destination)

    with pytest.raises(ValueError, match='stage music reference'):
        stage_package.import_custom_stage_zip_bytes(package.getvalue(), 'fallback')

    assert list(destination.iterdir()) == []


def test_import_rejects_non_object_playlist_before_vault_write(
        custom_stage_vault, monkeypatch):
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('stage.json', json.dumps({
            'name': 'Malformed', 'fileName': 'Stage.dat', 'playlist': [],
        }))
        archive.writestr('Stage.dat', b'stage')
    destination = custom_stage_vault / 'destination'
    destination.mkdir()
    monkeypatch.setattr(stage_package, 'CUSTOM_STAGES_PATH', destination)

    with pytest.raises(ValueError, match='stage.json playlist must be an object'):
        stage_package.import_custom_stage_zip_bytes(package.getvalue(), 'malformed')

    assert list(destination.iterdir()) == []
