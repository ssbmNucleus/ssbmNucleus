"""Watch with mods: play a replay, or a playlist of games or combo clips, in
Dolphin dressed in Vault skins and a stage variant, optionally recorded; and
place, park, pop out or close the playback window.
Routes attach to nucleome_bp (tracker/routes/nucleome.py). Each watch is a
``replay_watch`` job (watch_mods.py): the window follows its record from the
job store (``GET /api/jobs``, the ``job`` event).
"""
import json
import os
import subprocess
import sys

from flask import jsonify, request, send_file

from core.metadata import load_metadata
from tracker.replays import dolphin_config, playback, recording, watch_mods
from tracker.replays.watch_options import (_resolve_clip_entries, _resolve_skin_costume,
                                           _resolve_stage_selection, _skins_for_fighter,
                                           _stage_mods_for)
from tracker.routes.nucleome import nucleome_bp
from tracker.store import indexer
from tracker.store.games import _fighter_name, _game_row


# The routes resolve it through this module name (tests patch it here).
_launcher_vanilla_iso = dolphin_config.launcher_vanilla_iso


def _start(*args, **kwargs):
    """Start the watch job: (job id, None), or (None, a 409 response) while
    playback is taken (the running watch's id rides along)."""
    try:
        return watch_mods.start_job(*args, **kwargs), None
    except watch_mods.Busy as busy:
        return None, (jsonify({"error": str(busy), "job_id": busy.job_id}), 409)


@nucleome_bp.route("/watch-mods/options/<int:game_id>", methods=["GET"])
def watch_mods_options(game_id):
    """Everything the 'Watch with mods' popup needs: who's in the replay
    (character + costume slot) and which vault skins could dress them."""
    conn = indexer.connect()
    try:
        row = _game_row(conn, game_id)
    finally:
        conn.close()
    if row is None:
        return jsonify({"error": "unknown game"}), 404
    players = json.loads(row["players"]) if row["players"] else []
    meta = load_metadata() or {}
    chars_meta = meta.get("characters") or {}
    out_players = []
    for p in players:
        fighter = _fighter_name(p.get("character"))
        out_players.append({**p, "fighter": fighter,
                            "skins": _skins_for_fighter(fighter, chars_meta)})
    return jsonify({
        "game_id": game_id,
        "stage": row["stage"],
        "players": out_players,
        "stage_mods": _stage_mods_for(row["stage"], meta),
        "vanilla_iso": _launcher_vanilla_iso(),
        "playback_ready": dolphin_config.playback_dolphin_path() is not None,
    })


@nucleome_bp.route("/watch-mods/start", methods=["POST"])
def watch_mods_start():
    body = request.get_json(silent=True) or {}
    game_id = body.get("game_id")
    raw_selections = body.get("selections") or []
    conn = indexer.connect()
    try:
        row = _game_row(conn, game_id)
    finally:
        conn.close()
    if row is None:
        return jsonify({"error": "unknown game"}), 404
    if not os.path.exists(row["path"]):
        return jsonify({"error": "replay file no longer exists"}), 404
    vanilla = body.get("isoPath") or _launcher_vanilla_iso()
    if not vanilla or not os.path.exists(vanilla):
        return jsonify({"error": "no vanilla ISO found (set one in the Slippi "
                                  "Launcher or app settings)"}), 400

    players = {p["port"]: p for p in json.loads(row["players"] or "[]")}
    meta = load_metadata() or {}
    chars_meta = meta.get("characters") or {}
    selections = []
    for sel in raw_selections:
        player = players.get(sel.get("port"))
        if not player:
            return jsonify({"error": f"no player on port {sel.get('port')}"}), 400
        fighter = _fighter_name(player.get("character"))
        costume_path, err = _resolve_skin_costume(fighter, sel.get("skin_id"), chars_meta)
        if err:
            return jsonify({"error": f"port {sel.get('port')}: {err}"}), 400
        selections.append({"fighter": fighter,
                           "slot": player.get("costume") or 0,
                           "costume_path": costume_path})

    stage_sel = None
    stage_skin_id = body.get("stage_skin_id")
    if stage_skin_id:
        stage_sel, err = _resolve_stage_selection(row["stage"], stage_skin_id, meta)
        if err:
            return jsonify({"error": err}), 400

    # optional clip (the Combos tab): play just [start_frame, end_frame],
    # padded with a short lead-in/out so the moment has context
    clip = None
    if body.get("start_frame") is not None and body.get("end_frame") is not None:
        try:
            clip = (max(-123, int(body["start_frame"]) - 60),
                    int(body["end_frame"]) + 90)
        except (TypeError, ValueError):
            return jsonify({"error": "bad start_frame/end_frame"}), 400

    # no selections at all = plain watch: skip the build, play the vanilla ISO
    record = bool(body.get("record"))
    compress = bool(body.get("compress"))
    anonymize = bool(body.get("anonymize"))
    widescreen = bool(body.get("widescreen"))
    no_music = bool(body.get("no_music"))
    job_id, busy = _start(row["path"], vanilla, selections,
                          stage=stage_sel, record=record, clip=clip,
                          compress=compress, anonymize=anonymize,
                          widescreen=widescreen, no_music=no_music)
    if busy:
        return busy
    return jsonify({"started": True, "job_id": job_id})


