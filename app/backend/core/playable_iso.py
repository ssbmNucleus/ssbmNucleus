"""The one place this app is allowed to write a disc image someone plays.

The rule this module exists to enforce has no exceptions:

    Nucleus never edits or overwrites the user's clean Melee ISO, and never
    overwrites any ISO it did not itself produce.

The clean Melee file is a read-only SOURCE that projects are created from. "The
game you play" is the separate modded ISO this app builds. Every other file on
the machine belongs to somebody else.

Proof of ownership is a marker written beside each published copy
(``<name>.nucleus-build.json``) whose recorded ``output_digest`` still matches
the file's current bytes (or its ``pending_digest``, the bytes a publish was
replacing it with; see step 5). A marker next to a file somebody has since
replaced proves nothing about the file; an ISO with no marker is not ours
whatever its name suggests.

Everything that writes an ISO goes through :func:`publish` -- the delivery
workflow, its undo, and the Save button on the export screen -- so there is one
audit surface, and it behaves the same way for all of them:

1. **Check, exclusively.** The destination is refused outright when it is the
   clean source, the file Slippi Launcher is configured to open (unless that
   file is one of ours), or an existing file without a valid marker. A path that
   does not exist yet, inside a folder that does, is fine: we are about to
   create it.
2. **Stage beside it.** The bytes are copied to a randomly named sibling
   created with ``O_CREAT|O_EXCL`` -- never onto an existing name -- and hashed.
   A staged copy that does not hash to the source is thrown away and nothing is
   replaced.
3. **Check again, right before the write.** The destination is re-verified
   against the identity captured in step 1. A file that changed underneath us
   during the copy is somebody else's now, and the publication stops.
4. **Keep the old bytes.** The existing copy is hard-linked to an exclusively
   created ``<stem>.previous-<id>.iso`` first, so the playable path keeps its
   old contents until the atomic replace succeeds, and an undo has something to
   put back. A hard link costs no space; where the filesystem refuses one, the
   file is moved instead and that is recorded.
5. **Mark, replace atomically, mark again.** First a pending marker that
   vouches for both the old bytes and the new ones, then ``os.replace`` of the
   staged file, then the final marker -- which itself refuses to overwrite a
   file that is not a marker of ours. A final marker that cannot be written
   leaves the pending one, so a retry still sees the new copy as ours and only
   finishes its marker; a replace that fails puts the old marker back.

Pruning superseded copies is held to the same standard: one file per call, the
oldest beyond the kept count, only when its marker still matches its bytes, and
never anything that is protected or currently designated.
"""
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import file_retry
from core.hashing import sha256_file_or_none

MARKER_SUFFIX = '.nucleus-build.json'
MARKER_SCHEMA = 'nucleus-playable-copy-v1'
BACKUP_INFIX = '.previous-'

#: One wording for the refusal, wherever it is raised.
FOREIGN_FILE = ("That file isn't one Nucleus made, so I won't write over it. "
                "Pick a new file name.")
CLEAN_SOURCE = ('That is your clean Melee file. Nucleus only ever reads it, and builds your '
                'changes into a separate copy. Pick a different file name for the copy you '
                'play.')
PLAYED_FILE = ('That is the file Slippi Launcher is set to open, and it is not one Nucleus '
               'made. I will not write over it. Pick a new file name for your copy.')

#: Callables returning extra absolute paths that must never be deleted as stale
#: backups -- the destinations the user has designated. Registered by
#: `delivery.destination` so this module needs no import of that layer.
_PROTECTED_PROVIDERS = []


class ProtectedPath(ValueError):
    """This app may not write to that path. Nothing was changed."""


def register_protected_provider(provider):
    """Add a source of paths that must be treated as somebody's live game copy."""
    if provider not in _PROTECTED_PROVIDERS:
        _PROTECTED_PROVIDERS.append(provider)
    return provider


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def normalize(path):
    """A comparable absolute path. Works for files that do not exist yet."""
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(path)))


def same_file(left, right):
    return bool(left) and bool(right) and normalize(left) == normalize(right)


def digest_file(path, *, chunk=1 << 20):
    """SHA-256 of a file as 'sha256:<hex>', or None when it is not there."""
    digest = sha256_file_or_none(path, chunk)
    return None if digest is None else 'sha256:' + digest


