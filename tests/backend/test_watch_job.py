"""A watch is a ``replay_watch`` job (core/jobs.py). Stop names the job it
stops; what a watch changed in the playback Dolphin (dump flags, aspect ratio,
Gecko overrides, the Dolphin itself) is put back when it ends, or at the next
start when Nucleus died with it running."""
import json

import psutil
import pytest

from core import jobs
from core import state as core_state
from tests.gated import needs
from tracker.replays import dolphin_config, playback, recording, watch_mods


@pytest.fixture(autouse=True)
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_root_override", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(core_state, "get_socketio", lambda: None)
    return tmp_path / "jobs"


@pytest.fixture
def user(tmp_path, monkeypatch):
    user = tmp_path / "User"
    (user / "Config").mkdir(parents=True)
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    return user


def _running_job():
    job = jobs.Job(watch_mods.WATCH_KIND)
    job.status = "running"
    jobs._jobs[job.id] = job
    return job


# ---------------------------------------------------------------------------
# after a crash: the next start puts the playback Dolphin back
# ---------------------------------------------------------------------------

def _die(job_dir, job):
    """Rewrite the job's record as one a dead process left running."""
    path = job_dir / f"{job.id}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(status="running", owner={"pid": 999999999, "created": 1.0})
    path.write_text(json.dumps(record), encoding="utf-8")


def test_recovery_turns_off_the_dump_flags_a_dead_recording_left_on(job_dir, user):
    dol = str(user / "Config" / "Dolphin.ini")
    gfx = str(user / "Config" / "GFX.ini")
    dolphin_config._set_ini_keys(gfx, {dolphin_config._ASPECT_KEY: "3"})
    gs = user / "GameSettings"
    gs.mkdir()
    mine = b"[Gecko_Enabled]\n$Mine \xe9\n"
    (gs / "GALE01.ini").write_bytes(mine)

    # a recording sets the playback Dolphin up, then Nucleus dies mid-game
    job = jobs.Job(watch_mods.WATCH_KIND, label="Replay recording")
    watch_mods._override_playback(job, record=True, widescreen=True, anonymize=True,
                                  no_music=False)
    assert dolphin_config._read_ini_key(dol, "Movie", "DumpFrames") == "True"
    assert dolphin_config._read_ini_key(gfx, "Settings", "AspectRatio") == "1"
    assert b"SSBM Nucleus" in (gs / "GALE01.ini").read_bytes()
    _die(job_dir, job)

    recovered = jobs.recover_interrupted()
    assert [r["id"] for r in recovered] == [job.id]
    assert dolphin_config._read_ini_key(dol, "Movie", "DumpFrames") == "False"
    assert dolphin_config._read_ini_key(dol, "DSP", "DumpAudio") == "False"
    assert dolphin_config._read_ini_key(gfx, "Settings", "AspectRatio") == "3"
    assert (gs / "GALE01.ini").read_bytes() == mine
    assert not (gs / "GALE01r2.ini").exists()
    record = jobs.get(job.id)
    assert record["status"] == "interrupted" and record["owned"] == {}
    assert record["notes"] == ["The playback Dolphin's recording settings were put back."]

    # idempotent: a second start finds nothing left to do
    assert jobs.recover_interrupted() == []
    assert dolphin_config._read_ini_key(dol, "Movie", "DumpFrames") == "False"
    assert (gs / "GALE01.ini").read_bytes() == mine


def test_recovery_only_restores_what_the_watch_changed(job_dir, user):
    """A plain watch (no options) owns nothing, so recovery touches nothing."""
    gfx = str(user / "Config" / "GFX.ini")
    dolphin_config._set_ini_keys(gfx, {dolphin_config._ASPECT_KEY: "3"})
    job = jobs.Job(watch_mods.WATCH_KIND)
    watch_mods._override_playback(job, record=False, widescreen=False, anonymize=False,
                                  no_music=False)
    assert job.owned == {}
    jobs._persist(job)
    _die(job_dir, job)
    dolphin_config._set_ini_keys(gfx, {dolphin_config._ASPECT_KEY: "2"})  # the user's change
    jobs.recover_interrupted()
    assert dolphin_config._read_ini_key(gfx, "Settings", "AspectRatio") == "2"
    assert not (user / "Config" / "Dolphin.ini").exists()


class _FakeProcess:
    killed = []

    def __init__(self, pid):
        if pid != 4242:
            raise psutil.NoSuchProcess(pid)
        self.pid = pid

    def create_time(self):
        return 100.0

    def exe(self):
        return r"C:\Slippi\playback\Slippi Dolphin.exe"

    def kill(self):
        _FakeProcess.killed.append(self.pid)

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def processes(monkeypatch):
    _FakeProcess.killed = []
    monkeypatch.setattr(psutil, "Process", _FakeProcess)
    return _FakeProcess.killed


def test_a_playback_dolphin_left_running_is_closed(processes):
    owned = {"pid": 4242, "created": 100.2, "exe": r"C:\Slippi\playback\Slippi Dolphin.exe"}
    assert watch_mods._clean_watch("dolphin", owned)
    assert processes == [4242]


@pytest.mark.parametrize("owned", [
    {"pid": 4242, "created": 50.0, "exe": r"C:\Slippi\playback\Slippi Dolphin.exe"},
    {"pid": 4242, "created": 100.0, "exe": r"C:\Games\Dolphin.exe"},
    {"pid": 7, "created": 100.0, "exe": r"C:\Slippi\playback\Slippi Dolphin.exe"},
])
def test_a_reused_pid_is_never_killed(processes, owned):
    assert watch_mods._clean_watch("dolphin", owned) is None
    assert processes == []


