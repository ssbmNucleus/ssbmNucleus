"""vault_jobs — the background half of the cloud vault.

Two things a request handler cannot do: a full-library push runs for minutes to
hours, and the automatic index -> combos -> push chain has to happen without
any UI asking. Both are jobs (core/jobs.py), like the replay scan and the combo
pass, so the window follows all of them from the same job records.

The chain runs at launch AND on an interval for the life of the app: replays
land while Nucleus sits open behind Slippi, and a library that only updates on
restart is stale exactly when the user comes back to look at tonight's games.

Transport lives in vault_client; this only decides *when* it runs.
"""
import logging
import os
import threading
import time

from ..combos import combo_index
from ..store import identity, indexer
from ..store.pass_progress import PassProgress
from . import vault_client, vault_sync
from core import gates, jobs

logger = logging.getLogger(__name__)

# Read here as well as in tracker/routes/nucleome.py: the autorun never
# goes through a route, so a gate that only lived on the blueprint would still
# let a packaged build index and push at launch. electron/main.js sets
# NUCLEUS_VAULT=0 for packaged builds; dev keeps full access.
NUCLEOME_ENABLED = gates.enabled('nucleome')
VAULT_ENABLED = gates.enabled('vault')

# kv keys. auto_* default FALSE: a fresh install must not index a library or
# touch the network before the user has asked for either. The "_on_launch"
# names predate the open-app loop and are kept for stored settings — the flags
# now mean "automatically", at launch and on the interval below.
AUTO_SCAN_KEY = "auto_scan_on_launch"
AUTO_SYNC_KEY = "auto_sync_on_launch"
RAW_UPLOAD_KEY = vault_client.RAW_UPLOAD_KEY
TOKEN_KEY = "vault_app_token"
LAST_SYNC_KEY = "vault_last_sync_at"
# Mirrored from the viewer's Patreon entitlement alongside the token, because
# the backend has no way to ask on its own. Library-wide sync is the paid half
# of the vault -- it only pays off on the phone -- so a free account must not
# quietly upload a library in the background. Absent means "not yet told";
# only an explicit False disables, so an old install that has never mirrored
# keeps working until the viewer next opens Settings.
PLEDGE_KEY = "vault_pledge_active"
# Set once this install has seen a paid pledge and applied the paid defaults
# (routes/cloud.py vault_token): automatic processing and upload switch on,
# unless the user had already set them. Paying is the opt-in; after that the
# toggles are the user's, so turning upload off again sticks.
PAID_DEFAULTS_KEY = "vault_paid_defaults_applied"

_credential_generation = 0
_generation_lock = threading.Lock()

_ACCOUNT_STATE_KEYS = (
    LAST_SYNC_KEY,
    "combos_wire_refresh",
    "combos_wire_refresh_pos",
    # the code list agreed with the previous account's vault: against another
    # account's copy it would read every difference as a removal there
    vault_client.CODES_BASE_KEY,
)

# Both are jobs (core/jobs.py) the window's job store follows. They run every
# ten minutes under the loop and own nothing a restart must put back, so their
# records stay in memory.
SYNC_KIND = "cloud_sync"
AUTORUN_KIND = "cloud_autorun"
jobs.register_kind(SYNC_KIND, label="Cloud sync", keep=5)
jobs.register_kind(AUTORUN_KIND, label="Automatic processing", keep=5)

# How often the autorun checks whether the pass it is waiting on has ended.
_POLL_S = 2.0
# A pass still running after this long stops the chain (the autorun fails and
# says so) instead of counting as finished.
_WAIT_TIMEOUT_S = 6 * 3600


# --- sync -------------------------------------------------------------------

