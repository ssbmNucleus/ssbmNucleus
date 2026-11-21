"""One boot of a built disc, any number of tests in it: the fighter and a second fighter ("the bag") in a match, the
pad driven, and for each test a line of what happened (states, how far and how high, what the bag took) and, where a
test asks, pictures.

Usage (cwd app/backend): python look_probe.py <iso> <test> [<test> ...]
A test is a name in MOVES below (`round.py --plan` lists them; a fighter's own are added there). Tests run in the
order given, in one match, so what one leaves (damage, an item, a stale move) is there for the next: put
`match_<costume>[_<second fighter, hex>[_<stage>]]` between two tests for a new match in the same boot (about six
seconds; pictures after it are named -c<costume>).

A test is a list of (seconds from its start, step). The step words:
  the pad         'A+' 'A-' (any button, pressed and let go: A B X Y Z L R START D_UP ...), 'stick x y' (0 to 1 each,
                  0.5 0.5 is the middle), 'neutral' (the stick back to the middle AND EVERY BUTTON LET GO: a button
                  meant to stay held needs 'stick 0.5 0.5' in its place), 'turn' (the fighter faces left: the stick
                  pushed left for 0.05 s, which is a DASH: a press while it runs, or into a game frozen during it, is
                  not taken; give it about a second), 'face -1' / 'face 1' (turned left / right where he stands, at
                  once: no dash; the one to use before 'freeze'). A special aimed on a diagonal (an up special) is
                  pressed with the stick straight up and aimed after: a diagonal held as B is pressed is the SIDE special
  the bag         'bag dx dy' (put that far in front of the fighter AS HE FACES THEN: put it after a turn, not before;
                  in the air it is only DRAWN there: the engine
                  stands a fighter on the floor each frame, so a hit that must land in the air needs a target that
                  jumped), 'pin' / 'unpin' (held where it was put, whatever hits it), 'bagpercent n', 'bagface 1' /
                  'bagface -1' (the bag turned right / left where it stands: its back to a fighter who faces it),
                  'pads a b' (which pad each fighter reads: 'pads 1 0' gives the pad to the bag and takes it from
                  the fighter; both cannot be driven at once)
  the fighter     'percent n', 'fill' (to 150% and back to 0: damage taken fills a gauge), 'place x y', 'lift dy',
                  'metal' (metal from its next spawn), 'model group choice' (one part group's choice, then two frames),
                  'tint r g b a how' / 'untint' (a colour laid over the body)
  one frame at a time   'freeze', 'unfreeze', 'step n' (n frames, nothing logged), 'steplog n' (n frames, a line for
                  each frame where something changed: state, clip frame, damage, place, the bag)
  pictures        'shot <name>' (-> <LOOK_OUT>/<test>-<name>.png), 'closeup distance height lens yaw' (the camera
                  parked for the pictures that follow: it stands at (sin yaw, cos yaw) x distance from the fighter in
                  x and z, `height` above its feet, and looks level: 0 is from the front of the stage, about 60 a
                  fighter's front when it faces right)
  readings        'perf <label>' (where a frame's time goes), 'vel' (its speeds), 'attrs' (its numbers as the game
                  holds them), 'hud' (where the damage figures stand), 'gauge ...', 'gfx n' (see their steps below)
  'end'           nothing: it only says how long the test goes on being watched

Settings (the environment):
  PROBE_CKIND     the fighter's number on the roster (0x1A: the first added fighter)    PROBE_COLOR  its costume
  PROBE_BAG       the second fighter's (0x01 Donkey Kong)     PROBE_MIRROR=1  the bag reads the fighter's own pad
  LOOK_OUT        the folder pictures go to                   LOOK_BG=RRGGBB  the flat background
  PROBE_CLOSEUP   'distance height lens yaw' for every picture of the run (a test's own 'closeup' comes after it)
  PROBE_STEPSHOT  'first-last': a picture at each stepped frame whose clip frame is in that span (NOTHING is
                  photographed by 'steplog' without it, and nothing says so)
  PROBE_FACESHOT=1  a picture at each stepped frame on which a part group's choice changes, the choices in its name
  PROBE_BOXES=1   the fighter's live hitboxes at each stepped frame      PROBE_HITS=1  the same while it runs free
  PROBE_TRACK=1   the first item in the match followed (a shot, a can) PROBE_FLAGS=1  the script's four flags
  PROBE_ITEMS=1   every item at each stepped frame (kind, state, x, y, speed sideways), a line where one changed
  PROBE_AUDIO     a file: the game's sound through the whole boot is kept there
  PROBE_PORTRAIT_CAM, PROBE_HEAD_CAM, PROBE_PORTRAIT_STEP, PROBE_EARS_CAM, PROBE_LATE, PROBE_GFX_*, PROBE_FACE_*
                  belong to the tests that read them (look_portrait, look_ears, the late aerials, gfx_*, face_*)

Its deadline. The probe ends its own Dolphin after 100 s + 9 a test + 20 a new match + PROBE_EXTRA seconds, and
says which test it was in. A caller's own time limit must be longer than that (killed from outside first, the probe
cannot end its Dolphin): under a limit of 280 s that is at most nineteen tests a call with no new match (100 + 9 x 19
= 271; twenty is 280, which is not shorter than the limit), fewer with long stepped tests (give those PROBE_EXTRA
and count it in).
"""
import os
import sys
import _where  # noqa: E402
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
import particle_check  # noqa: E402
OUT = Path(os.environ.get('LOOK_OUT', '.'))
BG = os.environ.get('LOOK_BG', '404040')

CKIND = int(os.environ.get('PROBE_CKIND', '0x1A'), 16)
BAG = int(os.environ.get('PROBE_BAG', '0x01'), 16)
iso = Path(sys.argv[1])
wanted = sys.argv[2:]

B = [(0.0, 'B+'), (0.08, 'B-')]
SIDE = [(0.0, 'stick 1.0 0.5'), (0.02, 'B+'), (0.10, 'B-'), (0.10, 'neutral')]
UP = [(0.0, 'stick 0.5 1.0'), (0.02, 'B+'), (0.10, 'B-'), (0.10, 'neutral')]
DOWN = [(0.0, 'stick 0.5 0.0'), (0.02, 'B+'), (0.10, 'B-'), (0.10, 'neutral')]
MASH = [(0.25 + 0.07 * i, 'B+' if i % 2 == 0 else 'B-') for i in range(24)]


def after(t, steps):
    return [(t + s, a) for s, a in steps]


def landing(stick, cancel=False):
    late = float(os.environ.get('PROBE_LATE', '0.45'))             # seconds from the jump to the aerial
    steps = [(0.0, 'bag 80 0'), (0.3, 'X+'), (0.42, 'X-'), (0.3 + late, stick), (0.32 + late, 'A+'), (0.40 + late, 'A-'),
             (0.42 + late, 'neutral'), (3.4, 'end')]
    if cancel:
        steps += [(0.44 + late + 0.05 * i, 'R+' if i % 2 == 0 else 'R-') for i in range(16)]
    return steps


def throw(stick):
    return [(0.0, 'bag 9 0'), (0.4, 'Z+'), (0.48, 'Z-'), (1.1, stick), (1.2, 'neutral'), (4.0, 'end')]


# A fighter of forms (fighter_port/forms.py): the switch, once to each form and back to the first, with a picture
# of each form as it arrives and stands; the wait between presses is longer than the switch's own (fighters.FORMS).
# On the ground facing right, the same facing left, and in the air.
def forms_cycle(first=0.0, every=3.2, turn=False, air=False):
    steps = [(0.0, 'bag 80 0'), (0.05, 'percent 37'), (0.1, 'who')] + ([(0.2, 'turn')] if turn else [])
    for i in range(3):
        t = first + 0.5 + every * i
        if air:
            steps += [(t - 0.3, 'X+'), (t - 0.22, 'X-')]
        steps += after(t, DOWN) + [(t + 0.12, 'shot leave%d' % i), (t + 0.45, 'shot arrive%d' % i), (t + 0.5, 'who'),
                                   (t + 1.6, 'shot stand%d' % i), (t + 1.65, 'who')]
    return steps + [(first + 0.5 + every * 3, 'end')]


# Each form's own moves after the switch brought it: a jab and its three specials, a picture of each, then the switch
# to the next (every form's states work in a fighter the transformation made, not only in the one the match began with)
def forms_moves(every=7.0):
    steps = [(0.0, 'bag 60 0'), (0.1, 'who')]
    for i in range(3):
        t = 0.4 + every * i
        steps += [(t, 'A+'), (t + 0.08, 'A-'), (t + 0.25, 'shot jab%d' % i)]
        steps += after(t + 0.9, SIDE) + [(t + 1.25, 'shot side%d' % i)]
        steps += after(t + 2.4, B) + [(t + 2.75, 'shot neutral%d' % i)]
        steps += after(t + 4.0, UP) + [(t + 4.3, 'shot up%d' % i)]
        steps += after(t + 6.2, DOWN) + [(t + 6.8, 'who')]
    return steps + [(0.4 + every * 3, 'end')]


