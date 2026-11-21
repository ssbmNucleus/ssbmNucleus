"""
Repairing a fully baked Stadium variant (one welded mesh): classify the
playfield primitives from the mesh's own layout and carve them out of the
permanent groups' display lists into new JObjs in the normal-form group,
copying envelopes and stripping per-vertex matrices where needed.
"""

from __future__ import annotations

import struct
from vault.importing.stadium_dat import (GROUP_SHELL, GROUP_NORMAL, CANDIDATE_GROUPS,
    GX_VA_NULL, GX_VA_POS, PRIM_OPCODES, JOBJ_SKELETON_ROOT,
    JOBJ_ENVELOPE_MODEL, JOBJ_CLASSICAL_SCALING, JOBJ_OPA, RepairError, jobj_children,
    dobj_chain, _COMP_FMT, _display_attr_width, _groups, _walk_subtree,
    _append_child)


# -- baked-variant repair: primitive-level splitting -----------------------
# Variants with no group-5 geometry weld their platforms into whole-stage
# vertex buffers, so there is no joint or draw-object to relocate.  A display
# list is still a sequence of independently movable primitives referencing
# shared vertex arrays, so selected connected components can be carved into
# group-5 carrier joints without touching collision or material data.
#
# Absolute collision-space platform prisms are not sufficient: perspective
# imports such as Sky High place the visible arena around z=-200 while keeping
# vanilla collision at z=0.  The classifier therefore finds broad, shallow,
# centre-crossing deck layers in the mesh itself, uses their front-most depth
# cluster as the playfield anchor.  Earlier versions then moved all components
# that shared an anchor material plus nearby supports/facades; custom imports
# commonly pack their permanent rim into those same materials, so the whole
# arena disappeared during transformations.  Selection is now deliberately
# limited to thin deck surfaces and raised side-platform surfaces.  If no
# reliable anchor exists it falls back to the older side-pad rule; this remains
# useful for conventionally placed meshes.
#
# The former loader blocker is solved: a carrier with ENVELOPE pobjs must carry
# both JOBJ_ENVELOPE_MODEL and JOBJ_SKELETON_ROOT.  Without that pair Melee
# freezes at frame 1 while HSDRawViewer still renders the file correctly.
ENABLE_BAKED_SPLIT = True

PAD_SIDE_MIN_X = 5.0      # one-sided: entirely left of -5 or right of +5
PAD_TOP_MIN_Y = 12.0      # component must reach the platform band...
PAD_TOP_MAX_Y = 45.0      # ...but not tower above it
PAD_BOTTOM_MIN_Y = -95.0  # hanging undersides are fine, the abyss is not
PAD_MAX_EXTENT_X = 85.0
PAD_MAX_ABS_Z = 50.0
MIN_SPLIT_PRIMS = 2   # don't bother splitting for a single stray primitive
MAIN_SURFACE_MAX_HEIGHT = 5.0
MAIN_SURFACE_Y_SLOP = 5.0


def _rot_matrix(rx, ry, rz):
    import math
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    my = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    mz = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))

    def mul(a, b):
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                           for j in range(3)) for i in range(3))
    return mul(mz, mul(my, mx))


def _jobj_local(dat, jobj):
    rot = tuple(dat.f32(jobj + 0x14 + 4 * i) for i in range(3))
    scale = tuple(dat.f32(jobj + 0x20 + 4 * i) for i in range(3))
    trans = tuple(dat.f32(jobj + 0x2C + 4 * i) for i in range(3))
    return rot, scale, trans


def _is_identity_jobj(dat, jobj):
    rot, scale, trans = _jobj_local(dat, jobj)
    return (all(abs(r) < 1e-4 for r in rot)
            and all(abs(s - 1.0) < 1e-6 for s in scale)
            and all(abs(t) < 1e-4 for t in trans))