def _sync(job, token, generation, raw=None, fallback=True, combos_only=False):
    """One push, or the raw chain's metadata follow-up (``combos_only``).

    The result is this pass's own outcome: ``mode`` "upload" with pushed /
    skipped / failed, or "metadata" with committed / conversions / failed. A
    follow-up never carries the upload's totals, so an upload that failed
    keeps saying so on its own record (F-E-12).
    """
    # Opened inside the job, so a database that cannot open fails the sync
    # instead of leaving it running (F-E-8). sqlite3 connections are
    # single-thread by default, so the route's could not be handed over anyway.
    conn = indexer.connect()
    try:
        replaced = lambda: generation != _credential_generation
        should_cancel = lambda: replaced() or job.should_stop()
        # Refused before any work: the credential changed between the request
        # and this start (F-E-7), and the change already cleared the ledger.
        # Clearing again here could only wipe the new account's rows.
        if replaced() or indexer.kv_get(conn, TOKEN_KEY) != token:
            raise jobs.Cancelled()
        if raw is None:
            raw = vault_client.raw_upload_available(conn)
        progress = PassProgress(job, "games")

        def stage(name):
            def report(done, total, pushed=None, skipped=None):
                counts = {} if pushed is None else {"pushed": pushed, "skipped": skipped}
                progress.report(force=progress.counts.get("stage") != name, stage=name,
                                done=done, total=total, progress_at=time.time(), **counts)
            return report

        result = outcome = None
        if raw:
            try:
                if combos_only:
                    result = vault_client.commit_pending_combos(
                        token, on_progress=stage("combos"), conn=conn,
                        should_cancel=should_cancel)
                    # Playback is already available. Parsing conversions is
                    # last, and a failure retries independently next cycle.
                    conv = vault_client.commit_pending_conversions(
                        token, on_progress=stage("conversions"), conn=conn,
                        should_cancel=lambda: should_cancel()
                        or indexer.kv_get(conn, TOKEN_KEY) != token)
                    outcome = {"mode": "metadata",
                               "committed": result.get("refreshed", 0),
                               "conversions": conv.get("pushed", 0),
                               "failed": len(result.get("skipped") or [])
                               + len(conv.get("failed") or [])}
                else:
                    result = vault_client.sync_raw(
                        token, on_progress=stage("upload"), conn=conn,
                        should_cancel=should_cancel)
            except vault_client.RawUploadsUnsupported:
                logger.info("vault: server does not support raw uploads; "
                            "using frames for 24 hours")
                if not fallback or combos_only:
                    raise
        if result is None:
            if replaced():
                raise vault_sync.SyncCancelled("vault sync cancelled")
            raw = False
            result = vault_client.sync(
                token, on_progress=stage("upload"), on_reconcile=stage("reconcile"),
                conn=conn, should_cancel=should_cancel)
        if outcome is None:
            # a count, not the list: the per-game reasons are large and the
            # UI only ever renders "n failed"
            outcome = {"mode": "upload", "transport": "raw" if raw else "frames",
                       "pushed": result.get("pushed", 0),
                       "skipped": result.get("skipped", 0),
                       "failed": len(result.get("failed") or [])}
        if "timings" in result:
            outcome["timings"] = dict(result["timings"])
        if replaced():
            raise vault_sync.SyncCancelled("vault sync cancelled")
        indexer.kv_set(conn, LAST_SYNC_KEY,
                       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if replaced():
            raise vault_sync.SyncCancelled("vault sync cancelled")
        if outcome["failed"]:
            job.progress(detail=f"{outcome['failed']:,} failed")
        return outcome
    except vault_sync.SyncCancelled:
        # A credential change can race the narrow interval after a local
        # batch commit or last-sync write. Clear again while this is the only
        # sync: the next cannot start until this job has ended. A plain stop
        # keeps the ledger.
        if replaced():
            clear_account_sync_state(conn)
        raise jobs.Cancelled() from None
    finally:
        conn.close()


def start_sync(token, *, raw=None, fallback=True, combos_only=False):
    """Start a push as a ``cloud_sync`` job: its id, or None while one runs.

    Concurrent pushes would derive and upload the same pending games twice —
    harmless in the vault (content-hash keys) but hours of wasted CPU.

    The autorun defers an unsupported-server fallback until after combos, and
    runs its metadata follow-up as this same kind under the same credential
    generation.
    """
    generation = _credential_generation
    try:
        return jobs.start(
            SYNC_KIND,
            lambda job: _sync(job, token, generation, raw, fallback, combos_only),
            label="Cloud metadata" if combos_only else "Cloud sync",
            params={"mode": "metadata" if combos_only else "upload"},
            single=True, thread_name="nucleome-vault-sync")
    except jobs.JobBusy:
        return None


def cancel_sync():
    """Stop work holding a credential that has been cleared or replaced."""
    global _credential_generation
    with _generation_lock:
        _credential_generation += 1
    running = jobs.active_job(SYNC_KIND)
    if running is not None:
        jobs.cancel(running.id)


def clear_account_sync_state(conn):
    """Discard cloud-derived local state after any exact credential change.

    The raw bundle hashes remain cached locally. The new credential's first
    sync reconciles those hashes against its remote account and repopulates
    only matches that account actually owns.
    """
    vault_sync.ensure_schema(conn)
    # Keep ledger + every account-derived checkpoint as one SQLite change.
    # indexer.kv_del commits per call, so use SQL directly here.
    with conn:
        conn.execute("DELETE FROM vault_objects")
        conn.execute("DELETE FROM vault_upload_history")
        conn.execute("DELETE FROM vault_shared_links")
        # Do not initialize raw schemas on the default frames path. If raw
        # was used, neither its upload nor combo ledger may cross accounts.
        for table in ("vault_raw", "vault_raw_combos", "vault_raw_conv"):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table,)).fetchone():
                conn.execute(f"DELETE FROM {table}")
        conn.executemany("DELETE FROM kv WHERE key=?",
                         ((key,) for key in _ACCOUNT_STATE_KEYS))


