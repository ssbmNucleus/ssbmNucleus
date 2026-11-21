"""Reading "Currently in MEX" from the game files, and the HUD vanilla reset.

The file checks decode a slot's picture and compare it with vanilla and with
the recorded mod, tolerant of re-encoding (menu_pixels). Installing a
Percent Font / Ready-Go mod first puts that category back to vanilla, and
"Restore vanilla" does just that; both go through --hud-textures import.
"""
import json
import shutil
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image, ImageDraw

import core.state
from vault.routes.menus import menus_bp
from vault.routes.menus import percent
from vault.menus import hud_verify, menu_exports, menu_pixels, percent_install
from vault.menus import percent as percent_engine
from projects.routes.menus import percent as project_percent
from core.state import clear_project_path
from tests.left_out import needs_hud_manifest

_REAL_APPLY = project_percent.apply_percent_mod


# ── shared picture comparison ──

def _glyph(tmp_path, name, text='7', color=(255, 255, 255, 255), size=(32, 36), offset=(6, 2),
           width=3):
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.line([(offset[0], offset[1]), (offset[0] + 18, offset[1]),
            (offset[0] + 8, offset[1] + 30)], fill=color, width=width)
    if text == '1':
        im = Image.new('RGBA', size, (0, 0, 0, 0))
        ImageDraw.Draw(im).line([(16, 2), (16, 32)], fill=color, width=width)
    p = tmp_path / f'{name}.png'
    im.save(p)
    return p


def _quantize(src, dst, bits_color=4, bits_alpha=3):
    """What RGB5A3's translucent mode does to a picture (4-bit color,
    3-bit alpha)."""
    import numpy as np
    x = np.asarray(Image.open(src).convert('RGBA'), dtype=np.float64)

    def q(v, bits):
        levels = (1 << bits) - 1
        return np.round(np.round(v * levels / 255) * 255 / levels)
    out = np.dstack([q(x[..., c], bits_color) for c in range(3)] + [q(x[..., 3], bits_alpha)])
    Image.fromarray(out.astype(np.uint8), 'RGBA').save(dst)
    return dst


def test_same_picture_absorbs_reencoding(tmp_path):
    a = _glyph(tmp_path, 'a')
    b = _quantize(a, tmp_path / 'b.png')
    assert menu_pixels.same_picture(a, b) is True


def test_same_picture_rejects_another_glyph_a_move_and_a_recolor(tmp_path):
    a = _glyph(tmp_path, 'a')
    assert menu_pixels.same_picture(a, _glyph(tmp_path, 'one', text='1')) is False
    assert menu_pixels.same_picture(a, _glyph(tmp_path, 'moved', offset=(8, 2))) is False
    assert menu_pixels.same_picture(a, _glyph(tmp_path, 'red', color=(255, 60, 60, 255))) is False
    assert menu_pixels.same_picture(a, _glyph(tmp_path, 'bold', width=6)) is False


def test_transparent_color_does_not_count(tmp_path):
    a = Image.new('RGBA', (8, 8), (255, 0, 0, 0))
    b = Image.new('RGBA', (8, 8), (0, 0, 255, 0))
    assert menu_pixels.same_picture(a, b) is True


def test_source_pictures_are_resized_to_the_slot(tmp_path):
    # the importer resized a 2x source down to the slot, then encoded it
    big = Image.open(_glyph(tmp_path, 'big', size=(64, 72), offset=(12, 4), width=6))
    written = tmp_path / 'written.png'
    big.resize((32, 36), Image.BICUBIC).save(written)
    in_file = _quantize(written, tmp_path / 'in_file.png')
    assert menu_pixels.pixel_diff(in_file, big)['resized'] is True
    assert menu_pixels.same_picture(in_file, big, 'source') is True
    other = Image.open(_glyph(tmp_path, 'other', text='1', size=(64, 72), width=6))
    assert menu_pixels.same_picture(in_file, other, 'source') is False


def test_unreadable_pictures_compare_as_unknown(tmp_path):
    bad = tmp_path / 'bad.png'
    bad.write_bytes(b'not a png')
    assert menu_pixels.same_picture(bad, _glyph(tmp_path, 'a')) is None


