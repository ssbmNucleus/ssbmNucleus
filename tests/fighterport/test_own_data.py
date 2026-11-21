"""own_data: the donor's fighter data rewritten for a fighter on its own skeleton.

The first half holds the pure parts against small made-up rigs. The second half needs the donor's own files, the
frozen Duck Hunt rig and the source game's files; each test there is skipped on a machine without them.
"""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from fighter_port import own_data as od
from fighter_port.compat.bone_lookup import SLOTS

SLOT = {name: i for i, name in enumerate(SLOTS)}


# ------------------------------------------------------------------------------------------------- made-up rigs
def toy_rig():
    """top > hip > (legR > kneeR > footR), (legL > kneeL > footL), (bust > head, armR > handR)"""
    order = ['top', 'hip', 'legR', 'kneeR', 'footR', 'legL', 'kneeL', 'footL', 'bust', 'head', 'armR', 'handR']
    parent = dict(top=None, hip='top', legR='hip', kneeR='legR', footR='kneeR', legL='hip', kneeL='legL',
                  footL='kneeL', bust='hip', head='bust', armR='bust', handR='armR')
    t = dict(top=[0, 0, 0], hip=[0, 5, 0], legR=[-1, 0, 0], kneeR=[0, -2, 0], footR=[0, -2, 0], legL=[1, 0, 0],
             kneeL=[0, -2, 0], footL=[0, -2, 0], bust=[0, 3, 0], head=[0, 2, 0], armR=[-1.5, 0, 0], handR=[-3, 0, 0])
    rest = {j: dict(r=[0.0, 0.0, 0.0], t=[float(v) for v in t[j]], s=[1.0, 1.0, 1.0]) for j in order}
    return dict(order=order, parent=parent, rest=rest)


def toy_forward(rig, **binds):
    forward = [od.NONE] * len(SLOTS)
    for slot, joint in binds.items():
        forward[SLOT[slot]] = rig['order'].index(joint)
    return forward


def toy_donor():
    """joints: 0 top, 1 hip, 2 waistB, 3 bust, 4 hair (no slot), 5 rHand, 6 sword, 7 lHave, 8 lIndex1"""
    lookup = [od.NONE] * len(SLOTS)
    for slot, joint in dict(top=0, hip=1, waistB=2, bust=3, rHand=5, lHave=7, lIndex1=8).items():
        lookup[SLOT[slot]] = joint
    return dict(joints=9, lookup=lookup, parent=[None, 0, 1, 2, 3, 3, 5, 3, 7], sword=(6,))


def test_rest_worlds_and_height():
    rig = toy_rig()
    w = od.rest_worlds(rig)
    assert np.allclose(w[rig['order'].index('footR')][:3, 3], [-1, 1, 0])
    assert np.allclose(w[rig['order'].index('head')][:3, 3], [0, 10, 0])
    assert od.rig_height(w) == pytest.approx(10.0)


def test_rest_worlds_refuses_a_child_before_its_parent():
    rig = toy_rig()
    rig['order'] = rig['order'][1:] + rig['order'][:1]
    with pytest.raises(ValueError):
        od.rest_worlds(rig)


def test_tree_links_are_first_child_and_next_sibling():
    #        0
    #      1   4
    #     2 3
    links = od.tree_links([None, 0, 1, 1, 0])
    assert links == [(1, None), (2, 4), (None, 3), (None, None), (None, None)]


def test_tree_links_refuse_an_order_the_engine_would_not_walk():
    with pytest.raises(ValueError):
        od.tree_links([None, 0, 0, 1])          # 3 hangs under 1 but comes after 1's sibling
    with pytest.raises(ValueError):
        od.tree_links([None] + list(range(40)))  # a chain 40 deep


def test_region_is_nearest_first_without_helpers_and_cut_to_the_room():
    names = ['hand', '__helper', 'thumb', 'index', 'tip']
    parents = [None, 0, 1, 0, 3]
    assert od.region(parents, names, 0, 10) == ([0, 3, 2, 4], [])
    assert od.region(parents, names, 0, 2) == ([0, 3], [2, 4])
    assert od.region(parents, names, 0, 10, skip_anchor=True) == ([3, 2, 4], [])


