"""Export every model_changed entry in a website-imports scan, one process at a time.

Run from app/ (build HSDRawViewer first):
  python ../tools/admin/verify_smd_exports.py --corpus PATH/website-imports --output scratch/smd-before --vanilla PATH/PlSsNr.dat
  # Apply the fix and rebuild, then use a different output directory:
  python ../tools/admin/verify_smd_exports.py --corpus PATH/website-imports --output scratch/smd-after --vanilla PATH/PlSsNr.dat --compare scratch/smd-before/results.json

DATs stay local. Each result records the archive member, joint root, input/output
SHA-256, triangle count and exit code. Previously successful SMDs (including the
vanilla control) must be byte-identical when --compare is supplied.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "backend"))
from core.config import HSDRAW_EXE, get_subprocess_args


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def share_root(data):
    # HSD archive header, relocation table, public/external symbols, strings.
    _, data_size, relocations, publics, externals = struct.unpack_from(">5I", data)
    table = 0x20 + data_size + 4 * relocations
    strings = table + 8 * (publics + externals)
    roots = []
    for i in range(publics):
        _, offset = struct.unpack_from(">2I", data, table + 8 * i)
        start = strings + offset
        name = data[start:data.index(b"\0", start)].decode("ascii")
        if name.endswith("_Share_joint"):
            roots.append(name)
    if len(roots) != 1:
        raise ValueError(f"Expected one costume Share_joint, found {roots}")
    return roots[0]


def export(exe, data, directory, result):
    directory.mkdir(parents=True, exist_ok=False)
    dat = directory / "input.dat"
    smd = directory / "model.smd"
    dat.write_bytes(data)
    root = share_root(data)
    result.update(root=root, input_sha256=sha256(data))
    # No timeout-driven process killing: this tool only launches the headless
    # exporter and waits for it. No GUI, build server, or host app is restarted.
    process = subprocess.run(
        [str(exe), "--model", "export", str(dat), root, str(smd)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        **get_subprocess_args(),
    )
    (directory / "export.log").write_bytes(process.stdout)
    result["exit_code"] = process.returncode
    if process.returncode != 0 or b"SUCCESS: Exported model" not in process.stdout:
        raise RuntimeError(f"Export failed; see {directory / 'export.log'}")
    output = smd.read_bytes()
    lines = output.decode("utf-8-sig").splitlines()
    start = lines.index("triangles") + 1
    end = lines.index("end", start)
    if end == start or (end - start) % 4:
        raise ValueError("SMD contains no triangles or an incomplete triangle")
    result.update(smd_sha256=sha256(output), triangles=(end - start) // 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vanilla", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--exe", type=Path, default=HSDRAW_EXE,
                        help="Override only for an isolated build; defaults to core.config")
    args = parser.parse_args()
    exe = args.exe.resolve()
    if not exe.is_file():
        parser.error(f"Build the exporter first: {exe}")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    scan = json.loads((args.corpus / "scan.json").read_text(encoding="utf-8"))
    index = json.loads((args.corpus / "index.json").read_text(encoding="utf-8"))
    previous = {}
    if args.compare:
        previous = {r["id"]: r for r in json.loads(args.compare.read_text())["results"]}
    results = []

    def check(result, read_data):
        try:
            data = read_data()
            export(exe, data, args.output / result["id"], result)
            old = previous.get(result["id"], {})
            if old.get("ok"):
                if old["input_sha256"] != result["input_sha256"]:
                    raise ValueError("Comparison input changed")
                result["byte_identical"] = old["smd_sha256"] == result["smd_sha256"]
                if not result["byte_identical"]:
                    raise ValueError("Previously working SMD changed bytes")
            result["ok"] = True
        except Exception as error:
            result.update(ok=False, error=str(error))
            print(f"FAIL {result['id']}: {error}", flush=True)
        results.append(result)
        (args.output / "results.json").write_text(json.dumps(
            {"exe": str(exe), "results": results}, indent=2), encoding="utf-8")

    rows = [r for r in scan if r.get("model_changed")]
    for i, row in enumerate(rows):
        result = dict(id=f"costume-{i:03d}", post_id=row["post_id"],
                      title=row["title"], file=row["file"])

        def read_costume():
            matches = [(p, f) for p in index if p["post_id"] == row["post_id"]
                       for f in p["files"] if f["name"] == row["file"]]
            if len(matches) != 1:
                raise ValueError(f"Expected one matching index entry, got {len(matches)}")
            post, item = matches[0]
            archive = args.corpus / post["dir"] / f"{item['file_id']}.zip"
            with zipfile.ZipFile(archive) as zipped:
                # Same first-DAT selection used by the corpus scan.py.
                member = next(n for n in zipped.namelist()
                              if n.lower().endswith((".dat", ".usd")))
                result.update(file_id=item["file_id"], archive=str(archive), member=member)
                return zipped.read(member)

        check(result, read_costume)
        if (i + 1) % 20 == 0 or i + 1 == len(rows):
            print(f"{i + 1}/{len(rows)} costumes: {sum(r['ok'] for r in results)} passed", flush=True)
    if args.vanilla:
        check(dict(id="vanilla", file=str(args.vanilla)), args.vanilla.read_bytes)
    passed = sum(r["ok"] for r in results)
    identical = sum(r.get("byte_identical", False) for r in results)
    print(f"{passed}/{len(results)} exports passed; {identical} byte-identical comparisons")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
