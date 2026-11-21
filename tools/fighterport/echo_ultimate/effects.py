"""Read an Ultimate effect file (`effect/fighter/<name>/ef_<name>.eff`).

The file is a small list of names ("EFFN"), then the particle data ("VFXB") at 0x1000: a tree of sections, each
headed by a four-letter name. `ESTA` holds the effect sets (`ESET`, one per effect a script can call, named
`P_<Fighter><Thing>`); a set holds its emitters (`EMTR`, named `smoke1`, `flash1`, ...), and an emitter may hold more
emitters (the particles its particles give off). `GRTF` holds the pictures, as one Switch texture archive ("BNTX").

What is read here: the tree, the sets and their emitters by name, the pictures, and an emitter's own numbers.

The places of an emitter's numbers are READINGS: no description of this version of the block was to hand, so they
were found by laying Duck Hunt's emitters side by side (2026-11-12). What supports each: the five key counts match
the number of filled rows in the five key tables for every emitter looked at; the picture number matches the name
table's; `line1_alpha` and `line1_add` differ in the blend byte and nothing else of the kind; smoke rises (gravity
+1) and feathers fall (-1); a spark lives 8 frames, a feather 44. Anything not listed in `emitter` is not known.
How an emitter gives its particles off is the least sure reading. Three numbers sit together: 60 in nearly every
emitter, a small count, and a rate. Read as "`rate` particles a frame for `count` frames, and (unless the emitter is
marked one-time) again every 60 frames", every emitter makes sense: each piece of a breaking clay pigeon is one
particle (count 1, rate 1), the can's explosion gives off its flashes, sparks and smoke over 3 to 10 frames, a rate of
1.5 or 2.5 adds up over its frames, and the feathers come to about five a second. Read as "one every `count` frames
for 60 frames" a hit spark would be given off sixty times.
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import nutexb

NONE = 0xFFFFFFFF
EMITTER_BYTES = 0xAC0                # an emitter's own block, in this version (0x16) of the format

# Switch texture format (high byte) -> (kind, bytes per pixel or per 4x4 block)
FORMATS = {0x02: ('r', 1), 0x09: ('rg', 2), 0x0B: ('rgba', 4), 0x0C: ('bgra', 4), 0x1A: ('bc1', 8), 0x1B: ('bc2', 16),
           0x1C: ('bc3', 16), 0x1D: ('bc4', 8), 0x1E: ('bc5', 16), 0x20: ('bc7', 16),
           # sixteen bits a pixel, no see-through (Wolf's effect file has one: ef_cmn_parts01). READING: which end the
           # red is at is taken from the format's name (R5G6B5: red in the high five bits), not checked against the game
           0x07: ('rgb565', 2), 0x08: ('bgr565', 2)}


def particle_data(data: bytes) -> bytes:
    """The particle data inside an effect file (from its "VFXB" mark on)."""
    at = data.find(b'VFXB')
    if at < 0:
        raise ValueError('no particle data in this effect file')
    return data[at:]


def sections(v: bytes, at=None, depth=0):
    """Every section of the tree, parents before children: dicts of magic, at, size, binary (where its own block
    starts, or None), depth and name (sets and emitters)."""
    if at is None:
        at = struct.unpack_from('<H', v, 0x16)[0]
    out, seen = [], 0
    while at + 0x20 <= len(v):
        seen += 1
        if seen > 100000:
            raise ValueError('the section list does not end')
        magic = v[at:at + 4]
        if not magic.isalnum():
            break
        size, child, nxt, attr, binary, _pad, count, _unk = struct.unpack_from('<IIIIIIHH', v, at + 4)
        row = dict(magic=magic.decode('ascii'), at=at, size=size, depth=depth, count=count,
                   binary=None if binary == NONE else at + binary, name='')
        if row['magic'] in ('ESET', 'EMTR') and row['binary'] is not None:
            row['name'] = v[row['binary'] + 16:row['binary'] + 80].split(b'\0')[0].decode('ascii', 'replace')
        out.append(row)
        if attr not in (NONE, 0):
            out.extend(dict(r, attribute=True) for r in sections(v, at + attr, depth + 1))
        if child not in (NONE, 0) and count:
            out.extend(sections(v, at + child, depth + 1))
        if nxt in (NONE, 0):
            break
        at += nxt
    return out


def effects(v: bytes):
    """{effect set name: [emitter rows, in order; an emitter inside another carries 'inside': its parent's name]}"""
    out, current, parents = {}, None, {}
    for row in sections(v):
        if row.get('attribute'):
            continue
        if row['magic'] == 'ESET':
            current = out.setdefault(row['name'], [])
            parents = {}
        elif row['magic'] == 'EMTR' and current is not None:
            parents[row['depth']] = row['name']
            inside = parents.get(row['depth'] - 1) if row['depth'] > 2 else None
            current.append(dict(row, **({'inside': inside} if inside else {})))
    return out


SHAPES = {0: 'point', 1: 'circle', 2: 'circle', 3: 'disc', 4: 'sphere', 5: 'sphere', 6: 'sphere', 7: 'ball',
          8: 'cylinder', 9: 'cylinder', 10: 'box', 11: 'box', 12: 'line', 13: 'line', 14: 'rectangle'}


# how a particle goes through a picture's frames. 'random' (each particle one frame, of the first `frames_random`)
# is sure: the smokes and sparks use it. The other three are named from the order such lists usually take: a reading.
FRAMES = {0: 'one', 1: 'over_life', 2: 'once', 3: 'loop', 4: 'random'}


def _keys(v, at, count, width=3):
    """`count` rows of (values..., time 0..1) from a key table of eight 16-byte rows."""
    rows = []
    for i in range(min(count, 8)):
        *values, time = struct.unpack_from('<4f', v, at + 16 * i)
        rows.append(dict(time=time, value=tuple(values[:width]) if width > 1 else values[0]))
    return rows


def emitter(v: bytes, at: int):
    """One emitter's numbers, from its block at `at` (a row's 'binary'). Times of keys run 0..1 over a particle's
    life; speeds are units a frame; angles are radians unless said. See the module's note: these places are readings."""
    f = lambda off, n=1: struct.unpack_from(f'<{n}f', v, at + off) if n > 1 else struct.unpack_from('<f', v, at + off)[0]
    u = lambda off: struct.unpack_from('<I', v, at + off)[0]
    counts = struct.unpack_from('<5I', v, at + 0x60)
    out = dict(
        name=v[at + 16:at + 80].split(b'\0')[0].decode('ascii', 'replace'),
        # what a particle looks like over its life
        colour_keys=_keys(v, at + 0x3C0, counts[0]), alpha_keys=_keys(v, at + 0x440, counts[1], 1),
        colour2_keys=_keys(v, at + 0x4C0, counts[2]), alpha2_keys=_keys(v, at + 0x540, counts[3], 1),
        size_keys=_keys(v, at + 0x600, counts[4]),
        colour=f(0x9A0, 4), colour2=f(0x9B0, 4),            # the fixed colours (r, g, b, a), used where there are no keys
        size=f(0x9C0, 3), size_random=f(0x9CC, 3),          # size, and how far it varies, per cent
        life=u(0x8B8), life_random=u(0x8BC),                # frames, and per cent
        blend='add' if v[at + 0x89E] == 1 else 'normal',
        textures=[t for t in (u(0x9F0), u(0xA10), u(0xA30)) if t != NONE],
        # a picture cut into frames: how many across and down, and how a particle goes through them
        grid=(max(1, int(f(0x308))), max(1, int(f(0x30C)))), frames=FRAMES.get(v[at + 0xA50], v[at + 0xA50]),
        frame_table=list(struct.unpack_from(f'<{min(int(f(0x110)), 32)}I', v, at + 0x120)), frames_random=int(f(0x118)),
        # how it is given off
        # (it starts `start` frames in and gives off `rate` particles a frame for `emit_frames` frames; unless
        # `one_time`, it does so again every `loop` frames. See the module's note on how this was read.)
        one_time=bool(v[at + 0x7F0]), start=u(0x7F4), loop=u(0x7F8), emit_frames=u(0x7FC), rate=f(0x800),
        shape=SHAPES.get(u(0x838), u(0x838)), radius=f(0x858, 3),
        # how it moves
        speed=f(0x964), speed_along=f(0x968), direction=f(0x96C, 3), spread_degrees=f(0x978), speed_random=f(0x98C),
        gravity=f(0x814), gravity_direction=f(0x818, 3), drag=f(0xC0),
        turn=f(0x700, 3), turn_random=f(0x710, 3), spin=f(0x720, 3), spin_random=f(0x730, 3), spin_keep=f(0x72C),
    )
    return out


def texture_names(v: bytes):
    """{picture number: name}, from the pictures' name table."""
    out = {}
    for row in sections(v):
        if row['magic'] == 'GTNT' and row['binary'] is not None:
            at, end = row['binary'], row['at'] + row['size']
            while at + 16 <= end:
                number, _high, step, length = struct.unpack_from('<IIII', v, at)
                if not length:
                    break
                out[number] = v[at + 16:at + 16 + length].split(b'\0')[0].decode('ascii', 'replace')
                if not step:
                    break
                at += step
    return out


def texture_archive(v: bytes) -> bytes:
    """The pictures' archive (a "BNTX" file) out of the particle data."""
    for row in sections(v):
        if row['magic'] == 'GRTF' and row['binary'] is not None:
            return v[row['binary']:row['at'] + row['size'] + 0x20]
    raise ValueError('this effect file holds no pictures')


def textures(archive: bytes, unread=None):
    """[(name, RGBA image of the top mip)] from a Switch texture archive.

    A picture in a format this reader does not know: with `unread` a list, it is left out and (name, format) is
    added to the list, so that one picture costs what is drawn with it and not the whole file (Wolf's effect file
    had one such picture of 49, and the driver died on it four minutes in). Without `unread` it is an error, as
    it is for a caller that needs every picture."""
    from PIL import Image
    if archive[:4] != b'BNTX' or archive[0x20:0x24] != b'NX  ':
        raise ValueError('not a Switch texture archive')
    count, = struct.unpack_from('<I', archive, 0x24)
    table, = struct.unpack_from('<q', archive, 0x28)
    out = []
    for i in range(count):
        info, = struct.unpack_from('<q', archive, table + 8 * i)
        if archive[info:info + 4] != b'BRTI':
            raise ValueError(f'picture {i} is not where the archive says')
        fmt, = struct.unpack_from('<I', archive, info + 0x1C)
        width, height = struct.unpack_from('<ii', archive, info + 0x24)
        name_at, = struct.unpack_from('<q', archive, info + 0x60)
        mips_at, = struct.unpack_from('<q', archive, info + 0x70)
        length, = struct.unpack_from('<H', archive, name_at)
        name = archive[name_at + 2:name_at + 2 + length].decode('ascii', 'replace')
        start, = struct.unpack_from('<q', archive, mips_at)
        kind, unit = FORMATS.get(fmt >> 8, (None, 0))
        if kind is None:
            if unread is None:
                raise ValueError(f'{name}: picture format {fmt:#x} is not handled (echo_ultimate/effects.py FORMATS)')
            unread.append((name, fmt))
            continue
        data = archive[start:]
        if kind in ('rgb565', 'bgr565'):
            raw = nutexb.unswizzle(data, width, height, unit)
            px = [int.from_bytes(raw[k:k + 2], 'little') for k in range(0, width * height * 2, 2)]
            hi, mid, lo = ([(p >> 11 & 31) * 255 // 31 for p in px], [(p >> 5 & 63) * 255 // 63 for p in px],
                           [(p & 31) * 255 // 31 for p in px])
            red, blue = (hi, lo) if kind == 'rgb565' else (lo, hi)
            image = Image.merge('RGBA', [Image.frombytes('L', (width, height), bytes(c))
                                         for c in (red, mid, blue, [255] * len(px))])
        elif kind in ('r', 'rg', 'rgba', 'bgra'):
            raw = nutexb.unswizzle(data, width, height, unit)
            if kind == 'r':
                grey = Image.frombytes('L', (width, height), raw)
                image = Image.merge('RGBA', (grey, grey, grey, grey))
            elif kind == 'rg':
                two = Image.frombytes('LA', (width, height), raw)
                image = two.convert('RGBA')
            else:
                image = Image.frombytes('RGBA', (width, height), raw, 'raw', 'RGBA' if kind == 'rgba' else 'BGRA')
        else:
            bw, bh = -(-width // 4), -(-height // 4)
            raw = nutexb.unswizzle(data, bw, bh, unit)
            n = int(kind[2])
            image = Image.frombytes({4: 'L', 5: 'RGB'}.get(n, 'RGBA'), (bw * 4, bh * 4), raw, 'bcn', (n, kind.upper()))
            if n == 4:                                  # one channel: the picture is its own see-through mask
                image = Image.merge('RGBA', (image, image, image, image))
            elif n == 5:                                # two channels: brightness and mask
                grey, mask, _ = image.split()
                image = Image.merge('RGBA', (grey, grey, grey, mask))
            image = image.convert('RGBA').crop((0, 0, width, height))
        out.append((name, image))
    return out


def read(path):
    """-> {'effects': {set name: [emitter names]}, 'textures': [(name, image)]}"""
    v = particle_data(Path(path).read_bytes())
    return dict(effects={k: [e['name'] for e in rows] for k, rows in effects(v).items()},
                textures=textures(texture_archive(v)))


def unread_pictures(path):
    """The pictures of an effect file this reader cannot read, and how many it can: ([(name, format)], count read).
    Seconds; asked before any long stage (`fighter_port.preflight`, and the driver before it makes the clip bank)."""
    unread = []
    v = particle_data(Path(path).read_bytes())
    try:
        archive = texture_archive(v)
    except ValueError:                                  # a file with no pictures at all has none to fail on
        return [], 0
    return unread, len(textures(archive, unread))


# ---- the name list at the head of the file, and four more readings of an emitter's block ----

NAME_LIST = b'EFFN'
# how each of an emitter's four tracks (colour, second colour, alpha, second alpha) is driven
TRACK_MODES = {0: 'fixed', 2: 'keys', 3: 'random'}


def set_names(v: bytes):
    """The effect sets' names in the order the file holds them (the first set is number 1 in the name list)."""
    return [row['name'] for row in sections(v) if row['magic'] == 'ESET' and not row.get('attribute')]


def names(data: bytes):
    """{the name a script calls an effect by, lower case: its set's name, or None for a name with no particle set}

    From the name list at the head of the file (`data` is the whole file). A script carries hash40 of the lower-case
    name (`echo_ultimate.gamedata.prc.hash40`); the list holds the names in capitals ("DUCKHUNT_FEATHER").

    The layout is a READING, worked out from the bytes of five files (Duck Hunt, Shulk, Byleth, Cloud and the common
    file): "EFFN", a version, then four 16-bit numbers: how many names; A; B; and a 1 or 2 whose meaning is not known.
    At 0x10 one 16-byte row a name: 32 bits of flags (not read), the number of its set counted from 1 in the file's
    own order (0: none; Cloud's sword strokes, which are drawn with models, have 0), and 8 bytes that are zero except
    in the two files where A and B are not. Then B rows of 4 bytes (not read), A strings (empty in both files that
    have any), and the names, each ended by a zero byte. What supports it: in all five files every name with a set
    number names that set but for spelling (DUCKHUNT_ATK_SMOKE_R is set P_DuckhuntAtkSmokeR, SYS_HIT_NORMAL_S is
    P_CmnHitNormalS), and the lower-case names are the ones Duck Hunt's own scripts call (their hashes match).
    One name need not match its set's: DUCKHUNT_FINAL_MUZZLE is set P_DuckhuntFinalMuzzleflash.
    """
    if data[:4] != NAME_LIST:
        raise ValueError('this effect file does not start with a name list')
    count, extra, rows, _unknown = struct.unpack_from('<4H', data, 8)
    at = 0x10 + 16 * count + 4 * rows
    limit = data.find(b'VFXB')
    limit = len(data) if limit < 0 else limit
    texts = []
    for _ in range(extra + count):
        end = data.find(b'\0', at, limit)
        if end < 0:
            raise ValueError('the name list runs into the particle data')
        texts.append(data[at:end].decode('ascii', 'replace'))
        at = end + 1
    sets = set_names(particle_data(data))
    out = {}
    for i, text in enumerate(texts[extra:]):
        number, = struct.unpack_from('<I', data, 0x14 + 16 * i)
        if not text or number > len(sets):
            raise ValueError(f'the name list does not read as expected at name {i} ({text!r}, set {number})')
        out[text.lower()] = sets[number - 1] if number else None
    return out


def model(v: bytes, at: int):
    """The number of the 3D shape an emitter draws its picture on, or None when it draws a flat picture that faces
    the camera. `at` is the emitter's block (a row's 'binary').

    A READING: the 32 bits at 0x8C8 of the block are 0xFFFFFFFF in 122 of Duck Hunt's 163 emitters and, in the
    other 41, one of the 14 numbers listed in the file's model name table (section G3NT, under the models, G3PR;
    an earlier count of 13 missed the final smash's can, which is there). The 41 are the rings, shock waves, lines,
    the can and the clay pigeon's trace, most with a size of exactly 1 (a model's own size), which fits. In eleven
    fighters' files every number an emitter names is in the table. The shapes are read by `shapes`."""
    number, = struct.unpack_from('<I', v, at + 0x8C8)
    return None if number == NONE else number


def track_modes(v: bytes, at: int):
    """How each of an emitter's four tracks is driven: {'colour', 'colour2', 'alpha', 'alpha2': 'fixed' (the fixed
    colour applies and the key table is left over), 'keys' (the key table, over the life) or 'random' (each particle
    takes one of the listed values)}. An unknown value is given as its number.

    A READING: four bytes at 0x99C of the block, in the order colour, second colour, alpha, second alpha. Over Duck
    Hunt's and Shulk's files (about 520 emitters): a colour byte of 0 always comes with an empty key table, 2 with
    two or more keys, 3 with keys that all sit at time 0; an alpha byte of 2 always comes with two or more keys, and
    of 0 mostly with the single default key (1.0 at time 0) beside a fixed alpha that differs from it, so the fixed
    alpha is the live one there."""
    raw = v[at + 0x99C:at + 0x9A0]
    return {k: TRACK_MODES.get(b, b) for k, b in zip(('colour', 'colour2', 'alpha', 'alpha2'), raw)}


def mirror(v: bytes, at: int):
    """How an emitter's first picture is repeated over a particle: 'none' (the picture once), 'both' (the picture is
    a quarter of a whole: it is drawn four times, mirrored across and down, its bottom right corner at the middle),
    or the number found when it is neither.

    A READING: the byte at 0xA54 of the block. In Duck Hunt's file it is 3 for the four emitters that use the two
    pictures that are plainly a quarter of a whole (ef_cmn_flash04, a quarter of a star of light, and
    ef_duckhunt_target00, a quarter of a gun sight), 1 for two emitters of the final smash's smoke, and 0 for the
    other 157. What 1 and 2 mirror is not known."""
    value = v[at + 0xA54]
    return {0: 'none', 3: 'both'}.get(value, value)


def draw_type(v: bytes, at: int):
    """How an emitter lays its particle (a flat picture or a 3D shape): 'billboard' (faces the camera),
    'complex_billboard', 'y_billboard' (turns about its up axis only), 'polygon_xy' (lies in the effect's own space
    as it is), 'polygon_xz' (laid flat, face up), 'velocity_look' (its up axis along its speed),
    'velocity_look_polygon', or the number found when it is none of these.

    A READING: the byte at 0x8AA of the block, with the names of the usual list of such kinds in that order. What
    supports it, over Greninja's 200 emitters and Duck Hunt's 163: the flat ones with 4 are the three shadows on the
    ground and nothing else; 5 holds the streaks that fly (speed lines, water jets, muzzle flashes) and 0 the smoke,
    sparks and feathers; a ring model drawn in its own XY plane is used with 4 by the gun's ground light and with 0
    by the round impact flashes, and the shuriken's ring, whose model already lies in XZ, with 3."""
    value = v[at + 0x8AA]
    return DRAW_TYPES.get(value, value)


DRAW_TYPES = {0: 'billboard', 1: 'complex_billboard', 2: 'y_billboard', 3: 'polygon_xy', 4: 'polygon_xz',
              5: 'velocity_look', 6: 'velocity_look_polygon'}
SHADER_MODES = {0: 'plain', 1: 'refraction', 2: 'distortion'}


def shader_mode(v: bytes, at: int):
    """What an emitter's pictures are for: 'plain' (they are drawn), 'refraction' (it bends what is behind it and
    draws nothing of its own) or 'distortion' (one picture, a map of offsets, bends where the others are read and
    is not drawn itself); the number found when it is none of these.

    A READING: the byte at 0x910 of the block (0x908 always holds the same). Over eleven fighters' files (2198
    emitters): the 32 with 1 are named for it (rifraction1, refraction, ring_rif, wind_rif, indirect1) or draw a
    water ripple picture twice; of the 265 with 2, all but a handful have a picture named "indirect" or
    "distortion", most often the first; of the 1901 with 0, four do."""
    value = v[at + 0x910]
    return SHADER_MODES.get(value, value)


JOINS = {0: 'multiply', 1: 'add', 2: 'subtract'}


def combiner(v: bytes, at: int):
    """How an emitter's second and third pictures are joined to what the pictures before them make:
    {'colour': [the second's, the third's], 'alpha': [the same]}, each 'multiply', 'add', 'subtract' or the number
    found when it is none of these.

    A READING: the bytes at 0x902 and 0x903 of the block (colour) and 0x905 and 0x906 (alpha), in the order of the
    usual list of an emitter's combiner settings (how each later picture's colour is joined, the particle colour's,
    then the same for alpha), with 0, 1, 2 read as multiply, add, subtract. What supports it, over eleven fighters'
    files: these bytes are 0 to 3 and nothing else; where the second picture is a gradient ("grade", a fade made to
    be multiplied in), its colour byte is 0 in 66 of 71 emitters and its alpha byte in 60, as it is for 150 of 152
    other second pictures. What 3 is (three emitters) is not known, nor how a picture's channels are chosen as
    its input (that is not read): see `fighter_port.effect_shapes`."""
    return dict(colour=[JOINS.get(v[at + 0x902 + k], v[at + 0x902 + k]) for k in range(2)],
                alpha=[JOINS.get(v[at + 0x905 + k], v[at + 0x905 + k]) for k in range(2)])


def bends(name):
    """Whether a picture is, by its name, a map of offsets (an "indirect" or "distortion" picture) and not one that
    is drawn. A READING from the names: such pictures look like soft noise in two channels."""
    name = str(name).lower()
    return 'indirect' in name or 'distortion' in name


# ---- the 3D shapes some emitters draw their picture on (section G3PR) ----
#
# G3PR holds one Switch model archive ("BFRES", version 0.9, little-endian), read by hand here. Its header: the
# number of models (16 bits at 0xDC), where the model list starts (64 bits at 0x28), where the buffer of vertex and
# index data is described (64 bits at 0xB0: 32 bits not used here, its size, then 64 bits: where it starts). Each
# model ("FMDL", 0x78 bytes) gives its name (+0x08), its vertex lists (+0x20, "FVTX" blocks of 0x58 bytes), its
# shapes (+0x28, "FSHP" blocks of 0x60 bytes) and how many of each (16 bits at +0x68 and +0x6A). A vertex list
# gives its attributes (+0x08: 16 bytes each, a name such as _p0, a format, an offset in the vertex and a buffer
# number), the size and stride of each buffer (+0x30, +0x38), where its data starts in the buffer (32 bits at
# +0x48), how many attributes (8 bits at +0x4C) and vertices (32 bits at +0x50). A shape gives its vertex list's
# number (16 bits at +0x56) and its first mesh (+0x18): where its indices start in the buffer (32 bits at +0x20),
# what they draw (+0x24, 3: triangles), their size (+0x28, 0: 8 bits, 1: 16, 2: 32), how many (+0x2C) and the
# first vertex (+0x30).
#
# What supports these readings: every model, list, shape and skeleton is found under its four-letter mark where
# the offsets say, in eleven fighters' files (Greninja's 35 models, Duck Hunt's 14); the model count equals the
# rows of G3NT; a list's vertex count times its stride is the size its buffer gives (Greninja's kunai: 692 x 24);
# the formats are those of the format names' own numbering (0x1805 three 32-bit floats for _p0, 0x0E02 10-10-10-2
# for the normal _n0, 0x0B01 four bytes for the colour _c0, 0x1201 / 0x1205 / 0x0901 / 0x1202 for the UV _u0);
# every index is below its list's vertex count; and the shapes are what their names say (a ring is a flat
# annulus, the kunai a long blade along +Y, the attack lines a cylinder along +Z).
#
# G3NT ties a model to the number an emitter names (`model`): one row a model, in the models' order, each a
# 32-bit number, a step to the next row, and a small map of which vertex attribute is which (position, normal,
# -, colour, uv, -). The order is a READING: by it every emitter that draws on a shape draws on a model named
# for its own effect (P_GekkougaMizusyuriken's ring1 on p_gekkougamizusyuriken_ring1, kunai1 on
# p_gekkougasword_kunai1), and each row's map has a colour exactly where its model has a _c0 attribute.
#
# Each model also has a skeleton of one joint, whose place is often far from nothing (Greninja's
# cmn_impactring3 is moved 61 units to the side, flash2 41): the leftover of where the model sat when it was
# made. It is NOT applied: an effect drawn 61 units off its emitter would be nowhere near the fighter. READING.

_VERTEX_FORMATS = {0x1805: ('<f4', 3, None), 0x1505: ('<f2', 4, None), 0x1705: ('<f4', 2, None),
                   0x1205: ('<f2', 2, None), 0x1201: ('<u2', 2, 65535.0), 0x1202: ('<i2', 2, 32767.0),
                   0x0901: ('u1', 2, 255.0), 0x0B01: ('u1', 4, 255.0), 0x0E02: (None, 1, None)}
_INDEX_FORMATS = {0: '<u1', 1: '<u2', 2: '<u4'}
TRIANGLES = 3


def _bfres_string(b, at):
    length, = struct.unpack_from('<H', b, at)
    return b[at + 2:at + 2 + length].decode('ascii', 'replace')


def shape_numbers(v: bytes):
    """The numbers G3NT gives the models, in the models' order (the numbers `model` returns)."""
    out = []
    for row in sections(v):
        if row['magic'] == 'G3NT' and row['binary'] is not None:
            at, end = row['binary'], row['at'] + row['size'] + 0x20
            while at + 16 <= end:
                number, _high, step, _length = struct.unpack_from('<IIII', v, at)
                out.append(number)
                if not step:
                    break
                at += step
    return out


def shapes(v: bytes):
    """{model number (as `model` gives it): {'name', 'positions': (n, 3) floats, 'uvs': (n, 2) floats (0 where
    the model has none), 'colours': (n, 4) floats 0..1 (1 where the model has none), 'triangles': (m, 3) vertex
    numbers}} for every model of the file's
    G3PR (empty when it has none). The vertices are the model's own, in the effect's units (see the notes above:
    the model's own joint is not applied). UVs run 0..1 across the picture, (0, 0) at its top left."""
    import numpy as np
    block = next((row for row in sections(v) if row['magic'] == 'G3PR' and row['binary'] is not None), None)
    if block is None:
        return {}
    b = v[block['binary']:]
    if b[:8] != b'FRES    ' or b[0x0C:0x0E] != b'\xff\xfe':
        raise ValueError('G3PR does not hold a little-endian Switch model archive')
    b = b[:struct.unpack_from('<I', b, 0x1C)[0]]          # the archive's own size (the section's, in every file seen)
    numbers = shape_numbers(v)
    count, = struct.unpack_from('<H', b, 0xDC)
    if count != len(numbers):
        raise ValueError(f'G3PR holds {count} models and G3NT names {len(numbers)}')
    models, = struct.unpack_from('<Q', b, 0x28)
    info, = struct.unpack_from('<Q', b, 0xB0)
    _unused, _size, buffer = struct.unpack_from('<IIQ', b, info)
    out = {}
    for i, number in enumerate(numbers):
        m = models + 0x78 * i
        if b[m:m + 4] != b'FMDL':
            raise ValueError(f'model {i} of G3PR is not where the list says')
        name = _bfres_string(b, struct.unpack_from('<Q', b, m + 0x08)[0])
        lists, shapes_at = struct.unpack_from('<QQ', b, m + 0x20)
        _lists, n_shapes = struct.unpack_from('<HH', b, m + 0x68)
        positions, uvs, colours, triangles, base = [], [], [], [], 0
        for k in range(n_shapes):
            s = shapes_at + 0x60 * k
            if b[s:s + 4] != b'FSHP':
                raise ValueError(f'{name}: shape {k} is not where the model says')
            which, = struct.unpack_from('<H', b, s + 0x56)
            x = lists + 0x58 * which
            if b[x:x + 4] != b'FVTX':
                raise ValueError(f'{name}: vertex list {which} is not where the model says')
            attributes, = struct.unpack_from('<Q', b, x + 0x08)
            sizes_at, strides_at = struct.unpack_from('<QQ', b, x + 0x30)
            start, = struct.unpack_from('<I', b, x + 0x48)
            n_attributes, n_buffers = b[x + 0x4C], b[x + 0x4D]
            vertices, = struct.unpack_from('<I', b, x + 0x50)
            starts, at_ = [], buffer + start
            for j in range(n_buffers):
                starts.append(at_)
                at_ += -(-struct.unpack_from('<I', b, sizes_at + 0x10 * j)[0] // 8) * 8
            got = {}
            for j in range(n_attributes):
                a = attributes + 0x10 * j
                label = _bfres_string(b, struct.unpack_from('<Q', b, a)[0])
                fmt, offset, buf = struct.unpack_from('<IHH', b, a + 8)
                kind = _VERTEX_FORMATS.get(fmt)
                if kind is None:
                    raise ValueError(f'{name}: vertex attribute {label} has a format not read here ({fmt:#x})')
                if kind[0] is None:
                    continue
                stride, = struct.unpack_from('<I', b, strides_at + 0x10 * buf)
                rows = np.frombuffer(b, dtype=np.uint8, count=vertices * stride, offset=starts[buf]).reshape(vertices, stride)
                width = np.dtype(kind[0]).itemsize * kind[1]
                values = np.ascontiguousarray(rows[:, offset:offset + width]).view(kind[0]).reshape(vertices, kind[1])
                values = values.astype(np.float32)
                got[label] = values / kind[2] if kind[2] else values
            mesh, = struct.unpack_from('<Q', b, s + 0x18)
            face, primitive, index_format, indices, first = struct.unpack_from('<5I', b, mesh + 0x20)
            if primitive != TRIANGLES:
                raise ValueError(f'{name}: its mesh draws primitive {primitive}, not triangles')
            index = np.frombuffer(b, dtype=_INDEX_FORMATS[index_format], count=indices,
                                  offset=buffer + face).astype(np.int64) + first
            if '_p0' not in got or (len(index) and index.max() >= vertices):
                raise ValueError(f'{name}: shape {k} has no positions or an index past its vertices')
            positions.append(got['_p0'][:, :3])
            uvs.append(got.get('_u0', np.zeros((vertices, 2), np.float32))[:, :2])
            colours.append(got.get('_c0', np.ones((vertices, 4), np.float32)))
            triangles.append(index.reshape(-1, 3) + base)
            base += vertices
        out[number] = dict(name=name, positions=np.concatenate(positions), uvs=np.concatenate(uvs),
                           colours=np.concatenate(colours), triangles=np.concatenate(triangles))
    return out


def emission(v: bytes, at: int):
    """Three more numbers of how an emitter gives its particles off, beside the ones `emitter` reads:
    {'interval': frames it skips between two givings-off, 'interval_random': up to this many more frames skipped,
     'by_distance': whether it gives off by how far it has moved and not by time}.

    A READING, from Duck Hunt's 163 emitters. The 32 bits at 0x808 of the block are 0 in most emitters and otherwise
    a small whole number (1, 2, 3, 5, 9, 10, 20, 100); the 32 bits at 0x80C are 0 or a whole number no larger than
    it. Read as "it gives off `rate` particles, then skips this many frames", these fit what the emitters are: a
    beam whose particle lives 2 frames has 1 (one particle at any moment), the rapid jab's lines have 1 or 3 plus
    up to 1 more, the feathers have 5, and an emitter inside another that should give off once in its parent's short
    life has 100.
    The byte at 0x7F2 is 1 only for the clay pigeon's trace and the gun sight's after-image, the two emitters that
    leave something behind them as they move.

    These fit badly with `emitter`'s reading of the number at 0x7F8 as "does so again every `loop` frames" for an
    emitter that is not one-time: by that reading the can's smoke trail gives off one puff a second and the rapid
    jab's lines one every five frames, and two emitters would give off for 110 frames of every 60. Over the five
    files to hand (Duck Hunt, Shulk, Cloud, Byleth and the common file), 124 of the 303 emitters that are not
    one-time would by that reading have less than one particle alive at a time, an effect that blinks; read with
    the interval 22 would, and a particle's life sits just above its interval again and again (a life of 6 with an
    interval of 3, 7 with 5, 5 with 3, 12 with 7 plus up to 3). Read with the interval, an emitter that is not
    one-time gives off without end until the game removes it, and what the 60 at 0x7F8 is stays unknown. Which
    reading is right was not seen in the game."""
    interval, more = struct.unpack_from('<2I', v, at + 0x808)
    return dict(interval=interval, interval_random=more, by_distance=bool(v[at + 0x7F2]))
