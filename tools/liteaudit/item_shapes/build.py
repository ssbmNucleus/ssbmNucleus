"""Sizes, colours and timing for Watch Lite's own item and effect drawings (itemArt.js), from the vanilla ISO.

Watch Lite draws these things itself (shapes, strokes, a few particles); the game supplies numbers only.
The models are still read and posed from the game files to measure them (shapes.py and poses.py:
hsdgeom.py model reader, itemmodel.py articles, fighterbones.py fighter poses), but what is written is
their measurements: extents, colours, where they sit and how that changes frame by frame. No outline,
texture or sprite is written. Two decimals unless noted (as JavaScript Math.round does). World units
around the position Slippi records (x right, y up):
  car       Onett cars (GrOt.dat map_head group 3), keyed by item kind 160 state 2..5 = car i 0..3:
            x [front, back] (front toward -x), belt (top of the hood and boot), roof and its span
            [x0, x1], body colour, wheels [[x, radius]] (wheels on y 0).
  ice       Ice Climbers' ice (kind 106): half width by spin phase (frame in state, every 5 of 60),
            y [bottom, top], colour.
  missile   Samus' missile (kind 95): x [tail, nose] (nose +x), radius, shell and nose colours.
  turnip    Peach's turnip (kind 99, x1.3): bulb [x0, x1, y0, y1] and the leaves' top, with the origin
            at the top of the bulb, colours; held: [dx along facing, dy, tilt degrees] of the origin
            from Peach's x,y by her action frame, for each state in shapes.HELD_STATES.
  egg       Yoshi's egg around a victim: half width and height of the unit egg (bottom at 0), size by
            victim (ftCo_DatAttrs +0xBC, in internal character order), grow = [Yoshi attr x1C, x20].
  fireball  Mario's (48) / Luigi's (105) fireball: bright core circle [x, y, r] and the flame's centre
            and radius [x, y, r], before the spin.
  flame     Fire Fox / Fire Bird (EfFxData.dat models 3 and 4): charge by effect frame 0..18, [crown
            half width at its foot, at its top, crown height, column half width, column height, floor
            ring half width]; travel by effect frame 0..19 (1 decimal), seen from the camera across (x)
            and along (y) the travel line, [x centre, half width, back y, front y] of the plume and then
            of its core; hips {cid: {pivot, up[action frame]}}, the HipN anchor of the plume (Fox 1,
            Falco 22).
  pkTrail   Ness' PK Thunder tail pieces (kinds 70-73): {kind: {colour, amp: [zigzag half height per
            texture]}}.
  bolt      Pikachu's Thunder bolt (kinds 81/82): [{x: [x0, x1], stroke, glow: [x0, x1]}] per texture.
  shyGuy    Yoshi's Story Shy Guy (kind 210): its box [x0, x1, y0, y1], facing +x.
  randall   Yoshi's Story's Randall (GrSt.dat map_head group 2): its quad on the moving platform,
            {w: width / the line's, dx: centre's offset from the line's middle / the line's width,
            line: where the line crosses it / its height, from the top, h: height / width} (4 places).
  rebirth   revival platform (PlCo.dat): deck half width, top and bottom y at the fighter's feet
            (scale 1); scale {cid: s} where the fighter's respawn_platform_scale (ftCo_DatAttrs +0x160)
            is not 1.
  blaster   Falco's blaster shot shells: [radius, tip z, z at full radius front / back, tail z,
            colour, alpha], nose at z 0, tail toward -z.
  koopaShell Bowser's Whirling Fortress (359 ground, 360 air): {state: {first, frames}}, the shell-only
            model's box [x0, x1, y0, y1] by action frame from `first` while the game shows it (1
            decimal), fighter-local (x along facing, model scale applied).

    app/venv/Scripts/python.exe -B tools/liteaudit/item_shapes/build.py [--iso PATH] [--decomp PATH] [--out PATH]

Writes app/frontend/src/tracker/replays/data/itemMetrics.js (export default {car, ice, missile, turnip,
egg, fireball, flame, pkTrail, bolt, shyGuy, randall, rebirth, blaster, koopaShell}). --decomp is the melee decomp
checkout; only its config/GALE01/symbols.txt is read (the fighter motion state tables in the DOL, for
the held turnip, the Fire Fox hips and Bowser's shell).
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'app/frontend/src/tracker/replays/data'
sys.path[1:1] = [str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]

CODES = 'Mr Fx Ca Dk Kb Kp Lk Sk Ns Pe Pp Nn Pk Ss Ys Pr Mt Lg Ms Zd Cl Dr Fc Pc Gw Gn Fe'.split()
DARK = ('#000000', '#060606', '#090909')      # a car's tyre / shadow DObjs: not its body colour
HEADER = ("// Sizes, colours and timing of Watch Lite's own item and effect drawings (itemArt.js),\n"
          "// measured from the vanilla ISO's models by tools/liteaudit/item_shapes/build.py.\n"
          "// Numbers only: no outline, texture or sprite of the game's. Do not edit by hand.\n")


# ---------------------------------------------------------------- JavaScript-identical output
def js_round(v, places):
    """Math.round(v * 10^places) / 10^places (ties toward +infinity, as V8)."""
    k = 10 ** places
    x = v * k
    r = math.ceil(x)
    if r - 0.5 > x:
        r -= 1
    return r / k


def js_number(v):
    """Number.prototype.toString / JSON.stringify for a number."""
    if isinstance(v, (bool, np.bool_)):
        raise TypeError('bool')
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    v = float(v)
    if v != v or v in (math.inf, -math.inf):
        return 'null'
    if v == 0:
        return '0'
    s = repr(v)
    sign = '-' if s[0] == '-' else ''
    s = s.lstrip('-')
    mant, _, exp = s.partition('e')
    ip, _, fp = mant.partition('.')
    digits = ip + fp
    n = len(ip) + (int(exp) if exp else 0)
    stripped = digits.lstrip('0')
    n -= len(digits) - len(stripped)
    digits = stripped.rstrip('0')
    k = len(digits)
    if k <= n <= 21:
        out = digits + '0' * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + '.' + digits[n:]
    elif -6 < n <= 0:
        out = '0.' + '0' * -n + digits
    else:
        e = n - 1
        out = digits[0] + ('.' + digits[1:] if k > 1 else '') + 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    return sign + out


def _index_key(k):
    return k.isdigit() and (k == '0' or k[0] != '0') and int(k) < 2 ** 32 - 1


def js_stringify(o):
    """JSON.stringify(o): no spaces, integer-like object keys first in ascending order."""
    if o is None:
        return 'null'
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, dict):
        keys = [str(k) for k in o]
        vals = dict(zip(keys, o.values()))
        order = sorted((k for k in keys if _index_key(k)), key=int) + [k for k in keys if not _index_key(k)]
        return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + js_stringify(vals[k]) for k in order) + '}'
    if isinstance(o, (list, tuple)):
        return '[' + ','.join(js_stringify(v) for v in o) + ']'
    return js_number(o)


# ---------------------------------------------------------------- compaction
def r(v):
    return js_round(v, 2)


def r1(v):
    return js_round(v, 1)


def hex_rgb(c):
    assert all(float(v).is_integer() and 0 <= v <= 255 for v in c), c
    return '#' + ''.join('%02x' % int(v) for v in c)


def blaster_row(s):
    """[radius, tip z, z at full radius (front, back), tail z, colour, alpha] of the shell's last vertex colour."""
    x = js_round(s['r'] * 1000, 2) / 1000
    rgba = s['rgba'][-1]
    return [s['r'] if x == s['r'] else js_round(s['r'], 3), s['z'][1], s['z_at_rmax'][1], s['z_at_rmax'][0], s['z'][0],
            hex_rgb(rgba[:3]), js_round(rgba[3] / 255, 3)]


