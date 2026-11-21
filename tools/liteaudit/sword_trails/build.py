"""Sword trails for Watch Lite (swordTrails.js), from the game's own afterimage rule and the vanilla ISO.

The rule (melee decomp, ftafterimage.c):
  - Subaction command 0x31 "Sword Trail" (ftAction_80072B3C) writes its 25-bit value to Fighter +0x2100:
    0 starts a trail (the sample count restarts), -1 stops it; its beam-sword bit (+0x2101 bit 7) makes
    the trail follow a held Beam Sword instead of the fighter's own sword. Every other motion change
    stops it (fighter.c, Fighter_ChangeMotionState: only Marth's and Roy's Dancing Blade ground/air
    switch passes Ft_MF_KeepSwordTrail, and that switch replays the new script up to the same frame).
  - Each frame that did not start in hitlag (fighter.c, Fighter_ProcessHit_8006D1EC: x2219_b6),
    ftCo_800C2FD8 pushes the sword joint's world position and its X axis (the matrix's first column,
    model scale included) into a ring of 3; the count stops at 3.
  - With 2 or more samples, ftCo_800C2600 draws one triangle strip in the fighter's see-through pass,
    after its model: per sample the points base + axis x inner and base + axis x outer, from the
    newest sample (inner..outer = the attributes' x18..x1C) to the oldest, where they have moved to
    x18 + (x1C - x18) x x0 and ... x x4 (x0, x4 = the "old" fractions below); between samples the axis
    turns about their cross product in steps of 5 degrees (0.0872665 rad) while the base moves
    straight. Inner vertices are coloured xA..xC, outer ones xE..x10, alpha x8 at the newest sample to
    x9 at the oldest, interpolated by the distance the tip (base + axis x outer) travelled; blended
    src-alpha / inv-src-alpha, no texture, z-tested, not culled.
  - Fighters (the switch in ftCo_800C2600): Link and Young Link use ftLk_DatAttrs +0x64, Marth and Roy
    MarsAttributes +0x78 (the special attributes, ftData +0x04), struct SwordAttrs:
      +0x00 x0, +0x04 x4 (f32)  the oldest sample's inner and outer edge, as fractions of the blade
      +0x08 alpha new, +0x09 alpha old, +0x0A..0C inner RGB, +0x0E..10 outer RGB (u8)
      +0x14 part (s32), +0x18 inner, +0x1C outer (f32)  the sword joint and the blade along its X axis
    No other vanilla fighter has the command outside its item swings.
  - A held Beam Sword (every fighter's Swing1/3/4/Dash states, Captain Falcon's Swing42: the command's
    item bit) takes ftCo_800C2FD8's item branch: the sword item's bone 5 (it_80285314) and its Y axis
    (matrix column 1), inner 0, outer it_802852B8 = 10.03 x 0.3 x x28 x x4C x x10 (bone 6's Y scale
    x 10.03): x4C the blade bone's bind Y scale, x28 2 once held (picked up: 1 -> 2 over 4 frames), x10
    the swing's own length commands (subaction 0x2D, ftAction_800729D4: extend restarts it at 1 and
    moves it to a target over N frames, retract moves it back to 1). The draw takes the item's bytes
    (special attributes +0x1C, it_80285300): no taper, alpha 1 -> 0, pink ff40ff to white. The item's
    attach bone (model desc +0x8) is constrained to the fighter's hold part, whose own scale cancels the
    model scale (8007F6A4), and bone 5 hangs off it (ItCo.dat article 12).

    app/venv/Scripts/python.exe -B tools/liteaudit/sword_trails/build.py [--iso PATH]

Writes a `trail` key into app/frontend/src/tracker/replays/data/hits/<cid>.json (the per-fighter tables
the hosts already load, stageData.ensureReplayHitData) of Link 6, Marth 18, Young Link 20 and Roy 26,
and a `beam` key into every fighter's but Nana's (a follower), keeping everything else in the file
(tools/liteaudit/hit_tables.mjs carries both over when it rewrites them):
  trail {inner, outer, old: [x0, x4], alpha: [new, old] (0..1), color: ['rrggbb' inner, 'rrggbb' outer],
         states: {state: windows | state}}
  windows [[first, last, [[bx, by, bz, ax, ay, az] per action frame first..last]], ...]: the action
         frames (floor of Slippi's frame counter, as the fighter's pose) a trail is on, from the frame
         its start command runs to the one before it stops; the sword joint's position and X axis there,
         fighter-local (x along the facing, y up, z toward the camera when facing right), model scale
         applied (position to 0.1, axis to 0.01); a number is a state with exactly the same windows.
  beam  {old, alpha, color, states}: the same for a held Beam Sword, each row [bone 5's position, its
         Y axis, the blade's outer end] (inner is 0).
"""
import argparse
import json
import math
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[1:1] = [str(REPO / 'tools/liteaudit'), str(REPO / 'tools/liteaudit/item_shapes'), str(REPO / 'app/backend')]
DATA = REPO / 'app/frontend/src/tracker/replays/data'

