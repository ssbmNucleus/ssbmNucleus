"""Running the playback Dolphin: the live process (for the in-app embed, pop-out and Stop), launching
it and failing loudly when it dies on startup, and recording a whole-game playlist one game per run."""

import json
import ntpath
import os
import subprocess
import tempfile
import threading
import time
import uuid

from .dolphin_config import _clear_old_dumps, _playback_user_dir
from .recording import AUDIO_BYTES_PER_SEC, _collect_recording


# the live playback Dolphin (for in-app embedding + the Stop button)
_playback_lock = threading.Lock()
_playback_proc = None
_popped_out = False  # user detached Dolphin into its own window (embed paused)


def _set_playback(proc):
    """Track the live playback Dolphin, and register it as the window the app
    captures into the Watch popup (the same capture as Test in Game: its
    windows go behind the app; Pop out brings them back, seek bar included)."""
    global _playback_proc, _popped_out
    from shared.ingame import embed
    with _playback_lock:
        old, _playback_proc = _playback_proc, proc
        _popped_out = False
    if old is not None:
        embed.clear_active(old.pid)
    if proc is not None:
        embed.set_active(proc.pid, process=proc, show_gui=True)


def _track(job, proc, exe=None):
    """``proc`` is now the live playback Dolphin (None: there is none). The
    watch job owns a live one, so a Dolphin left running when Nucleus died is
    closed at the next start (close_left_running), and its record carries the
    capture session the popup attaches to."""
    _set_playback(proc)
    if job is None:
        return
    if proc is None:
        job.release("dolphin")
    else:
        identity = _identity(proc, exe)
        if identity:
            job.own("dolphin", identity)
    job.progress(capture_session_id=capture_session() if proc is not None else None)


def _identity(proc, exe):
    """What close_left_running checks before it closes ``proc``."""
    try:
        import psutil
        created = psutil.Process(proc.pid).create_time()
    except Exception:  # noqa: BLE001 - already gone: nothing to own
        return None
    return {"pid": proc.pid, "created": created, "exe": exe}