# ---------------------------------------------------------------- measurements
def box(pts):
    """[x0, x1, y0, y1] of points."""
    a = np.asarray(pts, dtype=float)
    return [float(a[:, 0].min()), float(a[:, 0].max()), float(a[:, 1].min()), float(a[:, 1].max())]


def span_at(poly, y):
    """Where a horizontal line at y crosses the closed polygon: (x0, x1), or None."""
    xs = []
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        if (ay <= y < by) or (by <= y < ay):
            xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
    return (min(xs), max(xs)) if xs else None


def car_metrics(c):
    """A car's length, the top of its hood and boot (the highest cut at least 85% as long as the car), its
    roof (the highest cut at least a quarter as long) and that roof's span, colour and wheels."""
    o = c['outline']
    x0, x1, y0, y1 = box(o)
    length = x1 - x0
    cuts = [(y, span_at(o, y)) for y in np.linspace(y0, y1, 801)[1:-1]]
    belt = max(y for y, sp in cuts if sp and sp[1] - sp[0] >= 0.85 * length)
    roof = max(y for y, sp in cuts if sp and sp[1] - sp[0] >= 0.25 * length)
    rx0, rx1 = span_at(o, roof - 0.05)
    return {'x': [r(x0), r(x1)], 'belt': r(belt), 'roof': r(roof), 'span': [r(rx0), r(rx1)],
            'body': next((h for h in c['colours'] if h not in DARK), c['colours'][0]),
            'wheels': [[r(v) for v in w] for w in c['wheels']]}


