"""The rules a second fighter (Cloud, after Byleth) turned out to need: specials chosen by the
shape of the fighter's own clips, scripts matched to the clip they play, the weapon a move
holds named by that weapon's own clips, and what is fetched from the game's archive."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from echo_ultimate.gamedata import arc
from fighter_port import weapons
from fighter_port.oneshot import THROUGH, chain_window, script_for, special_rows

CLOUD = {'specialn', 'specialairn', 'specials1', 'specials2', 'specials3', 'specialairs1', 'specialairs2',
         'specialairs3', 'specialhi1', 'specialhi2', 'specialairhi1', 'speciallw', 'speciallwstart', 'specialairlw'}
CLOUD_MOVES = {'game_specialhi': {'animation': 'd02specialhi1.nuanmb'}, 'game_specialairhi': {'animation': 'd02specialairhi1.nuanmb'},
               'game_specialn': {'animation': 'd00specialn.nuanmb'}, 'game_speciallw': {'animation': 'd03speciallw.nuanmb'}}
BYLETH = {'specialnstart', 'specialn', 'specialairnstart', 'specialairn', 'specialsstart', 'specialsf',
          'specialairsstart', 'specialairsf', 'specialhi', 'specialairhi', 'speciallw', 'specialairlw'}


def test_one_clip_neutral_and_a_numbered_side_chain():
    rows, chosen = special_rows('Marth', 'cloud', CLOUD, CLOUD_MOVES)
    # the donor's start and charge are passed through, the whole clip plays on its release
    assert rows['specialn'] == [('SpecialNStart', (0, 1)), ('SpecialNLoop', (1, 2)), {'motion': 'SpecialNEnd', 'from': THROUGH}]
    assert chosen['neutral'] == chosen['airneutral'] == 'through'
    # hits 1, 2, 3 on every direction of the donor's chain; the donor's fourth step stays its own
    assert rows['specials1'] == ['SpecialS1'] and rows['specials2'] == ['SpecialS2Hi', 'SpecialS2Lw']
    assert rows['specialairs3'] == ['SpecialAirS3Hi', 'SpecialAirS3S', 'SpecialAirS3Lw']
    assert not any('S4' in t for targets in rows.values() if isinstance(targets, list) for t in targets if isinstance(t, str))
    # up and down: the clip the game's own script for that input plays
    assert rows['specialhi1'] == 'SpecialHi' and rows['specialairhi1'] == 'SpecialAirHi' and rows['speciallw'] == 'SpecialLw'
    assert 'specialhi2' not in rows and 'speciallwstart' not in rows


def test_a_start_clip_and_a_release_keep_the_charge_form():
    rows, chosen = special_rows('Marth', 'master', BYLETH, {})
    assert rows['specialnstart'] == [('SpecialNStart', (0, 44)), ('SpecialNLoop', (45, 75))] and rows['specialn'] == 'SpecialNEnd'
    assert rows['specialsstart'] == {'motion': 'SpecialS1', 'then': ['specialsf']}
    assert rows['specialhi'] == 'SpecialHi' and rows['specialairlw'] == 'SpecialAirLw'
    assert chosen == {'neutral': 'charge', 'side': 'joined', 'airneutral': 'charge', 'airside': 'joined'}
    assert special_rows('Fox', 'cloud', CLOUD, CLOUD_MOVES) == ({}, {})          # no rules for that donor yet


def test_the_next_swing_is_taken_between_the_games_own_flags():
    hit = lambda first: {'first': first, 'last': first + 1}
    s1 = {'hitboxes': [hit(10)], 'flags': [{'cmd': 'on_flag', 'real': 1}, {'cmd': 'on_flag', 'real': 10},
                                           {'cmd': 'on_flag', 'real': 16}, {'cmd': 'off_flag', 'real': 30}]}
    assert chain_window(s1, 40) == (16, 30)
    assert chain_window({'hitboxes': [hit(2)], 'flags': [{'cmd': 'on_flag', 'real': 14}]}, 31) == (14, 30)   # never lowered: to the end
    assert chain_window({'hitboxes': [hit(2)], 'flags': [{'cmd': 'on_flag', 'real': 1}]}, 55) is None       # no flag after the hit


def test_a_script_goes_with_the_clip_it_plays():
    moves = dict(CLOUD_MOVES, game_attacks3={'animation': 'c01attacks3s.nuanmb'}, game_attack11={})
    assert script_for('c00attack11', moves) == 'game_attack11'
    assert script_for('d02specialhi1', moves) == 'game_specialhi'               # not game_specialhi1
    assert script_for('c01attacks3s', moves) == 'game_attacks3'
    assert script_for('a00wait1', moves) == 'game_wait1'                        # nothing plays it: the plain name


def test_what_a_port_fetches_for_a_fighter():
    listed = ['fighter/cloud/model/body/c00/model.numshb', 'fighter/cloud/model/body/c01/model.numshb',
              'fighter/cloud/motion/body/c00/a00wait1.nuanmb', 'fighter/cloud/motion/body/c03/a00wait1.nuanmb',
              'fighter/cloud/motion/wave/c00/motion_list.bin', 'fighter/cloud/param/vl.prc',
              'fighter/cloud/ai/param/attack_data_param.prc', 'fighter/cloudy/param/vl.prc']
    assert arc.fighter_paths(listed, 'cloud') == [listed[0], listed[2], listed[4], listed[5]]


def box(low, high):
    return {'min': np.array(low, float), 'max': np.array(high, float)}


def test_a_weapons_own_clip_names_the_move_that_holds_it():
    """A spun bow's hitboxes sit off the bow, and other models are about (a final smash's sword): the
    bow's own clip, named after the move, says which model the move's article is."""
    hit = {'bone': 'haver', 'x': 0.0, 'y': 30.0, 'z': 0.0}
    game = {'moves': {'game_specialnstart': {'hitboxes': [], 'articles': ['<bow>'], 'animation': 'd00specialnstart.nuanmb'},
                      'game_attackairn': {'hitboxes': [hit], 'articles': ['<bow>'], 'animation': 'c05attackairn.nuanmb'},
                      'game_final': {'hitboxes': [], 'articles': ['<whip>'], 'animation': 'd04visualscene01.nuanmb'}}}
    models = {'bow': box([-1, -8, -1], [1, 8, 1]), 'sword2': box([-1, 0, -1], [1, 15, 1]), 'baton': box([-1, 0, -1], [1, 4, 1])}
    clips = {'bow': {'d00specialnstart', 'd00specialn'}, 'sword2': {'d04visualscene01'}, 'baton': set()}
    by_script, notes = weapons.assign(game, models, clips)
    assert by_script['game_specialnstart'] == by_script['game_attackairn'] == 'bow' and by_script['game_final'] == 'sword2'
    without, notes = weapons.assign(game, models)                                # three models left over: no telling
    assert 'game_attackairn' not in without
    # a fighter whose own weapon is on the hold bone: its hitboxes there are that weapon's, whatever else would fit
    swing = {'moves': {'game_attackhi3': {'hitboxes': [dict(hit, y=6.0)], 'articles': []}}}
    other = {'fusionsword': box([-1, 0, -1], [1, 18, 1])}
    assert weapons.assign(swing, other)[0] == {'game_attackhi3': 'fusionsword'}
    assert weapons.assign(swing, other, own_bone='HaveR')[0] == {}


def test_a_stand_in_blade_is_a_crescent_seen_from_both_sides():
    m = weapons.blade_model(10.0, 'blade0')
    part = m['parts'][0]
    assert np.allclose(m['max'][1] - m['min'][1], 10.0) and m['min'][0] == 0.0 and np.all(part['positions'][:, 2] == 0)
    assert 2.5 < m['max'][0] < 3.5                                               # it bulges the way it flies
    assert len(part['triangles']) == m['triangles'] and m['triangles'] % 2 == 0
    front, back = part['triangles'][:m['triangles'] // 2], part['triangles'][m['triangles'] // 2:]
    n = len(part['positions']) // 2
    assert np.array_equal(back, front[:, ::-1] + n)                              # the same faces, turned over
    assert weapons.blade_picture([97, 159, 212]).size == (16, 16)


def test_clouds_up_special_clip_says_when_it_leaves_the_ground():
    dump = os.environ.get('ULTIMATE_DUMP')
    clip = Path(dump or '.') / 'gamedata/fighter/cloud/motion/body/c00/d02specialhi1.nuanmb'
    if not dump or not clip.exists():
        pytest.skip('needs ULTIMATE_DUMP with Cloud fetched')
    sys.path.insert(0, str(Path(dump) / 'pydeps' / 'ssbh_data_py-0.9.1'))
    import ssbh_data_py
    from fighter_port.oneshot import leaves_ground
    assert leaves_ground(ssbh_data_py, clip, [[0, 0.0], [24, 24.0]], 24) == 11
    still = clip.with_name('d00specialn.nuanmb')                                 # a clip whose root never rises
    assert leaves_ground(ssbh_data_py, still, None, 60) is None


def test_where_a_clips_travel_goes():
    """A clip that moves the fighter: the donor action's own physics takes it where that reads the clip's
    root, the port's code file where the state only slows the fighter down, and walking is left to speeds."""
    from fighter_port.oneshot import travel_route
    flagged = {'SpecialS3S', 'SwingDash', 'Dash'}                 # the donor's own actions that move by their clip
    assert travel_route('AttackS4', 'normal', 'Marth', flagged) == 'state'      # a forward smash that steps in
    assert travel_route('Attack12', 'normal', 'Marth', flagged) == 'state'
    assert travel_route('ThrowB', 'grab', 'Marth', flagged) == 'state'
    assert travel_route('SpecialS3S', 'special', 'Marth', flagged) == 'state'   # the donor's own does: so does the port's
    assert travel_route('AttackLw3', 'normal', 'Marth', flagged) == 'code'      # a sliding kick on a tilt's state
    assert travel_route('AttackS31', 'normal', 'Marth', flagged) == 'code'
    assert travel_route('SpecialS1', 'special', 'Marth', flagged) == 'code'
    assert travel_route('AttackAirF', 'normal', 'Marth', flagged) is None       # nothing in the air reads it
    assert travel_route('Dash', 'locomotion', 'Marth', flagged) is None
    assert travel_route('AttackS4', 'normal', 'Fox', flagged) is None           # a donor with no root joint named yet


