"""Unit tests for the Stadium transformation-visibility repair.

Builds tiny synthetic GrPs-shaped DAT archives (map_head + model groups +
jobj/dobj/pobj trees with real vertex data) so the geometry pipeline, the
duplicate detection, and the pointer/reloc surgery are all exercised without
shipping real mod files.
"""
from tests.paths import BACKEND
import struct
import sys
from pathlib import Path

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

from vault.importing.stadium_dat import (  # noqa: E402
    Dat, GROUP_BG, GROUP_NORMAL, GROUP_SHELL, JOBJ_ENVELOPE_MODEL, JOBJ_SKELETON_ROOT, RepairError,
    dobj_chain, jobj_children)
from vault.importing.stadium_freeze import YAKU_FROZEN, YAKU_VANILLA, freeze_stadium_transformations
from vault.importing.stadium_transform_fix import build_plan, repair_stadium_variant
from vault.importing.stadium_baked_split import split_baked_platforms


class DatBuilder:
    """Assembles a minimal valid HSD archive with a map_head symbol."""

    def __init__(self):
        # data offset 0 reads as a NULL pointer, so keep it unoccupied the
        # way real archives do
        self.data = bytearray(0x20)
        self.relocs = []

    def alloc(self, size):
        off = len(self.data)
        self.data += bytes(size)
        return off

    def u32(self, off, val, reloc=False):
        struct.pack_into(">I", self.data, off, val)
        if reloc:
            self.relocs.append(off)

    def f32(self, off, val):
        struct.pack_into(">f", self.data, off, val)

    def jobj(self, child=0, nxt=0, dobj=0, ty=(0.0, 0.0, 0.0)):
        j = self.alloc(0x40)
        self.u32(j + 0x04, 0x00040008)
        if child:
            self.u32(j + 0x08, child, reloc=True)
        if nxt:
            self.u32(j + 0x0C, nxt, reloc=True)
        if dobj:
            self.u32(j + 0x10, dobj, reloc=True)
        for i in range(3):
            self.f32(j + 0x20 + 4 * i, 1.0)          # scale
            self.f32(j + 0x2C + 4 * i, ty[i])        # translate
        return j

    def quad_dobj(self, verts, nxt=0):
        """DObj -> PObj drawing one quad over the given 4 (x,y,z) floats."""
        pos = self.alloc(len(verts) * 12)
        for i, (x, y, z) in enumerate(verts):
            self.f32(pos + i * 12, x)
            self.f32(pos + i * 12 + 4, y)
            self.f32(pos + i * 12 + 8, z)
        desc = self.alloc(0x18 * 2)
        self.u32(desc + 0x00, 9)          # GX_VA_POS
        self.u32(desc + 0x04, 2)          # INDEX8
        self.u32(desc + 0x08, 1)          # XYZ
        self.u32(desc + 0x0C, 4)          # f32
        struct.pack_into(">H", self.data, desc + 0x12, 12)  # stride
        self.u32(desc + 0x14, pos, reloc=True)
        self.u32(desc + 0x18, 0xFF)       # GX_VA_NULL terminator
        display = self.alloc(32)
        self.data[display] = 0x80         # GX_QUADS
        struct.pack_into(">H", self.data, display + 1, 4)
        for i in range(4):
            self.data[display + 3 + i] = i
        pobj = self.alloc(0x18)
        self.u32(pobj + 0x08, desc, reloc=True)
        struct.pack_into(">H", self.data, pobj + 0x0E, 1)   # n_display
        self.u32(pobj + 0x10, display, reloc=True)
        d = self.alloc(0x10)
        if nxt:
            self.u32(d + 0x04, nxt, reloc=True)
        self.u32(d + 0x0C, pobj, reloc=True)
        return d

    def mesh_dobj(self, verts, triangles, envelope_bind=0,
                  display_at_zero=False, direct_color=False):
        """DObj -> PObj drawing indexed triangles, optionally enveloped."""
        pos = self.alloc(len(verts) * 12)
        for i, (x, y, z) in enumerate(verts):
            self.f32(pos + i * 12, x)
            self.f32(pos + i * 12 + 4, y)
            self.f32(pos + i * 12 + 8, z)

        desc = self.alloc(0x18 * (2 + bool(envelope_bind) +
                                  bool(direct_color)))
        pos_desc = desc
        if envelope_bind:
            self.u32(desc + 0x00, 0)       # GX_VA_PNMTXIDX
            self.u32(desc + 0x04, 1)       # DIRECT
            pos_desc += 0x18
        self.u32(pos_desc + 0x00, 9)       # GX_VA_POS
        self.u32(pos_desc + 0x04, 2)       # INDEX8
        self.u32(pos_desc + 0x08, 1)       # XYZ
        self.u32(pos_desc + 0x0C, 4)       # f32
        struct.pack_into(">H", self.data, pos_desc + 0x12, 12)
        self.u32(pos_desc + 0x14, pos, reloc=True)
        end_desc = pos_desc + 0x18
        if direct_color:
            self.u32(end_desc + 0x00, 11)  # GX_VA_CLR0
            self.u32(end_desc + 0x04, 1)   # DIRECT
            self.u32(end_desc + 0x08, 0)   # RGB
            self.u32(end_desc + 0x0C, 1)   # RGB8 (3 stream bytes)
            end_desc += 0x18
        self.u32(end_desc, 0xFF)            # GX_VA_NULL

        display = 0 if display_at_zero else self.alloc(32)
        cursor = display
        for triangle in triangles:
            self.data[cursor] = 0x90       # GX_TRIANGLES
            struct.pack_into(">H", self.data, cursor + 1, len(triangle))
            cursor += 3
            for index in triangle:
                if envelope_bind:
                    self.data[cursor] = 0  # PNMTXIDX 0
                    cursor += 1
                self.data[cursor] = index
                cursor += 1
                if direct_color:
                    self.data[cursor:cursor + 3] = bytes((255, 128, 64))
                    cursor += 3

        pobj = self.alloc(0x18)
        self.u32(pobj + 0x08, desc, reloc=True)
        if envelope_bind:
            struct.pack_into(">H", self.data, pobj + 0x0C, 0x2000)
        struct.pack_into(">H", self.data, pobj + 0x0E, 1)
        self.u32(pobj + 0x10, display, reloc=True)
        if envelope_bind:
            env = self.alloc(0x10)
            self.u32(env, envelope_bind, reloc=True)
            self.f32(env + 4, 1.0)
            env_list = self.alloc(8)
            self.u32(env_list, env, reloc=True)
            self.u32(pobj + 0x14, env_list, reloc=True)

        dobj = self.alloc(0x10)
        self.u32(dobj + 0x0C, pobj, reloc=True)
        return dobj

    def finish(self, group_roots, yaku=None):
        groups = self.alloc(10 * 0x34)
        for i in range(10):
            self.u32(groups + i * 0x34, group_roots.get(i, 0xFFFFFFFF),
                     reloc=(i in group_roots))
        mh = self.alloc(0x40)
        self.u32(mh + 0x08, groups, reloc=True)
        self.u32(mh + 0x0C, 10)
        symbols = [(mh, b"map_head")]
        if yaku is not None:
            y = self.alloc(0x54)
            for i, v in enumerate(yaku):
                self.u32(y + 4 * i, v & 0xFFFFFFFF)
            symbols.append((y, b"yakumono_param"))
        dsize = len(self.data)
        reloc = b"".join(struct.pack(">I", r) for r in self.relocs)
        strings = bytearray()
        roots = bytearray()
        for off, name in symbols:
            roots += struct.pack(">II", off, len(strings))
            strings += name + b"\x00"
        header = struct.pack(">5I12x", 0, dsize, len(self.relocs),
                             len(symbols), 0)
        blob = bytearray(header + self.data + reloc + roots + strings)
        struct.pack_into(">I", blob, 0, len(blob))
        return bytes(blob)


