"""Compose each side-by-side pair: the real game frame (<shots>/<id>.png, from
capture.py) next to Watch Lite's picture of the same replay frame, painted with
a fixed camera matched to the game's, plus a close crop around a small subject.

    app/venv/Scripts/python.exe -B tools/liteaudit/sidebyside/compose.py --targets <run>/targets-ext.json
        --shots <run>/shots --pairs <run>/pairs --lib <paintlib.js> [--cache DIR] [--only id,id] [--chrome EXE]

Geometry: the game camera (CObj view matrix + perspective fov/aspect, read from
RAM at the captured frame) projects world points into the shot. Melee projects
at aspect 1.2173 (73:60) and Dolphin shows the 640x480 frame at 4:3, so the shot
is first resampled to square world pixels (width = height x 1.2173); then one
world unit is the same number of pixels across and down, as in Watch Lite.
Output: <pairs>/NN-<id>.png, <pairs>/index.json; Watch Lite renders in wl-<pairs>/.
"""
import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CACHE = REPO / 'app' / 'scratch' / 'liteaudit' / 'sidebyside' / 'cache'
CROP = 420           # crop panel edge, px
GAP = 12


def font(size, bold=False):
    for name in (('arialbd.ttf' if bold else 'arial.ttf'), 'segoeui.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


class Projector:
    def __init__(self, cam, width, height):
        self.m = cam['view_mtx']
        self.start = tuple(cam.get('interest') or (0.0, 0.0))[:2]
        fov, self.aspect = cam['fov_aspect']
        self.cot = 1 / math.tan(math.radians(fov) / 2)
        self.w, self.h = width, height

    def __call__(self, x, y, z=0.0):
        m = self.m
        vx = m[0] * x + m[1] * y + m[2] * z + m[3]
        vy = m[4] * x + m[5] * y + m[6] * z + m[7]
        vz = m[8] * x + m[9] * y + m[10] * z + m[11]
        xn = self.cot / self.aspect * vx / -vz
        yn = self.cot * vy / -vz
        return ((xn + 1) / 2 * self.w, (1 - yn) / 2 * self.h)

    def scale_at(self, x, y):
        """px per world unit at (x, y) on the z=0 plane (down, across)."""
        a, b, c = self(x, y), self(x, y + 1), self(x + 1, y)
        return a[1] - b[1], c[0] - a[0]

    def world_at(self, px, py):
        """The z=0 world point that lands on pixel (px, py) (Newton)."""
        x, y = self.start                  # Newton from the camera's look-at point
        for _ in range(30):
            p = self(x, y)
            sy, sx = self.scale_at(x, y)
            x += (px - p[0]) / sx
            y -= (py - p[1]) / sy
        return x, y


def subject_name(t):
    s = t.get('subject') or {}
    if 'port' in s:
        p = next((q for q in t['ports'] if q['port'] == s['port']), None)
        return f"player {s['port'] + 1}" + (f" (state {p['state']})" if p else '')
    if 'item' in s:
        return f"item kind {s['item']}"
    return ''


def render_wl(job, out, lib, cache, chrome=None):
    cmd = ['node', str(HERE / 'wlshot.mjs'), str(job), str(out), '--lib', str(lib), '--cache', str(cache),
           '--python', sys.executable] + (['--chrome', chrome] if chrome else [])
    r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'wlshot failed: {(r.stderr or r.stdout).strip()[-600:]}')


