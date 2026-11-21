"""
harvest_sheik_online.py -- harvest SHEIK's CSP placeholders, the one gap the
offline sweep can't cover. Offline, the Zelda cell renders Zelda; on the Slippi
UNRANKED online CSS the SAME Zelda cell renders SHEIK (the user's tip). So we
briefly enter the online CSS, hover the Zelda cell and cycle Sheik's costumes so
Dolphin dumps their placeholders, then leave.

SAFETY (this momentarily goes online): the online CSS loads BEFORE matchmaking
pairs anyone (validated in online_css_test.py). We stay only a few seconds (a HARD
wall-clock budget) and ALWAYS hold-B out -- in a finally, and on any timeout or
error -- so we never actually match a real player or start a game. Assumes Dolphin
is at the Online Play menu (scene 0x1, the modded ISO's boot screen) or already on
the online CSS.

    python harvest_sheik_online.py <mapping.json> [--budget 6.0] [--dwell 0.6] [--place]

Exit 0 = swept (check the watcher's match count for Sheik 36-40), 2 = couldn't
enter the online CSS.
"""

import json
import sys
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'app' / 'backend'))   # shared/ingame/ lives in the backend

from shared.ingame.melee_mem import Dolphin
from shared.ingame.melee_pipe import Pipe
from shared.ingame.melee_css import Cursor
from shared.ingame.char_select import load_grid, CSS_INDEX
from tex_scroll import rawnorm

SCENE_MAJOR = 0x80479D30
ONLINE_CSS = 0x08
ZELDA_CELL = "zelda"


def sheik_costumes(mapping_path):
    data = json.load(open(mapping_path, encoding="utf-8"))
    return sorted(int(c["costume_index"]) for c in data.get("costumes", [])
                  if rawnorm(c["character"]) == "sheik")


def hold_b_exit(p):
    """HOLD B to leave the CSS (a tap won't) -- so we drop out of matchmaking."""
    try:
        p.press("B")
        time.sleep(1.3)
        p.release("B")
        time.sleep(0.6)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mapping = sys.argv[1]
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 6.0
    dwell = float(sys.argv[sys.argv.index("--dwell") + 1]) if "--dwell" in sys.argv else 0.6
    place = "--place" in sys.argv

    costumes = sheik_costumes(mapping)
    if not costumes:
        print("no Sheik costumes in mapping; nothing to do")
        return 0
    print(f"Sheik online harvest: {len(costumes)} costumes (budget {budget}s, "
          f"{'place' if place else 'hover'}, dwell {dwell}s)")

    d = Dolphin()
    p = Pipe()
    grid = load_grid()
    zx, zy = grid[ZELDA_CELL]
    zidx = CSS_INDEX[ZELDA_CELL]
    cur = Cursor(d, p)
    p.neutral()
    time.sleep(0.3)

    # Enter the online CSS (press A from the Online Play menu) if not already there.
    if d.u8(SCENE_MAJOR) != ONLINE_CSS:
        p.tap("A", 0.08)
    t0 = time.time()
    reached = False
    while time.time() - t0 < 3.5:
        if d.u8(SCENE_MAJOR) == ONLINE_CSS:
            reached = True
            break
        time.sleep(0.2)
    if not reached:
        print(f"never reached online CSS (scene 0x{d.u8(SCENE_MAJOR):02x})")
        hold_b_exit(p)
        p.close()
        return 2

    css_start = time.time()
    presses = 0
    try:
        # Hover the Zelda cell -> the panel renders SHEIK on the online CSS.
        cur.move_to(zx, zy, timeout=2.5)
        for _ in range(4):
            if cur.hovered() == zidx:
                break
            cur.move_to(zx, zy, tol=0.6, timeout=1.2)
            time.sleep(0.1)
        if place:
            p.tap("A", 0.08)
            time.sleep(0.3)
        # Cycle Sheik's costumes with X (bounded: exactly len-1 presses, and a
        # hard wall-clock budget so we leave well before matchmaking pairs us).
        # NOTE: the costume byte (0x80480823) reads stale/0 on the ONLINE CSS, so
        # we DON'T gate on it -- we just press X once per costume and dwell; each
        # press cycles + renders the next Sheik CSP and Dolphin dumps it. The
        # watcher decodes the true index from the placeholder pixels (ground
        # truth), so the dumps are correct even though the byte readback isn't.
        time.sleep(dwell)
        presses = 0
        for _ in range(len(costumes) - 1):
            if time.time() - css_start > budget:
                break
            p.tap("X", 0.06)
            presses += 1
            time.sleep(dwell)
    finally:
        hold_b_exit(p)   # ALWAYS leave (covers timeout / exception too)

    p.center()
    p.close()
    print(f"Sheik online: hovered={cur.hovered()} (want {zidx}={ZELDA_CELL}), "
          f"cycled {presses + 1}/{len(costumes)} costumes via X, "
          f"{time.time() - css_start:.1f}s on CSS (held B out before matchmaking)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
