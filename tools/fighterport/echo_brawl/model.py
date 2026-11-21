"""A ripped Brawl model made ready for the model importer, from what the disc itself says about it.

A rip of a Brawl fighter is its model with everything in it at once, and two things about that are wrong for
anything that draws it as it stands:

  States. The model draws each of its objects under a bone that says whether it is shown (a face for blinking, one
  half shut, one in pain, one talking, lie on top of the resting face). Which are shown is not in the model: a
  clip's visibility animation shows and hides bones a frame at a time, and the fighter's own table of switches
  shows one group of bones of each switch. `parts` reads which bone each object is drawn under and whether that bone
  is shown at rest (the first frame of the standing clip; a switch's group for rest); `hidden` names the rip's
  meshes to take out.

  Layers. One material may draw several pictures over each other, each on its own texture coordinates and each
  clamped, repeated or mirrored its own way (an eye: its white, the iris, a highlight). A rip gives a layer a material
  of its own (`EyeL_-_FitIkeEyeIris_png`) and loses how it wraps, so a tool that repeats every picture draws a grid of
  irises. `layered` names the layers as the importer knows eyes by (EyeL the bottom one, EyeL1 and EyeL2 over it:
  rigswap.core.eyes lays surfaces that lie on an eye face for face over it, and makes the eye blink), puts them in
  that order, and draws each upper layer's picture out over the whole stretch its coordinates cover, wrapped as the
  game wraps it, so that it reads the same however it is repeated.

`prepare` does both to a COLLADA file and its pictures.
"""
from __future__ import annotations

import math
import re
import struct
from pathlib import Path

from . import arc, brres

VISIBLE = 0x100                     # a bone's flag: what is drawn under it is shown
FILL = 1024                         # the most pixels across a picture drawn out over its coordinates


def parts(root, fighter):
    """What the fighter's first costume says about its model: {'objects': [name by number], 'draws': [(material,
    object, bone, shown at rest)], 'layers': {material: [(texture, wrap across, wrap down), ...] in the game's order}}."""
    from .textures import costume_files
    files = costume_files(root, fighter)
    data = next(f['data'] for f in arc.read(files[min(files)].read_bytes())[1]
                if f['data'][:4] == b'bres' and '3DModels(NW4R)' in brres.folders(f['data']))
    mdl = next(iter(brres.folders(data)['3DModels(NW4R)'].values()))
    sections = struct.unpack_from('>11i', data, mdl + 0x10)
    off = resting(root, fighter)
    bones = {}
    for name, at in brres._group(data, mdl + sections[1]):
        index, _node, flags = struct.unpack_from('>iiI', data, at + 0x0C)
        bones[index] = (name, bool(flags & VISIBLE) and index not in off and name not in off)
    materials, layers = [], {}
    for name, at in brres._group(data, mdl + sections[6]):
        index = struct.unpack_from('>i', data, at + 0x0C)[0]
        count, first = struct.unpack_from('>ii', data, at + 0x2C)
        refs = []
        for i in range(count):
            ref = at + first + i * 0x34
            refs.append((brres._text(data, ref + struct.unpack_from('>i', data, ref)[0]), *struct.unpack_from('>II', data, ref + 0x18)))
        materials.append((index, name))
        layers[name] = refs
    materials = [n for _i, n in sorted(materials)]
    group = brres._group(data, mdl + sections[8])
    numbered = sorted((struct.unpack_from('>i', data, at + 0x3C)[0], name) for name, at in group)
    # (an object's own number; where a file does not hold it there, the group's own order is the numbers')
    objects = [n for _i, n in numbered] if [i for i, _n in numbered] == list(range(len(group))) else [name for name, _at in group]
    draws = []
    for name, at in brres._group(data, mdl + sections[0]):
        if not name.startswith('Draw'):
            continue
        p = at
        while data[p] != 1:
            code = data[p]
            if code == 4:                               # draw: material, object, the bone it is shown under, order
                material, obj, bone = struct.unpack_from('>HHH', data, p + 1)
                draws.append((materials[material], objects[obj], *bones[bone]))
                p += 8
            elif code in (2, 5, 6):
                p += 5
            elif code == 3:
                p += 4 + data[p + 3] * 6
            else:
                p += 1
    return {'objects': objects, 'draws': draws, 'layers': layers}


