"""Where a stage's (or costume's) colours come from, read straight from the DAT, and
in-place edits of the two colour stores the live renderer cannot change: vertex
colours and colour animation keys.

HSD colours a drawable (a DOBJ: one material, one or more POBJ meshes) from up to
four places; the live renderer's `updateTexture` / `setMaterialColors` reach only
the first two:

* **textures** (TOBJ images; the TOBJ's colour map says how one combines: REPLACE
  puts the texture alone, MODULATE multiplies it with what is below it);
* **material** colours (the MOBJ's ambient / diffuse / specular descriptor);
* **vertex** colours: a POBJ vertex attribute GX_VA_CLR0 (or CLR1), one value per
  vertex, stored in an array (INDEX8/16) or inline in the display list (DIRECT,
  which is how every vanilla stage checked stores them). Bits 0-1 of the material's
  render flags pick the colour channel's source: 1 the material, 2 the vertex
  colours, 3 both;
* **animation**: a material animation (map_head group -> MatAnimJoint tree ->
  MatAnim -> AOBJ -> FOBJ tracks) whose diffuse/ambient/specular R, G, B tracks
  replace the descriptor colour every frame. Texture animations can do the same for
  a TOBJ's TEV colours (KONST/TEV0/TEV1 tracks).

Lights (LOBJ colours) and fog (a group's FogDesc colour) are read too.

Edits work on DAT bytes the renderer exported (its re-serialised file) and keep
every format and count: a vertex colour keeps its GX colour format and its alpha, a
key keeps its value format, frame, interpolation and slot. One buffer can serve
several objects (the renderer's save merges identical buffers, HSDRaw
RemoveDuplicateBuffers); a buffer that also serves pointer fields the caller did not
choose is first copied to the end of the data section and only the chosen pointer
fields are moved to the copy (`isolate`: no relocation entry changes, the moved
fields already are pointers).

Structural keys, not file offsets, name everything, because every export lays the
file out anew: an object is the renderer's own material id (`Group <g>:<i>`, the
i-th DOBJ of group g in joint pre-order, as HSDRawViewer MaterialColors numbers
them; on a costume `Model:<i>` for the model the renderer draws, its first `_joint`
root, and `Extra <g>:<i>` for another root); a track is (kind, group, animation,
joint, dobj, ..., track). A texture is named as the renderer lists it: `Group <g> /
Texture_<n>` on a stage, `Texture_<n>` on a costume's model (n: first use of an image
buffer in DOBJ order, so it is the renderer's own texture index there).

`readers` says which objects each pointer field serves. `isolate` can give a chosen
object its own copy of a shared BUFFER, but one pointer FIELD that two objects read
(a vertex descriptor list or a POBJ two DOBJs share, an AOBJ two MatAnims share, a
MOBJ two DOBJs share) moves for both: `entangled` names the objects an edit would
reach that way, which the edit cannot separate.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER = 0x20

# GX vertex attributes and their index types
GX_VA_POS, GX_VA_NRM, GX_VA_CLR0, GX_VA_CLR1, GX_VA_TEX0 = 9, 10, 11, 12, 13
GX_VA_NULL = 0xFF
GX_NONE, GX_DIRECT, GX_INDEX8, GX_INDEX16 = 0, 1, 2, 3

# GX colour component types -> (name, bytes)
COLOUR_FORMATS = {0: ('RGB565', 2), 1: ('RGB8', 3), 2: ('RGBX8', 4), 3: ('RGBA4', 2), 4: ('RGBA6', 3), 5: ('RGBA8', 4)}
_COMPONENT_BYTES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4}      # U8 S8 U16 S16 F32

JOBJ_HIDDEN, JOBJ_PTCL, JOBJ_SPLINE = 1 << 4, 1 << 5, 1 << 14

# MOBJ render flags
RENDER_DIFFUSE_SOURCE = 0x3          # 0 compat (material), 1 material, 2 vertex, 3 both
RENDER_LIGHTING = 1 << 2
COLORMAP = {0: 'none', 1: 'alpha_mask', 2: 'rgb_mask', 3: 'blend', 4: 'modulate', 5: 'replace', 6: 'pass',
            7: 'add', 8: 'sub'}
# Texture formats that hold lightness only (I4 I8 IA4 IA8), and palette formats (grey with an IA8 table)
GREY_FORMATS = {0, 1, 2, 3}
PALETTE_FORMATS = {8, 9, 10}
# A colour whose channels differ by at most this much (of 255) carries no hue worth naming
NEUTRAL_SPREAD = 10

# Animated colour channels: material tracks (HSD_A_M_*), texture TEV tracks (HSD_A_T_*), lights (HSD_A_L_*)
MAT_TRACKS = {1: ('ambient', 0), 2: ('ambient', 1), 3: ('ambient', 2), 4: ('diffuse', 0), 5: ('diffuse', 1),
              6: ('diffuse', 2), 7: ('specular', 0), 8: ('specular', 1), 9: ('specular', 2)}
TEX_TRACKS = {12: ('constant', 0), 13: ('constant', 1), 14: ('constant', 2), 16: ('tev0', 0), 17: ('tev0', 1),
              18: ('tev0', 2), 20: ('tev1', 0), 21: ('tev1', 1), 22: ('tev1', 2)}
LIGHT_TRACKS = {9: ('light', 0), 10: ('light', 1), 11: ('light', 2)}
MATERIAL_FIELDS = {'ambient': 0x00, 'diffuse': 0x04, 'specular': 0x08}
MATERIAL_SIZE = 0x14

# FOBJ value formats (flag & 0xE0) -> struct code; values are LITTLE endian in a big-endian file
_FOBJ_FORMAT = {0x00: 'f', 0x20: 'h', 0x40: 'H', 0x60: 'b', 0x80: 'B'}
_PRIMITIVES = {0x80, 0x88, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8}


class DatError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# the archive                                                                  #
# --------------------------------------------------------------------------- #
class Dat:
    """A mutable HSD archive: data-section reads and writes, pointer fields, append."""

    def __init__(self, data):
        self.b = bytearray(data)
        if len(self.b) < HEADER:
            raise DatError('Not a DAT file')
        (self.file_size, self.data_size, self.reloc_count, self.root_count,
         self.ref_count) = struct.unpack_from('>5I', self.b, 0)
        reloc_start = HEADER + self.data_size
        if reloc_start + self.reloc_count * 4 + (self.root_count + self.ref_count) * 8 > len(self.b):
            raise DatError('Truncated DAT file')
        self.relocs = set(struct.unpack_from(f'>{self.reloc_count}I', self.b, reloc_start))
        roots_start = reloc_start + self.reloc_count * 4
        strings = roots_start + (self.root_count + self.ref_count) * 8
        names = []
        for i in range(self.root_count + self.ref_count):
            offset, name = struct.unpack_from('>II', self.b, roots_start + i * 8)
            end = self.b.index(b'\0', strings + name)
            names.append((self.b[strings + name:end].decode('ascii', 'replace'), offset))
        self.roots, self.references = names[:self.root_count], names[self.root_count:]
        self._referents = None

    # -- primitives (data-section offsets) -- #
    def valid(self, off):
        return off is not None and 0 <= off < self.data_size

    def u8(self, off): return self.b[HEADER + off]
    def u16(self, off): return struct.unpack_from('>H', self.b, HEADER + off)[0]
    def u32(self, off): return struct.unpack_from('>I', self.b, HEADER + off)[0]
    def f32(self, off): return struct.unpack_from('>f', self.b, HEADER + off)[0]
    def raw(self, off, size): return bytes(self.b[HEADER + off:HEADER + off + size])

    def put(self, off, data):
        if not (self.valid(off) and off + len(data) <= self.data_size):
            raise DatError('Write outside the data section')
        self.b[HEADER + off:HEADER + off + len(data)] = data

    def ptr(self, off):
        """The pointer stored at `off`, or None. A 0 is NULL only when the field is no relocation."""
        if not self.valid(off) or off + 4 > self.data_size:
            return None
        value = self.u32(off)
        if value == 0 and off not in self.relocs:
            return None
        return value if self.valid(value) else None

    def referents(self, target):
        """Every pointer field (data offset) in the file that points at `target`."""
        if self._referents is None:
            self._referents = {}
            for field_off in self.relocs:
                if self.valid(field_off) and field_off + 4 <= self.data_size:
                    self._referents.setdefault(self.u32(field_off), []).append(field_off)
        return sorted(self._referents.get(target, ()))

    def append(self, blob, align=0x20):
        """Add `blob` at the end of the data section (32-byte aligned) -> its data offset.

        Pointers are data-section offsets and the relocation and root tables index
        the data section, so growing it at its end moves nothing that is referenced.
        """
        start = -(-self.data_size // align) * align
        end = -(-(start + len(blob)) // align) * align
        at = HEADER + self.data_size
        self.b[at:at] = bytes(start - self.data_size) + bytes(blob) + bytes(end - start - len(blob))
        grow = end - self.data_size
        self.data_size += grow
        self.file_size += grow
        struct.pack_into('>II', self.b, 0, self.file_size, self.data_size)
        self._referents = None
        return start

    def repoint(self, field_off, target):
        if field_off not in self.relocs:
            raise DatError('Only an existing pointer field can be moved')
        struct.pack_into('>I', self.b, HEADER + field_off, target)
        self._referents = None

    def data(self):
        return bytes(self.b)


def null_array(dat, off, limit=4096):
    """Entries of a NULL-terminated pointer array."""
    out = []
    while off is not None and len(out) < limit:
        value = dat.ptr(off + len(out) * 4)
        if value is None:
            break
        out.append(value)
    return out


def tree(dat, root, child=0x08, sibling=0x0C, limit=100000):
    """Pre-order node offsets of a child/next tree (HSDRaw TreeList / LiveJObj.Enumerate order)."""
    order, seen, stack = [], set(), [root]
    while stack:
        node = stack.pop()
        if node is None or node in seen:
            continue
        seen.add(node)
        order.append(node)
        if len(order) > limit:
            raise DatError('Runaway joint tree')
        stack.append(dat.ptr(node + sibling))
        stack.append(dat.ptr(node + child))
    return order


def chain(dat, first, next_off, limit=100000):
    out, seen, node = [], set(), first
    while node is not None and node not in seen and len(out) < limit:
        seen.add(node)
        out.append(node)
        node = dat.ptr(node + next_off)
    return out


def isolate(dat, fields, buffer, extent):
    """The buffer `fields` may write -> its offset: `buffer` itself when no other pointer
    field reads it, else a copy of its first `extent` bytes the fields are moved to."""
    fields = sorted(set(fields))
    if not set(dat.referents(buffer)) - set(fields):
        return buffer
    copy = dat.append(dat.raw(buffer, extent))
    for field_off in fields:
        dat.repoint(field_off, copy)
    return copy


# --------------------------------------------------------------------------- #
# colour codecs                                                                #
# --------------------------------------------------------------------------- #
def decode_colour(fmt, raw):
    """GX vertex colour bytes -> (r, g, b, a) 0..255."""
    if fmt == 0:
        v = int.from_bytes(raw[:2], 'big')
        return ((v >> 11 & 31) * 255 + 15) // 31, ((v >> 5 & 63) * 255 + 31) // 63, ((v & 31) * 255 + 15) // 31, 255
    if fmt in (1, 2):
        return raw[0], raw[1], raw[2], 255
    if fmt == 3:
        v = int.from_bytes(raw[:2], 'big')
        return (v >> 12 & 15) * 17, (v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17
    if fmt == 4:
        v = int.from_bytes(raw[:3], 'big')
        return tuple(((v >> s & 63) * 255 + 31) // 63 for s in (18, 12, 6, 0))
    if fmt == 5:
        return raw[0], raw[1], raw[2], raw[3]
    raise DatError(f'Unknown vertex colour format {fmt}')


def encode_colour(fmt, rgb, original):
    """(r, g, b) -> the format's bytes. Alpha (and RGBX8's pad byte) are kept from `original`."""
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb[:3])
    if fmt == 0:
        return (round(r * 31 / 255) << 11 | round(g * 63 / 255) << 5 | round(b * 31 / 255)).to_bytes(2, 'big')
    if fmt == 1:
        return bytes((r, g, b))
    if fmt in (2, 5):
        return bytes((r, g, b, original[3]))
    if fmt == 3:
        alpha = int.from_bytes(original[:2], 'big') & 15
        return (round(r / 17) << 12 | round(g / 17) << 8 | round(b / 17) << 4 | alpha).to_bytes(2, 'big')
    if fmt == 4:
        alpha = int.from_bytes(original[:3], 'big') & 63
        return (round(r * 63 / 255) << 18 | round(g * 63 / 255) << 12 | round(b * 63 / 255) << 6
                | alpha).to_bytes(3, 'big')
    raise DatError(f'Unknown vertex colour format {fmt}')


# --------------------------------------------------------------------------- #
# FOBJ keys                                                                    #
# --------------------------------------------------------------------------- #
def _varint(buf, cursor):
    total = shift = 0
    while True:
        if cursor >= len(buf):
            raise DatError('Truncated key stream')
        byte = buf[cursor]
        cursor += 1
        total |= (byte & 127) << shift
        if byte < 128:
            return total, cursor
        shift += 7
        if shift > 28:
            raise DatError('Runaway key stream')


def _number(buf, cursor, flag):
    code = _FOBJ_FORMAT[flag & 0xE0]
    value = struct.unpack_from('<' + code, buf, cursor)[0]
    return (float(value) if code == 'f' else value / (1 << (flag & 31))), cursor + struct.calcsize(code)


def decode_keys(buf, value_flag, tan_flag):
    """One FOBJ key stream -> [{frame, op, value, tan, value_at?, tan_at?}] (byte positions in `buf`).

    Opcodes (GXInterpolationType): 1 CON, 2 LIN, 3 SPL0, 4 SPL (value + tangent), 5 SLP
    (tangent only), 6 KEY (value only); 1-4 are followed by the frames to the next key.
    """
    if (value_flag & 0xE0) not in _FOBJ_FORMAT or (tan_flag & 0xE0) not in _FOBJ_FORMAT:
        raise DatError('Unknown key value format')
    cursor, clock, keys = 0, 0, []
    while cursor < len(buf):
        word, cursor = _varint(buf, cursor)
        op = word & 15
        if op == 0:
            break
        if op > 6:
            raise DatError(f'Unknown key opcode {op}')
        for _ in range((word >> 4) + 1):
            key = {'frame': clock, 'op': op, 'value': None, 'tan': None, 'step': 0}
            if op != 5:
                key['value_at'] = cursor
                key['value'], cursor = _number(buf, cursor, value_flag)
            if op in (4, 5):
                key['tan_at'] = cursor
                key['tan'], cursor = _number(buf, cursor, tan_flag)
            if op in (1, 2, 3, 4):
                key['step'], cursor = _varint(buf, cursor)
                clock += key['step']
            keys.append(key)
    return keys


def _put_varint(value):
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def encode_keys(keys, value_flag, tan_flag):
    """[{op, value, tan, step}] -> a key stream (one key per packet), the inverse of decode_keys."""
    out = bytearray()
    for key in keys:
        op = key['op']
        out += _put_varint(op)
        if op != 5:
            out += encode_number(key['value'] or 0.0, value_flag)
        if op in (4, 5):
            out += encode_number(key['tan'] or 0.0, tan_flag)
        if op in (1, 2, 3, 4):
            out += _put_varint(int(key['step']))
    return bytes(out)


def encode_number(value, flag):
    """A key value or tangent in the track's own format (clamped to what the format holds)."""
    code = _FOBJ_FORMAT[flag & 0xE0]
    if code == 'f':
        return struct.pack('<f', value)
    scaled = round(value * (1 << (flag & 31)))
    low, high = {'h': (-32768, 32767), 'H': (0, 65535), 'b': (-128, 127), 'B': (0, 255)}[code]
    return struct.pack('<' + code, max(low, min(high, scaled)))


