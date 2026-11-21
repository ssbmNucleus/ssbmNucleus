"""
Menu background mods (one pool for the CSS and the SSS): the catalog and
importing a pack, which extracts the background model/animation bundle from a
MnSlChr or MnSlMap file with HSDRawViewer.
"""

import shutil
import tempfile
import uuid
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from vault.menus.store import BG_METADATA, BG_PATH, load_catalog, load_mod_json, save_catalog, save_mod_json
from vault.menus.files import (
    find_menu_dat_by_roots as _find_menu_dat_by_roots, find_mnslchr_dat as _find_mnslchr_dat,
    find_mnslmap_dat as _find_mnslmap_dat, _find_screenshot, _safe_extract_zip)
from vault.menus.hsd import _run_hsd_cli

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CSS Background mod catalog
# ─────────────────────────────────────────────────────────────────────────────

def _load_bg_catalog():
    return load_catalog(BG_METADATA, version='1.0')


def _save_bg_catalog(data):
    save_catalog(BG_METADATA, data)


def _load_bg_mod_json(mod_id):
    return load_mod_json(BG_PATH, mod_id)


def _save_bg_mod_json(mod_id, mod):
    save_mod_json(BG_PATH, mod_id, mod)


def _attach_bg_urls(mod):
    """Add screenshot URL to a background mod dict."""
    out = dict(mod)
    mod_id = mod.get('id')
    if not mod_id:
        return out
    base = f'/storage/menus/css/background/{mod_id}'
    if mod.get('screenshot'):
        out['screenshotUrl'] = f"{base}/{mod['screenshot']}"
    return out


def import_bg_archive(src_path, original_filename, name=None, description='',
                      menu_type=None):
    """Import a menu background mod from a file on disk.

    Accepts .zip (containing MnSlChr.dat/.usd or MnSlMap.dat/.usd) or a raw
    .dat/.usd file. Auto-detects CSS vs SSS source and extracts the background
    model/animation bundle via HSDRawViewer. `menu_type` ('css'|'sss') is the
    screen the user imported FROM: a full menu pack can contain BOTH MnSlChr
    and MnSlMap, and before this hint existed such zips always yielded the CSS
    background even when imported as an SSS mod. The detected source is
    recorded on the mod so each screen's vault page lists only its own kind.

    Returns the mod dict (without URLs). Raises ValueError for bad input,
    RuntimeError for extraction failures. Shared by the dedicated route and
    the unified /import/file dispatcher.
    """
    fname_lower = original_filename.lower()
    is_zip = fname_lower.endswith('.zip')
    name = (name or '').strip() or Path(original_filename).stem
    description = (description or '').strip()

    with tempfile.TemporaryDirectory(prefix='menubg_') as tmp:
        temp_root = Path(tmp)

        if is_zip:
            extract_dir = temp_root / 'extracted'
            extract_dir.mkdir()
            try:
                _safe_extract_zip(Path(src_path), extract_dir)
            except zipfile.BadZipFile:
                raise ValueError('Invalid or corrupt zip file')
            # Prefer the screen the user is importing for; fall back to the
            # other file when the preferred one isn't in the archive.
            if menu_type == 'sss':
                finders = ((_find_mnslmap_dat, '--sss-bg'),
                           (_find_mnslchr_dat, '--css-bg'))
            else:
                finders = ((_find_mnslchr_dat, '--css-bg'),
                           (_find_mnslmap_dat, '--sss-bg'))
            source_dat, hsd_cmd = None, finders[0][1]
            for finder, cmd in finders:
                found = finder(extract_dir)
                if found is not None:
                    source_dat, hsd_cmd = found, cmd
                    break
            if source_dat is None:
                # Menu files travel under any name ("Halo3CSS.dat"); the
                # root symbol says which screen a DAT really is.
                source_dat, hsd_cmd = _find_menu_dat_by_roots(extract_dir, menu_type)
            screenshot_src = _find_screenshot(extract_dir)
        else:
            source_dat = temp_root / Path(original_filename).name
            shutil.copyfile(str(src_path), str(source_dat))
            screenshot_src = None
            # A raw file IS one screen's DAT -- detect by filename (the intent
            # hint can't change what the file contains).
            if 'mnslmap' in fname_lower:
                hsd_cmd = '--sss-bg'
            else:
                hsd_cmd = '--css-bg'

        if source_dat is None or not source_dat.exists():
            raise ValueError('No MnSlChr or MnSlMap .dat/.usd found in upload')

        export_dir = temp_root / 'bg_export'
        export_dir.mkdir()
        result = _run_hsd_cli([hsd_cmd, 'export', str(source_dat), str(export_dir)])
        if result is None:
            # Try the other command in case detection was wrong
            alt_cmd = '--sss-bg' if hsd_cmd == '--css-bg' else '--css-bg'
            result = _run_hsd_cli([alt_cmd, 'export', str(source_dat), str(export_dir)])
            if result is not None:
                hsd_cmd = alt_cmd
        if result is None:
            raise RuntimeError('Failed to extract background from DAT')
        source_screen = 'css' if hsd_cmd == '--css-bg' else 'sss'

        bg_dat = export_dir / 'background.dat'
        if not bg_dat.exists():
            raise RuntimeError('HSDRawViewer did not produce background.dat')

        # Create mod entry
        mod_id = str(uuid.uuid4())[:8]
        mod_dir = BG_PATH / mod_id
        mod_dir.mkdir(parents=True, exist_ok=True)

        # Copy background.dat
        shutil.copy(str(bg_dat), str(mod_dir / 'background.dat'))

        # Copy screenshot if available
        screenshot_filename = None
        if screenshot_src is not None and screenshot_src.exists():
            screenshot_filename = f'screenshot{screenshot_src.suffix.lower()}'
            shutil.copy(str(screenshot_src), str(mod_dir / screenshot_filename))

        mod = {
            'id': mod_id,
            'name': name,
            'description': description,
            'screenshot': screenshot_filename,
            'source': source_screen,
            'created': datetime.now().isoformat(),
        }
        _save_bg_mod_json(mod_id, mod)

        catalog = _load_bg_catalog()
        catalog.setdefault('mods', []).append({
            'id': mod_id,
            'name': name,
            'description': description,
            'screenshot': screenshot_filename,
            'source': source_screen,
            'created': mod['created'],
        })
        _save_bg_catalog(catalog)

        logger.info(f'[OK] Imported {source_screen.upper()} background mod: {name} ({mod_id})')
        return mod
