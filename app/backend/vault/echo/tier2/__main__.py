"""python -m vault.echo.tier2 <verb>

  info                                   MexTK / devkitPPC / DOL / symbols availability
  scaffold --donor Ms --out DIR          write fighter.h / fighter.c / moves.c (+ helpers)
           [--dol main.dol] [--name "Shulk"] [--fighter-json f.json] [--pl PlMs.dat]
  compile  DIR [--out ftFunction.dat]    compile only (errors -> exit 1)
  build    DONOR_PL DIR OUT_PL           compile + append the ftFunction root to a Pl DAT

Donor lookup without explicit files: storage/echo/donors/Pl<Xx>.zip (the
export-fighter cache vault/echo/donors.py keeps); the DOL comes from --dol, any
projects/*/sys/main.dol, or the recorded vanilla ISO.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

from . import build, codegen

BACKEND = Path(__file__).resolve().parents[3]
NUCLEUS = BACKEND.parent


def _find_dol(explicit: str | None) -> bytes:
    if explicit:
        return Path(explicit).read_bytes()
    for p in sorted((NUCLEUS / "projects").glob("*/sys/main.dol")):
        return p.read_bytes()
    try:
        sys.path.insert(0, str(BACKEND))
        from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
        iso = known_vanilla_iso()
        if iso:
            return codegen.read_dol_from_iso(iso)
    except Exception:
        pass
    raise SystemExit("no main.dol: pass --dol, open a project, or record the vanilla ISO")


def _donor_files(donor: str, fighter_json: str | None, pl: str | None) -> tuple[dict, bytes | None]:
    if fighter_json:
        fj = json.loads(Path(fighter_json).read_text(encoding="utf-8"))
        return fj, Path(pl).read_bytes() if pl else None
    key = donor.strip()
    prefix = key[2:4] if key.lower().startswith("pl") and len(key) >= 4 else key
    cands = [NUCLEUS / "storage" / "echo" / "donors" / f"Pl{prefix}.zip"]
    if len(prefix) != 2:  # a fighter name: search the cache's fighter.json names
        cands = sorted((NUCLEUS / "storage" / "echo" / "donors").glob("Pl??.zip"))
    for z in cands:
        if not z.is_file():
            continue
        with zipfile.ZipFile(z) as zf:
            fj = json.loads(zf.read("fighter.json").decode("utf-8"))
            if len(prefix) != 2 and (fj.get("name") or "").lower() != key.lower():
                continue
            pl_name = (fj.get("files") or {}).get("fighterDataPath")
            pl_bytes = zf.read(pl_name) if pl_name and pl_name in zf.namelist() else None
            return fj, pl_bytes
    raise SystemExit(f"donor {donor!r} not in storage/echo/donors (export it once via the Echo "
                     "blueprint, or pass --fighter-json/--pl)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m vault.echo.tier2")
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("info")
    s = sub.add_parser("scaffold")
    s.add_argument("--donor", required=True, help="Pl prefix (Ms) or fighter name (Marth)")
    s.add_argument("--out", required=True)
    s.add_argument("--dol"); s.add_argument("--name"); s.add_argument("--fighter-json"); s.add_argument("--pl")
    s.add_argument("--no-symbols", action="store_true")
    c = sub.add_parser("compile"); c.add_argument("dir"); c.add_argument("--out")
    b = sub.add_parser("build"); b.add_argument("donor_pl"); b.add_argument("dir"); b.add_argument("out_pl")
    ns = ap.parse_args(argv)

    if ns.verb == "info":
        info = build.mextk_info()
        info["symbols"] = str(codegen.find_symbols_file() or "")
        try:
            info["dol_bytes"] = len(_find_dol(None))
        except SystemExit as e:
            info["dol_bytes"] = 0
            info["dol_error"] = str(e)
        print(json.dumps(info, indent=2))
        return 0
    if ns.verb == "scaffold":
        fj, pl = _donor_files(ns.donor, ns.fighter_json, ns.pl)
        dol = _find_dol(ns.dol)
        sym = None
        if not ns.no_symbols:
            sf = codegen.find_symbols_file()
            sym = codegen.load_symbols(sf) if sf else None
        files = codegen.scaffold(fj, dol, pl, sym, name=ns.name)
        out = Path(ns.out); out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
        for helper in build.INCLUDE_DIR.glob("*.c"):
            (out / helper.name).write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps({"out": str(out), "files": sorted(p.name for p in out.iterdir()),
                          "donor": fj.get("name"), "states": (files["fighter.c"].count("/* state "))}))
        return 0
    try:
        if ns.verb == "compile":
            data = build.compile_dir(ns.dir)
            if ns.out:
                Path(ns.out).write_bytes(data)
            print(json.dumps({"ok": True, "bytes": len(data), "out": ns.out}))
            return 0
        if ns.verb == "build":
            out = build.build_pl(Path(ns.donor_pl).read_bytes(), ns.dir)
            Path(ns.out_pl).write_bytes(out)
            print(json.dumps({"ok": True, "out": ns.out_pl, "bytes": len(out)}))
            return 0
    except build.BuildError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
