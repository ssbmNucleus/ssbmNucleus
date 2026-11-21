"""Vault upload throughput (2026-09-21: a 44k-game library took ~15 h at
~1.1 s/game on prod).

The speed-up has four moving parts, each tested here against the rule it must
not break:
  * derives run ahead in a temporary process burst -- plan order, the skip
    ledger and the missing-file rule are unchanged;
  * a batch's PUTs run concurrently -- cancellation still leaves nothing
    ledgered that was not committed;
  * PUTs reuse one connection per worker thread, retry a dead kept-alive
    socket once, and still prove the write with the ETag;
  * a quota refusal from mint is waited out instead of failing every batch.
"""
import hashlib
import http.server
import os
import sqlite3
import threading
import time

import pytest

from tracker.store import scan_pool
from tracker.cloud import vault_client, vault_sync


def _conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    vault_sync.ensure_schema(conn)
    return conn


def _items(tmp_path, names):
    out = []
    for i, name in enumerate(names):
        p = tmp_path / f"{name}.slp"
        if not name.startswith("missing"):
            p.write_bytes(name.encode())
        out.append({"id": i + 1, "path": str(p), "mtime": 1, "size": 1})
    return out


# --- the burst pool -----------------------------------------------------------

def test_burst_runs_in_other_processes_and_shuts_down(monkeypatch):
    monkeypatch.delenv("NUCLEUS_SCAN_INPROC", raising=False)
    monkeypatch.setattr(scan_pool, "_broken", False)
    with scan_pool.burst(2) as pool:
        jobs = [pool.submit(os.getpid) for _ in range(6)]
        pids = {job.result() for job in jobs}
    assert os.getpid() not in pids          # nothing ran in the serving process
    assert 1 <= len(pids) <= 2              # bounded by the worker count


def test_burst_of_one_or_inproc_uses_the_shared_path(monkeypatch):
    calls = []
    monkeypatch.setattr(scan_pool, "run", lambda fn, *a: calls.append(a) or fn(*a))
    with scan_pool.burst(1) as pool:
        assert pool.submit(len, "abc").result() == 3
    monkeypatch.setenv("NUCLEUS_SCAN_INPROC", "1")
    with scan_pool.burst(4) as pool:
        assert pool.submit(len, "ab").result() == 2
    assert calls == [("abc",), ("ab",)]


# --- push with parallel derive + concurrent PUTs -----------------------------

def _fake_derive(path):
    name = os.path.basename(path)
    if name.startswith("refused"):
        return None
    time.sleep(0.01)
    return b"blob:" + name.encode()


def test_parallel_push_keeps_order_skips_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("NUCLEUS_SCAN_INPROC", "1")      # burst -> inline runs
    monkeypatch.setattr(vault_sync, "derive_blob", _fake_derive)
    conn = _conn()
    names = ["g1", "missing2", "refused3", "g4", "g5", "g6", "g7"]
    items = _items(tmp_path, names)

    live = {"now": 0, "max": 0}
    lock = threading.Lock()

    def put(_url, _body):
        with lock:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        time.sleep(0.05)
        with lock:
            live["now"] -= 1

    committed = []

    def commit(uploaded):
        committed.append([u["game_id"] for u in uploaded])
        return [u["content_hash"] for u in uploaded]

    progress = []
    res = vault_sync.push(
        conn, items, lambda b: {x["content_hash"]: "u" for x in b}, put,
        commit=commit, batch=4, derive_workers=3, put_workers=4,
        on_progress=lambda d, *_: progress.append(d))

    assert res["pushed"] == 5 and res["skipped"] == 2 and not res["failed"]
    assert committed == [[1, 4, 5, 6], [7]]             # plan order preserved
    assert live["max"] > 1                              # PUTs overlapped
    assert progress == [1, 4, 5, 6, 7]
    skips = conn.execute("SELECT game_id FROM vault_skips").fetchall()
    assert [r[0] for r in skips] == [3]                 # refused -> ledgered
    ledger = {r[0] for r in conn.execute("SELECT game_id FROM vault_objects")}
    assert ledger == {1, 4, 5, 6, 7}                    # missing -> never


def test_cancel_during_concurrent_puts_ledgers_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("NUCLEUS_SCAN_INPROC", "1")
    monkeypatch.setattr(vault_sync, "derive_blob", _fake_derive)
    conn = _conn()
    items = _items(tmp_path, ["a", "b", "c", "d"])
    cancelled = threading.Event()
    commits = []

    def put(_url, _body):
        cancelled.set()                  # the credential changes mid-batch

    with pytest.raises(vault_sync.SyncCancelled):
        vault_sync.push(
            conn, items, lambda b: {x["content_hash"]: "u" for x in b}, put,
            commit=lambda up: commits.append(up) or [u["content_hash"] for u in up],
            batch=4, derive_workers=2, put_workers=4,
            should_cancel=cancelled.is_set)
    assert commits == []
    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0


