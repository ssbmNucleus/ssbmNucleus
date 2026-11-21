"""
online_css_test.py -- enter the Slippi ONLINE (unranked) character-select screen
and report whether it loaded HEALTHY or CRASHED. The online CSS uses more memory
than the offline VS CSS, so it's the worst case for CSP-memory overflow (too many
/ too-high-res CSPs). Used to find where the auto-compression formula must cap.

The modded ISO boots straight to the Slippi "Online Play" menu (Unranked
highlighted, scene 0x1). Pressing A enters the online CSS (scene 0x8), where the
CSPs load -- a memory crash happens HERE, within a second or two, BEFORE
matchmaking finds anyone. We detect crash/healthy fast and then HOLD B to leave
(so we never actually match a real player / start a game).

    python online_css_test.py        # attaches to the session pid

Exit 0 = healthy (CSS loaded + ran), 1 = crashed/hung, 2 = couldn't enter.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "backend"))  # shared/ingame/ lives in the backend
from shared.ingame.melee_mem import Dolphin
from shared.ingame.melee_pipe import Pipe

SCENE_MAJOR = 0x80479D30
SCENE_MINOR = 0x80479D33
FRAME = 0x80479D60
ONLINE_CSS = 0x08          # the Slippi online CSS / matchmaking scene


def read(d, addr, n=1):
    return d.u8(addr) if n == 1 else d.u32(addr)


def enter_and_watch(d, p, settle=8.0):
    """Press A to enter the online CSS, then watch for ~settle seconds. Returns
    ('healthy'|'crashed'|'no_entry', detail)."""
    p.neutral()
    time.sleep(0.3)
    before = d.u8(SCENE_MAJOR)
    p.tap("A", 0.08)

    start = time.time()
    last_frame = None
    frozen = 0.0
    reached = False
    while time.time() - start < settle:
        time.sleep(0.3)
        if not d.alive() or not d.locate():
            return ("crashed", "process/RAM gone (hard crash)")
        scene = d.u8(SCENE_MAJOR)
        f = d.u32(FRAME)
        if scene == ONLINE_CSS:
            reached = True
        # frame-freeze detection (hang / load crash)
        if f is None or f == last_frame:
            frozen += 0.3
            if frozen > 2.5:
                return ("crashed", f"frame frozen >2.5s in scene 0x{scene:02x}")
        else:
            frozen = 0.0
            last_frame = f
    if reached:
        return ("healthy", f"online CSS (0x08) loaded, frame {d.u32(FRAME)}")
    return ("no_entry", f"never reached online CSS (scene 0x{d.u8(SCENE_MAJOR):02x})")


def exit_css(p, d):
    """HOLD B to leave the CSS (a tap doesn't exit) -- so we don't sit in
    matchmaking. Best-effort; safe to call even if already gone."""
    try:
        p.press("B")
        time.sleep(1.3)
        p.release("B")
        time.sleep(0.8)
    except Exception:
        pass


def main():
    d = Dolphin()
    p = Pipe()
    verdict, detail = enter_and_watch(d, p)
    print(f"ONLINE-CSS: {verdict.upper()} -- {detail}")
    if verdict == "healthy":
        exit_css(p, d)   # leave before matchmaking completes
    p.close()
    return 0 if verdict == "healthy" else (1 if verdict == "crashed" else 2)


if __name__ == "__main__":
    sys.exit(main())
