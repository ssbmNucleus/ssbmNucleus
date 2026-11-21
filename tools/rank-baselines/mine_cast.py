"""Whole-cast shard churn: every character folder on HF -> baseline rows.

Philosophy: HuggingFace is the permanent store — local disk is only a working
buffer. For each character, every SAME-TIER shard (diamond-diamond /
master-master / platinum-platinum) is downloaded (unless already on disk),
mined through analyzer_v2, and — if this script downloaded it — deleted right
after. Pre-existing shards in the shard folders are mined in place and kept. While one
shard is mining, the next download runs in parallel, so bandwidth and CPU
overlap instead of alternating.

Rows accumulate in $MELEE_MINE_ROWS with the same .done markers as
mine_shards_v2, so the churn is resumable across nights and shards are never
re-mined. Re-run build_packs_v2.py any time to refresh the packs from
whatever has landed.

Usage: venv/Scripts/python.exe mine_cast.py [--workers 10]
       [--sample N]   only the N smallest shards per tier pair (quick pass)
       [--chars FOX,MARTH]
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request

import mine_shards_v2 as m2

HF_API = "https://huggingface.co/api/datasets/erickfm/melee-ranked-replays/tree/main/"
HF_DL = "https://huggingface.co/datasets/erickfm/melee-ranked-replays/resolve/main/"
DL_DIR = m2.SHARDS
MIN_FREE_GB = 100

# user's main first, then top opponents, then the rest of the cast
CAST = ["FALCO", "FOX", "MARTH", "SHEIK", "CPTFALCON", "PEACH", "JIGGLYPUFF",
        "SAMUS", "ICE_CLIMBERS", "LUIGI", "DOC", "GANONDORF", "PIKACHU",
        "YOSHI", "DK", "LINK", "NESS", "MARIO", "MEWTWO", "YLINK",
        "BOWSER", "ROY", "GAMEANDWATCH", "ZELDA", "KIRBY", "PICHU"]

SAME_TIER = ("diamond-diamond", "master-master", "platinum-platinum")


def free_gb(path):
    import shutil
    return shutil.disk_usage(path).free / 1e9


def shard_list(char):
    """[(name, size_bytes)] of .tar.gz files in a character's HF folder."""
    with urllib.request.urlopen(HF_API + char, timeout=60) as r:
        files = json.load(r)
    return [(f["path"].split("/")[-1], f.get("size", 0)) for f in files
            if f.get("type") == "file" and f["path"].endswith(".tar.gz")]


def local_path(fname):
    for d in m2.SHARD_DIRS:
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    return None


def rows_done(fname):
    name = fname[:-len(".tar.gz")]
    return os.path.exists(os.path.join(m2.ROWS_DIR, name + ".jsonl.done"))


def build_queue(cast, sample):
    """[(char, fname, size)] of shards still needing rows, in cast order."""
    queue = []
    for char in cast:
        try:
            names = shard_list(char)
        except Exception as e:
            print(f"LIST-FAIL {char}: {e} — skipping", flush=True)
            continue
        for tier in SAME_TIER:
            pool = [x for x in names if f"_{tier}_" in x[0]]
            if sample:
                pool.sort(key=lambda x: (local_path(x[0]) is None, x[1]))
                pool = pool[:sample]
            else:
                pool.sort(key=lambda x: x[0])
            queue.extend((char, f, s) for f, s in pool if not rows_done(f))
    return queue


def start_download(char, fname):
    out = os.path.join(DL_DIR, fname)
    proc = subprocess.Popen(["curl", "-sL", "-C", "-", "-o", out,
                             HF_DL + char + "/" + fname])
    return proc, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None,
                    help="only the N smallest shards per tier pair (default: ALL)")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--chars", default=None,
                    help="comma list; default = whole cast")
    args = ap.parse_args()
    cast = ([c.strip().upper() for c in args.chars.split(",")]
            if args.chars else CAST)

    os.makedirs(m2.ROWS_DIR, exist_ok=True)
    os.makedirs(m2.WORK_DIR, exist_ok=True)
    os.makedirs(DL_DIR, exist_ok=True)
    queue = build_queue(cast, args.sample)
    total_gb = sum(s for _, _, s in queue) / 1e9
    print(f"CAST QUEUE: {len(queue)} shards, {total_gb:.0f} GB to churn", flush=True)

    prefetch = {}  # fname -> (proc, outpath)

    def ensure_prefetch(idx):
        """Kick off the next needed download (one slot) beyond queue[idx]."""
        if prefetch:
            return
        for j in range(idx + 1, len(queue)):
            nchar, nfname, _ = queue[j]
            if rows_done(nfname) or local_path(nfname) is not None:
                continue
            if free_gb(DL_DIR) < MIN_FREE_GB:
                return
            prefetch[nfname] = start_download(nchar, nfname)
            return

    for idx, (char, fname, size) in enumerate(queue):
        if rows_done(fname):
            continue
        if free_gb(DL_DIR) < MIN_FREE_GB:
            print(f"STOP: D: free below {MIN_FREE_GB} GB floor", flush=True)
            break
        name = fname[:-len(".tar.gz")]
        path = local_path(fname)
        downloaded = False
        if path is None:
            if fname in prefetch:
                proc, out = prefetch.pop(fname)
            else:
                proc, out = start_download(char, fname)
            t0 = time.time()
            rc = proc.wait()
            if rc != 0 or not os.path.exists(out) or os.path.getsize(out) < 1e8:
                print(f"DL-FAIL {fname} rc={rc} — will retry on rerun", flush=True)
                continue
            print(f"DL {fname} {os.path.getsize(out)/1e9:.1f} GB "
                  f"(waited {(time.time()-t0)/60:.0f} min)", flush=True)
            path = out
            downloaded = True
        ensure_prefetch(idx)
        m2.mine_shard(name, path, args.workers)
        if downloaded:
            try:
                os.remove(path)
            except OSError:
                pass
            print(f"CLEANED {fname}", flush=True)
    # reap any dangling prefetch
    for fname, (proc, out) in prefetch.items():
        proc.kill()
    print("CAST MINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