def _same_file(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def close_left_running(owned):
    """Close the playback Dolphin a watch still owned when Nucleus died, only
    while that pid is the same process (start time) of the same executable.
    Killed, not asked to quit: a Dolphin that exits cleanly writes its settings
    back, the recording's dump flags with them. Returns a note, or None."""
    import psutil
    try:
        process = psutil.Process(owned["pid"])
        if (abs(process.create_time() - owned["created"]) >= 1.0
                or not _same_file(process.exe(), owned["exe"])):
            return None
        process.kill()
        process.wait(10)
    except psutil.Error:
        return None
    return "The playback Dolphin it left open was closed."


def _playback_pid():
    with _playback_lock:
        if _playback_proc and _playback_proc.poll() is None:
            return _playback_proc.pid
    return None


def capture_session():
    """The capture session of the live playback Dolphin, or None (not running,
    or another Dolphin took the capture). The popup only attaches to this one."""
    from shared.ingame import embed
    return embed.session_for(_playback_pid())


def is_popped_out():
    with _playback_lock:
        return _popped_out


def _set_popped(value):
    global _popped_out
    with _playback_lock:
        _popped_out = value


def position_window(x, y, width, height):
    """Pin the live playback Dolphin's render window over the frontend's
    placeholder (same mechanism as the in-game test embed). No-op while the
    user has the window popped out — a stale panel tick must not yank their
    detached window back over the app."""
    if is_popped_out():
        return {"found": True, "popout": True}
    from shared.ingame import embed
    return embed.position_pid(_playback_pid(), x, y, width, height)


def park_window():
    if is_popped_out():
        return {"found": False, "popout": True}
    from shared.ingame import embed
    return embed.park_pid(_playback_pid())


def popout_window():
    """Detach the playback Dolphin into a normal desktop window (chrome back,
    not topmost). The embed's position/park calls no-op until popin."""
    from shared.ingame import embed
    res = embed.popout_pid(_playback_pid())
    if res.get("found"):
        _set_popped(True)
    return {**res, "popout": is_popped_out()}


def popin_window():
    """Re-embed after a popout: clear the flag; the panel's next position tick
    re-strips the chrome and pins the window back over the placeholder."""
    _set_popped(False)
    return {"found": _playback_pid() is not None, "popout": False}


def stop_playback():
    """Close the live playback Dolphin (the embedded window has no title bar,
    so the UI needs an explicit Stop). Parks first — a dying GL window flashes
    black wherever it sits. The watch job notices and cleans up; it runs as the
    watch kind's on_cancel, after the job was asked to stop. Returns whether
    a Dolphin was running."""
    with _playback_lock:
        proc = _playback_proc
    if not proc or proc.poll() is not None:
        return False
    from shared.ingame import embed
    # Unregistered first: the closing popup's capture must not bring a dying
    # Dolphin's windows forward.
    embed.clear_active(proc.pid)
    embed.park_pid(proc.pid)
    proc.terminate()
    return True


LAUNCH_GRACE_S = 6.0    # Dolphin needs ~2-4s to boot; anything that exits
                        # inside this window never started playing.
_STDERR_TAIL_LINES = 25


def _drain_stderr(proc):
    """Keep the last few stderr lines, in a thread.

    A thread and not proc.communicate(): playback runs for as long as someone
    watches, and the pipe must keep being read the whole time. Left unread it
    fills, Dolphin blocks writing to it, and playback hangs with no visible
    cause -- a deadlock this codebase has already paid for once elsewhere.
    Bounded, so a chatty session cannot grow memory without limit.
    """
    from collections import deque
    tail = deque(maxlen=_STDERR_TAIL_LINES)

    def pump():
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    tail.append(line)
        except Exception:  # noqa: BLE001 — a dead pipe must never kill playback
            pass

    threading.Thread(target=pump, daemon=True).start()
    return tail


def _early_exit(proc, grace_s=LAUNCH_GRACE_S):
    """Return code if Dolphin exited during startup, else None."""
    deadline = time.time() + grace_s
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            return rc
        time.sleep(0.2)
    return None


def _launch_failure_message(rc, tail=()):
    """Say what to actually do, not just that something failed."""
    lines = list(tail)
    blob = " ".join(lines).lower()
    hint = ""
    # The single most common way a playback Dolphin fails to start on Windows:
    # no usable video backend. Worth naming outright, with the file to edit --
    # the playback build's config is SEPARATE from the netplay one, which is
    # why "netplay works fine" misleads everybody who hits this.
    if any(w in blob for w in ("direct3d", "d3d", "vulkan", "opengl", "backend",
                               "video", "adapter")) or not lines:
        hint = (" If Dolphin showed a graphics error, set GFXBackend under "
                "[Core] in the playback Dolphin's Dolphin.ini "
                "(%APPDATA%\\Slippi Launcher\\playback\\User\\Config) to OGL. "
                "That file is separate from the netplay build's, so netplay "
                "working does not rule this out.")
    detail = (" Last output: " + " | ".join(lines[-4:])) if lines else ""
    return f"Slippi playback exited immediately (code {rc}).{hint}{detail}"


def _crash_message(rc, tail=()):
    """The error for a playback Dolphin that ended by itself with a nonzero
    code, else None. Closing its window is a clean exit (0); Stop's terminate
    is nonzero too, so callers skip a stop the job asked for."""
    if not rc:
        return None
    lines = list(tail)
    detail = (" Last output: " + " | ".join(lines[-4:])) if lines else ""
    return f"Slippi playback stopped unexpectedly (code {rc}).{detail}"


# --- per-game recording of a whole-game playlist ----------------------------
# Slippi playback does NOT exit at the end of a queue (see
# combo_video/assemble.py, calibrated 2026-08-07): it sits there until
# something stops it. What it does do reliably is emit dspdump.wav at exactly
# 128000 B/s of EMULATED time, with dump frame 0 == Slippi frame -123. So each
# game gets its own Dolphin run against the one shared ISO, and the audio dump
# is the clock that says when the game is over.
FIRST_SLIPPI_FRAME = -123
GAME_END_MARGIN_S = 0.75           # emulate a hair past the last frame
GAME_BOOT_TIMEOUT_S = 90           # dump must start within this after launch
GAME_STALL_TIMEOUT_S = 60          # no audio growth for this long = wedged
GAME_END_IDLE_S = 5                # ...unless the whole game is already in


def game_seconds(entry):
    """Exact length of a whole-game queue entry (frames -123..endFrame)."""
    return (int(entry["endFrame"]) - FIRST_SLIPPI_FRAME + 1) / 60.0


def game_recording_name(index, total, replay_path, stamp):
    """File name (no extension) for game ``index`` (1-based) of a batch:
    ``playlist_<stamp>_<NN>_<replay stem>``. The shared batch stamp keeps a
    playlist's files together and the zero-padded index sorts them in the
    order they were played."""
    width = max(2, len(str(total)))
    stem = os.path.splitext(ntpath.basename(replay_path))[0]
    return f"playlist_{stamp}_{index:0{width}d}_{stem}"


def _write_comm(entries):
    """Playback comm file for a queue of [{path, startFrame, endFrame}]."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="nucleome_comm_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"mode": "queue", "replay": "", "isRealTimeMode": False,
                   "commandId": uuid.uuid4().hex,
                   "queue": [{"path": e["path"],
                              "startFrame": int(e["startFrame"]),
                              "endFrame": int(e["endFrame"])} for e in entries]},
                  f)
    return path


def _launch_playback(dolphin, comm_path, iso_path, job=None):
    """Start playback Dolphin, register it for embed/Stop and as the job's,
    and fail loudly if it dies during startup. Returns the process."""
    from core.child_env import child_environment
    proc = subprocess.Popen([dolphin, "-i", comm_path, "-b", "-e", iso_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=child_environment())
    _track(job, proc, dolphin)
    tail = _drain_stderr(proc)
    proc.stderr_tail = tail     # for _crash_message once it has played
    # Do not announce "Playing" until Dolphin has survived long enough to
    # have opened something. It used to be set on the line after Popen,
    # so a Dolphin that died on startup left the modal cheerfully claiming
    # to be playing while the user stared at nothing -- and the exit code
    # was never looked at either, so the failure reached no log and no
    # bug report.
    died = _early_exit(proc)
    # Closed by Stop during startup is not a failed start: the caller saves
    # what was recorded, as for a later Stop.
    if died is not None and not (job is not None and job.should_stop()):
        raise RuntimeError(_launch_failure_message(died, tail))
    return proc


def _await_game_end(proc, game_s, audio_path, job, poll_s=1.0):
    """Block until the audio dump shows the game (``game_s`` seconds, plus
    GAME_END_MARGIN_S) emulated. Returns 'done', 'stopped' (Stop pressed) or
    'exited' (Dolphin closed, e.g. the user closed a popped-out window).
    Stop is the watch ``job`` asked to stop.
    A dump that stops growing once the whole game is in also counts as done
    (a playback build that halts at the replay's end). Raises if the dump
    never starts or stalls mid-game."""
    need_s = game_s + GAME_END_MARGIN_S
    started = time.time()
    last_bytes, last_growth = -1, time.time()
    while True:
        if job.should_stop():
            return "stopped"
        if proc.poll() is not None:
            return "exited"
        try:
            cur = os.path.getsize(audio_path)
        except OSError:
            cur = 0
        if cur != last_bytes:
            last_bytes, last_growth = cur, time.time()
        emulated = cur / AUDIO_BYTES_PER_SEC
        if emulated >= need_s:
            return "done"
        if emulated >= game_s - 0.25 and time.time() - last_growth > GAME_END_IDLE_S:
            return "done"
        if cur == 0 and time.time() - started > GAME_BOOT_TIMEOUT_S:
            raise RuntimeError("Dolphin never started recording "
                               "(is the playback Dolphin healthy?)")
        if cur > 0 and time.time() - last_growth > GAME_STALL_TIMEOUT_S:
            raise RuntimeError("recording stalled: Dolphin stopped playing")
        time.sleep(poll_s)


def _stop_proc(proc):
    """Park (a dying GL window flashes black where it sits), then end it."""
    if proc.poll() is None:
        try:
            from shared.ingame import embed
            embed.clear_active(proc.pid)
            embed.park_pid(proc.pid)
        except Exception:  # noqa: BLE001 — parking is cosmetic
            pass
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def _record_games(dolphin, iso_path, entries, compress, widescreen, out_dir, job):
    """Record each whole game of a playlist to its OWN video file: one
    Dolphin run per game against the shared ISO, stopped by the audio clock,
    then muxed (and compressed per game when asked) before the next game
    starts. Stop (the watch ``job`` asked to stop) ends the batch after saving
    the game in progress; every video already saved stays. Returns the saved
    paths."""
    total = len(entries)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    audio_path = os.path.join(_playback_user_dir(), "Dump", "Audio", "dspdump.wav")
    saved = []
    for i, entry in enumerate(entries, 1):
        if job.should_stop():
            break
        _clear_old_dumps()
        comm = _write_comm([entry])
        outcome = None
        proc = None
        try:
            job.progress(detail=f"Recording game {i} of {total}: starting Dolphin…",
                         phase="launching", batch_index=i)
            proc = _launch_playback(dolphin, comm, iso_path, job)
            job.progress(detail=f"Recording game {i} of {total}", phase="playing")
            outcome = _await_game_end(proc, game_seconds(entry), audio_path, job)
        finally:
            with _playback_lock:
                live = _playback_proc
            if live is not None:
                _stop_proc(live)
            _track(job, None)
            try:
                os.remove(comm)
            except OSError:
                pass
        # TerminateProcess leaves a readable AVI (index unwritten); give the
        # file a beat to close before ffmpeg opens it
        time.sleep(1)
        job.progress(detail=f"Saving game {i} of {total}"
                            + (" (compressing for Discord)…" if compress else "…"),
                     phase="cleaning")
        out = _collect_recording(
            entry["path"], compress=compress, widescreen=widescreen,
            name=game_recording_name(i, total, entry["path"], stamp),
            # a finished game is cut at its last frame; a stopped one is
            # saved as far as it got
            max_seconds=game_seconds(entry) if outcome == "done" else None,
            out_dir=out_dir)
        if out:
            saved.append(out)
            job.progress(recordings=list(saved), last_recording=out)
        if outcome == "exited" and not job.should_stop():
            crashed = _crash_message(proc.poll(), getattr(proc, "stderr_tail", ()))
            if crashed:
                raise RuntimeError(crashed)
        if outcome != "done":
            break
    return saved
