"""Start Classic mode with the port's fighter and photograph the "versus" card before the first fight (the screen
that plays the fighter's intro clip, demo rows 10 and 11).

    (cwd app/backend) LOOK_OUT=<folder> python classic_probe.py <iso> <tile x> <tile y>

The menus are driven by their own state (mn MenuFlow: the menu's kind and the row under the cursor), one press at
a time: out of the netplay build's Online menu, 1-P Mode, Regular Match, Classic. It never presses A on a row it
has not read, and gives up if the scene is ever the online one. On the character screen the cursor is steered to
the tile (the place the project's css.json gives it, y turned over) and START pressed.
"""
import os
import struct
import sys
import threading
import time
from pathlib import Path

import _where  # noqa: E402

sys.path.insert(0, str(_where.BACKEND))
from core.config import STORAGE_PATH  # noqa: E402
from shared.ingame.boot import DolphinBoot  # noqa: E402
from shared.ingame.melee_mem import Dolphin  # noqa: E402
from shared.ingame.melee_pipe import Pipe  # noqa: E402
from shared.ingame.melee_css import Cursor  # noqa: E402
from shared.ingame import nav  # noqa: E402
sys.path.insert(0, str(_where.BACKEND / 'devtools'))
import frameshot as fs  # noqa: E402

OUT = Path(os.environ.get('LOOK_OUT', '.'))
iso, TX, TY = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
DEADLINE = 240
WATCH = float(os.environ.get('PROBE_WATCH', '16'))
KIND_MAIN, KIND_1P, KIND_REG = 0, 1, 6             # mn/forward.h MenuKind
PERF = 0x80407188


def log(m):
    print(m, flush=True)


boot = DolphinBoot(str(iso), None, str(Path(STORAGE_PATH) / 'test-runs'), log=lambda m: None)
p = None


def _overrun():
    print(f'PROBE DEADLINE PASSED after {DEADLINE} s: ending its Dolphin', flush=True)
    try:
        boot.cleanup()
    finally:
        os._exit(3)


_watch = threading.Timer(DEADLINE, _overrun)
_watch.daemon = True
_watch.start()

try:
    boot.prepare()
    boot.launch()
    log(f'Dolphin pid {boot.pid}')
    if not boot.wait_for_pipe(timeout=45):
        raise SystemExit('input pipe never appeared')
    d = Dolphin(boot.pid)
    t0 = time.time()
    while not d.locate() and time.time() - t0 < 20:
        if not d.alive():
            raise SystemExit('Dolphin died during boot')
        time.sleep(0.4)
    p = Pipe(boot.pipe_index)
    nav.wait_menu_ready(d, log=lambda m: None)
    scene = lambda: (d.u8(nav.SCENE_MAJOR), d.u8(nav.SCENE_MINOR))
    start = time.time()
    for _ in range(40):
        major = d.u8(nav.SCENE_MAJOR)
        if major == nav.ONLINE_CSS:
            p.press('B')
            time.sleep(2.0)
            p.release('B')
            raise SystemExit('landed on the online screen: backed out and stopped')
        if major != nav.MENU_MAJOR:
            if major not in (0, None):
                break
            time.sleep(0.2)
            continue
        state = nav.menu_flow(d)
        if state is None:
            raise SystemExit('the menu state cannot be read')
        cur, hov = state
        if cur in (KIND_MAIN, KIND_1P, KIND_REG):
            btn = 'A' if hov == 0 else 'D_UP'
        else:
            btn = 'B'
        log(f'menu kind {cur} row {hov} -> {btn}')
        p.tap(btn, 0.06)
        time.sleep(1.5 if btn == 'A' else 0.25)
        if time.time() - start > 60:
            raise SystemExit('the menus took too long')
    log(f'left the menus: scene {scene()}')
    time.sleep(3.0)
    log(f'scene {scene()}')
    fs.capture(boot, OUT / 'classic-css0.png')
    cur = Cursor(d, p)
    ok = cur.select(TX, TY, costume=0, lock=True)
    log(f'cursor at {cur.read_pos()}, hovered {cur.hovered()}, locked {cur.locked()}, select said {ok}')
    time.sleep(0.4)
    fs.capture(boot, OUT / 'classic-css1.png')
    p.tap('START', 0.08)
    began, last, shots = time.time(), scene(), 0
    first, presses = last, 1
    while time.time() - began < WATCH:
        if not d.alive():
            log('DOLPHIN DIED')
            raise SystemExit(2)
        now = scene()
        if now == first and presses < 4 and time.time() - began > 2.0 * presses:
            # a START the screen did not take (it came before the lock had settled: once in three runs): again
            log(f'{time.time() - began:.1f} s: still on the character screen; START again')
            p.tap('START', 0.08)
            presses += 1
        if now != last:
            log(f'{time.time() - began:.1f} s: scene {last} -> {now}')
            last = now
        if time.time() - began >= shots * 0.5:
            perf = struct.unpack('>3f', d.bytes(PERF, 12))
            fs.capture(boot, OUT / f'classic-{shots:02d}.png')
            log(f'picture classic-{shots:02d}.png at {time.time() - began:.1f} s, scene {now}, frame time {perf[2]:.3f}')
            shots += 1
        time.sleep(0.05)
    log(f'Dolphin alive at the end: {d.alive()}; last scene {last}')
finally:
    if p is not None:
        try:
            p.close()
        except Exception:
            pass
    boot.cleanup()
