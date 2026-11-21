"""A Rivals 2 fighter's moves read into the shape the port driver takes a fighter in (the one
`echo_ultimate.gamedata.moves.load` gives for Ultimate; echo_slapcity's for Slap City), and the clips of its
attacks made to fit them.

Where the game keeps a move: `Attacks/ATT_<short>_<Move>` (a blueprint's class default, RivalsCharacterAttackData).
It is not a script but a list of WINDOWS, each a stretch of frames:
  StringTableKey            its name ('Startup', 'Active 1', 'Recovery', 'Charge' ...)
  WindowLengthFrames        how many game frames it lasts
  AnimationStartFrame, AnimationLengthFrames   which stretch of the clip it plays over those frames (a window may
                            play its stretch faster or slower than one clip frame a game frame, or skip clip frames)
  NextWindowStringTableKey  the window after it ('' : the move ends; itself: it loops until a cancel)
  IasaFrame                 the frame of the window from which other inputs end the move (-1: none)
  WindowCancels             ways to another window: a press (AttackPressed: the next jab), a release (StrongReleased:
                            a smash's charge let go), landing (Grounded), a grab taking hold (OnGrab), the game's
                            own conditions (CharacterSpecific1: Zetterburn's target is burning)
  HitboxWindows             [(hitbox name, StartFrame, LengthInFrames)]: which of the move's hitboxes are out, by name
  HurtboxStateChanges       a hurtbox (by its bone; 'None' every one) made Intangible, Vulnerable, Default ...
  VelocityData, MovementProperties, AdvancedProperties (armour), LedgeProperties
The hitboxes are defined once (`HitboxAttributes`: bone, offset, radius, the name of their numbers) and their numbers
once (`HitboxOnHitProperties`: damage, base knockback, knockback scaling, angle, the special effect: Burn ...).
Sounds (`SFXCreationData`) and effects (`MeshEffectData`, `VFXCreationData`) are made on a window's frame.

How it is read. A move is cut into PARTS, each a Melee action: the windows from the first along `Next` (a smash's
charge window is left out and its frame becomes the charge: Melee holds the clip there), and each window reached only
by a press (the second and third jab) or by the stick (the angled forward tilts) starts a part of its own. Each part's
clip is made here, one clip frame a game frame (the windows' stretches resampled), so a part's frames are the game's
frames and its time keys are plain. The frame rule (READING: no published frame data held against it): a window's
frame 0 is the move's frame (frames before it) + 1, as players count; a hitbox out on window frame s for L frames is
out on move frames start + s to start + s + L - 1, L = 0 meaning to the window's end.

The numbers. Lengths are centimetres times the transcode's unit. Rivals 2's knockback is its own formula, in its
compiled code (not in the files): KNOCKBACK says how it is carried (STAND-IN).
"""
from __future__ import annotations

from .branches import branch_stem

import json
from pathlib import Path

import numpy as np

from .rules import BURN as BURN_RULES, RANNO_DARTS, POISON
from . import actorx
from . import transcode as tc

# The attacks a Melee action is played from: {the game's attack: [(part, the stem it is written under)]}. Parts:
# 'main' is the first window's path; a window name is the part that starts there; 'angle:<suffix>' the main path with
# each window that has a `<window><suffix>` twin replaced by it.
MOVES = {
    'Jab': [('main', 'c00attack11'), ('Startup 2', 'c00attack12'), ('Startup 3', 'c00attack13')],
    'Ftilt': [('main', 'c02attacks3s'), ('angle: Up', 'c02attacks3hi'), ('angle: Down', 'c02attacks3lw')],
    'Utilt': [('main', 'c02attackhi3')], 'Dtilt': [('main', 'c02attacklw3')], 'Dattack': [('main', 'c00attackdash')],
    'Fstrong': [('main', 'c03attacks4s')], 'Ustrong': [('main', 'c04attackhi4')], 'Dstrong': [('main', 'c04attacklw4')],
    'Nair': [('main', 'c05attackairn')], 'Fair': [('main', 'c05attackairf')], 'Bair': [('main', 'c05attackairb')],
    'Uair': [('main', 'c05attackairhi')], 'Dair': [('main', 'c05attackairlw')],
    'Grab': [('main', 'e00catch'), ('Hold', 'e00catchwait'), ('Release', 'e00catchcut')],
    'DashGrab': [('main', 'e00catchdash')], 'PivotGrab': [('main', 'e00catchturn')], 'Pummel': [('main', 'e00catchattack')],
    'Fthrow': [('main', 'e01throwf')], 'Bthrow': [('main', 'e01throwb')], 'Uthrow': [('main', 'e01throwhi')],
    'Dthrow': [('main', 'e01throwlw')],
    'GetupAttack': [('main', 'f03downattacku'), ('main', 'f04downattackd')],
    'LedgeAttack': [('main', 'g02cliffattack')],
    # (the specials' parts that only a button let go or a landing reaches have clips of their own: the fighter's
    # module plays them, SPECIALS.md)
    'Nspecial': [('main', 'd00specialn'), ('Uncharged Active', 'd00specialnuncharged')],
    'NspecialAir': [('main', 'd00specialairn'), ('Uncharged Active', 'd00specialairnuncharged')],
    'Fspecial': [('main', 'd01specials')], 'FspecialAir': [('main', 'd01specialairs')],
    'Uspecial': [('main', 'd02specialhi')], 'UspecialAir': [('main', 'd02specialairhi')], 'Dspecial': [('main', 'd03speciallw'), ('Active', 'd03speciallwslam')],
    'DspecialAir': [('main', 'd03specialairlw'), ('Active Loop', 'd03specialairlwdive')],
    'Taunt1': [('main', 'j01appeallwr')], 'Taunt2': [('main', 'j01appealsr')], 'Intro': [('main', 'j00entryr')],
}
# Same attack data with its declared aerial animation, only when there is no separate air attack.
AIR_CLIP = {'d00specialn': 'd00specialairn', 'd00specialnuncharged': 'd00specialairnuncharged',
            'd01specials': 'd01specialairs', 'd02specialhi': 'd02specialairhi',
            'd03speciallw': 'd03specialairlw', 'd03speciallwslam': 'd03specialairlwslam'}


