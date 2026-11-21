"""A port's portraits and stock icons, cut from pictures of it in the game.

Usage (cwd app/backend): python game_art.py <work> <iso> [--height H] [--yaw DEGREES] [--head-share S] [--head-side left|right]
The game is started ONCE on <iso>. For each costume in <work>/package/costumes/costumes.json a match is started
in that same boot (`look_probe.py`'s `match_<n>`, about six seconds each), the fighter stands, the game is stopped
and one picture is taken on a flat background with the camera parked on the whole fighter (`look_portrait`). The
fighter is cut out of it; the portrait is the whole cut-out and the stock icon the square round its head. With
--shots <folder> no game is started at all: the pictures are taken from that folder (the round's own, `round.py`),
which holds them under the same names. Writes <work>/package/art/<n>_{csp,hd,stock}.png (what `package_build.py`
takes as the costumes' artwork) and <work>/tmp/art/sheet.png to look at.

Where the head is, is asked of THIS fighter (`head_box`): the points of its body that follow its own head joint, in
the clip it stands in, seen from the picture's camera, as a share of its whole body. (It used to be "the square at
the top of the cut-out on the right", which is where the first fighter made this way, a dog, has its head: Wolf's
stock icons came out as the tip of an ear.) --head-share and --head-side put the old corner square back, for a
fighter the files cannot answer for.

A picture is only used if it is of the body the costume file holds now: one taken before its costume file was
written shows the body as it was. With a disc given, such a costume is photographed again; with --shots (the
round's pictures) the stage stops and says a new round is owed.

This optional developer route captures engine-driven joint rotations and effects. Ordinary packaging uses
port_art.py's locally rendered own idle, which is sufficient for a usable portrait without a game session.
The fighter must stand clear of the HUD in the picture; the camera is set from the fighter's drawn height
(--height, else <work>/data/report.json's), and the sheet says whether that worked.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
BG, TOL = 64, 10                     # the probe's flat background (#404040) and how near it a pixel must be
BELOW = 0.80                         # the share of the picture's height above the HUD
SPECK = 0.02                         # a solid piece not joined to the fighter smaller than this share of him is not his


def subject(image):
    """The fighter cut out of a picture, RGBA: the thing at the picture's middle that is not the flat background,
    with what it encloses (a grey patch of its own is kept, the background around it is not)."""
    rgb = image.convert('RGB')
    rgb = rgb.crop((0, 0, rgb.width, int(rgb.height * BELOW)))
    a = np.asarray(rgb).astype(int)
    solid = np.abs(a - BG).max(axis=2) > TOL
    # the thing at the middle: the nearest solid pixel to the centre, and everything joined to it
    ys, xs = np.nonzero(solid)
    if not len(xs):
        raise SystemExit('the picture is all background')
    k = np.argmin((xs - rgb.width / 2) ** 2 + (ys - rgb.height * 0.55) ** 2)
    mask = Image.fromarray((solid * 255).astype(np.uint8)).copy()
    ImageDraw.floodfill(mask, (int(xs[k]), int(ys[k])), 128)
    box = Image.fromarray(((np.asarray(mask) == 128) * 255).astype(np.uint8)).getbbox()
    box = (max(0, box[0] - 3), max(0, box[1] - 3), min(rgb.width, box[2] + 3), min(rgb.height, box[3] + 3))
    part = rgb.crop(box)
    near = Image.fromarray(((~solid[box[1]:box[3], box[0]:box[2]]) * 255).astype(np.uint8)).copy()
    w, h = near.size
    for x in range(w):                                   # the background, flooded in from the edges of the box
        for y in (0, h - 1):
            if near.getpixel((x, y)) == 255:
                ImageDraw.floodfill(near, (x, y), 128)
    for y in range(h):
        for x in (0, w - 1):
            if near.getpixel((x, y)) == 255:
                ImageDraw.floodfill(near, (x, y), 128)
    keep = np.asarray(near) != 128
    # what is solid in the box but not joined to the fighter is his only if it is a piece of some size (a flame
    # apart from the body); specks are not, nor the emulator's own words over the picture ("Wrote memory card ...",
    # each letter a speck of its own, at the top where a close camera puts the head)
    from scipy import ndimage
    inside = solid[box[1]:box[3], box[0]:box[2]]
    body = (np.asarray(mask) == 128)[box[1]:box[3], box[0]:box[2]]
    parts, count = ndimage.label(inside & ~body)
    if count:
        sizes = ndimage.sum(np.ones_like(parts), parts, index=np.arange(1, count + 1))
        small = np.zeros(count + 1, bool)
        small[1:] = np.asarray(sizes) < SPECK * body.sum()
        keep = keep & ~small[parts]
    alpha = Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    out = part.convert('RGBA')
    out.putalpha(alpha)
    return out


def fitted(cut, size, margin=0.04, anchor='bottom'):
    """A cut-out on a clear canvas of `size`'s shape, as large as fits inside a margin, made that size."""
    cut = cut.crop(cut.getchannel('A').point(lambda v: 255 if v > 40 else 0).getbbox())
    tw, th = size
    scale = min(tw * (1 - 2 * margin) / cut.width, th * (1 - 2 * margin) / cut.height)
    big = 4
    canvas = Image.new('RGBA', (tw * big, th * big), (0, 0, 0, 0))
    new = cut.resize((max(1, round(cut.width * scale * big)), max(1, round(cut.height * scale * big))), Image.LANCZOS)
    x = (canvas.width - new.width) // 2
    y = canvas.height - new.height - round(th * margin * big) if anchor == 'bottom' else (canvas.height - new.height) // 2
    canvas.alpha_composite(new, (x, y))
    return canvas.resize(size, Image.LANCZOS)


