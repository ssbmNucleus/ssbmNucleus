"""Final Destination's sky through the identify render and the recolour that follows it (2026-11-18).

FD's sky (texture 5) is an I8 texture over vertex colours, its nebula blends additively over it and
its groups have fog, so the id render read it as nothing: an id painted into an I8 slot loses its
hue, and the material colour, the blend and the fog tinted what was left. And the table ranked the
side walls first because the raised view looks down on them. Covered here:

* `_plan`: a lightness-only texture's id rides on its objects (their vertex colours, else their
  material), and `_as_stored` quantises it in the carrier's vertex format;
* `_id_copy`: the file the id render paints over, every other colour source neutral;
* `view_area`: a stage's backdrop is ranked by the game camera;
* `set_hue` with `saturation_shift` (and `hue_shift` with `set_saturation`) as one change.

The stage files are the synthetic archives of test_stage_colours; nothing renders.
"""
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from randall.recolor import lab_common, model_colours, texture_inspection as ti
from shared.rendering import dat_colours as dc, palette
from tests.backend.test_stage_colours import hue, keys, lab, run, stage, vertex  # noqa: F401 (lab: fixture)

VIEWER = SimpleNamespace(textures=[{'index': 0, 'name': 'Group 0 / Texture_0', 'matAnim': False}])
ADDITIVE = (0x19, 0, 0, 0, 1, 4, 1, 5, 3, 7, 0, 7)       # FD's nebula: blend SRCALPHA / ONE
COLOUR_AND_ALPHA_TEV = ti.COLOR_TEV | 1 << 31


def plan_of(data):
    return ti._plan(VIEWER, dc.scan(data))


# --------------------------------------------------------------------------- #
# a lightness-only slot                                                        #
# --------------------------------------------------------------------------- #
def test_an_i8_texture_over_vertex_colours_takes_its_id_through_them():
    plan = plan_of(stage())          # object 0: an I8 texture over vertex colours, as FD's sky
    assert plan['intensity'] == {0}
    assert plan['keys'] == [0, 'Group 0:1']
    assert plan['texture'] == {0: 0}
    assert plan['vertex'] == {'Group 0:0': 0, 'Group 0:1': 'Group 0:1'}
    assert plan['material'] == {}


def test_an_i8_texture_without_vertex_colours_takes_its_id_through_its_material():
    plan = plan_of(stage(render_flags=0x01))
    assert plan['intensity'] == {0}
    assert plan['vertex'] == {}
    assert plan['material'] == {'Group 0:0': 0, 'Group 0:1': 'Group 0:1'}


def test_a_texture_id_carried_by_vertex_colours_is_decoded_as_they_store_it():
    plan = plan_of(stage(fmt=3))     # RGBA4 vertex colours: 4 bits a channel
    ids = np.array([[100, 50, 7], [10, 20, 30]], np.uint8)
    stored = ti._as_stored(plan, ids)
    assert stored[0].tolist() == [102, 51, 0]
    assert stored[1].tolist() == [17, 17, 34]


def test_a_colour_texture_keeps_its_own_id():
    inv = dc.scan(stage())
    image = inv.dat.ptr(inv.objects[0].textures[0]['tobj'] + 0x4C)
    inv.dat.put(image + 8, (6).to_bytes(4, 'big'))           # RGBA8: the slot holds the id's hue itself
    plan = ti._plan(VIEWER, dc.scan(inv.dat.data()))
    assert plan['intensity'] == set()
    assert plan['vertex'] == {'Group 0:0': None, 'Group 0:1': 'Group 0:1'}