def test_joint_map_tiers():
    rig = toy_rig()
    forward = toy_forward(rig, top='top', hip='hip', waist='bust', bust='bust', rHand='handR')
    donor = toy_donor()
    m = od.joint_map(donor, forward, item_joint=7, item_target=rig['order'].index('head'))
    at = rig['order'].index
    assert (m[1]['to'], m[1]['tier']) == (at('hip'), 'SLOT')
    assert (m[2]['to'], m[2]['tier']) == (at('bust'), 'STAND_IN')            # waistB is empty, waist stands in
    assert (m[4]['to'], m[4]['tier']) == (at('bust'), 'ANCESTOR')            # hair: the joint above it
    assert (m[6]['to'], m[6]['tier']) == (at('handR'), 'SWORD')              # no hold slot: the right hand
    assert (m[7]['to'], m[7]['tier']) == (at('head'), 'ITEM')
    assert (m[8]['to'], m[8]['tier']) == (at('head'), 'ANCESTOR')            # a finger of the item hand
    assert set(m) == set(range(9))


def test_joint_map_sword_takes_the_right_hold_slot_when_there_is_one():
    rig = toy_rig()
    forward = toy_forward(rig, top='top', hip='hip', bust='bust', rHand='handR', rHave='armR')
    assert od.joint_map(toy_donor(), forward)[6]['to'] == rig['order'].index('armR')


def test_joint_map_refuses_a_joint_with_nothing_above_it():
    donor = dict(joints=2, lookup=[od.NONE] * len(SLOTS), parent=[None, 0], sword=())
    with pytest.raises(ValueError):
        od.joint_map(donor, [od.NONE] * len(SLOTS))


def test_hurt_joint_goes_to_a_joint_that_has_a_hurtbox():
    parents = [None, 0, 1, 2, 1]
    assert od.hurt_joint(2, parents, {2, 4}) == (2, 'itself')
    assert od.hurt_joint(3, parents, {1}) == (1, 'above')
    assert od.hurt_joint(1, parents, {3}) == (3, 'below')
    assert od.hurt_joint(4, parents, {3}) == (3, 'first')


def test_hurtboxes_carry_the_source_numbers_and_melee_heights():
    rig = toy_rig()
    rows = [dict(bone='head', a=[0, 0.5, 0], b=[0, 1, 0], radius=1.5, height='hit_height_high', part='x'),
            dict(bone='kneeR', a=[0, 0, 0], b=[0, -2, 0], radius=0.7, height='hit_height_low', part='x'),
            dict(bone='bust', a=[0, 0, 0], b=[0, 1, 0], radius=2.0, height='hit_height_center', part='x')]
    caps = od.hurtboxes(rows, rig['order'])
    assert [c['joint'] for c in caps] == [9, 3, 8]
    assert [c['height'] for c in caps] == [2, 0, 1]
    assert all(c['grabbable'] == 1 for c in caps) and caps[0]['radius'] == 1.5 and caps[1]['b'] == [0.0, -2.0, 0.0]
    assert [c['grabbable'] for c in od.hurtboxes(rows, rig['order'], grabbable={'bust'})] == [0, 0, 1]


def test_hurtboxes_refuse_too_many_and_a_joint_the_rig_lacks():
    rig = toy_rig()
    row = dict(bone='head', a=[0, 0, 0], b=[0, 1, 0], radius=1.0, height='hit_height_high', part='x')
    with pytest.raises(ValueError):
        od.hurtboxes([row] * 16, rig['order'])
    with pytest.raises(ValueError):
        od.hurtboxes([dict(row, bone='tail')], rig['order'])
    with pytest.raises(ValueError):
        od.hurtboxes([], rig['order'])


def test_capsule_check_finds_the_reading_and_the_sides():
    rig = toy_rig()
    order = rig['order']
    parents = [None if rig['parent'][j] is None else order.index(rig['parent'][j]) for j in order]
    w = od.rest_worlds(rig)
    caps = [dict(joint=order.index('kneeR'), height=0, grabbable=1, a=[0, 0, 0], b=[0, -2, 0], radius=0.5),
            dict(joint=order.index('kneeL'), height=0, grabbable=1, a=[0, 0, 0], b=[0, -2, 0], radius=0.5)]
    rng = np.random.default_rng(1)
    right = np.c_[-1 + rng.uniform(-.3, .3, 200), rng.uniform(1, 3, 200), rng.uniform(-.3, .3, 200)]
    left = right * [-1, 1, 1]
    points = np.r_[right, left]
    owner = np.r_[np.full(200, order.index('kneeR')), np.full(200, order.index('kneeL'))]
    c = od.capsule_check(caps, order, parents, w, points, owner)
    assert c['best_reading'] == 'as written' and c['readings']['as written']['body_inside'] == 1.0
    assert c['readings']['x and y swapped']['body_inside'] < 0.5
    assert c['sides_ok'] and c['pairs'][0]['right_x'] < 0 < c['pairs'][0]['left_x']
    assert all(row['toward_child'] == pytest.approx(1.0) for row in c['capsules'])
    # the two capsules swapped between the knees: the sides no longer hold
    swapped = [dict(caps[0], b=[0, -2, 3]), caps[1]]
    assert not od.capsule_check(swapped, order, parents, w)['sides_ok']


