"""What finishing a fighter from a second game (Ike, from Brawl) added to the port rules: a counter by the
fighter's own number, a charge whose full release is a script of its own, armour on the frame a hit will find,
a dash that is held and braked, sounds and costumes read from another game's files.

The last tests read the real disc and run only when BRAWL_ROOT names a folder with it extracted."""
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fighter_port import code, combat, own, voice
from fighter_port.oneshot import SECOND, with_own


# ---------------------------------------------------------------------------------------- the code file
def test_armour_is_on_for_the_frame_a_hit_will_find():
    text, provides = code.source('Marth', None, None, [{'actions': [297, 301], 'first': 6, 'last': 10},
                                                        {'actions': [321], 'first': 18, 'last': 38}])
    c = text['fighter.c']
    assert 'armour on the frames the game gives it' in provides
    # the code runs before the frame's clip moves on: what it reads is one less than the frame a hit finds
    assert 'float at = fd->state.frame + 1.0f;' in c
    assert '(a == 297 || a == 301) && at >= 6.0f && at <= 10.0f' in c and '(a == 321) && at >= 18.0f && at <= 38.0f' in c


def test_a_counter_strikes_back_by_the_fighters_own_number():
    text, provides = code.source('Marth', None, None, None, None, None, None, None, None, None,
                                 {'actions': [324, 326], 'times': 1.2, 'least': 10, 'at': 0x5C, 'window': [11, 34]})
    c = text['fighter.c']
    assert "a counter that strikes back by the fighter's own multiple" in provides
    assert '#define COUNTER_LEAST 10' in c and '(a == 324 || a == 326)' in c
    # the donor keeps what it took times its own number; the hit's damage is put on it in the state's own step
    assert 'fd->cb.Phys = Counter_Phys;' in c and 'Fighter_UpdateHitboxDamage(&fd->hitbox[i], damage, gobj);' in c


IKE = {'first': 373,
       'action': {m: 304 + i for i, m in enumerate(
           ('SpecialS2Hi', 'SpecialS2Lw', 'SpecialS3Hi', 'SpecialS3S', 'SpecialS3Lw', 'SpecialAirS2Hi', 'SpecialAirS2Lw',
            'SpecialAirS3Hi', 'SpecialAirS3S', 'SpecialAirS3Lw', 'SpecialAirS4Hi', 'SpecialS4Hi', 'SpecialHi', 'SpecialAirHi'))},
       'total': {m: 20 for m in ('SpecialS2Hi', 'SpecialS2Lw', 'SpecialS3Hi', 'SpecialS3S', 'SpecialS3Lw', 'SpecialAirS2Hi',
                                 'SpecialAirS2Lw', 'SpecialAirS3Hi', 'SpecialAirS3S', 'SpecialAirS3Lw', 'SpecialAirS4Hi',
                                 'SpecialS4Hi', 'SpecialAirHi')} | {'SpecialHi': 64},
       'state': {'SpecialS1': 349, 'SpecialAirS1': 358, 'SpecialHi': 367, 'SpecialAirHi': 368},
       'world': 0.5, 'flags': {'ground': 0x340213, 'air': 0x340613}, 'move': {'up': 0x14, 'down': 0x15, 'side': 0x13},
       'own_params': {'paramIkeSpecialS__9ftIkeNode': [70, 70, 4.2, 3.6, 0.06, 0.04, 0.1, 0.065, 12, 0.5, 0.3, 0.1,
                                                         0.25, 0.5, 1.0, 9.0, -3.0, 9.0]},
       'moves': {'game_specialsattack': {'hitboxes': [{'damage': 9.0}], 'momentum': [[1, 1.0, 0.0]]},
                 'game_specialhi3': {'momentum': [[1, 0.0, -6.0]]}},
       'charge': {'recoil': 10.0, 'full': [344, 348]}}


