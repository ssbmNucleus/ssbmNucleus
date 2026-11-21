"""The two ActorX files CUE4Parse writes for an Unreal game (`uetool export`, `UE_MESH=psk`): a skeletal mesh
(`.psk`: points, wedges, faces, materials, the reference skeleton, the weights, normals per wedge) and a clip
(`.psa`: its bones, one entry of numbers, and a key per bone per frame).

Everything is in Unreal's own space (centimetres, Z up, X ahead, Y to the side: left-handed). A joint's place and
turn are its parent's space. ActorX keeps the turn of every joint but the first CONJUGATED (UModel's convention,
which CUE4Parse writes): `bones()` and `keys()` give them as Unreal holds them (checked: the skeleton put together
this way lands each joint where the skin's own bind pose puts it, `test_rivals2_reader`).
"""
from __future__ import annotations

import struct

import numpy as np


def chunks(data):
    """{chunk id: (type flag, record size, count, bytes)} in file order."""
    out, at = {}, 0
    while at + 32 <= len(data):
        cid = data[at:at + 20].split(b'\0', 1)[0].decode('latin-1')
        flag, size, count = struct.unpack_from('<iii', data, at + 20)
        at += 32
        out[cid] = (flag, size, count, data[at:at + size * count])
        at += size * count
    return out


def _bones(raw, count):
    rows = []
    for k in range(count):
        name = raw[k * 120:k * 120 + 64].split(b'\0', 1)[0].decode('latin-1')
        flags, nchild, parent = struct.unpack_from('<Iii', raw, k * 120 + 64)
        qx, qy, qz, qw, px, py, pz = struct.unpack_from('<7f', raw, k * 120 + 76)
        q = np.array([qx, qy, qz, qw])
        if k:
            q[:3] = -q[:3]
        rows.append(dict(name=name, parent=None if k == 0 else parent, q=q, t=np.array([px, py, pz])))
    return rows


class Mesh:
    """A .psk: `bones` [{'name', 'parent', 'q' (x, y, z, w), 't'}], `points` (n, 3), `wedges` [(point, u, v,
    material)], `faces` (m, 3) wedge indices with `face_material` (m,), `materials` [name], `weights` [(point, bone,
    weight)], `normals` (wedges, 3) or None."""

    def __init__(self, path):
        data = open(path, 'rb').read()
        c = chunks(data)
        self.points = np.frombuffer(c['PNTS0000'][3], '<f4').reshape(-1, 3).astype(float)
        _f, size, n, raw = c['VTXW0000']
        big = len(self.points) > 0xFFFF
        self.wedges = []
        for k in range(n):
            if big:
                p, u, v, m = struct.unpack_from('<iffB', raw, k * size)
            else:
                p, _pad, u, v, m = struct.unpack_from('<HHffB', raw, k * size)
            self.wedges.append((p, u, v, m))
        key = 'FACE3200' if 'FACE3200' in c else 'FACE0000'
        _f, size, n, raw = c[key]
        fmt = '<3iBBI' if key == 'FACE3200' else '<3HBBI'
        faces, mats = [], []
        for k in range(n):
            a, b, cc, m, _aux, _sm = struct.unpack_from(fmt, raw, k * size)
            faces.append((a, b, cc))
            mats.append(m)
        self.faces = np.array(faces, int)
        self.face_material = np.array(mats, int)
        _f, size, n, raw = c['MATT0000']
        self.materials = [raw[k * size:k * size + 64].split(b'\0', 1)[0].decode('latin-1') for k in range(n)]
        skel = c.get('REFSKELT') or c.get('REFSKEL0')
        self.bones = _bones(skel[3], skel[2]) if skel else []
        ww = c.get('RAWWEIGHTS') or c.get('RAWW0000')
        self.weights = []
        if ww:
            for k in range(ww[2]):
                w, p, b = struct.unpack_from('<fii', ww[3], k * 12)
                self.weights.append((p, b, w))
        nn = c.get('VTXNORMS')
        self.normals = np.frombuffer(nn[3], '<f4').reshape(-1, 3).astype(float) if nn else None
        self.chunk_ids = list(c)


class Clip:
    """A .psa: `bones` (as in Mesh), `name`, `rate` (frames a second), `frames`, and `keys` (frames, bones) of
    (t (3), q (x, y, z, w)) as arrays `t` (frames, bones, 3) and `q` (frames, bones, 4); `scale` (frames, bones, 3)
    when the file has scale keys."""

    def __init__(self, path):
        data = open(path, 'rb').read()
        c = chunks(data)
        self.bones = _bones(c['BONENAMES'][3], c['BONENAMES'][2])
        raw = c['ANIMINFO'][3]
        self.name = raw[:64].split(b'\0', 1)[0].decode('latin-1')
        total, _root, _style, _quot, _red, track_time, rate, _start, _first, frames = struct.unpack_from(
            '<4iffFiii'.replace('F', 'f'), raw, 128)
        self.rate, self.frames, self.track_time = rate, frames, track_time
        nb = len(self.bones)
        keys = np.frombuffer(c['ANIMKEYS'][3], '<f4').reshape(-1, 8).astype(float)
        keys = keys[:frames * nb].reshape(frames, nb, 8)
        self.t = keys[:, :, 0:3].copy()
        q = keys[:, :, 3:7].copy()
        q[:, 1:, :3] = -q[:, 1:, :3]
        self.q = q
        sk = c.get('SCALEKEYS')
        self.scale = None
        if sk:
            s = np.frombuffer(sk[3], '<f4').reshape(-1, 4).astype(float)
            if len(s) >= frames * nb:
                self.scale = s[:frames * nb, :3].reshape(frames, nb, 3)