# ── cached exports ──

def test_export_is_cached_by_file_size_and_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_exports, 'cache_root', lambda: tmp_path / 'cache')
    calls = []

    def fake_cli(args, timeout=120):
        calls.append(args)
        out = Path(args[3])
        out.mkdir(parents=True, exist_ok=True)
        (out / 'manifest.json').write_text('{}', encoding='utf-8')
        return object()
    monkeypatch.setattr(menu_exports, '_run_hsd_cli', fake_cli)
    f = tmp_path / 'IfAll.usd'
    f.write_bytes(b'one')
    first = menu_exports.cached_export('--hud-textures', f)
    assert (first / 'manifest.json').is_file()
    assert menu_exports.cached_export('--hud-textures', f) == first
    assert len(calls) == 1
    f.write_bytes(b'changed!')
    second = menu_exports.cached_export('--hud-textures', f)
    assert len(calls) == 2 and second != first
    assert not first.exists()           # the old version's copy is dropped


def test_export_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_exports, 'cache_root', lambda: tmp_path / 'cache')
    monkeypatch.setattr(menu_exports, '_run_hsd_cli', lambda args, timeout=120: None)
    f = tmp_path / 'IfAll.usd'
    f.write_bytes(b'x')
    assert menu_exports.cached_export('--hud-textures', f) is None
    assert menu_exports.cached_export('--hud-textures', tmp_path / 'missing.usd') is None


# ── HUD check with decoded slots (faked export) ──

DIGIT = 'DmgNum_scene_models|anim|0'
EMBLEM = 'DmgMrk_scene_models|mat|0'
READY = 'ScInfCnt_scene_models|mat|13'
GO = 'ScInfCnt_scene_models|mat|14'
STOCK = 'Stc_scemdls|anim|0'
DIGIT_SLOT = {'root': 'DmgNum_scene_models', 'kind': 'anim', 'ordinal': 0,
              'width': 32, 'height': 36, 'format': 'IA4', 'file': 's0.png', 'replaced': True}
READY_SLOT = {'root': 'ScInfCnt_scene_models', 'kind': 'mat', 'ordinal': 13,
              'width': 32, 'height': 36, 'format': 'CI8', 'file': 's1.png', 'replaced': True}


@pytest.fixture
def env(tmp_path, monkeypatch):
    storage = tmp_path / 'percent'
    storage.mkdir()
    monkeypatch.setattr(percent, 'PERCENT_PATH', storage)
    monkeypatch.setattr(percent_engine, 'PERCENT_PATH', storage)
    monkeypatch.setattr(project_percent, 'PERCENT_PATH', storage)   # installs read the same store
    monkeypatch.setattr(percent_install, 'PERCENT_PATH', storage)
    monkeypatch.setattr(percent_engine, 'PERCENT_METADATA', storage / 'metadata.json')
    monkeypatch.setattr(menu_exports, 'cache_root', lambda: tmp_path / 'cache')
    project_dir = tmp_path / 'project'
    (project_dir / 'files').mkdir(parents=True)
    (project_dir / 'files' / 'IfAll.usd').write_bytes(b'stub')
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    monkeypatch.setattr(core.state, '_current_project_path', project_dir / 'project.mexproj')
    app = Flask(__name__)
    app.register_blueprint(menus_bp)
    client = app.test_client()
    client.tmp = tmp_path
    client.project_dir = project_dir
    client.storage = storage
    return client


