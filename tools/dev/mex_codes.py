"""
mex_codes.py -- SAFE updater for the bundled m-ex Gecko codes (codes.gct /
codes.ini) from upstream github.com/akaneia/m-ex (asm/).

The tool builds ISOs with a bundled snapshot of m-ex's codes. This script lets
you refresh them WITHOUT ever losing the current version: every `update` makes a
timestamped backup first, and `restore` puts any backup back. Default action is
read-only `status`.

NOTE: as of this writing the bundled codes.gct (63,984 B) is ~current with
upstream master (64,136 B). The Ace Build's larger codes.gct (77,080 B) is a
CUSTOM/extended m-ex core that is NOT in public upstream -- so updating from
upstream will NOT add it. Characters authored for the Ace Build (e.g. Metal
Mario's cape) need the Ace Build's m-ex, i.e. build on the Ace base.

Usage (run from repo root):
  python tools/dev/mex_codes.py status            # compare local vs upstream (read-only)
  python tools/dev/mex_codes.py backup            # snapshot current codes only
  python tools/dev/mex_codes.py update            # backup, then pull upstream codes
  python tools/dev/mex_codes.py restore <dir>     # restore codes from a backup dir
  python tools/dev/mex_codes.py list              # list available backups
"""
import hashlib
import shutil
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2] / "app"  # the app/ folder
# The codes ship inside the pinned prebuilt MexCLI (tools/build/fetch_native.py mex), unpacked
# at utility/mex/<rid>/. The source of truth is the ssbmNucleus-mex fork repo: edits made here
# are LOCAL experiments and are overwritten by the next `fetch_native.py mex --force`.
MEX = REPO / "utility" / "mex" / "win-x64"

# Upstream name -> where it lands in the unpacked MexCLI. mexcli reads codes.gct from its own
# directory (ImportIsoCommand uses AppDomain.BaseDirectory); the vault's code library is
# seed_codes.ini (never a codes.ini beside mexcli -- that would enable every code on new projects).
TARGETS = {
    "codes.gct": [MEX / "codes.gct"],
    "codes.ini": [MEX / "seed_codes.ini"],
}
UPSTREAM = "https://raw.githubusercontent.com/akaneia/m-ex/master/asm/{name}"
API = "https://api.github.com/repos/akaneia/m-ex/contents/asm/{name}"
BACKUP_ROOT = REPO / "tmp_retake" / "mex-codes-backups"


def md5(b):
    return hashlib.md5(b).hexdigest()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mex-codes/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def status():
    for name in TARGETS:
        print(f"\n== {name} ==")
        try:
            up = fetch(UPSTREAM.format(name=name))
            print(f"  upstream akaneia/m-ex master: {len(up)} B  md5 {md5(up)}")
        except Exception as e:  # noqa: BLE001
            print(f"  upstream: FETCH FAILED ({e})")
            up = None
        for path in TARGETS[name]:
            if path.exists():
                b = path.read_bytes()
                tag = "  (== upstream)" if up and md5(b) == md5(up) else \
                      "  (DIFFERS from upstream)" if up else ""
                rel = path.relative_to(REPO)
                print(f"  local {rel}: {len(b)} B  md5 {md5(b)}{tag}")
            else:
                print(f"  local {path.relative_to(REPO)}: MISSING")


def backup():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / stamp
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, paths in TARGETS.items():
        for path in paths:
            if path.exists():
                shutil.copy2(path, dest / f"fetched__{name}")
                n += 1
    print(f"backed up {n} file(s) -> {dest.relative_to(REPO)}")
    return dest


def update(include_ini=False):
    # codes.ini is a LOCAL FORK (currently larger than upstream = extra custom
    # codes), so do NOT overwrite it from upstream unless explicitly asked --
    # that would silently drop our custom codes. codes.gct is ~current with
    # upstream and is the lower-risk refresh.
    names = ["codes.gct"] + (["codes.ini"] if include_ini else [])
    if not include_ini:
        print("(skipping codes.ini -- it's a local fork; pass --include-ini to force)")
    backup()
    for name in names:
        try:
            data = fetch(UPSTREAM.format(name=name))
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: FETCH FAILED ({e}); skipping")
            continue
        for path in TARGETS[name]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(f"  wrote {path.relative_to(REPO)} ({len(data)} B)")
    print("done. Codes are data (read at runtime) -- no MexCLI rebuild needed.")
    print("To revert: python tools/dev/mex_codes.py restore <backup dir>")


def restore(dirname):
    src = Path(dirname)
    if not src.is_absolute():
        src = BACKUP_ROOT / dirname
    if not src.exists():
        print(f"backup dir not found: {src}")
        return 1
    for f in src.iterdir():
        tag, _, name = f.name.partition("__")
        for path in TARGETS.get(name, []):
            shutil.copy2(f, path)
            print(f"  restored {path.relative_to(REPO)}")
    print("restore complete.")
    return 0


def list_backups():
    if not BACKUP_ROOT.exists():
        print("no backups yet")
        return
    for d in sorted(BACKUP_ROOT.iterdir()):
        print(f"  {d.name}  ({len(list(d.iterdir()))} files)")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "backup":
        backup()
    elif cmd == "update":
        update(include_ini="--include-ini" in sys.argv)
    elif cmd == "restore":
        return restore(sys.argv[2]) if len(sys.argv) > 2 else print("need a backup dir")
    elif cmd == "list":
        list_backups()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
