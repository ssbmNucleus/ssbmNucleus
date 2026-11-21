"""Fishbunjin (Slap City's second fighter, 2026-11-13): what the own route and the Slap City reader learned from him
(moves by the input table, follow-on moves, throws that strike the held fighter, a move that leaves on both sides of
a choice, armour, a custom call's waves). Nothing here needs the game."""
from types import SimpleNamespace

from echo_slapcity import gamedata, transcode
from fighter_port import own_route


# ------------------------------------------------------------------------------------------------- the reader
def test_ordinary_moves_come_from_the_fighters_own_input_table():
    table = gamedata.move_table({'atkN': 'jab', 'strF': 'fstr', 'strD': 'dstr', 'spD': 'spd'})
    assert table['jab'] == ['c00attack11'] and table['fstr'] == ['c03attacks4s'] and table['dstr'] == ['c04attacklw4']
    assert table['spd'] == ['d03speciallw']
    # (Ittle Dew's names for those stems leave: a stem is played from one move)
    assert 'jab0' not in table and 'fsmash' not in table and 'dsmash' not in table


def test_a_smash_by_another_name_is_let_go_into_what_its_charge_check_goes_to():
    rate0 = {'t': 'SASF', 's': [{'w': 'Set', 'g': {'t': 'FSAN', 'a': 'fstr', 'r': 'rate'}, 's': {'f': 0.0}}]}
    move = {'tl': [{'af': 0, 'a': {'t': 'SAPA', 'a': 'fstr', 'cfg': {'rt': 1}}},
                   {'af': 6, 'a': rate0},
                   {'af': 6, 'a': {'t': 'SAAA', 'a': {'t': 'SACT', 'ct': {'t': 'CTB'}, 'a': {'t': 'SACTM', 'tm': 'fstr1'}}}}]}
    evs = gamedata.events(move)
    at = gamedata.charge_frame(evs, 'fstr')
    assert at == 6.0
    assert gamedata.charge_release(evs, {'fstr': move, 'fstr1': {'tl': []}}, 'fstr', at) == ('fstr1', 7)


def test_a_move_that_leaves_on_both_sides_of_a_choice_closes_its_boxes_there():
    # the down smash's slam: on its frame 20 to a second slam while attack is held, else to its recovery
    leave = {'t': 'SACT', 'ct': {'t': 'CTB'}, 'e': True, 'a': {'t': 'SACTM', 'tm': 'dstr2'}, 'ea': {'t': 'SACTM', 'tm': 'dstr1rec'}}
    moveset = {'dstr1': {'tl': [{'af': 20, 'a': leave}]}, 'dstr2': {'tl': []},
               'dstr1rec': {'tl': [{'af': 12, 'a': {'t': 'SACTM', 'tm': 'neutral'}}]}}
    row = {'first': 5, 'last': None}
    part = {'open': {0: row}}
    end = gamedata.leave_end(gamedata.events(moveset['dstr1']), moveset, 0, part)
    assert row['last'] == 20 and part['open'] == {} and end == 21 + 12


def _reader():
    return gamedata.Reader(SimpleNamespace(name='fishbunjin'), {'fthrow': {'dmg': 7.0, 'angle': 40.0}},
                           {'unit': 1.0, 'armature_scale': 1.0, 'shortcuts': {}}, 1.0)


def test_a_throw_that_strikes_the_fighter_held_is_read_as_the_throw():
    evs = [(0.0, 0, {'t': 'SAHSG', 's': 1}), (9.0, 0, {'t': 'SACH', 'h': 0, 'p': 'fthrow'}), (10.0, 0, {'t': 'SAEG'}),
           (11.0, 0, {'t': 'SACH', 'h': 1, 'p': 'fthrow'})]
    out = _reader().part(evs, 0, 'fthrow')
    assert out['hit_throws'] == [(10, 'fthrow')]            # the box after letting go is an ordinary one


def test_super_armour_is_a_stretch_from_its_partial_move_to_the_ordinary_one():
    evs = [(5.0, 0, {'t': 'SAPM', 'm': 'p_def_s_armor'}), (14.0, 0, {'t': 'SAPM', 'm': 'p_def_hrt'}),
           (3.0, 1, {'t': 'SAPM', 'm': 'p_def_s_armor'})]         # one inside a choice is not read
    out = _reader().part(sorted(evs, key=lambda e: e[0]), 0, 'fstr1')
    assert out['armour'] == [(6, True), (15, False)]


