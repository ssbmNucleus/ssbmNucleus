"""Tier-1 stats over the nucleome replay index — pure metadata math.

Everything here is computed from the games/game_players tables the indexer
already fills (characters, stages, opponents, dates, placements, LRAS): no
frame data, no AI. One call returns every section the Stats tab renders;
the same payload is what the coach will eventually read as context, so keep
it JSON-plain.

Scope rules (mirrors the Replays browser): parsed 2-player singles on
vanilla stages with vanilla characters, human opponents only. W/L comes
from indexer.infer_result (placements for real endings, end-of-game state
for old files and quits); undecidable games stay in the totals but out of
winrates.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime

from ..store.indexer import _STAGE_MARKS, _NO_MODDED_CHARS, infer_result

# a gap this long between game starts = a new play session
SESSION_GAP_S = 45 * 60


def _parse_dt(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _result(row):
    """True=win, False=loss, None=undecidable — indexer.infer_result over
    the row's JSON columns."""
    placements = json.loads(row["placements"]) if row["placements"] else None
    # Normal endings usually have decisive placements. Avoid parsing the much
    # larger final-state JSON unless the shared result rules need the fallback.
    result = infer_result(row["my_port"], placements, row["end_method"],
                          row["lras_initiator"], None)
    if result is not None:
        return result
    final_state = json.loads(row["final_state"]) if row["final_state"] else None
    return infer_result(row["my_port"], placements, row["end_method"],
                        row["lras_initiator"], final_state)


def _wl(wins, losses):
    decided = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / decided, 4) if decided else None,
    }


def _fetch_rows(conn, user_codes, my_char=None, start=None, end=None):
    """One row per (game, opponent) for the user's 2p vanilla singles vs
    humans, oldest first. Drives from idx_gp_code via CROSS JOIN — never
    let SQLite plan this from the games table (83s vs 0.2s on 20k games).

    start/end are inclusive YYYY-MM-DD day bounds, compared as string
    prefixes of start_at — the same local-date idiom as the browser's
    month filter (indexer._build_filter)."""
    codes = [c.upper() for c in user_codes if c]
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
    if my_char is not None:
        where.append("me.character = ?")
        params.append(my_char)
    if start:
        where.append("substr(g.start_at, 1, 10) >= ?")
        params.append(start)
    if end:
        where.append("substr(g.start_at, 1, 10) <= ?")
        params.append(end)
    rows = conn.execute(
        f"""SELECT g.id, g.start_at, g.stage, g.duration_s, g.end_method,
                   g.lras_initiator, g.placements, g.final_state,
                   me.port AS my_port, me.character AS my_char,
                   op.character AS opp_char, op.code AS opp_code,
                   op.name AS opp_name
            FROM game_players me CROSS JOIN games g ON g.id = me.game_id
            JOIN game_players op ON op.game_id = g.id AND op.port != me.port
            WHERE {' AND '.join(where)}
            ORDER BY g.start_at, g.id""",
        params).fetchall()
    # a game where BOTH codes are the user's (played yourself) matches twice —
    # keep the first perspective only
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    return out


