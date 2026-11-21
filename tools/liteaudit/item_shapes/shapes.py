"""Item and effect shapes from the vanilla ISO models, in world units (x right, y up, front view), at full
precision, for build.py to measure: only their sizes, colours, positions and timing are written
(itemMetrics.js), never the shapes. A silhouette is the outer contour of the model rasterised in an
orthographic front view (hsdgeom.raster / silhouette), simplified by approxPolyDP."""
import math

import cv2
import numpy as np

import fighterbones as fb
import hsdgeom
import itemmodel
from isofiles import dat
from tracker.video import sprites


def group_colour(d, parts):
    """the mean shaded colour of a group of DObjs, weighted by front-view triangle area (hsdgeom.mean_colours
    over the whole group), as #rrggbb."""
    cols, ws = [], []
    W3 = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3]], np.float32)
    for p in parts:
        for t in p['tris']:
            P = np.array([v['pos'] for v in t])
            clr = np.array([v['clr'] for v in t], np.float32) if 'clr' in t[0] else None
            uv = np.array([v['uv'] for v in t], np.float32) if 'uv' in t[0] else None
            c = hsdgeom.shade(d, p['mat'], W3 @ clr if clr is not None else None,
                              W3 @ uv if uv is not None else np.zeros((4, 2)) if clr is None else None)
            cols.append(c.mean(0))
            ws.append(abs(np.cross(P[1] - P[0], P[2] - P[0])[2]) / 2 + 1e-6)
    c = np.average(np.array(cols), axis=0, weights=np.array(ws))
    return '#%02x%02x%02x' % tuple(int(x) for x in c[:3])


def sil(parts, d, ppu=40, eps=0.08, cut=32):
    """outer polygons of `parts` (alpha >= cut), largest first."""
    lo, hi = hsdgeom.bounds(parts)
    f, W, H = hsdgeom.ortho(lo[0] - 0.5, hi[0] + 0.5, lo[1] - 0.5, hi[1] + 0.5, ppu)
    img, cov = hsdgeom.raster(d, parts, f, W, H, ss=1, alpha_cut=cut)
    polys = hsdgeom.silhouette(cov, lo[0] - 0.5, hi[1] + 0.5, ppu, eps_units=eps, min_area_units=0.05)
    return [[list(map(float, p)) for p in poly] for poly in polys]


# ---------------------------------------------------------------- Onett cars
CARS = {0: 11, 1: 1, 2: 6, 3: 16}           # gronett.c car_jobjs: Ground_801C3FA4 index = DFS index


def cars():
    """GrOt.dat map_head group 3, car k = item kind 160 state k + 2: outline relative to the car joint (= the
    item's x, y) in world units (the ground wrapper joint scales the group by grGroundParam +0), the
    per-DObj mean colours and the two wheel centres."""
    d = dat('GrOt.dat')
    S = d.f(d.root['grGroundParam'])
    head = d.root['map_head']
    root = d.p(d.p(head + 8) + 3 * 0x34)
    js = hsdgeom.joints(d, root)
    out = []
    for car, joint in CARS.items():
        ov = {0: dict(t=[0.0, 0.0, 0.0]), 1: dict(r=[0.0, 0.0, 0.0])}
        parts, _ = hsdgeom.model(d, js[joint]['off'], parent=np.diag([S, S, S, 1.0]), override=ov, siblings=False)
        lo, hi = hsdgeom.bounds(parts)
        ppu = 40
        f, W, H = hsdgeom.ortho(lo[0] - 1, hi[0] + 1, lo[1] - 1, hi[1] + 1, ppu)
        img, cov = hsdgeom.raster(d, parts, f, W, H, ss=2)
        polys = hsdgeom.silhouette(cov, lo[0] - 1, hi[1] + 1, ppu, eps_units=0.15)
        wheels = [[round(v * S, 3) for v in js[k]['t'][:2]] for k in range(joint + 2, joint + 4)]
        out.append(dict(item_state=car + 2, outline=polys[0], colours=[c['hex'] for c in hsdgeom.mean_colours(d, parts)],
                        wheels=wheels))
    return out


