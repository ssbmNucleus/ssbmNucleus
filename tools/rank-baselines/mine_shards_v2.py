"""Mine same-tier ranked shards through analyzer_v2 into per-game row files.

For each shard tarball (searched across $MELEE_SHARD_DIRS, $MELEE_SHARDS and
this folder): extract to $MELEE_MINE_WORK, run analyzer_v2 over every .slp
with a process pool, write one JSONL of per-player rows to
$MELEE_MINE_ROWS/<shard>.jsonl, then delete the extraction. A .done marker
makes the whole run resumable per shard.

Only SAME-TIER shards (diamond-diamond etc.) are mined: in cross-tier shards
there is no way to tell which player holds which rank, so their rows would
poison tier baselines.

Usage:  venv/Scripts/python.exe mine_shards_v2.py [--limit-games N]
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from analyzer_v2 import analyze_game

# Folders come from the environment; the defaults sit under the home folder
# (build_packs_v2 reads rows from the same MELEE_MINE_ROWS default).
HOME = os.path.expanduser("~")
SHARDS = os.environ.get("MELEE_SHARDS") or os.path.join(HOME, "melee-shards")
SHARD_DIRS = [d for d in os.environ.get("MELEE_SHARD_DIRS", "").split(os.pathsep) if d] + [
    SHARDS, os.path.dirname(os.path.abspath(__file__))]
ROWS_DIR = os.environ.get("MELEE_MINE_ROWS") or os.path.join(HOME, "melee-mine", "rows")
WORK_DIR = os.environ.get("MELEE_MINE_WORK") or os.path.join(HOME, "melee-mine", "work")

# priority: the tiers the coach needs first (diamond = user's next rung)
TIER_ORDER = ["diamond-diamond", "master-master", "platinum-platinum"]
# character folders present on disk; FALCO first (the user's main), then the
# top opponents — mining a character's own shards also de-biases the packs
# built from their appearances as opponents in other characters' shards
CHAR_ORDER = ["FALCO", "FOX", "MARTH", "SHEIK", "CPTFALCON", "PEACH"]


def find_shards(chars):
    """[(shard_name, tarball_path)] for same-tier shards, char then tier order."""
    found = {}
    for d in SHARD_DIRS:
        for char in chars:
            for p in glob.glob(os.path.join(d, f"{char}_*.tar.gz")):
                name = os.path.basename(p)[:-len(".tar.gz")]
                found.setdefault(name, p)
    ordered = []
    for char in chars:
        for tier in TIER_ORDER:
            for name in sorted(found):
                if name.startswith(f"{char}_{tier}_"):
                    ordered.append((name, found[name]))
    return ordered


def mine_shard(name, tar_path, workers, limit_games=None):
    rows_path = os.path.join(ROWS_DIR, name + ".jsonl")
    done_path = rows_path + ".done"
    if os.path.exists(done_path):
        print(f"SKIP {name} (done)", flush=True)
        return
    work = os.path.join(WORK_DIR, name)
    t0 = time.time()
    if not os.path.isdir(work) or not glob.glob(os.path.join(work, "**", "*.slp"),
                                                recursive=True):
        os.makedirs(work, exist_ok=True)
        print(f"EXTRACT {name} ({os.path.getsize(tar_path)/1e9:.1f} GB)...", flush=True)
        r = subprocess.run(["tar", "-xzf", tar_path, "-C", work])
        if r.returncode != 0:
            print(f"FAIL extract {name} rc={r.returncode}", flush=True)
            shutil.rmtree(work, ignore_errors=True)
            return
    files = glob.glob(os.path.join(work, "**", "*.slp"), recursive=True)
    if limit_games:
        files = files[:limit_games]
    print(f"MINE {name}: {len(files)} games "
          f"(extracted in {(time.time()-t0)/60:.1f} min)", flush=True)
    t1 = time.time()
    n_rows = 0
    with open(rows_path, "w", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for k, rows in enumerate(ex.map(analyze_game, files, chunksize=16)):
                for row in rows:
                    row["shard"] = name
                    out.write(json.dumps(row) + "\n")
                    n_rows += 1
                if k % 2000 == 1999:
                    print(f"  {name}: {k+1}/{len(files)} games, {n_rows} rows, "
                          f"{(time.time()-t1)/60:.1f} min", flush=True)
    open(done_path, "w").write("ok")
    shutil.rmtree(work, ignore_errors=True)
    print(f"DONE {name}: {n_rows} rows in {(time.time()-t1)/60:.1f} min "
          f"(total {(time.time()-t0)/60:.1f} min)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit-games", type=int, default=None)
    ap.add_argument("--only", default=None, help="substring filter on shard name")
    ap.add_argument("--chars", default="FALCO",
                    help="comma list of character folders, or 'all'")
    args = ap.parse_args()

    chars = CHAR_ORDER if args.chars.lower() == "all" else [
        c.strip().upper() for c in args.chars.split(",") if c.strip()]
    os.makedirs(ROWS_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    shards = find_shards(chars)
    if args.only:
        shards = [s for s in shards if args.only in s[0]]
    print(f"{len(shards)} same-tier shards queued: {[s[0] for s in shards]}", flush=True)
    for name, tar_path in shards:
        free = shutil.disk_usage(WORK_DIR).free / 1e9
        if free < 60:
            print(f"STOP: D: free {free:.0f} GB below 60 GB floor", flush=True)
            break
        mine_shard(name, tar_path, args.workers, args.limit_games)
    print("ALL SHARDS COMPLETE", flush=True)


if __name__ == "__main__":
    main()
