"""HSD model geometry for the item shapes: JObj tree with bind SRT (optionally overridden per joint),
DObj triangles with per-vertex position / colour / UV, materials and decoded textures, envelope
skinning, a numpy z-buffer rasteriser (any 4x4 projection), and a silhouette tracer (cv2 contours)
in model units.

Offsets are data-section relative (FighterNumericDat / datprobe convention). Needs app/backend on
sys.path (build.py sets it)."""
import math
import struct
from pathlib import Path

import numpy as np

from shared.rendering import datprobe

JOBJ_HIDDEN, JOBJ_PTCL, JOBJ_INSTANCE, JOBJ_SPLINE = 0x10, 0x20, 0x1000, 0x4000


class Dat(datprobe.DatFile):
    """datprobe.DatFile from bytes, plus float/short readers and root lookup."""

    def __init__(self, raw, name='?'):
        self.path = Path(name)
        self.raw = raw
        (self.file_size, self.data_size, self.reloc_count, self.root_count, self.ref_count) = struct.unpack_from('>IIIII', raw, 0)
        reloc_start = 0x20 + self.data_size
        self.relocs = set(struct.unpack_from(f'>{self.reloc_count}I', raw, reloc_start))
        roots_start = reloc_start + self.reloc_count * 4
        strings_start = roots_start + (self.root_count + self.ref_count) * 8
        self.roots = []
        for i in range(self.root_count):
            off, so = struct.unpack_from('>II', raw, roots_start + i * 8)
            end = raw.index(b'\0', strings_start + so)
            self.roots.append((raw[strings_start + so:end].decode('ascii', 'replace'), off))
        self.root = dict(self.roots)
        self._tex = {}

    def f(self, off):
        return struct.unpack_from('>f', self.raw, 0x20 + off)[0]

    def u(self, off):
        return self.u32(off)

    def h(self, off):
        return struct.unpack_from('>h', self.raw, 0x20 + off)[0]

    def b(self, off):
        return self.raw[0x20 + off]

    def p(self, off):
        """pointer or None"""
        return self.ptr(off)

    def texture(self, img_off, tlut_off):
        key = (img_off, tlut_off)
        if key not in self._tex:
            img = self.image_at(img_off)
            tl = self.tlut_at(tlut_off) if tlut_off is not None else None
            try:
                rows = datprobe.decode_image(img, tl)
                self._tex[key] = np.array(rows, dtype=np.float32)
            except Exception as e:  # noqa: BLE001
                print('texture decode failed', hex(img_off), e)
                self._tex[key] = np.full((1, 1, 4), 255, np.float32)
        return self._tex[key]


# --------------------------------------------------------------------------- matrices
def srt(s, r, t):
    cx, sx = math.cos(r[0]), math.sin(r[0])
    cy, sy = math.cos(r[1]), math.sin(r[1])
    cz, sz = math.cos(r[2]), math.sin(r[2])
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = Rz @ Ry @ Rx @ np.diag(s)
    m[:3, 3] = t
    return m


def joint_srt(d, j):
    return ([d.f(j + 0x20 + 4 * i) for i in range(3)], [d.f(j + 0x14 + 4 * i) for i in range(3)],
            [d.f(j + 0x2C + 4 * i) for i in range(3)])


def joints(d, root, parent=None, override=None, siblings=True):
    """DFS preorder list of joints: dict(off, index, parent, flags, s, r, t, world(bind or overridden)).
    override: {index or off: dict(s=..., r=..., t=...)} replacing those channels."""
    out = []
    override = override or {}
    base = np.eye(4) if parent is None else parent

    def walk(j, pi, pm, top=False):
        while j:
            i = len(out)
            s, r, t = joint_srt(d, j)
            o = override.get(i) or override.get(j) or {}
            s, r, t = o.get('s', s), o.get('r', r), o.get('t', t)
            m = o['world'] if 'world' in o else pm @ srt(s, r, t)
            flags = d.u(j + 4)
            out.append(dict(off=j, index=i, parent=pi, flags=flags, s=s, r=r, t=t, world=m))
            c = d.p(j + 8)
            if c and not flags & JOBJ_INSTANCE:
                walk(c, i, m)
            if top and not siblings:
                break
            j = d.p(j + 0x0C)
    walk(root, -1, base, True)
    return out


