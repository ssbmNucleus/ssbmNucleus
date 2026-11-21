"""Raw replay uploads: synthetic files, a real index schema, fake transports."""
import gzip
import hashlib
import io
import logging
import os
from pathlib import Path
import sqlite3
import struct
import threading
import uuid

import pytest

from tracker.cloud import vault_raw, vault_sync
from tracker.store import indexer, slp_meta


@pytest.fixture
def conn(tmp_path):
    # pytest can reuse a successful parametrized case's temp-directory name;
    # schema initialization is deliberately memoized by database path.
    db = sqlite3.connect(tmp_path / f"index-{uuid.uuid4().hex}.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(indexer.SCHEMA)
    vault_raw.ensure_raw_schema(db)
    yield db
    db.close()


def _slp(players=2, marker=0):
    """Just an event-size table and GameStart; no frame parser/real replay."""
    start = bytearray(0x141)
    start[0] = slp_meta.CMD_GAME_START
    start[1:4] = bytes((3, 16, 0))
    start[0x13:0x15] = struct.pack(">H", 31)
    for port in range(4):
        start[0x65 + 0x24 * port + 1] = 0 if port < players else 3
    start[-1] = marker
    raw = bytes((0x35, 4, 0x36)) + struct.pack(">H", len(start) - 1) + start
    return slp_meta.HEADER + struct.pack(">i", len(raw)) + raw


def _add(conn, tmp_path, gid, *, body=None, parse_ok=1, dated=True):
    path = tmp_path / f"g{gid}.slp"
    path.write_bytes(_slp(marker=gid) if body is None else body)
    st = path.stat()
    conn.execute(
        "INSERT INTO games(id, path, mtime, size, parse_ok, start_at, duration_s, "
        "players) VALUES(?,?,?,?,?,?,?,?)",
        (gid, str(path), st.st_mtime, st.st_size, parse_ok,
         f"2026-01-{gid:02d}T00:00:00Z" if dated else None, 60, "[]"))
    conn.commit()
    return path


def _ids(items):
    return [item["id"] for item in items]


def _ledger(conn):
    return {r[0] for r in conn.execute("SELECT game_id FROM vault_raw")}


class Transport:
    def __init__(self):
        self.minted = []
        self.puts = {}
        self.committed = []
        self.lock = threading.Lock()

    def mint(self, items):
        self.minted.append([dict(row) for row in items])
        assert all(set(row) == {"game_id", "content_hash", "bytes", "codec"}
                   and row["codec"] == "gz1" for row in items)
        return {row["content_hash"]: "mock://" + row["content_hash"] for row in items}

    def put(self, url, body):
        sha = url.removeprefix("mock://")
        assert hashlib.sha256(gzip.decompress(body)).hexdigest() == sha
        with self.lock:
            self.puts[sha] = body

    def commit(self, items):
        # Every row must refer to an object whose entire PUT already finished.
        for row in items:
            assert row["bytes"] == len(self.puts[row["content_hash"]])
            assert row["codec"] == "gz1"
            assert set(row) == {"game_id", "content_hash", "bytes", "codec"}
        self.committed.append([dict(row) for row in items])
        return [row["content_hash"] for row in items]


def _push(conn, transport=None, **kwargs):
    transport = transport or Transport()
    args = {"mint_urls": transport.mint, "put": transport.put,
            "commit": transport.commit, "sleep": lambda _seconds: None}
    args.update(kwargs)
    return vault_raw.push_raw(conn, vault_raw.plan_raw(conn), **args)


def test_schema_is_memoized_per_database_but_not_for_memory(conn):
    statements = []
    conn.set_trace_callback(statements.append)
    vault_raw.ensure_raw_schema(conn)
    vault_raw.ensure_raw_schema(conn)
    assert not any("CREATE " in s.upper() for s in statements)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'idx_vault_raw_hash'").fetchone()
    for _ in range(2):
        with sqlite3.connect(":memory:") as memory:
            vault_raw.ensure_raw_schema(memory)
            assert memory.execute("SELECT COUNT(*) FROM vault_raw").fetchone()[0] == 0


def test_plan_matches_existing_selection_order_limits_and_ids(conn, tmp_path):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    _add(conn, tmp_path, 4, dated=False)
    _add(conn, tmp_path, 5, parse_ok=0)
    assert vault_raw.plan_raw(conn) == vault_sync.plan(conn)
    assert _ids(vault_raw.plan_raw(conn)) == [3, 2, 1, 4]
    assert _ids(vault_raw.plan_raw(conn, newest_first=False)) == [4, 1, 2, 3]
    assert _ids(vault_raw.plan_raw(conn, game_ids=[1, 3], limit=1)) == [3]
    assert vault_raw.plan_raw(conn, game_ids=[-1]) == []
    assert vault_raw.plan_raw(conn, game_ids=[5]) == []


def test_raw_ledger_is_codec_specific_and_independent_of_frames(conn, tmp_path):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    conn.execute("INSERT INTO vault_raw VALUES(1,'h1',?,1,'now')", (vault_raw.RAW_CODEC,))
    conn.execute("INSERT INTO vault_raw VALUES(2,'h2','old-codec',1,'now')")
    conn.execute("INSERT INTO vault_objects VALUES(3,'h3',?,1,'now')", (vault_sync.DERIVER,))
    assert _ids(vault_raw.plan_raw(conn)) == [3, 2]
    assert vault_raw.plan_raw(conn, game_ids=[1]) == []
    result = _push(conn)
    assert result["pushed"] == 2 and not result["failed"]
    assert vault_raw.plan_raw(conn) == []
    assert {r[0] for r in conn.execute("SELECT codec FROM vault_raw")} == {"gz1"}
    conn.execute("DELETE FROM games WHERE id = 1")
    assert _ledger(conn) == {2, 3}


def test_compress_slp_is_gzip6_deterministic_without_name_or_timestamp(tmp_path):
    data = _slp() * 100
    first, second = tmp_path / "one.slp", tmp_path / "another-name.slp"
    first.write_bytes(data)
    second.write_bytes(data)
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))
    body = vault_raw.compress_slp(first)
    expected = io.BytesIO()
    with gzip.GzipFile(fileobj=expected, filename="", mode="wb",
                       compresslevel=6, mtime=0) as stream:
        stream.write(data)
    assert body == vault_raw.compress_slp(first) == vault_raw.compress_slp(second)
    assert body == expected.getvalue()
    assert body[3] & 0x08 == 0 and body[4:8] == b"\0" * 4
    assert gzip.decompress(body) == data