def sample(keys, frame):
    """The track's value at `frame` (sysdolphin fobj.c, as model_import's fobj_reader replays it)."""
    p0 = p1 = d0 = d1 = t0 = t1 = 0.0
    last, first = 0, True
    for key in keys:
        op = key['op']
        if op == 5:
            d0, d1 = d1, key['tan']
            last = op
            continue
        if first:
            p1, d1, t1 = key['value'], key['tan'] or 0.0, float(key['frame'])
            last, first = op, False
            if frame <= t1:
                return p1
            continue
        p0, p1 = p1, key['value']
        t0, t1 = t1, float(key['frame'])
        if op == 4:
            d0, d1 = d1, key['tan']
        elif last != 5:
            d0, d1 = d1, 0.0
        if frame <= t1:
            if t1 == t0:
                return p1
            u = (frame - t0) / (t1 - t0)
            if last in (1, 6):
                return p0
            if last == 2:
                return p0 + (p1 - p0) * u
            return ((2 * u ** 3 - 3 * u ** 2 + 1) * p0 + (u ** 3 - 2 * u ** 2 + u) * (t1 - t0) * d0
                    + (-2 * u ** 3 + 3 * u ** 2) * p1 + (u ** 3 - u ** 2) * (t1 - t0) * d1)
        last = op
    return p1


