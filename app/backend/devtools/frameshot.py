"""
frameshot.py -- frame-exact move screenshots: "screenshot marth fair frame 4".

Boots an ISO with the solo in-game engine (backend/shared/ingame: no CPU, no CSS
cursor), freezes the game with the retail debug-pause bits (framestep.py),
executes the requested move via single-frame TAS stepping (moves.py), then
steps to each requested frame and PrintWindow-captures it. Frame numbers use
community frame-data convention: frame 1 = the first frame whose action state
is the move's state.

Run from backend/ with plain python:

  python devtools/frameshot.py --move fair --frame 4                      # marth on FD
  python devtools/frameshot.py --char falco --move dair --frames 1-8
  python devtools/frameshot.py --char 0x1A --move sideb --frames 1,5,9 --iso <built.iso>

Many moves in ONE boot (the fighter settles back to idle and re-centers
between moves -- use this for per-character sweeps like the extras audit):

  python devtools/frameshot.py --char marth --shot fair:1-8 --shot fsmash:10 --shot jab:3

Many CHARACTERS/COSTUMES in ONE boot -- the throughput lever for costume
sweeps (a boot costs ~90s; a target costs ~15s, measured 2026-07-30):

  python devtools/frameshot.py --batch targets.json --closeup --plain-bg 404040

  targets.json:
    {"shots": ["idle", "jab:1"],
     "targets": [{"id": "machoke", "char": "falcon", "color": 5},
                 {"id": "hypno",   "char": "drmario", "color": 5,
                  "shots": ["idle", "fair:2"]}]}

  (a bare JSON list of targets works too, as does the "char:color" shorthand
  string form). Between targets we quit the match back to the CSS
  (shared/ingame/nav.reset_to_css), memory-select the next fighter and warp straight
  back to the stage -- the same loop shared/ingame/capture.py uses for DAS stage
  variants and zs_mismatch_probe.py uses for costumes.

With `--closeup --plain-bg` the camera is re-parked on the fighter before EVERY
capture (never once per move) and the result is MEASURED: a MODEL clipped by the
frame edge is re-shot from further back, and a model that is not drawn at all is
reported instead of written out as a HUD-only picture. The measurement is made
with the particles unlinked, because otherwise it is a picture of the dust trail
that gets fitted; the framing is never re-aimed, so a port and its control keep
the same gameplay root on the same pixel. `--no-autofit` turns the re-framing
off. See "THE SHOT NOTES" and autofit_capture() below.

Outputs <char>-<move>-f<NN>.png + a .json sidecar per move (state name, anim
frame, position per capture) into --out (default app/scratch/frameshot/).
In batch mode each target gets its OWN subdirectory under --out plus a
machine-readable `batch.json` manifest -- READ THAT instead of globbing: a
per-target status of "ok" is the only thing that means the shots are real.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from core.config import STORAGE_PATH, PROJECT_ROOT  # noqa: E402

from shared.ingame.boot import DolphinBoot, _write_ini  # noqa: E402
from shared.ingame.melee_mem import Dolphin  # noqa: E402
from shared.ingame.melee_css import Cursor  # noqa: E402
from shared.ingame.melee_sss import StageCursor, INTERNAL_STAGE_ID  # noqa: E402
from shared.ingame.observe import Observer, wait_in_game, wait_game_frames  # noqa: E402
from shared.ingame import nav, match_setup, framestep, observe  # noqa: E402
from shared.ingame import control_cache  # noqa: E402
from shared.ingame import screenshot as shot  # noqa: E402
from shared.ingame.char_select import ckind as resolve_ckind  # noqa: E402
from shared.ingame.moves import MoveRunner, MoveError, MOVES, park_bag  # noqa: E402
from shared.ingame.gamestate import Bag, nana_of  # noqa: E402
from shared.ingame.gamestate import (  # noqa: E402
    STATIC_PLAYER as GS_STATIC_PLAYER, STATIC_STRIDE as GS_STATIC_STRIDE,
    JOBJ_FLAGS as GS_JOBJ_FLAGS, JOBJ_ROOT_OBJ as GS_JOBJ_ROOT_OBJ,
    JOBJ_DISP_MASK as GS_JOBJ_DISP_MASK)

RUNS_ROOT = STORAGE_PATH / "test-runs"
DEFAULT_ISO = PROJECT_ROOT / "output" / "harness-test.iso"
DEFAULT_OUT = (PROJECT_ROOT / "output" / "agent-artifacts" / "frameshot"
               if getattr(sys, 'frozen', False)
               else PROJECT_ROOT / "scratch" / "frameshot")

# A move that never ran is written as `_error-<char>-<move>.png`, NOT
# `<char>-<move>-FAILED.png`. Windows globbing is CASE-INSENSITIVE, so the
# obvious success glob `<char>-*-f*.png` matched `-FAILED.png` and a hard crash
# was counted as a successful capture (a crashing Squirtle was written up as
# "1/1 moves captured"). The error files now share no prefix with the shots, so
# no `-f*` pattern can ever pick them up again.
ERROR_PREFIX = "_error-"

# --- THE SHOT NOTES: which moves are worth photographing --------------------- #
# Hard-won, measured, and easy to get wrong. A shot list is evidence design, not
# taste.
#
# * BOWSER `nair` IS UNUSABLE FROM FRAME 8 for ported costumes. Bowser's neutral
#   air tucks him into his shell, and the animation SWAPS MODEL PARTS to do it
#   (the per-anim visibility mechanism -- HSD anim code 31 -- the same one behind
#   Jigglypuff's hats). A costume ported onto Bowser does not carry the shell
#   part, so from frame 8 the game draws essentially nothing. Measured in game
#   2026-07-31, dragonite-on-Bowser vs vanilla Bowser, same boot, same camera:
#     frame:      1       4       6       8       9      10      16      30
#     ported: 163190  147330  153572     145     129     134      97      62
#     vanilla:165220  158629  140718   63824   74975   74012   71761   69497
#   (non-background pixels). This is NOT a camera bug -- the camera is parked on
#   the fighter at 39.5 world-y with the fighter's feet at 31.5, and vanilla
#   Bowser lands dead centre in the same frame. It cost the 2026-07-30 grading
#   run 16 HUD-only cells that were graded as if they showed something. For a
#   Bowser-donor subject shoot `nair:1-6`, or use another aerial.
#
# * `shield` IS A POOR EVIDENCE SHOT. It renders the subject inside a
#   translucent pink bubble that washes out every colour and occludes the
#   silhouette -- 4 of 24 subject cells in a sheet spent on a picture of a
#   shield. If the point is the COMPRESSION pose (does the rig fold without
#   tearing?), `dtilt:1` is strictly better: it compresses the skeleton to 0.67
#   of bind height against shield's 0.86, and nothing is drawn over the model.
#   The bubble cannot be hidden the way Nana is: it is not a node of the
#   fighter's JObj tree but an efLib GFX whose alpha ftCo_Guard writes every
#   frame from shield health (decomp ftCo_Guard.c:196, efLib_SetParamAlpha), so
#   the JObj render-flag trick does not reach it. Zeroing that effect's alpha
#   while the game is frozen is the plausible lever if anyone needs the shield
#   pose specifically -- UNIMPLEMENTED and unverified. Prefer dtilt:1.
#
# Machine-readable form of the first note, so a shot list that walks into it is
# warned about BEFORE the pictures are taken instead of after they are graded:
# {(donor, move): (first_bad_frame, why)}.
SHOT_HAZARDS = {
    ("bowser", "nair"): (
        8, "Bowser's nair swaps to a shell model part the ported costume does "
           "not have -- from frame 8 the subject is NOT DRAWN (measured "
           "2026-07-31: 153572 px at f6, 145 px at f8). Shoot nair:1-6"),
}

# Capture width in pixels. Part of the control-cache key (a 640px control next
# to a 1280px mon is not a comparison), so it is a named constant, not a magic
# number sprinkled through the capture calls.
CAPTURE_WIDTH = 1280

# --- THE FRAME BUDGET -------------------------------------------------------- #
# How many GAME frames the harness burns before a shot. These are load-bearing
# for image identity, not just for speed: an `idle` capture is one frame of a
# LOOPING Wait animation, so changing the budget rotates the animation phase and
# changes the picture. Measured 2026-07-30 by removing the 60-frame camera pan:
# every mid-move frame stayed bit-identical (jab mean 0.000, fair/nair <= 0.39)
# while the idle shots moved by mean 1.6-5.0, up to 11 % of pixels.
#
# So the budget is part of the control-cache key (`pipeline`). Change a number
# here and old cached controls stop matching -- by design: they would otherwise
# be paired against mon shots taken at a different animation phase, which is the
# silent-mis-pairing failure the cache is built to be incapable of.
# Ridden out after the stage load (READY / GO!). This is the single largest
# per-target cost -- 3.3-4.1s of every target, measured -- and it CANNOT be made
# faster by running the emulator harder: Slippi Dolphin ignores EmulationSpeed
# (it locks speed for netplay fairness), which is why --turbo measured as an
# exact no-op across every phase. A game-frame wait can therefore only be made
# SHORTER, not faster. MEX_READY_FRAMES exists to sweep it empirically; it is
# part of pipeline_id() so a different value correctly invalidates cached
# controls rather than pairing images taken at different settle depths.
READY_FRAMES = int(os.environ.get("MEX_READY_FRAMES", "200"))
IDLE_SETTLE_FRAMES = 8    # stepped before an `idle` capture
CAMERA_PAN_FRAMES = 60    # game-camera pan-back after a recenter (--closeup skips)


def fit_mode(args):
    """How a capture is measured and framed:

    * `"auto"`   -- measure the model and RE-FRAME it when it is clipped (the
      historical --closeup --plain-bg behaviour).
    * `"measure"` -- measure the model exactly the same way but NEVER move the
      camera (--fixed-camera). A verification profile that declares its camera
      cannot be allowed to widen the shot after seeing the result: the whole
      point of the extent evidence is that the framing was fixed in advance.
      The shipped pixels are identical to a `"off"` capture, which is why the
      control cache keys `"measure"` and `"off"` the same (see shot_spec).
    * `"off"`    -- neither measured nor re-framed.

    Measuring needs a MEASURABLE frame: the flat --plain-bg background is what
    separates subject from not-subject, and --closeup is what owns the camera.
    """
    if not (args.closeup and args.plain_bg):
        return "off"
    if getattr(args, "no_autofit", False):
        return "off"
    if getattr(args, "fixed_camera", False):
        return "measure"
    return "auto"


def autofit_on(args):
    """True only when a capture may be RE-FRAMED. Keyed into the control cache."""
    return fit_mode(args) == "auto"


def pipeline_id(args):
    # v3 = the 2026-07-31 autofit rewrite (measure the MODEL with the particles
    # hidden, root-relative radius, exponential backoff, never re-aim). It
    # changes the framing of any cell the old fit re-framed, so every control
    # cached under v2 must be re-shot rather than paired with a v3 mon shot.
    return {"v": 3, "ready": READY_FRAMES, "idle_settle": IDLE_SETTLE_FRAMES,
            "camera_pan": 0 if args.closeup else CAMERA_PAN_FRAMES}


def log(m):
    print(m, flush=True)


def _pinned_step(runner, bag, bag_pin, n):
    """Step n frames; if bag_pin, zero the bag's knockback each frame so a
    hard hit can't push it out of range (rapid-jab/command-grab finishers).
    Mirrors effect_probe.py's _pinned_step. Returns the real frame count."""
    if not (bag and bag_pin):
        return runner._step(n)
    got = 0
    for _ in range(n):
        got += runner._step(1)
        bag.pin()
    return got


def parse_frame_spec(spec):
    """'4' / '1-8' / '1,4,7' -> sorted unique 1-based list."""
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    frames = sorted(out)
    if not frames or frames[0] < 1:
        raise SystemExit("frames are 1-based (frame 1 = first frame of the move)")
    return frames


def parse_shot_specs(specs):
    """['fair:1-8', 'idle', ...] -> [(move, [frames]), ...]."""
    shots = []
    for s in specs or []:
        move, _, spec = str(s).partition(":")
        move = move.strip().lower()
        if move != "idle" and move not in MOVES:
            raise SystemExit(f"unknown move '{move}' "
                             f"(known: idle, {', '.join(MOVES)})")
        shots.append((move, parse_frame_spec(spec) if spec else [1]))
    return shots


def parse_shots(args):
    """Build the [(move, frames)] batch from --shot (repeatable, 'move:frames')
    or the single-move --move/--frame/--frames form."""
    shots = parse_shot_specs(args.shot)
    if args.move:
        shots.append((args.move, parse_frame_spec(args.frames)
                      if args.frames else [args.frame]))
    return shots


