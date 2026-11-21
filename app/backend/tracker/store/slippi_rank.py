"""Slippi ranked profiles by connect code, with a local cache.

Fetches ratingOrdinal / wins / losses from the public Slippi GraphQL gateway
(the same endpoint slippi.gg and the community rank tools use) and maps the
ordinal to a display tier. Results cache in the index DB's kv store for
CACHE_TTL_S so browsing replays doesn't hammer the API — a page of rows costs
at most a handful of fetches, once a day per code.
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone

import requests

from . import indexer

logger = logging.getLogger(__name__)

GQL_URL = "https://internal.slippi.gg/graphql"
CACHE_TTL_S = 24 * 3600
_FETCH_TIMEOUT_S = 6

# NB: the gateway's old `getConnectCode(code:)` field is gone (400s);
# `getUser(connectCode:)` is the current shape.
_QUERY = """
query ConnectCodeRank($cc: String!) {
  getUser(connectCode: $cc) {
    displayName
    rankedNetplayProfile {
      ratingOrdinal
      ratingUpdateCount
      wins
      losses
      dailyGlobalPlacement
      dailyRegionalPlacement
    }
  }
}
"""

# ordinal -> tier (Slippi's published thresholds)
_TIERS = [
    (765.43, "Bronze 1"), (913.72, "Bronze 2"), (1054.87, "Bronze 3"),
    (1188.88, "Silver 1"), (1315.75, "Silver 2"), (1435.48, "Silver 3"),
    (1548.07, "Gold 1"), (1653.52, "Gold 2"), (1751.83, "Gold 3"),
    (1843.0, "Plat 1"), (1927.03, "Plat 2"), (2003.92, "Plat 3"),
    (2073.67, "Diamond 1"), (2136.28, "Diamond 2"), (2191.75, "Diamond 3"),
    (2274.99, "Master 1"), (2350.0, "Master 2"),
]

_inflight_lock = threading.Lock()


def tier_for(rating, update_count, global_placement=None):
    # Slippi marks an account "Pending" until 5 placement games this season;
    # we hide Pending in the UI (a provisional rating isn't a real rank yet).
    if rating is None or not update_count or update_count < 5:
        return "Pending"
    if rating >= 2191.75 and global_placement:
        return "Grandmaster"
    for cutoff, name in _TIERS:
        if rating < cutoff:
            return name
    return "Master 3"


def _fetch_one(code):
    resp = requests.post(GQL_URL, json={
        "operationName": "ConnectCodeRank",
        "variables": {"cc": code},
        "query": _QUERY,
    }, timeout=_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    user = (resp.json().get("data") or {}).get("getUser")
    if not user:
        return {"exists": False}
    prof = user.get("rankedNetplayProfile") or {}
    rating = prof.get("ratingOrdinal")
    count = prof.get("ratingUpdateCount") or 0
    if rating is None:
        return {"exists": True, "ranked": False}
    return {
        "exists": True,
        "ranked": True,
        "rating": round(float(rating), 1),
        "tier": tier_for(float(rating), count, prof.get("dailyGlobalPlacement")),
        "wins": prof.get("wins") or 0,
        "losses": prof.get("losses") or 0,
    }


# ---------------------------------------------------------------------------
# Local rank-over-time sampling. Slippi only exposes each past season's FINAL
# rating, so intra-season history has to be recorded by us: every fresh fetch
# of one of the USER'S codes appends a timestamped sample (skipped while the
# rating hasn't moved, so an idle week costs zero rows). The Stats tab charts
# season finals as backfill + these samples from install day onward.
# ---------------------------------------------------------------------------

def _my_codes(conn):
    codes = list(indexer.kv_get(conn, "seen_login_codes") or [])
    for c in indexer.kv_get(conn, "user_codes") or []:
        if c not in codes:
            codes.append(c)
    return {c.upper() for c in codes}


def _record_sample(conn, code, rating, tier, wins, losses):
    last = conn.execute(
        "SELECT rating, wins, losses FROM rank_samples WHERE code=? "
        "ORDER BY at DESC LIMIT 1", (code,)).fetchone()
    if last is not None and abs(last["rating"] - rating) < 0.05 \
            and last["wins"] == wins and last["losses"] == losses:
        return
    conn.execute(
        "INSERT INTO rank_samples(code, at, rating, tier, wins, losses) "
        "VALUES(?,?,?,?,?,?)",
        (code, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         rating, tier, wins, losses))
    conn.commit()


def _maybe_sample(conn, code, rank):
    """Called on every fresh (non-cache) fetch: sample the user's own codes."""
    if not rank.get("ranked") or rank.get("rating") is None:
        return
    if code in _my_codes(conn):
        _record_sample(conn, code, rank["rating"], rank.get("tier"),
                       rank.get("wins") or 0, rank.get("losses") or 0)


def get_rank_samples(conn, codes):
    """{code: [{at, rating, tier, wins, losses}]} — locally recorded samples."""
    out = {}
    for code in {c.strip().upper() for c in codes if c}:
        out[code] = [dict(r) for r in conn.execute(
            "SELECT at, rating, tier, wins, losses FROM rank_samples "
            "WHERE code=? ORDER BY at", (code,))]
    return out