import fighterbones as fb  # noqa: E402
import hsdgeom  # noqa: E402
import numpy as np  # noqa: E402
import isofiles  # noqa: E402
import stage_bake as sb  # noqa: E402

SWORD_TRAIL = 49                     # subaction command 0x31 (0xC4 >> 2)
BLADE_LENGTH = 45                    # subaction command 0x2D (0xB4 >> 2), ftAction_800729D4
BEAM_SWORD, BEAM_JOINT, BLADE_BONE = 12, 5, 6
BLADE_REACH = 10.03 * 0.3            # it_802852B8: outer = 10.03 x 0.3 x x28 x x4C x x10 (bone 6's Y scale x 10.03)
BEAM_HELD_X28 = 2.0                  # itSword_Logic12_PickedUp: x28 goes 1 -> 2 over the first 4 held frames
# fighter code -> offset of struct SwordAttrs in its special attributes (ftCo_800C2600)
FIGHTERS = {'Lk': 0x64, 'Ms': 0x78, 'Cl': 0x64, 'Fe': 0x78}


def attrs(code):
    fd = fb.fighter(code)['fd']
    at = fd.dat.ptr(fd.ft_root + 4) + FIGHTERS[code]
    raw = bytes(fd.dat.buf[32 + at:32 + at + 0x20])
    x0, x4 = struct.unpack_from('>ff', raw, 0)
    part, inner, outer = struct.unpack_from('>iff', raw, 0x14)
    return dict(part=part, inner=inner, outer=outer, old=[x0, x4], alpha=[raw[8] / 255, raw[9] / 255],
                color=[raw[0xA:0xD].hex(), raw[0xE:0x11].hex()])


def commands(code, state):
    f = fb.fighter(code)
    a = f['fd'].actions[f['indices'][state]]
    try:
        return sb.commands(f['fd'], a, fb.tracks(code, state)[0])
    except ValueError:
        # a stream that loops without waiting (a few wait/idle states); none has the command
        script = f['fd'].script(a.index)
        assert not (script and script.of_code(SWORD_TRAIL)), (code, state)
        return []


def windows(code, state, beam=False):
    """[(first, stop)) action frames the fighter's own trail (beam: the held Beam Sword's) is on, from
    the state's command stream; any other trail command ends it."""
    end = fb.tracks(code, state)[0]
    out, start = [], None
    for t, op, h in commands(code, state):
        if op != SWORD_TRAIL:
            continue
        value = (h['unknown'] << 8 | h['render_status'])
        value = value - (1 << 25) if value & (1 << 24) else value      # the command's signed 25 bits
        frame = math.ceil(t)                                            # it runs on the first frame >= t
        if start is not None:
            out.append((start, frame))
            start = None
        if value == 0 and bool(h['beam_sword']) == beam:
            start = frame
    if start is not None:
        out.append((start, int(end) + 1))
    return [(a0, a1) for a0, a1 in out if a1 > a0]


def r2(v):
    v = round(float(v), 2)
    return 0.0 if v == 0 else v


def r1(v):
    v = round(float(v), 1)
    return 0.0 if v == 0 else v


def sample(code, state, frame, part):
    """the joint's position (0.1 units) and X axis (0.01: the tip, ~9 units out, moves under 0.1)"""
    m = fb.world(code, state, float(frame))[part]
    return [r1(v) for v in m[:3, 3]] + [r2(v) for v in m[:3, 0]]


def trail(code):
    f = fb.fighter(code)
    a = attrs(code)
    states, seen = {}, {}
    for state, index in enumerate(f['indices']):
        if index < 0 or index >= len(f['fd'].actions) or not f['fd'].actions[index].anim_size:
            continue
        runs = [[w0, w1 - 1, [sample(code, state, fr, a['part']) for fr in range(w0, w1)]] for w0, w1 in windows(code, state)]
        if not runs:
            continue
        sig = json.dumps(runs)
        if sig in seen:
            states[str(state)] = seen[sig]
        else:
            seen[sig] = state
            states[str(state)] = runs
    return dict(inner=r2(a['inner']), outer=r2(a['outer']), old=[r2(v) for v in a['old']], alpha=a['alpha'],
                color=a['color'], states=states), a['part']


def beam_attrs():
    """The Beam Sword (ItCo.dat article 12): its trail's SwordAttrs-like bytes (special attributes +0x1C,
    it_80285300), the bone chain from the attach bone (model desc +0x8, constrained to the hand) to bone 5
    (it_80285314), the blade bone 6's bind Y scale (x4C) and the item scale (ItemAttr +0x60)."""
    d = isofiles.dat('ItCo.dat')
    art = d.p(d.p(dict(d.roots)['itPublicData'] + 4) + 4 * BEAM_SWORD)
    sp = d.p(art + 4)
    raw = bytes(d.b(sp + 0x1C + k) for k in range(0x14))
    md = d.p(art + 0x10)
    attach, js = d.u(md + 8), hsdgeom.joints(d, d.p(md))
    chain, k = np.eye(4), BEAM_JOINT
    while k != attach:
        chain = hsdgeom.srt(js[k]['s'], js[k]['r'], js[k]['t']) @ chain
        k = js[k]['parent']
    x0, x4 = struct.unpack_from('>ff', raw, 0)
    return dict(old=[x0, x4], alpha=[raw[8] / 255, raw[9] / 255], color=[raw[0xA:0xD].hex(), raw[0xE:0x11].hex()],
                chain=chain, x4C=js[BLADE_BONE]['s'][1], scale=d.f(d.p(art) + 0x60))


