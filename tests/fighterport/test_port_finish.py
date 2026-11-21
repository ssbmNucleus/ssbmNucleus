"""What finishing two ports turned up: second versions of specials on actions of their own, a shot that
holds what it hits, a chain that waits for a hit, the fighter's own sounds in the donor's bank, trails in
the game's colour for each move, and Melee's own dust where the game makes dust."""
import importlib.util
import io
import json
import os
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest

from echo_ultimate import nus3audio
from fighter_port import code, items, own, states, voice
from fighter_port.oneshot import (EFFECT_MELEE, add_alternates, alternates, dress, frame_at, relative_rate, script_time,
                                  timed)
from vault.echo.subactions import Dat

_spec = importlib.util.spec_from_file_location('item_files', Path(__file__).with_name('test_port_items.py'))
item_files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(item_files)


# ------------------------------------------------------------------ second versions of specials
GAME = {'moves': {
    'game_specials1': {'animation': 'd01specials1.nuanmb', 'hitboxes': [{'first': 10, 'damage': 4.0}]},
    '0x110c71faca': {'animation': 'd01specials1.nuanmb', 'hitboxes': [{'first': 10, 'damage': 5.0}]},
    'game_specialn': {'animation': 'd00specialn.nuanmb', 'hitboxes': [], 'article_frames': [18]},
    '0x103b62a3d0': {'animation': 'd00specialn.nuanmb', 'hitboxes': [], 'article_frames': [16]},
    '0x16538c097f': {'animation': 'd02specialhilanding.nuanmb', 'hitboxes': [{'first': 1, 'damage': 3.5}]},
    '0x0ae26e8b23': {'animation': 'h07itemscrew.nuanmb', 'hitboxes': []},
    'game_attack11': {'animation': 'c00attack11.nuanmb', 'hitboxes': [{'first': 3, 'damage': 2.0}]},
    'game_specialsf': {'animation': 'd01specialsf.nuanmb', 'hitboxes': [{'first': 8, 'damage': 11.5}]},
    '0x121cce808b': {'animation': 'd01specialsf.nuanmb', 'hitboxes': [{'first': 8, 'damage': 11.5}]},
    '0xaaaaaaaaaa': {'animation': 'c00attack11.nuanmb', 'hitboxes': [{'first': 3, 'damage': 9.0}]}}}
TABLE = {'d01specials1': [{'target_motion': 'SpecialS1'}],
         'd00specialn': [{'target_motion': 'SpecialNStart', 'window': [0, 1]}, {'target_motion': 'SpecialNLoop', 'window': [1, 2]},
                         {'target_motion': 'SpecialNEnd', 'window': [2, None]}],
         'd02specialhilanding': [{'target_motion': 'SpecialS4Hi'}], 'c00attack11': [{'target_motion': 'Attack11'}],
         'd01specialsf': [{'target_motion': 'SpecialS1'}]}


def test_a_special_with_a_second_script_for_its_clip_has_a_second_version():
    found = alternates(GAME, TABLE)
    # the stretch of a cut clip that holds the shot; not the only script of a clip; not a move that is no special;
    # not the same hits under another name
    assert found == {'SpecialS1': '0x110c71faca', 'SpecialNEnd': '0x103b62a3d0'}


def test_a_second_versions_frames_are_found_on_the_clip_as_it_was_carried():
    assert script_time([[0, 0.0], [9, 9.0]], 13) == 13.0                 # a script's keys may stop early: it plays on
    assert script_time([[0, 0.0], [10, 10.0], [18, 14.0]], 16) == 13.0   # ... and a slowed stretch is slow
    assert script_time(None, 7) == 7.0
    assert frame_at([[0, 2.0], [19, 21.0], [51, 61.0]], 16.0) == 14      # the clip starts two frames in
    assert frame_at([[0, 0.0], [24, 24.0]], 10.5) == 11 and frame_at(None, 10.5) == 11
    assert relative_rate([[0, 0.0], [42, 56.0]], [[0, 0.0], [55, 55.0]]) == pytest.approx(56 / 42)
    assert relative_rate([[0, 0.0], [10, 10.0], [18, 14.0]], [[0, 0.0], [24, 24.0]]) == 1.0      # not one number: left alone
    assert timed([(2, {'frame': 7}, None), (11, {'id': 0}, None), (2, {'frame': 9}, None), (16, {}, None), (0, {}, None)]) == \
           [(7, (11, {'id': 0}, None)), (9, (16, {}, None))]


def test_a_second_version_gets_an_action_of_its_own_on_the_same_clip():
    zip_path = os.environ.get('PORT_DONOR_ZIP')
    if not zip_path or not Path(zip_path).exists() or not os.environ.get('NUCLEUS_REPO'):
        pytest.skip('needs PORT_DONOR_ZIP (a donor package exported from a project) and NUCLEUS_REPO')
    from vault.echo.subactions import FighterDat
    with zipfile.ZipFile(zip_path) as z:
        pl = z.read(json.loads(z.read('fighter.json'))['files']['fighterDataPath'])
    before = FighterDat(pl)
    plain = next(a for a in before.actions if a.motion == 'SpecialS1')
    script = [(2, {'frame': 9}, None), (19, {'flag': 2, 'value': 1}, None), (0, {}, None)]
    made, new = add_alternates(pl, [(plain.index, script), (plain.index + 1, [(0, {}, None)])])
    after = FighterDat(made)
    assert new == [len(before.actions), len(before.actions) + 1] and len(after.actions) % 4 == 0
    assert all(a.symbol is None and not a.anim_size for a in after.actions[new[-1] + 1:])              # filled out with empty ones
    second = after.actions[new[0]]
    assert (second.symbol, second.anim_offset, second.anim_size, second.flags) == \
           (plain.symbol, plain.anim_offset, plain.anim_size, plain.flags)
    assert [(c, f) for c, f, _ in after.script_items(new[0])][:2] == [(2, {'frame': 9}), (19, {'flag': 2, 'value': 1})]
    for a, b in zip(before.actions, after.actions):                      # every action the donor had is as it was
        assert (a.symbol, a.anim_offset, a.anim_size, a.flags) == (b.symbol, b.anim_offset, b.anim_size, b.flags)
        assert before.script_items(a.index) == after.script_items(b.index)


