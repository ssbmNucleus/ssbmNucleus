"""
Menu mods through the import endpoint: the menu kind hints that skip detection,
where each kind lands in the vault, and importing pictures, backgrounds and
HUD typefaces with the menus engine (vault/menus/).
"""

import zipfile
from pathlib import Path
from vault.menus.pause import (install_pause_mods_from_zip, looks_like_pause_zip,
    import_pause_picture)
from vault.menus.percent import install_percent_mods_from_zip
from vault.menus.doors import import_door_image
from vault.menus.backgrounds import import_bg_archive
from vault.importing.unified.detection import IMAGE_EXTS


# Explicit menu-kind hints (from the choice dialog, or a website link) that
# skip detection and go straight to that kind's installer.
_MENU_HINT_TYPES = {'css_doors', 'pause_picture', 'pause_screen', 'percent_font',
                    'ready_go', 'css_background', 'sss_background'}

# Where each menu kind lands in the vault -- appended to success messages so
# the import toast tells the user where to look.
_MENU_LOCATIONS = {
    'css_icon_grid': 'Menus › Character Select › Icon Grids',
    'css_background': 'Menus › Character Select › Backgrounds',
    'css_doors': 'Menus › Character Select › Doors',
    'sss_background': 'Menus › Stage Select › Backgrounds',
    'pause_screen': 'Menus › In-Game HUD › Pause Screens',
    'percent_font': 'Menus › In-Game HUD › Percent Fonts',
    'ready_go': 'Menus › In-Game HUD › Ready / Go / Game',
}


def _located(message, kind):
    loc = _MENU_LOCATIONS.get(kind)
    return f'{message} — {loc}' if loc else message


# ── menu kinds ───────────────────────────────────────────────────────────────

def _mnslchr_is_ambiguous(shallow):
    """A compiled MnSlChr with no loose '=' icon PNGs: icon grid or backdrop?"""
    return (shallow['type'] == 'css_icon_grid'
            and 'css_background' in shallow['candidates']
            and not shallow['detail'].get('icon_pngs'))


def _archive_images(temp_zip_path):
    with zipfile.ZipFile(temp_zip_path, 'r') as zf:
        names = [n for n in zf.namelist() if not n.endswith('/')
                 and Path(n).suffix.lower() in IMAGE_EXTS
                 and not n.startswith('__MACOSX')
                 and not Path(n).name.startswith('.')]
        return [(n, zf.read(n)) for n in names]


def _import_images_as(temp_zip_path, kind, custom_title):
    """Every picture in the archive becomes one door mod / pause picture."""
    try:
        images = _archive_images(temp_zip_path)
    except zipfile.BadZipFile:
        return {'success': False, 'error': 'Invalid or corrupt zip file'}, 400
    if not images:
        return {'success': False, 'error': 'No image found in the upload'}, 400
    mods = []
    for member, data in images:
        name = custom_title if (custom_title and len(images) == 1) else Path(member).stem
        if kind == 'css_doors':
            mods.append(import_door_image(data, name))
        else:
            mods.append(import_pause_picture(data, name))
    names = ', '.join(m['name'] for m in mods)
    if kind == 'css_doors':
        noun, menu_kind = 'door texture(s)', 'css_doors'
    else:
        noun, menu_kind = 'pause picture(s)', 'pause_screen'
    return {
        'success': True,
        'type': 'menu_mod',
        'menu_mod_type': menu_kind,
        'mods': mods,
        'imported_count': len(mods),
        'message': _located(f'Imported {len(mods)} {noun}: {names}', menu_kind),
    }, 200


def _import_background(temp_zip_path, filename, menu_type, custom_title):
    # The archive on disk is always a zip (raw dats are wrapped at entry), so
    # hand the importer a zip-suffixed name regardless of the upload's name.
    try:
        mod = import_bg_archive(temp_zip_path, Path(filename).stem + '.zip',
                                name=custom_title or Path(filename).stem,
                                menu_type=menu_type)
    except (ValueError, RuntimeError) as e:
        return {'success': False, 'error': str(e)}, 400
    kind = 'sss_background' if mod.get('source') == 'sss' else 'css_background'
    return {
        'success': True,
        'type': 'menu_mod',
        'menu_mod_type': kind,
        'mod': mod,
        'mods': [mod],
        'imported_count': 1,
        'message': _located(f"Imported menu background: {mod['name']}", kind),
    }, 200


def _percent_result(mods):
    cats = {c for m in mods for c in (m.get('categories') or [])}
    kind = 'ready_go' if cats == {'readygo'} else 'percent_font'
    names = ', '.join(m.get('name', '?') for m in mods)
    noun = 'Ready/Go pack(s)' if kind == 'ready_go' else 'percent font mod(s)'
    return {
        'success': True,
        'type': 'menu_mod',
        'menu_mod_type': kind,
        'mods': mods,
        'imported_count': len(mods),
        'message': _located(f'Imported {len(mods)} {noun}: {names}', kind),
    }


def _import_menu_by_hint(temp_zip_path, filename, mod_type, custom_title):
    """Dispatch an explicit menu-kind hint straight to that kind's installer."""
    try:
        if mod_type in ('css_doors', 'pause_picture'):
            return _import_images_as(temp_zip_path, mod_type, custom_title)
        if mod_type == 'pause_screen':
            if looks_like_pause_zip(temp_zip_path):
                mods = install_pause_mods_from_zip(
                    temp_zip_path, name=custom_title or Path(filename).stem)
                names = ', '.join(m.get('name', '?') for m in mods)
                return {
                    'success': True, 'type': 'menu_mod', 'menu_mod_type': 'pause_screen',
                    'mods': mods, 'imported_count': len(mods),
                    'message': _located(f'Imported {len(mods)} pause screen mod(s): {names}', 'pause_screen'),
                }, 200
            return _import_images_as(temp_zip_path, 'pause_picture', custom_title)
        if mod_type in ('percent_font', 'ready_go'):
            mods = install_percent_mods_from_zip(
                temp_zip_path, name=custom_title or Path(filename).stem)
            return _percent_result(mods), 200
        if mod_type in ('css_background', 'sss_background'):
            return _import_background(temp_zip_path, filename, mod_type[:3], custom_title)
    except zipfile.BadZipFile:
        return {'success': False, 'error': 'Invalid or corrupt zip file'}, 400
    except RuntimeError as e:
        return {'success': False, 'error': str(e)}, 400
    return {'success': False, 'error': f'Unknown import kind: {mod_type}'}, 400