def test_one_dense_part_does_not_overturn_the_games_reading():
    """Incineroar: his head and fur are most of the body's points, and read with x and y swapped the head's round
    capsule holds more of them, so that reading holds more of the body while it puts the limbs' capsules off their
    limbs. A reading must also hold more of each capsule's own points to win."""
    rig = toy_rig()
    order = rig['order']
    parents = [None if rig['parent'][j] is None else order.index(rig['parent'][j]) for j in order]
    w = od.rest_worlds(rig)
    knee_r, knee_l, head = order.index('kneeR'), order.index('kneeL'), order.index('head')
    caps = [dict(joint=knee_r, height=0, grabbable=1, a=[0, 0, 0], b=[0, -2, 0], radius=0.5),
            dict(joint=knee_l, height=0, grabbable=1, a=[0, 0, 0], b=[0, -2, 0], radius=0.5),
            dict(joint=head, height=0, grabbable=1, a=[0, 0, 0], b=[0, 2, 0], radius=1.0)]
    rng = np.random.default_rng(2)
    right = w[knee_r][:3, 3] + np.c_[rng.uniform(-.3, .3, 100), rng.uniform(-2, 0, 100), rng.uniform(-.3, .3, 100)]
    left = right * [-1, 1, 1]
    # a dense head lying along x: the swapped reading's capsule holds all of it, the game's half
    face = w[head][:3, 3] + np.c_[rng.uniform(0, 2, 2000), rng.uniform(-.3, .3, 2000), rng.uniform(-.3, .3, 2000)]
    points = np.r_[right, left, face]
    owner = np.r_[np.full(100, knee_r), np.full(100, knee_l), np.full(2000, head)]
    c = od.capsule_check(caps, order, parents, w, points, owner)
    t = c['readings']
    assert t['x and y swapped']['body_inside'] > t['as written']['body_inside'] + od.READING_MARGIN
    assert t['x and y swapped']['capsules_inside'] < t['as written']['capsules_inside']
    assert c['best_reading'] == 'as written'
    assert c['closest_other_reading']['why']


def test_a_pair_the_games_own_table_gives_lopsided_is_carried_and_one_off_its_limb_is_not():
    """The left and right check is of the route's work (the rig, the reader), not of the game's table. Wolf's table
    gives his two knees different numbers; that is the game's, and is carried. A capsule that is nowhere near its
    twin's place is not."""
    rig = toy_rig()
    order = rig['order']
    parents = [None if rig['parent'][j] is None else order.index(rig['parent'][j]) for j in order]
    w = od.rest_worlds(rig)

    def knees(right_end, left_end, radius=0.5):
        return [dict(joint=order.index(name), height=0, grabbable=1, a=[0, 0, 0], b=end, radius=radius)
                for name, end in (('kneeR', right_end), ('kneeL', left_end))]
    # (this rig's joints are not turned, so a mirrored pair has the same numbers but for x; the difference here is in z)
    lopsided = od.capsule_check(knees([0, -2, 0.2], [0, -2, -0.2]), order, parents, w)
    pair = lopsided['pairs'][0]
    assert lopsided['sides_ok'] and pair['lopsided_in_the_source'] and pair['mirror_error'] == pytest.approx(0.4)
    assert 'carried as it is' in pair['why'] and pair['source_numbers']['left']['b'] == [0, -2, -0.2]
    assert len(od.lopsided_notes(lopsided)) == 1 and 'kneeR' in od.lopsided_notes(lopsided)[0] and not od.sides_problems(lopsided)
    # further apart than the capsule is wide: not the same part of the body any more. It fails, and says the numbers
    # and what to do
    far = knees([0, -2, 0.6], [0, -2, -0.6])
    off = od.capsule_check(far, order, parents, w)
    said = od.sides_problems(off)
    assert not off['sides_ok'] and len(said) == 1 and not od.lopsided_notes(off)
    assert 'kneeR and kneeL' in said[0] and "lopsided=['kneeR']" in said[0] and 'fighters.py' in said[0] and '-0.6' in said[0]
    # ... until someone has looked at the model and written that the game means it
    accepted = od.capsule_check(far, order, parents, w, accepted=('kneeR',))
    assert accepted['sides_ok'] and 'accepted' in accepted['pairs'][0]['why']
    # a pair that IS its mirror image says nothing about lopsidedness
    same = od.capsule_check(knees([0, -2, 0], [0, -2, 0]), order, parents, w)
    assert same['sides_ok'] and 'lopsided_in_the_source' not in same['pairs'][0] and not od.lopsided_notes(same)

    # The two JOINTS not mirror images of each other (a rig whose left knee is not where its right one is): the
    # rig is at fault whatever the table says, and no acceptance covers that
    bent = toy_rig()
    bent['rest']['kneeL']['t'] = [0.5, -2.0, 0.0]
    broken = od.capsule_check(knees([0, -2, 0], [0, -2, 0]), order, parents, od.rest_worlds(bent), accepted=('kneeR',))
    assert not broken['sides_ok'] and not broken['pairs'][0]['lopsided_in_the_source'] and 'the rig' in broken['pairs'][0]['why']
    # each on its own side, always: a mirrored pair on the wrong sides is refused
    crossed = toy_rig()
    crossed['rest']['legR']['t'], crossed['rest']['legL']['t'] = [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]
    wrong = od.capsule_check(knees([0, -2, 0], [0, -2, 0]), order, parents, od.rest_worlds(crossed))
    assert not wrong['sides_ok'] and 'own side' in od.sides_problems(wrong)[0]


