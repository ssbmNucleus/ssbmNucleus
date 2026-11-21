"""An Ultimate effect's 3D shapes and several pictures made into the one flat picture a Melee particle draws: the
shape reader on real files (Greninja's and Duck Hunt's), `fighter_port.effect_shapes` on small made-up shapes and
pictures, and the effect plan carrying shapes as STAND-INS. The real files come from ULTIMATE_DUMP."""
import math
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from echo_ultimate import effects
from fighter_port import effect_shapes as fs
from fighter_port import own_effects as oe
from fighter_port.own_route import effect_counts

DUMP = os.environ.get('ULTIMATE_DUMP')


def effect_file(fighter):
    return Path(DUMP) / 'gamedata' / 'effect' / 'fighter' / fighter / f'ef_{fighter}.eff' if DUMP else None


def needs(fighter):
    path = effect_file(fighter)
    return pytest.mark.skipif(not (path and path.exists()), reason=f"needs ULTIMATE_DUMP with {fighter}'s effect file")


def particle_data(fighter):
    return effects.particle_data(effect_file(fighter).read_bytes())


# ---- the reader ----

@needs('gekkouga')
def test_greninjas_shapes_are_read_one_for_each_model_number():
    v = particle_data('gekkouga')
    shapes = effects.shapes(v)
    assert len(shapes) == len(effects.shape_numbers(v)) == 35
    for shape in shapes.values():
        n = len(shape['positions'])
        assert shape['positions'].shape == (n, 3) and shape['uvs'].shape == (n, 2) and shape['colours'].shape == (n, 4)
        assert shape['triangles'].min() >= 0 and shape['triangles'].max() < n and np.isfinite(shape['positions']).all()
    by_name = {s['name']: s for s in shapes.values()}
    kunai = by_name['p_gekkougasword_kunai1']
    low, high = kunai['positions'].min(axis=0), kunai['positions'].max(axis=0)
    assert len(kunai['positions']) == 692 and len(kunai['triangles']) == 1064
    assert high[1] - low[1] > 5 * (high[0] - low[0])                      # a blade, long along +y
    assert high[1] == pytest.approx(13.18, abs=0.01) and low[1] == pytest.approx(-4.65, abs=0.01)
    ring = by_name['p_gekkougamizusyuriken_ring1']['positions']             # the shuriken's ring lies in XZ
    assert np.allclose(ring[:, 1], 0.0) and np.ptp(ring[:, 0]) > 19 and np.ptp(ring[:, 2]) > 19
    flat = by_name['p_gekkougamizusyurikenhold_ring1']['positions']         # the held one's, in XY
    assert np.allclose(flat[:, 2], 0.0)
    # every emitter that draws on a shape names one of them
    for rows in effects.effects(v).values():
        for row in rows:
            number = effects.model(v, row['binary'])
            assert number is None or number in shapes


@needs('duckhunt')
def test_duck_hunts_fourteen_shapes_cover_every_emitter_that_draws_on_one():
    v = particle_data('duckhunt')
    shapes = effects.shapes(v)
    named = [effects.model(v, row['binary']) for rows in effects.effects(v).values() for row in rows]
    named = [n for n in named if n is not None]
    assert len(shapes) == 14 and len(named) == 41 and set(named) <= set(shapes)
    ring = next(s for s in shapes.values() if s['name'] == 'p_cmnhitfire_ring1')
    radius = np.hypot(ring['positions'][:, 0], ring['positions'][:, 1])
    assert np.allclose(ring['positions'][:, 2], 0.0) and radius.max() == pytest.approx(11.2, abs=0.2)
    assert np.ptp(ring['uvs'][:, 0]) == pytest.approx(4.0, abs=0.05)         # its picture goes round it four times


