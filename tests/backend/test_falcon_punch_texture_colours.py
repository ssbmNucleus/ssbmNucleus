"""Falcon Punch: custom colours, then a fire hue, then other colours, then a
restore, on the vanilla EfCaData.dat with the real HSDRawViewer (bug 11-19).

The hue used to repack the file, after which nine of the ten flare-line colour
writes were refused and the restore left 13 groups unresolved. With the texture
written in place, every colour write lands, all 35 colour spans restore, and
nothing outside the three fire textures differs from vanilla (Falcon Kick,
Raptor Boost and the rest of the file included)."""
import shutil
from pathlib import Path

import pytest

from core.config import HSDRAW_EXE
from core.extra_lookup import get_extra_type
from vault.extras import helpers, textures
from vault.extras.color_patch import apply_hex_patches
from vault.extras.texture_layout import _Archive, model_textures
from shared.rendering.datprobe import gx_image_size

pytestmark = pytest.mark.slow

FIRST = dict(color1='004BFF', color2='00CAFF', dots='05E0FF', flare_big_c1='0031FF',
             flare_lines_c2='FFFFFF', flare_small_c1='0200FF', smoke='2B55DE',
             trail_smoke='FFFFFF', wing_smoke='E8E1FF')     # the reported colours


@pytest.fixture
def falcon(tmp_path, monkeypatch):
    if not Path(HSDRAW_EXE).exists():
        pytest.skip('HSDRawViewer is not available')
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    vanilla = ensure_vanilla_ref('EfCaData.dat')
    if vanilla is None:
        pytest.skip('no vanilla EfCaData.dat (no recorded ISO)')
    vault = tmp_path / 'vault'
    (vault / 'test-base' / 'files').mkdir(parents=True)
    shutil.copy2(vanilla, vault / 'test-base' / 'files' / 'EfCaData.dat')
    project = tmp_path / 'project' / 'files'
    project.mkdir(parents=True)
    shutil.copy2(vanilla, project / 'EfCaData.dat')
    target = tmp_path / 'work' / 'EfCaData.dat'
    target.parent.mkdir()
    shutil.copy2(vanilla, target)
    monkeypatch.setattr(helpers, 'STORAGE_PATH', vault)
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: project)
    monkeypatch.setattr(helpers, 'HSDRAW_VIEWER_PATH', HSDRAW_EXE)
    return target, vanilla.read_bytes()


def _colours(target, values):
    cfg = get_extra_type('C. Falcon', 'falcon_punch')
    mods = {key: {'color': value} for key, value in values.items()}
    safety = helpers.make_write_safety(target, cfg['id'], cfg['target_file'], cfg['vanilla'])
    return apply_hex_patches(target, cfg['offsets'], mods, safety)


def _texture_bytes(raw, fire):
    """Every byte offset of the fire textures' pixels."""
    archive, spans = _Archive(raw), set()
    for node, index in textures.get_texture_targets(fire):
        image = archive.ptr(model_textures(archive, node)[index] + 0x4C)
        start = 0x20 + archive.ptr(image)
        size = gx_image_size(archive.u32(image + 8), archive.u16(image + 4), archive.u16(image + 6))
        spans.update(range(start, start + size))
    return spans


def _outside(a, b, allowed):
    assert len(a) == len(b)
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y and i not in allowed]


def test_colour_hue_colour_restore_keeps_every_colour_span(falcon):
    target, vanilla = falcon
    fire = get_extra_type('C. Falcon', 'punch_texture')
    textures_at = _texture_bytes(vanilla, fire)

    assert _colours(target, FIRST) == []
    coloured = target.read_bytes()

    textures.apply_texture_extra_hue('C. Falcon', 'punch_texture', fire, 216, target)
    hued = target.read_bytes()
    assert len(hued) == len(vanilla)
    assert _outside(coloured, hued, textures_at) == []          # only the fire textures changed
    assert hued != coloured

    # the same hue again writes the same bytes
    textures.apply_texture_extra_hue('C. Falcon', 'punch_texture', fire, 216, target)
    assert target.read_bytes() == hued

    # a second, different colour set lands everywhere (it used to skip 9 flare lines)
    assert _colours(target, {key: '1234EF' for key in FIRST}) == []

    report = {}
    cfg = get_extra_type('C. Falcon', 'falcon_punch')
    assert helpers.restore_extra_color_bytes(target, cfg, report=report) == []
    assert report['restored_spans'] == 35
    restored = target.read_bytes()
    assert _outside(vanilla, restored, textures_at) == []       # every colour back to vanilla

    textures.restore_texture_extra('C. Falcon', 'punch_texture', fire, target)
    assert _outside(vanilla, target.read_bytes(), textures_at) == []
    assert len(target.read_bytes()) == len(vanilla)


def test_firefox_hue_beside_an_image_shine_keeps_the_shine(tmp_path, monkeypatch):
    """Fox's EfFxData.dat: the Firefox texture is CI8 with a shared palette, and
    an image shine appends blocks a re-serialization would drop."""
    from copy import deepcopy
    from vault.extras import effect_model
    if not Path(HSDRAW_EXE).exists():
        pytest.skip('HSDRawViewer is not available')
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    vanilla = ensure_vanilla_ref('EfFxData.dat')
    if vanilla is None:
        pytest.skip('no vanilla EfFxData.dat (no recorded ISO)')
    shine = deepcopy(get_extra_type('Fox', 'shine'))
    shine['image_model'].update(width=4, height=4)
    pixels = [(255, 0, 0, 255), (0, 255, 0, 255)] * 8
    target = tmp_path / 'work' / 'EfFxData.dat'
    target.parent.mkdir()
    target.write_bytes(effect_model.install_image(vanilla.read_bytes(), pixels, shine))
    project = tmp_path / 'project' / 'files'
    project.mkdir(parents=True)
    shutil.copy2(vanilla, project / 'EfFxData.dat')
    monkeypatch.setattr(helpers, 'STORAGE_PATH', tmp_path / 'vault')
    monkeypatch.setattr(helpers, 'get_project_files_dir', lambda: project)
    monkeypatch.setattr(helpers, 'HSDRAW_VIEWER_PATH', HSDRAW_EXE)
    before = target.read_bytes()

    fire = get_extra_type('Fox', 'upb_texture')
    textures.apply_texture_extra_hue('Fox', 'upb_texture', fire, 200, target)
    after = target.read_bytes()
    archive, allowed = _Archive(before), set()
    for node, index in textures.get_texture_targets(fire):
        tobj = model_textures(archive, node)[index]
        image, tlut = archive.ptr(tobj + 0x4C), archive.ptr(tobj + 0x50)
        start = 0x20 + archive.ptr(image)
        allowed.update(range(start, start + gx_image_size(archive.u32(image + 8), 64, 64)))
        palette = 0x20 + archive.ptr(tlut)
        allowed.update(range(palette, palette + archive.u16(tlut + 0x0C) * 2))
    assert after != before and _outside(before, after, allowed) == []
    assert effect_model.read_rgba(effect_model.EffectDat(after), effect_model.parse_cfg(shine)) == (4, 4, pixels)
