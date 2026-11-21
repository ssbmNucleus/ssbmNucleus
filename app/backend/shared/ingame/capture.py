"""
capture.py -- take a clean in-game SCREENSHOT of a stage with the harness.

Boots a freshly-built ISO in the isolated throwaway Dolphin (boot.py), then poses
everything DIRECTLY via WriteProcessMemory (the same path force_select uses) -- no
Dolphin gecko engine (Slippi ignores user codes) and no fragile cursor/stick
framing:

  * clean-shot RAM patches: invisible fighters, no HUD/shadows/screen-shake;
  * 1-PLAYER start: relax the CSS "Ready to Fight" gate (0x80263064 cmpwi r31,2
    -> r31,1) so we load in ALONE -- nothing can attack/SD/move the camera;
  * Time mode + no time limit so a solo match doesn't instantly end;
  * DEBUG_FREE camera (mode 8) posed by direct writes for a deterministic
    whole-stage frame (mode 8 has no per-frame callback, so the writes stick).

The user's Slippi setup is never touched (throwaway User dir + per-process writes).
The CSS analog for stages: like a CSP for a character, but rendered live.

RE addresses are NTSC 1.02 (doldecomp/melee): the 1-player gate in mncharsel
fn_80262F44; GameRules at 0x8045BF10; the Camera struct at 0x80452C68 +
CameraDebugMode at 0x80453004.
"""

import time

from .boot import DOLPHIN_OPEN_MSG, DolphinBoot, wait_until_no_dolphin
from .melee_mem import Dolphin
from .melee_css import Cursor
from .melee_sss import StageCursor
from . import nav
from . import match_setup
from . import screenshot as _screenshot
from .observe import wait_in_game, wait_game_frames, FRAME_COUNTER
from .runner import _lock_vanilla, _ensure_on_sss, _memory_select_to_sss

CKIND_FOX = 0x02   # external char id; the fighter is invisible for the shot anyway


def _noop(*_a, **_k):
    pass


# How long a capture's Dolphin may live (DolphinBoot's `deadline`). A capture
# takes well under a minute, and these sit above the sum of the time limits its
# waits already have, so only a run that has stopped moving reaches one.
CAPTURE_DEADLINE = 300.0     # boot, menus, one stage load, one shot
VARIANT_DEADLINE = 60.0      # each further stage load in a batch
SHOT_DEADLINE = 5.0          # each further camera in a sweep


def _note_deadline(boot, result, log=_noop):
    """A capture whose Dolphin was ended at its deadline says so, in place of
    whichever step happened to notice the Dolphin was gone. A single shot that
    was already taken when the timer fired keeps its own result."""
    if not getattr(boot, "timed_out", False):      # a stand-in boot that knows no deadline never reached one
        return
    result["timedOut"] = True
    if result.get("ok") and "shots" not in result:
        return
    log(f"ended at the deadline; the run's own reason was: {result.get('reason')!r}")
    result["reason"] = ("Dolphin stopped responding, so the capture was ended "
                        f"after {float(boot.deadline):.0f} seconds.")


def _await_dolphin_clear(result, emit, log=_noop, stop_event=None):
    """An already-open Dolphin steals the foreground from our throwaway one,
    so menu inputs go nowhere and the run dies with a confusing pipe/menu
    timeout. WAIT for the user to close it (the progress message tells them
    to), continuing automatically. Mutates+returns `result` only when the
    wait timed out or was stopped; returns None when clear to boot.

    stop_event (each capture's too) is its job's stop: it ends this wait, and
    the Dolphin boot's lock queue, launch and pipe waits, at once."""
    if wait_until_no_dolphin(emit, log=log, stop_event=stop_event):
        return None
    result['reason'] = DOLPHIN_OPEN_MSG
    result['dolphinOpen'] = True
    result['systemic'] = True
    return result


# --- clean-shot RAM patches (gecko "04" codes as plain 32-bit writes) ----------
CODE_PATCHES = [
    (0x80030384, 0x60000000),   # Character Models Invisible [UnclePunch]
    (0x800872F8, 0x38600000),   # No Character Shadows [Altimor]
    (0x800304C4, 0x60000000),   # Disable Camera and Item Spawn Overlay (1)
    (0x8005A634, 0x48000094),   # Disable Camera and Item Spawn Overlay (2)
    (0x802275F8, 0x480000F0),   # Disable DPad Up Camera Changes
    (0x80030E44, 0x4E800020),   # Disable Screen Shake [Achilles1515]
]
HUD_FLAG_ADDR = 0x804D6D58       # 8-bit "remove HUD" flag (re-asserted before shot)

# 1-player start + Time/no-timer come from match_setup (shared with the runner).

# --- camera (Camera 0x80452C68 + CameraDebugMode 0x80453004) -------------------
CAMERA_MODE = 0x80452C6C         # CameraType; 8 = DEBUG_FREE (no per-frame cb)
CAMERA_FARZ = 0x80452C78
CAM_STD_INT = 0x80452C7C         # live STANDARD interest (read for calibration)
CAM_STD_EYE = 0x80452C94         # live STANDARD eye
CAM_STD_FOV = 0x80452CAC
CAM_DBG_INT = 0x80453040         # DEBUG_FREE look-at Vec3
CAM_DBG_EYE = 0x8045304C         # DEBUG_FREE eye Vec3
CAM_DBG_FOV = 0x80453058         # DEBUG_FREE fov (degrees)
CAMERA_DEBUG_FREE = 8

