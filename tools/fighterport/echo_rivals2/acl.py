"""Clips the game compressed with the ACL plugin (Animation Compression Library), read without CUE4Parse's native
library.

Rivals 2 compresses most clips with Unreal's own per-track codec, which CUE4Parse reads in C#. Some (Zetterburn: the
item-holding clips, being grabbed, the backward jumps, the teeter: 38 of 200) name
`/ACLPlugin/ACLAnimBoneCompressionSettings` instead, and their data is the ACL library's "compressed tracks". CUE4Parse
hands those to a native `CUE4Parse-Natives` DLL that its NuGet package does not carry and nothing on this machine has,
so the reader decodes them here: `uetool acl-raw` writes the clip's bytes and its track-to-bone table, `decode` reads
the tracks, `write_psa` writes the same ActorX clip CUE4Parse would (so the rest of the reader cannot tell them apart).

The layout below was read from the bytes themselves (ACL 2.1, tracks version 10, the uniformly sampled qvvf
algorithm) and checked by what must hold: every rotation a unit quaternion, every track continuous across its
segments' joins and between samples, and the result next to the clips CUE4Parse decodes (the item idle against the
idle, `test_rivals2_reader`):

- raw buffer header (size, hash), then the tracks header at 8: tag 0xac11ac11, version, algorithm, track type 12
  (qvvf), tracks, samples, sample rate, misc bits (0 has scale, 1 default scale, 2/3 scale/translation format,
  4-7 rotation format, 30 wrap optimised: the last sample is the first again and is not stored).
- the transform header at 0x20 (offsets from it): segments, variable sub-tracks, animated rotations/translations/
  scales, constant ones, database, segment headers, sub-track types, constant data, clip range data; segment start
  samples follow at +0x34 when there are two or more.
- sub-track types, two bits each, first track in the high bits of a little-endian word: 0 default (the skeleton's
  reference pose), 1 constant, 2 animated; a list for rotations, translations, then scales.
- constants: rotations three floats each in groups of four laid out x x x x, y y y y, z z z z; translations and
  scales three floats each.
- the clip range (min, extent) of every animated sub-track: rotations in groups of four (min x, y, z, extent x, y,
  z, each a row of four); translations and scales six floats each.
- a segment header (bits per sample, -, -, data offset): at the offset, one byte per animated sub-track giving its
  bits per component (rotations padded to a multiple of four; 0 the track holds still in this segment; 31 or more
  three raw floats), then at an even address the segment range (eight-bit min and extent per component; rotations
  in groups of four as in the clip range), then at a four-byte address the samples, one pose after another, each
  sub-track's components high bit first.
- a value is (stored / (2^bits - 1)) * segment extent / 255 + segment min / 255, then * clip extent + clip min. A
  track holding still in a segment keeps three 16-bit values in its segment range bytes instead (rotations: rows 0-1,
  2-3, 4-5 of its column, high byte first; translations and scales: little-endian), scaled the same way by the clip
  range. Rotations drop w (w = sqrt(1 - x^2 - y^2 - z^2)).
"""
from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import numpy as np

TAG = 0xAC11AC11
QVVF = 12
ROTATION_DROP_W_VARIABLE = 3      # misc bits 4-7 of every clip seen; the only rotation format read here
WRAP = 0x40000000
H = 0x20                          # the transform header's place: every offset in it counts from here


class Unsupported(ValueError):
    """An ACL clip in a form this reader was not written for (said, never guessed)."""


def _bits(buf):
    big = int.from_bytes(bytes(buf), 'big')
    n = len(buf) * 8

    def read(at, nbits):
        return (big >> (n - at - nbits)) & ((1 << nbits) - 1)
    return read


def _float(u):
    return struct.unpack('<f', struct.pack('<I', u))[0]


