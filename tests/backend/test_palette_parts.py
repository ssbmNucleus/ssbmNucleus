"""One analysis, clustered per part.

A session holds a single palette analysis, and a recolor can only name groups
from it. Whole-costume clustering merges parts that share a hue, so Mario's red
cap and red shirt came back as one group and could never differ; the only way
round it was an analysis per part, i.e. a model round trip per part. These
tests pin the property that removes that loop: parts sharing a colour stay
separately adjustable inside ONE analysis, recolored by ONE call.
"""
import numpy as np
import pytest

from shared.rendering import palette

RED, BLUE = (200, 30, 30, 255), (30, 60, 200, 255)


def solid(color, size=16):
    return np.tile(np.array(color, dtype=np.uint8), (size, size, 1))


def test_the_same_red_in_two_parts_becomes_two_groups():
    parts = {'cap': {8: solid(RED)}, 'shirt': {5: solid(RED)}}
    whole, _ = palette.analyze({8: solid(RED), 5: solid(RED)}, 8)
    split, _ = palette.analyze_parts(parts, 8)
    # Clustered together, one red is one hue family; per part, each keeps its own.
    assert {g['centerHue'] // 30 for g in whole} == {g['centerHue'] // 30 for g in split}
    assert {g['part'] for g in split} == {'cap', 'shirt'}


def test_group_indices_run_across_parts_and_each_map_points_at_its_own():
    parts = {'cap': {8: solid(RED)}, 'overalls': {0: solid(BLUE)}}
    groups, maps = palette.analyze_parts(parts, 4)
    assert [g['index'] for g in groups] == list(range(len(groups)))
    cap = {g['index'] for g in groups if g['part'] == 'cap'}
    overalls = {g['index'] for g in groups if g['part'] == 'overalls'}
    assert cap and overalls and not cap & overalls
    assert set(np.unique(maps[8])) - {255} <= cap
    assert set(np.unique(maps[0])) - {255} <= overalls


def test_one_recolor_moves_one_part_and_leaves_its_same_colored_neighbor():
    parts = {'cap': {8: solid(RED)}, 'shirt': {5: solid(RED)}}
    groups, maps = palette.analyze_parts(parts, 4)
    cap_groups = [g['index'] for g in groups if g['part'] == 'cap']
    # Gold cap, untouched shirt -- in a single adjustment set.
    adjustments = {i: (45, 60, 'set', 1) for i in cap_groups}
    cap = palette.apply_adjustments(parts['cap'][8], maps[8], adjustments)
    shirt = palette.apply_adjustments(parts['shirt'][5], maps[5], adjustments)
    assert cap is not None and not np.array_equal(cap, parts['cap'][8])
    assert shirt is None, 'the shirt shares the red but not the part, so it must not move'


def test_a_texture_cannot_belong_to_two_parts():
    with pytest.raises(ValueError, match='more than one part'):
        palette.analyze_parts({'cap': {8: solid(RED)}, 'emblem': {8: solid(RED)}}, 4)


def test_transparent_pixels_stay_unassigned_after_the_offset():
    clear = solid(RED)
    clear[:8, :, 3] = 0
    _, maps = palette.analyze_parts({'a': {0: solid(BLUE)}, 'b': {1: clear}}, 4)
    assert (maps[1].reshape(16, 16)[:8] == 255).all(), 'an offset must never turn "unassigned" into a group'


def test_a_one_color_part_is_one_group_not_max_groups_invented_slices():
    # The Skin Creator pads to max_groups by halving the widest range into equal,
    # invented counts. Handed to a model, that is eight near-identical "groups"
    # to deliberate over -- the degenerate buckets seen in a real Aztec run.
    # Denim as it really is: one blue family spread over ~20 degrees of hue.
    shade = solid((25, 80, 160, 255))         # hue ~215
    shade[:8] = (40, 45, 200, 255)            # hue ~238
    padded, _ = palette.analyze({0: shade}, 8)
    groups, _ = palette.analyze_parts({'overalls': {0: shade}}, 8)
    assert len(padded) > 1, 'the UI path still pads, by design'
    assert len(groups) == 1 and groups[0]['part'] == 'overalls'


WHITE = (235, 235, 235, 255)


def test_a_white_part_gets_a_group_instead_of_none():
    # A near-white shirt used to return ZERO groups: nothing to recolour at all.
    groups, maps = palette.analyze_parts({'shirt': {5: solid(WHITE)}}, 8)
    assert len(groups) == 1 and groups[0]['kind'] == 'neutral' and groups[0]['part'] == 'shirt'
    assert (maps[5] == groups[0]['index']).all()


def test_white_goes_black_by_colourising_not_shifting():
    groups, maps = palette.analyze_parts({'shirt': {5: solid(WHITE)}}, 8)
    g = groups[0]['index']
    shifted = palette.apply_adjustments(solid(WHITE), maps[5], {g: (120, 0, 'shift', 1)})
    assert shifted is None or np.array_equal(shifted, solid(WHITE)), 'a hue shift has no hue to move'
    black = palette.apply_adjustments(solid(WHITE), maps[5], {g: (0, 0, 'set', 0.15)})
    assert black[..., :3].max() < 45


def test_a_mixed_part_keeps_its_colours_separate_from_its_neutrals():
    mixed = solid(RED)
    mixed[:8] = WHITE
    groups, maps = palette.analyze_parts({'emblem': {10: mixed}}, 8)
    kinds = [g.get('kind', 'hue') for g in groups]
    assert kinds.count('neutral') == 1 and len(groups) >= 2
    neutral = next(g['index'] for g in groups if g.get('kind') == 'neutral')
    assert (maps[10].reshape(16, 16)[:8] == neutral).all()
    assert not (maps[10].reshape(16, 16)[8:] == neutral).any()


def emblem():
    """Mario's cap emblem in miniature: cap red to the edges, a white ring, and a
    red M inside the ring -- the same red as the field around it."""
    img = solid(RED, size=32)
    yy, xx = np.mgrid[:32, :32]
    r = np.hypot(yy - 15.5, xx - 15.5)
    img[(r > 7) & (r <= 11)] = WHITE          # the ring
    img[(r <= 7)] = WHITE                     # the white disc
    img[12:20, 13:19] = RED                   # the "M", enclosed
    return img, (r <= 11)


def test_the_surrounding_field_keeps_the_field_and_drops_the_letter():
    img, inside = emblem()
    reds = (img[..., 0] == RED[0]) & (img[..., 1] == RED[1])
    kept = palette.surrounding(reds)
    assert kept[0, 0] and kept[31, 31], 'the field is kept'
    assert not kept[inside].any(), 'the M inside the ring is not the cap'


def test_a_letter_touching_the_mirror_seam_is_still_not_the_field():
    """The real emblem is HALF a circle, mirrored on the model, so the M reaches
    the texture edge. 'Touches the border' kept it; size does not."""
    img, _ = emblem()
    half = img[:, :16].copy()                     # cut through the disc and the M
    reds = (half[..., 0] == RED[0]) & (half[..., 1] == RED[1])
    letter = np.zeros_like(reds)
    letter[12:20, 13:16] = True
    assert reds[letter].all() and letter[:, -1].any(), 'the M does touch the seam'
    kept = palette.surrounding(reds)
    assert kept[0, 0] and not kept[letter].any()


def test_a_part_borrows_only_its_own_colour_from_a_shared_texture():
    img, inside = emblem()
    groups, maps = palette.analyze_parts({'cap': {8: solid(RED)}}, 8, extras={'cap': {10: img}})
    cap = {g['index'] for g in groups if g['part'] == 'cap'}
    borrowed = maps[10].reshape(32, 32)
    assert set(np.unique(borrowed[~inside])) <= cap, 'the red field joins the cap'
    assert (borrowed[inside] == 255).all(), 'the ring and the M are left alone'
    # Recolour the cap black: the field follows, the M does not.
    out = palette.apply_adjustments(img, maps[10], {g: (0, 0, 'set', 0.1) for g in cap})
    assert out[0, 0, :3].max() < 40 and tuple(out[15, 15, :3]) == RED[:3]


def test_a_texture_named_as_its_own_part_is_never_borrowed():
    img, _ = emblem()
    groups, maps = palette.analyze_parts({'cap': {8: solid(RED)}, 'cap emblem': {10: img}}, 8,
                                         extras={'cap': {10: img}})
    emblem_groups = {g['index'] for g in groups if g['part'] == 'cap emblem'}
    assert set(np.unique(maps[10])) - {255} <= emblem_groups


def _hsl_texture(pixels):
    """A 1xN RGBA texture from (hue, saturation, lightness) triples."""
    from shared.rendering.palette import hsl_to_rgb
    h, s, l = (np.array(v, dtype=np.float64) for v in zip(*pixels))
    rgb = hsl_to_rgb(h, s, l)
    return np.concatenate([rgb, np.full((len(pixels), 1), 255, np.uint8)], axis=1).reshape(1, -1, 4)


def test_faint_fabric_pixels_move_with_their_fabric():
    """Marth's tunic: a 20%-saturation blue whose 8%-saturation pixels were left
    grey on every recolour -- the white blotches."""
    from shared.rendering import palette
    tunic = _hsl_texture([(215, 22, 55)] * 300 + [(215, 8, 60)] * 100)
    groups, maps = palette.analyze({0: tunic}, pad=False)
    assert len(groups) == 1 and (maps[0] == 0).all(), 'the faint pixels join the blue'
    out = palette.apply_adjustments(tunic, maps[0], {0: (265, 60, 'set', 0.55)})
    faint_after = out.reshape(-1, 4)[-1, :3]
    fabric_after = out.reshape(-1, 4)[0, :3]
    assert abs(int(faint_after[2]) - int(fabric_after[2])) < 40, 'no grey speckle left behind'


def test_near_white_gloves_are_never_pulled_into_blue_overalls():
    from shared.rendering import palette
    overalls = _hsl_texture([(220, 60, 45)] * 400)
    gloves = _hsl_texture([(220, 6, 85)] * 380 + [(220, 60, 45)] * 20)   # bluish-white, a blue seam
    groups, maps = palette.analyze({0: overalls, 1: gloves}, pad=False)
    assert (maps[1][:380] == 255).all(), 'blue is not the gloves\' dominant colour, so they stay out'


def test_true_greys_still_get_the_neutral_group():
    from shared.rendering import palette
    shirt = _hsl_texture([(215, 22, 55)] * 300 + [(0, 0, 95)] * 100)
    groups, maps = palette.analyze_parts({'shirt': {0: shirt}})
    assert any(g.get('kind') == 'neutral' and g['pixelCount'] == 100 for g in groups)


def _chroma(rgb):
    rgb = np.asarray(rgb, dtype=float)
    return rgb.max() - rgb.min()


def test_darkening_a_pale_colour_never_makes_it_more_colourful():
    """Link's pale blue-grey chainmail, darkened for a zombie, came out neon cyan."""
    from shared.rendering import palette
    pale = _hsl_texture([(183, 40, 85)] * 4)
    before = pale.reshape(-1, 4)[0, :3]
    out = palette.apply_adjustments(pale, np.zeros(4, np.uint8), {0: (0, 0, 'shift', 0.55)})
    after = out.reshape(-1, 4)[0, :3]
    assert after.mean() < before.mean(), 'it did get darker'
    assert _chroma(after) <= _chroma(before) + 2, 'but no more colourful'


def test_darkening_a_mid_tone_keeps_its_saturation():
    from shared.rendering import palette
    from shared.rendering.palette import rgb_to_hsl
    mid = _hsl_texture([(220, 50, 50)] * 4)
    out = palette.apply_adjustments(mid, np.zeros(4, np.uint8), {0: (0, 0, 'shift', 0.55)})
    _, s, _ = rgb_to_hsl(out.reshape(-1, 4)[:1, :3].astype(float))
    assert abs(s[0] - 50) < 2


def test_an_explicit_saturation_is_kept_even_when_darkening():
    from shared.rendering import palette
    from shared.rendering.palette import rgb_to_hsl
    pale = _hsl_texture([(183, 40, 85)] * 4)
    out = palette.apply_adjustments(pale, np.zeros(4, np.uint8), {0: (120, 60, 'set', 0.55)})
    _, s, _ = rgb_to_hsl(out.reshape(-1, 4)[:1, :3].astype(float))
    assert abs(s[0] - 60) < 2
