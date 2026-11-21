"""What a body's skin costs the game every frame, and making it cost less.

Melee skins a body on its own processor. A costume's polygons come in groups, and each group names up to ten
WEIGHTINGS (a list of joints with a share each); every frame, for every group, the game works out one blended
matrix for each weighting the group names (a weighted sum over its joints, then an inverse for the lighting). The
count that matters is therefore the weightings summed over the groups, and the joints summed over those. Marth's
own costume asks for 387 matrices over 497 joint shares. A body brought from a newer game has a weighting of its
own on almost every vertex (four joints, shares to three places): Duck Hunt's as imported asked for 8,156 over
20,578 and the game ran at 30 to 46 frames a second, where Ike's (2,516 over 5,092) held 60.

`cost` counts; `lighten` gives each vertex fewer joints and rounder shares before the body is imported, so that
vertices share weightings as a Melee artist's would; `low_detail` adds the cheap copy the engine draws for the
shadow; `regroup` makes an imported costume's polygon groups again, so that a weighting is named by as few groups as
can be (the importer puts each triangle strip in the first group with room, and a weighting ends up in about five).
"""
from __future__ import annotations

import struct
from collections import Counter, defaultdict

JOINT_IS_SPLINE, JOINT_IS_PARTICLE = 1 << 14, 1 << 5
GROUP_KIND, SKINNED = 0x3000, 0x2000


def objects(costume: bytes) -> list:
    """A costume's drawn pieces in the order the engine numbers them (joint by joint down the tree, each joint's
    pieces in turn), then the number of joints as the last item. Each piece: dict(joint, groups, matrices, weights,
    most_in_a_group, most_joints (the most joints any of its weightings blends), list_bytes, image (the first
    texture's width and height, or None))."""
    b = bytes(costume)
    _size, data, relocs, roots, refs = struct.unpack_from('>5I', b, 0)
    base = 0x20
    u32 = lambda o: struct.unpack_from('>I', b, base + o)[0]        # noqa: E731
    u16 = lambda o: struct.unpack_from('>H', b, base + o)[0]        # noqa: E731
    table = base + data + relocs * 4
    strings = table + (roots + refs) * 8
    root = None
    for i in range(roots):
        off, name = struct.unpack_from('>II', b, table + i * 8)
        text = b[strings + name:b.index(b'\0', strings + name)].decode('ascii', 'replace')
        if text.endswith('_joint') and 'matanim' not in text and 'shapeanim' not in text:
            root = off
            break
    if root is None:
        raise ValueError('the file has no joint tree')
    out, joints = [], 0
    stack = [root]
    while stack:                                   # a joint, then all below it, then the joint beside it
        j = stack.pop()
        number, joints = joints, joints + 1
        flags, child, nxt, obj = u32(j + 4), u32(j + 8), u32(j + 0xC), u32(j + 0x10)
        if flags & (JOINT_IS_SPLINE | JOINT_IS_PARTICLE):
            obj = 0
        while obj:
            row = dict(joint=number, groups=0, matrices=0, weights=0, most_in_a_group=0, most_joints=0, list_bytes=0,
                       image=None)
            material = u32(obj + 8)
            texture = u32(material + 8) if material else 0
            image = u32(texture + 0x4C) if texture else 0
            if image:
                row['image'] = (u16(image + 4), u16(image + 6))
            group = u32(obj + 0xC)
            while group:
                row['groups'] += 1
                row['list_bytes'] += u16(group + 0xE) * 32
                named = u32(group + 0x14)
                if u16(group + 0xC) & GROUP_KIND == SKINNED and named:
                    n = 0
                    while u32(named + 4 * n):
                        one, k = u32(named + 4 * n), 0
                        while u32(one + 8 * k):
                            k += 1
                        row['weights'] += k
                        row['most_joints'] = max(row['most_joints'], k)
                        n += 1
                    row['matrices'] += n
                    row['most_in_a_group'] = max(row['most_in_a_group'], n)
                group = u32(group + 4)
            out.append(row)
            obj = u32(obj + 4)
        if nxt:
            stack.append(nxt)
        if child:
            stack.append(child)
    out.append(joints)
    return out


# The game's picture formats, by its own numbers: (name, bytes a pixel). A plain picture or a cutout is stored in
# CMPR (4 bits a pixel); one with soft edges cannot be (CMPR keeps one bit of see-through) and is stored in RGB5A3,
# at 16 bits a pixel: four times the room.
PICTURE_FORMATS = {0: ('I4', 0.5), 1: ('I8', 1), 2: ('IA4', 1), 3: ('IA8', 2), 4: ('RGB565', 2), 5: ('RGB5A3', 2),
                   6: ('RGBA8', 4), 8: ('CI4', 0.5), 9: ('CI8', 1), 10: ('CI14', 2), 14: ('CMPR', 0.5)}
PLAIN_BITS, SOFT_BITS = 4, 16       # bits a pixel: CMPR, and RGB5A3
# A costume the match's file heap has been seen to hold, and the size past which one stops the `costumes` stage.
# The heap is 6,599,680 bytes for every file of the match (lbmemory.c); each costume in the match is held whole,
# once a colour. Two costumes of 2.9 MB did not load (Duck Hunt before his pictures were made smaller), nor did two
# of 3.4 MB, nor one of them beside Peach on Pokemon Stadium (Wolf); at 1.8 MB both fighters load everywhere, with
# 0.05 to 0.8 MB to spare on the largest stage. Between the two nothing has been measured, so the line is drawn low.
COSTUME_MOST = 2_000_000


