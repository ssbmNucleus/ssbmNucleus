"""Compare two verify_memory_input runs without launching Dolphin.

Exit 0: complete, background input/state/pixel parity. Exit 1: incomplete or
input/state/config mismatch. Exit 2: input/state match, but PNGs need review.
Raw pointers and global game-frame counters are deliberately not compared.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops


STATE_FIELDS = ("state", "state_name", "anim_frame", "move_frame", "facing", "x", "y", "airborne", "port")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def pad_samples(receipt):
    return [{"char": sample["char"], "commands": sample["commands"],
             "raw": next(block["raw"] for block in sample["evidence"]["raw_blocks"]
                         if block["name"] == "hsd_pad_game_status")}
            for sample in receipt["input_samples"]]


def compare(baseline, candidate):
    a, b = read(baseline / "verification.json"), read(candidate / "verification.json")
    report = {"baseline": str(baseline), "candidate": str(candidate), "runs": [], "captures": []}
    for receipt in (a, b):
        targets = receipt["targets"]
        focus = receipt["focus_samples"]
        complete = (receipt["success"] and receipt["cleanup"]["owned_process_exited"]
                    and {t["char"] for t in targets} == {"marth", "mario", "fox"}
                    and len(targets) == 3
                    and all(len(t["images"]) == 4 and not any(t[k] for k in
                            ("failures", "broken", "unproven", "missing", "cached")) for t in targets))
        report["runs"].append({"backend": receipt["backend"], "complete": bool(complete),
            "dolphin_pid": receipt["dolphin_pid"], "lock_slot": receipt["lock_slot"],
            "started_utc": receipt["started_utc"], "ready_utc": receipt["ready_utc"],
            "finished_utc": receipt["finished_utc"], "focus_samples": len(focus),
            "all_unfocused": bool(focus) and all(s["foreground"] != s["dolphin"] for s in focus)})
    report["config_equal"] = all(a.get(k) == b.get(k) for k in
                                   ("iso", "executable_sha256", "deterministic_visuals"))
    report["executable_sha256"] = a["executable_sha256"]
    report["pad_samples"] = {"baseline": pad_samples(a), "candidate": pad_samples(b)}
    report["pad_equal"] = (len(report["pad_samples"]["baseline"]) == 6
                           and report["pad_samples"]["baseline"] == report["pad_samples"]["candidate"])
    for char in ("marth", "mario", "fox"):
        for move, frame in (("jab", 3), ("ftilt", 4), ("fair", 4), ("upb", 5)):
            relative = Path(char) / f"{char}-{move}.json"
            sa, sb = read(baseline / relative), read(candidate / relative)
            ca, cb = sa["captures"], sb["captures"]
            state_equal = (len(ca) == len(cb) == 1 and
                           all(ca[0][k] == cb[0][k] for k in STATE_FIELDS) and
                           all(sa[k] == sb[k] for k in ("char", "ckind", "color", "move", "stage")))
            relative = Path(char) / f"{char}-{move}-f{frame:02d}.png"
            with Image.open(baseline / relative) as ia, Image.open(candidate / relative) as ib:
                pa, pb = ia.convert("RGB"), ib.convert("RGB")
                bounds = ImageChops.difference(pa, pb).getbbox() if pa.size == pb.size else "size differs"
                report["captures"].append({"file": relative.as_posix(), "state_equal": state_equal,
                    "pixel_equal": bounds is None, "difference_bounds": bounds,
                    "baseline_pixel_sha256": hashlib.sha256(pa.tobytes()).hexdigest(),
                    "candidate_pixel_sha256": hashlib.sha256(pb.tobytes()).hexdigest()})
    report["input_and_state_match"] = (report["config_equal"] and report["pad_equal"]
        and all(r["complete"] and r["all_unfocused"] for r in report["runs"])
        and all(c["state_equal"] for c in report["captures"]))
    report["pixel_matches"] = sum(c["pixel_equal"] for c in report["captures"])
    report["exit_code"] = (1 if not report["input_and_state_match"] else
                           0 if report["pixel_matches"] == 12 else 2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    options = parser.parse_args()
    try:
        report = compare(options.baseline.resolve(), options.candidate.resolve())
    except (OSError, KeyError, IndexError, ValueError, StopIteration) as exc:
        report = {"exit_code": 1, "error": f"Incomplete evidence: {exc}"}
    print(json.dumps(report, indent=2))
    raise SystemExit(report["exit_code"])


if __name__ == "__main__":
    main()
