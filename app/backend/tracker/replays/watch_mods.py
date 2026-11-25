"""Watch-with-mods: build a fresh cosmetic ISO for ONE replay and play it.

Fully stateless by design (user decision): every watch builds a brand-new ISO
from the vanilla source, uses it once, and deletes everything afterwards. No
caching, no persistent projects.

To avoid touching the running app's open-project state, the build runs in a
SHORT-LIVED HEADLESS BACKEND WORKER (a second app.py process on its own
port — the exact pipeline the test harness uses), driven over REST:

    spawn worker -> setup ok -> project/create (temp, from vanilla ISO)
      -> project/open
      -> per selection: /import (appends) -> /reorder (swap into the replay's
         costume slot) -> /remove (delete displaced vanilla at the end)
      -> /export/start -> wait for that export job's ISO
    kill worker -> write playback comm file -> launch playback Slippi Dolphin
      (-i comm -b -e iso) -> wait for exit -> delete ISO + comm + project dir.

Costume-slot replacement is the crux: replays reference a costume INDEX, so
the chosen skin must occupy exactly that index in the built ISO.

Recording a playlist of WHOLE games saves one video per game: the ISO is
built once, then each game gets its own playback Dolphin run (see
_record_games).

Each watch is a ``replay_watch`` job (core/jobs.py): one at a time, its step
in the record's ``extra.phase``. The job owns the playback Dolphin it runs and
every playback setting it changes (dump flags, aspect ratio, Gecko overrides),
so they are put back when it ends, or at the next start if Nucleus died.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile

import requests

import file_retry
from core import jobs
from core.child_procs import own
from core.config import OUTPUT_PATH, PROJECT_ROOT

from ..store.slp_meta import parse_slp
from .dolphin_config import (_ASPECT_KEY, _clear_old_dumps, _dolphin_ini, _ensure_video_backend,
                             _force_aspect, _force_render_window, _game_settings_dir, _gfx_ini,
                             _playback_user_dir, _read_ini_key, _restore_aspect, _set_dump_flags,
                             _user_overrides, playback_dolphin_path, remove_playback_overrides,
                             write_playback_overrides)
from .playback import (FIRST_SLIPPI_FRAME, _await_game_end, _crash_message, _launch_playback,
                       _record_games, _stop_proc, _track, _write_comm, close_left_running,
                       game_seconds, stop_playback)
from .recording import _collect_recording


# tracker/replays/watch_mods.py -> backend/
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKER_BOOT_TIMEOUT_S = 120
EXPORT_TIMEOUT_S = 15 * 60
WATCH_KIND = "replay_watch"
# The Combo Video final render's job kind (tracker/video/combo_video/assemble.py
# registers it). Named here so a watch can check for one without importing
# Combo Video, which a stable build does not carry.
COMBO_RENDER_KIND = "combo_video_render"


def _clean_watch(name, value):
    """Undo what a watch still owned when it ended or Nucleus died (core/jobs.py):
    the playback Dolphin it ran, then each setting it changed."""
    if name == "dolphin":
        return close_left_running(value)
    if name == "dump_flags":
        # Dumping is only ever on for a Nucleus recording, so off is its old value.
        if os.path.exists(value):
            _set_dump_flags(False, value)
            return "The playback Dolphin's recording settings were put back."
    elif name == "aspect":
        if os.path.exists(value["ini"]):
            _restore_aspect(value["ini"], value["prior"])
    elif name == "overrides":
        remove_playback_overrides(value["dir"], value["prior"])
    return None


# A Cancel (the popup's Stop, or the jobs list) closes the playback Dolphin the
# job is waiting on; the job then ends through its own function.
jobs.register_kind(WATCH_KIND, label="Replay playback", cleanup=_clean_watch,
                   on_cancel=lambda job: stop_playback())


class Busy(Exception):
    """Playback is taken: by a running watch (``job_id``) or a final render."""

    def __init__(self, message, job_id=None):
        super().__init__(message)
        self.job_id = job_id


def sweep_stale_artifacts():
    """Delete leftovers from watch jobs whose cleanup never ran (backend was
    killed mid-watch, machine rebooted, ...). In-use files (Dolphin still has
    the ISO open) simply fail to delete and get swept next time. Also sweeps
    the pre-rename 'nucleoid' prefixes."""
    import glob
    for pattern in ("nucleome_watch_*.iso", "nucleoid_watch_*.iso"):
        for path in glob.glob(str(OUTPUT_PATH / pattern)):
            try:
                os.remove(path)
            except OSError:
                pass
    projects = PROJECT_ROOT / "projects"
    for prefix in ("nucleome-watch-", "nucleoid-watch-"):
        for path in glob.glob(str(projects / f"{prefix}*")):
            shutil.rmtree(path, ignore_errors=True)


# run once when the backend imports this module
threading.Thread(target=sweep_stale_artifacts, daemon=True,
                 name="nucleome-watch-sweep").start()


class _Worker:
    """A short-lived headless backend instance on its own port.

    app.py gates every /api route on an X-Nucleus-Token header, so the worker
    is handed a token WE choose rather than one it is left to find: this
    process may have been given its token by Electron or generated its own,
    and a worker that generates a different one 401s every call. That is what
    broke watch-with-mods from 0.8.0 (when the gate landed) onward -- the
    worker booted fine, and the readiness probe below 401ed for 60 seconds
    before reporting "REST never became ready"."""

    def __init__(self):
        self.proc = None
        self.port = None
        self.token = secrets.token_hex(32)

    def start(self):
        # Tied to this backend: a crash must not leave a second backend
        # building into the data folder (core/child_procs).
        self.proc = own(subprocess.Popen(
            [sys.executable, "app.py"], cwd=BACKEND_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            # It is this backend again, so it keeps Nucleus's settings (data root, gates), with a token of its own
            # and without the window's key: nothing it does is the person's decision in the window.
            env={**{k: v for k, v in os.environ.items() if k.upper() != "NUCLEUS_UI_APPROVAL_KEY"},
                 "NUCLEUS_BACKEND_TOKEN": self.token, "NUCLEUS_WORKER": "1"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        self.port, boot_error = self._await_port()
        if not self.port:
            self.stop()
            raise RuntimeError("build worker never announced a port"
                               + (f" ({boot_error})" if boot_error else ""))
        # drain stdout in the background so the pipe never blocks the worker
        threading.Thread(target=lambda: [None for _ in self.proc.stdout],
                         daemon=True).start()
        # wait until REST is actually up. The probe gets a SHORT timeout of its
        # own: with api()'s 300 s default, one worker that accepts the
        # connection and then stalls blows straight past this deadline.
        deadline = time.time() + 60
        last = None
        while time.time() < deadline:
            try:
                self.api("GET", "/api/mex/status", timeout=5)
                return
            except requests.RequestException as exc:
                last = exc
                time.sleep(1)
        self.stop()
        raise RuntimeError(f"build worker REST never became ready ({last})")

    def _await_port(self):
        """(port, error) — port is None if the worker never announced one.

        Read on a thread because `for line in stdout` blocks: the deadline can
        only be tested between lines, so a worker that prints nothing at all
        would hang here forever. The reader's own failure is carried back
        instead of dying inside the thread, where the caller would see only
        "never announced a port" and lose the actual cause."""
        found = {}

        def read():
            try:
                for line in self.proc.stdout:
                    if line.startswith("BACKEND_PORT:"):
                        found["port"] = int(line.split(":", 1)[1].strip())
                        return
                found.setdefault("error", "worker stdout closed with no port")
            except Exception as exc:  # malformed port line, stream error
                found["error"] = f"{type(exc).__name__}: {exc}"

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(WORKER_BOOT_TIMEOUT_S)
        return found.get("port"), found.get("error")

    def api(self, method, route, body=None, timeout=300):
        url = f"http://127.0.0.1:{self.port}{route}"
        resp = requests.request(method, url, json=body, timeout=timeout,
                                headers={"X-Nucleus-Token": self.token})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(f"{route} failed: {data.get('error')}")
        return data

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


def _await_export(worker, artifact_id, job=None):
    """Block until the worker's export finishes; return the ISO it actually wrote.

    The `filename` handed to /export/start is only a suggested save name — the
    exporter writes output/artifacts/<artifactId>.iso and reports the real path
    in its job's result (`artifactId` is the export job's id; see
    projects/install/export_job.py). Watching for a file named after `filename`
    meant waiting the full EXPORT_TIMEOUT_S for a file nobody was ever going to
    write, and made a FAILED export look identical to one still running."""
    deadline = time.time() + EXPORT_TIMEOUT_S
    while time.time() < deadline:
        export = worker.api("GET", f"/api/jobs/{artifact_id}", timeout=60).get("job") or {}
        status = export.get("status")
        if status == "done":
            path = (export.get("result") or {}).get("path")
            if not path or not os.path.exists(path):
                raise RuntimeError("export reported complete but wrote no ISO")
            return path
        if status in ("failed", "cancelled", "interrupted"):
            raise RuntimeError(f"export failed: {export.get('error') or status}")
        fraction = export.get("progress")
        if job is not None:
            job.check_stop()
            if isinstance(fraction, (int, float)) and fraction > 0:
                job.progress(detail=f"Building the ISO… {int(fraction * 100)}%", phase="exporting")
        time.sleep(2)
    raise RuntimeError("export timed out — the ISO never finished building")


def _extract_stage_data(zip_path):
    """The stage file inside a vault stage zip: its first .dat/.usd member by name."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith((".dat", ".usd")))
        if not names:
            raise RuntimeError(f"no .dat/.usd stage file found in {zip_path}")
        return zf.read(names[0])


