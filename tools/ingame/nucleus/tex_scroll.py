"""
tex_scroll.py -- auto-scroll the character-select screen so Dolphin renders (and,
with DumpTextures on, dumps) every CSP placeholder in a texture-pack build.

This is the automation of the manual "scroll through every costume" step of
texture-pack mode. Given the build's texture mapping (global index -> character +
costume_index, written by the texture-pack export), it groups costumes by
character and, for each character: steers the cursor onto the cell (closed-loop
via melee_css.Cursor, confirmed by the hovered grid index), places the coin so
the costume's portrait renders on the player panel, then cycles the costume with
X across that character's whole range -- dwelling on each so Dolphin has a frame
to render+dump the 16x16 placeholder and the backend watcher a poll to catch it.

The placeholder for a given global index is byte-identical in every build, so the
index -> dumped-filename relation this reveals is build-independent: harvest once,
reuse forever (see run-texture-harvest.js).

    python tex_scroll.py <mapping.json> [--limit N] [--no-place] [--dwell 0.8]
                         [--only <Char>] [--exclude <Char>]

--limit N        sweep only the first N characters (a quick probe)
--no-place       hover only, don't place the coin (test whether hover alone dumps)
--dwell S        seconds to dwell on each costume (default 0.8)
--only <Char>    sweep ONLY this character (comma-separated ok). Used for the
                 online Sheik pass: on the unranked CSS the Zelda cell renders
                 Sheik, so `--only Sheik` cycles Sheik's costumes there.
--exclude <Char> skip this character (comma-separated). The offline pass uses
                 `--exclude Sheik` -- offline the Zelda cell renders Zelda, so
                 sweeping Sheik there would just re-dump Zelda.

Assumes Dolphin is already on a CLEAN CSS (e.g. after pipe.js gotocss). No CPU /
2nd player is needed -- we never start a match.
"""

import json
import sys
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'app' / 'backend'))   # shared/ingame/ lives in the backend

from shared.ingame.melee_mem import Dolphin
from shared.ingame.melee_pipe import Pipe
from shared.ingame.melee_css import Cursor
from shared.ingame.char_select import load_grid, norm, css_index, CSS_INDEX

# MEX fighter name (normalized, alnum-lower) -> grid.json key, for the names that
# char_select.norm/ALIASES doesn't already resolve to a grid cell.
EXTRA_KEYS = {
    "cfalcon": "falcon", "captainfalcon": "falcon", "captfalcon": "falcon",
    "mrgameandwatch": "gameandwatch", "mrgamewatch": "gameandwatch",
    "gamewatch": "gameandwatch", "mrgamewatchh": "gameandwatch",
    "iceclimbers": "iceclimbers", "popo": "iceclimbers", "ic": "iceclimbers",
    "sheik": "zelda", "drmario": "drmario",
}


def rawnorm(name):
    """Alnum-lowercase WITHOUT char_select's aliases -- so Sheik and Zelda stay
    DISTINCT (norm() would collapse Sheik->zelda, which the --only/--exclude
    filters must not do, since the whole point is to treat them separately)."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def grid_key(name, grid):
    """Resolve a MEX fighter name to a grid.json cell key, or None if it has no
    cell (e.g. Nana, or a custom fighter not placed in the vanilla grid)."""
    k = norm(name)            # applies char_select ALIASES
    if k in grid:
        return k
    if k in EXTRA_KEYS:
        return EXTRA_KEYS[k]
    return None


def parse_args(argv):
    opts = {"limit": None, "place": True, "dwell": 0.8, "only": None, "exclude": None}
    if len(argv) < 2:
        print(__doc__)
        sys.exit(2)
    opts["mapping"] = argv[1]
    if "--limit" in argv:
        opts["limit"] = int(argv[argv.index("--limit") + 1])
    if "--no-place" in argv:
        opts["place"] = False
    if "--dwell" in argv:
        opts["dwell"] = float(argv[argv.index("--dwell") + 1])
    if "--only" in argv:
        opts["only"] = {rawnorm(x) for x in argv[argv.index("--only") + 1].split(",")}
    if "--exclude" in argv:
        opts["exclude"] = {rawnorm(x) for x in argv[argv.index("--exclude") + 1].split(",")}
    return opts


def group_by_character(mapping_path, only=None, exclude=None):
    """[(grid_key, mex_name, [costume_index,...] sorted)] in CSS grid order.
    only/exclude are sets of normalized character names to keep/drop."""
    with open(mapping_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    grid = load_grid()
    by_name = {}
    skipped = {}
    for c in data.get("costumes", []):
        name = c["character"]
        nm = rawnorm(name)
        if only is not None and nm not in only:
            continue
        if exclude is not None and nm in exclude:
            continue
        gk = grid_key(name, grid)
        if gk is None:
            skipped[name] = skipped.get(name, 0) + 1
            continue
        by_name.setdefault((gk, name), []).append(int(c["costume_index"]))
    if skipped:
        print(f"  (skipped {sum(skipped.values())} placeholders with no grid cell: "
              f"{', '.join(sorted(skipped))})")
    # order characters by CSS grid index so the sweep follows screen order
    out = []
    for (gk, name), costumes in by_name.items():
        out.append((gk, name, sorted(set(costumes))))
    out.sort(key=lambda t: CSS_INDEX.get(t[0], 99))
    return out, grid


def sweep_character(cur, grid, gk, costumes, place, dwell):
    """Display every costume of one character so each placeholder gets rendered.
    Returns the count of distinct costume values actually shown."""
    x, y = grid[gk]
    idx = css_index(gk)
    cur.unlock()
    cur.move_to(x, y)
    for _ in range(5):                       # confirm we're on the right cell
        if cur.hovered() == idx:
            break
        cur.move_to(x, y, tol=0.6)
        time.sleep(0.12)
    on = cur.hovered() == idx
    cur.p.center()
    time.sleep(0.15)
    if place:
        cur.p.tap("A", 0.08)                 # place the coin -> portrait renders
        time.sleep(0.35)
    want = len(costumes)
    seen = set()
    # show costume 0 first (re-sync), then step up through the range with X
    cur.set_costume(0)
    time.sleep(dwell)
    seen.add(cur.costume())
    for _ in range(want + 2):                # +slack; stop once all are seen
        if len(seen) >= want:
            break
        cur.p.tap("X", 0.06)
        time.sleep(dwell)
        seen.add(cur.costume())
    if place:
        cur.p.tap("B", 0.06)                 # pick the coin back up to move on
        time.sleep(0.2)
    return on, sorted(seen)


def main():
    opts = parse_args(sys.argv)
    chars, grid = group_by_character(opts["mapping"], only=opts["only"], exclude=opts["exclude"])
    if opts["limit"] is not None:
        chars = chars[: opts["limit"]]
    total_costumes = sum(len(c) for _, _, c in chars)
    print(f"sweeping {len(chars)} characters / {total_costumes} costumes "
          f"(place={opts['place']}, dwell={opts['dwell']}s)")

    d = Dolphin()
    p = Pipe()
    cur = Cursor(d, p)
    p.neutral()
    time.sleep(0.4)

    swept = 0
    for gk, name, costumes in chars:
        on, seen = sweep_character(cur, grid, gk, costumes, opts["place"], opts["dwell"])
        swept += len(seen)
        flag = "" if on else "  [WARN cursor not confirmed on cell]"
        print(f"  {name:<16} cell={gk:<13} costumes={len(costumes):>2} "
              f"shown={len(seen):>2}{flag}")

    p.center()
    p.close()
    print(f"done: displayed {swept} costume portraits across {len(chars)} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
