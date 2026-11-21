"""Upload deterministic gzipped replays through caller-supplied transports.

The server chooses object keys. Only acknowledged uploads enter the local
ledger; a missing drive never schedules remote deletion. See raw-slp-vault.md.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import gzip
import io
import json
import logging
import os
import shutil
import threading
import time

from ..store.slp_meta import parse_slp
from .vault_sync import (
    QUOTA_SLICE_S, QUOTA_WAIT_S, SyncCancelled, _is_quota_error,
    content_hash, ensure_schema,
)

logger = logging.getLogger(__name__)
RAW_CODEC = "gz1"
CONV_CODEC = "json-gz1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_raw (
    game_id      INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    codec        TEXT NOT NULL,
    bytes        INTEGER NOT NULL,
    pushed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_vault_raw_hash ON vault_raw(content_hash);
CREATE TABLE IF NOT EXISTS vault_raw_conv (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    codec TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    pushed_at TEXT NOT NULL
);
-- Kept separate so the original raw ledger's row shape stays compatible.
-- Acknowledgements belong to the account, unlike the local combo scan marker.
CREATE TABLE IF NOT EXISTS vault_raw_combos (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    codec TEXT NOT NULL,
    combos_at REAL NOT NULL,
    frame_basis TEXT NOT NULL,
    committed_at TEXT NOT NULL
);
-- Separate from vault_skips: its game_id primary key cannot retain both a
-- frame-derivation refusal and a raw-header refusal for the same replay.
CREATE TABLE IF NOT EXISTS vault_raw_skips (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    codec   TEXT NOT NULL,
    mtime   REAL,
    size    INTEGER,
    reason  TEXT,
    at      TEXT
);
"""

_ensured_paths = set()
_ensure_lock = threading.Lock()
_PHASES = ("hash", "compress", "mint", "put", "commit", "quota_wait")


class RawUploadError(RuntimeError):
    """Fatal mint safety refusal: never retry or turn into per-game failures."""


def ensure_raw_schema(conn):
    """Initialize local ledgers once per on-disk database, like vault_sync."""
    ensure_schema(conn)  # owns the shared vault_hashes cache
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
        if path:  # each in-memory connection is a different database
            _ensured_paths.add(path)


def compress_slp(path):
    """gz1: gzip level 6, zero mtime and no filename, independent of path."""
    out = io.BytesIO()
    with open(path, "rb") as source:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out,
                           compresslevel=6, mtime=0) as dest:
            shutil.copyfileobj(source, dest, length=1 << 20)
    return out.getvalue()


def gzip_json(value):
    """Compact JSON, gzip-6, no filename or timestamp (json-gz1)."""
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out,
                       compresslevel=6, mtime=0) as dest:
        dest.write(json.dumps(value, separators=(",", ":"), allow_nan=False).encode())
    return out.getvalue()


def build_conversions(path):
    """Exactly /lite/conversions: actor indices 0/1, TRUE Slippi frames."""
    from ..store.game_trace import load_trace
    from ..video.interactions import detect_conversions
    trace = load_trace(path)
    if trace is None:
        raise ValueError("could not frame-parse this replay")
    if len(trace.data) != 2:
        return None
    return gzip_json({str(port): detect_conversions(trace, port) for port in (0, 1)})