def _override_playback(job, record, widescreen, anonymize, no_music):
    """Set the playback Dolphin up for this run. The job owns each change
    before making it, with what was there before, so its end (or the next
    start, if Nucleus dies first) puts exactly that back (_clean_watch)."""
    if record:
        _clear_old_dumps()
        ini = _dolphin_ini()
        job.own("dump_flags", ini)
        _set_dump_flags(True, ini)
    gfx = _gfx_ini()
    if (record or widescreen) and gfx:
        job.own("aspect", {"ini": gfx, "prior": _read_ini_key(gfx, *_ASPECT_KEY)})
        _force_aspect(gfx, widescreen=widescreen)
    gs_dir = _game_settings_dir()
    if (anonymize or widescreen or no_music) and gs_dir:
        job.own("overrides", {"dir": gs_dir, "prior": _user_overrides(gs_dir)})
        write_playback_overrides(gs_dir, hide_names=anonymize, widescreen=widescreen,
                                 no_music=no_music)


def _whole_game_entry(replay_path):
    """The queue entry for recording ``replay_path`` whole, as a playlist's
    whole games are played (first Slippi frame to the metadata's lastFrame),
    so the recording stops at the game's end and is cut to its length. None
    when the replay's length is unknown (no metadata footer, an unreadable
    file): that recording runs until the user stops it, as before."""
    try:
        last = parse_slp(replay_path).get("last_frame")
    except Exception:  # noqa: BLE001 - any unreadable replay keeps the old way
        return None
    if not isinstance(last, int) or last <= FIRST_SLIPPI_FRAME:
        return None
    return {"path": replay_path, "startFrame": FIRST_SLIPPI_FRAME, "endFrame": last}