CTX = {'first': 373,
       'action': {m: 300 + i for i, m in enumerate(('SpecialAirS4Hi', 'SpecialS4Hi', 'SpecialS4S', 'SpecialS4Lw', 'SpecialAirS4S',
                                                    'SpecialAirS4Lw', 'SpecialHi', 'SpecialAirHi', 'SpecialS2Hi', 'SpecialS2Lw'))},
       'total': {'SpecialAirS4Hi': 101, 'SpecialS4Hi': 22, 'SpecialS4S': 5, 'SpecialS4Lw': 30, 'SpecialAirS4S': 21, 'SpecialAirS4Lw': 11,
                 'SpecialHi': 24, 'SpecialAirHi': 24, 'SpecialS2Hi': 4, 'SpecialS2Lw': 57},
       'state': {'SpecialHi': 367, 'SpecialAirHi': 368, 'SpecialLw': 369, 'SpecialAirLw': 371, 'SpecialS1': 349, 'SpecialAirS1': 358,
                 'SpecialNStart': 341, 'SpecialNLoop': 342, 'SpecialAirNStart': 345, 'SpecialAirNLoop': 346},
       'functions': {}, 'world': 0.93, 'rise': 11, 'glow': 57, 'tip': 127, 'commit': 46,
       'moves': {'game_specialhi2': {'hitboxes': [{'first': 12, 'last': None}]}},
       'flags': {'ground': 0x340213, 'air': 0x340613}, 'move': {'up': 0x14, 'down': 0x15}}
LIMIT = ('SpecialNEnd', 'SpecialAirNEnd', 'SpecialS1', 'SpecialS2Hi', 'SpecialS3Hi', 'SpecialAirS1', 'SpecialAirS2Hi',
         'SpecialAirS3Hi', 'SpecialHi', 'SpecialAirHi')


def donor_row(i):
    return {'action': 295 + i, 'flags': 0x340211 + i, 'move': 0x12, 'bits': 1, 'anim': 0x80136000 + i, 'iasa': 0x80136100 + i,
            'phys': 0x80136200 + i, 'coll': 0x80136300 + i, 'camera': 0x800761C8}


def test_clouds_limit_versions_are_states_on_the_second_actions():
    ctx = dict(CTX, alt={m: 327 + i for i, m in enumerate(LIMIT)}, row={m: donor_row(i) for i, m in enumerate(LIMIT)},
               alt_rate={m: (56 / 42 if m.endswith('S3Hi') else 1.0) for m in LIMIT},
               alt_next={'SpecialS1': 13, 'SpecialS2Hi': 7}, gate=3, rise_mul=1.6, rise_flag=0,
               n_states={'ends': [343, 344], 'air_ends': [347, 348], 'all': list(range(341, 349))})
    made, why = own.build('cloud', ctx)
    c = '\n'.join(made['source'])
    assert why is None and len(made['rows']) == 15 and made['rows'][5]['name'] == 'Limit Blade Beam'
    beam, slash, rise = made['rows'][5], made['rows'][7], made['rows'][13]
    assert (beam['action'], beam['anim'], beam['bits']) == (327, 0x80136000, 1)             # the donor's own state, on the second action
    assert (slash['action'], slash['anim'], slash['phys'], slash['coll']) == (329, 'LimitS1_Anim', 0x80136202, 'Charge_Coll')
    assert (rise['action'], rise['phys'], rise['coll']) == (335, 'LimitRise_Phys', 0x80136308)
    assert '#define ST_LIMIT_N 378' in c and '#define ST_LIMIT_RISE_AIR 387' in c and '#define LIMIT_RISE 1.600f' in c
    assert 'if (slash_hit[fd->ply] && fd->state.frame >= 13.0f)' in c and 'ST_LIMIT_S3 : ST_LIMIT_S3_AIR, 1.3333f' in c
    assert 'fd->ftcmd_var.flag0 = (fd->ftcmd_var.flag3 && slash_hit[p]) ? 1 : 0;' in c                   # the plain chain waits for a hit
    assert 'if (s == 343 || s == 344)' in c and 'LimitFrame(fd, gobj);' in c
    assert '|| fd->state_id == ST_LIMIT_RISE || fd->state_id == ST_LIMIT_RISE_AIR' in c                  # the dive follows a Limit rise too
    assert made['shot'] == {'variant': 'beam_limit[fd->ply]', 'states': {'ground': [378, 343, 344], 'air': [379, 347, 348]}}
    assert made['entries'] == [375, 380, 383, 386, 387]
    text = '\n'.join(states.table_text([], made['rows']))
    assert '{327, 0x340211, 0x12, 0x1, (void *)0x80136000, (void *)0x80136100, (void *)0x80136200, (void *)0x80136300, (void *)0x800761c8}' in text
    # without the game's second scripts there is the gauge and the dive, as before
    plain, _ = own.build('cloud', CTX)
    assert len(plain['rows']) == 5 and plain['shot'] is None and 'LimitFrame' not in '\n'.join(plain['source'])


def test_byleth_puts_the_bow_and_the_axe_away():
    made, why = own.build('master', CTX)
    c = '\n'.join(made['source'])
    assert [r['name'] for r in made['rows']] == ['the whip has caught something', 'the kick off it', 'the bow put away', 'the axe put away']
    assert '#define ST_BOW_CANCEL 375' in c and '#define AXE_COMMIT 46.0f' in c
    assert 'if (s == 341 || s == 342 || s == 345 || s == 346)' in c
    assert '(fd->input.down & SHIELD_BUTTONS) && fd->state.frame < AXE_COMMIT' in c
    # the bow is put away, or left by a jump, only between the game's two frames of drawing it
    assert 'if (bow_age[p] >= BOW_CANCEL_FROM && bow_age[p] <= BOW_CANCEL_TO)' in c
    assert 'Fighter_IASACheck_JumpF(gobj) : Fighter_IASACheck_JumpAerial(gobj)' in c
    told = dict(CTX, own={'n': {'cancel_start_frame': 20, 'cancel_end_frame': 65, 'turn_disable_frame': 9}})
    c2 = '\n'.join(own.build('master', told)[0]['source'])
    assert '#define BOW_CANCEL_FROM 20 ' in c2 and '#define BOW_CANCEL_TO 65 ' in c2 and '#define BOW_TURN_WAIT 9 ' in c2
    # drawn, it can be turned round (the loop's states), with the game's wait between turns
    assert 'if ((s == 342 || s == 346) && !bow_wait[p] && fd->input.lstick.X * fd->facing_direction < -0.5f)' in c2
    assert 'latch_on[fd->ply] = i;' in c and '*to = od->phys.pos;' in c                                  # it follows what it caught