PAD = [(-55.0, 0.0, -10.0), (-25.0, 0.0, -10.0),
       (-25.0, 0.0, 10.0), (-55.0, 0.0, 10.0)]
DECK = [(-70.0, 0.0, -50.0), (70.0, 0.0, -50.0),
        (70.0, 25.0, 50.0), (-70.0, 25.0, 50.0)]
TOWER = [(-10.0, 0.0, -90.0), (10.0, 0.0, -90.0),
         (10.0, 80.0, -90.0), (-10.0, 80.0, -90.0)]


def build_variant(with_duplicate=True, empty_g5=False):
    b = DatBuilder()
    g5_dobj = 0 if empty_g5 else b.quad_dobj(DECK)
    g5_root = b.jobj(dobj=g5_dobj)
    dup = b.jobj(dobj=b.quad_dobj(DECK)) if with_duplicate else 0
    body = b.jobj(dobj=b.quad_dobj(TOWER), nxt=dup)
    g2_root = b.jobj(child=body)
    return b.finish({GROUP_NORMAL: g5_root, GROUP_SHELL: g2_root}), \
        (g5_root, g2_root, dup)


def test_duplicate_jobj_is_moved_to_group5():
    raw, (g5_root, g2_root, dup) = build_variant(with_duplicate=True)
    fixed, report = repair_stadium_variant(raw)
    assert report["status"] == "repaired", report
    assert len(report["actions"]) == 1
    dat = Dat(fixed)
    # the duplicate left group 2 and is now the tail of group 5's chain
    assert dup not in jobj_children(dat, g2_root)
    assert dup in jobj_children(dat, g5_root)
    # the non-duplicate body stayed put with its geometry intact
    assert len(dobj_chain(dat, jobj_children(dat, g2_root)[0])) == 1