def camera(work, height=None, yaw=62.0):
    """The probe's camera for a portrait, from the fighter's drawn height (else `drawn_height`)."""
    if height is None:
        height = drawn_height(work)
    return f'{2.9 * height:.1f} {0.42 * height:.1f} 35 {yaw:g}'


def drawn_height(work):
    """How tall the fighter is drawn as it stands: its body's own points (`standing`), or where they cannot be read
    the height of its tallest joint (<work>/data/report.json). The joint alone is short of a fighter whose head is
    above its last joint (Squirtle's tallest joint is his jaw: his portrait was cut off at the brow, under the
    emulator's words), so the taller of the two is taken."""
    height = json.loads((Path(work) / 'data' / 'report.json').read_text('utf-8'))['scale']['drawn_height']
    try:
        placed, _is_head, _name, scale = standing(work, 1)
        height = max(height, float(np.ptp(placed[0][:, 1])) * scale)
    except Exception:                                   # noqa: BLE001 (the joint's height stands)
        pass
    return height


def tests(count):
    """The probe's tests that photograph `count` costumes in one boot: the first match is costume 0's."""
    out = ['look_portrait']
    for n in range(1, count):
        out += [f'match_{n}', 'look_portrait']
    return out


def picture(shots, n):
    """Where the probe left costume n's picture in `shots` (None when it is not there)."""
    for name in ([f'look_portrait-c{n}-body.png'] + (['look_portrait-body.png'] if n == 0 else [])):
        if (Path(shots) / name).exists():
            return Path(shots) / name
    return None


def stale(work, rows, shots):
    """The costumes whose picture was taken BEFORE their costume file was written: [(number, file, picture)]. Such
    a picture shows the body as it was (smaller pictures, a part since added), and a portrait cut from it is of a
    fighter the disc does not hold. (A costume with no picture at all is not in this list: `picture` says.)"""
    out = []
    for n, row in enumerate(rows):
        costume, shot = Path(work) / 'package' / 'costumes' / row['file'], picture(shots, n)
        if shot is not None and costume.exists() and costume.stat().st_mtime > shot.stat().st_mtime:
            out.append((n, row['file'], shot))
    return out


STAND_CLIP = 'a00wait1'              # the clip every fighter of the game stands in
HEAD_ROOM = 0.04                     # the head's square is made this much larger a side: the pose in the picture
#                                      is some frame of the standing clip, not the one measured


