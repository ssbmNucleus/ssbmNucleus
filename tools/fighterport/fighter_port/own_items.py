"""The items a fighter on its own skeleton makes with its specials: each one's data in the fighter's own file.

A Melee item's data sits in the fighter's data file (`items.py`): its common numbers, numbers of its own, a list of
states (each a script of hitboxes) and a model. A donor like Marth has no items, so each is taken whole from a
fighter that has a simple one (Mario's fireball) and then made the port's own:

  model     the game's own model of the article, as it stands (`weapons.plain_model`: one joint, its own pictures),
            turned into the item's axes and drawn at the fighter's drawn scale; or a flat picture of it (`cutout`)
            where the game's model is a slab of thousands of triangles that is only ever seen from the front; or
            one picture for each pose of a thing the game shows a pose at a time (`cutouts`, `pose_meshes`)
  box       the box the stage stops it with, from the model's own size
  numbers   a block of floats the item's code reads (`set_own_attributes`), in the order the fighter's module gives
  states    one script of hitboxes for each state (`items.set_script`)

The item's behaviour is C in the port's code file (`item_<index>.c`, built into the file's itFunction root); the
fighter's module writes it.

    install(pl, specs, root, fighter, drawn, work) -> (bytes, [what was made of each])

A spec: {'name', 'model': {'folder', 'meshes' (names to keep, or None for all), 'lit'} or {'cutout': ...},
         'numbers': [floats], 'states': [[(frame, hitbox fields | None | items.DONE), ...], ...], 'box': {...} or None}
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

TEMPLATE = ('PlMr.dat', 0)          # a fighter with a simple item to take the data from: (vanilla file, item index)
BOX = 0x20                          # in an item's common numbers: its box about its own point (top, bottom, right, left)
# ... and what the stage stops it with: how far up, down, ahead and behind its own point it reaches (mpcoll.c: a
# box less than 3 tall or wide is made 3, which is why the template's own stood 1.5 over a floor)
STAGE_BOX = 0x40
MODEL_SCALE = 0x60                  # ... and the size its model is drawn at
# ... and the effects the engine plays where an item is removed (item.c ItemSwitch: when its time is up, and when a
# hit ends it). The template's are a fireball's puff of smoke; an item of the fighter's own has none (-1: what
# it shows as it goes is its own code's)
GONE_EFFECTS = (0x64, 0x68)
# The game's article axes (x to the fighter's side, y up, z the way it faces) in an item's (x the way it faces, y up,
# z toward the camera): a quarter turn about y.
TO_ITEM = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])


def game_model(root, fighter, folder, meshes=None, texture_dir=None):
    """An article's model as the game has it (`weapons.plain_model`), with only the meshes named in `meshes` (the
    start of a mesh's name) when given: a model can carry decals and other states of itself that the game shows
    and hides."""
    from . import weapons
    from .oneshot import ssbh
    S = ssbh(root)
    model = weapons.plain_model(S, root, fighter, folder, texture_dir)
    if meshes is not None:
        d = Path(root) / 'gamedata' / 'fighter' / fighter / 'model' / folder / 'c00'
        names = [o.name for o in S.mesh_data.read_mesh(str(d / 'model.numshb')).objects]
        keep = [p for n, p in zip(names, model['parts']) if any(n.startswith(m) for m in meshes)]
        if not keep:
            raise ValueError(f'{folder}: no mesh named like {meshes} (it has {names})')
        allp = np.vstack([p['positions'] for p in keep])
        model = dict(model, parts=keep, min=allp.min(0), max=allp.max(0), triangles=int(sum(len(p['triangles']) for p in keep)))
    return model


def box_of(model, turn, scale):
    """The box the stage stops an item with, from its model's own size once turned and scaled: how far its top,
    bottom and sides are from its own point."""
    corners = np.array([model['min'], model['max']]) @ (scale * np.asarray(turn, float)).T
    low, high = corners.min(0), corners.max(0)
    half = max(abs(float(low[0])), abs(float(high[0])))
    return {'top': float(high[1]), 'bottom': float(low[1]), 'right': -half, 'left': half}      # (signed as the template's are)


def slab_picture(part, picture, side=-1.0):
    """A flat picture of one mesh that the game builds as a slab of little coloured squares (a figure of an old
    game, drawn a pixel a square): the squares of the face that looks along x (`side`: -1 the face toward -x, which
    is the one the camera sees of an article that faces right), each in the colour its triangle takes from the
    mesh's own picture. -> (an RGBA image, (z of its left edge, z of its right edge, y of its foot, y of its top))"""
    from PIL import Image
    P, UV, T = np.asarray(part['positions'], float), np.asarray(part['uvs'], float), np.asarray(part['triangles'], int)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    normal = np.cross(b - a, c - a)
    area = np.linalg.norm(normal, axis=1)
    facing = (normal[:, 0] * side > 0.9 * area) & (area > 1e-9)
    if not facing.any():
        raise ValueError('the mesh has no face that looks along x')
    tri = T[facing]
    z, y = P[tri][:, :, 2], P[tri][:, :, 1]
    # One square of the figure is as wide and as tall as its triangles' edges usually are (the squares are not
    # square: Duck Hunt's gunmen are 0.3 by 0.25, and neighbours stand a hair apart, so the shortest gap between
    # two corners is no square's side).
    def usual(v):
        edges = np.abs(np.r_[v[:, 0] - v[:, 1], v[:, 1] - v[:, 2], v[:, 2] - v[:, 0]])
        sizes, counts = np.unique(np.round(edges[edges > 1e-2], 2), return_counts=True)
        return float(sizes[np.argmax(counts)])
    cell_z, cell_y = usual(z), usual(y)
    z0, z1, y0, y1 = float(z.min()), float(z.max()), float(y.min()), float(y.max())
    wide, tall = max(1, int(round((z1 - z0) / cell_z))), max(1, int(round((y1 - y0) / cell_y)))
    if wide * tall > 512 * 512:
        raise ValueError(f'the mesh is no figure of little squares ({wide} by {tall} of them)')
    src = np.asarray(Image.open(picture).convert('RGBA'))
    out = np.zeros((tall, wide, 4), np.uint8)
    centre = UV[tri].mean(axis=1) % 1.0
    colours = src[np.minimum((centre[:, 1] * src.shape[0]).astype(int), src.shape[0] - 1),
                  np.minimum((centre[:, 0] * src.shape[1]).astype(int), src.shape[1] - 1)]
    # each triangle colours the squares whose middles lie in it (a run of squares of one colour is often one
    # pair of triangles)
    u, v = (z - z0) / (z1 - z0) * wide, (y1 - y) / (y1 - y0) * tall
    for k in range(len(tri)):
        i0, i1 = max(0, int(np.floor(u[k].min()))), min(wide, int(np.ceil(u[k].max())))
        j0, j1 = max(0, int(np.floor(v[k].min()))), min(tall, int(np.ceil(v[k].max())))
        if i1 <= i0 or j1 <= j0:
            continue
        gu, gv = np.meshgrid(np.arange(i0, i1) + 0.5, np.arange(j0, j1) + 0.5)
        (ax, bx, cx), (ay, by, cy) = u[k], v[k]
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-9:
            continue
        wa = ((by - cy) * (gu - cx) + (cx - bx) * (gv - cy)) / det
        wb = ((cy - ay) * (gu - cx) + (ax - cx) * (gv - cy)) / det
        inside = (wa >= -1e-6) & (wb >= -1e-6) & (wa + wb <= 1 + 1e-6)
        block = out[j0:j1, i0:i1]
        block[inside, :3] = colours[k, :3]
        block[inside, 3] = 255
    return Image.fromarray(out).convert('RGBA'), (z0, z1, y0, y1)


