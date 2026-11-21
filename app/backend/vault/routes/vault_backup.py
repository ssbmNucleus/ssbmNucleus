"""
Vault Backup Blueprint - Backup and restore operations.

Handles creating backups of the storage vault and restoring from backups.
"""

import copy
import json
import uuid
import shutil
import sqlite3
import zipfile
import tempfile
import time
import logging
from contextlib import closing
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify

import file_retry
from core.config import PROJECT_ROOT, STORAGE_PATH, PROJECTS_PATH, LOGS_PATH
from core import jobs, storage_handles
from core.metadata import metadata_lock, load_metadata, save_metadata
from core.safe_archive import safe_extract_zip
from core.path_safety import portable_path_parts, resolve_under_root, validate_path_segment
from core.temporary_download import send_temporary_zip
from tracker.store import backup as tracker_backup

logger = logging.getLogger(__name__)

vault_backup_bp = Blueprint('vault_backup', __name__)

RESTORE_KIND = 'vault_restore'


def _clean_restore(name, value):
    """Undo what a restore still owned when it ended or Nucleus died (core/jobs.py).

    ``previous`` is the current Vault moved aside for a replace; it is owned only
    between that move and the new Vault going live, so finding it with no Vault
    in place means the restore never finished: put it back.
    """
    if name == 'previous':
        previous, vault = Path(value['path']), Path(value['vault'])
        if previous.exists() and not vault.exists():
            previous.rename(vault)
            return 'Your vault was put back.'
        return None
    path = Path(value)
    if name == 'staging' and path.name.startswith('.vault-restore-') and path.exists():
        shutil.rmtree(path)
    elif name == 'extract' and path.name.startswith('nucleus-restore-') and path.exists():
        shutil.rmtree(path)
    elif name == 'upload':
        path.unlink(missing_ok=True)
    return None


jobs.register_kind(RESTORE_KIND, label='Vault restore', cleanup=_clean_restore)


def _extract_zip_with_progress(zipf, dest, job, lo, hi,
                               skip=(), phase='Extracting files'):
    """Extract every member of an open ZipFile into ``dest``, reporting the
    job's progress mapped onto the [lo, hi] percent band. Members in ``skip``
    (posix relative paths) are not written."""
    last_pct = -1
    def on_progress(i, total, _member):
        nonlocal last_pct
        pct = lo + int((i / total) * (hi - lo))
        # Throttle: only emit when the integer percent advances.
        if pct != last_pct and job is not None:
            last_pct = pct
            job.progress(pct / 100, f'{phase}… ({i}/{total})')
    safe_extract_zip(zipf, dest, skip=skip, progress=on_progress)


# vault.db (+ WAL sidecars) is a rebuildable local cache of metadata.json, not a
# portable artifact — and copying a live WAL DB can capture an inconsistent
# state. Backups exclude it; restores rebuild it from the restored metadata.json
# (generated from the authoritative catalog). See docs/dev/VAULT_SQLITE_MIGRATION.md.
_DB_ARTIFACTS = {'vault.db', 'vault.db-wal', 'vault.db-shm'}

# Every other SQLite database in the Vault (Randall's chats.db, the task journal tasks.db, chat_reports'
# submissions.db) is live while the app runs: copied file by file it is half a transaction, and its -wal/-shm/-journal
# companions belong to that one file only. A backup carries a consistent snapshot of each (:func:`_sqlite_snapshot`)
# and never a companion. storage_relocation.py tells databases and companions apart the same way.
_SQLITE_HEADER = b'SQLite format 3\x00'
_SQLITE_COMPANIONS = ('-wal', '-shm', '-journal')
_SQLITE_SUFFIXES = ('.db', '.sqlite', '.sqlite3')
_LIVE_DATABASE = 'sqlite'   # a database's identity in _backup_files: its bytes may change, it may not go away


def _is_sqlite(path):
    try:
        with open(path, 'rb') as stream:
            return stream.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def _companion_database(path):
    """The database a -wal/-shm/-journal file belongs to (a SQLite file beside it, or a database name whose file is
    gone), or None for any other file. Decided by the name and the database's header, never by reading the
    companion: a Windows writer locks parts of -shm."""
    path = Path(path)
    for suffix in _SQLITE_COMPANIONS:
        if path.name.lower().endswith(suffix) and len(path.name) > len(suffix):
            database = path.with_name(path.name[:-len(suffix)])
            return database if database.suffix.lower() in _SQLITE_SUFFIXES or _is_sqlite(database) else None
    return None


def _sqlite_snapshot(source, workdir):
    """A consistent copy of a live database for a backup, in ``workdir``: SQLite's backup API reads one committed
    state, its WAL included, without writing the live file. The copy is a single file with no journal."""
    target = Path(workdir) / f'{uuid.uuid4().hex}.db'
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as reader, \
            closing(sqlite3.connect(str(target))) as writer:
        # The copy inherits WAL mode from its source; exclusive locking keeps that WAL's index in memory, so the
        # switch to a single file leaves nothing beside it (storage_relocation._snapshot does the same).
        writer.execute('PRAGMA locking_mode=EXCLUSIVE')
        reader.backup(writer)
        if (writer.execute('PRAGMA journal_mode=DELETE').fetchone() or [''])[0].lower() != 'delete':
            raise RuntimeError('the copy could not be made a single file')
    if any(Path(str(target) + suffix).exists() for suffix in _SQLITE_COMPANIONS):
        raise RuntimeError('the copy still has journal files')
    return target


def _settle_sqlite_journals(root):
    """A backup made before 0.9.0 holds live databases as raw files with their companions. Open each such database
    in the extracted tree once, so SQLite takes in its WAL (or rolls back a hot journal) and leaves one file, then
    remove every companion: published beside another copy of that database, one would be replayed into it."""
    companions = {path: _companion_database(path) for path in Path(root).rglob('*') if path.is_file()}
    companions = {path: database for path, database in companions.items() if database is not None}
    for database in sorted(set(companions.values())):
        if not _is_sqlite(database):
            continue
        try:
            with closing(sqlite3.connect(str(database), timeout=30)) as conn:
                # It came in a backup, perhaps a crafted one: SQLite's defensive settings, as tracker/store/backup.py.
                if hasattr(sqlite3, 'SQLITE_DBCONFIG_DEFENSIVE'):
                    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
                conn.execute('PRAGMA trusted_schema=OFF')
                conn.execute('SELECT count(*) FROM sqlite_master').fetchone()
                conn.execute('PRAGMA journal_mode=DELETE').fetchone()
        except sqlite3.Error:
            logger.warning("Could not take in the journal of the backup's %s; it is restored without it",
                           database.name, exc_info=True)
    for path in companions:
        path.unlink(missing_ok=True)


