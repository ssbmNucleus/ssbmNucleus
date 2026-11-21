"""The driver's second route: the fighter keeps its OWN skeleton.

    python -m fighter_port.oneshot duckhunt --donor Marth --root <dump folder> --donor-zip <Marth.zip> \
        --own <folder with rig/, body/, data/> --work <dir> [--mextk <MexTK folder>]

`fighter_port.oneshot` puts a fighter on a donor's skeleton: every clip is retargeted onto the donor's bones and
every hitbox is carried across by a `Placer` that knows both rigs. A fighter whose body fits no donor (a dog with a
duck on its back) keeps its own skeleton instead (`own_skeleton.prepare` makes the rig, the body and the donor's
fighter data rewritten for the rig). This module runs the driver's stages for such a fighter, with the driver's
own rules wherever they apply:

  spec      the driver's `build_spec`, unchanged: which clip goes on which donor action and how it is timed
  clips     each row becomes a job for `own_bank` (`job_from_row`): the clip is copied onto the fighter's own
            joints on the row's frames. Nothing is retargeted.
  scripts   the driver's `combat_spec`, `dress` and common-action rules, with an `OwnPlacer` in the `Placer`'s
            place: a hitbox on bone B goes on the rig's joint B at the offset the game gives
  values    attributes from the game's table, as the driver sets them
  swing     the rig's swing chains (`own_dynamics.apply`)
  final     <work>/final/{fighter data, animation bank, lookup.json}, <work>/report.json

LENGTHS. A hitbox's offset is read through its joint's matrix (ftcoll.c ftColl_8007AD18 -> lb_8000B1CC), and the
fighter's top joint carries the drawn scale (fighter.c Fighter_UpdateModelScale: the player's size times attributes
+0x8C), so an offset is in the joint's own units: on this rig the source game's, as written. A hitbox's size is not
read through any matrix: ftaction.c ftAction_8007121C stores it as it is, and the collision test multiplies it by
the PLAYER's size only (lbcollision.c lbColl_8000805C: `hit->scale * fp->x34_scale.y`, 1 for a fighter of normal
size), never by the fighter's drawn scale. So a size is in the world's units: the game's size times the drawn scale
(`scale_sizes`). A hurtbox's radius is the other way about (lbColl_80006E58 scales it by its joint's matrix), which
is why `own_data` copies those as they are.

WHAT IS LEFT OUT, each with a line in the log: the donor rig and anything carried to the donor's hand (a weapon,
a held fighter: the fighter's own hold and throw bones are joints of its rig), and the specials: nothing is built
for them (see `quiet_specials`). A face of whole parts shown and hidden by the game's visibility tracks is carried
by `own_faces`.

The sword trail is the game's own (`own_trail`, since 2026-11-13; it was left out until then): on the fighter's
weapon joint whose x axis lies along the blade, in the trail picture's colour, on the frames the game's script turns
it on and off, drawn by the code file's `GetTrailData`. A fighter whose game draws none, or whose rig has no joint
along the blade, has none (said in the log).

The fighter's own particle effects are carried by `OwnEffects`.
"""
from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path

from . import fighters

# Common actions whose clips the source game names another way than Melee does (Melee's own spelling of "forward",
# the game's "sleep" for Melee's "FuraSleep", one walk with a heavy item where Melee has two): clip name -> donor
# action, or several. On the donor's skeleton such an action keeps the donor's clip; here it would hold a pose.
MELEE_NAMES = {'downforwardu': 'DownFowardU', 'downforwardd': 'DownFowardD', 'sleepstart': 'FuraSleepStart',
               'sleeploop': 'FuraSleepLoop', 'sleepend': 'FuraSleepEnd', 'heavywalk': ['HeavyWalk1', 'HeavyWalk2'],
               # The items' own actions. Until 2026-11-13 every own-skeleton port held a standing pose in these: the
               # names differ and only the old Pokemon campaign's table paired them. Melee's jump in the air with the
               # Screw Attack (ItemScrewAir: a spin, then FallAerial) and being struck by one take the game's spin
               # (`itemscrew`, whose own name already fills ItemScrew); the Parasol opening and the float under it
               # take the raise of an assist trophy over the head (`itemassist`, the same 59 frames in every fighter
               # read: 8 to 16 the arm goes up, 16 to 20 it is held) as STAND-INS.
               'itemscrew': ['ItemScrewAir', 'ItemScrewDamage'],
               'itemassist': [('ItemParasolOpen', (8, 16)), ('ItemParasolFall', (16, 20))],
               # Melee plays DownSpotU when the fighter has a clip for it, else DownSpotD (ftCo_DownSpot_Enter), and
               # goes on to the face-up or face-down wait to match. The donor (Marth) has only DownSpotU, so it is
               # always played; a game fighter with only `downspotd` (Shulk, Wolf, Duck Hunt) held a standing pose
               # there and then lay face up. STAND-IN: 30 frames of the face-up lying clip, which is where the
               # engine goes next. A fighter with its own `downspotu` keeps it: rows are taken in the clips' sorted
               # order and `f03downspotu` comes before `f03downwaitu`.
               'downwaitu': [('DownSpotU', (0, 30))]}
# The fighter's own attacks, by the start of an action's name. One whose script, as the game-data reader gives it,
# makes no hitbox (a smash whose shots the game times in code) keeps none of the donor's either: the donor's
# hitboxes are where the donor's sword was. Item swings are not here: their hitboxes are the item's.
OWN_ATTACKS = ('Attack', 'DownAttack', 'CliffAttack')
# Actions that are no attack and no special whose script the port still writes from the game's (its own sounds and
# effects on the clip's own frames, nothing of the donor's): the taunt.
ALSO_DRESSED = ('Appeal',)
END = (0, {}, None)                                     # a script that does nothing


def joint_names(order, folded=None):
    """{a bone as a script names it: its joint} for a frozen rig's own bones: by name in lower case, and by the
    hash the game's files hold a name as when the name is not in the reader's word list ('0x0869e69c8c'). Helper
    joints (`__...`) are no bone of the game's and are left out; the game's `top` is the driver's joint 0.
    `folded` ({bone: the bone it went into}, the rig's provenance for a source over the engine's limit): a folded
    bone answers with the joint it went into (its offset is not turned into that joint's space: a READING, said
    where it is used)."""
    from echo_ultimate.gamedata.prc import hash40
    out = {}
    for i, name in enumerate(order):
        if name.startswith('__'):
            continue
        for key in (name.lower(), f'0x{hash40(name.lower()):010x}'):
            if out.setdefault(key, i) != i:
                raise ValueError(f'two joints answer to {key}: {order[out[key]]} and {name}')
    for name, into in (folded or {}).items():
        if into in order:
            for key in (name.lower(), f'0x{hash40(name.lower()):010x}'):
                out.setdefault(key, order.index(into))
    return out


# ---- the sword trail -------------------------------------------------------------------------------------------------
TRAIL_SLANT = 0.966             # cos 15 degrees: a joint whose x axis is further off the blade than this draws no trail


def skeleton_worlds(root, fighter):
    """The game's own skeleton at rest: ({bone name in lower case: its 4x4 world matrix} (row vectors: the place is
    the last row), {bone: its parent bone})."""
    import numpy as np
    from .oneshot import ssbh
    skel = ssbh(root).skel_data.read_skel(str(Path(root) / 'gamedata' / 'fighter' / fighter / 'model' / 'body' / 'c00'
                                              / 'model.nusktb'))
    names = [b.name.lower() for b in skel.bones]
    return ({b.name.lower(): np.array(skel.calculate_world_transform(b), float) for b in skel.bones},
            {b.name.lower(): names[b.parent_index] for b in skel.bones
             if b.parent_index is not None and 0 <= b.parent_index < len(names)})


def own_trail(game, worlds, parents, joints, base, colour):
    """The fighter's sword trail as the game draws it, on a joint of its own rig. -> (description or None, note)

    Melee draws a trail from a joint's place along that joint's own x axis: ftafterimage.c takes the place with
    lb_8000B1CC and the way from column 0 of the joint's matrix (`var_r29` is 0 for a fighter's own trail), and puts
    the trail from `offset_bottom` to `offset_top` along it. The matrix carries the fighter's drawn scale, so on this
    rig the two offsets are in the game's own units, as its commands write them (like a hitbox's offset, see the
    heading). The game's `AFTER_IMAGE*_ON` commands give the blade's two ends on a bone in THAT bone's axes, and the
    blade need not lie along its x (Shulk's `haver` holds the Monado along y). So the trail goes on the joint of the
    fighter's weapon whose x axis lies along the blade: the commands' bone, or a weapon bone under it
    (`oneshot.WEAPON_BONES`: one the clips carry with the hand; a blade joint the clips open and shut, like the
    Monado's `swordrb1`, is no such joint), the one whose axis passes nearest the blade. The blade's two ends are
    carried into that joint's axes at rest; what lies off its axis cannot be followed and is said in the note.

    `worlds`, `parents`: the game's skeleton (`skeleton_worlds`);
    `joints` the rig's {bone: joint} (`joint_names`); `base` the donor's own description (`code.donor_trail`: the
    fade and the outer colour, which the game's commands do not give); `colour(picture)` -> [r, g, b, a] or None
    (`oneshot.trail_colour`). The description has the donor's fields, the joint, the span, the colour of the
    fighter's ordinary attacks and `others` {script: colour} for the moves the game draws in another picture."""
    from collections import Counter
    import numpy as np
    from .oneshot import WEAPON_BONES, trail_paint
    ons = [e for m in game['moves'].values() for e in (m.get('effects') or [])
           if e['cmd'].startswith('AFTER_IMAGE') and '_ON' in e['cmd'] and len(e.get('args') or []) >= 11]
    ons = [e for e in ons if isinstance(e['args'][3], str) and str(e['args'][3]).lower() == str(e['args'][7]).lower()
           and all(isinstance(e['args'][i], (int, float)) for i in (4, 5, 6, 8, 9, 10))]
    if not ons:
        return None, 'the game draws no sword trail for this fighter'
    if not base:
        return None, "the donor has no trail description to take the fade and the outer colour from"
    bone = Counter(str(e['args'][3]).lower() for e in ons).most_common(1)[0][0]
    ons = [e for e in ons if str(e['args'][3]).lower() == bone]
    if bone not in worlds:
        return None, f'trail bone {bone!r} is not in the skeleton'
    # the blade's two ends, as most of the fighter's trail commands give them, in the world at rest
    pair = Counter(tuple(e['args'][4:7]) + tuple(e['args'][8:11]) for e in ons).most_common(1)[0][0]
    ends = [np.append(np.array(p, float), 1.0) @ worlds[bone] for p in (pair[:3], pair[3:])]

    def under(b):
        """Is `b` the trail bone or below it?"""
        seen = set()
        while b and b not in seen:
            if b == bone:
                return True
            seen.add(b)
            b = parents.get(b)
        return False

    tried = []
    for name in [bone] + [b for b in WEAPON_BONES if b != bone and b in worlds and under(b)]:
        if name not in joints:
            tried.append(f'{name}: not a joint of the rig')
            continue
        # the two ends in the joint's own axes (its rest matrix undone; any scale of the joint's own undone with it)
        inside = [(p @ np.linalg.inv(worlds[name]))[:3] for p in ends]
        span = inside[1] - inside[0]
        length = float(np.linalg.norm(span))
        if length < 1e-6:
            return None, 'the trail commands give one point, not two'
        slant = abs(float(span[0])) / length
        off = max(float(np.linalg.norm(p[1:])) for p in inside) / length
        tried.append(f'{name}: x axis {math.degrees(math.acos(min(1.0, slant))):.0f} degrees off the blade, {off:.0%} of '
                     'its length from it')
        if slant >= TRAIL_SLANT:
            tried[-1] = (off, name, sorted(float(p[0]) for p in inside))
    found = sorted(t for t in tried if isinstance(t, tuple))
    if not found:
        return None, f'no weapon joint of the rig lies along the blade of the trail on {bone} ({"; ".join(tried)})'
    off, name, (bottom, top) = found[0]
    out = dict(base, bone=int(joints[name]), bottom=bottom, top=top)
    note = f"trail along {name} (joint {out['bone']}): {bottom:.2f} to {top:.2f}, from the game's points on {bone}"
    if off > 0.05:
        note += f" (the blade lies {off:.0%} of its length off the joint's axis: drawn on the axis)"
    main, texture, others = trail_paint(game, ons, bone, colour)
    if main:
        out['in_col'] = main
        note += f'; colour {main[:3]} from {texture}'
    out['others'] = {k: c for k, c in others.items() if c != out['in_col']}
    if out['others']:
        note += (f"; {len(out['others'])} moves in other colours "
                 f"({len({tuple(c) for c in out['others'].values()})} colours)")
    return out, note


