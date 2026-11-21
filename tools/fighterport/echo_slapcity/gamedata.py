"""A Slap City fighter's moves read into the shape the port driver takes a fighter in (the one
`echo_ultimate.gamedata.moves.load` gives for Ultimate, `echo_brawl.gamedata.load` for Brawl).

The moveset. Each move is a timeline of actions (`tl`: [{'af': frame, 'a': action}]); an action is a short code
whose class the game's code names (read from Assembly-CSharp's IL: `SACH` is SAConfigHitbox, `SAPA` PlayAnim ...).
Those read here:
  SAPA / SATTW  play a clip (`rt` its rate; SATTW also runs `aa` at `ta`, `ab` at `tb` and `ae` at `af`)
  SASF          set numbers: `FSAN <clip> rate` is the clip's speed from then; `FSD landlag` an aerial's landing lag
  SASHC SACH    how many hitboxes there are; hitbox `h` on shortcut `b` at offset `l`, radius `r`, its numbers prop `p`
  SARA SAEA     the hitboxes hit again / are gone
  SASI          ordinary inputs may end the move (the frame it may be acted out of), SACTM: the move goes to another
  SAPSFX        a sound by the fighter's sound bank's name, SASA: an article (a shot), SACC: a call into the code
  SAPM p_def_dodge_hrt ... p_def_hrt   untouchable between
  SAT           the action in it, `f` frames on; SAOS a list; SACT a choice (both sides read, marked)
The frame rule (from the IL): on entering a move its frame-0 actions run; each later frame first counts one more
and then runs the actions whose frame has come. Frame `af` is the move's frame af + 1 as players count (1 is the
first): a hitbox at af 3 is out on frame 4. (READING: no published frame data to hold it against.)

Which move is a special is the game's own input table (`standardSCinputTrigger` on SmashCharacter: `spN` the
neutral special ...), not a move's name: a moveset keeps leftovers nothing starts (Ittle Dew's `nspecial_v1`).
A choice with two sides (SACT with `e`) is written as its OTHER side, the plain one (a tapped special, a stick
held no way); the side it is asked first is kept apart as the move's `alternatives` (a hitbox made and made again
on one frame, which the driver drops: SPECIALS.md "A script that holds alternatives"), for the module to carry.

The numbers. Lengths are the game's units times the transcode's unit (the port's own units; the drawn scale takes
them to Melee's). Slap City's knockback is Melee's formula with its own constants (`SmashRules.Knockback` in the
IL: 0.1, 0.05, 200/(w+100), 18) and a gain that multiplies where Melee's divides by 100: the numbers are carried
by KB_BASE and KB_GAIN (STAND-IN: the formula's later constants and the launch speed per unit of knockback were
not read).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import sounds

# the moves a Melee action is played from: {Slap City move: the stem (and so the driver's move name) it is under}
MOVES = {'jab0': 'c00attack11', 'jab1': 'c00attack12', 'jab2': 'c00attack13', 'ftilt': 'c02attacks3s',
         'utilt': 'c02attackhi3', 'dtilt': 'c02attacklw3', 'fsmash': 'c03attacks4s', 'usmash': 'c04attackhi4',
         'dsmash': 'c04attacklw4', 'nair': 'c05attackairn', 'fair': 'c05attackairf', 'bair': 'c05attackairb',
         'uair': 'c05attackairhi', 'dair': 'c05attackairlw', 'strair': 'z00airfinisher',
         'grab': 'e00catch', 'grabpummel': 'e00catchattack', 'fthrow': 'e01throwf', 'bthrow': 'e01throwb',
         'uthrow': 'e01throwhi', 'dthrow': 'e01throwlw', 'getupatk': 'f03downattacku', 'climbedgeatk': 'g02cliffattack',
         'dodgestill': 'b02escapen', 'dodgefwd': 'b02escapef', 'dodgeback': 'b02escapeb', 'airdodge': 'b02escapeair',
         'tauntanim': 'j01appeallwr', 'climbup': 'g02cliffclimb', 'edgeroll': 'g02cliffescape',
         'getupfwd': 'f03downforwardu', 'getupback': 'f03downbacku', 'techrollfwd': 'f05passivestandf',
         'techrollback': 'f05passivestandb', 'entrance': 'j00entryr'}
# the specials: the stem each of the game's input table's special inputs is played under (the move is the table's)
SPECIAL_INPUTS = {'spN': 'd00specialn', 'spF': 'd01specials', 'spU': 'd02specialhi', 'spD': 'd03speciallw'}
# the ordinary moves the input table names, as the specials: a move's name is the fighter's own (Ittle Dew's jab is
# `jab0` and her smashes `fsmash`; Fishbunjin's are `jab` and `fstr`, `ustr`, `dstr`), MOVES above is hers
ATTACK_INPUTS = {'atkN': 'c00attack11', 'atkF': 'c02attacks3s', 'atkU': 'c02attackhi3', 'atkD': 'c02attacklw3',
                 'strF': 'c03attacks4s', 'strU': 'c04attackhi4', 'strD': 'c04attacklw4', 'airN': 'c05attackairn',
                 'airF': 'c05attackairf', 'airB': 'c05attackairb', 'airU': 'c05attackairhi', 'airD': 'c05attackairlw',
                 'airStr': 'z00airfinisher', 'grab': 'e00catch', 'sidestep': 'b02escapen', 'fwdRoll': 'b02escapef',
                 'bckRoll': 'b02escapeb', 'airdodge': 'b02escapeair'}
# the same script for another stem (the move plays a second clip there: in the air, lying face down)
ALSO = {'d00specialn': ['d00specialairn'], 'd01specials': ['d01specialairs'], 'd02specialhi': ['d02specialairhi'],
        'd03speciallw': ['d03specialairlw'], 'f03downattacku': ['f04downattackd'],
        # (Slap City grabs from a dash with the same grab)
        'e00catch': ['e00catchdash'],
        'f03downforwardu': ['f04downforwardd'], 'f03downbacku': ['f04downbackd'],
        # STAND-IN: Slap City has no dash attack; the forward tilt is played and strikes in its place
        'c02attacks3s': ['c00attackdash']}
CHARGED = ('fsmash', 'usmash', 'dsmash', 'strair')      # a wind-up held while the button is, then `<move>1`
ENDS = ('neutral', 'idle', 'fall', 'specialfall', 'landlag', 'landlag_lc', 'landlag_special', 'tumble', 'crouch')
JUMPS = ('jump0', 'shjump')                             # the full and the short jump, the squat's two ways out
DODGE_ON, DODGE_OFF = ('p_def_dodge_hrt', 'p_no_hrt'), ('p_def_hrt',)
# a hit does not stagger him from these (Fishbunjin's smashes, `fstr1` frames 6 to 14: `p_def_s_armor`, super armour;
# `p_def_armor` gives way above some strength, not read: STAND-IN, both as armour) until DODGE_OFF
ARMOUR_ON = ('p_def_s_armor', 'p_def_armor')
AERIALS = {'nair': 'nair_landing_lag', 'fair': 'fair_landing_lag', 'bair': 'bair_landing_lag',
           'uair': 'uair_landing_lag', 'dair': 'dair_landing_lag'}
# STAND-IN, Slap City's knockback numbers to Melee's (see the head)
KB_BASE = 0.4
KB_GAIN = 30.0
FX_ELEMENT = (('fire', 'collision_attr_fire'), ('ice', 'collision_attr_ice'), ('freez', 'collision_attr_ice'))


def frame_of(entry):
    af = entry.get('af') or 0
    return float(af) if af else float(entry.get('at') or 0.0) * 60.0


def constant(x):
    """A float source that is a plain number -> the number, else None."""
    return float(x['f']) if isinstance(x, dict) and set(x) == {'f'} else None


def events(move):
    """[(move frame, depth of choice, action)] of a move's timeline, in order of frame (leaf actions only). An action
    on the side a two-sided choice asks first comes as a copy marked `alt` (the other side is the move as written)."""
    out = []

    def both(parent, child):
        if parent is None:
            return child
        if child is None:
            return parent
        return {'all': [parent, child]}

    def walk(a, frame, cond, alt, when=None):
        if not isinstance(a, dict):
            return
        t = a.get('t')
        if t == 'SAOS':
            for x in a.get('ac') or []:
                walk(x, frame, cond, alt, when)
        elif t == 'SACT':
            walk(a.get('a'), frame, cond + 1, alt or bool(a.get('e')), both(when, a.get('ct')))
            if a.get('e'):
                walk(a.get('ea'), frame, cond + 1, alt, both(when, {'not': a.get('ct')}))
        elif t == 'SAT':
            later = constant(a.get('f'))
            if later is not None:
                walk(a.get('a'), frame + later, cond, alt, when)
        elif t in ('SAAA', 'SAOH', 'SAOC'):
            walk(a.get('a'), frame, cond + 1, alt, when)
        elif t in ('SAOL', 'SAOLE'):
            return
        elif t == 'SATTW':
            out.append((frame, cond, {'t': 'SAPA', 'a': a.get('a'), 'cfg': a.get('c') or {}, 'fs': True, **({'alt': True} if alt else {}), **({'when': when} if when is not None else {})}))
            for key, at in (('aa', 'ta'), ('ab', 'tb'), ('ae', 'af')):
                f = constant(a.get(at))
                if f is not None:
                    walk(a.get(key), frame + f, cond, alt, when)
        else:
            # Keep every enclosing condition, including both sides of nested choices, for native special logic.
            more = dict({'alt': True} if alt else {}, **({'when': when} if when is not None else {}))
            out.append((frame, cond, dict(a, **more) if more else a))
    for entry in move.get('tl') or []:
        walk(entry.get('a'), frame_of(entry), 0, False)
    order = sorted(range(len(out)), key=lambda i: (out[i][0], i))
    return [out[i] for i in order]


def end_frame(evs):
    """The move frame on which it goes on to a resting move, unconditionally (None: it never does by itself)."""
    return next((f for f, cond, a in evs if a.get('t') == 'SACTM' and not cond and a.get('tm') in ENDS), None)


def leave_end(evs, moveset, shift, part):
    """A move that goes on to another on both sides of a choice (Fishbunjin's down smash `dstr1`: on its frame 20 to a
    second slam `dstr2` while attack is held, else to its recovery `dstr1rec`): it is played as the plain side, its
    boxes taken down on the frame it leaves (the game takes them down with the move) and the recovery's frames added
    (STAND-IN: the recovery's own clip is not played; the slam's holds its last pose). -> the action's end frame as
    players count, or None."""
    for f, cond, a in evs:
        if a.get('t') != 'SACTM' or not cond or a.get('alt') or a.get('tm') not in moveset:
            continue
        if not any(f2 == f and b.get('t') == 'SACTM' and b.get('alt') for f2, _c, b in evs):
            continue
        real = int(round(f)) + 1 + shift
        for row in part['open'].values():
            row['last'] = max(row['first'], real - 1)
        part['open'] = {}
        rest = end_frame(events(moveset[a['tm']]))
        return real + (int(round(rest)) if rest is not None else 0)
    return None


def jump_frame(evs):
    """The move frame on which the squat goes on to a jump, either side of its choice (Ittle Dew's `kneebend` asks on
    its frame 5 whether jump is held: `jump0`, else `shjump`), so the frames of squat before it; None: no jump."""
    return next((f for f, _cond, a in evs if a.get('t') == 'SACTM' and a.get('tm') in JUMPS), None)


def charge_frame(evs, move_id):
    """The move frame a smash's charge starts on: the SAT that sets its clip's rate to 0."""
    for f, _cond, a in evs:
        if a.get('t') == 'SASF':
            for s in a.get('s') or []:
                g = s.get('g') or {}
                if g.get('t') == 'FSAN' and g.get('r') == 'rate' and constant(s.get('s')) == 0.0:
                    return f
    return None


def charge_release(evs, moveset, move_id, at):
    """What a held move goes on to once let go: (the move, the shift of its frames: its frame f is frame f + 1 +
    shift), or None. A smash goes on to `<move>1` (a move of its own: asked for on the frame after the charge
    begins, when not held at all); a move whose charge's own check starts a partial move there (`SAPM`, as Ittle
    Dew's neutral special starts `p_nspecial` when the button is up or 15 frames are held) goes on in it from the
    charge's own frame (tapped: the same frame, so her tap strikes on the frame her leftover `nspecial_v1` does)."""
    if move_id in CHARGED and move_id + '1' in moveset:
        return move_id + '1', int(round(at)) + 1
    # (a smash by another name, Fishbunjin's `fstr`: what its charge's own check goes to, `fstr1`)
    for f, cond, a in evs:
        if f == at and cond and a.get('t') == 'SACTM' and a.get('tm') in moveset and a.get('tm') not in ENDS:
            return a['tm'], int(round(at)) + 1
    for f, cond, a in evs:
        if f == at and cond and a.get('t') == 'SAPM' and a.get('m') in moveset and a.get('m') not in DODGE_ON + DODGE_OFF:
            return a['m'], int(round(at))
    return None