# ------------------------------------------------------------------------- a shot that holds
def test_an_item_gets_a_second_state_whose_script_hits_again_and_again():
    out, _, desc = items.add_item(item_files.fighter(False), item_files.fighter(True), 0, Dat)
    out, state = items.add_state(out, desc, Dat)
    assert state == 1
    hit = {'damage': 2, 'angle': 80, 'weight_set_knockback': 30, 'size': 2894, 'again': 0}
    out = items.set_script(out, desc, state, [(0, hit), (6, hit), (28, dict(hit, damage=3, angle=48)), (30, None), (30, items.DONE)], Dat)
    d = Dat(out)
    array = d.ptr(desc + items.STATES)
    first, second = d.ptr(array + items.SCRIPT), d.ptr(array + 0x10 + items.SCRIPT)
    assert first is not None and second is not None and second != first
    words = [d.u32(second + 4 * i) for i in range(24)]
    assert words[0] >> 26 == items.HITBOX and (words[0] >> 20) & 7 == 0 and words[0] & 0x1FFF == 2       # the first run of hits
    assert words[5] >> 24 == 0                                                                         # it never hits again by itself
    assert items.TIMER == 1                                                                            # "so many frames": an item's script counts no frames
    assert words[6] == (items.TIMER << 26) | 6 and (words[7] >> 20) & 7 == 1                           # a new run six frames on
    assert words[13] == (items.TIMER << 26) | 22 and (words[14] >> 20) & 7 == 2 and words[14] & 0x1FFF == 3
    assert words[20:24] == [(items.TIMER << 26) | 2, items.NO_HITBOXES << 26, (items.SET_VAR << 26) | 1, 0]
    assert d.u32(first) >> 26 == items.HITBOX                                                          # the first state keeps its script


def test_a_holding_shots_code_stops_it_and_runs_its_second_state():
    shot = {'joint': 75, 'flag': 1, 'onload': 0x801364AC, 'variant': 'beam_limit[fd->ply]', 'shots': [
        {'item': 0, 'states': (343, 344), 'pierce': False, 'rise': 5.7, 'variant': 0},
        {'item': 2, 'states': (378, 343, 344), 'pierce': False, 'rise': 7.8, 'variant': 1,
         'trap': {'life': 31, 'ahead': 10.8, 'lag': 0.5}}]}
    lines, files = code.shot_source(shot)
    c = '\n'.join(lines)
    assert 'if ((s == 343 || s == 344) && (beam_limit[fd->ply]) == 0)' in c
    assert 'if ((s == 378 || s == 343 || s == 344) && (beam_limit[fd->ply]) == 1)' in c
    hold = files[2]
    assert '#define HOLD_AHEAD 10.8f' in hold and 'id->pos.X += HOLD_AHEAD * id->facing_direction;' in hold
    assert 'id->itcmd_var.flag1 = 1;' in hold and 'if (id->state == 1 && id->itcmd_var.flag1)' in hold      # the script says when it is over
    assert 'id->cb.on_enter_hitlag = Hold_Lag;' in hold and '{.state = 1, .animCallback = Shot_Anim' in hold
    assert '#define HOLD_LAG 0.5f' in hold and 'id->dmg.hitlag_remaining *= HOLD_LAG;' in hold
    assert 'Hold_Coll' not in files[0] and 'bool OnGiveDamage(GOBJ *item) { return true; }' in files[0]


def test_a_chain_is_not_shut_by_a_button_pressed_early():
    text, provides = code.source('Marth', chain={'states': [349, 350, 358], 'flag': 1})
    c = text['fighter.c']
    assert 'a chain that a button pressed early does not shut' in provides
    assert 'if (s == 349 || s == 350 || s == 358)' in c and 'fd->ftcmd_var.flag1 = 0;' in c and 'ChainFrame(fd);' in c


def test_a_trail_takes_the_games_colour_for_each_move():
    trail = {'x0': 0.0, 'x4': 0.0, 'start_alpha': 255, 'end_alpha': 0, 'in_col': [97, 159, 212, 255], 'out_col': [255, 255, 255, 255],
             'x12': 0, 'x13': 0, 'bone': 75, 'bottom': 1.22, 'top': 16.56,
             'by_action': [{'in_col': [220, 200, 90, 255], 'actions': [303, 328]}, {'in_col': [230, 90, 80, 255], 'actions': [321]}]}
    text, provides = code.source('Marth', trail)
    c = text['fighter.c']
    assert "the fighter's own sword trail, in 3 colours by move" in provides
    assert 'static AfterImageDesc trail_2 = {' in c and '.in_col = {230, 90, 80, 255}' in c
    assert 'if (a == 303 || a == 328)\n        return &trail_1;' in c and c.index('return &trail_2;') < c.index('return &trail;')
    plain, _ = code.source('Marth', dict(trail, by_action=[]))
    assert 'fd->action_id' not in plain['fighter.c'] and 'trail_1' not in plain['fighter.c']


# --------------------------------------------------------------------------------- sounds
def adpcm(nibbles, scale=0, pair=0):
    """One eight-byte block of GameCube ADPCM: fourteen 4-bit steps under one header."""
    out = bytearray([pair << 4 | scale])
    for a, b in zip(nibbles[::2], nibbles[1::2]):
        out.append((a & 0xF) << 4 | (b & 0xF))
    return bytes(out)


def idsp(blocks, rate=48000, count=28, coefs=(0,) * 16):
    head = bytearray(0xA0)
    head[:4] = b'IDSP'
    struct.pack_into('>9I', head, 8, 1, rate, count, 0, 0, 0x10, 0x40, 0x60, 0xA0)
    struct.pack_into('>16h', head, 0x40 + 0x1C, *coefs)
    return bytes(head) + b''.join(blocks)