def parse_char(s):
    """Character name (char_select table) or a raw external id like 0x1A."""
    kind = resolve_ckind(s)
    if kind is not None:
        return kind
    try:
        return int(s, 0)
    except ValueError:
        raise SystemExit(f"unknown character '{s}' (name or external id like 0x1A)")


def char_label(s, kind):
    return s.lower() if resolve_ckind(s) is not None else f"0x{kind:02X}"


def parse_bag_pos(s):
    """'dx,dy' -> (float, float). dx = units in front of the attacker."""
    parts = str(s).split(",")
    if len(parts) != 2:
        raise SystemExit("--bag-pos wants 'dx,dy' (e.g. 8,0)")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        raise SystemExit(f"--bag-pos not numeric: {s!r}")


def capture(boot, path, allow_focus_fallback=True, tries=10):
    """Write one PNG of Dolphin's render output.

    PrintWindow(PW_RENDERFULLCONTENT) reads the window's OWN pixels, so it works
    while Dolphin is occluded or in the background -- the only capture path a
    long unattended batch can rely on. `capture_png` is a fallback that calls
    SetForegroundWindow, i.e. it STEALS FOCUS mid-run; batch mode leaves it off
    (--allow-focus-fallback opts back in) so a batch can never silently
    photograph whatever window the steal landed on."""
    png = shot.capture_via_printwindow(boot.pid, max_width=1280, tries=tries)
    if not png and allow_focus_fallback:
        png = shot.capture_png(boot.pid, max_width=1280)
    if not png:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return True


# --- freshness: VERIFY the screen changed instead of sleeping and hoping ------ #
# The old path slept 0.15 s after every camera poke and 0.10 s after every
# plain-background poke, then captured. That is 0.25 s of dead wall clock on
# EVERY image (416 images = 104 s of the 584 s grading run) and it never checked
# anything -- it assumed the renderer had caught up.
#
# Measured 2026-07-30, one warm session:
#   * the RENDERED-frame counter (framestep.RENDERED_FRAMES) keeps ticking at
#     60/s while the game is debug-frozen, so it is a real "the renderer has
#     produced a new frame" signal;
#   * with NO wait at all, 6 of 32 captures at a fresh yaw angle came back
#     BYTE-IDENTICAL to the previous angle -- i.e. 18.8 % stale. The sleep was
#     protecting something real.
# So we replace "sleep and assume" with "wait for the renderer, then PROVE the
# pixels changed": strictly faster AND strictly stronger. A capture that cannot
# be proven fresh is reported, not silently kept.
class Fresh:
    """Per-session capture state: the previous PNG, so a new one can be proven
    different. Also counts unproven captures, which is a HANG SMELL -- a hung
    game renders the same frame forever, and that is exactly what "identical to
    the last capture" measures."""

    def __init__(self):
        self.prev = None
        self.unproven = 0
        self.regrabs = 0

    def grab(self, d, boot, tries=10, allow_focus_fallback=False,
             deadline=0.6, must_differ=True):
        """(png_bytes|None, proven_fresh). Waits for the renderer to advance,
        captures, and re-captures missing/identical images after another rendered
        frame (bounded by `deadline`). Black GPU reads are not render events."""
        if framestep.wait_render_frames(d, 2) == 0:
            # counter unreadable/stuck -- fall back to the historical sleep
            # rather than capture something we cannot vouch for
            time.sleep(0.15)
        t0 = time.time()
        png = None
        while True:
            # Own the retry at this boundary: each attempt follows an observed
            # renderer advance. The lower-level fixed-sleep loop can repeatedly
            # sample a black GPU surface without giving us a frame observation.
            png = shot.capture_via_printwindow(boot.pid, max_width=1280, tries=1)
            if png is None and allow_focus_fallback:
                png = shot.capture_png(boot.pid, max_width=1280)
            if png is not None and (not must_differ or self.prev is None or png != self.prev):
                self.prev = png
                return png, True
            if time.time() - t0 >= deadline:
                if png is None:
                    return None, False
                self.unproven += 1
                self.prev = png
                return png, False
            self.regrabs += 1
            framestep.wait_render_frames(d, 1, timeout=0.1)

    def write(self, d, boot, path, **kw):
        png, proven = self.grab(d, boot, **kw)
        if png is None:
            return False, False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return True, proven


# --- close-up camera ------------------------------------------------------- #
# Camera struct at 0x80452C68 (decomp `cm_80452C68`); DEBUG_FREE is the only
# mode that is write-stable -- camera.c's render dispatch for mode 8 just reads
# free_fov/free_int_pos/free_eye_pos back out, with no per-frame recompute. The
# STANDARD camera frames the whole stage, which is far too wide to judge a
# costume: a ported model is ~150px tall in a 1280x960 stage shot.
CAMERA_MODE = 0x80452C6C
CAMERA_FARZ = 0x80452C78
CAM_DBG_INT = 0x80453040
CAM_DBG_EYE = 0x8045304C
CAM_DBG_FOV = 0x80453058
CAMERA_DEBUG_FREE = 8
NO_DPAD_CAMERA = (0x802275F8, 0x480000F0)   # so nothing yanks the camera


def _screen_axes(yaw, side):
    """(right, up) unit vectors of the closeup camera's IMAGE PLANE, so a
    measured screen-space offset can be turned into a world-space aim shift."""
    import math
    if yaw is None:
        return (float(side), 0.0, 0.0), (0.0, 1.0, 0.0)
    a = math.radians(float(yaw))
    # eye - interest = (r sin a, ., r cos a) => view dir (-sin a, 0, -cos a);
    # right = dir x up.
    return (math.cos(a), 0.0, -math.sin(a)), (0.0, 1.0, 0.0)


def closeup_camera(d, player, dist=42.0, fov=35.0, height=8.0, side=1.0,
                   yaw=None, pitch=0.0, aim_dx=0.0, aim_dy=0.0):
    """Park DEBUG_FREE just off the fighter so it fills the frame.

    RE-PARKED BEFORE EVERY CAPTURE, not once per move: a fighter is a moving
    target and the late frames are exactly the ones a reviewer needs. Bowser's
    nair leaves the ground by 31.5 world units in ten frames -- with a 42-unit
    camera that is more than a full frame height, so a park-once camera photo-
    graphs empty sky. Verified in game 2026-07-31 by reading the camera struct
    back after the write at frame 10 of that nair: interest y 39.5 for a fighter
    whose feet are at 31.5, and vanilla Bowser lands dead centre of the frame.
    Do not "optimise" this back to one park per move.

    `side` is a multiplier on the Z eye offset: +1 front, -1 behind. `yaw`
    (degrees, 0 = front, 90 = the fighter's left, 180 = behind) overrides it and
    orbits the camera on a circle around the fighter -- the game is frozen, so
    the same frame can be inspected from any angle. `pitch` lifts the eye.
    Aim a little above the fighter's origin (which sits at its FEET) so the
    body, not the floor, is centred.

    `aim_dx`/`aim_dy` shift the aim point along the camera's own right/up axes
    (eye AND interest together, so the viewing angle is untouched). autofit
    USED to drive them to re-centre an off-centre subject and no longer does --
    it re-centred on the SILHOUETTE, which hides a model-origin offset and
    decouples a port's framing from its control's (see the autofit block
    comment). They are kept for diagnostics and default to 0, which is the
    framing every capture now uses.
    """
    import math
    try:
        x, y = player.pos()
    except Exception:
        x, y = 0.0, 0.0
    if yaw is None:
        ex, ez = x, dist * side
        ey = y + height
    else:
        a = math.radians(float(yaw))
        r = dist * math.cos(math.radians(pitch))
        ex, ez = x + r * math.sin(a), r * math.cos(a)
        ey = y + height + dist * math.sin(math.radians(pitch))
    right, up = _screen_axes(yaw, side)
    sh = tuple(right[i] * aim_dx + up[i] * aim_dy for i in range(3))
    d.write_u32(NO_DPAD_CAMERA[0], NO_DPAD_CAMERA[1])
    d.write_u32(CAMERA_MODE, CAMERA_DEBUG_FREE)
    for addr, vec in ((CAM_DBG_INT, (x, y + height, 0.0)),
                      (CAM_DBG_EYE, (ex, ey, ez))):
        for i, v in enumerate(vec):
            d.write_f32(addr + 4 * i, float(v) + sh[i])
    d.write_f32(CAM_DBG_FOV, float(fov))
    d.write_f32(CAMERA_FARZ, 16384.0)


# --- autofit: the camera follows the fighter, the FRAME follows the model ----- #
# Re-parking on the fighter every capture (above) keeps the fighter's ORIGIN in
# shot. It does not keep the MODEL in shot, and the difference is what wrecked
# the 2026-07-30/31 grading sheets: --cam-dist is calibrated per DONOR (Melee's
# fighters differ ~4x in height) but a ported costume is a different size from
# the fighter it rides on, so oversized ports run off the edges. Measured on the
# 83-target overnight run: 5/5 marth utilt f10, 5/5 mewtwo nair f10, 5/5 Ice
# Climbers idle/shield/usmash and every kingler/granbull cell touched the frame
# border, while the VANILLA control in the same row never did -- i.e. the defect
# tracks the model, not the move or the frame.
#
# So after the first capture we MEASURE the subject against the flat background
# and, only when it is clipped by the frame edge (or missing entirely), pull the
# camera back and shoot again.
#
# --- WHAT THE FIRST VERSION GOT WRONG, MEASURED 2026-07-31 -------------------- #
# It measured EVERY non-background pixel and re-aimed at that centroid. On a
# translating move that is not the model: `run` leaves a psLib DUST TRAIL ~24
# world units behind the fighter, just outside a calibrated frame. The loop it
# produced is vicious --
#   * a wisp of smoke clips an edge, so the fit pulls the camera BACK, which
#     brings MORE of the trail into frame, and re-aims TOWARDS it, which drags
#     the fighter off-centre;
#   * a censored bbox only grows, so the next pass sees an even bigger "subject".
# Measured on ekans__kirby run:6, one boot, four yaws, against the shipped
# 2026-07-31 sheets: the old fit moved the fighter 197-216 px off centre and
# shrank it 17-30 % at three of four yaws, and every one of the 64 `run` cells
# that grading_sheets flagged as CLIPPED had a chosen blob of mean saturation
# 0.0 -- grey smoke -- sitting at x/W 0.06-0.13 or 0.87-0.95. Not one was the
# model. The same run proved the alternatives dead: the rendered root matrix
# equals cur_pos exactly (no epoch skew), a commanded camera offset lands in the
# very next capture (no presentation lag), and four captures of a frozen pose
# are byte-identical.
#
# So the fit now
#   * MEASURES WITH THE PARTICLES HIDDEN (hidden_particles below) -- the subject
#     of a fit is the MODEL, and the final image is still shot with the effects
#     restored, so nothing is hidden from the reviewer;
#   * fits the ROOT-RELATIVE RADIUS about the principal point (the camera parks
#     the fighter's gameplay root there), never the silhouette midpoint;
#   * NEVER RE-AIMS. Re-centring each subject on its own silhouette hides a bad
#     model-origin offset -- exactly the defect a reviewer needs to see -- and
#     breaks the port/control comparison, because the two would be centred on
#     different things;
#   * backs off EXPONENTIALLY (x1.25) until the model is clear of every border,
#     because a clipped bbox is a LOWER BOUND and one modest nudge cannot work,
#     then refines once to leave AUTOFIT_MARGIN of headroom;
#   * never comes CLOSER than the donor's calibrated distance, so a port can
#     only ever be pulled back from its control, never zoomed past it.
AUTOFIT_MARGIN = 0.08        # headroom left around the model after the refine
AUTOFIT_BACKOFF = 1.25       # exponential, because a clipped bbox is a floor
AUTOFIT_MAX_PASSES = 6       # 1.25^6 = 3.8x, enough for any donor/costume pair
AUTOFIT_EMPTY_FRAC = 0.0015  # below this the subject is NOT DRAWN, not small
# Border pixels before a frame counts as "clipped". Measured on the MODEL ONLY
# (the particles are unlinked for the measurement), so this can be strict: a
# horn or a foot 2 px over the edge is exactly what this exists to catch. The
# old value of 8 was a hedge against particle noise that no longer reaches here.
AUTOFIT_EDGE_PX = 2
AUTOFIT_WIDE = 3.0           # search multiplier when the subject is missing
# The HUD (stock icon + percent) is composited over the bottom-left corner and
# is NOT the subject; measured as a fraction of the frame so it survives a
# resolution change.
HUD_FRAC = (0.36, 0.31)


