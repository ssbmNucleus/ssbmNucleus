"""Cloud shard mining on Modal — the ~30-minute alternative to the ~16h
local churn. One container per shard: stream the tarball from HuggingFace,
mine every game through analyzer_v2, write rows JSONL to a Modal Volume.

Cost: analysis measures ~0.3 core-s/game -> a full-cast same-tier pass
(~760k games, ~70 core-hours) is roughly $10-25 of Modal CPU. Iteration
strategy: run single characters while the row schema is still moving
(--chars FOX,FALCO), save the full-cast run for a finalized schema.

Usage (never run without the user's go-ahead — it spends real money):
    modal run modal_mine.py --chars FALCO,FOX          # test slice
    modal run modal_mine.py --chars all                # full cast
    modal run modal_mine.py --chars all --sample 2     # N smallest/tier-pair

Afterwards, pull the rows and build packs locally:
    modal volume get melee-mine-rows / <local folder>
    venv/Scripts/python.exe build_packs_v2.py   # (set MELEE_MINE_ROWS to the pull)

Optional: a Modal secret named "huggingface" with HF_TOKEN avoids throttling
on wide fan-outs.
"""
import json
import os

import modal

# analyzer_v2.py sits next to this script (tools/rank-baselines/).
HERE = os.path.dirname(os.path.abspath(__file__))

HF_API = "https://huggingface.co/api/datasets/erickfm/melee-ranked-replays/tree/main/"
HF_DL = "https://huggingface.co/datasets/erickfm/melee-ranked-replays/resolve/main/"

CAST = ["FALCO", "FOX", "MARTH", "SHEIK", "CPTFALCON", "PEACH", "JIGGLYPUFF",
        "SAMUS", "ICE_CLIMBERS", "LUIGI", "DOC", "GANONDORF", "PIKACHU",
        "YOSHI", "DK", "LINK", "NESS", "MARIO", "MEWTWO", "YLINK",
        "BOWSER", "ROY", "GAMEANDWATCH", "ZELDA", "KIRBY", "PICHU"]
SAME_TIER = ("diamond-diamond", "master-master", "platinum-platinum")

app = modal.App("nucleome-shard-mine")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("peppi-py", "huggingface_hub", "hf_transfer")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .add_local_file(os.path.join(HERE, "analyzer_v2.py"), "/root/analyzer_v2.py")
)

rows_vol = modal.Volume.from_name("melee-mine-rows", create_if_missing=True)


@app.function(
    image=image,
    volumes={"/rows": rows_vol},
    cpu=8,
    memory=8192,
    timeout=3600,
    retries=modal.Retries(max_retries=2),
    # HF_TOKEN from the user's "huggingface" Modal secret — authenticated
    # downloads avoid rate limits on wide fan-outs
    secrets=[modal.Secret.from_name("huggingface")],
)
def mine_shard(char: str, fname: str):
    """Download one shard tarball from HF, mine it, write rows to the volume."""
    import glob
    import shutil
    import tarfile
    import time
    from concurrent.futures import ProcessPoolExecutor

    from huggingface_hub import hf_hub_download
    from analyzer_v2 import analyze_game

    name = fname[: -len(".tar.gz")]
    rows_path = f"/rows/{name}.jsonl"
    if os.path.exists(rows_path + ".done"):
        return {"shard": name, "skipped": True}

    t0 = time.time()
    # hf_hub_download speaks HF's xet CDN protocol (plain requests gets 403
    # from datacenter IPs); hf_transfer makes it saturate the pipe
    tar_path = hf_hub_download(
        repo_id="erickfm/melee-ranked-replays", repo_type="dataset",
        filename=f"{char}/{fname}", local_dir="/tmp/dl",
        token=os.environ.get("HF_TOKEN"))
    # PER-SHARD dir, pre-cleaned: Modal REUSES warm containers across map
    # inputs, so a shared extract dir accumulates previous shards and every
    # later shard re-mines them (duplicate rows + massively inflated cost)
    work = f"/tmp/shard-{name}"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(work, filter="data")
    shutil.rmtree("/tmp/dl", ignore_errors=True)
    dl_min = (time.time() - t0) / 60

    files = glob.glob(os.path.join(work, "**", "*.slp"), recursive=True)
    t1 = time.time()
    n_rows = 0
    with open(rows_path, "w", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=8) as ex:
            for rows in ex.map(analyze_game, files, chunksize=16):
                for row in rows:
                    row["shard"] = name
                    out.write(json.dumps(row) + "\n")
                    n_rows += 1
    with open(rows_path + ".done", "w") as f:
        f.write("ok")
    rows_vol.commit()
    shutil.rmtree(work, ignore_errors=True)   # container may live on — clean up
    return {"shard": name, "games": len(files), "rows": n_rows,
            "dl_min": round(dl_min, 1),
            "mine_min": round((time.time() - t1) / 60, 1)}


def _shard_list(char):
    import urllib.request
    with urllib.request.urlopen(HF_API + char, timeout=60) as r:
        files = json.load(r)
    return [(f["path"].split("/")[-1], f.get("size", 0)) for f in files
            if f.get("type") == "file" and f["path"].endswith(".tar.gz")]


@app.local_entrypoint()
def main(chars: str = "FALCO", sample: int = 0):
    cast = CAST if chars.lower() == "all" else [
        c.strip().upper() for c in chars.split(",") if c.strip()]
    jobs = []
    total = 0
    for char in cast:
        try:
            names = _shard_list(char)
        except Exception as e:
            print(f"LIST-FAIL {char}: {e}")
            continue
        for tier in SAME_TIER:
            pool = sorted((x for x in names if f"_{tier}_" in x[0]),
                          key=lambda x: x[1])
            if sample:
                pool = pool[:sample]
            jobs.extend((char, f) for f, s in pool)
            total += sum(s for _, s in pool)
    print(f"{len(jobs)} shards, {total/1e9:.0f} GB queued on Modal")
    done = 0
    for result in mine_shard.starmap(jobs, return_exceptions=True):
        done += 1
        print(f"[{done}/{len(jobs)}]", result)
    print("MODAL MINING COMPLETE — pull rows with:")
    print("  modal volume get melee-mine-rows / <local folder>  (then MELEE_MINE_ROWS=<local folder>)")
