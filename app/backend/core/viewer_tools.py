"""File lookups (and a free port) for opening a model in HSDRawViewer.

Where a character's scene, animation archive (AJ) and fighter-data DAT live,
how a custom character's AJ / fighter data come out of its fighter.zip, and
where a vanilla costume archive is. The viewer routes (shared/routes/viewer.py),
the Skin Lab session and portrait renderer (shared/rendering/) and Randall's lab
tools all use these, so none of them has to import a route module to reach them.
"""

import json
import logging
import socket
import zipfile
from pathlib import Path

from core.config import STORAGE_PATH, VANILLA_ASSETS_DIR, PROCESSOR_DIR
from core.constants import VANILLA_CSS_COLOR_ORDER
from core.costume_files import find_vanilla_costume_archive

logger = logging.getLogger(__name__)


# Character prefixes for AJ files
VIEWER_CHAR_PREFIXES = {
    "C. Falcon": "PlCa", "Falco": "PlFc", "Fox": "PlFx",
    "Marth": "PlMs", "Roy": "PlFe", "Bowser": "PlKp",
    "DK": "PlDk", "Ganondorf": "PlGn", "Jigglypuff": "PlPr",
    "Kirby": "PlKb", "Link": "PlLk", "Luigi": "PlLg",
    "Mario": "PlMr", "Mewtwo": "PlMt", "Ness": "PlNs",
    "Peach": "PlPe", "Pichu": "PlPc", "Pikachu": "PlPk",
    "Ice Climbers": "PlPp", "Samus": "PlSs", "Sheik": "PlSk",
    "Yoshi": "PlYs", "Young Link": "PlCl", "Zelda": "PlZd",
    "Dr. Mario": "PlDr", "G&W": "PlGw", "Mr. Game & Watch": "PlGw",
    "Nana": "PlNn"
}


def find_scene_file(character):
    """Find a scene file for a character"""
    # csp_data keeps G&W under the short name the vault does not use
    folder = "G&W" if character == "Mr. Game & Watch" else character
    csp_data_dir = PROCESSOR_DIR / "csp_data" / folder

    if csp_data_dir.exists():
        # Try scene.yml first (most common)
        if (csp_data_dir / "scene.yml").exists():
            return csp_data_dir / "scene.yml"
        else:
            # Look for any .yml file (cspfinal.yml, CSP.yml, etc.)
            yml_files = sorted(csp_data_dir.glob("*.yml"))
            if yml_files:
                return yml_files[0]

    return None


def find_aj_file(character):
    """Find the AJ (animation archive) file for a character"""
    if character in VIEWER_CHAR_PREFIXES:
        prefix = VIEWER_CHAR_PREFIXES[character]
        aj_path = VANILLA_ASSETS_DIR / character / f"{prefix}AJ.dat"
        if aj_path.exists():
            return aj_path
    return None


def find_fighter_data_file(character):
    """Find the fighter-data dat (Pl<XX>.dat) for a character. Unlike the model
    costume dat, this holds ftData: the model-part visibility lookup table AND
    the per-action subaction scripts that drive per-animation part swaps
    (Bowser shell, Link's bow, Peach's f-smash weapon, ...).

    NOTE: the vanilla-assets dir usually ships only costume dats + the AJ, NOT
    the fighter-data dat, so the real source is the extracted base-game files
    (same place generate_csp falls back to)."""
    if character not in VIEWER_CHAR_PREFIXES:
        return None
    prefix = VIEWER_CHAR_PREFIXES[character]
    for p in (VANILLA_ASSETS_DIR / character / f"{prefix}.dat",
              STORAGE_PATH / "test-base" / "files" / f"{prefix}.dat"):
        if p.exists():
            return p
    return None


