"""Recording a playlist of WHOLE games saves one video per game.

The ISO is built once; each game then gets its own playback Dolphin run (the
playback build never exits at queue end, so the audio dump is the clock), is
muxed to its own file -- compressed per game for Discord when asked -- and
Stop ends the batch keeping every finished video. No Dolphin, no ffmpeg here:
the launch/wait/collect seams are faked.
"""
import json
import uuid
from pathlib import Path

import pytest
from flask import Flask

import tracker.routes.nucleome as bp_module
import tracker.routes.watch as watch_routes
from core import jobs
from core import state as core_state
from tracker.store import indexer
from tracker.replays import dolphin_config, playback, recording, watch_mods


@pytest.fixture(autouse=True)
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_root_override", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(core_state, "get_socketio", lambda: None)
    return tmp_path / "jobs"


def _running_job():
    """A watch job as the batch loop sees it (running, stoppable)."""
    job = jobs.Job(watch_mods.WATCH_KIND)
    job.status = "running"
    jobs._jobs[job.id] = job
    return job


# ---------------------------------------------------------------------------
# naming + durations
# ---------------------------------------------------------------------------

def test_game_seconds_counts_every_frame_from_minus_123():
    # -123..-123 is one frame; a 60-frame game past the lead-in is 184 frames
    assert playback.game_seconds({"endFrame": -123}) == pytest.approx(1 / 60)
    assert playback.game_seconds({"endFrame": 60}) == pytest.approx(184 / 60)


def test_recording_names_sort_in_play_order_and_share_the_batch_stamp():
    names = [playback.game_recording_name(i, 12, rf"C:\slp\Game_{g}.slp",
                                          "20260921-120000")
             for i, g in ((1, "B"), (2, "A"), (10, "C"))]
    assert names == ["playlist_20260921-120000_01_Game_B",
                     "playlist_20260921-120000_02_Game_A",
                     "playlist_20260921-120000_10_Game_C"]
    assert sorted(names) == names


def test_recording_name_pads_to_the_batch_size():
    assert playback.game_recording_name(7, 150, "/x/g.slp", "s") == "playlist_s_007_g"


# ---------------------------------------------------------------------------
# Discord budget per game
# ---------------------------------------------------------------------------

def _estimated_bytes(plan, seconds):
    video_kbps, audio_kbps, _h = plan
    return (video_kbps + audio_kbps) * 1000 / 8 * seconds


@pytest.mark.parametrize("seconds", [20, 90, 180, 300, 420, 480, 600])
def test_compress_plan_fits_the_cap_for_any_game_length(seconds):
    """A flat 120 kbps floor under 96 kbps audio overshot 10 MB for games
    longer than ~6 minutes; every length a match can run must fit."""
    plan = recording._compress_plan(seconds)
    assert _estimated_bytes(plan, seconds) <= recording._COMPRESS_TARGET_BYTES


def test_compress_plan_keeps_short_games_at_480p_with_full_audio():
    video_kbps, audio_kbps, height = recording._compress_plan(30)
    assert height == 480 and audio_kbps == recording._COMPRESS_AUDIO_KBPS
    assert video_kbps > 1000


def test_compress_plan_steps_down_for_long_games():
    _v, audio_kbps, height = recording._compress_plan(480)
    assert height < 480 and audio_kbps < recording._COMPRESS_AUDIO_KBPS


def test_compress_plan_unknown_duration_is_none():
    assert recording._compress_plan(None) is None
    assert recording._compress_plan(0) is None


def test_compress_plan_without_audio_spends_it_all_on_video():
    v_with, a_with, _ = recording._compress_plan(60, has_audio=True)
    v_without, a_without, _ = recording._compress_plan(60, has_audio=False)
    assert a_without == 0 and v_without > v_with


# ---------------------------------------------------------------------------
# the batch loop
# ---------------------------------------------------------------------------

class _FakeProc:
    pid = 4242

    def poll(self):
        return 0  # already gone: _stop_proc has nothing to do


