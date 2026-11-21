"""Eyes with their irises, and without a patch over them.

Ultimate draws an eye with one material that lays two pictures over each other:
the white of the eye on the mesh's first texture coordinates (map1) and the iris
on its second (uvSet), moved by the material's own transform; each eye has its
own iris picture. A model file made for other tools carries the first picture
only, so a costume built from one has blank eyes. Some fighters also lay a
see-through piece over both eyes (a lash shadow), and an import can turn that
into an opaque patch: black eyes.

This puts the eyes back in the costume's own textures:

  game_eyes    the game's eye materials and the meshes they are on
  pieces       the costume pieces that are those eyes, by the picture they are
               drawn with and the side of the head they are on
  coordinates  where a costume piece's texture coordinates sit in the game's
               (an import may crop, resize or turn a picture over; the piece's
               own shape says how)
  bake         one eye's picture: white, iris and overlay, in the costume
               texture's own layout
  cover        the costume piece that is the opaque patch, to be emptied
  blink        the costume draws an eye from the frames of its blink (open, half
               shut, shut), not from its plain texture: each frame gets the
               baked eye under the eyelid the import painted

Conventions (checked against both pictures and meshes): the game's texture
coordinates have v = 0 on a picture's top row; a costume exported by the model
tool has v = 0 on its bottom row.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

NS = '{http://www.collada.org/2005/11/COLLADASchema}'
FLAT = 4.0          # a picture whose colours differ by less than this is one flat colour
SAME = 12.0         # two flat colours this close are the same colour
LOOKS = 8.0         # mean colour difference under which a costume texture is a game picture, resized


# ------------------------------------------------------------------ the game
def game_eyes(ssbh, dump_root, fighter, folder='c00'):
    """The game's eyes: one entry per material that lays a second colour picture over a first.
    {material, white, iris, transform [scale u, scale v, move u, move v], clamp, map1, uvset,
     world (the mesh's points in the fighter's space), overlays [{texture, map1}]}
    `folder`: the costume whose model is read (a fighter with two bodies has two: c00 and c01)."""
    d = Path(dump_root) / 'gamedata' / 'fighter' / fighter / 'model' / 'body' / folder
    material = {(e.mesh_object_name, e.mesh_object_subindex): e.material_label
                for e in ssbh.modl_data.read_modl(str(d / 'model.numdlb')).entries}
    entries = {e.material_label: e for e in ssbh.matl_data.read_matl(str(d / 'model.numatb')).entries}
    skel = ssbh.skel_data.read_skel(str(d / 'model.nusktb'))
    world = {b.name: np.array(skel.calculate_world_transform(b), float) for b in skel.bones}      # row vectors
    objects = ssbh.mesh_data.read_mesh(str(d / 'model.numshb')).objects

    def pictures(e):
        return {t.param_id.name: t.data for t in e.textures}

    def coords(o):
        return {t.name: np.array(t.data, float)[:, :2] for t in o.texture_coordinates}

    eyes = []
    for label, e in entries.items():
        tex = pictures(e)
        if 'Texture0' not in tex or 'Texture1' not in tex:
            continue
        meshes = [o for o in objects if material.get((o.name, o.subindex)) == label and 'uvSet' in coords(o)]
        if not meshes:
            continue
        o = min(meshes, key=lambda o: len(o.name))      # the eye at rest has the plain name; the rest are expressions
        uv = coords(o)
        P = np.array(o.positions[0].data, float)[:, :3]
        if o.parent_bone_name in world and not o.bone_influences:
            P = (np.c_[P, np.ones(len(P))] @ world[o.parent_bone_name])[:, :3]
        move = next(([float(x) for x in v.data] for v in e.vectors if v.param_id.name == 'CustomVector31'), [1.0, 1.0, 0.0, 0.0])
        clamp = next(('Clamp' in str(s.data.wraps) for s in e.samplers if s.param_id.name == 'Sampler1'), False)
        overlays = []
        for other in objects:                            # a see-through piece of the same mesh, lying on the eye
            oe = entries.get(material.get((other.name, other.subindex)))
            if other.name != o.name or oe is None or oe is e or 'Texture1' in pictures(oe) or 'Texture0' not in pictures(oe):
                continue
            through = bool(oe.blend_states) and 'Zero' not in str(oe.blend_states[0].data.destination_color)
            m1 = coords(other).get('map1')
            if through and m1 is not None and np.abs(m1.min(0) - uv['map1'].min(0)).max() < 0.05 \
                    and np.abs(m1.max(0) - uv['map1'].max(0)).max() < 0.05:
                overlays.append({'texture': pictures(oe)['Texture0'], 'map1': m1})
        eyes.append({'material': label, 'white': tex['Texture0'], 'iris': tex['Texture1'], 'transform': move,
                     'clamp': clamp, 'map1': uv['map1'], 'uvset': uv['uvSet'], 'world': P, 'overlays': overlays})
    return eyes


def lid_colour(root, info, textures, eye_pieces):
    """The colour of the face's skin, for an eyelid. The face is the costume piece whose surface lies
    closest around the eye pieces; its skin is the median colour of its picture at its own corners,
    leaving out the dark ones (a face picture is painted dark in the sockets the eyes sit in, which is
    why a lid colour taken from right beside the eye comes out black). -> ((r, g, b), piece) or (None, None)
    (The game's own blink mesh is no help either: it is drawn with the lashes' picture.)"""
    single = [p for p in eye_pieces if not p.get('both')]
    lo = np.min([p['points'].min(0) for p in single], axis=0)
    hi = np.max([p['points'].max(0) for p in single], axis=0)
    size = hi - lo
    lo, hi = lo - [0.3 * size[0], 1.0 * size[1], 0], hi + [0.3 * size[0], 1.0 * size[1], 0]
    depth, best = float(np.mean([p['points'][:, 2].mean() for p in single])), None
    for row in info:
        if not row.get('verts') or row['dobj'] in {p['dobj'] for p in eye_pieces} or not row.get('textures'):
            continue
        image = textures.get(row['textures'][0])
        if image is None or _flat(image)[0] or np.asarray(image.convert('RGBA'))[..., 3].min() < 255:
            continue                                    # a flat or see-through picture is not a face
        got = piece(root, row['dobj'])
        if got is None:
            continue
        points, uv = got
        near = np.all((points[:, :2] >= lo[:2]) & (points[:, :2] <= hi[:2]), axis=1) & (np.abs(points[:, 2] - depth) < 2 * size[0])
        if near.sum() < 6:
            continue
        gap = float(np.abs(points[near, 2] - depth).mean())
        if best is None or gap < best[0]:
            colours = sample(np.asarray(image.convert('RGBA'), float), uv[:, 0], 1.0 - uv[:, 1])[:, :3]
            light = colours[colours.max(1) > 90]
            if len(light):
                best = (gap, tuple(float(v) for v in np.median(light, axis=0)), row['dobj'])
    return (best[1], best[2]) if best else (None, None)


def pictures(dump_root, fighter, names, folder='c00'):
    """{name: RGBA image} of the game's own textures for a costume (the first, unless told), taken out of
    the game's archive when not yet on disk (the archive's paths are lower case)."""
    from echo_ultimate import nutexb
    from echo_ultimate.gamedata import arc
    root = Path(dump_root)
    d = root / 'gamedata' / 'fighter' / fighter / 'model' / 'body' / folder
    missing = [f'fighter/{fighter}/model/body/{folder}/{n.lower()}.nutexb' for n in set(names)
               if not (d / f'{n}.nutexb').exists() and not (d / f'{n.lower()}.nutexb').exists()]
    if missing:
        arc.extract(root, root / 'gamedata', missing)
    return {n: nutexb.read(d / f'{n}.nutexb' if (d / f'{n}.nutexb').exists() else d / f'{n.lower()}.nutexb')[0].convert('RGBA')
            for n in set(names)}


# --------------------------------------------------------------- the costume
def piece(dae_root, n):
    """One costume piece from the model tool's export: (points, texture coordinates), one row per triangle corner."""
    g = next((g for g in dae_root.iter(NS + 'geometry') if re.fullmatch(rf'Joint_\d+_Object_{n}-geometry', g.get('id') or '')), None)
    if g is None:
        return None
    src = {}
    for s in g.iter(NS + 'source'):
        arr, acc = s.find(NS + 'float_array'), s.find(f'{NS}technique_common/{NS}accessor')
        if arr is not None and acc is not None and arr.text:
            src[s.get('id')] = np.array(arr.text.split(), float).reshape(-1, int(acc.get('stride')))
    mesh = g.find(NS + 'mesh')
    tri = mesh.find(NS + 'triangles') if mesh is not None else None
    if tri is None or tri.find(NS + 'p') is None or not tri.find(NS + 'p').text:
        return None
    inputs = {i.get('semantic'): (int(i.get('offset')), i.get('source').lstrip('#')) for i in tri.iter(NS + 'input')}
    verts = {i.get('semantic'): i.get('source').lstrip('#') for i in mesh.find(NS + 'vertices').iter(NS + 'input')}
    if 'VERTEX' not in inputs or 'TEXCOORD' not in inputs:
        return None
    p = np.array(tri.find(NS + 'p').text.split(), int).reshape(-1, max(o for o, _ in inputs.values()) + 1)
    return src[verts['POSITION']][p[:, inputs['VERTEX'][0]]], src[inputs['TEXCOORD'][1]][p[:, inputs['TEXCOORD'][0]]]