def cutout(image, extent, name, out, grow=4):
    """A flat model of a picture, in the game's article axes (it stands in the plane the fighter faces along, seen
    from both sides), in the shape `weapons.plain_model` gives: for `install`. The picture is saved beside it,
    each of its squares `grow` pixels wide so that it stays sharp when the game draws it larger."""
    from PIL import Image
    z0, z1, y0, y1 = extent
    tex = Path(out) / 'tex'
    tex.mkdir(parents=True, exist_ok=True)
    image.convert('RGBA').resize((image.width * grow, image.height * grow), Image.NEAREST).save(tex / f'{name}.png')
    front = np.array([[0.0, y0, z0], [0.0, y0, z1], [0.0, y1, z1], [0.0, y1, z0]])
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]])
    P = np.vstack([front, front])
    N = np.vstack([np.tile([-1.0, 0.0, 0.0], (4, 1)), np.tile([1.0, 0.0, 0.0], (4, 1))])
    T = np.array([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6]])
    return {'parts': [{'texture': name, 'positions': P, 'normals': N, 'uvs': np.vstack([uv, uv]), 'triangles': T}],
            'min': P.min(0), 'max': P.max(0), 'root': None, 'triangles': len(T)}


# A thing the game shows in one pose at a time: its model holds a mesh for each pose, named <Figure>_A, <Figure>_B ...
# (with the game's _VIS_ tail), and its code shows one and hides the rest (VisibilityModule; Duck Hunt's gunmen stand
# facing the camera, turn to aim, and fall when struck). A clip of its own shows nothing of this: the item carries a
# picture for each pose it shows and its code shows the right one (`cutouts`, `SHOW_POSE`).
POSE = r'^(.+?)_([A-Z])(?:_VIS_.*)?$'


