"""Every move, facing each way, photographed on the frames its hits come out: frame-exact (the game is stepped a
frame at a time and the pad is set between steps).

Usage (cwd app/backend): python sheet_probe.py <iso, full path> <port work dir> <out dir> [<move> ...]
  env PROBE_CKIND (the fighter's external id, default 0x1A), PROBE_BAG (default 0x01)
A move's pictures are <out>/<move>-<r|l><n>.png; the frames photographed are the first frames of its first and last
hits as the port's own combat.json has them (or the frames given in MOVES).

How long it takes, and its deadline. A boot is about 40 s and a move, both ways, about 14. The probe ends its own
Dolphin after 110 + 14 seconds a move (`DEADLINE`) and says then which moves it finished, which it was in and which
it never began. A caller with a time limit of its own must leave the probe its deadline: killed from outside
first, it cannot end its Dolphin, and that Dolphin is left running. Under a limit of 280 s that is AT MOST TWELVE
moves a call (110 + 14 x 12 = 278); with no moves named it runs every move in MOVES, which is minutes more than
that. A deadline with moves left over is not "too many moves": at 14 s a move the time was there, so the game
stopped in the move named (run that move alone again before anything is changed) or the machine was busy.
"""
import json
import os
import sys
import _where  # noqa: E402
import threading
import time
from pathlib import Path

sys.path.insert(0, str(_where.BACKEND))
from core.config import STORAGE_PATH  # noqa: E402
from shared.ingame.boot import DolphinBoot  # noqa: E402
from shared.ingame.melee_mem import Dolphin  # noqa: E402
from shared.ingame.melee_pipe import Pipe  # noqa: E402
from shared.ingame.melee_css import Cursor  # noqa: E402
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID  # noqa: E402
from shared.ingame.observe import wait_in_game, wait_game_frames  # noqa: E402
from shared.ingame import nav, match_setup, framestep  # noqa: E402
from shared.ingame.gamestate import Player, Bag  # noqa: E402
sys.path.insert(0, str(_where.BACKEND / 'devtools'))
import frameshot as fs  # noqa: E402

CKIND = int(os.environ.get('PROBE_CKIND', '0x1A'), 16)
BAG = int(os.environ.get('PROBE_BAG', '0x01'), 16)
iso, work, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
BG = '404040'
F, BK, U, D_, N = 'stick 1.0 0.5', 'stick 0.0 0.5', 'stick 0.5 1.0', 'stick 0.5 0.0', 'neutral'

