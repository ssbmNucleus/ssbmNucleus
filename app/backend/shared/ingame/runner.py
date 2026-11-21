"""
runner.py -- the in-app "Test in game" orchestrator.

Boots a freshly-built ISO in an isolated throwaway Dolphin (boot.py), drives the
menus to the OFFLINE character-select screen by scene feedback (nav.py), then
runs a PLAN of checks derived from the build manifest -- each check selects the
modded character/stage (closed-loop, melee_css/melee_sss), optionally triggers an
effect move, and watches RAM for a crash/hang (observe.py) -- and returns a
structured PASS/CRASH/HUNG result with screenshots.

Smart plan: a modpack (all six mod types in one ISO) is covered by just TWO
matches that share fighters --
  A) the custom character on the custom stage      -> character + stage + menu bg
  B) the modded fighter's costume on the DAS stage holding its button, then the
     effect move in-match                          -> costume + DAS + effect
Single-type builds get one matching check; anything we can't drive specifically
falls back to a boot-health watch (boot -> reach the CSS so the mod's data loads
-> watch process/frame health), which still catches the vast majority of broken
builds. NOTHING ever enters the online screen (nav.py aborts on scene 0x08).

Public entry: run_test(...). Designed to be called from a background thread in
the backend; it emits progress through the `emit` callback and always cleans up
Dolphin + the temp User dir.
"""

import base64
import time

from .boot import DolphinBoot
from .boot_errors import DolphinGraphicsError
from .melee_mem import Dolphin
from .melee_css import Cursor
from .melee_sss import StageCursor, INTERNAL_STAGE_ID, norm as _norm_stage
from .observe import Observer, wait_in_game, wait_game_frames
from . import nav
from . import match_setup
from . import screenshot as _screenshot
from .char_select import load_grid, cell, css_index, ckind as char_ckind, raw_key


# severity for aggregating the overall verdict (higher = worse)
_SEVERITY = {"healthy": 0, "ended": 1, "never_started": 2, "hung": 3, "crashed": 4, "error": 5}


def _noop(*_a, **_k):
    pass


# How long an automated run's Dolphin may live (DolphinBoot's `deadline`), on
# top of the time it is asked to watch. As in capture.py these sit above the
# sum of the time limits the run's waits already have, so only a run that has
# stopped moving reaches one. A playable preview has no deadline.
RUN_DEADLINE = 300.0       # boot, menus, the boot-health watch
CHECK_DEADLINE = 90.0      # one check: back to the CSS, selection, stage load, a move


def _note_deadline(boot, result, log=_noop):
    """A run whose Dolphin was ended at its deadline is a harness error, never a
    verdict on the build: the death the check in flight then saw was ours, and
    "crashed" would blame the mod for it. Checks that finished keep theirs."""
    if not getattr(boot, "timed_out", False):      # a stand-in boot that knows no deadline never reached one
        return
    reason = ("Dolphin stopped responding, so the test was ended after "
              f"{float(boot.deadline):.0f} seconds. This is not a verdict on the build; try again.")
    log(f"ended at the deadline; the run's own verdict was {result.get('verdict')!r}: {result.get('reason')!r}")
    if result["checks"] and result["checks"][-1]["verdict"] != "healthy":
        result["checks"][-1].update(verdict="error", reason=reason)
    result.pop("boot_health", None)          # watched after our kill: "crashed" there is ours too
    result.update(verdict="error", reason=reason, timedOut=True)
    result["pass"] = False


# --------------------------------------------------------------------------- #
# Plan building                                                                 #
# --------------------------------------------------------------------------- #
def _icon(d):
    """Normalise a cssIcon / sssIcon dict (tolerate missing keys)."""
    if not isinstance(d, dict):
        return None
    return d


