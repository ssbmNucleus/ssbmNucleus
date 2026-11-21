"""Nucleus on your phone: the cloud vault's routes (status and activity, the
Patreon app token, launch settings, phone pairing and devices, the library push).
Routes attach to nucleome_bp (tracker/routes/nucleome.py) and carry its vault gate.
"""
import threading

from flask import jsonify, request

from core import jobs
from tracker.cloud import vault_client, vault_jobs, vault_sync
from tracker.routes.nucleome import _requires_vault, _stored_token, _token_or_error, nucleome_bp
from tracker.store import indexer


# --- Vault: pairing, launch settings, and the push -------------------------
# Transport is tracker/cloud/vault_client.py; the background jobs are
# vault_jobs. Nothing below holds a credential of its own: the desktop's Patreon
# app token lives in the kv and the edge functions resolve it server-side.


def _launch_flags(conn):
    return {
        "auto_scan": bool(indexer.kv_get(conn, vault_jobs.AUTO_SCAN_KEY, False)),
        "auto_sync": bool(indexer.kv_get(conn, vault_jobs.AUTO_SYNC_KEY, False)),
    }


@nucleome_bp.route("/vault/status", methods=["GET"])
@_requires_vault
def vault_status():
    """Everything the Vault panel renders in one request: whether it can talk
    to the vault at all, the launch settings and local counts. A running sync
    is its job (cloud_sync). Deliberately offline — a panel that opened by hitting the network
    would stall behind an unreachable vault."""
    conn = indexer.connect()
    try:
        # vault_objects is created by vault_sync, not by indexer.connect(), so
        # a machine that has never synced would fail the status() query here.
        vault_sync.ensure_schema(conn)
        counts = vault_sync.status(conn)
        return jsonify({
            "upload_history": [dict(r) for r in conn.execute(
                "SELECT substr(uploaded_at,1,10) AS day, MAX(uploaded_at) AS uploaded_at, "
                "SUM(games) AS games FROM vault_upload_history GROUP BY day ORDER BY day DESC LIMIT 30")]
                if _stored_token(conn) else [],
            "shared_links": [dict(r) for r in conn.execute(
                "SELECT s.*, g.start_at FROM vault_shared_links s LEFT JOIN games g ON g.id=s.game_id "
                "ORDER BY s.shared_at DESC LIMIT 100")] if _stored_token(conn) else [],
            "configured": bool(_stored_token(conn)),
            # What the AUTORUN will act on, which is the mirrored value, not
            # whatever the viewer's live entitlement check says this second.
            # Surfaced so the panel can explain a sync that will not start.
            "pledge_active": indexer.kv_get(conn, vault_jobs.PLEDGE_KEY, None),
            **_launch_flags(conn),
            "synced": counts["pushed"],
            "pending": counts["pending"],
            # games the deriver refuses (corrupt / solo training) — counted so
            # "pending" means real upcoming work, not an eternal backlog
            "unsyncable": counts.get("skipped", 0),
            "last_sync_at": vault_jobs.last_sync_at(conn),
        })
    finally:
        conn.close()


@nucleome_bp.route("/vault/activity", methods=["GET"])
@_requires_vault
def vault_activity():
    token, err = _token_or_error()
    if err:
        return err
    try:
        activity = vault_client.account_activity(
            token, kind=request.args.get("kind"), cursor=request.args.get("cursor"),
            refresh=request.args.get("refresh") == "1")
    except ValueError:
        return jsonify({"error": "Invalid activity page."}), 400
    except (vault_client.VaultError, OSError):
        return jsonify({"error": "Could not load cloud activity. Try again."}), 502
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if _stored_token(conn) != token:
                return jsonify({"error": "Account changed. Refresh cloud activity."}), 409
            for link in activity["shared_links"]:
                # Backfill badges only for confirmed local mappings for this account.
                row = conn.execute("SELECT game_id FROM vault_objects WHERE content_hash=?",
                                   (link["content_hash"],)).fetchone()
                if row:
                    conn.execute("INSERT OR IGNORE INTO vault_shared_links(url,game_id,shared_at,combo) "
                                 "VALUES(?,?,?,NULL)", (link["url"], row["game_id"], ""))
        return jsonify(activity)
    finally:
        conn.close()


