"""
client_feed.py - the publisher's half of the Nucleus game client feed (Play installs from it:
app/backend/play/client_feed.py, docs/dev/PLAY_CLIENT_FEED.md).

Given the client ZIP and its sidecar manifest from the client's windows-build/client_release.py,
this writes the UNSIGNED feed JSON and prints the exact commands that sign and publish it with the
existing release tooling (tools/build/release_to_r2.py --client-zip ...). It signs nothing, reads
no credentials and uploads nothing.

    python tools/build/client_feed.py --zip <dir>/NucleusClient-0.1.0-win64.zip \
        --manifest <dir>/NucleusClient-0.1.0-win64.manifest.json --min-app-version 0.10.0

Before writing it checks what the app will check after the download: the sidecar is a format 1
``nucleus-client`` manifest for one version, named NucleusClient-<version>-win64 like the files, its
print_info says a release build (public_build and game_public_build true), the ZIP is the size and
SHA-256 the sidecar records, and (unless --no-unpack-check) the ZIP unpacks with the app's own
unpacker (play/client_feed.py extract) into a temporary folder, every file matching the sidecar's
list, nothing missing or extra.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / 'app' / 'backend'
OUT_DIR = REPO / 'app' / 'releases' / 'client' / 'windows'
BASE_URL = 'https://releases.ssbmnucleus.net/client/windows'
FEED_NAME = 'latest.json'
UNSIGNED_NAME = 'latest.unsigned.json'


def _backend_feed():
    """The app's own feed module (its schema, checks and unpacker), from this checkout."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from play import client_feed
    return client_feed


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_manifest_bytes(manifest) -> bytes:
    """What the signature covers: the same as release_to_r2.canonical_manifest_bytes."""
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def build_feed(zip_path: Path, manifest_path: Path, *, min_app_version: str, notes: str = '',
               base_url: str = BASE_URL, pub_date: str = None, unpack_check: bool = True) -> dict:
    """The unsigned feed for one client release. Raises SystemExit with the reason when the ZIP and
    sidecar do not belong together or the app would refuse them."""
    feed_mod = _backend_feed()
    zip_path, manifest_path = Path(zip_path), Path(manifest_path)
    if feed_mod.parse_version(min_app_version) is None:
        raise SystemExit(f'--min-app-version must be X.Y.Z, not {min_app_version!r}')
    for path in (zip_path, manifest_path):
        if not path.is_file():
            raise SystemExit(f'not found: {path}')
    raw_manifest = manifest_path.read_bytes()
    sidecar = json.loads(raw_manifest.decode('utf-8'))
    version = sidecar.get('version')
    if feed_mod.parse_version(version) is None:
        raise SystemExit(f'the sidecar names version {version!r}, not X.Y.Z')
    if sidecar.get('kind') != feed_mod.MANIFEST_KIND:
        raise SystemExit(f'the sidecar is kind {sidecar.get("kind")!r}, not {feed_mod.MANIFEST_KIND!r}: '
                         'package the client again with the current client_release.py')
    name = feed_mod.PACKAGE_NAME.format(version=version)
    if (zip_path.name, manifest_path.name) != (f'{name}.zip', f'{name}.manifest.json'):
        raise SystemExit(f'the files must be named {name}.zip and {name}.manifest.json '
                         f'(not {zip_path.name} and {manifest_path.name})')
    info = sidecar.get('print_info') if isinstance(sidecar.get('print_info'), dict) else {}
    if not all(info.get(field) is True for field in ('public_build', 'game_public_build')):
        raise SystemExit('the sidecar\'s print_info does not say public_build and game_public_build are true: '
                         'this is not a release build, and the app refuses to install it')
    zip_size, zip_sha = zip_path.stat().st_size, sha256_of(zip_path)
    recorded = sidecar.get('zip') or {}
    if recorded.get('size') != zip_size or recorded.get('sha256') != zip_sha:
        raise SystemExit(f'{zip_path.name} is not the ZIP {manifest_path.name} describes '
                         f'(sidecar: {recorded.get("size")} bytes {recorded.get("sha256")}; '
                         f'file: {zip_size} bytes {zip_sha})')
    if recorded.get('name') != zip_path.name:
        raise SystemExit(f'the sidecar names {recorded.get("name")!r}, the ZIP is {zip_path.name!r}')
    if sidecar.get('git_dirty'):
        raise SystemExit('the sidecar says the client was built from uncommitted changes (git_dirty): '
                         'publish only a clean build')
    base = base_url.rstrip('/')
    feed = {
        'schema': feed_mod.FEED_SCHEMA,
        'format': feed_mod.FEED_FORMAT,
        'version': version,
        'minAppVersion': min_app_version,
        'notes': notes or f'Nucleus {version}',
        'pub_date': pub_date or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'platforms': {
            feed_mod.PLATFORM_KEY: {
                'url': f'{base}/{zip_path.name}',
                'size': zip_size,
                'sha256': zip_sha,
                'manifest': {
                    'url': f'{base}/{manifest_path.name}',
                    'size': len(raw_manifest),
                    'sha256': hashlib.sha256(raw_manifest).hexdigest(),
                },
            },
        },
    }
    if isinstance(sidecar.get('git_commit'), str):
        feed['commit'] = sidecar['git_commit']
    # What the app does with it, minus the signature and the network: the schema, the file list.
    # A base URL other than the real one (a local stand-in) is checked against its own origin.
    src = feed_mod.production_source() if base == BASE_URL else _stand_in_source(feed_mod, base)
    work = Path(tempfile.mkdtemp(prefix='client-feed-check-'))
    try:
        offer = feed_mod.parse_feed(feed, src)
        files = feed_mod.read_manifest(raw_manifest, offer)
        if unpack_check:
            feed_mod.extract(zip_path, work / 'unpacked', files)
    except feed_mod.FeedError as e:
        raise SystemExit(f'the app would refuse this release: {e}')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return feed


