"""Slippi ranks: ranked profiles for a batch of connect codes (Replays rows)
and the player's season-by-season rank history (Stats).
Routes attach to nucleome_bp (tracker/routes/nucleome.py).
"""
from flask import jsonify, request

from tracker.routes.nucleome import nucleome_bp
from tracker.store import indexer, slippi_rank
from tracker.store.identity import user_codes as _user_codes


@nucleome_bp.route("/ranks", methods=["POST"])
def get_ranks():
    """Slippi ranked profiles for a batch of connect codes (cached 24h).
    Body: {codes: ["ABC#123", ...]} -> {"ABC#123": {tier, rating, ...}}"""
    codes = (request.get_json(silent=True) or {}).get("codes")
    if not isinstance(codes, list):
        return jsonify({"error": "codes must be a list"}), 400
    return jsonify(slippi_rank.get_ranks(codes[:50]))


@nucleome_bp.route("/rank-history", methods=["GET"])
def rank_history():
    """Season-by-season ranked history for the user's claimed codes (each
    past season's final rating + the live current-season rating; cached 24h)."""
    conn = indexer.connect()
    try:
        codes = _user_codes(conn)
    finally:
        conn.close()
    return jsonify(slippi_rank.get_rank_history(codes))