# ---------------------------------------------------------------- Ice Climbers' ice, Samus' missile
def ice():
    """kind 106 (PlPp.dat item 0): joint 1 spins about Y, 2 pi per 60 frames (state anim 0). Outline every
    5 frames of the spin, anchor = item x,y; colour = the mean colour of the last phase's mesh."""
    d, art = itemmodel.fighter_article('PlPp.dat', 0)
    phases = {}
    for k in range(12):
        parts, _, _ = itemmodel.item_parts(d, art, pos=(0, 0, 0), facing=1, anim=0, frame=k * 5.0)
        phases[k * 5] = sil(parts, d)[0]
    return dict(phases=phases, colours=[c['hex'] for c in hsdgeom.mean_colours(d, parts)])


def missile():
    """kind 95 (PlSs.dat item 2), facing +1 (nose +x), level; colours of the shell's two DObjs (joint 2)."""
    d, art = itemmodel.fighter_article('PlSs.dat', 2)
    parts, _, _ = itemmodel.item_parts(d, art, pos=(0, 0, 0), facing=1, anim=0, frame=0)
    cols = {(c['joint'], c['dobj']): c['hex'] for c in hsdgeom.mean_colours(d, parts)}
    return dict(poly=sil(parts, d, ppu=60, eps=0.04)[0], body=cols[(2, 0)], nose=cols[(2, 1)])


# ---------------------------------------------------------------- Peach's turnip
HELD_STATES = (352, 353, 14, 15, 20, 21, 25, 29, 39)   # SpecialLw, SpecialAirLw, Wait1, WalkSlow, Dash, Run, JumpF, Fall, Squat


def turnip():
    """kind 99 (PlPe.dat item 1), scale ItemAttr +0x60 (1.3). Flying: facing +1, spin 0, origin = item x,y (top
    of the bulb, base of the leaves); outline and bulb (joint 3) outline. Held: per Peach action frame, the
    turnip origin (item joint 2) and tilt with item joint 1 riding Peach's hold part (position + orientation),
    relative to Peach's position, x along facing."""
    d, art = itemmodel.fighter_article('PlPe.dat', 1)
    info = itemmodel.attr_info(d, art)
    root = d.p(d.p(art + 0x10))
    js0 = hsdgeom.joints(d, root)
    sc = info['scale']                       # x Player model scale (1 in VS) -> 1.3

    # flying: anim 2 (thrown) has no AnimJoint -> pose from anim 0 frame 0; the face (anim 0) shows the bulb
    tr = itemmodel.anim_tracks(d, itemmodel.state_anim(d, art, 0)['animjoint'])
    ov = itemmodel.anim_override(d, js0, tr, 0)
    hide = set()
    for j, node in zip(js0, tr):
        if 12 in node:                       # BRANCH visibility: value > 0.5 visible
            if sprites._track_value(node[12], 0) <= 0.5:
                hide.add(j['index'])
            else:
                ov.setdefault(j['index'], {})['show'] = True
    ov[0] = dict(s=[1, 1, 1], r=[0, 0, 0], t=[0, 0, 0])
    M = hsdgeom.srt([sc] * 3, [0, math.pi / 2 * 1.0, 0.0], [0, 0, 0])
    parts, _ = hsdgeom.model(d, root, override=ov, parent=M, with_hidden=True)
    parts = [p for p in parts if (ov.get(p['joint'], {}).get('show') or (not p['hidden'] and p['joint'] not in hide))
             and p['joint'] not in hide]
    poly = sil(parts, d, ppu=50, eps=0.06)[0]
    bulb = sil([p for p in parts if p['joint'] == 3], d, ppu=50, eps=0.06)[0]
    leaves_colour = group_colour(d, [p for p in parts if p['joint'] == 2])
    bulb_colour = group_colour(d, [p for p in parts if p['joint'] == 3])

    hp = fb.hold_part('Pe')

    def held_origin(st, fr):
        B = fb.world('Pe', st, fr, pos=(0, 0), facing=1.0)[hp].copy()
        for k in range(3):                   # RHaveN cancels the fighter model scale (8007F6A4)
            B[:3, k] /= np.linalg.norm(B[:3, k])
        J2 = B @ np.diag([sc, sc, sc, 1.0]) @ hsdgeom.srt([1, 1, 1], js0[2]['r'], js0[2]['t'])
        up = J2[:3, 1] / np.linalg.norm(J2[:3, 1])
        return [round(J2[0, 3], 2), round(J2[1, 3], 2), round(math.degrees(math.atan2(-up[0], up[1])), 1)]

    held = {}
    for st in HELD_STATES:
        end, _, _ = fb.tracks('Pe', st)
        held[st] = [held_origin(st, fr) for fr in range(int(end) + 1)]
    return dict(poly=poly, bulb=bulb, leaves_colour=leaves_colour, bulb_colour=bulb_colour, held=held)


