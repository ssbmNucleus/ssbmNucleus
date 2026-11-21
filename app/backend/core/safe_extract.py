"""One shared archive extractor: component containment + a cumulative budget.

Two defects this module exists to close, both found in the 2026-09-22 security
review of the website download path:

* **Containment.** Several import paths checked ``str(target).startswith(root)``
  after joining an attacker-controlled member name. That is a string prefix
  test, not path ancestry: with a root of ``.../custom_characters/review`` a
  member named ``../review-target/fighter.json`` resolves to a *sibling*
  folder whose path still starts with the root string, so the check passed and
  the write landed on somebody else's character. Every member here is split
  into normalized components and each component is validated on its own, so
  ``..``, absolute paths, drive letters, reserved Windows device names and
  trailing dots/spaces can never reach the filesystem. Links and reparse
  points are refused both as archive members and as pre-existing path
  components of the destination.

* **Budget.** Each archive layer used to check only its own declared sizes, so
  a small outer ZIP could carry a nested package whose members expanded to
  gigabytes. A :class:`Budget` is created once per user-visible operation and
  passed down through classification, nested archives and every package
  converter, so bytes, members, nesting depth and wall-clock time are counted
  across the whole operation rather than per layer.

Nothing here writes outside the destination it is handed, and every extraction
completes its preflight before the first byte is written.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

import file_retry
from core.path_safety import _WINDOWS_RESERVED_STEMS

__all__ = [
    'ArchiveBudgetExceeded', 'Budget', 'DestinationExists', 'PreparedMember',
    'UnsafeArchiveMember', 'archive_identity', 'assert_trusted_root',
    'destination_key', 'reserve_directory',
    'DANGEROUS_SUFFIXES', 'dangerous_members', 'extract_zip', 'is_safe_member_name',
    'extract_zip_to_new_directory', 'member_parts', 'new_budget',
    'preflight_zip', 'staged_directory',
]


class UnsafeArchiveMember(ValueError):
    """An archive member whose name could escape or hijack its destination.

    Carries the offending member, the reason and the action as separate
    fields. Importer boundaries forward `str(exc)`, so the sentence must never
    contain a local absolute path: what went wrong is a property of the
    ARCHIVE, and where we happened to be writing is the user's own business.
    """

    def __init__(self, reason, *, member=None, action=None):
        self.member = _display(member)
        self.reason = reason
        self.action = action or _REMEDY
        super().__init__(self.sentence())

    def sentence(self):
        subject = f'the entry "{self.member}"' if self.member else 'this archive'
        return (f'This archive is not safe to extract: {subject} '
                f'{self.reason}. {self.action}')

    def as_dict(self):
        return {'error': 'unsafe_archive_member', 'member': self.member,
                'reason': self.reason, 'action': self.action,
                'message': self.sentence()}


class ArchiveBudgetExceeded(ValueError):
    """The operation's cumulative byte/member/depth/time budget ran out."""


# Extensions that never belong in a Melee mod and that Windows will happily
# execute. Content carrying these is reported so the approval can refuse it;
# the extractor itself does not silently drop members.
DANGEROUS_SUFFIXES = frozenset({
    '.exe', '.com', '.scr', '.pif', '.cpl', '.msi', '.msp', '.msc', '.dll',
    '.bat', '.cmd', '.ps1', '.psm1', '.vbs', '.vbe', '.js', '.jse', '.wsf',
    '.wsh', '.hta', '.jar', '.lnk', '.url', '.reg', '.sh', '.app', '.deb',
    '.pkg', '.dmg', '.sys', '.drv',
})

MAX_PATH_DEPTH = 32

# A member that is itself an archive is charged for the BLOB WE WILL READ --
# its packed size -- rather than for its declared expansion, which its own
# preflight charges accurately the moment it is opened. Counting both made an
# ordinary nested package cost twice what it expands to. Skipping the charge
# entirely, as the first attempt did, meant a member advertising 1 GiB passed
# preflight with zero bytes charged and identification then read it
# (2026-09-22 review JJ, 1): the per-member cap and the ratio rule apply to
# every member, archive or not.
NESTED_ARCHIVE_SUFFIXES = frozenset({'.zip', '.7z', '.rar'})

