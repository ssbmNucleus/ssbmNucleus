"""What a Melee particle's one flat picture cannot take as it is, made into one: an Ultimate emitter's several
pictures joined into one picture (`join`), and the 3D shape some emitters draw their picture on flattened into a
picture as Melee's camera sees it (`flatten`). `own_effects.Plan` uses both; nothing here knows Melee's files.

Nothing here was seen in the game when it was written. The constants marked READING are choices where the source
is silent; each can be changed in one place.

The camera. Melee looks at a fighter from the side. In an effect's own space +Z is ahead and +Y up (see
`own_effects`), so with the fighter facing right ahead is to the right on the screen, up is up, and the effect's
+X points away from the camera. A picture made here is that view: across it runs the effect's z, down it the
effect's -y. Facing left, a particle given off once is drawn mirrored by the game (its picture is flipped
across), which is the view from that side; a particle held by a joint is not, and shows the same picture.
"""
from __future__ import annotations

import math

import numpy as np

# The game looks a little down on the fighters. READING: 8 degrees, so that a ring laid on the ground shows as a
# thin ellipse and not as a line. 0: straight from the side.
CAMERA_PITCH_DEGREES = 8.0
# A shape is drawn at this many pixels a side and then made smaller with the rest of the file's pictures (which
# smooths its edges).
RENDER_SIDE = 128
# A picture that is grey and has no see-through-ness of its own is a mask: what is joined is its brightness, as
# see-through-ness, and its colour is white. READING, the one `own_effects.OPAQUE_GREY_IS_MASK` makes for a picture
# drawn alone (Squirtle's Withdraw: its gradient, white about a black arch, is opaque).
GREY_IS_MASK = True
GREY_TOLERANCE, GREY_SHARE = 12, 0.995
# A picture's outermost ring of pixels does not count when asking whether it has see-through-ness of its own (it is
# where a picture is cut at its edge). ef_cmn_grade00, the white-to-black gradient Ultimate's flares draw on their
# disc (cmn_flare1), is in all seven effect files read (five fighters), opaque but for that ring (219 of 255, 6% of
# its pixels); read as a picture with an alpha of its own, every flare drawn with it normally was flattened into a
# dark disc (Incineroar's Revenge darkened half the screen; Wolf's reflector, Duck Hunt's can, Charizard's Fly the
# same). It is asked only of pictures joined or flattened here: a picture drawn alone is stored by its own alpha as
# before (`own_effects.picture_format`; asked there too, it would also turn Duck Hunt's clay shards,
# ef_duckhunt_claybreak00, clear ring and opaque inside, into a mask). No other of the 299 grey pictures of the
# seven is read differently by it.
BORDER_PIXELS = 1
# A joined picture "draws a square" when this share of its pixels are seen (alpha, times brightness when it is
# added) at SEEN or more, and as much of its outer band (EDGE of the side); it "draws a dark box" when it is laid
# over the fighter normally and at least DARK of it, and DARK_OF_SEEN of what is seen of it, is seen and dark
# (under DARK_BRIGHTNESS). Either gets a stand-in (`stand_in`). (Squirtle's Withdraw water wall drawn by its first
# picture alone: 39% of it seen and dark; with its three pictures joined, 17%, more than half of what is seen.)
SEEN, SQUARE_SHARE, EDGE = 0.25, 0.6, 0.125
DARK, DARK_OF_SEEN, DARK_BRIGHTNESS = 0.1, 0.4, 0.35

# the kinds of laying a particle (`echo_ultimate.effects.draw_type`) as the camera sees them: the shape's own XY
# plane toward the camera, or laid in the effect's space and seen from the side. READING for the two that lay the
# shape along its speed: its XY plane is toward the camera (Greninja's kunai, Duck Hunt's gunman's smoke and the
# rapid jab's lines are flat in XY, and from the side they would not be seen at all).
FACING_CAMERA = ('billboard', 'complex_billboard', 'y_billboard', 'velocity_look', 'velocity_look_polygon')
POLYGONS = ('polygon_xy', 'polygon_xz')
BY_SPEED = ('velocity_look', 'velocity_look_polygon')
# A shape seen thinner than this many pixels of the picture across or up is drawn this thick (a beam seen from
# the side would fall between the pixels).
LEAST_PIXELS = 2.0