# ---- clips: a row of the driver's spec as a job for own_bank ---------------------------------------------------------
def row_keys(keys, end, hold_end=False):
    """A clip's time keys as the driver has them ([[clip frame, source frame], ...]; None for the whole clip, frame
    for frame) as `own_bank` takes them, for a source clip whose last frame is `end`. -> keys, or None for the whole.

    `hold_end`: the clip is stored one frame longer than its keys (the engine leaves most actions a frame before
    their clip's count runs out; see the driver's PLAYS_WHOLE): it plays on at the speed it was going. A source
    frame past the clip's end holds its last pose, as the driver's own clips do."""
    end = float(end)
    if keys is None:
        if not hold_end:
            return None
        keys = [[0, 0.0], [int(round(end)), end]] if end >= 1 else [[0, 0.0]]
    keys = [[int(f), float(t)] for f, t in keys]
    if hold_end:
        if len(keys) > 1:
            (f0, t0), (f1, t1) = keys[-2], keys[-1]
            keys.append([f1 + 1, t1 + (t1 - t0) / (f1 - f0)])
        else:
            keys.append([keys[-1][0] + 1, keys[-1][1]])
    if keys[0][0] != 0 or any(b[0] <= a[0] or b[1] < a[1] for a, b in zip(keys, keys[1:])):
        raise ValueError('time keys start at clip frame 0, each frame later than the last, and never run backwards')
    return [[f, min(max(t, 0.0), end)] for f, t in keys]


def joined_parts(parts, length, hold_end=False):
    """The parts of a joined clip (several source clips played one after another) as `own_bank`'s parts.

    The driver's parts hand over on a shared frame: a part with keys up to frame N shows frames 0 to N - 1 and the
    next part starts on frame N (`moveset.join_parts`, `oneshot.part_starts`). `own_bank` gives a part with keys up
    to N all of 0 to N, so every part but the last is cut one frame short here and a script's frames stay where
    the driver counts them. `hold_end` holds the last pose one frame more (a joined clip has no more to play)."""
    from .oneshot import source_time
    out = []
    for i, part in enumerate(parts):
        end = float(length(part['stem']))
        keys = [[int(f), float(t)] for f, t in (part.get('time_keys') or [[0, 0.0], [int(round(end)), end]])]
        if i < len(parts) - 1:
            last = keys[-1][0] - 1
            if last < 0:
                continue                                # a part of no frames
            keys = [k for k in keys if k[0] < last] + [[last, source_time(keys, last)]]
        elif hold_end:
            keys.append([keys[-1][0] + 1, keys[-1][1]])
        out.append({'stem': part['stem'], 'keys': [[f, min(max(t, 0.0), end)] for f, t in keys]})
    return out


def moves_by_clip(row, code=True):
    """Whether the engine is to take this clip's travel off the model and hand it on (the action's flag
    0x80000000): the driver's 'state' and 'code' routes and the table's own engine roots. `code`: the port's code
    file is built; without it a 'code' row has nobody to take its travel."""
    return bool(row.get('engine_root')) and not (row.get('travel') == 'code' and not code)


def travel_of(row, code=True):
    """What becomes of the root's travel in a row's clip, in `own_bank`'s words: the axes kept on the root.
      'XYZ'  the driver gives the travel to the engine (`moves_by_clip`): it stays on the root, and the action's
             flag is set (`engine_flags`) so the engine takes it off the model for the state or the code file
      ''     the driver drops it (walking and running go by the fighter's speeds): it comes off
      None   the driver decides nothing (the travel is part of the pose): `own_bank`'s own rule for the action
    One owner each: the driver's code file moves the fighter only in 'code' rows, and those say 'XYZ' here."""
    if moves_by_clip(row, code):
        return 'XYZ'
    if row.get('travel') == 'code':
        return None
    return '' if row.get('root_motion_joint') else None


def job_from_row(row, length, loop=False, code=True):
    """One row of the driver's spec (a clip on a donor action) as a job for `own_bank.build`.
    `length(stem)`: a source clip's last frame. `loop`: the donor action plays round and round."""
    stem = row['source'].rsplit('/', 1)[1][:-len('.nuanmb')]
    if row.get('parts'):
        parts = joined_parts(row['parts'], length, row.get('hold_end'))
    else:
        keys = row_keys(row.get('time_keys'), length(stem), row.get('hold_end'))
        parts = [{'stem': stem} if keys is None else {'stem': stem, 'keys': keys}]
    job = {'motion': row['target_motion'], 'parts': parts, 'loop': bool(loop)}
    travel = travel_of(row, code)
    if travel is not None:
        job['travel'] = travel
    return job


def jobs_from_spec(clips, length, loops=(), code=True):
    """The spec's clip rows as jobs. -> (jobs, {row id: job}, [(row id, why it has no job)])"""
    jobs, by_id, errors = [], {}, []
    for row in clips:
        if row.get('blocked'):
            errors.append((row['id'], str(row['blocked'])))
            continue
        try:
            job = job_from_row(row, length, row.get('target_motion') in loops, code)
        except (ValueError, OSError, KeyError, ZeroDivisionError) as exc:
            errors.append((row['id'], f'{type(exc).__name__}: {exc}'))
            continue
        jobs.append(job)
        by_id[row['id']] = job
    return jobs, by_id, errors


def named_alike(fighter, actions, prefix, stems, taken):
    """Jobs for the donor's actions the spec has no row for and the fighter has a clip of the same name for
    (`own_bank.default_jobs`): the whole clip, frame for frame. `taken`: the motions that already have a job."""
    from . import own_bank
    own = {}
    for a in actions:
        if a.symbol and a.anim_size and a.symbol.startswith(prefix):
            own.setdefault(a.motion, []).append(a)
    loops = {m: any((x.flags or 0) & own_bank.LOOPS for x in acts) for m, acts in own.items()}
    jobs, _without = own_bank.default_jobs(fighter, {m: acts[0] for m, acts in own.items()}, loops, stems)
    return [j for j in jobs if j['motion'] not in taken]


def engine_flags(pl, clips, installed, code=True):
    """`pl` with the engine's travel flag on every action whose clip gives its travel to the engine
    (`moves_by_clip`), as the driver's install does for the donor route. -> (bytes, [what changed])"""
    from vault.echo.subactions import FighterDat
    from .moveset import enable_engine_root
    wanted = {c['target_motion'] for c in clips if c['target_motion'] in installed and moves_by_clip(c, code)}
    return enable_engine_root(pl, [x.index for x in FighterDat(pl).actions if x.motion in wanted])


# ---- scripts: the game's hitboxes on the fighter's own joints --------------------------------------------------------
class OwnPlacer:
    """What the driver's `Placer` answers, for a fighter on its own skeleton.

    The rig keeps every bone of the game's in its own frame (a helper joint sits above a bone, never in it), so a
    hitbox the game puts on bone B at an offset is on the joint named B at that same offset: no clip is followed,
    nothing drifts. `jobs` ({the spec's clip id: its job}) and `source` (an `own_bank.Source`) are only for
    `heading`."""

    def __init__(self, order, jobs=None, source=None, folded=None):
        self.joints, self.jobs, self.source, self.paths = joint_names(order, folded), jobs or {}, source, {}

    def scale(self, clip_id):
        """Offsets are in the joints' own units, the game's: nothing to multiply by (sizes: `scale_sizes`)."""
        return 1.0

    def place(self, clip_id, bone, offset, frames=None, keys=None):
        """-> (the joint named `bone`, the offset as given, 0.0), or None for a bone the rig does not have."""
        joint = self.joints.get(str(bone).lower())
        return None if joint is None else (joint, [float(v) for v in offset], 0.0)

    def path(self, clip_id):
        """Where the game's clip puts the fighter's root on each frame of the job, or None."""
        if clip_id not in self.paths:
            import numpy as np
            from . import own_bank
            job, way = self.jobs.get(clip_id), None
            sampled = own_bank.job_samples(self.source, job, 1)[0] if job and self.source is not None else None
            if sampled is not None:
                _frames, parts, _end, clips = sampled
                place = np.concatenate([self.source.root_place(raw, at) for raw, at in clips])
                way = own_bank.root_curve(place, parts)
            self.paths[clip_id] = way
        return self.paths[clip_id]

    def heading(self, clip_id, keys, start, end):
        """Which way the fighter itself is going over clip frames start..end, as a launch angle (0 ahead, 90 up),
        or None when its root goes nowhere to speak of: the `Placer`'s rule, on the job's own frames."""
        way = self.path(clip_id)
        if way is None or not len(way):
            return None
        at = lambda f: way[min(max(int(f), 0), len(way) - 1)]
        a, b = at(start - 2), at(end)
        ahead, up = float(b[2] - a[2]), float(b[1] - a[1])
        if math.hypot(ahead, up) < 0.5:
            return None
        return int(round(math.degrees(math.atan2(up, ahead)))) % 360


def rig_stub(frozen):
    """The frozen rig as the dict `combat_spec` opens a rig from. The driver reads a donor rig there for the
    hitboxes no `Placer` places; with an `OwnPlacer` every hitbox is placed, so nothing is read from it."""
    return {'order': frozen['order'], 'parent': frozen['parent'], 'rest': frozen['rest'], 'rename': {},
            'landmarks': {'pelvis': frozen['order'][0]}}


def scale_sizes(spec, drawn):
    """Every hitbox's size in the world's units: the game's size times the fighter's drawn scale (see the
    module's notes). Offsets are not touched. -> how many were sized"""
    count = 0
    for profile in spec['moves']:
        for phase in profile['phases']:
            for hb in phase['hitboxes']:
                hb['radius'] = max(0.1, hb['radius'] * drawn)
                count += 1
    return count


def scale_grab(items, drawn):
    """A grab script from the driver's `regrab` (made with offsets in the joints' units) with its boxes' sizes in
    the world's units."""
    from . import combat
    from .oneshot import GRAB_ELEMENT
    hitbox = combat.command('create_hitbox')[0]
    return [(code, dict(f, size=max(1, int(round(f['size'] * drawn)))), p)
            if code == hitbox and f.get('element') == GRAB_ELEMENT else (code, f, p) for code, f, p in items]


def clip_table(clips):
    """{clip stem: [row]} of the spec's clips, as the driver's script stages read them: the donor action, the
    clip's id and time keys, the stretch of a cut clip, where a joined part starts."""
    from .oneshot import part_starts
    table = {}
    for c in clips:
        if c.get('parts'):
            for q, start in zip(c['parts'], part_starts(c['parts'])):
                table.setdefault(q['stem'], []).append({'target_motion': c['target_motion'], 'id': c['id'],
                                                        'time_keys': None, 'offset': start})
            continue
        stem = c['source'].rsplit('/', 1)[1][:-len('.nuanmb')]
        table.setdefault(stem, []).append({'target_motion': c['target_motion'], 'id': c['id'],
                                           'time_keys': c.get('time_keys'), 'window': c.get('window'),
                                           'offset': c.get('offset') or 0, 'acts': c.get('acts'),
                                           'strike': c.get('strike')})
    return table


