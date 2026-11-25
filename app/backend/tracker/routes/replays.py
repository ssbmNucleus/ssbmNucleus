"""Replays: identity (which connect codes are the player's), scanning the
replay folder, and the replay list (filters, month buckets, final stocks,
open in the Slippi Launcher, reveal the file).

A scan is a ``replay_scan`` job (core/jobs.py): POST /replays/scan starts one,
and the screen follows its record. Routes attach to nucleome_bp
(tracker/routes/nucleome.py).
"""
import os
import subprocess
import sys
import threading

from flask import jsonify, request

from core import jobs
from core.child_env import child_environment
from tracker.cloud import vault_client, vault_sync
from tracker.routes import nucleome
from tracker.routes.nucleome import _synced_game_ids, nucleome_bp
from tracker.store import identity, indexer
from tracker.store.games import _validate_indexed_path


# identity code helpers moved to tracker.store.identity so other
# blueprints (combo_video) can resolve "me" the same way
_seen_login_codes = identity.seen_login_codes
_user_codes = identity.user_codes


@nucleome_bp.route("/identity", methods=["GET"])
def get_identity():
    conn = indexer.connect()
    try:
        codes = _user_codes(conn)
        login_codes, active = _seen_login_codes(conn)
        accounts = identity.get_launcher_accounts()
        return jsonify({
            "netplay": identity.get_netplay_identity(),
            "launcher_accounts": accounts,
            "replay_root": identity.replay_root(conn),
            "user_codes": codes,
            # Slippi logins seen on this machine and not removed
            "login_codes": login_codes,
            "active_login_code": active,  # the only one locked in the UI
            # codes recovered by matching launcher account names against
            # in-game netplay names — "your other Slippi accounts"
            "account_suggestions": indexer.codes_for_account_names(
                conn, accounts, exclude_codes=codes),
            **indexer.alias_summary(conn, codes),
            "index": indexer.index_counts(conn),
        })
    finally:
        conn.close()


