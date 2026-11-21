#!/usr/bin/env python3
"""Seed the scratch vault the guide screenshots are taken from.

Starts a private backend pointed at docs/guide/.capture/storage, uploads every mod in
seed-manifest.json through the normal import API (so the vault ends up exactly
as a user's would), makes sure the "Guide Build" project exists, then shuts the
backend down. Re-running is safe: duplicates are skipped by the importer and
the project is only created when missing.

Usage (from the repo root):
    app\\venv\\Scripts\\python docs\\guide\\scripts\\seed.py [--vault storage] [--iso <vanilla.iso>] [--fresh]

  --vault   an existing Nucleus vault to copy mods from (default: ./storage)
  --iso     the vanilla 1.02 ISO for project creation (default: GUIDE_VANILLA_ISO
            env, else the path recorded in <vault>/vanilla_iso.json, else the
            Slippi ISO folder)
  --fresh   wipe docs/guide/.capture/storage first
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

NUCLEUS = Path(__file__).resolve().parents[3] / "app"  # the app/ folder
GUIDE = Path(__file__).resolve().parents[1]  # docs/guide
CAPTURE = GUIDE / ".capture"
STORAGE = CAPTURE / "storage"
MANIFEST = GUIDE / "scripts" / "seed-manifest.json"
TOKEN = "guide-seed-token"
PROJECT_NAME = "Guide Build"
PYTHON = NUCLEUS / "venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)


def log(msg: str) -> None:
    print(f"[seed] {msg}", flush=True)


def find_vanilla_iso(vault: Path, explicit: str | None) -> Path:
    candidates = [explicit, os.environ.get("GUIDE_VANILLA_ISO")]
    rec = vault / "vanilla_iso.json"
    if rec.exists():
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
            candidates.append(data.get("path") or data.get("iso_path") or data.get("isoPath"))
        except Exception:
            pass
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    sys.exit("[seed] no vanilla ISO found; pass --iso")


class Backend:
    def __init__(self, storage: Path):
        self.storage = storage
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None

    def __enter__(self):
        env = {**os.environ, "NUCLEUS_STORAGE_DIR": str(self.storage), "NUCLEUS_BACKEND_TOKEN": TOKEN,
               "NUCLEUS_NO_UPDATE_CHECK": "1", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [str(PYTHON), str(NUCLEUS / "backend" / "app.py")],
            cwd=str(NUCLEUS), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )
        deadline = time.time() + 120
        assert self.proc.stdout
        for line in self.proc.stdout:
            m = re.search(r"BACKEND_PORT:\s*(\d+)", line)
            if m:
                self.port = int(m.group(1))
                break
            if time.time() > deadline:
                break
        if not self.port:
            self.__exit__(None, None, None)
            sys.exit("[seed] backend never printed BACKEND_PORT")
        # drain stdout in the background so the pipe never fills
        import threading
        threading.Thread(target=lambda: [None for _ in self.proc.stdout], daemon=True).start()
        for _ in range(60):
            try:
                if self.get("/api/mex/setup/status").ok:
                    break
            except requests.ConnectionError:
                time.sleep(1)
        log(f"backend up on :{self.port} (storage {self.storage})")
        return self

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        log("backend stopped")

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def get(self, path: str, **kw):
        return requests.get(self.base + path, headers={"X-Nucleus-Token": TOKEN}, timeout=kw.pop("timeout", 30), **kw)

    def post(self, path: str, **kw):
        return requests.post(self.base + path, headers={"X-Nucleus-Token": TOKEN}, timeout=kw.pop("timeout", 600), **kw)


def upload(be: Backend, path: Path, data: dict | None = None, endpoint: str = "/api/mex/import/file",
           filename: str | None = None, blob: bytes | None = None) -> None:
    payload = blob if blob is not None else path.read_bytes()
    form = {"slippi_action": "fix", "duplicate_action": "skip", **(data or {})}
    r = be.post(endpoint, files={"file": (filename or path.name, io.BytesIO(payload))}, data=form)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:200]}
    status = body.get("status") or body.get("message") or ("ok" if r.ok else r.text[:120])
    log(f"  {r.status_code} {path.name}: {str(status)[:110]}")


def seed_vault(be: Backend, vault: Path, manifest: dict) -> None:
    for item in manifest["items"]:
        matches = sorted(glob.glob(str(vault / item["path"])))
        if not matches:
            log(f"  MISSING {item['path']}")
            continue
        for src in matches[: item.get("limit", 1)]:
            src_path = Path(src)
            kind = item.get("kind", "mod")
            if kind == "patch":
                upload(be, src_path, endpoint="/api/mex/xdelta/import",
                       data={"name": item.get("name", src_path.stem), "description": item.get("description", "")})
            elif kind == "custom_character":
                # give the fighter package a recognizable filename so the vault names it well
                upload(be, src_path, filename=f"{item.get('name', src_path.parent.name)}.zip")
            else:
                upload(be, src_path)


def ensure_project(be: Backend, iso: Path) -> None:
    r = be.get("/api/mex/project/list")
    projects = r.json().get("projects", []) if r.ok else []
    if any(PROJECT_NAME.lower() in str(p.get("name", p.get("path", ""))).lower() for p in projects):
        log(f'project "{PROJECT_NAME}" already exists')
        return
    log(f'creating project "{PROJECT_NAME}" from {iso.name} (this takes a minute or two)...')
    r = be.post("/api/mex/project/create", json={"isoPath": str(iso), "projectName": PROJECT_NAME}, timeout=1800)
    log(f"  {r.status_code} {r.text[:160]}")
    be.post("/api/mex/project/close", json={}, timeout=60)


def rename_skins(manifest: dict) -> None:
    """Give seeded costumes readable display names (stored zips are named by id).

    Edits the scratch vault's metadata.json directly, after the backend has
    stopped, matching each costume record by its stored zip filename.
    """
    meta_path = STORAGE / "metadata.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # The importer slugifies the source name into the stored zip
    # ("DBZ Pack _ Goku Fox-plfxgr.zip" -> "dbz-pack-goku-fox-plfxgr-plfxgrmod.zip"),
    # so a raw lowercase comparison never matched and every costume kept its
    # filename as its display name.
    def slug(text: str) -> str:
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")

    wanted = {
        slug(Path(item["path"]).stem): item["name"]
        for item in manifest["items"]
        if item.get("name") and item.get("kind", "mod") == "mod" and not item["path"].startswith("das/")
    }
    renamed = 0
    for char in meta.get("characters", {}).values():
        for skin in char.get("skins", []):
            stem = slug(Path(skin.get("filename", "")).stem)
            for key, name in wanted.items():
                if stem == key or stem.startswith(key) or key.startswith(stem):
                    if skin.get("color") != name:
                        skin["color"] = name
                        renamed += 1
                    break
    meta_path.write_text(json.dumps(meta, indent=2) + os.linesep, encoding="utf-8")
    log(f"renamed {renamed} costume(s) for display")


def sample_replays(root: Path, count: int) -> None:
    """Copy the newest `count` .slp files into the small replay folder the
    Tracker screenshots index (a whole library takes hours)."""
    dest = CAPTURE / "replays"
    dest.mkdir(parents=True, exist_ok=True)
    files = sorted(root.rglob("*.slp"), key=lambda p: p.stat().st_mtime, reverse=True)[:count]
    for f in files:
        shutil.copy2(f, dest / f.name)
    log(f"copied {len(files)} replay(s) to {dest}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(NUCLEUS / "storage"))
    ap.add_argument("--iso")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--skip-project", action="store_true")
    ap.add_argument("--replays", help="Slippi replay root to sample .slp files from (newest first) into docs/guide/.capture/replays")
    ap.add_argument("--replay-count", type=int, default=60)
    args = ap.parse_args()

    if args.replays:
        sample_replays(Path(args.replays), args.replay_count)

    vault = Path(args.vault)
    if args.fresh and STORAGE.exists():
        shutil.rmtree(STORAGE)
    STORAGE.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    iso = None if args.skip_project else find_vanilla_iso(vault, args.iso)

    with Backend(STORAGE) as be:
        seed_vault(be, vault, manifest)
        if iso:
            ensure_project(be, iso)
    rename_skins(manifest)
    log("done")


if __name__ == "__main__":
    main()
