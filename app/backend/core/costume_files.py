"""
Helpers for locating costume archives across the backend.

Most costume archives are ``.dat`` files. Captain Falcon's red costume can
also appear as ``.usd`` while still behaving like a normal character costume.
"""

from pathlib import Path
from typing import Iterable, Optional


COSTUME_ARCHIVE_EXTENSIONS = ('.dat', '.usd')


def is_costume_archive_filename(filename: str) -> bool:
    """Return True if the ZIP entry / path looks like a character costume archive."""
    if not filename or filename.endswith('/') or filename.startswith('__MACOSX'):
        return False

    path = Path(filename)
    return (
        path.suffix.lower() in COSTUME_ARCHIVE_EXTENSIONS
        and path.stem.lower().startswith('pl')
    )


# Vanilla non-costume file prefixes — cheap skip before content parsing.
_NON_COSTUME_PREFIXES = ('gr', 'mn', 'gm', 'ef', 'if', 'ty', 'lb', 'sd', 'nt', 'vi')


def is_renamed_dat_candidate(filename: str) -> bool:
    """Dat-like files that don't follow the Pl* naming convention but might
    still be costume archives. Renamed uploads are very common in the wild
    ('lucinablack.dat', 'Ghost Ganon PlGnLa.dat', 'PlCaBu.rat' variant
    renames) — content parsing (DATParser + Ply symbol check) makes the
    final call; this filter just nominates candidates cheaply."""
    if not filename or filename.endswith('/') or filename.startswith('__MACOSX'):
        return False

    path = Path(filename)
    suffix = path.suffix.lower()
    dat_like = suffix in COSTUME_ARCHIVE_EXTENSIONS or (
        # the old website's alternate-variant renames: .rat, .lat, .0at…
        len(suffix) == 4 and suffix.endswith('at') and suffix[1].isalnum())
    if not dat_like:
        return False

    return not path.stem.lower().startswith(_NON_COSTUME_PREFIXES)


def get_costume_archive_extension(filename: str, default: str = '.dat') -> str:
    """Return the costume archive extension for a filename, defaulting to .dat."""
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in COSTUME_ARCHIVE_EXTENSIONS else default


def list_costume_archive_names(filenames: Iterable[str]) -> list[str]:
    """Return all filenames that look like costume archives."""
    return [name for name in filenames if is_costume_archive_filename(name)]


def find_costume_archive_name(
        filenames: Iterable[str], costume_code: Optional[str] = None) -> Optional[str]:
    """Return the costume archive matching ``costume_code``, or the first one.

    Stored imports normally name their member ``<costume_code>Mod.dat``. Older
    and externally-created zips often use ``<costume_code>.dat`` instead.
    Prefer either exact relationship when metadata identifies the costume, but
    retain the historical first-match fallback for single-DAT and legacy zips.
    """
    candidates = [name for name in filenames if is_costume_archive_filename(name)]
    if costume_code:
        code = Path(costume_code).stem.lower()
        for name in candidates:
            stem = Path(name).stem.lower()
            if stem == code or stem == f'{code}mod':
                return name
    return candidates[0] if candidates else None


def find_extracted_costume_archive(root: Path) -> Optional[Path]:
    """Find the first costume archive inside an extracted ZIP directory."""
    if not root.exists():
        return None

    for path in sorted(root.rglob('*')):
        relative_name = path.relative_to(root).as_posix()
        if path.is_file() and is_costume_archive_filename(relative_name):
            return path
    return None


def find_vanilla_costume_archive(costume_dir: Path, costume_code: str) -> Optional[Path]:
    """Find a vanilla costume archive by code within a costume directory."""
    for ext in COSTUME_ARCHIVE_EXTENSIONS:
        candidate = costume_dir / f"{costume_code}{ext}"
        if candidate.exists():
            return candidate
    return None