def bytes_by_kind(costume: bytes) -> dict:
    """Where a costume file's bytes go: its pictures (each counted once however many pieces use it; by stored
    format, with the sizes), its display lists, and everything else (vertex buffers, weight lists, joints,
    materials, palettes). -> dict(bytes, pictures=dict(bytes, count, by_format={name: dict(bytes, count, sizes)}),
    display_lists, rest). The measuring was first written by hand in Wolf's cold trial, after two matches that
    never loaded: 2.1 MB of his 3.4 MB costume was four pictures with soft edges."""
    b = bytes(costume)
    _size, data, relocs, roots, refs = struct.unpack_from('>5I', b, 0)
    base = 0x20
    u32 = lambda o: struct.unpack_from('>I', b, base + o)[0]        # noqa: E731
    u16 = lambda o: struct.unpack_from('>H', b, base + o)[0]        # noqa: E731
    table = base + data + relocs * 4
    strings = table + (roots + refs) * 8
    root = None
    for i in range(roots):
        off, name = struct.unpack_from('>II', b, table + i * 8)
        text = b[strings + name:b.index(b'\0', strings + name)].decode('ascii', 'replace')
        if text.endswith('_joint') and 'matanim' not in text and 'shapeanim' not in text:
            root = off
            break
    if root is None:
        raise ValueError('the file has no joint tree')
    images, lists, seen, stack = {}, 0, set(), [root]
    while stack:
        j = stack.pop()
        if j in seen:
            continue
        seen.add(j)
        flags, child, nxt, obj = u32(j + 4), u32(j + 8), u32(j + 0xC), u32(j + 0x10)
        stack += [x for x in (nxt, child) if x]
        if flags & (JOINT_IS_SPLINE | JOINT_IS_PARTICLE):
            obj = 0
        while obj:
            material = u32(obj + 8)
            texture = u32(material + 8) if material else 0
            while texture:                              # every picture a material lays on, not only its first
                image = u32(texture + 0x4C)
                if image:
                    images[u32(image)] = (u16(image + 4), u16(image + 6), u32(image + 8))
                texture = u32(texture + 4)
            group = u32(obj + 0xC)
            while group:
                lists += u16(group + 0xE) * 32
                group = u32(group + 4)
            obj = u32(obj + 4)
    by_format = {}
    for width, height, fmt in sorted(images.values(), reverse=True):
        name, per_pixel = PICTURE_FORMATS.get(fmt, (f'format {fmt}', 2))
        row = by_format.setdefault(name, dict(bytes=0, count=0, sizes=[]))
        row['bytes'] += int(width * height * per_pixel)
        row['count'] += 1
        row['sizes'].append(f'{width}x{height}')
    pictures = sum(r['bytes'] for r in by_format.values())
    return dict(bytes=len(b), pictures=dict(bytes=pictures, count=len(images), by_format=by_format),
                display_lists=lists, rest=len(b) - pictures - lists)


def kind_lines(name, kinds) -> list:
    """`bytes_by_kind` as lines to print: the whole, then pictures by format, display lists, the rest."""
    from collections import Counter as _Counter
    lines = [f"{name}: {kinds['bytes']:,} bytes"]
    for fmt, row in sorted(kinds['pictures']['by_format'].items(), key=lambda kv: -kv[1]['bytes']):
        sizes = ', '.join(f'{n} of {s}' if n > 1 else s for s, n in _Counter(row['sizes']).items())
        lines.append(f"   pictures {fmt:7} {row['bytes']:>10,} bytes  ({row['count']}: {sizes})")
    lines.append(f"   display lists    {kinds['display_lists']:>10,} bytes")
    lines.append(f"   everything else  {kinds['rest']:>10,} bytes  (vertex buffers, weight lists, joints, materials)")
    return lines


def too_large(name, kinds, most=COSTUME_MOST):
    """Why a costume of this size (`bytes_by_kind`) stops the `costumes` stage and what to do, or None when it is
    not over `most`."""
    if kinds['bytes'] <= most:
        return None
    soft_ = kinds['pictures']['by_format'].get('RGB5A3', {}).get('bytes', 0)
    where = (f'its pictures with soft edges are {soft_:,} bytes at {SOFT_BITS} bits a pixel '
             '(own_skeleton.PICTURE_SIDE and skin_cost.soft_side set their side)' if soft_ > kinds['bytes'] // 4 else
             'pictures: own_skeleton.PICTURE_SIDE; display lists: the parts the body carries, and skin_cost.regroup')
    return (f"{name} is {kinds['bytes']:,} bytes: over {most:,}. A match holds every file in one heap of 6,599,680 "
            'bytes and each costume whole, once a colour: two costumes of 2.9 MB did not load (the game hangs after '
            'stage select), and 1.8 MB leaves 0.05 to 0.8 MB on the largest stage. Make the largest kind smaller first '
            f'({where}), or give --allow-large (the port command passes it on) to build them as they are, and then '
            'read the heap in the game with its picture looked at (harness/heap_probe.py: two of the fighter in two '
            'colours, and beside Peach on Pokemon Stadium).')


def costume_room(name, costume: bytes, allow_large=False):
    """One built costume held against what a match holds, as the `costumes` stage asks it of each costume in turn.
    -> (its bytes by kind, the lines to print, why the stage stops here or None). Over `COSTUME_MOST` the stage
    stops, unless `allow_large`: then it goes on, and the last line says the costume is over and what is owed."""
    kinds = bytes_by_kind(costume)
    lines, stop = kind_lines(name, kinds), too_large(name, kinds)
    if stop and allow_large:
        lines.append(f'   OVER {COSTUME_MOST:,} bytes, built all the same (--allow-large): read the heap in the game '
                     '(harness/heap_probe.py, its picture looked at) before believing a disc with it')
        stop = None
    return kinds, lines, stop


def cost(costume: bytes, only=None) -> dict:
    """Count a costume file: joints, drawn pieces, polygon groups, `matrices` (the weightings summed over the
    groups: one blend each a frame), `weights` (the joints summed over those), the most weightings one group names,
    and the bytes of its display lists. `only`: the piece numbers to count (all of them when None)."""
    rows = objects(costume)
    joints = rows.pop()
    if only is not None:
        rows = [rows[i] for i in only]
    return dict(joints=joints, objects=len(rows), groups=sum(r['groups'] for r in rows),
                matrices=sum(r['matrices'] for r in rows), weights=sum(r['weights'] for r in rows),
                most_in_a_group=max((r['most_in_a_group'] for r in rows), default=0),
                list_bytes=sum(r['list_bytes'] for r in rows))