def bank(entries):
    """A .nus3audio file holding the named sounds."""
    names = b''.join(n.encode() + b'\0' for n in entries)
    count = len(entries)
    head = 24 + (8 + 4 * count) * 2 + (8 + 8 * count) + (8 + len(names)) + 8
    at, name_at, offs, data = head, 24 + (8 + 4 * count) * 2 + (8 + 8 * count) + 8, [], b''
    name_offsets = []
    for n, sound in entries.items():
        name_offsets.append(name_at)
        name_at += len(n) + 1
        offs.append((at + len(data), len(sound)))
        data += sound
    out = b'NUS3' + struct.pack('<I', 0) + b'AUDIINDX' + struct.pack('<II', 4, count)
    out += b'TNID' + struct.pack('<I', 4 * count) + b''.join(struct.pack('<I', i) for i in range(count))
    out += b'NMOF' + struct.pack('<I', 4 * count) + b''.join(struct.pack('<I', o) for o in name_offsets)
    out += b'ADOF' + struct.pack('<I', 8 * count) + b''.join(struct.pack('<II', o, s) for o, s in offs)
    out += b'TNNM' + struct.pack('<I', len(names)) + names
    out += b'PACK' + struct.pack('<I', len(data)) + data
    assert len(out) == head + len(data)
    return out


def test_a_games_sound_is_read_as_the_gamecubes_own_audio(tmp_path):
    # with no coefficients each step is the sample itself (times the scale); with a coefficient it builds on the last
    flat = idsp([adpcm([1, 2, 3, -1, -2, 0, 7, -8, 0, 0, 0, 0, 0, 0], scale=4), adpcm([1] * 14)])
    rate, samples = nus3audio.pcm(flat)
    assert rate == 48000 and list(samples[:8]) == [16, 32, 48, -16, -32, 0, 112, -128] and list(samples[14:17]) == [1, 1, 1]
    rising = idsp([adpcm([1] * 14)], count=14, coefs=(2048,) + (0,) * 15)            # each sample: the last one plus one
    assert list(nus3audio.pcm(rising)[1]) == list(range(1, 15))
    path = tmp_path / 'vc_test.nus3audio'
    path.write_bytes(bank({'vc_test_attack01': flat, 'vc_test_attack02': rising}))
    assert list(nus3audio.sounds(path)) == ['vc_test_attack01', 'vc_test_attack02'] and nus3audio.sounds(path)['vc_test_attack02'] == rising
    import wave
    wav = nus3audio.to_wav(flat, tmp_path / 'a.wav', 24000)
    with wave.open(str(wav)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (1, 24000, 14)


def test_the_donors_samples_are_swapped_for_the_fighters_sound_for_the_same_thing(tmp_path, monkeypatch):
    root = tmp_path
    one = idsp([adpcm([1] * 14)], count=14)
    for rel, entries in (('fighter/se_test', {'se_test_special_S01': one, 'se_test_special_S02': one, 'se_test_swing_m': one}),
                         ('fighter_voice/vc_test', {'vc_test_attack01': one, 'vc_test_attack02': one, 'vc_test_cliffcatch': one}),
                         ('fighter_voice/vc_test_cheer', {'vc_test_cheer': one})):
        path = root / 'gamedata' / 'sound' / 'bank' / (rel + '.nus3audio')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bank(entries))
    samples = ['se_call_mars', 'v_mars_atk1', 'v_mars_atk2', 'v_mars_atk3', 'v_mars_gake', 'v_mars_jump', 'se_mars_sw_conbo1',
               'se_mars_sw_conbo2', 'se_mars_sw_conbo3', 'se_mars_sw_demo_nuki', 'se_mars_unknown']
    chosen, left = voice.choose('Marth', 'test', root, samples)
    assert {k: v[0] for k, v in chosen.items()} == {
        'se_call_mars': 'vc_test_cheer', 'v_mars_atk1': 'vc_test_attack01', 'v_mars_atk2': 'vc_test_attack02',
        'v_mars_atk3': 'vc_test_attack01',                                   # fewer grunts than the donor has: round again
        'v_mars_gake': 'vc_test_cliffcatch', 'se_mars_sw_conbo1': 'se_test_special_S01', 'se_mars_sw_conbo2': 'se_test_special_S02',
        'se_mars_sw_conbo3': 'se_test_special_S01', 'se_mars_sw_demo_nuki': 'se_test_swing_m',
        # a voice of the donor's the fighter has no line for is silent (the donor's kept scripts play that sample on
        # its own occasion: whatever sat in it would be heard on every jump), and still listed as missing
        'v_mars_jump': voice.SILENCE}
    assert any(line.startswith('v_mars_jump: the fighter has no vc_test_jump01') for line in left)
    assert any(line.startswith('se_mars_unknown: nothing in the fighter') for line in left)
    # a script plays each by the donor's bank number and the place of the script named after its sample
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as z:
        z.writestr('scripts.json', json.dumps(['SFX_se_call_mars', 'SFXv_mars_atk1', 'SFXv_marsB_atk1', 'SFXv_mars_atk3',
                                               'SFXse_mars_sw_conbo1']))
    numbers = voice.calls(package.getvalue(), 19, chosen)
    assert numbers == {'vc_test_cheer': 190000, 'vc_test_attack01': 190001, 'se_test_special_s01': 190004}
    # ... unless that script does more than play it (the donor's charge sound loops with its pitch rising):
    # the fighter's sound would come out looped and bent too
    plain = bytes([1, 0, 0, 5, 16, 0, 0, 20, 14, 0, 0, 0])
    looped = bytes([1, 0, 0, 5, 2, 0, 0, 100, 13, 4, 0, 1, 3, 0, 0, 2, 14, 0, 0, 0])
    bodies = [plain, plain, plain, plain, looped]
    offsets, at = [], 12 + 8 + 4 * (len(bodies) + 1)
    for body in bodies:
        offsets.append(at)
        at += len(body)
    sem = (bytes(8) + struct.pack('>I', 1) + struct.pack('>2I', 0, len(bodies)) + struct.pack(f'>{len(bodies) + 1}I', *offsets, 0)
           + b''.join(bodies))
    assert voice.sound_steps(sem) == [[1, 16, 14]] * 4 + [[1, 2, 13, 3, 14]]
    with zipfile.ZipFile(package, 'a') as z:
        z.writestr('scripts.sem', sem)
    assert voice.calls(package.getvalue(), 19, chosen) == {'vc_test_cheer': 190000, 'vc_test_attack01': 190001}


