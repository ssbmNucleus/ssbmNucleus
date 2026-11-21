"""
The Pokemon Stadium (GrPs) archive model the transformation repair works on:
the map_head group layout, GX vertex and JObj flag constants, a minimal HSD
archive reader/patcher, JObj/DObj traversal, and the POS vertices and bounding
box of a DObj's display lists, and the in-file pointer surgery both repairs use
(unlink or append a child JObj, split off DObjs, append a bare JObj).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


# map_head model-group indices (vanilla GrPs layout, 10 groups)
GROUP_BG = 1          # background buildings + OV floor
GROUP_SHELL = 2       # permanent arena shell
GROUP_NORMAL = 5      # normal-form structure -- hidden during transformations
CANDIDATE_GROUPS = (GROUP_BG, GROUP_SHELL)
EXPECTED_GROUP_COUNT = 10

# A group-1/2 piece is RELOCATED to group 5 when it geometrically DUPLICATES
# a group-5 piece: same bounding box within DUP_TOL units per axis bound and
# a comparable vertex count.  Mod authors stack copies of their platform /
# deck geometry across groups (often as material layers: a reflective under-
# layer in group 5 plus the visible top coat in a permanent group) -- during
# transformations the group-5 layer hides correctly and the permanent copy is
# the lingering ghost (its collision is already toggled off with the normal
# form).  Moving -- never deleting -- preserves the stacked layers in the
# normal form exactly; a piece with no group-5 twin is never touched.
DUP_TOL = 3.0
DUP_NPOS_RATIO = 10.0  # vertex counts may differ (lod/retopo) up to this ratio

GX_VA_NULL = 0xFF
GX_VA_PNMTXIDX = 0
GX_VA_TEX0MTXIDX = 1
GX_VA_TEX7MTXIDX = 8
GX_VA_POS = 9
GX_DIRECT, GX_INDEX8, GX_INDEX16 = 1, 2, 3

PRIM_OPCODES = {0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8}

JOBJ_HIDDEN = 0x10
JOBJ_PTCL = 0x20
JOBJ_SPLINE = 0x4000
JOBJ_SKELETON_ROOT = 0x02
JOBJ_ENVELOPE_MODEL = 0x04
JOBJ_CLASSICAL_SCALING = 0x08
JOBJ_OPA = 0x00040000


class RepairError(Exception):
    pass


@dataclass
class BBox:
    lo: tuple = (float("inf"),) * 3
    hi: tuple = (float("-inf"),) * 3
    npos: int = 0

    def add(self, x, y, z):
        self.lo = (min(self.lo[0], x), min(self.lo[1], y), min(self.lo[2], z))
        self.hi = (max(self.hi[0], x), max(self.hi[1], y), max(self.hi[2], z))
        self.npos += 1

    def duplicates(self, other) -> bool:
        if not self.npos or not other.npos:
            return False
        ratio = max(self.npos, other.npos) / min(self.npos, other.npos)
        if ratio > DUP_NPOS_RATIO:
            return False
        for a, b in zip(self.lo + self.hi, other.lo + other.hi):
            if abs(a - b) > DUP_TOL:
                return False
        return True


class Dat:
    """Minimal HSD archive reader/patcher (data offsets, not file offsets)."""

    def __init__(self, data: bytes):
        self.b = bytearray(data)
        (self.fsize, self.dsize, self.nrel, self.nroot,
         self.nref) = struct.unpack_from(">5I", self.b, 0)
        if self.fsize != len(self.b):
            raise RepairError(f"header size {self.fsize} != file {len(self.b)}")
        self._retable()

    def _retable(self):
        self.reloc_off = 0x20 + self.dsize
        self.root_off = self.reloc_off + self.nrel * 4
        self.str_off = self.root_off + (self.nroot + self.nref) * 8
        self.symbols = {}
        for i in range(self.nroot + self.nref):
            d_off, s_off = struct.unpack_from(">II", self.b, self.root_off + i * 8)
            s = self.str_off + s_off
            name = self.b[s:self.b.index(b"\x00", s)].decode("ascii", "replace")
            self.symbols[name] = d_off
        self.relocs = set(struct.unpack_from(f">{self.nrel}I", self.b, self.reloc_off))

    def u16(self, doff):
        return struct.unpack_from(">H", self.b, 0x20 + doff)[0]

    def u32(self, doff):
        return struct.unpack_from(">I", self.b, 0x20 + doff)[0]

    def f32(self, doff):
        return struct.unpack_from(">f", self.b, 0x20 + doff)[0]

    def set_u32(self, doff, val):
        struct.pack_into(">I", self.b, 0x20 + doff, val)

    def valid(self, doff):
        return 0 < doff < self.dsize

    # -- relocation upkeep ------------------------------------------------
    def reloc_remove(self, field_off):
        """Drop the entry for a pointer field that now holds NULL."""
        for i in range(self.nrel):
            off = self.reloc_off + i * 4
            if struct.unpack_from(">I", self.b, off)[0] == field_off:
                del self.b[off:off + 4]
                self.nrel -= 1
                struct.pack_into(">I", self.b, 8, self.nrel)
                self.fsize = len(self.b)
                struct.pack_into(">I", self.b, 0, self.fsize)
                self._retable()
                return
        raise RepairError(f"reloc entry 0x{field_off:X} not found")

    def reloc_add(self, field_off):
        """Register a pointer field that now holds a real data offset."""
        if field_off in self.relocs:
            return
        end = self.reloc_off + self.nrel * 4
        self.b[end:end] = struct.pack(">I", field_off)
        self.nrel += 1
        struct.pack_into(">I", self.b, 8, self.nrel)
        self.fsize = len(self.b)
        struct.pack_into(">I", self.b, 0, self.fsize)
        self._retable()


# -- JObj / DObj traversal -----------------------------------------------

def jobj_children(dat, root):
    """Top-level child chain of a jobj (child + its next-siblings)."""
    out = []
    j = dat.u32(root + 0x08)
    seen = set()
    while dat.valid(j) and j not in seen:
        seen.add(j)
        out.append(j)
        j = dat.u32(j + 0x0C)
    return out


def dobj_chain(dat, jobj):
    flags = dat.u32(jobj + 0x04)
    if flags & (JOBJ_PTCL | JOBJ_SPLINE):
        return []
    out = []
    d = dat.u32(jobj + 0x10)
    seen = set()
    while dat.valid(d) and d not in seen:
        seen.add(d)
        out.append(d)
        d = dat.u32(d + 0x04)
    return out


def jobj_world(dat, jobj, parent_t=(0.0, 0.0, 0.0), parent_s=1.0):
    tx = parent_t[0] + dat.f32(jobj + 0x2C) * parent_s
    ty = parent_t[1] + dat.f32(jobj + 0x30) * parent_s
    tz = parent_t[2] + dat.f32(jobj + 0x34) * parent_s
    s = parent_s * dat.f32(jobj + 0x20)
    return (tx, ty, tz), s


# -- vertex/bbox extraction ----------------------------------------------

_ATTR_ITYPE_SIZE = {GX_INDEX8: 1, GX_INDEX16: 2}
_COMP_FMT = {0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("f", 4)}
GX_VA_CLR0 = 11
GX_VA_CLR1 = 12
_DIRECT_COLOR_SIZE = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}


def _display_attr_width(attr, atype, comp_type):
    """Bytes consumed by one display-list vertex for an attribute."""
    if atype == GX_DIRECT:
        if GX_VA_PNMTXIDX <= attr <= GX_VA_TEX7MTXIDX:
            return 1
        if attr in (GX_VA_CLR0, GX_VA_CLR1):
            try:
                return _DIRECT_COLOR_SIZE[comp_type]
            except KeyError as exc:
                raise RepairError(f"direct color type {comp_type}") from exc
        raise RepairError("direct non-matrix/color attribute")
    try:
        return _ATTR_ITYPE_SIZE[atype]
    except KeyError as exc:
        raise RepairError(f"attr_type {atype}") from exc


def dobj_bbox(dat, dobj, world_t=(0.0, 0.0, 0.0), world_s=1.0):
    """BBox over all POS vertices referenced by a dobj's pobj display lists.

    Returns a BBox with npos=0 when the geometry can't be decoded (unknown
    attribute layout) -- callers treat that as "not platform-like".
    """
    box = BBox()
    p = dat.u32(dobj + 0x0C)
    seen = set()
    while dat.valid(p) and p not in seen:
        seen.add(p)
        try:
            _pobj_positions(dat, p, box, world_t, world_s)
        except (RepairError, struct.error, IndexError):
            return BBox()  # undecodable -> never relocate
        p = dat.u32(p + 0x04)
    return box


def _pobj_positions(dat, pobj, box, world_t, world_s):
    desc = dat.u32(pobj + 0x08)
    n_display = dat.u16(pobj + 0x0E)
    display = dat.u32(pobj + 0x10)
    # A relocated zero is a real pointer to data-section offset 0, not NULL.
    # Some Stadium mods put a display list there (Slippi Stadium does), so
    # pointer validity must include relocation-table membership.
    has_display = (dat.valid(display)
                   or (display == 0 and (pobj + 0x10) in dat.relocs))
    if not dat.valid(desc) or not has_display or n_display == 0:
        return
    attrs = []
    off = desc
    for _ in range(32):
        attr = dat.u32(off)
        if attr == GX_VA_NULL:
            break
        atype = dat.u32(off + 0x04)
        comp_cnt = dat.u32(off + 0x08)
        comp_type = dat.u32(off + 0x0C)
        frac = dat.b[0x20 + off + 0x10]
        stride = dat.u16(off + 0x12)
        ptr = dat.u32(off + 0x14)
        attrs.append((attr, atype, comp_cnt, comp_type, frac, stride, ptr))
        off += 0x18
    else:
        raise RepairError("unterminated vtx desc list")

    pos = next((a for a in attrs if a[0] == GX_VA_POS), None)
    if pos is None:
        return

    # per-vertex byte width of each attribute in the display stream
    widths = []
    for attr, atype, comp_cnt, comp_type, _, _, _ in attrs:
        widths.append((attr, _display_attr_width(attr, atype, comp_type)))

    pos_indices = set()
    cur = 0x20 + display
    end = cur + n_display * 32
    while cur < end:
        op = dat.b[cur]
        if op == 0:
            break
        if op not in PRIM_OPCODES:
            raise RepairError(f"display opcode 0x{op:02X}")
        count = struct.unpack_from(">H", dat.b, cur + 1)[0]
        cur += 3
        for _ in range(count):
            for attr, w in widths:
                if attr == GX_VA_POS:
                    idx = (dat.b[cur] if w == 1
                           else struct.unpack_from(">H", dat.b, cur)[0])
                    pos_indices.add(idx)
                cur += w

    _, _, comp_cnt, comp_type, frac, stride, ptr = pos
    fmt, csz = _COMP_FMT[comp_type]
    ncomp = 2 if comp_cnt == 0 else 3
    scale = float(1 << frac) if comp_type != 4 else 1.0
    for idx in pos_indices:
        base = 0x20 + ptr + idx * stride
        vals = [struct.unpack_from(">" + fmt, dat.b, base + i * csz)[0] / scale
                for i in range(ncomp)]
        x, y = vals[0], vals[1]
        z = vals[2] if ncomp == 3 else 0.0
        box.add(world_t[0] + x * world_s, world_t[1] + y * world_s,
                world_t[2] + z * world_s)


def _groups(dat):
    mh = dat.symbols.get("map_head")
    if mh is None:
        raise RepairError("no map_head symbol -- not a stage file")
    gptr = dat.u32(mh + 0x08)
    count = dat.u32(mh + 0x0C)
    if count != EXPECTED_GROUP_COUNT:
        raise RepairError(f"unexpected model group count {count}")
    roots = []
    for i in range(count):
        r = dat.u32(gptr + i * 0x34)
        roots.append(r if dat.valid(r) else None)
    return roots


def _walk_subtree(dat, root):
    """Yield (parent, jobj, world_t, world_s) for every jobj under root
    (root itself yielded with parent=None)."""
    rt, rs = jobj_world(dat, root)
    stack = [(None, root, rt, rs)]
    seen = set()
    while stack:
        parent, jobj, wt, ws = stack.pop()
        if jobj in seen:
            continue
        seen.add(jobj)
        yield parent, jobj, wt, ws
        child = dat.u32(jobj + 0x08)
        c = child
        while dat.valid(c) and c not in seen:
            ct, cs = jobj_world(dat, c, wt, ws)
            stack.append((jobj, c, ct, cs))
            c = dat.u32(c + 0x0C)


# -- surgery --------------------------------------------------------------

def _unlink_child(dat, parent, jobj):
    """Remove jobj from parent's child chain, keeping the relocation table
    balanced (a pointer field that becomes NULL loses its entry)."""
    prev_field = parent + 0x08
    cur = dat.u32(prev_field)
    while cur != jobj:
        if not dat.valid(cur):
            raise RepairError(f"jobj 0x{jobj:X} not in chain of 0x{parent:X}")
        prev_field = cur + 0x0C
        cur = dat.u32(cur + 0x0C)
    nxt = dat.u32(jobj + 0x0C)
    if dat.valid(nxt):
        dat.set_u32(prev_field, nxt)
    else:
        dat.set_u32(prev_field, 0)
        if prev_field in dat.relocs:
            dat.reloc_remove(prev_field)


def _append_child(dat, root, jobj):
    """Append jobj to root's child chain (jobj must already be unlinked)."""
    chain = jobj_children(dat, root)
    tail_field = (chain[-1] + 0x0C) if chain else (root + 0x08)
    if dat.valid(dat.u32(tail_field)):
        raise RepairError("append target field not empty")
    dat.set_u32(tail_field, jobj)
    dat.reloc_add(tail_field)
    dat.set_u32(jobj + 0x0C, 0)
    if (jobj + 0x0C) in dat.relocs:
        dat.reloc_remove(jobj + 0x0C)