def last_sync_at(conn):
    """When this machine last finished a push, ISO-8601 UTC or None.

    Falls back to the newest pushed_at row so a library synced from the
    `python -m tracker.cloud.vault_client` CLI (which predates this kv key)
    does not report "never synced".
    """
    stamp = indexer.kv_get(conn, LAST_SYNC_KEY)
    if stamp:
        return stamp
    try:
        row = conn.execute(
            "SELECT MAX(pushed_at) FROM vault_objects").fetchone()
    except Exception:                                         # noqa: BLE001
        return None
    return row[0] if row else None


# --- automatic processing (launch + open-app loop) --------------------------

_PASSES = (indexer.SCAN_KIND, combo_index.SCAN_KIND, SYNC_KIND, AUTORUN_KIND)


def _busy():
    """Whether a pass (scan, combos, sync) or a chain is running."""
    return any(jobs.active_job(kind) is not None for kind in _PASSES)


def _run_pass(job, phase, start, kind):
    """Start one pass (or join the one already running) and wait for it to
    end. Returns its final record, or None when there was nothing to wait on.
    A pass that outlives the wait limit fails the chain (F-E-10): it must
    never count as finished."""
    job.progress(detail=_PHASE_DETAIL[phase], phase=phase)
    pass_id = start()
    if pass_id is None:
        running = jobs.active_job(kind)
        pass_id = running.id if running is not None else None
    if pass_id is None:
        return None
    deadline = time.time() + _WAIT_TIMEOUT_S
    while time.time() < deadline:
        record = jobs.get(pass_id)
        if record is None or record["status"] in jobs.FINAL:
            return record
        time.sleep(_POLL_S)
    raise TimeoutError(f"{_PHASE_DETAIL[phase].rstrip('…')} was still running after "
                       f"{_WAIT_TIMEOUT_S // 3600} hours")


_PHASE_DETAIL = {
    "scan": "Finding new replays…",
    "combos": "Finding combos…",
    "sync": "Syncing to your cloud library…",
    "metadata": "Uploading combo details…",
    "refresh": "Refreshing combos in your cloud library…",
}


def _ended(record):
    """Whether a pass ended done (or there was none to wait on)."""
    return record is None or record["status"] == "done"


def _require_done(record, what):
    if not _ended(record):
        raise RuntimeError(f"{what} {record['status']}"
                           + (f": {record['error']}" if record.get("error") else ""))


# One chain at a time, whoever starts it (launch, the ten-minute loop, a
# first pledge): it is a single job. Two chains at once break the order the
# chain exists for: the second one's scan is refused while the first indexes,
# so it goes straight to combos and the upload. A start that finds a chain
# running asks for one more pass instead (kick_autorun), so a setting changed
# mid-chain still lands now rather than on the next cycle.
_rerun_requested = False


