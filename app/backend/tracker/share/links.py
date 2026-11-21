"""Public share links: a combo's place in its game's public /combo/N ordinal."""
import json

from ..cloud import vault_client


def _combo_ordinal(conn, game_id, combo_id):
    """1-based position of a combo among the game's publicly listed combos.

    The public page's /combo/N is an ordinal into vault_combos filtered by
    move_count (the moves array's length, falling back to hits — the exact
    expression _worth_uploading applies locally) and ordered by start_frame.
    Recomputed here from the local index; if combos were re-extracted since
    the last push the ordinal can drift, exactly as the phone's would.
    """
    n = 0
    # ORDER BY the WIRE value (start_rf when extracted, the row basis the
    # upload ships) — the cloud orders /combo/N by what it received, and the
    # two sorts can differ at a partial-rollback tail if this one used the
    # true frames.
    for r in conn.execute(
            "SELECT id, moves_json, hits, did_kill FROM combos "
            "WHERE game_id = ? "
            "ORDER BY COALESCE(start_rf, start_frame) ASC, id ASC", (game_id,)):
        try:
            moves = json.loads(r["moves_json"]) if r["moves_json"] else []
        except (TypeError, ValueError):
            moves = []
        if not vault_client._worth_uploading(moves, r["hits"], r["did_kill"]):
            continue
        n += 1
        if r["id"] == combo_id:
            return n
    return None
