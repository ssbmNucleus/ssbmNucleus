"""States of a port's own, the fighter's state table, and the fixes a second fighter's first real test turned up:
the jab chain, move endings that play out, a third jab the donor has no clip for, shots that end at walls."""
import os
import struct
import zipfile
import io
import json
from pathlib import Path

import pytest

from fighter_port import code, combat, own, states
from fighter_port.oneshot import EXTRA_ACTION, add_action, weapon_for, with_ending


def dol(address, payload):
    """A GameCube executable with one data section holding `payload` at `address`."""
    head = bytearray(0x100)
    struct.pack_into('>I', head, 0x00 + 7 * 4, 0x100)       # the first data section's offset in the file,
    struct.pack_into('>I', head, 0x48 + 7 * 4, address)     # its address in memory
    struct.pack_into('>I', head, 0x90 + 7 * 4, len(payload))
    return bytes(head) + payload


def test_the_donors_states_are_read_from_the_executable():
    rows = [struct.pack('>iIBB2x5I', 295 + i, 0x340211, 0x12, 0, 0x80136844 + i, 0x80136914, 0x8013691C, 0x801369A4, 0x800761C8)
            for i in range(3)]
    got = states.donor_states(dol(0x803CF420, b''.join(rows)), 0x803CF420, 3)
    assert [r['action'] for r in got] == [295, 296, 297] and got[1]['anim'] == 0x80136845 and got[0]['move'] == 0x12
    with pytest.raises(ValueError):
        states.dol_at(dol(0x803CF420, b''.join(rows)), 0x80500000, 4)
    with pytest.raises(ValueError):                         # text where functions should be: not a state table
        states.donor_states(dol(0x803CF420, b'PlMs.dat' * 8), 0x803CF420, 1)


def test_the_ports_own_states_follow_the_donors_in_the_table():
    donor = [{'action': 295, 'flags': 0x340211, 'move': 0x12, 'bits': 0, 'anim': 0x80136844, 'iasa': 0, 'phys': 0x8013691C,
              'coll': 0x801369A4, 'camera': 0x800761C8}]
    text = '\n'.join(states.table_text(donor, [{'name': 'the dive', 'action': 318, 'flags': 0x340613, 'move': 0x14,
                                                 'phys': 'Dive_Phys', 'coll': 'Dive_Coll'}]))
    assert 'static struct FtState move_logic[]' in text
    assert '{295, 0x340211, 0x12, 0x0, (void *)0x80136844, 0, (void *)0x8013691c, (void *)0x801369a4, (void *)0x800761c8},    // 341' in text
    assert '{318, 0x340613, 0x14, 0x0, 0, 0, Dive_Phys, Dive_Coll, Fighter_UpdateCameraBox},    // 342: the dive' in text


CTX = {'first': 373, 'action': {m: 300 + i for i, m in enumerate(
           ('SpecialAirS4Hi', 'SpecialS4Hi', 'SpecialS4S', 'SpecialS4Lw', 'SpecialAirS4S', 'SpecialAirS4Lw', 'SpecialHi', 'SpecialAirHi'))},
       'total': {'SpecialAirS4Hi': 101, 'SpecialS4Hi': 22, 'SpecialS4S': 5, 'SpecialS4Lw': 30, 'SpecialAirS4S': 21,
                 'SpecialAirS4Lw': 11, 'SpecialHi': 24, 'SpecialAirHi': 24},
       'state': {'SpecialHi': 367, 'SpecialAirHi': 368, 'SpecialLw': 369, 'SpecialAirLw': 371},
       'functions': {}, 'world': 0.93, 'rise': 11, 'glow': 57, 'tip': 127,
       'moves': {'game_specialhi2': {'hitboxes': [{'first': 12, 'last': None}]}},
       'flags': {'ground': 0x340213, 'air': 0x340613}, 'move': {'up': 0x14, 'down': 0x15}}


