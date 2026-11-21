"""Playable one-match previews, using real controller port 1 until Stop.

The automation pipe occupies port 4 only during menu navigation. The user's
port-1 device and mappings are copied unchanged into the isolated profile.
No controller connection is inferred from those settings.
"""

import threading
import time

from .boot import DolphinBoot, DolphinBootCancelled
from .boot_errors import DolphinGraphicsError
from .melee_mem import Dolphin
from .melee_sss import StageCursor
from . import match_setup, nav
from .observe import FRAME_COUNTER, is_in_game


class _PreviewClosed(RuntimeError):
    pass


def preview_plan(manifest):
    """Choose the requested fighter on Battlefield, or Mario on a stage."""
    from .char_select import ckind
    manifest = manifest or {}
    character = manifest.get("character") or {}
    costume = manifest.get("costume") or {}
    effect = manifest.get("effect") or {}
    custom_stage = manifest.get("customStage") or {}
    das = manifest.get("das") or {}
    stage = {"kind": "name", "name": "battlefield"}
    fighter, color, name = ckind("mario"), 0, "Mario"
    if character:
        fighter = (character.get("cssIcon") or {}).get("fighter")
        color = int(character.get("colorIndex", 0) or 0)
        name = character.get("name") or "Selected character"
    elif costume or effect:
        selected = costume or effect
        name = selected.get("fighter") or ""
        fighter = ckind(name)
        color = int(costume.get("colorIndex", 0) or 0)
    elif custom_stage:
        stage = {"kind": "icon", "stageId": (custom_stage.get("sssIcon") or {}).get("stageId")}
    elif das:
        if not das.get("defaultVariant"):
            raise ValueError("Playable stage previews require the selected skin as the "
                             "default variant in the temporary test build.")
        stage = {"kind": "name", "name": das.get("stage", "battlefield")}
    if not isinstance(fighter, int) or isinstance(fighter, bool) or not 0 <= fighter <= 0x7F:
        raise ValueError("The test build did not identify the selected fighter. Rebuild its preview.")
    if not 0 <= color <= 255:
        raise ValueError("The selected costume index is invalid.")
    from .runner import _internal_stage_id
    stage_id = _internal_stage_id(stage)
    if stage_id is None:
        raise ValueError("The test build did not identify the selected stage. Rebuild its preview.")
    return {"fighter": fighter, "color": color, "name": name,
            "stage_id": stage_id, "hold": None}


