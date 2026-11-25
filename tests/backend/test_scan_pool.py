"""The scan worker is where untrusted replays are parsed (security review item
4, tracker/store/scan_pool.py).

peppi_py dies outright on some crafted .slp files. Before, a worker that died
latched the pool "broken" and every later call ran INLINE, in the serving
process: the next crafted file took the backend down. Now:

  - nothing ever runs in this process (WorkerUnavailable instead);
  - a call that crashes or outlives its timeout is ScanFailed, the worker is
    killed and replaced;
  - that file is quarantined by path, size and mtime, so it is refused at
    once until it changes;
  - calls take turns, so a crash is never blamed on another file;
  - a burst that loses a worker re-runs its unfinished jobs one at a time.

These run real spawned workers (scan_pool_tasks.py holds what they run).
"""
import json
import os
import threading
import time

import psutil
import pytest

from core import jobs
from tests.backend import scan_pool_tasks as tasks
from tracker.store import scan_pool


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.delenv("NUCLEUS_SCAN_INPROC", raising=False)
    monkeypatch.setattr(scan_pool, "QUARANTINE_PATH", tmp_path / "scan_quarantine.json")
    monkeypatch.setattr(scan_pool, "_unavailable_until", 0.0)
    return scan_pool


def _file(tmp_path, name, data=b"slp"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _quarantined(path):
    return scan_pool.quarantined(scan_pool.file_key(path))


# --- the shared worker -------------------------------------------------------

def test_a_crash_is_scan_failed_and_the_file_is_quarantined_until_it_changes(pool, tmp_path):
    bad = _file(tmp_path, "bad.slp")
    with pytest.raises(scan_pool.ScanFailed, match="bad.slp crashed the replay worker"):
        scan_pool.run(tasks.crash, bad)
    entry = _quarantined(bad)
    assert entry["what"] == "crashed the replay worker" and entry["task"] == "crash"
    saved = json.loads((tmp_path / "scan_quarantine.json").read_text(encoding="utf-8"))
    assert [e["path"] for e in saved["files"]] == [scan_pool.file_key(bad)[0]]

    # refused at once, without a worker: the task never runs
    marker = tmp_path / "ran"
    with pytest.raises(scan_pool.ScanFailed, match="before"):
        scan_pool.run(tasks.touch_then, bad, str(marker))
    assert not marker.exists()

    # the next file gets a fresh worker, not this process
    assert scan_pool.run(tasks.pid, _file(tmp_path, "good.slp")) != os.getpid()

    # a changed file is a new key and is read again
    with open(bad, "ab") as f:
        f.write(b"more")
    assert scan_pool.run(tasks.echo, bad) == "bad.slp"


def test_a_hang_is_killed_at_the_timeout_and_quarantined(pool, tmp_path):
    slow = _file(tmp_path, "slow.slp")
    started = time.monotonic()
    with pytest.raises(scan_pool.ScanFailed, match="ran past 2 seconds and was stopped"):
        scan_pool.run(tasks.hang, slow, timeout=2)
    assert time.monotonic() - started < 60
    worker = int((tmp_path / "slow.slp.pid").read_text())
    assert not psutil.pid_exists(worker) or psutil.Process(worker).status() == psutil.STATUS_ZOMBIE
    assert _quarantined(slow)["what"] == "ran past 2 seconds"
    assert scan_pool.run(tasks.echo, _file(tmp_path, "next.slp")) == "next.slp"


def test_the_tasks_own_error_is_raised_as_is_and_blames_nobody(pool, tmp_path):
    path = _file(tmp_path, "odd.slp")
    before = scan_pool.run(tasks.pid, path)
    with pytest.raises(OSError, match="the task's own error for odd.slp"):
        scan_pool.run(tasks.raise_oserror, path)
    assert _quarantined(path) is None
    assert scan_pool.run(tasks.pid, path) == before          # same worker, not replaced


def test_calls_take_turns_so_a_crash_is_only_ever_its_own_files(pool, tmp_path):
    bad, good = _file(tmp_path, "bad.slp"), _file(tmp_path, "good.slp")
    scan_pool.run(tasks.pid, good)                           # a worker is up
    results = {}

    def call(name, fn, *args):
        try:
            results[name] = scan_pool.run(fn, *args)
        except Exception as e:                               # noqa: BLE001
            results[name] = e

    threads = [threading.Thread(target=call, args=("good", tasks.echo, good, 0.5)),
               threading.Thread(target=call, args=("bad", tasks.crash, bad))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert results["good"] == "good.slp"
    assert isinstance(results["bad"], scan_pool.ScanFailed)
    assert _quarantined(bad) and _quarantined(good) is None


def test_nothing_runs_here_when_no_worker_can_start(pool, tmp_path, monkeypatch):
    path, marker = _file(tmp_path, "game.slp"), tmp_path / "ran"
    made = []

    def cannot_start(workers):
        made.append(workers)
        raise OSError("no processes for you")

    monkeypatch.setattr(scan_pool, "_pool", None)
    monkeypatch.setattr(scan_pool, "_new_pool", cannot_start)
    with pytest.raises(scan_pool.WorkerUnavailable, match="could not start"):
        scan_pool.run(tasks.touch_then, path, str(marker))
    # cooling down: refused again without trying to start another
    with pytest.raises(scan_pool.WorkerUnavailable, match="trying again in"):
        scan_pool.run(tasks.touch_then, path, str(marker))
    assert made == [1]
    assert not marker.exists() and _quarantined(path) is None


def test_a_worker_that_dies_starting_is_not_blamed_on_the_file(pool, tmp_path, monkeypatch):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    path, marker = _file(tmp_path, "game.slp"), tmp_path / "ran"
    made = []

    def dies_starting(workers):
        made.append(workers)
        return ProcessPoolExecutor(max_workers=workers,
                                   mp_context=multiprocessing.get_context("spawn"),
                                   initializer=os._exit, initargs=(7,))

    monkeypatch.setattr(scan_pool, "_pool", None)
    monkeypatch.setattr(scan_pool, "_new_pool", dies_starting)
    with pytest.raises(scan_pool.WorkerUnavailable):
        scan_pool.run(tasks.touch_then, path, str(marker))
    assert len(made) == 2                   # the call's worker, then the ping's
    assert not marker.exists() and _quarantined(path) is None
    with pytest.raises(scan_pool.WorkerUnavailable):
        scan_pool.run(tasks.touch_then, path, str(marker))
    assert len(made) == 2                   # cooling down


def test_the_quarantine_keeps_the_newest_entries(pool, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_pool, "QUARANTINE_MAX", 2)
    paths = [_file(tmp_path, f"g{i}.slp") for i in range(3)]
    for p in paths:
        scan_pool._quarantine(scan_pool.file_key(p), tasks.crash, "crashed the replay worker")
    assert [bool(_quarantined(p)) for p in paths] == [False, True, True]


def test_the_test_switch_still_runs_inline(pool, tmp_path, monkeypatch):
    monkeypatch.setenv("NUCLEUS_SCAN_INPROC", "1")
    assert scan_pool.run(tasks.pid, _file(tmp_path, "g.slp")) == os.getpid()


# --- bursts ------------------------------------------------------------------

def test_a_burst_that_loses_a_worker_reruns_the_rest_alone(pool, tmp_path):
    names = ["g0.slp", "g1.slp", "bad2.slp", "g3.slp", "g4.slp"]
    paths = [_file(tmp_path, n) for n in names]
    out = []
    with scan_pool.burst(2) as burst:
        jobs_ = [burst.submit(tasks.crash_if_bad, p) for p in paths]
        for job in jobs_:
            try:
                out.append(job.result())
            except scan_pool.ScanFailed as e:
                out.append(type(e).__name__)
    assert out == ["g0.slp", "g1.slp", "ScanFailed", "g3.slp", "g4.slp"]
    assert [bool(_quarantined(p)) for p in paths] == [False, False, True, False, False]
    # a quarantined file is not handed to a burst worker again
    with scan_pool.burst(2) as burst:
        with pytest.raises(scan_pool.ScanFailed):
            burst.submit(tasks.crash_if_bad, paths[2]).result()


# --- the passes that use it --------------------------------------------------

def _index(tmp_path, monkeypatch, run):
    from tracker.store import indexer
    replays = tmp_path / "replays"
    replays.mkdir()
    (replays / "bad.slp").write_bytes(b"bad")
    (replays / "good.slp").write_bytes(b"good")
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(indexer, "_initialized_paths", set())
    monkeypatch.setattr(scan_pool, "run", run)
    record = jobs.run_inline(indexer.SCAN_KIND, lambda job: indexer._scan(job, str(replays)))
    conn = indexer.connect()
    try:
        rows = {os.path.basename(r["path"]): (r["parse_ok"], r["parse_error"])
                for r in conn.execute("SELECT path, parse_ok, parse_error FROM games")}
    finally:
        conn.close()
    return record, rows


def test_the_index_records_a_file_that_killed_the_worker_as_failed(tmp_path, monkeypatch):
    def run(fn, path):
        if path.endswith("bad.slp"):
            raise scan_pool.ScanFailed("bad.slp crashed the replay worker", path)
        return {"players": []}, None

    record, rows = _index(tmp_path, monkeypatch, run)
    assert record["status"] == "done"
    assert rows == {"bad.slp": (0, "bad.slp crashed the replay worker"), "good.slp": (1, None)}


def test_the_index_stops_and_records_nothing_without_a_worker(tmp_path, monkeypatch):
    def run(fn, path):
        raise scan_pool.WorkerUnavailable("the replay worker could not start")

    record, rows = _index(tmp_path, monkeypatch, run)
    assert record["status"] == "failed" and "could not start" in record["error"]
    assert rows == {}                    # nothing marked unparseable for good


def test_the_combo_pass_stops_without_a_worker_and_counts_a_killer_as_failed(tmp_path, monkeypatch):
    from tracker.combos import combo_index
    games = [{"id": n, "path": _file(tmp_path, name), "mtime": 1.0, "players": "[]"}
             for n, name in enumerate(("bad.slp", "good.slp"), start=1)]
    stamped = []
    monkeypatch.setattr(combo_index, "_ensure_frame_basis", lambda conn: None)
    monkeypatch.setattr(combo_index, "_candidates", lambda conn: games)
    monkeypatch.setattr(combo_index, "_store_game_combos", lambda conn, game, extracted: None)

    class Conn:
        def execute(self, sql, params=()):
            stamped.append(params[1])

        def commit(self):
            pass

        def close(self):
            pass

    from tracker.store import indexer
    monkeypatch.setattr(indexer, "connect", lambda: Conn())

    def killer(fn, path, ports):
        if path.endswith("bad.slp"):
            raise scan_pool.ScanFailed("bad.slp crashed the replay worker", path)
        return [], None

    monkeypatch.setattr(scan_pool, "run", killer)
    record = jobs.run_inline(combo_index.SCAN_KIND, combo_index._scan)
    assert record["status"] == "done" and record["result"]["failed"] == 1
    assert stamped == [1]

    stamped.clear()

    def no_worker(fn, path, ports):
        raise scan_pool.WorkerUnavailable("the replay worker could not start")

    monkeypatch.setattr(scan_pool, "run", no_worker)
    record = jobs.run_inline(combo_index.SCAN_KIND, combo_index._scan)
    assert record["status"] == "failed" and stamped == []


def test_the_vault_derive_refuses_a_killer_and_stops_without_a_worker(monkeypatch):
    from tracker.cloud import vault_sync

    def killer(fn, path):
        raise scan_pool.ScanFailed("crashed the replay worker", path)

    monkeypatch.setattr(scan_pool, "run", killer)
    assert vault_sync._derive_offprocess("bad.slp") is None      # ledgered as refused

    class Job:
        def __init__(self, exc):
            self.exc = exc

        def result(self):
            raise self.exc

    assert vault_sync._derived(Job(scan_pool.ScanFailed("crashed"))) is None
    with pytest.raises(scan_pool.WorkerUnavailable):
        vault_sync._derived(Job(scan_pool.WorkerUnavailable("could not start")))

    def no_worker(fn, path):
        raise scan_pool.WorkerUnavailable("could not start")

    monkeypatch.setattr(scan_pool, "run", no_worker)
    with pytest.raises(scan_pool.WorkerUnavailable):
        vault_sync._derive_offprocess("game.slp")