@pytest.fixture
def hud(env, monkeypatch):
    """Vanilla pictures per slot; env.file holds what the project file shows."""
    pics = env.tmp / 'pics'
    pics.mkdir()
    env.pics = {
        'digit': _glyph(pics, 'v_digit'),
        'emblem': _glyph(pics, 'v_emblem', text='1'),
        'ready': _glyph(pics, 'v_ready', color=(200, 200, 40, 255)),
        'go': _glyph(pics, 'v_go', text='1', color=(200, 200, 40, 255)),
        'stock': _glyph(pics, 'v_stock', color=(0, 255, 0, 255)),
        'red_digit': _glyph(pics, 'red_digit', color=(255, 40, 40, 255)),
        'red_ready': _glyph(pics, 'red_ready', color=(255, 40, 40, 255), text='1'),
        'other': _glyph(pics, 'other', offset=(2, 4), width=5),
    }
    env.pics['q_digit'] = _quantize(env.pics['digit'], pics / 'q_digit.png')
    env.pics['q_red_digit'] = _quantize(env.pics['red_digit'], pics / 'q_red_digit.png')
    vanilla = {DIGIT: 'digit', EMBLEM: 'emblem', READY: 'ready', GO: 'go', STOCK: 'stock'}
    env.vanilla = {k: {'md5': f'v-{v}', 'file': env.pics[v]} for k, v in vanilla.items()}
    env.file = {k: dict(v) for k, v in env.vanilla.items()}
    env.exports = 0

    def fake_load(path):
        env.exports += 1
        return None if env.file is None else {k: dict(v) for k, v in env.file.items()}
    monkeypatch.setattr(hud_verify, 'load_slots', fake_load)
    monkeypatch.setattr(hud_verify, 'vanilla_slots', lambda: dict(env.vanilla))
    return env


def _set(env, key, pic, md5=None):
    env.file[key] = {'md5': md5 or f'f-{pic}', 'file': env.pics[pic]}


def _mod(env, mod_id, name, slots, pics):
    (env.storage / mod_id / 'textures').mkdir(parents=True)
    for s, pic in zip(slots, pics):
        shutil.copy(env.pics[pic], env.storage / mod_id / 'textures' / s['file'])
    mod = {'id': mod_id, 'name': name, 'source': 'glyphs', 'region': 'usd', 'slots': slots,
           'created': '2026-09-01T00:00:00'}
    (env.storage / mod_id / 'mod.json').write_text(json.dumps(mod), encoding='utf-8')
    return mod


def _record(env, installed):
    (env.project_dir / 'nucleus_menus.json').write_text(json.dumps({'installed': installed}),
                                                        encoding='utf-8')


def _entry(mod_id, name, kind, cats, when='2099-01-01T00:00:00'):
    return {'id': mod_id, 'name': name, 'kind': kind, 'categories': cats, 'installed': when}


def _verify(env):
    res = env.get('/api/mex/menus/installed?verify=hud')
    assert res.status_code == 200
    body = res.get_json()
    return body['installed'], body['verification']


def test_vanilla_project_reads_vanilla(hud):
    _installed, v = _verify(hud)
    assert v == {'hud:percent_font': {'state': 'vanilla', 'stale': False},
                 'hud:ready_go': {'state': 'vanilla', 'stale': False}}


def test_reencoded_vanilla_still_reads_vanilla(hud):
    # a restore re-encodes the vanilla picture: different bytes, same picture
    _set(hud, DIGIT, 'q_digit')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'vanilla', 'stale': False}


def test_premodded_project_reads_custom(hud):
    _set(hud, DIGIT, 'other')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'custom', 'stale': False}
    assert v['hud:ready_go']['state'] == 'vanilla'


def test_non_typeface_slots_are_ignored(hud):
    _set(hud, STOCK, 'other')      # m-ex stock icons live in IfAll too
    _installed, v = _verify(hud)
    assert v['hud:percent_font']['state'] == 'vanilla'


def test_recorded_mod_is_recognized_from_its_pictures(hud):
    _mod(hud, 'rg1', 'Red READY', [READY_SLOT], ['red_ready'])
    _record(hud, {'hud:ready_go': _entry('rg1', 'Red READY', 'ready_go', ['readygo'])})
    _set(hud, READY, 'red_ready')
    _installed, v = _verify(hud)
    assert v['hud:ready_go'] == {'state': 'installed'}


def test_recorded_mod_with_leftovers_of_another_mod_does_not_match(hud):
    _mod(hud, 'rg1', 'Red READY', [READY_SLOT], ['red_ready'])
    _record(hud, {'hud:ready_go': _entry('rg1', 'Red READY', 'ready_go', ['readygo'])})
    _set(hud, READY, 'red_ready')
    _set(hud, GO, 'other')          # an older pack's GO! is still there
    _installed, v = _verify(hud)
    assert v['hud:ready_go'] == {'state': 'custom', 'stale': True}


