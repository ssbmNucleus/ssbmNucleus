"""
Round-trip test for the custom-character vault Export -> Import flow.

The old export sent only the bare fighter.zip, so a re-import on another install
lost the CSPs/stocks/costumes and showed "N" placeholders. The fix bundles the
WHOLE vault folder behind a nucleus_export.json marker and restores it verbatim.
Also covers the belt-and-suspenders fallback: a bare fighter.zip whose costume
zips carry csp.png materializes previews via _sync_costume_meta.
"""
from tests.paths import BACKEND
import io
import sys
import json
import zipfile
import pytest
from pathlib import Path

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import vault.routes.custom_characters as cc
import vault.importing.custom_character_zip as cc_zip
import vault.catalog.custom_characters as cc_catalog
import core.metadata as core_metadata  # custom_characters now reads/writes via the DAL


def _make_costume_zip(dat_name, with_previews=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(dat_name, b'\x00DATBYTES')
        if with_previews:
            zf.writestr('csp.png', b'CSPPNG')
            zf.writestr('stc.png', b'STCPNG')
    return buf.getvalue()


def _seed_full_vault_char(root, slug='blaziken', stems=('PlBzNr', 'PlBzRe')):
    """Build a realistic vault folder: fighter.json, fighter.zip, csp_N.png,
    css_icon.png and materialized costumes/."""
    char_dir = root / slug
    (char_dir / 'costumes').mkdir(parents=True)

    fighter_data = {
        'name': 'Blaziken',
        'seriesID': 9,
        'costumes': [{'file': {'fileName': f'{s}.dat'}, 'name': s} for s in stems],
    }
    (char_dir / 'fighter.json').write_text(json.dumps(fighter_data), encoding='utf-8')

    # fighter.zip carries the inner costume zips
    fbuf = io.BytesIO()
    with zipfile.ZipFile(fbuf, 'w') as zf:
        zf.writestr('fighter.json', json.dumps(fighter_data))
        zf.writestr('icon.png', b'ICON')
        for s in stems:
            zf.writestr(f'{s}.zip', _make_costume_zip(f'{s}.dat'))
    (char_dir / 'fighter.zip').write_bytes(fbuf.getvalue())

    (char_dir / 'css_icon.png').write_bytes(b'CSSICON')
    for i, s in enumerate(stems):
        (char_dir / f'csp_{i}.png').write_bytes(f'CSP{i}'.encode())
        (char_dir / f'stock_{i}.png').write_bytes(f'STK{i}'.encode())
        (char_dir / 'costumes' / f'{s}.zip').write_bytes(_make_costume_zip(f'{s}.dat'))
        (char_dir / 'costumes' / f'{s}_csp.png').write_bytes(f'MCSP{i}'.encode())
    return char_dir, fighter_data


def test_export_import_roundtrip_preserves_everything(tmp_path, monkeypatch):
    src_root = tmp_path / 'src'
    src_root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', src_root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', src_root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', src_root)  # slug allocation

    src_meta = tmp_path / 'src_metadata.json'
    src_meta.write_text(json.dumps({
        'custom_characters': [{
            'slug': 'blaziken', 'name': 'Blaziken', 'source': 'zip',
            'series_id': 9, 'costume_count': 2, 'has_css_icon': True,
            'custom_series': {'active': True, 'name': 'Pokémon Plus'},
        }],
    }), encoding='utf-8')
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', src_meta)

    _seed_full_vault_char(src_root)

    export_bytes = cc._build_full_vault_export_bytes('blaziken')
    assert export_bytes is not None
    # the marker must be present and well-formed
    with zipfile.ZipFile(io.BytesIO(export_bytes)) as zf:
        assert cc.NUCLEUS_EXPORT_MARKER in zf.namelist()
        payload = json.loads(zf.read(cc.NUCLEUS_EXPORT_MARKER))
        assert payload['nucleus_export'] == cc.NUCLEUS_EXPORT_KIND
        assert payload['entry']['custom_series']['name'] == 'Pokémon Plus'
        names = set(zf.namelist())
    assert 'csp_0.png' in names and 'costumes/PlBzNr_csp.png' in names

    # --- import on a FRESH install ---
    dst_root = tmp_path / 'dst'
    dst_root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', dst_root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', dst_root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', dst_root)  # slug allocation
    dst_meta = tmp_path / 'dst_metadata.json'
    dst_meta.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', dst_meta)

    entry = cc_zip.import_custom_character_zip_bytes(export_bytes, 'fallback')

    restored = dst_root / entry['slug']
    # EVERYTHING survived: display assets, costumes, series metadata
    assert (restored / 'fighter.json').exists()
    assert (restored / 'css_icon.png').read_bytes() == b'CSSICON'
    assert (restored / 'csp_0.png').read_bytes() == b'CSP0'
    assert (restored / 'costumes' / 'PlBzNr_csp.png').read_bytes() == b'MCSP0'
    assert entry['custom_series']['name'] == 'Pokémon Plus'
    assert entry['has_css_icon'] is True

    data = json.loads(dst_meta.read_text(encoding='utf-8'))
    assert any(c['slug'] == entry['slug'] for c in data['custom_characters'])


def test_bare_fighter_zip_materializes_csp_from_inner_costume(tmp_path, monkeypatch):
    """A bare fighter.zip (no csp_N.png) still shows CSPs: _sync_costume_meta
    pulls csp.png out of each inner costume zip."""
    root = tmp_path / 'vault'
    root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', root)  # slug allocation

    stems = ('PlBzNr',)
    fighter_data = {
        'name': 'Bare', 'seriesID': 0,
        'costumes': [{'file': {'fileName': f'{s}.dat'}, 'name': s} for s in stems],
    }
    char_dir = root / 'bare'
    char_dir.mkdir()
    fbuf = io.BytesIO()
    with zipfile.ZipFile(fbuf, 'w') as zf:
        zf.writestr('fighter.json', json.dumps(fighter_data))
        for s in stems:
            zf.writestr(f'{s}.zip', _make_costume_zip(f'{s}.dat', with_previews=True))
    (char_dir / 'fighter.zip').write_bytes(fbuf.getvalue())

    entry = {'slug': 'bare', 'name': 'Bare'}
    changed = cc._sync_costume_meta(entry, char_dir, fighter_data)

    assert changed
    assert (char_dir / 'costumes' / 'PlBzNr_csp.png').read_bytes() == b'CSPPNG'
    assert (char_dir / 'costumes' / 'PlBzNr_stc.png').read_bytes() == b'STCPNG'
    meta = {m['id']: m for m in entry['costume_meta']}
    assert meta['PlBzNr']['has_csp'] is True


def test_zip_slip_member_is_refused(tmp_path, monkeypatch):
    """A malicious export member that escapes char_dir must fail the restore.

    It used to be skipped with a warning while the rest of the package was
    restored, and the prefix check it was skipped by let
    `../<slug>-target/fighter.json` through into a sibling character. The
    shared extractor validates every member before the first write, so a
    package carrying one is refused whole.
    """
    root = tmp_path / 'vault'
    root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', root)  # slug allocation
    meta = tmp_path / 'metadata.json'
    meta.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', meta)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(cc.NUCLEUS_EXPORT_MARKER, json.dumps({
            'nucleus_export': cc.NUCLEUS_EXPORT_KIND, 'version': 1,
            'entry': {'slug': 'evil', 'name': 'Evil'},
        }))
        zf.writestr('fighter.json', json.dumps({'name': 'Evil', 'costumes': []}))
        zf.writestr('../escaped.txt', b'PWNED')

    from core.safe_extract import UnsafeArchiveMember
    with pytest.raises(UnsafeArchiveMember):
        cc_zip.import_custom_character_zip_bytes(buf.getvalue(), 'fallback')

    assert not (tmp_path / 'escaped.txt').exists()
    assert not (root / 'evil').exists()