# Characters Windows refuses in a filename. `:` is handled separately (drive
# letters and alternate data streams have their own message).
_WINDOWS_ILLEGAL = '<>"|?*'

# An 8.3 short alias (`LONGFI~1.DAT`). A member may not name one: the alias of
# a long name the same archive also carries resolves to the SAME file, so two
# members that look distinct silently become one write over another. Real mod
# archives never contain them.
_SHORT_ALIAS = re.compile(r'~\d', re.ASCII)

# Defaults for one LOCAL operation (a file the user picked themselves). They
# match core.safe_archive.DEFAULT_LIMITS, which these paths already enforced.
# The chat download path builds a much tighter budget of its own -- see
# website.website_safety.download_budget.
DEFAULT_MAX_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 50_000
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_SECONDS = 900.0
DEFAULT_MAX_RATIO = 500


# ── member name containment ────────────────────────────────────────────────

_REMEDY = ("Nucleus only writes a mod's own files inside its own folder. "
           'Re-export it from Nucleus, or ask whoever published it for a '
           'clean package.')

_UNPRINTABLE = re.compile(r'[\x00-\x1f\x7f]')


def _display(name):
    """A member name safe to put in a message: escaped, bounded, no local path.

    The name comes from the archive, so it can carry control characters, bidi
    overrides, or several hundred characters of noise. It is shown because the
    user needs to know WHICH entry was refused.
    """
    if not isinstance(name, str) or not name:
        return ''
    cleaned = _UNPRINTABLE.sub('?', name).replace('"', "'")
    return cleaned[:120] + ('...' if len(cleaned) > 120 else '')


def _bad(name, reason, action=None):
    """A refusal a person can act on: which entry, what is wrong, what to do."""
    return UnsafeArchiveMember(reason, member=name, action=action)


def member_parts(name, *, max_depth=MAX_PATH_DEPTH):
    """Normalized, individually validated path components of an archive member.

    Raises :class:`UnsafeArchiveMember` for anything that could leave the
    destination directory or name a device/reserved path on Windows. A
    directory member keeps its components; the trailing separator is dropped.
    """
    if not isinstance(name, str) or not name:
        raise _bad(name, 'has no name')
    if '\x00' in name:
        raise _bad(name, 'contains a NUL byte')
    normalized = name.replace('\\', '/')
    if normalized.startswith('//'):
        raise _bad(name, 'is a UNC network path')
    windows = PureWindowsPath(name)
    posix = PurePosixPath(normalized)
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        raise _bad(name, 'is an absolute path')
    parts = tuple(part for part in posix.parts if part not in ('', '.'))
    if not parts:
        raise _bad(name, 'has no usable path components')
    if len(parts) > max_depth:
        raise _bad(name, 'is nested too deeply')
    for part in parts:
        if part == '..':
            raise _bad(name, 'walks up out of the destination folder')
        if ':' in part:
            raise _bad(name, 'names a drive or an alternate data stream')
        if part != part.rstrip(' .'):
            raise _bad(name, 'ends a folder or file name with a dot or space')
        if any(ord(char) < 32 or ord(char) == 127 for char in part):
            raise _bad(name, 'contains a control character')
        if any(char in _WINDOWS_ILLEGAL for char in part):
            raise _bad(name, 'contains a character Windows cannot put in a filename')
        if _SHORT_ALIAS.search(part):
            raise _bad(name, 'looks like an 8.3 short-name alias, which can '
                             'resolve to another entry in the same archive')
        # NFKC first: `COM\u00b9` is a reserved device name that a plain
        # uppercase comparison does not recognise.
        stem = unicodedata.normalize('NFKC', part).split('.', 1)[0].upper()
        if stem in _WINDOWS_RESERVED_STEMS:
            raise _bad(name, 'uses a reserved Windows device name')
    return parts


def destination_key(parts):
    """The identity a Windows filesystem gives this path.

    Two members whose keys match land on the same file however different their
    names look, so the member set is checked for collisions as a set rather
    than one name at a time.
    """
    return tuple(unicodedata.normalize('NFKC', part).casefold() for part in parts)