def compute_stats(conn, user_codes, my_char=None, start=None, end=None):
    rows = _fetch_rows(conn, user_codes, my_char=my_char, start=start, end=end)

    overview = {"games": len(rows), "playtime_s": 0.0,
                "first_at": None, "last_at": None}
    wins = losses = 0
    my_quits = opp_quits = 0
    by_my_char = defaultdict(lambda: [0, 0, 0])       # char -> [games, w, l]
    by_matchup = defaultdict(lambda: [0, 0, 0])       # opp char -> [games, w, l]
    by_stage = defaultdict(lambda: [0, 0, 0])         # stage -> [games, w, l]
    by_month = defaultdict(lambda: [0, 0, 0])         # (year, month) -> [games, w, l]
    heat = defaultdict(lambda: [0, 0, 0])             # (weekday, hour) -> [g,w,l]
    rivals = {}                                       # opp code -> dict
    days = set()

    timed = []  # (datetime, result) for session analysis
    for r in rows:
        res = _result(r)
        if res is True:
            wins += 1
        elif res is False:
            losses += 1
        if r["duration_s"]:
            overview["playtime_s"] += r["duration_s"]

        quit_by_me = (r["end_method"] == 7 and r["lras_initiator"] is not None
                      and r["lras_initiator"] == r["my_port"] - 1)
        quit_by_opp = (r["end_method"] == 7 and r["lras_initiator"] is not None
                       and r["lras_initiator"] != r["my_port"] - 1)
        my_quits += quit_by_me
        opp_quits += quit_by_opp

        for agg, key in ((by_my_char, r["my_char"]),
                         (by_matchup, r["opp_char"]),
                         (by_stage, r["stage"])):
            agg[key][0] += 1
            if res is True:
                agg[key][1] += 1
            elif res is False:
                agg[key][2] += 1

        dt = _parse_dt(r["start_at"])
        if dt is not None:
            timed.append((dt, res))
            days.add(dt.date().isoformat())
            if overview["first_at"] is None:
                overview["first_at"] = r["start_at"]
            overview["last_at"] = r["start_at"]
            month = by_month[(dt.year, dt.month)]
            month[0] += 1
            if res is True:
                month[1] += 1
            elif res is False:
                month[2] += 1

            # time-of-day heatmap in the machine's LOCAL time (this is the
            # user's own desktop, so astimezone() = their wall clock)
            local = dt.astimezone()
            cell = heat[(local.weekday(), local.hour)]  # weekday: Mon=0..Sun=6
            cell[0] += 1
            if res is True:
                cell[1] += 1
            elif res is False:
                cell[2] += 1

        code = r["opp_code"]
        if code:
            riv = rivals.get(code)
            if riv is None:
                riv = rivals[code] = {
                    "code": code, "name": None, "games": 0, "wins": 0,
                    "losses": 0, "chars": Counter(), "last_at": None,
                    "opp_quits": 0, "my_quits": 0}
            riv["games"] += 1
            if res is True:
                riv["wins"] += 1
            elif res is False:
                riv["losses"] += 1
            if r["opp_name"]:
                riv["name"] = r["opp_name"]  # rows are oldest-first: keeps latest
            if r["opp_char"] is not None:
                riv["chars"][r["opp_char"]] += 1
            riv["last_at"] = r["start_at"] or riv["last_at"]
            riv["opp_quits"] += quit_by_opp  # they rage-quit on me
            riv["my_quits"] += quit_by_me    # I quit against them

    overview.update(_wl(wins, losses))
    overview["playtime_s"] = round(overview["playtime_s"])
    overview["opponents"] = len(rivals)
    overview["active_days"] = len(days)

    def _table(agg, key_name):
        out = []
        for key, (n, w, l) in agg.items():
            out.append({key_name: key, "games": n, **_wl(w, l)})
        out.sort(key=lambda e: -e["games"])
        return out

    # ── sessions: split the timeline on 45-minute gaps ──
    sessions = []
    for dt, res in timed:  # already oldest-first
        if not sessions or (dt - sessions[-1][-1][0]).total_seconds() > SESSION_GAP_S:
            sessions.append([])
        sessions[-1].append((dt, res))
    # winrate at each exact game-number-within-session ("do I tilt?") —
    # no buckets; the UI fades thin-sample positions instead of cutting
    pos_stats = defaultdict(lambda: [0, 0, 0])
    for sess in sessions:
        for i, (_dt, res) in enumerate(sess, start=1):
            b = pos_stats[i]
            b[0] += 1
            if res is True:
                b[1] += 1
            elif res is False:
                b[2] += 1
    lengths = sorted(len(s) for s in sessions)
    session_summary = {
        "count": len(sessions),
        "avg_games": round(sum(lengths) / len(lengths), 1) if lengths else None,
        "median_games": lengths[len(lengths) // 2] if lengths else None,
        "longest": lengths[-1] if lengths else 0,
        "by_position": [
            {"position": i, "games": n, **_wl(w, l)}
            for i, (n, w, l) in sorted(pos_stats.items())],
        # exact histogram (sessions of length N) — the UI draws the full
        # distribution, no arbitrary buckets
        "length_distribution": [
            {"games": n, "sessions": c}
            for n, c in sorted(Counter(lengths).items())],
    }

    # top_char for every opponent (before the rivals loop mutates chars)
    for riv in rivals.values():
        top = riv["chars"].most_common(1)
        riv["top_char"] = top[0][0] if top else None

    def _salt_list(quit_key):
        rows = []
        for r in rivals.values():
            q = r[quit_key]
            if q < 1:
                continue
            rows.append({
                "code": r["code"], "name": r["name"], "top_char": r["top_char"],
                "quits": q, "games": r["games"],
                # both directions travel with every row so the tooltip can
                # show the full picture regardless of which list it's in
                "opp_quits": r["opp_quits"], "my_quits": r["my_quits"],
                **_wl(r["wins"], r["losses"]),
            })
        # most quits first; ties broken by how few games it took to earn them
        rows.sort(key=lambda e: (-e["quits"], e["games"]))
        return rows[:100]

    # everyone you've played at least a set against — the UI paginates
    rival_list = sorted((r for r in rivals.values() if r["games"] >= 5),
                        key=lambda r: -r["games"])[:500]
    for riv in rival_list:
        riv.update(_wl(riv["wins"], riv["losses"]))
        riv.pop("chars", None)

    return {
        "filters": {"my_char": my_char},
        "overview": overview,
        "my_characters": _table(by_my_char, "character"),
        "matchups": _table(by_matchup, "character"),
        "stages": _table(by_stage, "stage"),
        "months": sorted(
            ({"month": datetime(year, month, 1).strftime("%Y-%m"), "games": n, **_wl(w, l)}
             for (year, month), (n, w, l) in by_month.items()),
            key=lambda e: e["month"]),
        "sessions": session_summary,
        # weekday×hour play/win heatmap (only non-empty cells; UI fills grid)
        "time_heatmap": [
            {"d": d, "h": h, "games": n, **_wl(w, l)}
            for (d, h), (n, w, l) in sorted(heat.items())],
        "rivals": rival_list,
        "salt": {
            "my_quits": my_quits,
            "opp_quits": opp_quits,
            # opponents who rage-quit on YOU the most
            "saltiest": _salt_list("opp_quits"),
            # opponents YOU rage-quit against the most
            "ragebaiters": _salt_list("my_quits"),
        },
    }