def charge_row(f):
    """[crown half width at its foot, at its top, crown height, column half width, column height, ring half
    width] of one charge frame; the crown stands on the fighter's feet."""
    cx0, cx1, cy0, cy1 = box(f['crown'])
    foot = span_at(f['crown'], cy0 + 0.08 * (cy1 - cy0)) or (cx0, cx1)
    lx0, lx1, _, ly1 = box(f['column'])
    gx0, gx1, _, _ = box(f['ring'])
    return [r((foot[1] - foot[0]) / 2), r((cx1 - cx0) / 2), r(cy1), r((lx1 - lx0) / 2), r(ly1), r((gx1 - gx0) / 2)]


def plume_row(f):
    """[x centre, half width, back y, front y] of the travel plume and then of its core (1 decimal)."""
    out = []
    for part in (f['outer'], f['core']):
        x0, x1, y0, y1 = box(part)
        out += [r1((x0 + x1) / 2), r1((x1 - x0) / 2), r1(y0), r1(y1)]
    return out


def ellipse_box(e):
    cx, cy, rx, ry = e
    return [cx - rx, cx + rx, cy - ry, cy + ry]


def build():
    import poses
    import shapes
    cars, ice, missile, turnip, egg = shapes.cars(), shapes.ice(), shapes.missile(), shapes.turnip(), shapes.egg()
    fireballs = {kind: shapes.fireball(fname) for kind, fname in shapes.FIREBALLS}
    charge, travel, hips = shapes.flames(), shapes.travel_plume(), poses.travel_hips()
    trail, bolts, shy = shapes.pk_trail(), shapes.bolt(), shapes.shy_guy()
    platform_scale, shells, koopa = shapes.respawn_platform_scales(), shapes.blaster_shells(), poses.koopa_shell()
    deck, _ = shapes.revival_deck()
    ice_boxes = [box(ice['phases'][k]) for k in sorted(ice['phases'])]
    bulb, missile_box, egg_box, deck_box = box(turnip['bulb']), box(missile['poly']), box(egg['outline']), box(deck)
    shy_boxes = [box(shy['body'])] + [ellipse_box(shy[k]) for k in ('propeller', 'feet', 'mask', 'pupil')]

    def flame(fb):
        x0, x1, y0, y1 = box(fb['flame'])
        return [r((x0 + x1) / 2), r((y0 + y1) / 2), r((x1 - x0 + y1 - y0) / 4)]
    return {
        'car': {c['item_state']: car_metrics(c) for c in cars},
        'ice': {'w': [r((b[1] - b[0]) / 2) for b in ice_boxes],
                'y': [r(min(b[2] for b in ice_boxes)), r(max(b[3] for b in ice_boxes))], 'colour': ice['colours'][0]},
        'missile': {'x': [r(missile_box[0]), r(missile_box[1])], 'r': r((missile_box[3] - missile_box[2]) / 2),
                    'body': missile['body'], 'nose': missile['nose']},
        'turnip': {'bulb': [r(v) for v in bulb], 'top': r(box(turnip['poly'])[3]), 'leaves': turnip['leaves_colour'],
                   'bulbColour': turnip['bulb_colour'],
                   'held': {st: [[r(a), r(b), js_round(c, 0)] for a, b, c in rows] for st, rows in turnip['held'].items()}},
        'egg': {'w': r((egg_box[1] - egg_box[0]) / 2), 'h': r(egg_box[3] - egg_box[2]),
                'sizes': [egg['sizes'][c] for c in CODES], 'grow': [r(egg['x1C']), egg['x20']]},
        'fireball': {k: {'core': [r(v) for v in fb['core']], 'flame': flame(fb)} for k, fb in fireballs.items()},
        'flame': {'charge': [charge_row(f) for _, f in sorted(charge.items())],
                  'travel': [plume_row(f) for f in travel],
                  'hips': {cid: {'pivot': h['pivot_up'], 'up': [r(v) for v in h['hip_up']]} for cid, h in hips.items()}},
        'pkTrail': {kind: {'colour': hex_rgb(v[0]['colour']),
                           'amp': [r((box(t['line'])[3] - box(t['line'])[2]) / 2) for t in v]} for kind, v in trail.items()},
        'bolt': [{'x': [r(v) for v in box(b['line'])[:2]], 'stroke': r(b['stroke']), 'glow': [r(v) for v in b['glow_x']]}
                 for b in bolts],
        'shyGuy': {'box': [r(min(b[0] for b in shy_boxes)), r(max(b[1] for b in shy_boxes)),
                           r(min(b[2] for b in shy_boxes)), r(max(b[3] for b in shy_boxes))]},
        'randall': shapes.randall(),
        'rebirth': {'w': r((deck_box[1] - deck_box[0]) / 2), 'top': r(deck_box[3]), 'bottom': r(deck_box[2]),
                    'scale': {cid: r(platform_scale[c]) for cid, c in enumerate(CODES) if platform_scale[c] != 1}},
        'blaster': [blaster_row(s) for s in shells],
        'koopaShell': {st: {'first': k['first'], 'frames': [[r1(v) for v in box(f)] for f in k['frames']]}
                       for st, k in koopa.items()},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--decomp', type=Path, default=Path(os.environ.get('MELEE_DECOMP') or Path.home() / 'projects' / 'melee'))
    ap.add_argument('--out', type=Path, default=DATA / 'itemMetrics.js')
    args = ap.parse_args()
    import fighterbones
    import isofiles
    if args.iso is None:
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        args.iso = Path(str(known_vanilla_iso()))
    isofiles.open_iso(args.iso)
    fighterbones.DECOMP = args.decomp
    out = build()
    args.out.write_text(HEADER + 'export default ' + js_stringify(out) + ';\n', encoding='utf-8', newline='\n')
    print(f'{args.out.name}: {len(out["car"])} cars, {len(out["ice"]["w"])} ice phases, '
          f'{len(out["turnip"]["held"])} held turnip states, {len(out["flame"]["charge"])}+{len(out["flame"]["travel"])} '
          f'flame frames, {len(out["bolt"])} bolts, koopa shell frames '
          f'{[len(k["frames"]) for k in out["koopaShell"].values()]}, {args.out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
