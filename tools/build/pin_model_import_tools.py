"""Fill in the pins of app/utility/model_import_tools.json: versions in, URL, sha256 and size out, per platform.

The model import's tools (Blender 4, a Python 3.13 and the wheels rigswap needs) are downloaded by the app from the
official sources on the user's request (docs/dev/MODEL_IMPORT_TOOLS.md). Every file is pinned by URL, sha256 and
size, and nobody types a hash: this script reads each from the publisher.

    Blender            download.blender.org: the release's own blender-<v>.sha256 file
    Python (Windows)   python.org's embeddable zip; the digest is the one in python.org's signed .sigstore bundle
    Python (macOS, Linux)  python-build-standalone's release SHA256SUMS (install_only_stripped)
    wheels             PyPI's JSON API, at the versions app/utility/rigswap.requirements.txt lists (the one list)

The versions it pins are the manifest's ``pin`` block; the per-platform layout (archive root, entrypoint, trim list,
the paths that must survive the unpack) is ``LAYOUT`` here. It rewrites ``platforms`` and keeps every other key.

Each platform's ``on_disk`` is what a real install measured on disk per piece (Blender, the runtime), which the app's
Settings card shows before the download (assemble.estimate). ``--measured`` records it from install receipts
(``<data>/tools/model-import/receipt.json``), each piece only when the receipt is of the manifest's very downloads:
Blender's sha256, the runtime's key. A re-pin keeps a measured piece whose downloads did not move, and drops one whose
did; the app then estimates that piece from ratios until it is measured again.

    python tools/build/pin_model_import_tools.py                  # re-resolve the manifest's pins
    python tools/build/pin_model_import_tools.py --check          # exit 1 when the manifest is not what they resolve to
    python tools/build/pin_model_import_tools.py --pbs latest     # move to python-build-standalone's newest release
                                                                   # and the newest Python 3.13 in it
    python tools/build/pin_model_import_tools.py --blender 4.3.2 --python-win 3.13.17 --pbs 20261110
    python tools/build/pin_model_import_tools.py --measured win/receipt.json linux/receipt.json mac/receipt.json
                                                                   # record what installs measured (no network)

On Windows a requirement's own ``--hash`` must be the sha256 of the wheel picked for win-x64, so the two lists cannot
drift apart. Moving any pin needs a real import on each platform before it ships (the doc's last section).
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / 'app'
MANIFEST = APP / 'utility' / 'model_import_tools.json'
ASSEMBLE = REPO / 'app' / 'backend' / 'randall' / 'model_import' / 'tools' / 'assemble.py'
AGENT = 'ssbmNucleus-pin/1.0'
PLATFORMS = ('win-x64', 'linux-x64', 'osx-arm64')

BLENDER_DIR = 'https://download.blender.org/release/Blender{series}/'
PYTHON_ORG = 'https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip'
PBS_REPO = 'astral-sh/python-build-standalone'
PBS_API = 'https://api.github.com/repos/' + PBS_REPO + '/releases/{which}'
PBS_FILE = 'https://github.com/' + PBS_REPO + '/releases/download/{tag}/{name}'
PBS_TRIPLE = {'linux-x64': 'x86_64-unknown-linux-gnu', 'osx-arm64': 'aarch64-apple-darwin'}
PYPI = 'https://pypi.org/pypi/{name}/{version}/json'

# Wheels: CPython 3.13 on each platform, at the oldest OS the rest of the tools already need. bpy 5.2.2 is built for
# glibc 2.28 and macOS 11.0, and Blender 4.3 needs the same (Linux glibc 2.28, macOS 11.2).
GLIBC_FLOOR = (2, 28)
MACOS_FLOOR = (11, 0)

# The layout of each platform's downloads, by Blender series ({s}) and version ({v}). ``trim``: whole files and
# folders deleted after the unpack (the reasons are the manifest's _README); ``verify``: what must still be there.
# macOS keeps Blender.app whole: deleting files inside a signed bundle breaks its seal.
_BLENDER_KEEP = ['{s}/scripts/addons_core/io_scene_gltf2/__init__.py', '{s}/datafiles/colormanagement/config.ocio',
                 '{s}/datafiles/studiolights']
_TRIM = ['{s}/datafiles/locale', '{s}/scripts/addons_core/cycles', '{s}/python/bin']
LAYOUT = {
    'win-x64': {
        'blender': {'file': 'blender-{v}-windows-x64.zip', 'format': 'zip', 'root': 'blender-{v}-windows-x64',
                    'entrypoint': 'blender.exe', 'trim': ['blender.pdb', *_TRIM],
                    'verify': ['{s}/python/lib/site-packages/numpy/__init__.py', *_BLENDER_KEEP]},
        'python': {'format': 'zip', 'kind': 'embeddable', 'root': '', 'entrypoint': 'python.exe',
                   'site_packages': 'Lib/site-packages', 'verify': ['python313.zip', 'python313._pth'],
                   'wheel_verify': ['bpy/__init__.pyd', 'numpy/__init__.py', 'PIL/__init__.py']},
    },
    'linux-x64': {
        'blender': {'file': 'blender-{v}-linux-x64.tar.xz', 'format': 'tar.xz', 'root': 'blender-{v}-linux-x64',
                    'entrypoint': 'blender', 'trim': list(_TRIM),
                    'verify': ['{s}/python/lib/python3.11/site-packages/numpy/__init__.py', *_BLENDER_KEEP]},
        'python': {'format': 'tar.gz', 'kind': 'standalone', 'root': 'python', 'entrypoint': 'bin/python3',
                   'site_packages': 'lib/python3.13/site-packages', 'verify': ['lib/python3.13/os.py'],
                   'wheel_verify': ['bpy/__init__.so', 'numpy/__init__.py', 'PIL/__init__.py']},
    },
    # A .dmg's ``root`` is the item copied out of the mounted image, kept under its own name (a bundle stays a
    # .app), so the paths below start with it.
    'osx-arm64': {
        'blender': {'file': 'blender-{v}-macos-arm64.dmg', 'format': 'dmg', 'root': 'Blender.app',
                    'entrypoint': 'Blender.app/Contents/MacOS/Blender', 'trim': [],
                    'verify': ['Blender.app/Contents/Resources/{s}/python/lib/python3.11/site-packages/numpy/'
                               '__init__.py', *('Blender.app/Contents/Resources/' + p for p in _BLENDER_KEEP)]},
        'python': {'format': 'tar.gz', 'kind': 'standalone', 'root': 'python', 'entrypoint': 'bin/python3',
                   'site_packages': 'lib/python3.13/site-packages', 'verify': ['lib/python3.13/os.py'],
                   'wheel_verify': ['bpy/__init__.so', 'numpy/__init__.py', 'PIL/__init__.py']},
    },
}


class Web:
    """The few reads this script makes. Tests pass a stand-in with the same three methods."""

    def _open(self, url, method='GET'):
        return urllib.request.urlopen(urllib.request.Request(url, method=method, headers={'User-Agent': AGENT}),
                                      timeout=60)

    def text(self, url):
        with self._open(url) as response:
            return response.read().decode('utf-8')

    def json(self, url):
        return json.loads(self.text(url))

    def size(self, url):
        """The file's size from a HEAD request (after redirects)."""
        with self._open(url, 'HEAD') as response:
            length = response.headers.get('Content-Length')
        if not length:
            raise SystemExit(f'{url} answered no Content-Length')
        return int(length)


