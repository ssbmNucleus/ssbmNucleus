"""
stress_build.py -- build a modded ISO with N costumes spammed onto one fighter,
for stress-testing the m-ex costume-count limit.

Copies the ready extracted base project (storage/test-base), imports `--count`
copies of `--zip` onto `--character` via mexcli, then exports an ISO. Prints the
per-import costume count so we can see exactly where (if anywhere) the count
stops incrementing / wraps / errors.

Run from backend/:
  python devtools/stress_build.py --character Fox --count 200 --out ../output/stress-fox-200.iso
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
from core.config import PROJECT_ROOT, STORAGE_PATH  # noqa: E402
import mexcli.commands  # noqa: E402

TEST_BASE = STORAGE_PATH / "test-base"
DEFAULT_ZIP = STORAGE_PATH / "Fox" / "plfxnr-plfxnr02.zip"  # smallest Fox costume (~105KB)


def log(m):
    print(m, flush=True)


def parse_json(text):
    """mexcli prints noise (e.g. 'Trimmed Image WxH') then a JSON result. Handle:
    (a) a trailing pretty-printed object, (b) compact one-object-per-line streams
    (export progress -> take the last), (c) a single whole-text object."""
    if not text:
        return None
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):       # (a) trailing pretty object
        s = lines[i]
        if s.strip() == "{" and not s.startswith((" ", "\t")):
            try:
                return json.loads("\n".join(lines[i:]))
            except Exception:
                break
    out = None                                    # (b) compact lines
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("{") and ln.endswith("}"):
            try:
                out = json.loads(ln)
            except Exception:
                pass
    if out is not None:
        return out
    try:                                          # (c) whole text
        return json.loads(text.strip())
    except Exception:
        return None


def costume_count(proj, character):
    cp = mexcli.commands.run(["list-fighters", proj], timeout=120, check=False)
    data = parse_json(cp.stdout) or {}
    for f in data.get("fighters", []):
        if str(f.get("name")) == character or str(f.get("internalId")) == str(character):
            return f.get("costumeCount")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--character", default="Fox")
    ap.add_argument("--characters", default=None,
                    help="comma list for ROSTER mode; each char uses its smallest vault zip")
    ap.add_argument("--zip", default=str(DEFAULT_ZIP))
    ap.add_argument("--count", type=int, default=8, help="how many costumes to import")
    ap.add_argument("--out", required=True)
    ap.add_argument("--projname", default="stress")
    # CSP compression (the automated ApplyCompression path). Defaults match the
    # app's normal export. NOTE: color-smash only actually runs when csp<1.0 OR
    # color-smash is false (a quirk of ExportCommand's gate), so to use color-smash
    # for real, pass e.g. --csp-compression 0.9 --color-smash true.
    ap.add_argument("--csp-compression", default="1.0")
    ap.add_argument("--color-smash", default="false")
    ap.add_argument("--skip-compression", default="false")
    ap.add_argument("--distinct", action="store_true",
                    help="roster: import DISTINCT vault zips per char (default: spam smallest)")
    ap.add_argument("--strip", default="",
                    help="comma list 'video,trophies' to delete from the base before importing (free disc)")
    ap.add_argument("--keep", action="store_true", help="keep the working project dir")
    args = ap.parse_args()

    zip_path = Path(args.zip).resolve()
    if not zip_path.exists():
        raise SystemExit(f"costume zip missing: {zip_path}")
    out_iso = Path(args.out).resolve()
    out_iso.parent.mkdir(parents=True, exist_ok=True)

    work = (STORAGE_PATH / "test-builds" / f"{args.projname}_proj").resolve()
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    log(f"copying base project {TEST_BASE} -> {work} ...")
    t0 = time.time()
    shutil.copytree(TEST_BASE, work)
    proj = str((work / "project.mexproj").resolve())
    log(f"  copied in {time.time()-t0:.1f}s")

    if args.strip:
        strip_cats = {s.strip() for s in args.strip.split(',') if s.strip()}
        freed = 0
        for p in (work / "files").rglob('*'):
            if p.is_file():
                nm = p.name.lower()
                cat = 'video' if nm.startswith('mv') else ('trophies' if nm.startswith('ty') else None)
                if cat in strip_cats:
                    freed += p.stat().st_size
                    p.unlink()
        log(f"  stripped {sorted(strip_cats)}: freed {freed/1024/1024:.0f} MiB")

    # Build per-character zip lists. Roster mode spreads across characters;
    # --distinct imports each char's distinct vault zips (realistic .dat sizes,
    # for the SIZE limit), else spams the smallest (isolates the COUNT limit).
    def zips_for(character, n):
        zs = sorted((STORAGE_PATH / character).glob("*.zip"), key=lambda p: p.stat().st_size)
        zs = [z.resolve() for z in zs]
        if not zs:
            return []
        return zs[:n] if args.distinct else [zs[0]] * n

    if args.characters:
        jobs = []
        for c in [x.strip() for x in args.characters.split(",") if x.strip()]:
            zl = zips_for(c, args.count)
            if not zl:
                log(f"  !! no vault zip for '{c}'; skipping")
                continue
            jobs.append((c, zl))
    else:
        jobs = [(args.character, [zip_path] * args.count)]
    total_imports = sum(len(zl) for _, zl in jobs)
    log(f"jobs: {[(c, len(zl)) for c, zl in jobs]}  total_imports={total_imports} distinct={args.distinct}")

    per_char = {}
    t_imp = time.time()
    done = 0
    for (c, zl) in jobs:
        ok_c = 0
        last_total = None
        for i, z in enumerate(zl):
            cp = mexcli.commands.run(["import-costume", proj, c, str(z)], timeout=300, check=False)
            data = parse_json(cp.stdout) or {}
            ok = bool(data.get("success"))
            last_total = data.get("totalCostumes")
            done += 1
            if ok:
                ok_c += 1
            else:
                log(f"  [{c}] import {i+1}/{len(zl)} FAILED: {data.get('error') or cp.stderr[:160]}")
                break
            if done % 25 == 0 or done == total_imports:
                el = time.time() - t_imp
                log(f"  progress {done}/{total_imports} ({c} {i+1}/{len(zl)}) "
                    f"elapsed={el:.0f}s ({el/max(done,1):.1f}s/ea) lastTotal={last_total}")
        per_char[c] = {"imported_ok": ok_c, "final_total": last_total}
    log(f"imports done in {time.time()-t_imp:.1f}s; per_char={json.dumps(per_char)}")
    final_count = (per_char.get(args.character, {}) or {}).get("final_total")

    log(f"exporting -> {out_iso} (csp={args.csp_compression} color-smash={args.color_smash} "
        f"skip={args.skip_compression}) ...")
    t_exp = time.time()
    cp = mexcli.commands.run(["export", proj, str(out_iso), args.csp_compression,
                     args.color_smash, args.skip_compression], timeout=3600, check=False)
    res = parse_json(cp.stdout) or {}
    log(f"export finished in {time.time()-t_exp:.1f}s success={res.get('success')} "
        f"status={res.get('status')} {res.get('error') or ''}")
    if cp.returncode != 0 and not res.get("success"):
        log(f"  export stderr: {cp.stderr[:500]}")

    if out_iso.exists():
        log(f"ISO: {out_iso}  size={out_iso.stat().st_size/1024/1024:.1f} MB")
    else:
        log("ISO NOT PRODUCED")

    summary = {
        "mode": "roster" if args.characters else "single",
        "characters": [c for c, _ in jobs],
        "per_char_requested": args.count,
        "total_imports": total_imports,
        "per_char": per_char,
        "final_count": final_count,
        "iso": str(out_iso),
        "iso_mb": round(out_iso.stat().st_size / 1024 / 1024, 1) if out_iso.exists() else None,
        "export_success": bool(res.get("success")),
    }
    log("SUMMARY " + json.dumps(summary))

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if out_iso.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
