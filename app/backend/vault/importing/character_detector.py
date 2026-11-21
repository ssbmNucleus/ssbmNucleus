"""
Character Detector - Detects character and costume info from DAT files.

CSP/stock matching uses the same multi-strategy cascade as the website:
  1. Exact filename match (DAT stem == image base key)
  2. Character/color match (parsed from filenames or DAT detection)
  2.5. Folder name in image key (non-consuming)
  2.6. Color word match with quality scoring (non-consuming)
  2.7. Name overlap match (non-consuming)
  3. Same folder match (only if 1 costume DAT in that folder, consuming)
  3.5. Single image per folder -> shared (non-consuming)
  3.75. Folder positional M>=N>=2 (non-consuming)
  3.8. Folder share fewer-images-than-DATs (non-consuming)
  4. Global fallback (only if 1 costume DAT total, consuming)
  5. Single image fallback (1 image in whole archive, non-consuming)

Post-processing:
  - Duplicate DAT propagation (same hash -> share CSP/stock to siblings)
  - Char+color reuse (variant folders inheriting portraits)
  - Folder leftover matching (1 unmatched DAT + 1 free image per folder)
"""
import sys
import os
import re
import hashlib
from pathlib import Path
from typing import Dict, Tuple, List
import zipfile

from core.costume_files import list_costume_archive_names, is_renamed_dat_candidate

# py7zr is imported LAZILY, only when a .7z is actually handled. Importing it
# pulls in multiprocessing, and in a PyInstaller build that machinery can
# re-execute the app (see the freeze_support() note in app.py). find_spec
# answers "is 7z support available?" without paying that cost.
import importlib.util as _importlib_util

HAS_7Z_SUPPORT = _importlib_util.find_spec("py7zr") is not None


def _py7zr():
    """Import py7zr on demand. Callers must check HAS_7Z_SUPPORT first."""
    import py7zr
    return py7zr

# Add utility scripts to path
SCRIPT_DIR = Path(__file__).resolve().parents[3]  # app/ (this file lives in backend/vault/importing/)
UTILITY_DIR = SCRIPT_DIR / "utility" / "tools" / "processor"
sys.path.insert(0, str(UTILITY_DIR))

try:
    from detect_character import DATParser
except ImportError:
    print(f"Warning: Could not import DATParser from {UTILITY_DIR}")
    DATParser = None


# ── Helpers ported from csp_matcher.py ───────────────────────────────────────

def _strip_csp_suffixes(stem):
    """Strip common CSP prefixes/suffixes and lowercase."""
    return (stem
            .replace('csp_', '').replace('_csp', '')
            .replace('CSP_', '').replace('_CSP', '')
            .strip().lower())


def _strip_stock_suffixes(stem):
    """Strip common stock prefixes/suffixes and lowercase."""
    return (stem
            .replace('stock_', '').replace('_stock', '')
            .replace('STOCK_', '').replace('_STOCK', '')
            .strip().lower())


def _split_key_words(key):
    """Split an image key into lowercase words for folder-name matching.
    e.g. 'neutral-green' -> {'neutral', 'green'}
    """
    return set(w for w in re.split(r'[-_\s()\[\]]+', key.lower()) if len(w) >= 2)


# Mapping from colloquial color words to the canonical Melee color names.
_COLOR_WORD_TO_DAT_COLORS = {
    'default': {'Default'}, 'red': {'Red', 'Orange'}, 'blue': {'Blue', 'Lavender', 'Aqua'},
    'green': {'Green'}, 'white': {'White'}, 'yellow': {'Yellow'},
    'black': {'Black', 'Grey'}, 'pink': {'Pink'}, 'aqua': {'Aqua'},
    'lavender': {'Lavender'}, 'orange': {'Orange', 'Red'}, 'cyan': {'Cyan'},
    'purple': {'Purple'}, 'violet': {'Violet'}, 'brown': {'Brown'},
    'grey': {'Grey', 'Black'}, 'gray': {'Grey', 'Black'},
    'neutral': {'Default'}, 'normal': {'Default'},
}


def _match_color_word(key_words, dat_color):
    """Check if any word in key_words is a color alias for dat_color.

    Returns 0 (no match), 1 (alias match), or 2 (direct match).
    """
    if not dat_color:
        return 0
    best = 0
    dat_color_lower = dat_color.lower()
    for word in key_words:
        possible = _COLOR_WORD_TO_DAT_COLORS.get(word)
        if possible and dat_color in possible:
            if word == dat_color_lower:
                return 2  # direct match, can't do better
            best = max(best, 1)
    return best


_COLOR_WORDS_SET = set(_COLOR_WORD_TO_DAT_COLORS.keys())
_NOISE_WORDS = {'csp', 'stock', 'dat', 'png', 'jpg', 'jpeg', 'the', 'for', 'and', 'with',
                'of', 'in', 'at', 'to', 'on', 'or', 'an', 'is', 'it', 'my', 'vs'}

# Folder names that typically contain CSP/stock images, not DATs.
_MEDIA_CONTAINER_NAMES = {
    'csp', 'csps', 'css', 'ui', 'renders', 'icons', 'stocks', 'portraits',
    'menu textures', 'menu', 'images', 'pics', 'art',
}