def test_the_code_file_moves_the_fighter_in_states_that_only_slow_it():
    from fighter_port import code
    text, provides = code.source('Marth', None, None, None, None, [57, 303])
    c = text['fighter.c']
    assert provides == ['moves that travel along the ground', 'sword trail data']
    assert 'a == 57 || a == 303' in c and 'fd->phys.air_state != 0' in c
    assert 'fd->transN_offset.Z * fd->facing_direction' in c and 'fd->phys.self_vel_ground.X = go;' in c
    assert c.count('void OnFrame(GOBJ *gobj)') == 1 and 'TravelFrame(fd);' in c
    assert 'TravelFrame' not in code.source('Marth')[0]['fighter.c']


def test_clouds_sliding_kick_and_forward_smash_travel_as_the_game_has_them():
    dump = os.environ.get('ULTIMATE_DUMP')
    folder = Path(dump or '.') / 'gamedata/fighter/cloud/motion/body/c00'
    if not dump or not (folder / 'c02attacklw3.nuanmb').exists():
        pytest.skip('needs ULTIMATE_DUMP with Cloud fetched')
    sys.path.insert(0, str(Path(dump) / 'pydeps' / 'ssbh_data_py-0.9.1'))
    import ssbh_data_py
    from fighter_port.oneshot import clip_travel
    slide = clip_travel(ssbh_data_py, folder / 'c02attacklw3.nuanmb', [[0, 0.0], [40, 40.0]])
    assert round(slide[0]) == 40 and round(slide[1]) == 40 and slide[2] < 0.5     # 40 units along the ground, and stays there
    step = clip_travel(ssbh_data_py, folder / 'c03attacks4s.nuanmb')
    assert round(step[0]) == 11
    assert clip_travel(ssbh_data_py, folder / 'a00wait1.nuanmb') in (None, (0.0, 0.0, 0.0, 0.0))


