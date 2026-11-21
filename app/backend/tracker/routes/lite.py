"""Lite: renderable clips for the in-app 2D player, no Dolphin. A clip of an
indexed game (by frames, or by a tool-issued clip ref from Randall's chat); plus
the background fetch of the characters' animation geometry at backend start.
Routes attach to nucleome_bp (tracker/routes/nucleome.py).
"""
import gzip
import json
import logging
import os
import threading

from flask import Response, jsonify, request, send_file

from tracker.routes.nucleome import NUCLEOME_ENABLED, nucleome_bp
from tracker.store import indexer
from tracker.store.games import _game_row
from tracker.video.clip_refs import _recover_clip_window

logger = logging.getLogger(__name__)


def _ensure_anim_zips_bg():
    """Watch Lite's character geometry, fetched in the background at backend
    start when missing. First-run setup also downloads it, but EXISTING users
    (setup already complete) would otherwise stay in dot mode forever. Fast
    no-op once the zips exist; failures are silent (dots remain the
    fallback) and retried on the next backend start."""
    try:
        from tracker.video import anim_fetch
        anim_fetch.ensure_anim_zips()
    except Exception:
        logger.debug("Watch Lite anim zip fetch failed", exc_info=True)


if NUCLEOME_ENABLED:
    threading.Thread(target=_ensure_anim_zips_bg, daemon=True,
                     name="nucleome-anim-fetch").start()


# ---- Watch Lite: in-browser character clips (no Dolphin) --------------------
@nucleome_bp.route("/lite/charmaps", methods=["GET"])
def lite_charmaps():
    """Action->animation maps + state names, fetched once and cached by the
    frontend renderer."""
    from tracker.video import clip_render
    if not os.path.exists(clip_render.CHARMAPS_PATH):
        return jsonify({"error": "charmaps not available"}), 404
    return jsonify(clip_render.charmaps())


@nucleome_bp.route("/lite/slp/<int:game_id>", methods=["GET"])
def lite_slp(game_id):
    """Raw replay for the JS deriver. Only an indexed id can select a file."""
    conn = indexer.connect()
    try:
        row = _game_row(conn, game_id)
        if row is None or not os.path.isfile(row["path"]):
            return jsonify({"error": "game not found"}), 404
        path = os.path.abspath(row["path"])
    finally:
        conn.close()
    try:
        response = send_file(path, mimetype="application/octet-stream",
                             download_name=f"replay-{game_id}.slp", conditional=True)
    except FileNotFoundError:  # removed between the index lookup and opening
        return jsonify({"error": "game not found"}), 404
    response.cache_control.private = True
    return response


@nucleome_bp.route("/lite/clip-ref/<ref>/resolve", methods=["GET"])
def lite_clip_ref_resolve(ref):
    """Resolve a minted ref, preserving the legacy invalid-window safety net."""
    from tracker.store.game_trace import load_trace
    from tracker.video import clip_refs

    conn = indexer.connect()
    try:
        got = clip_refs.resolve(ref, conn=conn)
        if not got:
            return jsonify({"error": "unknown clip reference"}), 404
        game_id, start, end, _label = got
        row = _game_row(conn, game_id)
        if row is None or not os.path.isfile(row["path"]):
            return jsonify({"error": "game not found"}), 404
        trace = load_trace(row["path"])
        if trace is None or trace.n < 2:
            return jsonify({"error": "could not frame-parse this replay"}), 422
        first = trace.at(0).slippi_frame
        last = trace.at(trace.n - 1).slippi_frame
        if end <= start or start > last or end < first:
            snap = _recover_clip_window(conn, game_id)
            # Null bounds select the whole game, without the combo length cap.
            start, end = snap if snap else (None, None)
        return jsonify({"game_id": game_id, "start_frame": start, "end_frame": end})
    finally:
        conn.close()


_pack_cache = {}  # internal cid -> (JSON bytes, gzip bytes); at most 27 entries
_pack_lock = threading.Lock()


@nucleome_bp.route("/lite/pack/<int:cid>", methods=["GET"])
def lite_pack(cid):
    """Full character geometry, in the same shape as the mobile packs."""
    from tracker.video import clip_render

    if not 0 <= cid < len(clip_render._INT_TO_ZIP):
        return jsonify({"error": "character pack not found"}), 404
    with _pack_lock:
        packed = _pack_cache.get(cid)
        if packed is None:
            animations = clip_render._load_char(cid)
            if not animations:
                return jsonify({"error": "character pack not available"}), 404
            body = json.dumps(animations, separators=(",", ":")).encode("utf-8")
            packed = (body, gzip.compress(body, compresslevel=6, mtime=0))
            _pack_cache[cid] = packed
    use_gzip = request.accept_encodings["gzip"] > 0
    response = Response(packed[1 if use_gzip else 0], mimetype="application/json")
    if use_gzip:
        response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")
    response.cache_control.private = True
    response.cache_control.max_age = 86400
    response.add_etag()
    return response.make_conditional(request)