# --------------------------------------------------------------------------- #
# the inventory                                                                #
# --------------------------------------------------------------------------- #
@dataclass
class VertexColours:
    """One POBJ's CLR0/CLR1 attribute: where its values are and how they are stored."""
    key: tuple                    # (group, joint, dobj, pobj, attr)
    fmt: int
    kind: str                     # 'index' | 'direct'
    pointer_field: int            # the attribute's array pointer, or the POBJ's display-list pointer
    buffer: int                   # data offset of the array / display list
    stride: int
    positions: list               # array entry indices ('index') or byte offsets in the display list ('direct')
    buffer_size: int = 0          # a display list's size (a direct attribute's buffer)

    def offsets(self):
        if self.kind == 'index':
            return [self.buffer + i * self.stride for i in self.positions]
        return [self.buffer + p for p in self.positions]

    @property
    def size(self):
        return COLOUR_FORMATS[self.fmt][1]

    @property
    def extent(self):
        """Bytes of the buffer this attribute reads (an array is as long as its largest index)."""
        if self.kind == 'direct':
            return self.buffer_size
        return (max(self.positions) + 1) * self.stride if self.positions else 0


@dataclass
class Track:
    key: tuple                    # ('material', g, anim, joint, dobj, i) / ('texture', g, anim, joint, dobj, texanim, i)
    owner: str                    # 'material' | 'texture' | 'light'
    channel: tuple                # ('diffuse', 0..2) ...
    pointer_field: int            # the FOBJDesc's buffer pointer
    buffer: int
    length: int
    value_flag: int
    tan_flag: int
    keys: list
    end_frame: float = 0.0
    loop: bool = False

    @property
    def set_key(self):
        """The R, G, B tracks of one field in one animation share this."""
        return (*self.key[:-1], self.channel[0])