def blade(code, state):
    """The Beam Sword's length variable x10 after each action frame (itsword.c): subaction 0x2D
    (ftAction_800729D4) mode 0 restarts it at 1 and moves it to target / 256 over its frames
    (it_80284FC4), mode 1 moves it back to 1 (it_80285024); the item steps it once a frame
    (it_80285084), after the fighter's commands and before the trail's push reads it, except on the
    swing's first frame (action frame 1): the item updated before the fighter changed state.
    Measured in RAM on Mario's four swings: exact but where a swing starts while the last one's
    blade is still retracting (the length carries over; here it starts at 1)."""
    end = int(fb.tracks(code, state)[0])
    cmds = [(math.ceil(t), h) for t, op, h in commands(code, state) if op == BLADE_LENGTH]
    x10, step, target, out, k = 1.0, 0.0, 1.0, [], 0
    for fr in range(end + 1):
        while k < len(cmds) and cmds[k][0] <= fr:
            raw = cmds[k][1]['unknown'] << 18 | cmds[k][1]['duration']
            mode, frames = raw >> 24, max(1, (raw >> 14) & 0x3FF)
            if mode == 0:
                x10, target = 1.0, (raw & 0x3FFF) / 256
            elif mode == 1:
                target = 1.0
            step = (target - x10) / frames
            k += 1
        if fr >= 2:
            x10 += step
            if (step > 0 and x10 > target) or (step < 0 and x10 < target):
                x10, step = target, 0.0
        out.append(x10)
    return out


def beam(code, b):
    """Per state with a Beam Sword trail: its windows, each action frame [bone 5's position, its Y axis
    (ftCo_800C2FD8 takes column 1 for the item), the blade's outer end (inner is 0)], fighter-local."""
    f = fb.fighter(code)
    hold = fb.hold_part(code)
    states, seen = {}, {}
    for state, index in enumerate(f['indices']):
        if index < 0 or index >= len(f['fd'].actions) or not f['fd'].actions[index].anim_size:
            continue
        ws = windows(code, state, beam=True)
        if not ws:
            continue
        x10 = blade(code, state)
        runs = []
        for w0, w1 in ws:
            rows = []
            for fr in range(w0, w1):
                h = fb.world(code, state, float(fr))[hold]
                a = np.eye(4)
                # the hold part's own scale cancels the model scale (8007F6A4): a unit rotation
                a[:3, :3] = h[:3, :3] / np.linalg.norm(h[:3, :3], axis=0)
                a[:3, 3] = h[:3, 3]
                m = a @ np.diag([b['scale']] * 3 + [1.0]) @ b['chain']
                outer = BLADE_REACH * BEAM_HELD_X28 * b['x4C'] * x10[min(fr, len(x10) - 1)]
                rows.append([r1(v) for v in m[:3, 3]] + [r2(v) for v in m[:3, 1]] + [r2(outer)])
            runs.append([w0, w1 - 1, rows])
        sig = json.dumps(runs)
        if sig in seen:
            states[str(state)] = seen[sig]
        else:
            seen[sig] = state
            states[str(state)] = runs
    return states


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    args = ap.parse_args()
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    iso = args.iso or known_vanilla_iso()
    if not iso:
        sys.exit('no vanilla ISO recorded; pass --iso')
    isofiles.open_iso(Path(iso))
    b = beam_attrs()
    print(f"beam sword: old {b['old']}, alpha {b['alpha']}, colours {b['color']}, x4C {b['x4C']}, scale {b['scale']}")
    for code in fb.CODES:
        cid = fb.CODES.index(code)
        path = DATA / 'hits' / f'{cid}.json'
        d = json.loads(path.read_text(encoding='utf-8'))
        size = len(json.dumps(d, separators=(',', ':')))
        if code in FIGHTERS:
            d['trail'], part = trail(code)
        states = beam(code, b)
        if states:
            d['beam'] = dict(old=[r2(v) for v in b['old']], alpha=b['alpha'], color=b['color'], states=states)
        else:
            d.pop('beam', None)
        text = json.dumps(d, separators=(',', ':'))
        path.write_text(text + '\n', encoding='utf-8')
        print(f"{code} (cid {cid}): trail {len(json.dumps(d.get('trail'), separators=(',', ':'))) if 'trail' in d else 0} B, "
              f"beam {len(states)} states {len(json.dumps(d.get('beam'), separators=(',', ':'))) if states else 0} B, "
              f"file {size} -> {len(text) + 1} B")


if __name__ == '__main__':
    main()