def _flat(image):
    a = np.asarray(image.convert('RGB'), float).reshape(-1, 3)
    return (a.max(0) - a.min(0)).max() < FLAT, a.mean(0)


def looks_like(image, source):
    """Is a costume texture this game picture (resized, maybe out of shape)? A flat picture is, when both are the same flat colour."""
    from PIL import Image
    mine_flat, mine = _flat(image)
    src_flat, src = _flat(source)
    if mine_flat or src_flat:
        return bool(mine_flat and src_flat and np.abs(mine - src).max() < SAME)
    a = np.asarray(image.convert('RGB'), float)
    b = np.asarray(source.convert('RGB').resize(image.size, Image.LANCZOS), float)
    return float(np.abs(a - b).mean()) <= LOOKS


def pieces(dae_path, info, textures, eyes, images):
    """The costume pieces that are the game's eyes. `info`: the model tool's list of pieces
    ({dobj, verts, bones, textures}); `textures` {index: image} the costume's own pictures.
    -> [{dobj, texture, points, uv, eye}], each paired with the game eye on its side of the head. A piece
    that is both eyes at once (a far-away copy of the model) has `both` set and takes one eye's picture."""
    root = ET.parse(dae_path).getroot()
    whites = {e['white'] for e in eyes}
    found = []
    for row in info:
        if not row.get('verts') or len(row.get('bones') or []) != 1 or not row.get('textures'):
            continue
        index = row['textures'][0]
        if index not in textures or not any(looks_like(textures[index], images[w]) for w in whites):
            continue
        got = piece(root, row['dobj'])
        if got is not None:
            found.append({'dobj': row['dobj'], 'texture': index, 'points': got[0], 'uv': got[1], 'bone': row['bones'][0]})
    # a costume may also hold a far-away copy of the model whose two eyes are one piece with one picture
    narrow = min(np.ptp(p['points'][:, 0]) for p in found) if found else 0.0
    single = [p for p in found if np.ptp(p['points'][:, 0]) <= 1.6 * narrow]
    if len(single) != len(eyes):
        raise ValueError(f"{len(single)} costume pieces are one eye each (of {len(found)} drawn with an eye's white "
                         f"picture); the game has {len(eyes)} eyes")
    by_side = sorted(eyes, key=lambda e: e['world'][:, 0].mean())
    for p, e in zip(sorted(single, key=lambda p: p['points'][:, 0].mean()), by_side):
        p['eye'] = e
    middle = float(np.mean([p['points'][:, 0].mean() for p in single]))
    for p in found:
        if 'eye' not in p:
            # both eyes share its one picture: it gets the eye on the far side's, from the corners on that side
            p['eye'], p['both'] = by_side[-1], True
            keep = p['points'][:, 0] > middle
            p['points'], p['uv'] = p['points'][keep], p['uv'][keep]
    return found, root


