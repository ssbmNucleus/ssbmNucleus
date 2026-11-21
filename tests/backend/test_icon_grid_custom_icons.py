"""Icon-grid import must keep CUSTOM fighters' CSS icons (community #28:
"Nucleus' Vault is not saving custom CSS icons for characters").

Two ways they were dropped on the floor at import time:
  * an '=wolf.png' in a loose icon pack -- only vanilla names were accepted;
  * a bare mexSelectChr.dat (no MxDt.dat beside it) -- no slot table, so every
    icon went unlabeled and the import failed with "No recognizable icons".
"""
import zipfile

from flask import Flask
from PIL import Image

from vault.routes.menus import icons, menus_bp
from vault.menus import icons as icons_engine
from projects.routes.menus import icons as project_icons


def _png(path, color=(255, 0, 0, 255)):
    Image.new('RGBA', (64, 56), color).save(path)


def _isolate(tmp_path, monkeypatch):
    grid = tmp_path / 'icon_grid'
    grid.mkdir()
    monkeypatch.setattr(icons, 'ICON_GRID_PATH', grid)
    monkeypatch.setattr(icons_engine, 'ICON_GRID_PATH', grid)    # import / catalog (engine)
    monkeypatch.setattr(project_icons, 'ICON_GRID_PATH', grid)   # the install routes
    monkeypatch.setattr(icons_engine, 'ICON_GRID_METADATA', grid / 'metadata.json')
    return grid


def test_loose_pack_keeps_custom_fighter_icons(tmp_path, monkeypatch):
    grid = _isolate(tmp_path, monkeypatch)
    src = tmp_path / 'src'
    src.mkdir()
    for name in ('=mario.png', '=luigi.png', '=wolf.png', '=diddy_kong.png'):
        _png(src / name)
    _png(src / 'readme_banner.png')          # not '=': still not an icon
    z = tmp_path / 'pack.zip'
    with zipfile.ZipFile(z, 'w') as zf:
        for p in src.iterdir():
            zf.write(p, p.name)

    mods = icons_engine.install_icon_grid_mod(z, name='pack')
    names = [e['character'] for e in mods[0]['icons']]
    assert names == ['Mario', 'Luigi', 'Diddy Kong', 'Wolf']
    mod_dir = grid / mods[0]['id'] / 'icons'
    assert (mod_dir / 'Wolf.png').exists() and (mod_dir / 'Diddy_Kong.png').exists()


def _fake_mex_dump(slot_count):
    def dump(dat_path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        for i in range(slot_count):
            fg = f'icon_{i:02d}_fg.png'
            _png(out_dir / fg, (i * 9 % 256, 0, 0, 255))
            entries.append({'index': i, 'foreground': fg})
        return {'format': 'mex', 'icons': entries}
    return dump


def test_bare_mexselectchr_labels_stock_slots_and_keeps_extras(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(icons_engine, '_dump_dat_icons', _fake_mex_dump(27))
    z = tmp_path / 'css.zip'
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr('mexSelectChr.dat', b'not parsed -- dump is faked')

    mods = icons_engine.install_icon_grid_mod(z, name='mex')
    names = [e['character'] for e in mods[0]['icons']]
    assert len(names) == 27
    assert names[:25] == [n for n in icons_engine.ROSTER_ORDER if n != 'Sheik']
    assert names[25:] == ['Extra Icon 1', 'Extra Icon 2']


def test_install_plan_skips_unnamed_extras_until_relabeled(tmp_path, monkeypatch):
    grid = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(icons_engine, '_dump_dat_icons', _fake_mex_dump(26))
    monkeypatch.setattr('vault.menus.installed.record_installed_menu_mod',
                        lambda *a, **k: None)
    z = tmp_path / 'css.zip'
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr('mexSelectChr.dat', b'x')
    mod_id = icons_engine.install_icon_grid_mod(z, name='mex')[0]['id']

    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    client = app.test_client()

    plan = client.post(f'/api/mex/menus/css/icon_grid/install/{mod_id}').get_json()
    planned = {e['character'] for e in plan['icons']}
    assert 'Extra Icon 1' not in planned and 'Mario' in planned

    res = client.post(f'/api/mex/menus/css/icon_grid/{mod_id}/relabel',
                      json={'old_character': 'Extra Icon 1', 'new_character': 'Wolf'})
    assert res.status_code == 200
    assert (grid / mod_id / 'icons' / 'Wolf.png').exists()
    plan = client.post(f'/api/mex/menus/css/icon_grid/install/{mod_id}').get_json()
    assert 'Wolf' in {e['character'] for e in plan['icons']}