# Per-base-stage camera framing (eye, interest, fov). Calibrated 2026-06-11 via
# _cap_calibrate.py sweeps (one boot per stage, candidates eyeballed). An absent
# stage falls back to DEFAULT_FRAMING. Keyed by the INTERNAL_STAGE_ID name.
DEFAULT_FRAMING = {"eye": (0.0, 20.0, 450.0), "interest": (0.0, 8.0, 0.0), "fov": 40.0}
STAGE_FRAMING = {
    "battlefield": {"eye": (0.0, 35.7, 189.5), "interest": (0.0, 29.7, 0.0), "fov": 40.0},
    "finaldestination": {"eye": (0.0, 14.0, 237.1), "interest": (0.0, 8.0, 0.0), "fov": 40.0},
    "dreamland": {"eye": (0.0, 34.2, 214.1), "interest": (0.0, 28.2, 0.0), "fov": 40.0},
    "yoshisstory": {"eye": (0.0, 29.5, 201.7), "interest": (0.0, 23.5, 0.0), "fov": 40.0},
    "fountainofdreams": {"eye": (0.0, 29.9, 175.3), "interest": (0.0, 23.9, 0.0), "fov": 40.0},
    "pokemonstadium": {"eye": (0.0, 65.0, 310.0), "interest": (0.0, 8.0, 0.0), "fov": 40.0},
}

# Pokemon Stadium transformation control used by the single-client stage-shot
# harness. Patch the RNG call before the match loads, then wait for the real
# stage timer/loader to reach the requested settled form. This exercises the
# same GrPs1-4 load path as normal gameplay without involving matchmaking.
STADIUM_RNG_CALL = 0x801D463C
STADIUM_GOBJ_TABLE = 0x8049E6C8 + 0x180
STADIUM_GOBJ_USER_DATA = 0x2C
STADIUM_GROUND_STATE = 0xDC
STADIUM_GROUND_FORM = 0xDE
STADIUM_FORM_INDEX = {"fire": 0, "grass": 1, "rock": 2, "water": 3}
STADIUM_FORM_ID = {"fire": 3, "grass": 4, "rock": 6, "water": 9}
STADIUM_NORMAL_FORM = 5
# grStadium_GroundVars (gr/types.h): gp+D8 int idle countdown, gp+E2 s16 the
# "don't repeat the last form" guard.
STADIUM_GROUND_TIMER = 0xD8
STADIUM_GROUND_PREV2 = 0xE2
_STADIUM_NAME_BY_ID = {v: k for k, v in STADIUM_FORM_ID.items()}
_STADIUM_NAME_BY_ID[STADIUM_NORMAL_FORM] = "normal"


def _force_stadium_form(d, form_name, log=_noop):
    if form_name not in STADIUM_FORM_INDEX:
        raise ValueError(f"unknown Stadium form: {form_name}")
    instruction = 0x38600000 | STADIUM_FORM_INDEX[form_name]  # li r3,index
    if not d.write_u32(STADIUM_RNG_CALL, instruction):
        raise RuntimeError(f"could not force Stadium {form_name}")
    log(f"Stadium will select {form_name} (form {STADIUM_FORM_ID[form_name]})")


def _stadium_form_states(d):
    """Find the Stadium controller in StageInfo's ground-GObj table.

    Its slot is not stable between offline solo VS and online Direct.  Identify
    it by the controller's compact form/state fields instead of assuming the
    online slot (2).  Return (slot, form, state) candidates.
    """
    found = []
    for slot in range(64):
        gobj = d.u32(STADIUM_GOBJ_TABLE + slot * 4)
        if not gobj or not 0x80000000 <= gobj < 0x81800000:
            continue
        ground = d.u32(gobj + STADIUM_GOBJ_USER_DATA)
        if not ground or not 0x80000000 <= ground < 0x81800000:
            continue
        form = d.u16(ground + STADIUM_GROUND_FORM)
        state = d.u16(ground + STADIUM_GROUND_STATE)
        if form is not None and state is not None and 3 <= form <= 9 and state < 64:
            found.append((slot, form, state))
    return found


def _stadium_form_state(d, expected=None):
    states = _stadium_form_states(d)
    if expected is not None:
        for _slot, form, state in states:
            if form == expected:
                return form, state
    return states[0][1:] if states else (None, None)


def _wait_stadium_form(d, form_name, timeout=150.0, log=_noop):
    expected = STADIUM_FORM_ID[form_name]
    deadline = time.time() + timeout
    last = object()
    initial = None
    transitioned = False
    while time.time() < deadline and d.alive():
        states = _stadium_form_states(d)
        current = _stadium_form_state(d, expected=expected)
        if initial is None and current != (None, None):
            initial = current
        if initial is not None and current[1] not in (None, 0):
            transitioned = True
        if current != last:
            log(f"Stadium form/state -> {current}; candidates={states}")
            last = current
        # Require evidence that the real transition animation started before
        # accepting a settled target, otherwise a queued target can be captured
        # before its geometry has finished changing.
        if current == (expected, 0) and transitioned:
            return current
        time.sleep(0.1)
    current = _stadium_form_state(d, expected=expected)
    # A target form id can be queued even when its archive upload has hung.
    # Do not accept that id as settled without observing animation states.
    return current if transitioned else (current[0], -1)


