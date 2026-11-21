"""vault_client — transport between the desktop and the cloud vault.

vault_sync knows how to derive and track; this knows how to talk. It supplies
the mint_urls / put / commit callables that vault_sync.push() takes, so the
sync logic stays testable without a network and no credential ever reaches it.

Auth is the Patreon app token (or a paired device token), resolved server-side
by the vault-* edge functions. The Supabase anon key below is a publishable key
-- the viewer already ships it in services/account.js -- which is precisely why
the vault tables enable RLS with no policies: anyone can hold this key, and the
only thing standing between it and every patron's library is that PostgREST has
no policy to let it through.
"""
import hashlib
import json
import logging
import copy
import re
import threading
import time
from collections import OrderedDict
from datetime import date
import urllib.error
import urllib.request

from ..store import indexer
from . import vault_raw, vault_sync

logger = logging.getLogger(__name__)

SUPABASE_URL = "https://nttxcjrnqccogsibeqzz.supabase.co"
# Publishable, same value the viewer embeds. Not a secret.
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im50"
    "dHhjanJucWNjb2dzaWJlcXp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAyMDY3NTYsImV4"
    "cCI6MjA3NTc4Mjc1Nn0.5EJaMlem2rASzuttx1_PtwGd2cuyAOtM8VJmwwiEudo"
)

FN_SYNC = f"{SUPABASE_URL}/functions/v1/vault-sync"
FN_READ = f"{SUPABASE_URL}/functions/v1/vault-read"
FN_PUBLIC = f"{SUPABASE_URL}/functions/v1/vault-public"

# Where minted share ids resolve. /replay/<id> is served by a Cloudflare
# Worker in front of this hostname, not by the website repo.
SHARE_SITE = "https://ssbmnucleus.net"

# Games per mint (the edge function's MAX_BATCH is 100, deployed and in the
# repo). The pending upload limiter counts MINTS per 10 minutes, so games per
# mint is what sets the ceiling a fast sync runs into -- at 50 a sync would be
# held to 1,000 games / 10 min; at 100, twice that. Commits still go in
# COMMIT_CHUNK slices: a commit carries every combo of its games, and a fat
# one is what blew the Postgres statement timeout on a full refresh.
BATCH = 100
COMMIT_CHUNK = 50