def test_a_joint_tree_is_cut_after_its_first_nodes_in_the_engines_order():
    """A rig with fewer joints than the donor: the donor's metal skeleton is paired with the fighter's joints by
    counting, so its nodes past the rig's last joint are cut off (Falco's rig has 89 joints, Marth's 90)."""
    # 0 > (1 > (2, 3), 4 > 5), a node every 0x100: its child's link at +8, its next sibling's at +12
    tree = {0x000: (0x100, None), 0x100: (0x200, 0x400), 0x200: (None, 0x300), 0x300: (None, None),
            0x400: (0x500, None), 0x500: (None, None)}
    ptr = lambda slot: tree[slot - 8][0] if slot - 8 in tree else tree[slot - 12][1]      # noqa: E731
    nodes = [(0x000, None), (0x100, 0), (0x200, 1), (0x300, 1), (0x400, 0), (0x500, 4)]     # the engine's walking order
    assert od.links_past(nodes, ptr, 6) == {}
    assert od.links_past(nodes, ptr, 5) == {0x408: None}                    # the last node hangs from the fifth
    assert od.links_past(nodes, ptr, 4) == {0x10C: None}                    # node 4 is the second node's sibling
    assert od.links_past(nodes, ptr, 3) == {0x10C: None, 0x20C: None}
    assert od.links_past(nodes, ptr, 1) == {0x008: None}


def test_two_joints_are_mirror_images_whichever_axes_the_left_one_turns_about():
    from fighter_port.rigmap import euler_xyz
    right = np.eye(4)
    right[:3, :3], right[:3, 3] = euler_xyz([0.3, -0.7, 1.1]), [-1.5, 4.0, 0.5]
    flip = np.diag([-1.0, 1.0, 1.0, 1.0])
    # the game's own way (found on Wolf's and Duck Hunt's limbs): the left joint keeps x and y and turns z about
    left = flip @ right @ np.diag([1.0, 1.0, -1.0, 1.0])
    assert od.joints_mirror(right, left) == [1.0, 1.0, -1.0]
    # joints that are not turned at all: mirrored in place, x turned about
    assert od.joints_mirror(np.eye(4), np.eye(4)) == [-1.0, 1.0, 1.0]
    # not where its twin is, or turned some other way: not mirror images
    moved = left.copy()
    moved[:3, 3] += [0.0, 0.3, 0.0]
    assert od.joints_mirror(right, moved) is None
    turned = left.copy()
    turned[:3, :3] = turned[:3, :3] @ euler_xyz([0.0, 0.0, 0.4])
    assert od.joints_mirror(right, turned) is None