# name: (donor action whose hit frames to photograph, or None; [(frame, action)], the trigger's frame, frames to
# photograph when there is no profile, how far ahead the bag stands)
# The stick's sideways actions are for a fighter facing right: facing left they are mirrored.
MOVES = {
    'jab1': ('Attack11', [(0, 'A+'), (3, 'A-')], 0, [4, 8], 40),
    'jab2': ('Attack12', [(0, 'A+'), (3, 'A-'), (9, 'A+'), (12, 'A-')], 9, [5, 9], 40),
    'jab3': ('Attack13', [(0, 'A+'), (3, 'A-'), (9, 'A+'), (12, 'A-'), (18, 'A+'), (21, 'A-'), (27, 'A+'), (30, 'A-')], 18, [5, 9], 40),
    'ftilt': ('AttackS3S', [(0, 'stick 0.68 0.5'), (4, 'A+'), (7, 'A-'), (8, N)], 4, [8, 12], 40),
    'utilt': ('AttackHi3', [(0, 'stick 0.5 0.68'), (4, 'A+'), (7, 'A-'), (8, N)], 4, [8, 12], 40),
    'dtilt': ('AttackLw3', [(0, D_), (10, 'A+'), (13, 'A-'), (14, N)], 10, [6, 10], 40),
    'dash': ('AttackDash', [(0, F), (12, 'A+'), (15, 'A-'), (16, N)], 12, [9, 14], 60),
    'fsmash': ('AttackS4S', [(0, F), (0, 'A+'), (3, 'A-'), (4, N)], 0, [18, 24], 40),
    'usmash': ('AttackHi4', [(0, U), (0, 'A+'), (3, 'A-'), (4, N)], 0, [12, 18], 40),
    'dsmash': ('AttackLw4', [(0, D_), (0, 'A+'), (3, 'A-'), (4, N)], 0, [10, 18], 40),
    'nair': ('AttackAirN', [(0, 'X+'), (20, 'X-'), (22, 'A+'), (25, 'A-')], 22, [6, 12], 40),
    'fair': ('AttackAirF', [(0, 'X+'), (20, 'X-'), (22, F), (22, 'A+'), (25, 'A-'), (26, N)], 22, [10, 16], 40),
    'bair': ('AttackAirB', [(0, 'X+'), (20, 'X-'), (22, BK), (22, 'A+'), (25, 'A-'), (26, N)], 22, [10, 16], 40),
    'uair': ('AttackAirHi', [(0, 'X+'), (20, 'X-'), (22, U), (22, 'A+'), (25, 'A-'), (26, N)], 22, [8, 14], 40),
    'dair': ('AttackAirLw', [(0, 'X+'), (20, 'X-'), (22, D_), (22, 'A+'), (25, 'A-'), (26, N)], 22, [10, 16], 40),
    'grab': ('Catch', [(0, 'R+'), (0, 'A+'), (3, 'A-'), (3, 'R-')], 0, [8, 14], 40),
    'dashgrab': ('CatchDash', [(0, F), (12, 'R+'), (12, 'A+'), (15, 'A-'), (15, 'R-'), (16, N)], 12, [11, 16], 60),
    'pummel': (None, [(0, 'R+'), (0, 'A+'), (3, 'A-'), (3, 'R-'), (40, 'A+'), (43, 'A-')], 40, [4, 8], 9),
    'throwf': ('ThrowF', [(0, 'R+'), (0, 'A+'), (3, 'A-'), (3, 'R-'), (40, F), (46, N)], 40, [8, 14], 9),
    'throwb': ('ThrowB', [(0, 'R+'), (0, 'A+'), (3, 'A-'), (3, 'R-'), (40, BK), (46, N)], 40, [8, 14], 9),
    'throwhi': ('ThrowHi', [(0, 'R+'), (0, 'A+'), (3, 'A-'), (3, 'R-'), (40, U), (46, N)], 40, [8, 14], 9),
    'throwlw': ('ThrowLw', [(0, 'R+'), (0, 'A+'), (3, 'A-'), (3, 'R-'), (40, D_), (46, N)], 40, [8, 14], 9),
    'spotdodge': (None, [(0, 'R+'), (14, D_), (18, N), (20, 'R-')], 14, [6, 14], 40),
    'rollf': (None, [(0, 'R+'), (14, F), (18, N), (20, 'R-')], 14, [8, 18], 40),
    'rollb': (None, [(0, 'R+'), (14, BK), (18, N), (20, 'R-')], 14, [8, 18], 40),
    'shield': (None, [(0, 'R+'), (30, 'R-')], 0, [10, 20], 40),
    'airdodge': (None, [(0, 'X+'), (20, 'X-'), (22, 'R+'), (25, 'R-')], 22, [6, 16], 40),
    'neutralb': (None, [(0, 'B+'), (4, 'B-')], 0, [10, 20, 30], 60),
    'sideb': (None, [(0, F), (1, 'B+'), (5, 'B-'), (6, N)], 1, [10, 18, 26], 40),
    'upb': (None, [(0, U), (1, 'B+'), (5, 'B-'), (6, N)], 1, [8, 16, 26], 40),
    'downb': (None, [(0, D_), (1, 'B+'), (5, 'B-'), (6, N)], 1, [12, 30, 60], 40),
    'neutralb_air': (None, [(0, 'X+'), (20, 'X-'), (22, 'B+'), (26, 'B-')], 22, [10, 20, 30], 60),
    'sideb_air': (None, [(0, 'X+'), (20, 'X-'), (22, F), (23, 'B+'), (27, 'B-'), (28, N)], 23, [10, 18, 26], 40),
    'upb_air': (None, [(0, 'X+'), (20, 'X-'), (22, U), (23, 'B+'), (27, 'B-'), (28, N)], 23, [8, 16, 26], 40),
    'downb_air': (None, [(0, 'X+'), (20, 'X-'), (22, D_), (23, 'B+'), (27, 'B-'), (28, N)], 23, [12, 30, 60], 40),
    # a neutral special held: the charge, then let go
    'neutralb_held': (None, [(0, 'B+'), (70, 'B-')], 0, [40, 68, 78, 84], 60),
    'taunt': (None, [(0, 'D_UP+'), (3, 'D_UP-')], 0, [20, 50], 40),
    # the whip thrown from below a ledge, beside the stage's wall (SHEET_STAGE=yoshisstory: its walls run straight
    # down from its ledges at x = -56 and 56): in reach of the ledge, and too far below it
    'wall_ledge': (None, [(0, 'X+'), (7, 'place -100 30'), (9, 'place -70 -45'), (10, U), (11, 'B+'), (15, 'B-'), (16, N), (20, 'X-')], 11, [12, 30, 50], 40),
    'wall_low': (None, [(0, 'X+'), (7, 'place -100 30'), (9, 'place -70 -75'), (10, U), (11, 'B+'), (15, 'B-'), (16, N), (20, 'X-')], 11, [12, 30, 50], 40),
    'wall_lower': (None, [(0, 'X+'), (7, 'place -100 30'), (9, 'place -66 -85'), (10, U), (11, 'B+'), (15, 'B-'), (16, N), (20, 'X-')], 11, [12, 30, 50], 40),
    # a dash grab and a spot dodge, for how many frames each lasts (the states line counts frames)
}
wanted = sys.argv[4:] or list(MOVES)
_port = work / os.environ.get('PORT_DIR', 'port')              # the folder that holds combat.json
combat = json.loads((_port / 'combat.json').read_text('utf-8')) if (_port / 'combat.json').exists() else {'moves': []}


