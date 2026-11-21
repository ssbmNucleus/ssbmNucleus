"""7z uploads are repacked to a temp zip at entry of the unified import.

Regression: the Slippi-validation and duplicate-hash pre-check loops (and
everything downstream — import_character_costume, import_stage_mod, the
menu-mod installers) open the archive with zipfile directly, so a .7z upload
used to 500 with BadZipFile as soon as its costumes were detected. The fix
converts the .7z once (route upload + container inner archives), after which
the whole pipeline sees a plain zip.

All tests skip when py7zr isn't installed — without it 7z uploads were never
importable to begin with.
"""

import io
import zipfile

import pytest
from flask import Flask

import vault.routes.import_unified.routes as routes
import vault.importing.unified.menu_import as menu_import
import vault.importing.unified.archive as unified_archive
from vault.routes.import_unified import import_bp
from vault.importing.unified.helpers import compute_dat_hash

py7zr = pytest.importorskip('py7zr')


def _7z_bytes(members):
    data = io.BytesIO()
    with py7zr.SevenZipFile(data, 'w') as archive:
        for name, payload in members.items():
            archive.writestr(payload, name)
    data.seek(0)
    return data


def _zip_bytes(members):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    data.seek(0)
    return data


def _client():
    app = Flask(__name__)
    app.register_blueprint(import_bp)
    return app.test_client()


def _fake_detect_characters(zip_path):
    """Zipfile-based on purpose: it only works if the .7z really was
    converted to a zip before phase 1 ran."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        return [
            {
                'character': 'Fox',
                'color': name[:-4],
                'costume_code': name[:-4],
                'dat_file': name,
            }
            for name in zf.namelist()
            if name.startswith('Pl') and name.endswith('.dat')
        ]


def _quiet_other_phases(monkeypatch):
    monkeypatch.setattr(unified_archive, 'detect_stage_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'import_vanilla_stage_dats',
                        lambda *_a, **_k: [])
    monkeypatch.setattr(unified_archive, 'looks_like_icon_grid_zip', lambda _p: False)
    monkeypatch.setattr(unified_archive, 'looks_like_pause_zip', lambda _p: False)
    monkeypatch.setattr(menu_import, 'looks_like_pause_zip', lambda _p: False)
    monkeypatch.setattr(unified_archive, 'looks_like_percent_zip', lambda _p: False)


def test_7z_costume_runs_precheck_loops_and_imports(vault, monkeypatch):
    # The owned skin must be backed by a stored zip — hash-only ghost entries
    # (zip gone from storage) deliberately no longer count as duplicates.
    fox_dir = vault.storage / 'Fox'
    fox_dir.mkdir()
    with zipfile.ZipFile(fox_dir / 'owned.zip', 'w') as zf:
        zf.writestr('PlFxNr.dat', b'owned costume')

    vault.write({
        'characters': {
            'Fox': {
                'skins': [{
                    'id': 'owned',
                    'color': 'Neutral',
                    'filename': 'owned.zip',
                    'dat_hash': compute_dat_hash(b'owned costume'),
                }]
            }
        },
        'stages': {},
    })

    monkeypatch.setattr(unified_archive, 'detect_character_from_zip',
                        _fake_detect_characters)
    _quiet_other_phases(monkeypatch)

    validated = []

    def fake_validate(path, auto_fix=False):
        validated.append(path)
        return {'slippi_safe': True}

    monkeypatch.setattr(unified_archive, 'validate_for_slippi', fake_validate)

    imported = []

    def fake_import(zip_path, character_info, _filename, **_kwargs):
        # Downstream importers also expect a real zip
        with zipfile.ZipFile(zip_path, 'r') as zf:
            assert character_info['dat_file'] in zf.namelist()
        imported.append(character_info['dat_file'])
        return {'success': True, 'skin_id': character_info['costume_code']}

    monkeypatch.setattr(unified_archive, 'import_character_costume', fake_import)

    def costume_7z():
        return _7z_bytes({
            'PlFxNr.dat': b'owned costume',
            'PlFxRe.dat': b'new costume',
        })

    client = _client()

    # First pass: both the slippi loop AND the duplicate loop must run
    # without BadZipFile (this used to 500).
    first = client.post(
        '/api/mex/import/file',
        data={'file': (costume_7z(), 'skins.7z')},
        content_type='multipart/form-data',
    )
    assert first.status_code == 200
    assert first.get_json()['type'] == 'duplicate_dialog'
    assert len(validated) == 2
    assert imported == []

    resumed = client.post(
        '/api/mex/import/file',
        data={'file': (costume_7z(), 'skins.7z'),
              'duplicate_action': 'skip'},
        content_type='multipart/form-data',
    )
    body = resumed.get_json()

    assert resumed.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert imported == ['PlFxRe.dat']


def test_7z_stage_duplicate_skip(vault, monkeypatch):
    # Owned variants must be backed by a zip under storage/das/ — hash-only
    # ghost entries deliberately no longer count as duplicates.
    bf_dir = vault.storage / 'das' / 'battlefield'
    bf_dir.mkdir(parents=True)
    with zipfile.ZipFile(bf_dir / 'owned-bf.zip', 'w') as zf:
        zf.writestr('GrNBa.dat', b'owned stage')

    vault.write({
        'characters': {},
        'stages': {
            'battlefield': {
                'variants': [{
                    'id': 'owned-bf',
                    'name': 'Owned BF',
                    'dat_hash': compute_dat_hash(b'owned stage'),
                }]
            }
        },
    })

    def fake_detect_stages(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as zf:
            return [
                {'stage_name': 'Battlefield', 'folder': 'battlefield',
                 'stage_file': name}
                for name in zf.namelist() if name.endswith('.dat')
            ]

    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'detect_stage_from_zip', fake_detect_stages)
    monkeypatch.setattr(unified_archive, 'import_vanilla_stage_dats',
                        lambda *_a, **_k: [])

    imported = []

    def fake_import_stage(_zip_path, stage_info, _filename, **_kwargs):
        imported.append(stage_info['stage_file'])
        return {'success': True, 'variant_id': stage_info['stage_file']}

    monkeypatch.setattr(unified_archive, 'import_stage_mod', fake_import_stage)

    stage_7z = _7z_bytes({
        'GrNBa owned.dat': b'owned stage',
        'GrNBa new.dat': b'new stage',
    })

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (stage_7z, 'stages.7z'),
              'duplicate_action': 'skip'},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert imported == ['GrNBa new.dat']


def test_container_zip_converts_inner_7z(vault, monkeypatch):
    vault.write({'characters': {}, 'stages': {}})

    monkeypatch.setattr(unified_archive, 'detect_character_from_zip',
                        _fake_detect_characters)
    monkeypatch.setattr(unified_archive, 'validate_for_slippi',
                        lambda _path, auto_fix=False: {'slippi_safe': True})
    _quiet_other_phases(monkeypatch)

    imported = []

    def fake_import(_zip_path, character_info, _filename, **_kwargs):
        imported.append(character_info['dat_file'])
        return {'success': True, 'skin_id': character_info['costume_code']}

    monkeypatch.setattr(unified_archive, 'import_character_costume', fake_import)

    inner = _7z_bytes({'PlFxLa.dat': b'inner costume'}).getvalue()
    container = _zip_bytes({'fox lavender.7z': inner})

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (container, 'skin folder.zip')},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['type'] == 'multi'
    assert body['imported_count'] == 1
    assert body['failed'] == []
    assert imported == ['PlFxLa.dat']
