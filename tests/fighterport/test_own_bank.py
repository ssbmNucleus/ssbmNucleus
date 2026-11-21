"""The animation bank of a fighter on its own skeleton (fighter_port/own_bank.py): the parts that need no game files.
The last three tests read the donor's own bank and the source fighter's clips, and run only where those are.

    python -m pytest tests/test_own_bank.py -q
"""
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fighter_port import batch_evaluation as batch
from fighter_port import own_bank as ob
from fighter_port import rig_benchmark as bench
from fighter_port.compat import fobj_reader
from fighter_port.evaluation import Key, sample
from fighter_port.rigmap import euler_xyz

PREFIX = 'PlyTest5K_Share'
SYMBOL = PREFIX + '_ACTION_%s_figatree'


# ---- packing ---------------------------------------------------------------------------------------------------------
def test_a_count_is_packed_seven_bits_a_byte():
    assert [ob.varint(v) for v in (0, 127, 128, 300)] == [b'\x00', b'\x7f', b'\x80\x01', b'\xac\x02']
    for v in (0, 1, 127, 128, 5000, 70000):
        assert fobj_reader.read_varint(ob.varint(v), 0) == (v, len(ob.varint(v)))
    with pytest.raises(ValueError):
        ob.varint(-1)


def test_numbers_take_the_narrowest_form_that_holds_them():
    small, signed, wide, huge = [0.0, 0.5, 1.25], [-0.5, 0.25], [0.0, 300.12], [-1e6, 1e6 + 0.123]
    assert ob.number_format(small, 1e-4) & 0xE0 == 0x80           # one unsigned byte
    assert ob.number_format(signed, 1e-4) & 0xE0 == 0x60          # one signed byte
    assert ob.number_format(wide, 1e-2) & 0xE0 == 0x40            # two bytes
    assert ob.number_format(huge, 1e-4) == 0                      # a float
    assert ob.number_format([], 1e-4) == 0
    rng = np.random.default_rng(1)
    for values in (small, signed, wide, huge, rng.uniform(-3.2, 3.2, 40), rng.uniform(0, 60, 40)):
        flag = ob.number_format(values, 1e-4)
        for v in values:
            back, used = fobj_reader.read_number(ob.pack_number(v, flag), 0, flag)
            assert used == fobj_reader.FORMAT_WIDTH[flag & 0xE0]
            assert abs(back - v) <= (1e-4 if flag else abs(v) * 1e-6)


def test_the_finest_binary_point_is_never_further_off_than_the_first_that_fits():
    values = np.random.default_rng(2).uniform(-1.5, 1.5, 60)
    flag = ob.number_format(values, 1e-2)
    assert flag & 0xE0 == 0x60 and flag & 0x1F == 6               # 1.5 * 64 = 96 fits a signed byte; 128 would not
    worst = max(abs(fobj_reader.read_number(ob.pack_number(v, flag), 0, flag)[0] - v) for v in values)
    assert worst <= 2 ** -7 + 1e-12
    # no finer than the game's own files go (15 places), unless the tolerance itself asks for more
    assert ob.number_format([0.0, 0.001], 1e-4) == 0x80 | 15
    fine = ob.number_format([0.0, 0.0001], 1e-6)
    assert fine & 0xE0 == 0x80 and fine & 0x1F > 15
    assert abs(fobj_reader.read_number(ob.pack_number(0.0001, fine), 0, fine)[0] - 0.0001) <= 1e-6


def test_a_curve_is_written_as_the_commands_the_game_reads():
    assert ob.curve_commands([Key(0., 2.5, 'linear')]) == [(ob.KEY, 2.5, 0.0, 0)]
    keys = [Key(0., 0., 'fixed', 0., 1.), Key(4., 3., 'fixed', .5, .5), Key(6., 4., 'linear', .25, 0.),
            Key(9., 4.5, 'fixed', 0., -.5), Key(12., 2., 'linear', -1., 0.)]
    assert ob.curve_commands(keys) == [
        (ob.SPL, 0., 0., 4), (ob.SLP, 0., 1., 0),     # leaves frame 0 with a slope it did not arrive with
        (ob.SPL, 3., .5, 2),                          # one slope in and out: nothing more to say
        (ob.SLP, 0., .25, 0), (ob.LIN, 4., .25, 3),   # a straight run that ends a curve is led by its arriving slope
        (ob.SPL, 4.5, 0., 3), (ob.SLP, 0., -.5, 0),
        (ob.SLP, 0., -1., 0), (ob.LIN, 2., -1., 0)]   # the last key waits for nothing
    for bad in ([], [Key(1., 0., 'linear')], [Key(0., 0., 'linear'), Key(1.5, 0., 'linear')],
                [Key(0., 0., 'step'), Key(2., 0., 'linear')], [Key(0., 0., 'linear'), Key(0., 1., 'linear')]):
        with pytest.raises(ValueError):
            ob.curve_commands(bad)