def charge_most(move, release):
    """The most a held move is held: the number its charge's check compares what it has counted with (the choice
    whose action starts `release`: `spn_charge >= 15`), or None."""
    def holds(x):
        if isinstance(x, dict):
            if x.get('t') == 'SAPM' and x.get('m') == release:
                return True
            return any(holds(v) for v in x.values())
        return isinstance(x, list) and any(holds(v) for v in x)

    def most(ct):
        if not isinstance(ct, dict):
            return None
        if ct.get('t') == 'CTC' and ct.get('w') in ('EOLarger', 'Larger') and (ct.get('a') or {}).get('t') == 'FSD':
            return constant(ct.get('b'))
        return next((m for m in (most(c) for c in ct.get('c') or []) if m is not None), None)

    def find(x):
        if isinstance(x, dict):
            if x.get('t') == 'SACT' and holds(x.get('a')):
                found = most(x.get('ct'))
                if found is not None:
                    return found
            return next((m for m in (find(v) for v in x.values()) if m is not None), None)
        if isinstance(x, list):
            return next((m for m in (find(v) for v in x) if m is not None), None)
        return None
    return find(move)


def condition(ct):
    """What a choice asks, in words when it is one plain comparison of a number the fighter keeps with a number
    ({'compare': 'EOLarger', 'of': 'FST bomb', 'with': 95.0}: her bomb's timer at least 95 frames), else as written
    (`{'not': ...}`: its other side)."""
    if not isinstance(ct, dict):
        return ct
    if set(ct) == {'not'}:
        return {'not': condition(ct['not'])}
    if set(ct) == {'all'}:
        return {'all': [condition(c) for c in ct['all']]}
    a, b = ct.get('a') or {}, ct.get('b')
    if ct.get('t') == 'CTC' and a.get('t') in ('FST', 'FSD', 'FSM', 'FSC') and constant(b) is not None:
        return {'compare': ct.get('w'), 'of': f"{a['t']} {a.get('i') or a.get('a')}", 'with': constant(b)}
    return ct


def jab_chain(moveset, first):
    """Follow the source's attack-button transitions, not numeric suffixes on move names.

    Ittle uses jab0 -> jab1 -> jab2; Tetron uses jab -> jab2. Keep at most Melee's three
    ordinary jab slots. Repeats/branches remain custom behavior, not a guessed linear chain.
    """
    def attack_condition(x):
        if isinstance(x, dict):
            if x.get('t') == 'CTI' and (x.get('i') or {}).get('t') == 'Attack':
                return True
            return any(attack_condition(v) for v in x.values())
        return isinstance(x, list) and any(attack_condition(v) for v in x)

    def targets(x, attack=False):
        if isinstance(x, dict):
            if x.get('t') == 'SACT':
                yield from targets(x.get('a'), attack or attack_condition(x.get('ct')))
                yield from targets(x.get('ea'), attack)
            else:
                if attack and x.get('t') == 'SACTM':
                    yield x.get('tm')
                for v in x.values():
                    yield from targets(v, attack)
        elif isinstance(x, list):
            for v in x:
                yield from targets(v, attack)

    chain = [first] if first in moveset else []
    while chain and len(chain) < 3:
        following = set(targets(moveset[chain[-1]])) - set(ENDS)
        if len(following) != 1:
            break
        target = following.pop()
        if target not in moveset or target in chain:
            break
        chain.append(target)
    return chain



