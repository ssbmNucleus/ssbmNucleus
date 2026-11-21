"""KO blasts, star and screen KOs and the invincibility timers for Watch Lite (koEffects.js), from
the game's own data.

KO blast (ft_0D31.c ftCo_800D3680 / 800D3950 / 800D3BC8, efasync.c 0x42B): a fighter past the left,
right or bottom blast zone spawns effect 1067, EfCoData model 25, at its position (a side KO's y and a
bottom KO's x clamped into the blast zones), turned -pi/2 (left), +pi/2 (right) or 0 (bottom) so the
model's +y points into the stage, scaled by ftCommonData +0x4F4. Its first mesh's TEV stage takes the
player's colours (efLib_SetTevKonstColor: KONST = PlCo ftLoadCommonData [19], TEV0 = [18], by the
colour index gm_80160854 gives: the port for a human, the team in a team game, 4 for a CPU). Only
numbers ship; Watch Lite draws its own shapes (koBlast.js). Per mesh (joints 1-5): the box its
triangles fill in joint space and its colours (TEV0 / KONST where its TEV colour stage is on, tobj.c;
else its texture's dark and light colour); per frame its joint's scale and translation and whether it
shows, as RAM had them on the samples.json KO, and its KONST alpha (texture track 15). The model's
particle track (anim type 40) starts generators 212-217 and 222-224: beams, streaks, sparks and the
smoke that lingers ~40 frames. They are read from RAM like the hit sparks (hit_effects/record.py, the
KO in samples.json; positions and trails in the effect's own space: its app SRT carries the turn and
the scale): where each is, its size, turn, colours and which of the effect bank's textures it shows,
kept as a kind of shape (LOOKS) Watch Lite draws itself. The blast zones are each stage's general
points 0x97 and 0x98 (ground.c Ground_801C39C0) times its scale (grGroundParam +0).

Star and screen KOs (ft_0D31.c): a fighter past the top blast zone is a screen KO one time in
100 / ftCommonData +0x520 (16), else a star KO. Star (DeadUpStar 4, ice 5): after +0x504 frames (1)
it flies for +0x508 (130) frames on a straight line to z = +0x510 (-350) and y = +0x514 (0.6) x the
camera's top bound, playing DamageFall; then it hides and effect 0x42D (generator 289, the twinkle) is
spawned where it is (read from RAM, samples.json `star`). Screen (DeadUpFall 6, ice 9): its model is
placed in camera space (ftdrawcommon.c: cur_pos = inverse view x the point): lerped from +0x538 to
+0x544 over +0x528 (50) frames, held +0x52C (3) frames on the camera (DeadUpFallHitCamera 7, flat 8,
ice 10), then falling +0x530 (40) frames with y velocity +0x550 (1) under gravity +0x554 (0.2) capped at
+0x558 (1.7) and z velocity +0x55C (-1); then it hides. RAM agrees with both paths on every frame. The
game camera's vertical field of view is 30 degrees (RAM, every stage recorded); it pitches and turns by
camera.c Camera_80029CF8: pitch = clamp(-(2 (mid y - offset y)(0.5 - blend) + offset y + C[0x8]) x
grGroundParam +0x18, C[0x10], C[0xC]) + grGroundParam +0x14 (pan) degrees, blend from C[0x1C] to
C[0x20] as the bounds grow from C[0x24] to C[0x28]; yaw = clamp(-(mid x - offset x) x grGroundParam
+0x1C, C[0x18], C[0x14]); C = the camera constants at 0x803BCCA0 (main.dol); the offset is the stage's
general point 0x94 times its scale (RAM agrees on 5 stages).

Invincibility (ftcoll.c ftColl_8007B760 / 8007B7A4): a fighter is made intangible (x1990) or
invincible (x1994) for a while, the game flickering its model meanwhile (colour animation 9). The
timers, by what sets them: CliffWait (+0x49C, 30), wall tech or wall-jump tech (+0x764, 14), tumbling
into a wall or ceiling (FlyReflect, +0x1B8, 15) or bouncing off the ground (DownReflect, 15), a throw
for the thrower (+0x348, 8), climbing out of the ground (BuryJump, +0x620, 18), leaving RebirthWait or
Rebirth (+0x5D8, 120), leaving Yoshi's egg (Yoshi's attribute +0x38, 14; Kirby's copy +0x3D4, 14). Watch Lite
outlines the fighter while one runs, and on the respawn platform (invincible.js).

    app/venv/Scripts/python.exe -B tools/liteaudit/hit_effects/record.py --targets tools/liteaudit/ko_effects/samples.json --out <dir> --pre 2 --post 180 --shots 0
    app/venv/Scripts/python.exe -B tools/liteaudit/ko_effects/build.py --rec <dir> [--iso PATH] [--out PATH]

Writes app/frontend/src/tracker/replays/data/koEffects.js:
  blast     {scale, layers: [[x0, y0, x1, y1, prim 'rrggbb' | null (the player's KONST), env 'rrggbb' |
            null (the player's TEV0)]] (joints 1-5: the player's flame, the flash, the burst, the
            beam, the green flame; the box their triangles fill in joint space), frames: [[[layer, sx,
            sy, tx, ty, alpha]] by frame since the KO (0 = the frame the fighter is first dead, the
            model's animation frame 1: RAM)], colours: [[TEV0, KONST] by colour index], particles:
            {looks, frames: [[[look, x, y, half size, turn (degrees), colours, additive, tail?]] by
            frame since the KO] (effect units; tail = [dx, dy, alpha] back along a trail), colours:
            [[prim 'rrggbbaa', env 'rrggbb']]}}
  zones     {stage id: [left, right, top, bottom]}: the blast zones
  flash     {enter: {state: frames}, leave: {state: frames}}: entering or leaving that action state
            makes the fighter invincible or intangible for that many frames
  star      {wait, frames, after, z, y, twinkle: {frames, colours} as blast.particles (world units
            around where it starts; frame 0 = the first frame the fighter is hidden)}
  screen    {wait, start: [x, y, z], end, lerp, hold, fall, vy, gravity, terminal, vz} (camera space)
  fovy      the game camera's vertical field of view (degrees)
  camera    {aspect, pitch: [C 0x8, min, max], blend: [C 0x1C, 0x20, 0x24, 0x28], yaw: [min, max],
            stages: {stage id: [yaw factor, pitch factor, pan degrees, offset x, offset y]}}
"""
import argparse
import importlib.util
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / 'app/frontend/src/tracker/replays/data'
sys.path[0:0] = [str(REPO / 'tools/liteaudit/hit_effects'), str(REPO / 'tools/liteaudit/item_shapes'),
                 str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]