def test_clouds_own_states_a_dive_and_a_gauge():
    made, why = own.build('cloud', CTX)
    c = '\n'.join(made['source'])
    assert why is None and [r['name'] for r in made['rows']] == ['the dive', 'its landing', 'Limit Charge starts', 'Limit Charge', 'Limit Charge ends']
    assert '#define ST_DIVE 373' in c and '#define ST_CHARGE_END 377' in c and '#define ST_RISE 367' in c
    assert 'fd->state.frame >= 12.0f ? -6.510f : 0' in c                 # the plunge starts as the script's hitboxes come out
    assert 'DownSpecial(gobj, 369);' in c and 'DownSpecial(gobj, 371);' in c and 'Enter(gobj, ST_CHARGE_START);' in c
    assert 'fd->state.frame >= 11.0f && (fd->input.down & B_BUTTON)' in c and 'fd->state.frame >= 23.0f' in c
    assert made['load'] == ['OwnLoad(fd);'] and made['frame'] == ['OwnFrame(fd, gobj);']
    # what the gauge looks like: a bar on the player's damage display (an object of its own on the displays'
    # drawing list, drawn only by the displays' camera), a light that grows with the gauge, and (when the driver
    # knows Melee's gleam) a gleam on the sword as it fills
    assert 'GObj_AddGXLink(gobj, Gauge_Draw, HUD_LIST, 1);' in c and '#define HUD_LIST 11' in c and 'Gauge_Make(fd->ply);' in c
    assert 'camera->hsd_object != (void *)COBJ_GetCurrent()' in c and 'Vec3 *at = HUD_PLACE(p), a, b;' in c
    assert '#define GAUGE_Y 4.70f' in c and 'DRAW_RECT(&a, &b, &bar);' in c and 'drawn[p](gobj, pass);' in c
    assert 'fd->phys.pos.Y + GAUGE' not in c                              # nothing of it over the fighter's head
    assert 'gobj->gx_cb = (void (*)())Limit_Draw;' in c and 'c->color_enable = 1;' in c and 'if (c->colanim != 0)' in c
    # the light's colour is set as the numbers the game steps each frame too, or the game draws its own stale ones
    assert 'c->color_blue = 255.0f;' in c and 'c->color_alpha = (float)a;' in c and 'c->colorblend_alpha = 0;' in c
    # and an aura of rising streaks, drawn in the pass for see-through shapes, while it charges or is full
    assert '#define AURA_TALL 23.0f' in c and 'if (pass == 2 && aura[p])' in c and 'DRAW_RECT(&a, &b, &glow);' in c
    assert c.index('aura[p] = limit[p] >= 1.0f ? 1 : charging ? 2 : 0;') < c.index('if (c->colanim != 0)')
    assert 'SPAWN_EFFECT' not in c.split('static void OwnFrame')[1]
    lit, _ = own.build('cloud', dict(CTX, gleam={'gfx': 1011, 'bone': 75}, head=18.4))
    assert 'SPAWN_EFFECT(gobj, 1011, 75, 0, 0, &none, &none, 0.0f);' in '\n'.join(lit['source']) and '#define AURA_TALL 21.4f' in '\n'.join(lit['source'])
    assert own.build('cloud', dict(CTX, total={}))[0] is None            # no clips on the actions: nothing to build
    assert own.build('mario', CTX) == (None, None)


def test_byleths_own_states_a_whip_that_latches():
    ctx = dict(CTX, action=dict(CTX['action'], SpecialS2Hi=310, SpecialS2Lw=311), total=dict(CTX['total'], SpecialS2Hi=4, SpecialS2Lw=57))
    made, why = own.build('master', ctx)
    c = '\n'.join(made['source'])
    assert [r['name'] for r in made['rows']][:2] == ['the whip has caught something', 'the kick off it']
    assert '#define TIP_JOINT 127' in c and 'fd->cb.OnGiveDamage = Whip_Hit;' in c and 'Fighter_GetGObj(i)' in c
    assert 'float left = 101.0f - fd->state.frame;' in c and 'fd->phys.self_vel.Y = HOP_Y;' in c
    # the axe can be turned round once, on the published frames
    assert '#define AXE_TURN_FROM 12.0f' in c and 'axe_turned[p] = 1;' in c
    assert 'fd->state.frame >= AXE_TURN_FROM && fd->state.frame <= AXE_TURN_TO' in c
    assert own.build('master', dict(ctx, tip=None))[0] is None           # no whip: nothing to latch with
    assert own.build('master', CTX)[0] is None                           # nor without the clips of the weapons put away


def test_the_code_file_carries_own_states_and_their_setup():
    made, _ = own.build('cloud', CTX)
    made['table'] = states.table_text([], made['rows'])
    text, provides = code.source('Marth', None, None, None, None, None, made, 0x801364AC)
    c = text['fighter.c']
    assert provides[:2] == ["Climhazzard's dive", 'the Limit gauge: charge, and Finishing Touch when it is full']
    assert c.count('void OnLoad(GOBJ *gobj)') == 1 and '0x801364ac' in c and 'OwnLoad(fd);' in c       # the donor's own load first
    assert c.count('void OnFrame(GOBJ *gobj)') == 1 and 'OwnFrame(fd, gobj);' in c
    assert c.index('static void OwnFrame') < c.index('void OnFrame(GOBJ *gobj)') < c.index('move_logic[]')
    shot = {'joint': 75, 'flag': 1, 'onload': 0x801364AC, 'shots': [{'item': 0, 'states': (343,), 'pierce': False, 'rise': 5.7},
                                                                    {'item': 1, 'states': (347,), 'pierce': False}]}
    text, _ = code.source('Marth', None, shot, None, None, None, made, 0x801364AC)
    assert text['fighter.c'].count('void OnLoad(GOBJ *gobj)') == 1 and 'OwnLoad(fd);' in text['fighter.c']
    # a shot that stands on the ground runs along the floor and ends at a wall; any other ends at whatever it meets
    assert 'return (Item_CollAir_NoCB(item) & ~1) != 0;' in text['item_0.c']
    assert 'return (Item_CollAir_NoCB(item)) != 0;' in text['item_1.c']
    # a shot's model is turned to face the way it flies, when it is made and every frame after
    assert 'model->rot.Y = id->self_vel.X < 0 ? 3.14159265f : 0;' in text['item_0.c'] and '    Face(item);' in text['item_0.c']
    assert 'model->rot.Y = id->self_vel.X < 0 ? 3.14159265f : 0;' in text['fighter.c']