def without(table, motions):
    """`table` without the rows on these donor actions."""
    out = {stem: [r for r in rows if r['target_motion'] not in motions] for stem, rows in table.items()}
    return {stem: rows for stem, rows in out.items() if rows}


def silent_attacks(game, table, installed, written):
    """Profiles with no hitboxes for the fighter's own attacks (`OWN_ATTACKS`) that have a clip of the fighter's
    and whose script, as the reader gives it, makes no hitbox: the action gets a script of its own that only says
    when the fighter may act, in place of the donor's hitboxes. `written`: the motions a profile already has.
    -> [profile]"""
    from .oneshot import script_for
    out, seen = [], set(written)
    for stem, rows in sorted(table.items()):
        script = script_for(stem, game['moves'])
        for r in rows:
            motion = r['target_motion']
            if motion in seen or not installed.get(motion) or r.get('window') or r.get('offset') \
                    or not any(motion.startswith(n) for n in OWN_ATTACKS):
                continue
            seen.add(motion)
            total = int(installed[motion])
            if r.get('acts'):
                total = min(total, int(r['acts']))
            if total >= 2:
                out.append({'id': script[5:] if script.startswith('game_') else script, 'motions': [motion],
                            'total': total, 'phases': []})
    return out


# Hits the game's code times, not its script (found on Duck Hunt's smashes: each is three shots of an aiming
# reticle). The script makes each shot's hitbox some frames before the shot and never ends it; the game's code
# turns it on when the shot goes off. Per move: (frames from the hitbox being made to its hit, frames it hits for).
# The numbers are published frame data, written with their source in `fighters.py` (`code_timed_hits`), the one
# place a fighter is written into.
SHOTS = fighters.column('code_timed_hits')
# What a shot is seen by. The game's code draws the fighter's own aiming effect where each shot will land and
# flashes it as the shot goes off; no script names either. (the effect shown while aiming, how many frames one
# showing of it lasts in the effect file, the effect of the shot itself): `code_timed_effects` in `fighters.py`.
SHOT_EFFECTS = fighters.column('code_timed_effects')


def shots(game, fighter):
    """Give the hitboxes of a fighter's code-timed hits (`SHOTS`) the frames they hit on, in the game data as
    read, and add the effects each shot is seen by (`SHOT_EFFECTS`) to the move's effect calls, at the hitbox's own
    place. Only a hitbox its script never ends is touched. -> {move: [(first, last) of each]}"""
    done = {}
    seen = SHOT_EFFECTS.get(fighter)
    for name, (wait, frames) in SHOTS.get(fighter, {}).items():
        move = (game.get('moves') or {}).get(name)
        for h in (move or {}).get('hitboxes') or []:
            if h.get('last') is None:
                made = h['first']
                h['first'] += wait
                h['last'] = h['first'] + frames - 1
                done.setdefault(name, []).append((h['first'], h['last']))
                if seen and str(h.get('bone')) == 'top':
                    aim, lasts, flash = seen
                    place = [h.get('x') or 0.0, h.get('y') or 0.0, h.get('z') or 0.0]
                    calls = [(f, aim) for f in range(made, h['first'], lasts)] + [(h['first'], flash)]
                    move.setdefault('effects', []).extend(
                        {'cmd': 'EFFECT', 'real': f, 'name': effect, 'args': [effect, 'top', *place, 0, 0, 0, 1.0]}
                        for f, effect in calls)
    return done


class OwnEffects:
    """The fighter's OWN particle effects for one run (its effect file, through `own_effects`): the generators its
    scripts need are gathered as the scripts are written, and written out as the fighter's Melee effect file.

    A call in the game's script names an effect, a bone, a place from the bone, a turn and a size. Here it becomes
    one script command for each generator the effect's set converts to (`own_effects.Plan.use`), on the call's
    frame plus the generator's own delay, at the rig joint of that bone.

    What is read from a call and what is not:
      following      a call that makes the effect follow its bone (EFFECT_FOLLOW...) has every generator of its set
                     held by the joint, which carries its particles along (`Plan.use`'s `follow`); one that stops
                     with the move (all but ..._NO_STOP) is removed when the move ends.
      the place      in the game's units, in the fighter's own space (x side, y up, z ahead); written times the
                     drawn scale. A generator held by its joint takes no place from the command: on the base joint
                     or a joint that, at rest, is turned no way from it (`rig`), the place is given to the
                     generator itself; on any other joint it is not carried (noted).
      the turn       turns the way particles fly and lays a streak (a long thin particle) where it points; a
                     Melee particle faces the camera, so its other turns are not carried (noted).
      by code        a call the fighter's own code plays instead (its module's CODE_EFFECTS, `by_code`) is left
                     out of the script.
      a twin         a set for facing left called beside its facing-right twin (`..._l` with `..._r` on the same
                     frame) is left out: the engine turns a burst to the fighter's facing by itself. READING.
      switching off  not carried: a held generator ends with its action."""

    def __init__(self, root, fighter, scale, rig=None):
        from . import own_effects
        self.own_effects = own_effects
        self.fighter, self.scale = fighter, float(scale)
        path = Path(root) / 'gamedata' / 'effect' / 'fighter' / fighter / f'ef_{fighter}.eff'
        self.plan = own_effects.Plan(path, scale) if path.exists() else None
        self.notes, self.written = [], {}
        self.by_code = {}                   # {action: names of the effects the fighter's own code plays in it}
        # the joints whose space is the fighter's own at rest: no turn on them or any joint above them
        self.plain = {0}
        if rig:
            def turned(name):
                return any(abs(float(r)) > 1e-4 for r in ((rig.get('rest') or {}).get(name) or {}).get('r') or ())

            for i, name in enumerate(rig['order']):
                up = name
                while up is not None and not turned(up):
                    up = (rig.get('parent') or {}).get(up)
                if up is None:
                    self.plain.add(i)

    def pictures(self):
        """Read every picture of the fighter's effect file once. -> (how many were read, [(name, format)] of the
        ones in a format the reader does not know), or None for a fighter with no effect file. Seconds: the driver
        asks it before the clip bank, so that a file it cannot open stops the run at once and not minutes in."""
        return self.plan.pictures() if self.plan is not None else None

    @staticmethod
    def read(call, fighter):
        """One call as dict(name, bone, offset, turn, size), or None when it places nothing. In its arguments the
        effect's name comes first (twice in the commands that take one for each facing), then the bone, the place,
        the turn in degrees and the size."""
        args = call.get('args') or []
        at = next((i for i, x in enumerate(args) if isinstance(x, str) and x.startswith(fighter + '_')), None)
        if at is None or 'OFF' in call['cmd']:
            return None
        while at + 1 < len(args) and isinstance(args[at + 1], str) and args[at + 1].startswith(fighter + '_'):
            at += 1
        rest = args[at + 1:at + 9]
        if len(rest) < 8 or not isinstance(rest[0], str):
            return None
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rest[1:]):
            return None
        return dict(name=call['name'], bone=rest[0], offset=[float(v) for v in rest[1:4]],
                    turn=[float(v) for v in rest[4:7]], size=round(float(rest[7]), 4))

    def commands(self, motion, calls, joints, to_frame, total):
        """-> [(clip frame, script command)] for one action; `calls` as the game-data reader gives them ({'cmd',
        'real' (the game's frame), 'name', 'args'}), `joints` {a bone as the script names it: its joint}
        (`joint_names`; the game's `top` is joint 0), `to_frame` the game's frame -> the clip's, `total` the clip's
        frames."""
        if self.plan is None:
            return []
        out, here = [], {(c['name'], c['real']) for c in calls}
        for c in calls:
            got = self.read(c, self.fighter)
            if got is None:
                continue
            name = got['name']
            if name.endswith('_l') and (name[:-2] + '_r', c['real']) in here:
                continue
            if name in self.by_code.get(motion, ()):
                self.notes.append(f'{motion}: {name} is played by the fighter\'s own code')
                continue
            try:
                self.plan.set_name(name)
            except KeyError:
                self.notes.append(f'{motion}: {name} is not in the effect file')
                continue
            bone = str(got['bone']).lower()
            joint = 0 if bone == 'top' else joints.get(bone)
            if joint is None:
                self.notes.append(f'{motion}: {name} on {got["bone"]}, which is no joint of the rig')
                continue
            place = [round(v * self.scale, 3) for v in got['offset']]
            follow = 'FOLLOW' in c['cmd']
            uses = self.plan.use(name, got['size'], place if joint in self.plain else [0.0, 0.0, 0.0], got['turn'],
                                 follow=follow)
            if not uses:
                self.notes.append(f'{motion}: {name} has nothing that is carried (3D shapes)')
                continue
            held = any(u[2] in self.own_effects.ATTACHED for u in uses)
            if any(got['turn']):
                self.notes.append(f'{motion}: {name} turned {got["turn"]}: the way it flies and its streaks are '
                                  'turned, a particle itself is not (it faces the camera)')
            if held and joint not in self.plain and any(got['offset']):
                self.notes.append(f'{motion}: {name} held by {got["bone"]}: its place {got["offset"]} is not carried')
            frame = to_frame(c['real'])
            ends = {u[1] for u in uses if self.plan.ends(u[1])}
            for delay, fields in self.own_effects.script_items(uses, joint, place, destroy=follow and 'NO_STOP' not in c['cmd'],
                                                               ends=ends):
                if frame + delay <= total:
                    out.append((frame + delay, (self.own_effects.EFFECT_COMMAND, fields, None)))
            self.written.setdefault(name, []).append(dict(action=motion, frame=frame, bone=got['bone'], size=got['size'],
                                                          follow=follow, generators=[list(u) for u in uses]))
        return out

    def write(self, final):
        """The fighter's effect file and what tells the packaging stage about it (`effects.json`), into `final`.
        -> the report (None when the fighter has no effect file or no script used it)."""
        if self.plan is None or not self.plan.generators:
            return None
        word = self.fighter.title().replace('_', '')
        file, symbol = f'Ef{word}Data.dat', f'eff{word}DataTable'
        data = self.plan.file(symbol)
        (Path(final) / file).write_bytes(data)
        (Path(final) / 'effects.json').write_text(json.dumps(dict(file=file, symbol=symbol)), 'utf-8')
        report = self.plan.report()
        return dict(file=file, symbol=symbol, bytes=len(data), generators=len(self.plan.generators),
                    sizes=report['bytes'], warnings=report['warnings'], uses=self.written, notes=self.notes,
                    not_carried={name: [dict(emitter=r['emitter'], why=r['not_carried'], **({'stand_in': r['stand_in']}
                                                                                           if r.get('stand_in') else {}))
                                        for r in rows if not r['carried']]
                                 for name, rows in report['sets'].items() if any(not r['carried'] for r in rows)},
                    **effect_counts(report))


