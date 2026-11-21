"""Numbers for the missed-tech bounce and the shield break in Watch Lite (impactEffects.js), read from the
game. Watch Lite draws both with its own shapes (spikes, puffs, rays, sparks); only timing, size, colour,
position and motion come from here, never the game's textures or meshes.

Missed tech (ftCo_DownBound.c): entering DownBoundU / DownBoundD (183 / 191) spawns
  - effect 1030 (0x406, efasync.c efLib_Create_Attach_Pos(4)): EfCoData model 4 on the fighter's TopN,
    turned by the floor's slope (ftCo_800978D4): three rings of green spikes (two on joint 1, one on
    joint 2) that widen and flatten. Per ring: how many spikes go round (the texture's repeat x its
    spikes per tile), the texture's green; per frame: the base's radius, how far out and how high the
    spikes show (the meshes posed from RAM and rendered front on with their texture's alpha, measured),
    its KONST alpha (texture anim track 15) and whether it is hidden -> `crown`;
  - effect 1031 (0x407: generator 60, ftCo_800976A4): white puffs of dust sliding out along the floor
    (births per frame, where they start, speed, friction, rise, growth, life and fade, from RAM) ->
    `dust`; Fountain of Dreams' floor names a stage effect instead (mplib.c mpLib_80056B34).
Shield break: the fighter's ShieldBreakFly action script (its Pl*.dat action 286) spawns effect 1011 once
and effect 1001 (generator 12, the electric spark's particles 13-18) on action frames 1, 3 and 7, on TopN
plus a random +-7 on each axis (ftCo_8009F834, global HSD_Randf: not in the replay); ftCo_80098B20 adds
effect 1051 (generator 49: a small orb and specks). Per part, from RAM: sizes and alphas by age, counts,
spread, life and colour -> `shieldBreak` (`emit` is the action frames the bursts start on).

    app/venv/Scripts/python.exe -B tools/liteaudit/impact_effects/build.py --rec <record.py out dir> [--iso PATH] [--out PATH]

--rec holds record.py recordings of the samples in SAMPLES (missedtech-u, shieldbreak-falco: a shield
that ran out, no hitlag).
"""
import argparse
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / 'app/frontend/src/tracker/replays/data'
sys.path[0:0] = [str(REPO / 'tools/liteaudit/hit_effects'), str(REPO / 'tools/liteaudit/item_shapes'),
                 str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]
_spec = importlib.util.spec_from_file_location('hit_effects_build', REPO / 'tools/liteaudit/hit_effects/build.py')
HB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HB)

CROWN_MODEL, CROWN_JOINTS = 4, 3
EXTENT_HALF, EXTENT_PX, EXTENT_ALPHA = 60, 480, 0.15   # the square (world units) each ring is rendered in to measure it
DUST = 60
BURST = {'glow': 15, 'star': 13, 'sparkle': 14, 'sparks': 16, 'bolts': 17, 'zaps': 18}
FLARE, ORB, GLINT, SPECKS = 11, 53, 51, 50
SAMPLES = {'bounce': 'missedtech-u', 'shieldBreak': 'shieldbreak-falco'}
HEADER = ("// The missed-tech bounce and the shield break: numbers read from the game (EfCoData model 4, RAM in\n"
          "// playback Dolphin) by tools/liteaudit/impact_effects/build.py. Watch Lite draws its own shapes from\n"
          "// them; no game art is here. Do not edit by hand; see impactEffects.js.\n")


def r2(v):
    return round(v, 2)


def hexrgb(c):
    return '%02x%02x%02x' % tuple(int(v) for v in c[:3])


def subject(fr, m):
    return next(f for f in fr['fighters'] if f['port'] == m['subject']['port'])


def frames_from(m):
    return [(fr['match_frame'] - m['frame'], fr) for fr in m['frames'] if fr['match_frame'] >= m['frame']]


def world(p):
    if p.get('srt'):
        return [p['srt']['translate'][i] + p['pos'][i] for i in range(3)]
    return p['pos']