def aerial_part(att_name, att, which, stem, separate_air=False):
    """Aerial clip identity and declared source animation; never borrow ground data over a real air attack."""
    if separate_air or att_name.endswith('Air') or att_name not in ('Nspecial','Fspecial','Uspecial','Dspecial'):
        return None
    animation = (att.get('AerialAnimation') or {}).get('ObjectPath')
    if not animation:
        return None
    air_stem = AIR_CLIP.get(stem)
    if stem.startswith('d04branch_'):
        air_stem = branch_stem(att_name + 'Air', which)
    return (air_stem, animation.rsplit('.',1)[0]) if air_stem else None

AERIALS = {'Nair': 'landing_lag_n', 'Fair': 'landing_lag_f', 'Bair': 'landing_lag_b', 'Uair': 'landing_lag_hi',
           'Dair': 'landing_lag_lw'}
LANDING = {'Nair': 'nair_landing_lag', 'Fair': 'fair_landing_lag', 'Bair': 'bair_landing_lag',
           'Uair': 'uair_landing_lag', 'Dair': 'dair_landing_lag'}
# STAND-IN. Rivals 2's knockback (BaseKnockback, KnockbackScaling) is worked out in its compiled code; Rivals of
# Aether's published formula is base + scaling x 0.12 x percent (after the hit). Both that and Melee's (for a target
# of weight 100: (18 + 1.4 (p/10 + p d/20)) kbg/100 + bkb) are straight lines in the percent, so one is carried in
# the other exactly once a Rivals knockback unit has a size in Melee's: KB_UNIT, chosen so that a jab (base 4, no
# scaling) is Melee's jab knockback (24) and the forward strong's last hit at 110% (base 8, scaling 0.9: 19.9) is
# a knockback that sends off the side in Melee (about 120). Nothing measures it: no fighter is in both games.
KB_UNIT = 6.0
# The game's angles past 361 (362, 363: its own kinds, in its code) are written as Melee's 361 (STAND-IN)
SPECIAL_ANGLE = 361
FIRE = ('Burn', 'BurnConsume')


def windows(att):
    return {w['StringTableKey']: w for w in att.get('Windows') or []}


# windows that are Melee's own states after a special (its helpless fall and that fall's landing), not the move's
MELEE_STATES = ('Special Fall', 'Special Land')


def path_from(att, first, swap=None, stops=()):
    """[window] from `first` along Next, up to the end, a window that loops (kept once), a window another part
    starts at (`stops`) or one of MELEE_STATES. `swap`: a suffix whose twin windows replace the plain ones."""
    ws = windows(att)
    out, name, seen = [], first, set()
    while name and name in ws and name not in seen:
        if out and (name in stops or name.startswith(MELEE_STATES)):
            break
        seen.add(name)
        w = ws[name]
        if swap and name + swap in ws and out:
            w = ws[name + swap]
        out.append(w)
        name = w['NextWindowStringTableKey']
        if swap and w['StringTableKey'].endswith(swap):
            name = w['NextWindowStringTableKey']
    return out


def parts_with_branches(att_name, att, parts):
    """Keep input-driven and compiled-only branches as separate playable parts.

    Windows already on an exported path need a jump within that path, not a duplicate clip. Loops
    remain one cycle plus explicit path_end metadata; the reader does not invent their exit condition.
    """
    parts = list(parts)
    ws = windows(att)
    first = next(iter(ws), '')
    covered = set()
    for which, _stem in parts:
        start = first if which == 'main' or which.startswith('angle:') else which
        swap = which.split(':', 1)[1] if which.startswith('angle:') else None
        covered.update(w['StringTableKey'] for w in path_from(att, start, swap=swap))
    targets = sorted({c.get('PostCancelWindowStringTableKey') for w in ws.values()
                      for c in w.get('WindowCancels') or [] if c.get('PostCancelWindowStringTableKey') in ws})
    for target in targets:
        if target not in covered and not target.startswith(MELEE_STATES):
            parts.append((target, branch_stem(att_name, target)))
            covered.update(w['StringTableKey'] for w in path_from(att, target))
    # Some mechanics enter windows directly from compiled code: tongue capture,
    # sling, counters, resource hits. No WindowCancel points at those entry nodes.
    # Retain the remaining path components without inventing an input predicate.
    remaining = {name for name,w in ws.items() if name not in covered and
                 not name.startswith(MELEE_STATES) and int(w.get('WindowLengthFrames',0)) > 0}
    while remaining:
        incoming = {ws[name].get('NextWindowStringTableKey') for name in remaining}
        roots = [name for name in ws if name in remaining and name not in incoming]
        target = roots[0] if roots else next(name for name in ws if name in remaining)
        parts.append((target, branch_stem(att_name, target)))
        reachable = {w['StringTableKey'] for w in path_from(att,target)}
        remaining.difference_update(reachable)
    # Capture and release/recovery have separate native responsibilities. Keeping
    # both in one long animation can exceed Melee's fixed 32 KiB action buffer.
    captures = {c.get('PostCancelWindowStringTableKey') for w in ws.values()
                for c in w.get('WindowCancels') or []
                if c.get('WindowCancelType','').split('::')[-1] == 'OnGrab'}
    capture_windows = {w['StringTableKey'] for target in captures for w in path_from(att,target)}
    existing = {which for which, _ in parts}
    for release in (att.get('ThrowData') or {}).get('ThrowReleaseData') or []:
        target = release.get('ReleaseWindowStringTableKey')
        if target in capture_windows and target not in existing:
            parts.append((target, branch_stem(att_name, target)))
            existing.add(target)
    return parts


def window_cancels(part):
    """Source predicates and their frame intervals; preserving a predicate does not implement it."""
    out = []
    for start, window in part.windows:
        last = start + int(window['WindowLengthFrames']) - 1
        for cancel in window.get('WindowCancels') or []:
            first = start + max(0, int(cancel.get('WindowCancelFrame', 0)))
            length = max(0, int(cancel.get('WindowCancelLengthFrames', window['WindowLengthFrames'])))
            out.append(dict(window=window['StringTableKey'], first=first,
                            last=min(max(last, first) if first == last + 1 else last, first + length - 1), condition=dict(cancel)))
    return out