def jab_windows(move, target):
    """Simple attack-press listeners, active from registration until removal/move end.

    Only unconditional PreMoveUpd registrations with an ordinary attack/neutral-stick guard
    fit Melee's jab gate. Resource checks, release/hold branches and delayed callbacks stay
    in source_programs for custom logic; they must not become unconditional jab cancels.
    Frames are community frames; end is exclusive.
    """
    def guard(ct):
        if not isinstance(ct, dict):
            return None
        if ct.get('t') == 'CTM' and ct.get('m') == 'All':
            parts = [guard(c) for c in ct.get('c') or []]
            return set().union(*parts) if parts and all(p is not None for p in parts) else None
        if ct.get('t') == 'CTI':
            inp = ct.get('i') or {}
            if inp.get('t') == 'Attack' and inp.get('c') == 'Down':
                return {'attack'}
            if inp.get('t') == 'CtrlSegment' and inp.get('s') == 131072 and inp.get('c') == '6':
                return {'neutral'}
        return None

    flat = []
    def walk(a, frame):
        if not isinstance(a, dict):
            return
        if a.get('t') == 'SAOS':
            for child in a.get('ac') or []:
                walk(child, frame)
        elif a.get('t') == 'SAT':
            delay = constant(a.get('f'))
            if delay is not None:
                walk(a.get('a'), frame + delay)
        else:
            flat.append((frame, a))
    for entry in move.get('tl') or []:
        walk(entry.get('a'), frame_of(entry))
    flat.sort(key=lambda row: row[0])
    end = end_frame(events(move))
    result = []
    for index, (frame, action) in enumerate(flat):
        if action.get('t') != 'SAAA' or action.get('p') != 'PreMoveUpd' or constant(action.get('f')) != 0:
            continue
        branch = action.get('a') or {}
        kinds = guard(branch.get('ct'))
        dest = branch.get('a') or {}
        if (branch.get('t') != 'SACT' or kinds is None or 'attack' not in kinds or
                dest.get('t') != 'SACTM' or dest.get('tm') != target):
            continue
        stop = next((f for f, a in flat[index + 1:] if a.get('t') == 'SADA' and
                     a.get('d') == action.get('i', '') and a.get('i') == 0), end)
        if stop is not None and stop <= frame:
            continue
        result.append(dict(start=int(round(frame)) + 1, end=None if stop is None else int(round(stop)) + 1,
                           target=target, when=condition(branch.get('ct')), neutral='neutral' in kinds))
    return result


def starting_clip(evs):
    """One active, unconditional clip at entry; zero-weight parallel clips are dormant."""
    names = list(dict.fromkeys(a.get('a') for f, cond, a in evs if f == 0 and not cond and
                              a.get('t') == 'SAPA' and (a.get('cfg') or {}).get('wg', 1) > 0))
    return names[0] if len(names) == 1 else None


def move_table(inputs, moveset=None):
    """{Slap City move: [stems]} from the fighter's input table, with MOVES as defaults.

    A control has one source move, but several controls can share that move (Asha's four specials,
    Goddess's jab and neutral air). Override by control slot before grouping by source move.
    """
    by_stem = {stem: move for move, stem in MOVES.items()}
    for key, stem in list(ATTACK_INPUTS.items()) + list(SPECIAL_INPUTS.items()):
        if isinstance(inputs.get(key), str) and inputs[key]:
            by_stem[stem] = inputs[key]
    if moveset is not None and inputs.get('atkN'):
        for stem in ('c00attack11', 'c00attack12', 'c00attack13'):
            by_stem.pop(stem, None)
        for i, move in enumerate(jab_chain(moveset, inputs['atkN']), 1):
            by_stem[f'c00attack1{i}'] = move
    out = {}
    for stem, move in by_stem.items():
        out.setdefault(move, []).append(stem)
    return out


def follow_ons(moveset, inputs, table):
    """{move: [stems]}: the moves a special goes on to by itself or by a press (SACTM anywhere in it: Fishbunjin's side
    special runs, `spfrun`, and strikes, `spfatk`), each under the stem of every clip it starts on its first frame
    (the transcode's name for the clip: `z00specialforwardground3`), so their hits, sounds and frames are read as a
    special's are and a module can put them on actions of their own. A move the table already plays, a resting
    move, a partial move (`p_...`) and a clip that has a stem already are left out."""
    from .transcode import STEMS
    # (a special's air stem is not taken: the air form of a special may be a move of its own, Fishbunjin's down
    # special goes to `spdair` in the air, which plays `specialdownair`)
    used = {stem for stems in table.values() for stem in stems}
    seen = set(table)
    todo = [inputs[k] for k in SPECIAL_INPUTS if isinstance(inputs.get(k), str) and inputs[k] in moveset]
    out = {}

    def targets(x):
        if isinstance(x, dict):
            if x.get('t') == 'SACTM' and isinstance(x.get('tm'), str):
                yield x['tm']
            for v in x.values():
                yield from targets(v)
        elif isinstance(x, list):
            for v in x:
                yield from targets(v)
    def clips_of(move):
        clips = [a.get('a') for f, _c, a in events(moveset[move]) if f == 0 and a.get('t') == 'SAPA' and a.get('a')]
        stems = [s for s in dict.fromkeys(STEMS.get(c, ['z00' + c.replace('_', '')])[0] for c in clips) if s not in used]
        if stems:
            used.update(stems)
            out[move] = stems
    # (a special's own other clips first: Fishbunjin's up special starts four, the side rise's two among them)
    for move in todo:
        clips_of(move)
    def drain():
        while todo:
            move = todo.pop(0)
            for tm in targets(moveset.get(move)):
                if tm in seen or tm not in moveset or tm in ENDS or tm.startswith('p_') or tm in JUMPS:
                    continue
                seen.add(tm)
                todo.append(tm)
                clips_of(tm)
    drain()
    # Native/custom callbacks can enter a special without any SACTM edge:
    # BCM's grab enters spf2. Preserve its entry clip and reachable programs;
    # this exports data only, never invents a transition or an input binding.
    for move, program in moveset.items():
        if move in seen or move in ENDS or move in JUMPS or move.startswith('p_'):
            continue
        if any(f == 0 and a.get('t') == 'SAPA' and str(a.get('a', '')).lower().startswith('special')
               for f, _c, a in events(program)):
            seen.add(move)
            clips_of(move)
            todo.append(move)
            drain()
    return out