def extract_custom_character_data(slug):
    """Get a custom character's fighter-data dat: extract files.fighterDataPath
    from fighter.zip into the character dir (cached as data_cache.dat)."""
    char_dir = STORAGE_PATH / 'custom_characters' / slug
    cache = char_dir / 'data_cache.dat'
    if cache.exists():
        return cache
    fighter_json = char_dir / 'fighter.json'
    fighter_zip = char_dir / 'fighter.zip'
    if not fighter_json.exists() or not fighter_zip.exists():
        return None
    try:
        with open(fighter_json, 'r') as f:
            data_file = (json.load(f).get('files') or {}).get('fighterDataPath')
        if not data_file:
            return None
        with zipfile.ZipFile(fighter_zip) as zf:
            for n in zf.namelist():
                if n.split('/')[-1].lower() == data_file.lower():
                    cache.write_bytes(zf.read(n))
                    return cache
    except Exception as e:
        logger.warning(f"Failed to extract fighter data for custom character {slug}: {e}")
    return None


def extract_custom_character_aj(slug):
    """Get a custom character's animation archive: extract files.animFile
    from fighter.zip into the character dir (cached as aj_cache.dat)."""
    char_dir = STORAGE_PATH / 'custom_characters' / slug
    cache = char_dir / 'aj_cache.dat'
    if cache.exists():
        return cache
    fighter_json = char_dir / 'fighter.json'
    fighter_zip = char_dir / 'fighter.zip'
    if not fighter_json.exists() or not fighter_zip.exists():
        return None
    try:
        with open(fighter_json, 'r') as f:
            anim_file = (json.load(f).get('files') or {}).get('animFile')
        if not anim_file:
            return None
        with zipfile.ZipFile(fighter_zip) as zf:
            for n in zf.namelist():
                if n.split('/')[-1].lower() == anim_file.lower():
                    cache.write_bytes(zf.read(n))
                    return cache
    except Exception as e:
        logger.warning(f"Failed to extract AJ for custom character {slug}: {e}")
    return None


def custom_character_based_on(slug):
    """Donor skeleton for a custom character (e.g. Chun-Li -> Zelda),
    derived from a costume joint symbol 'Ply<Name>5K_...'."""
    import re
    fighter_json = STORAGE_PATH / 'custom_characters' / slug / 'fighter.json'
    if not fighter_json.exists():
        return None
    try:
        with open(fighter_json, 'r') as f:
            fighter = json.load(f)
        for costume in fighter.get('costumes', []):
            joint = (costume.get('file') or {}).get('jointSymbol') or ''
            m = re.match(r'Ply(.+?)5K', joint)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def find_vanilla_costume_file(character, costume_code):
    """Find a vanilla costume archive, tolerating both .dat/.usd and legacy folder names."""
    if character in ('Ice Climbers', 'Nana'):
        character = 'Nana' if costume_code.lower().startswith('plnn') else 'Ice Climbers'
    character_dir = VANILLA_ASSETS_DIR / character
    direct_path = find_vanilla_costume_archive(character_dir / costume_code, costume_code)
    if direct_path:
        return direct_path

    if not character_dir.exists():
        return None

    for folder in sorted(character_dir.iterdir()):
        if not folder.is_dir() or not folder.name.startswith('Pl'):
            continue
        if Path(folder.name).stem != costume_code:
            continue

        archive_path = find_vanilla_costume_archive(folder, costume_code)
        if archive_path:
            return archive_path

    # Older setup copied Red Falcon's portraits but looked for the literal
    # region placeholder "PlCaRe." instead of resolving .dat/.usd. Recover
    # missing canonical costumes from the user's own pristine reference bank.
    prefix = VIEWER_CHAR_PREFIXES.get(character)
    valid_codes = {f'{prefix}{color}' for color in VANILLA_CSS_COLOR_ORDER.get(character, [])}
    if prefix and costume_code in valid_codes:
        from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
        return ensure_vanilla_ref(f'{costume_code}.dat', storage_path=STORAGE_PATH)
    return None


def find_available_port():
    """Find an available port"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port
