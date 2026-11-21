"""Stats: the metadata stats (/stats) and the deep stats mined from the
player's own replays (/deep/*), including each stat's rank mapping against the
bundled baseline packs. Routes attach to nucleome_bp (tracker/routes/nucleome.py).
"""
from flask import jsonify, request

from tracker.routes.nucleome import _day_arg, nucleome_bp
from tracker.stats import aggregate, baseline_ranks, deep_stats
from tracker.store import indexer
from tracker.store.identity import user_codes as _user_codes


@nucleome_bp.route("/deep/start", methods=["POST"])
def deep_start():
    """Start deep-mining the user's own replays for one character (external
    id in the JSON body) or all characters: a ``deep_stats`` job. 409 if one
    is running."""
    body = request.get_json(silent=True) or {}
    character = body.get("character")
    if character is not None:
        try:
            character = int(character)
        except (TypeError, ValueError):
            return jsonify({"error": "character must be an external char id"}), 400
    result = deep_stats.start_mining(character)
    if not result.get("started"):
        return jsonify(result), 409
    return jsonify(result)


@nucleome_bp.route("/deep/status", methods=["GET"])
def deep_status():
    """Per-character coverage (?character=<ext id>); the running job is its
    record. secs_per_game is the rate MEASURED on this machine (for honest ETAs)."""
    out = {}
    char = request.args.get("character")
    conn = indexer.connect()
    try:
        out["secs_per_game"] = deep_stats.secs_per_game(conn)
        if char not in (None, ""):
            try:
                char_id = int(char)
            except ValueError:
                return jsonify({"error": "bad character id"}), 400
            out["coverage"] = deep_stats.char_status(conn, char_id)
    finally:
        conn.close()
    return jsonify(out)


@nucleome_bp.route("/deep/pack", methods=["GET"])
def deep_pack():
    """The player's aggregated deep-stats pack for ?character=<ext id>
    (same shape as the baseline packs), 404 until something is mined."""
    try:
        char_id = int(request.args.get("character", ""))
    except ValueError:
        return jsonify({"error": "character (external id) is required"}), 400
    pack = deep_stats.build_player_pack(char_id)
    if pack is None:
        conn = indexer.connect()
        try:
            coverage = deep_stats.char_status(conn, char_id)
        finally:
            conn.close()
        return jsonify({"error": "no deep stats mined for this character yet",
                        "coverage": coverage}), 404
    return jsonify(pack)


@nucleome_bp.route("/deep/baselines", methods=["GET"])
def deep_baselines():
    """Per-stat rank-mapping for ?character=<ext id>: each of the player's
    metrics mapped to the tier its value looks like, with a signal score for
    how cleanly that stat separates the tiers. 404 until deep stats are mined."""
    try:
        char_id = int(request.args.get("character", ""))
    except ValueError:
        return jsonify({"error": "character (external id) is required"}), 400
    data = baseline_ranks.baseline_ranking(char_id)
    if data is None:
        return jsonify({"error": "no deep stats mined for this character yet"}), 404
    return jsonify(data)


@nucleome_bp.route("/stats", methods=["GET"])
def get_stats():
    """Tier-1 (metadata-only) stats for the Stats tab. ?my_char filters
    every section to games where the user played that external char id;
    ?start/?end (YYYY-MM-DD, inclusive) bound every section to a period."""
    my_char = request.args.get("my_char")
    conn = indexer.connect()
    try:
        return jsonify(aggregate.compute_stats(
            conn, _user_codes(conn),
            my_char=int(my_char) if my_char not in (None, "") else None,
            start=_day_arg("start"), end=_day_arg("end")))
    except ValueError:
        return jsonify({"error": "bad my_char/start/end filter"}), 400
    finally:
        conn.close()