def _iter_primitives(dat, pobj):
    """Yield (file_off, length, pos_indices) for each display primitive."""
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
    widths = []
    off = desc
    for _ in range(32):
        attr = dat.u32(off)
        if attr == GX_VA_NULL:
            break
        atype = dat.u32(off + 0x04)
        widths.append((attr, _display_attr_width(
            attr, atype, dat.u32(off + 0x0C))))
        off += 0x18
    else:
        raise RepairError("unterminated vtx desc list")
    vsize = sum(w for _, w in widths)
    cur = 0x20 + display
    end = cur + n_display * 32
    while cur < end:
        op = dat.b[cur]
        if op == 0:
            break
        if op not in PRIM_OPCODES:
            raise RepairError(f"display opcode 0x{op:02X}")
        count = struct.unpack_from(">H", dat.b, cur + 1)[0]
        length = 3 + count * vsize
        pos_indices = []
        v = cur + 3
        for _ in range(count):
            a = v
            for attr, w in widths:
                if attr == GX_VA_POS:
                    pos_indices.append(
                        dat.b[a] if w == 1
                        else struct.unpack_from(">H", dat.b, a)[0])
                a += w
            v += vsize
        yield cur - 0x20, length, pos_indices
        cur += length


def _pos_reader(dat, pobj):
    desc = dat.u32(pobj + 0x08)
    off = desc
    for _ in range(32):
        attr = dat.u32(off)
        if attr == GX_VA_NULL:
            return None
        if attr == GX_VA_POS:
            comp_cnt = dat.u32(off + 0x08)
            comp_type = dat.u32(off + 0x0C)
            frac = dat.b[0x20 + off + 0x10]
            stride = dat.u16(off + 0x12)
            ptr = dat.u32(off + 0x14)
            fmt, csz = _COMP_FMT[comp_type]
            ncomp = 2 if comp_cnt == 0 else 3
            scale = float(1 << frac) if comp_type != 4 else 1.0

            def read(idx):
                base = 0x20 + ptr + idx * stride
                vals = [struct.unpack_from(">" + fmt, dat.b,
                                           base + i * csz)[0] / scale
                        for i in range(ncomp)]
                return (vals[0], vals[1], vals[2] if ncomp == 3 else 0.0)
            return read
        off += 0x18
    return None


def _envelope_single_bind(dat, pobj):
    """For an ENVELOPE pobj (flag 0x2000): return the bind jobj offset when
    every envelope entry is a single full-weight bind to one jobj, else None."""
    if not (dat.u16(pobj + 0x0C) & 0x2000):
        return None
    env_list = dat.u32(pobj + 0x14)
    if not dat.valid(env_list):
        return None
    bind = None
    i = 0
    while True:
        e = dat.u32(env_list + 4 * i)
        if not dat.valid(e):
            break
        jp = dat.u32(e)
        w = dat.f32(e + 4)
        if abs(w - 1.0) > 1e-4 or dat.valid(dat.u32(e + 8)):
            return None  # multi-bone or partial weight
        if bind is None:
            bind = jp
        elif bind != jp:
            return None  # entries bind different bones
        i += 1
        if i > 64:
            return None
    return bind


def _world_matrix(dat, chain):
    """Compose [R|t] (3x4) for a parent->child jobj chain."""
    m = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
    t = [0.0, 0.0, 0.0]
    for jobj in chain:
        rot, scale, trans = _jobj_local(dat, jobj)
        r = _rot_matrix(*rot)
        rs = [[r[i][j] * scale[j] for j in range(3)] for i in range(3)]
        t = [m[i][0] * trans[0] + m[i][1] * trans[1] + m[i][2] * trans[2]
             + t[i] for i in range(3)]
        m = [[sum(m[i][k] * rs[k][j] for k in range(3)) for j in range(3)]
             for i in range(3)]
    return m, t


def _bind_chain(dat, group_root, target):
    """Path of jobjs from group_root down to target (inclusive), or None."""
    def dfs(jobj, path):
        if jobj == target:
            return path + [jobj]
        c = dat.u32(jobj + 0x08)
        seen = set()
        while dat.valid(c) and c not in seen:
            seen.add(c)
            found = dfs(c, path + [jobj])
            if found:
                return found
            c = dat.u32(c + 0x0C)
        return None
    return dfs(group_root, [])


def _decompose_trs(m, t):
    """3x3+t -> (rot_xyz, scale, trans) for the Rz@Ry@Rx convention."""
    import math
    sx = math.sqrt(sum(m[i][0] ** 2 for i in range(3))) or 1.0
    sy = math.sqrt(sum(m[i][1] ** 2 for i in range(3))) or 1.0
    sz = math.sqrt(sum(m[i][2] ** 2 for i in range(3))) or 1.0
    r = [[m[i][0] / sx, m[i][1] / sy, m[i][2] / sz] for i in range(3)]
    b = math.asin(max(-1.0, min(1.0, -r[2][0])))
    a = math.atan2(r[2][1], r[2][2])
    c = math.atan2(r[1][0], r[0][0])
    return (a, b, c), (sx, sy, sz), tuple(t)


