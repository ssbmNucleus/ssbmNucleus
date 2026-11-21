"""One pass from an Ultimate fighter to a Melee roster character on a donor's skeleton.

    python -m fighter_port.oneshot master --name Byleth --donor Marth \
        --root <dump folder> --body <costume.dat> --donor-zip <Marth.zip> --work <dir>

No hand tuning: every choice below is a rule applied to the game's own data, so
what comes out wrong points at a rule to fix, not at a number to nudge.

Stages (each keeps its output under --work and is skipped when it is there):

  spec      which Ultimate clip goes on which donor action, timed from game data
  clips     decode each clip and carry it onto the donor's bones (moveset.compile_set)
  install   put the clips in the donor's animation bank and fighter data
  scripts   hitboxes, throws and attack flags from the game's move scripts
  values    attributes copied from the game's table
  package   five costumes, portraits and icons around the new data: a fighter zip

The body (a costume DAT already fitted to the donor) comes from outside; the app's
model importer makes one from any model file.

With `--own <folder>` the fighter keeps its OWN skeleton instead (a body no donor's bones fit): the same rules,
its clips copied onto its own joints and its hitboxes on the bones its scripts name. That route is own_route.py.

The clip-to-action table is the one written for Shulk (echo_tier2_shulk): the
file names are the same for every Ultimate fighter. Specials are the donor's own
states with whichever of the fighter's special clips fit them; see special_rows.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import nucleus_root  # noqa: E402
from fighter_port.combat_values import shield_field

for _p in (str(nucleus_root.BACKEND), str(nucleus_root.BACKEND.parents[1])):
    if _p not in sys.path:
        sys.path.insert(1, _p)

RECIPES = HERE / 'echo_tier2_shulk'

# A start clip that holds both the draw and the whole charge: the source frames of the draw and of a
# 30-frame stretch of the hold. (Per fighter: the game keeps where the charge begins in code.)
CHARGE_CUT = {'master': ((0, 44), (45, 75))}
# How long the donor's start and charge states are passed through by a neutral special that is one clip.
THROUGH = 2


def special_rows(donor, fighter, names, moves):
    """Which of the fighter's special clips go on which of the donor's special actions, by the shape of the
    fighter's own specials. A donor's special logic is not replaced, so this only chooses what is shown and
    where the hitboxes come from. `names` are the fighter's clip names (specialn, specialairs2, ...).
    -> ({clip name: target action | (action, (first, last)) | {...} | [several]}, what was chosen)

    For Marth (start / charge loop / release; a chain of up to four swings; one up special; a counter):
      neutral  a start clip and a release clip: the start clip is cut into draw and charge (Byleth's bow).
               One clip: the donor's start and charge are passed through in a frame each and the whole clip
               plays on the release (Cloud's Blade Beam); the driver sets the donor's charge to no loops.
      side     clips numbered 1, 2, 3(, 4): the donor's chain, each hit on every direction of its step
               (Cloud's Cross Slash). A start clip and a forward swing: joined on the first step (Byleth).
      up, down the clip the game's own script for that input plays."""
    if donor != 'Marth':
        return {}, {}
    rows, chosen = {}, {}

    def played(script):
        anim = (moves.get('game_' + script) or {}).get('animation')
        for c in ([anim[3:-len('.nuanmb')]] if anim else []) + [script, script + '1']:
            if c in names:
                return c
        return None

    for air, A in (('', ''), ('air', 'Air')):
        n, start = f'special{air}n', f'special{air}nstart'
        if start in names and f'special{air}nloop' in names and f'special{air}nend' in names:
            # the donor's own shape (a start, a charge that loops, a release): each on its own
            rows[start], rows[f'special{air}nloop'], rows[f'special{air}nend'] = (
                f'Special{A}NStart', f'Special{A}NLoop', f'Special{A}NEnd')
            chosen[f'{air}neutral'] = 'same'
        elif start in names and n in names:
            cut = CHARGE_CUT.get(fighter)
            rows[start] = [(f'Special{A}NStart', cut[0]), (f'Special{A}NLoop', cut[1])] if cut else f'Special{A}NStart'
            rows[n] = f'Special{A}NEnd'
            chosen[f'{air}neutral'] = 'charge'
        elif played(n):
            rows[played(n)] = [(f'Special{A}NStart', (0, 1)), (f'Special{A}NLoop', (1, 2)),
                               {'motion': f'Special{A}NEnd', 'from': THROUGH}]
            chosen[f'{air}neutral'] = 'through'
        s = [f'special{air}s{k}' for k in (1, 2, 3, 4)]
        if s[0] in names and s[1] in names:
            steps = [[f'Special{A}S1'], [f'Special{A}S2Hi', f'Special{A}S2Lw'],
                     [f'Special{A}S3Hi', f'Special{A}S3S', f'Special{A}S3Lw'],
                     [f'Special{A}S4Hi', f'Special{A}S4S', f'Special{A}S4Lw']]
            have = [c for c in s if c in names]
            have = have[:next((i for i, c in enumerate(s) if c not in names), len(s))]      # no gaps
            for clip, targets in zip(have, steps):
                rows[clip] = list(targets)
            chosen[f'{air}side'] = {'chain': [(clip, targets) for clip, targets in zip(have, steps)]}
        elif f'special{air}sstart' in names and f'special{air}sf' in names:
            rows[f'special{air}sstart'] = {'motion': f'Special{A}S1', 'then': [f'special{air}sf']}
            chosen[f'{air}side'] = 'joined'
        elif f'specials{air}start' in names and f'specials{air}dash' in names and f'specials{air}attack' in names:
            # a start, a dash and a swing at the end of it (the charge between them is the game's code): one after
            # another on the first step
            rows[f'specials{air}start'] = {'motion': f'Special{A}S1', 'then': [f'specials{air}dash', f'specials{air}attack']}
            chosen[f'{air}side'] = 'joined'
        elif played(f'special{air}s'):
            rows[played(f'special{air}s')] = f'Special{A}S1'
            chosen[f'{air}side'] = 'one'
        for key, target in ((f'special{air}hi', f'Special{A}Hi'), (f'special{air}lw', f'Special{A}Lw')):
            if played(key):
                rows[played(key)] = target
    return rows, chosen


def with_own(specials, own):
    """The special rows with the clips of the port's own states added. A clip both name goes on both actions (the
    donor's state shows it for the frame before the port's own state takes over)."""
    for clip, row in own.items():
        if clip in specials and specials[clip] != row:
            before = specials[clip]
            specials[clip] = (list(before) if isinstance(before, list) else [before]) + [row]
        else:
            specials[clip] = row
    return specials


def clip_names(root, fighter):
    motion = Path(root) / 'gamedata' / 'fighter' / fighter / 'motion' / 'body' / 'c00'
    return {p.stem[3:] for p in motion.glob('*.nuanmb')}


def leaves_ground(S, anim_path, keys, total):
    """The clip frame on which a clip's own root starts to rise, or None when it never does
    (the game then moves the fighter in code this reader does not read)."""
    track = next((n.tracks[0].values for g in S.anim_data.read_anim(str(anim_path)).groups
                  if 'Transform' in str(g.group_type) for n in g.nodes if n.name == 'Trans'), None)
    if not track or len(track) < 2:
        return None
    first = next((i for i, v in enumerate(track) if v.translation[1] > 0.01), None)
    if first is None:
        return None
    return next((f for f in range(int(total) + 1) if source_time(keys, f) >= first), None)


def clip_travel(S, anim_path, keys=None):
    """How far a clip's own root goes within the stretch the port plays (`keys`: its time keys), in the
    game's units: (furthest forward or back, where it ends, furthest up or down, where it ends)."""
    import numpy as np
    track = next((n.tracks[0].values for g in S.anim_data.read_anim(str(anim_path)).groups
                  if 'Transform' in str(g.group_type) for n in g.nodes if n.name == 'Trans'), None)
    if not track or len(track) < 2:
        return None
    t = np.array([v.translation for v in track], float)
    first = int(min(len(t) - 1, max(0, keys[0][1]))) if keys else 0
    last = int(min(len(t) - 1, keys[-1][1])) if keys else len(t) - 1
    seg = t[first:max(last, first) + 1] - t[first]
    return (float(np.abs(seg[:, 2]).max()), float(seg[-1, 2]), float(np.abs(seg[:, 1]).max()), float(seg[-1, 1]))


def travel_route(target, category, donor, flagged):
    """How a clip's travel on this donor action reaches the fighter: 'state' (the action's own physics
    reads it), 'code' (a ground state that only slows the fighter: the port's code file moves it), or
    None (nothing reads it: it stays in the picture). `flagged`: the donor actions that move by their own clip."""
    if donor not in TRAVEL_ROOT or category == 'locomotion':
        return None                                     # walking and running go by the fighter's speeds
    if target in flagged or any(target.startswith(n) for n in READS_TRAVEL):
        return 'state'
    if any(target.startswith(n) for n in FRICTION_ONLY + FRICTION_ONLY_DONOR.get(donor, ())):
        return 'code'
    return None


def add_action(pl: bytes, aj: bytes, follows: str, name: str):
    """The donor's data file and animation bank with the empty action after `follows` given a clip of
    its own: a copy of `follows`'s under the action name `name`, to be replaced like any other clip.
    -> (pl, aj), or None when the donor has no empty action there."""
    from vault.echo import datroot
    from vault.echo.subactions import ACTION_SIZE, FighterDat
    fd = FighterDat(pl)
    src = next((x for x in fd.actions if x.motion == follows and x.symbol and x.anim_size), None)
    if src is None or src.index + 1 >= len(fd.actions):
        return None
    dst = fd.actions[src.index + 1]
    if dst.symbol or dst.anim_size:
        return None
    symbol = src.symbol.replace(follows, name)
    data, relocs, roots, xrefs = datroot.parse(aj[src.anim_offset:src.anim_offset + src.anim_size])
    clip = datroot.build(data, relocs, [(roots[0][0], symbol)], xrefs)
    at = len(aj) + (-len(aj) % 0x20)
    aj = aj + bytes([0xFF]) * (at - len(aj)) + clip + bytes([0xFF]) * (-len(clip) % 0x20)
    d, entry = fd.dat, fd.action_table[0] + dst.index * ACTION_SIZE
    text = d.append_struct(symbol.encode('ascii') + bytes(1), align=4)
    d.set_u32(entry, text)
    d.add_reloc(entry)
    d.set_u32(entry + 0x04, at)
    d.set_u32(entry + 0x08, len(clip))
    d.set_u32(entry + 0x10, src.flags)
    d.set_u32(entry + 0x14, src.flags2)
    return d.to_bytes(), aj


def with_ending(keys, length):
    """Time keys that stop on the frame before the fighter may act, carried on to the end of the clip
    (`length`: its last source frame) at the speed it was playing. -> (keys, the frame it may act on),
    or (keys as given, None) when the clip has nothing left to play."""
    (f0, t0), (f1, t1) = keys[-2:]
    if length <= t1 + 0.5:
        return keys, None
    rate = (t1 - t0) / (f1 - f0) if f1 > f0 and t1 > t0 else 1.0
    return [list(k) for k in keys] + [[int(f1 + max(1, round((length - t1) / rate))), float(length)]], int(f1) + 1


def chain_window(move, total):
    """The frames a chained special takes its next input on: from the last flag the game's script raises
    after its first hit to the last flag it lowers (the end of the clip when it lowers none)."""
    hits = [h['first'] for h in move.get('hitboxes') or [] if isinstance(h.get('first'), int)]
    first = min(hits) if hits else 1
    on = [f['real'] for f in move.get('flags') or [] if f['cmd'] == 'on_flag' and f['real'] > first]
    off = [f['real'] for f in move.get('flags') or [] if f['cmd'] == 'off_flag']
    if not on:
        return None
    open_, close = max(on), max([f for f in off if f > max(on)] or [total - 1])
    return (int(open_), int(min(close, total - 1))) if open_ < total - 1 else None

def alternates(game, table):
    """Second versions of carried specials (a stronger one the fighter's own code picks, like a move with a
    full gauge): a script whose name did not resolve, with hits or a shot of its own, that plays the clip a
    named special's script plays. `table`: {clip: rows} as carried. -> {donor action: script}, one action a
    script: the first the clip is on, or the stretch of a cut clip that holds its first hit or shot."""
    moves, out = game['moves'], {}
    for script, m in sorted(moves.items()):
        anim = m.get('animation')
        events = ([h['first'] for h in m.get('hitboxes') or [] if isinstance(h.get('first'), int) and h.get('damage') != 0]
                  + [f for f in m.get('article_frames') or [] if f])
        if script.startswith('game_') or not anim or not events:
            continue
        stem = anim[:-len('.nuanmb')]
        named = script_for(stem, moves)
        if stem not in table or named == script or not named.startswith('game_special'):
            continue
        what = lambda mv: (sorted((h.get('first'), h.get('last'), h.get('damage'), h.get('angle'), h.get('kbg'), h.get('fkb'), h.get('bkb'))
                                  for h in mv.get('hitboxes') or []), [f for f in mv.get('article_frames') or [] if f])
        if what(m) == what(moves[named]):
            continue                                    # the same hits under another name: not another version
        rows = table[stem]
        holds = [r for r in rows if not r.get('window') or
                 (r['window'][0] <= min(events) and (r['window'][1] is None or min(events) <= r['window'][1]))]
        target = (holds or rows)[0]['target_motion']
        if target not in out:
            out[target] = script
    return out


def frame_at(keys, time):
    """The clip frame on which Ultimate animation time `time` is shown: `source_time` the other way."""
    import math
    if not keys:
        return int(math.floor(time + 0.5))
    for (f0, t0), (f1, t1) in zip(keys, keys[1:]):
        if time <= t1:
            return int(math.floor(f0 + (f1 - f0) * (time - t0) / (t1 - t0) + 0.5)) if t1 > t0 else int(f1)
    return int(keys[-1][0])


def script_time(keys, frame):
    """Ultimate animation time on frame `frame` of a script with these time keys. Unlike a carried clip's
    keys, a script's may stop before its last frame: past them it plays on frame for frame."""
    if not keys:
        return float(frame)
    if frame > keys[-1][0]:
        return float(keys[-1][1]) + (frame - keys[-1][0])
    return source_time(keys, frame)


def relative_rate(own_keys, clip_keys):
    """How much faster a second version of a move plays its clip than the version the clip was carried
    for, when that is one number for the whole clip (1.0 when it is not: its frames are still converted)."""
    def rate(keys):
        if not keys or len(keys) != 2 or keys[1][0] <= keys[0][0]:
            return None
        return (keys[1][1] - keys[0][1]) / (keys[1][0] - keys[0][0])
    a, b = rate(own_keys), rate(clip_keys)
    return a / b if a and b else 1.0


def timed(items):
    """[(frame, command)] of a script written here (it waits with "until frame N" timers only)."""
    frame, out = 0, []
    for item in items:
        if item[0] == 2:
            frame = item[1]['frame']
        elif item[0] == 0:
            break
        else:
            out.append((frame, item))
    return out


def add_alternates(pl: bytes, made):
    """`pl` with one more action for each (index of the action it is a second version of, script): the
    same clip and flags, its own script. The action table is written again at the end of the file, long
    enough for them (in fours: four entries end on the file's 32-byte lines, so what is written after it
    starts where it ends). -> (bytes, [the new actions' indices])"""
    import struct
    from vault.echo.subactions import ACTION_SIZE, FighterDat
    fd = FighterDat(pl)
    d = fd.dat
    tbl, count = fd.action_table
    blob = bytearray(d.buf[0x20 + tbl:0x20 + tbl + count * ACTION_SIZE])
    old = {off for off in range(tbl, tbl + count * ACTION_SIZE, 4) if off in d.relocs}
    pointers, new = [off - tbl for off in sorted(old)], []
    for source, _ in made:
        at = len(blob)
        blob += blob[source * ACTION_SIZE:(source + 1) * ACTION_SIZE]
        struct.pack_into('>I', blob, at + 0x0C, 0)          # its script comes next
        if tbl + source * ACTION_SIZE in old:
            pointers.append(at)                             # the clip's name
        new.append(at // ACTION_SIZE)
    blob += bytes(-len(blob) % (4 * ACTION_SIZE))
    table = d.append_struct(bytes(blob), pointers, align=0x20)
    d.set_u32(fd.ft_root + 0x0C, table)
    d._rebuild(bytes(d.buf[0x20:0x20 + d.data_size]), d.relocs - old)     # the old table is no longer one
    fd = FighterDat(d.to_bytes())
    for index, (_, items) in zip(new, made):
        fd.replace_script(index, list(items))
        fd._scripts.clear()
        fd = FighterDat(fd.to_bytes())
    return fd.to_bytes(), new


# A neutral special that fires a projectile, on a donor whose own neutral special charges and releases.
# release: the donor actions whose script lets the shot go; quiet: the donor actions whose own effects go;
# states: the donor's states for a plain release and for a full charge; flag: a script flag the donor's code
# leaves alone; loops: where the donor's special attributes hold how many 30-frame charge loops make a full charge.
SHOT_DONOR = {'Marth': {'release': ('SpecialNEnd', 'SpecialAirNEnd'),
                        'quiet': ('SpecialNStart', 'SpecialNLoop', 'SpecialAirNStart', 'SpecialAirNLoop'),
                        'start': 'SpecialNStart', 'states': {'release': (343, 347), 'full': (344, 348)}, 'flag': 1,
                        'loops': 0x0}}
# Where the game keeps a fighter's shots. Each: the weapon script with its hitbox, its model, the parameter
# table with its speed and life (or the distance it covers in `over` frames), when it is the one let go.
# move: the script on whose first frame a shot is let go; charge: a parameter table (found by a field it has)
# and the field that holds the frame a full charge is reached. (Per fighter until a second one shows the rule.)
SHOT_GAME = {'master': {'move': 'game_specialn', 'charge': ('shoot_end_frame', 'frame'), 'shots': [
    {'when': 'release', 'script': 'game_fly', 'model': 'arrow1', 'params': 'param_arrow1', 'speed': 'speed_x', 'life': 'life'},
    {'when': 'full', 'script': '0x0bc9c5766f', 'model': 'arrow2', 'params': 'param_arrow2', 'distance': 'distance',
     'over': 10.0, 'pierce': True}]},
             # a blade of light the game draws with particles (no model); a slower one in the air (`on`).
             # The Limit beam (`variant` 1: the fighter's own code says when; the second row of the same
             # parameter table): faster, and what it hits it holds: `then` is the script it runs from there.
             'cloud': {'move': 'game_specialn', 'shots': [
    {'when': 'release', 'on': 'ground', 'script': 'game_regular', 'params': 'param_wave', 'speed': 'speed_ground', 'life': 'life'},
    {'when': 'release', 'on': 'air', 'script': 'game_regularair', 'params': 'param_wave', 'speed': 'speed_air', 'life': 'life'},
    {'when': 'release', 'on': 'ground', 'script': '0x0f9a26dc62', 'params': 'param_wave', 'row': 1, 'speed': 'speed_ground',
     'life': 'life', 'variant': 1, 'then': '0x0b553beef9'},
    {'when': 'release', 'on': 'air', 'script': '0x12e00f3a48', 'params': 'param_wave', 'row': 1, 'speed': 'speed_air',
     'life': 'life', 'variant': 1, 'then': '0x0e9f3f553e'}]}}
# Ultimate's common effects that Melee has its own of: the dust a move kicks up and the gleam of a smash
# attack being charged. (Melee's number for each, as the donor's own scripts use it: 1021 under a dash
# attack and a forward tilt, 1019 under an up smash and an up special, 1011 on the sword as a smash starts,
# 1022 to 1026 under running, dashing, turning and jumping feet, 1024 and 1031 getting up and landing.)
# A fighter's own particle effects have no Melee form and are not carried.
EFFECT_MELEE = {'sys_smash_flash': 1011, 'sys_smash_flash_s': 1011, 'sys_atk_smoke': 1021, 'sys_action_smoke_h': 1021,
                'sys_v_smoke_a': 1019, 'sys_v_smoke_b': 1019, 'sys_action_smoke_v': 1019, 'sys_down_smoke': 1024,
                'sys_landing_smoke': 1031, 'sys_run_smoke': 1022, 'sys_dash_smoke': 1023, 'sys_turn_smoke': 1025,
                'sys_sliding_smoke': 1025, 'sys_jump_smoke': 1026,
                # dust thrown along the ground as a fighter drives forward: what a dash attack kicks up in both games
                'sys_h_smoke_a': 1021, 'sys_h_smoke_b': 1021}
# The games' shared sounds that Melee has its own of, by Melee's number for each, as its own fighters' scripts play
# them: the swing of a punch or a kick (166 on a jab, 165 on a tilt, a dash attack, the last hit of a jab) and of a
# sword (160 on Marth's, Roy's and Link's jabs, 159 on their bigger swings). The other shared sounds are numbered, not
# named, in the game's files and are not carried.
SOUND_MELEE = {'se_common_punch_kick_swing_s': 166, 'se_common_punch_kick_swing_m': 166, 'se_common_punch_kick_swing_l': 165,
               'se_common_sword_swing_s': 160, 'se_common_sword_swing_m': 160, 'se_common_sword_swing_l': 159}
# A fighter's own particle effects have no Melee form and are not carried. These few are drawn with one of Melee's
# shared effects in their place, chosen by eye from pictures of every shared effect (the probe's `gfxcat` moves take
# them): a stand-in for the game's effect, not the effect. Eruption's fire is Melee's burst of flame, and the blast
# of a full charge its explosion; each is put where the move's own hitboxes are.
EFFECT_STAND_IN = {'ike_hunka': 1040, 'ike_hunka_max': 1039}
COLANIM = 46                        # a script command: one of the game's ready-made colour animations over the body
SWING_LEAD = 2                      # frames a sword's trail is drawn before its first hitbox and after its last
# A fighter whose second versions of its specials are all drawn in one colour of their own, where the game's
# data gives those versions no trail picture to read it from: the script whose trail has that colour. (Cloud's
# Limit moves are blue, the colour of Finishing Touch, the one move only a full gauge gives.)
SECOND_COLOUR = {'cloud': 'game_speciallw'}
SWING_WORDS = ('slash', 'stroke')       # in the name of a fighter's own effect: it draws a swing of its weapon
# In the name of an effect: lines of speed, which the game draws on a move that drives the weapon the way it
# points (a stab down, a lunge) in place of a trail. A trail is the path of a blade's edge; along a blade
# that only moves the way it points it is a spike off its tip, and the sword seems to grow.
THRUST_WORD = 'speedline'
# Donor states that the donor's code enters part-way in (the frame it starts them on). The engine runs a script
# up to the frame a state starts on without its sounds and effects, so those are heard only from the frame
# after: Marth's release states start on frame 1 (ftMs_SpecialN.c), and his own release sounds sit on frame 2.
STARTS_ON = {'Marth': {'SpecialNEnd': 1, 'SpecialAirNEnd': 1}}
# The set knockback of Melee's own hits that lead into the next (Fox's drill kick, the first hit of his
# up air): what a hit under one of Ultimate's link angles is written with.
LINK_KB = 30
# The script flag in which the donor's chained special notes a button pressed before a step's window (it
# then never goes on): wiped each frame for a port, whose fighter has no such rule.
CHAIN_LOCK = {'Marth': 1}
# The script flag a chained special's first window is written on when the chain goes on only after a hit
# (`own.CHAIN_NEEDS_HIT`): one the donor's own code does not read.
CHAIN_GATE = {'Marth': 3}
# A special that cannot be knocked out of its swing. The game sets this in code this reader does not read, so
# the first frame is from the move's published frame data; it lasts until the swing's hitbox ends.
ARMOUR_GAME = {'master': {'script': 'game_speciallw', 'first': 34}}      # published: armour from frame 34 to the swing
ARMOUR_DONOR = {'Marth': (369, 371)}                    # the donor states the down special runs in, ground and air
# A special the donor charges and lets go: its code counts loops of 30 frames while the button is held, lets go by
# itself after so many, and sets the release's damage to a base plus so much a loop. Where each number sits in the
# donor's own special numbers, and the states of the full release.
CHARGE_DONOR = {'Marth': {'loops': 0x0, 'base': 0x4, 'step': 0x8, 'full': (344, 348)}}
# Where a fighter's game keeps the same: the table of its neutral special's numbers and which of them is the
# number of levels, the damage a level adds, and what a full charge costs the fighter itself; the base is the
# damage its release script writes. (Ike's: 7 levels of 4 on a script damage of 9 is the published 37.)
# (The game's table is the donor's own table of the same special, grown: lined up with the fighter that is in both
# games. Brawl's Marth has 2, 8, 5, 0.8, 0.02, 0 where Melee's has 4 loops, 7 damage, 5 a loop, 1.25 (one over 0.8),
# 0.02: so the second number is the damage a release starts from, and the sixth, nothing for Marth and 10 for Ike, is
# what a full charge costs the fighter. The script's own hitbox says 9; the code puts the table's number on it.)
CHARGE_GAME = {'ike': {'table': 'paramIkeSpecialN__9ftIkeNode', 'levels': 0, 'base': 1, 'step': 2, 'recoil': 5,
                       'script': 'game_specialnend'}}
# A counter. The donor's waits with a script flag up for as long as a hit taken is countered, and strikes back with
# its script's damage (its code multiplies what it took only for one fighter of the game's own): the port's code
# gives the strike the damage taken times the fighter's number, and no less than its least.
# 'bubble': where the donor keeps the ball a hit must touch to be countered (what it rides, its place, its size)
COUNTER_DONOR = {'Marth': {'wait': ('SpecialLw', 'SpecialAirLw'), 'hit': ('SpecialLwHit', 'SpecialAirLwHit'), 'flag': 1, 'times': 0x5C,
                           'bubble': {'rides': 0x64, 'place': 0x68, 'size': 0x74}}}
# (Lined up the same way: Brawl's Marth has 0.5, 0.0025, 0.04, 1.2, 1.1, 0.9, 16, 8 where Melee's has 2 (one over
# 0.5), 0.0025, 0.04, 1.2 and then its multiple: the fifth number is the multiple (1.1 for Marth, as published) and the
# eighth the least it gives back (8 for Marth). The ball is a table of its own, in the donor's own order: what it
# rides, its place, its size.)
COUNTER_GAME = {'ike': {'table': 'paramIkeSpecialLw__9ftIkeNode', 'times': 4, 'least': 7, 'script': 'game_speciallw',
                        'bubble': 'paramIkeSpecialLwShield__9ftIkeNode'}}
# An up special that throws a bending weapon, on a donor whose air up special can catch a ledge: the donor
# action and state, and the script flags that make its own code fall and catch ledges.
TETHER_DONOR = {'Marth': {'action': 'SpecialAirHi', 'state': 368, 'flags': (0, 1, 2)}}
# An up special whose rise is in its clip, on a donor whose own up special rises by its clip: the clip's
# travel is given to the engine on the donor's root joint (it is dropped for other moves), and the donor's
# script leaves the ground with one command and raises one flag (in the air the donor follows the clip
# only while that flag is up), which the port's script needs on the frame its own clip starts to rise.
# In the air the source game follows the clip from its first frame (a fighter that throws its sword before it
# rises hangs there while it does): the flag goes up on the air action's first frame. The donor multiplies the
# clip's travel in the air by a number of its own ('air_scale', an offset in its special numbers): made 1, so the
# air clip's own travel is what is seen.
RISE_DONOR = {'Marth': {'actions': ('SpecialHi', 'SpecialAirHi'), 'air': ('SpecialAirHi',), 'command': 25, 'flag': 0,
                        'root': 'JOBJ_1', 'air_scale': 0x40}}
MAX_JOINTS = 140                                        # how many joints the game holds for one fighter
# The states each of the donor's specials starts in (ground and air): where a special can be turned around.
ENTRY_STATES = {'Marth': ('SpecialNStart', 'SpecialAirNStart', 'SpecialS1', 'SpecialAirS1', 'SpecialHi', 'SpecialAirHi',
                          'SpecialLw', 'SpecialAirLw')}
# The game's own sign that a charge is being held (the flashing of a fighter with a full Giant Punch): a colour
# animation every fighter can wear, and one that stays on through other moves. For a port's own stored charge.
OWN_GLOW = {'Marth': 57}
# Common states that let the fighter act as soon as their script says so (the game's "first actionable
# frame"), while the animation goes on if nothing is asked: their clips are carried to their end, with
# the script's permission on the game's frame. Other states (specials, throws) end when their clip does,
# so their clips stop at that frame. Names are the start of an action's name.
ACTS_EARLY = ('Attack11', 'Attack12', 'Attack13', 'AttackDash', 'AttackS3', 'AttackHi3', 'AttackLw3',
              'AttackS4', 'AttackHi4', 'AttackLw4', 'AttackAir', 'Appeal')
# An action that runs the game's shared script (a dodge, a roll, a tech, a getup, a ledge climb, a shield drop)
# has no script of the fighter's own to say when it ends or when nothing can touch the fighter, and the donor's
# script says both for the donor. The game holds them elsewhere: for a dodge or a roll in the fighter's row of
# the dodge table (the game's code reads that, not the motion list), for a shield drop in the table every
# fighter shares, for the rest in the motion list, clip by clip. (Before this the clips of these actions played
# to their raw end, a spot dodge of 53 frames where the game's is 25, on the donor's untouchable frames.)
DODGE = {'EscapeN': 'escape_n', 'EscapeF': 'escape_f', 'EscapeB': 'escape_b', 'EscapeAir': 'escape_air'}
SHARED_END = {'GuardOff': 'guard_off_cancel_frame'}
# Donor actions that do not end with their clip's free frame: a landing lasts what the engine's own numbers say,
# and a fighter that has been hit reels for as long as the hit says (its clip plays through, as the donor's does).
ENGINE_ENDS = ('Landing', 'Damage', 'WallDamage')
# The donor actions that reach out to grab, and the game script of each. The game's two boxes are one for
# standing fighters and a thinner, longer one for fighters in the air; Melee's grab boxes can say the same.
GRABS = {'Catch': 'game_catch', 'CatchDash': 'game_catchdash'}
GRAB_ELEMENT = 8                    # the element of a hitbox that grabs
# A grab box takes hold on the frame after it is made (the donor's, made on 6, is known to grab on 7; its hits
# land on the frame they are written on), so the game's first grabbing frame is written one earlier.
GRAB_LEAD = 1


def shared_end(game, stem, target):
    """The frame the fighter may act on in a carried action with no script of its own to say so, or None."""
    params = game.get('motion_params') or {}
    if any(target.startswith(n) for n in ENGINE_ENDS):
        return None
    if target in DODGE:
        v = params.get(DODGE[target] + '_cancel_frame')
    elif target in SHARED_END:
        v = params.get(SHARED_END[target])
    else:
        v = ((game.get('motions') or {}).get(stem) or {}).get('cancel_frame')
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 1 else None


def shared_untouchable(game, stem, target):
    """[the first frame nothing can touch the fighter on, the frame that ends on] in a carried action that keeps
    the donor's script, in the game's animation frames, or None. A dodge: a start and a count, in the fighter's
    row of the dodge table. The rest: the motion list's start and end (a tech's are 1 and 21 where the game is
    known to be untouchable on frames 1 to 20: the end is the first frame it can be hit again)."""
    params = game.get('motion_params') or {}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if target in DODGE:
        first, count = (params.get(f'{DODGE[target]}_hit_{w}_frame') for w in ('xlu', 'normal'))
        if num(first) and num(count) and first >= 1 and count >= 1:
            return [int(first), int(first + count)]
        # (a game with no dodge table says it in the dodge's own script, like any other action: Brawl)
    span = ((game.get('motions') or {}).get(stem) or {}).get('intangible')
    return [int(span[0]), int(span[1])] if span and all(num(v) for v in span) and span[1] > span[0] >= 0 else None


def absolute(items):
    """A script's commands with the frame each runs on -> ([(frame, command)], it had an end mark), or None for
    one that loops or calls another (its commands have no one frame). "Wait N frames" and "wait until frame N"
    are both read."""
    frame, out = 0, []
    for item in items:
        code, fields = item[0], item[1]
        if code == 0:
            return out, True
        if code in (3, 4, 5, 6, 7):
            return None
        if code == 1:
            frame += int(fields['frame'])
        elif code == 2:
            frame = max(frame, int(fields['frame']))
        else:
            out.append((frame, item))
    return out, False


def rebuilt(events, ended):
    """[(frame, command)] back to a script that waits until each frame (commands of one frame keep their order)."""
    items, last = [], 0
    for frame, item in sorted(events, key=lambda e: e[0]):
        if frame > last:
            items.append((2, {'frame': int(frame)}, None))
            last = frame
        items.append(item)
    return items + ([(0, {}, None)] if ended else [])


def grab_boxes(move, scale):
    """The game's grab as Melee's balls -> (the first frame it grabs on, the frame its boxes are gone on,
    [{'position', 'radius', 'targets'}]) or None. Each of the game's boxes is a line with a radius; Melee's four
    balls are shared between them as a drawn-out hit's are (`balls`, `ball_points`)."""
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    made = [o for o in (move or {}).get('other') or [] if o['cmd'] == 'CATCH' and len(o['args']) >= 11
            and str(o['args'][1]).lower() == 'top' and all(num(v) for v in o['args'][2:9])]
    if not made:
        return None
    first = min(o['real'] for o in made)
    made = [o for o in made if o['real'] == first]
    end = move.get('catch_end')
    end = int(end) if num(end) and end > first else first + 2
    hs = [{'size': a[2], 'x': a[3], 'y': a[4], 'z': a[5], 'x2': a[6], 'y2': a[7], 'z2': a[8],
           'targets': {'<const 0xe7c4>': 'ground', '<const 0xe7c8>': 'air'}.get(str(a[10]))}
          for a in (o['args'] for o in sorted(made, key=lambda o: o['args'][0]))][:4]
    out = []
    for h, count in zip(hs, balls([stretch_of(h) for h in hs])):
        out += [{'position': [v * scale for v in point], 'radius': size * scale, 'targets': h['targets']}
                for point, size in ball_points(h, count)]
    return int(first), end, out


def regrab(items, move, scale):
    """A donor's grab script with the game's grab in it: the boxes where the game has them, made so that they
    take hold on the game's first frame and gone on the game's; what the donor did with its boxes (its sound,
    the hit a broken grab does) moves with them. None when the script or the game's data cannot be read."""
    from fighter_port import combat
    from vault.echo.subactions import FighterDat
    read, made = absolute(items), grab_boxes(move, scale)
    hitbox, clear = combat.command('create_hitbox')[0], combat.command('clear_hitboxes')[0]
    if read is None or made is None:
        return None
    events, ended = read
    boxes = [(f, it) for f, it in events if it[0] == hitbox and it[1].get('element') == GRAB_ELEMENT]
    if not boxes:
        return None
    first, end, new = made
    f0 = min(f for f, _ in boxes)
    f1 = min((f for f, it in events if it[0] == clear and f > f0), default=f0 + 2)
    g0, g1 = max(0, first - GRAB_LEAD), max(1, end - GRAB_LEAD)
    where = lambda f: min(f, g0) if f < f0 else min(g0 + (f - f0), g1 - 1) if f < f1 else g1 + (f - f1)
    out, put = [], False
    for f, it in events:
        if it[0] == hitbox and it[1].get('element') == GRAB_ELEMENT:
            if put:
                continue
            put = True
            for i, b in enumerate(new):
                x, y, z = (combat.fixed(v) for v in b['position'])
                out.append((g0, (hitbox, dict(boxes[0][1][1], id=i, size=combat.fixed(b['radius']), x_offset=z, y_offset=y,
                                              z_offset=x, hit_grounded_fighters=int(b['targets'] != 'air'),
                                              hit_aerial_fighters=int(b['targets'] != 'ground')), None)))
        else:
            out.append((where(f), it))
    items = rebuilt(out, ended)
    FighterDat.encode_script([i for i in items if i[0] != 0])
    return items, {'first': first, 'end': end, 'boxes': len(new)}


def untouchable(items, first, end, how=2):
    """A donor script that keeps everything but the frames nothing can touch the fighter on: those become
    `first` to the frame before `end` (a first frame of 1 is the script's start). `how`: 2 hits pass through
    it, 1 they strike it and do nothing. None for a script that cannot be read."""
    from fighter_port import combat
    state = combat.command('set_body_collision_state')[0]
    read = absolute(items)
    if read is None:
        return None
    events, ended = read
    events = [(f, it) for f, it in events if it[0] != state]
    on = (0 if first <= 1 else first, combat.command('set_body_collision_state', body_state=how))
    off = (end, combat.command('set_body_collision_state', body_state=0))
    # (on goes before what else the script does on its frame; off after)
    return rebuilt([on] + events + [off], ended)


# A jab the donor does not have. The game plays a third jab for any fighter whose action after the second
# jab has a clip (the donor itself is told apart by its own kind, which a new fighter does not have).
EXTRA_ACTION = {'attack13': ('Attack12', 'Attack13')}   # clip name: (the action it follows, its own name)
# Moves that move the fighter (a forward smash that steps in, a sliding kick). Ultimate moves a fighter by
# its clip's root bone; Melee does so only for an action that carries a flag (the engine then takes the
# root's travel out of the picture) AND whose state's physics reads that travel. Left alone, the travel
# stays in the picture: the body slides off its own position and hitboxes, and snaps back when the move ends.
#   READS_TRAVEL     common states whose physics reads it (the donor's own flagged actions do too)
#   FRICTION_ONLY    common ground states that only slow the fighter: the port's code file moves it instead
# (Read from the game's code: jab and forward smash use the routine that reads the root, tilts and the other
# smashes one that applies friction only.) Names are the start of an action's name.
READS_TRAVEL = ('Attack11', 'Attack12', 'Attack13', 'AttackS4', 'ThrowF', 'ThrowB', 'ThrowHi', 'ThrowLw')
FRICTION_ONLY = ('AttackS3', 'AttackHi3', 'AttackLw3', 'AttackHi4', 'AttackLw4')
FRICTION_ONLY_DONOR = {'Marth': ('SpecialS1', 'SpecialS2Hi', 'SpecialS2Lw')}
TRAVEL_ROOT = {'Marth': 'JOBJ_1'}                       # the donor joint whose travel the engine reads
TRAVEL = 0.5                                            # how far (the game's units) a root must go to count
MOVES_BY_CLIP = 0x80000000                              # the action flag
# a fighter with a simple projectile to take the item's data from: (vanilla data file, item index)
SHOT_TEMPLATE = ('PlMr.dat', 0)

# Clips the Shulk table has no row for (his forward tilt was hand-authored), by donor action name.
DONOR_ROWS = {'Marth': {'attacks3s': 'AttackS31'}}


_PLAYS = {}

# How many frames an action lasts, against the frame count its clip is stored with. Melee enters most actions one
# frame into their clip: its code steps the animation once as it changes state (ftAnim_8006EBA4 right after
# Fighter_ChangeMotionState, MexTK's Fighter_AdvanceScript), or starts the clip at frame 1. Such a clip of F frames
# is on screen for F - 1 (counted in the game on the donor, a frame at a time: its spot dodge is stored as 28 and
# lasts 27, its roll 36 and 35, air dodge 50 and 49, jab 28 and 27; smashes, the first state of each special, the
# ledge attack, roll, climb and jump, the getup attack and rolls all the same). So a clip that must last as long as
# its source says is stored one frame longer (`hold_end`).
# The actions below are entered at frame 0 with no step and play their whole clip (counted the same way: grab 30 and
# 30, shield drop 16, getting up 30, the bounce on landing 26, the techs 26 and 40, the taunt 93): they are stored as
# they are. Which is which is read off the game's own code, state by state (a name ending in * stands for every
# action that starts with it). An action that loops (the engine's own flag) wraps on its count and is stored as it
# is too: its last pose is its first. A port's own states are entered with the step.
PLAYS_WHOLE = ('Wait1', 'Wait2', 'WaitItem', 'TurnRun', 'RunBrake', 'Landing*', 'Jump*', 'SquatWait*', 'SquatRv',
               'Guard', 'GuardOff', 'GuardDamage', 'Rebound', 'Attack12', 'Attack13', 'Attack100*', 'DamageFall',
               'DownBound*', 'DownStand*', 'Passive*', 'Fura*', 'Pass', 'Ottotto*', 'StopWall', 'StopCeil', 'MissFoot',
               'Entry', 'Appeal*', 'Catch*', 'Capture*', 'WallDamage', 'ItemScrew*')
# ... and of a donor's own states: the later steps of Marth's chained side special and the strike of his counter
# start at frame 0 (his release of a charge starts at frame 1, like a step).
PLAYS_WHOLE_DONOR = {'Marth': ('SpecialS2*', 'SpecialS3*', 'SpecialS4*', 'SpecialAirS2*', 'SpecialAirS3*',
                               'SpecialAirS4*', 'SpecialLwHit', 'SpecialAirLwHit'),
                     'Roy': ('SpecialS2*', 'SpecialS3*', 'SpecialS4*', 'SpecialAirS2*', 'SpecialAirS3*',
                             'SpecialAirS4*', 'SpecialLwHit', 'SpecialAirLwHit')}
LOOPS = 0x40000000


def lasts_its_keys(motion, loops, donor=None):
    """Whether a clip that goes on the donor's action `motion` is stored one frame longer than its keys, so that it
    lasts as long as they say (`loops`: the donor's actions that loop)."""
    if not motion or motion in loops:
        return False
    for name in PLAYS_WHOLE + PLAYS_WHOLE_DONOR.get(donor, ()):
        if motion == name or (name.endswith('*') and motion.startswith(name[:-1])):
            return False
    return True

# The eyes: the donor's own script command that sets which picture its eyes show, and the pictures its idle blink
# steps through (open, half shut, shut: Marth's Wait1 sets 1, 2, 1, 0). A game that says which face a clip shows on
# which frames (`faces` in a move) has the port's eyes set on those frames; the donor's own blink is taken out of
# such a clip's script. A face the donor has no picture for (pain, with its mouth open) is the nearest of the three.
EYES_DONOR = {'Marth': {'command': 40, 'fields': {'material_flag': 1, 'material_index': 0, 'frame_flags': 1},
                        'open': 0, 'half': 1, 'closed': 2}}


def flash_keys(rows, offset=0):
    """A move's flashes ([[frame, colour, frames to get there]]) as keys the port's code plays: [(frame, frames to get
    there, the colour it starts from, the colour it goes to)]. A colour that comes up out of nothing starts as itself,
    clear."""
    out, cur = [], None

    def at(key, f):
        if key is None:
            return [0, 0, 0, 0]
        frame, fade, start, to = key
        k = 1.0 if fade <= 0 else min(1.0, (f - frame) / fade)
        return [int(round(a + (b - a) * k)) for a, b in zip(start, to)]

    for f, colour, fade in sorted(rows, key=lambda r: r[0]):
        f = max(1, int(f) + int(offset))
        start = at(cur, f)
        if start[3] == 0:
            start = list(colour[:3]) + [0]
        cur = (f, int(fade), start, [int(v) for v in colour])
        out.append(cur)
    return out

SECOND = '__2'                  # a second script under one name, as a reader keeps it (echo_brawl.gamedata.SECOND)


def combat_nth(actions, which):
    from fighter_port import combat
    return combat.nth_actions(actions, which)


def script_for(stem, moves):
    """The move script that goes with an animation file. Usually game_<name>; else the script
    whose motion plays that file (specialhi plays specialhi1); the straight version of an angled
    attack (attacks3s, attacks4s) uses the plain name."""
    name = 'game_' + stem[3:]
    if name in moves:
        return name
    plays = _PLAYS.get(id(moves))
    if plays is None:
        plays = _PLAYS[id(moves)] = {}
        for named in (False, True):                     # a script whose name did not resolve will do when no named one plays the clip
            for script in sorted(moves, key=len, reverse=True):   # the shortest name wins a shared clip
                anim = moves[script].get('animation')
                if script.startswith('game_') == named and anim and (named or anim[:-len('.nuanmb')] not in plays):
                    plays[anim[:-len('.nuanmb')]] = script
        for script in list(plays.values()):
            if not script.startswith('game_') and not moves[script].get('hitboxes'):
                plays = {k: v for k, v in plays.items() if v != script}
        _PLAYS[id(moves)] = plays
    if stem in plays:
        return plays[stem]
    if name.endswith('s') and name[:-1] in moves:
        return name[:-1]
    return name


# The donor's sword joint and the hand it hangs from, and the Ultimate bones tried for it.
WEAPON = {'Marth': {'target': 'JOBJ_75', 'target_anchor': 'JOBJ_73'}}
WEAPON_SOURCES = (('Sword1', 'HandR'), ('SwordR', 'HandR'), ('HaveR', 'HandR'))

# Ultimate bone (lowercase, as scripts name it) -> landmark, for hitboxes.
BONE_LANDMARK = {'hip': 'pelvis', 'waist': 'spine', 'bust': 'chest', 'neck': 'neck', 'head': 'head',
                 'claviclel': 'l_collar', 'shoulderl': 'l_shoulder', 'arml': 'l_elbow', 'handl': 'l_wrist',
                 'clavicler': 'r_collar', 'shoulderr': 'r_shoulder', 'armr': 'r_elbow', 'handr': 'r_wrist',
                 'legl': 'l_hip', 'kneel': 'l_knee', 'footl': 'l_ankle', 'toel': 'l_toe',
                 'legr': 'r_hip', 'kneer': 'r_knee', 'footr': 'r_ankle', 'toer': 'r_toe'}
WEAPON_BONES = ('sword1', 'sword2', 'swordr', 'haver')

ELEMENT = {'collision_attr_normal': 0, 'collision_attr_fire': 1, 'collision_attr_elec': 2,
           'collision_attr_cutup': 3, 'collision_attr_sting': 3, 'collision_attr_slash': 3,
           'collision_attr_ice': 5}

# Melee attribute <- Ultimate fighter_param field(s), copied unchanged (summed when two).
ATTRIBUTES = {'max_walk_speed': ('walk_speed_max',), 'initial_dash_speed': ('dash_speed',),
              'initial_run_speed': ('run_speed_max',), 'jump_startup_lag': ('jump_squat_frame',),
              'gravity': ('air_accel_y',), 'terminal_velocity': ('air_speed_y_stable',),
              'max_aerial_horizontal_speed': ('air_speed_x_stable',),
              'fast_fall_terminal_velocity': ('dive_speed_y',), 'weight': ('weight',),
              # Steering in the air is two numbers in both games: what the stick is multiplied by and a flat part
              # added in the stick's direction (ftcommon.c: lsx * air_drift_stick_mul +- aerial_drift_base). The
              # first ports wrote the sum of the game's two into the first and left the donor's flat part, so a
              # fighter steered with the donor's flat part on top of its own. (+0x68 is the flat part; the app's
              # table calls it 'aerial_friction'. What slows a fighter that is not steering is +0x70.)
              'aerial_speed': ('air_accel_x_mul',), 'aerial_friction': ('air_accel_x_add',),
              'air_friction': ('air_brake_x',),
              # What stops a fighter on the ground, and how a walk starts (ftwalkcommon.c: stick * walk_init_vel
              # + a flat walk_accel). For the 24 fighters in both games the game's two walk numbers are Melee's
              # times 1.05 exactly, each with each, so they are the same numbers (the first ports left all three
              # the donor's: a fighter slid to a stop as the donor does).
              'friction': ('ground_brake',), 'initial_walk_speed': ('walk_accel_mul',),
              'walk_acceleration': ('walk_accel_add',),
              # The same number in both games for the fighters in both (jumps exact; the others within a few
              # hundredths for 21 of 22 and for 22 of 24).
              'number_of_jumps': ('jump_count_max',), 'horizontal_air_jump_multiplier': ('jump_aerial_speed_x_mul',),
              'item_throw_velocity': ('throw_item_speed_mul',), 'item_throw_damage_scale': ('throw_item_power_mul',)}
# The shield's radius. Melee multiplies its number by the model's scale (Bowser's 31.25 at a scale of 0.69, Pichu's
# 24.3 at 0.5: times the scale, the 24 fighters in both games are all 1.05 to 1.6 times the game's radius; without
# it, 0.75 to 2.76). The game's is in its own lengths at a scale of 1.
SHIELD = ('shield_size', 'shield_radius')
# Aerial landing lag: Ultimate's own number, so a landing plays as the game plays it. (Melee halves it for a
# landing that is L-cancelled, which Ultimate has no word for. The first ports wrote twice the number, so that
# an L-cancel gave Ultimate's back; a landing without one then took twice as long as the game's and its clip
# played at half speed: Byleth's down air held its crouch for 56 frames.)
LANDING_TIMES = 1.0
HELD_REACH = 30.0                   # the size (the game's units) a hit for the held fighter alone is written with
# A shot that goes through what it hits and flies this fast (the game's units a frame: across a stage in under half
# a second) is seen in the game as a beam of light, not as a thing that flies. The game draws that with particles,
# which are not read here: the port's code draws a streak. Its colour is the game's, per fighter (Byleth's fully
# drawn arrow is "a golden beam"); gold where none is given.
BEAM_SPEED = 15.0
BEAM_COLOUR = {'master': (255, 186, 44)}
BEAM_HALF = 3.3                     # half the streak's height, in the game's units (its glow; the bright core is a fifth of it)
# The fighter's own parameter file (vl.prc): what its code reads. Names that resolve: the table of each special,
# and in it the speed upward a special starts with in the air.
OWN_TABLES = {'n': 'param_special_n', 's': 'param_special_s', 'hi': 'param_special_hi', 'lw': 'param_special_lw'}
# Names of values in those tables (the file holds only a hash of each; these were found by hashing likely names).
OWN_NAMES = ('cancel_start_frame', 'cancel_end_frame', 'turn_disable_frame', 'jump_speed_x', 'jump_speed_y', 'wall_hit_max',
             'wall_offset_x', 'wall_offset_y', 'air_speed_x_mul', 'air_speed_y_mul', 'speed_x_mul', 'super_armor_damage_max')
# The up special's kick is written by the game as a throw in three versions. The one a hurt fighter gets (the game
# picks by the caught fighter's damage) is the one with the most growth: it sends the fighter down.
STOMP_GAME = {'master': 'game_specialairhiovertake'}
START_Y = 'start_speed_y_air'
# The game's name of a fighter's number -> the field the port's code file knows it by (MexTK's): for a table in
# the fighter's own file that names such numbers with what they are multiplied by in a state of the fighter's.
BOOST_FIELD = {'walk_speed_max': 'walk_maximum_velocity', 'ground_brake': 'ground_friction', 'dash_speed': 'dash_initial_velocity',
               'run_speed_max': 'dashrun_terminal_velocity', 'air_accel_x_mul': 'aerial_drift_stick_mult',
               'air_accel_x_add': 'aerial_drift_base', 'air_speed_x_stable': 'aerial_drift_max', 'air_brake_x': 'aerial_friction',
               'air_accel_y': 'gravity', 'air_speed_y_stable': 'terminal_velocity'}
# The donor joint a held fighter hangs from and the body joint that is carried from; the game's own bone for it
# and the bone that is measured from. (Left still, a grabbed fighter stands inside the port's body instead of
# at its hand, and a throw's animation never moves it: the first hand-made port had the same fault.)
HELD = {'Marth': {'target': 'JOBJ_88', 'target_anchor': 'JOBJ_3'}}
HELD_SOURCE = ('Throw', 'Trans')
HOLDS = ('Catch', 'Throw')          # the start of the names of the actions that hold a fighter
# The sound a hit makes, in the game's words by their place in this game version's table: how hard (Melee's
# three levels) and what with (Melee's kinds: 1 a punch, 2 a kick, 3 a blade). A fighter's own hit sounds (a
# named sword's) are not in Melee: there a hit that cuts sounds as a blade, any other as a kick.
SOUND_LEVEL = {'<const 0xe734>': 0, '<const 0xe740>': 1, '<const 0xe744>': 2}
SOUND_KIND = {'<const 0xe778>': 1, '<const 0xe774>': 2, '<const 0xe738>': 3}
CUTS = ('collision_attr_cutup', 'collision_attr_sting', 'collision_attr_slash')
# A hit another attack cannot meet (the game's two words for it: not met at all, and going through). Melee's
# hits on the ground cancel each other unless a hit says it does not.
NO_CLANK = ('<const 0xb98c>', '<const 0xe728>')
# How high a jump goes is a height in the game's data and a starting speed in Melee's.
JUMPS = {'initial_vertical_jump_velocity': 'jump_y', 'max_shorthop_vertical_velocity': 'mini_jump_y'}
AIR_JUMP = ('vertical_air_jump_multiplier', 'jump_aerial_y')        # Melee: a share of the full jump's speed
# Melee attribute <- the game's field of the same meaning for a jump's sideways speed (what the stick adds,
# how much of the run is kept, the most it can be): both games work it out the same way.
SAME = {'initial_horizontal_jump_velocity': 'jump_speed_x', 'ground_to_air_jump_momentum_multiplier': 'jump_speed_x_mul',
        'max_shorthop_horizontal_velocity': 'jump_speed_x_max'}
LANDING = {'nair_landing_lag': 'landing_attack_air_frame_n', 'fair_landing_lag': 'landing_attack_air_frame_f',
           'bair_landing_lag': 'landing_attack_air_frame_b', 'uair_landing_lag': 'landing_attack_air_frame_hi',
           'dair_landing_lag': 'landing_attack_air_frame_lw'}


def log(*a):
    print(*a, flush=True)


def ssbh(root):
    p = os.environ.get('SSBH_DATA_PY') or str(Path(root) / 'pydeps' / 'ssbh_data_py-0.9.1')
    if p not in sys.path:
        sys.path.insert(0, p)
    import ssbh_data_py
    return ssbh_data_py


def motion_table():
    """{clip stem: [row]} from the Shulk recipes: target action and how travel is handled."""
    table = {}
    for f in sorted(RECIPES.glob('*_moveset.json')):
        for r in json.loads(f.read_text('utf-8')).get('clips', []):
            if not r.get('source') or not r.get('target_motion'):
                continue
            if r.get('category') == 'explicit_slot_reuse':
                continue        # Shulk's own rewiring (his third jab on a Dancing Blade slot), driven by his C code
            stem = r['source'].rsplit('/', 1)[1][:-len('.nuanmb')]
            row = {k: r[k] for k in ('target_motion', 'category', 'root_motion_joint', 'engine_root', 'body_scale')
                   if k in r}
            if row not in table.setdefault(stem, []):
                table[stem].append(row)
    return table


# Melee has one taunt and the game three. The table's is the down taunt (the choice made for the first fighter
# ported). A fighter known for another names its clip in `fighters.py` (`taunt`), the one place a fighter is
# written into: the dog's laugh is the side taunt, Wolf's howl his up taunt.
from fighter_port import fighters  # noqa: E402

TAUNT = fighters.column('taunt')
TAUNT_ACTION = 'Appeal'


def taunt_row(table, fighter, stems):
    """The table with the taunt's row on the fighter's own choice of clip (`TAUNT`), when it has that clip."""
    stem = next((s for s in stems if s[3:] == TAUNT.get(fighter)), None)
    if not stem:
        return table
    rows = [r for rs in table.values() for r in rs if r['target_motion'] == TAUNT_ACTION]
    for key in list(table):
        table[key] = [r for r in table[key] if r['target_motion'] != TAUNT_ACTION]
        if not table[key]:
            del table[key]
    table.setdefault(stem, []).append(dict(rows[0]) if rows else {'target_motion': TAUNT_ACTION, 'category': 'normal',
                                                                  'body_scale': 'rigid', 'root_motion_joint': 'Trans'})
    return table


# ----------------------------------------------------------------------- spec
def play_on(keys, rates, length):
    """Time keys that stop before their clip does, closed at the clip's last frame: it plays on at the speed its
    script last set (`rates`: the script's speed changes, a rate being game frames to one frame of the clip)."""
    frame, at = keys[-1]
    if at >= float(length) - 1e-6:
        return keys
    rate = next((float(r['rate']) for r in reversed(rates)
                 if isinstance(r.get('rate'), (int, float)) and not isinstance(r.get('rate'), bool) and r['rate'] > 0), 1.0)
    return keys + [[int(frame + math.ceil((float(length) - at) * rate - 1e-4)), float(length)]]


def to_cancel(keys, rates, cancel, length):
    """Time keys carried on to the frame before the fighter may act (`cancel`, the script's frame), at the speed in
    force there, when the reader's stop short of it. The reader's keys stop there (141 of Incineroar's 143 scripts);
    a script that changes its speed again after that frame stops them at the change before it instead: his side
    special's at frame 41 (clip frame 43) of the game's 58, from 42 at 0.8 and from 66 at 1, and the clip was cut
    there. A rate is frames of play to one of the clip; its `real` frame is the frame of play after the key's."""
    frame, at = keys[-1]
    until = int(cancel) - 1
    if frame >= until or at >= float(length) - 1e-6:
        return keys
    rate = 1.0
    for r in sorted((r for r in rates or [] if isinstance(r.get('rate'), (int, float))
                     and not isinstance(r.get('rate'), bool) and r['rate'] > 0 and isinstance(r.get('real'), (int, float))),
                    key=lambda r: r['real']):
        if r['real'] <= frame + 1:
            rate = float(r['rate'])
    t = at + (until - frame) / rate
    if t >= float(length) - 1e-6:
        return keys + [[int(frame + math.ceil((float(length) - at) * rate - 1e-4)), float(length)]]
    return keys + [[until, round(t, 4)]]


def rate_once(move):
    """A script that sets its clip's speed once, on its first frame, and never says when the fighter may act: the
    reader's time keys are only [0, 0] (no change of speed comes after a frame), so the speed is in its rates alone."""
    keys = (move or {}).get('time_keys') or []
    return len(keys) == 1 and any(isinstance(r.get('rate'), (int, float)) and not isinstance(r.get('rate'), bool)
                                  and r['rate'] > 0 and abs(float(r['rate']) - 1.0) > 1e-6
                                  for r in (move or {}).get('motion_rates') or [])


def weapon_for(script, by_script):
    """The held weapon a script uses: its own, else that of the move it continues
    (attacks4charge after attacks4) or begins (specialn before specialnstart)."""
    if script in by_script:
        return by_script[script]
    if script.startswith('game_landingair') and 'game_attackair' + script[len('game_landingair'):] in by_script:
        return by_script['game_attackair' + script[len('game_landingair'):]]     # still in the hand as it lands
    before = [s for s in by_script if script.startswith(s)]
    if before:
        return by_script[max(before, key=len)]
    after = [s for s in by_script if s.startswith(script)]
    return by_script[min(after, key=len)] if after else None


def forward_hold(S, skel, anim_path):
    """The hold bone further forward of the fighter halfway through a clip: the hand
    that holds a bow out, not the one that draws it."""
    import numpy as np
    from fighter_port.chain_weapon import _matrix
    names = [b.name for b in skel.bones]
    tracks = {n.name: n.tracks[0].values for g in S.anim_data.read_anim(str(anim_path)).groups
              if 'Transform' in str(g.group_type) for n in g.nodes}
    frame = max(len(v) for v in tracks.values()) // 2 if tracks else 0
    by_name = {b.name: b for b in skel.bones}

    def world(name):
        b, v = by_name[name], tracks.get(name)
        local = _matrix(v[min(frame, len(v) - 1)]) if v else np.array(b.transform, float).T
        return world(names[b.parent_index]) @ local if b.parent_index is not None else local

    ahead = {h: float(world(h)[2, 3]) for h in ('HaveL', 'HaveR') if h in by_name}
    return max(ahead, key=ahead.get) if ahead else None


def cut_keys(keys, until):
    """Time keys ([[clip frame, source time], ...]) that stop where the source reaches `until`."""
    out = [list(keys[0])]
    for (f0, t0), (f1, t1) in zip(keys, keys[1:]):
        if t1 >= until:
            out.append([int(round(f0 + (f1 - f0) * (until - t0) / (t1 - t0))) if t1 > t0 else f1, float(until)])
            return out
        out.append([f1, t1])
    return out


def part_starts(parts):
    """The clip frame each part of a joined clip starts on (a part ends the frame before the next begins)."""
    starts, at = [], 0
    for q in parts:
        starts.append(at)
        at += q['time_keys'][-1][0]
    return starts


# where a landmark stands when the body has no bone for it: the landmark next to it up the chain
LANDMARK_UP = {'spine': 'pelvis', 'chest': 'spine', 'neck': 'chest', 'l_collar': 'chest', 'r_collar': 'chest'}


def stand_in_landmarks(landmarks, bones, log=print):
    """A body with fewer bones in its spine or shoulders than Ultimate's (Slap City's Ittle Dew: one spine bone, no
    neck, no collar bones) has each such landmark stand at the nearest one up the chain that it has (LANDMARK_UP).
    -> the landmarks, changed in place; the others are left for the caller to refuse."""
    for mark in LANDMARK_UP:
        up = mark
        while landmarks.get(up) not in bones and up in LANDMARK_UP:
            up = LANDMARK_UP[up]
        if landmarks.get(mark) not in bones and landmarks.get(up) in bones:
            log(f'landmark {mark}: no {landmarks[mark]}; stands at {landmarks[up]} ({up})')
            landmarks[mark] = landmarks[up]
    return landmarks


def build_spec(fighter, donor, root, donor_pl, game, work, by_script=None, chain_stems=None, holds=None, rig_json=None,
               chain_runs=None, more_rows=None, preferred_rows=None):
    """`more_rows` {clip name: donor action, or several}: rows the table has none for, added as common actions (a
    fighter on its own skeleton fills actions a port on the donor's leaves to the donor's own clips)."""
    from vault.echo.subactions import FighterDat
    S = ssbh(root)
    src = Path(root) / 'gamedata' / 'fighter' / fighter
    motion = src / 'motion' / 'body' / 'c00'
    stems = sorted(p.stem for p in motion.glob('*.nuanmb'))
    skel = S.skel_data.read_skel(str(src / 'model' / 'body' / 'c00' / 'model.nusktb'))
    bones = [b.name for b in skel.bones]
    parents = {b.name: (bones[b.parent_index] if b.parent_index is not None else None) for b in skel.bones}
    from fighter_port.rigmap import Rig
    donor_rig = Rig(rig_json) if rig_json else None
    landmarks = json.loads((RECIPES / 'ultimate_landmarks.json').read_text('utf-8'))
    stand_in_landmarks(landmarks, bones, log)
    missing = [v for v in landmarks.values() if v not in bones]
    if missing:
        raise ValueError(f'{fighter} lacks the landmark bones {missing}; it needs its own landmark map')
    weapon = next((w for w in WEAPON_SOURCES if w[0] in bones and w[1] in bones), None)
    attachments = [{'source': weapon[0], 'source_anchor': weapon[1], **WEAPON[donor]}] if weapon and donor in WEAPON else []

    actions = FighterDat(Path(donor_pl).read_bytes()).actions
    flagged = {a.motion for a in actions if a.motion and a.flags & MOVES_BY_CLIP}
    travels = []
    by_motion = {}
    for a in actions:
        if a.motion and a.symbol:
            by_motion.setdefault(a.motion, set()).add(a.symbol)
    table = taunt_row(motion_table(), fighter, stems)
    moves = game['moves']
    specials, chosen = special_rows(donor, fighter, {s[3:] for s in stems}, moves)
    from fighter_port import own as own_states
    mine = {k: v for k, v in own_states.CLIPS.get(fighter, {}).items() if k in {s[3:] for s in stems}}
    with_own(specials, mine)                            # clips of states of the port's own, on donor actions it leaves free
    if chosen:
        log('specials:', chosen)
    if mine:
        log('own states: clips', {k: (v if isinstance(v, str) else v['motion']) for k, v in mine.items()})
    for stem in stems:
        extra = EXTRA_ACTION.get(stem[3:])
        if extra and extra[1] in by_motion and script_for(stem, moves) in moves:
            table[stem] = [{'target_motion': extra[1], 'category': 'normal', 'body_scale': 'rigid'}]
        if stem[3:] in specials:
            table.pop(stem, None)                       # the specials rules are the word on their clips
        for extra, category in ((DONOR_ROWS.get(donor, {}), 'normal'), (specials, 'special'),
                                (more_rows or {}, 'native_supplement')):
            entries = extra.get(stem[3:]) or []
            for entry in ([entries] if isinstance(entries, (str, tuple, dict)) else entries):
                join = entry if isinstance(entry, dict) and 'then' in entry else None
                later = entry if isinstance(entry, dict) and 'from' in entry else None
                target, span = ((entry['motion'], None) if isinstance(entry, dict)
                                else (entry, None) if isinstance(entry, str) else entry)
                if not any(r['target_motion'] == target for r in table.get(stem, [])):
                    row = {'target_motion': target, 'category': category, 'body_scale': 'rigid',
                           'root_motion_joint': 'Trans'}
                    if span:
                        row['span'] = list(span)
                    if join:
                        row['join'] = join
                    if later:
                        row['from'] = int(later['from'])
                    if isinstance(entry, dict) and 'strike' in entry:
                        row['strike'] = int(entry['strike'])       # its script's throw is a plain hit here
                    if isinstance(entry, dict) and 'holds' in entry:
                        row['holds'] = entry['holds']
                    if (target in RISE_DONOR.get(donor, {}).get('actions', ())
                            and leaves_ground(S, motion / f'{stem}.nuanmb', None, 10 ** 4) is not None):
                        # this donor state moves the fighter by its clip's root, and the clip rises: its travel goes to the engine
                        row['engine_root'] = {'target': RISE_DONOR[donor]['root'], 'basis': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
                    table.setdefault(stem, []).append(row)
    if preferred_rows:
        from .own_action_slots import reserve
        reserve(table,preferred_rows,stems)
    clips, used, skipped = [], {}, []
    for stem in stems:
        for row in table.get(stem, []):
            target = row['target_motion']
            symbols = by_motion.get(target)
            if not symbols:
                skipped.append((stem, target, 'donor has no such action'))
                continue
            if len(symbols) > 1:
                skipped.append((stem, target, 'donor action name is shared by several animations'))
                continue
            symbol = next(iter(symbols))
            if symbol in used:
                skipped.append((stem, target, f'already filled by {used[symbol]}'))
                continue
            used[symbol] = stem
            clip = {'id': f'{stem}-{target}'.lower(), 'source': f'motion/body/c00/{stem}.nuanmb', **row}
            clip.setdefault('body_scale', 'rigid')
            m = moves.get(script_for(stem, moves))
            join = clip.pop('join', None)
            if join:
                # several of the game's clips, one after another: each plays at the game's own speed for it
                parts = []
                for k, part in enumerate([stem] + [stem[:3] + t for t in join['then']]):
                    pm = moves.get(script_for(part, moves)) or {}
                    length = float(S.anim_data.read_anim(str(motion / f'{part}.nuanmb')).final_frame_index)
                    keys = pm['time_keys'] if pm.get('time_keys') and len(pm['time_keys']) > 1 else None
                    if keys is None:
                        rate = next((r['rate'] for r in pm.get('motion_rates', [])
                                     if r['real'] <= 1 and isinstance(r['rate'], (int, float)) and r['rate'] > 0), 1.0)
                        keys = [[0, 0.0], [max(1, round(length * rate)), length]]
                    if k == 0 and join.get('until') is not None:
                        keys = cut_keys(keys, float(join['until']))
                    if k and join.get('hold') and part == stem[:3] + join['then'][-1]:
                        keys = [[0, 0.0], [int(join['hold']), length]]      # a pose, held that long
                    parts.append({'source': f'motion/body/c00/{part}.nuanmb', 'stem': part, 'time_keys': keys})
                clip['parts'] = parts
            elif clip.get('span'):                      # a stretch of the source clip, frame for frame
                first, last = clip.pop('span')
                clip['time_keys'] = [[0, float(first)], [int(last - first), float(last)]]
                clip['window'] = [int(first), int(last)]
            elif clip.get('from'):                      # the clip from a later game frame on, at the game's own speed
                length = float(S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).final_frame_index)
                keys = m['time_keys'] if m and m.get('time_keys') and len(m['time_keys']) > 1 else [[0, 0.0], [int(length), length]]
                f0 = clip.pop('from')
                clip['time_keys'] = [[0, source_time(keys, f0)]] + [[f - f0, t] for f, t in keys if f > f0]
                clip['window'] = [int(f0), None]
                clip['offset'] = -int(f0)               # its script's frames come that much earlier
            elif target not in SHARED_END and m and m.get('time_keys') and (len(m['time_keys']) > 1 or rate_once(m)):
                # (an action whose end every fighter shares takes it from the shared table below even when the
                # fighter has a script of its own for it: Duck Hunt's shield drop script says 8, the game drops in 11)
                # (a script that sets its speed once, on its first frame, has only the key [0, 0]: Greninja's
                # specialnstart at 0.73 played frame for frame, 19 frames for the game's 14)
                clip['time_keys'] = [list(k) for k in m['time_keys']]
                if not m.get('cancel_frame_real'):
                    # A script that changes its clip's speed and never says when the fighter may act (the start of
                    # a special, which the next clip follows): the reader's keys stop at the last change of speed,
                    # and the clip plays on from there to its own end. (Found on Wolf: his reflector's opening was
                    # cut to 4 frames of 9 and the start of his side special to 7 of 17.)
                    length = float(S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).final_frame_index)
                    clip['time_keys'] = play_on(clip['time_keys'], m.get('motion_rates') or [], length)
                elif clip['time_keys'][-1][0] < int(m['cancel_frame_real']) - 1:
                    # the keys stop short of the frame he may act from (a change of speed after it): on to it
                    length = float(S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).final_frame_index)
                    clip['time_keys'] = to_cancel(clip['time_keys'], m.get('motion_rates') or [],
                                                  m['cancel_frame_real'], length)
                if m.get('cancel_frame_real') and any(target.startswith(n) for n in ACTS_EARLY):
                    # the keys stop where the fighter may act; this state lets it, and plays on otherwise
                    length = float(S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).final_frame_index)
                    clip['time_keys'], acts = with_ending(clip['time_keys'], length)
                    if acts:
                        clip['acts'] = acts
            elif clip.get('category') != 'special' or stem[3:] in mine:
                # no script of the fighter's own for this clip: the game's tables say when the fighter may act
                # (a special's clips are timed by its own rules; a clip of a state of the port's own ends there too:
                # the end of a charge, a weapon put away)
                ends = shared_end(game, stem, target)
                length = float(S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).final_frame_index)
                if ends and ends - 1 < length:
                    clip['time_keys'] = [[0, 0.0], [ends - 1, float(ends - 1)]]
                    if any(target.startswith(n) for n in ACTS_EARLY):
                        # a state that plays on when nothing is asked (a taunt): the clip goes to its end
                        clip['time_keys'], acts = with_ending(clip['time_keys'], length)
                        if acts:
                            clip['acts'] = acts
            # a move whose clip the bending weapon also has uses that weapon
            part_stems = [q['stem'] for q in clip.get('parts', [])] or [stem]
            run = (chain_runs or {}).get(stem)             # a bending weapon's clips found to play during this one
            if run and stem not in (chain_stems or {}) and not join:
                clip['chain_parts'] = [[w, first] for w, first in run[1]]
            said = clip.pop('holds', None)              # a clip of the port's own may say which weapon is in the hand
            held = ((run[0] if clip.get('chain_parts') else None)
                    or (chain_stems or {}).get(stem)
                    or next((w for w in (weapon_for(script_for(q, moves), by_script or {}) for q in part_stems) if w), None)
                    or (said if said in (holds or {}) else None))
            if len(part_stems) > 1:                     # the part with hitboxes says which hand, if any part does
                m = next((moves[script_for(q, moves)] for q in part_stems
                          if (moves.get(script_for(q, moves)) or {}).get('hitboxes')), m)
            # A weapon hangs on the body bone named like its own model's root (a lance on HaveR). A model rooted
            # on plain "Have" does not say which hand: then the move does, by a hold bone its hitboxes name. Failing
            # that, the fighter's own weapon in another form (a sword that becomes a whip: named as the body's own
            # weapon bone is) is in the hand its own is in; any other is in the hand that is held out. (Held-out
            # alone put Byleth's whip in the left hand, which is forward while the right draws back to throw: the
            # whip then flew up and behind.)
            named = (holds or {}).get(held)
            hold = named if named in bones else 'HaveR'          # the bone the weapon's model is built against
            hand = hold
            if held and named not in bones:
                said = [str(h.get('bone')).lower() for h in (m or {}).get('hitboxes', []) if str(h.get('bone')).lower() in ('haver', 'havel')]
                same = bool(weapon) and held.lower().rstrip('0123456789') == weapon[0].lower().rstrip('0123456789r')
                own = next((b for b in ('HaveR', 'HaveL') if same and b in bones and parents.get(b) == weapon[1]), None)
                hand = ({'haver': 'HaveR', 'havel': 'HaveL'}[max(set(said), key=said.count)] if said
                        else own or forward_hold(S, skel, motion / f'{stem}.nuanmb') or hold)
            if held and donor in WEAPON and hand in bones and parents.get(hand):
                # this move holds another weapon: the donor's weapon joint follows the hold bone, not the sword
                clip['weapon'] = held
                clip['attachments'] = [{'source': hand, 'source_anchor': parents[hand], **WEAPON[donor]}]
                other = donor_rig.landmarks.get('l_wrist' if hand.endswith('L') else 'r_wrist') if donor_rig else None
                if hand != hold and other:              # in the other hand: carried there, turned as it was built
                    clip['attachments'][0].update(target_anchor=other, carry=hold)
            if donor in HELD and all(b in bones for b in HELD_SOURCE) and any(target.startswith(n) for n in HOLDS):
                # an action that holds a fighter: the donor joint it hangs from follows the game's own bone for it
                clip['attachments'] = list(clip.get('attachments') or attachments) + [
                    {'source': HELD_SOURCE[0], 'source_anchor': HELD_SOURCE[1], **HELD[donor]}]
            # a clip whose root travels: the fighter has to go with it
            if not clip.get('engine_root') and not clip.get('parts'):
                far = clip_travel(S, motion / f'{stem}.nuanmb', clip.get('time_keys'))
                route = travel_route(target, clip.get('category'), donor, flagged) if far and max(far[0], far[2]) >= TRAVEL else None
                if route == 'code' and far[0] < TRAVEL:
                    route = None                        # the code file moves along the ground only
                if route:
                    clip['root_motion_joint'] = 'Trans'
                    clip['engine_root'] = {'target': TRAVEL_ROOT[donor], 'basis': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
                    clip['travel'] = route
                if far and max(far[0], far[2]) >= TRAVEL and clip.get('category') != 'locomotion':
                    travels.append((target, route or ('dropped' if clip.get('root_motion_joint') else 'in the picture'),
                                    round(far[0], 1), round(far[1], 1), round(far[2], 1), round(far[3], 1)))
            clips.append(clip)
    if travels:
        by = {}
        for t in travels:
            by.setdefault(t[1], []).append(f'{t[0]} {t[2]:g}' + (f' up {t[4]:g}' if t[4] >= TRAVEL else ''))
        for how, names in sorted(by.items()):
            log(f"travel ({how}):", ', '.join(names))
    (Path(work) / 'spec').mkdir(parents=True, exist_ok=True)
    (Path(work) / 'spec' / 'travel.json').write_text(json.dumps(travels, indent=1), 'utf-8')
    # tracks for bones the skeleton does not have would stop a clip; name them up front
    unbound = set()
    for stem in {c['source'].rsplit('/', 1)[1][:-7] for c in clips}:
        for g in S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).groups:
            if 'Transform' in str(g.group_type):
                unbound |= {n.name for n in g.nodes if n.name not in bones}
    # how long a clip lasts: see PLAYS_WHOLE
    loops = {x.motion for x in FighterDat(Path(donor_pl).read_bytes()).actions if x.motion and (x.flags or 0) & LOOPS}
    # (a donor action that holds the clip of one of the port's own states is entered by the port's code, with the step)
    stepped = {v if isinstance(v, str) else v['motion'] for v in own_states.CLIPS.get(fighter, {}).values()}
    for c in clips:
        motion_ = c.get('target_motion')
        if not c.get('blocked') and motion_ not in loops and (motion_ in stepped or lasts_its_keys(motion_, loops, donor)):
            c['hold_end'] = True
    spec = {'schema': 1, 'skeleton': 'model/body/c00/model.nusktb', 'landmarks': 'landmarks.json',
            'allow_unbound': sorted(unbound), 'attachments': attachments, 'clips': clips}
    d = Path(work) / 'spec'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'landmarks.json').write_text(json.dumps(landmarks, indent=1), 'utf-8')
    (d / 'moveset.json').write_text(json.dumps(spec, indent=1), 'utf-8')
    (d / 'skipped.json').write_text(json.dumps(skipped, indent=1), 'utf-8')
    log(f'spec: {len(clips)} clips on {len(used)} donor animations; {sum(1 for c in clips if "time_keys" in c)} timed '
        f'from game data; {len(skipped)} rows skipped; weapon {attachments or "none"}; unbound tracks {sorted(unbound)}')
    return d / 'moveset.json', src


