"""
Texture Pack Generation Module

Generates base-4 color encoded placeholder CSPs for texture pack mode,
and watches Dolphin's dump folder to decode and copy high-res textures.

Uses a 16x16 image with finder markers and 7 data cells to encode
costume indices up to 16,384 (4^7).
"""

import io
import json
import shutil
import logging
import file_retry
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List, Tuple, Dict
from PIL import Image

logger = logging.getLogger(__name__)

# =============================================================================
# Base-4 Color Encoding System
# =============================================================================

# Data colors (at corners of RGB cube for max distinction)
DATA_COLORS = [
    (0, 0, 0, 255),        # 0 = BLACK
    (255, 0, 0, 255),      # 1 = RED
    (0, 255, 0, 255),      # 2 = GREEN
    (0, 0, 255, 255),      # 3 = BLUE
]

# Finder marker colors (unique combo to identify our placeholders)
FINDER_COLORS = {
    'M1': (255, 255, 255, 255),  # WHITE
    'M2': (255, 0, 255, 255),    # MAGENTA
    'M3': (0, 255, 255, 255),    # CYAN
    'M4': (255, 255, 0, 255),    # YELLOW
}

GRAY = (128, 128, 128, 255)

# Layout: 4x4 grid of cells
# [M1][M2][D6][D5]
# [M3][D4][D3][D2]
# [  ][D1][D0][  ]
# [  ][  ][  ][M4]

DATA_POSITIONS = [
    (0, 2), (0, 3),        # D6, D5
    (1, 1), (1, 2), (1, 3),  # D4, D3, D2
    (2, 1), (2, 2)         # D1, D0
]

FINDER_POSITIONS = {
    'M1': (0, 0),
    'M2': (0, 1),
    'M3': (1, 0),
    'M4': (3, 3),
}


def generate_encoded_placeholder(index: int, size: int = 16) -> Image.Image:
    """
    Generate a 16x16 placeholder with base-4 encoded index.

    Uses 7 data cells to encode values 0-16383 (4^7).
    Finder markers in corners identify this as our placeholder.

    Args:
        index: Costume index (0-16383)
        size: Image size (default 16x16)

    Returns:
        PIL Image object
    """
    img = Image.new('RGBA', (size, size), GRAY)
    cell = size // 4

    def fill_cell(row: int, col: int, color: Tuple[int, int, int, int]):
        for y in range(row * cell, (row + 1) * cell):
            for x in range(col * cell, (col + 1) * cell):
                img.putpixel((x, y), color)

    # Draw finder markers
    for name, (row, col) in FINDER_POSITIONS.items():
        fill_cell(row, col, FINDER_COLORS[name])

    # Encode index in base-4 across 7 cells (D6 to D0)
    for i, (row, col) in enumerate(DATA_POSITIONS):
        digit = (index >> (2 * (6 - i))) & 3
        fill_cell(row, col, DATA_COLORS[digit])

    return img


def save_encoded_placeholder(index: int, output_path: Path, size: int = 16) -> None:
    """
    Generate and save an encoded placeholder to disk.

    Args:
        index: Costume index (0-16383)
        output_path: Path to save the PNG
        size: Image size (default 16x16)
    """
    img = generate_encoded_placeholder(index, size)
    img.save(output_path, format='PNG')
    logger.debug(f"Saved encoded placeholder index={index} to {output_path}")


