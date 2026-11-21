"""Play a short timed match to its end, let the results screen come up, and photograph it.

A copy of cloud-oneshot/results_probe.py with three differences:

  * The Slippi Dolphin the harness runs turns the results screen off by itself: its "Required: General Codes"
    (Sys/GameSettings/GALE01r2.ini) carry "Salty Runback" (C21A5B14), which replaces the instruction in the
    match's exit (gm_801A5AF0 + 0x24) that keeps the next scene's number (4, the results screen) with code
    that makes it 0 (the character select) or, with A+B held, 2 (the match again). This probe finds that
    code's body in the game's memory once the game is up and changes its `li r27, 0` to `li r27, 4`, in its
    own Dolphin only. Nothing on the disc or in any folder changes.
  * The clock is cut to two seconds once the KO is in, so a run is short.
  * On the results screen it reads each player's demo fighter (its demo action, the clip's frame, the clip
    the engine has loaded) and the game's own frame time, and takes pictures: close together while the
    victory clip plays, then every second and a half.

PROBE_CKIND / PROBE_BAG: the first and second fighters (external ids, hex). PROBE_HOLD: a button held on the
first pad while the results screen loads (B, Y or X pick the first, second or third victory pose;
gmresultplayer.c fn_8017A67C). LOOK_OUT: where the pictures go.

Usage (cwd app/backend): python results_probe_dh.py <full path to iso>
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
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID  # noqa: E402
from shared.ingame.observe import wait_in_game, wait_game_frames, SCENE_MAJOR, SCENE_SUBSTATE  # noqa: E402
from shared.ingame import nav, match_setup  # noqa: E402
from shared.ingame.gamestate import Player, Bag  # noqa: E402
sys.path.insert(0, str(_where.BACKEND / 'devtools'))
import frameshot as fs  # noqa: E402

OUT = Path(os.environ.get('LOOK_OUT', '.'))
CKIND = int(os.environ.get('PROBE_CKIND', '0x1A'), 16)
BAG = int(os.environ.get('PROBE_BAG', '0x01'), 16)
HOLD = os.environ.get('PROBE_HOLD', '')
TAG = os.environ.get('PROBE_TAG', f'{CKIND:02x}')
iso = Path(sys.argv[1])
DEADLINE = 240
RESULTS_FOR = float(os.environ.get('PROBE_WATCH', '14'))    # seconds of results screen to watch
QUICK = (14, 0.35)                                  # the first pictures come this many, this far apart (seconds)
TIMER_SECONDS = 0x8046B6A0 + 0x28                   # the match's clock (gm/types.h lbl_8046B6A0_t.timer_seconds)
PERF = 0x80407188                                   # HSD_PerfLastStat: three floats, shares of a sixtieth of a second
SALTY = bytes.fromhex('C21A5B14 0000000A 3BA00000 7FA3EB78 3D80801A 618C3680')
SALTY_LI = 0x48                                     # from the code's header to its `li r27, 0`
EXIT_HOOK = 0x801A5B14                              # gm_801A5AF0 + 0x24, where that code is hooked in
GC_BASE = 0x80000000


def log(m):
    print(m, flush=True)


def show_results_screen(d):
    """Make the match's exit go to the results screen again. -> the address patched, or None."""
    hook = d.u32(EXIT_HOOK) or 0
    log(f'the instruction at {EXIT_HOOK:#x} is {hook:#010x}')
    if hook >> 26 == 18:                            # a branch: the code's body is where it goes
        off = hook & 0x03FFFFFC
        body = EXIT_HOOK + (off - 0x04000000 if off & 0x02000000 else off)
        where = body + SALTY_LI - 8
    else:
        image = d.snapshot()
        at = image.find(SALTY) if image else -1
        if at < 0:
            return None
        where = GC_BASE + at + SALTY_LI
    if d.u32(where) != 0x3B600000:
        log(f'the code at {where:#x} is {d.u32(where):#x}, not li r27,0: left alone')
        return None
    d.write_u32(where, 0x3B600004)
    return where