def is_safe_member_name(name, *, max_depth=MAX_PATH_DEPTH):
    """True when :func:`member_parts` accepts this member name."""
    try:
        member_parts(name, max_depth=max_depth)
    except UnsafeArchiveMember:
        return False
    return True


def _is_link(path):
    """True for a symlink or any other reparse point (Windows junctions)."""
    try:
        info = os.lstat(path)
    except (OSError, ValueError):
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, 'st_file_attributes', 0)
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def assert_trusted_root(root):
    """The destination must be a real directory, not a link into one.

    A junction supplied AS the extraction root was previously accepted and
    written through: every per-member check asks about components BELOW the
    root, so the root itself was never examined (2026-09-22 re-review, 8).
    """
    root = Path(root)
    if _is_link(root):
        raise UnsafeArchiveMember(
            'is a link rather than a real folder',
            member=None,
            action='Extraction roots must be ordinary folders. Remove the link '
                   'and try again.')
    if root.exists() and not root.is_dir():
        raise UnsafeArchiveMember('already exists and is not a folder', member=None)
    return root


def _resolve_under(root: Path, parts):
    """Join validated components under `root`, refusing links on the way down."""
    current = root
    for part in parts:
        current = current / part
        if _is_link(current):
            raise _bad('/'.join(parts), 'would be written through a link')
    resolved = current.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise _bad('/'.join(parts), 'resolves outside the destination folder') from exc
    return current


# ── cumulative budget ──────────────────────────────────────────────────────

@dataclass
class Budget:
    """Bytes, members, nesting depth and time for ONE user-visible operation.

    Create it once at the entry point and hand the same instance to every
    classifier, nested-archive reader and package converter the operation
    touches. Counters only ever go up, so a chain of nested archives cannot
    each spend the full allowance.
    """

    max_bytes: int = DEFAULT_MAX_BYTES
    max_members: int = DEFAULT_MAX_MEMBERS
    max_depth: int = DEFAULT_MAX_DEPTH
    max_seconds: float = DEFAULT_MAX_SECONDS
    max_member_bytes: int | None = None     # None: the whole allowance
    max_compression_ratio: int = DEFAULT_MAX_RATIO
    used_bytes: int = 0
    used_members: int = 0
    depth: int = 0
    accounted: set = field(default_factory=set)
    started: float = field(default_factory=time.monotonic)
    message: str = ('This download exceeds the archive safety limits. '
                    'Nothing was imported.')

    # -- queries --------------------------------------------------------
    @property
    def remaining_bytes(self):
        return max(0, self.max_bytes - self.used_bytes)

    @property
    def remaining_members(self):
        return max(0, self.max_members - self.used_members)

    def check_time(self):
        if time.monotonic() - self.started > self.max_seconds:
            raise ArchiveBudgetExceeded(self.message)

    # -- spending -------------------------------------------------------
    def charge_members(self, count):
        self.check_time()
        self.used_members += int(count)
        if self.used_members > self.max_members:
            raise ArchiveBudgetExceeded(self.message)

    def charge_bytes(self, size):
        self.check_time()
        size = int(size)
        if size < 0:
            raise ArchiveBudgetExceeded(self.message)
        self.used_bytes += size
        if self.used_bytes > self.max_bytes:
            raise ArchiveBudgetExceeded(self.message)

    @contextmanager
    def nested(self):
        """Descend one archive level; raises when the nesting cap is reached."""
        if self.depth + 1 > self.max_depth:
            raise ArchiveBudgetExceeded(self.message)
        self.depth += 1
        try:
            yield self
        finally:
            self.depth -= 1

    def account_archive(self, identity, occurrence=None):
        """Claim one archive OCCURRENCE's expansion. False if already counted.

        Replaces the caller-controlled `rewind()`. Classification, the safety
        preflight and the import all walk the SAME archives; charging each
        visit made a legitimate download fail at a fraction of the advertised
        allowance, and zeroing the counters between passes was accounting by
        trust.

        The key is (content, occurrence), not content alone: re-reading one
        physical archive is free, but two SIBLING members with identical bytes
        are two extractions and cost twice -- keying on content alone let two
        identical 3 MiB siblings through a 4.5 MiB cap (2026-09-22 review JJ,
        1).
        """
        self.check_time()
        key = (identity, occurrence or '')
        if key in self.accounted:
            return False
        self.accounted.add(key)
        return True

    def member_limit(self):
        """The per-member cap, defaulting to the whole operation's allowance."""
        return self.max_bytes if self.max_member_bytes is None else self.max_member_bytes

    def check_member_size(self, size, compressed=None, *, name=''):
        """Apply the per-member cap and the ratio rule. Charges nothing.

        Separated from charging because an ARCHIVE member is charged for its
        packed blob but must still be refused outright when it advertises more
        than one member may expand to.
        """
        size = int(size)
        if size < 0 or size > self.member_limit():
            raise ArchiveBudgetExceeded(self.message)
        if size > 1024 * 1024 and compressed is not None:
            if compressed <= 0 or size > compressed * self.max_compression_ratio:
                raise ArchiveBudgetExceeded(
                    self.message + ' (' + (name or 'a member')
                    + ' has an unsafe compression ratio)')
        return size

    def charge_member_size(self, size, compressed=None, *, name='', charge=None):
        """Check one member, then charge `charge` bytes (its size by default).

        This is the single definition of the size policy -- core.safe_archive
        reads it from here.
        """
        size = self.check_member_size(size, compressed, name=name)
        self.charge_bytes(size if charge is None else max(0, int(charge)))

    def archive_limits(self):
        """`core.safe_archive.ArchiveLimits` scaled to what is left.

        Lets the py7zr/RAR preflights, which run inside third-party
        extractors, share this operation's remaining allowance. Both modules
        share one containment policy: core.safe_archive's member check
        delegates to `member_parts` here.
        """
        from core.safe_archive import ArchiveLimits
        return ArchiveLimits(
            max_entries=max(1, self.remaining_members),
            max_total_bytes=max(1, self.remaining_bytes),
            max_member_bytes=max(1, min(self.member_limit(), self.remaining_bytes)),
            max_compression_ratio=self.max_compression_ratio,
        )