def simpler(links, most: int, steps: int):
    """One vertex's weighting made simpler: its `most` heaviest joints, their shares rounded to whole parts of
    `steps` that still add up to all of it (the parts lost to rounding go to the joints that lost the most).
    links: [(joint, share)]. -> ((joint, parts), ...) in joint order; a joint left with no part is dropped."""
    whole = {}
    for joint, share in links:                          # (a joint named twice is one joint)
        whole[joint] = whole.get(joint, 0.0) + share
    links = sorted((l for l in whole.items() if l[1] > 0), key=lambda l: -l[1])[:most]
    total = sum(w for _j, w in links)
    exact = [(j, w / total * steps) for j, w in links]
    parts = {j: int(e) for j, e in exact}
    short = steps - sum(parts.values())
    for j, e in sorted(exact, key=lambda x: -(x[1] - int(x[1])))[:short]:
        parts[j] += 1
    return tuple(sorted((j, p) for j, p in parts.items() if p))


def lighten(model, most: int, steps: int) -> dict:
    """Give every vertex of a model (`shared.modellab.smd.SMD`) a simpler weighting, in place. -> what changed:
    how many different weightings there were and are, and the furthest any vertex's share moved."""
    before, after, moved = set(), set(), 0.0
    for t in model.triangles:
        for v in t.verts:
            links = [(j, w) for j, w in (v.weights or [(v.parent, 1.0)]) if w > 0]
            total = sum(w for _j, w in links)
            before.add(tuple(sorted((j, round(w / total, 4)) for j, w in links)))
            new = simpler(links, most, steps)
            was = {j: w / total for j, w in links}
            now = {j: p / steps for j, p in new}
            moved = max(moved, max(abs(was.get(j, 0.0) - now.get(j, 0.0)) for j in set(was) | set(now)))
            after.add(new)
            v.weights = [(j, p / steps) for j, p in new]
    return dict(most_joints=most, steps=steps, weightings_before=len(before), weightings_after=len(after),
                furthest_share_moved=round(moved, 3))


LOW = 'zlow_'                       # a low-detail piece's material is its body piece's with this before it
LOW_SIDE = 64                       # the longest side of a low-detail piece's picture
LOW_SHARE = 0.2                     # the share of a piece's triangles its low-detail copy keeps
LOW_WHOLE = 64                      # a piece of this many triangles or fewer is copied whole


def low_detail(model, only=None, share=LOW_SHARE) -> dict:
    """Add a body's low-detail copy to a model (`shared.modellab.smd.SMD`), in place: each piece again with about
    `share` of its triangles (`fewer`), under a material of its own, each vertex held by one joint.
    -> {low material: body material}. `only`: the materials to copy (all of them when None). A body that carries
    parts it shows and hides (a face of part swaps, `own_faces`) copies what it draws at rest: the shadow's outline
    is the resting one. `share` 1.0 copies every triangle as it is.

    Melee draws a fighter a second time every frame for its shadow (and for the reflection in one stage's water and
    the bubble that shows a fighter off the screen), and for that it shows the fighter's low-detail pieces and hides
    the rest. A fighter with no low-detail pieces is drawn whole again: its skin is worked out twice a frame. One
    joint a vertex needs no blending, and all of a body's vertices then share about as many matrices as it has
    joints. The copy was once every triangle again; a body from a newer game has ten times a Melee fighter's
    triangles, and Duck Hunt's copy (17,868 triangles) was what put two of him over the heap on Pokemon Stadium.
    Melee's own low-detail pieces are as plain as a shadow needs."""
    from dataclasses import replace
    groups = {}
    for t in model.triangles:
        if only is None or t.material in only:
            groups.setdefault(t.material, []).append(t)
    made, extra = {}, []
    for material, tris in groups.items():
        name = made[material] = LOW + material
        tris = fewer(tris, share) if share < 1.0 and len(tris) > LOW_WHOLE else tris
        for t in tris:
            verts = tuple(replace(v, weights=[(max(v.weights or [(v.parent, 1.0)], key=lambda l: l[1])[0], 1.0)])
                          for v in t.verts)
            extra.append(replace(t, material=name, verts=verts))
    model.triangles.extend(extra)
    return {low: body for body, low in made.items()}


def fewer(tris, share, by_island=False, whole=16):
    """One piece's triangles made fewer (about `share` of them) by merging the edges whose loss moves its surface
    least (`pyfqmr`, quadric error; the open edges kept where they are). Each new corner takes everything but its
    place (normal, picture coordinates, joints) from the nearest corner of the piece as it was. -> the new triangles,
    or the old ones when the merging leaves nothing.

    `by_island`: for a part that is seen, its picture must not slide. Each island of the picture (triangles joined
    by corners that share a place AND a picture coordinate) is merged on its own, so a seam of the picture is an
    open edge, kept where it is, and a new corner takes its picture coordinate from its own island. An island of
    `whole` triangles or fewer is kept as it is."""
    if not by_island:
        return _fewer(tris, share)
    key = lambda v: (tuple(round(c, 5) for c in v.pos), tuple(round(c, 5) for c in v.uv))     # noqa: E731
    parent = {}

    def root(k):
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for t in tris:
        a = root(key(t.verts[0]))
        for v in t.verts[1:]:
            parent[root(key(v))] = a
    islands = {}
    for t in tris:
        islands.setdefault(root(key(t.verts[0])), []).append(t)
    out = []
    for island in islands.values():
        out.extend(island if len(island) <= whole else _fewer(island, share))
    return out


