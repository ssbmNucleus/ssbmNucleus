"""Stage colours outside textures and material descriptors (shared/rendering/dat_colours.py,
randall/recolor/stage_colours.py): where each object's colour comes from, vertex colour and
animated colour edits that keep formats, counts, alpha and timing, their reset, and the saved
variant carrying them.

The stage files are small synthetic HSD archives built here (one map_head group, a joint
with DOBJs, POBJ vertex colours in every GX colour format, a material animation). No
renderer runs: the stand-in serves the file it was started on, as the real one exports it.
"""
import io
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from core import config
from randall.assistant import tools
from randall.recolor import stage_colours, stage_lab
from shared.rendering import dat_colours as dc

PURPLE = [(120, 40, 200, 255), (90, 30, 160, 128), (200, 160, 250, 0)]


# --------------------------------------------------------------------------- #
# a synthetic stage                                                            #
# --------------------------------------------------------------------------- #
class Builder:
    def __init__(self):
        self.data, self.relocs = bytearray(), []

    def alloc(self, size, align=4):
        self.data += bytes(-len(self.data) % align)
        offset = len(self.data)
        self.data += bytes(size)
        return offset

    def put(self, offset, fmt, *values):
        struct.pack_into('>' + fmt, self.data, offset, *values)

    def ptr(self, field, target):
        self.put(field, 'I', target)
        self.relocs.append(field)

    def blob(self, raw, align=32):
        offset = self.alloc(len(raw), align)
        self.data[offset:offset + len(raw)] = raw
        return offset

    def build(self, roots):
        self.data += bytes(-len(self.data) % 4)
        names = b''.join(name.encode() + b'\0' for name, _ in roots)
        table, offset = b'', 0
        for name, root in roots:
            table += struct.pack('>II', root, offset)
            offset += len(name) + 1
        body = bytes(self.data) + b''.join(struct.pack('>I', r) for r in sorted(self.relocs)) + table + names
        return struct.pack('>5I', 0x20 + len(body), len(self.data), len(self.relocs), len(roots), 0) + bytes(12) + body


def colour_bytes(fmt, rgba):
    r, g, b, a = rgba
    if fmt == 0:
        return (round(r * 31 / 255) << 11 | round(g * 63 / 255) << 5 | round(b * 31 / 255)).to_bytes(2, 'big')
    if fmt == 1:
        return bytes((r, g, b))
    if fmt in (2, 5):
        return bytes((r, g, b, a if fmt == 5 else 0x5A))
    if fmt == 3:
        return (round(r / 17) << 12 | round(g / 17) << 8 | round(b / 17) << 4 | round(a / 17)).to_bytes(2, 'big')
    return (round(r * 63 / 255) << 18 | round(g * 63 / 255) << 12 | round(b * 63 / 255) << 6
            | round(a * 63 / 255)).to_bytes(3, 'big')