# One credential change at a time. The handler checks a new token with the
# vault before storing it, so without this an older request still checking
# could store its token after a newer sign-out had cleared it (F-E-6).
_token_lock = threading.Lock()


@nucleome_bp.route("/vault/token", methods=["POST"])
@_requires_vault
def vault_token():
    """Store (or clear, with token=null) the desktop's Patreon app token.

    It lives in the kv rather than in the frontend because the launch autorun
    runs before any window exists. The response never echoes it back: this is
    the credential for the user's entire library, and a value returned here
    would end up in devtools, a screenshot, or a bug report.

    Body may also carry {active} — whether the linked Patreon has a live
    pledge. Only the viewer knows that (it holds the entitlement check), and
    the autorun needs it to decide whether background sync is allowed at all.
    Omitting it leaves the stored value alone rather than assuming a lapse.

    The pledge turning paid for the first time on this install switches
    automatic processing and upload on (each only if the user never set it)
    and starts the chain now, so paying is the last step: the library heads
    for the phone without a trip to the toggles. A pledge that comes back
    after a lapse starts the chain too, but the toggles stay as the user left
    them, and so do an existing payer's on the first launch of this build.
    A new token without {active} is stored as not paid until told.
    """
    body = request.get_json(silent=True) or {}
    token = body.get("token")
    if token is not None and not isinstance(token, str):
        return jsonify({"error": "token must be a string or null"}), 400
    token = (token or "").strip()
    active = body.get("active")
    if active is not None and not isinstance(active, bool):
        return jsonify({"error": "active must be a boolean or null"}), 400
    with _token_lock:
        return _store_token(token, active)


def _store_token(token, active):
    conn = indexer.connect()
    try:
        previous = _stored_token(conn)
        # Authenticate the exact replacement before persisting it. Status
        # cannot expose the secret for comparison, and accepting arbitrary
        # nonempty text would replace a working credential with one no vault
        # route can use. The stored token itself was checked when it was
        # stored, and the app re-sends it on every launch (vaultTokenMirror),
        # so re-checking it would turn an offline launch into a 502 for a
        # no-op.
        if token and token != previous:
            try:
                vault_client.list_devices(token)
            except vault_client.VaultError as e:
                message = str(e)
                auth_failure = any(word in message.lower() for word in
                                   ("invalid_token", "invalid token", "unauthorized"))
                return jsonify({"error": message}), 401 if auth_failure else 502
        changed = previous != (token or None)
        if changed:
            # Invalidate the running owner's generation before clearing its
            # cloud-derived ledger. A same-owner token rotation deliberately
            # pays the same safe reconciliation cost as an account switch.
            vault_jobs.cancel_sync()
            vault_jobs.clear_account_sync_state(conn)
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, token or None)
        kick = False
        if not token:
            # Signing out takes the pledge with it; leaving it true would let
            # the next token inherit a stranger's entitlement.
            indexer.kv_set(conn, vault_jobs.PLEDGE_KEY, None)
        elif changed and active is None:
            # A new account whose pledge has not been told yet is not paid
            # yet: keeping the previous account's value would let a free
            # account inherit a paid upload until the viewer catches up.
            indexer.kv_set(conn, vault_jobs.PLEDGE_KEY, False)
        elif active is not None:
            was_paid = indexer.kv_get(conn, vault_jobs.PLEDGE_KEY, None) is True
            indexer.kv_set(conn, vault_jobs.PLEDGE_KEY, active)
            if active:
                _paid_defaults(conn, apply=not was_paid)
            kick = active and (changed or not was_paid) and bool(
                indexer.kv_get(conn, vault_jobs.AUTO_SYNC_KEY, False))
    finally:
        conn.close()
    if kick:
        # The same chain the launch and the ten-minute loop run (index ->
        # combos -> upload), now or right after the pass in progress.
        vault_jobs.kick_autorun()
    return jsonify({"configured": bool(token)})