def _stadium_controller(d, timeout=10.0, log=_noop):
    """Resolve the transformation controller ONCE and keep using it.

    Several ground GObjs pass the loose form/state filter, so re-resolving per
    call can read state from one object and write the timer to another. The
    controller is the one sitting at the normal form (5) or a transformation id
    while idle; cache whatever we settle on for the rest of the capture.
    """
    deadline = time.time() + timeout
    while time.time() < deadline and d.alive():
        for slot in range(64):
            gobj = d.u32(STADIUM_GOBJ_TABLE + slot * 4)
            if not gobj or not 0x80000000 <= gobj < 0x81800000:
                continue
            ground = d.u32(gobj + STADIUM_GOBJ_USER_DATA)
            if not ground or not 0x80000000 <= ground < 0x81800000:
                continue
            form = d.u16(ground + STADIUM_GROUND_FORM)
            state = d.u16(ground + STADIUM_GROUND_STATE)
            if form is None or state is None:
                continue
            if form in (STADIUM_NORMAL_FORM, *STADIUM_FORM_ID.values()) and state < 64:
                log(f"Stadium controller at slot {slot} "
                    f"(ground=0x{ground:08X}, form={form}, state={state})")
                return ground
        time.sleep(0.1)
    return None


def _stadium_wait_idle(d, ground, timeout=30.0):
    """Block until the controller is out of its transition animation."""
    deadline = time.time() + timeout
    while time.time() < deadline and d.alive():
        if d.u16(ground + STADIUM_GROUND_STATE) == 0:
            return (d.u16(ground + STADIUM_GROUND_FORM), 0)
        time.sleep(0.05)
    return (d.u16(ground + STADIUM_GROUND_FORM),
            d.u16(ground + STADIUM_GROUND_STATE))


def _stadium_cycle(d, ground, wanted, on_form, timeout=180.0, log=_noop):
    """Cycle Stadium and hand each wanted form to `on_form` as it appears.

    We deliberately do NOT force which form comes up. The form is chosen inside
    case 0 by `sp60[HSD_Randi(4)]`, and the harness forces that by rewriting the
    call site -- which only works if the patch lands BEFORE Dolphin's JIT has
    compiled the block, i.e. before the stage loads. Mid-match the write is
    invisible to the recompiler, so a "forced" form is really just a random one.

    Instead: make each cycle cheap by expiring the idle timer, and collect forms
    opportunistically. The engine alternates normal -> transformation -> normal,
    and its own `while (xE2 == pick)` guard prevents immediate repeats, so the
    four fill in quickly.
    """
    remaining = set(wanted)
    deadline = time.time() + timeout
    seen_log = []
    while remaining and time.time() < deadline and d.alive():
        form, state = _stadium_wait_idle(d, ground)
        if state != 0:
            break
        name = _STADIUM_NAME_BY_ID.get(form)
        # Record BEFORE the capture branch: capturing the last wanted form
        # breaks out of the loop, so appending afterwards silently omitted every
        # form we actually took a shot of -- the summary then read as if the
        # requested form was never reached.
        seen_log.append(form)
        if name and name in remaining:
            log(f"Stadium reached {name} (form {form}) -- capturing")
            on_form(name)
            remaining.discard(name)
            if not remaining:
                break
        # Bias the next roll away from something we already have.
        done_ids = [STADIUM_FORM_ID[n] for n in wanted if n not in remaining
                    and n in STADIUM_FORM_ID]
        if done_ids:
            d.write_u16(ground + STADIUM_GROUND_PREV2, done_ids[-1])
        else:
            d.write_u16(ground + STADIUM_GROUND_PREV2, 0xFFFF)
        d.write_u32(ground + STADIUM_GROUND_TIMER, 0xFFFFFFFF)   # xD8 = -1
        time.sleep(0.15)
    log(f"Stadium cycle visited forms {seen_log}; missed {sorted(remaining)}")
    return remaining


def _apply_code_patches(d, log=_noop):
    ok = sum(1 for addr, val in CODE_PATCHES if d.write_u32(addr, val))
    log(f"applied {ok}/{len(CODE_PATCHES)} capture patches")
    return ok


def _read_vec3(d, addr):
    return (d.f32(addr), d.f32(addr + 4), d.f32(addr + 8))


def _write_vec3(d, addr, v):
    d.write_f32(addr, float(v[0]))
    d.write_f32(addr + 4, float(v[1]))
    d.write_f32(addr + 8, float(v[2]))


