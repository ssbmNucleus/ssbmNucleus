"""The automatic cloud upload must never stop, or stall, without saying so.

2026-10-04..15: the backend lost its copy of the Patreon token, the open-app
loop kept indexing every ten minutes, and nothing was uploaded for eleven days
without one line in the log. When the owner pressed Sync, the panel then sat on
"Uploading to your vault: 0 games" for the minute or two the cold reconcile
took. These pin the signals that make both visible, and the order that puts new
games ahead of the slow metadata refresh. The sync and the chain are jobs
(core/jobs.py), so the tests read their records. No network: vault_client is
stubbed.
"""
import logging
import sqlite3
import threading
import time

import pytest

from core import jobs
from tracker.combos import combo_index
from tracker.store import indexer, pass_progress
from tracker.cloud import vault_client, vault_jobs, vault_sync


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    # a private job table, so a test's sync never leaks into the next one
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(vault_jobs, "_blocked_reason", None)
    monkeypatch.setattr(vault_jobs, "_rerun_requested", False)
    monkeypatch.setattr(vault_jobs, "_POLL_S", 0.01)
    # These pin the frames chain, which still runs when raw upload is off or
    # the server refuses it. The raw chain (the default) is in
    # test_vault_raw_wiring.py.
    _kv(**{vault_client.RAW_UPLOAD_KEY: False})
    return tmp_path


def _kv(**values):
    conn = indexer.connect()
    try:
        for key, value in values.items():
            indexer.kv_set(conn, key, value)
    finally:
        conn.close()