import ptcltex                                      # noqa: E402

_spec = importlib.util.spec_from_file_location('hit_effects_build', REPO / 'tools/liteaudit/hit_effects/build.py')
_heb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_heb)
js_round, js_stringify = _heb.js_round, _heb.js_stringify

BLAST_MODEL = 25                  # effect 1067 (0x42B): EfCoData model 25, efLib_Create_Attach_Pos
BLAST_FRAMES = 60                 # the fighter stays dead for ftCommonData +0x500 = 60 frames; the
                                  # model's last mesh hides long before, its last particle at ~42
BLAST_GENS = [212, 213, 214, 215, 216, 217, 222, 223, 224]   # its particle track's generators (RAM)
TWINKLE_GENS = [289]              # effect 0x42D (efasync.c: generator 0x121), the star KO's twinkle
CAMERA_FOVY = 30                  # the game camera's vertical field of view (RAM, every stage recorded)
CAMERA_ASPECT = 1.21733           # and its aspect (RAM)
TRACE_PX = 640                    # a layer's texture is sampled this many pixels along its box's long side ...
TRACE_MIN_PX = 64                 # ... and at least this many along its short side, to find its colours
PLAYER_JOINT = 1                  # the mesh efLib_SetTevKonstColor colours: the model root's first child
HEADER = ("// KO blasts, star and screen KOs and the invincibility timers: numbers read from the game\n"
          "// (EfCoData.dat model 25 and its particles, PlCo.dat, the stages) by\n"
          "// tools/liteaudit/ko_effects/build.py; no game art. Do not edit by hand; see koBlast.js,\n"
          "// koFlight.js and invincible.js.\n")
PTCL, HIDDEN = 0x20, 0x10


def r2(v):
    return js_round(v, 2)


def r3(v):
    return js_round(v, 3)


def hexcol(c):
    return ''.join(f'{max(0, min(255, int(round(v)))):02x}' for v in c)


# what makes a fighter invincible or intangible: action state entered -> the ftCommonData offset of its
# timer (CliffWait, wall techs, FlyReflect, DownReflect, throws, BuryJump; RAM agreed on the ledge grabs,
# throws, wall bounce and respawns recorded; DownReflect and BuryJump had none in 300 recent games)
ENTER = {253: 0x49C, 202: 0x764, 203: 0x764, 247: 0x1B8, 248: 0x1B8, 335: 0x1B8, 219: 0x348, 220: 0x348,
         221: 0x348, 222: 0x348, 296: 0x620}