def _run_job(job, replay_path, vanilla_iso, selections, stage=None, record=False,
             clip=None, compress=False, anonymize=False, widescreen=False,
             split_games=False, out_dir=None, no_music=False):
    """The watch job's work (core/jobs.py). Returns ``{last_recording,
    recordings}``.

    selections: [{fighter, slot, costume_path}] — fighter is the app's
    display name ('Fox'), slot is the replay's costume index for that player,
    costume_path is the vault zip on disk.

    stage (optional): {code, ext, zip_path, name} — a vault stage variant to
    install as the replay stage's DEFAULT file (same 'default-replacement'
    recipe as the duel assembler: write the Gr file straight into the
    project's files dir; the replay still plays the same stage id, it just
    looks different). May also be a LIST of such dicts (a playlist spanning
    several stages installs all of them into the one ISO).

    With NO selections and NO stage this is a plain watch: no worker, no
    build — the vanilla ISO plays directly (and is never deleted).

    record=True flips the playback Dolphin's frame+audio dump flags on for
    this run, then muxes the dump into the recording folder afterwards
    (``out_dir``, the folder chosen when the job started; default: the
    configured one).

    clip (optional): (start_frame, end_frame) — play just that slice of the
    replay via the playback Dolphin's queue mode (the Combos tab's "watch
    this combo").

    split_games=True (with record and a playlist ``clip`` of WHOLE games):
    record each game to its own file — see _record_games.

    anonymize / widescreen / no_music: playback Gecko overrides (hide player
    names, 16:9, music off) for watching and recording alike; put back when
    the job ends, like the recording settings (_override_playback)."""
    worker = None
    project_dir = None
    iso_path = None
    delete_iso = False
    comm_path = None
    try:
        if not selections and not stage:
            iso_path = vanilla_iso
        else:
            delete_iso = True
            job.progress(detail="Starting build worker…", phase="starting-worker")
            worker = _Worker()
            worker.start()
            job.check_stop()

            job.progress(detail="Creating a fresh project from the vanilla ISO…",
                         phase="creating-project")
            name = f"nucleome-watch-{uuid.uuid4().hex[:8]}"
            created = worker.api("POST", "/api/mex/project/create",
                                 {"isoPath": vanilla_iso, "projectName": name},
                                 timeout=600)
            project_path = created["projectPath"]
            project_dir = os.path.dirname(project_path)
            worker.api("POST", "/api/mex/project/open", {"projectPath": project_path},
                       timeout=300)

            _install_selections(worker, selections, stage, project_dir, job)
            job.check_stop()

            job.progress(detail="Building the ISO… (this takes a minute or two)",
                         phase="exporting")
            iso_name = f"nucleome_watch_{uuid.uuid4().hex[:8]}.iso"
            started = worker.api("POST", "/api/mex/export/start",
                                 {"filename": iso_name})
            iso_path = _await_export(worker, started["artifactId"], job)

            worker.stop()
            worker = None

        job.check_stop()
        job.progress(detail="Launching Slippi playback…", phase="launching")
        dolphin = playback_dolphin_path()
        if not dolphin:
            raise RuntimeError("Slippi playback Dolphin not found "
                               "(is the Slippi Launcher installed?)")
        _force_render_window()
        _ensure_video_backend()
        _override_playback(job, record, widescreen, anonymize, no_music)
        if split_games and record and isinstance(clip, list) and clip:
            # a playlist of WHOLE games: one video file per game (and one
            # Discord-sized encode per game), the one ISO for every game
            saved = _record_games(dolphin, iso_path, clip, compress, widescreen,
                                  out_dir, job)
            return {"last_recording": saved[-1] if saved else None, "recordings": saved}
        # Recording a whole game: play it as a one-game queue so the audio
        # clock can stop Dolphin at the game's end (otherwise the dump runs on
        # through "Waiting for game..." until the user presses Stop).
        whole = _whole_game_entry(replay_path) if record and not clip else None
        if clip:
            # queue mode: `clip` is either ONE (start, end) slice of
            # replay_path, or a full playlist [{path, startFrame,
            # endFrame}, ...] spanning any number of replays (the
            # coach's queue_clips tool)
            if isinstance(clip, list) and clip and isinstance(clip[0], dict):
                entries = clip
            else:
                entries = [{"path": replay_path,
                            "startFrame": int(clip[0]),
                            "endFrame": int(clip[1])}]
            comm_path = _write_comm(entries)
        elif whole:
            comm_path = _write_comm([whole])
        else:
            fd, comm_path = tempfile.mkstemp(suffix=".json", prefix="nucleome_comm_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"mode": "normal", "replay": replay_path,
                           "isRealTimeMode": False,
                           "commandId": uuid.uuid4().hex}, f)
        proc = _launch_playback(dolphin, comm_path, iso_path, job)
        if job.should_stop():   # cancelled while it was launching
            stop_playback()

        game_done = False
        if whole:
            job.progress(detail="Recording — it stops by itself at the end of the game.",
                         phase="playing")
            audio = os.path.join(_playback_user_dir() or "", "Dump", "Audio", "dspdump.wav")
            try:
                game_done = _await_game_end(proc, game_seconds(whole), audio, job) == "done"
            except Exception:
                _stop_proc(proc)    # a dump that never started or stalled
                raise
            if game_done:
                _stop_proc(proc)
        else:
            job.progress(detail="Playing — close this popup when you're done.", phase="playing")
        rc = proc.wait()
        _track(job, None)
        # Stop's terminate exits nonzero too, and so does ours at a game's
        # end: only an exit nobody asked for is a crash.
        crashed = None if (job.should_stop() or game_done) else _crash_message(
            rc, getattr(proc, "stderr_tail", ()))
        job.progress(detail="Cleaning up…", phase="cleaning")
        recording = None
        if record:
            job.progress(detail="Saving the recording…")
            if game_done:
                # TerminateProcess leaves a readable AVI (index unwritten);
                # give the file a beat to close before ffmpeg opens it
                time.sleep(1)
            try:
                recording = _collect_recording(
                    replay_path, compress=compress, widescreen=widescreen, out_dir=out_dir,
                    # a finished game is cut at its last frame; a stopped
                    # one is saved as far as it got
                    max_seconds=game_seconds(whole) if game_done else None)
            except Exception:
                if not crashed:   # after a crash, the crash is the error to show
                    raise
        if crashed:
            raise RuntimeError(crashed + (" What was recorded before it stopped was saved."
                                          if recording else ""))
        return {"last_recording": recording, "recordings": [recording] if recording else []}
    except jobs.Cancelled:
        raise
    except Exception as e:
        saved = job.extra.get("recordings") or []
        kept = (f" ({len(saved)} game video"
                f"{'s' if len(saved) != 1 else ''} kept in the recording folder.)"
                if saved else "")
        raise RuntimeError(f"{type(e).__name__}: {e}{kept}") from e
    finally:
        # The playback settings go back when the job ends (_clean_watch).
        _track(job, None)
        if worker:
            worker.stop()
        cleanup = [comm_path] + ([iso_path] if delete_iso else [])
        for path in cleanup:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        if project_dir and os.path.isdir(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)