def _wait(job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record and record["status"] in jobs.FINAL:
            return record
        time.sleep(0.01)
    raise AssertionError(jobs.get(job_id))


def _sync(token="tok", **kwargs):
    """One sync on this thread, as the job would run it."""
    generation = vault_jobs._credential_generation
    return jobs.run_inline(vault_jobs.SYNC_KIND, lambda job: vault_jobs._sync(
        job, token, generation, **kwargs))


def _pass(kind, order, name, release=None):
    """A stand-in pass: a real job of ``kind`` that ends when ``release`` is set."""
    def start(*_args, **_kwargs):
        order.append(name)
        return jobs.start(kind, lambda job: release.wait(5) if release else None,
                          single=True)
    return start


# --- a running sync says what it is doing -----------------------------------

def test_sync_reports_the_reconcile_as_its_own_stage(db, monkeypatch):
    monkeypatch.setattr(pass_progress, "_EVERY_S", 0)
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    seen = []

    def fake_sync(token, on_progress, on_reconcile, conn, should_cancel):
        on_reconcile(0, 19128)
        on_reconcile(7000, 19128)
        seen.append(jobs.active_job(vault_jobs.SYNC_KIND).snapshot()["extra"])
        on_progress(1, 180, 1, 0)
        seen.append(jobs.active_job(vault_jobs.SYNC_KIND).snapshot()["extra"])
        return {"pushed": 180, "skipped": 0, "failed": []}

    monkeypatch.setattr(vault_client, "sync", fake_sync)
    record = _sync(raw=False)

    reconciling, uploading = seen
    assert reconciling["stage"] == "reconcile"
    assert (reconciling["done"], reconciling["total"]) == (7000, 19128)
    assert uploading["stage"] == "upload"
    assert (uploading["done"], uploading["total"]) == (1, 180)
    # the window turns this into "has not moved for n minutes"
    assert uploading["progress_at"] >= reconciling["progress_at"] > 0
    assert record["status"] == "done"
    assert record["result"] == {"mode": "upload", "transport": "frames",
                                "pushed": 180, "skipped": 0, "failed": 0}


def test_a_sync_whose_database_cannot_open_fails_and_frees_the_next(db, monkeypatch):
    """F-E-8: a sync that dies before its work ends failed with the error,
    and the next one can start."""
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    real_connect = indexer.connect

    def refuse():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(indexer, "connect", refuse)
    record = _wait(vault_jobs.start_sync("tok", raw=False))
    assert record["status"] == "failed"
    assert record["error"] == "unable to open database file"
    assert jobs.active_job(vault_jobs.SYNC_KIND) is None

    monkeypatch.setattr(indexer, "connect", real_connect)
    monkeypatch.setattr(vault_client, "sync", lambda token, **_kw: {
        "pushed": 0, "skipped": 0, "failed": []})
    assert _wait(vault_jobs.start_sync("tok", raw=False))["status"] == "done"


def test_a_sync_holding_a_replaced_token_does_nothing_and_keeps_the_ledger(db, monkeypatch):
    """F-E-7: a sync asked for under account A that starts after B replaced
    it must not upload with A, nor clear B's ledger."""
    _kv(**{vault_jobs.TOKEN_KEY: "account-b"})
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        conn.execute("INSERT INTO games(id, path, mtime, size) VALUES(1, 'a.slp', 1, 1)")
        conn.execute("INSERT INTO vault_objects(game_id, content_hash, deriver, bytes) "
                     "VALUES(1, 'hash-b', ?, 10)", (vault_sync.DERIVER,))
        conn.commit()
    finally:
        conn.close()
    calls = []
    monkeypatch.setattr(vault_client, "sync", lambda *a, **kw: calls.append(a))

    record = _sync("account-a", raw=False)
    assert record["status"] == "cancelled"
    assert calls == []
    conn = indexer.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 1
    finally:
        conn.close()


def test_upload_failures_stay_on_the_upload_after_the_metadata_follow_up(db, monkeypatch):
    """F-E-12: the raw chain's metadata pass is its own record; it never
    carries, or clears, the upload's failures."""
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    monkeypatch.setattr(vault_client, "sync_raw", lambda token, **_kw: {
        "pushed": 9, "skipped": 0, "failed": [{"game_id": 4, "error": "PUT"}]})
    monkeypatch.setattr(vault_client, "commit_pending_combos",
                        lambda token, **_kw: {"refreshed": 9, "skipped": []})
    monkeypatch.setattr(vault_client, "commit_pending_conversions",
                        lambda token, **_kw: {"pushed": 9, "failed": []})

    upload = _sync(raw=True, fallback=False)
    metadata = _sync(raw=True, fallback=False, combos_only=True)

    assert upload["result"] == {"mode": "upload", "transport": "raw",
                                "pushed": 9, "skipped": 0, "failed": 1}
    assert upload["detail"] == "1 failed"
    assert metadata["result"] == {"mode": "metadata", "committed": 9,
                                  "conversions": 9, "failed": 0}
    assert jobs.get(upload["id"])["result"]["failed"] == 1


# --- the chain: new games before the slow metadata refresh -------------------

def test_autorun_pushes_before_the_wire_basis_refresh(db, monkeypatch):
    replay_dir = db / "slp"
    replay_dir.mkdir()
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})

    order = []
    monkeypatch.setattr(indexer, "start_scan", _pass(indexer.SCAN_KIND, order, "scan"))
    monkeypatch.setattr(combo_index, "start_scan",
                        _pass(combo_index.SCAN_KIND, order, "combos"))

    def start_sync(token):
        order.append("sync")
        # the push finishes a moment later, on its own thread
        return jobs.start(vault_jobs.SYNC_KIND, lambda job: time.sleep(0.05), single=True)

    def refresh(token, generation=None, job=None):
        # only once the push has finished: the two never hit the vault together
        running = jobs.active_job(vault_jobs.SYNC_KIND) is not None
        order.append(f"refresh(sync running={running})")

    monkeypatch.setattr(vault_jobs, "start_sync", start_sync)
    monkeypatch.setattr(vault_jobs, "_maybe_refresh_wire_basis", refresh)

    record = jobs.run_inline(vault_jobs.AUTORUN_KIND, lambda job: vault_jobs._autorun(
        job, True, True, "tok", str(replay_dir)))
    assert record["status"] == "done"
    assert order == ["scan", "combos", "sync", "refresh(sync running=False)"]


def test_a_pass_that_outlives_the_wait_fails_the_chain_before_the_upload(db, monkeypatch):
    """F-E-10: a combo pass still running at the wait limit is not finished;
    uploading then would settle games without their combos for good."""
    monkeypatch.setattr(vault_jobs, "_WAIT_TIMEOUT_S", 0.1)
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    order = []
    release = threading.Event()
    monkeypatch.setattr(combo_index, "start_scan",
                        _pass(combo_index.SCAN_KIND, order, "combos", release))
    monkeypatch.setattr(vault_jobs, "start_sync", lambda token: order.append("sync"))
    try:
        record = jobs.run_inline(vault_jobs.AUTORUN_KIND, lambda job: vault_jobs._autorun(
            job, True, True, "tok", None))
    finally:
        release.set()
    assert record["status"] == "failed"
    assert "still running" in record["error"]
    assert order == ["combos"]