# This computer's own setup: files that name programs and folders on this PC. They mean nothing on another one,
# and from a crafted backup they named a program to run or a stranger's server to open (a network path hands
# it this computer's Windows sign-in). storage_relocation.PATH_SETTINGS_FILES lists the path settings a data
# move rewrites; every one of them is here.
_LOCAL_FILES = (
    ('assistant', 'mcp.json'),        # the creation toolkit folder the app runs a Python from
    ('assistant', 'settings.json'),   # "My game": this PC's project, game copies, Slippi Launcher or Dolphin
    ('vanilla_iso.json',),            # where this PC's clean Melee ISO is
    ('ai_studio.json',),              # an older version's model cache folder
)
# And whole folders of it: delivery receipts (randall/delivery/deliver_receipts.py) record this PC's project and
# game copy paths, and undoing a delivery writes the game back there. Another PC's receipts are wrong here, and a
# crafted one aimed the undo at a path of its choosing.
# Watch Lite's animation zips are this computer's downloads (tracker/video/anim_fetch.py, clip_render.user_zips_dir):
# about 90 MB, most of a 0.9.0 backup, that the app fetches again whenever they are missing (first-run setup and every
# start, tracker/routes/lite.py). A backup leaves them out and a replace keeps this computer's.
_LOCAL_FOLDERS = (
    ('assistant', 'deliveries'),
    ('nucleome', 'anim_zips'),
)


def _local_only(relative):
    """True for the files of this computer's own account and setup state, which never leave in a backup as they are
    and are never written from one (security review 11-19, M2): ``nucleome.db*`` (the Tracker store, whose kv holds
    the sign-ins and folder settings: a backup carries a sanitized copy instead, see :func:`_tracker_snapshot` and
    :func:`_incoming_tracker_store`), :data:`_LOCAL_FILES` and everything in :data:`_LOCAL_FOLDERS`. A shared
    backup handed over the account; a crafted one swapped it, planted a program to run or pointed the app at another
    computer's folders. The downloads in :data:`_LOCAL_FOLDERS` are left out for their size: the app fetches them
    again."""
    parts = tuple(part.lower() for part in str(relative).replace('\\', '/').split('/') if part not in ('', '.'))
    if len(parts) == 1 and parts[0].startswith('nucleome.db'):
        return True
    return parts in _LOCAL_FILES or any(parts[:len(folder)] == folder for folder in _LOCAL_FOLDERS)


def _local_only_members(zipf):
    """The members of an open backup ZIP that restore never writes (:func:`_local_only`), by raw name."""
    return {info.filename for info in zipf.infolist() if _local_only(info.filename)}


def _carry_local_state(previous, destination, tracker_store=True):
    """A replace restore swaps the whole Vault folder: move this computer's own state (:func:`_local_only`) from
    the Vault moved aside into the restored one, so the restore keeps the account and setup it had. With
    ``tracker_store`` False the backup brought Tracker data: the restored Vault has its own store, already holding
    this computer's sign-in (:func:`_carry_sign_in`), and this computer's old store stays in the Vault moved aside."""
    moves = ([path for path in previous.iterdir() if path.is_file() and path.name.lower().startswith('nucleome.db')]
             if tracker_store else [])
    moves += [previous.joinpath(*parts) for parts in _LOCAL_FILES if previous.joinpath(*parts).is_file()]
    moves += [previous.joinpath(*parts) for parts in _LOCAL_FOLDERS if previous.joinpath(*parts).is_dir()]
    for source in moves:
        target = destination / source.relative_to(previous)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Never one from the backup: restore skipped those. A folder left there can only be empty.
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink(missing_ok=True)
            source.rename(target)
        except OSError:
            logger.warning('Could not carry %s into the restored Vault; it stays in %s', source.name, previous,
                           exc_info=True)


# The Tracker store as a backup holds it: one sanitized SQLite file. An old (0.8.x) backup also holds the WAL that
# belongs to it. Any other nucleome.db* member is ignored.
_TRACKER_MEMBERS = ('nucleome.db', 'nucleome.db-wal')


def _tracker_snapshot(workdir):
    """The Tracker store for a backup: a sanitized copy in ``workdir`` (tracker.store.backup.snapshot), or None when
    this computer has none. A store that cannot be copied fails the backup: one without it would lose that data."""
    try:
        return tracker_backup.snapshot(STORAGE_PATH / tracker_backup.DB_NAME, workdir)
    except Exception as exc:
        raise RuntimeError(f'Could not back up the Tracker data ({tracker_backup.DB_NAME}): {exc}') from exc


def _incoming_tracker_store(zipf, workdir):
    """The backup's Tracker store, sanitized in ``workdir`` (tracker.store.backup.clean_incoming), or None when the
    backup has none. An old backup's raw store and its WAL go through the same sanitizing as a new one's."""
    members = {name for name in zipf.namelist() if name in _TRACKER_MEMBERS}
    if 'nucleome.db' not in members:
        return None
    safe_extract_zip(zipf, workdir, members=members)
    return tracker_backup.clean_incoming(Path(workdir) / 'nucleome.db')


def _stage_tracker_store(zip_path, staging, job):
    """Put the backup's Tracker data, sanitized, into the staged Vault. ``{'status': 'restored'}``, ``'none'``
    (the backup has none) or ``'unreadable'`` (left out). Without one, the replace keeps this computer's store.
    The job owns the scratch folder it reads the store in until that is gone."""
    workdir = Path(tempfile.mkdtemp(prefix='nucleus-restore-'))
    job.own('extract', str(workdir))
    try:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                incoming = _incoming_tracker_store(zipf, workdir)
        except tracker_backup.TrackerStoreError as exc:
            logger.warning("Vault restore leaves out the backup's Tracker data: %s", exc)
            return {'status': 'unreadable'}
        if incoming is None:
            return {'status': 'none'}
        shutil.copyfile(incoming, staging / tracker_backup.DB_NAME)
        return {'status': 'restored'}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if not workdir.exists():
            job.release('extract')


def _carry_sign_in(vault, staging):
    """This computer's sign-in, from its live Tracker store into the staged one (tracker.store.backup.carry_sign_in).
    If it cannot be read the restored store has none, never the backup's, and the old store keeps it in the Vault
    moved aside."""
    try:
        tracker_backup.carry_sign_in(vault / tracker_backup.DB_NAME, staging / tracker_backup.DB_NAME)
    except Exception:
        logger.warning('Could not carry the sign-in into the restored Tracker data; it stays in the previous Vault',
                       exc_info=True)


# The catalog fields that name a file inside the Vault. A delete or install joins them onto a Vault folder, so a
# restored catalog may only hold plain names there (``..`` or an absolute path deleted files outside the Vault).
_SKIN_FILE_FIELDS = ('filename', 'csp_filename', 'hd_csp_filename', 'stock_filename')
_VARIANT_FILE_FIELDS = ('filename', 'screenshot_filename')
_EXTRA_PATH_FIELDS = ('model_file', 'texture_file', 'screenshot')


