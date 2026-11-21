"""The clips of a fighter on its OWN skeleton: its animation bank (Pl??AJ.dat) and the table that says where each
clip is.

A fighter's animations are one small archive a clip, end to end in one file; the fighter's data file has a table of
actions, and each action names its clip (a symbol), where it starts in that file and how long it is. The game lays a
clip's joints on the fighter's joints BY POSITION, first on first (ftanim.c, ftAnim_8006F4C8), and it will not load a
clip of more than 0x8000 bytes (ftdata.c, "fighter figatree over!"). A port on its own skeleton clones a donor's states
and tables, so every clip of the donor's is replaced here by one on the new rig: a donor clip left in place would drive
the first joints of a skeleton it was never made for.

This is the general form of what the Pokemon Trainer campaign did with a script a step for three species
(its research_snapshot: bank.py, movement.py, stage6.py, stage6_verify.py, stage6_movement.py),
with two differences:

  * A clip keeps the time its JOB gives it. Those scripts squeezed every clip into the donor's frame count because
    they kept the donor's scripts; here a later stage writes each action's script from the source game's own frames,
    so the work comes in as a list of jobs and that stage decides the timing. With no list, each donor action takes
    the source clip of its own name, whole, frame for frame.
  * The curves are packed here, in Python (`pack_curve`, `write_figatree`), by the rules of the campaign's packer
    (tools/FigaCodec/Program.cs with HSDRaw's FOBJ_Encoder.cs); that packer is a program nobody has built on this
    machine. What is written is read back by a reader this module did not write (compat/fobj_reader.py, which
    replays the game's own fobj.c) before anything is measured.

A job:
    {'motion': 'Wait1',                         # the donor action's motion (between ACTION_ and _figatree)
     'parts': [{'stem': 'a00wait1',             # one source clip, or several played one after another
                'keys': [[0, 0.0], [N, x]]}],   # optional: the part's own frame -> the clip's frame, straight lines
                                                #   between; not given, the whole clip, frame for frame
     'loop': False,                             # optional: the game plays it round and round (its end is its start)
     'travel': 'Z'}                             # optional: the axes of the root's travel the clip keeps (see below)
A part with keys up to frame N takes N + 1 frames (0..N); the next part's first frame is the frame after. A job with
no parts, or none at all for an action, is a held pose: the standing clip's first frame for the donor clip's own
length. Never the donor's clip.

THE ROOT'S TRAVEL. In the source game the `Trans` bone carries the fighter's travel. Melee reads an action's flags
(ftanim.c, ftAnim_8006E9B4): with 0x80000000 on, it takes the travel off the model every frame and hands it to the
action's physics, which uses it or does not; with it off, the travel plays on the model as part of the pose while the
fighter itself stays where physics has it, so travel that does not come back snaps back when the action ends. This
module changes no flags, so each clip is made to suit the donor's:
    PHYSICS          walking, running, dashing, turning, braking: the engine moves the fighter. All travel comes off.
    ANIMATION_DELTA  the flag is on and the action's physics takes the travel: it stays. Six actions were read in the
                     engine's code (rolls, dash attack, dash grab, the moving techs: forward and back only); for the
                     rest the donor's own clip is the evidence (it travels a unit or more on that axis under the
                     flag), and such a row is listed as unsure: the flag can also be on to throw travel away.
    LOCAL_POSE       no travel, or the flag is off and the travel comes back to where it began (a lunge and return,
                     as the donor's own forward smash is made): it stays, as pose.
    ZERO_BY_DEFAULT  anything else comes off, and is listed.
Travel comes off the `Trans` joint itself and everything under it keeps its place relative to it, so no pose changes;
the engine's own joint above it is never given a curve (the engine overwrites that joint: a clip that cancels travel
there slides in the game while it measures as still on the desk).

SIZE AND ERROR. A clip is sampled on quarter frames, each joint's nine numbers are cut down to keys on whole frames
(`scalar_curves.reduce_track`, the campaign's), and the keys are packed. How far a curve may stray is set by what
it can move: a turn's tolerance is a budget of distance over the joint's reach (the furthest any joint under it
gets from it in the clip), so a hip is held far tighter than an ear tip. The budget starts at 0.0003 of the rig's
height; a clip that comes out over the game's limit is made again at the next of `BUDGETS` until it fits, and the
report says which were. Before loosening a budget, an oversized clip also tries dropping channels within that
rest-pose tolerance and giving scale channels a distance/reach budget, capped at SIZE_CAP. This keeps the
full duration and records both attempts. Every clip is then read back from its bytes and compared with the source reader's poses on
sixteenth frames, on whole frames and between them, as shares of the rig's height. Between frames the two cannot
agree where the source snaps a limb far in one frame (see `sharpest_turn`); the report gives that turn beside the error.

    python -m fighter_port.own_bank            # Duck Hunt on Marth: writes bank/PlMs.dat, bank/PlMsAJ.dat, bank/report.json
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from pathlib import Path

import numpy as np

from . import native_port as core

ALIGN = 0x20
CAPACITY = 0x8000                 # ftdata.c:1724: a clip of more than this many bytes is refused
EXTRACTS = 0x80000000             # an action's flag: the root's travel is taken off the model and given to physics
LOOPS = 0x40000000                # an action's flag: the clip plays round and round
ROOT = 'Trans'                    # the source's travelling bone; the engine's "TransN" on the frozen rig
HOLD_STEM = 'a00wait1'            # the standing clip: its first frame is what an action with no source holds
BUDGETS = tuple(round(0.0003 * 2 ** (k / 2), 6) for k in range(15))
#   what one joint's curves may move its furthest descendant by, as a share of the rig's height: the tolerance a
#   clip is cut down to. A clip too big for the game at one is tried at the next (each 1.4 times the last).
TURN_FLOOR = 0.0005               # no turn is asked to be nearer than this (radians): the campaign's own tolerance
TURN_CAP = 0.1                    # and none may be further off than this, however short its reach
LEAST_REACH = 0.05                # a joint with little or nothing under it still carries skin: its reach is taken
#                                   to be at least this share of the rig's height
SIZE_TOLERANCE = 5e-5             # ordinary fit keeps the campaign's scale tolerance
SIZE_CAP = 0.005                  # oversized clips may spend their geometric budget on scale (at most 0.5%)
GRID = 4                          # a clip is fitted on quarter frames
EVAL_GRID = 16                    # and measured on sixteenths, which it was not fitted on
ERROR = 1e-4                      # what packing one number may cost (the campaign packer's)
SCALE_ERROR = 2e-5                # the same for a size: an error in a size is carried down the whole limb
STILL = 2e-6                      # a joint's number that never leaves its rest by more than this gets no curve
MOVES = 1e-4                      # the root is said to travel on an axis once it moves this far along it
RETURNS = 0.02                    # travel has come back when it ends within this share of its reach from its start
DONOR_MOVES = 0.05                # the donor's clip is said to travel on an axis once it moves this far (units)
DONOR_DRIVES = 1.0                # and to move its fighter by that travel once it goes this far
CODEC = 'own-bank-1'

TYPES = (1, 2, 3, 5, 6, 7, 8, 9, 10)          # a joint's nine curves, as the game numbers them: turn, place, size
CON, LIN, SPL0, SPL, SLP, KEY = 1, 2, 3, 4, 5, 6
NUMBER = {0x00: 'f', 0x20: 'h', 0x40: 'H', 0x60: 'b', 0x80: 'B'}

# Who moves the fighter in the common states (from compat/movement_ownership.py, where each is given with the
# engine function that was read: walk, run and the like by their own physics; the six below through ft_80085030,
# which takes the forward axis only).
PHYSICS_MOTIONS = frozenset({'WalkSlow', 'WalkMiddle', 'WalkFast', 'Turn', 'TurnRun', 'Dash', 'Run', 'RunBrake'})
ROOT_MOTIONS = frozenset({'EscapeF', 'EscapeB', 'AttackDash', 'CatchDash', 'PassiveStandF', 'PassiveStandB'})


# ---- the game's packed curves -------------------------------------------------------------------------------------
def varint(value):
    """A whole number as the game packs it: seven bits a byte, low bits first, the top bit saying more follow."""
    value = int(value)
    if value < 0:
        raise ValueError('a packed count cannot be negative')
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def number_format(values, error):
    """How the game holds these numbers: a format byte (the top three bits the kind, the low five the binary point).
    The narrowest kind that holds every one to within `error`, as HSDRaw's FOBJ_Quantanizer picks it (one byte, then
    two, then a float; unsigned when nothing is negative); within that kind, the finest binary point that still
    holds the largest, which costs no byte and is never further off (the donor's own bank is packed that way, and
    goes no finer than 15 places: nor does this, unless the tolerance asks for more)."""
    v = np.asarray(values, dtype=float)
    if not len(v):
        return 0
    kinds = ((0x60, -128, 127), (0x20, -32768, 32767)) if v.min() < 0 else ((0x80, 0, 255), (0x40, 0, 65535))
    for code, low, high in kinds:
        found = None
        for power in range(31):
            scaled = np.rint(v * 2.0 ** power)
            if scaled.min() < low or scaled.max() > high:
                break                                   # a finer point only makes the numbers larger
            if (found is not None and power <= 15) or (found is None and
                                                       np.abs(scaled / 2.0 ** power - v).max() <= error):
                found = power
        if found is not None:
            return code | found
    return 0


def pack_number(value, flag):
    code = NUMBER[flag & 0xE0]
    if code == 'f':
        return struct.pack('<f', value)
    return struct.pack('<' + code, int(round(value * (1 << (flag & 0x1F)))))


def curve_commands(keys):
    """A curve's keys as the game's commands: [(command, value, slope, frames until the next value)].

    The rules of tools/FigaCodec/Program.cs. A key's command says how the curve runs FROM it (the game interpolates
    by the command before the one it has just read): a straight line, or a curve with a slope at each end. The game
    keeps two slopes, the one it left the last key with and the one it arrives with; a slope-only command moves
    them along without moving the clock. So a curved key whose two slopes differ is followed by its leaving slope,
    and a straight key that ends a curve is led by its arriving slope. A curve of one key is a value set once."""
    if not keys:
        raise ValueError('a curve needs a key')
    times = [k.time for k in keys]
    if times[0] != 0 or any(t != int(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('keys sit on whole frames, the first on frame 0, each later than the last')
    if len(keys) == 1:
        return [(KEY, keys[0].value, 0.0, 0)]
    out = []
    for i, k in enumerate(keys):
        if k.outgoing not in ('linear', 'fixed'):
            raise ValueError(f'a key runs on as a line or a curve, not {k.outgoing!r}')
        line = k.outgoing == 'linear'
        if line and i and keys[i - 1].outgoing == 'fixed':
            out.append((SLP, 0.0, k.in_slope, 0))
        out.append((LIN if line else SPL, k.value, k.in_slope, int(times[i + 1] - times[i]) if i + 1 < len(keys) else 0))
        if not line and i + 1 < len(keys) and abs(k.in_slope - k.out_slope) > 1e-6:
            out.append((SLP, 0.0, k.out_slope, 0))
    return out


def pack_commands(commands, value_flag, slope_flag):
    """Commands as the game's bytes: runs of one command, each led by its count and kind (HSDRaw FOBJ_Encoder.cs)."""
    out, i = bytearray(), 0
    while i < len(commands):
        op, j = commands[i][0], i
        while j < len(commands) and commands[j][0] == op:
            j += 1
        out += varint(((j - i - 1) << 4) | op)
        for _, value, slope, wait in commands[i:j]:
            if op != SLP:
                out += pack_number(value, value_flag)
            if op in (SPL, SLP):
                out += pack_number(slope, slope_flag)
            if op in (CON, LIN, SPL0, SPL):
                out += varint(wait)
        i = j
    return bytes(out)