# --------------------------------------------------------------------------- vertices
CSIZE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4}
CFMT = {0: '>B', 1: '>b', 2: '>H', 3: '>h', 4: '>f'}
CLRSIZE = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}


def read_clr(buf, q, ctype):
    if ctype == 0:
        v = struct.unpack_from('>H', buf, q)[0]
        return (((v >> 11) & 31) * 255 / 31, ((v >> 5) & 63) * 255 / 63, (v & 31) * 255 / 31, 255)
    if ctype == 1:
        return (buf[q], buf[q + 1], buf[q + 2], 255)
    if ctype == 2:
        return (buf[q], buf[q + 1], buf[q + 2], 255)
    if ctype == 3:
        v = struct.unpack_from('>H', buf, q)[0]
        return tuple(((v >> s) & 15) * 17 for s in (12, 8, 4, 0))
    if ctype == 4:
        r6 = buf[q] >> 2
        g6 = ((buf[q] & 3) << 4) | (buf[q + 1] >> 4)
        b6 = ((buf[q + 1] & 0xF) << 2) | (buf[q + 2] >> 6)
        a6 = buf[q + 2] & 0x3F
        return tuple(v * 255 / 63 for v in (r6, g6, b6, a6))
    return (buf[q], buf[q + 1], buf[q + 2], buf[q + 3])


def vtx_attrs(d, pobj):
    attrs = []
    a = d.p(pobj + 8)
    while a is not None and d.u(a) != 0xFF and len(attrs) < 26:
        attrs.append(dict(name=d.u(a), type=d.u(a + 4), cnt=d.u(a + 8), ctype=d.u(a + 12), frac=d.b(a + 16),
                          stride=d.u16(a + 18), arr=d.p(a + 20)))
        a += 24
    return attrs


def _value(d, x, buf, q):
    """(value, size consumed in the display list) for one attribute of one vertex."""
    name, typ = x['name'], x['type']
    if typ == 0:
        return None, 0
    if name <= 8:                      # PNMTXIDX / TEXnMTXIDX: direct u8
        return buf[q], 1
    if typ == 1:
        src, at = buf, q
    else:
        idx = buf[q] if typ == 2 else struct.unpack_from('>H', buf, q)[0]
        src, at = d.raw, 0x20 + x['arr'] + idx * x['stride']
    if name in (11, 12):
        v = read_clr(src, at, x['ctype'])
        n = CLRSIZE.get(x['ctype'], 4)
    else:
        if name == 9:
            nc = 3 if x['cnt'] == 1 else 2
        elif name == 10:
            nc = 3 if x['cnt'] == 0 else 9
        elif name == 25:
            nc = 9
        else:
            nc = 2 if x['cnt'] == 1 else 1
        cs = CSIZE[x['ctype']]
        div = 1.0 if x['ctype'] == 4 else float(1 << x['frac'])
        if name == 10 and x['ctype'] in (1, 3):
            div = 64.0 if x['ctype'] == 1 else 16384.0
        v = tuple(struct.unpack_from(CFMT[x['ctype']], src, at + k * cs)[0] / div for k in range(nc))
        n = nc * cs
    if typ == 1:
        return v, n
    return v, 1 if typ == 2 else 2