class Reader:
    def __init__(self, fighter, props, summary, drawn):
        self.f, self.props, self.s, self.drawn = fighter, props, summary, drawn
        self.unit = summary['unit']
        # (speeds, a hit's radius and an offset in the world's axes: the game's one unit, without the size the
        # prefab gives the body above its clips: transcode.UNIT)
        self.world = summary.get('world_unit', summary['unit'])
        self.arm = summary['armature_scale']
        self.short = summary['shortcuts']               # shortcut -> joint

    def offset(self, local):
        """A bone-local offset (the game's, in the bone's own scaled space) in the port's joint space."""
        x, y, z = (float(v) for v in local)
        return [-x * self.arm * self.unit, y * self.arm * self.unit, z * self.arm * self.unit]

    def strikes(self, prop_id):
        """What a hitbox strikes with: its attack property's numbers (`p`) under the driver's names."""
        prop = self.props.get(prop_id) or {}
        from fighter_port.combat_values import shield_bonus
        damage = float(prop.get('dmg', 0.0)) * float(prop.get('dmgmult', 1.0))
        return {'damage': damage, 'shield_damage': shield_bonus(damage, float(prop.get('shielddmg', 1.0))),
                'angle': float(prop.get('angle', 361.0)),
                'kbg': round(float(prop.get('kbgain', 0.0)) * KB_GAIN, 2),
                'bkb': round(float(prop.get('basekb', 0.0)) * KB_BASE, 2),
                'fkb': round(float(prop.get('setkb', 0.0)) * KB_BASE, 2),
                'hitlag': float(prop.get('hitlag', 1.0)), 'prop': prop_id,
                'grab': prop.get('type') not in (0, None) and str(prop_id or '').startswith('grab')}

    def hitbox(self, a, frame, run):
        fx = str(a.get('f') or '').lower()
        joint = self.short.get(a.get('b')) or 'Hip'
        x, y, z = self.offset(a.get('l') or [0, 0, 0])
        return dict({'id': int(a.get('h', 0)), 'bone': joint.lower(),
                     'size': float(a.get('r', 0.5)) * self.world,
                     'x': x, 'y': y, 'z': z, 'first': frame, 'last': None, 'run': run,
                     'world_offset': [-float(v) * self.world if i == 0 else float(v) * self.world
                                      for i, v in enumerate(a.get('w') or [0, 0, 0])],
                     'effect': next((e for word, e in FX_ELEMENT if word in fx), 'collision_attr_normal'),
                     'targets': None, 'flags': 0}, **self.strikes(a.get('p')))

    def part(self, evs, shift, clip):
        """One move's events read with its frames moved by `shift` (move frame f is frame f + 1 + shift)."""
        out = {'hitboxes': [], 'sounds': [], 'flags': [], 'articles': [], 'article_frames': [], 'calls': [],
               'dodge': [], 'rates': [], 'cancel': None, 'landlag': None, 'catch': [], 'throws': [], 'alternatives': [], 'sets': [],
               'hit_throws': [], 'armour': [], 'source_terms': []}
        live, run, count = {}, 0, 0
        holding = False                                 # between SAHSG (the held fighter is held) and SAEG (let go)

        def close(f):
            # (a box made and taken down on the same frame strikes on that one frame: the down smash's blast)
            for row in live.values():
                row['last'] = max(row['first'], f - 1)
            live.clear()

        def again(f, ids, **change):
            # the boxes out (`ids`, None: all) go on from this frame as boxes of their own with `change` (a box made
            # on this frame is changed where it is): a box struck again (SARA) and a box given another attack
            # property (SASATP) were read as one box all the way, so the forward air struck once for the game's three
            for h, row in list(live.items()):
                if ids is not None and h not in ids:
                    continue
                if row['first'] >= f:
                    row.update(change)
                    continue
                row['last'] = f - 1
                live[h] = dict(row, first=f, last=None, **change)
                out['hitboxes'].append(live[h])
        for f, cond, a in evs:
            real = int(round(f)) + 1 + shift
            t = a.get('t')
            if t in ('SASATP', 'SARA', 'SAEA', 'SASHC'):
                term = dict(kind='hitbox',real=real,action=dict(a),choice=cond,when=a.get('when'),
                            carried_by_script=not bool(cond))
                if t == 'SASATP':
                    term['properties'] = self.strikes(a.get('p'))
                out['source_terms'].append(term)
                if cond:
                    # A resource/state predicate must not rewrite or close the ordinary hitbox path.
                    # The runtime binding owns this branch; its raw operation and predicate remain available.
                    continue
            if t == 'SACH' and cond and int(a.get('h', 0)) in live:
                # A guarded replacement must not truncate the ordinary box (or create an extra re-hit).
                # Keep its full geometry and predicate for the runtime adapter.
                row = self.hitbox(a, real, run)
                out['source_terms'].append(dict(kind='hitbox',real=real,action=dict(a),choice=cond,
                    when=a.get('when'),carried_by_script=False,hitbox=row))
                out['alternatives'].append(dict(what='hitbox replacement',real=real,hitbox=row,when=a.get('when')))
                continue
            if a.get('alt') and t in ('SACH', 'SAPSFX'):
                # the side of a choice asked first: kept apart (a hitbox ends before it begins: the driver drops it)
                if t == 'SACH':
                    row = dict(self.hitbox(a, real, run), last=real - 1, choice=cond, alternative=True)
                    out['hitboxes'].append(row)
                    row['when'] = condition(a.get('when'))
                    out['alternatives'].append({'what': 'hitbox', 'real': real, 'hitbox': row})
                else:
                    out['alternatives'].append({'what': 'sound', 'real': real, 'name': sounds.name_of(self.f.name, a.get('s'))
                                                if a.get('s') else None})
                continue
            if t == 'SAPA' and not cond:
                out['rates'].append((real, float((a.get('cfg') or {}).get('rt', 1.0)), a.get('a'), bool(a.get('fs'))))
            elif t == 'SASF':
                for s in a.get('s') or []:
                    g, v = s.get('g') or {}, constant(s.get('s'))
                    out['source_terms'].append(dict(kind='float',real=real,target=dict(g),
                        operation=s.get('w'),value=s.get('s'),choice=cond,when=a.get('when')))
                    if g.get('t') == 'FSAN' and g.get('r') == 'rate' and v is not None and not cond:
                        out['rates'].append((real, v, g.get('a'), False))
                    elif g.get('t') == 'FSD' and g.get('i') == 'landlag' and v is not None:
                        out['landlag'] = max(v, out['landlag'] or 0)
                    if g.get('t') in ('FSM', 'FSD', 'FSCH') and v is not None and not cond and s.get('w') == 'Set':
                        # what the move sets itself, plainly: its own gravity, fall speed, jump height, speeds ...
                        out['sets'].append([real, g.get('a') or g.get('i'), v])
            elif t == 'SASHC':
                close(real)
                count = int(a.get('h', 0))
            elif t == 'SACH':
                old = live.pop(int(a.get('h', 0)), None)
                if old is not None:
                    old['last'] = max(old['first'], real - 1)
                if not live and old is None:
                    run += 1
                row = self.hitbox(a, real, run)
                row['choice'] = cond
                row['when'] = condition(a.get('when'))
                live[row['id']] = row
                out['hitboxes'].append(row)
                if holding:
                    # a throw that strikes the fighter held (Fishbunjin's forward, back and up throws: a hitbox, then
                    # SAEG lets go; Ittle Dew's launch with SALG)
                    out['hit_throws'].append((real, a.get('p')))
            elif t == 'SAHSG':
                holding = bool(a.get('s', 1))
            elif t == 'SAEG':
                holding = False
            elif t == 'SARA':
                run += 1
                again(real, None, run=run)
            elif t == 'SASATP':
                # (`h` -1: every box out; the forward air's last swing strikes harder, `fair2`; the down air's
                # later frames, `dair2` and `dair3`)
                h = int(a.get('h', -1))
                again(real, None if h < 0 else {h}, **self.strikes(a.get('p')))
            elif t == 'SAEA':
                close(real)
            elif t == 'SASI' and not cond and out['cancel'] is None:
                out['cancel'] = real
            elif t == 'SAPSFX':
                # under the name the reader writes the sound by (sounds.py): the words the sound stage reads
                out['sounds'].append({'cmd': 'PLAY_SE', 'real': real, 'name': sounds.name_of(self.f.name, a.get('s')) if a.get('s') else None,
                                      'args': [], 'choice': cond, 'when': condition(a.get('when')), 'source_sfx_id': a.get('s')})
            elif t == 'SASA':
                g = a.get('g') or {}
                out['articles'].append({'real': real, 'bank': a.get('b'), 'id': a.get('id'),
                                        'bone': (self.short.get(a.get('bn')) or 'Hip').lower(),
                                        'offset': self.offset(a.get('lo') or [0, 0, 0]),
                                        # (`wo`: an offset in the world's axes, x the way she faces: READING)
                                        'world': [float(v) * self.world for v in (a.get('wo') or [0, 0, 0])],
                                        'choice': cond, 'alt': bool(a.get('alt')),
                                        'spawn': spawn_numbers(g), 'spawn_terms': spawn_terms(g),
                                        'when': condition(a.get('when'))})
                out['article_frames'].append(real)
            elif t == 'SACC':
                out['calls'].append([real, a.get('c'), cond])
                out['source_terms'].append(dict(kind='call',real=real,name=a.get('c'),choice=cond,
                                                when=a.get('when')))
            elif t == 'SAPM' and a.get('m') in DODGE_ON + DODGE_OFF:
                out['dodge'].append((real, a.get('m') in DODGE_ON))
                if not cond:
                    out['armour'].append((real, False))
            elif t == 'SAPM' and a.get('m') in ARMOUR_ON and not cond:
                out['armour'].append((real, True))
            elif t == 'SALG':
                out['throws'].append((real, a.get('p')))
        out['open'] = live
        return out


