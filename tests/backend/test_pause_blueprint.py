from tests.paths import BACKEND
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.routes.menus import menus_bp
from vault.routes.menus import pause as pause_module
from vault.menus import pause as pause_engine
from vault.menus import pause_install
from projects.routes.menus import pause as project_pause
from vault.menus.hsd import _run_hsd_cli
from core.config import HSDRAW_EXE

REPO_ROOT = BACKEND_DIR.parent
VANILLA_GMPAUSE = REPO_ROOT / 'storage' / 'test-base' / 'files' / 'GmPause.usd'

needs_fixtures = pytest.mark.skipif(
    not VANILLA_GMPAUSE.exists() or not HSDRAW_EXE.exists(),
    reason='vanilla GmPause.usd fixture or HSDRawViewer build not available',
)


def _make_picture_bytes(size=(64, 64), color=(255, 40, 40, 255)):
    from PIL import Image
    img = Image.new('RGBA', size, color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


@pytest.fixture
def client(tmp_path, monkeypatch, open_project):
    # Keep mod storage out of the real vault
    pause_storage = tmp_path / 'pause_storage'
    pause_storage.mkdir()
    monkeypatch.setattr(pause_module, 'PAUSE_PATH', pause_storage)
    monkeypatch.setattr(pause_engine, 'PAUSE_PATH', pause_storage)
    monkeypatch.setattr(pause_engine, 'PAUSE_METADATA', pause_storage / 'metadata.json')
    monkeypatch.setattr(pause_install, 'PAUSE_PATH', pause_storage)
    monkeypatch.setattr(project_pause, 'PAUSE_PATH', pause_storage)   # the install route

    # Throwaway project with a vanilla GmPause.usd
    project_dir = tmp_path / 'project'
    files_dir = project_dir / 'files'
    files_dir.mkdir(parents=True)
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    if VANILLA_GMPAUSE.exists():
        shutil.copy(str(VANILLA_GMPAUSE), str(files_dir / 'GmPause.usd'))
    open_project(project_dir / 'project.mexproj')

    # The vanilla textures the editor seeds from are derived from the user's
    # own GmPause (nothing ships); derive them here, away from the real set.
    from shared.vanilla_extract import menu_refs
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    if VANILLA_GMPAUSE.exists() and HSDRAW_EXE.exists():
        assert menu_refs._derive_pause(files_dir, menu_refs.pause_dir()) == 11

    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    with app.test_client() as c:
        c.project_files_dir = files_dir
        yield c


@needs_fixtures
def test_import_zip_with_multiple_gmpause_variants(client):
    zip_buf = io.BytesIO()
    gmpause_bytes = VANILLA_GMPAUSE.read_bytes()
    with zipfile.ZipFile(zip_buf, 'w') as zf:
        zf.writestr('Mod/GmPause(white).dat', gmpause_bytes)
        zf.writestr('Mod/GmPause(black).dat', gmpause_bytes)
        zf.writestr('screenshot_0.png', _make_picture_bytes().read())
    zip_buf.seek(0)

    res = client.post('/api/mex/menus/pause/import', data={
        'file': (zip_buf, 'Cool Pause Mod.zip'),
        'name': 'Cool Pause Mod',
    }, content_type='multipart/form-data')

    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['imported_count'] == 2
    names = sorted(m['name'] for m in data['mods'])
    assert names == ['Cool Pause Mod (black)', 'Cool Pause Mod (white)']
    for mod in data['mods']:
        assert mod['source'] == 'dat'
        assert len(mod['textures']) == 11
        assert mod['screenshot'] == 'screenshot.png'

    # Catalog + previews
    res = client.get('/api/mex/menus/pause/list')
    mods = res.get_json()['mods']
    assert len(mods) == 2
    img = client.get(mods[0]['imageUrl'])
    assert img.status_code == 200

    # Install reproduces the mod's textures in the project file
    res = client.post(f"/api/mex/menus/pause/install/{mods[0]['id']}")
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    # Delete removes files and catalog entry
    res = client.post(f"/api/mex/menus/pause/delete/{mods[0]['id']}")
    assert res.get_json()['success'] is True
    assert len(client.get('/api/mex/menus/pause/list').get_json()['mods']) == 1


@needs_fixtures
def test_import_picture_and_install_replaces_main_texture(client, tmp_path):
    res = client.post('/api/mex/menus/pause/import', data={
        'file': (_make_picture_bytes(), 'my pic.png'),
        'name': 'My Picture',
    }, content_type='multipart/form-data')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    mod = data['mods'][0]
    assert mod['source'] == 'image'

    res = client.post(f"/api/mex/menus/pause/install/{mod['id']}")
    assert res.status_code == 200, res.get_json()
    assert res.get_json()['success'] is True

    # Re-export the project's GmPause and confirm the two 88x72 main
    # textures are now color (RGB5A3) instead of grayscale IA4.
    dump_dir = tmp_path / 'dump'
    result = _run_hsd_cli(['--pause-screen', 'export',
                           str(client.project_files_dir / 'GmPause.usd'), str(dump_dir)])
    assert result is not None
    manifest = json.loads((dump_dir / 'manifest.json').read_text())
    main = [t for t in manifest['textures'] if t['width'] == 88 and t['height'] == 72]
    assert len(main) == 2
    assert all(t['format'] == 'RGB5A3' for t in main)


@needs_fixtures
def test_texture_editor_replace_and_revert(client, tmp_path):
    # Picture mod → texture list seeds from vanilla with the picture in the
    # two 88x72 main slots.
    res = client.post('/api/mex/menus/pause/import', data={
        'file': (_make_picture_bytes(), 'pic.png'),
        'name': 'Editable',
    }, content_type='multipart/form-data')
    mod_id = res.get_json()['mods'][0]['id']

    res = client.get(f'/api/mex/menus/pause/{mod_id}/textures')
    assert res.status_code == 200
    textures = res.get_json()['textures']
    assert len(textures) == 11
    replaced = {t['index'] for t in textures if t['replaced']}
    main = {t['index'] for t in textures if t['width'] == 88 and t['height'] == 72}
    assert replaced == main and len(main) == 2

    # Texture image endpoint serves a file
    assert client.get(f'/api/mex/menus/pause/texture/{mod_id}/0').status_code == 200

    # Replace a hint slot (t8, 124x36) with a color image
    res = client.post(f'/api/mex/menus/pause/{mod_id}/replace_texture', data={
        'index': '8',
        'file': (_make_picture_bytes(color=(0, 200, 80, 255)), 'hint.png'),
    }, content_type='multipart/form-data')
    assert res.get_json()['success'] is True
    textures = client.get(f'/api/mex/menus/pause/{mod_id}/textures').get_json()['textures']
    assert next(t for t in textures if t['index'] == 8)['replaced'] is True

    # Install: replaced slots (mains + t8) become RGB5A3, untouched stay vanilla format
    res = client.post(f'/api/mex/menus/pause/install/{mod_id}')
    assert res.get_json()['success'] is True, res.get_json()
    dump_dir = tmp_path / 'editor_dump'
    assert _run_hsd_cli(['--pause-screen', 'export',
                         str(client.project_files_dir / 'GmPause.usd'), str(dump_dir)]) is not None
    manifest = {t['index']: t for t in json.loads((dump_dir / 'manifest.json').read_text())['textures']}
    assert manifest[8]['format'] == 'RGB5A3'
    assert all(manifest[i]['format'] == 'RGB5A3' for i in main)
    assert manifest[6]['format'] == 'I4'   # untouched "Pause" text keeps vanilla format

    # Revert t8 → back to the vanilla texture bytes
    res = client.post(f'/api/mex/menus/pause/{mod_id}/revert_texture', json={'index': 8})
    assert res.get_json()['success'] is True
    textures = client.get(f'/api/mex/menus/pause/{mod_id}/textures').get_json()['textures']
    assert next(t for t in textures if t['index'] == 8)['replaced'] is False
    from vault.routes.menus.pause import VANILLA_TEX_DIR, PAUSE_PATH as live_pause_path
    stored = (live_pause_path / mod_id / 'textures' / 't8.png').read_bytes()
    assert stored == (VANILLA_TEX_DIR() / 't8.png').read_bytes()


@needs_fixtures
def test_create_blank_pause_mod(client):
    res = client.post('/api/mex/menus/pause/create', json={'name': 'My Custom Pause'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    mod = data['mod']
    assert mod['name'] == 'My Custom Pause'
    assert mod['source'] == 'custom'
    # Seeded with the full vanilla set, nothing marked replaced
    assert len(mod['textures']) == 11
    assert not any(t.get('replaced') for t in mod['textures'])

    # It's in the catalog and installable as-is (vanilla round trip)
    mods = client.get('/api/mex/menus/pause/list').get_json()['mods']
    assert any(m['id'] == mod['id'] for m in mods)
    res = client.post(f"/api/mex/menus/pause/install/{mod['id']}")
    assert res.get_json()['success'] is True


def test_looks_like_pause_zip(tmp_path):
    good = tmp_path / 'good.zip'
    with zipfile.ZipFile(good, 'w') as zf:
        zf.writestr('foo/GmPause.usd', b'x')
    assert pause_engine.looks_like_pause_zip(good) is True

    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as zf:
        zf.writestr('foo/MnSlChr.dat', b'x')
    assert pause_engine.looks_like_pause_zip(bad) is False


def test_install_survives_a_scanner_holding_the_temp_output(client, tmp_path, monkeypatch):
    """Defender can still hold the GmPause.usd HSDRawViewer just wrote into the
    install's temp dir when that dir is deleted. The project file is already
    replaced by then, so the install must succeed and be recorded -- not 500
    and leave the Menus tab unaware of a changed GmPause.usd."""
    import errno
    import os
    from vault.menus import installed as menus_installed

    gmpause = client.project_files_dir / 'GmPause.usd'
    gmpause.write_bytes(b'VANILLA')
    exe = tmp_path / 'HSDRawViewer.exe'
    exe.write_bytes(b'')
    monkeypatch.setattr(pause_install, 'HSDRAW_EXE', exe)
    monkeypatch.setattr(project_pause, 'load_mod_json', lambda base, mod_id: {'id': mod_id, 'name': 'Red'})
    monkeypatch.setattr(pause_install, 'load_mod_json', lambda base, mod_id: {'id': mod_id, 'name': 'Red'})
    monkeypatch.setattr(pause_install, 'build_replacement_spec', lambda mod, mod_dir: [])
    outputs = []

    def fake_hsd(args, timeout=120):
        output = Path(args[-1])
        output.write_bytes(b'MODDED')
        outputs.append(output)
        return 'ok'
    monkeypatch.setattr(pause_install, '_run_hsd_cli', fake_hsd)
    recorded = []
    monkeypatch.setattr(menus_installed, 'record_installed_menu_mod',
                        lambda slot, kind, mod: recorded.append((slot, kind, mod['id'])))

    real_unlink = os.unlink
    scanning = {'on': True}

    def unlink_while_scanned(path, *args, **kwargs):
        if scanning['on'] and Path(path).name == 'GmPause.usd' and outputs:
            raise PermissionError(errno.EACCES, 'The process cannot access the file because '
                                  'it is being used by another process', str(path))
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(os, 'unlink', unlink_while_scanned)

    try:
        res = client.post('/api/mex/menus/pause/install/m1')
    finally:
        scanning['on'] = False
        if outputs:
            shutil.rmtree(outputs[0].parent, ignore_errors=True)

    assert res.status_code == 200, res.get_json()
    assert res.get_json()['success'] is True
    assert gmpause.read_bytes() == b'MODDED'
    assert recorded == [('hud:pause_screen', 'pause_screen', 'm1')]
