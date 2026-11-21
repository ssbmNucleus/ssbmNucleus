"""Offline, copy-only data-root relocation worker (no application imports).

Run before starting any backend or user-data writer. The Electron owner holds
the launch lock, supplies a dedicated data root, and selects the verified stage
only after this process succeeds. This worker never removes source or stage,
changes bootstrap settings, starts the app, or prints account/database values.
"""
import argparse
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import time
import uuid

from storage_data_lock import LOCK_FILENAME, acquire_data_root_lock


SQLITE_HEADER = b'SQLite format 3\0'
DB_SUFFIXES = {'.db', '.sqlite', '.sqlite3'}
SCRATCH_NAME = 'scratch'
# Regenerable trees that are not moved: the model import tools are a download the app can repeat (Settings), and on
# macOS and Linux they hold symlinks, which this worker refuses. The new root simply has none until downloaded again.
REGENERABLE = {('tools', 'model-import')}
CHUNK_SIZE = 4 * 1024 * 1024
LOCK_TIMEOUT = 0.25


class RelocationError(RuntimeError):
    pass


def _emit(event):
    print(json.dumps(event, ensure_ascii=True), flush=True)


def _no_links(path):
    """Check the path AND existing parents; Windows junctions are reparse points."""
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise RelocationError('Symbolic links and reparse points are not supported.')


def _absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise RelocationError('Source, stage, and target must be absolute paths.')
    # Validate before resolving: resolving first would hide a junction.
    _no_links(path)
    return path.resolve()


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, stat.S_IFMT(info.st_mode))


def _inventory(root):
    files, directories = {}, set()

    def walk(folder):
        _no_links(folder)
        for child in sorted(folder.iterdir()):
            _no_links(child)
            rel = child.relative_to(root)
            if rel.parts == (LOCK_FILENAME,):
                continue
            if rel.parts == (SCRATCH_NAME,):
                if not child.is_dir():
                    raise RelocationError('The application scratch path is not a directory.')
                continue
            if rel.parts in REGENERABLE:
                continue
            info = child.lstat()
            if stat.S_ISDIR(info.st_mode):
                directories.add(rel)
                walk(child)
            elif stat.S_ISREG(info.st_mode):
                files[rel] = _fingerprint(info)
            else:
                raise RelocationError('The data root contains an unsupported special file.')
    walk(root)
    return files, directories


def _databases(source, files):
    result = set()
    for rel in sorted(files):
        # A Windows SQLite writer locks portions of SHM against ordinary reads.
        # The base path sorts before its companions; SQLite reads these itself.
        if rel in _companions(result):
            continue
        path = source / rel
        with path.open('rb') as stream:
            header = stream.read(16)
        if header == SQLITE_HEADER:
            result.add(rel)
        elif path.suffix.lower() in DB_SUFFIXES:
            raise RelocationError('A database has an invalid SQLite header; repair it before moving.')
    return result


def _companions(databases):
    return {Path(str(rel) + suffix) for rel in databases
            for suffix in ('-wal', '-shm', '-journal')}


def _digest(path):
    _no_links(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK_SIZE), b''):
            digest.update(block)
    return digest.hexdigest()


def _copy_file(source, destination, progress):
    _no_links(source)
    _no_links(destination.parent)
    digest = hashlib.sha256()
    with source.open('rb') as reader, destination.open('xb') as writer:
        for block in iter(lambda: reader.read(CHUNK_SIZE), b''):
            writer.write(block)
            digest.update(block)
            progress(len(block))
        writer.flush()
        os.fsync(writer.fileno())
    shutil.copystat(source, destination, follow_symlinks=False)
    if _digest(destination) != digest.hexdigest():
        raise RelocationError('Copied file verification failed.')
    return digest.hexdigest()


def _integrity(connection):
    if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise RelocationError('SQLite integrity verification failed.')
    if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise RelocationError('SQLite foreign-key verification failed.')


