"""The driver's route for a fighter on its own skeleton (fighter_port/own_route.py).

The first tests need no game files: a spec row as a clip job, a hitbox on the fighter's own joint, the specials,
and that the driver's own functions do what they did when the route is not asked for. The last ones read Duck
Hunt's own files and run only where those are (ULTIMATE_DUMP, and the folder `own_skeleton.prepare` left).

    python -m pytest tests/test_own_route.py -q
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fighter_port import compat

compat.install()
from fighter_port import combat, oneshot, own_bank, own_route as route      # noqa: E402

ROOT = os.environ.get('ULTIMATE_DUMP')
DH = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2]) / 'app' / 'scratch' / 'duckhunt-native'
real = pytest.mark.skipif(not ROOT or not (DH / 'rig' / 'rig-duckhunt.json').exists()
                          or not (DH / 'data' / 'PlMs.dat').exists(),
                          reason="needs ULTIMATE_DUMP and Duck Hunt's own-skeleton folder (rig/, data/)")

ORDER = ['__engine_Top', 'Trans', '__engine_XRot', '__engine_YRot', 'Rot', 'Hip', '__chart_before_KneeR', 'KneeR',
         'DuckHead', 'Throw']
PARENT = dict(zip(ORDER, [None, '__engine_Top', 'Trans', '__engine_XRot', '__engine_YRot', 'Rot', 'Hip',
                          '__chart_before_KneeR', 'Hip', 'Trans']))
FROZEN = {'order': ORDER, 'parent': PARENT,
          'rest': {j: {'r': [0.0, 0.0, 0.0], 't': [0.0, 0.0, 0.0], 's': [1.0, 1.0, 1.0]} for j in ORDER}}


def row(motion='Attack11', stem='c00attack11', **more):
    return dict({'id': f'{stem}-{motion}'.lower(), 'source': f'motion/body/c00/{stem}.nuanmb', 'target_motion': motion,
                 'category': 'normal'}, **more)


def length(of):
    return lambda stem: of[stem]


# ---- a spec row as a clip job ----------------------------------------------------------------------------------------
def test_a_whole_clip_is_the_job_own_bank_makes_by_itself():
    job = route.job_from_row(row('Wait1', 'a00wait1'), length({'a00wait1': 119.0}), loop=True)
    assert job == {'motion': 'Wait1', 'parts': [{'stem': 'a00wait1'}], 'loop': True}      # no keys: the cache's own job


def test_time_keys_carry_over_and_a_clip_that_lasts_its_keys_is_a_frame_longer():
    keys = [[0, 0.0], [25, 25.0], [33, 33.0]]
    plain = route.job_from_row(row(time_keys=keys), length({'c00attack11': 40.0}))
    assert plain['parts'] == [{'stem': 'c00attack11', 'keys': keys}] and plain['loop'] is False
    held = route.job_from_row(row(time_keys=keys, hold_end=True), length({'c00attack11': 40.0}))
    assert held['parts'][0]['keys'] == keys + [[34, 34.0]]             # it plays on at the speed it was going
    ended = route.job_from_row(row(time_keys=keys, hold_end=True), length({'c00attack11': 33.0}))
    assert ended['parts'][0]['keys'] == keys + [[34, 33.0]]            # ... or holds the clip's last frame
    slowed = route.row_keys([[0, 0.0], [41, 27.5]], 40.0, hold_end=True)
    assert slowed[-1][0] == 42 and slowed[-1][1] == pytest.approx(27.5 + 27.5 / 41)
    # the frames own_bank stores are the frames the driver stores: the last key's frame
    frames, parts, shows, end = own_bank.timeline([own_bank.part_keys(held['parts'][0], 40)], 1)
    assert end == 34 and list(shows[:3]) == [0.0, 1.0, 2.0]


def test_a_clip_with_no_keys_that_lasts_its_length_holds_its_last_frame():
    assert route.row_keys(None, 20.0) is None
    assert route.row_keys(None, 20.0, hold_end=True) == [[0, 0.0], [20, 20.0], [21, 20.0]]
    assert route.row_keys(None, 0.0, hold_end=True) == [[0, 0.0], [1, 0.0]]         # a clip of one pose


def test_a_stretch_of_a_clip_and_keys_past_its_end():
    cut = route.job_from_row(row('SpecialNLoop', 'd00specialn', time_keys=[[0, 1.0], [1, 2.0]], window=[1, 2]),
                             length({'d00specialn': 41.0}))
    assert cut['parts'] == [{'stem': 'd00specialn', 'keys': [[0, 1.0], [1, 2.0]]}]
    assert route.row_keys([[0, 0.0], [50, 50.0]], 41.0) == [[0, 0.0], [50, 41.0]]
    for bad in ([[1, 0.0], [5, 5.0]], [[0, 0.0], [5, 5.0], [5, 6.0]], [[0, 4.0], [5, 2.0]]):
        with pytest.raises(ValueError):
            route.row_keys(bad, 41.0)


def test_joined_clips_hand_over_on_the_frame_the_driver_counts():
    parts = [{'stem': 'a', 'time_keys': [[0, 0.0], [4, 8.0]]}, {'stem': 'b', 'time_keys': [[0, 0.0], [5, 5.0]]}]
    joined = route.job_from_row(row('SpecialS1', 'a', parts=parts), length({'a': 20.0, 'b': 5.0}))
    assert joined['parts'] == [{'stem': 'a', 'keys': [[0, 0.0], [3, 6.0]]},          # frames 0 to 3; b starts on 4
                               {'stem': 'b', 'keys': [[0, 0.0], [5, 5.0]]}]
    maps = [own_bank.part_keys(p, {'a': 20, 'b': 5}[p['stem']]) for p in joined['parts']]
    frames, which, shows, end = own_bank.timeline(maps, 1)
    assert end == 4 + 5                                                # what moveset.join_parts stores
    assert int(np.argmax(which == 1)) == oneshot.part_starts(parts)[1] == 4
    longer = route.joined_parts(parts, length({'a': 20.0, 'b': 5.0}), hold_end=True)
    assert longer[1]['keys'] == [[0, 0.0], [5, 5.0], [6, 5.0]]         # nothing more to play: the last pose, held
    one = route.joined_parts([{'stem': 'a', 'time_keys': [[0, 2.0], [1, 3.0]]}, parts[1]], length({'a': 20.0, 'b': 5.0}))
    assert one[0]['keys'] == [[0, 2.0]]                                # a part of one frame


def test_who_moves_the_fighter_is_said_once():
    engine = {'target': 'JOBJ_1', 'basis': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    state = row('Attack12', root_motion_joint='Trans', engine_root=engine, travel='state')
    slide = row('AttackHi3', root_motion_joint='Trans', engine_root=engine, travel='code')
    dropped = row('WalkSlow', root_motion_joint='Trans')
    posed = row('EscapeN')
    at = length({'c00attack11': 30.0})
    assert route.job_from_row(state, at)['travel'] == 'XYZ' and route.moves_by_clip(state)
    assert route.job_from_row(slide, at)['travel'] == 'XYZ' and route.moves_by_clip(slide)
    assert route.job_from_row(dropped, at)['travel'] == '' and not route.moves_by_clip(dropped)
    assert 'travel' not in route.job_from_row(posed, at) and not route.moves_by_clip(posed)
    # with no code file nobody would take a 'code' row's travel: the flag is not set and the bank's own rule decides
    assert 'travel' not in route.job_from_row(slide, at, code=False) and not route.moves_by_clip(slide, code=False)
    assert route.job_from_row(state, at, code=False)['travel'] == 'XYZ'


def test_rows_become_jobs_and_a_row_that_cannot_is_named():
    clips = [row('Wait1', 'a00wait1'), row('Attack11', time_keys=[[0, 0.0], [5, 5.0]], hold_end=True),
             row('Attack12', 'c00attack12', blocked='not this fighter'),
             row('Attack13', 'c00attack13', time_keys=[[0, 3.0], [4, 1.0]])]
    jobs, by_id, errors = route.jobs_from_spec(clips, length({'a00wait1': 10.0, 'c00attack11': 9.0, 'c00attack13': 9.0}),
                                               loops={'Wait1'})
    assert [j['motion'] for j in jobs] == ['Wait1', 'Attack11'] and jobs[0]['loop'] and not jobs[1]['loop']
    assert by_id['c00attack11-attack11'] is jobs[1]
    assert [e[0] for e in errors] == ['c00attack12-attack12', 'c00attack13-attack13']


# ---- a hitbox on the fighter's own joint -----------------------------------------------------------------------------
def test_a_bone_is_the_joint_of_its_name():
    from echo_ultimate.gamedata.prc import hash40
    names = route.joint_names(ORDER)
    assert names['kneer'] == 7 and names['throw'] == 9 and names['trans'] == 1
    assert names[f"0x{hash40('duckhead'):010x}"] == 8                  # a name the reader only has the hash of
    assert not any(k.startswith('__') for k in names) and 'top' not in names
    with pytest.raises(ValueError):
        route.joint_names(['Hip', 'hip'])


def test_a_hitbox_keeps_its_bone_and_offset():
    placer = route.OwnPlacer(ORDER)
    assert placer.place('any', 'kneer', [1.0, -2.0, 3.5], [4, 5, 6], None) == (7, [1.0, -2.0, 3.5], 0.0)
    assert placer.place('any', 'KneeR', [0, 0, 0]) == (7, [0.0, 0.0, 0.0], 0.0)
    assert placer.place('any', 'sword1', [0, 0, 0]) is None            # a bone the rig does not have
    assert placer.place('any', '__chart_before_kneer', [0, 0, 0]) is None
    assert placer.scale('any') == 1.0


def hit(**more):
    return dict({'first': 4, 'last': 6, 'id': 0, 'part': 0, 'bone': 'top', 'damage': 3.0, 'angle': 361, 'kbg': 30,
                 'fkb': 0, 'bkb': 20, 'size': 2.0, 'x': 0.0, 'y': 4.0, 'z': 6.0, 'x2': None, 'y2': None, 'z2': None,
                 'effect': 'collision_attr_normal', 'targets': 'both', 'catch_only': False, 'ignore_throw': False,
                 'run': 1}, **more)


def game_of(hitboxes, script='game_attack11', **more):
    return {'moves': {script: dict({'hitboxes': hitboxes, 'other': [], 'flags': [], 'effects': [], 'sounds': []}, **more)}}


def test_hitboxes_go_on_own_joints_with_sizes_in_world_units():
    from echo_ultimate.gamedata.prc import hash40
    game = game_of([hit(), hit(id=1, bone='kneer', x=1.0, y=-2.0, z=3.0, size=4.0, damage=5.0),
                    hit(id=2, bone=f"0x{hash40('duckhead'):010x}", x=2.5, y=1.0, z=0.0),
                    hit(id=3, bone='sword1')])
    table = {'c00attack11': [{'target_motion': 'Attack11', 'id': 'c00attack11-attack11', 'time_keys': None, 'offset': 0}]}
    spec, notes = oneshot.combat_spec(game, table, 'Marth', route.rig_stub(FROZEN), 1.0, {'Attack11': 30},
                                      route.OwnPlacer(ORDER), {})
    assert route.scale_sizes(spec, 0.5) == 3
    boxes = {hb['bone']: hb for hb in spec['moves'][0]['phases'][0]['hitboxes']}
    assert sorted(boxes) == [0, 7, 8]                                  # the top joint, KneeR, DuckHead
    assert boxes[0]['position'] == [0.0, 4.0, 6.0] and boxes[0]['radius'] == pytest.approx(1.0)
    assert boxes[7]['position'] == [1.0, -2.0, 3.0] and boxes[7]['radius'] == pytest.approx(2.0)
    assert boxes[8]['position'] == [2.5, 1.0, 0.0] and boxes[7]['damage'] == 5
    assert any('sword1' in n and 'dropped' in n for n in notes)
    # and the script the profile compiles to names those joints, the size in 256ths of a world unit
    items = combat.compile_move(spec['moves'][0])
    made = {f['bone']: f for code, f, _ in items if code == combat.command('create_hitbox')[0]}
    assert made[7]['size'] == 512 and (made[7]['z_offset'], made[7]['y_offset'], made[7]['x_offset']) == (256, -512, 768)


def test_a_hitbox_drawn_out_along_a_line_is_balls_on_the_same_joint():
    game = game_of([hit(bone='kneer', x=0.0, y=0.0, z=0.0, x2=8.0, y2=0.0, z2=0.0, size=2.0)])
    table = {'c00attack11': [{'target_motion': 'Attack11', 'id': 'x', 'time_keys': None, 'offset': 0}]}
    spec, _ = oneshot.combat_spec(game, table, 'Marth', route.rig_stub(FROZEN), 1.0, {'Attack11': 30},
                                  route.OwnPlacer(ORDER), {})
    route.scale_sizes(spec, 0.9)
    boxes = spec['moves'][0]['phases'][0]['hitboxes']
    assert len(boxes) == 3 and {hb['bone'] for hb in boxes} == {7}     # the driver's own rule for how many
    assert [hb['position'][0] for hb in boxes] == pytest.approx([8 - 8 * (i + 0.25) / 3 for i in range(3)])
    assert all(hb['position'][1:] == [0.0, 0.0] for hb in boxes)       # places are in the joint, not scaled
    assert boxes[0]['radius'] == pytest.approx((2.0 + 8.0 / 3 / 4) * 0.9)


def test_a_throw_of_no_damage_is_written_so_and_its_hit_for_the_held_fighter_carries_the_damage():
    """Incineroar's back throw (cold trial, 2026-11-13): the throw is 0% at 47 and a box for the held fighter alone
    does 14%. Written 1%, the throw added a point and verify's 4.8 said NOT THE GAME'S."""
    abs_ = {'cmd': 'ATTACK_ABS', 'real': 1, 'args': [0, 0, 0.0, 47, 340, 0, 57, 0.0, 1.0]}
    game = game_of([hit(first=28, last=28, damage=14.0, angle=32, catch_only=True)], script='game_throwb',
                   other=[abs_, {'cmd': 'ATK_HIT_ABS', 'real': 30, 'args': [0, 'throw']}])
    table = {'c00throwb': [{'target_motion': 'ThrowB', 'id': 'x', 'time_keys': None, 'offset': 0}]}
    spec, _ = oneshot.combat_spec(game, table, 'Marth', route.rig_stub(FROZEN), 1.0, {'ThrowB': 50},
                                  route.OwnPlacer(ORDER), {})
    move = spec['moves'][0]
    assert move['throw']['damage'] == 0 and move['throw']['angle'] == 47 and move['throw']['release'] == 30
    held = [hb for p in move['phases'] for hb in p['hitboxes']]
    assert [hb['damage'] for hb in held] == [14] and held[0]['grabbed_only']
    assert combat.compile_move(move)                   # a throw of 0% is one the script takes


class _Source:
    """A stand-in for own_bank.Source: each clip is where its root is on each frame."""
    refused = {}

    def __init__(self, roots):
        self.roots = {k: np.asarray(v, float) for k, v in roots.items()}

    def clip(self, stem):
        return SimpleNamespace(stem=stem, end=len(self.roots[stem]) - 1)

    def root_place(self, raw, at):
        way = self.roots[raw.stem]
        return np.stack([np.interp(at, np.arange(len(way)), way[:, k]) for k in range(3)], axis=1)


def test_the_way_the_fighter_is_going_is_read_off_its_own_root():
    ahead = [[0.0, 0.0, float(f)] for f in range(11)]
    up = [[0.0, float(f), float(f)] for f in range(11)]
    still = [[0.0, 0.0, 0.0]] * 11
    jobs = {'a': {'motion': 'A', 'parts': [{'stem': 'ahead'}]}, 'u': {'motion': 'U', 'parts': [{'stem': 'up'}]},
            's': {'motion': 'S', 'parts': [{'stem': 'still'}]},
            'j': {'motion': 'J', 'parts': [{'stem': 'still', 'keys': [[0, 0.0], [3, 3.0]]}, {'stem': 'up'}]}}
    placer = route.OwnPlacer(ORDER, jobs, _Source({'ahead': ahead, 'up': up, 'still': still}))
    assert placer.heading('a', None, 4, 6) == 0 and placer.heading('u', None, 4, 6) == 45
    assert placer.heading('s', None, 4, 6) is None and placer.heading('nothing', None, 4, 6) is None
    assert placer.heading('j', None, 8, 10) == 45 and placer.heading('j', None, 1, 3) is None


def test_a_grab_from_the_drivers_rule_gets_world_sizes():
    grab, hitbox = oneshot.GRAB_ELEMENT, combat.command('create_hitbox')[0]
    items = [(2, {'frame': 5}, None), (hitbox, {'id': 0, 'bone': 0, 'element': grab, 'size': 1000, 'x_offset': 300}, None),
             (hitbox, {'id': 1, 'bone': 0, 'element': 3, 'size': 1000}, None), (0, {}, None)]
    out = route.scale_grab(items, 0.5)
    assert out[1][1]['size'] == 500 and out[1][1]['x_offset'] == 300 and out[2][1]['size'] == 1000
    assert out[0] == items[0] and out[3] == items[3]


def test_an_attack_the_game_gives_no_hitbox_gets_a_script_with_none():
    game = game_of([], 'game_attacks4', effects=[{'cmd': 'EFFECT', 'real': 3, 'name': 'sys_smash_flash', 'args': []}])
    table = {'c03attacks4s': [{'target_motion': 'AttackS4', 'id': 'a', 'time_keys': None, 'offset': 0, 'acts': 67}],
             'h04swing1': [{'target_motion': 'Swing1', 'id': 'b', 'time_keys': None, 'offset': 0}],
             'c00attack11': [{'target_motion': 'Attack11', 'id': 'c', 'time_keys': None, 'offset': 0}],
             'c02attackhi3': [{'target_motion': 'AttackHi3', 'id': 'd', 'time_keys': None, 'offset': 0}]}
    made = route.silent_attacks(game, table, {'AttackS4': 76, 'Swing1': 26, 'Attack11': 34}, written={'Attack11'})
    assert made == [{'id': 'attacks4', 'motions': ['AttackS4'], 'total': 67, 'phases': []}]
    # (an item's swing keeps the donor's script, a move already written is not written twice, an action with no
    #  clip of the fighter's is left alone)
    items = combat.compile_move(made[0])
    assert [code for code, _, _ in items] == [2, combat.command('allow_interrupt')[0]] and items[0][1] == {'frame': 67}


LINE = {'cmd': 'EFFECT_FOLLOW_FLIP', 'real': 8, 'name': 'duckhunt_attack_line',
        'args': ['duckhunt_attack_line', 'duckhunt_attack_line', 'top', 0, 6.4, -3, 0, 0, 0, 1.1, True, '<const 0xf604>']}
SMOKE_R = {'cmd': 'LANDING_EFFECT', 'real': 3, 'name': 'duckhunt_atk_smoke_r',
           'args': ['<const 0xe828>', None, 0, 'duckhunt_atk_smoke_r', 'top', 0, 0, 0, 0, 0, 0, 0.7, 0, 0]}
SMOKE_L = {'cmd': 'LANDING_EFFECT', 'real': 3, 'name': 'duckhunt_atk_smoke_l',
           'args': ['duckhunt_atk_smoke_l', 'top', 1, 0, 0, 0, 0, 0, 0.7, 0, 0, 0, 0, 0]}


def test_only_the_fighters_own_effect_calls_are_handed_over_and_each_is_read():
    move = {'effects': [LINE, {'cmd': 'FOOT_EFFECT', 'real': 9, 'name': 'sys_turn_smoke', 'args': []},
                        {'cmd': 'LAST_EFFECT_SET_COLOR', 'real': 8, 'name': None, 'args': []}]}
    calls = route.own_calls(move, 'duckhunt')
    assert [c['name'] for c in calls] == ['duckhunt_attack_line']
    read = route.OwnEffects.read
    assert read(LINE, 'duckhunt') == dict(name='duckhunt_attack_line', bone='top', offset=[0.0, 6.4, -3.0],
                                          turn=[0.0, 0.0, 0.0], size=1.1)
    assert read(SMOKE_R, 'duckhunt')['size'] == 0.7 and read(SMOKE_R, 'duckhunt')['bone'] == 'top'
    off = {'cmd': 'EFFECT_OFF_KIND', 'real': 1, 'name': 'duckhunt_attack100', 'args': ['duckhunt_attack100', False, False]}
    assert read(off, 'duckhunt') is None
    # a fighter with no effect file of its own writes nothing
    none = route.OwnEffects('no/such/folder', 'duckhunt', 1.0)
    assert none.commands('AttackDash', calls, route.joint_names(ORDER), lambda f: f, 50) == [] and none.plan is None


@real
def test_duck_hunts_own_effects_become_commands_on_his_joints(tmp_path):
    from fighter_port import own_effects
    effects = route.OwnEffects(ROOT, 'duckhunt', 0.9698)
    joints = route.joint_names(ORDER)
    feather = {'cmd': 'EFFECT_FOLLOW_arg11', 'real': 3, 'name': 'duckhunt_feather',
               'args': ['duckhunt_feather', 'kneer', 0, 0, 0, 0, 0, 0, 1, True, None]}
    got = effects.commands('AttackDash', [LINE, SMOKE_R, SMOKE_L, feather], joints, lambda f: f + 1, 50)
    frames = [f for f, _c in got]
    assert all(c[0] == own_effects.EFFECT_COMMAND and 6000 <= c[1]['gfx_id'] < 6000 + len(effects.plan.generators)
               for _f, c in got)
    assert min(frames) == 4 and 9 in frames                         # the game's frames 3 and 8, a frame on
    assert sorted(effects.written) == ['duckhunt_atk_smoke_r', 'duckhunt_attack_line', 'duckhunt_feather']   # no twin
    held = [c[1] for _f, c in got if c[1]['bone_id'] == joints['kneer']]
    assert held and all(h['destroy_on_state_change'] == 1 for h in held)           # the feathers ride their joint
    # the line follows its bone (EFFECT_FOLLOW_FLIP): held by joint 0, which carries its particles along, and
    # removed when the move ends; the game does not use the command's place for a held one, so its particles start
    # there (joint 0 is the fighter's own space)
    line = [c[1] for f, c in got if f == 9]
    assert line and all(b['bone_id'] == 0 and (b['x'], b['y'], b['z']) == (0, 0, 0) and b['destroy_on_state_change'] == 1
                        for b in line)
    assert all(effects.plan.behaviours[b['gfx_id'] - 6000] == own_effects.STEADY_BEHAVIOUR for b in line)
    first = own_effects.read_generator(effects.plan.generators[line[0]['gfx_id'] - 6000])['commands']
    assert [c[1][0] for c in first if c[0] & ~0x07 == own_effects.ADD_POSITION] ==         [dict(x=0.0, y=pytest.approx(6.4 * 0.9698, abs=1e-3), z=pytest.approx(-3 * 0.9698, abs=1e-3))], first
    assert [r['follow'] for r in effects.written['duckhunt_attack_line']] == [True]
    assert [r['follow'] for r in effects.written['duckhunt_atk_smoke_r']] == [False]
    # a smoke that does not follow stays where it was given off
    smoke = [c[1] for f, c in got if f >= 4 and c[1]['gfx_id'] - 6000 in
             {n for u in effects.written['duckhunt_atk_smoke_r'] for _d, n, _b in u['generators']}]
    assert smoke and all(effects.plan.behaviours[s['gfx_id'] - 6000] == own_effects.BURST_BEHAVIOUR for s in smoke)
    made = effects.write(tmp_path)
    assert made['uses']['duckhunt_attack_line'][0]['follow'] is True
    assert made['file'] == 'EfDuckhuntData.dat' and made['symbol'] == 'effDuckhuntDataTable'
    assert json.loads((tmp_path / 'effects.json').read_text('utf-8')) == dict(file=made['file'], symbol=made['symbol'])
    back = own_effects.read_effect_file((tmp_path / made['file']).read_bytes())
    assert back['symbol'] == made['symbol'] and len(back['generators']) == made['generators']


@real
def test_a_following_effect_keeps_its_place_only_on_an_unturned_joint_and_code_can_take_a_call():
    from fighter_port import own_effects
    turned = dict(FROZEN, rest=dict(FROZEN['rest'], Hip={'r': [1.57, 0.0, 0.0], 't': [0.0, 0.0, 0.0], 's': [1.0, 1.0, 1.0]}))
    effects = route.OwnEffects(ROOT, 'duckhunt', 0.9698, turned)
    joints = route.joint_names(ORDER)
    assert {joints['rot'], 0} <= effects.plain and joints['hip'] not in effects.plain and joints['kneer'] not in effects.plain

    def on(bone, cmd='EFFECT_FOLLOW'):
        return dict(LINE, cmd=cmd, args=['duckhunt_attack_line', bone, 0, 6.4, -3, 0, 0, 0, 1.1, True])

    def adds(got):
        numbers = {c[1]['gfx_id'] - 6000 for _f, c in got}
        return [c for n in numbers for c in own_effects.read_generator(effects.plan.generators[n])['commands']
                if c[0] & ~0x07 == own_effects.ADD_POSITION]

    assert adds(effects.commands('AttackDash', [on('rot')], joints, lambda f: f, 50))       # Rot: the fighter's own space
    assert not adds(effects.commands('AttackDash', [on('kneer')], joints, lambda f: f, 50))  # under a turned joint: not
    assert any('is not carried' in n for n in effects.notes)
    # ..._NO_STOP: what ends by itself is not removed when the move ends
    stays = effects.commands('AttackDash', [on('rot', 'EFFECT_FOLLOW_NO_STOP')], joints, lambda f: f, 50)
    assert stays and all(c[1]['destroy_on_state_change'] == int(not effects.plan.ends(c[1]['gfx_id'] - 6000))
                         for _f, c in stays)
    # a call the fighter's own code plays is left out of that action's script, and only that action's
    effects.by_code = {'AttackDash': ('duckhunt_attack_line',)}
    assert effects.commands('AttackDash', [on('rot')], joints, lambda f: f, 50) == []
    assert effects.commands('AttackS3', [on('rot')], joints, lambda f: f, 50)


# ---- the driver's own functions when the route is not asked for -------------------------------------------------------
def test_an_effect_goes_on_a_named_joint_only_when_a_port_brings_its_joints():
    donor = (10, {'bone_id': 75, 'use_common_bone_ids': 1, 'gfx_id': 1011, 'x': 0, 'y': 0, 'z': 1400,
                  'range_x': 9, 'range_y': 9, 'range_z': 9}, None)
    args = ['sys_smash_flash', 'kneer', -2.0, 10.0, 0.5]
    place = {'bone': 75, 'weapon': {'haver': np.eye(3)}, 'scale': 0.5}
    assert oneshot.placed(donor, args, place) is donor                 # the donor route: a bone with no rule
    feet = oneshot.placed(donor, ['sys_smash_flash', 'top', 3, 16, 4], place)[1]
    assert (feet['bone_id'], feet['z'], feet['y'], feet['x']) == (0, 0, 2048, 0)
    held = oneshot.placed(donor, ['sys_smash_flash', 'haver', 1, 2, 3], place)[1]
    assert (held['bone_id'], held['z'], held['y'], held['x']) == (75, 256, 512, 768)
    own = dict(place, bone=None, weapon={}, scale=1.0, joints=route.joint_names(ORDER))
    on = oneshot.placed(donor, args, own)[1]
    assert (on['bone_id'], on['use_common_bone_ids']) == (7, 0)
    assert (on['z'], on['y'], on['x']) == (-512, 2560, 128) and on['range_x'] == 0
    assert oneshot.placed(donor, ['sys_smash_flash', 'sword1', 0, 0, 0], own) is donor
    assert oneshot.placed(donor, ['sys_smash_flash', 'top', 3, 16, 4], own)[1]['y'] == 4096


def test_the_driver_takes_the_own_route_only_when_asked(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(route, 'run', lambda a: seen.append(a) or {'route': 'own skeleton'})
    asked = SimpleNamespace(own=str(tmp_path), work=str(tmp_path / 'w'), donor_zip=str(tmp_path / 'none.zip'))
    assert oneshot.run(asked) == {'route': 'own skeleton'} and seen == [asked]
    for plain in (SimpleNamespace(own=None, work=str(tmp_path / 'w'), donor_zip=str(tmp_path / 'none.zip'), fighter='x',
                                  donor='Marth'),
                  SimpleNamespace(work=str(tmp_path / 'w'), donor_zip=str(tmp_path / 'none.zip'), fighter='x',
                                  donor='Marth')):
        with pytest.raises(FileNotFoundError):                         # the donor route: it opens the donor's package
            oneshot.run(plain)
    assert len(seen) == 1
    got = []
    monkeypatch.setattr(oneshot, 'run', got.append)
    oneshot.main(['x', '--donor-zip', 'z', '--work', 'w', '--root', 'r'])
    oneshot.main(['x', '--donor-zip', 'z', '--work', 'w', '--root', 'r', '--own', 'folder'])
    assert got[0].own is None and got[1].own == 'folder'


# ---- Duck Hunt's own files -------------------------------------------------------------------------------------------
@pytest.fixture(scope='module')
def duckhunt(tmp_path_factory):
    """Duck Hunt's rig and rewritten fighter data, the game's scripts, and the driver's spec with and without the
    rows only an own skeleton needs."""
    from echo_ultimate.gamedata import moves as gd
    work = tmp_path_factory.mktemp('own_route')
    frozen = json.loads((DH / 'rig' / 'rig-duckhunt.json').read_text('utf-8'))
    game = json.loads(json.dumps(gd.load('duckhunt', ROOT), default=str))
    specs = {}
    for name, more in (('plain', None), ('own', route.MELEE_NAMES)):
        path, _ = oneshot.build_spec('duckhunt', 'Marth', ROOT, DH / 'data' / 'PlMs.dat', game, work / name, {}, {}, {},
                                     None, {}, more_rows=more)
        specs[name] = json.loads(path.read_text('utf-8'))['clips']
    return SimpleNamespace(frozen=frozen, game=game, specs=specs, pl=(DH / 'data' / 'PlMs.dat').read_bytes(), work=work)


@real
def test_the_rows_an_own_skeleton_adds_change_no_other_row(duckhunt):
    plain, own = duckhunt.specs['plain'], duckhunt.specs['own']
    added = [c for c in own if c not in plain]
    assert [c for c in own if c in plain] == plain                     # the donor route's spec, row for row
    assert sorted(c['target_motion'] for c in added) == ['DownFowardD', 'DownFowardU', 'DownSpotU', 'FuraSleepEnd',
                                                         'FuraSleepLoop', 'FuraSleepStart', 'HeavyWalk1', 'HeavyWalk2',
                                                         'ItemParasolFall', 'ItemParasolOpen', 'ItemScrewAir',
                                                         'ItemScrewDamage']
    by = {c['target_motion']: c for c in added}
    # the items' actions held a standing pose until 2026-11-13; Duck Hunt has only `downspotd`, so the face-up lie
    assert by['ItemScrewAir']['source'].endswith('h07itemscrew.nuanmb')
    assert by['ItemParasolOpen']['time_keys'] == [[0, 8.0], [8, 16.0]]
    assert by['DownSpotU']['source'].endswith('f03downwaitu.nuanmb') and by['DownSpotU']['time_keys'] == [[0, 0.0], [30, 30.0]]


def _frame(rot_rows, place):
    """A 4x4 row-vector matrix: three rows of axes, then the place."""
    m = np.eye(4)
    m[:3, :3], m[3, :3] = np.array(rot_rows, float), place
    return m


def test_the_sword_trail_goes_on_the_weapon_joint_whose_x_axis_lies_along_the_blade():
    # Melee runs a trail along its joint's x axis (ftafterimage.c: column 0 of the joint's matrix); the game's
    # commands give the blade's ends on `haver`, which holds the blade along its y (as Shulk's does). `swordr`, a
    # weapon bone under it, turns y into x: the trail goes on it, the ends carried into its axes.
    hand = _frame([[0, 0, -1], [0, 1, 0], [1, 0, 0]], [4.0, 10.0, 1.0])
    worlds = {'handr': hand, 'haver': _frame(np.eye(3), [0.5, 0, 0]) @ hand}
    worlds['swordr'] = _frame([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], [0, 0.5, 0]) @ worlds['haver']
    worlds['swordrb1'] = _frame(np.eye(3), [2.0, 0, 0.9]) @ worlds['swordr']       # the blade's own: opens and shuts
    parents = {'haver': 'handr', 'swordr': 'haver', 'swordrb1': 'swordr'}
    joints = {'handr': 9, 'haver': 10, 'swordr': 11, 'swordrb1': 12}
    on = lambda tex, a, b: {'cmd': 'AFTER_IMAGE4_ON_arg29', 'real': 5,
                            'args': [tex, tex + '2', 4, 'haver', *a, 'haver', *b, True, '0x0425cbfc4f', 'haver']}
    game = {'moves': {'game_attack11': {'effects': [on('tex_a', (0, 3, 0.9), (0, 19, 0.9))]},
                      'game_attacks3': {'effects': [on('tex_a', (0, 3, 0.9), (0, 19, 0.9))]},
                      'game_specials': {'effects': [on('tex_b', (0, 3, 0.6), (0, 15, 0.6))]}}}
    base = {'x0': 0.2, 'x4': 1.0, 'start_alpha': 255, 'end_alpha': 0, 'in_col': [0, 255, 255, 0],
            'out_col': [255, 255, 255, 0], 'x12': 0, 'x13': 0, 'bone': 75, 'bottom': 1.75, 'top': 9.63}
    colours = {'tex_a': [80, 170, 250, 0], 'tex_b': [255, 80, 140, 0]}
    trail, note = route.own_trail(game, worlds, parents, joints, base, colours.get)
    assert trail['bone'] == 11 and 'swordr' in note
    assert trail['bottom'] == pytest.approx(2.5) and trail['top'] == pytest.approx(18.5)
    assert trail['in_col'] == [80, 170, 250, 0] and trail['others'] == {'game_specials': [255, 80, 140, 0]}
    assert (trail['x0'], trail['out_col']) == (0.2, [255, 255, 255, 0])        # what the game does not say: the donor's
    assert '6% of its length off' in note                                      # (the blade sits 0.9 off the axis)
    # the bone itself, when its own x lies along the blade (and no weapon bone under it is needed)
    straight = {k: dict(m, effects=[dict(e, args=[*e['args'][:4], e['args'][5], 0, 0, 'haver', e['args'][9], 0, 0,
                                                  *e['args'][11:]]) for e in m['effects']]) for k, m in game['moves'].items()}
    trail2, _ = route.own_trail({'moves': straight}, worlds, parents, joints, base, colours.get)
    assert trail2['bone'] == 10 and (trail2['bottom'], trail2['top']) == pytest.approx((3, 19))
    # no weapon joint along the blade, or none in the rig: no trail, and the note says what was tried
    gone, why = route.own_trail(game, worlds, parents, {'haver': 10}, base, colours.get)
    assert gone is None and 'swordr: not a joint of the rig' in why and 'haver: x axis 90 degrees off' in why
    assert route.own_trail({'moves': {}}, worlds, parents, joints, base, colours.get)[0] is None
    assert route.own_trail(game, worlds, parents, joints, None, colours.get)[0] is None
    # the code file draws it on that joint
    from fighter_port import code
    c = code.source('Marth', trail)[0]['fighter.c']
    assert '.bone_index = 11, .offset_bottom = 2.500, .offset_top = 18.500' in c and '.in_col = {80, 170, 250, 0}' in c


def test_the_own_route_draws_a_trail_only_where_the_games_script_does():
    # the donor route also runs it under sword hitboxes when the game swings with an effect of its own; the own
    # route carries that effect itself, so it keeps to the game's trail commands
    cues = {'swings': {}, 'trail_on': (49, {'render_status': 0}, None), 'trail_off': (49, {'render_status': 255}, None),
            'trail_drawn_only': True}
    blank = [(0, {}, None)]
    lunge = {'hitboxes': [{'bone': 'haver', 'first': 9, 'last': 13, 'damage': 11}]}
    assert oneshot.dress(blank, lunge, 40, cues, 'AttackDash', 'test')[1] == []
    own = dict(lunge, effects=[{'cmd': 'AFTER_IMAGE4_ON_arg29', 'real': 5, 'args': ['tex']},
                               {'cmd': 'AFTER_IMAGE_OFF', 'real': 12, 'args': [4]}])
    assert oneshot.dress(blank, own, 40, cues, 'AttackHi3', 'test')[1] == ['trail 5-12']


@real
def test_a_fighter_with_its_own_face_up_spot_keeps_it_before_the_lying_stand_in():
    # rows are taken in the clips' sorted order: a game's `downspotu` must come before `downwaitu`, whose stand-in row
    # for DownSpotU is only for a fighter that has none (own_route.MELEE_NAMES)
    seen = 0
    for motion in sorted((Path(ROOT) / 'gamedata' / 'fighter').glob('*/motion/body/c00')):
        stems = sorted(p.stem for p in motion.glob('*downspotu.nuanmb')) + sorted(p.stem for p in motion.glob('*downwaitu.nuanmb'))
        if len(stems) == 2:
            seen += 1
            assert stems == sorted(stems), (motion, stems)
    assert seen


@real
def test_duck_hunts_rows_are_jobs_own_bank_takes(duckhunt):
    from vault.echo.subactions import FighterDat
    source = own_bank.Source(ROOT, 'duckhunt', duckhunt.frozen)
    ends = lambda stem: float(source.clip(stem).end)
    actions = FighterDat(duckhunt.pl).actions
    loops = {x.motion for x in actions if x.motion and (x.flags or 0) & own_bank.LOOPS}
    jobs, by_id, errors = route.jobs_from_spec(duckhunt.specs['own'], ends, loops)
    assert not errors and len(jobs) == len(duckhunt.specs['own']) > 170
    for job in jobs:                                                   # every key is a frame its clip has
        for part in job['parts']:
            own_bank.part_keys(part, source.clip(part['stem']).end)
    by_motion = {j['motion']: j for j in jobs}
    # the jab's second hit moves the fighter by its clip; walking goes by the fighter's speeds; a spot dodge's sway
    # is left to the bank's own rule
    assert by_motion['Attack12']['travel'] == 'XYZ' and by_motion['WalkSlow']['travel'] == ''
    assert 'travel' not in by_motion['EscapeN'] and by_motion['WalkSlow']['loop'] and not by_motion['Attack12']['loop']
    assert by_motion['SpecialNEnd']['parts'][0]['keys'][0] == [0, 2.0]             # one clip cut over three actions
    stored = lambda m: own_bank.timeline([own_bank.part_keys(p, source.clip(p['stem']).end)
                                          for p in by_motion[m]['parts']], 1)[3]
    assert stored('Attack11') == 34 and stored('Catch') == 34 and stored('EscapeN') == 26


@real
def test_duck_hunts_hitboxes_land_on_his_own_joints(duckhunt):
    from vault.echo.subactions import FighterDat
    order = duckhunt.frozen['order']
    clips = duckhunt.specs['own']
    source = own_bank.Source(ROOT, 'duckhunt', duckhunt.frozen)
    jobs, by_id, _ = route.jobs_from_spec(clips, lambda stem: float(source.clip(stem).end))
    installed = {j['motion']: own_bank.timeline([own_bank.part_keys(p, source.clip(p['stem']).end)
                                                 for p in j['parts']], 1)[3] for j in jobs}
    specials = {x.motion for x in FighterDat(duckhunt.pl).actions if x.motion and x.index >= 295}
    table = route.without(route.clip_table(clips), specials)
    spec, notes = oneshot.combat_spec(duckhunt.game, table, 'Marth', route.rig_stub(duckhunt.frozen), 1.0, installed,
                                      route.OwnPlacer(order, by_id, source), {})
    assert not [n for n in notes if 'no donor joint' in n]             # every bone his scripts name is a joint
    route.scale_sizes(spec, 0.5)
    by_motion = {m: p for p in spec['moves'] for m in p['motions']}
    assert not specials & set(by_motion)                               # nothing is written for a special
    tilt = by_motion['AttackS31']['phases'][0]
    assert {order[hb['bone']] for hb in tilt['hitboxes']} == {'DuckHead'} and tilt['start'] == 8
    assert {hb['damage'] for hb in tilt['hitboxes']} == {8}
    jab = by_motion['Attack11']['phases'][0]['hitboxes']
    assert {hb['bone'] for hb in jab} == {0} and jab[0]['position'] == [0.0, 4.0, 6.0]
    assert jab[0]['radius'] == pytest.approx(1.8 * 0.5)                # the game's 1.8, in world units
    silent = route.silent_attacks(duckhunt.game, table, installed, set(by_motion))
    # the smashes: the aiming reticle registers scripts under their names too, and the reader keeps the fighter's
    # own, so none is left without a hitbox; the game's code times their shots, and `shots` gives them their frames
    assert silent == [] and {'AttackS4', 'AttackHi4', 'AttackLw4'} <= set(by_motion)
    made = {'moves': {'game_attacks4': {'hitboxes': [{'first': 12, 'last': None}, {'first': 18, 'last': 20}]}}}
    assert route.shots(made, 'duckhunt') == {'game_attacks4': [(17, 18)]}
    assert made['moves']['game_attacks4']['hitboxes'][1] == {'first': 18, 'last': 20}      # one its script ends is left
    assert route.shots(made, 'cloud') == {}
    # the installed scripts read back with every joint one of the rig's
    pl, done, failed = oneshot.install_scripts(duckhunt.pl, {'schema': 1, 'moves': spec['moves'] + silent})
    assert not failed
    fd = FighterDat(pl)
    hitbox = combat.command('create_hitbox')[0]
    for motion in ('Attack11', 'AttackS31', 'AttackAirLw', 'AttackS4', 'ThrowLw', 'CliffAttackQuick'):
        act = next(x for x in fd.actions if x.motion == motion)
        boxes = [f for code, f, _ in fd.script_items(act.index) if code == hitbox]
        assert all(not f['use_common_bone_ids'] and f['bone'] < len(order) for f in boxes)
        assert boxes


@real
def test_no_special_keeps_anything_of_the_donors(duckhunt):
    from vault.echo.subactions import FighterDat
    before = FighterDat(duckhunt.pl)
    hitbox = combat.command('create_hitbox')[0]
    assert any(code == hitbox for x in before.actions if x.index >= 295 and x.script_offset is not None
               for code, _, _ in before.script_items(x.index))        # the donor's are there to begin with
    pl, emptied = route.quiet_specials(duckhunt.pl, 295)
    after = FighterDat(pl)
    assert len(emptied) == 32 and not after.verify_roundtrip()
    for x in after.actions:
        if x.index >= 295:
            assert x.script_offset is not None and after.script_items(x.index) == [(0, {}, None)]
        elif x.script_offset is not None:
            assert after.script_items(x.index) == before.script_items(x.index)


def bank_is_made():
    """Whether the clips the route's last run made can be used again. Making every clip from nothing takes minutes;
    the run below is seconds when the bank's cache holds them (it is keyed by own_bank.py itself)."""
    import hashlib
    path = DH / 'route' / 'bank' / 'report.json'
    if not path.exists() or not (DH / 'Marth.zip').exists():
        return False
    return json.loads(path.read_text('utf-8'))['settings']['code'] ==         hashlib.sha256(Path(own_bank.__file__).read_bytes()).hexdigest()[:16]


