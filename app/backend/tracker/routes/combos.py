"""Combos: extract combos from the indexed games, and the filterable combo
browser. Routes attach to nucleome_bp (tracker/routes/nucleome.py).
"""
from flask import jsonify, request

from core import jobs
from tracker.cloud import vault_client
from tracker.combos import combo_index
from tracker.routes.nucleome import _day_arg, _synced_game_ids, nucleome_bp
from tracker.store import indexer
from tracker.store.identity import user_codes as _user_codes


@nucleome_bp.route("/combos/scan", methods=["POST"])
def scan_combos():
    """Extract combos from every indexed game that hasn't been analyzed yet
    (incremental — only new/changed files are re-read)."""
    conn = indexer.connect()  # ensure schema/migrations exist before the scan
    conn.close()
    job_id = combo_index.start_scan()
    if job_id is None:
        running = jobs.active_job(combo_index.SCAN_KIND)
        return jsonify({"error": "a combo scan is already running",
                        "job_id": running.id if running else None}), 409
    return jsonify({"started": True, "job_id": job_id})


@nucleome_bp.route("/combos/status", methods=["GET"])
def combos_status():
    """Combo counts; a running pass is its job's record."""
    conn = indexer.connect()
    try:
        return jsonify({"counts": combo_index.counts(conn)})
    finally:
        conn.close()


@nucleome_bp.route("/combos", methods=["GET"])
def list_combos():
    """Filterable combo browser. mine=me|vs picks direction (my combos vs
    combos done to me); char/opp_char are attacker/victim external ids;
    min_moves, min_damage, kills=1, min_start/max_start (percent), and
    kind=true|string (true combo vs the victim escaping between hits) narrow;
    sort=recent|damage|moves|start_percent|duration, direction=asc|desc."""
    def _int_arg(name):
        v = request.args.get(name)
        return int(v) if v not in (None, "") else None

    def _float_arg(name):
        v = request.args.get(name)
        return float(v) if v not in (None, "") else None

    conn = indexer.connect()
    try:
        result = combo_index.query_combos(
            conn,
            user_codes=_user_codes(conn),
            mine=request.args.get("mine") or None,
            char=_int_arg("char"),
            opp_char=_int_arg("opp_char"),
            stage=_int_arg("stage"),
            opponent=request.args.get("opponent") or None,
            min_moves=_int_arg("min_moves"),
            min_damage=_float_arg("min_damage"),
            kills=request.args.get("kills") == "1",
            min_start=_float_arg("min_start"),
            max_start=_float_arg("max_start"),
            kind=request.args.get("kind") or None,
            date_from=_day_arg("date_from"),
            date_to=_day_arg("date_to"),
            sort=request.args.get("sort") or "recent",
            direction=request.args.get("direction") or None,
            # cap generously: the pager asks for 50, "Play [N]" marathons can
            # ask for far more (see PLAYLIST_CLIP_CAP)
            limit=min(_int_arg("limit") or 50, 2000),
            offset=_int_arg("offset") or 0,
        )
        # `synced` = this combo already has a public /combo/N page: its game is
        # in the vault AND the combo clears the upload length rule (short ones
        # never leave the machine — see vault_client.MIN_UPLOAD_MOVES).
        #
        # `shareable` drops the "already uploaded" half. Sharing now uploads
        # the game on demand, so the only thing that can permanently deny a
        # combo a public page is the length rule. The share button keys on
        # this; keying it on `synced` would hide sharing from everyone who
        # doesn't sync their library, which is now everyone on the free tier.
        synced = _synced_game_ids(
            conn, {c["game"]["id"] for c in result["combos"]})
        for c in result["combos"]:
            worth = vault_client._worth_uploading(
                c["moves_list"], c["hits"], c["did_kill"])
            c["synced"] = c["game"]["id"] in synced and worth
            c["shareable"] = worth
        return jsonify(result)
    except ValueError:
        return jsonify({"error": "bad numeric filter"}), 400
    finally:
        conn.close()