@dataclass
class DrawObject:
    id: str                       # the renderer's material id: 'Group <g>:<i>'
    group: int
    joint: int
    dobj: int
    mobj: int | None
    render_flags: int
    material: int | None          # HSD_Material offset
    hidden: bool = False          # its joint is hidden at rest (a joint animation may show it)
    textures: list = field(default_factory=list)       # [{texmap, colormap, name, size, format, grey}]
    vertex: list = field(default_factory=list)         # [VertexColours]
    tracks: list = field(default_factory=list)         # [Track] of every animation that colours it
    undecodable: bool = False

    @property
    def rest_tracks(self):
        """The tracks of animation 0, the one a match starts with."""
        return [t for t in self.tracks if t.key[2] == 0]


@dataclass
class Inventory:
    dat: Dat
    objects: list
    tracks: list
    lights: list                  # [{where, offset, rgba, tracks}]
    fogs: list                    # [{group, offset, rgba, type}]
    groups: list

    def object(self, object_id):
        return next((o for o in self.objects if o.id == object_id), None)


def _attributes(dat, desc_off):
    attrs = []
    off = desc_off
    for _ in range(32):
        attr = dat.u32(off)
        if attr == GX_VA_NULL:
            return attrs
        attrs.append({'attr': attr, 'type': dat.u32(off + 4), 'count': dat.u32(off + 8), 'comp': dat.u32(off + 12),
                      'stride': dat.u16(off + 0x12), 'field': off + 0x14, 'data': dat.ptr(off + 0x14)})
        off += 0x18
    raise DatError('Unterminated vertex attribute list')


def _direct_width(a):
    attr, comp, count = a['attr'], a['comp'], a['count']
    if attr <= 8:
        return 1
    if attr in (GX_VA_CLR0, GX_VA_CLR1):
        if comp not in COLOUR_FORMATS:
            raise DatError('Unknown vertex colour format')
        return COLOUR_FORMATS[comp][1]
    size = _COMPONENT_BYTES.get(comp)
    if size is None:
        raise DatError('Unknown component type')
    if attr == GX_VA_POS:
        return size * (2 if count == 0 else 3)
    if attr == GX_VA_NRM:
        return size * (3 if count == 0 else 9)
    if GX_VA_TEX0 <= attr <= GX_VA_TEX0 + 7:
        return size * (1 if count == 0 else 2)
    raise DatError(f'Direct attribute {attr}')