def pack_curve(keys, error=ERROR):
    """-> (the values' format, the slopes' format, the curve's bytes)."""
    commands = curve_commands(keys)
    value_flag = number_format([c[1] for c in commands if c[0] != SLP], error)
    slope_flag = number_format([c[2] for c in commands if c[0] in (SPL, SLP)], error)
    stream = pack_commands(commands, value_flag, slope_flag)
    if len(stream) > 0xFFFF:
        raise ValueError('one curve is longer than the game can count')
    return value_flag, slope_flag, stream


def write_figatree(symbol, frames, nodes):
    """One clip's archive. `nodes`: for each joint of the rig, in the rig's order, its curves as
    (kind, values' format, slopes' format, bytes); a joint with none keeps the model's rest (the game puts every
    joint back to rest before a clip starts, ftAnim_8006FA58). Laid out as the campaign's `compact` laid it:
    the header (lb/lbanim.h FigaTree: kind 1, flags 0, the length), each joint's count of curves ended by -1,
    the curves' twelve-byte rows, then the bytes, equal runs of bytes kept once."""
    from vault.echo import datroot
    if not 1 <= len(nodes) <= 0x8C or any(len(n) > 127 for n in nodes):
        raise ValueError('a clip has 1 to 140 joints of at most 127 curves')
    counts = bytes(len(n) for n in nodes) + b'\xff'
    counts += bytes(-len(counts) % 4)
    rows = [row for node in nodes for row in node]
    table = 20 + len(counts)
    data = bytearray(struct.pack('>iIfII', 1, 0, float(frames), 20, table) + counts + bytes(12 * len(rows)))
    relocations, placed = [12, 16], {}
    for i, (kind, value_flag, slope_flag, stream) in enumerate(rows):
        if not stream:
            raise ValueError('a curve with no bytes')
        if stream not in placed:
            data += bytes(-len(data) % 4)
            placed[stream] = len(data)
            data += stream
        struct.pack_into('>HhBBBBI', data, table + 12 * i, len(stream), 0, kind, value_flag, slope_flag, 0, placed[stream])
        relocations.append(table + 12 * i + 8)
    data += bytes(-len(data) % 4)
    return datroot.build(bytes(data), relocations, [(0, symbol)], [])


# ---- reading a clip back --------------------------------------------------------------------------------------------
def read_clip(blob):
    """A clip's archive as the game reads it, by a reader that is not this module's (compat/fobj_reader.py).
    -> {'symbol', 'kind', 'flags', 'frames', 'counts' (curves a joint), 'tracks' (each with its decoded commands)}"""
    from vault.echo import datroot
    from .compat import fobj_reader
    data, _relocations, roots, extern = datroot.parse(blob)
    if len(roots) != 1 or extern:
        raise ValueError('a clip is one archive with one root')
    at, symbol = roots[0]
    kind, flags, frames = struct.unpack_from('>iIf', data, at)
    _, counts, tracks, _, _ = fobj_reader.read_figatree(data, at)
    return dict(symbol=symbol, kind=kind, flags=flags, frames=frames, counts=list(counts), tracks=tracks)


def node_count(blob):
    """How many joints a clip says it has, read the way the game walks them (from the campaign's stage6.py
    `figatree_nodes`): signed bytes at the header's +0x0C pointer, ended by -1. None when it is not a clip."""
    from vault.echo import datroot
    try:
        data, _relocations, roots, _extern = datroot.parse(blob)
    except Exception:
        return None
    if len(roots) != 1:
        return None
    at = struct.unpack_from('>I', data, roots[0][0] + 0x0C)[0]
    n = 0
    while at + n < len(data):
        if data[at + n] == 0xFF:
            return n
        n += 1
        if n > 0x8C:
            return None
    return None


def clip_animation(blob, order, only=None):
    """A clip's archive as curves that can be posed (rig_benchmark.packed_animation). `only`: just these joints."""
    from . import rig_benchmark as bench
    clip = read_clip(blob)
    channels = [dict(joint=t.node, type=t.type, keys=t.events) for t in clip['tracks']
                if only is None or t.node in only]
    return bench.packed_animation(dict(end=clip['frames'], nodes=len(clip['counts']), channels=channels), order)


# ---- a job's time ------------------------------------------------------------------------------------------------
def part_keys(part, clip_end):
    """A part's map from its own frames to its clip's, checked: [[frame, clip frame], ...], frame 0 first."""
    keys = part.get('keys')
    if not keys:
        return [[0, 0.0], [int(clip_end), float(clip_end)]] if clip_end else [[0, 0.0]]
    out = []
    for key in keys:
        frame, at = key
        if frame != int(frame) or not -1e-6 <= at <= clip_end + 1e-6:
            raise ValueError(f"{part.get('stem')}: a key is [whole frame, clip frame within 0..{clip_end}], not {key}")
        out.append([int(frame), float(min(max(at, 0.0), clip_end))])
    if out[0][0] != 0 or any(b[0] <= a[0] for a, b in zip(out, out[1:])):
        raise ValueError(f"{part.get('stem')}: keys start at frame 0 and each is later than the last")
    return out


