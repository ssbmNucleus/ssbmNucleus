"""
Installing a vault costume must ship the portrait the user made ACTIVE in
Portraits ("Manage CSPs"), not whatever csp.png the zip happens to carry.

Before 2026-09-08 /api/mex/import handed MexCLI the raw vault zip, whose
csp.png is only ever the original portrait (or missing), so alternates never
reached a project. These cover core.active_portrait and both import endpoints
with MexCLI stubbed out.
"""
from tests.paths import BACKEND
import io
import sys
import uuid
import shutil
import zipfile
from pathlib import Path

import pytest
from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from core import active_portrait as ap  # noqa: E402
import projects.routes.costumes as costumes  # noqa: E402


@pytest.fixture
def tmp_path():
    root = Path(__file__).parent / '.tmp-install-portrait'
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    assert path.parent.resolve() == root.resolve()
    shutil.rmtree(path)


def _zip(path, members):
    with zipfile.ZipFile(path, 'w') as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def _members(path):
    with zipfile.ZipFile(path) as zf:
        return {i.filename: zf.read(i.filename) for i in zf.infolist()}


def _vault(tmp_path, *, with_zip_csp=True, active=None, alts=()):
    """storage/Falco/bk.zip + alt files + metadata for one skin."""
    d = tmp_path / 'storage' / 'Falco'
    d.mkdir(parents=True)
    members = {'PlFcReMod.dat': b'DAT'}
    if with_zip_csp:
        members['csp.png'] = b'ORIGINAL'
    _zip(d / 'bk.zip', members)
    (d / 'bk_csp.png').write_bytes(b'STANDALONE')
    alt_meta = []
    for aid, pose, is_hd in alts:
        fn = f'bk_csp_alt_{aid}.png'
        (d / fn).write_bytes(f'ALT-{aid}'.encode())
        alt_meta.append({'id': aid, 'filename': fn, 'pose_name': pose, 'is_hd': is_hd})
    meta = {'characters': {'Falco': {'skins': [{
        'id': 'bk', 'has_csp': True, 'active_csp_id': active, 'alternate_csps': alt_meta}]}}}
    return d / 'bk.zip', meta


# ---- core.active_portrait -----------------------------------------------------

def test_no_alternate_installs_zip_as_is(tmp_path):
    zip_path, meta = _vault(tmp_path)
    assert ap.prepare_install_zip(zip_path, meta) is None


def test_active_alternate_is_baked_into_a_temp_copy(tmp_path):
    zip_path, meta = _vault(tmp_path, active='a1', alts=[('a1', 'jump', False), ('a1_hd', 'jump', True)])
    tmp = ap.prepare_install_zip(zip_path, meta, temp_dir=tmp_path)
    assert tmp is not None and tmp != zip_path
    assert _members(tmp) == {'PlFcReMod.dat': b'DAT', 'csp.png': b'ALT-a1'}
    # the vault zip is untouched
    assert _members(zip_path)['csp.png'] == b'ORIGINAL'


def test_legacy_active_id_on_hd_member_folds_to_sd(tmp_path):
    zip_path, meta = _vault(tmp_path, active='a1_hd', alts=[('a1', 'jump', False), ('a1_hd', 'jump', True)])
    tmp = ap.prepare_install_zip(zip_path, meta, temp_dir=tmp_path)
    assert _members(tmp)['csp.png'] == b'ALT-a1'


def test_zip_without_csp_gets_the_standalone_portrait(tmp_path):
    zip_path, meta = _vault(tmp_path, with_zip_csp=False)
    tmp = ap.prepare_install_zip(zip_path, meta, temp_dir=tmp_path)
    assert _members(tmp) == {'PlFcReMod.dat': b'DAT', 'csp.png': b'STANDALONE'}


def test_source_zip_is_copied_when_given(tmp_path):
    # Falcon path: the neutralized temp is the archive to copy from
    zip_path, meta = _vault(tmp_path, active='a1', alts=[('a1', 'jump', False)])
    neutral = _zip(tmp_path / 'neutral.zip', {'PlFcReMod.dat': b'NEUTRAL', 'csp.png': b'ORIGINAL'})
    tmp = ap.prepare_install_zip(zip_path, meta, source_zip=neutral, temp_dir=tmp_path)
    assert _members(tmp) == {'PlFcReMod.dat': b'NEUTRAL', 'csp.png': b'ALT-a1'}