def _extract_content_words(name):
    """Extract meaningful content words from a filename or key.

    Strips PlXxYy codes, color words, and common noise.
    """
    name_lower = name.lower()
    name_lower = re.sub(r'\bpl[a-z]{2}[a-z]{2}\b', '', name_lower)
    words = set(w for w in re.split(r'[-_\s.,()\[\]\'\"]+', name_lower) if len(w) >= 2)
    return words - _NOISE_WORDS - _COLOR_WORDS_SET


def _name_overlap_score(dat_name, csp_key):
    """Score how well a CSP key matches a DAT filename by word overlap.

    Returns (overlap_count, -extra_csp_words) tuple for sorting.
    Higher is better.
    """
    dat_words = _extract_content_words(dat_name)
    csp_words = _extract_content_words(csp_key)
    if not dat_words or not csp_words:
        return (0, 0)
    overlap = len(dat_words & csp_words)
    extra = len(csp_words - dat_words)
    return (overlap, -extra)


def _normalize_folder_name(folder):
    """Normalize a folder name for matching — lowercase, strip parentheticals."""
    name = Path(folder).name.lower()
    name = re.sub(r'\s*\(.*?\)\s*', '', name).strip()
    return name


def _get_folder(filename):
    """Get the virtual folder of a ZIP entry filename."""
    if '/' in filename or '\\' in filename:
        return str(Path(filename).parent)
    return '.'


# ── Image filename char/color extraction (ported from dat_processor.py) ──────

def _extract_character_color_from_filename(filename):
    """Extract character and color from image filename patterns.

    Examples:
        PlFxGr.png -> (Fox, Green)
        fox_green_csp.png -> (Fox, Green)

    Returns:
        (character, color) or (None, None)
    """
    _CHAR_CODES = {
        'fx': 'Fox', 'fc': 'Falcon', 'dk': 'Donkey Kong', 'dr': 'Dr. Mario',
        'fa': 'Falco', 'gn': 'Ganondorf', 'kb': 'Kirby', 'kp': 'Koopa',
        'lk': 'Link', 'lg': 'Luigi', 'mr': 'Mario', 'ms': 'Marth',
        'mt': 'Mewtwo', 'ns': 'Ness', 'pe': 'Peach', 'pc': 'Pichu',
        'pk': 'Pikachu', 'pr': 'Jigglypuff', 'fe': 'Roy', 'ss': 'Samus',
        'ys': 'Yoshi', 'ze': 'Zelda', 'cl': 'Young Link', 'gw': 'Mr. Game And Watch',
        'ca': 'Captain Falcon', 'nn': 'Ness', 'pp': 'Ice Climbers',
    }
    _COLOR_CODES = {
        'nr': 'Default', 're': 'Red', 'rd': 'Red', 'bu': 'Blue', 'gr': 'Green', 'wh': 'White',
        'ye': 'Yellow', 'bk': 'Black', 'pi': 'Pink', 'aq': 'Aqua', 'la': 'Lavender',
        'or': 'Orange', 'cy': 'Cyan', 'pu': 'Purple', 'vi': 'Violet', 'br': 'Brown',
        'gy': 'Grey', 'dg': 'Dark Green',
    }

    # Strip common CSP/stock prefixes/suffixes and extension
    name = filename.lower()
    name = (name
            .replace('_csp', '').replace('_stock', '')
            .replace(' csp', '').replace(' stock', '')
            .replace('csp_', '').replace('stock_', '')
            .replace('.png', '').replace('.dat', '').replace('.usd', '')
            .replace('.jpg', '').replace('.jpeg', ''))

    # Try PlXxYy pattern anywhere in the name
    m = re.search(r'pl([a-z]{2})([a-z]{2})', name)
    if m:
        char = _CHAR_CODES.get(m.group(1))
        color = _COLOR_CODES.get(m.group(2))
        if char and color:
            return char, color

    # Try word-based patterns: fox_green, marth_white, etc.
    parts = name.split('_')
    if len(parts) >= 2:
        for code, char_name in _CHAR_CODES.items():
            if char_name.lower().replace(' ', '') == parts[0]:
                return char_name, parts[1].capitalize()

    return None, None


# ── 7z member reading ─────────────────────────────────────────────────────────

def read_7z_member(archive, member):
    """Read one member's bytes from an open py7zr handle.

    py7zr 1.0 removed SevenZipFile.read(); extract to a temp dir instead.
    reset() rewinds the handle so repeated extracts on one archive work.
    """
    import tempfile
    archive.reset()
    with tempfile.TemporaryDirectory(prefix='7z_member_') as tmp:
        archive.extract(path=tmp, targets=[member])
        p = Path(tmp) / member
        return p.read_bytes() if p.exists() else None


# ── Image dimension reading ───────────────────────────────────────────────────

def get_image_dimensions(archive, filename, is_7z=False):
    """Get dimensions of an image from an archive without fully extracting it.

    Returns:
        (width, height) or None
    """
    try:
        from PIL import Image
        import io

        if is_7z:
            image_bytes = read_7z_member(archive, filename)
        else:
            image_bytes = archive.read(filename)

        img = Image.open(io.BytesIO(image_bytes))
        dimensions = img.size
        img.close()
        return dimensions
    except Exception:
        return None