@pytest.fixture
def batch(tmp_path, monkeypatch):
    user = tmp_path / "User"
    user.mkdir()
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    for _mod in (playback, watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "_clear_old_dumps", lambda: None)
    monkeypatch.setattr(watch_mods.time, "sleep", lambda s: None)
    calls = {"launch": [], "collect": [], "outcomes": [], "job": _running_job()}

    def fake_launch(dolphin, comm, iso, job=None):
        with open(comm, encoding="utf-8") as f:
            calls["launch"].append((iso, json.load(f)))
        proc = _FakeProc()
        playback._set_playback(proc)
        return proc

    def fake_wait(proc, game_s, audio_path, job, poll_s=1.0):
        return calls["outcomes"].pop(0) if calls["outcomes"] else "done"

    def fake_collect(replay_path, compress=False, widescreen=False, name=None,
                     max_seconds=None, out_dir=None):
        calls["collect"].append(dict(replay=replay_path, compress=compress,
                                     widescreen=widescreen, name=name,
                                     max_seconds=max_seconds, out_dir=out_dir))
        return str(Path(out_dir) / f"{name}.mp4")

    for _mod in (playback, watch_mods):
        monkeypatch.setattr(_mod, "_launch_playback", fake_launch)
    monkeypatch.setattr(playback, "_await_game_end", fake_wait)
    for _mod in (playback, watch_mods):
        monkeypatch.setattr(_mod, "_collect_recording", fake_collect)
    yield calls
    playback._set_playback(None)


def _games(n):
    return [{"path": rf"C:\slp\Game_{i}.slp", "startFrame": -123,
             "endFrame": 1000 + i, "game_id": i, "full": True}
            for i in range(1, n + 1)]


def test_every_game_is_its_own_dolphin_run_and_its_own_file(batch):
    job = batch["job"]
    saved = playback._record_games("dolphin.exe", "shared.iso", _games(3),
                                   compress=True, widescreen=True,
                                   out_dir=r"D:\clips", job=job)
    # one launch per game, each a single-entry queue, all on the ONE iso
    assert [iso for iso, _ in batch["launch"]] == ["shared.iso"] * 3
    queues = [comm["queue"] for _, comm in batch["launch"]]
    assert [len(q) for q in queues] == [1, 1, 1]
    assert [q[0]["path"] for q in queues] == [g["path"] for g in _games(3)]
    assert all(comm["mode"] == "queue" for _, comm in batch["launch"])
    # one file per game, each compressed on its own, cut at its last frame
    assert len(saved) == 3 and len(set(saved)) == 3
    for i, c in enumerate(batch["collect"], 1):
        assert c["compress"] is True and c["widescreen"] is True
        assert c["out_dir"] == r"D:\clips"
        assert c["max_seconds"] == pytest.approx((1000 + i + 124) / 60)
        assert c["name"].endswith(f"_{i:02d}_Game_{i}")
    assert job.extra["recordings"] == saved
    assert job.extra["batch_index"] == 3


def test_stop_keeps_finished_games_and_saves_the_one_in_progress(batch):
    batch["outcomes"] = ["done", "stopped"]
    saved = playback._record_games("d", "iso", _games(5), False, False, "out", batch["job"])
    assert len(saved) == 2                      # game 3+ never started
    assert len(batch["launch"]) == 2
    # the stopped game is saved as far as it got (no cut)
    assert batch["collect"][1]["max_seconds"] is None


def test_a_stop_between_games_starts_nothing_more(batch, monkeypatch):
    real_collect = playback._collect_recording

    def collect_then_stop(*a, **kw):
        jobs.cancel(batch["job"].id)              # Stop pressed while saving
        return real_collect(*a, **kw)

    for _mod in (playback, watch_mods):
        monkeypatch.setattr(_mod, "_collect_recording", collect_then_stop)
    saved = playback._record_games("d", "iso", _games(4), False, False, "out", batch["job"])
    assert len(saved) == 1 and len(batch["launch"]) == 1


def test_dolphin_closed_by_the_user_ends_the_batch(batch):
    batch["outcomes"] = ["exited"]
    saved = playback._record_games("d", "iso", _games(3), False, False, "out", batch["job"])
    assert len(saved) == 1 and len(batch["launch"]) == 1


def test_dolphin_crashing_mid_game_fails_the_batch(batch, monkeypatch):
    """A nonzero exit nobody asked for is an error, not a user close; the
    game is still saved as far as it got."""
    batch["outcomes"] = ["exited"]
    monkeypatch.setattr(_FakeProc, "poll", lambda self: 3)
    with pytest.raises(RuntimeError, match=r"stopped unexpectedly \(code 3\)"):
        playback._record_games("d", "iso", _games(3), False, False, "out", batch["job"])
    assert len(batch["collect"]) == 1 and batch["collect"][0]["max_seconds"] is None