# ------------------------------------------------------------------ the sources

def _fill(text, **values):
    return text.format(**values) if isinstance(text, str) else [t.format(**values) for t in text]


def series(version):
    return '.'.join(version.split('.')[:2])


def blender_sums(web, version):
    """{file name: sha256} from Blender's own checksum file for ``version``."""
    url = BLENDER_DIR.format(series=series(version)) + f'blender-{version}.sha256'
    sums = {}
    for line in web.text(url).splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r'[0-9a-f]{64}', parts[0]):
            sums[parts[1].lstrip('*')] = parts[0]
    if not sums:
        raise SystemExit(f'{url} lists no checksums')
    return sums


def pin_blender(web, platform, version, sums):
    layout = LAYOUT[platform]['blender']
    values = dict(v=version, s=series(version))
    name = _fill(layout['file'], **values)
    if name not in sums:
        raise SystemExit(f"Blender {version}'s checksum file has no {name}")
    url = BLENDER_DIR.format(series=series(version)) + name
    return {'version': version, 'url': url, 'sha256': sums[name], 'size': web.size(url),
            'format': layout['format'], 'root': _fill(layout['root'], **values),
            'entrypoint': layout['entrypoint'], 'trim': _fill(layout['trim'], **values),
            'verify': _fill(layout['verify'], **values)}


def sigstore_sha256(web, url):
    """The sha256 python.org's signed bundle for ``url`` states (``<url>.sigstore``: its message digest)."""
    bundle = web.json(url + '.sigstore')
    digest = (bundle.get('messageSignature') or {}).get('messageDigest') or {}
    if digest.get('algorithm') != 'SHA2_256' or not digest.get('digest'):
        raise SystemExit(f'{url}.sigstore states no SHA2_256 digest')
    return base64.b64decode(digest['digest']).hex()