@nucleome_bp.route("/watch-mods/playlist-options", methods=["POST"])
def watch_mods_playlist_options():
    """Everything the playlist 'Watch with mods' popup needs: the UNION across
    the queue of every character (with the costume slots it appears at + vault
    skins) and every stage (with vault variants). One mod choice per
    character/stage dresses the whole playlist from a single stateless ISO."""
    body = request.get_json(silent=True) or {}
    conn = indexer.connect()
    try:
        rows, entries = _resolve_clip_entries(conn, body.get("clips") or [])
    finally:
        conn.close()
    meta = load_metadata() or {}
    chars_meta = meta.get("characters") or {}
    chars, stages = {}, {}
    for gid in {e["game_id"] for e in entries}:
        row = rows[gid]
        for p in json.loads(row["players"] or "[]"):
            cid = p.get("character")
            if cid is None:
                continue
            entry = chars.get(cid)
            if entry is None:
                fighter = _fighter_name(cid)
                entry = chars[cid] = {
                    "character": cid, "fighter": fighter, "costumes": set(),
                    "skins": _skins_for_fighter(fighter, chars_meta),
                }
            entry["costumes"].add(p.get("costume") or 0)
        sid = row["stage"]
        if sid not in stages:
            stages[sid] = {"stage": sid, "mods": _stage_mods_for(sid, meta)}
    # character rows sorted by ext id; costumes as a sorted list for a stable UI
    char_list = [{**c, "costumes": sorted(c["costumes"])}
                 for c in sorted(chars.values(), key=lambda c: c["character"])]
    return jsonify({
        "clip_count": len(entries),
        "characters": char_list,
        "stages": [stages[s] for s in sorted(stages)],
        "vanilla_iso": _launcher_vanilla_iso(),
        "playback_ready": dolphin_config.playback_dolphin_path() is not None,
    })


@nucleome_bp.route("/watch-mods/playlist-start", methods=["POST"])
def watch_mods_playlist_start():
    """Build ONE stateless cosmetic ISO covering every character/stage in the
    playlist, then play the whole queue against it. Recording a playlist of
    whole games writes one video per game into ``record_dir`` (the folder the
    popup showed); a combo playlist records one back-to-back video. char_selections maps a
    character ext id -> skin id (installed at EVERY costume slot that fighter
    uses in the queue, since replays load by index); stage_selections maps a
    stage id -> vault variant id."""
    body = request.get_json(silent=True) or {}
    char_selections = body.get("char_selections") or {}
    stage_selections = body.get("stage_selections") or {}
    conn = indexer.connect()
    try:
        rows, entries = _resolve_clip_entries(conn, body.get("clips") or [])
    finally:
        conn.close()
    if not entries:
        return jsonify({"error": "no playable clips in the playlist"}), 400
    vanilla = body.get("isoPath") or _launcher_vanilla_iso()
    if not vanilla or not os.path.exists(vanilla):
        return jsonify({"error": "no vanilla ISO found (set one in the Slippi "
                                  "Launcher or app settings)"}), 400
    meta = load_metadata() or {}
    chars_meta = meta.get("characters") or {}

    # every costume slot each character occupies across the queue, and every
    # stage the queue visits — the modded ISO must cover all of them
    char_slots, stage_ids = {}, set()
    for e in entries:
        row = rows[e["game_id"]]
        for p in json.loads(row["players"] or "[]"):
            cid = p.get("character")
            if cid is not None:
                char_slots.setdefault(cid, set()).add(p.get("costume") or 0)
        stage_ids.add(row["stage"])

    selections = []
    for cid_str, skin_id in char_selections.items():
        if not skin_id:
            continue
        try:
            cid = int(cid_str)
        except (TypeError, ValueError):
            continue
        fighter = _fighter_name(cid)
        costume_path, err = _resolve_skin_costume(fighter, skin_id, chars_meta)
        if err:
            return jsonify({"error": f"{fighter or cid}: {err}"}), 400
        for slot in sorted(char_slots.get(cid) or {0}):
            selections.append({"fighter": fighter, "slot": slot,
                               "costume_path": costume_path})

    stage_list = []
    for sid_str, variant_id in stage_selections.items():
        if not variant_id:
            continue
        try:
            sid = int(sid_str)
        except (TypeError, ValueError):
            continue
        if sid not in stage_ids:
            continue
        stage_sel, err = _resolve_stage_selection(sid, variant_id, meta)
        if err:
            return jsonify({"error": err}), 400
        stage_list.append(stage_sel)

    record = bool(body.get("record"))
    compress = bool(body.get("compress"))
    widescreen = bool(body.get("widescreen"))
    no_music = bool(body.get("no_music"))
    # Recording a playlist of WHOLE games saves one video per game (each
    # compressed on its own for Discord). Combo playlists keep the single
    # back-to-back video.
    split_games = record and all(e.get("full") for e in entries)
    out_dir = None
    if record:
        # the folder the popup showed when Start was pressed is the folder
        # this job writes to (persisted, so it is also the next default)
        requested = (body.get("record_dir") or "").strip()
        if requested:
            if not os.path.isabs(requested):
                return jsonify({"error": "the recording folder must be an "
                                         "absolute path"}), 400
            try:
                os.makedirs(requested, exist_ok=True)
            except OSError as exc:
                return jsonify({"error": f"cannot use the recording folder: "
                                         f"{exc}"}), 400
            recording.set_recording_dir(requested)
        out_dir = recording.recording_dir()
    job_id, busy = _start(entries[0]["path"], vanilla, selections,
                          stage=stage_list or None, record=record,
                          clip=entries, compress=compress,
                          widescreen=widescreen, no_music=no_music,
                          split_games=split_games, out_dir=out_dir)
    if busy:
        return busy
    return jsonify({"started": True, "job_id": job_id, "clip_count": len(entries),
                    "per_game": split_games, "record_dir": out_dir})


