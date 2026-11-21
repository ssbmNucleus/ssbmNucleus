"""The hand that holds items, per fighter, for Watch Lite (litePaint.drawItems, heldItems.js).

While a fighter holds an item (its own bomb, boomerang or turnip, or one it caught or picked up), the
game attaches the item to the fighter's item-hold part (ft_data->x8->x10, Item_8026AB54) and leaves the
item's own position alone. Slippi records that position, so for as long as the item is held the replay
says it is where it was pulled or picked up: drawn there, it floated and jumped to the hand on the throw.

This bakes where the hold part is, posed through each action's animation (fighterbones, as the sword
trails pose the sword joint), fighter-local (x along the facing, y up, model scale applied), every STEP
action frames (1 decimal; Watch Lite interpolates between), for the action states fighters hold items
in: COMMON for everyone (standing, moving, jumping, falling, landing, shielding, rolling, being hit,
picking up and throwing), plus OWN, the specials of the fighters whose own items start in the hand.

    app/venv/Scripts/python.exe -B tools/liteaudit/held_items/build.py [--iso PATH] [--decomp PATH]

Writes a `hold` key into app/frontend/src/tracker/replays/data/hits/<cid>.json, keeping everything else
in the file (tools/liteaudit/hit_tables.mjs carries it over when it rewrites them):
  hold {step, rest: [x, y] (Wait's first frame: states without a row), states: {state: [x0, y0, x1, y1,
       ...] (frames 0, step, 2 step... to the action's end) | state (the same rows)}}
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / 'app/frontend/src/tracker/replays/data'
sys.path[1:1] = [str(REPO / 'tools/liteaudit/item_shapes'), str(REPO / 'tools/liteaudit'), str(REPO / 'app/backend')]

STEP = 2
# Wait .. FallAerialB, FallSpecial, Squat .. LandingFallSpecial, the damage states, LightGet .. the item
# throws, Guard .. GuardSetOff, the down / tech states, Escape (rolls, air dodge), Pass, the ledge
COMMON = (list(range(14, 36)) + list(range(39, 44)) + list(range(75, 92)) + list(range(92, 116))
          + list(range(178, 183)) + list(range(183, 199)) + list(range(233, 237)) + [244] + list(range(252, 264)))
# fighters whose own items start in the hand (Link's and Young Link's bombs and boomerang, Peach's
# turnips and Bob-ombs, Yoshi's egg): their specials too
OWN = {'Lk', 'Cl', 'Pe', 'Ys'}
SPECIALS = list(range(341, 361))


def r1(v):
    """Math.round(v * 10) / 10 (ties toward +infinity), as JavaScript does."""
    x = v * 10
    i = int(x // 1)
    return (i + 1 if x - i >= 0.5 else i) / 10


def hold_table(code):
    import fighterbones as fb
    hp = fb.hold_part(code)
    states, seen = {}, {}
    rest = None
    for st in COMMON + (SPECIALS if code in OWN else []):
        try:
            end, _, _ = fb.tracks(code, st)
        except Exception:                                   # noqa: BLE001 - no animation for this state
            continue
        rows = []
        for fr in range(0, int(end) + 1, STEP):
            m = fb.world(code, st, float(fr))[hp]
            rows += [r1(float(m[0, 3])), r1(float(m[1, 3]))]
        if not rows:
            continue
        if st == 14:
            rest = rows[:2]
        key = json.dumps(rows)
        states[str(st)] = seen.get(key, rows)
        seen.setdefault(key, st)
    return {'step': STEP, 'rest': rest or [0, 0], 'states': states}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', type=Path, default=None, help='vanilla Melee ISO (default: the one the app knows)')
    ap.add_argument('--decomp', type=Path, default=Path(os.environ.get('MELEE_DECOMP') or Path.home() / 'projects' / 'melee'))
    args = ap.parse_args()
    import fighterbones as fb
    import isofiles
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    iso = args.iso or known_vanilla_iso()
    if not iso:
        sys.exit('no vanilla ISO recorded; pass --iso')
    isofiles.open_iso(Path(iso))
    fb.DECOMP = args.decomp
    for code in fb.CODES:
        cid = fb.CODES.index(code)
        path = DATA / 'hits' / f'{cid}.json'
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding='utf-8'))
        size = len(json.dumps(d, separators=(',', ':')))
        d['hold'] = hold_table(code)
        text = json.dumps(d, separators=(',', ':'))
        path.write_text(text + '\n', encoding='utf-8')
        print(f"{code} (cid {cid}): hold {len(d['hold']['states'])} states "
              f"{len(json.dumps(d['hold'], separators=(',', ':')))} B, file {size} -> {len(text) + 1} B", flush=True)


if __name__ == '__main__':
    main()