def demo_fighter(d, port):
    """What a player's fighter on the results screen is doing, read from its Fighter struct."""
    pl = Player(d, port)
    ft = pl.resolve()
    if not ft or not (GC_BASE <= ft < GC_BASE + 0x1800000):
        return None
    return dict(kind=d.u32(ft + 0x04), action=d.u32(ft + 0x10), frame=round(d.f32(ft + 0x894) or 0.0, 1),
                clips=d.u32(ft + 0x58C), clip=d.u32(ft + 0x590), anim_id=d.u32(ft + 0x14))


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
    if os.environ.get('PROBE_AUDIO'):
        # Dolphin writes what the game's sound chip puts out to User/Dump/Audio/dspdump.wav as it runs
        from shared.ingame import boot as boot_module
        boot_module._write_ini(os.path.join(str(boot.user_dir), 'Config', 'Dolphin.ini'),
                               lambda upsert, _replace: (upsert('DSP', 'DumpAudio', 'True'), upsert('DSP', 'DumpAudioSilent', 'True')))
    boot.launch()
    log(f'Dolphin pid {boot.pid}; run folder {boot.run_dir}')
    if not boot.wait_for_pipe(timeout=45):
        raise SystemExit('input pipe never appeared')
    d = Dolphin(boot.pid)
    t0 = time.time()
    while not d.locate() and time.time() - t0 < 20:
        if not d.alive():
            raise SystemExit('Dolphin died during boot')
        time.sleep(0.4)
    match_setup.patch_one_player(d, log=lambda m: None)
    p = Pipe(boot.pipe_index)
    if not nav.nav_to_css(d, p, log=lambda m: None):
        raise SystemExit('never reached the offline CSS')
    nav.wait_css_ready(d, Cursor(d, p), log=lambda m: None)
    patched = show_results_screen(d)
    log(f'results screen: the skip code patched at {patched:#x}' if patched else
        'results screen: the skip code was NOT found in memory')
    d.write_u8(match_setup.RULES_MODE, 0)               # a timed match
    d.write_u8(match_setup.RULES_TIME, 1)               # of one minute
    match_setup.write_bag_player(d, CKIND, 0, bag_ckind=BAG, bag_color=0)
    match_setup.warp_to_stage_select(d)
    sc = StageCursor(d, p)
    if not sc.wait_for_stage_select(timeout=8.0):
        raise SystemExit('CSS->SSS warp did not land')
    match_setup.write_bag_player(d, CKIND, 0, bag_ckind=BAG, bag_color=0)
    if not sc.force_select(INTERNAL_STAGE_ID['finaldestination']):
        raise SystemExit('match never started')
    wait_in_game(d, timeout=25.0)
    began = time.time()
    wait_game_frames(d, 200)
    match_setup.fix_player_pad_indices(d, [0, 1], log=lambda m: None)
    me, bag = Player(d, 0), Bag(d, port=1)
    me.resolve()
    if not bag.resolve():
        raise SystemExit('the bag never spawned')
    # one KO: the second fighter at a high percent takes a forward smash
    me.set_pos(-40.0, 20.0)
    bag.set_pos(60.0, 20.0)
    p.neutral()
    time.sleep(1.6)
    p.main(1.0, 0.5)
    time.sleep(0.05)
    p.neutral()
    time.sleep(0.9)
    bag.park_in_front(me, dx=12.0, dy=0.0)
    bag.set_percent(300)
    time.sleep(0.3)
    p.main(1.0, 0.5)
    p.press('A')
    time.sleep(0.08)
    p.release('A')
    p.neutral()
    time.sleep(3.0)
    log(f'after the smash: fighter state {me.state()}, second fighter percent {bag.percent()}')
    log(f'the clock says {d.u32(TIMER_SECONDS)} s; cut to 2')
    d.write_u32(TIMER_SECONDS, 2)
    if HOLD:
        p.press(HOLD)
        log(f'holding {HOLD} on the first pad')
    scene = lambda: (d.u8(SCENE_MAJOR), d.u8(SCENE_SUBSTATE))
    last, ended, seen, shots = scene(), None, [], 0
    log(f'scene in the match (major, minor state): {last}')
    while time.time() - began < 110:
        if not d.alive():
            log('DOLPHIN DIED')
            raise SystemExit(2)
        now = scene()
        if now != last:
            log(f'{time.time() - began:.1f} s after the match began: scene {last} -> {now}')
            last = now
            if ended is None and now != (2, 2):
                ended = time.time()
        if ended is not None and time.time() - ended > RESULTS_FOR:
            break
        if ended is not None:
            since = time.time() - ended
            row = (demo_fighter(d, 0), demo_fighter(d, 1))
            perf = struct.unpack('>3f', d.bytes(PERF, 12))
            key = tuple((r or {}).get('action') for r in row)
            if not seen or seen[-1] != key:
                seen.append(key)
                log(f'{since:5.1f} s: first {row[0]}  second {row[1]}')
            if since >= (shots * QUICK[1] if shots < QUICK[0] else QUICK[0] * QUICK[1] + (shots - QUICK[0]) * 1.5):
                shot = OUT / f'results-{TAG}-{shots:02d}.png'
                fs.capture(boot, shot)
                log(f'picture {shot.name} at {since:.1f} s, scene {now}; first frame {(row[0] or {}).get("frame")} '
                    f'action {(row[0] or {}).get("action")}; second frame {(row[1] or {}).get("frame")} action '
                    f'{(row[1] or {}).get("action")}; frame time {perf[0]:.3f} logic, {perf[1]:.3f} with drawing, '
                    f'{perf[2]:.3f} all')
                shots += 1
        time.sleep(0.05)
    if ended is None:
        log('the match never ended')
    log(f'Dolphin alive at the end: {d.alive()}; last scene {last}; demo actions seen (first, second): {seen}')
finally:
    if p is not None:
        try:
            p.close()
        except Exception:
            pass
    if os.environ.get('PROBE_AUDIO') and boot.user_dir:
        import shutil
        boot.terminate()                                # the file is whole once the game has stopped
        time.sleep(1.0)
        dump_ = Path(str(boot.user_dir)) / 'Dump' / 'Audio' / 'dspdump.wav'
        if dump_.exists():
            shutil.copyfile(dump_, os.environ['PROBE_AUDIO'])
            print('sound file kept:', os.environ['PROBE_AUDIO'], dump_.stat().st_size, 'bytes', flush=True)
        else:
            print('no sound file was written', flush=True)
    boot.cleanup()