def test_a_move_plays_the_fighters_own_sounds_and_melees_own_dust():
    cues = {'swings': {}, 'swing': (17, {'behavior': 1, 'sfx_id': 158, 'volume': 127}, None), 'voice': (18, {}, None),
            'own_sound': (17, {'behavior': 1, 'sfx_id': 190121, 'volume': 127}, None),
            'own_voice': (17, {'behavior': 2, 'sfx_id': 190076, 'volume': 127}, None),
            'effects': {1021: (10, {'gfx_id': 1021, 'bone_id': 0}, None)}}
    move = {'effects': [{'cmd': 'LANDING_EFFECT', 'real': 9, 'args': ['sys_atk_smoke', 'top', 0]},
                        {'cmd': 'EFFECT', 'real': 4, 'args': ['cloud_kyogiri_stroke1_r', 'top', 0]}],
            'sounds': [{'cmd': 'PLAY_SE', 'real': 6, 'name': 'se_test_special_s01'}, {'cmd': 'PLAY_SE', 'real': 8, 'name': 'se_test_attackhard_s01'},
                       {'cmd': 'PLAY_SEQUENCE', 'real': 6, 'name': 'vc_test_special_s01'}]}
    items_, added = dress([(0, {}, None)], move, 30, cues, 'SpecialS1', 'test', sound_ids={'se_test_special_s01': 190121})
    assert added == ['effect 9 (sys_atk_smoke)', 'swing 6 (its own: se_test_special_s01)', 'swing 8', 'voice 6']
    played = [(frame, item[0], item[1].get('sfx_id', item[1].get('gfx_id'))) for frame, item in timed(items_) if item[0] in (10, 17, 18)]
    assert sorted(played) == [(6, 17, 190121), (6, 18, None), (8, 17, 158), (9, 10, 1021)]       # the fighter's own effect is not carried
    assert EFFECT_MELEE['sys_smash_flash'] == 1011


def test_a_specials_voice_played_by_a_sequence_is_named_and_given_its_first_line():
    # Shulk (2026-11-13): his scripts play three voices by SEQUENCE, hashes the reader could not name (the trial named
    # them by length and crc32); Back Slash and Air Slash were silent of his voice
    from echo_ultimate.gamedata import names
    from echo_ultimate.gamedata.prc import hash40
    known = names.candidates('shulk')
    for hashed, name in ((0x14b22e12fe, 'seq_shulk_rnd_attack'), (0x17fecb0386, 'seq_shulk_rnd_special_s'),
                         (0x1774aeca6a, 'seq_shulk_rnd_special_h')):
        assert hash40(name) == hashed and name in known
    game = {'moves': {'game_specials': {'sounds': [{'cmd': 'PLAY_SEQUENCE', 'real': 5, 'name': 'seq_test_rnd_special_s'}]},
                      'game_specialhi': {'sounds': [{'cmd': 'PLAY_SEQUENCE', 'real': 3, 'name': 'seq_test_rnd_special_h'}]},
                      'game_attack11': {'sounds': [{'cmd': 'PLAY_SEQUENCE', 'real': 2, 'name': 'seq_test_rnd_attack'}]}}}
    voices = {'vc_test_special_s02', 'vc_test_special_s01', 'vc_test_attack01', 'vc_test_special_n01'}
    assert voice.name_sequences(game, 'test', voices) == {'seq_test_rnd_special_s': 'vc_test_special_s01',
                                                           'seq_test_rnd_special_h': None}
    e = game['moves']['game_specials']['sounds'][0]
    assert (e['name'], e['sequence'], e['stand_in']) == ('vc_test_special_s01', 'seq_test_rnd_special_s',
                                                         'the first of the 2 lines the game picks from')
    assert game['moves']['game_attack11']['sounds'][0]['name'] == 'seq_test_rnd_attack'    # the donor's voice cue picks
    # ... and the dresser now plays the line as the fighter's own voice
    cues = {'swings': {}, 'voice': (18, {}, None), 'own_voice': (17, {'behavior': 2, 'sfx_id': 190076, 'volume': 127}, None)}
    _, added = dress([(0, {}, None)], game['moves']['game_specials'], 30, cues, 'SpecialS', 'test',
                     sound_ids={'vc_test_special_s01': 190077})
    assert added == ['voice 5 (its own: vc_test_special_s01)']


def test_a_normals_voice_set_is_named_and_played_by_the_donors_pick():
    # Wolf (leftovers, 2026-11-13): his third jab's set was the hash 0x16ac2320b7, nine letters (`attack_a3`); and no
    # normal's set played anything on the own route (it writes his scripts new: there is no donor voice cue left)
    from echo_ultimate.gamedata import names
    from echo_ultimate.gamedata.prc import hash40
    assert hash40('seq_wolf_rnd_attack_a3') == 0x16ac2320b7 and 'seq_wolf_rnd_attack_a3' in names.candidates('wolf')
    cues = {'swings': {}, 'voice': (18, {'value': 0}, None)}
    jab = {'sounds': [{'cmd': 'PLAY_SEQUENCE', 'real': 4, 'name': 'seq_wolf_rnd_attack_a3'}]}
    items_, added = dress([(0, {}, None)], jab, 30, cues, 'Attack13', 'wolf')
    assert added == ['voice 4 (picked, for seq_wolf_rnd_attack_a3)'] and (18, {'value': 0}, None) in items_
    # not twice, not where nothing of the donor's may stand in, not for a set that is not an attack's
    assert dress(items_, jab, 30, cues, 'Attack13', 'wolf')[1] == []
    assert dress([(0, {}, None)], jab, 30, cues, 'Attack13', 'wolf', own_only=True)[1] == []
    fall = {'sounds': [{'cmd': 'PLAY_SEQUENCE', 'real': 4, 'name': 'seq_wolf_rnd_futtobi01'}]}
    assert dress([(0, {}, None)], fall, 30, cues, 'DamageFlyHi', 'wolf')[1] == []


def test_a_second_body_has_its_costumes_under_the_next_folders_names():
    root = os.environ.get('ULTIMATE_DUMP')
    if not root or not (Path(root) / 'Hashes_FullPath').exists():
        pytest.skip('needs ULTIMATE_DUMP')
    from fighter_port import recolors
    assert list(recolors.costume_folders(root, 'master')) == ['c00', 'c02', 'c04', 'c06']
    assert list(recolors.costume_folders(root, 'master', 'c01')) == ['c01', 'c03', 'c05', 'c07']