# action state left -> ftCommonData offset, or (fighter DAT, special attribute offset). Leaving the respawn
# platform: RebirthWait, or Rebirth itself when an input held as it ends drops the fighter in the frame
# RebirthWait begins (ftCo_RebirthWait_IASA; the replay never shows 13; about half of all respawns, and
# most in doubles). Both set +0x5D8 (RAM: 120 frames invulnerable from the first frame out of Rebirth).
LEAVE = {12: 0x5D8, 13: 0x5D8, 277: ('PlYs.dat', 0x38), 332: ('PlKb.dat', 0x3D4)}


def flash(plco, dat):
    """What makes a fighter invincible or intangible, with its timer."""
    cd = plco.p(plco.root['ftLoadCommonData'])

    def timer(src):
        if isinstance(src, int):
            return plco.u(cd + src)
        f, off = src
        d = dat(f)
        root = next(v for k, v in d.roots if k.startswith('ftData'))
        return d.u(d.p(root + 4) + off)
    return {'enter': {s: timer(src) for s, src in ENTER.items()}, 'leave': {s: timer(src) for s, src in LEAVE.items()}}


def star_screen(plco):
    """The star KO's flight and the screen KO's camera-space path (ftCommonData +0x504, +0x520)."""
    cd = plco.p(plco.root['ftLoadCommonData'])
    u, f = (lambda o: plco.u(cd + o)), (lambda o: r3(plco.f(cd + o)))
    star = {'wait': u(0x504), 'frames': u(0x508), 'after': u(0x50C), 'z': f(0x510), 'y': f(0x514)}
    screen = {'wait': u(0x524), 'start': [f(0x538), f(0x53C), f(0x540)], 'end': [f(0x544), f(0x548), f(0x54C)], 'lerp': u(0x528),
              'hold': u(0x52C), 'fall': u(0x530), 'vy': f(0x550), 'gravity': f(0x554), 'terminal': f(0x558),
              'vz': f(0x55C)}
    return star, screen


# ---------------------------------------------------------------- the KO blast
def port_colours(plco):
    """[TEV0, KONST] by colour index 0-4 (P1-P4, CPU): ftLoadCommonData [18] and [19]."""
    root = plco.root['ftLoadCommonData']
    a, b = plco.p(root + 18 * 4), plco.p(root + 19 * 4)
    return [[plco.raw[0x20 + a + 4 * i:0x20 + a + 4 * i + 3].hex(), plco.raw[0x20 + b + 4 * i:0x20 + b + 4 * i + 3].hex()]
            for i in range(5)]


def tex_tracks(d, ma):
    """{joint index: {texture anim track type: keys}} (MatAnimJoint tree, first material's first texture)."""
    from tracker.video import sprites
    out = {}
    if ma is None:
        return out
    for ji, mj in enumerate(d._iter_tree(ma, 0x00, 0x04)):
        m = d.p(mj + 8)
        ta = d.p(m + 8) if m is not None else None
        aobj = d.p(ta + 8) if ta is not None else None
        fo = d.p(aobj + 8) if aobj is not None else None
        while fo is not None:
            t, keys = sprites._decode_fobj(d, fo)
            if keys:
                out.setdefault(ji, {})[t] = keys
            fo = d.p(fo)
    return out


