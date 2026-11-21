"""Read only local animation zips, extracting selected characters into scratch."""
import argparse
import os
from pathlib import Path
import zipfile
import json
from common import output_dir, read_json, write_json, select

ZIP_NAMES = ["mario", "fox", "captainFalcon", "donkeyKong", "kirby", "bowser", "link", "sheik", "ness",
             "peach", "iceClimbers", "iceClimbers", "pikachu", "samus", "yoshi", "jigglypuff", "mewtwo",
             "luigi", "marth", "zelda", "youngLink", "doctorMario", "falco", "pichu", "mrGameAndWatch", "ganondorf", "roy"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest")
    ap.add_argument("--out")
    ap.add_argument("--shard", default="1/1")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--anim-zips", default=str(Path(os.environ.get("LOCALAPPDATA", "")) / "SSBM Nucleus/storage/nucleome/anim_zips"))
    args = ap.parse_args()
    out = output_dir(args.out)
    games = select(read_json(Path(args.manifest) if args.manifest else out / "golden.json"), args.shard, args.limit)
    need = set()
    for game in games:
        path = out / "truth" / (game["id"] + ".json.gz")
        if not path.exists():
            continue
        truth = read_json(path)
        bundle = truth.get("bundle")
        if not bundle:
            # JS-only playable files still get real animations for their cids.
            need.update(truth.get("raw", {}).get("chars_internal", []))
            if truth.get("raw", {}).get("follower_posts"):
                need.add(11)
            continue
        # Python playback still draws speculative rollback rows. Include cids
        # from its full output so transforms on those rows have real geometry.
        bundle = read_json(out / "python" / (game["id"] + ".json.gz"))
        f = bundle["frames"]
        actors = list(zip(f["cid"], f["state"])) + [(x["cid"], x["state"]) for x in f.get("fol", [])]
        for cids, _ in actors:
            need.update(cid for cid in cids if cid is not None)
    status = {}
    for cid in sorted(need):
        if not 0 <= cid < len(ZIP_NAMES):
            status[str(cid)] = {"error": "custom cid has no stock animation archive"}
            continue
        source = Path(args.anim_zips) / (ZIP_NAMES[cid] + ".zip")
        target = out / "anims" / args.shard.replace("/", "-") / f"{cid}.json.gz"
        cache_meta = target.with_name(f"{cid}.meta.json")
        try:
            stat = source.stat()
            stamp = {"source": str(source.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "full_archive": True}
            if target.exists() and cache_meta.exists():
                cached = read_json(cache_meta)
                if cached.get("stamp") == stamp:
                    status[str(cid)] = cached["status"]
                    continue
            # No extractall: zip member names never become filesystem paths.
            # Include the complete character archive. The real renderer can
            # choose fallback poses absent from charmaps; trimming by state
            # would create harness-only dots and make shard counts disagree.
            with zipfile.ZipFile(source) as archive:
                pack = {name[:-5]: json.loads(archive.read(name)) for name in archive.namelist()
                        if name.endswith(".json")}
            write_json(target, pack)
            status[str(cid)] = {"source": str(source), "animations": len(pack), "full_archive": True}
            write_json(cache_meta, {"stamp": stamp, "status": status[str(cid)]})
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            # Overwrite any old pack so a missing archive cannot look like success.
            write_json(target, {})
            status[str(cid)] = {"source": str(source), "error": str(exc)}
            write_json(cache_meta, {"stamp": None, "status": status[str(cid)]})
    write_json(out / f"animations-{args.shard.replace('/', '-')}.json", status)
    print(f"Animation packs: {sum('error' not in v for v in status.values())} loaded; {sum('error' in v for v in status.values())} unavailable", flush=True)


if __name__ == "__main__":
    main()