def _subject_mask(png_bytes, bg_hex, tol=24):
    """Boolean "not the flat background, and not the HUD" mask, or None when the
    image cannot be measured (no numpy/PIL, unreadable PNG)."""
    try:
        import io
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    try:
        a = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"),
                       dtype=np.int16)
    except Exception:
        return None
    H, W = a.shape[:2]
    v = int(str(bg_hex), 16)
    bg = np.array([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF], dtype=np.int16)
    keep = np.ones((H, W), dtype=bool)
    keep[H - int(H * HUD_FRAC[1]):, :int(W * HUD_FRAC[0])] = False
    return (np.abs(a - bg).sum(2) > tol) & keep


def _extent_of(k):
    """The measurement dict for an already-computed subject mask."""
    import numpy as np
    H, W = k.shape
    n = int(k.sum())
    out = {"frac": n / float(H * W), "bbox": None, "clipped": False,
           "missing": n == 0 or n / float(H * W) < AUTOFIT_EMPTY_FRAC,
           "cx": 0.0, "cy": 0.0, "w": 0.0, "h": 0.0, "px": n, "edge": 0,
           "W": W, "H": H}
    if n == 0:
        return out
    ys, xs = np.nonzero(k)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    out["bbox"] = (x0, x1, y0, y1)
    out["w"], out["h"] = (x1 - x0 + 1) / W, (y1 - y0 + 1) / H
    out["cx"] = ((x0 + x1) / 2.0) / W - 0.5
    out["cy"] = ((y0 + y1) / 2.0) / H - 0.5
    edges = (int((k[:, :2]).sum()), int((k[:, -2:]).sum()),
             int((k[:2, :]).sum()), int((k[-2:, :]).sum()))
    out["edge"] = max(edges)
    out["clipped"] = (not out["missing"]) and out["edge"] >= AUTOFIT_EDGE_PX
    return out


def subject_extent(png_bytes, bg_hex, tol=24):
    """Measure the subject -- MODEL PLUS EFFECTS -- against the flat --plain-bg
    background. Returns the measurement dict, or None if the image cannot be
    measured. Everything downstream treats None as "do not autofit": an
    unmeasurable frame must never be silently re-framed."""
    k = _subject_mask(png_bytes, bg_hex, tol)
    return None if k is None else _extent_of(k)


def model_extent(png_full, png_no_fighter, bg_hex, tol=24, grow=2):
    """Measure THE MODEL ALONE, by differencing against a render of the same
    frozen frame with the fighter's JObj taken out of every render pass.

    Hiding the fighter is the only reliable direction. The reverse -- hide every
    effect and photograph the model -- cannot be done from one lever: the run
    dust is TWO systems. The puffy clouds are psLib particles (hidden_particles
    unlinks them) but a smoke streak survives that unlink, and it is what pulled
    entei__dr_mario back from the calibrated 53.2 to 88 units in the 2026-07-31
    validation run. So: render with the fighter, render without it, and take the
    pixels the fighter ADDS.

    `grow` dilates the effects mask by a couple of pixels before subtracting, so
    antialiasing along a smoke edge cannot leave a rind of "model". The error
    this makes is CONSERVATIVE -- a limb seen through translucent dust is
    dropped, so the model can be measured slightly small, never large."""
    import numpy as np
    a = _subject_mask(png_full, bg_hex, tol)
    b = _subject_mask(png_no_fighter, bg_hex, tol)
    if a is None or b is None:
        return None
    if grow:
        d = b.copy()
        for s in range(1, int(grow) + 1):
            d[:-s] |= b[s:]
            d[s:] |= b[:-s]
            d[:, :-s] |= b[:, s:]
            d[:, s:] |= b[:, :-s]
        b = d
    return _extent_of(a & ~b)


def _fit_factor(m):
    """How much further back the camera must go for the whole silhouette to sit
    inside (1 - AUTOFIT_MARGIN) of the half-frame, measured about the PRINCIPAL
    POINT. The camera parks the fighter's gameplay root there, so this is the
    root-relative radius the review asked for -- NOT the silhouette midpoint. A
    model whose mass is entirely on one side of its root must still be fully
    visible, and centring on its own midpoint would hide exactly that.

    Backing the eye off along the view axis by a factor f divides every screen
    offset from the principal point by ~f, so the factor is read straight off
    the pixels and needs no FOV/aspect calibration."""
    x0, x1, y0, y1 = m["bbox"]
    cx, cy = m["W"] / 2.0, m["H"] / 2.0
    rx = max(abs(x0 - cx), abs(x1 - cx)) / (cx * (1 - AUTOFIT_MARGIN))
    ry = max(abs(y0 - cy), abs(y1 - cy)) / (cy * (1 - AUTOFIT_MARGIN))
    return max(rx, ry)


def camera_state(d):
    """The DEBUG_FREE camera words, read back out of the game.

    A capture is only attributable to a declared camera if the camera the game
    was actually using can be shown to have been that one, and to have been the
    same one for every image in a measurement group.
    """
    words = [d.u32(CAMERA_MODE)]
    for base in (CAM_DBG_INT, CAM_DBG_EYE):
        words += [d.u32(base + 4 * i) for i in range(3)]
    words.append(d.u32(CAM_DBG_FOV))
    return words


# How many re-grabs a frame gets to settle before we stop believing it is
# composited. The game is debug-frozen, so two consecutive PrintWindow grabs of
# the same camera and the same scene are byte-identical; a frame that keeps
# changing is one where a RAM poke (the camera, the flat background) has not
# reached the screen yet.
SETTLE_TRIES = 8


def measured_capture(fresh, d, boot, park, bg_hex, dist, log=log, name="",
                     allow_focus_fallback=False):
    """Capture ONE frame at a FIXED camera as an auditable measurement GROUP.

    The problem this replaces: `autofit_capture` measured the particle-hidden
    and fighter-hidden renders and then delivered `first_png`, an EARLIER
    capture. Nothing established that the delivered image had the same
    composition as the measured one -- and it did not always. In the 2026-09-22
    known-good run the grab frame's recorded actor bounds contained zero
    non-background pixels in the PNG that was saved, because the first capture
    was composited before the camera write reached the screen. A measurement
    that does not describe the delivered image is worse than no measurement.

    So: settle first, then take every image of the group at one camera, then
    prove the group held together.

    * `full` -- the delivered frame, effects and all, re-grabbed until two
      consecutive captures are byte-identical (the scene is frozen, so that is
      what "composited" looks like).
    * `actor` -- the same frame with psLib particles out of the render.
    * `background` -- the same frame with the fighter ALSO out of every render
      pass. The actor is what `actor` has and `background` does not.
    * `full` again after restoring, required to equal the first one.

    Returns (png, proven, info). `info` carries the retained `actor` and
    `background` bytes, the game-frame counter before and after the whole
    group, the camera words before and after, and `group_consistent`. The
    CALLER decides what the pixels mean; this function only establishes that
    the three images describe the same frozen frame at the same camera.
    """
    info = {"passes": 0, "dist": float(dist), "aim_dx": 0.0, "aim_dy": 0.0,
            "reframed": False, "missing": False, "clipped": False, "px": None,
            "radius": None, "effects_edge": None, "effects_only": False,
            "model_measured": False, "reframe_allowed": False,
            "group_consistent": False, "settled": False, "settle_grabs": 0,
            "camera_before": None, "camera_after": None,
            "game_before": None, "game_after": None,
            "actor_png": None, "background_png": None,
            "schema": "frameshot-measurement-group-v1"}

    def shoot(must_differ):
        return fresh.grab(d, boot, must_differ=must_differ,
                          allow_focus_fallback=allow_focus_fallback)

    park(dist, 0.0, 0.0)
    info["camera_before"] = camera_state(d)
    info["game_before"] = d.u32(observe.FRAME_COUNTER)

    png, proven = shoot(True)
    if png is None:
        return None, False, info
    # SETTLE: keep grabbing until the screen stops changing. Without this the
    # group can straddle the arrival of the camera poke.
    for attempt in range(SETTLE_TRIES):
        again, _ = shoot(False)
        info["settle_grabs"] = attempt + 1
        if again is None:
            return None, False, info
        if again == png:
            info["settled"] = True
            break
        png = again
    if not info["settled"]:
        log(f"  ** {name}: the frame never settled after {SETTLE_TRIES} grabs; "
            f"this capture is not attributable to the declared camera")
        return png, proven, info

    # Visibility writes cross the same asynchronous render/compositor boundary
    # as camera writes. Settle EACH state: a stable full frame alone does not
    # establish that an immediately sampled hidden frame has arrived.
    info['state_settled'] = {}
    def settled_state(label):
        previous, _ = shoot(False)
        for attempt in range(SETTLE_TRIES):
            current, _ = shoot(False)
            if current is not None and current == previous:
                info['state_settled'][label] = True
                return current
            previous = current
        info['state_settled'][label] = False
        return previous

    with hidden_particles(d):
        actor_png = settled_state('actor')
        if actor_png is not None:
            with hidden_fighter(d):
                background_png = settled_state('background')
        else:
            background_png = None
    restored = settled_state('restored')

    info["camera_after"] = camera_state(d)
    info["game_after"] = d.u32(observe.FRAME_COUNTER)
    info["actor_png"] = actor_png
    info["background_png"] = background_png
    info["passes"] = 3
    info["group_consistent"] = bool(
        actor_png is not None and background_png is not None
        and restored is not None and restored == png
        and all(info['state_settled'].get(k) for k in ('actor','background','restored'))
        and info["camera_before"] == info["camera_after"]
        and info["game_before"] is not None
        and info["game_before"] == info["game_after"])
    info["model_measured"] = info["group_consistent"]
    if not info["group_consistent"]:
        log(f"  ** {name}: the measurement group did not hold together "
            f"(restored={'same' if restored == png else 'different'}, "
            f"camera={'same' if info['camera_before'] == info['camera_after'] else 'moved'}, "
            f"game frame {info['game_before']} -> {info['game_after']}); "
            f"this frame cannot be measured")
    return png, proven, info