def _read_vault_catalog():
    """Read the authoritative catalog; an absent DB can still be pre-migration."""
    from core import config, vault
    if getattr(config, 'VAULT_BACKEND', 'json') == 'db':
        blob = vault.load_blob()
        if blob is not None:
            return blob
    return load_metadata(default={}, path=STORAGE_PATH / 'metadata.json')


def _backup_files():
    """Capture file identities so uncoordinated asset writes invalidate a backup. This computer's own state
    (:func:`_local_only`) is left out, and so are SQLite companions; a database's identity is
    :data:`_LIVE_DATABASE`, since the app may write it while the backup takes its snapshot."""
    snapshot = {}
    if not STORAGE_PATH.exists():
        return snapshot
    root = STORAGE_PATH.resolve()
    for path in STORAGE_PATH.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Vault backup does not allow symlinks: {path.name}')
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError('Vault file escapes the storage directory') from exc
        if (relative in _DB_ARTIFACTS or relative == 'metadata.json' or _local_only(relative)
                or _companion_database(resolved) is not None):
            continue
        if _is_sqlite(resolved):
            snapshot[relative] = _LIVE_DATABASE
            continue
        stat = resolved.stat()
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
    return snapshot


def _validate_restore_catalog(root):
    """Reject unreadable catalogs before publishing any replacement files.

    Preserve unknown fields/older partial catalogs, but enforce the collection
    shapes used by the Vault. Asset-format validation belongs to each importer.
    """
    def records(value, label):
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            raise ValueError(f'Invalid backup catalog: {label} must be a list of objects')

    with (root / 'metadata.json').open(encoding='utf-8') as source:
        blob = json.load(source)
    if not isinstance(blob, dict):
        raise ValueError('Invalid backup catalog: metadata.json must be an object')
    for family, items_key in (('characters', 'skins'), ('stages', 'variants')):
        if family not in blob:
            continue
        if not isinstance(blob[family], dict):
            raise ValueError(f'Invalid backup catalog: {family} must be an object')
        for name, data in blob[family].items():
            if not isinstance(data, dict):
                raise ValueError(f'Invalid backup catalog: {family}.{name} must be an object')
            if items_key in data:
                records(data[items_key], f'{family}.{name}.{items_key}')
            if family == 'characters' and 'extras' in data:
                if not isinstance(data['extras'], dict):
                    raise ValueError(f'Invalid backup catalog: {name}.extras must be an object')
                for kind, entries in data['extras'].items():
                    records(entries, f'{name}.extras.{kind}')
    for family in ('xdelta', 'custom_characters', 'custom_stages', 'bundles'):
        if family in blob:
            records(blob[family], family)
    _validate_catalog_names(blob)
    for catalog in root.rglob('metadata.json'):
        if catalog != root / 'metadata.json':
            with catalog.open(encoding='utf-8') as source:
                json.load(source)
    return blob


def _validate_catalog_names(blob):
    """Every file and folder name a restored catalog gives goes through ``validate_path_segment`` (an extra's
    ``models/<id>.dat`` through ``portable_path_parts``): a crafted backup must not name a path outside the Vault."""
    def segment(value, label):
        if value is None or value == '':
            return
        try:
            validate_path_segment(value, field=label)
        except ValueError as exc:
            raise ValueError(f'Invalid backup catalog: {exc}') from None

    def relative(value, label):
        if value is None or value == '':
            return
        try:
            portable_path_parts(value, field=label)
        except ValueError as exc:
            raise ValueError(f'Invalid backup catalog: {exc}') from None

    for name, data in (blob.get('characters') or {}).items():
        segment(name, 'character name')
        for skin in data.get('skins') or []:
            if skin.get('type') != 'folder':
                segment(skin.get('id'), f'{name} skin id')
            for field in _SKIN_FILE_FIELDS:
                segment(skin.get(field), f'{name} skin {field}')
            for alternate in skin.get('alternate_csps') or []:
                if isinstance(alternate, dict):
                    segment(alternate.get('filename'), f'{name} alternate portrait filename')
        for kind, entries in (data.get('extras') or {}).items():
            for entry in entries:
                segment(entry.get('id'), f'{name} {kind} id')
                for field in _EXTRA_PATH_FIELDS:
                    relative(entry.get(field), f'{name} {kind} {field}')
    for name, data in (blob.get('stages') or {}).items():
        segment(name, 'stage name')
        for variant in data.get('variants') or []:
            segment(variant.get('id'), f'{name} variant id')
            for field in _VARIANT_FILE_FIELDS:
                segment(variant.get(field), f'{name} variant {field}')
    for family in ('custom_characters', 'custom_stages'):
        for item in blob.get(family) or []:
            segment(item.get('slug'), f'{family} slug')
    for family in ('xdelta', 'bundles'):
        for item in blob.get(family) or []:
            segment(item.get('id'), f'{family} id')


def _prepare_restore_db(root, blob):
    """Build and verify the replacement DB before moving the current Vault."""
    from core import config, vault
    if getattr(config, 'VAULT_BACKEND', 'json') != 'db':
        return
    # A custom DB outside the Vault cannot participate in the directory swap.
    if Path(config.VAULT_DB_PATH).resolve() != (STORAGE_PATH / 'vault.db').resolve():
        raise ValueError('Replace restore requires vault.db inside the Vault directory')
    path = root / 'vault.db'
    vault.save_blob(blob, path=path)
    if vault.load_blob(path=path) != blob:
        raise ValueError('Restored database failed catalog verification')


def _rename_aside(destination, previous, attempts=5, pause_s=0.3):
    """Move the live Vault folder aside. Windows refuses while any file under it is open, and the assistant's task
    journal keeps tasks.db open on its threads (core/storage_handles.py), so close every registered handle first.
    A journal write can reopen it in between, and a virus scanner can hold a file for a moment: close and try again
    a few times before giving up (the caller rolls back; nothing has moved yet)."""
    for attempt in range(attempts):
        storage_handles.close_all()
        try:
            destination.rename(previous)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause_s)