def decode_placeholder(img: Image.Image) -> Optional[int]:
    """
    Decode a dumped texture to extract the costume index.

    Verifies finder pattern first, then reads 7 base-4 data cells.

    Args:
        img: PIL Image (scaled up from 16x16 by Dolphin)

    Returns:
        Costume index (0-16383) or None if not our placeholder
    """
    cell_w = img.width // 4
    cell_h = img.height // 4

    def get_pixel(row: int, col: int) -> Tuple[int, int, int]:
        """Sample center of cell."""
        cx = col * cell_w + cell_w // 2
        cy = row * cell_h + cell_h // 2
        pixel = img.getpixel((cx, cy))
        return pixel[:3] if isinstance(pixel, tuple) else (pixel, pixel, pixel)

    def is_finder_match(row: int, col: int, expected: Tuple[int, int, int, int]) -> bool:
        """Check if cell matches expected finder color (with tolerance)."""
        r, g, b = get_pixel(row, col)
        er, eg, eb = expected[:3]
        return abs(r - er) < 80 and abs(g - eg) < 80 and abs(b - eb) < 80

    # Verify finder pattern
    for name, (row, col) in FINDER_POSITIONS.items():
        if not is_finder_match(row, col, FINDER_COLORS[name]):
            return None  # Not our placeholder

    def decode_data_color(row: int, col: int) -> int:
        """Decode a data cell to base-4 digit (0-3)."""
        r, g, b = get_pixel(row, col)

        # Check which color it's closest to
        if r < 80 and g < 80 and b < 80:
            return 0  # BLACK
        if r > 180 and g < 80 and b < 80:
            return 1  # RED
        if r < 80 and g > 180 and b < 80:
            return 2  # GREEN
        if r < 80 and g < 80 and b > 180:
            return 3  # BLUE

        # Fallback: find closest by dominant channel
        if r >= g and r >= b:
            return 1  # RED
        if g >= r and g >= b:
            return 2  # GREEN
        if b >= r and b >= g:
            return 3  # BLUE
        return 0  # BLACK

    # Read 7 base-4 digits (D6 to D0)
    index = 0
    for i, (row, col) in enumerate(DATA_POSITIONS):
        digit = decode_data_color(row, col)
        index |= (digit << (2 * (6 - i)))

    return index


@dataclass
class CostumeMapping:
    """Maps a placeholder index to a costume's real CSP."""
    index: int                    # Global costume index (encoded in placeholder)
    character: str                # Character name
    costume_index: int            # Costume index within character
    skin_id: str                  # Storage skin ID (for lookup)
    real_csp_path: str            # Path to the actual high-res CSP (SD fallback)
    matched: bool = False         # Whether texture was matched
    dumped_filename: Optional[str] = None  # TEX_0x... filename when matched
    # HD source resolved at export time (vault HD CSP, or a 4x render of a patch
    # costume cached by DAT hash). When set, the texture pack uses this instead of
    # the SD real_csp_path. None -> fall back to the live vault-hash match / SD.
    hd_csp_path: Optional[str] = None
    dat_hash: Optional[str] = None  # md5 of the costume DAT (HD cache key)