def _snapshot(source, destination, progress):
    # A different source connection owns BEGIN IMMEDIATE throughout relocation.
    # Reading the committed snapshot on this connection also includes WAL data.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True,
                                timeout=LOCK_TIMEOUT)) as reader:
        with closing(sqlite3.connect(str(destination))) as writer:
            # Backup inherits the source's WAL header. Its first integrity read
            # can therefore create WAL/SHM before conversion to DELETE. Apple's
            # system SQLite can leave SHM behind even after a successful mode
            # switch and close. This destination is private to the worker: use
            # SQLite's exclusive mode so its WAL index stays in memory instead.
            if writer.execute('PRAGMA locking_mode=EXCLUSIVE').fetchone() != ('exclusive',):
                raise RelocationError('Cannot exclusively prepare the database snapshot.')
            reader.backup(writer, pages=1024,
                          progress=lambda *_: progress(0), sleep=0.01)
            _integrity(writer)
            if writer.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',):
                raise RelocationError('Cannot convert the database snapshot to standalone mode.')
            writer.commit()
    # Never unlink journals manually: any unexpected companion fails closed,
    # retaining the source and stage for recovery instead of risking lost WAL.
    if any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise RelocationError('Database snapshot still has journal files; relocation was not activated.')
    with destination.open('r+b') as stream:
        os.fsync(stream.fileno())


def _rebaser(source, stage, target, files, directories):
    copied = set(files) | directories | {Path('.')}

    def rebase(value):
        if not isinstance(value, str) or not Path(value).is_absolute():
            return value
        # Lexical exact path containment, followed by checked inventory membership.
        # No substring replacement, URLs, relative paths, absent files or scratch.
        path = Path(os.path.normpath(value))
        try:
            rel = path.relative_to(source)
        except ValueError:
            return value
        if rel not in copied or not (stage / rel).exists():
            return value
        return str(target / rel)
    return rebase


def _rewrite_json(path, fields, rebase, *, texture_mapping=False):
    # These are settings, not arbitrary imported JSON, metadata or chat messages.
    before = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(before, dict):
        raise RelocationError('A path settings file is malformed.')
    after = dict(before)
    for field in fields:
        if field in after:
            after[field] = rebase(after[field])
    if texture_mapping:
        costumes = before.get('costumes')
        if not isinstance(costumes, list) or any(not isinstance(item, dict) for item in costumes):
            raise RelocationError('An output texture mapping file is malformed.')
        after['costumes'] = [dict(item) for item in costumes]
        for item in after['costumes']:
            for field in ('real_csp_path', 'hd_csp_path'):
                if field in item:
                    item[field] = rebase(item[field])
    if after != before:
        with path.open('w', encoding='utf-8') as stream:
            # Historical consumers may open these files in the Windows locale.
            json.dump(after, stream, ensure_ascii=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())


# The stored settings that hold an absolute path on this computer, which a move rewrites. A Vault backup never
# carries them and a restore never takes them from one (tests/backend/test_vault_backup_local_state.py checks
# vault_backup and tracker/store/backup.py against these lists).
PATH_SETTINGS_FILES = (
    ('storage/vanilla_iso.json', ('path',)),
    ('storage/ai_studio.json', ('hfCacheDir',)),
)
TRACKER_PATH_TABLES = ('games', 'vault_hashes')             # their ``path`` column
TRACKER_PATH_KEYS = ('recording_dir', 'replay_root_override')   # kv values


