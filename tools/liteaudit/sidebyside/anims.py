"""Write the full slippilab animation pack of each internal character id to
<out>/<cid>.json, for wlshot.mjs. Packs already written are kept.

    python anims.py --out <dir> [--anim-zips DIR] cid [cid ...]
"""
import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract_anims import ZIP_NAMES                                  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--anim-zips", default=str(Path(os.environ.get("LOCALAPPDATA", "")) / "SSBM Nucleus/storage/nucleome/anim_zips"))
    ap.add_argument("cids", nargs="*", type=int)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for cid in a.cids:
        target = out / f"{cid}.json"
        if target.exists() or not 0 <= cid < len(ZIP_NAMES):
            continue
        # no extractall: zip member names never become filesystem paths
        with zipfile.ZipFile(Path(a.anim_zips) / f"{ZIP_NAMES[cid]}.zip") as z:
            pack = {n[:-5]: json.loads(z.read(n)) for n in z.namelist() if n.endswith(".json")}
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")
        tmp.replace(target)


if __name__ == "__main__":
    main()
