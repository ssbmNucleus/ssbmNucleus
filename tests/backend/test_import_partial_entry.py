"""
Regression tests for the vault-import data-integrity bug: a skin import that was
interrupted (or raced between two unlocked read-modify-write cycles) left a
PARTIAL metadata entry -- `dat_hash`/`slippi_safe`/`filename` set but no
`color`/`has_csp`/`has_stock`/`date_added` -- which crashed the character page.

Two guarantees are covered here:

  (a) import commits COMPLETE-or-nothing: if a mandatory step (CSP render) fails
      mid-import, no partial entry is left behind (test_*exception*).
  (b) a load-time sanitizer heals any partial entry already on disk, deriving
      color from the id slug and recomputing has_csp/has_stock from files
      (test_sanitizer*).

Driven through the real core.metadata DAL via the shared `vault` fixture, so the
same tests keep working when the store swaps from metadata.json to SQLite.
"""
import zipfile

import pytest

import core.metadata as cm
import vault.importing.unified.characters as characters


@pytest.fixture(autouse=True)
def isolate_import_files(vault, monkeypatch):
    # These tests call the importer directly, bypassing VaultHarness.client().
    # Redirect its already-imported storage constant as well as the metadata
    # fixture, so synthetic archives never overwrite the real dev vault.
    monkeypatch.setattr(characters, 'STORAGE_PATH', vault.storage)


def _make_zip(path, dat_name='PlMrNr.dat', dat_bytes=b'\x00' * 64):
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(dat_name, dat_bytes)
    return str(path)


def _char_info(costume_code='PlMrNr', character='Mario', dat_name='PlMrNr.dat'):
    return {
        'character': character,
        'costume_code': costume_code,
        'color': 'Wario',
        'dat_file': dat_name,
        'csp_file': None,
        'stock_file': None,
    }


# --------------------------------------------------------------------------- #
# (a) exception mid-import leaves NO partial entry
# --------------------------------------------------------------------------- #
def test_import_exception_leaves_no_partial_entry(vault, monkeypatch):
    vault.write({'characters': {}, 'stages': {}})

    # slippi validation succeeds (sets slippi_safe + dat_hash early)...
    monkeypatch.setattr(characters, 'validate_for_slippi',
                        lambda p, auto_fix=False: {'slippi_safe': True, 'output': ''})
    # ...but the CSP render (a mandatory step, AFTER dat_hash/slippi are known)
    # blows up -- exactly where a two-phase writer would have already committed
    # the stub with dat_hash+slippi_safe but no color/has_csp.
    def boom(*a, **k):
        raise RuntimeError('CSP render exploded')
    monkeypatch.setattr(characters, 'build_csp_and_stock', boom)

    zip_path = _make_zip(vault.path('upload.zip'))
    result = characters.import_character_costume(
        zip_path, _char_info(), 'Mario - Wario.zip')

    assert result['success'] is False
    # The whole point: metadata was NOT mutated with a half-entry.
    data = vault.read()
    skins = data.get('characters', {}).get('Mario', {}).get('skins', [])
    assert skins == [], f"expected no entry, got {skins}"


def test_successful_import_writes_complete_entry(vault, monkeypatch):
    vault.write({'characters': {}, 'stages': {}})

    monkeypatch.setattr(characters, 'validate_for_slippi',
                        lambda p, auto_fix=False: {'slippi_safe': True, 'output': ''})
    monkeypatch.setattr(characters, 'build_csp_and_stock',
                        lambda *a, **k: {
                            'csp': b'PNGDATA', 'csp_source': 'generated',
                            'stock': b'STOCK', 'stock_source': 'generated',
                        })

    zip_path = _make_zip(vault.path('upload.zip'))
    result = characters.import_character_costume(
        zip_path, _char_info(), 'Mario - Wario.zip')

    assert result['success'] is True
    skins = vault.read()['characters']['Mario']['skins']
    assert len(skins) == 1
    entry = skins[0]
    assert vault.path('Mario', entry['filename']).is_file()
    # every field that the partial-entry bug was missing is present
    for field in ('color', 'has_csp', 'has_stock', 'date_added',
                  'dat_hash', 'slippi_safe', 'filename'):
        assert field in entry, f"complete entry missing {field}: {entry}"
    assert entry['has_csp'] is True
    # display name is derived from the filename slug (lowercased by the importer)
    assert entry['color'] == 'wario'