# --------------------------------------------------------------------------- #
# the id copy                                                                  #
# --------------------------------------------------------------------------- #
def busy_stage():
    """Object 0: an I8 texture under FD's sky diffuse, an additive blend, a BLEND colour map with its own TEV
    and a diffuse/specular animation; object 1 rests at alpha 0 (FD's edge lines); a lit fog group."""
    frames = [0, 50, 100]
    data = stage(render_flags=0x01, pe=ADDITIVE, colormap=3, tev=COLOUR_AND_ALPHA_TEV, fog=(1, (0x30, 0x10, 0x60, 0xFF)),
                 tracks=[(4, 0x88, dc.encode_keys(keys(2, frames, [0.2, 0.4, 0.2]), 0x88, 0)),
                         (5, 0x88, dc.encode_keys(keys(2, frames, [0.1, 0.3, 0.1]), 0x88, 0)),
                         (6, 0x88, dc.encode_keys(keys(2, frames, [0.6, 0.9, 0.6]), 0x88, 0)),
                         (7, 0x88, dc.encode_keys(keys(2, frames, [0.5, 0.5, 0.5]), 0x88, 0))],
                 light=((0x4B, 0x25, 0x9D, 0xFF), [
                     (9, 0x88, dc.encode_keys(keys(2, frames, [0.29, 0.17, 0.29]), 0x88, 0)),
                     (10, 0x88, dc.encode_keys(keys(2, frames, [0.15, 0.08, 0.15]), 0x88, 0)),
                     (11, 0x88, dc.encode_keys(keys(2, frames, [0.61, 0.73, 0.61]), 0x88, 0))]))
    inv = dc.scan(data)
    sky, line = (o.material for o in inv.objects)
    inv.dat.put(sky + 0x04, bytes((0x33, 0x1E, 0xA1, 0xFF)))
    inv.dat.put(line + 0x04, bytes((0xFF, 0x00, 0xFF, 0x00)))
    inv.dat.put(line + 0x0C, struct.pack('>f', 0.0))
    return inv.dat.data()


def test_the_id_copy_leaves_only_the_id_colour():
    source = busy_stage()
    plan = plan_of(source)
    colour = {0: (100, 50, 7), 'Group 0:1': (10, 20, 30)}
    copy = ti._id_copy(source, plan, colour)
    inv = dc.scan(copy)
    dat = inv.dat
    sky, line = inv.objects
    # Materials: ambient white, diffuse the id it carries, specular black; opaque stays opaque.
    assert dat.raw(sky.material, 12) == bytes((255, 255, 255, 255, 100, 50, 7, 255, 0, 0, 0, 255))
    assert dat.f32(sky.material + 0x0C) == 1.0
    # Below the alpha cut it stays clear: an alpha animation shows it (FD's lines fade in).
    assert dat.raw(line.material + 0x04, 4) == bytes((10, 20, 30, 0)) and dat.f32(line.material + 0x0C) == 0.0
    # The plain alpha blend, a MODULATE colour map, no colour TEV (its alpha TEV stays), no fog.
    pe = dat.ptr(sky.mobj + 0x14)
    assert tuple(dat.raw(pe + 4, 3)) == ti.ID_BLEND and dat.raw(pe, 4) == bytes(ADDITIVE[:4])
    tobj = sky.textures[0]['tobj']
    assert sky.textures[0]['colormap'] == 'modulate'
    assert dat.u32(dat.ptr(tobj + 0x58) + 0x1C) == 1 << 31
    assert [f['type'] for f in inv.fogs] == [0] and inv.fogs[0]['rgba'] == (0x30, 0x10, 0x60, 0xFF)
    # Lights grey at their brightest channel, their keys too.
    (light,) = inv.lights
    assert light['rgba'] == (0x9D, 0x9D, 0x9D, 0xFF)
    assert all(abs(k['value'] - 0.73) < 2 / 256 for t in light['tracks'] for k in t.keys)
    # Material colour keys say what the descriptor says, at the same frames.
    tracks = {t.channel: t for t in sky.tracks}
    for channel, value in ((('diffuse', 0), 100 / 255), (('diffuse', 1), 50 / 255), (('diffuse', 2), 7 / 255),
                           (('specular', 0), 0.0)):
        assert all(abs(k['value'] - value) < 2 / 256 for k in tracks[channel].keys), channel
        assert [k['frame'] for k in tracks[channel].keys] == [0, 50, 100]
    # Vertex colours and texture pixels are painted through the renderer, not here; the source is untouched.
    assert vertex(copy, 'Group 0:0') == vertex(source, 'Group 0:0')
    assert len(copy) == len(source) and dc.scan(source).dat.raw(sky.material + 4, 3) == bytes((0x33, 0x1E, 0xA1))


@pytest.mark.parametrize('carrier', ['Group 0:0', 'Group 0:1'])
def test_a_shared_material_keeps_the_id_it_carries(carrier):
    inv = dc.scan(stage(render_flags=0x01))
    first, second = inv.objects
    inv.dat.put(second.mobj + 0x0C, first.material.to_bytes(4, 'big'))     # both objects on one material
    source = inv.dat.data()
    plan = dict(plan_of(source), material={carrier: carrier})             # only one of them carries an id
    copy = dc.scan(ti._id_copy(source, plan, {carrier: (100, 50, 7)}))
    assert copy.dat.raw(first.material + 4, 3) == bytes((100, 50, 7))