def frames_for(motion, fallback):
    prof = next((p for p in combat['moves'] if motion and motion in p['motions']), None)
    if not prof or not prof.get('phases'):
        if prof and prof.get('throw'):
            return [max(2, prof['throw']['release'] - 2), prof['throw']['release'] + 3]
        return list(fallback)
    first, last = prof['phases'][0], prof['phases'][-1]
    a, b = first['start'], (last['start'] if last is not first else min(first['end'], first['start'] + 3))
    return [a, b if b > a else a + 3]


def mirror(action):
    if action.startswith('stick'):
        _, x, y = action.split()
        return f'stick {1.0 - float(x):.2f} {y}'
    return action


boot = DolphinBoot(str(iso), None, str(Path(STORAGE_PATH) / 'test-runs'), log=lambda m: None)
p = None


finished, in_hand = [], []                               # the moves photographed both ways; the one being stepped now


def _overrun():
    left = [n for n in wanted if n not in finished and n not in in_hand]
    print(f'PROBE DEADLINE PASSED after {DEADLINE} s (110 + 14 a move, {len(wanted)} moves): finished {finished or "none"}; '
          f'it was in {in_hand or "no move yet (the boot, or the match starting)"}; never begun {left or "none"}. At 14 s a '
          'move the time was there for all of them: the game stopped where it was, or the machine was busy. Run the move '
          'it was in alone before changing anything; then the ones never begun. Ending its Dolphin', flush=True)
    try:
        boot.cleanup()
    finally:
        os._exit(3)


DEADLINE = 110 + 14 * len(wanted)
print(f'{len(wanted)} moves; this probe ends its own Dolphin after {DEADLINE} s (110 + 14 a move). A caller\'s own time '
      f'limit must be longer than that: 280 s allows twelve moves a call', flush=True)