def test_a_failed_combo_pass_stops_the_frames_upload(db, monkeypatch):
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    order = []

    def failing_combos():
        order.append("combos")
        return jobs.start(combo_index.SCAN_KIND, lambda job: 1 / 0, single=True)

    monkeypatch.setattr(combo_index, "start_scan", failing_combos)
    monkeypatch.setattr(vault_jobs, "start_sync", lambda token: order.append("sync"))
    record = jobs.run_inline(vault_jobs.AUTORUN_KIND, lambda job: vault_jobs._autorun(
        job, True, True, "tok", None))
    assert record["status"] == "failed"
    assert "combo pass failed" in record["error"]
    assert order == ["combos"]


def test_a_wire_basis_refresh_that_stopped_at_a_hole_is_not_marked_done(db, monkeypatch):
    """F-E-1: the one-shot repair is only done once the vault acknowledged
    every row; a pass that stopped early resumes next cycle."""
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        conn.execute("INSERT INTO games(id, path, mtime, size) VALUES(1, 'a.slp', 1, 1)")
        conn.execute("INSERT INTO vault_objects(game_id, content_hash, deriver, bytes) "
                     "VALUES(1, 'hash-a', ?, 10)", (vault_sync.DERIVER,))
        indexer.kv_set(conn, "combos_frame_basis", combo_index._FRAME_BASIS)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(combo_index, "counts", lambda conn: {"games_pending": 0})
    results = iter([{"refreshed": 0, "skipped": ["hash-a"], "complete": False},
                    {"refreshed": 1, "skipped": [], "complete": True}])
    monkeypatch.setattr(vault_client, "refresh_meta", lambda token, **_kw: next(results))

    def marker():
        conn = indexer.connect()
        try:
            return indexer.kv_get(conn, "combos_wire_refresh")
        finally:
            conn.close()

    vault_jobs._maybe_refresh_wire_basis("tok")
    assert marker() is None
    vault_jobs._maybe_refresh_wire_basis("tok")
    assert marker() == combo_index._FRAME_BASIS


# --- a switched-on auto-sync that cannot run says so --------------------------

def test_auto_sync_without_a_token_is_logged_once_and_recovery_too(db, caplog):
    _kv(**{vault_jobs.AUTO_SYNC_KEY: True})
    caplog.set_level(logging.INFO, logger=vault_jobs.logger.name)

    assert vault_jobs._read_settings()[1] is False
    assert vault_jobs._read_settings()[1] is False      # next cycle: no repeat
    paused = [r for r in caplog.records if "uploads paused" in r.getMessage()]
    assert len(paused) == 1 and paused[0].levelno == logging.WARNING
    assert "token" in paused[0].getMessage()

    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    assert vault_jobs._read_settings()[1] is True
    assert any("can run again" in r.getMessage() for r in caplog.records)


def test_auto_sync_with_a_lapsed_pledge_is_logged(db, caplog):
    _kv(**{vault_jobs.AUTO_SYNC_KEY: True, vault_jobs.TOKEN_KEY: "tok",
           vault_jobs.PLEDGE_KEY: False})
    caplog.set_level(logging.INFO, logger=vault_jobs.logger.name)
    assert vault_jobs._read_settings()[1] is False
    assert any("not pledged" in r.getMessage() for r in caplog.records)


def test_auto_sync_off_by_choice_logs_nothing(db, caplog):
    caplog.set_level(logging.INFO, logger=vault_jobs.logger.name)
    assert vault_jobs._read_settings()[1] is False
    assert not caplog.records


# --- one chain at a time -----------------------------------------------------

def test_a_kick_during_a_chain_runs_one_more_pass_after_it(db, monkeypatch):
    """A first pledge while the loop is mid-scan: the running chain read
    auto_sync=False, so the upload must follow it, not wait ten minutes, and
    must never run beside it."""
    runs = []
    inside = threading.Event()
    release = threading.Event()

    def chain(job, auto_scan, auto_sync, token, replay_dir):
        runs.append(auto_sync)
        if len(runs) == 1:
            inside.set()
            release.wait(5)

    monkeypatch.setattr(vault_jobs, "_autorun_chain", chain)
    monkeypatch.setattr(vault_jobs, "maybe_autostart",
                        lambda: (_ for _ in ()).throw(AssertionError("second chain started")))
    _kv(**{vault_jobs.TOKEN_KEY: "tok", vault_jobs.AUTO_SCAN_KEY: True})
    job_id = vault_jobs._start_autorun((True, False, "tok", None))
    assert inside.wait(5)
    _kv(**{vault_jobs.AUTO_SYNC_KEY: True})
    vault_jobs.kick_autorun()                       # chain running: queued
    assert vault_jobs._loop_cycle() is False        # a loop tick: refused
    release.set()
    assert _wait(job_id)["status"] == "done"
    assert runs == [False, True]


