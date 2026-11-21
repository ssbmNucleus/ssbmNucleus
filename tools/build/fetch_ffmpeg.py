"""Reproduce the bundled ffmpeg from utility/ffmpeg.manifest.json.

The Windows installer ships a pinned, unmodified GPL ffmpeg so game
recordings encode to mp4 on a fresh PC. The unpack (``app/utility/ffmpeg/``)
is git-ignored; this script and the manifest are what is tracked:

    python tools/build/fetch_ffmpeg.py            # download, verify, unpack
    python tools/build/fetch_ffmpeg.py --check     # is the unpack already good?
    python tools/build/fetch_ffmpeg.py --archive <zip>   # use a local copy

Same contract as fetch_native.py, whose download/verify/unpack helpers (fetch_common.py) this
reuses: the download is only trusted when its sha256 matches the manifest, and
`trim` deletes whole files without patching anything. `url` is BtbN's release
asset; an optional `fallback_urls` list is tried after it, under the same
sha256 gate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_common import (PROJECT_ROOT, RECEIPT_NAME, download, extract,  # noqa: E402
                          load_manifest, measure, sha256_of, target_dir, verify_tree)

MANIFEST = PROJECT_ROOT / 'utility' / 'ffmpeg.manifest.json'


def _run(executable: Path, *args: str) -> str | None:
    options: dict = {}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        done = subprocess.run([str(executable), *args], capture_output=True, text=True,
                              timeout=60, **options)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout or ''


def installed_version(destination: Path, manifest: dict) -> str | None:
    """The unpack's own version string, or None when it cannot run.

    Compared against the manifest's `build` (the full string, e.g.
    "n9.0.2-17-g2a571b6068-20260930", which names the exact FFmpeg commit) when
    it has one, otherwise against the bare release number."""
    out = _run(destination / manifest['entrypoint'], '-hide_banner', '-version')
    for line in (out or '').splitlines():
        if line.startswith('ffmpeg version '):
            reported = line.split()[2]
            return reported if manifest.get('build') else reported.lstrip('n').split('-')[0]
    return None


def expected_version(manifest: dict) -> str:
    return manifest.get('build') or manifest['version']


def candidate_urls(manifest: dict) -> list[str]:
    return [manifest['url'], *(manifest.get('fallback_urls') or [])]


def fetch_verified(manifest: dict, scratch: Path) -> tuple[Path, str]:
    """Try the mirror, then each fallback; return the first download whose
    sha256 is the pinned one. A URL is trusted for nothing but its bytes."""
    failures = []
    for index, url in enumerate(candidate_urls(manifest)):
        target = scratch / f'ffmpeg-{index}.zip'
        try:
            download(url, target)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            print(f'  unavailable: {url} ({exc})')
            failures.append(f'{url}: {exc}')
            continue
        print(f'verifying sha256 of the download from {url}')
        digest = sha256_of(target)
        if digest != manifest['sha256']:
            print(f'  REJECTED: {url} served {digest}, manifest pins {manifest["sha256"]}')
            failures.append(f'{url}: sha256 {digest}')
            target.unlink()
            continue
        return target, url
    raise SystemExit('no source served the pinned ffmpeg:\n  ' + '\n  '.join(failures))


def has_libx264(destination: Path, manifest: dict) -> bool:
    """Recordings encode with libx264; a build without it is useless here."""
    out = _run(destination / manifest['entrypoint'], '-hide_banner', '-encoders')
    return bool(out) and ' libx264 ' in out


def write_receipt(destination: Path, manifest: dict, extra: dict) -> None:
    receipt = {
        'version': manifest['version'],
        'build': manifest.get('build'),
        'url': manifest['url'],
        'sha256': manifest['sha256'],
        'license': (manifest.get('license') or {}).get('spdx'),
        'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'manifest': str(MANIFEST.relative_to(PROJECT_ROOT)).replace('\\', '/'),
        'trimmed': manifest.get('trim'),
        **extra,
    }
    (destination / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


def check(manifest: dict, *, log=print) -> bool:
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
    reported = installed_version(destination, manifest)
    if reported != expected_version(manifest):
        log(f'VERSION MISMATCH: unpack reports {reported!r}, manifest pins '
            f'{expected_version(manifest)!r}')
        return False
    if not has_libx264(destination, manifest):
        log('NO libx264: this ffmpeg cannot encode recordings')
        return False
    log(f'ok: ffmpeg {reported} at {destination} ({measure(destination) / 1e6:.0f} MB)')
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true',
                        help='only report whether the existing unpack matches the manifest')
    parser.add_argument('--archive', type=Path,
                        help='use this already-downloaded zip instead of fetching the URLs')
    parser.add_argument('--force', action='store_true',
                        help='re-unpack even when the existing tree already matches')
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    destination = target_dir(manifest)
    if args.check:
        return 0 if check(manifest) else 1
    if not args.force and check(manifest, log=lambda *_: None):
        print(f'ffmpeg {expected_version(manifest)} is already unpacked at {destination}; '
              f'nothing to do (--force to redo it)')
        return 0

    with tempfile.TemporaryDirectory(prefix='nucleus-ffmpeg-') as scratch:
        if args.archive:
            archive, source = Path(args.archive), 'local archive'
            if not archive.is_file():
                raise SystemExit(f'archive not found: {archive}')
            print(f'verifying sha256 of {archive.name}')
            digest = sha256_of(archive)
            if digest != manifest['sha256']:
                raise SystemExit(f'REFUSED: {archive} hashes {digest}, manifest pins '
                                 f'{manifest["sha256"]}. Not unpacking.')
        else:
            archive, source = fetch_verified(manifest, Path(scratch))
        print('sha256 matches the manifest')
        extract(archive, manifest, destination, log=print)
        write_receipt(destination, manifest, {'downloaded_from': source,
                                              'bytes_on_disk': measure(destination),
                                              'archive_bytes': archive.stat().st_size})

    if not check(manifest):
        return 1
    print('ffmpeg is bundled. tools/build/ship_rules.json stages utility/ffmpeg '
          'into the installer; package.json extraResources copies it to resources/utility/ffmpeg.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