def test_ecb_joints_go_by_the_part_of_the_body_not_the_place_in_the_list():
    index = dict(Head=11, ShoulderR=47, ShoulderL=41, KneeR=59, KneeL=54, Hip=5)
    new_slot = {11: 'headN', 47: 'rShoulder', 41: 'lShoulder', 59: 'rKnee', 54: 'lKnee', 5: 'hip'}
    donor_slot = {60: 'headN', 70: 'rShoulder', 28: 'lShoulder', 14: 'rKnee', 7: 'lKnee', 4: 'hip'}
    # the donor's order turned round: the source's joints follow the donor's parts, not their own order
    six, how = od.ecb_joints([4, 7, 14, 28, 70, 60], donor_slot,
                             ['Head', 'ShoulderR', 'ShoulderL', 'KneeR', 'KneeL', 'Hip'], new_slot, index)
    assert six == [5, 54, 59, 41, 47, 11] and all(h.startswith('same part') for h in how)
    # Marth names his right shoulder twice: the second place takes what the source has left
    six, how = od.ecb_joints([60, 70, 70, 14, 7, 4], donor_slot,
                             ['Head', 'ShoulderR', 'ShoulderL', 'KneeR', 'KneeL', 'Hip'], new_slot, index)
    assert six == [11, 47, 41, 59, 54, 5] and sorted(six) == sorted(index.values())
    assert how[2].startswith('what the source')
    with pytest.raises(ValueError):
        od.ecb_joints([60, 70], donor_slot, ['Head'], new_slot, index)


def test_more_collision_joints_than_six_keep_the_ones_that_make_the_box():
    # Ivysaur's list: the usual six, his bulb and the model's root (forward, up at rest)
    at = dict(Head=(6.0, 6.0), ShoulderR=(3.0, 3.0), ShoulderL=(3.0, 3.0), KneeR=(-2.0, 2.0), KneeL=(-2.0, 2.0),
              Hip=(-1.0, 4.0), Flower=(-1.5, 11.0), top=(0.0, 0.0))
    six, out = od.ecb_six(list(at), at)
    assert len(six) == 6 and set(out) | set(six) == set(at)
    assert {'top', 'Flower', 'Head', 'KneeR'} <= set(six)          # the lowest, highest, furthest forward and back
    assert out == ['KneeL', 'Hip']                                 # the rest kept in the source's order, to six
    assert od.ecb_six(['Head', 'Hip'], {})[0] == ['Head'] + ['Hip'] * 5  # repeats preserve extrema


def test_the_models_root_in_a_source_table_is_the_rigs_top_joint():
    assert od.SOURCE_ROOT == 'top' and od.RIG_ROOT == '__engine_Top'


def test_ik_lengths_are_measured_on_the_rest_rig():
    rig = toy_rig()
    at = rig['order'].index
    got = od.ik_lengths(od.rest_worlds(rig), {'thigh': (at('legR'), at('kneeR')), 'shin': (at('kneeR'), at('footR')),
                                              'forearm': (at('armR'), at('handR')), 'foot': at('footR')})
    assert got == {'thigh': pytest.approx(2.0), 'shin': pytest.approx(2.0), 'forearm': pytest.approx(3.0),
                   'foot height': pytest.approx(1.0)}


def test_default_scale_is_the_two_games_units_measured_on_the_donor():
    marth = od.DONOR['Marth']
    assert od.default_scale(marth) == pytest.approx(16.650622 * 1.15 / 19.744346)
    assert od.default_scale(dict(rig_height=10.0, scale=2.0, ultimate_height=40.0), 20.0) == pytest.approx(1.0)


def test_the_reader_and_the_writer_agree_on_where_a_joint_sits_in_a_command():
    from vault.echo.commands import COMMANDS
    assert {code: c.size for code, c in COMMANDS.items()} == od.CMD_SIZE
    assert COMMANDS[od.CMD_GFX].param('bone_id').bit_offset == od.JOINT_FIELD[od.CMD_GFX][0]
    assert COMMANDS[od.CMD_GFX].param('use_common_bone_ids').bit_offset == od.COMMON_FLAG[od.CMD_GFX]
    assert COMMANDS[od.CMD_HIT].param('bone').bit_offset == od.JOINT_FIELD[od.CMD_HIT][0]
    assert COMMANDS[od.CMD_HIT].param('use_common_bone_ids').bit_offset == od.COMMON_FLAG[od.CMD_HIT]
    assert COMMANDS[od.CMD_HURT_STATE].param('bone_id').bit_offset == od.JOINT_FIELD[od.CMD_HURT_STATE][0]
    assert COMMANDS[od.CMD_BONE_PHYSICS].param('bone_id').bit_offset == od.JOINT_FIELD[od.CMD_BONE_PHYSICS][0]
    for code, (first, bits) in od.JOINT_FIELD.items():
        assert first + bits <= 32 and code in od.CMD_NAME
    assert od._bits(0x2A8C0000, 6, 8) == 0xA3 and od._bits(0x00000041, 24, 8) == 0x41


def gfx(bone, common=0, head=0):
    return (od.CMD_GFX << 26) | (bone << 18) | (common << 17) | (head << 15)


def hit(bone, common=0, ident=3, damage=12):
    return (od.CMD_HIT << 26) | (ident << 23) | (bone << 11) | (common << 10) | damage