def test_an_unreadable_file_has_no_id_copy():
    assert ti._id_copy(b'not a dat', {'material': {}}, {}) is None


# --------------------------------------------------------------------------- #
# ranking                                                                      #
# --------------------------------------------------------------------------- #
def test_a_stage_backdrop_is_ranked_by_the_game_camera():
    walls, sky = [0.115, 0.648, 0.0], [0.56, 0.20, 0.0]       # FD, 2026-11-18: game camera, raised, zoom
    assert ti.view_area(walls, 'stage') == 0.115
    assert ti.view_area(sky, 'stage') > ti.view_area(walls, 'stage')
    assert ti.view_area([0.0, 0.03, 0.01], 'stage') == 0.03   # a platform top the game camera does not show
    assert ti.view_area([0.2, 0.3], 'costume') == 0.3         # front and back are both seen in game
    assert 'game-camera share' in ti.VIEWS_NOTE.format(area=ti.VIEWS_AREA['stage'])


# --------------------------------------------------------------------------- #
# set one, shift the other                                                     #
# --------------------------------------------------------------------------- #
def test_an_exact_value_of_one_and_a_shift_of_the_other_is_one_change():
    assert lab_common.colour_change({'set_hue': 290, 'saturation_shift': -20}) == (290, -20, 'set_hue', 1)
    assert lab_common.colour_change({'hue_shift': 200, 'set_saturation': 40, 'lightness_scale': 0.8}) == \
        (-160, 40, 'set_saturation', 0.8)
    assert lab_common.colour_change({'set_hue': 290}) == (290, 60, 'set', 1)
    for both, field in (({'set_hue': 290, 'hue_shift': 10}, 'hue'), ({'set_saturation': 4, 'saturation_shift': 5},
                                                                     'saturation')):
        with pytest.raises(ValueError, match=f'either {field}_shift or set_{field}'):
            lab_common.colour_change(both)
    assert lab_common.adds_colour((290, 10, 'set_hue', 1)) and not lab_common.adds_colour((290, 0, 'set_hue', 1))


def hsl(rgb):
    h, s, l = palette.rgb_to_hsl(np.asarray(rgb, float).reshape(1, 3))
    return float(h[0]), float(s[0]), float(l[0])


@pytest.mark.parametrize('value, want', [((290, -20, 'set_hue', 1), (290, 40, 50)),
                                         ((-40, 30, 'set_saturation', 1), (300, 30, 50)),
                                         ((290, 0, 'set_hue', 1), (290, 60, 50))])
def test_textures_and_colour_keys_set_one_channel_and_shift_the_other(value, want):
    base = np.array([[204, 51, 102]], float)      # hue 340, saturation 60, lightness 50
    assert [round(v) for v in hsl(base[0])] == [340, 60, 50]
    pixels = np.concatenate([base, [[255]]], 1).astype(np.uint8).reshape(1, 1, 4)
    out = palette.apply_adjustments(pixels, np.zeros(1, np.uint8), {0: value})
    assert out is not None, 'a value that sets something changes even with nothing to shift'
    got = hsl(out.reshape(-1, 4)[0, :3])
    assert abs(got[0] - want[0]) < 2 and abs(got[1] - want[1]) < 2 and abs(got[2] - want[2]) < 2
    keyed = model_colours.apply(base[0] / 255, value).reshape(-1)
    got = hsl(keyed * 255)
    assert abs(got[0] - want[0]) < 1 and abs(got[1] - want[1]) < 1


def test_a_set_hue_with_a_saturation_shift_recolours_vertex_colours(lab):
    sid = lab.open(stage())['session_id']
    result = run('stage_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'material_ids': ['Group 0'], 'set_hue': 290, 'saturation_shift': 10}])
    assert 'error' not in result, result
    for object_id in ('Group 0:0', 'Group 0:1'):
        (_, count, colours), = vertex(lab.renderers[-1].data, object_id)
        assert count == 3 and all(abs(hue(c) - 290) < 3 for c in colours if max(c[:3]) != min(c[:3]))