def _autorun(job, auto_scan, auto_sync, token, replay_dir):
    """Run the chain; then run it again, with fresh settings, for every
    kick_autorun that arrived meanwhile."""
    global _rerun_requested
    _rerun_requested = False
    _autorun_chain(job, auto_scan, auto_sync, token, replay_dir)
    while _rerun_requested:
        _rerun_requested = False
        auto_scan, auto_sync, token, replay_dir = _read_settings()
        if not (auto_scan or auto_sync):
            break
        _autorun_chain(job, auto_scan, auto_sync, token, replay_dir)
    job.progress(detail="", phase=None)


def _start_autorun(settings, inline=False):
    """Run the chain as a ``cloud_autorun`` job, on this thread when
    ``inline`` (the loop). Raises JobBusy while one runs."""
    fn = lambda job: _autorun(job, *settings)
    if inline:
        return jobs.run_inline(AUTORUN_KIND, fn, single=True)
    return jobs.start(AUTORUN_KIND, fn, single=True, thread_name="nucleome-autorun")


def kick_autorun():
    """Run the chain now (a first pledge just turned upload on), or once more
    right after the one in progress, whose settings were read before."""
    global _rerun_requested
    if jobs.active_job(AUTORUN_KIND) is not None:
        _rerun_requested = True
        return
    maybe_autostart()


def _autorun_chain(job, auto_scan, auto_sync, token, replay_dir):
    """Default: index -> combos -> frames -> wire-basis refresh, in order.

    The raw opt-in instead uploads before combos and commits their metadata
    afterward. A server capability backoff selects the default frames chain.

    The first three are a dependency chain, not a preference: combos read rows
    the index writes, and the push derives from both. Running them
    concurrently would push a library the combo pass has not annotated yet,
    so the push waits for combos to end done. A failed scan does not stop it:
    combos and the push work on what is indexed. The refresh goes last
    because it is the slow one: it re-commits metadata for every synced game,
    and after a sign-in clears the ledger that is the whole library (~30 min
    for 19k games, 2026-10-15). While it ran before the push, this thread sat
    in it and new games waited behind it.
    """
    generation = _credential_generation
    conn = indexer.connect()
    try:
        raw_requested = vault_client.raw_requested(conn)
        raw = vault_client.raw_upload_available(conn)
    finally:
        conn.close()
    if raw:
        _autorun_raw_chain(job, auto_scan, auto_sync, token, replay_dir, generation)
        return
    combos = None
    if auto_scan:
        if replay_dir and os.path.isdir(replay_dir):
            _run_pass(job, "scan", lambda: indexer.start_scan(replay_dir), indexer.SCAN_KIND)
        else:
            logger.info("nucleome autorun: no replay folder, skipping scan")
        combos = _run_pass(job, "combos", combo_index.start_scan, combo_index.SCAN_KIND)
    # The chain can spend hours indexing before it reaches the network.
    # Re-read the credential after those waits so sign-out cannot leave a
    # queued autorun holding the former account token.
    token_current = _token_current(token, generation)
    if auto_sync and token_current:
        _require_done(combos, "the combo pass")
        # Waited out -- or a manual Sync that got there first -- so the
        # refresh below never hits the vault alongside it. raw=False keeps
        # this cycle on frames even if the backoff expires during indexing;
        # the following refresh belongs to frames.
        _run_pass(job, "sync",
                  lambda: start_sync(token, raw=False) if raw_requested else start_sync(token),
                  SYNC_KIND)
    if token_current and generation == _credential_generation:
        _maybe_refresh_wire_basis(token, generation, job)


def _token_current(token, generation):
    conn = indexer.connect()
    try:
        return bool(token and generation == _credential_generation
                    and indexer.kv_get(conn, TOKEN_KEY) == token)
    finally:
        conn.close()