def test_a_packed_curve_plays_in_the_game_as_the_curve_it_was_made_from():
    """The bytes, replayed the way the game's fobj.c reads them (a reader that is not this module's), against the
    plain meaning of the keys: a line, or a curve with a slope at each end."""
    keys = [Key(0., .1, 'fixed', 0., .05), Key(5., .6, 'fixed', .12, -.02), Key(9., .4, 'linear', -.1, 0.),
            Key(14., -.3, 'fixed', 0., .2), Key(20., 1.1, 'fixed', .01, .01), Key(31., .2, 'linear', -.15, 0.)]
    value_flag, slope_flag, stream = ob.pack_curve(keys)
    events = fobj_reader.decode(stream, value_flag, slope_flag)
    assert [e['frame'] for e in events if e['op'] != ob.SLP] == [0, 5, 9, 14, 20, 31]
    for t in np.linspace(0, 31, 31 * 8 + 1):
        assert abs(fobj_reader.native_value(events, float(t)) - sample(keys, float(t))) < 5e-4
    assert fobj_reader.native_value(events, 40.0) == pytest.approx(.2, abs=1e-4)      # past its end it holds
    # one key is a value set once
    value_flag, slope_flag, stream = ob.pack_curve([Key(0., -1.25, 'linear')])
    events = fobj_reader.decode(stream, value_flag, slope_flag)
    assert [e['op'] for e in events] == [ob.KEY] and events[0]['value'] == pytest.approx(-1.25, abs=1e-4)


def clip(symbol, frames=10.0, joints=3, value=1.0):
    track = (5, *ob.pack_curve([Key(0., 0., 'linear'), Key(float(frames), value, 'linear')]))
    still = (1, *ob.pack_curve([Key(0., .5, 'linear')]))
    return ob.write_figatree(symbol, frames, [[still, track] if i == 1 else [] for i in range(joints)])


def test_a_clip_archive_reads_back():
    blob = clip(SYMBOL % 'Wait1', frames=12.0, joints=4, value=2.0)
    assert len(blob) % 0x20 == 0 and ob.node_count(blob) == 4
    back = ob.read_clip(blob)
    assert back['symbol'] == SYMBOL % 'Wait1' and back['frames'] == 12.0 and (back['kind'], back['flags']) == (1, 0)
    assert back['counts'] == [0, 2, 0, 0] and [(t.node, t.type, t.start) for t in back['tracks']] == [(1, 1, 0), (1, 5, 0)]
    animation = ob.clip_animation(blob, ['a', 'b', 'c', 'd'])
    assert set(animation.channels) == {'b'} and animation.end == 12.0
    assert batch.curve_values(animation.channels['b']['translateX'], np.array([0., 6., 12.])) == pytest.approx([0, 1, 2], abs=1e-4)
    assert ob.clip_animation(blob, ['a', 'b', 'c', 'd'], only={0}).channels == {}
    assert ob.node_count(b'not a clip') is None


def test_equal_curves_are_stored_once():
    track = (1, *ob.pack_curve([Key(0., 0., 'fixed', 0., .1), Key(30., 1., 'linear', .1, 0.)]))
    one = ob.write_figatree(SYMBOL % 'A', 30, [[track], [], []])
    three = ob.write_figatree(SYMBOL % 'A', 30, [[track], [track], [track]])
    assert len(three) - len(one) <= 0x20 + 24 and len(ob.read_clip(three)['tracks']) == 3
    with pytest.raises(ValueError):
        ob.write_figatree(SYMBOL % 'A', 30, [])


# ---- a job's time ----------------------------------------------------------------------------------------------------
def test_a_part_runs_its_whole_clip_unless_its_keys_say_otherwise():
    assert ob.part_keys({'stem': 'a'}, 30) == [[0, 0.0], [30, 30.0]]
    assert ob.part_keys({'stem': 'a'}, 0) == [[0, 0.0]]
    assert ob.part_keys({'stem': 'a', 'keys': [[0, 10], [5, 20.5]]}, 30) == [[0, 10.0], [5, 20.5]]
    for keys in ([[1, 0.0], [5, 2.0]], [[0, 0.0], [0, 2.0]], [[0, 0.0], [5, 31.0]], [[0, -1.0], [5, 2.0]], [[0, 0.0], [2.5, 3.0]]):
        with pytest.raises(ValueError):
            ob.part_keys({'stem': 'a', 'keys': keys}, 30)


def test_parts_follow_one_another_and_every_whole_frame_is_sampled():
    frames, parts, shows, end = ob.timeline([[[0, 0.0], [4, 4.0]]], 4)
    assert end == 4 and len(frames) == 17 and np.array_equal(frames, np.arange(17) / 4) and np.array_equal(shows, frames)
    # a clip slowed to half speed, then the second half of another
    frames, parts, shows, end = ob.timeline([[[0, 0.0], [4, 2.0]], [[0, 5.0], [3, 8.0]]], 2)
    assert end == 8                                               # 0..4, then 5..8: five frames and four
    assert np.array_equal(frames, [0, .5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 6.5, 7, 7.5, 8])   # nothing between 4 and 5
    assert np.array_equal(parts, [0] * 9 + [1] * 7)
    assert np.allclose(shows[:9], np.arange(9) / 4) and np.allclose(shows[9:], 5 + np.arange(7) / 2)
    # a job of one frame lasts one frame: a clip cannot be nothing long
    frames, parts, shows, end = ob.timeline([[[0, 7.0]]], 4)
    assert end == 1 and np.array_equal(frames, np.arange(5) / 4) and set(shows) == {7.0}