def test_repaired_file_reparses_and_replans_clean():
    raw, _ = build_variant(with_duplicate=True)
    fixed, _ = repair_stadium_variant(raw)
    # idempotent: a second pass finds nothing left to do
    again, report = repair_stadium_variant(fixed)
    assert again is None
    assert report["status"] == "clean", report


def test_no_duplicate_is_clean():
    raw, _ = build_variant(with_duplicate=False)
    fixed, report = repair_stadium_variant(raw)
    assert fixed is None
    assert report["status"] == "clean"


def test_empty_group5_is_flagged_not_touched():
    raw, _ = build_variant(with_duplicate=False, empty_g5=True)
    fixed, report = repair_stadium_variant(raw)
    assert fixed is None
    assert report["status"] == "flagged"
    assert any("manual" in n for n in report["notes"])


def test_non_stage_file_is_skipped():
    blob = bytearray(0x40)
    struct.pack_into(">5I", blob, 0, 0x40, 0x20, 0, 0, 0)
    fixed, report = repair_stadium_variant(bytes(blob))
    assert fixed is None
    assert report["status"] == "skipped"


def test_reloc_table_stays_balanced():
    raw, _ = build_variant(with_duplicate=True)
    before = Dat(raw)
    fixed, _ = repair_stadium_variant(raw)
    after = Dat(fixed)
    # surgery nulls one next-pointer (entry dropped) and mints one tail
    # pointer (entry added): the count is unchanged and every entry still
    # references a non-null pointer field inside the data section
    assert after.nrel == before.nrel
    for r in after.relocs:
        assert 0 <= r < after.dsize
        assert after.valid(after.u32(r))


def test_plan_reports_positions():
    raw, (g5_root, g2_root, dup) = build_variant(with_duplicate=True)
    plan = build_plan(Dat(raw))
    assert [(g, j) for g, _, j in plan.jobj_moves] == [(GROUP_SHELL, dup)]
    assert plan.dobj_moves == []