# -------------------------------------------------------------------- scripts
def donor_joint(rig, name):
    return int(name.split('_')[1])


def stature(rig_json):
    """Height of the head joint above the root in a rig JSON's rest pose (translations only matter here)."""
    import numpy as np
    from fighter_port.rigmap import Rig
    r = Rig(rig_json)
    w = r.rest_world() if hasattr(r, 'rest_world') else None
    if w is None:
        return None
    return float(np.asarray(w[r.landmarks['head']])[1, 3])


def source_time(keys, frame):
    """Ultimate animation time shown on clip frame `frame` (time keys are piecewise linear)."""
    if not keys:
        return float(frame)
    for (f0, t0), (f1, t1) in zip(keys, keys[1:]):
        if frame <= f1:
            return t0 + (t1 - t0) * (frame - f0) / (f1 - f0) if f1 > f0 else t1
    return float(keys[-1][1])


class Placer:
    """Where a hitbox scripted on an Ultimate bone sits on the donor's joints.

    A hitbox is a point fixed in one Ultimate bone's own axes. The donor's joints
    have other axes, and some bones (the hold bone a lance sits in) have no donor
    joint at all, so the numbers cannot be copied. Instead the point is followed
    through the fighter's own animation, measured from the nearest body landmark
    above it (the hand for anything held), carried across the way the retarget
    carries the body (same rotation and scale), and written in the axes of
    whichever donor joint it stays most still in: that landmark's joint, or the
    donor's weapon joint when the landmark is the weapon's hand."""

    def __init__(self, clips_dir, donor_rig_json, donor):
        from fighter_port.rigmap import Rig
        self.dir, self.target, self.donor, self.cache = Path(clips_dir), Rig(donor_rig_json), donor, {}

    def _clip(self, clip_id):
        if clip_id not in self.cache:
            import numpy as np
            from fighter_port.evaluation import Animation
            from fighter_port.rigmap import Rig
            d = self.dir / clip_id
            report = json.loads((d / 'transfer.json').read_text('utf-8'))
            self.cache[clip_id] = (Rig(d / 'decoded' / 'source.joints.json'), Animation(d / 'decoded' / 'source.anim'),
                                   Animation(d / 'full.anim'), np.array(report['basis'], float), float(report['scale']))
        return self.cache[clip_id]

    def scale(self, clip_id):
        return self._clip(clip_id)[4]

    def heading(self, clip_id, keys, start, end):
        """Which way the fighter itself is going over clip frames start..end, as a launch angle (0 ahead,
        90 up), or None when its root goes nowhere to speak of."""
        import math
        src, sanim, tanim, B, scale = self._clip(clip_id)
        root = next((n for n in src.order if n == 'Trans'), None)
        if root is None:
            return None
        clamp = lambda g: min(max(source_time(keys, g), sanim.start), sanim.end)
        a = sanim.world(src, clamp(max(start - 2, 0)))[root][:3, 3]
        b = sanim.world(src, clamp(end))[root][:3, 3]
        ahead, up = float(b[2] - a[2]), float(b[1] - a[1])
        if math.hypot(ahead, up) < 0.5:
            return None
        return int(round(math.degrees(math.atan2(up, ahead)))) % 360

    def place(self, clip_id, bone, offset, frames, keys):
        """-> (donor joint index, [x, y, z], how far the point drifts in that joint over `frames`), or None."""
        import numpy as np
        from fighter_port.smpl_to_anim import orthonormalize
        src, sanim, tanim, B, scale = self._clip(clip_id)
        S = {n.lower(): n for n in src.order}.get(bone)
        if S is None:
            return None
        landmark_of = {j: lm for lm, j in src.landmarks.items()}
        anchor = next((j for j in src._ancestors(S) if landmark_of.get(j) in self.target.landmarks), None)
        if anchor is None:
            return None
        t_anchor = self.target.landmarks[landmark_of[anchor]]
        candidates = [t_anchor]
        weapon = WEAPON.get(self.donor)
        if weapon and weapon['target_anchor'] == t_anchor and S != anchor:
            candidates.append(weapon['target'])
        seen = {c: [] for c in candidates}
        for g in frames:
            s = min(max(source_time(keys, g - 1), sanim.start, tanim.start), sanim.end, tanim.end)
            sw, tw = sanim.world(src, s), tanim.world(self.target, s)
            point = sw[S][:3, 3] + sw[S][:3, :3] @ np.asarray(offset, float)
            there = tw[t_anchor][:3, 3] + scale * (B @ (point - sw[anchor][:3, 3]))
            for c in candidates:
                seen[c].append(orthonormalize(tw[c][:3, :3]).T @ (there - tw[c][:3, 3]))

        def drift(c):
            a = np.array(seen[c])
            return float(np.linalg.norm(a - a.mean(axis=0), axis=1).max())

        # the joint the point stays most still in; where that does not tell (a hitbox out for one frame is still
        # in every joint) the joint it is nearest to: a point far out from a fast-moving joint lands somewhere
        # else if the frame is one off, and a sword thrown from the hand is fifty units from the hand
        reach = lambda c: float(np.linalg.norm(np.array(seen[c]).mean(axis=0)))
        least = min(drift(c) for c in candidates)
        best = min((c for c in candidates if drift(c) <= least + 0.05), key=reach)
        return int(best.split('_')[1]), [float(v) for v in np.array(seen[best]).mean(axis=0)], drift(best)


