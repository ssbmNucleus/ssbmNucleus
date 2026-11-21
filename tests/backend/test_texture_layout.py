"""A texture import replaces the texture's bytes in place and moves nothing else
(bug 11-19: a Falcon Punch fire hue repacked EfCaData.dat and the colour extras
then lost their offsets). Synthetic archives only: an effect table whose model
0 is one joint with a DObj per texture, built here byte by byte."""
import struct
from pathlib import Path

import pytest

from shared.rendering.datprobe import gx_image_size
from vault.extras import textures
from vault.extras.texture_layout import TextureLayoutError, _Archive, model_textures, transplant_texture

NODE = 'effTestDataTable/Models_0_/RootJoint'
CMPR, RGB5A3, CI8 = 14, 5, 9


def _fill(key):
    return 20 + sum(key.encode()) % 200


def build(images, *, lead=0, fills=None, palette_fill=0x7F, palette_count=256, mipmap=0,
          tail=b'COLOUR BYTES 1234'):
    """images: (width, height, gx_format, buffer key) per texture; textures with
    the same key share one pixel buffer, as vanilla Falcon's do. CI8 textures
    share one palette. `lead` pads the data section's start, so the same tree
    built with another lead is what a re-serialization that moved it gives."""
    fills = fills or {}
    data, relocs = bytearray(lead), []

    def block(size):
        while len(data) % 0x20:
            data.append(0)
        offset = len(data)
        data.extend(bytes(size))
        return offset

    def ptr(at, target):
        struct.pack_into('>I', data, at, target)
        relocs.append(at)

    table = block(0x08 + 0x14)
    jobj = block(0x40)
    ptr(table + 0x08 + 0x04, jobj)
    buffers, tlut, previous = {}, None, None
    for width, height, fmt, key in images:
        dobj, mobj, tobj, image = block(0x10), block(0x18), block(0x5C), block(0x18)
        ptr(dobj + 0x08, mobj)
        ptr(mobj + 0x08, tobj)
        ptr(tobj + 0x4C, image)
        if key not in buffers:
            size = gx_image_size(fmt, width, height)
            buffers[key] = block(size)
            data[buffers[key]:buffers[key] + size] = bytes([fills.get(key, _fill(key))]) * size
        ptr(image, buffers[key])
        struct.pack_into('>HHII', data, image + 0x04, width, height, fmt, mipmap)
        if fmt == CI8:
            if tlut is None:
                tlut, palette = block(0x10), block(palette_count * 2)
                data[palette:palette + palette_count * 2] = bytes([palette_fill]) * (palette_count * 2)
                ptr(tlut, palette)
                struct.pack_into('>I', data, tlut + 0x04, 2)
                struct.pack_into('>H', data, tlut + 0x0C, palette_count)
            ptr(tobj + 0x50, tlut)
        ptr((jobj + 0x10) if previous is None else (previous + 0x04), dobj)
        previous = dobj
    end = block(len(tail))
    data[end:end + len(tail)] = tail
    names = b'effTestDataTable\0'
    body = bytes(data)
    reloc_bytes = b''.join(struct.pack('>I', r) for r in sorted(relocs))
    roots = struct.pack('>II', table, 0)
    total = 0x20 + len(body) + len(reloc_bytes) + len(roots) + len(names)
    return (struct.pack('>5I', total, len(body), len(relocs), 1, 0) + bytes(12)
            + body + reloc_bytes + roots + names)


def _changed(a, b):
    assert len(a) == len(b)
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


def _pixels(raw, index):
    archive = _Archive(raw)
    image = archive.ptr(model_textures(archive, NODE)[index] + 0x4C)
    size = gx_image_size(archive.u32(image + 8), archive.u16(image + 4), archive.u16(image + 6))
    return 0x20 + archive.ptr(image), archive.bytes_at(archive.ptr(image), size)


FALCON = [(64, 64, CMPR, 'lava'), (64, 64, CMPR, 'lava'), (32, 32, CMPR, 'ember'),
          (64, 64, CMPR, 'lava'), (64, 32, RGB5A3, 'wisp')]


def test_only_the_textures_own_bytes_change_and_nothing_moves():
    raw = build(FALCON)
    imported = build(FALCON, lead=0x40, fills={'ember': 0xAB})
    result = transplant_texture(raw, imported, NODE, 2)
    start, pixels = _pixels(raw, 2)
    assert _changed(raw, result) == list(range(start, start + 512))
    assert _pixels(result, 2)[1] == bytes([0xAB]) * 512
    assert result.endswith(raw[-60:]) and b'COLOUR BYTES 1234' in result


def test_a_shared_pixel_buffer_changes_once_for_every_texture_using_it():
    """Seven of vanilla Falcon's image headers share one buffer. HSDRaw edits a
    shared buffer in place, so every texture using it shows the new pixels."""
    raw = build(FALCON)
    result = transplant_texture(raw, build(FALCON, lead=0x40, fills={'lava': 0xAB}), NODE, 0)
    for index in (0, 1, 3):
        assert _pixels(result, index)[1] == bytes([0xAB]) * 2048
    assert _pixels(result, 2)[1] == _pixels(raw, 2)[1]
    assert len(_changed(raw, result)) == 2048


