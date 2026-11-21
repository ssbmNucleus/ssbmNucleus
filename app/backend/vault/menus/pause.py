"""
Pause screen (GmPause) mods: the catalog, the vanilla texture manifest, importing
GmPause files or a picture, and the editable texture set of a mod.
"""

import json
import shutil
import tempfile
import uuid
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from shared.vanilla_extract.menu_refs import pause_dir
from vault.menus.store import (
    PAUSE_METADATA, PAUSE_PATH, load_catalog, load_mod_json, save_catalog, save_mod_json)
from vault.menus.files import _find_screenshot, _safe_extract_zip
from vault.menus.hsd import _run_hsd_cli

logger = logging.getLogger(__name__)


IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp')

# Vanilla GmPause textures — the base set for per-texture editing of mods that
# didn't ship a full dat. Derived from the user's own GmPause.usd at first run
# and on project open (menu_refs); nothing ships, so before that there is no
# vanilla base. Resolve per call so a derivation that lands mid-session is
# picked up.
def VANILLA_TEX_DIR():
    return pause_dir()


def _load_vanilla_manifest():
    try:
        with open(VANILLA_TEX_DIR() / 'manifest.json', 'r', encoding='utf-8') as f:
            return json.load(f).get('textures', [])
    except Exception as e:
        logger.warning(f'Vanilla pause texture manifest unavailable: {e}')
        return []


def _load_pause_catalog():
    return load_catalog(PAUSE_METADATA, '1.0')


def _save_pause_catalog(data):
    save_catalog(PAUSE_METADATA, data)


def _attach_pause_urls(mod):
    out = dict(mod)
    if mod.get('id'):
        out['imageUrl'] = f"/api/mex/menus/pause/image/{mod['id']}"
    return out


def _find_gmpause_files(directory):
    """All GmPause*.dat/.usd files in an extracted directory, sorted by name."""
    found = []
    for p in sorted(Path(directory).rglob('*')):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if name_lower.startswith('gmpause') and name_lower.endswith(('.dat', '.usd')):
            found.append(p)
    return found


