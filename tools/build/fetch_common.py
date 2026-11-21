"""Shared helpers for the pinned-toolchain fetchers.

fetch_ffmpeg.py and fetch_native.py (MexCLI / HSDRawViewer) do the same job:
read a tracked manifest, download an archive, refuse it unless its sha256 is
the pinned one, unpack it under app/utility/, and leave a receipt so
``--check`` can tell a current unpack from a stale one.  The pieces
live here so there is one implementation of the verify-then-unpack rule.

``PROJECT_ROOT`` is the ``app/`` directory (the dir holding package.json); the
manifests' ``unpack_to`` paths are relative to it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO_ROOT / 'app'
RECEIPT_NAME = '.fetch-receipt.json'
CHUNK = 1 << 20
DEFAULT_REQUIRED = ('version', 'url', 'sha256', 'archive_root', 'unpack_to', 'entrypoint')


def load_manifest(path: Path, required=DEFAULT_REQUIRED) -> dict:
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in required:
        if not manifest.get(key):
            raise SystemExit(f'{Path(path).name} is missing "{key}"')
    if 'sha256' in manifest and len(manifest['sha256']) != 64:
        raise SystemExit(f'{Path(path).name}: sha256 must be 64 hex characters')
    return manifest


def target_dir(manifest: dict) -> Path:
    return PROJECT_ROOT / manifest['unpack_to']


def sha256_of(path: Path, *, log=print) -> str:
    digest = hashlib.sha256()
    size, seen, mark = path.stat().st_size, 0, 0
    with path.open('rb') as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
            seen += len(block)
            if size and seen * 10 // size > mark:
                mark = seen * 10 // size
                log(f'  hashing {mark * 10}%')
    return digest.hexdigest()


def download(url: str, destination: Path, *, log=print, headers: dict | None = None) -> Path:
    log(f'downloading {url}')
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={'User-Agent': 'ssbmNucleus-build/1.0', **(headers or {})})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open('wb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        seen, mark = 0, 0
        while True:
            block = response.read(CHUNK)
            if not block:
                break
            out.write(block)
            seen += len(block)
            if total and seen * 10 // total > mark:
                mark = seen * 10 // total
                log(f'  {mark * 10}%  ({seen / 1e6:.0f} MB)')
    log(f'downloaded {destination.stat().st_size / 1e6:.0f} MB in '
        f'{time.perf_counter() - started:.0f}s')
    return destination


def measure(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def extract(archive: Path, manifest: dict, destination: Path, *, log=print) -> None:
    """Unpack `archive`, stripping its single top-level directory.

    A manifest without ``archive_root`` names a flat archive: nothing is stripped.
    Members the zip marks executable keep their execute bit.
    """
    root = (manifest.get('archive_root') or '').strip('/')
    root = root + '/' if root else ''
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(destination.parent)) as staging:
        staging_path = Path(staging)
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            stray = [i.filename for i in infos if not i.filename.startswith(root)]
            if stray:
                raise SystemExit(f'archive does not live under {root}: {stray[:3]}')
            for info in infos:
                name = info.filename
                relative = name[len(root):]
                if not relative:
                    continue
                # Refuse anything that would escape the unpack directory.
                out = (staging_path / relative).resolve()
                if not str(out).startswith(str(staging_path.resolve())):
                    raise SystemExit(f'archive member escapes the unpack directory: {name}')
                if name.endswith('/'):
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, out.open('wb') as target:
                    shutil.copyfileobj(source, target, CHUNK)
                if (info.external_attr >> 16) & 0o111:
                    out.chmod(out.stat().st_mode | 0o111)
            log(f'unpacked {len(infos)} entries')
        trim(staging_path, manifest, log=log)
        verify_tree(staging_path, manifest)
        if destination.exists():
            log(f'replacing the existing unpack at {destination}')
            shutil.rmtree(destination)
        staging_path.rename(destination)
        # TemporaryDirectory's cleanup must still find something to remove.
        staging_path.mkdir(exist_ok=True)


def trim(root: Path, manifest: dict, *, log=print) -> dict:
    """Delete the manifest's optional payload; returns bytes before/after."""
    rules = manifest.get('trim') or {}
    before = measure(root)
    removed = 0
    for relative in rules.get('files') or ():
        victim = root / relative
        if victim.is_file():
            removed += victim.stat().st_size
            victim.unlink()
        else:
            log(f'  trim: {relative} is not in this build (skipped)')
    for relative in rules.get('dirs') or ():
        victim = root / relative
        if victim.is_dir():
            removed += measure(victim)
            shutil.rmtree(victim)
        else:
            log(f'  trim: {relative}/ is not in this build (skipped)')
    after = measure(root)
    if rules:
        log(f'trimmed {removed / 1e6:.0f} MB: {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB on disk')
    return {'bytes_before_trim': before, 'bytes_after_trim': after}


def verify_tree(root: Path, manifest: dict) -> None:
    """Every path the pipeline depends on must have survived the trim."""
    missing = [p for p in [manifest['entrypoint'], *(manifest.get('verify_after_unpack') or ())]
               if not (root / p).exists()]
    if missing:
        raise SystemExit('the unpack is missing paths the app needs: '
                         + ', '.join(missing))


def write_receipt(destination: Path, manifest: dict, extra: dict, *, manifest_path: Path,
                  fields: dict | None = None) -> None:
    receipt = {
        'version': manifest.get('version'),
        'url': manifest.get('url'),
        'sha256': manifest['sha256'],
        'license': (manifest.get('license') or {}).get('spdx'),
        'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'manifest': str(Path(manifest_path).resolve().relative_to(PROJECT_ROOT)).replace('\\', '/'),
        'trimmed': manifest.get('trim'),
        **(fields or {}),
        **extra,
    }
    (destination / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


def check(manifest: dict, *, label: str, version_of=None, expected=None, extra_check=None,
          log=print) -> bool:
    """Is the unpack on disk the one the manifest pins?

    `version_of(destination, manifest)` (optional) asks the unpack what it
    reports; it must equal `expected`.  `extra_check(destination, manifest, log)`
    may veto for tool-specific reasons.
    """
    destination = target_dir(manifest)
    if not (destination / manifest['entrypoint']).is_file():
        log(f'MISSING: {destination / manifest["entrypoint"]}')
        return False
    receipt_path = destination / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.is_file() else {}
    if receipt.get('sha256') != manifest['sha256']:
        log(f'STALE: unpack was made from {receipt.get("sha256", "an unrecorded archive")!r}, '
            f'manifest pins {manifest["sha256"]}')
        return False
    try:
        verify_tree(destination, manifest)
    except SystemExit as exc:
        log(f'INCOMPLETE: {exc}')
        return False
    reported = None
    if version_of is not None:
        reported = version_of(destination, manifest)
        if reported != expected:
            log(f'VERSION MISMATCH: unpack reports {reported!r}, manifest pins {expected!r}')
            return False
    if extra_check is not None and not extra_check(destination, manifest, log):
        return False
    log(f'ok: {label} {reported or expected or ""} at {destination} ({measure(destination) / 1e6:.0f} MB)')
    return True