def _autorun_raw_chain(job, auto_scan, auto_sync, token, replay_dir, generation):
    """index -> raw upload -> combos -> raw metadata; fallback keeps frames order."""
    if auto_scan:
        if replay_dir and os.path.isdir(replay_dir):
            _run_pass(job, "scan", lambda: indexer.start_scan(replay_dir), indexer.SCAN_KIND)
        else:
            logger.info("nucleome autorun: no replay folder, skipping scan")
    if auto_sync and _token_current(token, generation):
        _run_pass(job, "sync", lambda: start_sync(token, raw=True, fallback=False), SYNC_KIND)
    combos = None
    if auto_scan:
        combos = _run_pass(job, "combos", combo_index.start_scan, combo_index.SCAN_KIND)
    # The combo pass may have taken hours, or the first mint may have reached
    # a legacy server. Re-read both credentials and the capability backoff.
    if not _token_current(token, generation):
        return
    conn = indexer.connect()
    try:
        raw = vault_client.raw_upload_available(conn)
    finally:
        conn.close()
    if auto_sync:
        if raw:
            _run_pass(job, "metadata",
                      lambda: start_sync(token, raw=True, fallback=False, combos_only=True),
                      SYNC_KIND)
        else:
            _require_done(combos, "the combo pass")
            _run_pass(job, "sync", lambda: start_sync(token, raw=False), SYNC_KIND)
    if not raw and _token_current(token, generation):
        _maybe_refresh_wire_basis(token, generation, job)


def _maybe_refresh_wire_basis(token, generation=None, job=None):
    """One-shot cloud repair after the row-basis re-extraction (combos.py
    "combos_frame_basis"): rows already synced keep their old true-frame
    combos in the cloud forever, because plan() only pushes what the current
    deriver lacks and a plain commit never revisits them. Once the local
    re-extraction has fully caught up (no pending games), re-commit
    metadata + combos for everything synced — an upsert, no uploads — and
    mark it done. Never raises; a failed run retries next cycle.

    The pass checkpoints per chunk (resume_key) so a retry continues where
    the last one died. Without that, every retry restarted all 18.5k games
    from row one — cycles of that hammered prod into statement timeouts on
    2026-08-23 (and, with vault-sync <v16's unchecked delete, duplicated
    combos). The checkpoint outlives app restarts; it is cleared when a
    pass completes. A pass that stopped at a game the vault did not
    acknowledge is not complete, so it is not marked done (F-E-1): the next
    cycle resumes at that game.
    """
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        if indexer.kv_get(conn, "combos_wire_refresh") == combo_index._FRAME_BASIS:
            return
        if indexer.kv_get(conn, "combos_frame_basis") != combo_index._FRAME_BASIS:
            return  # re-extraction not even queued yet
        if combo_index.counts(conn)["games_pending"] > 0:
            return  # still re-extracting; refresh would ship stale rows
        if not conn.execute(
                "SELECT 1 FROM vault_objects LIMIT 1").fetchone():
            indexer.kv_set(conn, "combos_wire_refresh", combo_index._FRAME_BASIS)
            conn.commit()
            return  # nothing synced yet — nothing to repair
        pos = indexer.kv_get(conn, "combos_wire_refresh_pos")
        logger.info("vault: one-shot combo wire-basis refresh starting%s",
                    f" (resuming after {pos[:12]}…)" if pos else "")
        if job is not None:
            job.progress(detail=_PHASE_DETAIL["refresh"], phase="refresh")
        if generation is None:
            generation = _credential_generation
        result = vault_client.refresh_meta(
            token, conn=conn, resume_key="combos_wire_refresh_pos",
            should_cancel=lambda: generation != _credential_generation)
        if generation != _credential_generation:
            raise vault_sync.SyncCancelled("vault metadata refresh cancelled")
        if not result.get("complete"):
            logger.warning("vault: wire-basis refresh stopped at a game the vault did "
                           "not acknowledge; it resumes there next cycle")
            return
        indexer.kv_set(conn, "combos_wire_refresh", combo_index._FRAME_BASIS)
        conn.commit()
        logger.info("vault: wire-basis refresh complete")
    except Exception:                                         # noqa: BLE001
        logger.warning("vault: wire-basis refresh failed; will retry",
                       exc_info=True)
    finally:
        conn.close()


def _read_settings():
    """(auto_scan, auto_sync, token, replay_dir), re-read on EVERY cycle so a
    toggle flipped mid-session takes effect without a restart. auto_sync is
    already token-gated: wanting a push with no credentials is a no.

    It is now pledge-gated too. auto_scan is NOT -- scanning is local work on
    the user's own replays and stays free; only the upload is paid."""
    conn = indexer.connect()
    try:
        auto_scan = bool(indexer.kv_get(conn, AUTO_SCAN_KEY, False))
        auto_sync = bool(indexer.kv_get(conn, AUTO_SYNC_KEY, False))
        token = indexer.kv_get(conn, TOKEN_KEY) or None
        pledged = indexer.kv_get(conn, PLEDGE_KEY, None)
        replay_dir = identity.replay_root(conn) if auto_scan else None
    finally:
        conn.close()
    blocked = None
    if auto_sync and not token:
        blocked = "no Patreon token has reached the backend"
    elif auto_sync and pledged is False:
        blocked = "the linked Patreon is marked as not pledged"
    _note_sync_blocked(blocked)
    return auto_scan, auto_sync and not blocked, token, replay_dir