def test_a_different_mod_is_never_taken_for_the_recorded_one(hud):
    _mod(hud, 'pf1', 'Red digits', [DIGIT_SLOT], ['red_digit'])
    _record(hud, {'hud:percent_font': _entry('pf1', 'Red digits', 'percent_font', ['percent'])})
    _set(hud, DIGIT, 'other')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'custom', 'stale': True}


def test_recorded_mod_reencoded_still_matches(hud):
    _mod(hud, 'pf1', 'Red digits', [DIGIT_SLOT], ['red_digit'])
    _record(hud, {'hud:percent_font': _entry('pf1', 'Red digits', 'percent_font', ['percent'])})
    _set(hud, DIGIT, 'q_red_digit')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'installed'}


def test_record_whose_file_went_back_to_vanilla(hud):
    _mod(hud, 'pf1', 'Red digits', [DIGIT_SLOT], ['red_digit'])
    _record(hud, {'hud:percent_font': _entry('pf1', 'Red digits', 'percent_font', ['percent'])})
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'vanilla', 'stale': True}


def test_fingerprint_taken_while_the_file_is_as_installed(hud):
    _mod(hud, 'pf1', 'Red digits', [DIGIT_SLOT], ['red_digit'])
    f = hud.project_dir / 'files' / 'IfAll.usd'
    st = f.stat()
    entry = {**_entry('pf1', 'Red digits', 'percent_font', ['percent']),
             'file_stat': [st.st_mtime_ns, st.st_size]}
    _record(hud, {'hud:percent_font': entry})
    _set(hud, DIGIT, 'red_digit', md5='written')
    installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'installed'}
    assert 'hud_fingerprint' not in installed['hud:percent_font']
    assert 'file_stat' not in installed['hud:percent_font']
    stored = json.loads((hud.project_dir / 'nucleus_menus.json').read_text())['installed']
    assert stored['hud:percent_font']['hud_fingerprint'] == {DIGIT: 'written'}

    # the vault mod is edited later: the fingerprint still recognizes the file
    shutil.copy(hud.pics['other'], hud.storage / 'pf1' / 'textures' / 's0.png')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'installed'}


def test_vault_mod_gone_trusts_the_record_unless_vanilla(hud):
    _record(hud, {'hud:percent_font': _entry('gone', 'Deleted', 'percent_font', ['percent'])})
    _set(hud, DIGIT, 'other')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'installed', 'unverified': True}


def test_vault_mod_edited_after_install_trusts_the_record(hud):
    _mod(hud, 'pf1', 'Red digits', [DIGIT_SLOT], ['other'])
    _record(hud, {'hud:percent_font': _entry('pf1', 'Red digits', 'percent_font', ['percent'],
                                             when='2000-01-01T00:00:00')})
    _set(hud, DIGIT, 'red_digit')
    _installed, v = _verify(hud)
    assert v['hud:percent_font'] == {'state': 'installed', 'unverified': True}


def test_export_failure_falls_back_to_the_record(hud):
    _record(hud, {'hud:ready_go': _entry('rg1', 'Words', 'ready_go', ['readygo'])})
    hud.file = None
    installed, v = _verify(hud)
    assert v == {} and installed['hud:ready_go']['id'] == 'rg1'


def test_plain_installed_read_never_runs_the_check(hud):
    hud.get('/api/mex/menus/installed')
    assert hud.exports == 0


def test_without_a_project(hud):
    clear_project_path()
    body = hud.get('/api/mex/menus/installed?verify=hud').get_json()
    assert body['installed'] == {} and body['verification'] == {}


def test_fingerprint_is_not_written_over_a_newer_install(env):
    from vault.menus import installed
    _record(env, {'hud:ready_go': {'id': 'new', 'name': 'New', 'kind': 'ready_go',
                                   'installed': '2026-09-20T00:00:00'}})
    installed.add_installed_menu_fields({'hud:ready_go': ('old', '2026-09-01T00:00:00',
                                                        {'hud_fingerprint': {'x': 'y'}})})
    stored = json.loads((env.project_dir / 'nucleus_menus.json').read_text())['installed']
    assert 'hud_fingerprint' not in stored['hud:ready_go']
    installed.add_installed_menu_fields({'hud:ready_go': ('new', '2026-09-20T00:00:00',
                                                        {'hud_fingerprint': {'x': 'y'}})})
    stored = json.loads((env.project_dir / 'nucleus_menus.json').read_text())['installed']
    assert stored['hud:ready_go']['hud_fingerprint'] == {'x': 'y'}


