"""Does the game survive Kirby copying the port's fighter? Kirby is the first fighter, the port's fighter the
second (its copy data is only loaded when it is in the match); Kirby is given its ability the way the game's own
code does on a respawn (match_setup.install_kirby_copy_via_rebirth), then uses the copied special.

    (cwd app/backend) LOOK_OUT=<folder> python kirby_copy_probe.py <iso> [<donor external id, hex> [<donor internal id>]]

The first fighter a project adds is external 0x1A and internal 27. Says whether the game still steps afterwards
(a stop inside the game leaves Dolphin alive: the frame counter is what tells) and what the game's log says.
"""
import os
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
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID  # noqa: E402
from shared.ingame.observe import wait_in_game, wait_game_frames, FRAME_COUNTER  # noqa: E402
from shared.ingame import nav, match_setup  # noqa: E402
from shared.ingame.gamestate import Player  # noqa: E402
sys.path.insert(0, str(_where.BACKEND / 'devtools'))
import frameshot as fs  # noqa: E402

OUT = Path(os.environ.get('LOOK_OUT', '.'))
iso = Path(sys.argv[1])
DONOR_EXT = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x1A
DONOR_INT = int(sys.argv[3]) if len(sys.argv) > 3 else 27
KIRBY_EXT = 0x04
DEADLINE = 240


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


def steps(d, seconds=1.0):
    a = d.u32(FRAME_COUNTER)
    time.sleep(seconds)
    return (d.u32(FRAME_COUNTER) or 0) - (a or 0)


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
    match_setup.patch_one_player(d, log=lambda m: None)
    log(f'copy on respawn armed: {match_setup.arm_kirby_copy_ondeath(d, log=log)}')
    p = Pipe(boot.pipe_index)
    if not nav.nav_to_css(d, p, log=lambda m: None):
        raise SystemExit('never reached the offline CSS')
    nav.wait_css_ready(d, Cursor(d, p), log=lambda m: None)
    match_setup.write_bag_player(d, KIRBY_EXT, 0, bag_ckind=DONOR_EXT, bag_color=0)
    match_setup.warp_to_stage_select(d)
    sc = StageCursor(d, p)
    if not sc.wait_for_stage_select(timeout=8.0):
        raise SystemExit('CSS->SSS warp did not land')
    match_setup.write_bag_player(d, KIRBY_EXT, 0, bag_ckind=DONOR_EXT, bag_color=0)
    if not sc.force_select(INTERNAL_STAGE_ID['finaldestination']):
        raise SystemExit('match never started')
    wait_in_game(d, timeout=25.0)
    wait_game_frames(d, 200)
    match_setup.fix_player_pad_indices(d, [0, 1], log=lambda m: None)
    log(f'in the match; the game steps {steps(d)} frames a second')
    fs.capture(boot, OUT / 'kirby-0-before.png')
    # where m-ex keeps each fighter's hat for Kirby (a pointer a fighter, at rtoc + 0x124), and what the donor's
    # own hat code reads from it
    RTOC = 0x804DF9E0
    table = d.u32(RTOC + 0x124)
    ext_num, int_num = d.u32(RTOC + 0x14C), d.u32(RTOC + 0x148)
    entries = [d.u32(table + 4 * i) for i in range(min(ext_num or 0, 64))] if table else []
    log(f'hat table at {table:#x}; fighters {ext_num} outside, {int_num} inside; entries that hold a hat: '
        f'{[(i, hex(e)) for i, e in enumerate(entries) if e]}')
    log('the donor hat code at 0x800F084C: ' + ' '.join(f'{d.u32(0x800F084C + 4 * i):08x}' for i in range(4)))
    hat = match_setup.install_kirby_copy_via_rebirth(d, DONOR_INT, port=0, log=log)
    log(f'after the respawn Kirby wears the ability of fighter {hat} (asked for {DONOR_INT})')
    stepped = steps(d, 2.0)
    log(f'the game steps {stepped} frames in two seconds after it; Dolphin alive {d.alive()}')
    fs.capture(boot, OUT / 'kirby-1-copied.png')
    if stepped > 30:
        me = Player(d, 0)
        me.resolve()
        me.set_pos(-20.0, 0.0)
        time.sleep(1.5)
        p.press('B')
        time.sleep(0.1)
        p.release('B')
        for i in range(4):
            time.sleep(0.25)
            fs.capture(boot, OUT / f'kirby-2-special-{i}.png')
        log(f'Kirby in state {me.state()} after the special; the game steps {steps(d)} frames a second; alive {d.alive()}')
finally:
    if p is not None:
        try:
            p.close()
        except Exception:
            pass
    boot.cleanup()
