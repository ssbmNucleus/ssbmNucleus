"""Deep stats: frame-mine the USER'S OWN replays, per character, in-app.

The bundled baseline packs (baselines/<tier>/<Char>.json) are population
yardsticks; this module produces the player's own measurements to hold
against them — for ANY character they play, not just their main. Rows are
stored per game in nucleome.db (deep_rows), so mining is incremental: the
first pass over a character costs ~0.2s/game in a background thread, then
only new replays are pending. Bump ANALYZER_VERSION when analyzer.py's stat
definitions change and everything re-mines lazily.

Entry points:
  start_mining(character?)  a ``deep_stats`` job (core/jobs.py, one at a
                            time); character None = all my games
  active_mining()           the running job's record, or None
  char_status(conn, char)   {mined, pending, total} for one character
  build_player_pack(char)   aggregate mined rows -> a pack shaped like the
                            baseline packs (+ oos_mix), for Stats panel + coach

Used by tracker/routes/stats.py (/api/nucleome/deep/*) and the
coach tools (my_deep_stats / start_deep_analysis).
"""
import json
import logging
import os
import time

from core import jobs
from ..store import identity, indexer
from ..store.pass_progress import PassProgress
from ..store.indexer import _NO_MODDED_CHARS, _STAGE_MARKS

logger = logging.getLogger(__name__)

# v4: canonical move-name fix (ATTACK_NAMES was shifted one down across ids
# 1-20 — "uair" was really bair, "neutral-B" really dair, shine was unmapped).
# Numbers identical to v3; only labels changed. Bumping forces a lazy re-mine
# so stored rows carry correct names.
ANALYZER_VERSION = 4

# external char id -> analyzer row name (mirrors analyzer.CHAR_NAMES)
from .analyzer import CHAR_NAMES as _AN_CHAR_NAMES  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS deep_rows (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    character INTEGER NOT NULL,
    analyzer_version INTEGER NOT NULL,
    start_at TEXT,
    row TEXT NOT NULL,
    replay_mtime REAL,
    replay_size INTEGER,
    perspective_code TEXT,
    status TEXT NOT NULL DEFAULT 'complete'
);
CREATE INDEX IF NOT EXISTS idx_deep_char ON deep_rows(character, analyzer_version);
"""


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(deep_rows)")}
    for name, decl in (
            ("replay_mtime", "REAL"), ("replay_size", "INTEGER"),
            ("perspective_code", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'complete'")):
        if name not in cols:
            conn.execute(f"ALTER TABLE deep_rows ADD COLUMN {name} {decl}")


def _user_codes(conn):
    return [c.upper() for c in identity.known_user_codes(conn) if c]


def _candidates(conn, character=None, only_unmined=True):
    """My parsed 2p vanilla singles vs humans (same scope as the Stats page),
    optionally one character, optionally only games not yet deep-mined."""
    codes = _user_codes(conn)
    if not codes:
        return []
    marks = ",".join("?" for _ in codes)
    where = [
        f"me.code IN ({marks})",
        "g.parse_ok = 1",
        "g.is_teams = 0",
        f"g.stage IN ({_STAGE_MARKS})",
        _NO_MODDED_CHARS,
        "op.type = 0",
        "(SELECT COUNT(*) FROM game_players x WHERE x.game_id = g.id) = 2",
    ]
    params = list(codes)
    if character is not None:
        where.append("me.character = ?")
        params.append(character)
    if only_unmined:
        where.append("""NOT EXISTS (
            SELECT 1 FROM deep_rows d
             WHERE d.game_id = g.id AND d.analyzer_version = ?
               AND d.status = 'complete'
               AND d.replay_mtime = g.mtime AND d.replay_size = g.size
               AND d.perspective_code = me.code)""")
        params.append(ANALYZER_VERSION)
    rows = conn.execute(
        f"""SELECT g.id, g.path, g.start_at, g.mtime, g.size,
                   me.port AS my_port, me.character AS my_char, me.code AS my_code
            FROM game_players me CROSS JOIN games g ON g.id = me.game_id
            JOIN game_players op ON op.game_id = g.id AND op.port != me.port
            WHERE {' AND '.join(where)}
            ORDER BY g.start_at, g.id""", params).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    return out


DEFAULT_SECS_PER_GAME = 0.2   # seed estimate until this machine measures itself


def secs_per_game(conn):
    """Measured per-game mining rate on THIS machine (updated after every
    completed job of 25+ games), falling back to the seed estimate."""
    try:
        v = float(indexer.kv_get(conn, "deep_mine_secs_per_game"))
        if 0.005 < v < 30:
            return v
    except (TypeError, ValueError):
        pass
    return DEFAULT_SECS_PER_GAME


def char_status(conn, character):
    """{mined, pending, total} deep-mining coverage for one character."""
    ensure_schema(conn)
    total = len(_candidates(conn, character=character, only_unmined=False))
    pending = len(_candidates(conn, character=character, only_unmined=True))
    return {"mined": total - pending, "pending": pending, "total": total}


# ---------------------------------------------------------------------------
# background mining job (one at a time; a job like the combo scan's)
# ---------------------------------------------------------------------------

MINE_KIND = "deep_stats"
jobs.register_kind(MINE_KIND, label="Deep stats", keep=5)


def active_mining():
    """The running mining job's record, or None."""
    job = jobs.active_job(MINE_KIND)
    return job.snapshot() if job is not None else None