def _baked_pad_variant(enveloped):
    b = DatBuilder()
    bind = b.jobj() if enveloped else 0
    verts = [(-55.0, 25.0, -10.0), (-25.0, 25.0, -10.0),
             (-25.0, 25.0, 10.0), (-55.0, 25.0, 10.0)]
    mesh = b.mesh_dobj(verts, [(0, 1, 2), (0, 2, 3)], bind)
    g2 = b.jobj(child=bind, dobj=mesh)
    g5 = b.jobj()
    return b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}), g5


@pytest.mark.parametrize("enveloped", [False, True])
def test_baked_split_carrier_has_required_envelope_flags(enveloped):
    raw, g5 = _baked_pad_variant(enveloped)
    dat = Dat(raw)
    actions = split_baked_platforms(dat)
    assert actions
    carrier = jobj_children(dat, g5)[-1]
    required = JOBJ_SKELETON_ROOT | JOBJ_ENVELOPE_MODEL
    assert (dat.u32(carrier + 4) & required) == (required if enveloped else 0)


def _baked_playfield_variant(enveloped):
    b = DatBuilder()
    bind = b.jobj() if enveloped else 0
    anchor = b.mesh_dobj(
        [(-90.0, 40.0, -260.0), (90.0, 40.0, -260.0),
         (90.0, 45.0, -135.0), (-90.0, 45.0, -135.0)],
        [(0, 1, 2), (0, 2, 3)], bind)
    support = b.mesh_dobj(
        [(-70.0, -100.0, -240.0), (70.0, -100.0, -240.0),
         (70.0, 40.0, -150.0), (-70.0, 40.0, -150.0)],
        [(0, 1, 2), (0, 2, 3)], bind)
    # This is exactly the old absolute side-pad shape.  Once a perspective-
    # offset deck anchor exists, it is scenery and must not win classification.
    decoy = b.mesh_dobj(
        [(-55.0, 25.0, -10.0), (-25.0, 25.0, -10.0),
         (-25.0, 25.0, 10.0), (-55.0, 25.0, 10.0)],
        [(0, 1, 2), (0, 2, 3)], bind)
    b.u32(anchor + 0x04, support, reloc=True)
    b.u32(support + 0x04, decoy, reloc=True)
    g2 = b.jobj(child=bind, dobj=anchor)
    g5 = b.jobj()
    return b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}), g5, decoy


def _nonduplicate_overlay_variant(broad):
    b = DatBuilder()
    g5 = b.jobj(dobj=b.quad_dobj(DECK))
    if broad:
        verts = [(-200.0, -10.0, -300.0), (200.0, -10.0, -300.0),
                 (200.0, 0.0, 50.0), (-200.0, 0.0, 50.0)]
    else:
        verts = [(-90.0, -4.0, -60.0), (90.0, -4.0, -60.0),
                 (90.0, 0.0, 60.0), (-90.0, 0.0, 60.0)]
    g2 = b.jobj(dobj=b.mesh_dobj(verts, [(0, 1, 2), (0, 2, 3)]))
    return b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2})


def test_repair_entrypoint_repairs_large_nonduplicate_overlay():
    fixed, report = repair_stadium_variant(
        _nonduplicate_overlay_variant(broad=True))

    assert fixed is not None
    assert report["status"] == "repaired"


def test_repair_entrypoint_leaves_standard_nonduplicate_overlay_clean():
    fixed, report = repair_stadium_variant(
        _nonduplicate_overlay_variant(broad=False))

    assert fixed is None
    assert report["status"] == "clean"