@dataclass
class TexturePackMapping:
    """Tracks all costume placeholders for a texture pack build."""
    build_id: str                 # Unique build identifier
    build_name: str               # Load/ subfolder of this build's pack (the build id)
    created_at: str               # ISO timestamp
    costumes: List[Dict] = field(default_factory=list)

    def add_costume(self, costume: CostumeMapping) -> None:
        """Add a costume mapping."""
        self.costumes.append(asdict(costume))

    def find_by_index(self, index: int) -> Optional[Dict]:
        """
        Find a costume mapping by its encoded index.

        Args:
            index: Decoded index from placeholder (0-16383)

        Returns:
            Costume mapping dict if found, None otherwise
        """
        for costume in self.costumes:
            if costume['index'] == index:
                return costume
        return None

    def get_unmatched_count(self) -> int:
        """Return count of costumes not yet matched."""
        return sum(1 for c in self.costumes if not c['matched'])

    def get_matched_count(self) -> int:
        """Return count of costumes already matched."""
        return sum(1 for c in self.costumes if c['matched'])

    def save(self, output_path: Path) -> None:
        """Save mapping to JSON file."""
        with open(output_path, 'w') as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> 'TexturePackMapping':
        """Load mapping from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls(
            build_id=data['build_id'],
            build_name=data['build_name'],
            created_at=data['created_at'],
            costumes=data.get('costumes', [])
        )


class TexturePackMatcher:
    """
    Watches Dolphin's dump folder for placeholder textures and copies
    high-res CSPs to the load folder.
    """

    def __init__(
        self,
        dump_path: Path,
        load_path: Path,
        mapping: TexturePackMapping,
        storage_path: Optional[Path] = None,
        on_match: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        *, job
    ):
        """
        Initialize the texture matcher used by the shared job.

        Args:
            dump_path: Dolphin's texture dump directory
            load_path: Dolphin's texture load directory
            mapping: TexturePackMapping with color-to-costume mappings
            storage_path: Path to storage folder for HD CSPs
            on_match: Callback when a texture is matched (receives costume dict)
            on_progress: Callback for progress updates (matched_count, total_count)
            job: Shared job owning partial copies and cancellation
        """
        self.dump_path = dump_path
        self.load_path = load_path
        self.mapping = mapping
        self.storage_path = storage_path
        self.on_match = on_match
        self.on_progress = on_progress
        self.job = job
        self.seen_files: set = set()

    def scan(self) -> None:
        """One pass through dumped textures, on the shared job's worker."""
        if not self.dump_path.exists():
            return

        # Look for PNG files that might be dumped textures
        # Dolphin dumps with pattern: tex1_WxH_hash_hash_#.png
        for tex_file in self.dump_path.glob("*.png"):
            if self.job.should_stop():
                break
            if tex_file.name in self.seen_files:
                continue

            self.seen_files.add(tex_file.name)

            # Skip if it doesn't look like a Dolphin texture dump
            # Dolphin uses patterns like: tex1_136x188_cbdd7d7201f3e390_9a1111f167d5ff4e_9.png
            if not tex_file.name.startswith('tex'):
                logger.debug(f"Skipping non-texture file: {tex_file.name}")
                continue

            logger.debug(f"Processing texture dump: {tex_file.name}")

            # Try to decode placeholder using base-4 encoding
            try:
                with Image.open(tex_file) as img:
                    index = decode_placeholder(img)
            except Exception as e:
                logger.error(f"Failed to read texture {tex_file}: {e}")
                continue

            if index is None:
                # Not our placeholder (finder pattern didn't match)
                logger.debug(f"  -> Not a placeholder (finder pattern not found)")
                continue

            logger.info(f"  -> Decoded index: {index}")

            # Match to costume by index
            costume = self.mapping.find_by_index(index)
            if costume and not costume['matched']:
                logger.info(f"  -> MATCH: {costume['character']} costume {costume['costume_index']}")
                self._process_match(costume, tex_file)
            elif costume and costume['matched']:
                logger.debug(f"  -> Already matched: {costume['character']}")
            else:
                logger.warning(f"  -> No costume found for index {index}")

    def _process_match(self, costume: Dict, dumped_file: Path) -> None:
        """Copy real CSP to Load folder with correct filename."""
        try:
            # Create build-specific subdirectory
            load_subdir = self.load_path / self.mapping.build_name
            load_subdir.mkdir(parents=True, exist_ok=True)

            # Copy real CSP with dumped texture's filename
            dest_file = load_subdir / dumped_file.name
            real_csp_path = costume['real_csp_path']

            # Convert Windows path to WSL path if needed (must do before hash lookup)
            import os
            if os.name != 'nt' and real_csp_path and len(real_csp_path) >= 2 and real_csp_path[1] == ':':
                drive_letter = real_csp_path[0].lower()
                rest_of_path = real_csp_path[2:].replace('\\', '/')
                real_csp_path = f'/mnt/{drive_letter}{rest_of_path}'
                logger.debug(f"Converted backup CSP path: {costume['real_csp_path']} -> {real_csp_path}")

            # Check for HD CSP in storage using perceptual hash matching
            if self.storage_path:
                hd_csp = self._find_hd_csp_by_hash(real_csp_path, costume['character'])
                if hd_csp:
                    real_csp_path = str(hd_csp)
                    logger.info(f"Using HD CSP for {costume['character']}: {hd_csp.name}")

            real_csp = Path(real_csp_path)

            if not real_csp.exists():
                logger.warning(f"Real CSP not found: {real_csp}")
                return

            partial = load_subdir / f'texture-match-{self.job.id}.png.part'
            self.job.own('partial', str(partial))
            shutil.copy2(real_csp, partial)
            file_retry.replace(partial, dest_file)
            self.job.release('partial')

            # Update mapping
            costume['matched'] = True
            costume['dumped_filename'] = dumped_file.name

            logger.info(f"Matched texture: {costume['character']} costume {costume['costume_index']} -> {dumped_file.name}")

            # Notify callbacks
            if self.on_match:
                self.on_match(costume)

            if self.on_progress:
                matched = self.mapping.get_matched_count()
                total = len(self.mapping.costumes)
                self.on_progress(matched, total)

        except Exception as e:
            logger.error(f"Failed to process match for {costume['character']}: {e}", exc_info=True)

    def _find_hd_csp_by_hash(self, backup_csp_path: str, character: str) -> Optional[Path]:
        """
        Find HD CSP by matching perceptual hash of the backup CSP.

        Args:
            backup_csp_path: Path to the backup CSP from the project
            character: Character name to search within

        Returns:
            Path to HD CSP if found, None otherwise
        """
        try:
            import imagehash

            # Hash the backup CSP
            backup_img = Image.open(backup_csp_path)
            backup_hash = imagehash.phash(backup_img)

            # Load metadata to find skins with HD CSPs. Goes through the DAL
            # (metadata.json OR the SQLite vault) — a raw file read misses every
            # DB-only import and silently downgrades the pack to SD CSPs.
            metadata = _vault_metadata(self.storage_path)
            if not metadata:
                logger.debug("No metadata.json found in storage")
                return None

            char_skins = metadata.get('characters', {}).get(character, {}).get('skins', [])

            for skin in char_skins:
                if skin.get('has_hd_csp') and skin.get('csp_hash'):
                    stored_hash = imagehash.hex_to_hash(skin['csp_hash'])
                    distance = backup_hash - stored_hash
                    if distance < 10:  # Hamming distance threshold
                        hd_csp = self.storage_path / character / f"{skin['id']}_csp_hd.png"
                        if hd_csp.exists():
                            logger.info(f"Hash match found: {skin['id']} (distance={distance})")
                            return hd_csp
                        else:
                            logger.warning(f"Hash matched but HD CSP missing: {hd_csp}")

            logger.debug(f"No hash match found for {character} CSP")
            return None

        except Exception as e:
            logger.error(f"Error finding HD CSP by hash: {e}", exc_info=True)
            return None