MOVES = {
    'forms_moves': forms_moves(),
    # the switch a frame at a time (the handle stays on the form that leaves: its leaving state, then asleep)
    'forms_frames': [(0.4, 'freeze'), (0.4, 'stick 0.5 0.0'), (0.4, 'steplog 2'), (0.4, 'B+'), (0.4, 'steplog 2'), (0.4, 'B-'),
                     (0.4, 'neutral'), (0.4, 'steplog 32'), (0.4, 'who'), (0.4, 'unfreeze'), (1.0, 'end')],
    # the memory left before and after each switch: a form made mid-match whose files were loaded with the match
    # costs only the fighter made; one loaded then would cost its files too
    'forms_room': [(0.0, 'bag 80 0'), (0.1, 'room')] + [step for i in range(3) for step in (
        after(0.4 + 3.2 * i, DOWN) + [(1.6 + 3.2 * i, 'who'), (1.7 + 3.2 * i, 'room')])] + [(10.2, 'end')],
    'forms_cycle': forms_cycle(),
    'forms_cycle_left': forms_cycle(turn=True),
    'forms_cycle_air': forms_cycle(air=True, every=3.4),
    'forms_soon': [(0.0, 'bag 80 0'), (0.1, 'who')] + after(0.4, DOWN) + [(1.5, 'who')] + after(1.6, DOWN) + [(2.6, 'who'), (3.0, 'end')],
    # plain versions
    'beam': [(0.0, 'bag 30 0')] + after(0.3, B) + [(2.5, 'end')],
    'slash_whiff': [(0.0, 'bag 80 0')] + after(0.3, SIDE) + after(0.3, MASH) + [(3.0, 'end')],
    'slash_hit': [(0.0, 'bag 9 0'), (0.0, 'pin')] + after(0.3, SIDE) + after(0.3, MASH) + [(3.5, 'end')],
    'rise': [(0.0, 'bag 80 0')] + after(0.3, UP) + [(3.0, 'end')],
    # Limit versions: the gauge filled by damage first
    'limit_beam': [(0.0, 'fill'), (0.0, 'bag 30 0')] + after(0.6, B) + [(3.5, 'end')],
    'limit_beam_air': [(0.0, 'fill'), (0.0, 'bag 30 0'), (0.6, 'stick 0.5 1.0'), (0.68, 'neutral')] + after(0.95, B) + [(4.0, 'end')],
    'limit_slash': [(0.0, 'fill'), (0.0, 'bag 9 0')] + after(0.6, SIDE) + [(4.0, 'end')],
    'limit_slash_pin': [(0.0, 'fill'), (0.0, 'bag 9 0'), (0.0, 'pin')] + after(0.6, SIDE) + [(4.0, 'end')],
    'limit_slash_whiff': [(0.0, 'fill'), (0.0, 'bag 80 0')] + after(0.6, SIDE) + [(3.0, 'end')],
    'limit_rise': [(0.0, 'fill'), (0.0, 'bag 7 0')] + after(0.6, UP) + [(4.0, 'end')],
    'limit_rise_dive': [(0.0, 'fill'), (0.0, 'bag 80 0')] + after(0.6, UP) + [(0.85, 'B+'), (0.92, 'B-'), (4.0, 'end')],
    'limit_down': [(0.0, 'fill'), (0.0, 'bag 8 0')] + after(0.6, DOWN) + [(3.5, 'end')],
    'gauge_once': [(0.0, 'fill'), (0.0, 'bag 80 0')] + after(0.6, UP) + after(2.6, UP) + [(5.0, 'end')],
    # Byleth
    'whip': [(0.0, 'bag 4 22'), (0.0, 'pin')] + after(0.3, UP) + [(1.2, 'unpin'), (3.5, 'end')],
    'whip_far': [(0.0, 'bag 14 30'), (0.0, 'pin')] + after(0.3, UP) + [(1.2, 'unpin'), (3.5, 'end')],
    'bow_cancel': [(0.0, 'bag 80 0'), (0.3, 'B+'), (0.9, 'R+'), (0.98, 'R-'), (1.0, 'B-'), (3.0, 'end')],
    'axe_cancel': [(0.0, 'bag 80 0')] + after(0.3, DOWN) + [(0.7, 'R+'), (0.78, 'R-'), (3.5, 'end')],
    'axe': [(0.0, 'bag 12 0')] + after(0.3, DOWN) + [(3.5, 'end')],
    # with PROBE_MIRROR and the bag the same fighter: both swing, and the one in front is hit in the back mid-swing
    'axe_mirror': [(0.0, 'bag 14 0')] + after(0.3, DOWN) + [(3.5, 'end')],
    # with PROBE_MIRROR, the fighter Marth (0x12) and the bag the port: both get down+B (Marth counters, the port
    # swings its axe), then Marth jabs the port in the back while its swing is armoured
    'armour': [(0.0, 'bag 9 0')] + after(0.3, DOWN) + [(1.26 + 0.05 * i, 'A+' if i % 2 == 0 else 'A-') for i in range(8)] + [(3.2, 'end')],
    # the same with Link (0x06): his down+B pulls a bomb, and A throws it at the port's back
    'armour_link': [(0.0, 'bag 12 0')] + after(0.3, DOWN) + [(1.04, 'A+'), (1.10, 'A-'), (3.2, 'end')],
    'armour_link_late': [(0.0, 'bag 12 0')] + after(0.3, DOWN) + [(1.60, 'A+'), (1.66, 'A-'), (3.4, 'end')],
    'reverse_up': [(0.0, 'bag 80 0'), (0.3, 'stick 0.5 1.0'), (0.32, 'B+'), (0.34, 'stick 0.0 0.5'), (0.42, 'neutral'), (0.42, 'B-'), (3.2, 'end')],
    'reverse_down': [(0.0, 'bag 80 0'), (0.3, 'stick 0.5 0.0'), (0.32, 'B+'), (0.34, 'stick 0.0 0.5'), (0.42, 'neutral'), (0.42, 'B-'), (3.4, 'end')],
    'reverse_n_air': [(0.0, 'bag 80 0'), (0.3, 'stick 0.5 1.0'), (0.38, 'neutral'), (0.65, 'B+'), (0.67, 'stick 0.0 0.5'), (0.75, 'neutral'), (0.75, 'B-'), (3.4, 'end')],
    # ---- pictures
    'look_beam_left': [(0.0, 'bag 80 0'), (0.2, 'turn'), (0.6, 'B+'), (0.68, 'B-'), (1.02, 'shot a'), (1.25, 'shot b'), (2.6, 'end')],
    'look_beam_right': [(0.0, 'bag 80 0'), (0.6, 'B+'), (0.68, 'B-'), (1.02, 'shot a'), (1.25, 'shot b'), (2.6, 'end')],
    'look_charge': [(0.0, 'bag 26 0'), (0.3, 'stick 0.5 0.0'), (0.32, 'B+'), (0.4, 'stick 0.5 0.5'), (1.2, 'shot a'), (2.4, 'shot b'), (7.4, 'shot full1'), (7.8, 'B-'),
                    (8.3, 'shot full2'), (8.6, 'shot full3'), (8.9, 'shot full4'), (9.4, 'end')],
    'look_full': [(0.0, 'bag 26 0'), (0.3, 'fill'), (0.36, 'shot a'), (0.44, 'shot b'), (0.52, 'shot c'), (0.62, 'shot d'), (0.9, 'shot e'), (1.3, 'shot f'), (1.6, 'end')],
    'look_limit_beam': [(0.0, 'fill'), (0.0, 'bag 30 0')] + after(0.6, B) + [(0.95, 'shot a'), (1.1, 'shot b'), (1.25, 'shot c'), (3.2, 'end')],
    'look_limit_slash': [(0.0, 'fill'), (0.0, 'bag 9 0'), (0.0, 'pin')] + after(0.6, SIDE) + [(0.82, 'shot a'), (1.0, 'shot b'), (1.2, 'shot c'), (1.42, 'shot d'), (3.6, 'end')],
    'look_finish': [(0.0, 'fill'), (0.0, 'bag 8 0')] + after(0.6, DOWN) + [(0.75, 'shot a'), (0.9, 'shot b'), (1.1, 'shot c'), (3.2, 'end')],
    'look_arrow_left': [(0.0, 'bag 80 0'), (0.2, 'turn'), (0.6, 'B+'), (0.68, 'B-'), (1.42, 'shot a'), (1.5, 'shot b'), (1.58, 'shot c'), (3.0, 'end')],
    'look_arrow_right': [(0.0, 'bag 80 0'), (0.6, 'B+'), (0.68, 'B-'), (1.42, 'shot a'), (1.5, 'shot b'), (1.58, 'shot c'), (3.0, 'end')],
    'look_tint': [(0.0, 'bag 22 0'), (0.3, 'shot none'),
                  (0.5, 'tint 255 0 0 128 hex'), (0.9, 'shot red_hex'), (1.0, 'tint 0 255 0 128 hex'), (1.4, 'shot green_hex'),
                  (1.5, 'tint 0 0 255 128 hex'), (1.9, 'shot blue_hex'),
                  (2.0, 'tint 255 0 0 128 all'), (2.4, 'shot red_all'), (2.5, 'tint 0 255 0 128 all'), (2.9, 'shot green_all'),
                  (3.0, 'tint 0 0 255 128 all'), (3.4, 'shot blue_all'), (3.5, 'tint 40 120 255 60 all'), (3.9, 'shot glow_all'),
                  (4.0, 'untint'), (4.4, 'shot after'), (4.6, 'end')],
    'look_gleam': [(0.0, 'bag 18 0'), (0.3, 'percent 150'), (0.32, 'shot a'), (0.33, 'shot b'), (0.34, 'shot c'), (0.35, 'shot d'), (0.8, 'percent 0'), (1.0, 'end')],
    'look_gleam2': [(0.0, 'bag 18 0'), (0.3, 'freeze'), (0.3, 'percent 150'), (0.3, 'step 2'), (0.3, 'shot a'), (0.3, 'step 2'), (0.3, 'shot b'),
                    (0.3, 'step 3'), (0.3, 'shot c'), (0.3, 'step 4'), (0.3, 'shot d'), (0.3, 'percent 0'), (0.3, 'unfreeze'), (0.6, 'end')],
    'look_hud': [(0.0, 'bag 26 0'), (0.2, 'hud'), (0.3, 'percent 60'), (0.6, 'shot default'),
                 (0.7, 'gauge -3 3 6 0.5 -0.5'), (1.0, 'shot zneg'), (1.1, 'gauge -3 0 6 0.5 0.5'), (1.4, 'shot y0'),
                 (1.5, 'gauge -3 -3 6 0.5 0.5'), (1.8, 'shot yneg'), (1.9, 'gauge 0 3 3 1.0 0.5'), (2.2, 'shot x0'), (2.4, 'end')],
    'look_hud2': [(0.0, 'bag 26 0'), (0.3, 'shot empty'), (0.4, 'percent 35'), (0.8, 'shot third'), (0.9, 'percent 70'), (1.3, 'shot most'),
                  (1.4, 'percent 135'), (1.8, 'shot full1'), (2.0, 'shot full2'), (2.2, 'end')],
    'land_n': landing('neutral'), 'land_f': landing('stick 1.0 0.5'), 'land_b': landing('stick 0.0 0.5'),
    'land_hi': landing('stick 0.5 1.0'), 'land_lw': landing('stick 0.5 0.0'),
    'lcancel_n': landing('neutral', True), 'lcancel_f': landing('stick 1.0 0.5', True), 'lcancel_b': landing('stick 0.0 0.5', True),
    'lcancel_hi': landing('stick 0.5 1.0', True), 'lcancel_lw': landing('stick 0.5 0.0', True),
    'throw_f': throw('stick 1.0 0.5'), 'throw_b': throw('stick 0.0 0.5'), 'throw_hi': throw('stick 0.5 1.0'), 'throw_lw': throw('stick 0.5 0.0'),
    'pummel': [(0.0, 'bag 9 0'), (0.4, 'Z+'), (0.48, 'Z-'), (1.1, 'A+'), (1.16, 'A-'), (1.6, 'A+'), (1.66, 'A-'), (4.0, 'end')],
    # how high the jumps go ("rose"): a full hop, a short hop, and a full hop with the second jump at its top
    'hop_full': [(0.0, 'bag 60 0'), (0.3, 'X+'), (0.7, 'X-'), (2.2, 'end')],
    'hop_short': [(0.0, 'bag 60 0'), (0.3, 'X+'), (0.33, 'X-'), (2.2, 'end')],
    # reach: a down smash with the target close behind, and forward smashes with it further and further off
    'dsmash_behind': [(0.0, 'bag -6 0'), (0.3, 'stick 0.5 0.0'), (0.3, 'A+'), (0.38, 'A-'), (0.4, 'neutral'), (3.0, 'end')],
    **{f'fsmash_{n}': [(0.0, f'bag {n} 0'), (0.3, 'stick 1.0 0.5'), (0.3, 'A+'), (0.38, 'A-'), (0.4, 'neutral'), (3.2, 'end')]
       for n in (16, 20, 24, 28, 32)},
    **{f'ftilt_{n}': [(0.0, f'bag {n} 0'), (0.3, 'stick 0.65 0.5'), (0.36, 'A+'), (0.44, 'A-'), (0.46, 'neutral'), (2.6, 'end')]
       for n in (12, 16, 20, 24)},
    **{f'look_throw_{n}': [(0.0, 'bag 9 0'), (0.4, 'Z+'), (0.48, 'Z-'), (1.1, stick), (1.2, 'neutral'), (1.28, 'shot a'), (1.42, 'shot b'),
                           (1.56, 'shot c'), (1.7, 'shot d'), (4.0, 'end')]
       for n, stick in (('f', 'stick 1.0 0.5'), ('lw', 'stick 0.5 0.0'))},
    # aerials thrown later in a short hop, so their hits come on the way down onto a standing target
    'fair_late': [(0.0, 'bag 13 0'), (0.3, 'X+'), (0.33, 'X-'), (0.44, 'stick 1.0 0.5'), (0.5, 'A+'), (0.58, 'A-'), (0.6, 'neutral'), (3.2, 'end')],
    'nair_late': [(0.0, 'bag 10 0'), (0.3, 'X+'), (0.33, 'X-'), (0.6, 'A+'), (0.68, 'A-'), (3.2, 'end')],
    # a neutral air beside a target held in the air at the height the swing passes in front
    'nair_air': [(0.0, 'bag 9 14'), (0.0, 'pin'), (0.3, 'X+'), (0.33, 'X-'), (0.38, 'A+'), (0.46, 'A-'), (3.2, 'end')],
    # a dash attack after a short dash, the target far enough off that the fighter does not run through it first
    'dash_40': [(0.0, 'bag 40 0'), (0.3, 'stick 1.0 0.5'), (0.4, 'A+'), (0.48, 'A-'), (0.5, 'neutral'), (3.2, 'end')],
    'fsmash_36': [(0.0, 'bag 36 0'), (0.3, 'stick 1.0 0.5'), (0.3, 'A+'), (0.38, 'A-'), (0.4, 'neutral'), (3.2, 'end')],
    'nair_air2': [(0.0, 'bag 9 18'), (0.0, 'pin'), (0.3, 'X+'), (0.33, 'X-'), (0.38, 'A+'), (0.46, 'A-'), (3.2, 'end')],
    # the up special facing each way, photographed through the throw
    'look_whip_right': [(0.0, 'bag 70 0')] + after(0.5, UP) + [(0.5 + t, f'shot r{i}') for i, t in enumerate((0.12, 0.2, 0.28, 0.36, 0.5))] + [(3.0, 'end')],
    'look_whip_left': [(0.0, 'bag 70 0'), (0.1, 'turn')] + after(0.9, UP) + [(0.9 + t, f'shot l{i}') for i, t in enumerate((0.12, 0.2, 0.28, 0.36, 0.5))] + [(3.4, 'end')],
    # the down special with a target close behind: left alone it misses; the stick held back while the axe is up turns it
    'axe_noturn': [(0.0, 'bag -14 0')] + after(0.3, DOWN) + [(3.0, 'end')],
    'axe_turn': [(0.0, 'bag -14 0')] + after(0.3, DOWN) + [(0.7, 'stick 0.0 0.5'), (0.82, 'neutral'), (3.0, 'end')],
    'axe_turn_twice': [(0.0, 'bag -14 0')] + after(0.3, DOWN) + [(0.6, 'stick 0.0 0.5'), (0.7, 'neutral'), (0.8, 'stick 1.0 0.5'), (0.9, 'neutral'), (3.0, 'end')],
    # the Limit gauge: filled by damage dealt (a jab lands, then the target's damage is pushed up: the gauge counts
    # what a fighter it last hit goes up by), so the down special is Finishing Touch and not the charge
    'gauge_dealt': [(0.0, 'bag 7 0'), (0.0, 'pin'), (0.3, 'A+'), (0.38, 'A-'), (1.0, 'bagpercent 170'), (1.3, 'bagpercent 0'), (1.5, 'unpin')]
                   + after(1.6, DOWN) + [(4.5, 'end')],
    'gauge_not_dealt': [(0.0, 'bag 60 0'), (1.0, 'bagpercent 170'), (1.3, 'bagpercent 0')] + after(1.6, DOWN) + [(3.0, 'B+'), (3.05, 'B-'), (4.0, 'end')],
    # a full gauge left alone runs out after fifteen seconds: the down special is the charge again
    'gauge_expires': [(0.0, 'fill'), (0.0, 'bag 60 0')] + after(16.5, DOWN) + [(17.5, 'B+'), (17.55, 'B-'), (18.5, 'end')],
    'gauge_holds': [(0.0, 'fill'), (0.0, 'bag 8 0')] + after(13.0, DOWN) + [(16.0, 'end')],
    # how far a second of running goes, without the gauge and with it full
    'run_plain': [(0.0, 'bag -60 0'), (0.3, 'stick 1.0 0.5'), (1.3, 'neutral'), (2.5, 'end')],
    'run_limit': [(0.0, 'fill'), (0.0, 'bag -60 0'), (0.6, 'stick 1.0 0.5'), (1.6, 'neutral'), (2.8, 'end')],
    # the gauge over his head while he charges it
    'look_charge2': [(0.0, 'bag 60 0'), (0.3, 'stick 0.5 0.0'), (0.32, 'B+'), (0.4, 'neutral'), (1.2, 'shot over'), (1.6, 'B-'), (2.6, 'end')],
    # a down air and a dash attack, photographed while the sword is out
    'look_dair': [(0.0, 'bag 60 0'), (0.3, 'X+'), (0.7, 'X-'), (0.75, 'stick 0.5 0.0'), (0.77, 'A+'), (0.85, 'A-'), (0.87, 'neutral'),
                  (1.0, 'shot a'), (1.12, 'shot b'), (1.24, 'shot c'), (3.0, 'end')],
    'look_dash': [(0.0, 'bag 80 0'), (0.3, 'stick 1.0 0.5'), (0.45, 'A+'), (0.53, 'A-'), (0.55, 'neutral'), (0.62, 'shot a'), (0.7, 'shot b'),
                  (0.78, 'shot c'), (3.0, 'end')],
    # half a second of running from a standstill, without the gauge and with it full (then the gauge is spent)
    'run_plain2': [(0.0, 'bag -60 0'), (0.3, 'stick 1.0 0.5'), (0.8, 'neutral'), (2.4, 'end')],
    'run_limit2': [(0.0, 'fill'), (0.0, 'bag -60 0'), (0.6, 'stick 1.0 0.5'), (1.1, 'neutral')] + after(2.4, DOWN) + [(5.0, 'end')],
    # the fighter's numbers before the gauge fills, with it full, and after it is spent
    'boost_read': [(0.0, 'bag 60 0'), (0.3, 'attrs'), (0.5, 'fill'), (1.2, 'attrs')] + after(1.5, DOWN) + [(3.6, 'attrs'), (4.0, 'end')],
    # the charge held for a second and a half, photographed twice
    'look_charge3': [(0.0, 'bag 60 0'), (0.3, 'stick 0.5 0.0'), (0.32, 'B+'), (0.45, 'stick 0.5 0.5'), (1.0, 'shot over1'), (1.5, 'shot over2'),
                     (1.9, 'B-'), (3.2, 'end')],
    # the neutral special held to its full charge (it lets go by itself), photographed through the shot and after
    'look_beam_full': [(0.0, 'bag 70 0'), (0.3, 'B+')] + [(2.1 + 0.07 * i, f'shot f{i:02d}') for i in range(16)] + [(3.4, 'B-'), (4.6, 'end')],
    'look_beam_full_left': [(0.0, 'bag -70 0'), (0.1, 'turn'), (0.9, 'B+')] + [(2.7 + 0.07 * i, f'shot g{i:02d}') for i in range(16)]
                           + [(4.0, 'B-'), (5.2, 'end')],
    # the full shot stepped two frames at a time from just before it lets go, a picture at each step
    'look_beam_step': [(0.0, 'bag 70 0'), (0.3, 'B+'), (2.0, 'freeze')]
                      + [x for i in range(24) for x in ((2.05 + 0.1 * i, 'step 2'), (2.1 + 0.1 * i, f'shot s{i:02d}'))]
                      + [(4.6, 'unfreeze'), (4.8, 'B-'), (5.8, 'end')],
    # the full shot with the target close, and at mid range: it must hit at any distance
    'beam_near': [(0.0, 'bag 7 0'), (0.3, 'B+'), (3.2, 'B-'), (4.2, 'end')],
    'beam_mid': [(0.0, 'bag 34 0'), (0.3, 'B+'), (3.2, 'B-'), (4.2, 'end')],
    'beam_far': [(0.0, 'bag 110 0'), (0.3, 'B+'), (3.2, 'B-'), (4.2, 'end')],
    'look_beam_step_left': [(0.0, 'bag 70 0'), (0.1, 'turn'), (0.9, 'B+'), (2.6, 'freeze')]
                           + [x for i in range(20) for x in ((2.65 + 0.1 * i, 'step 2'), (2.7 + 0.1 * i, f'shot t{i:02d}'))]
                           + [(4.8, 'unfreeze'), (5.0, 'B-'), (6.0, 'end')],
    # the arrow let go at once (no charge): no beam
    'arrow_quick': [(0.0, 'bag 40 0'), (0.3, 'B+'), (0.9, 'B-'), (1.3, 'shot q0'), (2.6, 'end')],
    'dash_24': [(0.0, 'bag 24 0'), (0.3, 'stick 1.0 0.5'), (0.55, 'A+'), (0.63, 'A-'), (0.65, 'neutral'), (3.2, 'end')],
    # where a grabbed fighter is held, through a pummel and an up throw
    'look_hold': [(0.0, 'bag 9 0'), (0.4, 'Z+'), (0.48, 'Z-'), (1.0, 'shot hold1'), (1.3, 'shot hold2'), (1.5, 'A+'), (1.56, 'A-'),
                  (1.62, 'shot pummel'), (1.95, 'stick 0.5 1.0'), (2.05, 'neutral'), (2.12, 'shot up1'), (2.27, 'shot up2'),
                  (2.42, 'shot up3'), (4.0, 'end')],
    'look_land_lw': [(0.0, 'bag 26 0')] + landing('stick 0.5 0.0')[1:-1] + [(1.2, 'shot air1'), (1.36, 'shot air2')]
                    + [(1.44 + 0.13 * i, f'shot land{i}') for i in range(8)] + [(3.4, 'end')],
    'look_land_n': [(0.0, 'bag 26 0')] + landing('neutral')[1:-1] + [(1.2, 'shot air1'), (1.36, 'shot air2')]
                   + [(1.44 + 0.13 * i, f'shot land{i}') for i in range(5)] + [(3.4, 'end')],
    # a short hop and a forward air at once, onto a standing target: the hit for standing targets must be the one that lands
    'fair_ground': [(0.0, 'bag 13 0'), (0.3, 'X+'), (0.33, 'X-'), (0.36, 'stick 1.0 0.5'), (0.38, 'A+'), (0.46, 'A-'), (0.48, 'neutral'), (3.2, 'end')],
    'look_throw_b': [(0.0, 'bag 9 0'), (0.4, 'Z+'), (0.48, 'Z-'), (1.1, 'stick 0.0 0.5'), (1.2, 'neutral'), (1.28, 'shot a'), (1.42, 'shot b'),
                     (1.56, 'shot c'), (1.7, 'shot d'), (1.95, 'shot e'), (2.6, 'shot f'), (4.0, 'end')],
    'nair_ground': [(0.0, 'bag 10 0'), (0.3, 'X+'), (0.33, 'X-'), (0.38, 'A+'), (0.46, 'A-'), (3.2, 'end')],
    'usmash_bag': [(0.0, 'bag 8 0'), (0.3, 'stick 0.5 1.0'), (0.3, 'A+'), (0.38, 'A-'), (0.4, 'neutral'), (3.4, 'end')],
    'dash_bag': [(0.0, 'bag 34 0'), (0.3, 'stick 1.0 0.5'), (0.55, 'A+'), (0.63, 'A-'), (0.65, 'neutral'), (3.2, 'end')],
    # standing still, stepped a frame at a time with the camera on the face (PROBE_STEPSHOT=first-last clip frames)
    'look_blink': [(0.0, 'bag 60 0'), (0.3, 'closeup 16 16.8 24 75'), (0.3, 'freeze'), (0.3, 'steplog 150'), (0.3, 'unfreeze'), (0.6, 'end')],
    # the fighter standing, frozen, seen from eight sides and then close on the head from four
    'look_round': [(0.0, 'bag 60 0'), (0.3, 'freeze')] + [x for k, yaw in enumerate(range(0, 360, 45))
                                                         for x in ((0.3, f'closeup 34 10 35 {yaw}'), (0.3, f'shot y{yaw:03d}'))]
                  + [x for yaw in (60, 90, 120, 270) for h_ in (12, 14) for x in ((0.3, f'closeup 14 {h_} 22 {yaw}'), (0.3, f'shot h{h_}y{yaw:03d}'))]
                  + [(0.3, 'unfreeze'), (0.6, 'end')],
    # a first look at a new fighter: standing, walking, running, a jump and its landing
    'look_first': [(0.0, 'bag -70 0'), (0.3, 'closeup 46 8 35 0'), (0.5, 'shot stand'), (1.0, 'stick 0.72 0.5'), (1.35, 'shot walk1'),
                   (1.55, 'shot walk2'), (1.7, 'neutral'), (2.2, 'stick 0.0 0.5'), (2.45, 'shot dash'), (2.6, 'shot run'), (2.7, 'neutral'),
                   (3.4, 'X+'), (3.55, 'shot jump1'), (3.7, 'X-'), (3.8, 'shot jump2'), (4.1, 'shot fall'), (4.9, 'shot landed'),
                   (5.1, 'stick 0.5 0.0'), (5.5, 'shot crouch'), (5.7, 'neutral'), (6.1, 'end')],
    # the swung parts (ears, hair, capes): close on the head while the fighter walks, turns, jumps and lands
    'look_swing': [(0.0, 'bag -70 0'), (0.3, 'closeup 40 7 35 0'), (0.6, 'shot rest'), (0.8, 'stick 0.72 0.5'),
                   (1.1, 'shot go'), (1.3, 'neutral'), (1.42, 'shot stop'), (2.0, 'X+'), (2.2, 'X-'), (2.3, 'shot up'),
                   (2.62, 'shot top'), (2.95, 'shot down'), (3.3, 'shot land'), (4.0, 'shot after'), (4.2, 'end')],
    # pictures to make a portrait and a stock icon from: standing, stepped to a chosen frame, the camera on the whole
    # fighter and then on its head (PROBE_PORTRAIT_CAM / PROBE_HEAD_CAM: distance, height, lens, angle round)
    'look_portrait': [(0.0, 'bag 150 0'), (0.6, 'freeze'), (0.6, f"step {os.environ.get('PROBE_PORTRAIT_STEP', '12')}"),
                      (0.6, f"closeup {os.environ.get('PROBE_PORTRAIT_CAM', '50 8.5 35 62')}"), (0.6, 'shot body'),
                      (0.6, f"closeup {os.environ.get('PROBE_HEAD_CAM', '20 13.5 30 62')}"), (0.6, 'shot head'),
                      (0.6, 'unfreeze'), (0.9, 'end')],
    # each attack stepped a frame at a time for close pictures (PROBE_CLOSEUP parks the camera, PROBE_STEPSHOT picks
    # the clip frames photographed)
    **{f'close_{n}': [(0.0, 'bag 90 0'), (0.5, 'freeze'), (0.5, stick), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                      (0.5, 'steplog 58'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('jab', 'stick 0.5 0.5'), ('ftilt', 'stick 0.65 0.5'), ('utilt', 'stick 0.5 0.68'), ('fsmash', 'stick 1.0 0.5'),
                        ('usmash', 'stick 0.5 1.0'), ('dsmash', 'stick 0.5 0.0'))},
    'close_dtilt': [(0.0, 'bag 90 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'steplog 10'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                    (0.5, 'neutral'), (0.5, 'steplog 48'), (0.5, 'unfreeze'), (1.0, 'end')],
    'close_dash': [(0.0, 'bag 150 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 12'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                   (0.5, 'neutral'), (0.5, 'steplog 56'), (0.5, 'unfreeze'), (1.0, 'end')],
    **{f'close_{n}': [(0.0, 'bag 90 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 20'), (0.5, 'X-'), (0.5, stick), (0.5, 'A+'), (0.5, 'steplog 2'),
                      (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 50'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('nair', 'stick 0.5 0.5'), ('fair', 'stick 1.0 0.5'), ('bair', 'stick 0.0 0.5'), ('uair', 'stick 0.5 1.0'),
                        ('dair', 'stick 0.5 0.0'))},
    # where a frame's time goes while the fighter stands, walks, crouches and jumps (the game's own clock)
    'look_perf': [(0.0, 'bag -70 0'), (0.5, 'perf stand'), (1.6, 'stick 0.72 0.5'), (1.9, 'perf walk'), (2.9, 'neutral'),
                  (3.2, 'stick 0.5 0.0'), (3.7, 'perf crouch'), (4.7, 'neutral'), (5.0, 'X+'), (5.12, 'perf jump'), (6.0, 'X-'),
                  (7.0, 'perf stand again'), (8.0, 'end')],
    # the swung parts in motion, stepped: a picture every few frames through a dash, the stop, a full jump and the landing
    'look_ears': [(0.0, 'bag -70 0'), (0.3, f"closeup {os.environ.get('PROBE_EARS_CAM', '26 8 35 30')}"), (0.6, 'freeze'), (0.6, 'shot a00')]
                 + [(0.6, 'stick 1.0 0.5')] + [x for i in range(8) for x in ((0.6, 'step 3'), (0.6, f'shot b{i:02d}'))]
                 + [(0.6, 'neutral')] + [x for i in range(8) for x in ((0.6, 'step 3'), (0.6, f'shot c{i:02d}'))]
                 + [(0.6, 'X+'), (0.6, 'step 4'), (0.6, 'shot d00'), (0.6, 'step 4'), (0.6, 'X-')]
                 + [x for i in range(1, 15) for x in ((0.6, f'shot d{i:02d}'), (0.6, 'step 4'))]
                 + [x for i in range(6) for x in ((0.6, f'shot e{i:02d}'), (0.6, 'step 5'))]
                 + [(0.6, 'unfreeze'), (0.9, 'end')],
    # the neutral special held to its full charge, stepped through its release (PROBE_STEPSHOT picks the frames)
    'look_erupt_full': [(0.0, 'bag 45 0'), (0.5, 'B+'), (4.45, 'freeze'), (4.45, 'steplog 70'), (4.45, 'B-'), (4.45, 'unfreeze'), (6.0, 'end')],
    # the same while it charges: a picture every few frames of the first second
    'look_erupt_charge': [(0.0, 'bag 45 0'), (0.5, 'B+'), (0.9, 'freeze'), (0.9, 'steplog 40'), (0.9, 'B-'), (0.9, 'unfreeze'), (3.0, 'end')],
    'look_turn': [(0.0, 'bag 12 0'), (0.5, 'shot right'), (0.7, 'turn'), (1.3, 'shot left'), (1.6, 'end')],
    # 'face -1' and a special pressed into the frozen game on the same moment: he must turn where he stands and the
    # neutral special must start facing left, toward a bag put after the turn
    'look_face': [(0.0, 'shot right'), (0.3, 'face -1'), (0.3, 'bag 40 0'), (0.4, 'freeze'), (0.4, 'B+'), (0.4, 'steplog 12'),
                  (0.4, 'B-'), (0.4, 'shot left'), (0.4, 'unfreeze'), (1.4, 'end')],
    'reverse_n': [(0.0, 'bag 80 0'), (0.3, 'B+'), (0.32, 'stick 0.0 0.5'), (0.40, 'neutral'), (0.42, 'B-'), (2.8, 'end')],
    'reverse_side': [(0.0, 'bag 80 0'), (0.3, 'stick 1.0 0.5'), (0.32, 'B+'), (0.34, 'stick 0.0 0.5'), (0.42, 'neutral'), (0.42, 'B-'), (2.8, 'end')],
    # ---- common actions: how long each lasts (states: 233 roll forward, 234 roll back, 235 spot dodge, 236 air dodge,
    # 178 to 180 shield up, held, down; 212 grab, 214 dash grab, 216 holding)
    'spotdodge': [(0.0, 'bag 70 0'), (0.3, 'R+'), (0.6, 'stick 0.5 0.0'), (0.66, 'neutral'), (0.7, 'R-'), (2.4, 'end')],
    'roll_f': [(0.0, 'bag 70 0'), (0.3, 'R+'), (0.6, 'stick 1.0 0.5'), (0.66, 'neutral'), (0.7, 'R-'), (2.4, 'end')],
    'roll_b': [(0.0, 'bag 70 0'), (0.3, 'R+'), (0.6, 'stick 0.0 0.5'), (0.66, 'neutral'), (0.7, 'R-'), (2.4, 'end')],
    'shield_drop': [(0.0, 'bag 70 0'), (0.3, 'R+'), (0.9, 'R-'), (2.0, 'end')],
    'airdodge': [(0.0, 'bag 70 0'), (0.3, 'X+'), (0.7, 'X-'), (0.75, 'R+'), (0.83, 'R-'), (3.0, 'end')],
    # the shield as it comes up and after it has worn down: where it sits on the body and how much of the body it covers
    'look_shield': [(0.0, 'bag 26 0'), (0.3, 'R+'), (0.7, 'shot full'), (3.0, 'shot worn'), (3.1, 'R-'), (3.8, 'end')],
    # the taunt, three times along it
    'look_taunt': [(0.0, 'bag 60 0'), (0.5, 'D_UP+'), (0.58, 'D_UP-'), (0.9, 'shot a'), (1.4, 'shot b'), (2.0, 'shot c'), (3.4, 'end')],
    **{f'grab_{n}': [(0.0, f'bag {n} 0'), (0.4, 'Z+'), (0.48, 'Z-'), (2.2, 'end')] for n in (8, 12, 14, 16, 18, 20)},
    **{f'grabair_{n}': [(0.0, f'bag {n} 4'), (0.0, 'pin'), (0.4, 'Z+'), (0.48, 'Z-'), (0.9, 'unpin'), (2.2, 'end')] for n in (12, 16, 18, 20)},
    'grab_whiff': [(0.0, 'bag 70 0'), (0.4, 'Z+'), (0.48, 'Z-'), (2.2, 'end')],
    'dashgrab_whiff': [(0.0, 'bag 110 0'), (0.3, 'stick 1.0 0.5'), (0.5, 'Z+'), (0.58, 'Z-'), (0.6, 'neutral'), (2.6, 'end')],
    # ---- Cloud's charge: it goes on with the button let go; the button again, shield or a jump ends it
    'charge_toggle': [(0.0, 'bag 70 0')] + after(0.3, DOWN) + [(2.3, 'B+'), (2.38, 'B-'), (3.6, 'end')],
    'charge_shield': [(0.0, 'bag 70 0')] + after(0.3, DOWN) + [(1.5, 'R+'), (1.9, 'R-'), (3.0, 'end')],
    'charge_jump': [(0.0, 'bag 70 0')] + after(0.3, DOWN) + [(1.5, 'X+'), (1.58, 'X-'), (3.4, 'end')],
    'charge_stick': [(0.0, 'bag 70 0')] + after(0.3, DOWN) + [(1.5, 'stick 1.0 0.5'), (1.7, 'neutral'), (3.2, 'end')],
    # left alone it ends when the gauge is full; with damage taken part-way it takes that much longer
    'charge_plain': [(0.0, 'bag 70 0')] + after(0.3, DOWN) + [(8.0, 'end')],
    'charge_drain': [(0.0, 'bag 70 0')] + after(0.3, DOWN) + [(4.5, 'percent 30'), (10.0, 'end')],
    # the neutral special in the air after a running jump: his speed before and after it starts
    'beam_air_speed': [(0.0, 'bag -70 0'), (0.3, 'stick 1.0 0.5'), (0.7, 'X+'), (0.9, 'X-'), (0.95, 'neutral'), (1.0, 'vel'), (1.02, 'B+'),
                       (1.06, 'vel'), (1.1, 'B-'), (1.12, 'vel'), (3.2, 'end')],
    # ---- Byleth's bow: put away only between two frames of drawing it; a jump leaves it; drawn, it can be turned
    'bow_early': [(0.0, 'bag 70 0'), (0.3, 'B+'), (0.45, 'R+'), (0.53, 'R-'), (1.4, 'B-'), (3.0, 'end')],
    'bow_late': [(0.0, 'bag 70 0'), (0.3, 'B+'), (1.6, 'R+'), (1.68, 'R-'), (3.6, 'B-'), (4.6, 'end')],
    'bow_jump': [(0.0, 'bag 70 0'), (0.3, 'B+'), (0.9, 'X+'), (0.98, 'X-'), (1.0, 'B-'), (3.0, 'end')],
    'bow_turn': [(0.0, 'bag -40 0'), (0.3, 'B+'), (1.3, 'stick 0.0 0.5'), (1.4, 'neutral'), (1.7, 'B-'), (3.4, 'end')],
    # the kick off a caught fighter: one that is hurt goes down; caught further out it is hit harder
    'stomp_low': [(0.0, 'bag 4 22'), (0.0, 'pin')] + after(0.3, UP) + [(0.6, 'unpin'), (3.5, 'end')],
    'stomp_high': [(0.0, 'bag 4 22'), (0.0, 'pin'), (0.1, 'bagpercent 60')] + after(0.3, UP) + [(0.6, 'unpin'), (3.5, 'end')],
    'stomp_far': [(0.0, 'bag 14 38'), (0.0, 'pin')] + after(0.3, UP) + [(0.6, 'unpin'), (3.5, 'end')],
    'side_tilt': [(0.0, 'bag 80 0'), (0.3, 'stick 0.66 0.5'), (0.5, 'B+'), (0.55, 'vel'), (0.58, 'B-'), (0.6, 'neutral'), (0.62, 'vel'), (3.0, 'end')],
    'side_held2': [(0.0, 'bag 80 0'), (0.3, 'stick 0.78 0.5'), (0.75, 'B+'), (0.80, 'vel'), (0.83, 'B-'), (0.85, 'neutral'), (0.87, 'vel'), (3.2, 'end')],
    'side_flick2': [(0.0, 'bag 80 0'), (0.3, 'stick 1.0 0.5'), (0.32, 'B+'), (0.37, 'vel'), (0.40, 'B-'), (0.42, 'neutral'), (0.44, 'vel'), (3.0, 'end')],
    # the side special with a flick of the stick, and with the stick already held
    'side_flick': [(0.0, 'bag 80 0')] + after(0.3, SIDE) + [(3.0, 'end')],
    'side_held': [(0.0, 'bag 80 0'), (0.3, 'stick 0.8 0.5'), (0.9, 'B+'), (0.98, 'B-'), (1.0, 'neutral'), (3.4, 'end')],
    # ---- Ike (Brawl). Frame-exact: the game is frozen and stepped. `me` is Ike; the bag (PROBE_BAG=0x12, Marth) is
    # given the pad when it must swing ('pads 1 0'), and Ike then holds nothing.
    # Eruption let go at once, held half way, held to its fullest (it lets go by itself)
    'erupt_tap': [(0.0, 'bag 12 0'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    'erupt_half': [(0.0, 'bag 12 0'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 110'), (0.5, 'B-'), (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    'erupt_full': [(0.0, 'bag 12 0'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 330'), (0.5, 'B-'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the counter with nothing hitting him: how long it lasts
    'counter_whiff': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                      (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Quick Draw: tapped, held to its fullest, into a fighter (tapped and full), toward an edge, in the air
    'qd_tap': [(0.0, 'bag 150 0'), (0.2, 'place -80 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
               (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')],
    'qd_full': [(0.0, 'bag 150 0'), (0.2, 'place -80 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'), (0.5, 'steplog 110'),
                (0.5, 'B-'), (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')],
    'qd_hit': [(0.0, 'bag 45 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
               (0.5, 'steplog 130'), (0.5, 'unfreeze'), (1.0, 'end')],
    'qd_full_hit': [(0.0, 'bag 90 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'), (0.5, 'steplog 110'),
                    (0.5, 'B-'), (0.5, 'steplog 130'), (0.5, 'unfreeze'), (1.0, 'end')],
    'qd_edge': [(0.0, 'bag -60 0'), (0.2, 'place 50 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                (0.5, 'steplog 120'), (0.5, 'unfreeze'), (1.0, 'end')],
    'qd_air': [(0.0, 'bag -60 0'), (0.3, 'X+'), (0.7, 'X-'), (0.75, 'freeze'), (0.75, 'stick 1.0 0.5'), (0.75, 'B+'), (0.75, 'steplog 2'), (0.75, 'B-'),
               (0.75, 'neutral'), (0.75, 'steplog 150'), (0.75, 'unfreeze'), (1.2, 'end')],
    # Aether beside a fighter; and alone
    'aether': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
               (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')],
    'aether_alone': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                     (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Aether beside a fighter left free, at several distances: which of its hits a real target takes
    **{f'aether_at_{n}': [(0.0, f'bag {n} 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'neutral'),
                          (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')] for n in (5, 8, 11, 14, 17, 20)},
    # the up special from the top of a jump, stepped: how far it rises from where it started
    'upb_air': [(0.0, 'bag -60 0'), (0.3, 'X+'), (0.7, 'X-'), (0.8, 'freeze'), (0.8, 'stick 0.5 1.0'), (0.8, 'B+'), (0.8, 'steplog 2'),
                (0.8, 'neutral'), (0.8, 'steplog 110'), (0.8, 'unfreeze'), (1.3, 'end')],
    'upb_ground': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'neutral'),
                   (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the down special, then the second fighter's jab `k` frames in (armour from a frame the game gives)
    **{f'downb_jab_{k}': [(0.0, 'bag 11 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'neutral'),
                          (1.0, f'steplog {k}'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 60'),
                          (1.0, 'pads 0 1'), (1.0, 'unfreeze'), (1.6, 'end')] for k in range(20, 40)},
    # ---- common actions counted a frame at a time (states: 233 roll forward, 234 roll back, 235 spot dodge, 236 air dodge,
    # 178 to 180 shield up, held, down)
    'step_spotdodge': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'R+'), (0.5, 'steplog 10'), (0.5, 'stick 0.5 0.0'), (0.5, 'steplog 3'),
                       (0.5, 'neutral'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    'step_rollf': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'R+'), (0.5, 'steplog 10'), (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 3'),
                   (0.5, 'neutral'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'step_rollb': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'R+'), (0.5, 'steplog 10'), (0.5, 'stick 0.0 0.5'), (0.5, 'steplog 3'),
                   (0.5, 'neutral'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'step_shield': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'R+'), (0.5, 'steplog 20'), (0.5, 'neutral'), (0.5, 'steplog 40'),
                    (0.5, 'unfreeze'), (1.0, 'end')],
    'step_airdodge': [(0.0, 'bag 70 0'), (0.3, 'X+'), (0.7, 'X-'), (0.75, 'freeze'), (0.75, 'R+'), (0.75, 'steplog 3'), (0.75, 'neutral'),
                      (0.75, 'steplog 90'), (0.75, 'unfreeze'), (1.3, 'end')],
    'step_jab': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'neutral'), (0.5, 'steplog 60'),
                 (0.5, 'unfreeze'), (1.0, 'end')],
    'step_grab': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'R+'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'neutral'), (0.5, 'steplog 60'),
                  (0.5, 'unfreeze'), (1.0, 'end')],
    **{f'step_{n}': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, stick), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'neutral'), (0.5, 'steplog 110'),
                     (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('fsmash', 'stick 1.0 0.5'), ('usmash', 'stick 0.5 1.0'), ('dsmash', 'stick 0.5 0.0'))},
    **{f'step_{n}': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, stick), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'neutral'), (0.5, 'steplog 110'),
                     (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('sideb', 'stick 1.0 0.5'), ('upb', 'stick 0.5 1.0'), ('downb', 'stick 0.5 0.0'), ('neutralb', 'stick 0.5 0.5'))},
    # hanging from the stage's left ledge, then each way off it (252 catching, 253 hanging)
    **{f'step_ledge_{n}': [(0.0, 'bag 60 0'), (0.2, 'place -120 60'), (0.25, 'place -100 -20'), (1.4, 'freeze'), (1.4, press), (1.4, 'steplog 2'),
                           (1.4, 'neutral'), (1.4, 'steplog 80'), (1.4, 'unfreeze'), (1.9, 'end')]
       for n, press in (('climb', 'stick 0.5 1.0'), ('attack', 'A+'), ('roll', 'R+'), ('jump', 'X+'))},
    'step_dashgrab': [(0.0, 'bag 110 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 12'), (0.5, 'R+'), (0.5, 'A+'), (0.5, 'steplog 2'),
                      (0.5, 'neutral'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'step_taunt': [(0.0, 'bag 70 0'), (0.5, 'freeze'), (0.5, 'D_UP+'), (0.5, 'steplog 2'), (0.5, 'neutral'), (0.5, 'steplog 130'),
                   (0.5, 'unfreeze'), (1.0, 'end')],
    # knocked down by the second fighter's forward smash, then each way up (183 to 190 face up, 191 to 198 face down)
    **{f'step_down_{n}': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 0.0 0.5'), (1.0, 'A+'), (1.0, 'steplog 2'),
                          (1.0, 'neutral'), (1.0, 'steplog 170'), (1.0, 'pads 0 1'), (1.0, press), (1.0, 'steplog 3'), (1.0, 'neutral'),
                          (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')]
       for n, press in (('stand', 'stick 0.5 1.0'), ('attack', 'A+'), ('rollf', 'stick 1.0 0.5'), ('rollb', 'stick 0.0 0.5'))},
    # the same knock-down, shield held as he lands: a tech where he is, forward, back (199 to 201)
    **{f'step_tech_{n}': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 0.0 0.5'), (1.0, 'A+'), (1.0, 'steplog 2'),
                          (1.0, 'neutral'), (1.0, 'steplog 30'), (1.0, 'pads 0 1'), (1.0, 'steplog 8'), (1.0, stick), (1.0, 'R+'),
                          (1.0, 'steplog 14'), (1.0, 'neutral'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')]
       for n, stick in (('place', 'stick 0.5 0.5'), ('f', 'stick 1.0 0.5'), ('b', 'stick 0.0 0.5'))},
    'step_ledge_up': [(0.0, 'bag 60 0'), (0.2, 'place -120 60'), (0.25, 'place -100 -20'), (1.4, 'freeze'), (1.4, 'stick 1.0 0.5'), (1.4, 'steplog 2'),
                      (1.4, 'neutral'), (1.4, 'steplog 80'), (1.4, 'unfreeze'), (1.9, 'end')],
    # ---- moves at the game's own speed, alone, for what they sound like (PROBE_AUDIO)
    **{f'snd_{n}': [(0.0, 'bag 90 0'), (0.5, stick), (0.52, 'A+'), (0.6, 'A-'), (0.62, 'neutral'), (2.6, 'end')]
       for n, stick in (('jab', 'stick 0.5 0.5'), ('fsmash', 'stick 1.0 0.5'), ('usmash', 'stick 0.5 1.0'), ('dsmash', 'stick 0.5 0.0'),
                        ('ftilt', 'stick 0.65 0.5'), ('utilt', 'stick 0.5 0.7'), ('dtilt', 'stick 0.5 0.3'))},
    'snd_eruption': [(0.0, 'bag 90 0'), (0.5, 'B+'), (0.58, 'B-'), (3.0, 'end')],
    'snd_eruption_full': [(0.0, 'bag 90 0'), (0.5, 'B+'), (5.2, 'B-'), (6.6, 'end')],
    'snd_quickdraw': [(0.0, 'bag -90 0'), (0.2, 'place -80 0'), (0.5, 'stick 1.0 0.5'), (0.52, 'B+'), (0.6, 'B-'), (0.62, 'neutral'), (3.0, 'end')],
    'snd_quickdraw_hit': [(0.0, 'bag 45 0'), (0.5, 'stick 1.0 0.5'), (0.52, 'B+'), (0.6, 'B-'), (0.62, 'neutral'), (3.2, 'end')],
    'snd_aether': [(0.0, 'bag -90 0'), (0.5, 'stick 0.5 1.0'), (0.52, 'B+'), (0.6, 'B-'), (0.62, 'neutral'), (3.4, 'end')],
    'snd_counter': [(0.0, 'bag 90 0'), (0.5, 'stick 0.5 0.0'), (0.52, 'B+'), (0.6, 'B-'), (0.62, 'neutral'), (2.4, 'end')],
    'snd_jump': [(0.0, 'bag 90 0'), (0.5, 'X+'), (0.9, 'X-'), (2.4, 'end')],
    'snd_grab': [(0.0, 'bag 90 0'), (0.5, 'Z+'), (0.58, 'Z-'), (2.2, 'end')],
    'snd_taunt': [(0.0, 'bag 90 0'), (0.5, 'D_UP+'), (0.58, 'D_UP-'), (3.6, 'end')],
    'snd_quiet': [(0.0, 'bag 90 0'), (2.0, 'end')],
    # Aether with the target held where it stands: every hit of it lands
    'aether_pin': [(0.0, 'bag 9 0'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'neutral'),
                   (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Aether from the air beside the stage's left side, facing it: he hangs, rises, comes down past its ledge
    **{f'aether_side_{i}': [(0.0, 'bag 60 0'), (0.2, 'place -120 60'), (0.25, f'place {x} {y}'), (0.3, 'freeze'), (0.3, 'stick 0.5 1.0'), (0.3, 'B+'),
                            (0.3, 'steplog 2'), (0.3, 'neutral'), (0.3, 'steplog 170'), (0.3, 'unfreeze'), (1.0, 'end')]
       for i, (x, y) in enumerate(((-100, -20), (-96, -35), (-104, -10)))},
    # Aether from beside the stage, below its ledge: caught only on the way down
    **{f'aether_ledge_{i}': [(0.0, 'bag 60 0'), (0.25, f'place {x} {y}'), (0.3, 'freeze'), (0.3, 'stick 0.5 1.0'), (0.3, 'B+'), (0.3, 'steplog 2'), (0.3, 'B-'),
                             (0.3, 'neutral'), (0.3, 'steplog 150'), (0.3, 'unfreeze'), (1.0, 'end')]
       for i, (x, y) in enumerate(((-96, -30), (-94, -45), (-93, -20)))},
    # ---- the second fighter (PROBE_BAG=0x09, Marth, who faces the first) swings at Ike `k` frames after Ike starts.
    # An input sent before a step is seen by the game a frame later, and a fighter given the pad sees what is held on
    # it as newly pressed: so the pad is empty for a frame before it changes hands.
    **{f'{name}_{k}': [(0.0, 'bag 11 0'), (1.0, 'freeze')] + start
                      + [(1.0, f'steplog {k}'), (1.0, 'pads 1 0')] + swing + [(1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 70'),
                         (1.0, 'pads 0 1'), (1.0, 'unfreeze'), (1.6, 'end')]
       for name, start, swing in (
           # the counter: down and B, then nothing; the second fighter jabs
           ('counter', [(1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'neutral')], [(1.0, 'A+')]),
           # the same, and the second fighter's forward smash
           ('countersm', [(1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'neutral')], [(1.0, 'stick 0.0 0.5'), (1.0, 'A+')]),
           # Eruption let go at once
           ('erupt_hit', [(1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'neutral')], [(1.0, 'A+')]),
           # Aether
           ('aether_hit', [(1.0, 'stick 0.5 1.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'neutral')], [(1.0, 'A+')]),
       ) for k in range(1, 46)},
    # the whip thrown at the stage's side from below its ledge
    **{f'wall_{i}': [(0.0, 'bag 60 0'), (0.25, f'place {x} {y}'), (0.3, 'stick 0.5 1.0'), (0.32, 'B+'), (0.4, 'B-'), (0.4, 'neutral'), (3.4, 'end')]
       for i, (x, y) in enumerate(((-96, -40), (-92, -55), (-90, -70), (-100, -30), (-88, -85)))},
    # ---- Duck Hunt's specials (states 373 on; stepped a frame at a time unless they are pictures)
    # Duck Jump with the stick held forward, then held back, all the way to the landing
    **{f'dh_upb_{n}': [(0.0, 'bag -60 0'), (0.2, 'place -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                       (0.5, stick), (0.5, 'steplog 108'), (0.5, 'neutral'), (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('fwd', 'stick 1.0 0.5'), ('back', 'stick 0.0 0.5'), ('still', 'neutral'))},
    # Duck Jump, then A (an attack in the air) or R (an air dodge) `k` frames after the up special is asked for
    **{f'dh_upb_{n}_{k}': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                           (0.5, f'steplog {k}'), (0.5, press), (0.5, 'steplog 2'), (0.5, 'neutral'), (0.5, 'steplog 140'),
                           (0.5, 'unfreeze'), (1.0, 'end')]
       for n, press in (('attack', 'A+'), ('dodge', 'R+')) for k in range(44, 54)},
    # Duck Jump photographed through the flight, facing each way
    'dh_look_upb_right': [(0.0, 'bag 70 0')] + after(0.5, UP) + [(0.5 + t, f'shot r{i}') for i, t in enumerate((0.06, 0.3, 0.7, 1.1, 1.5, 1.9))] + [(4.0, 'end')],
    'dh_look_upb_left': [(0.0, 'bag 70 0'), (0.1, 'turn')] + after(0.9, UP) + [(0.9 + t, f'shot l{i}') for i, t in enumerate((0.06, 0.3, 0.7, 1.1, 1.5, 1.9))] + [(4.4, 'end')],
    # Trick Shot. With PROBE_TRACK=1 his item is followed (x and y from where he stood, its state; the can's states:
    # 0 carried, 1 flying, 2 standing, 3 a hop, 4 and 5 after its last shot, 6 going off). Stepped a frame at a time
    # with a moment between steps, so that each frame is followed.
    'dh_can_step': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-')]
                   + [(0.55 + 0.035 * i, 'steplog 1') for i in range(110)] + [(4.6, 'unfreeze'), (5.0, 'end')],
    # the kicked can into a target at three distances: what the can's touch and its explosion do
    **{f'dh_can_bag_{n}': [(0.0, f'bag {n} 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-')]
                          + [(0.55 + 0.035 * i, 'steplog 1') for i in range(120)] + [(5.0, 'unfreeze'), (5.4, 'end')]
       for n in (14, 24, 32)},
    # the can kicked, left to stand, then shot ten times slowly; and shot as fast as the button can be pressed
    'dh_can_shots': [(0.0, 'bag -60 0'), (0.2, 'place -70 0'), (0.5, 'B+'), (0.58, 'B-')]
                    + [x for i in range(10) for x in ((2.2 + 0.8 * i, 'B+'), (2.28 + 0.8 * i, 'B-'))] + [(11.5, 'end')],
    'dh_can_fast': [(0.0, 'bag -60 0'), (0.2, 'place -70 0'), (0.5, 'B+'), (0.58, 'B-')]
                   + [x for i in range(12) for x in ((1.9 + 0.2 * i, 'B+'), (1.98 + 0.2 * i, 'B-'))] + [(6.5, 'end')],
    # an item never outlives its fighter: a can kicked, then the fighter dropped below the stage (PROBE_TRACK=1: the can is gone)
    'dh_can_die': [(0.0, 'bag -60 0'), (0.5, 'B+'), (0.58, 'B-'), (2.2, 'place 0 -400'), (5.5, 'end')],
    # the can left alone: how long it stands before it goes off by itself
    'dh_can_alone': [(0.0, 'bag -60 0'), (0.5, 'B+'), (0.58, 'B-'), (12.5, 'end')],
    # the standing can and a target put on it; a shot beside a target
    'dh_can_touch': [(0.0, 'bag -60 0'), (0.5, 'B+'), (0.58, 'B-'), (2.4, 'bag 36 0'), (4.0, 'end')],
    'dh_can_shot_hit': [(0.0, 'bag 44 0'), (0.5, 'B+'), (0.58, 'B-'), (2.4, 'B+'), (2.48, 'B-'), (4.5, 'end')],
    # pictures: the kick, the flight, the standing can, a shot and its hop, facing each way; the explosion on a target
    'dh_look_can_right': [(0.0, 'bag 80 0'), (0.5, 'B+'), (0.58, 'B-'), (0.62, 'shot held'), (0.8, 'shot kick'), (1.1, 'shot fly1'),
                          (1.4, 'shot fly2'), (2.2, 'shot stand'), (2.4, 'B+'), (2.48, 'B-'), (2.5, 'shot shot'), (2.62, 'shot hop1'),
                          (2.9, 'shot hop2'), (3.4, 'perf can out'), (4.6, 'end')],
    'dh_look_can_left': [(0.0, 'bag 80 0'), (0.1, 'turn'), (0.9, 'B+'), (0.98, 'B-'), (1.02, 'shot held'), (1.2, 'shot kick'),
                         (1.5, 'shot fly1'), (1.8, 'shot fly2'), (2.6, 'shot stand'), (2.8, 'B+'), (2.88, 'B-'), (2.9, 'shot shot'),
                         (3.02, 'shot hop1'), (3.3, 'shot hop2'), (5.0, 'end')],
    'dh_look_can_bang': [(0.0, 'bag 26 0'), (0.5, 'B+'), (0.58, 'B-')] + [(1.15 + 0.05 * i, f'shot b{i:02d}') for i in range(12)]
                        + [(3.0, 'end')],
    # Clay Shooting (PROBE_TRACK=1 follows the clay: 0 new, 1 flying, 2 broken by a shot, 3 broken by what it met).
    # Thrown and left alone (it breaks where it comes down); thrown into a target; thrown and shot as it passes a
    # target held a little off the floor (B again as the clay gets there)
    'dh_clay_alone': [(0.0, 'bag -60 0')] + after(0.5, SIDE) + [(4.0, 'end')],
    **{f'dh_clay_bag_{n}': [(0.0, f'bag {n} 0')] + after(0.5, SIDE) + [(4.0, 'end')] for n in (30, 60)},
    **{f'dh_clay_shot_{n}': [(0.0, f'bag {n} 14'), (0.0, 'pin')] + after(0.5, SIDE)
                           + [(0.53 + (13 + (n - 18) / 1.4) / 60, 'B+'), (0.61 + (13 + (n - 18) / 1.4) / 60, 'B-'), (2.4, 'unpin'), (4.5, 'end')]
       for n in (30, 45, 60)},
    # the clay thrown and shot `k` frames after the side special is asked for, a frame at a time, a target standing ahead
    **{f'dh_clay_step_{k}': [(0.0, 'bag 62 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                            (0.5, f'steplog {k}'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-')]
                           + [(0.55 + 0.035 * i, 'steplog 1') for i in range(70)] + [(3.2, 'unfreeze'), (3.6, 'end')] for k in (30, 36, 42)},
    # the same with nothing in the clay's way: the shot alone
    'dh_clay_step_far': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                         (0.5, 'steplog 30'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-')]
                        + [(0.55 + 0.035 * i, 'steplog 1') for i in range(60)] + [(2.9, 'unfreeze'), (3.3, 'end')],
    # pictures: the throw, the clay in flight, the shot and its burst, facing each way
    'dh_look_clay_right': [(0.0, 'bag -60 0')] + after(0.5, SIDE) + [(0.7, 'shot wind'), (0.86, 'shot throw'),
                          (1.0, 'shot fly1'), (1.15, 'shot fly2'), (1.2, 'B+'), (1.28, 'B-'), (1.31, 'shot shot1'), (1.36, 'shot shot2'),
                          (1.42, 'shot burst1'), (1.5, 'shot burst2'), (1.6, 'shot burst3'), (2.0, 'perf after'), (4.0, 'end')],
    'dh_look_clay_left': [(0.0, 'bag 60 0'), (0.2, 'stick 0.0 0.5'), (0.22, 'B+'), (0.3, 'B-'), (0.3, 'neutral'),
                         (0.4, 'shot wind'), (0.56, 'shot throw'), (0.7, 'shot fly1'), (0.85, 'shot fly2'), (0.9, 'B+'), (0.98, 'B-'),
                         (1.01, 'shot shot1'), (1.06, 'shot shot2'), (1.12, 'shot burst1'), (1.2, 'shot burst2'), (1.3, 'shot burst3'), (4.0, 'end')],
    # Wild Gunman (PROBE_TRACK=1 follows the gunman and then his bullet). Alone; with a target near and far in front
    'dh_gun_alone': [(0.0, 'bag -60 0')] + after(0.5, DOWN) + [(4.6, 'end')],
    **{f'dh_gun_bag_{n}': [(0.0, f'bag {n} 0')] + after(0.5, DOWN) + [(4.6, 'end')] for n in (22, 36, 48)},
    'dh_gun_step': [(0.0, 'bag 30 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral')]
                   + [(0.55 + 0.035 * i, 'steplog 1') for i in range(125)] + [(5.2, 'unfreeze'), (5.6, 'end')],
    'dh_look_gun_right': [(0.0, 'bag 80 0')] + after(0.5, DOWN) + [(0.56, 'shot start'), (0.7, 'shot appear'), (1.1, 'shot wait'),
                         (1.4, 'shot f1'), (1.5, 'shot f2'), (1.6, 'shot f3'), (1.7, 'shot f4'), (1.8, 'shot f5'), (1.9, 'shot f6'),
                         (2.0, 'shot f7'), (2.1, 'shot f8'), (2.3, 'perf gunman out'), (4.6, 'end')],
    'dh_look_gun_left': [(0.0, 'bag 80 0'), (0.1, 'turn')] + after(0.9, DOWN) + [(1.1, 'shot appear'), (1.5, 'shot wait'),
                        (1.8, 'shot f1'), (1.9, 'shot f2'), (2.0, 'shot f3'), (2.1, 'shot f4'), (2.2, 'shot f5'), (2.3, 'shot f6'),
                        (2.4, 'shot f7'), (2.5, 'shot f8'), (5.0, 'end')],
    # the gunmen, five in a row (each comes once a round), a frame at a time: a target held in front takes each one's
    # shot, and the frame of the move it lands on says which gunman it was
    'dh_gun_five': [(0.0, 'bag 24 0'), (0.0, 'pin'), (0.8, 'freeze')]
                   + [x for i in range(5) for x in ((0.8, 'stick 0.5 0.0'), (0.8, 'steplog 1'), (0.8, 'B+'), (0.8, 'steplog 2'), (0.8, 'B-'),
                                                    (0.8, 'neutral'), (0.8, 'steplog 200'))]
                   + [(0.8, 'unfreeze'), (1.3, 'end')],
    # the same five with nothing in their way (the bag behind): with PROBE_ITEMS=1 each bullet's place a frame, so how
    # fast it goes and how far (the game's: 10 frames at the gunman's own speed, 8, 9, 8, 5, 8 a frame)
    'dh_gun_travel': [(0.0, 'bag -60 0'), (0.0, 'pin'), (0.8, 'freeze')]
                     + [x for i in range(5) for x in ((0.8, 'stick 0.5 0.0'), (0.8, 'steplog 1'), (0.8, 'B+'), (0.8, 'steplog 2'), (0.8, 'B-'),
                                                      (0.8, 'neutral'), (0.8, 'steplog 200'))]
                     + [(0.8, 'unfreeze'), (1.3, 'end')],
    # each gunman's poses across his life (facing the camera, turned to aim his gun, facing it again): five in a row,
    # the bag behind out of his way, a picture every eighth frame from the press to 202 frames on, named by that frame
    'dh_look_gun_turn': [(0.0, 'bag -60 0'), (0.8, 'freeze')]
                        + [x for i in range(5) for x in ([(0.8, 'stick 0.5 0.0'), (0.8, 'step 1'), (0.8, 'B+'), (0.8, 'step 2'),
                                                          (0.8, 'B-'), (0.8, 'neutral')]
                                                         + [y for k in range(25) for y in ((0.8, 'step 8'), (0.8, f'shot g{i}f{10 + 8 * k:03d}'))])]
                        + [(0.8, 'unfreeze'), (1.3, 'end')],
    # one gunman (whichever comes) a picture a frame across every gunman's shot (frames 45 to 100 of the move): his
    # muzzle flash shows as his bullet leaves, not after it
    'dh_look_gun_flash': [(0.0, 'bag -60 0'), (0.8, 'freeze'), (0.8, 'stick 0.5 0.0'), (0.8, 'step 1'), (0.8, 'B+'), (0.8, 'step 2'),
                          (0.8, 'B-'), (0.8, 'neutral'), (0.8, 'step 42')]
                         + [y for k in range(56) for y in ((0.8, 'step 1'), (0.8, f'shot f{45 + k:03d}'))]
                         + [(0.8, 'unfreeze'), (1.3, 'end')],
    # a gunman's bullet and his own standing can: a can kicked out, then three gunmen (whichever come), a picture every
    # fifth frame across the frames they fire on (the bullets of the two with the big shot reach the can: it is
    # knocked along, never set off; the others' pass over it)
    'dh_look_gun_can': [(0.0, 'bag -60 0'), (0.5, 'B+'), (0.58, 'B-'), (2.3, 'freeze')]
                       + [x for k in range(3) for x in ([(2.3, 'stick 0.5 0.0'), (2.3, 'step 1'), (2.3, 'B+'), (2.3, 'step 2'), (2.3, 'B-'),
                                                        (2.3, 'neutral'), (2.3, 'step 48')]
                                                       + [y for i in range(12) for y in ((2.3, 'step 5'), (2.3, f'shot g{k}{i:02d}'))]
                                                       + [(2.3, 'step 95')])]
                       + [(2.3, 'unfreeze'), (2.8, 'end')],
    # the aiming reticle on a standing can as it is shot, and on a clay thrown to the left as it is shot: a picture a frame
    'dh_look_reticle': [(0.0, 'bag 80 0'), (0.5, 'B+'), (0.58, 'B-'), (2.3, 'freeze'), (2.3, 'B+'), (2.3, 'step 2'), (2.3, 'B-')]
                       + [x for i in range(10) for x in ((2.3, 'step 1'), (2.3, f'shot r{i:02d}'))] + [(2.3, 'unfreeze'), (3.2, 'end')],
    # a can left standing in the open until its time runs out (600 frames from the kick): a picture every third frame
    # across the moment it goes off (the can itself is gone as the explosion begins)
    'dh_look_can_end': [(0.0, 'bag 80 0'), (0.5, 'B+'), (0.58, 'B-'), (2.3, 'freeze'), (2.3, 'step 484')]
                       + [x for i in range(24) for x in ((2.3, 'step 3'), (2.3, f'shot e{i:02d}'))] + [(2.3, 'unfreeze'), (3.2, 'end')],
    'dh_look_clay_left2': [(0.0, 'bag 80 0'), (0.1, 'turn'), (0.9, 'freeze'), (0.9, 'stick 0.0 0.5'), (0.9, 'B+'), (0.9, 'step 2'), (0.9, 'B-'),
                           (0.9, 'neutral'), (0.9, 'step 28'), (0.9, 'B+'), (0.9, 'step 2'), (0.9, 'B-')]
                          + [x for i in range(14) for x in ((0.9, 'step 1'), (0.9, f'shot c{i:02d}'))] + [(0.9, 'unfreeze'), (1.6, 'end')],
    # Duck Jump from the top of a jump, an attack in the air on the first frame it can come: he is helpless once it is over
    'dh_upb_air_attack': [(0.0, 'bag -60 0'), (0.3, 'X+'), (0.7, 'X-'), (0.8, 'freeze'), (0.8, 'stick 0.5 1.0'), (0.8, 'B+'), (0.8, 'steplog 2'),
                          (0.8, 'B-'), (0.8, 'neutral'), (0.8, 'steplog 48'), (0.8, 'A+'), (0.8, 'steplog 2'), (0.8, 'A-'), (0.8, 'steplog 170'),
                          (0.8, 'unfreeze'), (1.3, 'end')],
    # his specials at the game's own speed, for what they sound like (PROBE_AUDIO): Duck Jump; Wild Gunman; a clay thrown,
    # shot and burst; a can into a target (its explosion); a can kicked, left to stand and shot once
    'dh_snd_hi': [(0.0, 'bag -60 0')] + after(0.5, UP) + [(4.4, 'end')],
    'dh_snd_lw': [(0.0, 'bag 80 0')] + after(0.5, DOWN) + [(4.6, 'end')],
    'dh_snd_s': [(0.0, 'bag -60 0')] + after(0.5, SIDE) + [(1.25, 'B+'), (1.33, 'B-'), (3.4, 'end')],
    'dh_snd_bang': [(0.0, 'bag 26 0'), (0.5, 'B+'), (0.58, 'B-'), (3.4, 'end')],
    'dh_snd_n': [(0.0, 'bag 80 0'), (0.5, 'B+'), (0.58, 'B-'), (2.4, 'B+'), (2.48, 'B-'), (4.4, 'end')],
    # ---- a face of part swaps (own_faces). PROBE_FACESHOT=1 takes a picture at every stepped frame on which the
    # fighter's model choices change (the eleven groups' choices are in the picture's name and in the log).
    # standing still for four seconds: the resting clip's blink comes by its own clock
    'face_blink': [(0.0, 'bag 60 0'), (0.3, 'freeze'), (0.3, 'shot rest'), (0.3, 'steplog 250'), (0.3, 'unfreeze'), (0.6, 'end')],
    # the second fighter is given the pad and smashes towards the first (the hurt faces), then a second time
    'face_hit': [(0.0, 'bag 12 0'), (0.5, 'freeze'), (0.5, 'pads 1 0'), (0.5, 'stick 0.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'),
                 (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 110'), (0.5, 'pads 0 1'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the forward smash, the jab and a full jump, a frame at a time
    'face_fsmash': [(0.0, 'bag 90 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                    (0.5, 'neutral'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'face_jump': [(0.0, 'bag 90 0'), (0.5, 'freeze'), (0.5, 'shot ground'), (0.5, 'X+'), (0.5, 'steplog 12'), (0.5, 'shot up1'),
                  (0.5, 'steplog 10'), (0.5, 'shot up2'), (0.5, 'X-'), (0.5, 'steplog 60'), (0.5, 'shot landed'),
                  (0.5, 'unfreeze'), (1.0, 'end')],
    # metal: the fighter is marked "always metal", dropped below the stage and comes back metal (the game's own
    # routine, fighter.c:560); then it stands, smashes and jumps
    'face_metal': [(0.0, 'bag 90 0'), (0.3, 'metal'), (0.4, 'place 0 -400'), (6.5, 'shot back'), (7.0, 'freeze'), (7.0, 'shot stand'),
                   (7.0, 'stick 1.0 0.5'), (7.0, 'A+'), (7.0, 'steplog 2'), (7.0, 'A-'), (7.0, 'neutral'), (7.0, 'steplog 70'),
                   (7.0, 'X+'), (7.0, 'steplog 14'), (7.0, 'shot jump'), (7.0, 'X-'), (7.0, 'steplog 60'), (7.0, 'unfreeze'),
                   (7.4, 'perf metal'), (8.4, 'end')],
    # ---- attacks stepped a frame at a time INTO a target (a hit is its own thing to test: Wolf's dash attack
    # stopped the game on the frame it landed, and a sheet of pictures taken with the target out of reach never met it)
    **{f'hit_{n}': [(0.0, f'bag {far} 0'), (0.5, 'freeze'), (0.5, stick), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                    (0.5, 'steplog 62'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick, far in (('jab', 'stick 0.5 0.5', 8), ('ftilt', 'stick 0.65 0.5', 11), ('utilt', 'stick 0.5 0.68', 6), ('fsmash', 'stick 1.0 0.5', 12),
                             ('usmash', 'stick 0.5 1.0', 6), ('dsmash', 'stick 0.5 0.0', 9))},
    'hit_dtilt': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'steplog 10'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                  (0.5, 'neutral'), (0.5, 'steplog 48'), (0.5, 'unfreeze'), (1.0, 'end')],
    'hit_dash': [(0.0, 'bag 36 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 12'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                 (0.5, 'neutral'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    # (the dash attack's late hit: the target where the attack only reaches it near its end)
    **{f'hit_dash_{far}': [(0.0, f'bag {far} 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 12'), (0.5, 'A+'), (0.5, 'steplog 2'),
                           (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')] for far in (48, 54, 60, 66)},
    **{f'hit_{n}': [(0.0, 'bag 8 14'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 8'), (0.5, 'X-'), (0.5, stick), (0.5, 'A+'),
                    (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 40'), (0.5, 'unpin'), (0.5, 'steplog 30'),
                    (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('nair', 'stick 0.5 0.5'), ('fair', 'stick 1.0 0.5'), ('uair', 'stick 0.5 1.0'), ('dair', 'stick 0.5 0.0'))},
    # ---- Wolf's specials (states 373 on), stepped a frame at a time. PROBE_TRACK=1 follows his laser.
    # the Blaster with the target out of reach of the blade and in the laser's way; with it at the blade; in the air
    'w_laser': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_laser_far': [(0.0, 'bag 110 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_blade': [(0.0, 'bag 12 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_laser_air': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                    (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Wolf Flash: alone; into a target held where the dash ends; the stick up and down through the start; from the air
    'w_flash': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                (0.5, 'steplog 120'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_flash_hit': [(0.0, 'bag 40 17'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                    (0.5, 'neutral'), (0.5, 'steplog 26'), (0.5, 'unpin'), (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    **{f'w_flash_{n}': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, stick),
                        (0.5, 'steplog 20'), (0.5, 'neutral'), (0.5, 'steplog 100'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('up', 'stick 0.5 1.0'), ('down', 'stick 0.5 0.0'))},
    # (a target held in the air by the probe is still stood on the floor by the engine each frame, so its hurtboxes
    # are not where it is drawn: the arrival's hit is tested with the dash turned down onto a target that stands)
    'w_flash_down_hit': [(0.0, 'bag 46 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                         (0.5, 'stick 0.5 0.0'), (0.5, 'steplog 20'), (0.5, 'neutral'), (0.5, 'steplog 100'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_flash_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'),
                    (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 130'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Fire Wolf: the stick let go (straight up), held each way through the start; from the air; into a target above
    **{f'w_fire_{n}': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, stick),
                       (0.5, 'steplog 30'), (0.5, 'neutral'), (0.5, 'steplog 130'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick in (('up', 'neutral'), ('fwd', 'stick 1.0 0.5'), ('back', 'stick 0.0 0.5'), ('diag', 'stick 0.85 0.85'), ('down', 'stick 0.5 0.0'))},
    'w_fire_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'),
                   (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 170'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_fire_hit': [(0.0, 'bag 2 22'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                   (0.5, 'neutral'), (0.5, 'steplog 44'), (0.5, 'unpin'), (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Fire Wolf's fire, a picture a frame from the press through the gathering and the flight (36 frames), from the
    # side (s, the game's own view) and every second frame from an angle (a): does it wrap him and go with him?
    # Straight up from the ground facing right; aimed up and ahead facing left; aimed ahead from a jump. (Set
    # PROBE_EXTRA=150 for the three: 162 pictures.)
    **{f'w_look_fire_{n}': [(0.0, 'bag -60 0')] + ([(0.1, 'turn')] if n == 'left' else []) + [(0.6, 'freeze')]
                           + ([(0.6, 'X+'), (0.6, 'steplog 14'), (0.6, 'X-')] if n == 'air' else [])
                           + [(0.6, 'stick 0.5 1.0'), (0.6, 'B+'), (0.6, 'steplog 1'), (0.6, 'B-'), (0.6, aim)]
                           + [x for k in range(36) for x in ([(0.6, 'steplog 1'), (0.6, 'closeup 48 8 35 0'), (0.6, f'shot f{k:02d}s')]
                                                             + ([(0.6, 'closeup 48 8 35 55'), (0.6, f'shot f{k:02d}a')] if k % 2 else []))]
                           + [(0.6, 'neutral'), (0.6, 'steplog 30'), (0.6, 'unfreeze'), (1.2, 'end')]
       for n, aim in (('up', 'stick 0.5 1.0'), ('left', 'stick 0.15 0.85'), ('air', 'stick 1.0 0.5'))},
    # the Reflector: let go at once; held for a second; in the air; with a target beside him as it opens
    'w_ref': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
              (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_ref_held': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'),
                   (0.5, 'steplog 60'), (0.5, 'B-'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_ref_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'),
                  (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'), (0.5, 'steplog 30'), (0.5, 'B-'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_ref_hit': [(0.0, 'bag 7 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                  (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    # ... and a shot sent back: the second fighter (PROBE_BAG=0x02 Fox, who faces him) fires while it is held up
    # (the pad's 'neutral' lets every button go: a held button is kept with 'stick 0.5 0.5'. The second fighter is
    # given the pad with the special button still down: it reads a button it finds held as newly pressed, and fires.)
    'w_ref_shot': [(0.0, 'bag 40 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'stick 0.5 0.5'),
                   (1.0, 'steplog 12'), (1.0, 'pads 1 0'), (1.0, 'steplog 40'), (1.0, 'pads 0 1'),
                   (1.0, 'steplog 50'), (1.0, 'B-'), (1.0, 'steplog 40'), (1.0, 'unfreeze'), (1.6, 'end')],
    # ... and a slow shot sent back: the second fighter (PROBE_BAG=0x08 Mario) throws a fireball, the pad comes back,
    # and the reflector is held up until it arrives
    'w_ref_ball': [(0.0, 'bag 46 0'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'B+'), (1.0, 'steplog 3'), (1.0, 'B-'), (1.0, 'neutral'),
                   (1.0, 'steplog 6'), (1.0, 'pads 0 1'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'stick 0.5 0.5'),
                   (1.0, 'steplog 110'), (1.0, 'B-'), (1.0, 'neutral'), (1.0, 'steplog 30'), (1.0, 'unfreeze'), (1.6, 'end')],
    # his specials at the game's own speed, alone, for what they sound like (PROBE_AUDIO)
    'snd_w_n': [(0.0, 'bag 110 0'), (0.5, 'B+'), (0.58, 'B-'), (2.6, 'end')],
    'snd_w_s': [(0.0, 'bag -90 0'), (0.2, 'place -60 0'), (0.5, 'stick 1.0 0.5'), (0.52, 'B+'), (0.6, 'B-'), (0.62, 'neutral'), (3.2, 'end')],
    'snd_w_hi': [(0.0, 'bag -90 0'), (0.5, 'stick 0.5 1.0'), (0.52, 'B+'), (0.6, 'B-'), (0.62, 'neutral'), (4.2, 'end')],
    'snd_w_lw': [(0.0, 'bag 90 0'), (0.5, 'stick 0.5 0.0'), (0.52, 'B+'), (0.6, 'stick 0.5 0.5'), (1.4, 'B-'), (1.42, 'neutral'), (2.8, 'end')],
    # the fighter's own numbers as the game holds them; a full hop with the second jump at its top; a run timed
    'w_attrs': [(0.0, 'bag 60 0'), (0.3, 'attrs'), (0.6, 'end')],
    'w_jump2': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 26'), (0.5, 'X-'), (0.5, 'steplog 2'), (0.5, 'X+'),
                (0.5, 'steplog 40'), (0.5, 'X-'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_run': [(0.0, 'bag -60 0'), (0.2, 'place -70 0'), (0.6, 'freeze'), (0.6, 'stick 1.0 0.5'), (0.6, 'steplog 62'), (0.6, 'neutral'),
              (0.6, 'steplog 40'), (0.6, 'unfreeze'), (1.0, 'end')],
    'w_walk': [(0.0, 'bag -60 0'), (0.2, 'place -70 0'), (0.6, 'freeze'), (0.6, 'stick 0.72 0.5'), (0.6, 'steplog 62'), (0.6, 'neutral'),
               (0.6, 'steplog 30'), (0.6, 'unfreeze'), (1.0, 'end')],
    # Fire Wolf along the ground through a target that stands: its hits every two frames, then the landing kick
    'w_fire_fwd_hit': [(0.0, 'bag 14 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                       (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 30'), (0.5, 'neutral'), (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    # ... and aimed up through a target standing on him (it is carried up by the hits)
    'w_fire_up_hit': [(0.0, 'bag 3 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                      (0.5, 'neutral'), (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')],
    # aerials out of a short hop onto a target that stands (a target held in the air is not where it is drawn)
    **{f'sh_{n}': [(0.0, f'bag {far} 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 2'), (0.5, 'X-'), (0.5, f'steplog {wait}'), (0.5, stick),
                   (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')]
       for n, stick, far, wait in (('nair', 'stick 0.5 0.5', 8, 3), ('fair', 'stick 1.0 0.5', 10, 3), ('bair', 'stick 0.0 0.5', -9, 3),
                                   ('uair', 'stick 0.5 1.0', 5, 2), ('dair', 'stick 0.5 0.0', 6, 8))},
    # the reflect test again, at the game's own speed (no stepping): Mario throws, the pad comes back, the reflector is held
    'w_ref_ball_rt': [(0.0, 'bag 46 0'), (1.0, 'pads 1 0'), (1.02, 'B+'), (1.1, 'B-'), (1.12, 'neutral'), (1.2, 'pads 0 1'),
                      (1.22, 'stick 0.5 0.0'), (1.24, 'B+'), (1.3, 'stick 0.5 0.5'), (3.2, 'B-'), (3.22, 'neutral'), (4.6, 'end')],
    # the standing blink stepped with the camera on HIS head (`look_blink` parks its own camera, set for an earlier
    # fighter's head, over whatever PROBE_CLOSEUP says); PROBE_STEPSHOT=first-last picks the clip frames photographed
    'w_blink': [(0.0, 'bag 60 0'), (0.3, 'closeup 13 11.6 22 75'), (0.3, 'freeze'), (0.3, 'steplog 150'), (0.3, 'unfreeze'), (0.6, 'end')],
    # his face close up through a forward smash (the mouth opens), and as the second fighter's smash lands on him
    'w_face_smash': [(0.0, 'bag 90 0'), (0.3, 'closeup 13 11.6 22 75'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'),
                     (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 10'), (0.5, 'shot f12'), (0.5, 'steplog 8'), (0.5, 'shot f20'),
                     (0.5, 'steplog 6'), (0.5, 'shot f26'), (0.5, 'steplog 30'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_face_hurt': [(0.0, 'bag 14 0'), (0.3, 'closeup 16 10.5 24 75'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 0.0 0.5'), (1.0, 'A+'),
                    (1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 20'), (1.0, 'shot h22'), (1.0, 'steplog 4'), (1.0, 'shot h26'),
                    (1.0, 'steplog 6'), (1.0, 'shot h32'), (1.0, 'steplog 12'), (1.0, 'shot h44'), (1.0, 'pads 0 1'), (1.0, 'steplog 40'),
                    (1.0, 'unfreeze'), (1.6, 'end')],
    # the up aerial on a target that has jumped: the second fighter is given the pad for its jump, then he jumps under it
    'sh_uair2': [(0.0, 'bag 3 0'), (0.5, 'freeze'), (0.5, 'pads 1 0'), (0.5, 'X+'), (0.5, 'steplog 8'), (0.5, 'X-'), (0.5, 'neutral'),
                 (0.5, 'pads 0 1'), (0.5, 'X+'), (0.5, 'steplog 5'), (0.5, 'stick 0.5 1.0'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                 (0.5, 'X-'), (0.5, 'neutral'), (0.5, 'steplog 50'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the same blink from two more sides (his left eye is under a patch: the first camera saw only that side)
    'w_blink_a': [(0.0, 'bag 60 0'), (0.3, 'closeup 13 11.6 22 110'), (0.3, 'freeze'), (0.3, 'steplog 75'), (0.3, 'unfreeze'), (0.6, 'end')],
    'w_blink_b': [(0.0, 'bag 60 0'), (0.3, 'closeup 13 11.6 22 -60'), (0.3, 'freeze'), (0.3, 'steplog 75'), (0.3, 'unfreeze'), (0.6, 'end')],
    # the hurt face with the hitter BEHIND him (in front, the hitter fills the close-up)
    'w_face_hurt2': [(0.0, 'bag -14 0'), (0.3, 'closeup 16 11.0 24 110'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 1.0 0.5'), (1.0, 'A+'),
                     (1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 20'), (1.0, 'shot h22'), (1.0, 'steplog 2'), (1.0, 'shot h24'),
                     (1.0, 'steplog 2'), (1.0, 'shot h26'), (1.0, 'steplog 3'), (1.0, 'shot h29'), (1.0, 'pads 0 1'), (1.0, 'steplog 50'),
                     (1.0, 'unfreeze'), (1.6, 'end')],
    'w_face_hurt3': [(0.0, 'bag -14 0'), (0.3, 'closeup 16 11.0 24 -60'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 1.0 0.5'), (1.0, 'A+'),
                     (1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 20'), (1.0, 'shot h22'), (1.0, 'steplog 2'), (1.0, 'shot h24'),
                     (1.0, 'steplog 2'), (1.0, 'shot h26'), (1.0, 'steplog 3'), (1.0, 'shot h29'), (1.0, 'pads 0 1'), (1.0, 'steplog 50'),
                     (1.0, 'unfreeze'), (1.6, 'end')],
    # (the close-up camera stands at sin(yaw), cos(yaw) of its distance in x and z: 50 is his right-front as he faces right)
    'w_blink_c': [(0.0, 'bag 60 0'), (0.3, 'closeup 13 11.6 22 50'), (0.3, 'freeze'), (0.3, 'steplog 75'), (0.3, 'unfreeze'), (0.6, 'end')],
    # a hit taken from far off, so that nothing stands between the camera and his face: the second fighter's shot (PROBE_BAG=0x08)
    'w_face_hurt4': [(0.0, 'bag 46 0'), (0.3, 'closeup 15 11.0 24 50'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'B+'), (1.0, 'steplog 3'),
                     (1.0, 'B-'), (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 32'), (1.0, 'shot s35'), (1.0, 'steplog 2'),
                     (1.0, 'shot s37'), (1.0, 'steplog 2'), (1.0, 'shot s39'), (1.0, 'steplog 2'), (1.0, 'shot s41'), (1.0, 'steplog 3'),
                     (1.0, 'shot s44'), (1.0, 'steplog 4'), (1.0, 'shot s48'), (1.0, 'steplog 30'), (1.0, 'unfreeze'), (1.6, 'end')],
    # Fire Wolf's pulse as he gathers himself, and the flash as a shot is sent back: a picture on each of the frames
    'w_flash_hi': [(0.0, 'bag 80 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                   (0.5, 'steplog 2'), (0.5, 'shot f4'), (0.5, 'steplog 1'), (0.5, 'shot f5'), (0.5, 'steplog 1'), (0.5, 'shot f6'),
                   (0.5, 'steplog 1'), (0.5, 'shot f7'), (0.5, 'steplog 1'), (0.5, 'shot f8'), (0.5, 'steplog 1'), (0.5, 'shot f9'),
                   (0.5, 'steplog 120'), (0.5, 'unfreeze'), (1.0, 'end')],
    'w_flash_lw': [(0.0, 'bag 46 0'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'B+'), (1.0, 'steplog 3'), (1.0, 'B-'), (1.0, 'neutral'),
                   (1.0, 'steplog 6'), (1.0, 'pads 0 1'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'stick 0.5 0.5'),
                   (1.0, 'steplog 21'), (1.0, 'shot r32'), (1.0, 'steplog 1'), (1.0, 'shot r33'), (1.0, 'steplog 1'), (1.0, 'shot r34'),
                   (1.0, 'steplog 1'), (1.0, 'shot r35'), (1.0, 'steplog 1'), (1.0, 'shot r36'), (1.0, 'steplog 1'), (1.0, 'shot r37'),
                   (1.0, 'steplog 1'), (1.0, 'shot r38'), (1.0, 'steplog 2'), (1.0, 'shot r40'), (1.0, 'steplog 30'), (1.0, 'B-'),
                   (1.0, 'neutral'), (1.0, 'steplog 30'), (1.0, 'unfreeze'), (1.6, 'end')],
    # the knock-down again for a fighter one forward smash does not floor at nothing (`step_down_*` left Wolf on his feet):
    # he stands right of the middle with 15 per cent on him, is hit to the left and lands on the stage; then each way up
    **{f'w_down_{n}': [(0.0, 'place 40 0'), (0.2, 'bag 14 0'), (0.4, 'percent 15'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 0.0 0.5'),
                       (1.0, 'A+'), (1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 170'), (1.0, 'pads 0 1'), (1.0, press),
                       (1.0, 'steplog 3'), (1.0, 'neutral'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')]
       for n, press in (('stand', 'stick 0.5 1.0'), ('attack', 'A+'), ('rollf', 'stick 1.0 0.5'), ('rollb', 'stick 0.0 0.5'))},
    # ... and the tech: shield pressed `wait` frames after the hit is asked for (W_TECH: read the landing frame off w_down_stand)
    **{f'w_tech_{n}': [(0.0, 'place 40 0'), (0.2, 'bag 14 0'), (0.4, 'percent 15'), (1.0, 'freeze'), (1.0, 'pads 1 0'), (1.0, 'stick 0.0 0.5'),
                       (1.0, 'A+'), (1.0, 'steplog 2'), (1.0, 'neutral'), (1.0, 'steplog 28'), (1.0, 'pads 0 1'),
                       (1.0, f"steplog {int(os.environ.get('W_TECH', '40')) - 30}"), (1.0, stick), (1.0, 'R+'), (1.0, 'steplog 14'),
                       (1.0, 'neutral'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')]
       for n, stick in (('place', 'stick 0.5 0.5'), ('f', 'stick 1.0 0.5'), ('b', 'stick 0.0 0.5'))},
    # pictures of each special, facing each way, at the game's own speed
    **{f'w_look_{n}_{side}': [(0.0, 'bag 70 0')] + ([(0.1, 'turn')] if side == 'left' else [])
                             + [(0.9, stick), (0.92, 'B+'), (1.0, 'B-'), (1.0, 'neutral')]
                             + [(1.0 + t, f'shot {side[0]}{i}') for i, t in enumerate(times)] + [(1.0 + times[-1] + 1.2, 'end')]
       for side in ('right', 'left')
       for n, stick, times in (('n', 'stick 0.5 0.5', (0.12, 0.22, 0.3, 0.45, 0.7)), ('s', 'stick 1.0 0.5' if side == 'right' else 'stick 0.0 0.5', (0.1, 0.24, 0.3, 0.34, 0.45, 0.8)),
                               ('hi', 'stick 0.5 1.0', (0.15, 0.36, 0.45, 0.5, 0.58, 0.7, 1.0)), ('lw', 'stick 0.5 0.0', (0.06, 0.12, 0.2, 0.35, 0.5)))},
    # ---- Greninja's specials (own_gekkouga: states 373 on), stepped a frame at a time. PROBE_TRACK=1 follows the
    # first item (the shuriken, the water).
    # Water Shuriken: a tap (thrown uncharged); held 20 frames past the gathering (the second of four levels); held to
    # the full charge (thrown by itself, a target at its end); from a jump; the full one facing left
    'gk_shu_tap': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 32'),
                   (0.5, 'shot n34'), (0.5, 'steplog 4'), (0.5, 'shot n38'), (0.5, 'steplog 50'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_shu_half': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 46'), (0.5, 'B-'), (0.5, 'steplog 10'),
                    (0.5, 'shot n56'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_shu_full': [(0.0, 'bag 50 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 40'), (0.5, 'shot h40'), (0.5, 'steplog 32'),
                    (0.5, 'shot m72'), (0.5, 'steplog 6'), (0.5, 'shot m78'), (0.5, 'steplog 10'), (0.5, 'shot m88'), (0.5, 'B-'),
                    (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_shu_air': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 6'), (0.5, 'X-'), (0.5, 'B+'), (0.5, 'steplog 2'),
                   (0.5, 'B-'), (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    # (facing left: turned, then let stand still before the target is put in front and the game is held: a button
    # pressed while the turn's dash runs is not taken)
    'gk_shu_left': [(0.1, 'turn'), (1.0, 'bag 50 0'), (1.1, 'freeze'), (1.1, 'B+'), (1.1, 'steplog 40'), (1.1, 'shot h40'),
                    (1.1, 'steplog 32'), (1.1, 'shot m72'), (1.1, 'steplog 6'), (1.1, 'shot m78'), (1.1, 'B-'), (1.1, 'steplog 70'),
                    (1.1, 'unfreeze'), (1.6, 'end')],
    # Shadow Sneak: readied 30 frames with a target near the shadow, the stick let go (the kick ahead); the stick held
    # back as he comes out (the kick behind); from a jump, let go at once; facing left
    'gk_sneak': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'),
                 (0.5, 'steplog 14'), (0.5, 'shot r16'), (0.5, 'steplog 14'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 8'),
                 (0.5, 'shot g8'), (0.5, 'steplog 11'), (0.5, 'shot k1'), (0.5, 'steplog 6'), (0.5, 'shot k7'), (0.5, 'steplog 70'),
                 (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_sneak_back': [(0.0, 'bag 44 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'),
                      (0.5, 'steplog 28'), (0.5, 'B-'), (0.5, 'stick 0.0 0.5'), (0.5, 'steplog 19'), (0.5, 'shot k1'), (0.5, 'neutral'),
                      (0.5, 'steplog 6'), (0.5, 'shot k7'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_sneak_air': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'),
                     (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 130'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_sneak_left': [(0.1, 'turn'), (1.0, 'bag 60 0'), (1.1, 'freeze'), (1.1, 'stick 0.0 0.5'), (1.1, 'B+'), (1.1, 'steplog 2'),
                      (1.1, 'stick 0.5 0.5'), (1.1, 'steplog 14'), (1.1, 'shot r16'), (1.1, 'steplog 14'), (1.1, 'B-'), (1.1, 'neutral'),
                      (1.1, 'steplog 19'), (1.1, 'shot k1'), (1.1, 'steplog 6'), (1.1, 'shot k7'), (1.1, 'steplog 70'), (1.1, 'unfreeze'),
                      (1.6, 'end')],
    # Hydro Pump: the stick let go (straight up); held up and ahead; from a jump; facing left, aimed up and ahead; with a
    # target beside him for the water
    'gk_pump': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                (0.5, 'steplog 16'), (0.5, 'shot j2'), (0.5, 'steplog 8'), (0.5, 'shot j10'), (0.5, 'steplog 10'), (0.5, 'shot j20'),
                (0.5, 'steplog 120'), (0.5, 'unfreeze'), (1.0, 'end')],
    # (the stick straight up as B is pressed, or it is the side special; aimed while he gathers himself)
    'gk_pump_diag': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                     (0.5, 'stick 0.85 0.85'), (0.5, 'steplog 16'), (0.5, 'shot j2'), (0.5, 'steplog 8'), (0.5, 'shot j10'),
                     (0.5, 'steplog 10'), (0.5, 'shot j20'), (0.5, 'neutral'), (0.5, 'steplog 120'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_pump_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'),
                    (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 170'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_pump_left': [(0.1, 'turn'), (1.0, 'bag 60 0'), (1.1, 'freeze'), (1.1, 'stick 0.5 1.0'), (1.1, 'B+'), (1.1, 'steplog 2'),
                     (1.1, 'B-'), (1.1, 'stick 0.15 0.85'), (1.1, 'steplog 16'), (1.1, 'shot j2'), (1.1, 'steplog 8'), (1.1, 'shot j10'),
                     (1.1, 'steplog 10'), (1.1, 'shot j20'), (1.1, 'neutral'), (1.1, 'steplog 120'), (1.1, 'unfreeze'), (1.6, 'end')],
    'gk_pump_water': [(0.0, 'bag 5 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                      (0.5, 'neutral'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Substitute: alone (nothing strikes); struck by the second fighter's jab inside the window, the stick let go (he
    # comes out at its back); the same with the stick held down (from above, down); from a jump, alone; struck facing left
    'gk_sub': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
               (0.5, 'steplog 20'), (0.5, 'shot p22'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_sub_hit': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                   (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'), (1.0, 'neutral'),
                   (1.0, 'pads 0 1'), (1.0, 'steplog 8'), (1.0, 'shot c1'), (1.0, 'steplog 8'), (1.0, 'shot c2'), (1.0, 'steplog 8'),
                   (1.0, 'shot c3'), (1.0, 'steplog 6'), (1.0, 'shot c4'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')],
    'gk_sub_down': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                    (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'), (1.0, 'neutral'),
                    (1.0, 'pads 0 1'), (1.0, 'stick 0.5 0.0'), (1.0, 'steplog 16'), (1.0, 'shot c2'), (1.0, 'steplog 8'), (1.0, 'shot c3'),
                    (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'shot c4'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')],
    'gk_sub_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'),
                   (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')],
    # (facing left with the target behind him: it faces him and strikes his back)
    'gk_sub_left': [(0.1, 'turn'), (0.9, 'bag -14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                    (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'), (1.0, 'neutral'),
                    (1.0, 'pads 0 1'), (1.0, 'steplog 16'), (1.0, 'shot c2'), (1.0, 'steplog 8'), (1.0, 'shot c3'), (1.0, 'steplog 6'),
                    (1.0, 'shot c4'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')],
    # where an item of his strikes as it is made: the shuriken let go into a target beside him; the pump's water
    # striking a target behind him a few frames after it is made (the jet aimed up and ahead)
    'gk_shu_point': [(0.0, 'bag 8 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 50'),
                     (0.5, 'unfreeze'), (1.0, 'end')],
    'gk_pump_water_late': [(0.0, 'bag -20 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'),
                           (0.5, 'B-'), (0.5, 'stick 0.85 0.85'), (0.5, 'steplog 40'), (0.5, 'neutral'), (0.5, 'steplog 60'),
                           (0.5, 'unfreeze'), (1.0, 'end')],
    # Incineroar (own_gaogaen.py). Darkest Lariat with the stick held ahead (he is carried into the bag), and in the air;
    # Alolan Whip into a bag in reach (caught, pulled in, thrown forward) and into nothing; Cross Chop from the ground
    # and from a jump; Revenge struck by the bag's jab, then his own forward tilt with the power kept
    'ig_lariat': [(0.0, 'bag 30 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'stick 1.0 0.5'),
                  (0.5, 'steplog 90'), (0.5, 'neutral'), (0.5, 'unfreeze'), (1.0, 'end')],
    'ig_lariat_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 6'), (0.5, 'X-'), (0.5, 'B+'),
                      (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 100'), (0.5, 'unfreeze'), (1.0, 'end')],
    'ig_whip': [(0.0, 'bag 24 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                (0.5, 'neutral'), (0.5, 'steplog 30'), (0.5, 'shot pulled'), (0.5, 'steplog 30'), (0.5, 'shot thrown'),
                (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'ig_whip_miss': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                     (0.5, 'neutral'), (0.5, 'steplog 70'), (0.5, 'unfreeze'), (1.0, 'end')],
    'ig_chop': [(0.0, 'bag 12 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                (0.5, 'neutral'), (0.5, 'steplog 28'), (0.5, 'shot top'), (0.5, 'steplog 14'), (0.5, 'shot dive'),
                (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.5, 'end')],
    'ig_chop_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 10'), (0.5, 'X-'), (0.5, 'stick 0.5 1.0'),
                    (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 130'), (0.5, 'unfreeze'),
                    (1.5, 'end')],
    'ig_revenge': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                   (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'),
                   (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 12'), (1.0, 'shot strike'), (1.0, 'steplog 50'),
                   (1.0, 'stick 1.0 0.5'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'), (1.0, 'neutral'), (1.0, 'steplog 50'),
                   (1.0, 'unfreeze'), (1.6, 'end')],
    'ig_revenge_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 10'), (0.5, 'X-'), (0.5, 'stick 0.5 0.0'),
                       (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 70'), (0.5, 'unfreeze'),
                       (1.0, 'end')],
    # his forward tilt alone, for the damage it does without Revenge's power
    'ig_ftilt': [(0.0, 'bag 14 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 3'), (0.5, 'A-'),
                 (0.5, 'neutral'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Revenge struck by the bag's jab with the bag pinned in front (round 1: the strike back sent it out of reach), then
    # his forward tilt: the bag's damage from it against ig_ftilt's
    'ig_revenge_power': [(0.0, 'bag 14 0'), (0.0, 'pin'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'),
                         (1.0, 'steplog 2'), (1.0, 'B-'), (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'pads 1 0'),
                         (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'), (1.0, 'neutral'), (1.0, 'pads 0 1'),
                         (1.0, 'steplog 50'), (1.0, 'stick 1.0 0.5'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'),
                         (1.0, 'neutral'), (1.0, 'steplog 40'), (1.0, 'unfreeze'), (1.6, 'end')],
    # Shulk (own_shulk.py). Monado Arts: his numbers read as each press puts on the next art (Jump, Speed, Shield,
    # Buster, Smash); his forward tilt's damage alone, in Buster and in Smash; a full jump alone and in Jump; Back Slash
    # into a bag ahead; Air Slash and its follow-up; Vision struck by the bag's jab; and Vision a third time in a row,
    # struck late (the window has shrunk: not caught), against the same late jab on a first use (caught)
    'sk_arts_numbers': [(0.0, 'bag 60 0'), (0.3, 'attrs'), (0.5, 'B+'), (0.58, 'B-'), (1.2, 'attrs'), (1.5, 'B+'),
                        (1.58, 'B-'), (2.2, 'attrs'), (2.5, 'B+'), (2.58, 'B-'), (3.2, 'attrs'), (3.5, 'B+'), (3.58, 'B-'),
                        (4.2, 'attrs'), (4.5, 'B+'), (4.58, 'B-'), (5.2, 'attrs'), (5.5, 'end')],
    'sk_fsmash': [(0.0, 'bag 16 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 3'), (0.5, 'A-'),
                 (0.5, 'neutral'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'sk_buster_fsmash': [(0.0, 'bag 60 0'), (0.3, 'B+'), (0.38, 'B-'), (0.8, 'B+'), (0.88, 'B-'), (1.3, 'B+'), (1.38, 'B-'),
                        (1.8, 'B+'), (1.88, 'B-'), (2.3, 'attrs'), (2.4, 'bag 16 0'), (2.8, 'freeze'), (2.8, 'stick 1.0 0.5'),
                        (2.8, 'A+'), (2.8, 'steplog 3'), (2.8, 'A-'), (2.8, 'neutral'), (2.8, 'steplog 40'), (2.8, 'unfreeze'),
                        (3.3, 'end')],
    'sk_smash_ftilt': [(0.0, 'bag 60 0'), (0.3, 'B+'), (0.38, 'B-'), (0.8, 'B+'), (0.88, 'B-'), (1.3, 'B+'), (1.38, 'B-'),
                       (1.8, 'B+'), (1.88, 'B-'), (2.3, 'B+'), (2.38, 'B-'), (2.8, 'bag 16 0'), (3.2, 'freeze'),
                       (3.2, 'stick 1.0 0.5'), (3.2, 'A+'), (3.2, 'steplog 3'), (3.2, 'A-'), (3.2, 'neutral'), (3.2, 'steplog 40'),
                       (3.2, 'unfreeze'), (3.7, 'end')],
    'sk_jump': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 6'), (0.5, 'X-'), (0.5, 'steplog 70'),
                (0.5, 'unfreeze'), (1.0, 'end')],
    'sk_jump_art': [(0.0, 'bag -60 0'), (0.3, 'B+'), (0.38, 'B-'), (1.0, 'freeze'), (1.0, 'X+'), (1.0, 'steplog 6'), (1.0, 'X-'),
                    (1.0, 'steplog 90'), (1.0, 'unfreeze'), (1.5, 'end')],
    'sk_backslash': [(0.0, 'bag 30 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                     (0.5, 'neutral'), (0.5, 'steplog 30'), (0.5, 'shot blade'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'sk_airslash': [(0.0, 'bag 14 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                    (0.5, 'neutral'), (0.5, 'steplog 22'), (0.5, 'shot top'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                    (0.5, 'steplog 12'), (0.5, 'shot add'), (0.5, 'steplog 120'), (0.5, 'unfreeze'), (1.5, 'end')],
    'sk_vision': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                  (1.0, 'neutral'), (1.0, 'steplog 6'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'),
                  (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 12'), (1.0, 'shot strike'), (1.0, 'steplog 60'),
                  (1.0, 'unfreeze'), (1.6, 'end')],
    'sk_vision_late': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                       (1.0, 'neutral'), (1.0, 'steplog 18'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'),
                       (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')],
    'sk_vision_row': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                      (1.0, 'neutral'), (1.0, 'steplog 72'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                      (1.0, 'neutral'), (1.0, 'steplog 72'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'),
                      (1.0, 'B-'), (1.0, 'neutral'), (1.0, 'steplog 18'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'),
                      (1.0, 'A-'), (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')],
    # Back Slash into a bag that faces him (its front hits: 10%) and into one with its back to him (its back ones: 16%)
    'sk_backslash_front': [(0.0, 'bag 30 0'), (0.0, 'bagface -1'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'),
                           (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 110'), (0.5, 'unfreeze'),
                           (1.0, 'end')],
    'sk_backslash_back': [(0.0, 'bag 30 0'), (0.0, 'bagface 1'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'),
                          (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 30'), (0.5, 'shot blade'),
                          (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    # round 1 struck at about frame 25, the edge of both windows; these strike at about frame 32, inside a first use's
    # window (35 frames from frame 7) and past a third use's (35 x 0.66 x 0.66 = 15)
    'sk_vision_30': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                     (1.0, 'neutral'), (1.0, 'steplog 27'), (1.0, 'pads 1 0'), (1.0, 'A+'), (1.0, 'steplog 3'), (1.0, 'A-'),
                     (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 70'), (1.0, 'unfreeze'), (1.6, 'end')],
    'sk_vision_row30': [(0.0, 'bag 14 0'), (1.0, 'freeze'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'), (1.0, 'B-'),
                        (1.0, 'neutral'), (1.0, 'steplog 72'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'), (1.0, 'steplog 2'),
                        (1.0, 'B-'), (1.0, 'neutral'), (1.0, 'steplog 72'), (1.0, 'stick 0.5 0.0'), (1.0, 'B+'),
                        (1.0, 'steplog 2'), (1.0, 'B-'), (1.0, 'neutral'), (1.0, 'steplog 27'), (1.0, 'pads 1 0'), (1.0, 'A+'),
                        (1.0, 'steplog 3'), (1.0, 'A-'), (1.0, 'neutral'), (1.0, 'pads 0 1'), (1.0, 'steplog 70'),
                        (1.0, 'unfreeze'), (1.6, 'end')],
    # (leftovers) how three arts are shown, photographed as each starts (its symbol), on (its aura) and in a swing (the
    # glow at his sword hand, and the blade's trail: his forward tilt's script draws it on frames 12 to 16, the shot
    # is on the 14th): Jump, Speed, Shield; the art voices are listened for (audio_check). The tilt is `stick 0.65`:
    # the stick at 1.0 with A in one frozen frame is a forward SMASH (no trail in its script), whose 97 frames ate the
    # next art's press (game run 9, the first boot)
    'sk_arts_show': [(0.0, 'bag 60 0')] + [
        step for k, art in enumerate(('jump', 'speed', 'shield'))
        for step in [(0.5 + 1.2 * k, 'freeze'), (0.5 + 1.2 * k, 'B+'), (0.5 + 1.2 * k, 'steplog 2'),
                     (0.5 + 1.2 * k, 'B-'), (0.5 + 1.2 * k, 'steplog 8'), (0.5 + 1.2 * k, f'shot {art}_start'),
                     (0.5 + 1.2 * k, 'steplog 22'), (0.5 + 1.2 * k, f'shot {art}_symbol'), (0.5 + 1.2 * k, 'steplog 20'),
                     (0.5 + 1.2 * k, 'stick 0.65 0.5'), (0.5 + 1.2 * k, 'A+'), (0.5 + 1.2 * k, 'steplog 3'),
                     (0.5 + 1.2 * k, 'A-'), (0.5 + 1.2 * k, 'neutral'), (0.5 + 1.2 * k, 'steplog 11'),
                     (0.5 + 1.2 * k, f'shot {art}_swing'), (0.5 + 1.2 * k, 'steplog 35'), (0.5 + 1.2 * k, f'shot {art}_on'),
                     (0.5 + 1.2 * k, 'unfreeze')]] + [(4.2, 'end')],
    # the sword trail read from the game (`trail`) and photographed: his down smash, whose script draws it from frame
    # 15 to 45 (the own route's `own_trail`, on `swordr`), before it, twice in it and after it
    'sk_trail': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'trail'), (0.5, 'stick 0.5 0.0'), (0.5, 'A+'), (0.5, 'steplog 3'),
                 (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 9'), (0.5, 'trail'), (0.5, 'steplog 10'), (0.5, 'trail'),
                 (0.5, 'shot dsmash_22'), (0.5, 'steplog 10'), (0.5, 'trail'), (0.5, 'shot dsmash_32'),
                 (0.5, 'steplog 20'), (0.5, 'trail'), (0.5, 'unfreeze'), (1.2, 'end')],
    # his forward throw in Buster (the fourth press) against the same in Smash (the fifth): the damage the bag takes
    # differs as the arts' attack_power_mul do (1.4 and 0.3); every art's voice is listened for on the way
    'sk_buster_throw': [(0.0, 'bag 60 0'), (0.3, 'B+'), (0.38, 'B-'), (0.8, 'B+'), (0.88, 'B-'), (1.3, 'B+'), (1.38, 'B-'),
                        (1.8, 'B+'), (1.88, 'B-'), (2.3, 'bag 9 0'), (2.7, 'Z+'), (2.78, 'Z-'), (3.4, 'stick 1.0 0.5'),
                        (3.5, 'neutral'), (5.0, 'end')],
    'sk_smash_throw': [(0.0, 'bag 60 0'), (0.3, 'B+'), (0.38, 'B-'), (0.8, 'B+'), (0.88, 'B-'), (1.3, 'B+'), (1.38, 'B-'),
                       (1.8, 'B+'), (1.88, 'B-'), (2.3, 'B+'), (2.38, 'B-'), (2.8, 'bag 9 0'), (3.2, 'Z+'), (3.28, 'Z-'),
                       (3.9, 'stick 1.0 0.5'), (4.0, 'neutral'), (5.5, 'end')],
    # ---- Ittle Dew's specials (Slap City; states 373 on). PROBE_TRACK=1 follows her fireball.
    # the fire sword's fireball with the target in its way; from a jump
    # (pictures: the fireball as it leaves the mace and six frames on; it is made on her frame 13 and flies 3.4 a
    # frame, so the camera stands far enough back to keep it in the picture to frame 20: at 70 it was off the edge)
    'id_fire': [(0.0, 'bag 60 0'), (0.3, 'closeup 100 10 35 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 12'), (0.5, 'shot fly1'),
                (0.5, 'steplog 6'), (0.5, 'shot fly2'), (0.5, 'steplog 72'), (0.5, 'unfreeze'), (1.0, 'end')],
    'id_fire_air': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                    (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the fire mace held to the charge's most (15 counted from her frame 6, so let go by itself on frame 20): the
    # bigger swing (PROBE_BOXES=1: its size) and the slow fireball that strikes the target six times a frame apart
    # (pictures: the swing, the fireball on its way)
    'id_fire_hold': [(0.0, 'bag 60 0'), (0.3, 'closeup 100 10 35 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 22'), (0.5, 'shot swing'),
                     (0.5, 'B-'), (0.5, 'steplog 6'), (0.5, 'shot fly1'), (0.5, 'steplog 8'), (0.5, 'shot fly2'), (0.5, 'steplog 70'),
                     (0.5, 'unfreeze'), (1.0, 'end')],
    # the bomb, thrown with the stick let go (5 ahead and 15 up, the game's units a second): it bounces along to the
    # target and bursts on its 90th frame (PROBE_ITEMS=1: its place and state each frame; pictures: thrown, on its
    # way, the burst)
    'id_side': [(0.0, 'bag 38 0'), (0.3, 'closeup 130 12 35 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                (0.5, 'neutral'), (0.5, 'steplog 15'), (0.5, 'shot throw'), (0.5, 'steplog 20'), (0.5, 'shot fly'), (0.5, 'steplog 71'),
                (0.5, 'shot burst'), (0.5, 'steplog 30'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the teleport from the ground: the ball made on her frame 21 flies ahead and up (the stick let go), is steered
    # right from frame 33 and stands on 40; on 41 she is where it is, then her helpless fall to a landing
    # (PROBE_ITEMS=1: the ball each frame; pictures: the ball, and the frames before and after she goes to it)
    'id_up': [(0.0, 'bag -60 0'), (0.3, 'closeup 110 20 35 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
              (0.5, 'neutral'), (0.5, 'steplog 20'), (0.5, 'shot ball'), (0.5, 'steplog 10'), (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 8'),
              (0.5, 'shot before'), (0.5, 'steplog 1'), (0.5, 'shot after'), (0.5, 'neutral'), (0.5, 'steplog 100'), (0.5, 'unfreeze'),
              (1.0, 'end')],
    'id_up_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'),
                  (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the down special: the hop, the dive and the blast as she lands, beside the target; from a jump
    'id_down': [(0.0, 'bag 12 0'), (0.3, 'closeup 55 12 35 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
                (0.5, 'steplog 28'), (0.5, 'shot dive'), (0.5, 'steplog 16'), (0.5, 'shot landed'), (0.5, 'steplog 46'), (0.5, 'unfreeze'),
                (1.0, 'end')],
    'id_down_air': [(0.0, 'bag 12 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'),
                    (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 110'), (0.5, 'unfreeze'), (1.0, 'end')],
    # her normals onto a standing target, stepped, a picture on the frame the game's first hit comes out (the
    # driver's table: forward smash 16, up smash 15, down smash 30, down tilt 7, neutral air 6, forward air 7)
    'id_fsmash': [(0.0, 'bag 14 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                  (0.5, 'steplog 14'), (0.5, 'shot hit'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'id_usmash': [(0.0, 'bag 6 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                  (0.5, 'steplog 13'), (0.5, 'shot hit'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'id_dsmash': [(0.0, 'bag 8 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                  (0.5, 'steplog 28'), (0.5, 'shot hit'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'id_dtilt': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'steplog 10'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                 (0.5, 'neutral'), (0.5, 'steplog 5'), (0.5, 'shot hit'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'id_nair': [(0.0, 'bag 10 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 1'), (0.5, 'X-'), (0.5, 'steplog 6'), (0.5, 'A+'), (0.5, 'steplog 2'),
                (0.5, 'A-'), (0.5, 'steplog 4'), (0.5, 'shot hit'), (0.5, 'steplog 50'), (0.5, 'unfreeze'), (1.0, 'end')],
    'id_fair': [(0.0, 'bag 13 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 1'), (0.5, 'X-'), (0.5, 'steplog 6'), (0.5, 'stick 1.0 0.5'),
                (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 5'), (0.5, 'shot hit'), (0.5, 'steplog 50'),
                (0.5, 'unfreeze'), (1.0, 'end')],
    # the same with nothing to strike (the target behind her): its ice sound (her frame 7) on its own, not under a
    # hit's, and early in the boot's sound
    'id_fair_alone': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 1'), (0.5, 'X-'), (0.5, 'steplog 6'), (0.5, 'stick 1.0 0.5'),
                      (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 55'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the forward air into a bag held where it stands: the game's three strikes (frames 7, 12 and 17), the last harder
    'id_fair_pinned': [(0.0, 'bag 13 0'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 1'), (0.5, 'X-'), (0.5, 'steplog 6'),
                       (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 14'),
                       (0.5, 'shot third'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    # her numbers, the squat before a full jump, then steering in the air: the stick a little, then full, then let go
    # (the game steps her speed by the same amount however far the stick leans, up to air speed x stick, and lets it
    # die slowly)
    'id_drift': [(0.0, 'bag 90 0'), (0.3, 'attrs'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 8'), (0.5, 'vel'),
                 (0.5, 'stick 0.7 0.5'), (0.5, 'step 1'), (0.5, 'vel'), (0.5, 'step 1'), (0.5, 'vel'), (0.5, 'step 6'), (0.5, 'vel'),
                 (0.5, 'stick 1.0 0.5'), (0.5, 'step 1'), (0.5, 'vel'), (0.5, 'step 1'), (0.5, 'vel'), (0.5, 'step 10'), (0.5, 'vel'),
                 (0.5, 'stick 0.5 0.5'), (0.5, 'step 1'), (0.5, 'vel'), (0.5, 'step 1'), (0.5, 'vel'), (0.5, 'step 10'), (0.5, 'vel'),
                 (0.5, 'neutral'), (0.5, 'unfreeze'), (1.0, 'end')],
    # ---- Fishbunjin's specials (Slap City; own_fishbunjin: states 373 on), stepped a frame at a time.
    # Flex: its hit round him on frame 2, the target close; from a jump it stops him dead and he falls
    'fb_neutral': [(0.0, 'bag 9 0'), (0.3, 'closeup 70 12 35 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'shot hit'),
                   (0.5, 'B-'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_neutral_air': [(0.0, 'bag 60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'B+'), (0.5, 'steplog 2'),
                       (0.5, 'B-'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Bunjin Bull: he gathers himself (20 frames), runs (from his dash speed toward twice it), A strikes the target on
    # the way (a slap on the strike's frames 6 to 9); then steered: the stick back turns him; then from a jump, the
    # run in the air and the strike, helpless after it
    'fb_side': [(0.0, 'bag 70 0'), (0.3, 'closeup 120 12 35 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'),
                (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 30'), (0.5, 'shot run'), (0.5, 'steplog 6'), (0.5, 'A+'), (0.5, 'steplog 2'),
                (0.5, 'A-'), (0.5, 'steplog 6'), (0.5, 'shot strike'), (0.5, 'steplog 50'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_side_steer': [(0.0, 'bag -70 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                      (0.5, 'neutral'), (0.5, 'steplog 30'), (0.5, 'stick 0.0 0.5'), (0.5, 'steplog 3'), (0.5, 'neutral'),
                      (0.5, 'steplog 30'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 50'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_side_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'),
                    (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 30'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'),
                    (0.5, 'steplog 90'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Bell Ringer: 8 frames still, then up by the clip's root (hits from frame 9 to 30), a hop on 31, helpless on 41;
    # the side rise with the stick across by frame 9; from a jump
    'fb_up': [(0.0, 'bag 8 0'), (0.3, 'closeup 110 25 35 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
              (0.5, 'neutral'), (0.5, 'steplog 14'), (0.5, 'shot rise'), (0.5, 'steplog 16'), (0.5, 'shot top'), (0.5, 'steplog 100'),
              (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_up_side': [(0.0, 'bag 20 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                   (0.5, 'stick 1.0 0.5'), (0.5, 'steplog 10'), (0.5, 'neutral'), (0.5, 'steplog 20'), (0.5, 'shot side'), (0.5, 'steplog 100'),
                   (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_up_air': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'),
                  (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 150'), (0.5, 'unfreeze'), (1.0, 'end')],
    # Deep Breath: tapped (the weakest wave, 10 at his frame 6 after letting go, 2 units ahead), held 3 seconds (the
    # 3-second wave: 30) and in the air (the punch, frames 17 to 20). The target stands in the wave's reach.
    'fb_down': [(0.0, 'bag 14 0'), (0.3, 'closeup 70 12 35 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'),
                (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 6'), (0.5, 'shot wave'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_down_held': [(0.0, 'bag 14 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'stick 0.5 0.5'),
                     (0.5, 'step 184'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 80'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_down_air': [(0.0, 'bag 10 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'),
                    (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 60'), (0.5, 'unfreeze'), (1.0, 'end')],
    # his normals onto a standing target, a picture on the frame the game's first hit comes out (the driver's table:
    # jab 6, forward smash 36, up smash 20, down smash 32); the smashes' armour is in their rows' `armor`
    'fb_jab': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'steplog 4'), (0.5, 'shot hit'),
               (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_fsmash': [(0.0, 'bag 14 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                  (0.5, 'steplog 34'), (0.5, 'shot hit'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    'fb_usmash': [(0.0, 'bag 6 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                  (0.5, 'steplog 18'), (0.5, 'shot hit'), (0.5, 'steplog 45'), (0.5, 'unfreeze'), (1.0, 'end')],
    # (his down smash is a flop onto his back: its hits, angle 235, come down BEHIND him; the target stands there)
    'fb_dsmash': [(0.0, 'bag -10 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'),
                  (0.5, 'steplog 30'), (0.5, 'shot hit'), (0.5, 'steplog 40'), (0.5, 'unfreeze'), (1.0, 'end')],
    # ---- Zetterburn's specials and his burn (Rivals 2; own_zetterburn: states 373 on), stepped a frame at a time.
    # A burn shows in the stepped rows as the bag's % rising by the tick, every BURN_EVERY frames after the hit that
    # set it alight, with no hit of his: each test steps on long enough (200 frames) to see the whole burn.
    # the fire burst let go at once (the small one), and held through its charge (the big one), beside the target
    'zt_burst_tap': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 220'),
                     (0.5, 'unfreeze'), (1.0, 'end')],
    'zt_burst_held': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 48'), (0.5, 'shot charged'), (0.5, 'B-'),
                      (0.5, 'steplog 220'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the side special: the mane swipe, then the fireball (made on his frame 17) flying into a target out of the
    # swipe's reach; pictures of the fireball as it is made and on its way
    'zt_fireball': [(0.0, 'bag 40 0'), (0.3, 'closeup 70 10 35 0'), (0.5, 'freeze'), (0.5, 'stick 1.0 0.5'), (0.5, 'B+'), (0.5, 'steplog 2'),
                    (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 16'), (0.5, 'shot fly1'), (0.5, 'steplog 4'), (0.5, 'shot fly2'),
                    (0.5, 'steplog 200'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the up special: straight up with the stick let go; aimed ahead; and into a held target (its seven hits)
    'zt_up': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'),
              (0.5, 'steplog 40'), (0.5, 'shot fly'), (0.5, 'steplog 140'), (0.5, 'unfreeze'), (1.0, 'end')],
    'zt_up_aim': [(0.0, 'bag -60 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                  (0.5, 'stick 1.0 0.7'), (0.5, 'steplog 36'), (0.5, 'shot fly'), (0.5, 'neutral'), (0.5, 'steplog 140'), (0.5, 'unfreeze'),
                  (1.0, 'end')],
    'zt_up_hit': [(0.0, 'bag 7 0'), (0.0, 'pin'), (0.5, 'freeze'), (0.5, 'stick 0.5 1.0'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'),
                  (0.5, 'neutral'), (0.5, 'steplog 34'), (0.5, 'unpin'), (0.5, 'steplog 200'), (0.5, 'unfreeze'), (1.0, 'end')],
    # the down special on the ground into a target (the slam); with the target away, then put in the puddle it left
    # (photographed once the slam is over: during it his body hides the puddle)
    'zt_slam': [(0.0, 'bag 12 0'), (0.3, 'closeup 55 10 35 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'),
                (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 24'), (0.5, 'shot slam'), (0.5, 'steplog 200'), (0.5, 'unfreeze'), (1.0, 'end')],
    'zt_puddle': [(0.0, 'bag 80 0'), (0.3, 'closeup 55 10 35 0'), (0.5, 'freeze'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'), (0.5, 'steplog 2'),
                  (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 62'), (0.5, 'shot puddle'), (0.5, 'bag 3 0'), (0.5, 'steplog 200'),
                  (0.5, 'unfreeze'), (1.0, 'end')],
    # the down special from a jump: the hop, the dive and the slam as he lands, beside the target
    'zt_dive': [(0.0, 'bag 20 0'), (0.5, 'freeze'), (0.5, 'X+'), (0.5, 'steplog 14'), (0.5, 'X-'), (0.5, 'stick 0.5 0.0'), (0.5, 'B+'),
                (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'neutral'), (0.5, 'steplog 24'), (0.5, 'shot dive'), (0.5, 'steplog 200'),
                (0.5, 'unfreeze'), (1.0, 'end')],
    # the consume: the small burst sets the target alight, then the forward strong strikes it while it burns
    'zt_consume': [(0.0, 'bag 9 0'), (0.5, 'freeze'), (0.5, 'B+'), (0.5, 'steplog 2'), (0.5, 'B-'), (0.5, 'steplog 34'),
                   (0.5, 'stick 1.0 0.5'), (0.5, 'A+'), (0.5, 'steplog 2'), (0.5, 'A-'), (0.5, 'neutral'), (0.5, 'steplog 160'),
                   (0.5, 'unfreeze'), (1.0, 'end')],
}


# A catalogue of the game's own effects: gfxcat_<first>_<last> jabs once for each number in the range, with the jab's
# own effect command (found in memory by PROBE_GFX_BYTES, the hex of its script up to that command's number) rewritten
# to that number, and photographs it twice.
for _name in wanted:
    if _name.startswith('gfxcat_'):
        _a, _b = (int(v) for v in _name.split('_')[1:3])
        _steps, _t = [(0.0, f"bag {os.environ.get('PROBE_GFX_BAG', '-32 0')}")], 0.4
        if os.environ.get('PROBE_GFX_CAM'):               # the camera parked close for the pictures (as 'closeup')
            _steps.append((0.1, 'closeup ' + os.environ['PROBE_GFX_CAM']))
        for _n in range(_a, _b + 1):
            _steps += [(_t, f'gfx {_n}'), (_t + 0.02, 'A+'), (_t + 0.08, 'A-'), (_t + 0.17, f'shot {_n}a'), (_t + 0.30, f'shot {_n}b')]
            _t += 0.75
        MOVES[_name] = _steps + [(_t + 0.2, 'end')]


# Every choice of every model group in turn, photographed (a face of part swaps: `own_faces`). PROBE_FACE_CHOICES is
# how many choices each group after the first has, PROBE_FACE_REST the choice each rests on.
if 'face_cat' in wanted:
    _steps = [(0.0, 'bag 60 0'), (0.3, 'freeze')]
    for _g, (_k, _rest) in enumerate(zip(os.environ['PROBE_FACE_CHOICES'].split(), os.environ['PROBE_FACE_REST'].split()), 1):
        for _c in range(int(_k)):
            _steps += [(0.3, f'model {_g} {_c}'), (0.3, f'shot g{_g:02d}c{_c}')]
        _steps += [(0.3, f'model {_g} {_rest}')]
    MOVES['face_cat'] = _steps + [(0.3, 'unfreeze'), (0.6, 'end')]
# ... and one picture of several groups set at once (PROBE_FACE_SET: 'group:choice group:choice ...')
if 'face_set' in wanted:
    MOVES['face_set'] = ([(0.0, 'bag 60 0'), (0.3, 'freeze')]
                         + [(0.3, 'model ' + _w.replace(':', ' ')) for _w in os.environ['PROBE_FACE_SET'].split()]
                         + [(0.3, 'shot set'), (0.3, 'step 30'), (0.3, 'shot later'), (0.3, 'unfreeze'), (0.6, 'end')])


def log(m):
    print(m, flush=True)


boot = DolphinBoot(str(iso), None, str(Path(STORAGE_PATH) / 'test-runs'), log=lambda m: None)
p = None


def _overrun():
    # a probe never outlives its deadline: its Dolphin is ended and the run fails loudly (a Dolphin that
    # froze while starting once sat on the owner's screen for seven minutes with this script waiting on it)
    # (the first words are what `round.py` looks for; what follows says where it was, for a reader)
    at_ = globals().get('name')
    left_ = wanted[wanted.index(at_) + 1:] if at_ in wanted else wanted
    print(f'PROBE DEADLINE PASSED after {DEADLINE} s: ending its Dolphin (100 s + 9 a test + 20 a new match + PROBE_EXTRA, '
          f'for {len(wanted)} tests; it was in {at_ or "none yet (the boot, or the first match starting)"}; not begun: '
          f'{" ".join(left_) or "none"})', flush=True)
    try:
        boot.cleanup()
    finally:
        os._exit(3)


def kill_stage_particles(d):
    """The stage's background particles out of the pictures (`fs.kill_stage_particles`), with the GAME FROZEN. The kill
    walks the game's particle lists from outside and unlinks each stage particle, a pointer read and then a pointer
    written, while the particle update (`efLib_particles_proc_main`, a process of the game) changes the same lists
    every frame. Run together they race (G19, 2026-11-13, `app/scratch/g17/hunt5`: the walk slowed to 30 ms a node,
    6 boots each way on the Hydro Pump disc): unfrozen, the walk went round a LOOP in a list until the deadline in 2
    boots and dropped every particle the game made while it walked in 2 more (27 and 64, taken from the pool and on
    no list, the free list emptied); frozen, the pool did not change in any. A particle freed while the walk held it
    is written back onto a live list, and loops that list when the pool hands it out again, in the next move that
    makes many particles; a looping list hangs the game as it draws: the rare stops in Greninja's Hydro Pump (3 in 11,
    under load), Incineroar's Cross Chop, Wolf and Duck Hunt. The freeze stops the update; the render pass only reads
    the lists. The lists are read again while still
    frozen and anything wrong is said (`PARTICLES AFTER THE STAGE KILL`)."""
    held_ = not framestep.is_frozen(d)
    if held_:
        framestep.freeze(d)
        framestep.wait_render_frames(d, 2)              # the logic frame under way when the bit was set is over
    g0_, used_ = d.u32(framestep.FRAME_COUNTER), d.u32(particle_check.PARTICLE_POOL + 8)
    try:
        fs.kill_stage_particles(d)
    except Exception as exc:
        log(f'   the stage particles were not taken out: {exc}')
    ran_ = (d.u32(framestep.FRAME_COUNTER) or 0) - (g0_ or 0)
    mem_ = d.snapshot()
    if held_:
        framestep.unfreeze(d)
    bad_ = particle_check.faults(mem_)
    now_ = particle_check.read(mem_)['used']            # (from the frozen snapshot: running, the pool moves)
    if ran_:
        bad_.append(f'{ran_} game frames ran during it (the freeze did not hold)')
    if now_ != used_ and not ran_:
        bad_.append(f'particles in use went {used_} -> {now_}')
    if bad_:
        log('   PARTICLES AFTER THE STAGE KILL: ' + '; '.join(bad_) + f' ({particle_check.summary(mem_)})')


import threading  # noqa: E402
DEADLINE = (100 + 9 * len(wanted) + 20 * sum(1 for n_ in wanted if n_.startswith('match_'))
            + int(os.environ.get('PROBE_EXTRA', '0')))     # PROBE_EXTRA: seconds more, for long moves
_watch = threading.Timer(DEADLINE, _overrun)
_watch.daemon = True
_watch.start()
try:
    boot.prepare()
    AUDIO = os.environ.get('PROBE_AUDIO')
    if AUDIO:
        # Dolphin writes what the game's sound chip puts out to User/Dump/Audio/dspdump.wav as it runs
        from shared.ingame import boot as boot_module
        boot_module._write_ini(os.path.join(str(boot.user_dir), 'Config', 'Dolphin.ini'),
                               lambda upsert, _replace: (upsert('DSP', 'DumpAudio', 'True'), upsert('DSP', 'DumpAudioSilent', 'True')))
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
    match_setup.write_bag_player(d, CKIND, int(os.environ.get('PROBE_COLOR', '0')), bag_ckind=BAG, bag_color=0)
    match_setup.warp_to_stage_select(d)
    sc = StageCursor(d, p)
    if not sc.wait_for_stage_select(timeout=8.0):
        raise SystemExit('CSS->SSS warp did not land')
    match_setup.write_bag_player(d, CKIND, int(os.environ.get('PROBE_COLOR', '0')), bag_ckind=BAG, bag_color=0)
    if not sc.force_select(INTERNAL_STAGE_ID['finaldestination']):
        raise SystemExit('match never started')
    wait_in_game(d, timeout=25.0)
    wait_game_frames(d, 200)
    if not os.environ.get('PROBE_MIRROR'):              # left alone, the second fighter reads the same pad: it does what the first does
        match_setup.fix_player_pad_indices(d, [0, 1], log=lambda m: None)
    me, bag = Player(d, 0), Bag(d, port=1)
    me.resolve()
    if not bag.resolve():
        raise SystemExit('the bag never spawned')
    def room_():
        """What is left of the game's memory as a test starts: the object heap's own count (objalloc.c `obj_heap`), and
        the free runs of the heap its objects come from (OSAlloc.c: `HeapArray`, the handle in `current_heap`)."""
        out = [f"object heap {d.u32(0x80406E54) or 0:,} left" if d.u32(0x80406E48) else 'no object heap']
        array_, handle_ = d.u32(0x804D7360) or 0, d.u32(0x804D5E00)
        if array_ and handle_ is not None and handle_ < 32:
            cell_, total_, big_, runs_ = d.u32(array_ + 12 * handle_ + 4) or 0, 0, 0, 0
            while cell_ and runs_ < 20000:
                size_ = d.u32(cell_ + 8) or 0
                total_, big_, runs_ = total_ + size_, max(big_, size_), runs_ + 1
                cell_ = d.u32(cell_ + 4) or 0
            out.append(f'heap {handle_}: {total_:,} free in {runs_} runs, the largest {big_:,}')
        return '; '.join(out)

    def item():
        lists = d.u32(0x804D782C)                      # the game's lists of objects; the ninth is the items
        g = d.u32(lists + 9 * 4) if lists else 0
        data = d.u32(g + 0x2C) if g else 0
        if not data:
            return None
        return (d.u32(data + 0x24), round(d.f32(data + 0x4C), 1), round(d.f32(data + 0x40), 2), round(d.f32(data + 0xD44)))

    fs.assert_plain_bg(d, BG)
    kill_stage_particles(d)
    TAG = ''
    for name in wanted:
        if name.startswith('match_'):
            # A NEW MATCH IN THE SAME BOOT: match_<costume>[_<second fighter, hex>[_<stage>]]. The game is quit back to
            # the character screen (no new Dolphin), the players are written again and the stage chosen in memory:
            # about six seconds. It is how one boot photographs every costume, changes the fighter beside the port or
            # the stage, and gives a test a match nothing has been left in. Pictures taken after it carry -c<costume>.
            bits_ = name.split('_')[1:]
            color_, bag_ = int(bits_[0]), (int(bits_[1], 16) if len(bits_) > 1 else BAG)
            stage_ = bits_[2] if len(bits_) > 2 else 'finaldestination'
            t_ = time.time()
            p.neutral()
            # a test may have left the game frozen for its pictures (a portrait does): the freeze is let go before the
            # match is quit. Quit while frozen, the freeze is carried into the matches after, and some tests later a
            # frame step stops taking and the game does not run again (found in the first two rounds).
            framestep.unfreeze(d)
            time.sleep(0.15)
            globals().pop('closeup_', None)                # ... and the camera a test parked is not the next match's
            for try_ in range(3):
                # (the quit is a pause and then four buttons at once: a press the game misses leaves the match
                # running or paused, and the same presses again put that right)
                if nav.reset_to_css(d, p, log=lambda m: None):
                    break
                g0_ = d.u32(0x80479D60)
                time.sleep(0.5)
                print(f'{name}: the quit to the character screen did not take (try {try_ + 1}); the game '
                      f'{"runs" if d.u32(0x80479D60) != g0_ else "is paused or stopped"}', flush=True)
                p.neutral()
                time.sleep(0.3)
            else:
                raise SystemExit(f'{name}: never got back to the character screen')
            match_setup.write_bag_player(d, CKIND, color_, bag_ckind=bag_, bag_color=0)
            match_setup.warp_to_stage_select(d)
            sc = StageCursor(d, p)
            if not sc.wait_for_stage_select(timeout=8.0):
                raise SystemExit(f'{name}: CSS->SSS warp did not land')
            match_setup.write_bag_player(d, CKIND, color_, bag_ckind=bag_, bag_color=0)
            if not sc.force_select(INTERNAL_STAGE_ID[stage_]):
                raise SystemExit(f'{name}: match never started')
            wait_in_game(d, timeout=25.0)
            wait_game_frames(d, 200)
            if not os.environ.get('PROBE_MIRROR'):
                match_setup.fix_player_pad_indices(d, [0, 1], log=lambda m: None)
            me, bag = Player(d, 0), Bag(d, port=1)
            me.resolve()
            if not bag.resolve():
                raise SystemExit(f'{name}: the bag never spawned')
            fs.assert_plain_bg(d, BG)
            kill_stage_particles(d)
            # (the stage and the second fighter in the name when they are not the usual: the room's three matches)
            TAG = f'-c{color_}' + ('' if stage_ == 'finaldestination' else f'-{stage_}') + ('' if bag_ == BAG else f'-with{bag_:x}')
            print(f'{name}: a new match in the same boot (costume {color_}, second fighter {bag_:#x}, {stage_}) in {time.time() - t_:.1f} s', flush=True)
            continue
        if bag.state() in (252, 253):
            # the second fighter is hanging from a ledge (it would stay hung wherever it is put): it is given the pad
            # for a moment, with the stick down, to let go
            for port_, pad_ in ((0, 1), (1, 0)):
                base_ = match_setup.PLAYER_BLOCK + match_setup.PLAYER_BLOCK_STRIDE * port_
                d.write_u8(base_ + match_setup.STATIC_PLAYER_ID, pad_)
                f_ = d.u32(d.u32(base_ + 0xB0) + 0x2C) if d.u32(base_ + 0xB0) else 0
                if f_:
                    d.write_u8(f_ + match_setup.FT_X618_PLAYER_ID, pad_)
            p.main(0.5, 0.0)
            time.sleep(0.25)
            p.neutral()
            time.sleep(0.1)
            match_setup.fix_player_pad_indices(d, [0, 1], log=lambda m: None)
        me.resolve()                                    # (a fighter of forms may have switched in the test before)
        me.set_pos(-40.0, 20.0)
        bag.set_pos(60.0, 20.0)
        me.set_percent(0)
        bag.set_percent(0)
        p.neutral()
        time.sleep(1.6)
        p.main(1.0, 0.5)                                # face right
        time.sleep(0.05)
        p.neutral()
        time.sleep(0.9)
        print(f'{name}: room: {room_()}', flush=True)
        steps = sorted(MOVES[name], key=lambda s: s[0])
        if os.environ.get('PROBE_CLOSEUP'):                # the camera parked close for every picture of the run
            w_ = [float(v) for v in os.environ['PROBE_CLOSEUP'].split()]
            globals()['closeup_'] = dict(dist=w_[0], height=w_[1], fov=w_[2] if len(w_) > 2 else 35.0, yaw=w_[3] if len(w_) > 3 else None)
        if AUDIO:
            dump_ = Path(str(boot.user_dir)) / 'Dump' / 'Audio' / 'dspdump.wav'
            log(f'{name}: sound file at {dump_.stat().st_size if dump_.exists() else 0} bytes as it starts')
        x0, y0 = me.pos()
        seen, top, far, t0, pinned, hits, last_pct, bag_seen = [], 0.0, 0.0, time.time(), None, [], 0.0, []
        shots, flags, track, bag_times = [], [], [], []
        hitlog = []
        stepped = []
        itemlog = []
        tint = None
        while steps:
            now = time.time() - t0
            while steps and steps[0][0] <= now:
                _, action = steps.pop(0)
                if action == 'end':
                    continue
                if action == 'fill':
                    me.set_percent(150)
                    time.sleep(0.12)
                    me.set_percent(0)
                elif action == 'hud':
                    print('hud places', [[round(d.f32(0x804A0FD8 + 0x18 + 12 * i + 4 * k), 2) for k in range(3)] for i in range(6)], flush=True)
                elif action.startswith('gauge'):
                    if 'gauge_addr' not in globals():
                        at = d.snapshot().find(bytes.fromhex('46f4d280'))
                        globals()['gauge_addr'] = 0x80000000 + at if at >= 0 else None
                        print('gauge numbers at', hex(gauge_addr) if gauge_addr else None, flush=True)
                    if gauge_addr:
                        for k, v in enumerate(action.split()[1:6]):
                            d.write_f32(gauge_addr + 4 + 4 * k, float(v))
                elif action.startswith('lift'):
                    x_, y_ = me.pos()
                    me.set_pos(x_, y_ + float(action.split()[1]))
                elif action == 'freeze':
                    framestep.freeze(d)
                elif action == 'unfreeze':
                    framestep.unfreeze(d)
                elif action.startswith('step '):
                    framestep.step(d, int(action.split()[1]))
                elif action.startswith('pads'):
                    # which pad each fighter reads: 'pads 0 1' is each its own (the second has none), 'pads 1 0' gives
                    # the pipe to the second fighter and leaves the first with nothing held
                    for port_, pad_ in enumerate(int(v) for v in action.split()[1:3]):
                        base_ = match_setup.PLAYER_BLOCK + match_setup.PLAYER_BLOCK_STRIDE * port_
                        d.write_u8(base_ + match_setup.STATIC_PLAYER_ID, pad_)
                        g_ = d.u32(base_ + 0xB0)
                        f_ = d.u32(g_ + 0x2C) if g_ else 0
                        if f_:
                            d.write_u8(f_ + match_setup.FT_X618_PLAYER_ID, pad_)
                elif action.startswith('steplog'):
                    # frames stepped one at a time; a line for each: (frames in, state, clip frame, my %, x, y, bag state, bag %)
                    for _ in range(int(action.split()[1])):
                        if framestep.step(d, 1) < 1:
                            # The step did not take within its second. It can be three things, and they are told apart here: the
                            # machine was busy (a second try with more time takes: go on), the stepping is stuck while the game is
                            # alive (let go of the freeze and the game runs on: this test is void, the next can run), or the game
                            # has stopped (nothing after it can be believed: the boot ends here).
                            snap_ = framestep.snapshot(d)
                            if framestep.step(d, 1, timeout_per=6.0) >= 1:
                                log(f'   a step took more than a second at step {len(stepped) + 1} (a busy machine): went on; {snap_}')
                            else:
                                # the game did not take the step (it has stopped): where each fighter's script stands,
                                # read three times, and no more steps are asked of it
                                for who_, f_ in (('fighter', me), ('second fighter', bag)):
                                    t_ = f_._ft()
                                    at_ = [d.u32(t_ + 0x3EC) for _k in range(3) if not time.sleep(0.03)]
                                    log(f'   A STEP DID NOT TAKE at step {len(stepped) + 1}: {who_} in state {d.u32(t_ + 0x10)}, action '
                                        f'{d.u32(t_ + 0x14)}, clip frame {d.f32(t_ + 0x894):.1f}; its script waits {d.f32(t_ + 0x3E4):.1f}, '
                                        f'frame {d.f32(t_ + 0x3E8):.1f}, at {[hex(v_) for v_ in at_]}, '
                                        + (f'command {d.u32(at_[0]):#010x} {d.u32(at_[0] + 4):#010x}' if at_[0] else 'its end'))
                                # ... and what the game was in the middle of: the return addresses on its stack (the longest
                                # chain of frames under the arena), read twice a moment apart
                                for _k in range(2):
                                    words_ = {a_: d.u32(a_) or 0 for a_ in range(0x804EC000, 0x804EEC00, 4)}
                                    best_ = []
                                    for a_ in words_:
                                        chain_, at2_ = [], a_
                                        while at2_ in words_ and at2_ < words_[at2_] < 0x804EEC00 and len(chain_) < 60:
                                            chain_.append(words_.get(at2_ + 4, 0))
                                            at2_ = words_[at2_]
                                        if len(chain_) > len(best_):
                                            best_ = chain_
                                    log('   its stack, innermost first: ' + ' '.join(f'{v_:08x}' for v_ in best_[:28]))
                                    time.sleep(0.2)
                                # ... and the game's particles (a loop in a list of them hangs it as it draws: particleSort)
                                mem_ = d.snapshot()
                                log('   its particles: ' + particle_check.summary(mem_))
                                for line_ in particle_check.faults(mem_) or ['nothing wrong with them']:
                                    log('   PARTICLES: ' + line_)
                                for line_ in particle_check.listing(mem_):
                                    log('   PARTICLE LIST: ' + line_)
                                if globals().get('particle_last_'):
                                    # what changed since the step before (PROBE_PARTICLES): the write that closed the loop
                                    for line_ in particle_check.changes(globals()['particle_last_'],
                                                                         particle_check.state(mem_)) or ['nothing']:
                                        log('   PARTICLES SINCE THE LAST STEP: ' + line_)
                                    for line_ in particle_check.listing(globals()['particle_last_'], link=0):
                                        log('   PARTICLE LIST AT THE LAST STEP: ' + line_)
                                framestep.unfreeze(d)
                                g0_ = d.u32(0x80479D60)                         # the count of game frames
                                time.sleep(0.6)
                                if d.u32(0x80479D60) != g0_:
                                    log(f'   THE STEPPING STUCK, NOT THE GAME, in {name}: let go, the game runs on ({snap_}); this test is void')
                                    break
                                raise SystemExit(f'THE GAME STOPPED in {name}: it does not run when let go ({snap_})')
                        if pinned:
                            bag.pin()
                        x_, y_ = me.pos()
                        ft_ = me._ft()
                        row_ = (me.state(), round(me.anim_frame() or 0), round(me.percent() or 0.0, 1), round(x_ - x0, 1), round(y_ - y0, 1),
                                bag.state(), round(bag.percent() or 0.0, 1), round(bag.pos()[0] - x0, 1), round(d.f32(ft_ + 0x18B4), 1))
                        stepped.append(row_)
                        if os.environ.get('PROBE_PARTICLES'):
                            # the game's particles after each step: a line when what is wrong with them changes, and
                            # their counts each step it is wrong (particle_check)
                            mem_ = d.snapshot()
                            bad_ = particle_check.faults(mem_)
                            if bad_ != globals().get('particle_bad_'):
                                log(f'   particles at step {len(stepped)} ({row_[:2]}): {particle_check.summary(mem_)}')
                                for line_ in bad_ or ['nothing wrong with them']:
                                    log('   PARTICLES: ' + line_)
                                globals()['particle_bad_'] = bad_
                            globals()['particle_last_'] = particle_check.state(mem_)
                        if os.environ.get('PROBE_ITEMS'):
                            # every item in the match at this step: (kind, state, x, y from where he stood, its speed
                            # sideways), down the game's item list (each item's object: the next at +0x08, its data +0x2C)
                            g_, items_ = d.u32(d.u32(0x804D782C) + 9 * 4), []
                            while g_ and len(items_) < 16:
                                i_ = d.u32(g_ + 0x2C)
                                if i_:
                                    items_.append((d.u32(i_ + 0x10), d.u32(i_ + 0x24), round(d.f32(i_ + 0x4C) - x0, 1),
                                                   round(d.f32(i_ + 0x50) - y0, 1), round(d.f32(i_ + 0x40), 2)))
                                g_ = d.u32(g_ + 0x08)
                            if not itemlog or itemlog[-1][1] != tuple(items_):
                                itemlog.append((len(stepped), tuple(items_)))
                        span_ = os.environ.get('PROBE_STEPSHOT')    # 'first-last': a picture at each step whose clip frame is in it
                        if span_ and int(span_.split('-')[0]) <= row_[1] <= int(span_.split('-')[1]):
                            if globals().get('closeup_'):
                                fs.closeup_camera(d, me, **closeup_)
                            fs.assert_plain_bg(d, BG)
                            time.sleep(0.08)
                            fs.capture(boot, OUT / f"{name}-s{len(stepped):03d}-c{row_[1]:03d}.png")
                        if os.environ.get('PROBE_FACESHOT'):
                            # the choice of each of the fighter's model groups (fp+0x5F4: default, current; a pair a group)
                            face_ = tuple(d.u8(ft_ + 0x5F4 + 2 * g_ + 1) for g_ in range(11))
                            face_ = tuple(v_ - 256 if v_ > 127 else v_ for v_ in face_)
                            if face_ != globals().get('face_was_'):
                                globals()['face_was_'] = face_
                                log(f'     face at step {len(stepped)} (state {row_[0]}, clip frame {row_[1]}): {face_}')
                                if globals().get('closeup_'):
                                    fs.closeup_camera(d, me, **closeup_)
                                fs.assert_plain_bg(d, BG)
                                time.sleep(0.08)
                                fs.capture(boot, OUT / f"{name}-f{len(stepped):03d}-{'_'.join(str(v_) for v_ in face_[1:])}.png")
                        if os.environ.get('PROBE_BOXES'):
                            # the fighter's live hitboxes (damage, x, y, radius) and where the bag is, a frame at a time
                            boxes_ = [(d.u32(ft_ + 0x914 + 0x138 * i_ + 0x0C), round(d.f32(ft_ + 0x914 + 0x138 * i_ + 0x4C) - x0, 1),
                                       round(d.f32(ft_ + 0x914 + 0x138 * i_ + 0x50) - y0, 1), round(d.f32(ft_ + 0x914 + 0x138 * i_ + 0x1C), 1))
                                      for i_ in range(4) if d.u32(ft_ + 0x914 + 0x138 * i_)]
                            if boxes_:
                                bx_, by_ = bag.pos()
                                log(f'     boxes at {len(stepped)} (clip frame {row_[1]}): {boxes_}; bag at x {bx_ - x0:+.1f}, y {by_ - y0:+.1f}, state {bag.state()}')
                        top, far = max(top, y_ - y0), (x_ - x0 if abs(x_ - x0) > abs(far) else far)
                elif action.startswith('gfx '):
                    if 'gfx_addr' not in globals():
                        pattern_ = bytes.fromhex(os.environ['PROBE_GFX_BYTES'])
                        at_ = d.snapshot().find(pattern_)
                        globals()['gfx_addr'] = 0x80000000 + at_ + len(pattern_) if at_ >= 0 else None
                        log(f'   effect number at {hex(gfx_addr) if gfx_addr else None}')
                    if gfx_addr:
                        d.write_u8(gfx_addr, int(action.split()[1]) >> 8)
                        d.write_u8(gfx_addr + 1, int(action.split()[1]) & 0xFF)
                elif action.startswith('perf'):
                    # the game's own clock for a frame (HSD_PerfLastStat): its logic, its logic and drawing, all of it,
                    # each as a share of a sixtieth of a second; the matrices it loaded and its blends by joint count
                    rows_ = []
                    for _ in range(40):
                        rows_.append([d.f32(0x80407188 + 4 * k_) for k_ in range(3)] + [d.u32(0x80407188 + 12)])
                        time.sleep(0.02)
                    mean_ = [sum(r_[k_] for r_ in rows_) / len(rows_) for k_ in range(4)]
                    blend_ = [d.u32(0x80407188 + 16 + 4 * k_) for k_ in range(8)]
                    log(f"   a frame's time, {action[5:] or 'now'} (state {me.state()}): logic {mean_[0]:.2f}, drawing {mean_[1] - mean_[0]:.2f}, "
                        f"all {mean_[2]:.2f} of a sixtieth (most {max(r_[2] for r_ in rows_):.2f}); matrices loaded {mean_[3]:.0f}; "
                        f"blends by joints {blend_}")
                elif action.startswith('closeup'):
                    # the camera parked close on the fighter for the pictures that follow: distance, height, lens, angle round
                    w_ = [float(v) for v in action.split()[1:]]
                    globals()['closeup_'] = dict(dist=w_[0], height=w_[1], fov=w_[2] if len(w_) > 2 else 35.0, yaw=w_[3] if len(w_) > 3 else None)
                elif action.startswith('percent'):
                    me.set_percent(int(action.split()[1]))
                elif action.startswith('model '):
                    # a model group's current choice written straight into the fighter (fp+0x5F4: default, current; a
                    # pair a group), then two frames stepped: the game shows it from its next frame
                    g_, c_ = (int(v) for v in action.split()[1:3])
                    d.write_u8(me._ft() + 0x5F4 + 2 * g_ + 1, c_ & 0xFF)
                    if framestep.step(d, 2) < 2:
                        log(f'   THE GAME STOPPED with group {g_} on choice {c_}')
                elif action == 'metal':
                    # the fighter's "always metal" bit (fp+0x2223, the bit before the last): metal from its next spawn
                    d.write_u8(me._ft() + 0x2223, d.u8(me._ft() + 0x2223) | 0x02)
                elif action == 'room':
                    # the memory left now (as each test starts: `room_`), e.g. before and after a form is made mid-match
                    log(f'   room at {now:.2f} s: {room_()}')
                elif action == 'who':
                    # a fighter of forms: who holds the player's place now (the handle is walked again: a switch moves
                    # the player to another fighter), with what the switch must have carried across
                    me.resolve()
                    slot_ = match_setup.PLAYER_BLOCK
                    log(f'   who at {now:.2f} s: kind {me.kind()}, places {d.u8(slot_ + 0x0C)}/{d.u8(slot_ + 0x0D)}, '
                        f'fighters {d.u32(slot_ + 0xB0):#x}/{d.u32(slot_ + 0xB4):#x}, state {me.state()}, '
                        f'facing {me.facing():+.0f}, at {tuple(round(v, 1) for v in me.pos())}, {me.percent():.0f}%, '
                        f'in the air {me.airborne()}, kept aside {d.u32(me._ft() + 0x22F0):#x}, '
                        f'switch clock {d.u32(me._ft() + 0x22F4)}')    # forms.PARKED, forms.CLOCK
                elif action == 'vel':
                    ft_ = me._ft()
                    log(f'   speed at {now:.2f} s: x {d.f32(ft_ + 0x80):+.3f}, y {d.f32(ft_ + 0x84):+.3f}, along the ground {d.f32(ft_ + 0xEC):+.3f}, state {me.state()}')
                elif action == 'trail':
                    # the sword trail as the game holds it (ftafterimage.c ftCo_800C2FD8): how many points it has
                    # (-1: off), the span along its joint it is drawn over (the description's two offsets, copied
                    # each frame it is on: 0 to 0 if no description was ever read), and the newest point with its
                    # joint's x axis there (the axis's length is the joint's drawn scale)
                    ft_ = me._ft()
                    count = d.u8(ft_ + 0x2100)
                    newest = ft_ + 0x20B0 + 24 * (((d.u8(ft_ + 0x2101) >> 1) - 1) % 3)
                    at_ = [d.f32(newest + 4 * i) for i in range(3)]
                    way = [d.f32(newest + 12 + 4 * i) for i in range(3)]
                    log(f'   trail at {now:.2f} s: points {count - 256 if count > 127 else count}, span '
                        f'{d.f32(ft_ + 0x20F8):.3f} to {d.f32(ft_ + 0x20FC):.3f}, newest at {tuple(round(v, 1) for v in at_)} '
                        f'along {tuple(round(v, 3) for v in way)} (length {sum(v * v for v in way) ** 0.5:.3f}), '
                        f'he is at {tuple(round(v, 1) for v in me.pos())}')
                elif action.startswith('place'):
                    me.set_pos(float(action.split()[1]), float(action.split()[2]))
                elif action == 'attrs':
                    # the fighter's own numbers as the game holds them now: walk, friction, dash, run, the squat, gravity,
                    # fall, steering in the air (the part the stick multiplies, the flat part), air speed, air friction
                    ft_ = me._ft()
                    log(f'   numbers at {now:.2f} s: ' + ', '.join(f'{n} {d.f32(ft_ + o):.4f}' for n, o in (
                        ('walk', 0x118), ('friction', 0x128), ('dash', 0x12C), ('run', 0x138), ('squat', 0x148), ('gravity', 0x16C),
                        ('fall', 0x170), ('drift x stick', 0x174), ('drift flat', 0x178), ('air speed', 0x17C), ('air friction', 0x180))))
                elif action.startswith('bagpercent'):
                    bag.set_percent(int(action.split()[1]))
                elif action.startswith('bagface'):
                    # the bag turned where it stands, as 'face' turns the fighter (1 right, -1 left): a hit from
                    # behind (Shulk's Back Slash) needs a bag with its back to him
                    d.write_f32(bag._ft() + 0x2C, float(action.split()[1]))
                elif action.startswith('bag'):
                    _, dx, dy = action.split()
                    bag.park_in_front(me, dx=float(dx), dy=float(dy))
                    pinned_at = (bag._pin_x, bag._pin_y)
                elif action == 'pin':
                    pinned = True
                elif action == 'unpin':
                    pinned = None
                elif action.startswith('shot'):
                    if globals().get('closeup_'):
                        fs.closeup_camera(d, me, **closeup_)
                        time.sleep(0.1)
                    fs.assert_plain_bg(d, BG)
                    time.sleep(0.02)
                    fs.capture(boot, OUT / f"{name}{TAG}-{action.split()[1]}.png")
                elif action.startswith('tint'):
                    w = action.split()
                    tint = ([int(v) for v in w[1:5]], w[5])
                elif action == 'untint':
                    tint = None
                    d.write_u8(me._ft() + 0x488 + 0x7C, d.u8(me._ft() + 0x488 + 0x7C) & 0x7F)
                elif action == 'turn':
                    p.main(0.0, 0.5)
                    time.sleep(0.05)
                    p.neutral()
                elif action.startswith('face '):
                    # turned where he stands by the game's own facing (fighter data 0x2C: 1 right, -1 left): no dash,
                    # no turn state, so a press right after it (or into a frozen game) is taken
                    d.write_f32(me._ft() + 0x2C, float(action.split()[1]))
                elif action == 'neutral':
                    p.neutral()
                elif action.startswith('stick'):
                    _, sx, sy = action.split()
                    p.main(float(sx), float(sy))
                elif action.endswith('+'):
                    p.press(action[:-1])
                elif action.endswith('-'):
                    p.release(action[:-1])
            if pinned:
                bag.pin()
            if tint:
                o = me._ft() + 0x488
                d.write_bytes(o + 0x2C, bytes(tint[0]))
                if tint[1] == 'all':
                    for i, v in enumerate(tint[0]):
                        d.write_f32(o + 0x30 + 4 * i, float(v))
                        d.write_f32(o + 0x40 + 4 * i, 0.0)
                d.write_u8(o + 0x7C, d.u8(o + 0x7C) | 0x80)
            s = me.state()
            x, y = me.pos()
            top, far = max(top, y - y0), (x - x0 if abs(x - x0) > abs(far) else far)
            if not seen or seen[-1][0] != s:
                seen.append([s, round(now, 2)])
            pct = bag.percent() or 0.0
            if pct > last_pct + 0.01:
                hits.append((round(now, 2), round(pct - last_pct, 1)))
                last_pct = pct
            if os.environ.get('PROBE_HITS'):
                # the fighter's four hitboxes as the game holds them: (on, damage, x, y) relative to where it stood
                ft = me._ft()
                row = tuple((d.u32(ft + 0x914 + 0x138 * i), d.u32(ft + 0x914 + 0x138 * i + 0x0C),
                             round(d.f32(ft + 0x914 + 0x138 * i + 0x4C) - x0, 1), round(d.f32(ft + 0x914 + 0x138 * i + 0x50) - y0, 1),
                             round(d.f32(ft + 0x914 + 0x138 * i + 0x54), 1), round(d.f32(ft + 0x914 + 0x138 * i + 0x1C), 1),
                             # its damage, angle, growth and base as the game holds them now
                             (d.u32(ft + 0x914 + 0x138 * i + 0x08), d.u32(ft + 0x914 + 0x138 * i + 0x20),
                              d.u32(ft + 0x914 + 0x138 * i + 0x24), d.u32(ft + 0x914 + 0x138 * i + 0x2C)))
                            if d.u32(ft + 0x914 + 0x138 * i) else None for i in range(4))
                if any(row) and (not hitlog or hitlog[-1][2] != row):
                    bx_, by_ = bag.pos()
                    hitlog.append((round(now, 2), (round(x - x0, 1), round(y - y0, 1), round(bx_ - x0, 1), round(by_ - y0, 1)), row))
            if os.environ.get('PROBE_FLAGS'):
                ft = me._ft()
                now_flags = tuple(d.u32(ft + 0x2200 + 4 * i) for i in range(4)) + (round(me.anim_frame()),)
                if not flags or flags[-1][1:5] != now_flags[:4]:
                    flags.append((round(now, 2),) + now_flags)
            if os.environ.get('PROBE_TRACK') and (not track or now - track[-1][0] >= 0.03):
                lists = d.u32(0x804D782C)
                g = d.u32(lists + 9 * 4) if lists else 0
                data = d.u32(g + 0x2C) if g else 0
                bxy = bag.pos()
                track.append((round(now, 2), round(bxy[0] - x0, 1), round(bxy[1] - y0, 1), bag.state(),
                              (round(d.f32(data + 0x4C) - x0, 1), round(d.f32(data + 0x50) - y0, 1), d.u32(data + 0x24)) if data else None))
            it = item()
            if it and (not shots or shots[-1][1] != it[0] or shots[-1][3] != it[2]):
                shots.append((round(now, 2),) + it)
            elif not it and shots and shots[-1][1] is not None:
                shots.append((round(now, 2), None, None, None, None))
            bs = bag.state()
            if not bag_seen or bag_seen[-1] != bs:
                bag_seen.append(bs)
                bag_times.append((bs, round(now, 2)))
            time.sleep(0.004)
        p.neutral()
        for b in 'ABR':
            p.release(b)
        bx, by = bag.pos()
        log(f"{name}: states (number, seconds in) {seen}; rose {top:+.1f}; went {far:+.1f}; faces {me.facing():+.0f}; "
            f"bag took {last_pct:.1f}% in hits (seconds, %) {hits}; bag ended {bx - x0:+.1f}, {by - y0:+.1f}; "
            f"bag states (with seconds) {[(b, None) for b in bag_seen[:14]] if not bag_times else bag_times[:14]}" + (f"; track (seconds, bag x, bag y, bag state, shot x y state) {[t for t in track if t[4]]}" if track else '') + (f"; script flags (seconds, 0, 1, 2, 3, clip frame) {flags[:30]}" if flags else '') + (f"; shot (seconds, state, x, speed, life) {shots[:10]}" if shots else ''))
        if stepped:
            log('   stepped (frame, state, clip frame, my %, x, y, bag state, bag %, bag x, my armour) where something changed:')
            last_ = None
            for i_, r_ in enumerate(stepped):
                key_ = (r_[0], r_[2], r_[5], r_[6], r_[8])
                if key_ != last_ or i_ == len(stepped) - 1:
                    log(f'     {i_ + 1}: {r_}')
                last_ = key_
            log(f'   started at x {x0:+.1f}, y {y0:+.1f}; bag faces {bag.facing():+.0f}')
            runs_ = []
            for r_ in stepped:
                if runs_ and runs_[-1][0] == r_[0]:
                    runs_[-1][1] += 1
                else:
                    runs_.append([r_[0], 1])
            log('   frames in each state, in order: ' + ' '.join(f'{a}x{b}' for a, b in runs_))
            log(f'   height at the first stepped frame {stepped[0][4]:+.1f}, lowest {min(r_[4] for r_ in stepped):+.1f}, highest {max(r_[4] for r_ in stepped):+.1f}')
            log(f'   went {stepped[-1][3] - stepped[0][3]:+.1f} over the stepped frames (from x {x0 + stepped[0][3]:+.1f}); furthest {max(abs(r_[3]) for r_ in stepped):.1f}; highest {max(r_[4] for r_ in stepped):+.1f}')
        if itemlog:
            log('   items at each step where one changed (step: (kind, state, x, y, speed sideways) ...):')
            for n_, items_ in itemlog[:400]:
                log(f'     {n_}: {items_}')
        for h_ in hitlog[:40]:
            log(f'   hitboxes at {h_[0]} s, fighter x y and bag x y {h_[1]}: {h_[2]}')
        time.sleep(1.0)
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
