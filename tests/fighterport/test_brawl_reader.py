"""The Brawl reader's pure parts, and what the driver does differently for a fighter from Brawl."""
import math

import pytest

from echo_brawl import arc, brres
from echo_brawl.moveset import hitbox, timeline
from echo_brawl.transcode import quaternion, ultimate_name


def test_a_script_counts_frames_as_players_do():
    events = [{'event': 'wait', 'args': [2.0]}, {'event': 'hitbox', 'args': []}, {'event': 'wait', 'args': [2.0]},
              {'event': 'clear_hitboxes', 'args': []}, {'event': 'wait_until', 'args': [16.0]}, {'event': 'allow_interrupt', 'args': []}]
    # a move's first frame is 1: a hitbox after a wait of 2 is out on frame 3 (Ike's jab, published as frame 3)
    assert [(f, e['event']) for f, e in timeline(events)] == [(3.0, 'hitbox'), (5.0, 'clear_hitboxes'), (17.0, 'allow_interrupt')]


def test_a_hitbox_event_is_read_by_its_packed_words():
    h = hitbox([70 << 16 | 1, 22, 361, 100, 3 << 16 | 50, 6.0, 0.0, 6.0, -3.0, 0.0, 1.0, 1.0, 0x3a831c82])
    assert (h['bone'], h['id'], h['damage'], h['angle'], h['kbg'], h['bkb'], h['shield_damage']) == (70, 1, 22, 361, 100, 50, 3)
    assert h['effect'] == 'slash' and h['size'] == 6.0 and (h['y'], h['z']) == (6.0, -3.0)


def test_bones_take_the_names_the_driver_knows_them_by():
    assert [ultimate_name(n) for n in ('HipN', 'LShoulderN', 'LShoulderJ', 'RHaveN', 'SwordN', 'TransN', 'CMant01N')] == [
        'Hip', 'ClavicleL', 'ShoulderL', 'HaveR', 'Sword1', 'Trans', 'CMant01N']


def test_a_rotation_in_degrees_about_x_then_y_then_z():
    q = quaternion((90.0, 0.0, 0.0))
    assert q == pytest.approx([math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4)])
    rows = brres.matrix((1.0, 1.0, 1.0), (0.0, 0.0, 90.0), (1.0, 2.0, 3.0))
    # a quarter turn about z takes the bone's x to the parent's y; the last column is where the bone is
    assert [round(rows[r][0], 6) for r in range(3)] == [0.0, 1.0, 0.0] and [rows[r][3] for r in range(3)] == [1.0, 2.0, 3.0]


def test_a_curve_between_two_keys_follows_their_slopes():
    assert brres._hermite(0.0, 0.0, 0.0, 10.0, 10.0, 0.0, 5.0) == pytest.approx(5.0)      # flat at both ends: an ease through the middle
    assert brres._hermite(0.0, 0.0, 1.0, 10.0, 10.0, 1.0, 2.0) == pytest.approx(2.0)      # slope 1 at both ends: a straight line


def test_compressed_archives_unpack():
    raw = b'ARC\x00' + bytes(60)
    packed = b'\x10' + len(raw).to_bytes(3, 'little')
    for i in range(0, len(raw), 8):
        packed += b'\x00' + raw[i:i + 8]                 # eight literal bytes a block
    assert arc.lz77(packed) == raw and arc.read(packed) == ('', [])


def test_a_dodge_with_no_dodge_table_is_read_from_its_own_script():
    from fighter_port.oneshot import shared_untouchable
    game = {'motion_params': {}, 'motions': {'b02escapen': {'cancel_frame': 26, 'intangible': [2, 21]}}}
    assert shared_untouchable(game, 'b02escapen', 'EscapeN') == [2, 21]


def test_a_brawl_fighters_specials_go_on_the_donors_by_their_shape():
    from fighter_port.oneshot import special_rows
    names = {'specialnstart', 'specialnloop', 'specialnend', 'specialairnstart', 'specialairnloop', 'specialairnend',
             'specialsstart', 'specialshold', 'specialsdash', 'specialsattack', 'specialsend',
             'specialsairstart', 'specialsairdash', 'specialsairattack', 'specialhi', 'specialairhi', 'speciallw', 'specialairlw'}
    rows, chosen = special_rows('Marth', 'ike', names, {})
    # a start, a charge that loops and a release are the donor's own three, each on its own
    assert (rows['specialnstart'], rows['specialnloop'], rows['specialnend']) == ('SpecialNStart', 'SpecialNLoop', 'SpecialNEnd')
    assert chosen['neutral'] == 'same' and chosen['airneutral'] == 'same'
    # a start, a dash and a swing: one after another on the first step
    assert rows['specialsstart'] == {'motion': 'SpecialS1', 'then': ['specialsdash', 'specialsattack']}
    assert rows['specialsairstart'] == {'motion': 'SpecialAirS1', 'then': ['specialsairdash', 'specialsairattack']}
    assert rows['specialhi'] == 'SpecialHi' and rows['speciallw'] == 'SpecialLw'
