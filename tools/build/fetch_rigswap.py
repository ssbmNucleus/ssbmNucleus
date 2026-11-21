"""Reproduce the installer's rigswap package (utility/rigswap/app) from utility/rigswap.manifest.json.

Randall's model import runs rigswap as a subprocess. Since 0.9.0 its Python and Blender are a download the user
starts in Settings (utility/model_import_tools.json, docs/dev/MODEL_IMPORT_TOOLS.md); the installer carries only
rigswap's own package, on every platform: its source at the pinned commit, compiled. Only bytecode ships, except the
files Blender 4 runs with its own Python (``rigswap.source_kept``). The tree (``app/utility/rigswap/app/``) is
git-ignored; this script and the manifest are tracked, so any build machine can recreate it:

    python tools/build/fetch_rigswap.py              # take the commit, compile it
    python tools/build/fetch_rigswap.py --check      # is the tree already the pinned one?

rigswap's package comes from a local clone (``--rigswap-repo``, else RIGSWAP_REPO, else ~/projects/rigswap) that
has the pinned commit. The bytecode must be CPython 3.13's, what the downloaded runtime is on every platform: it is
compiled by ``--python``, else the Python running this when it is 3.13 (the Windows venv), else ``python3.13`` on
PATH, else the very Python the app downloads for this platform (utility/model_import_tools.json), fetched and checked
by the app's own assembly code into app/build/rigswap-compiler/.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_common import PROJECT_ROOT, RECEIPT_NAME, load_manifest, measure  # noqa: E402

MANIFEST = PROJECT_ROOT / 'utility' / 'rigswap.manifest.json'
TOOLS = PROJECT_ROOT / 'utility' / 'model_import_tools.json'
ASSEMBLE = PROJECT_ROOT / 'backend' / 'randall' / 'model_import' / 'tools' / 'assemble.py'
COMPILER = PROJECT_ROOT / 'build' / 'rigswap-compiler'
REQUIRED = ('unpack_to', 'entrypoint', 'rigswap')
PYTHON = (3, 13)        # the downloaded runtime's minor version: its bytecode is what ships


def _version_of(python: str):
    done = subprocess.run([python, '-c', 'import sys; print(*sys.version_info[:3])'], capture_output=True, text=True,
                          **_quiet())
    return tuple(int(x) for x in done.stdout.split()) if done.returncode == 0 and done.stdout.strip() else None


def _platform_key():
    import platform
    machine = platform.machine().lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, machine)
    system = 'win' if sys.platform == 'win32' else 'osx' if sys.platform == 'darwin' else 'linux'
    return f'{system}-{arch}'


def _pinned_python() -> str:
    """The CPython 3.13 the app downloads for this platform, sha256-checked and unpacked by assemble.py (loaded from
    its file: it is standard library only) into COMPILER. -> its executable."""
    spec = importlib.util.spec_from_file_location('nucleus_tools_assemble', ASSEMBLE)
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    key = _platform_key()
    entry = json.loads(TOOLS.read_text(encoding='utf-8'))['platforms'].get(key)
    if not entry:
        raise SystemExit(f'{TOOLS.name} names no Python for {key}; pass --python <a CPython 3.13>')
    python = entry['python']
    folder = COMPILER / python['version']
    executable = folder / python['entrypoint']
    if not executable.exists():
        print(f'fetching the pinned Python {python["version"]} for {key} to compile with')
        archive = assemble.fetch(COMPILER, f'Python {python["version"]}', python)
        shutil.rmtree(folder, ignore_errors=True)
        if python['format'] == 'zip':
            assemble.unzip(archive, folder, mapper=assemble._strip(python.get('root') or ''))
        else:
            raw = COMPILER / f'{python["version"]}.raw'
            shutil.rmtree(raw, ignore_errors=True)
            assemble.untar(archive, raw)
            assemble._lift(raw, python.get('root') or '', folder)
        assemble._executable(executable)
    return str(executable)


def compiler(given: str | None = None) -> str:
    """A CPython 3.13 to compile rigswap with (the module docstring says which)."""
    if given:
        if (_version_of(given) or ())[:2] != PYTHON:
            raise SystemExit(f'--python {given} is not a CPython {PYTHON[0]}.{PYTHON[1]}')
        return given
    if sys.version_info[:2] == PYTHON:
        return sys.executable
    found = shutil.which(f'python{PYTHON[0]}.{PYTHON[1]}')
    if found and (_version_of(found) or ())[:2] == PYTHON:
        return found
    return _pinned_python()


def _quiet():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def target(manifest: dict) -> Path:
    return PROJECT_ROOT / manifest['unpack_to']


def _sources(destination: Path, manifest: dict, log) -> bool:
    """No rigswap source ships but the files kept for Blender 4."""
    kept = {Path(p).as_posix() for p in manifest['rigswap']['source_kept']}
    stray = [p.relative_to(destination).as_posix() for p in destination.rglob('*.py')
             if p.relative_to(destination).as_posix() not in kept]
    if stray:
        log(f'SOURCE: {len(stray)} rigswap source files would ship, e.g. {stray[:3]}')
    return not stray


def check(manifest: dict, *, log=print) -> bool:
    destination = target(manifest)
    receipt_path = destination / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.is_file() else {}
    if receipt.get('rigswap_commit') != manifest['rigswap']['commit']:
        log(f'STALE: {destination} holds rigswap {receipt.get("rigswap_commit")!r}; the manifest pins '
            f'{manifest["rigswap"]["commit"]}')
        return False
    missing = [p for p in [manifest['entrypoint'], *manifest.get('verify_after_unpack', ())]
               if not (destination / p).exists()]
    if missing:
        log(f'INCOMPLETE: {destination} lacks {", ".join(missing)}')
        return False
    if receipt.get('python') and tuple(receipt['python'][:2]) != PYTHON:
        log(f'WRONG PYTHON: compiled by {receipt["python"]}, the runtime is {PYTHON}')
        return False
    if not _sources(destination, manifest, log):
        return False
    log(f'ok: rigswap {manifest["rigswap"]["commit"][:9]} at {destination} ({measure(destination) / 1e6:.1f} MB)')
    return True


def _rigswap_repo(given: Path | None) -> Path:
    repo = Path(given or os.environ.get('RIGSWAP_REPO') or Path.home() / 'projects' / 'rigswap')
    if not (repo / '.git').exists():
        raise SystemExit(f'no rigswap clone at {repo}: pass --rigswap-repo or set RIGSWAP_REPO')
    return repo


def _package(repo: Path, manifest: dict, app: Path, python: str) -> int:
    """rigswap's package at the pinned commit into ``app``, compiled beside where each source was; the source
    deleted but ``source_kept``. -> how many modules."""
    pin = manifest['rigswap']
    archive = subprocess.run(['git', '-C', str(repo), 'archive', '--format=zip', pin['commit'], pin['package']],
                             capture_output=True, **_quiet())
    if archive.returncode:
        raise SystemExit(f'git archive {pin["commit"]} failed in {repo} (fetch it first): '
                         f'{archive.stderr.decode(errors="replace").strip()}')
    with zipfile.ZipFile(io.BytesIO(archive.stdout)) as bundle:
        bundle.extractall(app)
    # -s: a traceback names rigswap's own path (rigswap\plugins\...), not this build's staging folder
    done = subprocess.run([python, '-m', 'compileall', '-b', '-q', '-s', str(app), str(app / pin['package'])],
                          capture_output=True, text=True, **_quiet())
    if done.returncode:
        raise SystemExit(f'compiling rigswap failed: {done.stdout}{done.stderr}')
    kept = {Path(p).as_posix() for p in pin['source_kept']}
    modules = 0
    for source in list(app.rglob('*.py')):
        relative = source.relative_to(app).as_posix()
        if relative in kept:
            source.with_suffix('.pyc').unlink(missing_ok=True)   # Python 3.13 bytecode Blender's 3.11 cannot read
        else:
            source.unlink()
        modules += 1
    for cache in list(app.rglob('__pycache__')):
        shutil.rmtree(cache)
    return modules


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='only report whether the tree matches the manifest')
    parser.add_argument('--rigswap-repo', type=Path, help='a local rigswap clone holding the pinned commit')
    parser.add_argument('--python', help='a CPython 3.13 to compile with (default: see above)')
    parser.add_argument('--force', action='store_true', help='rebuild even when the tree already matches')
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest, required=REQUIRED)
    destination = target(manifest)
    if args.check:
        return 0 if check(manifest) else 1
    if not args.force and check(manifest, log=lambda *_: None):
        print(f'rigswap {manifest["rigswap"]["commit"][:9]} is already at {destination}; nothing to do '
              '(--force to redo it)')
        return 0
    repo = _rigswap_repo(args.rigswap_repo)
    python = compiler(args.python)
    version = _version_of(python)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(destination.parent), prefix='.fetch-rigswap-') as staging:
        stage = Path(staging) / 'app'
        print(f'compiling rigswap {manifest["rigswap"]["commit"][:9]} from {repo}')
        modules = _package(repo, manifest, stage, python)
        missing = [p for p in [manifest['entrypoint'], *manifest.get('verify_after_unpack', ())]
                   if not (stage / p).exists()]
        if missing:
            raise SystemExit(f'the compiled package lacks {", ".join(missing)}')
        receipt = {'manifest': str(Path(args.manifest).resolve().relative_to(PROJECT_ROOT)).replace('\\', '/'),
                   'rigswap_commit': manifest['rigswap']['commit'], 'python': list(version or ()),
                   'modules': modules,
                   'bytes_on_disk': measure(stage),
                   'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        (stage / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        if destination.exists():
            print(f'replacing the existing tree at {destination}')
            shutil.rmtree(destination)
        stage.rename(destination)
    old = destination.parent / 'python'
    if old.is_dir():
        print(f'note: {old} is the old bundled runtime; nothing ships it since 0.9.0 (the app downloads its tools), '
              'so it can be deleted')
    if not check(manifest):
        return 1
    print('rigswap is bundled when the assistant gate ships (tools/build/ship_rules.json stages utility/rigswap/app '
          'on every platform; package.json extraResources copies it to resources/utility/rigswap/app).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