def header(b):
    _size, _hash, tag, ver, alg, ttype, ntracks, nsamples, rate, misc = struct.unpack_from('<IIIHBBIIfI', b, 0)
    if tag != TAG:
        raise Unsupported(f'not ACL compressed tracks (tag {tag:#x})')
    if ttype != QVVF or alg != 0:
        raise Unsupported(f'ACL track type {ttype} / algorithm {alg} (only qvvf, uniformly sampled)')
    if (misc >> 4) & 0xF != ROTATION_DROP_W_VARIABLE or not misc & 8 or (misc & 1 and not misc & 4):
        raise Unsupported(f'ACL formats {misc:#x} (only variable rotation, translation and scale)')
    (nseg, nvar, nrot, ntra, nsca, _crot, _ctra, _csca, _db, seg_off, types_off, const_off,
     range_off) = struct.unpack_from('<13I', b, H)
    starts = list(struct.unpack_from(f'<{nseg}I', b, H + 0x34)) if nseg > 1 else [0]
    segs = [struct.unpack_from('<4I', b, H + seg_off + 16 * i) for i in range(nseg)]
    words = (ntracks * 2 + 31) // 32
    types = []
    for part in range(3 if misc & 1 else 2):
        v = []
        for w in struct.unpack_from(f'<{words}I', b, H + types_off + part * words * 4):
            v.extend((w >> (30 - 2 * i)) & 3 for i in range(16))
        types.append(v[:ntracks])
    return dict(version=ver, ntracks=ntracks, nsamples=nsamples, rate=rate, misc=misc, has_scale=bool(misc & 1),
                default_scale=(misc >> 1) & 1, wrap=bool(misc & WRAP), nseg=nseg, nvar=nvar, nrot=nrot, ntra=ntra,
                nsca=nsca, starts=starts, segs=segs, types=types, const_off=const_off, range_off=range_off)