def test_put_changes_only_its_own_bits():
    word = 0xFFFFFFFF
    assert od._put(word, 6, 8, 0) == 0xFC03FFFF and od._put(0, 13, 8, 0xFF) == 0x0007F800
    assert od._bits(od._put(0x12345678, 24, 8, 0xAB), 24, 8) == 0xAB
    with pytest.raises(ValueError):
        od._put(0, 6, 8, 256)


def test_command_target_repoints_a_joint_and_keeps_the_rest_of_the_command():
    rig = toy_rig()
    forward = toy_forward(rig, top='top', hip='hip', bust='bust', rHand='handR')
    reverse = [od.NONE] * len(rig['order'])
    for slot, joint in enumerate(forward):
        if joint != od.NONE:
            reverse[joint] = slot
    donor = toy_donor()
    parents = [None if rig['parent'][j] is None else rig['order'].index(rig['parent'][j]) for j in rig['order']]
    at = rig['order'].index
    jmap = od.joint_map(donor, forward, item_joint=7, item_target=at('head'))
    args = (donor, jmap, forward, reverse, parents, {at('hip'), at('head')})

    row = od.command_target(od.CMD_HIT, hit(6), *args)                       # the sword
    assert row['tier'] == 'SWORD' and row['word'] == hit(at('handR')) and row['donor_joint'] == 6
    row = od.command_target(od.CMD_GFX, gfx(4), *args)                       # hair: the joint above
    assert row['tier'] == 'ANCESTOR' and row['word'] == gfx(at('bust'))
    # left as they are: the head flag, a selector, a slot the rig binds
    assert od.command_target(od.CMD_GFX, gfx(4, head=1), *args)['word'] == gfx(4, head=1)
    assert od.command_target(od.CMD_GFX, gfx(0x8D), *args)['tier'] is None
    assert od.command_target(od.CMD_HIT, hit(SLOT['hip'], common=1), *args)['kept'].startswith('a slot the rig binds')
    # a slot the rig leaves empty: the slot of the joint the donor's joint goes to ...
    row = od.command_target(od.CMD_HIT, hit(SLOT['waistB'], common=1), *args)
    assert row['tier'] == 'SLOT>ANCESTOR' and row['word'] == hit(SLOT['hip'], common=1)
    # ... or, when that joint has no slot, the joint itself with the flag taken off
    row = od.command_target(od.CMD_HIT, hit(SLOT['lHave'], common=1), *args)
    assert row['tier'] == 'SLOT>JOINT' and row['word'] == hit(at('head'))
    # a hurtbox switch lands on a joint that has a hurtbox
    row = od.command_target(od.CMD_HURT_STATE, (od.CMD_HURT_STATE << 26) | (3 << 18) | 2, *args)
    assert od._bits(row['word'], 6, 8) == at('hip') and row['tier'] == 'SLOT>hurtbox above' and row['word'] & 0x3FFFF == 2
    with pytest.raises(ValueError):
        od.command_target(od.CMD_HIT, hit(200), *args)                       # no such donor joint
    with pytest.raises(ValueError):
        od.command_target(od.CMD_HIT, hit(SLOT['rHave'], common=1), *args)   # a slot the donor has not either


def test_trail_target_turns_off_only_the_donors_own_sword():
    start, off, item = od.CMD_SWORD_TRAIL << 26, (od.CMD_SWORD_TRAIL << 26) | 0x1FFFFFF, (od.CMD_SWORD_TRAIL << 26) | (1 << 25)
    assert od.trail_target(start) == (off, "the donor sword's, turned off")
    assert od.trail_target(off) == (off, 'already off')
    assert od.trail_target(item) == (item, "a held sword item's, left")


# -------------------------------------------------------------------------------------------- the real files
REPO = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2])
DONOR_DIR = REPO / 'app/scratch/brawl-oneshot/port/donor'
WORK = REPO / 'app/scratch/duckhunt-native'
SOURCE = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
PLCO = REPO / 'app/storage/test-base/files/PlCo.dat'
VL = SOURCE / 'gamedata/fighter/duckhunt/param/vl.prc'
HAVE = all(p.exists() for p in (DONOR_DIR / 'PlMs.dat', WORK / 'rig/rig-duckhunt.json', WORK / 'rig/lookup.json',
                                WORK / 'body/duckhunt.dat', VL))
real = pytest.mark.skipif(not HAVE, reason='the donor, the frozen rig or the source game\'s files are not here')


