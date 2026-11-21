"""The pristine test base: one untouched m-ex project of the vanilla ISO, built
once and copied for every one-mod test build.

`mexcli create` turns the vanilla ISO into an m-ex project. On a hard disk that
takes about three minutes, and every Test in Game used to pay it. Now it runs
once per (vanilla ISO, MexCLI) pair. The result is kept here and never written
to: each test copies it into its own fresh proj_<id> folder and installs its one
mod there (test_build.create_temp_project), then deletes that copy. A test still
starts from a project nothing else has touched, so it can never be polluted by
a previous one.

Layout of the root (storage/test-builds/pristine-base/):

    base-<key>/                         the base for one (ISO, MexCLI) pair
    base-<key>/.nucleus-pristine.json   what it was built from (not copied)
    .building-<id>/                     a build in progress
    .trash-<id>/                        an old base being deleted
    ../pristine-base.lock               one builder or copier at a time

<key> hashes the ISO's size, mtime and first and last MiB, the MexCLI files that
decide what `create` writes, and FORMAT. A different ISO or a MexCLI update gives
a new key: the next test builds a new base and the old one is deleted.

A base is never half-built. `create` writes into .building-<id>/, the record is
written only after it succeeds, and one rename turns the folder into
base-<key>/. A Stop kills `create` and deletes the folder. A crash or an app exit
leaves a .building-* folder that nothing reads and the next build deletes; the
`create` process itself is tied to the backend (core.child_procs) and dies with
it. A base-<key>/ without a matching record is deleted and rebuilt.

The lock is held while a base is checked, built or copied, so a second test that
starts during a build waits for it, and a base is never deleted while it is
being copied.

Copies are real copies (CopyFile2, through shutil.copy2), never hard links: a
test writes into its project (import-costume, the DAS loader, main.dol), and
through a hard link those writes would land in the base.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import file_retry
from core import file_lock
from core.child_procs import own
from core.config import get_subprocess_args
from core.hashing import sha256_bytes, sha256_file
from mexcli.commands import parse_json
from mexcli.project import MexExportCancelled

logger = logging.getLogger(__name__)

FORMAT = 1                          # bump when what a base must contain changes
PROJECT_NAME = 'NucleusTest'
RECORD = '.nucleus-pristine.json'
# The m-ex project of the 1.02 ISO is about this big (first_run_setup uses the
# same figure); the folder's size is how far `create` has got.
EXPECTED_BYTES = 1_400_000_000
EXPECTED_SECONDS = 180              # `create` on a hard disk
CREATE_TIMEOUT_SECONDS = 30 * 60
STOP_GRACE_SECONDS = 5
BUILD_MESSAGE = 'Preparing the test base from your Melee ISO (one time, about 3 minutes)…'
CLEAN_MESSAGE = 'Removing an old test base…'
# Files beside the MexCLI executable that decide what `create` writes: its code,
# the file library, and the m-ex codes it installs (codes.gct, and the optional
# codes.ini / the shipped seed_codes.ini).
MEXCLI_FILES = ('mexcli.dll', 'mexLib.dll', 'HSDRaw.dll', 'codes.gct', 'codes.ini', 'seed_codes.ini')
_SAMPLE = 1 << 20                   # bytes hashed from each end of the ISO


class BuildStopped(MexExportCancelled):
    """Stop arrived while the test project was being prepared."""


def iso_identity(iso):
    """Size, mtime and a hash of the first and last MiB: tells two ISOs apart
    without reading 1.3 GB."""
    iso = Path(iso)
    st = iso.stat()
    with open(iso, 'rb') as stream:
        sample = stream.read(_SAMPLE)
        if st.st_size > _SAMPLE:
            stream.seek(max(_SAMPLE, st.st_size - _SAMPLE))
            sample += stream.read(_SAMPLE)
    return {'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'sample_sha256': sha256_bytes(sample)}


def mexcli_identity(mexcli):
    """One hash over the MexCLI executable and the MEXCLI_FILES beside it."""
    exe = Path(mexcli)
    parts = [f'{path.name}:{sha256_file(path)}'
             for path in [exe, *(exe.parent / name for name in MEXCLI_FILES)] if path.is_file()]
    return sha256_bytes('\n'.join(parts).encode('utf-8'))


def base_key(iso, mexcli):
    """(key, identity) of the base for this ISO and MexCLI."""
    identity = {'format': FORMAT, 'name': PROJECT_NAME,
                'iso': iso_identity(iso), 'mexcli': mexcli_identity(mexcli)}
    return sha256_bytes(json.dumps(identity, sort_keys=True).encode('utf-8'))[:16], identity


def copy_fresh_project(iso, dest, *, root, mexcli, progress=None, should_stop=None, log=None):
    """Copy the pristine base for `iso` into `dest` (which must not exist yet),
    building the base first when there is none for this ISO and MexCLI.

    progress(step, fraction, message) is called with step 'wait' (another build
    or copy holds the base), 'clean' (deleting an old base or leftovers), 'base'
    (building it, about once a second) or 'copy'. log(message) gets one line
    when a build starts and one when it ends. Raises BuildStopped once
    should_stop() is true. On any failure `dest` is removed and no half-built
    base is left for a later test. Returns the base.

    A base whose files no longer match what its record counted when it was
    built (a file deleted or truncated by hand, a disk error) is discarded and
    built again.
    """
    progress = progress or (lambda *_args: None)
    log = log or (lambda _message: None)
    root, dest = Path(root), Path(dest)
    if dest.exists():
        raise FileExistsError(f'test project folder already exists: {dest}')
    key, identity = base_key(iso, mexcli)
    try:
        with _locked(root, should_stop, progress):
            base, listing = _ready(root, key), None
            if base is not None:
                listing = _intact_listing(base)
                if listing is None:
                    logger.warning('pristine test base %s is damaged; rebuilding it', base.name)
                    base = None
            if base is None:
                base, listing = _build(root, iso, mexcli, key, identity, progress, should_stop, log)
            _clear(root, progress, keep=base)
            _copy(base, dest, listing, progress, should_stop)
    except BaseException:
        _remove(dest)
        raise
    return base


@contextmanager
def ready_base(iso, *, root, mexcli, wait=0.5):
    """The finished base for `iso` and `mexcli`, for reading only, or None.

    Never builds. The lock is held for the block, so the base cannot be deleted
    or rebuilt while it is read; when a build or copy holds the lock past
    `wait` seconds the answer is None. Nothing may be written into the base."""
    root = Path(root)
    if not root.is_dir():
        yield None
        return
    key, _identity = base_key(iso, mexcli)
    lock = file_lock.exclusive(root, timeout=wait)
    try:
        lock.__enter__()
    except file_lock.LockBusy:
        yield None
        return
    try:
        yield _ready(root, key)
    finally:
        lock.__exit__(None, None, None)


def _check(should_stop):
    if should_stop is not None and should_stop():
        raise BuildStopped('Test stopped while the test project was being prepared.')


@contextmanager
def _locked(root, should_stop, progress):
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    while True:
        _check(should_stop)
        lock = file_lock.exclusive(root, timeout=0.5)
        try:
            lock.__enter__()
            break
        except file_lock.LockBusy:
            waited = int(time.monotonic() - started)
            progress('wait', 0.0, f'Waiting for another test build to finish preparing… {waited}s')
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _ready(root, key):
    """base-<key>/ when it is complete and is the base for `key`, else None."""
    base = root / f'base-{key}'
    try:
        record = json.loads((base / RECORD).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get('key') != key:
        return None
    return base if (base / 'project.mexproj').is_file() else None


def _listing(base):
    """(folders, [(relative path, size)]) of a base, its record left out.
    Raises OSError when any folder cannot be listed, rather than skipping it."""
    def fail(error):
        raise error

    folders, files = [], []
    for current, _subfolders, names in os.walk(base, onerror=fail):
        rel = Path(current).relative_to(base)
        folders.append(rel)
        for name in names:
            if rel == Path('.') and name == RECORD:
                continue
            files.append((rel / name, (Path(current) / name).stat().st_size))
    return folders, files


def _intact_listing(base):
    """The base's listing when it still has exactly the files and bytes its
    record counted at build time, else None."""
    try:
        record = json.loads((base / RECORD).read_text(encoding='utf-8'))
        listing = _listing(base)
    except (OSError, ValueError):
        return None
    files = listing[1]
    if record.get('files') != len(files) or record.get('bytes') != sum(size for _rel, size in files):
        return None
    return listing


def _to_trash(path):
    """Move a folder out of the way in one rename (the next _clear deletes it);
    delete it in place when the rename is refused."""
    try:
        os.rename(path, path.parent / f'.trash-{uuid.uuid4().hex[:12]}')
    except OSError:
        _remove(path)


def _remove(path):
    """Delete a file or folder; best effort (a locked leftover is never read)."""
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            pass


def _clear(root, progress, keep=None):
    """Delete everything under the root but `keep`: old bases, interrupted
    builds, trash. Only called under the lock, so none of it is in use.

    A base is first renamed to .trash-<id>, so a delete that stops half way
    leaves nothing that looks like a base. If the rename fails its record goes
    first, which makes it unusable for the same reason.
    """
    entries = [entry for entry in root.iterdir() if keep is None or entry != keep]
    if entries:
        progress('clean', 0.0, CLEAN_MESSAGE)    # deleting 1.4 GB can take a while
    for entry in entries:
        if entry.is_dir() and entry.name.startswith('base-'):
            trash = root / f'.trash-{uuid.uuid4().hex[:12]}'
            try:
                os.rename(entry, trash)
                entry = trash
            except OSError:
                _remove(entry / RECORD)
        _remove(entry)


def _build(root, iso, mexcli, key, identity, progress, should_stop, log):
    """Build base-<key>/ from scratch; returns (base, its listing)."""
    _clear(root, progress)
    base = root / f'base-{key}'
    if base.exists():
        # Checked before the long `create`, which could never be renamed into place.
        raise RuntimeError(
            'An old test base could not be removed (another program may have a file in it open): '
            f'{base}. Close that program or delete the folder, then start the test again.')
    work = root / f'.building-{uuid.uuid4().hex[:12]}'
    log(BUILD_MESSAGE)
    progress('base', 0.0, f'{BUILD_MESSAGE} 0s')
    started = time.monotonic()
    try:
        _run_create(mexcli, iso, work, progress, should_stop, started)
        if not (work / 'project.mexproj').is_file():
            raise RuntimeError('mexcli create did not produce a project.mexproj')
        listing = _listing(work)
        files = listing[1]
        seconds = round(time.monotonic() - started)
        record = {**identity, 'key': key, 'seconds': seconds,
                  'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
                  'files': len(files), 'bytes': sum(size for _rel, size in files)}
        (work / RECORD).write_text(json.dumps(record, indent=2), encoding='utf-8')
        # A scanner opening the files just written can briefly refuse the rename.
        file_retry.retry_locked(os.rename, work, base, timeout=30.0)
    except BuildStopped:
        _to_trash(work)                 # one rename, so a Stop frees the slot at once
        raise
    except BaseException:
        _remove(work)
        raise
    logger.info('pristine test base %s built from %s in %ss', base.name, iso, seconds)
    log(f'Test base ready ({seconds}s); later tests reuse it.')
    return base, listing


def _create_command(mexcli, iso, out_dir):
    return [str(mexcli), 'create', str(iso), str(out_dir), PROJECT_NAME]


def _spawn(argv, cwd):
    """Start `create`, tied to this process so an app exit cannot orphan it."""
    return own(subprocess.Popen(
        argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
        **get_subprocess_args()))


def _end(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=STOP_GRACE_SECONDS)


def _folder_bytes(folder):
    total = 0
    stack = [folder]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _run_create(mexcli, iso, work, progress, should_stop, started):
    argv = _create_command(mexcli, iso, work)
    logger.info('mexcli create (pristine test base): %s', argv)
    proc = _spawn(argv, work.parent)
    output = []
    reader = threading.Thread(target=lambda: output.extend(proc.stdout), daemon=True)
    reader.start()
    shown = 0                       # _build already showed 0s
    try:
        while True:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                pass
            _check(should_stop)
            elapsed = time.monotonic() - started
            if elapsed > CREATE_TIMEOUT_SECONDS:
                raise RuntimeError(f'mexcli create did not finish in {CREATE_TIMEOUT_SECONDS // 60} minutes')
            if int(elapsed) != shown:
                shown = int(elapsed)
                # Half measured, half time: bytes written show the ISO being
                # extracted, and time keeps the bar moving through m-ex's
                # install and save after it, when the folder stops growing.
                fraction = (0.5 * min(1.0, _folder_bytes(work) / EXPECTED_BYTES)
                            + 0.47 * min(1.0, elapsed / EXPECTED_SECONDS))
                progress('base', fraction, f'{BUILD_MESSAGE} {shown}s')
    except BaseException:
        _end(proc)
        raise
    finally:
        reader.join(timeout=STOP_GRACE_SECONDS)
    text = ''.join(output)
    result = parse_json(text)
    # MexCLI can also report a failure in its final JSON while exiting 0.
    if proc.returncode != 0 or result.get('success') is False:
        raise RuntimeError('mexcli create failed: ' + (result.get('error') or text.strip()[-500:]
                                                       or f'exit code {proc.returncode}'))


def _copy(base, dest, listing, progress, should_stop):
    """Copy a base's listing (_listing) into dest."""
    folders, files = listing
    total = sum(size for _rel, size in files)
    dest.mkdir(parents=True)
    for rel in folders[1:]:
        (dest / rel).mkdir(parents=True, exist_ok=True)
    done, shown = 0, 0.0
    progress('copy', 0.0, 'Copying the test base… 0%')
    for rel, size in files:
        _check(should_stop)
        shutil.copy2(base / rel, dest / rel)
        done += size
        now = time.monotonic()
        if now - shown >= 0.25:
            shown = now
            fraction = done / total if total else 1.0
            progress('copy', fraction, f'Copying the test base… {int(fraction * 100)}%')
    progress('copy', 1.0, 'Copying the test base… 100%')
