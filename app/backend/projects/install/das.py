"""
Dynamic Alternate Stages outside the routes: the six loader-backed stages,
how a stage variant is named once it is installed in a project, which archive
member is a stage file, the vault screenshot lookup, and the idempotent heals
for project DAS folders that older versions wrote.

No routes. Used by the DAS install routes (projects/routes/das.py), the vault's
DAS variant routes (vault/routes/das.py), the export job (projects/install/export_job.py
heals the folders before every build) and the unified importer.
"""

import os
import re
import glob
import hashlib
import logging
from pathlib import Path

from core.stages import LEGAL_STAGES

logger = logging.getLogger(__name__)


BUTTON_INDICATOR_RE = re.compile(r'\s*\(([ABXYLRZ])\)$', re.IGNORECASE)
WHITESPACE_RE = re.compile(r'\s+')
PROJECT_VARIANT_WORD_RE = re.compile(r'[A-Za-z0-9]+')
STADIUM_SHORT_HASH_RE = re.compile(r'H(?P<digest>[0-9A-F]{6})$', re.IGNORECASE)

# The longest per-variant Stadium stem proven through a complete natural
# transform cycle in Dolphin is 17 characters.  Longer names can load the
# normal form successfully and then hang when Stadium resolves the nested
# GrPs/<Variant>/GrPsN.dat path.  Keep this deliberately conservative until
# the game's selected-path stack buffer is expanded in the loader itself.
STADIUM_VARIANT_STEM_MAX = 17

# DAS Stage configuration -- the six loader-backed tournament stages, derived
# from the single stage registry (core/stages.py). Every other versus stage is
# a 'replace' slot handled by projects/routes/stage_slots.py.
DAS_STAGES = LEGAL_STAGES

# Mapping of stage codes to default screenshot filenames
DAS_DEFAULT_SCREENSHOTS = {
    'GrNBa': 'battlefield.jpg',
    'GrNLa': 'final destination.png',
    'GrSt': 'Yoshis story.jpg',
    'GrOp': 'dreamland.jpg',
    'GrPs': 'pokemon stadium.jpg',
    'GrIz': 'Fountain of Dreams.webp'
}


def stage_code_from_archive_member(filename):
    """Return the legal-stage code explicitly named by an archive member.

    DAS variants are often generically named, so absence of a code is not an
    error. An explicit *different* code is strong evidence that a file was
    sorted into the wrong vault folder, though (for example the historical
    ``GrNLa-PEGASUS-ARENA.dat`` found under Pokemon Stadium). Loading that
    Final Destination archive through Stadium's ground callbacks crashes.
    """
    basename = Path(filename).name.lower()
    for code in DAS_STAGES:
        if code.lower() in basename:
            return code
    return None


def select_stage_archive_member(stage_files, requested_code):
    """Select the member for ``requested_code`` or describe a hard mismatch.

    Prefer an explicitly matching member in multi-stage archives. Preserve
    legacy support for generic filenames when no member names a known legal
    stage. If codes are present but none match, return their distinct codes
    so the HTTP route can reject the import before touching the project.
    """
    coded = [(name, stage_code_from_archive_member(name))
             for name in stage_files]
    matching = [name for name, code in coded if code == requested_code]
    if matching:
        return matching[0], []

    detected = sorted({code for _, code in coded if code})
    if detected:
        return None, detected
    return stage_files[0], []


def stadium_transformation_members(stage_files):
    """Return ZIP members for a complete GrPs1.dat..GrPs4.dat sidecar set.

    Paths inside the ZIP are ignored; only the canonical basenames count.  A
    partial set is rejected by the import route because the runtime loader
    deliberately checks only GrPs1 before switching all four paths.
    """
    found = {}
    for name in stage_files:
        match = re.fullmatch(r'grps([1-4])\.(?:dat|usd)',
                             Path(name).name.lower())
        if match:
            index = int(match.group(1))
            if index in found:
                raise ValueError(f'Duplicate GrPs{index} transformation file')
            found[index] = name
    return found


def strip_button_indicator(filename):
    """
    Remove button indicator from filename stem
    Example: Vanilla(B) -> Vanilla
    """
    return normalize_whitespace(BUTTON_INDICATOR_RE.sub('', filename))


def extract_button_indicator(filename):
    """
    Extract button indicator from filename stem
    Example: Vanilla(B) -> B
    Returns None if no button indicator found
    """
    match = BUTTON_INDICATOR_RE.search(filename)
    return match.group(1).upper() if match else None


def add_button_indicator(filename, button):
    """
    Add button indicator to filename (replaces existing if present)
    Example: vanilla, B -> vanilla(B)
    """
    cleaned = strip_button_indicator(filename)
    return f"{cleaned}({button.upper()})"


def normalize_whitespace(name):
    """Collapse repeated whitespace and trim ends."""
    return WHITESPACE_RE.sub(' ', name).strip()


