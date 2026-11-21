"""menu_checks: "Currently in MEX" read from the project files for the pause
screen, CSS doors, icon grid and the CSS / SSS backgrounds.

Exports are faked with small pictures here (the tolerant comparison itself
is covered in test_menus_file_checks.py); the last tests run the real tools
on copies of the vanilla files when a dev checkout has them.
"""
import json
import shutil
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image, ImageDraw

import core.state
from vault.routes.menus import menus_bp
from vault.menus import menu_checks, menu_exports
# the file checks read the vault stores through the engine modules
from vault.menus import pause, pause_install, doors, icons, backgrounds
from projects.routes.menus import pause as project_pause, doors as project_doors
from projects.routes.menus import backgrounds as project_backgrounds


def _pic(path, color, shape='box', size=(32, 32)):
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w, h = size
    if shape == 'box':
        d.rectangle([w // 6, h // 6, w - w // 6, h - h // 6], outline=color, width=3)
    else:
        d.ellipse([w // 8, h // 8, w - w // 8, h - h // 8], fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


# ── the shared verdict ──

def test_classify():
    c = menu_checks.classify
    assert c(None, None, True) == {'state': 'vanilla', 'stale': False}
    assert c(None, None, False) == {'state': 'custom', 'stale': False}
    rec = {'id': 'x'}
    assert c(rec, True, False) == {'state': 'installed'}
    assert c(rec, False, True) == {'state': 'vanilla', 'stale': True}
    assert c(rec, None, False) == {'state': 'installed', 'unverified': True}
    assert c(rec, False, False) == {'state': 'custom', 'stale': True}
    assert c(rec, True, None) is None          # file unreadable: show the record


# ── fixtures: a project, a vault, and fake exports per file ──

@pytest.fixture
def env(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    files = project / 'files'
    files.mkdir(parents=True)
    for name in ('GmPause.usd', 'MnSlChr.usd', 'MnSlMap.usd'):
        (files / name).write_bytes(b'stub')
    (project / 'project.mexproj').write_text('')
    monkeypatch.setattr(core.state, '_current_project_path', project / 'project.mexproj')
    vault = tmp_path / 'vault'
    monkeypatch.setattr(pause, 'PAUSE_PATH', vault / 'pause')
    monkeypatch.setattr(pause_install, 'PAUSE_PATH', vault / 'pause')
    monkeypatch.setattr(doors, 'DOORS_PATH', vault / 'doors')
    monkeypatch.setattr(icons, 'ICON_GRID_PATH', vault / 'icon_grid')
    monkeypatch.setattr(backgrounds, 'BG_PATH', vault / 'background')
    vanilla = tmp_path / 'vanilla'
    vanilla.mkdir()
    for name in ('GmPause.usd', 'MnSlChr.usd', 'MnSlMap.usd'):
        (vanilla / name).write_bytes(b'vanilla')
    monkeypatch.setattr(menu_checks, '_vanilla_ref',
                        lambda *names: vanilla / names[0] if (vanilla / names[0]).exists() else None)
    exports = {}      # (mode, file name, 'project'|'vanilla'|path) -> dir

    def fake_export(mode, path, timeout=300):
        path = Path(path)
        who = 'vanilla' if path.parent == vanilla else ('project' if path.parent == files else str(path))
        return exports.get((mode, path.name, who))
    monkeypatch.setattr(menu_checks, 'cached_export', fake_export)
    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    c = app.test_client()
    c.tmp, c.project, c.files, c.vault, c.exports = tmp_path, project, files, vault, exports
    return c


def _record(env, installed):
    (env.project / 'nucleus_menus.json').write_text(json.dumps({'installed': installed}))


def _entry(mod_id, kind, when='2099-01-01T00:00:00', **extra):
    return {'id': mod_id, 'name': mod_id, 'kind': kind, 'installed': when, **extra}


def _verify(env, menu):
    body = env.get(f'/api/mex/menus/installed?verify={menu}').get_json()
    return body['verification']


# ── pause screen ──

def _pause_export(env, who, pics):
    d = env.tmp / 'exp' / f'pause_{who}'
    textures = []
    for i, (color, shape, size) in enumerate(pics):
        _pic(d / f't{i}.png', color, shape, size)
        textures.append({'index': i, 'width': size[0], 'height': size[1], 'format': 'IA4',
                         'filename': f't{i}.png'})
    (d / 'manifest.json').write_text(json.dumps({'textures': textures}))
    env.exports[('--pause-screen', 'GmPause.usd', who)] = d


VAN_PAUSE = [((255, 255, 255, 255), 'box', (32, 32)), ((200, 200, 200, 255), 'box', (88, 72))]


def test_pause_vanilla_and_custom(env):
    _pause_export(env, 'vanilla', VAN_PAUSE)
    _pause_export(env, 'project', VAN_PAUSE)
    assert _verify(env, 'hud')['hud:pause_screen'] == {'state': 'vanilla', 'stale': False}
    _pause_export(env, 'project', [VAN_PAUSE[0], ((255, 0, 0, 255), 'dot', (88, 72))])
    assert _verify(env, 'hud')['hud:pause_screen'] == {'state': 'custom', 'stale': False}


def test_pause_picture_mod_is_recognized(env):
    _pause_export(env, 'vanilla', VAN_PAUSE)
    mod_dir = env.vault / 'pause' / 'p1'
    _pic(mod_dir / 'picture.png', (255, 0, 0, 255), 'dot', (176, 144))
    # the importer wrote the picture resized onto the 88x72 main slot
    _pause_export(env, 'project', VAN_PAUSE)
    Image.open(mod_dir / 'picture.png').resize((88, 72), Image.BICUBIC).save(
        env.exports[('--pause-screen', 'GmPause.usd', 'project')] / 't1.png')
    (mod_dir / 'mod.json').write_text(json.dumps({'id': 'p1', 'name': 'p1', 'source': 'image'}))
    _record(env, {'hud:pause_screen': _entry('p1', 'pause_screen')})
    assert _verify(env, 'hud')['hud:pause_screen'] == {'state': 'installed'}
    # another picture in the file: the record no longer holds
    _pause_export(env, 'project', [VAN_PAUSE[0], ((0, 0, 255, 255), 'box', (88, 72))])
    assert _verify(env, 'hud')['hud:pause_screen'] == {'state': 'custom', 'stale': True}


def test_pause_dat_mod_is_recognized(env):
    _pause_export(env, 'vanilla', VAN_PAUSE)
    modded = [((0, 255, 0, 255), 'dot', (32, 32)), VAN_PAUSE[1]]
    _pause_export(env, 'project', modded)
    mod_dir = env.vault / 'pause' / 'd1'
    _pic(mod_dir / 'textures' / 't0.png', (0, 255, 0, 255), 'dot', (32, 32))
    _pic(mod_dir / 'textures' / 't1.png', (200, 200, 200, 255), 'box', (88, 72))
    (mod_dir / 'mod.json').write_text(json.dumps({'id': 'd1', 'name': 'd1', 'source': 'dat', 'textures': [
        {'index': 0, 'file': 't0.png'}, {'index': 1, 'file': 't1.png'}]}))
    _record(env, {'hud:pause_screen': _entry('d1', 'pause_screen')})
    assert _verify(env, 'hud')['hud:pause_screen'] == {'state': 'installed'}


def test_pause_mod_edited_after_install_trusts_the_record(env):
    _pause_export(env, 'vanilla', VAN_PAUSE)
    _pause_export(env, 'project', [VAN_PAUSE[0], ((255, 0, 0, 255), 'dot', (88, 72))])
    mod_dir = env.vault / 'pause' / 'p1'
    _pic(mod_dir / 'picture.png', (0, 0, 255, 255), 'box', (176, 144))
    (mod_dir / 'mod.json').write_text(json.dumps({'id': 'p1', 'name': 'p1', 'source': 'image'}))
    _record(env, {'hud:pause_screen': _entry('p1', 'pause_screen', when='2000-01-01T00:00:00')})
    assert _verify(env, 'hud')['hud:pause_screen'] == {'state': 'installed', 'unverified': True}


def test_pause_export_failure_leaves_the_slot_out(env):
    _pause_export(env, 'vanilla', VAN_PAUSE)          # no project export
    _record(env, {'hud:pause_screen': _entry('p1', 'pause_screen')})
    assert 'hud:pause_screen' not in _verify(env, 'hud')


# ── CSS doors ──

def _doors_export(env, who, color, shape):
    d = env.tmp / 'exp' / f'doors_{who}'
    if d.exists():
        shutil.rmtree(d)
    for n in (99, 100):
        _pic(d / f'menu_j1_128x200_IA8_{n}.png', color, shape, (128, 200))
    _pic(d / 'menu_j2_64x56_CI8_3.png', (1, 2, 3, 255), 'box', (64, 56))   # not a door
    env.exports[('--css-doors', 'MnSlChr.usd', who)] = d


def test_doors(env):
    _doors_export(env, 'vanilla', (200, 200, 200, 255), 'box')
    _doors_export(env, 'project', (200, 200, 200, 255), 'box')
    assert _verify(env, 'css')['css:doors'] == {'state': 'vanilla', 'stale': False}

    # a door mod: the importer stretches door.png and keeps the file's alpha
    door = env.vault / 'doors' / 'd1' / 'door.png'
    _pic(door, (255, 0, 0, 255), 'dot', (256, 400))
    _doors_export(env, 'project', (255, 0, 0, 255), 'dot')
    _record(env, {'css:doors': _entry('d1', 'css_doors')})
    assert _verify(env, 'css')['css:doors'] == {'state': 'installed'}

    _doors_export(env, 'project', (0, 0, 255, 255), 'box')
    assert _verify(env, 'css')['css:doors'] == {'state': 'custom', 'stale': True}


# ── icon grid ──

JOINT = {c: j for j, c in icons.VANILLA_ICON_JOINT_TO_CHARACTER.items()}


def _fighters(env, icons_by_name):
    fdir = env.project / 'data' / 'fighters'
    fdir.mkdir(parents=True, exist_ok=True)
    for n, (name, (color, shape)) in enumerate(icons_by_name.items()):
        (fdir / f'{n:03d}.json').write_text(json.dumps(
            {'name': name, 'assets': {'cssIcon': f'css\\icon_{n:03d}'}}))
        _pic(env.project / 'assets' / 'css' / f'icon_{n:03d}.png', color, shape, (64, 56))


def _vanilla_icons(env, names):
    d = env.tmp / 'exp' / 'icons_vanilla'
    entries = []
    for name, (color, shape) in names.items():
        fn = f'icon_j{JOINT[name]:03d}.png'
        _pic(d / fn, color, shape, (64, 56))
        entries.append({'filename': fn, 'joint_index': JOINT[name]})
    (d / 'manifest.json').write_text(json.dumps({'format': 'vanilla', 'icons': entries}))
    env.exports[('--css-icons', 'MnSlChr.usd', 'vanilla')] = d


VAN_ICONS = {'Mario': ((255, 0, 0, 255), 'box'), 'Fox': ((0, 0, 255, 255), 'box')}


def test_icon_grid(env):
    _vanilla_icons(env, VAN_ICONS)
    _fighters(env, {**VAN_ICONS, 'Wolf': ((9, 9, 9, 255), 'dot')})   # custom fighter ignored
    assert _verify(env, 'css')['css:icon_grid'] == {'state': 'vanilla', 'stale': False}

    grid = env.vault / 'icon_grid' / 'g1'
    _pic(grid / 'icons' / 'Fox.png', (0, 255, 0, 255), 'dot', (128, 112))
    (grid / 'mod.json').write_text(json.dumps({'id': 'g1', 'name': 'g1', 'icons': [
        {'character': 'Fox', 'icon': 'Fox.png'}]}))
    _fighters(env, {'Mario': VAN_ICONS['Mario'], 'Fox': ((0, 255, 0, 255), 'dot')})
    # MexCLI keeps the picture it was given as the project's icon PNG
    shutil.copy(grid / 'icons' / 'Fox.png', env.project / 'assets' / 'css' / 'icon_001.png')
    _record(env, {'css:icon_grid': _entry('g1', 'css_icon_grid', icons_installed=['Fox'])})
    assert _verify(env, 'css')['css:icon_grid'] == {'state': 'installed'}

    _fighters(env, {'Mario': VAN_ICONS['Mario'], 'Fox': ((255, 255, 0, 255), 'box')})
    assert _verify(env, 'css')['css:icon_grid'] == {'state': 'custom', 'stale': True}


# ── CSS / SSS background ──

def _bg_export(env, key, model, pics):
    d = env.tmp / 'exp' / ('bg_' + str(abs(hash(key))))
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    textures = []
    for i, (color, shape) in enumerate(pics):
        _pic(d / f'bg_t{i}.png', color, shape)
        textures.append({'index': i, 'filename': f'bg_t{i}.png', 'md5': f'{color}{shape}'})
    (d / 'manifest.json').write_text(json.dumps({'model_md5': model, 'textures': textures}))
    env.exports[key] = d


def test_css_background(env):
    _bg_export(env, ('--bg-textures', 'MnSlChr.usd', 'vanilla'), 'vanilla-geo', [])
    _bg_export(env, ('--bg-textures', 'MnSlChr.usd', 'project'), 'vanilla-geo', [])
    assert _verify(env, 'css')['css:background'] == {'state': 'vanilla', 'stale': False}

    bundle = env.vault / 'background' / 'b1' / 'background.dat'
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b'bundle')
    _bg_export(env, ('--bg-textures', 'background.dat', str(bundle)), 'halo-geo',
               [((0, 0, 255, 255), 'dot')])
    _bg_export(env, ('--bg-textures', 'MnSlChr.usd', 'project'), 'halo-geo',
               [((0, 0, 255, 255), 'dot')])
    _record(env, {'css:background': _entry('b1', 'css_background')})
    assert _verify(env, 'css')['css:background'] == {'state': 'installed'}

    # same geometry, another texture: not this mod
    _bg_export(env, ('--bg-textures', 'MnSlChr.usd', 'project'), 'halo-geo',
               [((255, 0, 0, 255), 'box')])
    assert _verify(env, 'css')['css:background'] == {'state': 'custom', 'stale': True}


def test_sss_background_and_old_tools(env):
    _bg_export(env, ('--bg-textures', 'MnSlMap.usd', 'vanilla'), 'sss-geo', [((1, 1, 1, 255), 'box')])
    _bg_export(env, ('--bg-textures', 'MnSlMap.usd', 'project'), 'other-geo', [((1, 1, 1, 255), 'box')])
    assert _verify(env, 'sss')['sss:background'] == {'state': 'custom', 'stale': False}
    # an HSDRawViewer without --bg-textures: no export, the slot is left out
    env.exports.pop(('--bg-textures', 'MnSlMap.usd', 'project'))
    assert _verify(env, 'sss') == {}


def test_no_vanilla_reference_leaves_slots_out(env, monkeypatch):
    monkeypatch.setattr(menu_checks, '_vanilla_ref', lambda *names: None)
    _pause_export(env, 'project', VAN_PAUSE)
    assert _verify(env, 'hud').get('hud:pause_screen') is None


def test_verify_lists_only_known_menus(env):
    body = env.get('/api/mex/menus/installed?verify=nonsense').get_json()
    assert 'verification' not in body
    assert env.get('/api/mex/menus/installed').get_json().get('verification') is None


# ── real tools on copies of the vanilla files ──

def _real(name):
    from core.config import HSDRAW_EXE
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    try:
        ref = ensure_vanilla_ref(name)
    except Exception:
        ref = None
    return ref if ref is not None and HSDRAW_EXE.exists() else None


@pytest.fixture
def real_env(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    (project / 'files').mkdir(parents=True)
    (project / 'project.mexproj').write_text('')
    monkeypatch.setattr(core.state, '_current_project_path', project / 'project.mexproj')
    monkeypatch.setattr(menu_exports, 'cache_root', lambda: tmp_path / 'cache')
    vault = tmp_path / 'vault'
    monkeypatch.setattr(pause, 'PAUSE_PATH', vault / 'pause')
    monkeypatch.setattr(pause_install, 'PAUSE_PATH', vault / 'pause')
    monkeypatch.setattr(doors, 'DOORS_PATH', vault / 'doors')
    monkeypatch.setattr(backgrounds, 'BG_PATH', vault / 'background')
    # the install routes (projects/routes/menus/) read the same vault stores
    monkeypatch.setattr(project_pause, 'PAUSE_PATH', vault / 'pause')
    monkeypatch.setattr(project_doors, 'DOORS_PATH', vault / 'doors')
    monkeypatch.setattr(project_backgrounds, 'BG_PATH', vault / 'background')
    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    c = app.test_client()
    c.project, c.vault, c.tmp = project, vault, tmp_path
    return c


@pytest.mark.skipif(_real('GmPause.usd') is None, reason='vanilla GmPause.usd or HSDRawViewer unavailable')
@pytest.mark.slow
def test_real_pause_picture_install(real_env):
    shutil.copy(str(_real('GmPause.usd')), str(real_env.project / 'files' / 'GmPause.usd'))
    assert _verify(real_env, 'hud')['hud:pause_screen'] == {'state': 'vanilla', 'stale': False}
    mod_dir = real_env.vault / 'pause' / 'p1'
    _pic(mod_dir / 'picture.png', (255, 0, 0, 255), 'dot', (176, 144))
    (mod_dir / 'mod.json').write_text(json.dumps({'id': 'p1', 'name': 'p1', 'source': 'image',
                                                  'created': '2026-09-01T00:00:00'}))
    import os, time
    os.utime(mod_dir / 'mod.json', (time.time() - 3600, time.time() - 3600))
    res = real_env.post('/api/mex/menus/pause/install/p1')
    assert res.status_code == 200, res.get_json()
    assert _verify(real_env, 'hud')['hud:pause_screen'] == {'state': 'installed'}
    shutil.copy(str(_real('GmPause.usd')), str(real_env.project / 'files' / 'GmPause.usd'))
    assert _verify(real_env, 'hud')['hud:pause_screen'] == {'state': 'vanilla', 'stale': True}


@pytest.mark.skipif(_real('MnSlChr.usd') is None, reason='vanilla MnSlChr.usd or HSDRawViewer unavailable')
@pytest.mark.slow
def test_real_doors_and_css_background(real_env, monkeypatch):
    van = _real('MnSlChr.usd')
    target = real_env.project / 'files' / 'MnSlChr.usd'
    shutil.copy(str(van), str(target))
    first = _verify(real_env, 'css')
    assert first['css:doors'] == {'state': 'vanilla', 'stale': False}
    if 'css:background' not in first:
        pytest.skip('this HSDRawViewer build has no --bg-textures')
    assert first['css:background'] == {'state': 'vanilla', 'stale': False}

    door = real_env.vault / 'doors' / 'd1' / 'door.png'
    _pic(door, (255, 0, 0, 255), 'dot', (256, 400))
    (real_env.vault / 'doors' / 'metadata.json').write_text(json.dumps([{'id': 'd1', 'name': 'd1'}]))
    monkeypatch.setattr(doors, 'DOORS_METADATA', real_env.vault / 'doors' / 'metadata.json')
    import os, time
    os.utime(door, (time.time() - 3600, time.time() - 3600))
    res = real_env.post('/api/mex/menus/css/doors/install/d1')
    assert res.status_code == 200, res.get_json()
    assert _verify(real_env, 'css')['css:doors'] == {'state': 'installed'}

    # a background bundle from the vanilla SSS, installed into the CSS
    sss = _real('MnSlMap.usd')
    if sss is None:
        return
    from vault.menus.hsd import _run_hsd_cli
    out = real_env.tmp / 'sssbg'
    assert _run_hsd_cli(['--sss-bg', 'export', str(sss), str(out)]) is not None
    bdir = real_env.vault / 'background' / 'b1'
    bdir.mkdir(parents=True)
    shutil.copy(str(out / 'background.dat'), str(bdir / 'background.dat'))
    (bdir / 'mod.json').write_text(json.dumps({'id': 'b1', 'name': 'b1', 'source': 'sss'}))
    # The install also rewrites the build's code list; this synthetic project has
    # no extracted sys/ for the real MexCLI, so compile with the shared fake.
    from core import build_transaction
    from tests.backend.test_build_commit_transaction import fake_code_compiler
    monkeypatch.setattr(build_transaction, 'CODE_COMPILER', fake_code_compiler)
    res = real_env.post('/api/mex/menus/css/background/install/b1')
    assert res.status_code == 200, res.get_json()
    after = _verify(real_env, 'css')
    assert after['css:background'] == {'state': 'installed'}
    assert after['css:doors'] == {'state': 'installed'}      # untouched by the bg install
