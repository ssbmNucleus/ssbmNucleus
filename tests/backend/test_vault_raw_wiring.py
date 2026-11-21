"""Raw vault rollout wiring. Private SQLite DBs and fake transports only."""
import gzip
import hashlib
import logging
import time
import uuid

import pytest

from core import jobs
from tracker.cloud import vault_client, vault_jobs, vault_raw, vault_sync
from tracker.combos import combo_index
from tracker.store import indexer


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / f"raw-wiring-{uuid.uuid4().hex}.db")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(vault_jobs, "_POLL_S", 0.01)
    monkeypatch.setattr(vault_jobs, "_credential_generation", 0)
    monkeypatch.setattr(vault_raw, "parse_slp", lambda _path: {"players": [{}, {}]})
    monkeypatch.setattr(vault_client, "_codes_for_sync", lambda *_: set())
    monkeypatch.setattr(vault_client, "_call",
                        lambda *_: pytest.fail("unexpected network request"))
    monkeypatch.setattr(vault_client, "_put",
                        lambda *_: pytest.fail("unexpected PUT"))
    conn = indexer.connect()
    indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "token")
    yield conn
    conn.close()


def add_game(db, tmp_path, gid, processed=False, body=None):
    path = tmp_path / f"{gid}.slp"
    path.write_bytes(body or f"synthetic replay {gid}".encode())
    stat = path.stat()
    db.execute(
        "INSERT INTO games(id,path,mtime,size,parse_ok,start_at,players,combos_at) "
        "VALUES(?,?,?,?,1,?,'[]',?)",
        (gid, str(path), stat.st_mtime, stat.st_size, f"2026-10-{gid:02d}",
         stat.st_mtime if processed else None))
    db.commit()
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Transport:
    def __init__(self, monkeypatch, kinds=None):
        self.kinds = iter(kinds) if kinds is not None else None
        self.calls, self.puts = [], []
        monkeypatch.setattr(vault_client, "_call", self.call)
        monkeypatch.setattr(vault_client, "_put", self.put)

    def call(self, url, payload):
        assert url == vault_client.FN_SYNC and payload["token"] == "token"
        self.calls.append(payload)
        if payload["action"] == "mint":
            kind = next(self.kinds) if self.kinds is not None else "slp"
            out = {"urls": {r["content_hash"]: f"mock://{kind}/{r['content_hash']}"
                            for r in payload["items"]}}
            if kind is not None:
                out["kind"] = kind
            return out
        assert payload["action"] == "commit"
        return {}

    def put(self, url, body):
        assert url.startswith("mock://slp/")
        assert hashlib.sha256(gzip.decompress(body)).hexdigest() == url.rsplit("/", 1)[1]
        self.puts.append((url, body))

    @property
    def games(self):
        return [g for call in self.calls if call["action"] == "commit"
                for g in call["games"]]


def wait(job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record and record["status"] in jobs.FINAL:
            return record
        time.sleep(0.01)
    raise AssertionError(jobs.get(job_id))


def inline_start(monkeypatch, **kwargs):
    """Start a sync job through start_sync and wait for its final record."""
    record = wait(vault_jobs.start_sync("token", **kwargs))
    assert record["status"] == "done", record
    return record


def run_chain(*settings):
    """The autorun chain as a job on this thread; its final record."""
    return jobs.run_inline(vault_jobs.AUTORUN_KIND,
                           lambda job: vault_jobs._autorun(job, *settings))


def test_raw_is_the_default_and_only_false_turns_it_off(db):
    assert vault_client.raw_requested(db) and vault_client.raw_upload_available(db)
    indexer.kv_set(db, vault_client.RAW_UPLOAD_KEY, False)
    assert not vault_client.raw_requested(db) and not vault_client.raw_upload_available(db)
    indexer.kv_set(db, vault_client.RAW_UPLOAD_KEY, True)
    assert vault_client.raw_upload_available(db)
    # A server that refused raw within the day still sends this cycle to frames.
    indexer.kv_set(db, vault_client.RAW_RETRY_AFTER_KEY, time.time() + 60)
    assert vault_client.raw_requested(db) and not vault_client.raw_upload_available(db)


def test_off_keeps_frames_transport(db, tmp_path, monkeypatch):
    sha = add_game(db, tmp_path, 1)
    indexer.kv_set(db, vault_client.RAW_UPLOAD_KEY, False)
    calls, puts = [], []
    monkeypatch.setattr(vault_client, "sync_raw", lambda *_a, **_k: pytest.fail("raw called"))
    monkeypatch.setattr(vault_client, "_remote_hashes", lambda _t: {})
    monkeypatch.setattr(vault_client, "DERIVE_WORKERS", 1)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda _p: b"unchanged frames bytes")
    monkeypatch.setattr(vault_client, "_put", lambda url, body: puts.append((url, body)))

    def call(_url, payload):
        calls.append(payload)
        return {"urls": {sha: "mock://frames"}} if payload["action"] == "mint" else {}

    monkeypatch.setattr(vault_client, "_call", call)
    assert inline_start(monkeypatch)
    assert puts == [("mock://frames", b"unchanged frames bytes")]
    assert calls[0] == {"action": "mint", "token": "token", "items": [
        {"content_hash": sha, "bytes": len(b"unchanged frames bytes")}]}
    assert calls[1] == {"action": "commit", "token": "token", "games": [{
        "content_hash": sha, "bytes": len(b"unchanged frames bytes"),
        "deriver": "frames-v4", "meta": vault_client._game_meta(db, 1, set()),
        "combos": []}]}
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='vault_raw'").fetchone()