def test_ikes_own_states_a_held_dash_and_a_plunge():
    made, why = own.build('ike', IKE)
    assert why is None and len(made['rows']) == 12 and made['entries'] == [373, 378]
    c = '\n'.join(made['source'])
    # the dash: speed by the frames it was held, in the fighter's own units
    assert '#define QD_MAX 70' in c and '#define QD_SPEED 2.1f' in c and '#define QD_GAIN 0.03f' in c
    assert '#define QD_DAMAGE 9.0f' in c and '#define QD_DAMAGE_GAIN 0.1f' in c
    # its end keeps half the dash's speed and is braked: on the ground through the game's friction step
    assert '#define QD_END 0.5f' in c and '#define QD_BRAKE 0.15f' in c and '#define QD_BRAKE_AIR 0.05f' in c
    assert 'Qd_Brake(&fd->phys.self_vel_ground.X, QD_BRAKE - fd->attr.ground_friction);' in c
    assert 'Fighter_PhysGround_ApplyFriction(gobj);' in c
    # held for as long as the button is; he swings at the first fighter he reaches
    assert 'if (!(fd->input.held & B_BUTTON))' in c and 'Enter(gobj, Qd(fd, 3));' in c
    # the up special: the plunge at the script's own speed, a ledge on the way down, the slam on landing
    assert '#define PLUNGE_SPEED 3.0f' in c and '#define UP_LAST 63.0f' in c and 'Plunge_Landed' in c
    assert 'Fighter_CollAir_GrabFacingLedgeWalljump(gobj, LEDGE_CHECK, Plunge_Landed);' in c
    # a full charge of the neutral special costs him damage of his own
    assert '(s == 344 || s == 348) && s != was' in c and '#define RECOIL 10.0f' in c
    assert [r['name'] for r in made['rows']][-2:] == ["Aether's plunge", "Aether's slam"]
    # without the clips of the states there is nothing to build
    assert own.build('ike', dict(IKE, total={}))[0] is None


def test_a_clip_two_actions_need_goes_on_both():
    rows = with_own({'specialsstart': 'SpecialS1', 'specialhi': 'SpecialHi'}, {'specialsstart': 'SpecialS2Hi', 'specialhi3': 'SpecialAirS4Hi'})
    # the donor's state shows the clip for the frame before the port's own state takes over: both carry it
    assert rows == {'specialsstart': ['SpecialS1', 'SpecialS2Hi'], 'specialhi': 'SpecialHi', 'specialhi3': 'SpecialAirS4Hi'}


def test_a_second_script_goes_on_the_donors_second_action():
    acts = [SimpleNamespace(index=i, motion=m) for i, m in ((297, 'SpecialNEnd'), (298, 'SpecialNEnd'), (301, 'SpecialAirNEnd'),
                                                            (302, 'SpecialAirNEnd'), (310, 'Swing4'))]
    assert [a.index for a in combat.nth_actions(acts, 0)] == [297, 301, 310]
    assert [a.index for a in combat.nth_actions(acts, 1)] == [298, 302]
    assert SECOND == '__2'


# ---------------------------------------------------------------------------------------- sounds
def test_a_brawl_sound_goes_by_the_words_the_sound_tables_use():
    from echo_brawl import gamedata
    word = lambda n: gamedata.sound_word(n, 'ike')
    assert word('snd_se_Ike_swing_l') == 'se_ike_swing_l' and word('snd_vc_Ike_Attack05') == 'vc_ike_attack05'
    assert word('snd_vc_Ike_Damage_hoshikie') == 'vc_ike_knockout'       # the game's own word for a star knock-out
    assert word('snd_vc_ouen_Ike') == 'vc_ike_cheer' and word('snd_se_narration_characall_Ike') == 'vc_narration_characall_ike'
    assert word('snd_se_common_punch_kick_swing_m') == 'se_common_punch_kick_swing_m'


