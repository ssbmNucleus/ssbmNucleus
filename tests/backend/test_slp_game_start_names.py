"""Player names and connect codes from GameStart, and the one-time re-parse
of rows the older parser wrote without them.

Since Slippi 3.9.0 a replay's GameStart event holds each port's online display
name and connect code (Shift-JIS, the code's '#' full width). The metadata
footer repeats them, except where a client left its `names` empty: the Nucleus
client wrote its online replays that way, so the Tracker indexed them with no
name or code and could not tell which player was the user. slp_meta now reads
GameStart where the footer has nothing; the index re-parses, once, the rows
that need it (indexer.PARSE_BASIS). Every replay here is built in the test.
"""
import json
import os
import struct

import pytest

from tracker.store import indexer, scan_pool, slp_meta

GS_SIZE = 0x33C   # the GameStart payload a 3.20 replay carries
END_SIZE = 0x08


# --- building replays ------------------------------------------------------------

def _key(text):
    raw = text.encode()
    return b"U" + bytes([len(raw)]) + raw


def ubjson(value):
    """The little UBJSON the metadata footer uses: objects, strings, ints."""
    if isinstance(value, dict):
        return b"{" + b"".join(_key(k) + ubjson(v) for k, v in value.items()) + b"}"
    if isinstance(value, str):
        return b"S" + _key(value)
    return b"l" + struct.pack(">i", value)


def metadata(names=None, last_frame=600):
    """A footer like Dolphin's; names = {port: {"netplay": .., "code": ..}}.
    A port without an entry gets the empty `names` the Nucleus client wrote."""
    names = names or {}
    return {"startAt": "2026-01-01T00:00:00Z", "lastFrame": last_frame,
            "players": {str(port - 1): {"names": names.get(port, {}), "characters": {"18": 100}}
                        for port in (1, 2, 3, 4)},
            "playedOn": "dolphin"}


def field(value, width):
    raw = value.encode("cp932") if isinstance(value, str) else value
    assert len(raw) < width, "fixture field too long"
    return raw.ljust(width, b"\0")


def game_start(players, version=(3, 20, 0), teams=False, size=GS_SIZE):
    """players: [{"port", "character", "type", "team", "name", "code"}]; name
    and code are text (encoded cp932) or raw bytes, written at the spec's
    GameStart offsets."""
    ev = bytearray(0x400)
    ev[0] = slp_meta.CMD_GAME_START
    ev[1:4] = bytes(version)
    ev[0x0D] = int(teams)
    struct.pack_into(">H", ev, 0x13, 31)                    # Battlefield
    for i in range(4):
        ev[0x66 + 0x24 * i] = slp_meta.PLAYER_TYPE_EMPTY
    for p in players:
        i = p["port"] - 1
        base = 0x65 + 0x24 * i
        ev[base] = p.get("character", 2)
        ev[base + 1] = p.get("type", slp_meta.PLAYER_TYPE_HUMAN)
        ev[base + 9] = p.get("team", 0)
        if p.get("name") is not None:
            off = slp_meta.GS_NAME_OFF + slp_meta.GS_NAME_LEN * i
            ev[off:off + slp_meta.GS_NAME_LEN] = field(p["name"], slp_meta.GS_NAME_LEN)
        if p.get("code") is not None:
            off = slp_meta.GS_CODE_OFF + slp_meta.GS_CODE_LEN * i
            ev[off:off + slp_meta.GS_CODE_LEN] = field(p["code"], slp_meta.GS_CODE_LEN)
    return bytes(ev[:1 + size])


def replay(gs, meta):
    """A whole .slp: payload table, GameStart, GameEnd, metadata footer."""
    sizes = {slp_meta.CMD_GAME_START: len(gs) - 1, slp_meta.CMD_GAME_END: END_SIZE}
    table = bytes([slp_meta.CMD_EVENT_PAYLOADS, 1 + 3 * len(sizes)]) + b"".join(
        bytes([cmd]) + struct.pack(">H", size) for cmd, size in sizes.items())
    end = bytearray(1 + END_SIZE)
    end[0], end[1], end[2] = slp_meta.CMD_GAME_END, 2, 0xFF   # GAME!, no LRAS
    end[3:7] = bytes([0, 1, 0xFF, 0xFF])                       # port 1 won
    raw = table + gs + bytes(end)
    return (slp_meta.HEADER + struct.pack(">i", len(raw)) + raw
            + b"U\x08metadata" + ubjson(meta) + b"}")