def _pobj_colours(dat, pobj, key):
    """The CLR0/CLR1 attributes of one POBJ, with every vertex position they are read at."""
    desc = dat.ptr(pobj + 0x08)
    display = dat.ptr(pobj + 0x10)
    blocks = dat.u16(pobj + 0x0E)
    if desc is None or display is None or not blocks:
        return []
    attrs = _attributes(dat, desc)
    colours = [a for a in attrs if a['attr'] in (GX_VA_CLR0, GX_VA_CLR1) and a['type'] != GX_NONE]
    if not colours:
        return []
    widths = []
    for a in attrs:
        if a['type'] == GX_NONE:
            widths.append(0)
        elif a['type'] == GX_DIRECT:
            widths.append(_direct_width(a))
        elif a['type'] in (GX_INDEX8, GX_INDEX16):
            if a['attr'] == GX_VA_NRM and a['count'] == 2:
                raise DatError('NBT3 normals')
            widths.append(1 if a['type'] == GX_INDEX8 else 2)
        else:
            raise DatError('Unknown attribute type')
    found = {id(a): set() for a in colours}
    size = blocks * 32
    cursor, end = display, min(display + size, dat.data_size)
    while cursor + 3 <= end:
        op = dat.u8(cursor)
        if op == 0:
            break
        if op & 0xF8 not in _PRIMITIVES:
            raise DatError(f'Display list opcode {op:#x}')
        count = dat.u16(cursor + 1)
        cursor += 3
        for _ in range(count):
            for a, width in zip(attrs, widths):
                if id(a) in found:
                    if a['type'] == GX_DIRECT:
                        found[id(a)].add(cursor - display)
                    elif a['type'] == GX_INDEX8:
                        found[id(a)].add(dat.u8(cursor))
                    else:
                        found[id(a)].add(dat.u16(cursor))
                cursor += width
        if cursor > end:
            raise DatError('Display list overruns its size')
    out = []
    for a in colours:
        if a['comp'] not in COLOUR_FORMATS:
            raise DatError('Unknown vertex colour format')
        positions = sorted(found[id(a)])
        if a['type'] == GX_DIRECT:
            out.append(VertexColours((*key, a['attr']), a['comp'], 'direct', pobj + 0x10, display,
                                     COLOUR_FORMATS[a['comp']][1], positions, size))
        elif a['data'] is not None:
            out.append(VertexColours((*key, a['attr']), a['comp'], 'index', a['field'], a['data'],
                                     a['stride'] or COLOUR_FORMATS[a['comp']][1], positions))
    return out


def _tracks(dat, aobj, key, owner, channels):
    """The colour tracks of one AOBJ."""
    if aobj is None:
        return []
    out = []
    flags = dat.u32(aobj)
    for index, desc in enumerate(chain(dat, dat.ptr(aobj + 0x08), 0x00)):
        kind = dat.u8(desc + 0x0C)
        if kind not in channels:
            continue
        buffer = dat.ptr(desc + 0x10)
        length = dat.u32(desc + 0x04)
        if buffer is None or not 0 < length <= dat.data_size - buffer:
            continue
        value_flag, tan_flag = dat.u8(desc + 0x0D), dat.u8(desc + 0x0E)
        try:
            keys = decode_keys(dat.raw(buffer, length), value_flag, tan_flag)
        except (DatError, struct.error):
            continue
        out.append(Track((*key, index), owner, channels[kind], desc + 0x10, buffer, length, value_flag,
                         tan_flag, keys, dat.f32(aobj + 0x04), bool(flags & (1 << 29))))
    return out


def map_groups(dat):
    """[(group index, group record offset)] of a stage's map_head, or None for a file without one."""
    head = next((off for name, off in dat.roots if name == 'map_head'), None)
    if head is None:
        return None
    table, count = dat.ptr(head + 0x08), dat.u32(head + 0x0C)
    if table is None or not 0 < count <= 4096:
        return []
    return [(i, table + i * 0x34) for i in range(count)]


def _stadium(dat, groups):
    """The groups the renderer shows of Pokemon Stadium (its StageScene): the normal form only."""
    names = [n for n, _ in dat.roots + dat.references]
    if len(groups) == 10 and any(n.startswith('GrdPStadium') for n in names):
        return {0, 1, 2, 5}
    return None


def _lights(dat, groups):
    lights, fogs, tracks = [], [], []
    for gi, g in groups:
        for li, light in enumerate(null_array(dat, dat.ptr(g + 0x18))):
            lobj = dat.ptr(light)
            if lobj is None:
                continue
            found = []
            for ai, first in enumerate(null_array(dat, dat.ptr(light + 4))):
                for ni, node in enumerate(chain(dat, first, 0x00)):
                    found += _tracks(dat, dat.ptr(node + 4), ('light', gi, li, ai, ni), 'light', LIGHT_TRACKS)
            tracks += found
            lights.append({'where': f'Group {gi} light {li}', 'offset': lobj + 0x0C,
                           'rgba': tuple(dat.raw(lobj + 0x0C, 4)), 'tracks': found})
        fog = dat.ptr(g + 0x1C)
        if fog is not None:
            fogs.append({'group': gi, 'offset': fog + 0x10, 'rgba': tuple(dat.raw(fog + 0x10, 4)), 'type': dat.u32(fog)})
    return lights, fogs, tracks


