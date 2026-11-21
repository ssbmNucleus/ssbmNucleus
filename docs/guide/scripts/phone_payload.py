"""Build the vault-read payloads the phone app expects, from the guide's own
sample library (docs/guide/.capture/storage/nucleome.db).

The phone normally gets these from the cloud with a paired device token. For
screenshots that is the wrong tool: it would need a real credential and would
put a different library in the phone shots than the desktop shots show. The
response shapes here mirror meleeWebsite/supabase/functions/vault-read
(`list` and `combos`) exactly, so the app runs its real code paths.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

NUCLEUS = Path(__file__).resolve().parents[3] / "app"  # the app/ folder
GUIDE = Path(__file__).resolve().parents[1]  # docs/guide
sys.path.insert(0, str(NUCLEUS / "backend"))
DB = GUIDE / ".capture" / "storage" / "nucleome.db"


def build() -> dict:
    from tracker.cloud import vault_client

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    codes = {c.upper() for c in json.loads(
        conn.execute("select value from kv where key='user_codes'").fetchone()[0])}

    games, ranks = [], {}
    # The local index has no content_hash (that lives in the push ledger); the
    # phone only uses it to name a clip object, which a stubbed vault has none
    # of, so a stable stand-in keeps the rows well formed without pretending.
    for row in conn.execute("select id, path, size from games order by id desc"):
        meta = vault_client._game_meta(conn, row["id"], codes)
        if not meta:
            continue
        digest = hashlib.sha256(str(row["path"]).encode("utf-8")).hexdigest()
        games.append({"id": row["id"], "content_hash": digest,
                      "bytes": row["size"], "ranks": None, **meta})

    for key, value in conn.execute("select key, value from kv where key like 'rank:%'"):
        try:
            ranks[key.split(":", 1)[1]] = json.loads(value)
        except (TypeError, ValueError):
            pass

    by_id = {g["id"]: g for g in games}
    combos = []
    for c in conn.execute("select * from combos"):
        game = by_id.get(c["game_id"])
        if game is None:
            continue
        try:
            moves = json.loads(c["moves_json"]) if c["moves_json"] else []
        except (TypeError, ValueError):
            moves = []
        combos.append({
            "id": c["id"], "game_id": c["game_id"], "port": c["port"],
            "opp_port": c["opp_port"], "character": c["character"],
            "code": c["code"], "name": c["name"],
            "opp_character": c["opp_character"], "opp_code": c["opp_code"],
            "opp_name": c["opp_name"], "start_frame": c["start_frame"],
            "end_frame": c["end_frame"], "hits": c["hits"], "damage": c["damage"],
            "did_kill": bool(c["did_kill"]), "moves": moves,
            "start_percent": c["start_percent"], "end_percent": c["end_percent"],
            "true_combo": bool(c["true_combo"]),
            "vault_games": {"content_hash": game["content_hash"],
                            "stage": game["stage"], "start_at": game["start_at"]},
        })
    conn.close()
    return {"games": games, "combos": combos, "ranks": ranks,
            "codes": sorted(codes)}


if __name__ == "__main__":
    data = build()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else GUIDE / ".capture" / "phone-data.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    print(f"[phone] {len(data['games'])} games, {len(data['combos'])} combos, "
          f"{len(data['ranks'])} ranks, codes={data['codes']} -> {out}")