def head_fractions(points, is_head, yaw):
    """Where a fighter's head is in a picture of its whole body: (left, top, right, bottom) of the head's own box as
    shares of the body's box, both seen from the portrait's camera. `points`: the body's points in the fighter's own
    space as it stands (x to its left, y up, z the way it faces); `is_head`: which of them follow the head joint.

    The camera is the probe's close-up (`frameshot.closeup_camera`): it stands at (sin yaw, cos yaw) from the
    fighter in the stage's x and z and looks level, and the fighter faces right, which is the stage's +x. So a
    point's place across the picture is z cos(yaw) + x sin(yaw) of its own, and up the picture its y. (Held against
    the game's own pictures of Wolf and of Duck Hunt, 2026-11-12: the body's outline drawn this way lies on the
    fighter in both; drawn mirrored it lies on neither.) The camera's lens is left out: from 2.9 body heights away
    it moves a share by a few hundredths, and `HEAD_ROOM` is there for that."""
    import math
    points, is_head = np.asarray(points, float), np.asarray(is_head, bool)
    a = math.radians(float(yaw))
    across = points[:, 2] * math.cos(a) + points[:, 0] * math.sin(a)
    up = points[:, 1]
    left, right, low, high = across.min(), across.max(), up.min(), up.max()
    wide, tall = max(right - left, 1e-9), max(high - low, 1e-9)
    h_across, h_up = across[is_head], up[is_head]
    return (float((h_across.min() - left) / wide), float((high - h_up.max()) / tall),
            float((h_across.max() - left) / wide), float((high - h_up.min()) / tall))


def standing(work, frames=3):
    """The fighter's body as it stands, from what the prepare stage left in its work folder (the rig, the body's own
    mesh and which of its parts are drawn at rest, the joint table, the fighter data's report) and the game's
    standing clip. -> ([the body's points in the fighter's own space, one array a frame, for `frames` frames spread
    over the clip], which points follow the head joint or what hangs from it, the head joint's name, the size the
    game draws the body at). Raises with the reason when a file is not there or the fighter has no head joint."""
    work = Path(work)
    if str(HERE.parents[1]) not in sys.path:
        sys.path.insert(0, str(HERE.parents[1]))
    from fighter_port import own_data
    from fighter_port.compat import smd
    from fighter_port.compat.bone_lookup import SLOTS
    report = json.loads((work / 'data' / 'report.json').read_text('utf-8'))
    fighter, root = report['fighter'], report['inputs']['source']
    frozen = json.loads((work / 'rig' / f'rig-{fighter}.json').read_text('utf-8'))
    lookup = json.loads((work / 'rig' / 'lookup.json').read_text('utf-8'))
    selection = json.loads((work / 'body' / 'selection.json').read_text('utf-8'))
    receipt = json.loads((work / 'body' / 'receipt.json').read_text('utf-8'))
    order = frozen['order']
    head = lookup['forward'][SLOTS.index('headN')]
    if head == 255:
        raise ValueError('the fighter has no joint bound as its head (rig/lookup.json)')
    # the body as it is drawn at rest (the parts a clip shows only for a moment are not in a standing picture)
    materials = [row['material'] for row in receipt['mesh_groups']]
    at_rest = {(m['name'], m['subindex']) for m in selection['at_rest']}
    drawn = {materials[i] for i, m in enumerate(selection['meshes']) if (m['name'], m['subindex']) in at_rest}
    points, owner = [], []
    for triangle in smd.load(work / 'body' / f'{fighter}.smd').triangles:
        if triangle.material in drawn:
            for v in triangle.verts:
                points.append(v.pos)
                owner.append(max(v.weights, key=lambda w: w[1])[0])
    points, owner = np.c_[np.array(points, float), np.ones(len(points))], np.array(owner)
    index = {j: i for i, j in enumerate(order)}
    under = {head}
    for i, j in enumerate(order):                       # (a parent comes before its children in the rig's order)
        if frozen['parent'][j] is not None and index[frozen['parent'][j]] in under:
            under.add(i)
    is_head = np.isin(owner, list(under))
    if not is_head.any():
        raise ValueError(f'no point of the body follows {order[head]} or what hangs from it')
    rest = np.linalg.inv(own_data.rest_worlds(frozen))
    last = own_data.source_pose(root, fighter, frozen, STAND_CLIP, 'end')[1]
    placed = []
    for k in range(frames):
        pose = own_data.source_pose(root, fighter, frozen, STAND_CLIP, round(last * k / frames))[0]
        now = own_data.rest_worlds(dict(order=order, parent=frozen['parent'], rest=pose))
        placed.append(np.einsum('nij,nj->ni', (now @ rest)[owner], points)[:, :3])
    return placed, is_head, order[head], float(report['scale']['written'])


