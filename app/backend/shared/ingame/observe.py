"""
observe.py -- watch a running Slippi Melee for crashes/hangs while a mod is
loaded, reading live state from RAM. Boot a modded ISO, get into a match, and
have the Observer tell you objectively whether the mod ran or crashed.

Ported from tools/ingame/nucleus/observe.py: the Observer class is identical (the
crash/hang verdict logic is the validated core). The dev CLI main() and
capture_diagnostics (which shelled out to `node control.js shot`) are dropped --
screenshots are taken by the runner via screenshot.py (stdlib ctypes + PIL).

Crash/hang signals (most reliable first):
  - process death            -> CRASH
  - MEM1 / GALE01 gone        -> CRASH
  - frame counter frozen      -> HANG
  - left in-game unexpectedly -> ENDED (soft crash to menu)

Scene state (Melee 1.02): major 0x80479D30 == 0x02 in VS mode; in-match substate
0x80479D33 == 0x02 in-game (0x00 = character select). Frame counter 0x80479D60.
"""

import json
import time

SCENE_MAJOR = 0x80479D30
SCENE_SUBSTATE = 0x80479D33
FRAME_COUNTER = 0x80479D60


def is_in_game(d):
    """True when the VS in-match scene is up (major 0x02 / substate 0x02)."""
    return d.u8(SCENE_MAJOR) == 0x02 and d.u8(SCENE_SUBSTATE) == 0x02


def wait_in_game(d, timeout=30.0, poll=0.1, log=None):
    """Block until the match is actually IN-GAME, then return True. This absorbs
    host-variable stage LOAD time: a slower machine simply spends longer on the
    black load screen, and we wait for the real scene flag instead of guessing
    with a fixed sleep. Returns False on timeout or if Dolphin dies."""
    start = time.time()
    while time.time() - start < timeout:
        if not d.alive():
            return False
        if is_in_game(d):
            if log:
                log(f"in-game after {time.time() - start:.1f}s")
            return True
        time.sleep(poll)
    return is_in_game(d)


def wait_game_frames(d, frames, fps_floor=10.0, poll=0.02, log=None):
    """Observe every requested game frame, with a bounded inactivity deadline.

    Concurrent emulators can advance below the assumed throughput without
    hanging. The old total wall-clock deadline rejected those healthy loads.
    Keep the same safety budget, renewed ONLY by an observed counter advance;
    a stopped/unreadable counter or dead process still fails. Counter resets
    start the requested interval again, and an absolute bound prevents endless
    scene changes from renewing the wait forever.
    """
    frames = max(0, int(frames))
    if not frames:
        return True
    timeout = max(2.0, frames / max(1.0, fps_floor) + 2.0)
    start = time.monotonic()
    deadline = start + timeout
    absolute = start + (frames + 1) * timeout
    f0 = last = d.u32(FRAME_COUNTER)
    if f0 is None:
        if log:
            log(f"wait_game_frames({frames}) failed: counter unreadable")
        return False
    reason = 'counter made no progress within the safety budget'
    while time.monotonic() < min(deadline, absolute):
        if not d.alive():
            reason = 'process exited'
            break
        f = d.u32(FRAME_COUNTER)
        if f is not None:
            if f < last:
                # A scene flip invalidates the previous interval. The reset
                # itself does not count as forward progress or renew a budget.
                f0 = f
            elif f > last:
                deadline = time.monotonic() + timeout
            last = f
            if f - f0 >= frames:
                elapsed = time.monotonic() - start
                if log and elapsed > timeout:
                    log(f"wait_game_frames({frames}) observed {f-f0} frames in {elapsed:.2f}s; slow progress retained")
                return True
        time.sleep(poll)
    else:
        if time.monotonic() >= absolute:
            reason = 'absolute scene-reset bound reached'
    if log:
        log(f"wait_game_frames({frames}) failed after {time.monotonic()-start:.2f}s: "
            f"{reason}; start={f0}, last={last}")
    return False


