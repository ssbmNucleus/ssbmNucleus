"""
Vault-index DAL bypasses: proof that every fixed call site now lands in the
ACTIVE storage backend, not just metadata.json.

Each test runs under the `dual_backend` fixture (params json + db). In `db`
mode dual-write is off, so metadata.json is never written — a call site that
still hand-rolled `open(STORAGE_PATH / 'metadata.json')` would read nothing and
these assertions would fail. That is exactly the regression being locked down.
See the DAL contract in core/metadata.py and docs/VAULT_SQLITE_MIGRATION.md.
"""
import hashlib
import io
import json
import sys
import zipfile

import pytest
from flask import Flask

import core.helpers as helpers
import core.metadata as core_metadata
from vault.importing import iso_scanner
import vault.importing.iso_known_hashes as known_hashes
from projects.install import texture_pack
from shared.routes import viewer as viewer_module
from vault.routes import xdelta as xdelta_module


def _costume_zip(dat_name='PlFxNr.dat', payload=b'\x00' * 64) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(dat_name, payload)
    return buf.getvalue()


# --------------------------- vault/routes/xdelta.py ---------------------------

def test_xdelta_save_and_load_use_the_active_backend(dual_backend):
    entries = [{'id': 'ace', 'name': 'Ace Build', 'filename': '1e906281.xdelta'}]

    xdelta_module.save_xdelta_metadata(entries)

    # visible through the DAL (DB row-decomposed in db mode, JSON otherwise)...
    assert core_metadata.load_metadata()['xdelta'] == entries
    # ...and read back by the blueprint's own loader.
    assert xdelta_module.load_xdelta_metadata() == entries


def test_xdelta_save_preserves_the_rest_of_the_vault(dual_backend):
    dual_backend.write({'version': '1.0', 'characters': {'Fox': {'skins': []}},
                        'stages': {}})

    xdelta_module.save_xdelta_metadata([{'id': 'p1'}])

    after = core_metadata.load_metadata()
    assert after['characters'] == {'Fox': {'skins': []}}
    assert after['xdelta'] == [{'id': 'p1'}]


def test_xdelta_load_on_empty_vault_is_empty_list(dual_backend):
    assert xdelta_module.load_xdelta_metadata() == []


# ---------------------------- core/helpers.py -------------------------------

def test_migrate_legacy_character_names_lands_in_active_backend(dual_backend, monkeypatch):
    monkeypatch.setattr(helpers, 'STORAGE_PATH', dual_backend.storage)
    dual_backend.write({
        'version': '1.0',
        'characters': {'Captain Falcon': {'skins': [{'id': 'plca-plca05'}]},
                       'Donkey Kong': {'skins': []}},
        'stages': {},
    })
    (dual_backend.storage / 'Captain Falcon').mkdir()

    helpers.migrate_legacy_character_names()

    chars = core_metadata.load_metadata()['characters']
    assert 'Captain Falcon' not in chars and 'Donkey Kong' not in chars
    assert chars['C. Falcon']['skins'] == [{'id': 'plca-plca05'}]
    assert 'DK' in chars
    # folder rename still happens (outside the metadata lock)
    assert (dual_backend.storage / 'C. Falcon').is_dir()


def test_migrate_legacy_character_names_noop_on_empty_vault(dual_backend, monkeypatch):
    monkeypatch.setattr(helpers, 'STORAGE_PATH', dual_backend.storage)
    helpers.migrate_legacy_character_names()  # must not raise
    assert core_metadata.load_metadata() is None


def test_backfill_dat_hashes_lands_in_active_backend(dual_backend, monkeypatch):
    monkeypatch.setattr(helpers, 'STORAGE_PATH', dual_backend.storage)
    payload = b'\x01\x02\x03' * 16
    dual_backend.touch('Fox', 'cool-fox.zip', data=_costume_zip(payload=payload))
    dual_backend.write({
        'version': '1.0',
        'characters': {'Fox': {'skins': [{'id': 'cool-fox', 'filename': 'cool-fox.zip'}]}},
        'stages': {},
    })

    helpers.backfill_dat_hashes()

    skin = core_metadata.load_metadata()['characters']['Fox']['skins'][0]
    assert skin['dat_hash'] == hashlib.md5(payload).hexdigest()


def test_backfill_dat_hashes_keeps_existing_hashes(dual_backend, monkeypatch):
    monkeypatch.setattr(helpers, 'STORAGE_PATH', dual_backend.storage)
    dual_backend.touch('Fox', 'cool-fox.zip', data=_costume_zip())
    dual_backend.write({
        'characters': {'Fox': {'skins': [
            {'id': 'cool-fox', 'filename': 'cool-fox.zip', 'dat_hash': 'keepme'},
        ]}},
    })

    helpers.backfill_dat_hashes()

    assert core_metadata.load_metadata()['characters']['Fox']['skins'][0]['dat_hash'] == 'keepme'


# --------------------------- shared/routes/viewer.py ---------------------------

def _viewer_client(harness, monkeypatch):
    monkeypatch.setattr(viewer_module, 'STORAGE_PATH', harness.storage)
    app = Flask(__name__)
    app.register_blueprint(viewer_module.viewer_bp)
    return app.test_client()