def normalize_variant_name(name):
    """
    Normalize a DAS project filename stem.
    - Sanitizes filesystem-unsafe characters
    - Converts the base name to PascalCase with no spaces
    - Canonicalizes button indicators to "Name(B)" format
    """
    if name is None:
        return None

    sanitized = sanitize_filename(name)
    button = extract_button_indicator(sanitized)
    base_name = strip_button_indicator(sanitized)
    words = PROJECT_VARIANT_WORD_RE.findall(base_name)

    if words:
        normalized_base = ''.join(word[:1].upper() + word[1:] for word in words)
    else:
        normalized_base = re.sub(r'\s+', '', base_name)

    if button:
        return add_button_indicator(normalized_base, button)

    return normalized_base


def stadium_runtime_variant_name(name, salt=''):
    """Return a deterministic Stadium stem safe for nested form paths.

    Button indicators remain at the end and a six-hex digest prevents two
    truncated display names from collapsing onto the same file.  When a name
    was already shortened, preserve its digest while adding/removing a button
    so UI assignment does not give the same variant a new identity.
    """
    normalized = normalize_variant_name(name)
    if not normalized:
        return normalized
    if len(normalized) <= STADIUM_VARIANT_STEM_MAX and not salt:
        return normalized

    button = extract_button_indicator(normalized)
    base = strip_button_indicator(normalized)
    prior = STADIUM_SHORT_HASH_RE.search(base)
    if prior and not salt:
        digest = prior.group('digest').upper()
        readable = base[:prior.start()]
    else:
        identity = f'{base.casefold()}\0{salt}'.encode('utf-8')
        digest = hashlib.sha256(identity).hexdigest()[:6].upper()
        readable = base

    indicator = f'({button.upper()})' if button else ''
    # Alphanumeric marker survives normalize_variant_name(); underscores do
    # not, so ``H`` is intentionally part of the on-disc identity token.
    suffix = f'H{digest}'
    readable_budget = STADIUM_VARIANT_STEM_MAX - len(indicator) - len(suffix)
    if readable_budget < 1:
        raise ValueError('Pokemon Stadium variant name cannot fit runtime path')
    return f'{readable[:readable_budget]}{suffix}{indicator}'


def stadium_variant_match_key(name):
    """Match shortened Stadium stems back to their catalog display names."""
    normalized = normalize_variant_name(name)
    base = strip_button_indicator(normalized or '')
    shortened = STADIUM_SHORT_HASH_RE.search(base)
    if shortened:
        return f"stadium-hash:{shortened.group('digest').lower()}"
    return get_variant_match_key(normalized)


def stadium_variant_hashed_match_key(name):
    """Return the stable hash identity even when the display name still fits."""
    normalized = normalize_variant_name(name)
    base = strip_button_indicator(normalized or '')
    shortened = STADIUM_SHORT_HASH_RE.search(base)
    if shortened:
        digest = shortened.group('digest').lower()
    else:
        identity = f'{base.casefold()}\0'.encode('utf-8')
        digest = hashlib.sha256(identity).hexdigest()[:6]
    return f'stadium-hash:{digest}'


def get_variant_match_key(name):
    """
    Convert a display name or installed filename stem into a canonical
    key for project-side DAS matching.
    """
    normalized = normalize_variant_name(name)
    return strip_button_indicator(normalized).lower() if normalized else ''


def sanitize_filename(name):
    """
    Sanitize a display name for use as a filename
    Removes filesystem-unsafe characters while keeping readability
    """
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    return normalize_whitespace(sanitized)


def direct_variant_child(stage_folder: Path, name: str) -> Path:
    """Resolve one direct child while rejecting traversal/path syntax.

    Both separators are refused on every platform, not just the local one.
    Path().name strips a backslash-separated parent on Windows but treats the
    whole thing as one filename on Linux, so a name containing a backslash
    sailed through this guard when it was written on Linux -- and then
    traversed the moment that project was opened on Windows. A DAS variant
    name never legitimately contains either separator.
    """
    if (not name or name in {'.', '..'}
            or '/' in name or '\\' in name
            or Path(name).name != name):
        raise ValueError('Invalid DAS variant name')
    root = stage_folder.resolve()
    child = (stage_folder / name).resolve()
    if child.parent != root:
        raise ValueError('Invalid DAS variant name')
    return child


def find_stage_screenshot(folder_path: Path, variant_id: str):
    """
    Find a stage screenshot with any image extension.
    Returns (exists: bool, path: Path or None, extension: str or None)

    When several extensions exist for the same variant (e.g. an original .jpg and a
    freshly-captured .png), prefer .png, then the most recently modified -- so a new
    capture is never shadowed by a stale screenshot of a different extension. (Plain
    "first glob match" returned .jpg before .png alphabetically, which made captured
    screenshots appear not to save.)
    """
    pattern = str(folder_path / f"{variant_id}_screenshot.*")
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
    matches = [m for m in glob.glob(pattern)
               if os.path.splitext(m)[1].lower() in image_extensions]
    if not matches:
        return False, None, None

    def rank(m):
        ext = os.path.splitext(m)[1].lower()
        try:
            mtime = os.path.getmtime(m)
        except OSError:
            mtime = 0
        return (ext == '.png', mtime)   # .png wins; then newest

    best = max(matches, key=rank)
    return True, Path(best), os.path.splitext(best)[1].lower()


