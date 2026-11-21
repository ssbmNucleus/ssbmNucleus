"""Brawl's resource files (BRRES): folders of models (MDL0), textures (TEX0) and animations (CHR0).

Read here: the folders, a model's bones, and an animation's curves sampled a frame at a time.
"""
from __future__ import annotations

import math
import struct


def _group(data, at):
    """A resource group at `at` -> [(name, offset of the entry's data in the file)]."""
    count = struct.unpack_from('>I', data, at + 4)[0]
    out = []
    for i in range(1, count + 1):
        _id, _flag, _left, _right, name, body = struct.unpack_from('>HHHHii', data, at + 8 + i * 16)
        out.append((_text(data, at + name), at + body))
    return out


def _text(data, at):
    size = struct.unpack_from('>I', data, at - 4)[0]
    return data[at:at + size].decode('ascii', 'replace')


def folders(data: bytes):
    """{folder name: {file name: offset}} of a BRRES."""
    if data[:4] != b'bres':
        raise ValueError('not a BRRES')
    root = struct.unpack_from('>H', data, 0x0C)[0]
    out = {}
    for name, at in _group(data, root + 8):
        out[name] = dict(_group(data, at))
    return out


# ---------------------------------------------------------------------------------------- models
def bones(data: bytes, mdl0: int):
    """A model's bones in index order: [{'name', 'index', 'parent', 'scale', 'rotation' (degrees, applied x then y
    then z), 'translation'}]."""
    version = struct.unpack_from('>I', data, mdl0 + 8)[0]
    group = mdl0 + struct.unpack_from('>i', data, mdl0 + 0x10 + 4)[0]            # the second section: bones
    found = {}
    for name, at in _group(data, group):
        index = struct.unpack_from('>i', data, at + 0x0C)[0]
        s = struct.unpack_from('>3f', data, at + 0x20)
        r = struct.unpack_from('>3f', data, at + 0x2C)
        t = struct.unpack_from('>3f', data, at + 0x38)
        parent = struct.unpack_from('>i', data, at + 0x5C)[0]
        found[at] = {'name': name, 'index': index, 'parent_at': at + parent if parent else None,
                     'scale': s, 'rotation': r, 'translation': t}
    for b in found.values():
        b['parent'] = found[b.pop('parent_at')]['index'] if b['parent_at'] in found else None
    return sorted(found.values(), key=lambda b: b['index']), version