def _set_free_camera(d, eye, interest, fov):
    """Pose the camera deterministically via DEBUG_FREE (mode 8), which reads
    these fields directly with no smoothing/clamping/recompute."""
    d.write_u32(CAMERA_MODE, CAMERA_DEBUG_FREE)
    _write_vec3(d, CAM_DBG_INT, interest)
    _write_vec3(d, CAM_DBG_EYE, eye)
    d.write_f32(CAM_DBG_FOV, float(fov))
    d.write_f32(CAMERA_FARZ, 16384.0)   # avoid clipping the back of the stage


def capture_stage(iso_path, slippi_path, runs_root, internal_id, hold=None,
                  framing_key=None, emit=None, log=None, settle=4.0,
                  hires_textures=False, framing_sweep=None,
                  stadium_form=None, stadium_timeout=150.0,
                  stadium_forms=None, render_size=None, internal_res=None,
                  stop_event=None, deadline=None):
    """Boot the ISO, load the stage ALONE in a no-timer Time match (internal_id,
    holding `hold` for a DAS variant), pose the camera, and return
    {"ok": bool, "png": bytes|None, "reason": str}.

    deadline: seconds the Dolphin may live before it is ended and the capture
    fails with "timedOut" (default: CAPTURE_DEADLINE plus what the requested
    Stadium forms and sweep cameras are allowed).

    framing_key selects a per-base-stage camera preset (STAGE_FRAMING).
    framing_sweep (calibration): a list of framing dicts -- one boot, one shot
    per framing; returns {"ok", "shots": [{"framing", "png", "reason"}]}.

    render_size (w, h) enlarges the render window, which IS the shot resolution;
    internal_res renders at that multiple of native and downsamples into it."""
    emit = emit or _noop
    log = log or _noop
    result = {"ok": False, "png": None, "reason": ""}
    if _await_dolphin_clear(result, emit, log, stop_event):
        return result

    shot_width = render_size[0] if render_size else 960
    if deadline is None:
        deadline = CAPTURE_DEADLINE + SHOT_DEADLINE * len(framing_sweep or ())
        if stadium_forms:        # the cycle's own budget, as given to it below
            deadline += 10.0 + max(60.0, 2.5 * stadium_timeout * len(stadium_forms))
        elif stadium_form:
            deadline += stadium_timeout
    boot = DolphinBoot(iso_path, slippi_path, runs_root,
                       hires_textures=hires_textures, clean_osd=True,
                       render_size=render_size, internal_res=internal_res,
                       log=log, stop_event=stop_event, deadline=deadline)
    p = None
    try:
        emit("booting", 10, "Preparing an isolated Dolphin (capture mode)…")
        boot.prepare()
        boot.launch()
        emit("booting", 20, "Waiting for the controller pipe…")
        if not boot.wait_for_pipe(timeout=45):
            result["reason"] = "Dolphin never opened its input pipe."
            return result

        emit("booting", 28, "Attaching to emulated memory…")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            if not d.alive():
                result["reason"] = "Dolphin exited during boot."
                return result
            time.sleep(0.4)
        if d.base is None:
            result["reason"] = "Could not read the game's memory after boot."
            return result

        _apply_code_patches(d, log=log)               # clean-shot patches (persist)
        if stadium_form:
            _force_stadium_form(d, stadium_form, log=log)
        solo = match_setup.patch_one_player(d, log=log)  # load in alone if possible

        try:
            p = boot.open_pipe()
        except OSError as e:
            log(f"controller pipe never reopened: {e}")
            result["reason"] = ("Dolphin's controller pipe didn't come back up "
                                "(it may have been mid-restart) — please retry.")
            return result
        cur = Cursor(d, p)
        sc = StageCursor(d, p)

        emit("at_css", 40, "Navigating to the character-select screen…")
        try:
            if not nav.nav_to_css(d, p, log=log):
                result["reason"] = "Could not reach the character-select screen."
                return result
        except nav.OnlineAbort as oa:
            result["reason"] = str(oa)
            return result
        nav.wait_css_ready(d, cur, log=log)
        match_setup.force_time_infinite(d, log=log)   # so a solo match persists

        emit("selecting_stage", 55, "Loading the stage…")
        # Primary: cursor-free memory selection (write a solo Fox + warp CSS->SSS).
        # The fighter is invisible for the shot, so any vanilla fighter works -- this
        # just skips the cursor lock + START. Falls back to the cursor path if we
        # couldn't load solo or the warp didn't land (then we're still on the CSS).
        on_sss = _memory_select_to_sss(d, sc, CKIND_FOX, 0, log) if solo else False
        if not on_sss:
            if not solo:
                nav.add_cpu(d, p, cur=cur, log=log)  # fallback: need a 2nd player
            _lock_vanilla(cur, "fox", 0)
            # Reach the stage-select screen (START from the locked CSS). With the
            # 1-player patch this works solo; otherwise the added CPU satisfies it.
            if not sc.ensure_stage_select():
                if not (not solo and _ensure_on_sss(d, p, sc, cur, log)):
                    result["reason"] = "Could not reach the stage-select screen."
                    return result
        p.neutral()                  # start from a clean controller state before the held load
        time.sleep(0.15)
        if not sc.force_select(internal_id, hold=hold):
            result["reason"] = "Could not start the match on the stage."
            return result

        emit("framing", 75, "Waiting for the stage to finish loading…")
        if stadium_forms:
            # All requested forms from ONE boot: booting is the expensive part,
            # and each transformation is forced rather than waited out.
            if not wait_in_game(d, timeout=30.0, log=log):
                result["reason"] = "stage never finished loading into a match"
                return result
            ground = _stadium_controller(d, log=log)
            if ground is None:
                result["reason"] = "Stadium transformation controller not found"
                return result
            fr = STAGE_FRAMING.get(framing_key, DEFAULT_FRAMING)
            shots = []
            taken = {}

            def _grab(name):
                pct = 78 + int(18 * len(taken) / max(len(stadium_forms), 1))
                emit("transforming", pct, f"Capturing {name}…")
                png, reason = _frame_and_shot(
                    boot, d, fr, settle=settle if not taken else 0.7, log=log,
                    max_width=shot_width)
                taken[name] = {"form": name, "png": png, "reason": reason}

            # stadium_timeout is a per-form settle budget; the cycle has to
            # cover every requested form plus the normal form the engine forces
            # in between, and each capture costs a few seconds of its own. Give
            # it a budget that scales, or a short --timeout silently truncates
            # the run and reports the tail as "never came up".
            missed = _stadium_cycle(d, ground, stadium_forms, _grab,
                                    timeout=max(60.0, 2.5 * stadium_timeout
                                                * len(stadium_forms)),
                                    log=log)
            for name in stadium_forms:
                shots.append(taken.get(name, {
                    "form": name, "png": None,
                    "reason": "form never came up during the cycle"}))
            result["stadiumMissed"] = sorted(missed)
            result["ok"] = any(s["png"] for s in shots)
            result["shots"] = shots
            result["reason"] = "forms"
            result["solo"] = solo
            return result
        if stadium_form:
            if not wait_in_game(d, timeout=30.0, log=log):
                result["reason"] = "stage never finished loading into a match"
                return result
            emit("transforming", 82,
                 f"Waiting for the {stadium_form} transformation")
            observed = _wait_stadium_form(
                d, stadium_form, timeout=stadium_timeout, log=log)
            result["stadium"] = {
                "requested": stadium_form,
                "expectedForm": STADIUM_FORM_ID[stadium_form],
                "observedForm": observed[0],
                "observedState": observed[1],
            }
            if observed != (STADIUM_FORM_ID[stadium_form], 0):
                result["reason"] = (f"Stadium {stadium_form} never settled "
                                    f"(form/state={observed})")
                # Preserve visual evidence for selector/controller diagnostics.
                # This is especially useful when the scene flag says in-game
                # but the expected Stadium controller never materializes.
                if framing_sweep is not None:
                    shots = []
                    for fr in framing_sweep:
                        png, reason = _frame_and_shot(
                            boot, d, fr, settle=0.2, log=log,
                            max_width=shot_width)
                        shots.append({"framing": fr, "png": png,
                                      "reason": reason})
                    result["shots"] = shots
                return result
            # The transformation is already settled; only hold the clean pose
            # briefly before each screenshot.
            settle = min(settle, 0.7)
        if framing_sweep is not None:
            # calibration mode: one boot, many camera candidates. The camera is
            # deterministic (DEBUG_FREE, no per-frame recompute), so after the
            # first settled shot each new framing only needs a short hold.
            shots = []
            for i, fr in enumerate(framing_sweep):
                emit("capturing", 90, f"Sweep shot {i + 1}/{len(framing_sweep)}…")
                png, reason = _frame_and_shot(boot, d, fr,
                                              settle=settle if i == 0 else 0.7,
                                              log=log, max_width=shot_width)
                shots.append({"framing": fr, "png": png, "reason": reason})
            result["ok"] = any(s["png"] for s in shots)
            result["shots"] = shots
            result["reason"] = "sweep"
            result["solo"] = solo
            return result
        fr = STAGE_FRAMING.get(framing_key, DEFAULT_FRAMING)
        emit("capturing", 90, "Capturing the screenshot…")
        png, reason = _frame_and_shot(boot, d, fr, settle=settle, log=log,
                                      max_width=shot_width)
        if not png:
            result["reason"] = reason
            return result
        result["ok"] = True
        result["png"] = png
        result["reason"] = "captured"
        result["solo"] = solo
        return result
    except Exception as e:
        result["reason"] = f"{type(e).__name__}: {e}"
        return result
    finally:
        try:
            if p is not None:
                p.close()
        except Exception:
            pass
        boot.cleanup()
        _note_deadline(boot, result, log)