def scan(data):
    """Read every colour store of a stage DAT (map_head groups) or a costume DAT (`*_joint` roots)."""
    dat = data if isinstance(data, Dat) else Dat(data)
    groups = map_groups(dat)
    objects, tracks, lights, fogs, listed, units = [], [], [], [], [], []
    if groups is not None:
        shown = _stadium(dat, groups)
        for gi, g in groups:
            root = dat.ptr(g)
            if root is not None and (shown is None or gi in shown):
                units.append((gi, root, null_array(dat, dat.ptr(g + 0x08))))
        lights, fogs, tracks = _lights(dat, groups)
    else:
        joint_roots = [(n, o) for n, o in dat.roots if n.endswith('_joint') and not n.endswith('anim_joint')]
        for gi, (name, off) in enumerate(joint_roots):
            stem = name[:-len('_joint')]
            units.append((gi, off, [o for n, o in dat.roots if n == stem + '_matanim_joint']))
    for gi, root, matanims in units:
        # The renderer's own names (module doc): a stage's groups; a costume's model, then its other roots.
        label = f'Group {gi}' if groups is not None else 'Model' if gi == 0 else f'Extra {gi}'
        texture_label = f'{label} / ' if groups is not None or gi else ''
        joints = tree(dat, root)
        running, textures_seen, by_slot = 0, {}, {}
        for ji, jobj in enumerate(joints):
            flags = dat.u32(jobj + 0x04)
            if flags & (JOBJ_PTCL | JOBJ_SPLINE):
                continue
            for di, dobj in enumerate(chain(dat, dat.ptr(jobj + 0x10), 0x04)):
                mobj = dat.ptr(dobj + 0x08)
                obj = DrawObject(f'{label}:{running}', gi, ji, di, mobj,
                                 dat.u32(mobj + 0x04) if mobj is not None else 0,
                                 dat.ptr(mobj + 0x0C) if mobj is not None else None, bool(flags & JOBJ_HIDDEN))
                running += 1
                for tobj in chain(dat, dat.ptr(mobj + 0x08), 0x04) if mobj is not None else ():
                    image = dat.ptr(tobj + 0x4C)
                    pixels = dat.ptr(image) if image is not None else None
                    tflags = dat.u32(tobj + 0x40)
                    row = {'texmap': dat.u32(tobj + 0x08), 'colormap': COLORMAP.get(tflags >> 16 & 15, 'none'),
                           'tobj': tobj}
                    if pixels is not None:
                        # Numbered as the renderer lists a group's textures: first use of an image buffer.
                        textures_seen.setdefault(pixels, len(textures_seen))
                        fmt, tlut = dat.u32(image + 8), dat.ptr(tobj + 0x50)
                        # `buffer`: the pixels' offset. Two groups can draw one buffer (Dream Land's front strip
                        # and side faces): one texture in the file, two in the renderer's list.
                        row.update(name=f'{texture_label}Texture_{textures_seen[pixels]}', format=fmt, buffer=pixels,
                                   size=(dat.u16(image + 4), dat.u16(image + 6)),
                                   grey=fmt in GREY_FORMATS or (fmt in PALETTE_FORMATS and tlut is not None
                                                                and dat.u32(tlut + 4) == 0))
                    obj.textures.append(row)
                for pi, pobj in enumerate(chain(dat, dat.ptr(dobj + 0x0C), 0x04)):
                    try:
                        obj.vertex += _pobj_colours(dat, pobj, (gi, ji, di, pi))
                    except (DatError, struct.error, IndexError):
                        obj.undecodable = True
                objects.append(obj)
                by_slot[(ji, di)] = obj
        # A MatAnimJoint tree pairs with the joint tree node by node and its MatAnim list with
        # the joint's DOBJ list entry by entry (HSD_JObjAddAnimAll): a node or entry without a
        # partner animates nothing.
        for ai, matanim_root in enumerate(matanims):
            for ji, node in enumerate(tree(dat, matanim_root, child=0x00, sibling=0x04)):
                for di, matanim in enumerate(chain(dat, dat.ptr(node + 0x08), 0x00)):
                    found = _tracks(dat, dat.ptr(matanim + 0x04), ('material', gi, ai, ji, di), 'material', MAT_TRACKS)
                    for ti, texanim in enumerate(chain(dat, dat.ptr(matanim + 0x08), 0x00)):
                        found += _tracks(dat, dat.ptr(texanim + 0x08), ('texture', gi, ai, ji, di, ti), 'texture',
                                         TEX_TRACKS)
                    tracks += found
                    if (ji, di) in by_slot:
                        by_slot[(ji, di)].tracks += found
        listed.append(gi)
    return Inventory(dat, objects, tracks, lights, fogs, listed)


# --------------------------------------------------------------------------- #
# what colours each object                                                     #
# --------------------------------------------------------------------------- #
def vertex_values(dat, colours):
    """[(offset, rgba)] of one attribute's referenced values."""
    return [(off, decode_colour(colours.fmt, dat.raw(off, colours.size))) for off in colours.offsets()]