def _install_selections(worker, selections, stage, project_dir, job=None):
    """Install each selection (and the stage variants) into the worker's open
    project, reporting each step on the watch ``job`` when there is one."""
    for i, sel in enumerate(selections):
        if job is not None:
            job.progress(detail=f"Installing skin {i + 1}/{len(selections)} "
                                f"({sel['fighter']})…", phase="installing")
        worker.api("POST", "/api/mex/import",
                   {"fighter": sel["fighter"], "costumePath": sel["costume_path"]},
                   timeout=600)
        costumes = worker.api(
            "GET", f"/api/mex/fighters/{requests.utils.quote(sel['fighter'])}/costumes")
        count = len(costumes.get("costumes") or [])
        appended = count - 1
        slot = sel["slot"]
        if slot >= count:
            # Replays from a modded build can reference a costume index past
            # the vanilla roster (e.g. Fox slot 8). Imports append, so pad
            # with repeat imports until a copy lands exactly AT the slot —
            # the fillers below it are never loaded by the replay.
            while count <= slot:
                worker.api("POST", "/api/mex/import",
                           {"fighter": sel["fighter"],
                            "costumePath": sel["costume_path"]},
                           timeout=600)
                count += 1
        elif appended != slot:
            # swap the new skin into the replay's costume slot, then drop
            # the displaced vanilla costume (now at the appended index)
            worker.api("POST", "/api/mex/reorder",
                       {"fighter": sel["fighter"], "fromIndex": appended,
                        "toIndex": slot}, timeout=120)
            worker.api("POST", "/api/mex/remove",
                       {"fighter": sel["fighter"], "costumeIndex": appended},
                       timeout=120)

    # stage: one variant (single-replay watch) or a list of variants (a
    # playlist can span several stages — each is a distinct Gr file, so they
    # all coexist in the one ISO).
    stages = stage if isinstance(stage, list) else ([stage] if stage else [])
    for st in stages:
        if job is not None:
            job.progress(detail=f"Installing stage skin ({st['name']})…", phase="installing")
        from pathlib import Path
        data = _extract_stage_data(Path(st["zip_path"]))
        files_dir = Path(project_dir) / "files"
        # Stadium ships under BOTH extensions (.usd EN / .dat JP — the
        # saved-language crash); everyone else uses their single root ext.
        exts = (".usd", ".dat") if st["code"] == "GrPs" else (st["ext"],)
        for ext in exts:
            file_retry.retry_locked((files_dir / f"{st['code']}{ext}").write_bytes, data)