@pytest.mark.parametrize("echo", [None, "frames", "SLP"])
def test_unsupported_server_never_puts_and_persists_backoff(db, tmp_path, monkeypatch, echo):
    add_game(db, tmp_path, 1)
    transport = Transport(monkeypatch, [echo])
    before = time.time()
    with pytest.raises(vault_client.VaultError, match="^server does not support raw uploads$"):
        vault_client.sync_raw("token", conn=db)
    assert transport.puts == [] and transport.games == []
    assert len(transport.calls) == 1  # fatal, no quiet retry
    retry = indexer.kv_get(db, vault_client.RAW_RETRY_AFTER_KEY)
    assert before + 86400 <= retry <= time.time() + 86400
    with pytest.raises(vault_client.VaultError):
        vault_client.sync_raw("token", conn=db)
    assert len(transport.calls) == 1
    assert db.execute("SELECT COUNT(*) FROM vault_raw").fetchone()[0] == 0


def test_capability_is_checked_on_every_batch(db, tmp_path, monkeypatch):
    for gid in (1, 2):
        add_game(db, tmp_path, gid)
    monkeypatch.setattr(vault_client, "BATCH", 1)
    transport = Transport(monkeypatch, ["slp", None])
    with pytest.raises(vault_client.RawUploadsUnsupported):
        vault_client.sync_raw("token", conn=db)
    assert len(transport.puts) == len(transport.games) == 1
    assert all(url.startswith("mock://slp/") for url, _body in transport.puts)


def test_raw_commit_includes_combos_only_for_current_processed_games(db, tmp_path, monkeypatch):
    hashes = {gid: add_game(db, tmp_path, gid, processed=gid != 1) for gid in (1, 2, 3)}
    db.execute("UPDATE games SET combos_at=mtime-1 WHERE id=3")
    db.commit()
    seen = []
    monkeypatch.setattr(vault_client, "_combos_for",
                        lambda _c, gid: seen.append(gid) or [{"hits": 4}])
    transport = Transport(monkeypatch)
    result = vault_client.sync_raw("token", conn=db)
    assert result["pushed"] == 3 and not result["failed"]
    assert seen == [2]
    games = {g["content_hash"]: g for g in transport.games}
    assert games[hashes[2]]["combos"] == [{"hits": 4}]
    for gid in (1, 3):
        assert "combos" not in games[hashes[gid]]
    for game in games.values():
        assert game["slp_codec"] == "gz1" and game["slp_bytes"] > 0
        assert "bytes" not in game and "deriver" not in game
    mint = transport.calls[0]
    assert mint["kind"] == "slp"
    assert all(set(item) == {"content_hash", "bytes", "codec"} for item in mint["items"])
    assert [r[0] for r in db.execute("SELECT game_id FROM vault_raw_combos")] == [2]