def _floats(image):
    return np.asarray(image.convert('RGBA'), dtype=np.float32) / 255.0


def _image(pixels):
    from PIL import Image
    return Image.fromarray((np.clip(pixels, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), 'RGBA')


def opaque(alpha, full=1.0):
    """Whether a picture's alpha (h x w) is `full` everywhere but its outermost ring of pixels (BORDER_PIXELS)."""
    b = BORDER_PIXELS if min(alpha.shape[:2]) > 2 * BORDER_PIXELS else 0
    inner = alpha[b:alpha.shape[0] - b, b:alpha.shape[1] - b]
    return bool(inner.size) and float(inner.min()) >= full


def is_mask(pixels):
    """Whether a picture (floats, h x w x 4) is grey with no see-through-ness of its own (see GREY_IS_MASK,
    BORDER_PIXELS)."""
    if not GREY_IS_MASK or not opaque(pixels[..., 3]):
        return False
    spread = (pixels[..., :3].max(axis=-1) - pixels[..., :3].min(axis=-1)) * 255.0
    return float(np.mean(spread <= GREY_TOLERANCE)) >= GREY_SHARE


def _as_joined(pixels):
    """A picture as it is joined: a mask's brightness as its alpha (its ring too: BORDER_PIXELS) and white as its
    colour; any other as it is."""
    if is_mask(pixels):
        out = np.ones_like(pixels)
        out[..., 3] = pixels[..., 0]
        return out
    return pixels


def _resized(pixels, width, height):
    from PIL import Image
    if pixels.shape[1] == width and pixels.shape[0] == height:
        return pixels
    return np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(pixels[..., i])).resize((width, height), Image.BILINEAR))
                     for i in range(4)], axis=-1)


def _apply(how, a, b):
    if how == 'add':
        return np.clip(a + b, 0.0, 1.0)
    if how == 'subtract':
        return np.clip(a - b, 0.0, 1.0)
    return a * b                                    # multiply, and what is not known (said by the caller)


def join(images, grid=(1, 1), colour=('multiply', 'multiply'), alpha=('multiply', 'multiply')):
    """Several pictures (PIL) as one: the first cut into its grid of frames, each later picture stretched over
    each frame and joined to what the ones before it make, its colour by `colour[k]` and its alpha by `alpha[k]`
    (`echo_ultimate.effects.combiner`). A mask (GREY_IS_MASK) joins by its brightness. -> PIL picture of the first's
    size, its frames where the first's are."""
    first = _as_joined(_floats(images[0]))
    across, down = max(1, int(grid[0])), max(1, int(grid[1]))
    width, height = first.shape[1] // across, first.shape[0] // down
    out = first.copy()
    others = [_as_joined(_floats(image)) for image in images[1:]]
    for row in range(down):
        for column in range(across):
            cell = out[row * height:(row + 1) * height, column * width:(column + 1) * width]
            for k, other in enumerate(others):
                other = _resized(other, width, height)
                cell[..., :3] = _apply(colour[min(k, len(colour) - 1)], cell[..., :3], other[..., :3])
                cell[..., 3] = _apply(alpha[min(k, len(alpha) - 1)], cell[..., 3], other[..., 3])
    return _image(out)


def seen(pixels, additive):
    """How much of each pixel shows: its alpha, times its brightness when it is added to what is behind it."""
    return pixels[..., 3] * (pixels[..., :3].max(axis=-1) if additive else 1.0)


def draws_square(image, additive=False):
    """Whether a picture shows as a square or a dark box (see SEEN, DARK), and why: (None, '') when it does not,
    else ('square' or 'dark', words)."""
    pixels = _floats(image)
    shown = seen(pixels, additive)
    h, w = shown.shape
    band = np.ones_like(shown, dtype=bool)
    eh, ew = max(1, int(round(h * EDGE))), max(1, int(round(w * EDGE)))
    band[eh:h - eh, ew:w - ew] = False
    share, edge = float(np.mean(shown >= SEEN)), float(np.mean(shown[band] >= SEEN))
    if share >= SQUARE_SHARE and edge >= SQUARE_SHARE:
        return 'square', f'{share:.0%} of it is seen, {edge:.0%} of its edge'
    if not additive:
        dark = float(np.mean((shown >= SEEN) & (pixels[..., :3].max(axis=-1) < DARK_BRIGHTNESS)))
        if dark >= DARK and dark >= DARK_OF_SEEN * share:
            return 'dark', f'{dark:.0%} of it is seen and dark, of {share:.0%} seen'
    return None, ''