# ── Build image indexes ───────────────────────────────────────────────────────

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg'}
_CSP_ASPECT_RATIO = 136 / 188   # ~0.723
_STOCK_ASPECT_RATIO = 1.0
_ASPECT_RATIO_TOLERANCE = 0.05


def _build_image_indexes(archive, filenames, is_7z=False):
    """Build dual indexes for CSPs and stocks from archive file list.

    Classification priority:
      1. Strict dimension multiples (most reliable)
      2. Keyword patterns in filename
      3. Aspect ratio fallback for non-standard sizes

    Returns:
        (csps_by_name, csps_by_path, stocks_by_name, stocks_by_path)
        csps_by_name:  stripped_key -> [info, ...]   (list per key)
        csps_by_path:  zip_filename -> info           (identity = zip filename)

    Info dict keys: filename, file_path, character, color, filename_folder
    """
    csps_by_name = {}
    csps_by_path = {}
    stocks_by_name = {}
    stocks_by_path = {}

    for filename in filenames:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _IMAGE_EXTS:
            continue

        basename = Path(filename).stem
        basename_lower = basename.lower()
        filename_folder = _get_folder(filename)

        char, color = _extract_character_color_from_filename(filename)

        info = {
            'filename': filename,
            'file_path': filename,  # ZIP filename serves as unique identity key
            'character': char,
            'color': color,
            'filename_folder': filename_folder,
        }

        # --- Classification priority ---
        image_type = None

        # 1. Strict dimension multiples (read image bytes)
        dimensions = get_image_dimensions(archive, filename, is_7z)
        if dimensions:
            w, h = dimensions
            if w % 136 == 0 and h % 188 == 0:
                image_type = 'csp'
            elif w % 24 == 0 and h % 24 == 0 and w == h:
                image_type = 'stock'

        # 2. Keywords (fallback when dimensions don't match standard multiples)
        if image_type is None:
            if any(p in basename_lower for p in ('csp', 'portrait', 'icon')) and 'stock' not in basename_lower:
                image_type = 'csp'
            elif any(p in basename_lower for p in ('stc', 'stock')):
                image_type = 'stock'

        # 3. Aspect ratio for non-standard sizes
        if image_type is None and dimensions:
            w, h = dimensions
            if h > 0:
                aspect = w / h
                if abs(aspect - _CSP_ASPECT_RATIO) < _ASPECT_RATIO_TOLERANCE:
                    image_type = 'csp'
                elif abs(aspect - _STOCK_ASPECT_RATIO) < _ASPECT_RATIO_TOLERANCE:
                    image_type = 'stock'

        if image_type == 'csp':
            key = _strip_csp_suffixes(basename)
            csps_by_name.setdefault(key, []).append(info)
            csps_by_path[filename] = info
        elif image_type == 'stock':
            key = _strip_stock_suffixes(basename)
            stocks_by_name.setdefault(key, []).append(info)
            stocks_by_path[filename] = info

    return csps_by_name, csps_by_path, stocks_by_name, stocks_by_path


# ── Main cascade matching ─────────────────────────────────────────────────────