def test_pending_combos_commit_once_including_empty_processed_array(db, tmp_path, monkeypatch):
    hashes = {gid: add_game(db, tmp_path, gid) for gid in (1, 2)}
    transport = Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db)
    db.execute("UPDATE games SET combos_at=mtime WHERE id=1")
    db.commit()
    transport.calls.clear()
    result = vault_client.commit_pending_combos("token", conn=db)
    assert result == {"refreshed": 1, "skipped": []}
    assert len(transport.puts) == 2  # metadata follow-up performs no PUT
    assert len(transport.games) == 1 and transport.games[0]["combos"] == []
    assert transport.games[0]["content_hash"] == hashes[1]
    assert transport.games[0]["slp_codec"] == "gz1"
    assert vault_client.commit_pending_combos("token", conn=db)["refreshed"] == 0
    assert len(transport.calls) == 2
    db.execute("UPDATE games SET combos_at=mtime WHERE id=2")
    db.commit()
    assert vault_client.commit_pending_combos("token", conn=db)["refreshed"] == 1


def test_pending_combos_ack_only_and_duplicate_hashes(db, tmp_path, monkeypatch):
    for gid in (1, 2, 3):
        add_game(db, tmp_path, gid, body=b"same replay" if gid < 3 else None)
    transport = Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db)
    db.execute("UPDATE games SET combos_at=mtime")
    db.commit()
    transport.calls.clear()
    original = vault_client._commit_games

    def partial(token, games):
        assert len({g["content_hash"] for g in games}) == len(games) == 2
        return original(token, games[1:])

    monkeypatch.setattr(vault_client, "_commit_games", partial)
    result = vault_client.commit_pending_combos("token", conn=db)
    assert result == {"refreshed": 2, "skipped": [3]}
    assert len(transport.calls[0]["items"]) == 1
    monkeypatch.setattr(vault_client, "_commit_games", original)
    assert vault_client.commit_pending_combos("token", conn=db)["refreshed"] == 1


def test_pending_combos_guards_server_rollback(db, tmp_path, monkeypatch):
    add_game(db, tmp_path, 1)
    Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db)
    db.execute("UPDATE games SET combos_at=mtime")
    db.commit()
    legacy = Transport(monkeypatch, [None])
    with pytest.raises(vault_client.RawUploadsUnsupported):
        vault_client.commit_pending_combos("token", conn=db)
    assert legacy.puts == legacy.games == []
    assert db.execute("SELECT COUNT(*) FROM vault_raw_combos").fetchone()[0] == 0


@pytest.mark.parametrize("followup", [False, True])
def test_cancel_during_commit_does_not_ack_combos(db, tmp_path, monkeypatch, followup):
    add_game(db, tmp_path, 1, processed=not followup)
    Transport(monkeypatch)
    if followup:
        vault_client.sync_raw("token", conn=db)
        db.execute("UPDATE games SET combos_at=mtime")
        db.commit()
    cancelled = False

    def commit(_token, games):
        nonlocal cancelled
        cancelled = True
        return [g["content_hash"] for g in games]

    monkeypatch.setattr(vault_client, "_commit_games", commit)
    run = vault_client.commit_pending_combos if followup else vault_client.sync_raw
    with pytest.raises(vault_sync.SyncCancelled):
        run("token", conn=db, should_cancel=lambda: cancelled)
    assert db.execute("SELECT COUNT(*) FROM vault_raw_combos").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM vault_raw").fetchone()[0] == int(followup)


def test_raw_uploads_count_as_synced(db, tmp_path, monkeypatch):
    """F-E-2: a game the raw transport settled is in the cloud, not pending."""
    add_game(db, tmp_path, 1, processed=True)
    add_game(db, tmp_path, 2, processed=True)
    Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db, game_ids=[1])
    status = vault_sync.status(db)
    assert (status["pushed"], status["pending"]) == (1, 1)


