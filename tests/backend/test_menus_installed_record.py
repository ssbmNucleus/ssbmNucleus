"""What the ISO editor's Menus tab shows under "Currently in MEX" for the HUD
typeface slots (/api/mex/menus/installed).

A HUD typeface mod can cover the damage percent digits, the READY/GO word
banners, or both. Every install used to be filed under hud:percent_font, so a
Ready/Go pack showed on the Percent Font tab and Ready/Go said "Vanilla".
Installs now record the tab they came from plus every category the mod
covers, and old records are repaired when read.
"""
import json

import pytest
from flask import Flask

from vault.routes.menus import menus_bp
from vault.routes.menus import percent
from vault.menus import percent as percent_engine, percent_install
from projects.routes.menus import percent as project_percent
import core.state
from core.state import clear_project_path
from tests.left_out import needs_hud_manifest



# Slot shapes as mod.json stores them: DmgNum anim = percent digits,
# ScInfCnt mat ordinal 13/14 = READY/GO banners (core.hud_words.WORD_MAT_ORDINALS).
DIGIT_SLOT = {'root': 'DmgNum_scene_models', 'kind': 'anim', 'ordinal': 0,
              'width': 32, 'height': 36, 'format': 'IA4', 'file': 's0.png', 'replaced': True}
READY_SLOT = {'root': 'ScInfCnt_scene_models', 'kind': 'mat', 'ordinal': 13,
              'width': 256, 'height': 64, 'format': 'IA4', 'file': 's1.png', 'replaced': True}


@pytest.fixture
def env(tmp_path, monkeypatch):
    storage = tmp_path / 'percent'
    storage.mkdir()
    monkeypatch.setattr(percent, 'PERCENT_PATH', storage)
    monkeypatch.setattr(percent_engine, 'PERCENT_PATH', storage)
    monkeypatch.setattr(project_percent, 'PERCENT_PATH', storage)   # installs read the same store
    monkeypatch.setattr(percent_install, 'PERCENT_PATH', storage)
    monkeypatch.setattr(percent_engine, 'PERCENT_METADATA', storage / 'metadata.json')

    project_dir = tmp_path / 'project'
    (project_dir / 'files').mkdir(parents=True)
    (project_dir / 'files' / 'IfAll.usd').write_bytes(b'stub')
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    # set the open project without set_project_path's background menu-ref
    # derivation thread (it races other tests over the derived HUD refs)
    monkeypatch.setattr(core.state, '_current_project_path', project_dir / 'project.mexproj')

    applied = []
    # The HSDRawViewer write itself is covered by test_percent_blueprint.py;
    # these tests are about the bookkeeping around it.
    monkeypatch.setattr(project_percent, 'apply_percent_mod',
                        lambda mod_id, path, **kw: applied.append((mod_id, kw)) or {})

    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    client = app.test_client()
    client.project_dir = project_dir
    client.storage = storage
    client.applied = applied
    return client


def _mod(env, mod_id, name, slots, **extra):
    mod = {'id': mod_id, 'name': name, 'description': '', 'source': 'glyphs',
           'region': 'usd', 'slots': slots, 'created': '2026-09-01T00:00:00', **extra}
    (env.storage / mod_id).mkdir()
    (env.storage / mod_id / 'mod.json').write_text(json.dumps(mod), encoding='utf-8')
    return mod


def _installed(env):
    res = env.get('/api/mex/menus/installed')
    assert res.status_code == 200
    return res.get_json()['installed']


def _record_file(env):
    return json.loads((env.project_dir / 'nucleus_menus.json').read_text(encoding='utf-8'))


@needs_hud_manifest()
def test_ready_go_install_is_recorded_under_ready_go(env):
    _mod(env, 'rg1', 'Words', [READY_SLOT])
    res = env.post('/api/mex/menus/percent/install/rg1', json={'slot': 'ready_go'})
    assert res.status_code == 200
    body = res.get_json()
    assert set(body['installed']) == {'hud:ready_go'}

    installed = _installed(env)
    assert installed['hud:ready_go']['id'] == 'rg1'
    assert installed['hud:ready_go']['kind'] == 'ready_go'
    assert 'hud:percent_font' not in installed