@nucleome_bp.route("/identity/codes", methods=["POST"])
def set_identity_codes():
    """Set the full list of codes that are "me". The active Slippi login
    always stays; a past login left out is forgotten until it is the active
    login again (identity.set_codes)."""
    codes = (request.get_json(silent=True) or {}).get("codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        return jsonify({"error": "codes must be a list of strings"}), 400
    conn = indexer.connect()
    try:
        _seen, active = _seen_login_codes(conn)
        before = identity.known_user_codes(conn)
        saved = identity.set_codes(conn, codes, active)
        vault_client.note_codes_edit(conn, before, saved)
        token = (nucleome._stored_token(conn)
                 if nucleome.VAULT_ENABLED and set(saved) != set(before) else None)
    finally:
        conn.close()
    if token:
        _publish_codes(token)
    return jsonify({"user_codes": saved})


def _publish_codes(token):
    """Reconcile the edited list with the cloud vault now, in the background,
    so the phone stops counting a removed code before the next sync. Offline
    is fine: the next sync merges the same edit (vault_client.sync_codes)."""
    def run():
        conn = indexer.connect()
        try:
            vault_client.sync_codes(conn, token)
        except Exception:                                     # noqa: BLE001
            pass
        finally:
            conn.close()

    threading.Thread(target=run, daemon=True, name="identity-codes-publish").start()


@nucleome_bp.route("/replays/scan", methods=["POST"])
def scan_replays():
    body = request.get_json(silent=True) or {}
    manual = (body.get("dir") or "").strip().strip('"')
    conn = indexer.connect()
    try:
        replay_dir = os.path.expanduser(manual) if manual else identity.replay_root(conn)
        if not replay_dir or not os.path.isdir(replay_dir):
            return jsonify({"error": f"replay directory not found: {replay_dir!r}"}), 400
        if manual:
            # remember the user's choice — identity + future rescans use it
            indexer.kv_set(conn, "replay_root_override", replay_dir)
    finally:
        conn.close()
    job_id = indexer.start_scan(replay_dir)
    if job_id is None:
        running = jobs.active_job(indexer.SCAN_KIND)
        return jsonify({"error": "a scan is already running",
                        "job_id": running.id if running else None}), 409
    return jsonify({"started": True, "job_id": job_id, "dir": replay_dir})


@nucleome_bp.route("/replays/status", methods=["GET"])
def index_status():
    """Index counts; a running scan is its job's record."""
    conn = indexer.connect()
    try:
        return jsonify({"index": indexer.index_counts(conn)})
    finally:
        conn.close()


def _result_arg():
    v = request.args.get("result")
    return v if v in ("win", "loss") else None


def _teams_arg():
    v = request.args.get("teams")
    return {"singles": 0, "doubles": 1}.get(v)  # None if unset/other


@nucleome_bp.route("/replays", methods=["GET"])
def list_replays():
    def _int_arg(name):
        v = request.args.get(name)
        return int(v) if v not in (None, "") else None

    conn = indexer.connect()
    try:
        result = indexer.query_games(
            conn,
            user_codes=_user_codes(conn),
            my_char=_int_arg("my_char"),
            opp_char=_int_arg("opp_char"),
            stage=_int_arg("stage"),
            opponent=request.args.get("opponent") or None,
            month=request.args.get("month") or None,
            result=_result_arg(),
            teams=_teams_arg(),
            limit=min(_int_arg("limit") or 50, 200),
            offset=_int_arg("offset") or 0,
        )
        # `synced` drives the row's share-link button: only a game already in
        # the cloud vault has a public page to link to.
        synced = _synced_game_ids(conn, [g["id"] for g in result["games"]])
        links = {}
        if nucleome.VAULT_ENABLED:
            vault_sync.ensure_schema(conn)
            ids = [g["id"] for g in result["games"]]
            if ids:
                marks = ",".join("?" for _ in ids)
                links = {r["game_id"]: r["url"].split("/combo/")[0] for r in conn.execute(
                    f"SELECT game_id, url FROM vault_shared_links WHERE game_id IN ({marks})", ids)}
        for g in result["games"]:
            g["share_url"] = links.get(g["id"])
            g["synced"] = g["id"] in synced
        return jsonify(result)
    except ValueError:
        return jsonify({"error": "bad numeric filter"}), 400
    finally:
        conn.close()


@nucleome_bp.route("/replays/facets", methods=["GET"])
def replay_facets():
    conn = indexer.connect()
    try:
        return jsonify(indexer.filter_facets(conn, _user_codes(conn)))
    finally:
        conn.close()


@nucleome_bp.route("/replays/months", methods=["GET"])
def replay_months():
    """[{ym, count}] month buckets for the collapsible list, honouring the
    active filters (same args as /replays minus paging)."""
    def _int_arg(name):
        v = request.args.get(name)
        return int(v) if v not in (None, "") else None

    conn = indexer.connect()
    try:
        return jsonify({"months": indexer.query_month_buckets(
            conn,
            user_codes=_user_codes(conn),
            my_char=_int_arg("my_char"),
            opp_char=_int_arg("opp_char"),
            stage=_int_arg("stage"),
            opponent=request.args.get("opponent") or None,
            result=_result_arg(),
            teams=_teams_arg(),
        )})
    except ValueError:
        return jsonify({"error": "bad numeric filter"}), 400
    finally:
        conn.close()


@nucleome_bp.route("/replays/watch", methods=["POST"])
def watch_replay():
    path = (request.get_json(silent=True) or {}).get("path")
    conn = indexer.connect()
    try:
        valid = _validate_indexed_path(conn, path)
    finally:
        conn.close()
    if not valid:
        return jsonify({"error": "unknown replay path"}), 404
    try:
        if sys.platform == "win32":
            os.startfile(valid)  # opens with the .slp handler (Slippi Launcher)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", valid], env=child_environment())
        else:
            subprocess.Popen(["xdg-open", valid], env=child_environment())
        return jsonify({"ok": True})
    except OSError as e:
        return jsonify({"error": str(e)}), 500


@nucleome_bp.route("/replays/stocks", methods=["POST"])
def get_stocks():
    """Final stock counts for a batch of games, for the row summary. Body:
    {game_ids: [..]} -> {game_id: {port: stocks}}. Read from each .slp's last
    frame (cheap) and cached in the kv store keyed by game id + file mtime."""
    from tracker.store.slp_meta import read_final_stocks
    ids = (request.get_json(silent=True) or {}).get("game_ids")
    if not isinstance(ids, list):
        return jsonify({"error": "game_ids must be a list"}), 400
    out = {}
    conn = indexer.connect()
    try:
        for gid in ids[:200]:
            row = conn.execute(
                "SELECT path FROM games WHERE id=? AND parse_ok=1", (gid,)).fetchone()
            if not row or not os.path.exists(row["path"]):
                continue
            try:
                mtime = int(os.path.getmtime(row["path"]))
            except OSError:
                continue
            ck = f"stocks:{gid}"
            cached = indexer.kv_get(conn, ck)
            if cached and cached.get("m") == mtime:
                out[str(gid)] = cached["s"]
                continue
            stocks = {str(p): s for p, s in read_final_stocks(row["path"]).items()}
            indexer.kv_set(conn, ck, {"m": mtime, "s": stocks})
            out[str(gid)] = stocks
    finally:
        conn.close()
    return jsonify(out)


@nucleome_bp.route("/replays/reveal", methods=["POST"])
def reveal_replay():
    path = (request.get_json(silent=True) or {}).get("path")
    conn = indexer.connect()
    try:
        valid = _validate_indexed_path(conn, path)
    finally:
        conn.close()
    if not valid:
        return jsonify({"error": "unknown replay path"}), 404
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(valid)], env=child_environment())
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(valid)], env=child_environment())
    return jsonify({"ok": True})
