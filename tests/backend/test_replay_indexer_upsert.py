from tests.paths import BACKEND
import sqlite3
import sys
import unittest
from pathlib import Path


BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tracker.store import indexer  # noqa: E402


def _parsed(*codes):
    return {
        "is_teams": False,
        "players": [
            {
                "port": port,
                "type": 0,
                "character": port,
                "costume": 0,
                "code": code,
                "name": code,
            }
            for port, code in enumerate(codes, start=1)
        ],
    }


class ReplayIndexerUpsertTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        indexer._init_schema(self.conn)     # SCHEMA plus the added columns

    def tearDown(self):
        self.conn.close()

    def players_by_path(self):
        rows = self.conn.execute(
            """SELECT g.path, gp.port, gp.code
                 FROM games AS g
                 LEFT JOIN game_players AS gp ON gp.game_id = g.id
                 ORDER BY g.path, gp.port""").fetchall()
        result = {}
        for row in rows:
            result.setdefault(row["path"], [])
            if row["port"] is not None:
                result[row["path"]].append((row["port"], row["code"]))
        return result

    def test_insert_update_interleavings_keep_players_with_their_game(self):
        indexer._upsert_game(
            self.conn, "a.slp", 1.0, 100, _parsed("A#1", "A#2"))
        indexer._upsert_game(
            self.conn, "b.slp", 1.0, 100, _parsed("B#1", "B#2"))

        # Updating A after inserting B used to replace B's player rows because
        # cursor.lastrowid still held B's id.
        indexer._upsert_game(
            self.conn, "a.slp", 2.0, 101, _parsed("A#3", "A#4"))
        self.assertEqual(
            self.players_by_path(),
            {
                "a.slp": [(1, "A#3"), (2, "A#4")],
                "b.slp": [(1, "B#1"), (2, "B#2")],
            },
        )

        # A failed re-parse removes only that replay's stale players; a later
        # successful parse restores only that replay's current players.
        indexer._upsert_game(self.conn, "b.slp", 2.0, 102, None, "bad replay")
        self.assertEqual(
            self.players_by_path(),
            {"a.slp": [(1, "A#3"), (2, "A#4")], "b.slp": []},
        )

        indexer._upsert_game(
            self.conn, "b.slp", 3.0, 103, _parsed("B#3", "B#4"))
        self.assertEqual(
            self.players_by_path(),
            {
                "a.slp": [(1, "A#3"), (2, "A#4")],
                "b.slp": [(1, "B#3"), (2, "B#4")],
            },
        )

        game_rows = self.conn.execute(
            "SELECT path, mtime, size, parse_ok, parse_error FROM games ORDER BY path"
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in game_rows],
            [("a.slp", 2.0, 101, 1, None), ("b.slp", 3.0, 103, 1, None)],
        )


if __name__ == "__main__":
    unittest.main()