REST = 'Wait1'                      # the clip a fighter stands in


def resting(root, fighter):
    """The bones (names, and numbers from the fighter's switches) under which nothing is drawn while the fighter stands
    at rest: hidden on the first frame of the standing clip, or in a switch's other groups and not in its group for
    rest."""
    from .gamedata import read_moveset
    from .transcode import motion_file
    out = set()
    data, _clips = motion_file(root, fighter)
    at = brres.folders(data).get('AnmVis(NW4R)', {}).get(REST)
    if at is not None:
        out |= {name for name, shown in brres.visibility(data, at)[1].items() if shown and not shown[0]}
    switches, rest = read_moveset(root, fighter).switches()
    for number, groups in enumerate(switches):
        shown = set(groups[rest[number]]) if number in rest and rest[number] < len(groups) else set()
        out |= {b for group in groups for b in group} - shown
    return out


def hidden(model, meshes):
    """The rip's meshes (`meshes`: their names, the model's own object names) that the game does not draw at rest.
    A state that is another form of a shown one (the same materials in the same order: a blinking face for the resting
    face) is often ripped only in part, one copy kept of what the forms share: a hidden object stays where the shown
    form's object in the same place is not in the rip. -> names to take out, sorted."""
    states = {}
    for material, obj, bone, shown in model['draws']:
        states.setdefault((bone, shown), []).append((obj, material))
    resting = [objs for (bone, shown), objs in states.items() if shown]
    out = set()
    for (bone, shown), objs in states.items():
        if shown:
            continue
        twin = next((r for r in resting if [m for _o, m in r] == [m for _o, m in objs] and r != objs), None)
        for k, (obj, _material) in enumerate(objs):
            if obj in meshes and (twin is None or twin[k][0] in meshes):
                out.add(obj)
    return sorted(out)


def _take_out(dae, name):
    """The COLLADA text without mesh `name`: the node that shows it, its skin, its geometry."""
    node = re.compile(r'[ \t]*<node id="%s" name="%s" type="NODE">.*?</node>\s*\n' % (re.escape(name), re.escape(name)), re.S)
    found = node.findall(dae)
    if len(found) != 1 or found[0].count('<node ') != 1:
        raise ValueError(f'{name}: not one plain node in the file')
    url = re.search(r'url="#([^"]+)"', found[0]).group(1)
    dae = node.sub('', dae, count=1)
    dae = re.sub(r'[ \t]*<controller id="%s"[^>]*>.*?</controller>\s*\n' % re.escape(url), '', dae, count=1, flags=re.S)
    return re.sub(r'[ \t]*<geometry id="%s-mesh"[^>]*>.*?</geometry>\s*\n' % re.escape(name), '', dae, count=1, flags=re.S)


def spread(picture, low, high, wrap):
    """`picture` drawn out over the stretch of texture coordinates from `low` to `high` ((u, v) each, whole numbers),
    wrapped as the game wraps it (`wrap`: across, down; 0 clamp, 1 repeat, 2 mirror). v runs up the picture."""
    import numpy as np
    from PIL import Image
    a = np.asarray(picture.convert('RGBA'))
    h, w = a.shape[:2]
    across, down = high[0] - low[0], high[1] - low[1]
    scale = min(1.0, FILL / max(across * w, down * h))
    W, H = max(1, round(across * w * scale)), max(1, round(down * h * scale))
    u = low[0] + (np.arange(W) + 0.5) / W * across
    v = high[1] - (np.arange(H) + 0.5) / H * down

    def place(t, size, how):
        if how == 1:
            t = t % 1.0
        elif how == 2:
            t = t % 2.0
            t = np.where(t > 1.0, 2.0 - t, t)
        return np.clip(np.floor(t * size), 0, size - 1).astype(int)

    x, y = place(u, w, wrap[0]), place(1.0 - v, h, wrap[1])
    return Image.fromarray(a[y][:, x], 'RGBA')


