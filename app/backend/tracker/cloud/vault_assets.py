"""vault_assets — build the static assets the mobile client needs.

Three kinds, all identical for every user, so they are shipped once with the
client rather than per-vault:

  packs/char-<internal id>.json.gz   full animation set for one character
  charmaps.json                      action->animation maps (88 KB)
  stock/<external id>-<costume>.png  stock icons for list rows
  stage/<stage id>.png               stage icons for list rows

Randall on Yoshi's Story is Watch Lite's own drawing (itemArt.js), so no sprite
ships; a sprite/ folder left in an old deploy directory can be deleted.

Two id spaces are in play and they are NOT the same numbering. Animation packs
are keyed by *internal* character id (what bundle.frames.cid holds, and what
slippilab's zips are indexed by). Stock icons are keyed by *external* id (what
games.players[].character holds, and what the /stock endpoint takes). Mixing
them silently yields the wrong character rather than an error.

Packs ship pre-gzipped because Pages would otherwise upload ~250 MB of raw JSON
to deliver the same bytes; the client inflates with DecompressionStream, which
it already does for clip bundles.
"""
import gzip
import json
import os
import urllib.request

from ..video import clip_render

BACKEND = os.environ.get("NUCLEUS_BACKEND", "http://127.0.0.1:5000")
API = f"{BACKEND}/api/nucleome"


def build_packs(out_dir, cids=None):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    ids = cids if cids is not None else range(len(clip_render._INT_TO_ZIP))
    for cid in ids:
        full = clip_render._load_char(cid)
        if not full:
            continue
        raw = json.dumps({str(cid): full}, separators=(",", ":")).encode()
        blob = gzip.compress(raw, 6)
        path = os.path.join(out_dir, f"char-{cid}.json.gz")
        with open(path, "wb") as f:
            f.write(blob)
        written.append((cid, len(full), len(blob)))
    return written


def build_charmaps(out_path):
    with open(clip_render.CHARMAPS_PATH, encoding="utf-8") as f:
        cm = json.load(f)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cm, f, separators=(",", ":"))
    return os.path.getsize(out_path)


def _fetch(url, path):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except Exception:                                         # noqa: BLE001
        return 0
    if not data:
        return 0
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def build_stocks(out_dir, pairs):
    """pairs = iterable of (external_char_id, costume)."""
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for ext, costume in pairs:
        p = os.path.join(out_dir, f"{ext}-{costume}.png")
        if os.path.exists(p):
            continue
        if _fetch(f"{API}/stock/{ext}/{costume}", p):
            n += 1
    return n


def build_stages(out_dir, stage_ids):
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for sid in stage_ids:
        p = os.path.join(out_dir, f"{sid}.png")
        if os.path.exists(p):
            continue
        if _fetch(f"{API}/stage-icon/{sid}", p):
            n += 1
    return n


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Build mobile vault static assets")
    ap.add_argument("out", help="output directory (the Pages site root)")
    ap.add_argument("--skip-icons", action="store_true",
                    help="packs + charmaps only; icons need the backend running")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)

    print("charmaps...")
    print(f"  {build_charmaps(os.path.join(args.out, 'charmaps.json')) / 1024:.0f} KB")

    print("animation packs...")
    total = 0
    for cid, n_anims, nbytes in build_packs(os.path.join(args.out, "packs")):
        total += nbytes
        print(f"  cid {cid:2d}  {n_anims:4d} anims  {nbytes / 1024 / 1024:5.2f} MB gz")
    print(f"  total {total / 1024 / 1024:.1f} MB")

    if args.skip_icons:
        return 0

    print("stock icons...")
    pairs = [(ext, c) for ext in range(26) for c in range(6)]
    print(f"  {build_stocks(os.path.join(args.out, 'stock'), pairs)} written")

    print("stage icons...")
    print(f"  {build_stages(os.path.join(args.out, 'stage'), range(0, 33))} written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