def autofit_capture(fresh, d, boot, park, bg_hex, dist, fov, log=log,
                    name="", allow_focus_fallback=False, reframe=True):
    """Park -> grab -> MEASURE THE MODEL -> (only when the MODEL is clipped or
    missing) back off and shoot again. Returns (png|None, proven, info).

    With `reframe=False` (fit_mode "measure") the camera is NEVER moved: the
    model is measured once at the declared distance and the first capture is
    the shipped image. `info["model_measured"]` then says the measurement came
    from the fighter-hidden difference rather than from the subject silhouette,
    so a caller can tell a clipped MODEL from a clipped dust trail without
    letting the harness widen the shot to make the answer nicer.

    `park(dist, aim_dx, aim_dy)` must place the camera AND re-assert the flat
    background: every pass is a fresh capture of the same frozen game frame, so
    whatever the background needs is needed again. Freshness is the existing
    prove-the-pixels-changed path (class Fresh) -- no sleeps are added, and the
    game stays debug-frozen throughout, so frame-exactness is untouched.

    The first capture is taken exactly as it always was, effects and all. It is
    a valid PREFILTER because the model is a subset of the subject: if nothing
    at all touches a border, the model does not either, and that picture is
    returned untouched (the overwhelmingly common case, and byte-identical to
    what the old code produced). Only when something DOES touch a border do we
    pay for the fit -- and that fit measures the MODEL ALONE (psLib particles
    unlinked, and the remainder differenced against a fighter-hidden render of
    the same frozen frame), because on `run` what touches the border is almost
    always the dust trail. See the block comment above for the measurements.
    """
    base = float(dist)
    info = {"passes": 0, "dist": base, "aim_dx": 0.0, "aim_dy": 0.0,
            "reframed": False, "missing": False, "clipped": False, "px": None,
            "radius": None, "effects_edge": None, "effects_only": False,
            "model_measured": False, "reframe_allowed": bool(reframe)}

    def shoot(must_differ=True):
        return fresh.grab(d, boot, must_differ=must_differ,
                          allow_focus_fallback=allow_focus_fallback)

    park(dist, 0.0, 0.0)
    png, proven = shoot()
    if png is None:
        return None, False, info
    m = subject_extent(png, bg_hex)
    if m is None:
        return png, proven, info           # unmeasurable: never re-frame
    info.update(px=m["px"], effects_edge=m["edge"])
    if not (m["clipped"] or m["missing"]):
        return png, proven, info           # already in frame: keep that picture

    # Something reached a border. Decide WHAT, on the model alone.
    first_png, first_proven = png, proven

    def measure_model(moved):
        """(png, proven, model measurement) at the CURRENT camera. Cheap path
        first: with the particles unlinked the frame is usually the model alone
        and one grab answers it. Only when something still reaches a border do
        we pay for the second render that isolates it.

        `moved` says the camera was just re-parked, so the pixels MUST change
        and Fresh can prove it. The other grabs here only toggle a visibility
        flag and may legitimately return an identical frame (nothing psLib was
        visible; the fighter was not drawn), and demanding a difference would
        make each of those wait out the freshness deadline for nothing."""
        png_, proven_ = shoot(must_differ=moved)
        if png_ is None:
            return None, False, None
        mm = subject_extent(png_, bg_hex)
        if mm is None or not mm["clipped"]:
            return png_, proven_, mm
        with hidden_fighter(d):
            png_e, _pe = shoot(must_differ=False)
        if png_e is None:
            return png_, proven_, mm
        isolated = model_extent(png_, png_e, bg_hex)
        if isolated is None:
            return png_, proven_, mm
        # The actor was isolated from the effects by a paired capture of the
        # same frozen frame with the fighter out of every render pass. Say so:
        # a caller that must not guess ("is that the model or the dust?") needs
        # to know which of the two measurements it is holding.
        info["model_measured"] = True
        return png_, proven_, isolated

    with hidden_particles(d):
        for attempt in range(AUTOFIT_MAX_PASSES):
            if attempt or dist != base:
                park(dist, 0.0, 0.0)
            png, proven, m = measure_model(bool(attempt) or dist != base)
            if png is None:
                png, proven = first_png, first_proven
                break
            if m is None:
                break
            info.update(passes=attempt + 1, dist=round(dist, 2), px=m["px"],
                        missing=bool(m["missing"]), clipped=bool(m["clipped"]))
            if not reframe:
                # The camera is the profile's. Record what was measured at it
                # and stop -- no wide search, no backoff, no refine.
                info["bbox"] = m.get("bbox")
                info["frac"] = m.get("frac")
                if not (m["missing"] or m["clipped"]):
                    info["radius"] = round(_fit_factor(m), 3)
                break
            if m["missing"]:
                # Off-frame, or NOT DRAWN. One wide search answers it; if the
                # model is still absent it is the model, not the camera (Bowser's
                # nair swaps to a shell part ported costumes do not have -- see
                # THE SHOT NOTES).
                if attempt == 0:
                    dist *= AUTOFIT_WIDE
                    continue
                break
            if m["clipped"]:
                # A clipped bbox is a LOWER BOUND -- 20 or 200 px may be off
                # frame -- so one modest nudge cannot be right. Back off
                # exponentially until the model is clear of every border.
                dist *= AUTOFIT_BACKOFF
                continue
            info["radius"] = round(_fit_factor(m), 3)
            # Clear of every border, so the bbox is a TRUE extent: refine once.
            # `base` is a FLOOR -- a port may be pulled back from its control,
            # never zoomed past it, or the pair stops being a size comparison.
            want = max(base, dist * _fit_factor(m))
            if abs(want - dist) > 0.05 * dist:
                dist = want
                park(dist, 0.0, 0.0)
                png2, proven2, m2 = measure_model(True)
                if m2 and not (m2["clipped"] or m2["missing"]):
                    png, proven, m = png2, proven2, m2
                    info.update(dist=round(dist, 2), px=m["px"],
                                radius=round(_fit_factor(m), 3),
                                passes=info["passes"] + 1)
                else:
                    dist /= AUTOFIT_BACKOFF     # the refine overshot: step out
                    info["dist"] = round(dist, 2)
            break
    if info["missing"]:
        # The wide search found nothing, so the model is NOT DRAWN and no camera
        # can fix it. Ship the calibrated framing: a HUD-only picture at the
        # donor's own distance at least sits in the sheet next to a control that
        # was shot the same way, and the sidecar says it is not evidence.
        dist = base
        info["dist"] = round(base, 2)
    info["reframed"] = abs(dist - base) > 0.01
    info["effects_only"] = bool(not info["clipped"] and not info["missing"]
                                and not info["reframed"]
                                and (info["effects_edge"] or 0) >= AUTOFIT_EDGE_PX)

    # THE SHIPPED IMAGE is always taken with the effects restored: the fit is a
    # measurement, not a censor. When the fit kept the calibrated distance the
    # very first capture already IS that image, so re-use it instead of paying
    # for another grab (this is the dust case, i.e. most of them).
    if info["reframed"]:
        park(dist, 0.0, 0.0)
        # must_differ=False: this re-shoots a camera the fit already proved
        # fresh, and when the frame holds no effects the restored image is
        # LEGITIMATELY byte-identical to the last fit capture. Demanding a
        # difference here made a correct capture spin to its deadline and then
        # report itself unproven -- a false hang smell in the manifest.
        png3, proven3 = shoot(must_differ=False)
        if png3 is not None:
            png, proven = png3, proven3
    else:
        png, proven = first_png, first_proven

    if info["missing"]:
        how = (f"after a {info['dist']:.0f}-unit wide search" if reframe
               else f"at the declared {info['dist']:.0f}-unit camera "
                    f"(fixed: no wide search is allowed)")
        log(f"  ** {name}: THE SUBJECT IS NOT DRAWN -- {info['px']} non-"
            f"background pixels {how}. "
            f"This cell is NOT evidence of anything; do not grade it")
    elif info["model_measured"] and not reframe and info["clipped"]:
        log(f"  (fixed camera: {name}: the MODEL is clipped by the frame at "
            f"the declared distance -- recorded, NOT re-framed)")
    elif info["reframed"]:
        log(f"  (autofit: {name}: the MODEL was clipped by the frame; "
            f"re-framed at dist {info['dist']:.0f} after {info['passes']} "
            f"extra grab(s))")
    elif info["effects_only"]:
        log(f"  (autofit: {name}: {info['effects_edge']} border pixels, but the "
            f"model is fully in frame -- an EFFECT touches the edge, not the "
            f"model; framing kept)")
    return png, proven, info


def assert_plain_bg(d, rgb_hex):
    """'Every Stage has a Plain Background and No Stage Textures' (Achilles,
    1.02) as direct RAM pokes: flat-color word RRGGBB00 at 0x80452C70 plus the
    render-flag word at 0x80453000. The game can rewrite these (the original
    is a per-frame gecko code), so re-assert before every capture."""
    d.write_u32(0x80452C70, (int(rgb_hex, 16) & 0xFFFFFF) << 8)
    d.write_u32(0x80453000, 0x00C40000)


# FD's drifting background "stars" are efLib PARTICLES the Achilles code can't
# touch: the stage's background-JObj anim carries SPtcl keys that spawn one
# long-lived psLib generator (bank 0x1E -- efLib_Cb_SPtcl routes stage banks
# to grLib, eflib.c:998). Fighter effects use their own ef banks, so killing
# bank 0x1E removes ONLY the stars. Lever: unlink bank-0x1E generators from
# the global generator list (hsd_804D78FC) and bank-0x1E particles from the
# per-linkNo particle lists (hsd_804D0908[]); the particle render pass walks
# these lists every composited frame, so unlinked nodes vanish immediately,
# even while frozen. Nothing is freed -> no dangling pointers (a few leaked
# structs per anim loop). Validated by backend/devtools/research/fd_star_gen_hunt.py; see
# research/docs-research/fd-star-particles.md.
_PS_GEN_HEAD = 0x804D78FC     # hsd_804D78FC: HSD_Generator* list head
_PS_PART_HEADS = 0x804D0908   # hsd_804D0908: HSD_Particle*[] per-linkNo heads
_PS_STAGE_BANK = 0x1E         # stage SPtcl/DPtcl bank (grLib route)


def kill_stage_particles(d, bank=_PS_STAGE_BANK):
    """Unlink every live psLib generator/particle of the stage bank. Re-run
    before each capture (the stage anim can respawn the generator).

    Always with the game debug-frozen (frozen here if it is not already, and
    let go after). The walk reads a next pointer and then writes it, while the
    game's particle update (efLib_particles_proc_main) changes the same lists
    every logic frame. Unfrozen the two race: a particle freed between the read
    and the write is put back on a live list, and the list loops when the pool
    hands that particle out again. The game then hangs drawing particles,
    seconds later, in the next move that makes many (the fighterport G19 stop,
    2026-11-13: with the walk slowed, unfrozen looped 2 of 6 boots and lost
    particles in 2 more; frozen, 0 of 6). The render pass only reads the lists."""
    held = not framestep.is_frozen(d)
    if held:
        framestep.freeze(d)
        framestep.wait_render_frames(d, 2)    # the logic frame under way has ended
    try:
        _unlink_bank(d, bank)
    finally:
        if held:
            framestep.unfreeze(d)


def _unlink_bank(d, bank):
    prev, g, guard = None, d.u32(_PS_GEN_HEAD), 0
    while g and guard < 512:
        nxt = d.u32(g + 0x00)
        if d.u8(g + 0x18) == bank:                 # HSD_Generator.bank
            d.write_u32(_PS_GEN_HEAD if prev is None else prev + 0x00, nxt)
        else:
            prev = g
        g = nxt
        guard += 1
    for link_no in range(8):                       # psLib caps linkNo < 8
        head = _PS_PART_HEADS + 4 * link_no
        prev, p, guard = None, d.u32(head), 0
        while p and guard < 4096:
            nxt = d.u32(p + 0x00)
            if d.u8(p + 0x08) == bank:             # HSD_Particle.bank
                d.write_u32(head if prev is None else prev + 0x00, nxt)
            else:
                prev = p
            p = nxt
            guard += 1


class hidden_particles:
    """Every psLib particle out of the render, REVERSIBLY -- the measurement
    pass of autofit_capture().

    `kill_stage_particles` relinks around one bank and cannot be undone. Here we
    only need the lists to read EMPTY for the next composited frame, so zero the
    nine list heads and put them back afterwards: the nodes and their next
    pointers are untouched, nothing is freed, and the game is debug-frozen, so
    between the save and the restore the only thing that walks those lists is
    the (read-only) render pass.

    Why it must exist: `run`'s dust trail is a bank-0 psLib emission that sits
    ~24 world units behind the fighter -- just outside a calibrated frame, and
    the first thing a widening camera finds. Measured 2026-07-31 on
    ekans__kirby: with the particles hidden the fighter's mask touches NO border
    at any of four yaws; with them visible the old fit chased the smoke to
    dist 49.2 and aim_dx -6.0 and pushed the model 197 px off centre."""

    def __init__(self, d):
        self.d = d
        self.saved = []

    def __enter__(self):
        heads = [_PS_GEN_HEAD] + [_PS_PART_HEADS + 4 * i for i in range(8)]
        self.saved = [(a, self.d.u32(a)) for a in heads]
        for a, _v in self.saved:
            self.d.write_u32(a, 0)
        return self

    def __exit__(self, *exc):
        for a, v in self.saved:
            self.d.write_u32(a, v)
        return False


class hidden_fighter:
    """The fighter's model out of every render pass, REVERSIBLY -- the second
    half of the model measurement (see model_extent).

    Same lever gamestate.Follower.hide uses for Nana: clear the OPA/XLU/TEXEDGE
    display bits (own DObj at 18, children at 28) of the root JObj. Both triples
    are needed -- a fighter is an ENVELOPE_MODEL, so the skinned body is the
    root's own DObj and rigid props hang off children. The SIMULATION is
    untouched; nothing rewrites the flag; and it takes effect on the very next
    presented frame with no stepped frame required, which is what makes it
    usable while the game is debug-frozen."""

    def __init__(self, d, port=0):
        self.d = d
        self.port = port
        self.jobj = None
        self.flags = None

    def __enter__(self):
        gobj = self.d.u32(GS_STATIC_PLAYER + GS_STATIC_STRIDE * self.port + 0xB0)
        self.jobj = self.d.u32(gobj + GS_JOBJ_ROOT_OBJ) if gobj else None
        if self.jobj:
            self.flags = self.d.u32(self.jobj + GS_JOBJ_FLAGS)
            if self.flags is not None:
                self.d.write_u32(self.jobj + GS_JOBJ_FLAGS,
                                 self.flags & ~GS_JOBJ_DISP_MASK)
        return self

    def __exit__(self, *exc):
        if self.jobj and self.flags is not None:
            self.d.write_u32(self.jobj + GS_JOBJ_FLAGS, self.flags)
        return False


