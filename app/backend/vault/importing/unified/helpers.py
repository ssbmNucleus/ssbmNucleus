"""
Shared import helpers - filename sanitizing, DAT hashing, duplicate detection.
"""

import re
import zipfile
import logging
import hashlib
from pathlib import Path

# Module accessor (not a from-import) so tests that monkeypatch
# core.config.STORAGE_PATH reach the duplicate checks too.
from core import config
from core.costume_files import find_costume_archive_name

logger = logging.getLogger(__name__)


def sanitize_filename(name):
    """Sanitize filename by removing/replacing invalid characters."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def compute_dat_hash(dat_data: bytes) -> str:
    """Compute MD5 hash of DAT file data."""
    return hashlib.md5(dat_data).hexdigest()


def compute_hash_from_stored_skin(character: str, skin: dict) -> str:
    """
    Extract DAT from stored zip and compute its hash.
    Used to backfill hashes for skins imported before this feature.
    """
    try:
        zip_path = config.STORAGE_PATH / character / skin['filename']
        if not zip_path.exists():
            logger.warning(f"Zip file not found for hash computation: {zip_path}")
            return None

        with zipfile.ZipFile(zip_path, 'r') as zf:
            archive_name = find_costume_archive_name(
                zf.namelist(), skin.get('costume_code'))
            if archive_name:
                dat_data = zf.read(archive_name)
                computed_hash = compute_dat_hash(dat_data)
                logger.info(f"Computed hash for existing skin {skin['id']}: {computed_hash}")
                return computed_hash
        logger.warning(f"No costume archive found in zip for {skin['id']}")
        return None
    except Exception as e:
        logger.warning(f"Failed to compute hash for {skin['id']}: {e}")
        return None


def check_duplicate_skin(character: str, dat_hash: str, metadata: dict) -> dict:
    """
    Check if a skin with this DAT hash already exists for the character.
    Computes hash on-demand for skins missing dat_hash (backfill).

    Returns the existing skin entry if found, None otherwise.
    """
    char_data = metadata.get('characters', {}).get(character, {})
    for skin in char_data.get('skins', []):
        # Skins lists also hold folder rows ({"type": "folder", ...}) used for
        # vault organization — nothing to hash there.
        if skin.get('type') == 'folder' or 'filename' not in skin:
            continue
        # G&W color mods all wrap the SAME vanilla DAT (their identity is the
        # gaw_colors pair, not the bytes) — never report them as duplicates of
        # an incoming plain DAT.
        if skin.get('gaw_colors'):
            continue
        # Ghost entry: metadata survived but the stored zip is gone. The vault
        # UI hides these, so treating them as owned would refuse the re-import
        # while showing the user nothing to delete.
        if not (config.STORAGE_PATH / character / skin['filename']).exists():
            continue
        existing_hash = skin.get('dat_hash')

        # If skin doesn't have hash, compute it from stored zip (backfill)
        if existing_hash is None:
            existing_hash = compute_hash_from_stored_skin(character, skin)
            if existing_hash:
                # Cache the computed hash in metadata (will be saved later)
                skin['dat_hash'] = existing_hash

        if existing_hash == dat_hash:
            return skin
    return None


def check_duplicate_stage(stage_folder: str, dat_hash: str, metadata: dict) -> dict:
    """Return existing stage variant if DAT hash matches, else None.

    Variants whose zip no longer exists under storage/das/ don't count: the
    DAS listings only show variants backed by a zip, so a hash-only ghost
    would refuse the import as "already owned" while showing nowhere in the UI.
    """
    for variant in metadata.get('stages', {}).get(stage_folder, {}).get('variants', []):
        if variant.get('dat_hash') != dat_hash:
            continue
        zip_name = variant.get('filename') or f"{variant.get('id')}.zip"
        if (config.STORAGE_PATH / 'das' / stage_folder / zip_name).exists():
            return variant
    return None


def check_duplicate_patch(file_hash: str, patches: list) -> dict:
    """Return existing xdelta patch if file hash matches, else None."""
    for patch in patches:
        if patch.get('file_hash') == file_hash:
            return patch
    return None


def check_duplicate_effect(storage_char: str, effect_type: str, file_hash: str, metadata: dict) -> dict:
    """Return existing effect entry if file hash matches, else None."""
    extras = metadata.get('characters', {}).get(storage_char, {}).get('extras', {})
    for entry in extras.get(effect_type, []):
        if entry.get('file_hash') == file_hash:
            return entry
    return None


def extract_custom_name_from_filename(filename: str, character_name: str) -> str:
    """
    Extract a custom name from the zip filename to use in costume ID.

    Args:
        filename: Original zip filename (e.g., "Villager Climbers (2).zip")
        character_name: Detected character name (e.g., "Ice Climbers")

    Returns:
        Custom name string, or None if no meaningful name could be extracted

    Examples:
        "Villager Climbers (2).zip" -> "villager-climbers"
        "Fox - Shadow Link.zip" -> "shadow-link"
        "Ice Climbers_CustomSkin.zip" -> "customskin"
        "costume.zip" -> None (too generic)
    """
    # Remove file extension
    base_name = Path(filename).stem

    # Remove numbers in parentheses: "(2)", "(1)", etc.
    base_name = re.sub(r'\s*\(\d+\)\s*$', '', base_name)

    # Try to remove character name prefix if present
    # Handle patterns like "Fox - CustomName" or "Ice Climbers - CustomName"
    char_pattern = re.escape(character_name)
    base_name = re.sub(rf'^{char_pattern}\s*[-_:]\s*', '', base_name, flags=re.IGNORECASE)

    # Remove common version patterns: v1, v2, V1.0, etc.
    base_name = re.sub(r'\s*[vV]\d+(\.\d+)?\s*$', '', base_name)

    # Clean up: convert to lowercase, replace spaces/underscores with hyphens
    base_name = base_name.lower()
    base_name = re.sub(r'[_\s]+', '-', base_name)

    # Remove special characters except hyphens
    base_name = re.sub(r'[^a-z0-9-]', '', base_name)

    # Remove multiple consecutive hyphens
    base_name = re.sub(r'-+', '-', base_name)

    # Remove leading/trailing hyphens
    base_name = base_name.strip('-')

    # Check if result is too generic or empty
    generic_names = {'costume', 'skin', 'mod', 'custom', 'default', 'new', 'import'}
    if not base_name or base_name in generic_names or len(base_name) < 2:
        return None

    return base_name