# ---- the root's travel -----------------------------------------------------------------------------------------------
def test_each_part_goes_on_from_where_the_last_ended():
    place = np.array([[0, 0, 0], [0, 0, 2], [0, 0, 4], [0, 1, 0], [0, 1, 3]], dtype=float)
    curve = ob.root_curve(place, np.array([0, 0, 0, 1, 1]))
    assert curve.tolist() == [[0, 0, 0], [0, 0, 2], [0, 0, 4], [0, 0, 4], [0, 0, 7]]
    assert ob.travel_of(curve) == {'Z': (7.0, 7.0)}
    assert ob.travel_of(np.array([[0., 0, 0], [0, 3, 0], [0, 0, 0]])) == {'Y': (3.0, 0.0)}


def poses(n=5):
    """Three joints in a line: the engine's top, the travelling root under it, a limb under that."""
    top = np.broadcast_to(np.eye(4), (n, 4, 4)).copy()
    root, limb = top.copy(), top.copy()
    root[:, :3, 3] = np.c_[np.zeros(n), np.linspace(0, 1, n), np.linspace(0, 8, n)]
    limb[:, :3, :3] = [euler_xyz([0.1 * i, 0.2, -0.05 * i]) for i in range(n)]
    limb[:, :3, 3] = root[:, :3, 3] + [0, 2, 0]
    return {'Top': top, ob.ROOT: root, 'Limb': limb}


def test_travel_comes_off_the_root_and_nothing_else_changes():
    worlds = poses()
    parent = {'Top': None, ob.ROOT: 'Top', 'Limb': ob.ROOT}
    assert ob.under(parent, ob.ROOT) == [ob.ROOT, 'Limb'] and ob.under(parent, 'Top') == ['Top', ob.ROOT, 'Limb']
    parts = np.zeros(5, dtype=int)
    out = ob.settle_root(worlds, parts, 'Y', ob.under(parent, ob.ROOT))
    assert np.array_equal(out['Top'], worlds['Top'])                               # the engine's joint is never moved
    assert np.allclose(out[ob.ROOT][:, 2, 3], 0) and np.allclose(out[ob.ROOT][:, 1, 3], np.linspace(0, 1, 5))
    was = np.linalg.solve(worlds[ob.ROOT], worlds['Limb'])
    assert np.allclose(np.linalg.solve(out[ob.ROOT], out['Limb']), was)            # the limb's own numbers are as they were
    assert np.array_equal(worlds[ob.ROOT][:, 2, 3], np.linspace(0, 8, 5))          # and what was handed in is not changed
    kept = ob.settle_root(worlds, parts, 'XYZ', ob.under(parent, ob.ROOT))
    assert all(np.allclose(kept[j], worlds[j]) for j in worlds)


def test_what_becomes_of_travel_follows_the_donor_actions_flag():
    forward, lunge = {'Z': (30.0, 30.0)}, {'Z': (5.0, 0.0)}
    assert ob.travel_policy('Wait1', False, {}, {})['owner'] == 'LOCAL_POSE'
    # the engine's own physics walks the fighter, flag or no flag
    for flag in (False, True):
        row = ob.travel_policy('Run', flag, forward, forward)
        assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('PHYSICS', '', 'Z', False)
    # read in the engine: the roll's physics takes forward travel, and only that
    row = ob.travel_policy('EscapeF', True, forward, {'Y': (1.0, 0.0), 'Z': (35.0, 35.0)})
    assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('ANIMATION_DELTA', 'Z', 'Y', False)
    # not read: the donor's own clip is the evidence, and the row says it is unsure
    row = ob.travel_policy('DownBackU', True, {'Z': (27.0, -27.0)}, {'Z': (26.0, -26.0)})
    assert (row['owner'], row['keep'], row['unsure']) == ('ANIMATION_DELTA', 'Z', True)
    row = ob.travel_policy('PassiveWall', True, {}, {'Z': (2.7, 2.7)})
    assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('ZERO_BY_DEFAULT', '', 'Z', True)
    # a donor clip that barely stirs is no evidence that the state moves the fighter by its clip
    row = ob.travel_policy('PassiveWallJump', True, {'Z': (0.256, 0.0)}, {'Z': (5.8, 5.8)})
    assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('ZERO_BY_DEFAULT', '', 'Z', True)
    # the flag off: a lunge that comes back is pose; travel that does not would snap back, so it comes off
    row = ob.travel_policy('Attack12', False, {}, lunge)
    assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('LOCAL_POSE', 'Z', '', False)
    row = ob.travel_policy('WallDamage', False, {}, {'Z': (5.0, 5.0)})
    assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('ZERO_BY_DEFAULT', '', 'Z', True)
    # the campaign switched this action's flag on; with it off the travel cannot stay
    row = ob.travel_policy('CatchDash', False, {}, {'Z': (21.8, 21.8)})
    assert (row['keep'], row['cancel'], row['unsure']) == ('', 'Z', True) and 'flag' in row['why']
    # a clip that serves actions both ways is treated as if the flag were off
    row = ob.travel_policy('WallDamage', True, forward, forward, mixed=True)
    assert (row['keep'], row['cancel'], row['unsure']) == ('', 'Z', True)
    # the job's own word settles it
    row = ob.travel_policy('Run', False, {}, {'Y': (1.0, 1.0), 'Z': (17.0, 17.0)}, wanted='Z')
    assert (row['owner'], row['keep'], row['cancel'], row['unsure']) == ('JOB', 'Z', 'Y', False)
    assert ob.travel_policy('Run', False, {}, forward, wanted='')['cancel'] == 'Z'