def _hue(rgb):
    return max(rgb[:3]) - min(rgb[:3]) > NEUTRAL_SPREAD


def uses_vertex(obj):
    """True when the object's colour channel takes its vertex colours and it has some."""
    return obj.render_flags & RENDER_DIFFUSE_SOURCE in (2, 3) and any(v.positions for v in obj.vertex)


def colour_from(obj, dat, grey=None):
    """('texture' | 'material' | 'vertex' | 'animation' | 'mixed', parts): which store holds the
    object's colour, i.e. which edit changes it.

    The colour channel's source comes from the render flags (module doc); a texture
    whose colour map is REPLACE hides it; a material whose diffuse or ambient R/G/B is
    animated at match start (animation 0) shows the keys, not the descriptor. A store
    counts when it carries hue; when none does (a grey or white object), the store an
    edit would have to change counts. `grey`: names of textures known to hold
    lightness only (the live renderer's pixels); without it a texture's format decides.
    """
    source = obj.render_flags & RENDER_DIFFUSE_SOURCE
    named = [t for t in obj.textures if t.get('name') and t['colormap'] not in ('none', 'alpha_mask', 'pass')]
    replace = bool(named) and named[0]['colormap'] == 'replace'
    if replace:
        named = named[:1]
    coloured = [t for t in named if not (t['name'] in grey if grey is not None else t.get('grey'))]
    vertex = [rgba for v in obj.vertex for _, rgba in vertex_values(dat, v)] if source in (2, 3) and not replace else []
    material_used = not replace and (source != 2 or not vertex)
    animated = [t for t in obj.rest_tracks if t.owner == 'material' and t.channel[0] in ('diffuse', 'ambient')]
    animated = animated if material_used else []
    parts = []
    if coloured:
        parts.append('texture')
    if vertex and any(_hue(c) for c in vertex):
        parts.append('vertex')
    if animated:
        channels = {}
        for t in animated:
            channels.setdefault(t.channel[0], {})[t.channel[1]] = [k['value'] for k in t.keys if k['value'] is not None]
        if any(len(c) < 3 or len({tuple(v) for v in c.values()}) > 1 for c in channels.values()):
            parts.append('animation')
    elif material_used and obj.material is not None:
        fields = ('diffuse', 'ambient') if obj.render_flags & RENDER_LIGHTING else ('diffuse',)
        if any(_hue(dat.raw(obj.material + MATERIAL_FIELDS[f], 3)) for f in fields):
            parts.append('material')
    if not parts:          # a grey or white object: the store a colour edit would have to change
        parts.append('vertex' if vertex else 'animation' if animated else
                     'material' if material_used and obj.material is not None else 'texture')
    return (parts[0] if len(parts) == 1 else 'mixed'), parts


# --------------------------------------------------------------------------- #
# edits                                                                        #
# --------------------------------------------------------------------------- #
def store_fields(obj, store, fields=None):
    """The pointer fields an edit of one store of `obj` moves or writes through (module doc).

    'vertex': its colour attributes (only when it takes vertex colours); 'animation': the
    key buffers of its colour tracks of `fields` and, when one of those is a material
    field, the MOBJ's material pointer (the descriptor colour follows the keys)."""
    if store == 'vertex':
        return {a.pointer_field for a in obj.vertex if a.positions} if uses_vertex(obj) else set()
    chosen = [t for t in obj.tracks if fields is None or t.channel[0] in fields]
    out = {t.pointer_field for t in chosen}
    if obj.mobj is not None and obj.material is not None and {t.channel[0] for t in chosen} & set(MATERIAL_FIELDS):
        out.add(obj.mobj + 0x0C)
    return out


def readers(inventory, store, fields=None):
    """{pointer field: {object ids}} for one store over every object of the inventory."""
    out = {}
    for obj in inventory.objects:
        for field_off in store_fields(obj, store, fields):
            out.setdefault(field_off, set()).add(obj.id)
    return out


def entangled(inventory, objects, store, fields=None):
    """The ids of objects outside `objects` an edit of their `store` would change too: they
    read one of the same pointer fields, which `isolate` cannot split (module doc)."""
    chosen = {obj.id for obj in objects}
    by_field = readers(inventory, store, fields)
    out = set()
    for obj in objects:
        for field_off in store_fields(obj, store, fields):
            out |= by_field.get(field_off, set()) - chosen
    return sorted(out, key=_id_order)


def _id_order(object_id):
    label, _, index = object_id.rpartition(':')
    return label, int(index) if index.isdigit() else 0


def private_vertex(dat, attrs):
    """Move `attrs` onto buffers no other pointer field reads (module doc). Updates each attr.buffer."""
    by_buffer = {}
    for attr in attrs:
        by_buffer.setdefault(attr.buffer, []).append(attr)
    for buffer, group in by_buffer.items():
        new = isolate(dat, [a.pointer_field for a in group], buffer, max(a.extent for a in group))
        for attr in group:
            attr.buffer = new


def private_track(dat, track):
    """A track whose key buffer other tracks also read gets its own copy (R, G and B may share one)."""
    track.buffer = isolate(dat, [track.pointer_field], track.buffer, track.length)


def private_material(dat, obj):
    if obj.material is not None and obj.mobj is not None:
        obj.material = isolate(dat, [obj.mobj + 0x0C], obj.material, MATERIAL_SIZE)