def _fewer(tris, share):
    from dataclasses import replace
    import numpy as np
    import pyfqmr
    from scipy.spatial import cKDTree
    index, points, corners, faces = {}, [], [], []
    for t in tris:
        face = []
        for v in t.verts:
            key = tuple(round(c, 5) for c in v.pos)
            if key not in index:
                index[key] = len(points)
                points.append(key)
                corners.append(v)
            face.append(index[key])
        faces.append(face)
    s = pyfqmr.Simplify()
    s.setMesh(np.array(points, dtype=np.float64), np.array(faces, dtype=np.int32))
    s.simplify_mesh(target_count=max(16, int(len(faces) * share)), aggressiveness=7, preserve_border=True,
                    verbose=False)
    new_points, new_faces, _normals = s.getMesh()
    if not len(new_faces):
        return tris
    # Each new corner is put on the piece as it was: the nearest point of the old triangles near it (eight by
    # their middles). Its picture coordinate and normal are that point's, blended from the old triangle's three
    # corners, so the picture does not slide; its joints are those of the old corner it lies nearest.
    P, F = np.array(points), np.array(faces)
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    Q = np.asarray(new_points, dtype=np.float64)
    k = min(8, len(F))
    _d, near = cKDTree((A + B + C) / 3).query(Q, k=k)
    near = np.asarray(near).reshape(len(Q), k)
    a, b, c = A[near], B[near], C[near]                               # (points, k, 3)
    v0, v1, v2 = b - a, c - a, Q[:, None, :] - a
    dot = lambda x, y: np.einsum('nki,nki->nk', x, y)                 # noqa: E731
    d00, d01, d11, d20, d21 = dot(v0, v0), dot(v0, v1), dot(v1, v1), dot(v2, v0), dot(v2, v1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-12, 1e-12, d00 * d11 - d01 * d01)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    bary = np.clip(np.stack([1 - v - w, v, w], axis=-1), 0, None)
    bary /= np.where(bary.sum(-1, keepdims=True) > 0, bary.sum(-1, keepdims=True), 1)
    spot = bary[..., 0:1] * a + bary[..., 1:2] * b + bary[..., 2:3] * c
    pick = np.argmin(np.linalg.norm(spot - Q[:, None, :], axis=-1), axis=1)
    rows = np.arange(len(Q))
    face, weight = F[near[rows, pick]], bary[rows, pick]              # (points, 3) each
    uv = np.array([v.uv for v in corners])
    normal = np.array([v.normal for v in corners])
    new_uv = np.einsum('ni,nij->nj', weight, uv[face])
    new_normal = np.einsum('ni,nij->nj', weight, normal[face])
    new_normal /= np.maximum(np.linalg.norm(new_normal, axis=1, keepdims=True), 1e-9)
    nearest = face[rows, np.argmax(weight, axis=1)]
    like = [replace(corners[n], pos=tuple(float(x) for x in p), uv=tuple(float(x) for x in t),
                    normal=tuple(float(x) for x in m))
            for p, n, t, m in zip(Q, nearest, new_uv, new_normal)]
    material = tris[0].material
    return [replace(tris[0], material=material, verts=tuple(like[i] for i in face)) for face in new_faces
            if len(set(int(i) for i in face)) == 3]


HIDDEN_SHARE = 0.5                  # the share of its triangles a part hidden at rest keeps
HIDDEN_WHOLE = 400                  # ... a part of this many triangles or fewer is kept whole


def fewer_hidden(model, hidden, share=HIDDEN_SHARE, whole=HIDDEN_WHOLE) -> dict:
    """STAND-IN, for room: the parts hidden at rest (`hidden`: their materials) keep about `share` of their
    triangles (`fewer`, island by island of the picture, so no picture slides), in place; a part of `whole`
    triangles or fewer is kept whole. The order of the parts is kept (the face's groups number them).
    -> {material: [triangles before, after]}

    A body from a newer game carries every part its clips show and hide, and on Duck Hunt those were two thirds of
    his triangles (39,913 of 57,781) and 0.44 MB of each costume's drawing lists, for parts seen a few frames at a
    time. Room is found where `small_pictures` finds it for their pictures: what rest hides."""
    groups = {}
    for t in model.triangles:
        if t.material in hidden:
            groups.setdefault(t.material, []).append(t)
    made, done = {}, {}
    for material, tris in groups.items():
        if len(tris) <= whole:
            continue
        new = fewer(tris, share, by_island=True)
        if len(new) < len(tris):
            made[material], done[material] = new, [len(tris), len(new)]
    if made:
        triangles, placed = [], set()
        for t in model.triangles:
            if t.material not in made:
                triangles.append(t)
            elif t.material not in placed:
                placed.add(t.material)
                triangles.extend(made[t.material])
        model.triangles[:] = triangles
    return done


def low_pictures(folder, made, side=LOW_SIDE) -> None:
    """Each low-detail material's picture: its body material's, made small (beside it in `folder`)."""
    from pathlib import Path
    from PIL import Image
    for low, body in made.items():
        image = Image.open(Path(folder) / f'{body}.png')
        scale = min(1.0, side / max(image.size))
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        (image if scale == 1.0 else image.resize(size, Image.LANCZOS)).save(Path(folder) / f'{low}.png')