# =============================================================================
# Offline texture-pack naming (no ISO boot)
# =============================================================================
#
# The placeholder for a given GLOBAL costume index is byte-identical in every
# build (generate_encoded_placeholder is deterministic, compiled the same way),
# so the Dolphin load filename it produces -- tex1_16x16_<texHash>_<tlutHash>_9.png
# -- is a pure function of the index. Once that index -> filename relation has
# been harvested ONCE (by booting any build and scrolling the CSS so Dolphin
# dumps each placeholder; see tools/ingame/nucleus/run-texture-harvest.js), every future
# build's texture pack can be named WITHOUT booting: read the build's own mapping
# (index -> real CSP) and copy each CSP into Load/ under table[index].


def _vault_metadata(storage_path) -> dict:
    """Vault index for `storage_path`, read through the DAL.

    When the caller's storage_path IS the live vault we go through the plain
    load_metadata() so the SQLite backend is honored; a different folder (tests,
    a secondary vault) is read as that folder's metadata.json via path=, which
    the DAL never redirects to the DB. Mirrors first_run_setup._uses_shared_vault.
    """
    from core.config import STORAGE_PATH as LIVE_STORAGE_PATH
    from core.metadata import load_metadata
    storage_path = Path(storage_path)
    if storage_path == Path(LIVE_STORAGE_PATH):
        return load_metadata(default={}) or {}
    return load_metadata(default={}, path=storage_path / 'metadata.json') or {}


def _to_local_csp_path(real_csp_path: str) -> str:
    """Mirror the watcher's Windows->WSL path fixup (no-op on Windows)."""
    import os
    if os.name != 'nt' and real_csp_path and len(real_csp_path) >= 2 and real_csp_path[1] == ':':
        drive_letter = real_csp_path[0].lower()
        rest = real_csp_path[2:].replace('\\', '/')
        return f'/mnt/{drive_letter}{rest}'
    return real_csp_path