def plan_conversions(conn, limit=None, newest_first=True, game_ids=None):
    ensure_raw_schema(conn)
    sql = """
        SELECT v.game_id, v.content_hash, g.path
          FROM vault_raw v JOIN games g ON g.id=v.game_id
          LEFT JOIN vault_raw_conv c ON c.game_id=v.game_id
         WHERE v.codec=? AND v.pushed_at IS NOT NULL
           AND (SELECT COUNT(*) FROM game_players p WHERE p.game_id=g.id)=2
           AND (c.game_id IS NULL OR c.content_hash!=v.content_hash OR c.codec!=?)
    """
    params = [RAW_CODEC, CONV_CODEC]
    if game_ids:
        ids = [int(g) for g in game_ids]
        sql += f" AND g.id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    sql += " ORDER BY g.start_at " + ("DESC" if newest_first else "ASC")
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def push_conversions(conn, items, mint_urls, put, commit, on_progress=None,
                     batch=50, should_cancel=None):
    """Slow, deferrable sidecar pass. Only server-acknowledged hashes settle.

    No frames, raw-artifact or combo fields are sent by this pass. Failed files
    and unacknowledged commits remain pending for the next autorun.
    """
    def check():
        if should_cancel and should_cancel():
            raise SyncCancelled("vault conversions cancelled")

    check()
    ensure_raw_schema(conn)
    groups = {}
    for item in items:
        groups.setdefault(item["content_hash"], []).append(item)
    groups = list(groups.values())
    pushed, skipped, failed = 0, 0, []
    for i in range(0, len(groups), max(1, batch)):
        pending = []
        for group in groups[i:i + max(1, batch)]:
            check()
            item = group[0]
            try:
                stat = os.stat(item["path"])
                sha = content_hash(conn, item["path"], stat.st_mtime, stat.st_size)
                if sha != item["content_hash"]:
                    raise ValueError("local replay differs from uploaded raw game")
                check()
                body = build_conversions(item["path"])
                check()
                if not _same_file(stat, os.stat(item["path"])):
                    raise ValueError("replay changed during conversion parse")
                if body is None:
                    skipped += len(group)
                    continue
                pending.append((group, body))
            except SyncCancelled:
                raise
            except FileNotFoundError:
                skipped += len(group)
            except Exception as e:
                failed.extend((r["game_id"], str(e)) for r in group)
        conn.commit()  # release hash-cache writes before transport
        if not pending:
            continue
        check()
        payload = [{"content_hash": group[0]["content_hash"], "bytes": len(body),
                    "codec": CONV_CODEC} for group, body in pending]
        urls = mint_urls(payload)  # transport must guard the echoed kind
        uploaded = []
        for group, body in pending:
            check()
            sha = group[0]["content_hash"]
            try:
                if not urls.get(sha):
                    raise ValueError("no conversion URL minted")
                put(urls[sha], body)
                check()
                uploaded.append((group, body))
            except SyncCancelled:
                raise
            except Exception as e:
                failed.extend((r["game_id"], str(e)) for r in group)
        check()
        accepted = set(commit([{"content_hash": group[0]["content_hash"],
                                "conv_bytes": len(body)} for group, body in uploaded])) if uploaded else set()
        check()  # account replacement during PUT/commit must not ledger
        with conn:
            for group, body in uploaded:
                if group[0]["content_hash"] not in accepted:
                    failed.extend((r["game_id"], "commit not acknowledged") for r in group)
                    continue
                for row in group:
                    conn.execute(
                        "INSERT INTO vault_raw_conv VALUES(?,?,?,?,?) "
                        "ON CONFLICT(game_id) DO UPDATE SET content_hash=excluded.content_hash, "
                        "codec=excluded.codec, bytes=excluded.bytes, pushed_at=excluded.pushed_at",
                        (row["game_id"], row["content_hash"], CONV_CODEC, len(body),
                         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                    pushed += 1
        if on_progress:
            on_progress(pushed + skipped + len(failed), len(items))
    return {"pushed": pushed, "skipped": skipped, "failed": failed}


def plan_raw(conn, limit=None, newest_first=True, game_ids=None):
    """Mirror plan()'s indexed-game selection, using the raw codec ledger.

    Frame uploads/refusals do not settle raw uploads. As in vault_sync.plan,
    parse_ok is the eligibility filter, and undated games sort last in DESC.
    Refusals are retried after the index observes a changed mtime or size.
    """
    ensure_raw_schema(conn)
    order = "DESC" if newest_first else "ASC"
    sql = f"""
        SELECT g.id, g.path, g.mtime, g.size, g.duration_s
          FROM games g
          LEFT JOIN vault_raw v ON v.game_id = g.id AND v.codec = ?
         WHERE g.parse_ok = 1 AND v.game_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM vault_raw_skips s
                            WHERE s.game_id = g.id AND s.codec = ?
                              AND s.mtime IS g.mtime AND s.size IS g.size)
    """
    params = [RAW_CODEC, RAW_CODEC]
    if game_ids:
        ids = [int(g) for g in game_ids]
        sql += f" AND g.id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    sql += f" ORDER BY g.start_at {order}"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(id=r[0], path=r[1], mtime=r[2], size=r[3], duration_s=r[4])
            for r in conn.execute(sql, params)]


@dataclass
class _Compressed:
    body: bytes | None = None
    stat: os.stat_result | None = None
    refusal: str | None = None
    error: Exception | None = None
    seconds: float = 0.0


def _compress_checked(path, check_cancelled):
    """No database access in workers; the cheap header reader gates gzip."""
    result = _Compressed()
    started = time.perf_counter()
    try:
        check_cancelled()
        result.stat = os.stat(path)
        try:
            meta = parse_slp(path)
            if not meta or len(meta.get("players") or []) < 2:
                result.refusal = "header refused: fewer than 2 players"
        except (FileNotFoundError, SyncCancelled):
            raise
        except Exception as e:  # corrupt/truncated headers must not abort sync
            result.refusal = f"header refused: {e}"
        check_cancelled()
        if result.refusal is None:
            result.body = compress_slp(path)
    except SyncCancelled:
        raise
    except Exception as e:
        result.error = e
    finally:
        result.seconds = time.perf_counter() - started
    return result


def _compress_ahead(items, workers, window, check_cancelled):
    """Bounded look-ahead in plan order; closing cancels queued compression."""
    pool = ThreadPoolExecutor(max_workers=workers,
                              thread_name_prefix="vault-raw-compress")
    pending = deque()
    source = iter(enumerate(items))
    exhausted = False
    try:
        while True:
            # The extra slot leaves a whole next batch in flight when the
            # current batch's final item is yielded, even with one worker.
            while not exhausted and len(pending) < max(window + 1, workers):
                check_cancelled()
                try:
                    i, item = next(source)
                except StopIteration:
                    exhausted = True
                    break
                pending.append((i, item, pool.submit(
                    _compress_checked, item["path"], check_cancelled)))
            if not pending:
                return
            i, item, job = pending.popleft()
            check_cancelled()
            yield i, item, job.result()
    finally:
        for _i, _item, job in pending:
            job.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


def _same_file(left, right):
    return (left.st_size, left.st_mtime_ns, left.st_ctime_ns) == (
        right.st_size, right.st_mtime_ns, right.st_ctime_ns)


def push_raw(conn, items, mint_urls, put, commit=None, on_progress=None,
             batch=100, should_cancel=None, compress_workers=4, put_workers=6,
             *, sleep=None):
    """Compress, mint, PUT, commit, then ledger only acknowledged hashes.

    mint_urls and commit receive {game_id, content_hash, bytes, codec} rows;
    neither receives an object key. The transport adapter adds kind="slp"
    to mint and maps commit rows to slp_bytes/slp_codec/meta (without combos).
    put(url, body) must be thread-safe. With commit=None, successful PUTs are
    acknowledged, matching vault_sync.push's transport-only mode.

    Each failed transport phase gets one quiet transient retry. Quota errors
    wait at most QUOTA_WAIT_S per phase, in cancellable slices. sleep(seconds)
    is injectable. Progress uses (done, total, pushed, skipped).

    Timings are seconds: compress sums header/gzip worker time (which can
    overlap); the other phases measure elapsed time on the calling thread.
    All SQLite access stays on that thread.
    """
    pushed = skipped = 0
    failed = []
    queue = []
    timings = dict.fromkeys(_PHASES, 0.0)
    batch_timings = dict(timings)
    batch_items = 0
    batch = max(1, int(batch))
    sleep = sleep or time.sleep

    def check_cancelled():
        if should_cancel and should_cancel():
            raise SyncCancelled("vault raw sync cancelled")

    def request(phase, call):
        retried = False
        waited = 0
        while True:
            check_cancelled()
            try:
                started = time.perf_counter()
                try:
                    return call()
                finally:
                    batch_timings[phase] += time.perf_counter() - started
            except SyncCancelled:
                raise
            except RawUploadError:
                raise
            except Exception as e:
                quota = _is_quota_error(e)
                if quota:
                    if waited >= QUOTA_WAIT_S:
                        raise
                    delay = min(QUOTA_SLICE_S, QUOTA_WAIT_S - waited)
                    waited += delay
                elif not retried:
                    retried = True
                    delay = 5
                else:
                    raise
                check_cancelled()
                started = time.perf_counter()
                try:
                    sleep(delay)
                finally:
                    if quota:
                        batch_timings["quota_wait"] += time.perf_counter() - started
                check_cancelled()

    def flush():
        nonlocal pushed, batch_items, batch_timings
        if not batch_items:
            return
        try:
            check_cancelled()
            # Release cache/skip writes before waiting on any network work.
            conn.commit()
            if not queue:
                return
            twins, unique = {}, []
            for game_id, sha, body in queue:
                if sha in twins:
                    twins[sha].append(game_id)
                else:
                    twins[sha] = []
                    unique.append((game_id, sha, body))

            def fail(game_id, sha, reason):
                failed.extend((g, reason) for g in (game_id, *twins[sha]))

            def row(game_id, sha, body):
                return {"game_id": game_id, "content_hash": sha,
                        "bytes": len(body), "codec": RAW_CODEC}

            payload = [row(*u) for u in unique]
            try:
                urls = request("mint", lambda: mint_urls(payload))
            except SyncCancelled:
                raise
            except RawUploadError:
                raise
            except Exception as e:
                failed.extend((g, f"mint failed: {e}") for g, _h, _b in queue)
                return
            check_cancelled()
            pending = []
            for game_id, sha, body in unique:
                url = urls.get(sha)
                if not url:
                    fail(game_id, sha, "no url minted")
                else:
                    pending.append((game_id, sha, body, url))

            def put_one(job):
                check_cancelled()
                try:
                    put(job[3], job[2])
                except SyncCancelled:
                    raise
                except Exception as e:
                    return job, e
                return job, None

            uploaded = {}
            errors = {}

            def put_pending():
                nonlocal pending
                outcomes = list(put_pool.map(put_one, pending))
                check_cancelled()
                pending = []
                errors.clear()
                for job, err in outcomes:
                    game_id, sha, body, _url = job
                    if err is None:
                        uploaded[sha] = row(game_id, sha, body)
                    else:
                        pending.append(job)
                        errors[sha] = err
                if errors:
                    # Retry only failed objects; one quota wait budget covers
                    # the concurrent PUT round, not one window per worker.
                    quota = next((e for e in errors.values() if _is_quota_error(e)), None)
                    raise quota if quota is not None else next(iter(errors.values()))

            if pending:
                try:
                    request("put", put_pending)
                except SyncCancelled:
                    raise
                except Exception:
                    for game_id, sha, _body, _url in pending:
                        fail(game_id, sha, f"put failed: {errors[sha]}")
            check_cancelled()
            # Preserve plan order even when some PUTs needed a retry.
            uploaded = [uploaded[h] for _g, h, _b in unique if h in uploaded]
            acknowledged = {u["content_hash"] for u in uploaded}
            if commit and uploaded:
                try:
                    acknowledged = request("commit", lambda: set(commit(uploaded)))
                except SyncCancelled:
                    raise
                except Exception as e:
                    for u in uploaded:
                        fail(u["game_id"], u["content_hash"], f"commit failed: {e}")
                    return
            # A credential may have changed during the remote acknowledgement.
            check_cancelled()
            for u in uploaded:
                sha = u["content_hash"]
                if sha not in acknowledged:
                    fail(u["game_id"], sha, "commit not acknowledged")
                    continue
                for game_id in (u["game_id"], *twins[sha]):
                    conn.execute(
                        "INSERT INTO vault_raw(game_id, content_hash, codec, bytes, "
                        "pushed_at) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(game_id) DO UPDATE SET "
                        "content_hash=excluded.content_hash, codec=excluded.codec, "
                        "bytes=excluded.bytes, pushed_at=excluded.pushed_at",
                        (game_id, sha, RAW_CODEC, u["bytes"],
                         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                    pushed += 1
            conn.commit()
        finally:
            for phase in _PHASES:
                timings[phase] += batch_timings[phase]
            logger.info("vault raw batch: items=%d %s", batch_items,
                        " ".join(f"{p}={batch_timings[p]:.3f}s" for p in _PHASES))
            queue.clear()
            batch_items = 0
            batch_timings = dict.fromkeys(_PHASES, 0.0)

    check_cancelled()
    ensure_raw_schema(conn)
    put_pool = ThreadPoolExecutor(max_workers=max(1, int(put_workers or 1)),
                                  thread_name_prefix="vault-raw-put")
    compressed = _compress_ahead(items, max(1, int(compress_workers or 1)),
                                 batch, check_cancelled)
    try:
        for i, item, result in compressed:
            check_cancelled()
            batch_items += 1
            batch_timings["compress"] += result.seconds
            if isinstance(result.error, FileNotFoundError):
                skipped += 1  # vanished files are never refusal-ledgered
            elif result.error is not None:
                failed.append((item["id"], f"compress failed: {result.error}"))
            else:
                try:
                    if not _same_file(result.stat, os.stat(item["path"])):
                        raise OSError("file changed during compression")
                    if result.refusal is not None:
                        conn.execute(
                            "INSERT INTO vault_raw_skips(game_id, codec, mtime, size, "
                            "reason, at) VALUES(?,?,?,?,?,?) "
                            "ON CONFLICT(game_id) DO UPDATE SET codec=excluded.codec, "
                            "mtime=excluded.mtime, size=excluded.size, "
                            "reason=excluded.reason, at=excluded.at",
                            (item["id"], RAW_CODEC, result.stat.st_mtime,
                             result.stat.st_size, result.refusal,
                             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                        conn.commit()  # preserve refusals even if a later batch is cancelled
                        skipped += 1
                    else:
                        check_cancelled()
                        started = time.perf_counter()
                        try:
                            sha = content_hash(conn, item["path"],
                                               result.stat.st_mtime, result.stat.st_size)
                        finally:
                            batch_timings["hash"] += time.perf_counter() - started
                        if not _same_file(result.stat, os.stat(item["path"])):
                            raise OSError("file changed during hashing")
                        check_cancelled()
                        queue.append((item["id"], sha, result.body))
                except FileNotFoundError:
                    skipped += 1
                except OSError as e:
                    failed.append((item["id"], f"hash failed: {e}"))
            if len(queue) >= batch:
                flush()
            if on_progress:
                on_progress(i + 1, len(items), pushed, skipped)
        tail = bool(queue)
        flush()
        check_cancelled()
        conn.commit()
        if tail and on_progress:
            on_progress(len(items), len(items), pushed, skipped)
    finally:
        compressed.close()
        put_pool.shutdown(wait=True, cancel_futures=True)
    return {"pushed": pushed, "skipped": skipped, "failed": failed,
            "timings": timings}