# Synthetic players for a replay with GameStart names and an empty metadata `names` object.
NUCLEUS_PLAYERS = [
    {"port": 1, "character": 9, "name": "Player One", "code": b"ONE\x81\x94835"},
    {"port": 2, "character": 2, "name": "Player Two", "code": b"TWO\x81\x94187"},
]


@pytest.fixture
def write(tmp_path):
    def write(data, name="game.slp"):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)
    return write


def names(parsed):
    return [(p["port"], p["name"], p["code"]) for p in parsed["players"]]


# --- the parser --------------------------------------------------------------------

def test_metadata_names_still_win_over_game_start(write):
    meta = metadata({1: {"netplay": "Meta One", "code": "ONE#1"},
                     2: {"netplay": "Meta Two", "code": "TWO#2"}})
    got = slp_meta.parse_slp(write(replay(game_start(NUCLEUS_PLAYERS), meta)))
    assert names(got) == [(1, "Meta One", "ONE#1"), (2, "Meta Two", "TWO#2")]


def test_game_start_fills_in_when_the_metadata_names_are_empty(write):
    got = slp_meta.parse_slp(write(replay(game_start(NUCLEUS_PLAYERS), metadata())))
    # the full-width '＃' (0x81 0x94) is the plain '#' the metadata would hold
    assert names(got) == [(1, "Player One", "ONE#835"), (2, "Player Two", "TWO#187")]
    # nothing else moves: the output keys are the ones it always had
    assert set(got) == {"version", "is_teams", "stage", "players", "start_at", "played_on",
                        "last_frame", "duration_s", "end_method", "lras_initiator", "placements"}
    assert set(got["players"][0]) == {"port", "type", "character", "costume", "team", "name", "code"}


def test_no_names_anywhere_stays_none(write):
    offline = [{"port": 1}, {"port": 2, "type": slp_meta.PLAYER_TYPE_CPU}]
    got = slp_meta.parse_slp(write(replay(game_start(offline), metadata())))
    assert names(got) == [(1, None, None), (2, None, None)]
    assert slp_meta.game_start_names(write(replay(game_start(offline), metadata()), "o.slp")) == {
        1: (None, None), 2: (None, None)}


def test_each_field_falls_back_on_its_own(write):
    meta = metadata({1: {"netplay": "Footer Name"}, 2: {"code": "FOOT#9"}})
    got = slp_meta.parse_slp(write(replay(game_start(NUCLEUS_PLAYERS), meta)))
    assert names(got) == [(1, "Footer Name", "ONE#835"), (2, "Player Two", "FOOT#9")]


@pytest.mark.parametrize("raw_name, raw_code, want", [
    pytest.param("マルス", "AB#1", ("マルス", "AB#1"), id="japanese-name-ascii-hash"),
    pytest.param("ＡＢ  ", b"AB\x81\x94123", ("ＡＢ", "AB#123"), id="full-width-name-kept"),
    pytest.param(b"Ok", "ＡＢ＃１", ("Ok", "AB#1"), id="full-width-code-made-ascii"),
    pytest.param(b"AB\x81\x20", b"AB\x81\x941", (None, "AB#1"), id="bad-trail-byte"),
    pytest.param(b"ABC\x82", b"AB\x81\x941", (None, "AB#1"), id="lone-lead-byte"),
    pytest.param(b"AB\x07C", b"AB\x81\x941", (None, "AB#1"), id="control-char"),
    pytest.param(b"\xf0\x40", b"AB\x81\x941", (None, "AB#1"), id="private-use"),
    pytest.param(b"   ", b"AB\x81\x941", (None, "AB#1"), id="blank-name"),
    pytest.param("Fine", b"ABCD123", ("Fine", None), id="code-without-hash"),
    pytest.param("Fine", b"AB \x81\x941", ("Fine", None), id="code-with-space"),
    pytest.param("Fine", b"\x81\x94123", ("Fine", None), id="code-without-tag"),
    pytest.param("Fine", b"AB\x81\x94", ("Fine", None), id="code-without-digits"),
    pytest.param("Fine", b"AB\x81\x941\xff", ("Fine", None), id="code-bad-byte"),
])
def test_a_bad_field_is_simply_absent(write, raw_name, raw_code, want):
    players = [{"port": 1, "name": raw_name, "code": raw_code},
               {"port": 2, "name": "Other", "code": b"OTH\x81\x942"}]
    got = slp_meta.parse_slp(write(replay(game_start(players), metadata())))
    assert names(got) == [(1, *want), (2, "Other", "OTH#2")]


