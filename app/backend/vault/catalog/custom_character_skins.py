"""
A costume stored as a skin of a custom character: validating the costume ZIP,
its preview pictures, the main CSP (rendered from the character's default pose
or copied from an alternate), and filing special-fighter costumes (Giga Bowser,
the wireframes, the hands, Sandbag) under the custom character that owns them.

No routes. Used by the skin routes (vault/routes/custom_characters/skins.py) and
the unified import (vault/importing/unified/archive.py).
"""

import shutil
import tempfile
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from core.config import CUSTOM_CHARACTERS_PATH
from core.zip_tools import replace_zip_member
from core.path_safety import resolve_under_root
from vault.importing.custom_character_scan import _norm_fighter_name

logger = logging.getLogger(__name__)


def _validate_costume_zip(zip_bytes):
    """Check a costume zip has a usable DAT. Returns (dat_name, error)."""
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            dats = [n for n in zf.namelist()
                    if n.lower().endswith(('.dat', '.usd')) and not n.endswith('/')]
    except zipfile.BadZipFile:
        return None, 'Invalid or corrupted ZIP file'
    if not dats:
        return None, 'ZIP contains no costume .dat file'
    dat_name = Path(dats[0]).name
    # MexCostume.FromZip derives the costume key from stem[4:6]
    if len(Path(dat_name).stem) < 6:
        return None, f'Costume DAT name "{dat_name}" is too short (expected PlXxYy style)'
    return dat_name, None


def _extract_skin_previews(skins_dir, skin_id, zip_bytes):
    """Pull csp/stock PNGs out of a costume zip for vault display.
    Uses the canonical vault naming (_csp.png / _stc.png) so the shared
    skin-editing stack finds them."""
    import io
    has_csp = has_stock = False
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for n in zf.namelist():
            base = n.split('/')[-1].lower()
            if base in ('csp.png', 'portrait.png', 'select.png') and not has_csp:
                (skins_dir / f'{skin_id}_csp.png').write_bytes(zf.read(n))
                has_csp = True
            elif base in ('stc.png', 'stock.png', 'icon.png') and not has_stock:
                (skins_dir / f'{skin_id}_stc.png').write_bytes(zf.read(n))
                has_stock = True
    return has_csp, has_stock


def _dat_from_zip_bytes(zip_bytes):
    """Return (filename, bytes) for the first costume DAT/USD in a zip."""
    import io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = next((n for n in zf.namelist()
                     if n.lower().endswith(('.dat', '.usd')) and not n.endswith('/')), None)
        if not name:
            return None, None
        return Path(name).name, zf.read(name)


def _custom_pose_path(slug, pose_name):
    """A custom character's saved pose file. The pose name comes from the
    client, so this raises ValueError unless it stays inside the pose library
    ('..', absolute and drive paths are all refused)."""
    from shared.rendering.portrait import pose_character_key, poses_root

    char_key = f'custom_characters/{slug}/costumes'
    return resolve_under_root(poses_root(), f'{pose_character_key(char_key)}/{pose_name}.yml',
                              field='pose name')


def _custom_pose_render_bytes(slug, dat_bytes, dat_filename, pose_name, scales=(1, 4)):
    """Render a custom character DAT in a saved pose. Returns {scale: png_bytes}."""
    pose_name = (pose_name or '').strip()
    if not pose_name or not dat_bytes:
        return {}

    from shared.rendering.portrait import render_portrait

    char_key = f'custom_characters/{slug}/costumes'
    try:
        pose_path = _custom_pose_path(slug, pose_name)
    except ValueError as e:
        logger.warning(f"Default CSP pose '{pose_name}' refused for {slug}: {e}")
        return {}
    if not pose_path.exists():
        logger.info(f"Default CSP pose '{pose_name}' does not exist for {slug}; skipping render")
        return {}

    tmp = tempfile.mkdtemp(prefix='custom_skin_csp_')
    try:
        dat_path = Path(tmp) / Path(dat_filename or 'costume.dat').name
        dat_path.write_bytes(dat_bytes)
        rendered = {}
        for scale in scales:
            result = render_portrait(str(dat_path), char_key,
                                     pose_name=pose_name, scale=scale)
            # These bytes are stored AS the pose's portrait, so a default
            # render standing in for a failed pose must not be accepted.
            if result.pose_applied and result.path and Path(result.path).exists():
                rendered[scale] = Path(result.path).read_bytes()
            elif scale == 1:
                return {}
        return rendered
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _main_csp_filename(skin):
    return skin.get('csp_filename') or f"{skin.get('id')}_csp.png"