# imagehash is optional; if it's not installed we simply skip the HD upgrade and
# use the project's regular CSP (exactly what the live watcher falls back to).
try:
    import imagehash as _imagehash
except ImportError:
    _imagehash = None


def find_hd_csp_by_hash(storage_path: Path, backup_csp_path: str, character: str) -> Optional[Path]:
    """Module-level twin of TexturePackMatcher._find_hd_csp_by_hash: find an HD
    CSP in storage whose perceptual hash matches the project's backup CSP. Returns
    None (no upgrade) if imagehash isn't available."""
    if _imagehash is None:
        return None
    try:
        imagehash = _imagehash
        backup_hash = imagehash.phash(Image.open(backup_csp_path))
        metadata = _vault_metadata(storage_path)
        if not metadata:
            return None
        for skin in metadata.get('characters', {}).get(character, {}).get('skins', []):
            if skin.get('has_hd_csp') and skin.get('csp_hash'):
                if (backup_hash - imagehash.hex_to_hash(skin['csp_hash'])) < 10:
                    hd_csp = storage_path / character / f"{skin['id']}_csp_hd.png"
                    if hd_csp.exists():
                        return hd_csp
        return None
    except Exception as e:
        logger.error(f"Error finding HD CSP by hash: {e}", exc_info=True)
        return None


def place_costume_csp(costume: Dict, dest_filename: str, load_subdir: Path,
                      storage_path: Optional[Path]) -> bool:
    """Copy a costume's best available CSP into load_subdir as dest_filename.
    Resolution priority (highest first):
      1. hd_csp_path -- HD resolved at export time (vault HD CSP, or a 4x render
         of a patch costume cached by DAT hash). The right answer for costumes
         that have no vault identity, e.g. Animelee-patch slots.
      2. live vault perceptual-hash match -- legacy path for mappings written
         before export-time resolution existed.
      3. real_csp_path -- the project's SD CSP (always present; last resort).
    Returns True on copy."""
    src = None

    pre = costume.get('hd_csp_path')
    if pre:
        pre = _to_local_csp_path(pre)
        if Path(pre).exists():
            src = pre

    if src is None:
        base = _to_local_csp_path(costume['real_csp_path'])
        if storage_path:
            hd = find_hd_csp_by_hash(storage_path, base, costume['character'])
            if hd:
                src = str(hd)
        if src is None:
            src = base

    real_csp = Path(src)
    if not real_csp.exists():
        logger.warning(f"Real CSP not found for offline naming: {real_csp}")
        return False
    shutil.copy2(real_csp, load_subdir / dest_filename)
    return True


def apply_offline_texture_pack(mapping: 'TexturePackMapping', table_entries: Dict,
                               load_path: Path, storage_path: Optional[Path]) -> Dict:
    """Name a build's texture pack from a harvested index->filename table, with no
    boot. table_entries maps str(index) -> {filename, ...}. Copies each costume's
    CSP into load_path/<build_name>/<filename>, marks the mapping, and reports
    which indices were missing from the table (e.g. Sheik, or indices past the
    harvested range)."""
    load_subdir = load_path / mapping.build_name
    load_subdir.mkdir(parents=True, exist_ok=True)
    matched, missing, copy_failed = 0, [], []
    for costume in mapping.costumes:
        rec = table_entries.get(str(costume['index']))
        if not rec or not rec.get('filename'):
            missing.append(costume['index'])
            continue
        if place_costume_csp(costume, rec['filename'], load_subdir, storage_path):
            costume['matched'] = True
            costume['dumped_filename'] = rec['filename']
            matched += 1
        else:
            copy_failed.append(costume['index'])
    return {
        'matched': matched,
        'total': len(mapping.costumes),
        'missingFromTable': sorted(missing),
        'copyFailed': sorted(copy_failed),
        'texturePackPath': str(load_subdir),
    }
