from tests.paths import BACKEND
import sqlite3
import sys
from pathlib import Path

import pytest


BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import jobs  # noqa: E402
from tracker.cloud import vault_jobs, vault_sync  # noqa: E402


def test_cancellation_stops_before_minting_the_next_batch(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    vault_sync.ensure_schema(conn)
    monkeypatch.setattr(vault_sync.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda path: path.encode())
    monkeypatch.setattr(vault_sync, "content_hash",
                        lambda _conn, path, _mtime, _size: f"hash-{path}")
    items = [
        {"id": 1, "path": "one", "mtime": 1, "size": 1},
        {"id": 2, "path": "two", "mtime": 1, "size": 1},
    ]
    minted = []
    cancelled = False

    def mint(batch):
        minted.append([row["game_id"] for row in batch])
        return {row["content_hash"]: "mock://put" for row in batch}

    def progress(done, *_args):
        nonlocal cancelled
        if done == 1:
            cancelled = True

    with pytest.raises(vault_sync.SyncCancelled):
        vault_sync.push(
            conn, items, mint, lambda _url, _body: None,
            commit=lambda uploaded: [row["content_hash"] for row in uploaded],
            on_progress=progress, batch=1,
            should_cancel=lambda: cancelled)

    assert minted == [[1]]
    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 1
    conn.close()


def test_cancellation_during_remote_commit_leaves_local_success_unledgered(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    vault_sync.ensure_schema(conn)
    monkeypatch.setattr(vault_sync.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda _path: b"body")
    monkeypatch.setattr(vault_sync, "content_hash",
                        lambda _conn, _path, _mtime, _size: "hash-one")
    cancelled = False

    def commit(uploaded):
        nonlocal cancelled
        cancelled = True
        return [row["content_hash"] for row in uploaded]

    with pytest.raises(vault_sync.SyncCancelled):
        vault_sync.push(
            conn, [{"id": 1, "path": "one", "mtime": 1, "size": 1}],
            lambda _batch: {"hash-one": "mock://put"},
            lambda _url, _body: None, commit=commit,
            should_cancel=lambda: cancelled)

    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0
    conn.close()


def test_cancellation_during_mint_backoff_skips_retry(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    vault_sync.ensure_schema(conn)
    monkeypatch.setattr(vault_sync.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda _path: b"body")
    monkeypatch.setattr(vault_sync, "content_hash",
                        lambda _conn, _path, _mtime, _size: "hash-one")
    cancelled = False
    mint_calls = 0

    def mint(_batch):
        nonlocal mint_calls
        mint_calls += 1
        raise RuntimeError("temporary mint failure")

    def cancel_during_backoff(_seconds):
        nonlocal cancelled
        cancelled = True

    monkeypatch.setattr(vault_sync.time, "sleep", cancel_during_backoff)

    with pytest.raises(vault_sync.SyncCancelled):
        vault_sync.push(
            conn, [{"id": 1, "path": "one", "mtime": 1, "size": 1}],
            mint, lambda _url, _body: None,
            should_cancel=lambda: cancelled)

    assert mint_calls == 1
    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0
    conn.close()


def test_worker_does_not_record_last_sync_after_credential_changes(monkeypatch):
    class Connection:
        def close(self):
            pass

    generation = vault_jobs._credential_generation
    writes = []

    def sync(_token, **_kwargs):
        vault_jobs._credential_generation += 1
        return {"pushed": 1, "skipped": 0, "failed": []}

    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(vault_jobs.indexer, "connect", Connection)
    monkeypatch.setattr(vault_jobs.indexer, "kv_get",
                        lambda _conn, _key, default=None: "former-owner-token")
    monkeypatch.setattr(vault_jobs.indexer, "kv_set",
                        lambda *_args: writes.append(_args))
    monkeypatch.setattr(vault_jobs.vault_client, "sync", sync)
    monkeypatch.setattr(vault_jobs, "clear_account_sync_state", lambda _conn: None)
    try:
        record = jobs.run_inline(vault_jobs.SYNC_KIND, lambda job: vault_jobs._sync(
            job, "former-owner-token", generation, raw=False))
        assert writes == []
        assert record["status"] == "cancelled"
    finally:
        vault_jobs._credential_generation = generation