def _rewrite_references(source, stage, target, files, directories, databases):
    rebase = _rebaser(source, stage, target, files, directories)
    for name, fields in PATH_SETTINGS_FILES:
        path = stage / name
        if path.is_file():
            _rewrite_json(path, fields, rebase)
    for rel in files:
        if len(rel.parts) == 2 and rel.parts[0] == 'output' and rel.name.endswith('_texture_mapping.json'):
            _rewrite_json(stage / rel, (), rebase, texture_mapping=True)

    replay_db = Path('storage/nucleome.db')
    if replay_db not in databases:
        return
    with closing(sqlite3.connect(str(stage / replay_db))) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        with connection:
            for table in TRACKER_PATH_TABLES:
                if table not in tables:
                    continue
                # Column/table names are a fixed schema allowlist, never user input.
                for (value,) in connection.execute(f'SELECT path FROM {table}').fetchall():
                    updated = rebase(value)
                    if updated != value:
                        connection.execute(f'UPDATE {table} SET path=? WHERE path=?',
                                           (updated, value))
            if 'kv' in tables:
                for key in TRACKER_PATH_KEYS:
                    row = connection.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
                    if row is None:
                        continue
                    value = json.loads(row[0])
                    updated = rebase(value)
                    if updated != value:
                        connection.execute('UPDATE kv SET value=? WHERE key=?',
                                           (json.dumps(updated), key))
        _integrity(connection)


def _preflight(source, stage, target):
    if any(_overlap(a, b) for a, b in ((source, stage), (source, target), (stage, target))):
        raise RelocationError('Source, stage, and target must not overlap.')
    if source == Path(source.anchor) or target == Path(target.anchor):
        raise RelocationError('A drive root cannot be used as a data folder.')
    if not source.is_dir():
        raise RelocationError('The current data drive or folder is unavailable.')
    # Fail closed if a direct caller accidentally supplies this source checkout.
    if any((source / marker).exists() for marker in ('.git', 'backend', 'frontend', 'package.json')):
        raise RelocationError('Moving a development/source checkout is not supported.')
    if stage.exists() or not stage.parent.is_dir() or not target.parent.is_dir():
        raise RelocationError('Stage must be new and destination parent folders must exist.')
    if target.exists() and (not target.is_dir() or next(target.iterdir(), None) is not None):
        raise RelocationError('The destination must be absent or empty.')
    if stage.parent.stat().st_dev != target.parent.stat().st_dev:
        raise RelocationError('Staging and final destination must be on the same filesystem.')


def relocate(source, stage, target, *, emit=_emit, await_activation=None):
    """Copy and verify into a NEW stage, returning counts; never activate it."""
    source, stage, target = map(_absolute, (source, stage, target))
    _preflight(source, stage, target)
    with acquire_data_root_lock(source):
        return _relocate_locked(source, stage, target, emit, await_activation)