def test_a_settings_read_that_fails_at_launch_still_installs_the_loop(db, monkeypatch):
    """F-E-9: the loop re-reads the settings every cycle, so it must be
    installed even when the launch read fails, or the session never retries."""
    monkeypatch.setattr(vault_jobs, "NUCLEOME_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "VAULT_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "_loop_started", False)
    started = []
    monkeypatch.setattr(vault_jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: started.append(kw["name"])})())

    def unreadable():
        raise OSError("storage not ready")
    monkeypatch.setattr(vault_jobs, "_read_settings", unreadable)
    assert vault_jobs.maybe_autostart() is False
    assert started == ["nucleome-autoloop"]


# --- a stop, a failed scan, a sync already running ----------------------------

def test_a_plain_stop_ends_the_sync_cancelled_and_keeps_the_ledger(db, monkeypatch):
    """Only a credential change clears the ledger; the user's Stop leaves it
    (and the last-sync time) for the next sync to continue from."""
    _kv(**{vault_jobs.TOKEN_KEY: "tok", vault_jobs.LAST_SYNC_KEY: "previous"})
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        conn.execute("INSERT INTO games(id, path, mtime, size) VALUES(1, 'a.slp', 1, 1)")
        conn.execute("INSERT INTO vault_objects(game_id, content_hash, deriver, bytes) "
                     "VALUES(1, 'hash-a', ?, 10)", (vault_sync.DERIVER,))
        conn.commit()
    finally:
        conn.close()
    asked = []

    def stopped(token, on_progress, on_reconcile, conn, should_cancel):
        asked.append(should_cancel())
        jobs.cancel(jobs.active_job(vault_jobs.SYNC_KIND).id)
        asked.append(should_cancel())       # the job's Stop reaches the transport
        raise vault_sync.SyncCancelled("vault sync cancelled")

    monkeypatch.setattr(vault_client, "sync", stopped)
    record = _sync(raw=False)
    assert record["status"] == "cancelled" and not record["error"]
    assert asked == [False, True]
    conn = indexer.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 1
        assert indexer.kv_get(conn, vault_jobs.LAST_SYNC_KEY) == "previous"
    finally:
        conn.close()


def test_a_failed_scan_still_lets_combos_and_the_upload_run(db, monkeypatch):
    """Combos and the push work on what is already indexed."""
    replay_dir = db / "slp"
    replay_dir.mkdir()
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    order = []

    def failing_scan(_dir):
        order.append("scan")
        return jobs.start(indexer.SCAN_KIND, lambda job: 1 / 0, single=True)

    monkeypatch.setattr(indexer, "start_scan", failing_scan)
    monkeypatch.setattr(combo_index, "start_scan",
                        _pass(combo_index.SCAN_KIND, order, "combos"))
    monkeypatch.setattr(vault_jobs, "start_sync", lambda token: order.append("sync"))
    monkeypatch.setattr(vault_jobs, "_maybe_refresh_wire_basis",
                        lambda *_a, **_k: order.append("refresh"))
    record = jobs.run_inline(vault_jobs.AUTORUN_KIND, lambda job: vault_jobs._autorun(
        job, True, True, "tok", str(replay_dir)))
    assert record["status"] == "done"
    assert order == ["scan", "combos", "sync", "refresh"]
    assert jobs.list_jobs(kind=indexer.SCAN_KIND)[0]["status"] == "failed"


def test_the_chain_waits_out_a_sync_already_running_before_the_refresh(db, monkeypatch):
    """A manual Sync got there first: the chain joins it instead of skipping
    the wait, so the refresh never hits the vault alongside it."""
    _kv(**{vault_jobs.TOKEN_KEY: "tok"})
    release = threading.Event()
    manual = jobs.start(vault_jobs.SYNC_KIND, lambda job: release.wait(5), single=True)
    order = []

    def busy(token):
        order.append("sync refused")
        return None

    def refresh(token, generation=None, job=None):
        running = jobs.active_job(vault_jobs.SYNC_KIND) is not None
        order.append(f"refresh(sync running={running})")

    monkeypatch.setattr(vault_jobs, "start_sync", busy)
    monkeypatch.setattr(vault_jobs, "_maybe_refresh_wire_basis", refresh)
    timer = threading.Timer(0.2, release.set)
    timer.start()
    try:
        record = jobs.run_inline(vault_jobs.AUTORUN_KIND, lambda job: vault_jobs._autorun(
            job, False, True, "tok", None))
    finally:
        release.set()
        timer.cancel()
    assert record["status"] == "done"
    assert order == ["sync refused", "refresh(sync running=False)"]
    assert jobs.get(manual)["status"] == "done"
