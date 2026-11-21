"""
Stage Detector - Detects which stage a mod is for based on filename patterns
"""
import os
import re
import struct
import zipfile
from typing import Optional, Dict, List, Tuple, Set
from PIL import Image
from io import BytesIO

from core.stages import ALL_STAGES as _REGISTRY_ALL_STAGES

# Stage code -> {name, folder} for EVERY versus stage (the six DAS stages
# first), derived from the single stage registry (core/stages.py). A raw
# GrXx.dat for any of them imports as a vault stage skin under
# storage/das/<folder>/; the project-side install decides DAS alt vs. slot.
STAGE_MAPPING = {
    code: {'name': info['name'], 'folder': info['folder']}
    for code, info in _REGISTRY_ALL_STAGES.items()
}

# A code counts only as a whole token: 'GrGr' must not match 'GrGreatPlateau',
# and 'GrKg' must not match 'GrKgX'. Digits may follow ('GrPs1' -> GrPs) so
# Stadium's transformation files still resolve to their stage.
_CODE_TOKEN_RES = {
    code: re.compile(r'(?<![A-Z0-9])' + re.escape(code.upper()) + r'(?![A-Z])')
    for code in STAGE_MAPPING
}


def match_stage_code(name_upper: str) -> Optional[str]:
    """First registry code present as a whole token in an UPPER-CASED name."""
    for code, pattern in _CODE_TOKEN_RES.items():
        if pattern.search(name_upper):
            return code
    return None

# Both extensions are stage data. The m-ex DAS loader only accepts '.dat' alts
# and current exports write '.dat'; '.usd' is the legacy spelling that
# projects.install.das.migrate_das_folder_extensions heals on export/install/panel
# load. Accepting only one of them here means a perfectly good skin is reported
# as "could not detect mod type" -- which is exactly what GrPs did, since it
# demanded '.usd' and every modern Stadium skin ships '.dat'.
STAGE_EXTENSIONS = ('.dat', '.usd')

# GrPs1..GrPs4 are Pokemon Stadium's in-stage transformation stages (fire,
# grass, water, rock). They belong to a base skin and are never variants in
# their own right.
STADIUM_TRANSFORMATION_RE = re.compile(r'grps([1-4])\.(?:dat|usd)$', re.IGNORECASE)


def find_stadium_bundle_bases(filenames: List[str]) -> Set[str]:
    """Directory paths that hold a complete GrPs1-4 transformation set.

    Nucleus packages a per-transformation Stadium skin as a base stage file
    named after the VARIANT plus a sibling folder of the same name holding the
    four forms -- 'Minecraft.dat' + 'Minecraft/GrPs1..4.dat' -- because that is
    the shape the DAS loader wants under 'files/GrPs/'. The base carries no
    stage code at all, so the filename scan below cannot see it; the sidecar
    folder beside it is the only thing that identifies it as Stadium.

    A partial set is not a bundle: the runtime loader probes GrPs1 and then
    switches all four paths at once, so three forms would load garbage for the
    fourth. Those fall through to the ordinary scan instead.
    """
    forms = {}
    for name in filenames:
        if name.endswith('/'):
            continue
        match = STADIUM_TRANSFORMATION_RE.fullmatch(os.path.basename(name))
        if match:
            folder = os.path.dirname(name)
            if folder:
                forms.setdefault(folder, set()).add(int(match.group(1)))
    return {folder for folder, indexes in forms.items()
            if indexes == {1, 2, 3, 4}}


def extract_stage_code_from_filename(filename: str) -> Optional[str]:
    """
    Extract stage code (GrNBa, GrPs, etc.) from a filename.

    Args:
        filename: Filename to extract from (can be full path)

    Returns:
        Stage code if found, None otherwise
    """
    return match_stage_code(os.path.basename(filename).upper())


def _is_stadium_named_stage(zf, filename):
    """Legacy Stadium skins append their name directly, e.g. GrPsCoO.usd.

    Only relax that specific prefix when the HSD root table confirms stage
    data. Keep the whole-token rule for other codes/custom stage names.
    """
    if not re.match(r'^GrPs[A-Za-z]', os.path.basename(filename), re.IGNORECASE):
        return False
    with zf.open(filename) as source:
        header = source.read(32)
        if len(header) != 32:
            return False
        size, data_size, relocations, roots, refs = struct.unpack_from('>5I', header)
        root_start = 32 + data_size + relocations * 4
        strings_start = root_start + (roots + refs) * 8
        if size != zf.getinfo(filename).file_size or not 0 < roots <= 4096 or not root_start < strings_start < size:
            return False
        source.seek(root_start)
        table = source.read(roots * 8)
        for index in range(roots):
            data_offset, string_offset = struct.unpack_from('>2I', table, index * 8)
            if data_offset >= data_size or strings_start + string_offset >= size:
                continue
            source.seek(strings_start + string_offset)
            if source.read(9) == b'map_head\0':
                return True
    return False