def test_quota_refusal_is_waited_out_not_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda p: b"x")
    monkeypatch.setattr(vault_sync.time, "sleep", lambda _s: None)
    conn = _conn()
    items = _items(tmp_path, ["a"])
    calls = []

    def mint(batch):
        calls.append(1)
        if len(calls) < 4:
            raise vault_client.VaultError(
                'vault-sync: HTTP 429 {"error":"vault upload quota exceeded"}')
        return {x["content_hash"]: "u" for x in batch}

    res = vault_sync.push(conn, items, mint, lambda *_: None,
                          commit=lambda up: [u["content_hash"] for u in up])
    assert res["pushed"] == 1 and not res["failed"]
    assert len(calls) == 4


def test_non_quota_mint_failure_still_fails_the_batch_after_one_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda p: b"x")
    monkeypatch.setattr(vault_sync.time, "sleep", lambda _s: None)
    conn = _conn()
    calls = []

    def mint(_batch):
        calls.append(1)
        raise RuntimeError("edge function timeout")

    res = vault_sync.push(conn, _items(tmp_path, ["a"]), mint, lambda *_: None)
    assert len(calls) == 2 and len(res["failed"]) == 1


# --- keep-alive PUT -------------------------------------------------------------

class _PutHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive
    seen_ports = []
    bad_etag = False

    def do_PUT(self):                      # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen_ports.append(self.client_address[1])
        etag = "0" * 32 if type(self).bad_etag else hashlib.md5(body).hexdigest()
        self.send_response(200)
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_a):
        pass


@pytest.fixture
def put_server(monkeypatch):
    monkeypatch.setattr(vault_client.urllib.request, "getproxies", lambda: {})
    _PutHandler.seen_ports = []
    _PutHandler.bad_etag = False
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PutHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    vault_client._put_local.conns = {}
    yield f"http://127.0.0.1:{srv.server_address[1]}/b/k?X-Amz-Signature=s"
    srv.shutdown()
    srv.server_close()
    vault_client._put_local.conns = {}


def test_put_reuses_one_connection(put_server):
    for i in range(5):
        vault_client._put(put_server, f"body{i}".encode())
    assert len(_PutHandler.seen_ports) == 5
    assert len(set(_PutHandler.seen_ports)) == 1        # one TCP connection


def test_put_retries_once_on_a_dead_kept_alive_socket(put_server):
    vault_client._put(put_server, b"one")
    # the server (or a NAT) silently drops the idle connection
    for c in vault_client._put_local.conns.values():
        c.sock.close()
    vault_client._put(put_server, b"two")
    assert len(set(_PutHandler.seen_ports)) == 2


def test_put_still_proves_the_write(put_server):
    _PutHandler.bad_etag = True
    with pytest.raises(vault_client.VaultError, match="etag mismatch"):
        vault_client._put(put_server, b"body")


# --- commit chunking ----------------------------------------------------------

def test_sync_mints_100_but_commits_in_chunks(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(vault_sync, "plan", lambda *a, **k: [{"id": 1}])
    monkeypatch.setattr(vault_client, "_remote_hashes", lambda _t: {})
    monkeypatch.setattr(vault_client, "_codes_for_sync", lambda *_: set())
    monkeypatch.setattr(vault_client, "_game_meta", lambda *_: {})
    monkeypatch.setattr(vault_client, "_combos_for", lambda *_: [])
    sizes = []
    monkeypatch.setattr(vault_client, "_commit_games",
                        lambda _t, games: sizes.append(len(games))
                        or [g["content_hash"] for g in games])
    seen = {}

    def fake_push(_conn, _items, _mint, _put, commit=None, batch=None, **kw):
        seen.update(batch=batch, **kw)
        acked = commit([{"game_id": i, "content_hash": f"h{i}", "bytes": 1}
                        for i in range(batch)])
        return {"pushed": len(acked), "skipped": 0, "failed": []}

    monkeypatch.setattr(vault_sync, "push", fake_push)
    monkeypatch.setattr(vault_sync, "status", lambda _c: {})
    vault_client.sync("tok" * 8, conn=conn)
    assert seen["batch"] == 100
    assert sizes == [vault_client.COMMIT_CHUNK] * (100 // vault_client.COMMIT_CHUNK)
    assert seen["derive_workers"] == vault_client.DERIVE_WORKERS
    assert seen["put_workers"] == vault_client.PUT_WORKERS
