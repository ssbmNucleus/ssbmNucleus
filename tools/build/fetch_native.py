"""Fetch the pinned prebuilt native toolchain: MexCLI and HSDRawViewer.

The m-ex and HSDLib source trees no longer live in this repo.  Their forks
(ssbmNucleus/m-ex, ssbmNucleus/HSDLib) publish self-contained
builds as GitHub Releases, and the manifests pin one tag and one sha256 per
platform:

    app/utility/mex.manifest.json      -> app/utility/mex/<rid>/      (mexcli, codes.gct, seed_codes.ini, DLLs)
    app/utility/hsdlib.manifest.json   -> app/utility/hsdraw/<rid>/   (HSDRawViewer.exe / hsdrawviewer, Scripts/, lib/)

Usage:
    python tools/build/fetch_native.py all                          # both, for this machine
    python tools/build/fetch_native.py mex --platform linux-x64
    python tools/build/fetch_native.py all --platform host --check  # is the unpack current? (exit 1 if not)
    python tools/build/fetch_native.py hsdlib --force               # re-unpack

To bump a tool: publish a new tag on the fork, then edit `tag` and the per-platform
`sha256` values (from the release's SHA256SUMS.txt) in the manifest.

Downloads try, in order: `gh release download` when the GitHub CLI is installed and
logged in; a token from the environment (NUCLEUS_FETCH_TOKEN, then GH_TOKEN, then
GITHUB_TOKEN) sent as a Bearer header to the GitHub API; then the release's plain
download link with no login.  The dev manifests pin private forks, which need one of
the first two.  The public source copy's manifests pin the public repos (ssbmNucleus/
HSDLib, ssbmNucleus/m-ex), which the plain link serves to anyone, so a stranger's
setup needs no GitHub account.  Release build hosts need none of these:
release_lan.py downloads their archives on the dispatching machine and sends them
with the job, and NUCLEUS_NATIVE_ARCHIVES points this script at them.  Whatever the
transport, the archive's sha256 must equal the manifest's or nothing is unpacked.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_common  # noqa: E402
from fetch_common import PROJECT_ROOT, extract, load_manifest, measure, sha256_of, target_dir  # noqa: E402

UTILITY = PROJECT_ROOT / 'utility'
TOOLS = {
    'mex': UTILITY / 'mex.manifest.json',
    'hsdlib': UTILITY / 'hsdlib.manifest.json',
}
PLATFORMS = ('win-x64', 'linux-x64', 'osx-arm64')
TOKEN_VARS = ('NUCLEUS_FETCH_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')
ARCHIVES_VAR = 'NUCLEUS_NATIVE_ARCHIVES'  # a folder of already-downloaded release assets
API = 'https://api.github.com'


def host_platform() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == 'Windows':
        return 'win-x64'
    if system == 'Linux' and machine in ('x86_64', 'amd64'):
        return 'linux-x64'
    if system == 'Darwin' and machine in ('arm64', 'aarch64'):
        return 'osx-arm64'
    raise SystemExit(f'no prebuilt native toolchain for {system}/{machine}; '
                     f'supported: {", ".join(PLATFORMS)}')


def load_tool(tool: str, rid: str) -> dict:
    """The manifest flattened to one platform, in the shape fetch_common expects."""
    path = TOOLS[tool]
    raw = load_manifest(path, required=('repo', 'tag', 'platforms'))
    entry = (raw['platforms'] or {}).get(rid)
    if not entry:
        raise SystemExit(f'{path.name} has no entry for platform {rid!r}')
    for key in ('asset', 'sha256', 'unpack_to', 'entrypoint'):
        if not entry.get(key):
            raise SystemExit(f'{path.name}: platforms.{rid} is missing "{key}"')
    if len(entry['sha256']) != 64:
        raise SystemExit(f'{path.name}: platforms.{rid}.sha256 must be 64 hex characters')
    return {
        'tool': tool, 'rid': rid, 'manifest_path': path,
        'repo': raw['repo'], 'tag': raw['tag'], 'license': raw.get('license'),
        'version': raw['tag'],
        'url': f'https://github.com/{raw["repo"]}/releases/download/{raw["tag"]}/{entry["asset"]}',
        'archive_root': '',          # the release zips are flat
        'asset': entry['asset'], 'sha256': entry['sha256'],
        'unpack_to': entry['unpack_to'], 'entrypoint': entry['entrypoint'],
        'verify_after_unpack': entry.get('verify_after_unpack') or [],
    }


# --------------------------------------------------------------------------
# download (gh, a token, or the public link)
# --------------------------------------------------------------------------

def _token() -> str | None:
    for name in TOKEN_VARS:
        if os.environ.get(name):
            return os.environ[name]
    return None


def _gh_ready() -> bool:
    gh = shutil.which('gh')
    if not gh:
        return False
    try:
        done = subprocess.run([gh, 'auth', 'status'], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _api_json(url: str, token: str):
    request = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ssbmNucleus-build/1.0'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode('utf-8'))


def _download_with_token(repo: str, tag: str, asset: str, destination: Path, token: str) -> None:
    release = _api_json(f'{API}/repos/{repo}/releases/tags/{tag}', token)
    match = next((a for a in release.get('assets', []) if a.get('name') == asset), None)
    if not match:
        raise SystemExit(f'{repo} release {tag} has no asset {asset!r}')
    url = f'{API}/repos/{repo}/releases/assets/{match["id"]}'
    request = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}', 'Accept': 'application/octet-stream',
        'User-Agent': 'ssbmNucleus-build/1.0'})
    # The API answers with a redirect to a pre-signed storage URL.  That URL must
    # NOT receive the Authorization header, so follow it by hand.
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        response = opener.open(request, timeout=120)
        location = None
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get('Location')
    if location:
        fetch_common.download(location, destination)
    else:
        with destination.open('wb') as out:
            shutil.copyfileobj(response, out, fetch_common.CHUNK)


def fetch_archive(spec: dict, scratch: Path) -> Path:
    repo, tag, asset = spec['repo'], spec['tag'], spec['asset']
    destination = scratch / asset
    # Release build hosts have no GitHub credentials: the machine that dispatches the
    # release fetches the archives and ships them with the job (release_lan.py). The
    # sha256 check in fetch() still applies to whatever is found here.
    prefetched = os.environ.get(ARCHIVES_VAR, '').strip()
    if prefetched and (Path(prefetched) / asset).is_file():
        print(f'using {asset} delivered with the release job ({ARCHIVES_VAR})')
        return Path(prefetched) / asset
    if _gh_ready():
        print(f'downloading {repo} {tag} {asset} (gh)')
        subprocess.run(['gh', 'release', 'download', '-R', repo, tag, '-p', asset,
                        '-D', str(scratch), '--clobber'], check=True)
        if not destination.is_file():
            raise SystemExit(f'gh did not produce {asset}')
        return destination
    token = _token()
    if token:
        print(f'downloading {repo} {tag} {asset} (token)')
        try:
            _download_with_token(repo, tag, asset, destination, token)
            return destination
        except urllib.error.HTTPError as exc:
            # A token for something else (expired, or scoped to other repos) must not stop a public download.
            refused = f'GitHub refused the token ({exc.code} {exc.reason}); it needs read access to {repo}'
            print(f'{refused}; trying the public link')
    else:
        refused = None
    return _download_public(spec, destination, refused)


def _download_public(spec: dict, destination: Path, refused: str | None) -> Path:
    """The release's plain download link, with no login: what a public repo's release serves to anyone."""
    repo, tag, asset = spec['repo'], spec['tag'], spec['asset']
    print(f'downloading {repo} {tag} {asset} (public link)')
    try:
        fetch_common.download(spec['url'], destination)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise SystemExit(f'GitHub refused {spec["url"]} ({exc.code} {exc.reason})')
        # GitHub answers 404 both for a private repo and for a release or file that does not exist.
        raise SystemExit(
            f'{repo} release {tag} has no {asset} anyone can download (404). If {repo} is private, install the '
            f'GitHub CLI and run `gh auth login`, or set one of {", ".join(TOKEN_VARS)} to a token with read '
            f'access to it.' + (f' ({refused})' if refused else ''))
    except urllib.error.URLError as exc:
        raise SystemExit(f'could not reach GitHub for {asset}: {exc.reason}')
    return destination


# --------------------------------------------------------------------------
# check / fetch
# --------------------------------------------------------------------------

def check(spec: dict, *, log=print) -> bool:
    return fetch_common.check(spec, label=f'{spec["tool"]} {spec["tag"]} ({spec["rid"]})', log=log)


def _make_executable(spec: dict, destination: Path) -> None:
    if spec['rid'].startswith('win'):
        return
    for child in destination.iterdir():
        if child.is_file() and ('.' not in child.name or child.name == spec['entrypoint']):
            child.chmod(child.stat().st_mode | 0o111)


def fetch(spec: dict, *, force: bool, check_only: bool, archive: Path | None = None) -> bool:
    destination = target_dir(spec)
    if check_only:
        return check(spec)
    if not force and check(spec, log=lambda *_: None):
        print(f'{spec["tool"]} {spec["tag"]} ({spec["rid"]}) is already unpacked at {destination}; '
              f'nothing to do (--force to redo it)')
        return True
    with tempfile.TemporaryDirectory(prefix='nucleus-native-') as scratch:
        scratch_path = Path(scratch)
        archive = archive or fetch_archive(spec, scratch_path)
        print(f'verifying sha256 of {archive.name}')
        digest = sha256_of(archive, log=lambda *_: None)
        if digest != spec['sha256']:
            raise SystemExit(f'REFUSED: {archive.name} hashes {digest}, manifest pins {spec["sha256"]}. '
                             f'Not unpacking.')
        print('sha256 matches the manifest')
        extract(archive, spec, destination)
        _make_executable(spec, destination)
        fetch_common.write_receipt(
            destination, spec,
            {'bytes_on_disk': measure(destination), 'archive_bytes': archive.stat().st_size},
            manifest_path=spec['manifest_path'],
            fields={'repo': spec['repo'], 'tag': spec['tag'], 'asset': spec['asset'], 'rid': spec['rid']})
    return check(spec)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tool', choices=['mex', 'hsdlib', 'all'])
    parser.add_argument('--platform', default='host', choices=[*PLATFORMS, 'host'],
                        help='which build to fetch (default: this machine)')
    parser.add_argument('--check', action='store_true',
                        help='only report whether the existing unpack matches the manifest')
    parser.add_argument('--force', action='store_true', help='re-unpack even when current')
    parser.add_argument('--archive', type=Path,
                        help='use this local zip instead of downloading (single tool only)')
    args = parser.parse_args(argv)

    rid = host_platform() if args.platform == 'host' else args.platform
    tools = list(TOOLS) if args.tool == 'all' else [args.tool]
    if args.archive and len(tools) != 1:
        parser.error('--archive needs a single tool')
    ok = True
    for tool in tools:
        spec = load_tool(tool, rid)
        ok = fetch(spec, force=args.force, check_only=args.check, archive=args.archive) and ok
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
