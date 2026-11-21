"""Content fingerprints and immutable capture bundles (no model weights copied)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


def fingerprint(path: Path) -> dict:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": path.resolve().as_posix(), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def capture_bundle(out: Path, files: dict, metadata: dict) -> Path:
    """Append-only sibling run directory. A later run cannot replace its evidence."""
    import uuid
    out = Path(out)
    root = out.parent / (out.stem + ".runs") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for role, source in files.items():
        source = Path(source)
        target = root / (role + source.suffix)
        shutil.copy2(source, target)
        artifacts[role] = {"file": target.name, "source": fingerprint(source),
                           "sha256": fingerprint(target)["sha256"]}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "artifacts": artifacts, **metadata}, indent=2), encoding="utf-8")
    return manifest


def verify_bundle(manifest: Path) -> tuple[dict, dict]:
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    paths = {}
    for role, entry in data["artifacts"].items():
        path = (manifest.parent / entry["file"]).resolve()
        if path.parent != manifest.parent:
            raise ValueError(f"artifact {role} must live inside its run bundle")
        if fingerprint(path)["sha256"] != entry["sha256"]:
            raise ValueError(f"artifact changed after capture: {role}")
        paths[role] = path
    return data, paths