# ---- curves from poses -----------------------------------------------------------------------------------------------
def little_rig():
    rest = {'Top': dict(r=[0., 0., 0.], t=[0., 0., 0.], s=[1., 1., 1.]),
            ob.ROOT: dict(r=[0., 0., 0.], t=[0., 0., 0.], s=[1., 1., 1.]),
            'Arm': dict(r=[0.3, -0.2, 0.1], t=[1., 2., 0.], s=[1., 1., 1.]),
            'Hand': dict(r=[0., 0., 3.0], t=[0., 3., 0.], s=[1., 1., 1.])}
    parent = {'Top': None, ob.ROOT: 'Top', 'Arm': ob.ROOT, 'Hand': 'Arm'}
    rig = SimpleNamespace(order=list(rest), parent=parent, rest=rest, local={}, world={})
    for j in rig.order:
        m = np.eye(4)
        m[:3, :3] = euler_xyz(rest[j]['r']) * np.array(rest[j]['s'])
        m[:3, 3] = rest[j]['t']
        rig.local[j] = m
        rig.world[j] = rig.world[parent[j]] @ m if parent[j] is not None else m
    return rig


def little_motion(rig, frames):
    """The arm swings and stretches, the root walks, the hand stays at rest."""
    worlds = {j: [] for j in rig.order}
    for f in frames:
        local = {j: m.copy() for j, m in rig.local.items()}
        local[ob.ROOT][:3, 3] = [0., 0.1 * np.sin(f / 3), 0.4 * f]
        local['Arm'][:3, :3] = euler_xyz([0.3 + 0.8 * np.sin(f / 4), -0.2 + 0.02 * f, 0.1 + 2.9 * np.sin(f / 9)]) * (1 + 0.01 * f)
        for j in rig.order:
            p = rig.parent[j]
            worlds[j].append(worlds[p][-1] @ local[j] if p is not None else local[j])
    return {j: np.array(w) for j, w in worlds.items()}


def test_a_joints_own_numbers_match_the_slow_way_of_working_them_out():
    rig = little_rig()
    frames = np.arange(0, 20.25, .25)
    worlds = little_motion(rig, frames)
    tracks, lean = ob.local_tracks(rig, worlds)
    slow = bench.local_vectors(rig, [batch.frame(worlds, i) for i in range(len(frames))], project_shear=True)
    assert lean < 1e-7
    for j in rig.order:
        assert np.allclose(tracks[j][:, 3:], slow[j][:, 3:], atol=1e-9)             # place and size
        for a, b in zip(tracks[j][::7], slow[j][::7]):
            assert np.allclose(euler_xyz(a[:3]), euler_xyz(b[:3]), atol=1e-7)        # the same turn, however written
        assert np.abs(np.diff(tracks[j][:, :3], axis=0)).max() < 1.0                  # no jump of a whole turn
    # a joint that never leaves rest reads as its rest, not as the same turn written another way
    assert np.allclose(tracks['Hand'][:, :3], rig.rest['Hand']['r'], atol=1e-9)


def test_a_joint_leaning_under_an_uneven_parent_is_squared_and_said():
    rig = little_rig()
    worlds = little_motion(rig, np.arange(3.0))
    worlds['Hand'] = worlds['Hand'].copy()
    worlds['Hand'][:, :3, 0] += 0.2 * worlds['Hand'][:, :3, 1]                        # a lean no joint can hold
    tracks, lean = ob.local_tracks(rig, worlds)
    assert lean > 0.01 and np.isfinite(tracks['Hand']).all()
    worlds['Hand'][:, :3, :3] = 0
    with pytest.raises(ValueError):
        ob.local_tracks(rig, worlds)


def test_curves_sit_on_whole_frames_and_a_joint_at_rest_gets_none():
    rig = little_rig()
    frames = np.arange(0, 24.25, .25)
    tracks, _ = ob.local_tracks(rig, little_motion(rig, frames))
    curves = ob.author(rig, frames, tracks, lambda joint, kind: 0.0005)
    assert not any(j in ('Top', 'Hand') for j, _ in curves)
    assert {kind for j, kind in curves if j == ob.ROOT} == {6, 7}                     # it moves up and forward, nothing else
    assert {kind for j, kind in curves if j == 'Arm'} == {1, 2, 3, 8, 9, 10}
    assert all(k.time == int(k.time) for keys in curves.values() for k in keys)
    with pytest.raises(ValueError):
        ob.author(rig, frames[1:], {j: t[1:] for j, t in tracks.items()}, lambda joint, kind: 0.0005)