def _match_images(dat_results, csps_by_name, csps_by_path, stocks_by_name, stocks_by_path):
    """Match CSP/stock images to costume DATs using the full website cascade.

    Adapted from csp_matcher.py for in-ZIP use:
      - file_path = zip filename (unique identity key, no disk extraction needed)
      - DAT hash from r['_hash'] (MD5 computed during pass 1)
      - Nana DATs excluded (caller passes non-Nana results only)

    Returns:
        dict mapping dat_file (zip filename) -> {
            'csp_file': str or None,
            'stock_file': str or None,
        }
    """
    # Build set of costume DAT filenames and hash groups
    costume_dat_filenames = set()
    hash_groups = {}  # hash -> [dat_filename, ...]

    for r in dat_results:
        costume_dat_filenames.add(r['dat_file'])
        h = r.get('_hash')
        if h:
            hash_groups.setdefault(h, []).append(r['dat_file'])
        else:
            hash_groups.setdefault(r['dat_file'], []).append(r['dat_file'])

    unique_costume_dat_count = len(hash_groups)

    # Single DAT info for char/color injection into unnamed images
    single_dat_info = None
    if unique_costume_dat_count == 1 and dat_results:
        single_dat_info = dat_results[0]

    # Reverse lookup: dat_filename -> sibling dat_filenames (same hash)
    dat_siblings = {}
    for group in hash_groups.values():
        for df in group:
            dat_siblings[df] = group

    # dat_filename -> dat_result for post-matching passes
    _dat_results_by_fn = {r['dat_file']: r for r in dat_results}

    # Collect all DAT folders
    dat_folders = set()
    for r in dat_results:
        dat_folders.add(_get_folder(r['dat_file']))

    # --- Folder promotion ---
    # Promote CSPs/stocks in media subfolders to their parent DAT folder.
    for image_pool in (csps_by_path, stocks_by_path):
        for info in image_pool.values():
            folder = info['filename_folder']
            if folder == '.' or folder in dat_folders:
                continue
            parent = str(Path(folder).parent) if folder != '.' else '.'

            # Strategy A: direct child of a DAT folder (CSP/, UI/, etc.)
            if parent in dat_folders:
                info['filename_folder'] = parent
                continue

            # Strategy B: mirrored CSP tree (CSPs/X/ -> X/)
            parts = Path(folder).parts
            if len(parts) >= 2 and parts[0].lower() in _MEDIA_CONTAINER_NAMES:
                stripped = str(Path(*parts[1:]))
                if stripped in dat_folders:
                    info['filename_folder'] = stripped
                    continue

            # Strategy C: sibling folder under common parent
            if info['filename_folder'] == folder:
                sibling_dat_folders = {df for df in dat_folders
                                       if str(Path(df).parent) == parent}
                if len(sibling_dat_folders) == 1:
                    info['filename_folder'] = next(iter(sibling_dat_folders))
                    continue

            # Strategy D: CSP in parent folder, DATs in child subfolder
            if info['filename_folder'] == folder and folder != '.':
                child_dat_folders = {df for df in dat_folders
                                     if str(Path(df).parent) == folder}
                if len(child_dat_folders) == 1:
                    info['filename_folder'] = next(iter(child_dat_folders))

    # If only one costume DAT, inject its char/color into unnamed images
    if single_dat_info:
        for info in csps_by_path.values():
            if not info.get('character'):
                info['character'] = single_dat_info['character']
                info['color'] = single_dat_info.get('color')
        for info in stocks_by_path.values():
            if not info.get('character'):
                info['character'] = single_dat_info['character']
                info['color'] = single_dat_info.get('color')

    consumed_csps = set()
    consumed_stocks = set()
    matches = {}

    _NON_CONSUMING = frozenset((
        'folder_name', 'folder_single_image', 'single_image',
        'color_word', 'name_overlap', 'folder_position', 'folder_share',
    ))

    for r in dat_results:
        dat_fn = r['dat_file']
        char = r['character']
        color = r.get('color')
        dat_basename_lower = Path(dat_fn).stem.lower()
        dat_filename_folder = _get_folder(dat_fn)

        # Count unique costume DATs in this folder (by hash)
        folder_hashes = set()
        for fn in costume_dat_filenames:
            if _get_folder(fn) == dat_filename_folder:
                fn_r = _dat_results_by_fn.get(fn)
                if fn_r:
                    folder_hashes.add(fn_r.get('_hash', fn))
        costume_dats_in_folder = len(folder_hashes)

        matched_csp = None
        matched_stock = None
        csp_strategy = None
        stock_strategy = None

        # --- Strategy 1: Exact filename match ---
        csp_candidates = csps_by_name.get(dat_basename_lower, [])
        if csp_candidates:
            same_folder = [c for c in csp_candidates
                           if c['file_path'] not in consumed_csps
                           and c['filename_folder'] == dat_filename_folder]
            any_unconsumed = [c for c in csp_candidates if c['file_path'] not in consumed_csps]
            pick = (same_folder or any_unconsumed or [None])[0]
            if pick:
                matched_csp = pick
                csp_strategy = 'filename'

        stock_candidates = stocks_by_name.get(dat_basename_lower, [])
        if stock_candidates:
            same_folder = [s for s in stock_candidates
                           if s['file_path'] not in consumed_stocks
                           and s['filename_folder'] == dat_filename_folder]
            any_unconsumed = [s for s in stock_candidates if s['file_path'] not in consumed_stocks]
            pick = (same_folder or any_unconsumed or [None])[0]
            if pick:
                matched_stock = pick
                stock_strategy = 'filename'

        # --- Strategy 2: Character/color match ---
        if not matched_csp and char and color:
            for info in csps_by_path.values():
                if info['file_path'] in consumed_csps:
                    continue
                if info.get('character') == char and info.get('color') == color:
                    matched_csp = info
                    csp_strategy = 'char_color'
                    break

        if not matched_stock and char and color:
            for info in stocks_by_path.values():
                if info['file_path'] in consumed_stocks:
                    continue
                if info.get('character') == char and info.get('color') == color:
                    matched_stock = info
                    stock_strategy = 'char_color'
                    break

        # --- Strategy 2.5: Folder name in image key (non-consuming) ---
        if not matched_csp and dat_filename_folder != '.' and costume_dats_in_folder == 1:
            folder_norm = _normalize_folder_name(dat_filename_folder)
            if folder_norm:
                for key, info_list in csps_by_name.items():
                    if folder_norm in _split_key_words(key):
                        matched_csp = info_list[0]
                        csp_strategy = 'folder_name'
                        break

        if not matched_stock and dat_filename_folder != '.' and costume_dats_in_folder == 1:
            folder_norm = _normalize_folder_name(dat_filename_folder)
            if folder_norm:
                for key, info_list in stocks_by_name.items():
                    if folder_norm in _split_key_words(key):
                        matched_stock = info_list[0]
                        stock_strategy = 'folder_name'
                        break

        # --- Strategy 2.6: Color word match (non-consuming) ---
        if not matched_csp and color:
            candidates = []
            for key, info_list in csps_by_name.items():
                quality = _match_color_word(_split_key_words(key), color)
                if quality:
                    same_folder = [i for i in info_list if i['filename_folder'] == dat_filename_folder]
                    pick = same_folder[0] if same_folder else info_list[0]
                    candidates.append((key, pick, quality))
            if len(candidates) == 1:
                matched_csp = candidates[0][1]
                csp_strategy = 'color_word'
            elif len(candidates) > 1:
                best_quality = max(c[2] for c in candidates)
                candidates = [(k, i, q) for k, i, q in candidates if q == best_quality]
                if len(candidates) == 1:
                    matched_csp = candidates[0][1]
                    csp_strategy = 'color_word'
                else:
                    scored = sorted(
                        [(_name_overlap_score(dat_basename_lower, k), k, i) for k, i, _ in candidates],
                        reverse=True
                    )
                    best = scored[0]
                    second = scored[1] if len(scored) > 1 else None
                    if best[0][0] > 0 and (second is None or best[0] > second[0]):
                        matched_csp = best[2]
                        csp_strategy = 'color_word'

        if not matched_stock and color:
            candidates = []
            for key, info_list in stocks_by_name.items():
                quality = _match_color_word(_split_key_words(key), color)
                if quality:
                    same_folder = [i for i in info_list if i['filename_folder'] == dat_filename_folder]
                    pick = same_folder[0] if same_folder else info_list[0]
                    candidates.append((key, pick, quality))
            if len(candidates) == 1:
                matched_stock = candidates[0][1]
                stock_strategy = 'color_word'
            elif len(candidates) > 1:
                best_quality = max(c[2] for c in candidates)
                candidates = [(k, i, q) for k, i, q in candidates if q == best_quality]
                if len(candidates) == 1:
                    matched_stock = candidates[0][1]
                    stock_strategy = 'color_word'
                else:
                    scored = sorted(
                        [(_name_overlap_score(dat_basename_lower, k), k, i) for k, i, _ in candidates],
                        reverse=True
                    )
                    best = scored[0]
                    second = scored[1] if len(scored) > 1 else None
                    if best[0][0] > 0 and (second is None or best[0] > second[0]):
                        matched_stock = best[2]
                        stock_strategy = 'color_word'

        # --- Strategy 2.7: Name overlap match (non-consuming) ---
        if not matched_csp:
            scored = []
            for key, info_list in csps_by_name.items():
                score = _name_overlap_score(dat_basename_lower, key)
                if score[0] > 0:
                    same_folder = [i for i in info_list if i['filename_folder'] == dat_filename_folder]
                    pick = same_folder[0] if same_folder else info_list[0]
                    scored.append((score, key, pick))
            if scored:
                scored.sort(reverse=True)
                best = scored[0]
                second = scored[1] if len(scored) > 1 else None
                if best[0][0] >= 1 and (second is None or best[0] > second[0]):
                    matched_csp = best[2]
                    csp_strategy = 'name_overlap'

        if not matched_stock:
            scored = []
            for key, info_list in stocks_by_name.items():
                score = _name_overlap_score(dat_basename_lower, key)
                if score[0] > 0:
                    same_folder = [i for i in info_list if i['filename_folder'] == dat_filename_folder]
                    pick = same_folder[0] if same_folder else info_list[0]
                    scored.append((score, key, pick))
            if scored:
                scored.sort(reverse=True)
                best = scored[0]
                second = scored[1] if len(scored) > 1 else None
                if best[0][0] >= 1 and (second is None or best[0] > second[0]):
                    matched_stock = best[2]
                    stock_strategy = 'name_overlap'

        # --- Strategy 3: Same folder (only if 1 costume DAT in folder, consuming) ---
        if not matched_csp and costume_dats_in_folder == 1:
            for info in csps_by_path.values():
                if info['file_path'] not in consumed_csps and info['filename_folder'] == dat_filename_folder:
                    matched_csp = info
                    csp_strategy = 'folder'
                    break

        if not matched_stock and costume_dats_in_folder == 1:
            for info in stocks_by_path.values():
                if info['file_path'] not in consumed_stocks and info['filename_folder'] == dat_filename_folder:
                    matched_stock = info
                    stock_strategy = 'folder'
                    break

        # --- Strategy 3.5: Single image per folder (non-consuming) ---
        if not matched_csp and dat_filename_folder != '.':
            folder_csps = [i for i in csps_by_path.values() if i['filename_folder'] == dat_filename_folder]
            if len(folder_csps) == 1:
                matched_csp = folder_csps[0]
                csp_strategy = 'folder_single_image'

        if not matched_stock and dat_filename_folder != '.':
            folder_stocks = [i for i in stocks_by_path.values() if i['filename_folder'] == dat_filename_folder]
            if len(folder_stocks) == 1:
                matched_stock = folder_stocks[0]
                stock_strategy = 'folder_single_image'

        # --- Strategy 3.75: Folder positional M>=N>=2 (non-consuming) ---
        if not matched_csp:
            allow_position = dat_filename_folder != '.'
            if not allow_position:
                root_csps = [i for i in csps_by_path.values() if i['filename_folder'] == '.']
                allow_position = all(c['file_path'] not in consumed_csps for c in root_csps)
            if allow_position:
                folder_csps = sorted(
                    [i for i in csps_by_path.values() if i['filename_folder'] == dat_filename_folder],
                    key=lambda i: i['filename'].lower()
                )
                folder_dat_fns = sorted(
                    {fn for fn in costume_dat_filenames if _get_folder(fn) == dat_filename_folder},
                    key=str.lower
                )
                if len(folder_csps) >= len(folder_dat_fns) >= 2 and dat_fn in folder_dat_fns:
                    idx = folder_dat_fns.index(dat_fn)
                    matched_csp = folder_csps[idx]
                    csp_strategy = 'folder_position'

        if not matched_stock:
            allow_position = dat_filename_folder != '.'
            if not allow_position:
                root_stocks = [i for i in stocks_by_path.values() if i['filename_folder'] == '.']
                allow_position = all(s['file_path'] not in consumed_stocks for s in root_stocks)
            if allow_position:
                folder_stocks = sorted(
                    [i for i in stocks_by_path.values() if i['filename_folder'] == dat_filename_folder],
                    key=lambda i: i['filename'].lower()
                )
                folder_dat_fns = sorted(
                    {fn for fn in costume_dat_filenames if _get_folder(fn) == dat_filename_folder},
                    key=str.lower
                )
                if len(folder_stocks) >= len(folder_dat_fns) >= 2 and dat_fn in folder_dat_fns:
                    idx = folder_dat_fns.index(dat_fn)
                    matched_stock = folder_stocks[idx]
                    stock_strategy = 'folder_position'

        # --- Strategy 3.8: Folder share fewer-images-than-DATs (non-consuming) ---
        if not matched_csp:
            folder_csps = sorted(
                [i for i in csps_by_path.values() if i['filename_folder'] == dat_filename_folder],
                key=lambda i: i['filename'].lower()
            )
            if folder_csps and len(folder_csps) < costume_dats_in_folder:
                none_consumed = all(c['file_path'] not in consumed_csps for c in folder_csps)
                if dat_filename_folder != '.' or none_consumed:
                    matched_csp = folder_csps[0]
                    csp_strategy = 'folder_share'

        if not matched_stock:
            folder_stocks = sorted(
                [i for i in stocks_by_path.values() if i['filename_folder'] == dat_filename_folder],
                key=lambda i: i['filename'].lower()
            )
            if folder_stocks and len(folder_stocks) < costume_dats_in_folder:
                none_consumed = all(s['file_path'] not in consumed_stocks for s in folder_stocks)
                if dat_filename_folder != '.' or none_consumed:
                    matched_stock = folder_stocks[0]
                    stock_strategy = 'folder_share'

        # --- Strategy 4: Global fallback (only if 1 costume DAT total, consuming) ---
        if not matched_csp and unique_costume_dat_count == 1:
            for info in csps_by_path.values():
                if info['file_path'] not in consumed_csps:
                    matched_csp = info
                    csp_strategy = 'global'
                    break

        if not matched_stock and unique_costume_dat_count == 1:
            for info in stocks_by_path.values():
                if info['file_path'] not in consumed_stocks:
                    matched_stock = info
                    stock_strategy = 'global'
                    break

        # --- Strategy 5: Single image fallback (non-consuming) ---
        if not matched_csp and len(csps_by_path) == 1:
            matched_csp = next(iter(csps_by_path.values()))
            csp_strategy = 'single_image'

        if not matched_stock and len(stocks_by_path) == 1:
            matched_stock = next(iter(stocks_by_path.values()))
            stock_strategy = 'single_image'

        # Record matches and mark consumed
        matches[dat_fn] = {
            'csp_file': matched_csp['filename'] if matched_csp else None,
            'stock_file': matched_stock['filename'] if matched_stock else None,
        }

        if matched_csp and csp_strategy not in _NON_CONSUMING:
            consumed_csps.add(matched_csp['file_path'])
        if matched_stock and stock_strategy not in _NON_CONSUMING:
            consumed_stocks.add(matched_stock['file_path'])

    # --- Duplicate DAT propagation (same hash -> share CSP/stock to siblings) ---
    for dat_fn, result in list(matches.items()):
        siblings = dat_siblings.get(dat_fn, [])
        if len(siblings) <= 1:
            continue
        for sibling in siblings:
            if sibling == dat_fn or sibling not in matches:
                continue
            if not matches[sibling]['csp_file'] and result['csp_file']:
                matches[sibling]['csp_file'] = result['csp_file']
            if not matches[sibling]['stock_file'] and result['stock_file']:
                matches[sibling]['stock_file'] = result['stock_file']

    # --- Same char+color reuse (variant folders inheriting portraits) ---
    char_color_csp = {}
    char_color_stock = {}
    for dat_fn, result in matches.items():
        r = _dat_results_by_fn.get(dat_fn)
        if not r:
            continue
        key = (r.get('character'), r.get('color'))
        if result['csp_file'] and key not in char_color_csp:
            char_color_csp[key] = result['csp_file']
        if result['stock_file'] and key not in char_color_stock:
            char_color_stock[key] = result['stock_file']

    for dat_fn, result in matches.items():
        r = _dat_results_by_fn.get(dat_fn)
        if not r:
            continue
        key = (r.get('character'), r.get('color'))
        if not result['csp_file'] and key in char_color_csp:
            result['csp_file'] = char_color_csp[key]
        if not result['stock_file'] and key in char_color_stock:
            result['stock_file'] = char_color_stock[key]

    # --- Folder leftover matching (1 unmatched DAT + 1 free image per folder) ---
    folder_unmatched_csp = {}
    folder_free_csps = {}
    folder_unmatched_stock = {}
    folder_free_stocks = {}

    for dat_fn, result in matches.items():
        folder = _get_folder(dat_fn)
        if not result['csp_file']:
            folder_unmatched_csp.setdefault(folder, []).append(dat_fn)
        if not result['stock_file']:
            folder_unmatched_stock.setdefault(folder, []).append(dat_fn)

    for info in csps_by_path.values():
        if info['file_path'] not in consumed_csps:
            folder_free_csps.setdefault(info['filename_folder'], []).append(info)
    for info in stocks_by_path.values():
        if info['file_path'] not in consumed_stocks:
            folder_free_stocks.setdefault(info['filename_folder'], []).append(info)

    for folder, unmatched in folder_unmatched_csp.items():
        free = folder_free_csps.get(folder, [])
        if len(unmatched) == 1 and len(free) == 1:
            matches[unmatched[0]]['csp_file'] = free[0]['filename']

    for folder, unmatched in folder_unmatched_stock.items():
        free = folder_free_stocks.get(folder, [])
        if len(unmatched) == 1 and len(free) == 1:
            matches[unmatched[0]]['stock_file'] = free[0]['filename']

    return matches