def identity_of(path):
    """Cheap file identity: what changes the moment anything writes to it."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns)


# --------------------------------------------------------------------------
# markers
# --------------------------------------------------------------------------

def marker_path(output_path):
    return Path(str(output_path) + MARKER_SUFFIX)


def read_marker(output_path):
    try:
        record = json.loads(marker_path(output_path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get('schema') == MARKER_SCHEMA else None


def write_marker(output_path, payload):
    """Record that this app produced the file at `output_path`.

    Refuses to overwrite a file at the marker's name that is not a marker of
    ours: the rule is about not destroying somebody's file, and a `.json` beside
    their ISO is still their file.
    """
    marker = marker_path(output_path)
    if marker.exists() and read_marker(output_path) is None:
        raise ProtectedPath(
            f'There is already a file called {marker.name} that Nucleus did not write. '
            'I will not replace it. Choose a different name for your copy.')
    record = {'schema': MARKER_SCHEMA, 'written_at': time.time(), **payload}
    temporary = _create_exclusive(marker.parent, lambda: f'{marker.name}.{os.urandom(6).hex()}.part')
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding='utf-8')
    file_retry.replace(temporary, marker)
    return record


def clear_marker(output_path):
    marker = marker_path(output_path)
    if read_marker(output_path) is not None:
        marker.unlink(missing_ok=True)


def produced_by_nucleus(output_path, *, digest=None):
    """Did this app write the file that is there NOW?"""
    file = Path(output_path)
    if not file.is_file():
        return False
    record = read_marker(file) or {}
    # A pending digest is a publish whose final marker was not written yet.
    vouched = {record.get('output_digest'), record.get('pending_digest')} - {None}
    if not vouched:
        return False
    return (digest if digest is not None else digest_file(file)) in vouched


# --------------------------------------------------------------------------
# what is protected
# --------------------------------------------------------------------------

def launcher_iso():
    """Only `settings.isoPath` from the Slippi Launcher config, or None.

    Deliberately narrow: that settings document holds the user's netplay auth
    secret elsewhere, and none of the rest of it belongs anywhere near this.
    """
    try:
        from shared.ingame.boot import read_launcher_settings
        path = ((read_launcher_settings() or {}).get('settings') or {}).get('isoPath')
    except Exception:  # noqa: BLE001 - discovery must never break a write check
        return None
    return str(path) if path else None


def clean_sources():
    """Every path the clean Melee ISO is recorded at. Read-only, always."""
    from core import config
    paths = []
    try:
        from shared.vanilla_extract import vanilla_refs
        current = vanilla_refs.known_vanilla_iso()
        if current:
            paths.append(current)
        try:
            recorded = json.loads(Path(vanilla_refs.ISO_RECORD_PATH).read_text(encoding='utf-8'))
            if recorded.get('path'):
                paths.append(Path(recorded['path']))
        except (OSError, ValueError):
            pass
    except Exception:  # noqa: BLE001 - an unconfigured source protects nothing
        pass
    for name in ('VANILLA_ISO', 'VANILLA_ISO_PATH', 'BASE_ISO'):
        value = getattr(config, name, None)
        if value:
            paths.append(Path(value))
    return {normalize(path) for path in paths}


def designated_outputs():
    """Paths the user has designated as a game copy, from every provider."""
    found = set()
    for provider in _PROTECTED_PROVIDERS:
        try:
            found.update(normalize(path) for path in (provider() or []) if path)
        except Exception:  # noqa: BLE001 - a broken provider must not unprotect anything
            continue
    return found


def protected_paths():
    """Everything that must never be deleted or silently replaced."""
    protected = clean_sources() | designated_outputs()
    played = launcher_iso()
    if played:
        protected.add(normalize(played))
    return protected


# --------------------------------------------------------------------------
# the writable check
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """What was at the destination when it was checked, so it can be rechecked."""
    path: str
    exists: bool
    identity: tuple
    digest: str
    marker: dict


def assert_writable(path, *, allow_launcher_selection=True):
    """May this app write the playable copy at `path`? Raises if not.

    Returns a :class:`Snapshot` of what is there now, to be handed back to
    :func:`reverify` immediately before the write.
    """
    if not path:
        raise ProtectedPath('Choose where your playable copy should live.')
    file = Path(path)
    if not file.is_absolute():
        raise ProtectedPath('The location for your playable copy has to be a full path.')
    if file.suffix.lower() != '.iso':
        raise ProtectedPath('Your playable copy has to be an .iso file.')
    if not file.parent.is_dir():
        raise ProtectedPath(f'The folder for your playable copy does not exist: {file.parent}')
    if normalize(file) in clean_sources():
        raise ProtectedPath(CLEAN_SOURCE)
    ours = produced_by_nucleus(file)
    # The Launcher's configured ISO is refused even when it is not there yet:
    # the user is about to point that file at a game, and a missing path is not
    # permission to create ours in its place.
    played = launcher_iso()
    if allow_launcher_selection and played and same_file(file, played) and not ours:
        raise ProtectedPath(PLAYED_FILE)
    if file.exists() and not file.is_file():
        raise ProtectedPath('That path is not a file.')
    if file.is_file() and not ours:
        raise ProtectedPath(FOREIGN_FILE)
    # The marker's own name has to be free too, and it is checked HERE rather
    # than at the end: refusing after the replace would leave the user's game
    # copy holding new bytes with nothing to say they are ours.
    marker = marker_path(file)
    if marker.exists() and read_marker(file) is None:
        raise ProtectedPath(
            f'There is already a file called {marker.name} that Nucleus did not write. '
            'I will not replace it. Choose a different name for your copy.')
    return Snapshot(path=str(file), exists=file.is_file(), identity=identity_of(file),
                    digest=digest_file(file) if file.is_file() else None,
                    marker=read_marker(file) or {})


def reverify(snapshot):
    """Re-check a destination immediately before writing to it.

    Cheap when nothing touched it: the stat identity is enough to say so. When
    the identity changed, the full ownership check runs again, because whatever
    is there now is a different file and may not be ours.
    """
    file = Path(snapshot.path)
    identity = identity_of(file)
    if identity == snapshot.identity:
        return snapshot
    return assert_writable(snapshot.path)


# --------------------------------------------------------------------------
# exclusive allocation
# --------------------------------------------------------------------------

def _create_exclusive(directory, name_factory, attempts=8):
    """Create a new empty file under a name nothing else holds. Never replaces."""
    directory = Path(directory)
    for _ in range(attempts):
        candidate = directory / name_factory()
        if normalize(candidate) in protected_paths():
            continue
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        os.close(descriptor)
        return candidate
    raise ProtectedPath('Could not reserve a free filename beside your game copy.')


def reserve_backup(output_path, label=''):
    """A free `<stem>.previous-<id>.iso` beside the output, created exclusively."""
    output = Path(output_path)
    tag = (label or '')[:40]

    def name():
        return f'{output.stem}{BACKUP_INFIX}{tag}{os.urandom(4).hex()}{output.suffix}'

    return _create_exclusive(output.parent, name)


# --------------------------------------------------------------------------
# publishing
# --------------------------------------------------------------------------

def publish(source, output, *, marker, expect_digest=None, keep_backups=1,
            backup_label='', on_backup=None):
    """Put `source`'s bytes at `output`, atomically, without destroying anything.

    Args:
        source: the finished disc image to publish.
        output: the user's designated playable copy.
        marker: extra fields for the ownership marker (project, receipt, …).
        expect_digest: the digest the source was VERIFIED at. A source whose
            bytes no longer match what was checked is refused: verification has
            to stay authoritative all the way to the write.
        keep_backups: how many superseded copies to keep beside the output.
        on_backup: called with the backup record as soon as it exists and
            before the destination is replaced, so a caller can journal the
            restoration location before the destructive step.

    Returns:
        ``{'output': {...}, 'backup': {...}|None, 'backup_moved': bool}``.

    Raises:
        ProtectedPath: the destination is not ours to write, or changed under us.
    """
    source, output = Path(source), Path(output)
    if not source.is_file():
        # A missing SOURCE is a failed operation, not a refusal to write: the
        # caller reports "the build disappeared", which is a different sentence
        # and a different thing for the user to do about it.
        raise FileNotFoundError(2, 'the build is no longer in the output folder', str(source))
    source_digest = digest_file(source)
    if expect_digest and source_digest != expect_digest:
        raise ProtectedPath('The build changed after it was checked, so it was not published. '
                            'Build it again.')
    snapshot = assert_writable(output)
    if snapshot.exists and snapshot.digest == source_digest \
            and snapshot.marker.get('pending_digest') == source_digest:
        # An earlier publish of these bytes replaced the file but could not
        # write its final marker: finish that one instead of copying again.
        write_marker(output, {**marker, 'output_digest': source_digest})
        return {'output': {'path': str(output), 'digest': source_digest,
                           'bytes': output.stat().st_size},
                'backup': None, 'pruned': prune_backups(output, keep=keep_backups)}

    staged = _create_exclusive(output.parent, lambda: f'{output.name}.{os.urandom(6).hex()}.part')
    backup = None
    moved = False
    pending = False
    try:
        # `shutil.copyfile` rather than a hand-rolled loop: it is the call the
        # app's own save path has always used, and the one its failure tests
        # (antivirus holding the destination, the source vanishing mid-copy)
        # exercise. The target was created exclusively just above, so writing
        # over it replaces only our own empty placeholder.
        shutil.copyfile(source, staged)
        if digest_file(staged) != source_digest:
            raise ProtectedPath('The copy written beside your game file does not match the '
                                'build, so it was thrown away and nothing was replaced.')
        # Somebody may have replaced the destination while that copy ran.
        snapshot = reverify(snapshot)
        if snapshot.exists:
            reserved = reserve_backup(output, backup_label)
            try:
                # A hard link keeps the old bytes alive under a second name
                # without copying them, so the playable path never stops being
                # the old game until the replace below succeeds.
                os.unlink(reserved)
                os.link(output, reserved)
            except OSError:
                file_retry.replace(output, reserved)
                moved = True
            backup = {'path': str(reserved), 'digest': snapshot.digest,
                      'bytes': Path(reserved).stat().st_size, 'moved': moved}
            if snapshot.marker:
                kept = {k: v for k, v in snapshot.marker.items() if k != 'pending_digest'}
                write_marker(reserved, {**kept, 'output_digest': snapshot.digest,
                                        'superseded_at': time.time()})
            if on_backup is not None:
                on_backup(dict(backup))
        # Vouch for the bytes about to land BEFORE they land: if the final
        # marker below cannot be written, our own new copy must not look like
        # somebody else's file to the next save.
        write_marker(output, {**marker, 'output_digest': snapshot.digest,
                              'pending_digest': source_digest})
        pending = True
        file_retry.replace(staged, output)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        if moved and backup and not Path(output).exists():
            # The replace failed after the old copy was moved: put it straight
            # back, so the path the user launches is never left empty.
            try:
                file_retry.replace(backup['path'], output)
            except OSError:
                pass
        if pending:
            # Nothing was replaced: the marker goes back to what it said.
            try:
                if snapshot.marker:
                    write_marker(output, snapshot.marker)
                else:
                    clear_marker(output)
            except (OSError, ProtectedPath):
                pass
        raise
    write_marker(output, {**marker, 'output_digest': source_digest})
    pruned = prune_backups(output, keep=keep_backups)
    return {'output': {'path': str(output), 'digest': source_digest,
                       'bytes': output.stat().st_size},
            'backup': backup, 'pruned': pruned}


def prune_backups(output_path, keep=1):
    """Delete at most ONE superseded copy, and only when it is provably ours.

    Held to the same standard as a write: the file must carry a marker whose
    digest still matches its bytes, and must not be a clean source, the file the
    Launcher opens, or anything currently designated. Anything else is left
    exactly where it is, whatever its name looks like.
    """
    output = Path(output_path)
    protected = protected_paths()
    candidates = []
    for path in output.parent.glob(f'{output.stem}{BACKUP_INFIX}*{output.suffix}'):
        if normalize(path) in protected or same_file(path, output):
            continue
        record = read_marker(path)
        if not record or record.get('output_digest') != digest_file(path):
            continue                      # a stale marker is not ownership
        candidates.append(path)
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    stale = candidates[max(keep, 0):]
    if not stale:
        return []
    oldest = stale[-1]
    oldest.unlink(missing_ok=True)
    clear_marker(oldest)
    return [str(oldest)]


def restore(backup, output, *, marker, expect_digest=None):
    """Put a preserved copy back at `output`, through the same publisher."""
    return publish(backup, output, marker={**marker, 'restored': True},
                   expect_digest=expect_digest, backup_label='undo-')
