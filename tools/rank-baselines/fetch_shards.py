"""Sequential, resumable shard downloader -> G:/AI/melee-shards.
curl -C - resumes partial downloads; skips completed files (size check via .done marker)."""
import os, subprocess, sys, time

BASE = "https://huggingface.co/datasets/erickfm/melee-ranked-replays/resolve/main/FALCO/"
DEST = sys.argv[1] if len(sys.argv) > 1 else r"G:\AI\melee-shards"

# priority order: diamond (user's next rung) -> master rest -> plat (user tier) -> cross-tier
SHARDS = (
    [f"FALCO_diamond-diamond_a{i}.tar.gz" for i in (1, 2, 4, 5, 6)] +   # a3 already local
    [f"FALCO_master-master_a{i}.tar.gz" for i in (1, 3, 4, 5, 6)] +     # a2 already local
    ["FALCO_platinum-platinum_a1.tar.gz", "FALCO_platinum-platinum_a3.tar.gz"] +
    [f"FALCO_master-diamond_a{i}.tar.gz" for i in (1, 2, 3, 4, 5, 6)] +
    ["FALCO_master-platinum_a1.tar.gz", "FALCO_master-platinum_a2.tar.gz"]
)

MIN_FREE_GB = 40 if "D:" in DEST.upper() else 25   # hard floor: stop before G: gets tight

def free_gb(path):
    import shutil
    return shutil.disk_usage(path).free / 1e9

def main():
    os.makedirs(DEST, exist_ok=True)
    for name in SHARDS:
        out = os.path.join(DEST, name)
        done = out + ".done"
        if os.path.exists(done):
            print(f"SKIP {name}", flush=True)
            continue
        if free_gb(DEST) < MIN_FREE_GB:
            print(f"STOP: G: free below {MIN_FREE_GB}GB floor", flush=True)
            break
        t0 = time.time()
        r = subprocess.run(["curl", "-sL", "-C", "-", "-o", out, BASE + name])
        if r.returncode == 0 and os.path.getsize(out) > 1e8:
            open(done, "w").write("ok")
            print(f"OK   {name}  {os.path.getsize(out)/1e9:.2f}GB in {(time.time()-t0)/60:.0f}min", flush=True)
        else:
            print(f"FAIL {name} rc={r.returncode} — will resume on rerun", flush=True)
            time.sleep(30)
    print("SHARD DOWNLOADS COMPLETE", flush=True)

if __name__ == "__main__":
    main()