def test_percent_install_is_recorded_under_percent_font(env):
    _mod(env, 'pf1', 'Digits', [DIGIT_SLOT])
    env.post('/api/mex/menus/percent/install/pf1', json={'slot': 'percent_font'})
    installed = _installed(env)
    assert installed['hud:percent_font']['id'] == 'pf1'
    assert installed['hud:percent_font']['categories'] == ['percent']
    assert 'hud:ready_go' not in installed


@needs_hud_manifest()
def test_ready_go_install_keeps_the_percent_font_record(env):
    _mod(env, 'pf1', 'Digits', [DIGIT_SLOT])
    _mod(env, 'rg1', 'Words', [READY_SLOT])
    env.post('/api/mex/menus/percent/install/pf1', json={'slot': 'percent_font'})
    env.post('/api/mex/menus/percent/install/rg1', json={'slot': 'ready_go'})
    installed = _installed(env)
    assert installed['hud:percent_font']['id'] == 'pf1'
    assert installed['hud:ready_go']['id'] == 'rg1'


def test_mod_covering_both_is_recorded_in_both_slots(env):
    # Install writes every stored slot, so the digits AND the banners change.
    _mod(env, 'both', 'Full typeface', [DIGIT_SLOT, READY_SLOT])
    res = env.post('/api/mex/menus/percent/install/both', json={'slot': 'ready_go'})
    assert set(res.get_json()['installed']) == {'hud:ready_go', 'hud:percent_font'}
    installed = _installed(env)
    assert installed['hud:percent_font']['id'] == 'both'
    assert installed['hud:ready_go']['id'] == 'both'
    assert installed['hud:percent_font']['kind'] == 'percent_font'


@needs_hud_manifest()
def test_install_without_a_slot_falls_back_to_the_mod_categories(env):
    # Older clients (and scripts) post no body at all.
    _mod(env, 'rg1', 'Words', [READY_SLOT])
    res = env.post('/api/mex/menus/percent/install/rg1')
    assert res.status_code == 200
    assert set(_installed(env)) == {'hud:ready_go'}


def test_failed_install_records_nothing(env, monkeypatch):
    _mod(env, 'rg1', 'Words', [READY_SLOT])

    def boom(mod_id, path, **kw):
        raise RuntimeError('No textures stored for this mod')
    monkeypatch.setattr(project_percent, 'apply_percent_mod', boom)
    res = env.post('/api/mex/menus/percent/install/rg1', json={'slot': 'ready_go'})
    assert res.status_code == 400
    assert _installed(env) == {}


# ── read-time repair of records written by the old install route ──

def _write_legacy(env, installed):
    (env.project_dir / 'nucleus_menus.json').write_text(
        json.dumps({'installed': installed}), encoding='utf-8')


def _legacy_entry(mod_id, name, when='2026-09-10T10:00:00'):
    return {'id': mod_id, 'name': name, 'imageUrl': f'/api/mex/menus/percent/image/{mod_id}',
            'kind': 'percent_font', 'installed': when}


@needs_hud_manifest()
def test_repair_moves_a_ready_go_pack_off_the_percent_font_slot(env):
    _mod(env, 'rg1', 'Words', [READY_SLOT])
    _write_legacy(env, {'hud:percent_font': _legacy_entry('rg1', 'Words'),
                        'css:doors': {'id': 'd1', 'name': 'Doors', 'kind': 'css_doors'}})
    installed = _installed(env)
    assert 'hud:percent_font' not in installed
    assert installed['hud:ready_go']['id'] == 'rg1'
    assert installed['hud:ready_go']['kind'] == 'ready_go'
    assert installed['css:doors']['id'] == 'd1'          # other slots untouched
    # persisted, and a second read changes nothing
    saved = _record_file(env)['installed']
    assert set(saved) == {'hud:ready_go', 'css:doors'}
    assert _installed(env) == installed