def layer(d, part):
    """One mesh in its own joint space: the box its triangles fill and its colours (prim, env: its
    TEV stage's KONST and TEV0, else its texture's light and dark colour where it shows)."""
    import hsdgeom
    t = part['mat']['tobjs'][0]
    tev = d.p(t['off'] + 0x58)
    active = d.u(tev + 28) if tev is not None else 0
    colour_tev, alpha_tev = bool(active & (1 << 30)), bool(active & (1 << 31))
    P = np.array([v['pos'] for tri in part['tris'] for v in tri])
    lo, hi = P[:, :2].min(0), P[:, :2].max(0)
    pad = (hi - lo) * 0.02
    lo, hi = lo - pad, hi + pad
    span = hi - lo
    k = TRACE_PX / span.max()
    W, H = max(TRACE_MIN_PX, int(round(span[0] * k))), max(TRACE_MIN_PX, int(round(span[1] * k)))
    tex = d.texture(t['img'], t['tlut']).astype(np.float32)
    A = np.zeros((H, W), np.float32)
    C = np.zeros((H, W, 3), np.float32)
    for tri in part['tris']:
        Q = np.array([v['pos'][:2] for v in tri])
        S = np.stack([(Q[:, 0] - lo[0]) / span[0] * W, (hi[1] - Q[:, 1]) / span[1] * H], 1)
        (x0, y0), (x1, y1), (x2, y2) = S
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        mnx, mxx = max(int(S[:, 0].min()), 0), min(int(S[:, 0].max()) + 1, W)
        mny, mxy = max(int(S[:, 1].min()), 0), min(int(S[:, 1].max()) + 1, H)
        if mnx >= mxx or mny >= mxy:
            continue
        ys, xs = np.mgrid[mny:mxy, mnx:mxx] + 0.5
        w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
        w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (1 - w0 - w1 >= -1e-6)
        if not inside.any():
            continue
        bary = np.stack([w0[inside], w1[inside], 1 - w0[inside] - w1[inside]], 1)
        uv = bary @ np.array([v['uv'] for v in tri], np.float32)
        smp = hsdgeom._sample(tex, uv, t)
        a = smp[:, 3] / 255
        iy, ix = np.nonzero(inside)
        old = A[mny + iy, mnx + ix]
        A[mny + iy, mnx + ix] = 1 - (1 - old) * (1 - a)
        C[mny + iy, mnx + ix] = C[mny + iy, mnx + ix] * (1 - a[:, None]) + smp[:, :3] * a[:, None]
    shown = A > 0.02
    rgb = np.where(shown[..., None], C / np.maximum(A, 1e-6)[..., None], 0)
    if colour_tev:
        # TEV0 x (1 - tex) + KONST x tex: the intensity is the texture's colour (grey)
        I = rgb.mean(2) / 255
        lit = d.raw[0x20 + tev + 16:0x20 + tev + 19], d.raw[0x20 + tev + 20:0x20 + tev + 23]
        prim, env = lit[0].hex(), lit[1].hex()
    else:
        # the texture's own colour, as env + (prim - env) x intensity along its luminance
        lum = rgb.mean(2)
        sel = shown & (A > 0.2)
        lo_l, hi_l = np.percentile(lum[sel], 5), np.percentile(lum[sel], 95)
        dark, light = sel & (lum <= lo_l + 4), sel & (lum >= hi_l - 4)
        env = rgb[dark].mean(0) if dark.any() else rgb[sel].min(0)
        prim = rgb[light].mean(0) if light.any() else rgb[sel].max(0)
        I = np.clip((lum - env.mean()) / max(prim.mean() - env.mean(), 1.0), 0, 1)
        prim, env = hexcol(prim), hexcol(env)
    return {'box': [r2(lo[0]), r2(lo[1]), r2(hi[0]), r2(hi[1])], 'prim': prim, 'env': env,
            'konst_alpha': alpha_tev}


def blast(d, plco, m):
    """EfCoData model 25 as layers in joint space and, by frame since the KO, each one's joint
    scale/translation, whether it shows and its alpha. The joints are posed as RAM had them (the
    samples.json KO, record.py: each joint's local scale, translation and hidden flag; the effect is
    first drawn at its animation frame 1 on the frame the fighter is first dead); the alpha is the
    texture's KONST alpha track at that animation frame (it agrees with RAM)."""
    import hsdgeom
    from tracker.video import sprites
    tab = d.root['effCommonDataTable']
    base = tab + 8 + BLAST_MODEL * 0x14
    root, ma = d.p(base + 4), d.p(base + 0xC)
    js = hsdgeom.joints(d, root)
    texanim = tex_tracks(d, ma)
    # each mesh in its own joint space: every joint's world the identity
    ov = {j['index']: {'world': np.eye(4)} for j in js}
    parts, _ = hsdgeom.model(d, root, override=ov, parent=np.eye(4), with_hidden=True)
    layers, joint_of = [], []
    for q in parts:
        if not q['tris'] or not q['mat']['tobjs']:
            continue
        L = layer(d, q)
        L['joint'] = q['joint']
        layers.append(L)
        joint_of.append(q['joint'])
    # the sample's effect: the one with the model's joints whose root is at the KO'd fighter
    F, port = m['frame'], m['subject']['port']
    at = next(fr for fr in m['frames'] if fr['match_frame'] == F)
    pos = next(f for f in at['fighters'] if f['port'] == port)['pos']
    eff = next(e['gobj'] for e in at['effects'] if len(e.get('joints') or []) == len(js)
               and abs(e['joints'][0]['world'][3] - pos[0]) < 0.01 and abs(e['joints'][0]['world'][7] - pos[1]) < 0.01)
    frames = []
    for fr in m['frames']:
        k = fr['match_frame'] - F
        if k < 0:
            continue
        e = next((x for x in fr['effects'] if x['gobj'] == eff), None)
        if e is None:
            break
        rj = e['joints']
        f = float(rj[0]['anim_frame'])
        row = []
        for li, (L, ji) in enumerate(zip(layers, joint_of)):
            j = rj[ji]
            if int(j['flags'], 16) & HIDDEN:
                continue
            alpha = 1.0
            if L['konst_alpha']:
                keys = texanim.get(ji, {}).get(15)
                alpha = float(sprites._track_value(keys, f)) if keys else 1.0
            if alpha < 0.004:
                continue
            row.append([li, r3(j['scale'][0]), r3(j['scale'][1]), r2(j['translate'][0]), r2(j['translate'][1]), r3(alpha)])
        frames.append(row)
    while frames and not frames[-1]:
        frames.pop()
    cd = plco.p(plco.root['ftLoadCommonData'])
    return {'scale': r3(plco.f(cd + 0x4F4)),
            'layers': [[*L['box'], None if ji == PLAYER_JOINT else L['prim'], None if ji == PLAYER_JOINT else L['env']]
                       for L, ji in zip(layers, joint_of)],
            'frames': frames, 'colours': port_colours(plco)}