@needs('pzenigame')
def test_squirtles_withdraw_reads_as_three_pictures_joined_and_a_refraction():
    v = particle_data('pzenigame')
    rows = {effects.emitter(v, r['binary'])['name']: r for r in effects.effects(v)['P_PZenigameKaranikomoruLine']}
    wave, bend = rows['waveline1']['binary'], rows['rifraction1']['binary']
    assert effects.draw_type(v, wave) == 'billboard' and effects.shader_mode(v, wave) == 'plain'
    assert effects.combiner(v, wave) == dict(colour=['multiply', 'multiply'], alpha=['add', 'multiply'])
    assert effects.shader_mode(v, bend) == 'refraction'
    assert effects.bends('ef_cmn_indirect00') and not effects.bends('ef_pzenigame_waveline00')


# ---- joining pictures ----

def square(colour, size=16, alpha=255):
    return Image.new('RGBA', (size, size), tuple(colour) + (alpha,))


def disc(size=32, colour=(255, 255, 255)):
    y, x = np.mgrid[0:size, 0:size]
    r = np.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) / (size / 2)
    a = np.clip(1.0 - r, 0.0, 1.0) * 255
    pixels = np.dstack([np.full((size, size), c) for c in colour] + [a]).astype(np.uint8)
    return Image.fromarray(pixels, 'RGBA')


def test_pictures_are_joined_by_their_combiner_and_a_grey_opaque_one_is_a_mask():
    red, half = square((255, 0, 0), alpha=200), square((128, 128, 128))
    joined = np.asarray(fs.join([red, half], colour=('multiply',), alpha=('multiply',)))
    # the grey picture is a mask: it takes alpha by its brightness and leaves the colour
    assert tuple(joined[0, 0]) == pytest.approx((255, 0, 0, 100), abs=2)
    added = np.asarray(fs.join([square((100, 0, 0), alpha=100), square((0, 100, 0), alpha=100)],
                               colour=('add',), alpha=('add',)))
    assert tuple(added[0, 0]) == pytest.approx((100, 100, 0, 200), abs=2)
    # a later picture is stretched over each frame of the first's grid
    sheet = Image.new('RGBA', (32, 16), (255, 255, 255, 255))
    out = np.asarray(fs.join([sheet, disc(8)], grid=(2, 1)))
    assert out[8, 8, 3] > 200 and out[8, 24, 3] > 200 and out[0, 0, 3] < 10 and out[0, 16, 3] < 10


def test_a_square_and_a_dark_box_are_found_and_given_a_stand_in_that_is_neither():
    assert fs.draws_square(square((255, 255, 255), 32))[0] == 'square'
    assert fs.draws_square(disc())[0] is None
    dark = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    dark.paste(square((30, 30, 40), 24, 160), (4, 4))
    assert fs.draws_square(dark)[0] == 'dark' and fs.draws_square(dark, additive=True)[0] is None
    cut = np.asarray(fs.stand_in(square((255, 255, 255), 32)))
    assert cut[0, 0, 3] == 0 and cut[16, 16, 3] > 240                        # round: no corners
    clear = np.asarray(fs.stand_in(dark, cut_round=False))
    assert clear[16, 16, 3] < 0.25 * 160                                     # the dark is made see-through


# ---- a shape as a flat picture ----

def quad(z=0.0):
    """A square two units a side in the XY plane, its picture's UVs over it, top left at (-1, 1)."""
    return dict(name='quad', positions=np.array([[-1, 1, z], [1, 1, z], [1, -1, z], [-1, -1, z]], float),
                uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float), colours=np.ones((4, 4)),
                triangles=np.array([[0, 1, 2], [0, 2, 3]]))


def test_the_view_is_from_the_side_for_a_laid_shape_and_from_the_front_for_one_that_faces_the_camera():
    points = np.array([[0.0, 0.0, 5.0], [0.0, 3.0, 0.0], [2.0, 0.0, 0.0]])
    across, up, _ = fs.view(points, 'polygon_xy')
    assert across[0] == pytest.approx(5.0) and up[1] == pytest.approx(3.0 * math.cos(math.radians(fs.CAMERA_PITCH_DEGREES)))
    assert across[2] == pytest.approx(0.0)                                   # +x runs away from the camera
    across, up, _ = fs.view(points, 'billboard')
    assert across[2] == pytest.approx(2.0) and up[1] == pytest.approx(3.0) and across[0] == pytest.approx(0.0)
    # a ring in XY laid flat, face up, shows from the side as a thin ellipse
    ring = np.array([[math.cos(a), math.sin(a), 0.0] for a in np.linspace(0, 2 * math.pi, 16)])
    across, up, _ = fs.view(ring, 'polygon_xz')
    assert np.ptp(across) == pytest.approx(2.0, abs=0.05) and np.ptp(up) < 0.4
    # the same turn as own_effects._turned, for many points
    turn = (0.3, -0.7, 1.1)
    assert fs.turned(points, turn)[0] == pytest.approx(oe._turned(points[0], turn))