def jab_windows(part):
    """Unconditional attack-press branches to the next ordinary jab; end is exclusive.

    Raw window_cancels retain all predicates, including right-stick and input-consumption policy.
    Resource/held/released/conditional branches remain custom control flow.
    """
    target = {'c00attack11': 'Startup 2', 'c00attack12': 'Startup 3'}.get(part.stem)
    if not target:
        return []
    out = []
    for row in window_cancels(part):
        c = row['condition']
        if (c.get('WindowCancelType', '').split('::')[-1] == 'AttackPressed' and
            c.get('PostCancelWindowStringTableKey') == target and
            c.get('WindowCancelPrerequisite', 'None').split('::')[-1] == 'None' and
            not c.get('NegatePrerequisite') and not c.get('bPreseveWindowTimer') and
            c.get('CancelIntoAttack', 'None').split('::')[-1] == 'None' and row['first'] <= row['last']):
            out.append(dict(start=row['first'],end=row['last']+1,target=target,neutral=False,
                            source_condition=dict(c)))
    return out


def is_charge(w):
    return any(c.get('WindowCancelType', '').endswith('StrongReleased') for c in w.get('WindowCancels') or [])


def melee_kb(bkb, kbs, damage):
    """(bkb, kbg) of Melee's formula standing in for Rivals' (see KB_UNIT): the same slope in the percent, the same
    knockback at 0%."""
    kbg = 100.0 * KB_UNIT * kbs * 0.12 / (1.4 * (0.1 + max(damage, 0.0) / 20.0))
    bkb = KB_UNIT * bkb - 0.18 * kbg
    return round(max(0.0, bkb), 1), round(min(kbg, 511.0), 1)


def angle_of(a):
    a = float(a)
    return float(SPECIAL_ANGLE) if a > 361 else a


class Part:
    """One Melee action made from windows."""

    def __init__(self, att, wins, stem):
        self.att, self.stem = att, stem
        self.windows, self.charge = [], None
        frame = 1
        for w in wins:
            if is_charge(w):
                self.charge = frame
                continue
            self.windows.append((frame, w))
            frame += int(w['WindowLengthFrames'])
        self.total = frame - 1

    def clip_frames(self):
        """The clip frame shown on each move frame 1..total, and one more (the end pose)."""
        out = []
        for start, w in self.windows:
            n, a0, al = int(w['WindowLengthFrames']), float(w['AnimationStartFrame']), float(w['AnimationLengthFrames'])
            for k in range(n):
                out.append(a0 + al * k / max(n, 1))
        if self.windows:
            _s, w = self.windows[-1]
            out.append(float(w['AnimationStartFrame']) + float(w['AnimationLengthFrames']))
        return out


def resample(clip: actorx.Clip, frames):
    """A clip of the given (fractional) frames of another, straight between keys (rotations the short way)."""
    out = actorx.Clip.__new__(actorx.Clip)
    out.bones, out.name, out.rate = clip.bones, clip.name, 60.0
    n = len(frames)
    out.frames = n
    out.t = np.zeros((n,) + clip.t.shape[1:])
    out.q = np.zeros((n,) + clip.q.shape[1:])
    out.scale = None if clip.scale is None else np.zeros((n,) + clip.scale.shape[1:])
    last = clip.frames - 1
    for i, f in enumerate(frames):
        f = min(max(f, 0.0), last)
        a = int(np.floor(f))
        b = min(a + 1, last)
        u = f - a
        out.t[i] = clip.t[a] * (1 - u) + clip.t[b] * u
        qa, qb = clip.q[a], clip.q[b].copy()
        flip = np.einsum('ij,ij->i', qa, qb) < 0
        qb[flip] = -qb[flip]
        q = qa * (1 - u) + qb * u
        out.q[i] = q / np.linalg.norm(q, axis=1, keepdims=True)
        if clip.scale is not None:
            out.scale[i] = clip.scale[a] * (1 - u) + clip.scale[b] * u
    return out


class Reader:
    def __init__(self, sk: tc.Skeleton, unit):
        self.sk, self.unit = sk, unit

    def joint(self, bone):
        if bone in (None, 'None', 'Root', 'Group'):
            return 'top'
        return tc.NAMES.get(bone, bone)

    def pose(self, clip, frame):
        """{joint: 4x4 in the port's space} on a frame of a (made) clip."""
        f = int(min(max(round(frame), 0), clip.frames - 1))
        w = self.sk.worlds(tc.clip_locals(self.sk, clip, f))
        return {j: tc.ported(m, self.unit) for j, m in w.items()}

    def offset(self, h, clip, frame):
        """A hitbox's offset in its joint's space. An offset given in the root's space (`OffsetBoneName` Root) is
        turned into the joint's on the frame the hitbox comes out (READING: the game places it so every frame)."""
        o = h.get('Offset') or {}
        v = tc.point([o.get('X', 0.0), o.get('Y', 0.0), o.get('Z', 0.0)], self.unit)
        j = self.joint(h.get('BoneName'))
        if h.get('OffsetBoneName') == 'Root' and j != 'top' and clip is not None:
            m = self.pose(clip, frame)[j]
            v = m[:3, :3].T @ v
        return j, [float(x) for x in v]


def on_hit(att):
    return {o['Name']: o for o in att.get('HitboxOnHitProperties') or []}


