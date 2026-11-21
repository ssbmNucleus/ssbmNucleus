"""One locked, journaled, recoverable transaction over a managed build's files.

A *build* here is what the app calls a project: a directory holding
``project.mexproj`` beside ``files/``, ``data/``, ``sys/`` and ``assets/``.
Installing a menu means replacing ``files/MnSlChr.usd`` AND rewriting
``files/codes.ini`` + ``files/codes.gct``. Several file replacements are not
collectively atomic on any filesystem this app runs on, so the operation is
journaled instead.

The sequence, all inside :func:`build_lock`:

    staged -> applying -> applied -> verified -> committed

* ``staged``    every original copied into the journal; nothing written yet.
* ``applying``  files are being replaced; a death here leaves a mixed build.
* ``applied``   every write landed; verification has not run.
* ``verified``  verification passed AND the durable outcome of the operation
  (its receipt, the authorization it consumed) is recorded IN the journal.
* ``committed`` that outcome has been written out; the operation is complete.

:func:`recover` therefore has two jobs, not one. A journal left ``applying`` or
``applied`` is rolled back - the build goes back to what it was. A journal left
``verified`` is *finished*: the files are already correct and verified, so the
recorded receipt and authorization consumption are written out and the journal
is closed. Anything else would lose the outcome of a change that really did
happen, and would let the same authorization be spent twice.

Rollback is journaled the same way (``rolling_back``), refuses to run when the
files are no longer the ones it replaced, and validates every backup's hash
before it puts anything back.

Nothing here decides *what* to install. It is given exact bytes and exact
destinations by :mod:`nucleus_api.builds`, which is the only caller that maps a
registered artifact kind onto a destination path.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import file_retry
from core.hashing import sha256_file_or_none as sha256_file  # None when the file is missing

JOURNAL_DIRNAME = '.nucleus-build-journal'
LOCK_FILENAME = '.nucleus-build.lock'

#: Files this subsystem may write, relative to the build directory. A
#: destination outside this tuple is a programming error, not a caller choice.
MANAGED_FILES = ('files/MnSlChr.usd', 'files/MnSlMap.usd',
                 'files/codes.ini', 'files/codes.gct')

#: Files this subsystem never writes but whose contents decide whether a
#: proposal is still applicable: the disc header that says WHICH game this is,
#: and the m-ex marker that says which menu variant it carries. They are part of
#: the revision, so swapping a build's region after an approval invalidates it.
IDENTITY_FILES = ('sys/boot.bin', 'data/mex.json')

STAGED, APPLYING, APPLIED, VERIFIED, COMMITTED = (
    'staged', 'applying', 'applied', 'verified', 'committed')
ROLLING_BACK, ROLLED_BACK, RECOVERED = 'rolling_back', 'rolled_back', 'recovered'
#: A build whose state nobody can establish: an unreadable journal, a backup
#: that does not hash to what it claims, a restore that did not complete, or an
#: external whole-workspace save that died mid-write. It is NOT silently
#: repaired and NOT reported as recovered - it is quarantined, and every reader
#: and writer refuses it until a person looks.
QUARANTINED = 'quarantined'
#: A MexCLI command that opens and saves the WHOLE workspace. It cannot be
#: journaled file by file, so it is bracketed instead: a journal left open in
#: this state means the save died halfway and the build is not trustworthy.
EXTERNAL_SAVE = 'external_save'

#: States a recover() pass must act on, and what it does with each.
NEEDS_ROLLBACK = (APPLYING, APPLIED)
NEEDS_FINALIZE = (VERIFIED,)
NEEDS_RESTORE_COMPLETION = (ROLLING_BACK,)

_TXN_ID = re.compile(r'^txn_[0-9a-f]{12}$')


class SimulatedCrash(BaseException):
    """Injected between two writes so recovery can be tested for real.

    A ``BaseException`` on purpose: :func:`apply_change` must not unwind it,
    because a real crash does not run the rollback either.
    """


#: ``FAULT_HOOK(stage, relpath)`` is called at each journaled step when set.
#: Stages: ``'before_write'``, ``'after_write'``, ``'after_external'``,
#: ``'before_verify'``, ``'before_finalize'``, ``'during_restore'``.
#: Tests set it; production leaves it None.
FAULT_HOOK = None


class BuildBusyError(RuntimeError):
    """Another writer holds this build's mutation lock."""


class TransactionError(RuntimeError):
    """A journaled change could not be applied. ``code`` names the reason."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# hashing / small helpers
# --------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _fault(stage, relpath=None):
    if FAULT_HOOK is not None:
        FAULT_HOOK(stage, relpath)


def write_json_durably(path, payload):
    """Write JSON so a crash leaves either the old file or the whole new one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.',
                                         suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        file_retry.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _slug(relpath):
    return relpath.replace('/', '__').replace('\\', '__')


def copy_durably(source, destination):
    """Copy bytes and get them to the platter before the journal advances.

    ``shutil.copyfile`` returns when the bytes are in the page cache. A journal
    entry that says "the original is safe in the backup" is only true once the
    backup itself has been flushed, so every copy this module makes - backups,
    staged replacements, restores - goes through here.
    """
    destination = Path(destination)
    with open(source, 'rb') as reader, open(destination, 'wb') as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    return destination