def new_budget(**overrides):
    """A fresh :class:`Budget` for one operation."""
    return Budget(**overrides)


# ── ZIP preflight and extraction ───────────────────────────────────────────

@dataclass(frozen=True)
class PreparedMember:
    name: str
    parts: tuple
    size: int
    is_dir: bool
    mode: int = 0


def _member_mode(info):
    return (info.external_attr >> 16) & 0xFFFF


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _member_is_link(info):
    """True for a POSIX symlink entry OR a Windows reparse-point entry.

    A ZIP carries the Unix mode in the high half of external_attr and the
    Windows file attributes in the low half. Checking only S_ISLNK accepted an
    entry flagged FILE_ATTRIBUTE_REPARSE_POINT.
    """
    if stat.S_ISLNK(_member_mode(info)):
        return True
    return bool(info.external_attr & _FILE_ATTRIBUTE_REPARSE_POINT)


def archive_identity(zf):
    """A stable id for an open ZipFile, from its central directory alone.

    No payload is read: the member names, sizes, CRCs and header offsets are
    what distinguishes one archive from another, and they are already in
    memory. Two visits to the same archive share an identity; a different
    archive never does.
    """
    digest = hashlib.sha256()
    for info in zf.infolist():
        digest.update(repr((info.filename, info.file_size, info.compress_size,
                            info.CRC, info.header_offset)).encode('utf-8', 'replace'))
    return digest.hexdigest()