@pytest.fixture(scope='module')
def inputs():
    return dict(pl=(DONOR_DIR / 'PlMs.dat').read_bytes(),
                frozen=json.loads((WORK / 'rig/rig-duckhunt.json').read_text('utf-8')),
                lookup=json.loads((WORK / 'rig/lookup.json').read_text('utf-8')),
                costume=(WORK / 'body/duckhunt.dat').read_bytes())


@real
def test_the_donors_metal_skeleton_cuts_to_a_rig_with_fewer_joints(inputs):
    ed = od._Edit(inputs['pl'])
    metal = ed.dat.ptr(ed.root + 0x5C)
    before = od._File(ed.bytes())
    nodes = before.tree(metal)
    assert len(nodes) == od.DONOR['Marth']['joints'] == 90
    for keep in (89, 60, 1):                              # (Falco's rig has 89 joints)
        ed = od._Edit(inputs['pl'])
        ed.set_pointers(od.links_past(nodes, before.ptr, keep))
        left = od._File(ed.bytes()).tree(metal)
        # exactly the first nodes, in the same order, each still under the same parent
        assert left == nodes[:keep]


@pytest.fixture(scope='module')
def built(inputs):
    out, report = od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth',
                           inputs['costume'])
    return out, report


@pytest.mark.skipif(not (PLCO.exists() and (DONOR_DIR / 'PlMsNr.dat').exists()), reason='no PlCo.dat / donor costume')
def test_the_kept_donor_facts_are_the_files():
    from fighter_port import compat
    compat.install()
    from randall.model_import.native_rig import bone_lookup
    marth = od.DONOR['Marth']
    table = bone_lookup.from_plco(PLCO.read_bytes(), marth['kind'])
    assert table['forward'] == marth['lookup'] and table['count'] == marth['joints']
    costume = od.costume_census((DONOR_DIR / 'PlMsNr.dat').read_bytes())
    assert costume['parents'] == marth['parent'] and costume['joints'] == marth['joints']
    pl = od.census((DONOR_DIR / 'PlMs.dat').read_bytes(), marth['root'])
    assert pl['facts']['model_scale'] == pytest.approx(marth['scale'])
    assert pl['facts']['shield_pose']['parents'] == marth['parent']         # the shield pose is a whole skeleton


@real
def test_the_source_tables_read_by_name(inputs):
    src = od.source_tables(VL.read_bytes(), inputs['frozen']['order'])
    assert [r['bone'] for r in src['hurt']] == ['Bust', 'Hip', 'Head', 'DuckHead', 'DuckHip', 'ArmR', 'ArmL',
                                                'KneeR', 'KneeL']
    assert [r['height'] for r in src['hurt']] == ['hit_height_center'] * 2 + ['hit_height_high'] + \
        ['hit_height_center'] * 4 + ['hit_height_low'] * 2
    assert [e['bone'] for e in src['ecb']] == ['Head', 'ShoulderR', 'ShoulderL', 'KneeR', 'KneeL', 'Hip']
    with pytest.raises(ValueError):
        od.source_tables(VL.read_bytes(), [j for j in inputs['frozen']['order'] if j != 'DuckHead'])


@real
def test_no_joint_in_the_new_file_is_past_the_rig(built, inputs):
    out, report = built
    v = report['verify']
    assert v['ok'], v['problems']
    assert v['highest'] < v['limit'] == 102 and not v['out_of_range'] and v['round_trip_problems'] == 0
    rows = od.census(out, 'ftDataMars', joints=102, attr_joints=od.DONOR['Marth']['attr_joints'])
    assert all(0 <= r['value'] < 102 for r in rows['joints'] if r['kind'] == 'JOINT')
    assert rows['facts']['hurtbox_count'] == 9 and rows['facts']['dynamics']['count'] == 0
    assert not any(row['pieces'] for row in rows['facts']['visibility'])
    assert rows['facts']['shield_pose']['nodes'] == 102 and rows['facts']['metal']['pieces'] == 0
    assert rows['facts']['sword_trail'].get('own') is None
    assert report['scripts']['repointed'] == sum(report['scripts']['repointed_by_tier'].values()) > 400


@real
def test_the_donor_file_is_seen_whole_by_the_census(inputs):
    """What the census finds in Marth's own file: the counts the rewrite has to account for."""
    old = od.census(inputs['pl'], 'ftDataMars', joints=90, attr_joints=od.DONOR['Marth']['attr_joints'])
    assert not old['facts']['out_of_range']
    scripts = [r for r in old['joints'] if r['consumer'].startswith('script ')]
    assert len(scripts) == 510 and sum(r['kind'] == 'SLOT' for r in scripts) == 1
    assert old['facts']['script_blocks'] == 360 and old['facts']['script_entries'] == 341
    assert old['facts']['hurtbox_count'] == 11 and old['facts']['dynamics']['count'] == 3
    assert old['facts']['metal'] == dict(nodes=90, pieces=12)