def _sync_directory(path):
    """Flush a directory entry where the platform supports it."""
    if os.name == 'nt':
        return                      # Windows has no directory fsync; os.replace is atomic
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_durably(staged, target):
    """Atomically put ``staged`` in ``target``'s place, bytes already flushed."""
    file_retry.replace(staged, target)
    _sync_directory(Path(target).parent)


def is_reparse_point(path):
    """True when this path is a symlink, junction or other reparse point.

    Windows junctions are not symlinks and ``is_symlink()`` misses them, so the
    file attribute is checked directly. Every path this module reads or writes
    goes through :func:`assert_contained`, which refuses one.
    """
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, 'st_file_attributes', 0) & 0x400)   # REPARSE_POINT


def assert_contained(root, candidate, *, what='path'):
    """Resolve ``candidate`` under ``root`` and refuse anything that escapes.

    Refuses absolute escapes, ``..`` traversal, and any reparse point between
    the root and the candidate - a junction planted inside the workspace would
    otherwise redirect a write into the build, or out of it.

    Args:
        root: the directory the path must stay inside.
        candidate: the path to check; relative parts resolve against ``root``.
        what: a noun for the error message.

    Returns:
        pathlib.Path: the resolved, contained path.

    Raises:
        TransactionError: the path escapes, or a link/junction is in the way.

    Example:
        >>> assert_contained(build, build / 'files' / 'codes.ini')
        WindowsPath('.../files/codes.ini')
    """
    root = Path(root).resolve()
    target = Path(candidate)
    if not target.is_absolute():
        target = root / target
    resolved = Path(os.path.normpath(str(target)))
    try:
        resolved.relative_to(root)
    except ValueError:
        raise TransactionError('path_escape',
                               f'Refusing this {what}: {candidate} is outside {root}.') from None
    walk = root
    for part in resolved.relative_to(root).parts:
        walk = walk / part
        if is_reparse_point(walk):
            raise TransactionError(
                'path_escape',
                f'Refusing this {what}: {walk} is a link or junction, and where it really '
                'points is not what was approved.')
    return resolved


# --------------------------------------------------------------------------
# build identity
# --------------------------------------------------------------------------

def is_mex_build(directory):
    """True when this directory is a MEX project: the one committable format."""
    directory = Path(directory)
    return project_file(directory).is_file() and (directory / 'files').is_dir()


def project_file(directory):
    """The ``.mexproj`` MexCLI commands take, for a MEX build.

    Every project Nucleus creates has ``project.mexproj``. A build made elsewhere
    and opened in place can name it anything: ACE's public build ships
    ``ace.mexproj``, and assuming the default name there failed every character
    install with ``[Errno 2]``. So: the default name when present, else the
    folder's own ``.mexproj`` (the default path, missing, when there is none).
    """
    directory = Path(directory)
    default = directory / 'project.mexproj'
    if default.is_file():
        return default
    own = sorted(directory.glob('*.mexproj'))
    return own[0] if own else default


def managed_digests(directory):
    """SHA-256 of every managed and identity file present in the build.

    Returns a ``{relpath: sha256}`` dict; absent files are omitted, so a build
    with no ``MnSlMap.usd`` simply has no entry for it.
    """
    directory = Path(directory)
    digests = {}
    for relpath in MANAGED_FILES + IDENTITY_FILES:
        digest = sha256_file(directory / relpath)
        if digest is not None:
            digests[relpath] = digest
    return digests


def build_revision(directory):
    """A content revision for the build's managed AND identity files.

    Derived from the files themselves rather than a counter, so an edit made
    outside this subsystem (the app's own install route, a hand copy, an ISO
    re-import that changes the disc revision) also changes the revision and
    invalidates a pending authorization.
    """
    digests = managed_digests(directory)
    canonical = '\n'.join(f'{name}:{digests[name]}' for name in sorted(digests))
    return 'rev-' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]


def compiler_identity():
    """What will compile the code list, identified so a swap invalidates a plan.

    Returns ``{'name', 'path', 'sha256', 'available'}``. The digest is of the
    compiler binary itself: a MexCLI upgrade between preparing a change and
    committing it can produce a different ``codes.gct``, and that should be
    noticed rather than assumed away.
    """
    compiler = CODE_COMPILER
    name = getattr(compiler, '__name__', repr(compiler))
    if compiler is not mexcli_sync_codes:
        return {'name': name, 'path': None, 'sha256': None, 'available': True}
    try:
        from core.config import MEXCLI_PATH
        path = Path(MEXCLI_PATH)
    except Exception:                                          # noqa: BLE001
        return {'name': name, 'path': None, 'sha256': None, 'available': False,
                'parts': {}}
    # The launcher is not the implementation. mexcli.exe is a thin host for
    # mexcli.dll, mexLib.dll and HSDRaw.dll; swapping any of those changes what
    # the code list compiles to while the .exe's hash stays put.
    parts = {}
    for name_of in COMPILER_FILES:
        candidate = path.parent / name_of
        digest = sha256_file(candidate)
        if digest is not None:
            parts[name_of] = digest
    combined = hashlib.sha256(
        '\n'.join(f'{k}:{parts[k]}' for k in sorted(parts)).encode('utf-8')).hexdigest()
    return {'name': name, 'path': str(path), 'sha256': combined if parts else None,
            'parts': parts, 'available': path.is_file() and bool(parts)}


