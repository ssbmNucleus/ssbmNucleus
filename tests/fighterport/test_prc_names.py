"""The name finder: a parameter file's hashes named by trying words (GAPS G1, G8 of Greninja's trial)."""
from fighter_port import prc_names


def targets_of(*names):
    return prc_names.by_length({prc_names.hash40(n) for n in names})


def test_names_of_one_to_four_words_are_found_and_nothing_else():
    names = ('speed', 'life_max', 'hold_x_speed', 'attack_speed_min_up', 'shoot_hit_stop_frame')
    words = ['speed', 'life', 'max', 'hold', 'x', 'attack', 'min', 'up', 'shoot', 'hit', 'stop', 'frame', 'down', 'y']
    found = prc_names.search(words, targets_of(*names, 'not_a_name_here'), 4)
    assert sorted(found.values()) == sorted(names)
    assert all(prc_names.hash40(n) == h for h, n in found.items())


def test_a_name_longer_than_the_words_allowed_is_not_found():
    found = prc_names.search(['attack', 'speed', 'min', 'up'], targets_of('attack_speed_min_up'), 3)
    assert found == {}


def test_script_names_run_their_words_together_after_their_kind():
    found = prc_names.search(['max', 'shot', 'vanish'], targets_of('game_maxshot', 'game_maxvanish', 'game_shot'), 2,
                             joiner='', start=b'game_')
    assert sorted(found.values()) == ['game_maxshot', 'game_maxvanish', 'game_shot']


def test_the_words_the_modules_already_name_are_read_without_importing_them():
    known = prc_names.known_names()
    assert 'landing_frame' in known and 'charge_frame_max' in known      # Duck Hunt's or Wolf's, and Greninja's
