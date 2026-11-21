"""Standalone shard miner for the conscripted laptop (stdlib + peppi-py).

Same churn as mine_cast.py but self-contained: downloads same-tier shards
from HF, mines them through analyzer_v2 (same folder), writes rows JSONL to
./rows, deletes tarballs/extractions. Works BACKWARDS through the cast so it
meets the desktop/Modal lanes in the middle — overlap is harmless (identical
rows), the reversed order just minimizes it.

Run (from its folder, with analyzer_v2.py beside it):
    py -3.12 laptop_mine.py

Ship ./rows/*.jsonl back to the desktop's $MELEE_MINE_ROWS when done.
"""
import glob
import json
import os
import shutil
import tarfile
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(BASE, "rows")
WORK = os.path.join(BASE, "work")
DL = os.path.join(BASE, "dl")

HF_API = "https://huggingface.co/api/datasets/erickfm/melee-ranked-replays/tree/main/"
HF_DL = "https://huggingface.co/datasets/erickfm/melee-ranked-replays/resolve/main/"

# the whole-cast order, REVERSED (desktop + Modal work front-to-back)
CAST = ["PICHU", "KIRBY", "ZELDA", "GAMEANDWATCH", "ROY", "BOWSER", "YLINK",
        "MEWTWO", "MARIO", "NESS", "LINK", "DK", "YOSHI", "PIKACHU",
        "GANONDORF", "DOC", "LUIGI", "ICE_CLIMBERS", "SAMUS", "JIGGLYPUFF",
        "PEACH", "CPTFALCON", "SHEIK", "MARTH", "FOX", "FALCO"]
SAME_TIER = ("diamond-diamond", "master-master", "platinum-platinum")
WORKERS = 14
MIN_FREE_GB = 40


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nucleome-miner"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def shard_list(char):
    return [(f["path"].split("/")[-1], f.get("size", 0))
            for f in http_json(HF_API + char)
            if f.get("type") == "file" and f["path"].endswith(".tar.gz")]


def download(char, fname):
    os.makedirs(DL, exist_ok=True)
    out = os.path.join(DL, fname)
    req = urllib.request.Request(HF_DL + char + "/" + fname,
                                 headers={"User-Agent": "nucleome-miner"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    return out


def mine(name, tar_path):
    from analyzer_v2 import analyze_game
    rows_path = os.path.join(ROWS, name + ".jsonl")
    work = os.path.join(WORK, name)
    os.makedirs(work, exist_ok=True)
    t0 = time.time()
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(work, filter="data")
    files = glob.glob(os.path.join(work, "**", "*.slp"), recursive=True)
    print(f"MINE {name}: {len(files)} games "
          f"(extracted {(time.time()-t0)/60:.1f} min)", flush=True)
    n = 0
    with open(rows_path, "w", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            for rows in ex.map(analyze_game, files, chunksize=16):
                for row in rows:
                    row["shard"] = name
                    out.write(json.dumps(row) + "\n")
                    n += 1
    open(rows_path + ".done", "w").write("ok")
    shutil.rmtree(work, ignore_errors=True)
    print(f"DONE {name}: {n} rows in {(time.time()-t0)/60:.1f} min", flush=True)


def main():
    os.makedirs(ROWS, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    for char in CAST:
        try:
            names = shard_list(char)
        except Exception as e:
            print(f"LIST-FAIL {char}: {e}", flush=True)
            continue
        queue = []
        for tier in SAME_TIER:
            queue.extend(sorted(f for f, _ in names if f"_{tier}_" in f))
        print(f"=== {char}: {len(queue)} same-tier shards", flush=True)
        for fname in queue:
            name = fname[: -len(".tar.gz")]
            if os.path.exists(os.path.join(ROWS, name + ".jsonl.done")):
                print(f"SKIP {name}", flush=True)
                continue
            if free_gb(BASE) < MIN_FREE_GB:
                print(f"STOP: free space below {MIN_FREE_GB} GB", flush=True)
                return
            try:
                t0 = time.time()
                tar_path = download(char, fname)
                print(f"DL {fname} {os.path.getsize(tar_path)/1e9:.1f} GB "
                      f"in {(time.time()-t0)/60:.1f} min", flush=True)
                mine(name, tar_path)
            except Exception as e:
                print(f"FAIL {fname}: {type(e).__name__}: {e}", flush=True)
            finally:
                try:
                    os.remove(os.path.join(DL, fname))
                except OSError:
                    pass
    print("LAPTOP MINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