# ── Public API ────────────────────────────────────────────────────────────────

def detect_character_from_zip(zip_path: str) -> List[Dict]:
    """
    Detect character information from a ZIP/7z file containing character costumes.

    Args:
        zip_path: Path to the ZIP or 7z file

    Returns:
        List of dicts with character info. Empty list if none detected.
        Each dict contains:
        {
            'character': 'Fox',
            'color': 'Green',
            'costume_code': 'PlFxGr',
            'dat_file': 'PlFxGr.dat',
            'csp_file': 'csp.png' or None,
            'stock_file': 'stc.png' or None,
            'symbol': '...',
            'folder': 'green_fox/' or '.',
        }
    """
    if not DATParser:
        print("DATParser not available")
        return []

    is_7z = zip_path.lower().endswith('.7z')
    if is_7z and not HAS_7Z_SUPPORT:
        print("7z file provided but py7zr not installed")
        return []

    try:
        if is_7z:
            archive = _py7zr().SevenZipFile(zip_path, 'r')
            filenames = archive.getnames()
        else:
            archive = zipfile.ZipFile(zip_path, 'r')
            filenames = archive.namelist()

        dat_files = list_costume_archive_names(filenames)

        # Content fallback: also nominate dat-like files that don't follow the
        # Pl* naming convention (renamed costume dats are very common in the
        # wild). Pass 1 below validates by content — DATParser must identify a
        # character AND find Ply joint symbols — so misnamed non-costume files
        # still fall out naturally.
        seen = set(dat_files)
        dat_files += [n for n in filenames
                      if n not in seen and is_renamed_dat_candidate(n)]

        if not dat_files:
            if not is_7z:
                archive.close()
            return []

        import tempfile

        # --- Pass 1: Parse all DATs, compute hashes, detect char/color ---
        dat_results = []
        for dat_filename in dat_files:
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(dat_filename)[1] or '.dat', delete=False) as tmp:
                if is_7z:
                    dat_bytes = read_7z_member(archive, dat_filename)
                else:
                    dat_bytes = archive.read(dat_filename)
                tmp.write(dat_bytes)
                tmp_path = tmp.name

            try:
                parser = DATParser(tmp_path)
                parser.read_dat()

                character, symbol = parser.detect_character()
                if not character:
                    continue

                # Only include costume DATs (must have Ply symbols)
                has_ply_symbol = any('Ply' in node['symbol'] for node in parser.root_nodes)
                if not has_ply_symbol:
                    continue

                color_info = parser.detect_costume_color()
                costume_code = parser.get_character_filename()
                is_nana = 'PlNn' in (costume_code or '')

                dat_hash = hashlib.md5(dat_bytes).hexdigest()

                # Normalize Ice Climbers character name
                if character in ('Ice Climbers (Nana)', 'Ice Climbers (Popo)'):
                    character = 'Ice Climbers'

                dat_results.append({
                    'character': character,
                    'color': color_info if color_info else 'Custom',
                    'costume_code': costume_code,
                    'dat_file': dat_filename,
                    'symbol': symbol,
                    'folder': _get_folder(dat_filename),
                    'is_ice_climbers_nana': is_nana,
                    '_hash': dat_hash,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if not dat_results:
            if not is_7z:
                archive.close()
            return []

        # --- Pass 2: Build image indexes + match images (non-Nana DATs only) ---
        # Nana inherits Popo's CSP at import time (import_unified.py line ~390)
        non_nana_results = [r for r in dat_results if not r.get('is_ice_climbers_nana')]

        csps_by_name, csps_by_path, stocks_by_name, stocks_by_path = _build_image_indexes(
            archive, filenames, is_7z
        )

        matches = _match_images(
            non_nana_results, csps_by_name, csps_by_path, stocks_by_name, stocks_by_path
        )

        if not is_7z:
            archive.close()

        # --- Pass 3: Assemble results ---
        results = []
        for r in dat_results:
            dat_fn = r['dat_file']
            match = matches.get(dat_fn, {})
            results.append({
                'character': r['character'],
                'color': r['color'],
                'costume_code': r['costume_code'],
                'dat_file': dat_fn,
                'csp_file': match.get('csp_file'),
                'stock_file': match.get('stock_file'),
                'symbol': r['symbol'],
                'folder': r['folder'],
            })

        # --- Ice Climbers pairing ---
        # Two-pass: prefer the vanilla color-name pairing (Default/Default,
        # Red/White, Orange/Aqua, Green/Yellow), then fall back to filename
        # slot suffix (PlPpXX <-> PlNnXX) for non-vanilla color slots. Anything
        # still unmatched is emitted as a solo entry so the caller can decide
        # what to do — never silently dropped.
        processed_results = []
        ice_climbers_entries = [r for r in results if r['character'] == 'Ice Climbers']
        other_entries = [r for r in results if r['character'] != 'Ice Climbers']

        if ice_climbers_entries:
            popo_entries = [r for r in ice_climbers_entries if 'PlPp' in r.get('costume_code', '')]
            nana_entries = [r for r in ice_climbers_entries if 'PlNn' in r.get('costume_code', '')]

            POPO_TO_NANA = {
                'Default': 'Default',
                'Red': 'White',
                'Orange': 'Aqua/Light Blue',
                'Green': 'Yellow',
            }

            def _slot_suffix(costume_code):
                stem = os.path.splitext(costume_code or '')[0]
                return stem[-2:] if len(stem) >= 4 else None

            def _link_pair(popo, nana):
                popo['is_popo'] = True
                popo['is_nana'] = False
                popo['pair_dat_file'] = nana['dat_file']
                popo['pair_color'] = nana['color']
                popo['pair_costume_code'] = nana['costume_code']
                nana['is_nana'] = True
                nana['is_popo'] = False
                nana['pair_dat_file'] = popo['dat_file']
                nana['pair_color'] = popo['color']
                nana['pair_costume_code'] = popo['costume_code']

            paired_nanas = set()
            paired_popos = set()

            # Pass 1: vanilla color-name pairing
            for popo in popo_entries:
                expected = POPO_TO_NANA.get(popo['color'])
                if not expected:
                    continue
                for nana in nana_entries:
                    if id(nana) in paired_nanas:
                        continue
                    if nana['color'] == expected:
                        _link_pair(popo, nana)
                        paired_popos.add(id(popo))
                        paired_nanas.add(id(nana))
                        processed_results.append(popo)
                        processed_results.append(nana)
                        break

            # Pass 2: filename suffix fallback for custom-color slots
            for popo in popo_entries:
                if id(popo) in paired_popos:
                    continue
                suf = _slot_suffix(popo.get('costume_code'))
                if not suf:
                    continue
                for nana in nana_entries:
                    if id(nana) in paired_nanas:
                        continue
                    if _slot_suffix(nana.get('costume_code')) == suf:
                        _link_pair(popo, nana)
                        paired_popos.add(id(popo))
                        paired_nanas.add(id(nana))
                        processed_results.append(popo)
                        processed_results.append(nana)
                        break

            # Pass 3: singleton fallback — exactly one unpaired Popo and one
            # unpaired Nana in the same zip is unambiguously a pair, even when
            # the colors don't follow the vanilla table and the filenames don't
            # share a slot suffix (e.g. website exports pairing Green Popo with
            # an Aqua Nana).
            solo_popos = [p for p in popo_entries if id(p) not in paired_popos]
            solo_nanas = [n for n in nana_entries if id(n) not in paired_nanas]
            if len(solo_popos) == 1 and len(solo_nanas) == 1:
                popo, nana = solo_popos[0], solo_nanas[0]
                _link_pair(popo, nana)
                paired_popos.add(id(popo))
                paired_nanas.add(id(nana))
                processed_results.append(popo)
                processed_results.append(nana)

            # Unmatched IC halves are intentionally dropped — solo Popo/Nana
            # imports aren't supported (you can't play half an Ice Climber).
            # If neither the vanilla color-name table, the filename-suffix
            # fallback, nor the singleton fallback found a partner, the entry
            # is silently discarded.

        processed_results.extend(other_entries)
        return processed_results

    except Exception as e:
        print(f"Error detecting character from {zip_path}: {e}")
        import traceback
        traceback.print_exc()
        return []


def is_character_costume(dat_path: str) -> bool:
    """
    Check if a DAT file is a character costume (vs data/effect mod).

    Args:
        dat_path: Path to DAT file

    Returns:
        True if it's a character costume file
    """
    if not DATParser:
        return False

    try:
        parser = DATParser(dat_path)
        parser.read_dat()
        has_ply_symbol = any('Ply' in node['symbol'] for node in parser.root_nodes)
        return has_ply_symbol
    except Exception:
        return False