def stretches(hbs, total):
    """A move's hitboxes (the reader's, with first and last frames) cut wherever the set of them changes: each
    stretch holds the hitboxes that are out on it. -> [(start, end, hitboxes, continues)]

    `continues`: the stretch is the same attack as the one before it (the game's `run`: some hitbox stayed out),
    so what the early hit struck the late hit does not strike again. A hitbox with a re-hit timer strikes again
    every so many frames: the move is cut there too, and the stretch that starts there does not continue."""
    again = set()
    for h in hbs:
        every = h.get('rehit')
        if isinstance(every, (int, float)) and not isinstance(every, bool) and every >= 1:
            last = h['last'] if isinstance(h.get('last'), int) else total
            again |= set(range(h['first'] + int(every), last + 1, int(every)))
    points = sorted({h['first'] for h in hbs} | {h['last'] + 1 for h in hbs if isinstance(h.get('last'), int)} | again)
    out, run_before = [], None
    for i, start in enumerate(points):
        group = [h for h in hbs if h['first'] <= start and (not isinstance(h.get('last'), int) or h['last'] >= start)]
        group = list({h.get('id'): h for h in group}.values())          # one hitbox to a game id: the last made
        end = min(points[i + 1] - 1 if i + 1 < len(points) else total, total)
        if not group or start > total or end < start:
            continue
        run = group[0].get('run')
        continues = (bool(out) and run is not None and run == run_before and out[-1][1] == start - 1
                     and start not in again)
        out.append((start, end, group, continues))
        run_before = run
    return out


