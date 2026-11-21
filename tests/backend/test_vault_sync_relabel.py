"""frames-v2 -> frames-v3 deriver migration.

Only Ice Climbers bundles changed shape in v3 (frames.fol); every other blob
is byte-identical. ensure_schema() must relabel non-ICs rows in place so a
whole-library re-upload is never scheduled, while ICs rows keep their v2 label
and fall out of plan() as pending.
"""
import json
import sqlite3

from tracker.cloud import vault_sync


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE games (
        id INTEGER PRIMARY KEY, path TEXT, mtime REAL, size INTEGER,
        duration_s REAL, parse_ok INTEGER, start_at TEXT, players TEXT)""")
    return conn


def _add(conn, gid, chars, deriver="frames-v2"):
    players = json.dumps([{"port": i + 1, "character": c}
                          for i, c in enumerate(chars)])
    conn.execute(
        "INSERT INTO games VALUES (?,?,?,?,?,1,?,?)",
        (gid, f"g{gid}.slp", 0.0, 1, 60.0, f"2020-01-0{gid}T00:00:00Z",
         players))
    conn.execute(
        "INSERT INTO vault_objects VALUES (?,?,?,?,?)",
        (gid, f"hash{gid}", deriver, 100, "2020-01-01T00:00:00Z"))


def test_relabel_keeps_only_ics_pending(monkeypatch):
    # This test pins the v2 -> v3 RELABEL semantics, so hold the current
    # deriver at v3: under the real DERIVER (v4+) every v3 row is also
    # pending re-derive — correct behavior, but a different concern that
    # made this assertion silently version-dependent.
    monkeypatch.setattr(vault_sync, "DERIVER", "frames-v3")
    conn = _db()
    conn.executescript(vault_sync.SCHEMA)
    _add(conn, 1, [2, 20])          # Fox vs Falco -> relabel
    _add(conn, 2, [14, 20])         # ICs vs Falco -> stays v2, re-pushes
    _add(conn, 3, [2, 20], deriver="frames-v3")   # already current
    vault_sync.ensure_schema(conn)

    labels = dict(conn.execute(
        "SELECT game_id, deriver FROM vault_objects"))
    assert labels == {1: "frames-v3", 2: "frames-v2", 3: "frames-v3"}
    pending = [i["id"] for i in vault_sync.plan(conn)]
    assert pending == [2]


def test_relabel_survives_missing_games_table():
    conn = sqlite3.connect(":memory:")
    vault_sync.ensure_schema(conn)   # must not raise on a fresh index
