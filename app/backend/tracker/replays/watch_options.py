"""What Watch with mods can dress a replay with: the Vault skins for each
fighter and the Vault variants for the stage, resolving a chosen skin or variant
to its file, and checking a playlist of games or combo clips against the index.
Shared by the Watch and Combo Video routes.
"""
import os

from core.config import STORAGE_PATH
from ..store.games import STAGE_VAULT, _game_row


def _stage_mods_for(stage_id, meta):
    """Vault stage variants that could reskin this replay's stage."""
    info = STAGE_VAULT.get(stage_id)
    if not info:
        return []
    folder, _code, _ext = info
    out = []
    for v in (meta.get("stages", {}).get(folder) or {}).get("variants") or []:
        vid = v.get("id")
        if not vid:
            continue
        entry = {"id": vid, "name": v.get("name") or vid}
        if v.get("has_screenshot"):
            entry["screenshot"] = f"/storage/das/{folder}/{vid}_screenshot.png"
        out.append(entry)
    return out


def _skins_for_fighter(fighter, chars_meta):
    """Vault skins that could dress a fighter, shaped for the picker UI."""
    skins = []
    if fighter:
        for s in (chars_meta.get(fighter) or {}).get("skins") or []:
            if not s.get("filename"):
                continue
            csp_file = s.get("csp_filename") or "{}_csp.png".format(s.get("id"))
            skins.append({
                "id": s.get("id"),
                "name": s.get("name") or s.get("id"),
                "csp": f"/storage/{fighter}/{csp_file}",
            })
    return skins


def _resolve_skin_costume(fighter, skin_id, chars_meta):
    """On-disk vault costume-zip path for a fighter's chosen skin id, or
    (None, error)."""
    skin = next((s for s in (chars_meta.get(fighter) or {}).get("skins") or []
                 if s.get("id") == skin_id), None)
    if not fighter or not skin or not skin.get("filename"):
        return None, "unknown skin"
    costume_path = str(STORAGE_PATH / fighter / skin["filename"])
    if not os.path.exists(costume_path):
        return None, f"skin file missing: {skin['filename']}"
    return costume_path, None


def _resolve_stage_selection(stage_id, variant_id, meta):
    """Resolve a chosen stage-vault variant to the watch_mods install spec
    ({code, ext, zip_path, name}), or (None, error)."""
    info = STAGE_VAULT.get(stage_id)
    if not info:
        return None, "this stage has no vault skins"
    folder, code, ext = info
    variant = next((v for v in (meta.get("stages", {}).get(folder) or {}).get("variants") or []
                    if v.get("id") == variant_id), None)
    if not variant:
        return None, "unknown stage skin"
    # ISO-scan-imported variants store no 'filename'; the zip follows the id
    zip_path = STORAGE_PATH / "das" / folder / (
        variant.get("filename") or f"{variant_id}.zip")
    if not zip_path.exists():
        return None, f"stage skin file missing: {zip_path.name}"
    return {"code": code, "ext": ext, "zip_path": str(zip_path),
            "name": variant.get("name") or variant_id}, None


# The UI lets you pick any playlist length (combo marathons are a feature) —
# this is only a runaway backstop against a fat-fingered 999999 building an
# absurd comm queue. The modded ISO build cost is bounded regardless (one
# import per DISTINCT costume slot, ~120 slots total), so long queues are cheap
# to build and just take a while to watch.
PLAYLIST_CLIP_CAP = 2000


def _resolve_clip_entries(conn, clips):
    """Validate a [{game_id, start_frame, end_frame}] playlist against the
    index. Returns (rows_by_game_id, entries) where each entry is a padded
    queue item {path, startFrame, endFrame, game_id} in the given order.
    Unknown/missing games and unparseable frames are dropped; capped.

    A clip with `full: true` is a WHOLE game (the Replays tab's multi-select
    "Watch / record as playlist"): it plays from the first Slippi frame (-123)
    to the game's indexed last_frame, unpadded — the frames are taken from the
    index, never the client (the client's end_frame is only a fallback for a
    row with no last_frame)."""
    rows, entries = {}, []
    for c in (clips or [])[:PLAYLIST_CLIP_CAP]:
        if not isinstance(c, dict):
            continue
        gid = c.get("game_id")
        row = rows.get(gid)
        if row is None:
            row = _game_row(conn, gid)
            if row is None or not os.path.exists(row["path"]):
                continue
            rows[gid] = row
        if c.get("full"):
            last = row["last_frame"]
            if not isinstance(last, int):
                try:
                    last = int(c["end_frame"])
                except (KeyError, TypeError, ValueError):
                    continue
            if last <= -123:
                continue
            entries.append({"path": row["path"], "startFrame": -123,
                            "endFrame": last, "game_id": gid, "full": True})
            continue
        try:
            sf, ef = int(c["start_frame"]), int(c["end_frame"])
        except (KeyError, TypeError, ValueError):
            continue
        # same lead-in/out padding as the single-combo watch and the coach reel
        entries.append({"path": row["path"], "startFrame": max(-123, sf - 60),
                        "endFrame": ef + 90, "game_id": gid})
    return rows, entries