def build_screenshot_indexes(zf: zipfile.ZipFile, filenames: List[str]) -> Tuple[Dict, Dict, Dict]:
    """
    Build indexes of screenshots for smart matching.

    Similar to character_detector.build_image_indexes() but for stage screenshots.

    Args:
        zf: ZipFile object
        filenames: List of filenames in ZIP

    Returns:
        Tuple of (screenshots_by_name, screenshots_by_code, screenshots_by_folder)
    """
    image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}

    screenshots_by_name = {}  # Cleaned basename -> (filename, aspect_ratio)
    screenshots_by_code = {}  # Stage code -> [(filename, aspect_ratio, folder)]
    screenshots_by_folder = {}  # Folder path -> [(filename, aspect_ratio)]

    for filename in filenames:
        # Skip directories
        if filename.endswith('/'):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext not in image_extensions:
            continue

        # Get image dimensions for aspect ratio scoring
        try:
            img_data = zf.read(filename)
            img = Image.open(BytesIO(img_data))
            width, height = img.size
            aspect_ratio = width / height if height > 0 else 0
        except Exception:
            aspect_ratio = 0

        # Index by cleaned name
        basename = os.path.basename(filename)
        name_without_ext = os.path.splitext(basename)[0].lower()

        # Remove common prefixes
        for prefix in ['screenshot_', 'preview_', 'stage_', 'icon_', 'banner_']:
            if name_without_ext.startswith(prefix):
                name_without_ext = name_without_ext[len(prefix):]
                break

        screenshots_by_name[name_without_ext] = (filename, aspect_ratio)

        # Index by stage code
        stage_code = extract_stage_code_from_filename(filename)
        if stage_code:
            if stage_code not in screenshots_by_code:
                screenshots_by_code[stage_code] = []
            folder = os.path.dirname(filename)
            screenshots_by_code[stage_code].append((filename, aspect_ratio, folder))

        # Index by folder
        folder = os.path.dirname(filename)
        if folder not in screenshots_by_folder:
            screenshots_by_folder[folder] = []
        screenshots_by_folder[folder].append((filename, aspect_ratio))

    return screenshots_by_name, screenshots_by_code, screenshots_by_folder


