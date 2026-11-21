"""The Tracker's long passes as jobs (core/jobs.py): the replay scan, the combo
pass and deep stats. A start answers with its job id, a second start while one
runs is refused with the running job, and a pass reports its counters at most
twice a second (tracker/store/pass_progress.py). Temp database, no replays.
"""
import sys
import threading
import time

import pytest
from flask import Flask

import tracker.routes.nucleome as bp_module
from core import jobs
from tracker.combos import combo_index
from tracker.stats import deep_stats
from tracker.store import indexer, pass_progress
from tracker.store.pass_progress import PassProgress


# --- PassProgress -------------------------------------------------------------

class _Job:
    def __init__(self):
        self.sent = []

    def progress(self, fraction=None, detail=None, **extra):
        self.sent.append((fraction, detail, extra))


def test_a_pass_reports_at_most_every_half_second_unless_forced(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(pass_progress.time, "monotonic", lambda: clock[0])
    job = _Job()
    progress = PassProgress(job, "games", failed=0)

    progress.report(total=10)                       # the first always goes
    progress.report(done=1)                         # 0 s later: held
    clock[0] += 0.4
    progress.report(done=2)                         # 0.4 s later: still held
    assert len(job.sent) == 1
    clock[0] += 0.1
    progress.report(done=3)                         # 0.5 s: goes, with the latest
    progress.add(failed=1)
    progress.report(force=True, done=4)             # forced: goes at once
    assert job.sent == [
        (0.0, "0 / 10 games", {"total": 10, "done": 0, "failed": 0}),
        (0.3, "3 / 10 games", {"total": 10, "done": 3, "failed": 0}),
        (0.4, "4 / 10 games", {"total": 10, "done": 4, "failed": 1}),
    ]
    assert progress.counts == {"total": 10, "done": 4, "failed": 1}


def test_a_pass_with_no_total_yet_is_indeterminate():
    job = _Job()
    PassProgress(job, "files").report(force=True, done=5)
    assert job.sent == [(None, None, {"total": 0, "done": 5})]


# --- the start routes -----------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(bp_module, "NUCLEOME_ENABLED", True)
    release = threading.Event()
    app = Flask(__name__)
    app.register_blueprint(bp_module.nucleome_bp)
    test_client = app.test_client()
    test_client.release = release
    yield test_client
    release.set()


def _held(release):
    """A pass body that runs until the test lets it go."""
    def body(job, *_args):
        release.wait(5)
        return {}
    return body


def _wait(job_id):
    deadline = time.time() + 5
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record and record["status"] in jobs.FINAL:
            return record
        time.sleep(0.01)
    raise AssertionError(jobs.get(job_id))


def test_a_replay_scan_answers_its_job_and_a_second_start_names_the_running_one(
        client, tmp_path, monkeypatch):
    seen = []

    def scan(job, replay_dir):
        seen.append(replay_dir)
        client.release.wait(5)
        return {}
    monkeypatch.setattr(indexer, "_scan", scan)
    replays = tmp_path / "Slippi"
    replays.mkdir()

    first = client.post("/api/nucleome/replays/scan", json={"dir": str(replays)})
    assert first.status_code == 200
    body = first.get_json()
    assert body["started"] is True and body["dir"] == str(replays)
    job_id = body["job_id"]
    assert jobs.get(job_id)["kind"] == indexer.SCAN_KIND
    assert jobs.get(job_id)["params"] == {"dir": str(replays)}

    second = client.post("/api/nucleome/replays/scan", json={"dir": str(replays)})
    assert second.status_code == 409
    assert second.get_json()["job_id"] == job_id
    client.release.set()
    assert _wait(job_id)["status"] == "done"
    assert seen == [str(replays)]


def test_a_replay_scan_of_a_missing_folder_starts_nothing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "start_scan", lambda _dir: pytest.fail("started a scan"))
    response = client.post("/api/nucleome/replays/scan", json={"dir": str(tmp_path / "gone")})
    assert response.status_code == 400
    assert jobs.list_jobs(kind=indexer.SCAN_KIND) == []


def test_a_combo_pass_answers_its_job_and_a_second_start_names_the_running_one(
        client, monkeypatch):
    monkeypatch.setattr(combo_index, "_scan", _held(client.release))
    first = client.post("/api/nucleome/combos/scan")
    assert first.status_code == 200
    job_id = first.get_json()["job_id"]
    assert jobs.get(job_id)["kind"] == combo_index.SCAN_KIND

    second = client.post("/api/nucleome/combos/scan")
    assert second.status_code == 409
    assert second.get_json()["job_id"] == job_id
    client.release.set()
    assert _wait(job_id)["status"] == "done"


def test_deep_stats_answers_its_job_and_a_busy_start_carries_the_running_record(
        client, monkeypatch):
    monkeypatch.setitem(sys.modules, "peppi_py", sys.modules.get("peppi_py") or object())
    monkeypatch.setattr(deep_stats, "_mine", _held(client.release))
    first = client.post("/api/nucleome/deep/start", json={"character": 20})
    assert first.status_code == 200
    job_id = first.get_json()["job_id"]
    assert jobs.get(job_id)["params"] == {"character": 20}
    assert deep_stats.active_mining()["id"] == job_id

    second = client.post("/api/nucleome/deep/start", json={"character": 2})
    assert second.status_code == 409
    body = second.get_json()
    assert body["started"] is False and "already running" in body["reason"]
    assert body["job"]["id"] == job_id and body["job"]["status"] == "running"
    client.release.set()
    assert _wait(job_id)["status"] == "done"
    assert deep_stats.active_mining() is None



def test_a_combo_pass_ends_with_its_counts_as_the_job_result(client, tmp_path, monkeypatch):
    """The counters the window showed while it ran are the record's result."""
    from tracker.store import scan_pool
    present = tmp_path / "game.slp"
    present.write_bytes(b"slp")
    broken = tmp_path / "broken.slp"
    broken.write_bytes(b"slp")
    games = [{"id": n, "path": str(path), "mtime": 1.0, "players": "[]"}
             for n, path in enumerate((present, broken, tmp_path / "gone.slp"), start=1)]
    monkeypatch.setattr(combo_index, "_ensure_frame_basis", lambda conn: None)
    monkeypatch.setattr(combo_index, "_candidates", lambda conn: games)
    monkeypatch.setattr(combo_index, "_store_game_combos", lambda conn, game, extracted: None)
    combos = [{"moves": [1, 2, 3, 4]}, {"moves": [1, 2]}]
    monkeypatch.setattr(scan_pool, "run", lambda fn, path, ports: (
        (combos, None) if path == str(present) else (None, "peppi: truncated replay")))

    record = jobs.run_inline(combo_index.SCAN_KIND, combo_index._scan)
    assert record["status"] == "done"
    assert record["result"] == {"total": 3, "done": 3, "found": 1, "failed": 1}
    assert record["extra"] == record["result"]
    assert record["progress"] == 1.0
