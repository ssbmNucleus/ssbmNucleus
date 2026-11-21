"""csp_debug.py -- one-stop diagnostic for "this costume's CSP looks wrong".

The CSP/stock portraits are produced by `generate_csp.py` -> `HSDRawViewer.exe --csp`
(the headless renderer in <ssbmNucleus-hsdlib>/HSDRawViewer/). When a portrait renders
wrong (black blob, white blob, missing part, blank, wrong eyes...), this tool gathers the
evidence needed to localize the bug to ONE of the known classes (see KNOWN_CAUSES below)
or flag it as new.

What it does for a costume:
  1. Resolves it to a DAT (accepts a vault slot "Char/slot-id", a .zip, or a .dat).
  2. Probes structure: roots, JOBJ/DObj counts, texture-format histogram, how many
     UNIQUE pixel blobs vs UNIQUE TLUTs vs unique (pixel,tlut) PAIRS (the Vader tell),
     how many textures are decodable and white/dark/colored, mexCostume accessories,
     matanim presence.
  3. Renders the CSP three ways into <outdir>/<name>/: normal, no-hide (all hiding
     disabled via `--hide-dobjs 9999`), and -- if a vault zip -- copies the bundled csp.png.
  4. Prints a heuristic diagnosis pointing at the likely cause class.

Usage (run with the repo `python`, from anywhere):
  python utility/tools/processor/csp_debug.py "Marth/plmsgr-plmsgr01"        # installed vault
  python utility/tools/processor/csp_debug.py path/to/PlXxYyMod.dat
  python utility/tools/processor/csp_debug.py costume.zip --vault "C:\\...\\storage"
  python utility/tools/processor/csp_debug.py "Fox/shitslippy-plfxsp" --no-render   # probe only

Default vault: the installed app vault `%LOCALAPPDATA%\\SSBM Nucleus\\storage`
(NOT the repo `storage/` -- that is the dev copy and often differs from what the user sees).

See docs/dev/CSP_RENDERING_DEBUG.md for the full workflow + known-cause table + fixes.
"""
import argparse
import glob
import os
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent              # ssbmNucleus/
sys.path.insert(0, str(HERE))                 # generate_csp
sys.path.insert(0, str(REPO / "backend"))     # shared.rendering.datprobe

from shared.rendering.datprobe import DatFile, decode_image  # noqa: E402

DEFAULT_VAULT = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "SSBM Nucleus" / "storage"

KNOWN_CAUSES = """\
KNOWN CAUSE CLASSES (fixed ones live in HSDRawViewer; see csp-renderer-edge-case-fixes memory):
  A. black/colored BLOB, many tex but few unique pixel blobs + many TLUTs  -> palette-swatch
     model + image-only texture cache collapsed them. FIXED (cache key = (img,tlut)).
  B. missing separate-root / m-ex accessory (cap, Navi, cape) -> mexCostume.Accessories[]
     not rendered. FIXED (splice + AttachBone follow). Check 'mexCostume accessories' below.
  C. blank/grey EYES -> real eye only in *_matanim_joint, CSP applied no matanim. FIXED
     (matanim now applied at frame 0). Check 'matanim' below.
  D. body PART or WHOLE model MISSING but textures are fine -> over-hiding: scene yml
     hiddenNodes / low_poly_dobjs derived from VANILLA Pl<XX>.dat are wrong for a custom /
     reordered model. Compare normal vs no-hide render. (low_poly hide list robustness.)
  E. WHITE blobs from UNDECODABLE textures -> rare; C# decodes most. Usually really cause G.
  F. model BLANK / only a stray part even with no-hide, but the DAT HAS pobj pointers ->
     POBJ attribute list missing its GX_VA_NULL terminator -> GX_DisplayList reads 0 prims.
     FIXED (RenderDObj.cs appends the terminator). Run with CSP_DOBJ_DEBUG=1 to see skips.
  G. flat WHITE/DARK silhouette (form ok, no texture detail) or flat-white parts -> material
     uses multi-texturing (2nd texmap/TEX1) and/or normal-based texgen (GX_TG_NRM, sphere/env
     map); the CSP shader's TEV samples wrong -> base texture not applied. OPEN (needs GX
     texgen + multi-stage TEV in the shader).

Set CSP_DOBJ_DEBUG=1 for per-render [cspdbg]/[texdbg]/[texfail]/pobj-skip logging.
"""


def resolve_dat(target, vault, workdir):
    """Return (dat_path, bundled_csp_or_None, label)."""
    p = Path(target)
    # vault slot form "Char/slot-id"
    if not p.exists() and "/" in target and not target.lower().endswith((".dat", ".zip")):
        cand = vault / (target + ".zip")
        if cand.exists():
            p = cand
    if not p.exists():
        raise SystemExit(f"not found: {target} (looked in {vault})")
    label = p.stem
    if p.suffix.lower() == ".dat":
        return p, None, label
    if p.suffix.lower() == ".zip":
        sub = workdir / label
        sub.mkdir(parents=True, exist_ok=True)
        bundled = None
        with zipfile.ZipFile(p) as zf:
            dats = [n for n in zf.namelist() if n.lower().endswith(".dat")]
            if not dats:
                raise SystemExit(f"no .dat in {p}")
            zf.extract(dats[0], sub)
            if "csp.png" in zf.namelist():
                zf.extract("csp.png", sub)
                bundled = sub / "csp.png"
        return sub / dats[0], bundled, label
    raise SystemExit(f"unsupported target: {target}")