def hitbox_rows(rd, att, part, clip):
    """The part's hitboxes in the driver's rows (one per hitbox a window brings out)."""
    from fighter_port.combat_values import shield_bonus
    attrs = {h['Name']: h for h in att.get('HitboxAttributes') or []}
    props = on_hit(att)
    rows, run, hid = [], 0, {}
    for start, w in part.windows:
        n = int(w['WindowLengthFrames'])
        if w.get('HitboxWindows'):
            run += 1
        for hw in w.get('HitboxWindows') or []:
            h = attrs.get(hw['HitboxName'])
            if h is None:
                continue
            p = props.get(h.get('OnHitPropertiesName')) or {}
            adv = p.get('AdvancedOnHitProperties') or {}
            first = start + int(hw['StartFrame'])
            length = int(hw['LengthInFrames']) or (n - int(hw['StartFrame']))
            last = first + max(length, 1) - 1
            joint, off = rd.offset(h, clip, first)
            dmg = float(p.get('Damage', 0))
            bkb, kbg = melee_kb(float(p.get('BaseKnockback', 0.0)), float(p.get('KnockbackScaling', 0.0)), dmg)
            effect = adv.get('SpecialEffect', '').split('::')[-1]
            ident = hid.setdefault(hw['HitboxName'], len(hid))
            ground = h.get('Groundedness', '').split('::')[-1]
            rows.append({'id': ident, 'bone': joint.lower(), 'damage': dmg,
                         'angle': angle_of(p.get('KnockbackAngle', 361)), 'kbg': kbg, 'bkb': bkb, 'fkb': 0.0,
                         'rehit': int(h.get('CanRehitAfterXFrames') or 0) or None,
                         'game_angle': float(p.get('KnockbackAngle', 361)),
                         'size': float(h.get('Radius', 30.0)) * rd.unit, 'x': off[0], 'y': off[1], 'z': off[2],
                         'first': first, 'last': last, 'run': run,
                         'effect': 'collision_attr_fire' if effect in FIRE or 'Fire' in str(p.get('HitEffectName'))
                         else 'collision_attr_normal',
                         'shield_damage': shield_bonus(dmg, float(adv.get('ShieldDamageMultiplier', 1.0))),
                         'hitlag': float(adv.get('HitpauseMultiplier', 1.0)),
                         'targets': {'GroundOnly': 'ground', 'AirOnly': 'air'}.get(ground), 'flags': 0,
                         'name': hw['HitboxName'], 'props': h.get('OnHitPropertiesName'), 'special_effect': effect,
                         'grab': h.get('HitResponse', '').endswith('Grab'),
                         'rivals_kb': [float(p.get('BaseKnockback', 0.0)), float(p.get('KnockbackScaling', 0.0))]})
    return rows


def sounds(att, part, fighter):
    """{'cmd': 'PLAY_SE', 'real', 'name'} for each sound the move makes on a window this part plays."""
    starts = {w['StringTableKey']: s for s, w in part.windows}
    out = []
    for s in att.get('SFXCreationData') or []:
        at = starts.get(s.get('CreationWindowStringTableKey'))
        if at is None:
            continue
        word = s['SoundName'].lower().replace(' ', '_')
        name = f"{'vc' if s.get('bIsVoiceLine') else 'se'}_{fighter}_{word}"
        out.append({'cmd': 'PLAY_SE', 'real': max(1, at + int(s.get('CreationWindowFrame', 0))), 'name': name,
                    'args': [], 'game_name': s['SoundName']})
    return out


def hurt_states(part):
    """[(move frame, hurtbox, state)] of the part's windows."""
    out = []
    for start, w in part.windows:
        for h in w.get('HurtboxStateChanges') or []:
            out.append((start + int(h['WindowFrame']), h['HurtboxName'], h['HurtboxState'].split('::')[-1],
                        bool(h['HurtboxActive'])))
    return out


def intangible(part):
    """[first, last] move frames on which every hurtbox is Intangible or Invincible ('None' names them all)."""
    on = off = None
    for f, name, state, _active in hurt_states(part):
        if name != 'None':
            continue
        if state in ('Intangible', 'Invincible') and on is None:
            on = f
        elif state not in ('Intangible', 'Invincible') and on is not None and off is None:
            off = f
    if on is None:
        return None
    return [on, (off - 1) if off else part.total]


def made_articles(att, part):
    """[{'id', 'real', 'offset', 'window'}]: the things (`ArticleCreationData`: an article, a blueprint of its own)
    the move makes on a window this part plays, by their names (`ART_<short>_<Name>`, lower case), on the move's frame,
    at an offset from him in Melee's units (ahead, up). An empty creation window is a compiled-code trigger:
    retain the declaration with an unknown frame, never invent a spawn at the start of every branch."""
    starts = {w['StringTableKey']: s for s, w in part.windows}
    out = []
    for a in att.get('ArticleCreationData') or []:
        win = a.get('CreationWindowStringTableKey') or ''
        at = starts.get(win)
        if win and at is None:
            continue
        name = a['ArticleData']['ObjectPath'].rsplit('/', 1)[-1].rsplit('.', 1)[0].split('_', 2)[-1].lower()
        off = a.get('InitialOffsetFromOwner') or {}
        out.append({'id': name, 'real': at + int(a.get('CreationWindowFrame', 0)) if at is not None else None,
                    'trigger': 'window' if win else 'compiled', 'window': win, 'source_creation': dict(a),
                    'offset': [float(off.get('X', 0.0)) * tc.MELEE_PER_CM, float(off.get('Y', 0.0)) * tc.MELEE_PER_CM]})
    return out