# ── the vanilla reset before an install, and "Restore vanilla" ──

TIMER_SLOT = {'root': 'ScInfTim_scene_models', 'kind': 'anim', 'ordinal': 3,
              'width': 32, 'height': 36, 'format': 'IA4', 'file': 's2.png', 'replaced': True}
STOCK_SLOT = {'root': 'Stc_scemdls', 'kind': 'anim', 'ordinal': 0,
              'width': 24, 'height': 24, 'format': 'CI4', 'file': 's3.png', 'replaced': True}


@needs_hud_manifest()
def test_reset_keys_cover_the_category_and_the_previous_mods_extras():
    keys = project_percent.hud_reset_keys(['percent'])
    assert DIGIT in keys and EMBLEM in keys
    assert READY not in keys and not any(k.startswith('Stc_scemdls') for k in keys)
    prev = {'slots': [TIMER_SLOT, STOCK_SLOT, READY_SLOT]}
    keys2 = project_percent.hud_reset_keys(['percent'], [prev])
    assert keys2 - keys == {'ScInfTim_scene_models|anim|3'}   # never stocks, never words
    words = project_percent.hud_reset_keys(['readygo'])
    assert READY in words and GO in words and DIGIT not in words


@needs_hud_manifest()
def test_install_resets_the_categories_it_covers(env, monkeypatch):
    calls = []
    monkeypatch.setattr(project_percent, 'apply_percent_mod',
                        lambda mod_id, path, **kw: calls.append(kw) or {})
    (env.storage / 'old').mkdir()
    (env.storage / 'old' / 'mod.json').write_text(json.dumps(
        {'id': 'old', 'name': 'Old', 'slots': [DIGIT_SLOT, TIMER_SLOT]}), encoding='utf-8')
    (env.storage / 'new').mkdir()
    (env.storage / 'new' / 'mod.json').write_text(json.dumps(
        {'id': 'new', 'name': 'New', 'slots': [DIGIT_SLOT]}), encoding='utf-8')
    _record(env, {'hud:percent_font': _entry('old', 'Old', 'percent_font', ['percent'])})
    res = env.post('/api/mex/menus/percent/install/new', json={'slot': 'percent_font'})
    assert res.status_code == 200
    keys = calls[0]['reset_keys']
    assert EMBLEM in keys and 'ScInfTim_scene_models|anim|3' in keys
    assert READY not in keys


@needs_hud_manifest()
def test_apply_puts_reset_slots_and_the_mod_in_one_import(env, monkeypatch, tmp_path):
    _mod_dir = env.storage / 'pf1' / 'textures'
    _mod_dir.mkdir(parents=True)
    _glyph(tmp_path, 'x')
    shutil.copy(tmp_path / 'x.png', _mod_dir / 's0.png')
    (env.storage / 'pf1' / 'mod.json').write_text(json.dumps(
        {'id': 'pf1', 'name': 'x', 'slots': [DIGIT_SLOT]}), encoding='utf-8')
    monkeypatch.setattr(percent_install, 'HSDRAW_EXE', tmp_path / 'x.png')      # "exists"
    specs = []
    monkeypatch.setattr(percent_install, '_run_hud_import', lambda path, reps: specs.append(reps))
    van = {k: {'md5': 'v', 'file': tmp_path / 'x.png'} for k in (DIGIT, EMBLEM)}
    monkeypatch.setattr(hud_verify, 'vanilla_ifall_path', lambda: tmp_path / 'x.png')
    monkeypatch.setattr(hud_verify, 'load_slots', lambda p: van)
    ifall = env.project_dir / 'files' / 'IfAll.usd'
    _REAL_APPLY('pf1', ifall, reset_keys={DIGIT, EMBLEM})
    indices = [r['index'] for r in specs[0]]
    assert len(indices) == len(set(indices)) == 2          # digit once: the mod's
    digit = next(r for r in specs[0] if r['png'].endswith('s0.png'))
    assert digit['format'] == 'rgb5a3'

    # no vanilla ISO: the mod still goes in, and the caller is told
    monkeypatch.setattr(hud_verify, 'vanilla_ifall_path', lambda: None)
    notes = []
    _REAL_APPLY('pf1', ifall, reset_keys={DIGIT, EMBLEM}, notes=notes)
    assert len(specs[1]) == 1 and notes and 'vanilla' in notes[0].lower()