def looks_like_pause_zip(zip_path):
    """Returns True if the zip contains a GmPause dat/usd file."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for n in zf.namelist():
                if n.startswith('__MACOSX'):
                    continue
                base = Path(n).name.lower()
                if base.startswith('gmpause') and base.endswith(('.dat', '.usd')):
                    return True
        return False
    except zipfile.BadZipFile:
        return False


def _variant_label(dat_path, base_name):
    """Derive a per-variant mod name from the GmPause filename.

    `GmPause(white).dat` → `<base_name> (white)`; a bare `GmPause.dat`
    just keeps base_name.
    """
    stem = dat_path.stem
    suffix = stem[len('gmpause'):].strip(' _-()') if stem.lower().startswith('gmpause') else stem
    return f'{base_name} ({suffix})' if suffix else base_name


def _import_pause_dat(dat_path, name, description, screenshot_src, catalog):
    """Dump a compiled GmPause's textures into a new mod. Returns the mod dict
    (without URLs) or raises RuntimeError."""
    with tempfile.TemporaryDirectory(prefix='pause_export_') as tmp:
        export_dir = Path(tmp) / 'dump'
        export_dir.mkdir()
        result = _run_hsd_cli(['--pause-screen', 'export', str(dat_path), str(export_dir)])
        if result is None:
            raise RuntimeError(f'Failed to extract textures from {dat_path.name}')

        manifest_path = export_dir / 'manifest.json'
        if not manifest_path.exists():
            raise RuntimeError('HSDRawViewer did not produce a texture manifest')
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        entries = manifest.get('textures', [])
        if not entries:
            raise RuntimeError(f'No textures found in {dat_path.name}')

        mod_id = str(uuid.uuid4())[:8]
        mod_dir = PAUSE_PATH / mod_id
        tex_dir = mod_dir / 'textures'
        tex_dir.mkdir(parents=True, exist_ok=True)

        textures = []
        for entry in entries:
            src = export_dir / entry['filename']
            if not src.exists():
                continue
            tex_name = f"t{entry['index']}.png"
            shutil.copy(str(src), str(tex_dir / tex_name))
            textures.append({
                'index': entry['index'],
                'width': entry['width'],
                'height': entry['height'],
                'format': entry['format'],
                'file': tex_name,
            })

        screenshot_filename = None
        if screenshot_src is not None and screenshot_src.exists():
            screenshot_filename = f'screenshot{screenshot_src.suffix.lower()}'
            shutil.copy(str(screenshot_src), str(mod_dir / screenshot_filename))

        mod = {
            'id': mod_id,
            'name': name,
            'description': description,
            'source': 'dat',
            'screenshot': screenshot_filename,
            'textures': textures,
            'created': datetime.now().isoformat(),
        }
        save_mod_json(PAUSE_PATH, mod_id, mod)
        catalog.setdefault('mods', []).append({
            'id': mod_id,
            'name': name,
            'description': description,
            'source': 'dat',
            'created': mod['created'],
        })
        logger.info(f'[OK] Imported pause mod: {name} ({mod_id}) — {len(textures)} textures')
        return mod


def install_pause_mods_from_zip(zip_path, name=None, description=''):
    """Import every GmPause variant in a zip. Returns list of mod dicts with
    URLs attached. Raises RuntimeError when nothing recognizable is found."""
    zip_path = Path(zip_path)
    base_name = (name or zip_path.stem).strip() or zip_path.stem

    with tempfile.TemporaryDirectory(prefix='pause_import_') as tmp:
        extract_dir = Path(tmp) / 'extracted'
        extract_dir.mkdir()
        _safe_extract_zip(zip_path, extract_dir)

        dats = _find_gmpause_files(extract_dir)
        if not dats:
            raise RuntimeError('No GmPause .dat/.usd found in archive')

        screenshot_src = _find_screenshot(extract_dir)
        multi = len(dats) > 1

        catalog = _load_pause_catalog()
        installed = []
        for dat in dats:
            mod_name = _variant_label(dat, base_name) if multi else base_name
            mod = _import_pause_dat(dat, mod_name, description, screenshot_src, catalog)
            installed.append(_attach_pause_urls(mod))
        _save_pause_catalog(catalog)
        return installed


def pause_preview_path(mod_id, mod=None):
    """The file get_pause_image serves for a mod (zip screenshot, uploaded
    picture, or the main (largest) extracted texture), or None."""
    mod = mod if mod is not None else load_mod_json(PAUSE_PATH, mod_id)
    if not mod:
        return None
    mod_dir = PAUSE_PATH / mod_id
    candidates = []
    if mod.get('screenshot'):
        candidates.append(mod_dir / mod['screenshot'])
    candidates.append(mod_dir / 'picture.png')
    for tex in sorted(mod.get('textures', []),
                      key=lambda t: t.get('width', 0) * t.get('height', 0),
                      reverse=True):
        candidates.append(mod_dir / 'textures' / tex['file'])
    return next((p for p in candidates if p.exists()), None)


def import_pause_picture(data, name, description=''):
    """Store one picture as a pause mod that replaces the central pause
    graphic on install. Returns the mod dict with URLs attached. Shared by the
    dedicated route and the unified /import/file dispatcher."""
    name = (name or '').strip() or 'Pause picture'
    mod_id = str(uuid.uuid4())[:8]
    mod_dir = PAUSE_PATH / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / 'picture.png').write_bytes(data)

    mod = {
        'id': mod_id,
        'name': name,
        'description': description or '',
        'source': 'image',
        'created': datetime.now().isoformat(),
    }
    save_mod_json(PAUSE_PATH, mod_id, mod)
    catalog = _load_pause_catalog()
    catalog.setdefault('mods', []).append({
        'id': mod_id,
        'name': name,
        'description': description or '',
        'source': 'image',
        'created': mod['created'],
    })
    _save_pause_catalog(catalog)
    logger.info(f'[OK] Imported pause picture mod: {name} ({mod_id})')
    return _attach_pause_urls(mod)


def _main_pair_indices(mod):
    """Indices of the 88x72 'main graphic' slots (vanilla t4 + t10). The game
    layers both at the same screen position, so the editor treats them as one
    slot — replacing or reverting one must do both."""
    return [t['index'] for t in mod.get('textures', [])
            if t.get('width') == 88 and t.get('height') == 72]


def _ensure_textures(mod):
    """Give a mod a full per-index texture set so it can be edited slot-by-slot.

    Dat-sourced mods already have one. Picture mods get seeded from the vanilla
    texture assets, with the picture dropped into the two 88x72 "main" slots
    (marked replaced so install encodes them RGB5A3 — same as the picture
    install path). Returns the (possibly updated) mod, or raises RuntimeError."""
    if mod.get('textures'):
        return mod

    vanilla = _load_vanilla_manifest()
    if not vanilla:
        raise RuntimeError('Vanilla pause textures unavailable; cannot edit this mod')

    mod_dir = PAUSE_PATH / mod['id']
    tex_dir = mod_dir / 'textures'
    tex_dir.mkdir(parents=True, exist_ok=True)
    picture = mod_dir / 'picture.png'

    MAIN_SLOTS = {t['index'] for t in vanilla if t['width'] == 88 and t['height'] == 72}

    textures = []
    for t in vanilla:
        tex_name = f"t{t['index']}.png"
        entry = {
            'index': t['index'],
            'width': t['width'],
            'height': t['height'],
            'format': t['format'],
            'file': tex_name,
        }
        if t['index'] in MAIN_SLOTS and picture.exists():
            shutil.copy(str(picture), str(tex_dir / tex_name))
            entry['replaced'] = True
        else:
            shutil.copy(str(VANILLA_TEX_DIR() / t['file']), str(tex_dir / tex_name))
        textures.append(entry)

    mod['textures'] = textures
    save_mod_json(PAUSE_PATH, mod['id'], mod)
    logger.info(f"[OK] Seeded per-texture set for pause mod {mod['id']} ({mod.get('source')})")
    return mod