def preflight_zip(zf, *, budget, skip=(), members=None,
                  max_depth=MAX_PATH_DEPTH, charge=True, occurrence=None):
    """Validate EVERY selected member of an open ZipFile. Writes nothing.

    Returns the prepared members. Raises :class:`UnsafeArchiveMember` or
    :class:`ArchiveBudgetExceeded`; either way the caller has not touched the
    filesystem yet.

    The WHOLE member set is checked, not each name in turn: two entries that a
    Windows filesystem would land on the same file, or a name used as both a
    file and a folder, are a collision and are refused.
    """
    skipped = set(skip)
    selected = set(members) if members is not None else None
    infos = [info for info in zf.infolist()
             if info.filename not in skipped
             and (selected is None or info.filename in selected)]
    if selected is not None and {info.filename for info in infos} != selected:
        raise UnsafeArchiveMember('is missing a member the importer needs',
                                  member=sorted(selected - {i.filename for i in infos})[0]
                                  if selected - {i.filename for i in infos} else None)
    # One expansion per distinct archive OCCURRENCE, however many passes look
    # at it. The occurrence is a LOGICAL ancestry -- '' for the object the
    # operation is about, then '!<member>' per level -- never a filesystem
    # path: deriving it from temporary extraction directories made the same
    # nested archive a different occurrence on every pass, and a real nested
    # costume export was charged three times over (2026-09-22 review MM, 2).
    place = occurrence or ''
    if charge and not budget.account_archive(archive_identity(zf), place):
        charge = False
    if charge:
        budget.charge_members(len(infos))
    else:
        budget.check_time()

    prepared = []
    files, directories = {}, set()
    for info in infos:
        parts = member_parts(info.filename, max_depth=max_depth)
        mode = _member_mode(info)
        if _member_is_link(info):
            raise _bad(info.filename, 'is a link, and archive links are not allowed')
        is_dir = info.is_dir()
        size = 0 if is_dir else int(info.file_size)
        if not is_dir:
            if size < 0:
                raise _bad(info.filename, 'declares a negative size')
            if charge:
                nested = PurePosixPath(parts[-1]).suffix.lower() in NESTED_ARCHIVE_SUFFIXES
                budget.charge_member_size(
                    size, info.compress_size, name=info.filename,
                    # An archive member is CHECKED here -- the per-member cap
                    # and the ratio rule decide whether we may read it at all
                    # -- but what it expands to is charged by its own
                    # preflight, so charging the packed blob as well would
                    # make an ordinary nested package cost twice over.
                    charge=0 if nested else None)
        key = destination_key(parts)
        if is_dir:
            directories.add(key)
        else:
            if key in files:
                raise _bad(info.filename,
                           f'lands on the same file as "{_display(files[key])}"',
                           action='Two entries cannot write the same file. Ask '
                                  'whoever published it for a clean package.')
            files[key] = info.filename
        prepared.append(PreparedMember(info.filename, parts, size, is_dir, mode))

    # A name used as a file AND as a folder (or as a parent of another member)
    # cannot both exist; whichever wins depends on extraction order.
    parents = {key[:n] for key in files for n in range(1, len(key))}
    clash = (directories | parents) & set(files)
    if clash:
        offender = next(iter(clash))
        raise _bad(files[offender], 'is used as both a file and a folder',
                   action='Ask whoever published it for a clean package.')
    return prepared


def dangerous_members(names):
    """Member names whose extension Windows would treat as executable."""
    found = []
    for name in names:
        try:
            parts = member_parts(name)
        except UnsafeArchiveMember:
            found.append(name)
            continue
        if PurePosixPath(parts[-1]).suffix.lower() in DANGEROUS_SUFFIXES:
            found.append(name)
    return found


def _copy_member(zf, info_name, target, expected, budget=None):
    remaining = expected
    with zf.open(info_name, 'r') as source, open(target, 'wb') as output:
        while remaining:
            if budget is not None:
                # A single huge member is still one member: without this the
                # time budget could only be observed between members.
                budget.check_time()
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise UnsafeArchiveMember(
                    f'archive member {info_name!r} ended before its declared size')
            output.write(chunk)
            remaining -= len(chunk)
        if source.read(1):
            raise UnsafeArchiveMember(
                f'archive member {info_name!r} exceeds its declared size')