def layered(dae, pictures, layers):
    """The COLLADA text with each layered material's surfaces named, ordered and drawn as the module's docstring says.
    `pictures`: {file name: image} beside the file; `layers`: `parts`' own. -> (text, {new file name: image}, notes)"""
    new, notes = {}, []
    for material, refs in sorted(layers.items()):
        if len(refs) < 2:
            continue
        order = list(reversed(refs))                    # the last picture a material names is the one underneath
        names = {f'{material}_-_{tex}_png': (k, tex, (wu, wv)) for k, (tex, wu, wv) in enumerate(order)}
        if not all(f'<material id="{n}-material"' in dae for n in names):
            continue                                    # (not ripped as a material a layer)
        for old, (k, tex, wrap) in names.items():
            name = material if k == 0 else f'{material}{k}'
            dae = dae.replace(f'<material id="{old}-material" name="{old}">', f'<material id="{old}-material" name="{name}">')
            if k == 0:
                continue
            # this layer's corners in every mesh that draws it, and the stretch of coordinates they cover
            used = []
            for geo in re.finditer(r'<geometry id="([^"]+)"[^>]*>.*?</geometry>', dae, re.S):
                for group in re.finditer(r'<polylist material="%s-material" count="\d+">(.*?)</polylist>' % re.escape(old), geo.group(0), re.S):
                    inputs = re.findall(r'<input semantic="(\w+)" source="#([^"]+)" offset="(\d+)"', group.group(1))
                    stride = 1 + max(int(o) for _s, _src, o in inputs)
                    semantic, source, offset = next(i for i in inputs if i[0] == 'TEXCOORD')
                    p = [int(v) for v in re.search(r'<p>([^<]*)</p>', group.group(1)).group(1).split()]
                    used.append((source, sorted(set(p[int(offset)::stride]))))
            if not used:
                continue
            arrays = {}
            for source, _indices in used:
                m = re.search(r'(<float_array id="%s-array" count="\d+">)([^<]*)(</float_array>)' % re.escape(source), dae)
                arrays[source] = (m, [float(v) for v in m.group(2).split()])
            points = [(arrays[s][1][2 * i], arrays[s][1][2 * i + 1]) for s, idx in used for i in idx]
            low = (math.floor(min(u for u, _ in points) + 1e-6), math.floor(min(v for _, v in points) + 1e-6))
            high = (math.ceil(max(u for u, _ in points) - 1e-6), math.ceil(max(v for _, v in points) - 1e-6))
            high = (max(high[0], low[0] + 1), max(high[1], low[1] + 1))
            if (low, high) == ((0, 0), (1, 1)):
                notes.append(f'{name}: {tex} lies within its own picture, left as it is')
                continue
            file = f'{tex}_{name}.png'
            new[file] = spread(pictures[f'{tex}.png'], low, high, wrap)
            for source, indices in used:
                m, values = arrays[source]
                for i in indices:
                    values[2 * i] = (values[2 * i] - low[0]) / (high[0] - low[0])
                    values[2 * i + 1] = (values[2 * i + 1] - low[1]) / (high[1] - low[1])
                dae = dae.replace(m.group(0), m.group(1) + ' '.join(f'{v:.6g}' for v in values) + m.group(3), 1)
                arrays[source] = (re.search(r'(<float_array id="%s-array" count="\d+">)([^<]*)(</float_array>)' % re.escape(source), dae), values)
            # the layer's own picture: a new image, named by the material's effect
            image = f'{tex}_{name}_png'
            dae = dae.replace('</library_images>', f'    <image id="{image}" name="{image}">\n      <init_from>{file}</init_from>\n'
                                                   f'    </image>\n  </library_images>', 1)
            effect = re.search(r'<effect id="%s-effect">.*?</effect>' % re.escape(old), dae, re.S)
            dae = dae.replace(effect.group(0), effect.group(0).replace(f'<init_from>{tex}_png</init_from>', f'<init_from>{image}</init_from>'), 1)
            notes.append(f'{name}: {tex} drawn out over {low} to {high} of its coordinates, '
                         f"{('clamped', 'repeated', 'mirrored')[min(wrap[0], 2)]} across and {('clamped', 'repeated', 'mirrored')[min(wrap[1], 2)]} down")
    # the surfaces in order, for every layered material together: the bottom layers of every side first, then each
    # layer over them (EyeL, EyeR, EyeL1, EyeR1, ...)
    def key(symbol):
        name = re.search(r'<material id="%s" name="([^"]+)"' % re.escape(symbol), dae)
        m = re.fullmatch(r'(.*?)(\d?)', name.group(1)) if name else None
        base = m.group(1) if m else symbol
        return (0, int(m.group(2) or 0), base) if base in layers and len(layers[base]) > 1 else (1, 0, symbol)

    def reorder(block, pattern, symbol_of):
        items = re.findall(pattern, block, re.S)
        if len(items) < 2 or not any(key(symbol_of(i))[0] == 0 for i in items):
            return block
        first = block.index(items[0])
        last = block.index(items[-1]) + len(items[-1])
        ordered = sorted(items, key=lambda i: key(symbol_of(i)))
        return block[:first] + ''.join(ordered) + block[last:]

    symbol = lambda item: re.search(r'(?:material|symbol)="([^"]+)"', item).group(1)
    for geo in re.findall(r'<geometry id="[^"]+"[^>]*>.*?</geometry>', dae, re.S):
        dae = dae.replace(geo, reorder(geo, r'[ \t]*<polylist material="[^"]+" count="\d+">.*?</polylist>\s*\n', symbol), 1)
    for bind in re.findall(r'<bind_material>.*?</bind_material>', dae, re.S):
        dae = dae.replace(bind, reorder(bind, r'[ \t]*<instance_material symbol="[^"]+"[^>]*>.*?</instance_material>\s*\n|'
                                              r'[ \t]*<instance_material symbol="[^"]+"[^>]*/>\s*\n', symbol), 1)
    return dae, new, notes