def soft(image) -> bool:
    """Whether the importer will store a picture at 16 bits a pixel: its OWN test, step for step (HSDRawViewer's
    ModelImporter.HasPartialAlpha: one pixel in every 64th of each side is looked at, and one whose see-through is
    between 8 and 248 of 255 is enough). So the answer here is the format the picture ends up in, not a guess at it."""
    rgba = image.convert('RGBA')
    alpha = rgba.getchannel('A').load()
    step_x, step_y = max(1, rgba.width // 64), max(1, rgba.height // 64)
    return any(8 < alpha[x, y] < 248 for y in range(0, rgba.height, step_y) for x in range(0, rgba.width, step_x))


def soft_side(plain_side: int) -> int:
    """The longest side a picture with soft edges may have, for it to take the room a plain one of `plain_side`
    does: fewer pixels by as much as each costs more (16 bits against 4: half the side)."""
    return max(1, int(plain_side * (PLAIN_BITS / SOFT_BITS) ** 0.5))


def soft_pictures(folder, materials, side) -> dict:
    """STAND-IN, for room, on every fighter: each material's picture (<material>.png in `folder`) that will be
    stored at 16 bits a pixel (`soft`) and is longer than `side`, made `side` at its longest, in place.
    -> {material: [size before, size after]}

    Which part uses the picture does not matter here (`small_pictures` is the rule for parts rest hides): a soft
    picture a part drawn at rest uses is where a costume's room goes. Wolf's four (his fur) at 512 a side were
    2.1 MB of a 3.4 MB costume, and two of him in two colours did not load on any stage; at 256 they are 0.5 MB."""
    from pathlib import Path
    from PIL import Image
    done = {}
    for material in materials:
        path = Path(folder) / f'{material}.png'
        if not path.exists():
            continue
        image = Image.open(path).convert('RGBA')
        if max(image.size) <= side or not soft(image):
            continue
        scale = side / max(image.size)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image.resize(size, Image.LANCZOS).save(path)
        done[material] = [list(image.size), list(size)]
    return done


HIDDEN_SIDE = 2                     # a picture only hidden parts use is made this many times smaller a side
HIDDEN_LEAST = 128                  # ... but no smaller than this
CUTOUT = 128                        # the alpha at which a soft edge is cut: all above it, nothing below


def small_pictures(folder, hidden, shown, shrink=HIDDEN_SIDE, least=HIDDEN_LEAST) -> dict:
    """STAND-IN, for room: the pictures that only parts hidden at rest use, made smaller, in place.

    A costume that carries every part its clips show and hide (`own_faces`) carries their pictures too, and a
    fighter's files share one heap with the stage and the other fighters (6.6 MB in a match: two Duck Hunts in
    two costumes of 2.9 MB each did not load). What is seen for a few frames at a time is where the room is found:
    a picture only such parts use is halved a side (never below `least`), and one with soft edges (alpha between
    nothing and all) is made a cutout, which the game holds in its small format (4 bits a pixel where a soft edge
    takes 16). A picture a part drawn at rest uses is not touched, whichever material asks for it.
    `hidden`, `shown`: the materials (their picture is <material>.png in `folder`) of the parts rest hides and of
    the ones it draws. -> {material: what was done}"""
    import hashlib
    from pathlib import Path
    import numpy as np
    from PIL import Image
    folder = Path(folder)
    kept = {hashlib.sha256((folder / f'{m}.png').read_bytes()).hexdigest() for m in shown}
    done, made = {}, {}
    for material in hidden:
        path = folder / f'{material}.png'
        was = hashlib.sha256(path.read_bytes()).hexdigest()
        if was in kept:
            continue
        if was not in made:
            image = Image.open(path).convert('RGBA')
            said = {}
            alpha = np.asarray(image)[..., 3]
            if ((alpha > 8) & (alpha < 247)).mean() > 0.001:
                pixels = np.asarray(image).copy()
                pixels[..., 3] = np.where(alpha >= CUTOUT, 255, 0)
                image = Image.fromarray(pixels, 'RGBA')
                said['cutout'] = True
            if shrink > 1 and max(image.size) // shrink >= least:
                size = (max(1, image.width // shrink), max(1, image.height // shrink))
                said['size'] = [list(image.size), list(size)]
                if said.get('cutout'):                   # (a cutout stays one: its edge is cut again after the resize)
                    pixels = np.asarray(image.resize(size, Image.LANCZOS)).copy()
                    pixels[..., 3] = np.where(pixels[..., 3] >= CUTOUT, 255, 0)
                    image = Image.fromarray(pixels, 'RGBA')
                else:
                    image = image.resize(size, Image.LANCZOS)
            made[was] = (image, said)
        image, said = made[was]
        if said:
            image.save(path)
            done[material] = said
    return done


def pieces(costume: bytes, body_materials: int, copied=None) -> dict:
    """Which of an imported costume's pieces are the body and which its low-detail copy, by the engine's numbers:
    {'high': [...], 'low': [...]}. The importer makes a piece a material, in the order the materials first appear,
    so the copies come after the body's; that is checked here (a low-detail piece blends nothing).
    `copied`: the body pieces that have a copy, in order (all of them when None: the copy is the second half)."""
    rows = objects(costume)
    rows.pop()
    high = list(range(body_materials))
    copied = high if copied is None else list(copied)
    if len(rows) != body_materials + len(copied):
        raise ValueError(f'{len(rows)} pieces came out of the import for {body_materials} materials and '
                         f'{len(copied)} copies')
    low = list(range(body_materials, body_materials + len(copied)))
    if any(rows[i]['most_joints'] > 1 for i in low):
        raise ValueError('a piece in the low-detail half blends joints: the pieces are not in the order expected')
    for a, b in zip(copied, low):
        if rows[a]['image'] and rows[b]['image'] and max(rows[b]['image']) > max(rows[a]['image']):
            raise ValueError(f'piece {b} has a larger picture than piece {a}, the body piece it should copy')
    return dict(high=high, low=low)


# ---------------------------------------------------------------------------------------- the groups, made again
MOST_IN_A_GROUP = 10                # the matrices one group can name (the graphics chip holds ten at a time)
MATRIX_NUMBERS = range(0, 9)        # the vertex attributes that are a matrix number: position, then eight textures
DIRECT, INDEX8, INDEX16 = 1, 2, 3
TRIANGLES, STRIP = 0x90, 0x98
HEAD = 0x20
MOST_IN_A_STRIP = 3                 # a strip that runs through more weightings than this is cut where they change


def cut(verts, which, most=MOST_IN_A_STRIP) -> list:
    """A triangle strip cut into strips that each run through at most `most` weightings (a single triangle may
    have three whatever `most` is). -> [(vertices, weightings)], drawing the same triangles the same way round:
    a piece that starts on an odd vertex of the strip has its first vertex twice, which turns its triangles back."""
    out, start, n = [], 0, len(verts)
    while start < n - 2:
        end = start + 3
        seen = set(which[start:end])
        while end < n and (which[end] in seen or len(seen) < most):
            seen.add(which[end])
            end += 1
        part_v, part_w = list(verts[start:end]), list(which[start:end])
        if start % 2:
            part_v, part_w = part_v[:1] + part_v, part_w[:1] + part_w
        out.append((part_v, part_w))
        start = end - 2
    return out


def triangles(kind, corners) -> list:
    """The triangles a primitive draws, each as three corners the way round it is drawn, starting from its least
    corner; a strip's triangles with two corners the same (they draw nothing) are left out."""
    if kind == 'triangle':
        found = [tuple(corners)]
    else:
        found = [(corners[i + 1], corners[i], corners[i + 2]) if i % 2 else (corners[i], corners[i + 1], corners[i + 2])
                 for i in range(len(corners) - 2)]
        found = [t for t in found if len(set(t)) == 3]
    out = []
    for t in found:
        k = t.index(min(t))
        out.append(t[k:] + t[:k])
    return out


def group(needs, most=MOST_IN_A_GROUP) -> list:
    """Sets of weightings, each at most `most`, such that every primitive's own set (`needs`: a frozenset each) lies
    inside one. A group is grown from the weighting most primitives use, taking each time the addition that lets
    in the most primitives for each weighting added; groups that fit together are then joined."""
    left = set(range(len(needs)))
    users = defaultdict(set)
    for i, need in enumerate(needs):
        if len(need) > most:
            raise ValueError(f'a primitive needs {len(need)} weightings; a group holds {most}')
        for w in need:
            users[w].add(i)
    out = []
    while left:
        seed = max((w for w in users if users[w]), key=lambda w: (len(users[w]), w))
        chosen = {seed}
        while True:
            gain = Counter()
            for i in set().union(*(users[w] for w in chosen)):
                more = needs[i] - chosen
                if more and len(chosen) + len(more) <= most:
                    gain[more] += 1
            if not gain:
                break
            chosen |= max(gain, key=lambda more: (gain[more] / len(more), -len(more), sorted(more)))
        inside = [i for i in left if needs[i] <= chosen]
        if not inside:                                   # nothing fits around that start: one primitive alone
            i = min(left)
            chosen, inside = set(needs[i]), [k for k in left if needs[k] <= needs[i]]
        out.append(chosen)
        for i in inside:
            left.discard(i)
            for w in needs[i]:
                users[w].discard(i)
    while True:                                          # join the two groups that share the most, while any two fit
        best = None
        for a in range(len(out)):
            for b in range(a + 1, len(out)):
                both = len(out[a] | out[b])
                if both <= most:
                    key = (len(out[a] & out[b]), -both)
                    if best is None or key > best[0]:
                        best = (key, a, b)
        if best is None:
            return out
        out[best[1]] |= out.pop(best[2])


def _layout(dat, desc):
    """A vertex as a group's description gives it: (the description as a value, to hold two against each other;
    the bytes a vertex takes in the list; where in those bytes its matrix numbers are, the position's first)."""
    rows, size, matrices, at = [], 0, [], desc
    while dat.u32(at) != 0xFF:
        attr, kind = dat.u32(at), dat.u32(at + 4)
        rows.append(tuple(dat.u32(at + 4 * k) for k in range(6)))
        if attr in MATRIX_NUMBERS:
            if kind != DIRECT:
                raise ValueError('a matrix number that is not written in the list itself')
            matrices.append((size, attr))
            size += 1
        elif kind == INDEX8:
            size += 1
        elif kind == INDEX16:
            size += 2
        elif kind:
            raise ValueError('a vertex attribute written out in the list itself is not read here')
        at += 0x18
    if not matrices or matrices[0][1] != 0:
        raise ValueError('the vertices carry no position matrix number')
    return tuple(rows), size, matrices


def _piece(dat, piece):
    """One piece's groups, read: dict(kinds, weightings). Groups with the same flags and the same vertex data are
    one kind: dict(desc, layout, flags, form, items), in the order the kinds are first met. An item is (kind,
    vertices, weightings): kind is 'triangle' or the strip's own first byte; vertices the bytes of each as written;
    weightings the place in the file of each vertex's weighting (one place for one weighting, however many groups
    named it). Raises ValueError for a piece this cannot take apart (its groups are then left as they are)."""
    buf = dat.buf
    same, kinds = {}, {}
    g = dat.ptr(piece + 0xC)
    while g is not None:
        flags = struct.unpack_from('>H', buf, HEAD + g + 0xC)[0]
        blocks = struct.unpack_from('>H', buf, HEAD + g + 0xE)[0]
        if flags & GROUP_KIND != SKINNED:
            raise ValueError('a group that is not skinned by weightings')
        desc = dat.ptr(g + 8)
        layout = _layout(dat, desc)
        kind = kinds.setdefault((layout[0], flags), dict(desc=desc, layout=layout, flags=flags, form=None, items=[]))
        named, slots, n = dat.ptr(g + 0x14), [], 0
        while dat.u32(named + 4 * n):
            one, k, key = dat.u32(named + 4 * n), 0, []
            while dat.u32(one + 8 * k):
                key.append((dat.u32(one + 8 * k), dat.u32(one + 8 * k + 4)))
                k += 1
            slots.append(same.setdefault(tuple(key), one))
            n += 1
        _rows, size, matrices = layout
        at, end = HEAD + dat.ptr(g + 0x10), HEAD + dat.ptr(g + 0x10) + blocks * 32
        while at < end and buf[at]:
            op = buf[at]
            if op & 0xF8 not in (TRIANGLES, STRIP):
                raise ValueError(f'a primitive of kind {op & 0xF8:#x}')
            if kind['form'] is None:
                kind['form'] = op & 7
            elif kind['form'] != op & 7:
                raise ValueError('two vertex formats in one kind of group')
            count = struct.unpack_from('>H', buf, at + 1)[0]
            verts = [bytes(buf[at + 3 + i * size:at + 3 + (i + 1) * size]) for i in range(count)]
            at += 3 + count * size
            which = []
            for v in verts:
                slot, rest = divmod(v[matrices[0][0]], 3)
                if rest or slot >= len(slots) or any(v[o] != 30 + 3 * slot for o, _a in matrices[1:]):
                    raise ValueError('a matrix number that names no weighting of its group')
                which.append(slots[slot])
            if op & 0xF8 == TRIANGLES:
                if count % 3:
                    raise ValueError('a triangle list that is not whole triangles')
                kind['items'] += [('triangle', verts[i:i + 3], which[i:i + 3]) for i in range(0, count, 3)]
            else:
                kind['items'].append((op, verts, which))
        g = dat.ptr(g + 4)
    if not kinds:
        raise ValueError('no groups')
    return dict(kinds=list(kinds.values()), weightings=same)


def _joints(dat):
    """{a joint's place in the file: its number} (a joint, then all below it, then the joint beside it)."""
    root = next((off for name, off in dat.roots if name.endswith('_joint') and 'matanim' not in name
                 and 'shapeanim' not in name), None)
    out, stack = {}, [] if root is None else [root]
    while stack:
        j = stack.pop()
        out[j] = len(out)
        child, nxt = dat.ptr(j + 8), dat.ptr(j + 0xC)
        if nxt is not None:
            stack.append(nxt)
        if child is not None:
            stack.append(child)
    return out


def _pieces(dat):
    """The places of a costume's pieces, in the engine's order."""
    root = next((off for name, off in dat.roots if name.endswith('_joint') and 'matanim' not in name
                 and 'shapeanim' not in name), None)
    if root is None:
        raise ValueError('the file has no joint tree')
    out, stack = [], [root]
    while stack:
        j = stack.pop()
        flags, child, nxt = dat.u32(j + 4), dat.ptr(j + 8), dat.ptr(j + 0xC)
        obj = None if flags & (JOINT_IS_SPLINE | JOINT_IS_PARTICLE) else dat.ptr(j + 0x10)
        while obj is not None:
            out.append(obj)
            obj = dat.ptr(obj + 4)
        if nxt is not None:
            stack.append(nxt)
        if child is not None:
            stack.append(child)
    return out


def _share(bits: int) -> float:
    return struct.unpack('>f', struct.pack('>I', bits))[0]


def drawn(costume: bytes, weights=None) -> list:
    """What each piece of a costume draws, whatever its groups and strips: a count of its triangles, each as its
    three corners the way round it is drawn, a corner being the vertex as written (without its matrix numbers)
    and the weighting it is held by, written out as joints and shares; with it, which kind of group it is in and
    that kind's flags. Two costumes that give the same list draw the same thing. A piece that cannot be read
    gives None. `weights` (most joints, steps): every weighting is read as `simpler` makes it, so a costume and
    the same costume with its weightings made simpler give the same list."""
    from vault.echo.subactions import Dat
    dat = Dat(bytes(costume))
    out, number = [], _joints(dat)
    for piece in _pieces(dat):
        try:
            got = _piece(dat, piece)
        except ValueError:
            out.append(None)
            continue
        # (with `weights`, a weighting of one joint is told from a blend that came down to one joint: the engine
        # reads the first in the joint's own space and the second in the model's)
        content = {place: ((len(key) == 1, simpler([(number[joint], _share(share)) for joint, share in key], *weights))
                           if weights else tuple((number[joint], share) for joint, share in key))
                   for key, place in got['weightings'].items()}
        count = Counter()
        for n, kind in enumerate(got['kinds']):
            drop = sorted(o for o, _a in kind['layout'][2])
            bare = lambda v: bytes(x for i, x in enumerate(v) if i not in drop)    # noqa: E731
            count.update((n, kind['flags'], t) for what, verts, which in kind['items']
                         for t in triangles(what, [(bare(v), content[w]) for v, w in zip(verts, which)]))
        out.append(count)
    return out


def part_starts(file: bytes) -> set:
    """Every place in a file's data that a pointer or a named root points to: where its parts begin."""
    b = bytes(file)
    _size, data_size, reloc_count, root_count, _refs = struct.unpack_from('>5I', b, 0)
    slots = struct.unpack_from(f'>{reloc_count}I', b, HEAD + data_size)
    roots_at = HEAD + data_size + reloc_count * 4
    return ({struct.unpack_from('>I', b, HEAD + slot)[0] for slot in slots}
            | {struct.unpack_from('>I', b, roots_at + 8 * i)[0] for i in range(root_count)})


def compact(file: bytes, also=()):
    """A file of this kind without the parts nothing points to. A part runs from one pointed-to place to the next;
    it is kept when a chain of pointers reaches it from one of the file's named roots. What is kept stays in its
    order, and parts that lay side by side stay side by side; every kept byte keeps its place modulo 32 (pictures
    and display lists must sit on 32). `also`: places where parts began before an edit took their last pointer
    away (`part_starts` of the file as it was); without them such a part counts as the tail of the part before it
    and is kept. -> (the new file, the bytes dropped)"""
    import bisect
    b = bytes(file)
    _size, data_size, reloc_count, root_count, ref_count = struct.unpack_from('>5I', b, 0)
    if ref_count:
        raise ValueError('a file that points into other files is not compacted here')
    data = b[HEAD:HEAD + data_size]
    reloc_at = HEAD + data_size
    slots = sorted(struct.unpack_from(f'>{reloc_count}I', b, reloc_at))
    roots_at = reloc_at + reloc_count * 4
    roots = [struct.unpack_from('>II', b, roots_at + 8 * i) for i in range(root_count)]
    strings = b[roots_at + 8 * root_count:]
    value = {slot: struct.unpack_from('>I', data, slot)[0] for slot in slots}
    starts = sorted(set(value.values()) | {off for off, _name in roots} | {x for x in also if 0 <= x < data_size})
    if any(not 0 <= x < data_size for x in starts):
        raise ValueError('a pointer leaves the file')
    part = lambda place: bisect.bisect_right(starts, place) - 1        # noqa: E731
    inside = defaultdict(list)                                         # a part's own pointers
    for slot in slots:
        if part(slot) >= 0:
            inside[part(slot)].append(slot)
    live, todo = set(), [part(off) for off, _name in roots]
    while todo:
        k = todo.pop()
        if k in live:
            continue
        live.add(k)
        todo.extend(part(value[slot]) for slot in inside[k])
    ends = starts[1:] + [data_size]
    out, moved, last = bytearray(), {}, None
    for k in sorted(live):
        if last is None or k != last + 1:                              # a new run: back onto the same place in 32
            out.extend(bytes((starts[k] - len(out)) % 32))
        moved[k] = len(out) - starts[k]
        out.extend(data[starts[k]:ends[k]])
        last = k
    out.extend(bytes(-len(out) % 4))
    new_slots = []
    for k in sorted(live):
        for slot in inside[k]:
            struct.pack_into('>I', out, slot + moved[k], value[slot] + moved[part(value[slot])])
            new_slots.append(slot + moved[k])
    table = b''.join(struct.pack('>II', off + moved[part(off)], name) for off, name in roots)
    body = bytes(out) + struct.pack(f'>{len(new_slots)}I', *sorted(new_slots)) + table + strings
    head = struct.pack('>5I', HEAD + len(body), len(out), len(new_slots), root_count, 0) + b[20:HEAD]
    return head + body, len(b) - len(head) - len(body)


def regroup(costume: bytes, most=MOST_IN_A_GROUP, strip=MOST_IN_A_STRIP, weights=None):
    """A costume with every piece's polygon groups made again (`group`): the same triangles, the same weighting on
    every vertex, each weighting named by as few groups as can be. A strip that runs through more than `strip`
    weightings is cut first (`cut`), since a group must name every weighting of a strip it holds. The old groups
    are taken out of the file (`compact`). A piece that cannot be taken apart is left as it is and named in the
    report.
    `weights` (most joints, steps): the weightings are made simpler first (`simpler`: a vertex's heaviest joints,
    their shares in whole parts of `steps`), for a costume that was imported with the weightings it came with:
    many vertices then share one weighting, which is what the engine's cost counts. The triangles and where
    their vertices are do not change; what holds each vertex does, by at most half a step.
    -> (the new file, dict(pieces=[one row a piece], before, after))"""
    from vault.echo.subactions import Dat
    dat = Dat(bytes(costume))
    base = (dat.data_size + 0x1F) // 0x20 * 0x20
    blob, pointers, heads, rows = bytearray(), [], [], []

    def put(data, align):
        blob.extend(bytes(-len(blob) % align))
        at = len(blob)
        blob.extend(data)
        return at

    lighter = {}                                         # a simpler weighting -> where it is written
    twins = {}                                           # what a piece draws -> (its new groups, its row)
    for number, piece in enumerate(_pieces(dat)):
        try:
            got = _piece(dat, piece)
        except ValueError as why:
            rows.append(dict(piece=number, left=str(why)))
            continue
        # two pieces that draw the same thing from the same lists (a body piece and its twin in another list of
        # pieces) go on sharing: the groups are made once
        places = {place: key for key, place in got['weightings'].items()}
        twin = tuple((kind['desc'], kind['flags'], kind['form'],
                      tuple((what, tuple(verts), tuple(places[w] for w in which)) for what, verts, which in kind['items']))
                     for kind in got['kinds'])
        if twin in twins:
            first, row = twins[twin]
            heads.append((piece, first))
            rows.append(dict(row, piece=number, shares=row['piece']))
            continue
        simple = {}
        if weights:
            for key, place in got['weightings'].items():
                if len(key) == 1:
                    continue                            # held by one joint already: written in that joint's own space
                light = simpler([(joint, _share(share)) for joint, share in key], *weights)
                if light not in lighter:
                    # The engine reads a vertex whose weighting is ONE joint at full weight in that joint's own
                    # space, and a blended one in the model's (pobj.c). A blended vertex left with one joint is
                    # still written in the model's space, so its weighting stays a blend: the joint twice, half
                    # and half. (Written as one joint, the vertex flies off: spikes all over the body.)
                    shares = ([(light[0][0], 0.5), (light[0][0], 0.5)] if len(light) == 1 else
                              [(joint, parts / weights[1]) for joint, parts in light])
                    at = put(b''.join(struct.pack('>If', joint, share) for joint, share in shares) + bytes(8), 4)
                    pointers.extend(at + 8 * n for n in range(len(shares)))
                    lighter[light] = base + at
                simple[place] = lighter[light]
        made = []                                        # (weightings, list, blocks, how many, description, flags)
        for kind in got['kinds']:
            items = []
            for what, verts, which in kind['items']:
                which = [simple.get(w, w) for w in which]
                if what != 'triangle' and len(set(which)) > strip:
                    items += [(what, v, w) for v, w in cut(verts, which, strip)]
                else:
                    items.append((what, verts, which))
            _rows, _size, matrices = kind['layout']
            needs = [frozenset(which) for _what, _verts, which in items]
            sets = group(needs, most)
            home = {}
            for i, need in enumerate(needs):
                home.setdefault(next(k for k, chosen in enumerate(sets) if need <= chosen), []).append(i)
            for k in sorted(home):
                order = []                               # the group's weightings, in the order its vertices meet them
                for i in home[k]:
                    for w in items[i][2]:
                        if w not in order:
                            order.append(w)
                slot = {w: n for n, w in enumerate(order)}

                def written(v, w):
                    v = bytearray(v)
                    v[matrices[0][0]] = 3 * slot[w]
                    for o, _a in matrices[1:]:
                        v[o] = 30 + 3 * slot[w]
                    return bytes(v)

                corners = [written(v, w) for i in home[k] if items[i][0] == 'triangle'
                           for v, w in zip(items[i][1], items[i][2])]
                lists = bytearray()
                for at in range(0, len(corners), 0xFFFC):    # a primitive counts its vertices in sixteen bits
                    part = corners[at:at + 0xFFFC]
                    lists += bytes([TRIANGLES | (kind['form'] or 0)]) + struct.pack('>H', len(part)) + b''.join(part)
                for i in home[k]:
                    if items[i][0] != 'triangle':
                        lists += bytes([items[i][0]]) + struct.pack('>H', len(items[i][1]))
                        lists += b''.join(written(v, w) for v, w in zip(items[i][1], items[i][2]))
                lists += bytes(-len(lists) % 32)
                named = put(b''.join(struct.pack('>I', w) for w in order) + bytes(4), 4)
                pointers.extend(named + 4 * n for n in range(len(order)))
                made.append((named, put(lists, 32), len(lists) // 32, len(order), kind['desc'], kind['flags']))
        start = put(b'', 4)
        for n, (named, lists, blocks, _count, desc, flags) in enumerate(made):
            at = put(struct.pack('>IIIHHII', 0, base + start + 0x18 * (n + 1) if n + 1 < len(made) else 0,
                                 desc, flags, blocks, base + lists, base + named), 4)
            pointers.extend([at + 8, at + 0x10, at + 0x14] + ([at + 4] if n + 1 < len(made) else []))
        heads.append((piece, base + start))
        rows.append(dict(piece=number, weightings=len(set(simple.values())) if weights else len(got['weightings']),
                         groups=len(made), matrices=sum(m[3] for m in made)))
        twins[twin] = (base + start, rows[-1])
    before = cost(costume)
    if not heads:
        return bytes(costume), dict(pieces=rows, before=before, after=before)
    if dat.append_struct(bytes(blob), pointers, align=0x20) != base:
        raise RuntimeError('the new groups did not land where they were laid out for')
    for piece, first in heads:
        dat.set_u32(piece + 0xC, first)
    # A joint is 0x40 bytes. What lies behind one with no pointer to it is reached by nothing: a costume from the
    # app's importer has a whole chain of pieces there that the joint no longer names, each still holding the
    # old groups and lists. A part's end is made there, so that they go with the rest that nothing reaches.
    out, _dropped = compact(dat.to_bytes(), part_starts(costume) | {joint + 0x40 for joint in _joints(dat)})
    if drawn(out, weights) != drawn(costume, weights):
        raise RuntimeError('the costume does not draw the same thing with its groups made again')
    return out, dict(pieces=rows, before=before, after=cost(out))