# --------------------------------------------------------------------------
# GCT: the compiled code list the disc actually carries
# --------------------------------------------------------------------------

#: Every deployed file the code compiler's behaviour depends on. The managed
#: implementation lives in the DLLs beside the launcher.
COMPILER_FILES = ('mexcli.exe', 'mexcli.dll', 'mexLib.dll', 'HSDRaw.dll')

GCT_HEADER = bytes.fromhex('00D0C0DE00D0C0DE')
GCT_FOOTER = bytes.fromhex('F000000000000000')


def gct_report(path):
    """Read a ``codes.gct`` and say whether it is one.

    "The file is not empty" is not a check: a hash written to that filename
    passes it. A real GCT opens with ``00D0C0DE 00D0C0DE``, ends with
    ``F0000000 00000000`` and is a whole number of 8-byte words.

    Args:
        path: the build's ``files/codes.gct``.

    Returns:
        dict: ``{'status': 'pass'|'fail', 'bytes', 'body': bytes, 'reason'}``.
        ``body`` is the compiled region between header and footer, so a caller
        can look for a particular code's compiled bytes in it.

    Example:
        >>> gct_report(build / 'files' / 'codes.gct')['status']
        'pass'
    """
    path = Path(path)
    if not path.is_file():
        return {'status': 'fail', 'bytes': 0, 'body': b'', 'reason': 'no codes.gct'}
    data = path.read_bytes()
    if len(data) < len(GCT_HEADER) + len(GCT_FOOTER):
        return {'status': 'fail', 'bytes': len(data), 'body': b'',
                'reason': 'too short to be a GCT'}
    if len(data) % 8:
        return {'status': 'fail', 'bytes': len(data), 'body': b'',
                'reason': 'not a whole number of 8-byte words'}
    if not data.startswith(GCT_HEADER):
        return {'status': 'fail', 'bytes': len(data), 'body': b'',
                'reason': f'header is {data[:8].hex().upper()}, not 00D0C0DE00D0C0DE'}
    if not data.endswith(GCT_FOOTER):
        return {'status': 'fail', 'bytes': len(data), 'body': b'',
                'reason': f'footer is {data[-8:].hex().upper()}, not F000000000000000'}
    return {'status': 'pass', 'bytes': len(data),
            'body': data[len(GCT_HEADER):-len(GCT_FOOTER)], 'reason': None}


# --------------------------------------------------------------------------
# the lock every writer must honour
# --------------------------------------------------------------------------

class _BuildLock:
    def __init__(self, stream, windows_lock, mexcli_lock, directory):
        self._stream = stream
        self._windows_lock = windows_lock
        self._mexcli_lock = mexcli_lock
        self.directory = directory

    def release(self):
        stream, self._stream = self._stream, None
        try:
            if stream is not None:
                try:
                    if os.name == 'nt':
                        import ctypes
                        import msvcrt
                        kernel, overlapped = self._windows_lock
                        kernel.UnlockFileEx(msvcrt.get_osfhandle(stream.fileno()), 0, 1, 0,
                                            ctypes.byref(overlapped))
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                finally:
                    stream.close()
        finally:
            if self._mexcli_lock is not None:
                self._mexcli_lock.release()
                self._mexcli_lock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


def build_lock(directory, *, timeout=30.0):
    """Take the build's exclusive mutation lock, or raise :class:`BuildBusyError`.

    Two locks, because the app has two kinds of competing writer:

    * ``core.state.mexcli_lock`` -- the RLock every MexCLI workspace write in
      this process already holds (costume import/reorder, sync-codes, export).
    * an exclusive byte lock on ``<build>/.nucleus-build.lock`` -- a second
      Nucleus process (a headless harness backend, a second window) is a real
      writer that a thread lock cannot see.

    Prefer :func:`core.build_access.build_session`, which also recovers the
    build before handing it over. Use this directly only where recovery has
    already happened.

    Args:
        directory: the build directory.
        timeout: seconds to wait for the cross-process lock.

    Returns:
        A context manager; ``release()`` drops both locks in the right order.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise TransactionError('unknown_build', f'No such build directory: {directory}')
    if is_reparse_point(directory):
        raise TransactionError('path_escape',
                               f'{directory} is a link or junction; refusing to lock it.')

    from core.state import mexcli_lock

    if not mexcli_lock.acquire(blocking=True, timeout=(timeout if timeout > 0 else -1)):
        raise BuildBusyError('Another Nucleus workspace operation is still running.')
    try:
        marker = directory / LOCK_FILENAME
        descriptor = os.open(marker, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        stream = os.fdopen(descriptor, 'r+b', buffering=0)
        try:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise TransactionError('unknown_build',
                                       'The build lock marker is not a regular file.')
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                try:
                    windows_lock = _take_file_lock(stream)
                    break
                except (BlockingIOError, PermissionError, OSError) as exc:
                    if time.monotonic() >= deadline:
                        raise BuildBusyError(
                            'Another Nucleus process is writing this build. Close the other '
                            'window or wait for its operation to finish; nothing was changed.'
                        ) from exc
                    time.sleep(0.1)
        except BaseException:
            stream.close()
            raise
        return _BuildLock(stream, windows_lock, mexcli_lock, directory)
    except BaseException:
        mexcli_lock.release()
        raise


def _take_file_lock(stream):
    if os.name != 'nt':
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return None
    from storage_data_lock import _lock_windows
    return _lock_windows(stream, True)


# --------------------------------------------------------------------------
# journal
# --------------------------------------------------------------------------

def journal_root(directory):
    """Where this build's journals, sealed proposals and receipts live."""
    return Path(directory) / JOURNAL_DIRNAME