# Last reason auto-sync was switched on but could not run, so the log says so
# once per change rather than every cycle. 2026-10-04..15 went eleven days
# without an upload and without one line in the log: the backend had lost
# its copy of the token, and the loop just indexed every ten minutes.
_blocked_reason = None


def _note_sync_blocked(reason):
    global _blocked_reason
    if reason == _blocked_reason:
        return
    if reason:
        logger.warning("vault autorun: auto-sync is on but %s; uploads paused",
                       reason)
    elif _blocked_reason:
        logger.info("vault autorun: auto-sync can run again")
    _blocked_reason = reason


# Between cycles of the open-app loop. Sets played behind an open Nucleus land
# every few minutes; ten keeps the library near-live without walking the
# replay folder on every game end. Each pass is incremental, so an idle cycle
# costs a directory walk and three no-op status checks.
_LOOP_INTERVAL_S = 10 * 60

_loop_lock = threading.Lock()
_loop_started = False


def _loop_cycle():
    """One tick of the open-app loop: re-read the flags, skip if nothing is
    wanted or a pass is still running, else run the chain. Returns whether the
    chain ran (tests; nothing branches on it)."""
    try:
        auto_scan, auto_sync, token, replay_dir = _read_settings()
    except Exception:                                         # noqa: BLE001
        logger.debug("nucleome autoloop: settings unreadable", exc_info=True)
        return False
    if not auto_scan and not auto_sync:
        return False
    # A pass still running means the previous cycle (or a manual Sync now) has
    # the machine; layering a second chain on top would double-derive.
    if _busy():
        return False
    try:
        _start_autorun((auto_scan, auto_sync, token, replay_dir), inline=True)
    except jobs.JobBusy:
        return False
    return True


def _loop_worker():
    while True:
        time.sleep(_LOOP_INTERVAL_S)
        _loop_cycle()


def _ensure_loop():
    """Start the open-app loop thread, exactly once per process. It runs even
    while both flags are off — each cycle re-reads them, which is what lets a
    toggle flipped in Settings take effect within a cycle, no restart."""
    global _loop_started
    with _loop_lock:
        if _loop_started:
            return
        _loop_started = True
    threading.Thread(target=_loop_worker, daemon=True,
                     name="nucleome-autoloop").start()


def maybe_autostart():
    """Start the automatic processing the user opted into: the launch chain
    now, and the open-app loop for as long as the backend lives.

    Called from app.py during startup, so it must neither raise nor block: a
    missing replay folder or a dead token costs an un-updated index, never a
    backend that fails to boot. Returns whether launch work was started (tests
    and logs; nothing branches on it).
    """
    if not (NUCLEOME_ENABLED and VAULT_ENABLED):
        return False
    # The loop first: it re-reads the settings every cycle, so a read that
    # fails now (storage not ready yet) is retried instead of costing the
    # whole session its automatic work.
    _ensure_loop()
    try:
        auto_scan, auto_sync, token, replay_dir = _read_settings()
    except Exception:                                         # noqa: BLE001
        logger.debug("nucleome autorun: settings unreadable", exc_info=True)
        return False

    if not auto_scan and not auto_sync:
        return False
    # Nothing should be running this early, but a backend restarted while a
    # previous process's work was in flight (or a test harness) must not get a
    # second chain layered on top of the first.
    if _busy():
        logger.info("nucleome autorun: a pass is already running, skipping")
        return False
    try:
        _start_autorun((auto_scan, auto_sync, token, replay_dir))
    except jobs.JobBusy:
        return False
    except Exception:                                         # noqa: BLE001
        logger.warning("nucleome autorun: could not start", exc_info=True)
        return False
    return True