def test_a_joint_with_a_long_reach_is_held_tighter_than_a_fingertip():
    rig = little_rig()
    worlds = little_motion(rig, np.arange(0, 8.25, .25))
    reach = ob.reaches(rig, worlds)
    assert reach['Hand'] == 0.0 and reach['Arm'] == pytest.approx(3.0 * 1.08, rel=0.01)     # the hand, three units out, at the arm's longest
    assert reach['Top'] >= reach[ob.ROOT] >= reach['Arm']
    allow = ob.tolerances(dict(reach, Arm=20.0, Hand=0.0), 0.001, 20.0)                     # 0.02 units of leeway
    assert allow('Arm', 1) == pytest.approx(0.001)                                          # 0.02 over a reach of 20
    assert allow('Hand', 2) == pytest.approx(0.02)                                          # over the least reach, a twentieth of the height
    assert allow('Arm', 6) == pytest.approx(0.02) and allow('Arm', 9) == ob.SIZE_TOLERANCE
    assert ob.tolerances({'Arm': 500.0}, 0.0001, 20.0)('Arm', 3) == ob.TURN_FLOOR           # never asked finer than the floor
    assert ob.tolerances({'Arm': 0.0}, 0.5, 20.0)('Arm', 3) == ob.TURN_CAP                  # nor let go further than the cap
    # each step of the ladder is looser than the last
    assert all(b > a for a, b in zip(ob.BUDGETS, ob.BUDGETS[1:]))


def test_a_swing_within_one_frame_is_told_apart_from_a_poor_fit():
    rig = little_rig()
    frames = np.arange(0, 6.25, .25)
    worlds = little_motion(rig, frames)
    slow = ob.sharpest_turn(rig, worlds, frames, 'Hand', 2.5)
    assert 0 < slow < 30
    snapped = {j: w.copy() for j, w in worlds.items()}
    for j in ('Arm', 'Hand'):                                    # from frame 3 on the arm is a quarter turn further round
        snapped[j][frames >= 3] = snapped[j][frames >= 3] @ np.block([[euler_xyz([0, 0, np.pi / 2]), np.zeros((3, 1))],
                                                                       [np.zeros((1, 3)), np.ones((1, 1))]])
    assert ob.sharpest_turn(rig, snapped, frames, 'Hand', 2.5) > 80           # the hand's error there is the arm's snap
    assert ob.sharpest_turn(rig, snapped, frames, 'Hand', 4.5) == ob.sharpest_turn(rig, worlds, frames, 'Hand', 4.5)
    assert ob.sharpest_turn(rig, snapped, frames, 'Hand', 6.0) < 30           # the last frame looks back at the one before


def test_a_written_clip_poses_the_rig_as_the_motion_it_was_made_from():
    rig = little_rig()
    frames = np.arange(0, 24.25, .25)
    worlds = little_motion(rig, frames)
    tracks, _ = ob.local_tracks(rig, worlds)
    blob = ob.encode(rig, SYMBOL % 'Swing', 24, ob.author(rig, frames, tracks, lambda joint, kind: 0.0005))
    assert ob.node_count(blob) == 4 and ob.read_clip(blob)['counts'][0] == 0
    fine = np.arange(0, 24 + 1 / 16, 1 / 16)
    posed = batch.animation_worlds(ob.clip_animation(blob, rig.order), rig, fine)
    truth = little_motion(rig, fine)
    assert max(np.abs(posed[j][:, :3, 3] - truth[j][:, :3, 3]).max() for j in rig.order) < 0.02
    looser = ob.encode(rig, SYMBOL % 'Swing', 24, ob.author(rig, frames, tracks, lambda joint, kind: 0.02))
    assert len(looser) < len(blob)


# ---- the bank --------------------------------------------------------------------------------------------------------
def little_donor(clips, flags=()):
    """A fighter data file with nothing in it but an action table, and its bank. `clips`: [(symbol or None, bytes)]:
    one action each, an action with the same symbol as one before it sharing that clip."""
    from vault.echo import datroot
    bank, spans = ob.assemble([(s, b) for i, (s, b) in enumerate(clips) if s and s not in [c[0] for c in clips[:i]]])
    table = 0x20
    names = table + 24 * len(clips)
    data = bytearray(names)
    struct.pack_into('>I', data, 0x0C, table)
    relocations, at = [0x0C], {}
    for i, (symbol, _blob) in enumerate(clips):
        if symbol is None:
            continue
        if symbol not in at:
            at[symbol] = len(data)
            data += symbol.encode() + b'\0'
        struct.pack_into('>IIIIII', data, table + 24 * i, at[symbol], *spans[symbol], 0,
                         flags[i] if i < len(flags) else 0x12, 0)
        relocations.append(table + 24 * i)
    data += bytes(-len(data) % 4)
    return datroot.build(bytes(data), relocations, [(0, 'ftDataTest')], []), bank


