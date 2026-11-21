"""The round: every in-game check of a port as the tests of ONE boot."""
import importlib.util
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / 'tools' / 'fighterport' / 'fighter_port' / 'harness'


def _load(name):
    import sys
    sys.path.insert(0, str(HARNESS))
    spec = importlib.util.spec_from_file_location(name, HARNESS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


round_ = _load('round')
NAMES = list(round_.COMMON) + ['dh_can_step', 'dh_gun_five', 'face_blink', 'whip']


def test_the_probe_carries_the_common_tests_and_the_new_match_step():
    names = round_.known()
    assert set(round_.COMMON) <= set(names)
    assert "name.startswith('match_')" in (HARNESS / 'look_probe.py').read_text('utf-8')


def test_every_costume_is_photographed_in_the_one_boot_each_in_a_new_match():
    tests, mine, empty = round_.plan(NAMES, costumes=3)
    assert tests[:6] == ['look_portrait', 'match_1', 'look_portrait', 'match_2', 'look_portrait', 'match_0']
    assert not mine and not empty


def test_the_fighters_own_tests_are_chosen_by_pattern_and_each_gets_a_match_of_its_own():
    tests, mine, empty = round_.plan(NAMES, own=['dh_*', 'face_*', 'nothing_*'])
    assert mine == ['dh_can_step', 'dh_gun_five', 'face_blink'] and empty == ['nothing_*']
    for name in mine:
        assert tests[tests.index(name) - 1] == 'match_0'
    assert 'whip' not in tests                                   # another fighter's test is not this fighter's


def test_a_second_boot_starts_at_the_named_test_with_no_portraits_again():
    tests, _mine, _ = round_.plan(NAMES, costumes=2, own=['dh_*'], start='dh_gun_five')
    assert tests == ['match_0', 'dh_gun_five']


def test_the_round_allows_itself_what_the_probe_allows():
    tests, _, _ = round_.plan(NAMES, costumes=8, own=['dh_*'])
    extra, allowed = round_.deadline(tests)
    matches = sum(1 for t in tests if t.startswith('match_'))
    assert allowed == 100 + 9 * len(tests) + 20 * matches + extra and extra >= 60


def test_the_three_room_matches_come_last_each_with_its_picture():
    tests, _, _ = round_.plan(NAMES, own=['dh_*'], kind=0x1A)
    assert tests[-6:] == ['match_1_1a', 'look_round', 'match_1_1a_pokemonstadium', 'look_round',
                          'match_0_c_pokemonstadium', 'look_round']
    assert round_.plan(NAMES, own=['dh_*'])[0][-1] == 'dh_gun_five'           # no roster number: no room matches
    log = ('match_1_1a: a new match in the same boot (costume 1, second fighter 0x1a, finaldestination) in 6.0 s\n'
           'look_round: states (number, seconds in) [[14, 0.0]]\n'
           'match_1_1a_pokemonstadium: the bag never spawned\n')
    got = round_.read(log, tests[-6:])
    assert got['room'] == {'match_1_1a': 'loaded', 'match_1_1a_pokemonstadium': 'DID NOT LOAD'} and got['stopped']


def test_the_log_says_which_tests_ran_and_that_the_game_stopped():
    tests = ['look_perf', 'match_0', 'dh_can_step', 'match_0', 'dh_gun_five']
    log = ('look_perf: states (number, seconds in) [[14, 0.0]]\n'
           'match_0: a new match in the same boot (costume 0, second fighter 0x1, finaldestination) in 5.6 s\n'
           'dh_can_step: states (number, seconds in) [[14, 0.0]]\n'
           'match_0: a new match in the same boot (costume 0, second fighter 0x1, finaldestination) in 5.6 s\n'
           'PROBE DEADLINE PASSED after 300 s: ending its Dolphin\n')
    got = round_.read(log, tests)
    assert got['ran'] == ['look_perf', 'dh_can_step'] and got['not_run'] == ['dh_gun_five']
    assert got['stopped'] and got['matches'] == 2
    whole = round_.read(log.replace('PROBE DEADLINE PASSED after 300 s: ending its Dolphin', 'dh_gun_five: states (number, seconds in) []'), tests)
    assert not whole['stopped'] and not whole['not_run']


def test_a_stuck_step_is_not_a_stopped_game_and_its_test_is_asked_again():
    tests = ['step_jab', 'step_grab', 'snd_jump']
    log = ('step_jab: sound file at 1 bytes as it starts\n'
           '   A STEP DID NOT TAKE at step 1: fighter in state 14\n'
           '   THE STEPPING STUCK, NOT THE GAME, in step_jab: let go, the game runs on ({}); this test is void\n'
           'step_jab: states (number, seconds in) [[14, 0.0]]\n'
           'step_grab: states (number, seconds in) [[14, 0.0], [212, 0.2]]\n'
           'snd_jump: states (number, seconds in) [[14, 0.0], [24, 0.3]]\n')
    got = round_.read(log, tests)
    assert got['void'] == ['step_jab'] and got['not_run'] == ['step_jab'] and got['ran'] == ['step_grab', 'snd_jump']
    assert not got['stopped']


def test_nothing_is_believed_of_the_test_the_game_stopped_in():
    tests = ['step_jab', 'snd_jump']
    log = ('step_jab: sound file at 1 bytes as it starts\n'
           '   A STEP DID NOT TAKE at step 1: fighter in state 14\n'
           'THE GAME STOPPED in step_jab: it does not run when let go ({})\n')
    got = round_.read(log, tests)
    assert got['stopped'] and got['not_run'] == ['step_jab', 'snd_jump'] and not got['ran']
    assert got['dead'] == ['step_jab']