def test_the_next_jab_is_let_out_with_the_games_own_reading_of_its_command():
    items = combat.compile_move({'id': 'attack11', 'motions': ['Attack11'], 'total': 30, 'phases': [], 'jab_followup': 7})
    followup = [fields for code_, fields, _ in items if code_ == combat.command('enable_jab_followup')[0]]
    assert followup == [{'toggle': 0}]                                   # 1 reads "off unless an item is held"


def test_a_move_plays_to_its_end_after_the_frame_the_fighter_may_act():
    keys, acts = with_ending([[0, 0.0], [66, 66.0]], 78.0)
    assert keys == [[0, 0.0], [66, 66.0], [78, 78.0]] and acts == 67
    keys, acts = with_ending([[0, 0.0], [5, 6.0], [45, 46.0], [55, 66.0]], 88.0)        # the ending keeps the last speed: two source frames a frame
    assert keys[-1] == [66, 88.0] and acts == 56
    assert with_ending([[0, 0.0], [66, 66.0]], 66.0) == ([[0, 0.0], [66, 66.0]], None)   # nothing left to play


def test_keys_that_stop_short_of_the_frame_the_fighter_may_act_go_on_to_it():
    from fighter_port.oneshot import to_cancel
    # Incineroar's side special: may act from 58; 0.8 from 1, 1 from 9, 0.8 from 42, 1 from 66 (after it): the
    # reader's keys stop at 41, and from there the clip plays 1.25 frames of the clip a frame, to frame 57
    rates = [{'real': 1, 'rate': 0.8}, {'real': 9, 'rate': 1}, {'real': 42, 'rate': 0.8}, {'real': 66, 'rate': 1}]
    keys = [[0, 0.0], [8, 10.0], [41, 43.0]]
    assert to_cancel(keys, rates, 58, 80.0) == keys + [[57, 63.0]]
    assert to_cancel(keys, rates, 58, 50.0) == keys + [[47, 50.0]]          # the clip ends first: it ends there
    assert to_cancel([[0, 0.0], [57, 57.0]], rates, 58, 80.0) == [[0, 0.0], [57, 57.0]]     # already there


def test_a_landing_keeps_the_weapon_the_aerial_held():
    by_script = {'game_attackairf': 'spear', 'game_attackairlw': 'axe', 'game_specialnstart': 'bow'}
    assert weapon_for('game_landingairf', by_script) == 'spear' and weapon_for('game_landingairlw', by_script) == 'axe'
    assert weapon_for('game_landingairn', by_script) is None and weapon_for('game_specialn', by_script) == 'bow'


def test_the_donors_empty_third_jab_gets_a_clip_to_fill():
    zip_path = os.environ.get('PORT_DONOR_ZIP')
    if not zip_path or not Path(zip_path).exists() or not os.environ.get('NUCLEUS_REPO'):
        pytest.skip('needs PORT_DONOR_ZIP (a donor package exported from a project) and NUCLEUS_REPO')
    from vault.echo.subactions import FighterDat
    with zipfile.ZipFile(zip_path) as z:
        fj = json.loads(z.read('fighter.json'))
        pl, aj = z.read(fj['files']['fighterDataPath']), z.read(fj['files']['animFile'])
    follows, name = EXTRA_ACTION['attack13']
    made_pl, made_aj = add_action(pl, aj, follows, name)
    before, after = FighterDat(pl), FighterDat(made_pl)
    second = next(a for a in before.actions if a.motion == follows)
    third = after.actions[second.index + 1]
    assert before.actions[second.index + 1].symbol is None and third.motion == name and third.symbol.endswith(f'ACTION_{name}_figatree')
    assert third.anim_offset >= len(aj) and abs(third.anim_size - second.anim_size) < 64          # the same clip, written out again
    assert made_aj[:len(aj)] == aj and third.flags == second.flags
    assert [(a.motion, a.anim_offset) for a in after.actions if a.index != third.index] == \
           [(a.motion, a.anim_offset) for a in before.actions if a.index != third.index]
    assert add_action(made_pl, made_aj, follows, name) is None               # it has one now


def test_a_back_throw_turns_the_fighter_round_before_it_lets_go():
    hit = {'bone': 0, 'position': [0.0, 5.0, 5.0], 'radius': 4.0, 'damage': 3, 'angle': 45, 'kbg': 90, 'bkb': 0}
    throw = {'id': 'throwb', 'motions': ['ThrowB'], 'total': 31, 'turns': [15],
             'phases': [{'start': 13, 'end': 14, 'hitboxes': [dict(hit, grabbed_only=True)]}],
             'throw': {'damage': 3, 'angle': 38, 'kbg': 110, 'bkb': 48, 'release': 15}}
    items = combat.compile_move(throw)
    turn = combat.command('reverse_direction')[0]
    assert [fields['enabled'] for code_, fields, _ in items if code_ == turn] == [1, 0]      # the turn, then the release
    made = combat.command('create_hitbox')[0]
    held = next(fields for code_, fields, _ in items if code_ == made)
    assert held['only_hit_grabbed_fighter'] == 1 and held['clank'] == 0                     # for the held fighter only
    plain = dict(throw, turns=[])
    assert [fields['enabled'] for code_, fields, _ in combat.compile_move(plain) if code_ == turn] == [0]