def time_keys(rates, clip_name, first, last):
    """[[frame - 1, clip frame]] from the clip's start and its rate changes, up to `last` (as players count)."""
    keys, at, clip, rate = [], first, 0.0, 1.0
    for real, r, name, from_start in sorted(rates, key=lambda x: x[0]):
        if name not in (None, clip_name):
            continue
        clip += (real - at) * rate
        at = real
        if from_start and real == first:
            clip = 0.0
        rate = r
        if not keys or keys[-1][0] != real - 1:
            keys.append([real - 1, round(clip, 4)])
        else:
            keys[-1][1] = round(clip, 4)
    if not keys or keys[0][0] != first - 1:
        keys.insert(0, [first - 1, 0.0])
    if last is not None and last - 1 > keys[-1][0]:
        keys.append([last - 1, round(clip + (last - at) * rate, 4)])
    return keys


def move_entry(rd, moveset, move_id, stem):
    """One Melee action's entry from a Slap City move (and its release, for a charged one)."""
    evs = events(moveset[move_id])
    chain = jab_chain(moveset, move_id) if stem in ('c00attack11', 'c00attack12') else []
    clip = next((a.get('a') for f, cond, a in evs if a.get('t') == 'SAPA' and not cond), None)
    parts, flags = [], []
    at = charge_frame(evs, move_id)
    release = charge_release(evs, moveset, move_id, at) if at is not None else None
    if release is not None:
        head = [e for e in evs if e[0] <= at]
        parts.append(rd.part(head, 0, clip))
        hold = int(round(at)) + 1                       # the frame the clip stops for the charge
        flags.append({'cmd': 'on_flag', 'real': hold, 'which': 'charge'})
        parts[0]['rates'].append((hold, 0.0, clip, False))
        then, shift = release
        if then != move_id + '1' and not any(f == at and a.get('t') == 'SACTM' and a.get('tm') == then for f, _c, a in evs):
            # (a partial move sets nothing of the clip's: the check that starts it puts the clip's rate back to 1)
            parts[0]['rates'].append((hold, 1.0, clip, False))
        evs2 = events(moveset[then])
        parts.append(rd.part(evs2, shift, clip))
        end = end_frame(evs2)
        end = None if end is None else int(round(end)) + 1 + shift
        if end is None:
            end = leave_end(evs2, moveset, shift, parts[-1])
    else:
        parts.append(rd.part(evs, 0, clip))
        end = end_frame(evs)
        end = None if end is None else int(round(end)) + 1
    hits = [h for p in parts for h in p['hitboxes']]
    last_frame = (end - 1) if end else None
    for p in parts:
        for row in p['open'].values():
            row['last'] = last_frame
    rates = [r for p in parts for r in p['rates']]
    cancel = next((p['cancel'] for p in parts if p['cancel']), None)
    dodge = sorted(x for p in parts for x in p['dodge'])
    on = next((f for f, state in dodge if state), None)
    off = next((f for f, state in dodge if not state and on is not None and f > on), None)
    intangible = [on, off - 1] if on is not None and off is not None else None
    # armour: [the frame it is on from, the frame it ends on] (as Brawl's reader gives it); one not ended by the
    # move ends with it
    armour, since = [], None
    for f, state in sorted(x for p in parts for x in p['armour']):
        if state and since is None:
            since = f
        elif not state and since is not None and f > since:
            armour.append([since, f])
            since = None
    if since is not None and end:
        armour.append([since, end])
    stop = (cancel - 1) if cancel else last_frame
    entry = {'hitboxes': [h for h in hits if h['first'] <= (last_frame or 10 ** 6)], 'other': [], 'motion_rates': [],
             'jab_followup_windows': jab_windows(moveset[move_id], chain[1]) if len(chain) > 1 else [],
             'flags': flags, 'turns': [], 'articles': [a for p in parts for a in p['articles']],
             'article_frames': [f for p in parts for f in p['article_frames']],
             'cancel_frame_script': cancel, 'cancel_frame_real': cancel, 'intangible': intangible, 'catch_end': None,
             'invincible': False, 'armour': armour, 'momentum': [], 'ledge_grab': None, 'counter': None, 'effects': [],
             'flashes': [], 'sounds': [s for p in parts for s in p['sounds'] if s['name']],
             'calls': [c for p in parts for c in p['calls']], 'faces': [],
             'time_keys': time_keys(rates, clip, 1, stop + 1 if stop else None),
             'alternatives': [x for p in parts for x in p['alternatives']],
             'sets': [x for p in parts for x in p['sets']],
             'source_terms': [x for p in parts for x in p['source_terms']],
             # a held move: the frame its clip stops on, and the move it goes on to once let go
             'charge': {'from': flags[0]['real'], 'release': release[0], 'most': charge_most(moveset[move_id], release[0])}
             if release else None,
             'entry_clips': [{'clip': a.get('a'), 'when': condition(a.get('when')), 'choice': c,
                              'weight': (a.get('cfg') or {}).get('wg', 1)}
                             for f, c, a in evs if f == 0 and a.get('t') == 'SAPA'],
             'animation': stem + '.nuanmb', 'slapcity_move': move_id, 'clip': clip, 'end': end,
             'landing_lag': max([p['landlag'] for p in parts if p['landlag'] is not None] or [0]) or None}
    # a grab's boxes are the catch: Melee's CATCH, out from their first frame to their last
    grabs = [h for h in entry['hitboxes'] if str(h.get('prop', '')).startswith('grab')]
    if grabs:
        entry['hitboxes'] = [h for h in entry['hitboxes'] if h not in grabs]
        for h in grabs:
            entry['other'].append({'cmd': 'CATCH', 'real': h['first'], 'args': [h['id'], h['bone'], h['size'], h['x'], h['y'], h['z'],
                                                                                 h['x'], h['y'], h['z'], 0, None]})
        entry['catch_end'] = max(h['last'] or h['first'] for h in grabs) + 1
    # a throw: the launch (SALG) with its prop's numbers, then the release; with no launch, the first hit on the
    # fighter held is the throw (its hitbox is kept: it strikes the others near too)
    throws = [t for p in parts for t in p['throws']] or [t for p in parts for t in p['hit_throws']][:1]
    for real, prop_id in throws:
        prop = rd.props.get(prop_id) or {}
        entry['other'].append({'cmd': 'ATTACK_ABS', 'real': real,
                               'args': [0, 'top', float(prop.get('dmg', 0)), float(prop.get('angle', 45)),
                                        round(float(prop.get('kbgain', 0)) * KB_GAIN, 2), round(float(prop.get('setkb', 0)) * KB_BASE, 2),
                                        round(float(prop.get('basekb', 0)) * KB_BASE, 2)]})
        entry['other'].append({'cmd': 'ATK_HIT_ABS', 'real': real, 'args': []})
    return entry


