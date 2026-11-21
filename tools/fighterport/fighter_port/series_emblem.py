"""A series emblem as a model: the flat shape Melee draws behind a fighter's damage, from the series' picture.

Melee's emblem is a flat model of triangles (the project keeps one a series: `assets/series/emblem_NNN.obj`, three
`v` lines a triangle; the game's own are about 6.6 wide and 4.6 high around the middle, z 0). A series added with
only a picture gets no model, and the game then shows a piece of the picture's shape (Duck Hunt's duck showed as a
head and half a wing). So the model is made here from the picture: its outline, holes and all, cut into triangles.

`triangles(image)` -> [((x, y), (x, y), (x, y)), ...] in the emblem's own lengths; `obj(triangles)` -> the file's
text; `covered(triangles, image)` -> how much of the picture's shape the triangles cover and how much they spill
(both as shares), which `write` checks before it writes.
"""
from __future__ import annotations

from pathlib import Path

WIDE, HIGH = 6.6, 4.6               # the box the game's own emblems sit in (Donkey Kong's: 6.75 by 4.61)
STEP = 4.0                          # a point on the outline at least every so many pixels of a 256 picture
SMOOTH = 0.5                        # the outline is straightened by at most this many pixels
LEAST = 0.985                       # the share of the shape the triangles must cover, and may spill at most 1 - it


def _mask(image):
    import numpy as np
    rgba = np.asarray(image.convert('RGBA'))
    alpha = rgba[..., 3]
    if alpha.min() == 255:          # no cut-out: the shape is what is bright
        alpha = rgba[..., :3].max(axis=2)
    return (alpha >= 128).astype('uint8')


def _shapes(mask):
    """The picture's shapes as polygons with their holes (pixel coordinates, y down)."""
    import cv2
    from shapely.geometry import Polygon
    contours, tree = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    if tree is None:
        return out
    tree = tree[0]
    for i, c in enumerate(contours):
        if tree[i][3] != -1 or len(c) < 3:          # a hole: taken with its outer shape
            continue
        holes, k = [], tree[i][2]
        while k != -1:
            if len(contours[k]) >= 3:
                holes.append([tuple(p[0]) for p in contours[k]])
            k = tree[k][0]
        shape = Polygon([tuple(p[0]) for p in c], holes).buffer(0)
        shape = shape.simplify(SMOOTH, preserve_topology=True)
        for part in getattr(shape, 'geoms', [shape]):
            if part.area >= 4.0:
                out.append(part)
    return out


def _cut(shape, step):
    """One polygon as triangles: every triangle of its outline's points that lies inside it."""
    from shapely.geometry import MultiPoint
    from shapely.ops import triangulate
    points = []
    for ring in [shape.exterior] + list(shape.interiors):
        n = max(3, int(ring.length / step))
        points += [ring.interpolate(i / n, normalized=True) for i in range(n)]
        points += [type(points[0])(xy) for xy in ring.coords[:-1]]
    return [tuple(t.exterior.coords[:3]) for t in triangulate(MultiPoint(points))
            if shape.contains(t.representative_point())]


def triangles(image):
    mask = _mask(image)
    if not mask.any():
        raise ValueError('the picture has no shape')
    step = STEP * max(mask.shape) / 256.0
    cut = [t for shape in _shapes(mask) for t in _cut(shape, step)]
    ys, xs = mask.nonzero()
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    scale = min(WIDE / (x1 - x0), HIGH / (y1 - y0))
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    out = []
    for t in cut:
        (x1, y1), (x2, y2), (x3, y3) = t = tuple(((x - mx) * scale, (my - y) * scale) for x, y in t)
        # every triangle of the game's own emblems winds clockwise (seen from the front): one that does not
        # would be drawn from behind only
        out.append(t if (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1) < 0 else (t[0], t[2], t[1]))
    return out


def covered(tris, image):
    """(share of the picture's shape under the triangles, share of the triangles outside the shape)."""
    import numpy as np
    from PIL import Image, ImageDraw
    mask = _mask(image)
    ys, xs = mask.nonzero()
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    scale = min(WIDE / (x1 - x0), HIGH / (y1 - y0))
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    canvas = Image.new('L', (mask.shape[1], mask.shape[0]), 0)
    draw = ImageDraw.Draw(canvas)
    for t in tris:
        draw.polygon([(x / scale + mx, my - y / scale) for x, y in t], fill=1)
    drawn = np.asarray(canvas).astype(bool)
    shape = mask.astype(bool)
    return (drawn & shape).sum() / max(1, shape.sum()), (drawn & ~shape).sum() / max(1, drawn.sum())


def obj(tris) -> str:
    lines = []
    for t in tris:
        lines += [f'v {x:.7g} {y:.7g} 0' for x, y in t]
    lines += [f'f {3 * i + 1} {3 * i + 2} {3 * i + 3}' for i in range(len(tris))]
    return '\n'.join(lines) + '\n'


def write(image, path) -> dict:
    """The picture's shape as an emblem model at `path`. -> dict(triangles, covered, spilled, larger)

    An outline is traced through the middles of the edge pixels, so a line one or two pixels wide (Xenoblade's
    emblem: the Monado's rings) comes out with next to no width and the cut covers too little (97.2% of it). Then the
    picture is read again at twice its size (each pixel four), which gives such a line its width; the emblem is the
    same size either way (`triangles` fits the shape to the game's box). `larger` says which reading was kept."""
    from PIL import Image
    tries = [(1, image), (2, image.resize((image.width * 2, image.height * 2), Image.NEAREST))]
    for larger, picture in tries:
        tris = triangles(picture)
        inside, spill = covered(tris, picture)          # (measured at the size it was read at)
        if inside >= LEAST and spill <= 1 - LEAST + 0.02:
            break
    else:
        raise ValueError(f'the emblem model covers {inside:.1%} of the picture and spills {spill:.1%}')
    Path(path).write_text(obj(tris), 'utf-8')
    return dict(triangles=len(tris), covered=round(float(inside), 4), spilled=round(float(spill), 4), larger=larger)