# ---------------------------------------------------------------- missed tech
def crown(d, m):
    """Two rings of spikes (model 4's joints 1 and 2). Per ring: how many spikes go round (the texture's
    repeat x its spikes per tile, summed over the joint's meshes), and per frame since the bounce: how
    far out and how high the spikes show (the
    joint's meshes posed from RAM and rendered front on with their texture's alpha x vertex alpha: the
    99th percentile of the area over EXTENT_ALPHA), and the alpha (KONST track 15; 0 once hidden)."""
    import hsdgeom
    import numpy as np
    from tracker.video import sprites
    tab = d.root['effCommonDataTable']
    base = tab + 8 + CROWN_MODEL * 0x14
    root, ma = d.p(base + 4), d.p(base + 0xC)
    alpha_track = {}
    for ji, mj in enumerate(d._iter_tree(ma, 0x00, 0x04)):
        mat = d.p(mj + 8)
        ta = d.p(mat + 8) if mat is not None else None
        aobj = d.p(ta + 8) if ta is not None else None
        fo = d.p(aobj + 8) if aobj is not None else None
        while fo is not None:
            t, keys = sprites._decode_fobj(d, fo)
            if t == 15 and keys:
                alpha_track[ji] = keys
            fo = d.p(fo)
    rings, green = {}, None
    for q in hsdgeom.model(d, root, with_hidden=True)[0]:
        t = q['mat']['tobjs'][0]
        tex = d.texture(t['img'], t['tlut']).astype(float)
        # spikes per tile: dips of the texture's top edge (the highest texel with alpha) across u
        a = tex[:, :, 3] > 60
        top = np.array([np.argmax(a[:, u]) if a[:, u].any() else tex.shape[0] for u in range(tex.shape[1])], float)
        top = np.convolve(np.r_[top[-2:], top, top[:2]], np.ones(3) / 3, 'valid')[1:-1]
        peaks = sum(1 for u in range(len(top)) if top[u] < top[u - 1] and top[u] <= top[(u + 1) % len(top)])
        lit = tex[tex[:, :, 3] > 60]
        green = green or hexrgb(lit[np.argmin(lit[:, 0] + lit[:, 2])])
        ring = rings.setdefault(q['joint'], {'n': 0, 'reach': [], 'height': [], 'a': []})
        ring['n'] += int(t['repeat'][0]) * peaks
    N, R = EXTENT_PX, EXTENT_HALF
    gobj, origin = None, None
    for k, fr in frames_from(m):
        effs = [e for e in fr['effects'] if len(e.get('joints') or []) == CROWN_JOINTS]
        if gobj is None:
            me = subject(fr, m)
            e = min(effs, key=lambda e: abs(e['joints'][0]['world'][3] - me['pos'][0]) + abs(e['joints'][0]['world'][7] - me['pos'][1]))
            gobj, w = e['gobj'], e['joints'][0]['world']
            origin = np.array([w[3], w[7], w[11]])
        e = next((x for x in effs if x['gobj'] == gobj), None)
        if e is None:
            break
        js, f = e['joints'], float(e['joints'][0]['anim_frame'])
        ov = {}
        for i, j in enumerate(js):
            W4 = np.eye(4)
            W4[:3, :4] = np.array(j['world']).reshape(3, 4)
            W4[:3, 3] -= origin
            ov[i] = {'world': W4}
        parts, _ = hsdgeom.model(d, root, override=ov, parent=np.eye(4), with_hidden=True)
        shown = False
        for jt, ring in rings.items():
            a = float(sprites._track_value(alpha_track[jt], f)) if jt in alpha_track else 1.0
            if int(js[jt]['flags'], 16) & 0x10:
                a = 0.0
            A = np.zeros((N, N))
            for q in parts:
                if q['joint'] != jt:
                    continue
                t = q['mat']['tobjs'][0]
                tex = d.texture(t['img'], t['tlut']).astype(np.float32)
                for tri in q['tris']:
                    P = np.array([v['pos'] for v in tri])
                    S = np.stack([(P[:, 0] + R) * N / (2 * R), (R - P[:, 1]) * N / (2 * R)], 1)
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
                    uv = bary @ np.array([v['uv'] for v in tri], np.float32)
                    va = bary @ np.array([v['clr'][3] for v in tri], np.float32) / 255
                    smp = hsdgeom._sample(tex, uv, t)
                    iy, ix = np.nonzero(inside)
                    A[mny + iy, mnx + ix] = np.maximum(A[mny + iy, mnx + ix], smp[:, 3] / 255 * va)
            ys, xs = np.nonzero(A > EXTENT_ALPHA)
            X, Y = (xs + 0.5) * 2 * R / N - R, R - (ys + 0.5) * 2 * R / N
            ring['reach'].append(r2(float(np.percentile(np.abs(X), 99))) if len(X) else 0)
            ring['height'].append(r2(float(np.percentile(Y, 99))) if len(Y) else 0)
            ring['a'].append(r2(max(0.0, a)))
            shown = shown or a > 0.004
        if not shown:
            for ring in rings.values():
                for key in ('reach', 'height', 'a'):
                    ring[key].pop()
            break
    return {'green': green, 'rings': [rings[j] for j in sorted(rings)]}


def dust(m):
    """Generator 60's puffs: how many are born on each frame, where (out from the fighter), their speed
    across the floor and up, friction and rise, size and growth, life, and alpha by age."""
    banks = {b['bank']: b for b in m['banks']}
    me0 = subject(next(fr for fr in m['frames'] if fr['match_frame'] == m['frame']), m)
    born, births, out, sp, vy, size0, grow, life, alpha = {}, defaultdict(int), [], [], [], [], [], 0, defaultdict(list)
    fric = grav = None
    for k, fr in frames_from(m):
        for p in fr['particles']:
            if p['bank'] != 0 or HB.gid(banks, p) != DUST:
                continue
            if p['addr'] not in born:
                born[p['addr']] = (k, p)
                births[k] += 1
                x, z = p['pos'][0] - me0['pos'][0], p['pos'][2]
                out.append(math.hypot(x, z))
                sp.append(math.hypot(p['vel'][0], p['vel'][2]))
                vy.append(p['vel'][1])
                size0.append(p['size'])
                life = max(life, p['life'] + 1)
                fric, grav = p['fric'], p['grav']
            k0, p0 = born[p['addr']]
            age = k - k0
            alpha[age].append(p['prim_shown'][3] / 255)
            if age == 1:
                grow.append(p['size'] - p0['size'])
    return {'births': [births[k] for k in range(max(births) + 1)], 'out': r2(statistics.median(out)),
            'speed': r2(statistics.median(sp)), 'rise': r2(statistics.median(vy)), 'friction': r2(fric), 'gravity': r2(grav),
            'size': r2(statistics.median(size0)), 'grow': r2(statistics.median(grow)), 'life': life,
            'alpha': [r2(statistics.median(alpha[a])) for a in range(life) if alpha[a]]}


