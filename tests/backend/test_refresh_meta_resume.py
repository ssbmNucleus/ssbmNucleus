"""refresh_meta checkpointing (the 2026-08-23 stampede fix).

A pass over the whole sync ledger used to restart from row one whenever any
chunk failed — retried every autorun cycle, that hammered the prod DB into
statement timeouts. With resume_key, rows are walked in content_hash order,
the last committed hash is checkpointed to kv after every chunk, and a rerun
continues after it. Completion clears the key.
"""
import sqlite3

import pytest

from tracker.store import indexer
from tracker.cloud import vault_client, vault_sync


def _db(n_games):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
    conn.executescript(vault_sync.SCHEMA)
    for i in range(n_games):
        # zero-padded so lexicographic order == insertion order
        conn.execute(
            "INSERT INTO vault_objects (game_id, content_hash, deriver, bytes)"
            " VALUES (?,?,?,?)", (i + 1, f"h{i:04d}", vault_sync.DERIVER, 10))
    return conn


@pytest.fixture
def stub_meta(monkeypatch):
    monkeypatch.setattr(vault_client, "_codes_for_sync",
                        lambda conn, token: [])
    monkeypatch.setattr(vault_client, "_game_meta",
                        lambda conn, gid, codes: {"id": gid})
    monkeypatch.setattr(vault_client, "_combos_for", lambda conn, gid: [])


def test_failed_chunk_resumes_from_checkpoint(stub_meta, monkeypatch):
    conn = _db(250)                                   # 3 chunks of 100
    committed = []
    calls = {"n": 0}

    def flaky_commit(token, games, on_skip=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("edge function 500")
        hashes = [g["content_hash"] for g in games]
        committed.extend(hashes)
        return hashes

    monkeypatch.setattr(vault_client, "_commit_games", flaky_commit)
    with pytest.raises(RuntimeError):
        vault_client.refresh_meta("tok", conn=conn, resume_key="pos")
    # chunk 1 landed and was checkpointed; the dead chunk 2 was not
    assert committed == [f"h{i:04d}" for i in range(100)]
    assert indexer.kv_get(conn, "pos") == "h0099"

    monkeypatch.setattr(
        vault_client, "_commit_games",
        lambda token, games, on_skip=None: (
            committed.extend(g["content_hash"] for g in games),
            [g["content_hash"] for g in games])[1])
    out = vault_client.refresh_meta("tok", conn=conn, resume_key="pos")
    # the rerun starts AFTER the checkpoint — every game exactly once
    assert out["refreshed"] == 150
    assert out["resumed_after"] == "h0099"
    assert committed == [f"h{i:04d}" for i in range(250)]
    assert indexer.kv_get(conn, "pos") is None        # cleared on completion
    assert out["complete"] is True


def test_without_resume_key_kv_untouched(stub_meta, monkeypatch):
    conn = _db(50)
    monkeypatch.setattr(vault_client, "_commit_games",
                        lambda token, games, on_skip=None:
                        [g["content_hash"] for g in games])
    out = vault_client.refresh_meta("tok", conn=conn)
    assert out["refreshed"] == 50
    assert conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0] == 0


def test_cancellation_during_commit_does_not_advance_checkpoint(stub_meta,
                                                                monkeypatch):
    conn = _db(150)
    cancelled = False
    calls = 0

    def commit(_token, games, on_skip=None):
        nonlocal cancelled, calls
        calls += 1
        cancelled = True
        return [game["content_hash"] for game in games]

    monkeypatch.setattr(vault_client, "_commit_games", commit)

    with pytest.raises(vault_sync.SyncCancelled):
        vault_client.refresh_meta(
            "former-owner-token", conn=conn, resume_key="pos",
            should_cancel=lambda: cancelled)

    assert calls == 1
    assert indexer.kv_get(conn, "pos") is None


def test_already_cancelled_refresh_makes_no_account_requests(stub_meta,
                                                             monkeypatch):
    conn = _db(1)
    calls = []
    monkeypatch.setattr(vault_client, "_commit_games",
                        lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(vault_sync.SyncCancelled):
        vault_client.refresh_meta(
            "former-owner-token", conn=conn,
            should_cancel=lambda: True)

    assert calls == []


def test_partial_ack_checkpoints_only_contiguous_rows(stub_meta, monkeypatch):
    conn = _db(150)
    calls = []

    def partial(_token, games, on_skip=None):
        calls.append([game["content_hash"] for game in games])
        on_skip("h0050", "timeout")
        return [game["content_hash"] for game in games
                if game["content_hash"] != "h0050"]

    monkeypatch.setattr(vault_client, "_commit_games", partial)
    out = vault_client.refresh_meta("tok", conn=conn, resume_key="pos")

    assert len(calls) == 1
    assert out["skipped"] == ["h0050"]
    assert indexer.kv_get(conn, "pos") == "h0049"
    assert out["complete"] is False                  # resumes at the hole (F-E-1)