def test_large_arena_fallback_keeps_vertical_facade():
    b = DatBuilder()
    anchor = b.mesh_dobj(
        [(-200.0, -10.0, -300.0), (200.0, -10.0, -300.0),
         (200.0, 0.0, 50.0), (-200.0, 0.0, 50.0)],
        [(0, 1, 2), (0, 2, 3)])
    facade = b.mesh_dobj(
        [(40.0, -5.0, -200.0), (90.0, -5.0, -200.0),
         (90.0, 80.0, -190.0), (40.0, 80.0, -190.0)],
        [(0, 1, 2), (0, 2, 3)])
    b.u32(anchor + 0x04, facade, reloc=True)
    g2 = b.jobj(dobj=anchor)
    g5 = b.jobj()
    dat = Dat(b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}))

    actions = split_baked_platforms(dat)

    assert len(actions) == 1
    assert all(f"dobj@0x{facade:X}" not in action for action in actions)


def test_direct_rgb8_vertex_color_does_not_block_split():
    # Sparse broad quads may legitimately slope beyond the normal five-unit
    # top-coat limit; dense components do not get this exception.
    b = DatBuilder()
    mesh = b.mesh_dobj(
        [(-90.0, -14.0, -60.0), (90.0, -14.0, -60.0),
         (90.0, 0.0, 60.0), (-90.0, 0.0, 60.0)],
        [(0, 1, 2), (0, 2, 3)], direct_color=True)
    g2 = b.jobj(dobj=mesh)
    g5 = b.jobj()
    dat = Dat(b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}))

    actions = split_baked_platforms(dat)

    assert len(actions) == 1
    assert "split 2 playfield primitives" in actions[0]


def test_dense_shallow_shell_is_not_split():
    # Dense, shallow components are support shells, not top coats.
    b0 = DatBuilder()
    d0 = b0.mesh_dobj(
        [(-95, 0, -65), (95, 0, -65), (95, 2, 65), (-95, 2, 65)],
        [(0, 1, 2), (0, 2, 3)])
    s0 = b0.mesh_dobj(
        [(-94, -11, -64), (94, -11, -64), (94, -11, 64),
         (-94, -11, 64), (-94, 1, -64), (94, 1, -64),
         (94, 1, 64), (-94, 1, 64)],
        [(0, 1, 5), (0, 5, 4), (1, 2, 6),
         (1, 6, 5), (4, 5, 6)])
    b0.u32(d0 + 4, s0, reloc=True)
    dat0 = Dat(b0.finish({GROUP_NORMAL: b0.jobj(),
                          GROUP_SHELL: b0.jobj(dobj=d0)}))
    assert len(split_baked_platforms(dat0)) == 1


def test_collision_space_anchor_includes_relative_upper_pad():
    b = DatBuilder()
    anchor = b.mesh_dobj(
        [(-90.0, -4.0, -60.0), (90.0, -4.0, -60.0),
         (90.0, 0.0, 60.0), (-90.0, 0.0, 60.0)],
        [(0, 1, 2), (0, 2, 3)])
    pad = b.mesh_dobj(
        [(-55.0, 22.0, -10.0), (-25.0, 22.0, -10.0),
         (-25.0, 26.0, 10.0), (-55.0, 26.0, 10.0)],
        [(0, 1, 2), (0, 2, 3)])
    b.u32(anchor + 0x04, pad, reloc=True)
    g2 = b.jobj(dobj=anchor)
    g5 = b.jobj()
    dat = Dat(b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}))

    actions = split_baked_platforms(dat)

    assert len(actions) == 2
    assert any(f"dobj@0x{pad:X}" in action for action in actions)


def test_repair_entrypoint_runs_enabled_baked_splitter():
    raw, _ = _baked_pad_variant(enveloped=False)

    fixed, report = repair_stadium_variant(raw)

    assert fixed is not None
    assert report["status"] == "repaired"
    assert any("playfield primitives" in action
               for action in report["actions"])