def head_box(work, yaw=62.0, frames=3):
    """This fighter's head in its portrait picture, from its own files: (left, top, right, bottom) as shares of its
    body's box (the widest over a few frames of the clip it stands in). -> (the box or None, how it was found or
    why it could not be)."""
    try:
        placed, is_head, name, _scale = standing(work, frames)
        box = None
        for points in placed:
            got = head_fractions(points, is_head, yaw)
            box = got if box is None else (min(box[0], got[0]), min(box[1], got[1]), max(box[2], got[2]), max(box[3], got[3]))
        return box, f"the points that follow {name}, in {frames} frames of {STAND_CLIP}, from {yaw:g} degrees round"
    except Exception as exc:                            # noqa: BLE001 (said by the caller, which then cuts the old way)
        return None, f'{type(exc).__name__}: {exc}'


def head_camera(work, yaw=62.0):
    """The probe's camera for a picture of this fighter's HEAD (`PROBE_HEAD_CAM`: distance, height, lens, angle
    round), from its own head as it stands: level with the head's middle, far enough for the whole head. None when
    the files cannot say (the probe then keeps its fixed camera, which is at the height of a dog's head)."""
    try:
        placed, is_head, _name, scale = standing(work, 1)
        head = placed[0][is_head]
        low, high = float(head[:, 1].min()), float(head[:, 1].max())
        size = max(high - low, float(np.ptp(head[:, 0])), float(np.ptp(head[:, 2]))) * scale
        return f'{3.2 * size:.1f} {(low + high) / 2 * scale:.1f} 30 {yaw:g}'
    except Exception:                                   # noqa: BLE001
        return None