def replace_track(dat, track, stream, value_flag, tan_flag):
    """Give a track a new key stream: appended, its FOBJDesc moved to it (length and formats set).

    For a channel whose keys must follow another channel's frames (a hue change needs R, G
    and B keyed alike); the FOBJDesc keeps its place, type and start frame.
    """
    desc = track.pointer_field - 0x10
    buffer = dat.append(stream)
    dat.repoint(track.pointer_field, buffer)
    dat.put(desc + 0x04, struct.pack('>I', len(stream)))
    dat.put(desc + 0x0D, bytes((value_flag, tan_flag)))
    track.buffer, track.length, track.value_flag, track.tan_flag = buffer, len(stream), value_flag, tan_flag
    track.keys = decode_keys(stream, value_flag, tan_flag)


def _rgba_hex(raw):
    return '#' + bytes(raw[:4]).hex()


# The ids the live renderer can address (its MaterialColors ids): a stage's groups, a costume's model.
RENDERED = ('Group ', 'Model:')


def colour_messages(before, after):
    """The protocol-2 stream messages that take a renderer showing `before` to `after`.

    Both are scans of the same model: `before` the renderer's export, `after` the same
    bytes once an edit (or a reset) here changed them. -> [setVertexColors,
    setAnimationColors, setLightColors] (only those with something to send), which
    the viewer applies to its loaded structures as this module edits bytes
    (HSDRawViewer LiveColorEdits; docs/dev/VIEWER_STREAMING.md):

    * vertex colours: per object whose values changed, each changed attribute as
      (POBJ index in its DOBJ, GX attribute 11/12) and its decoded RGBA values in the
      order `VertexColours.offsets` reads them, base64;
    * colour tracks: each track whose key stream or formats changed, by its structural
      key, with the whole new stream (a re-keyed track, `replace_track`, changes its
      frames too);
    * material descriptor colours (ambient, diffuse, specular) of objects whose
      colours changed; light colours by light name.

    Raises DatError when the two do not describe the same model, or when a change is
    on something the renderer does not draw by an id it knows (another root's
    objects): the caller then reloads the edited file instead.
    """
    import base64
    if [o.id for o in before.objects] != [o.id for o in after.objects]:
        raise DatError('The edit changed which objects the file has')

    def rendered(object_id):
        if not object_id.startswith(RENDERED):
            raise DatError(f'{object_id} is not an object the renderer draws')
        return object_id

    vertex, materials = [], []
    for old, new in zip(before.objects, after.objects):
        old_attrs = {(a.key[3], a.key[4]): a for a in old.vertex}
        rows = []
        for attr in new.vertex:
            values = [rgba for _, rgba in vertex_values(after.dat, attr)]
            was = old_attrs.get((attr.key[3], attr.key[4]))
            if was is not None and [rgba for _, rgba in vertex_values(before.dat, was)] == values:
                continue
            rows.append({'pobj': attr.key[3], 'attr': attr.key[4],
                         'rgba': base64.b64encode(bytes(v for rgba in values for v in rgba)).decode('ascii')})
        if rows:
            vertex.append({'id': rendered(new.id), 'colors': rows})
        if new.material is not None and old.material is not None and \
                after.dat.raw(new.material, 12) != before.dat.raw(old.material, 12):
            materials.append({'id': rendered(new.id), **{field: _rgba_hex(after.dat.raw(new.material + at, 4))
                                                          for field, at in MATERIAL_FIELDS.items()}})
    old_tracks = {t.key: t for t in before.tracks}
    tracks = {'material': [], 'texture': [], 'light': []}
    for track in after.tracks:
        was = old_tracks.get(track.key)
        stream = after.dat.raw(track.buffer, track.length)
        if was is not None and (was.value_flag, was.tan_flag) == (track.value_flag, track.tan_flag) \
                and before.dat.raw(was.buffer, was.length) == stream:
            continue
        tracks[track.owner].append({'key': list(track.key), 'data': base64.b64encode(stream).decode('ascii'),
                                    'valueFlag': track.value_flag, 'tanFlag': track.tan_flag})
    old_lights = {light['where']: light for light in before.lights}
    lights = [{'name': light['where'], 'rgba': _rgba_hex(after.dat.raw(light['offset'], 4))}
              for light in after.lights
              if light['where'] in old_lights
              and after.dat.raw(light['offset'], 4) != before.dat.raw(old_lights[light['where']]['offset'], 4)]
    messages = []
    if vertex:
        messages.append({'type': 'setVertexColors', 'objects': vertex})
    if tracks['material'] or tracks['texture'] or materials:
        messages.append({'type': 'setAnimationColors', 'tracks': tracks['material'] + tracks['texture'],
                         'materials': materials})
    if lights or tracks['light']:
        messages.append({'type': 'setLightColors', 'lights': lights, 'tracks': tracks['light']})
    return messages


def write_key(dat, track, key, value=None, tan=None):
    """Rewrite one key's value and/or tangent in place, in the track's own formats."""
    if value is not None and 'value_at' in key:
        dat.put(track.buffer + key['value_at'], encode_number(value, track.value_flag))
        key['value'] = _number(encode_number(value, track.value_flag), 0, track.value_flag)[0]
    if tan is not None and 'tan_at' in key:
        dat.put(track.buffer + key['tan_at'], encode_number(tan, track.tan_flag))
        key['tan'] = _number(encode_number(tan, track.tan_flag), 0, track.tan_flag)[0]
