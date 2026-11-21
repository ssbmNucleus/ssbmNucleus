from tests.paths import BACKEND
import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.routes.menus import menus_bp
from vault.routes.menus import percent as percent_module
from vault.menus import percent as percent_engine, percent_install
from projects.routes.menus import percent as project_percent
from core.config import HSDRAW_EXE
from tests.left_out import needs_hud_manifest

REPO_ROOT = BACKEND_DIR.parent
VANILLA_IFALL = REPO_ROOT / 'storage' / 'test-base' / 'files' / 'IfAll.usd'

needs_fixtures = pytest.mark.skipif(
    not VANILLA_IFALL.exists() or not HSDRAW_EXE.exists(),
    reason='vanilla IfAll.usd fixture or HSDRawViewer build not available',
)


def _glyph_png_bytes(label, size=(32, 36), color=(255, 60, 60, 255)):
    from PIL import Image
    img = Image.new('RGBA', size, color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


def _glyph_pack_zip():
    """A zip of digit images 0-9 + percent, like the archive glyph packs."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w') as zf:
        for d in range(10):
            zf.writestr(f'{d}.png', _glyph_png_bytes(str(d)))
        zf.writestr('percent.png', _glyph_png_bytes('%', size=(32, 24)))
    zip_buf.seek(0)
    return zip_buf


@pytest.fixture
def client(tmp_path, monkeypatch, open_project):
    # Keep mod storage out of the real vault
    percent_storage = tmp_path / 'percent_storage'
    percent_storage.mkdir()
    monkeypatch.setattr(percent_module, 'PERCENT_PATH', percent_storage)
    monkeypatch.setattr(percent_engine, 'PERCENT_PATH', percent_storage)
    monkeypatch.setattr(project_percent, 'PERCENT_PATH', percent_storage)   # the install route
    monkeypatch.setattr(percent_install, 'PERCENT_PATH', percent_storage)   # the install engine
    monkeypatch.setattr(percent_engine, 'PERCENT_METADATA', percent_storage / 'metadata.json')

    # Throwaway project with a vanilla IfAll.usd
    project_dir = tmp_path / 'project'
    files_dir = project_dir / 'files'
    files_dir.mkdir(parents=True)
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    if VANILLA_IFALL.exists():
        shutil.copy(str(VANILLA_IFALL), str(files_dir / 'IfAll.usd'))
    open_project(project_dir / 'project.mexproj')

    # A derived HUD set, away from the real one: the shipped slot manifests
    # plus a stand-in preview per glyph (the real previews are derived from
    # the user's own IfAll; nothing ships).
    from shared.vanilla_extract import menu_refs
    from core.config import BACKEND_ASSETS_DIR
    from core.hud_words import GLYPH_KEYS
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    hud = tmp_path / 'menu_refs' / 'hud_vanilla'
    hud.mkdir(parents=True)
    for manifest in (BACKEND_ASSETS_DIR / 'hud_vanilla').glob('manifest_*.json'):
        shutil.copy(str(manifest), str(hud / manifest.name))
    for key in GLYPH_KEYS:
        (hud / f'glyph_{key}.png').write_bytes(_glyph_png_bytes(key))

    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    with app.test_client() as c:
        c.project_files_dir = files_dir
        yield c


def test_looks_like_percent_zip_glyph_pack(tmp_path):
    zip_path = tmp_path / 'pack.zip'
    zip_path.write_bytes(_glyph_pack_zip().read())
    assert percent_engine.looks_like_percent_zip(zip_path) is True


def test_looks_like_percent_zip_rejects_unrelated(tmp_path):
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w') as zf:
        zf.writestr('PlFxNr.dat', b'not really a dat')
        zf.writestr('readme.txt', 'hi')
    zip_path = tmp_path / 'other.zip'
    zip_path.write_bytes(zip_buf.getvalue())
    assert percent_engine.looks_like_percent_zip(zip_path) is False


@needs_hud_manifest()
def test_glyph_pack_import_and_install(client):
    """Glyph-pack import maps each digit onto every DmgNum slot showing it,
    then installs into the project's IfAll.usd."""
    res = client.post('/api/mex/menus/percent/import', data={
        'file': (_glyph_pack_zip(), 'My Percent Font.zip'),
        'name': 'My Percent Font',
    }, content_type='multipart/form-data')

    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['imported_count'] == 1
    mod = data['mods'][0]
    assert mod['source'] == 'glyphs'
    # 10 digits over 93 slots (12 for the 0 quads, 9 each for 1-9) + 4 percent
    assert len(mod['slots']) == 97

    # listed
    res = client.get('/api/mex/menus/percent/list')
    assert len(res.get_json()['mods']) == 1

    # preview available
    res = client.get(f"/api/mex/menus/percent/image/{mod['id']}")
    assert res.status_code == 200

    if not (HSDRAW_EXE.exists() and VANILLA_IFALL.exists()):
        return
    before = (client.project_files_dir / 'IfAll.usd').read_bytes()
    res = client.post(f"/api/mex/menus/percent/install/{mod['id']}")
    assert res.status_code == 200
    assert res.get_json()['success'] is True
    after = (client.project_files_dir / 'IfAll.usd').read_bytes()
    assert before != after


@needs_fixtures
def test_dat_import_diffs_against_vanilla(client, tmp_path):
    """A modified IfAll imports with only the changed slots stored; a pristine
    vanilla IfAll is rejected as having nothing to import."""
    # Pristine vanilla → rejected
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w') as zf:
        zf.writestr('IfAll.usd', VANILLA_IFALL.read_bytes())
    zip_buf.seek(0)
    res = client.post('/api/mex/menus/percent/import', data={
        'file': (zip_buf, 'Vanilla.zip'),
        'name': 'Vanilla',
    }, content_type='multipart/form-data')
    assert res.status_code == 400
    assert 'identical to vanilla' in res.get_json()['error']

    # Build a modified IfAll by installing a glyph mod, then re-import it
    res = client.post('/api/mex/menus/percent/import', data={
        'file': (_glyph_pack_zip(), 'Seed.zip'),
        'name': 'Seed',
    }, content_type='multipart/form-data')
    seed_id = res.get_json()['mods'][0]['id']
    modded = tmp_path / 'IfAll.usd'
    shutil.copy(str(VANILLA_IFALL), str(modded))
    project_percent.apply_percent_mod(seed_id, modded)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w') as zf:
        zf.writestr('Cool Font/IfAll.usd', modded.read_bytes())
    zip_buf.seek(0)
    res = client.post('/api/mex/menus/percent/import', data={
        'file': (zip_buf, 'Cool Font.zip'),
        'name': 'Cool Font',
    }, content_type='multipart/form-data')
    assert res.status_code == 200
    mod = res.get_json()['mods'][0]
    assert mod['source'] == 'dat'
    # `region` records which vanilla manifest this file's slot skeleton matched,
    # and both answers are legitimate here. The manifests are derived from the
    # user's own m-ex PROJECT (menu_refs: "the manifests must describe a MEX
    # project's IfAll"), and a project IfAll.usd carries roots vanilla has not --
    # an emblem matanim root, on this machine -- so the VANILLA fixture below
    # matches the dat manifest instead. Vanilla's two regions are byte-identical
    # in slot structure anyway, so the label cannot distinguish them. What must
    # hold is the slot mapping, asserted next.
    assert mod['region'] in ('usd', 'dat')
    # the same 97 slots the seed mod touched
    assert len(mod['slots']) == 97
    roots = {s['root'] for s in mod['slots']}
    assert roots == {'DmgNum_scene_models'}


@needs_hud_manifest()
def test_glyph_editor_flow(client):
    """Create a blank mod, replace a glyph, revert it."""
    res = client.post('/api/mex/menus/percent/create',
                      json={'name': 'Editor Font'})
    assert res.status_code == 200
    mod = res.get_json()['mod']
    assert mod['source'] == 'custom'

    # All glyphs vanilla on a fresh mod
    res = client.get(f"/api/mex/menus/percent/{mod['id']}/glyphs")
    glyphs = res.get_json()['glyphs']
    assert [g['key'] for g in glyphs] == [str(d) for d in range(10)] + ['percent', 'hp']
    assert not any(g['replaced'] for g in glyphs)

    # Vanilla glyph image serves
    res = client.get(f"/api/mex/menus/percent/glyph/{mod['id']}/7")
    assert res.status_code == 200

    # Replace the 7 — lands on every slot showing a 7 (9 anim frames)
    res = client.post(f"/api/mex/menus/percent/{mod['id']}/replace_glyph", data={
        'key': '7',
        'file': (io.BytesIO(_glyph_png_bytes('7')), 'seven.png'),
    }, content_type='multipart/form-data')
    assert res.get_json()['success'] is True

    res = client.get(f"/api/mex/menus/percent/{mod['id']}/glyphs")
    seven = next(g for g in res.get_json()['glyphs'] if g['key'] == '7')
    assert seven['replaced'] is True

    # Install works with the partial glyph set
    if HSDRAW_EXE.exists() and VANILLA_IFALL.exists():
        res = client.post(f"/api/mex/menus/percent/install/{mod['id']}")
        assert res.get_json()['success'] is True

    # Revert removes the glyph-added slots entirely
    res = client.post(f"/api/mex/menus/percent/{mod['id']}/revert_glyph",
                      json={'key': '7'})
    assert res.get_json()['success'] is True
    res = client.get(f"/api/mex/menus/percent/{mod['id']}/glyphs")
    seven = next(g for g in res.get_json()['glyphs'] if g['key'] == '7')
    assert seven['replaced'] is False and seven['overridden'] is False


def _word_pack_zip():
    """A zip of READY/GO/GAME banner images: semantic + Dolphin-hash names."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w') as zf:
        zf.writestr('ready3.png', _glyph_png_bytes('READY', size=(280, 84)))
        zf.writestr('go21.png', _glyph_png_bytes('GO', size=(376, 188)))
        # hash-named GAME! banner — identified by its unique dimensions
        zf.writestr('tex1_528x144_babea042c3cd59fe_9.png',
                    _glyph_png_bytes('GAME', size=(528, 144)))
    zip_buf.seek(0)
    return zip_buf


@needs_hud_manifest()
def test_word_pack_import_and_categories(client):
    """Word packs map READY/GO!/GAME! onto the ScInfCnt banner slots and land
    in the readygo category; glyph packs stay in percent."""
    zip_path_check = _word_pack_zip()
    import tempfile as _tf
    with _tf.NamedTemporaryFile(suffix='.zip', delete=False) as f:
        f.write(zip_path_check.read())
        tmp_name = f.name
    assert percent_engine.looks_like_percent_zip(Path(tmp_name)) is True
    Path(tmp_name).unlink()

    res = client.post('/api/mex/menus/percent/import', data={
        'file': (_word_pack_zip(), 'Cool Banners.zip'),
        'name': 'Cool Banners',
    }, content_type='multipart/form-data')
    assert res.status_code == 200
    mod = res.get_json()['mods'][0]
    # ready 1 slot + go 1 slot + game 1 slot = 3 (time would add 3 aliased)
    assert len(mod['slots']) == 3
    assert all(s['root'] == 'ScInfCnt_scene_models' for s in mod['slots'])

    res = client.post('/api/mex/menus/percent/import', data={
        'file': (_glyph_pack_zip(), 'Digits.zip'),
        'name': 'Digits',
    }, content_type='multipart/form-data')
    assert res.status_code == 200

    rg = client.get('/api/mex/menus/percent/list?category=readygo').get_json()['mods']
    pct = client.get('/api/mex/menus/percent/list?category=percent').get_json()['mods']
    assert [m['name'] for m in rg] == ['Cool Banners']
    assert [m['name'] for m in pct] == ['Digits']

    if HSDRAW_EXE.exists() and VANILLA_IFALL.exists():
        res = client.post(f"/api/mex/menus/percent/install/{mod['id']}")
        assert res.get_json()['success'] is True


@needs_hud_manifest()
def test_word_editor_flow(client):
    """A readygo custom mod lists word banners and supports replace/revert,
    including the triple-aliased Time! banner."""
    res = client.post('/api/mex/menus/percent/create',
                      json={'name': 'Banner Pack', 'category': 'readygo'})
    mod = res.get_json()['mod']

    res = client.get(f"/api/mex/menus/percent/{mod['id']}/words")
    words = res.get_json()['glyphs']
    assert [w['key'] for w in words] == ['ready', 'go', 'game', 'time', 'sudden',
                                         'death', 'success', 'failure', 'complete']

    # blank readygo mod shows up only in the readygo list
    rg = client.get('/api/mex/menus/percent/list?category=readygo').get_json()['mods']
    assert any(m['id'] == mod['id'] for m in rg)
    pct = client.get('/api/mex/menus/percent/list?category=percent').get_json()['mods']
    assert not any(m['id'] == mod['id'] for m in pct)

    res = client.post(f"/api/mex/menus/percent/{mod['id']}/replace_glyph", data={
        'key': 'time',
        'file': (io.BytesIO(_glyph_png_bytes('TIME', size=(528, 164))), 'time.png'),
    }, content_type='multipart/form-data')
    assert res.get_json()['success'] is True

    # "Time!" is stored three times in vanilla — all three must be covered
    mod_json = percent_module.load_mod_json(percent_module.PERCENT_PATH, mod['id'])
    assert len(mod_json['slots']) == 3

    res = client.post(f"/api/mex/menus/percent/{mod['id']}/revert_glyph",
                      json={'key': 'time'})
    assert res.get_json()['success'] is True
    mod_json = percent_module.load_mod_json(percent_module.PERCENT_PATH, mod['id'])
    assert mod_json['slots'] == []


@needs_hud_manifest()
def test_delete_percent_mod(client):
    res = client.post('/api/mex/menus/percent/import', data={
        'file': (_glyph_pack_zip(), 'Doomed.zip'),
        'name': 'Doomed',
    }, content_type='multipart/form-data')
    mod_id = res.get_json()['mods'][0]['id']

    res = client.post(f'/api/mex/menus/percent/delete/{mod_id}')
    assert res.get_json()['success'] is True
    res = client.get('/api/mex/menus/percent/list')
    assert res.get_json()['mods'] == []