def start_job(replay_path, vanilla_iso, selections, stage=None, record=False,
              clip=None, compress=False, anonymize=False, widescreen=False,
              split_games=False, out_dir=None, no_music=False):
    """Start a watch job; returns its id. Raises Busy while another watch
    runs or a final render holds the playback Dolphin.

    split_games: record a playlist of whole games as one video per game.
    out_dir: the recording folder for this job (default: the configured one)."""
    if jobs.active_job(COMBO_RENDER_KIND) is not None:
        raise Busy("a final render is using Dolphin — wait for it to finish")
    batch = bool(split_games and record and isinstance(clip, list) and clip)
    try:
        return jobs.start(
            WATCH_KIND,
            lambda job: _run_job(job, replay_path, vanilla_iso, selections, stage, record,
                                 clip, compress, anonymize, widescreen, batch, out_dir, no_music),
            label="Replay recording" if record else "Replay playback",
            params={"replay": replay_path, "record": bool(record),
                    "widescreen": bool(widescreen), "batch_total": len(clip) if batch else 0},
            single=True, thread_name="nucleome-watch-mods")
    except jobs.JobBusy as busy:
        raise Busy("a watch build is already running", busy.job_id) from None


def stop_job(job_id=None):
    """Stop the running watch (only if it is ``job_id``, when given): close its
    Dolphin; a recording batch saves the game in progress and starts no more.
    Returns whether a watch was stopped."""
    job = jobs.active_job(WATCH_KIND)
    if job is None or (job_id and job.id != job_id):
        return False
    jobs.cancel(job.id)   # closes the Dolphin (on_cancel)
    return True