def article(pak, pkg, rd):
    """One article's own data (`ART_<short>_<Name>`'s class default: its windows, its one hitbox and that hitbox's
    numbers, what ends it) in Melee's units: a speed a frame, frames, a hitbox row as a move's."""
    a = pak.default(pkg)
    ws = a.get('Windows') or []
    life, speed, hit_frames = 0, [0.0, 0.0], None
    for w in ws:
        if w['StringTableKey'] in ('Destroy', 'Captured'):
            continue
        for v in w.get('VelocityData') or []:
            speed = [float(v['Velocity']['X']) * tc.MELEE_PER_CM, float(v['Velocity']['Y']) * tc.MELEE_PER_CM]
        for hw in w.get('HitboxWindows') or []:
            hit_frames = [life + int(hw['StartFrame']) + 1, life + int(hw['StartFrame']) + int(hw['LengthInFrames'])]
        life += int(w['WindowLengthFrames'])
    # an article's hitbox is a one-row list as an attack's (HitboxAttributes), its numbers the row its
    # OnHitPropertiesName names (none for the flame puddle: its class does what it does)
    h = (a.get('HitboxAttributes') or [{}])[0]
    props = next((p for p in a.get('HitboxOnHitProperties') or [] if p.get('Name') == h.get('OnHitPropertiesName')), {})
    row = None
    if props:
        from fighter_port.combat_values import shield_bonus
        dmg = float(props.get('Damage', 0))
        bkb, kbg = melee_kb(float(props.get('BaseKnockback', 0.0)), float(props.get('KnockbackScaling', 0.0)), dmg)
        effect = ((props.get('AdvancedOnHitProperties') or {}).get('SpecialEffect') or '').split('::')[-1]
        row = {'damage': dmg, 'angle': angle_of(props.get('KnockbackAngle', 361)), 'kbg': kbg, 'bkb': bkb, 'fkb': 0.0,
               'shield_damage': shield_bonus(dmg, float((props.get('AdvancedOnHitProperties') or {}).get('ShieldDamageMultiplier', 1.0))),
               'size': float(h.get('Radius', 30.0)) * rd.unit, 'rehit': int(h.get('CanRehitAfterXFrames') or 0) or None,
               'effect': 'collision_attr_fire' if effect in FIRE else 'collision_attr_normal',
               'special_effect': effect, 'first': hit_frames[0] if hit_frames else 1,
               'last': hit_frames[1] if hit_frames else life}
    ends = {k: str(a.get(k, '')).split('::')[-1] for k in ('GroundCollisionResponse', 'WallCollisionResponse',
                                                            'CeilingCollisionResponse', 'HasHitReaction')}
    from .articles import program

    def hit_values(attribute, values):
        from fighter_port.combat_values import shield_bonus
        damage = float(values.get('Damage', 0))
        base, growth = melee_kb(float(values.get('BaseKnockback', 0)), float(values.get('KnockbackScaling', 0)), damage)
        effect = ((values.get('AdvancedOnHitProperties') or {}).get('SpecialEffect') or '').split('::')[-1]
        offset = attribute.get('Offset') or {}
        return dict(damage=damage, angle=angle_of(values.get('KnockbackAngle', 361)), bkb=base, kbg=growth,
                    shield_damage=shield_bonus(damage, float((values.get('AdvancedOnHitProperties') or {}).get('ShieldDamageMultiplier', 1.0))),
                    fkb=0.0, size=float(attribute.get('Radius', 30))*rd.unit,
                    rehit=int(attribute.get('CanRehitAfterXFrames') or 0), special_effect=effect,
                    effect='collision_attr_fire' if effect in FIRE else 'collision_attr_normal',
                    offset=[float(offset.get(axis, 0))*rd.unit for axis in 'XYZ'])

    return {'life': life, 'speed': speed, 'hit': row, 'hit_size_cm': float(h.get('Radius', 0.0)),
            'harmless_hitbox': props == {} and bool(h), 'class': (a.get('ArticleClass') or {}).get('ObjectName'),
            'ends': ends, 'projectile': bool(a.get('bIsProjectile')),
            'windows': [[w['StringTableKey'], int(w['WindowLengthFrames'])] for w in ws],
            'program': program(a, rd.unit, hit_values), 'source_package': pkg}


def armour_windows(windows):
    """WindowArmor sets a value; -1 leaves the previous value in this path.

    Source attacks start unarmored. Keep positive source values in the reader;
    the native adapter explicitly reports its superarmor approximation.
    """
    active, spans = 0, []
    for first, window in windows:
        value = int((window.get('AdvancedProperties') or {}).get('WindowArmor', 0))
        if value >= 0:
            active = value
        length = int(window['WindowLengthFrames'])
        if active > 0 and length > 0:
            spans.append(dict(first=first, last=first + length - 1, armour=active))
    return spans


def entry_of(rd, att, part, clip, fighter, att_name):
    hits = hitbox_rows(rd, att, part, clip)
    cancel = None
    for start, w in part.windows:
        if int(w['IasaFrame']) >= 0:
            cancel = start + int(w['IasaFrame'])
            break
    flags = []
    if part.charge:
        flags.append({'cmd': 'on_flag', 'real': part.charge, 'which': 'charge'})
    for start, w in part.windows:               # a press that goes on to the next jab
        for c in w.get('WindowCancels') or []:
            if c.get('WindowCancelType', '').endswith('AttackPressed'):
                flags.append({'cmd': 'on_flag', 'real': start + max(0, int(c.get('WindowCancelFrame', 0))),
                              'which': 'combo'})
    armour = armour_windows(part.windows)
    ledge = next((s + int(w['LedgeProperties']['CanGrabLedgeOnFrame']) for s, w in part.windows
                  if int((w.get('LedgeProperties') or {}).get('CanGrabLedgeOnFrame', -1)) >= 0), None)
    momentum = []
    for s, w in part.windows:
        for v in w.get('VelocityData') or []:
            kinds = [v['HorizontalVelocityType'].split('::')[-1], v['VerticalVelocityType'].split('::')[-1]]
            # a speed is in cm a frame (Melee units: x MELEE_PER_CM); a MultiplyVelocity is a factor, kept as it is
            x, y = (float(v['Velocity'][k]) * (1.0 if kind == 'MultiplyVelocity' else tc.MELEE_PER_CM)
                    for k, kind in zip('XY', kinds))
            momentum.append({'real': s + int(v.get('ApplyVelocityOnWindowFrame', 0)), 'window': w['StringTableKey'],
                             'x': x, 'y': y, 'x_kind': kinds[0], 'y_kind': kinds[1],
                             'last': s + min(int(w['WindowLengthFrames']) - 1, int(v.get('ApplyVelocityUntilFrame', 9999))),
                             'modifiers': v.get('VelocityModifiers') or [], 'source_velocity': dict(v)})
    entry = {'hitboxes': [h for h in hits if not h['grab']], 'other': [], 'motion_rates': [], 'flags': flags,
             'turns': [], 'articles': made_articles(att, part), 'article_frames': [], 'cancel_frame_script': cancel,
             'cancel_frame_real': cancel, 'intangible': intangible(part), 'catch_end': None, 'invincible': False,
             'armour': armour, 'momentum': momentum, 'ledge_grab': ledge, 'counter': None, 'effects': [],
             'flashes': [], 'sounds': sounds(att, part, fighter), 'calls': [], 'faces': [],
             # the keys stop on the frame before he may act (3.8), and the driver plays the clip on from there for a
             # move that plays on when nothing is pressed; a special's clip is whole (its module ends it)
             'time_keys': ([[0, 0.0], [cancel - 1, float(cancel - 1)]]
                           if cancel and 1 < cancel <= part.total and not part.stem.startswith('d0')
                           else [[0, 0.0], [max(part.total, 1), float(max(part.total, 1))]]),
             'animation': part.stem + '.nuanmb', 'rivals2_attack': att_name,
             'windows': [[s, w['StringTableKey'], int(w['WindowLengthFrames'])] for s, w in part.windows],
             'window_cancels': window_cancels(part),
             'jab_followup_windows': jab_windows(part) if att_name == 'Jab' else [],
             'path_end': (part.windows[-1][1].get('NextWindowStringTableKey') or '') if part.windows else '',
             'conditional_only': part.stem.startswith('d04branch_'),
             'entry_trigger': ('input_branch' if any(c.get('PostCancelWindowStringTableKey') == part.windows[0][1]['StringTableKey']
                 for w in att.get('Windows') or [] for c in w.get('WindowCancels') or []) else 'compiled')
                 if part.stem.startswith('d04branch_') and part.windows else 'main',
             'end': part.total + 1, 'landing_lag': att.get('LandingLagFrames') if att_name in LANDING else None,
             'hurt_states': hurt_states(part)}
    grabs = [h for h in hits if h['grab']]
    if grabs:
        for h in grabs:
            entry['other'].append({'cmd': 'CATCH', 'real': h['first'],
                                   'args': [h['id'], h['bone'], h['size'], h['x'], h['y'], h['z'],
                                            h['x'], h['y'], h['z'], 0, None]})
        entry['catch_end'] = max(h['last'] for h in grabs) + 1
    grabs_on_top(rd, entry, clip)
    return entry