def _main_hd_csp_filename(skin):
    return skin.get('hd_csp_filename') or f"{skin.get('id')}_csp_hd.png"


def _write_main_csp(storage_dir, skin, sd_bytes, hd_bytes=None, pose_name=None, source='generated'):
    """Write a skin's main CSP files and tag their pose/source in metadata."""
    if not skin.get('id') or not sd_bytes:
        return False

    csp_filename = _main_csp_filename(skin)
    (storage_dir / csp_filename).write_bytes(sd_bytes)
    skin['has_csp'] = True
    skin['csp_filename'] = csp_filename
    skin['csp_source'] = source
    if pose_name:
        skin['csp_pose_name'] = pose_name
    else:
        skin.pop('csp_pose_name', None)

    if hd_bytes:
        hd_filename = _main_hd_csp_filename(skin)
        (storage_dir / hd_filename).write_bytes(hd_bytes)
        skin['has_hd_csp'] = True
        skin['hd_csp_filename'] = hd_filename
        skin['hd_csp_source'] = source
        skin['hd_csp_resolution'] = '4x'
        skin['hd_csp_size'] = '544x752'

    return True


def _copy_existing_pose_alt_to_main(storage_dir, skin, pose_name):
    """Use an existing alternate for pose_name as the main CSP without new alts."""
    if not pose_name:
        return False
    alts = skin.get('alternate_csps') or []
    sd_alt = next((a for a in alts if a.get('pose_name') == pose_name and not a.get('is_hd')), None)
    if not sd_alt:
        return False

    sd_path = storage_dir / sd_alt.get('filename', '')
    if not sd_path.exists():
        return False

    hd_alt = next((a for a in alts if a.get('pose_name') == pose_name and a.get('is_hd')), None)
    hd_bytes = None
    if hd_alt:
        hd_path = storage_dir / hd_alt.get('filename', '')
        if hd_path.exists():
            hd_bytes = hd_path.read_bytes()

    return _write_main_csp(
        storage_dir,
        skin,
        sd_path.read_bytes(),
        hd_bytes,
        pose_name=pose_name,
        source='alternate'
    )


def _ensure_custom_skin_main_csp(slug, storage_dir, skin, zip_path, zip_bytes, pose_name, replace_existing=False):
    """Ensure a skin has a main CSP by copying a matching alt or rendering one."""
    if not pose_name:
        return {'filled': False, 'source': None}

    main_path = storage_dir / _main_csp_filename(skin)
    if not replace_existing and skin.get('has_csp') and main_path.exists():
        return {'filled': False, 'source': 'existing'}

    if _copy_existing_pose_alt_to_main(storage_dir, skin, pose_name):
        replace_zip_member(zip_path, 'csp.png', (storage_dir / _main_csp_filename(skin)).read_bytes())
        return {'filled': True, 'source': 'alternate'}

    dat_name, dat_bytes = _dat_from_zip_bytes(zip_bytes)
    rendered = _custom_pose_render_bytes(slug, dat_bytes, dat_name, pose_name)
    if not rendered.get(1):
        return {'filled': False, 'source': None}

    _write_main_csp(
        storage_dir,
        skin,
        rendered[1],
        rendered.get(4),
        pose_name=pose_name,
        source='generated'
    )
    replace_zip_member(zip_path, 'csp.png', rendered[1])
    return {'filled': True, 'source': 'generated'}