def pobj_prims(d, pobj):
    """[[vertex dict(pos, nrm, clr, uv, pnmtx)]] per primitive, with the primitive op."""
    attrs = vtx_attrs(d, pobj)
    dl_off = d.p(pobj + 0x10)
    n32 = d.u16(pobj + 0x0E)
    buf = d.raw[0x20 + dl_off:0x20 + dl_off + n32 * 32]
    prims, q = [], 0
    while q < len(buf):
        op = buf[q]
        if op == 0:
            break
        n = struct.unpack_from('>H', buf, q + 1)[0]
        q += 3
        verts = []
        for _ in range(n):
            v = {}
            for x in attrs:
                val, sz = _value(d, x, buf, q)
                q += sz
                nm = x['name']
                if nm == 0:
                    v['pnmtx'] = val
                elif nm == 9:
                    v['pos'] = val if len(val) == 3 else (val[0], val[1], 0.0)
                elif nm == 10:
                    v['nrm'] = val[:3]
                elif nm == 11:
                    v['clr'] = val
                elif nm == 13:
                    v['uv'] = val
            verts.append(v)
        prims.append((op & 0xF8, verts))
    return prims


def tris_of(op, vs):
    if op == 0x90:
        return [(vs[i], vs[i + 1], vs[i + 2]) for i in range(0, len(vs) - 2, 3)]
    if op == 0x98:
        return [(vs[i], vs[i + 1], vs[i + 2]) if i % 2 == 0 else (vs[i + 1], vs[i], vs[i + 2]) for i in range(len(vs) - 2)]
    if op == 0xA0:
        return [(vs[0], vs[i], vs[i + 1]) for i in range(1, len(vs) - 1)]
    if op == 0x80:
        out = []
        for i in range(0, len(vs) - 3, 4):
            out += [(vs[i], vs[i + 1], vs[i + 2]), (vs[i], vs[i + 2], vs[i + 3])]
        return out
    return []


def material(d, mobj):
    if mobj is None:
        return dict(mode=0, amb=(128,) * 4, dif=(255,) * 4, alpha=1.0, tobjs=[])
    mode = d.u(mobj + 4)
    mat = d.p(mobj + 0x0C)
    amb = tuple(d.raw[0x20 + mat:0x20 + mat + 4]) if mat is not None else (128,) * 4
    dif = tuple(d.raw[0x20 + mat + 4:0x20 + mat + 8]) if mat is not None else (255,) * 4
    alpha = d.f(mat + 0x0C) if mat is not None else 1.0
    tobjs = []
    t = d.p(mobj + 8)
    while t is not None and len(tobjs) < 8:
        img = d.p(t + 0x4C)
        flags = d.u(t + 0x40)
        tobjs.append(dict(off=t, id=d.u(t + 8), src=d.u(t + 0x0C), rot=[d.f(t + 0x10 + 4 * i) for i in range(3)],
                          scale=[d.f(t + 0x1C + 4 * i) for i in range(3)], trans=[d.f(t + 0x28 + 4 * i) for i in range(3)],
                          wrap=(d.u(t + 0x34), d.u(t + 0x38)), repeat=(d.b(t + 0x3C), d.b(t + 0x3D)), flags=flags,
                          blending=d.f(t + 0x44), img=img, tlut=d.p(t + 0x50),
                          coord=flags & 0xF, lightmap=(flags >> 4) & 0xFFF, colormap=(flags >> 16) & 0xF,
                          alphamap=(flags >> 20) & 0xF))
        t = d.p(t + 4)
    return dict(mode=mode, amb=amb, dif=dif, alpha=alpha, tobjs=tobjs)


def inv_bind(d, j, world):
    ib = d.p(j['off'] + 0x38)
    if ib is not None:
        m = np.eye(4)
        m[:3, :4] = np.array([d.f(ib + 4 * k) for k in range(12)]).reshape(3, 4)
        return m
    return np.linalg.inv(world)


