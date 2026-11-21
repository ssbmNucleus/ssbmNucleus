"""Dump the real Python bundle and a last-occurrence projection, plus raw truth."""
import argparse
from bisect import bisect_left
from pathlib import Path
import time
from common import ROOT, output_dir, read_json, write_json, select, fingerprint
from raw import scan


def canonical(bundle, fids):
    # Project the OUTPUT of build_viz_bundle, not a substitute implementation:
    # this preserves state-history decisions such as lightshield and categories.
    last = {f: i for i, f in enumerate(fids)}
    frames = sorted(last)
    keep = [last[f] for f in frames]
    old_to_new = {old: new for new, old in enumerate(keep)}

    def take(series):
        if series is None:
            return None
        vals = [series[i] for i in keep]
        return "".join(vals) if isinstance(series, str) else vals

    result = {**bundle, "meta": {**bundle["meta"], "start_frame": frames[0], "n": len(keep),
                                "finalized": all(b == a + 1 for a, b in zip(frames, frames[1:]))},
              "frames": {}, "items": []}
    for key, values in bundle["frames"].items():
        result["frames"][key] = ([{k: v if k == "of" else take(v) for k, v in follower.items()} for follower in values]
                                 if key == "fol" else [take(v) for v in values])
    # Row order can briefly reverse at a partial tail. Bisect on sorted row ids,
    # then sort canonical indices; never assume last-occurrence rows are monotone.
    sorted_rows = sorted(old_to_new)
    for item in bundle.get("items", []):
        a, b = item["f"], item["f"] + len(item["x"])
        indices = sorted(old_to_new[r] for r in sorted_rows[bisect_left(sorted_rows, a):bisect_left(sorted_rows, b)])
        runs = []
        for idx in indices:
            if not runs or idx != runs[-1][-1] + 1:
                runs.append([])
            runs[-1].append(idx)
        for run in runs:
            result["items"].append({"t": item["t"], "o": item["o"], "f": run[0],
                                    **{k: [item[k][keep[j] - a] for j in run] for k in ("x", "y", "d", "s")}})
    result["items"].sort(key=lambda t: t["f"])
    result["stage_state"] = {}
    new_of_frame = {fr: idx for idx, fr in enumerate(frames)}
    for kind, events in bundle.get("stage_state", {}).items():
        result["stage_state"][kind] = [[new_of_frame[fids[ev[0]]], *ev[1:]] for ev in events if 0 <= ev[0] < len(fids)]
    return result, frames, keep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest")
    ap.add_argument("--out")
    ap.add_argument("--shard", default="1/1")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    out = output_dir(args.out)
    manifest = read_json(Path(args.manifest) if args.manifest else out / "golden.json")
    games = select(manifest, args.shard, args.limit)
    from tracker.store.game_trace import _parse
    from tracker.video.viz_export import build_viz_bundle
    import importlib.metadata
    signature = fingerprint([Path(__file__), Path(__file__).with_name("raw.py"),
                             *[ROOT / p for p in ("app/backend/tracker/store/game_trace.py",
                               "app/backend/tracker/video/viz_export.py", "app/backend/tracker/video/stage_items.py",
                               "app/backend/tracker/video/interactions.py", "app/backend/tracker/stats/analyzer.py")]])
    version = importlib.metadata.version("peppi_py")
    ok = cached = errors = 0
    start = time.monotonic()
    for num, game in enumerate(games):
        if not game.get("eligible"):
            continue
        target = out / "truth" / (game["id"] + ".json.gz")
        producer_path = out / "python" / (game["id"] + ".json.gz")
        stat = Path(game["path"]).stat()
        stamp = {"source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns,
                 "extractor": signature, "peppi": version}
        if not args.refresh and target.exists() and producer_path.exists():
            previous = read_json(target)
            if previous.get("stamp") == stamp and previous.get("python_error") is None:
                cached += 1
                continue
        record = {"schema": 1, "path": game["path"], "id": game["id"], "stamp": stamp, "bundle": None}
        try:
            record["raw"] = scan(game["path"], detail=True)
            trace = _parse(game["path"])
            if trace is None:
                raise ValueError("Python trace unavailable: peppi rejected/panicked, empty, or unsupported replay")
            bundle = build_viz_bundle(trace)
            fids = trace.frame_ids[:trace.n] if trace.frame_ids else list(range(trace.start_frame, trace.start_frame + trace.n))
            record["bundle"], record["frame_ids"], record["last_rows"] = canonical(bundle, fids)
            record["row_fids"] = fids
            write_json(producer_path, bundle)
            ok += 1
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            record["python_error"] = f"{type(exc).__name__}: {exc}"
            errors += 1
            print(game["relative_path"], record["python_error"], flush=True)
        write_json(target, record)
        if (num + 1) % 10 == 0:
            print(f"Truth {num + 1}/{len(games)} ({time.monotonic() - start:.1f}s)", flush=True)
    print(f"Truth: {ok} dumped, {cached} cached, {errors} unavailable; {time.monotonic() - start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