def _store_custom_skin(slug, char_dir, entry, zip_bytes, dat_name, skin_name,
                       source_character=None, src_skin=None, requested_pose=''):
    """Write a costume zip into <custom char>/skins/ and append its entry to
    `entry['added_skins']` (the caller saves metadata). Shared by the
    add-skin route and the unified importer's special-fighter routing."""
    import uuid
    skin_id = uuid.uuid4().hex[:8]
    skins_dir = Path(char_dir) / 'skins'
    skins_dir.mkdir(exist_ok=True)
    zip_path = skins_dir / f'{skin_id}.zip'
    zip_path.write_bytes(zip_bytes)
    has_csp, has_stock = _extract_skin_previews(skins_dir, skin_id, zip_bytes)

    skin_entry = {
        'id': skin_id,
        # canonical field name so the shared skin-edit stack works on it
        'color': skin_name or Path(dat_name).stem,
        'filename': f'{skin_id}.zip',
        'dat_name': dat_name,
        'has_csp': has_csp,
        'has_stock': has_stock,
        'source_character': source_character,
        'date_added': datetime.now().isoformat(),
    }
    if has_csp:
        skin_entry['csp_source'] = 'uploaded'
    if src_skin is not None:
        # carry slippi status over from the canonical source skin
        for field in ('slippi_safe', 'slippi_tested', 'slippi_test_date', 'slippi_manual_override'):
            if field in src_skin:
                skin_entry[field] = src_skin[field]
    if not has_csp:
        pose_name = requested_pose or entry.get('default_pose') or ''
        csp_result = _ensure_custom_skin_main_csp(
            slug, skins_dir, skin_entry, zip_path, zip_bytes, pose_name
        )
        if csp_result.get('filled'):
            skin_entry['has_csp'] = True
    entry.setdefault('added_skins', []).append(skin_entry)
    return skin_entry


# Fighters that exist in every m-ex project but have no tile in the vault's
# Characters grid: they live as custom characters (Giga Bowser is seeded as a
# built-in; the others can be added by hand). A costume for one of them must
# never become a `characters` entry -- that is the "GIGAKOOPA tab" report.
SPECIAL_FIGHTER_NAMES = {
    'Giga Bowser', 'Wireframe Male', 'Wireframe Female',
    'Master Hand', 'Crazy Hand', 'Sandbag',
}


def find_custom_character_for_fighter(metadata, fighter_name):
    """The vault custom character that IS this special fighter, or None."""
    want = _norm_fighter_name(fighter_name)
    for entry in metadata.get('custom_characters', []):
        if _norm_fighter_name(entry.get('name', '')) == want:
            return entry
    return None


def add_special_fighter_costume(metadata, fighter_name, zip_bytes, skin_name):
    """Route an imported special-fighter costume (Giga Bowser, wireframes,
    hands, Sandbag) to its custom character instead of the Characters grid.

    Returns (skin_entry, None) on success or (None, reason) when it could not
    be placed -- the built-in fighter is not set up yet, or no custom
    character represents this fighter. The caller saves metadata."""
    entry = find_custom_character_for_fighter(metadata, fighter_name)
    if entry is None:
        if fighter_name == 'Giga Bowser':
            return None, ("Set up Giga Bowser first (Custom Characters → Giga Bowser), "
                          "then import this skin again")
        return None, (f"{fighter_name} skins need a {fighter_name} custom character; "
                      "Nucleus does not set one up yet")
    char_dir = CUSTOM_CHARACTERS_PATH / entry['slug']
    if not (char_dir / 'fighter.json').exists():
        return None, (f"Set up {entry.get('name', fighter_name)} first "
                      "(Custom Characters), then import this skin again")
    dat_name, err = _validate_costume_zip(zip_bytes)
    if err:
        return None, err
    skin_entry = _store_custom_skin(entry['slug'], char_dir, entry, zip_bytes,
                                    dat_name, skin_name)
    skin_entry['slug'] = entry['slug']
    logger.info(f"[OK] Routed {fighter_name} costume '{skin_name}' to custom character {entry['slug']}")
    return skin_entry, None