def test_the_donors_own_symbols_are_told_from_other_fighters():
    from vault.echo.subactions import FighterDat
    pl, _bank = little_donor([(SYMBOL % 'Wait1', clip(SYMBOL % 'Wait1')), (SYMBOL % 'Run', clip(SYMBOL % 'Run')),
                              ('PlyOther_Share_ACTION_Thrown_figatree', clip('PlyOther_Share_ACTION_Thrown_figatree'))])
    assert ob.donor_prefix(FighterDat(pl).actions) == PREFIX


def test_with_no_jobs_each_action_takes_the_clip_of_its_own_name():
    jobs, without = ob.default_jobs('nobody', {'Wait1': None, 'Dash': None, 'Odd': None}, {'Wait1': True},
                                    ['a00wait1', 'a02dash', 'z99unused'])
    assert jobs == [dict(motion='Dash', parts=[dict(stem='a02dash')], loop=False),
                    dict(motion='Wait1', parts=[dict(stem='a00wait1')], loop=True)]
    assert list(without) == ['Odd']


def test_a_bank_is_put_together_repointed_and_read_back():
    other = 'PlyOther_Share_ACTION_Thrown_figatree'
    old = [(SYMBOL % 'Wait1', clip(SYMBOL % 'Wait1', joints=2)), (None, b''), (SYMBOL % 'Run', clip(SYMBOL % 'Run', joints=2)),
           (other, clip(other, joints=7)), (SYMBOL % 'Wait1', b'')]
    pl, bank = little_donor(old)
    new = [(SYMBOL % 'Wait1', clip(SYMBOL % 'Wait1', frames=40, joints=5)), (SYMBOL % 'Run', clip(SYMBOL % 'Run', frames=90, joints=5)),
           (other, old[3][1])]
    new_bank, spans = ob.assemble(new)
    assert all(start % 0x20 == 0 for start, _ in spans.values()) and len(new_bank) % 0x20 == 0
    assert all(new_bank[start:start + length] == blob for (symbol, blob), (start, length) in zip(new, spans.values()))
    new_pl = ob.repoint(pl, spans)
    assert len(new_pl) == len(pl) and sum(a != b for a, b in zip(new_pl, pl)) <= 8 * 3
    checked = ob.verify(new_pl, new_bank, pl, bank, PREFIX, 5, engine=[0, 4])
    assert checked['ok'], checked['problems']
    assert (checked['rows'], checked['clips'], checked['own'], checked['foreign']) == (4, 3, 2, 1)
    assert checked['largest']['bytes'] == max(len(b) for _, b in new) and checked['bank_bytes'] == len(new_bank)
    with pytest.raises(ValueError):
        ob.assemble(new + [new[0]])

    def problems(**changed):
        args = dict(new_pl=new_pl, new_aj=new_bank, donor_pl=pl, donor_aj=bank, prefix=PREFIX, nodes=5)
        args.update(changed)
        return ' '.join(ob.verify(**args)['problems'])
    # a table one entry off still points at good clips, only the wrong ones
    swapped = dict(spans)
    swapped[SYMBOL % 'Wait1'], swapped[SYMBOL % 'Run'] = spans[SYMBOL % 'Run'], spans[SYMBOL % 'Wait1']
    assert 'the cut holds' in problems(new_pl=ob.repoint(pl, swapped))
    assert 'the rig has 6' in problems(nodes=6)                                    # the wrong count of joints
    longer = dict(spans)
    longer[SYMBOL % 'Run'] = (spans[SYMBOL % 'Run'][0], spans[SYMBOL % 'Run'][1] + 0x20)   # the game checks a clip's own length
    assert 'the archive says' in problems(new_pl=ob.repoint(pl, longer), new_aj=new_bank + bytes(0x20))
    assert 'the game takes' in problems(capacity=0x40)                             # a clip too long
    damaged = bytearray(new_bank)
    damaged[spans[other][0] + 0x30] ^= 1
    assert "not the donor's byte for byte" in problems(new_aj=bytes(damaged))
    elsewhere = bytearray(new_pl)
    elsewhere[0x20 + 0x10] ^= 1                                                    # a byte outside the table
    assert 'outside the table' in problems(new_pl=bytes(elsewhere))
    engine = ob.write_figatree(SYMBOL % 'Run', 9, [[(5, *ob.pack_curve([Key(0., 1., 'linear')]))], [], [], [], []])
    moved_bank, moved_spans = ob.assemble([new[0], (SYMBOL % 'Run', engine), new[2]])
    assert "engine's own joints" in ' '.join(
        ob.verify(ob.repoint(pl, moved_spans), moved_bank, pl, bank, PREFIX, 5, engine=[0, 4])['problems'])


# ---- with the game's files ---------------------------------------------------------------------------------------------
SCRATCH = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2]) / 'app' / 'scratch'
DONOR = SCRATCH / 'brawl-oneshot' / 'port' / 'donor'
ROOT = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
RIG = SCRATCH / 'duckhunt-native' / 'rig' / 'rig-duckhunt.json'
has_donor = (DONOR / 'PlMs.dat').exists() and (DONOR / 'PlMsAJ.dat').exists()
has_source = has_donor and RIG.exists() and (ROOT / 'gamedata' / 'fighter' / 'duckhunt' / 'motion' / 'body' / 'c00').exists()