def migrate_das_folder_extensions(project_files, stage_codes=None):
    """Heal legacy DAS stage folders so the m-ex loader accepts their alts.

    Older Nucleus versions wrote Pokemon Stadium DAS alternates (and the
    in-folder ``vanilla`` base) into ``files/GrPs/`` with a ``.usd`` extension.
    The m-ex Dynamic Alternate Stages loader only treats ``.dat`` files in the
    folder as valid alternates -- a folder whose alts are all ``.usd`` makes it
    assert "no valid alts found in GrPs folder / alts must end in the correct
    file extension" (dynamicAlts.c) and the stage crashes on load. (Stadium is
    the only stage affected: it's the one whose root file is ``.usd``.)

    Rename every stray ``*.usd`` alt in a DAS stage folder to ``*.dat`` -- the
    archive format is identical, so this recovers the variant rather than
    discarding it. When a ``*.dat`` of the same stem already exists, drop the
    ``.usd`` as a redundant leftover if it's the ``vanilla`` base or byte-for-byte
    identical, otherwise keep it under a unique ``_N`` name. Idempotent: once a
    folder is clean it does nothing, so it's cheap to call on every build /
    panel load.

    Returns ``{'renamed': [(old, new), ...], 'removed': [name, ...]}``.
    """
    project_files = Path(project_files)
    codes = stage_codes if stage_codes is not None else list(DAS_STAGES)
    renamed, removed = [], []

    for stage_code in codes:
        folder = project_files / stage_code
        if not folder.is_dir():
            continue

        for usd in sorted(folder.glob('*.usd')):
            target = folder / f"{usd.stem}.dat"
            if target.exists():
                # A .dat of the same stem is already present (e.g. the project
                # was re-imported under current code). Drop the .usd if it's the
                # vanilla base or identical content; otherwise keep both.
                redundant = usd.stem.lower() == 'vanilla'
                if not redundant:
                    try:
                        redundant = (usd.stat().st_size == target.stat().st_size
                                     and usd.read_bytes() == target.read_bytes())
                    except OSError:
                        redundant = False
                if redundant:
                    try:
                        usd.unlink()
                        removed.append(usd.name)
                    except OSError as e:
                        logger.warning(f"DAS migrate: could not remove {usd}: {e}")
                    continue
                n = 1
                while target.exists():
                    target = folder / f"{usd.stem}_{n}.dat"
                    n += 1
            try:
                usd.rename(target)
                renamed.append((usd.name, target.name))
            except OSError as e:
                logger.warning(f"DAS migrate: could not rename {usd} -> {target}: {e}")

    if renamed or removed:
        logger.info(f"DAS extension migration: renamed={renamed} removed={removed}")
    return {'renamed': renamed, 'removed': removed}


def migrate_stadium_variant_stems(project_files):
    """Shorten unsafe existing Stadium stems and keep sidecars attached.

    This is an idempotent pre-export heal, parallel to the legacy ``.usd``
    migration above.  Only generated internal names change; archive bytes do
    not.  A sidecar directory is moved transactionally with its normal DAT.
    """
    folder = Path(project_files) / 'GrPs'
    renamed = []
    if not folder.is_dir():
        return {'renamed': renamed}

    for source in sorted(folder.glob('*.dat')):
        old_stem = source.stem
        target_stem = stadium_runtime_variant_name(old_stem)
        # Safe existing stems need no case-only rename. In particular, the
        # installed vanilla.dat aliases Vanilla.dat on Windows; treating that
        # same file as a collision used to leave this read path looping forever.
        if target_stem.casefold() == old_stem.casefold():
            continue

        for salt_index in range(1000):
            if salt_index:
                target_stem = stadium_runtime_variant_name(
                    old_stem, salt=f'collision-{salt_index}')
            target = folder / f'{target_stem}.dat'
            target_forms = folder / target_stem
            old_forms = folder / old_stem
            if not target.exists() and (not target_forms.exists()
                                        or target_forms == old_forms):
                break
        else:
            raise FileExistsError(
                f'Cannot allocate a unique Stadium variant name for {old_stem!r}')

        source.rename(target)
        try:
            if old_forms.is_dir():
                old_forms.rename(target_forms)
        except Exception:
            target.rename(source)
            raise
        renamed.append((old_stem, target_stem))

    if renamed:
        logger.info(f'Stadium runtime stem migration: renamed={renamed}')
    return {'renamed': renamed}