# Past seasons carry each season's FINAL rating — one real data point per
# season per code, the only rank history Slippi exposes publicly.
_HISTORY_QUERY = """
query ConnectCodeRankHistory($cc: String!) {
  getUser(connectCode: $cc) {
    displayName
    rankedNetplayProfile {
      ratingOrdinal
      ratingUpdateCount
      wins
      losses
      dailyGlobalPlacement
    }
    rankedNetplayProfileHistory {
      ratingOrdinal
      wins
      losses
      season { name startedAt endedAt }
    }
  }
}
"""


def _fetch_history(code):
    resp = requests.post(GQL_URL, json={
        "operationName": "ConnectCodeRankHistory",
        "variables": {"cc": code},
        "query": _HISTORY_QUERY,
    }, timeout=_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    user = (resp.json().get("data") or {}).get("getUser")
    if not user:
        return {"exists": False, "seasons": []}
    seasons = []
    for entry in user.get("rankedNetplayProfileHistory") or []:
        rating = entry.get("ratingOrdinal")
        wins = entry.get("wins") or 0
        losses = entry.get("losses") or 0
        season = entry.get("season") or {}
        # an unplayed season still returns a row with the default rating —
        # only seasons with actual sets are history
        if rating is None or wins + losses == 0:
            continue
        seasons.append({
            "name": season.get("name"),
            "started_at": season.get("startedAt"),
            "ended_at": season.get("endedAt"),
            "rating": round(float(rating), 1),
            "tier": tier_for(float(rating), wins + losses),
            "wins": wins,
            "losses": losses,
        })
    seasons.sort(key=lambda s: s["started_at"] or "")
    out = {"exists": True, "seasons": seasons, "current": None}
    prof = user.get("rankedNetplayProfile") or {}
    rating = prof.get("ratingOrdinal")
    if rating is not None and (prof.get("wins") or prof.get("losses")):
        out["current"] = {
            "rating": round(float(rating), 1),
            "tier": tier_for(float(rating), prof.get("ratingUpdateCount") or 0,
                             prof.get("dailyGlobalPlacement")),
            "wins": prof.get("wins") or 0,
            "losses": prof.get("losses") or 0,
        }
    return out


def get_rank_history(codes):
    """{code: {seasons: [...], current: {...}}} for each connect code, from
    the same kv cache/TTL discipline as get_ranks."""
    out = {}
    misses = []
    conn = indexer.connect()
    try:
        now = time.time()
        for code in {c.strip().upper() for c in codes if c and "#" in c}:
            cached = indexer.kv_get(conn, f"rank_history:{code}")
            if cached and now - cached.get("at", 0) < CACHE_TTL_S:
                out[code] = cached["history"]
            else:
                misses.append(code)
        with _inflight_lock:
            for code in misses:
                try:
                    history = _fetch_history(code)
                    ttl_at = now
                except Exception as e:  # noqa: BLE001 — offline/API down
                    logger.info(f"rank history fetch failed for {code}: {e}")
                    history = {"exists": None, "seasons": [], "current": None}
                    ttl_at = now - CACHE_TTL_S + 600  # retry in ~10 min
                indexer.kv_set(conn, f"rank_history:{code}",
                               {"at": ttl_at, "history": history})
                if history.get("current"):
                    _maybe_sample(conn, code, {"ranked": True, **history["current"]})
                out[code] = history
        # our own recorded intra-season points ride along with each code
        for code, samples in get_rank_samples(conn, list(out)).items():
            out[code]["samples"] = samples
    finally:
        conn.close()
    return out


def _cached_rank(conn, code):
    """The cached rank for `code` while it is fresh, else None."""
    cached = indexer.kv_get(conn, f"rank:{code}")
    if cached and time.time() - cached.get("at", 0) < CACHE_TTL_S:
        return cached["rank"]
    return None


def get_ranks(codes):
    """{code: rank-info} for each requested connect code (uppercased).
    Serves from cache when fresh; fetch failures cache briefly as unknown so
    an offline session doesn't retry per keystroke."""
    out = {}
    misses = []
    conn = indexer.connect()
    try:
        now = time.time()
        for code in {c.strip().upper() for c in codes if c and "#" in c}:
            cached = _cached_rank(conn, code)
            if cached is not None:
                out[code] = cached
            else:
                misses.append(code)
        if not misses:
            # all cached: never queue behind another caller's fetches
            return out
        # Serialize fetches (one caller at a time) to stay polite to the API.
        # A caller that waited here usually wanted the codes the one ahead of
        # it just fetched (overlapping requests for the same page of rows), so
        # each code is re-checked under the lock instead of fetched again.
        with _inflight_lock:
            for code in misses:
                cached = _cached_rank(conn, code)
                if cached is not None:
                    out[code] = cached
                    continue
                try:
                    rank = _fetch_one(code)
                    ttl_at = now
                except Exception as e:  # noqa: BLE001 — offline/API down
                    logger.info(f"rank fetch failed for {code}: {e}")
                    rank = {"exists": None}
                    ttl_at = now - CACHE_TTL_S + 600  # retry in ~10 min
                indexer.kv_set(conn, f"rank:{code}", {"at": ttl_at, "rank": rank})
                _maybe_sample(conn, code, rank)
                out[code] = rank
    finally:
        conn.close()
    return out