def test_a_shape_is_drawn_with_its_picture_on_it():
    picture = Image.new('RGBA', (8, 8), (255, 0, 0, 255))
    picture.paste((0, 0, 255, 255), (0, 0, 4, 8))                            # left half blue, right half red
    out = np.asarray(fs.flatten(quad(), picture, 'billboard', half=2.0, side=32))
    assert tuple(out[16, 12]) == (0, 0, 255, 255) and tuple(out[16, 20]) == (255, 0, 0, 255)
    assert out[2, 2, 3] == 0                                                 # outside the quad, seen through
    # seen from the side, a quad in XY is edge-on: nothing
    assert np.asarray(fs.flatten(quad(), picture, 'polygon_xy', half=2.0, side=32))[..., 3].max() == 0
    # added: two quads one behind the other add up
    two = quad()
    two.update(positions=np.vstack([two['positions'], two['positions'] - [0, 0, 1]]), uvs=np.vstack([two['uvs']] * 2),
               colours=np.ones((8, 4)) * [1, 1, 1, 0.25], triangles=np.vstack([two['triangles'], two['triangles'] + 4]))
    grey = Image.new('RGBA', (4, 4), (255, 255, 255, 255))
    added = np.asarray(fs.flatten(two, grey, 'billboard', half=2.0, side=16, additive=True))
    laid = np.asarray(fs.flatten(two, grey, 'billboard', half=2.0, side=16))
    assert float(added[8, 8, 3]) * float(added[8, 8, 0]) / 255.0 == pytest.approx(128, abs=2) and laid[8, 8, 3] == pytest.approx(112, abs=2)
    # what is added is stored with its colour equal to its alpha where it is grey: one byte a pixel (I8)
    assert added[8, 8, 0] == pytest.approx(added[8, 8, 3], abs=1)
    assert oe.picture_format(Image.fromarray(added)) == oe.I8


def test_a_beam_seen_from_the_side_is_drawn_two_pixels_thick():
    beam = quad()
    beam['positions'] = np.array([[0, 0.001, 0], [0, 0.001, 10], [0, -0.001, 10], [0, -0.001, 0]], float)
    out = np.asarray(fs.flatten(beam, Image.new('RGBA', (4, 4), (255,) * 4), 'polygon_xy', half=10.0, side=64))
    assert out[..., 3].max() == 255 and (out[..., 3] > 0).any(axis=1).sum() >= 1


def test_convert_lays_a_picture_along_its_speed_when_asked():
    e = dict(name='x', colour_keys=[], alpha_keys=[], colour2_keys=[], alpha2_keys=[], size_keys=[],
             colour=(1, 1, 1, 1), colour2=(1, 1, 1, 1), size=(2, 2, 2), size_random=(0, 0, 0), life=10, life_random=0,
             blend='normal', textures=[1], grid=(1, 1), frames='one', frame_table=[], frames_random=0, one_time=True,
             start=0, loop=0, emit_frames=1, rate=1.0, shape='point', radius=(0, 0, 0), speed=0.0, speed_along=0.01,
             direction=(0, 1, 0), spread_degrees=0, speed_random=0, gravity=0, gravity_direction=(0, -1, 0), drag=1,
             turn=(0, 0, 0), turn_random=(0, 0, 0), spin=(0, 0, 0), spin_random=(0, 0, 0), spin_keep=1)
    got = oe.convert(e, images=1, along_speed=True)
    assert (oe.ALONG_SPEED, []) in got['commands'] and math.hypot(*got['header']['velocity']) >= oe.LEAST_SPEED
    assert (oe.ALONG_SPEED, []) not in oe.convert(e, images=1)['commands']