def _journal_path(directory, txn_id):
    if not _TXN_ID.match(txn_id or ''):
        raise TransactionError('malformed_id', f'{txn_id!r} is not a transaction id.')
    return journal_root(directory) / 'txn' / txn_id / 'journal.json'


def read_journal(directory, txn_id):
    """The journal record for one transaction, or None."""
    path = _journal_path(directory, txn_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def _save_journal(directory, journal):
    write_json_durably(_journal_path(directory, journal['txn_id']), journal)


def recover(directory):
    """Put a build back to a usable state after an interrupted change.

    The caller must hold :func:`build_lock`; :func:`core.build_access.build_session`
    does both in the right order. Three cases:

    * ``applying`` / ``applied`` -- the write may be partial and nothing was
      verified. Every original goes back and the journal is closed.
    * ``verified`` -- the files ARE correct and were verified; only the record
      of the outcome is missing. The receipt and the authorization consumption
      stored in the journal are written out and the journal is committed. This
      is what stops a crash from losing a change that really happened, or from
      letting the same authorization be spent a second time.
    * ``rolling_back`` -- a rollback was interrupted; it is finished.

    Args:
        directory: the build directory.

    Returns:
        list[dict]: one ``{'txn_id', 'action', 'restored', 'finalized'}`` per
        journal that needed attention. Empty when nothing was interrupted.

    Example:
        >>> from core import build_transaction
        >>> build_transaction.recover(build_dir)
        [{'txn_id': 'txn_ab12cd34ef56', 'action': 'rolled_back',
          'restored': ['files/codes.ini'], 'finalized': []}]
    """
    directory = Path(directory)
    root = journal_root(directory) / 'txn'
    if not root.is_dir():
        return []
    actions = []
    for entry in sorted(root.iterdir()):
        path = entry / 'journal.json'
        if not path.is_file():
            continue
        try:
            journal = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            # A journal nobody can read is not an empty journal. Skipping it
            # would hand out a build whose last operation is unknown.
            actions.append(_quarantine_unreadable(directory, entry, exc))
            continue
        if not isinstance(journal, dict) or journal.get('txn_id') != entry.name:
            actions.append(_quarantine_unreadable(
                directory, entry, 'the journal does not describe this transaction'))
            continue
        state = journal.get('state')
        if state == QUARANTINED:
            actions.append({'txn_id': journal['txn_id'], 'action': 'quarantined',
                            'restored': [], 'finalized': [],
                            'problem': journal.get('problem')})
        elif state in NEEDS_ROLLBACK or state in NEEDS_RESTORE_COMPLETION:
            actions.append(_recover_by_restoring(directory, journal, state))
        elif state in NEEDS_FINALIZE:
            actions.append(_recover_by_finalizing(directory, journal))
        elif state == EXTERNAL_SAVE:
            actions.append(_quarantine(
                directory, journal,
                'A MexCLI whole-workspace save was interrupted. It rewrites many files at '
                'once and cannot be undone file by file, so this build cannot be repaired '
                'automatically.'))
        elif state == STAGED:
            journal.update({'state': ROLLED_BACK, 'recovered_utc': _now()})
            _save_journal(directory, journal)
            actions.append({'txn_id': journal['txn_id'], 'action': 'discarded_staged',
                            'restored': [], 'finalized': []})
    return actions


def _recover_by_restoring(directory, journal, state):
    """Put the originals back, and prove it before calling the build usable."""
    try:
        restored = _restore_originals(directory, journal)
    except TransactionError as exc:
        return _quarantine(directory, journal, str(exc))
    wrong = [entry['relpath'] for entry in journal['entries']
             if sha256_file(directory / entry['relpath']) != entry.get('original_sha256')]
    if wrong:
        return _quarantine(
            directory, journal,
            f'These files did not come back to what they were: {wrong}. Reporting this '
            'build as recovered would be a guess about its contents.')
    if state in NEEDS_RESTORE_COMPLETION and journal.get('finalize'):
        try:
            _write_finalization(directory, journal)
        except TransactionError as exc:
            return _quarantine(directory, journal, str(exc))
    journal.update({'state': ROLLED_BACK if state in NEEDS_RESTORE_COMPLETION else RECOVERED,
                    'recovered_utc': _now(), 'restored': restored})
    _save_journal(directory, journal)
    action = 'rollback_completed' if state in NEEDS_RESTORE_COMPLETION else 'rolled_back'
    return {'txn_id': journal['txn_id'], 'action': action, 'restored': restored,
            'finalized': []}


def _recover_by_finalizing(directory, journal):
    """The files were written AND verified; only the record of it is missing."""
    wrong = [entry['relpath'] for entry in journal['entries']
             if entry.get('replacement_sha256')
             and sha256_file(directory / entry['relpath']) != entry['replacement_sha256']]
    if wrong:
        return _quarantine(
            directory, journal,
            f'This change was verified, but {wrong} no longer hold what it wrote. Writing '
            'its receipt now would record an outcome the build does not have.')
    try:
        written = _write_finalization(directory, journal)
    except TransactionError as exc:
        return _quarantine(directory, journal, str(exc))
    journal.update({'state': COMMITTED, 'recovered_utc': _now(),
                    'finalized_by_recovery': True})
    _save_journal(directory, journal)
    return {'txn_id': journal['txn_id'], 'action': 'finalized', 'restored': [],
            'finalized': written}


def _quarantine(directory, journal, problem):
    journal.update({'state': QUARANTINED, 'problem': problem,
                    'quarantined_utc': _now()})
    _save_journal(directory, journal)
    return {'txn_id': journal['txn_id'], 'action': 'quarantined', 'restored': [],
            'finalized': [], 'problem': problem}


def _quarantine_unreadable(directory, entry, problem):
    journal = {'txn_id': entry.name, 'state': QUARANTINED, 'entries': [],
               'problem': f'This journal could not be read: {problem}',
               'quarantined_utc': _now()}
    _save_journal(directory, journal)
    return {'txn_id': entry.name, 'action': 'quarantined', 'restored': [],
            'finalized': [], 'problem': journal['problem']}


def quarantined(directory):
    """Every transaction this build cannot account for.

    Args:
        directory: the build directory.

    Returns:
        list[dict]: ``{'txn_id', 'problem'}`` per quarantined journal, empty
        when the build is accountable for everything it did.

    Example:
        >>> build_transaction.quarantined(build_dir)
        [{'txn_id': 'txn_ab12cd34ef56', 'problem': 'This journal could not be read: ...'}]
    """
    root = journal_root(Path(directory)) / 'txn'
    if not root.is_dir():
        return []
    blocked = []
    for entry in sorted(root.iterdir()):
        path = entry / 'journal.json'
        if not path.is_file():
            continue
        try:
            journal = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            blocked.append({'txn_id': entry.name, 'problem': 'unreadable journal'})
            continue
        if isinstance(journal, dict) and journal.get('state') == QUARANTINED:
            blocked.append({'txn_id': entry.name, 'problem': journal.get('problem')})
    return blocked


#: How each kind of durable outcome is written. A journal records a KIND and an
#: identity, never a destination: recovery reads journals out of the build
#: directory, and a project someone else authored could otherwise hand it an
#: absolute path and have it written on open. The destination is derived here,
#: from a validated identity, by code that lives outside the build.
FINALIZERS = {}

#: Where each kind's resolver lives. Recovery runs on a build the moment it is
#: opened, in a process that may never have imported the module that writes that
#: record, so the registry fills itself on demand rather than depending on
#: somebody having imported the right thing first.
_FINALIZER_MODULES = {
    'receipt': 'nucleus_api.builds',
    'authorization': 'core.build_authorization',
}


def _resolver_for(kind):
    if kind in FINALIZERS:
        return FINALIZERS[kind]
    module = _FINALIZER_MODULES.get(kind)
    if module:
        import importlib
        try:
            owner = importlib.import_module(module)
            # Already-imported modules do not re-run their registration, and
            # this module can be reloaded, so the hook is called explicitly.
            hook = getattr(owner, '_register_finalizers', None)
            if hook is not None:
                hook()
        except Exception:                                       # noqa: BLE001
            return None
    return FINALIZERS.get(kind)


def register_finalizer(kind, resolve):
    """Declare where one kind of durable outcome is written.

    Args:
        kind: the journal's label, e.g. ``'receipt'``.
        resolve: ``resolve(build_dir, identifier) -> Path``, which validates the
            identifier and returns the only destination it may have.

    Example:
        >>> register_finalizer('receipt', _receipt_destination)
    """
    FINALIZERS[kind] = resolve


def _finalization_targets(directory, journal):
    """Resolve every finalization destination, or refuse the whole journal."""
    targets = []
    for item in journal.get('finalize') or []:
        kind = item.get('kind')
        resolve = _resolver_for(kind)
        if resolve is None:
            raise TransactionError(
                'unknown_finalizer',
                f'This journal asks for a {kind!r} record, which nothing knows how to '
                'place. A journal names a kind and an identity; it does not get to name '
                'a destination.')
        try:
            target = resolve(directory, item.get('id'))
        except Exception as exc:                                # noqa: BLE001
            raise TransactionError(
                'unresolvable_finalizer',
                f'{kind} {item.get("id")!r} does not resolve to a destination: {exc}') from exc
        targets.append((target, item.get('json')))
    return targets


def _write_finalization(directory, journal):
    """Write the durable outcome the journal recorded. Idempotent by design."""
    written = []
    for target, payload in _finalization_targets(directory, journal):
        write_json_durably(target, payload)
        written.append(str(target))
    return written


def _restore_originals(directory, journal):
    """Put every original back, or raise. There is no partial success here.

    Every backup is checked against the hash the journal recorded for it BEFORE
    anything is written, so a restore either runs over intact copies or does not
    start. A missing backup used to be skipped and the transaction closed anyway,
    which reported a build as recovered while leaving it mixed.
    """
    txn_dir = journal_root(directory) / 'txn' / journal['txn_id']
    plan = []
    for entry in journal['entries']:
        target = assert_contained(directory, entry['relpath'], what='restore destination')
        if entry.get('original_sha256') is None:
            plan.append((entry, target, None))
            continue
        backup = txn_dir / 'originals' / _slug(entry['relpath'])
        measured = sha256_file(backup)
        if measured != entry['original_sha256']:
            raise TransactionError(
                'backup_not_intact',
                f'The journal copy of {entry["relpath"]} is missing or altered (expected '
                f'{entry["original_sha256"]}, found {measured}). Restoring from it would '
                'write bytes nobody recorded.')
        plan.append((entry, target, backup))

    restored = []
    for entry, target, backup in plan:
        if backup is None:
            try:
                target.unlink()
                restored.append(entry['relpath'])
            except FileNotFoundError:
                pass
            continue
        _fault('during_restore', entry['relpath'])
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.name + '.restore.tmp')
        copy_durably(backup, staged)
        _replace_durably(staged, target)
        restored.append(entry['relpath'])
    return restored