@needs_hud_manifest()
def test_repair_keeps_a_newer_ready_go_record(env):
    _mod(env, 'rg1', 'Old words', [READY_SLOT])
    _write_legacy(env, {
        'hud:percent_font': _legacy_entry('rg1', 'Old words', '2026-09-01T10:00:00'),
        'hud:ready_go': {'id': 'rg2', 'name': 'New words', 'kind': 'ready_go',
                         'categories': ['readygo'], 'installed': '2026-09-20T10:00:00'},
    })
    installed = _installed(env)
    assert set(installed) == {'hud:ready_go'}
    assert installed['hud:ready_go']['id'] == 'rg2'


@needs_hud_manifest()
def test_repair_fills_ready_go_for_a_legacy_full_typeface(env):
    _mod(env, 'both', 'Full typeface', [DIGIT_SLOT, READY_SLOT])
    _write_legacy(env, {'hud:percent_font': _legacy_entry('both', 'Full typeface')})
    installed = _installed(env)
    assert installed['hud:percent_font']['id'] == 'both'
    assert installed['hud:ready_go']['id'] == 'both'


def test_repair_leaves_a_real_percent_font_alone(env):
    _mod(env, 'pf1', 'Digits', [DIGIT_SLOT])
    _write_legacy(env, {'hud:percent_font': _legacy_entry('pf1', 'Digits')})
    installed = _installed(env)
    assert set(installed) == {'hud:percent_font'}
    assert installed['hud:percent_font']['id'] == 'pf1'


@needs_hud_manifest()
def test_repair_does_not_resurrect_a_cleared_ready_go_slot(env):
    # New-style records carry `categories`; clearing hud:ready_go later (a
    # restore) must not be undone by the legacy repair.
    _mod(env, 'both', 'Full typeface', [DIGIT_SLOT, READY_SLOT])
    env.post('/api/mex/menus/percent/install/both', json={'slot': 'percent_font'})
    data = _record_file(env)
    del data['installed']['hud:ready_go']
    (env.project_dir / 'nucleus_menus.json').write_text(json.dumps(data), encoding='utf-8')
    assert set(_installed(env)) == {'hud:percent_font'}


def test_repair_skips_records_whose_vault_mod_is_gone(env):
    _write_legacy(env, {'hud:percent_font': _legacy_entry('gone', 'Deleted mod')})
    installed = _installed(env)
    assert installed['hud:percent_font']['id'] == 'gone'


def test_installed_is_empty_without_a_project(env):
    clear_project_path()
    assert _installed(env) == {}


# ── CSS icon grid: recorded only once icons really land ──

class _Run:
    def __init__(self, code, out=''):
        self.returncode, self.stdout, self.stderr = code, out, ''


@pytest.fixture
def icon_env(env, tmp_path, monkeypatch):
    from PIL import Image
    from vault.routes.menus import icons
    from vault.menus import icons as icons_engine
    from projects.routes.menus import icons as project_icons
    grid = tmp_path / 'icon_grid'
    mod_dir = grid / 'ig1' / 'icons'
    mod_dir.mkdir(parents=True)
    for name in ('Mario', 'Fox', 'Falco'):
        Image.new('RGBA', (64, 56), (255, 0, 0, 255)).save(mod_dir / f'{name}.png')
    (grid / 'ig1' / 'mod.json').write_text(json.dumps({
        'id': 'ig1', 'name': 'Grid', 'icons': [
            {'character': c, 'icon': f'{c}.png'} for c in ('Mario', 'Fox', 'Falco')]}),
        encoding='utf-8')
    monkeypatch.setattr(icons, 'ICON_GRID_PATH', grid)
    monkeypatch.setattr(icons_engine, 'ICON_GRID_PATH', grid)
    monkeypatch.setattr(project_icons, 'ICON_GRID_PATH', grid)   # the install routes
    monkeypatch.setattr(icons_engine, 'ICON_GRID_METADATA', grid / 'metadata.json')
    mexcli = tmp_path / 'mexcli.exe'
    mexcli.write_bytes(b'')
    monkeypatch.setattr(project_icons, 'MEXCLI_PATH', mexcli)
    env.fail = set()
    monkeypatch.setattr(project_icons.subprocess, 'run',
                        lambda cmd, **kw: _Run(1, 'boom') if cmd[3] in env.fail else _Run(0))
    return env