@real
def test_the_census_sees_a_joint_past_the_rig(built):
    out, _ = built
    rows = od.census(out, 'ftDataMars', joints=102)
    hurt = next(r for r in rows['joints'] if r['consumer'] == 'hurtbox[0]')
    broken = bytearray(out)
    struct.pack_into('>I', broken, od.HDR + hurt['at'], 200)
    assert od.census(bytes(broken), 'ftDataMars', joints=102)['facts']['out_of_range'] == ['hurtbox[0]']


@real
def test_the_same_inputs_give_the_same_file_and_the_donor_is_not_touched(inputs):
    before = bytes(inputs['pl'])
    a, _ = od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth', inputs['costume'])
    b, _ = od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth', inputs['costume'])
    assert a == b and inputs['pl'] == before


@real
def test_parameters_are_written_and_reported(inputs):
    out, report = od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth',
                           inputs['costume'], model_scale=1.25, item_hold='HaveR', keep_metal=True,
                           grabbable={'Bust', 'Hip'})
    assert report['verify']['ok'], report['verify']['problems']
    facts = od.census(out, 'ftDataMars', joints=102)
    assert facts['facts']['model_scale'] == pytest.approx(1.25) and facts['facts']['metal']['pieces'] == 12
    order = inputs['frozen']['order']
    hold = next(r for r in facts['joints'] if r['consumer'] == 'modelLookup.itemHold')
    assert order[hold['value']] == 'HaveR'
    assert [h['grabbable'] for h in facts['facts']['hurtboxes']] == [1, 1, 0, 0, 0, 0, 0, 0, 0]
    with pytest.raises(ValueError):
        od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth', inputs['costume'],
                 item_hold='NoSuchJoint')
    with pytest.raises(ValueError):
        od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth', inputs['costume'],
                 texture_slots=[0, 99])


@real
def test_more_hurtboxes_than_the_donor_has_room_for_go_on_the_end(inputs):
    src = od.source_tables(VL.read_bytes(), inputs['frozen']['order'])
    extra = [dict(src['hurt'][0], bone=b) for b in ('Waist', 'Neck', 'Tail1')]
    out, report = od.build(inputs['pl'], inputs['frozen'], inputs['lookup'], SOURCE, 'duckhunt', 'Marth',
                           inputs['costume'], source=dict(hurt=src['hurt'] + extra, ecb=src['ecb']))
    assert report['verify']['ok'], report['verify']['problems']
    assert od.census(out, 'ftDataMars', joints=102)['facts']['hurtbox_count'] == 12
    assert 'on the end' in report['hurtboxes']['written']


@real
def test_item_hold_hand_fallback_is_written_to_actual_fighter_data(inputs, monkeypatch):
    from fighter_port import fighters
    told=dict(fighters.FIGHTERS['duckhunt']);told.pop('item_hold')
    monkeypatch.setitem(fighters.FIGHTERS,'duckhunt',told)
    lookup=dict(inputs['lookup'],forward=list(inputs['lookup']['forward']))
    for slot in ('rHave','lHave'):
        lookup['forward'][SLOT[slot]]=od.NONE
    expected=lookup['forward'][SLOT['rHand']]
    assert expected != od.NONE
    output,report=od.build(inputs['pl'],inputs['frozen'],lookup,SOURCE,'duckhunt','Marth',inputs['costume'])
    assert report['verify']['ok'],report['verify']['problems']
    assert report['item_hold']['chosen_by']=='right-hand fallback (no hold bone)'
    facts=od.census(output,'ftDataMars',joints=len(inputs['frozen']['order']))
    written=next(r for r in facts['joints'] if r['consumer']=='modelLookup.itemHold')
    assert written['value']==expected


def test_ecb_with_fewer_than_six_points_keeps_the_same_bounds():
    from fighter_port.own_data import ecb_six
    at = {'body': (0,2), 'left': (-3,1), 'right': (4,1), 'bottom': (0,0)}
    chosen, dropped = ecb_six(list(at), at)
    assert len(chosen) == 6 and set(chosen) == set(at) and dropped == []
    for axis in (0,1):
        assert min(at[n][axis] for n in chosen) == min(p[axis] for p in at.values())
        assert max(at[n][axis] for n in chosen) == max(p[axis] for p in at.values())
    with pytest.raises(ValueError, match='no stage-collision'):
        ecb_six([], {})
