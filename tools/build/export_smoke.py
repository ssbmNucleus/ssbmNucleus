"""Prove that the app can still build an ISO, end to end, before we ship it.

0.8.7 shipped unable to export anything. The change was C#-only -- a padding
pass appended to `MexWorkspace.ExportISO` that reopened the finished image
while the writer still held it -- and nothing in the release ran a real export,
so every gate passed and every user's build failed on its last step.

Two checks, both against the real `mexcli` binary:

  contract  the error MexCLI reports for a failed export must arrive on ONE
            line. The backend reads that stream line by line, so a
            pretty-printed error parses as nothing and the app falls back to
            reporting debug chatter. Fast (no export).
  export    create or reuse a project, export it, and require a real ISO:
            exit 0, a success result, the disc padding Melee's rounded reads
            need, and -- the 0.8.7 regression itself -- no handle left open on
            the image afterwards. Slow (a few minutes, a few GB of disk).

Run it standalone, or let `ci.py release` run it as a gate:

    python tools/build/export_smoke.py                 # both checks
    python tools/build/export_smoke.py --contract-only # the fast one
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2] / 'app'   # tools/build -> repo root -> app/ (the dir holding package.json)
sys.path.insert(0, str(REPO_ROOT / 'backend'))

# A vanilla Melee image is ~1.36 GB; anything far below that is not an ISO.
MIN_ISO_BYTES = 1_000_000_000
EXPORT_TIMEOUT = 30 * 60


class SmokeFailure(RuntimeError):
    pass


def mexcli_path():
    """The pinned prebuilt mexcli (utility/mex/<rid>/, from fetch_native.py).

    This is the exact binary build.bat copies into the installer, so it is the
    one the gate must exercise.
    """
    from core.config import MEXCLI_PATH

    path = Path(MEXCLI_PATH)
    if not path.is_file():
        raise SmokeFailure(
            f'mexcli not fetched (expected {MEXCLI_PATH}). Run '
            '`python tools/build/fetch_native.py mex --platform host`; this gate '
            'cannot be skipped for a release.')
    # The release zip ships codes.gct beside the binary, which is where mexcli reads it.
    if not (path.parent / 'codes.gct').is_file():
        raise SmokeFailure(f'codes.gct missing beside {path}; re-run fetch_native.py --force')
    return path

def run_mexcli(*args, timeout=EXPORT_TIMEOUT):
    proc = subprocess.run([str(mexcli_path()), *args], capture_output=True,
                          text=True, timeout=timeout, cwd=str(REPO_ROOT))
    return proc


def result_line(stdout):
    """The result MexCLI reports, if it put one on a line of its own."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (
                data.get('success') is not None
                or data.get('status') in ('completed', 'error')):
            return data
    return None


def check_error_is_one_line():
    """A failed export must report its reason on a single line.

    Guards the second half of the 0.8.7 break: MexCLI serialised its error
    JSON indented, the backend's line reader parsed none of it, and users got
    a dialog full of [DEBUG] portrait-compression lines instead of the cause.
    """
    missing = Path(__file__).resolve().parent / 'no-such-project.mexproj'
    proc = run_mexcli('export', str(missing), 'unused.iso', '1.0', 'false',
                      'false', timeout=120)
    if proc.returncode == 0:
        raise SmokeFailure('mexcli export accepted a project that does not exist')
    data = result_line(proc.stdout)
    if data is None:
        raise SmokeFailure(
            'a failed export did not report its error on one line, so the app '
            'cannot read it and will fall back to showing stderr debug output. '
            'stdout was:\n' + proc.stdout[:2000])
    if not data.get('error'):
        raise SmokeFailure(f'failed export reported no error text: {data}')
    return data['error']


def find_project(explicit=None):
    """A .mexproj to base the smoke export on, or None.

    Never the one we export: an export rewrites the project's portraits and
    saves the workspace, so the caller copies this somewhere disposable first.
    """
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise SmokeFailure(f'--project is not a file: {path}')
        return path
    env = os.environ.get('NUCLEUS_SMOKE_PROJECT')
    if env:
        return find_project(env)
    for candidate in sorted((REPO_ROOT / 'projects').glob('*/project.mexproj')):
        return candidate
    return None


def copy_project(project, destination):
    destination.mkdir(parents=True, exist_ok=True)
    copy = destination / project.parent.name
    shutil.copytree(project.parent, copy)
    return copy / project.name