def cover(root, info, textures, eye_pieces):
    """Costume pieces that lie over the eyes as one flat opaque colour: what an import makes of the
    game's see-through overlay. -> their numbers."""
    low = np.min([p['points'][:, :2].min(0) for p in eye_pieces], axis=0)
    high = np.max([p['points'][:, :2].max(0) for p in eye_pieces], axis=0)
    size = high - low
    out = []
    for row in info:
        if not row.get('verts') or row['dobj'] in {p['dobj'] for p in eye_pieces} or not row.get('textures'):
            continue
        if row.get('bones') != [eye_pieces[0]['bone']] or row['textures'][0] not in textures:
            continue
        image = textures[row['textures'][0]]
        flat, _ = _flat(image)
        opaque = np.asarray(image.convert('RGBA'))[..., 3].min() == 255
        got = piece(root, row['dobj'])
        if not flat or not opaque or got is None:
            continue
        lo, hi = got[0][:, :2].min(0), got[0][:, :2].max(0)
        if np.all(np.abs(lo - low) < 0.2 * size) and np.all(np.abs(hi - high) < 0.2 * size):
            out.append(row['dobj'])
    return out


# ------------------------------------------------------------------ the bake
def affine(src, dst, wraps=False):
    """M (3x2) with dst = [src, 1] @ M as nearly as it goes, and how far off the worst point is.
    `wraps`: dst are texture coordinates of a picture that repeats, so a point may be stored a whole
    picture away from where its neighbours are (-0.02 kept as 0.98); such points are put back."""
    A = np.c_[src, np.ones(len(src))]
    dst = np.array(dst, float)
    M, *_ = np.linalg.lstsq(A, dst, rcond=None)
    if wraps:
        # points in the middle of the patch are not the ones stored a picture away: start from them
        lo, hi = np.quantile(src, 0.2, axis=0), np.quantile(src, 0.8, axis=0)
        inner = np.all((src >= lo) & (src <= hi), axis=1)
        if inner.sum() >= 4 and np.linalg.matrix_rank(A[inner]) == 3:
            M, *_ = np.linalg.lstsq(A[inner], dst[inner], rcond=None)
    for _ in range(4 if wraps else 0):
        turns = np.round(dst - A @ M)
        dst = dst - turns
        M, *_ = np.linalg.lstsq(A, dst, rcond=None)     # over every point, each where its neighbours are
        if not turns.any():
            break
    return M, float(np.abs(A @ M - dst).max())


