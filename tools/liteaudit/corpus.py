"""Inventory a replay directory (never the repo), then select a stable golden set."""
import argparse
import hashlib
import os
from pathlib import Path
from common import ROOT, output_dir, read_json, write_json, fingerprint
from raw import scan
from tracker.store.slp_meta import parse_slp


def golden(games, size):
    candidates = [g for g in games if g["eligible"]]
    chosen, reasons, missing = {}, {}, []

    def add(g, why):
        chosen[g["id"]] = g
        reasons.setdefault(g["id"], []).append(why)

    # Coverage comes before filling by hash. Ranking ties use the relative path,
    # so a copied replay tree yields the same subset on another machine.
    def cover(label, pred, score=lambda g: g["raw"]["unique_frames"]):
        options = [g for g in candidates if pred(g)]
        if options:
            add(sorted(options, key=lambda g: (-score(g), g["relative_path"].casefold()))[0], label)
        else:
            missing.append(label)

    worst = sorted(candidates, key=lambda g: (-g["raw"]["rollback_rows"], g["relative_path"].casefold()))
    for g in [g for g in worst if g["raw"]["rollback_rows"]][:6]:
        add(g, "worst rollback rows")
    for stage in sorted({g["stage"] for g in candidates} | {2, 3, 8, 23, 28}):
        cover(f"stage {stage}", lambda g, s=stage: g["stage"] == s)
    for cid, name in ((10, "Ice Climbers"), (9, "Peach"), (13, "Samus"),
                      (6, "Link"), (20, "Young Link"), (24, "Game & Watch")):
        cover(name, lambda g, c=cid: c in g["raw"]["chars_internal"])
    cover("Zelda/Sheik transforms", lambda g: g["raw"]["transforms"])
    cover("Ice Climbers follower", lambda g: g["raw"]["follower_posts"] > 0)
    for cid, name in ((1, "Fox"), (22, "Falco")):
        cover(f"laser-heavy {name}", lambda g, c=cid: c in g["raw"]["chars_internal"],
              lambda g: g["raw"]["laser_events"])
    cover("four ports", lambda g: len(g["players"]) == 4)
    cover("netplay", lambda g: g["netplay"])
    for g in sorted(candidates, key=lambda g: g["id"]):
        if len(chosen) >= size:
            break
        if g["id"] not in chosen:
            add(g, "stable hash fill")
    return {"games": [{**g, "selection_reasons": reasons[g["id"]]} for g in sorted(chosen.values(), key=lambda g: g["relative_path"].casefold())],
            "requested_size": size, "missing_coverage": missing, "eligible_count": len(candidates)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path.home() / "OneDrive/Documents/Slippi"))
    ap.add_argument("--out")
    ap.add_argument("--size", type=int, default=40)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    root, out = Path(args.root).resolve(), output_dir(args.out)
    if ROOT.is_relative_to(root) or root.is_relative_to(ROOT):
        raise ValueError("replay root must be outside the repo; no repository tree walks")
    if not root.is_dir():
        raise ValueError(f"replay root is not a directory: {root}")
    signature = fingerprint([Path(__file__), Path(__file__).with_name("raw.py"), ROOT / "app/backend/tracker/store/slp_meta.py"])
    old = read_json(out / "corpus.json") if (out / "corpus.json").exists() else {}
    cache = {g["path"]: g for g in old.get("games", [])} if old.get("scanner") == signature and not args.refresh else {}
    games = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs.sort(key=str.casefold)
        for name in sorted(names, key=str.casefold):
            if not name.lower().endswith(".slp"):
                continue
            path = Path(directory) / name
            stat = path.stat()
            hit = cache.get(str(path))
            if hit and hit["size"] == stat.st_size and hit["mtime_ns"] == stat.st_mtime_ns:
                games.append(hit)
                continue
            rel = path.relative_to(root).as_posix()
            row = {"id": hashlib.sha256(rel.encode()).hexdigest()[:16], "path": str(path),
                   "relative_path": rel, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "eligible": False}
            try:
                meta = parse_slp(str(path))
                row.update(stage=meta["stage"], players=meta["players"], version=meta["version"],
                           netplay=meta["played_on"] == "slippi" or any(p.get("code") for p in meta["players"]),
                           chars=[p["character"] for p in meta["players"]])
                if 2 <= len(meta["players"]) <= 4:
                    row["raw"] = scan(path)
                    row["eligible"] = row["raw"]["unique_frames"] > 0 and row["raw"]["version"] >= [2, 0, 0]
                else:
                    row["excluded"] = "requires 2-4 players"
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            games.append(row)
    games.sort(key=lambda g: g["relative_path"].casefold())
    base = {"schema": 1, "root": str(root), "scanner": signature}
    write_json(out / "corpus.json", {**base, "games": games})
    subset = golden(games, args.size)
    write_json(out / "golden.json", {**base, **subset})
    print(f"Corpus: {len(games)} files, {subset['eligible_count']} eligible; golden: {len(subset['games'])}; missing coverage: {subset['missing_coverage']}", flush=True)


if __name__ == "__main__":
    main()