def test_ack_only_ledgers_with_shared_hash_cache(conn, tmp_path, monkeypatch):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    path = str(tmp_path / "g1.slp")
    st = os.stat(path)
    cached = vault_sync.content_hash(conn, path, st.st_mtime, st.st_size)
    original_hash = vault_sync.sha256_file

    def hash_file(path, chunk):
        assert Path(path).name != "g1.slp"  # raw must use the existing cache
        return original_hash(path, chunk)

    monkeypatch.setattr(vault_sync, "sha256_file", hash_file)
    transport = Transport()

    def commit(items):
        transport.commit(items)
        return (row["content_hash"] for row in items if row["game_id"] != 2)

    result = _push(conn, transport, commit=commit)
    assert result["pushed"] == 2 and result["failed"] == [(2, "commit not acknowledged")]
    assert _ledger(conn) == {1, 3}
    assert _ids(vault_raw.plan_raw(conn)) == [2]
    assert conn.execute("SELECT content_hash FROM vault_raw WHERE game_id=1").fetchone()[0] == cached
    for row in conn.execute("SELECT content_hash, bytes, pushed_at FROM vault_raw"):
        assert row[1] == len(transport.puts[row[0]]) and row[2]


def test_duplicates_mint_put_commit_once_and_ledger_each_copy(conn, tmp_path):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid, body=_slp())
    transport = Transport()
    result = _push(conn, transport)
    assert result["pushed"] == 3 and not result["failed"]
    assert len(transport.minted[0]) == len(transport.puts) == len(transport.committed[0]) == 1
    assert _ledger(conn) == {1, 2, 3}


def test_commit_failure_leaves_games_pending_after_one_retry(conn, tmp_path):
    _add(conn, tmp_path, 1)
    calls, sleeps = [], []

    def commit(items):
        calls.append(items)
        raise RuntimeError("database unavailable")

    result = _push(conn, commit=commit, sleep=sleeps.append)
    assert len(calls) == 2 and sleeps == [5]
    assert result["pushed"] == 0
    assert result["failed"] == [(1, "commit failed: database unavailable")]
    assert not _ledger(conn) and _ids(vault_raw.plan_raw(conn)) == [1]


