"""Bulk pre-downloader: fetch every remaining un-mined same-tier shard into
$MELEE_SHARDS ahead of the churner, so mining never waits on the network.
mine_cast/mine_shards_v2 check that folder (local_path) before downloading —
anything landed here is consumed with zero download wait, and the rolling
cleaner deletes it after it's mined.

Skips shards that are already mined (rows/.done), already local, or in
flight. Downloads smallest-first so the churner's near-term queue fills
fastest. Safe to re-run.
"""
import json
import os
import time
import urllib.request

# Same folders and defaults as mine_shards_v2 (not imported: it pulls in analyzer_v2).
ROWS = os.environ.get("MELEE_MINE_ROWS") or os.path.join(os.path.expanduser("~"), "melee-mine", "rows")
DEST = os.environ.get("MELEE_SHARDS") or os.path.join(os.path.expanduser("~"), "melee-shards")
HF_API = "https://huggingface.co/api/datasets/erickfm/melee-ranked-replays/tree/main/"
HF_DL = "https://huggingface.co/datasets/erickfm/melee-ranked-replays/resolve/main/"

CAST = ["FALCO", "FOX", "MARTH", "SHEIK", "CPTFALCON", "PEACH", "JIGGLYPUFF",
        "SAMUS", "ICE_CLIMBERS", "LUIGI", "DOC", "GANONDORF", "PIKACHU",
        "YOSHI", "DK", "LINK", "NESS", "MARIO", "MEWTWO", "YLINK",
        "BOWSER", "ROY", "GAMEANDWATCH", "ZELDA", "KIRBY", "PICHU"]
SAME_TIER = ("diamond-diamond", "master-master", "platinum-platinum")
MIN_FREE_GB = 80


def free_gb(path):
    import shutil
    return shutil.disk_usage(path).free / 1e9


def main():
    os.makedirs(DEST, exist_ok=True)
    todo = []
    for char in CAST:
        try:
            req = urllib.request.Request(HF_API + char,
                                         headers={"User-Agent": "nucleome-miner"})
            files = json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            print(f"LIST-FAIL {char}: {e}", flush=True)
            continue
        for f in files:
            n = f["path"].split("/")[-1]
            if not n.endswith(".tar.gz"):
                continue
            if not any(f"_{t}_" in n for t in SAME_TIER):
                continue
            name = n[:-7]
            if os.path.exists(os.path.join(ROWS, name + ".jsonl.done")):
                continue
            if os.path.exists(os.path.join(DEST, n)):
                continue
            todo.append((char, n, f.get("size", 0)))
    todo.sort(key=lambda x: x[2])          # smallest first
    print(f"prefetching {len(todo)} shards, "
          f"{sum(s for _, _, s in todo)/1e9:.0f} GB", flush=True)
    for char, fname, size in todo:
        name = fname[:-7]
        if os.path.exists(os.path.join(ROWS, name + ".jsonl.done")):
            print(f"SKIP {name} (mined meanwhile)", flush=True)
            continue
        if free_gb(DEST) < MIN_FREE_GB:
            print(f"STOP: free below {MIN_FREE_GB} GB", flush=True)
            break
        tmp = os.path.join(DEST, fname + ".part")
        try:
            t0 = time.time()
            req = urllib.request.Request(HF_DL + char + "/" + fname,
                                         headers={"User-Agent": "nucleome-miner"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                import shutil
                shutil.copyfileobj(r, f, length=1 << 20)
            os.replace(tmp, os.path.join(DEST, fname))
            print(f"DL {fname} {size/1e9:.1f} GB in {(time.time()-t0)/60:.1f} min",
                  flush=True)
        except Exception as e:
            print(f"FAIL {fname}: {type(e).__name__}: {e}", flush=True)
            try:
                os.remove(tmp)
            except OSError:
                pass
    print("PREFETCH COMPLETE", flush=True)


if __name__ == "__main__":
    main()