# ---------------------------------------------------------------- Yoshi's egg
def egg():
    """ftCo_YoshiEgg.c: PlYs.dat ftData+0x48 entry 3 (an HSD_Joint), its child joint pinned to the victim's
    TransN. Outline at unit scale relative to the pinned joint; the victim's size (ftCo_DatAttrs +0xBC) per
    fighter code; growth from (1 - Yoshi attr x1C) to 1 over Yoshi attr x20 frames (ftCo_800BBCC0)."""
    ys = dat('PlYs.dat')
    ft = next(v for k, v in ys.roots if k.startswith('ftData'))
    root = ys.p(ys.p(ft + 0x48) + 12)
    da = ys.p(ft + 4)
    parts, _ = hsdgeom.model(ys, root, override={0: dict(t=[0, 0, 0]), 1: dict(t=[0, 0, 0])})
    lo, hi = hsdgeom.bounds(parts)
    ppu = 60
    f, W, H = hsdgeom.ortho(lo[0] - 0.2, hi[0] + 0.2, lo[1] - 0.2, hi[1] + 0.2, ppu)
    img, cov = hsdgeom.raster(ys, parts, f, W, H, ss=2)
    outline = hsdgeom.silhouette(cov, lo[0] - 0.2, hi[1] + 0.2, ppu, eps_units=0.05)[0]
    sizes = {}
    for code in fb.CODES:
        d = dat(f'Pl{code}.dat')
        f2 = next(v for k, v in d.roots if k.startswith('ftData'))
        sizes[code] = round(d.f(d.p(f2) + 0xBC), 3)
    return dict(outline=outline, sizes=sizes, x1C=ys.f(da + 0x1C), x20=ys.f(da + 0x20))


# ---------------------------------------------------------------- Mario's / Luigi's fireball
FIREBALLS = ((105, 'PlLg.dat'), (48, 'PlMr.dat'))