def test_a_four_player_teams_game(write):
    players = [
        {"port": 1, "character": 2, "team": 0, "name": "Red One", "code": b"RED\x81\x941"},
        {"port": 2, "character": 9, "team": 0, "name": "Red Two", "code": b"RED\x81\x942"},
        {"port": 3, "character": 20, "team": 1, "name": "Blue One", "code": b"BLU\x81\x941"},
        {"port": 4, "character": 15, "team": 1, "name": "Blue Two", "code": b"BLU\x81\x942"},
    ]
    # the footer names ports 1 and 3 only, differently: theirs win there
    meta = metadata({1: {"netplay": "Footer Red", "code": "FRED#1"},
                     3: {"netplay": "Footer Blue", "code": "FBLU#3"}})
    got = slp_meta.parse_slp(write(replay(game_start(players, teams=True), meta)))
    assert got["is_teams"] is True
    assert [(p["port"], p["team"], p["name"], p["code"]) for p in got["players"]] == [
        (1, 0, "Footer Red", "FRED#1"), (2, 0, "Red Two", "RED#2"),
        (3, 1, "Footer Blue", "FBLU#3"), (4, 1, "Blue Two", "BLU#2")]


def test_game_start_is_read_only_where_the_spec_has_the_names(write):
    # before 3.9.0 those bytes are not names, whatever they hold
    old = slp_meta.parse_slp(write(replay(game_start(NUCLEUS_PLAYERS, version=(3, 8, 0)),
                                          metadata()), "old.slp"))
    assert names(old) == [(1, None, None), (2, None, None)]
    # a payload that stops before the code block: no names, no error
    short = game_start(NUCLEUS_PLAYERS, version=(3, 9, 0), size=0x1F0)
    assert names(slp_meta.parse_slp(write(replay(short, metadata()), "short.slp"))) == [
        (1, None, None), (2, None, None)]
    ok = game_start(NUCLEUS_PLAYERS, version=(3, 9, 0), size=0x249)
    assert names(slp_meta.parse_slp(write(replay(ok, metadata()), "39.slp"))) == [
        (1, "Player One", "ONE#835"), (2, "Player Two", "TWO#187")]


def test_game_start_names_reads_game_start_alone_and_never_raises(write, tmp_path):
    gs = game_start(NUCLEUS_PLAYERS)
    # cut right after GameStart: no frames, no GameEnd, no footer
    head = replay(gs, metadata())[:slp_meta.RAW_START + 8 + len(gs)]
    assert slp_meta.game_start_names(write(head, "g.slp")) == {
        1: ("Player One", "ONE#835"), 2: ("Player Two", "TWO#187")}
    assert slp_meta.game_start_names(write(b"not a replay" * 10, "junk.slp")) == {}
    assert slp_meta.game_start_names(write(slp_meta.HEADER + b"\0\0\0\x10\x35", "cut.slp")) == {}
    assert slp_meta.game_start_names(str(tmp_path / "missing.slp")) == {}


# --- the re-parse after the update -------------------------------------------------