def timeline(maps, grid):
    """Where every sample of a job falls. `maps`: each part's checked keys, in order.
    -> (the job's frames at each sample, which part each is in, the clip frame each shows, the job's last frame).
    Every whole frame is there; between two parts there is nothing to sample (one clip ends, the next begins)."""
    frames, parts, shows, at = [], [], [], 0
    for k, keys in enumerate(maps):
        last = keys[-1][0]
        own = np.arange(last * grid + 1, dtype=float) / grid
        frames.append(at + own)
        parts.append(np.full(len(own), k))
        shows.append(np.interp(own, [key[0] for key in keys], [key[1] for key in keys]))
        at += last + 1
    frames, parts, shows = np.concatenate(frames), np.concatenate(parts), np.concatenate(shows)
    if at == 1:                                     # one frame in all: a clip has to last, so it holds for one
        frames = np.arange(grid + 1, dtype=float) / grid
        parts, shows, at = np.zeros(grid + 1, dtype=int), np.full(grid + 1, shows[0]), 2
    return frames, parts, shows, at - 1


# ---- the root's travel -------------------------------------------------------------------------------------------
def root_curve(place, parts):
    """The root's place through a job. Each source clip starts from its own origin (the source game has by then
    moved the fighter to where the clip before it ended), so each later part goes on from the end of the last."""
    place = np.asarray(place, dtype=float)
    out = place.copy()
    for k in sorted(set(parts.tolist()))[1:]:
        first = int(np.argmax(parts == k))
        out[parts == k] += out[first - 1] - place[first]
    return out


def travel_of(curve, least=MOVES):
    """{axis: (how far it reaches, where it ends against where it began)} for the axes the root moves on."""
    reach, net = np.ptp(curve, axis=0), curve[-1] - curve[0]
    return {axis: (float(reach[i]), float(net[i])) for i, axis in enumerate('XYZ') if reach[i] > least}


def travel_policy(motion, extracts, donor, source, wanted=None, mixed=False):
    """What becomes of the root's travel in one clip (see the module's notes).
    `extracts`: the donor action's flag. `donor`, `source`: `travel_of` the donor's clip and of the source's.
    `wanted`: the job's own word (the axes to keep), which settles it. `mixed`: the clip serves actions with the
    flag on and with it off, so it has to be right for both.
    -> {'owner', 'keep', 'cancel' (axes), 'unsure', 'why'}"""
    moving = ''.join(a for a in 'XYZ' if a in source)

    def row(owner, keep, why, unsure=False):
        keep = ''.join(a for a in moving if a in keep)
        return dict(owner=owner, keep=keep, cancel=''.join(a for a in moving if a not in keep), unsure=unsure, why=why)

    if wanted is not None:
        return row('JOB', wanted, 'the job says which axes the clip keeps')
    if not moving:
        return row('LOCAL_POSE', '', 'the clip does not move the root')
    if motion in PHYSICS_MOTIONS:
        return row('PHYSICS', '', "the engine's own physics moves the fighter in this state")
    back = ''.join(a for a in moving if abs(source[a][1]) <= RETURNS * source[a][0] + 1e-3)
    if extracts and not mixed:
        if motion in ROOT_MOTIONS:
            return row('ANIMATION_DELTA', 'Z', "the flag is on and this state's physics takes the forward travel "
                                               "(ft_80085030); sideways and upward travel would be thrown away")
        keep = ''.join(a for a in moving if a in donor and donor[a][0] >= DONOR_DRIVES)
        lost = ''.join(a for a in moving if a not in keep)
        why = []
        if keep:
            why.append(f"the flag is on and the donor's own clip travels on {keep}, so this state is taken to use "
                       "it; its physics was not read")
        if lost:
            why.append(f"the flag is on, so the engine takes {lost} off the model; the donor's clip hardly travels "
                       "there or not at all, so nothing shows it used, and it comes off")
        return row('ANIMATION_DELTA' if keep else 'ZERO_BY_DEFAULT', keep, '; '.join(why), unsure=True)
    why = []
    if back:
        why.append(f"the flag is off and the travel on {back} comes back to where it began: it plays as pose, as the "
                   "donor's own lunges do (the campaign would have taken it off)")
    if len(back) < len(moving):
        why.append(f"the flag is off and the travel on {''.join(a for a in moving if a not in back)} does not come "
                   "back: left in, the model would slide away and snap back when the action ends")
    if motion in ROOT_MOTIONS:
        why.append("the campaign kept forward travel here by switching the action's flag on; this donor's is off "
                   "and the builder changes no flags")
    if mixed:
        why.append('the clip serves actions with the flag on and with it off')
    return row('LOCAL_POSE' if len(back) == len(moving) else 'ZERO_BY_DEFAULT', back, '; '.join(why),
               unsure=len(back) < len(moving) or motion in ROOT_MOTIONS or mixed)


def settle_root(worlds, parts, keep, moved):
    """The poses with the root's travel left on the `keep` axes only. The root joint itself is put where it should
    be and every joint under it (`moved`) goes with it by the same step, so no joint's own turn, place or size
    changes but the root's place. Nothing above the root is touched."""
    place = worlds[ROOT][:, :3, 3]
    curve = root_curve(place, parts)
    step = np.where([a in keep for a in 'XYZ'], curve, curve[0]) - place
    out = dict(worlds)
    for j in moved:
        if j in worlds:
            w = np.array(worlds[j], copy=True)
            w[:, :3, 3] += step
            out[j] = w
    return out


def under(parent, joint):
    """`joint` and every joint below it, given each joint's parent."""
    out = []
    for j in parent:
        k = j
        while k is not None and k != joint:
            k = parent[k]
        if k == joint:
            out.append(j)
    return out


# ---- the source ----------------------------------------------------------------------------------------------------
class Source:
    """The fighter's own clips, and the frozen rig they are laid on."""

    def __init__(self, root, fighter, frozen):
        import ssbh_data_py as ssbh
        from .ultimate import skeleton_metadata
        base = Path(root) / 'gamedata' / 'fighter' / fighter
        self.skeleton = base / 'model' / 'body' / 'c00' / 'model.nusktb'
        self.motion = base / 'motion' / 'body' / 'c00'
        # (less the bones the rig folded, for a source over the engine's limit: own_skeleton.fold_plan)
        from .own_skeleton import source_rig
        self.rig = source_rig(self.skeleton, frozen)
        self.exact = set(frozen.get('provenance', {}).get('scale_exact') or ())
        self.scaled, self.charted = core.rebuild_helpers(frozen, self.rig)
        self.target = core.rig_from_meta(frozen)
        self.height = core.rig_height(self.target)
        if ROOT not in self.target.order or ROOT not in self.rig.order:
            raise ValueError(f'the rig has no {ROOT} joint')
        self.moved = under(self.target.parent, ROOT)
        self.source_moved = under(self.rig.parent, ROOT)
        self.above = [j for j in self.target.order if j not in self.moved]
        self.clips, self.refused, self.hashes = {}, {}, {}
        # tracks for bones the skeleton does not have (Shulk's S_Hip_hit, on 318 of his 359 clips; the donor route's
        # spec names the same as `allow_unbound`): no joint of the rig is made from them, so they move nothing that is
        # drawn or struck. Each clip's are passed over and listed here, not taken as a reason to refuse the clip.
        self.unbound = {}

    def stems(self):
        return sorted(p.stem for p in self.motion.glob('*.nuanmb'))

    def hash(self, stem):
        if stem not in self.hashes:
            path = self.skeleton if stem is None else self.motion / f'{stem}.nuanmb'
            self.hashes[stem] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return self.hashes[stem]

    def clip(self, stem):
        """The clip, or None when the reader refuses it or it is not there (why is kept in `refused`)."""
        from .source_preflight import ANY_BONE, RawSource
        if stem not in self.clips and stem not in self.refused:
            path = self.motion / f'{stem}.nuanmb'
            try:
                if not path.exists():
                    raise FileNotFoundError('the fighter has no such clip')
                raw = RawSource.from_files(self.skeleton, path, allow_unbound=ANY_BONE)
                if raw.ignored:
                    self.unbound[stem] = sorted(raw.ignored)
                core.sanitize_scale(raw)
                unmet = sorted(j for j, track in raw.tracks.items() if track.compensate_scale
                               and j not in self.scaled.helpers and j not in self.exact and j in self.rig.order)
                if unmet:
                    raise ValueError(f"{unmet} make up for a parent's size and the frozen rig has no helper for them")
                self.clips[stem] = raw
            except Exception as exc:
                self.refused[stem] = str(exc)[:200]
        return self.clips.get(stem)

    def poses(self, raw, at):
        """The clip at these clip frames (any order, any repeats), on the frozen rig: joint -> (n, 4, 4)."""
        from . import source_rig_worlds
        once, back = np.unique(np.asarray(at, dtype=float), return_inverse=True)
        worlds = source_rig_worlds.expand(raw, once, self.scaled, self.charted, self.target)
        return {j: w[back] for j, w in worlds.items()}

    def reference(self, raw, at):
        """The same frames by the source reader alone, on the source's own joints: what a clip is measured against."""
        from . import batch_evaluation as batch
        once, back = np.unique(np.asarray(at, dtype=float), return_inverse=True)
        worlds = batch.raw_worlds(raw, once)
        return {j: w[back] for j, w in worlds.items() if j in self.rig.world}

    def root_place(self, raw, at):
        """Where the clip puts the root at these clip frames, from its track alone (it is the skeleton's root)."""
        track = raw.tracks.get(ROOT)
        if track is None:
            return np.repeat(raw.bind[ROOT][None, :3, 3], len(at), axis=0)
        at = np.asarray(at, dtype=float)
        low = np.minimum(np.floor(at).astype(int), raw.end)
        high = np.minimum(low + 1, raw.end)
        u = (at - low)[:, None]
        return (1 - u) * track.t[low] + u * track.t[high]