def fireball(fname):
    """A camera-facing quad pair on the root joint, spun about the view axis by the item spin. From the core
    quad (DObj 0) unspun: the bright core circle [x, y, r] (minimum enclosing circle of the pixels brighter
    than 200 x alpha) and the flame outline (alpha > 0.5), relative to the item x,y."""
    d, art = itemmodel.fighter_article(fname, 0)
    root = d.p(d.p(art + 0x10))
    parts, _ = hsdgeom.model(d, root, override={0: dict(s=[1, 1, 1], r=[0, 0, 0], t=[0, 0, 0])})
    core = [p for p in parts if p['dobj'] == 0]
    ppu = 40
    lo, hi = hsdgeom.bounds(core)
    f, W, H = hsdgeom.ortho(lo[0], hi[0], lo[1], hi[1], ppu)
    img, cov = hsdgeom.raster(d, core, f, W, H, ss=1, alpha_cut=1)
    a = img[..., 3].astype(float) / 255
    lum = img[..., :3].astype(float).mean(2) * a
    hot = np.where(lum > 200, lum, 0)
    cs, _ = cv2.findContours(((a > 0.5) * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    poly = cv2.approxPolyDP(c, 0.12 * ppu, True)[:, 0, :]
    poly = [(round(lo[0] + (x + 0.5) / ppu, 2), round(hi[1] - (y + 0.5) / ppu, 2)) for x, y in poly]
    (cx, cy), r = cv2.minEnclosingCircle(np.argwhere(hot > 0)[:, ::-1].astype(np.float32))
    return dict(core=[round(lo[0] + cx / ppu, 2), round(hi[1] - cy / ppu, 2), round(r / ppu, 2)], flame=poly)


# ---------------------------------------------------------------- Fire Fox / Fire Bird flames
def effect_parts(idx, frame):
    """EfFxData.dat effFoxDataTable model `idx` posed by its own AnimJoint (envelope skinned), BRANCH
    visibility and MatAnim at effect frame `frame`; effect-local world units."""
    d = dat('EfFxData.dat')
    m = d.root['effFoxDataTable'] + 8 + idx * 0x14
    root, aj, ma = d.p(m + 4), d.p(m + 8), d.p(m + 0xC)
    js = hsdgeom.joints(d, root)
    ov = itemmodel.anim_override(d, js, itemmodel.anim_tracks(d, aj), frame) if aj is not None else {}
    hide, show = set(), set()               # BRANCH visibility (track 12)
    for j, node in zip(js, itemmodel.anim_tracks(d, aj) if aj else []):
        if 12 in node:
            (show if sprites._track_value(node[12], frame) > 0.5 else hide).add(j['index'])
    ov.setdefault(0, {})
    parts, _ = hsdgeom.model(d, root, override=ov, parent=np.eye(4), with_hidden=True)
    keep = [p for p in parts if (p['joint'] in show) or (not p['hidden'] and p['joint'] not in hide)]
    if ma is not None:
        keep = itemmodel.apply_matanim(keep, itemmodel.matanim_state(d, ma, frame))
    return keep


def flames():
    """Model 3 (charge, efSync 1163, attached by position to TransN): per effect frame 0..18, the outline
    (alpha >= 48) of the crown / column / ring joint groups, effect-local world units."""
    d = dat('EfFxData.dat')

    def outlines(idx, frames, groups, cut=48, ppu=12):
        out = {}
        for fr in frames:
            parts = effect_parts(idx, float(fr))
            row = {}
            for name, jset in groups.items():
                ps = [p for p in parts if p['joint'] in jset]
                lo, hi = hsdgeom.bounds(ps)
                f, W, H = hsdgeom.ortho(lo[0] - 1, hi[0] + 1, lo[1] - 1, hi[1] + 1, ppu)
                img, cov = hsdgeom.raster(d, ps, f, W, H, ss=1, alpha_cut=cut)
                polys = hsdgeom.silhouette(cov, lo[0] - 1, hi[1] + 1, ppu, eps_units=0.35, min_area_units=0.5)
                row[name] = [list(map(float, pt)) for pt in polys[0]]
            out[fr] = row
        return out

    return outlines(3, range(0, 19), {'crown': {1, 2, 3}, 'column': {4, 5, 6}, 'ring': {8}})


def raster_fx(d, parts, to_screen, W, H, ss=2):
    """Additive render (GX blend SRCALPHA, ONE): per pixel the sum of colour x alpha (H x W x 3)."""
    Ws, Hs = W * ss, H * ss
    acc = np.zeros((Hs, Ws, 3), np.float32)
    for part in parts:
        for tri in part['tris']:
            P = np.array([v['pos'] for v in tri])
            S, Z = to_screen(P)
            S = S * ss
            (x0, y0), (x1, y1), (x2, y2) = S
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue
            minx, maxx = max(int(S[:, 0].min()), 0), min(int(S[:, 0].max()) + 1, Ws)
            miny, maxy = max(int(S[:, 1].min()), 0), min(int(S[:, 1].max()) + 1, Hs)
            if minx >= maxx or miny >= maxy:
                continue
            ys, xs = np.mgrid[miny:maxy, minx:maxx]
            xs = xs + 0.5
            ys = ys + 0.5
            w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
            w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
            w2 = 1 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not m.any():
                continue
            W3 = np.stack([w0[m], w1[m], w2[m]], 1)
            clr = np.array([v.get('clr', (255, 255, 255, 255)) for v in tri], np.float32) if 'clr' in tri[0] else None
            uv = np.array([v.get('uv', (0, 0)) for v in tri], np.float32) if 'uv' in tri[0] else None
            c = hsdgeom.shade(d, part['mat'], W3 @ clr if clr is not None else None,
                              W3 @ uv if uv is not None else (np.zeros((W3.shape[0], 2)) if clr is None else None))
            a = c[:, 3] / 255
            iy, ix = np.nonzero(m)
            acc[miny:maxy, minx:maxx][iy, ix] += c[:, :3] * a[:, None]
    if ss > 1:
        acc = acc.reshape(H, ss, W, ss, 3).mean((1, 3))
    return acc


TRAVEL_OUTER, TRAVEL_CORE, TRAVEL_PPU = 60, 250, 8


def travel_plume():
    """Model 4 (travel, efSync 1164, on HipN) joints 3/4 (joint 2, the billboard glow, left out) seen from the
    camera: the effect root turns local z into the stage plane across the travel line and local y along it, so
    the outline is the side view (z, y). The materials blend additively, so the outline is where the summed
    colour x alpha reaches 60 (outer) or 250 (core, saturated), closed by 1 unit. Per effect frame 0..19:
    {outer, core} as [px = local z, py = local y (+ = travel)]."""
    d = dat('EfFxData.dat')
    ppu = TRAVEL_PPU

    def outline(mask, zmin, ymax):
        r = max(1, int(round(1.0 * ppu)))
        m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        ps = hsdgeom.silhouette(m > 0, zmin, ymax, ppu, eps_units=0.35, min_area_units=1.0)
        return ps[0] if ps else []

    frames = []
    for k in range(20):
        parts = [p for p in effect_parts(4, float(k)) if p['joint'] in (3, 4)]
        vs = np.array([v['pos'] for p in parts for t in p['tris'] for v in t])
        zmin, zmax = vs[:, 2].min() - 2, vs[:, 2].max() + 2
        ymin, ymax = vs[:, 1].min() - 2, vs[:, 1].max() + 2
        W, H = int(np.ceil((zmax - zmin) * ppu)), int(np.ceil((ymax - ymin) * ppu))

        def side(P, zmin=zmin, ymax=ymax):
            return np.stack([(P[:, 2] - zmin) * ppu, (ymax - P[:, 1]) * ppu], 1), P[:, 0]
        lum = raster_fx(d, parts, side, W, H, ss=2).max(2)
        frames.append(dict(outer=outline(lum >= TRAVEL_OUTER, zmin, ymax), core=outline(lum >= TRAVEL_CORE, zmin, ymax)))
    return frames


# ---------------------------------------------------------------- polylines
def rdp(pts, eps):
    """Ramer-Douglas-Peucker on an open polyline (numpy)."""
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts.tolist()
    a, b = pts[0], pts[-1]
    ab = b - a
    n = np.hypot(*ab) or 1e-9
    q = pts - a
    dist = np.abs(ab[0] * q[:, 1] - ab[1] * q[:, 0]) / n
    i = int(np.argmax(dist))
    if dist[i] > eps:
        return rdp(pts[:i + 1], eps)[:-1] + rdp(pts[i:], eps)
    return [a.tolist(), b.tolist()]


# ---------------------------------------------------------------- Ness' PK Thunder, Pikachu's Thunder
def pk_trail():
    """PK Thunder tail pieces (kinds 70-73, PlNs.dat items 4-7): for each distinct MatAnim texture over state anim
    0 frames 0..7, the brightest row per pixel column (intensity = mean RGB x alpha >= 80) of the front view
    (facing +1, travel +x, item point at x = 0, the piece spanning x -4..0), simplified (RDP 0.12); the mean
    colour of the pixels brighter than 120. {kind: [{line, colour}]}."""
    ppu = 40
    out = {}
    for art_i, kind in ((4, 70), (5, 71), (6, 72), (7, 73)):
        d, art = itemmodel.fighter_article('PlNs.dat', art_i)
        sa = itemmodel.state_anim(d, art, 0)
        out[kind] = []
        seen = set()
        for af in range(0, 8):
            parts, _, _ = itemmodel.item_parts(d, art, pos=(0, 0, 0), facing=1, anim=0, frame=float(af))
            st = itemmodel.matanim_state(d, sa['matanim'], float(af))
            key = str(st[(1, 0)]['tex'])
            if key in seen:
                continue
            seen.add(key)
            parts = itemmodel.apply_matanim(parts, st)
            f, W, H = hsdgeom.ortho(-4.5, 0.5, -3, 3, ppu)
            img, cov = hsdgeom.raster(d, parts, f, W, H, ss=1, alpha_cut=1)
            inten = img[..., :3].astype(float).mean(2) * img[..., 3] / 255.0
            pts = []
            for c in range(W):
                col = inten[:, c]
                r = int(np.argmax(col))
                if col[r] < 80:
                    continue
                pts.append((-4.5 + (c + 0.5) / ppu, 3 - (r + 0.5) / ppu))
            rgb = img[..., :3][inten > 120].mean(0).round(0).tolist() if (inten > 120).any() else None
            out[kind].append(dict(line=[[round(x, 2), round(y, 2)] for x, y in rdp(pts, 0.12)], colour=rgb))
    return out


def bolt():
    """Pikachu's Thunder bolt (kinds 81/82, PlPk.dat item 0): one quad (u 0..1 -> x -10..10, v 0..1 -> y 0..-40,
    the item point at the top centre) with MatAnim textures. For each distinct texture over state anim 0 frames
    0..7: the centre line of the bright stroke per texel row (intensity >= 60, run above half its peak),
    simplified (RDP 0.12); the stroke width (median run width) and the glow's x extent (intensity > 25)."""
    d, art = itemmodel.fighter_article('PlPk.dat', 0)
    sa = itemmodel.state_anim(d, art, 0)
    out = []
    seen = set()
    for af in range(0, 8):
        st = itemmodel.matanim_state(d, sa['matanim'], float(af))
        img_off, tl = st[(0, 0)]['tex'][0]
        if (img_off, tl) in seen:
            continue
        seen.add((img_off, tl))
        tex = d.texture(img_off, tl)
        H, W = tex.shape[:2]
        inten = tex[..., :3].mean(2) * tex[..., 3] / 255.0
        pts, widths = [], []
        for r in range(H):
            row = inten[r]
            c = int(np.argmax(row))
            if row[c] < 60:
                continue
            lo = c                      # the contiguous run around c above half the peak
            while lo - 1 >= 0 and row[lo - 1] > 0.5 * row[c]:
                lo -= 1
            hi = c
            while hi + 1 < W and row[hi + 1] > 0.5 * row[c]:
                hi += 1
            u = (lo + hi + 1) / 2 / W
            v = (r + 0.5) / H
            pts.append((round(-10 + 20 * u, 2), round(-40 * v, 2)))
            widths.append((hi - lo + 1) / W * 20)
        glow = np.nonzero(inten.max(0) > 25)[0]
        out.append(dict(line=[[round(x, 2), round(y, 2)] for x, y in rdp(pts, 0.12)],
                        stroke=round(float(np.median(widths)), 2),
                        glow_x=[round(-10 + 20 * glow.min() / W, 2), round(-10 + 20 * (glow.max() + 1) / W, 2)]))
    return out


# ---------------------------------------------------------------- Yoshi's Story Shy Guy
def shy_classes(t):
    """per texel classes of the Shy Guy sprite: opaque, mask (filled convex hull of the light-grey blob on the
    right), pupil (dark inside the mask), blue feet, propeller, red body, other."""
    rgb = t[..., :3].astype(np.float32) / 255
    A = t[..., 3]
    op = A >= 128
    hsv = cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    h, s, v = hsv[..., 0] * 2, hsv[..., 1] / 255, hsv[..., 2] / 255
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    blue = op & (h > 200) & (h < 260) & (s > 0.4)
    prop = op & (h > 35) & (h < 80) & (s > 0.3) & (v > 0.25)
    grey = op & (s < 0.28) & (v > 0.42)
    dark = op & (v < 0.25)
    n, lab, st, cen = cv2.connectedComponentsWithStats(grey.astype(np.uint8))
    W = t.shape[1]
    cand = [i for i in range(1, n) if cen[i][0] > W * 0.6]
    mk = np.zeros_like(op)
    if cand:
        i = max(cand, key=lambda i: st[i, cv2.CC_STAT_AREA])
        mk = lab == i
        ys_, xs_ = np.nonzero(mk)
        hull = cv2.convexHull(np.stack([xs_, ys_], 1).astype(np.int32))
        filled = np.zeros(mk.shape, np.uint8)
        cv2.fillConvexPoly(filled, hull, 1)
        mk = filled.astype(bool) & op
    pupil = mk & dark
    red = op & ~blue & ~prop & ~mk & (R > 0.35) & (G < 0.6 * R) & (B < 0.6 * R)
    other = op & ~(blue | prop | mk | red)
    return dict(op=op, black=pupil, mask=mk, blue=blue, red=red, prop=prop, other=other)


def shy_guy():
    """Kind 210 (It_Kind_Heiho, GrSt.dat itemdata): a camera-facing quad with a 3-image MatAnim texture.
    From the first image (state anim 0, frame 0), facing +1 as stored, item scale (ItemAttr +0x60) applied,
    relative to the quad centre: the body outline (red, mask, feet and other texels, opened, the largest
    piece, closed) and the bounding boxes of the mask, the pupil, the feet and the propeller as ellipses
    [cx, cy, rx, ry]."""
    d = dat('GrSt.dat')
    lst, i = d.root['itemdata'], 0
    while d.u(d.p(lst + 4 * i)) != 210:
        i += 1
    art = d.p(d.p(lst + 4 * i) + 4)
    root = d.p(d.p(art + 0x10))
    quad = hsdgeom.model(d, root, override={0: dict(s=[1, 1, 1], r=[0, 0, 0], t=[0, 0, 0])})[0]
    lo, hi = hsdgeom.bounds(quad)
    qx, qy = hi[0], hi[1]                                # quad half size, model units (3 places)
    scale = round(itemmodel.attr_info(d, art)['scale'], 3)
    st = itemmodel.matanim_state(d, itemmodel.state_anim(d, art, 0)['matanim'], 0.0)
    img = next(iter(st[(quad[0]['joint'], quad[0]['dobj'])]['tex'].values()))[0]
    t = d.texture(img, None).astype(np.uint8)
    H, W = t.shape[:2]

    def to_world(px, py):
        return round(float((-qx + (px + 0.5) / W * 2 * qx) * scale), 2), round(float((qy - (py + 0.5) / H * 2 * qy) * scale), 2)

    def bbox(mask):
        ys, xs = np.nonzero(mask)
        x0, y0 = to_world(xs.min() - 0.5, ys.max() + 0.5)
        x1, y1 = to_world(xs.max() + 0.5, ys.min() - 0.5)
        return [x0, y0, x1, y1]

    def ellipse(b):
        return [round((b[0] + b[2]) / 2, 2), round((b[1] + b[3]) / 2, 2), round((b[2] - b[0]) / 2, 2), round((b[3] - b[1]) / 2, 2)]

    c = shy_classes(t)
    # the feet: the blue texels in the left 55% of the image (the few others lie inside the mask)
    feet = c['blue'] & (np.arange(W)[None, :] < W * 0.55)
    P = 8
    body = c['red'] | c['mask'] | c['blue'] | c['other']
    body = np.pad(body, P).astype(np.uint8)
    body = cv2.morphologyEx(body, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(body)
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    body = (lab == big).astype(np.uint8)
    body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    cs, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    body = np.zeros_like(body)
    cv2.drawContours(body, cs, -1, 1, -1)
    body = body[P:-P, P:-P].astype(bool) & c['op']
    body = cv2.morphologyEx(np.pad(body, P).astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))[P:-P, P:-P].astype(bool)
    cs, _ = cv2.findContours(body.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = []
    for cont in sorted(cs, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(cont) >= 6:
            outline = [to_world(x, y) for x, y in cv2.approxPolyDP(cont, 0.9, True)[:, 0, :]]
            break
    return dict(body=outline, mask=ellipse(bbox(c['mask'])), pupil=ellipse(bbox(c['black'])), feet=ellipse(bbox(feet)),
                propeller=ellipse(bbox(c['prop'])))


def randall():
    """Yoshi's Story's Randall (GrSt.dat map_head group 2): where its sprite sits on the moving platform.
    The group's collision link (map group +0x20: area, -1, joint) ties collision area 0's one floor line
    to joint 1, which also carries the cloud's textured quad (UV 0..1, image upright), so both are in
    that joint's space whatever the path and scale do to it. Returns the quad's width as a multiple of
    the line's, its centre's offset from the line's middle as a fraction of the line's width, and where
    the line crosses the quad, as a fraction of the quad's height from its top, and the quad's height over its
    width."""
    d = dat('GrSt.dat')
    mh = d.root['map_head']
    g = d.p(mh + 0x08) + 2 * 0x34
    link = d.p(g + 0x20)
    area, joint = d.u16(link), d.u16(link + 4)
    root = d.p(g)
    js = hsdgeom.joints(d, root)
    parts = [q for q in hsdgeom.model(d, root, parent=np.eye(4), with_hidden=True)[0] if q['joint'] == joint]
    J = next(j for j in js if j['index'] == joint)['world']
    P = np.array([(np.linalg.inv(J) @ np.array([*v['pos'], 1.0]))[:3] for q in parts for t in q['tris'] for v in t])
    x0, x1, y0, y1 = P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max()
    cd = d.root['coll_data']
    verts, lines, mj = d.p(cd), d.p(cd + 0x08), d.p(cd + 0x24) + area * 0x28
    first, count = d.u16(mj), d.u16(mj + 2)              # the area's floor lines
    assert count == 1, f'Randall area {area}: {count} floor lines'
    ln = lines + first * 0x10
    a, b = [(d.f(verts + 8 * i), d.f(verts + 8 * i + 4)) for i in (d.u16(ln), d.u16(ln + 2))]
    lw, lx, ly = abs(b[0] - a[0]), (a[0] + b[0]) / 2, a[1]
    return {'w': round(float((x1 - x0) / lw), 4), 'dx': round(float(((x0 + x1) / 2 - lx) / lw), 4),
            'line': round(float((y1 - ly) / (y1 - y0)), 4), 'h': round(float((y1 - y0) / (x1 - x0)), 4)}


# ---------------------------------------------------------------- revival platform, blaster shot
PLATFORM_FLICKER = {3, 4, 5}   # joint 3's subtree: its BRANCH track shows it on even platform-anim frames only
PLATFORM_GLOW = {6}            # the translucent vertical glow above the deck


def _round2(v):
    """Math.round(v * 100) / 100 (ties toward +infinity), as the rest of itemMetrics.js is rounded."""
    x = v * 100
    r = math.ceil(x)
    if r - 0.5 > x:
        r -= 1
    return r / 100


def symmetric(poly):
    """A left-right symmetric outline from a traced one: each point is paired with the trace point nearest to
    its mirror image (the pairing must be one-to-one, a point on the axis pairs with itself), averaged with
    that partner's mirror image and rounded to 2 decimals (|x| rounded, so pairs stay exact mirrors).
    Wound clockwise (y up), starting from the trace's first point."""
    pts = [(float(x), float(y)) for x, y in poly]
    partner = [min(range(len(pts)), key=lambda j: math.hypot(pts[j][0] + x, pts[j][1] - y)) for x, y in pts]
    assert all(partner[partner[i]] == i for i in range(len(pts))), 'trace is not mirror-symmetric'
    out = []
    for i, (x, y) in enumerate(pts):
        px, py = pts[partner[i]]
        ax = (x - px) / 2
        out.append([math.copysign(_round2(abs(ax)), ax) + 0.0, _round2((y + py) / 2)])
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(out, out[1:] + out[:1]))
    return out if area < 0 else out[:1] + out[1:][::-1]


def revival_deck():
    """The revival platform (PlCo.dat ftLoadCommonData[8]: HSD_Joint + AnimJoint), scale 1, at the platform
    origin (the fighter's feet), front view: its outline on an odd platform-anim frame (frame 1: no bulb,
    joint 3's subtree hidden) without the glow, traced at 40 px/unit (simplified 0.12), made symmetric."""
    d = dat('PlCo.dat')
    plat = d.p(d.root['ftLoadCommonData'] + 4 * 8)
    joint, aj = d.p(plat), d.p(plat + 4)
    ov = itemmodel.anim_override(d, hsdgeom.joints(d, joint), itemmodel.anim_tracks(d, aj), 1.0)
    ov[0] = dict(s=[1.0] * 3, r=[0, 0, 0], t=[0.0, 0.0, 0.0])
    parts, _ = hsdgeom.model(d, joint, override=ov)
    parts = [p for p in parts if p['joint'] not in PLATFORM_GLOW and p['joint'] not in PLATFORM_FLICKER]
    lo, hi = hsdgeom.bounds(parts)
    ppu = 40
    f, W, H = hsdgeom.ortho(lo[0] - 0.5, hi[0] + 0.5, lo[1] - 0.5, hi[1] + 0.5, ppu)
    img, cov = hsdgeom.raster(d, parts, f, W, H, ss=2, alpha_cut=8)
    trace = hsdgeom.silhouette(cov, lo[0] - 0.5, hi[1] + 0.5, ppu, eps_units=0.12, min_area_units=0.05)[0]
    return symmetric(trace), trace


def respawn_platform_scales():
    """ftCo_DatAttrs +0x160 (respawn_platform_scale) per fighter code, 4 places."""
    out = {}
    for code in fb.CODES:
        d = dat(f'Pl{code}.dat')
        attr = d.p(next(v for k, v in d.roots if k.startswith('ftData')))
        out[code] = round(d.f(attr + 0x160), 4)
    return out


def blaster_shells():
    """Falco's blaster shot (PlFc.dat item 0, model at the item root, nose at z = 0, tail toward -z): per
    DObj shell, the radius around the z axis, the z extent, the z values at the full radius and the vertex
    colours (sorted)."""
    d, art = itemmodel.fighter_article('PlFc.dat', 0)
    root = d.p(d.p(art + 0x10))
    parts, _ = hsdgeom.model(d, root, override={0: dict(s=[1, 1, 1], r=[0, 0, 0], t=[0, 0, 0])})
    out = []
    for p in parts:
        P = np.array([v['pos'] for t in p['tris'] for v in t])
        C = np.array([v.get('clr', (255,) * 4) for t in p['tris'] for v in t])
        r = np.hypot(P[:, 0], P[:, 1])
        out.append(dict(r=round(r.max(), 3), z=[round(P[:, 2].min(), 3), round(P[:, 2].max(), 3)],
                        z_at_rmax=sorted(set(np.round(P[r > r.max() - 1e-3, 2], 3).tolist())),
                        rgba=sorted(set(tuple(int(round(x)) for x in c) for c in C))))
    return out