def _paid_defaults(conn, apply):
    """Once per install. `apply` (this is the pledge turning paid): both launch
    flags go on, each only if the user never set it, so an explicit off stays
    off. Otherwise (a payer already paid before this build): just record it,
    so their toggles stay exactly as they left them."""
    if indexer.kv_get(conn, vault_jobs.PAID_DEFAULTS_KEY, False):
        return
    if apply:
        for key in (vault_jobs.AUTO_SCAN_KEY, vault_jobs.AUTO_SYNC_KEY):
            if indexer.kv_get(conn, key, None) is None:
                indexer.kv_set(conn, key, True)
    indexer.kv_set(conn, vault_jobs.PAID_DEFAULTS_KEY, True)


@nucleome_bp.route("/vault/settings", methods=["GET", "POST"])
@_requires_vault
def vault_settings():
    """Get or set the two launch flags. Both default false — a fresh install
    must not index a library or reach the network unasked — until the first
    paid pledge switches them on (vault_token). A POST may carry either key
    alone; absent keys are left as they are."""
    conn = indexer.connect()
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            for field, key in (("auto_scan", vault_jobs.AUTO_SCAN_KEY),
                               ("auto_sync", vault_jobs.AUTO_SYNC_KEY)):
                if field in body:
                    indexer.kv_set(conn, key, bool(body[field]))
        return jsonify(_launch_flags(conn))
    finally:
        conn.close()


@nucleome_bp.route("/vault/pair", methods=["POST"])
@_requires_vault
def vault_pair():
    """Mint a device token for a phone.

    The response carries device_token and pair_url, and this is the ONLY time
    they exist anywhere — the vault stores just a hash. A token the UI fails to
    show (or the user fails to scan) is re-paired, never recovered, so nothing
    here should be treated as re-fetchable.
    """
    token, err = _token_or_error()
    if err:
        return err
    label = (request.get_json(silent=True) or {}).get("label") or "Phone"
    try:
        return jsonify(vault_client.pair_device(token, str(label)))
    except vault_client.VaultError as e:
        # a dead token or an offline vault is the remote's verdict, not a bug
        # in this process — 502 keeps it out of the crash reports
        return jsonify({"error": str(e)}), 502


@nucleome_bp.route("/vault/devices", methods=["GET"])
@_requires_vault
def vault_devices():
    token, err = _token_or_error()
    if err:
        return err
    try:
        return jsonify({"devices": vault_client.list_devices(token)})
    except vault_client.VaultError as e:
        return jsonify({"error": str(e)}), 502


@nucleome_bp.route("/vault/revoke", methods=["POST"])
@_requires_vault
def vault_revoke():
    token, err = _token_or_error()
    if err:
        return err
    try:
        device_id = int((request.get_json(silent=True) or {})["device_id"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "device_id (integer) is required"}), 400
    try:
        vault_client.revoke_device(token, device_id)
    except vault_client.VaultError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"revoked": device_id})


@nucleome_bp.route("/vault/sync", methods=["POST"])
@_requires_vault
def vault_start_sync():
    """Push everything not yet in the vault, as a ``cloud_sync`` job (its id
    comes back); a full first run is hours, so nothing about it can be awaited
    on the request.

    Paid: a whole-library push exists to feed the phone, and the phone is the
    $5 tier. Sharing one game still uploads that game (POST /share) on any
    tier. The viewer hides this button for free accounts; this is the check
    that means hiding it is not the only thing stopping it."""
    token, err = _token_or_error()
    if err:
        return err
    conn = indexer.connect()
    try:
        pledged = indexer.kv_get(conn, vault_jobs.PLEDGE_KEY, None)
    finally:
        conn.close()
    if pledged is False:
        return jsonify({"error": "pledge_required"}), 402
    job_id = vault_jobs.start_sync(token)
    if job_id is None:
        running = jobs.active_job(vault_jobs.SYNC_KIND)
        return jsonify({"error": "a sync is already running",
                        "job_id": running.id if running else None}), 409
    return jsonify({"started": True, "job_id": job_id})
