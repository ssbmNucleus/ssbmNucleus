"""Hit effects for Watch Lite (hitSparks.js), from what the game itself draws when a hit lands.

Which effect a hit spawns is the game's rule (ftcoll.c ftColl_8007A06C, table ftColl_803C0CAC by the
hitbox element; ftColl_80078538 for normal hits; efasync.c efAsync_Dispatch):
  normal   0x3E8: EfCoData model 10 (7 of 8; model 9 otherwise), scaled 0.3 + 0.04 x damage in
           [0.3, 1.5]; its particle track (anim type 40, value bank | id << 6) starts generators
           2 (particles 0, 1), 306 and 307
  strong   0x3F3 instead when the knockback is >= 180 (PlCo ftCommonData +0x3F0): generator 11
  electric 0x3E9: generator 12 (particles 13-19)       fire  0x3EA: generator 20 (particles 21-24)
  slash    0x3EC: model 8, turned by a random angle: generator 267 (particles 268-270) and two
           mesh crescents (joints 2, 3) that blink on alternate frames
  dark     0x416: generator 406 (particles 407-411)
  ice      0x3ED: generators 80 (particles 81-83) and 84, turned by the victim's facing
  shield   a hit on a shield, 1052 (0x41C): generator 93 at the contact point on the bubble
The particles are the game's own: the HSD particle system runs a command list per particle, so
their positions, sizes, turns, colours and texture poses are read from RAM frame by frame
(record.py, playback Dolphin, the hits in samples.json) rather than re-simulated. Each particle is
a camera-facing square of half size `size` (times its app SRT's scale), turned by `rotate`, or
along its velocity for DirVec / Trail (a Trail stretches back to pos - vel), coloured
env x (1 - tex) + prim x tex with alpha prim.a x tex alpha (PrimEnv; prim x tex otherwise) and
blended by kind bits 22-23: 0 alpha, 1 additive (psdisp.c, psdisptev.c). The hit effects draw
EfCoData.dat's own particle textures (ptcltex.py), reduced to radial glow profiles and nested outlines
of a few alpha and light levels (outlines, never pixels); shield hits and techs keep Watch Lite's own
drawing of each texture (sparkArt.js), so theirs are written as ids only.

    app/venv/Scripts/python.exe -B tools/liteaudit/hit_effects/build.py --rec <record.py out dir> [--iso PATH] [--out PATH]

Writes app/frontend/src/tracker/replays/data/hitEffects.js:
  textures  [[group, pose, flags, regions?]] by index: the particle texture each particle draws, by its
            group and pose in EfCoData.dat's particle texture bank (flags 1/2 mirror-wrapped s/t, 4/8 flipped
            s/t), and, for those the hit effects draw, the texture traced as two maps, alpha A and light I x
            A (intensity 0..1 x alpha):
            [2, [r, A, light, ...]] their glows: radial profiles by distance from the centre (0..141
            units to the corners), the values every direction shares at that distance;
            [0, A, under, light, dark, rings] what stands out of the alpha's glow, as nested outlines
            (alpha above the glow >= t): the alpha it brings its pixels to and the alpha it is drawn
            over (fitted to the pixels it ends up showing), and the light I x A and dark (1 - I) x A
            it adds there;
            [1, light, rings] the light's own nested outlines and the light each adds, only where the
            alpha's outlines miss it;
            rings are closed outlines in the particle's square (-100..100 = -1..1 of the half size,
            y up), filled even-odd, each [x0, y0, dx1, dy1, ...] (every point after the first as a
            step from the one before)
  effects   {kind: {scaled?: 1, colours: [[prim 'rrggbbaa', env 'rrggbb']], frames: [[particle]] by
            frame since the hit (0 = the hit frame)}};
            particle [texture, x, y, half size, turn (degrees, CCW), colours index, additive (0/1),
            tail?] in world units around the contact point (effect
            units for `scaled`), tail = [dx, dy, alpha] back to where a Trail particle was a frame ago;
            `facing` (ice): the sample victim's facing, the effect being mirrored with the victim's
  slash     [[outer ring, core ring, outer light, core light] per visible crescent] by frame since the
            hit, effect units: the slash model's two crescents (EfCoData model 8), drawn additively, the
            core's light on top of the outer's
  shieldStun {strips, frames: [[bands, scribble]] by frame since the shield was hit} (EfCoData model
            13): the torn bubble is cut into `strips` horizontal strips; each band [middle, half height,
            reach] of them (bubble radii, up from the bubble's centre) is stretched sideways up to `reach`
            past the rim, with a white scribble over it when `scribble`
  tech      {glow: [[blend, KONST, TEV0, half size] or 0] by frame since the tech, rings: {base, lobes,
            frames}, wall: [toward the wall, up], ceil: up}: a tech's glow and rings as numbers (see
            tech_effect); where a wall or ceiling tech's effect sits from the fighter. Its rays are
            effects.tech (particles, as the hit effects)
  shake     {mul, add, patterns: [air, ground, electric]}: the victim's hitlag shake, mul x hitlag
            + add frames stepping through [dx, dy] offsets (PlCo.dat)
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
sys.path[0:0] = [str(HERE), str(REPO / 'tools/liteaudit/item_shapes'), str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]
import cv2                                          # noqa: E402
import ptcltex                                      # noqa: E402

_spec = importlib.util.spec_from_file_location('item_shapes_build', REPO / 'tools/liteaudit/item_shapes/build.py')
_isb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_isb)
js_round, js_stringify = _isb.js_round, _isb.js_stringify

EFFECTS = {
    'normal': {'gens': [0, 1, 306, 307], 'scaled': True},
    'strong': {'gens': [11]},
    'electric': {'gens': [13, 14, 15, 16, 17, 18, 19]},
    'fire': {'gens': [21, 22, 23, 24]},
    'slash': {'gens': [268, 269, 270]},
    'dark': {'gens': [407, 408, 409, 410, 411]},
    'ice': {'gens': [81, 82, 83, 84], 'faces': True},
    'shield': {'gens': [93], 'traced': False},     # Watch Lite's own drawing (sparkArt.js)
}
LAST_K = 24                   # frames after the hit that record.py keeps (--post)
BORN_NEAR = 30                # a particle of the effect is born this close to the contact point
EFFECT_SCALE_MAX = 1.5        # the largest a scaled (normal) effect is drawn: ftColl_80078538
GLOW_RINGS, GLOW_RMAX = 40, math.sqrt(2)       # a texture's glow, by distance from its centre (to the corners) ...
GLOW_PERCENTILE = 20                          # ... the alpha this share of each ring stays under ...
GLOW_MIN = 0.03                               # ... when it shows at all
ALPHA_LEVELS = (0.06, 0.2, 0.4, 0.65, 0.85)   # what stands out of the glow, nested outlines of alpha >= t
LIGHT_WHEN, LIGHT_GAIN = 0.015, 0.25          # the light gets its own outlines when they bring it this much closer
SIMPLIFY = 0.012                              # outline tolerance, of the texture's size
MIN_REGION = 0.0015                           # smallest traced shape, of the texture's area
SHOWN_PPU = 6                      # pixels per world unit a spark is traced for (Watch Lite's closest framing)
PRIM_ENV, MIRROR_S, MIRROR_T, FLIP_S, FLIP_T, TRAIL, DIRVEC = 0x80, 0x20, 0x40, 1 << 18, 1 << 19, 1 << 20, 1 << 21
HEADER = ("// Hit effects read from the game: the particles each hit spawns (RAM, playback Dolphin) and\n"
          "// EfCoData.dat's textures and slash model, traced, by tools/liteaudit/hit_effects/build.py. Do not\n"
          "// edit by hand; see hitSparks.js.\n")


def r1(v):
    return js_round(v, 1)


def r3(v):
    return js_round(v, 3)


def r2(v):
    return js_round(v, 2)


def gid(banks, p):
    """The particle's command list as an index into its bank's table (the generator / particle id)."""
    cl = int(p['cmdlist'], 16)
    best = None
    for i, c in enumerate(banks.get(p['bank'], {}).get('cmds', [])):
        c = int(c, 16)
        if c and 0 <= cl - c - 0x3C < 0x400 and (best is None or cl - c < best[1]):
            best = (i, cl - c)
    return best[0] if best else None


def profile_points(r, a, l, tol=0.01):
    """The few points of a radial profile (alpha a and light l by distance r) that keep both within
    tol when joined by straight lines (greedy, worst point first)."""
    keep = [0, len(r) - 1]
    while True:
        ks = sorted(keep)
        err = np.maximum(np.abs(np.interp(r, r[ks], a[ks]) - a), np.abs(np.interp(r, r[ks], l[ks]) - l))
        worst = int(err.argmax())
        if err[worst] <= tol or worst in keep:
            return ks
        keep.append(worst)


# ---------------------------------------------------------------- textures
class Textures:
    def __init__(self, d, tex_bank):
        self.d, self.bank = d, tex_bank
        self.keys, self.largest, self.groups = {}, {}, {}

    def index(self, texg, pose, kind, half, traced):
        """The texture's index; `half` (world units) is how large this particle draws it, `traced` whether
        its effect is drawn with the game's texture (the hit effects) or with Watch Lite's own drawing
        (shield hits, techs: sparkArt.js)."""
        key = (texg, pose, bool(kind & MIRROR_S), bool(kind & MIRROR_T), bool(kind & FLIP_S), bool(kind & FLIP_T))
        if key not in self.keys:
            self.keys[key] = len(self.keys)
        if traced:
            self.largest[key] = max(self.largest.get(key, 0.0), half)
        return self.keys[key]

    def listed(self):
        """Every texture in index order: [group, pose, flags] (1/2 mirror-wrapped s/t, 4/8 flipped s/t), plus
        its traced regions when a hit effect draws it, each only as finely as its largest use can show."""
        out = []
        for key in sorted(self.keys, key=self.keys.get):
            texg, pose, ms, mt, fs, ft = key
            row = [texg, pose, ms * 1 | mt * 2 | fs * 4 | ft * 8]
            if key in self.largest:
                row.append(self.trace(*key, half=self.largest[key])['regions'])
            out.append(row)
        return out

    def image(self, texg, pose, ms, mt, fs, ft):
        if texg not in self.groups:
            self.groups[texg] = ptcltex.group(self.d, self.bank, texg)
        img = self.groups[texg]['poses'][pose].copy()
        if fs:
            img = img[:, ::-1]
        if ft:
            img = img[::-1]
        # GX mirror wrap with the texture matrix scaled by 2 (psdisp.c): s 0..2 shows the image, then its
        # mirror; t is also moved by 1, so t 1..3 shows the mirror first, then the image. Row 0 is the
        # top of the square (the corner texture coordinates at 0x8040C340, tex_base 0)
        if ms:
            img = np.concatenate([img, img[:, ::-1]], 1)
        if mt:
            img = np.concatenate([img[::-1], img], 0)
        return img

    def trace(self, texg, pose, ms, mt, fs, ft, half=20.0):
        """The texture as two maps the painter fills in single colours: its alpha A and its light I x A
        (the colour env x (1 - I) + prim x I over alpha A is min(prim, env) over A, plus (prim - min) x
        I x A and (env - min) x (1 - I) x A of added light, psdisptev.c). Each map is its glow (a radial
        profile: the value every direction shares at each distance from the centre) and what stands out
        of it as nested outlines (value above the glow >= t for each t in ALPHA_LEVELS, each inside the
        one before) with the mean values of the pixels up to the next level. The alpha's outlines carry
        the light's means too; the light gets outlines of its own only where those means miss it (where
        the texture's intensity does not follow its alpha)."""
        img = self.image(texg, pose, ms, mt, fs, ft)
        h, w = img.shape[:2]
        up = max(1, 256 // max(w, h))                     # trace smooth outlines from a bilinear upsample
        A = cv2.resize(img[:, :, 3] / 255.0, (w * up, h * up), interpolation=cv2.INTER_LINEAR)
        I = cv2.resize(img[:, :, :3].mean(2) / 255.0, (w * up, h * up), interpolation=cv2.INTER_LINEAR)
        return trace_maps(A, I, half)


def trace_maps(A, I, half, simplify=SIMPLIFY, min_region=MIN_REGION):
    """Trace an alpha map A and an intensity map I (0..1, at tracing resolution) as Textures.trace
    describes; `half` (world units) is the largest half size they are drawn at."""
    H, W = A.shape
    # outline tolerance and smallest shape: half a pixel (one pixel squared) at SHOWN_PPU pixels per
    # world unit on the largest square this texture is drawn in, never finer than simplify / min_region
    px = max(W, H) / (2 * max(half, 0.1) * SHOWN_PPU)
    tol = max(simplify * max(W, H), 0.5 * px)
    smallest = max(min_region * W * H, px * px)

    def rings_of(mask):
        cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        rings = []
        for c in cs:
            if abs(cv2.contourArea(c)) < smallest:
                continue
            c = cv2.approxPolyDP(c, tol, True)[:, 0, :]
            if len(c) < 3:
                continue
            # hundredths of the half size, as integers, each point after the first as the step
            # from the one before: [x0, y0, dx1, dy1, ...] (short numbers)
            pts = [(round(100 * (2 * (x + 0.5) / W - 1)), round(100 * (1 - 2 * (y + 0.5) / H))) for x, y in c]
            flat = [*pts[0]]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                flat += [bx - ax, by - ay]
            rings.append(flat)
        return rings

    def raster(rings):
        # the outlines as the painter fills them (even-odd)
        m = np.zeros((H, W), np.uint8)
        for flat in rings:
            pts = [(flat[0], flat[1])]
            for i in range(2, len(flat), 2):
                pts.append((pts[-1][0] + flat[i], pts[-1][1] + flat[i + 1]))
            one = np.zeros((H, W), np.uint8)
            cv2.fillPoly(one, [np.array([((u / 100 + 1) / 2 * W - 0.5, (1 - v / 100) / 2 * H - 0.5) for u, v in pts],
                                        np.float32).round().astype(np.int32)], 1)
            m ^= one
        return m.astype(bool)

    yy, xx = np.mgrid[0:H, 0:W]
    R = np.hypot(2 * (xx + 0.5) / W - 1, 2 * (yy + 0.5) / H - 1)
    L = I * A
    # the glow: the alpha every direction shares at each distance from the centre (a low percentile
    # of each ring of pixels), drawn as a radial gradient; the outlines then trace only what stands
    # out of it (rays, flakes, puffs)
    ring = np.minimum((R / GLOW_RMAX * GLOW_RINGS).astype(int), GLOW_RINGS - 1).ravel()
    r_mid = (np.arange(GLOW_RINGS) + 0.5) / GLOW_RINGS * GLOW_RMAX
    ga = np.array([np.percentile(A.ravel()[ring == i], GLOW_PERCENTILE) if (ring == i).any() else 0.0
                   for i in range(GLOW_RINGS)])
    glow = ga.max() >= GLOW_MIN
    GA = np.interp(R, r_mid, ga) if glow else np.zeros_like(A)
    # what stands out of the glow: nested outlines of alpha above the glow >= t, each filled with one
    # alpha over what is drawn under it; that alpha is fitted (least squares) to the pixels the
    # outline ends up showing (inside it, outside the next), as the painter builds the alpha up
    res = A - GA
    masks, rings_by = [], []
    for t in ALPHA_LEVELS:
        rings = rings_of(res >= t) if (res >= t).any() else []
        if rings:
            masks.append(raster(rings))
            rings_by.append(rings)
    drawn = GA.copy()
    alpha_levels = []
    for j, m in enumerate(masks):
        band = m & ~masks[j + 1] if j + 1 < len(masks) else m
        if band.sum() < 1:
            band = m
        q, r = 1 - drawn[band], 1 - A[band]
        x = float(np.clip(1 - (q * r).sum() / max((q * q).sum(), 1e-9), 0, 1))
        want = float(A[band].mean())
        # stored as the band's alpha and the alpha it is drawn over (the painter scales both by the
        # particle's alpha): x = 1 - (1 - want) / (1 - under)
        under = 1 - (1 - want) / (1 - x) if x < 0.999 else want
        alpha_levels.append((band, m, want, under))
        drawn[m] = drawn[m] * (1 - x) + x
    # the light, never more than the alpha as drawn (light outside it would tint the edges), and its
    # glow likewise (never above the alpha's glow)
    L = np.minimum(L, drawn)
    gl = np.minimum(ga, [np.percentile(L.ravel()[ring == i], GLOW_PERCENTILE) if (ring == i).any() else 0.0
                         for i in range(GLOW_RINGS)])
    GL = np.interp(R, r_mid, gl) if glow else np.zeros_like(A)
    layers = []
    if glow:
        stops = []
        for i in profile_points(r_mid, ga, gl):
            stops += [round(100 * float(r_mid[i])), r2(float(ga[i])), r2(float(gl[i]))]
        layers.append([2, stops])

    def increments(target, start, levels):
        # added light: each outline adds one amount, fitted to the pixels it ends up showing
        d, out = start.copy(), []
        for band, m in levels:
            inc = max(0.0, float((target[band] - d[band]).mean()))
            out.append(inc)
            d[m] += inc
        return out, d

    D = A - L                                     # the env's share of the colour: (1 - I) x A
    inc_l, light = increments(L, GL, [(band, m) for band, m, _, _ in alpha_levels])
    inc_d, _ = increments(D, GA - GL, [(band, m) for band, m, _, _ in alpha_levels])
    for (band, m, want, under), il, idk, rings in zip(alpha_levels, inc_l, inc_d, rings_by):
        layers.append([0, r2(want), r2(under), r3(il), r3(idk), rings])
    shown = A >= ALPHA_LEVELS[0]
    if shown.any():
        # where the light does not follow the alpha's outlines: outlines of its own, kept when they
        # bring the light clearly closer (by LIGHT_GAIN of its error, at least LIGHT_WHEN)
        res = L - GL
        own = []
        for t in ALPHA_LEVELS:
            rings = rings_of(res >= t) if (res >= t).any() else []
            if rings:
                own.append((raster(rings), rings))
        levels = [(m & ~own[j + 1][0] if j + 1 < len(own) else m, m) for j, (m, _) in enumerate(own)]
        levels = [(band if band.sum() else m, m) for band, m in levels]
        inc, own_light = increments(L, GL, levels)
        before = float(np.abs(L[shown] - light[shown]).mean())
        after = float(np.abs(L[shown] - own_light[shown]).mean())
        if before - after > max(LIGHT_WHEN, LIGHT_GAIN * before):
            for il, (_, rings) in zip(inc, own):
                layers.append([1, r3(il), rings])
    return {'regions': layers}


# ---------------------------------------------------------------- particles
def origin_of(m, frame, parts):
    """The contact point the effect grew from: its app SRT's translate, else the victim's recorded
    contact point (Fighter +0x1854) nearest the first particle, else that particle's birth position."""
    for p in parts:
        if p.get('srt'):
            return p['srt']['translate'][:2]
    first = parts[0]['pos'][:2]
    pts = [f['dmg']['pos'][:2] for f in frame['fighters'] if f['dmg']['pos'] and any(f['dmg']['pos'])]
    near = min(pts, key=lambda q: math.hypot(q[0] - first[0], q[1] - first[1]), default=None)
    if near and math.hypot(near[0] - first[0], near[1] - first[1]) < 6:
        return near
    return first


def local(p, origin, scaled):
    """position and half size around the origin: effect units for a scaled effect (its SRT's)"""
    x, y = p['pos'][0], p['pos'][1]
    half = p['size']
    if p.get('srt'):
        t, s = p['srt']['translate'], p['srt']['scale'][0]
        if scaled:
            return x + (t[0] - origin[0]) / s, y + (t[1] - origin[1]) / s, half, 1.0
        return t[0] + s * x - origin[0], t[1] + s * y - origin[1], half * s, s
    return x - origin[0], y - origin[1], half, 1.0


def hexcol(c, alpha=True):
    c = [max(0, min(255, int(v))) for v in c]
    return '#' + ''.join(f'{v:02x}' for v in (c if alpha else c[:3]))


def effect(m, spec, tex):
    banks = {b['bank']: b for b in m['banks']}
    F = m['frame']
    gens = set(spec['gens'])
    alive, frames, origin, palette = {}, [], None, []
    for fr in m['frames']:
        k = fr['match_frame'] - F
        mine = []
        for p in fr['particles']:
            g = gid(banks, p) if p['bank'] == 0 else None
            if g not in gens:
                continue
            a = alive.get(p['addr'])
            if a is None or a['gid'] != g or p['life'] > a['life']:
                a = alive[p['addr']] = {'gid': g, 'born': k, 'pos0': p, 'keep': None}
            a['life'] = p['life']
            if k >= 0:
                mine.append((p, a))
        if k < 0:
            continue
        if origin is None and mine:
            origin = origin_of(m, fr, [p for p, _ in mine])
        row = []
        for p, a in mine:
            if a['keep'] is None:
                bx, by, _, _ = local(a['pos0'], origin, False)
                a['keep'] = a['born'] >= 0 and math.hypot(bx, by) <= BORN_NEAR
            if not a['keep']:
                continue
            kind = int(p['kind'], 16)
            x, y, half, s = local(p, origin, spec.get('scaled'))
            if half <= 0.02:
                continue
            vx, vy = p['vel'][0], p['vel'][1]
            if kind & (TRAIL | DIRVEC):
                ang = math.atan2(-vx, vy) + (p['rot'] if kind & DIRVEC else 0.0)
            else:
                ang = p['rot']
            prim = p['prim_shown']
            env = p['env_shown'] if kind & PRIM_ENV else [0, 0, 0, 0]
            if prim[3] < 4:
                continue
            shown = half * (EFFECT_SCALE_MAX if spec.get('scaled') else 1.0)
            colours = [hexcol(prim)[1:], hexcol(env, False)[1:]]
            if colours not in palette:
                palette.append(colours)
            item = [tex.index(p['texg'], p['pose'], kind, shown, spec.get('traced', True)), r1(x), r1(y), r1(half), round(math.degrees(ang)) % 360,
                    palette.index(colours), (kind >> 22) & 3]
            if kind & TRAIL:
                k_scale = 1.0 if spec.get('scaled') or not p.get('srt') else s
                item.append([r1(-vx * k_scale), r1(-vy * k_scale), r2(p['trail'])])
            row.append(item)
        frames.append(row)
        if k >= LAST_K:
            break
    while frames and not frames[-1]:
        frames.pop()
    out = {'scaled': 1, 'frames': frames} if spec.get('scaled') else {'frames': frames}
    out['colours'] = palette
    if spec.get('faces'):
        # the effect is turned by the victim's facing (efAsync_Dispatch 0x3ED: SRT rotation y 0 or pi):
        # the facing of the victim in this sample; the painter mirrors it for the other side
        at = next(fr for fr in m['frames'] if fr['match_frame'] == F)
        pre = next(fr for fr in m['frames'] if fr['match_frame'] == F - 1)
        hit = [v for v in at['fighters'] for q in pre['fighters'] if q['port'] == v['port'] and v['percent'] > q['percent'] + 0.001]
        out['facing'] = 1 if (hit[0]['facing'] if hit else 1) > 0 else -1
    return out


# ---------------------------------------------------------------- shield stun
def shield_stun(d):
    """EfCoData model 13 (effect 1049, spawned on the shield joint as shield stun begins, ftCo_80092F2C,
    efasync.c 0x419): a flipbook of the bubble, one or two of its meshes shown per frame (anim track
    12, RAM-checked): the bubble cut into thin horizontal strips, a few of them shifted sideways
    (joints 2-7, in the player's shield colour), on alternate frames a white scribble over it (joint
    8), then the plain bubble (joint 1) from frame 7 on. The tear is a band or two of strips whose
    texture stretches the disc's rows sideways (and nudges them), the bands sliding apart frame by
    frame. As numbers for Watch Lite's own torn bubble: how many strips, and per frame each band's
    middle and half height and how far past the rim it reaches (bubble radii), and whether the scribble
    shows."""
    import hsdgeom
    import itemmodel
    from tracker.video import sprites
    tab = d.root['effCommonDataTable']
    m = tab + 8 + 13 * 0x14
    root, aj = d.p(m + 4), d.p(m + 8)
    js = hsdgeom.joints(d, root)
    tracks = itemmodel.anim_tracks(d, aj)
    frames, strips = [], 0
    for f in range(1, 30):
        f = float(f)
        vis = {j['index'] for j, node in zip(js, tracks) if node and 12 in node and sprites._track_value(node[12], f) > 0.5}
        if vis <= {1}:
            break
        ov = itemmodel.anim_override(d, js, tracks, f)
        ov.setdefault(0, {})
        parts, _ = hsdgeom.model(d, root, override=ov, parent=np.eye(4), with_hidden=True)
        rows = []                                  # (strip middle y, how far past the rim it reaches)
        for q in parts:
            if q['joint'] not in vis - {1, 8}:
                continue
            tris = q['tris']
            bubble = max(abs(v['pos'][1]) for tri in tris for v in tri)
            for i in range(0, len(tris), 2):
                P = np.array([v['pos'] for v in tris[i] + tris[i + 1]]) / bubble
                U = np.array([v['uv'][0] for v in tris[i] + tris[i + 1]])
                x0, x1, u0, u1 = P[:, 0].min(), P[:, 0].max(), U.min(), U.max()
                y = P[:, 1].mean()
                # the disc's row y as this strip shows it: centred at cx, stretched hw times
                cx, hw = x0 + (0.5 - u0) / (u1 - u0) * (x1 - x0), 0.5 * (x1 - x0) / (u1 - u0)
                rim = math.sqrt(max(0.0, 1 - y * y))
                rows.append((y, max(abs(cx - hw * rim), abs(cx + hw * rim)) - rim))
        strips = max(strips, len(rows))
        # the bands: runs of torn strips next to each other
        step = 2.0 / max(1, len(rows))
        bands, run = [], []
        for y, out in sorted(r for r in rows if r[1] > 0.02):
            if run and y - run[-1][0] > 1.5 * step:
                bands.append(run)
                run = []
            run.append((y, out))
        if run:
            bands.append(run)
        frames.append([[[r2((b[0][0] + b[-1][0]) / 2), r2((b[-1][0] - b[0][0]) / 2 + step / 2), r2(max(o for _, o in b))]
                        for b in bands], int(8 in vis)])
    return {'strips': strips, 'frames': frames}


# ---------------------------------------------------------------- techs
TECH_MODEL, TECH_JOINTS = 15, 6    # effect 1053 (0x41D): EfCoData model 15, efLib_Create_Attach_Pos
TECH_RAYS = [261, 11]              # its particles (effects.tech): 8 thin rays closing in (generator 261) and
                                   # a white-blue star flash (11, the hard hit's): both in RAM at every tech
TECH_GLOW = 3                      # its glow quad
TECH_RINGS = (2, 5)                # its two spinning rings
# where a wall tech's effect sits from the fighter (after the tech), toward the wall and up: the ECB's
# side point (ftCo_PassiveWall.c); measured in RAM over 6 wall and wall-jump techs (median)
TECH_WALL = (3.3, 8.5)
# a ceiling tech's sits on top of the ECB (ftCo_PassiveCeil.c): no ceiling tech turned up in 601
# replays to measure, so twice the side point's height (the ECB's sides are halfway up)
TECH_CEIL = 2 * TECH_WALL[1]


def fobj_value(keys, frame):
    """A decoded FObj track (sprites._decode_fobj) at `frame` as the game plays it (fobj.c, HSDRaw's
    FOBJ_Player): between two keys the interpolation is the earlier key's. sprites._track_value takes
    the later key's, which holds a fade the game already runs: the tech rings' BLEND track (1 at frame
    5, linear to 0 at 8) stayed at 1 until 8, where the playback Dolphin shows them faded at 6 and 7."""
    if frame <= keys[0]['frame'] or len(keys) == 1:
        return keys[0]['value']
    if frame >= keys[-1]['frame']:
        return keys[-1]['value']
    i = max(j for j, k in enumerate(keys) if k['frame'] <= frame)
    a, b = keys[i], keys[i + 1]
    t, span = frame - a['frame'], b['frame'] - a['frame']
    if span <= 0 or a['interp'] in (1, 6):                      # CON, KEY: hold
        return a['value']
    if a['interp'] == 2:                                        # LIN
        return a['value'] + (b['value'] - a['value']) * t / span
    s = t / span                                                # SPL0 / SPL / SLP: Hermite
    d0, d1 = (0.0, 0.0) if a['interp'] == 3 else (a['tan'], b['tan'])
    return ((2 * s ** 3 - 3 * s ** 2 + 1) * a['value'] + (s ** 3 - 2 * s ** 2 + s) * span * d0
            + (-2 * s ** 3 + 3 * s ** 2) * b['value'] + (s ** 3 - s ** 2) * span * d1)


def tech_effect(d, m):
    """A tech's effect (all of them spawn effect 1053: ftCo_Passive.c, PassiveStand, PassiveWall,
    PassiveCeil): EfCoData model 15, whose particle track starts generator 261 (thin rays closing in,
    effects.tech, read like the hit effects) and whose two rings spin out while a glow quad fades in.
    The joints are posed by RAM (the effect's joint world matrices, record.py; the same for every tech:
    the effect never turns with the fighter). Their colour is their texture's TEV stage (tobj.c
    MakeColorGenTExp): TEV0 x (1 - tex) + KONST x tex at tex alpha, mixed over the material's colour
    and alpha by the BLEND track (TObjMakeTExp: colormap and alphamap BLEND; texture anim tracks 9,
    KONST 12-14, TEV0 16-18); the quad's PE adds it, the rings (no PE) blend by alpha. Watch Lite draws
    both with its own shapes from these numbers:
    - glow: per frame since the tech, [blend, KONST, TEV0, half size (world units)], or 0 while hidden;
    - rings: base, the rings' material colour and alpha ('rrggbbaa'); lobes, per ring, its model's four
      quarter-disc quads as [u0, v0, u1, v1]: a lobe's two edges from the ring's centre (model units, in
      the ring's plane); frames, per frame per ring, [[ax, ay, az, bx, by, bz], blend, KONST, TEV0]: the
      ring plane's two axes in world units per model unit (from RAM: they turn and grow; z toward the
      camera), so a lobe's edge (u, v) is u x a + v x b from the effect.
    The tech also starts colour animation 120 on the fighter (ftCo_800BFFD0; PlCo ftLoadCommonData
    [6]: white at alpha 120 for 2 frames), which the recorded frames do not show: left out. Plus the
    wall and ceiling offsets."""
    import hsdgeom
    from tracker.video import sprites
    tab = d.root['effCommonDataTable']
    base = tab + 8 + TECH_MODEL * 0x14
    root, ma = d.p(base + 4), d.p(base + 0xC)
    tracks = {}                                   # joint index -> {texture anim track type: keys}
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
        return float(fobj_value(keys, f)) if keys else default

    # the model in its joints' own units: the rings' lobes, the glow quad's size, the materials
    plain, _ = hsdgeom.model(d, root, override={i: {'world': np.eye(4)} for i in range(TECH_JOINTS)}, parent=np.eye(4),
                             with_hidden=True)
    lobes, mats, glow_half = {}, {}, 0.0
    for q in plain:
        jt = q['joint']
        if not q['mat']['tobjs']:
            continue
        mats[jt] = q
        if jt == TECH_GLOW:
            glow_half = max(abs(v['pos'][c]) for tri in q['tris'] for v in tri for c in (0, 1))
        if jt in TECH_RINGS:
            out = []
            for i in range(0, len(q['tris']), 2):
                at = {tuple(int(round(c)) for c in v['uv']): np.array(v['pos']) for v in q['tris'][i] + q['tris'][i + 1]}
                e10, e01 = at[(1, 0)] - at[(1, 1)], at[(0, 1)] - at[(1, 1)]
                out.append([r2(e10[0]), r2(e10[1]), r2(e01[0]), r2(e01[1])])
            lobes[jt] = out
    ring_base = {hexcol(list(mats[j]['mat']['dif'][:3]) + [round(255 * mats[j]['mat']['alpha'])])[1:] for j in TECH_RINGS}
    if len(ring_base) != 1:
        raise SystemExit('tech rings: the two rings no longer share a material')

    def colours(jt, f):
        t = mats[jt]['mat']['tobjs'][0]
        tev = d.p(t['off'] + 0x58)
        konst = [round(track(jt, 12 + c, f, d.b(tev + 16 + c) / 255) * 255) for c in range(3)]
        tev0 = [round(track(jt, 16 + c, f, d.b(tev + 20 + c) / 255) * 255) for c in range(3)]
        return r2(track(jt, 9, f, t['blending'])), hexcol(konst, False)[1:], hexcol(tev0, False)[1:]

    F, sub = m['frame'], m['subject']['port']
    gobj, origin, glow, rings = None, None, [], []
    for fr in m['frames']:
        k = fr['match_frame'] - F
        if k < 0:
            continue
        me = next(f for f in fr['fighters'] if f['port'] == sub)
        effs = [e for e in fr['effects'] if len(e.get('joints') or []) == TECH_JOINTS]
        if gobj is None:
            # the one spawned on the fighter
            e = min(effs, key=lambda e: math.hypot(e['joints'][0]['world'][3] - me['pos'][0],
                                                   e['joints'][0]['world'][7] - me['pos'][1]))
            w = e['joints'][0]['world']
            gobj, origin = e['gobj'], np.array([w[3], w[7], w[11]])
        e = next((x for x in effs if x['gobj'] == gobj), None)
        if e is None:
            break
        js = e['joints']
        f = float(js[0]['anim_frame'])
        hidden = {i for i, j in enumerate(js) if int(j['flags'], 16) & 0x10}
        W = {i: np.array(j['world']).reshape(3, 4) for i, j in enumerate(js)}
        row = []
        for jt in TECH_RINGS:
            blend, konst, tev0 = colours(jt, f)
            if jt in hidden or blend <= 0.004:
                continue
            if np.abs(W[jt][:, 3] - origin).max() > 0.05:
                raise SystemExit('tech rings: a ring no longer spins about the effect')
            row.append([[r3(c) for c in (*W[jt][:, 0], *W[jt][:, 1])], blend, konst, tev0])
        blend, konst, tev0 = colours(TECH_GLOW, f)
        g = 0 if TECH_GLOW in hidden or blend <= 0.004 else \
            [blend, konst, tev0, r2(glow_half * np.linalg.norm(W[TECH_GLOW][:, 0]))]
        if not row and not g and (any(glow) or any(rings)):
            break                                 # shown, and gone
        glow.append(g)
        rings.append(row)
    while glow and not glow[-1]:
        glow.pop()
    while rings and not rings[-1]:
        rings.pop()
    return {'glow': glow, 'rings': {'base': ring_base.pop(), 'lobes': [lobes[j] for j in TECH_RINGS], 'frames': rings},
            'wall': list(TECH_WALL), 'ceil': TECH_CEIL}


# ---------------------------------------------------------------- slash crescents
def slash_crescents(d):
    """EfCoData model 8 joints 2 and 3 (the meshes) by frame since the hit (effect frame k + 1:
    the effect's animation already reads frame 1 on the frame the hit lands, RAM-checked), in effect
    units seen from the camera; each visible joint as [outer, core] outlines of its additive light."""
    import hsdgeom
    import itemmodel
    import shapes
    from tracker.video import sprites
    tab = d.root['effCommonDataTable']
    m = tab + 8 + 8 * 0x14
    root, aj, ma = d.p(m + 4), d.p(m + 8), d.p(m + 0xC)
    js = hsdgeom.joints(d, root)
    tracks = itemmodel.anim_tracks(d, aj)
    out = []
    for k in range(10):
        f = float(k + 1)
        ov = itemmodel.anim_override(d, js, tracks, f)
        show = {j['index'] for j, node in zip(js, tracks) if 12 in node and sprites._track_value(node[12], f) > 0.5}
        ov.setdefault(0, {})
        parts, _ = hsdgeom.model(d, root, override=ov, parent=np.eye(4), with_hidden=True)
        if ma is not None:
            parts = itemmodel.apply_matanim(parts, itemmodel.matanim_state(d, ma, f))
        row = []
        for j in (2, 3):
            ps = [p for p in parts if p['joint'] == j and j in show]
            if not ps:
                continue
            ppu, R = 12, 30
            W = H = 2 * R * ppu

            def front(P):
                return np.stack([(P[:, 0] + R) * ppu, (R - P[:, 1]) * ppu], 1), P[:, 2]
            acc = shapes.raster_fx(d, ps, front, W, H, ss=2)
            lum = acc.max(2)
            ring = []
            for cut in (40, 200):
                mask = (lum >= cut).astype(np.uint8)
                cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                if not cs:
                    ring.append([])
                    continue
                c = max(cs, key=cv2.contourArea)
                c = cv2.approxPolyDP(c, 0.25 * ppu, True)[:, 0, :]
                ring.append([[r1(x / ppu - R), r1(R - y / ppu)] for x, y in c])
            # the light each region adds (additive): the outer one its mean, the core what it adds on top
            outer_sel, core_sel = lum >= 40, lum >= 200
            outer = acc[outer_sel].mean(0) if outer_sel.any() else np.zeros(3)
            core = acc[core_sel].mean(0) - outer if core_sel.any() else np.zeros(3)
            row.append([ring[0], ring[1], hexcol(outer.tolist(), False), hexcol(np.clip(core, 0, 255).tolist(), False)])
        out.append(row)
    while out and not out[-1]:
        out.pop()
    return out


def shake(plco):
    """The victim's hitlag shake (ftCo_DamageFall.c ftCo_80090594 / ftCo_80090690, fighter.c): for
    x168 x hitlag + x16C frames (PlCo ftCommonData) the model steps through a pattern of offsets,
    PlCo `ftLoadCommonData` [9]: [Vec2 *, count] for air, ground (along the facing / floor) and the
    electric zap."""
    root = plco.root['ftLoadCommonData']
    cd = plco.p(root)
    table = plco.p(root + 9 * 4)
    pats = []
    for t in range(3):
        p, n = plco.p(table + 8 * t), plco.u(table + 8 * t + 4)
        pats.append([[r2(plco.f(p + 8 * i)), r2(plco.f(p + 8 * i + 4))] for i in range(n)])
    return {'mul': r2(plco.f(cd + 0x168)), 'add': r2(plco.f(cd + 0x16C)), 'patterns': pats}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rec', type=Path, required=True, help='record.py output for samples.json')
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--out', type=Path, default=DATA / 'hitEffects.js')
    args = ap.parse_args()
    import isofiles
    from isofiles import dat
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = Path(str(known_vanilla_iso()))
    isofiles.open_iso(args.iso)
    d = dat('EfCoData.dat')
    _, tex_bank = ptcltex.banks(d, 'effCommonDataTable')
    tex = Textures(d, tex_bank)
    samples = json.loads((HERE / 'samples.json').read_text())
    effects, tech = {}, None
    for s in samples:
        m = json.loads((args.rec / f"{s['id']}.json").read_text())
        if not m.get('ok'):
            raise SystemExit(f"{s['id']}: recording failed ({m.get('error')})")
        if s['kind'] == 'tech':
            tech = tech_effect(d, m)
            effects['tech'] = effect(m, {'gens': TECH_RAYS, 'traced': False}, tex)
        else:
            effects[s['kind']] = effect(m, EFFECTS[s['kind']], tex)
    out = {'textures': tex.listed(), 'effects': effects, 'slash': slash_crescents(d), 'shieldStun': shield_stun(d),
           'tech': tech, 'shake': shake(dat('PlCo.dat'))}
    args.out.write_text(HEADER + 'export default ' + js_stringify(out) + ';\n', encoding='utf-8', newline='\n')
    print(f"{args.out.name}: {len(out['textures'])} textures, " + ', '.join(
        f"{k} {len(v['frames'])} frames / {sum(map(len, v['frames']))} particles" for k, v in effects.items())
        + f", slash crescents {len(out['slash'])} frames, {args.out.stat().st_size} bytes")


if __name__ == '__main__':
    main()