def test_stop_between_games_reaches_the_batch_with_no_dolphin_open(batch, monkeypatch):
    """Stop pressed while a game is being saved (no Dolphin running) still ends
    the batch: it asks the job to stop, not just the Dolphin."""
    playback._set_playback(None)
    assert watch_mods.stop_job(batch["job"].id) is True
    assert batch["job"].should_stop()
    assert playback._record_games("d", "iso", _games(2), False, False, "out", batch["job"]) == []


def test_stop_while_dolphin_starts_saves_the_game_instead_of_failing(tmp_path, monkeypatch):
    """Stop (or closing the popup) inside the launch grace kills Dolphin
    during startup: that is a stop, not a failed start."""
    job = _running_job()

    class _Killed:
        pid = 4242
        stderr = None

        def poll(self):
            return 1                      # terminated by Stop

    def popen(*a, **kw):
        jobs.cancel(job.id)               # Stop pressed while Dolphin starts
        return _Killed()

    user = tmp_path / "User"
    user.mkdir()
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    monkeypatch.setattr(playback, "_clear_old_dumps", lambda: None)
    monkeypatch.setattr(playback.subprocess, "Popen", popen)
    monkeypatch.setattr(playback, "_track", lambda *a: None)
    monkeypatch.setattr(playback, "_drain_stderr", lambda proc: [])
    monkeypatch.setattr(playback.time, "sleep", lambda s: None)
    monkeypatch.setattr(playback, "_collect_recording", lambda *a, **kw: "out/game1.mp4")
    saved = playback._record_games("d", "iso", _games(3), False, False, "out", job)
    assert saved == ["out/game1.mp4"]


# ---------------------------------------------------------------------------
# the job: one ISO, settings restored
# ---------------------------------------------------------------------------

def test_split_job_restores_playback_settings(tmp_path, monkeypatch):
    user = tmp_path / "User"
    (user / "Config").mkdir(parents=True)
    gfx = user / "Config" / "GFX.ini"
    gfx.write_text("[Settings]\nAspectRatio = 3\n", encoding="utf-8")
    for _mod in (dolphin_config, playback, recording):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    for _mod in (watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "playback_dolphin_path", lambda: "dolphin.exe")
    seen = {}

    def fake_record(dolphin, iso, entries, compress, widescreen, out_dir, job):
        # during the batch: dumping on, 16:9 forced, widescreen code enabled
        dol = str(user / "Config" / "Dolphin.ini")
        seen["dump"] = dolphin_config._read_ini_key(dol, "Movie", "DumpFrames")
        seen["aspect"] = dolphin_config._read_ini_key(str(gfx), "Settings", "AspectRatio")
        seen["ws_ini"] = (user / "GameSettings" / "GALE01.ini").exists()
        seen.update(iso=iso, n=len(entries), compress=compress, out_dir=out_dir)
        return ["g1.mp4", "g2.mp4"]

    monkeypatch.setattr(watch_mods, "_record_games", fake_record)
    record = jobs.run_inline(watch_mods.WATCH_KIND, lambda job: watch_mods._run_job(
        job, "g1.slp", "vanilla.iso", [], record=True, clip=_games(2),
        compress=True, widescreen=True, split_games=True, out_dir="out"))
    assert seen == {"dump": "True", "aspect": "1", "ws_ini": True,
                    "iso": "vanilla.iso", "n": 2, "compress": True,
                    "out_dir": "out"}
    # afterwards: dump flags off, the user's aspect back, our override gone
    dol = str(user / "Config" / "Dolphin.ini")
    assert dolphin_config._read_ini_key(dol, "Movie", "DumpFrames") == "False"
    assert dolphin_config._read_ini_key(str(gfx), "Settings", "AspectRatio") == "3"
    assert not (user / "GameSettings" / "GALE01.ini").exists()
    assert record["status"] == "done" and record["owned"] == {}
    assert record["result"] == {"last_recording": "g2.mp4", "recordings": ["g1.mp4", "g2.mp4"]}