# ---------------------------------------------------------------- blast zones
def blast_zones(camera=None):
    """{Slippi stage id: [left, right, top, bottom]}: each vanilla stage's general points 0x97 and 0x98
    (world, through the points' joint tree) times the stage's scale, grGroundParam +0 (ground.c
    Ground_801C39C0, Ground_801C0498). `camera` (a dict) gets each stage's camera turn: [grGroundParam
    +0x1C, +0x18, +0x14 (s32), general point 0x94 x and y times the scale] (Ground_801C38D0)."""
    import hsdgeom
    from isofiles import dat
    from core.stages import STAGES_BY_SLIPPI_ID
    out = {}
    for sid in sorted(STAGES_BY_SLIPPI_ID):
        d = dat(STAGES_BY_SLIPPI_ID[sid]['code'] + '.dat')
        mh, gp = d.root.get('map_head'), d.root.get('grGroundParam')
        if mh is None or gp is None:
            continue
        scale = d.f(gp)
        pts = {}
        for g in range(d.u(mh + 4)):
            e = d.p(mh) + 0xC * g
            js = hsdgeom.joints(d, d.p(e))
            plist = d.p(e + 4)
            for i in range(d.u(e + 8)):
                ji, ty = d.h(plist + 4 * i), d.h(plist + 4 * i + 2)
                if ty in (0x94, 0x97, 0x98) and 0 <= ji < len(js):
                    pts[ty] = js[ji]['world'][:2, 3] * scale
        if 0x97 in pts and 0x98 in pts:
            a, b = pts[0x97], pts[0x98]
            out[sid] = [r2(min(a[0], b[0])), r2(max(a[0], b[0])), r2(max(a[1], b[1])), r2(min(a[1], b[1]))]
        if camera is not None:
            centre = pts.get(0x94, (0.0, 0.0))
            pan = struct.unpack('>i', d.raw[0x20 + gp + 0x14:0x20 + gp + 0x18])[0]
            camera[sid] = [r3(d.f(gp + 0x1C)), r3(d.f(gp + 0x18)), pan, r2(centre[0]), r2(centre[1])]
    return out


