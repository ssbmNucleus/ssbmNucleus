""".rar uploads are repacked to a temp zip at entry of the unified import.

Same shape as the .7z conversion in test_import_7z_conversion.py: everything
downstream of detection opens the archive with zipfile directly, so a .rar has
to become a plain zip before phase 1 runs. Before this, .rar was refused at
the door and inner .rar members of a container zip were reported as failures.

The archives are committed fixtures rather than built in-process: only UnRAR
ships (utility/unrar*), and it cannot create archives. rar_fixtures/ holds
  skins.rar         PlFxNr.dat = b'owned costume', PlFxRe.dat = b'new costume'
  stages.rar        'GrNBa owned.dat' = b'owned stage', 'GrNBa new.dat' = b'new stage'
  fox lavender.rar  PlFxLa.dat = b'inner costume'

Tests skip when rarfile or the UnRAR binary is missing — without both, .rar
uploads are refused by design.
"""

import io
import struct
import zlib
import zipfile
from pathlib import Path

import pytest
from flask import Flask

import vault.routes.import_unified.routes as routes
import vault.importing.unified.menu_import as menu_import
import vault.importing.unified.archive as unified_archive
from vault.routes.import_unified import import_bp
from vault.importing.unified.helpers import compute_dat_hash

pytest.importorskip('rarfile')

from core.rar_tools import rar_available  # noqa: E402

pytestmark = pytest.mark.skipif(
    not rar_available(), reason='UnRAR binary not available')

FIXTURES = Path(__file__).parent / 'rar_fixtures'


def _rar_bytes(name):
    return io.BytesIO((FIXTURES / name).read_bytes())


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
    """Zipfile-based on purpose: it only works if the .rar really was
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


def test_rar_costume_runs_precheck_loops_and_imports(vault, monkeypatch):
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

    client = _client()

    first = client.post(
        '/api/mex/import/file',
        data={'file': (_rar_bytes('skins.rar'), 'skins.rar')},
        content_type='multipart/form-data',
    )
    assert first.status_code == 200
    assert first.get_json()['type'] == 'duplicate_dialog'
    assert len(validated) == 2
    assert imported == []

    resumed = client.post(
        '/api/mex/import/file',
        data={'file': (_rar_bytes('skins.rar'), 'skins.rar'),
              'duplicate_action': 'skip'},
        content_type='multipart/form-data',
    )
    body = resumed.get_json()

    assert resumed.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert imported == ['PlFxRe.dat']


def test_rar_stage_duplicate_skip(vault, monkeypatch):
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

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (_rar_bytes('stages.rar'), 'stages.rar'),
              'duplicate_action': 'skip'},
        content_type='multipart/form-data',
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['imported_count'] == 1
    assert body['skipped_count'] == 1
    assert imported == ['GrNBa new.dat']


def test_container_zip_converts_inner_rar(vault, monkeypatch):
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

    inner = (FIXTURES / 'fox lavender.rar').read_bytes()
    container = _zip_bytes({'fox lavender.rar': inner})

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


def test_unreadable_rar_upload_says_so(vault):
    """A corrupt or password-protected .rar reports that, rather than the
    "could not detect any mods" a raw non-zip would produce downstream."""
    vault.write({'characters': {}, 'stages': {}})

    resp = _client().post(
        '/api/mex/import/file',
        # A RAR signature over garbage: format detection reads the bytes, not the
        # extension, so a corrupt archive must still look like one.
        data={'file': (io.BytesIO(b'Rar!\x1a\x07\x01\x00' + b'not a real rar'), 'broken.rar')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 400
    assert 'could not be opened' in resp.get_json()['error']


def _header_encrypted_rar():
    """A RAR5 whose headers are encrypted: signature, then the archive
    encryption header (type 4, KDF count 15, 16-byte salt), then ciphertext."""
    def vint(n):
        out = bytearray()
        while True:
            low, n = n & 0x7f, n >> 7
            out.append(low | (0x80 if n else 0))
            if not n:
                return bytes(out)
    body = vint(4) + vint(0) + vint(0) + vint(0) + bytes([15]) + bytes(range(16))
    header = vint(len(body)) + body
    return (b'Rar!\x1a\x07\x01\x00' + struct.pack('<I', zlib.crc32(header))
            + header + bytes(64))


def test_header_encrypted_rar_upload_says_it_could_not_be_opened(vault):
    """Without the password rarfile lists no members and reports no error, so
    this used to repack an empty zip and say "could not detect any mods"."""
    vault.write({'characters': {}, 'stages': {}})

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (io.BytesIO(_header_encrypted_rar()), 'locked.rar')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 400
    assert 'could not be opened' in resp.get_json()['error']


def test_rar_upload_is_refused_when_unrar_is_missing(monkeypatch):
    """The door closes politely instead of letting the archive fall through
    to a baffling "could not detect any mods in this file"."""
    monkeypatch.setattr(routes, 'rar_available', lambda: False)
    monkeypatch.setattr(unified_archive, 'rar_available', lambda: False)

    resp = _client().post(
        '/api/mex/import/file',
        data={'file': (_rar_bytes('skins.rar'), 'skins.rar')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 400
    assert 'rar' in resp.get_json()['error'].lower()