def _mean(rows):
    px = [c for r in rows for c in r]
    n = len(px) or 1
    return (sum(c[0] for c in px) // n, sum(c[1] for c in px) // n, sum(c[2] for c in px) // n)


def probe(dat_path):
    d = DatFile(dat_path)
    roots = [r[0] for r in d.roots]
    print(f"  roots ({len(roots)}): {', '.join(roots)}")
    body = d.find_roots("_Share_joint")
    if not body:
        print("  !! no *_Share_joint root -- renderer may find nothing (cause F)")
        return
    body = body[0][1]
    jobjs = d._iter_tree(body, 0x08, 0x0C)

    # texture walk
    pix, tlut, pairs, fmts = set(), set(), set(), {}
    ndobj = ntex = 0
    for j in jobjs:
        dobj = d.ptr(j + 0x10)
        while dobj is not None:
            ndobj += 1
            mobj = d.ptr(dobj + 0x08)
            if mobj is not None:
                tobj = d.ptr(mobj + 0x08)
                while tobj is not None:
                    io, to = d.ptr(tobj + 0x4C), d.ptr(tobj + 0x50)
                    if io is not None:
                        ntex += 1
                        img = d.image_at(io)
                        fmts[img.format] = fmts.get(img.format, 0) + 1
                        tl = d.ptr(to) if to else None
                        pix.add(d.ptr(io)); tlut.add(tl); pairs.add((d.ptr(io), tl))
                    tobj = d.ptr(tobj + 0x04)
            dobj = d.ptr(dobj + 0x04)

    # decodability + color of unique textures
    seen = set(); nw = nb = col = err = 0
    for t in d.jobj_textures(body):
        k = t.image.data_offset
        if k in seen:
            continue
        seen.add(k)
        try:
            c = _mean(decode_image(t.image, t.tlut))
            if min(c) > 200:
                nw += 1
            elif max(c) < 40:
                nb += 1
            else:
                col += 1
        except Exception:
            err += 1

    print(f"  geometry: {len(jobjs)} JOBJ, {ndobj} DObj, {ntex} texture refs")
    print(f"  textures: unique pixel-blobs={len(pix)}  unique TLUTs={len(tlut)}  unique (pix,tlut) pairs={len(pairs)}")
    print(f"  formats : {fmts}   (14=CMPR 9=CI8 8=CI4 6=RGBA8 5=RGB5A3 1=I8 0=I4)")
    print(f"  decoded : white(>200)={nw}  dark(<40)={nb}  colored={col}  UNDECODABLE={err}")
    mex = next((r for r in d.roots if r[0] == "mexCostume"), None)
    if mex:
        sym = mex[1]
        cnt = d.u32(sym + 0x08)
        print(f"  mexCostume accessories: AccessoryCount={cnt} (cause B if a cap/companion is missing)")
    print(f"  matanim root: {'yes' if any('matanim' in r for r in roots) else 'NO'} (cause C if eyes are grey/blank)")

    # heuristic hints
    hints = []
    if len(pairs) > len(pix) * 2 and fmts.get(9, 0) + fmts.get(8, 0) > 0:
        hints.append("A: many TLUTs share few pixel-blobs -> swatch model (should be FIXED; if not, verify build)")
    if err > 0:
        hints.append(f"E: {err} UNDECODABLE textures -> likely white blobs on those parts")
    if mex:
        hints.append("B: has m-ex accessories -> confirm they appear in the render")
    if hints:
        print("  hints: " + " | ".join(hints))


def render(dat_path, name, outdir, no_render):
    if no_render:
        return
    import generate_csp
    sub = outdir / name
    sub.mkdir(parents=True, exist_ok=True)
    work = sub / Path(dat_path).name
    if Path(dat_path).resolve() != work.resolve():
        shutil.copy2(dat_path, work)

    out = generate_csp.generate_csp(str(work), scale=2)
    if out and os.path.exists(out):
        shutil.copy2(out, sub / "render_normal.png")
        print(f"  render (normal) -> {sub / 'render_normal.png'}")

    # no-hide: --hide-dobjs 9999 overrides scene hiddenNodes + low-poly with a no-op
    orig_c = generate_csp.curated_hide_override
    orig_l = generate_csp.low_poly_dobjs
    try:
        generate_csp.curated_hide_override = lambda *a, **k: "9999"
        generate_csp.low_poly_dobjs = lambda *a, **k: "9999"
        out2 = generate_csp.generate_csp(str(work), scale=2)
        if out2 and os.path.exists(out2):
            shutil.copy2(out2, sub / "render_nohide.png")
            print(f"  render (no-hide) -> {sub / 'render_nohide.png'}")
            print("  -> if no-hide shows the missing part, the hide list is wrong (cause D)")
    finally:
        generate_csp.curated_hide_override = orig_c
        generate_csp.low_poly_dobjs = orig_l


def main():
    ap = argparse.ArgumentParser(description="Diagnose a costume's CSP render.")
    ap.add_argument("target", help='vault slot "Char/slot-id", a .zip, or a .dat')
    ap.add_argument("--vault", default=str(DEFAULT_VAULT), help="vault storage dir")
    ap.add_argument("--outdir", default=None, help="where to write renders")
    ap.add_argument("--no-render", action="store_true", help="probe only, skip rendering")
    args = ap.parse_args()

    outdir = Path(args.outdir) if args.outdir else (Path.cwd() / "csp_debug_out")
    outdir.mkdir(parents=True, exist_ok=True)
    dat, bundled, label = resolve_dat(args.target, Path(args.vault), outdir)
    print(f"== {label}\n  dat: {dat}")
    if bundled:
        sub = outdir / label; sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, sub / "bundled_current.png")
        print(f"  bundled (current) csp -> {sub / 'bundled_current.png'}")
    probe(dat)
    render(dat, label, outdir, args.no_render)
    print("\n" + KNOWN_CAUSES)


if __name__ == "__main__":
    main()
