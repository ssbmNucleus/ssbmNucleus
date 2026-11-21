"""Identify textures in the live renderer's own index space.

Two directions. The forward lookups -- `texture_usage`, `texture_sheet`, `highlight`
-- answer "where is texture N drawn?". `identify` answers the reverse, "what is drawn
HERE?", in one picture (both labs: skin_lab and stage_lab call it):

* **One render.** Every texture is painted one flat id colour (alpha kept, made
  opaque or clear), vertex colours turn white (or, for an object identified on its
  own, its id colour), and an object with no texture takes its id colour through its
  material. All of it goes in at once (updateTextures and setVertexColors on a
  protocol-2 viewer; one texture at a time on an older one, whose vertex colours then
  stay), one frame is grabbed, and everything is put back exactly as it was: the
  renderer reloads the file exported before the look (`_take_back`: putting each
  texture back would encode it again and could land in the wrong slot), and the
  camera returns. It is a look, not an edit.
* **The ids.** A texture index, or an object `Group g:i` / `Model:i` for an object
  with no texture, and for the objects of a texture that ONLY vertex-coloured objects
  draw while their vertex colours carry the hue (Dream Land's tree and side bushes
  are one texture, told apart by vertex colour): there each object is its own id,
  edited with recolor_vertex material_ids. Animation frames show as their base
  texture; a texture only ever drawn as a second layer is painted white and named
  as a layer of what it lies on.
* **Decoding.** The renderer's own gain (a material's diffuse plus ambient lightens
  an unlit surface up to ~1.5x) keeps a colour's proportions, so an id colour has no
  channel above DECODE_LEVEL and a pixel is matched by its colour divided by its
  brightest channel. Pixels too dark, or between two ids (JPEG edges), are unknown
  and filled from their neighbours; specks are dropped.
* **The picture** is drawn from the decoded ids, not the render: each id in a colour
  far from its neighbours' (`display_colours`), shaded by the real render, outlined,
  numbered at the inside of each sizeable region, with a legend (size, colour_from,
  what is too small to number, what this camera does not see). The `surfaces` table
  carries the same per id: share of the picture, screen box, colour_from, format,
  the objects that draw it. `points` looks pixels up in the same id buffer.
"""
import base64
import io
import math
import struct
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from shared import mod_files
from shared.rendering import regions


HIDDEN_NOTE = ('hidden textures are never drawn on the fighter by default -- "lowpoly" is the '
               'off-screen magnifier/shadow model, "alternate" a model piece only some moves swap in -- '
               'so editing them alone changes nothing you can see.')


def _look_folder(item):
    """The session's own working folder (a Skin Lab's scratch, a Stage Lab's workspace), where a look writes
    the file it reloads; None for a session without one."""
    scratch = item.get('scratch')
    if scratch is not None and getattr(scratch, 'name', None):
        return Path(scratch.name)
    source = (item.get('source') or {}).get('datFile')
    return Path(source).parent if source else None


def _snapshot(item):
    """What a look needs to leave the renderer as it found it (`_take_back`), taken before it writes anything:
    the true material values (lab_common.material_baseline, read once a session) and the file the renderer
    shows. None when the renderer cannot load a file back (an older one, a stand-in) or the session has no
    folder: the look then puts things back itself."""
    from . import lab_common
    viewer, folder = item['viewer'], _look_folder(item)
    if folder is None or not lab_common.supports(viewer, 'loadDat'):
        return None
    try:
        lab_common.material_baseline(item)
        return {'folder': folder, 'data': viewer.export_dat()}
    except Exception:
        return None


def _take_back(item, snapshot):
    """The session's renderer back on the file `_snapshot` took (loadDat, camera kept) -> True; False when
    loadDat failed (the renderer refuses before changing anything; the caller puts everything back itself).

    A look's own put-back is not the file it found. The renderer writes a texture into every slot whose
    encoded bytes equal that slot's (HSDRawViewer RenderJObj.ApplyTexture), and a flat paint in a palette
    format encodes alike in every slot of a size, so putting two back gave each the other's art: Dream Land
    saved its side faces with the front strip's grass and its platform tops with the platform sides, and
    Fountain of Dreams' leaves and pillars came back in one another's colours.
    Writing a texture back also encodes it again, which a CMPR texture does not survive (Dream Land's
    lightning: 36 levels off on average). The file taken before the look has none of that.

    As after model_colours.reload, the renderer's own material "originals" are this file's from here on
    (`resumed`: resets go to the baseline `_snapshot` read). A stage animation starts again at frame 0 on a
    reload, so a frame or pause the session set (stage_lab `animation`) is set again."""
    from . import lab_common
    viewer, folder = item['viewer'], snapshot['folder']
    expected = lab_common.texture_list(viewer)
    path = folder / f'look-{uuid.uuid4().hex[:12]}.dat'
    try:
        path.write_bytes(snapshot['data'])
        viewer.reopen(path)
    except Exception:
        path.unlink(missing_ok=True)
        return False
    item['resumed'] = True
    for old in folder.glob('look-*.dat'):
        if old != path:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass
    if not lab_common.same_textures(viewer, expected):
        viewer.close()                     # the lab reopens it from its last checkpoint on the next call
        raise ValueError('The working copy reloaded with a different texture list after the look; open it again.')
    _pose(item)
    return True


def _pose(item):
    """A stage animation starts again at frame 0 on a reload: the frame or pause the session set, again."""
    viewer = item['viewer']
    pose = item.get('animation') or {}
    if pose.get('playing') is False:
        viewer.set_anim_playing(False)       # paused first, so the frame set next is the one it stays on
    if 'frame' in pose:
        viewer.set_anim_frame(pose['frame'])
    if pose.get('playing') is True:
        viewer.set_anim_playing(True)


def _hidden_kinds(hidden):
    """{texture index: 'lowpoly' | 'alternate'} from skin_lab's data-read sets."""
    return {i: kind for kind in ('lowpoly', 'alternate') for i in (hidden or {}).get(kind, [])}


def texture_usage(viewer, hidden=None, layout=None):
    """`layout`: the session's UV layout when the caller already holds it (lab_common.uv_layout)."""
    layouts = {entry['index']: entry for entry in (viewer.get_uv_layout() if layout is None else layout)}
    kinds = _hidden_kinds(hidden)
    rows = []
    for texture in viewer.textures:
        index = texture['index']
        base = texture.get('animates') if texture.get('matAnim') else index
        triangles = np.asarray(layouts.get(base, {}).get('triangles', []), dtype=float)
        row = {**texture, 'geometry_texture_index': base,
               'mapped_triangles': len(triangles),
               **({'hidden': kinds[base]} if base in kinds else {}),
               'animation_variants': [t['index'] for t in viewer.textures
                                      if t.get('matAnim') and t.get('animates') == index],
               'needs_material_upscale': max(texture['width'], texture['height']) < 128}
        if triangles.size:
            positions = triangles[:, 6:15].reshape(-1, 3)
            row['bounds'] = {'min': positions.min(0).round(3).tolist(),
                             'max': positions.max(0).round(3).tolist()}
        rows.append(row)
    return {'textures': rows, 'reading': True,
            'note': 'Live Skin Lab indices, including animation links. ' + (HIDDEN_NOTE + ' ' if kinds else '') +
                    'Triangle counts describe UV-mapped geometry, not semantic body parts or visibility. Use highlight with candidate texture_indices to see '
                    'their actual location, and texture_sheet to inspect artwork. No mapping means unknown, not unused.'}


def texture_sheet(viewer, page=0, hidden=None, marks=None, read=None):
    """One labelled page of 32 live textures. `marks` ({index: label}) adds a label
    (the Stage Lab's "grey" slots); `read` (index -> PNG bytes) reuses pixels the
    caller already holds instead of asking the renderer again."""
    count = 32
    pages = max(1, math.ceil(len(viewer.textures) / count))
    if type(page) is not int or not 0 <= page < pages:
        raise ValueError(f'Choose a texture sheet page from 0 to {pages - 1}.')
    textures = viewer.textures[page * count:(page + 1) * count]
    kinds = _hidden_kinds(hidden)
    read = read or viewer.get_full_texture
    sheet = Image.new('RGB', (960, max(1, math.ceil(len(textures) / 6)) * 154), '#20252c')
    draw = ImageDraw.Draw(sheet)
    for offset, texture in enumerate(textures):
        with Image.open(io.BytesIO(read(texture['index']))) as image:
            image = image.convert('RGBA')
            scale = min(144 / image.width, 120 / image.height)
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                                 Image.Resampling.NEAREST)
            x, y = offset % 6 * 160 + 8, offset // 6 * 154 + 4
            sheet.paste(image, (x, y), image)
            label = f"{texture['index']} | {texture['width']}x{texture['height']}"
            if texture.get('matAnim'):
                label += f" -> {texture.get('animates', '?')}"
            elif texture['index'] in kinds:
                label += ' | low-poly' if kinds[texture['index']] == 'lowpoly' else ' | alt model'
            if marks and texture['index'] in marks:
                label += f" | {marks[texture['index']]}"
            draw.text((x, y + 124), label, fill='white')
    output = io.BytesIO()
    sheet.save(output, format='PNG')
    return {'reading': True, 'page': page, 'pages': pages,
            'texture_indices': [t['index'] for t in textures],
            'files': [{**mod_files.register(output.getvalue(), f'Live texture sheet {page}.png'), 'preview_only': True}],
            'note': 'Labels are live Skin Lab indices and size; arrows identify the base texture an animation '
                    'frame replaces. ' + ('"low-poly" and "alt model" labels mark ' + HIDDEN_NOTE + ' ' if kinds else '') +
                    'Use highlight to confirm which geometry uses a texture before editing.'}