# Upload throughput (bug: a 44k-game library at ~1.1 s/game = ~15 h).
# Measured 2026-09-21 on the push pipeline with the prod edge-function
# latencies: derive was ~65% of wall time and ran one game at a time; the
# PUTs were strictly sequential and each paid a fresh TCP+TLS handshake
# (~83 ms of a ~180 ms PUT from here). The server is not the bottleneck:
# mint ~0.35 s + commit ~0.7 s per 50-game batch (~2% of the old wall time).
#
# Derive workers are a temporary burst (see scan_pool.burst): out of process,
# one priority class below the backend, gone when the sync ends. Half the
# cores, capped at 4 so a sync never walks off with the machine -- each child
# is a spawn re-import of the backend (a few hundred MB).
import os as _os
DERIVE_WORKERS = max(1, min(4, (_os.cpu_count() or 2) // 2))
# Concurrent PUTs per batch. R2 has no per-client limit anywhere near this,
# and each PUT is ~35-75 KB, so this is about hiding latency, not bandwidth.
PUT_WORKERS = 6

# Opt-in local setting. A failed capability probe suppresses raw attempts for
# a day, including after a restart; frames sync remains available throughout.
RAW_UPLOAD_KEY = "vault_raw_upload"
RAW_RETRY_AFTER_KEY = "vault_raw_retry_after"
RAW_RETRY_S = 24 * 60 * 60

# The "me" code list as this machine and the vault last agreed on it
# (sync_codes). Account-derived: a sign-in to another account clears it.
CODES_BASE_KEY = "vault_codes_base"
# Codes removed here while there is no agreed list yet (note_codes_edit).
CODES_REMOVED_KEY = "vault_codes_removed"


class VaultError(RuntimeError):
    pass


class RawUploadsUnsupported(VaultError, vault_raw.RawUploadError):
    """The server has not proved that mint URLs point to raw replay objects."""


class ConversionsUnsupported(VaultError, vault_raw.RawUploadError):
    """The server has not proved that mint URLs point to conversion objects."""


def _call(url, payload, timeout=120):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise VaultError(f"{url.rsplit('/', 1)[-1]}: HTTP {e.code} "
                         f"{e.read()[:300].decode('utf-8', 'replace')}") from e
    except OSError as e:
        # Offline, DNS, refused, timed out (URLError and TimeoutError are both
        # OSErrors). Still the remote's verdict, so callers see a VaultError
        # and the routes answer 502 instead of crashing with a 500.
        raise VaultError(f"{url.rsplit('/', 1)[-1]}: unreachable "
                         f"({getattr(e, 'reason', e)})") from e
    # A dead token comes back in-band with 200 so a client can drop it rather
    # than treat it as an outage -- the convention ai-entitlement uses.
    if isinstance(out, dict) and out.get("error"):
        raise VaultError(str(out["error"]))
    return out


_put_local = threading.local()


def _put_conn(scheme, host, timeout):
    """This thread's keep-alive connection to `host` (one per PUT worker)."""
    import http.client
    conns = getattr(_put_local, "conns", None)
    if conns is None:
        conns = _put_local.conns = {}
    key = (scheme, host)
    c = conns.get(key)
    if c is None:
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        c = conns[key] = cls(host, timeout=timeout)
    return c


def _drop_put_conn(scheme, host):
    conns = getattr(_put_local, "conns", None) or {}
    c = conns.pop((scheme, host), None)
    if c is not None:
        try:
            c.close()
        except Exception:                                     # noqa: BLE001
            pass


def _put(url, body, timeout=300):
    """PUT over a reused per-thread connection; see _put_once for the proof.

    Reusing the connection skips the TCP+TLS handshake that was ~half of every
    PUT. A kept-alive socket the server has since closed fails on first use,
    so a connection-level error gets ONE retry on a fresh connection -- safe
    because the object key is the content hash (a repeated PUT is the same
    write). A configured proxy keeps the old urllib path, which honours it.
    """
    from urllib.parse import urlsplit
    if urllib.request.getproxies().get(urlsplit(url).scheme):
        return _put_urllib(url, body, timeout)
    import http.client
    parts = urlsplit(url)
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    for attempt in (0, 1):
        conn = _put_conn(parts.scheme, parts.netloc, timeout)
        try:
            conn.request("PUT", target, body=body, headers={
                "Content-Type": "application/gzip",
                "Content-Length": str(len(body)),
            })
            r = conn.getresponse()
            data = r.read()
        except (http.client.HTTPException, OSError):
            _drop_put_conn(parts.scheme, parts.netloc)
            if attempt:
                raise
            continue
        if r.will_close:
            _drop_put_conn(parts.scheme, parts.netloc)
        if r.status not in (200, 201):
            raise VaultError(f"PUT returned {r.status}: {data[:200]!r}")
        _check_etag(r.getheader("ETag"), body)
        return


def _check_etag(etag, body):
    etag = (etag or "").strip('"').lower()
    expect = hashlib.md5(body).hexdigest()
    if etag and etag != expect:
        raise VaultError(f"PUT etag mismatch: got {etag}, expected {expect}")
    if not etag:
        raise VaultError("PUT returned no ETag; cannot confirm the write")


def _put_urllib(url, body, timeout=300):
    """Upload one object and prove it landed.

    A 200 is not proof. During the first live sync one PUT of five returned 200
    while the object never appeared in the bucket, and because nothing checked,
    the row was committed and the game looked synced -- a phone would have hit a
    404 much later with no way to trace it back. R2 sets ETag to the MD5 of a
    non-multipart body, so comparing it costs nothing and turns a silent failure
    into a retryable error at the point it happens.
    """
    req = urllib.request.Request(url, data=body, method="PUT",
                                 headers={"Content-Type": "application/gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status not in (200, 201):
            raise VaultError(f"PUT returned {r.status}")
        etag = r.headers.get("ETag")
    _check_etag(etag, body)


# --- local metadata -------------------------------------------------------

def _user_codes(conn):
    """Uppercased "me" codes, resolved once per sync run — identity work
    (reading launcher config + kv) is not something to repeat per game."""
    from ..store import identity
    return {c.upper() for c in identity.user_codes(conn) if c}


def _commit_games(token, games, on_skip=None):
    """Commit a batch of game rows, halving it whenever the database gives up.

    Returns the content hashes whose metadata was committed. A singleton that
    still times out is omitted and reported through ``on_skip``.

    A commit carries every combo for every game in the batch, and a handful of
    long games can put tens of thousands of rows in one statement — enough for
    Postgres to cancel it. That killed a full metadata refresh at 5,500 games:
    one oversized batch, and the whole run raised. Halving turns that into a
    couple of extra round trips, and a single game that still times out is
    reported and stepped over rather than ending the pass.
    """
    try:
        _call(FN_SYNC, {"action": "commit", "token": token, "games": games})
        return [g["content_hash"] for g in games]
    except VaultError as e:
        if "timeout" not in str(e).lower():
            raise
        if len(games) == 1:
            if on_skip:
                on_skip(games[0].get("content_hash"), str(e))
            return []
        mid = len(games) // 2
        return (_commit_games(token, games[:mid], on_skip)
                + _commit_games(token, games[mid:], on_skip))


def _codes_for_sync(conn, token):
    """The codes to stamp games with, reconciled with the vault first so a
    code ticked on the phone counts here too. A prefs hiccup must never stop
    a push, so an unreachable vault just falls back to what this machine
    knows."""
    try:
        return {c.upper() for c in sync_codes(conn, token)}
    except Exception:                                         # noqa: BLE001
        return _user_codes(conn)


def _game_meta(conn, game_id, codes):
    """Everything the phone's browse/stats surfaces need, computed HERE with
    the desktop's own inference — the phone never re-derives win/loss.

    end_stocks reads the .slp's final Post-Frame events (the same source as
    the desktop row summary). During a meta refresh the local file can be gone
    (append-only vault outlives dead drives), so it falls back to the indexed
    final_state, and failing that stays empty rather than blocking the row.
    """
    row = conn.execute(
        "SELECT path, start_at, stage, duration_s, is_teams, players, "
        "end_method, lras_initiator, placements, final_state "
        "FROM games WHERE id = ?", (game_id,)).fetchone()
    if row is None:
        return {}
    try:
        players = json.loads(row["players"]) if row["players"] else []
    except (TypeError, ValueError):
        players = []

    user_port = next(
        (p["port"] for p in players
         if (p.get("code") or "").upper() in codes), None)
    result = indexer._result_for(row, user_port) if len(players) == 2 else None

    end_stocks = {}
    try:
        from ..store.slp_meta import read_final_stocks
        end_stocks = {str(p): s for p, s in read_final_stocks(row["path"]).items()}
    except Exception:                                         # noqa: BLE001
        pass
    if not end_stocks and row["final_state"]:
        try:
            fs = json.loads(row["final_state"])
            end_stocks = {str(p): v["stocks"] for p, v in fs.items()}
        except (TypeError, ValueError, KeyError):
            pass

    return {
        "start_at": row["start_at"],
        "stage": row["stage"],
        "duration_s": row["duration_s"],
        "is_teams": bool(row["is_teams"]),
        "players": players,
        "user_port": user_port,
        "result": result,
        "end_stocks": end_stocks,
        # end_method 7 = No Contest (LRAS); the initiator port feeds the
        # phone's salt report the same way it feeds the desktop's.
        "end_method": row["end_method"],
        "lras_initiator": row["lras_initiator"],
    }


# What is worth carrying to the cloud. 90% of detected combos are one or two
# moves — a jab into a grab, a stray aerial — and they are noise on every
# surface that reads them: they bury the browse list, they inflate the payload
# of every commit (a fat commit is what blew the Postgres statement timeout on
# a full refresh), and nobody scrolls to them.
#
# Length is the whole test, deliberately: killing does NOT rescue a short one.
# A two-move kill is a hit and an edgeguard, which is not a combo however the
# stock ended — and an exemption for them put 20k of those back in front of
# the reader, which is exactly the noise this removes.
#
# Measured on one 300k-combo library: everything = 300,772 rows; this rule =
# 29,186 (10%).
#
# Applied HERE, at the upload boundary, and not in the detector: the desktop's
# own index keeps every combo (it is local and cheap), so the threshold is a
# publishing decision that can be changed and re-synced, not a measurement
# that has to be redone.
MIN_UPLOAD_MOVES = 4


def _worth_uploading(moves, hits, did_kill):     # noqa: ARG001 — kills earn no pass
    return (len(moves) or hits or 0) >= MIN_UPLOAD_MOVES


def _combos_for(conn, game_id):
    rows = conn.execute(
        "SELECT port, character, code, opp_character, opp_code, start_frame, "
        "end_frame, hits, damage, did_kill, moves_json, start_percent, "
        "end_percent, true_combo, name, opp_name, start_rf, end_rf "
        "FROM combos WHERE game_id = ?", (game_id,)).fetchall()
    out = []
    for r in rows:
        try:
            moves = json.loads(r["moves_json"]) if r["moves_json"] else []
        except (TypeError, ValueError):
            moves = []
        if not _worth_uploading(moves, r["hits"], r["did_kill"]):
            continue
        out.append({
            "port": r["port"], "character": r["character"], "code": r["code"],
            "opp_character": r["opp_character"], "opp_code": r["opp_code"],
            # The cloud copy feeds the derived-bundle viewers (mobile, share
            # pages), which index bundle ROWS — ship the row-frame basis when
            # the extractor recorded it. True frames are the local columns.
            # Accepted side effect: wire timestamps/durations become bundle-
            # row elapsed time (they match the viewer scrubber, and drift a
            # few % from true match time on rollback-heavy games).
            "start_frame": r["start_rf"] if r["start_rf"] is not None else r["start_frame"],
            "end_frame": r["end_rf"] if r["end_rf"] is not None else r["end_frame"],
            "hits": r["hits"], "damage": r["damage"],
            "did_kill": bool(r["did_kill"]), "moves": moves,
            # the desktop card's detail line: percent range, TRUE/STRING, names
            "start_percent": r["start_percent"], "end_percent": r["end_percent"],
            "true_combo": None if r["true_combo"] is None else bool(r["true_combo"]),
            "name": r["name"], "opp_name": r["opp_name"],
        })
    return out


# --- the sync -------------------------------------------------------------

def _remote_hashes(token):
    """{content_hash: (deriver, bytes)} for everything the vault holds.

    A few 5,000-row pages (vault-read "hashes") — the reconcile feed that lets
    a cold push ledger adopt what is already up instead of re-uploading it.
    """
    out = {}
    before = None
    while True:
        body = {"action": "hashes", "token": token}
        if before is not None:
            body["before"] = before
        resp = _call(FN_READ, body)
        for it in resp.get("items", []):
            out[it["content_hash"]] = (it.get("deriver"), it.get("bytes"))
        before = resp.get("next_before")
        if not before:
            return out


def sync(token, limit=None, on_progress=None, conn=None, newest_first=True,
         game_ids=None, should_cancel=None, on_reconcile=None):
    """Push everything not yet in the vault. One button, whole library.

    Returns the push result plus a status snapshot. Safe to re-run: planning
    skips what is already up, and a repeated PUT lands on the same content-hash
    key anyway.

    `game_ids` pushes only those games — the share-on-demand path, where a
    desktop that never syncs its library still has to get the one game it is
    sharing into the vault. The reconcile below is skipped for it: paging the
    whole remote hash set to place a single game costs more than the upload.

    `on_reconcile(checked, total)` reports the reconcile, which runs before
    the first upload and is the whole first minute or two of a sync after a
    sign-in (the ledger starts empty); `on_progress` only starts after it.
    """
    own_conn = conn is None
    conn = conn or indexer.connect()
    try:
        def check_cancelled():
            if should_cancel and should_cancel():
                raise vault_sync.SyncCancelled("vault sync cancelled")

        check_cancelled()
        vault_sync.ensure_schema(conn)
        items = vault_sync.plan(conn, limit=limit, newest_first=newest_first,
                                game_ids=game_ids)
        if items and not game_ids:
            # Reconcile before pushing: a fresh install (reinstall, new PC)
            # has an empty vault_objects ledger and would re-derive and
            # re-upload a library the vault already holds. Ask the server
            # what it has and adopt the matches; a genuine first sync gets an
            # empty answer and pays nothing. Best-effort — a reconcile
            # failure must never block a normal push.
            try:
                check_cancelled()
                if on_reconcile:
                    on_reconcile(0, len(items))
                remote = _remote_hashes(token)
                if remote and vault_sync.adopt_remote(conn, remote,
                                                      on_progress=on_reconcile):
                    items = vault_sync.plan(conn, limit=limit,
                                            newest_first=newest_first)
            except Exception:                             # noqa: BLE001
                logger.warning("vault reconcile skipped", exc_info=True)
        if not items:
            return {"pushed": 0, "skipped": 0, "failed": [],
                    "status": vault_sync.status(conn)}

        def mint_urls(batch_items):
            out = _call(FN_SYNC, {
                "action": "mint", "token": token,
                "items": [{"content_hash": b["content_hash"],
                           "bytes": b["bytes"]} for b in batch_items],
            })
            return out.get("urls", {})

        check_cancelled()
        codes = _codes_for_sync(conn, token)

        def commit(uploaded):
            games = []
            for u in uploaded:
                games.append({
                    "content_hash": u["content_hash"],
                    "bytes": u["bytes"],
                    "deriver": vault_sync.DERIVER,
                    "meta": _game_meta(conn, u["game_id"], codes),
                    "combos": _combos_for(conn, u["game_id"]),
                })
            acked = []
            for i in range(0, len(games), COMMIT_CHUNK):
                acked.extend(_commit_games(token, games[i:i + COMMIT_CHUNK]))
            return acked

        result = vault_sync.push(conn, items, mint_urls, _put, commit=commit,
                                 on_progress=on_progress, batch=BATCH,
                                 should_cancel=should_cancel,
                                 # a one-game share gains nothing from a
                                 # burst pool but its spawn cost
                                 derive_workers=1 if game_ids else DERIVE_WORKERS,
                                 put_workers=PUT_WORKERS)
        result["status"] = vault_sync.status(conn)
        return result
    finally:
        if own_conn:
            conn.close()


def raw_requested(conn):
    """Raw .slp upload is the default. Only an explicit False turns it off
    (indexer.kv_set(conn, RAW_UPLOAD_KEY, False)); there is no UI for it."""
    return indexer.kv_get(conn, RAW_UPLOAD_KEY, True) is not False


def raw_upload_available(conn):
    """Raw is requested and the server has not refused it in the last day. A
    server without raw support fails the mint echo check, which starts the
    cooldown, so the frames chain keeps running until the server is updated."""
    return raw_requested(conn) and not _raw_cooldown(conn)


def _raw_cooldown(conn):
    retry_after = indexer.kv_get(conn, RAW_RETRY_AFTER_KEY, 0)
    return isinstance(retry_after, (int, float)) and retry_after > time.time()


def _check_raw_cancelled(should_cancel):
    if should_cancel and should_cancel():
        raise vault_sync.SyncCancelled("vault raw sync cancelled")


def _mint_raw(conn, token, items, should_cancel):
    _check_raw_cancelled(should_cancel)
    if _raw_cooldown(conn):
        raise RawUploadsUnsupported("server does not support raw uploads")
    out = _call(FN_SYNC, {
        "action": "mint", "kind": "slp", "token": token,
        "items": [{"content_hash": u["content_hash"], "bytes": u["bytes"],
                   "codec": u["codec"]} for u in items],
    })
    _check_raw_cancelled(should_cancel)
    # Older servers ignore kind and sign the FRAMES object key. Never expose
    # even one such URL to push_raw: the PUT would destroy phone playback.
    if not isinstance(out, dict) or out.get("kind") != "slp":
        indexer.kv_set(conn, RAW_RETRY_AFTER_KEY, time.time() + RAW_RETRY_S)
        raise RawUploadsUnsupported("server does not support raw uploads")
    return out.get("urls", {})


def _raw_game(conn, uploaded, codes):
    game_id = uploaded["game_id"]
    game = {"content_hash": uploaded["content_hash"],
            "slp_bytes": uploaded["bytes"], "slp_codec": uploaded["codec"],
            "meta": _game_meta(conn, game_id, codes)}
    # combos_at is the source mtime processed by combo_index, not a count:
    # an extracted game with zero combos must send [], an unprocessed one
    # must omit the key so the server preserves any existing combos.
    row = conn.execute(
        "SELECT combos_at FROM games WHERE id=? AND combos_at = mtime",
        (game_id,)).fetchone()
    stamp = row[0] if row else None
    if stamp is not None:
        game["combos"] = _combos_for(conn, game_id)
    return game, stamp


def _record_raw_combos(conn, uploaded, stamp, basis):
    if stamp is None:
        return
    conn.execute(
        "INSERT INTO vault_raw_combos(game_id, content_hash, codec, combos_at, "
        "frame_basis, committed_at) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(game_id) DO UPDATE SET content_hash=excluded.content_hash, "
        "codec=excluded.codec, combos_at=excluded.combos_at, "
        "frame_basis=excluded.frame_basis, committed_at=excluded.committed_at",
        (uploaded["game_id"], uploaded["content_hash"], uploaded["codec"],
         stamp, basis, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))


def sync_raw(token, limit=None, on_progress=None, conn=None, newest_first=True,
             game_ids=None, should_cancel=None):
    """Push .slp objects only after each mint explicitly proves raw support.

    Explicit raw transport; background callers select it with the local opt-in.
    sync() remains the frames/share transport with its existing wire payloads.
    """
    own_conn = conn is None
    conn = conn or indexer.connect()
    try:
        _check_raw_cancelled(should_cancel)
        items = vault_raw.plan_raw(conn, limit=limit, newest_first=newest_first,
                                   game_ids=game_ids)
        codes = None

        def commit(uploaded):
            nonlocal codes
            _check_raw_cancelled(should_cancel)
            if codes is None:
                codes = _codes_for_sync(conn, token)
            acked = []
            for i in range(0, len(uploaded), COMMIT_CHUNK):
                _check_raw_cancelled(should_cancel)
                chunk = uploaded[i:i + COMMIT_CHUNK]
                basis = indexer.kv_get(conn, "combos_frame_basis", "")
                prepared = [_raw_game(conn, u, codes) for u in chunk]
                accepted = _commit_games(token, [g for g, _stamp in prepared])
                _check_raw_cancelled(should_cancel)
                with conn:
                    for u, (_game, stamp) in zip(chunk, prepared):
                        if u["content_hash"] in accepted:
                            _record_raw_combos(conn, u, stamp, basis)
                acked.extend(accepted)
            return acked

        result = vault_raw.push_raw(
            conn, items, lambda batch: _mint_raw(conn, token, batch, should_cancel),
            _put, commit=commit, on_progress=on_progress, batch=BATCH,
            should_cancel=should_cancel, put_workers=PUT_WORKERS)
        logger.info("vault raw sync: pushed=%d timings=%s", result["pushed"],
                    result["timings"])
        return result
    finally:
        if own_conn:
            conn.close()


def commit_pending_combos(token, limit=None, on_progress=None, conn=None,
                          newest_first=True, game_ids=None, should_cancel=None):
    """Commit processed combos for raw games; checkpoint only acknowledged rows.

    Probes raw mint support once per pass, including on later launches, so a
    server rollback is noticed before any raw metadata commit. The probe's URL
    is discarded; this pass performs no PUTs and needs no local replay file.
    """
    own_conn = conn is None
    conn = conn or indexer.connect()
    try:
        _check_raw_cancelled(should_cancel)
        vault_raw.ensure_raw_schema(conn)
        basis = indexer.kv_get(conn, "combos_frame_basis", "")
        sql = """
            SELECT v.game_id, v.content_hash, v.bytes, v.codec, g.combos_at
              FROM vault_raw v JOIN games g ON g.id = v.game_id
              LEFT JOIN vault_raw_combos c ON c.game_id = v.game_id
             WHERE v.codec = ? AND g.combos_at = g.mtime
               AND (c.game_id IS NULL OR c.content_hash != v.content_hash
                    OR c.codec != v.codec OR c.combos_at != g.combos_at
                    OR c.frame_basis != ?)
        """
        params = [vault_raw.RAW_CODEC, basis]
        if game_ids:
            ids = [int(g) for g in game_ids]
            sql += f" AND g.id IN ({','.join('?' * len(ids))})"
            params.extend(ids)
        sql += " ORDER BY g.start_at " + ("DESC" if newest_first else "ASC")
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        # Multiple indexed paths can refer to one remote game. Never upsert
        # the same content hash twice in a Postgres commit batch.
        grouped = {}
        for row in rows:
            grouped.setdefault(row["content_hash"], []).append(row)
        groups = list(grouped.values())
        done, skipped, codes = 0, [], None
        for i in range(0, len(groups), COMMIT_CHUNK):
            chunk = groups[i:i + COMMIT_CHUNK]
            uploaded = [group[0] for group in chunk]
            # Probe support once per pass, with one real row. Every mint is a
            # quota claim (60 per 10 minutes), so probing each chunk would
            # stall a large library on the limiter. Later chunks are safe
            # without it: a server that predates raw uploads rejects these
            # rows outright (no frames `bytes`), before writing anything.
            if i == 0:
                _mint_raw(conn, token, uploaded[:1], should_cancel)
            if codes is None:
                codes = _codes_for_sync(conn, token)
            _check_raw_cancelled(should_cancel)
            prepared = [_raw_game(conn, u, codes) for u in uploaded]
            # A concurrent combo reset can make a selected row stale.
            games = [game for game, stamp in prepared if stamp is not None]
            accepted = set(_commit_games(token, games)) if games else set()
            _check_raw_cancelled(should_cancel)
            with conn:
                for group, (_game, stamp) in zip(chunk, prepared):
                    if group[0]["content_hash"] not in accepted:
                        skipped.extend(r["game_id"] for r in group)
                        continue
                    for row in group:
                        _record_raw_combos(conn, row, row["combos_at"], basis)
                        done += 1
            if on_progress:
                on_progress(done, len(rows))
        logger.info("vault raw combos: committed=%d skipped=%d", done, len(skipped))
        return {"refreshed": done, "skipped": skipped}
    finally:
        if own_conn:
            conn.close()


def commit_pending_conversions(token, limit=None, on_progress=None, conn=None,
                               newest_first=True, game_ids=None, should_cancel=None):
    """Probe once before frame parsing; each actual mint also guards its kind."""
    own_conn = conn is None
    conn = conn or indexer.connect()
    try:
        def mint(items):
            _check_raw_cancelled(should_cancel)
            out = _call(FN_SYNC, {"action": "mint", "kind": "conv", "token": token,
                                  "items": items})
            _check_raw_cancelled(should_cancel)
            if not isinstance(out, dict) or out.get("kind") != "conv":
                raise ConversionsUnsupported("server does not support conversion sidecars")
            return out.get("urls", {})

        _check_raw_cancelled(should_cancel)
        items = vault_raw.plan_conversions(conn, limit, newest_first, game_ids)
        if items:
            # No parse on an old server. The one-byte probe URL is discarded;
            # real mints claim/sign the actual compressed lengths afterward.
            mint([{"content_hash": items[0]["content_hash"], "bytes": 1,
                   "codec": vault_raw.CONV_CODEC}])
        return vault_raw.push_conversions(
            conn, items, mint, _put, lambda games: _commit_games(token, games),
            on_progress=on_progress, batch=COMMIT_CHUNK, should_cancel=should_cancel)
    finally:
        if own_conn:
            conn.close()


def refresh_meta(token, on_progress=None, conn=None, resume_key=None,
                 should_cancel=None):
    """Re-commit metadata + combos for everything already synced, without
    touching the objects in R2.

    Exists because meta gets richer over time (result/end-stocks landed after
    the first 714 games were up): commit is an upsert keyed on the content
    hash, so pushing fresh rows updates the vault in place. Cheap — a few
    hundred games per HTTP call, no uploads.

    resume_key: kv key for checkpointing. Rows are walked in content_hash
    order and the last committed hash is stored under the key after every
    chunk, so a rerun with the same key continues AFTER it instead of from
    row one. Without this, a large pass that dies on one failed chunk
    restarts from ZERO on every retry — 18.5k games retried every autorun
    cycle is what melted the prod DB on 2026-08-23. The key is cleared on
    completion. Games synced after a checkpoint may sort below it and be
    passed over by the resumed run; they were pushed by the normal sync
    with current meta+combos, so they don't need this refresh.
    """
    own_conn = conn is None
    conn = conn or indexer.connect()

    def check_cancelled():
        if should_cancel and should_cancel():
            raise vault_sync.SyncCancelled("vault metadata refresh cancelled")

    try:
        vault_sync.ensure_schema(conn)
        check_cancelled()
        codes = _codes_for_sync(conn, token)
        check_cancelled()
        after = indexer.kv_get(conn, resume_key) if resume_key else None
        # Deliberately NOT filtered by deriver: metadata is derived from the
        # index, not the blob, so rows pushed under an older deriver still
        # deserve the refresh — and after a deriver bump they'd otherwise be
        # invisible here until re-uploaded.
        rows = conn.execute(
            "SELECT game_id, content_hash, deriver, bytes "
            "FROM vault_objects WHERE content_hash > ? "
            "ORDER BY content_hash",
            (after if isinstance(after, str) else "",)).fetchall()
        done = 0
        skipped = []
        complete = True
        for i in range(0, len(rows), 100):
            check_cancelled()
            chunk = rows[i:i + 100]
            games = [{
                "content_hash": r["content_hash"],
                "bytes": r["bytes"],
                # each row keeps ITS OWN deriver — a meta refresh must not
                # relabel a v1 object as v2
                "deriver": r["deriver"],
                "meta": _game_meta(conn, r["game_id"], codes),
                "combos": _combos_for(conn, r["game_id"]),
            } for r in chunk]
            acknowledged = _commit_games(
                token, games, on_skip=lambda h, e: skipped.append(h))
            # If the owning credential changed while the commit was in flight,
            # leave the local checkpoint untouched. Repeating an acknowledged
            # metadata upsert on the next eligible run is safe.
            check_cancelled()
            done += len(acknowledged)
            if resume_key:
                acked = set(acknowledged)
                contiguous = []
                for row in chunk:
                    if row["content_hash"] not in acked:
                        break
                    contiguous.append(row["content_hash"])
                if contiguous:
                    indexer.kv_set(conn, resume_key, contiguous[-1])
                if len(contiguous) != len(chunk):
                    # A scalar checkpoint cannot encode a hole. Stop here so
                    # the first unacknowledged hash is retried next run rather
                    # than being skipped forever.
                    complete = False
                    break
            if on_progress:
                on_progress(done, len(rows))
        if resume_key and complete:
            check_cancelled()
            indexer.kv_del(conn, resume_key)
        # complete: every row up to the end was acknowledged. A pass that
        # stopped at a hole resumes there; it is not finished.
        return {"refreshed": done, "skipped": skipped, "resumed_after": after,
                "complete": complete and not skipped}
    finally:
        if own_conn:
            conn.close()


def set_prefs(token, startgg_slug=None):
    """Write per-owner prefs (first use: the start.gg slug). Whatever device
    sets it, every other paired device inherits it."""
    return _call(FN_READ, {"action": "prefs-set", "token": token,
                           "startgg_slug": startgg_slug})


def _upper_set(codes):
    return {str(c).strip().upper() for c in codes or [] if c}


def note_codes_edit(conn, before, after):
    """Record codes removed here while there is no agreed list yet.

    sync_codes tells a removal here from one on the phone by comparing both
    sides with the list they last agreed on. Until a merge has written that
    list (the first sync after an update or after a sign-in to another
    account), its fallback is the union, which would bring a code removed
    here back from the vault's copy. These codes are taken out of that union.
    Once the agreed list exists the merge sees removals by itself, and
    nothing is recorded."""
    if indexer.kv_get(conn, CODES_BASE_KEY) is not None:
        return
    before, after = _upper_set(before), _upper_set(after)
    removed = _upper_set(indexer.kv_get(conn, CODES_REMOVED_KEY))
    removed = (removed - after) | (before - after)
    indexer.kv_set(conn, CODES_REMOVED_KEY, sorted(removed))


def sync_codes(conn, token):
    """Reconcile which connect codes are "me" between this machine and the
    vault, and return the merged list.

    The phone can only tell the difference between your games and your
    opponent's if it knows your codes, and it has no Slippi install to read
    them from — so the desktop publishes them, and a code you tick on the
    phone comes back here.

    Both sides can add and remove codes, so this is a three-way merge against
    the list both last agreed on (CODES_BASE_KEY): a code added on either side
    since then is kept, a code removed on either side is dropped, and a code
    both still hold stays. So a code removed on this machine reaches the
    vault instead of coming back from it, and an untick on the phone removes
    the code here, a past Slippi login included (identity.set_codes forgets
    it). The ACTIVE login (today's user.json) always stays: it counts as "me"
    on this machine whatever the list says.

    With no agreed list yet, the merge is the union of both sides, less the
    codes removed here in the meantime (note_codes_edit), so a first merge
    never drops a code on a guess.
    """
    from ..store import identity

    remote = _call(FN_READ, {"action": "prefs-get", "token": token}).get("user_codes")
    remote = None if remote is None else _upper_set(remote)
    _seen, active = identity.seen_login_codes(conn)
    local = _upper_set(identity.known_user_codes(conn))
    base = indexer.kv_get(conn, CODES_BASE_KEY)

    if remote is None:
        # nothing shared yet: this machine seeds the list
        merged = set(local)
    elif base is None:
        merged = (local | remote) - _upper_set(indexer.kv_get(conn, CODES_REMOVED_KEY))
    else:
        base = _upper_set(base)
        merged = (local & remote) | (local - base) | (remote - base)
    if active:
        merged.add(active)
    codes = sorted(merged)
    if set(codes) != remote:
        _call(FN_READ, {"action": "prefs-set", "token": token, "user_codes": codes})

    # The agreed list is written only once the vault holds `codes`, and only
    # after the local lists: one that ran ahead of either would read the
    # older copy as an edit on the other side at the next merge. If a write
    # fails, the agreed list stays as it was and the next merge finds the
    # same difference again. Best-effort: a sync running in the app holds the
    # index open, and a locked kv write must not take down a refresh that is
    # otherwise entirely network work.
    try:
        identity.set_codes(conn, codes, active)
        with conn:
            conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (CODES_BASE_KEY, json.dumps(codes)))
            conn.execute("DELETE FROM kv WHERE key=?", (CODES_REMOVED_KEY,))
    except Exception:                                         # noqa: BLE001
        pass
    return codes


# --- public share links ----------------------------------------------------

_ACTIVITY_TTL = 300
_ACTIVITY_REFRESH_MIN = 30
_ACTIVITY_CACHE_SIZE = 64
_activity_cache = OrderedDict()
# Serialize activity cache misses, including the network read, so simultaneous
# mounts/refreshes cannot launch duplicate requests. Only this feature uses it.
_activity_lock = threading.Lock()


def _activity_page(token, kind, cursor, refresh):
    key = (hashlib.sha256(token.encode()).hexdigest(), kind, cursor)
    with _activity_lock:
        cached = _activity_cache.get(key)
        if cached:
            stamp, page, error = cached
            ttl = _ACTIVITY_REFRESH_MIN if refresh or error else _ACTIVITY_TTL
            if time.monotonic() - stamp < ttl:
                _activity_cache.move_to_end(key)
                if error:
                    raise VaultError(error)
                return copy.deepcopy(page)
        try:
            page = _call(FN_READ, {"action": "activity-page", "kind": kind,
                                   "token": token, "cursor": cursor}, timeout=30)
            limit = 30 if kind == "uploads" else 50
            if not isinstance(page.get("rows"), list) or len(page["rows"]) > limit:
                raise VaultError("Invalid cloud activity page")
            next_cursor = page.get("next")
            if next_cursor is not None:
                _validate_activity_cursor(kind, next_cursor)
                if (not page["rows"] or (cursor and
                        (next_cursor >= cursor if kind == "uploads" else next_cursor <= cursor))):
                    raise VaultError("Cloud activity pagination did not advance")
            error = None
        except (VaultError, OSError, ValueError, TypeError, AttributeError):
            # Briefly cache failures too; an unavailable deployment must not
            # trigger a request storm or fall back to crawling the raw history.
            page, error = None, "Cloud activity is unavailable. Try again shortly."
        _activity_cache[key] = (time.monotonic(), copy.deepcopy(page), error)
        _activity_cache.move_to_end(key)
        while len(_activity_cache) > _ACTIVITY_CACHE_SIZE:
            _activity_cache.popitem(last=False)
        if error:
            raise VaultError(error)
        return page


def _validate_activity_cursor(kind, cursor):
    if cursor is None:
        return
    if not isinstance(cursor, str):
        raise ValueError("Invalid activity cursor")
    if kind == "uploads":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cursor):
            raise ValueError("Invalid activity cursor")
        date.fromisoformat(cursor)
    elif not re.fullmatch(r"[0-9a-z]{12}", cursor):
        raise ValueError("Invalid activity cursor")


def account_activity(token, *, kind=None, cursor=None, refresh=False):
    """One cached page per kind; older history is fetched only on demand."""
    if kind not in (None, "uploads", "shares") or (cursor is not None and kind is None):
        raise ValueError("Invalid activity kind")
    _validate_activity_cursor(kind, cursor)
    result = {"upload_history": [], "shared_links": [], "next_uploads": None, "next_shares": None}
    for page_kind in ((kind,) if kind else ("uploads", "shares")):
        page = _activity_page(token, page_kind, cursor, refresh)
        result[f"next_{page_kind}"] = page.get("next")
        if page_kind == "uploads":
            result["upload_history"] = page["rows"]
        else:
            for row in page["rows"]:
                share_id = str(row["id"])
                if not re.fullmatch(r"[0-9a-z]{12}", share_id):
                    raise VaultError("Invalid cloud share link")
                result["shared_links"].append({"url": f"{SHARE_SITE}/replay/{share_id}",
                    "content_hash": row["content_hash"], "start_at": row.get("start_at"),
                    "players": row.get("players") or []})
    return result


def mint_share(token, content_hash, *, should_cancel=None):
    """Mint (or re-read) a game's public link: one database row.

    The link plays the game's own file (the raw .slp when the vault has it,
    else its frames file), so nothing is built or uploaded at share time.
    """
    _check_raw_cancelled(should_cancel)
    out = _call(FN_PUBLIC, {"action": "mint", "token": token,
                            "content_hash": content_hash})
    _check_raw_cancelled(should_cancel)
    return out


def push_share_thumb(token, share_id, png_b64):
    """Upload a share's unfurl thumbnail. The PNG is drawn by the client (it
    is the one place the stock icons meet a canvas); losing it loses only the
    picture, never the link."""
    return _call(FN_PUBLIC, {"action": "thumb", "token": token,
                             "id": share_id, "png_b64": png_b64})


# --- pairing --------------------------------------------------------------
# The phone client lives here; a paired device token rides in the URL fragment
# so it never reaches the Pages log or a Referer header.
VAULT_WEB_URL = "https://tracker.ssbmnucleus.net"


def pair_url(device_token):
    return f"{VAULT_WEB_URL}/#t={device_token}"


def pair_device(token, label="Phone"):
    """Mint a device token for a phone and return it with its pairing URL.

    This is the ONLY moment the raw token exists anywhere — the vault stores
    just its hash — so a token that isn't captured now is re-paired, never
    recovered. Requires the desktop's app token: a device cannot mint devices.
    """
    out = _call(FN_SYNC, {"action": "pair", "token": token, "label": label})
    out["pair_url"] = pair_url(out["device_token"])
    return out


def list_devices(token):
    return _call(FN_SYNC, {"action": "devices", "token": token}).get("devices", [])


def revoke_device(token, device_id):
    return _call(FN_SYNC, {"action": "revoke", "token": token,
                           "device_id": int(device_id)})


def verify(token, limit=200, repair_conn=None):
    """Fetch every indexed object back and confirm it is really there and really
    decompresses. Catches silent write failures and truncation that the upload
    path cannot see on its own.

    With repair_conn, any bad object has its local vault_objects row dropped so
    the next sync re-derives and re-pushes it.
    """
    import gzip

    page = _call(FN_READ, {"action": "list", "token": token, "limit": limit})
    hashes = [g["content_hash"] for g in page.get("games", [])]
    if not hashes:
        return {"checked": 0, "ok": 0, "bad": []}

    bad = []
    ok = 0
    for i in range(0, len(hashes), 100):
        chunk = hashes[i:i + 100]
        urls = _call(FN_READ, {"action": "urls", "token": token,
                               "content_hashes": chunk}).get("urls", {})
        for h in chunk:
            url = urls.get(h)
            if not url:
                bad.append((h, "no url"))
                continue
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    raw = r.read()
                json.loads(gzip.decompress(raw))
                ok += 1
            except Exception as e:                            # noqa: BLE001
                bad.append((h, str(e)[:120]))

    if repair_conn is not None and bad:
        repair_conn.executemany(
            "DELETE FROM vault_objects WHERE content_hash = ?",
            [(h,) for h, _ in bad])
        repair_conn.commit()
    return {"checked": len(hashes), "ok": ok, "bad": bad}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Push replays to the cloud vault")
    ap.add_argument("token", help="Patreon app token or paired device token")
    ap.add_argument("--limit", type=int, default=None,
                    help="only push this many games (a first run is ~0.3s/game)")
    ap.add_argument("--newest-first", action="store_true",
                    help="(default; kept so old invocations still parse)")
    ap.add_argument("--oldest-first", action="store_true",
                    help="push the oldest pending games first instead of the "
                         "newest (the pre-#64 order)")
    ap.add_argument("--refresh-meta", action="store_true",
                    help="re-commit meta+combos for already-synced games")
    ap.add_argument("--startgg-slug", default=None,
                    help="store your start.gg slug in the vault (phones inherit it)")
    ap.add_argument("--sync-codes", action="store_true",
                    help="reconcile your 'me' connect codes with the vault "
                         "(a push does this anyway; this is the standalone run)")
    args = ap.parse_args()

    if args.startgg_slug is not None:
        print(json.dumps(set_prefs(args.token, startgg_slug=args.startgg_slug)))
        raise SystemExit(0)

    if args.sync_codes:
        _conn = indexer.connect()
        try:
            print(json.dumps({"codes": sync_codes(_conn, args.token)}))
        finally:
            _conn.close()
        raise SystemExit(0)

    if args.refresh_meta:
        res = refresh_meta(args.token, on_progress=lambda d, t: print(
            f"  {d}/{t}", flush=True))
        print(json.dumps(res))
        raise SystemExit(0)

    def progress(done, total, pushed, skipped):
        if done % 10 == 0 or done == total:
            print(f"  {done}/{total}  pushed={pushed} skipped={skipped}", flush=True)

    res = sync(args.token, limit=args.limit, on_progress=progress,
               newest_first=not args.oldest_first)
    print(json.dumps({k: v for k, v in res.items() if k != "failed"}, indent=2))
    if res["failed"]:
        print(f"\n{len(res['failed'])} failed; first few:")
        for gid, why in res["failed"][:5]:
            print(f"  game {gid}: {why}")