def stage(fmt=1, kind='direct', objects=2, shared=False, render_flags=0x12, tracks=None, texture=True, light=None,
          pe=None, colormap=4, tev=None, fog=None):
    """A stage DAT: `objects` DOBJs on one joint, each a triangle with CLR0 colours (PURPLE).

    kind 'direct' stores the colours in the display list, 'index' in an array (`shared`: one
    array for every object). `tracks`: [(type, value_flag, stream)] of a material animation on
    object 0 (an alpha track is always added). Object 0 draws an I8 (greyscale) texture.
    `light`: (rgba, [(type, value_flag, stream)]) of a group light and its colour animation.
    Object 0 can also have a pixel-engine descriptor (`pe`: its 12 bytes), a colour map other
    than MODULATE (`colormap`) and a TEV block (`tev`: its active flags); the group a fog
    (`fog`: (type, rgba)).
    """
    b = Builder()
    head = b.alloc(0x30)
    group = b.alloc(0x34)
    b.ptr(head + 0x08, group)
    b.put(head + 0x0C, 'I', 1)
    joint = b.alloc(0x40)
    b.ptr(group, joint)
    positions = b.blob(struct.pack('>9f', 0, 0, 0, 10, 0, 0, 0, 10, 0))
    size = dc.COLOUR_FORMATS[fmt][1]
    array = b.blob(b''.join(colour_bytes(fmt, c) for c in PURPLE)) if kind == 'index' else None
    previous = joint + 0x10
    for index in range(objects):
        dobj, mobj, material, pobj = b.alloc(0x10), b.alloc(0x18), b.alloc(0x14), b.alloc(0x18)
        b.ptr(previous, dobj)
        previous = dobj + 0x04
        b.ptr(dobj + 0x08, mobj)
        b.ptr(dobj + 0x0C, pobj)
        b.put(mobj + 0x04, 'I', render_flags | (0x10 if texture and index == 0 else 0))
        b.ptr(mobj + 0x0C, material)
        b.put(material, '12Bff', 128, 128, 128, 255, 180, 180, 180, 255, 255, 255, 255, 255, 1.0, 50.0)
        if pe is not None and index == 0:
            b.ptr(mobj + 0x14, b.blob(bytes(pe), 4))
        if texture and index == 0:
            tobj, image = b.alloc(0x5C), b.alloc(0x18)
            b.ptr(mobj + 0x08, tobj)
            b.put(tobj + 0x40, 'I', colormap << 16)                   # 4: colour map MODULATE
            if tev is not None:
                block = b.alloc(0x20)
                b.put(block + 0x1C, 'I', tev)
                b.ptr(tobj + 0x58, block)
            b.ptr(tobj + 0x4C, image)
            b.ptr(image, b.blob(bytes(range(64))))
            b.put(image + 4, 'HHI', 8, 8, 1)                           # 8x8 I8
        attrs = b.alloc(0x18 * 3)
        b.put(attrs, 'IIIIBBH', 9, 2, 1, 4, 0, 0, 12)
        b.ptr(attrs + 0x14, positions)
        b.put(attrs + 0x18, 'IIIIBBH', 11, 1 if kind == 'direct' else 2, 1, fmt, 0, 0, size)
        if kind == 'index':
            b.ptr(attrs + 0x18 + 0x14, array if shared else b.blob(b''.join(colour_bytes(fmt, c) for c in PURPLE)))
        b.put(attrs + 0x30, 'I', 0xFF)
        b.ptr(pobj + 0x08, attrs)
        stream = bytearray(b'\x90' + struct.pack('>H', 3))
        for v in range(3):
            stream += bytes((v,)) + (colour_bytes(fmt, PURPLE[v]) if kind == 'direct' else bytes((v,)))
        stream += bytes(-len(stream) % 32)
        b.put(pobj + 0x0E, 'H', len(stream) // 32)
        b.ptr(pobj + 0x10, b.blob(bytes(stream)))
    if tracks is not None:
        anims = b.alloc(8)
        b.ptr(group + 0x08, anims)
        node, matanim, aobj = b.alloc(0x0C), b.alloc(0x10), b.alloc(0x10)
        b.ptr(anims, node)
        b.ptr(node + 0x08, matanim)
        b.ptr(matanim + 0x04, aobj)
        b.put(aobj, 'If', 1 << 29, 60.0)
        previous = aobj + 0x08
        for kind_, value_flag, raw in [*tracks, (10, 0x88, dc.encode_keys(
                [{'op': 2, 'value': 0.25, 'tan': None, 'step': 60}, {'op': 2, 'value': 0.75, 'tan': None, 'step': 0}],
                0x88, 0))]:
            desc = b.alloc(0x14)
            b.ptr(previous, desc)
            previous = desc
            b.put(desc + 0x04, 'IfBBB', len(raw), 0.0, kind_, value_flag, 0)
            b.ptr(desc + 0x10, b.blob(raw))
    if light is not None:
        rgba, light_tracks = light
        lights, record, lobj = b.alloc(8), b.alloc(8), b.alloc(0x1C)
        b.ptr(group + 0x18, lights)
        b.ptr(lights, record)
        b.ptr(record, lobj)
        b.put(lobj + 0x0C, '4B', *rgba)
        if light_tracks:
            anims, node, aobj = b.alloc(8), b.alloc(0x10), b.alloc(0x10)
            b.ptr(record + 4, anims)
            b.ptr(anims, node)
            b.ptr(node + 4, aobj)
            b.put(aobj, 'If', 0, 100.0)
            previous = aobj + 0x08
            for kind_, value_flag, raw in light_tracks:
                desc = b.alloc(0x14)
                b.ptr(previous, desc)
                previous = desc
                b.put(desc + 0x04, 'IfBBB', len(raw), 0.0, kind_, value_flag, 0)
                b.ptr(desc + 0x10, b.blob(raw))
    if fog is not None:
        fog_type, rgba = fog
        record = b.alloc(0x14)
        b.put(record, 'I', fog_type)
        b.put(record + 0x08, 'ff', 20.0, 400.0)
        b.put(record + 0x10, '4B', *rgba)
        b.ptr(group + 0x1C, record)
    return b.build([('map_head', head)])


def keys(op, frames, values, tans=None):
    out = []
    for i, (frame, value) in enumerate(zip(frames, values)):
        step = frames[i + 1] - frame if i + 1 < len(frames) else 0
        out.append({'op': op, 'value': value, 'tan': tans[i] if tans else None, 'step': step})
    return out


# --------------------------------------------------------------------------- #
# the Stage Lab around it                                                      #
# --------------------------------------------------------------------------- #
def png(rgba, size=(8, 8)):
    out = io.BytesIO()
    Image.new('RGBA', size, rgba).save(out, format='PNG')
    return out.getvalue()


class Renderer:
    """The live renderer's protocol over the file it was started on (exportDat returns it)."""
    camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}

    def __init__(self, exe, port, dat_file, **kwargs):
        self.data = Path(dat_file).read_bytes()
        self.textures = [{'index': 0, 'name': 'Group 0 / Texture_0', 'width': 8, 'height': 8, 'matAnim': False,
                          'animates': -1, 'extra': False}]
        self.closed = False

    def get_full_texture(self, index): return png((90, 90, 90, 255))
    def grab_frame(self): return png((10, 10, 10, 255), (16, 16))
    def export_dat(self): return self.data
    def get_uv_layout(self): return [{'index': 0, 'triangles': [[0] * 15]}]
    def set_camera(self, **kwargs): return dict(self.camera)
    def alive(self): return not self.closed
    def close(self): self.closed = True
    def update_texture(self, index, data): pass
    def material_command(self, command): return {'success': True, 'materials': []}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    renderers = []

    def make(*args, **kwargs):
        renderers.append(Renderer(*args, **kwargs))
        return renderers[-1]
    monkeypatch.setattr(stage_lab, 'ViewerSession', make)
    monkeypatch.setattr(stage_colours, 'ViewerSession', make)
    (tmp_path / 'skinlab_stages').mkdir()
    from shared.rendering import stage_ops
    monkeypatch.setattr(stage_ops, 'STAGE_DATS_DIR', tmp_path / 'skinlab_stages')

    def open_(data):
        (tmp_path / 'skinlab_stages' / 'GrNLa.dat').write_bytes(data)
        return run('stage_lab_open', stage_code='GrNLa')
    yield SimpleNamespace(renderers=renderers, root=tmp_path, open=open_)
    for key in list(stage_lab._sessions):
        stage_lab._sessions.pop(key)['viewer'].close()