def job_samples(source, job, grid):
    """A job's samples: (frames, parts, last frame, [(clip, the clip frames its samples show)]), or (None, why)."""
    raws = []
    for part in job.get('parts') or []:
        raw = source.clip(part['stem'])
        if raw is None:
            return None, f"{part['stem']}: {source.refused[part['stem']]}"
        raws.append(raw)
    maps = [part_keys(part, raw.end) for part, raw in zip(job['parts'], raws)]
    frames, parts, shows, end = timeline(maps, grid)
    return (frames, parts, end, [(raw, shows[parts == k]) for k, raw in enumerate(raws)]), None


def job_travel(source, job):
    """`travel_of` the root through a job, from the clips' root tracks alone (cheap: it is asked before anything is
    made, so that what is done with the travel can be part of a clip's cache key)."""
    sampled, why = job_samples(source, job, GRID)
    if sampled is None:
        return None, why
    _frames, parts, _end, clips = sampled
    place = np.concatenate([source.root_place(raw, at) for raw, at in clips])
    return travel_of(root_curve(place, parts)), None


# ---- curves from poses --------------------------------------------------------------------------------------------
def local_tracks(rig, worlds):
    """Each joint's own turn (three angles), place and size through the samples: (joint -> (samples, 9), the most any
    joint's turn was off square before it was squared).

    rig_benchmark.local_vectors with `project_shear=True`, a whole clip at a time instead of a matrix at a time
    (it was nine tenths of a clip's time). Two things differ: a joint's first angles are the ones nearest its rest
    (the same turn can be written two ways, and a joint that never leaves rest should read as rest and get no
    curve), and how far off square the turns were is handed back instead of dropped. A source bind is only as square
    as the floats it is stored in, and a joint under a parent of uneven size leans a little; either is squared up,
    and what that costs shows in the clip's measured error."""
    from . import batch_evaluation as batch
    order = rig.order
    n = len(worlds[order[0]])
    turn = np.empty((n, len(order), 3, 3))
    place, size = np.empty((n, len(order), 3)), np.empty((n, len(order), 3))
    lean = 0.0
    for i, j in enumerate(order):
        p = rig.parent[j]
        local = np.linalg.solve(worlds[p], worlds[j]) if p is not None else np.asarray(worlds[j])
        m = local[:, :3, :3]
        s = np.linalg.norm(m, axis=1)
        if not np.isfinite(local).all() or np.any(s < 1e-10):
            raise ValueError(f'{j}: a joint with no size cannot be animated')
        r = m / s[:, None, :]
        off = np.abs(np.swapaxes(r, 1, 2) @ r - np.eye(3)).max(axis=(1, 2))
        bad = (off > 1e-7) | (np.linalg.det(r) < 0)
        if bad.any():
            u, _, vt = np.linalg.svd(m[bad])
            fixed = u @ vt
            flip = np.linalg.det(fixed) < 0
            if flip.any():
                u[flip, :, -1] *= -1
                fixed[flip] = u[flip] @ vt[flip]
            r[bad] = fixed
            lean = max(lean, float(off.max()))
        turn[:, i], place[:, i], size[:, i] = r, local[:, :3, 3], s
    # the turn as the game's three angles (rig_benchmark.rotation_angles), written the way that follows on from the
    # frame before: of the two ways to write a turn, the one whose angles are nearest the last
    cosine = np.hypot(turn[..., 0, 0], turn[..., 1, 0])
    plain = cosine > 1e-12
    y = np.arctan2(-turn[..., 2, 0], cosine)
    x = np.where(plain, np.arctan2(turn[..., 2, 1], turn[..., 2, 2]), np.arctan2(-turn[..., 1, 2], turn[..., 1, 1]))
    z = np.where(plain, np.arctan2(turn[..., 1, 0], turn[..., 0, 0]), 0.0)
    one, two = np.stack([x, y, z], axis=-1), np.stack([x + np.pi, np.pi - y, z + np.pi], axis=-1)
    angles = np.empty_like(one)
    last = np.array([rig.rest[j]['r'] for j in order], dtype=float)
    for f in range(n):
        a = one[f] - 2 * np.pi * np.round((one[f] - last) / (2 * np.pi))
        b = two[f] - 2 * np.pi * np.round((two[f] - last) / (2 * np.pi))
        other = np.abs(b - last).max(axis=1) < np.abs(a - last).max(axis=1)
        last = angles[f] = np.where(other[:, None], b, a)
    if not np.allclose(batch.euler_matrices(angles.reshape(-1, 3)).reshape(turn.shape), turn, rtol=0, atol=1e-7):
        raise ValueError('a turn was lost in writing it as angles')
    return {j: np.concatenate([angles[:, i], place[:, i], size[:, i]], axis=1) for i, j in enumerate(order)}, lean


def reaches(rig, worlds, stride=4):
    """How far each joint's furthest descendant gets from it in these poses: {joint: units}, nothing for a joint
    with nothing under it (a clip at a time)."""
    index = {j: i for i, j in enumerate(rig.order)}
    below = {j: [] for j in rig.order}
    for j in rig.order:
        k = rig.parent[j]
        while k is not None:
            below[k].append(index[j])
            k = rig.parent[k]
    at = np.stack([np.asarray(worlds[j])[::stride, :3, 3] for j in rig.order], axis=1)
    return {j: float(np.linalg.norm(at[:, below[j]] - at[:, [index[j]]], axis=2).max()) if below[j] else 0.0
            for j in rig.order}


def tolerances(reach, budget, height, scale_min=None):
    """What each curve may be off by, so that no joint's own error moves anything under it by more than `budget`
    (a share of the rig's height): a turn by the budget over the joint's reach, a move by the budget itself
    (a joint's turn at the root of a long limb matters more than a fingertip's).
    -> a function of (joint, kind)."""
    units = budget * height

    def allow(joint, kind):
        if kind >= 8:
            if scale_min is None:
                return SIZE_TOLERANCE
            # A scale error changes a descendant's distance by error / current_scale. Use the
            # smallest absolute scale in this channel, so a nearly hidden limb stays protected.
            return min(SIZE_CAP, units * scale_min[joint, kind] / max(reach[joint], LEAST_REACH * height))
        if kind >= 5:
            return units
        return min(TURN_CAP, max(TURN_FLOOR, units / max(reach[joint], LEAST_REACH * height)))
    return allow


