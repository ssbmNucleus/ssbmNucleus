"""vault_sync — push derived replay data to the cloud vault.

One "Sync" button, whole library, incremental, append-only. No per-replay
upload or removal UI. See research/docs-research/mobile-vault.md.

What goes up is the *frame data only* — positions, states, direction, percent.
Animation geometry is 96-99% of a clip payload and is identical for every user,
so it ships once as per-character packs rather than inlined per game. Measured
2026-08-15: frame data is 0.54 KB gzipped per second of gameplay, ~58 KB for an
average game, against ~1.5 MB for the raw .slp.

Two rules this module exists to enforce:

1. **No credentials here.** The desktop app is distributed to users, so anything
   it holds is public. Presigned URLs are minted by the edge function, which is
   the only thing that ever sees an R2 key. `push()` takes callables.
2. **The client never chooses the object key.** It sends a content hash; the
   server derives `v1/{owner}/games/{hash}.json.gz`. Client-supplied keys are
   how you end up re-validating them everywhere (see vAMP's r2Storage
   .validateR2Key) or, worse, not validating them somewhere.
"""
import gzip
import io
import json
import os
import sqlite3
import threading
import time

from core.hashing import sha256_file
from ..store import indexer

# Bump when the derived payload's shape or content changes, so a sync re-pushes
# what it already sent. Cheap to bump; the alternative is stale blobs that no
# longer match what the renderer expects.
# v2: bundles carry `items` (projectile/item tracks from the raw 0x3B events)
# and `stage_state` (FoD platform heights / Stadium transformations, 0x3F/0x41)
# so lasers, needles, turnips and dynamic stages render in Watch Lite.
# v3: Ice Climbers games carry `frames.fol` (Nana's render-only follower rows)
# so she is drawn instead of silently missing. Only ICs bundles changed shape,
# so ensure_schema() relabels every non-ICs v2 row in place (byte-identical
# blobs) instead of re-pushing the whole library — see _relabel_unchanged.
# v4: bundles carry `frames.lt` (analog trigger press depth) so shield bubbles
# render at the true in-game size (hard press = half the size factor of a
# light one). Every bundle's content changes — no relabel, full re-push.
DERIVER = "frames-v4"


class SyncCancelled(RuntimeError):
    """Raised at a safe boundary when the owning credential was replaced."""

# CSS-selected external character id that carries a follower (Nana).
_ICS_EXT_ID = 14