def highlight(item, indices):
    from .skin_lab import _png, _preview
    viewer = item['viewer']
    known = {t['index'] for t in viewer.textures}
    if (not isinstance(indices, list) or not 1 <= len(indices) <= 16
            or any(type(i) is not int or i not in known for i in indices)):
        raise ValueError('Choose 1..16 live texture_indices to highlight.')
    # Include linked animation frames so blinking cannot hide the diagnostic.
    chosen = set(indices)
    chosen.update(t['animates'] for t in viewer.textures
                  if t['index'] in chosen and t.get('matAnim') and t.get('animates') in known)
    chosen.update(t['index'] for t in viewer.textures if t.get('matAnim') and t.get('animates') in chosen)
    before = {i: viewer.get_full_texture(i) for i in sorted(chosen)}
    snapshot = _snapshot(item)
    restore_errors = []
    try:
        for index, raw in before.items():
            with Image.open(io.BytesIO(raw)) as image:
                pixels = np.array(image.convert('RGBA'))
            pixels[..., :3] = [255, 0, 255]
            viewer.update_texture(index, _png(pixels))
        file = _preview(item, 'Texture location - magenta.png')
    finally:
        if snapshot is None or not _take_back(item, snapshot):     # the file as the look found it
            for index, raw in before.items():
                try:
                    viewer.update_texture(index, raw)
                except Exception:
                    restore_errors.append(index)
        if restore_errors:
            raise ValueError(f'Could not restore diagnostic textures {restore_errors}. Reopen the last working copy before editing.')
    return {'reading': True, 'texture_indices': sorted(chosen),
            'files': [{**file, 'preview_only': True}],
            'note': 'Magenta marks where these textures render in this pose. Original textures have been restored. '
                    'This is a diagnostic, not an edit. If the requested part is not highlighted, select another texture.'}


# --------------------------------------------------------------------------- #
# identify: "what is drawn HERE?" (module doc)                                 #
# --------------------------------------------------------------------------- #
DECODE_LEVEL = 136           # an id colour's brightest channel (8 x 17: exact in a 4-bit vertex colour); a
                             # material's gain up to 1.8x cannot clip it
DARK = 18                    # a pixel whose brightest channel is below this is unknown
SPECK = 24                   # a region under this many frame pixels is noise (JPEG edges between ids)
FILL = 3                     # unknown pixels this close to an id take it
MIN_LABEL_AREA = 0.0012      # a region under this share of the picture gets no number
MAJOR_AREA = 0.005           # an id covering at least this share of the picture is a major surface,
MAJOR_SHARE = 0.02           # or this share of all it identified (a stage small in the frame: Battlefield)
PICTURE_WIDTH = 1024         # vision.PREVIEW_MAX_SIDE: the model sees the picture unscaled
LEGEND_MAX = 240
LABELS_PER_ID = 3
MAX_POINTS = 16
ALPHA_CUT = 24               # alpha at least this is drawn opaque in the id render, below it clear
GX_FORMATS = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565', 5: 'RGB5A3', 6: 'RGBA8', 8: 'CI4', 9: 'CI8',
              10: 'CI14X2', 14: 'CMPR'}
# The picture's colours (Kelly's colours of maximum contrast and a few more), never the decoding's.
DISPLAY = ('#f3c300', '#875692', '#f38400', '#a1caf1', '#be0032', '#c2b280', '#848482', '#008856', '#e68fac',
           '#0067a5', '#f99379', '#604e97', '#f6a600', '#b3446c', '#dcd300', '#a0522d', '#8db600', '#e25822',
           '#00b5c8', '#f2f3f4', '#d000d0', '#7fffd4', '#1e90ff', '#ff69b4', '#32cd32', '#ffe4b5')
UNKNOWN = (58, 58, 58)
IDENTIFY_NOTE = ('Every surface is painted one flat colour and numbered with its id: a number is a texture_index; '
                 '"g:i" is the object "Group g:i" (a texture several objects draw whose vertex colours tell them '
                 'apart, or an object with no texture): edit it with recolor_vertex or set_material by that id. '
                 'surfaces: per id, its share of the picture (area), screen box (x0,y0,x1,y1, 0..1), colour_from '
                 'and the objects drawing it, largest first. identify with points [[x,y]] (0..1 of the picture) '
                 'says what is under a spot; with camera, from another angle. Nothing was changed.')


def label(key):
    """An id as the picture numbers it: 29, 'Group 5:16' -> '5:16', 'Model:3' -> 'm3'."""
    if isinstance(key, int):
        return str(key)
    if key.startswith('Group '):
        return key[6:]
    if key.startswith('Model:'):
        return 'm' + key[6:]
    return key


def id_palette(count):
    """`count` decode colours: two rings of hue (full and 0.6 saturation), as far apart as they allow,
    none with a channel above DECODE_LEVEL (module doc). -> (count, 3) uint8"""
    import colorsys
    if count <= 0:
        return np.zeros((0, 3), np.uint8)
    outer = count if count < 4 else max(3, round(count / 1.6))
    rows = []
    for n, saturation, offset in ((outer, 1.0, 0.0), (count - outer, 0.6, 0.5)):
        for k in range(n):
            rows.append(colorsys.hsv_to_rgb(((k + offset) / n) % 1.0, saturation, 1.0))
    return np.clip(np.round(np.array(rows) * DECODE_LEVEL), 0, 255).astype(np.uint8)


def _proportions(colours):
    colours = np.asarray(colours, np.float32)
    return colours / np.maximum(colours.max(-1, keepdims=True), 1)


def palette_spacing(palette):
    """The smallest distance between two decode colours, by proportion (what decoding tells apart)."""
    if len(palette) < 2:
        return 1.0
    p = _proportions(palette)
    d = np.sqrt(((p[:, None] - p[None]) ** 2).sum(-1))
    return float(d[~np.eye(len(p), dtype=bool)].min())


def decode(rgb, palette):
    """Per pixel, the palette row its colour shows, or -1 (too dark, or between ids). rgb: (h, w, 3) uint8.

    Each distinct colour (6 bits a channel) once: its colour over its brightest channel against
    each decode colour's, accepted within 45% of the palette's own spacing."""
    if not len(palette):
        return np.full(rgb.shape[:2], -1, np.int32)
    q = (rgb >> 2).astype(np.int32)
    codes = (q[..., 0] << 12) | (q[..., 1] << 6) | q[..., 2]
    unique, inverse = np.unique(codes.ravel(), return_inverse=True)
    grid = np.stack([unique >> 12, (unique >> 6) & 63, unique & 63], -1).astype(np.float32) * 4 + 2
    p, ref = _proportions(grid), _proportions(palette)
    distance = (p * p).sum(1)[:, None] + (ref * ref).sum(1)[None] - 2 * p @ ref.T
    nearest = distance.argmin(1)
    close = np.sqrt(np.maximum(distance[np.arange(len(p)), nearest], 0)) <= min(0.12, 0.45 * palette_spacing(palette))
    table = np.where(close & (grid.max(1) >= DARK), nearest, -1).astype(np.int32)
    return table[inverse].reshape(codes.shape)


def _majority(ids, size=5):
    """Each pixel the id most of its size x size neighbours show (unknown pixels do not vote): leaf holes and
    JPEG's blurred colour at fine detail read as the surface around them."""
    best = np.full(ids.shape, -1, np.int32)
    votes = np.zeros(ids.shape, np.int32)
    for value, box in enumerate(regions.find_objects(ids + 1)):
        if box is None:
            continue
        box = tuple(slice(max(0, s.start - size), s.stop + size) for s in box)
        count = regions.box_count(ids[box] == value, size)
        win = count > votes[box]
        votes[box] = np.where(win, count, votes[box])
        best[box] = np.where(win, value, best[box])
    return best


def _clean(ids):
    """Majority over a small window, specks dropped, then unknown pixels next to an id take it."""
    ids = _majority(ids)
    boxes = regions.find_objects(ids + 1)
    for value, box in enumerate(boxes):
        if box is None:
            continue
        parts, count = regions.label(ids[box] == value)
        if count > 1 or (count == 1 and (parts > 0).sum() < SPECK):
            sizes = np.bincount(parts.ravel())
            small = sizes < SPECK
            small[0] = False
            region = ids[box]
            region[small[parts]] = -1
    unknown = ids < 0
    if unknown.any() and not unknown.all():
        fill, rows, cols = regions.nearest_known(unknown, FILL)
        ids[fill] = ids[rows[fill], cols[fill]]
    return ids


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                 # Pillow before 10.1: the bitmap font
        return ImageFont.load_default()