def test_restore_cannot_overwrite_a_sibling_character(tmp_path, monkeypatch):
    """The review's reproduced probe: `../<other>/fighter.json` in a restore."""
    root = tmp_path / 'vault'
    root.mkdir()
    victim = root / 'review-target'
    victim.mkdir()
    (victim / 'fighter.json').write_text('original', encoding='utf-8')
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', root)  # slug allocation
    meta = tmp_path / 'metadata.json'
    meta.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', meta)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(cc.NUCLEUS_EXPORT_MARKER, json.dumps({
            'nucleus_export': cc.NUCLEUS_EXPORT_KIND, 'version': 1,
            'entry': {'slug': 'review', 'name': 'review'},
        }))
        zf.writestr('fighter.json', json.dumps({'name': 'review', 'costumes': []}))
        zf.writestr('../review-target/fighter.json', b'PWNED')

    from core.safe_extract import UnsafeArchiveMember
    with pytest.raises(UnsafeArchiveMember):
        cc_zip.import_custom_character_zip_bytes(buf.getvalue(), 'fallback')
    assert (victim / 'fighter.json').read_text(encoding='utf-8') == 'original'


def test_restore_refuses_an_executable_member(tmp_path, monkeypatch):
    """A full-vault export never contains a .exe; one that does is not ours."""
    root = tmp_path / 'vault'
    root.mkdir()
    monkeypatch.setattr(cc, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_zip, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', root)  # slug allocation
    meta = tmp_path / 'metadata.json'
    meta.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', meta)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(cc.NUCLEUS_EXPORT_MARKER, json.dumps({
            'nucleus_export': cc.NUCLEUS_EXPORT_KIND, 'version': 1,
            'entry': {'slug': 'evil', 'name': 'Evil'},
        }))
        zf.writestr('fighter.json', json.dumps({'name': 'Evil', 'costumes': []}))
        zf.writestr('tools/setup.exe', b'MZ')

    from core.safe_extract import UnsafeArchiveMember
    with pytest.raises(UnsafeArchiveMember, match='never writes'):
        cc_zip.import_custom_character_zip_bytes(buf.getvalue(), 'fallback')
    assert not (root / 'evil').exists()
