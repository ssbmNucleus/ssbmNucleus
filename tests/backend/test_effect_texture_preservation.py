"""A texture import keeps an installed image shine, its revert header and every
other byte of the file: only the texture's own pixels and palette change, in
place, however much the native import moved things (bug 11-19)."""
from tests.paths import APP
from copy import deepcopy
from pathlib import Path
import struct

import pytest

from vault.extras import effect_model, textures
from vault.extras.texture_layout import TextureLayoutError, _Archive, model_textures
from core.extra_lookup import get_extra_type
from shared.rendering.datprobe import gx_image_size


VANILLA = APP / 'storage/test-base/files/EfFxData.dat'
pytestmark = pytest.mark.skipif(not VANILLA.exists(), reason='vanilla EfFxData.dat unavailable')


@pytest.fixture
def image_dat(tmp_path):
    config = deepcopy(get_extra_type('Fox', 'shine'))
    config['image_model'].update(width=4, height=4)
    original = VANILLA.read_bytes()
    pixels = [(255, 0, 0, 255), (0, 255, 0, 255)] * 8
    image = effect_model.install_image(original, pixels, config)
    path = tmp_path / 'EfFxData.dat'
    path.write_bytes(image)
    return path, config, original


def _texture_spans(raw, node, index):
    """(file offset, length) of the texture's pixels and palette."""
    archive = _Archive(raw)
    tobj = model_textures(archive, node)[index]
    image = archive.ptr(tobj + 0x4C)
    spans = [(0x20 + archive.ptr(image),
              gx_image_size(archive.u32(image + 8), archive.u16(image + 4), archive.u16(image + 6)))]
    tlut = archive.ptr(tobj + 0x50)
    if tlut is not None:
        spans.append((0x20 + archive.ptr(tlut), archive.u16(tlut + 0x0C) * 2))
    return spans


def _relocate_and_recolour(raw, node, index):
    """What HSDRaw's import does to the file, roughly: every data node moves by
    32 bytes (all pointers fixed up), an unrelated sparkle colour differs, and
    the target texture's pixels and palette are re-encoded."""
    archive = effect_model.EffectDat(raw)
    old_data = bytes(archive.data)
    old_relocs = archive.relocs.copy()
    archive.data = bytearray(32) + archive.data
    for offset in old_relocs:
        pointer, = struct.unpack_from('>I', old_data, offset)
        struct.pack_into('>I', archive.data, offset + 32, pointer + 32)
    archive.relocs = {offset + 32 for offset in old_relocs}
    archive.roots = [(offset + 32, name) for offset, name in archive.roots]
    archive.refs = [(offset + 32, name) for offset, name in archive.refs]
    archive.data_size = len(archive.data)
    archive.data[0x127:0x12A] = bytes.fromhex('123456')
    moved = archive.to_bytes()
    out = bytearray(moved)
    for start, length in _texture_spans(moved, node, index):
        out[start:start + length] = bytes([0xAB]) * length
    return bytes(out)


@pytest.mark.parametrize('operation', ['install', 'restore'])
def test_texture_operations_keep_the_image_shine_and_every_other_byte(
        image_dat, tmp_path, monkeypatch, operation):
    target, shine, _original = image_dat
    before = target.read_bytes()
    pixels_before = effect_model.read_rgba(effect_model.EffectDat(before),
                                          effect_model.parse_cfg(shine))
    header_before = effect_model.find_header(effect_model.EffectDat(before))
    fire = deepcopy(get_extra_type('Fox', 'upb_texture'))
    node, index = textures.get_texture_targets(fire)[0]
    fire['texture_targets'] = [{'path': node, 'index': index}]

    def graph_import(source, node_path, tex_index, png, output):
        source_bytes = Path(source).read_bytes()
        assert source_bytes == before and target.read_bytes() == before
        Path(output).write_bytes(_relocate_and_recolour(source_bytes, node_path, tex_index))

    monkeypatch.setattr(textures, 'import_texture', graph_import)
    monkeypatch.setattr(textures.helpers, 'STORAGE_PATH', tmp_path / 'vault')
    monkeypatch.setattr(textures, 'ensure_vanilla_texture', lambda *args, **kwargs: tmp_path / 'unused.png')

    if operation == 'install':
        textures.apply_texture_extra_hue('Fox', 'upb_texture', fire,
                                         fire.get('vanilla_hue', 30), target)
    else:
        textures.restore_texture_extra('Fox', 'upb_texture', fire, target)

    result = target.read_bytes()
    allowed = set()
    for start, length in _texture_spans(before, node, index):
        allowed.update(range(start, start + length))
        assert result[start:start + length] == bytes([0xAB]) * length
    assert len(result) == len(before)
    assert {i for i, (a, b) in enumerate(zip(before, result)) if a != b} <= allowed
    archive = effect_model.EffectDat(result)
    assert effect_model.find_header(archive) == header_before
    assert effect_model.read_rgba(archive, effect_model.parse_cfg(shine)) == pixels_before
    reverted, changed = effect_model.revert_dat(result, shine)
    assert changed and len(reverted) < len(result)
    assert not list(tmp_path.glob('.*.dat'))


@pytest.mark.parametrize('failure_stage', ['import', 'layout'])
def test_texture_failure_preserves_original(image_dat, tmp_path, monkeypatch, failure_stage):
    target, _, _ = image_dat
    before = target.read_bytes()

    def graph_import(source, node_path, tex_index, png, output):
        Path(output).write_bytes(b'not an archive' if failure_stage == 'layout'
                                 else _relocate_and_recolour(Path(source).read_bytes(), node_path, tex_index))
        if failure_stage == 'import':
            raise RuntimeError('texture importer failed')

    monkeypatch.setattr(textures, 'import_texture', graph_import)
    with pytest.raises((RuntimeError, TextureLayoutError)):
        textures._import_over(target, 'effFoxDataTable/Models_4_/RootJoint', 1, tmp_path / 'unused.png')

    assert target.read_bytes() == before
    assert not list(tmp_path.glob('.*.dat'))