# ---------------------------------------------------------------- shield break
def shield_break(m):
    """Per part of a burst (the first one), by age: size, alpha; counts; how far its sparks and bolts
    are from the burst's centre; colours (the particles' env colour, their prim being white). Plus the
    1011 flare and 1051's orb, glint and specks, and the action frames the bursts start on."""
    banks = {b['bank']: b for b in m['banks']}
    first_k, centre, emit, centres = None, None, [], []
    parts = defaultdict(lambda: defaultdict(list))
    for k, fr in frames_from(m):
        me = subject(fr, m)
        for p in fr['particles']:
            if p['bank'] != 0:
                continue
            g = HB.gid(banks, p)
            if g in BURST.values():
                # a burst's centre: its child generators' position (13-16) or its bolts' SRT (17, 18)
                c = p['srt']['translate'] if g in (17, 18) else (p.get('gen_pos') or p['pos'])
                if not any(math.dist(c, o) < 1 for o in centres):
                    centres.append(c)
                    emit.append(int(me['anim_frame']))
                    if centre is None:
                        first_k, centre = k, c
                if math.dist(c, centre) > 1:
                    continue
                pos = world(p)
                parts[g][k - first_k].append((p['size'], p['prim_shown'][3] / 255, math.hypot(pos[0] - centre[0], pos[1] - centre[1]),
                                              p['env_shown'], p['pose']))
            elif g in (FLARE, ORB, GLINT, SPECKS):
                # how far from where it was spawned (its SRT)
                parts[g][k].append((p['size'], p['prim_shown'][3] / 255, math.hypot(p['pos'][0], p['pos'][1]) if p.get('srt') else 0.0,
                                    p['env_shown'] if g != ORB else p['prim_shown'], p['pose']))

    def by_age(g, f):
        ages = sorted(parts[g])
        return [r2(f(parts[g][a])) if not isinstance(f(parts[g][a]), int) else f(parts[g][a]) for a in range(ages[-1] + 1) if parts[g].get(a)]

    def colour(g):
        return hexrgb(next(iter(parts[g].values()))[0][3])
    out = {'emit': sorted(set(emit))}
    for name, g in BURST.items():
        out[name] = {'size': by_age(g, lambda v: max(x[0] for x in v)), 'alpha': by_age(g, lambda v: max(x[1] for x in v)),
                     'n': max(len(v) for v in parts[g].values()), 'reach': by_age(g, lambda v: max(x[2] for x in v)), 'colour': colour(g)}
    for name, g in (('flare', FLARE), ('orb', ORB), ('glint', GLINT), ('specks', SPECKS)):
        out[name] = {'size': by_age(g, lambda v: max(x[0] for x in v)), 'alpha': by_age(g, lambda v: max(x[1] for x in v)),
                     'n': max(len(v) for v in parts[g].values()), 'colour': colour(g)}
    out['specks']['reach'] = by_age(SPECKS, lambda v: max(x[2] for x in v))
    # the texture frame each shows by age: the star steps flash, jagged ring, rays, scattered rays;
    # the flare a four-point star, then an eight-point one
    out['star']['pose'] = by_age(BURST['star'], lambda v: v[0][4])
    out['flare']['pose'] = by_age(FLARE, lambda v: v[0][4])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rec', type=Path, required=True)
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--out', type=Path, default=DATA / 'impactEffects.js')
    args = ap.parse_args()
    import isofiles
    from isofiles import dat
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = Path(str(known_vanilla_iso()))
    isofiles.open_iso(args.iso)
    d = dat('EfCoData.dat')
    rec = {k: json.loads((args.rec / f'{v}.json').read_text()) for k, v in SAMPLES.items()}
    for k, m in rec.items():
        if not m.get('ok'):
            raise SystemExit(f'{SAMPLES[k]}: recording failed ({m.get("error")})')
    out = {'crown': crown(d, rec['bounce']), 'dust': dust(rec['bounce']), 'shieldBreak': shield_break(rec['shieldBreak'])}
    args.out.write_text(HEADER + 'export default ' + HB.js_stringify(out) + ';\n', encoding='utf-8', newline='\n')
    print(f"{args.out.name}: {args.out.stat().st_size} bytes")


if __name__ == '__main__':
    main()