class _Job:
    def progress(self, *args, **kwargs):
        pass


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A replay folder, its own index, the worker inline, and the calls the
    scan hands the worker (function name, file name)."""
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setenv("NUCLEUS_SCAN_INPROC", "1")
    folder = tmp_path / "Slippi"
    folder.mkdir()
    calls = []
    real_run = scan_pool.run

    def run(fn, *args, **kwargs):
        calls.append((fn.__name__, os.path.basename(args[0])))
        return real_run(fn, *args, **kwargs)
    monkeypatch.setattr(scan_pool, "run", run)

    class Library:
        def add(self, name, data):
            (folder / name).write_bytes(data)

        def scan(self):
            calls.clear()
            return indexer._scan(_Job(), str(folder))

        def row(self, name):
            conn = indexer.connect()
            try:
                return conn.execute("SELECT * FROM games WHERE path = ?",
                                    (str(folder / name),)).fetchone()
            finally:
                conn.close()
    lib = Library()
    lib.calls = calls
    return lib


def _counts(result):
    return {k: result[k] for k in ("total", "done", "added", "updated", "removed", "failed")}


def _index_as_the_old_parser_did(library, monkeypatch):
    """Scan with GameStart names unread (what the parser did before), then
    clear the parse basis as the column migration leaves every older row."""
    with monkeypatch.context() as m:
        m.setattr(slp_meta, "GS_NAMES_VERSION", (99, 0))
        library.scan()
    conn = indexer.connect()
    try:
        conn.execute("UPDATE games SET parse_basis = NULL")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def old_index(library, monkeypatch):
    """Four games indexed by the old parser: one the Nucleus client recorded
    (names in GameStart only), an offline one (no names anywhere), a normal
    online one (names in the footer) and a 3.8 one (no GameStart names)."""
    library.add("nucleus.slp", replay(game_start(NUCLEUS_PLAYERS), metadata()))
    library.add("offline.slp", replay(game_start([{"port": 1}, {"port": 2}]), metadata()))
    library.add("stock.slp", replay(game_start(NUCLEUS_PLAYERS), metadata(
        {1: {"netplay": "Footer Player", "code": "FOOT#69"},
         2: {"netplay": "Snow", "code": "SNOW#206"}})))
    library.add("old.slp", replay(game_start(NUCLEUS_PLAYERS, version=(3, 8, 0)), metadata()))
    _index_as_the_old_parser_did(library, monkeypatch)
    conn = indexer.connect()
    try:
        nucleus = conn.execute("SELECT id, mtime FROM games WHERE path LIKE '%nucleus.slp'").fetchone()
        assert json.loads(conn.execute("SELECT players FROM games WHERE id=?",
                                       (nucleus["id"],)).fetchone()[0])[1]["code"] is None
        # its combos were extracted (with no codes), and it was synced
        conn.execute("UPDATE games SET combos_at = mtime")
        conn.execute("INSERT INTO combos(game_id, port, opp_port, start_frame, end_frame) "
                     "VALUES(?, 2, 1, 10, 50)", (nucleus["id"],))
        conn.execute("CREATE TABLE vault_objects (game_id INTEGER, content_hash TEXT)")
        conn.execute("INSERT INTO vault_objects VALUES(?, 'abc')", (nucleus["id"],))
        conn.commit()
    finally:
        conn.close()
    return library


def test_the_reparse_selects_only_rows_the_new_parser_can_improve(old_index):
    conn = indexer.connect()
    try:
        picked = indexer._reparse_candidates(conn)
    finally:
        conn.close()
    # the footer-named game and the 3.8 one are never read again
    assert sorted(os.path.basename(p) for p in picked) == ["nucleus.slp", "offline.slp"]


def test_the_next_scan_names_the_nucleus_game_once(old_index):
    result = old_index.scan()
    assert sorted(old_index.calls) == [("reparse_for_index", "nucleus.slp"),
                                       ("reparse_for_index", "offline.slp")]
    # the renamed game counts as updated, so the Replays list reloads
    assert _counts(result) == {"total": 2, "done": 2, "added": 0, "updated": 1,
                               "removed": 0, "failed": 0}

    nucleus = old_index.row("nucleus.slp")
    assert [(p["port"], p["name"], p["code"]) for p in json.loads(nucleus["players"])] == [
        (1, "Player One", "ONE#835"), (2, "Player Two", "TWO#187")]
    assert nucleus["parse_basis"] == indexer.PARSE_BASIS
    assert nucleus["combos_at"] is None            # the combo pass copies the names in
    conn = indexer.connect()
    try:
        assert sorted(tuple(r) for r in conn.execute(
            "SELECT port, code, name FROM game_players WHERE game_id=?", (nucleus["id"],))) == [
            (1, "ONE#835", "Player One"), (2, "TWO#187", "Player Two")]
        # same file, same content: its cloud ledger stays
        assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 1
        # the Tracker now finds it under the user's code, against the opponent
        listed = indexer.query_games(conn, ["two#187"])
        assert [(g["user_port"], [p["name"] for p in g["players"] if p["port"] != g["user_port"]])
                for g in listed["games"]] == [(2, ["Player One"])]
    finally:
        conn.close()

    # the offline game was looked at (one small read), changed nothing, and is stamped
    offline = old_index.row("offline.slp")
    assert offline["parse_basis"] == indexer.PARSE_BASIS and offline["combos_at"] is not None
    # rows that needed nothing were not touched at all
    assert old_index.row("stock.slp")["parse_basis"] is None
    assert old_index.row("old.slp")["parse_basis"] is None

    # idempotent: the next scan reads nothing and changes nothing
    again = old_index.scan()
    assert old_index.calls == []
    assert _counts(again) == {"total": 0, "done": 0, "added": 0, "updated": 0,
                              "removed": 0, "failed": 0}


def test_a_failed_reparse_keeps_the_old_row_and_is_not_retried(old_index, monkeypatch):
    before = old_index.row("nucleus.slp")
    real_run = scan_pool.run

    def crash_on_nucleus(fn, *args, **kwargs):
        if args[0].endswith("nucleus.slp"):
            old_index.calls.append((fn.__name__, "nucleus.slp"))
            raise scan_pool.ScanFailed("nucleus.slp crashed the replay worker", args[0])
        return real_run(fn, *args, **kwargs)
    monkeypatch.setattr(scan_pool, "run", crash_on_nucleus)

    result = old_index.scan()
    assert result["failed"] == 1 and result["updated"] == 0
    after = old_index.row("nucleus.slp")
    assert (after["players"], after["parse_ok"], after["combos_at"]) == (
        before["players"], 1, before["combos_at"])
    assert after["parse_basis"] == indexer.PARSE_BASIS
    old_index.scan()
    assert ("reparse_for_index", "nucleus.slp") not in old_index.calls


def test_a_changed_file_is_parsed_as_before_and_a_new_one_is_stamped(old_index, tmp_path):
    data = replay(game_start(NUCLEUS_PLAYERS), metadata(last_frame=900))
    old_index.add("nucleus.slp", data)          # rewritten: a normal re-parse
    later = old_index.row("nucleus.slp")["mtime"] + 10
    os.utime(tmp_path / "Slippi" / "nucleus.slp", (later, later))
    old_index.add("new.slp", data)
    result = old_index.scan()
    assert ("parse_for_index", "nucleus.slp") in old_index.calls
    assert ("reparse_for_index", "nucleus.slp") not in old_index.calls
    assert result["added"] == 1
    for name in ("nucleus.slp", "new.slp"):
        row = old_index.row(name)
        assert row["parse_basis"] == indexer.PARSE_BASIS
        assert json.loads(row["players"])[1]["code"] == "TWO#187"


def test_a_deleted_replay_is_pruned_not_reparsed(old_index, tmp_path):
    os.remove(tmp_path / "Slippi" / "nucleus.slp")
    old_index.scan()
    assert ("reparse_for_index", "nucleus.slp") not in old_index.calls
    assert old_index.row("nucleus.slp") is None   # pruned as deleted, as before


def test_an_existing_index_gets_the_column_with_every_row_unstamped(tmp_path, monkeypatch):
    """The upgrade itself: an ADD COLUMN on first connect, no rewrite of rows."""
    import sqlite3
    db = tmp_path / "nucleome.db"
    old = sqlite3.connect(db)
    old.execute("""CREATE TABLE games (          -- as builds before it made it
        id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, mtime REAL NOT NULL,
        size INTEGER NOT NULL, parse_ok INTEGER NOT NULL DEFAULT 1, parse_error TEXT,
        start_at TEXT, played_on TEXT, version TEXT, stage INTEGER, is_teams INTEGER,
        last_frame INTEGER, duration_s REAL, end_method INTEGER, lras_initiator INTEGER,
        placements TEXT, players TEXT, final_state TEXT, combos_at REAL)""")
    old.execute("INSERT INTO games(path, mtime, size) VALUES('a.slp', 1, 1)")
    old.commit()
    old.close()
    monkeypatch.setattr(indexer, "DB_PATH", db)
    conn = indexer.connect()
    try:
        assert conn.execute("SELECT parse_basis FROM games").fetchall()[0][0] is None
    finally:
        conn.close()
