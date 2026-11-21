import io
import zipfile

from flask import Flask

import vault.routes.import_unified.routes as routes
import vault.importing.unified.archive as unified_archive
from vault.routes.import_unified import import_bp
from vault.importing.unified.helpers import check_duplicate_skin, compute_dat_hash


COMMON_DAT = b'common vanilla costume'
OWNED_DAT = b'actual owned costume'


def _costume_zip(name, data):
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, 'w') as archive:
        archive.writestr(name, data)
    archive_data.seek(0)
    return archive_data


def _client():
    app = Flask(__name__)
    app.register_blueprint(import_bp)
    return app.test_client()


def test_multi_dat_backfill_hashes_the_entry_costume_code(vault, monkeypatch):
    fox_dir = vault.storage / 'Fox'
    fox_dir.mkdir()
    with zipfile.ZipFile(fox_dir / 'owned-red.zip', 'w') as archive:
        # The unrelated common DAT comes first, reproducing the old ZIP-order
        # bug. The metadata entry belongs to the red DAT.
        archive.writestr('PlFxNr.dat', COMMON_DAT)
        archive.writestr('PlFxRe.dat', OWNED_DAT)

    vault.write({
        'characters': {
            'Fox': {
                'skins': [{
                    'id': 'owned-red',
                    'color': 'Red',
                    'costume_code': 'PlFxRe',
                    'filename': 'owned-red.zip',
                }]
            }
        },
        'stages': {},
    })

    def fake_detect(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as archive:
            dat_file = next(name for name in archive.namelist()
                            if name.lower().endswith('.dat'))
        return [{
            'character': 'Fox',
            'color': 'Neutral',
            'costume_code': dat_file[:-4],
            'dat_file': dat_file,
        }]

    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', fake_detect)
    monkeypatch.setattr(unified_archive, 'validate_for_slippi',
                        lambda _path, auto_fix=False: {'slippi_safe': True})
    monkeypatch.setattr(
        unified_archive, 'import_character_costume',
        lambda *_args, **_kwargs: {'success': True, 'skin_id': 'imported'})

    client = _client()

    common = client.post(
        '/api/mex/import/file',
        data={'file': (_costume_zip('PlFxNr.dat', COMMON_DAT), 'common.zip')},
        content_type='multipart/form-data',
    )
    assert common.status_code == 200
    assert common.get_json()['success'] is True

    stored_skin = vault.read()['characters']['Fox']['skins'][0]
    assert stored_skin['dat_hash'] == compute_dat_hash(OWNED_DAT)
    assert stored_skin['dat_hash'] != compute_dat_hash(COMMON_DAT)

    actual_owned = client.post(
        '/api/mex/import/file',
        data={'file': (_costume_zip('PlFxRe.dat', OWNED_DAT), 'owned.zip')},
        content_type='multipart/form-data',
    )
    body = actual_owned.get_json()

    assert actual_owned.status_code == 200
    assert body['type'] == 'duplicate_dialog'
    assert body['duplicate_skins'][0]['existing_skin']['id'] == 'owned-red'


def test_single_dat_backfill_keeps_first_match_fallback(vault):
    fox_dir = vault.storage / 'Fox'
    fox_dir.mkdir()
    with zipfile.ZipFile(fox_dir / 'legacy.zip', 'w') as archive:
        archive.writestr('PlFxNr.dat', OWNED_DAT)

    metadata = {
        'characters': {
            'Fox': {
                'skins': [{
                    'id': 'legacy',
                    'color': 'Legacy',
                    'filename': 'legacy.zip',
                }]
            }
        }
    }

    existing = check_duplicate_skin('Fox', compute_dat_hash(OWNED_DAT), metadata)
    assert existing['id'] == 'legacy'


def test_ice_climbers_backfill_selects_the_matching_half(vault):
    climber_dir = vault.storage / 'Ice Climbers'
    climber_dir.mkdir()
    with zipfile.ZipFile(climber_dir / 'pair.zip', 'w') as archive:
        archive.writestr('PlNnAq.dat', COMMON_DAT)
        archive.writestr('PlPpGrMod.dat', OWNED_DAT)

    metadata = {
        'characters': {
            'Ice Climbers': {
                'skins': [{
                    'id': 'popo-green',
                    'color': 'Green',
                    'costume_code': 'PlPpGr',
                    'filename': 'pair.zip',
                }]
            }
        }
    }

    existing = check_duplicate_skin(
        'Ice Climbers', compute_dat_hash(OWNED_DAT), metadata)
    assert existing['id'] == 'popo-green'
    assert metadata['characters']['Ice Climbers']['skins'][0]['dat_hash'] == (
        compute_dat_hash(OWNED_DAT))
