"""Cloud commit acknowledgements must exactly control the local push ledger."""
import sqlite3

from tracker.cloud import vault_client, vault_sync


def _db(count):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, path TEXT, mtime REAL, "
        "size INTEGER, duration_s REAL, parse_ok INTEGER, start_at TEXT)"
    )
    for game_id in range(1, count + 1):
        conn.execute(
            "INSERT INTO games VALUES (?,?,?,?,?,?,?)",
            (game_id, f"game-{game_id}", 1, 1, 60, 1, f"2026-01-{game_id:02d}"),
        )
    vault_sync.ensure_schema(conn)
    return conn


def _run_push(monkeypatch, conn, acknowledged):
    monkeypatch.setattr(vault_sync.os.path, "exists", lambda path: True)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda path: path.encode())
    monkeypatch.setattr(vault_sync, "content_hash", lambda conn, path, *args: f"hash-{path}")
    items = vault_sync.plan(conn)
    return vault_sync.push(
        conn,
        items,
        lambda batch: {item["content_hash"]: "mock://put" for item in batch},
        lambda url, body: None,
        commit=lambda uploaded: acknowledged,
    )


def test_commit_games_returns_only_successful_hashes_after_timeout_split(monkeypatch):
    games = [{"content_hash": h} for h in ("good-a", "bad", "good-b")]
    skipped = []

    def mocked_call(url, payload):
        hashes = [game["content_hash"] for game in payload["games"]]
        if "bad" in hashes:
            raise vault_client.VaultError("database statement timeout")
        return {}

    monkeypatch.setattr(vault_client, "_call", mocked_call)
    acknowledged = vault_client._commit_games(
        "token", games, on_skip=lambda content_hash, error: skipped.append(content_hash))

    assert acknowledged == ["good-a", "good-b"]
    assert skipped == ["bad"]


def test_partial_commit_ledgers_only_acknowledged_games(monkeypatch):
    conn = _db(3)
    result = _run_push(monkeypatch, conn, {"hash-game-1", "hash-game-3"})

    assert result == {
        "pushed": 2,
        "skipped": 0,
        "failed": [(2, "commit not acknowledged")],
    }
    assert conn.execute(
        "SELECT game_id FROM vault_objects ORDER BY game_id").fetchall() == [(1,), (3,)]
    assert conn.execute("SELECT SUM(games) FROM vault_upload_history").fetchone()[0] == 2
    assert [item["id"] for item in vault_sync.plan(conn)] == [2]


def test_persistently_timed_out_singleton_stays_pending(monkeypatch):
    conn = _db(1)
    result = _run_push(monkeypatch, conn, [])

    assert conn.execute("SELECT COUNT(*) FROM vault_upload_history").fetchone()[0] == 0
    assert result["pushed"] == 0
    assert result["failed"] == [(1, "commit not acknowledged")]
    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0
    assert [item["id"] for item in vault_sync.plan(conn)] == [1]


def test_duplicate_replays_are_uploaded_once_and_ledgered_for_every_copy(monkeypatch):
    """The same replay in two folders: one content hash, two local games.

    Committing both in one batch made vault-sync's upsert touch a row twice,
    which Postgres refuses, so the batch failed on every sync (2026-09-25)."""
    conn = _db(3)
    monkeypatch.setattr(vault_sync.os.path, "exists", lambda path: True)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda path: path.encode())
    monkeypatch.setattr(vault_sync, "content_hash",
                        lambda conn, path, *args: "same" if path != "game-2" else "other")
    minted, puts, committed = [], [], []

    def commit(uploaded):
        committed.append([u["content_hash"] for u in uploaded])
        return [u["content_hash"] for u in uploaded]

    result = vault_sync.push(
        conn, vault_sync.plan(conn),
        lambda batch: minted.append([b["content_hash"] for b in batch])
        or {b["content_hash"]: "mock://put" for b in batch},
        lambda url, body: puts.append(url),
        commit=commit,
    )

    assert result == {"pushed": 3, "skipped": 0, "failed": []}
    assert sorted(minted[0]) == ["other", "same"]
    assert len(puts) == 2
    assert sorted(committed[0]) == ["other", "same"]
    assert conn.execute(
        "SELECT game_id, content_hash FROM vault_objects ORDER BY game_id").fetchall() == [
        (1, "same"), (2, "other"), (3, "same")]
    assert conn.execute("SELECT SUM(games) FROM vault_upload_history").fetchone()[0] == 3
    assert vault_sync.plan(conn) == []


def test_a_failed_duplicate_fails_every_copy(monkeypatch):
    conn = _db(2)
    result = _run_push_same_hash(monkeypatch, conn, acknowledged=[])

    assert result["pushed"] == 0
    assert sorted(result["failed"]) == [(1, "commit not acknowledged"),
                                        (2, "commit not acknowledged")]
    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0


def _run_push_same_hash(monkeypatch, conn, acknowledged):
    monkeypatch.setattr(vault_sync.os.path, "exists", lambda path: True)
    monkeypatch.setattr(vault_sync, "_derive_offprocess", lambda path: path.encode())
    monkeypatch.setattr(vault_sync, "content_hash", lambda conn, path, *args: "same")
    return vault_sync.push(
        conn, vault_sync.plan(conn),
        lambda batch: {b["content_hash"]: "mock://put" for b in batch},
        lambda url, body: None,
        commit=lambda uploaded: acknowledged,
    )