def test_a_sound_waits_for_the_frame_after_the_one_its_state_starts_on():
    # the donor enters its release state on frame 1, and the engine plays no sound up to the frame a state starts on
    from fighter_port.oneshot import STARTS_ON
    cues = {'swings': {}, 'own_sound': (17, {'behavior': 0, 'sfx_id': 190121, 'volume': 127}, None)}
    move = {'sounds': [{'cmd': 'PLAY_SE', 'real': 1, 'name': 'se_test_special_n01'}]}
    ids = {'se_test_special_n01': 190109}
    first = STARTS_ON['Marth']['SpecialNEnd'] + 1
    items_, added = dress([(0, {}, None)], move, 30, cues, 'SpecialNEnd', 'test', -2, sound_ids=ids, first=first)
    assert first == 2 and [(f, i[1]['sfx_id']) for f, i in timed(items_)] == [(2, 190109)] and added == ['swing 2 (its own: se_test_special_n01)']
    items_, _ = dress([(0, {}, None)], move, 30, cues, 'SpecialS1', 'test', sound_ids=ids)
    assert [f for f, _ in timed(items_)] == [1]


def test_a_specials_sample_takes_the_sound_its_own_script_plays(tmp_path):
    # which of a fighter's numbered sounds a move uses is the script's word: a bow's release is its third
    one = idsp([adpcm([1] * 14)], count=14)
    for rel, entries in (('fighter/se_test', {'se_test_special_N01': one, 'se_test_special_N02': one, 'se_test_special_N03': one}),
                         ('fighter_voice/vc_test', {'vc_test_special_n01': one})):
        path = tmp_path / 'gamedata' / 'sound' / 'bank' / (rel + '.nus3audio')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bank(entries))
    moves = {'game_specialn': {'sounds': [{'cmd': 'PLAY_SE', 'real': 1, 'name': 'se_test_special_n03'}]},
             'game_specialnstart': {'sounds': [{'cmd': 'PLAY_SE', 'real': 20, 'name': 'vc_test_special_n01'},
                                               {'cmd': 'PLAY_STATUS', 'real': 27, 'name': 'se_test_special_n01'}]}}
    samples = ['se_mars_sbreak', 'se_mars_sbreak_tame']
    chosen, _ = voice.choose('Marth', 'test', tmp_path, samples, moves)
    # a special's sound with no sample of the donor's left to take is added to the bank (its name led by a plus)
    assert {k: v[0] for k, v in chosen.items()} == {'se_mars_sbreak': 'se_test_special_N03', 'se_mars_sbreak_tame': 'se_test_special_N01',
                                                    '+vc_test_special_n01': 'vc_test_special_n01'}
    chosen, _ = voice.choose('Marth', 'test', tmp_path, samples)          # with no scripts to go by: in number order
    assert {k: v[0] for k, v in chosen.items()} == {'se_mars_sbreak': 'se_test_special_N01', 'se_mars_sbreak_tame': 'se_test_special_N02'}


def test_a_sound_kept_as_numbered_variants_takes_the_first_under_the_name_its_script_plays(tmp_path):
    # Incineroar's Cross Chop landing plays se_gaogaen_special_h04; the bank holds only _h04_01 and _h04_02 (the
    # game picks one): passed over, it was silent and no receipt said so (cold trial, 2026-11-13)
    one, two = idsp([adpcm([1] * 14)], count=14), idsp([adpcm([2] * 14)], count=14)
    path = tmp_path / 'gamedata' / 'sound' / 'bank' / 'fighter' / 'se_test.nus3audio'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bank({'se_test_special_h04_01': one, 'se_test_special_h04_02': two}))
    moves = {'game_specialhibound': {'sounds': [{'cmd': 'PLAY_SE', 'real': 1, 'name': 'se_test_special_h04'}]}}
    chosen, left = voice.choose('Marth', 'test', tmp_path, ['se_mars_sbreak'], moves)
    named = {v[0]: v[1] for v in chosen.values()}
    assert 'se_test_special_h04' in named and not any('h04' in why for why in left)
    first = voice._banks(tmp_path, 'test')['se']['se_test_special_h04_01'][1]
    assert named['se_test_special_h04'] == first


def test_a_special_that_runs_through_its_first_state_can_still_be_turned_around():
    # Blade Beam passes the donor's start state in one frame: the first frames of the move run on into its release
    rows=([dict(action=295+i,flags=0,move=0,bits=0,anim=0,iasa=0,phys=0,coll=0,camera=0)
           for i in range(38)], [])
    text, provides = code.source('Marth', reverse=[341, 349, (342, 4), (343, 3), (344, 3), (378, 2)], state_rows=rows)
    c = text['fighter.c']
    assert 'specials that can be turned around as they start' in provides
    assert 'ReverseFrame(fd);' not in c and 'Reverse_IASA_341' in c
    assert rows[0][0]['iasa']==0  # code generation does not mutate the caller's table
    with pytest.raises(ValueError,match='needs the donor and own state rows'):
        code.source('Marth',reverse=[341])
    assert ('if (!(((s == 341 || s == 349 || s == 342) && fd->state.frame <= 4.0f) || ((s == 343 || s == 344) && fd->state.frame <= 3.0f)'
            ' || ((s == 378) && fd->state.frame <= 2.0f)))') in c
    plain, _ = code.source('Marth', reverse=[341, 349], state_rows=rows)
    assert 'if (!(s == 341 || s == 349) || fd->state.frame > 4.0f)' in plain['fighter.c']


def test_an_effect_goes_where_the_game_puts_it():
    import numpy as np
    from fighter_port.oneshot import placed
    donor = (10, {'bone_id': 0, 'use_common_bone_ids': 0, 'destroy_on_state_change': 0, 'unk1': 0, 'gfx_id': 1011, 'unk2': 0,
                  'z': 0, 'y': 0, 'x': 0, 'range_z': 5, 'range_y': 5, 'range_x': 5}, None)
    place = {'bone': 75, 'weapon': {'haver': np.array([[0, 0.5, 0], [0.5, 0, 0], [0, 0, 0.5]])}, 'scale': 0.5}
    # on the weapon: the game's point, carried into the donor's weapon joint (the offsets are the joint's x, y, z)
    on_sword = placed(donor, ['sys_smash_flash', 'haver', -2, 10, 0], place)[1]
    assert (on_sword['bone_id'], on_sword['z'], on_sword['y'], on_sword['x']) == (75, 1280, -256, 0) and on_sword['range_x'] == 0
    # over the feet: its height only
    over_feet = placed(donor, ['sys_smash_flash', 'top', 3, 17, 4], place)[1]
    assert (over_feet['bone_id'], over_feet['z'], over_feet['y'], over_feet['x']) == (0, 0, 2176, 0)
    assert placed(donor, ['sys_smash_flash', 'hip', 0, 2, 0], place) is donor      # a bone with no rule: as the donor has it
    assert placed(donor, ['sys_smash_flash', 'haver', 0, 2, 0], None) is donor