def _mine(job, character):
    from .analyzer import analyze_game
    started = time.time()
    # Inside the job: a database that cannot open fails the job.
    conn = indexer.connect()
    try:
        progress = PassProgress(job, "games", failed=0)
        ensure_schema(conn)
        todo = _candidates(conn, character=character, only_unmined=True)
        progress.report(force=True, total=len(todo))
        for i, g in enumerate(todo):
            try:
                if os.path.exists(g["path"]):
                    rows = analyze_game(g["path"])
                    # game_players.port is the 1-based slippi port — match on
                    # the row's slp_port, never on the ports-array index
                    mine = next((r for r in rows
                                 if r["slp_port"] == g["my_port"]), None)
                else:
                    mine = None
                if mine is None:
                    # gone/short/unparseable: stamp an empty row so it never
                    # re-queues (pack assembly skips empty rows)
                    conn.execute(
                        """INSERT OR REPLACE INTO deep_rows
                           (game_id, character, analyzer_version, start_at, row,
                            replay_mtime, replay_size, perspective_code, status)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (g["id"], g["my_char"], ANALYZER_VERSION,
                         g["start_at"], "{}", g["mtime"], g["size"],
                         g["my_code"], "failed"))
                    progress.add(failed=1)
                else:
                    conn.execute(
                        """INSERT OR REPLACE INTO deep_rows
                           (game_id, character, analyzer_version, start_at, row,
                            replay_mtime, replay_size, perspective_code, status)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (g["id"], g["my_char"], ANALYZER_VERSION,
                         g["start_at"], json.dumps(mine), g["mtime"], g["size"],
                         g["my_code"], "complete"))
            except BaseException as e:
                # incl. pyo3 PanicException from peppi (BaseException-derived,
                # not importable, so matched by name); anything else re-raises
                if not isinstance(e, Exception) and type(e).__name__ != "PanicException":
                    raise
                logger.exception("deep-mine failed for %s", g["path"])
                conn.execute(
                    """INSERT OR REPLACE INTO deep_rows
                       (game_id, character, analyzer_version, start_at, row,
                        replay_mtime, replay_size, perspective_code, status)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (g["id"], g["my_char"], ANALYZER_VERSION, g["start_at"],
                     "{}", g["mtime"], g["size"], g["my_code"], "failed"))
                progress.add(failed=1)
            progress.report(done=i + 1)
            if (i + 1) % 25 == 0:
                conn.commit()
        conn.commit()
        progress.report(force=True)
        # record the measured rate so future ETAs reflect THIS machine
        done = progress.counts["done"]
        if done >= 25:
            rate = (time.time() - started) / done
            indexer.kv_set(conn, "deep_mine_secs_per_game", round(rate, 4))
            conn.commit()
        return dict(progress.counts)
    finally:
        conn.close()


def start_mining(character=None):
    """Kick off deep mining for one character (or all my games).
    Returns {"started": True, "job_id"} or {"started": False, "reason", "job"?}."""
    try:
        import peppi_py  # noqa: F401
    except ImportError:
        return {"started": False,
                "reason": "peppi-py is not available in this build"}
    try:
        job_id = jobs.start(MINE_KIND, lambda job: _mine(job, character),
                            params={"character": character}, single=True,
                            thread_name="nucleome-deep-mine")
    except jobs.JobBusy:
        return {"started": False, "reason": "a mining job is already running",
                "job": active_mining()}
    return {"started": True, "job_id": job_id}


# ---------------------------------------------------------------------------
# pack assembly (same math as build_packs_v2, over the player's rows)
# ---------------------------------------------------------------------------

MIN_SIT_EVENTS = 75
SITUATION_FIELDS = {"out_of_shieldstun": "oos", "ledge": "ledge",
                    "tech": "tech_opt", "knockdown": "knockdown"}


def _load_char_rows(conn, character):
    ensure_schema(conn)
    codes = _user_codes(conn)
    if not codes:
        return []
    marks = ",".join("?" for _ in codes)
    out = []
    for r in conn.execute(
            f"""SELECT d.start_at, d.row FROM deep_rows d
                 JOIN games g ON g.id=d.game_id
                WHERE d.character=? AND d.analyzer_version=?
                  AND d.status='complete' AND d.replay_mtime=g.mtime
                  AND d.replay_size=g.size
                  AND d.perspective_code IN ({marks})
                ORDER BY d.start_at""",
            (character, ANALYZER_VERSION, *codes)):
        try:
            row = json.loads(r["row"])
        except json.JSONDecodeError:
            continue
        if row:
            row["startAt"] = r["start_at"]
            out.append(row)
    return out


def build_player_pack(character, since=None, until=None, last_n=None):
    """Aggregate the player's mined rows for one character into a pack the
    same shape as the baseline packs (+ recent split + oos_mix), or None if
    nothing is mined (or nothing falls in the window). `character` is the
    external char id.

    Windowing (any combination): `since`/`until` are ISO date prefixes
    ("2020", "2020-10", "2020-10-05") compared against each game's start
    time; `last_n` keeps the most recent N games after date filtering. A
    windowed pack carries a `window` block describing the slice. There is
    deliberately NO built-in "recent" split — the caller picks windows
    (user rule 2026-07-14: no magic window sizes).
    """
    from . import pack_math
    conn = indexer.connect()
    try:
        rows = _load_char_rows(conn, character)
        status = char_status(conn, character)
    finally:
        conn.close()
    windowed = bool(since or until or last_n)
    if since:
        rows = [r for r in rows if (r.get("startAt") or "") >= str(since)]
    if until:
        u = str(until)
        rows = [r for r in rows if (r.get("startAt") or "")[:len(u)] <= u]
    if last_n:
        rows = rows[-max(1, int(last_n)):]
    if not rows:
        return None
    char_name = _AN_CHAR_NAMES.get(character, f"ext{character}")
    pack = pack_math.build_pack(rows, "player", char_name)
    if windowed:
        pack["window"] = {"since": since, "until": until, "last_n": last_n,
                          "first_game": rows[0].get("startAt"),
                          "last_game": rows[-1].get("startAt")}
    pack["situations"] = {}
    for sit, field in SITUATION_FIELDS.items():
        per_mu = {}
        for r in rows:
            for e in r.get(field) or []:
                per_mu.setdefault(r.get("vs"), []).append(tuple(e))
        tables = {mu: {"situation": sit, "matchup": mu,
                       **pack_math.oos_table(evs)}
                  for mu, evs in per_mu.items()
                  if mu and len(evs) >= MIN_SIT_EVENTS}
        if tables:
            pack["situations"][sit] = tables
    pack["coverage"] = status
    return pack