def _hold_clean_pose(d, fr, frames=12):
    """Re-assert the DEBUG_FREE camera + clean-shot patches + HUD-off flag over
    `frames` real GAME frames right before the grab. DEBUG_FREE has no per-frame
    callback so the camera sticks, but the HUD flag is re-read every frame -- so
    we keep asserting it, counted in GAME frames (not wall-clock) so a slow
    machine can't grab the frame before the HUD-off flag has taken effect."""
    last = d.u32(FRAME_COUNTER)
    advanced = 0
    deadline = time.time() + max(1.5, frames / 10.0 + 1.0)
    while advanced < frames and time.time() < deadline and d.alive():
        _set_free_camera(d, fr["eye"], fr["interest"], fr["fov"])
        _apply_code_patches(d)
        d.write_u8(HUD_FLAG_ADDR, 0x01)
        f = d.u32(FRAME_COUNTER)
        if f is not None and last is not None:
            if f > last:
                advanced += f - last
            last = f
        time.sleep(0.008)


def _frame_and_shot(boot, d, fr, settle=4.0, log=_noop, max_width=960):
    """Wait for the match to actually be IN-GAME (absorbs host-variable stage load
    time), then wait a fixed number of GAME frames past the intro zoom -- both
    read from the game's own RAM, so this is host-SPEED independent (a slow
    Dolphin just takes more wall-clock for the same game frames; the old fixed
    time.sleep() grabbed too early on a slow machine). Then pose the DEBUG_FREE
    camera + re-assert the clean-shot state and grab. The scene is static (solo,
    no timer, frozen camera) so the frame is stable. Returns (png_bytes, reason);
    png_bytes is None on failure."""
    if not wait_in_game(d, timeout=30.0, log=log):
        return None, "stage never finished loading into a match"
    wait_game_frames(d, max(1, round(settle * 60)), log=log)   # past the GO! intro zoom
    log(f"default cam eye={_read_vec3(d, CAM_STD_EYE)} "
        f"interest={_read_vec3(d, CAM_STD_INT)} fov={d.f32(CAM_STD_FOV)}")
    _hold_clean_pose(d, fr)
    if not d.alive():
        return None, "Dolphin exited before the screenshot"

    # Grab the render window's own pixels (PrintWindow) -- clean even though the
    # throwaway Dolphin never takes the foreground. _hold_clean_pose just asserted
    # the DEBUG_FREE camera + HUD-off over the last frames, and the scene is static
    # (solo, no timer, frozen camera), so the grabbed frame is clean and stable.
    png = _screenshot.capture_via_printwindow(boot.pid, max_width=max_width)
    if not png:  # last resort: desktop grab of the window rect
        png = _screenshot.capture_png(boot.pid, max_width=max_width)
    if not png:
        return None, "screenshot capture returned no image"
    return png, "captured"