# ---------------------------------------------------------------------------
# Stop, and one Dolphin user at a time
# ---------------------------------------------------------------------------

def test_stop_only_stops_the_watch_it_names(monkeypatch):
    closed = []
    monkeypatch.setattr(watch_mods, "stop_playback", lambda: closed.append(1) or True)
    job = _running_job()
    assert watch_mods.stop_job("an-older-watch") is False
    assert not job.should_stop() and closed == []
    assert watch_mods.stop_job(job.id) is True
    assert job.should_stop() and closed == [1]


def test_a_cancel_from_the_jobs_list_closes_the_watchs_dolphin_too(monkeypatch):
    """The job waits on Dolphin, so the jobs list's Cancel is the popup's Stop."""
    closed = []
    monkeypatch.setattr(watch_mods, "stop_playback", lambda: closed.append(1) or True)
    job = _running_job()
    assert jobs.cancel(job.id) is True
    assert job.should_stop() and closed == [1]


def test_stop_with_no_watch_running_closes_nothing(monkeypatch):
    monkeypatch.setattr(watch_mods, "stop_playback", lambda: pytest.fail("closed a Dolphin"))
    assert watch_mods.stop_job("watch-1") is False


def test_a_second_watch_is_refused_with_the_running_ones_id():
    job = _running_job()
    with pytest.raises(watch_mods.Busy) as busy:
        watch_mods.start_job("g.slp", "vanilla.iso", [])
    assert busy.value.job_id == job.id


def test_a_watch_waits_for_a_final_render():
    render = jobs.Job(watch_mods.COMBO_RENDER_KIND)   # Combo Video's final render (combo_video/assemble.py)
    render.status = "running"
    jobs._jobs[render.id] = render
    with pytest.raises(watch_mods.Busy, match="final render"):
        watch_mods.start_job("g.slp", "vanilla.iso", [])
    assert jobs.active_job(watch_mods.WATCH_KIND) is None


@needs('combo_video')
def test_a_final_render_waits_for_a_watch():
    from tracker.video.combo_video import assemble
    _running_job()
    job_id, error = assemble.start_export("timeline-1")
    assert job_id is None and "watch job" in error


class _SyncThread:
    def __init__(self, target, args=(), **_kw):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class _Dolphin:
    """A playback Dolphin that has already played: wait() is its exit code."""
    def __init__(self, rc=0, stop=False):
        self.rc, self.stop = rc, stop

    def wait(self):
        if self.stop:   # Stop pressed while it plays
            jobs.cancel(jobs.active_job(watch_mods.WATCH_KIND).id)
        return self.rc


@pytest.fixture
def no_dolphin(monkeypatch, user):
    """jobs.start runs the watch inline, with no ISO build and no Dolphin."""
    monkeypatch.setattr(jobs.threading, "Thread", _SyncThread)
    for _mod in (watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "playback_dolphin_path", lambda: "dolphin.exe")
        monkeypatch.setattr(_mod, "_force_render_window", lambda: None)
    monkeypatch.setattr(watch_mods, "_ensure_video_backend", lambda: None)
    for _mod in (playback, watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "_clear_old_dumps", lambda: None)
    monkeypatch.setattr(watch_mods, "_launch_playback", lambda *a: _Dolphin())
    monkeypatch.setattr(watch_mods, "_collect_recording", lambda *a, **kw: "out/g.mp4")


def test_a_watch_records_its_job_and_result(no_dolphin, user):
    """End to end through jobs.start: the id comes back at once, the record
    carries the watch's params, and the result names the recording."""

    job_id = watch_mods.start_job("g.slp", "vanilla.iso", [], record=True, widescreen=True)
    record = jobs.get(job_id)
    assert record["kind"] == watch_mods.WATCH_KIND and record["label"] == "Replay recording"
    assert record["params"]["widescreen"] is True and record["params"]["record"] is True
    assert record["status"] == "done" and record["owned"] == {}
    assert record["result"] == {"last_recording": "out/g.mp4", "recordings": ["out/g.mp4"]}
    dol = str(user / "Config" / "Dolphin.ini")
    assert dolphin_config._read_ini_key(dol, "Movie", "DumpFrames") == "False"


def test_a_dolphin_that_crashes_while_playing_fails_the_watch(no_dolphin, monkeypatch):
    """A nonzero exit nobody asked for is an error, not a finished watch;
    Stop's terminate (nonzero too) still ends it done."""
    monkeypatch.setattr(watch_mods, "_launch_playback", lambda *a: _Dolphin(rc=3))
    record = jobs.get(watch_mods.start_job("g.slp", "vanilla.iso", [], record=True))
    assert record["status"] == "failed"
    assert "stopped unexpectedly (code 3)" in record["error"]
    assert "recorded before it stopped was saved" in record["error"]

    monkeypatch.setattr(watch_mods, "_launch_playback", lambda *a: _Dolphin(rc=1, stop=True))
    assert jobs.get(watch_mods.start_job("g.slp", "vanilla.iso", []))["status"] == "done"


def test_a_combo_video_install_leaves_watch_free(monkeypatch):
    """A Combo Video final render installs its skins through the same helper,
    with no watch job: a failed install there leaves Watch free to start."""
    class _Worker:
        def api(self, *a, **kw):
            raise RuntimeError("import failed")

    class _NoThread:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            pass

    sel = {"fighter": "Fox", "costume_path": "fox.zip", "slot": 0}
    with pytest.raises(RuntimeError, match="import failed"):
        watch_mods._install_selections(_Worker(), [sel], None, "project")
    assert jobs.active_job(watch_mods.WATCH_KIND) is None
    monkeypatch.setattr(jobs.threading, "Thread", _NoThread)
    assert watch_mods.start_job("g.slp", "vanilla.iso", [])