def throw_hits(rd, att, entry, part):
    """A throw: Melee's throw hit (ATTACK_ABS) and its release (ATK_HIT_ABS). The game's throws either name their
    numbers in ThrowData (released on its window's first frame) or strike the held fighter with a hitbox (its
    numbers, on its frame): the hitbox's are taken where it has one."""
    td = (att.get('ThrowData') or {}).get('ThrowReleaseData') or []
    starts = {w['StringTableKey']: s for s, w in part.windows}
    # A conditional follow-up after the release strikes normally; converting it into a second
    # throw would erase its hitboxes and ask Melee to release a victim that is no longer held.
    releases = [r for r in td if r.get('ReleaseWindowStringTableKey') in starts]
    if td and not releases:
        return
    if not td and part.windows and part.windows[0][1] is not (att.get('Windows') or [None])[0]:
        return
    if entry['hitboxes']:
        h = entry['hitboxes'][0]
        real, dmg, ang, bkb, kbg = h['first'], h['damage'], h['angle'], h['bkb'], h['kbg']
        entry['hitboxes'] = []
    elif releases:
        k = releases[0]['ThrowKnockbackData']
        real = starts[releases[0]['ReleaseWindowStringTableKey']]
        dmg = float(k['Damage'])
        bkb, kbg = melee_kb(float(k['BaseKnockback']), float(k['KnockbackScaling']), dmg)
        ang = angle_of(k['KnockbackAngle'])
    else:
        return
    entry['other'].append({'cmd': 'ATTACK_ABS', 'real': real, 'args': [0, 'top', dmg, ang, kbg, 0.0, bkb]})
    entry['other'].append({'cmd': 'ATK_HIT_ABS', 'real': real, 'args': []})


def grabs_on_top(rd, entry, clip):
    """Ultimate's grab boxes are in the fighter's own space (`top`), the only one the driver reads
    (oneshot.grab_boxes): each is put where its joint is on the frame it comes out."""
    for o in entry['other']:
        if o['cmd'] != 'CATCH' or o['args'][1] == 'top':
            continue
        a = o['args']
        w = rd.pose(clip, o['real'] - 1)
        j = next((k for k in w if k.lower() == a[1]), 'Hip')
        at = w[j] @ np.array([a[3], a[4], a[5], 1.0])
        x, y, z = (float(v) for v in at[:3] - w['Trans'][:3, 3])
        o['from_bone'] = a[1]
        o['args'] = [a[0], 'top', a[2], x, y, z, x, y, z, 0, None]


def attributes(cd, lengths):
    """The fighter's numbers under Melee's names, in Melee's units a frame (Rivals 2's are centimetres a frame:
    x MELEE_PER_CM)."""
    m = tc.MELEE_PER_CM
    out = {'initial_dash_speed': cd['DashSpeed'] * m, 'initial_run_speed': cd['RunSpeedMax'] * m,
           'max_walk_speed': cd['WalkSpeedMax'] * m, 'walk_acceleration': cd['WalkAccelerationMax'] * m,
           'friction': cd['FrictionGround'] * m, 'gravity': cd['Gravity'] * m,
           'terminal_velocity': cd['FallSpeedMax'] * m, 'fast_fall_terminal_velocity': cd['FastFallSpeed'] * m,
           'max_aerial_horizontal_speed': cd['AirSpeedHorizontalMax'] * m, 'aerial_speed': cd['AirAcceleration'] * m,
           'air_friction': cd['FrictionAir'] * m, 'weight': float(cd['Weight']),
           # Rivals 2 steers in the air by one number (AirAcceleration a frame at full stick); Melee by the stick
           # times one and a flat part (oneshot.ATTRIBUTES): all in the first, none flat
           'aerial_friction': 0.0,
           'initial_vertical_jump_velocity': cd['FullHopSpeed'] * m,
           'max_shorthop_vertical_velocity': cd['ShortHopSpeed'] * m,
           'vertical_air_jump_multiplier': cd['DoubleJumpSpeed'] / cd['FullHopSpeed'],
           'max_shorthop_horizontal_velocity': cd['JumpSpeedHorizontalMax'] * m}
    if lengths.get('JumpSquat'):
        out['jump_startup_lag'] = float(lengths['JumpSquat'])        # READING: the clip's frames
    return out