def _replace_restore(zip_path, job):
    """Stage completely, then publish with the previous directory recoverable.

    The job owns the staging tree, and the moved-aside Vault until the new one
    is live, so a crash between the two renames is undone at the next start
    (``_clean_restore``). The metadata lock excludes cooperating writers during
    the directory switch. It does not yet coordinate legacy writers that bypass
    that lock.
    """
    destination = STORAGE_PATH.resolve()
    parent = destination.parent
    staging = parent / f'.vault-restore-{uuid.uuid4().hex}'
    previous = parent / f'.vault-previous-{uuid.uuid4().hex}'
    job.own('staging', str(staging))
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            _extract_zip_with_progress(zipf, staging, job, 5, 90,
                                       skip=_DB_ARTIFACTS | _local_only_members(zipf),
                                       phase='Validating backup')
        _settle_sqlite_journals(staging)
        blob = _validate_restore_catalog(staging)
        _prepare_restore_db(staging, blob)
        job.progress(0.92, 'Reading Tracker data…')
        tracker = _stage_tracker_store(zip_path, staging, job)
        restored_tracker = tracker['status'] == 'restored'
        job.progress(0.95, 'Publishing restored vault…')
        with metadata_lock:
            had_previous = destination.exists()
            if had_previous:
                if restored_tracker:
                    _carry_sign_in(destination, staging)
                job.own('previous', {'path': str(previous), 'vault': str(destination)})
                _rename_aside(destination, previous)
            try:
                staging.rename(destination)
            except Exception as publish_error:
                if had_previous:
                    try:
                        previous.rename(destination)
                    except Exception as rollback_error:
                        raise RuntimeError(
                            f'Restore failed; the previous Vault is preserved at {previous}. '
                            f'Automatic rollback failed: {rollback_error}') from publish_error
                raise
            job.release('previous')
            if had_previous:
                _carry_local_state(previous, destination, tracker_store=not restored_tracker)
        if restored_tracker:
            tracker_backup.forget_schema_caches()
        # Retain the prior Vault for recovery. Deleting it here could discard
        # writes from legacy operations that still hold files in that directory.
        return (str(previous) if had_previous else None), tracker
    finally:
        # This is only our unpublished, uniquely named staging tree. Never
        # remove the current or previous Vault on any failure path.
        if staging.exists():
            assert staging.resolve().parent == parent
            shutil.rmtree(staging)
        job.release('staging')


def _sync_db_after_restore():
    """Rebuild vault.db from the (restored/merged) metadata.json when the DB
    backend is active, so the DB reflects the restore. No-op in JSON mode."""
    from core import config, vault
    if getattr(config, 'VAULT_BACKEND', 'json') != 'db':
        return
    meta_path = STORAGE_PATH / 'metadata.json'
    if not meta_path.exists():
        return
    with open(meta_path, 'r', encoding='utf-8') as f:
        blob = json.load(f)
    vault.save_blob(blob)


def _tree_size(root):
    """Total size in bytes of the files under root. Missing root reads as 0,
    and files that vanish mid-walk are skipped instead of failing the call."""
    if not root.exists():
        return 0
    total = 0
    for entry in root.rglob('*'):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


@vault_backup_bp.route('/api/mex/storage/stats', methods=['GET'])
def get_storage_stats():
    """Return disk usage in bytes, split by what the space is holding."""
    storage = _tree_size(STORAGE_PATH)
    projects = _tree_size(PROJECTS_PATH)
    return jsonify({'success': True, 'stats': {
        'storage': storage,
        'projects': projects,
    }})


def _backup_destination(body):
    """Where Export Vault saves the backup: the ``destination`` the app's save dialog picked (electron/ipc/files.js,
    ``save-vault-backup-dialog``), or None without one. It is a .zip in a folder that exists, outside the Vault (the
    next backup would carry it). ValueError says what is wrong with it."""
    destination = body.get('destination') if isinstance(body, dict) else None
    if destination is None or destination == '':
        return None
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError('No destination given')
    path = Path(destination.strip())
    if not path.is_absolute():
        raise ValueError('Choose a full path to save the backup to')
    if path.suffix.lower() != '.zip':
        raise ValueError('Save the backup as a .zip file')
    if not path.parent.is_dir():
        raise ValueError(f'Folder does not exist: {path.parent}')
    if path.is_dir():
        raise ValueError(f'{path.name} is a folder; choose a file name')
    try:
        path.resolve().relative_to(STORAGE_PATH.resolve())
    except ValueError:
        return path
    raise ValueError('Save the backup outside the Vault folder')


def _save_backup(backup_path, destination):
    """Put a finished backup at ``destination``, whole or not at all: copied beside it under a hidden name, then put in
    place in one rename. A failed save leaves no part file, and any file the user chose to replace stays as it was."""
    staging = destination.with_name(f'.{destination.name}.{uuid.uuid4().hex[:8]}.part')
    try:
        file_retry.retry_locked(shutil.copyfile, backup_path, staging)
        file_retry.replace(staging, destination)
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError as cleanup_error:
            logger.warning(f'Could not remove partial Vault export {staging}: {cleanup_error}')