def test_restore_vanilla_clears_the_record(env, monkeypatch, tmp_path):
    monkeypatch.setattr(project_percent, 'HSDRAW_EXE', tmp_path)
    done = []
    monkeypatch.setattr(project_percent, '_vanilla_reset_replacements',
                        lambda keys, region, skip_keys=(): [{'index': 1, 'png': 'x', 'format': 'original'}])
    monkeypatch.setattr(project_percent, '_run_hud_import', lambda path, reps: done.append(reps))
    _record(env, {'hud:ready_go': _entry('rg1', 'Words', 'ready_go', ['readygo']),
                  'hud:percent_font': _entry('pf1', 'Digits', 'percent_font', ['percent'])})
    res = env.post('/api/mex/menus/percent/restore-vanilla', json={'slot': 'ready_go'})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()['cleared'] == 'hud:ready_go'
    stored = json.loads((env.project_dir / 'nucleus_menus.json').read_text())['installed']
    assert set(stored) == {'hud:percent_font'}
    assert done


@needs_hud_manifest()
def test_restore_vanilla_needs_a_vanilla_iso(env, monkeypatch, tmp_path):
    monkeypatch.setattr(project_percent, 'HSDRAW_EXE', tmp_path)
    monkeypatch.setattr(hud_verify, 'vanilla_ifall_path', lambda: None)
    _record(env, {'hud:ready_go': _entry('rg1', 'Words', 'ready_go', ['readygo'])})
    res = env.post('/api/mex/menus/percent/restore-vanilla', json={'slot': 'ready_go'})
    assert res.status_code == 400
    assert 'vanilla' in res.get_json()['error'].lower()
    stored = json.loads((env.project_dir / 'nucleus_menus.json').read_text())['installed']
    assert 'hud:ready_go' in stored                    # nothing changed


def test_restore_vanilla_rejects_unknown_slots(env):
    assert env.post('/api/mex/menus/percent/restore-vanilla', json={'slot': 'pause'}).status_code == 400


# ── real files: HSDRawViewer on copies of the vanilla IfAll ──

def _real_vanilla():
    from core.config import HSDRAW_EXE
    try:
        ref = hud_verify.vanilla_ifall_path()
    except Exception:
        ref = None
    return ref if (ref is not None and HSDRAW_EXE.exists()) else None


needs_real = pytest.mark.skipif(_real_vanilla() is None,
                                reason='vanilla IfAll.usd reference or HSDRawViewer build not available')


@pytest.fixture
def private_temp(tmp_path, monkeypatch):
    """The real installs run HSDRawViewer and work in temp folders. The process
    temp dir is app/scratch (core.config repoints TEMP there), which every other
    test run on this machine shares; with a second run going, this test died on
    WinError 5 in that shared scratch. Its temp work goes to its own folder: the
    Python side through tempfile, HSDRawViewer through the TEMP it inherits."""
    import tempfile
    private = tmp_path / 'temp'
    private.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(private))
    for key in ('TMP', 'TEMP', 'TMPDIR'):
        monkeypatch.setenv(key, str(private))
    return private


def _real_mod(env, mod_id, name, slot_pics):
    """slot_pics: [(slot dict, PIL image)]"""
    tex = env.storage / mod_id / 'textures'
    tex.mkdir(parents=True)
    slots = []
    for n, (slot, im) in enumerate(slot_pics):
        s = {**slot, 'file': f's{n}.png', 'replaced': True}
        im.save(tex / s['file'])
        slots.append(s)
    (env.storage / mod_id / 'mod.json').write_text(json.dumps(
        {'id': mod_id, 'name': name, 'source': 'glyphs', 'region': 'usd', 'slots': slots,
         'created': '2026-09-01T00:00:00'}), encoding='utf-8')