def attributes(base, moveset, unit, drawn, rise_speed, landing):
    """The fighter's numbers under Melee's names, in Melee's units a frame. `rise_speed(height, gravity)`: the
    driver's (a jump's starting speed to reach a height).

    How the game moves a fighter (`SmashCharacter.UpdMoveVel` in the IL), each a step toward a speed: on the ground,
    with the stick let go, toward 0 by floorbrake x floorfriction (Melee's `friction`); in the air with the stick let
    go, toward 0 by `airdecay` (Melee's +0x70, `air_friction`; `airbrake` is never read there: it brakes the
    game's articles); steering, toward airspeed x stick by `airacc`, the same step however far the stick leans.
    Melee steers by stick x +0x64 plus a flat +0x68 in the stick's direction (ftcommon.c), so the game's step is all
    flat part: +0x64 `aerial_speed` 0 and +0x68 `aerial_friction` the step (the first port wrote the step into the
    part the stick multiplies and left the donor's flat part on top)."""
    length = unit * drawn                               # Melee units per game unit
    per_frame = length / 60.0
    per_frame2 = length / 3600.0
    jumps = {}
    for move_id, key in (('jump0', 'full'), ('shjump', 'short'), ('jump1', 'air')):
        for _f, _c, a in events(moveset.get(move_id, {})):
            if a.get('t') == 'SASF':
                for s in a.get('s') or []:
                    if (s.get('g') or {}).get('i') == 'jumpheight' and constant(s.get('s')) is not None:
                        jumps[key] = constant(s.get('s')) * length
    gravity = float(base['gravity']) * per_frame2
    squat = jump_frame(events(moveset.get('kneebend', {})))
    out = {'initial_dash_speed': float(base['floordashspeed']) * per_frame,
           'initial_run_speed': float(base['floorrunspeed']) * per_frame,
           'max_walk_speed': float(base['floorrunspeed']) * per_frame,      # (no walk of its own: the run's speed)
           'friction': float(base['floorbrake']) * float(base.get('floorfriction', 1.0)) * per_frame2,
           'gravity': gravity,
           'terminal_velocity': float(base['fallSpeed']) * per_frame,
           'fast_fall_terminal_velocity': float(base['fastFallSpeed']) * per_frame,
           'max_aerial_horizontal_speed': float(base['airspeed']) * per_frame,
           'aerial_speed': 0.0,
           'aerial_friction': float(base['airacc']) * per_frame2,
           'air_friction': float(base['airdecay']) * per_frame2,
           'weight': float(base['weight'])}
    if squat is not None:
        out['jump_startup_lag'] = float(int(round(squat)))
    if 'full' in jumps:
        full = rise_speed(jumps['full'], gravity)
        out['initial_vertical_jump_velocity'] = full
        if 'short' in jumps:
            out['max_shorthop_vertical_velocity'] = rise_speed(jumps['short'], gravity)
        if 'air' in jumps:
            out['vertical_air_jump_multiplier'] = rise_speed(jumps['air'], gravity) / full
    out.update({melee: float(v) for melee, v in landing.items()})
    return out, jumps


def hurtboxes(rd, moveset, skeleton_rest):
    """The fighter's hurtboxes (`p_def_hrt`) as own_data takes them: [dict(bone, a, b, radius, height, part)], each
    capsule on its first bone; an end on a second bone is put in the first's space at rest."""
    rows = []
    for _f, _c, a in events(moveset['p_def_hrt']):
        if a.get('t') != 'SASH':
            continue
        for h in (a.get('h') or {}).get('h') or []:
            ja, jb = rd.short.get(h['ba']), rd.short.get(h['bb'])
            if ja not in skeleton_rest:
                raise ValueError(f'hurtbox start bone {h["ba"]!r} is not on the source skeleton')
            pa, pb = rd.offset(h.get('loa') or [0, 0, 0]), rd.offset(h.get('lob') or [0, 0, 0])
            if not h['bb']:
                # HurtSet.ApplySetup only adds a second track when one resolves. An absent end is a sphere.
                jb, pb = ja, list(pa)
            elif jb not in skeleton_rest:
                raise ValueError(f'hurtbox end bone {h["bb"]!r} is not on the source skeleton')
            if jb != ja:
                wa, wb = np.asarray(skeleton_rest[ja]), np.asarray(skeleton_rest[jb])
                pb = list((np.linalg.inv(wa) @ wb @ np.array(pb + [1.0]))[:3])
            word = h['ba']
            height = ('hit_height_high' if word in ('head', 'body') else
                      'hit_height_low' if any(k in word for k in ('hip', 'knee', 'heel', 'foot')) else 'hit_height_center')
            part = ('collision_part_head' if word == 'head' else
                    'collision_part_body_legs' if height == 'hit_height_low' else 'collision_part_body')
            rows.append(dict(bone=ja, a=[float(v) for v in pa], b=[float(v) for v in pb],
                             radius=float(h['r']) * rd.world, height=height, part=part))
    return rows


def spawn_numbers(g):
    """What an article is given as it is made (SASA's `md`: Velocity, Gravity ...): {name: [x, y]}, each the number
    a plain one is, or the number that multiplies the facing (`forwarddir`); a part read from the stick or anything
    else is None."""
    def num(src):
        if not isinstance(src, dict):
            return None
        if set(src) == {'f'}:
            return float(src['f'])
        if src.get('t') == 'FSF' and src.get('fw') == 'Mult':
            a, b = src.get('fa') or {}, src.get('fb') or {}
            for x, y in ((a, b), (b, a)):
                if x.get('t') == 'FSM' and x.get('a') == 'forwarddir' and set(y) == {'f'}:
                    return float(y['f'])
        if src.get('t') == 'FSF' and src.get('fw') == 'Add':
            parts = [num(src.get('fa')), num(src.get('fb'))]
            return None if None in parts else sum(parts)
        return None
    out = {}
    for row in g.get('md') or []:
        o = row.get('o') or {}
        if o.get('t') == 'OSV2':
            out[row.get('i')] = [num(o.get('x')), num(o.get('y'))]
    return out


def spawn_terms(g):
    """The same numbers as sums of terms, each a number times what it is read from: {name: [x, y]}, each
    {'1': a plain number, 'forwarddir': times the facing, 'ctrlXRaw': times the stick across (-1 to 1, not turned by
    the facing), 'ctrlY': times the stick up ...}, or None where a part is neither (Ittle Dew's bomb is thrown at
    5 the way she faces plus 7.5 the stick across, and 15 plus 5 the stick up)."""
    def terms(src):
        if not isinstance(src, dict):
            return None
        if set(src) == {'f'}:
            return {'1': float(src['f'])}
        t = src.get('t')
        if t in ('FSM', 'FSI'):
            return {src.get('a') or src.get('i'): 1.0} if (src.get('a') or src.get('i')) else None
        if t == 'FSF' and src.get('fw') == 'Add':
            a, b = terms(src.get('fa')), terms(src.get('fb'))
            if a is None or b is None:
                return None
            return {k: a.get(k, 0.0) + b.get(k, 0.0) for k in {**a, **b}}
        if t == 'FSF' and src.get('fw') == 'Mult':
            a, b = terms(src.get('fa')), terms(src.get('fb'))
            for x, y in ((a, b), (b, a)):
                if x is not None and y is not None and set(x) == {'1'}:
                    return {k: v * x['1'] for k, v in y.items()}
        return None
    out = {}
    for row in g.get('md') or []:
        o = row.get('o') or {}
        if o.get('t') == 'OSV2':
            out[row.get('i')] = [terms(o.get('x')), terms(o.get('y'))]
    return out


def projectiles(f):
    """{article id: the numbers of its `SmashProjectile`}: what it strikes with (`atkprop`), its hit's size, how far
    it goes, how many hits and bounces end it, how soon it strikes one again, its own speed and gravity (in the
    game's units, a second)."""
    out = {}
    for bank in f.articles().values():
        for art_id, obj in bank.items():
            if obj is None or obj.type.name != 'MonoBehaviour' or f.game.script(obj) != 'SmashProjectile':
                continue
            d = f.game.mono(obj)
            # (refreshAtkFrames: the frames after which it may strike the same one again; 0 never: Ittle Dew's
            # full-charge fireball strikes every frame up to its six hits)
            keep = ('atkprop', 'hitSize', 'topnsize', 'deactivateAfterDist', 'deactivateAfterFrames', 'deactivateAfterHits',
                    'deactivateAfterBounces', 'deactFrames', 'passthroughVertical', 'passthroughHorizontal',
                    'refreshAtkFrames', 'bounceAngleMin', 'bounceVelMult', 'minVel', 'collidestage', 'legacyCollision')
            row = {k: d.get(k) for k in keep}
            row.update(move_vel=[d['move_vel']['x'], d['move_vel']['y']], gravity=[d['gravity']['x'], d['gravity']['y']])
            out[art_id] = row
    return out