@pytest.mark.parametrize("phase", ["mint", "put", "commit"])
def test_transient_transport_failure_gets_one_quiet_retry(conn, tmp_path, phase):
    _add(conn, tmp_path, 1)
    transport = Transport()
    original = getattr(transport, phase)
    calls, sleeps = [], []

    def flaky(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary timeout")
        return original(*args)

    result = _push(conn, transport, **{
        "mint_urls" if phase == "mint" else phase: flaky, "sleep": sleeps.append})
    assert len(calls) == 2 and sleeps == [5]
    assert result["pushed"] == 1 and not result["failed"]


def test_exhausted_mint_retry_fails_only_its_batch(conn, tmp_path):
    for gid in (1, 2):
        _add(conn, tmp_path, gid)
    transport = Transport()
    calls = []

    def mint(items):
        calls.append(items[0]["game_id"])
        if items[0]["game_id"] == 2:
            raise RuntimeError("edge timeout")
        return transport.mint(items)

    result = _push(conn, transport, mint_urls=mint, batch=1)
    assert calls == [2, 2, 1]
    assert result["pushed"] == 1 and result["failed"] == [(2, "mint failed: edge timeout")]
    assert _ledger(conn) == {1}


def test_missing_urls_and_failed_puts_are_never_committed(conn, tmp_path):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    transport = Transport()
    failed_sha = hashlib.sha256((tmp_path / "g2.slp").read_bytes()).hexdigest()
    put_calls = []

    def mint(items):
        return transport.mint([row for row in items if row["game_id"] != 3])

    def put(url, body):
        put_calls.append(url)
        if url.endswith(failed_sha):
            raise RuntimeError("upload unavailable")
        transport.put(url, body)

    result = _push(conn, transport, mint_urls=mint, put=put, put_workers=3)
    assert result["pushed"] == 1 and _ledger(conn) == {1}
    assert sorted(result["failed"]) == [(2, "put failed: upload unavailable"), (3, "no url minted")]
    assert sum(url.endswith(failed_sha) for url in put_calls) == 2
    assert len(put_calls) == 3  # successful objects are not re-PUT on retry
    assert [r["game_id"] for r in transport.committed[0]] == [1]


@pytest.mark.parametrize("phase", ["mint", "put", "commit"])
def test_quota_wait_uses_slices_and_resumes(conn, tmp_path, monkeypatch, phase):
    _add(conn, tmp_path, 1)
    monkeypatch.setattr(vault_raw, "QUOTA_WAIT_S", 5)
    monkeypatch.setattr(vault_raw, "QUOTA_SLICE_S", 2)
    transport = Transport()
    original = getattr(transport, phase)
    calls, sleeps = [], []

    def quota(*args):
        calls.append(1)
        if len(calls) < 4:
            raise RuntimeError("HTTP 429 vault upload quota exceeded")
        return original(*args)

    result = _push(conn, transport, **{
        "mint_urls" if phase == "mint" else phase: quota, "sleep": sleeps.append})
    assert sleeps == [2, 2, 1] and len(calls) == 4
    assert result["pushed"] == 1 and not result["failed"]


def test_quota_wait_stops_at_one_window_and_reports_elapsed(conn, tmp_path, monkeypatch):
    _add(conn, tmp_path, 1)
    monkeypatch.setattr(vault_raw, "QUOTA_WAIT_S", 5)
    monkeypatch.setattr(vault_raw, "QUOTA_SLICE_S", 2)
    clock, sleeps, calls = [0.0], [], []
    monkeypatch.setattr(vault_raw.time, "perf_counter", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def quota(_items):
        calls.append(1)
        raise RuntimeError("HTTP 429")

    result = _push(conn, mint_urls=quota, sleep=sleep)
    assert sleeps == [2, 2, 1] and len(calls) == 4
    assert result["timings"]["quota_wait"] == 5
    assert result["pushed"] == 0 and result["failed"] == [(1, "mint failed: HTTP 429")]
    assert not _ledger(conn)


@pytest.mark.parametrize("reason", ["HTTP 429 quota exceeded", "temporary timeout"])
def test_cancellation_during_wait_prevents_retry(conn, tmp_path, reason):
    _add(conn, tmp_path, 1)
    cancelled = threading.Event()
    calls = []

    def mint(_items):
        calls.append(1)
        raise RuntimeError(reason)

    with pytest.raises(vault_sync.SyncCancelled):
        _push(conn, mint_urls=mint, sleep=lambda _s: cancelled.set(),
              should_cancel=cancelled.is_set)
    assert calls == [1] and not _ledger(conn)


@pytest.mark.parametrize("phase", ["compress", "hash", "mint", "put", "commit"])
def test_cancellation_between_steps_never_ledgers(conn, tmp_path, monkeypatch, phase):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    transport = Transport()
    cancelled = threading.Event()
    options = {"should_cancel": cancelled.is_set, "put_workers": 3}
    if phase in ("compress", "hash"):
        name = "compress_slp" if phase == "compress" else "content_hash"
        original = getattr(vault_raw, name)
    else:
        original = getattr(transport, phase)

    def cancel(*args):
        result = original(*args)
        cancelled.set()
        return result

    if phase in ("compress", "hash"):
        monkeypatch.setattr(vault_raw, name, cancel)
    else:
        options["mint_urls" if phase == "mint" else phase] = cancel
    with pytest.raises(vault_sync.SyncCancelled):
        _push(conn, transport, **options)
    assert not _ledger(conn)
    if phase != "commit":
        assert transport.committed == []
    if phase == "mint":
        assert transport.puts == {}


def test_pre_cancelled_push_does_no_file_or_transport_work(conn, tmp_path, monkeypatch):
    _add(conn, tmp_path, 1)

    def unexpected(*_args):
        pytest.fail("cancelled sync started work")

    monkeypatch.setattr(vault_raw, "parse_slp", unexpected)
    with pytest.raises(vault_sync.SyncCancelled):
        _push(conn, mint_urls=unexpected, should_cancel=lambda: True)


def test_cancel_after_a_committed_batch_keeps_only_earlier_acknowledgements(conn, tmp_path):
    for gid in (1, 2):
        _add(conn, tmp_path, gid)
    transport = Transport()
    cancelled = threading.Event()
    with pytest.raises(vault_sync.SyncCancelled):
        _push(conn, transport, batch=1, should_cancel=cancelled.is_set,
              on_progress=lambda *_args: cancelled.set())
    assert _ledger(conn) == {2}
    assert len(transport.minted) == len(transport.committed) == 1
    assert _ids(vault_raw.plan_raw(conn)) == [1]


def test_refusal_is_persisted_before_later_cancellation(conn, tmp_path):
    _add(conn, tmp_path, 1)
    _add(conn, tmp_path, 2, body=_slp(players=1))
    cancelled = threading.Event()
    with pytest.raises(vault_sync.SyncCancelled):
        _push(conn, should_cancel=cancelled.is_set,
              on_progress=lambda *_args: cancelled.set())
    conn.rollback()  # closing a cancelled caller must not erase the refusal
    assert _ids(vault_raw.plan_raw(conn)) == [1]
    assert not _ledger(conn)


@pytest.mark.parametrize("when", ["before", "header", "compress", "hash"])
def test_missing_file_is_skipped_without_any_ledger(conn, tmp_path, monkeypatch, when):
    path = _add(conn, tmp_path, 1)
    if when == "before":
        path.unlink()
    else:
        name = {"header": "parse_slp", "compress": "compress_slp", "hash": "content_hash"}[when]
        original = getattr(vault_raw, name)

        def disappear(*args):
            path.unlink()
            return original(*args)

        monkeypatch.setattr(vault_raw, name, disappear)
    result = _push(conn)
    assert result["skipped"] == 1 and result["pushed"] == 0 and not result["failed"]
    assert not _ledger(conn)
    assert conn.execute("SELECT COUNT(*) FROM vault_raw_skips").fetchone()[0] == 0
    assert _ids(vault_raw.plan_raw(conn)) == [1]


@pytest.mark.parametrize("body", [_slp(players=1), b"unreadable header"])
def test_refusal_is_recorded_once_until_file_changes(conn, tmp_path, monkeypatch, body):
    path = _add(conn, tmp_path, 1, body=body)
    st = path.stat()
    conn.execute("INSERT INTO vault_skips VALUES(?,?,?,?,?,?)",
                 (1, vault_sync.DERIVER, st.st_mtime, st.st_size, "derive refused", "now"))
    original = vault_raw.parse_slp
    reads = []

    def read(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(vault_raw, "parse_slp", read)
    result = _push(conn)
    assert result["skipped"] == 1 and not result["failed"] and not _ledger(conn)
    assert _push(conn)["skipped"] == 0 and len(reads) == 1
    skip = conn.execute("SELECT * FROM vault_raw_skips").fetchone()
    assert skip["game_id"] == 1 and skip["codec"] == "gz1" and skip["reason"].startswith("header refused:")
    assert conn.execute("SELECT deriver FROM vault_skips").fetchone()[0] == vault_sync.DERIVER
    path.write_bytes(_slp(players=2))
    os.utime(path, (st.st_mtime + 2, st.st_mtime + 2))
    changed = path.stat()
    conn.execute("UPDATE games SET mtime=?, size=? WHERE id=1", (changed.st_mtime, changed.st_size))
    assert _push(conn)["pushed"] == 1 and len(reads) == 2


def test_file_change_between_compression_and_hash_stays_pending(conn, tmp_path, monkeypatch):
    path = _add(conn, tmp_path, 1)
    original = vault_raw.compress_slp

    def mutate(path):
        body = original(path)
        with open(path, "ab") as file:
            file.write(b"changed")
        return body

    monkeypatch.setattr(vault_raw, "compress_slp", mutate)
    result = _push(conn)
    assert result["pushed"] == result["skipped"] == 0
    assert result["failed"] == [(1, "hash failed: file changed during compression")]
    assert not _ledger(conn)


def test_parallel_puts_finish_before_commit_and_keep_plan_order(conn, tmp_path):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    transport = Transport()
    barrier = threading.Barrier(3)
    threads = set()

    def put(url, body):
        with transport.lock:
            threads.add(threading.get_ident())
        barrier.wait(timeout=5)
        transport.put(url, body)

    result = _push(conn, transport, put=put, put_workers=3)
    assert result["pushed"] == 3 and not result["failed"]
    assert len(threads) == 3
    assert [row["game_id"] for row in transport.committed[0]] == [3, 2, 1]


def test_compression_is_threaded_and_next_batch_overlaps_put(conn, tmp_path, monkeypatch):
    for gid in (1, 2):
        _add(conn, tmp_path, gid)
    original = vault_raw.compress_slp
    put_started, second_compressed = threading.Event(), threading.Event()
    threads = []
    transport = Transport()

    def compress(path):
        threads.append(threading.get_ident())
        if Path(path).name == "g1.slp":
            assert put_started.wait(5), "next batch must not block current PUT"
            body = original(path)
            second_compressed.set()
            return body
        return original(path)

    def put(url, body):
        put_started.set()
        assert second_compressed.wait(5), "next batch must compress during PUT"
        transport.put(url, body)

    monkeypatch.setattr(vault_raw, "compress_slp", compress)
    result = _push(conn, transport, put=put, batch=1, compress_workers=1, put_workers=1)
    assert result["pushed"] == 2 and not result["failed"]
    assert threading.get_ident() not in threads


def test_compress_workers_bound_parallel_compression(conn, tmp_path, monkeypatch):
    for gid in (1, 2, 3, 4):
        _add(conn, tmp_path, gid)
    original = vault_raw.compress_slp
    barrier = threading.Barrier(2)
    threads = set()
    lock = threading.Lock()

    def compress(path):
        with lock:
            threads.add(threading.get_ident())
        barrier.wait(timeout=5)
        return original(path)

    monkeypatch.setattr(vault_raw, "compress_slp", compress)
    result = _push(conn, compress_workers=2)
    assert result["pushed"] == 4 and not result["failed"]
    assert len(threads) == 2 and threading.get_ident() not in threads


def test_timings_progress_and_info_logs_for_each_batch(conn, tmp_path, caplog):
    for gid in (1, 2, 3):
        _add(conn, tmp_path, gid)
    progress = []
    with caplog.at_level(logging.INFO, logger=vault_raw.__name__):
        result = _push(conn, batch=2, on_progress=lambda *args: progress.append(args))
    phases = {"hash", "compress", "mint", "put", "commit", "quota_wait"}
    assert set(result) == {"pushed", "skipped", "failed", "timings"}
    assert set(result["timings"]) == phases
    assert all(isinstance(v, float) and v >= 0 for v in result["timings"].values())
    assert result["timings"]["compress"] > 0 and result["timings"]["hash"] > 0
    records = [record for record in caplog.records if record.name == vault_raw.__name__]
    assert len(records) == 2
    assert all(all(f"{phase}=" in record.message for phase in phases) for record in records)
    assert progress[-1] == (3, 3, 3, 0)
    assert _push(conn)["timings"] == dict.fromkeys(phases, 0.0)


def test_transport_only_mode_and_skipped_progress(conn, tmp_path):
    path = _add(conn, tmp_path, 1)
    _add(conn, tmp_path, 2)
    path.unlink()
    progress = []
    result = _push(conn, commit=None, batch=1, on_progress=lambda *args: progress.append(args))
    assert result["pushed"] == result["skipped"] == 1 and not result["failed"]
    assert progress[-1] == (2, 2, 1, 1)