def own_tables(root):
    """{special: {name or the file's own key: value}}: the first row of each of a fighter's own special tables."""
    out = {}
    for key, name in OWN_TABLES.items():
        rows = root.get(name)
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        if row:
            out[key] = {str(k): v for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return out


def own_parameters(root):
    """What a fighter's own parameter file says its code does, as far as names resolve.
    -> (start: {special: speed upward it starts with in the air}, boost: {MexTK field: times})

    `boost` is from a table whose rows each name one of a fighter's numbers and carry one column that is
    neither all 0 nor all 1: what that number is multiplied by in a state of the fighter's (a full gauge)."""
    start, boost = {}, {}
    for key, name in OWN_TABLES.items():
        rows = root.get(name)
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        v = (row or {}).get(START_Y)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            start[key] = float(v)
    for rows in root.values():
        if not (isinstance(rows, list) and len(rows) >= 4 and all(isinstance(r, dict) for r in rows)):
            continue
        # (a name the file gives is its own kind of value, not text: it is read as text here)
        named = [next((str(v) for v in r.values() if not isinstance(v, (int, float, bool)) and str(v) in BOOST_FIELD), None)
                 for r in rows]
        if sum(1 for n in named if n) < 4:
            continue
        columns = [k for k, v in rows[0].items() if isinstance(v, float)
                   and any(isinstance(r.get(k), float) and r[k] not in (0.0, 1.0) for r in rows)]
        if len(columns) != 1:
            continue
        for r, n in zip(rows, named):
            if n and isinstance(r.get(columns[0]), float) and r[columns[0]] > 0:
                boost[BOOST_FIELD[n]] = round(float(r[columns[0]]), 4)
    return start, boost


def stretch_of(h):
    """How far a hitbox is drawn out: the game makes many of its hitboxes a line with a radius (a blade's edge,
    a lance's shaft) by giving a second point. 0 for a plain ball."""
    ends = [h.get(k) for k in ('x', 'y', 'z', 'x2', 'y2', 'z2')]
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in ends):
        return 0.0
    return math.dist(ends[:3], ends[3:])


SAID_OF_A_HIT = ('bone', 'damage', 'angle', 'kbg', 'bkb', 'fkb', 'targets', 'part', 'effect', 'sfx_level', 'sfx_type',
                 'shield_damage', 'clang', 'facing', 'ignore_throw')


def joined(hbs, room=4, slack=1.0):
    """A move's hitboxes when it has more than Melee holds (`room`): a row of plain balls on one bone that say
    the same of a hit, each touching the next (the game's way of covering a blade or a shaft), is made one
    hitbox drawn out from the row's first ball to its last; the longest rows first, until they fit. (Before,
    the weakest were dropped: a lance kept its tip and lost the middle of its shaft.)"""
    hbs = list(hbs)
    at = lambda h: (float(h['x']), float(h['y']), float(h['z']))
    while len(hbs) > room:
        rows = {}
        for h in hbs:
            if stretch_of(h) < 0.01 and not h.get('catch_only'):
                rows.setdefault(tuple(str(h.get(k)) for k in SAID_OF_A_HIT), []).append(h)
        best = None
        for row in rows.values():
            if len(row) < 2:
                continue
            a, b = max(((p, q) for p in row for q in row), key=lambda pq: math.dist(at(pq[0]), at(pq[1])))
            along = sorted(row, key=lambda h: math.dist(at(a), at(h)))
            if any(math.dist(at(p), at(q)) > float(p['size']) + float(q['size']) + slack for p, q in zip(along, along[1:])):
                continue                                # not a row: balls apart from each other (one each side)
            if best is None or len(along) > len(best):
                best = along
        if best is None:
            break
        first, last = best[0], best[-1]
        one = dict(min(best, key=lambda h: h['id'] if isinstance(h.get('id'), int) else 99),
                   x=first['x'], y=first['y'], z=first['z'], x2=last['x'], y2=last['y'], z2=last['z'],
                   size=max(float(h['size']) for h in best))
        hbs = [h for h in hbs if not any(h is r for r in best)] + [one]
    return hbs


def balls(lengths, room=4, least=0.25):
    """How many of Melee's hitboxes (balls: it has `room` of them) each hitbox of a move gets, from how far
    each is drawn out: one each, and what is left over goes one at a time to the hitbox left worst off (see
    `ball_points`), while that still gains `least` of the game's units."""
    counts = [1] * len(lengths)
    for _ in range(max(0, room - len(lengths))):
        gain = [L / (4 * k) - L / (4 * (k + 1)) for L, k in zip(lengths, counts)]
        best = max(range(len(gain)), key=lambda i: gain[i], default=None)
        if best is None or gain[best] < least:
            break
        counts[best] += 1
    return counts


def ball_points(h, count):
    """A hitbox as `count` balls: [(point, radius)]. A plain ball is itself. One drawn out along a line is cut
    into `count` equal shares, each with a ball a quarter of a share wider than the game's radius. Melee has
    balls only, so something gives: the balls are set so that the line's far end (the one further from its
    bone: a weapon's tip, a swing's outer reach) is covered exactly as the game has it; each ball is a quarter
    of a share wide at the line's sides, and the near end falls half a share short (where the fighter's other
    hitboxes usually are). (The first ports wrote one ball at the line's first end, whichever end that was: a
    down smash's back hit missed a target standing close behind. Splitting the shortfall evenly between the
    two ends was tried and cost a forward smash its outer reach.)"""
    a = [float(h['x']), float(h['y']), float(h['z'])]
    far = stretch_of(h)
    if far < 0.01:
        return [(a, float(h['size']))]
    b = [float(h['x2']), float(h['y2']), float(h['z2'])]
    if math.hypot(*a) < math.hypot(*b):
        a, b = b, a                                     # a: the far end
    return [([p + (q - p) * (i + 0.25) / count for p, q in zip(a, b)], float(h['size']) + far / count / 4)
            for i in range(count)]


