"""The game's own match camera (cm/camera.c, Camera_80029CF8), and what it can ever show of a flat background.

The pack's bakes were laid out for the harness's still framing (a 40 degree lens, nearly level). A real match never uses it: the lens is 30 degrees
and the camera looks down 5 to 17 degrees, dollying between the stage's nearest and farthest distance. So what play shows of a flat picture is a
smaller window, lower down, and it reaches further out at the bottom than the still framing's overscan allowed for.

Units: world (file x stage scale). cam = the stage's StageCameraInfo as match_probe.py prints it (cam_info), g = the camera's constants."""
import math

import numpy as np

G = dict(x8=-30.0, pitch_hi=5.0, pitch_lo=-7.0, pan_hi=17.5, pan_lo=-17.5, blend_lo=0.0, blend_hi=0.0682, len_lo=60.0, len_hi=120.0)   # cm_803BCCA0 +8 .. +0x28
ASPECT = 1.2173
FOV = 30.0
RAD = math.pi / 180


def camera(box, cam, fov=None, depth_now=None):
    """The camera the game settles on for a bounds box (x_min, y_min, x_max, y_max): eye and interest, world units."""
    x0, y0, x1, y1 = box
    fov = fov or cam.get('fov', FOV)      # the lens is the stage's own: 30 degrees on five of the legal stages, 20 on Yoshi's Story
    ox, oy = cam['x_offset'], cam['y_offset']
    ln = max(x1 - x0, y1 - y0)
    blend = G['blend_hi'] if ln > G['len_hi'] else G['blend_lo'] if ln < G['len_lo'] else G['blend_lo'] + (G['blend_hi'] - G['blend_lo']) * (ln - G['len_lo']) / (G['len_hi'] - G['len_lo'])
    pitch = -(((y0 - oy) + (y1 - oy)) * (0.5 - blend) + oy + G['x8']) * cam['x24']
    pitch = (min(max(pitch, G['pitch_lo']), G['pitch_hi']) + cam['pan_degrees']) * RAD
    half = 0.5 * fov * RAD
    tu, td = math.tan(half + pitch), math.tan(half - pitch)
    vfd = (y1 - y0) / (tu + td)
    voff = vfd * math.tan(pitch)
    iy = voff + (y1 - vfd * tu)
    pan = -((0.5 * (x0 + x1) - ox) * cam['x20'])
    pan = min(max(pan, G['pan_lo']), G['pan_hi']) * RAD
    tr, tl = ASPECT * math.tan(half - pan), ASPECT * math.tan(half + pan)
    hfd = (x1 - x0) / (tr + tl)
    hoff = ASPECT * hfd * math.tan(pan)
    ix = x1 - hfd * tr - hoff
    d = min(max(max(vfd, hfd), cam['zoom_rate']), cam['max_depth'])
    return np.array([ix + hoff, iy - voff, d]), np.array([ix, iy, 0.0])


def corners(eye, interest, fov=FOV):
    """Unit-depth rays through the four screen corners and the centre, world space."""
    f = interest - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1.0, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    ty = math.tan(0.5 * fov * RAD)
    tx = ty * ASPECT
    return [f + sx * tx * r + sy * ty * u for sx, sy in ((-1, 1), (1, 1), (1, -1), (-1, -1), (0, 0))]


class Board:
    """A flat picture square to a bake camera: eye and target in world units, standing depth from the eye along its axis."""

    def __init__(self, eye, target, depth):
        self.eye = np.array(eye, float)
        self.f = np.array(target, float) - self.eye
        self.f /= np.linalg.norm(self.f)
        self.r = np.array([1.0, 0, 0])
        self.u = np.cross(self.r, self.f)
        self.depth = depth

    def hit(self, eye, ray):
        """Where a ray lands on the board, in the bake camera's tangent units (u right, v up; the bake's own axis is 0, 0)."""
        t = (self.depth - np.dot(eye - self.eye, self.f)) / np.dot(ray, self.f)
        rel = eye + t * ray - self.eye
        return np.dot(rel, self.r) / self.depth, np.dot(rel, self.u) / self.depth

    def window(self, box, cam):
        """What the settled camera for a bounds box shows of the board: (u_min, v_min, u_max, v_max) and the magnification of the picture on screen,
        as the board's tangent half-height that fills the screen."""
        eye, interest = camera(box, cam)
        pts = [self.hit(eye, ray) for ray in corners(eye, interest, cam.get('fov', FOV))]
        us, vs = [p[0] for p in pts[:4]], [p[1] for p in pts[:4]]
        return min(us), min(vs), max(us), max(vs)


def boxes(cam, n=13, least=30.0, x_reach=None, y_span=None):
    """Bounds boxes the game can hand its camera: any rectangle inside the stage's camera bounds, the bottom pushed down as the game does
    (10 plus up to 390 as the camera pulls back). x_reach and y_span narrow it to where fighters usually are."""
    left, right = cam['left'] + cam['x_offset'], cam['right'] + cam['x_offset']
    bottom, top = cam['bottom'] + cam['y_offset'], cam['top'] + cam['y_offset']
    if x_reach is not None:
        left, right = max(left, -x_reach), min(right, x_reach)
    if y_span is not None:
        bottom, top = max(bottom, y_span[0]), min(top, y_span[1])
    xs, ys = np.linspace(left, right, n), np.linspace(bottom, top, n)
    for a in range(n):
        for b in range(a + 1, n):
            if xs[b] - xs[a] < least:
                continue
            for c in range(n):
                for e in range(c + 1, n):
                    if ys[e] - ys[c] < least:
                        continue
                    box = [xs[a], ys[c], xs[b], ys[e]]
                    d = cam['zoom_rate']
                    for _ in range(4):      # the push depends on how far back the camera stands, which depends on the push
                        zf = min(max((d - 80.0) / 4920.0, 0.0), 1.0)
                        pushed = [box[0], box[1] - (390.0 * zf + 10.0), box[2], box[3]]
                        d = camera(pushed, cam)[0][2]
                    yield pushed


def envelope(board, cam, **kw):
    w = np.array([board.window(b, cam) for b in boxes(cam, **kw)])
    return dict(u=(float(w[:, 0].min()), float(w[:, 2].max())), v=(float(w[:, 1].min()), float(w[:, 3].max())), n=len(w),
                width=(float(np.median(w[:, 2] - w[:, 0])), float((w[:, 2] - w[:, 0]).min())))