def test_room_in_the_bank_goes_to_what_the_fighters_moves_play(monkeypatch):
    sound = lambda: {'pcm': np.ones(2205, np.int16), 'rate': 22050}
    se = {n: (n, sound()) for n in ('se_ike_swing_l', 'se_ike_swing_ll', 'se_ike_001', 'se_ike_013', 'se_ike_dash_start')}
    vc = {n: (n, sound()) for n in ('vc_ike_attack01', 'vc_ike_005', 'vc_ike_010')}
    monkeypatch.setattr(voice, '_banks', lambda root, fighter, game='ultimate': {'se': se, 'vc': vc, 'cheer': {}})
    moves = {'game_attacks4s': {'hitboxes': [1], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_ike_swing_ll'}, {'cmd': 'PLAY_SE', 'name': 'se_ike_001'}]},
             'game_attackairf': {'hitboxes': [1], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_ike_swing_ll'}]},
             'game_speciallwhit': {'hitboxes': [1], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'vc_ike_005'}]},
             'game_specialnend': {'hitboxes': [1], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'vc_ike_010'}, {'cmd': 'PLAY_SE', 'name': 'se_ike_013'}]},
             # a dodge is not a script the port writes: what it plays earns no place
             'game_escapen': {'hitboxes': [], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_ike_dash_start'}]}}
    samples = ['se_mars_sw_demo1', 'se_mars_sw_demo2', 'se_mars_sw_demo3', 'v_mars_atk1', 'v_mars_count1', 'v_mars_count2',
               'v_mars_shiedbreak', 'se_mars_sbreak', 'v_mars_jump']
    chosen, left = voice.choose('Marth', 'ike', None, samples, moves, 'brawl')
    got = {k: v[0] for k, v in chosen.items()}
    assert got['se_mars_sw_demo1'] == 'se_ike_swing_l' and got['v_mars_atk1'] == 'vc_ike_attack01'
    # a game that numbers its lines: a special's voice is the one its script plays, in one place of the row
    assert got['v_mars_count1'] == 'vc_ike_005' and got['v_mars_shiedbreak'] == 'vc_ike_010' and got['se_mars_sbreak'] == 'se_ike_013'
    # the places whose rows found nothing: the most played first (the dodge's sound is not among them)
    assert got['se_mars_sw_demo2'] == 'se_ike_swing_ll' and got['se_mars_sw_demo3'] == 'se_ike_001'
    # (a voice place of the donor's with nothing for it is made silent, never left as the donor's line)
    assert got['v_mars_count2'] == voice.SILENCE and 'se_ike_dash_start' not in got.values()
    assert any(line.startswith('v_mars_jump: the fighter has no vc_ike_jump01') for line in left)
    assert voice.seconds(se['se_ike_001'][1]) == pytest.approx(0.1)


# ---------------------------------------------------------------------------------------- textures
def test_a_texture_header_says_where_its_pixels_are():
    from echo_brawl import textures
    head = bytearray(0x40)
    head[:4] = b'TEX0'
    struct.pack_into('>iiIHHI', head, 0x10, 0x40, 0, 1, 64, 32, 9)
    assert textures._texture(bytes(head), 0) == (64, 32, 9, 0x40, True)
    pal = bytearray(0x40) + struct.pack('>4H', 0x8000, 0xFFFF, 0x801F, 0xFC00)
    pal[:4] = b'PLT0'
    struct.pack_into('>iiIH', pal, 0x10, 0x40, 0, 2, 4)
    table = textures._palette(bytes(pal), 0)
    assert (table.format, table.count, len(table.data)) == (2, 4, 8)


# ---------------------------------------------------------------------------------------- the real disc
ROOT = os.environ.get('BRAWL_ROOT', '')
needs_disc = pytest.mark.skipif(not (ROOT and any(Path(ROOT).rglob('FitIke.pac'))), reason='needs BRAWL_ROOT (a disc with Ike on it)')


@needs_disc
def test_ikes_full_charge_is_a_script_of_its_own_and_his_sounds_have_names():
    from echo_brawl import gamedata
    game = gamedata.load('ike', ROOT)
    plain, full = game['moves']['game_specialnend'], game['moves']['game_specialnend' + SECOND]
    assert game['same_name_scripts']['game_specialnend'] == 'game_specialnend' + SECOND
    assert max(h['damage'] for h in plain['hitboxes']) == 9 and plain['armour'] == [[6, 11]]
    assert max(h['damage'] for h in full['hitboxes']) == 37 and full['armour'] == []
    assert game['moves']['game_speciallw']['counter'] == [11, 34]
    played = {(e['real'], e['name']) for e in game['moves']['game_attacks4s']['sounds']}
    assert (2, 'vc_ike_attack05') in played and (7, 'se_ike_swing_ll') in played
    # a tilt's grunt is one the game picks itself: named as the attack voice with no number
    assert any(e['name'] == 'vc_ike_attack' for e in game['moves']['game_attackairf']['sounds'])


@needs_disc
def test_ikes_samples_and_costumes_are_on_the_disc():
    from echo_brawl import gamedata, textures
    bank = gamedata.sound_bank(ROOT, 'ike')
    assert 'se_ike_swing_ll' in bank['se'] and 'vc_ike_attack01' in bank['vc'] and len(bank['cheer']) == 1 and len(bank['call']) == 1
    assert 'se_ike_011' not in bank['se']                # a place the archive leaves all but empty
    assert voice.announcer(ROOT, 'ike', 'brawl') is not None
    files = textures.costume_files(ROOT, 'ike')
    assert sorted(files) == [0, 1, 2, 3, 4, 5]
    pictures = textures.costumes(ROOT, 'ike')
    assert pictures[0]['Fit_Ike01'].size == (512, 512) and pictures[0]['Fit_Ike01'].tobytes() != pictures[5]['Fit_Ike01'].tobytes()
    assert pictures[0]['FitIkeEyeIris'].tobytes() == pictures[5]['FitIkeEyeIris'].tobytes()


@needs_disc
def test_a_specials_table_lines_up_with_the_fighter_in_both_games():
    """Brawl's Marth against Melee's Marth names the columns: the damage a release starts from, the counter's
    multiple and its least, and the ball a hit must touch (the tables the driver's rules index)."""
    from echo_brawl import gamedata
    from fighter_port.oneshot import CHARGE_GAME, COUNTER_GAME
    if not any(Path(ROOT).rglob('FitMarth.pac')):
        pytest.skip('Marth is not extracted from the disc')
    marth = gamedata.read_moveset(ROOT, 'marth')
    value = lambda table: [round(f, 4) if abs(f) < 1e6 and (abs(f) > 1e-6 or i == 0) else i for _o, f, i in marth.params(table)]
    # Melee's Marth: 4 loops, 7 damage, 5 a loop, 1.25, 0.02; then 2.0, 0.0025, 0.04, 1.2 and the multiple
    assert value('paramMarthSpecialN__11ftMarthNode')[1:5] == [8, 5, 0.8, 0.02]
    assert value('paramMarthSpecialLw__11ftMarthNode')[:5] == [0.5, 0.0025, 0.04, 1.2, 1.1]
    assert value('paramMarthSpecialLw__11ftMarthNode')[7] == 8.0 and len(value('paramMarthSpecialLwShield__11ftMarthNode')) == 6
    ike = gamedata.read_moveset(ROOT, 'ike')
    number = lambda table, i: ike.params(table)[i]
    charge, counter = CHARGE_GAME['ike'], COUNTER_GAME['ike']
    assert number(charge['table'], charge['base'])[2] == 10 and number(charge['table'], charge['recoil'])[1] == 10.0
    assert number(counter['table'], counter['times'])[1] == pytest.approx(1.2) and number(counter['table'], counter['least'])[1] == 10.0
    assert [round(v[1], 1) for v in ike.params(counter['bubble'])[:5]] == [0.0, 0.0, 8.7, 0.0, 10.0]
