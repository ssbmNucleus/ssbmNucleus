"""Regression coverage for skipping duplicates inside a multi-costume ZIP."""

import io
import zipfile

from flask import Flask

import vault.routes.import_unified.routes as routes
import vault.importing.unified.archive as unified_archive
from vault.routes.import_unified import import_bp
from vault.importing.unified.helpers import compute_dat_hash


def _costume_zip():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('PlFxNr.dat', b'existing costume')
        archive.writestr('PlFxRe.dat', b'new costume')
    data.seek(0)
    return data


def _character_infos():
    return [
        {
            'character': 'Fox',
            'color': 'Neutral',
            'costume_code': 'PlFxNr',
            'dat_file': 'PlFxNr.dat',
        },
        {
            'character': 'Fox',
            'color': 'Red',
            'costume_code': 'PlFxRe',
            'dat_file': 'PlFxRe.dat',
        },
    ]


def test_skip_duplicate_continues_with_remaining_costumes(vault, monkeypatch):
    # The owned skin must be backed by a stored zip — hash-only ghost entries
    # (zip gone from storage) deliberately no longer count as duplicates.
    fox_dir = vault.storage / 'Fox'
    fox_dir.mkdir()
    with zipfile.ZipFile(fox_dir / 'existing.zip', 'w') as zf:
        zf.writestr('PlFxNr.dat', b'existing costume')

    vault.write({
        'characters': {
            'Fox': {
                'skins': [{
                    'id': 'existing',
                    'color': 'Neutral',
                    'filename': 'existing.zip',
                    'dat_hash': compute_dat_hash(b'existing costume'),
                }]
            }
        },
        'stages': {},
    })

    monkeypatch.setattr(unified_archive, 'detect_character_from_zip',
                        lambda _path: _character_infos())
    monkeypatch.setattr(unified_archive, 'validate_for_slippi',
                        lambda _path, auto_fix=False: {'slippi_safe': True})

    imported = []

    def fake_import(_zip_path, character_info, _filename, **_kwargs):
        imported.append(character_info['dat_file'])
        return {'success': True, 'skin_id': character_info['costume_code']}

    monkeypatch.setattr(unified_archive, 'import_character_costume', fake_import)

    app = Flask(__name__)
    app.register_blueprint(import_bp)
    client = app.test_client()

    first = client.post(
        '/api/mex/import/file',
        data={'file': (_costume_zip(), 'costumes.zip')},
        content_type='multipart/form-data',
    )
    assert first.get_json()['type'] == 'duplicate_dialog'
    assert imported == []

    resumed = client.post(
        '/api/mex/import/file',
        data={
            'file': (_costume_zip(), 'costumes.zip'),
            'duplicate_action': 'skip',
        },
        content_type='multipart/form-data',
    )
    body = resumed.get_json()

    assert resumed.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert body['skipped_duplicates'][0]['existing_skin']['id'] == 'existing'
    assert imported == ['PlFxRe.dat']