def build_plan(manifest):
    """Turn a build manifest into a list of checks. See module docstring for the
    smart 2-match modpack coverage. Returns [] for boot-health-only (handled by
    the caller)."""
    if not manifest:
        return []

    costume = manifest.get("costume") or None
    character = manifest.get("character") or None
    custom_stage = manifest.get("customStage") or None
    das = manifest.get("das") or None
    effect = manifest.get("effect") or None

    css_icon = _icon(character.get("cssIcon")) if character else None
    sss_icon = _icon(custom_stage.get("sssIcon")) if custom_stage else None

    checks = []

    # --- Match A: custom character (+ custom stage if present) ---------------
    if css_icon:
        stage = None
        covers = ["character"]
        label_stage = "Battlefield"
        if sss_icon:
            stage = {"kind": "icon", "page": int(sss_icon.get("page", 0)),
                     "x": float(sss_icon["x"]), "y": float(sss_icon["y"]),
                     "stageId": sss_icon.get("stageId")}
            covers.append("stage")
            label_stage = custom_stage.get("name", "custom stage")
        checks.append({
            "label": f"{character.get('name', 'custom fighter')} on {label_stage}",
            "covers": covers + ["menu"],
            "char": {"kind": "custom", "x": float(css_icon["x"]),
                     "y": float(css_icon["y"]), "index": int(css_icon["index"]),
                     "ckind": css_icon.get("fighter"),
                     "costume": int(character.get("colorIndex", 0) or 0)},
            "stage": stage,
            "hold": None,
            "move": None,
        })
    elif sss_icon:
        # custom stage but no custom character -> a vanilla fighter reaches the SSS
        checks.append({
            "label": f"Fox on {custom_stage.get('name', 'custom stage')}",
            "covers": ["stage", "menu"],
            "char": {"kind": "vanilla", "name": "fox", "costume": 0},
            "stage": {"kind": "icon", "page": int(sss_icon.get("page", 0)),
                      "x": float(sss_icon["x"]), "y": float(sss_icon["y"]),
                      "stageId": sss_icon.get("stageId")},
            "hold": None,
            "move": None,
        })

    # --- Match B: the modded fighter's abilities (costume + DAS + effect) ----
    ability_covers = []
    ability_fighter = None
    if effect and effect.get("fighter"):
        ability_fighter = effect["fighter"]
    elif costume and costume.get("fighter"):
        ability_fighter = costume["fighter"]

    if ability_fighter:
        ccostume = 0
        if costume and str(costume.get("fighter", "")).lower() == str(ability_fighter).lower():
            ccostume = int(costume.get("colorIndex", 0) or 0)
            ability_covers.append("costume")
        stage = {"kind": "name", "name": "battlefield"}
        hold = None
        if das and das.get("button"):
            stage = {"kind": "name", "name": das.get("stage", "battlefield")}
            hold = str(das["button"]).upper()
            ability_covers.append("das")
        move = None
        if effect and effect.get("move"):
            move = effect["move"]
            ability_covers.append("effect")
        if ability_covers:  # only add if it actually exercises something
            stage_label = das.get("stage", "Battlefield") if das else "Battlefield"
            checks.append({
                "label": f"{ability_fighter} abilities ({', '.join(ability_covers)}) on {stage_label}",
                "covers": ability_covers + ["menu"],
                "char": {"kind": "vanilla", "name": ability_fighter, "costume": ccostume},
                "stage": stage,
                "hold": hold,
                "move": move,
            })

    # --- Standalone costume mod (its own match if not folded into B) ---------
    folded_costume = any("costume" in c["covers"] for c in checks)
    if costume and costume.get("fighter") and not folded_costume:
        checks.append({
            "label": f"{costume['fighter']} costume {costume.get('colorIndex', 0)}",
            "covers": ["costume", "menu"],
            "char": {"kind": "vanilla", "name": costume["fighter"],
                     "costume": int(costume.get("colorIndex", 0) or 0)},
            "stage": {"kind": "name", "name": "battlefield"},
            "hold": None,
            "move": None,
        })

    # --- Standalone DAS mod (no costume/effect to fold into) -----------------
    folded_das = any("das" in c["covers"] for c in checks)
    if das and das.get("button") and not folded_das:
        checks.append({
            "label": f"DAS {das.get('stage', 'stage')} (hold {das['button']})",
            "covers": ["das", "menu"],
            "char": {"kind": "vanilla", "name": "fox", "costume": 0},
            "stage": {"kind": "name", "name": das.get("stage", "battlefield")},
            "hold": str(das["button"]).upper(),
            "move": None,
        })

    return checks


