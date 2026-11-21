"""Images every Tracker page shows: stage icons, vanilla stock icons, and the
sprites derived from the player's own vanilla ISO (Randall's cloud faces, the
shine). The icon and sprite files are public media in app.py
(_PUBLIC_MEDIA_PREFIXES): an <img> cannot send the backend token.
Routes attach to nucleome_bp (tracker/routes/nucleome.py).
"""
import os

from flask import jsonify, send_file

from core.constants import CHAR_PREFIXES, VANILLA_CSS_COLOR_ORDER
from shared.rendering.costume_assets import VANILLA_ASSETS_DIR
from shared.vanilla_extract.menu_refs import stage_art_path
from tracker.routes.nucleome import nucleome_bp
from tracker.store.games import (EXT_CHAR_FOLDERS, STAGE_ART_FILES, STAGE_GR_CODES,
                                 _PREFIX_KEY_OVERRIDES)
from tracker.video import sprites


@nucleome_bp.route("/stage-icon/<int:stage_id>", methods=["GET"])
def stage_icon(stage_id):
    path = None
    if stage_id in STAGE_ART_FILES:
        path = (VANILLA_ASSETS_DIR.parent / "stages" / STAGE_ART_FILES[stage_id])
    elif stage_id in STAGE_GR_CODES:
        # The stage-select icon, copied out of the user's own game at setup
        # and on project open (menu_refs); nothing is bundled.
        path = stage_art_path(f"Gr{STAGE_GR_CODES[stage_id]}", "icon")
    if not path or not os.path.exists(path):
        return jsonify({"error": "no icon"}), 404
    resp = send_file(path, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@nucleome_bp.route("/stock/<int:ext_id>/<int:costume>", methods=["GET"])
def stock_icon(ext_id, costume):
    """Vanilla stock icon for an external character id + costume index,
    served from the bundled vanilla assets (exact costume when it exists,
    default color as fallback)."""
    folder = EXT_CHAR_FOLDERS.get(ext_id)
    if not folder:
        return jsonify({"error": "unknown character"}), 404
    prefix_key = _PREFIX_KEY_OVERRIDES.get(folder, folder)
    code = CHAR_PREFIXES.get(prefix_key)
    colors = VANILLA_CSS_COLOR_ORDER.get(folder) or ["Nr"]
    if not code:
        return jsonify({"error": "no prefix"}), 404
    candidates = []
    if 0 <= costume < len(colors):
        candidates.append(colors[costume])
    candidates.append("Nr")
    for color in candidates:
        path = VANILLA_ASSETS_DIR / folder / f"Pl{code}{color}" / "stock.png"
        if path.exists():
            resp = send_file(path, mimetype="image/png")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
    return jsonify({"error": "icon not found"}), 404


@nucleome_bp.route("/sprites", methods=["GET"])
def sprites_manifest():
    """Manifest of the Melee-derived UI sprites (Randall's cloud faces +
    blink track, shine loop/reflect frames). Derives them from the recorded
    vanilla ISO on first request; 503 until an ISO has been recorded."""
    manifest = sprites.ensure_sprites()
    if manifest is None:
        return jsonify({"error": "sprites unavailable (no vanilla ISO "
                                  "recorded yet)"}), 503
    return jsonify(manifest)


@nucleome_bp.route("/sprites/<name>", methods=["GET"])
def sprite_file(name):
    """A derived sprite PNG by manifest filename."""
    path = sprites.sprite_path(name)
    if path is None and sprites.ensure_sprites() is not None:
        path = sprites.sprite_path(name)  # first request may need derivation
    if path is None:
        return jsonify({"error": "unknown sprite"}), 404
    resp = send_file(path, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