def model(d, root, override=None, parent=None, with_hidden=False, bind=None, siblings=True):
    """Triangles of the tree at `root`: list of dict(joint, dobj, mat, tris=[(3 x vertex)]) with each
    vertex dict(pos=(x,y,z) in model space, clr, uv). `bind` = joints() of the same tree at bind
    pose for envelope skinning (defaults to the un-overridden tree)."""
    js = joints(d, root, parent=parent, override=override, siblings=siblings)
    bj = bind or joints(d, root, parent=parent, siblings=siblings)
    by_off = {j['off']: j for j in js}
    bind_by_off = {j['off']: j for j in bj}
    out = []
    for j in js:
        if j['flags'] & (JOBJ_PTCL | JOBJ_SPLINE):
            continue
        hidden = bool(j['flags'] & JOBJ_HIDDEN)
        if hidden and not with_hidden:
            continue
        dobj = d.p(j['off'] + 0x10)
        k = 0
        while dobj is not None:
            mat = material(d, d.p(dobj + 8))
            pobj = d.p(dobj + 0x0C)
            tris = []
            while pobj is not None:
                pflags = d.u16(pobj + 0x0C)
                kind = pflags & 0x3000
                envs = None
                if kind == 0x2000:
                    envs = []
                    el = d.p(pobj + 0x14)
                    i = 0
                    while el is not None:
                        e = d.p(el + 4 * i)
                        if e is None:
                            break
                        pairs, m = [], np.zeros((4, 4))
                        q = 0
                        while True:
                            jo = d.p(e + 8 * q)
                            if jo is None:
                                break
                            w = d.f(e + 8 * q + 4)
                            pj, bjj = by_off.get(jo), bind_by_off.get(jo)
                            if pj is not None:
                                m += w * (pj['world'] @ inv_bind(d, bjj, bjj['world']))
                            pairs.append((jo, w))
                            q += 1
                        # pobj.c SetupEnvelopeModelMtx: an owner flagged SKELETON_ROOT draws a single-weight
                        # envelope with the bone's matrix alone (vertices local to the bone), no inverse bind
                        if len(pairs) == 1 and pairs[0][1] >= 1 - 1e-6 and j['flags'] & 0x2:
                            pj = by_off.get(pairs[0][0])
                            m = pj['world'] if pj is not None else np.eye(4)
                        envs.append(m if pairs else np.eye(4))
                        i += 1
                for op, vs in pobj_prims(d, pobj):
                    for v in vs:
                        p = np.array([*v['pos'], 1.0])
                        if envs is not None:
                            mi = v.get('pnmtx', 0) // 3
                            m = envs[mi] if mi < len(envs) else np.eye(4)
                            if len(envs) == 1 and 'pnmtx' not in v:
                                m = envs[0]
                            v['pos'] = tuple((m @ p)[:3])
                        else:
                            v['pos'] = tuple((j['world'] @ p)[:3])
                    tris += tris_of(op, vs)
                pobj = d.p(pobj + 4)
            out.append(dict(joint=j['index'], joint_off=j['off'], dobj=k, mat=mat, tris=tris, hidden=hidden))
            dobj = d.p(dobj + 4)
            k += 1
    return out, js


def bounds(parts):
    vs = np.array([v['pos'] for p in parts for t in p['tris'] for v in t])
    if not len(vs):
        return None
    return vs.min(0).round(3).tolist(), vs.max(0).round(3).tolist()


# --------------------------------------------------------------------------- shading
def _sample(tex, uv, tobj):
    h, w = tex.shape[:2]
    u, v = uv[..., 0], uv[..., 1]
    sx, sy = tobj['scale'][0] or 1, tobj['scale'][1] or 1
    rs, rt = tobj['repeat'][0] or 1, tobj['repeat'][1] or 1
    u = (u - tobj['trans'][0]) * rs / sx
    v = (v - tobj['trans'][1]) * rt / sy

    def wrap(c, mode):
        if mode == 0:
            return np.clip(c, 0, 0.9999)
        if mode == 2:
            k = np.floor(c)
            f = c - k
            return np.where(k.astype(int) % 2 == 1, 1 - f, f).clip(0, 0.9999)
        return c - np.floor(c)
    u, v = wrap(u, tobj['wrap'][0]), wrap(v, tobj['wrap'][1])
    return tex[(v * h).astype(int).clip(0, h - 1), (u * w).astype(int).clip(0, w - 1)]


