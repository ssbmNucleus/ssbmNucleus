"""How full the game's file heaps are in a match (lbmemory.c: six heaps, each a list of what is held in it).

Usage (cwd app/backend): python heap_probe.py <iso>
    PROBE_CKIND      the fighter's number on the roster (0x1A: the first added fighter)     PROBE_COLOR      its costume
    PROBE_BAG        the second fighter's (0x01 Donkey Kong; 0x0C Peach, the game's largest) PROBE_BAG_COLOR  its costume
    PROBE_STAGE      finaldestination (the smallest), pokemonstadium (the largest), battlefield, dreamland, ...
    PROBE_WATCH      seconds more to stay and print the heaps again, a line every eight
    LOOK_OUT         a folder: a picture of the screen is left there, to LOOK AT
Boots a match of the fighter and a second one, waits, and prints each heap: its bounds, every file it holds by
size (and by name, where one file of the disc has that size), what is free and the largest free run.

The three matches a new fighter is read in (each with LOOK_OUT, and its picture looked at):
    PROBE_BAG=0x0C PROBE_STAGE=pokemonstadium                    beside Peach on Pokemon Stadium
    PROBE_BAG=0x1A PROBE_BAG_COLOR=1                             two of the fighter in two costumes, Final Destination
    PROBE_BAG=0x1A PROBE_BAG_COLOR=1 PROBE_STAGE=pokemonstadium  the same on Pokemon Stadium

Whether the match loaded is asked of the MATCH: both fighters exist (the game has made each one's object and its
fighter data) and the game's frame counter moves while they do. It says IN THE MATCH or THE MATCH DID NOT LOAD
from that alone. (It used to say "in the match" whenever its wait came back, and its wait comes back at its time
limit too: two matches that never loaded, a costume too large to be held twice, were written down as passes with
"2.2 MB free", which was what was left when loading stopped.) A match that did not load ends the probe with exit
code 2, and its free figures are of a heap that stopped filling, not of a match.
Its Dolphin is ended at its deadline.
"""
import os
import sys
import threading
import time
from pathlib import Path

ALLOC = 0x804318B0                                      # lbMemory_804318B0
HEAPS = 6
FRAME_COUNTER = 0x80479D60                              # the game's own count of frames (shared/ingame/observe.py)
MOST_HELD = 200                                         # a heap's list is walked no further than this


def heap_rows(u32, alloc=ALLOC):
    """Every heap as the game holds it, read through `u32(address)`. -> [dict(heap, lo, hi, held (the size of each
    thing held, in the list's own order), free, largest_run)]; a heap the game has not set up is left out."""
    rows = []
    for i in range(HEAPS):
        h = alloc + 0x638 + 0x10 * i
        lo, hi, first = u32(h + 4), u32(h + 8), u32(h + 0xC)
        if not lo or not hi or hi <= lo:
            continue
        held, at, gaps, entry = [], lo, [], first
        while entry and len(held) < MOST_HELD:
            e_lo, e_size = u32(entry + 4), u32(entry + 8)
            gaps.append(e_lo - at)
            held.append(e_size)
            at = e_lo + e_size
            entry = u32(entry)
        gaps.append(hi - at)
        rows.append(dict(heap=i, lo=lo, hi=hi, held=held, free=sum(g for g in gaps if g > 0), largest_run=max(gaps)))
    return rows