def test_a_paletted_texture_takes_its_palette_too():
    flame = [(64, 64, CI8, 'flame'), (64, 64, CI8, 'flame')]
    raw = build(flame)
    result = transplant_texture(raw, build(flame, lead=0x20, fills={'flame': 0xAB},
                                           palette_fill=0x11), NODE, 1)
    assert len(_changed(raw, result)) == 4096 + 512


def test_repeating_the_same_import_gives_the_same_file():
    raw = build(FALCON)
    imported = build(FALCON, lead=0x40, fills={'wisp': 0xAB})
    once = transplant_texture(raw, imported, NODE, 4)
    assert transplant_texture(once, imported, NODE, 4) == once


@pytest.mark.parametrize('images,native', [
    ([(64, 64, CMPR, 'lava')], [(64, 64, RGB5A3, 'lava')]),       # other format
    ([(64, 64, CMPR, 'lava')], [(32, 64, CMPR, 'lava')]),         # other size
])
def test_a_texture_that_does_not_fit_in_place_is_refused(images, native):
    with pytest.raises(TextureLayoutError):
        transplant_texture(build(images), build(native, lead=0x40), NODE, 0)


def test_a_palette_of_another_size_is_refused():
    flame = [(64, 64, CI8, 'flame')]
    with pytest.raises(TextureLayoutError, match='palette'):
        transplant_texture(build(flame), build(flame, palette_count=128), NODE, 0)


def test_mipmaps_and_paths_it_cannot_follow_are_refused():
    lava = [(64, 64, CMPR, 'lava')]
    with pytest.raises(TextureLayoutError, match='mipmapped'):
        transplant_texture(build(lava, mipmap=1), build(lava, mipmap=1, lead=0x40), NODE, 0)
    raw = build(lava)
    for path, index in ((NODE, 5), ('effOtherDataTable/Models_0_/RootJoint', 0),
                        ('effTestDataTable/Models_3_/RootJoint', 0), ('effTestDataTable/Particles', 0)):
        with pytest.raises(TextureLayoutError):
            transplant_texture(raw, build(lava, lead=0x40), path, index)


def test_a_buffer_the_native_import_did_not_share_is_refused():
    """If the native result shows a texture that shared the buffer still holding
    the old pixels, an in-place copy would change it anyway: refuse."""
    raw = build(FALCON)
    split = [(64, 64, CMPR, 'lava'), (64, 64, CMPR, 'lava copy')] + FALCON[2:]
    imported = build(split, lead=0x40, fills={'lava': 0xAB, 'lava copy': _fill('lava')})
    with pytest.raises(TextureLayoutError, match='sharing'):
        transplant_texture(raw, imported, NODE, 0)


def test_a_changed_texture_list_is_refused():
    with pytest.raises(TextureLayoutError, match='texture list'):
        transplant_texture(build(FALCON), build(FALCON[:-1], lead=0x40), NODE, 0)


# --------------------------------------------------------------------------
# textures._import_over
# --------------------------------------------------------------------------

def test_import_over_writes_in_place_and_leaves_no_temporary_files(tmp_path, monkeypatch):
    raw = build(FALCON)
    target = tmp_path / 'EfTsData.dat'
    target.write_bytes(raw)

    def fake_import(source, node_path, tex_index, png, output):
        assert Path(source).read_bytes() == raw and (node_path, tex_index) == (NODE, 2)
        Path(output).write_bytes(build(FALCON, lead=0x40, fills={'ember': 0xAB}))

    monkeypatch.setattr(textures, 'import_texture', fake_import)
    textures._import_over(target, NODE, 2, tmp_path / 'fire.png')
    assert len(_changed(raw, target.read_bytes())) == 512
    assert sorted(p.name for p in tmp_path.iterdir()) == ['EfTsData.dat']


@pytest.mark.parametrize('failure', ['import', 'layout'])
def test_a_failed_import_leaves_the_file_alone(tmp_path, monkeypatch, failure):
    raw = build(FALCON)
    target = tmp_path / 'EfTsData.dat'
    target.write_bytes(raw)

    def fake_import(source, node_path, tex_index, png, output):
        Path(output).write_bytes(build([(32, 32, CMPR, 'lava')] + FALCON[1:], lead=0x40))
        if failure == 'import':
            raise RuntimeError('texture importer failed')

    monkeypatch.setattr(textures, 'import_texture', fake_import)
    with pytest.raises((RuntimeError, TextureLayoutError)):
        textures._import_over(target, NODE, 0, tmp_path / 'fire.png')
    assert target.read_bytes() == raw
    assert sorted(p.name for p in tmp_path.iterdir()) == ['EfTsData.dat']