PAUSE_STAGE_INTERNAL_ID = 0x1F   # Battlefield: dark backdrop shows the light pause graphics


def _pause_match(d, p, tries=3, log=_noop):
    """Pause the running match by tapping START. Pausing hands the camera to the
    pause controller, so a CameraType change away from its in-match value is the
    confirmation signal (the global frame counter does NOT freeze on pause).
    Returns True when the switch was observed; the caller may still proceed
    optimistically on False -- a missed read just means we couldn't confirm."""
    m0 = d.u32(CAMERA_MODE)
    for attempt in range(1, tries + 1):
        p.tap("START", hold=0.08)
        deadline = time.time() + 1.2
        while time.time() < deadline and d.alive():
            m = d.u32(CAMERA_MODE)
            if m is not None and m0 is not None and m != m0:
                log(f"paused (camera mode {m0} -> {m}) on tap {attempt}")
                return True
            time.sleep(0.05)
        log(f"pause tap {attempt}: camera mode unchanged ({m0})")
    return False


def capture_pause(iso_path, slippi_path, runs_root, emit=None, log=None, settle=2.0,
                  internal_id=PAUSE_STAGE_INTERNAL_ID, stop_event=None,
                  deadline=CAPTURE_DEADLINE):
    """Boot the ISO, load a stage ALONE (invisible fighter, no timer), PAUSE the
    match, and screenshot the pause overlay -- the live preview for a pause
    screen mod. Same clean-shot setup as capture_stage but WITHOUT the HUD-off
    flag or the DEBUG_FREE camera: the pause overlay IS the subject, and pausing
    runs its own camera. Returns {"ok": bool, "png": bytes|None, "reason": str}.
    `deadline`: seconds the Dolphin may live before it is ended and the capture
    fails with "timedOut"."""
    emit = emit or _noop
    log = log or _noop
    result = {"ok": False, "png": None, "reason": ""}
    if _await_dolphin_clear(result, emit, log, stop_event):
        return result

    boot = DolphinBoot(iso_path, slippi_path, runs_root, clean_osd=True, log=log,
                       stop_event=stop_event, deadline=deadline)
    p = None
    try:
        emit("booting", 10, "Preparing an isolated Dolphin (capture mode)…")
        boot.prepare()
        boot.launch()
        emit("booting", 20, "Waiting for the controller pipe…")
        if not boot.wait_for_pipe(timeout=45):
            result["reason"] = "Dolphin never opened its input pipe."
            return result

        emit("booting", 28, "Attaching to emulated memory…")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            if not d.alive():
                result["reason"] = "Dolphin exited during boot."
                return result
            time.sleep(0.4)
        if d.base is None:
            result["reason"] = "Could not read the game's memory after boot."
            return result

        # NO clean-shot code patches here: the pause preview should look like a
        # real paused game -- visible fighter, shadows, and the in-match HUD
        # behind the overlay. (The stage capture's invisible-fighter/HUD-off
        # patches made the pause shot look empty.)
        solo = match_setup.patch_one_player(d, log=log)

        try:
            p = boot.open_pipe()
        except OSError as e:
            log(f"controller pipe never reopened: {e}")
            result["reason"] = ("Dolphin's controller pipe didn't come back up "
                                "(it may have been mid-restart) — please retry.")
            return result
        cur = Cursor(d, p)
        sc = StageCursor(d, p)

        emit("at_css", 40, "Navigating to the character-select screen…")
        try:
            if not nav.nav_to_css(d, p, log=log):
                result["reason"] = "Could not reach the character-select screen."
                return result
        except nav.OnlineAbort as oa:
            result["reason"] = str(oa)
            return result
        nav.wait_css_ready(d, cur, log=log)
        match_setup.force_time_infinite(d, log=log)

        emit("selecting_stage", 55, "Loading the stage…")
        on_sss = _memory_select_to_sss(d, sc, CKIND_FOX, 0, log) if solo else False
        if not on_sss:
            if not solo:
                nav.add_cpu(d, p, cur=cur, log=log)
            _lock_vanilla(cur, "fox", 0)
            if not sc.ensure_stage_select():
                if not (not solo and _ensure_on_sss(d, p, sc, cur, log)):
                    result["reason"] = "Could not reach the stage-select screen."
                    return result
        p.neutral()
        time.sleep(0.15)
        if not sc.force_select(internal_id):
            result["reason"] = "Could not start the match."
            return result

        emit("framing", 75, "Waiting for the stage to finish loading…")
        if not wait_in_game(d, timeout=30.0, log=log):
            result["reason"] = "stage never finished loading into a match"
            return result
        wait_game_frames(d, max(1, round(settle * 60)), log=log)   # past the GO! intro zoom

        emit("capturing", 85, "Pausing the match…")
        paused = _pause_match(d, p, log=log)
        if not paused:
            log("could not confirm the pause via camera mode; capturing anyway")
        time.sleep(1.0)                              # let the overlay fade-in finish
        if not d.alive():
            result["reason"] = "Dolphin exited before the screenshot"
            return result

        emit("capturing", 92, "Capturing the screenshot…")
        png = _screenshot.capture_via_printwindow(boot.pid, max_width=960)
        if not png:
            png = _screenshot.capture_png(boot.pid, max_width=960)
        if not png:
            result["reason"] = "screenshot capture returned no image"
            return result
        result["ok"] = True
        result["png"] = png
        result["reason"] = "captured"
        result["paused_confirmed"] = paused
        result["solo"] = solo
        return result
    except Exception as e:
        result["reason"] = f"{type(e).__name__}: {e}"
        return result
    finally:
        try:
            if p is not None:
                p.close()
        except Exception:
            pass
        boot.cleanup()
        _note_deadline(boot, result, log)