def run(tool, **args):
    return tools.execute(tools.prepare(tool, args))


def vertex(data, object_id):
    inv = dc.scan(data)
    obj = inv.object(object_id)
    return [(v.fmt, len(v.positions), [c for _, c in dc.vertex_values(inv.dat, v)]) for v in obj.vertex]


def hue(rgb):
    from shared.rendering.palette import rgb_to_hsl
    return float(rgb_to_hsl(np.array([rgb[:3]], float))[0][0])


# --------------------------------------------------------------------------- #
# reading                                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('fmt', sorted(dc.COLOUR_FORMATS))
def test_colour_codecs_round_trip_and_keep_alpha(fmt):
    for rgba in PURPLE:
        raw = colour_bytes(fmt, rgba)
        decoded = dc.decode_colour(fmt, raw)
        assert dc.encode_colour(fmt, decoded, raw) == raw
        green = dc.encode_colour(fmt, (20, 220, 40), raw)
        assert len(green) == len(raw) and dc.decode_colour(fmt, green)[3] == decoded[3]


def test_key_streams_decode_grouped_packets_and_encode_back():
    # One packet of three LIN keys (count-1 in the high bits), then an SPL key with a tangent.
    stream = bytes([0x22, 0x80, 10, 0x40, 20, 0x00, 0]) + bytes([0x04, 0x40]) + struct.pack('<f', 0.25) + bytes([0])
    decoded = dc.decode_keys(stream, 0x87, 0x00)
    assert [(k['frame'], k['op'], k['value']) for k in decoded] == [(0, 2, 1.0), (10, 2, 0.5), (30, 2, 0.0),
                                                                    (30, 4, 0.5)]
    assert decoded[3]['tan'] == 0.25
    again = dc.decode_keys(dc.encode_keys(decoded, 0x87, 0x00), 0x87, 0x00)
    assert [(k['frame'], k['op'], k['value'], k['tan']) for k in again] == \
        [(k['frame'], k['op'], k['value'], k['tan']) for k in decoded]