@nucleome_bp.route("/watch-mods/stop", methods=["POST"])
def watch_mods_stop():
    """Stop the watch job ``job_id`` (body): close its playback Dolphin (the
    embedded render window has no title bar); a recording batch saves the game
    in progress and starts no more. A stale id stops nothing, so an old popup
    can never stop a newer watch."""
    job_id = (request.get_json(silent=True) or {}).get("job_id")
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    return jsonify({"stopped": watch_mods.stop_job(job_id)})


@nucleome_bp.route("/watch-mods/window/position", methods=["POST"])
def watch_mods_window_position():
    """Pin the playback Dolphin's render window over the frontend's
    placeholder (same embed mechanism as Test in game). Body: {x, y, width,
    height} in PHYSICAL screen pixels; found=false until the window exists."""
    if os.name != "nt":
        # supported:false lets DolphinEmbedPanel show an honest "separate
        # window" state instead of waiting forever for an embed.
        return jsonify({"success": False, "found": False, "supported": False,
                        "error": "Window embedding is only supported on Windows."}), 400
    data = request.get_json(silent=True) or {}
    try:
        x, y = int(data["x"]), int(data["y"])
        w, h = int(data["width"]), int(data["height"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"success": False, "found": False,
                        "error": "x, y, width and height (integers) are required."}), 400
    return jsonify({"success": True, **playback.position_window(x, y, w, h)})


@nucleome_bp.route("/watch-mods/window/park", methods=["POST"])
def watch_mods_window_park():
    if os.name != "nt":
        return jsonify({"success": True, "found": False, "supported": False})
    return jsonify({"success": True, **playback.park_window()})


@nucleome_bp.route("/watch-mods/window/popout", methods=["POST"])
def watch_mods_window_popout():
    """Detach the playback Dolphin into a normal desktop window (title bar
    back, not always-on-top). position/park no-op until popin."""
    if os.name != "nt":
        return jsonify({"success": False, "found": False, "supported": False})
    return jsonify({"success": True, **playback.popout_window()})


@nucleome_bp.route("/watch-mods/window/popin", methods=["POST"])
def watch_mods_window_popin():
    """Re-embed a popped-out playback Dolphin into the modal."""
    if os.name != "nt":
        return jsonify({"success": False, "found": False, "supported": False})
    return jsonify({"success": True, **playback.popin_window()})


@nucleome_bp.route("/watch-mods/recording-file/<path:name>", methods=["GET"])
def recording_file(name):
    """Stream a finished recording (the coach's rendered clip reels play
    inline in the chat). Only basenames under the recording dir."""
    base = os.path.abspath(recording.recording_dir())
    full = os.path.abspath(os.path.join(base, os.path.basename(name)))
    if not full.startswith(base) or not os.path.exists(full):
        return jsonify({"error": "unknown recording"}), 404
    return send_file(full, conditional=True)


@nucleome_bp.route("/watch-mods/recording-dir", methods=["GET", "POST"])
def recording_dir():
    """Get or set the folder finished recordings are saved to."""
    if request.method == "POST":
        path = (request.get_json(silent=True) or {}).get("path")
        return jsonify({"dir": recording.set_recording_dir(path)})
    return jsonify({"dir": recording.recording_dir()})


@nucleome_bp.route("/watch-mods/reveal-recording", methods=["POST"])
def reveal_recording():
    path = (request.get_json(silent=True) or {}).get("path") or ""
    # only reveal files that actually exist under the configured recording dir
    rec_dir = os.path.normpath(recording.recording_dir())
    norm = os.path.normpath(path)
    if not (norm.startswith(rec_dir + os.sep) and os.path.exists(norm)):
        return jsonify({"error": "unknown recording"}), 404
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", norm])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(norm)])
    return jsonify({"ok": True})