def _start_if_ready(sc):
    """Press START once; True if that reached the stage-select screen. START only
    leaves a CSS that is ready, so this is the game's own answer to "is a fighter
    already picked?". The CSS a match returns to has the last one picked, and
    _lock_vanilla's single A press there UN-picks it: on 2026-11-10 that turned
    one missed warp into a lost variant. Nothing read from RAM says it instead:
    nav.port_coin_down stays False on that CSS."""
    sc.p.tap("START", 0.06)
    return sc.wait_for_stage_select(timeout=1.5)


def _back_to_css(d, p, sc, log=_noop):
    """Between a batch's variants: back on a running CSS from wherever the last
    variant left the game. After a shot that is a running match, and the quit
    combo is right. A variant that was skipped never started one: it stopped on
    the CSS or on the stage-select screen, where the same buttons back out to
    the main menu and the rest of the boot is lost (seen 2026-11-10)."""
    if sc.on_stage_select():
        log("between variants: still on the stage-select screen; backing out with B")
        for _ in range(3):
            p.tap("B", 0.08)
            time.sleep(0.4)
            if nav.at_offline_css(d):
                break
    if nav.at_offline_css(d):
        return nav.wait_css_running(d, p)
    return nav.reset_to_css(d, p, log=log)


def capture_stage_batch(iso_path, slippi_path, runs_root, variants,
                        emit=None, log=None, settle=4.0, hires_textures=False,
                        stop_event=None, deadline=None):
    """Boot ONE ISO and screenshot many DAS variants -- possibly spanning SEVERAL
    base stages -- in a single session. Each variant carries its own stage + hold:
    `variants` = [{"id", "button", "internal_id", "framing_key"}] (as placed by
    build_stage_skin_multibatch_iso; `id` should be globally unique, e.g.
    "<stageCode>:<variantId>"). Build + boot happen once; between shots we quit to
    the CSS, re-enter, force-select that variant's stage holding its button.
    Returns {"ok": bool, "shots": [{"id","button","png"}],
    "failures": [{"id","button","reason"}], "reason": str,
    "systemic": bool}.

    deadline: seconds the Dolphin may live (default CAPTURE_DEADLINE plus
    VARIANT_DEADLINE per variant). A batch ended there reports "timedOut" and
    keeps the shots it already took; to the caller's retry it is a crash."""
    emit = emit or _noop
    log = log or _noop
    # crashed_id: the variant in-flight when Dolphin died, so the caller can
    # retry the SAME ISO with that one moved to the end (a single bad stage
    # otherwise blocks every variant queued behind it). None = no crash.
    result = {"ok": False, "shots": [], "failures": [], "reason": "",
              "crashed_id": None, "systemic": False}
    if _await_dolphin_clear(result, emit, log, stop_event):
        return result

    if deadline is None:
        deadline = CAPTURE_DEADLINE + VARIANT_DEADLINE * len(variants)
    boot = DolphinBoot(iso_path, slippi_path, runs_root,
                       hires_textures=hires_textures, clean_osd=True, log=log,
                       stop_event=stop_event, deadline=deadline)
    p = None
    try:
        emit("booting", 8, "Preparing an isolated Dolphin (capture mode)…")
        boot.prepare()
        boot.launch()
        emit("booting", 16, "Waiting for the controller pipe…")
        if not boot.wait_for_pipe(timeout=45):
            result["reason"] = "Dolphin never opened its input pipe."
            result["systemic"] = True
            return result

        emit("booting", 22, "Attaching to emulated memory…")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            if not d.alive():
                result["reason"] = "Dolphin exited during boot."
                result["systemic"] = True
                return result
            time.sleep(0.4)
        if d.base is None:
            result["reason"] = "Could not read the game's memory after boot."
            result["systemic"] = True
            return result

        _apply_code_patches(d, log=log)
        solo = match_setup.patch_one_player(d, log=log)
        try:
            p = boot.open_pipe()
        except OSError as e:
            log(f"controller pipe never reopened: {e}")
            result["systemic"] = True
            result["reason"] = ("Dolphin's controller pipe didn't come back up "
                                "(it may have been mid-restart) — please retry.")
            return result
        cur = Cursor(d, p)
        sc = StageCursor(d, p)

        emit("at_css", 26, "Navigating to the character-select screen…")
        try:
            if not nav.nav_to_css(d, p, log=log):
                result["reason"] = "Could not reach the character-select screen."
                result["systemic"] = True
                return result
        except nav.OnlineAbort as oa:
            result["reason"] = str(oa)
            result["systemic"] = True
            return result
        nav.wait_css_ready(d, cur, log=log)
        match_setup.force_time_infinite(d, log=log)

        n = len(variants)
        for i, v in enumerate(variants):
            vid, button = v["id"], v["button"]
            internal_id = v["internal_id"]
            fr = STAGE_FRAMING.get(v.get("framing_key"), DEFAULT_FRAMING)
            emit("capturing", 30 + int(60 * i / max(1, n)),
                 f"Capturing variant {i + 1}/{n}…")
            if i > 0:
                # Quit the previous match back to the CSS before the next variant.
                if not d.alive():
                    result["reason"] = "Dolphin exited mid-batch."
                    result["crashed_id"] = vid
                    break
                if not _back_to_css(d, p, sc, log):
                    reason = "Could not return to the CSS between variants."
                    result["failures"].append({"id": vid, "button": button, "reason": reason})
                    result["reason"] = reason
                    result["crashed_id"] = vid
                    break
            on_sss = _memory_select_to_sss(d, sc, CKIND_FOX, 0, log) if solo else False
            if not on_sss and not _start_if_ready(sc):
                # The cursor path, on a CSS that START does not leave: nothing
                # is picked on it yet (still on the CSS if the warp missed).
                if not solo:
                    nav.add_cpu(d, p, cur=cur, log=log)
                _lock_vanilla(cur, "fox", 0)
                if not sc.ensure_stage_select():
                    if not (not solo and _ensure_on_sss(d, p, sc, cur, log)):
                        reason = "Could not reach the stage-select screen."
                        result["failures"].append({"id": vid, "button": button, "reason": reason})
                        log(f"could not reach the SSS for {vid}; skipping")
                        continue
            p.neutral()              # clear any residual held button from the prior variant
            time.sleep(0.15)
            if not sc.force_select(internal_id, hold=button):
                reason = "Could not start the match on the stage."
                result["failures"].append({"id": vid, "button": button, "reason": reason})
                log(f"could not start the match for {vid} (hold {button}); skipping")
                continue
            png, reason = _frame_and_shot(boot, d, fr, settle=settle, log=log)
            if png:
                result["shots"].append({"id": vid, "button": button, "png": png})
                log(f"captured {vid} (hold {button})")
            else:
                result["failures"].append({"id": vid, "button": button, "reason": reason})
                log(f"screenshot failed for {vid}: {reason}")
            if not d.alive():
                result["reason"] = "Dolphin exited mid-batch."
                result["crashed_id"] = vid
                break

        result["ok"] = len(result["shots"]) > 0
        if not result["reason"]:
            result["reason"] = f"captured {len(result['shots'])}/{n}"
        return result
    except Exception as e:
        result["reason"] = f"{type(e).__name__}: {e}"
        return result
    finally:
        try:
            if p is not None:
                p.close()
        except Exception:
            pass
        boot.cleanup()
        _note_deadline(boot, result, log)