def test_colour_source_classification():
    data = stage(fmt=1, tracks=[(t, 0x87, dc.encode_keys(keys(2, [0, 60], v), 0x87, 0))
                                for t, v in ((4, [1.0, 0.2]), (5, [0.0, 0.5]), (6, [0.0, 0.1]))])
    inv = dc.scan(data)
    first, second = inv.objects
    assert (first.id, second.id) == ('Group 0:0', 'Group 0:1')
    assert first.textures[0]['name'] == 'Group 0 / Texture_0' and first.textures[0]['grey'] is True
    # vertex source over a greyscale texture: the vertex colours hold the colour
    assert dc.colour_from(first, inv.dat) == ('vertex', ['vertex'])
    # the same with a colour texture is a mix
    assert dc.colour_from(first, inv.dat, grey=set()) == ('mixed', ['texture', 'vertex'])
    # material source, colour animated at match start: the keys hold it
    animated = dc.scan(stage(render_flags=0x01, tracks=[(t, 0x87, dc.encode_keys(keys(2, [0, 60], v), 0x87, 0))
                                                        for t, v in ((4, [1.0, 0.2]), (5, [0.0, 0.5]), (6, [0.0, 0.1]))]))
    assert dc.colour_from(animated.objects[0], animated.dat)[0] == 'animation'
    # material source, no animation: a grey material with a grey texture still names the material
    plain = dc.scan(stage(render_flags=0x01))
    assert dc.colour_from(plain.objects[1], plain.dat) == ('material', ['material'])


def test_the_open_tells_the_model_where_colour_comes_from(lab):
    opened = lab.open(stage(fmt=4))
    assert opened['textures'][0]['colour_from'] == 'vertex'
    assert opened['colour_sources'] == {'Group 0': 'vertex 0-1 (0 #591ca2..#c6a2fb, 1 #591ca2..#c6a2fb)'}
    assert 'recolor_vertex' in opened['colour_note']
    listed = run('stage_lab', session_id=opened['session_id'], action='color_sources')
    assert listed['colour_sources'] == opened['colour_sources']


