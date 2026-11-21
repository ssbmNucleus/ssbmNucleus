"""Share: the permanent public link for a game or one of its combos (uploading
that one game on demand, on any tier) and the link's unfurl thumbnail.
Routes attach to nucleome_bp (tracker/routes/nucleome.py) and carry its vault gate.
"""
import sqlite3

from flask import jsonify, request

from tracker.cloud import vault_client, vault_sync
from tracker.routes.nucleome import _requires_vault, _stored_token, _token_or_error, nucleome_bp
from tracker.share.links import _combo_ordinal
from tracker.store import indexer


@nucleome_bp.route("/share", methods=["POST"])
@_requires_vault
def share_link():
    """The permanent public URL for a game — or one of its combos — minted on
    first use (idempotent server-side, same as the phone's share).

    Body: {game_id, combo_id?}. If the game is not in the vault yet this
    UPLOADS IT FIRST, rather than the old 409. Library-wide sync is a paid
    feature now (it only pays off on the phone), so on the free tier this is
    the only thing that ever puts a replay in the vault: you share a game,
    that game goes up, nothing else does. The share id still resolves against
    the vault's copy, so the upload is not optional — it is what makes the
    link exist.
    """
    body = request.get_json(silent=True) or {}
    try:
        game_id = int(body["game_id"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "game_id (integer) is required"}), 400
    combo_id = body.get("combo_id")
    if combo_id is not None:
        try:
            combo_id = int(combo_id)
        except (TypeError, ValueError):
            return jsonify({"error": "combo_id must be an integer"}), 400

    token, err = _token_or_error()
    if err:
        return err

    raw_only = False

    def pushed_hash(conn):
        nonlocal raw_only
        for table in ("vault_objects", "vault_raw"):
            try:
                row = conn.execute(
                    f"SELECT content_hash FROM {table} "
                    "WHERE game_id = ? AND pushed_at IS NOT NULL",
                    (game_id,)).fetchone()
            except sqlite3.OperationalError:
                continue
            if row:
                raw_only = table == "vault_raw"
                return row["content_hash"]
        return None

    conn = indexer.connect()
    try:
        # Validate the requested local combo before uploading a replay. A short
        # sequence or a combo belonging to another game has no public ordinal.
        ordinal = None
        if combo_id is not None:
            ordinal = _combo_ordinal(conn, game_id, combo_id)
            if ordinal is None:
                return jsonify({"error": "This combo is unavailable for sharing. Public combo links require at least four moves."}), 404
        content_hash = pushed_hash(conn)
        if content_hash is None:
            # Upload just this game. Same push path as a full sync, narrowed
            # to one id, on the caller's thread: the viewer is sitting on a
            # spinner waiting for a link, so there is nothing to hand a
            # background job. It stops before settling anything once the
            # account changes, or account A's upload would land in B's
            # ledger (F-E-7).
            try:
                vault_client.sync(token, conn=conn, game_ids=[game_id],
                                  should_cancel=lambda: _stored_token(conn) != token)
            except vault_sync.SyncCancelled:
                return jsonify({"error": "Account changed while sharing. Please try again."}), 409
            except vault_client.VaultError as e:
                return jsonify({"error": str(e)}), 502
            content_hash = pushed_hash(conn)
        if content_hash is None:
            # plan() found nothing to do and there is still no pushed row:
            # the replay is unparsed, missing from disk, or the deriver
            # refused it (vault_skips). None of those are retryable here.
            return jsonify({"error": "this replay could not be prepared for "
                                     "sharing"}), 409
    finally:
        conn.close()

    try:
        if raw_only:
            conn = indexer.connect()
            try:
                minted = vault_client.mint_share(
                    token, content_hash,
                    should_cancel=lambda: _stored_token(conn) != token)
            finally:
                conn.close()
        else:
            minted = vault_client.mint_share(token, content_hash)
    except vault_sync.SyncCancelled:
        return jsonify({"error": "Account changed while sharing. Please try again."}), 409
    except vault_client.VaultError as e:
        return jsonify({"error": str(e)}), 502
    url = f"{vault_client.SHARE_SITE}/replay/{minted['id']}"
    if ordinal is not None:
        url += f"/combo/{ordinal}"
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        # Serialize the credential check and write against account replacement.
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if _stored_token(conn) != token:
                return jsonify({"error": "Account changed while sharing. Please try again."}), 409
            conn.execute(
                "INSERT OR IGNORE INTO vault_shared_links(url, game_id, shared_at, combo) "
                "VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'),?)",
                (url, game_id, ordinal))
    finally:
        conn.close()
    return jsonify({"id": minted["id"], "url": url, "combo": ordinal})


@nucleome_bp.route("/share/thumb", methods=["POST"])
@_requires_vault
def share_thumb():
    """Forward the client-drawn unfurl PNG for a share id.

    The viewer draws the thumbnail (it is where the stock icons meet a
    canvas); this route only lends it the stored app token, which must never
    reach the renderer. Fire-and-forget on the client — a lost picture never
    loses the link.
    """
    body = request.get_json(silent=True) or {}
    share_id = body.get("id")
    png_b64 = body.get("png_b64")
    if not isinstance(share_id, str) or not isinstance(png_b64, str):
        return jsonify({"error": "id and png_b64 (strings) are required"}), 400
    token, err = _token_or_error()
    if err:
        return err
    try:
        vault_client.push_share_thumb(token, share_id, png_b64)
    except vault_client.VaultError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True})