def _unit(points):
    """Points as fractions of their own box across (x) and up (y): the same for an eye whatever its size or place."""
    xy = points[:, :2]
    lo, size = xy.min(0), np.maximum(np.ptp(xy, axis=0), 1e-9)
    return (xy - lo) / size


def coordinates(costume_piece):
    """M (3x2): the game's map1 for a costume texture coordinate of this piece. Both the game's eye and the
    costume's piece are the same patch of face, so a place in the patch (a fraction across and up) has a
    texture coordinate in each; the two are tied through it. -> (M, how far off the fits are)"""
    eye = costume_piece['eye']
    to_game, off_g = affine(_unit(eye['world']), eye['map1'], wraps=True)
    to_mine, off_c = affine(_unit(costume_piece['points']), costume_piece['uv'], wraps=True)
    grid = np.array([[x, y] for x in (0.0, 0.5, 1.0) for y in (0.0, 0.5, 1.0)])
    mine, game = np.c_[grid, np.ones(9)] @ to_mine, np.c_[grid, np.ones(9)] @ to_game
    M, off = affine(mine, game)
    return M, max(off, off_g, off_c)


def sample(image, u, v, clamp=False):
    """Colours of a picture (H x W x 4 floats) at texture coordinates (v = 0 on its top row), smoothed between texels."""
    h, w = image.shape[:2]
    x, y = u * w - 0.5, v * h - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]

    def at(ix, iy):
        if clamp:
            return image[np.clip(iy, 0, h - 1), np.clip(ix, 0, w - 1)]
        return image[iy % h, ix % w]

    return (at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx) * (1 - fy) + (at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx) * fy


def bake(costume_piece, images, size, over=4):
    """One eye's picture in the costume texture's own layout: the white, the iris over it where the iris
    picture is not see-through, then any overlay. `size` (w, h) of the costume texture. -> RGBA image"""
    from PIL import Image
    eye = costume_piece['eye']
    to_map1, _ = coordinates(costume_piece)
    second, _ = affine(eye['map1'], eye['uvset'])                 # where the iris layer's coordinates are, for a map1
    w, h = size[0] * over, size[1] * over
    u, v = np.meshgrid((np.arange(w) + 0.5) / w, 1.0 - (np.arange(h) + 0.5) / h)       # the costume's v runs up the picture
    mine = np.stack([u, v, np.ones_like(u)], -1)
    m1 = mine @ to_map1
    px = lambda name: np.asarray(images[name], float)
    out = sample(px(eye['white']), m1[..., 0], m1[..., 1])[..., :3]
    s = np.concatenate([m1, np.ones_like(u)[..., None]], -1) @ second
    su, sv, mu, mv = eye['transform']
    iris = sample(px(eye['iris']), (s[..., 0] - mu) * su, (s[..., 1] + mv) * sv, eye['clamp'])
    a = iris[..., 3:4] / 255.0
    out = out * (1 - a) + iris[..., :3] * a
    for o in eye['overlays']:                           # it shares the eye's own coordinates
        layer = sample(px(o['texture']), m1[..., 0], m1[..., 1])
        a = layer[..., 3:4] / 255.0
        out = out * (1 - a) + layer[..., :3] * a
    image = Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), 'RGB').resize(size, Image.LANCZOS)
    return image.convert('RGBA')