def test_code_that_puts_a_fighter_somewhere_by_hand_tells_the_collision():
    # a fighter put somewhere by writing his place (a counter's strike from behind the one who struck) is swept there
    # by the next collision from where he stood, and lands partway: Greninja's came out 8 short, on the near side.
    # The game's own moves that do it (Warp Star, Barrel) then call mpColl_80043680 (MexTK Coll_CopyPosToECBs),
    # which sets the collision's three places to his and its flag 0x20; a port writes those out.
    import re
    told_ = ('fd->coll_data.topN_Curr = fd->phys.pos;', 'fd->coll_data.topN_CurrCorrect = fd->phys.pos;',
             'fd->coll_data.topN_Prev = fd->phys.pos;', 'fd->coll_data.flags |= 0x20;')
    for path in sorted((Path(__file__).resolve().parents[2] / 'tools' / 'fighterport' / 'fighter_port').glob('own_*.py')):
        text = path.read_text('utf-8')
        for body in re.findall(r'\n(?:static )?void \w+\([^)]*\)\n\{\n(.*?)\n\}', text, re.S):
            writes = [m.end() for m in re.finditer(r'fd->phys\.pos(?:\.[XY])? = ', body)]
            if writes:
                told = [body.find(line, writes[-1]) for line in told_]
                assert min(told) > 0, f'{path.name}: a function writes his place and never tells the collision'
                assert body.find('Enter(', writes[-1]) < 0 or max(told) < body.find('Enter(', writes[-1]), path.name