def author(rig, frames, tracks, allow, reducer=None, still=STILL, compact=False, reduced=None):
    """A clip's curves: {(joint, kind): keys}, keys on whole frames only (the game's clock counts whole frames).

    native_port.author_dense, given the joints' numbers already worked out (so that a second, looser try does not
    work them out again) and a tolerance a curve (`allow(joint, kind)`). A number that stays within `still` of
    the joint's rest gets no curve; one that hardly moves gets one key; the rest are cut down to the fewest keys
    that stay within their tolerance of every sample."""
    if reducer is None:
        from .scalar_curves import reduce_track as reducer
    frames = np.asarray(frames, dtype=float)
    whole = [i for i, f in enumerate(frames) if float(f).is_integer()]
    if len(whole) < 2 or not np.array_equal(frames[whole], np.arange(int(frames[-1]) + 1)):
        raise ValueError('every whole frame of the clip has to be among its samples')
    out = {}
    for j in rig.order:
        rest = np.r_[rig.rest[j]['r'], rig.rest[j]['t'], rig.rest[j]['s']]
        for column, kind in enumerate(TYPES):
            values = tracks[j][:, column]
            tolerance = allow(j, kind)
            # Keeping the model's rest value is also an approximation within the same bound.
            # Without this, hundreds of redundant constant channels each cost a table row.
            if np.max(np.abs(values - rest[column])) <= (tolerance if compact else still):
                continue
            key = (j, kind, tolerance)
            if reduced is not None and key in reduced:
                out[j, kind] = reduced[key]
            else:
                out[j, kind] = reducer(frames, values, whole, tolerance)
                if reduced is not None:
                    reduced[key] = out[j, kind]
    return out


def encode(rig, symbol, end, curves):
    """Curves -> the clip's archive, every joint of the rig in it, in the rig's order."""
    index = {j: i for i, j in enumerate(rig.order)}
    nodes = [[] for _ in rig.order]
    for (j, kind), keys in curves.items():
        nodes[index[j]].append((kind, *pack_curve(keys, SCALE_ERROR if kind >= 8 else ERROR)))
    return write_figatree(symbol, end, nodes)


def measure(source, blob, frames, reference):
    """How far the written clip is from the source: read the bytes back, pose the frozen rig with them, and compare
    the source's joints with the source reader's at every sample, whole frames apart from the frames between.
    -> ({'whole', 'between' (the furthest any joint is from its place, as a share of the rig's height), 'joint',
         'frame', 'basis' (the furthest any number of a joint's turn-and-size is off)},
        {axis: how far the written clip moves the root along it, on whole frames})"""
    from . import batch_evaluation as batch
    animation = clip_animation(blob, source.target.order)
    frames = np.asarray(frames, dtype=float)
    posed = batch.animation_worlds(animation, source.target, frames)
    whole = np.array([float(f).is_integer() for f in frames])
    reach = np.ptp(posed[ROOT][whole][:, :3, 3], axis=0)
    posed = {j: posed[j] for j in reference}
    every = batch.measure_worlds(frames, posed, reference)['metrics']
    on = batch.measure_worlds(frames[whole], {j: w[whole] for j, w in posed.items()},
                              {j: w[whole] for j, w in reference.items()})['metrics']
    return (dict(whole=on['pivot']['value'] / source.height, between=every['pivot']['value'] / source.height,
                 joint=every['pivot']['joint'], frame=every['pivot']['frame'], basis=every['basis']['value']),
            {a: round(float(reach[i]), 4) for i, a in enumerate('XYZ') if reach[i] > 1e-3})


def sharpest_turn(rig, worlds, frames, joint, frame):
    """The largest turn, in degrees, that `joint` or any joint above it makes across the one frame that holds
    `frame`. A source clip that swings a limb far from one frame to the next has no true pose between the two:
    the source reader takes the short way round, the game's three angles each take their own way (and near the
    pole of those angles no curve between two whole frames can follow), so the two part company between the
    frames however well they agree on them. This says when that is what an error is."""
    frames = np.asarray(frames, dtype=float)
    low = min(int(np.floor(frame)), int(frames[-1]) - 1)
    a, b = int(np.searchsorted(frames, low)), int(np.searchsorted(frames, low + 1))
    if b >= len(frames) or frames[a] != low or frames[b] != low + 1:
        return 0.0
    most = 0.0
    while joint is not None:
        p = rig.parent[joint]
        own = [np.linalg.solve(worlds[p][i], worlds[joint][i]) if p is not None else worlds[joint][i] for i in (a, b)]
        turn = [m[:3, :3] / np.linalg.norm(m[:3, :3], axis=0) for m in own]
        most = max(most, float(np.degrees(np.arccos(np.clip((np.trace(turn[0].T @ turn[1]) - 1) / 2, -1, 1)))))
        joint = p
    return round(most, 1)


def fit(source, symbol, end, frames, tracks, reach, capacity, reducer=None):
    """Fit the full duration. Oversized clips first compact rest/scale channels at the same budget.

    Ordinary clips retain their previous encoding. The compact retry uses the geometric distance
    budget for scale as well as rotation/translation; its actual pose error is still measured from
    the written bytes on sixteenth frames by make_clip, including any accumulated hierarchy error.
    """
    tried, reduced = [], {}
    # The fixed scale tolerance and capped rotations recur across retries. Their curves need
    # fitting only once per clip; reuse is exact and does not alter packing or error measurement.
    scale_min = {(j, kind): float(np.min(np.abs(tracks[j][:, column])))
                 for j in source.target.order for column, kind in enumerate(TYPES) if kind >= 8}
    for budget in BUDGETS:
        for compact in (False, True):
            allow = tolerances(reach, budget, source.height, scale_min if compact else None)
            curves = author(source.target, frames, tracks, allow, reducer, compact=compact, reduced=reduced)
            blob = encode(source.target, symbol, end, curves)
            tried.append(dict(budget=budget, bytes=len(blob), compact=compact))
            if len(blob) <= capacity:
                return blob, dict(budget=budget, bytes=len(blob), compact=compact, tried=tried,
                                  curves=len(curves), keys=sum(len(k) for k in curves.values()))
    raise ValueError(f"{symbol}: {tried[-1]['bytes']} bytes at the loosest tolerance ({BUDGETS[-1]} of the rig's "
                     f'height); the game takes {capacity}. The full-duration clip cannot fit this rig.')


def make_clip(source, symbol, job, keep, capacity, reducer=None):
    """One job's clip. -> (bytes, its row for the report). The root's travel stays on the `keep` axes."""
    frames, parts, end, clips = job_samples(source, job, GRID)[0]
    worlds = {}
    for raw, at in clips:
        for j, w in source.poses(raw, at).items():
            worlds.setdefault(j, []).append(w)
    worlds = settle_root({j: np.concatenate(w) for j, w in worlds.items()}, parts, keep, source.moved)
    tracks, lean = local_tracks(source.target, worlds)

    eval_frames, eval_parts, _end, eval_clips = job_samples(source, job, EVAL_GRID)[0]
    reference = {}
    for raw, at in eval_clips:
        for j, w in source.reference(raw, at).items():
            reference.setdefault(j, []).append(w)
    reference = settle_root({j: np.concatenate(w) for j, w in reference.items()}, eval_parts, keep,
                            source.source_moved)

    blob, row = fit(source, symbol, end, frames, tracks, reaches(source.target, worlds), capacity, reducer)
    error, root_reach = measure(source, blob, eval_frames, reference)
    error['turn_there'] = sharpest_turn(source.target, worlds, frames, error['joint'], error['frame'])
    row.update(frames=end, stems=[p['stem'] for p in job['parts']], error=error, root_reach=root_reach)
    if lean > 1e-5:
        row['lean'] = lean
    whole = np.array([float(f).is_integer() for f in frames])
    if job.get('loop'):
        gap = max(float(np.linalg.norm(w[whole][-1][:3, 3] - w[whole][0][:3, 3])) for w in worlds.values())
        row['loop_gap'] = gap / source.height
    return blob, row