@real
def test_the_whole_route_runs_and_what_it_writes_reads_back(tmp_path, monkeypatch):
    """`python -m fighter_port.oneshot duckhunt --own <folder> ...` into a work folder of the test's own."""
    if not bank_is_made():
        pytest.skip("the route has not been run on this machine since own_bank.py last changed (its clips take minutes)")
    # (no MexTK: the route's own files, without his code; the checklist's env sets MEXTK_DIR, and then the 8 items
    # and the code file are built too)
    monkeypatch.delenv('MEXTK_DIR', raising=False)
    from vault.echo.subactions import FighterDat
    work = tmp_path / 'route'
    assert oneshot.main(['duckhunt', '--donor', 'Marth', '--root', ROOT, '--donor-zip', str(DH / 'Marth.zip'),
                         '--own', str(DH), '--work', str(work)]) == 0
    report = json.loads((work / 'report.json').read_text('utf-8'))
    final = work / 'final'
    assert sorted(p.name for p in final.iterdir()) == [
        'EfDuckhuntData.dat', 'GmRstMMs.dat', 'PlMs.dat', 'PlMsAJ.dat', 'PlMsDViWaitAj.dat', 'effects.json',
        'extra.json', 'ftDemoEndingMotionFileDuckh.dat', 'ftDemoIntroMotionFileDuckhu.dat', 'lookup.json',
        'replace.json']
    assert json.loads((final / 'lookup.json').read_text('utf-8')) == json.loads((DH / 'rig' / 'lookup.json').read_text('utf-8'))
    assert report['route'] == 'own skeleton' and report['items'] == 0 and report['code'] == []
    checked = report['check']
    assert checked['ok'] and checked['highest_joint'] < checked['joints'] == 102
    assert checked['largest_clip']['bytes'] <= 0x8000 and checked['own_clips'] == 209
    assert report['clips']['compiled'] == 184 and report['clips']['held'] == len(report['held']) == 25
    moves = {m['action']: m for m in report['moves']}
    tilt = moves['AttackS31']
    assert tilt['boxes'] == ['DuckHead(8)'] * 3 and tilt['first'] == tilt['game_first'] == 8 and tilt['acts'] == 32
    assert moves['Attack11']['first'] == 4 and moves['Attack11']['frames'] == 34
    # the smashes: three shots each, on the frames the game's code gives them (published: 17, 12 and 12 the first)
    assert [moves[m]['first'] for m in ('AttackS4', 'AttackHi4', 'AttackLw4')] == [17, 12, 12]
    assert all(moves[m]['boxes'] and moves[m]['acts'] == moves[m]['game_acts'] for m in ('AttackS4', 'AttackHi4', 'AttackLw4'))
    assert report['code_timed_hits']['game_attacks4'] == [[17, 18], [23, 24], [29, 30]]
    assert moves['ThrowF']['throw'] == moves['ThrowF']['game_throw'] == '8% at 45'
    assert moves['Catch']['first'] == moves['Catch']['game_first'] - oneshot.GRAB_LEAD
    # the files themselves: no special can hit, and the ears are on the game's swinging joints
    fd, hitbox = FighterDat((final / 'PlMs.dat').read_bytes()), combat.command('create_hitbox')[0]
    assert not [x.motion for x in fd.actions if x.index >= 295 and x.script_offset is not None
                and any(code == hitbox for code, _, _ in fd.script_items(x.index))]
    assert len(report['swing']['chains']) == 7 and not fd.verify_roundtrip()