class _Guarded:
    """Check cancellation at each existing RAM/pipe operation during setup."""
    def __init__(self, target, check):
        self._target, self._check = target, check

    def __getattr__(self, name):
        value = getattr(self._target, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            self._check()
            result = value(*args, **kwargs)
            self._check()
            return result
        return call


def _wait_css_initialized(memory, pipe, stop_event, check, log, timeout=15.0):
    """Wait for the automation port's CSS hand and 90 emulated settle frames.

    The scene flag changes before CSS initialization finishes. Writing the
    player block/scene transition then can be overwritten by initialization.
    Port 4 is our connected pipe; port 1 need not have a connected controller
    yet. A pointer replacement or frame reset restarts the settle interval.
    """
    deadline = time.monotonic() + timeout
    cursor = first_frame = previous_frame = None
    while time.monotonic() < deadline:
        check()
        nav._guard_online(memory, pipe)
        if not nav.at_offline_css(memory):
            log("Playable preview left offline CSS before initialization finished")
            return False
        current_cursor = memory.deref(nav.CSS_CURSOR_PTR + 4 * 3)
        frame = memory.u32(FRAME_COUNTER)
        if current_cursor is None or frame is None:
            cursor = first_frame = previous_frame = None
        else:
            if current_cursor != cursor or previous_frame is None or frame < previous_frame:
                cursor, first_frame = current_cursor, frame
            previous_frame = frame
            if frame - first_frame >= 90:
                log("Playable preview CSS initialized; port-4 hand settled for 90 game frames")
                return True
        stop_event.wait(0.05)
    check()
    log("Playable preview CSS initialization timed out before fighter selection")
    return False


def run_interactive_test(iso_path, slippi_path, runs_root, manifest=None,
                         emit=None, log=None, hires_textures=False, load_seed=None,
                         stop_event=None, on_interactive_state=None):
    emit = emit or (lambda *_: None)
    log = log or (lambda *_: None)
    state = on_interactive_state or (lambda _: None)
    stop_event = stop_event if stop_event is not None else threading.Event()
    result = {"interactive": True, "success": False, "pass": False,
              "verdict": "error", "reason": "", "controllerPort": 1}
    # A playable session is captured into the app's preview at whatever size
    # the panel gives it, so render big and supersample: a 640x480 window
    # just looked like a small window blown up.
    boot = DolphinBoot(iso_path, slippi_path, runs_root, interactive=True,
                       stop_event=stop_event, hires_textures=hires_textures,
                       load_seed=load_seed, render_size=(1280, 960), internal_res=2,
                       log=log)
    raw_pipe = None
    raw_memory = None

    def update(phase, message):
        state({"phase": phase, "controllerPort": 1, "message": message})

    def check():
        boot.check_graphics_startup()  # includes cancellation
        if not boot.alive():
            process = getattr(boot, "proc", None)
            code = process.poll() if process is not None else None
            if code not in (None, 0):
                raise RuntimeError(f"Dolphin exited unexpectedly (exit code {code}).")
            raise _PreviewClosed("Dolphin was closed.")

    try:
        boot.check_cancelled()
        plan = preview_plan(manifest)
        update("loading", "Preparing your playable preview...")
        emit("booting", 5, "Preparing an isolated Dolphin with your port-1 controls...")
        boot.prepare()
        emit("waiting", None, "Waiting for an available Dolphin session. If another "
             "Dolphin is open, close it; you can also Stop this preview.")
        boot.launch()
        emit("booting", 18, "Waiting for menu automation...")
        if not boot.wait_for_pipe(timeout=45):
            check()
            raise RuntimeError("Dolphin did not open its menu-control pipe.")
        raw_memory = Dolphin(boot.pid)
        memory = _Guarded(raw_memory, check)
        deadline = time.monotonic() + 20
        while not memory.locate():
            if time.monotonic() >= deadline:
                raise RuntimeError("Could not read the game's memory after boot.")
            stop_event.wait(0.1)
        raw_pipe = boot.open_pipe()
        pipe = _Guarded(raw_pipe, check)
        if not match_setup.patch_one_player(memory, log=log):
            raise RuntimeError("This build does not support the solo preview start gate.")
        emit("at_css", 32, "Opening the offline character-select screen...")
        if not nav.nav_to_css(memory, pipe, log=log, check_startup=check):
            raise RuntimeError("Could not reach the offline character-select screen.")
        emit("at_css", 40, "Waiting for character select to finish loading...")
        if not _wait_css_initialized(memory, pipe, stop_event, check, log):
            raise RuntimeError("The offline character-select screen did not finish loading. "
                               "Retry the preview; if it repeats, check the Dolphin window.")
        match_setup.force_time_infinite(memory, log=log)
        stage_cursor = StageCursor(memory, pipe)
        from .runner import _memory_select_to_sss
        if not _memory_select_to_sss(memory, stage_cursor, plan["fighter"], plan["color"], log):
            major, minor = memory.u8(nav.SCENE_MAJOR), memory.u8(nav.SCENE_MINOR)
            log(f"Playable preview CSS-to-SSS transition failed: scene={major}/{minor}")
            raise RuntimeError("Dolphin did not advance from character select to stage select. "
                               "Retry the preview; if it repeats, check the Dolphin window.")
        emit("selecting_stage", 52, "Loading the selected stage...")
        if not stage_cursor.force_select(plan["stage_id"], hold=None):
            raise RuntimeError("Could not start the selected stage.")
        deadline = time.monotonic() + 30
        while not is_in_game(memory):
            check()
            if time.monotonic() >= deadline:
                raise RuntimeError("The selected match did not finish loading.")
            stop_event.wait(0.1)
        # Repair the existing CSS->SSS warp's input routing explicitly, then
        # release every automation button before handing the game to the user.
        match_setup.fix_player_pad_indices(memory, (0,), log=log)
        pipe.neutral()
        update("playing", "Ready. Use your controller on port 1; press Stop when finished.")
        while True:
            check()
            nav._guard_online(memory, pipe)
            # A pause or a stationary fighter is legitimate during manual play.
            # No frame-health timer ends the preview or declares a PASS.
            stop_event.wait(0.2)
    except DolphinBootCancelled:
        result.update(success=True, verdict="stopped", reason="Playable preview stopped.")
        update("stopped", result["reason"])
    except _PreviewClosed as error:
        result.update(success=True, verdict="closed", reason=str(error))
        update("stopped", result["reason"])
    except DolphinGraphicsError as error:
        result.update(reason=str(error), error_code="graphics_initialization_failed")
        update("error", result["reason"])
    except Exception as error:
        result.update(reason=str(error))
        update("error", result["reason"])
    finally:
        if raw_pipe is not None:
            try:
                raw_pipe.neutral()
            except Exception:
                pass
            try:
                raw_pipe.close()
            except Exception:
                pass
        if raw_memory is not None:
            raw_memory.close()      # the RAM process handle: the pipe does not own it
        try:
            boot.cleanup()
        except Exception as error:
            # Process termination runs before log preservation in cleanup. A
            # filesystem failure preserving that log must not replace Stop's
            # result or prevent the route from releasing its session.
            result["cleanup_warning"] = str(error)
            log(f"Playable preview cleanup warning: {error}")
    return result