def effect_counts(report):
    """What the effect file's receipt says of the emitters made STAND-INS (`own_effects.Plan.report`):
    {'shapes': {'carried', 'refused': how many emitters of the sets the scripts use draw on a 3D shape and are
    flattened, or not carried, and 'why' each refused one is not}, 'pictures': {what each emitter that draws with
    more than one picture, or bends its pictures, got ('combined', 'one drawn', 'stand-in', 'left out'): how many},
    'stand_ins': {set: [{'emitter', 'stand_in', 'why'}] of the carried ones}, 'groups': each texture group's
    picture, format, side (width x height x frames) and bytes, 'fitted': the groups made smaller to fit the bank}."""
    rows = [(name, r) for name, rs in report['sets'].items() for r in rs]
    shaped = [r for _, r in rows if r.get('model') is not None]
    why = {}
    for r in shaped:
        if not r['carried']:
            key = '; '.join(r['not_carried'])
            why[key] = why.get(key, 0) + 1
    pictures = {}
    for _, r in rows:
        if r.get('pictures'):
            got = r['pictures'].get('got', 'first')
            pictures[got] = pictures.get(got, 0) + 1
    stand_ins = {}
    for name, r in rows:
        if r['carried'] and r.get('stand_in'):
            stand_ins.setdefault(name, []).append(dict(emitter=r['emitter'], stand_in=r['stand_in'], why=r['not_carried']))
    return dict(shapes=dict(carried=sum(r['carried'] for r in shaped), refused=sum(not r['carried'] for r in shaped), why=why),
                pictures=pictures, stand_ins=stand_ins,
                groups=[dict(picture=g['picture'], format=g['format'], side=f"{g['width']}x{g['height']}x{g['images']}",
                             bytes=g['bytes']) for g in report.get('groups') or []],
                fitted=list(report.get('fitted') or []))


def armour_spans(played, moves, script_for):
    """Normalize reader armor windows onto every action playing the source move.

    Legacy pairs end exclusively; Rivals dictionaries end inclusively. Rivals
    strength is retained for reporting. Positive Rivals armor currently uses the
    shared native superarmor adaptation, not a numerical knockback conversion.
    """
    by = {}
    for act, stem in played.items():
        if not stem:
            continue
        key = script_for(stem, moves)
        for span in (moves.get(key) or {}).get('armour') or []:
            strength = None
            if isinstance(span, dict):
                first, last = int(span['first']), int(span['last'])
                strength = int(span['armour'])
                if strength <= 0:
                    continue
            else:
                first, end = span
                first, last = int(first), int(end) - 1
            if last < first:
                continue
            group = (str(key), first, last, strength)
            if group not in by:
                by[group] = dict(actions=[], first=first, last=last)
                if strength is not None:
                    by[group].update(source_armour=strength, adaptation='native superarmor')
            by[group]['actions'].append(int(act))
    return [dict(span, actions=sorted(set(span['actions'])))
            for _, span in sorted(by.items(), key=lambda item: item[0][:3])]


def own_calls(move, fighter):
    """A move's effect calls that name an effect of the fighter's own."""
    return [e for e in (move or {}).get('effects') or [] if e.get('real')
            and str(e.get('name') or '').startswith(fighter + '_')]


def quiet_specials(pl, first):
    """The donor's specials for a fighter nothing is built for: every special action's script emptied.

    A port on the donor's skeleton whose specials have no states of their own (no entry in `own.py`) keeps the
    donor's states, and under any clip whose game script has no hitbox it keeps the donor's script: the donor's
    hitboxes, sounds, sword gleams, its chain window and its counter window. Here those would sit on a body they
    were never made for, so nothing of the donor's is left in a special's script. The donor's states still run
    (they are the game's code); with no script flags raised its chain never goes on and its counter never opens.
    `first`: the first special action. -> (bytes, the motions emptied)"""
    from vault.echo.subactions import FighterDat
    fd, done = FighterDat(pl), []
    for index in [x.index for x in fd.actions if x.index >= first and x.script_offset is not None]:
        fd.replace_script(index, [END])
        fd._scripts.clear()
        fd = FighterDat(fd.to_bytes())
        done.append(fd.actions[index].motion)
    return fd.to_bytes(), done


# ---- reading the result back ---------------------------------------------------------------------------------------
def check(pl, aj, base_pl, donor_aj, frozen, lookup, donor='Marth', prefix=None):
    """The written pair, read the way the game will, without running it. -> {'ok', 'problems', the counts}
    `base_pl`, `donor_aj`: the fighter data and bank the clips were made over (the table of the one points into the
    other), which say what each action's clip is called and which clips are another fighter's.
    - the app's reader takes the fighter data and writes every command back as it read it;
    - `own_bank.verify`: every action's clip is cut from the bank where its table says, is one archive of that
      name with the rig's joint count, and none is over the game's limit (the fighter data itself has been written
      on since the bank was made, which that check says once: that line is not a problem here);
    - `own_data.census`: every joint index in every script and table is one of the rig's joints, and every slot a
      script names is one the rig binds."""
    from vault.echo.subactions import FighterDat
    from . import own_bank, own_data
    order = frozen['order']
    fd = FighterDat(pl)
    problems = [f'does not write back as read: {p}' for p in fd.verify_roundtrip()[:5]]
    prefix = prefix or own_bank.donor_prefix(fd.actions)
    engine = [i for i, j in enumerate(order) if j not in own_bank.under(frozen['parent'], own_bank.ROOT)]
    bank = own_bank.verify(pl, aj, base_pl, donor_aj, prefix, len(order), own_bank.CAPACITY, engine)
    problems += [p for p in bank['problems'] if not p.startswith("the fighter data differs from the donor's")]
    D = own_data.DONOR[donor]
    census = own_data.census(pl, D['root'], joints=len(order), attr_joints=D['attr_joints'])
    problems += [f"{c}: a joint past the rig's {len(order)}" for c in census['facts']['out_of_range']]
    forward = lookup['forward']
    for row in census['joints']:
        if row['kind'] == 'SLOT' and not (0 <= row['value'] < len(forward) and forward[row['value']] != own_data.NONE):
            problems.append(f"{row['consumer']}: slot {row['value']}, which the rig leaves empty")
    joints = [r['value'] for r in census['joints'] if r['kind'] == 'JOINT']
    largest = max((x.anim_size or 0, x.motion) for x in fd.actions)
    if largest[0] > own_bank.CAPACITY:
        problems.append(f'{largest[1]}: a clip of {largest[0]} bytes')
    return {'ok': not problems, 'problems': problems, 'actions': len(fd.actions), 'clips': bank['clips'],
            'own_clips': bank['own'], 'joint_indices': len(joints), 'highest_joint': max(joints), 'joints': len(order),
            'slots_named': sum(1 for r in census['joints'] if r['kind'] == 'SLOT'),
            'largest_clip': {'motion': largest[1], 'bytes': largest[0]}, 'capacity': own_bank.CAPACITY,
            'script_blocks': census['facts']['script_blocks'], 'model_scale': census['facts']['model_scale']}


# The ordinary moves, as the driver's table names their donor actions (a name ending in * is every action that
# starts with it: a donor's forward tilt is AttackS3 with something after it).
ORDINARY = (('jab', ('Attack11', 'Attack12', 'Attack13')), ('dash attack', ('AttackDash',)),
            ('tilts', ('AttackS3*', 'AttackHi3', 'AttackLw3')), ('smashes', ('AttackS4', 'AttackHi4', 'AttackLw4')),
            ('aerials', ('AttackAirN', 'AttackAirF', 'AttackAirB', 'AttackAirHi', 'AttackAirLw')),
            ('grab', ('Catch', 'CatchDash')), ('pummel', ('CatchAttack',)),
            ('throws', ('ThrowF', 'ThrowB', 'ThrowHi', 'ThrowLw')), ('getup attacks', ('DownAttackU', 'DownAttackD')),
            ('ledge attack', ('CliffAttackSlow', 'CliffAttackQuick')))


def moves_table(pl, frozen, game, table, rows):
    """The ordinary moves as they were written, beside what the game's own script says: one row an action.
    `table`: `clip_table`; `rows`: the bank report's rows (which clip each action plays).
    -> ([row dict], the same as lines of text)"""
    from vault.echo.subactions import FighterDat
    from . import combat
    from .compat.bone_lookup import SLOTS
    from .oneshot import GRAB_ELEMENT, absolute, script_for
    order, fd, moves = frozen['order'], FighterDat(pl), game['moves']
    hitbox, throw = combat.command('create_hitbox')[0], combat.command('throw')[0]
    interrupt = combat.command('allow_interrupt')[0]
    stem_of = {r['target_motion']: stem for stem, rs in table.items() for r in rs}
    bank = {r['motion']: r for r in rows.values() if r.get('motion')}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    out = []
    for group, names in ORDINARY:
        for name in names:
            acts = [x for x in fd.actions if x.motion and x.anim_size and
                    (x.motion.startswith(name[:-1]) if name.endswith('*') else x.motion == name)]
            if not acts:
                out.append({'move': group, 'action': name, 'clip': None, 'note': 'the donor has no such action'})
                continue
            act = acts[0]
            stem, made = stem_of.get(act.motion), bank.get(act.motion) or {}
            row = {'move': group, 'action': act.motion, 'clip': stem or '(held pose)', 'frames': made.get('frames')}
            read = absolute(fd.script_items(act.index)) if act.script_offset is not None else None
            events = read[0] if read else []
            boxes = [(f, it[1]) for f, it in events if it[0] == hitbox]
            if boxes:
                first = min(f for f, _ in boxes)
                row['first'] = first
                row['boxes'] = [f"{SLOTS[b['bone']] if b.get('use_common_bone_ids') else order[b['bone']]}"
                                f"({'grab' if b.get('element') == GRAB_ELEMENT else b['damage']})"
                                for f, b in boxes if f == first]
                row['damage'] = sorted({b['damage'] for _, b in boxes if b.get('element') != GRAB_ELEMENT})
            row['acts'] = next((f for f, it in events if it[0] == interrupt), None)
            thrown = [it[1] for _, it in events if it[0] == throw and it[1].get('throw_type') == 0]
            if thrown:
                row['throw'] = f"{thrown[0]['damage']}% at {thrown[0]['angle']}"
            m = moves.get(script_for(stem, moves)) if stem else None
            if m:
                hbs = [h for h in m.get('hitboxes') or [] if isinstance(h.get('first'), int) and h.get('damage') != 0
                       and not (isinstance(h.get('last'), int) and h['last'] < h['first'])]
                if hbs:
                    first = min(h['first'] for h in hbs)
                    row['game_first'] = first
                    row['game_boxes'] = [f"{h.get('bone')}({h['damage']:g})" for h in hbs if h['first'] == first]
                    row['game_damage'] = sorted({h['damage'] for h in hbs if num(h.get('damage'))})
                caught = [o for o in m.get('other') or [] if o['cmd'] == 'CATCH']
                if caught:
                    row['game_first'] = min(o['real'] for o in caught)
                    row['game_boxes'] = [f"{o['args'][1]}(grab)" for o in caught if o['real'] == row['game_first']]
                hurl = [o['args'] for o in m.get('other') or [] if o['cmd'] == 'ATTACK_ABS' and len(o['args']) >= 7]
                if hurl and num(hurl[0][2]):
                    row['game_throw'] = f"{hurl[0][2]:g}% at {hurl[0][3]}"
                row['game_acts'] = m.get('cancel_frame_real')
            out.append(row)
    show = lambda v: '-' if v in (None, [], '') else ' '.join(str(x) for x in v) if isinstance(v, list) else str(v)
    head = ('action', 'clip', 'frames', 'acts', 'first', 'hitboxes: joint(damage)', 'throw',
            "game's: first", 'hitboxes', 'throw', 'acts')
    cells = [[r['action'], r.get('clip') or r.get('note'), show(r.get('frames')), show(r.get('acts')),
              show(r.get('first')), show(r.get('boxes')), show(r.get('throw')), show(r.get('game_first')),
              show(r.get('game_boxes')), show(r.get('game_throw')), show(r.get('game_acts'))] for r in out]
    widths = [max(len(str(line[i])) for line in [head] + cells) for i in range(len(head))]
    lines = ['  '.join(str(v).ljust(w) for v, w in zip(line, widths)).rstrip() for line in [head] + cells]
    return out, lines