def _python_entry(platform, version, url, sha256, size, extra=None):
    layout = LAYOUT[platform]['python']
    return {'version': version, 'url': url, 'sha256': sha256, 'size': size, **(extra or {}),
            **{k: layout[k] for k in ('format', 'kind', 'root', 'entrypoint', 'site_packages', 'verify',
                                      'wheel_verify')}}


def pin_python_org(web, version):
    url = PYTHON_ORG.format(v=version)
    return _python_entry('win-x64', version, url, sigstore_sha256(web, url), web.size(url))


def pbs_release(web, tag):
    """python-build-standalone's release ``tag`` ('latest' for the newest) -> (tag, {asset name: size})."""
    release = web.json(PBS_API.format(which='latest' if tag == 'latest' else f'tags/{tag}'))
    return release['tag_name'], {a['name']: int(a['size']) for a in release.get('assets') or []}


def pbs_name(platform, version, tag):
    return f'cpython-{version}+{tag}-{PBS_TRIPLE[platform]}-install_only_stripped.tar.gz'


def newest_313(assets, tag):
    """The newest CPython 3.13.x python-build-standalone ``tag`` has for every platform here."""
    found = []
    for name in assets:
        match = re.fullmatch(r'cpython-(3\.13\.\d+)\+' + re.escape(tag) + r'-(.+)-install_only_stripped\.tar\.gz',
                             name)
        if match and match.group(2) in PBS_TRIPLE.values():
            found.append(match.group(1))
    versions = sorted({v for v in found if found.count(v) == len(PBS_TRIPLE)}, key=lambda v: int(v.split('.')[2]))
    if not versions:
        raise SystemExit(f'python-build-standalone {tag} has no CPython 3.13 install_only_stripped for '
                         + ', '.join(PBS_TRIPLE.values()))
    return versions[-1]


def pbs_sums(web, tag):
    sums = {}
    for line in web.text(PBS_FILE.format(tag=tag, name='SHA256SUMS')).splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r'[0-9a-f]{64}', parts[0]):
            sums[parts[1].lstrip('*')] = parts[0]
    return sums


def pin_pbs(platform, version, tag, assets, sums):
    name = pbs_name(platform, version, tag)
    if name not in sums or name not in assets:
        raise SystemExit(f'python-build-standalone {tag} has no {name} (or no checksum for it)')
    return _python_entry(platform, version, PBS_FILE.format(tag=tag, name=name), sums[name], assets[name],
                         {'release': tag})


# ------------------------------------------------------------------ the wheels

def requirements(path):
    """[(name, version, {sha256, ...})] from a pip requirements file with ``--hash`` lines (the hashes optional)."""
    text = Path(path).read_text(encoding='utf-8')
    found = []
    for block in re.split(r'(?<!\\)\n', text.replace('\r', '')):
        block = block.split('#', 1)[0].replace('\\\n', ' ').strip()
        if not block:
            continue
        match = re.match(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;]+)', block)
        if not match:
            raise SystemExit(f'{Path(path).name}: not a pinned requirement: {block}')
        found.append((match.group(1), match.group(2), set(re.findall(r'--hash=sha256:([0-9a-f]{64})', block))))
    return found


def wheel_tags(filename):
    """(python tags, abi tags, platform tags) of a wheel file name."""
    parts = filename[:-len('.whl')].split('-')
    if len(parts) not in (5, 6):
        return None
    py, abi, plat = parts[-3:]
    return set(py.split('.')), set(abi.split('.')), set(plat.split('.'))


def _glibc(tag):
    legacy = {'manylinux1_x86_64': (2, 5), 'manylinux2010_x86_64': (2, 12), 'manylinux2014_x86_64': (2, 17)}
    if tag in legacy:
        return legacy[tag]
    match = re.fullmatch(r'manylinux_(\d+)_(\d+)_x86_64', tag)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _platform_rank(platform, tags):
    """(rank, os floor) of the best platform tag here for ``platform``, or None when none fits. A platform wheel
    ranks above a pure one; at the same rank a lower OS floor is better (it runs on more machines)."""
    best = None
    for tag in tags:
        if tag == 'any':
            found = (1, (0, 0))
        elif platform == 'win-x64':
            found = (2, (0, 0)) if tag == 'win_amd64' else None
        elif platform == 'linux-x64':
            glibc = _glibc(tag)
            found = (2, glibc) if glibc and glibc <= GLIBC_FLOOR else None
        else:
            match = re.fullmatch(r'macosx_(\d+)_(\d+)_(arm64|universal2)', tag)
            floor = (int(match.group(1)), int(match.group(2))) if match else None
            found = ((3 if match.group(3) == 'arm64' else 2), floor) if floor and floor <= MACOS_FLOOR else None
        if found and (best is None or (found[0], tuple(-x for x in found[1])) > (best[0], tuple(-x for x in best[1]))):
            best = found
    return best


