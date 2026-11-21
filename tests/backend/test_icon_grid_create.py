"""POST /api/mex/menus/css/icon_grid/create — the Menus page's "+" for icon
grids: a grid seeded from the vanilla MnSlChr, built through the SAME
installer an imported MnSlChr goes through."""
import zipfile

from flask import Flask

from vault.routes.menus import menus_bp
from vault.menus import icons
import shared.vanilla_extract.vanilla_refs as vanilla_refs


def _client():
    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    return app.test_client()


def test_create_seeds_from_the_vanilla_css_through_the_installer(tmp_path, monkeypatch):
    vanilla = tmp_path / 'MnSlChr.usd'
    vanilla.write_bytes(b'vanilla css bytes')
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref',
                        lambda name, storage_path=None: vanilla if name == 'MnSlChr.usd' else None)
    seen = {}

    def fake_install(zip_path, name=None, description=''):
        with zipfile.ZipFile(zip_path) as zf:
            seen['members'] = zf.namelist()
            seen['bytes'] = zf.read('MnSlChr.usd')
        seen['name'] = name
        return [{'id': 'ig_new', 'name': name, 'icons': []}]
    monkeypatch.setattr(icons, 'install_icon_grid_mod', fake_install)

    resp = _client().post('/api/mex/menus/css/icon_grid/create', json={})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['mod']['id'] == 'ig_new'
    assert seen == {'members': ['MnSlChr.usd'], 'bytes': b'vanilla css bytes', 'name': 'New Icon Grid'}


def test_create_without_a_vanilla_reference_explains(monkeypatch):
    monkeypatch.setattr(vanilla_refs, 'ensure_vanilla_ref', lambda name, storage_path=None: None)
    resp = _client().post('/api/mex/menus/css/icon_grid/create', json={'name': 'x'})
    assert resp.status_code == 400
    assert 'vanilla' in resp.get_json()['error'].lower()