def article_numbers(f):
    """{article id: its numbers} of each article that is not a `SmashProjectile` (`projectiles` reads those): its
    script's name, its plain fields (`plain_fields`) and each attack property it holds (Ittle Dew's bomb: `atkprop`
    its blast's, `atkpropfly` its touch's in flight, `fuselength` ...)."""
    out = {}
    for bank in f.articles().values():
        for art_id, obj in bank.items():
            if obj is None or obj.type.name != 'MonoBehaviour' or f.game.script(obj) == 'SmashProjectile':
                continue
            d = f.game.mono(obj)
            row = dict(plain_fields(d), script=f.game.script(obj))
            row.update({k: v for k, v in d.items() if isinstance(v, dict) and {'dmg', 'angle', 'basekb'} <= set(v)})
            # where each of its own parts it names stands about its point, in the game's units (x mirrored as the
            # port's): its `hitbox` is where its hits are made about
            from .transcode import node_worlds
            go = obj.read().m_GameObject.read()
            places = {node.m_Name: m for node, m in node_worlds(f, next(c.read() for c in f.components(go, 'Transform')))}
            row['places'] = {}
            for k, ref in d.items():
                if isinstance(ref, dict) and set(ref) == {'m_FileID', 'm_PathID'} and ref['m_PathID']:
                    target = f.game.deref(obj.assets_file, ref)
                    if target is not None and target.type.name in ('Transform', 'GameObject'):
                        tgo = target.read() if target.type.name == 'GameObject' else target.read().m_GameObject.read()
                        m = places.get(tgo.m_Name)
                        if m is not None:
                            row['places'][k] = [float(-m[0, 3]), float(m[1, 3])]
            out[art_id] = row
    return out


def plain_fields(d):
    """A component's fields that are numbers, words or vectors ({x, y[, z]} as a list): what a custom call's code
    reads besides the objects it moves (those are left out)."""
    out = {}
    for k, v in d.items():
        if k.startswith('m_'):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) or isinstance(v, str) and len(v) <= 64:
            out[k] = v
        elif isinstance(v, dict) and set(v) in ({'x', 'y'}, {'x', 'y', 'z'}):
            out[k] = [float(v[a]) for a in ('x', 'y', 'z') if a in v]
    return out


def transform_fields(t):
    """Prefab-local placement and parent TRS chain, including nonuniform scale and rotation.

    The article root is instantiated at a new position; retain its rotation and scale, but not its position.
    Paths also identify the transforms changed by referenced tween components.
    """
    from .fighter import trs
    chain = []
    for _ in range(64):
        p, q, s = t.m_LocalPosition, t.m_LocalRotation, t.m_LocalScale
        chain.append(dict(name=t.m_GameObject.read().m_Name, t=[p.x, p.y, p.z],
                          q=[q.x, q.y, q.z, q.w], s=[s.x, s.y, s.z]))
        if not t.m_Father.path_id:
            break
        t = t.m_Father.read()
    else:
        raise ValueError('Custom-call transform parent chain is cyclic or too deep')
    chain.reverse()
    chain[0]['t'] = [0.0, 0.0, 0.0]
    matrix = np.eye(4)
    for node in chain:
        matrix = matrix @ trs(node['t'], node['q'], node['s'])
    return dict(at=[round(float(x), 5) for x in matrix[:3, 3]],
                path='/'.join(n['name'] for n in chain), chain=chain)


def deep_fields(game, owner, d, depth=1):
    """`plain_fields`, and what a custom call keeps in lists and in the things it makes: a list of records is read
    record by record, a nested record of numbers as its plain fields (an attack property), and a reference to
    another script (`depth` deep) as that script's fields, a reference to a place (a Transform) as `{'at': [x, y,
    z]}` plus its parent TRS chain (`transform_fields`). Pointer arrays preserve their order and unresolved slots.
    Referenced components include their own transform so a tween can be matched to its hitbox tracks.
    Fishbunjin's down special
    (`FishbunjinSelectSpecialDownShockwaveCC`) keeps its waves so: `waves`, each `afterSeconds` and the
    `FishbunjinShockwave` it makes, whose own `waves` are hit balls on places (`track`) with `radius` and `atkprop`."""
    out = plain_fields(d)
    def reference(v):
        obj = game.deref(owner, v)
        if obj is None:
            return None
        if obj.type.name == 'MonoBehaviour' and depth > 0:
            data = game.mono(obj)
            sub = dict(deep_fields(game, obj.assets_file, data, depth - 1), script=game.script(obj))
            go = game.deref(obj.assets_file, data.get('m_GameObject', {}))
            if go is not None:
                for component in go.read().m_Components:
                    target = component.deref()
                    if target.type.name == 'Transform':
                        sub['transform'] = transform_fields(target.read())
                        break
            return sub
        if obj.type.name == 'Transform':
            return transform_fields(obj.read())
        return None
    for k, v in d.items():
        if k.startswith('m_') or k in out:
            continue
        if isinstance(v, dict) and 'm_PathID' in v:
            sub = reference(v)
            if sub is not None:
                out[k] = sub
        elif isinstance(v, dict):
            sub = plain_fields(v)
            if sub:
                out[k] = sub
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            rows = [reference(x) if 'm_PathID' in x else deep_fields(game, owner, x, depth) for x in v]
            if any(x is not None for x in rows):
                out[k] = rows  # keep list positions, including unresolved references
    return out


def custom_calls(f):
    """{script: its fields} of each custom call on the fighter (`CustomCallMB`: the code a move's `SACC`
    calls into by name, such as Ittle Dew's `IttleDewTeleportCC` with the ball's speed and first way): `deep_fields`."""
    out = {}

    def walk(tr):
        go = tr.m_GameObject.read()
        for c in f.components(go, 'MonoBehaviour'):
            name = f.game.script(c)
            if name.endswith('CC') or name.endswith('CustomCall'):
                # Custom call -> article -> updater -> concrete motion. The old one-hop read omitted
                # ProxyUpdater arrays, turning moving article hitboxes into stationary ones.
                data = deep_fields(f.game, c.assets_file, f.game.mono(c), depth=4)
                shortcut = next((b for b in (f.character.get('useBones') or {}).get('shortcuts', [])
                                 if b.get('id') == data.get('spawnOnBone')), None)
                if shortcut:
                    target = f.ref(shortcut['bone'])
                    if target is not None:
                        data['spawnTransform'] = transform_fields(target.read())
                out[name] = data
        for ch in tr.m_Children:
            walk(ch.read())
    walk(next(c.read() for c in f.components(f.prefab, 'Transform')))
    return out


def clip_frame(keys, real):
    """The clip's frame on a frame of the move (1-based), from its time keys ([[frame - 1, clip frame], ...])."""
    keys = sorted(keys or [[0, 0.0]])
    xs, ys = [k[0] for k in keys], [k[1] for k in keys]
    if len(keys) == 1:
        return ys[0] + (real - 1 - xs[0])
    if real - 1 > xs[-1]:
        return ys[-1] + (real - 1 - xs[-1])
    return float(np.interp(real - 1, xs, ys))