def hold_pose(source, stem=HOLD_STEM):
    """The pose an action with no source holds: the standing clip's first frame, as one sample on the frozen rig
    and on the source's own joints."""
    raw = source.clip(stem)
    if raw is None:
        raise ValueError(f'the standing clip {stem} cannot be read: {source.refused[stem]}')
    return source.poses(raw, [0.0]), source.reference(raw, [0.0])


def make_hold(source, symbol, frames, pose, capacity):
    """A clip that holds one pose for `frames` frames. -> (bytes, its row)."""
    worlds, reference = pose
    tracks, _lean = local_tracks(source.target, {j: np.repeat(w, 2, axis=0) for j, w in worlds.items()})
    curves = author(source.target, np.array([0.0, 1.0]), tracks, lambda joint, kind: TURN_FLOOR)
    blob = encode(source.target, symbol, frames, curves)
    if len(blob) > capacity:
        raise ValueError(f'{symbol}: a held pose is {len(blob)} bytes; the game takes {capacity}')
    at = np.array([0.0, float(frames)]) if frames > 0 else np.array([0.0])
    error, root_reach = measure(source, blob, at, {j: np.repeat(w, len(at), axis=0) for j, w in reference.items()})
    return blob, dict(budget=BUDGETS[0], bytes=len(blob), tried=[dict(budget=BUDGETS[0], bytes=len(blob))],
                      curves=len(curves), keys=len(curves), frames=frames, stems=[], error=error,
                      root_reach=root_reach)


# ---- the donor ----------------------------------------------------------------------------------------------------
def donor_prefix(actions):
    """The donor's own symbols start with this: the commonest start among its actions' symbols (the part before
    _ACTION_). Other fighters' clips ride in a bank under other starts (a thrown victim's poses)."""
    counts = {}
    for a in actions:
        if a.symbol and a.anim_size and '_ACTION_' in a.symbol:
            start = a.symbol.split('_ACTION_', 1)[0]
            counts[start] = counts.get(start, 0) + 1
    if not counts:
        raise ValueError('the fighter data names no clips')
    return max(counts, key=counts.get)


def donor_travel(blob, joint):
    """`travel_of` the donor's own clip at its travelling joint (quarter frames; a curve that starts late is read
    from its start, as compat/movement_ownership.inspect_clip reads it)."""
    from . import batch_evaluation as batch
    clip = read_clip(blob)
    if not 0 <= joint < len(clip['counts']) or not np.isfinite(clip['frames']) or clip['frames'] <= 0:
        return {}
    animation = clip_animation(blob, [str(i) for i in range(len(clip['counts']))], only={joint})
    start = {t.type: t.start for t in clip['tracks'] if t.node == joint}
    at = np.linspace(0.0, clip['frames'], max(2, int(clip['frames'] * 4) + 1))
    curve = np.zeros((len(at), 3))
    for i, name in enumerate(('translateX', 'translateY', 'translateZ')):
        keys = animation.channels.get(str(joint), {}).get(name)
        if keys:
            curve[:, i] = batch.curve_values(keys, np.maximum(at - start.get(5 + i, 0), 0.0))
    return travel_of(curve, DONOR_MOVES)


def default_jobs(fighter, owned, loops, stems):
    """The jobs when none are given: each donor action takes the source clip of its own name (lower case, after the
    clip's three-letter start; `native_port.build_catalog`, with the fighter's own exceptions if it has any), whole.
    `loops`: {motion: the donor plays it round and round}. -> (jobs, {motion: why it has no source})"""
    species = core.SPECIES.get(fighter) or core.Species(fighter, fighter, core.MARTH)
    rows, _orphans = core.build_catalog(species, owned, stems, {})
    jobs, without = [], {}
    for motion, row in rows.items():
        if row['clip']:
            jobs.append(dict(motion=motion, parts=[dict(stem=row['clip'])], loop=bool(loops.get(motion))))
        else:
            without[motion] = row['reason']
    return jobs, without


# ---- the bank --------------------------------------------------------------------------------------------------------
def assemble(entries):
    """Clips end to end, each starting on a 0x20 boundary. `entries`: (symbol, bytes) in order.
    -> (the bank, {symbol: (where it starts, how long it is)})"""
    bank, spans = bytearray(), {}
    for symbol, blob in entries:
        if symbol in spans:
            raise ValueError(f'{symbol} is in the bank twice')
        spans[symbol] = (len(bank), len(blob))
        bank += blob
        bank += bytes(-len(bank) % ALIGN)
    return bytes(bank), spans


def repoint(pl_bytes, spans):
    """The fighter data with each action's clip start and length set from `spans`; nothing else changes."""
    from vault.echo.subactions import ACTION_SIZE, FighterDat
    fighter = FighterDat(pl_bytes)
    table, _count = fighter.action_table
    for action in fighter.actions:
        if action.symbol in spans:
            start, length = spans[action.symbol]
            fighter.dat.set_u32(table + action.index * ACTION_SIZE + 4, start)
            fighter.dat.set_u32(table + action.index * ACTION_SIZE + 8, length)
    return fighter.to_bytes()


def verify(new_pl, new_aj, donor_pl, donor_aj, prefix, nodes, capacity=CAPACITY, engine=()):
    """The written files, read the way the game will: cut the written bank by the written fighter data's own table.
    Each cut must be one archive, as long as the table says, whose root is the symbol its action names (a cut one
    entry off is still a good clip, just the wrong one); the port's own clips must say exactly `nodes` joints and give no curve to the joints
    numbered in `engine` (the engine's own, outside the travelling one); other fighters' clips must be the donor's byte for
    byte; none may be longer than the game takes; and the fighter data may differ from the donor's only in the
    table's starts and lengths. -> {'ok', 'problems', the counts}"""
    from vault.echo import datroot
    from vault.echo.subactions import ACTION_SIZE, HEADER_SIZE, FighterDat
    fighter, donor = FighterDat(new_pl), FighterDat(donor_pl)
    problems, seen, largest = [], {}, ('', 0)
    rows = own = foreign = 0
    for action, was in zip(fighter.actions, donor.actions):
        if action.symbol != was.symbol:
            problems.append(f'action {action.index}: names {action.symbol}, the donor names {was.symbol}')
        if not action.symbol or not was.anim_size:
            if (action.anim_offset, action.anim_size) != (was.anim_offset, was.anim_size):
                problems.append(f'action {action.index}: has no clip, yet its start or length changed')
            continue
        rows += 1
        start, length = action.anim_offset, action.anim_size
        if start % ALIGN or start + length > len(new_aj):
            problems.append(f'{action.symbol}: {start}..{start + length} is off a 0x20 boundary or past the bank')
            continue
        if length > capacity:
            problems.append(f'{action.symbol}: {length} bytes; the game takes {capacity}')
        blob = new_aj[start:start + length]
        if action.symbol in seen:
            if seen[action.symbol] != (start, length):
                problems.append(f'{action.symbol}: two actions point at different clips')
            continue
        seen[action.symbol] = (start, length)
        try:
            _data, _relocations, roots, _extern = datroot.parse(blob)
        except Exception as exc:
            problems.append(f'{action.symbol}: the cut is not an archive ({exc})')
            continue
        if len(roots) != 1 or roots[0][1] != action.symbol:
            problems.append(f'{action.symbol}: the cut holds {[n for _, n in roots]}')
            continue
        if struct.unpack_from('>I', blob)[0] != length:           # archive.c:30: the game refuses the clip otherwise
            problems.append(f"{action.symbol}: the archive says it is {struct.unpack_from('>I', blob)[0]} bytes, "
                            f'the table {length}')
        if length > largest[1]:
            largest = (action.symbol, length)
        if action.symbol.startswith(prefix):
            own += 1
            if node_count(blob) != nodes:
                problems.append(f'{action.symbol}: {node_count(blob)} joints; the rig has {nodes}')
            else:
                clip = read_clip(blob)
                if clip['kind'] != 1 or clip['flags'] != 0 or any(clip['counts'][i] for i in engine):
                    problems.append(f"{action.symbol}: a wrong header, or a curve on one of the engine's own joints")
        else:
            foreign += 1
            if blob != donor_aj[was.anim_offset:was.anim_offset + was.anim_size]:
                problems.append(f"{action.symbol}: another fighter's clip is not the donor's byte for byte")
    table, count = donor.action_table
    free = {HEADER_SIZE + table + i * ACTION_SIZE + k for i in range(count) for k in range(4, 12)}
    if len(new_pl) != len(donor_pl) or any(a != b and i not in free for i, (a, b) in enumerate(zip(new_pl, donor_pl))):
        problems.append("the fighter data differs from the donor's outside the table's starts and lengths")
    return dict(ok=not problems, problems=problems, rows=rows, clips=len(seen), own=own, foreign=foreign,
                bank_bytes=len(new_aj), largest=dict(symbol=largest[0], bytes=largest[1]), capacity=capacity,
                rig_joints=nodes)


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:40]