def _abi_rank(pythons, abis):
    """3: built for CPython 3.13 itself; 2: the stable ABI from an older CPython; 1: pure Python; None: not 3.13's."""
    if 'cp313' in abis and 'cp313' in pythons:
        return 3
    if 'abi3' in abis and any(re.fullmatch(r'cp3(\d+)', p) and int(p[3:]) <= 13 for p in pythons):
        return 2
    if 'none' in abis and pythons & {'py3', 'py313', 'cp313'}:
        return 1
    return None


def pick_wheel(files, platform, name, version):
    """The wheel of ``files`` (PyPI JSON ``urls``) a CPython 3.13 on ``platform`` installs."""
    best, best_score = None, None
    for entry in files:
        if entry.get('packagetype') != 'bdist_wheel' or entry.get('yanked'):
            continue
        tags = wheel_tags(entry['filename'])
        if not tags:
            continue
        abi, plat = _abi_rank(tags[0], tags[1]), _platform_rank(platform, tags[2])
        if abi is None or plat is None:
            continue
        score = (abi, plat[0], tuple(-x for x in plat[1]))
        if best_score is None or score > best_score:
            best, best_score = entry, score
    if best is None:
        raise SystemExit(f'PyPI has no {name} {version} wheel for CPython 3.13 on {platform}')
    return best


def pin_wheels(web, platform, reqs):
    wheels = []
    for name, version, hashes in reqs:
        files = web.json(PYPI.format(name=name, version=version)).get('urls') or []
        if platform == 'win-x64' and hashes:
            chosen = [f for f in files if f.get('digests', {}).get('sha256') in hashes
                      and f.get('packagetype') == 'bdist_wheel']
            picked = pick_wheel(files, platform, name, version)
            if not chosen or picked['digests']['sha256'] not in hashes:
                raise SystemExit(f'{name} {version}: the requirements file pins a hash that is not the win-x64 '
                                 f'wheel PyPI has ({picked["filename"]} {picked["digests"]["sha256"]})')
            entry = picked
        else:
            entry = pick_wheel(files, platform, name, version)
        wheels.append({'name': name, 'version': version, 'filename': entry['filename'], 'url': entry['url'],
                       'sha256': entry['digests']['sha256'], 'size': int(entry['size'])})
    return wheels


# ------------------------------------------------------------------ measured on disk

def runtime_key(entry):
    """The key the app gives ``entry``'s runtime (assemble.runtime_key: its Python and wheels), from the app's own
    assemble.py (standard library only), so a receipt and the manifest are compared as the app compares them."""
    spec = importlib.util.spec_from_file_location('nucleus_tools_assemble_for_pin', ASSEMBLE)
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    return assemble.runtime_key(entry)


def kept_on_disk(old, new):
    """What ``old`` (a platform entry before a re-pin) measured on disk that still holds for ``new``: Blender's while
    its file and trim list are the same, the runtime's while its key is."""
    on_disk = (old or {}).get('on_disk') or {}
    kept = {}
    blender, runtime = on_disk.get('blender'), on_disk.get('runtime')
    if blender and blender.get('sha256') == new['blender']['sha256'] \
            and (old.get('blender') or {}).get('trim') == new['blender']['trim']:
        kept['blender'] = blender
    if runtime and runtime.get('key') == runtime_key(new):
        kept['runtime'] = runtime
    return kept