# --------------------------------------------------------------------------- #
# vertex colours                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('fmt', sorted(dc.COLOUR_FORMATS))
@pytest.mark.parametrize('kind', ['direct', 'index'])
def test_vertex_recolor_keeps_format_count_and_alpha(lab, fmt, kind):
    source = stage(fmt=fmt, kind=kind)
    sid = lab.open(source)['session_id']
    result = run('stage_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'material_ids': ['Group 0:0'], 'set_hue': 120, 'set_saturation': 80}])
    assert result['changed'] == {'Group 0:0': 3} and 'viewer_update' not in result and result['checkpoint_file']
    edited = lab.renderers[-1].data
    assert len(lab.renderers) == 2 and lab.renderers[0].closed, 'the session reloaded the edited file'
    assert len(edited) == len(source), 'no buffer grew'
    (fmt_before, count_before, before), = vertex(source, 'Group 0:0')
    (fmt_after, count_after, after), = vertex(edited, 'Group 0:0')
    assert (fmt_after, count_after) == (fmt_before, count_before)
    for old, new in zip(before, after):
        assert new[3] == old[3], 'alpha is kept'
        assert abs(hue(new) - 120) < 12 or max(new[:3]) == min(new[:3])
    assert vertex(edited, 'Group 0:1') == vertex(source, 'Group 0:1'), 'an object not named is untouched'


def test_a_shared_colour_array_is_copied_for_the_chosen_object_only(lab):
    source = stage(fmt=5, kind='index', shared=True)
    before = dc.Dat(source)
    sid = lab.open(source)['session_id']
    run('stage_lab', session_id=sid, action='recolor_vertex',
        edits=[{'material_ids': ['Group 0:1'], 'hue_shift': 180}])
    edited = lab.renderers[-1].data
    after = dc.Dat(edited)
    assert len(edited) > len(source) and after.reloc_count == before.reloc_count
    assert vertex(edited, 'Group 0:0') == vertex(source, 'Group 0:0')
    assert vertex(edited, 'Group 0:1') != vertex(source, 'Group 0:1')


def test_batched_vertex_edits_by_texture_and_group_with_a_mask(lab):
    sid = lab.open(stage(fmt=5))['session_id']
    result = run('stage_lab', session_id=sid, action='recolor_vertex', edits=[
        {'texture_index': 0, 'set_hue': 0, 'set_saturation': 90, 'mask': {'lum_min': 70}},     # the light vertex only
        {'material_ids': ['Group 0'], 'lightness_scale': 0.5}])
    assert result['changed'] == {'Group 0:0': 3, 'Group 0:1': 3}
    (_, _, colours), = vertex(lab.renderers[-1].data, 'Group 0:0')
    assert abs(hue(colours[2]) - 0) < 12 or abs(hue(colours[2]) - 360) < 12
    assert abs(hue(colours[0]) - hue(PURPLE[0])) < 12


def test_objects_that_do_not_take_vertex_colours_are_named(lab):
    sid = lab.open(stage(render_flags=0x01))['session_id']
    result = run('stage_lab', session_id=sid, action='recolor_vertex', edits=[{'material_ids': ['Group 0:0'],
                                                                              'hue_shift': 90}])
    assert result['not_vertex'] == ['Group 0:0'] and result['changed'] == {}
    assert len(lab.renderers) == 1, 'nothing changed: no reload'
    assert 'Unknown material_ids' in run('stage_lab', session_id=sid, action='recolor_vertex',
                                         edits=[{'material_ids': ['Group 7:0'], 'hue_shift': 9}])['error']


# --------------------------------------------------------------------------- #
# animated colours                                                             #
# --------------------------------------------------------------------------- #
def animated_stage():
    frames = [0, 20, 60]
    spline = keys(4, frames, [1.0, 0.5, 1.0], [0.0, 0.01, 0.0])
    return stage(render_flags=0x03, tracks=[
        (4, 0x00, dc.encode_keys(spline, 0x00, 0x00)),                                   # diffuse R, float SPL
        (5, 0x88, dc.encode_keys(keys(2, frames, [0.1, 0.3, 0.1]), 0x88, 0)),            # diffuse G, U8 LIN
        (6, 0x88, dc.encode_keys(keys(2, frames, [0.1, 0.3, 0.1]), 0x88, 0))])           # diffuse B


def tracks_of(data):
    inv = dc.scan(data)
    return {t.channel: t for t in inv.tracks}, inv


def alpha_track(data):
    """The material animation's alpha track (type 10): bytes and keys."""
    dat = dc.Dat(data)
    (_, group), = dc.map_groups(dat)
    node = dc.null_array(dat, dat.ptr(group + 0x08))[0]
    aobj = dat.ptr(dat.ptr(node + 0x08) + 0x04)
    track, = dc._tracks(dat, aobj, ('alpha',), 'material', {10: ('alpha', 0)})
    return dat.raw(track.buffer, track.length), [(k['frame'], k['value']) for k in track.keys]


def test_animated_recolor_changes_key_values_and_keeps_timing_and_alpha(lab):
    source = animated_stage()
    sid = lab.open(source)['session_id']
    result = run('stage_lab', session_id=sid, action='recolor_animated',
                 edits=[{'material_ids': ['Group 0:0'], 'set_hue': 120, 'set_saturation': 80}])
    assert result['changed']['Group 0:0'] > 0 and 'viewer_update' not in result and 'rekeyed' not in result
    edited = lab.renderers[-1].data
    old, _ = tracks_of(source)
    new, inv = tracks_of(edited)
    for channel in (('diffuse', 0), ('diffuse', 1), ('diffuse', 2)):
        assert [(k['frame'], k['op']) for k in new[channel].keys] == [(k['frame'], k['op']) for k in old[channel].keys]
        assert (new[channel].value_flag, new[channel].length) == (old[channel].value_flag, old[channel].length)
    for frame in (0, 20, 60):
        rgb = [dc.sample(new[('diffuse', c)].keys, frame) for c in range(3)]
        assert rgb[1] > rgb[0] and rgb[1] > rgb[2], f'green at frame {frame}: {rgb}'
    assert alpha_track(edited) == alpha_track(source), 'the alpha track is untouched'
    assert all(np.isfinite(k['tan']) for k in new[('diffuse', 0)].keys)
    # The descriptor colour of the animated field follows.
    material = inv.objects[0].material
    assert inv.dat.raw(material + 4, 3) != dc.Dat(source).raw(dc.scan(source).objects[0].material + 4, 3)


def test_channels_keyed_at_different_frames_are_rekeyed_on_the_richest(lab):
    red_pulse = stage(render_flags=0x01, tracks=[
        (4, 0x87, dc.encode_keys(keys(3, [0, 128, 256], [1.0, 0.0, 1.0]), 0x87, 0)),
        (5, 0x88, dc.encode_keys(keys(1, [0, 256], [0.0, 0.0]), 0x88, 0)),
        (6, 0x88, dc.encode_keys(keys(1, [0, 256], [0.0, 0.0]), 0x88, 0))])
    sid = lab.open(red_pulse)['session_id']
    result = run('stage_lab', session_id=sid, action='recolor_animated',
                 edits=[{'material_ids': ['Group 0:0'], 'set_hue': 120, 'set_saturation': 100}])
    assert result['rekeyed'] == ['Group 0:0']
    new, _ = tracks_of(lab.renderers[-1].data)
    assert [k['frame'] for k in new[('diffuse', 1)].keys] == [0, 128, 256]
    assert [round(k['value'], 2) for k in new[('diffuse', 1)].keys] == [1.0, 0.0, 1.0]     # a green pulse
    assert [round(k['value'], 2) for k in new[('diffuse', 0)].keys] == [0.0, 0.0, 0.0]


# --------------------------------------------------------------------------- #
# reset and save                                                               #
# --------------------------------------------------------------------------- #
def test_reset_restores_vertex_colours_and_keys(lab):
    source = animated_stage()
    sid = lab.open(source)['session_id']
    run('stage_lab', session_id=sid, action='recolor_vertex', edits=[{'material_ids': ['Group 0'], 'hue_shift': 90}])
    run('stage_lab', session_id=sid, action='recolor_animated', edits=[{'texture_index': 0, 'hue_shift': 120}])
    edited = lab.renderers[-1].data
    assert vertex(edited, 'Group 0:1') != vertex(source, 'Group 0:1')
    one = run('stage_lab', session_id=sid, action='reset_colors', material_ids=['Group 0:1'])
    assert list(one['restored']) == ['Group 0:1'] and 'viewer_update' not in one
    assert vertex(lab.renderers[-1].data, 'Group 0:1') == vertex(source, 'Group 0:1')
    assert vertex(lab.renderers[-1].data, 'Group 0:0') != vertex(source, 'Group 0:0')
    run('stage_lab', session_id=sid, action='reset_colors')
    restored = lab.renderers[-1].data
    assert vertex(restored, 'Group 0:0') == vertex(source, 'Group 0:0')
    old, _ = tracks_of(source)
    new, inv = tracks_of(restored)
    for channel, track in old.items():
        assert [(k['frame'], k['op'], k['value'], k['tan']) for k in new[channel].keys] == \
            [(k['frame'], k['op'], k['value'], k['tan']) for k in track.keys]
    assert inv.dat.raw(inv.objects[0].material, dc.MATERIAL_SIZE) == \
        dc.Dat(source).raw(dc.scan(source).objects[0].material, dc.MATERIAL_SIZE)


def test_the_saved_variant_carries_the_edit(lab):
    source = stage(fmt=3)
    sid = lab.open(source)['session_id']
    run('stage_lab', session_id=sid, action='recolor_vertex',
        edits=[{'material_ids': ['Group 0'], 'set_hue': 120, 'set_saturation': 70}])
    saved = run('stage_lab', session_id=sid, action='save', name='Green')
    archive = config.STORAGE_PATH / 'das' / saved['folder'] / f"{saved['variantId']}.zip"
    with zipfile.ZipFile(archive) as opened:
        data = opened.read('GrNLa.dat')
    for object_id in ('Group 0:0', 'Group 0:1'):
        (_, count, colours), = vertex(data, object_id)
        assert count == 3 and all(abs(hue(c) - 120) < 15 for c in colours if max(c[:3]) != min(c[:3]))


def test_edits_are_validated_before_anything_changes(lab):
    sid = lab.open(stage())['session_id']
    for edits, message in (([{'hue_shift': 10}], 'material_ids or a texture_index'),
                           ([{'material_ids': ['Group 0:0'], 'texture_index': 0, 'hue_shift': 1}], 'material_ids or'),
                           ([{'material_ids': ['Group 0:0'], 'fields': ['diffuse'], 'hue_shift': 1}], 'material_ids or'),
                           ([{'material_ids': ['Group 0:0'], 'hue_shift': 1, 'mask': {'surrounding': True}}], 'mask')):
        assert message in run('stage_lab', session_id=sid, action='recolor_vertex', edits=edits)['error']
    assert len(lab.renderers) == 1


# --------------------------------------------------------------------------- #
# lights                                                                       #
# --------------------------------------------------------------------------- #
def lit_stage():
    frames = [0, 50, 100]
    return stage(render_flags=0x05, light=((0x4B, 0x25, 0x9D, 0xFF), [
        (9, 0x88, dc.encode_keys(keys(2, frames, [0.29, 0.17, 0.29]), 0x88, 0)),
        (10, 0x88, dc.encode_keys(keys(2, frames, [0.15, 0.08, 0.15]), 0x88, 0)),
        (11, 0x88, dc.encode_keys(keys(2, frames, [0.61, 0.73, 0.61]), 0x88, 0))]))


def test_coloured_lights_are_evidence_and_recolor_like_the_rest(lab):
    source = lit_stage()
    opened = lab.open(source)
    assert opened['colour_sources']['lights'] == '2 lit objects; Group 0 light 0 #4b259d animated (recolor_lights)'
    sid = opened['session_id']
    assert 'Unknown lights' in run('stage_lab', session_id=sid, action='recolor_lights',
                                   edits=[{'lights': ['Group 9 light 0'], 'hue_shift': 10}])['error']
    result = run('stage_lab', session_id=sid, action='recolor_lights',
                 edits=[{'lights': ['Group 0 light 0'], 'set_hue': 120, 'set_saturation': 60}])
    assert result['changed'] == {'Group 0 light 0': 10} and 'viewer_update' not in result
    inv = dc.scan(lab.renderers[-1].data)
    (light,) = inv.lights
    r, g, b, a = light['rgba']
    assert g > r and g > b and a == 0xFF
    for frame in (0, 50, 100):
        rgb = [dc.sample(t.keys, frame) for t in sorted(light['tracks'], key=lambda t: t.channel[1])]
        assert rgb[1] > rgb[0] and rgb[1] > rgb[2]
    run('stage_lab', session_id=sid, action='reset_colors')
    (restored,) = dc.scan(lab.renderers[-1].data).lights
    (original,) = dc.scan(source).lights
    assert restored['rgba'] == original['rgba']
    assert [[k['value'] for k in t.keys] for t in restored['tracks']] ==         [[k['value'] for k in t.keys] for t in original['tracks']]