@pytest.mark.parametrize('route', ['/api/viewer/paths'])
def test_viewer_lookup_sees_backend_only_skin(dual_backend, monkeypatch, route):
    """The viewer path lookup must FIND a skin that exists only in the active
    backend. Before the fix, db mode read a nonexistent metadata.json and
    answered 'No costumes in storage' / 'Character not found'."""
    client = _viewer_client(dual_backend, monkeypatch)
    dual_backend.write({
        'characters': {'Fox': {'skins': [
            {'id': 'cool-fox', 'filename': 'cool-fox.zip', 'color': 'Neutral'},
        ]}},
    })

    resp = client.post(route, json={'character': 'Fox', 'skinId': 'cool-fox'})

    # The zip isn't on disk, so it stops one step LATER than the lookup — which
    # is the proof the lookup itself resolved.
    assert resp.status_code == 404
    assert 'Costume file not found' in resp.get_json()['error']


@pytest.mark.parametrize('route', ['/api/viewer/paths'])
def test_viewer_lookup_still_404s_for_unknown_character(dual_backend, monkeypatch, route):
    client = _viewer_client(dual_backend, monkeypatch)
    dual_backend.write({'characters': {'Fox': {'skins': []}}})

    resp = client.post(route, json={'character': 'Nobody', 'skinId': 'x'})

    assert resp.status_code == 404
    assert 'not found' in resp.get_json()['error']


def test_viewer_paths_404s_on_empty_vault(dual_backend, monkeypatch):
    client = _viewer_client(dual_backend, monkeypatch)
    resp = client.post('/api/viewer/paths', json={'character': 'Fox', 'skinId': 'a'})
    assert resp.status_code == 404
    assert resp.get_json()['error'] == 'No costumes in storage'


# ------------------------------ iso_scanner.py ------------------------------

def test_iso_scanner_vault_hashes_see_backend_only_entries(dual_backend, monkeypatch):
    monkeypatch.setattr(known_hashes, 'STORAGE_PATH', dual_backend.storage)
    payload = b'\xAB' * 32
    dual_backend.touch('Fox', 'cool-fox.zip', data=_costume_zip(payload=payload))
    dual_backend.write({
        'characters': {'Fox': {'skins': [
            {'id': 'cool-fox', 'filename': 'cool-fox.zip', 'dat_hash': 'prefixhash'},
        ]}},
    })

    hashes = iso_scanner._load_vault_hashes()

    assert 'prefixhash' in hashes                              # from the index
    assert hashlib.md5(payload).hexdigest() in hashes          # from the stored zip


def test_iso_scanner_vault_hashes_empty_on_empty_vault(dual_backend, monkeypatch):
    monkeypatch.setattr(known_hashes, 'STORAGE_PATH', dual_backend.storage)
    assert iso_scanner._load_vault_hashes() == {}


# ------------------------------ texture_pack.py -----------------------------

class _FakeHash:
    def __init__(self, value):
        self.value = value

    def __sub__(self, other):
        return abs(self.value - other.value)


class _FakeImagehash:
    @staticmethod
    def phash(image):
        return _FakeHash(0)

    @staticmethod
    def hex_to_hash(text):
        return _FakeHash(int(text, 16))


def _seed_hd_csp(harness):
    from PIL import Image
    csp = harness.path('Fox', 'cool-fox_csp.png')
    Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(csp)
    hd = harness.path('Fox', 'cool-fox_csp_hd.png')
    Image.new('RGBA', (32, 32), (255, 0, 0, 255)).save(hd)
    harness.write({
        'characters': {'Fox': {'skins': [
            {'id': 'cool-fox', 'filename': 'cool-fox.zip',
             'has_hd_csp': True, 'csp_hash': '0'},
        ]}},
    })
    return csp, hd


def test_texture_pack_vault_metadata_uses_active_backend(dual_backend):
    dual_backend.write({'characters': {'Fox': {'skins': [{'id': 'cool-fox'}]}}})
    meta = texture_pack._vault_metadata(dual_backend.storage)
    assert meta['characters']['Fox']['skins'] == [{'id': 'cool-fox'}]


def test_texture_pack_vault_metadata_reads_foreign_folder_as_json(dual_backend, tmp_path):
    """A storage_path that is NOT the live vault stays a plain metadata.json
    read (path= escape hatch) even in db mode — secondary/test vaults."""
    other = tmp_path / 'other-storage'
    other.mkdir()
    (other / 'metadata.json').write_text(json.dumps({'characters': {'Marth': {}}}),
                                         encoding='utf-8')
    dual_backend.write({'characters': {'Fox': {}}})

    assert texture_pack._vault_metadata(other) == {'characters': {'Marth': {}}}
    assert texture_pack._vault_metadata(tmp_path / 'nope') == {}


def test_find_hd_csp_by_hash_sees_backend_only_skin(dual_backend, monkeypatch):
    monkeypatch.setattr(texture_pack, '_imagehash', _FakeImagehash)
    csp, hd = _seed_hd_csp(dual_backend)

    found = texture_pack.find_hd_csp_by_hash(dual_backend.storage, str(csp), 'Fox')

    assert found == hd


def test_watcher_find_hd_csp_by_hash_sees_backend_only_skin(dual_backend, monkeypatch):
    monkeypatch.setitem(sys.modules, 'imagehash', _FakeImagehash)
    csp, hd = _seed_hd_csp(dual_backend)

    watcher = texture_pack.TexturePackMatcher.__new__(texture_pack.TexturePackMatcher)
    watcher.storage_path = dual_backend.storage

    assert watcher._find_hd_csp_by_hash(str(csp), 'Fox') == hd


def test_find_hd_csp_by_hash_none_on_empty_vault(dual_backend, monkeypatch):
    monkeypatch.setattr(texture_pack, '_imagehash', _FakeImagehash)
    from PIL import Image
    csp = dual_backend.path('Fox', 'cool-fox_csp.png')
    Image.new('RGBA', (8, 8)).save(csp)

    assert texture_pack.find_hd_csp_by_hash(dual_backend.storage, str(csp), 'Fox') is None