def record_measured(manifest, receipts, *, log=print):
    """``manifest`` with each receipt's bytes on disk (an install's receipt.json) in its platform's ``on_disk``, for
    each piece the receipt is of the manifest's very downloads. A receipt that matches no piece is refused."""
    platforms = json.loads(json.dumps(manifest['platforms']))
    for path in receipts:
        receipt = json.loads(Path(path).read_text(encoding='utf-8'))
        platform = receipt.get('platform')
        if platform not in platforms:
            raise SystemExit(f'{path}: platform {platform!r} is not in the manifest')
        entry = platforms[platform]
        blender, runtime = receipt.get('blender') or {}, receipt.get('runtime') or {}
        found = {}
        if blender.get('sha256') == entry['blender']['sha256'] and isinstance(blender.get('bytes_on_disk'), int):
            found['blender'] = {'sha256': blender['sha256'], 'bytes': blender['bytes_on_disk']}
        if runtime.get('key') == runtime_key(entry) and isinstance(runtime.get('bytes_on_disk'), int):
            found['runtime'] = {'key': runtime['key'], 'bytes': runtime['bytes_on_disk']}
        if not found:
            raise SystemExit(f"{path}: neither piece is the manifest's {platform} pin (Blender sha256, runtime key)")
        for piece in ('blender', 'runtime'):
            if piece not in found:
                log(f'{platform}: {path} is not of the pinned {piece}; its size is not recorded')
        entry['on_disk'] = {**(entry.get('on_disk') or {}), **found}
        log(f'{platform}: on disk ' + ', '.join(f'{piece} {value["bytes"]:,} B' for piece, value in found.items()))
    return {**manifest, 'platforms': platforms}


# ------------------------------------------------------------------ the manifest

def resolve(manifest, web, *, log=print):
    """``manifest`` with ``platforms`` resolved from its ``pin`` block (``on_disk`` kept where it still holds)."""
    pin = manifest['pin']
    reqs = requirements(APP / pin['requirements'])
    log(f'Blender {pin["blender"]}: download.blender.org checksums')
    sums = blender_sums(web, pin['blender'])
    tag, assets = pbs_release(web, pin['python_build_standalone'])
    pbs = pbs_sums(web, tag)
    platforms = {}
    for platform in PLATFORMS:
        version = pin['python'][platform]
        log(f'{platform}: Python {version}, {len(reqs)} wheels')
        python = (pin_python_org(web, version) if platform == 'win-x64'
                  else pin_pbs(platform, version, tag, assets, pbs))
        platforms[platform] = {'blender': pin_blender(web, platform, pin['blender'], sums), 'python': python,
                               'wheels': pin_wheels(web, platform, reqs)}
        kept = kept_on_disk((manifest.get('platforms') or {}).get(platform), platforms[platform])
        if kept:
            platforms[platform]['on_disk'] = kept
    return {**manifest, 'pin': {**pin, 'python_build_standalone': tag}, 'platforms': platforms}


def apply_args(manifest, args, web):
    """The ``pin`` block with the command line's moves applied."""
    pin = json.loads(json.dumps(manifest['pin']))
    if args.blender:
        pin['blender'] = args.blender
    if args.python_win:
        pin['python']['win-x64'] = args.python_win
    if args.pbs:
        tag, assets = pbs_release(web, args.pbs)
        pin['python_build_standalone'] = tag
        newest = newest_313(assets, tag)
        for platform in PBS_TRIPLE:
            pin['python'][platform] = newest
    return {**manifest, 'pin': pin}


def totals(manifest):
    """{platform: download bytes} for a report."""
    return {platform: entry['blender']['size'] + entry['python']['size'] + sum(w['size'] for w in entry['wheels'])
            for platform, entry in (manifest.get('platforms') or {}).items()}


def dump(manifest):
    return json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'


def main(argv=None, web=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='exit 1 when the manifest is not what its pins resolve to')
    parser.add_argument('--blender', help='pin this Blender version')
    parser.add_argument('--python-win', help="pin this python.org embeddable Python on Windows")
    parser.add_argument('--pbs', help="python-build-standalone release tag, or 'latest' (the newest 3.13 in it)")
    parser.add_argument('--measured', nargs='+', type=Path, metavar='RECEIPT',
                        help="record what installs measured on disk (their receipt.json) into the manifest as it is; "
                             'nothing is re-resolved')
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if args.measured:
        recorded = record_measured(manifest, args.measured)
        if args.check:
            same = dump(recorded) == dump(manifest)
            print('ok: the manifest has these sizes' if same else 'STALE: the manifest lacks these sizes')
            return 0 if same else 1
        args.manifest.write_text(dump(recorded), encoding='utf-8')
        print(f'wrote {args.manifest}')
        return 0
    web = web or Web()
    resolved = resolve(apply_args(manifest, args, web), web)
    if args.check:
        same = dump(resolved) == dump(manifest)
        print('ok: the manifest matches its pins' if same else 'STALE: the manifest is not what its pins resolve to')
        return 0 if same else 1
    args.manifest.write_text(dump(resolved), encoding='utf-8')
    for platform, size in totals(resolved).items():
        print(f'{platform}: {size / 1e6:.0f} MB to download')
    print(f'wrote {args.manifest}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