# --- liveness: the check that "in-game" is NOT --------------------------------
def liveness(d, seconds=1.5, freeze_secs=1.0, early_ok_frames=3):
    """(verdict, reason) -- 'healthy' | 'hung' | 'crashed', from the GAME FRAME
    COUNTER (observe.Observer.watch_health).

    `early_ok_frames` returns 'healthy' the moment that many frame advances are
    observed (~50 ms) instead of watching for the full `seconds`. The hung and
    crashed verdicts are IDENTICAL either way -- a frozen counter still has to
    sit still for `freeze_secs`, a dead process still fails on the first poll --
    so this only shortens the boring answer. It matters because the between-
    target recovery calls this twice per target, which measured 3.0 s of every
    22.5 s target. Pass early_ok_frames=0 for the old full-watch behaviour
    (crash SOAK tests, where watching for a while IS the point).

    Why this exists: wait_in_game() only reads the scene flags, and a costume
    that HANGS the engine during the stage load can leave those flags reading
    in-game -- so the harness happily logs "in-game after 0.0s" and then
    photographs the same stale frame for every remaining target. The scene flag
    can lie; the frame counter cannot. ONLY call this while the game is NOT
    debug-frozen (framestep.freeze deliberately stops the counter)."""
    v, why, _st = Observer(d).watch_health(seconds=seconds,
                                           freeze_secs=freeze_secs,
                                           early_ok_frames=early_ok_frames)
    return v, why


# --- one booted, attached, CSS-ready Dolphin ---------------------------------
class SessionError(RuntimeError):
    pass


# Settle after the offline CSS scene flag flips, on the CURSOR-FREE path only.
# nav.wait_css_ready's 1.5 s default protects cursor input; frameshot never
# moves the cursor here.
CSS_SETTLE = 0.3


class Session:
    """One booted Dolphin + attached MEM1 + open pipe, parked on a ready offline
    CSS. A batch reuses ONE of these for every target: the ~90s boot is paid
    once instead of once per costume, which is the whole point of --batch."""

    def __init__(self, args, iso, log=log, stop_event=None):
        self.args = args
        self.iso = iso
        self.log = log
        # Cancellation has to reach the BOOT, not only the capture loop.
        # DolphinBoot already checks a stop event through its lock wait, its
        # "another Dolphin is open" wait and its launch; without one, a Stop
        # during preparation stopped nothing and the worker launched anyway.
        self.stop_event = stop_event
        self.boot = None
        self.d = None
        self.p = None
        # per-session freshness state (the previous capture, so the next one can
        # be PROVEN different rather than assumed fresh after a sleep)
        self.fresh = Fresh()

    def open(self):
        args, log_ = self.args, self.log
        boot = DolphinBoot(str(self.iso), None, str(RUNS_ROOT), clean_osd=True,
                           turbo=bool(getattr(args, "turbo", False)), log=log_,
                           stop_event=self.stop_event)
        self.boot = boot
        boot.prepare()
        # Slippi's local input-delay pipeline runs even offline: it adds 2
        # frames of pipe-input latency and draws the "Delay: 2f" OSD into
        # every capture. Zero it in the throwaway config.
        _write_ini(str(boot.user_dir / "Config" / "Dolphin.ini"),
                   lambda upsert, _r: upsert("Core", "SlippiOnlineDelay", "0"))
        boot.launch()
        if not boot.wait_for_pipe(timeout=45):
            raise SessionError("input pipe never appeared")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            if not d.alive():
                raise SessionError("Dolphin died during boot")
            time.sleep(0.4)
        if d.base is None:
            raise SessionError("could not locate MEM1")
        self.d = d

        match_setup.patch_one_player(d, log=log_)
        if args.kirby_copy:
            # JIT gotcha: arm before Kirby's first spawn compiles the function
            if not match_setup.arm_kirby_copy_ondeath(d, log=log_):
                raise SessionError("could not arm the Kirby copy-ability patch")
        self.p = boot.open_pipe()
        if not nav.nav_to_css(d, self.p, log=log_):
            raise SessionError("never reached the offline CSS")
        nav.wait_css_ready(d, Cursor(d, self.p), log=log_)
        match_setup.force_time_infinite(d, log=log_)
        return self

    def alive(self):
        return bool(self.boot and self.boot.alive() and self.d and self.d.alive())

    def close(self, keep=False):
        if self.boot:
            try:
                shot.close_capture(self.boot.pid)
            except Exception as exc:
                # Capture teardown must not strand the process/slot we own.
                self.log(f"capture teardown failed: {exc}")
        try:
            if self.p:
                self.p.close()
        except Exception:
            pass
        if not self.boot:
            return None
        if keep:
            # DolphinBoot.cleanup() rmtree's the run dir, taking
            # User/Logs/dolphin.log with it -- the one artifact that explains a
            # hang. terminate() keeps it.
            self.boot.terminate()
            self.log(f"run dir kept: {self.boot.run_dir}")
            return str(self.boot.run_dir)
        self.boot.cleanup()
        return None


def recover_to_css(sess, log=log, tries=3):
    """Get back to a READY offline CSS from wherever we are -- mid-match, stuck
    on the stage-select screen, or on a menu -- so one bad target can't poison
    every target queued behind it.

    Returns True only when the CSS is confirmed AND the frame counter is
    advancing: a HUNG game reads 'at the CSS' exactly as happily as a live one,
    and continuing from there is how stale frames get captured and scored as
    passes."""
    d, p = sess.d, sess.p
    framestep.unfreeze(d)          # the quit inputs need real frames to run
    try:
        p.neutral()                # drop anything still held (shield holds L)
    except Exception:
        pass
    for _ in range(max(1, tries)):
        if not sess.alive():
            log("recover: Dolphin is gone")
            return False
        v, why = liveness(d)
        if v != "healthy":
            log(f"recover: game is {v} ({why}) -- it cannot be driven back to the CSS")
            return False
        if nav.at_offline_css(d):
            # settle=0.3, not the 1.5 s default: that settle exists so CURSOR
            # inputs land on a freshly-flipped CSS, and this path drives no
            # cursor at all -- it memory-writes the player block, warps to the
            # SSS and re-asserts the block after the warp. Measured 1.2 s per
            # target of pure wait for a UI we never touch.
            nav.wait_css_ready(d, Cursor(d, p), settle=CSS_SETTLE, log=log)
            match_setup.force_time_infinite(d, log=log)
            return True
        if StageCursor(d, p).on_stage_select():
            log("recover: backing out of the stage-select screen")
            for _ in range(3):
                p.tap("B", 0.08)
                time.sleep(0.4)
                if nav.at_offline_css(d):
                    break
            continue
        nav.reset_to_css(d, p, log=log)
    return nav.at_offline_css(d)


def start_match(sess, args, tgt, bag_kind, log=log):
    """CSS -> in-game as (char, color) on --stage, ending with the game frozen.
    Returns (ok, reason). Every failure reason is load-bearing: a False here
    MUST NOT be followed by captures."""
    d, p = sess.d, sess.p
    ckind, color = tgt["ckind"], tgt["color"]

    def write_players():
        if bag_kind is None:
            match_setup.write_solo_player(d, ckind, color)
        else:
            match_setup.write_bag_player(d, ckind, color, bag_ckind=bag_kind,
                                         bag_color=args.bag_color)
        if getattr(args,'native_items',None):
            from shared.ingame.items import configure_rules
            receipt=configure_rules(d,args.native_items)
            if not hasattr(args,'native_item_rule_receipts'):args.native_item_rule_receipts=[]
            args.native_item_rule_receipts.append(receipt)

    log(f"memory-select {tgt['label']} (ckind=0x{ckind:02X}, color {color})"
        + (f" + bag 0x{bag_kind:02X}" if bag_kind is not None else " solo")
        + "...")
    write_players()
    match_setup.warp_to_stage_select(d)
    sc = StageCursor(d, p)
    if not sc.wait_for_stage_select(timeout=8.0):
        return False, "CSS->SSS warp did not land"
    write_players()                       # re-assert after the scene flip
    if not sc.force_select(INTERNAL_STAGE_ID[args.stage]):
        return False, "match never started"
    log(f"match started on {args.stage}")

    if not wait_in_game(d, timeout=25.0, log=log):
        return False, "never reached in-game"
    # THE GATE. wait_in_game() above is a SCENE-FLAG check and it false-positives
    # ("in-game after 0.0s") on a build that hangs during the stage load. Riding
    # out READY/GO is counted in real GAME FRAMES, so a stalled counter fails it
    # -- and that is the only signal that separates "loaded" from "hung".
    if not wait_game_frames(d, READY_FRAMES, log=log):
        v, why = liveness(d) if sess.alive() else ("crashed", "process exited")
        return False, f"{v} on load: the required startup frame interval did not complete ({why})"
    # Route each fighter to its own controller pad. The CSS->SSS warp skips
    # the vanilla PlayerInitData->StaticPlayer.player_id copy, so without
    # this every port polls pad 0 = the pipe and the bag MIRRORS the
    # attacker (bag did the attacker's up-B; both clanked into Rebound).
    active_ports = [0] if bag_kind is None else [0, 1]
    match_setup.fix_player_pad_indices(d, active_ports, log=log)
    if args.plain_bg:
        # after READY/GO so late stage-load writes can't undo it
        assert_plain_bg(d, args.plain_bg)
        if args.stage == "finaldestination":
            kill_stage_particles(d)

    if args.kirby_copy:
        hat = match_setup.install_kirby_copy_via_rebirth(
            d, match_setup.KIRBY_COPY_FTKIND[args.kirby_copy], port=0, log=log)
        if hat != match_setup.KIRBY_COPY_FTKIND[args.kirby_copy]:
            return False, f"kirby copy install failed (hat.kind={hat})"

    framestep.freeze(d)
    # Prove the game can actually be STEPPED before handing the session to the
    # move runner. Right after a stage load the freeze handshake is sometimes
    # not armed yet, and the first recipe dies with "frame step stalled (0/2
    # frames ran)" -- silently costing that target its first shot. Re-arm once;
    # if it still won't step, say so instead of capturing whatever is on screen.
    if framestep.step(d, 1) < 1:
        log("freeze handshake not armed after the load; re-arming")
        framestep.unfreeze(d)
        time.sleep(0.25)
        framestep.freeze(d)
        if framestep.step(d, 1) < 1:
            return False, "frame stepping never armed after the match loaded"
    if getattr(args, "debug_draw", "off") != "off":
        from shared.ingame.debug_draw import set_debug_draw
        set_debug_draw(d, args.debug_draw, active_ports)
    return True, ""