def decode(b):
    """The clip's sub-tracks -> dict(header..., rot (samples, tracks, 4) x y z w, tra (samples, tracks, 3),
    sca (samples, tracks, 3)), with NaN where a sub-track is default (the caller fills the reference pose; a default
    scale is filled here). Samples as stored (a wrap-optimised clip's repeated first sample is not added)."""
    h = header(b)
    nt, ns = h['ntracks'], h['nsamples']
    kinds = h['types']
    anim = [[t for t in range(nt) if k[t] == 2] for k in kinds]
    const = [[t for t in range(nt) if k[t] == 1] for k in kinds]
    out = [np.full((ns, nt, 3), np.nan) for _ in range(3)]
    if not h['has_scale']:
        out[2][:] = float(h['default_scale'])
    else:
        sca_default = [t for t in range(nt) if kinds[2][t] == 0]
        out[2][:, sca_default] = float(h['default_scale'])
    # constants
    p = H + h['const_off']
    cr = const[0]
    for g in range(0, len(cr), 4):
        n = min(4, len(cr) - g)
        blk = np.array(struct.unpack_from(f'<{3 * n}f', b, p)).reshape(3, n)
        p += 12 * n
        for k in range(n):
            out[0][:, cr[g + k]] = blk[:, k]
    for kind in (1, 2) if h['has_scale'] else (1,):
        for t in const[kind]:
            out[kind][:, t] = struct.unpack_from('<3f', b, p)
            p += 12
    # clip ranges
    p = H + h['range_off']
    clip = [[], [], []]
    nrot = len(anim[0])
    for g in range(0, nrot, 4):
        n = min(4, nrot - g)
        blk = np.array(struct.unpack_from(f'<{6 * n}f', b, p)).reshape(6, n)
        p += 24 * n
        clip[0].extend((blk[0:3, k], blk[3:6, k]) for k in range(n))
    for kind in (1, 2) if h['has_scale'] else (1,):
        for _t in anim[kind]:
            clip[kind].append((np.array(struct.unpack_from('<3f', b, p)), np.array(struct.unpack_from('<3f', b, p + 12))))
            p += 24
    pad_r = (nrot + 3) // 4 * 4
    nvar_seen = pad_r + len(anim[1]) + (len(anim[2]) if h['has_scale'] else 0)
    if (nvar_seen, nrot, len(anim[1])) != (h['nvar'], h['nrot'], h['ntra']):
        raise Unsupported(f"ACL animated sub-tracks: header {h['nvar']} ({h['nrot']} rotations, {h['ntra']} "
                          f"translations), types {nvar_seen} ({nrot}, {len(anim[1])})")
    # segments
    for s, (pose_bits, _rb, _tb, off) in enumerate(h['segs']):
        first = h['starts'][s]
        last = h['starts'][s + 1] if s + 1 < h['nseg'] else ns
        base = H + off
        nfmt = nvar_seen
        fmt = b[base:base + nfmt]
        seg_range = h['nseg'] > 1          # one segment: no segment range at all, values straight to the clip range
        rng = (base + nfmt + 1) & ~1
        data = (rng + nfmt * 6 + 3) & ~3 if seg_range else (base + nfmt + 3) & ~3
        read = _bits(b[data:data + ((last - first) * pose_bits + 7) // 8 + 8])
        # per sub-track: (kind, track, bits, range (min, extent) or the still value, clip range)
        plan = []
        whole = (np.zeros(3), np.ones(3))
        if not seg_range:
            if any(fmt[j] == 0 for j in range(nrot)) or any(fmt[j] == 0 for j in range(pad_r, nfmt)):
                raise Unsupported(f'ACL: a sub-track still in the only segment (no range bytes to hold it)')
            for j, t in enumerate(anim[0]):
                plan.append((0, t, fmt[j], whole, clip[0][j]))
            at = pad_r
            for kind in (1, 2) if h['has_scale'] else (1,):
                for j, t in enumerate(anim[kind]):
                    plan.append((kind, t, fmt[at], whole, clip[kind][j]))
                    at += 1
        for j, t in enumerate(anim[0] if seg_range else ()):
            g, k = divmod(j, 4)
            blk = np.frombuffer(b, np.uint8, 24, rng + 24 * g).reshape(6, 4).astype(float)
            nb = fmt[j]
            if nb == 0:
                still = np.array([blk[0, k] * 256 + blk[1, k], blk[2, k] * 256 + blk[3, k],
                                  blk[4, k] * 256 + blk[5, k]]) / 65535.0
                plan.append((0, t, 0, still, clip[0][j]))
            else:
                plan.append((0, t, nb, (blk[0:3, k] / 255.0, blk[3:6, k] / 255.0), clip[0][j]))
        at = pad_r
        for kind in ((1, 2) if h['has_scale'] else (1,)) if seg_range else ():
            for j, t in enumerate(anim[kind]):
                raw6 = b[rng + 6 * at:rng + 6 * at + 6]
                nb = fmt[at]
                if nb == 0:
                    plan.append((kind, t, 0, np.array(struct.unpack('<3H', raw6)) / 65535.0, clip[kind][j]))
                else:
                    plan.append((kind, t, nb, (np.array(list(raw6[0:3])) / 255.0, np.array(list(raw6[3:6])) / 255.0),
                                 clip[kind][j]))
                at += 1
        for i in range(last - first):
            bit = i * pose_bits
            for kind, t, nb, rg, (cmin, cext) in plan:
                if nb == 0:
                    v = rg * cext + cmin
                elif nb >= 31:
                    v = np.array([_float(read(bit + 32 * c, 32)) for c in range(3)])
                    bit += 96
                else:
                    m = (1 << nb) - 1
                    v = np.array([read(bit + nb * c, nb) for c in range(3)]) / m
                    bit += 3 * nb
                    v = (v * rg[1] + rg[0]) * cext + cmin
                out[kind][first + i, t] = v
            if i == 0 and bit != pose_bits:
                raise Unsupported(f'ACL segment {s}: a pose read {bit} bits, its header says {pose_bits}')
    xyz = out[0]
    w = np.sqrt(np.clip(1.0 - (xyz ** 2).sum(-1), 0.0, None))
    rot = np.concatenate([xyz, w[..., None]], -1)
    norm = np.linalg.norm(rot, axis=-1, keepdims=True)
    rot = np.where(np.isnan(norm), rot, rot / np.where(norm > 0, norm, 1))
    return dict(h, rot=rot, tra=out[1], sca=out[2])


# ---- the ActorX clip, as CUE4Parse-Conversion's ActorXAnim writes it --------------------------------------------

def _chunk(cid, flag, size, count, payload):
    return cid.encode('latin-1').ljust(20, b'\0') + struct.pack('<iii', flag, size, count) + payload


def reference(bones):
    """The skeleton's reference pose from an `acl-raw` record's `bones` [{name, parent, q, t, s}] (Unreal's own):
    dict(names, parents, q, t, s, parent_scale), parent_scale being the product of the ancestors' scales (CUE4Parse's
    GetParentScales: every translation it writes is multiplied by it)."""
    names = [b['name'] for b in bones]
    parents = [int(b['parent']) for b in bones]
    s = np.array([b['s'] for b in bones], float)
    ps = np.ones_like(s)
    for i, p in enumerate(parents):
        while p >= 0:
            ps[i] *= s[p]
            p = parents[p]
    return dict(names=names, parents=parents, q=np.array([b['q'] for b in bones], float),
                t=np.array([b['t'] for b in bones], float), s=s, parent_scale=ps)


def bone_table(ref):
    """ANIMHEAD + BONENAMES as ActorXAnim writes them: the reference pose unchanged (rotation, translation times the
    parent scale, scale as the size), 120 bytes a bone."""
    head = _chunk('ANIMHEAD', 20100422, 0, 0, b'')
    rows = b''
    for k, name in enumerate(ref['names']):
        rows += name.encode('latin-1')[:63].ljust(64, b'\0') + struct.pack('<Iii', 0, 0, ref['parents'][k])
        rows += struct.pack('<4f3ff3f', *ref['q'][k], *(ref['t'][k] * ref['parent_scale'][k]), 1.0, *ref['s'][k])
    return head + _chunk('BONENAMES', 0, 120, len(ref['names']), rows)


def keys(dec, track_to_bone, ref):
    """Per bone, per frame (Unreal's own space): q (frames, bones, 4), t, s, as CUE4Parse's AnimConverter builds them
    for an ACL clip: a default sub-track takes the bone's reference pose, a wrap-optimised clip gets its first sample
    again at the end, and a bone with no track holds its reference pose."""
    ns = dec['nsamples']
    frames = ns + 1 if dec['wrap'] and ns > 0 else ns
    nb = len(ref['names'])
    q = np.repeat(ref['q'][None], frames, 0).astype(float)
    t = np.repeat(ref['t'][None], frames, 0).astype(float)
    s = np.repeat(ref['s'][None], frames, 0).astype(float)
    for track, bone in enumerate(track_to_bone):
        if not 0 <= bone < nb:
            continue
        for arr, src, refv in ((q, dec['rot'], ref['q']), (t, dec['tra'], ref['t']), (s, dec['sca'], ref['s'])):
            v = src[:, track].copy()
            v[np.isnan(v).any(-1)] = refv[bone]
            arr[:ns, bone] = v
            if frames > ns:
                arr[ns, bone] = v[0]
    return q, t, s


def write_psa(path, name, q, t, s, ref, frames, seconds, rate_scale=1.0):
    """The ActorX clip CUE4Parse-Conversion writes (ActorXAnim): ANIMHEAD + BONENAMES (the reference pose),
    ANIMINFO (rate = frames / length * max(1, rate scale)), ANIMKEYS with translations times the parent scale and
    every key's Y negated (and the root's W), SCALEKEYS relative to the reference scale."""
    nfr, nb = q.shape[0], q.shape[1]
    if nfr != frames:
        raise Unsupported(f'{name}: {nfr} decoded frames, the clip says {frames}')
    rate = frames / seconds * max(1.0, rate_scale) if seconds else 30.0
    info = (name.encode('latin-1')[:63].ljust(64, b'\0') + b'None'.ljust(64, b'\0')
            + struct.pack('<4i3f3i', nb, 0, 0, frames * nb, 0.0, float(frames), rate, 0, 0, frames))
    body = bone_table(ref) + _chunk('ANIMINFO', 0, 168, 1, info)
    kq = q.copy()
    kq[..., 1] *= -1
    kq[:, 0, 3] *= -1
    kt = t * ref['parent_scale'][None]
    kt[..., 1] *= -1
    rows = np.concatenate([kt, kq, np.ones((nfr, nb, 1))], -1).astype('<f4')
    body += _chunk('ANIMKEYS', 0, 32, nfr * nb, rows.tobytes())
    refs = np.where(np.abs(ref['s']) < 1e-4, 1.0, ref['s'])
    rel = s / refs[None]
    srows = np.concatenate([rel, np.ones((nfr, nb, 1))], -1).astype('<f4')
    body += _chunk('SCALEKEYS', 0, 16, nfr * nb, srows.tobytes())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(body)
    return Path(path)


def to_psa(raw_json, out_path):
    """One `uetool acl-raw` record (a path or the dict) -> the .psa CUE4Parse would have written."""
    rec = json.loads(Path(raw_json).read_text('utf-8')) if not isinstance(raw_json, dict) else raw_json
    if not rec.get('acl'):
        raise Unsupported(f"{rec.get('clip')}: no ACL bytes ({rec.get('codec')})")
    if rec.get('additive'):
        raise Unsupported(f"{rec['clip']}: an additive clip (CUE4Parse would convert it against its base pose)")
    if not rec.get('bones'):
        raise Unsupported(f"{rec['clip']}: no skeleton to take the reference pose from")
    dec = decode(base64.b64decode(rec['acl']))
    ref = reference(rec['bones'])
    q, t, s = keys(dec, rec['track_to_bone'], ref)
    return write_psa(out_path, rec.get('name') or rec['clip'].rsplit('/', 1)[-1], q, t, s, ref,
                     rec['frames'], rec['seconds'], rec.get('rate_scale') or 1.0)


def decode_scalar(b):
    """ACL 2.1 float1f curves: constants, quantized ranges and unaligned raw floats.

    Format: ACL v2.1.0 core/impl/compressed_headers.h (scalar_tracks_header),
    core/impl/variable_bit_rates.h and decompression/impl/decompression.scalar.h.
    https://github.com/nfrechette/acl/tree/v2.1.0/includes/acl
    Returns samples as stored; a wrap-optimized closing sample is added by curve_tracks.
    """
    if len(b) < 52:
        raise Unsupported('truncated ACL scalar header')
    size, _hash, tag, version, algorithm, kind, nt, ns, rate, misc = struct.unpack_from('<IIIHBBIIfI', b)
    if size != len(b) or tag != TAG or (version, algorithm, kind) != (10, 0, 0):
        raise Unsupported(f'ACL scalar header: size {size}, version {version}, algorithm {algorithm}, type {kind}')
    if misc & 0x3fffffff or not np.isfinite(rate) or rate <= 0 or ns == 0:
        raise Unsupported('ACL scalar timing or flags')
    stride, meta, const, ranges, animated = struct.unpack_from('<5I', b, H)

    def span(offset, count):
        if offset < H + 20 or offset + count > size:
            raise Unsupported('ACL scalar data offset outside buffer')
        return b[offset:offset + count]

    codes = span(H + meta, nt)
    if any(c > 24 for c in codes):
        raise Unsupported('ACL scalar bit rate')
    widths = [32 if c == 24 else c for c in codes]
    if sum(widths) != stride:
        raise Unsupported('ACL scalar frame stride does not match track widths')
    constants = iter(struct.unpack(f'<{codes.count(0)}f', span(H + const, 4 * codes.count(0))))
    nr = sum(0 < c < 24 for c in codes)
    rg = iter(struct.unpack(f'<{2 * nr}f', span(H + ranges, 8 * nr)))
    read = _bits(span(H + animated, (stride * ns + 7) // 8))
    result = np.empty((ns, nt), dtype=float)
    offset = 0
    for i, width in enumerate(widths):
        if width == 0:
            result[:, i] = next(constants)
        elif width == 32:
            result[:, i] = [_float(read(f * stride + offset, width)) for f in range(ns)]
        else:
            lo, extent = next(rg), next(rg)
            result[:, i] = [read(f * stride + offset, width) / ((1 << width) - 1) * extent + lo
                            for f in range(ns)]
        offset += width
    if not np.isfinite(result).all():
        raise Unsupported('non-finite ACL scalar values')
    return dict(values=result, rate=rate, wrap=bool(misc & WRAP))


def curve_tracks(record):
    """The same FloatCurves shape as CUE4Parse, with the codec's linear sample interpolation."""
    decoded = decode_scalar(base64.b64decode(record['acl'], validate=True))
    values = decoded['values']
    names = [n['DisplayName'] for n in record['curve_names']]
    if len(names) != values.shape[1] or len(set(n.casefold() for n in names)) != len(names):
        raise Unsupported('ACL scalar curve names do not match the tracks')
    if decoded['wrap']:
        values = np.concatenate([values, values[:1]], axis=0)
    duration = (len(values) - 1) / decoded['rate']
    if abs(duration - record['seconds']) > max(1e-5, duration * 1e-5):
        raise Unsupported(f'ACL scalar duration {duration} != sequence length {record["seconds"]}')
    return {'FloatCurves': [dict(CurveName=name, FloatCurve=dict(
        Keys=[dict(Time=f / decoded['rate'], Value=float(v), InterpMode='RCIM_Linear')
              for f, v in enumerate(values[:, i])],
        PreInfinityExtrap='RCCE_Constant', PostInfinityExtrap='RCCE_Constant'))
        for i, name in enumerate(names)]}
