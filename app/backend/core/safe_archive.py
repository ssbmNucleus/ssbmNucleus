"""Bounded 7z / RAR extraction for the desktop import paths.

There is ONE containment policy and ONE size policy in the codebase, and they
live in :mod:`core.safe_extract`. This module is the format-specific layer for
the archives whose extraction happens inside a third-party extractor (py7zr,
UnRAR), so its job is the preflight: every member name is validated by
`safe_extract.member_parts` and every declared size by a `safe_extract.Budget`
built from the caller's :class:`ArchiveLimits`. ZIP extraction is
`safe_extract.extract_zip` itself -- `safe_extract_zip` below is the
back-compatible spelling of that one call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int = 50_000
    max_total_bytes: int = 16 * 1024 * 1024 * 1024
    max_member_bytes: int = 4 * 1024 * 1024 * 1024
    max_compression_ratio: int = 500
    max_path_depth: int = 32


DEFAULT_LIMITS = ArchiveLimits()


def _safe_parts(name: str, limits: ArchiveLimits) -> tuple[str, ...]:
    """The shared containment policy (core.safe_extract.member_parts).

    Delegating means 7z/RAR members get the same reserved-name,
    trailing-dot, drive-letter and UNC checks that ZIP members get, instead of
    the weaker local copy this module used to carry.
    """
    from core.safe_extract import member_parts
    return member_parts(name, max_depth=limits.max_path_depth)


def _target(destination: Path, parts: tuple[str, ...]) -> Path:
    from core.safe_extract import _resolve_under
    return _resolve_under(destination.resolve(), parts)


def budget_for(limits: ArchiveLimits):
    """A core.safe_extract.Budget expressing these limits."""
    from core.safe_extract import Budget
    return Budget(max_bytes=limits.max_total_bytes, max_members=limits.max_entries,
                  max_member_bytes=limits.max_member_bytes,
                  max_compression_ratio=limits.max_compression_ratio,
                  message="archive exceeds the total extraction limit")


def _check_size(total: int, size: int, compressed: int | None,
                limits: ArchiveLimits) -> int:
    """Size policy, delegated to the shared Budget so there is one copy of it."""
    budget = budget_for(limits)
    budget.used_bytes = total
    budget.charge_member_size(size, compressed)
    return budget.used_bytes


def safe_extract_zip(
    archive,
    destination,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
    skip: Iterable[str] = (),
    members: Iterable[str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    budget=None,
) -> None:
    """Validate an open ZipFile completely, then extract selected members.

    Back-compatible spelling of `core.safe_extract.extract_zip`; pass `budget`
    to spend the caller's cumulative allowance instead of a fresh one.
    """
    from core.safe_extract import extract_zip, preflight_zip
    budget = budget or budget_for(limits)
    if progress is None:
        extract_zip(archive, destination, budget=budget, skip=skip, members=members,
                    max_depth=limits.max_path_depth)
        return
    prepared = preflight_zip(archive, budget=budget, skip=skip, members=members,
                             max_depth=limits.max_path_depth)
    count = len(prepared)
    for index, member in enumerate(prepared, 1):
        extract_zip(archive, destination, budget=budget, members={member.name},
                    max_depth=limits.max_path_depth, charge=False)
        progress(index, count, member.name)


# Every way a py7zr entry can say "I am not an ordinary file". Only regular
# files and directories are extracted; anything else is refused rather than
# handed to py7zr's extractor, which would materialise it.
_SEVENZIP_LINK_FLAGS = ("is_symlink", "is_junction", "is_socket", "is_block_device",
                        "is_character_device", "is_fifo")


def _flag(info, name) -> bool:
    """Read a py7zr FileInfo flag whether it is an attribute or a method."""
    value = getattr(info, name, False)
    if callable(value):
        try:
            value = value()
        except Exception:           # noqa: BLE001 - an unreadable flag is not a pass
            return True
    return bool(value)


def _solid_aware_packed(info, previous_packed) -> int | None:
    """The packed size to use for the ratio check, or None when unknowable.

    In a SOLID 7z block every member after the first reports no compressed
    size of its own -- the block is shared. Treating that as zero refused an
    ordinary two-file solid archive outright. `None` means "the ratio cannot
    be computed here"; the absolute per-member and total caps still apply.
    """
    packed = getattr(info, "compressed", None)
    if packed is None:
        return None
    packed = int(packed or 0)
    return packed if packed > 0 else None


def safe_extract_7z(archive, destination, *,
                    limits: ArchiveLimits = DEFAULT_LIMITS, budget=None) -> None:
    """Preflight a py7zr archive before using its extractor."""
    from core.safe_extract import assert_trusted_root
    infos = archive.list()
    if len(infos) > limits.max_entries:
        raise ValueError("archive contains too many entries")
    total_bytes = 0
    previous_packed = None
    for info in infos:
        _safe_parts(info.filename, limits)
        if any(_flag(info, flag) for flag in _SEVENZIP_LINK_FLAGS):
            raise ValueError("archive links are not allowed")
        is_directory = _flag(info, "is_directory")
        if not is_directory and hasattr(info, "is_file") and not _flag(info, "is_file"):
            raise ValueError("archive contains an entry that is not a regular file")
        if not is_directory:
            total_bytes = _check_size(
                total_bytes,
                int(getattr(info, "uncompressed", 0) or 0),
                _solid_aware_packed(info, previous_packed),
                limits,
            )
    if budget is not None:
        budget.charge_members(len(infos))
        budget.charge_bytes(total_bytes)
    destination = assert_trusted_root(destination)
    Path(destination).mkdir(parents=True, exist_ok=True)
    archive.extractall(path=destination)


def safe_extract_rar(archive, destination, *,
                     limits: ArchiveLimits = DEFAULT_LIMITS, budget=None) -> None:
    """Preflight a rarfile archive before using its extractor.

    UnRAR does the actual extraction, so this is the only place the member
    paths and sizes are checked against our own limits.
    """
    infos = archive.infolist()
    if len(infos) > limits.max_entries:
        raise ValueError("archive contains too many entries")
    total_bytes = 0
    for info in infos:
        _safe_parts(info.filename, limits)
        is_symlink = getattr(info, "is_symlink", None)
        if is_symlink is not None and is_symlink():
            raise ValueError("archive links are not allowed")
        if not info.is_dir():
            # A solid RAR block can report a packed size of 0 for members
            # after the first. That is normal, not a bomb, so the ratio check
            # is skipped there and the hard size caps carry the weight.
            packed = int(getattr(info, "compress_size", 0) or 0)
            total_bytes = _check_size(
                total_bytes,
                int(getattr(info, "file_size", 0) or 0),
                packed if packed > 0 else None,
                limits,
            )
    if budget is not None:
        budget.charge_members(len(infos))
        budget.charge_bytes(total_bytes)
    from core.safe_extract import assert_trusted_root
    destination = assert_trusted_root(destination)
    Path(destination).mkdir(parents=True, exist_ok=True)
    archive.extractall(path=destination)