def test_import_preserves_concurrent_entry(vault, monkeypatch):
    """The locked commit re-reads live metadata, so an entry written by another
    importer DURING the slow CSP render is not clobbered by a stale snapshot."""
    vault.write({'characters': {'Mario': {'skins': []}}, 'stages': {}})

    monkeypatch.setattr(characters, 'validate_for_slippi',
                        lambda p, auto_fix=False: {'slippi_safe': True, 'output': ''})

    # While "our" import is rendering, a concurrent import lands another skin.
    def render_then_race(*a, **k):
        with cm.metadata_transaction() as live:
            live['characters']['Mario']['skins'].append(
                {'id': 'other', 'color': 'Other', 'filename': 'other.zip',
                 'has_csp': False, 'has_stock': False, 'date_added': 'x',
                 'dat_hash': 'deadbeef', 'slippi_safe': True})
        return {'csp': None, 'csp_source': 'none',
                'stock': None, 'stock_source': None}
    monkeypatch.setattr(characters, 'build_csp_and_stock', render_then_race)

    zip_path = _make_zip(vault.path('upload.zip'))
    result = characters.import_character_costume(
        zip_path, _char_info(), 'Mario - Wario.zip')

    assert result['success'] is True
    ids = {s['id'] for s in vault.read()['characters']['Mario']['skins']}
    # BOTH the concurrent 'other' and our import survived (no lost update)
    assert 'other' in ids
    assert len(ids) == 2


# --------------------------------------------------------------------------- #
# (b) load-time sanitizer repairs a synthetic partial entry
# --------------------------------------------------------------------------- #
def test_sanitizer_repairs_partial_entry(vault):
    # The exact fingerprint from the bug report: dat_hash + slippi_safe +
    # filename, but no color / has_csp / has_stock / date_added.
    vault.write({'characters': {'Mario': {'skins': [{
        'id': 'plmrnr-plmrnr05',
        'filename': 'plmrnr-plmrnr05.zip',
        'slippi_safe': True,
        'dat_hash': '75cf25a0981e105e970214e4a26d7bf4',
    }]}}})
    # a CSP file exists on disk, a stock file does not
    vault.touch('Mario', 'plmrnr-plmrnr05_csp.png')

    repaired = cm.sanitize_skin_metadata()

    skin = repaired['characters']['Mario']['skins'][0]
    assert skin['color'] == 'plmrnr05'          # derived from id slug
    assert skin['has_csp'] is True              # csp file exists
    assert skin['has_stock'] is False           # stock file absent
    assert 'date_added' in skin
    # persisted to disk
    on_disk = vault.read()['characters']['Mario']['skins'][0]
    assert on_disk['color'] == 'plmrnr05'


def test_sanitizer_is_idempotent_and_leaves_healthy_entries(vault):
    healthy = {
        'id': 'good', 'color': 'Green', 'filename': 'good.zip',
        'has_csp': True, 'has_stock': True, 'date_added': '2026-01-01T00:00:00',
        'dat_hash': 'abc', 'slippi_safe': True,
    }
    vault.write({'characters': {'Fox': {'skins': [dict(healthy)]}}})

    cm.sanitize_skin_metadata()
    first = vault.read()
    cm.sanitize_skin_metadata()
    second = vault.read()

    assert first == second                       # idempotent
    assert first['characters']['Fox']['skins'][0] == healthy  # untouched


def test_sanitizer_skips_folder_rows(vault):
    vault.write({'characters': {'Fox': {'skins': [
        {'type': 'folder', 'id': 'folder_1', 'name': 'Faves'},
        {'id': 'good', 'color': 'Green', 'filename': 'good.zip'},
    ]}}})
    cm.sanitize_skin_metadata()
    skins = vault.read()['characters']['Fox']['skins']
    # folder row keeps its shape (no bogus color injected)
    assert skins[0] == {'type': 'folder', 'id': 'folder_1', 'name': 'Faves'}