def test_a_hit_for_airborne_targets_only_and_its_twin_for_standing_ones():
    hit = {'bone': 0, 'position': [0.0, 5.0, 5.0], 'radius': 4.0, 'damage': 14, 'kbg': 80, 'bkb': 20}
    move = {'id': 'attackairf', 'motions': ['AttackAirF'], 'total': 54, 'phases': [{'start': 18, 'end': 19, 'hitboxes': [
        dict(hit, angle=270, grounded=False), dict(hit, angle=60, aerial=False), dict(hit, angle=45)]}]}
    made = combat.command('create_hitbox')[0]
    hits = [fields for code_, fields, _ in combat.compile_move(move) if code_ == made]
    assert [(h['angle'], h['hit_grounded_fighters'], h['hit_aerial_fighters']) for h in hits] == [(270, 0, 1), (60, 1, 0), (45, 1, 1)]


def test_landing_lag_is_the_games_own_number():
    from fighter_port import oneshot
    assert oneshot.LANDING_TIMES == 1.0 and oneshot.LANDING['dair_landing_lag'] == 'landing_attack_air_frame_lw'


def test_a_late_hit_goes_on_from_the_hit_before_it():
    hit = {'bone': 0, 'position': [0.0, 5.0, 5.0], 'radius': 4.0, 'kbg': 80, 'bkb': 20, 'angle': 45}
    move = {'id': 'attackairf', 'motions': ['AttackAirF'], 'total': 54, 'phases': [
        {'start': 18, 'end': 19, 'hitboxes': [dict(hit, damage=14, slot=0), dict(hit, damage=13, slot=1)]},
        {'start': 20, 'end': 25, 'continues': True, 'hitboxes': [dict(hit, damage=11, slot=1)]},
        {'start': 30, 'end': 31, 'hitboxes': [dict(hit, damage=5, ignore_thrown=True)]}]}
    clear, remove, made, timer = (combat.command(k)[0] for k in ('clear_hitboxes', 'remove_hitbox', 'create_hitbox',
                                                               'asynchronous_timer'))
    seen, on = [], None
    for code_, fields, _ in combat.compile_move(move):
        if code_ == timer:
            on = fields['frame']
        elif code_ == clear:
            seen.append((on, 'clear'))
        elif code_ == remove:
            seen.append((on, 'remove', fields['index']))
        elif code_ == made:
            seen.append((on, 'hit', fields['id'], fields['damage'], fields.get('ignore_thrown_fighters', 0)))
    # the late hit: the hitbox that is gone is taken away, the other made again weaker, and nothing is cleared
    # between (a clear would let it strike a target the early hit has struck)
    assert seen == [(18, 'clear'), (18, 'hit', 0, 14, 0), (18, 'hit', 1, 13, 0), (20, 'remove', 0), (20, 'hit', 1, 11, 0),
                    (26, 'clear'), (30, 'clear'), (30, 'hit', 0, 5, 1), (32, 'clear')]
    with pytest.raises(ValueError):                     # a stretch that goes on must follow the one before at once
        combat.compile_move(dict(move, phases=[move['phases'][0], dict(move['phases'][1], start=22)]))


def test_a_moves_hitboxes_are_cut_where_they_change():
    from fighter_port.oneshot import stretches
    box = lambda i, first, last, run, **more: dict({'id': i, 'first': first, 'last': last, 'run': run, 'damage': 1.0}, **more)
    # a forward air: two hitboxes, one of them made again weaker for the late hit while it is still out
    fair = [box(0, 18, 19, 1), box(3, 18, 19, 1), box(3, 20, 25, 1)]
    assert [(a, b, [h['id'] for h in hs], goes_on) for a, b, hs, goes_on in stretches(fair, 54)] == [
        (18, 19, [0, 3], False), (20, 25, [3], True)]
    # a hitbox that stays out while two more join it is still out on the stretch they start
    dash = [box(0, 9, 11, 1), box(3, 10, 11, 1), box(4, 10, 11, 1)]
    assert [(a, b, [h['id'] for h in hs], goes_on) for a, b, hs, goes_on in stretches(dash, 45)] == [
        (9, 9, [0], False), (10, 11, [0, 3, 4], True)]
    # all cleared between two swings: the second is an attack of its own; a hitbox never cleared lasts to the end
    two = [box(0, 8, 9, 1), box(0, 21, None, 2)]
    assert [(a, b, goes_on) for a, b, _, goes_on in stretches(two, 30)] == [(8, 9, False), (21, 30, False)]
    # a re-hit timer: the hitbox strikes again every seven frames, and the hit that ends the move goes on from it
    spin = [box(0, 6, 26, 1, rehit=7), box(0, 27, 28, 1)]
    assert [(a, b, goes_on) for a, b, _, goes_on in stretches(spin, 52)] == [
        (6, 12, False), (13, 19, False), (20, 26, False), (27, 28, True)]


