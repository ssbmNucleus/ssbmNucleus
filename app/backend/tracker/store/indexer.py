"""SQLite replay index for nucleOME mode.

Scans the Slippi replay directory (a ``replay_scan`` job: from Replays, or
from the cloud loop when automatic processing is on) into
storage/nucleome.db, incrementally: files are re-parsed only when their
(mtime, size) changed, and rows for deleted files are pruned.
"""
import json
import os
import sqlite3
import threading

from core import jobs
from core.config import STORAGE_PATH
from .pass_progress import PassProgress
from .slp_meta import parse_slp, read_final_state, SlpParseError

# Vanilla stage ids only — replays on modded stages ("Stage 326") are indexed
# but never surfaced: supporting them isn't worth it (no names, no icons,
# usually unwatchable without the exact build).
VANILLA_STAGE_IDS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
                     18, 19, 20, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32)
_STAGE_MARKS = ",".join(str(s) for s in VANILLA_STAGE_IDS)

# Same call for characters: replays featuring MODDED characters ("Char 35",
# external id > 25) are indexed but never surfaced — no names, no icons, and
# the watch pipeline can't dress them.
VANILLA_CHAR_IDS = tuple(range(26))
_CHAR_MARKS = ",".join(str(c) for c in VANILLA_CHAR_IDS)
_NO_MODDED_CHARS = ("g.id NOT IN (SELECT game_id FROM game_players "
                    f"WHERE character IS NULL OR character NOT IN ({_CHAR_MARKS}))")

DB_PATH = STORAGE_PATH / "nucleome.db"