def _extract_dobjs(dat, host, hits):
    """Unlink `hits` from host's dobj chain and link them to each other;
    returns the head of the extracted chain."""
    hits_set = set(hits)
    prev_field = host + 0x10
    cur = dat.u32(prev_field)
    while dat.valid(cur):
        nxt = dat.u32(cur + 0x04)
        if cur in hits_set:
            if dat.valid(nxt):
                dat.set_u32(prev_field, nxt)
            else:
                dat.set_u32(prev_field, 0)
                if prev_field in dat.relocs:
                    dat.reloc_remove(prev_field)
        else:
            prev_field = cur + 0x04
        cur = nxt
    for a, b in zip(hits, hits[1:]):
        dat.set_u32(a + 0x04, b)
        dat.reloc_add(a + 0x04)
    dat.set_u32(hits[-1] + 0x04, 0)
    if (hits[-1] + 0x04) in dat.relocs:
        dat.reloc_remove(hits[-1] + 0x04)
    return hits[0]


def _new_bare_jobj(dat) -> int:
    """Append a fresh identity JObj (0x40 bytes) to the data section.
    Data offsets are unaffected; the tables after the data shift."""
    jobj = dat.dsize
    desc = bytearray(0x40)
    # CLASSICAL_SCALING | ROOT_OPA: render the carried dobjs in the opaque
    # pass like the sibling stage jobjs do
    struct.pack_into(">I", desc, 0x04, 0x00040008)
    for off in (0x20, 0x24, 0x28):  # scale = 1
        struct.pack_into(">f", desc, off, 1.0)
    dat.b[0x20 + dat.dsize:0x20 + dat.dsize] = desc
    dat.dsize += 0x40
    struct.pack_into(">I", dat.b, 4, dat.dsize)
    dat.fsize = len(dat.b)
    struct.pack_into(">I", dat.b, 0, dat.fsize)
    dat._retable()
    return jobj