# ---- the plan ----

@needs('duckhunt')
def test_duck_hunts_can_explosion_ring_is_a_flattened_stand_in_shared_by_its_two_emitters():
    plan = oe.Plan(effect_file('duckhunt'), 0.9698)
    uses = plan.use('duckhunt_trick_bomb', 1.0)
    rows = {r['emitter']: r for r in plan.report()['sets']['P_DuckhuntTrickBomb']}
    ring, base = rows['ring1'], rows['ring1_base']
    assert ring['carried'] and base['carried'] and 'STAND-IN' in ring['stand_in'][0] and 'p_cmnhitfire_ring1' in ring['stand_in'][0]
    a, b = (oe.read_generator(plan.generators[r['generators'][0]]) for r in (ring, base))
    assert a['tex_group'] == b['tex_group']                                # one picture for the shape and picture
    group = plan.groups[a['tex_group']]
    assert len(group['images']) == 4                                       # its picture's four frames, each drawn on it
    assert 'flattened' in plan.group_labels[a['tex_group']]
    # drawn as wide as the ring is at its largest: its model is 22.4 units across, sized by the emitter's size keys
    e = effects.emitter(plan.v, next(r for r in plan.sets['P_DuckhuntTrickBomb']
                                     if effects.emitter(plan.v, r['binary'])['name'] == 'ring1')['binary'])
    largest = max(max(abs(float(k['value'][0])), abs(float(k['value'][1]))) for k in e['size_keys'] or [dict(value=(1, 1))])
    drawn = max([a['size']] + [c[1][1] for c in a['commands'] if c[0] == oe.SIZE])
    assert drawn == pytest.approx(11.2 * float(e['size'][0]) * largest * 0.9698, rel=0.03)
    counts = effect_counts(plan.report())
    assert counts['shapes']['carried'] >= 4 and 'P_DuckhuntTrickBomb' in counts['stand_ins']
    assert len(uses) == len([r for r in rows.values() if r['carried']])


@needs('gekkouga')
def test_refractions_are_left_out_and_a_map_of_offsets_is_not_drawn():
    plan = oe.Plan(effect_file('gekkouga'), 1.0)
    plan.use('P_GekkougaSword', 1.0)
    plan.use('P_GekkougaMizusyuriken', 1.0)
    rows = {r['emitter']: r for r in plan.report()['sets']['P_GekkougaMizusyuriken']}
    bend = rows['syuriken1_zanzo_indirect1']
    assert not bend['carried'] and 'refraction' in bend['not_carried'][0] and bend['pictures']['got'] == 'left out'
    water = {r['emitter']: r for r in plan.report()['sets']['P_GekkougaSword']}['kunai_water1']
    assert water['carried'] and water['pictures']['drawn'] == 1                # its cmn_indirect00 is the map
    label = plan.group_labels[oe.read_generator(plan.generators[water['generators'][0]])['tex_group']]
    assert 'indirect' not in label and 'water00' in label


@needs('pzenigame')
def test_squirtles_withdraw_wall_is_no_longer_its_first_picture_alone():
    plan = oe.Plan(effect_file('pzenigame'), 1.0)
    plan.use('P_PZenigameKaranikomoruLine', 1.0)
    row = {r['emitter']: r for r in plan.report()['sets']['P_PZenigameKaranikomoruLine']}['waveline1']
    assert row['carried'] and row['pictures']['got'] in ('combined', 'stand-in')
    group = plan.groups[oe.read_generator(plan.generators[row['generators'][0]])['tex_group']]
    shown = oe.decode_image(group['images'][0], group['format'], group['width'], group['height'])
    assert fs.draws_square(shown)[0] is None                               # no square, no dark box
    assert not any('more picture' in text for text in row['not_carried'])