def detect_stage_from_zip(zip_path: str) -> List[Dict]:
    """
    Detect stage mods in a ZIP file. Supports multiple stages per ZIP.

    Uses intelligent screenshot matching similar to character detection:
    - Tier 0: Exact filename match (screenshot_grnba.png -> GrNBa.dat)
    - Tier 1: Stage code match (extracts GrNBa from image filename)
    - Tier 2: Same-folder match (if only 1 stage in folder)
    - Tier 3: Global fallback (if only 1 stage in entire ZIP)

    Args:
        zip_path: Path to the ZIP file

    Returns:
        List of stage info dicts (empty list if none found):
        [{
            'stage_code': 'GrNBa',
            'stage_name': 'Battlefield',
            'folder': 'battlefield',
            'stage_file': 'GrNBa.dat',
            'screenshot': 'screenshot.png' or None,
            'extension': '.dat' or '.usd'
        }, ...]
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            filenames = zf.namelist()

            # Find all stage files in the ZIP
            bundle_bases = find_stadium_bundle_bases(filenames)
            stage_files = []
            for filename in filenames:
                # Skip directories
                if filename.endswith('/'):
                    continue

                basename = os.path.basename(filename)
                name_upper = basename.upper()
                file_ext = os.path.splitext(basename)[1].lower()

                if file_ext not in STAGE_EXTENSIONS:
                    continue

                # A Stadium bundle's base file is named after the variant
                # ('Minecraft.dat'), so claim it by its sidecar folder before
                # the code scan, which has nothing to match on.
                if os.path.splitext(filename)[0] in bundle_bases:
                    stage_files.append({
                        'filename': filename,
                        'stage_code': 'GrPs',
                        'stage_info': STAGE_MAPPING['GrPs'],
                        'extension': file_ext
                    })
                    continue

                # Transformation files ride along with their base skin --
                # import_stage_mod pulls them out of the source ZIP itself.
                # Reporting them as stages would put four junk variants in the
                # vault and drop the actual stage.
                if STADIUM_TRANSFORMATION_RE.fullmatch(basename):
                    continue

                # Check for stage patterns (whole-token code match)
                stage_code = match_stage_code(name_upper)
                if not stage_code and _is_stadium_named_stage(zf, filename):
                    stage_code = 'GrPs'
                if stage_code:
                    stage_files.append({
                        'filename': filename,
                        'stage_code': stage_code,
                        'stage_info': STAGE_MAPPING[stage_code],
                        'extension': file_ext
                    })

            # If no stages found, return empty list
            if not stage_files:
                return []

            # Build screenshot indexes for smart matching
            screenshots_by_name, screenshots_by_code, screenshots_by_folder = build_screenshot_indexes(zf, filenames)

            # Track used screenshots to prevent double-matching
            used_screenshots: Set[str] = set()

            # Match screenshots to each stage using four-tier system
            results = []
            for stage_file_info in stage_files:
                filename = stage_file_info['filename']
                stage_code = stage_file_info['stage_code']
                stage_info = stage_file_info['stage_info']
                file_ext = stage_file_info['extension']

                screenshot = None
                match_tier = None

                # Get context for this stage file
                basename = os.path.basename(filename)
                name_without_ext = os.path.splitext(basename)[0].lower()
                folder = os.path.dirname(filename)

                # TIER 0: Exact filename match
                # e.g., "GrNBa.dat" matches with "grnba.png" or "screenshot_grnba.png"
                if name_without_ext in screenshots_by_name:
                    candidate_file, aspect_ratio = screenshots_by_name[name_without_ext]
                    if candidate_file not in used_screenshots:
                        screenshot = candidate_file
                        match_tier = 0

                # TIER 1: Stage code match
                # e.g., "screenshot_grnba.png" or "grnba_preview.png" -> GrNBa.dat
                if screenshot is None and stage_code in screenshots_by_code:
                    candidates = screenshots_by_code[stage_code]
                    # Filter out already used
                    candidates = [(f, ar, fld) for f, ar, fld in candidates if f not in used_screenshots]
                    if candidates:
                        # Prefer same folder if available
                        same_folder = [c for c in candidates if c[2] == folder]
                        if same_folder:
                            screenshot = same_folder[0][0]
                        else:
                            screenshot = candidates[0][0]
                        match_tier = 1

                # TIER 2: Same-folder match (only if single stage in folder)
                if screenshot is None and folder:
                    stages_in_folder = [sf for sf in stage_files if os.path.dirname(sf['filename']) == folder]
                    if len(stages_in_folder) == 1:
                        # Only one stage in this folder, can safely match any screenshot from folder
                        if folder in screenshots_by_folder:
                            candidates = screenshots_by_folder[folder]
                            # Filter out already used
                            candidates = [(f, ar) for f, ar in candidates if f not in used_screenshots]
                            if candidates:
                                # Pick best aspect ratio (prefer 16:9 = 1.777 for stages)
                                candidates_sorted = sorted(candidates, key=lambda x: abs(x[1] - 1.777))
                                screenshot = candidates_sorted[0][0]
                                match_tier = 2

                # TIER 3: Global fallback (only if single stage in entire ZIP)
                if screenshot is None and len(stage_files) == 1:
                    # Only one stage in entire ZIP, can use any screenshot
                    all_screenshots = []
                    for folder_path, screenshots in screenshots_by_folder.items():
                        all_screenshots.extend(screenshots)
                    # Filter out already used
                    all_screenshots = [(f, ar) for f, ar in all_screenshots if f not in used_screenshots]
                    if all_screenshots:
                        # Pick best aspect ratio
                        all_screenshots_sorted = sorted(all_screenshots, key=lambda x: abs(x[1] - 1.777))
                        screenshot = all_screenshots_sorted[0][0]
                        match_tier = 3

                # Mark screenshot as used
                if screenshot:
                    used_screenshots.add(screenshot)

                results.append({
                    'stage_code': stage_code,
                    'stage_name': stage_info['name'],
                    'folder': stage_info['folder'],
                    'stage_file': filename,
                    'screenshot': screenshot,
                    'extension': file_ext
                })

            return results

    except Exception as e:
        print(f"Error detecting stages from {zip_path}: {e}")
        import traceback
        traceback.print_exc()
        return []