def shade(d, mat, clr, uv):
    """RGBA (0..255 float arrays) for pixels with interpolated vertex colour / uv."""
    mode = mat['mode']
    n = clr.shape[0] if clr is not None else uv.shape[0]
    dif = np.array(mat['dif'], np.float32)
    base = np.tile(dif, (n, 1))
    if mode & 2 and clr is not None:              # RENDER_VERTEX
        base = clr.copy() if not mode & 1 else clr * dif / 255
    alpha_mode = (mode >> 13) & 3
    a = np.full(n, 255 * mat['alpha'], np.float32)
    if alpha_mode in (2, 3) and clr is not None:
        a = clr[:, 3] * (mat['alpha'] if alpha_mode == 3 else 1)
    rgb = base[:, :3]
    for t in mat['tobjs']:
        # only diffuse/ambient/ext lightmaps colour the surface; specular/shadow maps are skipped
        if t['img'] is None or (t['lightmap'] and not t['lightmap'] & 0xD):
            continue
        tex = d.texture(t['img'], t['tlut'])
        if t['coord'] == 0 and uv is not None:
            s = _sample(tex, uv, t)
        else:
            s = np.tile(tex.reshape(-1, 4).mean(0), (n, 1))
        cm = t['colormap']
        if cm == 5:
            rgb = s[:, :3].copy()
        elif cm == 7:
            rgb = np.minimum(rgb + s[:, :3], 255)
        elif cm == 3:
            rgb = rgb * (1 - t['blending']) + s[:, :3] * t['blending']
        elif cm in (4, 0, 6):
            rgb = rgb * s[:, :3] / 255
        am = t['alphamap']          # HSD TEX_ALPHAMAP: 0 none 1 mask 2 blend 3 modulate 4 replace 5 pass 6 add 7 sub
        if am == 3:
            a = a * s[:, 3] / 255
        elif am == 4:
            a = s[:, 3].copy()
        elif am == 2:
            a = a * (1 - t['blending']) + s[:, 3] * t['blending']
        elif am == 6:
            a = np.minimum(a + s[:, 3], 255)
    return np.concatenate([rgb, a[:, None]], 1)


# --------------------------------------------------------------------------- raster
def raster(d, parts, to_screen, W, H, ss=2, bg=None, alpha_cut=8):
    """Render parts with a vertex->screen function f(N x 3 world) -> (N x 2 px, N depth (bigger=nearer)).
    Returns (RGBA uint8 image array HxW, coverage mask HxW bool). ss = supersample."""
    Ws, Hs = W * ss, H * ss
    rgb = np.zeros((Hs, Ws, 3), np.float32) if bg is None else np.repeat(np.repeat(bg[..., :3].astype(np.float32), ss, 0), ss, 1)
    alpha = np.zeros((Hs, Ws), np.float32)
    zbuf = np.full((Hs, Ws), -np.inf, np.float32)
    cover = np.zeros((Hs, Ws), bool)
    order = sorted(parts, key=lambda p: bool(p['mat']['mode'] & (1 << 30)))
    for part in order:
        xlu = bool(part['mat']['mode'] & (1 << 30))
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
            z = w0 * Z[0] + w1 * Z[1] + w2 * Z[2]
            m &= z >= zbuf[miny:maxy, minx:maxx] - (1e-4 if xlu else 0)
            if not m.any():
                continue
            W3 = np.stack([w0[m], w1[m], w2[m]], 1)
            clr = np.array([v.get('clr', (255, 255, 255, 255)) for v in tri], np.float32) if 'clr' in tri[0] else None
            uv = np.array([v.get('uv', (0, 0)) for v in tri], np.float32) if 'uv' in tri[0] else None
            c = shade(d, part['mat'], W3 @ clr if clr is not None else None, W3 @ uv if uv is not None else (np.zeros((W3.shape[0], 2)) if clr is None else None))
            a = c[:, 3] / 255
            keep = a * 255 >= alpha_cut
            sub = rgb[miny:maxy, minx:maxx]
            idx = np.nonzero(m)
            iy, ix = idx[0][keep], idx[1][keep]
            ck, ak = c[keep], a[keep]
            if xlu:
                sub[iy, ix] = sub[iy, ix] * (1 - ak[:, None]) + ck[:, :3] * ak[:, None]
            else:
                sub[iy, ix] = ck[:, :3] * ak[:, None] + sub[iy, ix] * (1 - ak[:, None]) if bg is not None else ck[:, :3]
                zbuf[miny:maxy, minx:maxx][iy, ix] = z[m][keep]
            alpha[miny:maxy, minx:maxx][iy, ix] = np.maximum(alpha[miny:maxy, minx:maxx][iy, ix], ak * 255)
            cover[miny:maxy, minx:maxx][iy, ix] = True
    img = np.dstack([rgb.clip(0, 255), alpha]).astype(np.float32)
    if ss > 1:
        img = img.reshape(H, ss, W, ss, 4).mean((1, 3))
        cov = cover.reshape(H, ss, W, ss).mean((1, 3)) >= 0.5
    else:
        cov = cover
    return img.astype(np.uint8), cov