def test_raw_ledgers_are_cleared_when_credentials_change(db, tmp_path, monkeypatch):
    add_game(db, tmp_path, 1, processed=True)
    Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db)
    vault_jobs.clear_account_sync_state(db)
    for table in ("vault_raw", "vault_raw_combos"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM vault_hashes").fetchone()[0] == 1


def test_manual_sync_fallback_and_cooldown_expiry(db, tmp_path, monkeypatch):
    add_game(db, tmp_path, 1)
    indexer.kv_set(db, vault_client.RAW_UPLOAD_KEY, True)
    legacy = Transport(monkeypatch, [None])
    frames = []
    monkeypatch.setattr(vault_client, "sync", lambda *a, **k:
                        frames.append(True) or {"pushed": 0, "failed": []})
    assert inline_start(monkeypatch)
    assert frames == [True] and not legacy.puts
    assert inline_start(monkeypatch)
    assert frames == [True, True] and len(legacy.calls) == 1
    indexer.kv_set(db, vault_client.RAW_RETRY_AFTER_KEY, time.time() - 1)
    supported = Transport(monkeypatch)
    assert inline_start(monkeypatch)
    assert len(supported.puts) == 1 and frames == [True, True]


def setup_chain(db, tmp_path, monkeypatch, raw=True):
    indexer.kv_set(db, vault_client.RAW_UPLOAD_KEY, raw)
    order = []
    monkeypatch.setattr(indexer, "start_scan", lambda _d: order.append("index"))
    monkeypatch.setattr(combo_index, "start_scan", lambda: order.append("combos"))
    monkeypatch.setattr(vault_jobs, "_maybe_refresh_wire_basis", lambda *_:
                        order.append("refresh"))
    return order


@pytest.mark.parametrize("raw", [False, True])
def test_autorun_chain_order_and_off_path(db, tmp_path, monkeypatch, raw):
    order = setup_chain(db, tmp_path, monkeypatch, raw)

    def start(_token, **kwargs):
        if kwargs.get("combos_only"):
            order.append("commit_pending_combos")
        else:
            order.append("raw" if kwargs.get("raw") else "frames")

    monkeypatch.setattr(vault_jobs, "start_sync", start)
    run_chain(True, True, "token", str(tmp_path))
    assert order == (["index", "raw", "combos", "commit_pending_combos"] if raw else
                     ["index", "combos", "frames", "refresh"])


def test_autorun_defers_unsupported_fallback_until_after_combos(db, tmp_path, monkeypatch):
    order = setup_chain(db, tmp_path, monkeypatch)

    def start(_token, **kwargs):
        if kwargs.get("raw"):
            order.append("raw")
            indexer.kv_set(db, vault_client.RAW_RETRY_AFTER_KEY, time.time() + 86400)
        else:
            order.append("frames")

    monkeypatch.setattr(vault_jobs, "start_sync", start)
    run_chain(True, True, "token", str(tmp_path))
    assert order == ["index", "raw", "combos", "frames", "refresh"]


@pytest.mark.parametrize("change_at", ["index", "raw", "combos"])
def test_autorun_rechecks_credentials_between_raw_steps(db, tmp_path, monkeypatch, change_at):
    order = setup_chain(db, tmp_path, monkeypatch)

    def step(name):
        order.append(name)
        if name == change_at:
            vault_jobs.cancel_sync()
            indexer.kv_set(db, vault_jobs.TOKEN_KEY, "replacement")

    monkeypatch.setattr(indexer, "start_scan", lambda _: step("index"))
    monkeypatch.setattr(combo_index, "start_scan", lambda: step("combos"))
    monkeypatch.setattr(vault_jobs, "start_sync", lambda _t, **k: step(
        "followup" if k.get("combos_only") else "raw"))
    run_chain(True, True, "token", str(tmp_path))
    assert "followup" not in order and "refresh" not in order
    if change_at == "index":
        assert "raw" not in order


def test_timings_reach_the_upload_record_and_survive_combo_followup(db, tmp_path, monkeypatch, caplog):
    add_game(db, tmp_path, 1, processed=True)
    indexer.kv_set(db, vault_client.RAW_UPLOAD_KEY, True)
    Transport(monkeypatch)
    caplog.set_level(logging.INFO)
    upload = inline_start(monkeypatch)
    timings = upload["result"]["timings"]
    assert set(timings) == {"hash", "compress", "mint", "put", "commit", "quota_wait"}
    assert all(value >= 0 for value in timings.values())
    assert any("vault raw sync:" in record.message for record in caplog.records)
    inline_start(monkeypatch, raw=True, combos_only=True, fallback=False)
    assert jobs.get(upload["id"])["result"]["timings"] == timings


def test_schema_adds_combo_tracking_to_existing_raw_ledger_idempotently(db):
    db.executescript("""
        CREATE TABLE vault_raw(game_id INTEGER PRIMARY KEY, content_hash TEXT,
                               codec TEXT, bytes INTEGER, pushed_at TEXT);
        INSERT INTO vault_raw VALUES(42,'hash','gz1',10,'before');
    """)
    vault_raw.ensure_raw_schema(db)
    vault_raw.ensure_raw_schema(db)
    assert db.execute("SELECT pushed_at FROM vault_raw").fetchone()[0] == "before"
    assert db.execute("SELECT COUNT(*) FROM vault_raw_combos").fetchone()[0] == 0


def test_raw_plan_options_and_processed_empty_combos(db, tmp_path, monkeypatch):
    for gid in (1, 2, 3):
        add_game(db, tmp_path, gid, processed=True)
    transport = Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db, limit=1, newest_first=False, game_ids=[1, 2])
    assert [r[0] for r in db.execute("SELECT game_id FROM vault_raw")] == [1]
    assert transport.games[0]["combos"] == []
    assert vault_client.commit_pending_combos("token", conn=db)["refreshed"] == 0
    assert len(transport.calls) == 2


