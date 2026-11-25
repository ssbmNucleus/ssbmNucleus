from tests.paths import BACKEND
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import jobs  # noqa: E402
from tracker.combos import combo_index  # noqa: E402
from tracker.stats import deep_stats  # noqa: E402
from tracker.store import indexer


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(indexer.SCHEMA)
    return conn


class DeepStatsInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        deep_stats.ensure_schema(self.conn)
        indexer.kv_set(self.conn, "user_codes", ["ME#1"])
        cur = self.conn.execute(
            """INSERT INTO games(path, mtime, size, parse_ok, stage, is_teams,
                                  start_at) VALUES(?,?,?,?,?,?,?)""",
            ("game.slp", 1.0, 100, 1, 31, 0, "2026-01-01"))
        self.game_id = cur.lastrowid
        self.conn.executemany(
            """INSERT INTO game_players
               (game_id, port, type, character, costume, code, name)
               VALUES(?,?,?,?,?,?,?)""",
            [(self.game_id, 1, 0, 2, 0, "ME#1", "me"),
             (self.game_id, 2, 0, 3, 0, "OPP#1", "opp")])

    def tearDown(self):
        self.conn.close()

    def add_deep_row(self, *, status="complete", mtime=1.0, size=100,
                     code="ME#1"):
        self.conn.execute(
            """INSERT INTO deep_rows
               (game_id, character, analyzer_version, start_at, row,
                replay_mtime, replay_size, perspective_code, status)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (self.game_id, 2, deep_stats.ANALYZER_VERSION, "2026-01-01",
             '{"openings": 1}', mtime, size, code, status))

    def test_success_is_invalidated_by_replay_fingerprint_change(self):
        self.add_deep_row()
        self.assertEqual(deep_stats._candidates(self.conn, 2, True), [])
        self.conn.execute("UPDATE games SET mtime=2, size=101 WHERE id=?",
                          (self.game_id,))
        self.assertEqual(len(deep_stats._candidates(self.conn, 2, True)), 1)
        self.assertEqual(deep_stats._load_char_rows(self.conn, 2), [])

    def test_failure_retries_and_changed_identity_hides_old_perspective(self):
        self.add_deep_row(status="failed")
        self.assertEqual(len(deep_stats._candidates(self.conn, 2, True)), 1)
        indexer.kv_set(self.conn, "user_codes", ["OPP#1"])
        rows = deep_stats._candidates(self.conn, 3, True)
        self.assertEqual([(r["my_port"], r["my_code"]) for r in rows],
                         [(2, "OPP#1")])
        self.assertEqual(deep_stats._load_char_rows(self.conn, 2), [])


class TraversalPruneTests(unittest.TestCase):
    def test_walk_error_preserves_unseen_index_rows(self):
        conn = memory_db()
        conn.execute(
            "INSERT INTO games(path, mtime, size, parse_ok) VALUES(?,?,?,1)",
            (r"R:\replays\blocked\old.slp", 1.0, 100))

        def incomplete_walk(_root, onerror=None):
            yield (r"R:\replays", ["blocked"], [])
            onerror(PermissionError("blocked subtree"))

        class KeepOpen:
            def __getattr__(self, name):
                if name == "close":
                    return lambda: None
                return getattr(conn, name)

        with mock.patch.object(indexer, "connect", return_value=KeepOpen()), \
             mock.patch.object(indexer.os, "walk", side_effect=incomplete_walk):
            record = jobs.run_inline(indexer.SCAN_KIND,
                                     lambda job: indexer._scan(job, r"R:\replays"))

        self.assertEqual(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["removed"], 0)
        self.assertIn("traversal incomplete", record["result"]["warning"])
        conn.close()


class ChangedReplayUploadTests(unittest.TestCase):
    """F-E-3: new content at an indexed path is not the upload of the old one."""

    def test_a_changed_file_forgets_its_upload_and_an_unchanged_one_keeps_it(self):
        from tracker.cloud import vault_raw, vault_sync
        with tempfile.TemporaryDirectory() as folder:
            replays = Path(folder) / "replays"
            replays.mkdir()
            changed = replays / "changed.slp"
            kept = replays / "kept.slp"
            changed.write_bytes(b"one")
            kept.write_bytes(b"two")

            def scan():
                return jobs.run_inline(indexer.SCAN_KIND,
                                       lambda job: indexer._scan(job, str(replays)))

            with mock.patch.object(indexer, "DB_PATH", Path(folder) / "nucleome.db"),                  mock.patch("tracker.store.scan_pool.run", return_value=({"players": []}, None)):
                scan()
                conn = indexer.connect()
                try:
                    vault_raw.ensure_raw_schema(conn)
                    ids = {Path(r["path"]).name: r["id"]
                           for r in conn.execute("SELECT id, path FROM games")}
                    for gid in ids.values():
                        conn.execute("INSERT INTO vault_objects(game_id, content_hash, deriver, "
                                     "bytes) VALUES(?,?,?,1)", (gid, f"h{gid}", vault_sync.DERIVER))
                        conn.execute("INSERT INTO vault_raw(game_id, content_hash, codec, bytes) "
                                     "VALUES(?,?,?,1)", (gid, f"h{gid}", vault_raw.RAW_CODEC))
                    conn.commit()
                finally:
                    conn.close()
                changed.write_bytes(b"different content")
                record = scan()
                conn = indexer.connect()
                try:
                    uploads = {table: {r[0] for r in conn.execute(f"SELECT game_id FROM {table}")}
                               for table in ("vault_objects", "vault_raw")}
                finally:
                    conn.close()

        self.assertEqual(record["result"]["updated"], 1)
        self.assertEqual(uploads, {"vault_objects": {ids["kept.slp"]},
                                   "vault_raw": {ids["kept.slp"]}})


class ScanJobFailureTests(unittest.TestCase):
    """F-J-14: a database that cannot open ends the pass failed, never running."""

    def _wait(self, job_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            record = jobs.get(job_id)
            if record["status"] in jobs.FINAL and record.get("ended_at"):
                return record
            time.sleep(0.01)
        raise AssertionError(jobs.get(job_id))

    def _assert_fails_then_frees(self, kind, start):
        def refuse():
            raise sqlite3.OperationalError("unable to open database file")
        with mock.patch.object(indexer, "connect", side_effect=refuse):
            record = self._wait(start())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["error"], "unable to open database file")
            self.assertIsNone(jobs.active_job(kind))
            self._wait(start())

    def test_replay_scan(self):
        self._assert_fails_then_frees(indexer.SCAN_KIND, lambda: indexer.start_scan("R:/none"))

    def test_combo_scan(self):
        self._assert_fails_then_frees(combo_index.SCAN_KIND, combo_index.start_scan)

    def test_deep_stats(self):
        with mock.patch.dict(sys.modules, {"peppi_py": sys.modules.get("peppi_py") or object()}):
            self._assert_fails_then_frees(
                deep_stats.MINE_KIND, lambda: deep_stats.start_mining(2)["job_id"])


class DeepMineFailureTests(unittest.TestCase):
    """A replay that crashes the analyzer is stamped failed; Ctrl-C is not."""

    def _mine(self, error):
        conn = memory_db()
        deep_stats.ensure_schema(conn)
        game_id = conn.execute(
            "INSERT INTO games(path, mtime, size, parse_ok) VALUES(?,?,?,?)",
            (__file__, 1.0, 100, 1)).lastrowid
        game = {"id": game_id, "path": __file__, "my_port": 1, "my_char": 2,
                "start_at": "2026-01-01", "mtime": 1.0, "size": 100,
                "my_code": "ME#1"}

        class KeepOpen:
            def __getattr__(self, name):
                return (lambda: None) if name == "close" else getattr(conn, name)

        class Job:
            def progress(self, *args, **kwargs):
                pass

        with mock.patch.object(indexer, "connect", return_value=KeepOpen()), \
             mock.patch.object(deep_stats, "_candidates", return_value=[game]):
            if error is None:
                deep_stats._mine(Job(), 2)
            else:
                # the mock analyzer cannot cross into the scan worker, so the
                # pass runs inline (the switch tests use); its error handling
                # is what is tested
                with mock.patch.dict("os.environ", {"NUCLEUS_SCAN_INPROC": "1"}), \
                     mock.patch("tracker.stats.analyzer.analyze_game", side_effect=error):
                    deep_stats._mine(Job(), 2)
        return conn.execute("SELECT status FROM deep_rows").fetchall()

    def test_a_peppi_panic_marks_the_game_failed(self):
        PanicException = type("PanicException", (BaseException,), {})
        self.assertEqual([tuple(r) for r in self._mine(PanicException("boom"))], [("failed",)])

    def test_ctrl_c_is_not_swallowed_as_a_bad_replay(self):
        with self.assertRaises(KeyboardInterrupt):
            self._mine(KeyboardInterrupt())

    # The analyzer is peppi_py, which a crafted replay can crash outright, so
    # mining hands each game to the scan worker (tracker/store/scan_pool.py).
    def _mine_through(self, run):
        from tracker.store import scan_pool
        with mock.patch.object(scan_pool, "run", side_effect=run) as worker:
            rows = self._mine(None)
        return worker, rows

    def test_mining_runs_the_analyzer_in_the_scan_worker(self):
        from tracker.stats.analyzer import analyze_game
        worker, rows = self._mine_through(lambda fn, path: [{"slp_port": 1, "apm": 300}])
        self.assertEqual(worker.call_args.args, (analyze_game, __file__))
        self.assertEqual([tuple(r) for r in rows], [("complete",)])

    def test_a_replay_that_crashed_the_worker_is_a_failed_row(self):
        from tracker.store import scan_pool
        _worker, rows = self._mine_through(scan_pool.ScanFailed("crashed the replay worker"))
        self.assertEqual([tuple(r) for r in rows], [("failed",)])

    def test_no_worker_stops_the_job_and_marks_nothing_failed(self):
        from tracker.store import scan_pool
        with self.assertRaises(scan_pool.WorkerUnavailable):
            self._mine_through(scan_pool.WorkerUnavailable("could not start"))


if __name__ == "__main__":
    unittest.main()
