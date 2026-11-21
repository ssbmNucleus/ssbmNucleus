#!/usr/bin/env python3
"""Remove regenerable debris (scratch, test runs, caches, installers, ISOs).

Dry run by default: lists what would be deleted with sizes. Pass --yes to delete.
Anything git tracks is never deleted; app/storage itself, venv,
node_modules and .git are never touched.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
N = "app"

# (target, kind): "contents" = children of dir, "path" = the path itself, "glob" = glob in dir
TARGETS = [
    (f"{N}/scratch", "contents"),
    (f"{N}/storage/test-runs", "contents"),
    (f"{N}/storage/test-builds", "contents"),
    (f"{N}/backend/artifacts", "path"),
    (f"{N}/ship-report.txt", "path"),
    (f"{N}/build/mex_backend", "path"),
    (f"{N}/dist-backend", "path"),
    (f"{N}/dist-electron", "path"),
    (f"{N}/build-package-staging", "path"),
    (".tmp", "path"),
    (".tmp-*", "glob"),
    (f"{N}/backend/.tmp-*", "glob"),
    (f"{N}/.tmp", "path"),
    (f"{N}/backend/.tmp", "path"),
    (f"{N}/SSBM Nucleus Setup*.exe", "glob"),
    (f"{N}/*.iso", "glob"),
]
CACHE_PARENTS = ["", N, f"{N}/backend", "tests", "tests/backend", "tests/eval/randall", "tests/tools/discord", "eval", "eval/randall", "tools"]
CACHE_NAMES = [".pytest_cache", "__pycache__"]
PROTECTED = {".git", "node_modules", "venv"}


def expand():
    out = []  # (path, top-level target label)
    for rel, kind in TARGETS:
        p = ROOT / rel
        if kind == "contents":
            if p.is_dir():
                out += [(c, rel) for c in sorted(p.iterdir())]
        elif kind == "glob":
            out += [(c, rel) for c in sorted(p.parent.glob(p.name))]
        elif p.exists():
            out.append((p, rel))
    for parent in CACHE_PARENTS:
        for name in CACHE_NAMES:
            p = ROOT / parent / name
            if p.is_dir():
                out.append((p, f"{parent or '.'}/{name}"))
    return out


def tracked(p):
    rel = p.relative_to(ROOT).as_posix()
    r = subprocess.run(["git", "ls-files", "--", rel], cwd=ROOT,
                       capture_output=True, text=True)
    return r.returncode != 0 or bool(r.stdout.strip())


def size(p):
    if p.is_symlink() or p.is_file():
        try:
            return p.lstat().st_size
        except OSError:
            return 0
    total = 0
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _force_writable(func, path, _exc):
    # Read-only files (e.g. .git objects a test created) block rmtree on Windows.
    os.chmod(path, 0o666)
    func(path)


def remove(p):
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, onerror=_force_writable)
    else:
        try:
            p.unlink()
        except PermissionError:
            os.chmod(p, 0o666)
            p.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="actually delete (default is dry run)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()

    groups = {}  # label -> [paths]
    for p, label in expand():
        groups.setdefault(label, []).append(p)

    rel = lambda p: p.relative_to(ROOT).as_posix()
    mb = lambda b: f"{b / 1048576:.1f} MB"
    rows, refused, failed = [], [], []
    for label, paths in groups.items():
        if any(p.name in PROTECTED or p == ROOT / N / "storage" for p in paths):
            refused.append((label, "protected"))
            continue
        # tracked check: whole target dir for "contents" targets, else each path
        probe = [ROOT / label] if (ROOT / label).is_dir() and label in dict(TARGETS)             and dict(TARGETS)[label] == "contents" else paths
        if any(tracked(p) for p in probe):
            refused.append((label, "contains git-tracked files"))
            continue
        total = sum(size(p) for p in paths)
        n = 0
        if a.yes:
            for p in paths:
                try:
                    remove(p)
                    n += 1
                except OSError as e:
                    failed.append((rel(p), str(e)))
        rows.append((label, len(paths), total))

    grand = sum(r[2] for r in rows)
    if a.json:
        print(json.dumps({
            "dry_run": not a.yes,
            "targets": [{"target": l, "count": c, "bytes": b} for l, c, b in rows],
            "total_bytes": grand,
            "refused": [{"target": t, "reason": r} for t, r in refused],
            "failed": [{"path": p, "error": e} for p, e in failed],
        }, indent=2))
    else:
        for label, c, b in rows:
            print(f"{mb(b):>10}  {label}" + (f"  ({c} items)" if c > 1 else ""))
        for t, r in refused:
            print(f"   REFUSED  {t} ({r})")
        for p, e in failed:
            print(f"    FAILED  {p}: {e}")
        print(("Freed " if a.yes else "Would free ") + mb(grand)
              + ("" if a.yes else ". Dry run; pass --yes to delete."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