@needs('duckhunt')
def test_a_shape_the_port_stands_in_for_by_hand_is_not_flattened_too():
    plan = oe.Plan(effect_file('duckhunt'), 1.0)
    plan.by_hand('duckhunt_trick_bomb', 'ring1')
    plan.use('duckhunt_trick_bomb', 1.0)
    rows = {r['emitter']: r for r in plan.report()['sets']['P_DuckhuntTrickBomb']}
    assert not rows['ring1']['carried'] and 'its own stand-in' in rows['ring1']['not_carried'][0]
    assert rows['ring1_base']['carried']
    with pytest.raises(ValueError):
        plan.by_hand('duckhunt_trick_bomb', 'ring1_base')                  # already flattened: said too late


@needs('duckhunt')
def test_a_bank_too_big_is_fitted_by_halving_the_flattened_shapes_first():
    plan = oe.Plan(effect_file('duckhunt'), 1.0)
    plan.use('duckhunt_trick_bomb', 1.0)
    plan.use('duckhunt_atk_smoke_r', 1.0)
    kinds = [s['kind'] for s in plan._sources]
    assert 'shape' in kinds and 'plain' in kinds
    before = [dict(g) for g in plan.groups]
    full = len(oe.texture_bank(plan.groups))
    cost = lambda g: len(g['images']) * oe.image_bytes(g['format'], g['width'], g['height'])
    shape = max((i for i, k in enumerate(kinds) if k == 'shape'), key=lambda i: (cost(before[i]), -i))
    fitted = plan.fit(full - 1)                                            # one byte too many: one halving
    assert fitted == [plan.group_labels[shape]] and plan.groups[shape]['width'] == before[shape]['width'] // 2
    assert len(plan.groups[shape]['images']) == len(before[shape]['images'])           # its frames kept
    assert all(plan.groups[i] == before[i] for i, k in enumerate(kinds) if k != 'shape')  # the rest as they were
    assert len(oe.texture_bank(plan.groups)) < full and plan.report()['fitted'] == fitted
    # with no limit to reach it halves nothing below FIT_LEAST_SIDE
    plan.fit(0)
    assert all(max(g['width'], g['height']) >= oe.FIT_LEAST_SIDE or max(b['width'], b['height']) < 2 * oe.FIT_LEAST_SIDE
               for g, b in zip(plan.groups, before))


@needs('gekkouga')
def test_a_held_shape_laid_along_its_speed_is_given_off_anew_turned_as_the_joint_is():
    # Greninja's water blades: held at the hand, laid along a speed that, in Ultimate, is in the hand's own space
    plan = oe.Plan(effect_file('gekkouga'), 0.9698)
    held = dict((n, b) for _, n, b in plan.use('gekkouga_sword', 1.0, follow=True))
    loose = dict((n, b) for _, n, b in plan.use('gekkouga_sword', 1.0, follow=False))
    rows = {r['emitter']: r for r in plan.report()['sets']['P_GekkougaSword']}
    blade = rows['kunai1']['generators'][0]
    assert held[blade] == oe.TURNED_BEHAVIOUR and oe.TURNED_BEHAVIOUR in oe.ATTACHED
    g = oe.read_generator(plan.generators[blade])
    assert g['life'] == oe.RENEWED_LIFE and g['random'] == -1.0 and g['gen_life'] == 100     # one a frame, for its life
    assert any(c[0] == oe.ALONG_SPEED for c in g['commands'])
    assert plan.ends(blade)                                                # it ends by itself, as the emitter does
    assert set(loose.values()) <= {oe.BURST_BEHAVIOUR, oe.STEADY_BEHAVIOUR}  # given off where it was called: as before
    splash = rows['shibuki1']['generators'][0]
    assert held[splash] == oe.STEADY_BEHAVIOUR                              # a flat emitter held: as before


