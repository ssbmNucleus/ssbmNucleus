"""Third shard train -> $MELEE_SHARDS: ALL non-Falco character folders,
priority-ordered. Enumerates each character's shards from the HF API so
nothing is guessed. Stops at 150GB free-space floor."""
import json, os, subprocess, sys, time, urllib.request
import fetch_shards as fs

SHARDS = os.environ.get("MELEE_SHARDS") or os.path.join(os.path.expanduser("~"), "melee-shards")

# priority: user's opponents/mains first, then playerbase size (~folder size)
CHARS = ["MARTH", "FOX", "SHEIK", "CPTFALCON", "PEACH", "JIGGLYPUFF",
         "SAMUS", "ICE_CLIMBERS", "LUIGI", "DOC", "GANONDORF", "PIKACHU",
         "YOSHI", "DK", "LINK", "NESS", "MARIO", "MEWTWO", "YLINK",
         "BOWSER", "ROY", "GAMEANDWATCH", "ZELDA", "KIRBY", "PICHU"]

def shard_list(char):
    url = f"https://huggingface.co/api/datasets/erickfm/melee-ranked-replays/tree/main/{char}"
    with urllib.request.urlopen(url, timeout=60) as r:
        files = json.load(r)
    return [f["path"].split("/")[-1] for f in files
            if f.get("type") == "file" and f["path"].endswith(".tar.gz")]

def main():
    fs.DEST = SHARDS
    fs.MIN_FREE_GB = 150
    for char in CHARS:
        try:
            names = shard_list(char)
        except Exception as e:
            print(f"LIST-FAIL {char}: {e} — retry in 60s", flush=True)
            time.sleep(60)
            try:
                names = shard_list(char)
            except Exception as e2:
                print(f"LIST-FAIL {char} again: {e2} — skipping", flush=True)
                continue
        print(f"=== {char}: {len(names)} shards", flush=True)
        fs.BASE = f"https://huggingface.co/datasets/erickfm/melee-ranked-replays/resolve/main/{char}/"
        fs.SHARDS = names
        fs.main()
        if fs.free_gb(fs.DEST) < fs.MIN_FREE_GB:
            print("FLOOR REACHED — stopping character queue", flush=True)
            break
    print("CHARACTER SHARD QUEUE COMPLETE", flush=True)

if __name__ == "__main__":
    main()