def head_square(cut_box, share):
    """The square to cut for the stock icon: round the head's box (`share`: its shares of the cut-out's box
    `cut_box`, as `head_box` gives them), as large as the box's longer side and `HEAD_ROOM` more, kept inside the
    cut-out's own height. -> (left, top, right, bottom) in the cut-out's pixels"""
    x0, y0, x1, y1 = cut_box
    wide, tall = x1 - x0, y1 - y0
    left, top, right, bottom = x0 + share[0] * wide, y0 + share[1] * tall, x0 + share[2] * wide, y0 + share[3] * tall
    side = max(right - left, bottom - top) * (1 + HEAD_ROOM)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    top_ = min(max(cy - side / 2, y0), max(y0, y1 - side))
    return (round(cx - side / 2), round(top_), round(cx + side / 2), round(top_ + side))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('work')
    p.add_argument('iso', nargs='?')
    p.add_argument('--shots', help='a folder that already holds the pictures (no game is started)')
    p.add_argument('--height', type=float, help="the fighter's drawn height in the game's units")
    p.add_argument('--yaw', type=float, default=62.0, help='the angle round the fighter the picture is taken from')
    p.add_argument('--head-share', type=float, help="(the old way) the head's square as a share of the cut-out's width, "
                                                    'at its top on --head-side: given, the head is not asked of the fighter')
    p.add_argument('--head-side', choices=('left', 'right'), help='(the old way) the side of the cut-out the head is on')
    p.add_argument('--ckind', default='0x1A', help="the fighter's number on the roster (the first added fighter is 0x1A)")
    a = p.parse_args(argv)
    work = Path(a.work)
    rows = json.loads((work / 'package' / 'costumes' / 'costumes.json').read_text('utf-8'))
    shots = Path(a.shots) if a.shots else work / 'tmp' / 'art'
    shots.mkdir(parents=True, exist_ok=True)
    old = stale(work, rows, shots)
    if a.shots and old:
        raise SystemExit(
            f"the pictures in {shots} were taken before the costume files were written ({', '.join(f for _n, f, _s in old)}): "
            'they show the body as it was, and artwork cut from them is of a fighter the disc does not hold. A new '
            'round is owed on a disc with these costumes (the port command: --from firstdisc)')
    if not a.shots and (old or any(picture(shots, n) is None for n in range(len(rows)))):
        if not a.iso:
            raise SystemExit('a disc to photograph the fighter on, or --shots <folder of pictures>')
        if old:
            print(f"photographing again: the pictures of {', '.join(f for _n, f, _s in old)} are older than those "
                  'costume files', flush=True)
        for was in shots.glob('look_portrait*.png'):     # none of the old ones is left to be cut by mistake
            was.unlink()
        env = dict(os.environ, LOOK_OUT=str(shots), PROBE_CKIND=a.ckind, PROBE_PORTRAIT_CAM=camera(work, a.height, a.yaw))
        at_head = head_camera(work, a.yaw)              # (the picture of the head alone: aimed at this fighter's own)
        if at_head:
            env['PROBE_HEAD_CAM'] = at_head
        wanted = tests(len(rows))
        subprocess.run([sys.executable, str(HERE / 'look_probe.py'), str(a.iso)] + wanted, env=env,
                       stdout=open(shots / 'probe.log', 'w'), stderr=subprocess.STDOUT, timeout=200 + 30 * len(wanted))
    # where the head is: asked of this fighter's own files, unless the old corner square was asked for by name
    share, how = (None, 'the corner square was asked for (--head-share, --head-side)')
    if a.head_share is None and a.head_side is None:
        share, how = head_box(work, a.yaw)
    if share is None:
        print(f"the head's place was not taken from the fighter's own head ({how}): the stock icon is the square at "
              f"the top of the cut-out on the {a.head_side or 'right'}, {a.head_share or 0.62:g} of its width. LOOK at "
              'the sheet: that is where a dog has its head', flush=True)
    else:
        print(f"the head: {how}; its box is {[round(v, 2) for v in share]} of the body's (left, top, right, bottom)",
              flush=True)
    made = []
    for n, row in enumerate(rows):
        shot = picture(shots, n)
        if shot is None:
            raise SystemExit(f"no picture of costume {n} ({row['name']}) in {shots}" + ('' if a.shots else f": see {shots / 'probe.log'}"))
        cut = subject(Image.open(shot))
        hd = fitted(cut, (272, 376))
        box = cut.getchannel('A').point(lambda v: 255 if v > 40 else 0).getbbox()
        if share is not None:
            square = head_square(box, share)
        else:
            side = round((box[2] - box[0]) * (a.head_share or 0.62))
            left = box[2] - side if (a.head_side or 'right') == 'right' else box[0]
            square = (left, box[1], left + side, box[1] + side)
        stock = fitted(cut.crop(square), (24, 24), margin=0.0, anchor='middle')
        made.append((hd, stock))
    art = work / 'package' / 'art'
    art.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (len(made) * 280, 376 + 110), (70, 80, 100))
    for n, (hd, stock) in enumerate(made):
        hd.save(art / f'{n}_hd.png')
        hd.resize((136, 188), Image.LANCZOS).save(art / f'{n}_csp.png')
        stock.save(art / f'{n}_stock.png')
        sheet.paste(hd, (n * 280 + 4, 4), hd)
        big = stock.resize((96, 96), Image.NEAREST)
        sheet.paste(big, (n * 280 + 4, 384), big)
    out = work / 'tmp' / 'art'
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(out / 'sheet.png')
    print(f'artwork for {len(made)} costumes in {art}; look at {out / "sheet.png"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