# ---------------------------------------------------------------- the file
def piece_offsets(d, root):
    """Where each piece (DObj) sits in a costume file, in the model tool's order."""
    out, stack = [], [root]
    while stack:
        j = stack.pop()
        flags = d.u32(j + 4)
        dobj = d.ptr(j + 0x10) if not flags & ((1 << 14) | (1 << 5)) else None
        while dobj is not None:
            out.append(dobj)
            dobj = d.ptr(dobj + 4)
        for o in (0xC, 8):
            if d.ptr(j + o) is not None:
                stack.append(d.ptr(j + o))
    return out


def picture_size(d, dobj):
    """(w, h) of the picture a piece is drawn with, or None."""
    mobj = d.ptr(dobj + 8)
    tobj = d.ptr(mobj + 8) if mobj is not None else None
    image = d.ptr(tobj + 0x4C) if tobj is not None else None
    return (d.u32(image + 4) >> 16, d.u32(image + 4) & 0xFFFF) if image is not None else None


def empty(costume: bytes, node: str, numbers, Dat) -> bytes:
    """`costume` with the pieces `numbers` drawing nothing (the piece stays in its place in the list, so
    every other piece keeps its number)."""
    d = Dat(costume)
    root = next(off for name, off in d.roots if name == node)
    offsets, gone = piece_offsets(d, root), set()
    for n in numbers:
        if d.ptr(offsets[n] + 0xC) is not None:
            d.set_u32(offsets[n] + 0xC, 0)
            gone.add(offsets[n] + 0xC)
    if gone:
        d._rebuild(bytes(d.buf[0x20:0x20 + d.data_size]), d.relocs - gone)
    return d.to_bytes()


def wrap(costume: bytes, node: str, modes, Dat) -> bytes:
    """`costume` with the pictures of the pieces in `modes` ({piece number: (across, down)}) repeated, clamped or
    mirrored as told (0 clamp, 1 repeat, 2 mirror: the console's own numbers, the same in every game on it).
    A game that draws an eye as layers lays the iris over the white once, clamped; a model file made for other
    tools does not say so, and an import that repeats it draws a grid of irises."""
    d = Dat(costume)
    root = next(off for name, off in d.roots if name == node)
    offsets = piece_offsets(d, root)
    for n, (across, down) in modes.items():
        mobj = d.ptr(offsets[n] + 8)
        tobj = d.ptr(mobj + 8) if mobj is not None else None
        if tobj is not None:
            d.set_u32(tobj + 0x34, int(across))
            d.set_u32(tobj + 0x38, int(down))
    return d.to_bytes()


# ------------------------------------------------------------ the blink frames
LID = 24.0          # a blink frame differs from the open one by more than this where the import painted an eyelid