@pytest.mark.parametrize("followup", [False, True])
def test_worker_cancellation_clears_raw_state_and_last_sync(db, tmp_path, monkeypatch, followup):
    add_game(db, tmp_path, 1, processed=True)
    Transport(monkeypatch)
    vault_client.sync_raw("token", conn=db)
    indexer.kv_set(db, vault_jobs.LAST_SYNC_KEY, "previous")

    def cancel(*_args, **_kwargs):
        vault_jobs.cancel_sync()
        return {"pushed": 0, "failed": [], "refreshed": 0, "skipped": []}

    monkeypatch.setattr(vault_client, "commit_pending_combos" if followup else "sync_raw", cancel)
    record = jobs.run_inline(vault_jobs.SYNC_KIND, lambda job: vault_jobs._sync(
        job, "token", 0, raw=True, combos_only=followup))
    assert record["status"] == "cancelled"
    assert indexer.kv_get(db, vault_jobs.LAST_SYNC_KEY) is None
    for table in ("vault_raw", "vault_raw_combos"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_raw_autorun_respects_auto_sync_off(db, tmp_path, monkeypatch):
    order = setup_chain(db, tmp_path, monkeypatch)
    monkeypatch.setattr(vault_jobs, "start_sync", lambda *_a, **_k: pytest.fail("sync disabled"))
    run_chain(True, False, "token", str(tmp_path))
    assert order == ["index", "combos"]


def test_fallback_cycle_stays_frames_if_cooldown_expires_during_scan(db, tmp_path, monkeypatch):
    order = setup_chain(db, tmp_path, monkeypatch)
    indexer.kv_set(db, vault_client.RAW_RETRY_AFTER_KEY, time.time() + 1)

    def scan(_dir):
        order.append("index")
        indexer.kv_set(db, vault_client.RAW_RETRY_AFTER_KEY, 0)

    def sync(_token, **kwargs):
        assert kwargs == {"raw": False}
        order.append("frames")

    monkeypatch.setattr(indexer, "start_scan", scan)
    monkeypatch.setattr(vault_jobs, "start_sync", sync)
    run_chain(True, True, "token", str(tmp_path))
    assert order == ["index", "combos", "frames", "refresh"]


def test_real_raw_chain_uploads_then_commits_new_combos(db, tmp_path, monkeypatch):
    order = setup_chain(db, tmp_path, monkeypatch)
    add_game(db, tmp_path, 1)
    transport = Transport(monkeypatch)
    monkeypatch.setattr(vault_client, "sync", lambda *_a, **_k: pytest.fail("frames in raw chain"))

    def combos():
        assert len(transport.puts) == 1 and "combos" not in transport.games[0]
        order.append("combos")
        db.execute("UPDATE games SET combos_at=mtime")
        db.commit()

    real_start = vault_jobs.start_sync

    def start(_token, **kwargs):
        order.append("followup" if kwargs.get("combos_only") else "raw")
        return real_start(_token, **kwargs)

    monkeypatch.setattr(combo_index, "start_scan", combos)
    monkeypatch.setattr(vault_jobs, "start_sync", start)
    run_chain(True, True, "token", str(tmp_path))
    assert order == ["index", "raw", "combos", "followup"]
    assert len(transport.puts) == 1 and len(transport.games) == 2
    assert transport.games[1]["combos"] == []
    assert [r["status"] for r in jobs.list_jobs(kind=vault_jobs.SYNC_KIND)] == ["done", "done"]