def test_a_hitbox_made_again_in_another_group_may_strike_again():
    hit = {'bone': 0, 'position': [0.0, 5.0, 5.0], 'radius': 4.0, 'kbg': 80, 'bkb': 20, 'angle': 88}
    move = {'id': 'specialhi', 'motions': ['SpecialHi'], 'total': 24, 'phases': [
        {'start': 7, 'end': 9, 'hitboxes': [dict(hit, damage=6, slot=0)]},
        {'start': 10, 'end': 16, 'continues': True, 'hitboxes': [dict(hit, damage=7, slot=0, group=1)]}]}
    made, clear = combat.command('create_hitbox')[0], combat.command('clear_hitboxes')[0]
    items = combat.compile_move(move)
    assert [(fields['damage'], fields['hit_group']) for code_, fields, _ in items if code_ == made] == [(6, 0), (7, 1)]
    assert sum(1 for code_, _, _ in items if code_ == clear) == 2          # at its start and at its end, not between


def test_a_move_the_game_makes_untouchable_stays_so():
    hit = {'bone': 0, 'position': [0.0, 5.0, 5.0], 'radius': 4.0, 'damage': 10, 'kbg': 80, 'bkb': 20, 'angle': 45}
    move = {'id': 'cliffattack', 'motions': ['CliffAttackQuick'], 'total': 55, 'intangible': [1, 23],
            'phases': [{'start': 20, 'end': 22, 'hitboxes': [hit]}]}
    state, timer = combat.command('set_body_collision_state')[0], combat.command('asynchronous_timer')[0]
    seen, on = [], None
    for code_, fields, _ in combat.compile_move(move):
        if code_ == timer:
            on = fields['frame']
        elif code_ == state:
            seen.append((on, fields['body_state']))
    assert seen == [(1, 2), (24, 0)]                    # untouchable from the first frame through the 23rd
    with pytest.raises(ValueError):
        combat.compile_move(dict(move, intangible=[30, 20]))


def test_a_hitbox_drawn_out_along_a_line_is_several_balls():
    from fighter_port.oneshot import ball_points, balls, stretch_of
    lance = {'x': 0.0, 'y': 9.5, 'z': -17.0, 'x2': 0.0, 'y2': 9.5, 'z2': -25.0, 'size': 3.0}
    assert stretch_of(lance) == 8.0 and stretch_of({'x': 0.0, 'y': 1.0, 'z': 2.0, 'x2': None, 'size': 3.0}) == 0.0
    # one ball: a quarter of the line wider, set so its far end (the tip, further from the bone) is the game's
    assert ball_points(lance, 1) == [([0.0, 9.5, -23.0], 5.0)]
    # two: an eighth of the line wider, the first again reaching exactly as far as the game's tip
    assert ball_points(lance, 2) == [([0.0, 9.5, -24.0], 4.0), ([0.0, 9.5, -20.0], 4.0)]
    # the far end is the far end whichever way round the game wrote the line
    turned = dict(lance, z=-25.0, z2=-17.0)
    assert ball_points(turned, 1) == ball_points(lance, 1)
    assert ball_points({'x': 1.0, 'y': 2.0, 'z': 3.0, 'x2': None, 'y2': None, 'z2': None, 'size': 4.0}, 1) == [([1.0, 2.0, 3.0], 4.0)]
    # Melee's four balls: one to each hitbox, the rest to whichever is drawn out furthest
    assert balls([0.0, 8.0]) == [1, 3] and balls([0.0, 0.0, 0.0, 9.0]) == [1, 1, 1, 1]
    assert balls([0.0]) == [1] and balls([6.0, 6.0]) == [2, 2] and balls([0.5, 0.0]) == [1, 1]


def test_a_hit_carries_its_sound_what_it_does_to_a_shield_and_whether_it_can_be_met():
    hit = {'bone': 0, 'position': [0.0, 5.0, 5.0], 'radius': 4.0, 'damage': 10, 'kbg': 80, 'bkb': 20, 'angle': 45}
    move = {'id': 'attacklw4', 'motions': ['AttackLw4'], 'total': 40, 'phases': [{'start': 10, 'end': 12, 'hitboxes': [
        dict(hit, sound_level=0, sound_kind=2, shield_damage=8, clank=False), hit]}]}
    made = combat.command('create_hitbox')[0]
    first, second = [fields for code_, fields, _ in combat.compile_move(move) if code_ == made]
    assert (first['hit_sfx_severity'], first['hit_sfx_kind'], first['shield_damage'], first['clank'], first['rebound']) == (0, 2, 8, 0, 0)
    # said nothing: a hard hit of a blade that other attacks can meet, as before
    assert (second['hit_sfx_severity'], second['hit_sfx_kind'], second['shield_damage'], second['clank'], second['rebound']) == (2, 3, 0, 1, 1)
    with pytest.raises(ValueError):
        combat.compile_move(dict(move, phases=[{'start': 10, 'end': 12, 'hitboxes': [dict(hit, sound_level=5)]}]))