class Observer:
    def __init__(self, dolphin):
        self.d = dolphin

    def status(self):
        """One snapshot of liveness + scene. Returns None-ish dicts if RAM is
        unreadable (process gone or emulation stopped)."""
        if not self.d.alive():
            return {"alive": False}
        if self.d.base is None and not self.d.locate():
            return {"alive": True, "mem": False}
        frame = self.d.u32(FRAME_COUNTER)
        if frame is None:
            if not self.d.locate():
                return {"alive": True, "mem": False}
            frame = self.d.u32(FRAME_COUNTER)
        major = self.d.u8(SCENE_MAJOR)
        sub = self.d.u8(SCENE_SUBSTATE)
        return {
            "alive": True,
            "mem": frame is not None,
            "frame": frame,
            "major": major,
            "sub": sub,
            "in_game": major == 0x02 and sub == 0x02,
        }

    def watch_health(self, seconds=20.0, freeze_secs=3.0, log=None,
                     early_ok_frames=0, poll=0.2):
        """Watch process + frame-counter health on ANY screen (boot/menu/game).
        Catches boot- and load-time crashes without needing to select the mod --
        the global frame counter advances on every screen, so a freeze or
        process death is a crash/hang regardless of where we are.

        `early_ok_frames` > 0 returns "healthy" as soon as that many DISTINCT
        counter advances have been observed, instead of always burning the full
        `seconds`. This is a pure latency win with no loss of hang detection:
        the hung/crashed verdicts are unchanged (a frozen counter still has to
        sit still for `freeze_secs`, and a dead process still fails on the first
        poll) -- only the boring "yes, it is running" answer comes back in
        ~1 frame instead of `seconds`. Use it where the caller is about to drive
        the game anyway and every later gate re-checks liveness; keep the full
        watch where the point IS to observe for a while (crash soak tests).
        Measured: the batch's between-target recovery called this twice per
        target at seconds=1.5 and spent 3.0 s of every 22.5 s target doing so."""
        start = time.time()
        last_frame = None
        last_change = start
        advances = 0

        def emit(event, **kw):
            if log:
                log(json.dumps({"t": round(time.time() - start, 2), "event": event, **kw}))

        emit("health_watch_start", seconds=seconds)
        if early_ok_frames > 0:
            poll = min(poll, 0.005)
        while time.time() - start < seconds:
            st = self.status()
            if st is None or not st.get("alive"):
                return "crashed", "dolphin process exited", st
            if not st.get("mem"):
                return "crashed", "emulated RAM unreadable", st
            f = st.get("frame")
            if f != last_frame:
                if last_frame is not None:
                    advances += 1
                    if early_ok_frames and advances >= early_ok_frames:
                        return ("healthy",
                                f"frame counter advanced {advances}x in "
                                f"{time.time() - start:.2f}s", st)
                last_frame = f
                last_change = time.time()
            elif time.time() - last_change > freeze_secs:
                emit("frame_frozen", frame=f, major=st.get("major"), sub=st.get("sub"))
                return "hung", f"frame counter frozen at {f} for >{freeze_secs}s", st
            time.sleep(poll)
        return "healthy", f"alive and advancing for {seconds:.0f}s", self.status()

    def watch(self, seconds=20.0, freeze_secs=2.0, min_ingame=4.0, log=None, require_ingame=True):
        """Poll until the watch window elapses or a crash/hang is detected.
        Returns (verdict, reason, last_status). verdict in
        {healthy, crashed, hung, ended, never_started}. A mod that loads and
        runs past min_ingame seconds is a PASS even if the match then ends."""
        start = time.time()
        last_frame = None
        last_frame_change = start
        reached_ingame = False
        ingame_start = None
        prev_scene = None

        def emit(event, **kw):
            if log:
                log(json.dumps({"t": round(time.time() - start, 2), "event": event, **kw}))

        emit("watch_start", seconds=seconds)
        while time.time() - start < seconds:
            st = self.status()
            if st is None or not st.get("alive"):
                return "crashed", "dolphin process exited", st
            if not st.get("mem"):
                if reached_ingame:
                    return "crashed", "emulated RAM became unreadable", st
                time.sleep(0.2)
                continue

            scene = (st["major"], st["sub"])
            if scene != prev_scene:
                emit("scene", major=st["major"], sub=st["sub"], in_game=st["in_game"])
                prev_scene = scene

            if st["in_game"]:
                if not reached_ingame:
                    reached_ingame = True
                    ingame_start = time.time()
                    emit("reached_ingame", frame=st["frame"])
                if st["frame"] != last_frame:
                    last_frame = st["frame"]
                    last_frame_change = time.time()
                elif time.time() - last_frame_change > freeze_secs:
                    emit("frame_frozen", frame=st["frame"])
                    return "hung", f"frame counter frozen at {st['frame']} for >{freeze_secs}s", st
            elif reached_ingame:
                dur = time.time() - ingame_start
                emit("left_ingame", major=st["major"], sub=st["sub"], ingame_secs=round(dur, 1))
                if dur < min_ingame:
                    return "ended", f"left in-game after only {dur:.1f}s (possible soft crash)", st
                return "healthy", f"loaded and ran {dur:.1f}s in-game before the match ended", st

            time.sleep(0.2)

        last = self.status()
        if require_ingame and not reached_ingame:
            return "never_started", "never reached in-game during the watch window", last
        return "healthy", "ran to end of watch window without crash/hang", last
