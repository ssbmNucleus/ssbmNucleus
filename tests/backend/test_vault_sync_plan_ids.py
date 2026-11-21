"""plan(game_ids=...) — the share-on-demand upload path.

Whole-library sync is the paid tier now (it only pays off in the phone app),
so on the free tier the ONLY thing that puts a replay in the vault is sharing
it: POST /share pushes that one game and then mints. That narrows to a single
id through plan(), which is where these tests live.

The filter is spliced into plan()'s SQL rather than added as a fixed clause,
so the cases that matter are the boring ones: that it selects the right row at
all, that it still respects the pending test (a re-share must not re-upload),
and that it composes with the skip rules instead of stepping around them.
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


def _add_game(conn, tmp_path, gid, body=b"x", parse_ok=1):
    p = tmp_path / f"g{gid}.slp"
    p.write_bytes(body)
    st = p.stat()
    conn.execute(
        "INSERT INTO games VALUES (?,?,?,?,?,?,?,'[]')",
        (gid, str(p), st.st_mtime, st.st_size, 60.0, parse_ok,
         f"2020-01-{gid:02d}T00:00:00Z"))
    return st


def _ids(rows):
    return sorted(r["id"] for r in rows)


def test_selects_only_the_named_game(tmp_path):
    conn = _db()
    for gid in (1, 2, 3):
        _add_game(conn, tmp_path, gid)

    assert _ids(vault_sync.plan(conn)) == [1, 2, 3]
    assert _ids(vault_sync.plan(conn, game_ids=[2])) == [2]
    assert _ids(vault_sync.plan(conn, game_ids=[1, 3])) == [1, 3]


def test_unknown_ids_select_nothing_rather_than_everything(tmp_path):
    """A bad splice here would drop the filter and plan the whole library --
    i.e. one share silently uploading everything, which is the exact failure
    this feature exists to prevent."""
    conn = _db()
    _add_game(conn, tmp_path, 1)

    assert vault_sync.plan(conn, game_ids=[-99999]) == []
    assert _ids(vault_sync.plan(conn, game_ids=[1, -99999])) == [1]


def test_an_already_pushed_game_plans_to_nothing(tmp_path):
    """Re-sharing must not re-upload: the pending test still applies."""
    conn = _db()
    st = _add_game(conn, tmp_path, 1)
    h = vault_sync.content_hash(conn, str(tmp_path / "g1.slp"), st.st_mtime, st.st_size)
    conn.execute(
        "INSERT INTO vault_objects (game_id, content_hash, deriver, bytes, pushed_at) "
        "VALUES (?,?,?,?,datetime('now'))", (1, h, vault_sync.DERIVER, 10))

    assert vault_sync.plan(conn, game_ids=[1]) == []


def test_unparsed_games_are_still_excluded(tmp_path):
    """parse_ok = 0 means there is nothing to derive. Naming the id directly
    must not become a way around that."""
    conn = _db()
    _add_game(conn, tmp_path, 1, parse_ok=0)

    assert vault_sync.plan(conn, game_ids=[1]) == []


def test_a_recorded_skip_still_wins(tmp_path):
    """vault_skips records a derive refusal for an unchanged file. Sharing the
    game by id must not retry it forever."""
    conn = _db()
    st = _add_game(conn, tmp_path, 1)
    conn.execute(
        "INSERT INTO vault_skips (game_id, deriver, mtime, size, reason) "
        "VALUES (?,?,?,?,'nope')",
        (1, vault_sync.DERIVER, st.st_mtime, st.st_size))

    assert vault_sync.plan(conn, game_ids=[1]) == []


def test_limit_and_ids_compose(tmp_path):
    conn = _db()
    for gid in (1, 2, 3):
        _add_game(conn, tmp_path, gid)

    got = vault_sync.plan(conn, game_ids=[1, 2, 3], limit=2)
    assert len(got) == 2