def test_jumps_reach_the_games_heights_under_the_fighters_own_gravity():
    from fighter_port.oneshot import attribute_ops, rise_speed
    assert abs(rise_speed(30.6, 0.098) - 2.4) < 0.01            # measured in game: 2.4 under 0.098 rises 30.6
    game = {'attributes': {'air_accel_y': 0.098, 'jump_y': 32.5, 'mini_jump_y': 17.0, 'jump_aerial_y': 32.5,
                           'jump_speed_x': 0.95, 'jump_speed_x_mul': 0.9, 'jump_speed_x_max': 1.2}}
    got = {op['name']: op['value'] for op in attribute_ops(game)[0]}

    def rises(v, g=0.098):
        h = 0.0
        while v > 0:
            h, v = h + v, v - g
        return h
    assert abs(rises(got['initial_vertical_jump_velocity']) - 32.5) < 0.2
    assert abs(rises(got['max_shorthop_vertical_velocity']) - 17.0) < 0.2
    assert abs(got['vertical_air_jump_multiplier'] - 1.0) < 1e-6
    assert (got['initial_horizontal_jump_velocity'], got['ground_to_air_jump_momentum_multiplier'],
            got['max_shorthop_horizontal_velocity']) == (0.95, 0.9, 1.2)


def test_a_row_of_like_hitboxes_is_one_when_there_are_too_many():
    from fighter_port.oneshot import joined, stretch_of
    ball = lambda i, y, damage, size=2.4, **more: dict({'id': i, 'bone': 'haver', 'x': -0.5, 'y': y, 'z': -0.5, 'x2': None, 'y2': None,
                                                         'z2': None, 'size': size, 'damage': damage, 'angle': 48, 'kbg': 80, 'bkb': 30}, **more)
    # a lance: three balls along its shaft, two at its tip, and two more hitboxes: seven where Melee holds four
    lance = [ball(0, 4.0, 8.5, 3.0), ball(1, 9.2, 8.5), ball(2, 13.5, 8.5), ball(3, 19.0, 12.75, 3.4), ball(4, 25.0, 12.75, 3.0),
             ball(5, 5.0, 8.5, bone='top'), ball(6, 16.5, 12.75, bone='top')]
    got = sorted(joined(lance), key=lambda h: h['id'])
    assert [h['id'] for h in got] == [0, 3, 5, 6]
    assert (got[0]['y'], got[0]['y2'], got[0]['size'], stretch_of(got[0])) == (4.0, 13.5, 3.0, 9.5)     # the shaft, as one line
    assert (got[1]['y'], got[1]['y2'], got[1]['size']) == (19.0, 25.0, 3.4)                             # the tip
    # few enough: left as they are
    assert joined(lance[:4]) == lance[:4]
    # like hitboxes that do not touch (one each side of the fighter) are not a row
    sides = [ball(i, y, 10.0) for i, y in enumerate((-12.0, 12.0))] + [ball(i + 2, 0.0, d, bone='top') for i, d in enumerate((1, 2, 3))]
    assert len(joined(sides)) == 5


def test_what_a_fighters_own_parameter_file_says():
    from fighter_port.oneshot import own_parameters
    table = [{'a': 0.0, 'mul': m, 'b': 1.0, 'c': 1.0, 'what': n, 'z': '0x0000000000'}
             for n, m in (('walk_speed_max', 1.15), ('ground_brake', 1.15), ('dash_speed', 1.1), ('run_speed_max', 1.1),
                          ('air_speed_x_stable', 1.2), ('air_accel_y', 1.1), ('walk_accel_mul', 1.15))]
    root = {'param_special_hi': [{'start_speed_y_air': 1.4, 'other': 3.0}, {'start_speed_y_air': 0.0}],
            'param_special_lw': [{'start_speed_y_air': 0.0}], '0x14651c2316': table,
            'param_private': {'x': 1.0}}
    start, boost = own_parameters(root)
    assert start == {'hi': 1.4}                                         # nothing said of a special that starts with none
    assert boost == {'walk_maximum_velocity': 1.15, 'ground_friction': 1.15, 'dash_initial_velocity': 1.1,
                     'dashrun_terminal_velocity': 1.1, 'aerial_drift_max': 1.2, 'gravity': 1.1}
    # a table with two columns that vary is not read as one
    two = [dict(r, b=1.0 + i * 0.1) for i, r in enumerate(table)]
    assert own_parameters({'t': two})[1] == {}


def test_clouds_gauge_fills_by_damage_dealt_runs_out_and_changes_his_numbers():
    made, _ = own.build('cloud', dict(CTX, boost={'gravity': 1.1, 'dash_initial_velocity': 1.1}, limit_hold=900))
    c = '\n'.join(made['source'])
    assert '#define LIMIT_PER_DEALT (1.0f / 150.0f)' in c and '#define LIMIT_HOLD 900' in c
    assert 'od->dmg.source_ply == p' in c and 'if (--limit_left[p] <= 0)' in c
    assert 'if (pass == 2 && aura[p] == 2)' in c and '#define OVER_Y (AURA_TALL - 1.5f)' in c      # over his head while he charges
    assert 'plain[fd->ply][0] = fd->attr.dash_initial_velocity;' in c
    assert 'fd->attr.gravity = plain[p][1] * (on ? 1.1f : 1.0f);' in c and 'Boost(fd, limit[p] >= 1.0f);' in c
    plain, _ = own.build('cloud', CTX)                                   # a file that names no such table: nothing changes
    assert 'fd->attr.' not in '\n'.join(plain['source']).split('static void Boost')[1].split('}')[1]