def compose(t, n, shots, pairs, work, lib, cache, chrome, log):
    meta = json.loads((shots / f"{t['id']}.json").read_text())
    if not meta.get('ok'):
        log(f"{t['id']}: no game shot ({meta.get('error')})")
        return None
    t0 = time.time()
    game = Image.open(shots / f"{t['id']}.png").convert('RGB')
    cam = meta['camera']
    H = game.height
    W = round(H * cam['fov_aspect'][1])
    if game.width > W + 4:
        # Dolphin already shows the 73:60 picture, pillarboxed: keep its centre
        x0 = (game.width - W) // 2
        game = game.crop((x0, 0, x0 + W, H))
        note = "game shot shown at the game's own 73:60 aspect (square world pixels)"
    else:
        game = game.resize((W, H), Image.LANCZOS)
        note = "game shot resampled from 4:3 to the game's 73:60 aspect (square world pixels)"
    proj = Projector(cam, W, H)
    cx, cy = proj.world_at(W / 2, H / 2)
    S, Sx = proj.scale_at(cx, cy)
    views = [{'cx': cx, 'cy': cy, 'S': S, 'w': W, 'h': H}]
    crop = None
    if t.get('point'):
        px, py = t['point']
        shine = t.get('type') == 'shine'
        item = 'item' in (t.get('subject') or {})
        dust = t.get('type') == 'dust'
        R = 13 if shine else 16 if item else 20 if dust else 24
        sP, _ = proj.scale_at(px, py)
        gx, gy = proj(px, py)
        box = (gx - R * sP, gy - R * sP, gx + R * sP, gy + R * sP)
        # a close-up only when the subject is small in the full frame
        if shine or item or dust or 2 * R * sP < 0.45 * H:
            crop = (box, R)
            views.append({'cx': px, 'cy': py, 'S': CROP / (2 * R), 'w': CROP, 'h': CROP})
    job = work / f"{t['id']}.json"
    job.write_text(json.dumps({'slp': t['slp'], 'frame': t['frame'], 'views': views}))
    out = work / f"{t['id']}.png"
    render_wl(job, out, lib, cache, chrome)
    wl = Image.open(out).convert('RGB')
    wl_full = wl.crop((0, 0, W, H))
    al = meta.get('alignment') or {}
    exact = meta.get('match_frame') == t['frame'] and al.get('frame') == t['frame']
    # canvas
    head_h, col_h = 92, 26
    rows_h = head_h + col_h + H + (GAP + col_h + CROP if crop else 0) + GAP
    canvas = Image.new('RGB', (2 * W + 3 * GAP, rows_h), (18, 20, 28))
    dr = ImageDraw.Draw(canvas)
    f_big, f_mid, f_small = font(22, True), font(17), font(15)
    dr.text((GAP, 8), f"{n:02d}  {t['label']}", font=f_big, fill=(240, 240, 240))
    dr.text((GAP, 38), f"replay {Path(t['slp']).name}   frame {t['frame']}   stage {t['stage']}"
            + (f"   subject: {subject_name(t)}" if subject_name(t) else ''), font=f_mid, fill=(200, 205, 215))
    check = (f"frame check: Dolphin frozen on match frame {meta['match_frame']}, best replay match {al.get('frame')} "
             f"(cost {al.get('cost')})")
    dr.text((GAP, 62), (check if exact else 'FRAME CHECK FAILED: ' + check) + f"; {note}", font=f_small,
            fill=(150, 160, 175) if exact else (255, 90, 90))
    y = head_h
    dr.text((GAP, y + 3), 'Melee (Slippi playback Dolphin)', font=f_mid, fill=(255, 210, 120))
    dr.text((2 * GAP + W, y + 3), 'Watch Lite (same frame, camera matched to the game)', font=f_mid, fill=(130, 210, 255))
    y += col_h
    canvas.paste(game, (GAP, y))
    canvas.paste(wl_full, (2 * GAP + W, y))
    if crop:
        (x0, y0, x1, y1), R = crop
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, W - 1), min(y1, H - 1)
        if cx0 < cx1 and cy0 < cy1:                  # the box, clipped to each panel
            dr.rectangle((GAP + cx0, y + cy0, GAP + cx1, y + cy1), outline=(255, 210, 120), width=2)
            dr.rectangle((2 * GAP + W + cx0, y + cy0, 2 * GAP + W + cx1, y + cy1), outline=(130, 210, 255), width=2)
        y += H + GAP
        gx, gy = (x0 + x1) / 2, (y0 + y1) / 2
        off = '' if 0 <= gx < W and 0 <= gy < H else '  (the subject is outside the game camera view on this frame)'
        dr.text((GAP, y + 3), f"close-up: the boxed {2 * R} x {2 * R} world units around the subject, both sides{off}",
                font=f_mid, fill=(200, 205, 215))
        y += col_h
        g = game.crop(tuple(round(v) for v in (x0, y0, x1, y1))).resize((CROP, CROP), Image.LANCZOS)
        w = wl.crop((0, H, CROP, H + CROP))
        left = (2 * W + 3 * GAP) // 2 - CROP - GAP // 2
        canvas.paste(g, (left, y))
        canvas.paste(w, (left + CROP + GAP, y))
    dest = pairs / f"{n:02d}-{t['id']}.png"
    canvas.save(dest)
    secs = round(time.time() - t0, 1)
    log(f"{t['id']}: wrote {dest.name} ({secs} s compose, {meta.get('seconds_total')} s capture; horizontal/vertical px per unit {Sx:.3f}/{S:.3f})"
        + ('' if exact else '  FRAME CHECK FAILED'))
    return {'n': n, 'id': t['id'], 'type': t.get('type'), 'png': dest.name, 'shows': t['label'], 'replay': t['slp'],
            'frame': t['frame'], 'stage': t['stage'], 'subject': subject_name(t), 'frame_exact': exact,
            'frame_check': al, 'capture_s': meta.get('seconds_total'), 'compose_s': secs}


def compose_all(targets, shots, pairs, lib, cache=CACHE, chrome=None, only=None, log=print):
    """Compose every captured target; writes <pairs>/index.json (unless `only`) and returns its rows."""
    shots, pairs = Path(shots), Path(pairs).resolve()
    work = pairs.parent / ('wl-' + pairs.name)
    pairs.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, t in enumerate(targets, 1):
        if only and t['id'] not in only:
            continue
        if not (shots / f"{t['id']}.json").exists():
            log(f"{t['id']}: not captured")
            continue
        try:
            r = compose(t, n, shots, pairs, work, lib, cache, chrome, log)
            if r:
                rows.append(r)
        except Exception as e:                    # noqa: BLE001
            log(f"{t['id']}: compose FAILED {e!r}")
    if not only:
        (pairs / 'index.json').write_text(json.dumps(rows, indent=1))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', required=True, help='targets-ext.json from prep.mjs')
    ap.add_argument('--shots', required=True, help='capture.py output folder')
    ap.add_argument('--pairs', required=True, help='output folder for the pair PNGs')
    ap.add_argument('--lib', required=True, help='paintlib.js from build.mjs')
    ap.add_argument('--cache', default=str(CACHE), help='animation packs and browser profile')
    ap.add_argument('--chrome', help='Chrome or Edge executable (default: found automatically)')
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    targets = json.loads(Path(a.targets).read_text())

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    compose_all(targets, a.shots, a.pairs, a.lib, Path(a.cache), a.chrome,
                set(a.only.split(',')) if a.only else None, log)


if __name__ == '__main__':
    sys.exit(main())
