# The combo state machine in this module is a port of slippi-js
# (https://github.com/project-slippi/slippi-js), Copyright (c) Project Slippi,
# licensed under the GNU Lesser General Public License v3.0. The ported
# portions remain under the LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0.html);
# the rest of SSBM Nucleus is GPL-3.0 (see LICENSE at the repository root).
"""Combo extraction for the nucleOME Combos tab.

Walks each replay's raw Post-Frame events (dependency-free, same style as
slp_meta) and runs a port of slippi-js's combo state machine over them:

  - a combo OPENS when the opponent enters a damage/grabbed state,
  - it EXTENDS while they stay damaged, teching, downed, or dying — with a
    45-frame grace window (Timers.COMBO_STRING_RESET_FRAMES) once they're
    actionable again,
  - each percent increase is attributed to a MOVE via the attacker's
    "last attack landed" id; consecutive hits inside one un-interrupted
    attack animation count as multi-hits of the same move,
  - it KILLS if the opponent loses a stock before the window closes,
  - it is a TRUE combo (vs a string) if the victim never regained control
    between hits: every frame from the first hit to the last was spent
    damaged, grabbed, thrown, teching, downed, or dying. Hits that land
    inside the 45-frame grace window after the victim became actionable
    mark the whole conversion as a string. Tech chases stay "true".

Both directions of every 1v1 game are computed (your combos AND combos done
to you). Results are stored in the `combos` table with denormalized
character/stage/code columns so the browser can filter and sort without
joins. Extraction is a separate ``combo_scan`` job (frame data means
reading whole files — a large corpus takes a while on the first pass), and
is incremental: games are re-extracted only when the file's mtime no longer
matches games.combos_at.
"""
import json
import logging
import os
import struct

from core import jobs
from ..store.pass_progress import PassProgress
from ..store.slp_meta import (HEADER, RAW_START, CMD_POST_FRAME,
                       _parse_payload_sizes, SlpParseError)

logger = logging.getLogger(__name__)

# Post-Frame Update offsets, payload-relative (spec offset minus the command
# byte). PERCENT/STOCKS match slp_meta's constants.
PF_FRAME = 0x0        # s32
PF_PORT = 0x4         # u8
PF_FOLLOWER = 0x5     # u8 (Nana)
PF_STATE = 0x7        # u16 action state id
PF_PERCENT = 0x15     # f32
PF_LAST_ATTACK = 0x1D  # u8 "last attack landed" (slippi move id)
PF_STOCKS = 0x20      # u8
MIN_PF_SIZE = PF_STOCKS + 1  # oldest usable payload (every 0.1+ file has this)

_i32 = struct.Struct(">i")
_u16 = struct.Struct(">H")
_f32 = struct.Struct(">f")

# slippi-js Timers.COMBO_STRING_RESET_FRAMES
COMBO_RESET_FRAMES = 45


# --- action-state predicates (slippi-js melee/actions.ts ranges) -----------

def _is_damaged(s):
    return (0x4B <= s <= 0x5B) or s == 0x26  # DamageHi..FlyRoll, DamageFall


def _is_grabbed(s):
    return 0xDF <= s <= 0xE8  # CapturePulledHi..CaptureFoot


def _is_command_grabbed(s):
    # command grabs (Kirby swallow, DK cargo, ...) minus BarrelWait
    return ((0x10A <= s <= 0x113) or (0x11A <= s <= 0x125)) and s != 0x125


def _is_thrown(s):
    return 0xEF <= s <= 0xF3  # ThrownF..ThrownLwWomen


def _is_teching(s):
    return 0xC7 <= s <= 0xCC


def _is_downed(s):
    return 0xB7 <= s <= 0xC6


def _is_dying(s):
    return s <= 0x0A


# ---------------------------------------------------------------------------
# Frame ingestion
# ---------------------------------------------------------------------------