def camera_constants(iso):
    """The camera constants (camera.c cm_803BCCA0) from the ISO's main.dol."""
    with open(iso, 'rb') as f:
        f.seek(0x420)
        dol = struct.unpack('>I', f.read(4))[0]
        f.seek(dol)
        h = f.read(0xE4)
        offs, addrs, sizes = struct.unpack('>18I', h[:72]), struct.unpack('>18I', h[72:144]), struct.unpack('>18I', h[144:216])
        addr = 0x803BCCA0
        sec = next(i for i in range(18) if addrs[i] <= addr < addrs[i] + sizes[i])
        f.seek(dol + offs[sec] + addr - addrs[sec])
        c = struct.unpack('>60f', f.read(0xF0))
    v = lambda o: r3(c[o // 4])                                                # noqa: E731
    return {'pitch': [v(0x8), v(0x10), v(0xC)], 'blend': [v(0x1C), v(0x20), v(0x24), v(0x28)], 'yaw': [v(0x18), v(0x14)]}


# the shape Watch Lite draws for each of the effect bank's textures (texture group, pose: None = any):
# a thin streak (24; 23 pose 0), flame spikes (23 pose 1), a four-point sparkle (4 pose 0, 25 pose 0),
# a star (4 pose 2), a smoke puff (11), a starburst (25 poses 1, 2)
LOOKS = ['streak', 'spikes', 'sparkle', 'star', 'smoke', 'burst']
TEX_LOOK = {(24, None): 'streak', (23, 0): 'streak', (23, 1): 'spikes', (23, 2): 'sparkle', (4, 0): 'sparkle',
            (4, 1): 'sparkle', (4, 2): 'star', (11, None): 'smoke', (25, 0): 'sparkle', (25, 1): 'burst',
            (25, 2): 'burst'}


def particles(m, gens, d, scaled=True, last=BLAST_FRAMES):
    """An effect's particles frame by frame (hit_effects.effect on a samples.json recording, every
    particle of its generators kept wherever it is born): effect units when `scaled`, else world units
    around where the first one starts; each one's texture kept only as the kind of shape it is."""
    _heb.BORN_NEAR, _heb.LAST_K = 1e9, last
    _, bank = ptcltex.banks(d, 'effCommonDataTable')
    tex = _heb.Textures(d, bank)
    fx = _heb.effect(m, {'gens': gens, 'scaled': scaled}, tex)
    key = {i: k for k, i in tex.keys.items()}

    def look(i):
        g, pose = key[i][:2]
        name = TEX_LOOK.get((g, pose)) or TEX_LOOK.get((g, None))
        if name is None:
            raise SystemExit(f'particle texture group {g} pose {pose}: no shape for it in TEX_LOOK')
        return LOOKS.index(name)
    frames = [[[look(p[0]), *p[1:]] for p in row] for row in fx['frames']]
    return {'frames': frames, 'colours': fx['colours']}


def recording(rec, sid):
    m = json.loads((rec / f"{sid}.json").read_text())
    if not m.get('ok'):
        raise SystemExit(f"{sid}.json: recording failed ({m.get('error')})")
    return m


def twinkle_start(m, star):
    """The star sample re-keyed so frame 0 is the first frame the fighter is hidden: the end of its
    wait and flight (the twinkle is spawned then)."""
    return dict(m, frame=m['frame'] + star['wait'] + star['frames'])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rec', type=Path, required=True, help='record.py output for samples.json (ko.json, star.json)')
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--out', type=Path, default=DATA / 'koEffects.js')
    args = ap.parse_args()
    import isofiles
    from isofiles import dat
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = known_vanilla_iso()
        if args.iso is None:
            raise SystemExit('no vanilla ISO recorded: pass --iso')
    isofiles.open_iso(Path(str(args.iso)))
    plco, efco = dat('PlCo.dat'), dat('EfCoData.dat')
    ko, star_rec = recording(args.rec, 'ko'), recording(args.rec, 'star')
    star, screen = star_screen(plco)
    star['twinkle'] = particles(twinkle_start(star_rec, star), TWINKLE_GENS, efco, scaled=False, last=30)
    cams = {}
    zones = blast_zones(cams)
    camera = {'aspect': CAMERA_ASPECT, **camera_constants(Path(str(args.iso))), 'stages': cams}
    out = {'blast': blast(efco, plco, ko), 'zones': zones, 'flash': flash(plco, dat), 'star': star,
           'screen': screen, 'fovy': CAMERA_FOVY, 'camera': camera}
    out['blast']['particles'] = {'looks': LOOKS, **particles(ko, BLAST_GENS, efco)}
    args.out.write_text(HEADER + 'export default ' + js_stringify(out) + ';\n', encoding='utf-8', newline='\n')
    b = out['blast']
    print(f"{args.out.name}: blast {len(b['layers'])} layers, {len(b['frames'])} frames, "
          f"{sum(map(len, b['particles']['frames']))} particles over {len(b['particles']['frames'])} frames, "
          f"{len(out['zones'])} blast zones; "
          f"twinkle {len(star['twinkle']['frames'])} frames; "
          f"{len(out['flash']['enter']) + len(out['flash']['leave'])} invincibility triggers; {args.out.stat().st_size} bytes")


if __name__ == '__main__':
    main()