def display_colours(ids):
    """{id row: RGB}: each visible id a picture colour far from those of the ids it touches, and, the
    largest first, one no other id has while unused ones last."""
    counts = np.bincount(ids[ids >= 0].ravel()) if (ids >= 0).any() else np.zeros(0, int)
    present = [v for v in range(len(counts)) if counts[v]]
    touching = {v: set() for v in present}
    width = len(counts) + 1
    for a, b in ((ids[:, :-1], ids[:, 1:]), (ids[:-1], ids[1:])):
        edge = (a != b) & (a >= 0) & (b >= 0)
        for pair in np.unique(a[edge].astype(np.int64) * width + b[edge]).tolist():
            x, y = divmod(pair, width)
            touching[x].add(y)
            touching[y].add(x)
    choices = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in DISPLAY]
    weight = np.array([2.0, 4.0, 3.0])

    def apart(c, d):
        return float(np.sqrt((((np.array(c, float) - np.array(d, float)) ** 2) * weight).sum()))
    chosen, used = {}, {}
    for v in sorted(present, key=lambda v: -counts[v]):
        near = [chosen[n] for n in touching[v] if n in chosen]

        def score(c):
            neighbours = min((apart(c, n) for n in near), default=1e9)
            return (min(neighbours, 240) // 60, -used.get(c, 0), neighbours)
        best = max(choices, key=score)
        chosen[v] = best
        used[best] = used.get(best, 0) + 1
    return chosen


def _plan(viewer, inventory, grey_names=()):
    """What one identify render paints (module doc).

    -> {'keys': [id], 'texture': {live index: id | None (painted white)}, 'vertex': {object id: id | None},
        'material': {object id: id}, 'objects': {object id: obj}, 'drawn_by': {index: [object ids]},
        'layers': {index: [indices on the same objects]}, 'kinds': {object id: colour_from},
        'split': {indices whose objects are ids of their own (told apart by vertex colour)},
        'intensity': {indices whose slot stores lightness only}}

    A slot that stores lightness only (I4, I8, IA4, IA8, a greyscale palette) cannot hold an id colour: the
    renderer encodes a painted texture in the slot's own format, so FD's sky (texture 5, I8) drew its id as a
    grey level under the material's indigo. Such a texture is painted white and its id rides on the objects
    that draw it: their vertex colours when they take them, else their material ('vertex' / 'material')."""
    from shared.rendering import dat_colours as dc
    live = {t['name']: t['index'] for t in viewer.textures if not t.get('matAnim') and t.get('name')}
    objects = [o for o in (inventory.objects if inventory else []) if o.id.startswith(dc.RENDERED)]
    drawn_by, first, layers, kinds, vertex_hue, base, intensity = {}, set(), {}, {}, set(), {}, set()
    for obj in objects:
        own = list(dict.fromkeys(live[t['name']] for t in obj.textures if t.get('name') in live))
        intensity.update(live[t['name']] for t in obj.textures if t.get('name') in live and t.get('grey'))
        for position, index in enumerate(own):
            drawn_by.setdefault(index, []).append(obj.id)
            layers.setdefault(index, set()).update(i for i in own if i != index)
            if position == 0:
                first.add(index)
                base[obj.id] = index
        try:
            kind, parts = dc.colour_from(obj, inventory.dat, set(grey_names))
        except Exception:
            kind, parts = 'texture', ['texture']
        kinds[obj.id] = kind
        if 'vertex' in parts and dc.uses_vertex(obj):
            vertex_hue.add(obj.id)
    by_id = {o.id: o for o in objects}
    keys, texture, vertex, material, split = [], {}, {}, {}, set()
    for t in viewer.textures:
        if t.get('matAnim'):
            continue
        index, users = t['index'], drawn_by.get(t['index'], [])
        if len(users) >= 2 and all(dc.uses_vertex(by_id[u]) for u in users) and any(u in vertex_hue for u in users):
            texture[index] = None                      # its objects are told apart by vertex colour
            split.add(index)
            for user in users:
                vertex[user] = user
                keys.append(user)
        elif users and index not in first:
            texture[index] = None                      # only ever a second layer: named with what it lies on
        else:
            texture[index] = index
            keys.append(index)
    for obj in objects:
        if not any(t.get('name') in live for t in obj.textures):
            keys.append(obj.id)
            if dc.uses_vertex(obj):
                vertex[obj.id] = obj.id
            elif obj.material is not None:
                material[obj.id] = obj.id
        elif dc.uses_vertex(obj) and obj.id not in vertex:
            vertex[obj.id] = None                      # white: its texture's id colour shows as painted
    for obj in objects:                                # a lightness-only slot's id rides on its objects
        index = base.get(obj.id)
        if index in intensity and texture.get(index) == index:
            if dc.uses_vertex(obj):
                vertex[obj.id] = index
            elif obj.material is not None:
                material[obj.id] = index
    for t in viewer.textures:                          # an animation frame shows as its base
        if t.get('matAnim'):
            texture[t['index']] = texture.get(t.get('animates'))
    keys = list(dict.fromkeys(keys))
    return {'keys': keys, 'texture': texture, 'vertex': vertex, 'material': material, 'objects': by_id,
            'drawn_by': drawn_by, 'layers': {i: sorted(v) for i, v in layers.items() if v}, 'kinds': kinds,
            'split': split, 'intensity': intensity}


def _as_stored(plan, palette):
    """The decode colours as the renderer will show them: an id painted through vertex colours is stored in its
    attribute's GX format (Dream Land's are RGBA4: 4 bits a channel), so it is matched as stored."""
    from shared.rendering import dat_colours as dc
    reference = palette.copy()
    carriers = {}                       # an id -> the first object whose vertex colours paint it
    for object_id, key in plan['vertex'].items():
        if key is not None:
            carriers.setdefault(key, object_id)
    for n, key in enumerate(plan['keys']):
        obj = plan['objects'].get(carriers.get(key))
        attrs = [a for a in (obj.vertex if obj else ()) if a.positions]
        if attrs:
            fmt = attrs[0].fmt
            stored = dc.decode_colour(fmt, dc.encode_colour(fmt, palette[n], bytes(dc.COLOUR_FORMATS[fmt][1])))
            reference[n] = stored[:3]
    return reference


def _vertex_message(inventory, objects, colour_of):
    """setVertexColors for `objects`: colour_of(obj, rgba) -> new RGBA per stored value (dat_colours order)."""
    from shared.rendering import dat_colours as dc
    rows = []
    for obj in objects:
        colors = []
        for attr in obj.vertex:
            if not attr.positions:
                continue
            values = [colour_of(obj, rgba) for _, rgba in dc.vertex_values(inventory.dat, attr)]
            colors.append({'pobj': attr.key[3], 'attr': attr.key[4],
                           'rgba': base64.b64encode(bytes(v for rgba in values for v in rgba)).decode('ascii')})
        if colors:
            rows.append({'id': obj.id, 'colors': colors})
    return {'type': 'setVertexColors', 'objects': rows}


def _supports(viewer, message):
    check = getattr(viewer, 'supports', None)
    return callable(check) and check(message) is True


def _restore_camera(viewer, camera):
    viewer.set_camera(rot_x=camera['rotX'], rot_y=camera['rotY'], scale=camera['scale'], x=camera['x'], y=camera['y'])


# The id copy (`_id_copy`): what a look changes in the file it paints over, so an id colour reaches the frame
# as painted. GX blend modes (HSD_PEDesc type, source and destination factors) and a TObj's colour map.
ID_BLEND = (1, 4, 5)                 # GX_BM_BLEND, GX_BL_SRCALPHA, GX_BL_INVSRCALPHA: an opaque id replaces
MODULATE = 4                         # COLORMAP_MODULATE: a painted texture times the (white) colour below it
COLOR_TEV = 1 << 30                  # TOBJ_TEVREG_ACTIVE.COLOR_TEV: the texture's own colour combiner
TEXTURE_COLOUR = ('ambient', 'diffuse', 'specular')


def _id_copy(data, plan, colour):
    """The file the identify render paints over: `data` with everything that colours a surface besides its
    id made neutral -> bytes, or None when the file cannot be read.

    An id is one store's colour (a texture, vertex colours, a material) times white everywhere else, and
    the frame shows it only if nothing else adds to it or tints it. FD's sky showed none of that
    (2026-11-18): its material diffuse #331ea1 multiplied the painted id, its nebula (Groups 4:1/4:2) blends
    additively (SRCALPHA/ONE) over the sky, and its background groups have fog. So, in the copy only:
    every material's ambient and diffuse are white (diffuse the id colour where the material carries one,
    `plan['material']`), its specular black, its alpha opaque from ALPHA_CUT up (lower is left: FD's edge
    lines rest at alpha 0 and an alpha animation, which the copy keeps, shows them); every
    pixel-engine blend is the plain alpha blend; every texture's colour map is MODULATE and its colour TEV
    off (a blend or add colour map, a TEV konst colour, would mix the id with something else); every fog
    is off; every light is grey at its brightest channel (a lit id keeps its proportions); every colour
    key of a material or light says the same. Vertex colours and textures are painted afterwards, through
    the renderer, as before. The copy is a look: `_take_back` loads the real file again."""
    from shared.rendering import dat_colours as dc
    try:
        inventory = dc.scan(data)
    except Exception:
        return None
    dat = inventory.dat

    def put_u32(offset, value):
        dat.put(offset, value.to_bytes(4, 'big'))
    done = set()
    for obj in inventory.objects:
        if not obj.id.startswith(dc.RENDERED):
            continue
        key = plan['material'].get(obj.id)
        diffuse = bytes(colour[key]) if key is not None else b'\xff\xff\xff'
        if obj.material is not None and dat.valid(obj.material + dc.MATERIAL_SIZE - 1):
            m = obj.material
            alpha = dat.u8(m + 0x07) / 255 * dat.f32(m + 0x0C)
            opaque = math.isfinite(alpha) and alpha >= ALPHA_CUT / 255
            if m not in done or key is not None:     # a shared material: the id it carries wins
                dat.put(m + 0x00, b'\xff\xff\xff' + bytes([dat.u8(m + 0x03)]))
                dat.put(m + 0x04, diffuse + (b'\xff' if opaque else bytes([dat.u8(m + 0x07)])))
                dat.put(m + 0x08, b'\x00\x00\x00' + bytes([dat.u8(m + 0x0B)]))
                if opaque:          # below the cut it stays: an alpha animation may show it (FD's lines)
                    dat.put(m + 0x0C, struct.pack('>f', 1.0))
            done.add(m)
        pe = dat.ptr(obj.mobj + 0x14) if obj.mobj is not None else None
        if pe is not None and dat.valid(pe + 6):
            dat.put(pe + 4, bytes(ID_BLEND))
        for row in obj.textures:
            tobj = row.get('tobj')
            if tobj is None or not dat.valid(tobj + 0x5B):
                continue
            put_u32(tobj + 0x40, dat.u32(tobj + 0x40) & ~(0xF << 16) | MODULATE << 16)
            tev = dat.ptr(tobj + 0x58)
            if tev is not None and dat.valid(tev + 0x1F):
                put_u32(tev + 0x1C, dat.u32(tev + 0x1C) & ~COLOR_TEV)
        for track in obj.tracks:
            if track.owner == 'material' and track.channel[0] in TEXTURE_COLOUR:
                field, channel = track.channel
                value = (0.0 if field == 'specular' else
                         colour[key][channel] / 255 if field == 'diffuse' and key is not None else 1.0)
                for k in track.keys:
                    dc.write_key(dat, track, k, value, 0.0)
    for fog in inventory.fogs:
        if dat.valid(fog['offset'] - 0x10 + 3):
            put_u32(fog['offset'] - 0x10, 0)              # GX_FOG_NONE
    lit = set()
    for light in inventory.lights:
        if light['offset'] not in lit:
            lit.add(light['offset'])
            dat.put(light['offset'], bytes([max(light['rgba'][:3])] * 3))
        values = [k['value'] for t in light['tracks'] for k in t.keys if k.get('value') is not None]
        for track in light['tracks']:
            for k in track.keys:
                dc.write_key(dat, track, k, max(values, default=1.0), 0.0)
    return dat.data()


def _load_id_copy(item, snapshot, plan, colour):
    """The renderer on the id copy of the file `_snapshot` took (loadDat into the session's own folder,
    camera kept) at the moment the real file's animation had reached -> True; False when it could not be
    made or loaded, the renderer back on the real file (the caller then neutralises what it can through the
    renderer). A reload starts a stage animation at frame 0, and FD's edge lines fade in by animation, so
    without the frame they were missing from the id render that the shade a moment earlier showed."""
    from . import lab_common
    viewer = item['viewer']
    data = _id_copy(snapshot['data'], plan, colour)
    if data is None:
        return False
    expected = lab_common.texture_list(viewer)
    state, started = None, time.perf_counter()
    if (item.get('animation') or {}).get('playing') is not False and callable(getattr(viewer, 'playing_frame', None)):
        try:
            state = viewer.playing_frame()
        except Exception:
            state = None
    path = snapshot['folder'] / f'look-ids-{uuid.uuid4().hex[:12]}.dat'
    try:
        path.write_bytes(data)
        viewer.reopen(path)
    except Exception:
        path.unlink(missing_ok=True)
        return False
    if not lab_common.same_textures(viewer, expected):
        _take_back(item, snapshot)
        return False
    _pose(item)
    count = (state or {}).get('frameCount') or 0
    if count > 0 and isinstance(state.get('frame'), (int, float)):
        speed = state.get('speed') if isinstance(state.get('speed'), (int, float)) else 1.0
        viewer.set_anim_frame((state['frame'] + (time.perf_counter() - started) * 60 * speed) % count)
    return True


def _render_ids(item, plan, inventory, palette, cameras, more=None):
    """Paint every id, grab one frame per camera (None: the session's own), put everything back exactly
    (module doc). `more(frames)` may name further cameras to grab while the ids are still painted (the
    zoom view is chosen from the first frame). -> (frames, False when vertex colours could not be painted).

    The renderer first loads the id copy of its file (`_id_copy`: materials, blending, colour maps, fog and
    lights neutral). One that cannot load a file gets its material colours set through the renderer instead
    (white, the id where a material carries it): blending and fog then stay."""
    from . import lab_common
    viewer = item['viewer']
    colour = {key: tuple(int(c) for c in palette[n]) for n, key in enumerate(plan['keys'])}
    originals = {index: viewer.get_full_texture(index) for index in plan['texture']}
    painted = {}
    for index, key in plan['texture'].items():
        pixels = lab_common.pixels(originals[index])
        drawn = pixels[..., 3] >= ALPHA_CUT
        # A lightness-only slot stores its alpha as its level (I4, I8): white where drawn, clear elsewhere.
        rgb = colour[key] if key is not None and index not in plan.get('intensity', ()) else (255, 255, 255)
        pixels[..., :3] = np.where(drawn[..., None], np.array(rgb, np.uint8), 0)
        pixels[..., 3] = np.where(drawn, 255, 0)
        painted[index] = lab_common.png(pixels)
    vertex_objects = [plan['objects'][o] for o in plan['vertex']]
    vertex_ok = bool(vertex_objects) and inventory is not None and _supports(viewer, 'setVertexColors')
    camera_before = dict(viewer.camera) if any(cameras) or more else None

    def paint(obj, rgba):
        key = plan['vertex'][obj.id]
        return (*(colour[key] if key is not None else (255, 255, 255)), 255 if rgba[3] >= ALPHA_CUT else 0)
    errors, frames = [], []
    snapshot = _snapshot(item)
    neutral, materials, material_back = False, [], []
    try:
        neutral = snapshot is not None and _load_id_copy(item, snapshot, plan, colour)
        if not neutral:
            materials, material_back = _material_paint(viewer, plan, colour)
        lab_common.write_textures(viewer, painted)
        if vertex_ok:
            viewer.apply_colour_messages([_vertex_message(inventory, vertex_objects, paint)])
        if materials:
            viewer.material_command({'type': 'setMaterialColors', 'edits': materials})
        for camera in cameras:
            frames.append(_grab(viewer, camera, camera_before))
        for camera in (more(frames) if more else ()):
            frames.append(_grab(viewer, camera, camera_before))
    finally:
        # The file as the look found it (_take_back); a renderer that cannot load one gets each thing put back.
        reloaded = snapshot is not None and _take_back(item, snapshot)
        if neutral and not reloaded:       # still on the id copy, which nothing but a reload undoes
            viewer.close()                 # the lab reopens it from its last checkpoint on the next call
            raise ValueError('Could not load the working copy back after the identify render; open it again.')
        steps = [] if reloaded else [lambda: lab_common.write_textures(viewer, originals)]
        if vertex_ok and not reloaded:
            steps.append(lambda: viewer.apply_colour_messages(
                [_vertex_message(inventory, vertex_objects, lambda obj, rgba: tuple(rgba))]))
        if material_back:                  # also after a reload: not every renderer resets materials on one
            steps.append(lambda: viewer.material_command({'type': 'setMaterialColors', 'edits': material_back}))
        if camera_before:
            steps.append(lambda: _restore_camera(viewer, camera_before))
        for step in steps:
            try:
                step()
            except Exception as exc:
                errors.append(str(exc))
        remember = getattr(viewer, 'remember_textures', None)
        if callable(remember) and not errors and not reloaded:
            remember(originals)       # the renderer holds exactly these bytes again: nothing to read back
    if errors:
        raise ValueError('Could not put everything back after the identify render (' + '; '.join(errors)[:200]
                         + '). Reopen the last checkpoint before editing.')
    return frames, vertex_ok or not vertex_objects


def _material_paint(viewer, plan, colour):
    """Without the id copy: every listed material's colours set through the renderer (diffuse white or the id
    it carries, ambient white, specular black; alpha bytes kept). -> (setMaterialColors edits, the edits back)."""
    edits, back = [], []
    listed = viewer.material_command({'type': 'getMaterials'}).get('materials') or []
    for material in listed:
        key = plan['material'].get(material.get('id'))
        rgb = {'diffuse': colour[key] if key is not None else (255, 255, 255), 'ambient': (255, 255, 255),
               'specular': (0, 0, 0)}
        for f in material.get('fields') or []:
            value = f.get('value')
            if f.get('key') in rgb and isinstance(value, str) and len(value) == 9:
                edits.append({'id': material['id'], 'field': f['key'],
                              'value': '#' + bytes(rgb[f['key']]).hex() + value[7:]})
                back.append({'id': material['id'], 'field': f['key'], 'value': value})
    return edits, back


def _grab(viewer, camera, home):
    """One frame from `camera` (set_camera arguments; None: the session's own camera, `home`)."""
    if camera:
        viewer.set_camera(**camera)
    elif home and dict(viewer.camera) != home:
        _restore_camera(viewer, home)
    return viewer.grab_frame()


def _label_spot(component):
    """The point deepest inside a region (its distance transform's maximum), so a number lands on it."""
    depth = regions.distance_inside(np.pad(component, 1))[1:-1, 1:-1]
    y, x = np.unravel_index(int(depth.argmax()), depth.shape)
    return int(x), int(y)


def _wrap(text, width=150):
    lines, current = [], ''
    for word in text.split(' '):
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = '    ' + word
        else:
            current = f'{current} {word}' if current else word
    return lines + [current]


def _regions_image(ids, colours, shade):
    """Each id in its picture colour, shaded by the real render, outlined; unknown pixels dark grey."""
    canvas = np.empty((*ids.shape, 3), np.float32)
    canvas[:] = UNKNOWN
    for value, rgb in colours.items():
        canvas[ids == value] = rgb
    if shade is not None:
        canvas *= 0.62 + 0.38 * (shade.astype(np.float32).mean(-1, keepdims=True) / 255.0)
    edge = np.zeros(ids.shape, bool)
    edge[:, 1:] |= ids[:, 1:] != ids[:, :-1]
    edge[1:] |= ids[1:] != ids[:-1]
    canvas[edge] *= 0.25
    return canvas


def _place_labels(draw, ids, rows, keys, minimum, taken, font, per_id=LABELS_PER_ID, origin=(0, 0)):
    """Number each row's id deep inside its largest regions of `ids` (a panel; `origin` its top left in the
    picture), at most `per_id` times, never over another number. -> the ids numbered."""
    def free(box):
        return all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in taken)
    numbered = set()
    boxes = regions.find_objects(ids + 1)
    for row in rows:
        value = keys.index(row['id'])
        crop = boxes[value] if value < len(boxes) else None
        if crop is None:
            continue
        parts, count = regions.label(ids[crop] == value, diagonal=True)
        sizes = np.bincount(parts.ravel())[1:]
        pieces = regions.find_objects(parts)
        placed = 0
        for n in np.argsort(-sizes):
            if sizes[n] < minimum or placed >= per_id:
                break
            piece = pieces[n]
            component = parts[piece] == n + 1
            dy = origin[1] + crop[0].start + piece[0].start
            dx = origin[0] + crop[1].start + piece[1].start
            text = label(row['id'])
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=2)
            for _ in range(3):
                lx, ly = _label_spot(component)
                x, y = lx + dx, ly + dy
                box = (x - (right - left) // 2 - 2, y - (bottom - top) // 2 - 2,
                       x + (right - left) // 2 + 2, y + (bottom - top) // 2 + 2)
                if free(box):
                    draw.text((box[0] + 2 - left, box[1] + 2 - top), text, font=font, fill='white',
                              stroke_width=2, stroke_fill='black')
                    taken.append(box)
                    placed += 1
                    break
                component = component.copy()       # crowded there: try the next deepest spot
                component[max(0, ly - 14):ly + 15, max(0, lx - 24):lx + 25] = False
                if not component.any():
                    break
        if placed:
            numbered.add(row['id'])
    return numbered


def _points(draw, points_at, font):
    for number, at in enumerate(points_at, 1):
        x, y = at['pixel']
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline='white', width=2)
        draw.text((x + 8, y - 8), f'P{number}', font=font, fill='white', stroke_width=2, stroke_fill='black')