def _art(size, color, shape):
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w, h = size
    if shape == 'box':
        d.rectangle([w // 6, h // 6, w - w // 6, h - h // 6], outline=color, width=max(2, w // 12))
    else:
        d.ellipse([w // 8, h // 8, w - w // 8, h - h // 8], fill=color)
    return im


@needs_real
@pytest.mark.slow
def test_real_install_a_then_b_leaves_no_a_and_restore_reads_vanilla(env, monkeypatch, private_temp):
    vanilla_path = _real_vanilla()
    ifall = env.project_dir / 'files' / 'IfAll.usd'
    shutil.copy(str(vanilla_path), str(ifall))
    van = hud_verify.load_slots(vanilla_path)
    emblem_key = next(k for k in van if k.startswith('DmgMrk_scene_models|mat'))
    root, kind, ordinal = emblem_key.split('|')
    emblem_slot = {'root': root, 'kind': kind, 'ordinal': int(ordinal), 'width': 80,
                   'height': 64, 'format': 'I4'}
    ready_slot = {'root': 'ScInfCnt_scene_models', 'kind': 'mat', 'ordinal': 13,
                  'width': 256, 'height': 64, 'format': 'CI8'}
    go_slot = {**ready_slot, 'ordinal': 14}
    digit_slot = {'root': 'DmgNum_scene_models', 'kind': 'anim', 'ordinal': 1,
                  'width': 32, 'height': 36, 'format': 'IA4'}

    # A: digit 1 + the emblem + READY;  B: digit 1 only;  W: GO! only
    _real_mod(env, 'A', 'Mod A', [(digit_slot, _art((32, 36), (255, 0, 0, 255), 'box')),
                                  (emblem_slot, _art((80, 64), (0, 0, 255, 255), 'dot')),
                                  (ready_slot, _art((256, 64), (0, 255, 0, 255), 'box'))])
    _real_mod(env, 'B', 'Mod B', [(digit_slot, _art((32, 36), (255, 255, 0, 255), 'dot'))])
    _real_mod(env, 'W', 'Mod W', [(go_slot, _art((256, 64), (255, 0, 255, 255), 'dot'))])

    def state():
        return _verify(env)[1]

    def post(mod_id, slot):
        res = env.post(f'/api/mex/menus/percent/install/{mod_id}', json={'slot': slot})
        assert res.status_code == 200, res.get_json()
        assert not res.get_json().get('resetSkipped')

    assert state() == {'hud:percent_font': {'state': 'vanilla', 'stale': False},
                       'hud:ready_go': {'state': 'vanilla', 'stale': False}}
    post('A', 'percent_font')
    s = state()
    assert s['hud:percent_font'] == {'state': 'installed'}
    assert s['hud:ready_go'] == {'state': 'installed'}

    # B replaces A's typeface: A's emblem goes back to vanilla
    post('B', 'percent_font')
    after_b = hud_verify.load_slots(ifall)
    assert hud_verify.slot_is_vanilla(after_b[emblem_key], van[emblem_key])
    assert state()['hud:percent_font'] == {'state': 'installed'}
    # A's READY is a Ready/Go slot: B (percent only) leaves it alone
    ready_key = 'ScInfCnt_scene_models|mat|13'
    assert not hud_verify.slot_is_vanilla(after_b[ready_key], van[ready_key])

    # W (GO! only) replaces A on Ready/Go: A's READY goes back to vanilla
    post('W', 'ready_go')
    after_w = hud_verify.load_slots(ifall)
    assert hud_verify.slot_is_vanilla(after_w[ready_key], van[ready_key])
    assert state()['hud:ready_go'] == {'state': 'installed'}

    # a real different mod is never vanilla and never the recorded one
    for key in ('hud:percent_font', 'hud:ready_go'):
        assert state()[key]['state'] == 'installed'
    records = json.loads((env.project_dir / 'nucleus_menus.json').read_text())
    records['installed']['hud:percent_font']['id'] = 'A'           # pretend A is recorded
    records['installed']['hud:percent_font'].pop('hud_fingerprint', None)
    (env.project_dir / 'nucleus_menus.json').write_text(json.dumps(records))
    assert state()['hud:percent_font'] == {'state': 'custom', 'stale': True}

    # restore both: every typeface slot reads vanilla again
    for slot in ('percent_font', 'ready_go'):
        res = env.post('/api/mex/menus/percent/restore-vanilla', json={'slot': slot})
        assert res.status_code == 200, res.get_json()
    assert state() == {'hud:percent_font': {'state': 'vanilla', 'stale': False},
                       'hud:ready_go': {'state': 'vanilla', 'stale': False}}
    restored = hud_verify.load_slots(ifall)
    for k in set(van) & set(restored):
        if hud_verify.slot_category(k) is None:
            assert restored[k]['md5'] == van[k]['md5']      # stocks/emblems untouched


@needs_real
@pytest.mark.slow
def test_real_check_reads_vanilla_the_mod_and_a_reencoded_vanilla(env, tmp_path, private_temp):
    from core.config import HSDRAW_EXE
    import subprocess
    vanilla_path = _real_vanilla()
    ifall = env.project_dir / 'files' / 'IfAll.usd'
    shutil.copy(str(vanilla_path), str(ifall))
    ready_slot = {'root': 'ScInfCnt_scene_models', 'kind': 'mat', 'ordinal': 13,
                  'width': 256, 'height': 64, 'format': 'CI8'}
    _real_mod(env, 'R', 'Red READY', [(ready_slot, _art((256, 64), (255, 0, 0, 255), 'box'))])
    res = env.post('/api/mex/menus/percent/install/R', json={'slot': 'ready_go'})
    assert res.status_code == 200
    assert _verify(env)[1]['hud:ready_go'] == {'state': 'installed'}

    # every typeface slot re-encoded from the vanilla pictures (not the same
    # bytes: CI8 palettes are rebuilt) still reads as vanilla
    van = hud_verify.load_slots(vanilla_path)
    spec = [{'index': v['index'], 'png': str(v['file']), 'format': 'original'}
            for k, v in van.items() if hud_verify.slot_category(k) and
            (k.startswith(('DmgNum', 'DmgMrk')) or k in hud_verify._word_mat_keys())]
    (tmp_path / 'spec.json').write_text(json.dumps({'replacements': spec}))
    out = tmp_path / 'IfAll.usd'
    subprocess.run([str(HSDRAW_EXE), '--hud-textures', 'import', str(ifall),
                    str(tmp_path / 'spec.json'), str(out)], check=True, capture_output=True)
    shutil.copy(str(out), str(ifall))
    changed = hud_verify.load_slots(ifall)
    assert any(changed[k]['md5'] != van[k]['md5'] for k in changed if k in van)
    assert _verify(env)[1] == {'hud:percent_font': {'state': 'vanilla', 'stale': False},
                               'hud:ready_go': {'state': 'vanilla', 'stale': True}}


IN_USE = "The process cannot access the file 'GmPause.usd' because it is being used by another process."


@pytest.mark.parametrize('stderr, failing, calls, ok', [
    (IN_USE, 2, 3, True),                          # held twice, then free
    (IN_USE, 3, 3, False),                         # held throughout: three tries, then give up
    ('Main called with 5 arguments', 3, 1, False),  # a real failure is not retried
])
def test_hsd_cli_waits_out_a_scanner_but_not_a_real_failure(tmp_path, monkeypatch, stderr, failing, calls, ok):
    """A file held by another process is retried; anything else fails at once."""
    import subprocess
    from vault.menus import hsd
    exe = tmp_path / 'HSDRawViewer.exe'
    exe.write_bytes(b'')
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        busy = len(seen) <= failing
        return subprocess.CompletedProcess(cmd, 1 if busy else 0, '', stderr if busy else '')

    monkeypatch.setattr(hsd, 'HSDRAW_EXE', exe)
    monkeypatch.setattr(hsd.subprocess, 'run', run)
    monkeypatch.setattr(hsd.time, 'sleep', lambda s: None)
    result = hsd._run_hsd_cli(['--pause-screen', 'GmPause.usd'])
    assert len(seen) == calls
    assert (result is not None) == ok