def matrix(scale, rotation, translation):
    """The 4x4 of a bone's own scale, rotation (degrees; x, then y, then z) and place, as rows."""
    x, y, z = (math.radians(v) for v in rotation)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    r = [[cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
         [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
         [-sy, sx * cy, cx * cy]]
    return [[r[i][0] * scale[0], r[i][1] * scale[1], r[i][2] * scale[2], translation[i]] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


# ---------------------------------------------------------------------------------------- animations
def _hermite(f0, v0, t0, f1, v1, t1, f):
    span = f1 - f0
    if span <= 0:
        return v1
    u = (f - f0) / span
    return (v0 * (2 * u ** 3 - 3 * u ** 2 + 1) + t0 * span * (u ** 3 - 2 * u ** 2 + u)
            + v1 * (-2 * u ** 3 + 3 * u ** 2) + t1 * span * (u ** 3 - u ** 2))


def _keys(data, at, fmt):
    """Keyframes [(frame, value, tangent)] of an interpolated curve (formats 1 to 3)."""
    count = struct.unpack_from('>H', data, at)[0]
    out = []
    if fmt == 3:                                        # three floats a key
        for i in range(count):
            out.append(struct.unpack_from('>3f', data, at + 8 + i * 12))
        return out
    step, base = struct.unpack_from('>2f', data, at + 8)
    for i in range(count):
        if fmt == 1:                                    # four bytes a key: frame, step, tangent
            word = struct.unpack_from('>I', data, at + 16 + i * 4)[0]
            tangent = word & 0xFFF
            tangent = (tangent - 0x1000 if tangent & 0x800 else tangent) / 32.0
            out.append((float(word >> 24), base + step * ((word >> 12) & 0xFFF), tangent))
        else:                                           # six bytes a key
            frame, value, tangent = struct.unpack_from('>HHh', data, at + 16 + i * 6)
            out.append((frame / 32.0, base + step * value, tangent / 256.0))
    return out


def _curve(data, at, fmt, frames):
    """One curve's value on each frame 0..frames-1."""
    if fmt in (1, 2, 3):
        keys = _keys(data, at, fmt)
        out, k = [], 0
        for f in range(frames):
            while k + 1 < len(keys) and keys[k + 1][0] <= f:
                k += 1
            if f <= keys[0][0] or len(keys) == 1:
                out.append(keys[0][1])
            elif k + 1 >= len(keys):
                out.append(keys[-1][1])
            else:
                (f0, v0, t0), (f1, v1, t1) = keys[k], keys[k + 1]
                out.append(_hermite(f0, v0, t0, f1, v1, t1, f))
        return out
    if fmt == 6:                                        # a float a frame
        return list(struct.unpack_from(f'>{frames}f', data, at))
    step, base = struct.unpack_from('>2f', data, at)
    if fmt == 4:                                        # a byte a frame
        return [base + step * v for v in struct.unpack_from(f'>{frames}B', data, at + 8)]
    return [base + step * v for v in struct.unpack_from(f'>{frames}H', data, at + 8)]      # two bytes a frame


def animation(data: bytes, chr0: int):
    """-> {'frames', 'loop', 'bones': {bone name: {'scale', 'rotation', 'translation'}}}; each of a bone's three is a
    list a frame of (x, y, z), or None where the animation leaves the bone's own value alone. Rotations in degrees."""
    version = struct.unpack_from('>I', data, chr0 + 8)[0]
    head = chr0 + 0x10
    group = chr0 + struct.unpack_from('>i', data, head)[0]
    info = head + (8 if version >= 5 else 4) + 8       # past the data (and user data) offset, the name and path offsets
    frames, _count = struct.unpack_from('>HH', data, info)
    loop = struct.unpack_from('>I', data, info + 4)[0]
    out = {}
    for name, at in _group(data, group):
        code = struct.unpack_from('>I', data, at + 4)[0]
        slot = at + 8
        entry = {}
        for part, has, iso, fixed, fmt, default in (
                ('scale', 22, 4, 13, (code >> 25) & 3, 1.0),
                ('rotation', 23, 5, 16, (code >> 27) & 7, 0.0),
                ('translation', 24, 6, 19, (code >> 30) & 3, 0.0)):
            if not code >> has & 1:
                entry[part] = None
                continue
            axes = []
            for axis in range(1 if code >> iso & 1 else 3):
                if code >> (fixed + axis) & 1:
                    axes.append([struct.unpack_from('>f', data, slot)[0]] * frames)
                else:
                    axes.append(_curve(data, at + struct.unpack_from('>i', data, slot)[0], fmt, frames))
                slot += 4
            if len(axes) == 1:
                axes = axes * 3
            entry[part] = list(zip(*axes))
        out[name] = entry
    return {'frames': frames, 'loop': bool(loop), 'bones': out}


def visibility(data: bytes, vis0: int):
    """A visibility animation -> (frames, {bone name: [shown on each frame]}): what is drawn under a bone is shown or
    hidden a frame at a time (a blinking face under one bone, the resting face under another)."""
    version = struct.unpack_from('>I', data, vis0 + 8)[0]
    head = vis0 + 0x10
    group = vis0 + struct.unpack_from('>i', data, head)[0]
    info = head + (8 if version >= 4 else 4) + 8        # past the data (and user data) offset, the name and path offsets
    frames, _count = struct.unpack_from('>HH', data, info)
    out = {}
    for name, at in _group(data, group):
        flags = struct.unpack_from('>I', data, at + 4)[0]
        if flags & 2:                                   # the same on every frame
            out[name] = [bool(flags & 1)] * frames
        else:
            bits = data[at + 8:at + 8 + (frames + 7) // 8]
            out[name] = [bool(bits[f >> 3] >> (7 - (f & 7)) & 1) for f in range(frames)]
    return frames, out
