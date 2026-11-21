"""Shared paths and deterministic, atomic scratch artifacts; no app writes."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app/scratch/liteaudit/harness"
sys.path.insert(0, str(ROOT / "app/backend"))


def output_dir(value=None):
    path = Path(value or OUT).resolve()
    if not path.is_relative_to(OUT.resolve()):
        raise ValueError(f"output must stay under {OUT}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, value):
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if str(path).endswith(".gz"):
        data = gzip.compress(data, compresslevel=1, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_json(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if str(path).endswith(".gz") else data)


def fingerprint(paths):
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def select(manifest, shard="1/1", limit=None):
    i, n = map(int, shard.split("/"))
    if not 1 <= i <= n:
        raise ValueError("shard is 1-based: i/N, 1 <= i <= N")
    return manifest["games"][i - 1::n][:limit]