def world_hit_offsets(moves, sk):
    """Bake source world offsets back into each animated bone's local space.

    SAConfigHitbox passes independent local and world offsets to TrackTransform:
    TransformPoint(local) + world. A world vector cannot be added directly to a
    bone-local vector: rotations and scale would distort it. Keep source run/id
    when splitting spans so native position updates retain their hit history.
    """
    lower = {j.lower(): j for j in sk.names}
    cache = {}
    for entry in moves.values():
        clip = sk.clips.get(entry.get('clip'))
        expanded = []
        for hit in entry.get('hitboxes') or []:
            offset = np.asarray(hit.get('world_offset') or [0, 0, 0], float)
            if not np.any(offset) or hit.get('last') is None or hit['last'] < hit['first']:
                expanded.append(hit)
                continue
            if clip is None:
                raise ValueError(f'{entry.get("clip")}: world-offset hitbox needs its source clip')
            joint = lower.get(hit['bone'])
            if joint is None:
                raise ValueError(f'{entry.get("clip")}: world-offset hitbox has unknown joint {hit["bone"]}')
            for frame in range(int(hit['first']), int(hit['last']) + 1):
                source_frame = clip_frame(entry.get('time_keys'), frame)
                key = (entry['clip'], source_frame)
                if key not in cache:
                    cache[key] = sk.joint_worlds(sk.pose(clip, source_frame))
                matrix = np.asarray(cache[key][joint], float)
                local = np.asarray([hit['x'], hit['y'], hit['z']], float)
                local += np.linalg.solve(matrix[:3, :3], offset)
                expanded.append(dict(hit, first=frame, last=frame, world_offset_baked=True,
                                     **dict(zip(('x', 'y', 'z'), map(float, local)))))
        entry['hitboxes'] = expanded


def grabs_on_top(moves, sk):
    """Ultimate's grab boxes are placed in the fighter's own space (`top`: its place on the ground, Y up, Z ahead),
    and the driver reads only those (oneshot.grab_boxes). Slap City's sit on a bone: each is put where that bone is
    on the frame the box comes out, in the clip the move plays (`sk`: transcode.Skeleton). Changed in place."""
    lower = {j.lower(): j for j in sk.names}
    for e in moves.values():
        rows = [o for o in e.get('other') or [] if o['cmd'] == 'CATCH' and o['args'][1] != 'top']
        clip = sk.clips.get(e.get('clip'))
        if not rows or clip is None:
            continue
        for o in rows:
            a = o['args']
            w = sk.joint_worlds(sk.pose(clip, clip_frame(e.get('time_keys'), o['real'])))
            at = w[lower.get(a[1], 'Hip')] @ np.array([a[3], a[4], a[5], 1.0])
            x, y, z = (float(v) for v in at[:3] - w['Trans'][:3, 3])
            o['args'] = [a[0], 'top', a[2], x, y, z, x, y, z, 0, None]
            o['from_bone'] = a[1]
    # and where each article is made, in the same space (the port's own code makes them: a shot at a point)
    for e in moves.values():
        clip = sk.clips.get(e.get('clip'))
        for art in e.get('articles') or []:
            if clip is None:
                continue
            w = sk.joint_worlds(sk.pose(clip, clip_frame(e.get('time_keys'), art['real'])))
            at = w[lower.get(art['bone'], 'Hip')] @ np.array([*art['offset'], 1.0])
            art['top'] = [float(v) for v in at[:3] - w['Trans'][:3, 3]]


def read_moves(rd, moveset, inputs):
    """Read each source script into every control slot that uses it, plus its follow-on states."""
    moves, motions = {}, {}
    table = move_table(inputs, moveset)
    plays = {m: list(dict.fromkeys(s for stem in stems for s in [stem] + ALSO.get(stem, [])))
             for m, stems in table.items()}
    for m, stems in follow_ons(moveset, inputs, table).items():
        for other in plays.values():
            other[:] = [s for s in other if s not in stems]
        plays[m] = plays.get(m, []) + stems
    for move_id, stems in plays.items():
        if move_id not in moveset or not stems:
            continue
        stem = stems[0]
        entry = move_entry(rd, moveset, move_id, stem)
        for s in stems:
            e = dict(entry, animation=s + '.nuanmb')
            moves['game_' + s[3:]] = e
            if e['cancel_frame_real'] or e['intangible']:
                motions[s] = {'game': 'game_' + s[3:], 'cancel_frame': e['cancel_frame_real'], 'intangible': e['intangible']}
    return moves, motions


def source_sound_receipts(moves, entries):
    """SAPlaySFX calls only the fighter bank; SmashSFXBank.PlaySFX ignores an absent id.

    Inspect source ids, not exported WAVs: a failed decode of an existing id is still a port omission.
    The lookup in the source game is case-sensitive even though the port's sound names are lower-case.
    """
    ids={e['id'] for e in entries}
    for move in moves.values():
        for event in move.get('sounds') or []:
            if 'source_sfx_id' in event:
                name=event['source_sfx_id']
                event['source_sound']=dict(id=name,bank='fighter',exists=name in ids)


def load(fighter, root, drawn=None, game=None):
    """-> the driver's `game` for a fighter transcoded under `root` (`transcode.write`'s slapcity.json beside it),
    read again from the game's folder named in that file (or `game`, an open `unity.Game`)."""
    from fighter_port.oneshot import rise_speed
    folder = Path(root) / 'gamedata' / 'fighter' / fighter
    summary = json.loads((folder / 'slapcity.json').read_text('utf-8'))
    if game is None:
        from .unity import Game
        game = Game(summary['data_dir'])
    from .fighter import Fighter
    f = Fighter(game, summary['fighter'])
    if drawn is None:
        from fighter_port import own_data
        drawn = own_data.default_scale(own_data.DONOR['Marth'])
    props = f.props()
    moveset = f.moveset()
    rd = Reader(f, props, summary, drawn)
    moves, motions = read_moves(rd, moveset, f.character.get('standardSCinputTrigger') or {})
    source_sound_receipts(moves, f.sound_bank()['entries'])
    from .transcode import Skeleton
    skeleton = Skeleton(f)
    world_hit_offsets(moves, skeleton)
    grabs_on_top(moves, skeleton)
    landing = {melee: moves['game_' + MOVES[m][3:]]['landing_lag'] for m, melee in AERIALS.items()
               if moves.get('game_' + MOVES[m][3:], {}).get('landing_lag')}
    base = f.base()
    att, jumps = attributes(base, moveset, summary.get('world_unit', summary['unit']), drawn, rise_speed, landing)
    melee = [{'op': 'set_attribute', 'name': k, 'value': float(v)} for k, v in att.items()]
    rest = {}
    import ssbh_data_py as ssbh
    skel = ssbh.skel_data.read_skel(str(folder / 'model' / 'body' / 'c00' / 'model.nusktb'))
    names = [b.name for b in skel.bones]
    for b in skel.bones:
        m = np.asarray(b.transform, float).T
        rest[b.name] = rest[names[b.parent_index]] @ m if b.parent_index is not None else m
    tables = dict(hurt=hurtboxes(rd, moveset, rest),
                  ecb=[dict(bone=j, offset=[0.0, 0.0, 0.0]) for j in summary.get('collision_joints') or
                       [j for j in ('Hip', 'Head', 'HandL', 'HandR', 'FootL', 'FootR') if j in rest]])
    return {'fighter': fighter, 'game': 'slapcity', 'attributes': {}, 'melee_attributes': melee, 'moves': moves,
            'projectiles': projectiles(f), 'articles': article_numbers(f), 'custom_calls': custom_calls(f),
            'article_models': summary.get('articles') or {}, 'call_pictures': summary.get('call_pictures') or {},
            # `unit`: port units per game unit for speeds and distances (what the modules read); `body_unit`: on the
            # body, with the size the prefab gives it above its clips (transcode.UNIT)
            'unit': summary.get('world_unit', summary['unit']), 'body_unit': summary['unit'],
            'kb': {'base': KB_BASE, 'gain': KB_GAIN},
            'specials': {k: v for k, v in (f.character.get('standardSCinputTrigger') or {}).items() if k in SPECIAL_INPUTS},
            # Lossless source programs retain loops, recurring hooks, state transitions and expressions.
            # The flattened common-move view is insufficient for custom resource/conditional specials.
            'source_programs': moveset, 'source_attack_properties': props,
            'same_name_scripts': {}, 'registered_scripts': {'moves': len(moveset)}, 'motions': motions,
            'motion_params': {}, 'own_params': {'base': base, 'jumps': jumps}, 'bones': names,
            'source_tables': tables, 'drawn': drawn}
