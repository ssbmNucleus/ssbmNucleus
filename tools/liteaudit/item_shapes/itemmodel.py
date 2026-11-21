"""Item articles and models: Article {+0 ItemAttr, +4 special attrs, +8 hurt bones, +0xC state anim
table (stride 0x10: AnimJoint, MatAnimJoint, ?, command script), +0x10 ItemModelDesc {+0 HSD_Joint*}}.
The item JObj root takes the item's position, rotation Y = pi/2 x facing when ItemAttr byte1 & 0x20
(item.c HSD_JObjSetFacingDirItem), and uniform scale ItemAttr +0x60 (Item.scl)."""
import math

import hsdgeom
from isofiles import dat
from tracker.video import sprites


def fighter_article(fname, index):
    d = dat(fname)
    root = next(v for k, v in d.roots if k.startswith('ftData'))
    items = d.p(root + 0x48)
    return d, d.p(items + 4 * index)


def attr_info(d, art):
    a = d.p(art)
    b1 = d.b(a + 1)
    return dict(byte0=hex(d.b(a)), byte1=hex(b1), faces=bool(b1 & 0x20), scale=d.f(a + 0x60),
                ecb=[round(d.f(a + 0x40 + 4 * i), 3) for i in range(4)], spin=d.f(a + 0xC),
                fall=d.f(a + 0x10), fall_max=d.f(a + 0x14))


def anim_tracks(d, aj_root):
    """[{type: keys}] per AnimJoint node in DFS preorder (child before next), parallel to the JObj tree."""
    out = []

    def walk(aj):
        while aj is not None:
            node = {}
            aobj = d.p(aj + 8)
            if aobj is not None:
                fo = d.p(aobj + 8)
                while fo is not None:
                    t, keys = sprites._decode_fobj(d, fo)
                    start = d.f(fo + 8)
                    for k in keys:
                        k['frame'] -= start
                    node[t] = keys
                    fo = d.p(fo)
                node['_end'] = d.f(aobj + 4)
            out.append(node)
            walk(d.p(aj))
            aj = d.p(aj + 4)
    walk(aj_root)
    return out


def anim_override(d, js, tracks, frame):
    """override dict for hsdgeom.joints from AnimJoint tracks at a frame (bind values elsewhere)."""
    ov = {}
    for j, node in zip(js, tracks):
        if not node:
            continue
        s, r, t = list(j['s']), list(j['r']), list(j['t'])
        for typ, keys in node.items():
            if typ == '_end' or not keys:
                continue
            v = sprites._track_value(keys, frame)
            if 1 <= typ <= 3:
                r[typ - 1] = v
            elif 5 <= typ <= 7:
                t[typ - 5] = v
            elif 8 <= typ <= 10:
                s[typ - 8] = v
        ov[j['index']] = dict(s=s, r=r, t=t)
    return ov


def state_anim(d, art, anim_index):
    st = d.p(art + 0xC)
    p = st + 0x10 * anim_index
    return dict(animjoint=d.p(p), matanim=d.p(p + 4), unk8=d.p(p + 8), script=d.p(p + 0xC))


def item_parts(d, art, pos=(0.0, 0.0, 0.0), facing=1.0, anim=None, frame=0.0, scale=None, rot=None, extra=None,
               with_hidden=False):
    """World-space triangles of the item's model. anim = state anim index (article +0xC table) or None.
    rot overrides the root rotation (x, y, z); default (0, pi/2 * facing, 0) when the attr flag is set."""
    info = attr_info(d, art)
    md = d.p(art + 0x10)
    root = d.p(md)
    js0 = hsdgeom.joints(d, root)
    ov = {}
    if anim is not None:
        sa = state_anim(d, art, anim)
        if sa['animjoint'] is not None:
            ov = anim_override(d, js0, anim_tracks(d, sa['animjoint']), frame)
    r0 = ov.get(0, {}).get('r', js0[0]['r'])
    if rot is not None:
        r0 = list(rot)
    elif info['faces']:
        r0 = [r0[0], math.pi / 2 * facing, r0[2]]
    sc = info['scale'] if scale is None else scale
    ov[0] = dict(s=[sc] * 3, r=r0, t=list(pos))
    for k, v in (extra or {}).items():
        ov.setdefault(k, {}).update(v)
    parts, js = hsdgeom.model(d, root, override=ov, with_hidden=with_hidden)
    return parts, js, info


def matanim_state(d, maj_root, frame):
    """{(joint index, dobj index): dict(tex={texmap id: (img, tlut)}, dif=(r,g,b)|None, alpha=float|None)} at frame."""
    out = {}
    joints_ = d._iter_tree(maj_root, 0x00, 0x04)
    for ji, mj in enumerate(joints_):
        ma = d.p(mj + 8)
        mi = 0
        while ma is not None:
            st = dict(tex={}, dif=None, alpha=None)
            aobj = d.p(ma + 4)
            if aobj is not None:
                fo = d.p(aobj + 8)
                dif = {}
                while fo is not None:
                    t, keys = sprites._decode_fobj(d, fo)
                    if keys:
                        v = sprites._track_value(keys, frame)
                        if t in (4, 5, 6):
                            dif[t] = v
                        elif t == 10:
                            st['alpha'] = v
                    fo = d.p(fo)
                if dif:
                    st['dif'] = dif
            ta = d.p(ma + 8)
            while ta is not None:
                texmap = d.u(ta + 4)
                imgs = [d.p(d.p(ta + 0xC) + 4 * i) for i in range(d.u16(ta + 0x14))] if d.p(ta + 0xC) is not None else []
                tls = [d.p(d.p(ta + 0x10) + 4 * i) for i in range(d.u16(ta + 0x16))] if d.p(ta + 0x10) is not None else []
                ii = ti = 0
                aobj = d.p(ta + 8)
                if aobj is not None:
                    fo = d.p(aobj + 8)
                    while fo is not None:
                        t, keys = sprites._decode_fobj(d, fo)
                        if keys:
                            v = sprites._track_value(keys, frame)
                            if t == 1:
                                ii = int(v)
                            elif t == 10:
                                ti = int(v)
                        fo = d.p(fo)
                if imgs:
                    st['tex'][texmap] = (imgs[min(ii, len(imgs) - 1)], tls[min(ti, len(tls) - 1)] if tls else None)
                ta = d.p(ta)
            out[(ji, mi)] = st
            ma = d.p(ma)
            mi += 1
    return out


def apply_matanim(parts, state):
    """copy of parts with textures / diffuse / alpha from matanim_state."""
    res = []
    for p in parts:
        st = state.get((p['joint'], p['dobj']))
        if not st:
            res.append(p)
            continue
        mat = dict(p['mat'])
        mat['tobjs'] = [dict(t, img=st['tex'][t['id']][0], tlut=st['tex'][t['id']][1] if st['tex'][t['id']][1] is not None else t['tlut'])
                        if t['id'] in st['tex'] else t for t in mat['tobjs']]
        if st['dif']:
            dif = list(mat['dif'])
            for t, v in st['dif'].items():
                dif[t - 4] = max(0, min(255, int(round(v * 255))))
            mat['dif'] = tuple(dif)
        if st['alpha'] is not None:
            mat['alpha'] = st['alpha']
        res.append(dict(p, mat=mat))
    return res