# --------------------------------------------------------------------------
# the code compiler seam
# --------------------------------------------------------------------------

def mexcli_sync_codes(directory, ini_text):
    """Write a build's code list with MexCLI, the app's own code writer.

    ``mexcli sync-codes`` rewrites BOTH ``files/codes.ini`` and
    ``files/codes.gct`` from a complete desired INI, preserving nothing of its
    own -- which is why the merge happens before this is called.
    """
    from core.config import MEXCLI_PATH, get_subprocess_args
    if not Path(MEXCLI_PATH).is_file():
        raise TransactionError(
            'code_compiler_unavailable',
            f'MexCLI is missing at {MEXCLI_PATH}; the build\'s codes.gct cannot be rebuilt, '
            'so the code change was not applied.')
    scratch = Path(tempfile.mkdtemp(prefix='nucleus-build-codes-'))
    try:
        desired = scratch / 'codes.ini'
        desired.write_text(ini_text, encoding='utf-8')
        result = subprocess.run(
            [str(MEXCLI_PATH), 'sync-codes', str(project_file(directory)), str(desired)],
            capture_output=True, text=True, timeout=300, **get_subprocess_args())
        try:
            payload = json.loads(result.stdout or '{}')
        except ValueError:
            payload = {}
        if result.returncode != 0 or not payload.get('success'):
            raise TransactionError(
                'code_sync_failed',
                'MexCLI sync-codes failed: '
                f'{payload.get("error") or result.stderr or result.stdout or "no output"}')
        return {'applied': payload.get('count'), 'enabled': payload.get('enabled'),
                'gct_bytes': payload.get('gctBytes')}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