def hurtboxes(hb, rd):
    """The fighter's hurtboxes as own_data takes them: [dict(bone, a, b, radius, height, part)], from the physics
    asset (`HB_<short>`: a capsule a bone, Unreal's Sphyl: centre, a turn, radius, the length between the ends'
    centres along its own Z). Only those the character data makes active at rest are kept (its tail is Intangible
    until a move makes it hittable, and the up special's is made only for that move)."""
    rows, left = [], []
    for o in hb['bodies']:
        bone = o['BoneName']
        if bone in hb['skip']:
            left.append(bone)
            continue
        for s in o['AggGeom'].get('SphylElems') or []:
            c = s['Center']
            r = s['Rotation']
            p, y, ro = (np.radians(float(r.get(k, 0.0))) for k in ('Pitch', 'Yaw', 'Roll'))
            sp, cp, sy, cy, sr, cr = np.sin(p), np.cos(p), np.sin(y), np.cos(y), np.sin(ro), np.cos(ro)
            axis = np.array([-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp])   # FRotationMatrix's Z
            centre = np.array([c['X'], c['Y'], c['Z']], float)
            half = float(s['Length']) / 2.0
            a = tc.point(centre - axis * half, rd.unit)
            b = tc.point(centre + axis * half, rd.unit)
            joint = rd.joint(bone)
            height = ('hit_height_high' if bone in ('Head_M', 'Mouth_M') else
                      'hit_height_low' if any(k in bone for k in ('Hip', 'Knee', 'Ankle')) else 'hit_height_center')
            part = ('collision_part_head' if height == 'hit_height_high' else
                    'collision_part_body_legs' if height == 'hit_height_low' else 'collision_part_body')
            rows.append(dict(bone=joint, a=[float(v) for v in a], b=[float(v) for v in b],
                             radius=float(s['Radius']) * rd.unit, height=height, part=part, source_bone=bone))
    return rows, left