def extract_zip(zf, destination, *, budget, skip=(), members=None,
                contents=None, max_depth=MAX_PATH_DEPTH, charge=True):
    """Preflight the whole archive, then write it under `destination`.

    `contents` optionally maps a member name to replacement bytes (the audio
    normalization the character restore does). Returns {member name: path}.
    """
    prepared = preflight_zip(zf, budget=budget, skip=skip, members=members,
                             max_depth=max_depth, charge=charge)
    root = assert_trusted_root(destination)
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()
    written = {}
    overrides = contents or {}
    for member in prepared:
        budget.check_time()
        target = _resolve_under(root_resolved, member.parts)
        if member.is_dir:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if _is_link(target):
            raise _bad(member.name, 'already exists at the destination as a link')
        if member.name in overrides:
            target.write_bytes(overrides[member.name])
        else:
            _copy_member(zf, member.name, target, member.size, budget)
        permissions = stat.S_IMODE(member.mode)
        if permissions and os.name != 'nt':
            target.chmod(permissions)
        written[member.name] = target
    return written


class DestinationExists(ValueError):
    """The folder an import wanted to create is already there."""


def reserve_directory(final_dir):
    """Atomically claim `final_dir` as OURS, or raise DestinationExists.

    `mkdir()` without `exist_ok` is the reservation: on every filesystem we
    support it either creates the directory or fails, so two concurrent
    imports that deduplicated to the same slug cannot both believe they own
    it. The caller removes it if the import does not complete.
    """
    final_dir = Path(final_dir)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    assert_trusted_root(final_dir.parent)
    try:
        final_dir.mkdir()
    except FileExistsError as exc:
        raise DestinationExists(
            'Another item already occupies that place in the vault. Rename or '
            'remove it, then import again.') from exc
    return final_dir


@contextmanager
def staged_directory(final_dir, *, prefix='.staging-', replace=False):
    """A fresh staging folder committed onto `final_dir` only on success.

    The staging folder is a sibling of the destination so the commit is a
    same-filesystem rename, and the destination must NOT already exist. The
    previous version replaced an existing destination item by item: a failure
    partway through left new bytes in one file, the original of another
    deleted, and staging behind -- the opposite of the rollback this promises
    (2026-09-22 re-review, 4). An existing destination is now a refusal the
    caller has to resolve, and `replace=True` is accepted only for a
    destination this call reserved itself.
    """
    final_dir = Path(final_dir)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    assert_trusted_root(final_dir.parent)
    if final_dir.exists() and not replace:
        raise DestinationExists(
            'Another item already occupies that place in the vault. Rename or '
            'remove it, then import again.')
    if _is_link(final_dir):
        raise UnsafeArchiveMember('already exists as a link', member=None)
    staging = final_dir.parent / f'{prefix}{final_dir.name}-{os.getpid()}-{time.monotonic_ns():x}'
    if staging.exists():  # pragma: no cover - a collision needs the same ns
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        yield staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if final_dir.exists():
        # Only a destination we reserved ourselves reaches here, and it is
        # empty or ours: swap it aside, put the staged tree in place, then
        # drop the old one. A failure at any step leaves exactly one complete
        # tree in place.
        previous = final_dir.parent / f'{prefix}old-{final_dir.name}-{time.monotonic_ns():x}'
        file_retry.replace(final_dir, previous)
        try:
            file_retry.replace(staging, final_dir)
        except BaseException:
            file_retry.replace(previous, final_dir)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(previous, ignore_errors=True)
    else:
        file_retry.replace(staging, final_dir)


def extract_zip_to_new_directory(zf, final_dir, *, budget, skip=(), members=None,
                                 contents=None, max_depth=MAX_PATH_DEPTH, charge=True,
                                 replace=False):
    """Validate everything, extract into a fresh staging folder, then commit.

    `final_dir` must not already exist unless `replace=True`, which the caller
    passes only for a destination it reserved with `reserve_directory`.

    `charge=False` when the caller already preflighted this same archive
    against the same budget. (Budget accounting is keyed to the archive's own
    identity as well, so a repeat visit is free either way.)
    """
    with staged_directory(final_dir, replace=replace) as staging:
        written = extract_zip(zf, staging, budget=budget, skip=skip, members=members,
                              contents=contents, max_depth=max_depth, charge=charge)
    return {name: Path(final_dir).joinpath(*member_parts(name, max_depth=max_depth))
            for name in written}