def commands(stream, value_flag, slope_flag):
    """A packed curve back to its commands, waits and all (the other way round from `pack_commands`)."""
    at, out = 0, []
    while at < len(stream):
        word, at = fobj_reader.read_varint(stream, at)
        op = word & 15
        for _ in range((word >> 4) + 1):
            value = slope = 0.0
            wait = 0
            if op != ob.SLP:
                value, at = fobj_reader.read_number(stream, at, value_flag)
            if op in (ob.SPL, ob.SLP):
                slope, at = fobj_reader.read_number(stream, at, slope_flag)
            if op in (ob.CON, ob.LIN, ob.SPL0, ob.SPL):
                wait, at = fobj_reader.read_varint(stream, at)
            out.append((op, value, slope, wait))
    return out


@pytest.mark.skipif(not has_donor, reason="needs the donor's own files")
def test_the_games_own_curves_pack_back_to_what_they_were():
    """Every curve of the donor's bank, unpacked to commands and packed again by this module. The game's own tool
    sometimes spends a spare byte on a run's count; apart from that the bytes are the game's."""
    from vault.echo import datroot
    from vault.echo.subactions import FighterDat
    aj = (DONOR / 'PlMsAJ.dat').read_bytes()
    seen, same, total = set(), 0, 0
    for action in FighterDat((DONOR / 'PlMs.dat').read_bytes()).actions:
        if not action.symbol or action.symbol in seen:
            continue
        seen.add(action.symbol)
        blob = aj[action.anim_offset:action.anim_offset + action.anim_size]
        data = datroot.parse(blob)[0]
        for t in ob.read_clip(blob)['tracks'][::5]:
            stream = data[t.pointer:t.pointer + t.length]
            was = commands(stream, t.value_flag, t.slope_flag)
            again = ob.pack_commands(was, t.value_flag, t.slope_flag)
            assert commands(again, t.value_flag, t.slope_flag) == was
            same += again == stream
            total += 1
    assert total > 5000 and same / total > 0.99


@pytest.mark.skipif(not has_donor, reason="needs the donor's own files")
def test_the_donors_own_travel_is_read_from_its_clips():
    from vault.echo.subactions import FighterDat
    aj = (DONOR / 'PlMsAJ.dat').read_bytes()
    actions = {a.motion: a for a in FighterDat((DONOR / 'PlMs.dat').read_bytes()).actions if a.symbol}
    travel = lambda m: ob.donor_travel(aj[actions[m].anim_offset:actions[m].anim_offset + actions[m].anim_size], 1)
    assert travel('Wait1') == {}
    assert travel('EscapeF')['Z'] == pytest.approx((35.0, 35.0), abs=0.1)          # a roll goes forward and stays
    lunge = travel('AttackS4')['Z']
    assert lunge[0] > 3 and abs(lunge[1]) < 0.01                                   # a forward smash steps out and back
    assert not actions['AttackS4'].flags & ob.EXTRACTS and actions['EscapeF'].flags & ob.EXTRACTS


@pytest.mark.skipif(not has_source, reason="needs the donor's files, the frozen rig and the source fighter's clips")
def test_a_whole_bank_is_built_and_reads_back(tmp_path):
    import json
    from fighter_port import compat
    compat.install()
    pl, aj = (DONOR / 'PlMs.dat').read_bytes(), (DONOR / 'PlMsAJ.dat').read_bytes()
    frozen = json.loads(RIG.read_text('utf-8'))
    jobs = [dict(motion='Wait1', parts=[dict(stem='a00wait1', keys=[[0, 0.0], [20, 20.0]])], loop=True),
            dict(motion='AttackDash', parts=[dict(stem='c00attackdash')]),
            dict(motion='Run', parts=[dict(stem='a02run'), dict(stem='a02run', keys=[[0, 1.0], [7, 15.0]])]),
            dict(motion='Appeal', parts=[dict(stem='e01thrownf')]),              # a clip the reader refuses
            dict(motion='NoSuchAction', parts=[dict(stem='a00wait1')])]
    log = []
    new_pl, new_aj, report = ob.build(pl, aj, frozen, ROOT, 'duckhunt', jobs, log=log.append, cache=tmp_path)
    t = report['totals']
    assert (t['rows'], t['own_clips'], t['with_source'], t['held'], t['foreign']) == (272, 209, 3, 206, 4)
    assert report['verify']['ok'] and t['largest']['bytes'] <= 0x8000 and len(new_aj) == t['bank_bytes']
    assert report['jobs_for_no_action'] == ['NoSuchAction'] and 'e01thrownf' in report['refused_clips']
    assert [j['motion'] for j in report['job_list']] == sorted(j['motion'] for j in jobs)
    assert 'override' in report['held']['Appeal']
    rows = {r['motion']: r for r in report['rows'].values() if r['kind'] != 'FOREIGN'}
    assert rows['Wait1']['frames'] == 20 and rows['Run']['frames'] == 15 + 1 + 7
    assert rows['AttackDash']['travel']['keep'] == 'Z' and rows['AttackDash']['root_reach']['Z'] == pytest.approx(36.0, abs=0.01)
    assert rows['Run']['travel']['cancel'] == 'Z' and rows['Run']['root_reach'] == {}
    assert rows['Landing']['kind'] == 'HELD' and rows['Landing']['frames'] == rows['Landing']['donor_frames']
    assert all(r['error']['whole'] < 0.0025 for r in rows.values())
    # the written files, by the written table: the right clip under every action, on the new rig
    checked = ob.verify(new_pl, new_aj, pl, aj, 'PlyMars5K_Share', 102)
    assert checked['ok'] and checked['own'] == 209
    # a second build takes every clip from the cache and writes the same bytes
    again_pl, again_aj, again = ob.build(pl, aj, frozen, ROOT, 'duckhunt', jobs, log=log.append, cache=tmp_path)
    assert (again_pl, again_aj) == (new_pl, new_aj) and again['totals']['cached'] == 209