def _skinning_matrix(dat, group_root, bind_jobj):
    """world(bind) @ inverse_bind -- the fixed transform single-bind skinned
    vertices actually render with."""
    chain = _bind_chain(dat, group_root, bind_jobj)
    if chain is None:
        raise RepairError(f"bind jobj 0x{bind_jobj:X} not under group root")
    m, t = _world_matrix(dat, chain)
    inv_ptr = dat.u32(bind_jobj + 0x38)
    if dat.valid(inv_ptr):
        inv = [[dat.f32(inv_ptr + (i * 4 + j) * 4) for j in range(4)]
               for i in range(3)]
        im = [[inv[i][j] for j in range(3)] for i in range(3)]
        it = [inv[i][3] for i in range(3)]
        t = [m[i][0] * it[0] + m[i][1] * it[1] + m[i][2] * it[2] + t[i]
             for i in range(3)]
        m = [[sum(m[i][k] * im[k][j] for k in range(3)) for j in range(3)]
             for i in range(3)]
    return m, t


def _copy_envelope(dat, env_list) -> int:
    """Deep-copy a pobj's envelope (the list plus every envelope descriptor).

    The moved primitives must keep their skinning to land where the author
    put them, but two pobjs cannot share one envelope -- the loader chokes
    on it -- so each gets its own copy, with relocation entries for every
    pointer so the loader fixes them up."""
    descs = []
    i = 0
    while True:
        e = dat.u32(env_list + 4 * i)
        if not dat.valid(e):
            break
        pairs = []
        j = 0
        while True:
            jp = dat.u32(e + 8 * j)
            if not dat.valid(jp):
                break
            pairs.append((jp, dat.b[0x20 + e + 8 * j + 4:0x20 + e + 8 * j + 8]))
            j += 1
        descs.append(pairs)
        i += 1
        if i > 64:
            raise RepairError("envelope list too long")
    if not descs:
        raise RepairError("empty envelope list")

    desc_offs = []
    for pairs in descs:
        blob = bytearray()
        for jp, weight in pairs:
            blob += struct.pack(">I", jp) + weight
        blob += bytes(8)                      # null-terminated
        off = _append_data(dat, bytes(blob))
        for k in range(len(pairs)):
            dat.reloc_add(off + 8 * k)        # jobj pointer
        desc_offs.append(off)

    list_off = _append_data(dat, b"".join(struct.pack(">I", o)
                                          for o in desc_offs) + bytes(4))
    for k in range(len(desc_offs)):
        dat.reloc_add(list_off + 4 * k)
    return list_off


def _append_data(dat, blob, align=4) -> int:
    # GX display lists must start 32-byte aligned; structures need 4.
    pad = (-dat.dsize) % align
    if pad:
        dat.b[0x20 + dat.dsize:0x20 + dat.dsize] = bytes(pad)
        dat.dsize += pad
    off = dat.dsize
    dat.b[0x20 + dat.dsize:0x20 + dat.dsize] = blob
    dat.dsize += len(blob)
    struct.pack_into(">I", dat.b, 4, dat.dsize)
    dat.fsize = len(dat.b)
    struct.pack_into(">I", dat.b, 0, dat.fsize)
    dat._retable()
    return off


def _transform_reader(reader, matrix, trans):
    """Wrap a POS reader with a fixed 3x4 model-to-world transform."""
    def world_of(index):
        point = reader(index)
        return tuple(
            sum(matrix[row][col] * point[col] for col in range(3))
            + trans[row]
            for row in range(3))
    return world_of


def _component_records(pobj, prims, world_of):
    """Return connected primitive components with their world-space bounds."""
    parent = {}

    def find(item):
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for off, _, indices in prims:
        primitive = ("p", off)
        find(primitive)
        for index in indices:
            union(primitive, ("v", index))

    components = {}
    for primitive in prims:
        components.setdefault(find(("p", primitive[0])), []).append(primitive)

    records = []
    for members in components.values():
        points = [world_of(index)
                  for _, _, indices in members for index in indices]
        if not points:
            continue
        lo = tuple(min(point[axis] for point in points) for axis in range(3))
        hi = tuple(max(point[axis] for point in points) for axis in range(3))
        records.append({"pobj": pobj, "members": members, "lo": lo, "hi": hi})
    return records