def ortho(xmin, xmax, ymin, ymax, ppu):
    """front view (x right, y up, viewer at +z): world -> px."""
    W = int(math.ceil((xmax - xmin) * ppu))
    H = int(math.ceil((ymax - ymin) * ppu))

    def f(P):
        S = np.stack([(P[:, 0] - xmin) * ppu, (ymax - P[:, 1]) * ppu], 1)
        return S, P[:, 2]
    return f, W, H


def silhouette(mask, xmin, ymax, ppu, eps_units=0.08, min_area_units=0.5):
    """Outer contours of a coverage mask as polygons in model units (x right, y up)."""
    import cv2
    m = (mask.astype(np.uint8) * 255)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        if cv2.contourArea(c) < min_area_units * ppu * ppu:
            continue
        a = cv2.approxPolyDP(c, eps_units * ppu, True)[:, 0, :].astype(float)
        out.append([(round(xmin + (x + 0.5) / ppu, 2), round(ymax - (y + 0.5) / ppu, 2)) for x, y in a])
    out.sort(key=lambda poly: -abs(_area(poly)))
    return out


def _area(poly):
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]))


def transform_parts(parts, m):
    """copy of parts with every vertex position multiplied by 4x4 m."""
    out = []
    for p in parts:
        tris = []
        for t in p['tris']:
            nt = []
            for v in t:
                q = dict(v)
                q['pos'] = tuple((m @ np.array([*v['pos'], 1.0]))[:3])
                nt.append(q)
            tris.append(tuple(nt))
        out.append(dict(p, tris=tris))
    return out


def mean_colours(d, parts):
    """per DObj: area-weighted mean RGBA of its shaded vertices/texture (front view area)."""
    res = []
    for p in parts:
        if not p['tris']:
            continue
        cols, ws = [], []
        for t in p['tris']:
            P = np.array([v['pos'] for v in t])
            a = abs(np.cross(P[1] - P[0], P[2] - P[0])[2]) / 2 + 1e-6
            clr = np.array([v['clr'] for v in t], np.float32) if 'clr' in t[0] else None
            uv = np.array([v['uv'] for v in t], np.float32) if 'uv' in t[0] else None
            W3 = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3]], np.float32)
            c = shade(d, p['mat'], W3 @ clr if clr is not None else None, W3 @ uv if uv is not None else np.zeros((4, 2)) if clr is None else None)
            cols.append(c.mean(0))
            ws.append(a)
        c = np.average(np.array(cols), axis=0, weights=np.array(ws))
        res.append(dict(joint=p['joint'], dobj=p['dobj'], rgba=[int(x) for x in c], hex='#%02x%02x%02x' % tuple(int(x) for x in c[:3]),
                        mode=hex(p['mat']['mode']), ntex=len(p['mat']['tobjs'])))
    return res