def _stand_in_source(feed_mod, base: str):
    """The trust rules for a feed served somewhere other than the real site (only a local test
    stand-in can be one; the app itself refuses anything else)."""
    from dataclasses import replace
    from urllib.parse import urlsplit
    parts = urlsplit(base + '/')
    prod = feed_mod.production_source()
    return replace(prod, feed_url=base + '/' + FEED_NAME, scheme=parts.scheme, host=parts.hostname,
                   port=parts.port, path_prefix=parts.path, test=True)


def release_command(zip_path: Path, manifest_path: Path, min_app_version: str, notes: str, dry_run: bool) -> str:
    args = ['python', 'tools/build/release_to_r2.py', '--client-zip', f'"{zip_path}"',
            '--client-manifest', f'"{manifest_path}"', '--client-min-app-version', min_app_version]
    if notes:
        args += ['--notes', json.dumps(notes)]
    args.append('--dry-run' if dry_run else '--require-upload')
    return ' '.join(args)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--zip', type=Path, required=True, help='NucleusClient-<version>-win64.zip')
    ap.add_argument('--manifest', type=Path, required=True, help='its sidecar, NucleusClient-<version>-win64.manifest.json')
    ap.add_argument('--min-app-version', required=True, help='the oldest SSBM Nucleus that may install it (X.Y.Z)')
    ap.add_argument('--notes', default='')
    ap.add_argument('--out', type=Path, default=OUT_DIR, help=f'where {UNSIGNED_NAME} is written')
    ap.add_argument('--base-url', default=BASE_URL)
    ap.add_argument('--no-unpack-check', action='store_true', help='skip unpacking the ZIP with the app\'s unpacker')
    args = ap.parse_args(argv)
    feed = build_feed(args.zip, args.manifest, min_app_version=args.min_app_version, notes=args.notes,
                      base_url=args.base_url, unpack_check=not args.no_unpack_check)
    args.out.mkdir(parents=True, exist_ok=True)
    unsigned = args.out / UNSIGNED_NAME
    unsigned.write_text(json.dumps(feed, indent=2) + '\n', encoding='utf-8')
    print(f'unsigned feed: {unsigned}')
    print(f'  version {feed["version"]}, needs SSBM Nucleus {feed["minAppVersion"]}+, '
          f'ZIP {feed["platforms"]["windows-x86_64"]["size"] / 1e6:.1f} MB')
    print()
    print('Sign and stage it (no upload; prints the aws-cli commands in order):')
    print('  ' + release_command(args.zip, args.manifest, args.min_app_version, args.notes, True))
    print('Then publish it (uploads the ZIP and its file list first, the signed latest.json last):')
    print('  ' + release_command(args.zip, args.manifest, args.min_app_version, args.notes, False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