def run_shots(sess, args, tgt, bag_kind, out_dir, log=log):
    """Run this target's shots on the (already frozen, in-game) session.
    Returns {"images": [...], "failures": int, "broken": reason|None}."""
    d, p, boot = sess.d, sess.p, sess.boot
    label = tgt["label"]
    shots = tgt["shots"]
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"images": [], "failures": 0, "broken": None, "unproven": 0,
           "cached": 0, "specs": {}, "missing": 0, "refits": 0, "fits": {},
           "identity": None, "stage_state": None}
    allow_focus = args.allow_focus_fallback
    bag_dx, bag_dy = parse_bag_pos(args.bag_pos)
    orbit = [float(a) for a in args.orbit.split(",") if a.strip()] or [None]
    fresh = sess.fresh
    cache_ctx = tgt.get("cache_ctx")     # set only for CACHEABLE targets
    mode = fit_mode(args)
    fit_on = mode != "off"

    def park_closeup(yaw):
        """A `park(dist, aim_dx, aim_dy)` for autofit_capture: re-aim the camera
        at the fighter's CURRENT position and re-assert the flat background."""
        def _park(dist, aim_dx, aim_dy):
            closeup_camera(d, runner.player, dist=dist, fov=args.cam_fov,
                           height=args.cam_height, side=args.cam_side, yaw=yaw,
                           pitch=args.cam_pitch, aim_dx=aim_dx, aim_dy=aim_dy)
            if args.plain_bg:
                assert_plain_bg(d, args.plain_bg)
                if args.stage == "finaldestination":
                    kill_stage_particles(d)
        return _park

    def grab(name, move=None, frame=None, yaw=None, fit=False):
        """Capture the CURRENT frozen frame to <name>. With `fit`, the camera is
        parked by autofit_capture (which may re-frame a clipped subject);
        otherwise the caller has already parked it."""
        path = out_dir / name
        if fit:
            if mode == "measure":
                png, proven, info = measured_capture(
                    fresh, d, boot, park_closeup(yaw), args.plain_bg,
                    args.cam_dist, log=log, name=name,
                    allow_focus_fallback=allow_focus)
            else:
                png, proven, info = autofit_capture(
                    fresh, d, boot, park_closeup(yaw), args.plain_bg,
                    args.cam_dist, args.cam_fov, log=log, name=name,
                    allow_focus_fallback=allow_focus, reframe=True)
            ok = png is not None
            if ok:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png)
                # RETAIN THE PAIR beside the frame it measures. A measurement
                # whose inputs were thrown away cannot be re-derived, checked
                # or disputed -- and one of them turned out to describe a
                # different capture than the one that was delivered.
                for key, suffix in (("actor_png", "-actor.png"),
                                    ("background_png", "-background.png")):
                    blob = info.pop(key, None)
                    if blob:
                        side = path.with_name(path.stem + suffix)
                        side.write_bytes(blob)
                        info[key.replace("_png", "_file")] = side.name
                if info["missing"]:
                    res["missing"] += 1
                if info["reframed"] and not info["missing"]:
                    res["refits"] += 1
                # Keep the measurement whenever there IS one. A fixed-camera
                # run never re-frames, so "reframed or missing" would throw
                # away exactly the clipped-model evidence it was taken for.
                if (info["reframed"] or info["missing"] or info["model_measured"]
                        or mode == "measure"):
                    res["fits"][name] = info
        else:
            ok, proven = fresh.write(d, boot, path,
                                     allow_focus_fallback=allow_focus)
        if not ok:
            return False
        if not proven:
            res["unproven"] += 1
            log(f"  ** {name}: could not prove the frame is fresh (identical to "
                f"the previous capture) -- treat with suspicion")
        res["images"].append(str(path))
        if cache_ctx is not None and move is not None and frame is not None:
            res["specs"][str(path)] = shot_spec(args, tgt, cache_ctx, move,
                                                frame, yaw)
        return True

    # Ice Climbers: the port's follower (StaticPlayer.player_entity[1]). None
    # for every other fighter -- see gamestate.nana_of / grab() below.
    nana = None
    runner = MoveRunner(d, p, log=log, camera_pan=not args.closeup)
    if runner.player.resolve() is None:
        res["failures"] += len(shots)
        res["broken"] = "the fighter never spawned (port 0 ft is null)"
        log(f"** {res['broken']}")
        return res
    # WHO IS ACTUALLY IN THE MATCH, read back from the live fighter -- not
    # echoed from the player block we wrote. `identity["costume_id"]` is the
    # slot the engine loaded, which is the only thing that can distinguish
    # "built slot 4, captured slot 4" from "built slot 4, captured slot 0".
    try:
        res["identity"] = runner.player.identity()
    except Exception as e:
        res["identity"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        from shared.ingame.stage_state import capture_stage_state
        res["stage_state"] = capture_stage_state(d)
    except Exception as e:
        res["stage_state"] = {"error": f"{type(e).__name__}: {e}"}
    log(f"live identity: {res['identity']}  stage: {res['stage_state']}")
    nana = nana_of(d, 0)
    if nana is not None:
        # ICE CLIMBERS. Nana spawns COINCIDENT with Popo (measured: same x
        # within 0.1, z -3.8), so an ICs capture is two bodies in one space --
        # at rest she hides exactly behind him and the instant anything moves
        # she smears across him. Costumes were loading correctly the whole
        # time; they simply could not be SEEN. Drop her from the render passes
        # (she stays in the simulation). Re-asserted once per shot below: one
        # RAM write, and it re-acquires her if she respawns into a new GObj.
        nana.hide()
        log("Ice Climbers: Nana hidden from the render passes so the graded "
            "fighter (Popo) is the only body in frame")
    if args.kirby_copy and runner.player.state() in (12, 13):
        # recover from the copy-install rebirth halo before the first shot
        runner.p.frame(["SET MAIN 0.500 0.000", "FLUSH"])
        runner._step(3)
        runner.p.neutral()
        runner.player.set_pos(0.0, 25.0)
        for _ in range(180):
            runner._step(1)
            if runner.player.state() == 14:
                break
    bag = None
    if bag_kind is not None:
        bag = Bag(d, port=1)
        if not bag.resolve():
            res["failures"] += len(shots)
            res["broken"] = "bag player never spawned (port 1 ft is null)"
            log(f"** {res['broken']}")
            return res
        log(f"bag resolved on port 1: {bag.snapshot()['state_name']}")
    for move, frames in shots:
        hz = SHOT_HAZARDS.get((label, move))
        if hz and max(frames) >= hz[0]:
            log(f"** SHOT HAZARD {label} {move}:{max(frames)} -- {hz[1]}")
    log(f"game frozen; running {len(shots)} move(s) for {tgt['id']}...")

    # scheduled mid-move inputs: {move_frame: [pipe lines]}
    sched = {}
    for spec in args.input_at or []:
        n, _, lines = spec.partition(":")
        sched.setdefault(int(n), []).extend(lines.split("|"))

    for move, frames in shots:
        try:
            runner.reset()          # idle at center stage between moves
            if nana is not None:
                nana.hide()         # cheap re-assert; survives a respawn
            if move == "idle":
                # Frame 1 is the settled idle sample; later requested frames
                # advance from it. Keep the actual animation frame in evidence.
                runner._step(IDLE_SETTLE_FRAMES)
                state = runner.player.snapshot()["state"]
            else:
                if bag:
                    park_bag(runner, bag, dx=bag_dx, dy=bag_dy)
                    bs = bag.snapshot()
                    log(f"bag parked at ({bs['x']:.1f}, {bs['y']:.1f}) "
                        f"state={bs['state_name']}")
                state = runner.execute(move, rise=args.rise)
            snap0 = runner.player.snapshot()
            log(f"{move} started: state={snap0['state_name']} "
                f"anim={snap0['anim_frame']} (this is frame 1)")

            results = []
            cur = 1
            for target in frames:
                while cur < target:
                    stops = [f for f in sched if cur < f <= target]
                    nxt = min(stops) if stops else target
                    cur += _pinned_step(runner, bag, args.bag_pin, nxt - cur)
                    if cur in sched:
                        runner.p.frame(list(sched[cur]) + ["FLUSH"])
                        log(f"  (frame {cur}: sent {'; '.join(sched[cur])})")
                if cur != target:
                    log(f"  (step overshoot: wanted frame {target}, at {cur})")
                s = runner.player.snapshot()
                # The SIMULATION frame this capture belongs to. Frozen stepping
                # means it must not move while a frame is being photographed,
                # and it must advance between two different move frames -- both
                # of which a later reader can only check if it is recorded.
                s["game_frame"] = d.u32(observe.FRAME_COUNTER)
                s["port"] = 0
                if bag:
                    b = bag.snapshot()
                    b["in_damage"] = bag.in_damage()
                    s["bag"] = b
                name = f"{label}-{move}-f{cur:02d}.png"
                # The camera is re-parked HERE, on the frame that is about to be
                # photographed -- never once per move. The fighter is a moving
                # target (Bowser is 31.5 units off the ground by frame 10 of his
                # nair) and the late frames are the ones worth looking at.
                #
                # The game is frozen but the renderer keeps running, so
                # PrintWindow can still grab a frame composited BEFORE the
                # camera write landed -- that silently produced wide,
                # off-centre shots on 4 of 6 captures. grab() now WAITS for
                # the rendered-frame counter and then proves the pixels
                # changed, which covers both this and the plain-bg poke
                # without a fixed sleep.
                if args.closeup and not fit_on:
                    park_closeup(orbit[0])(args.cam_dist, 0.0, 0.0)
                elif not args.closeup and args.plain_bg:
                    assert_plain_bg(d, args.plain_bg)
                    if args.stage == "finaldestination":
                        kill_stage_particles(d)
                # Cache the shot under the REQUESTED frame, and only when the
                # stepper actually landed on it. An overshoot (`cur != target`)
                # is a different picture from the one a later run would ask for,
                # and serving it back would be exactly the kind of "paired
                # against a subtly different control" defect this cache exists
                # not to create.
                cache_f = cur if cur == target else None
                ok = grab(name, move, cache_f, orbit[0], fit=fit_on)
                # extra turntable angles off the SAME frozen frame
                for ang in orbit[1:]:
                    if not fit_on:
                        park_closeup(ang)(args.cam_dist, 0.0, 0.0)
                    grab(f"{label}-{move}-f{cur:02d}-yaw{int(ang):03d}.png",
                         move, cache_f, ang, fit=fit_on)
                s["move_frame"] = cur
                s["file"] = name if ok else None
                if name in res["fits"]:
                    # the frame was re-framed (or the subject was NOT DRAWN):
                    # say so IN the evidence, next to the picture it describes
                    s["autofit"] = res["fits"][name]
                results.append(s)
                if not ok:
                    res["failures"] += 1
                log(f"  frame {cur}: state={s['state_name']} "
                    f"anim={s['anim_frame']}"
                    + (f" bag={s['bag']['state_name']}" if bag else "")
                    + f" -> {name if ok else 'CAPTURE FAILED'}")

            sidecar = {"char": label, "ckind": tgt["ckind"], "color": tgt["color"],
                       "move": move, "stage": args.stage, "entry_state": state,
                       # requested vs OBSERVED, side by side in the evidence
                       "live_identity": res["identity"],
                       "live_stage_state": res["stage_state"],
                       "captures": results}
            if bag:
                sidecar["bag"] = {"ckind": bag_kind, "dx": bag_dx, "dy": bag_dy,
                                  "hit": any(r.get("bag", {}).get("in_damage")
                                             for r in results)}
                log(f"bag hit this move: {sidecar['bag']['hit']}")
            (out_dir / f"{label}-{move}.json").write_text(json.dumps(
                sidecar, indent=2))
        except MoveError as e:
            res["failures"] += 1
            log(f"MOVE FAILED ({move}): {e}")
            capture(boot, out_dir / f"{ERROR_PREFIX}{label}-{move}.png",
                    allow_focus_fallback=allow_focus)
            try:
                runner.reset()      # recover for the remaining shots
            except MoveError as e2:
                log(f"could not recover idle after failure ({e2}); aborting this target")
                res["broken"] = f"frame stepping stalled: {e2}"
                break
    return res


# --- the invariant-control cache ---------------------------------------------- #
# A target marked `"control": true` (batch) or run with --control (single) is
# declared INVARIANT: the donor's untouched vanilla fighter, which cannot change
# between sessions. Its images are keyed on every parameter that moves a pixel
# -- camera, background, move, frame, angle, resolution AND a content hash of
# the ISO's render environment -- and reused instead of re-shot.
#
# In the 2026-07-30 grading run 7 of 26 targets were exactly this (~157 s of a
# 584 s run), and verify_mon.py additionally paid a WHOLE EXTRA DOLPHIN BOOT per
# mon to shoot the same control again.
#
# The hard rule is in control_cache.key_of(): a spec missing any keyed field is
# an error, not a cache miss. If you add a capture flag that changes the image,
# add it to SPEC_FIELDS and bump SCHEMA -- a collision here silently pairs a mon
# against a control shot under different settings, which is the single most
# expensive class of bug this project has.
def target_is_control(args, tgt):
    return bool(getattr(args, "control", False) or tgt.get("control"))


def cache_context(args, iso, tgt, log=log):
    """(env_id, detail) for this target, or None if the cache is off/unusable."""
    if getattr(args, "no_control_cache", False):
        return None
    try:
        return control_cache.env_id(iso, tgt["label"], tgt["color"], args.stage)
    except Exception as e:
        log(f"control-cache: cannot identify the render environment ({e}); "
            f"caching disabled for {tgt['id']}")
        return None


def shot_spec(args, tgt, ctx, move, frame, yaw):
    bag = None
    if args.bag:
        dx, dy = parse_bag_pos(args.bag_pos)
        bag = {"ckind": parse_char(args.bag), "color": args.bag_color,
               "dx": dx, "dy": dy, "pin": bool(args.bag_pin)}
    # Resolve the camera from the TARGET first, args second. This must not
    # depend on WHEN it is called: store_control_shots runs inside the
    # per-target camera override (so it saw cam_dist 46.8), while
    # try_cached_target runs at the top of the loop BEFORE that override is
    # applied (so it saw the command-line default). Reading args directly made
    # store and lookup compute different keys for the same picture, and the
    # cache never hit once -- 120 entries, 0 serves. Failing safe, but useless.
    cam = tgt.get("cam") or {}

    def _cam(field):
        return cam.get(field, getattr(args, field))

    return control_cache.make_spec(
        env=ctx[0], char=tgt["label"], ckind=tgt["ckind"], color=tgt["color"],
        move=move, frame=frame, yaw=yaw, closeup=args.closeup,
        cam_dist=_cam("cam_dist"), cam_fov=_cam("cam_fov"),
        cam_height=_cam("cam_height"), cam_side=_cam("cam_side"),
        cam_pitch=args.cam_pitch, plain_bg=args.plain_bg, stage=args.stage,
        width=CAPTURE_WIDTH, rise=args.rise, pipeline=pipeline_id(args),
        bag=bag, kirby_copy=args.kirby_copy, input_at=args.input_at,
        # autofit can MOVE THE CAMERA for this image, so it is a keyed
        # parameter: a control shot taken with it off must never be served to a
        # run with it on.
        autofit=autofit_on(args))


def expected_shot_files(args, tgt):
    """Every (filename, move, frame, yaw) this target WILL produce, derived from
    the same rules run_shots uses. Only exact -- i.e. only usable for the cache
    -- for shots whose stepper lands on the requested frame, which is why a
    cached entry is only ever written when it did."""
    label = tgt["label"]
    orbit = [float(a) for a in args.orbit.split(",") if a.strip()] or [None]
    out = []
    for move, frames in tgt["shots"]:
        for f in frames:
            for ai, ang in enumerate(orbit):
                nm = (f"{label}-{move}-f{f:02d}.png" if ai == 0 else
                      f"{label}-{move}-f{f:02d}-yaw{int(ang):03d}.png")
                out.append((nm, move, f, ang))
    return out


def try_cached_target(args, iso, tgt, out_dir, log=log):
    """ALL-OR-NOTHING cache hit for one control target. Returns the list of
    written image paths, or None on a miss.

    All-or-nothing on purpose: once the match is loaded, skipping a handful of
    individual captures saves little, and mixing cached and freshly-shot images
    inside one target's directory makes the evidence harder to reason about."""
    ctx = cache_context(args, iso, tgt, log=log)
    if ctx is None:
        return None
    want = expected_shot_files(args, tgt)
    hits = []
    for nm, move, f, ang in want:
        spec = shot_spec(args, tgt, ctx, move, f, ang)
        src = control_cache.lookup(spec)
        if src is None:
            return None
        hits.append((src, out_dir / nm))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for src, dst in hits:
        dst.write_bytes(Path(src).read_bytes())
        written.append(str(dst))
    (out_dir / "_control_cache.json").write_text(json.dumps(
        {"env": ctx[0], "env_files": ctx[1], "iso": str(iso),
         "images": len(written),
         "note": "served from the invariant vanilla-control cache; "
                 "no Dolphin match was loaded for this target"}, indent=2))
    log(f"control-cache HIT: {len(written)} image(s) for {tgt['id']} "
        f"(env {ctx[0]}) -- no match loaded")
    return written


def store_control_shots(args, iso, tgt, res, log=log):
    """Put a freshly-shot control's images into the cache."""
    n = 0
    for path, spec in (res.get("specs") or {}).items():
        try:
            control_cache.store(spec, path, provenance={
                "iso": str(iso), "target": tgt["id"],
                "captured": datetime.now().isoformat(timespec="seconds")})
            n += 1
        except Exception as e:
            log(f"control-cache: could not store {path}: {e}")
    if n:
        log(f"control-cache: stored {n} invariant image(s) for {tgt['id']}")
    return n


# --- targets ------------------------------------------------------------------
# Per-target camera overrides. The batch's whole point is mixing CHARACTERS in
# one boot, and Melee's fighters differ ~4x in height (Kirby 10.6 units,
# Ganondorf 20.3, Bowser 42.6): one --cam-dist for all of them frames the small
# ones as specks and crops the big ones in half. That is not cosmetic -- a
# clipped model is the "fixed crop window" evidence defect that already wasted
# two review rounds. A target may carry {"cam": {"dist": .., "height": ..,
# "fov": .., "side": ..}}; anything it omits keeps the command-line value.
CAM_KEYS = {"dist": "cam_dist", "height": "cam_height",
            "fov": "cam_fov", "side": "cam_side"}


def make_target(char, color, shots, tid=None, seen=None, cam=None,
                control=False):
    kind = parse_char(char)
    lab = char_label(char, kind)
    tid = str(tid or f"{lab}-c{int(color)}")
    if seen is not None:
        base, n = tid, 2
        while tid in seen:
            tid = f"{base}-{n}"
            n += 1
        seen.add(tid)
    cam = {CAM_KEYS[k]: float(v) for k, v in (cam or {}).items()
           if k in CAM_KEYS}
    return {"id": tid, "char": char, "label": lab, "ckind": kind,
            "color": int(color), "shots": shots, "cam": cam,
            "control": bool(control)}


def load_batch(path, default_shots):
    """Parse --batch <file>. Accepts either a bare JSON list of targets or
    {"shots": [...], "targets": [...]} (the top-level "shots" is the default for
    targets that don't carry their own). A target is
    {"id"?, "char", "color"?, "shots"?/"moves"?} or the shorthand "char:color"."""
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"--batch file missing: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"--batch {p}: not valid JSON ({e})")
    if isinstance(data, dict):
        raw = data.get("targets") or data.get("mons") or []
        file_shots = data.get("shots") or data.get("moves")
    else:
        raw, file_shots = data, None
    if not raw:
        raise SystemExit(f"--batch {p}: no targets")
    fallback = parse_shot_specs(file_shots) if file_shots else default_shots
    out, seen = [], set()
    for i, t in enumerate(raw):
        if isinstance(t, str):
            c, _, col = t.partition(":")
            t = {"char": c, "color": int(col or 0)}
        if not isinstance(t, dict):
            raise SystemExit(f"--batch {p}: target #{i + 1} is not an object")
        char = t.get("char") or t.get("character")
        if not char:
            raise SystemExit(f"--batch {p}: target #{i + 1} has no 'char'")
        spec = t.get("shots") or t.get("moves")
        shots = parse_shot_specs(spec) if spec else fallback
        if not shots:
            raise SystemExit(
                f"--batch {p}: target '{char}' has no shots and neither the "
                f"file nor --shot supplies a default")
        out.append(make_target(char, t.get("color", 0), shots,
                               tid=t.get("id") or t.get("name"), seen=seen,
                               cam=t.get("cam"),
                               control=t.get("control") or t.get("vanilla")))
    return out


def _result(tgt, status, reason="", seconds=0.0, images=None, out_dir=None):
    return {"id": tgt["id"], "char": tgt["char"], "color": tgt["color"],
            "status": status, "reason": reason, "seconds": round(seconds, 1),
            "images": images or [], "dir": str(out_dir) if out_dir else None}


def run_targets(args, iso, targets, base_out, flat, bag_kind, *,
                timing=None, on_session=None, stop_event=None):
    """Boot ONE Dolphin and capture every target through it, quitting to the CSS
    between targets. Returns (results, boots, kept_run_dirs).

    The wrapper exists purely so that NO exit path -- a return, a SystemExit, or
    an unexpected exception -- can leave a Dolphin running: a leaked one holds
    the machine-wide `ingame/dolphin_lock` and blocks every later run.

    `timing`, when given, is filled in with `boot_seconds` and
    `teardown_seconds`: a caller that has to report where a verification run
    spent its minutes cannot get boot apart from captures out of the total.

    `on_session`, when given, is called with the live `Session` right after it
    opens and with `None` after it closes. It exists so a coordinator can hold
    a reference to the ONE emulator instance it owns and stop exactly that on
    cancellation -- never a process found by name or by port."""
    state = {"sess": None, "kept": [], "timing": timing if timing is not None else {},
             "on_session": on_session, "stop_event": stop_event}
    state["timing"].setdefault("boot_seconds", 0.0)
    state["timing"].setdefault("teardown_seconds", 0.0)
    try:
        return _run_targets(state, args, iso, targets, base_out, flat, bag_kind)
    finally:
        if state["sess"] is not None:
            t_close = time.time()
            kd = state["sess"].close(keep=args.keep_run)
            state["timing"]["teardown_seconds"] += time.time() - t_close
            if kd:
                state["kept"].append(kd)
            state["sess"] = None
            _notify_session(state, None)


def _notify_session(state, session):
    cb = state.get("on_session")
    if cb is None:
        return
    try:
        cb(session)
    except Exception:
        # A coordinator's bookkeeping must never take the emulator down with it.
        log("on_session callback raised; continuing")


def _run_targets(state, args, iso, targets, base_out, flat, bag_kind):
    results, kept = [], state["kept"]
    timing = state["timing"]
    fresh = True          # this session has not started a match yet
    boots = 0
    reboots = 0
    i = 0
    while i < len(targets):
        sess = state["sess"]
        tgt = targets[i]
        out_dir = base_out if flat else base_out / tgt["id"]
        t0 = time.time()
        log(f"\n===== [{i + 1}/{len(targets)}] {tgt['id']} "
            f"({tgt['label']} color {tgt['color']}) =====")

        # INVARIANT CONTROL: try the on-disk cache BEFORE booting/loading
        # anything. A full hit costs no Dolphin time at all -- which is why the
        # check sits above the session bootstrap, not inside the match loop.
        if target_is_control(args, tgt):
            cached = try_cached_target(args, iso, tgt, out_dir, log=log)
            if cached is not None:
                r = _result(tgt, "ok", "", time.time() - t0, cached, out_dir)
                r["cached"] = True
                results.append(r)
                log(f"----- {tgt['id']}: ok (cached, {len(cached)} image(s), "
                    f"{time.time() - t0:.1f}s)")
                i += 1
                continue
            tgt["cache_ctx"] = cache_context(args, iso, tgt, log=log)

        if sess is None:
            # assign BEFORE open() so a failure mid-boot still gets torn down
            # (a half-launched Dolphin would otherwise linger holding the
            # machine-wide dolphin_lock).
            sess = state["sess"] = Session(args, iso,
                                           stop_event=state.get("stop_event"))
            # Hand the coordinator the session BEFORE open(): the boot itself
            # can hang (menu navigation spun for 626 s on 2026-09-22, holding
            # the machine-wide lock the whole time), and a watchdog that only
            # learns about the emulator after a SUCCESSFUL boot cannot stop the
            # one case that needs stopping most.
            _notify_session(state, sess)
            t_boot = time.time()
            try:
                sess.open()
            except SessionError as e:
                timing["boot_seconds"] += time.time() - t_boot
                kd = sess.close(keep=True)     # keep the boot log
                if kd:
                    kept.append(kd)
                state["sess"] = None
                _notify_session(state, None)
                if boots == 0:
                    raise SystemExit(str(e))    # never got off the ground
                log(f"** reboot failed: {e}")
                for t in targets[i:]:
                    results.append(_result(t, "skipped",
                                           f"no Dolphin session: {e}"))
                return results, boots, kept
            timing["boot_seconds"] += time.time() - t_boot
            boots += 1
            fresh = True
            _notify_session(state, sess)   # again, now that boot.pid exists

        broken = None
        if not fresh and not recover_to_css(sess, log=log):
            broken = "could not return to a ready CSS between targets"
        if broken is None:
            fresh = False
            ok, reason = start_match(sess, args, tgt, bag_kind, log=log)
            if ok:
                # per-target camera, restored afterwards so one target can never
                # silently re-frame the rest of the batch
                saved = {k: getattr(args, k) for k in tgt.get("cam", {})}
                for k, v in tgt.get("cam", {}).items():
                    setattr(args, k, v)
                try:
                    r = run_shots(sess, args, tgt, bag_kind, out_dir, log=log)
                finally:
                    for k, v in saved.items():
                        setattr(args, k, v)
                status = ("ok" if r["failures"] == 0 and not r["broken"]
                          else "partial" if r["images"] else "failed")
                row = _result(tgt, status, r["broken"] or "",
                              time.time() - t0, r["images"], out_dir)
                if r.get("missing"):
                    # A HUD-only PNG is not a capture failure -- the grab
                    # worked, the model just was not drawn -- but it is not
                    # evidence either, and 16 such cells were graded as if they
                    # were. It goes in the manifest so nothing downstream can
                    # mistake an empty frame for a passing one.
                    row["subject_missing"] = r["missing"]
                if r.get("refits"):
                    row["autofit_refits"] = r["refits"]
                if r.get("fits"):
                    row["autofit"] = r["fits"]
                if r.get("unproven"):
                    # Not a hard failure, but it MUST be visible in the
                    # manifest: an image that never changed from the previous
                    # capture is what a hung renderer looks like.
                    row["unproven_fresh"] = r["unproven"]
                if r.get("identity"):
                    row["live_identity"] = r["identity"]
                if r.get("stage_state"):
                    row["live_stage_state"] = r["stage_state"]
                results.append(row)
                # Only an unblemished control run is worth caching: a partial /
                # broken target must never seed the library other runs trust.
                if status == "ok" and not r.get("unproven") \
                        and target_is_control(args, tgt) and tgt.get("cache_ctx"):
                    store_control_shots(args, iso, tgt, r, log=log)
                log(f"----- {tgt['id']}: {status} "
                    f"({len(r['images'])} image(s), {time.time() - t0:.1f}s)"
                    + (f"  ** {r['unproven']} UNPROVEN-FRESH **"
                       if r.get("unproven") else "")
                    + (f"  ** {r['missing']} SUBJECT-NOT-DRAWN **"
                       if r.get("missing") else "")
                    + (f"  [{r['refits']} re-framed]" if r.get("refits") else ""))
                if r["broken"]:
                    broken = r["broken"]
                else:
                    i += 1
                    continue
            else:
                results.append(_result(tgt, "failed", reason,
                                       time.time() - t0, [], out_dir))
                log(f"----- {tgt['id']}: FAILED ({reason})")
                # A failed START is only fatal for the batch if the game itself
                # is gone: otherwise back out to the CSS and carry on.
                if recover_to_css(sess, log=log):
                    i += 1
                    continue
                broken = f"unrecoverable after '{reason}'"
        else:
            results.append(_result(tgt, "hung", broken, time.time() - t0, [],
                                   out_dir))

        # --- the session is unusable from here ---------------------------------
        log(f"** SESSION BROKEN: {broken}")
        t_close = time.time()
        kd = sess.close(keep=True)   # ALWAYS keep the logs of a broken run
        timing["teardown_seconds"] += time.time() - t_close
        if kd:
            kept.append(kd)
        state["sess"] = None
        _notify_session(state, None)
        i += 1
        if args.on_hang == "reboot" and reboots < args.max_reboots and i < len(targets):
            reboots += 1
            log(f"rebooting Dolphin ({reboots}/{args.max_reboots}) to continue "
                f"with the remaining {len(targets) - i} target(s)")
            continue
        for t in targets[i:]:
            results.append(_result(t, "skipped", f"batch aborted: {broken}"))
        if i < len(targets):
            log(f"** ABORTING the remaining {len(targets) - i} target(s) -- "
                f"they are NOT captured and must not be read as passes")
        return results, boots, kept

    return results, boots, kept


def build_parser():
    """The frameshot command line, as a parser.

    Extracted from main() so a coordinator can run a capture IN-PROCESS with
    exactly the CLI's own defaults -- and so the machine-wide Dolphin lock can
    be held across build + boot + captures by ONE pid -- instead of re-typing a
    Namespace that silently drifts from the flags.
    """
    ap = argparse.ArgumentParser(description="frame-exact move screenshots")
    ap.add_argument("--char", default="marth", help="name or external id (0x1A = 1st m-ex fighter)")
    ap.add_argument("--color", type=int, default=0, help="costume slot")
    ap.add_argument("--move", choices=MOVES, help="single-move form")
    ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--frames", help="range/list: 1-8 or 1,4,7 (overrides --frame)")
    ap.add_argument("--shot", action="append", metavar="MOVE[:FRAMES]",
                    help="repeatable; many moves in one boot, e.g. "
                         "--shot fair:1-8 --shot fsmash:10")
    ap.add_argument("--batch", metavar="TARGETS.JSON",
                    help="capture MANY (char, color, shots) targets in ONE boot: "
                         "quit to the CSS between targets instead of rebooting "
                         "Dolphin. Each target gets its own subdir under --out "
                         "plus a batch.json manifest")
    ap.add_argument("--on-hang", choices=("reboot", "abort"), default="reboot",
                    help="what to do when a target hangs/crashes the game: "
                         "reboot Dolphin and continue with the rest (default), "
                         "or abort the batch. Either way the remaining targets "
                         "are never silently reported as captured")
    ap.add_argument("--max-reboots", type=int, default=3,
                    help="cap on --on-hang reboot recoveries per batch")
    ap.add_argument("--control", action="store_true",
                    help="this run captures an INVARIANT vanilla control (the "
                         "donor's untouched fighter): consult and populate the "
                         "on-disk control cache instead of re-shooting it every "
                         "session. In --batch, mark individual targets with "
                         "\"control\": true instead")
    ap.add_argument("--no-control-cache", action="store_true",
                    help="never read or write the control cache (force a fresh "
                         "capture -- use this to re-validate the cache)")
    ap.add_argument("--turbo", action="store_true",
                    help="uncap Dolphin's emulation speed and mute audio in the "
                         "throwaway config. Only affects REAL-TIME waits (boot, "
                         "menu nav, the post-load READY/GO gate); every capture "
                         "is taken with the game debug-frozen, so frame "
                         "exactness is unchanged")
    ap.add_argument("--allow-focus-fallback", action="store_true",
                    help="allow the focus-stealing screenshot fallback when the "
                         "occlusion-safe PrintWindow capture fails (off by "
                         "default so a batch can't photograph the wrong window)")
    ap.add_argument("--debug-draw", choices=("off", "overlay", "collision"), default="off",
                    help="retail hitboxes/hurtboxes: overlay on model, or collision only")
    ap.add_argument("--closeup", action="store_true",
                    help="park the DEBUG_FREE camera on the fighter so it fills "
                         "the frame (for judging model/costume quality)")
    ap.add_argument("--fixed-camera", action="store_true",
                    help="MEASURE every --closeup --plain-bg capture exactly as "
                         "autofit does, but NEVER move the camera: a clipped or "
                         "missing model is recorded, not re-framed. Use this "
                         "whenever the camera is part of a declared capture "
                         "profile, so a wider shot chosen after seeing the "
                         "result cannot make an extent check pass")
    ap.add_argument("--no-autofit", action="store_true",
                    help="never re-frame a capture. By default a --closeup "
                         "--plain-bg capture is MEASURED after the grab and, "
                         "only when the subject is clipped by the frame edge "
                         "or missing entirely, re-shot from further back. A "
                         "shot that was already fully in frame is never touched")
    ap.add_argument("--cam-dist", type=float, default=42.0)
    ap.add_argument("--cam-fov", type=float, default=35.0)
    ap.add_argument("--cam-height", type=float, default=8.0)
    ap.add_argument("--orbit", default="",
                    help="comma-separated yaw angles in degrees to capture at "
                         "each frame, e.g. 0,45,90,180 (turntable)")
    ap.add_argument("--cam-pitch", type=float, default=0.0,
                    help="camera elevation in degrees for --orbit")
    ap.add_argument("--cam-side", type=float, default=1.0,
                    help="+1 = in front, -1 = behind (check backfaces/holes)")
    ap.add_argument("--keep-run", action="store_true",
                    help="keep the isolated run dir so "
                         "User/Logs/dolphin.log survives for diagnosis (a run "
                         "that hangs keeps it regardless)")
    ap.add_argument("--stage", default="finaldestination")
    ap.add_argument("--iso", default=str(DEFAULT_ISO))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--rise", type=int, default=10, help="frames to rise before an aerial")
    ap.add_argument("--plain-bg", nargs="?", const="404040", metavar="RRGGBB",
                    help="flat stage background + no stage textures (Achilles "
                         "gecko code) so effect colors read unambiguously; "
                         "optional color, default neutral gray 404040")
    ap.add_argument("--input-at", action="append", metavar="N:LINE[|LINE]",
                    help="repeatable; on move frame N send raw pipe line(s), "
                         "e.g. 40:PRESS B and 42:RELEASE B to throw a charged "
                         "special. Applies to every shot in the run.")
    ap.add_argument("--bag", nargs="?", const="dk", metavar="CHAR",
                    help="add a punching-bag 2nd player (a HUMAN port with no "
                         "controller: stands still, never attacks, never moves "
                         "the camera) so on-hit-only effects are capturable. "
                         "Optional char name/id, default dk (big hurtbox)")
    ap.add_argument("--bag-color", type=int, default=0, help="bag costume slot")
    ap.add_argument("--bag-pos", default="8,0", metavar="DX,DY",
                    help="park the bag DX units in front of the attacker at "
                         "height DY before each move (default 8,0)")
    ap.add_argument("--kirby-copy", metavar="DONOR",
                    choices=sorted(match_setup.KIRBY_COPY_FTKIND),
                    help="give the (Kirby) attacker this donor's copy ability "
                         "before the shots run (KO->rebirth primitive), so "
                         "neutralb is the COPIED special drawing the "
                         "EfKb<XX>.dat copy bank. The donor MUST be in the "
                         "match: pass --bag <donor> too, or the install "
                         "HANGS the game (match_setup.py)")
    ap.add_argument("--bag-pin", action="store_true",
                    help="zero the bag's knockback velocity every stepped "
                         "frame + re-pin its position (gamestate.Bag.pin()), "
                         "so it can't be launched/thrown out of re-grab range "
                         "-- unblocks rapid-jab and command-grab finishers "
                         "(effect_probe.py's bag.pin spec key, same mechanism)")
    return ap


def main():
    args = build_parser().parse_args()

    iso = Path(args.iso).resolve()   # Dolphin runs from another cwd
    if not iso.exists():
        raise SystemExit(f"ISO missing: {iso}")
    if args.stage not in INTERNAL_STAGE_ID:
        raise SystemExit(f"unknown stage '{args.stage}' "
                         f"(known: {', '.join(sorted(INTERNAL_STAGE_ID))})")
    cli_shots = parse_shots(args)
    if args.batch:
        targets = load_batch(args.batch, cli_shots)
        flat = False
        # Batch runs are unattended: a focus-stealing capture would silently
        # photograph whatever window won the race.
        if not args.allow_focus_fallback:
            log("batch: captures are PrintWindow-only (occlusion-safe); "
                "pass --allow-focus-fallback to re-enable the focus fallback")
        # (single-target runs keep the historical fallback -- they're short and
        # usually attended, and callers depend on always getting an image)
    else:
        if not cli_shots:
            raise SystemExit("nothing to do: pass --shot move:frames "
                             "(repeatable), --move ..., or --batch targets.json")
        targets = [make_target(args.char, args.color, cli_shots)]
        flat = True
        args.allow_focus_fallback = True

    if args.kirby_copy and not args.bag:
        raise SystemExit("--kirby-copy requires --bag <donor> (the donor must "
                         "be in the match or the copy install hangs the game)")
    bag_kind = parse_char(args.bag) if args.bag else None
    # absolute: the manifest is read from other cwds (and frameshot itself is
    # usually run from backend/ with a relative --out)
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    started = datetime.now().isoformat(timespec="seconds")
    phases = {}
    results, boots, kept = run_targets(args, iso, targets, out_dir, flat,
                                       bag_kind, timing=phases)
    total = time.time() - t0

    ok = sum(1 for r in results if r["status"] == "ok")
    shots_n = sum(len(r["images"]) for r in results)
    cached_n = sum(1 for r in results if r.get("cached"))
    if args.batch:
        manifest = {
            "iso": str(iso), "stage": args.stage, "started": started,
            "seconds": round(total, 1), "boots": boots,
            # boot and teardown broken out, so a caller reporting where the
            # minutes went does not have to guess which part of the total was
            # the ~90 s emulator boot and which part was actual capturing.
            "boot_seconds": round(phases.get("boot_seconds", 0.0), 1),
            "teardown_seconds": round(phases.get("teardown_seconds", 0.0), 1),
            "capture_seconds": round(
                max(0.0, total - phases.get("boot_seconds", 0.0)
                    - phases.get("teardown_seconds", 0.0)), 1),
            "seconds_per_target": round(total / max(1, len(results)), 1),
            "targets_total": len(results), "ok": ok, "images": shots_n,
            "cached_targets": cached_n,
            # The capture SETTINGS, recorded with the run. Without these the
            # manifest cannot tell you whether two runs are comparable -- and
            # "compared against a control shot with different settings" is the
            # exact evidence defect the control cache is keyed to prevent.
            "capture": {
                "closeup": args.closeup, "autofit": autofit_on(args),
                "fit_mode": fit_mode(args), "orbit": args.orbit,
                "cam_dist": args.cam_dist, "cam_fov": args.cam_fov,
                "cam_height": args.cam_height, "cam_side": args.cam_side,
                "cam_pitch": args.cam_pitch, "plain_bg": args.plain_bg,
                "width": CAPTURE_WIDTH, "rise": args.rise,
                "bag": args.bag, "bag_color": args.bag_color,
                "bag_pos": args.bag_pos, "kirby_copy": args.kirby_copy,
                "input_at": args.input_at, "turbo": args.turbo,
            },
            "kept_run_dirs": kept, "targets": results,
        }
        (out_dir / "batch.json").write_text(json.dumps(manifest, indent=2))
        log("")
        for r in results:
            log(f"  {r['status']:8s} {r['id']:24s} "
                f"{len(r['images']):3d} img {r['seconds']:6.1f}s"
                + ("  [cached]" if r.get("cached") else "")
                + (f"  ** {r['subject_missing']} subject-not-drawn **"
                   if r.get("subject_missing") else "")
                + (f"  [{r['autofit_refits']} re-framed]"
                   if r.get("autofit_refits") else "")
                + (f"  ** {r['unproven_fresh']} unproven-fresh **"
                   if r.get("unproven_fresh") else "")
                + (f"  -- {r['reason']}" if r["reason"] else ""))
        log(f"\n{ok}/{len(results)} targets ok, {shots_n} images, {boots} boot(s), "
            f"{cached_n} target(s) served from the control cache, "
            f"{total:.1f}s total = {total / max(1, len(results)):.1f}s/target")
        log(f"manifest -> {out_dir / 'batch.json'}")
    log(f"done -> {out_dir}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