# ---- the run ---------------------------------------------------------------------------------------------------------
def run(a):
    """The driver's `run` for a fighter on its own skeleton (`a.own`: the folder with rig/, body/, data/)."""
    from . import compat
    compat.install()
    from echo_ultimate.gamedata import arc, moves as gd, swing
    from vault.echo import ops as echo_ops
    from vault.echo.subactions import Dat, FighterDat
    from . import code, oneshot as drv, own_bank, own_dynamics, own_faces
    from . import voice as voice_
    from .moveset import guard_animation_loops
    from .states import FIRST_SPECIAL_ACTION
    log = drv.log

    from . import source_game
    written = source_game.written(getattr(a, 'game', 'ultimate'))
    if getattr(a, 'game', 'ultimate') != 'ultimate' and not written:
        raise SystemExit("--own carries an Ultimate fighter, or one of a game written out in Ultimate's shapes "
                         "(source_game.py): its rig and clips are read from those files")
    own, work = Path(a.own), Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    report = {'fighter': a.fighter, 'donor': a.donor, 'route': 'own skeleton', 'items': 0}
    skipped = report['skipped'] = []

    def skip(what, why):
        skipped.append(f'{what}: {why}')
        log(f'{what}: skipped ({why})')

    # the rig, and the donor's fighter data as `own_data` rewrote it for the rig
    frozen = json.loads((own / 'rig' / f'rig-{a.fighter}.json').read_text('utf-8'))
    lookup = json.loads((own / 'rig' / 'lookup.json').read_text('utf-8'))
    order = frozen['order']
    with zipfile.ZipFile(a.donor_zip) as z:
        fighter_json = json.loads(z.read('fighter.json'))
        pl_name, aj_name = fighter_json['files']['fighterDataPath'], fighter_json['files']['animFile']
        zip_aj = z.read(aj_name)
        zip_pl = z.read(pl_name)
        sound_zip = z.read('sound.zip') if 'sound.zip' in z.namelist() else None
    pl = (own / 'data' / pl_name).read_bytes()
    made_from = json.loads((own / 'data' / 'report.json').read_text('utf-8')).get('inputs', {}).get('donor_file')
    # the bank the rewritten data's action table points into is the one beside the donor file it was made from
    # (a donor file that was given a third jab has a bank one clip longer than the package's)
    beside = Path(made_from) / aj_name if made_from else None
    donor_aj = beside.read_bytes() if beside is not None and beside.is_file() else zip_aj
    ft = FighterDat(pl)
    drawn = ft.dat.f32(ft.dat.ptr(ft.ft_root) + 0x8C)
    report['own'] = {'folder': str(own), 'joints': len(order), 'drawn_scale': drawn,
                     'donor_bank': str(beside) if beside is not None and beside.is_file() else 'the package\'s'}
    log(f"own skeleton: {len(order)} joints, drawn at {drawn:.4f}; the fighter data is {own / 'data' / pl_name}")
    skip('donor rig', "the fighter's joints are its own; no clip is retargeted and no hitbox carried across")

    # the fighter's files and what its scripts say, as the driver reads them
    have, listed = arc.fetch_fighter(a.root, a.fighter)
    log(f'game files: {have} of {listed} for {a.fighter}')
    if not have:
        raise SystemExit(f'the archive lists no files for a fighter named {a.fighter!r}')
    game_path = work / 'game.json'
    # (a game written out in Ultimate's shapes: its reader wrote the moves, source_game.py)
    game_ = source_game.game_data(a.root, a.fighter) if written else gd.load(a.fighter, a.root)
    # a special's voice the game picks from a set (a sequence) is given the first line of that set (voice.name_sequences)
    sequences_ = {} if written else voice_.name_sequences(game_, a.fighter, set(voice_._banks(a.root, a.fighter)['vc']))
    if sequences_:
        report['voice_sequences'] = sequences_
        log('voices played by a sequence: ' + ', '.join(f'{k} -> {v or "NO LINE of that occasion in the bank"}'
                                                         for k, v in sequences_.items()))
    game_path.write_text(json.dumps(game_, indent=1, default=str), 'utf-8')
    game = json.loads(game_path.read_text('utf-8'))
    moves = game['moves']
    timed = shots(game, a.fighter)
    if timed:
        report['code_timed_hits'] = timed
        log(f"hits the game's code times, given their frames from published data: {timed}")

    # ---- what takes seconds and can stop the run is done NOW, before the clip bank (minutes). The fighter's own
    # effect file is opened and every picture in it read: Wolf's first driver died on one picture of 49, in a
    # format the reader did not know, at the first script that used an effect, after the bank had been made. A
    # picture that cannot be read costs what is drawn with it (said here and in the report), not the run.
    effects = OwnEffects(a.root, a.fighter, drawn, frozen)
    read_ = effects.pictures()
    if read_ is None:
        log("own effects: the fighter has no effect file of its own; its scripts' own effects are not drawn")
    else:
        log(f'own effects: {read_[0]} pictures of the effect file read'
            + (f"; {len(read_[1])} in a format the reader does not know, what is drawn with them is NOT carried: "
               + ', '.join(f'{n} ({f:#x})' for n, f in read_[1]) + ' (echo_ultimate/effects.py FORMATS)' if read_[1] else ''))
        report['effect_pictures'] = {'read': read_[0], 'unread': [{'name': n, 'format': hex(f)} for n, f in read_[1]]}

    # an action the donor has no clip for (a third jab): its empty slot gets one, to be filled like the rest
    for clip_name, (follows, name) in drv.EXTRA_ACTION.items():
        if clip_name in drv.clip_names(a.root, a.fighter) and 'game_' + clip_name in moves:
            made = drv.add_action(pl, donor_aj, follows, name)
            if made:
                pl, donor_aj = made
                log(f'actions: the donor has no {name}; its empty action after {follows} now has a clip to fill')
    base = work / 'base'
    base.mkdir(exist_ok=True)
    (base / pl_name).write_bytes(pl)
    skip('weapons', "nothing is carried to the donor's hand: the fighter's own hold bones are joints of its rig")

    # ---- spec: the driver's own, with the rows only an own skeleton needs
    # (and, when the fighter's own specials can be built, the clips of their states on donor actions left free)
    kit = code.toolkit(getattr(a, 'mextk', None))
    dol = special_dol(a, work, own)
    # The shared template carries supported source programs/windows for Slap and Rivals,
    # and clip/hitbox placeholders for other readers. The report keeps mechanic gaps explicit.
    # Its own module, once written (fighter_port/own_<fighter>.py), is used instead.
    table = own_states_table()
    specials_of = a.fighter if a.fighter in table else ('template' if 'template' in table else a.fighter)
    builds = bool(kit and dol and specials_of in table and fighter_json['functions'].get('moveLogicPointer'))
    own_clips = dict(own_special_clips(specials_of)) if builds else {}
    source_plan=None
    adapter=fighters.specials(a.fighter) if builds else None
    if adapter is not None and callable(getattr(adapter,'source_plan',None)):
        source_plan=adapter.source_plan(game,own_clips)
        own_clips.update(source_plan['clips'])
    if builds and specials_of == 'template' and game.get('game') == 'rivals2':
        from .own_rivals_states import plan as rivals_state_plan
        own_clips.update(rivals_state_plan(game, own_clips)['clips'])
    if builds and specials_of == 'template' and game.get('game') == 'slapcity':
        from .own_slap_states import plan as slap_state_plan
        own_clips.update(slap_state_plan(game, own_clips)['clips'])
    # a fighter of forms (fighters.FORMS): the switch's clips go on the switch special's actions and two left free
    from . import forms
    switch_clips = forms.clips(a.fighter, drv.clip_names(a.root, a.fighter)) if builds else {}
    if switch_clips:
        own_clips = {c: m for c, m in own_clips.items() if m not in switch_clips.values()}
        own_clips.update(switch_clips)
        log(f"forms: one of {forms.group_of(a.fighter)[0]}'s forms; the switch's clips: {switch_clips}")
    spec_path, _source = drv.build_spec(a.fighter, a.donor, a.root, base / pl_name, game, work, {}, {}, {}, None, {},
                                        more_rows=dict(MELEE_NAMES, **own_clips),preferred_rows=own_clips)
    clips = json.loads(spec_path.read_text('utf-8'))['clips']

    # ---- sounds. The taunt has no move script (nothing in it hits), so the reader's moves do not hold what it
    # plays: its sounds are read with the articles' and put among the moves, marked as a script the port writes,
    # and the game file is written again so that the sounds stage chooses the same bank.
    from echo_ultimate.gamedata import articles as articles_
    articles = {} if written else articles_.load(a.fighter, a.root)
    unscripted = articles.get('unscripted') or {}
    for c in clips:
        if (c.get('target_motion') in ALSO_DRESSED or c.get('target_motion') in switch_clips.values()) and c.get('source'):
            script = drv.script_for(c['source'].rsplit('/', 1)[1][:-len('.nuanmb')], dict(moves, **unscripted))
            if script in unscripted and script not in moves:
                # (with every field a move script's entry has, empty: nothing in it hits)
                blank = {k: type(v)() for k, v in next(iter(moves.values())).items() if isinstance(v, (list, dict))}
                moves[script] = dict(blank, **unscripted[script], port_plays=True)
                log(f"{c['target_motion']}: plays {script}'s sounds "
                    f"({[e.get('name') for e in unscripted[script].get('sounds') or [] if e.get('name')]})")
    # The sounds the fighter's own code plays (its items, its own states) are in no script either: they go among
    # the moves too, under the bank chooser's own name for them, in the order the fighter's module gives.
    code_sounds = own_code_sounds(specials_of) if builds else []
    if code_sounds:
        blank = {k: type(v)() for k, v in next(iter(moves.values())).items() if isinstance(v, (list, dict))}
        moves[voice_.CODE] = dict(blank, code_plays=True,
                                  sounds=[{'cmd': 'PLAY_SE', 'real': 1, 'name': n, 'args': [n]} for n in code_sounds])
        log(f"its own code plays {len(code_sounds)} sounds: {code_sounds}")
    # (and the effects its own code plays are left out of the scripts)
    if builds:
        from . import own as own_
        effects.by_code = own_.code_effects(specials_of)
        for set_name, emitter_name in own_.hand_stand_ins(specials_of) if effects.plan is not None else ():
            effects.plan.by_hand(set_name, emitter_name)
    game_path.write_text(json.dumps(game, indent=1, default=str), 'utf-8')
    sound_ids = {}
    if sound_zip is not None and fighter_json.get('soundBank') is not None:
        with zipfile.ZipFile(io.BytesIO(sound_zip)) as sz:
            samples = [s['name'] for s in json.loads(sz.read('group.json'))['sounds']]
        # (the game the fighter is from: the sounds stage chooses the same bank from the same banks)
        chosen, _ = voice_.choose(a.donor, a.fighter, a.root, samples, moves, getattr(a, 'game', 'ultimate'), sound_zip,
                                  route=report['route'])
        sound_ids = voice_.calls(sound_zip, fighter_json['soundBank'], chosen,
                                 voice_.aliases(a.root, a.fighter, getattr(a, 'game', 'ultimate')))
    report['own_sounds'] = sorted(sound_ids)
    log(f"sounds: {len(sound_ids)} of the fighter's own will be in its bank")

    for c in clips:
        # a state of the fighter's own is entered with the step (see the driver's PLAYS_WHOLE): its clip is stored
        # a frame longer, so that it lasts as long as the game's
        if own_clips.get(c['source'].rsplit('/', 1)[1][3:-len('.nuanmb')]) == c['target_motion']:
            c['hold_end'] = True
    special_shape = drv.special_rows(a.donor, a.fighter, drv.clip_names(a.root, a.fighter), moves)[1]
    report['specials'] = special_shape

    # ---- clips: each row a job, copied onto the fighter's own joints
    S = drv.ssbh(a.root)
    motion = Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'motion' / 'body' / 'c00'
    lengths = {}

    def length(stem):
        if stem not in lengths:
            lengths[stem] = float(S.anim_data.read_anim(str(motion / f'{stem}.nuanmb')).final_frame_index)
        return lengths[stem]

    actions = FighterDat(pl).actions
    prefix = own_bank.donor_prefix(actions)
    loops = {x.motion for x in actions if x.motion and (x.flags or 0) & own_bank.LOOPS}
    jobs, by_id, errors = jobs_from_spec(clips, length, loops, code=bool(kit))
    stems = sorted(p.stem for p in motion.glob('*.nuanmb'))
    alike = named_alike(a.fighter, actions, prefix, stems, {j['motion'] for j in jobs})
    if alike:
        log(f"clips: {len(alike)} more actions take the fighter's clip of their own name, whole:",
            ', '.join(j['motion'] for j in alike))
    if not kit:
        lost = sorted(c['target_motion'] for c in clips if c.get('travel') == 'code')
        if lost:
            log('travel: no code file can be built (no MexTK), so nobody would take the travel of', ', '.join(lost),
                '; it is left to the bank\'s own rule')
    (work / 'clip-errors.json').write_text(json.dumps(errors, indent=1), 'utf-8')
    bank_dir = work / 'bank'
    bank_dir.mkdir(exist_ok=True)
    (bank_dir / 'jobs.json').write_text(json.dumps(jobs + alike, indent=1), 'utf-8')
    # Every clip made is kept in <work>/bank/cache under the name of what it was made from (the rig, the job, the
    # source files): a run after a failure further on, or after a change to one move, makes only the clips whose
    # job changed (Wolf: the first bank 259 s, the rerun 37 s). Nothing needs clearing by hand.
    cache = own / 'bank' / 'cache'
    kept = len(list(cache.glob('*.dat'))) if cache.is_dir() else 0
    log(f'clips: {len(jobs)} jobs from the spec, {len(alike)} by name, {len(errors)} rows with none; making the bank '
        f'(the cache {cache} holds {kept} clips from earlier runs: only a clip whose job changed is made again'
        + ('' if kept else '; a first bank takes some minutes') + ')')
    base_pl = pl                                        # the fighter data whose table still points into the donor's bank
    # (a form of a fighter of forms: its clip file must fit its share of the clip heap beside the other forms':
    # forms.clip_share; the bank is made at looser tolerances until it does, from the step the last run ended on)
    from . import forms
    share, step_file = forms.clip_share(a.fighter), bank_dir / 'forms-step.json'
    step = json.loads(step_file.read_text('utf-8')).get('step', 0) if share and step_file.exists() else 0
    while True:
        bank_pl, aj, bank = forms.bank(own_bank, step, lambda: own_bank.build(
            base_pl, donor_aj, frozen, a.root, a.fighter, jobs + alike, log=log, cache=cache, prefix=prefix))
        if not share or len(aj) <= share or step >= forms.LOOSEST:
            break
        was, step = step, forms.looser(len(aj), share, step)
        log(f'forms: the clip file is {len(aj):,} bytes, over its share of the clip heap ({share:,}): made again '
            f'{step} steps looser (from {was})')
    if share:
        step_file.write_text(json.dumps({'step': step, 'bytes': len(aj), 'share': share}), 'utf-8')
        bank['forms'] = {'share': share, 'step': step, 'bytes': len(aj), 'fits': len(aj) <= share}
        log(f"forms: the clip file is {len(aj):,} bytes, {'within' if len(aj) <= share else 'STILL OVER'} its share "
            f'of the clip heap ({share:,}), the tolerance {step} steps looser than the first')
    (bank_dir / 'report.json').write_text(json.dumps(bank, indent=1), 'utf-8')
    rows = bank['rows']
    made = {r['motion']: r for r in rows.values() if r.get('kind') == 'SOURCE'}
    installed = {c['target_motion']: int(made[c['target_motion']]['frames']) for c in clips
                 if c['id'] in by_id and c['target_motion'] in made}
    refused = {r['motion']: r.get('why') for r in rows.values() if r.get('motion')}
    errors += [(c['id'], str(refused.get(c['target_motion']))) for c in clips
               if c['id'] in by_id and c['target_motion'] not in made]            # a clip the reader would not take
    (work / 'clip-errors.json').write_text(json.dumps(errors, indent=1), 'utf-8')
    t = bank['totals']
    report['clips'] = {'compiled': len(installed), 'by_name': len(alike), 'error': len(errors), 'held': t['held'],
                       'loosened': t['loosened'], 'bank_bytes': t['bank_bytes'], 'largest': t['largest']}
    report['held'] = bank['held']
    log(f"clips: {t['with_source']} of {t['own_clips']} actions' clips are the fighter's own, {t['held']} hold a pose; "
        f"bank {t['bank_bytes']:,} bytes, largest {t['largest']['bytes']:,} (a clip may be {own_bank.CAPACITY:,}); "
        f"{t['loosened']} thinned to fit; {t['cached']} from the cache, {t['own_clips'] - t['cached']} made now "
        f"({cache})")
    pl, flagged = engine_flags(bank_pl, clips, installed, code=bool(kit))
    report['travel'] = {'spec': json.loads((work / 'spec' / 'travel.json').read_text('utf-8')),
                        'flag_set_on_actions': [c['action'] for c in flagged],
                        'kept': {m: v['axes'] for m, v in bank['travel']['kept'].items()},
                        'taken_off': {m: v['axes'] for m, v in bank['travel']['cancelled'].items()}}
    log(f"travel: the engine's flag set on {len(flagged)} more actions whose clip moves the fighter; kept on the root in "
        f"{len(bank['travel']['kept'])} clips, taken off in {len(bank['travel']['cancelled'])}")
    # a donor script that jumps back to its own start waits for the clip to come round first, as the driver's
    # install makes it: under a clip longer than the donor's it would otherwise spin within one frame
    pl, guards = guard_animation_loops(pl, [x.index for x in FighterDat(pl).actions
                                            if x.symbol and x.symbol.startswith(prefix)])
    report['loop_guards'] = [g['action'] for g in guards]
    log(f'scripts that loop: {len(guards)} of the donor\'s wait for their clip to come round')

    # ---- scripts: hitboxes and throws from the game's scripts, on the fighter's own joints
    full_table = clip_table(clips)
    specials = {x.motion for x in FighterDat(pl).actions if x.motion and x.index >= FIRST_SPECIAL_ACTION}
    table = without(full_table, specials)
    folded = frozen.get('provenance', {}).get('folded') or {}
    placer = OwnPlacer(order, by_id, own_bank.Source(a.root, a.fighter, frozen), folded)
    spec, notes = drv.combat_spec(game, table, a.donor, rig_stub(frozen), 1.0, installed, placer, {})
    sized = scale_sizes(spec, drawn)
    silent = silent_attacks(game, table, installed, {m for p in spec['moves'] for m in p['motions']})
    spec['moves'] += silent
    for p in silent:
        # (a weapon of the fighter's can register a script under a move's own name; the reader keeps one a name)
        twins = (game.get('same_name_scripts') or {}).get('game_' + p['id']) or []
        more = sum(len(t.get('hitboxes') or []) for t in twins)
        notes.append(f"{p['id']}: the script the reader keeps under this name makes no hitbox; {p['motions'][0]} is "
                     "written with none (and none of the donor's)"
                     + (f"; another script of the same name makes {more} (same_name_scripts in game.json)" if more else ''))
    (work / 'combat.json').write_text(json.dumps(spec, indent=1), 'utf-8')
    pl, done, failed = drv.install_scripts(pl, spec)
    notes += [f'{name}: {why}' for name, why in failed if 'no action number' in why]
    failed = [f for f in failed if 'no action number' not in f[1]]
    report['scripts'] = {'written': len(done), 'failed': failed, 'notes': notes, 'sized': sized,
                         'no_hitboxes': [p['motions'][0] for p in silent]}
    log(f'scripts: {len(done)} moves written ({len(silent)} with no hitbox of their own), {len(failed)} failed, '
        f'{len(notes)} notes; {sized} hitbox sizes in world units (x {drawn:.4f})')

    # what the hitbox writer leaves out: sounds, voice and the shared effects, on the game's own frames
    cues = drv.donor_cues(FighterDat(base.joinpath(pl_name).read_bytes()))
    # the sword trail where the game draws one, on the fighter's own weapon joint (`own_trail`); the donor's own
    # trail commands were turned off in the fighter data (`own_data.trail_target`), so the commands that turn the
    # trail on and off are read from the donor's file as it came
    worlds, skeleton = skeleton_worlds(a.root, a.fighter)
    base_trail = code.donor_trail(zip_pl, a.donor, Dat)
    trail, trail_note = own_trail(game, worlds, skeleton, joint_names(order, folded), base_trail,
                                  lambda t: drv.trail_colour(a.root, a.fighter, t, base_trail['in_col'][3]))
    if trail and not kit:
        trail, trail_note = None, 'the code file draws it, and none can be built (no MexTK)'
    donor_trail_cues = drv.donor_cues(FighterDat(zip_pl))
    for k in ('trail_on', 'trail_off'):
        cues.pop(k, None)
        if trail and k in donor_trail_cues:
            cues[k] = donor_trail_cues[k]
    if trail and not ('trail_on' in cues and 'trail_off' in cues):
        trail, trail_note = None, "the donor's scripts have no command that turns a trail on and off to copy"
    if trail:
        # the trail only where the game's script draws one: the donor route also draws it under a move's
        # sword hitboxes when the game swings with an effect of its own instead, which this route carries
        cues['trail_drawn_only'] = True
        report['trail'] = {k: v for k, v in trail.items() if k != 'others'}
        report['trail']['note'] = trail_note
        log(f'sword trail: {trail_note}')
    else:
        skip('sword trail', trail_note)
    # the donor's own swing stands in for nothing: where the bank lacks one of the fighter's sounds the move is
    # quiet there (a sword's swing under a peck or a gunshot is the donor's sound left behind)
    cues['swings'] = {}
    cues.pop('swing', None)
    skip('donor swing sounds', "a sound of the fighter's that the bank has no room for is not replaced by the donor's swing")
    joints = joint_names(order, folded)
    cues['place'] = {'bone': None, 'weapon': {}, 'scale': 1.0, 'joints': joints}
    fd, dressed, seam = FighterDat(pl), {}, {'moves': 0, 'calls': 0, 'commands': 0}
    # (`effects`, the fighter's own effect file, was opened before the clip bank)

    def dressed_script(items, move, total, motion_, shift, own_only=False):
        """A script with what the game's script for its clip has on its own frames: the sounds and shared effects
        the driver's `dress` writes, and what the seam gives for the fighter's own effects. -> (items, added)"""
        first = drv.STARTS_ON.get(a.donor, {}).get(motion_, 0) + 1
        items, added = drv.dress(items, move, total, cues, motion_, a.fighter, shift, sound_ids=sound_ids, first=first,
                                 own_only=own_only)
        calls = own_calls(move, a.fighter)
        if calls:
            more = effects.commands(motion_, calls, joints, lambda f: f + shift, total)
            for frame, command in more:
                items = drv.at_frame(items, max(first, int(frame)), command)
            seam['moves'] += 1
            seam['calls'] += len(calls)
            seam['commands'] += len(more)
            added = added + [f'own effect {int(f)}' for f, _ in more]
        return items, added

    for profile in spec['moves']:
        move = moves.get('game_' + profile['id']) or moves.get(profile['id'])
        if profile['id'] not in done or not move:
            continue
        base_id = profile['id'][:-len(drv.SECOND)] if profile['id'].endswith(drv.SECOND) else profile['id']
        for motion_ in profile['motions']:
            acts = [x for x in fd.actions if x.motion == motion_]
            if profile.get('occurrence') is not None:
                acts = drv.combat_nth(acts, profile['occurrence'])
            for act in [x for x in acts if x.script_offset is not None]:
                shift = next((r.get('offset') or 0 for rows_ in table.values() for r in rows_
                              if r['target_motion'] == motion_
                              and drv.script_for_row(rows_, table, game) in ('game_' + base_id, base_id)), 0)
                items, added = dressed_script(fd.script_items(act.index), move, profile['total'], motion_, shift)
                if added:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    dressed[motion_] = added

    # actions that keep the donor's script: untouchable on the game's frames, and a grab where and when the game's is
    written = {m for p in spec['moves'] if p['id'] in done for m in p['motions']}
    shared = {'untouchable': {}, 'grabs': {}, 'unread': []}
    for stem, rows_ in table.items():
        for r in rows_:
            motion_, total = r['target_motion'], installed.get(r['target_motion'])
            if motion_ in written or not total or r.get('offset') or r.get('window'):
                continue
            span = drv.shared_untouchable(game, stem, motion_)
            to_frame = lambda v, keys=r.get('time_keys'): drv.frame_at(keys, float(v) - 1.0) + 1
            for act in [x for x in fd.actions if x.motion == motion_ and x.script_offset is not None]:
                items, changed = fd.script_items(act.index), False
                if span:
                    first_, end_ = max(1, to_frame(span[0])), min(to_frame(span[1]), int(total))
                    new = drv.untouchable(items, first_, end_) if first_ < end_ else None
                    if new:
                        items, changed = new, True
                        shared['untouchable'][motion_] = [first_, end_ - 1]
                    else:
                        shared['unread'].append(motion_)
                if motion_ in drv.GRABS:
                    new = drv.regrab(items, moves.get(drv.GRABS[motion_]), 1.0)
                    if new:
                        items, changed = scale_grab(new[0], drawn), True
                        shared['grabs'][motion_] = new[1]
                        heard = [e for e in (moves.get(drv.GRABS[motion_]) or {}).get('sounds') or []
                                 if e.get('real') and sound_ids.get(str(e.get('name') or '').lower()) is not None]
                        if heard and 'own_sound' in cues:
                            items = [i for i in items if i[0] != 17]
                            for e in heard:
                                items = drv.at_frame(items, max(1, int(to_frame(e['real']))),
                                                     (17, dict(cues['own_sound'][1], sfx_id=sound_ids[e['name'].lower()]), None))
                            shared.setdefault('grab_sounds', {})[motion_] = [e['name'] for e in heard]
                    else:
                        shared['unread'].append(motion_)
                if changed:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
    report['shared'] = shared
    log(f"common actions: untouchable on the game's frames in {len(shared['untouchable'])}; grabs {shared['grabs']}; "
        f"not read {sorted(set(shared['unread']))}")

    # the colour a move lays over the body, on the game's own frames: played by the port's code
    flash = []
    for stem, rows_ in table.items():
        lit = (moves.get(drv.script_for(stem, moves)) or {}).get('flashes') or []
        for r in rows_ if lit else []:
            if r.get('window') or not installed.get(r['target_motion']):
                continue
            for act in [x for x in fd.actions if x.motion == r['target_motion']]:
                if not any(k[0] == act.index for k in flash):
                    flash += [(act.index, *k) for k in drv.flash_keys(lit, r.get('offset') or 0)]
                    if act.script_offset is not None and any(i[0] == drv.COLANIM for i in fd.script_items(act.index)):
                        fd.replace_script(act.index, [i for i in fd.script_items(act.index) if i[0] != drv.COLANIM])
                        fd._scripts.clear()
                        fd = FighterDat(fd.to_bytes())
    if flash:
        report['flashes'] = sorted({k[0] for k in flash})
        log(f"flashes: the body's colour on the game's own frames in {len(report['flashes'])} actions ({len(flash)} keys)")
    pl = fd.to_bytes()

    # ---- specials: nothing of the donor's is left in their scripts. A fighter with an entry in `own.py` gets
    # states of its own for them (after the donor's in its state table) when the code file can be built.
    pl, emptied = quiet_specials(pl, FIRST_SPECIAL_ACTION)
    if not builds:
        articles = None                                 # (read above for the sounds; the specials are not built)
    # A fighter whose own states strike with the fighter itself (a blade on the gun in his hand, a kick as a flight
    # ends) names the actions of those states (`own.SPECIAL_HITS`): their hitboxes are written from the game's
    # scripts for their clips, the way an attack's are. (Duck Hunt's specials strike only with the items they make,
    # so the route wrote none; Wolf was the first to need this.)
    hit_scripts = set()
    hit_motions = set(own_special_hits(specials_of)) if builds else set()
    if builds and (source_plan is not None or specials_of == 'template' and game.get('game') in ('rivals2', 'slapcity')):
        hit_motions.update(own_clips.values())
    if hit_motions:
        special_table = {stem: [r for r in rows_ if r['target_motion'] in hit_motions] for stem, rows_ in full_table.items()}
        special_table = {stem: rows_ for stem, rows_ in special_table.items() if rows_}
        sspec, snotes = drv.combat_spec(game, special_table, a.donor, rig_stub(frozen), 1.0, installed, placer, {})
        ssized = scale_sizes(sspec, drawn)
        pl, sdone, sfailed = drv.install_scripts(pl, sspec)
        hit_scripts = {m for p in sspec['moves'] if p['id'] in sdone for m in p['motions']}
        spec['moves'] += sspec['moves']
        (work / 'combat.json').write_text(json.dumps(spec, indent=1), 'utf-8')
        report['special_hits'] = {'written': sorted(hit_scripts), 'failed': sfailed, 'notes': snotes, 'sized': ssized}
        log(f"specials: the hitboxes of {len(sdone)} scripts written on {len(hit_scripts)} actions of the fighter's own "
            f"states ({sorted(hit_scripts)}); {len(sfailed)} failed {sfailed or ''}; {len(snotes)} notes {snotes or ''}")
    fd = FighterDat(pl)
    for stem, rows_ in full_table.items():
        # (a clip with no move script of its own can still have sounds and effects: the start of an up special)
        move = moves.get(drv.script_for(stem, moves)) or unscripted.get(drv.script_for(stem, moves))
        for r in rows_ if move else []:
            motion_, total = r['target_motion'], installed.get(r['target_motion'])
            if (motion_ not in specials and motion_ not in ALSO_DRESSED) or not total:
                continue
            for act in [x for x in fd.actions if x.motion == motion_ and x.script_offset is not None]:
                # what the game's script has on this stretch of the clip, and nothing of the donor's in its place
                begun = fd.script_items(act.index) if motion_ in hit_scripts else [END]
                items, added = dressed_script(begun, move, int(total), motion_, r.get('offset') or 0, own_only=True)
                if added:
                    fd.replace_script(act.index, items)
                    fd._scripts.clear()
                    fd = FighterDat(fd.to_bytes())
                    dressed[motion_] = added
    pl = fd.to_bytes()
    if any(special_shape.get(k) == 'through' for k in ('neutral', 'airneutral')) and 'loops' in drv.SHOT_DONOR.get(a.donor, {}):
        # a neutral special that is one clip passed through the donor's start, charge and release: with no charge
        # loops the donor goes straight on to its release, held or not (the driver's own rule)
        d = Dat(pl)
        d.set_u32(d.ptr(next(off for name, off in d.roots if name.startswith('ftData')) + 4)
                  + drv.SHOT_DONOR[a.donor]['loops'], 0)
        pl = d.to_bytes()
    filled = sorted(m for m in specials if m in installed)
    for stem, rows_ in sorted(full_table.items()):
        kept = [h for h in (moves.get(drv.script_for(stem, moves)) or {}).get('hitboxes') or [] if h.get('damage')]
        if kept and any(r['target_motion'] in specials for r in rows_) and not any(r['target_motion'] in hit_scripts for r in rows_):
            notes.append(f"{drv.script_for(stem, moves)}: {len(kept)} hitboxes in the script the reader keeps for {stem}; "
                         "not written (nothing is built for a special)")
    report['special_actions'] = {'emptied': len(emptied), 'own_clip': filled,
                                 'held_pose': sorted(m for m in specials if m not in installed and m in bank['held'])}
    mine, report['own_states'] = None, []
    if builds:
        from . import own as own_states, own_items, states
        from echo_ultimate.gamedata.prc import Prc
        donor_rows = states.donor_states(dol.read_bytes(), int(fighter_json['functions']['moveLogicPointer']),
                                         len(FighterDat(zip_pl).actions) - FIRST_SPECIAL_ACTION)
        index = {}
        for act in FighterDat(pl).actions:
            if act.motion:
                index.setdefault(act.motion, act.index)
        state_of = {m: states.FIRST_SPECIAL_STATE + next(i for i, r in enumerate(donor_rows) if r['action'] == n)
                    for m, n in index.items() if any(r['action'] == n for r in donor_rows)}
        vl = Path(a.root) / 'gamedata' / 'fighter' / a.fighter / 'param' / 'vl.prc'
        ctx = {'first': states.FIRST_SPECIAL_STATE + len(donor_rows), 'action': index, 'total': installed,
               'state': state_of, 'functions': fighter_json['functions'], 'moves': moves, 'world': drawn, 'drawn': drawn,
               # the donor's own row for each of its special actions: a state of the fighter's own for the same
               # input keeps that row's flags and the number the engine knows the move by
               'row': {m: donor_rows[state_of[m] - states.FIRST_SPECIAL_STATE] for m in state_of},
               'common_rows': states.common_by_motion(dol.read_bytes(), index),
               'flags': {'ground': donor_rows[state_of['SpecialHi'] - states.FIRST_SPECIAL_STATE]['flags'],
                         'air': donor_rows[state_of['SpecialAirHi'] - states.FIRST_SPECIAL_STATE]['flags']},
               'move': {'up': donor_rows[state_of['SpecialHi'] - states.FIRST_SPECIAL_STATE]['move'],
                        'down': donor_rows[state_of['SpecialLw'] - states.FIRST_SPECIAL_STATE]['move']},
               'vl': Prc(vl.read_bytes(), own_states.names(specials_of)).root if vl.exists() else {},
               'gravity': (game.get('attributes') or {}).get('air_accel_y'), 'articles': articles,
               'effects': effects, 'sound_ids': sound_ids, 'joints': joints, 'root': a.root, 'work': work,
               'source_game': game, 'generic_specials': specials_of != a.fighter}
        if source_plan is not None:ctx['rivals_plan']=source_plan
        # (a form: the switch's states first, then its specials, the switch left out of them: forms.build)
        mine, why = forms.build(a.fighter, specials_of, ctx, own_states.build)
        if mine and specials_of != a.fighter:
            common = bool((mine.get('numbers') or {}).get('movement'))
            description = ('shared source movement, supported branches and article adapters'
                           if common else 'animation and hitbox placeholders')
            log(f"own states: shared template builds {description}; unsupported source behavior is listed in the report")
            report['specials_not_written'] = ('shared source execution: source callbacks, transitions and article classes '
                'outside the supported set still need adapters' if common else
                f'no fighter_port/{fighters.specials_name(a.fighter)}.py: the plain specials of own_template.py are built')
            report['specials_from'] = 'own_template.py'
        if mine:
            states.apply_iasa(donor_rows, state_of, mine.get('donor_iasa') or {})
            mine['table'] = states.table_text(donor_rows, mine['rows'])
            if mine.get('items'):
                # the items its specials make: each one's data in the fighter's own file, its code in the code file
                pl, made_items = own_items.install(pl, mine['items'], a.root, a.fighter, drawn, work / 'items', log)
                report['items'], report['own_items'] = len(mine['items']), made_items
            report['own_states'] = [r['name'] for r in mine['rows']]
            report['special_numbers'] = mine.get('numbers') or {}
            from .port_mechanics import assess
            report['mechanic_coverage'] = assess(game,mine)
            if mine.get('forms'):
                report['forms'] = mine['forms']
            log(f"own states: {report['own_states']} as states {ctx['first']} to {ctx['first'] + len(mine['rows']) - 1}"
                + (f"; {report['items']} items" if report['items'] else ''))
        else:
            raise ValueError(f'{specials_of}: own states could not be built: {why}')
    elif specials_of in table:
        log('own states: not built (they need MexTK (--mextk), the game executable (--dol, or a project beside the '
            "work folder) and the donor's state table): the specials do nothing")
    else:
        # (said aloud: Wolf's first disc had four specials that did nothing, and nothing had said they would)
        log(f"own states: THE FOUR SPECIALS DO NOTHING on this build: the fighter has no module of its own states. To "
            f'give it specials, {fighters.specials_start(a.fighter)}')
        report['specials_not_written'] = f'no fighter_port/{fighters.specials_name(a.fighter)}.py'
    if mine:
        skip("the donor's specials", f"the fighter's own are built: {len(emptied)} special actions' scripts emptied of the "
                                     f"donor's hitboxes, sounds and flags; {len(filled)} play the fighter's own clip")
    else:
        skip('specials', f"nothing is built for them: {len(emptied)} special actions' scripts emptied of the donor's "
                         f"hitboxes, sounds and flags; {len(filled)} play the fighter's own clip")
    report['dressed'] = dressed
    report['own_effects'] = seam
    log(f"own effects: {seam['calls']} calls in {seam['moves']} scripts; {seam['commands']} commands written")
    log(f'sounds, voice, effects: {len(dressed)} actions;',
        {k: sum(1 for v in dressed.values() for x in v if x.startswith(k)) for k in ('swing', 'voice', 'effect')})

    # ---- values
    # (the fighter data's model scale IS the drawn scale on this route, so the shield is the game's own radius)
    ops, anotes = (game['melee_attributes'], []) if game.get('melee_attributes') else drv.attribute_ops(game, drawn, drawn)
    pl = echo_ops.apply(pl, ops).data
    report['attributes'] = {'set': len(ops), 'notes': anotes}
    log(f'attributes: {len(ops)} set')

    # ---- swing chains: which of them each action leaves to physics, by the game's own word for the action's clip
    bones = [b.name for b in S.skel_data.read_skel(str(motion.parents[2] / 'model' / 'body' / 'c00' / 'model.nusktb')).bones]
    shares = swing.blend(motion, bones, stems)
    played = {i: (row.get('stems') or [None])[0] for row in rows.values() for i in row.get('actions', [])}
    pl, swung = own_dynamics.apply(pl, frozen, played, shares)
    report['swing'] = {'chains': [c['joints'][0] for c in swung['chains']], 'spheres': len(swung['spheres']),
                       'rows': swung['rows'], 'actions': swung['actions']}
    log(f"swing chains: {report['swing']['chains']}; {swung['actions']}")

    # ---- what the game only does for its own fighters: the port's code file, when this route has work for it
    slides = sorted({act.index for c in clips if c.get('travel') == 'code' and c['target_motion'] in installed
                     for act in FighterDat(pl).actions if act.motion == c['target_motion']}) if kit else []
    report['code'] = []
    if mine and mine.get('flash'):
        # a colour a state of the fighter's own lays over the body by its module's word (a stand-in it names: an
        # effect that shows a state is on and has no form here): [(action, frame, frames to get there, from, to)]
        # (and the flashes of the scripts its own states play, which the table above does not reach; an action the
        # table did reach is not given its keys twice)
        lit_already = {k[0] for k in flash}
        own_keys = [tuple(k) for k in mine['flash'] if k[0] not in lit_already]
        flash += own_keys
        report['own_flashes'] = sorted({k[0] for k in own_keys})
    if trail and trail.get('others'):
        # a move the game draws in another picture (Shulk's Back Slash in red, his Air Slash in pink): its actions
        trail['by_action'] = drv.trail_colours(trail['others'], None, full_table, game['moves'], {}, {},
                                               FighterDat(pl).actions)
        report['trail']['by_action'] = trail['by_action']
    # armour on the frames a move's own script gives it (`armour`: [first frame, the frame it ends on] as players
    # count; Fishbunjin's forward and up smashes are not knocked out of their swings), on every action that plays
    # the move's clip (the Ultimate-skeleton route's `oneshot` had this; this route wrote none until 2026-11-13)
    armours = armour_spans(played, game['moves'], drv.script_for) if kit else []
    report['armour'] = armours
    if armours:
        log(f"armour: {len(armours)} stretches the game's scripts give it, on actions {sorted({x for s in armours for x in s['actions']})}")
    from . import own_jab, own_momentum
    jabs = own_jab.collect([p for p in spec['moves'] if p['id'] in done], FighterDat(pl).actions)
    if jabs and not kit:
        raise ValueError('source jab listeners require MexTK; refusing a build with missing input behavior')
    report['jab_listeners'] = jabs
    momentum, report['momentum'] = own_momentum.collect(played, game['moves'], drv.script_for, drawn) if kit else ([], {})
    # ---- final files, read back the way the game will
    final = work / 'final'
    final.mkdir(exist_ok=True)
    # the clips outside the fighter's two files (the results screen's, the cut scenes'): its own, on its own joints
    from . import own_demo

    def demo_script(line):
        """A win pose's sounds, as the game's script for its clip plays them: only what the bank holds, on the
        game's own frames. (The game names a sound played in a win pose `<sound>_winNN`: the same sound.)"""
        import re
        from vault.echo.subactions import COMMANDS
        script = drv.script_for(line['stem'], dict(moves, **unscripted)) if line.get('stem') else None
        move = unscripted.get(script) or moves.get(script)
        if not move or not line.get('frames'):
            return None
        if line.get('source_first') is not None:
            first,last = line['source_first'],line['source_last']
            move = dict(move, sounds=[dict(e,real=float(e['real'])-first) for e in move.get('sounds') or []
                if (float(e['real'])>first or first==0) and float(e['real'])<=last])
        ids = dict(sound_ids)
        for e in move.get('sounds') or []:
            name = str(e.get('name') or '').lower()
            if re.sub(r'_win\d+$', '', name) in sound_ids:
                ids[name] = sound_ids[re.sub(r'_win\d+$', '', name)]
        items, _added = drv.dress([END], move, int(line['frames']), cues, line.get('source_motion') or line['motion'], a.fighter, 0, sound_ids=ids,
                                  first=1, own_only=True)
        items = [i for i in items if COMMANDS[i[0]].key in own_demo.VOICED]
        if not any(COMMANDS[i[0]].key == 'sound_effect' for i in items):
            return None
        return FighterDat.encode_script(items)[0]

    pl, report['demo'] = own_demo.write(final, pl, frozen, a.root, a.fighter, a.donor_zip,
                                        cache=own / 'bank' / 'cache', log=log, script_for=demo_script, continuations=bool(kit))
    # ---- the face: the parts the game's clips show and hide, on every action's script and in the port's code
    pl, mine, report['faces'] = own_faces.carry(pl, own, a.root, a.fighter, jobs + alike, rows, mine, bool(kit), log, demo_jobs=report['demo']['jobs'])
    if not report['faces']:
        skip('eyes', 'the costume carries no parts to show and hide (own_skeleton.body makes them from the clips)')

    # Numeric material curves are separate from whole-piece visibility switches.
    from . import own_opacity
    mine, report['material_opacity'] = own_opacity.carry(
        pl, own, a.root, a.fighter, jobs + alike, rows, mine, bool(kit), demo_jobs=report['demo']['jobs'])

    pl, report['demo']['faces'] = own_faces.outside_a_match(pl, own, a.root, a.fighter, bool(kit), log, demo_jobs=report['demo']['jobs'])
    from . import own_demo_segments
    mine = own_demo_segments.code(mine, report['demo'])
    if kit and (slides or flash or mine or trail or armours or momentum or jabs):
        files, provides = code.source(a.donor, trail, None, armours or None, None, slides, mine,
                                      int(fighter_json['functions']['onLoad']), list((mine or {}).get('entries') or []) or None,
                                      None, None, flash, state_rows=(donor_rows, mine.get('rows', [])) if mine else None, momentum=momentum, jabs=jabs)
        (work / 'code').mkdir(exist_ok=True)
        for name, text in files.items():
            (work / 'code' / name).write_text(text, 'utf-8')
        pl = code.build(pl, files, kit)
        report['code'] = provides
        log('code file:', provides)
    else:
        log('no code file:', 'no move slides along the ground by its clip, none flashes and no special is built' if kit else
            'MexTK not found (give --mextk or set MEXTK_DIR)')


    (final / pl_name).write_bytes(pl)
    (final / aj_name).write_bytes(aj)
    (final / 'lookup.json').write_text((own / 'rig' / 'lookup.json').read_text('utf-8'), 'utf-8')
    for old in list(final.glob('Ef*Data.dat')) + [final / 'effects.json']:
        if old.exists():
            old.unlink()
    report['effect_file'] = effects.write(final)
    if report['effect_file']:
        e = report['effect_file']
        log(f"effect file: {e['file']} ({e['bytes']:,} bytes, {e['generators']} generators) for {len(e['uses'])} effects; "
            f"{len(e['notes'])} notes" + (f"; {e['warnings']}" if e['warnings'] else ''))
    checked = check((final / pl_name).read_bytes(), (final / aj_name).read_bytes(), base_pl, donor_aj, frozen, lookup,
                    a.donor, prefix)
    report['check'] = checked
    log(f"read back: {'PASS' if checked['ok'] else 'FAIL'}; {checked['actions']} actions, {checked['own_clips']} clips of "
        f"its own, largest {checked['largest_clip']['bytes']:,} of {checked['capacity']:,} bytes; "
        f"{checked['joint_indices']} joint indices, highest {checked['highest_joint']} of {checked['joints']}")
    for line in checked['problems'][:20]:
        log('  ' + line)
    listing, lines = moves_table(pl, frozen, game, full_table, rows)
    report['moves'] = listing
    (work / 'moves.txt').write_text(chr(10).join(lines) + chr(10), 'utf-8')
    for line in lines:
        log(line)
    (work / 'report.json').write_text(json.dumps(report, indent=1, default=str), 'utf-8')
    if not checked['ok']:
        raise SystemExit('the written files do not read back: ' + '; '.join(checked['problems'][:5]))
    log('data files ready in', final)
    return report


def own_states_table():
    """The fighters `own.py` builds states of their own for."""
    from . import own
    return own.BUILD


def own_special_clips(fighter):
    """{clip name: donor action} for the clips of a fighter's own special states on this route (`own.OWN_CLIPS`)."""
    from . import own
    return own.OWN_CLIPS.get(fighter, {})


def own_special_hits(fighter):
    """The actions of a fighter's own special states whose hitboxes the route writes from the game's scripts
    (`own.SPECIAL_HITS`): states in which the fighter itself strikes."""
    from . import own
    return own.SPECIAL_HITS.get(fighter, ())


def own_code_sounds(fighter):
    """The sounds of a fighter's that its own code plays, in the order they matter (`own.code_sounds`)."""
    from . import own
    return own.code_sounds(fighter)


def special_dol(a, work, own):
    """The game's executable, for the donor's state table: the one given (--dol), the project beside the work
    folder (where the driver looks), or the project beside the fighter's own folder. -> path or None"""
    for c in (getattr(a, 'dol', None), Path(work).parent / 'project' / 'sys' / 'main.dol',
              Path(own) / 'project' / 'sys' / 'main.dol'):
        if c and Path(c).is_file():
            return Path(c)
    return None
