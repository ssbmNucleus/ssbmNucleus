"""/api/mex/menus/summary — the vault Menus sidebar's count badges.

The counts must agree with what each kind's own list route would return:
backgrounds without a recorded source show on BOTH screens, and a HUD
typeface mod that touches digits and word banners counts under both
percent_font and ready_go.
"""
import json

from flask import Flask

from vault.routes.menus import menus_bp
# the catalogs are read through the engine modules
from vault.menus import icons, backgrounds, doors, pause, percent


def _client(tmp_path, monkeypatch):
    root = tmp_path / 'menus'
    (root / 'icon_grid').mkdir(parents=True)
    (root / 'background').mkdir()
    (root / 'doors').mkdir()
    (root / 'pause').mkdir()
    (root / 'percent').mkdir()
    monkeypatch.setattr(icons, 'ICON_GRID_METADATA', root / 'icon_grid' / 'metadata.json')
    monkeypatch.setattr(backgrounds, 'BG_METADATA', root / 'background' / 'metadata.json')
    monkeypatch.setattr(doors, 'DOORS_METADATA', root / 'doors' / 'metadata.json')
    monkeypatch.setattr(pause, 'PAUSE_METADATA', root / 'pause' / 'metadata.json')
    monkeypatch.setattr(percent, 'PERCENT_METADATA', root / 'percent' / 'metadata.json')
    monkeypatch.setattr(percent, 'PERCENT_PATH', root / 'percent')
    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    return app.test_client(), root


def test_summary_counts_every_kind_like_its_list_route(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    (root / 'icon_grid' / 'metadata.json').write_text(json.dumps({
        'version': '2.0', 'mods': [{'id': 'ig1', 'name': 'A'}, {'id': 'ig2', 'name': 'B'}, {'name': 'no id'}]}))
    (root / 'background' / 'metadata.json').write_text(json.dumps({
        'version': '1.0', 'mods': [
            {'id': 'b1', 'name': 'css only', 'source': 'css'},
            {'id': 'b2', 'name': 'sss only', 'source': 'sss'},
            {'id': 'b3', 'name': 'legacy, no source'},
        ]}))
    (root / 'doors' / 'metadata.json').write_text(json.dumps([{'id': 'd1', 'name': 'door'}]))
    (root / 'pause' / 'metadata.json').write_text(json.dumps({
        'version': '1.0', 'mods': [{'id': 'p1', 'name': 'pause'}]}))
    (root / 'percent' / 'metadata.json').write_text(json.dumps({
        'version': '1.0', 'mods': [
            {'id': 'f1', 'name': 'digits', 'categories': ['percent']},
            {'id': 'f2', 'name': 'words', 'categories': ['readygo']},
            {'id': 'f3', 'name': 'both', 'categories': ['percent', 'readygo']},
        ]}))

    resp = client.get('/api/mex/menus/summary')
    assert resp.status_code == 200
    counts = resp.get_json()['counts']
    assert counts == {
        'css_icon_grid': 2,
        'css_background': 2,   # css + legacy
        'css_doors': 1,
        'sss_background': 2,   # sss + legacy
        'pause_screen': 1,
        'percent_font': 2,
        'ready_go': 2,
    }

    # The list routes agree with the badges.
    assert len(client.get('/api/mex/menus/background/list?menu_type=css').get_json()['mods']) == 2
    assert len(client.get('/api/mex/menus/percent/list?category=readygo').get_json()['mods']) == 2


def test_summary_is_all_zero_on_an_empty_vault(tmp_path, monkeypatch):
    client, _root = _client(tmp_path, monkeypatch)
    counts = client.get('/api/mex/menus/summary').get_json()['counts']
    assert set(counts) == {'css_icon_grid', 'css_background', 'css_doors', 'sss_background',
                           'pause_screen', 'percent_font', 'ready_go'}
    assert all(v == 0 for v in counts.values())