# --------------------------------------------------------------------------- #
# Selection + move helpers (ported from cl_match.py)                            #
# --------------------------------------------------------------------------- #
def _lock_vanilla(cur, name, costume):
    """Steer to a vanilla character cell + set costume, then ONE deliberate A to
    lock (an even A count silently unlocks; START downstream is the real check)."""
    grid = load_grid()
    x, y = cell(grid, name)
    cur.select(x, y, costume=costume, lock=False, css_index=css_index(name))
    cur.p.center()
    time.sleep(0.15)
    cur.p.tap("A", 0.08)
    time.sleep(0.35)
    return cur.hovered() == css_index(name)


def _lock_custom(cur, x, y, index, costume=0):
    """Lock a custom m-ex fighter by its CSS icon coordinate (target = (x, y-3.5),
    the validated icon->cursor offset); confirm the hovered grid index, cycle to
    the requested costume slot, then lock."""
    tx, ty = x, y - 3.5
    cur.unlock()
    cur.move_to(tx, ty)
    for _ in range(4):
        if cur.hovered() == index:
            break
        cur.move_to(tx, ty, tol=0.7)
        time.sleep(0.12)
    cur.set_costume(int(costume or 0))
    cur.p.center()
    time.sleep(0.15)
    cur.p.tap("A", 0.08)
    time.sleep(0.35)
    return cur.hovered() == index


def _select_char(cur, char):
    if char["kind"] == "custom":
        return _lock_custom(cur, char["x"], char["y"], char["index"],
                            int(char.get("costume", 0) or 0))
    return _lock_vanilla(cur, char["name"], int(char.get("costume", 0)))


def _internal_stage_id(stage):
    """The engine INTERNAL stage id for a force_select start, or None if the stage
    must be cursor-selected (a custom icon with no usable id)."""
    if stage is None or stage.get("kind") == "name":
        name = stage["name"] if stage else "battlefield"
        return INTERNAL_STAGE_ID.get(_norm_stage(name))
    if stage.get("kind") == "icon":
        sid = stage.get("stageId")
        return sid if isinstance(sid, int) and 0 <= sid <= 0x7F else None
    if stage.get("kind") == "id":
        return int(stage["id"])
    return None


def _select_stage(sc, stage, hold):
    """Pick + start the stage. Prefer the engine's force_stage_id write (no
    cursor, layout/page independent -- so a custom stage on a later SSS page works
    the same as a vanilla one) whenever we know the INTERNAL stage id; fall back
    to cursor-coordinate selection only when we don't."""
    sid = _internal_stage_id(stage)
    if sid is not None:
        return sc.force_select(sid, hold=hold)
    # No usable internal id -> drive the cursor to the placed icon (page-aware).
    if stage and stage.get("kind") == "icon":
        return sc.select_at(stage["x"], stage["y"], page=int(stage.get("page", 0)),
                            press=True, hold=hold)
    name = stage["name"] if stage else "battlefield"
    return sc.select(name, press=True, hold=hold)


def _memory_select_to_sss(d, sc, ckind, color, log=_noop):
    """Cursor-free selection: write the solo player block (chosen fighter + color)
    and memory-warp the CSS straight to the stage-select screen -- no cursor lock,
    no add-CPU, no START 'ready' gate. Returns True once on the SSS (the caller
    then force_selects the stage); False if the warp didn't land -- in which case
    we're still on the CSS, so the cursor path is a clean fallback. Requires Time/
    no-timer rules (force_time_infinite) already set so the solo match sustains."""
    match_setup.write_solo_player(d, ckind, color)
    match_setup.warp_to_stage_select(d)
    if not sc.wait_for_stage_select(timeout=8.0):
        return False
    match_setup.write_solo_player(d, ckind, color)   # re-assert after the scene flip
    return True