def _playfield_component_hits(meshes, broad_only=False):
    """Classify a baked playfield from the mesh's own depth/layout.

    Welded imports can place their visible arena hundreds of model units away
    from collision space for forced perspective, so absolute platform prisms
    select scenery.  Find the broad, shallow, centre-crossing deck layers
    first, then take only thin top-surface layers and raised side-platform
    layers in that depth band.  The permanent rim/skirt/facade is intentionally
    excluded even when it shares a PObj/material with the deck.  None means no
    reliable anchor was found and lets the caller fall back to the older
    side-pad rule.
    """
    records = []
    for pobj, prims, world_of in meshes:
        component_records = _component_records(pobj, prims, world_of)
        records.extend(component_records)

    anchors = []
    for record in records:
        lo, hi = record["lo"], record["hi"]
        width = hi[0] - lo[0]
        height = hi[1] - lo[1]
        depth = hi[2] - lo[2]
        if (lo[0] < 0 < hi[0]
                and 100.0 <= width <= 350.0
                and height <= 20.0
                and 80.0 <= depth <= 250.0
                and len(record["members"]) >= MIN_SPLIT_PRIMS):
            anchors.append(record)
    if anchors and broad_only:
        return None

    broad_anchor = False
    if not anchors:
        # A few imports scale the normal arena much wider/deeper than vanilla
        # while retaining the same shallow, centre-crossing structure.  Only
        # consider this broader envelope when the standard anchor found
        # nothing, so it cannot perturb already classified layouts.
        broad_anchor = True
        for record in records:
            lo, hi = record["lo"], record["hi"]
            width = hi[0] - lo[0]
            height = hi[1] - lo[1]
            depth = hi[2] - lo[2]
            if (lo[0] < 0 < hi[0]
                    and 100.0 <= width <= 450.0
                    and height <= 20.0
                    and 80.0 <= depth <= 400.0
                    and len(record["members"]) >= MIN_SPLIT_PRIMS):
                anchors.append(record)
    if not anchors:
        return None

    # Far scenery can also contain wide flat polygons.  The visible arena is
    # the front-most cluster of matching material layers.
    front = max(anchor["hi"][2] for anchor in anchors)
    anchors = [anchor for anchor in anchors
               if anchor["hi"][2] >= front - 80.0]
    z_lo = min(anchor["lo"][2] for anchor in anchors) - 60.0
    z_hi = max(anchor["hi"][2] for anchor in anchors) + \
        (180.0 if broad_anchor else 30.0)
    deck_y = max(anchor["hi"][1] for anchor in anchors)
    x_lo = min(anchor["lo"][0] for anchor in anchors) - 10.0
    x_hi = max(anchor["hi"][0] for anchor in anchors) + 10.0

    hits = {}
    for record in records:
        lo, hi = record["lo"], record["hi"]
        width = hi[0] - lo[0]
        height = hi[1] - lo[1]
        depth = hi[2] - lo[2]
        in_depth_band = lo[2] >= z_lo and hi[2] <= z_hi
        one_sided = hi[0] <= -PAD_SIDE_MIN_X or lo[0] >= PAD_SIDE_MIN_X
        in_deck_envelope = lo[0] >= x_lo and hi[0] <= x_hi
        # A walking surface must span both horizontal axes.  Requiring both is
        # what separates a broad vertical ledge wall (wide X, zero Z depth)
        # from a shallow sloped floor.
        useful_extent = width >= 10.0 and depth >= 10.0
        # Main-floor top coats are nearly planar.  Some forced-perspective
        # imports use one sparse, broad quad whose two triangles slope by more
        # than five world units, so permit the proportional allowance only for
        # that simple surface.  Applying it to a dense connected component can
        # swallow the arena's whole rim/skirt (Sky High has a 68-primitive,
        # 13-unit-tall shell), making the ledges disappear during transforms.
        sparse_sloped_surface = len(record['members']) <= 4
        surface_height_limit = MAIN_SURFACE_MAX_HEIGHT
        if sparse_sloped_surface:
            surface_height_limit = max(
                surface_height_limit, 0.10 * max(width, depth))
        main_surface = (height <= surface_height_limit
                        and deck_y - surface_height_limit <= lo[1]
                        and hi[1] >= deck_y - MAIN_SURFACE_Y_SLOP
                        and hi[1] <= deck_y + MAIN_SURFACE_Y_SLOP
                        and in_depth_band and in_deck_envelope
                        and useful_extent)
        # Upper pads follow the deck's own transformed coordinate space; this
        # also covers forced-perspective imports such as Sky High.  The deck X
        # envelope and depth cluster keep unrelated terraces/scenery out.
        upper_pad = (one_sided
                     and 20.0 <= width <= 80.0
                     and height <= 10.0 and depth <= 80.0
                     and 10.0 <= lo[1] - deck_y <= 45.0
                     and in_depth_band and in_deck_envelope)
        if main_surface or upper_pad:
            hits.setdefault(record["pobj"], set()).update(
                primitive[0] for primitive in record["members"])
    return hits