def build(pl_bytes, aj_bytes, frozen, root, fighter, jobs=None, capacity=CAPACITY, log=print, *, cache=None,
          prefix=None, donor_root_joint=1, hold=HOLD_STEM, reducer=None):
    """The donor's fighter data and bank -> (the fighter data repointed, the new bank, the report).

    `pl_bytes`, `aj_bytes`: the DONOR's own pair, untouched (other fighters' clips are copied out of this bank by
    this table). `frozen`: the rig file's contents. `root`: the folder that holds gamedata/fighter/<fighter>.
    `jobs`: see the module's notes; not given, every action takes the source clip of its own name.
    `cache`: a folder to keep made clips in (keyed by the rig, the job, the source files, what is done with the
    root's travel, the tolerances and this file). `donor_root_joint`: the donor's travelling joint (1 in every
    fighter the game ships: the joint under the top one)."""
    from vault.echo import datroot
    from vault.echo.subactions import FighterDat
    started = time.time()
    donor = FighterDat(pl_bytes)
    prefix = prefix or donor_prefix(donor.actions)
    source = Source(root, fighter, frozen)
    nodes = len(source.target.order)
    cache = Path(cache) if cache else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    rig_hash = _key({k: frozen[k] for k in ('order', 'parent', 'rest')}, frozen['provenance'].get('scale_helpers'),
                    frozen['provenance'].get('chart_helpers'))
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    settings = dict(codec=CODEC, code=code_hash, budgets=BUDGETS, turn_floor=TURN_FLOOR, turn_cap=TURN_CAP,
                    least_reach=LEAST_REACH, size_tolerance=SIZE_TOLERANCE, size_cap=SIZE_CAP, grid=GRID, eval_grid=EVAL_GRID,
                    error=ERROR, scale_error=SCALE_ERROR, still=STILL, capacity=capacity,
                    reducer=getattr(reducer, '__name__', 'reduce_track'))

    # the donor's actions by clip: one clip can serve several actions
    by_symbol = {}
    for action in donor.actions:
        if action.symbol and action.anim_size:
            by_symbol.setdefault(action.symbol, []).append(action)
    for symbol, actions in by_symbol.items():
        spans = {(a.anim_offset, a.anim_size) for a in actions}
        start, length = next(iter(spans))
        try:
            named = datroot.parse(aj_bytes[start:start + length])[2]
        except Exception:
            named = []
        if len(spans) != 1 or [n for _, n in named] != [symbol]:
            raise ValueError(f"{symbol}: the bank does not hold this clip where the fighter data says; give the "
                             "donor's own two files")
    own = {s: a for s, a in by_symbol.items() if s.startswith(prefix)}
    motion_of = {s: a[0].motion for s, a in own.items()}
    loops = {motion_of[s]: any(a.flags & LOOPS for a in acts) for s, acts in own.items()}

    without = {}
    given = jobs is not None
    if jobs is None:
        jobs, without = default_jobs(fighter, {motion_of[s]: a[0] for s, a in own.items()}, loops, source.stems())
    by_motion = {}
    for job in jobs:
        if job['motion'] in by_motion:
            raise ValueError(f"two jobs for {job['motion']}")
        by_motion[job['motion']] = job
    strays = sorted(set(by_motion) - set(motion_of.values()))

    pose = hold_pose(source, hold)
    entries, rows, hits = [], {}, 0
    total = len(by_symbol)
    for n, (symbol, actions) in enumerate(by_symbol.items(), 1):
        start, length = actions[0].anim_offset, actions[0].anim_size
        old = aj_bytes[start:start + length]
        if symbol not in own:
            entries.append((symbol, old))
            rows[symbol] = dict(kind='FOREIGN', bytes=length, actions=[a.index for a in actions])
            continue
        motion = motion_of[symbol]
        job = by_motion.get(motion)
        extracting = [bool(a.flags & EXTRACTS) for a in actions]
        was = donor_travel(old, donor_root_joint)
        donor_frames = read_clip(old)['frames']
        base = dict(motion=motion, actions=[a.index for a in actions], extracts=all(extracting),
                    donor_frames=donor_frames, donor_bytes=length)
        if any(extracting) != all(extracting):
            base['mixed_flags'] = True
        if was:
            base['donor_travel'] = {a: [round(v, 3) for v in t] for a, t in was.items()}
        travel, why = (None, without.get(motion, 'no job for this action'))
        if job is not None and job.get('parts'):
            travel, why = job_travel(source, job)
        elif job is not None:
            why = 'the job has no parts'
        if travel is None:
            key = _key('hold', settings, rig_hash, symbol, donor_frames, hold, source.hash(hold), source.hash(None))
            made = lambda: make_hold(source, symbol, donor_frames, pose, capacity)
            base.update(kind='HELD', why=why)
        else:
            policy = travel_policy(motion, all(extracting), was, travel, job.get('travel'),
                                   mixed=any(extracting) != all(extracting))
            key = _key('clip', settings, rig_hash, symbol, job.get('parts'), bool(job.get('loop')), policy['keep'],
                       [source.hash(p['stem']) for p in job['parts']], source.hash(None))
            made = lambda: make_clip(source, symbol, job, policy['keep'], capacity, reducer)
            base.update(kind='SOURCE', travel=dict(policy, source={a: [round(v, 3) for v in t]
                                                                    for a, t in travel.items()}))
        blob = row = None
        if cache and (cache / f'{key}.dat').exists() and (cache / f'{key}.json').exists():
            blob, row = (cache / f'{key}.dat').read_bytes(), json.loads((cache / f'{key}.json').read_text('utf-8'))
            hits += 1
        if blob is None:
            blob, row = made()
            if cache:
                (cache / f'{key}.dat').write_bytes(blob)
                (cache / f'{key}.json').write_text(json.dumps(row), 'utf-8')
        rows[symbol] = dict(base, **row)
        entries.append((symbol, blob))
        log(f"  [{n}/{total}] {motion:<20} {base['kind']:<6} {row['frames']:>5.0f}f {row['bytes']:>6}B  "
            f"budget {row['budget']:<8} off {row['error']['whole']:.5f} whole, {row['error']['between']:.5f} between"
            + (f"  (was {row['tried'][0]['bytes']}B)" if len(row['tried']) > 1 else ''))

    new_aj, spans = assemble(entries)
    new_pl = repoint(pl_bytes, spans)
    checked = verify(new_pl, new_aj, pl_bytes, aj_bytes, prefix, nodes, capacity,
                     [source.target.order.index(j) for j in source.above])
    # did what was decided about the root's travel reach the bytes? (the campaign's stage6_movement.py: its first
    # try took every clip from a cache made before the decision and changed nothing.) Read from the written clips.
    for row in rows.values():
        if row['kind'] != 'SOURCE':
            continue
        travel, wrote = row['travel'], row['root_reach']
        for axis in travel['cancel']:
            if axis in wrote:
                checked['problems'].append(f"{row['motion']}: travel on {axis} was to come off; the clip moves "
                                           f"the root {wrote[axis]} along it")
        for axis in travel['keep']:
            if abs(wrote.get(axis, 0.0) - travel['source'][axis][0]) > 0.05 * travel['source'][axis][0] + 0.05:
                checked['problems'].append(f"{row['motion']}: travel on {axis} was to stay ({travel['source'][axis][0]}"
                                           f"); the clip moves the root {wrote.get(axis, 0.0)} along it")
    checked['ok'] = not checked['problems']

    made = {s: r for s, r in rows.items() if r['kind'] != 'FOREIGN'}
    sourced = {r['motion']: r for r in made.values() if r['kind'] == 'SOURCE'}
    held = {r['motion']: r for r in made.values() if r['kind'] == 'HELD'}
    brief = lambda r: dict(motion=r['motion'], stems=r['stems'], frames=r['frames'], bytes=r['bytes'], budget=r['budget'],
                           whole=r['error']['whole'], between=r['error']['between'], joint=r['error']['joint'],
                           frame=r['error']['frame'], turn_there=r['error'].get('turn_there', 0.0))
    moved = {m: r['travel'] for m, r in sourced.items() if r['travel']['source']}
    report = dict(
        schema='own-bank-1', fighter=fighter, prefix=prefix, rig_joints=nodes, rig_height=source.height,
        capacity=capacity, settings=settings, jobs='given' if given else "each action's own name",
        totals=dict(rows=checked['rows'], clips=checked['clips'], own_clips=len(made), with_source=len(sourced),
                    held=len(held), foreign=checked['foreign'], bank_bytes=len(new_aj), donor_bank_bytes=len(aj_bytes),
                    largest=checked['largest'], loosened=sum(len(r['tried']) > 1 for r in made.values()),
                    cached=hits, seconds=round(time.time() - started, 1)),
        with_source=sorted(sourced), held={m: r['why'] for m, r in sorted(held.items())},
        jobs_for_no_action=strays, refused_clips=dict(source.refused),
        # {bone the skeleton lacks: clips with a track for it}: passed over (they move nothing of the rig)
        unbound_tracks={b: sorted(s for s, bs in source.unbound.items() if b in bs)
                        for b in sorted({b for bs in source.unbound.values() for b in bs})},
        travel=dict(
            rule="by the donor action's flag 0x80000000 (this builder changes no flags): PHYSICS = the engine walks "
                 "the fighter, all travel off; ANIMATION_DELTA = flag on and the state's physics takes the travel, "
                 "kept; LOCAL_POSE = no travel, or flag off and the travel comes back to its start, kept as pose; "
                 "ZERO_BY_DEFAULT = anything else, off. A job's own 'travel' settles it.",
            cancelled={m: dict(axes=t['cancel'], owner=t['owner'], why=t['why']) for m, t in sorted(moved.items())
                       if t['cancel']},
            kept={m: dict(axes=t['keep'], owner=t['owner'], why=t['why']) for m, t in sorted(moved.items())
                  if t['keep']},
            unsure={m: t['why'] for m, t in sorted(moved.items()) if t['unsure']},
            # the donor moves its fighter by its clip here (the flag is on and its clip travels), and the new clip
            # does not travel on that axis: whoever writes the action has to move the fighter some other way
            donor_travel_not_in_the_clip={
                r['motion']: dict(donor=r['donor_travel'], clip=r.get('root_reach', {}), kind=r['kind'])
                for r in made.values()
                if r['extracts'] and r['motion'] not in PHYSICS_MOTIONS
                and any(t[0] >= DONOR_DRIVES and a not in r.get('root_reach', {})
                        for a, t in r.get('donor_travel', {}).items())}),
        loops_that_do_not_close={m: r['loop_gap'] for m, r in sorted(sourced.items()) if r.get('loop_gap', 0) > 0.005},
        loosened=[dict(brief(r), tried=r['tried']) for r in sorted(made.values(), key=lambda r: -r['budget'])
                  if len(r['tried']) > 1],
        worst=[brief(r) for r in sorted(made.values(), key=lambda r: -r['error']['between'])[:10]],
        worst_on_whole_frames=[brief(r) for r in sorted(made.values(), key=lambda r: -r['error']['whole'])[:10]],
        # the campaign's own pass marks (native_port.RELATIVE_ACCEPTANCE), for comparison: nothing is refused on them
        past_the_campaigns_marks=dict(
            marks=dict(whole=core.RELATIVE_ACCEPTANCE['integer_pivot'], between=core.RELATIVE_ACCEPTANCE['fine_pivot']),
            whole=sorted(m for m, r in sourced.items() if r['error']['whole'] > core.RELATIVE_ACCEPTANCE['integer_pivot']),
            between=sorted(m for m, r in sourced.items()
                           if r['error']['between'] > core.RELATIVE_ACCEPTANCE['fine_pivot'])),
        job_list=[by_motion[m] for m in sorted(by_motion)],
        verify=checked,
        notes=["Nothing here was run in the game: every figure is from reading the written files back.",
               "'whole' and 'between' are the furthest any source joint is from its place, as a share of the rig's "
               "height, on whole frames and on sixteenths of a frame; 'turn_there' is the largest turn (degrees) a "
               "joint above the worst one makes across that one frame in the source. Where it is large the error "
               "between frames is the source swinging a limb within one frame, which keys on whole frames cannot "
               "follow, not a loose fit.",
               "'budget' is the tolerance a clip was cut down to (see BUDGETS); a clip in 'loosened' did not fit the "
               "game's limit at the first."],
        rows=rows)
    if not checked['ok']:
        raise ValueError('the written bank does not read back: ' + '; '.join(checked['problems'][:5]))
    return new_pl, new_aj, report