# ---- a track for a bone the skeleton lacks ------------------------------------------------------------------------------
def test_a_track_for_a_bone_the_skeleton_lacks_is_passed_over_and_named_not_a_reason_to_refuse_the_clip():
    # Shulk's S_Hip_hit is on 318 of his 359 clips and in no model file: the own route's reader refused his standing
    # clip for it, and the driver stopped. The reader is given every bone as one it may pass over.
    from fighter_port.source_preflight import ANY_BONE, PreflightError, RawSource, Track
    bones = [('Trans', None, np.eye(4)), ('Hip', 'Trans', np.eye(4))]
    one = Track(np.zeros((1, 3)), np.array([[0.0, 0.0, 0.0, 1.0]]), np.ones((1, 3)), False, {})
    tracks = {'Trans': one, 'Hip': one, 'S_Hip_hit': one}
    with pytest.raises(PreflightError):
        RawSource(bones, tracks, 0)
    raw = RawSource(bones, tracks, 0, allow_unbound=ANY_BONE)
    assert sorted(raw.tracks) == ['Hip', 'Trans'] and raw.ignored == ['S_Hip_hit']
    assert 'anything' in ANY_BONE


def test_compact_fit_discards_only_channels_within_rest_tolerance_and_keeps_duration():
    rig = little_rig()
    frames = np.arange(0., 40.25, .25)
    tracks = {j: np.tile(np.r_[rig.rest[j]['r'], rig.rest[j]['t'], rig.rest[j]['s']], (len(frames), 1))
              for j in rig.order}
    # Constant exporter noise costs table rows even though rest is an equally good approximation.
    for j in ('Arm', 'Hand'):
        tracks[j][:, 3:6] += 0.0002
    tracks['Arm'][:, 3] += 0.5  # a real offset must survive compaction
    source = SimpleNamespace(target=rig, height=20.)
    reach = {j: 20. for j in rig.order}
    regular = ob.encode(rig, SYMBOL % 'Noise', 40,
                        ob.author(rig, frames, tracks, ob.tolerances(reach, ob.BUDGETS[0], source.height)))
    blob, row = ob.fit(source, SYMBOL % 'Noise', 40, frames, tracks, reach, len(regular)-1)
    assert row['compact'] and row['budget'] == ob.BUDGETS[0]
    assert ob.read_clip(blob)['frames'] == 40
    assert row['curves'] == 1
    posed = batch.animation_worlds(ob.clip_animation(blob, rig.order), rig, frames)
    assert np.isfinite(posed['Hand']).all()
    assert {t.type for t in ob.read_clip(blob)['tracks']} == {5}
    # A fitting clip retains its original encoding, with no relaxed retry.
    same, report = ob.fit(source, SYMBOL % 'Noise', 40, frames, tracks, reach, len(regular))
    assert same == regular and not report['compact'] and len(report['tried']) == 1


def test_scale_tolerance_respects_limb_reach_and_small_scales():
    mins = {('Long', 8): 1., ('Short', 8): 1., ('Hidden', 8): 0.0001}
    allow = ob.tolerances({'Long': 40., 'Short': 1., 'Hidden': 40.}, 0.001, 20., mins)
    assert allow('Long', 8) == pytest.approx(0.0005)
    assert allow('Short', 8) == ob.SIZE_CAP
    assert allow('Hidden', 8) == pytest.approx(5e-8)
    # Relative scale error times reach does not exceed the distance budget.
    for name, reach in [('Long', 40.), ('Short', 1.), ('Hidden', 40.)]:
        assert allow(name, 8) / mins[name, 8] * reach <= 0.02 + 1e-12


def test_repeated_tolerances_reuse_reduction_without_changing_encoded_curves():
    from fighter_port.scalar_curves import reduce_track
    rig=little_rig(); frames=np.arange(0., 8.25, .25)
    tracks,_=ob.local_tracks(rig,little_motion(rig,frames))
    calls=[]
    def counted(*args):
        calls.append(1)
        return reduce_track(*args)
    reduced={};allow=lambda j,k: 0.0005
    a=ob.author(rig,frames,tracks,allow,counted,reduced=reduced)
    count=len(calls)
    b=ob.author(rig,frames,tracks,allow,counted,reduced=reduced)
    assert count>0 and len(calls)==count
    assert ob.encode(rig,SYMBOL % 'Cached',8,a)==ob.encode(rig,SYMBOL % 'Cached',8,b)