def _relocate_locked(source, stage, target, emit, await_activation):
    emit({'phase': 'inventory'})
    initial_files, directories = _inventory(source)
    databases = _databases(source, initial_files)
    companions = _companions(databases)
    files = {rel: info for rel, info in initial_files.items() if rel not in companions}
    total = sum(info[2] for rel, info in initial_files.items() if rel not in companions)
    # WAL pages can be newer/larger than the main database. Include them in the
    # estimate plus reserve for settings serialization and filesystem metadata.
    total += sum(info[2] for rel, info in initial_files.items() if rel in companions)
    required = total + max(16 * 1024 * 1024, total // 20)
    if shutil.disk_usage(stage.parent).free < required:
        raise RelocationError('The destination does not have enough free space.')
    probe = stage.parent / ('.nucleus-write-probe-' + uuid.uuid4().hex)
    try:
        with probe.open('xb') as stream:
            stream.write(b'Nucleus relocation writability check\n')
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        # Only this exact, uniquely named file is removed; no recursive cleanup.
        if probe.exists():
            probe.unlink()

    copied_bytes = 0
    last_progress = 0.0

    def progress(count):
        nonlocal copied_bytes, last_progress
        copied_bytes += count
        now = time.monotonic()
        if now - last_progress >= 0.2:
            emit({'phase': 'copying', 'bytes': copied_bytes, 'totalBytes': total})
            last_progress = now

    with ExitStack() as stack:
        # Acquire every database writer lock before creating the stage. This
        # rejects active writers with a short timeout; never copies a live WAL
        # as an ordinary file. Caller must still prevent backend/native startup.
        for rel in sorted(databases):
            connection = sqlite3.connect((source / rel).as_uri() + '?mode=rw',
                                         uri=True, timeout=LOCK_TIMEOUT)
            stack.callback(connection.close)
            connection.execute('BEGIN IMMEDIATE')
            stack.callback(connection.rollback)
            _integrity(connection)

        _no_links(stage.parent)
        stage.mkdir()
        for rel in sorted(directories, key=lambda p: (len(p.parts), str(p))):
            (stage / rel).mkdir()
        (stage / SCRATCH_NAME).mkdir()
        digests = {}
        for rel in sorted(files):
            if rel in databases:
                emit({'phase': 'snapshotting', 'files': len(digests)})
                _snapshot(source / rel, stage / rel, progress)
                progress((stage / rel).stat().st_size)
            else:
                if _fingerprint((source / rel).lstat()) != files[rel]:
                    raise RelocationError('Source data changed during relocation; close other tools and retry.')
                digests[rel] = _copy_file(source / rel, stage / rel, progress)

        emit({'phase': 'verifying', 'bytes': copied_bytes})
        # Check every copied byte against the current source, including files
        # whose size/mtime were deliberately restored by a concurrent writer.
        for rel, digest in digests.items():
            if (_fingerprint((source / rel).lstat()) != files[rel]
                    or _digest(source / rel) != digest):
                raise RelocationError('Source data changed during relocation; close other tools and retry.')
            progress(0)
        current_files, current_directories = _inventory(source)
        current_files = {rel: info for rel, info in current_files.items() if rel not in companions}
        if (set(current_files) != set(files) or current_directories != directories
                or any(current_files[rel] != files[rel] for rel in files if rel not in databases)
                or any(current_files[rel][:2] != files[rel][:2] for rel in databases)):
            raise RelocationError('The source inventory changed during relocation.')

        _rewrite_references(source, stage, target, files, directories, databases)
        # Verify DBs once more after path updates; identity/history never rebuilt.
        for rel in databases:
            with closing(sqlite3.connect((stage / rel).as_uri() + '?mode=ro', uri=True)) as connection:
                _integrity(connection)
        _no_links(stage)
        _no_links(target)
        if target.exists() and next(target.iterdir(), None) is not None:
            raise RelocationError('The destination changed during relocation.')

        result = {'phase': 'verified', 'files': len(files), 'bytes': copied_bytes}
        emit(result)
        # The Electron owner must publish the verified stage and bootstrap while
        # BOTH the source-root lease and SQLite writer locks remain held. An EOF
        # (e.g. owner interruption) aborts without selecting/deleting any data.
        if await_activation is not None:
            await_activation()
    return result


def _await_activation():
    if sys.stdin.readline().strip() != 'activate':
        raise RelocationError('Relocation was not activated; the original data and staged copy are preserved.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--await-activation', action='store_true',
                        help='Hold all source locks after verified until stdin activate or abort/EOF.')
    args = parser.parse_args(argv)
    try:
        relocate(args.source, args.stage, args.target,
                 await_activation=_await_activation if args.await_activation else None)
        return 0
    except Exception as exc:
        # Do not include persisted values or database contents in diagnostics.
        message = str(exc) if isinstance(exc, RelocationError) else {
            'OperationalError': 'SQLite is busy or unavailable. Close other tools and retry.',
            'DatabaseError': 'A SQLite database failed verification.',
            'PermissionError': 'A storage folder is not writable or readable.',
            'FileNotFoundError': 'A storage drive or file became unavailable.',
            'DataRootBusyError': 'The current data folder is in use. Close other Nucleus tools and retry.',
        }.get(type(exc).__name__, 'Relocation failed; the original data has been preserved.')
        _emit({'phase': 'error', 'error': message, 'errorType': type(exc).__name__})
        return 1


if __name__ == '__main__':
    sys.exit(main())