def pose_meshes(names):
    """The figures of a model that are drawn in poses, from its meshes' names: {figure: its poses' letters, A first}.
    A figure counts when its letters run on from A (a pair named _L and _R is a left and a right, not two poses)."""
    import re
    found = {}
    for name in names:
        m = re.match(POSE, name)
        if m:
            found.setdefault(m.group(1), set()).add(m.group(2))
    return {figure: sorted(letters) for figure, letters in found.items()
            if len(letters) > 1 and sorted(letters) == [chr(ord('A') + k) for k in range(len(letters))]}


def mesh_names(root, fighter, folder):
    """The names of an article model's meshes, in the model's order."""
    from .oneshot import ssbh
    d = Path(root) / 'gamedata' / 'fighter' / fighter / 'model' / folder / 'c00'
    return [o.name for o in ssbh(root).mesh_data.read_mesh(str(d / 'model.numshb')).objects]


PICTURE_MOST = 256      # the longest side of a picture `weapons.write_smd` keeps as it is (its max_texture)


def cutouts(pictures, out, grow=4):
    """Several flat pictures in one model (each as `cutout` makes one), a mesh each in the order given: the poses of a
    thing the game shows one at a time. Its meshes keep that order on its one joint, so the item's code shows a pose
    by its place in the list (`SHOW_POSE`). `pictures`: [(image, extent, name)], the image and extent as
    `slab_picture` gives them; each name names its own picture (two of one name would be drawn as one mesh)."""
    names = [name for _image, _extent, name in pictures]
    if len(set(names)) != len(names):
        raise ValueError(f'two poses share a picture name: {names}')
    # One size of square for every pose, the largest that keeps the biggest picture within what `weapons.write_smd`
    # keeps (it shrinks a larger one, the shrinking blurs the squares' edges, and the model tool then stores the
    # picture at two bytes a pixel in place of half a byte: Duck Hunt's tallest gunmen cost 45 to 56 KB a pose).
    side = max(max(image.size) for image, _extent, _name in pictures)
    grow = max(1, min(grow, PICTURE_MOST // side))
    parts = []
    for image, extent, name in pictures:
        parts += cutout(image, extent, name, out, grow)['parts']
    P = np.vstack([p['positions'] for p in parts])
    return {'parts': parts, 'min': P.min(0), 'max': P.max(0), 'root': None,
            'triangles': int(sum(len(p['triangles']) for p in parts))}


# In the item's C (and in the fighter's, to show only the first pose of an item just made, before its own code has
# run): show one pose of a model made by `cutouts` and hide the rest.
SHOW_POSE = '''
// Show one of its poses and hide the rest: its model holds a mesh for each pose, in the order the port drew them
// (own_items.cutouts), all on its one joint.
static void Show_Pose(GOBJ *item, int pose)
{
    DOBJ *mesh = ((JOBJ *)item->hsd_object)->dobj;
    int k;
    for (k = 0; mesh; k++, mesh = mesh->next)
    {
        if (k == pose)
            DOBJ_ClearFlags(mesh, DOBJ_HIDDEN);
        else
            DOBJ_SetFlags(mesh, DOBJ_HIDDEN);
    }
}
'''


def install(pl, specs, root, fighter, drawn, work, log=print):
    """`pl` with one item for each spec, in order (a spec's place in the list is its item number).
    -> (bytes, [what was made of each])"""
    from core.config import HSDRAW_EXE
    from shared.vanilla_extract import vanilla_refs
    from vault.echo.subactions import Dat
    from . import items, weapons
    template = Path(vanilla_refs.ensure_vanilla_ref(TEMPLATE[0])).read_bytes()
    work = Path(work)
    made = []
    for spec in specs:
        name = spec['name']
        pl, index, desc = items.add_item(pl, template, TEMPLATE[1], Dat)
        pl = items.set_own_attributes(pl, desc, [float(v) for v in spec.get('numbers') or [0.0]], Dat)
        pl = items.set_spin(pl, desc, 0.0, Dat)
        # the states after the first, then the first: each new script is made from the template's own first
        # hitbox, which the first state's script holds until it is written itself
        scripts = list(spec['states'])
        for events in scripts[1:]:
            pl, state = items.add_state(pl, desc, Dat)
            pl = items.set_script(pl, desc, state, events, Dat)
        pl = items.set_script(pl, desc, 0, scripts[0], Dat)
        look = spec['model']
        out = work / name
        turn = np.array(look.get('turn') if look.get('turn') is not None else TO_ITEM, float)
        if look.get('cutout'):
            model = look['cutout'](out)                 # (the fighter's module draws it)
        else:
            model = game_model(root, fighter, look['folder'], look.get('meshes'), out / 'tex')
        smd, missing = weapons.write_smd({name: model}, name, float(drawn) * turn, out, [out / 'tex'])
        addon, _ = weapons.build_addon(HSDRAW_EXE, smd, 0, out)
        pl = items.set_model(pl, desc, addon.read_bytes(), Dat, unlit=not look.get('lit'))
        box = spec.get('box') or box_of(model, turn, float(drawn))
        d = Dat(pl)
        common = d.ptr(desc)
        for k, side in enumerate(('top', 'bottom', 'right', 'left')):
            d.set_f32(common + BOX + 4 * k, float(box[side]))
            d.set_f32(common + STAGE_BOX + 4 * k, abs(float(box[side])))
        d.set_f32(common + MODEL_SCALE, 1.0)
        for at in GONE_EFFECTS:
            d.set_i32(common + at, -1)
        pl = d.to_bytes()
        row = {'item': index, 'name': name, 'triangles': model['triangles'], 'states': len(scripts),
               'size': np.round((model['max'] - model['min']) * float(drawn), 2).tolist(), 'box': box,
               'textures_missing': missing, 'model_bytes': addon.stat().st_size}
        made.append(row)
        log(f"item {index}: {name}: {row['triangles']} triangles, size {row['size']}, {row['states']} states, "
            f"box {[round(box[s], 2) for s in ('top', 'bottom', 'right', 'left')]}"
            + (f', textures missing {missing}' if missing else ''))
    return pl, made