def test_a_sword_swing_the_game_draws_with_an_effect_gets_the_trail():
    cues = {'swings': {}, 'trail_on': (49, {'render_status': 0}, None), 'trail_off': (49, {'render_status': 1}, None)}
    blank = [(0, {}, None)]
    # hitboxes out on the weapon and no trail command: the trail runs from a little before them to a little after
    lunge = {'hitboxes': [{'bone': 'haver', 'first': 9, 'last': 13, 'damage': 11}, {'bone': 'top', 'first': 14, 'last': 18, 'damage': 8}]}
    assert dress(blank, lunge, 40, cues, 'AttackDash', 'test')[1] == ['trail 7-15']
    # hitboxes on the fighter's base point, with a slash effect of the fighter's own: the sword's all the same
    smash = {'hitboxes': [{'bone': 'top', 'first': 19, 'last': 19, 'damage': 4}, {'bone': 'top', 'first': 24, 'last': 24, 'damage': 3}],
             'effects': [{'cmd': 'EFFECT_FOLLOW', 'real': 18, 'args': ['test_smash_slash', 'top', 0]}]}
    assert dress(blank, smash, 60, cues, 'AttackS4', 'test')[1] == ['trail 17-26']
    # a move the game marks with lines of speed drives its weapon the way it points (a stab down, a lunge): a
    # trail there would be a spike off the blade's tip, so none is made up for it
    stab = dict(lunge, effects=[{'cmd': 'EFFECT_FOLLOW_COLOR', 'real': 8, 'args': ['test_speedline', 'top', 0]}])
    assert dress(blank, stab, 40, cues, 'AttackAirLw', 'test')[1] == []
    both = dict(smash, effects=smash['effects'] + [{'cmd': 'EFFECT_FOLLOW_COLOR', 'real': 8, 'args': ['test_speedline', 'top', 0]}])
    assert dress(blank, both, 60, cues, 'AttackDash', 'test')[1] == []
    # a kick has the game's common arc too: no trail
    kick = {'hitboxes': [{'bone': 'top', 'first': 4, 'last': 5, 'damage': 3}],
            'effects': [{'cmd': 'EFFECT', 'real': 3, 'args': ['sys_attack_arc_b', 'top', 0]}]}
    assert dress(blank, kick, 30, cues, 'Attack11', 'test')[1] == []
    # and a move the game does give a trail keeps the game's own frames
    own = dict(lunge, effects=[{'cmd': 'AFTER_IMAGE4_ON_arg29', 'real': 5, 'args': ['tex']}, {'cmd': 'AFTER_IMAGE_OFF', 'real': 12, 'args': [4]}])
    assert dress(blank, own, 40, cues, 'AttackHi3', 'test')[1] == ['trail 5-12']
    risen = dict(own, effects=own['effects'] + [{'cmd': 'EFFECT_COLOR', 'real': 6, 'args': ['test_speedline', 'top', 0]}])
    assert dress(blank, risen, 40, cues, 'SpecialHi', 'test')[1] == ['trail 5-12']       # the game's own word stands


def test_second_versions_take_a_trail_colour_of_their_own():
    from types import SimpleNamespace as Act
    from fighter_port.oneshot import trail_colours
    moves = {'game_specials1': {}, 'game_speciallw': {}, 'game_attackhi3': {}, '0x11': {}}
    table = {'c05specials1': [{'target_motion': 'SpecialS1'}, {'target_motion': 'SpecialAirS1'}],
             'c05speciallw': [{'target_motion': 'SpecialLw'}], 'c00attackhi3': [{'target_motion': 'AttackHi3'}]}
    actions = [Act(motion='SpecialS1', index=303, anim_size=1), Act(motion='SpecialS1', index=328, anim_size=1),
               Act(motion='SpecialAirS1', index=312, anim_size=1), Act(motion='SpecialLw', index=323, anim_size=1),
               Act(motion='AttackHi3', index=55, anim_size=1), Act(motion='SpecialLw', index=400, anim_size=0)]
    yellow, blue = [143, 186, 101, 0], [97, 159, 212, 0]
    others, second, alt = {'game_specials1': yellow, 'game_speciallw': blue}, {'SpecialS1': '0x11'}, {'SpecialS1': 328}
    # the second version of the side special has no colour of its own in the data: it takes the one named for
    # second versions, and that colour does not leak onto the move's other actions
    assert trail_colours(others, 'game_speciallw', table, moves, second, alt, actions) == [
        {'in_col': blue, 'actions': [323, 328]}, {'in_col': yellow, 'actions': [303, 312]}]
    assert trail_colours(others, None, table, moves, second, alt, actions) == [
        {'in_col': blue, 'actions': [323]}, {'in_col': yellow, 'actions': [303, 312]}]