def _read_post_frames(path):
    """{frame: {port_idx: (state, percent, last_attack, stocks)}} for leader
    players. Rollback re-writes of a frame overwrite the earlier values (last
    wins, matching slippi-js)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(4096)
        if not head.startswith(HEADER):
            raise SlpParseError("not a slp file (bad header)")
        raw_len = struct.unpack(">i", head[len(HEADER):len(HEADER) + 4])[0]
        if raw_len <= 0:
            # unfinished file: locate the metadata footer like parse_slp
            f.seek(max(0, size - 65536))
            tail = f.read()
            idx = tail.rfind(b"U\x08metadata{")
            if idx < 0:
                raise SlpParseError("raw length 0 and no metadata footer")
            raw_len = (max(0, size - 65536) + idx) - RAW_START
        sizes, gs_off = _parse_payload_sizes(head)
        pf_size = sizes.get(CMD_POST_FRAME)
        if not pf_size or pf_size < MIN_PF_SIZE:
            raise SlpParseError("post-frame payload too small")
        f.seek(0)
        data = f.read(min(RAW_START + raw_len, size))

    frames = {}
    # Row map: {frame: {port: row_index}}, row_index = how many post-frames
    # this port had emitted BEFORE this one — i.e. this event's index in the
    # port's array as peppi builds it. Rollback re-emissions are extra rows
    # there (game_trace.py:105), so index != frame - start; the LAST
    # occurrence wins here exactly like the value dict above, which is also
    # the row a viewer of the derived bundle visually lands on.
    rows = {}
    counts = [0, 0, 0, 0]
    pos, end = gs_off, len(data)
    while pos < end:
        cmd = data[pos]
        sz = sizes.get(cmd)
        if sz is None:
            break  # unknown event = can't safely skip; keep what we have
        if cmd == CMD_POST_FRAME and pos + 1 + sz <= end:
            base = pos + 1
            if not data[base + PF_FOLLOWER]:  # ignore Nana
                frame = _i32.unpack_from(data, base + PF_FRAME)[0]
                port = data[base + PF_PORT]
                if port < 4:
                    frames.setdefault(frame, {})[port] = (
                        _u16.unpack_from(data, base + PF_STATE)[0],
                        _f32.unpack_from(data, base + PF_PERCENT)[0],
                        data[base + PF_LAST_ATTACK],
                        data[base + PF_STOCKS],
                    )
                    rows.setdefault(frame, {})[port] = counts[port]
                    counts[port] += 1
        pos += 1 + sz
    return frames, rows


# ---------------------------------------------------------------------------
# Combo detection
# ---------------------------------------------------------------------------

def _finalize(combo, end_frame):
    combo["end_frame"] = end_frame
    combo["damage"] = round(combo["end_percent"] - combo["start_percent"], 1)
    return combo


def _detect_direction(order, frames, att, dfn):
    """Combos BY port-index `att` ON port-index `dfn` (0-based)."""
    combos = []
    combo = None
    move = None
    last_hit_anim = None
    reset = 0
    free_streak = 0  # consecutive frames the victim was fully actionable
    prev = {}  # port -> last-seen tuple
    last_frame_seen = None

    for f in order:
        cur = frames[f]
        if att not in cur or dfn not in cur:
            for p, v in cur.items():
                prev[p] = v
            continue
        opp_state, opp_pct, _oa, opp_stocks = cur[dfn]
        ply_state, _pp, ply_attack, _ps = cur[att]
        popp = prev.get(dfn)
        last_frame_seen = f

        damaged = (_is_damaged(opp_state) or _is_grabbed(opp_state)
                   or _is_command_grabbed(opp_state))
        if damaged:
            if combo is None:
                combo = {
                    "start_frame": f,
                    "start_percent": round(popp[1] if popp else opp_pct, 1),
                    "end_percent": opp_pct,
                    "moves": [],
                    "did_kill": False,
                    "true_combo": True,
                }
                move = None
                last_hit_anim = None
                reset = 0
            dmg = (opp_pct - popp[1]) if popp else 0.0
            if dmg > 0:
                # a follow-up that lands after the victim had actionable
                # frames is a string, not a true combo (free_streak still
                # holds the count through the previous frame here)
                if combo["moves"] and free_streak > 0:
                    combo["true_combo"] = False
                if last_hit_anim is None or move is None:
                    move = {"frame": f, "move_id": ply_attack,
                            "hits": 0, "damage": 0.0}
                    combo["moves"].append(move)
                move["hits"] += 1
                move["damage"] = round(move["damage"] + dmg, 1)
                last_hit_anim = ply_state

        if combo is not None:
            # percent only rises inside a combo; max() shields against the
            # respawn reset to 0 on the kill frame
            combo["end_percent"] = max(combo["end_percent"], opp_pct)
            lost_stock = popp is not None and opp_stocks < popp[3]
            active = not (damaged or _is_teching(opp_state)
                          or _is_downed(opp_state) or _is_dying(opp_state))
            reset = reset + 1 if active else 0
            if lost_stock:
                combo["did_kill"] = True
            if lost_stock or reset > COMBO_RESET_FRAMES:
                if combo["moves"]:
                    combos.append(_finalize(combo, f))
                combo = None
                move = None
                last_hit_anim = None

        # control tracker for true-combo classification: thrown / teching /
        # downed states hold the victim just like hitstun does, so tech
        # chases and throw links don't count as regained control
        held = (damaged or _is_thrown(opp_state) or _is_teching(opp_state)
                or _is_downed(opp_state) or _is_dying(opp_state))
        free_streak = 0 if held else free_streak + 1

        # leaving the attack animation closes the multi-hit window: the next
        # damage event starts a new move
        if ply_state != last_hit_anim:
            last_hit_anim = None

        for p, v in cur.items():
            prev[p] = v

    if combo is not None and combo["moves"] and last_frame_seen is not None:
        combos.append(_finalize(combo, last_frame_seen))
    # Every "move" carries the attacker's last-landed-attack id; move_id 0 means
    # the attacker never actually hit. A "combo" whose moves are ALL move_id 0 is
    # damage from something other than the opponent — a stage hazard (Corneria
    # Arwing lasers, Onett cars, ...) that the state machine wrongly credits as a
    # combo. Require at least one real move so hazards aren't mined as combos.
    return [c for c in combos
            if c["damage"] > 0 and any(m["move_id"] for m in c["moves"])]


def extract_combos(path, ports):
    """All combos in one 1v1 replay, both directions. `ports` = the two
    1-based ports from GameStart. Returns [{port, opp_port, start_frame,
    end_frame, start_percent, end_percent, damage, moves: [...], did_kill}]."""
    frames, rows = _read_post_frames(path)
    order = sorted(frames)
    a, b = ports[0] - 1, ports[1] - 1
    first = order[0] if order else -123
    out = []
    for att, dfn in ((a, b), (b, a)):
        for c in _detect_direction(order, frames, att, dfn):
            c["port"] = att + 1
            c["opp_port"] = dfn + 1
            # Row-frame basis for the derived-bundle viewers (mobile, share
            # pages, Watch Lite): first_frame + row_index. start/end_frame stay
            # TRUE Slippi frames — Dolphin playback seeks by those. On a clean
            # local replay the two are identical; on rollback netplay the
            # row basis absorbs the re-emission drift the viewers suffer from.
            pr = rows.get(c["start_frame"], {}).get(att)
            er = rows.get(c["end_frame"], {}).get(att)
            c["start_rf"] = (first + pr) if pr is not None else None
            c["end_rf"] = (first + er) if er is not None else None
            out.append(c)
    out.sort(key=lambda c: c["start_frame"])
    return out


# ---------------------------------------------------------------------------
# Scanning (user-triggered, incremental)
# ---------------------------------------------------------------------------

# A pass is a job (core/jobs.py), in memory like the replay scan's.
SCAN_KIND = "combo_scan"
jobs.register_kind(SCAN_KIND, label="Combo scan", keep=5)


def _candidate_where():
    """Shared eligibility for scanning and the pending count."""
    from ..store.indexer import _STAGE_MARKS, _NO_MODDED_CHARS
    return f"""g.parse_ok = 1 AND IFNULL(g.is_teams, 0) = 0
              AND g.stage IN ({_STAGE_MARKS})
              AND (SELECT COUNT(*) FROM game_players gp
                   WHERE gp.game_id = g.id) = 2
              AND {_NO_MODDED_CHARS}
              AND (g.combos_at IS NULL OR g.combos_at != g.mtime)"""


def _candidates(conn):
    """Parsed vanilla singles whose file changed since the last extraction."""
    return conn.execute(
        f"""SELECT g.id, g.path, g.mtime, g.stage, g.start_at, g.players
            FROM games g WHERE {_candidate_where()}"""
    ).fetchall()


def _store_game_combos(conn, game, combos):
    """Replace one game's combo rows (delete + insert) and stamp combos_at."""
    players = {p["port"]: p for p in json.loads(game["players"] or "[]")}
    conn.execute("DELETE FROM combos WHERE game_id=?", (game["id"],))
    rows = []
    for c in combos:
        me = players.get(c["port"]) or {}
        opp = players.get(c["opp_port"]) or {}
        moves = c["moves"]
        rows.append((
            game["id"], c["port"], c["opp_port"],
            (me.get("code") or None) and me["code"].strip().upper(),
            (opp.get("code") or None) and opp["code"].strip().upper(),
            me.get("name"), opp.get("name"),
            me.get("character"), opp.get("character"),
            game["stage"], game["start_at"],
            c["start_frame"], c["end_frame"],
            c["start_percent"], round(c["end_percent"], 1), c["damage"],
            len(moves), sum(m["hits"] for m in moves),
            int(c["did_kill"]), int(c["true_combo"]),
            moves[0]["move_id"], moves[-1]["move_id"],
            json.dumps(moves),
            c.get("start_rf"), c.get("end_rf"),
        ))
    conn.executemany(
        """INSERT INTO combos(game_id, port, opp_port, code, opp_code, name,
               opp_name, character, opp_character, stage, start_at,
               start_frame, end_frame, start_percent, end_percent, damage,
               moves, hits, did_kill, true_combo, opening_move, ending_move,
               moves_json, start_rf, end_rf)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.execute("UPDATE games SET combos_at=? WHERE id=?",
                 (game["mtime"], game["id"]))
    return len(rows)


def extract_for_scan(path, ports):
    """extract_combos for the background pass, run in the scan_pool worker.

    Returns (combos, error) and never raises: an exception crossing the
    process boundary would be indistinguishable from the pool itself failing
    (see scan_pool). The caller only ever counted these as "failed" anyway.
    """
    try:
        return extract_combos(path, ports), None
    except (SlpParseError, OSError, struct.error) as e:
        return None, f"{type(e).__name__}: {e}"
    except Exception as e:                                    # noqa: BLE001
        # never let one weird file kill the scan
        return None, f"unexpected: {type(e).__name__}: {e}"


_FRAME_BASIS = "row-v1"


def _ensure_frame_basis(conn):
    """One-shot migration: combos extracted before start_rf/end_rf existed
    must be re-extracted, or uploads keep feeding viewers the drifting true
    frames. Resetting combos_at re-queues every game for the incremental
    pass; the kv marker makes it exactly once."""
    from ..store import indexer
    if indexer.kv_get(conn, "combos_frame_basis") == _FRAME_BASIS:
        return
    conn.execute("UPDATE games SET combos_at = NULL")
    indexer.kv_set(conn, "combos_frame_basis", _FRAME_BASIS)
    conn.commit()


def _scan(job):
    from ..store import indexer, scan_pool
    # Inside the job: a database that cannot open fails the pass.
    conn = indexer.connect()

    def stamp(game):
        """Mark the game done so we don't retry it every pass (the next
        replay scan prunes rows whose file is gone)."""
        conn.execute("UPDATE games SET combos_at=? WHERE id=?",
                     (game["mtime"], game["id"]))

    try:
        progress = PassProgress(job, "games", found=0, failed=0)
        _ensure_frame_basis(conn)
        todo = _candidates(conn)
        progress.report(force=True, total=len(todo))
        for i, game in enumerate(todo):
            try:
                if not os.path.exists(game["path"]):
                    stamp(game)
                else:
                    ports = [p["port"] for p in json.loads(game["players"] or "[]")]
                    # the frame walk is the expensive part -- off-process, so
                    # a full re-extraction cannot make the app unresponsive
                    extracted, error = scan_pool.run(
                        extract_for_scan, game["path"], ports)
                    if error:
                        logger.debug("combos: %s: %s", game["path"], error)
                        stamp(game)
                        progress.add(failed=1)
                    else:
                        _store_game_combos(conn, game, extracted)
                        progress.add(found=sum(len(c["moves"]) >= 4 for c in extracted))
            except Exception:  # never let one weird row kill the scan
                stamp(game)
                progress.add(failed=1)
            progress.report(done=i + 1)
            if (i + 1) % 50 == 0:
                conn.commit()
        conn.commit()
        progress.report(force=True)
        return dict(progress.counts)
    finally:
        conn.close()


def start_scan():
    """Start a background combo extraction: its job id, or None while one runs."""
    try:
        return jobs.start(SCAN_KIND, _scan, single=True,
                          thread_name="nucleome-combo-scan")
    except jobs.JobBusy:
        return None


def counts(conn):
    """Index totals for the Combos tab header / empty state."""
    combos_n = conn.execute("SELECT COUNT(*) AS n FROM combos WHERE moves >= 4").fetchone()["n"]
    scanned = conn.execute(
        "SELECT COUNT(*) AS n FROM games WHERE combos_at IS NOT NULL"
    ).fetchone()["n"]
    pending = conn.execute(
        f"SELECT COUNT(*) AS n FROM games g WHERE {_candidate_where()}"
    ).fetchone()["n"]
    return {"combos": combos_n, "games_scanned": scanned,
            "games_pending": pending}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

# The sortable column per key; direction is chosen by the caller (asc/desc) so
# the UI can toggle any metric either way. DEFAULT_DIR is what a sort button
# lands on the first time it's picked (the "natural" direction for that metric).
SORT_FIELDS = {
    "recent": "c.start_at",
    "damage": "c.damage",
    "moves": "c.moves",
    "start_percent": "c.start_percent",
    "duration": "(c.end_frame - c.start_frame)",
}
SORT_DEFAULT_DIR = {
    "recent": "desc", "damage": "desc", "moves": "desc",
    "start_percent": "asc", "duration": "desc",
}
# stable total order (id is unique) so pagination never repeats/skips rows;
# game_id/start_frame keep a game's combos in play order within a tie
_SORT_TIEBREAK = "c.game_id DESC, c.start_frame ASC, c.id ASC"


def _order_by(sort, direction):
    field = SORT_FIELDS.get(sort) or SORT_FIELDS["recent"]
    d = (direction or SORT_DEFAULT_DIR.get(sort, "desc")).lower()
    d = "ASC" if d == "asc" else "DESC"
    return f"{field} {d}, {_SORT_TIEBREAK}"


def query_combos(conn, user_codes, mine=None, char=None, opp_char=None,
                 stage=None, opponent=None, min_moves=None, min_damage=None,
                 kills=None, min_start=None, max_start=None, kind=None,
                 date_from=None, date_to=None,
                 sort="recent", direction=None, limit=50, offset=0):
    """Filterable combo list. `char`/`opp_char` are attacker/victim external
    ids. `mine` = 'me' (my combos) or 'vs' (combos done to me), resolved
    through the user's claimed codes. `kind` = 'true' (hitstun/tech-chase
    the whole way) or 'string' (victim regained control between hits); rows
    extracted before the flag existed match neither until re-analyzed.
    `date_from`/`date_to` are ISO date prefixes compared against start_at
    (lexicographic — '2024-01' style prefixes work)."""
    codes = [c.upper() for c in user_codes if c]
    where, params = [], []
    if mine == "me" and codes:
        marks = ",".join("?" for _ in codes)
        where.append(f"c.code IN ({marks})")
        params.extend(codes)
    elif mine == "vs" and codes:
        marks = ",".join("?" for _ in codes)
        where.append(f"c.opp_code IN ({marks})")
        params.extend(codes)
    if char is not None:
        where.append("c.character = ?")
        params.append(char)
    if opp_char is not None:
        where.append("c.opp_character = ?")
        params.append(opp_char)
    if stage is not None:
        where.append("c.stage = ?")
        params.append(stage)
    if opponent:
        # search the non-user side: in 'vs' mode the other person is the
        # attacker (c.code/name), otherwise they're the victim (c.opp_*)
        if mine == "vs":
            where.append("(c.code LIKE ? OR c.name LIKE ?)")
        else:
            where.append("(c.opp_code LIKE ? OR c.opp_name LIKE ?)")
        params.extend([f"%{opponent.upper()}%", f"%{opponent}%"])
    if min_moves is not None:
        where.append("c.moves >= ?")
        params.append(min_moves)
    if min_damage is not None:
        where.append("c.damage >= ?")
        params.append(min_damage)
    if kills:
        where.append("c.did_kill = 1")
    if kind == "true":
        where.append("c.true_combo = 1")
    elif kind == "string":
        where.append("c.true_combo = 0")
    if min_start is not None:
        where.append("c.start_percent >= ?")
        params.append(min_start)
    if max_start is not None:
        where.append("c.start_percent <= ?")
        params.append(max_start)
    if date_from:
        where.append("c.start_at >= ?")
        params.append(date_from)
    if date_to:
        # bump the prefix (append U+FFFF) so '2024-06-30' includes that whole day
        where.append("c.start_at < ?")
        params.append(date_to + chr(0xFFFF))
    where_sql = " AND ".join(where) if where else "1=1"
    order_sql = _order_by(sort, direction)

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM combos c WHERE {where_sql}",
        params).fetchone()["n"]
    rows = conn.execute(
        f"""WITH page AS (
                SELECT c.id FROM combos c JOIN games g ON g.id = c.game_id
                WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?
            )
            SELECT c.*, g.path AS game_path, g.players AS game_players,
                   g.duration_s AS game_duration
            FROM page JOIN combos c ON c.id = page.id
                JOIN games g ON g.id = c.game_id
            ORDER BY {order_sql}""",
        params + [limit, offset]).fetchall()

    combos = []
    for r in rows:
        combos.append({
            "id": r["id"],
            "port": r["port"],
            "opp_port": r["opp_port"],
            "character": r["character"],
            "opp_character": r["opp_character"],
            "name": r["name"],
            "opp_name": r["opp_name"],
            "code": r["code"],
            "opp_code": r["opp_code"],
            "stage": r["stage"],
            "start_at": r["start_at"],
            "start_frame": r["start_frame"],
            "end_frame": r["end_frame"],
            "start_percent": r["start_percent"],
            "end_percent": r["end_percent"],
            "damage": r["damage"],
            "moves": r["moves"],
            "hits": r["hits"],
            "did_kill": bool(r["did_kill"]),
            "true_combo": (None if r["true_combo"] is None
                           else bool(r["true_combo"])),
            "opening_move": r["opening_move"],
            "ending_move": r["ending_move"],
            "moves_list": json.loads(r["moves_json"] or "[]"),
            "game": {
                "id": r["game_id"],
                "path": r["game_path"],
                "stage": r["stage"],
                "start_at": r["start_at"],
                "players": json.loads(r["game_players"] or "[]"),
                "duration_s": r["game_duration"],
            },
        })
    return {"total": total, "combos": combos}


if __name__ == "__main__":
    import sys
    from ..store.slp_meta import parse_slp
    meta = parse_slp(sys.argv[1])
    found = extract_combos(sys.argv[1], [p["port"] for p in meta["players"]])
    print(json.dumps(found, indent=2))
    print(f"{len(found)} combos")