def stand_in(image, grid=(1, 1), cut_round=True):
    """A picture that is not a square nor a dark box, for one that draws one: see-through where it is dark (its
    alpha times its brightness; its colour at full brightness) and, for a square (`cut_round`), cut round in each
    frame (its alpha fades from half the way out to the edge)."""
    pixels = _floats(image)
    across, down = max(1, int(grid[0])), max(1, int(grid[1]))
    height, width = pixels.shape[0] // down, pixels.shape[1] // across
    y, x = np.mgrid[0:height, 0:width]
    r = np.hypot((x + 0.5) / width * 2.0 - 1.0, (y + 0.5) / height * 2.0 - 1.0)
    t = np.clip((1.0 - r) / 0.5, 0.0, 1.0)
    round_ = t * t * (3.0 - 2.0 * t)
    bright = pixels[..., :3].max(axis=-1)
    out = pixels.copy()
    out[..., 3] = pixels[..., 3] * bright
    out[..., :3] = np.where(bright[..., None] > 1e-6, pixels[..., :3] / np.maximum(bright[..., None], 1e-6), 1.0)
    for row in range(down):
        for column in range(across):
            if cut_round:
                out[row * height:(row + 1) * height, column * width:(column + 1) * width, 3] *= round_
    return _image(out)


# ---- a 3D shape as a flat picture ----

def turned(points, turn):
    """Points (n, 3) turned about x, then y, then z (radians): `own_effects._turned` for many points."""
    p = np.asarray(points, dtype=np.float64).copy()
    rx, ry, rz = (float(t) for t in turn)
    c, s = math.cos(rx), math.sin(rx)
    p[:, 1], p[:, 2] = p[:, 1] * c - p[:, 2] * s, p[:, 1] * s + p[:, 2] * c
    c, s = math.cos(ry), math.sin(ry)
    p[:, 0], p[:, 2] = p[:, 0] * c + p[:, 2] * s, -p[:, 0] * s + p[:, 2] * c
    c, s = math.cos(rz), math.sin(rz)
    p[:, 0], p[:, 1] = p[:, 0] * c - p[:, 1] * s, p[:, 0] * s + p[:, 1] * c
    return p


def view(positions, draw, size=(1.0, 1.0, 1.0), turn=(0.0, 0.0, 0.0), call_turn=(0.0, 0.0, 0.0)):
    """Where a shape's points fall on the screen: (across, up, how far from the camera), each (n,), in the effect's
    units, the effect's origin at (0, 0).

    The shape is sized (`size`: x, y, z), laid as its kind says (`draw`: 'polygon_xz' lays its XY plane flat, face
    up), turned by the emitter's own turn and then the script call's (radians), and seen: a kind that faces the
    camera shows its own x across and y up; any other is seen from the side (z across, y up) with the camera's
    pitch (CAMERA_PITCH_DEGREES). The call's turn is given only to a shape that is not turned to face the camera."""
    p = np.asarray(positions, dtype=np.float64) * np.asarray(size, dtype=np.float64)
    if draw == 'polygon_xz':
        p = turned(p, (-math.pi / 2.0, 0.0, 0.0))           # its +z (the way its face looks) to up
    p = turned(p, turn)
    if draw in FACING_CAMERA:
        return p[:, 0], p[:, 1], -p[:, 2]
    p = turned(p, call_turn)
    pitch = math.radians(CAMERA_PITCH_DEGREES)
    up = p[:, 1] * math.cos(pitch) + p[:, 0] * math.sin(pitch)
    far = p[:, 0] * math.cos(pitch) - p[:, 1] * math.sin(pitch)
    return p[:, 2], up, far


def reach(across, up):
    """Half the side of the square about the origin that holds every point."""
    return float(max(np.abs(across).max(initial=0.0), np.abs(up).max(initial=0.0)))


