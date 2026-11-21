"""
compute_texture_table.py -- build the index -> Dolphin-filename table PURELY by
computation: NO Dolphin, NO ISO, NO harvest. This is the endgame of the texture-
pack automation -- it reproduces, from first principles, the exact filename
Dolphin would dump for each costume placeholder.

The chain (all validated bit-exact against 124 harvested ground-truth pairs):
  index N
    -> generate_encoded_placeholder(N)          (the deterministic 16x16 PNG)
    -> mexcli placeholder-bytes                  (the REAL CSP encode: CI8 image
                                                  + RGB5A3 256-entry palette, the
                                                  same ImageConverter.FromPNG path
                                                  the texture-pack export uses)
    -> texHash  = XXH64(imageData, 256, seed=0)
       tlutHash = XXH64(palette[2*min : 2*(max+1)], seed=0)   (Dolphin hashes only
                                                  the USED palette index range)
    -> tex1_16x16_<texHash>_<tlutHash>_9.png

Dolphin (incl. this Slippi build) names CI8 textures by XXH64 of the texture data
and of the used-palette subset; format 9 = CI8. Because the placeholder for index
N is byte-identical in every build, this filename is a pure function of N -- so the
whole table can be generated offline and reused for any build forever.

    python compute_texture_table.py --max 200 [--out table.json] [--verify]
    python compute_texture_table.py --indices 36,37,38 --verify

--max N        compute indices 0..N
--indices a,b  compute a specific set
--out PATH     write table (default app/scratch/ingame/nucleus/texture_filename_table_computed.json)
--verify       compare against the harvested table and report matches/mismatches
--merge        merge into the --out table instead of overwriting
"""

import json
import os
import subprocess
import sys
import tempfile

import xxhash

# backend texture_pack.generate_encoded_placeholder is the placeholder source of truth
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "app"))  # the app/ folder
sys.path.insert(0, os.path.join(REPO, "backend"))
from projects.install.texture_pack import generate_encoded_placeholder  # noqa: E402

MEXCLI = os.path.join(REPO, "utility", "mex", "win-x64", "mexcli.exe")
HARVESTED = os.path.join(REPO, "scratch", "ingame", "nucleus", "texture_filename_table.json")
DEFAULT_OUT = os.path.join(REPO, "scratch", "ingame", "nucleus", "texture_filename_table_computed.json")


def x64(b):
    return format(xxhash.xxh64(b, seed=0).intdigest(), "016x")


def encoded_bytes(index, tmpdir):
    """Run the real CSP encoder on placeholder N; return (imageData, palette)."""
    p = os.path.join(tmpdir, f"ph{index}.png")
    generate_encoded_placeholder(index).save(p, format="PNG")
    out = subprocess.run([MEXCLI, "placeholder-bytes", p], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"mexcli placeholder-bytes failed for {index}: {out.stderr[:300]}")
    d = json.loads(out.stdout.strip().splitlines()[-1])
    return bytes.fromhex(d["img"]), bytes.fromhex(d["pal"]), d["usedMin"], d["usedMax"]


def compute_record(index, tmpdir):
    img, pal, mn, mx = encoded_bytes(index, tmpdir)
    tex_hash = x64(img)
    tlut_hash = x64(pal[2 * mn:2 * (mx + 1)])
    return {
        "filename": f"tex1_16x16_{tex_hash}_{tlut_hash}_9.png",
        "w": 16, "h": 16, "texHash": tex_hash, "tlutHash": tlut_hash, "fmt": "9",
    }


def parse_args(argv):
    opts = {"max": None, "indices": None, "out": DEFAULT_OUT, "verify": False, "merge": False}
    if "--max" in argv:
        opts["max"] = int(argv[argv.index("--max") + 1])
    if "--indices" in argv:
        opts["indices"] = [int(x) for x in argv[argv.index("--indices") + 1].split(",")]
    if "--out" in argv:
        opts["out"] = argv[argv.index("--out") + 1]
    opts["verify"] = "--verify" in argv
    opts["merge"] = "--merge" in argv
    return opts


def main():
    opts = parse_args(sys.argv)
    if opts["indices"] is not None:
        indices = opts["indices"]
    elif opts["max"] is not None:
        indices = list(range(opts["max"] + 1))
    elif opts["verify"] and os.path.exists(HARVESTED):
        indices = sorted(int(k) for k in json.load(open(HARVESTED))["entries"])
    else:
        print(__doc__)
        return 2
    if not os.path.exists(MEXCLI):
        print(f"mexcli not found at {MEXCLI} (build MexCLI -c Release)")
        return 2

    print(f"computing {len(indices)} placeholder filenames (no Dolphin, no ISO)...")
    entries = {}
    with tempfile.TemporaryDirectory() as tmp:
        for n, i in enumerate(indices):
            entries[str(i)] = compute_record(i, tmp)
            if (n + 1) % 25 == 0:
                print(f"  {n + 1}/{len(indices)}")

    if opts["verify"]:
        if not os.path.exists(HARVESTED):
            print("no harvested table to verify against")
        else:
            truth = json.load(open(HARVESTED))["entries"]
            shared = [i for i in indices if str(i) in truth]
            bad = [(i, entries[str(i)]["filename"], truth[str(i)]["filename"])
                   for i in shared if entries[str(i)]["filename"] != truth[str(i)]["filename"]]
            print(f"VERIFY: {len(shared) - len(bad)}/{len(shared)} computed == harvested")
            for i, c, t in bad[:12]:
                print(f"  MISMATCH idx {i}: computed {c} != harvested {t}")
            if not bad:
                print("  PERFECT — pure computation reproduces the harvested table exactly.")

    out_path = os.path.abspath(opts["out"])
    table = {"entries": {}, "builds": []}
    if opts["merge"] and os.path.exists(out_path):
        table = json.load(open(out_path))
    table["entries"].update(entries)
    table["count"] = len(table["entries"])
    table.setdefault("builds", []).append({"label": "computed (pure-math)", "added": len(entries)})
    json.dump(table, open(out_path, "w"), indent=2)
    print(f"wrote {table['count']} indices -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