_watch = threading.Timer(DEADLINE, _overrun)
_watch.daemon = True
_watch.start()
try:
    boot.prepare()
    boot.launch()
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
    match_setup.force_time_infinite(d, log=lambda m: None)
    match_setup.write_bag_player(d, CKIND, 0, bag_ckind=BAG, bag_color=0)
    match_setup.warp_to_stage_select(d)
    sc = StageCursor(d, p)
    if not sc.wait_for_stage_select(timeout=8.0):
        raise SystemExit('CSS->SSS warp did not land')
    match_setup.write_bag_player(d, CKIND, 0, bag_ckind=BAG, bag_color=0)
    if not sc.force_select(INTERNAL_STAGE_ID[os.environ.get('SHEET_STAGE', 'finaldestination')]):
        raise SystemExit('match never started')
    wait_in_game(d, timeout=25.0)
    wait_game_frames(d, 200)
    match_setup.fix_player_pad_indices(d, [0, 1], log=lambda m: None)
    me, bag = Player(d, 0), Bag(d, port=1)
    me.resolve()
    if not bag.resolve():
        raise SystemExit('the bag never spawned')
    fs.assert_plain_bg(d, BG)
    # with the game frozen: relinking the particle lists while it runs races the game's own update and can loop a
    # list, and the game hangs drawing it (look_probe.kill_stage_particles, G19)
    framestep.freeze(d)
    framestep.wait_render_frames(d, 2)
    try:
        fs.kill_stage_particles(d)
    except Exception:
        pass
    framestep.unfreeze(d)
    OUT.mkdir(parents=True, exist_ok=True)

    def act(action):
        if action == N:
            p.neutral()
        elif action.startswith('stick'):
            _, sx, sy = action.split()
            p.main(float(sx), float(sy))
        elif action.startswith('place'):
            me.set_pos(float(action.split()[1]), float(action.split()[2]))
        elif action.endswith('+'):
            p.press(action[:-1])
        elif action.endswith('-'):
            p.release(action[:-1])

    for name in wanted:
        motion, script, trigger, fallback, ahead = MOVES[name]
        shots = frames_for(motion, fallback)
        in_hand[:] = [name]
        for side in 'rl':
            framestep.unfreeze(d)
            p.neutral()
            for b in 'ABXZR':
                p.release(b)
            me.set_pos(-20.0 if side == 'r' else 20.0, 20.0)
            me.set_percent(0)
            bag.set_percent(0)
            time.sleep(1.5)
            p.main(1.0 if side == 'r' else 0.0, 0.5)
            time.sleep(0.05)
            p.neutral()
            time.sleep(0.7)
            bag.park_in_front(me, dx=float(ahead), dy=0.0)
            time.sleep(0.3)
            framestep.freeze(d)
            steps = sorted([(f, a if side == 'r' else mirror(a)) for f, a in script], key=lambda s: s[0])
            last = max(f for f, _ in steps)
            before, clock, seen, taken, track = None, None, [], 0, []
            for frame in range(last + max(shots) + 12):
                if frame == trigger:
                    before = me.state()                 # what it was doing before the move was asked for
                for f, a in steps:
                    if f == frame:
                        act(a)
                framestep.step(d, 1)
                s = me.state()
                if frame >= trigger and clock is None and s != before:
                    clock = 1                           # the move's first frame
                elif clock is not None:
                    clock += 1
                if not seen or seen[-1][0] != s:
                    seen.append((s, frame))
                if os.environ.get('SHEET_TRACK') and frame >= trigger:
                    x_, y_ = me.pos()
                    track.append((frame, s, round(x_, 1), round(y_, 1)))
                if clock is not None and taken < len(shots) and clock >= shots[taken]:
                    framestep.wait_render_frames(d, 2)
                    fs.capture(boot, OUT / f'{name}-{side}{taken}.png')
                    taken += 1
            framestep.unfreeze(d)
            p.neutral()
            for b in 'ABXZR':
                p.release(b)
            print(f'{name} {side}: photographed on frames {shots[:taken]} of {shots}; states (number, step) {seen[:12]}; faces {me.facing():+.0f}', flush=True)
            if track:
                print('   track (step, state, x, y):', track[::2], flush=True)
            time.sleep(0.8)
        finished.append(name)
        in_hand[:] = []
finally:
    if p is not None:
        try:
            p.close()
        except Exception:
            pass
    boot.cleanup()