def test_relocated_zero_offset_display_list_is_split():
    b = DatBuilder()
    mesh = b.mesh_dobj(
        [(-90.0, 40.0, -260.0), (90.0, 40.0, -260.0),
         (90.0, 45.0, -135.0), (-90.0, 45.0, -135.0)],
        [(0, 1, 2), (0, 2, 3)], display_at_zero=True)
    g2 = b.jobj(dobj=mesh)
    g5 = b.jobj()
    dat = Dat(b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}))

    actions = split_baked_platforms(dat)

    assert len(actions) == 1
    assert "split 2 playfield primitives" in actions[0]
    assert jobj_children(dat, g5)


@pytest.mark.parametrize("enveloped", [False, True])
def test_baked_playfield_anchor_beats_absolute_pad_decoy(enveloped):
    raw, g5, decoy = _baked_playfield_variant(enveloped)
    dat = Dat(raw)
    actions = split_baked_platforms(dat)
    # The broad deck moves, but its deep support is permanent shell geometry.
    assert len(actions) == 1
    assert all(f"dobj@0x{decoy:X}" not in action for action in actions)
    carrier = jobj_children(dat, g5)[-1]
    required = JOBJ_SKELETON_ROOT | JOBJ_ENVELOPE_MODEL
    assert (dat.u32(carrier + 4) & required) == (required if enveloped else 0)

    # A repaired welded file is a fixed point.  Without the carrier signature,
    # its new group-5 floor can cause permanent shell layers to be selected on
    # a later import.
    repaired = bytes(dat.b)
    repaired_again, report = repair_stadium_variant(repaired)
    assert repaired_again is None
    assert report["status"] == "clean"


def test_disconnected_border_sharing_floor_pobj_stays_permanent():
    b = DatBuilder()
    mesh = b.mesh_dobj(
        [(-90.0, -1.0, -60.0), (90.0, -1.0, -60.0),
         (90.0, 0.0, 60.0), (-90.0, 0.0, 60.0),
         (-90.0, -18.0, -60.0), (90.0, -18.0, -60.0),
         (90.0, -2.0, -60.0), (-90.0, -2.0, -60.0)],
        [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)])
    g2 = b.jobj(dobj=mesh)
    g5 = b.jobj()
    dat = Dat(b.finish({GROUP_NORMAL: g5, GROUP_SHELL: g2}))

    actions = split_baked_platforms(dat)

    assert len(actions) == 1
    assert "split 2 playfield primitives" in actions[0]


def test_background_rooftop_is_not_mistaken_for_playfield():
    b = DatBuilder()
    roof = b.mesh_dobj(
        [(-90.0, 40.0, -60.0), (90.0, 40.0, -60.0),
         (90.0, 40.0, 60.0), (-90.0, 40.0, 60.0)],
        [(0, 1, 2), (0, 2, 3)])
    g1 = b.jobj(dobj=roof)
    g5 = b.jobj()
    dat = Dat(b.finish({GROUP_NORMAL: g5, GROUP_BG: g1}))

    assert split_baked_platforms(dat) == []

def _yaku_variant():
    b = DatBuilder()
    g5 = b.jobj(dobj=b.quad_dobj(DECK))
    return b.finish({GROUP_NORMAL: g5},
                    yaku=YAKU_VANILLA + (300, 120, 60))


def test_freeze_and_unfreeze_roundtrip():
    raw = _yaku_variant()
    frozen, rep = freeze_stadium_transformations(raw, True)
    assert rep["previous"] == list(YAKU_VANILLA)
    assert rep["applied"] == list(YAKU_FROZEN)
    assert not rep["was_frozen"]
    again, rep2 = freeze_stadium_transformations(frozen, True)
    assert rep2["was_frozen"]
    restored, rep3 = freeze_stadium_transformations(frozen, False)
    assert rep3["applied"] == list(YAKU_VANILLA)
    dat = Dat(restored)
    y = dat.symbols["yakumono_param"]
    import struct as _s
    assert _s.unpack_from(">4i", dat.b, 0x20 + y) == YAKU_VANILLA


def test_freeze_requires_yakumono():
    raw, _ = build_variant()
    with pytest.raises(RepairError):
        freeze_stadium_transformations(raw, True)