# A scan is a job (core/jobs.py). It runs every ten minutes under the cloud
# loop and owns nothing to put back, so its records stay in memory.
SCAN_KIND = "replay_scan"
jobs.register_kind(SCAN_KIND, label="Replay scan", keep=5)

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    parse_ok INTEGER NOT NULL DEFAULT 1,
    parse_error TEXT,
    start_at TEXT,
    played_on TEXT,
    version TEXT,
    stage INTEGER,
    is_teams INTEGER,
    last_frame INTEGER,
    duration_s REAL,
    end_method INTEGER,
    lras_initiator INTEGER,
    placements TEXT,
    players TEXT
);
CREATE TABLE IF NOT EXISTS game_players (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    port INTEGER NOT NULL,
    type INTEGER NOT NULL,
    character INTEGER,
    costume INTEGER,
    code TEXT,
    name TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS rank_samples (
    code TEXT NOT NULL,
    at TEXT NOT NULL,
    rating REAL NOT NULL,
    tier TEXT,
    wins INTEGER,
    losses INTEGER
);
CREATE TABLE IF NOT EXISTS combos (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    port INTEGER NOT NULL,
    opp_port INTEGER NOT NULL,
    code TEXT,
    opp_code TEXT,
    name TEXT,
    opp_name TEXT,
    character INTEGER,
    opp_character INTEGER,
    stage INTEGER,
    start_at TEXT,
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    start_percent REAL,
    end_percent REAL,
    damage REAL,
    moves INTEGER,
    hits INTEGER,
    did_kill INTEGER NOT NULL DEFAULT 0,
    true_combo INTEGER,
    opening_move INTEGER,
    ending_move INTEGER,
    moves_json TEXT
);
-- opaque, tool-issued clip references. Randall can hallucinate raw frame
-- numbers in a clip token; a ref is a hash of REAL frames minted by a tool, so
-- a fabricated token simply doesn't resolve (see tracker.video.clip_refs).
CREATE TABLE IF NOT EXISTS clip_refs (
    ref TEXT PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    label TEXT,
    created REAL
);
CREATE INDEX IF NOT EXISTS idx_combos_game ON combos(game_id);
CREATE INDEX IF NOT EXISTS idx_combos_code ON combos(code, character);
CREATE INDEX IF NOT EXISTS idx_combos_opp_code ON combos(opp_code);
CREATE INDEX IF NOT EXISTS idx_combos_damage ON combos(damage);
CREATE INDEX IF NOT EXISTS idx_combos_start ON combos(start_at);
-- Browse the newest highlights without sorting complete combo/JSON rows.
-- The trailing filters also let the exact result count use the same index.
CREATE INDEX IF NOT EXISTS idx_combos_code_recent ON combos(
    code, start_at DESC, game_id DESC, start_frame ASC, id ASC, moves, damage);
CREATE INDEX IF NOT EXISTS idx_combos_opp_recent ON combos(
    opp_code, start_at DESC, game_id DESC, start_frame ASC, id ASC, moves, damage);
CREATE INDEX IF NOT EXISTS idx_rank_samples_code ON rank_samples(code, at);
CREATE INDEX IF NOT EXISTS idx_games_start ON games(start_at DESC);
CREATE INDEX IF NOT EXISTS idx_games_stage ON games(stage);
CREATE INDEX IF NOT EXISTS idx_gp_game ON game_players(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_code ON game_players(code);
CREATE INDEX IF NOT EXISTS idx_gp_char ON game_players(character);
CREATE INDEX IF NOT EXISTS idx_gp_code_char ON game_players(code, character);
CREATE INDEX IF NOT EXISTS idx_gp_game_char ON game_players(game_id, character);
"""


# Schema/migration DDL runs once per database per process. It used to run on
# every connect(), which made every request a WRITER: the no-op CREATEs still
# take the write lock, so while the launch chain (scan/combos/upload) held it,
# every read endpoint — including the /vault/status the Settings panel polls
# every 2s — queued behind work it didn't need. Under WAL, a connection that
# only reads never waits on writers; skipping the DDL is what makes reads
# actually read-only. Keyed by path because tests point DB_PATH elsewhere.
_initialized_paths = set()
_init_lock = threading.Lock()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    path = str(DB_PATH)
    if path not in _initialized_paths:
        with _init_lock:
            if path not in _initialized_paths:
                _init_schema(conn)
                _initialized_paths.add(path)
    return conn


def parse_for_index(path):
    """parse_slp for the background scan, run in the scan_pool worker.

    Returns (parsed, error) and never raises: an exception crossing the
    process boundary would be indistinguishable from the pool itself failing
    (see scan_pool), and the caller only ever stored the message.
    """
    try:
        parsed = parse_slp(path)
        # End-of-game state (stocks/percent) whenever the result can't be
        # trusted to placements: pre-3.13 files have none, and LRAS placements
        # are officially undefined — the state is the only honest way to score
        # those games.
        if parsed.get("placements") is None or parsed.get("end_method") == 7:
            parsed["final_state"] = read_final_state(
                path, parsed.get("last_frame"))
        return parsed, None
    except SlpParseError as e:
        return None, str(e)
    except Exception as e:  # never let one weird file kill the scan
        return None, f"unexpected: {type(e).__name__}: {e}"


def _init_schema(conn):
    # WAL is persistent in the file; setting it here (not per-connect) keeps
    # later connections from taking even the brief journal-mode check lock.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # migrations (executescript only CREATEs; new columns need ALTER)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(games)")}
    if "final_state" not in cols:
        conn.execute("ALTER TABLE games ADD COLUMN final_state TEXT")
        conn.commit()
    if "combos_at" not in cols:
        # mtime the combo pass last extracted this game at (NULL = never);
        # a mismatch with games.mtime marks the game stale for re-extraction
        conn.execute("ALTER TABLE games ADD COLUMN combos_at REAL")
        conn.commit()
    combo_cols = {r[1] for r in conn.execute("PRAGMA table_info(combos)")}
    if "start_rf" not in combo_cols:
        # Row-frame basis (meta.start_frame + bundle row index) for the
        # derived-bundle viewers: rollback netplay re-emits corrected frames
        # as extra rows, so true Slippi frames drift against the arrays the
        # viewers index (game_trace.py). start_frame/end_frame stay TRUE
        # frames for Dolphin seeking; uploads prefer these when present.
        # combos.py owns the re-extraction (kv "combos_frame_basis").
        conn.execute("ALTER TABLE combos ADD COLUMN start_rf INTEGER")
        conn.execute("ALTER TABLE combos ADD COLUMN end_rf INTEGER")
        conn.commit()
    if "true_combo" not in combo_cols:
        # 1 = victim never regained control between hits (true combo),
        # 0 = string, NULL = extracted before the flag existed. Un-stamp
        # combos_at so the next combo scan re-extracts everything with it.
        conn.execute("ALTER TABLE combos ADD COLUMN true_combo INTEGER")
        conn.execute("UPDATE games SET combos_at = NULL")
        conn.commit()


# ---------------------------------------------------------------------------
# kv helpers (user code overrides etc.)
# ---------------------------------------------------------------------------

def kv_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def kv_set(conn, key, value):
    conn.execute(
        "INSERT INTO kv(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)))
    conn.commit()


def kv_del(conn, key):
    conn.execute("DELETE FROM kv WHERE key=?", (key,))
    conn.commit()


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _upsert_game(conn, path, mtime, size, parsed, error=None):
    if parsed is None:
        row = (path, mtime, size, 0, error, None, None, None, None, None,
               None, None, None, None, None, None, None)
    else:
        row = (path, mtime, size, 1, None,
               parsed.get("start_at"), parsed.get("played_on"), parsed.get("version"),
               parsed.get("stage"), int(bool(parsed.get("is_teams"))),
               parsed.get("last_frame"), parsed.get("duration_s"),
               parsed.get("end_method"), parsed.get("lras_initiator"),
               json.dumps(parsed.get("placements")) if parsed.get("placements") is not None else None,
               json.dumps(parsed.get("final_state")) if parsed.get("final_state") else None,
               json.dumps(parsed.get("players")))
    conn.execute(
        """INSERT INTO games(path, mtime, size, parse_ok, parse_error, start_at,
               played_on, version, stage, is_teams, last_frame, duration_s,
               end_method, lras_initiator, placements, final_state, players)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET
               mtime=excluded.mtime, size=excluded.size,
               parse_ok=excluded.parse_ok, parse_error=excluded.parse_error,
               start_at=excluded.start_at, played_on=excluded.played_on,
               version=excluded.version, stage=excluded.stage,
               is_teams=excluded.is_teams, last_frame=excluded.last_frame,
               duration_s=excluded.duration_s, end_method=excluded.end_method,
               lras_initiator=excluded.lras_initiator,
               placements=excluded.placements,
               final_state=excluded.final_state, players=excluded.players""",
        row)
    # SQLite leaves lastrowid unchanged when the conflict branch updates an
    # existing row, so it may identify an unrelated game inserted earlier on
    # this connection. Resolve the row through the same unique key used by the
    # upsert before replacing its players.
    game_id = conn.execute(
        "SELECT id FROM games WHERE path=?", (path,)).fetchone()["id"]
    conn.execute("DELETE FROM game_players WHERE game_id=?", (game_id,))
    if parsed is not None:
        conn.executemany(
            "INSERT INTO game_players(game_id, port, type, character, costume, code, name) "
            "VALUES(?,?,?,?,?,?,?)",
            [(game_id, p["port"], p["type"], p.get("character"), p.get("costume"),
              # codes stored uppercase so lookups can hit idx_gp_code directly
              (p.get("code") or None) and p["code"].strip().upper(),
              p.get("name")) for p in parsed.get("players") or []])
    return game_id


# Cloud upload ledgers, keyed by game id. A file whose content changed at the
# same path keeps its id, so its old upload would still count as this
# content's and the new content would never upload (F-E-3).
_UPLOAD_LEDGERS = ("vault_objects", "vault_raw", "vault_raw_conv", "vault_raw_combos")


def _forget_uploads(conn, game_id):
    for table in _UPLOAD_LEDGERS:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone():
            conn.execute(f"DELETE FROM {table} WHERE game_id=?", (game_id,))


def _scan(job, replay_dir):
    # Inside the job, so a database that cannot open fails the scan instead
    # of leaving it running for the life of the backend (F-J-14).
    conn = connect()
    try:
        progress = PassProgress(job, "files", added=0, updated=0, removed=0, failed=0)
        known = {r["path"]: (r["mtime"], r["size"])
                 for r in conn.execute("SELECT path, mtime, size FROM games")}
        todo = []
        seen = set()
        traversal_errors = []
        def walk_error(error):
            traversal_errors.append(error)

        for root, _dirs, files in os.walk(replay_dir, onerror=walk_error):
            for fn in files:
                if not fn.lower().endswith(".slp"):
                    continue
                path = os.path.join(root, fn)
                seen.add(path)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                prior = known.get(path)
                if prior is None or prior != (st.st_mtime, st.st_size):
                    todo.append((path, st.st_mtime, st.st_size, prior is not None))

        # os.walk otherwise suppresses enumeration failures. An incomplete
        # traversal cannot prove that absent indexed paths were deleted.
        removed_paths = [] if traversal_errors else [p for p in known if p not in seen]
        warning = None
        if traversal_errors:
            first = traversal_errors[0]
            warning = (f"directory traversal incomplete: {first}"
                       + (f" (+{len(traversal_errors) - 1} more)"
                          if len(traversal_errors) > 1 else ""))
        progress.report(force=True, total=len(todo), removed=len(removed_paths))

        for chunk_start in range(0, len(removed_paths), 500):
            chunk = removed_paths[chunk_start:chunk_start + 500]
            conn.executemany("DELETE FROM games WHERE path=?", [(p,) for p in chunk])
        conn.commit()

        from . import scan_pool
        for i, (path, mtime, size, existed) in enumerate(todo):
            # parsing is the expensive part -- off-process, so indexing a big
            # replay folder cannot make the app unresponsive
            parsed, error = scan_pool.run(parse_for_index, path)
            game_id = _upsert_game(conn, path, mtime, size, parsed, error)
            if existed:
                _forget_uploads(conn, game_id)
            if error:
                progress.add(failed=1)
            else:
                progress.add(**{"updated" if existed else "added": 1})
            progress.report(done=i + 1)
            if (i + 1) % 200 == 0:
                conn.commit()
        conn.commit()
        progress.report(force=True)
        return {**progress.counts, "dir": replay_dir, "warning": warning}
    finally:
        conn.close()


def start_scan(replay_dir):
    """Start a background scan: its job id, or None while one is running."""
    try:
        return jobs.start(SCAN_KIND, lambda job: _scan(job, replay_dir),
                          params={"dir": replay_dir}, single=True,
                          thread_name="nucleome-replay-scan")
    except jobs.JobBusy:
        return None


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def index_counts(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(parse_ok) AS ok FROM games").fetchone()
    return {"indexed": row["n"] or 0, "parsed": row["ok"] or 0}


# A No-Contest game with tied stocks needs at least this percent gap before
# we call a winner — anything closer is a handwarmer/early quit, not a game.
LRAS_PERCENT_GAP = 25.0


def infer_result(user_port, placements, end_method, lras_initiator, final_state):
    """True=win, False=loss, None=undecidable, for a 2-player game.

    - GAME!/TIME! endings trust placements (verified: end-state inference
      agrees with placements on 100% of GAME! files), falling back to the
      recorded end-of-game state for pre-3.13 files.
    - No Contest (LRAS) NEVER trusts placements (slippi-js calls them
      undefined for this ending, and they contradict the game state in
      ~15% of files): more stocks wins; tied stocks needs a real percent
      deficit; a dead-even quit counts as no game at all. The old
      "quitter loses" convention poisoned long-running head-to-heads
      where one side habitually quit out.
    """
    if user_port is None:
        return None
    p = user_port - 1
    if end_method != 7 and placements and 0 <= p < len(placements):
        placement = placements[p]
        if placement == 0:
            return True
        if placement is not None and placement > 0:
            return False
    fs = final_state or {}
    mine = fs.get(str(user_port)) or fs.get(user_port)
    others = [v for k, v in fs.items() if int(k) != user_port]
    if mine and len(others) == 1:
        theirs = others[0]
        if mine["stocks"] != theirs["stocks"]:
            return mine["stocks"] > theirs["stocks"]
        gap = LRAS_PERCENT_GAP if end_method == 7 else 0.5
        if abs(mine["percent"] - theirs["percent"]) > gap:
            return mine["percent"] < theirs["percent"]
    return None


def _result_for(game, user_port):
    """Derive W/L ('win'/'loss'/None) for a parsed 2-player game row."""
    if user_port is None:
        return None
    placements = json.loads(game["placements"]) if game["placements"] else None
    final_state = json.loads(game["final_state"]) if game["final_state"] else None
    res = infer_result(user_port, placements, game["end_method"],
                       game["lras_initiator"], final_state)
    return None if res is None else ("win" if res else "loss")


def _build_filter(codes, my_char, opp_char, stage, opponent, month=None, teams=None):
    """Shared FROM + WHERE + params for the browser list and its month
    buckets, so both honour identical filters. Returns (from_sql, where_sql,
    params). `teams` (0/1) filters singles vs doubles; the win/loss `result`
    filter is applied in Python (it depends on the final-state inference).

    Codes are stored uppercase, so all code predicates hit idx_gp_code — the
    identity CROSS JOIN drives the plan down to the user's own games instead
    of scanning the whole corpus (the UPPER()-wrapped version took 80s+).
    """
    where = ["g.parse_ok = 1", f"g.stage IN ({_STAGE_MARKS})", _NO_MODDED_CHARS]
    params = []
    from_sql = "games g"
    if codes:
        marks = ",".join("?" for _ in codes)
        from_sql = "game_players me CROSS JOIN games g ON g.id = me.game_id"
        where.insert(0, f"me.code IN ({marks})")
        params.extend(codes)
        if my_char is not None:
            where.append("me.character = ?")
            params.append(my_char)
        opp_conds = ["op.game_id = g.id", "op.port != me.port"]
        opp_params = []
        if opp_char is not None:
            opp_conds.append("op.character = ?")
            opp_params.append(opp_char)
        if opponent:
            opp_conds.append("(op.code LIKE ? OR op.name LIKE ?)")
            needle = f"%{opponent.upper()}%"
            opp_params.extend([needle, f"%{opponent}%"])
        if len(opp_conds) > 2:
            where.append("EXISTS (SELECT 1 FROM game_players op WHERE "
                         + " AND ".join(opp_conds) + ")")
            params.extend(opp_params)
    else:
        # no identity: my_char/opp_char both match any slot
        for ch in (my_char, opp_char):
            if ch is not None:
                where.append(
                    "EXISTS (SELECT 1 FROM game_players x WHERE x.game_id=g.id AND x.character=?)")
                params.append(ch)
        if opponent:
            where.append(
                "EXISTS (SELECT 1 FROM game_players x WHERE x.game_id=g.id AND "
                "(x.code LIKE ? OR x.name LIKE ?))")
            params.extend([f"%{opponent.upper()}%", f"%{opponent}%"])
    if stage is not None:
        where.append("g.stage=?")
        params.append(stage)
    if teams is not None:
        where.append("g.is_teams=?")
        params.append(int(teams))
    if month:
        where.append("substr(g.start_at, 1, 7) = ?")
        params.append(month)
    return from_sql, " AND ".join(where), params


def _iter_results(conn, codes, from_sql, where_sql, params):
    """Yield (game_row, players, user_port, result) for the filtered set,
    newest first — the shared scan used when the win/loss filter is active
    (result depends on final-state inference, so it can't live in SQL)."""
    code_set = set(codes)
    rows = conn.execute(
        f"SELECT g.* FROM {from_sql} WHERE {where_sql} "
        f"ORDER BY g.start_at DESC, g.id DESC", params).fetchall()
    for g in rows:
        players = json.loads(g["players"]) if g["players"] else []
        user_port = next(
            (p["port"] for p in players
             if (p.get("code") or "").upper() in code_set), None)
        res = _result_for(g, user_port) if len(players) == 2 else None
        yield g, players, user_port, res


def query_month_buckets(conn, user_codes, my_char=None, opp_char=None,
                        stage=None, opponent=None, result=None, teams=None):
    """[{ym: 'YYYY-MM', count: N}] newest first, honouring the same filters
    as query_games — the collapsible month sections in the browser."""
    codes = [c.upper() for c in user_codes if c]
    from_sql, where_sql, params = _build_filter(
        codes, my_char, opp_char, stage, opponent, teams=teams)
    if result:
        # win/loss counts need per-game inference; group in Python
        counts = {}
        for g, _players, _up, res in _iter_results(conn, codes, from_sql, where_sql, params):
            if res == result and g["start_at"]:
                ym = g["start_at"][:7]
                counts[ym] = counts.get(ym, 0) + 1
        return [{"ym": ym, "count": counts[ym]} for ym in sorted(counts, reverse=True)]
    rows = conn.execute(
        f"SELECT substr(g.start_at, 1, 7) AS ym, COUNT(*) AS n "
        f"FROM {from_sql} WHERE {where_sql} AND g.start_at IS NOT NULL "
        f"GROUP BY ym ORDER BY ym DESC", params).fetchall()
    return [{"ym": r["ym"], "count": r["n"]} for r in rows]


def _game_dict(g, players, user_port, res):
    return {
        "id": g["id"],
        "path": g["path"],
        "start_at": g["start_at"],
        "stage": g["stage"],
        "is_teams": bool(g["is_teams"]),
        "duration_s": g["duration_s"],
        # last Slippi frame (game starts at -123) — the full-game playlist end
        "last_frame": g["last_frame"],
        "players": players,
        "user_port": user_port,
        "result": res,
    }


def query_games(conn, user_codes, my_char=None, opp_char=None, stage=None,
                opponent=None, month=None, result=None, teams=None,
                limit=50, offset=0):
    """Filterable game list, newest first. `user_codes` identifies "me".
    `month` ('YYYY-MM') restricts to one month's games; `result` (win/loss)
    and `teams` (0/1) narrow further."""
    codes = [c.upper() for c in user_codes if c]
    from_sql, where_sql, params = _build_filter(
        codes, my_char, opp_char, stage, opponent, month, teams)

    if result:
        # win/loss can't be a SQL predicate (final-state inference) — filter
        # the month's rows in Python, then page. A month is bounded (hundreds).
        matched = [(_game_dict(g, players, up, res))
                   for g, players, up, res
                   in _iter_results(conn, codes, from_sql, where_sql, params)
                   if res == result]
        return {"total": len(matched), "games": matched[offset:offset + limit]}

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM {from_sql} WHERE {where_sql}",
        params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT g.* FROM {from_sql} WHERE {where_sql} "
        f"ORDER BY g.start_at DESC, g.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]).fetchall()

    code_set = set(codes)
    games = []
    for g in rows:
        players = json.loads(g["players"]) if g["players"] else []
        user_port = next(
            (p["port"] for p in players
             if (p.get("code") or "").upper() in code_set), None)
        games.append(_game_dict(
            g, players, user_port,
            _result_for(g, user_port) if len(players) == 2 else None))
    return {"total": total, "games": games}


def alias_summary(conn, user_codes):
    """All (code, name) pairs seen for the user's codes + top opponent codes."""
    codes = [c.upper() for c in user_codes if c]
    aliases = []
    if codes:
        marks = ",".join("?" for _ in codes)
        aliases = [dict(r) for r in conn.execute(
            f"SELECT code, name, COUNT(*) AS games FROM game_players "
            f"WHERE code IN ({marks}) AND name IS NOT NULL "
            f"GROUP BY code, name ORDER BY games DESC LIMIT 25", codes)]
    top_codes = [dict(r) for r in conn.execute(
        "SELECT code, COUNT(*) AS games FROM game_players "
        "WHERE code IS NOT NULL GROUP BY code ORDER BY games DESC LIMIT 8")]
    return {"aliases": aliases, "top_codes": top_codes}


def codes_for_account_names(conn, names, exclude_codes=()):
    """Codes whose in-game netplay name exactly matches a Slippi launcher
    account name — the launcher only stores the ACTIVE account's connect code
    on disk, but replays played on the other accounts carry both the name and
    the code, so this recovers 'Player' -> ABCD#123 style matches."""
    exclude = {c.upper() for c in exclude_codes}
    out = []
    for name in names:
        if not name:
            continue
        for r in conn.execute(
                "SELECT code, COUNT(*) AS games FROM game_players "
                "WHERE name = ? AND code IS NOT NULL "
                "GROUP BY code ORDER BY games DESC LIMIT 3", (name,)):
            if r["code"] not in exclude:
                out.append({"account": name, "code": r["code"], "games": r["games"]})
    out.sort(key=lambda s: -s["games"])
    return out


def filter_facets(conn, user_codes):
    """Distinct characters/stages with counts, for the filter dropdowns."""
    codes = [c.upper() for c in user_codes if c]
    facets = {"my_characters": [], "opp_characters": [], "stages": []}
    if codes:
        marks = ",".join("?" for _ in codes)
        facets["my_characters"] = [dict(r) for r in conn.execute(
            f"SELECT character, COUNT(*) AS games FROM game_players "
            f"WHERE code IN ({marks}) AND character IN ({_CHAR_MARKS}) "
            f"GROUP BY character ORDER BY games DESC", codes)]
        facets["opp_characters"] = [dict(r) for r in conn.execute(
            f"SELECT gp.character, COUNT(*) AS games FROM game_players gp "
            f"JOIN game_players me ON me.game_id = gp.game_id AND me.code IN ({marks}) "
            f"WHERE gp.port != me.port AND gp.character IN ({_CHAR_MARKS}) "
            f"GROUP BY gp.character ORDER BY games DESC", codes)]
    else:
        facets["my_characters"] = [dict(r) for r in conn.execute(
            f"SELECT character, COUNT(*) AS games FROM game_players "
            f"WHERE character IN ({_CHAR_MARKS}) GROUP BY character ORDER BY games DESC")]
        facets["opp_characters"] = facets["my_characters"]
    facets["stages"] = [dict(r) for r in conn.execute(
        f"SELECT stage, COUNT(*) AS games FROM games "
        f"WHERE parse_ok=1 AND stage IN ({_STAGE_MARKS}) "
        f"GROUP BY stage ORDER BY games DESC")]
    return facets