@vault_backup_bp.route('/api/mex/storage/backup', methods=['POST'])
def backup_vault():
    """Create a backup ZIP of the entire storage vault.

    With a JSON ``destination`` (Export Vault: the path the user picked in the app's save dialog) the backup is saved
    there and nothing stays in output/. Without one it stays in output/vault_backups for the one-shot download below
    (the browser dev flow). Electron never downloads it: Chromium's own Save As dialog showed the download URL,
    backend token and all, as its title, and cancelling it deleted the backup."""
    try:
        destination = _backup_destination(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    partial_path = backup_path = None
    try:
        logger.info("=== VAULT BACKUP REQUEST ===")

        backups_dir = PROJECT_ROOT / "output" / "vault_backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"vault_backup_{timestamp}_{uuid.uuid4().hex[:8]}.zip"
        backup_path = backups_dir / backup_filename
        partial_path = backup_path.with_suffix('.part')

        logger.info(f"Creating backup: {backup_path}")

        with metadata_lock:
            catalog = _read_vault_catalog()
            snapshot = _backup_files()
            with tempfile.TemporaryDirectory(prefix='nucleus-backup-') as scratch, \
                    zipfile.ZipFile(partial_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr('metadata.json', json.dumps(catalog, indent=2))
                for relative, identity in snapshot.items():
                    candidate = STORAGE_PATH / relative
                    if candidate.is_symlink():
                        raise RuntimeError('Vault changed during backup; wait for active edits and retry')
                    source = resolve_under_root(
                        STORAGE_PATH, relative, field='Vault backup path')
                    if not source.is_file():
                        raise RuntimeError('Vault changed during backup; wait for active edits and retry')
                    if identity == _LIVE_DATABASE:
                        try:
                            database = _sqlite_snapshot(source, scratch)
                        except (sqlite3.Error, RuntimeError) as exc:
                            raise RuntimeError(f'Could not back up {relative}: {exc}') from exc
                        zipf.write(database, relative)
                        continue
                    stat = source.stat()
                    if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != identity:
                        raise RuntimeError('Vault changed during backup; wait for active edits and retry')
                    zipf.write(source, relative)
                tracker = _tracker_snapshot(Path(scratch))
                if tracker is not None:
                    zipf.write(tracker, tracker_backup.DB_NAME)
            # Some legacy asset writers do not yet take metadata_lock. Fail
            # visibly if their writes changed the file set during this backup.
            if snapshot != _backup_files() or catalog != _read_vault_catalog():
                raise RuntimeError('Vault changed during backup; wait for active edits and retry')
            file_retry.replace(partial_path, backup_path)

        backup_size = backup_path.stat().st_size
        logger.info(f"Backup created successfully: {backup_size} bytes")

        if destination is not None:
            try:
                _save_backup(backup_path, destination)
            except OSError as exc:
                raise RuntimeError(f'Could not save the backup to {destination.parent} ({exc.strerror or exc}). '
                                   'Antivirus or Windows Controlled Folder Access may block that folder; '
                                   'try another one.') from exc
            logger.info(f"Vault backup saved to {destination}")
            logger.info("=== VAULT BACKUP COMPLETE ===")
            return jsonify({'success': True, 'filename': destination.name, 'size': backup_size,
                            'path': str(destination)})

        logger.info("=== VAULT BACKUP COMPLETE ===")

        return jsonify({
            'success': True,
            'filename': backup_filename,
            'size': backup_size,
            'path': str(backup_path)
        })
    except Exception as e:
        logger.error(f"Vault backup error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        # A saved export leaves nothing in output/: the copy there was only its staging.
        leftovers = [partial_path] + ([backup_path] if destination is not None else [])
        for leftover in leftovers:
            if leftover is None:
                continue
            try:
                file_retry.retry_locked(leftover.unlink, missing_ok=True)
            except OSError as cleanup_error:
                logger.warning(f'Could not remove partial Vault backup {leftover}: {cleanup_error}')


@vault_backup_bp.route('/api/mex/storage/backup/download/<filename>', methods=['GET'])
def download_backup(filename):
    """Download a backup file"""
    try:
        backups_dir = PROJECT_ROOT / "output" / "vault_backups"
        validate_path_segment(filename, field='backup filename')
        if not filename.lower().endswith('.zip') or filename.lower() == '.zip':
            return jsonify({'success': False, 'error': 'Invalid backup filename'}), 400
        candidate = backups_dir / filename
        if candidate.is_symlink():
            return jsonify({'success': False, 'error': 'Backup file not found'}), 404
        backup_path = resolve_under_root(
            backups_dir, filename, field='backup filename')

        if not backup_path.is_file():
            return jsonify({'success': False, 'error': 'Backup file not found'}), 404

        return send_temporary_zip(backup_path, download_name=filename)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Backup download error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# Top-level metadata lists and the key that uniquely identifies an item within them.
_METADATA_LISTS = (
    ('xdelta', 'id'),
    ('custom_characters', 'slug'),
    ('custom_stages', 'slug'),
    ('bundles', 'id'),
)

# Dict-of-collections sections: section name -> key holding the per-entry item list.
_METADATA_COLLECTIONS = (
    ('characters', 'skins'),
    ('stages', 'variants'),
)

# Side catalogs are separate stores, not sections of the root metadata blob.
# Their item files are owned by a directory named after the catalog entry ID.
_SIDE_CATALOGS = (
    ('menus/css/icon_grid/metadata.json', 'mods', 'menu_mods'),
    ('menus/css/background/metadata.json', 'mods', 'menu_mods'),
    ('menus/css/doors/metadata.json', None, 'menu_mods'),
    ('menus/pause/metadata.json', 'mods', 'menu_mods'),
    ('menus/percent/metadata.json', 'mods', 'menu_mods'),
    ('codes/metadata.json', None, 'codes'),
)


def _merge_catalog_entries(current, incoming):
    """Keep complete current entries and append unique incoming identities."""
    merged = copy.deepcopy(current)
    if not isinstance(current, list) or not isinstance(incoming, list):
        raise ValueError('Invalid backup catalog: expected an item list')
    known = set()
    for item in current + incoming:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
            raise ValueError('Invalid backup catalog: each item needs an id')
        validate_path_segment(item['id'])
    if len({item['id'] for item in incoming}) != len(incoming):
        raise ValueError('Invalid backup catalog: duplicate item id')
    known.update(item['id'] for item in current)
    added, kept = [], []
    for item in incoming:
        if item['id'] in known:
            kept.append(item)
        else:
            merged.append(copy.deepcopy(item))
            added.append(item)
            known.add(item['id'])
    return merged, added, kept


def _merge_side_catalogs(extract_root, report, skip_prefixes):
    """Prepare all side catalogs before copying files or publishing metadata."""
    updates = {}
    for relative, list_key, family in _SIDE_CATALOGS:
        incoming_path = extract_root / relative
        if not incoming_path.exists():
            continue
        incoming = load_metadata(path=incoming_path)
        default = {'mods': []} if list_key else []
        current = load_metadata(default=default, path=STORAGE_PATH / relative)
        if list_key:
            if not isinstance(current, dict) or not isinstance(incoming, dict):
                raise ValueError(f'Invalid catalog shape: {relative}')
            entries, added, kept = _merge_catalog_entries(current.get(list_key, []), incoming.get(list_key, []))
            merged = {**copy.deepcopy(incoming), **copy.deepcopy(current), list_key: entries}
        else:
            merged, added, kept = _merge_catalog_entries(current, incoming)
        updates[relative] = merged
        for label, items in (('added', added), ('kept', kept)):
            report[label][family].extend(item.get('name') or item['id'] for item in items)
        directory = Path(relative).parent.as_posix()
        for item in kept:
            skip_prefixes.add(f'{directory}/{item["id"]}/')
    return updates


def merge_vault_metadata(current, incoming):
    """Merge ``incoming`` vault metadata into ``current``, keeping every current
    item and adding only items from the backup that aren't already present.

    The vault metadata has three shapes that each need different handling:

    * ``characters`` / ``stages`` -- dicts keyed by name, each holding a list of
      items (``skins`` / ``variants``) deduplicated by ``id``. Folder markers in a
      skin list also carry an ``id`` so they dedupe the same way.
    * ``xdelta`` / ``custom_characters`` / ``custom_stages`` / ``bundles`` --
      top-level lists deduplicated by ``id`` or ``slug``.
    * any other top-level key (e.g. ``version``) -- carried over from current,
      or from incoming when current lacks it.

    Returns ``(merged, stats)`` where ``stats`` counts items added from the backup.
    """
    merged = copy.deepcopy(current) if current else {}
    incoming = incoming or {}
    stats = {'characters': 0, 'stages': 0, 'xdelta': 0,
             'custom_characters': 0, 'custom_stages': 0, 'bundles': 0, 'extras': 0}

    # Dict-of-collections (characters/stages): merge per-name item lists by id.
    for section, item_key in _METADATA_COLLECTIONS:
        merged_section = merged.setdefault(section, {})
        for name, data in (incoming.get(section) or {}).items():
            if name not in merged_section:
                merged_section[name] = copy.deepcopy(data)
                stats[section] += len(data.get(item_key, []) if isinstance(data, dict) else [])
                continue
            existing_items = merged_section[name].setdefault(item_key, [])
            existing_ids = {item.get('id') for item in existing_items}
            for item in (data.get(item_key, []) if isinstance(data, dict) else []):
                if item.get('id') not in existing_ids:
                    existing_items.append(copy.deepcopy(item))
                    existing_ids.add(item.get('id'))
                    stats[section] += 1

    # Effects live alongside skins in each character, not in the skin list.
    for character, data in (incoming.get('characters') or {}).items():
        if not isinstance(data, dict) or not data.get('extras'):
            continue
        current_extras = ((current or {}).get('characters', {}).get(character, {}).get('extras') or {})
        target = merged['characters'][character].setdefault('extras', {})
        for kind, entries in data['extras'].items():
            target[kind], added, _ = _merge_catalog_entries(current_extras.get(kind, []), entries)
            stats['extras'] += len(added)

    # Top-level lists (xdelta/custom_*/bundles): merge by identity key.
    for list_key, id_key in _METADATA_LISTS:
        existing_list = merged.setdefault(list_key, [])
        existing_ids = {item.get(id_key) for item in existing_list}
        for item in (incoming.get(list_key) or []):
            if item.get(id_key) not in existing_ids:
                existing_list.append(copy.deepcopy(item))
                existing_ids.add(item.get(id_key))
                stats[list_key] += 1

    # Preserve any other top-level keys the backup introduces (e.g. version).
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)

    return merged, stats


def merge_plan(current, incoming):
    """Compare current vs incoming vault metadata and classify every backup item
    as NEW (not in the vault) or a CONFLICT (already present -- we keep ours).

    Returns ``(report, skip_prefixes)``:

    * ``report`` = ``{'added': {...}, 'kept': {...}}`` where each is a dict of
      per-type display-name lists, so the UI can show exactly what happened.
    * ``skip_prefixes`` = relative-path prefixes of CONFLICTING items' files. The
      file copy skips anything under these so a kept item's folder is never
      polluted by the backup's (possibly different) copy of the same item. Each
      content type maps to a path prefix:
        - custom_characters / custom_stages -> ``<kind>/<slug>/`` (whole folder)
        - skins   -> ``<Character>/<id>.`` and ``<Character>/<id>_``
        - variants-> ``das/<stage>/<id>.`` and ``das/<stage>/<id>_``
      (xdelta / bundles are single-file items, so plain skip-existing is already
      atomic for them -- no prefix needed, only a report entry.)
    """
    current = current or {}
    incoming = incoming or {}
    added = {k: [] for k in ('custom_characters', 'custom_stages',
                             'skins', 'variants', 'xdelta', 'bundles', 'extras',
                             'menu_mods', 'codes')}
    kept = {k: [] for k in added}
    skip = set()

    # Folder-per-slug items: skip the WHOLE folder on conflict.
    for key in ('custom_characters', 'custom_stages'):
        cur_slugs = {i.get('slug') for i in (current.get(key) or []) if isinstance(i, dict)}
        for item in (incoming.get(key) or []):
            if not isinstance(item, dict):
                continue
            slug = item.get('slug')
            name = item.get('name') or slug
            if slug in cur_slugs:
                kept[key].append(name)
                skip.add(f'{key}/{slug}/')
            else:
                added[key].append(name)

    # Single-file top-level items keyed by id (skip-existing is already atomic).
    for key in ('xdelta', 'bundles'):
        cur_ids = {i.get('id') for i in (current.get(key) or []) if isinstance(i, dict)}
        for item in (incoming.get(key) or []):
            if not isinstance(item, dict):
                continue
            label = item.get('name') or item.get('id')
            (kept if item.get('id') in cur_ids else added)[key].append(label)

    # Skins: flat files <Character>/<id>.* -- skip that id's files on conflict.
    cur_chars = current.get('characters') or {}
    for char, data in (incoming.get('characters') or {}).items():
        current_extras = (cur_chars.get(char) or {}).get('extras') or {}
        for kind, entries in ((data or {}).get('extras') or {}).items():
            _, new_entries, conflicts = _merge_catalog_entries(current_extras.get(kind, []), entries)
            added['extras'].extend(f'{char}: {item.get("name") or item["id"]}' for item in new_entries)
            kept['extras'].extend(f'{char}: {item.get("name") or item["id"]}' for item in conflicts)
            for item in conflicts:
                skip.add(f'{char}/models/{item["id"]}.')
                skip.add(f'{char}/models/{item["id"]}_')
                for field in ('model_file', 'texture_file', 'screenshot'):
                    if isinstance(item.get(field), str):
                        skip.add(f'{char}/{item[field]}')
        cur_ids = {s.get('id') for s in ((cur_chars.get(char) or {}).get('skins') or [])
                   if isinstance(s, dict)}
        for s in ((data or {}).get('skins') or []):
            if not isinstance(s, dict) or s.get('type') == 'folder':
                continue  # folder markers are metadata-only (no files)
            sid = s.get('id')
            label = f"{char} {s.get('color') or sid}"
            if sid in cur_ids:
                kept['skins'].append(label)
                skip.add(f'{char}/{sid}.')
                skip.add(f'{char}/{sid}_')
            else:
                added['skins'].append(label)

    # Stage variants: flat files das/<stage>/<id>.* -- skip that id's files.
    cur_stages = current.get('stages') or {}
    for stage, data in (incoming.get('stages') or {}).items():
        cur_ids = {v.get('id') for v in ((cur_stages.get(stage) or {}).get('variants') or [])
                   if isinstance(v, dict)}
        for v in ((data or {}).get('variants') or []):
            if not isinstance(v, dict):
                continue
            vid = v.get('id')
            label = f"{stage}: {v.get('name') or vid}"
            if vid in cur_ids:
                kept['variants'].append(label)
                skip.add(f'das/{stage}/{vid}.')
                skip.add(f'das/{stage}/{vid}_')
            else:
                added['variants'].append(label)

    return {'added': added, 'kept': kept}, skip


def _merge_restore(zip_path, job=None):
    """Restore a backup ZIP in *merge* mode: keep the current vault and add only
    items it doesn't already have. The backup's ``metadata.json`` is deep-merged
    with the current one (never overwritten). Data files for items you ALREADY
    have are skipped ATOMICALLY -- the whole conflicting item is left untouched,
    so a kept custom character/stage/skin can't end up as a mix of your build and
    the backup's. The backup's Tracker data then merges into this computer's
    store (:func:`_merge_tracker_store`). Returns ``(stats, report, tracker)``.

    Progress (when ``job`` is given): extract 5->50%, copy 50->95%, metadata
    merge 95->97%, Tracker data 97->100%.
    """
    with tempfile.TemporaryDirectory(prefix='nucleus-restore-') as extract_dir:
        if job is not None:
            job.own('extract', extract_dir)
        try:
            root = Path(extract_dir)
            (root / 'files').mkdir()
            (root / 'tracker').mkdir()
            stats, report = _merge_extracted(zip_path, root / 'files', job)
            return stats, report, _merge_tracker_store(zip_path, root / 'tracker', job)
        finally:
            if job is not None:
                job.release('extract')


def _merge_tracker_store(zip_path, workdir, job):
    """Add the backup's Tracker data to this computer's store (tracker.store.backup.merge_into): games it lacks with
    their rows, settings it has not set; its own rows and sign-in stay. The Vault merge is already published, so a
    failure is reported, not raised: ``{'status': 'merged', 'games': n}``, ``'none'``, ``'unreadable'`` or
    ``'failed'``."""
    if job is not None:
        job.progress(0.97, 'Merging Tracker data…')
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            incoming = _incoming_tracker_store(zipf, workdir)
    except Exception as exc:                                # noqa: BLE001 - reported with the merge's result
        logger.warning("Vault merge leaves out the backup's Tracker data: %s", exc)
        return {'status': 'unreadable'}
    if incoming is None:
        return {'status': 'none'}
    try:
        games = tracker_backup.merge_into(incoming, STORAGE_PATH / tracker_backup.DB_NAME)
    except Exception as exc:                                # noqa: BLE001 - reported with the merge's result
        logger.warning("Vault merge could not add the backup's Tracker data", exc_info=True)
        return {'status': 'failed', 'error': str(exc)}
    tracker_backup.forget_schema_caches()
    return {'status': 'merged', 'games': games}


def _merge_extracted(zip_path, extract_root, job):
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        _extract_zip_with_progress(zipf, extract_root, job, 5, 50,
                                   skip=_local_only_members(zipf), phase='Reading backup')
    _settle_sqlite_journals(extract_root)

    incoming_meta = _validate_restore_catalog(extract_root)
    with metadata_lock:
        current_meta = _read_vault_catalog()
        report, skip_prefixes = merge_plan(current_meta, incoming_meta)
        merged_meta, stats = merge_vault_metadata(current_meta, incoming_meta)
        side_catalogs = _merge_side_catalogs(extract_root, report, skip_prefixes)
        for family in ('menu_mods', 'codes'):
            stats[family] = len(report['added'][family])

        # Catalogs are merged explicitly. A conflicting item's entire file
        # family stays untouched, including files absent from our version.
        catalog_paths = {'metadata.json', *side_catalogs}
        files = [s for s in extract_root.rglob('*')
                 if s.is_file()
                 and s.relative_to(extract_root).as_posix() not in catalog_paths | _DB_ARTIFACTS
                 and not _local_only(s.relative_to(extract_root).as_posix())]
        # Preflight destinations before adding any file: the existing Vault
        # may contain symlinks, even though archive extraction is confined.
        planned = []
        for src in files:
            relative = src.relative_to(extract_root).as_posix()
            if not any(relative.startswith(p) for p in skip_prefixes):
                planned.append((src, resolve_under_root(STORAGE_PATH, relative)))
        for relative in catalog_paths:
            resolve_under_root(STORAGE_PATH, relative)

        STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        total = len(planned) or 1
        published = []
        last_pct = -1
        try:
            for i, (src, dest) in enumerate(planned, 1):
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    # An interrupted copy must not leave a truncated live asset.
                    partial = dest.with_name(f'.{dest.name}.{uuid.uuid4().hex}.part')
                    try:
                        shutil.copy2(src, partial)
                        if dest.exists():
                            raise RuntimeError('Vault changed during merge; retry after active edits finish')
                        file_retry.replace(partial, dest)
                        published.append(dest)
                    finally:
                        partial.unlink(missing_ok=True)
                if job is not None:
                    pct = 50 + int((i / total) * 45)
                    if pct != last_pct:
                        last_pct = pct
                        job.progress(pct / 100, f'Adding new items… ({len(published)} added)')
        except BaseException:
            # Nothing is cataloged yet: take back the files this merge added, or a
            # later merge would skip the same items as "already there".
            for path in reversed(published):
                try:
                    path.unlink()
                except OSError:
                    logger.warning('Could not take back %s after a failed merge', path, exc_info=True)
            raise

        if job is not None:
            job.progress(0.95, 'Updating vault catalog…')
        for relative, catalog in side_catalogs.items():
            save_metadata(catalog, path=STORAGE_PATH / relative)
        save_metadata(merged_meta, path=STORAGE_PATH / 'metadata.json')
        _sync_db_after_restore()
        return stats, report



def _tracker_note(tracker):
    """What a restore's message adds about the backup's Tracker data."""
    status = tracker.get('status')
    if status == 'merged' and tracker.get('games'):
        return f" Tracker: added {tracker['games']} game(s) from the backup."
    if status == 'unreadable':
        return " The backup's Tracker data could not be read and was left out; this computer's is unchanged."
    if status == 'failed':
        return (" The backup's Tracker data could not be added this time (Tracker may be busy); "
                "merging the backup again adds it.")
    return ''


def run_vault_restore(job, tmp_path, restore_mode):
    """The restore job (core/jobs.py): restore a backup ZIP, then delete the
    upload (owned from the job's start). Returns ``{mode, message, added?,
    report?, recovery_path?}``; any exception fails the job with its message."""
    tmp_path = Path(tmp_path)
    try:
        if restore_mode not in ('merge', 'replace'):
            raise ValueError('Restore mode must be merge or replace')
        job.progress(0.02, 'Reading backup…')
        logger.info(f"Restore mode: {restore_mode}")

        if restore_mode == 'merge':
            logger.info("Merging backup into existing vault...")
            stats, report, tracker = _merge_restore(tmp_path, job)
            added = sum(stats.values())
            kept = sum(len(v) for v in report['kept'].values())
            logger.info(f"Merge added {added} new item(s), kept {kept} conflict(s): {stats}")
            if added and kept:
                message = (f'Vault merged: added {added} new item(s), '
                           f'kept your version of {kept} conflict(s)')
            elif added:
                message = f'Vault merged: added {added} new item(s)'
            elif kept:
                message = (f'Vault merged: no new items — kept your version of '
                           f'{kept} item(s) already in your vault')
            else:
                message = 'Vault merged successfully (no new items found)'
            logger.info("=== VAULT RESTORE COMPLETE ===")
            return {'mode': restore_mode, 'message': message + _tracker_note(tracker), 'added': stats,
                    'report': report, 'tracker': tracker}

        recovery_path, tracker = _replace_restore(tmp_path, job)
        logger.info("=== VAULT RESTORE COMPLETE ===")
        return {
            'mode': restore_mode,
            'message': ('Vault restored successfully (replace mode). '
                        f'Previous Vault retained at {recovery_path}'
                        if recovery_path else
                        'Vault restored successfully (replace mode)') + _tracker_note(tracker),
            'recovery_path': recovery_path,
            'tracker': tracker,
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
            job.release('upload')
        except OSError:
            pass  # still owned: the job's cleanup tries again


@vault_backup_bp.route('/api/mex/storage/restore', methods=['POST'])
def restore_vault():
    """Receive a backup ZIP, validate it, and start the restore job. Returns the
    job's id as ``restore_id`` at once; the window follows it through the job
    store (``job`` event, ``GET /api/jobs/<id>``).

    The upload (saving the multi-GB ZIP) happens during this request, so the
    client can show upload progress via XHR; the slow extract/merge then reports
    progress on the job."""
    tmp_path = None
    worker_started = False
    try:
        logger.info("=== VAULT RESTORE REQUEST ===")

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No backup file uploaded'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not file.filename.lower().endswith('.zip'):
            return jsonify({'success': False, 'error': 'Only ZIP files are supported'}), 400

        restore_mode = request.form.get('mode', 'replace')
        if restore_mode not in ('merge', 'replace'):
            return jsonify({'success': False,
                            'error': 'Restore mode must be merge or replace'}), 400
        restore_id = request.form.get('restore_id')
        if restore_id:
            try:
                restore_id = str(uuid.UUID(restore_id))
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid restore_id'}), 400
        else:
            restore_id = str(uuid.uuid4())
        if jobs.get(restore_id) is not None:
            return jsonify({'success': False, 'error': 'Restore ID already used'}), 409

        with tempfile.NamedTemporaryFile(prefix='nucleus-restore-upload-', suffix='.zip', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            file.save(tmp)

        # Validate before starting the job, so obvious errors return inline.
        # Close the zip BEFORE unlinking -- Windows can't delete an open file.
        validation_error = None
        try:
            with zipfile.ZipFile(tmp_path, 'r') as zipf:
                if 'metadata.json' not in zipf.namelist():
                    validation_error = 'Invalid backup file: metadata.json not found'
        except zipfile.BadZipFile:
            validation_error = 'Invalid backup file: not a valid ZIP'
        if validation_error:
            tmp_path.unlink(missing_ok=True)
            return jsonify({'success': False, 'error': validation_error}), 400

        upload = str(tmp_path)
        try:
            jobs.start(RESTORE_KIND, lambda job: run_vault_restore(job, upload, restore_mode),
                       label='Vault restore', params={'mode': restore_mode}, job_id=restore_id,
                       single=True, critical=True, owned={'upload': upload})
        except jobs.JobBusy:
            return jsonify({'success': False, 'error': 'Another Vault restore is already running'}), 409
        except ValueError:
            return jsonify({'success': False, 'error': 'Restore ID already used'}), 409
        worker_started = True

        return jsonify({
            'success': True,
            'message': 'Vault restore started',
            'restore_id': restore_id,
            'mode': restore_mode,
        })
    except Exception as e:
        logger.error(f"Vault restore error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if tmp_path is not None and not worker_started:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning('Could not remove failed restore upload %s', tmp_path, exc_info=True)


@vault_backup_bp.route('/api/mex/storage/clear', methods=['POST'])
def clear_storage():
    """Clear storage based on provided options. Refused while a Vault restore
    runs, and done under the metadata lock, so it can never delete files a
    merge is about to catalog."""
    if jobs.active_job(RESTORE_KIND) is not None:
        return jsonify({'success': False,
                        'error': 'A Vault restore is running. Clear Storage after it finishes.'}), 409
    with metadata_lock:
        return _clear_storage()


def _clear_storage():
    try:
        data = request.json or {}
        clear_intake = data.get('clearIntake', False)
        clear_logs = data.get('clearLogs', False)

        logger.info("=== CLEAR STORAGE REQUEST ===")
        logger.info(f"Clear Intake: {clear_intake}")
        logger.info(f"Clear Logs: {clear_logs}")

        removed_count = 0
        output_lines = []

        # Clear storage
        logger.info("Clearing storage...")
        output_lines.append("Clearing storage...")

        # Remove character folders in storage (excluding 'das' folder)
        if STORAGE_PATH.exists():
            for item in STORAGE_PATH.iterdir():
                if item.is_dir() and item.name != "das":
                    logger.info(f"  Removing: {item.name}/")
                    output_lines.append(f"  Removing: {item.name}/")
                    shutil.rmtree(item)
                    removed_count += 1

        # Remove stage variant folders in storage/das/
        das_dir = STORAGE_PATH / "das"
        if das_dir.exists():
            for stage_folder in das_dir.iterdir():
                if stage_folder.is_dir():
                    variant_count = 0
                    for variant_item in stage_folder.iterdir():
                        if variant_item.is_file():
                            variant_item.unlink()
                        else:
                            shutil.rmtree(variant_item)
                        variant_count += 1
                    if variant_count > 0:
                        logger.info(f"  Removing: das/{stage_folder.name}/ ({variant_count} items)")
                        output_lines.append(f"  Removing: das/{stage_folder.name}/ ({variant_count} items)")
                        removed_count += 1

        # Clear Python cache directories
        for cache_dir in PROJECT_ROOT.rglob("__pycache__"):
            if cache_dir.is_dir():
                logger.info(f"  Removing: {cache_dir.relative_to(PROJECT_ROOT)}")
                output_lines.append(f"  Removing: {cache_dir.relative_to(PROJECT_ROOT)}")
                shutil.rmtree(cache_dir)
                removed_count += 1

        # Reset metadata.json to default structure
        metadata_file = STORAGE_PATH / 'metadata.json'
        if metadata_file.exists() or STORAGE_PATH.exists():
            logger.info("  Resetting: metadata.json")
            output_lines.append("  Resetting: metadata.json")
            STORAGE_PATH.mkdir(parents=True, exist_ok=True)
            with open(metadata_file, 'w') as f:
                json.dump({'version': '1.0', 'characters': {}, 'stages': {}}, f, indent=2)
            _sync_db_after_restore()
            removed_count += 1

        if removed_count > 0:
            output_lines.append(f"[OK] Cleared {removed_count} items from storage")
        else:
            output_lines.append("[INFO] Storage is already empty")

        # Optionally clear intake
        if clear_intake:
            logger.info("\nClearing intake...")
            output_lines.append("\nClearing intake...")
            intake_dir = PROJECT_ROOT / "intake"
            intake_count = 0
            if intake_dir.exists():
                for item in intake_dir.iterdir():
                    if item.is_file():
                        logger.info(f"  Removing: {item.name}")
                        output_lines.append(f"  Removing: {item.name}")
                        item.unlink()
                        intake_count += 1
            if intake_count > 0:
                output_lines.append(f"[OK] Cleared {intake_count} files from intake")
            else:
                output_lines.append("[INFO] Intake is already empty")

        # Optionally clear logs
        if clear_logs:
            logger.info("\nClearing logs...")
            output_lines.append("\nClearing logs...")
            logs_count = 0
            if LOGS_PATH.exists():
                for item in LOGS_PATH.iterdir():
                    if item.is_file() and item.suffix == '.log':
                        logger.info(f"  Removing: {item.name}")
                        output_lines.append(f"  Removing: {item.name}")
                        item.unlink()
                        logs_count += 1
            if logs_count > 0:
                output_lines.append(f"[OK] Cleared {logs_count} log files")
            else:
                output_lines.append("[INFO] No log files to clear")

        logger.info("=== CLEAR STORAGE COMPLETE ===")
        output_lines.append("\nDone!")

        return jsonify({
            'success': True,
            'message': 'Storage cleared successfully',
            'output': '\n'.join(output_lines)
        })
    except Exception as e:
        logger.error(f"Clear storage error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