def test_a_specials_follow_on_moves_are_read_under_stems_of_their_own():
    play = lambda clip: {'af': 0, 'a': {'t': 'SAPA', 'a': clip}}
    moveset = {'spf': {'tl': [play('specialforward'), {'af': 20, 'a': {'t': 'SACTM', 'tm': 'spfrun'}}]},
               'spfrun': {'tl': [play('specialforwardground2'), {'af': 1, 'a': {'t': 'SAAA', 'a': {'t': 'SACTM', 'tm': 'spfatk'}}}]},
               'spfatk': {'tl': [play('specialforwardground3'), {'af': 42, 'a': {'t': 'SACTM', 'tm': 'neutral'}}]},
               'neutral': {'tl': []}}
    table = gamedata.move_table({'spF': 'spf'})
    got = gamedata.follow_ons(moveset, {'spF': 'spf'}, table)
    assert set(got) >= {'spfrun', 'spfatk'} and 'neutral' not in got
    assert all(len(v) == 1 for v in got.values()) and len({v[0] for v in got.values()}) == len(got)


def test_a_custom_calls_lists_and_nested_numbers_are_read():
    cc = {'m_Script': 1, 'localOffset': {'x': 0.0, 'y': 0.0, 'z': 2.0}, 'waves': [
        {'afterSeconds': 3.0, 'shockWave': {'attackFrames': 6}},
        {'afterSeconds': 0.0, 'note': 'x'}]}
    got = gamedata.deep_fields(None, None, cc)
    assert got['localOffset'] == [0.0, 0.0, 2.0] and 'm_Script' not in got
    assert got['waves'][0] == {'afterSeconds': 3.0, 'shockWave': {'attackFrames': 6}} and got['waves'][1]['note'] == 'x'


def test_the_armature_is_the_child_the_skin_hangs_from_not_one_named_armature():
    nodes = [{'name': 'top', 'parent': None, 's': [1.15, 1.15, 1.15]}, {'name': 'holder', 'parent': 0, 's': [1, 1, 1]},
             {'name': 'Armature.001', 'parent': 1, 's': [1, 1, 1]}, {'name': 'hip', 'parent': 2, 's': [1, 1, 1]},
             {'name': 'stars', 'parent': 1, 's': [1, 1, 1]}, {'name': 'Armature', 'parent': 4, 's': [1, 1, 1]}]
    assert transcode.armature_of(nodes, 1, [3]) == 2
    assert transcode.scale_above(nodes, 1) == 1.15


# --------------------------------------------------------------------------------------------- the own route
def test_the_armour_a_moves_script_gives_goes_on_every_action_that_plays_it():
    moves = {'game_attacks4s': {'armour': [[31, 41]]}, 'game_attackhi4': {'armour': [[15, 26]]}, 'game_attack11': {}}
    played = {62: 'c03attacks4s', 66: 'c04attackhi4', 44: 'c00attack11', 70: None}
    script_for = lambda stem, _m: {'c03attacks4s': 'game_attacks4s', 'c04attackhi4': 'game_attackhi4'}.get(stem, 'game_attack11')
    got = own_route.armour_spans(played, moves, script_for)
    assert got == [{'actions': [66], 'first': 15, 'last': 25}, {'actions': [62], 'first': 31, 'last': 40}]


# --------------------------------------------------------------------------------------------- his specials


def test_flex_armour_branch_excludes_both_grounded_states():
    # Reduced raw spn branch: CTM None asks that *none* of these conditions holds.
    # The old own module overrode the reader with an unconditional three-frame armour span.
    gate = {'t': 'CTM', 'm': 'None', 'c': [
        {'t': 'CTMV', 'm': 'kneebend', 'p': 7, 'e': []},
        {'t': 'CTMV', 'm': 'tumble', 'p': 7, 'e': []},
        *[{'t': 'CTC', 'w': 'Equal', 'a': {'t': 'FSM', 'a': 'grounded'}, 'b': {'f': n}}
          for n in (0, 1)]]}
    move = {'tl': [{'af': 0, 'a': {'t': 'SACT', 'ct': gate, 'e': False, 'a': {
        't': 'SAOS', 'ac': [{'t': 'SAPM', 'm': 'p_def_s_armor'},
                          {'t': 'SAT', 'f': {'f': 3}, 'a': {'t': 'SAPM', 'm': 'p_def_hrt'}}]}}}]}
    assert _reader().part(gamedata.events(move), 0, 'spn')['armour'] == []