#: The step that turns a desired ``codes.ini`` into the build's real
#: ``codes.ini`` + ``codes.gct``. MexCLI in the app; tests may replace it, but
#: whatever replaces it must still produce a GCT :func:`gct_report` accepts.
CODE_COMPILER = mexcli_sync_codes


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def apply_change(directory, writes, *, label, identities=None, code_ini=None,
                 verify=None, finalize_builder=None, txn_id=None):
    """Replace a build's files as one journaled, recoverable transaction.

    Args:
        directory: the build directory. The caller must already hold
            :func:`build_lock` and have run :func:`recover`.
        writes: list of ``{'relpath', 'source', 'sha256'}``. ``relpath`` must be
            one of :data:`MANAGED_FILES`; ``source`` is the sealed file whose
            bytes are installed.
        label: a short human name for the receipt, e.g. ``'menu + codes'``.
        identities: the operation's identities (proposal, authorization, receipt
            ids) recorded in the journal BEFORE anything is written, so a crash
            leaves a record of what was being done and for whom.
        code_ini: the complete desired ``codes.ini`` text, or None to leave the
            build's codes alone. When given, ``codes.ini`` and ``codes.gct`` are
            backed up and then rewritten by :data:`CODE_COMPILER`.
        verify: ``verify(directory) -> dict`` run while the journal is still
            open. Anything it raises rolls the whole change back.
        finalize_builder: ``finalize_builder(journal) -> [{'path', 'json'}]``,
            called under the lock after verification. Its result is stored in
            the journal and then written; a crash in between is completed by
            :func:`recover`, so the receipt and the authorization consumption
            cannot be lost.
        txn_id: override the generated transaction id (tests).

    Returns:
        dict: the closed journal - ``{'txn_id', 'state', 'label', 'entries',
        'verification', 'code_sync', 'identities', 'applied_utc'}``.

    Raises:
        TransactionError: the change was rolled back; the build is unchanged.

    Example:
        >>> with bt.build_lock(build_dir):
        ...     bt.recover(build_dir)
        ...     bt.apply_change(build_dir, [{'relpath': 'files/MnSlChr.usd',
        ...                                  'source': sealed, 'sha256': digest}],
        ...                     label='menu')['state']
        'committed'
    """
    directory = Path(directory)
    txn_id = txn_id or ('txn_' + secrets.token_hex(6))
    if not _TXN_ID.match(txn_id):
        raise TransactionError('malformed_id', f'{txn_id!r} is not a transaction id.')
    txn_dir = journal_root(directory) / 'txn' / txn_id
    (txn_dir / 'originals').mkdir(parents=True, exist_ok=True)
    (txn_dir / 'staged').mkdir(parents=True, exist_ok=True)

    entries = []
    for write in writes:
        relpath = write['relpath']
        if relpath not in MANAGED_FILES:
            raise TransactionError('unmanaged_destination',
                                   f'{relpath} is not a file this subsystem may write.')
        source = Path(write['source'])
        digest = sha256_file(source)
        if digest is None or (write.get('sha256') and digest != write['sha256']):
            raise TransactionError('artifact_hash_mismatch',
                                   f'{source} no longer matches the hash it was sealed with.')
        assert_contained(directory, relpath, what='destination')
        copy_durably(source, txn_dir / 'staged' / _slug(relpath))
        entries.append({'relpath': relpath, 'mode': 'replace',
                        'original_sha256': sha256_file(directory / relpath),
                        'replacement_sha256': digest})
    if code_ini is not None:
        for relpath in ('files/codes.ini', 'files/codes.gct'):
            entries.append({'relpath': relpath, 'mode': 'compiler',
                            'original_sha256': sha256_file(directory / relpath),
                            'replacement_sha256': None})

    for entry in entries:
        original = directory / entry['relpath']
        if entry['original_sha256'] is not None:
            copy_durably(original, txn_dir / 'originals' / _slug(entry['relpath']))
            keep = sha256_file(txn_dir / 'originals' / _slug(entry['relpath']))
            if keep != entry['original_sha256']:
                raise TransactionError('backup_not_intact',
                                       f'The journal copy of {entry["relpath"]} does not '
                                       'match the file it was taken from.')

    journal = {'txn_id': txn_id, 'label': label, 'state': STAGED,
               'build_dir': str(directory), 'entries': entries,
               'identities': dict(identities or {}),
               'created_utc': _now(), 'has_code_change': code_ini is not None}
    _save_journal(directory, journal)

    journal['state'] = APPLYING
    _save_journal(directory, journal)

    try:
        for entry in entries:
            if entry['mode'] != 'replace':
                continue
            _fault('before_write', entry['relpath'])
            target = assert_contained(directory, entry['relpath'], what='destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            landing = target.with_name(target.name + '.nucleus-new')
            copy_durably(txn_dir / 'staged' / _slug(entry['relpath']), landing)
            _replace_durably(landing, target)
            _fault('after_write', entry['relpath'])
        code_sync = None
        if code_ini is not None:
            code_sync = CODE_COMPILER(directory, code_ini)
            _fault('after_external', 'files/codes.ini')
            for entry in entries:
                if entry['mode'] == 'compiler':
                    entry['replacement_sha256'] = sha256_file(directory / entry['relpath'])
        journal['state'] = APPLIED
        journal['code_sync'] = code_sync
        _save_journal(directory, journal)

        _fault('before_verify', None)
        journal['verification'] = verify(directory) if verify is not None \
            else {'status': 'skipped'}
        journal['applied_utc'] = _now()

        _fault('before_finalize', None)
        journal['finalize'] = list(finalize_builder(journal)) if finalize_builder else []
        journal['state'] = VERIFIED
        _save_journal(directory, journal)
    except SimulatedCrash:
        raise
    except Exception as exc:                                    # noqa: BLE001
        try:
            restored = _restore_originals(directory, journal)
        except TransactionError as restore_failure:
            # The change failed AND its originals cannot be put back. That is a
            # build nobody can state the contents of, so it is quarantined
            # rather than reported as rolled back.
            _quarantine(directory, journal,
                        f'{exc} -- and the originals could not be restored: '
                        f'{restore_failure}')
            raise TransactionError(
                'rollback_failed',
                f'{exc}. Restoring the originals then failed too, so this build is '
                f'quarantined: {restore_failure}') from exc
        journal.update({'state': ROLLED_BACK, 'error': str(exc), 'restored': restored})
        _save_journal(directory, journal)
        if isinstance(exc, TransactionError):
            raise
        raise TransactionError('apply_failed', f'The change was rolled back: {exc}') from exc

    _write_finalization(directory, journal)
    journal['state'] = COMMITTED
    _save_journal(directory, journal)
    return journal


def begin_external_save(directory, label):
    """Open a journal around a whole-workspace save nobody can undo piecemeal.

    Args:
        directory: the build directory. The caller holds :func:`build_lock`.
        label: what is being run, e.g. ``'mexcli set-css-icon'``.

    Returns:
        dict: the journal record; pass it to :func:`end_external_save`.

    Example:
        >>> record = begin_external_save(build_dir, 'mexcli sync-codes')
    """
    journal = {'txn_id': 'txn_' + secrets.token_hex(6), 'label': label,
               'state': EXTERNAL_SAVE, 'build_dir': str(directory), 'entries': [],
               'identities': {}, 'created_utc': _now(), 'external': True,
               'managed_before': managed_digests(directory)}
    _save_journal(Path(directory), journal)
    return journal


def end_external_save(directory, journal, *, failed=False):
    """Close that journal, so an interrupted save is the only one left open.

    Args:
        directory: the build directory.
        journal: the record from :func:`begin_external_save`.
        failed: the command reported a failure. The journal is quarantined,
            because a failed whole-workspace save may have written part of it.

    Returns:
        dict: the closed journal.

    Example:
        >>> end_external_save(build_dir, record)['state']
        'committed'
    """
    directory = Path(directory)
    journal = dict(journal)
    journal['managed_after'] = managed_digests(directory)
    journal['finished_utc'] = _now()
    if failed:
        journal.update({'state': QUARANTINED,
                        'problem': (f'{journal["label"]} failed part way through a '
                                    'whole-workspace save. Which files it had already '
                                    'rewritten is not recorded anywhere.')})
    else:
        journal['state'] = COMMITTED
    _save_journal(directory, journal)
    return journal


def rollback(directory, txn_id, *, finalize=()):
    """Undo a committed transaction, refusing when it is no longer the last word.

    Args:
        directory: the build directory. The caller must hold :func:`build_lock`
            and have run :func:`recover`.
        txn_id: the transaction to undo (a receipt's ``journal_id``).

    Returns:
        dict: ``{'txn_id', 'restored', 'revision'}`` - the build revision after
        the originals went back.

    Raises:
        TransactionError: ``stale_rollback`` when a file no longer holds the
            bytes this transaction wrote (undoing it would delete somebody
            else's change), or ``backup_not_intact`` when a journal copy does
            not hash to the original it claims to be.

    Example:
        >>> build_transaction.rollback(build_dir, 'txn_ab12cd34ef56')['restored']
        ['files/MnSlChr.usd', 'files/codes.ini', 'files/codes.gct']
    """
    directory = Path(directory)
    journal = read_journal(directory, txn_id)
    if journal is None:
        raise TransactionError('unknown_transaction', f'No journal {txn_id} in this build.')
    if journal['state'] != COMMITTED:
        raise TransactionError('not_rollbackable',
                               f'Transaction {txn_id} is {journal["state"]}, not committed.')

    stale = []
    for entry in journal['entries']:
        measured = sha256_file(directory / entry['relpath'])
        if measured != entry['replacement_sha256']:
            stale.append({'file': entry['relpath'], 'expected': entry['replacement_sha256'],
                          'measured': measured})
    if stale:
        raise TransactionError(
            'stale_rollback',
            f'{directory.name} no longer holds what this change wrote ({stale!r}). '
            'Undoing it now would delete a later change nobody asked to lose.')

    txn_dir = journal_root(directory) / 'txn' / txn_id
    for entry in journal['entries']:
        if entry.get('original_sha256') is None:
            continue
        measured = sha256_file(txn_dir / 'originals' / _slug(entry['relpath']))
        if measured != entry['original_sha256']:
            raise TransactionError(
                'backup_not_intact',
                f'The journal copy of {entry["relpath"]} is missing or altered; there is '
                'nothing trustworthy to put back.')

    journal['state'] = ROLLING_BACK
    journal['rollback_started_utc'] = _now()
    # Whatever has to be recorded once the originals are back travels IN the
    # journal, so a death between the restore and the record is finished by
    # recovery instead of leaving a receipt that describes the undone state.
    journal['finalize'] = list(finalize)
    _finalization_targets(directory, journal)          # resolvable before we start
    _save_journal(directory, journal)

    restored = _restore_originals(directory, journal)
    incomplete = [entry['relpath'] for entry in journal['entries']
                  if sha256_file(directory / entry['relpath']) != entry['original_sha256']]
    if incomplete:
        raise TransactionError('rollback_incomplete',
                               f'These files did not come back: {incomplete}. The journal '
                               'stays open so the next recover() finishes it.')
    _write_finalization(directory, journal)
    journal.update({'state': ROLLED_BACK, 'rolled_back_utc': _now(), 'restored': restored})
    _save_journal(directory, journal)
    return {'txn_id': txn_id, 'restored': restored, 'revision': build_revision(directory)}