def _paletted(image, count):
    """An RGB picture as at most `count` colours: (H x W indices, [(r, g, b)])."""
    from PIL import Image
    q = image.convert('RGB').quantize(colors=min(count, 256), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    flat = q.getpalette() or []
    colours = [tuple(flat[i:i + 3]) for i in range(0, min(len(flat), count * 3), 3)]
    return np.asarray(q, np.uint8), colours


def _index_bytes(indices):
    """A picture of palette indices in the console's order: tiles 8 across and 4 down, row by row."""
    h, w = indices.shape
    if w % 8 or h % 4:
        raise ValueError(f'a paletted picture of {w}x{h} is not whole tiles')
    return indices.reshape(h // 4, 4, w // 8, 8).transpose(0, 2, 1, 3).tobytes()


def _palette_bytes(colours, fmt, count):
    """A palette in the console's 16-bit colours (format 1: 5-6-5; 2: 5-5-5 with the opaque bit), `count` entries."""
    import struct
    out = bytearray(count * 2)
    for i, (r, g, b) in enumerate(colours[:count]):
        if fmt == 1:
            v = ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
        elif fmt == 2:
            v = 0x8000 | ((r * 31 + 127) // 255) << 10 | ((g * 31 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
        else:
            raise ValueError(f'palette format {fmt} is not a colour one')
        struct.pack_into('>H', out, i * 2, v)
    return bytes(out)


def blink(costume: bytes, baked: dict, info, DatFile, decode_image, work: Path, lid=None) -> tuple[bytes, dict]:
    """`costume` with each eye's blink frames redrawn over its baked picture. `baked` {piece number: RGBA image};
    `info` the model tool's piece list (for which joint a piece hangs on); `DatFile` / `decode_image` the app's
    reader of a costume's texture animations (shared.rendering.datprobe). A frame keeps what the import painted
    over the open eye (an eyelid) and takes the baked eye everywhere else. `lid` (r, g, b): the eyelid's
    colour; what the import painted keeps its light and dark but takes this colour (an import can only
    guess a lid's colour from the pictures it was given). -> (bytes, {piece: frames redrawn})"""
    from PIL import Image
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'blink-in.dat'
    path.write_bytes(costume)
    f = DatFile(path)
    root = next((o for n, o in f.roots if n.endswith('_matanim_joint')), None)
    if root is None:
        return costume, {}
    owner = {row['dobj']: row['owner'] for row in info}
    first = {}
    for row in info:
        first.setdefault(row['owner'], row['dobj'])
    out, done, header = bytearray(costume), {}, 0x20
    for t in f.matanim_texanims(root):
        number = next((n for n in baked if owner.get(n) == t.joint_index and n - first[owner[n]] == t.matanim_index), None)
        if number is None or not t.images:
            continue
        if any(i.format != 9 for i in t.images) or len(t.tluts) != len(t.images):
            raise ValueError(f'piece {number}: blink frames in a form this does not write (formats {[i.format for i in t.images]})')

        def colours(k):
            rows = decode_image(t.images[k], t.tluts[k])
            return np.array(rows, float)[..., :3]

        open_eye = colours(0)
        for k, (img, tlut) in enumerate(zip(t.images, t.tluts)):
            new = np.asarray(baked[number].convert('RGB').resize((img.width, img.height), Image.LANCZOS), float)
            if k:
                old = colours(k)
                painted = np.abs(old - open_eye).max(-1) > LID
                if lid is not None and painted.any():
                    light = old.mean(-1, keepdims=True)
                    old = np.clip(np.array(lid, float) * (light / max(float(np.median(light[painted])), 1.0)), 0, 255)
                new = np.where(painted[..., None], old, new)
            indices, palette = _paletted(Image.fromarray(np.clip(new + 0.5, 0, 255).astype(np.uint8), 'RGB'), tlut.count)
            data = _index_bytes(indices)
            out[header + img.data_offset:header + img.data_offset + len(data)] = data
            table = _palette_bytes(palette, tlut.format, tlut.count)
            out[header + tlut.data_offset:header + tlut.data_offset + len(table)] = table
        done[number] = len(t.images)
    return bytes(out), done


def frames(costume: bytes, pictures: dict, DatFile, decode_image, work: Path) -> tuple[bytes, dict]:
    """`costume` with pictures laid over its eyes' blink frames: `pictures` {frame number: RGBA image the size of a
    frame, see-through where the open eye (the costume's first frame) still shows}. For an import that made the eyes
    blink but had no lid to draw: the lids come from somewhere else (the source game's own blinking faces).
    -> (bytes, {piece: [frames redrawn]})"""
    from PIL import Image
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'frames-in.dat'
    path.write_bytes(costume)
    f = DatFile(path)
    root = next((o for n, o in f.roots if n.endswith('_matanim_joint')), None)
    if root is None:
        return costume, {}
    out, done, header = bytearray(costume), {}, 0x20
    for t in f.matanim_texanims(root):
        if not t.images or any(i.format != 9 for i in t.images) or len(t.tluts) != len(t.images):
            continue
        opened = Image.fromarray(np.array(decode_image(t.images[0], t.tluts[0]), np.uint8), 'RGBA').convert('RGB')
        for k, lid in sorted(pictures.items()):
            if k >= len(t.images):
                continue
            img, tlut = t.images[k], t.tluts[k]
            new = opened.resize((img.width, img.height), Image.LANCZOS).convert('RGBA')
            new.alpha_composite(lid.convert('RGBA').resize((img.width, img.height), Image.LANCZOS))
            indices, palette = _paletted(new.convert('RGB'), tlut.count)
            data = _index_bytes(indices)
            out[header + img.data_offset:header + img.data_offset + len(data)] = data
            table = _palette_bytes(palette, tlut.format, tlut.count)
            out[header + tlut.data_offset:header + tlut.data_offset + len(table)] = table
            done.setdefault(f'{t.joint_index}.{t.matanim_index}', []).append(k)
    return bytes(out), done
