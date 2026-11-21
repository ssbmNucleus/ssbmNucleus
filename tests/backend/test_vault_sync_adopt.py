"""Reconcile-on-sync: a cold push ledger adopts what the vault already holds.

vault_objects is local-only, so a reinstall or new PC starts with every game
"pending" and would re-derive and re-upload the whole library. adopt_remote()
takes the server's {content_hash: (deriver, bytes)} feed and marks the matches
pushed; only hashing the .slp (cached) is paid. An old-deriver remote row is
NOT adopted — the upgrade re-push must still happen — and a genuine first
sync (empty feed) is a no-op.
"""
import sqlite3

from tracker.cloud import vault_sync


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE games (
        id INTEGER PRIMARY KEY, path TEXT, mtime REAL, size INTEGER,
        duration_s REAL, parse_ok INTEGER, start_at TEXT, players TEXT)""")
    conn.executescript(vault_sync.SCHEMA)
    return conn


def _add_game(conn, tmp_path, gid, body: bytes):
    p = tmp_path / f"g{gid}.slp"
    p.write_bytes(body)
    st = p.stat()
    conn.execute(
        "INSERT INTO games VALUES (?,?,?,?,?,1,?,'[]')",
        (gid, str(p), st.st_mtime, st.st_size, 60.0,
         f"2020-01-0{gid}T00:00:00Z"))
    return vault_sync.content_hash(conn, str(p), st.st_mtime, st.st_size)


def test_adopts_current_deriver_matches_only(tmp_path):
    conn = _db()
    h1 = _add_game(conn, tmp_path, 1, b"game one")   # remote, current deriver
    h2 = _add_game(conn, tmp_path, 2, b"game two")   # remote, OLD deriver
    _add_game(conn, tmp_path, 3, b"game three")      # not remote

    remote = {h1: (vault_sync.DERIVER, 111),
              h2: ("frames-v2", 222),
              "deadbeef": (vault_sync.DERIVER, 333)}  # remote-only: ignored
    assert vault_sync.adopt_remote(conn, remote) == 1

    rows = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT game_id, content_hash, deriver, bytes FROM vault_objects")}
    assert rows == {1: (h1, vault_sync.DERIVER, 111)}
    # 1 is settled; 2 (upgrade) and 3 (new) still pend.
    assert sorted(i["id"] for i in vault_sync.plan(conn)) == [2, 3]


def test_empty_feed_is_a_noop(tmp_path):
    conn = _db()
    _add_game(conn, tmp_path, 1, b"solo first sync")
    assert vault_sync.adopt_remote(conn, {}) == 0
    assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0


def test_reports_progress_over_every_pending_game(tmp_path):
    """The cold reconcile after a sign-in checks the whole library before the
    first upload; it has to say how far along it is, or the panel shows an
    upload of 0 games for a minute or two (2026-10-15)."""
    conn = _db()
    hashes = [_add_game(conn, tmp_path, gid, f"game {gid}".encode())
              for gid in range(1, 6)]
    seen = []
    adopted = vault_sync.adopt_remote(
        conn, {hashes[0]: (vault_sync.DERIVER, 1)},
        on_progress=lambda checked, total: seen.append((checked, total)))
    assert adopted == 1
    assert seen[0] == (0, 5) and seen[-1] == (5, 5)


def test_missing_file_is_skipped_not_fatal(tmp_path):
    conn = _db()
    h1 = _add_game(conn, tmp_path, 1, b"still here")
    conn.execute(
        "INSERT INTO games VALUES (2,?,0.0,1,60.0,1,'2020-01-02T00:00:00Z','[]')",
        (str(tmp_path / "vanished.slp"),))
    remote = {h1: (vault_sync.DERIVER, 10)}
    assert vault_sync.adopt_remote(conn, remote) == 1
    assert [i["id"] for i in vault_sync.plan(conn)] == [2]