# ---------------------------------------------------------------------------
# the endpoint decides per-game vs one video, and pins the folder
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    test_dir = Path(__file__).parent / f".per-game-tmp-{uuid.uuid4().hex[:8]}"
    test_dir.mkdir()
    db_path = test_dir / "nucleome.db"
    monkeypatch.setattr(indexer, "DB_PATH", db_path)
    app = Flask(__name__)
    app.register_blueprint(bp_module.nucleome_bp)
    iso = test_dir / "vanilla.iso"
    iso.write_bytes(b"x")
    monkeypatch.setattr(watch_routes, "_launcher_vanilla_iso", lambda: str(iso))
    monkeypatch.setattr(watch_routes, "load_metadata", lambda: {})
    for gid, last in ((1, 8000), (2, 5400)):
        slp = test_dir / f"game{gid}.slp"
        slp.write_bytes(b"x")
        conn = indexer.connect()
        try:
            conn.execute(
                "INSERT INTO games (id, path, mtime, size, parse_ok, start_at,"
                " stage, is_teams, last_frame, duration_s, players) VALUES"
                " (?, ?, 0, 1, 1, '2026-09-01T10:00:00', 31, 0, ?, 1, ?)",
                (gid, str(slp), last,
                 json.dumps([{"port": 0, "character": 2, "costume": 1}])))
            conn.commit()
        finally:
            conn.close()
    seen = {}

    def fake_start(path, vanilla, selections, **kw):
        seen.clear()
        seen.update(kw)
        return "watch-1"

    monkeypatch.setattr(watch_mods, "start_job", fake_start)
    yield app.test_client(), test_dir, seen
    indexer._initialized_paths.discard(str(db_path))
    for p in sorted(test_dir.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink(missing_ok=True)
    test_dir.rmdir()


FULL = [{"game_id": 1, "full": True}, {"game_id": 2, "full": True}]
COMBOS = [{"game_id": 1, "start_frame": 500, "end_frame": 700}]


def test_recording_whole_games_splits_into_the_chosen_folder(client):
    c, d, seen = client
    folder = str(d / "my clips")
    r = c.post("/api/nucleome/watch-mods/playlist-start",
               json={"clips": FULL, "record": True, "compress": True,
                     "record_dir": folder})
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["job_id"] == "watch-1"
    assert body["per_game"] is True and body["record_dir"] == folder
    assert seen["split_games"] is True and seen["out_dir"] == folder
    assert seen["compress"] is True
    assert Path(folder).is_dir()
    assert recording.recording_dir() == folder     # remembered for next time


def test_combo_playlists_keep_one_video(client):
    c, _d, seen = client
    r = c.post("/api/nucleome/watch-mods/playlist-start",
               json={"clips": COMBOS, "record": True})
    assert r.status_code == 200
    assert seen["split_games"] is False


def test_watching_without_recording_never_splits(client):
    c, _d, seen = client
    r = c.post("/api/nucleome/watch-mods/playlist-start", json={"clips": FULL})
    assert r.status_code == 200
    assert seen["split_games"] is False and seen["out_dir"] is None


def test_no_music_reaches_the_job_from_both_start_routes(client):
    c, _d, seen = client
    r = c.post("/api/nucleome/watch-mods/start",
               json={"game_id": 1, "record": True, "no_music": True,
                     "widescreen": True, "anonymize": True})
    assert r.status_code == 200, r.get_json()
    assert seen["no_music"] is True and seen["widescreen"] is True
    assert seen["anonymize"] is True
    r = c.post("/api/nucleome/watch-mods/playlist-start",
               json={"clips": COMBOS, "no_music": True})
    assert r.status_code == 200, r.get_json()
    assert seen["no_music"] is True
    # absent = music on, for both routes
    c.post("/api/nucleome/watch-mods/start", json={"game_id": 1})
    assert seen["no_music"] is False
    c.post("/api/nucleome/watch-mods/playlist-start", json={"clips": COMBOS})
    assert seen["no_music"] is False


def test_relative_recording_folder_is_refused(client):
    c, _d, _seen = client
    r = c.post("/api/nucleome/watch-mods/playlist-start",
               json={"clips": FULL, "record": True, "record_dir": "clips"})
    assert r.status_code == 400


def test_both_start_routes_answer_the_job_id(client):
    c, _d, _seen = client
    r = c.post("/api/nucleome/watch-mods/start", json={"game_id": 1})
    assert r.status_code == 200 and r.get_json()["job_id"] == "watch-1"


def test_a_busy_start_names_the_running_watch(client, monkeypatch):
    c, _d, _seen = client

    def busy(*a, **kw):
        raise watch_mods.Busy("a watch build is already running", "watch-0")

    monkeypatch.setattr(watch_mods, "start_job", busy)
    for route, body in (("start", {"game_id": 1}), ("playlist-start", {"clips": FULL})):
        r = c.post(f"/api/nucleome/watch-mods/{route}", json=body)
        assert r.status_code == 409
        assert r.get_json()["job_id"] == "watch-0"


def test_stop_names_the_watch_it_stops(client, monkeypatch):
    c, _d, _seen = client
    monkeypatch.setattr(watch_mods, "stop_playback", lambda: True)
    job = _running_job()
    assert c.post("/api/nucleome/watch-mods/stop", json={}).status_code == 400
    r = c.post("/api/nucleome/watch-mods/stop", json={"job_id": "an-older-watch"})
    assert r.get_json() == {"stopped": False} and not job.should_stop()
    r = c.post("/api/nucleome/watch-mods/stop", json={"job_id": job.id})
    assert r.get_json() == {"stopped": True} and job.should_stop()


def test_the_old_status_route_is_gone(client):
    c, _d, _seen = client
    assert c.get("/api/nucleome/watch-mods/status").status_code == 404


# ---------------------------------------------------------------------------
# the audio clock
# ---------------------------------------------------------------------------

class _LiveProc:
    def poll(self):
        return None


@pytest.fixture
def clock(tmp_path, monkeypatch):
    """A fake dspdump.wav whose size advances on each poll."""
    audio = tmp_path / "dspdump.wav"
    now = {"t": 1000.0}
    monkeypatch.setattr(watch_mods.time, "time", lambda: now["t"])
    for _mod in (playback, recording):
        monkeypatch.setattr(_mod, "AUDIO_BYTES_PER_SEC", 100)  # small files

    def feed(seconds_per_poll):
        it = iter(seconds_per_poll)
        total = {"s": 0.0}

        def sleep(_s):
            now["t"] += 1.0
            total["s"] += next(it, 0.0)
            audio.write_bytes(b"\0" * int(total["s"] * recording.AUDIO_BYTES_PER_SEC))
        monkeypatch.setattr(watch_mods.time, "sleep", sleep)
    yield audio, feed


def test_game_is_done_once_the_margin_is_emulated(clock):
    audio, feed = clock
    feed([1.0] * 100)
    assert playback._await_game_end(_LiveProc(), 10.0, str(audio), _running_job()) == "done"
    emulated = audio.stat().st_size / recording.AUDIO_BYTES_PER_SEC
    assert emulated >= 10.0 + playback.GAME_END_MARGIN_S


def test_a_dump_that_halts_after_the_last_frame_counts_as_done(clock):
    audio, feed = clock
    feed([2.0] * 5)          # 10 s of game, then nothing more
    assert playback._await_game_end(_LiveProc(), 10.0, str(audio), _running_job()) == "done"


def test_a_dump_that_halts_mid_game_is_a_stall(clock):
    audio, feed = clock
    feed([1.0] * 3)
    with pytest.raises(RuntimeError, match="stalled"):
        playback._await_game_end(_LiveProc(), 10.0, str(audio), _running_job())


def test_stop_wins_over_the_clock(clock):
    audio, feed = clock
    feed([1.0] * 100)
    job = _running_job()
    jobs.cancel(job.id)
    assert playback._await_game_end(_LiveProc(), 10.0, str(audio), job) == "stopped"


# ---------------------------------------------------------------------------
# one whole game recorded from the Replays tab: stopped and cut at its end
# (hand check 11-20: a 45 s game saved 3:39, the rest "Waiting for game...")
# ---------------------------------------------------------------------------

class _EndedProc:
    pid = 4343
    stderr_tail = ()

    def __init__(self, rc):
        self.rc = rc

    def poll(self):
        return self.rc

    def wait(self, timeout=None):
        return self.rc


@pytest.fixture
def single(tmp_path, monkeypatch):
    user = tmp_path / "User"
    (user / "Config").mkdir(parents=True)
    for _mod in (dolphin_config, playback, recording, watch_mods):
        monkeypatch.setattr(_mod, "_playback_user_dir", lambda: str(user))
    for _mod in (watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "playback_dolphin_path", lambda: "dolphin.exe")
        monkeypatch.setattr(_mod, "_force_render_window", lambda: None)
    monkeypatch.setattr(watch_mods, "_ensure_video_backend", lambda: None)
    for _mod in (playback, watch_mods, dolphin_config):
        monkeypatch.setattr(_mod, "_clear_old_dumps", lambda: None)
    monkeypatch.setattr(watch_mods.time, "sleep", lambda s: None)
    seen = {"comm": None, "waited": None, "stopped": [], "collect": None,
            "outcome": "done", "rc": 1, "user": user}

    def fake_parse(path):
        if isinstance(seen.get("last_frame"), Exception):
            raise seen["last_frame"]
        return {"last_frame": seen.get("last_frame", 1077)}

    def fake_launch(dolphin, comm, iso, job=None):
        with open(comm, encoding="utf-8") as f:
            seen["comm"] = json.load(f)
        return _EndedProc(seen["rc"])

    def fake_wait(proc, game_s, audio_path, job, poll_s=1.0):
        seen["waited"] = (game_s, audio_path)
        return seen["outcome"]

    def fake_collect(replay_path, compress=False, widescreen=False, name=None,
                     max_seconds=None, out_dir=None):
        seen["collect"] = {"replay": replay_path, "max_seconds": max_seconds}
        return "out/g.mp4"

    monkeypatch.setattr(watch_mods, "parse_slp", fake_parse)
    monkeypatch.setattr(watch_mods, "_launch_playback", fake_launch)
    monkeypatch.setattr(watch_mods, "_await_game_end", fake_wait)
    monkeypatch.setattr(watch_mods, "_stop_proc", lambda proc: seen["stopped"].append(proc.pid))
    monkeypatch.setattr(watch_mods, "_collect_recording", fake_collect)
    return seen


def _record_one(record=True):
    return jobs.run_inline(watch_mods.WATCH_KIND, lambda job: watch_mods._run_job(
        job, "g.slp", "vanilla.iso", [], record=record))


def test_a_recorded_game_stops_by_itself_and_is_cut_at_its_last_frame(single):
    done = _record_one()
    game_s = (1077 + 123 + 1) / 60
    # played as a one-game queue from the first Slippi frame to lastFrame
    assert single["comm"]["mode"] == "queue"
    assert single["comm"]["queue"] == [{"path": "g.slp", "startFrame": -123, "endFrame": 1077}]
    # the audio clock is the playback user's dump, and Dolphin is stopped at the end
    assert single["waited"][0] == pytest.approx(game_s)
    assert Path(single["waited"][1]) == single["user"] / "Dump" / "Audio" / "dspdump.wav"
    assert single["stopped"] == [4343]
    assert single["collect"] == {"replay": "g.slp", "max_seconds": pytest.approx(game_s)}
    # our own terminate (nonzero exit) is not a crash
    assert done["status"] == "done", done.get("error")
    assert done["result"] == {"last_recording": "out/g.mp4", "recordings": ["out/g.mp4"]}


def test_a_recording_whose_dolphin_was_closed_early_keeps_what_it_got(single):
    single.update(outcome="exited", rc=0)
    done = _record_one()
    assert single["stopped"] == []
    assert single["collect"] == {"replay": "g.slp", "max_seconds": None}
    assert done["status"] == "done"


def test_a_dolphin_that_dies_mid_recording_is_still_a_crash(single):
    single.update(outcome="exited", rc=3)
    done = _record_one()
    assert done["status"] == "failed"
    assert "stopped unexpectedly (code 3)" in done["error"]


@pytest.mark.parametrize("last_frame", [None, -200, ValueError("no metadata footer")])
def test_a_replay_of_unknown_length_records_as_before_until_stop(single, last_frame):
    single.update(last_frame=last_frame, rc=0)
    done = _record_one()
    assert single["comm"]["mode"] == "normal" and single["comm"]["replay"] == "g.slp"
    assert single["waited"] is None and single["stopped"] == []
    assert single["collect"] == {"replay": "g.slp", "max_seconds": None}
    assert done["status"] == "done"


def test_watching_without_recording_is_unchanged(single):
    single.update(last_frame=AssertionError("a plain watch never reads the replay"), rc=0)
    done = _record_one(record=False)
    assert single["comm"]["mode"] == "normal"
    assert single["waited"] is None and single["collect"] is None
    assert done["status"] == "done"