def names_by_size(disc_files):
    """{a size as a heap holds it: the disc's files of that size}. A file is held whole, in a place rounded up to 32
    bytes. `disc_files`: [{'name', 'size'}] (the disc's own list)."""
    out = {}
    for f in disc_files:
        out.setdefault(-(-int(f['size']) // 32) * 32, []).append(f['name'])
    return out


NAMED_FROM = 4096                                       # a held thing smaller than this is not a file to name


def heap_lines(rows, names=None):
    """The heaps as lines to print: each heap's bounds and totals, then every thing it holds, largest first, by size
    and by the name of the disc's file of that size (several files of one size, a fighter's costumes, are said as
    one of them; a thing of a few bytes is the game's own bookkeeping and is not named)."""
    names = names or {}
    lines = []
    for r in rows:
        lines.append(f"  heap {r['heap']}: {r['lo']:#x}..{r['hi']:#x} ({(r['hi'] - r['lo']) / 1e6:.2f} MB); "
                     f"{len(r['held'])} things held, {sum(r['held']) / 1e6:.2f} MB; free {r['free'] / 1e6:.2f} MB, "
                     f"largest run {r['largest_run'] / 1e6:.2f} MB")
        for size in sorted(r['held'], reverse=True):
            who = (names.get(size) or names.get(-(-size // 32) * 32) or []) if size >= NAMED_FROM else []
            said = (' or '.join(who) if len(who) <= 3 else
                    f"one of {len(who)} files of that size ({', '.join(who[:3])} ...)")
            lines.append(f"      {size:>10,} bytes" + (f'  {said}' if who else ''))
    return lines


def loaded(fighters, frames, scene=True):
    """Whether the match is running, from the match itself. `fighters`: what was read of each port's fighter
    ([dict(port, ft (its data's address, or None when the game has made no fighter), state)]); `frames`: the game's
    frame counter read twice, a moment apart; `scene`: whether the game says it is in a match at all (true while
    one still loads, so it can only say no). -> (True or False, why, in words)"""
    if not scene:
        return False, 'the game is not in a match (it never left the menus, or left the match again)'
    absent = [f['port'] + 1 for f in fighters if not f.get('ft') or f.get('state') is None]
    if absent:
        return False, ('the game has made no fighter for player ' + ' and '.join(str(n) for n in absent)
                       + ': the match is not running (the screen is the stage select fading out, or black)')
    if frames[0] is None or frames[1] is None or frames[1] <= frames[0]:
        return False, f"the game's frame counter does not move ({frames[0]} then {frames[1]}): the game has stopped"
    return True, f"{len(fighters)} fighters exist and the frame counter runs ({frames[0]} then {frames[1]})"


def main(argv=None):
    import _where
    sys.path.insert(0, str(_where.BACKEND))
    from core.config import STORAGE_PATH
    from shared.ingame.boot import DolphinBoot
    from shared.ingame.melee_mem import Dolphin
    from shared.ingame.melee_pipe import Pipe
    from shared.ingame.melee_css import Cursor
    from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID
    from shared.ingame.observe import wait_in_game
    from shared.ingame.gamestate import Player
    from shared.ingame import nav, match_setup

    argv = sys.argv[1:] if argv is None else argv
    ckind = int(os.environ.get('PROBE_CKIND', '0x1A'), 16)
    second = int(os.environ.get('PROBE_BAG', '0x01'), 16)
    color, second_color = int(os.environ.get('PROBE_COLOR', '0')), int(os.environ.get('PROBE_BAG_COLOR', '0'))
    stage = os.environ.get('PROBE_STAGE', 'finaldestination')
    watch = float(os.environ.get('PROBE_WATCH', '0'))
    deadline = 120 + int(watch)
    iso = Path(argv[0])
    boot = DolphinBoot(str(iso), None, str(Path(STORAGE_PATH) / 'test-runs'), log=lambda m: None)

    def overrun():
        print(f'PROBE DEADLINE PASSED after {deadline} s: ending its Dolphin', flush=True)
        try:
            boot.cleanup()
        finally:
            os._exit(3)

    timer = threading.Timer(deadline, overrun)
    timer.daemon = True
    timer.start()
    names = {}
    try:                                                # (names for the sizes: the disc's own list of files)
        from shared.vanilla_extract import vanilla_refs
        names = names_by_size(vanilla_refs.list_files_in_iso(str(iso)))
    except Exception as exc:                            # noqa: BLE001 (the sizes are still printed)
        print(f"(the disc's file list was not read, so sizes are not named: {type(exc).__name__}: {exc})", flush=True)

    def heaps(d):
        print('\n'.join(heap_lines(heap_rows(d.u32), names)), flush=True)

    pipe, code = None, 0
    try:
        boot.prepare()
        boot.launch()
        if not boot.wait_for_pipe(timeout=45):
            raise SystemExit('input pipe never appeared')
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            time.sleep(0.4)
        match_setup.patch_one_player(d, log=lambda m: None)
        pipe = Pipe(boot.pipe_index)
        if not nav.nav_to_css(d, pipe, log=lambda m: None):
            raise SystemExit('never reached the offline CSS')
        nav.wait_css_ready(d, Cursor(d, pipe), log=lambda m: None)
        print('at the character select screen:', flush=True)
        heaps(d)
        match_setup.force_time_infinite(d, log=lambda m: None)
        match_setup.write_bag_player(d, ckind, color, bag_ckind=second, bag_color=second_color)
        match_setup.warp_to_stage_select(d)
        sc = StageCursor(d, pipe)
        if not sc.wait_for_stage_select(timeout=8.0):
            raise SystemExit('CSS->SSS warp did not land')
        match_setup.write_bag_player(d, ckind, color, bag_ckind=second, bag_color=second_color)
        if not sc.force_select(INTERNAL_STAGE_ID[stage]):
            print('the stage select did not take the stage', flush=True)
        scene = wait_in_game(d, timeout=20.0)          # (the scene's word only: it is true while a match still loads)
        time.sleep(3.0)
        # ... and the match's own: its fighters, and its frames moving
        fighters = []
        for port in (0, 1):
            who = Player(d, port)
            ft = who.resolve()
            fighters.append(dict(port=port, ft=ft, state=who.state() if ft else None,
                                 kind=who.kind() if ft else None, costume=who.costume_id() if ft else None))
        before = d.u32(FRAME_COUNTER)
        time.sleep(0.5)
        ok, why = loaded(fighters, (before, d.u32(FRAME_COUNTER)), scene)
        asked = f'fighter {ckind:#x} colour {color}, second {second:#x} colour {second_color}, on {stage}'
        if ok:
            print(f"IN THE MATCH ({asked}): {why}; the fighters' own kinds and costumes: "
                  f"{[(f['kind'], f['costume']) for f in fighters]}", flush=True)
        else:
            code = 2
            print(f'THE MATCH DID NOT LOAD ({asked}): {why}. The heaps below are as loading left them: their free '
                  'figures are NOT room to spare.', flush=True)
        heaps(d)
        began = time.time()
        while time.time() - began < watch:
            time.sleep(8.0)
            print(f'{time.time() - began:.0f} s on (Dolphin alive: {d.alive()}):', flush=True)
            heaps(d)
        if os.environ.get('LOOK_OUT'):                 # a picture of the screen as the game draws it: look at it
            sys.path.insert(0, str(_where.BACKEND / 'devtools'))
            import frameshot as fs
            shot = Path(os.environ['LOOK_OUT']) / f'match-{stage}-{second:02x}.png'
            fs.capture(boot, shot)
            print('picture', shot, '(look at it: a match that did not load shows the stage select screen or black)',
                  flush=True)
    finally:
        if pipe is not None:
            try:
                pipe.close()
            except Exception:                           # noqa: BLE001
                pass
        boot.cleanup()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