def test_a_move_registered_only_as_a_shared_script_is_read_and_a_fighters_own_wins():
    """Shulk's Monado Arts have no `animcmd_game` script, only `animcmd_game_share`: they must still be moves, or
    their sound and effect scripts (the art's voice line and glow) are passed over with them."""
    from echo_ultimate.gamedata.moves import game_scripts
    reg = [{'agent': 'animcmd_game', 'name': 'game_attack11'},
           {'agent': 'animcmd_game_share', 'name': 'game_attack11'},
           {'agent': 'animcmd_game_share', 'name': 'game_specialnjump'},
           {'agent': 'animcmd_sound', 'name': 'sound_specialnjump'}]
    assert game_scripts(reg) == {0, 2}


def test_explicit_jab_window_is_mapped_for_runtime_without_a_false_close_opcode():
    game=game_of([hit()],jab_followup_windows=[dict(start=10,end=21,target='second')])
    table={'c00attack11':[dict(target_motion='Attack11',id='jab',time_keys=None,offset=0,
                              to_clip=lambda frame: frame*2)]}
    spec,_=oneshot.combat_spec(game,table,'Marth',route.rig_stub(FROZEN),1.,{'Attack11':60},
                              route.OwnPlacer(ORDER),{})
    profile=spec['moves'][0]
    assert profile['jab_followup_windows']==[[20,42]]
    clock=0;gates=[]
    for code,fields,_ in combat.compile_move(profile):
        if code==combat.command('asynchronous_timer')[0]:
            clock=fields['frame']
        elif code==combat.command('enable_jab_followup')[0]:
            gates.append((clock,fields['toggle']))
    assert gates==[]  # the runtime owns both ends; toggle=1 never closes the retail gate



def test_jab_listener_can_continue_past_general_iasa_and_preserves_neutral_stick():
    game=game_of([hit()],jab_followup_windows=[dict(start=10,end=33,target='second',neutral=True)])
    table={'c00attack11':[dict(target_motion='Attack11',id='jab',time_keys=None,offset=0,acts=20)]}
    spec,_=oneshot.combat_spec(game,table,'Marth',route.rig_stub(FROZEN),1.,{'Attack11':40},
                              route.OwnPlacer(ORDER),{})
    profile=spec['moves'][0]
    assert profile['total']==20 and profile['jab_followup_windows']==[[10,33]]
    assert profile['jab_followup_neutral']==[True]
    assert not any(c==combat.command('enable_jab_followup')[0] for c,_,_ in combat.compile_move(profile))