@nucleome_bp.route("/lite/conversions/<int:game_id>", methods=["GET"])
def lite_conversions(game_id):
    """Conversion sidecar (?conversions=1), in TRUE Slippi frame coordinates."""
    from tracker.store.game_trace import load_trace
    from tracker.video.interactions import detect_conversions

    conn = indexer.connect()
    try:
        row = _game_row(conn, game_id)
        if row is None or not os.path.isfile(row["path"]):
            return jsonify({"error": "game not found"}), 404
        players = conn.execute("SELECT COUNT(*) FROM game_players WHERE game_id=?",
                               (game_id,)).fetchone()[0]
        # load_trace deliberately refuses single-player files. They still have
        # an empty sidecar, just like doubles/FFA, rather than a parse error.
        if players != 2:
            return jsonify({})
        path = row["path"]
    finally:
        conn.close()
    trace = load_trace(path)
    if trace is None:
        return jsonify({"error": "could not frame-parse this replay"}), 422
    if len(trace.data) != 2:
        return jsonify({})
    return jsonify({str(port): detect_conversions(trace, port) for port in (0, 1)})


def _clip_response(game_id, start, end):
    """Build the {bundle, anim, available, recovered} payload for a clip window
    (Slippi frames; start/end may be None for the whole game). Shared by the
    frame-based and ref-based clip endpoints."""
    from tracker.video import clip_render
    from tracker.store.game_trace import load_trace
    from tracker.video.viz_export import build_clip_bundle, build_viz_bundle

    conn = indexer.connect()
    try:
        row = _game_row(conn, game_id)
        if row is None or not os.path.exists(row["path"]):
            return jsonify({"error": "game not found"}), 404
        trace = load_trace(row["path"])
        if trace is None:
            return jsonify({"error": "could not frame-parse this replay"}), 422

        recovered = False
        if start is not None and end is not None:
            first = trace.at(0).slippi_frame
            last = trace.at(trace.n - 1).slippi_frame
            # A window that ends before/starts after the game, or is inverted, is
            # bogus (hallucinated frames) — snap to the game's best real combo so
            # the clip isn't a single frozen frame.
            if end <= start or start > last or end < first:
                snap = _recover_clip_window(conn, game_id)
                if snap:
                    start, end, recovered = snap[0], snap[1], True
                else:
                    start = end = None            # no combos: fall back to whole game
            bundle = (build_clip_bundle(trace, start, end)
                      if start is not None else build_viz_bundle(trace))
        else:
            bundle = build_viz_bundle(trace)
    finally:
        conn.close()

    # Belt-and-suspenders: never serve a degenerate (unplayable) clip.
    if bundle["meta"]["n"] < 2:
        return jsonify({"error": "clip frames out of range for this game"}), 422

    available = clip_render.zips_available()
    anim = clip_render.anims_for_clip(bundle) if available else {}
    return jsonify({"bundle": bundle, "anim": anim, "available": available,
                    "recovered": recovered})


@nucleome_bp.route("/lite/clip/<int:game_id>", methods=["GET"])
def lite_clip(game_id):
    """A renderable clip: a (windowed) viz bundle + the exact animations it uses.
    ?start=&end= (Slippi frames) yields a padded combo window; omit for the whole
    game. Used by the Watch Lite buttons, which pass trustworthy frames from real
    DB rows. `available` is False when the animation geometry isn't installed."""
    start = request.args.get("start", type=int)
    end = request.args.get("end", type=int)
    return _clip_response(game_id, start, end)


@nucleome_bp.route("/lite/clip-ref/<ref>", methods=["GET"])
def lite_clip_ref(ref):
    """Resolve an opaque, tool-issued clip ref (see tracker.video.clip_refs)
    to its real window, then render it. Randall's inline chat clips use this:
    the model can only copy a ref it was handed, so a hallucinated token resolves
    to nothing (honest 404) instead of a wrong or frozen clip."""
    from tracker.video import clip_refs
    got = clip_refs.resolve(ref)
    if not got:
        return jsonify({"error": "unknown clip reference"}), 404
    game_id, start, end, _label = got
    return _clip_response(game_id, start, end)