def load(pak, fighter, short, name, root, log=print):
    """-> the driver's `game` for a fighter whose body and clips transcode.write wrote under `root`; the attacks'
    clips are written here (see the head)."""
    import ssbh_data_py as ssbh
    folder = Path(root) / 'gamedata' / 'fighter' / name
    from . import visuals, opacity
    source_visuals = visuals.load(pak, fighter, short)
    summary = json.loads((folder / 'rivals2.json').read_text('utf-8'))
    material_opacity = opacity.prepare(pak, source_visuals, summary, fighter, short)
    unit = summary['unit']
    base = f'Rivals2/Content/Characters/{fighter}'
    exported = Path(root) / 'rivals2-cache' / 'export'
    body = f'{base}/Skins/Default/SK_{short}_Default'
    mesh = actorx.Mesh(next(x for x in pak.export([body], exported)[body] if x.endswith('.psk')))
    sk = tc.Skeleton(mesh, unit)
    sk.height = summary['height_cm']
    sk.rest = sk.worlds(sk.rest_local)
    rd = Reader(sk, unit)
    cd = pak.default(pak.find(f'CD_{fighter}', base + '/'))
    motion = folder / 'motion' / 'body' / 'c00'
    moves, motions, parts_made, source_attacks = {}, {}, {}, {}
    # Discover actual attacks first: an explicit air attack owns its windows, cancels and articles.
    for att_name in MOVES:
        try:
            pkg = pak.find(f'ATT_{short}_{att_name}', base + '/Attacks/')
        except KeyError:
            continue
        source_attacks[att_name] = pak.default(pkg)
    for att_name, att in source_attacks.items():
        parts = parts_with_branches(att_name, att, MOVES[att_name])
        anim = ((att.get('AerialAnimation') or att.get('GroundedAnimation')) if att_name.endswith('Air')
                else (att.get('GroundedAnimation') or att.get('AerialAnimation'))) or {}
        anim = anim.get('ObjectPath')
        if not anim:
            continue
        anim_pkg = anim.rsplit('.', 1)[0]
        files = pak.export([anim_pkg], exported)[anim_pkg]
        psa = next((x for x in files if x.endswith('.psa')), None)
        if psa is None:
            log(f'  {att_name}: its clip {anim_pkg} could not be read (not written)')
            continue
        src = actorx.Clip(psa)
        ws = att.get('Windows') or []
        # a part's first window ends another part's path, unless it is on the move's own path from its first
        # window (the down special's slam is the ground move's own Active, played again after a dive)
        chain = {w['StringTableKey'] for w in path_from(att, ws[0]['StringTableKey'])} if ws else set()
        stops = {w for w, _s in parts if w != 'main' and not w.startswith('angle:') and w not in chain}
        for which, stem in parts:
            if which == 'main':
                wins = path_from(att, ws[0]['StringTableKey'], stops=stops)
            elif which.startswith('angle:'):
                wins = path_from(att, ws[0]['StringTableKey'], swap=which.split(':', 1)[1], stops=stops)
            else:
                wins = path_from(att, which, stops=stops)
            if not wins:
                continue
            part = Part(att, wins, stem)
            made = resample(src, part.clip_frames())
            tc.write_clip(sk, ssbh, made, [motion / f'{stem}.nuanmb'], holding=att_name in (
                'Grab', 'DashGrab', 'Pummel', 'Fthrow', 'Bthrow', 'Uthrow', 'Dthrow'))
            opacity.carry(material_opacity, source_visuals, anim_pkg, stem, part.clip_frames())
            entry = entry_of(rd, att, part, made, name, att_name)
            if att_name.endswith('throw'):
                throw_hits(rd, att, entry, part)
            moves['game_' + stem[3:]] = entry
            parts_made[stem] = dict(attack=att_name, part=which, frames=part.total, charge=part.charge,
                                    windows=[w['StringTableKey'] for _s, w in part.windows])
            if entry['cancel_frame_real'] or entry['intangible']:
                motions[stem] = {'game': 'game_' + stem[3:], 'cancel_frame': entry['cancel_frame_real'],
                                 'intangible': entry['intangible']}
            aerial = aerial_part(att_name, att, which, stem, att_name + 'Air' in source_attacks)
            if aerial:
                air_stem, air_pkg = aerial
                files = pak.export([air_pkg], exported).get(air_pkg, [])
                psa = next((x for x in files if x.endswith('.psa')), None)
                if psa is None:
                    raise ValueError(f'{att_name}: declared aerial animation could not be read: {air_pkg}')
                air_src = actorx.Clip(psa)
                air_part = Part(att, wins, air_stem)
                air_made = resample(air_src, air_part.clip_frames())
                tc.write_clip(sk, ssbh, air_made, [motion / f'{air_stem}.nuanmb'])
                opacity.carry(material_opacity, source_visuals, air_pkg, air_stem, air_part.clip_frames())
                air_entry = entry_of(rd, att, air_part, air_made, name, att_name)
                air_entry['aerial'] = True
                moves['game_' + air_stem[3:]] = air_entry
                parts_made[air_stem] = dict(attack=att_name,part=which,frames=air_part.total,
                    charge=air_part.charge,windows=[w['StringTableKey'] for _s,w in air_part.windows],aerial=True)
                if air_entry['cancel_frame_real'] or air_entry['intangible']:
                    motions[air_stem] = {'game':'game_' + air_stem[3:],
                        'cancel_frame':air_entry['cancel_frame_real'],'intangible':air_entry['intangible']}
    # the burn (`SpecialEffect` Burn sets the target alight, BurnConsume ends a burn for a stronger hit): which of
    # his attacks do which, and the consuming hit's own numbers (on a branch of windows only a burning target opens:
    # the game's CharacterSpecific1 cancel, so no part above plays it). How long a burn lasts and what it costs a
    # frame are compiled behavior (UBurnStatusEffect has no fields); calibrated rules travel separately
    # in status_effect_rules, with their observed build and evidence rather than invented asset provenance.
    burn = {'sets_alight': [], 'consume': {}}
    for att_name in sorted({e['rivals2_attack'] for e in moves.values()} | {'GetupSpecial', 'LedgeSpecial', 'PummelSpecial'}):
        try:
            a = pak.default(pak.find(f'ATT_{short}_{att_name}', base + '/Attacks/'))
        except KeyError:
            continue
        for pr in a.get('HitboxOnHitProperties') or []:
            eff = ((pr.get('AdvancedOnHitProperties') or {}).get('SpecialEffect') or '').split('::')[-1]
            if eff == 'Burn' and att_name not in burn['sets_alight']:
                burn['sets_alight'].append(att_name)
            if eff == 'BurnConsume':
                bkb, kbg = melee_kb(float(pr.get('BaseKnockback', 0.0)), float(pr.get('KnockbackScaling', 0.0)),
                                    float(pr.get('Damage', 0)))
                burn['consume'][att_name] = {'damage': float(pr.get('Damage', 0)), 'angle': angle_of(pr.get('KnockbackAngle', 361)),
                                             'bkb': bkb, 'kbg': kbg, 'name': pr['Name']}
    # the things his moves make (articles: blueprints of their own beside the attacks)
    projectiles = {}
    for f in pak.files():
        if f.startswith(base + '/Attacks/Articles/ART_') and f.endswith('.uasset'):
            pkg = f[:-len('.uasset')]
            projectiles[pkg.rsplit('/', 1)[-1].split('_', 2)[-1].lower()] = article(pak, pkg, rd)
    # numbers
    att = attributes(cd, summary['lengths'])
    for a_name, melee in LANDING.items():
        e = next((e for e in moves.values() if e.get('rivals2_attack') == a_name), None)
        if e and e.get('landing_lag'):
            att[melee] = float(e['landing_lag'])
    melee_attrs = [{'op': 'set_attribute', 'name': k, 'value': float(v)} for k, v in att.items()]
    # hurtboxes: those active at rest and hittable (HurtboxDefinitions)
    hb_pkg = pak.find(f'HB_{short}', base + '/')
    bodies = [o['Properties'] for o in pak.props(hb_pkg) if o.get('Type') == 'SkeletalBodySetup']
    skip = set()
    for d in cd.get('HurtboxDefinitions') or []:
        if not d.get('HurtboxActive', True) or d.get('bIsTemporary') or \
                d.get('HurtboxDefaultState', '').endswith('Intangible'):
            skip.add(d['HurtboxName'])
    hurt, left = hurtboxes(dict(bodies=bodies, skip=skip), rd)
    tables = dict(hurt=hurt,
                  ecb=[dict(bone=j, offset=[0.0, 0.0, 0.0]) for j in ('Hip', 'Head', 'HandL', 'HandR', 'FootL', 'FootR')])
    log(f'  {len(moves)} moves from {len(MOVES)} attacks; {len(hurt)} hurtboxes (left out, not hittable at rest: '
        f'{sorted(left)})')
    return {'fighter': name, 'game': 'rivals2', 'attributes': {}, 'melee_attributes': melee_attrs, 'moves': moves,
            'compiled_rules': {'RannoDarts': dict(RANNO_DARTS)} if name == 'ranno' else {},
            'projectiles': projectiles, 'burn': burn, 'status_effect_rules': {'Burn': dict(BURN_RULES), 'Poison': dict(POISON)}, 'unit': unit, 'kb': {'kb_unit': KB_UNIT},'same_name_scripts': {},
            'registered_scripts': {'moves': len(moves)}, 'motions': motions, 'motion_params': {},
            'own_params': {'character': {k: v for k, v in cd.items() if isinstance(v, (int, float))}},
            'bones': sk.names, 'source_tables': tables, 'drawn': summary['drawn'], 'parts': parts_made,
            'hurtboxes_left_out': sorted(left), 'source_attacks': source_attacks, 'source_visuals': source_visuals,
            'material_opacity': material_opacity,
            # (verify 3.1 then says the donor's dodge frames stay, rather than calling it a fault: checklist 3.10)
            'no_dodge_frames': 'Rivals 2 runs its dodges, rolls, techs and getups as shared engine states: their '
                               'untouchable frames are in no file'}
