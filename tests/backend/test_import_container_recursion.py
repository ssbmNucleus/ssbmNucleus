"""Container-zip recursion + duplicate 'skip' semantics for the unified import.

Covers the "one giant zip of my whole skin folder" support case: inner skin
zips must be recursed into (previously only loose dats imported and every
inner archive was silently ignored), and duplicate_action='skip' must skip
only the owned items — for stages and patches too, where 'skip' used to
bypass the duplicate check entirely and import the duplicates.
"""

import io
import zipfile

from flask import Flask

import vault.routes.import_unified.routes as routes
import vault.importing.unified.menu_import as menu_import
import vault.importing.unified.archive as unified_archive
from vault.routes.import_unified import import_bp
from vault.importing.unified.helpers import compute_dat_hash


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
    """Nominate every Pl*.dat member of the given zip as a Fox costume."""
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


def test_container_zip_recurses_into_inner_skin_zips(vault, monkeypatch):
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

    inner_a = _zip_bytes({'PlFxNr.dat': b'costume a'}).getvalue()
    inner_b = _zip_bytes({'PlFxRe.dat': b'costume b'}).getvalue()
    container = _zip_bytes({
        'skins/fox neutral.zip': inner_a,
        'skins/fox red.zip': inner_b,
    })

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (container, 'my whole skin folder.zip')},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['type'] == 'multi'
    assert body['types'] == ['character']
    assert body['imported_count'] == 2
    assert body['failed'] == []
    assert sorted(imported) == ['PlFxNr.dat', 'PlFxRe.dat']
    assert sorted((c['character'], c['id']) for c in body['costumes']) == [('Fox', 'PlFxNr'), ('Fox', 'PlFxRe')]


def test_container_imports_loose_dats_and_reports_rar(vault, monkeypatch):
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

    inner = _zip_bytes({'PlFxLa.dat': b'inner costume'}).getvalue()
    container = _zip_bytes({
        'fox lavender.zip': inner,
        # Real .rar members import now (test_import_rar.py); this one is
        # deliberately not an archive at all.
        'old pack.rar': b'not a real rar',
        'PlFxGr.dat': b'loose costume',
    })

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (container, 'mixed folder.zip')},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 2
    # both the inner-zip costume AND the loose dat made it in
    assert sorted(imported) == ['PlFxGr.dat', 'PlFxLa.dat']
    # the unreadable .rar is reported, not silently dropped
    assert len(body['failed']) == 1
    assert body['failed'][0]['name'] == 'old pack.rar'
    assert body['failed'][0]['error'] == 'could not be opened as a rar archive'


def test_container_auto_skips_duplicates_inside_inner_zips(vault, monkeypatch):
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
    monkeypatch.setattr(unified_archive, 'validate_for_slippi',
                        lambda _path, auto_fix=False: {'slippi_safe': True})
    _quiet_other_phases(monkeypatch)

    imported = []

    def fake_import(_zip_path, character_info, _filename, **_kwargs):
        imported.append(character_info['dat_file'])
        return {'success': True, 'skin_id': character_info['costume_code']}

    monkeypatch.setattr(unified_archive, 'import_character_costume', fake_import)

    # One inner zip holds an owned duplicate AND a new costume: only the
    # duplicate is skipped, the rest of that same zip still imports.
    inner = _zip_bytes({
        'PlFxNr.dat': b'owned costume',
        'PlFxRe.dat': b'new costume',
    }).getvalue()
    container = _zip_bytes({'fox pack.zip': inner})

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (container, 'skins.zip')},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert body['skipped_duplicates'][0]['existing_skin']['id'] == 'owned'
    assert imported == ['PlFxRe.dat']


def test_stage_duplicate_skip_keeps_remaining_variants(vault, monkeypatch):
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

    def stage_zip():
        return _zip_bytes({
            'GrNBa owned.dat': b'owned stage',
            'GrNBa new.dat': b'new stage',
        })

    client = _client()

    first = client.post(
        '/api/mex/import/file',
        data={'file': (stage_zip(), 'stages.zip')},
        content_type='multipart/form-data',
    )
    assert first.get_json()['type'] == 'duplicate_dialog'
    assert imported == []

    resumed = client.post(
        '/api/mex/import/file',
        data={'file': (stage_zip(), 'stages.zip'),
              'duplicate_action': 'skip'},
        content_type='multipart/form-data',
    )
    body = resumed.get_json()

    assert resumed.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert body['skipped_duplicates'][0]['existing_skin']['id'] == 'owned-bf'
    assert imported == ['GrNBa new.dat']


def test_patch_duplicate_skip_keeps_remaining_patches(vault, monkeypatch):
    vault.write({'characters': {}, 'stages': {}})

    monkeypatch.setattr(unified_archive, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'detect_stage_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'import_vanilla_stage_dats',
                        lambda *_a, **_k: [])

    existing = [{'id': 'p1', 'name': 'Owned Patch',
                 'file_hash': compute_dat_hash(b'owned patch')}]
    saved = {}
    monkeypatch.setattr(unified_archive, 'load_xdelta_metadata', lambda: list(existing))
    monkeypatch.setattr(unified_archive, 'save_xdelta_metadata',
                        lambda patches: saved.update({'patches': patches}))

    def patch_zip():
        return _zip_bytes({
            'owned.xdelta': b'owned patch',
            'new.xdelta': b'new patch',
        })

    client = _client()

    first = client.post(
        '/api/mex/import/file',
        data={'file': (patch_zip(), 'patches.zip')},
        content_type='multipart/form-data',
    )
    assert first.get_json()['type'] == 'duplicate_dialog'
    assert saved == {}

    resp = client.post(
        '/api/mex/import/file',
        data={'file': (patch_zip(), 'patches.zip'),
              'duplicate_action': 'skip'},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert body['skipped_duplicates'][0]['existing_skin']['id'] == 'p1'
    assert [p['name'] for p in body['patches']] == ['new']
    # only the new patch was appended to metadata
    assert len(saved['patches']) == 2