def _legend(width, rows, keys, colours, too_small, unseen, unseen_words='this camera'):
    """The legend: a chip per id, then what is not numbered and what no view shows. -> an image."""
    small, columns, line = _font(12), 4, 15
    entries = [(colours.get(keys.index(row['id']), UNKNOWN),
                f"{label(row['id'])}  {row.get('size') or 'object'} {row.get('colour_from') or ''}".rstrip())
               for row in rows]
    notes = []
    if too_small:
        notes += _wrap('Too small to number: ' + ', '.join(label(k) for k in too_small))
    if unseen:
        notes += _wrap(f'Not visible from {unseen_words}: ' + ', '.join(label(k) for k in unseen))
    budget = max(1, (LEGEND_MAX - 12) // line - len(notes))
    if math.ceil(len(entries) / columns) > budget:
        keep = budget * columns - 1
        entries = entries[:keep] + [((0, 0, 0), f'+{len(rows) - keep} more in surfaces')]
    used_rows = math.ceil(len(entries) / columns)
    legend = Image.new('RGB', (width, 10 + line * (used_rows + len(notes))), (24, 26, 30))
    pen = ImageDraw.Draw(legend)
    step = width // columns
    for n, (rgb, text) in enumerate(entries):
        x, y = (n % columns) * step + 6, 5 + (n // columns) * line
        pen.rectangle((x, y + 1, x + 11, y + 12), fill=tuple(int(c) for c in rgb), outline=(200, 200, 200))
        pen.text((x + 16, y), text, font=small, fill=(235, 235, 235))
    for n, text in enumerate(notes):
        pen.text((6, 5 + (used_rows + n) * line), text, font=small, fill=(235, 235, 235))
    return legend


def _png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def _picture(ids, keys, shade, rows, too_small, unseen, points_at):
    """The labelled identify picture (module doc) -> PNG bytes. Ids that get no number join `too_small`."""
    height, width = ids.shape
    colours = display_colours(ids)
    image = Image.fromarray(np.clip(_regions_image(ids, colours, shade), 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    numbered = _place_labels(draw, ids, rows, keys, MIN_LABEL_AREA * width * height, [], _font(17))
    too_small += [row['id'] for row in rows if row['id'] not in numbered and row['id'] not in too_small]
    _points(draw, points_at, _font(12))
    legend = _legend(width, rows, keys, colours, too_small, unseen)
    out = Image.new('RGB', (width, height + legend.height))
    out.paste(image, (0, 0))
    out.paste(legend, (0, height))
    return _png_bytes(out)


# --------------------------------------------------------------------------- #
# three views in one picture (module doc: identify without a camera)          #
# --------------------------------------------------------------------------- #
VIEWS = {'stage': ('game camera', 'raised three-quarter', 'zoom on small scenery'),
         'costume': ('front', 'back', 'head zoom')}
RAISED = {'rot_x': 28.0, 'rot_y': 30.0}     # the stage's raised front three-quarter view, added to its camera
STAGE_ZOOM = 2.5                            # the busiest small-scenery window is this fraction of the frame's width
ZOOM_ASPECT = 2.0                           # and this much wider than high: scenery stands along the ground
GAP = 6
MAX_PICTURE_SIDE = 1024                     # vision.PREVIEW_MAX_SIDE: what the model sees unscaled
MIN_PANEL_SCALE = 0.45                      # a layout shrinking a view more than this: two pictures instead
MAX_PANEL_SCALE = 1.4
BACKDROP = (24, 26, 30)


def _camera_args(camera):
    return {'rot_x': camera['rotX'], 'rot_y': camera['rotY'], 'scale': camera['scale'], 'x': camera['x'],
            'y': camera['y']}


def _rgb(frame):
    with Image.open(io.BytesIO(frame)) as image:
        return np.array(image.convert('RGB'))


def _phase_shift(a, b):
    """(dx, dy) in pixels that move image a onto image b (phase correlation of their grey levels)."""
    ga, gb = a.astype(np.float32).mean(-1), b.astype(np.float32).mean(-1)
    fa, fb = np.fft.rfft2(ga - ga.mean()), np.fft.rfft2(gb - gb.mean())
    product = fa.conj() * fb
    r = np.fft.irfft2(product / (np.abs(product) + 1e-9), s=ga.shape)
    y, x = np.unravel_index(int(r.argmax()), r.shape)
    h, w = r.shape
    return (x if x < w / 2 else x - w), (y if y < h / 2 else y - h)


def _pan_scale(item, home, shade):
    """Frame pixels per unit of camera pan. A pan is a shift on screen whatever the zoom, but its size per
    unit depends on how the renderer framed the model (3.75 px on Dream Land, ~55 on Mario), so it is
    measured once per renderer: one frame panned by a known step. -> px per unit, or None."""
    viewer = item['viewer']
    cached = item.get('pan_scale')
    if cached and cached[0] is viewer:
        return cached[1]
    item['pan_scale'] = (viewer, _measure_pan(viewer, home, shade))
    return item['pan_scale'][1]


def _measure_pan(viewer, home, shade):
    try:
        for step in (8.0, 96.0):          # a shift of 20+ pixels: the measure is within a few percent
            moved = _rgb(_grab(viewer, {**_camera_args(home), 'x': home['x'] + step}, home))
            dx, _ = _phase_shift(shade, moved)
            if abs(dx) >= 20:
                return abs(dx) / step
    finally:
        _restore_camera(viewer, home)
    return None


def _zoom_camera(home, window, frame_shape, ids_shape, pan):
    """The camera that fills the frame with `window` (left, top, width, height in decode pixels).

    Measured on the real renderer (Dream Land, Mario): a point shows at C + k (p0 - C) + pan_px * (x, y),
    with C the frame centre, k the zoom over the session's own and p0 where it shows unpanned; so a zoom
    keeps the centre only when the pan grows with it (Mario's own y pan of 8.2 units, 55 px each, put the
    pivot below the frame and a head zoom on his belly). The window's centre W comes to C with
    pan = k (own pan - (W - C) / pan_px)."""
    fh, fw = frame_shape
    ih, iw = ids_shape
    left, top, width, height = window
    k = iw / width if width / height >= iw / ih else ih / height
    cx, cy = (left + width / 2) * fw / iw, (top + height / 2) * fh / ih
    return {**_camera_args(home), 'scale': home['scale'] * k,
            'x': k * (home['x'] - (cx - fw / 2) / pan), 'y': k * (home['y'] - (cy - fh / 2) / pan)}


def _window_sums(mask, height, width, stride):
    """Sums of `mask` over every height x width window at `stride` -> (rows, cols) array."""
    s = np.zeros((mask.shape[0] + 1, mask.shape[1] + 1), np.int64)
    s[1:, 1:] = mask.cumsum(0).cumsum(1)
    ys = np.arange(0, mask.shape[0] - height + 1, stride)
    xs = np.arange(0, mask.shape[1] - width + 1, stride)
    y0, x0 = ys[:, None], xs[None]
    return s[y0 + height, x0 + width] - s[y0, x0 + width] - s[y0 + height, x0] + s[y0, x0], ys, xs


def _busiest(ids, zoom=STAGE_ZOOM, aspect=ZOOM_ASPECT, stride=8):
    """The window (1/zoom of the frame's width, `aspect` wide to high) holding the most distinct small ids
    (under MAJOR_AREA of the frame: fences, flowers, stars), more of their pixels breaking ties
    -> (left, top, width, height) or None."""
    h, w = ids.shape
    counts = np.bincount(ids[ids >= 0].ravel()) if (ids >= 0).any() else np.zeros(0, int)
    small = [v for v in range(len(counts)) if SPECK <= counts[v] < MAJOR_AREA * ids.size]
    if not small:
        return None
    width = int(w / zoom)
    height = min(h, int(width / aspect))
    # On blocks of `stride` pixels (a block counts when the id is in it): thin fences still count, 1/64 the work.
    rows, cols = h // stride, w // stride
    blocks = ids[:rows * stride, :cols * stride].reshape(rows, stride, cols, stride)
    score = weight = None
    for value in small:
        present = (blocks == value).any((1, 3))
        sums, ys, xs = _window_sums(present, height // stride, width // stride, 1)
        found = sums >= 2
        score = found.astype(np.int64) if score is None else score + found
        weight = sums if weight is None else weight + sums
    best = np.unravel_index(int(np.argmax(score * (rows * cols + 1) + weight)), score.shape)
    return int(xs[best[1]]) * stride, int(ys[best[0]]) * stride, width, height


def _head(ids):
    """A costume's head: the top of the figure, a little wider than tall -> (left, top, width, height) or None."""
    h, w = ids.shape
    rows = np.nonzero((ids >= 0).sum(1) >= 3)[0]
    if len(rows) < 8:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    band = max(8, int(0.26 * (bottom - top)))
    ys, xs = np.nonzero(ids[top:top + band] >= 0)
    if not len(xs):
        return None
    height = band * 1.35
    width = height * w / h
    cx, cy = float(np.median(xs)), top + band / 2
    left = min(max(0.0, cx - width / 2), w - width)
    up = min(max(0.0, cy - height / 2), h - height)
    return int(left), int(up), int(width), int(height)


def _content(ids, whole=False):
    """The part of a view worth showing: every id but a backdrop spanning the frame, with a margin.
    -> (top, left, bottom, right)."""
    h, w = ids.shape
    if whole:
        return 0, 0, h, w
    boxes = regions.find_objects(ids + 1)
    backdrop = [v for v, b in enumerate(boxes)
                if b is not None and b[0].stop - b[0].start >= 0.9 * h and b[1].stop - b[1].start >= 0.9 * w]
    mask = (ids >= 0) & ~np.isin(ids, backdrop)
    rows, cols = np.nonzero(mask.sum(1) >= 3)[0], np.nonzero(mask.sum(0) >= 3)[0]
    if len(rows) < 8 or len(cols) < 8:
        return 0, 0, h, w
    my, mx = int(0.04 * h), int(0.04 * w)
    return (max(0, int(rows[0]) - my), max(0, int(cols[0]) - mx),
            min(h, int(rows[-1]) + 1 + my), min(w, int(cols[-1]) + 1 + mx))


def _layout(sizes, width, height):
    """Panels for crops of `sizes` [(w, h)] in at most `width` x `height`: one row of three, two over one,
    one over two, or a column, whichever shrinks its most shrunk panel least.
    -> (rects [(x, y, w, h)] in the sizes' order, used height, the smallest panel scale)."""
    best = None
    n = len(sizes)
    shapes = ([[list(range(n))]] if n < 3 else
              [[[0, 1, 2]], [[0, 1], [2]], [[0], [1, 2]], [[0], [1], [2]]])
    for rows in shapes:
        heights = []
        for row in rows:
            fit = (width - GAP * (len(row) - 1)) / sum(sizes[i][0] / sizes[i][1] for i in row)
            heights.append(min(fit, MAX_PANEL_SCALE * min(sizes[i][1] for i in row)))
        total = sum(heights) + GAP * (len(rows) - 1)
        shrink = min(1.0, height / total)
        heights = [hr * shrink for hr in heights]
        scale = min(heights[r] / sizes[i][1] for r, row in enumerate(rows) for i in row)
        if best is None or scale > best[0] + 1e-6:
            rects, y = [None] * n, 0
            for r, row in enumerate(rows):
                widths = [heights[r] * sizes[i][0] / sizes[i][1] for i in row]
                x = (width - sum(widths) - GAP * (len(row) - 1)) / 2
                for i, pw in zip(row, widths):
                    rects[i] = (int(round(x)), int(round(y)), max(1, int(round(pw))), max(1, int(round(heights[r]))))
                    x += pw + GAP
                y += heights[r] + GAP
            best = (scale, rects, int(round(y - GAP)))
    return best[1], best[2], best[0]


def _compose_views(panels, keys, rows, names, too_small, unseen, colours, plan=None, points=None):
    """One picture of `panels` [(view, ids crop, shade crop)] with one legend. `points` ([x, y], 0..1 of the
    whole picture) are looked up in it (_point_lookup); `too_small` gains the ids no panel numbers.
    -> (PNG bytes, {view: (x, y, w, h)}, ids numbered, smallest panel scale, point lookups, picture ids)."""
    # The legend's room, at its tallest (every id too small to number), so the picture never passes 1024.
    legend_probe = _legend(MAX_PICTURE_SIDE, rows, keys, colours, [r['id'] for r in rows], unseen, 'any view')
    budget = MAX_PICTURE_SIDE - legend_probe.height - GAP
    rects, used, scale = _layout([(c.shape[1], c.shape[0]) for _, c, _ in panels], MAX_PICTURE_SIDE, budget)
    height = used + GAP + legend_probe.height
    ids = np.full((height, MAX_PICTURE_SIDE), -1, np.int32)
    shade = np.full((height, MAX_PICTURE_SIDE, 3), 255, np.uint8)
    where = {}
    for (view, crop, shade_crop), (x, y, w, h) in zip(panels, rects):
        ids[y:y + h, x:x + w] = np.array(Image.fromarray(crop.astype(np.int32)).resize((w, h), Image.Resampling.NEAREST))
        shade[y:y + h, x:x + w] = np.array(Image.fromarray(shade_crop).resize((w, h), Image.Resampling.BILINEAR))
        where[view] = (x, y, w, h)
    canvas = _regions_image(ids, colours, shade)
    inside = np.zeros(ids.shape, bool)
    for x, y, w, h in where.values():
        inside[y:y + h, x:x + w] = True
    canvas[~inside] = BACKDROP
    image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    font, small, taken, numbered = _font(17), _font(12), [], set()
    for view, (x, y, w, h) in where.items():
        visible = {keys[v] for v in np.unique(ids[y:y + h, x:x + w]) if v >= 0}
        numbered |= _place_labels(draw, ids[y:y + h, x:x + w], [r for r in rows if r['id'] in visible], keys,
                                  MIN_LABEL_AREA * w * h, taken, font, per_id=2, origin=(x, y))
        title = f'{names.index(view) + 1} {view}'
        box = draw.textbbox((x + 6, y + 4), title, font=small)
        draw.rectangle((box[0] - 4, box[1] - 3, box[2] + 4, box[3] + 3), fill=BACKDROP)
        draw.text((x + 6, y + 4), title, font=small, fill=(235, 235, 235))
    too_small += [r['id'] for r in rows if r['id'] not in numbered and r['id'] not in too_small]
    legend = _legend(MAX_PICTURE_SIDE, rows, keys, colours, too_small, unseen, 'any view')
    final = used + GAP + legend.height
    out = Image.new('RGB', (MAX_PICTURE_SIDE, final), BACKDROP)
    out.paste(image.crop((0, 0, MAX_PICTURE_SIDE, used)), (0, 0))
    out.paste(legend, (0, used + GAP))
    picture = np.full((final, MAX_PICTURE_SIDE), -1, np.int32)
    picture[:used] = ids[:used]
    at = _point_lookup(picture, keys, plan, points) if points else []
    _points(ImageDraw.Draw(out), at, small)
    return _png_bytes(out), where, numbered, scale, at, picture


def check_points(points):
    if points is not None and (not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS or any(
            not isinstance(p, (list, tuple)) or len(p) != 2
            or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in p) for p in points)):
        raise ValueError(f'points lists 1..{MAX_POINTS} [x, y] pairs, each 0..1 of the picture (0,0 top left).')


def _point_lookup(ids, keys, plan, points):
    """What is under each point: the id there (or around it, when the spot is an edge), the texture and its
    layers, the objects drawing it."""
    height, width = ids.shape
    out = []
    for x, y in points or ():
        px, py = min(width - 1, int(x * width)), min(height - 1, int(y * height))
        value = int(ids[py, px])
        if value < 0:
            window = ids[max(0, py - 6):py + 7, max(0, px - 6):px + 7]
            known = window[window >= 0]
            value = int(np.bincount(known).argmax()) if known.size else -1
        at = {'point': [round(float(x), 3), round(float(y), 3)], 'pixel': (px, py), 'id': None}
        if value >= 0:
            key = keys[value]
            texture = key if isinstance(key, int) else next(
                (i for i, users in plan['drawn_by'].items() if key in users), None)
            at['id'] = key
            if texture is not None:
                at['texture_index'] = texture
                if plan['layers'].get(texture):
                    at['layers'] = [texture, *plan['layers'][texture]]
            at['objects'] = plan['drawn_by'].get(key, []) if isinstance(key, int) else [key]
        out.append(at)
    return out


def _main_box(ids, value, crop, count):
    """The screen box of an id's regions that matter (strays under 3% of its area left out). -> top, left, bottom, right"""
    parts, _ = regions.label(ids[crop] == value, diagonal=True)
    sizes = np.bincount(parts.ravel())
    keep = [n for n in range(1, len(sizes)) if sizes[n] >= max(SPECK, 0.03 * count)] or [int(sizes[1:].argmax()) + 1]
    pieces = regions.find_objects(parts)
    top = min(pieces[n - 1][0].start for n in keep) + crop[0].start
    left = min(pieces[n - 1][1].start for n in keep) + crop[1].start
    bottom = max(pieces[n - 1][0].stop for n in keep) + crop[0].start
    right = max(pieces[n - 1][1].stop for n in keep) + crop[1].start
    return top, left, bottom, right


def _check_camera(camera):
    if camera is not None and (not isinstance(camera, dict) or not camera
                               or set(camera) - {'rot_x', 'rot_y', 'scale', 'x', 'y'} or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000 for v in camera.values())):
        raise ValueError('camera takes rot_x, rot_y, scale and x, y numbers.')


def _facts(key, plan, textures, formats, grey):
    """What the table says about an id besides where it is: size, colour_from, format, the objects drawing it."""
    row = {}
    if isinstance(key, int):
        texture = textures.get(key) or {}
        users = plan['drawn_by'].get(key, [])
        row['size'] = f"{texture.get('width')}x{texture.get('height')}"
        kinds = {plan['kinds'].get(u) for u in users} - {None}
        if kinds:
            row['colour_from'] = kinds.pop() if len(kinds) == 1 else 'mixed'
        if formats.get(texture.get('name')):
            row['format'] = formats[texture.get('name')]
        if key in grey:
            row['greyscale'] = True
        if users:
            row['objects'] = users if len(users) <= 6 else users[:6] + [f'+{len(users) - 6} more']
        if plan['layers'].get(key):
            row['layers'] = plan['layers'][key]
    else:
        row['colour_from'] = plan['kinds'].get(key)
        own = [i for i, users in plan['drawn_by'].items() if key in users]
        if own:
            row['texture_index'] = own[0]
    return row


def _decoded(frame, reference):
    """A grabbed frame as decoded ids at PICTURE_WIDTH (sampled, never blended: a blend of two id colours
    would read as a third), and the frame's own (height, width)."""
    with Image.open(io.BytesIO(frame)) as image:
        height = round(image.height * PICTURE_WIDTH / image.width)
        rgb = np.array(image.convert('RGB').resize((PICTURE_WIDTH, height), Image.Resampling.NEAREST))
        size = (image.height, image.width)
    return _clean(decode(rgb, reference)), size


def _shade(frame, shape):
    with Image.open(io.BytesIO(frame)) as image:
        return np.array(image.convert('RGB').resize((shape[1], shape[0]), Image.Resampling.BILINEAR))


def identify(item, data=None, *, camera=None, points=None, shade=None, grey=(), name='Identify map.png',
             views=None):
    """The identify map of a lab session (module doc). `data`: the DAT bytes the renderer shows (None: export
    them); `shade`: the render at the session's camera when the caller just grabbed it; `grey`: greyscale
    slot indices; `views`: 'stage' or 'costume' for the three views in one picture when no `camera` is given
    (`_identify_views`), else one view. -> {'files', 'surfaces', 'major', 'too_small'?, 'not_visible'?, 'at'?,
    'note'}; the table is kept as item['identify'] (what the coverage line compares edits with)."""
    from shared.rendering import dat_colours as dc
    viewer = item['viewer']
    _check_camera(camera)
    check_points(points)
    try:
        inventory = dc.scan(data if data is not None else viewer.export_dat())
    except Exception:
        inventory = None              # no object evidence: every texture still gets its id
    names = {t['index']: t.get('name') for t in viewer.textures}
    plan = _plan(viewer, inventory, {names[i] for i in grey if names.get(i)})
    keys = plan['keys']
    palette = id_palette(len(keys))
    textures = {t['index']: t for t in viewer.textures}
    formats = {}
    for obj in (inventory.objects if inventory else []):
        for t in obj.textures:
            if t.get('name') and t.get('format') is not None:
                formats.setdefault(t['name'], GX_FORMATS.get(t['format'], str(t['format'])))
    if views in VIEWS and camera is None:
        return _identify_views(item, plan, inventory, palette, views, points, shade, grey, name,
                               lambda key: _facts(key, plan, textures, formats, grey))
    if camera is not None or shade is None:
        before = dict(viewer.camera) if camera else None
        try:
            if camera:
                viewer.set_camera(**camera)
            shade = viewer.grab_frame()
        finally:
            if before:
                _restore_camera(viewer, before)
    frames, vertex_painted = _render_ids(item, plan, inventory, palette, [camera])
    ids, _ = _decoded(frames[0], _as_stored(plan, palette))
    height = ids.shape[0]
    shade_rgb = _shade(shade, ids.shape)
    total = float(ids.size)
    boxes = regions.find_objects(ids + 1)
    counts = np.bincount(ids[ids >= 0].ravel(), minlength=len(keys)) if len(keys) else np.zeros(0, int)
    rows, unseen, too_small = [], [], []
    for value, key in enumerate(keys):
        if not counts[value]:
            unseen.append(key)
            continue
        top, left, bottom, right = _main_box(ids, value, boxes[value], counts[value])
        rows.append({'id': key, 'area': round(counts[value] / total, 4),
                     'box': [round(left / PICTURE_WIDTH, 3), round(top / height, 3),
                             round(right / PICTURE_WIDTH, 3), round(bottom / height, 3)],
                     **_facts(key, plan, textures, formats, grey)})
        if counts[value] < MIN_LABEL_AREA * total:
            too_small.append(key)
    rows.sort(key=lambda r: -r['area'])
    at = _point_lookup(ids, keys, plan, points)
    picture = _picture(ids, keys, shade_rgb, rows, too_small, unseen, at)
    seen = float(counts.sum()) / total if len(counts) else 0.0
    major = [r['id'] for r in rows if r['area'] >= MAJOR_AREA or (seen and r['area'] >= MAJOR_SHARE * seen)]
    item['identify'] = _table(item, plan, inventory, major, rows)
    return {'reading': True,
            'files': [{**mod_files.register(picture, name), 'preview_only': True}],
            'surfaces': rows, 'major': major,
            **({'too_small': too_small} if too_small else {}),
            **({'not_visible': unseen} if unseen else {}),
            **({'at': [{k: v for k, v in a.items() if k != 'pixel'} for a in at]} if at else {}),
            'note': IDENTIFY_NOTE + ('' if vertex_painted else VERTEX_NOTE)}


VERTEX_NOTE = (' This renderer cannot set vertex colours, so vertex-coloured surfaces may read as unknown '
               '(dark grey).')
VIEWS_NOTE = ('Every surface is painted one flat colour and numbered with its id, in three views in one picture '
              '(the titles say which), with one legend: an id has the same colour and number in every view. A number '
              'is a texture_index; "g:i" is the object "Group g:i" (a texture several objects draw whose vertex '
              'colours tell them apart, or an object with no texture): edit it with recolor_vertex or set_material '
              'by that id. surfaces: per id, `views` its share of each view (0: not seen there), `area` (what the '
              'table is sorted by) {area}, screen box (x0,y0,x1,y1, 0..1 of the whole picture) where it is seen '
              'first, colour_from and the objects drawing it. identify with points [[x,y]] (0..1 of this picture) '
              'says what is under a spot; with camera, one view from that angle. Nothing was changed.')
VIEWS_AREA = {'stage': 'its share of the game camera, what a player sees (of the raised view only for a surface the '
                       'game camera does not show): the backdrop is the id with the largest game-camera share, not '
                       'the largest in the raised view',
              'costume': 'the larger of its front and back shares'}


def view_area(views, kind):
    """An id's `area` in the three-view table, what it is ranked by. A stage: its share of the game camera
    (view 1, what a player sees), or of the raised view for a surface the game camera does not show (a
    platform top). Not the larger of the two: FD's side walls are 11.5% of the game camera and 64.8% of the
    raised view, which looks down on them, so they led the table and were recoloured as "the background"
    (2026-11-18) while the sky filled the game camera. A costume: the larger of front and back (both are
    seen in game)."""
    if kind == 'stage':
        return views[0] if views[0] or len(views) < 2 else views[1]
    return max(views[:2])


def _identify_views(item, plan, inventory, palette, kind, points, shade, grey, name, facts):
    """The identify map from three views in one picture (module doc), the session's state put back exactly.

    A stage: its game camera, a raised front three-quarter view (ground and platform tops), and a zoom on
    the window of the game view holding the most distinct small ids (fences, stars: what the game view is
    too small to number). A costume: front, back (seen in game) and a zoom on the head. A pan is measured
    first (_pan_scale) so the zoom lands on its window; without it the zoom view is left out.
    """
    viewer = item['viewer']
    names = VIEWS[kind]
    home = dict(viewer.camera)
    reference = _as_stored(plan, palette)
    second = ({**_camera_args(home), 'rot_x': home['rotX'] + RAISED['rot_x'], 'rot_y': home['rotY'] + RAISED['rot_y']}
              if kind == 'stage' else {**_camera_args(home), 'rot_y': home['rotY'] + 180.0})
    try:
        shades = [shade if shade is not None else _grab(viewer, None, home), _grab(viewer, second, home)]
        pan = _pan_scale(item, home, _rgb(shades[0]))
    finally:
        _restore_camera(viewer, home)
    zoom = {}

    def more(frames):                      # still painted: the zoom view is chosen from the first frame
        ids, size = _decoded(frames[0], reference)
        window = _busiest(ids) if kind == 'stage' else _head(ids)
        if window is None or not pan:
            return []
        zoom['camera'] = _zoom_camera(home, window, size, ids.shape, pan)
        zoom['ids'], zoom['window'] = ids, window
        return [zoom['camera']]
    frames, vertex_painted = _render_ids(item, plan, inventory, palette, [None, second], more)
    if zoom.get('camera'):
        try:
            shades.append(_grab(viewer, zoom['camera'], home))
        finally:
            _restore_camera(viewer, home)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:      # numpy lets go of the GIL: the views decode side by side
        later = list(pool.map(lambda frame: _decoded(frame, reference)[0], frames[1:]))
    decoded = [zoom['ids'] if 'ids' in zoom else _decoded(frames[0], reference)[0], *later]
    shown = names[:len(decoded)]
    keys = plan['keys']
    counts = [np.bincount(ids[ids >= 0].ravel(), minlength=len(keys)) if len(keys) else np.zeros(0, int)
              for ids in decoded]
    seen_ids = [k for v, k in enumerate(keys) if any(c[v] for c in counts)]
    unseen = [k for k in keys if k not in seen_ids]
    area = {k: [round(float(c[keys.index(k)]) / ids.size, 4) for c, ids in zip(counts, decoded)] for k in seen_ids}
    rows = sorted(({'id': k, 'area': view_area(area[k], kind), 'views': area[k], **facts(k)} for k in seen_ids),
                  key=lambda r: (-r['area'], -max(r['views'])))
    crops = []
    for n, ids in enumerate(decoded):
        if n == 2 and kind == 'stage':     # the zoomed window fills the frame's width: its band of rows
            band = min(ids.shape[0], round(zoom['window'][3] * ids.shape[1] / zoom['window'][2]))
            top, left, bottom, right = (ids.shape[0] - band) // 2, 0, (ids.shape[0] + band) // 2, ids.shape[1]
        else:
            top, left, bottom, right = _content(ids)
        crops.append((shown[n], ids[top:bottom, left:right], _shade(shades[n], ids.shape)[top:bottom, left:right]))
    # One colour per id across every panel: the panels side by side, apart, decide the colours together.
    tallest = max(crop.shape[0] for _, crop, _ in crops)
    colours = display_colours(np.concatenate([np.pad(crop, ((0, tallest - crop.shape[0]), (0, 1)), constant_values=-1)
                                              for _, crop, _ in crops], axis=1))
    too_small = []
    png, where, numbered, scale, at, picture = _compose_views(crops, keys, rows, list(shown), too_small, unseen,
                                                              colours, plan, points)
    files = [png]
    split = scale < MIN_PANEL_SCALE and len(crops) == 3
    if split:                              # too small to read as one: views 1+2, then the zoom on its own
        too_small = []
        png, where, numbered, scale, at, picture = _compose_views(crops[:2], keys, rows, list(shown), too_small,
                                                                  unseen, colours, plan, points)
        zoomed = []
        files = [png, _compose_views(crops[2:], keys, [r for r in rows if r['views'][2]], list(shown), zoomed,
                                     [], colours)[0]]
        too_small = [k for k in too_small if k in zoomed or not area[k][2]]
    height, width = picture.shape
    for row in rows:                       # the box where the picture first shows it, 0..1 of the whole picture
        value = keys.index(row['id'])
        for view in shown:
            if view not in where:
                continue
            x, y, w, h = where[view]
            ys, xs = np.nonzero(picture[y:y + h, x:x + w] == value)
            if len(xs):
                row['box'] = [round(float(x + xs.min()) / width, 3), round(float(y + ys.min()) / height, 3),
                              round(float(x + xs.max() + 1) / width, 3), round(float(y + ys.max() + 1) / height, 3)]
                break
    major = []
    for n in range(min(2, len(decoded))):
        identified = float(counts[n].sum()) / decoded[n].size if len(counts[n]) else 0.0
        major += [r['id'] for r in rows if r['id'] not in major and (
            r['views'][n] >= MAJOR_AREA or (identified and r['views'][n] >= MAJOR_SHARE * identified))]
    item['identify'] = _table(item, plan, inventory, major, rows)
    return {'reading': True,
            'files': [{**mod_files.register(data, name if n == 0 else name.replace('.png', ' (zoom).png')),
                       'preview_only': True} for n, data in enumerate(files)],
            'views': list(shown), 'surfaces': rows, 'major': major,
            **({'too_small': too_small} if too_small else {}),
            **({'not_visible': unseen} if unseen else {}),
            **({'at': [{k: v for k, v in a.items() if k != 'pixel'} for a in at]} if at else {}),
            'note': VIEWS_NOTE.format(area=VIEWS_AREA[kind]) + (' The zoom view is its own picture (the first was too small to read with it).'
                                  if split else '') + ('' if vertex_painted else VERTEX_NOTE)}


# --------------------------------------------------------------------------- #
# coverage: which surfaces a whole-stage theme has not reached yet             #
# --------------------------------------------------------------------------- #
# The identify views (game camera, raised front, zoom) barely see a stage's side and back
# faces: Dream Land's ends under the walkway were 0.09% of one view, so a theme that gave
# every MAJOR surface its part still saved them vanilla. Coverage therefore counts every
# surface the stage has (`units`), the major ones first: every identify id, plus the
# textures no id stands for (second layers, animation frames). Slots that are one texture
# to the renderer (`aliases`) count once, and an edit of one marks them all.
def _one_texture(viewer, inventory):
    """Groups of live texture indices the renderer writes as one (-> [[index, ...]]): the slots of one group
    whose encoded pixels are the same bytes (RenderJObj.ApplyTexture's own rule, so a picture under two
    palettes is one), and slots of two groups drawing one buffer in the file. Animation frames are not
    slots of the file's materials: the renderer never writes one with a texture it differs from."""
    import hashlib
    from shared.rendering.datprobe import gx_image_size
    live = {t['name']: t['index'] for t in viewer.textures if t.get('name') and not t.get('matAnim')}
    members = {}
    for obj in (inventory.objects if inventory else []):
        for t in obj.textures:
            index = live.get(t.get('name'))
            if index is None or t.get('buffer') is None:
                continue
            members.setdefault(('buffer', t['buffer']), set()).add(index)
            try:
                raw = inventory.dat.raw(t['buffer'], gx_image_size(t['format'], *t['size']))
            except Exception:
                continue
            group = t['name'].rpartition(' / ')[0]
            members.setdefault(('bytes', group, hashlib.sha1(raw).digest()), set()).add(index)
    parent = {}

    def find(i):
        while parent.setdefault(i, i) != i:
            i = parent[i]
        return i
    for indices in members.values():
        first, *rest = sorted(indices)
        for index in rest:
            parent[find(index)] = find(first)
    groups = {}
    for index in parent:
        groups.setdefault(find(index), []).append(index)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _table(item, plan, inventory, major, rows):
    """What the coverage line compares edits with (item['identify']); a stage's also lists every surface."""
    keys = list(plan['keys'])
    table = {'major': major, 'area': {r['id']: r['area'] for r in rows}, 'keys': keys,
             'drawn_by': {i: list(u) for i, u in plan['drawn_by'].items()}}
    if item.get('kind') != 'stage':
        return table
    textures = item['viewer'].textures
    # A texture whose objects are ids of their own is edited through them; any other texture no id names
    # (a second layer, an animation frame) is a surface of its own.
    split = plan.get('split') or set()
    table['units'] = keys + [t['index'] for t in textures if t['index'] not in keys and t['index'] not in split]
    table['frames'] = [t['index'] for t in textures if t.get('matAnim')]
    table['extra'] = [t['index'] for t in textures if t.get('extra')]
    table['aliases'] = _one_texture(item['viewer'], inventory)
    return table


def _alias_of(table):
    """{index: its alias group} (`_one_texture`)."""
    return {i: group for group in table.get('aliases') or () for i in group}


def mark_edited(item, textures=(), objects=(), every=False, clear=None):
    """Record what an edit changed, in identify ids (item['edited_ids']). `clear`: ids a reset put back (True: all)."""
    table = item.get('identify') or {}
    keys = set(table.get('units') or table.get('keys') or ())
    drawn_by = table.get('drawn_by') or {}
    aliases = _alias_of(table)
    edited = item.setdefault('edited_ids', set())
    if clear is True:
        edited.clear()
        return
    if every:
        edited.update(keys)
    for index in {a for i in textures for a in aliases.get(i, [i])}:
        if index in keys:
            edited.add(index)
        edited.update(o for o in drawn_by.get(index, ()) if o in keys)
    for object_id in objects:
        if object_id in keys:
            edited.add(object_id)
        edited.update(i for i, users in drawn_by.items() if object_id in users and i in keys)
    for key in {a for k in clear or () for a in aliases.get(k, [k])}:
        edited.discard(key)
        edited.difference_update(o for o in drawn_by.get(key, ()) if o in keys)


SURFACE_FIELDS = ('units', 'frames', 'extra', 'aliases')


def coverage_record(item):
    """The identify table and the edits so far as a resume record keeps them (JSON keys are strings)."""
    table = item.get('identify')
    if not table:
        return None
    return {'major': table['major'], 'area': [[k, v] for k, v in table['area'].items()], 'keys': table['keys'],
            'drawn_by': [[i, u] for i, u in table['drawn_by'].items()], 'edited': list(item.get('edited_ids') or ()),
            **{field: table[field] for field in SURFACE_FIELDS if field in table}}


def restore_coverage(item, record):
    if isinstance(record, dict) and record.get('major') is not None:
        item['identify'] = {'major': record['major'], 'area': {k: v for k, v in record['area']},
                            'keys': record['keys'], 'drawn_by': {i: u for i, u in record['drawn_by']},
                            **{field: record[field] for field in SURFACE_FIELDS if field in record}}
        item['edited_ids'] = set(record.get('edited') or ())


def coverage(item):
    """The line each edit of a whole-stage theme carries: the surfaces (identify) not edited yet, the major ones
    first, then every other one (module section note). -> str|None"""
    table = item.get('identify') or {}
    major = table.get('major') or []
    units = list(table.get('units') or major)
    if not units:
        return None
    edited = item.get('edited_ids') or set()
    area = table.get('area') or {}
    aliases = _alias_of(table)

    def shown(key):              # one unedited slot of a texture speaks for the rest: the one seen most
        group = [a for a in aliases.get(key, [key]) if a in units and a not in edited]
        return max(group, key=lambda a: (area.get(a, 0), -units.index(a))) == key
    left = [key for key in major if key not in edited]
    rest = [key for key in units if key not in edited and key not in major and shown(key)]
    if not left and not rest:
        return ('Every surface of the identify map has been edited.' if 'units' in table else
                'Every major surface of the identify map has been edited.')     # a record from before `units`
    line = []
    if left:
        line.append('Major surfaces not yet edited: ids ' + ', '.join(
            f'{label(k)} ({area.get(k, 0) * 100:.0f}%)' for k in left) + '.')
    if rest:
        keys, frames, extra = set(table.get('keys') or ()), set(table.get('frames') or ()), set(table.get('extra') or ())
        # (No major surfaces: the identify map read nothing, so nothing is known to be small.)
        kinds = [(' (small, or side and back faces the views barely show)' if major else '',
                  [k for k in rest if k in keys - extra]),
                 (' (second layers)', [k for k in rest if k not in keys | frames | extra]),
                 (' (animation frames)', [k for k in rest if k in frames]),
                 (' (parts only a stage animation shows)', [k for k in rest if k in extra])]
        line.append(('Also still vanilla' if left else 'Every major surface is edited; still vanilla' if major
                     else 'Still vanilla') + ': ids '
                    + '; '.join(', '.join(label(k) for k in ids) + words for words, ids in kinds if ids) + '.')
    return ' '.join(line) + (' A whole-stage theme gives each its part before reporting done; leave one vanilla only '
                             'on purpose and say which and why in the reply (identify and highlight show where they are).')