@needs('gekkouga')
def test_a_shape_drawn_wider_than_all_the_camera_shows_is_not_carried():
    # Greninja's Water Shuriken hold: a flare of size 45 on cmn_flare1 (49 across) read 2,140 across and tinted the
    # whole screen while he held it; the thrown shuriken's flare, the same shape at size 0.7, is carried as before
    plan = oe.Plan(effect_file('gekkouga'), 0.9698)
    plan.use('gekkouga_mizusyuriken_hold', 1.0, follow=True)
    plan.use('gekkouga_mizusyuriken', 1.0)
    report = plan.report()
    hold = {r['emitter']: r for r in report['sets']['P_GekkougaMizusyurikenHold']}
    assert not hold['flare1']['carried'] and not hold['flare1']['generators']
    assert 'wider than all the camera shows' in hold['flare1']['not_carried'][0]
    said = hold['flare1']['not_carried'][0]
    assert 2100 < int(said.split(' would be drawn ')[1].split(' across')[0].replace(',', '')) < 2200
    assert '(size 45)' in said and 'stand_in' not in hold['flare1']
    assert hold['wakka1']['carried']                                       # the held ring beside it: flattened
    thrown = {r['emitter']: r for r in report['sets']['P_GekkougaMizusyuriken']}
    assert thrown['flare1']['carried'] and thrown['flare1']['stand_in']
    counts = effect_counts(report)['shapes']
    assert any('wider than all the camera shows' in why for why in counts['why'])
    # called at a fifth of its size it fits (428 across): the rule is the width drawn, not the emitter
    small = oe.Plan(effect_file('gekkouga'), 0.9698)
    small.use('gekkouga_mizusyuriken_hold', 0.2, follow=True)
    row = {r['emitter']: r for r in small.report()['sets']['P_GekkougaMizusyurikenHold']}['flare1']
    assert row['carried'] and row['generators']


def test_a_grey_opaque_picture_with_a_see_through_edge_is_still_a_mask():
    # a white-to-black gradient, opaque but for its outermost ring of pixels (as ef_cmn_grade00: 219 of 255)
    pixels = np.zeros((16, 16, 4), np.uint8)
    pixels[..., :3] = np.linspace(255, 0, 16, dtype=np.uint8)[:, None, None]
    pixels[..., 3] = 255
    pixels[0, :, 3] = pixels[-1, :, 3] = pixels[:, 0, 3] = pixels[:, -1, 3] = 219
    grade = Image.fromarray(pixels, 'RGBA')
    assert fs.is_mask(np.asarray(grade, np.float32) / 255.0)
    assert oe.picture_format(grade) == oe.IA8                                # drawn alone: by its own alpha, as before
    joined = np.asarray(fs.join([square((255, 0, 0)), grade], colour=('multiply',), alpha=('multiply',)))
    assert joined[1, 8, 3] > 200 and joined[14, 8, 3] < 40 and joined[14, 8, 0] == 255   # see-through by brightness
    # see-through one pixel inside the ring: an alpha of its own, as before
    pixels[1, 1, 3] = 219
    inside = Image.fromarray(pixels, 'RGBA')
    assert not fs.is_mask(np.asarray(inside, np.float32) / 255.0)


@needs('gaogaen')
def test_a_flare_drawn_normally_on_its_disc_is_a_glow_and_not_a_dark_disc():
    # Incineroar's Revenge: cmn_flare1 with ef_cmn_grade00, laid over him normally. Read as a picture with an alpha of
    # its own, its black was opaque and the flattened disc darkened half the screen; read as a mask, it is a glow
    plan = oe.Plan(effect_file('gaogaen'), 1.0)
    plan.pictures()
    grade = next(image for name, image in plan._pictures.values() if name == 'ef_cmn_grade00')
    assert fs.is_mask(np.asarray(grade.convert('RGBA'), np.float32) / 255.0)
    plan.use('P_GaogaenRevengeStart', 1.0)
    row = {r['emitter']: r for r in plan.report()['sets']['P_GaogaenRevengeStart']}['flare1']
    assert row['carried'] and row['stand_in']
    [group] = [g for g, label in zip(plan.groups, plan.group_labels) if label.startswith('cmn_flare1 with ef_cmn_grade00')]
    picture = oe.decode_image(group['images'][0], group['format'], group['width'], group['height'])
    pixels = np.asarray(picture.convert('RGBA'), np.float32) / 255.0
    assert fs.draws_square(picture)[0] is None
    seen = pixels[..., 3] > 0.25
    assert seen.any() and pixels[..., :3].max(axis=-1)[seen].mean() > 0.8      # what is seen of it is bright
