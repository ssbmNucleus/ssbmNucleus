"""Mine MY replays + the summit corpus through analyzer_v2, and mine MY
out-of-shieldstun option mix (mirror of the tier situation tables).

Outputs (all under data/):
  v2_rows_mine.jsonl     my Falco player-games (analyzer_v2 rows, my port only)
  v2_rows_summit.jsonl   summit11 corpus rows (both players are summit-level)
  my_oos_events.json     my OOS events tagged by opponent character

Run while the shard miner is going: use --workers 4 to share cores.
"""
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor

from analyzer_v2 import analyze_game
from response_mining import mine_game as mine_oos

# the corpus lives at the repo root, one level up from this package
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
# Your own connect code: the player whose games are mined.
ME = os.environ.get("MINE_CONNECT_CODE", "ABCD#123")

# corpus_index.jsonl stores INTERNAL char ids as strings
INTERNAL_NAMES = {"2": "CF", "3": "DK", "1": "Fox", "24": "G&W", "4": "Kirby",
                  "5": "Bowser", "6": "Link", "17": "Luigi", "0": "Mario",
                  "18": "Marth", "16": "Mewtwo", "8": "Ness", "9": "Peach",
                  "12": "Pikachu", "10": "Popo", "15": "Puff", "13": "Samus",
                  "14": "Yoshi", "19": "Zelda", "7": "Sheik", "22": "Falco",
                  "21": "YLink", "23": "Doc", "25": "Roy", "26": "Pichu",
                  "20": "Ganon"}
FALCO_INTERNAL = "22"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    # ---- 1. my Falco games through analyzer_v2
    mine = json.load(open(os.path.join(DATA, "my_falco.json")))
    my_files = [g["file"] for g in mine]
    my_port_of = {g["file"]: g["my_port"] for g in mine}
    print(f"my games: {len(my_files)}", flush=True)
    n_rows = 0
    with open(os.path.join(DATA, "v2_rows_mine.jsonl"), "w", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for fn, rows in zip(my_files, ex.map(analyze_game, my_files, chunksize=8)):
                for row in rows:
                    if row["port"] == my_port_of[fn]:
                        row["shard"] = "mine"
                        row["startAt"] = next(
                            (g["startAt"] for g in mine if g["file"] == fn), None)
                        out.write(json.dumps(row) + "\n")
                        n_rows += 1
    print(f"my rows: {n_rows}", flush=True)

    # ---- 2. summit corpus through analyzer_v2 (both players are summit tier)
    summit = json.load(open(os.path.join(DATA, "summit11_falco.json")))
    pro_files = [g["file"] for g in summit if len(g["players"]) == 2]
    print(f"summit games: {len(pro_files)}", flush=True)
    n_rows = 0
    with open(os.path.join(DATA, "v2_rows_summit.jsonl"), "w", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for rows in ex.map(analyze_game, pro_files, chunksize=2):
                for row in rows:
                    row["shard"] = "summit11"
                    out.write(json.dumps(row) + "\n")
                    n_rows += 1
    print(f"summit rows: {n_rows}", flush=True)

    # ---- 3. my OOS option mix, per opponent character
    jobs = []
    for line in open(os.path.join(DATA, "corpus_index.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if "error" in r or (r.get("frames") or 0) < 3600:
            continue
        memb = next((p for p in r["players"] if p["code"] == ME), None)
        oppp = next((p for p in r["players"] if p["code"] != ME), None)
        if memb and oppp and FALCO_INTERNAL in memb["chars"] and len(oppp["chars"]) == 1:
            opp_name = INTERNAL_NAMES.get(oppp["chars"][0])
            if opp_name:
                jobs.append((r["file"], memb["port"], opp_name))
    print(f"my OOS-minable games: {len(jobs)}", flush=True)
    events_by_mu = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for (fn, port, opp), evs in zip(
                jobs, ex.map(mine_oos, [(f, p) for f, p, _ in jobs], chunksize=8)):
            events_by_mu.setdefault(opp, []).extend(evs)
    json.dump(events_by_mu, open(os.path.join(DATA, "my_oos_events.json"), "w"))
    for mu, evs in sorted(events_by_mu.items(), key=lambda kv: -len(kv[1])):
        print(f"  vs {mu}: {len(evs)} OOS situations", flush=True)
    print("OWN MINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