def _ensure_on_sss(d, p, sc, cur, log, solo=False):
    """Get onto the stage-select screen. Normally that needs a locked character
    AND a 2nd player, so we add a CPU (closed-loop, RAM-verified) if one's missing,
    then press START. When `solo` (the 1-player start patch is in), we skip the
    add-CPU step entirely and just press START. Returns True once on the SSS."""
    for attempt in range(4):
        if sc.on_stage_select():
            return True
        if not solo and not nav.any_extra_player(d):
            log("no 2nd player present; opening a port door")
            nav.add_cpu(d, p, cur=cur, log=log)
        p.tap("START", 0.1)
        if sc.wait_for_stage_select(timeout=2.5):
            return True
        time.sleep(0.2)
    return sc.on_stage_select()


def _transform_to_sheik(d, p, log=_noop):
    """The CSS cursor can only pick Zelda (Sheik has no cell of her own), so on
    the cursor-select fallback a Sheik check starts the match as Zelda -- one
    deliberate down-B once controls are live transforms her into Sheik so
    Sheik's data actually loads. NOT needed on the memory-selection path, which
    writes Sheik's own external id (0x13) and loads her directly. One press
    only: Sheik's down-B transforms BACK, so blind retries would just toggle."""
    wait_in_game(d, timeout=20.0)
    wait_game_frames(d, 180)   # ~3s of game time: past READY/GO so inputs register
    log("transforming Zelda -> Sheik (down-B)")
    # Main-stick y: 0.0 = DOWN, 1.0 = UP (verified in-match: 1.0+B was Farore's).
    p.frame(["SET MAIN 0.500 0.000", "FLUSH"])   # hold down first: not Nayru's
    time.sleep(0.1)
    p.frame(["PRESS B", "FLUSH"])
    time.sleep(0.15)
    p.frame(["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])
    wait_game_frames(d, 150)   # ride out the transform animation
    p.center()


def _perform_move(d, p, move, reps=6):
    """After a match starts, perform the in-game move that exercises an effect
    mod (so its model/data actually loads). Waits out the load + GO! countdown
    first -- gated on the game's own state (in-game scene, then a fixed number of
    GAME frames) so the inputs land after controls are live on ANY machine, not a
    fixed wall-clock sleep that fires too early on a slow one."""
    wait_in_game(d, timeout=20.0)
    wait_game_frames(d, 180)   # ~3s of game time: past READY/GO so inputs register
    if move == "neutralb":
        for _ in range(reps):
            p.tap("B", 0.06)
            time.sleep(0.5)
    elif move == "sideb":
        for _ in range(reps):
            p.frame(["SET MAIN 1.000 0.500", "PRESS B", "FLUSH"])
            time.sleep(0.12)
            p.frame(["RELEASE B", "SET MAIN 0.500 0.500", "FLUSH"])
            time.sleep(0.6)
    p.center()


def _shot_b64(boot):
    """Capture a screenshot as a data-URI. Prefers PrintWindow on the render
    window (clean pixels even when the throwaway Dolphin is occluded / unfocused);
    falls back to the desktop window grab if that comes back empty."""
    png = None
    try:
        png = _screenshot.capture_via_printwindow(boot.pid, max_width=640)
    except Exception:
        png = None
    if not png:
        try:
            png = _screenshot.capture_png(boot.pid, max_width=640)
        except Exception:
            png = None
    if png:
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return None


# --------------------------------------------------------------------------- #
# Main entry                                                                    #
# --------------------------------------------------------------------------- #
def run_test(iso_path, slippi_path, runs_root, manifest=None, emit=None, log=None,
             observe_seconds=9, hires_textures=False, load_seed=None,
             interactive=False, stop_event=None, on_interactive_state=None,
             deadline=None):
    """Boot the ISO, drive it, and return a result dict:
        {
          "verdict": "healthy"|"ended"|"never_started"|"hung"|"crashed"|"error",
          "pass": bool,
          "reason": str,
          "checks": [ {label, covers, verdict, reason, started, screenshot} ],
          "screenshot": <data-uri of the CSS / last frame>,
          "drove": [check labels],
          "online_aborted": bool,
        }
    emit(stage, percentage, message) reports progress; log(msg) is for the log.
    stop_event (a threading.Event) stops a playable preview; an automated run
    hands it to its Dolphin boot, so a set event ends the run's waits (the
    Dolphin lock queue, the boot, the menu navigation) at once.
    deadline: seconds an automated run's Dolphin may live before it is ended
    and the run returns verdict "error" with "timedOut" (default: RUN_DEADLINE,
    CHECK_DEADLINE per check of the manifest, and the watch time asked for).
    """
    if interactive:
        from .interactive import run_interactive_test
        return run_interactive_test(
            iso_path, slippi_path, runs_root, manifest=manifest, emit=emit, log=log,
            hires_textures=hires_textures, load_seed=load_seed, stop_event=stop_event,
            on_interactive_state=on_interactive_state)
    emit = emit or _noop
    log = log or _noop

    result = {
        "verdict": "error", "pass": False, "reason": "", "checks": [],
        "screenshot": None, "drove": [], "online_aborted": False,
    }

    # an already-open Dolphin steals input focus from the throwaway one —
    # wait for the user to close it (the progress message says why) instead
    # of dying minutes later with a confusing menu timeout
    from .boot import DOLPHIN_OPEN_MSG, wait_until_no_dolphin
    if not wait_until_no_dolphin(emit, log=log, stop_event=stop_event):
        result.update(verdict="error", reason=DOLPHIN_OPEN_MSG)
        return result

    if deadline is None:
        try:
            checks = len(build_plan(manifest))
        except Exception:
            checks = 0          # a manifest that cannot be planned is reported where the plan is built
        deadline = (RUN_DEADLINE + max(observe_seconds, 12)
                    + checks * (CHECK_DEADLINE + observe_seconds))

    # Match the diagnostic screenshot's 640px cap at launch. The live preview
    # scales this surface without resizing Dolphin during GPU initialization.
    boot = DolphinBoot(iso_path, slippi_path, runs_root, render_size=(640, 480),
                       hires_textures=hires_textures, load_seed=load_seed, log=log,
                       stop_event=stop_event, deadline=deadline)
    p = None  # so the error-path screenshots / finally can reference it safely
    try:
        emit("booting", 5, "Preparing an isolated Dolphin (your Slippi setup is untouched)…")
        boot.prepare()
        emit("booting", 12, "Launching the build…")
        boot.launch()

        emit("booting", 18, "Waiting for the controller pipe…")
        if not boot.wait_for_pipe(timeout=45):
            result.update(verdict="crashed",
                          reason="Dolphin never opened its input pipe (the build may have failed to boot).")
            return result

        # Attach to RAM (wait for MEM1 to be mapped).
        emit("booting", 24, "Attaching to emulated memory…")
        d = Dolphin(boot.pid)
        t0 = time.time()
        while not d.locate() and time.time() - t0 < 20:
            boot.check_graphics_startup()
            if not d.alive():
                result.update(verdict="crashed", reason="Dolphin process exited during boot.")
                return result
            time.sleep(0.4)
        if d.base is None:
            result.update(verdict="crashed", reason="Could not read the game's memory after boot.")
            return result

        # Load matches ALONE (1-player) when we can patch the CSS start gate: no
        # CPU to add (faster, fewer cursor sweeps) and nothing that can attack or
        # disturb the check. Falls back to a 2nd player if the patch doesn't apply.
        solo = match_setup.patch_one_player(d, log=log)

        try:
            p = boot.open_pipe()
        except OSError as e:
            log(f"controller pipe never reopened: {e}")
            result.update(verdict="crashed",
                          reason="Dolphin's controller pipe didn't come back up "
                                 "(it may have failed to boot); please retry.")
            return result
        obs = Observer(d)

        # Drive to the OFFLINE character-select screen (never online).
        emit("at_css", 32, "Navigating to the offline character-select screen…")
        try:
            if not nav.nav_to_css(d, p, log=log,
                                  check_startup=boot.check_graphics_startup):
                # RAM health remains useful evidence, but no requested mod
                # check ran if we never reached the offline menu.
                emit("observing", 60, "Couldn't confirm the menu; watching boot health instead…")
                verdict, reason, _ = obs.watch_health(seconds=observe_seconds, log=log)
                result["screenshot"] = _shot_b64(boot)
                result.update(verdict="error" if verdict == "healthy" else verdict,
                              reason="Could not reach the offline character-select screen; "
                                     "the requested in-game checks did not run. "
                                     "Boot-health observation: " + reason,
                              boot_health={"verdict": verdict, "reason": reason})
                result["pass"] = False
                return result
        except nav.OnlineAbort as oa:
            result.update(verdict="error", online_aborted=True, reason=str(oa))
            result["screenshot"] = _shot_b64(boot)
            return result

        cur = Cursor(d, p)
        sc = StageCursor(d, p)

        # The offline-CSS scene flag flips a beat BEFORE the screen is actually
        # interactive -- wait for the cursor to come alive (and settle) before
        # driving anything, or the add-CPU press is dropped into a dead screen and
        # the match never starts (no 2nd player). This was the harness's implicit
        # 3s post-nav delay.
        nav.wait_css_ready(d, cur, log=log)
        if solo:
            match_setup.force_time_infinite(d, log=log)  # a 1-player match won't end

        # Snapshot the (now-settled) CSS (shows the menu background + portraits).
        result["screenshot"] = _shot_b64(boot)

        plan = build_plan(manifest)
        if not plan:
            # No manifest / nothing specific to drive -> boot-health at the CSS.
            emit("observing", 70, "Watching boot health at the character-select screen…")
            verdict, reason, _ = obs.watch_health(seconds=max(observe_seconds, 12), log=log)
            result.update(verdict=verdict, reason="boot-health: " + reason)
            result["pass"] = verdict == "healthy"
            return result

        # Open the port-2 door (2nd player) before character select, as in the
        # harness flow. Best-effort here -- the per-check START step verifies a
        # 2nd player actually exists and reliably opens one (panel-row sweep with
        # START verification) if this missed. Skipped when loading solo.
        if not solo:
            nav.add_cpu(d, p, cur=cur, log=log)

        n = len(plan)
        for i, check in enumerate(plan):
            base_pct = 36 + int(48 * i / max(1, n))
            label = check["label"]
            result["drove"].append(label)
            sub = {"label": label, "covers": check["covers"], "verdict": "error",
                   "reason": "", "started": False, "screenshot": None}
            try:
                if i > 0:
                    emit("selecting_char", base_pct, f"Returning to the CSS for: {label}…")
                    if not nav.reset_to_css(d, p, log=log):
                        sub.update(verdict="error", reason="could not return to the CSS for this check")
                        result["checks"].append(sub)
                        continue

                emit("selecting_char", base_pct + 2, f"Selecting: {label}…")
                # Primary path: cursor-free memory selection (write the solo player
                # block + warp CSS->SSS). Used when we can load solo, know the
                # fighter's external c_kind (vanilla), and can force-select the
                # stage. Falls back to the proven cursor lock + START otherwise --
                # or if the warp doesn't land, in which case we're still on the CSS
                # so the fallback is clean.
                if check["char"]["kind"] == "vanilla":
                    ck = char_ckind(check["char"]["name"])
                else:  # custom m-ex fighter: external id captured from the build
                    ck = check["char"].get("ckind")
                if not (isinstance(ck, int) and 0 <= ck <= 0x7F):
                    ck = None
                color = int(check["char"].get("costume", 0) or 0)
                stage_id = _internal_stage_id(check.get("stage"))
                used_memory = False
                if solo and ck is not None and stage_id is not None:
                    used_memory = _memory_select_to_sss(d, sc, ck, color, log)
                    log(f"[{label}] memory select -> SSS: {used_memory}")

                emit("selecting_stage", base_pct + 6, f"Choosing the stage for: {label}…")
                if not used_memory:
                    on_cell = _select_char(cur, check["char"])
                    log(f"[{label}] char on_cell={on_cell} hovered={cur.hovered()}")
                    # Make sure the port door opened (2nd player present) + the
                    # character locked, landing us on the stage-select screen,
                    # before we try to pick the stage.
                    if not _ensure_on_sss(d, p, sc, cur, log, solo=solo):
                        sub.update(verdict="never_started",
                                   reason="couldn't reach stage select (no 2nd player, or the character didn't lock)")
                        sub["screenshot"] = _shot_b64(boot)
                        result["checks"].append(sub)
                        continue
                started = _select_stage(sc, check.get("stage"), check.get("hold"))
                sub["started"] = bool(started)
                log(f"[{label}] match_started={started}")

                if not started:
                    sub.update(verdict="never_started",
                               reason="couldn't start the match (selection failed)")
                    sub["screenshot"] = _shot_b64(boot)
                    result["checks"].append(sub)
                    continue

                # Cursor-selected Sheik started the match as Zelda -- transform.
                if (not used_memory and check["char"]["kind"] == "vanilla"
                        and raw_key(check["char"]["name"]) == "sheik"):
                    emit("in_match", base_pct + 8, f"Transforming into Sheik for: {label}…")
                    _transform_to_sheik(d, p, log=log)

                if check.get("move"):
                    emit("in_match", base_pct + 9, f"Triggering {check['move']} for: {label}…")
                    _perform_move(d, p, check["move"])

                emit("observing", base_pct + 11, f"Watching for crashes/hangs: {label}…")
                verdict, reason, _ = obs.watch(seconds=observe_seconds, require_ingame=True, log=log)
                sub.update(verdict=verdict, reason=reason)
                sub["screenshot"] = _shot_b64(boot)
                result["checks"].append(sub)
                log(f"[{label}] VERDICT {verdict} -- {reason}")
            except nav.OnlineAbort as oa:
                result["online_aborted"] = True
                sub.update(verdict="error", reason=str(oa))
                result["checks"].append(sub)
                break
            except Exception as e:  # one check failing shouldn't abort the rest
                sub.update(verdict="error", reason=f"{type(e).__name__}: {e}")
                result["checks"].append(sub)
                log(f"[{label}] ERROR {e}")

        # Aggregate.
        if result["checks"]:
            worst = max(result["checks"], key=lambda c: _SEVERITY.get(c["verdict"], 5))
            result["verdict"] = worst["verdict"]
            result["reason"] = worst["reason"] if worst["verdict"] != "healthy" else \
                "every modded element loaded and ran without a crash or hang."
            result["pass"] = all(c["verdict"] == "healthy" for c in result["checks"])
            # Prefer a gameplay screenshot for the headline image if we have one.
            for c in result["checks"]:
                if c.get("screenshot"):
                    result["screenshot"] = c["screenshot"]
                    break
        else:
            result.update(verdict="error", reason="no checks ran")

        emit("done", 96, "Wrapping up…")
        return result
    except DolphinGraphicsError as e:
        # The renderer is unavailable; asking PrintWindow for a screenshot of
        # its modal failure only adds another wait and can steal focus.
        result.update(verdict="error", reason=str(e),
                      error_code="graphics_initialization_failed")
        return result
    except Exception as e:
        result.update(verdict="error", reason=f"{type(e).__name__}: {e}")
        try:
            result["screenshot"] = _shot_b64(boot)
        except Exception:
            pass
        return result
    finally:
        try:
            p.close()  # noqa: F821 - best effort if it exists
        except Exception:
            pass
        try:
            d.close()  # noqa: F821 - the RAM process handle, if it was opened
        except Exception:
            pass
        boot.cleanup()
        _note_deadline(boot, result, log)