def _sample(texture, u, v):
    """A picture (h, w, 4 floats) read at UVs that repeat, between its pixels."""
    h, w = texture.shape[:2]
    x = (u - np.floor(u)) * w - 0.5
    y = (v - np.floor(v)) * h - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    x0, x1, y0, y1 = x0 % w, (x0 + 1) % w, y0 % h, (y0 + 1) % h
    top = texture[y0, x0] * (1 - fx) + texture[y0, x1] * fx
    bottom = texture[y1, x0] * (1 - fx) + texture[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def flatten(shape, picture, draw, half, size=(1.0, 1.0, 1.0), turn=(0.0, 0.0, 0.0), call_turn=(0.0, 0.0, 0.0),
            additive=False, side=RENDER_SIDE):
    """A shape (`echo_ultimate.effects.shapes` gives one) with `picture` (PIL) on it, as the camera sees it (`view`),
    in a square picture `side` pixels a side that holds `half` effect units each way from the origin. Its triangles
    are drawn both sides, the farthest first; their colour and alpha are the picture's times the shape's own
    vertex colour. Added (`additive`): they add up; else each is laid over the ones behind it. -> PIL picture,
    its alpha what Melee's blending needs (added: colour times alpha is what each pixel adds, and the two are
    equal where it is grey, so `own_effects.picture_format` stores it as I8, in half the bytes)."""
    across, up, far = view(shape['positions'], draw, size, turn, call_turn)
    px = (across / max(half, 1e-9) + 1.0) * 0.5 * side
    py = (1.0 - up / max(half, 1e-9)) * 0.5 * side
    for p in (px, py):                              # (LEAST_PIXELS)
        span = float(np.ptp(p)) if len(p) else 0.0
        if span < LEAST_PIXELS:
            middle = (float(p.max()) + float(p.min())) / 2.0
            p[:] = middle + (p - middle) * (LEAST_PIXELS / max(span, 1e-9)) if span > 1e-9 else p
    texture = _floats(picture)
    uv, colours, triangles = shape['uvs'], shape['colours'], np.asarray(shape['triangles'])
    colour = np.zeros((side, side, 3))
    cover = np.zeros((side, side))
    order = np.argsort(-far[triangles].mean(axis=1), kind='stable') if len(triangles) else []
    for t in order:
        tri = triangles[t]
        xs, ys = px[tri], py[tri]
        x0, x1 = max(int(math.floor(xs.min())), 0), min(int(math.ceil(xs.max())), side - 1)
        y0, y1 = max(int(math.floor(ys.min())), 0), min(int(math.ceil(ys.max())), side - 1)
        if x0 > x1 or y0 > y1:
            continue
        denom = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(denom) < 1e-9:
            continue
        gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1] + 0.5
        gy, gx = gy + 1.3e-5, gx + 2.9e-5               # (off the centre: an edge two share is not drawn twice)
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / denom
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / denom
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        if not inside.any():
            continue
        u = w0 * uv[tri[0], 0] + w1 * uv[tri[1], 0] + w2 * uv[tri[2], 0]
        v = w0 * uv[tri[0], 1] + w1 * uv[tri[1], 1] + w2 * uv[tri[2], 1]
        tint = (w0[..., None] * colours[tri[0]] + w1[..., None] * colours[tri[1]] + w2[..., None] * colours[tri[2]])
        rgba = _sample(texture, u, v) * tint
        a = np.clip(rgba[..., 3], 0.0, 1.0) * inside
        c = np.clip(rgba[..., :3], 0.0, 1.0)
        region = colour[y0:y1 + 1, x0:x1 + 1]
        if additive:
            region += c * a[..., None]
        else:
            region *= (1.0 - a[..., None])
            region += c * a[..., None]
            cover[y0:y1 + 1, x0:x1 + 1] = a + cover[y0:y1 + 1, x0:x1 + 1] * (1.0 - a)
    out = np.zeros((side, side, 4))
    if additive:                                    # colour times alpha is what it adds; each is its square root
        alpha = np.sqrt(np.clip(colour.max(axis=-1), 0.0, 1.0))    # where it is grey (so one byte a pixel: I8)
    else:
        alpha = cover
    out[..., :3] = np.where(alpha[..., None] > 1e-6, colour / np.maximum(alpha[..., None], 1e-6), 0.0)
    out[..., 3] = alpha
    return _image(out)
