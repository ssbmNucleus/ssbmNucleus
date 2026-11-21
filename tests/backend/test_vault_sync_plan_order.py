"""plan() order — bug #64 (Discord 2026-09-19).

A 44k-game library synced oldest first: hours of 2021-22 replays that predate
the player's current connect code went up with no `user_port`, and the phone
(which only lists games attributed to your codes) showed "0 games" until the
recent end of the library finally arrived. The phone already lists games per
committed batch; what made it wait was the ORDER. A whole-library sync must
push newest first.
"""
import sqlite3

from tracker.cloud import vault_client, vault_sync


def _db(tmp_path, dates):
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE games (
        id INTEGER PRIMARY KEY, path TEXT, mtime REAL, size INTEGER,
        duration_s REAL, parse_ok INTEGER, start_at TEXT, players TEXT)""")
    conn.executescript(vault_sync.SCHEMA)
    for gid, start_at in dates.items():
        p = tmp_path / f"g{gid}.slp"
        p.write_bytes(b"x")
        st = p.stat()
        conn.execute("INSERT INTO games VALUES (?,?,?,?,?,1,?,'[]')",
                     (gid, str(p), st.st_mtime, st.st_size, 60.0, start_at))
    return conn


DATES = {
    1: "2021-01-04T00:00:00Z",   # pre-current-code era: unlistable on the phone
    2: "2026-09-19T00:00:00Z",
    3: "2023-06-01T00:00:00Z",
    4: None,                     # undated: the phone can't list it either
}


def test_default_plan_is_newest_first(tmp_path):
    conn = _db(tmp_path, DATES)
    assert [r["id"] for r in vault_sync.plan(conn)] == [2, 3, 1, 4]


def test_a_limited_default_plan_takes_the_newest(tmp_path):
    conn = _db(tmp_path, DATES)
    assert [r["id"] for r in vault_sync.plan(conn, limit=1)] == [2]


def test_oldest_first_is_still_available(tmp_path):
    conn = _db(tmp_path, DATES)
    got = [r["id"] for r in vault_sync.plan(conn, newest_first=False)]
    assert got[-2:] == [3, 2]


def test_whole_library_sync_defaults_to_newest_first():
    """vault_jobs calls sync() without the flag, so the default IS the app's
    behaviour."""
    import inspect
    assert inspect.signature(vault_client.sync).parameters["newest_first"].default is True
