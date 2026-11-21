"""The Stats tab's start/end period filter (stats.compute_stats).

Bounds are inclusive YYYY-MM-DD local days, compared as string prefixes of
games.start_at — the same idiom as the Replays browser's month filter."""
import json

import pytest

from tracker.store import indexer
from tracker.stats import aggregate

ME = "ABC#123"


def _add_game(conn, gid, start_at, my_char=2, opp_char=9):
    conn.execute(
        "INSERT INTO games (id, path, mtime, size, parse_ok, start_at, stage,"
        " is_teams, duration_s, end_method, placements)"
        " VALUES (?, ?, 0, 1, 1, ?, 31, 0, 60, 3, ?)",
        (gid, f"g{gid}.slp", start_at, json.dumps([0, 1])))
    conn.execute(
        "INSERT INTO game_players (game_id, port, type, character, code, name)"
        " VALUES (?, 1, 0, ?, ?, 'me')", (gid, my_char, ME))
    conn.execute(
        "INSERT INTO game_players (game_id, port, type, character, code, name)"
        " VALUES (?, 2, 0, ?, 'OPP#456', 'opp')", (gid, opp_char))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    conn = indexer.connect()
    _add_game(conn, 1, "2023-01-01T10:00:00")
    _add_game(conn, 2, "2023-06-15T20:30:00")
    _add_game(conn, 3, "2024-02-01T09:00:00")
    conn.commit()
    yield conn
    conn.close()


def test_unbounded_sees_everything(conn):
    s = aggregate.compute_stats(conn, [ME])
    assert s["overview"]["games"] == 3
    assert s["overview"]["first_at"] == "2023-01-01T10:00:00"
    assert s["overview"]["last_at"] == "2024-02-01T09:00:00"


def test_start_bound_is_inclusive(conn):
    s = aggregate.compute_stats(conn, [ME], start="2023-06-15")
    assert s["overview"]["games"] == 2
    assert s["overview"]["first_at"] == "2023-06-15T20:30:00"


def test_end_bound_is_inclusive(conn):
    s = aggregate.compute_stats(conn, [ME], end="2023-06-15")
    assert s["overview"]["games"] == 2
    assert s["overview"]["last_at"] == "2023-06-15T20:30:00"


def test_window_and_empty_period(conn):
    s = aggregate.compute_stats(conn, [ME], start="2023-06-01", end="2023-06-30")
    assert s["overview"]["games"] == 1
    empty = aggregate.compute_stats(conn, [ME], start="2025-01-01", end="2025-12-31")
    assert empty["overview"]["games"] == 0