def test_dangling_active_id_and_unknown_skin_fail_open(tmp_path):
    zip_path, meta = _vault(tmp_path, active='gone', alts=[('a1', 'jump', False)])
    assert ap.prepare_install_zip(zip_path, meta) is None
    assert ap.prepare_install_zip(zip_path, {'characters': {}}) is None
    assert ap.prepare_install_zip(zip_path, None) is None


# ---- /api/mex/import + /import-batch ------------------------------------------

class _Mex:
    def __init__(self):
        self.calls = []

    def import_costume(self, fighter, path):
        self.calls.append((fighter, Path(path), _members(path)))
        return {'ok': True}

    def import_costumes(self, manifest):
        for fighter, paths in manifest.items():
            for p in paths:
                self.calls.append((fighter, Path(p), _members(p)))
        return {'ok': True}


def _client(monkeypatch, tmp_path, meta):
    mex = _Mex()
    monkeypatch.setattr(costumes, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(costumes, 'load_metadata', lambda: meta)
    monkeypatch.setattr(costumes, 'get_mex_manager', lambda: mex)
    monkeypatch.setattr(costumes, 'reload_mex_manager', lambda: None)
    monkeypatch.setattr(costumes.time, 'sleep', lambda s: None)
    app = Flask(__name__)
    app.register_blueprint(costumes.costumes_bp)
    return app.test_client(), mex


def test_import_endpoint_ships_active_portrait_and_cleans_temp(tmp_path, monkeypatch):
    zip_path, meta = _vault(tmp_path, active='a1', alts=[('a1', 'jump', False)])
    client, mex = _client(monkeypatch, tmp_path, meta)
    resp = client.post('/api/mex/import', json={'fighter': 'Falco', 'costumePath': 'storage/Falco/bk.zip'})
    assert resp.status_code == 200, resp.get_json()
    (fighter, path, members), = mex.calls
    assert fighter == 'Falco'
    assert path != zip_path and members['csp.png'] == b'ALT-a1'
    assert not path.exists(), 'temp portrait zip must be unlinked after install'
    assert _members(zip_path)['csp.png'] == b'ORIGINAL'


def test_import_endpoint_uses_vault_zip_when_original_is_active(tmp_path, monkeypatch):
    zip_path, meta = _vault(tmp_path, alts=[('a1', 'jump', False)])
    client, mex = _client(monkeypatch, tmp_path, meta)
    resp = client.post('/api/mex/import', json={'fighter': 'Falco', 'costumePath': 'storage/Falco/bk.zip'})
    assert resp.status_code == 200
    (_, path, members), = mex.calls
    assert path == zip_path and members['csp.png'] == b'ORIGINAL'


def test_import_batch_ships_active_portraits_per_item(tmp_path, monkeypatch):
    zip_path, meta = _vault(tmp_path, active='a1', alts=[('a1', 'jump', False)])
    # second skin, original active
    d = zip_path.parent
    _zip(d / 'plain.zip', {'PlFcBuMod.dat': b'DAT2', 'csp.png': b'ORIGINAL2'})
    meta['characters']['Falco']['skins'].append({'id': 'plain', 'has_csp': True})
    client, mex = _client(monkeypatch, tmp_path, meta)
    resp = client.post('/api/mex/import-batch', json={'items': [
        {'fighter': 'Falco', 'costumePath': 'storage/Falco/bk.zip'},
        {'fighter': 'Falco', 'costumePath': 'storage/Falco/plain.zip'}]})
    assert resp.status_code == 200, resp.get_json()
    assert [(m['csp.png']) for _, _, m in mex.calls] == [b'ALT-a1', b'ORIGINAL2']
    assert mex.calls[1][1] == d / 'plain.zip'
    assert not mex.calls[0][1].exists(), 'temp portrait zip must be unlinked after install'