def prepare(dae, pictures, model):
    """A rip's COLLADA text and pictures ({file name: image}) as the importer should be given them.
    -> (text, {new file name: image}, what was done)"""
    meshes = set(re.findall(r'<geometry id="([^"]+)-mesh"', dae))
    gone = hidden(model, meshes)
    for name in gone:
        dae = _take_out(dae, name)
    dae, new, notes = layered(dae, pictures, model['layers'])
    return dae, new, ([f"not drawn at rest, taken out: {', '.join(gone)}"] if gone else []) + notes


# ---------------------------------------------------------------------------------------- the lids of a blink
LID_STATES = (('blinkhalf', 'half'), ('blink', 'closed'))        # a bone's name -> what the eyes under it are doing


def _mesh(dae, name, material=None):
    """A mesh of the COLLADA text as triangles -> (corners (n, 3, 3), their texture coordinates (n, 3, 2), the
    image file its material draws); `material`: only the faces drawn with it."""
    import numpy as np
    geo = re.search(r'<geometry id="%s-mesh"[^>]*>.*?</geometry>' % re.escape(name), dae, re.S)
    if geo is None:
        return None
    values = lambda source: [float(v) for v in re.search(
        r'<float_array id="%s-array" count="\d+">([^<]*)</float_array>' % re.escape(source), geo.group(0)).group(1).split()]
    positions = re.search(r'<input semantic="POSITION" source="#([^"]+)"', geo.group(0)).group(1)
    P = np.array(values(positions)).reshape(-1, 3)
    corners, coords, image = [], [], None
    for group in re.finditer(r'<polylist material="([^"]+)-material" count="\d+">(.*?)</polylist>', geo.group(0), re.S):
        if material is not None and group.group(1) != material:
            continue
        inputs = {sem: (src, int(off)) for sem, src, off in
                  re.findall(r'<input semantic="(\w+)" source="#([^"]+)" offset="(\d+)"', group.group(2))}
        stride = 1 + max(off for _src, off in inputs.values())
        p = np.array(re.search(r'<p>([^<]*)</p>', group.group(2)).group(1).split(), int).reshape(-1, 3, stride)
        T = np.array(values(inputs['TEXCOORD'][0])).reshape(-1, 2)
        corners.append(P[p[:, :, inputs['VERTEX'][1]]])
        coords.append(T[p[:, :, inputs['TEXCOORD'][1]]])
        effect = re.search(r'<effect id="%s-effect">.*?</effect>' % re.escape(group.group(1)), dae, re.S)
        ids = re.findall(r'<init_from>([^<]+)</init_from>', effect.group(0)) if effect else []
        file = next((re.search(r'<image id="%s"[^>]*>\s*<init_from>([^<]+)</init_from>' % re.escape(i), dae) for i in ids), None)
        image = image or (file.group(1) if file else None)
    if not corners:
        return None
    return np.concatenate(corners), np.concatenate(coords), image