# ------------------------------------------------------------------------- common actions
GAME = {'motion_params': {'escape_n_cancel_frame': 26.0, 'escape_n_hit_xlu_frame': 3.0, 'escape_n_hit_normal_frame': 15.0,
                          'escape_f_cancel_frame': 30.0, 'escape_f_hit_xlu_frame': 4.0, 'escape_f_hit_normal_frame': 12.0,
                          'escape_air_cancel_frame': 50.0, 'escape_air_hit_xlu_frame': 3.0, 'escape_air_hit_normal_frame': 28.0,
                          'guard_off_cancel_frame': 11},
        'motions': {'f05passive': {'game': 'game_passive', 'cancel_frame': 27, 'intangible': [1, 21]},
                    'b02escapen': {'game': 'game_escapen', 'cancel_frame': 27, 'intangible': None},
                    'c05landingairn': {'game': 'game_landingairn', 'cancel_frame': 20, 'intangible': None}}}


def test_a_common_action_ends_and_is_untouchable_on_the_games_frames():
    from fighter_port.oneshot import shared_end, shared_untouchable
    # a dodge: the fighter's row of the dodge table, not the motion list (which says 27 here)
    assert shared_end(GAME, 'b02escapen', 'EscapeN') == 26 and shared_untouchable(GAME, 'b02escapen', 'EscapeN') == [3, 18]
    assert shared_end(GAME, 'b02escapef', 'EscapeF') == 30 and shared_untouchable(GAME, 'b02escapef', 'EscapeF') == [4, 16]
    # a shield drop: the table every fighter shares; a tech: the motion list
    assert shared_end(GAME, 'b00guardoff', 'GuardOff') == 11
    assert shared_end(GAME, 'f05passive', 'Passive') == 27 and shared_untouchable(GAME, 'f05passive', 'Passive') == [1, 21]
    # the engine ends a landing by its own numbers, and a fighter that was hit reels as long as the hit says
    assert shared_end(GAME, 'c05landingairn', 'LandingAirN') is None
    assert shared_end(dict(GAME, motions={'f00damagehi1': {'cancel_frame': 9, 'intangible': None}}), 'f00damagehi1', 'DamageHi1') is None
    # an air dodge: the fighter's own number where it has one (a fighter whose row says -1 plays its clip out)
    assert shared_end(GAME, 'b02escapeair', 'EscapeAir') == 50 and shared_untouchable(GAME, 'b02escapeair', 'EscapeAir') == [3, 31]
    assert shared_end({'motion_params': {'escape_air_cancel_frame': -1.0}}, 'b02escapeair', 'EscapeAir') is None
    assert shared_end({}, 'x', 'Passive') is None and shared_untouchable({}, 'x', 'Passive') is None


def test_a_donors_script_keeps_all_but_its_untouchable_frames():
    from fighter_port.oneshot import absolute, untouchable
    sound = (17, {'sfx_id': 2}, None)
    donor = [sound, (2, {'frame': 2}, None), (26, {'body_state': 2}, None), (1, {'frame': 17}, None),
             (26, {'body_state': 0}, None), (2, {'frame': 25}, None), (23, {}, None)]
    assert absolute(donor)[0] == [(0, sound), (2, donor[2]), (19, donor[4]), (25, donor[6])]       # "wait 17" from 2 is 19
    new = untouchable(donor, 3, 18)
    assert [(f, i[0], i[1].get('body_state')) for f, i in absolute(new)[0]] == [
        (0, 17, None), (3, 26, 2), (18, 26, 0), (25, 23, None)]
    # from the first frame: at the script's start
    assert absolute(untouchable(donor, 1, 21))[0][0][1][1] == {'body_state': 2}
    assert untouchable([(3, {}, None), sound], 3, 18) is None                                      # a script that loops is left alone