def find_vanilla_iso(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get('NUCLEUS_VANILLA_ISO')
    if env:
        candidates.append(Path(env))
    # Worktrees share the validated input recorded by the normal checkout.
    from release_paths import vanilla_iso_records
    for record in vanilla_iso_records(REPO_ROOT):
        try:
            candidates.append(Path(json.loads(record.read_text(encoding='utf-8'))['path']))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    candidates += sorted(REPO_ROOT.glob('*.iso'))
    for path in candidates:
        if path.is_file() and path.stat().st_size >= MIN_ISO_BYTES:
            return path
    return None


def create_project(iso, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    proc = run_mexcli('create', str(iso), str(workdir), 'export_smoke')
    if proc.returncode != 0:
        raise SmokeFailure(
            f'could not create a project from {iso.name}:\n{proc.stdout[:2000]}')
    for candidate in sorted(workdir.rglob('*.mexproj')):
        return candidate
    raise SmokeFailure(f'mexcli create wrote no .mexproj under {workdir}')


def check_export(project, out_iso):
    from core.iso_reads import inspect

    started = time.monotonic()
    proc = run_mexcli('export', str(project), str(out_iso), '1.0', 'false', 'false')
    elapsed = time.monotonic() - started
    data = result_line(proc.stdout)
    if proc.returncode != 0:
        reason = (data or {}).get('error') or proc.stdout[-2000:] or proc.stderr[-2000:]
        raise SmokeFailure(f'export failed (exit {proc.returncode}): {reason}')
    if not data or data.get('success') is not True:
        raise SmokeFailure(f'export exited 0 without reporting success: {data}')
    if not out_iso.is_file():
        raise SmokeFailure('export reported success but wrote no ISO')
    size = out_iso.stat().st_size
    if size < MIN_ISO_BYTES:
        raise SmokeFailure(f'exported ISO is only {size:,} bytes')

    # The 0.8.7 regression itself: the export used to leave a handle open on
    # the image, so its own padding pass could not reopen it exclusively.
    # Anything the app does with the file afterwards -- padding, os.replace
    # into place, hashing -- needs this to hold.
    try:
        with out_iso.open('r+b'):
            pass
    except OSError as exc:
        raise SmokeFailure(f'the exported ISO is still locked after export: {exc}')

    report = inspect(out_iso)
    if report['status'] != 'PASS_ROUNDED_DVD_READS':
        raise SmokeFailure(
            f'exported ISO fails Melee\'s rounded disc reads: {report["status"]}; '
            f'{len(report["issues"])} file(s) read past the end of the image')
    if size % 2048:
        raise SmokeFailure(f'exported ISO does not end on a sector boundary ({size:,} B)')
    return dict(bytes=size, files=report['files'], seconds=round(elapsed, 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', help='.mexproj to export (default: the first under projects/)')
    parser.add_argument('--iso', help='vanilla ISO to create a project from when there is none')
    parser.add_argument('--contract-only', action='store_true',
                        help='only check that a failed export reports on one line')
    parser.add_argument('--keep', action='store_true', help='keep the exported ISO')
    args = parser.parse_args(argv)

    try:
        error = check_error_is_one_line()
        print(f'  contract ok: a failed export reports "{error[:70]}..."')
        if args.contract_only:
            return 0

        temp_root = Path(tempfile.mkdtemp(prefix='nucleus_export_smoke_'))
        try:
            # Prefer a fresh project from a vanilla ISO: it is what a new user
            # actually builds, and it touches nothing of the caller's. An
            # existing project is a fallback, and only ever as a copy -- an
            # export rewrites portraits and saves the workspace in place.
            iso = find_vanilla_iso(args.iso)
            existing = find_project(args.project)
            if args.project or iso is None:
                if existing is None:
                    raise SmokeFailure(
                        'nothing to export: no vanilla ISO to create a project from '
                        'and no project under projects/. Pass --iso or --project (or '
                        'set NUCLEUS_VANILLA_ISO / NUCLEUS_SMOKE_PROJECT). A release '
                        'must not skip this gate.')
                print(f'  copying {existing.parent.name} (the original is not touched)...')
                project = copy_project(existing, temp_root / 'copy')
            else:
                print(f'  creating a project from {iso.name}...')
                project = create_project(iso, temp_root / 'project')
            print(f'  exporting {project.parent.name}...')
            out_iso = temp_root / 'export_smoke.iso'
            stats = check_export(project, out_iso)
            print(f'  export ok: {stats["bytes"]:,} B, {stats["files"]} files, '
                  f'{stats["seconds"]}s, padding intact, no handle left open')
            if args.keep:
                print(f'  kept: {out_iso}')
                return 0
        finally:
            if not args.keep:
                shutil.rmtree(temp_root, ignore_errors=True)
        return 0
    except SmokeFailure as exc:
        print(f'EXPORT SMOKE FAILED: {exc}', file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print('EXPORT SMOKE FAILED: mexcli did not finish', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