def _inside(points, tri):
    """For 2D `points` (n, 2) and one triangle (3, 2): (which are inside, their weights on its corners (n, 3))."""
    import numpy as np
    a, b, c = tri
    det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(det) < 1e-12:
        return np.zeros(len(points), bool), None
    w0 = ((b[1] - c[1]) * (points[:, 0] - c[0]) + (c[0] - b[0]) * (points[:, 1] - c[1])) / det
    w1 = ((c[1] - a[1]) * (points[:, 0] - c[0]) + (a[0] - c[0]) * (points[:, 1] - c[1])) / det
    w = np.stack([w0, w1, 1.0 - w0 - w1], 1)
    return (w >= -1e-6).all(1), w


def lids(dae, pictures, model, size=None):
    """What a blink puts over the eye, from the rip as it came (the faces the game shows while it blinks are still
    in it): {'half' | 'closed': an image laid out as the eye's bottom picture is, see-through where the eye still
    shows}. For each point of the eye's picture, the place on the eye it is drawn at; where the blinking face lies
    in front of that place (looking at the face from the front), the face's own colour there. {} when the rip has
    no such faces or no layered eye."""
    import numpy as np
    from PIL import Image
    eyes = [(m, refs[-1][0]) for m, refs in sorted(model['layers'].items()) if len(refs) > 1]
    faces = {}
    for _material, obj, bone, _shown in model['draws']:
        state = next((st for word, st in LID_STATES if word in bone.lower()), None)
        if state and state not in faces and f'<geometry id="{obj}-mesh"' in dae:
            faces[state] = obj
    eye_tris = []
    for mesh in set(re.findall(r'<geometry id="([^"]+)-mesh"', dae)):
        for material, texture in eyes:
            got = _mesh(dae, mesh, f'{material}_-_{texture}_png')
            if got is not None:
                eye_tris.append(got)
    if not faces or not eye_tris:
        return {}
    picture = pictures[eye_tris[0][2]]
    W, H = size or picture.size
    u, v = np.meshgrid((np.arange(W) + 0.5) / W, 1.0 - (np.arange(H) + 0.5) / H)
    texels = np.stack([u.ravel(), v.ravel()], 1)
    place = np.full((W * H, 3), np.nan)                 # where on the eye each point of its picture is drawn
    for corners, coords, _image in eye_tris:
        for tri_p, tri_t in zip(corners, coords):
            inside, w = _inside(texels, tri_t)
            inside &= np.isnan(place[:, 0])
            place[inside] = w[inside] @ tri_p
    out = {}
    for state, obj in faces.items():
        corners, coords, image = _mesh(dae, obj)
        skin = np.asarray(pictures[image].convert('RGBA'), float)
        h, w_ = skin.shape[:2]
        colour = np.zeros((W * H, 4))
        depth = np.full(W * H, -np.inf)
        on = ~np.isnan(place[:, 0])
        for tri_p, tri_t in zip(corners, coords):
            lo, hi = tri_p[:, :2].min(0), tri_p[:, :2].max(0)
            near = on & (place[:, 0] >= lo[0]) & (place[:, 0] <= hi[0]) & (place[:, 1] >= lo[1]) & (place[:, 1] <= hi[1])
            if not near.any():
                continue
            idx = np.nonzero(near)[0]
            inside, w = _inside(place[idx, :2], tri_p[:, :2])
            if not inside.any():
                continue
            idx, w = idx[inside], w[inside]
            z = w @ tri_p[:, 2]
            front = (z > depth[idx]) & (z >= place[idx, 2] - 1e-3)      # in front of the eye, and of any face already there
            idx, w = idx[front], w[front]
            depth[idx] = z[front]
            t = w @ tri_t
            x = np.clip((t[:, 0] % 1.0) * w_, 0, w_ - 1).astype(int)
            y = np.clip((1.0 - t[:, 1] % 1.0) * h, 0, h - 1).astype(int)
            colour[idx] = skin[y, x]
            colour[idx, 3] = 255
        out[state] = Image.fromarray(colour.reshape(H, W, 4).astype(np.uint8), 'RGBA')
    return out