def _pad_components(prims, world_of):
    """Cluster primitives by shared POS indices; return the union of hit
    offsets for components that classify as side pads."""
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for off, _, idxs in prims:
        key = ("p", off)
        parent.setdefault(key, key)
        for i in idxs:
            vk = ("v", i)
            parent.setdefault(vk, vk)
            union(key, vk)

    comps = {}
    for off, ln, idxs in prims:
        comps.setdefault(find(("p", off)), []).append((off, ln, idxs))

    hit_offsets = set()
    for members in comps.values():
        pts = [world_of(i) for _, _, idxs in members for i in idxs]
        if not pts:
            continue
        min_x = min(p[0] for p in pts)
        max_x = max(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        max_y = max(p[1] for p in pts)
        max_az = max(abs(p[2]) for p in pts)
        one_sided = max_x <= -PAD_SIDE_MIN_X or min_x >= PAD_SIDE_MIN_X
        if (one_sided
                and PAD_TOP_MIN_Y <= max_y <= PAD_TOP_MAX_Y
                and min_y >= PAD_BOTTOM_MIN_Y
                and (max_x - min_x) <= PAD_MAX_EXTENT_X
                and max_az <= PAD_MAX_ABS_Z):
            hit_offsets.update(off for off, _, _ in members)
    return hit_offsets


def _has_baked_split_carrier(dat):
    """Recognize carriers produced by :func:`split_baked_platforms`.

    New carrier PObjs share both their source MObj and vertex descriptor with
    a PObj still hosted in a permanent group.  Ordinary group-5 geometry does
    not have that cross-group identity, while checking both pointers avoids a
    false match on common materials alone.
    """
    roots = _groups(dat)
    g5root = roots[GROUP_NORMAL]
    if g5root is None:
        return False

    permanent_pairs = set()
    for gi in CANDIDATE_GROUPS:
        root = roots[gi]
        if root is None:
            continue
        for _, jobj, _, _ in _walk_subtree(dat, root):
            for dobj in dobj_chain(dat, jobj):
                mobj = dat.u32(dobj + 0x08)
                pobj = dat.u32(dobj + 0x0C)
                while dat.valid(pobj):
                    desc = dat.u32(pobj + 0x08)
                    # Synthetic/minimal stages may omit an MObj entirely; the
                    # shared descriptor is still the source identity in that
                    # case, represented by the exact (NULL, desc) pair.
                    if dat.valid(desc):
                        permanent_pairs.add((mobj, desc))
                    pobj = dat.u32(pobj + 0x04)

    for carrier in jobj_children(dat, g5root):
        for dobj in dobj_chain(dat, carrier):
            mobj = dat.u32(dobj + 0x08)
            pobj = dat.u32(dobj + 0x0C)
            while dat.valid(pobj):
                if (mobj, dat.u32(pobj + 0x08)) in permanent_pairs:
                    return True
                pobj = dat.u32(pobj + 0x04)
    return False


def split_baked_platforms(dat, broad_only=False) -> list:
    """Carve playfield primitives out of permanent-group display lists into new
    group-5 hosted geometry.  Returns an action log (empty = nothing done).
    Only touches hosts whose ancestors (below the group root) are identity,
    so the carrier can clone the host transform verbatim."""
    log = []
    roots = _groups(dat)
    g5root = roots[GROUP_NORMAL]
    if g5root is None:
        return log

    for gi in CANDIDATE_GROUPS:
        root = roots[gi]
        if root is None:
            continue
        hosts = [(None, root)] + [(root, c) for c in jobj_children(dat, root)]
        for parent, host in hosts:
            if parent is not None and not _is_identity_jobj(dat, parent) \
                    and parent != root:
                continue
            if parent is not None and not _is_identity_jobj(dat, root):
                continue  # rotated root with nested children: unsupported
            rot, scale, trans = _jobj_local(dat, host)
            m = _rot_matrix(*rot)

            plain_m = [[m[row][col] * scale[col] for col in range(3)]
                       for row in range(3)]
            meshes = []
            for scan_dobj in dobj_chain(dat, host):
                scan_pobj = dat.u32(scan_dobj + 0x0C)
                while dat.valid(scan_pobj):
                    try:
                        scan_reader = _pos_reader(dat, scan_pobj)
                        scan_prims = list(_iter_primitives(dat, scan_pobj)) \
                            if scan_reader else []
                    except (RepairError, struct.error, IndexError):
                        scan_prims = []
                    scan_flags = dat.u16(scan_pobj + 0x0C) \
                        if scan_prims else 0
                    scan_bind = _envelope_single_bind(dat, scan_pobj) \
                        if scan_prims else None
                    if scan_prims and not (scan_flags & 0x2000 \
                                           and scan_bind is None):
                        if scan_bind is not None:
                            scan_m, scan_t = _skinning_matrix(
                                dat, root, scan_bind)
                        else:
                            scan_m, scan_t = plain_m, trans
                        meshes.append((scan_pobj, scan_prims,
                                       _transform_reader(scan_reader, scan_m,
                                                         scan_t)))
                    scan_pobj = dat.u32(scan_pobj + 0x04)
            # Group 1 is the background/buildings group.  A broad flat rooftop
            # there can resemble a deck (Battle City's skyline contains one),
            # but vanilla never hides that scenery with the normal-form model.
            # Keep mesh-relative deck classification on the arena shell; group
            # 1 still gets the conservative collision-space side-pad fallback.
            playfield_hits = (_playfield_component_hits(
                meshes, broad_only=broad_only) if gi == GROUP_SHELL else None)

            # carriers keyed by the transform the moved geometry needs:
            # ("host",) = clone of the host TRS (plain pobjs);
            # ("bind", jobj) = world(bind) @ inverse_bind (de-skinned pobjs)
            carriers = {}
            envelope_carriers = set()
            for dobj in dobj_chain(dat, host):
                pobj = dat.u32(dobj + 0x0C)
                new_pobjs = {}
                while dat.valid(pobj):
                    try:
                        reader = _pos_reader(dat, pobj)
                        prims = list(_iter_primitives(dat, pobj)) \
                            if reader else []
                    except (RepairError, struct.error, IndexError):
                        prims = []
                    flags = dat.u16(pobj + 0x0C) if prims else 0
                    bind = _envelope_single_bind(dat, pobj) if prims else None
                    if prims and (flags & 0x2000) and bind is None:
                        log_note = (f"jobj@0x{host:X}: multi-bone skinned "
                                    f"pobj -- cannot split, skipping")
                        if log_note not in log:
                            log.append(log_note)
                        prims = []
                    if prims:
                        if bind is not None:
                            # Envelope vertex arrays are authored in bind
                            # space; classify through the renderer's rest-pose
                            # skinning matrix, not the host TRS.
                            skin_m, skin_t = _skinning_matrix(dat, root, bind)
                            world_of = _transform_reader(reader, skin_m,
                                                         skin_t)
                        else:
                            world_of = _transform_reader(reader, plain_m,
                                                         trans)
                        hit_offs = (playfield_hits.get(pobj, set())
                                    if playfield_hits is not None
                                    else _pad_components(prims, world_of))
                    else:
                        hit_offs = set()
                    hits = [pr for pr in prims if pr[0] in hit_offs]
                    if len(hits) >= MIN_SPLIT_PRIMS:
                        hit_set = {pr[0] for pr in hits}
                        kept = b"".join(
                            bytes(dat.b[0x20 + o:0x20 + o + ln])
                            for o, ln, _ in prims if o not in hit_set)
                        # Keep the source pobj's rendering contract intact --
                        # same descriptor, same flags, its own envelope copy
                        # when skinned -- so only the display list is new and
                        # the geometry lands exactly where it always did.
                        moved = b"".join(
                            bytes(dat.b[0x20 + o:0x20 + o + ln])
                            for o, ln, _ in hits)
                        new_flags = flags
                        ckey = ("host",)
                        # compact the source list in place; zeros terminate
                        disp = dat.u32(pobj + 0x10)
                        size = dat.u16(pobj + 0x0E) * 32
                        dat.b[0x20 + disp:0x20 + disp + size] = \
                            kept + bytes(size - len(kept))
                        src_desc = dat.u32(pobj + 0x08)
                        pad = (-len(moved)) % 32
                        new_disp = _append_data(dat, moved + bytes(pad),
                                                align=32)
                        blob = bytearray(0x18)
                        struct.pack_into(">H", blob, 0x0C, new_flags)
                        struct.pack_into(">H", blob, 0x0E,
                                         (len(moved) + pad) // 32)
                        new_pobj = _append_data(dat, blob)
                        dat.set_u32(new_pobj + 0x08, src_desc)
                        dat.reloc_add(new_pobj + 0x08)
                        dat.set_u32(new_pobj + 0x10, new_disp)
                        dat.reloc_add(new_pobj + 0x10)
                        src_env = dat.u32(pobj + 0x14)
                        if (new_flags & 0x2000) and dat.valid(src_env):
                            env_off = _copy_envelope(dat, src_env)
                            dat.set_u32(new_pobj + 0x14, env_off)
                            dat.reloc_add(new_pobj + 0x14)
                            envelope_carriers.add(ckey)
                        new_pobjs.setdefault(ckey, []).append(new_pobj)
                        log.append(
                            f"split {len(hits)} playfield primitives out of "
                            f"jobj@0x{host:X}/dobj@0x{dobj:X} (group {gi})")
                    pobj = dat.u32(pobj + 0x04)
                for ckey, plist in new_pobjs.items():
                    for a, b in zip(plist, plist[1:]):
                        dat.set_u32(a + 0x04, b)
                        dat.reloc_add(a + 0x04)
                    nd = _append_data(dat, bytes(0x10))
                    mobj = dat.u32(dobj + 0x08)
                    if dat.valid(mobj):
                        dat.set_u32(nd + 0x08, mobj)
                        dat.reloc_add(nd + 0x08)
                    dat.set_u32(nd + 0x0C, plist[0])
                    dat.reloc_add(nd + 0x0C)
                    carriers.setdefault(ckey, []).append(nd)
            for ckey, dlist in carriers.items():
                for a, b in zip(dlist, dlist[1:]):
                    dat.set_u32(a + 0x04, b)
                    dat.reloc_add(a + 0x04)
                if ckey[0] == "bind":
                    sm, st = _skinning_matrix(dat, root, ckey[1])
                    crot, cscale, ctrans = _decompose_trs(sm, st)
                else:
                    crot, cscale, ctrans = rot, scale, trans
                carrier = _append_data(dat, bytes(0x40))
                carrier_flags = JOBJ_CLASSICAL_SCALING | JOBJ_OPA
                if ckey in envelope_carriers:
                    # HSD's envelope matrix setup requires the hosting JObj to
                    # advertise both halves of the skeleton/envelope contract.
                    # Missing either bit freezes Melee at stage-load frame 1,
                    # even though HSDRawViewer accepts and renders the archive.
                    carrier_flags |= JOBJ_SKELETON_ROOT | JOBJ_ENVELOPE_MODEL
                dat.set_u32(carrier + 0x04, carrier_flags)
                for i in range(3):
                    struct.pack_into(">f", dat.b,
                                     0x20 + carrier + 0x14 + 4 * i, crot[i])
                    struct.pack_into(">f", dat.b,
                                     0x20 + carrier + 0x20 + 4 * i, cscale[i])
                    struct.pack_into(">f", dat.b,
                                     0x20 + carrier + 0x2C + 4 * i, ctrans[i])
                dat.set_u32(carrier + 0x10, dlist[0])
                dat.reloc_add(carrier + 0x10)
                _append_child(dat, g5root, carrier)
    return log