def test_byleths_kick_wall_and_dash_take_the_games_numbers():
    ctx = dict(CTX, own={'hi': {'jump_speed_x': 0.9, 'jump_speed_y': 2.6, 'wall_hit_max': 3, '0x16ac56872a': 50.0, '0x171e7b6a7c': 2.0},
                         's': {'0x0c7cbfe735': 3.0, '0x0ce4436a80': 0.34}},
               tether={'state': 368, 'first': 12, 'last': 30, 'width': 30.0, 'y': 20.0, 'height': 40.0},
               stomp={'damage': 6.5, 'angle': 260, 'kbg': 110, 'bkb': 14}, wall_act=24, world=1.0,
               action=dict(CTX['action'], SpecialAirS4S=320), total=dict(CTX['total'], SpecialAirS4S=40))
    made, _ = own.build('master', ctx)
    c = '\n'.join(made['source'])
    # the kick: harder the further out the whip caught, and a hurt fighter is sent down
    assert '#define STOMP_DAMAGE 6.5f' in c and '#define STOMP_MORE 2.0f' in c and '#define STOMP_AT 50.0f' in c
    assert '#define STOMP_ANGLE 260 ' in c and '#define STOMP_KBG 110' in c and '#define STOMP_BKB 14' in c
    # the whip's reach: from his hand (a little over half his height up) to where its tip gets
    assert '#define WALL_HAND 9.6f' in c and '#define WHIP_REACH 42.7' in c
    assert 'Fighter_UpdateHitboxDamage(hit, (int)(STOMP_DAMAGE * stomp[p] + 0.5f), gobj);' in c
    assert 'float far = sqrtf(best) / WHIP_REACH;' in c                              # how far off the caught fighter was
    assert 'down = ((FighterData *)other->userdata)->dmg.percent >= STOMP_AT;' in c and 'hit->kb = STOMP_BKB;' in c
    # he leaves the kick with the game's speeds
    assert '#define HOP_X 0.9f' in c and '#define HOP_Y 2.6f' in c and 'fd->phys.self_vel.X = HOP_X * fd->input.lstick.X;' in c
    # the wall: a state of its own for the jump off it, as many walls as the game allows, on the frames the whip is out
    assert made['rows'][-1]['name'] == 'the jump off a wall the whip caught' and '#define ST_WALLJUMP 377' in c
    assert '#define WALL_MAX 3 ' in c and '#define WALL_FROM 14.0f' in c and '#define WALL_TO 30.0f' in c and '#define WALL_ACT 23.0f' in c
    assert 'WALL_LEFT(ax, ay, tip.X, tip.Y, &hit, &line, &flags, &normal, -1, -1)' in c and '0x800501CC' in c and '0x800509B8' in c
    assert 'if (fd->phys.air_state == 0)\n        wall_count[p] = 0;' in c
    # the dash of a flicked side special
    assert '#define LUNGE_SPEED 3.0f' in c and '#define LUNGE_BRAKE 0.34f' in c and '#define ST_SIDE ' in c
    assert 'lunge[p] = fd->input.timer_lstick_smash_x < LUNGE_FLICK ? LUNGE_SPEED : 0.0f;' in c
    # the axe: the published frames it can be turned round on
    assert '#define AXE_TURN_FROM 12.0f' in c and '#define AXE_TURN_TO 41.0f' in c
    # without the clip of the jump off a wall there is no wall to catch
    bare = dict(ctx, action={k: v for k, v in ctx['action'].items() if k != 'SpecialAirS4S'})
    plain = '\n'.join(own.build('master', bare)[0]['source'])
    assert '#define WALL_MAX 0 ' in plain and len(own.build('master', bare)[0]['rows']) == 4


def test_clouds_charge_goes_on_by_itself_and_a_hit_takes_from_the_gauge():
    made, _ = own.build('cloud', dict(CTX, own={'n': {'speed_x_mul': 0.2, 'air_speed_x_mul': 0.4, 'air_speed_y_mul': 0.65}}))
    c = '\n'.join(made['source'])
    assert '!(fd->input.held & B_BUTTON)' not in c                                   # letting go does not end it
    assert '((fd->input.down & B_BUTTON) && charge_age[p] >= CHARGE_AGAIN)' in c and '#define CHARGE_AGAIN 8 ' in c
    assert '#define CANCEL_BUTTONS 0xC70' in c
    assert 'Fighter_IASACheck_AllGrounded(gobj);' in c and 'if (fd->state_id == state)' in c
    assert 'else if (limit[p] < 1.0f)\n            limit[p] = limit[p] > by ? limit[p] - by : 0.0f;' in c
    assert 'was_charging[p] = fd->state_id >= ST_CHARGE_START && fd->state_id <= ST_CHARGE_END;' in c
    # the neutral special keeps part of his speed as it starts
    assert '#define N_GROUND_X 0.2f' in c and '#define N_AIR_X 0.4f' in c and '#define N_AIR_Y 0.65f' in c
    assert 'fd->phys.self_vel.Y *= N_AIR_Y;' in c


def test_a_sound_a_script_plays_is_also_given_a_plain_place_when_its_row_put_it_where_the_donor_loops(monkeypatch):
    # the donor's charge sample is played in a loop by the donor's own code; the row for it takes the first sound
    # the fighter's neutral start plays. When the port writes that start's script itself, the script can call the
    # sound only by a plain place, so the sound still wants one (here the release's sample, which nothing else wants)
    sound = lambda: {'pcm': np.ones(320, np.int16), 'rate': 32000}
    se = {n: (n, sound()) for n in ('se_x_charge01',)}
    monkeypatch.setattr(voice, '_banks', lambda root, fighter, game='ultimate': {'se': se, 'vc': {}, 'cheer': {}})
    plain = lambda sample: [(1, sample), (16, 1), (4, 15), (6, 204), (14, 0)]
    loop = lambda sample: [(1, sample), (2, 0), (13, 5), (3, 0), (14, 0)]
    samples = ['se_mars_sbreak', 'se_mars_sbreak_tame']
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as z:
        z.writestr('scripts.sem', voice.sem_write([plain(0), loop(1)]))
        z.writestr('scripts.json', json.dumps(['SFX' + s for s in samples]))
    moves = {'game_specialnstart': {'hitboxes': [], 'sounds': [{'cmd': 'PLAY_SE', 'name': 'se_x_charge01'}]}}
    # where the donor's code still plays its charge place, the row keeps it there too
    chosen, _ = voice.choose('Marth', 'x', None, samples, moves, 'ultimate', package.getvalue(), route='donor')
    assert chosen['se_mars_sbreak_tame'][0] == 'se_x_charge01' and chosen['se_mars_sbreak'][0] == 'se_x_charge01'
    assert voice.calls(package.getvalue(), 19, chosen) == {'se_x_charge01': 190000}
    # on his own skeleton nothing of the donor's plays it: that place is silent (7.18) and the plain one holds it
    chosen, _ = voice.choose('Marth', 'x', None, samples, moves, 'ultimate', package.getvalue(), route='own skeleton')
    assert chosen['se_mars_sbreak_tame'][0] == voice.SILENCE and chosen['se_mars_sbreak'][0] == 'se_x_charge01'
    assert voice.calls(package.getvalue(), 19, chosen) == {'se_x_charge01': 190000}