def combat_spec(game, table, donor, rig_json, scale, installed, placer=None, tips=None):
    """Combat profiles (fighter_port.combat schema) from the game's hitbox timelines.
    `table` rows carry the clip id and time keys of each donor action; `placer`
    (a Placer) puts hitboxes that are not on the fighter's base point."""
    from fighter_port.rigmap import Rig
    rig = Rig(rig_json)
    weapon_joint = donor_joint(rig, WEAPON[donor]['target']) if donor in WEAPON else None
    profiles, notes = [], []
    # a row may name its script itself (a second version of a move: `alternates`); it then also brings
    # `to_clip`, which turns that script's frames into frames of the clip as it was carried
    of = lambda stem, r: r.get('script') or script_for(stem, game['moves'])
    played = {of(stem, r) for stem, rows_ in table.items() for r in rows_}
    for script, m in sorted(game['moves'].items()):
        # a second script under one name plays the first one's clip, on the donor's second action for it
        base = script[:-len(SECOND)] if script.endswith(SECOND) else script
        if not base.startswith('game_') and base not in played:
            continue                                    # a script whose name did not resolve counts when a carried clip plays it
        rows = [r for stem, rows_ in table.items() for r in rows_ if of(stem, r) == base]
        rows = [r for r in rows if r['target_motion'] in installed]
        hit_frames = [h['first'] for h in m['hitboxes'] if isinstance(h.get('first'), int) and h.get('damage') != 0]
        if hit_frames and any(r.get('window') for r in rows):
            # one game clip cut over several donor actions: the hits go on the stretch that holds the first of them
            holds = [r for r in rows if not r.get('window') or
                     (r['window'][0] <= min(hit_frames) and (r['window'][1] is None or min(hit_frames) <= r['window'][1]))]
            rows = holds or rows
        targets = list(dict.fromkeys(r['target_motion'] for r in rows))
        if not targets:
            continue
        clip_id, keys = rows[0].get('id'), rows[0].get('time_keys')
        if placer is not None and clip_id:
            scale = placer.scale(clip_id)          # the scale this clip was carried across with
        hbs = [h for h in m['hitboxes'] if isinstance(h.get('first'), int)]
        # a hitbox made and made again on the same frame (a script that writes both sides of a choice) was
        # never out: only the one that stayed counts
        both = [h for h in hbs if isinstance(h.get('last'), int) and h['last'] < h['first']]
        if both:
            # (said: Greninja's Substitute strike holds five, one for each way the stick is held, and nothing said
            # the driver had kept only the last)
            notes.append(f'{script}: alternatives: {len(both)} hitboxes made and made again on the same frame, a choice '
                         "the game's code makes (one for each way, a level ...); only the one that stays is written: "
                         'carry the others in the module (SPECIALS.md, "A script that holds alternatives")')
        hbs = [h for h in hbs if h not in both]
        if any(h.get('damage') == 0 for h in hbs):
            # a box with no damage is the game looking for something (a reflector, a wind box): not a hit here
            notes.append(f'{script}: {sum(1 for h in hbs if h.get("damage") == 0)} hitboxes that do no damage left out')
            hbs = [h for h in hbs if h.get('damage') != 0]
        shift = rows[0].get('offset') or 0              # this script's part starts that far into a joined clip
        to_clip = rows[0].get('to_clip')
        if to_clip:
            hbs = [dict(h, first=to_clip(h['first']),
                        last=max(to_clip(h['last']), to_clip(h['first'])) if isinstance(h.get('last'), int) else h.get('last'))
                   for h in hbs]
        elif shift:
            hbs = [dict(h, first=h['first'] + shift, last=h['last'] + shift if isinstance(h.get('last'), int) else h.get('last'))
                   for h in hbs]
        throw = None
        abs_ = [o for o in m['other'] if o['cmd'] == 'ATTACK_ABS' and len(o['args']) >= 7]
        hit = [o for o in m['other'] if o['cmd'] == 'ATK_HIT_ABS']
        if abs_ and hit and all(isinstance(abs_[0]['args'][i], (int, float)) for i in (2, 3, 4, 6)):
            a = abs_[0]['args']
            # the game's own damage, none included: a throw of 0% leaves its damage to a hit for the held fighter
            # (Incineroar's back throw: 0% at 47, and 14% from a `catch_only` box), and 1% would be added to it
            throw = {'damage': max(0, round(a[2])), 'angle': int(a[3]), 'kbg': int(a[4]), 'bkb': int(a[6]),
                     'release': int(hit[0]['real'])}
        if not hbs and not throw:
            continue
        total = installed[targets[0]]
        if rows[0].get('acts'):
            total = min(total, int(rows[0]['acts']))    # the clip plays on past the frame the fighter may act on
        phases = []
        # The move is cut wherever its set of hitboxes changes (one is made, one ends); each stretch holds the
        # hitboxes that are out on it. A stretch of the same attack as the one before (the game's `run`: some
        # hitbox stayed out) goes on from it, so a target struck by the early hit is not struck again by the
        # late one; Melee's four hitboxes are kept by the game's own id from stretch to stretch for that.
        if any(h['first'] > total for h in hbs):
            notes.append(f'{script}: hits from frame {min(h["first"] for h in hbs if h["first"] > total)} are past '
                         f'the clip ({total} frames); dropped')
        slots = {}
        for start, end, group, continues in stretches(hbs, total):
            continues = continues and bool(phases) and phases[-1]['end'] == start - 1
            if not continues:
                slots = {}
            kept = []
            for h in sorted(group, key=lambda h: (-(h.get('damage') or 0), h.get('id') or 0)):
                nums = [h.get(k) for k in ('damage', 'angle', 'kbg', 'bkb', 'size', 'x', 'y', 'z')]
                if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in nums):
                    notes.append(f'{script}: hitbox {h.get("id")} has a value set at run time; dropped')
                    continue
                kept.append(h)
            kept = sorted(joined(kept), key=lambda h: (-(h.get('damage') or 0), h.get('id') or 0))
            if len(kept) > 4:
                notes.append(f'{script}: {len(kept)} hitboxes at frame {start}; Melee holds 4, kept the strongest')
                kept = kept[:4]
            # The game's own order: where two hitboxes of a move reach a target at once the lower number strikes
            # (the dull part of a blade before its tip). Melee tries its four in order too.
            kept.sort(key=lambda h: h['id'] if isinstance(h.get('id'), int) else 99)
            whole = lambda h: h.get('catch_only') or (str(h.get('bone') or '').lower() == 'throw'
                                                      and (tips or {}).get(script) is not None)
            out = []
            for h, count in zip(kept, balls([0.0 if whole(h) else stretch_of(h) for h in kept])):
                bone = str(h.get('bone') or '').lower()
                for part, (point, size) in enumerate([([h['x'], h['y'], h['z']], h['size'])] if whole(h)
                                                     else ball_points(h, count)):
                    position = [v * scale for v in point]
                    if h.get('catch_only'):
                        # a hit for the held fighter and nobody else. Melee holds its victim in poses of the victim's
                        # own (made for the donor's throws), not where this fighter's animation strikes, so the hit
                        # is made wide enough to reach the held fighter wherever it is; it can strike no one else.
                        joint, position, size = 0, [0.0, 10.0 * scale, 6.0 * scale], HELD_REACH
                    elif bone == 'top':
                        joint = 0                  # the fighter's base point: same axes in both games
                    elif bone == 'throw' and (tips or {}).get(script) is not None:
                        joint, position = tips[script], [0.0, 0.0, 0.0]     # the end of a thrown whip: its last joint
                    elif placer is not None and clip_id:
                        window = sorted({int(start), int((start + end) // 2), int(end)})
                        placed = placer.place(clip_id, bone, list(point), window, keys)
                        if placed is None:
                            notes.append(f'{script}: hitbox on bone {h.get("bone")!r} has no donor joint; dropped')
                            continue
                        joint, position, drift = placed
                        if drift > 1.0 and part == 0:
                            notes.append(f'{script}: hitbox on {bone} drifts {drift:.1f} units in donor joint {joint} '
                                         f'over frames {start}-{end}; its average place is used')
                    elif bone in WEAPON_BONES and weapon_joint is not None:
                        joint = weapon_joint
                    elif bone in BONE_LANDMARK and BONE_LANDMARK[bone] in rig.landmarks:
                        joint = donor_joint(rig, rig.landmarks[BONE_LANDMARK[bone]])
                    else:
                        notes.append(f'{script}: hitbox on bone {h.get("bone")!r} has no donor joint; dropped')
                        continue
                    angle = int(h['angle'])
                    if angle > 361:
                        # Ultimate's own rule for a hit that must lead into the next: the target goes the way the
                        # attacker is going. Melee has no such angle, so the way the fighter moves on those frames is
                        # written; a fighter that is standing still sends it up and a little ahead.
                        going = placer.heading(clip_id, keys, start, end) if placer is not None and clip_id else None
                        if part == 0:
                            notes.append(f'{script}: angle {angle} (an Ultimate-only launch rule) written as '
                                         + (f'{going}, the way the fighter is going' if going is not None else '80'))
                        angle = going if going is not None else 80
                    hb = {'bone': joint, 'position': position,
                          'radius': max(0.1, size * scale), 'damage': max(1, int(h['damage'] + 0.5)),
                          'angle': angle, 'kbg': int(h['kbg']), 'bkb': int(h['bkb']),
                          'element': ELEMENT.get(str(h.get('effect')), 0)}
                    if h.get('targets') == 'ground':
                        hb['aerial'] = False                # a hit for standing targets only
                    elif h.get('targets') == 'air':
                        hb['grounded'] = False              # for airborne targets only (a meteor's twin strikes the rest)
                    if h.get('catch_only'):
                        hb['grabbed_only'] = True           # for the fighter this one is holding and nobody else
                    if h.get('ignore_throw'):
                        hb['ignore_thrown'] = True          # for anyone but the fighter being thrown (Melee has the mark)
                    # the sound of the hit: how hard, and what with
                    if str(h.get('sfx_level')) in SOUND_LEVEL:
                        hb['sound_level'] = SOUND_LEVEL[str(h['sfx_level'])]
                    if h.get('sfx_type') is not None:
                        hb['sound_kind'] = SOUND_KIND.get(str(h['sfx_type']), 3 if str(h.get('effect')) in CUTS else 2)
                    hb['shield_damage'] = shield_field(h.get('shield_damage'))
                    if str(h.get('clang')) in NO_CLANK:
                        hb['clank'] = False                 # another attack cannot meet this hit
                    hb['game_id'] = (h.get('id'), part)
                    if isinstance(h.get('part'), int) and not isinstance(h.get('part'), bool) and 0 < h['part'] < 8:
                        hb['group'] = h['part']             # the game's hit group
                    if isinstance(h.get('fkb'), (int, float)) and h['fkb']:
                        # under a link angle Ultimate carries the target at the attacker's own speed and does not
                        # launch it by this number at all: Melee's own linking hits are written instead
                        hb['fixed_kb'] = min(int(h['fkb']), LINK_KB) if int(h['angle']) > 361 else int(h['fkb'])
                    out.append(hb)
            if out:
                # each keeps the Melee hitbox it had on the stretch before; a new one takes a free one
                slots = {g: s for g, s in slots.items() if g in {hb['game_id'] for hb in out}}
                free = [s for s in range(4) if s not in slots.values()]
                for hb in out:
                    if hb['game_id'] not in slots:
                        slots[hb['game_id']] = free.pop(0)
                    hb['slot'] = slots[hb.pop('game_id')]
                phase = {'start': int(start), 'end': int(end), 'hitboxes': sorted(out, key=lambda hb: hb['slot'])}
                assert len(phase['hitboxes']) <= 4
                if continues:
                    phase['continues'] = True
                phases.append(phase)
        if throw and rows[0].get('strike') is not None:
            # a hit the game writes as a throw (it holds what it hits; nothing is held here): a plain hit about the
            # fighter's chest on the frames up to the throw's, with the numbers of the one of its variants asked for
            a = abs_[min(int(rows[0]['strike']), len(abs_) - 1)]['args']
            at_ = min(max(3, int(hit[0]['real'])), int(total))
            phases.append({'start': at_ - 2, 'end': at_, 'hitboxes': [{
                'bone': 0, 'position': [0.0, 8.0 * scale, 5.0 * scale], 'radius': 8.0 * scale, 'damage': max(1, round(a[2])),
                'angle': int(a[3]), 'kbg': int(a[4]), 'bkb': int(a[6]), 'element': 0}]})
            throw = None
        profile = {'id': script[5:] if script.startswith('game_') else script, 'motions': targets, 'total': int(total), 'phases': phases}
        if script != base:
            profile['occurrence'] = 1
        elif script + SECOND in game['moves']:
            profile['occurrence'] = 0
        on = [f['real'] for f in m.get('flags', []) if f['cmd'] == 'on_flag']
        off = [f['real'] for f in m.get('flags', []) if f['cmd'] == 'off_flag']
        first = phases[0]['start'] if phases else None
        if any(t.startswith('AttackAir') for t in targets) and on and off and on[0] < off[-1] <= total:
            profile['landing_window'] = [int(on[0]), int(off[-1])]
        if any(t in ('AttackS4', 'AttackHi4', 'AttackLw4') for t in targets) and first:
            before = [f for f in on if f < first]
            if before and before[0] >= 1:
                profile['charge'] = int(before[0])
        if any(t in ('Attack11', 'Attack12') for t in targets):
            if 'jab_followup_windows' in m:
                windows, neutral = [], []
                for window in m['jab_followup_windows']:
                    start, end = window['start'], window.get('end')
                    start = int(to_clip(start) if to_clip else start + shift)
                    end = int(to_clip(end) if to_clip else end + shift) if end is not None else int(installed[targets[0]]) + 1
                    start, end = max(1, start), min(int(installed[targets[0]]) + 1, end)
                    if 'when' in window and 'neutral' not in window:
                        raise ValueError('jab listener stick predicate missing; rerun the Slap City reader')
                    if start < end:
                        windows.append([start, end])
                        neutral.append(bool(window.get('neutral')))
                profile['jab_followup_windows'] = windows
                profile['jab_followup_neutral'] = neutral
            elif first:
                after = [f for f in on if first < f <= total]
                if after:
                    profile['jab_followup'] = int(after[0])
        untouched = m.get('intangible')
        if untouched and all(isinstance(v, int) and not isinstance(v, bool) for v in untouched) and len(untouched) == 2:
            # the game makes the fighter untouchable for these frames (the donor's script for the action, which
            # said so for the donor's own frames, is replaced by the one written here)
            first_, last_ = (to_clip(v) for v in untouched) if to_clip else (v + shift for v in untouched)
            first_, last_ = max(1, int(first_)), min(int(last_), int(total))
            if first_ <= last_:
                profile['intangible'] = [first_, last_]
        turns = [int(t) for t in m.get('turns') or [] if isinstance(t, int)]
        if throw:
            throw['release'] = min(max(2, throw['release']), total)
            profile['throw'] = throw
            if turns:
                # the script turns the fighter round (a back throw): Melee's throws can do the same
                profile['turns'] = [min(max(1, t), total) for t in turns]
        elif turns:
            notes.append(f'{script}: the script turns the fighter round on frame {turns}; only a throw can carry that')
        if profile['phases'] or throw:
            profiles.append(profile)
    return {'schema': 1, 'moves': profiles}, notes


def at_frame(items, frame, command):
    """A move script with `command` added at `frame`. Scripts written here wait with
    "until frame N" timers only; one that loops or waits another way gets the
    command at its start instead."""
    if frame <= 0 or any(code in (1, 3, 4, 5, 6, 7) for code, _, _ in items):
        return [command] + list(items)
    for i, (code, fields, _) in enumerate(items):
        if code == 2 and fields['frame'] > frame:
            before = [f['frame'] for c, f, _ in items[:i] if c == 2]
            wait = [] if before and before[-1] == frame else [(2, {'frame': frame}, None)]
            return list(items[:i]) + wait + [command] + list(items[i:])
        if code == 0:
            return list(items[:i]) + [(2, {'frame': frame}, None), command] + list(items[i:])
    return list(items) + [(2, {'frame': frame}, None), command]


def script_for_row(rows, table, game):
    """The game script the stem that owns `rows` belongs to."""
    stem = next(k for k, v in table.items() if v is rows)
    return script_for(stem, game['moves'])


def donor_cues(fd):
    """What the donor's own scripts use for a sword trail, a swing sound and an attack voice:
    {'trail_on', 'trail_off', 'voice', 'swing', 'swings': {motion: [sound commands]}}."""
    cues = {'swings': {}}
    for act in fd.actions:
        if act.script_offset is None or not act.motion:
            continue
        for code, fields, extra in fd.script_items(act.index):
            if code == 49:
                cues.setdefault('trail_off' if fields.get('render_status') else 'trail_on', (code, dict(fields), None))
            elif code == 10:
                cues.setdefault('effects', {}).setdefault(fields.get('gfx_id'), (code, dict(fields), None))
            elif code == 17 and fields.get('sfx_id', 0) >= 10000:
                # a sound of the fighter's own bank: one that is a voice line, one that is not (how each is played)
                cues.setdefault('own_voice' if fields.get('behavior') == 2 else 'own_sound', (code, dict(fields), None))
            elif code == 18:
                cues.setdefault('voice', (code, dict(fields), None))
            elif code == 17 and act.motion.startswith('Attack'):
                cues['swings'].setdefault(act.motion, []).append((code, dict(fields), None))
    first = next((v for k, v in sorted(cues['swings'].items()) if v), None)
    if first:
        cues['swing'] = first[0]
    return cues


def effect_place(root, fighter, clips_dir, rig_json, donor, scale):
    """What `dress` needs to put one of Melee's effects where the game puts its own: the donor's weapon joint,
    the 3x3 that takes each of the fighter's weapon bones' axes to that joint's (scale included), and the
    scale of the fighter itself. -> {'bone', 'weapon': {bone name: 3x3}, 'scale'}"""
    from fighter_port import weapons
    out = {'bone': None, 'weapon': {}, 'scale': float(scale)}
    if donor not in WEAPON:
        return out
    out['bone'] = int(WEAPON[donor]['target'].split('_')[1])
    skel = ssbh(root).skel_data.read_skel(str(Path(root) / 'gamedata' / 'fighter' / fighter / 'model' / 'body' / 'c00' / 'model.nusktb'))
    for b in skel.bones:
        if b.name.lower() in WEAPON_BONES:
            try:
                out['weapon'][b.name.lower()] = weapons.to_joint(clips_dir, rig_json, WEAPON[donor]['target'], b.name)
            except (KeyError, StopIteration):
                pass
    return out


def placed(command, args, place):
    """One of the donor's own effect commands, moved to where the game's command (its `args`: name, bone, x, y, z)
    puts the effect: on the weapon, the game's point carried into the donor's weapon joint; over the fighter's
    feet, its height. (A point ahead of or beside the feet is left where the donor has it: the game's commands
    do not agree on which of their numbers is which there.) Any other bone: the donor's command as it is."""
    bone = str(args[1] if len(args) > 1 else '').lower()
    xyz = list(args[2:5])
    if not place or len(xyz) != 3 or not all(isinstance(v, (int, float)) for v in xyz):
        return command
    fields = dict(command[1], range_x=0, range_y=0, range_z=0)
    if bone in place['weapon'] and place['bone'] is not None:
        point = place['weapon'][bone] @ xyz
        fields.update(bone_id=place['bone'])
    elif bone == 'top':
        point = (0.0, xyz[1] * place['scale'], 0.0)
        fields.update(bone_id=0)
    elif bone in (place.get('joints') or {}):
        # a fighter on its own skeleton has the game's bone itself (`joints`: bone name -> its joint): the effect
        # goes on that joint, at the game's own point
        point = xyz
        fields.update(bone_id=place['joints'][bone], use_common_bone_ids=0)
    else:
        return command
    # the command's three offsets are the joint's x, y and z in that order (the reader names them z, y, x), in 256ths
    fields.update(z=int(round(point[0] * 256)), y=int(round(point[1] * 256)), x=int(round(point[2] * 256)))
    return (command[0], fields, None)


def dress(items, move, total, cues, motion, fighter, shift=0, at=None, sound_ids=None, first=1, own_only=False):
    """A written move script with what the hitbox writer leaves out, on the game's own frames:
    the sword trail where the game draws one, the donor's swing sound where the game plays the
    fighter's, the donor's attack voice where the game plays a voice line. `at` turns a frame of the
    script into a frame of the clip (a second version of a move); else `shift` is added. `sound_ids`
    {sound name: number}: the fighter's own sounds that the port's bank holds (`voice.calls`); those are
    played themselves. `first`: the earliest frame a sound or an effect is heard or seen on (see STARTS_ON).
    `own_only`: nothing of the donor's stands in for a sound the bank does not hold (a charge being drawn is no swing).
    -> (items, what was added)"""
    sound_ids = sound_ids or {}
    added = []
    at = at or (lambda f: f + shift)
    effects = [dict(e, real=max(first, at(e['real']))) if e.get('real') else e for e in move.get('effects') or []]
    sounds = [dict(e, real=max(first, at(e['real']))) if e.get('real') else e for e in move.get('sounds') or []]
    ons = sorted(e['real'] for e in effects if e['cmd'].startswith('AFTER_IMAGE') and '_ON' in e['cmd'] and e['real'])
    offs = sorted(e['real'] for e in effects if e['cmd'].startswith('AFTER_IMAGE_OFF') and e['real'])
    thrust = any(isinstance(x, str) and THRUST_WORD in x for e in effects for x in (e.get('args') or [])[:1])
    if not ons and 'trail_on' in cues and not thrust and not cues.get('trail_drawn_only'):
        # The game draws many sword swings with an effect made for the move (a slash, an arc) and no trail.
        # Those effects have no Melee form, so the swing would be bare: the trail runs while the move's
        # hitboxes are out on the weapon, from a little before the first.
        swings = [h for h in move.get('hitboxes') or [] if str(h.get('bone') or '').lower() in WEAPON_BONES
                  and isinstance(h.get('first'), int) and h.get('damage')]
        if not swings and motion.startswith(('Attack', 'Special')) and any(
                isinstance(x, str) and x.startswith(fighter + '_') and any(w in x for w in SWING_WORDS)
                for e in effects for x in (e.get('args') or [])[:1]):
            # hitboxes on the fighter's own base point (a smash attack's reach is often written that way), with a
            # swing effect of the fighter's own: the sword's all the same. (One of the game's common effects, an
            # arc or a line, says nothing: a kick has those too.)
            swings = [h for h in move.get('hitboxes') or [] if isinstance(h.get('first'), int) and h.get('damage')]
        if swings:
            ons = [max(first, at(min(h['first'] for h in swings)) - SWING_LEAD)]
            offs = [min(total - 1, max(at(h['last']) if isinstance(h.get('last'), int) else total - 1 for h in swings) + SWING_LEAD)]
    if ons and ons[0] < total and 'trail_on' in cues and 'trail_off' in cues:
        end = min(max([f for f in offs if f > ons[0]] or [total - 1]), total - 1)
        items = at_frame(items, int(ons[0]), cues['trail_on'])
        items = at_frame(items, int(end), cues['trail_off'])
        added.append(f'trail {int(ons[0])}-{int(end)}')
    made = set()
    for e in effects:                                   # Melee's own dust and gleam where the game has its own
        name = next((x for x in (e.get('args') or [])[:1] if isinstance(x, str)), None)
        gfx = EFFECT_MELEE.get(name)
        stand_in = gfx is None and name in EFFECT_STAND_IN
        if stand_in:
            gfx = EFFECT_STAND_IN[name]
        if gfx is None or not e.get('real') or e['real'] >= total or (int(e['real']), gfx) in made:
            continue
        template = cues.get('effects', {}).get(gfx)
        if template is None and stand_in and cues.get('effects'):
            like_ = next(iter(cues['effects'].values()))    # any of the donor's effect commands, with the number changed
            template = (like_[0], dict(like_[1], gfx_id=gfx, bone_id=0, use_common_bone_ids=0, x=0, y=0, z=0,
                                       range_x=0, range_y=0, range_z=0), None)
        if template is None:
            continue
        command = placed(template, e.get('args') or [], cues.get('place'))
        if stand_in and cues.get('place'):
            # where the move's hitboxes on the fighter's own base point are as the effect starts: ahead of the feet
            # (the command's x is the way the fighter faces), at the lowest of them
            boxes = [h for h in move.get('hitboxes') or [] if str(h.get('bone')) == 'top' and isinstance(h.get('first'), int)
                     and at(h['first']) <= e['real'] <= (at(h['last']) if isinstance(h.get('last'), int) else total)]
            if boxes:
                box, k_ = min(boxes, key=lambda h: h['y']), cues['place']['scale'] * 256
                command = (command[0], dict(command[1], bone_id=0, x=int(round(box['z'] * k_)), y=int(round(box['y'] * k_)), z=0), None)
        made.add((int(e['real']), gfx))
        items = at_frame(items, int(e['real']), command)
        added.append(f'effect {int(e["real"])} ({name}{", a stand-in" if stand_in else ""})')
    plays = [e for e in sounds if e['cmd'].startswith('PLAY') and e.get('name') and e['real'] and e['real'] < total]
    own = [e for e in plays if e['name'].startswith(f'se_{fighter}_')
           and not any(w in e['name'] for w in ('cloth', 'step', 'landing', 'jump', 'squat'))]
    bank = cues['swings'].get(motion) or ([cues['swing']] if 'swing' in cues else [])
    for k, e in enumerate(sorted(own, key=lambda e: e['real'])):
        number = sound_ids.get(e['name'].lower())
        if number is not None and 'own_sound' in cues:
            items = at_frame(items, int(e['real']), (17, dict(cues['own_sound'][1], sfx_id=number), None))
            added.append(f'swing {int(e["real"])} (its own: {e["name"]})')
        elif bank and not own_only:
            items = at_frame(items, int(e['real']), bank[min(k, len(bank) - 1)])
            added.append(f'swing {int(e["real"])}')
    like = cues.get('own_sound') or cues.get('swing')
    for e in sorted((e for e in plays if e['name'].lower() in SOUND_MELEE), key=lambda e: e['real']):
        if like:                                        # one of the games' shared swings: Melee's own for it
            items = at_frame(items, int(e['real']), (17, dict(like[1], sfx_id=SOUND_MELEE[e['name'].lower()]), None))
            added.append(f'swing {int(e["real"])} (shared: {e["name"]})')
    spoken = False
    for e in sorted((e for e in plays if e['name'].startswith('vc_')), key=lambda e: e['real']):
        number = sound_ids.get(e['name'].lower())
        if number is not None and 'own_voice' in cues:
            items = at_frame(items, int(e['real']), (17, dict(cues['own_voice'][1], sfx_id=number), None))
            added.append(f'voice {int(e["real"])} (its own: {e["name"]})')
            spoken = True
        elif not spoken and 'voice' in cues and not own_only:
            items = at_frame(items, int(e['real']), cues['voice'])
            added.append(f'voice {int(e["real"])}')
            spoken = True
    # A normal's voice the game picks from a set (`PLAY_SEQUENCE seq_<fighter>_rnd_attack...`: a jab's, a tilt's, an
    # air attack's) is Melee's own pick: the donor's random attack voice (`Random Smash SFX`, command 18), whose
    # samples the bank holds the fighter's attack lines in. Left as it was, nothing played it: the own route writes
    # his scripts new, so his normals were silent of his voice. Not where the script has a voice of its own already.
    pick = re.compile(rf'seq_{re.escape(fighter.lower())}_rnd_attack(_[a-z0-9_]+)?')
    if not spoken and not own_only and 'voice' in cues and not any(code == 18 for code, _, _ in items):
        e = next((e for e in sorted(plays, key=lambda e: e['real']) if pick.fullmatch(e['name'].lower())), None)
        if e is not None:
            items = at_frame(items, int(e['real']), cues['voice'])
            added.append(f'voice {int(e["real"])} (picked, for {e["name"]})')
            spoken = True
    return items, added


def game_trail(game, fighter, root, clips_dir, rig_json, donor, base):
    """The fighter's sword trail as the game draws it, as a description for the donor's
    weapon joint (`base` is the donor's own, for what the game does not say): the span
    along the blade from the trail commands' two points, the colour from the trail's
    texture. -> (description or None, note)"""
    from collections import Counter
    import numpy as np
    from fighter_port import weapons
    ons = [e for m in game['moves'].values() for e in (m.get('effects') or [])
           if e['cmd'].startswith('AFTER_IMAGE') and '_ON' in e['cmd'] and len(e['args']) >= 9]
    ons = [e for e in ons if len(e['args']) >= 11 and isinstance(e['args'][3], str) and e['args'][3] == e['args'][7]
           and all(isinstance(e['args'][i], (int, float)) for i in (4, 5, 6, 8, 9, 10))]
    if not ons or not base or donor not in WEAPON:
        return None, 'the game draws no sword trail for this fighter' if not ons else 'the donor has no trail to base one on'
    bone = Counter(e['args'][3] for e in ons).most_common(1)[0][0]
    ons = [e for e in ons if e['args'][3] == bone]
    skel = ssbh(root).skel_data.read_skel(str(Path(root) / 'gamedata' / 'fighter' / fighter / 'model' / 'body' / 'c00' / 'model.nusktb'))
    name = next((b.name for b in skel.bones if b.name.lower() == bone), None)
    if name is None:
        return None, f'trail bone {bone!r} is not in the skeleton'
    to_joint = weapons.to_joint(clips_dir, rig_json, WEAPON[donor]['target'], name)
    # the command gives the blade's two ends in the bone's own axes: the pair most moves use
    pair = Counter(tuple(e['args'][4:7]) + tuple(e['args'][8:11]) for e in ons).most_common(1)[0][0]
    ends = sorted((to_joint @ np.array(p, float) for p in (pair[:3], pair[3:])), key=lambda p: p[0])
    off = max(float(np.linalg.norm(p[1:])) for p in ends) / max(abs(float(ends[1][0])), 1e-6)
    out = dict(base, bone=int(WEAPON[donor]['target'].split('_')[1]), bottom=float(ends[0][0]), top=float(ends[1][0]))
    note = f'trail along {name}: {out["bottom"]:.2f} to {out["top"]:.2f} on donor joint {out["bone"]}'
    if off > 0.15:
        note += f' (the blade leaves the joint\'s own axis by {off:.0%}; the trail cannot follow that)'
    main, texture, others = trail_paint(game, ons, bone, lambda t: trail_colour(root, fighter, t, base['in_col'][3]))
    if main:
        out['in_col'] = main
        note += f'; colour {out["in_col"][:3]} from {texture}'
    others = {k: c for k, c in others.items() if c != out['in_col']}
    out['others'] = others
    if others:
        note += f'; {len(others)} moves in other colours ({len({tuple(c) for c in others.values()})} colours)'
    return out, note


def trail_colour(root, fighter, texture, alpha):
    """The colour of one of the game's trail pictures ([r, g, b, `alpha`]), or None."""
    import numpy as np
    if isinstance(texture, str) and texture.startswith('brawl_'):
        # Brawl draws a fighter's trail with one picture of the fighter's own, laid on as light: black is nothing,
        # so the colour is what its bright parts are, at full strength
        from echo_brawl import textures as brawl_textures
        picture = brawl_textures.trail_picture(root, fighter)
        if picture is None:
            return None
        a = np.asarray(picture.convert('RGB'), float)
        w = a.max(2, keepdims=True)
        if w.sum() <= 0:
            return None
        mean = (a * w).sum((0, 1)) / w.sum()
        return [int(round(c * 255 / mean.max())) for c in mean] + [alpha]
    if not isinstance(texture, str) or texture.startswith(('0x', '<')):
        return None                                 # (a trail that is not a picture: the donor's colour stays)
    from echo_ultimate import nutexb
    from echo_ultimate.gamedata import arc
    rel = f'effect/fighter/{fighter}/trail/{texture}.nutexb'
    path = arc.extract(Path(root), Path(root) / 'gamedata', [rel]).get(rel)
    if not path:
        return None
    a = np.asarray(nutexb.read(path)[0], float)
    w = a[..., 3:4] / 255
    if w.sum() <= 0:
        return None
    return [int(round(c)) for c in (a[..., :3] * w).sum((0, 1)) / w.sum()] + [alpha]


def trail_paint(game, ons, bone, colour):
    """The colours of a fighter's trail commands `ons` on `bone`: (its own colour or None, the picture it is from,
    {script: colour} of the moves the game draws in another picture). `colour(picture)` -> colour or None."""
    from collections import Counter
    # the fighter's own colour is that of its ordinary attacks (a final smash has many trail commands, in a
    # colour of its own: counted with the rest it would win, and every move with no trail command would take it)
    plain = [e['args'][0] for script, m in game['moves'].items() if script.startswith('game_attack')
             for e in (m.get('effects') or []) if e in ons]
    texture = Counter(plain or [e['args'][0] for e in ons]).most_common(1)[0][0]
    main = colour(texture)
    # a move the game draws in another picture has its own colour: {script: colour}
    others = {}
    for script, m in game['moves'].items():
        mine = [e['args'][0] for e in (m.get('effects') or []) if e['cmd'].startswith('AFTER_IMAGE') and '_ON' in e['cmd']
                and len(e['args']) >= 9 and e['args'][3] == bone]
        if mine and mine[0] != texture:
            c = colour(mine[0])
            if c and c != main:
                others[script] = c
    return main, texture, others


def trail_colours(others, second_colour, table, moves, alternates, alt, actions):
    """The actions of each move whose trail is another colour than the fighter's own.
    `others` {script: colour}; `alternates` {motion: the script of its second version}; `alt` {motion: the
    index of its second action}; `second_colour`: a script whose colour every second version takes when the
    game's data gives it none (see SECOND_COLOUR). -> [{'in_col', 'actions'}]"""
    by_colour = {}
    for stem, rows in table.items():
        own = script_for(stem, moves)
        for script in {own} | {s for m, s in alternates.items() if any(r['target_motion'] == m for r in rows)}:
            colour = others.get(script)
            if not colour and script != own:
                colour = others.get(second_colour)
            if not colour:
                continue
            seconds = {m for m, s in alternates.items() if s == script}
            for r in rows:
                for act in actions:
                    if act.motion != r['target_motion'] or not act.anim_size:
                        continue
                    # a move's own script colours its first actions; a second version's script colours only
                    # the second action of the motions it is the second version of
                    second = alt.get(act.motion) == act.index
                    if (not second) if script == own else (second and act.motion in seconds):
                        by_colour.setdefault(tuple(colour), set()).add(act.index)
    return [{'in_col': list(c), 'actions': sorted(v)} for c, v in sorted(by_colour.items())]


def game_shot(game, fighter, root, scale):
    """The neutral special's projectiles as the game has them, in donor units: each one's
    hitbox, speed and life; the frame of the move they are let go on; the frame a full
    charge is reached. -> (description or None, note)"""
    from echo_ultimate.gamedata.prc import Prc
    where = SHOT_GAME.get(fighter)
    if not where:
        return None, 'no projectile known for this fighter'
    vl = Path(root) / 'gamedata' / 'fighter' / fighter / 'param' / 'vl.prc'
    names = [n for sh in where['shots'] for n in (sh['params'], sh.get('speed'), sh.get('life'), sh.get('distance')) if n]
    params = Prc(vl.read_bytes(), names + list(where.get('charge') or ())).root if vl.exists() else {}
    shots = []
    for sh in where['shots']:
        weapon = game['moves'].get(sh['script'])
        hits = [h for h in (weapon or {}).get('hitboxes', [])
                if all(isinstance(h.get(k), (int, float)) for k in ('damage', 'angle', 'kbg', 'bkb', 'size'))]
        table = params.get(sh['params'])
        row = table[min(int(sh.get('row') or 0), len(table) - 1)] if isinstance(table, list) and table else table
        if not hits or not isinstance(row, dict):
            return None, f"the game's {sh['script']} / {sh['params']} did not read"
        if 'distance' in sh:
            life = float(sh['over'])
            speed = float(row[sh['distance']]) / life
        else:
            speed, life = float(row[sh['speed']]), float(row[sh['life']])
        h = max(hits, key=lambda h: (h['damage'], h['size']))
        # the item has one hitbox: as big as the game's boxes are tall together. Boxes that sit above the
        # shot's own base point are a shot that stands on the ground; it starts on the fighter's ground.
        first = [x for x in hits if x['first'] == min(y['first'] for y in hits)]
        ys = [float(x['y']) for x in first if isinstance(x.get('y'), (int, float))] or [0.0]
        size = max(float(x['size']) for x in hits)
        low, high = max(min(ys) - size, 0.0) if min(ys) > 0 else min(ys) - size, max(ys) + size
        stands = (max(ys) + min(ys)) / 2 > size
        trap = None
        if sh.get('then'):
            # what it does once it has hit: each of that script's hitboxes on its own frames, one that
            # hits again every few frames written out as that many hits; then it ends
            after, events = (game['moves'].get(sh['then']) or {}).get('hitboxes') or [], []
            for x in after:
                if not all(isinstance(x.get(k), (int, float)) for k in ('first', 'damage', 'angle', 'kbg', 'bkb', 'size')):
                    continue
                last = x['last'] if isinstance(x.get('last'), int) else x['first']
                every = int(x.get('rehit') or 0)
                link = x['angle'] > 361                 # a hit that holds: Melee's own linking hits (see LINK_KB)
                for f in range(int(x['first']), int(last) + 1, every) if every else [int(x['first'])]:
                    events.append((f - 1, {'damage': max(1, int(x['damage'] + 0.5)), 'angle': 80 if link else int(x['angle']),
                                           'knockback_growth': int(x['kbg']), 'base_knockback': int(x['bkb']),
                                           'weight_set_knockback': min(int(x.get('fkb') or 0), LINK_KB) if link else int(x.get('fkb') or 0),
                                           'size': int(x['size'] * scale * 256), 'again': 0,
                                           'y_offset': int(float(x.get('y') or 0) * scale * 256),
                                           'element': ELEMENT.get(str(x.get('effect')), 0)}))
            if events:
                ends = max((x['last'] if isinstance(x.get('last'), int) else x['first']) for x in after if isinstance(x.get('first'), int))
                # Where it holds. The game's flying boxes sit behind the shot's own point, so when one of them
                # touches a target that point is already at the target, and the holding boxes are about it. Here the
                # shot is one ball about its own point: it stops a ball's radius short, and steps on by that much
                # (less what the game's own box would still have had to go).
                behind = -float(sum(x['z'] for x in first if isinstance(x.get('z'), (int, float))) / max(1, len(first)))
                ahead = max(size, (high - low) / 2) * scale + (behind - max(float(x['size']) for x in first)) * scale
                # how long each of its hits stops it, beside a plain hit (the game's own number for the first of them)
                lag = next((float(x['hitlag']) for x in after if isinstance(x.get('hitlag'), (int, float))), 1.0)
                trap = {'events': sorted(events, key=lambda e: e[0]) + [(int(ends), None), (int(ends), 'done')],
                        'life': int(ends) + 1, 'ahead': max(0.0, ahead), 'lag': lag}
        shots.append({'when': sh['when'], 'on': sh.get('on'), 'model': sh.get('model'), 'pierce': bool(sh.get('pierce')),
                      'variant': int(sh.get('variant') or 0), 'trap': trap,
                      'damage': int(h['damage'] + 0.5), 'angle': int(h['angle']) if h['angle'] <= 361 else 80,
                      'kbg': int(h['kbg']), 'bkb': int(h['bkb']), 'radius': max(size, (high - low) / 2) * scale,
                      'height': (high - low) * scale, 'rise': (high + low) / 2 * scale if stands else None,
                      'element': ELEMENT.get(str(h.get('effect')), 0), 'speed': speed * scale, 'life': life,
                      # what it takes off a shield beyond its damage
                      'shield_damage': shield_field(h.get('shield_damage'))})
    move = game['moves'].get(where['move'], {})
    made = [f for f in move.get('article_frames') or [] if f]
    # let go on the frame the move's script makes the shot; a script that does not: its first effect or sound
    go = min(made) if made else min([e['real'] for e in (move.get('effects') or []) + (move.get('sounds') or []) if e.get('real')] or [1])
    full = None
    if where.get('charge'):
        has, field = where['charge']
        rows = [r for t in params.values() for r in (t if isinstance(t, list) else [t]) if isinstance(r, dict)]
        full = next((float(r[field]) for r in rows if has in r and field in r), None)
    out = {'shots': shots, 'frame': int(go), 'scale': float(scale), 'full_charge_frame': full}
    return out, ('shots: ' + '; '.join(f"{sh['when']}{' ' + sh['on'] if sh.get('on') else ''} {sh['damage']}% at {sh['angle']}, speed {sh['speed']:.1f} for {sh['life']:.0f} frames"
                                       + (', goes through' if sh['pierce'] else '') for sh in shots)
                 + f"; let go on frame {out['frame']} of {where['move']}; full charge at frame {full}")


def shot_scripts(fd, donor, shot, FighterDat, written=(), shift=0):
    """The donor's release scripts made to raise the shot's flag (added to a script the port
    wrote, `written`; in place of the donor's own otherwise), its start and charge scripts
    emptied (their effects are the donor's). `shift`: the release clip starts that many game
    frames into the move. -> (FighterDat, actions rewritten)"""
    rule, done = SHOT_DONOR[donor], []
    frame, raise_ = max(1, shot['frame'] + shift), (19, {'flag': rule['flag'], 'value': 1}, None)
    for motions, items in ((rule['release'], [(2, {'frame': frame}, None), raise_, (0, {}, None)]),
                           (rule['quiet'], [(0, {}, None)])):
        for motion in motions:
            for act in [x for x in fd.actions if x.motion == motion and x.script_offset is not None]:
                new = items
                if motion in rule['release'] and motion in written:
                    new = at_frame(fd.script_items(act.index), frame, raise_)
                fd.replace_script(act.index, list(new))
                fd._scripts.clear()
                fd = FighterDat(fd.to_bytes())
                done.append(motion)
    return fd, done


def install_scripts(pl_bytes, spec):
    """Apply each profile on its own so one bad move does not cost the rest."""
    from fighter_port import combat
    data, done, failed = pl_bytes, [], []
    for profile in spec['moves']:
        try:
            data, report = combat.install_profiles(data, {'schema': 1, 'moves': [profile]})
            done.append(profile['id'])
        except (ValueError, KeyError) as exc:
            failed.append((profile['id'], str(exc)))
    return data, done, failed


def rise_speed(height, gravity):
    """The speed a jump starts with to rise `height` under `gravity`, as Melee moves a fighter: each frame it goes
    up by its speed, which then drops by gravity. (Measured in game: Marth's 2.4 under 0.098 rises 30.6.)"""
    def rises(v):
        h = 0.0
        while v > 0:
            h, v = h + v, v - gravity
        return h
    low, high = 0.0, 50.0
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if rises(mid) < height else (low, mid)
    return (low + high) / 2


def attribute_ops(game, length=None, model_scale=None):
    """The fighter's numbers as edits of the fighter data. `length` is what the game's lengths are multiplied by
    here and `model_scale` the scale the fighter data draws the model at (for the one number the engine
    multiplies by that scale itself: the shield); without them the shield stays the donor's and a note says so."""
    att = game['attributes']
    ops, notes = [], []
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if number(att.get(SHIELD[1])) and att[SHIELD[1]] > 0:
        if length and model_scale:
            ops.append({'op': 'set_attribute', 'name': SHIELD[0],
                        'value': float(att[SHIELD[1]]) * float(length) / float(model_scale)})
        else:
            notes.append(f'{SHIELD[0]}: the scales were not given, so it stays the donor\'s')
    gravity = att.get('air_accel_y')
    if number(gravity) and gravity > 0:
        # jumps: the game's heights, as the speeds that reach them under the fighter's own gravity (the first
        # ports kept the donor's speeds, so a fighter with more gravity than the donor jumped lower than its own
        # game has it and one with a low jump jumped the donor's height)
        speeds = {melee: rise_speed(float(att[field]), float(gravity)) for melee, field in JUMPS.items()
                  if number(att.get(field)) and att[field] > 0}
        ops += [{'op': 'set_attribute', 'name': melee, 'value': float(v)} for melee, v in speeds.items()]
        full = speeds.get('initial_vertical_jump_velocity')
        if full and number(att.get(AIR_JUMP[1])) and att[AIR_JUMP[1]] > 0:
            ops.append({'op': 'set_attribute', 'name': AIR_JUMP[0],
                        'value': rise_speed(float(att[AIR_JUMP[1]]), float(gravity)) / full})
    for melee, field in SAME.items():
        if number(att.get(field)):
            ops.append({'op': 'set_attribute', 'name': melee, 'value': float(att[field])})
    for melee, fields in ATTRIBUTES.items():
        vals = [att.get(f) for f in fields]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            ops.append({'op': 'set_attribute', 'name': melee, 'value': float(sum(vals))})
        else:
            notes.append(f'{melee}: no game value for {fields}')
    for melee, field in LANDING.items():
        v = att.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ops.append({'op': 'set_attribute', 'name': melee, 'value': float(v) * LANDING_TIMES})
    return ops, notes


# ---------------------------------------------------------------------- stages
def clip_frames(aj_bytes, pl_bytes):
    """{motion: clip length} from an animation bank through its fighter data's action table."""
    import struct
    from vault.echo import datroot
    from vault.echo.subactions import FighterDat
    out = {}
    for a in FighterDat(pl_bytes).actions:
        if a.motion and a.anim_size and a.motion not in out:
            data, _, roots, _ = datroot.parse(aj_bytes[a.anim_offset:a.anim_offset + a.anim_size])
            out[a.motion] = int(round(struct.unpack_from('>f', data, roots[0][0] + 8)[0]))
    return out


def run(a):
    if getattr(a, 'own', None):
        # the fighter keeps its own skeleton: the second route (own_route.py), which uses this file's rules
        from fighter_port import own_route
        return own_route.run(a)
    from echo_ultimate.gamedata import moves as gd
    from fighter_port import dat_rig, moveset, pipeline
    from vault.echo import ops as echo_ops

    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    report = {'fighter': a.fighter, 'donor': a.donor}

    with zipfile.ZipFile(a.donor_zip) as z:
        names = z.namelist()
        fighter_json = json.loads(z.read('fighter.json'))
        pl_name = fighter_json['files']['fighterDataPath']
        aj_name = fighter_json['files']['animFile']
        donor_pl, donor_aj = z.read(pl_name), z.read(aj_name)
        costume0 = fighter_json['costumes'][0]['file']['fileName']
        inner = Path(costume0).stem + '.zip'
        with zipfile.ZipFile(io.BytesIO(z.read(inner))) as cz:
            donor_costume = cz.read(costume0)
    from vault.echo.subactions import FighterDat as _Fd
    from fighter_port.states import FIRST_SPECIAL_ACTION
    special_count = len(_Fd(donor_pl).actions) - FIRST_SPECIAL_ACTION       # the donor's own special states, one an action
    d = work / 'donor'
    d.mkdir(exist_ok=True)
    (d / pl_name).write_bytes(donor_pl)
    (d / aj_name).write_bytes(donor_aj)
    (d / costume0).write_bytes(donor_costume)
    rig = work / f'{a.donor}.joints.json'
    if not rig.exists():
        dat_rig.write(d / costume0, rig)

    brawl = getattr(a, 'game', 'ultimate') == 'brawl'
    game_path = work / 'game.json'
    if brawl:
        # a Brawl fighter: its skeleton and clips are written out once in the formats the driver reads, under the
        # names the driver's tables know; its scripts and numbers are read fresh every run
        from echo_brawl import gamedata as brawl_data, transcode as brawl_clips
        made = Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'transcode.json'
        if not made.exists():
            known = {}
            for stem_ in motion_table():
                known.setdefault(stem_[3:], stem_)
            stems_, lengths_ = brawl_clips.write(a.root, a.fighter, ssbh(a.root), known)
            made.write_text(json.dumps({'stems': stems_, 'lengths': lengths_}, indent=1), 'utf-8')
        written = json.loads(made.read_text('utf-8'))
        log(f"game files: {len(written['stems'])} clips of {a.fighter} written out from Brawl's")
        game_path.write_text(json.dumps(brawl_data.load(a.fighter, a.root, written['lengths'], written['stems']),
                                        indent=1, default=str), 'utf-8')
    else:
        # the fighter's models, clips and parameter tables, out of the game's archive (kept once there)
        from echo_ultimate.gamedata import arc
        have, listed = arc.fetch_fighter(a.root, a.fighter)
        log(f'game files: {have} of {listed} for {a.fighter}')
        if not have:
            raise SystemExit(f'the archive lists no files for a fighter named {a.fighter!r}')
        # game data is read fresh every run (seconds); a stale copy would hide a reader fix
        from fighter_port import voice as voice_seq
        game_ = gd.load(a.fighter, a.root)
        # a special's voice the game picks from a set (a sequence) is given the first line of that set
        sequences_ = voice_seq.name_sequences(game_, a.fighter, set(voice_seq._banks(a.root, a.fighter)['vc']))
        if sequences_:
            report['voice_sequences'] = sequences_
        game_path.write_text(json.dumps(game_, indent=1, default=str), 'utf-8')
    game = json.loads(game_path.read_text('utf-8'))

    # the fighter's own sounds that will be in the port's bank, by the number a script plays each with
    from fighter_port import voice as voice_
    sound_ids = {}
    with zipfile.ZipFile(a.donor_zip) as z:
        if 'sound.zip' in z.namelist() and fighter_json.get('soundBank') is not None:
            sound_zip = z.read('sound.zip')
            with zipfile.ZipFile(io.BytesIO(sound_zip)) as sz:
                samples = [s['name'] for s in json.loads(sz.read('group.json'))['sounds']]
            chosen_, _ = voice_.choose(a.donor, a.fighter, a.root, samples, game['moves'], a.game, sound_zip)
            sound_ids = voice_.calls(sound_zip, fighter_json['soundBank'], chosen_,
                                     voice_.aliases(a.root, a.fighter, a.game))
    report['own_sounds'] = sorted(sound_ids)
    log(f"sounds: {len(sound_ids)} of the fighter's own will be in its bank")

    # an action the donor has no clip for (a third jab): its empty slot gets one, to be filled like the rest
    for clip_name, (follows, name) in EXTRA_ACTION.items():
        if clip_name in clip_names(a.root, a.fighter) and 'game_' + clip_name in game['moves']:
            made = add_action(donor_pl, donor_aj, follows, name)
            if made:
                donor_pl, donor_aj = made
                (d / pl_name).write_bytes(donor_pl)
                (d / aj_name).write_bytes(donor_aj)
                log(f'actions: the donor has no {name}; its empty action after {follows} now has a clip to fill')

    # weapons that appear per move (a lance, an axe): which model, and which moves
    from fighter_port import weapons
    # a weapon bends when its own clips bend it and its joints fit beside the donor's; else it is a rigid one
    from fighter_port import chain_weapon
    from fighter_port.rigmap import Rig as Rig__
    room = MAX_JOINTS - len(Rig__(rig).order)
    bending = {}
    if a.donor in WEAPON and not brawl:
        for name in chain_weapon.chains(a.root, a.fighter, ssbh(a.root)):
            c = chain_weapon.read(ssbh(a.root), a.root, a.fighter, name)
            if c and len(c['bones']) <= room:
                bending[name] = c
            elif c:
                log(f"weapons: {name} bends, but its {len(c['bones'])} joints do not fit beside the donor's "
                    f"({room} to spare of {MAX_JOINTS}); it stays rigid")
    held_models = weapons.hold_models(ssbh(a.root), a.root, a.fighter, set(bending)) if a.donor in WEAPON and not brawl else {}
    for sh in SHOT_GAME.get(a.fighter, {}).get('shots', []):              # a projectile is let go, not held
        held_models.pop(sh.get('model'), None)
    own_clips = {name: {p.stem for p in (Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'motion' / name / 'c00').glob('*.nuanmb')}
                 for name in held_models}
    own_bones = [b.name for b in ssbh(a.root).skel_data.read_skel(str(
        Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'model' / 'body' / 'c00' / 'model.nusktb')).bones]
    own_bone = next((w[0] for w in WEAPON_SOURCES if w[0] in own_bones and w[1] in own_bones), None)
    by_script, weapon_notes = weapons.assign(game, held_models, own_clips, own_bone) if held_models else ({}, [])
    # a weapon that bends (a whip): its own joints and one clip per move that uses it
    chain_stems = {stem: name for name, c in bending.items() for stem in c['clips']}
    specials, special_shape = special_rows(a.donor, a.fighter, clip_names(a.root, a.fighter), game['moves'])
    from fighter_port import own as own_states
    own_clips = {k: v for k, v in own_states.CLIPS.get(a.fighter, {}).items() if k in clip_names(a.root, a.fighter)}
    with_own(specials, own_clips)
    report['specials'] = special_shape
    # the weapon's other clips: each belongs to the body clip whose hand path its own root track lies on
    chain_runs = {}
    if bending:
        S_ = ssbh(a.root)
        body_dir = Path(a.root) / 'gamedata' / 'fighter' / a.fighter
        skel_ = S_.skel_data.read_skel(str(body_dir / 'model' / 'body' / 'c00' / 'model.nusktb'))
        wanted = {stem[3:] for stem in ()}              # every special and every clip the table carries is tried
        for path in sorted((body_dir / 'motion' / 'body' / 'c00').glob('*.nuanmb')):
            if path.stem in chain_stems or path.stem[3:] not in specials:
                continue
            for name, c in bending.items():
                run = chain_weapon.align(S_, c, chain_weapon.hold_path(S_, skel_, path, c['hold']), used=())
                if run:
                    chain_runs[path.stem] = (name, run)
        for stem, (name, run) in chain_runs.items():
            log(f'weapons: during {stem} the {name} plays', ', '.join(f'{w} from frame {first}' for w, first in run))
    weapon_order = sorted(set(by_script.values()) | set(bending))
    for n in weapon_notes:
        log('weapons:', n)

    old_spec = work / 'spec' / 'moveset.json'
    before = json.loads(old_spec.read_text('utf-8')) if old_spec.exists() else None
    holds = {name: m['root'] for name, m in held_models.items()}
    spec_path, source_root = build_spec(a.fighter, a.donor, a.root, d / pl_name, game, work, by_script, chain_stems, holds, rig,
                                        chain_runs)
    after = json.loads(spec_path.read_text('utf-8'))
    # only the weapons a ported move holds are built (a final smash's own model is named by its script too)
    weapon_order = [w for w in weapon_order if any(c.get('weapon') == w for c in after['clips'])]
    clips_dir = work / 'clips'
    if before is not None and before != after and clips_dir.exists():
        # keep finished clips whose recipe row did not change; redo the rest
        import shutil
        same_frame = all(before.get(k) == after.get(k) for k in before if k != 'clips')
        old = {c['id']: c for c in before['clips']}
        redo = [c['id'] for c in after['clips'] if not same_frame or old.get(c['id']) != c]
        for cid in redo:
            shutil.rmtree(clips_dir / cid, ignore_errors=True)
        (clips_dir / 'identity.json').unlink(missing_ok=True)
        log(f'spec changed: {len(redo)} clips will be redone')
    cov = moveset.compile_set(spec_path, source_root, rig, d / pl_name, clips_dir)
    report['clips'] = cov['counts']
    log('clips:', cov['counts'])
    errors = [(r['id'], r.get('reason')) for r in cov['clips'] if r['status'] == 'error']
    (work / 'clip-errors.json').write_text(json.dumps(errors, indent=1), 'utf-8')

    out_aj, out_pl = work / 'installed' / aj_name, work / 'installed' / pl_name
    install = json.loads((work / 'clips' / 'install.json').read_text('utf-8'))
    import hashlib
    digest = hashlib.sha256()
    digest.update(repr(a.clip_error).encode())
    for item in install:
        digest.update(item['move'].encode() + hashlib.sha256(Path(item['file']).read_bytes()).digest())
    stamp = out_aj.parent / 'clips.sha256'
    if not out_pl.exists() or not stamp.exists() or stamp.read_text() != digest.hexdigest():
        out_aj.parent.mkdir(exist_ok=True)
        for old_file in (out_aj, out_pl):
            old_file.unlink(missing_ok=True)
        result = pipeline.install(d / aj_name, d / pl_name, install, out_aj, out_pl, error=a.clip_error)
        (work / 'install-report.json').write_text(json.dumps(result, indent=1, default=str), 'utf-8')
        stamp.write_text(digest.hexdigest())
    log('installed animation bank:', out_aj.stat().st_size, 'bytes')

    pl = out_pl.read_bytes()
    lengths = clip_frames(out_aj.read_bytes(), pl)
    installed_motions = {r['target_motion']: lengths.get(r['target_motion'])
                         for r in cov['clips'] if r['status'] == 'compiled' and lengths.get(r['target_motion'])}
    from fighter_port.rigmap import Rig as Rig_
    full_table = {}
    for c in json.loads(spec_path.read_text('utf-8'))['clips']:
        if c.get('parts'):
            for q, start in zip(c['parts'], part_starts(c['parts'])):
                full_table.setdefault(q['stem'], []).append({'target_motion': c['target_motion'], 'id': c['id'],
                                                             'time_keys': None, 'offset': start})
            continue
        stem = c['source'].rsplit('/', 1)[1][:-7]
        full_table.setdefault(stem, []).append({'target_motion': c['target_motion'], 'id': c['id'],
                                                'time_keys': c.get('time_keys'), 'window': c.get('window'),
                                                'offset': c.get('offset') or 0, 'acts': c.get('acts'),
                                                'strike': c.get('strike')})
    # a hitbox the game puts on the end of a thrown whip rides the whip's last joint
    tips = {}
    for c in json.loads(spec_path.read_text('utf-8'))['clips']:
        if c.get('chain_parts') and c.get('weapon') in bending:
            tips[script_for(c['source'].rsplit('/', 1)[1][:-7], game['moves'])] = \
                len(Rig_(rig).order) + len(bending[c['weapon']]['bones']) - 1
    spec, notes = combat_spec(game, full_table, a.donor, rig, a.scale, installed_motions,
                              Placer(clips_dir, rig, a.donor), tips)
    (work / 'combat.json').write_text(json.dumps(spec, indent=1), 'utf-8')
    pl, done, failed = install_scripts(pl, spec)
    # a second script under one name on a donor with one action for it: nowhere to put it, and said
    notes += [f'{name}: {why}' for name, why in failed if 'no action number' in why]
    failed = [f for f in failed if 'no action number' not in f[1]]
    report['scripts'] = {'written': len(done), 'failed': failed, 'notes': notes}
    log(f'scripts: {len(done)} moves written, {len(failed)} failed, {len(notes)} notes')

    # the written scripts carry hitboxes and timing only: add the trail, swing sound and voice the game has
    from vault.echo.subactions import FighterDat
    cues = donor_cues(FighterDat(donor_pl))
    cues['place'] = effect_place(a.root, a.fighter, clips_dir, rig, a.donor, a.scale)
    fd, dressed = FighterDat(pl), {}
    for profile in spec['moves']:
        move = game['moves'].get('game_' + profile['id']) or game['moves'].get(profile['id'])
        if profile['id'] not in done or not move:
            continue
        base_id = profile['id'][:-len(SECOND)] if profile['id'].endswith(SECOND) else profile['id']
        for motion in profile['motions']:
            acts_ = [x for x in fd.actions if x.motion == motion]
            if profile.get('occurrence') is not None:
                acts_ = combat_nth(acts_, profile['occurrence'])
            for act in [x for x in acts_ if x.script_offset is not None]:
                shift = next((r.get('offset') or 0 for rows_ in full_table.values() for r in rows_
                              if r['target_motion'] == motion
                              and script_for_row(rows_, full_table, game) in ('game_' + base_id, base_id)), 0)
                items, added = dress(fd.script_items(act.index), move, profile['total'], cues, motion, a.fighter, shift,
                                     sound_ids=sound_ids, first=STARTS_ON.get(a.donor, {}).get(motion, 0) + 1)
                if added:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    dressed[motion] = added
    # a chained side special: each step but the last takes the next input on the game's own frames
    # (the donor opens its follow-up while its script holds flag 0 up)
    windows = {}
    # a chain that goes on only once its first swing has hit: that step's window is written on a flag the
    # donor does not read, for the port's own code to pass on (it needs the code file and the state table)
    from fighter_port import code as code_
    gate = (CHAIN_GATE.get(a.donor) if a.fighter in own_states.CHAIN_NEEDS_HIT and a.fighter in own_states.BUILD
            and code_.toolkit(a.mextk) and fighter_json['functions'].get('moveLogicPointer')
            and (Path(a.dol) if a.dol else work.parent / 'project' / 'sys' / 'main.dol').exists() else None)
    for air in ('', 'air'):
        chain = (special_shape.get(f'{air}side') or {}).get('chain') if isinstance(special_shape.get(f'{air}side'), dict) else None
        for step, ((clip, targets), nxt) in enumerate(zip(chain or [], (chain or [])[1:])):
            move = game['moves'].get(script_for('xxx' + clip, game['moves'])) or {}
            for motion in targets:
                total = installed_motions.get(motion)
                span = chain_window(move, int(total)) if total else None
                if not span:
                    continue
                flag_ = gate if gate is not None and step == 0 else 0
                for act in [x for x in fd.actions if x.motion == motion and x.script_offset is not None]:
                    items = [i for i in fd.script_items(act.index) if not (i[0] == 19 and i[1].get('flag') == 0)]
                    items = at_frame(items, span[0], (19, {'flag': flag_, 'value': 1}, None))
                    items = at_frame(items, span[1], (19, {'flag': flag_, 'value': 0}, None))
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    windows[motion] = list(span)
    # an up special whose clip rises: the donor's own leave-the-ground command, on the frame the clip does
    rise_rule = RISE_DONOR.get(a.donor)
    if rise_rule:
        donor_fd = FighterDat(donor_pl)
        command = next(((c, dict(f), None) for act in donor_fd.actions
                        if act.motion in rise_rule['actions'] and act.script_offset is not None
                        for c, f, _ in donor_fd.script_items(act.index) if c == rise_rule['command']), None)
        risen = {}
        for stem, rows_ in full_table.items():
            for r in rows_:
                total = installed_motions.get(r['target_motion'])
                if r['target_motion'] not in rise_rule['actions'] or not total or not command:
                    continue
                at = leaves_ground(ssbh(a.root), Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'motion' / 'body' / 'c00'
                                   / f'{stem}.nuanmb', r.get('time_keys'), total)
                if at is None:
                    continue
                for act in [x for x in fd.actions if x.motion == r['target_motion'] and x.script_offset is not None]:
                    items = fd.script_items(act.index)
                    if any(c == rise_rule['command'] for c, _, _ in items):
                        continue
                    items = at_frame(items, max(1, at), command)
                    if rise_rule.get('flag') is not None:
                        flag_at = 1 if r['target_motion'] in rise_rule.get('air', ()) else max(1, at)
                        items = at_frame(items, flag_at, (19, {'flag': rise_rule['flag'], 'value': 1}, None))
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    risen[r['target_motion']] = at
        if risen:
            report['rise'] = risen
            log('up special: its clip rises; the donor leaves the ground on frame', risen)
        elif any(r['target_motion'] in rise_rule['actions'] for rows_ in full_table.values() for r in rows_):
            log("up special: its clip does not rise (the game moves it in code); it will not leave the ground")
    if windows:
        report['chain_windows'] = windows
        log('side special: the next swing can be asked for on frames', windows)
    # actions that keep the donor's script: nothing can touch the fighter on the game's frames for each, and a
    # grab reaches where and when the game's does
    written_motions = {m for p in spec['moves'] if p['id'] in done for m in p['motions']}
    placer_ = Placer(clips_dir, rig, a.donor)
    shared = {'untouchable': {}, 'grabs': {}, 'unread': []}
    for stem, rows_ in full_table.items():
        for r in rows_:
            motion, total = r['target_motion'], installed_motions.get(r['target_motion'])
            if motion in written_motions or not total or r.get('offset') or r.get('window'):
                continue
            span = shared_untouchable(game, stem, motion)
            # (the list's frames are the animation's; a clip carried at another speed shows each on another frame)
            to_frame = lambda v, keys=r.get('time_keys'): frame_at(keys, float(v) - 1.0) + 1
            for act in [x for x in fd.actions if x.motion == motion and x.script_offset is not None]:
                items, changed = fd.script_items(act.index), False
                if span:
                    first_, end_ = max(1, to_frame(span[0])), min(to_frame(span[1]), int(total))
                    new = untouchable(items, first_, end_) if first_ < end_ else None
                    if new:
                        items, changed = new, True
                        shared['untouchable'][motion] = [first_, end_ - 1]
                    else:
                        shared['unread'].append(motion)
                if motion in GRABS and r.get('id'):
                    new = regrab(items, game['moves'].get(GRABS[motion]), placer_.scale(r['id']))
                    if new:
                        items, changed = new[0], True
                        shared['grabs'][motion] = new[1]
                        # the sound of the grab: the fighter's own where its script plays one the bank holds, on the
                        # game's frame, in place of the donor's
                        own_ = [e for e in (game['moves'].get(GRABS[motion]) or {}).get('sounds') or []
                                if e.get('real') and sound_ids.get(str(e.get('name') or '').lower()) is not None]
                        if own_ and 'own_sound' in cues:
                            items = [i for i in items if i[0] != 17]
                            for e in own_:
                                items = at_frame(items, max(1, int(to_frame(e['real']))),
                                                 (17, dict(cues['own_sound'][1], sfx_id=sound_ids[e['name'].lower()]), None))
                            shared.setdefault('grab_sounds', {})[motion] = [e['name'] for e in own_]
                    else:
                        shared['unread'].append(motion)
                if changed:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
    # a counter: the donor's waiting script holds its flag up on the game's frames, and is unharmed on the game's
    counter, rule_c, where_c = None, COUNTER_DONOR.get(a.donor), COUNTER_GAME.get(a.fighter)
    if rule_c and where_c:
        from fighter_port import combat as combat_
        move_c = game['moves'].get(where_c['script']) or {}
        table_c = (game.get('own_params') or {}).get(where_c['table']) or []
        if move_c.get('counter') and len(table_c) > max(where_c['times'], where_c['least']):
            new_items = None
            for motion in rule_c['wait']:
                for act in [x for x in fd.actions if x.motion == motion and x.script_offset is not None]:
                    read = absolute(fd.script_items(act.index))
                    if read is not None:
                        body = combat_.command('set_body_collision_state')[0]
                        events = [(f, it) for f, it in read[0]
                                  if not (it[0] == 19 and it[1].get('flag') == rule_c['flag']) and it[0] != body]
                        events += [(move_c['counter'][0], (19, {'flag': rule_c['flag'], 'value': 1}, None)),
                                   (move_c['counter'][1], (19, {'flag': rule_c['flag'], 'value': 0}, None))]
                        if move_c.get('intangible'):
                            events += [(move_c['intangible'][0], combat_.command('set_body_collision_state',
                                                                                   body_state=1 if move_c.get('invincible') else 2)),
                                       (move_c['intangible'][1], combat_.command('set_body_collision_state', body_state=0))]
                        new_items = rebuilt(events, read[1])
                    if new_items is not None:               # (a script that only calls the first one takes the first one's)
                        fd.replace_script(act.index, list(new_items))
                        fd._scripts.clear()
                        fd = FighterDat(fd.to_bytes())
            counter = {'actions': sorted(x.index for x in fd.actions if x.motion in rule_c['hit']),
                       'times': float(table_c[where_c['times']]), 'least': int(round(table_c[where_c['least']])),
                       'at': rule_c['times'], 'window': list(move_c['counter'])}
            log(f"counter: a hit taken on frames {counter['window'][0]} to {counter['window'][1] - 1} is struck back for "
                f"{counter['times']} times its damage, {counter['least']} at the least")
    # the eyes on the game's own frames
    rule_e, eyed = EYES_DONOR.get(a.donor), {}
    if rule_e:
        for stem, rows_ in full_table.items():
            states_ = (game['moves'].get(script_for(stem, game['moves'])) or {}).get('faces') or []
            if not states_:
                continue
            for r in rows_:
                total_ = installed_motions.get(r['target_motion'])
                if r.get('window') or not total_:
                    continue
                for act in [x for x in fd.actions if x.motion == r['target_motion'] and x.script_offset is not None]:
                    items = [i for i in fd.script_items(act.index) if i[0] != rule_e['command']]
                    for frame, state in states_:
                        frame = int(frame) + int(r.get('offset') or 0)
                        if frame <= total_:
                            items = at_frame(items, max(1, frame), (rule_e['command'], dict(rule_e['fields'], frame=rule_e[state]), None))
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    eyed[r['target_motion']] = [list(x) for x in states_]
    if eyed:
        report['eyes'] = eyed
        log(f"eyes: set on the game's own frames in {len(eyed)} actions (a blink in "
            f"{sum(1 for v in eyed.values() if any(s == 'half' for _f, s in v))}, shut in "
            f"{sum(1 for v in eyed.values() if any(s == 'closed' for _f, s in v))})")
    # the colour a move lays over the body, on the game's own frames: played by the port's code
    flash = []
    for stem, rows_ in full_table.items():
        lit_ = (game['moves'].get(script_for(stem, game['moves'])) or {}).get('flashes') or []
        if not lit_:
            continue
        for r in rows_:
            if r.get('window') or not installed_motions.get(r['target_motion']):
                continue
            for act in [x for x in fd.actions if x.motion == r['target_motion']]:
                if not any(k[0] == act.index for k in flash):
                    flash += [(act.index, *k) for k in flash_keys(lit_, r.get('offset') or 0)]
                    if act.script_offset is not None:   # the donor's own colour animation for the action goes
                        items = fd.script_items(act.index)
                        if any(i[0] == COLANIM for i in items):
                            fd.replace_script(act.index, [i for i in items if i[0] != COLANIM])
                            fd._scripts.clear()
                            fd = FighterDat(fd.to_bytes())
    if flash:
        report['flashes'] = sorted({k[0] for k in flash})
        log(f"flashes: the body's colour on the game's own frames in {len(report['flashes'])} actions ({len(flash)} keys)")
    report['shared'] = shared
    log(f"common actions: untouchable on the game's frames in {len(shared['untouchable'])}; grabs {shared['grabs']}; "
        f"not read {sorted(set(shared['unread']))}")
    pl = fd.to_bytes()
    if any(special_shape.get(k) == 'through' for k in ('neutral', 'airneutral')) and a.donor in SHOT_DONOR and 'loops' in SHOT_DONOR[a.donor]:
        # a neutral special that does not charge: with no charge loops the donor goes from its start
        # straight through to its full release, held or not
        from vault.echo.subactions import Dat as Dat_
        d_ = Dat_(pl)
        ft_ = next(off for name, off in d_.roots if name.startswith('ftData'))
        d_.set_u32(d_.ptr(ft_ + 4) + SHOT_DONOR[a.donor]['loops'], 0)
        pl = d_.to_bytes()
        log('neutral special: one clip, so the donor charge is set to nothing and its release plays the move')
    report['dressed'] = dressed
    log(f'trails, sounds, voice: {len(dressed)} moves;',
        {k: sum(1 for v in dressed.values() for x in v if x.startswith(k)) for k in ('trail', 'swing', 'voice')})

    # (a game whose fighter numbers are Melee's own kind gives them under Melee's names itself)
    if game.get('melee_attributes'):
        ops, anotes = game['melee_attributes'], []
    else:
        from vault.echo.attributes import Attributes
        from vault.echo.subactions import FighterDat
        ops, anotes = attribute_ops(game, a.scale, Attributes(FighterDat(pl)).get('model_scale'))
    res = echo_ops.apply(pl, ops)
    pl = res.data
    report['attributes'] = {'set': len(ops), 'notes': anotes}
    log(f'attributes: {len(ops)} set')

    # a neutral special that fires: the release scripts raise a flag for the code file's shot
    from vault.echo.subactions import FighterDat
    shot, shot_note = game_shot(game, a.fighter, a.root, Placer(clips_dir, rig, a.donor).scale(
        next(r['id'] for r in cov['clips'] if r['status'] == 'compiled'))) if a.donor in SHOT_DONOR else (None, 'the donor has no charge-and-release special')
    log('neutral special:', shot_note)
    if shot:
        through = special_shape.get('neutral') == 'through'
        if through:                                     # the donor passes straight to its full release
            for sh in shot['shots']:
                sh['when'] = 'full'
        fd, rewritten = shot_scripts(FighterDat(pl), a.donor, shot, FighterDat,
                                     written={m for p in spec['moves'] if p['id'] in done for m in p['motions']},
                                     shift=-THROUGH if through else 0)
        # the release has no hitbox of the fighter's own (the shot carries it), so the hitbox writer never saw
        # its script: the game's sounds and voice for it are put on here
        release_move = game['moves'].get(SHOT_GAME[a.fighter]['move']) or {}
        for motion in SHOT_DONOR[a.donor]['release']:
            if motion in {m for p_ in spec['moves'] if p_['id'] in done for m in p_['motions']} or not installed_motions.get(motion):
                continue
            for act in [x for x in fd.actions if x.motion == motion and x.script_offset is not None]:
                # (the game's own script for this stretch of the clip: the one in the air has its own)
                stem_ = next((st for st, rows_ in full_table.items() if any(r['target_motion'] == motion for r in rows_)), None)
                its_move = game['moves'].get(script_for(stem_, game['moves'])) if stem_ else None
                items, added = dress(fd.script_items(act.index), its_move or release_move, int(installed_motions[motion]), cues,
                                     motion, a.fighter, -THROUGH if through else 0, sound_ids=sound_ids,
                                     first=STARTS_ON.get(a.donor, {}).get(motion, 0) + 1)
                if added:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    dressed[motion] = added
        # the start (a draw, a charge): its scripts were emptied of the donor's own effects; the fighter's own
        # sounds for it go on where the bank holds them (a charge that loops is left silent: its sounds would loop)
        for motion in [m for m in SHOT_DONOR[a.donor]['quiet'] if m.endswith('Start') and installed_motions.get(m)]:
            stem_ = next((st for st, rows_ in full_table.items() if any(r['target_motion'] == motion for r in rows_)), None)
            its_move = game['moves'].get(script_for(stem_, game['moves'])) if stem_ else None
            for act in [x for x in fd.actions if its_move and x.motion == motion and x.script_offset is not None]:
                items, added = dress(fd.script_items(act.index), its_move, int(installed_motions[motion]), cues, motion,
                                     a.fighter, sound_ids=sound_ids, own_only=True)
                if added:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    dressed[motion] = added
        pl = fd.to_bytes()
        report['shot'] = dict(shot, scripts=rewritten)

    # moves that hold another weapon switch the sword slot to that weapon's variant: at the start, or, for a
    # bending weapon, on the frames its own clip shows it
    fd = FighterDat(pl)
    switched, chains = {}, {}
    rows = {r['id']: r for r in cov['clips'] if r['status'] == 'compiled'}
    for c in json.loads(spec_path.read_text('utf-8'))['clips']:
        if not c.get('weapon') or c['target_motion'] not in installed_motions:
            continue
        variant = weapons.FIRST_VARIANT + weapon_order.index(c['weapon'])
        stem = c['source'].rsplit('/', 1)[1][:-7]
        on, off = 0, None
        if c['weapon'] in bending and c.get('chain_parts'):
            chains.setdefault(c['weapon'], {'variant': variant, 'clips': []})['clips'].append(
                {'motion': c['target_motion'], 'symbol': rows[c['id']]['symbol'], 'anim': rows[c['id']]['animation'],
                 'time_keys': c.get('time_keys'), 'shown': [0, None],
                 'parts': [{'stem': w, 'first': first} for w, first in c['chain_parts']]})
        elif c['weapon'] in bending:
            shown = chain_weapon.Clip(ssbh(a.root), bending[c['weapon']], stem)
            spans = [s for p in bending[c['weapon']]['parts'] for s in shown.visible(p['name'])]
            if not spans:
                continue
            last = installed_motions[c['target_motion']]
            times = [source_time(c.get('time_keys'), f) for f in range(int(last) + 1)]
            on = next((f for f, t in enumerate(times) if t >= min(s[0] for s in spans)), None)
            off = next((f for f, t in enumerate(times) if t > max(s[1] for s in spans)), None)
            if on is None:
                continue
            chains.setdefault(c['weapon'], {'variant': variant, 'clips': []})['clips'].append(
                {'motion': c['target_motion'], 'stem': stem, 'symbol': rows[c['id']]['symbol'],
                 'anim': rows[c['id']]['animation'], 'time_keys': c.get('time_keys'), 'shown': [on, off]})
        for act in [x for x in fd.actions if x.motion == c['target_motion'] and x.script_offset is not None]:
            items = fd.script_items(act.index)
            if any(code == 31 for code, _, _ in items):
                continue
            items = at_frame(items, on, (31, {'struct_id': weapons.SLOT, 'extrabitnonsense': 0, 'object_id': variant}, None))
            if off is not None:
                items = at_frame(items, off, (31, {'struct_id': weapons.SLOT, 'extrabitnonsense': 0, 'object_id': 0}, None))
            fd.replace_script(act.index, items)
            fd._scripts.clear()
            fd = FighterDat(fd.to_bytes())
            switched.setdefault(c['weapon'], []).append(c['target_motion'])
    pl = fd.to_bytes()
    (work / 'weapons.json').write_text(json.dumps(
        {'order': [w for w in weapon_order if w not in bending], 'slot': weapons.SLOT,
         'first_variant': weapons.FIRST_VARIANT, 'variants': {w: weapons.FIRST_VARIANT + i for i, w in enumerate(weapon_order)},
         'hold': 'HaveR', 'attach': WEAPON.get(a.donor), 'moves': switched, 'chains': chains, 'clip_error': a.clip_error,
         'notes': weapon_notes},
        indent=1), 'utf-8')
    report['weapons'] = switched
    log('weapons:', {k: len(v) for k, v in switched.items()}, 'moves switch to them')

    # what the game only does for its own fighters comes from the port's compiled code file
    from fighter_port import code
    kit = code.toolkit(a.mextk)
    from vault.echo.subactions import Dat
    trail, trail_note = game_trail(game, a.fighter, a.root, clips_dir, rig, a.donor, code.donor_trail(donor_pl, a.donor, Dat))
    log('trail:', trail_note)
    shot_code = None
    if shot and kit and a.donor in WEAPON:
        # each shot is an item: its data is taken from a fighter that has a simple projectile, then given its own numbers
        import struct
        import numpy as np
        from core.config import HSDRAW_EXE
        from fighter_port import items
        from shared.vanilla_extract import vanilla_refs
        from vault.echo.subactions import FighterDat as _FD
        template = Path(vanilla_refs.ensure_vanilla_ref(SHOT_TEMPLATE[0])).read_bytes()
        rule, made = SHOT_DONOR[a.donor], []
        for sh in shot['shots']:
            pl, item_index, desc = items.add_item(pl, template, SHOT_TEMPLATE[1], Dat)
            pl = items.set_own_attributes(pl, desc, [sh['speed'], sh['life']], Dat)
            pl = items.set_spin(pl, desc, 0.0, Dat)
            pl = items.set_hitbox(pl, desc, {'damage': sh['damage'], 'angle': sh['angle'], 'knockback_growth': sh['kbg'],
                                             'base_knockback': sh['bkb'], 'size': int(sh['radius'] * 256),
                                             'element': sh['element'], 'shield_damage': int(sh.get('shield_damage') or 0)}, _FD)
            if sh.get('model'):
                # the shot's own model, from the game's, turned so its length lies the way an item flies
                out_dir = work / 'items'
                model = weapons.plain_model(ssbh(a.root), a.root, a.fighter, sh['model'], out_dir / 'tex')
                long_axis = int(np.argmax(model['max'] - model['min']))
                turn = np.roll(np.eye(3), a.shot_axis - long_axis, axis=0)       # the model's long axis onto the item's
                smd, missing = weapons.write_smd({sh['model']: model}, sh['model'], shot['scale'] * turn, out_dir, [out_dir / 'tex'])
                addon, _ = weapons.build_addon(HSDRAW_EXE, smd, 0, out_dir)
                pl = items.set_model(pl, desc, addon.read_bytes(), Dat)
                log(f"shot model: {sh['model']}, {model['triangles']} triangles, "
                    f"size {np.round((model['max'] - model['min']) * shot['scale'], 2).tolist()}, textures missing {missing}")
            elif trail and trail.get('in_col'):
                # the game draws this shot with particles and has no model of it: a plain blade as tall as
                # its hitboxes, in the colour of the fighter's sword trail
                out_dir, name = work / 'items', f'blade{len(made)}'
                (out_dir / 'tex').mkdir(parents=True, exist_ok=True)
                # (a blade of light: the trail's colour let out toward white; a second version of the shot in
                # the colour of the fighter's second versions, when it has one)
                second = (trail.get('others') or {}).get(SECOND_COLOUR.get(a.fighter)) if sh.get('variant') else None
                tint = [int(c + (255 - c) * 0.45) for c in (second or trail['in_col'])[:3]]
                weapons.blade_picture(tint).save(out_dir / 'tex' / f'{name}.png')
                smd, missing = weapons.write_smd({name: weapons.blade_model(sh['height'], name)}, name, np.eye(3),
                                                 out_dir, [out_dir / 'tex'])
                addon, _ = weapons.build_addon(HSDRAW_EXE, smd, 0, out_dir)
                pl = items.set_model(pl, desc, addon.read_bytes(), Dat)
                log(f"shot model: none in the game (particles); a plain blade {sh['height']:.1f} tall stands in")
            states = rule['states'][sh['when']]
            if special_shape.get('neutral') == 'through':
                # passed straight through, the donor ends in its plain release when the button was let go
                # at once and in its full release when it is still held: the shot goes in both
                both = (rule['states']['release'], rule['states']['full'])
                states = tuple(st[0] for st in both) + tuple(st[1] for st in both)
                if sh.get('on'):
                    states = tuple(st[0 if sh['on'] == 'ground' else 1] for st in both)
            elif sh.get('on'):                          # a shot for the ground or the air only
                states = (states[0],) if sh['on'] == 'ground' else (states[1],)
            trap = None
            if sh.get('trap'):
                # it holds what it hits: a second state whose script is the hits it then makes
                pl, state = items.add_state(pl, desc, Dat)
                pl = items.set_script(pl, desc, state, sh['trap']['events'], Dat)
                trap = {'life': sh['trap']['life'], 'ahead': sh['trap'].get('ahead') or 0.0, 'lag': sh['trap'].get('lag', 1.0)}
                log(f"shot: one that holds what it hits: {len(sh['trap']['events']) - 2} more hits over {trap['life']} frames")
            beam = None
            if sh['pierce'] and not trap and sh['speed'] >= BEAM_SPEED * shot['scale']:
                beam = {'speed': float(sh['speed']), 'life': float(sh['life']), 'half': BEAM_HALF * shot['scale'],
                        'colour': BEAM_COLOUR.get(a.fighter, (255, 186, 44))}
                log(f"shot: one that crosses {sh['speed'] * sh['life']:.0f} units in {sh['life']:.0f} frames is drawn as a beam of light")
            made.append({'item': item_index, 'states': states, 'pierce': sh['pierce'], 'rise': sh.get('rise'),
                         'variant': sh.get('variant') or 0, 'on': sh.get('on'), 'trap': trap, 'beam': beam})
        if shot.get('full_charge_frame') and 'loops' in rule:
            # how long a full charge takes: the donor counts 30-frame loops after its start clip
            start = installed_motions.get(rule['start']) or 0
            loops = max(1, round((shot['full_charge_frame'] - start) / 30))
            d_ = Dat(pl)
            ft_ = next(off for name, off in d_.roots if name.startswith('ftData'))
            d_.set_u32(d_.ptr(ft_ + 4) + rule['loops'], loops)
            pl = d_.to_bytes()
            log(f"full charge: frame {shot['full_charge_frame']:.0f} in the game; {start} frames of start then {loops} loops of 30 here")
        shot_code = {'shots': made, 'joint': int(WEAPON[a.donor]['target'].split('_')[1]), 'flag': rule['flag'],
                     'onload': int(fighter_json['functions']['onLoad'])}
        report['items'] = len(made)
    # an up special that rises by its own clip: in the air the donor's multiple of the clip's travel is made 1
    if report.get('rise') and RISE_DONOR.get(a.donor, {}).get('air_scale') is not None:
        d_ = Dat(pl)
        sp_ = d_.ptr(next(off for name, off in d_.roots if name.startswith('ftData')) + 4)
        was_ = d_.f32(sp_ + RISE_DONOR[a.donor]['air_scale'])
        d_.set_f32(sp_ + RISE_DONOR[a.donor]['air_scale'], 1.0)
        pl = d_.to_bytes()
        report['rise_air_scale'] = {'was': round(was_, 4), 'now': 1.0}
        log(f"up special in the air: the donor's multiple of the clip's travel ({was_:g}) made 1")
    # a charged special: the donor's own numbers for it become the fighter's
    charge, rule_g, where_g = None, CHARGE_DONOR.get(a.donor), CHARGE_GAME.get(a.fighter)
    if rule_g and where_g:
        table_g = (game.get('own_params') or {}).get(where_g['table']) or []
        hits_g = [h['damage'] for h in (game['moves'].get(where_g['script']) or {}).get('hitboxes') or []]
        if hits_g and len(table_g) > max(where_g['levels'], where_g['step'], where_g['recoil'], where_g.get('base', 0)):
            d_ = Dat(pl)
            sp_ = d_.ptr(next(off for name, off in d_.roots if name.startswith('ftData')) + 4)
            base_g = table_g[where_g['base']] if where_g.get('base') is not None else max(hits_g)
            charge = {'levels': int(table_g[where_g['levels']]), 'base': int(round(base_g)),
                      'step': int(table_g[where_g['step']]), 'recoil': float(table_g[where_g['recoil']]), 'full': list(rule_g['full'])}
            d_.set_u32(sp_ + rule_g['loops'], charge['levels'])
            d_.set_u32(sp_ + rule_g['base'], charge['base'])
            d_.set_u32(sp_ + rule_g['step'], charge['step'])
            pl = d_.to_bytes()
            full_g = [h['damage'] for h in (game['moves'].get(where_g['script'] + SECOND) or {}).get('hitboxes') or []]
            log(f"charge: {charge['levels']} levels; damage {charge['base']} and {charge['step']} more a level; held to its "
                f"fullest {max(full_g) if full_g else charge['base'] + charge['levels'] * charge['step']:g}, which costs the fighter {charge['recoil']:g}")
    if counter:
        d_ = Dat(pl)
        sp_ = d_.ptr(next(off for name, off in d_.roots if name.startswith('ftData')) + 4)
        d_.set_f32(sp_ + counter['at'], counter['times'])
        ball_ = (game.get('own_params') or {}).get(where_c.get('bubble') or '') or []
        where_b = rule_c.get('bubble')
        if where_b and len(ball_) >= 5 and all(isinstance(v, (int, float)) for v in ball_[:5]):
            # the ball a hit must touch: the game's own, in the port's size (what it rides is a whole number there)
            d_.set_u32(sp_ + where_b['rides'], int(ball_[0]))
            for k in range(3):
                d_.set_f32(sp_ + where_b['place'] + 4 * k, float(ball_[1 + k]) * a.scale)
            d_.set_f32(sp_ + where_b['size'], float(ball_[4]) * a.scale)
            counter['bubble'] = [int(ball_[0])] + [round(float(v) * a.scale, 3) for v in ball_[1:5]]
            log(f"counter: the ball a hit must touch rides part {counter['bubble'][0]} at {counter['bubble'][1:4]}, size {counter['bubble'][4]}")
        pl = d_.to_bytes()
    armour = None
    if a.fighter in ARMOUR_GAME and a.donor in ARMOUR_DONOR:
        hits = game['moves'].get(ARMOUR_GAME[a.fighter]['script'], {}).get('hitboxes') or []
        ends = [h['last'] or h['first'] for h in hits if isinstance(h.get('first'), int)]
        if ends:
            armour = {'states': ARMOUR_DONOR[a.donor], 'first': ARMOUR_GAME[a.fighter]['first'], 'last': max(ends)}
            log(f"armour: frames {armour['first']} to {armour['last']} of the down special")
    # armour on the frames a move's own script gives it (a game that says so in the script: Brawl)
    armours, fd_a = ([armour] if armour else []), FighterDat(pl)
    for stem, rows_ in full_table.items():
        name_ = script_for(stem, game['moves'])
        twice = bool(name_) and name_ + SECOND in game['moves']
        for which_, key_ in enumerate((name_, name_ + SECOND) if twice else (name_,)):
            spans = (game['moves'].get(key_) or {}).get('armour') or []
            for r in rows_:
                acts = [x for x in fd_a.actions if x.motion == r['target_motion']]
                if twice:                                   # the first script is on the donor's first action, the second on its second
                    acts = combat_nth(acts, which_)
                acts = [x.index for x in acts]
                if r.get('window') or not acts or not installed_motions.get(r['target_motion']):
                    continue
                shift_ = r.get('offset') or 0
                armours += [{'actions': acts, 'first': first_ + shift_, 'last': end_ - 1 + shift_} for first_, end_ in spans]
    if len(armours) > (1 if armour else 0):
        log(f"armour: on {len(armours) - (1 if armour else 0)} more stretches the game's scripts give it")
    tether = None
    rule = TETHER_DONOR.get(a.donor)
    thrown = next((c for c in json.loads(spec_path.read_text('utf-8'))['clips']
                   if rule and c['target_motion'] == rule['action'] and c.get('chain_parts') and c.get('weapon') in bending), None)
    if thrown:
        far = chain_weapon.reach(ssbh(a.root), bending[thrown['weapon']], thrown['chain_parts'])
        if far and far['up'] > 0:
            scale_ = Placer(clips_dir, rig, a.donor).scale(thrown['id'])
            keys_ = thrown.get('time_keys')
            last_frame = int(installed_motions.get(rule['action']) or 0)
            times = [source_time(keys_, f) for f in range(last_frame + 1)]
            first = next((f for f, t in enumerate(times) if t >= far['first']), 0)
            last = max([f for f, t in enumerate(times) if t <= far['last']] or [first])
            tether = {'state': rule['state'], 'first': first, 'last': last, 'width': far['forward'] * scale_,
                      'y': far['up'] * scale_ / 2, 'height': far['up'] * scale_}
            # the donor's own code falls and catches ledges once its script raises these flags
            fd_ = FighterDat(pl)
            for act in [x for x in fd_.actions if x.motion == rule['action'] and x.script_offset is not None]:
                items_ = fd_.script_items(act.index)
                for flag in rule['flags']:
                    items_ = at_frame(items_, first, (19, {'flag': flag, 'value': 1}, None))
                fd_.replace_script(act.index, items_)
                fd_._scripts.clear()
                fd_ = FighterDat(fd_.to_bytes())
            pl = fd_.to_bytes()
            log(f"tether: the whip reaches {tether['width']:.1f} ahead and {tether['height']:.1f} up; "
                f"ledge catch that far on frames {first} to {last} of {rule['action']}")
    # second versions of specials (the fighter's own code picks them): each on an action of its own beside
    # the plain one, the same clip with that version's script
    alt, alt_rate, alt_next = {}, {}, {}
    fd_ = FighterDat(pl)
    rise_rule, pending = RISE_DONOR.get(a.donor), []
    for motion, script in alternates(game, full_table).items():
        normal = next((x for x in fd_.actions if x.motion == motion and x.script_offset is not None), None)
        if motion not in installed_motions or normal is None:
            continue
        stem, row = next((s, r) for s, rows_ in full_table.items() for r in rows_ if r['target_motion'] == motion)
        move = game['moves'][script]
        own_keys = move['time_keys'] if move.get('time_keys') and len(move['time_keys']) > 1 else None
        to_clip = lambda f, own_keys=own_keys, clip_keys=row.get('time_keys'): frame_at(clip_keys, script_time(own_keys, f))
        one, more = combat_spec(game, {stem: [dict(row, script=script, to_clip=to_clip)]}, a.donor, rig, a.scale,
                                installed_motions, Placer(clips_dir, rig, a.donor), tips)
        notes += more
        from fighter_port import combat
        items_ = combat.compile_move(one['moves'][0]) if one['moves'] else [(0, {}, None)]
        if not one['moves'] and move.get('intangible'):
            # a second version with no hitboxes of its own (it lets a shot go) that the game makes untouchable
            # for some frames: those frames are written all the same
            first_, last_ = (int(to_clip(v)) for v in move['intangible'])
            last_ = min(last_, int(installed_motions[motion]) - 1)
            if 1 <= first_ <= last_:
                items_ = at_frame(items_, first_, combat.command('set_body_collision_state', body_state=2))
                items_ = at_frame(items_, last_ + 1, combat.command('set_body_collision_state', body_state=0))
        items_, dressed_ = dress(items_, move, int(installed_motions[motion]), cues, motion, a.fighter, at=to_clip,
                                 sound_ids=sound_ids)                # (its own state starts it on frame 0)
        for frame, item in timed(fd_.script_items(normal.index)):
            rises = rise_rule and motion in rise_rule['actions'] and (
                item[0] == rise_rule['command'] or (item[0] == 19 and item[1].get('flag') == rise_rule.get('flag')
                                                    and item[1].get('value') == 1))
            # the weapon in the hand; the donor's leave-the-ground; and, when the game's effect and sound
            # scripts for this version did not read, the plain version's trail, swing sound and voice (the clip is the same)
            if item[0] == 31 or rises or (not dressed_ and item[0] in (49, 17, 18)):
                items_ = at_frame(items_, frame, item)
        shots_at = [f for f in move.get('article_frames') or [] if f]
        if shots_at and shot and motion in SHOT_DONOR.get(a.donor, {}).get('release', ()):
            items_ = at_frame(items_, max(1, to_clip(min(shots_at))), (19, {'flag': SHOT_DONOR[a.donor]['flag'], 'value': 1}, None))
        pending.append((motion, normal.index, items_))
        alt_rate[motion] = relative_rate(own_keys, row.get('time_keys'))
        hits_ = [h['first'] for h in move.get('hitboxes') or [] if isinstance(h.get('first'), int)]
        on_ = sorted(f['real'] for f in move.get('flags') or [] if f['cmd'] == 'on_flag' and hits_ and f['real'] > min(hits_))
        alt_next[motion] = to_clip(on_[0]) if on_ else None      # the frame its script hands on to what comes next
    if pending:
        pl, new_ = add_alternates(pl, [(index, items_) for _, index, items_ in pending])
        alt = {motion: index for (motion, _, _), index in zip(pending, new_)}
        report['alternates'] = {m: alternates(game, full_table)[m] for m in alt}
        log(f'second versions: {len(alt)} specials have one in the game; each is on an action of its own:', alt)
    slides = sorted({act.index for c in json.loads(spec_path.read_text('utf-8'))['clips'] if c.get('travel') == 'code'
                     and c['target_motion'] in installed_motions
                     for act in FighterDat(pl).actions if act.motion == c['target_motion']})
    if slides:
        log(f'travel: the code file moves the fighter during {len(slides)} actions whose donor state only slows it')
    report['travel'] = json.loads((work / 'spec' / 'travel.json').read_text('utf-8'))
    # states of the port's own (moves the donor has nothing like), after the donor's in the fighter's state table
    mine, dol = None, Path(a.dol) if a.dol else work.parent / 'project' / 'sys' / 'main.dol'
    own_motions = sorted({(v if isinstance(v, str) else v['motion']) for v in own_clips.values()})
    if own_motions and kit and dol.exists() and fighter_json['functions'].get('moveLogicPointer'):
        from fighter_port import states
        fd_ = FighterDat(pl)
        donor_rows = states.donor_states(dol.read_bytes(), int(fighter_json['functions']['moveLogicPointer']), special_count)
        index = {}
        for act in fd_.actions:
            if act.motion:
                index.setdefault(act.motion, act.index)
        state_of = {m: states.FIRST_SPECIAL_STATE + next(i for i, r in enumerate(donor_rows) if r['action'] == n)
                    for m, n in index.items() if any(r['action'] == n for r in donor_rows)}
        row = lambda m: donor_rows[state_of[m] - states.FIRST_SPECIAL_STATE]
        d_ = Dat(pl)
        common = d_.ptr(next(off for name, off in d_.roots if name.startswith('ftData')))
        world = Placer(clips_dir, rig, a.donor).scale(next(r['id'] for r in cov['clips'] if r['status'] == 'compiled')) * d_.f32(common + 0x8C)
        ctx = {'first': states.FIRST_SPECIAL_STATE + len(donor_rows), 'action': index, 'total': installed_motions,
               'state': state_of, 'functions': fighter_json['functions'], 'moves': game['moves'], 'world': world,
               'flags': {'ground': row('SpecialHi')['flags'], 'air': row('SpecialAirHi')['flags']},
               'move': dict({'up': row('SpecialHi')['move'], 'down': row('SpecialLw')['move']},
                            **({'side': row('SpecialS1')['move']} if 'SpecialS1' in state_of else {})),
               'rise': (report.get('rise') or {}).get('SpecialHi'), 'glow': OWN_GLOW.get(a.donor, 0),
               'tip': next(iter(tips.values()), None), 'commit': armour['first'] if armour else None,
               # second versions of specials: their actions, how fast each plays its clip, the frame each hands on;
               # the donor's row for each of its special actions; the flag a chain's first window waits on
               'alt': alt, 'alt_rate': alt_rate, 'alt_next': alt_next, 'row': {m: row(m) for m in state_of},
               'common_rows': states.common_by_motion(dol.read_bytes(), index),
               'gate': gate, 'rise_flag': (RISE_DONOR.get(a.donor) or {}).get('flag'),
               # for what the port's own code draws: Melee's gleam (the donor's own scripts make it too) on the
               # donor's weapon joint, and how high the fighter's head is over its feet
               'gleam': ({'gfx': EFFECT_MELEE['sys_smash_flash'], 'bone': int(WEAPON[a.donor]['target'].split('_')[1])}
                         if a.donor in WEAPON and EFFECT_MELEE['sys_smash_flash'] in cues.get('effects', {}) else None),
               'head': (stature(rig) or 16.0) * d_.f32(common + 0x8C),
               # what the game's own tables say of the fighter's specials (a game that names them), and what
               # the driver has already set up of a charge and a counter
               'own_params': game.get('own_params') or {}, 'charge': charge, 'counter': counter}
        # what the fighter's own parameter file says its code does, as far as its names resolve
        from echo_ultimate.gamedata.prc import Prc as Prc_
        vl_ = Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'param' / 'vl.prc'
        if vl_.exists():
            own_root = Prc_(vl_.read_bytes(), list(OWN_TABLES.values()) + [START_Y] + list(BOOST_FIELD) + list(OWN_NAMES)).root
            ctx['start_y'], ctx['boost'] = own_parameters(own_root)
            ctx['own'] = own_tables(own_root)
        ctx['tether'] = tether
        ctx['wall_act'] = ((game.get('motions') or {}).get('d02specialairhiwalljump') or {}).get('cancel_frame')
        kicks = [o['args'] for o in (game['moves'].get(STOMP_GAME.get(a.fighter)) or {}).get('other') or []
                 if o['cmd'] == 'ATTACK_ABS' and len(o['args']) >= 7 and all(isinstance(o['args'][i], (int, float)) for i in (2, 3, 4, 6))]
        if kicks:
            down = max(kicks, key=lambda k: k[4])
            ctx['stomp'] = {'damage': float(down[2]), 'angle': int(down[3]), 'kbg': int(down[4]), 'bkb': int(down[6])}
            log(f"own parameters: specials that start with a speed upward in the air {ctx['start_y'] or 'none'}; "
                f"numbers a state of the fighter's changes {ctx['boost'] or 'none'}")
        if a.donor in SHOT_DONOR:
            # the donor states its neutral special passes through, and the ones it lets go in (ground, air)
            sd = SHOT_DONOR[a.donor]
            ctx['n_states'] = {'ends': [sd['states']['release'][0], sd['states']['full'][0]],
                               'air_ends': [sd['states']['release'][1], sd['states']['full'][1]],
                               'all': sorted({state_of[m] for m in sd['release'] + sd['quiet'] if m in state_of}
                                             | set(sd['states']['release']) | set(sd['states']['full']))}
        if any(m in alt for m in (RISE_DONOR.get(a.donor) or {}).get('actions', ())):
            # how much higher the up special's second version goes: the one number of the up special's
            # parameter table that is 1 in its first row and more in its second
            from echo_ultimate.gamedata.prc import Prc
            vl = Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'param' / 'vl.prc'
            table_ = Prc(vl.read_bytes(), ['param_special_hi']).root.get('param_special_hi') if vl.exists() else None
            if isinstance(table_, list) and len(table_) > 1:
                more_ = [table_[1][k] for k, v in table_[0].items() if isinstance(v, float) and v == 1.0
                         and isinstance(table_[1].get(k), float) and table_[1][k] > 1.0]
                if len(more_) == 1:
                    ctx['rise_mul'] = more_[0]
        mine, why = own_states.build(a.fighter, ctx)
        if not mine:
            raise ValueError(f'{a.fighter}: own states could not be built: {why}')
        if mine:
            states.apply_iasa(donor_rows, state_of, mine.get('donor_iasa') or {})
            mine['table'] = states.table_text(donor_rows, mine['rows'])
            if mine.get('shot') and shot_code:
                # which version of the shot is let go is the port's own code's word; its states are too
                shot_code['variant'] = mine['shot']['variant']
                for sh_ in shot_code['shots']:
                    if sh_.get('variant'):
                        sh_['states'] = tuple(mine['shot']['states'][sh_.get('on') or 'ground'])
            # an action of the port's own that got no script of its own must not keep the donor's
            fd_ = FighterDat(pl)
            written = {m for p in spec['moves'] if p['id'] in done for m in p['motions']}
            stem_of = {(v if isinstance(v, str) else v['motion']): k for k, v in own_clips.items()}
            for motion in own_motions:
                for act in [x for x in fd_.actions if x.motion == motion and x.script_offset is not None]:
                    if motion not in written:
                        # ... but it has the sounds the game's script for its clip plays
                        own_move = game['moves'].get(script_for('xxx' + stem_of[motion], game['moves'])) or {}
                        items_, added_ = dress([(0, {}, None)], own_move, int(installed_motions.get(motion) or 0), cues, motion,
                                               a.fighter, sound_ids=sound_ids)
                        fd_.replace_script(act.index, items_)
                        fd_._scripts.clear()
                        fd_ = FighterDat(fd_.to_bytes())
                        if added_:
                            dressed[motion] = added_
            pl = fd_.to_bytes()
            log(f"own states: {[r['name'] for r in mine['rows']]} as states {ctx['first']} to {ctx['first'] + len(mine['rows']) - 1}")
        elif why:
            log('own states: not built:', why)
    elif own_motions:
        log('own states: not built (they need MexTK, the game executable (--dol) and the donor state table)')
    report['own_states'] = [r['name'] for r in mine['rows']] if mine else []
    if gate is not None and not (mine and f'flag{gate}' in chr(10).join(mine['source'])):
        raise SystemExit("the chain's first window waits on a hit, but the port's own code that passes it on was not built")
    if shot_code and not shot_code.get('variant'):      # no code of the port's own to say when: the plain shots only
        shot_code['shots'] = [sh_ for sh_ in shot_code['shots'] if not sh_.get('variant')]
    turn, chain_code = [], None
    state_rows = (donor_rows, mine['rows']) if mine else None
    if a.donor in ENTRY_STATES and dol.exists() and fighter_json['functions'].get('moveLogicPointer'):
        # the states a special starts in: the donor's, by the action each plays, and any of the port's own
        from fighter_port import states as states_
        fd_ = FighterDat(pl)
        rows_ = states_.donor_states(dol.read_bytes(), int(fighter_json['functions']['moveLogicPointer']), special_count)
        if state_rows is None:
            state_rows = (rows_, [])
        first_ = {}
        for act in fd_.actions:
            if act.motion:
                first_.setdefault(act.motion, act.index)
        turn = [states_.FIRST_SPECIAL_STATE + i for i, r in enumerate(rows_)
                if any(first_.get(m) == r['action'] for m in ENTRY_STATES[a.donor])]
        turn += list((mine or {}).get('entries', []))
        # a neutral special that passes the donor's start and charge states in a frame each: its first frames run on
        # into the release (and into a state of the port's own that takes the release's place), so the turn does too
        for key_, air_ in (('neutral', ''), ('airneutral', 'Air')):
            if special_shape.get(key_) != 'through' or a.donor not in SHOT_DONOR:
                continue
            sd_ = SHOT_DONOR[a.donor]
            ends_ = [sd_['states']['release'][1 if air_ else 0], sd_['states']['full'][1 if air_ else 0]]
            turn += [(states_.FIRST_SPECIAL_STATE + i, 4) for i, r in enumerate(rows_)
                     if first_.get(f'Special{air_}NLoop') == r['action']]
            turn += [(s_, max(1, 4 - THROUGH + STARTS_ON.get(a.donor, {}).get(f'Special{air_}NEnd', 0))) for s_ in ends_]
            turn += [(s_, max(1, 4 - THROUGH)) for s_ in (((mine or {}).get('shot') or {}).get('states') or {}).get(
                'air' if air_ else 'ground', []) if s_ not in ends_]
        # a chained side special: every state of the donor's chain (the donor notes an early press in a script flag)
        steps_ = {m for k in ('side', 'airside') if isinstance(special_shape.get(k), dict)
                  for _, targets in special_shape[k].get('chain') or [] for m in targets}
        if steps_ and a.donor in CHAIN_LOCK:
            chain_code = {'flag': CHAIN_LOCK[a.donor],
                          'states': [states_.FIRST_SPECIAL_STATE + i for i, r in enumerate(rows_)
                                     if any(first_.get(m) == r['action'] for m in steps_)]}
    if trail and trail.get('others'):
        trail['by_action'] = trail_colours(trail['others'], SECOND_COLOUR.get(a.fighter), full_table, game['moves'],
                                           report.get('alternates') or {}, alt, FighterDat(pl).actions)
    from . import own_jab
    jabs = own_jab.collect([p for p in spec['moves'] if p['id'] in done], FighterDat(pl).actions)
    if jabs and not kit:
        raise ValueError('source jab listeners require MexTK; refusing a build with missing input behavior')
    report['jab_listeners'] = jabs
    files, provides = code.source(a.donor, trail, shot_code, armours if len(armours) > 1 or not armour else armour, tether,
                                  slides, mine, int(fighter_json['functions']['onLoad']), turn, chain_code, counter,
                                  flash, state_rows=state_rows, jabs=jabs)
    if kit and files:
        src = work / 'code'
        src.mkdir(exist_ok=True)
        for name, text in files.items():
            (src / name).write_text(text, 'utf-8')
        pl = code.build(pl, files, kit)
        report['code'] = provides
        log('code file:', provides)
    else:
        report['code'] = []
        log('no code file:', 'nothing to provide for this donor' if not files else
            'MexTK not found (give --mextk or set MEXTK_DIR); trails will not draw')

    final = work / 'final'
    final.mkdir(exist_ok=True)
    (final / pl_name).write_bytes(pl)
    (final / aj_name).write_bytes(out_aj.read_bytes())
    (work / 'report.json').write_text(json.dumps(report, indent=1, default=str), 'utf-8')
    log('data files ready in', final)
    return report


def main(argv=None):
    from fighter_port import source_game
    ap = argparse.ArgumentParser(prog='python -m fighter_port.oneshot')
    ap.add_argument('fighter', help="Ultimate's internal fighter name (Byleth is master)")
    ap.add_argument('--donor', default='Marth')
    ap.add_argument('--root', default=os.environ.get('ULTIMATE_DUMP'), help='dump folder (romfs/data.arc, ...)')
    ap.add_argument('--game', default='ultimate', choices=('ultimate', 'brawl') + source_game.GAMES,
                    help="the game the fighter is from. brawl: --root holds the disc's extracted fighter folder "
                         "(.../fighter/<name>/Fit<Name>.pac and the rest), and the fighter's name is that folder's")
    ap.add_argument('--donor-zip', required=True, help="the donor's fighter package exported from a project")
    ap.add_argument('--work', required=True)
    ap.add_argument('--scale', type=float, default=0.88,
                    help='Ultimate units to donor units for hitbox sizes and offsets (donor height / fighter height)')
    ap.add_argument('--clip-error', type=float, default=0.002,
                    help='how far a stored clip value may sit from the true one (radians, units). The whole bank '
                         'of clips is loaded as one block: 2.42 MB loaded in game, 2.54 MB did not, and at '
                         '0.0001 a full port of 177 clips is already 2.42 MB')
    ap.add_argument('--mextk', default=None, help='the MexTK folder (MexTK.exe, mex.h, include/, melee.link) '
                    'from github.com/akaneia/m-ex; default MEXTK_DIR. Without it no code file is built')
    ap.add_argument('--dol', default=None, help="the game's executable (main.dol), for the donor's state table when the "
                    "port adds states of its own; default <work>/../project/sys/main.dol")
    ap.add_argument('--shot-axis', type=int, default=0, help="which of the item's axes (0 x, 1 y, 2 z) a projectile's length lies along")
    ap.add_argument('--own', default=None, help="the fighter keeps its OWN skeleton: the folder that holds its frozen rig, "
                    "body and rewritten fighter data (rig/, body/, data/, as fighter_port.own_skeleton.prepare leaves "
                    "them). Its clips are copied, not retargeted, and its hitboxes go on its own joints (own_route.py)")
    a = ap.parse_args(argv)
    if not a.root:
        ap.error('give --root or set ULTIMATE_DUMP')
    run(a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