def main(argv=None):
    import argparse
    scratch = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[3]) / 'app' / 'scratch'
    ap = argparse.ArgumentParser(description='Build the animation bank of a fighter on its own skeleton.')
    ap.add_argument('--fighter', default='duckhunt')
    ap.add_argument('--root', type=Path, default=Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904'),
                    help='the folder that holds gamedata/fighter/<fighter>')
    ap.add_argument('--work', type=Path, help='the port\'s work folder (default: scratch/<fighter>-native)')
    ap.add_argument('--donor', type=Path, default=scratch / 'brawl-oneshot' / 'port' / 'donor',
                    help="the folder with the donor's own fighter data and bank")
    ap.add_argument('--jobs', type=Path, help='a JSON list of jobs (default: each action takes the clip of its name)')
    ap.add_argument('--capacity', type=lambda v: int(v, 0), default=CAPACITY)
    ap.add_argument('--no-cache', action='store_true')
    a = ap.parse_args(argv)
    from . import compat
    compat.install()
    species = core.SPECIES.get(a.fighter)
    names = species.donor if species else core.MARTH
    work = a.work or scratch / f'{a.fighter}-native'
    out = work / 'bank'
    out.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((work / 'rig' / f'rig-{a.fighter}.json').read_text('utf-8'))
    jobs = json.loads(a.jobs.read_text('utf-8')) if a.jobs else None
    pl, aj, report = build((a.donor / names.pl).read_bytes(), (a.donor / names.aj).read_bytes(), frozen, a.root,
                           a.fighter, jobs, a.capacity, cache=None if a.no_cache else out / 'cache',
                           prefix=names.symbol_prefix)
    if not report['totals']['cached']:
        report['totals']['seconds_for_a_whole_build'] = report['totals']['seconds']
    (out / names.pl).write_bytes(pl)
    (out / names.aj).write_bytes(aj)
    # the same check again, on what is now on the disk
    donor_pl, donor_aj = (a.donor / names.pl).read_bytes(), (a.donor / names.aj).read_bytes()
    engine = [i for i, j in enumerate(frozen['order']) if j not in under(frozen['parent'], ROOT)]
    written = verify((out / names.pl).read_bytes(), (out / names.aj).read_bytes(), donor_pl, donor_aj,
                     names.symbol_prefix, len(frozen['order']), a.capacity, engine)
    report['written'] = dict(written, files={n: dict(path=str(out / n), bytes=(out / n).stat().st_size,
                                                    sha256=hashlib.sha256((out / n).read_bytes()).hexdigest())
                                             for n in (names.pl, names.aj)})
    (out / 'report.json').write_text(json.dumps(report, indent=1), 'utf-8')
    if not written['ok']:
        raise SystemExit('the files on the disk do not read back: ' + '; '.join(written['problems'][:5]))
    t = report['totals']
    print(f"{a.fighter}: {t['rows']} actions, {t['own_clips']} clips of its own ({t['with_source']} from the source, "
          f"{t['held']} held), {t['foreign']} of other fighters; bank {t['bank_bytes']:,} bytes, largest "
          f"{t['largest']['symbol']} {t['largest']['bytes']:,}; {t['loosened']} loosened; {t['seconds']} s "
          f"({t['cached']} from the cache)")
    print(f"wrote {out / names.pl}, {out / names.aj}, {out / 'report.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
