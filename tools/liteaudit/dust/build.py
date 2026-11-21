"""Movement dust for Watch Lite (movementDust.js), from the game's own action scripts and effects.

When the game spawns it (melee decomp): a fighter's action scripts (Pl<XX>.dat) carry effect commands,
0x28 "Graphic Effect" (ftAction_80071028: bone, gfx id, offset, random range) and 0x37 "Sound and
Graphic Effect" (ftAction_80072E4C: gfx id on TopN; a floor material may swap it for a stage effect,
mpLib_80056AC4, on a few Fountain of Dreams / Pokemon Stadium / Icicle Mountain floors: not drawn). Both
go through ftCo_8009F834 to efAsync_Dispatch. The dust ids and what they spawn (efasync.c):
  dash        0x3FF  EfCoData model 5, turned about y by the facing (and about z by the floor's slope),
                     its particle track starting generator 9 (particles 7, 8)
  turn        0x401  generator 0x5A (particle 90) by the facing; 0x400 the same the other way (turnback)
  jump        0x402  generator 0x59 (particle 89) on the joint
  airjump     0x403  generator 0x5E (particle 94) on the joint: a ring that stays, grows and fades
  landing     0x404  EfCoData model 24 (turned by the floor's slope), particle track generator 10
  airlanding  0x407  generator 0x3C (particle 60)
  step        0x3FE  generator 0x107 (particles 264, 265) by the facing
Which states: every state of every vanilla fighter whose script has one of these commands, walked once
through its animation (commands()): dash starts, run turns and brakes, ground and double jumps,
landings, aerial and special-fall landings (wavedashes), walk and run steps, rolls, getup rolls, ledge
jumps and rolls, item swings and the rest that come with the same commands. A command on a bone other
than TopN (Ganondorf's side B) is left out; offsets on TopN are kept (forward along the facing, up);
random ranges are not (the centre). The runtime rule (movementDust.js, events_of here): a command runs
on the first frame of a state's run whose action frame (Slippi's) has reached its time; a run restarts
when the state changes or the action frame goes back. Checked on the samples: each recorded effect
appears on that frame (generator particles one frame later where the generator emits them so).

What they look like: shapes of Watch Lite's own, no game art in the data. What the game spawns is read
frame by frame in playback Dolphin (hit_effects/record.py, the samples in samples.json) around where the
fighter stood when the command ran (every puff stays where it spawned), and measured: each particle
(through its app SRT, its square, its texture's alpha and intensity) and each part of the two models
(posed by RAM, seen from the front, rendered with the material's colour toward the texture stage's by
the texture's blend track, tobj.c, and alpha by the same blend, HSD_FObjInterpretAnim's evaluation of
the tracks) becomes the ellipse with the same alpha mass, centre and spread, its colour (env toward prim
by the mean intensity), or a ring where it is hollow (the double jump's). Watch Lite paints a soft
ellipse (alpha x (1 - r^2)) or a thin ring per shape.

    app/venv/Scripts/python.exe -B tools/liteaudit/dust/build.py --rec <record.py out for samples.json> [--iso PATH] [--out PATH]

Writes app/frontend/src/tracker/replays/data/movementDust.js:
  kinds     ['dash', 'turn', ...]: the effects, in the order the schedules index them
  effects   {kind: {facing, colours: ['rrggbb'], frames: [[shape]] by frame since the command ran (0 = the
            frame the action frame reached the command's time)}}; shape [kind (0 soft ellipse, 1 ring), x,
            y, rx, ry, turn (degrees, 0..179), alpha, colours index, ring line width?] in world units
            around the spawn point (facing: the sample's; the painter mirrors for the other side)
  fighters  {common: {state: commands}, cid: {state: commands | []}}: per action state the commands most
            fighters share, then per internal fighter id where its own differ ([]: none); a command is
            time x 8 + kind index, or [time, kind index, forward, up] when it sits off TopN; a number in
            place of a list is a state of the same table with the same list
"""
import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / 'app/frontend/src/tracker/replays/data'
sys.path[0:0] = [str(REPO / 'tools/liteaudit/hit_effects'), str(REPO / 'tools/liteaudit/item_shapes'),
                 str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hfx = _module('hit_effects_build', REPO / 'tools/liteaudit/hit_effects/build.py')
js_round, js_stringify, hexcol = hfx.js_round, hfx.js_stringify, hfx.hexcol

def fobj_value(keys, frame):
    """A decoded animation track (tracker.video.sprites._decode_fobj keys, stream order) at `frame`, as
    HSD_FObjInterpretAnim plays it (fobj.c): each segment runs from one key to the next over the first
    key's wait, interpolated by the first key's op (CON holds, LIN, SPL0 / SPL / SLP Hermite), an SLP
    key only setting the next key's tangent. RAM-checked on the dash model's blend tracks (an eased
    0.6 -> 0 over frames 7-14, a linear one over 12-20); sprites._track_value takes the op from the
    segment's end key and gets both wrong."""
    if not keys:
        return 0.0
    real = [i for i, k in enumerate(keys) if k['interp'] != 5]
    wait = {i: (keys[real[n + 1]]['frame'] - keys[i]['frame']) if n + 1 < len(real) else math.inf
            for n, i in enumerate(real)}
    st = {'p0': 0.0, 'p1': 0.0, 'd0': 0.0, 'd1': 0.0, 'op': 0, 'opi': 0, 'i': 0, 'last': None}

    def load():
        while st['i'] < len(keys):
            k = keys[st['i']]
            st['i'] += 1
            st['opi'], st['op'] = st['op'], k['interp']
            op = st['op']
            if op in (1, 2):
                st['p0'], st['p1'] = st['p1'], k['value']
                if st['opi'] != 5:
                    st['d0'], st['d1'] = st['d1'], 0.0
            elif op == 3:
                st['p0'], st['d0'], st['p1'], st['d1'] = st['p1'], st['d1'], k['value'], 0.0
            elif op == 4:
                st['p0'], st['p1'], st['d0'], st['d1'] = st['p1'], k['value'], st['d1'], k['tan']
            elif op == 5:
                st['d0'], st['d1'] = st['d1'], k['tan']
                continue
            st['last'] = st['i'] - 1
            return True
        return False
    if not load():
        return keys[0]['value']
    t0, fterm = 0.0, wait[st['last']]
    if not load():
        return st['p1']
    while frame >= t0 + fterm:
        t0 += fterm
        fterm = wait[st['last']]
        if not load():
            return st['p1']
    time, op, p0, p1, d0, d1 = frame - t0, st['opi'], st['p0'], st['p1'], st['d0'], st['d1']
    if op == 1:
        return p0
    if op == 2:
        return p0 + (p1 - p0) / fterm * time if fterm else p1
    if op in (3, 4, 5):
        if not fterm:
            return p1
        inv = 1.0 / fterm
        fv1 = time * time
        fv2 = inv * inv * fv1 * time
        fv3 = 3.0 * fv1 * inv * inv
        fv4 = fv2 - fv1 * inv
        fv2 = 2.0 * fv2 * inv
        return d1 * fv4 + d0 * (time + (fv4 - fv1 * inv)) + p0 * (1.0 + (fv2 - fv3)) + p1 * (-fv2 + fv3)
    return p0


# the schedules' kinds (at most 8: a command packs as time x 8 + kind); turnback is turn the other way
KINDS = ['dash', 'turn', 'jump', 'airjump', 'landing', 'airlanding', 'step', 'turnback']
IDS = {0x3FF: 'dash', 0x401: 'turn', 0x400: 'turnback', 0x402: 'jump', 0x403: 'airjump', 0x404: 'landing',
       0x407: 'airlanding', 0x3FE: 'step'}
EFFECTS = {
    'dash': {'model': 5, 'joints': 7, 'gens': [7, 8]},
    'turn': {'gens': [90]},
    'jump': {'gens': [89]},
    'airjump': {'gens': [94]},
    'landing': {'model': 24, 'joints': 8, 'gens': [10]},
    'airlanding': {'gens': [60]},
    'step': {'gens': [264, 265]},
}
GRAPHIC, SOUND_GRAPHIC = 10, 55       # command codes 0x28 >> 2, 0xDC >> 2
BORN_WINDOW = 8                       # a particle of the effect is born this many frames after the command at most ...
BORN_NEAR = 25                        # ... and this close to where it spawned
MESH_HALF, MESH_PX = 18, 288          # the models are rendered in a square of this half size (world units), pixels across
MAX_FRAMES = 60
PRIM_ENV, TRAIL, DIRVEC, FLIP_S, FLIP_T = hfx.PRIM_ENV, hfx.TRAIL, hfx.DIRVEC, hfx.FLIP_S, hfx.FLIP_T
HEADER = ("// Movement dust: when each fighter's action scripts spawn it, and the shapes Watch Lite draws for\n"
          "// it, measured from what the game spawns (RAM, playback Dolphin), by tools/liteaudit/dust/build.py.\n"
          "// Do not edit by hand; see movementDust.js.\n")


def r1(v):
    return js_round(v, 1)


# ---------------------------------------------------------------- when: the action scripts
def commands(fd, action, end):
    """[(time, code, fields)] of an action's script over one pass of its animation (stage_bake.commands'
    walker), up to `end` or a Go To back to a command already walked: a run or walk script loops that way,
    its absolute waits meaning the animation's next loop, which Slippi shows as the action frame going back
    (movementDust.js then starts the state's commands over). A Go To into code not yet walked (Bowser's
    run jumps back into a block its dash shares) is followed."""
    from vault.echo.subactions import read_bits, to_signed
    from vault.echo.commands import COMMANDS
    at = action.script_offset
    if at is None:
        return []
    time, stack, loops, result, seen, walked = -1, [], [], [], set(), set()
    for _ in range(100000):
        if (at, time) in seen:
            break
        seen.add((at, time))
        walked.add(at)
        code = fd.dat.buf[32 + at] >> 2
        spec = COMMANDS[code]
        fields = {}
        for p in spec.params:
            v = read_bits(fd.dat.buf, (32 + at) * 8 + p.bit_offset, p.bits)
            fields[p.key] = to_signed(v, p.bits) if p.signed else v
        nxt = at + spec.size
        if code == 0:
            break
        if code == 1:
            time += fields['frame']
        elif code == 2:
            time = max(time, fields['frame'])
        elif code == 3:
            loops.append([nxt, fields['count']])
        elif code == 4:
            if not loops:
                break
            loops[-1][1] -= 1
            if loops[-1][1] > 0:
                nxt = loops[-1][0]
            else:
                loops.pop()
        elif code == 5:
            stack.append(nxt)
            nxt = fields['pointer']
        elif code == 6:
            if not stack:
                break
            nxt = stack.pop()
        elif code == 7:
            if fields['pointer'] in walked:
                break
            nxt = fields['pointer']
        elif code == 8:
            break
        else:
            result.append((max(0, time), code, fields))
        if time > end:
            break
        at = nxt
    return result


def schedules():
    """{cid: {state: [[t, kind index, forward, up, sign]...]}} from every vanilla fighter's scripts."""
    import fighterbones as fb
    out, skipped = {}, 0
    for code in fb.CODES:
        f = fb.fighter(code)
        table, seen = {}, {}
        for state, index in enumerate(f['indices']):
            if index < 0 or index >= len(f['fd'].actions):
                continue
            a = f['fd'].actions[index]
            try:
                end = fb.tracks(code, state)[0] if a.anim_size else 120
            except Exception:                          # noqa: BLE001 -- no animation to bound it
                end = 120
            cmds = commands(f['fd'], a, end)
            rows = []
            for t, op, h in cmds:
                if op == GRAPHIC and h['gfx_id'] in IDS:
                    if h['bone_id'] or h['use_common_bone_ids']:
                        skipped += 1
                        continue
                    kind = IDS[h['gfx_id']]
                    # offset.x/y/z are the command's first, second and third fields (ftAction_80071028),
                    # in TopN's frame: z is forward along the facing, y up, x toward the camera (dropped)
                    fwd, up = h['x'] / 256, h['y'] / 256
                elif op == SOUND_GRAPHIC and (h['graphic_id'] & 0xFFFF) in IDS:
                    kind = IDS[h['graphic_id'] & 0xFFFF]
                    fwd = up = 0.0
                else:
                    continue
                t = int(math.ceil(t - 1e-6))
                rows.append([t, KINDS.index(kind), r1(fwd), r1(up)] if fwd or up else t * 8 + KINDS.index(kind))
            if not rows:
                continue
            rows.sort(key=lambda r: r[0] if isinstance(r, list) else r >> 3)
            sig = json.dumps(rows)
            table[str(state)] = seen[sig] if sig in seen else rows
            seen.setdefault(sig, state)
        out[str(f['cid'])] = table
    return out, skipped


def compact(table):
    """The schedules as movementDust.js reads them: `common` holds each common state's (< 341) list most
    fighters share, each fighter only where it differs ([] where it has none); a number is a state of the
    same table with the same list."""
    from collections import Counter
    full = {cid: {s: t[str(v)] if isinstance(v, int) else v for s, v in t.items()} for cid, t in table.items()}

    def refs(t):
        out, seen = {}, {}
        for s in sorted(t, key=int):
            sig = json.dumps(t[s])
            out[s] = seen[sig] if sig in seen and t[s] else t[s]
            seen.setdefault(sig, int(s))
        return out
    common = {}
    for s in sorted({s for t in full.values() for s in t if int(s) < 341}, key=int):
        best, n = Counter(json.dumps(t[s]) for t in full.values() if s in t).most_common(1)[0]
        if n > 1:
            common[s] = json.loads(best)
    out = {'common': refs(common)}
    for cid, t in full.items():
        mine = {s: rows for s, rows in t.items() if common.get(s) != rows}
        mine.update({s: [] for s in common if s not in t})
        out[cid] = refs(mine)
    return out


def events_of(cid, rows, table):
    """[(row index, kind, sign, forward, up)] by the rule movementDust.js uses: a state's run starts when the
    state changes or its action frame goes back (re-entered, or its animation looped); each command fires
    once per run, on the first row whose action frame has reached its time."""
    out, fired, prev = [], set(), None
    sched = table.get(str(cid), {})
    for i, (st, age) in enumerate(rows):
        if prev is None or st != prev[0] or age < prev[1]:
            fired = set()
        cmds = sched.get(str(st), [])
        if isinstance(cmds, int):
            cmds = sched[str(cmds)]
        for j, c in enumerate(cmds):
            t, kind, fwd, up = c if isinstance(c, list) else (c >> 3, c & 7, 0.0, 0.0)
            if j not in fired and age >= t:
                fired.add(j)
                if prev is not None:                    # the first row's run started before the recording
                    out.append((i, KINDS[kind], fwd, up))
        prev = (st, age)
    return out


# ---------------------------------------------------------------- what: particles
def srt_matrix(srt):
    """The app SRT's 3 x 4 matrix (its mtx when the particle system has filled it, else from its SRT)."""
    m = srt.get('mmtx')
    if m and any(abs(v) > 1e-9 for v in m):
        return np.array(m, float).reshape(3, 4)
    rx, ry, rz = srt['rot'][:3]
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    R = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ \
        np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    M = np.zeros((3, 4))
    M[:, :3] = R * np.array(srt['scale'])
    M[:, 3] = srt['translate']
    return M


# ---------------------------------------------------------------- what: shapes of our own
# Watch Lite draws every puff as a shape of its own (movementDust.js), never the game's art: a particle's
# texture and a model part's rendered pixels are only measured here, for the ellipse with the same alpha
# mass, centre and spread (second moments), its colour, and whether it is hollow (a ring).
BLOB_R = 6 ** 0.5        # a soft disc of profile 1 - r^2 out to R spreads R / sqrt(6) along each axis ...
BLOB_MASS = 0.5          # ... and puts down this share of its peak alpha x its area
RING_INNER = 0.45        # a shape whose alpha within this many spreads of its centre is under ...
RING_HOLLOW = 0.55       # ... this share of its alpha further out is a ring
TEX_PX = 32              # textures are measured at most this many pixels across
MIN_SPREAD = 0.2         # no shape is thinner than this spread (world units)


def shape(A, I, xs, ys, px_area, prim, env, alpha=1.0):
    """[kind, x, y, rx, ry, turn, alpha, colour, width?] for an alpha map A (intensity I) whose pixels sit at
    world xs, ys, px_area world units each, at alpha x A: kind 0 a soft ellipse (profile 1 - r^2 out to
    rx, ry, peak alpha), 1 a ring (radii rx, ry, line width, alpha); colour 'rrggbb', env toward prim by
    the alpha-weighted intensity. None when it would barely show."""
    w = float(A.sum())
    mass = w * px_area * alpha
    if mass < 0.05:
        return None
    cx, cy = float((A * xs).sum() / w), float((A * ys).sum() / w)
    dx, dy = xs - cx, ys - cy
    cov = np.array([[(A * dx * dx).sum(), (A * dx * dy).sum()], [(A * dx * dy).sum(), (A * dy * dy).sum()]]) / w
    ev, V = np.linalg.eigh(cov)
    # (a part lying flat, the landing's ground disc, is seen edge-on: kept as a thin streak)
    s1, s2 = float(np.sqrt(max(ev[1], MIN_SPREAD ** 2))), float(np.sqrt(max(ev[0], MIN_SPREAD ** 2)))
    e1 = V[:, 1]
    turn = math.degrees(math.atan2(e1[1], e1[0]))
    u, v = (dx * e1[0] + dy * e1[1]) / s1, (dy * e1[0] - dx * e1[1]) / s2
    rho = np.sqrt(u * u + v * v)
    lit = float((A * I).sum() / w)
    colour = hexcol([e + (p - e) * lit for p, e in zip(prim, env)], False)[1:]
    inner, around = A[rho < RING_INNER], A[(rho >= RING_INNER) & (rho < 2.5)]
    if inner.size and around.size and inner.mean() < RING_HOLLOW * around.mean():
        mean = float((A * rho).sum() / w)
        rx, ry = s1 * mean, s2 * mean
        width = max(0.3, 2 * float(np.sqrt((A * (rho - mean) ** 2).sum() / w)) * (s1 + s2) / 2)
        return [1, cx, cy, rx, ry, turn, min(1.0, mass / (math.pi * (rx + ry) * width)), colour, width]
    rx, ry = BLOB_R * s1, BLOB_R * s2
    return [0, cx, cy, rx, ry, turn, min(1.0, mass / (BLOB_MASS * math.pi * rx * ry)), colour]


def packed(sh, palette):
    """A shape as stored: rounded, its colour an index into the effect's palette, its turn mod 180."""
    if sh[7] not in palette:
        palette.append(sh[7])
    out = [sh[0], r1(sh[1]), r1(sh[2]), r1(sh[3]), r1(sh[4]), round(sh[5]) % 180, js_round(sh[6], 2), palette.index(sh[7])]
    return out + [r1(sh[8])] if sh[0] == 1 else out


class TextureStats:
    """A particle texture (hit_effects' Textures as the image source), reduced to TEX_PX across: its alpha,
    intensity and pixel coordinates in its square (-1..1, y up). Measured, never shipped."""
    def __init__(self, tex):
        self.tex, self.cache = tex, {}

    def __call__(self, texg, pose, kind):
        key = (texg, pose, kind & (hfx.MIRROR_S | hfx.MIRROR_T | FLIP_S | FLIP_T))
        if key not in self.cache:
            img = self.tex.image(texg, pose, bool(kind & hfx.MIRROR_S), bool(kind & hfx.MIRROR_T), bool(kind & FLIP_S),
                                 bool(kind & FLIP_T))
            h, w = img.shape[:2]
            f = max(1, max(h, w) // TEX_PX)
            img = img[:h // f * f, :w // f * f].reshape(h // f, f, w // f, f, 4).mean((1, 3))
            h, w = img.shape[:2]
            ys, xs = np.mgrid[0:h, 0:w]
            self.cache[key] = (img[:, :, 3] / 255.0, img[:, :, :3].mean(2) / 255.0,
                               2 * (xs + 0.5) / w - 1, 1 - 2 * (ys + 0.5) / h)
        return self.cache[key]


def particles(m, spec, ev, frames, stats):
    """Per frame since the command: the kind's particles around the spawn point, each as shape()."""
    banks = {b['bank']: b for b in m['banks']}
    gens = set(spec['gens'])
    alive, rows = {}, []
    k0, cx, cy = ev['k'], ev['x'], ev['y']
    for fr in frames:
        k = fr['match_frame'] - m['frame'] - k0
        if k < 0:
            continue
        if k >= MAX_FRAMES:
            break
        row = []
        for p in fr['particles']:
            if p['bank'] != 0 or hfx.gid(banks, p) not in gens:
                continue
            M = srt_matrix(p['srt']) if p.get('srt') else None
            pos = np.array(p['pos'], float)
            world = M[:, :3] @ pos + M[:, 3] if M is not None else pos
            a = alive.get(p['addr'])
            if a is None or p['life'] > a['life']:
                a = alive[p['addr']] = {'born': k, 'keep': k <= BORN_WINDOW and math.hypot(world[0] - cx, world[1] - cy) <= BORN_NEAR}
            a['life'] = p['life']
            if not a['keep']:
                continue
            kind = int(p['kind'], 16)
            half = p['size'] * (float(np.linalg.norm(M[:, 0])) if M is not None else 1.0)
            prim = p['prim_shown']
            if half <= 0.02 or prim[3] < 4:
                continue
            vel = np.array(p['vel'], float)
            if M is not None:
                vel = M[:, :3] @ vel
            if kind & (TRAIL | DIRVEC):
                ang = math.atan2(-vel[0], vel[1]) + (p['rot'] if kind & DIRVEC else 0.0)
            else:
                ang = p['rot']
            env = p['env_shown'] if kind & PRIM_ENV else [0, 0, 0, 0]
            # the particle's square (psdisp.c): half size, turned; a Trail stretches back to where it was
            ox, oy, hw, hh, fade = world[0] - cx, world[1] - cy, half, half, 1.0
            if kind & TRAIL:
                tx, ty = -vel[0], -vel[1]
                ox, oy, hh, fade = ox + tx / 2, oy + ty / 2, half + math.hypot(tx, ty) / 2, (1 + p['trail']) / 2
            A, I, lx, ly = stats(p['texg'], p['pose'], kind)
            c, sn = math.cos(ang), math.sin(ang)
            xs, ys = ox + c * hw * lx - sn * hh * ly, oy + sn * hw * lx + c * hh * ly
            sh = shape(A, I, xs, ys, 4 * hw * hh / A.size, prim[:3], env[:3], prim[3] / 255 * fade)
            if sh:
                row.append(sh)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- what: the models, measured
def mesh(d, m, spec, ev, frames):
    """The model's parts per frame since the command, posed by RAM and seen from the front, each part's
    rendered alpha and intensity measured as shape() around the spawn point."""
    import hsdgeom
    import itemmodel
    from tracker.video import sprites
    # the material animation (texture flipbook in itemmodel.matanim_state, blend, TEV colours) as HSD plays it
    sprites._track_value = lambda keys, frame, default=0.0: fobj_value(keys, frame) if keys else default
    tab = d.root['effCommonDataTable']
    base = tab + 8 + spec['model'] * 0x14
    root, ma = d.p(base + 4), d.p(base + 0xC)
    tracks = {}                                       # joint index -> {texture anim track type: keys}
    for ji, mj in enumerate(d._iter_tree(ma, 0x00, 0x04)):
        mat = d.p(mj + 8)
        ta = d.p(mat + 8) if mat is not None else None
        aobj = d.p(ta + 8) if ta is not None else None
        fo = d.p(aobj + 8) if aobj is not None else None
        while fo is not None:
            t, keys = sprites._decode_fobj(d, fo)
            if keys:
                tracks.setdefault(ji, {})[t] = keys
            fo = d.p(fo)

    def track(j, t, f, default):
        keys = tracks.get(j, {}).get(t)
        return float(sprites._track_value(keys, f)) if keys else default

    N, R = MESH_PX, MESH_HALF
    gy, gx = np.mgrid[0:N, 0:N]
    wx, wy = (gx + 0.5) * 2 * R / N - R, R - (gy + 0.5) * 2 * R / N
    px_area = (2 * R / N) ** 2
    origin = np.array([ev['x'], ev['y'], 0.0])
    gobj, out = None, []
    for fr in frames:
        k = fr['match_frame'] - m['frame'] - ev['k']
        if k < 0:
            continue
        effs = [e for e in fr['effects'] if len(e.get('joints') or []) == spec['joints']]
        if gobj is None:
            near = [e for e in effs if math.hypot(e['joints'][0]['world'][3] - origin[0], e['joints'][0]['world'][7] - origin[1]) < 10]
            if not near:
                out.append([])
                if k > 3:
                    raise SystemExit(f"{m['id']}: model {spec['model']} never spawned near the fighter")
                continue
            gobj = near[0]['gobj']
        e = next((x for x in effs if x['gobj'] == gobj), None)
        if e is None or k >= MAX_FRAMES:
            break
        js = e['joints']
        f = float(js[0]['anim_frame'] or 0.0)
        ov = {}
        for i, j in enumerate(js):
            W4 = np.eye(4)
            W4[:3, :4] = np.array(j['world']).reshape(3, 4)
            W4[:3, 3] -= origin
            ov[i] = {'world': W4}
        parts, _ = hsdgeom.model(d, root, override=ov, parent=np.eye(4), with_hidden=True)
        parts = itemmodel.apply_matanim(parts, itemmodel.matanim_state(d, ma, f))
        hidden = {i for i, j in enumerate(js) if int(j['flags'], 16) & 0x10}
        row = []
        for q in parts:
            jt = q['joint']
            if jt in hidden or not q['mat']['tobjs']:
                continue
            t = q['mat']['tobjs'][0]
            blend = track(jt, 9, f, t['blending'])
            mat_a = q['mat']['alpha']
            if max(blend, mat_a) <= 0.004:
                continue
            # the texture's colour, or its TEV stage's when it has one (tobj.c MakeColorGenTExp: TEV0 x (1 -
            # tex) + KONST x tex), as tex_env + (tex_prim - tex_env) x the texture's intensity
            tev = d.p(t['off'] + 0x58)
            active = d.u(tev + 28) if tev is not None else 0
            if active & 0x40000000:
                assert [d.b(tev + 8 + i) for i in range(4)] == [0x85, 0x80, 8, 15], (spec['model'], jt)
                tex_prim = [track(jt, 12 + c, f, d.b(tev + 16 + c) / 255) * 255 for c in range(3)]
                tex_env = [track(jt, 16 + c, f, d.b(tev + 20 + c) / 255) * 255 for c in range(3)]
            else:
                tex_prim, tex_env = [255] * 3, [0] * 3
            if active & 0x80000000:                    # its alpha: the texture's (GX_CA_TEXA in d)
                assert [d.b(tev + 12 + i) for i in range(4)] == [7, 7, 7, 4], (spec['model'], jt)
            # TEX_COLORMAP_BLEND / TEX_ALPHAMAP_BLEND (TObjMakeTExp): the material's constant colour and
            # alpha toward the texture stage's by the blend
            assert t['colormap'] == 3 and t['alphamap'] == 2, (spec['model'], jt, t['colormap'], t['alphamap'])
            dif = q['mat']['dif']
            env = [dif[c] * (1 - blend) + tex_env[c] * blend for c in range(3)]
            prim = [dif[c] * (1 - blend) + tex_prim[c] * blend for c in range(3)]
            texture = d.texture(t['img'], t['tlut']).astype(np.float32)
            if d.image_at(t['img']).format in (0, 1):
                texture = texture.copy()
                texture[:, :, 3] = texture[:, :, 0]          # GX I4 / I8: the intensity is the alpha too
            A, P = np.zeros((N, N)), np.zeros((N, N))
            for tri in q['tris']:
                Pv = np.array([v['pos'] for v in tri])
                S = np.stack([(Pv[:, 0] + R) * N / (2 * R), (R - Pv[:, 1]) * N / (2 * R)], 1)
                (x0, y0), (x1, y1), (x2, y2) = S
                area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
                if abs(area) < 1e-9:
                    continue
                mnx, mxx = max(int(S[:, 0].min()), 0), min(int(S[:, 0].max()) + 1, N)
                mny, mxy = max(int(S[:, 1].min()), 0), min(int(S[:, 1].max()) + 1, N)
                if mnx >= mxx or mny >= mxy:
                    continue
                ys, xs = np.mgrid[mny:mxy, mnx:mxx] + 0.5
                w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
                w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
                inside = (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0)
                if not inside.any():
                    continue
                bary = np.stack([w0[inside], w1[inside], 1 - w0[inside] - w1[inside]], 1)
                smp = hsdgeom._sample(texture, bary @ np.array([v['uv'] for v in tri], np.float32), t)
                # TEX_ALPHAMAP_BLEND: material alpha toward the texture's by the blend; blended over (XLU)
                a = np.clip(mat_a * (1 - blend) + smp[:, 3] / 255 * blend, 0, 1)
                iy, ix = np.nonzero(inside)
                py, px = mny + iy, mnx + ix
                P[py, px] = P[py, px] * (1 - a) + smp[:, :3].mean(1) / 255 * a
                A[py, px] = A[py, px] * (1 - a) + a
            I = np.where(A > 1e-4, np.clip(P / np.maximum(A, 1e-4), 0, 1), 0)
            sh = shape(A, I, wx, wy, px_area, prim, env)
            if sh:
                row.append(sh)
        out.append(row)
    return out


# ---------------------------------------------------------------- the samples
def sample_event(m, kind, table):
    """The sample's command: the first `kind` event of its subject from the recording's start (RAM state
    and action frame, events_of), with where the fighter stood and faced."""
    sub = m['subject']['port']
    frames = m['frames']
    mes = [next(f for f in fr['fighters'] if f['port'] == sub) for fr in frames]
    cid = mes[0]['kind']
    evs = [e for e in events_of(cid, [(me['state'], me['anim_frame']) for me in mes], table) if e[1] == kind]
    if not evs:
        raise SystemExit(f"{m['id']}: no {kind} command in the recording")
    i, _, fwd, up = evs[0]
    me = mes[i]
    facing = 1 if me['facing'] >= 0 else -1
    return {'k': frames[i]['match_frame'] - m['frame'], 'x': me['pos'][0] + facing * fwd, 'y': me['pos'][1] + up,
            'facing': facing, 'cid': cid, 'state': me['state']}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rec', type=Path, required=True, help='record.py output for samples.json')
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--out', type=Path, default=DATA / 'movementDust.js')
    args = ap.parse_args()
    import isofiles
    from isofiles import dat
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = Path(str(known_vanilla_iso()))
    isofiles.open_iso(args.iso)
    d = dat('EfCoData.dat')
    _, tex_bank = hfx.ptcltex.banks(d, 'effCommonDataTable')
    stats = TextureStats(hfx.Textures(d, tex_bank))
    table, skipped = schedules()
    samples = json.loads((HERE / 'samples.json').read_text())
    effects = {}
    for s in samples:
        m = json.loads((args.rec / f"{s['id']}.json").read_text())
        if not m.get('ok'):
            raise SystemExit(f"{s['id']}: recording failed ({m.get('error')})")
        spec = EFFECTS[s['kind']]
        ev = sample_event(m, s['kind'], table)
        rows = particles(m, spec, ev, m['frames'], stats)
        parts = mesh(d, m, spec, ev, m['frames']) if spec.get('model') is not None else []
        n = max(len(rows), len(parts))
        # a frame's model parts first, its particles over them
        frames = [(parts[k] if k < len(parts) else []) + (rows[k] if k < len(rows) else []) for k in range(n)]
        while frames and not frames[-1]:
            frames.pop()
        palette = []
        frames = [[packed(sh, palette) for sh in row] for row in frames]
        effects[s['kind']] = {'facing': ev['facing'], 'colours': palette, 'frames': frames}
        first = next((k for k, r in enumerate(frames) if r), None)
        print(f"{s['kind']}: sample {s['id']} (cid {ev['cid']}, state {ev['state']}, command at k={ev['k']}): shapes "
              f"from frame {first} for {len(frames)} frames, {sum(map(len, frames))} in all "
              f"({sum(1 for r in frames for x in r if x[0] == 1)} rings)")
    missing = [k for k in KINDS if k not in effects and k != 'turnback']
    if missing:
        raise SystemExit(f'no sample for {missing}')
    fighters = compact(table)
    out = {'kinds': KINDS, 'effects': effects, 'fighters': fighters}
    args.out.write_text(HEADER + 'export default ' + js_stringify(out) + ';\n', encoding='utf-8', newline='\n')
    n = sum(len(v) for v in table.values())
    print(f"{args.out.name}: {n} fighter states ({skipped} commands on other bones left out), schedule "
          f"{len(js_stringify(fighters))} B, effects {len(js_stringify(effects))} B, file {args.out.stat().st_size} B")


if __name__ == '__main__':
    main()