def _install_grid(env):
    plan = env.post('/api/mex/menus/css/icon_grid/install/ig1').get_json()
    results = [env.post('/api/mex/menus/css/icon_grid/install/ig1/icon', json=icon).status_code
               for icon in plan['icons']]
    return plan, results


def test_icon_grid_plan_alone_records_nothing(icon_env):
    plan = icon_env.post('/api/mex/menus/css/icon_grid/install/ig1').get_json()
    assert plan['total'] == 3
    assert 'css:icon_grid' not in _installed(icon_env)


def test_icon_grid_failed_install_records_nothing(icon_env):
    icon_env.fail = {'Mario', 'Fox', 'Falco'}
    _plan, results = _install_grid(icon_env)
    # main quarantines a failed whole-workspace save before another icon can write.
    assert results == [500, 409, 409]
    assert 'css:icon_grid' not in _installed(icon_env)


def test_icon_grid_full_install_is_recorded(icon_env):
    _plan, results = _install_grid(icon_env)
    assert results == [200, 200, 200]
    entry = _installed(icon_env)['css:icon_grid']
    assert entry['id'] == 'ig1'
    assert sorted(entry['icons_installed']) == ['Falco', 'Fox', 'Mario']
    assert entry['icons_total'] == 3


def test_icon_grid_partial_install_says_how_many_landed(icon_env):
    icon_env.fail = {'Fox'}
    _plan, results = _install_grid(icon_env)
    assert results == [200, 500, 409]
    entry = _installed(icon_env)['css:icon_grid']
    assert entry['icons_installed'] == ['Mario']
    assert entry['icons_total'] == 3


def test_icon_grid_reinstall_starts_a_fresh_count(icon_env):
    # A client can stop after one successful icon without a failed workspace
    # save. Starting another plan must replace, not accumulate, its count.
    plan = icon_env.post('/api/mex/menus/css/icon_grid/install/ig1').get_json()
    first = icon_env.post('/api/mex/menus/css/icon_grid/install/ig1/icon',
                          json=plan['icons'][0])
    assert first.status_code == 200
    assert len(_installed(icon_env)['css:icon_grid']['icons_installed']) == 1
    _install_grid(icon_env)
    entry = _installed(icon_env)['css:icon_grid']
    assert len(entry['icons_installed']) == 3


def test_icon_grid_single_icon_without_a_plan_still_records(icon_env):
    # scripted callers that post only {character, icon}
    res = icon_env.post('/api/mex/menus/css/icon_grid/install/ig1/icon',
                        json={'character': 'Mario', 'icon': 'Mario.png'})
    assert res.status_code == 200
    entry = _installed(icon_env)['css:icon_grid']
    assert entry['icons_installed'] == ['Mario']
    assert 'icons_total' not in entry


# ── preview snapshot: vault edits/deletes don't change "Currently in MEX" ──