def test_a_grab_reaches_where_and_when_the_games_does():
    from fighter_port.oneshot import absolute, grab_boxes, regrab
    move = {'other': [{'cmd': 'CATCH', 'real': 9, 'args': [0, 'top', 3.3, 0.0, 6.6, 4.0, 0.0, 6.6, 8.7, 1, '<const 0xe7c4>']},
                      {'cmd': 'CATCH', 'real': 9, 'args': [1, 'top', 1.65, 0.0, 6.6, 2.35, 0.0, 6.6, 10.35, 1, '<const 0xe7c8>']}],
            'catch_end': 11}
    first, end, boxes = grab_boxes(move, 1.0)
    assert (first, end, len(boxes)) == (9, 11, 4)
    assert [b['targets'] for b in boxes] == ['ground', 'ground', 'air', 'air']                     # Melee's four balls, shared between the two
    assert max(b['position'][2] + b['radius'] for b in boxes if b['targets'] == 'ground') == pytest.approx(8.7 + 3.3)
    assert max(b['position'][2] + b['radius'] for b in boxes if b['targets'] == 'air') == pytest.approx(10.35 + 1.65)
    box = lambda i, x: (11, {'id': i, 'bone': 0, 'damage': 0, 'size': 1000, 'z_offset': 0, 'y_offset': 2000, 'x_offset': x,
                             'angle': 361, 'knockback_growth': 100, 'weight_set_knockback': 0, 'base_knockback': 0, 'element': 8,
                             'hit_grounded_fighters': 1, 'hit_aerial_fighters': 1, 'clank': 1, 'rebound': 0, 'hit_group': 0,
                             'only_hit_grabbed_fighter': 0, 'use_common_bone_ids': 0, 'item_hit_interaction': 1,
                             'ignore_thrown_fighters': 0, 'ignore_fighter_scale': 0, 'shield_damage': 0, 'hit_sfx_severity': 1,
                             'hit_sfx_kind': 2}, None)
    donor = [(2, {'frame': 6}, None), (17, {'behavior': 0, 'unknown': 0, 'sfx_id': 527, 'padding': 0, 'volume': 90, 'panning': 64}, None),
             box(0, 3300), box(1, 2500), box(2, 1800), (1, {'frame': 2}, None), (16, {'_pad': 0}, None)]
    items, told = regrab(donor, move, 1.0)
    events = absolute(items)[0]
    made = [(f, i[1]) for f, i in events if i[0] == 11]
    assert told == {'first': 9, 'end': 11, 'boxes': 4}
    # made a frame before the game's first grabbing frame (a grab box takes hold the frame after), gone a frame before its end
    assert {f for f, _ in made} == {8} and [f for f, i in events if i[0] == 16] == [10] and [f for f, i in events if i[0] == 17] == [8]
    assert [(b['hit_grounded_fighters'], b['hit_aerial_fighters']) for _, b in made] == [(1, 0), (1, 0), (0, 1), (0, 1)]
    assert all(b['element'] == 8 and b['y_offset'] == round(6.6 * 256) for _, b in made)
    assert regrab([(2, {'frame': 6}, None), (16, {'_pad': 0}, None)], move, 1.0) is None            # a script with no grab box


def test_the_fighters_other_numbers_are_its_own_too():
    """Steering in the air is two numbers (the stick's part and a flat part), a walk's start is two, and what
    stops a fighter on the ground and in the air are the game's; the shield is the game's radius, divided by the
    scale the engine multiplies it by."""
    from fighter_port.oneshot import attribute_ops
    game = {'attributes': {'air_accel_x_mul': 0.07, 'air_accel_x_add': 0.01, 'air_brake_x': 0.015, 'ground_brake': 0.09,
                           'walk_accel_mul': 0.105, 'walk_accel_add': 0.105, 'jump_count_max': 2,
                           'jump_aerial_speed_x_mul': 0.9, 'throw_item_speed_mul': 0.95, 'throw_item_power_mul': 1.0,
                           'shield_radius': 9.7}}
    ops, notes = attribute_ops(game, 0.97, 0.97)
    got = {op['name']: op['value'] for op in ops}
    assert (got['aerial_speed'], got['aerial_friction'], got['air_friction']) == (0.07, 0.01, 0.015)
    assert (got['friction'], got['initial_walk_speed'], got['walk_acceleration']) == (0.09, 0.105, 0.105)
    assert (got['number_of_jumps'], got['horizontal_air_jump_multiplier']) == (2.0, 0.9)
    assert abs(got['shield_size'] - 9.7) < 1e-6
    # a model drawn at the donor's scale: the engine multiplies the number by that scale itself
    assert abs({op['name']: op['value'] for op in attribute_ops(game, 0.97, 1.08)[0]}['shield_size'] - 9.7 * 0.97 / 1.08) < 1e-6
    ops, notes = attribute_ops(game)
    assert 'shield_size' not in {op['name'] for op in ops} and any('shield_size' in n for n in notes)


def test_module_input_wrappers_preserve_donor_callbacks_and_install_on_both_forms():
    rows = {m: {'iasa': 0x80136100 + i} for i,m in enumerate(CTX['state'])}
    made,_ = own.build('cloud', dict(CTX,row=rows))
    c='\n'.join(made['source'])
    assert set(made['donor_iasa']) == {'SpecialHi','SpecialAirHi'}
    assert '((void (*)(GOBJ *))0x80136100)(gobj);' in c
    assert '((void (*)(GOBJ *))0x80136101)(gobj);' in c
    donor=[dict(iasa=1),dict(iasa=2)]
    states.apply_iasa(donor,{'SpecialHi':341,'SpecialAirHi':342},made['donor_iasa'])
    assert [r['iasa'] for r in donor] == ['OwnInput_SpecialHi','OwnInput_SpecialAirHi']
    assert rows['SpecialHi']['iasa']==0x80136100  # constructing wrappers does not mutate context
    with pytest.raises(ValueError,match='missing donor state'):
        states.apply_iasa(donor,{},made['donor_iasa'])


def test_common_attack_rows_keep_the_original_state_and_move_identity():
    rows = [struct.pack('>iIBB2x5I',i+2,0x240609,10,128,0x8008C520,0,0x8008C7F0,0x8008C810,0x800761C8)
            for i in range(states.FIRST_SPECIAL_STATE)]
    got = states.common_by_motion(dol(states.COMMON_STATE_TABLE,b''.join(rows)),{'AttackS4S':62,'Missing':900})
    assert set(got)=={'AttackS4S'}
    assert got['AttackS4S']['state']==60 and got['AttackS4S']['move']==10
    assert got['AttackS4S']['flags']==0x240609 and got['AttackS4S']['bits']==128