_HASH_CHUNK = 1 << 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_upload_history (
    id INTEGER PRIMARY KEY,
    uploaded_at TEXT NOT NULL,
    games INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS vault_shared_links (
    url TEXT PRIMARY KEY,
    game_id INTEGER NOT NULL,
    shared_at TEXT NOT NULL,
    combo INTEGER
);
CREATE TABLE IF NOT EXISTS vault_objects (
    game_id      INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    deriver      TEXT NOT NULL,
    bytes        INTEGER NOT NULL,
    pushed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_vault_hash ON vault_objects(content_hash);
CREATE TABLE IF NOT EXISTS vault_hashes (
    path  TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size  INTEGER NOT NULL,
    sha   TEXT NOT NULL
);
-- Games the deriver REFUSES (corrupt .slp, solo training, degenerate) used to
-- stay "pending" forever and re-derive on every sync — a 2,787-game backlog
-- made every Sync click grind for minutes and upload nothing. Record the
-- refusal once; retry only when the file changes or the deriver bumps.
-- Local bookkeeping only: nothing here ever deletes anything, anywhere.
CREATE TABLE IF NOT EXISTS vault_skips (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    deriver TEXT NOT NULL,
    mtime   REAL,
    size    INTEGER,
    reason  TEXT,
    at      TEXT
);
"""


# Once per database per process, same reasoning as indexer.connect(): this is
# called from /vault/status, which the Settings panel polls every 2 seconds
# while the launch chain runs — exactly when the DDL's write lock is contended.
_ensured_paths = set()
_ensure_lock = threading.Lock()


def ensure_schema(conn):
    row = conn.execute(
        "SELECT file FROM pragma_database_list WHERE name = 'main'").fetchone()
    path = row[0] if row else ""
    if path in _ensured_paths:
        return
    with _ensure_lock:
        if path in _ensured_paths:
            return
        conn.executescript(SCHEMA)
        conn.commit()
        _relabel_unchanged(conn)
        # an in-memory db has no path ("") — never memoize those, every
        # connection is a distinct empty database
        if path:
            _ensured_paths.add(path)


def _relabel_unchanged(conn):
    """frames-v2 -> frames-v3 changed only Ice Climbers bundles (frames.fol
    appeared). Every other game's blob is byte-identical under both labels, so
    relabel those rows in place instead of re-deriving and re-uploading a whole
    library; ICs games keep their v2 label and plan() re-pushes just them.
    Idempotent and cheap: once no v2 rows remain this reads nothing."""
    try:
        rows = conn.execute(
            "SELECT v.game_id, g.players FROM vault_objects v "
            "JOIN games g ON g.id = v.game_id "
            "WHERE v.deriver = 'frames-v2'").fetchall()
    except sqlite3.OperationalError:
        return                       # no games table yet (fresh index)
    keep = []
    for game_id, players in rows:
        try:
            chars = [p.get("character") for p in json.loads(players or "[]")]
        except (TypeError, ValueError, AttributeError):
            chars = []
        if _ICS_EXT_ID not in chars:
            keep.append((game_id,))
    if keep:
        conn.executemany(
            "UPDATE vault_objects SET deriver = 'frames-v3' WHERE game_id = ?",
            keep)
        conn.commit()


# --- identity -------------------------------------------------------------

def content_hash(conn, path, mtime=None, size=None):
    """SHA-256 of the .slp itself, cached by (path, mtime, size).

    Hashes the replay rather than the derived blob deliberately: this is the
    identity of the *game*, so it must not move when the deriver changes. It is
    also what makes the cloud's UNIQUE (owner_id, content_hash) idempotent when
    the same replay is re-indexed from a different path.
    """
    st = None
    if mtime is None or size is None:
        st = os.stat(path)
        mtime = st.st_mtime if mtime is None else mtime
        size = st.st_size if size is None else size

    row = conn.execute(
        "SELECT mtime, size, sha FROM vault_hashes WHERE path = ?", (path,)
    ).fetchone()
    if row and abs(row[0] - mtime) < 1e-6 and row[1] == size:
        return row[2]

    sha = sha256_file(path, _HASH_CHUNK)
    conn.execute(
        "INSERT INTO vault_hashes(path, mtime, size, sha) VALUES(?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, "
        "size=excluded.size, sha=excluded.sha",
        (path, mtime, size, sha),
    )
    return sha


# --- derivation -----------------------------------------------------------

def derive_blob(path):
    """Frame data for one whole game, gzipped. Returns bytes, or None if the
    replay will not frame-parse (a corrupt .slp must skip, not abort a sync)."""
    from ..store.game_trace import load_trace
    from ..video.viz_export import build_viz_bundle

    try:
        trace = load_trace(path)
        if trace is None:
            return None
        # build_viz_bundle sits inside the same guard: a handful of replays
        # carry None frame values for a port (mid-game drop-in slots) and
        # TypeError out of the rounding helpers. One weird game must skip,
        # never abort a two-hour full-library sync (bitten twice now).
        bundle = build_viz_bundle(trace)
        if bundle["meta"]["n"] < 2:
            return None        # degenerate; the renderer refuses these anyway
        # serialization inside the guard too: an unserializable stray (the
        # peppi Team enum was one) is a skip, never an aborted run
        raw = json.dumps(bundle, separators=(",", ":")).encode()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:                                     # noqa: BLE001
        # BaseException, not Exception: peppi_py is Rust via pyo3 and a
        # malformed .slp makes it *panic* ("A StructArray must contain at
        # least one field"), surfacing as pyo3_runtime.PanicException --
        # which derives from BaseException only.
        return None
    buf = io.BytesIO()
    # mtime=0 so identical input compresses to identical bytes -- a re-derive
    # must not look like a change. Level 6, not 9: measured 2026-09-21 on 36
    # real games, level 9 cost 3x the CPU (15.8 vs 4.7 ms, ~13% of a derive)
    # for a 4.5% smaller blob. Nothing keys on the blob bytes (identity is the
    # .slp hash, the ledger keys on DERIVER), so no re-push follows.
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as gz:
        gz.write(raw)
    return buf.getvalue()


# Derivation runs in the shared worker subprocess, not in the serving process.
# Measured on the live app: with a 2,787-game backlog the in-process derive
# loop held the GIL enough that /stats went from 0.2s to 10-18s for the whole
# multi-hour run — and since the launch autorun resumes the backlog on every
# boot, "the app is slow every time I open it" WAS the sync. The replay index
# and the combo pass go through the same worker (tracker.store.scan_pool):
# the chain runs them in order anyway, and one child keeps the memory cost of
# the spawn re-import to a single copy.
#
# derive_blob itself never raises (BaseException guard, corrupt .slp -> None),
# so it is safe to hand straight to the pool.
def _derive_offprocess(path):
    from ..store import scan_pool
    return scan_pool.run(derive_blob, path)


# The pending upload-claim limiter (meleeWebsite migration
# 20260829_security_hardening: api_claim_vault_upload) answers a mint over its
# per-window budget with HTTP 429 "vault upload quota exceeded".
QUOTA_WAIT_S = 11 * 60
QUOTA_SLICE_S = 30


def _is_quota_error(e):
    text = str(e).lower()
    return "quota" in text or "http 429" in text


_MISSING = object()      # the replay is gone locally: skip, never ledger it
_CANCELLED = object()    # a PUT worker saw the cancel before starting


def _derive_ahead(items, workers, window):
    """Yield (index, item, body) in plan order, body = bytes | None (refused)
    | _MISSING.

    One worker: derives lazily, one at a time, through the shared worker --
    exactly the old loop. More: a scan_pool.burst derives up to `window` games
    ahead, so while push() is minting/uploading/committing one batch the
    children are already deriving the next. Measured 2026-09-21: derive was
    ~65% of a batch's wall time and ran strictly serially with the network.
    Closing the generator (push's finally) shuts the burst pool down, which
    also drops any look-ahead a cancelled sync will never read.
    """
    if not workers or workers <= 1:
        for i, item in enumerate(items):
            if not os.path.exists(item["path"]):
                yield i, item, _MISSING
            else:
                yield i, item, _derive_offprocess(item["path"])
        return

    from collections import deque
    from ..store import scan_pool
    with scan_pool.burst(workers) as pool:
        pending = deque()
        it = iter(enumerate(items))
        exhausted = False
        try:
            while True:
                while not exhausted and len(pending) < max(window, workers):
                    try:
                        i, item = next(it)
                    except StopIteration:
                        exhausted = True
                        break
                    if not os.path.exists(item["path"]):
                        pending.append((i, item, _MISSING))
                    else:
                        pending.append((i, item, pool.submit(derive_blob, item["path"])))
                if not pending:
                    return
                i, item, job = pending.popleft()
                yield i, item, job if job is _MISSING else job.result()
        finally:
            for _i, _item, job in pending:
                if job is not _MISSING:
                    job.cancel()


# --- reconcile ------------------------------------------------------------

def adopt_remote(conn, remote_rows, on_progress=None):
    """Mark pending games the cloud already holds as pushed, without uploading.

    ``remote_rows``: {content_hash: (deriver, bytes)} from vault-read's
    "hashes" action. The push ledger (vault_objects) is local-only, so a
    reinstall, a new PC or a Patreon sign-in starts cold and would re-derive
    and re-upload the whole library; hashing the .slp (cached in vault_hashes)
    is the only cost of adopting instead. Only rows whose remote deriver
    matches the current one are adopted — an old-deriver row stays pending so
    the upgrade re-push still happens.

    Commits every 200 games checked so the Sync status counters move while a
    big reconcile runs, and reports ``on_progress(checked, total)`` at the
    same points. A cold reconcile of a 20k library takes a minute or two, and
    without that callback the panel sat on "Uploading… 0 games" for all of it
    (2026-10-15: read as a stuck sync). Returns the number adopted.
    """
    if not remote_rows:
        return 0
    adopted = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    items = plan(conn)
    total = len(items)
    if on_progress:
        on_progress(0, total)
    for checked, item in enumerate(items, 1):
        try:
            sha = content_hash(conn, item["path"], item["mtime"], item["size"])
        except OSError:
            sha = None
        row = remote_rows.get(sha) if sha else None
        if row and row[0] == DERIVER:
            conn.execute(
                "INSERT INTO vault_objects(game_id, content_hash, deriver, "
                "bytes, pushed_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(game_id) DO UPDATE SET content_hash=excluded.content_hash, "
                "deriver=excluded.deriver, bytes=excluded.bytes, "
                "pushed_at=excluded.pushed_at",
                (item["id"], sha, DERIVER, int(row[1] or 0), now))
            adopted += 1
        if checked % 200 == 0:
            conn.commit()
            if on_progress:
                on_progress(checked, total)
    conn.commit()
    if on_progress:
        on_progress(total, total)
    return adopted


# --- planning -------------------------------------------------------------

def plan(conn, limit=None, newest_first=True, game_ids=None):
    """Games that still need pushing, NEWEST first by default.

    A game is pending when it has no vault_objects row, or its row was written
    by a different deriver. Append-only: rows whose replay has vanished locally
    are NOT scheduled for deletion — a dead drive must never empty the vault.

    Newest first because the phone lists games the moment their batch commits
    (every BATCH games, not at the end of the run) — but it only lists games
    attributed to your connect codes, and years-old replays often predate the
    code you play under now. Bug #64: a 44k-game library pushing oldest first
    spent hours uploading ~18k 2021-22 games with no `user_port`, and the
    phone sat on "0 games" the whole time. Recent games first means the first
    batch is already something the phone can show. Undated rows (NULL
    start_at) sort last under DESC; the phone can't list them anyway.

    `newest_first=False` keeps the old oldest-first order for anyone who
    explicitly wants it (CLI `--oldest-first`).

    `game_ids` narrows the plan to specific games. That is what share-on-demand
    uses: a free account never pushes its library, so the one game it chose to
    share has to be uploadable on its own. Still goes through the same pending
    test, so an already-pushed game plans to nothing rather than re-uploading.
    """
    order = "DESC" if newest_first else "ASC"
    # vault_skips: a recorded derive-refusal excludes the game until the file
    # changes (mtime/size, NULL-safe via IS) or the deriver label moves on.
    sql = f"""
        SELECT g.id, g.path, g.mtime, g.size, g.duration_s
          FROM games g
          LEFT JOIN vault_objects v ON v.game_id = g.id AND v.deriver = ?
         WHERE g.parse_ok = 1 AND v.game_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM vault_skips s
                            WHERE s.game_id = g.id AND s.deriver = ?
                              AND s.mtime IS g.mtime AND s.size IS g.size)
         ORDER BY g.start_at {order}
    """
    params = [DERIVER, DERIVER]
    if game_ids:
        ids = [int(g) for g in game_ids]
        # Spliced before ORDER BY, so the f-string above has to be reopened
        # rather than appended to.
        sql = sql.replace("ORDER BY", f"AND g.id IN ({','.join('?' * len(ids))}) ORDER BY")
        params.extend(ids)
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(id=r[0], path=r[1], mtime=r[2], size=r[3], duration_s=r[4])
            for r in conn.execute(sql, params)]


def status(conn):
    """Counts for the Sync button: what is up, what is pending.

    A game is up when either transport settled it: a frames row at the
    current deriver, or a raw row at the current codec (F-E-2). The raw
    ledger exists only once raw uploads were used.
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM games WHERE parse_ok = 1").fetchone()[0]
    pushed, sent_bytes = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM vault_objects "
        "WHERE deriver = ?", (DERIVER,)).fetchone()
    raw_up = ""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='vault_raw'").fetchone():
        from .vault_raw import RAW_CODEC
        raw_up = (" OR EXISTS (SELECT 1 FROM vault_raw r WHERE r.game_id = g.id "
                  f"AND r.codec = '{RAW_CODEC}')")
        pushed += conn.execute(
            "SELECT COUNT(*) FROM games g JOIN vault_raw r ON r.game_id = g.id "
            "WHERE g.parse_ok = 1 AND r.codec = ? AND NOT EXISTS (SELECT 1 FROM "
            "vault_objects o WHERE o.game_id = g.id AND o.deriver = ?)",
            (RAW_CODEC, DERIVER)).fetchone()[0]
    skipped = conn.execute(
        "SELECT COUNT(*) FROM vault_skips s JOIN games g ON g.id = s.game_id "
        "WHERE s.deriver = ? AND g.parse_ok = 1 "
        "AND s.mtime IS g.mtime AND s.size IS g.size "
        f"AND NOT (0{raw_up})", (DERIVER,)).fetchone()[0]
    return {"games": total, "pushed": pushed, "skipped": skipped,
            "pending": max(0, total - pushed - skipped),
            # Advisory only. vAMP's grace-cleanup planner once trusted a
            # client-declared size and hard-deleted an entire library when it
            # defaulted to 0; anything that decides quota or deletion must read
            # sizes back from R2, never from this number.
            "bytes_sent_local_estimate": sent_bytes, "deriver": DERIVER}


# --- pushing --------------------------------------------------------------

def push(conn, items, mint_urls, put, commit=None, on_progress=None, batch=50,
         should_cancel=None, derive_workers=1, put_workers=1):
    """Upload `items` (from plan()) using caller-supplied transport.

    Throughput knobs (both default to the old one-at-a-time behaviour):
    `derive_workers` derives that many games at once in a temporary
    scan_pool.burst (still out of process, still below the backend's
    priority) and keeps up to a batch of derives in flight AHEAD of the
    upload, so the next batch derives while this one is minting/PUTting/
    committing. `put_workers` runs a batch's PUTs concurrently; `put` must be
    thread-safe when it is > 1. Order, the skip ledger, progress and
    cancellation stay on this thread and behave exactly as before.

    mint_urls(list[{game_id, content_hash, bytes}]) -> {content_hash: put_url}
        Asks the edge function for presigned PUTs. The function derives the
        object key from the authenticated owner and the hash; we never send a
        key and never see a credential.
    put(url, body: bytes) -> None, raising on failure.
    commit(list[{game_id, content_hash, bytes}]) -> iterable[content_hash]
        Called once per batch after its objects are safely in R2, to write the
        index rows, and returns the hashes actually acknowledged by that write.
        Ordering matters: rows written before the upload would point
        at objects that may never arrive, and every read would have to defend
        against it. If commit raises, the batch is left unmarked locally so the
        next sync retries it -- an object re-uploaded is harmless, a game
        missing from the index is not.

    Returns {"pushed": n, "skipped": n, "failed": [(game_id, reason)]}.
    """
    pushed = skipped = 0
    failed = []
    queue = []

    def check_cancelled():
        if should_cancel and should_cancel():
            raise SyncCancelled("vault sync cancelled")

    def flush():
        nonlocal pushed
        if not queue:
            return
        check_cancelled()
        # A transient mint failure (edge-function timeout, network blip) must
        # cost one batch, not the whole multi-hour run — the killed run at
        # 3,890/19,852 died exactly here. One quiet retry, then fail the batch
        # and move on; plan() re-schedules it next sync.
        #
        # A QUOTA refusal is different: it is the server pacing us, and it
        # clears on its own within its window (the upload-claim limiter counts
        # mints per 10 minutes). Failing the batch there would just burn the
        # plan -- every following batch hits the same wall -- so wait it out,
        # in cancellable slices, for up to one full window.
        # The same replay in two folders is two local games with one content
        # hash. It is one object and one cloud row, so it is minted, PUT and
        # committed once; every local copy is ledgered off that one result.
        # Committing both in one batch made vault-sync's upsert touch a row
        # twice, which Postgres refuses -- the whole batch 500'd on every sync
        # (2026-09-25).
        twins = {}                  # sha -> the other game ids carrying it
        unique = []
        for g, h, b in queue:
            if h in twins:
                twins[h].append(g)
            else:
                twins[h] = []
                unique.append((g, h, b))
        payload = [{"game_id": g, "content_hash": h, "bytes": len(b)}
                   for g, h, b in unique]
        try:
            urls = mint_urls(payload)
        except Exception as first:                        # noqa: BLE001
            waited = 0
            err = first
            while _is_quota_error(err) and waited < QUOTA_WAIT_S:
                time.sleep(QUOTA_SLICE_S)
                waited += QUOTA_SLICE_S
                check_cancelled()
                try:
                    urls = mint_urls(payload)
                    err = None
                    break
                except Exception as e:                    # noqa: BLE001
                    err = e
            if err is not None:
                time.sleep(5)
                check_cancelled()
                try:
                    urls = mint_urls(payload)
                except Exception as e:                    # noqa: BLE001
                    for g, _h, _b in queue:
                        failed.append((g, f"mint failed: {e}"))
                    queue.clear()
                    return
        def fail(game_id, sha, reason):
            for g in (game_id, *twins[sha]):
                failed.append((g, reason))

        uploaded = []
        jobs = []
        for game_id, sha, body in unique:
            url = urls.get(sha)
            if not url:
                fail(game_id, sha, "no url minted")
                continue
            jobs.append((game_id, sha, body, url))

        def put_one(job):
            game_id, sha, body, url = job
            if should_cancel and should_cancel():
                return job, _CANCELLED
            try:
                put(url, body)
            except Exception as e:                      # noqa: BLE001
                return job, str(e)
            return job, None

        if put_pool is not None and len(jobs) > 1:
            check_cancelled()
            outcomes = list(put_pool.map(put_one, jobs))
        else:
            outcomes = []
            for job in jobs:
                check_cancelled()
                outcomes.append(put_one(job))
        for (game_id, sha, body, _url), err in outcomes:
            if err is _CANCELLED:
                continue
            if err is not None:
                fail(game_id, sha, err)
                continue
            uploaded.append({"game_id": game_id, "content_hash": sha,
                             "bytes": len(body)})
        # Anything a worker skipped for cancellation was never PUT; the
        # uploaded ones are real objects but stay unledgered, exactly as a
        # cancel between two serial PUTs always left them.
        check_cancelled()

        acknowledged = {u["content_hash"] for u in uploaded}
        if commit and uploaded:
            check_cancelled()
            try:
                acknowledged = set(commit(uploaded))
            except Exception as e:                      # noqa: BLE001
                # Objects are in R2 but unindexed. Leave them unmarked so the
                # next sync re-pushes and re-commits; the PUT is idempotent
                # because the key is the content hash.
                for u in uploaded:
                    fail(u["game_id"], u["content_hash"], f"commit failed: {e}")
                queue.clear()
                return
            # The request above may have completed for the former owner while
            # sign-out/token replacement happened in flight. Preserve the
            # remote acknowledgement, but leave local success unrecorded so
            # the current owner must reconcile or push independently.
            check_cancelled()

        committed = []
        for u in uploaded:
            if u["content_hash"] in acknowledged:
                committed.append(u)
            else:
                fail(u["game_id"], u["content_hash"], "commit not acknowledged")

        ledgered = 0
        for u in committed:
            sha, nbytes = u["content_hash"], u["bytes"]
            for game_id in (u["game_id"], *twins[sha]):
                conn.execute(
                    "INSERT INTO vault_objects(game_id, content_hash, deriver, "
                    "bytes, pushed_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(game_id) DO UPDATE SET content_hash=excluded.content_hash, "
                    "deriver=excluded.deriver, bytes=excluded.bytes, "
                    "pushed_at=excluded.pushed_at",
                    (game_id, sha, DERIVER, nbytes,
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                )
                ledgered += 1
        pushed += ledgered
        if ledgered:
            conn.execute(
                "INSERT INTO vault_upload_history(uploaded_at, games) VALUES(?,?)",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ledgered))
        conn.commit()
        queue.clear()

    put_pool = None
    if put_workers and put_workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        put_pool = ThreadPoolExecutor(max_workers=int(put_workers),
                                      thread_name_prefix="vault-put")
    derived = _derive_ahead(items, derive_workers, window=max(batch, 1))
    try:
        for i, item, body in derived:
            check_cancelled()
            if body is _MISSING:
                skipped += 1             # append-only: absent locally != delete
                continue
            if body is None:
                # Deriver refused this file (corrupt, solo training, degenerate).
                # Ledger it so it never grinds another sync; missing-path skips
                # above stay unrecorded on purpose — a drive that comes back must
                # resume, and an exists() check costs nothing anyway.
                conn.execute(
                    "INSERT INTO vault_skips(game_id, deriver, mtime, size, "
                    "reason, at) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(game_id) DO UPDATE SET deriver=excluded.deriver, "
                    "mtime=excluded.mtime, size=excluded.size, "
                    "reason=excluded.reason, at=excluded.at",
                    (item["id"], DERIVER, item.get("mtime"), item.get("size"),
                     "derive refused",
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                conn.commit()
                skipped += 1
                continue
            try:
                sha = content_hash(conn, item["path"], item.get("mtime"), item.get("size"))
            except OSError as e:
                failed.append((item["id"], f"hash failed: {e}"))
                continue
            queue.append((item["id"], sha, body))
            if len(queue) >= batch:
                flush()
            if on_progress:
                on_progress(i + 1, len(items), pushed, skipped)
        flush()
        check_cancelled()
        conn.commit()
    finally:
        derived.close()              # shuts the burst pool, drops look-ahead
        if put_pool is not None:
            put_pool.shutdown(wait=True, cancel_futures=True)
    return {"pushed": pushed, "skipped": skipped, "failed": failed}


# --- dry run --------------------------------------------------------------

def dry_run(limit=200):
    """Derive without uploading, to measure what a real sync would cost."""
    conn = indexer.connect()
    try:
        ensure_schema(conn)
        items = plan(conn, limit=limit)
        total = secs = 0
        t0 = time.time()
        derived = 0
        for it in items:
            if not os.path.exists(it["path"]):
                continue
            body = derive_blob(it["path"])
            if body is None:
                continue
            total += len(body)
            secs += it.get("duration_s") or 0
            derived += 1
        elapsed = time.time() - t0
        st = status(conn)
        return {
            "sampled": derived, "pending_total": st["pending"],
            "bytes": total,
            "kb_per_game": (total / derived / 1024) if derived else 0,
            "kb_per_second_of_play": (total / secs / 1024) if secs else 0,
            "derive_seconds": elapsed,
            "projected_gb_full_library":
                (total / derived * st["pending"] / 1024 ** 3) if derived else 0,
            "projected_derive_hours":
                (elapsed / derived * st["pending"] / 3600) if derived else 0,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    for k, v in dry_run(n).items():
        print(f"{k:32s} {v}")