def _png_bytes(color, size=(48, 24)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGBA', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _pixel(data):
    import io
    from PIL import Image
    return Image.open(io.BytesIO(data)).convert('RGBA').getpixel((0, 0))


def test_install_snapshots_the_preview_into_the_project(env):
    _mod(env, 'rg1', 'Words', [READY_SLOT], screenshot='screenshot.png')
    (env.storage / 'rg1' / 'screenshot.png').write_bytes(_png_bytes((255, 0, 0, 255)))
    env.post('/api/mex/menus/percent/install/rg1', json={'slot': 'ready_go'})

    entry = _installed(env)['hud:ready_go']
    assert entry['snapshot'] == 'hud_ready_go.png'
    assert entry['snapshotUrl'].startswith('/api/mex/menus/installed/preview/hud/ready_go?v=')
    assert (env.project_dir / 'nucleus_menus_previews' / 'hud_ready_go.png').is_file()
    assert entry['imageUrl'] == '/api/mex/menus/percent/image/rg1'   # fallback kept

    res = env.get(entry['snapshotUrl'])
    assert res.status_code == 200
    assert _pixel(res.data) == (255, 0, 0, 255)

    # editing the vault mod's picture does not change the installed one ...
    (env.storage / 'rg1' / 'screenshot.png').write_bytes(_png_bytes((0, 0, 255, 255)))
    assert _pixel(env.get(entry['snapshotUrl']).data) == (255, 0, 0, 255)
    # ... and neither does deleting the vault mod
    import shutil
    shutil.rmtree(env.storage / 'rg1')
    assert env.get(entry['snapshotUrl']).status_code == 200


def test_big_previews_are_downscaled(env):
    _mod(env, 'pf1', 'Digits', [DIGIT_SLOT], screenshot='screenshot.png')
    (env.storage / 'pf1' / 'screenshot.png').write_bytes(_png_bytes((0, 255, 0, 255), (1920, 1080)))
    env.post('/api/mex/menus/percent/install/pf1', json={'slot': 'percent_font'})
    from PIL import Image
    with Image.open(env.project_dir / 'nucleus_menus_previews' / 'hud_percent_font.png') as im:
        assert max(im.size) == 640


def test_mod_without_a_preview_records_no_snapshot(env):
    _mod(env, 'rg1', 'Words', [READY_SLOT])     # no screenshot, no stored textures
    env.post('/api/mex/menus/percent/install/rg1', json={'slot': 'ready_go'})
    entry = _installed(env)['hud:ready_go']
    assert 'snapshot' not in entry and 'snapshotUrl' not in entry
    assert env.get('/api/mex/menus/installed/preview/hud/ready_go').status_code == 404


def test_storage_url_previews_are_snapshotted(env, monkeypatch):
    from vault.menus import installed
    storage = env.project_dir.parent / 'storage'
    shot = storage / 'menus' / 'css' / 'background' / 'bg1' / 'screenshot.png'
    shot.parent.mkdir(parents=True)
    shot.write_bytes(_png_bytes((9, 9, 9, 255)))
    monkeypatch.setattr(installed, 'STORAGE_PATH', storage)
    installed.record_installed_menu_mod('css:background', 'css_background', {
        'id': 'bg1', 'name': 'BG', 'screenshotUrl': '/storage/menus/css/background/bg1/screenshot.png'})
    assert _installed(env)['css:background']['snapshot'] == 'css_background.png'
    # a path escaping the storage root is never copied
    installed.record_installed_menu_mod('sss:background', 'sss_background', {
        'id': 'bg2', 'name': 'BG2', 'screenshotUrl': '/storage/../project/project.mexproj'})
    assert 'snapshot' not in _installed(env)['sss:background']


def test_clearing_a_slot_removes_its_snapshot(env):
    from vault.menus import installed
    _mod(env, 'rg1', 'Words', [READY_SLOT], screenshot='screenshot.png')
    (env.storage / 'rg1' / 'screenshot.png').write_bytes(_png_bytes((255, 0, 0, 255)))
    env.post('/api/mex/menus/percent/install/rg1', json={'slot': 'ready_go'})
    installed.clear_installed_menu_mod('hud:ready_go')
    assert not (env.project_dir / 'nucleus_menus_previews' / 'hud_ready_go.png').exists()
    assert env.get('/api/mex/menus/installed/preview/hud/ready_go').status_code == 404


def test_preview_route_only_serves_the_slots_own_snapshot(env):
    previews = env.project_dir / 'nucleus_menus_previews'
    previews.mkdir()
    (previews / 'hud_percent_font.png').write_bytes(_png_bytes((1, 2, 3, 255)))
    (env.project_dir / 'secret.png').write_bytes(_png_bytes((4, 5, 6, 255)))
    _write_legacy(env, {
        'hud:ready_go': {'id': 'x', 'name': 'x', 'kind': 'ready_go', 'categories': ['readygo'],
                         'snapshot': 'hud_percent_font.png'},
        'css:doors': {'id': 'd', 'name': 'd', 'kind': 'css_doors', 'snapshot': '../secret.png'},
    })
    assert env.get('/api/mex/menus/installed/preview/hud/ready_go').status_code == 404
    assert env.get('/api/mex/menus/installed/preview/css/doors').status_code == 404
