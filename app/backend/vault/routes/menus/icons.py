"""
CSS Icon Grid mods.

A mod can arrive in two flavors:
  1. Loose PNGs named after characters
  2. Compiled CSS dat files (`MnSlChr.dat/.usd`, `mexSelectChr.dat`, optional `MxDt.dat`)

Regardless of source, on import we normalize to a tiny per-mod payload:

    storage/menus/css/icon_grid/
        metadata.json                       # catalog of installed mods
        <mod_id>/
            mod.json                        # per-mod manifest (icons + names + screenshot)
            screenshot.png                  # optional preview
            icons/
                <Character>.png             # one labeled icon per character

Anything else from the source archive is discarded. Some zips ship two packs
in one archive (e.g. both `mario.png` and `=mario.png`); we keep only the last
write per character — the user can split the zip if they want both variants.
"""

import shutil
import tempfile
import zipfile
import logging
from pathlib import Path
from flask import request, jsonify

from . import menus_bp
from vault.menus.store import ICON_GRID_PATH
from vault.menus.files import send_mod_zip
from vault.menus.icons import (_safe_filename, _load_catalog, _save_catalog, _attach_urls, _load_mod_json,
    _save_mod_json, install_icon_grid_mod, create_icon_grid_from_vanilla)

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/css/icon_grid/create', methods=['POST'])
def create_icon_grid_mod():
    """Create a new icon grid seeded with the vanilla icons. Body: {name?}."""
    try:
        payload = request.get_json(silent=True) or {}
        name = (payload.get('name') or '').strip() or 'New Icon Grid'
        mod = create_icon_grid_from_vanilla(name)
        return jsonify({'success': True, 'mod': mod})
    except RuntimeError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Create icon grid error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/list', methods=['GET'])
def list_icon_grid_mods():
    """List all installed CSS Icon Grid mods (catalog summaries)."""
    try:
        catalog = _load_catalog()
        mods = []
        for entry in catalog.get('mods', []):
            mod_id = entry.get('id')
            if not mod_id:
                continue
            # Re-attach URLs based on stored screenshot name
            out = dict(entry)
            if entry.get('screenshot'):
                out['screenshotUrl'] = f"/storage/menus/css/icon_grid/{mod_id}/{entry['screenshot']}"
            mods.append(out)
        return jsonify({'success': True, 'mods': mods})
    except Exception as e:
        logger.error(f'List icon grid mods error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/import', methods=['POST'])
def import_icon_grid_mod():
    """Import an icon grid mod. Accepts .zip (loose PNGs or DAT bundle) or a
    raw .dat/.usd compiled CSS file.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        fname_lower = file.filename.lower()
        is_zip = fname_lower.endswith('.zip')
        is_dat = fname_lower.endswith('.dat')
        is_usd = fname_lower.endswith('.usd')
        if not (is_zip or is_dat or is_usd):
            return jsonify({'success': False, 'error': 'File must be .zip, .dat, or .usd'}), 400

        name = (request.form.get('name') or '').strip() or Path(file.filename).stem
        description = (request.form.get('description') or '').strip()

        # Raw .dat/.usd: wrap in a temp zip so the installer's single code path
        # (extract → detect → label) handles it transparently. A raw CSS dat
        # encodes only one icon set, so the multi-pack case can't apply.
        if is_dat or is_usd:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                raw_bytes = file.read()
                with zipfile.ZipFile(tmp_path, 'w') as zf:
                    zf.writestr(file.filename, raw_bytes)
                try:
                    mods = install_icon_grid_mod(tmp_path, name=name, description=description)
                except RuntimeError as e:
                    return jsonify({'success': False, 'error': str(e)}), 400
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        else:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                file.save(str(tmp_path))
                try:
                    mods = install_icon_grid_mod(tmp_path, name=name, description=description)
                except zipfile.BadZipFile:
                    return jsonify({'success': False, 'error': 'Invalid or corrupt zip file'}), 400
                except RuntimeError as e:
                    return jsonify({'success': False, 'error': str(e)}), 400
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

        return jsonify({'success': True, 'mods': mods, 'imported_count': len(mods)})
    except Exception as e:
        logger.error(f'Import icon grid mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/icons', methods=['GET'])
def get_icon_grid_icons(mod_id):
    """Return the full mod.json for a single mod, with URLs."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return jsonify({'success': True, 'mod': _attach_urls(mod)})
    except Exception as e:
        logger.error(f'Get icon grid icons error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/update/<mod_id>', methods=['POST'])
def update_icon_grid_mod(mod_id):
    """Update name/description of an icon grid mod."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.json or {}
        if 'name' in payload and payload['name'] is not None:
            new_name = str(payload['name']).strip()
            if new_name:
                mod['name'] = new_name
        if 'description' in payload and payload['description'] is not None:
            mod['description'] = str(payload['description'])

        _save_mod_json(mod_id, mod)

        # Update catalog summary too
        catalog = _load_catalog()
        for entry in catalog.get('mods', []):
            if entry.get('id') == mod_id:
                entry['name'] = mod['name']
                entry['description'] = mod.get('description', '')
                break
        _save_catalog(catalog)

        return jsonify({'success': True, 'mod': _attach_urls(mod)})
    except Exception as e:
        logger.error(f'Update icon grid mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/screenshot', methods=['POST'])
def set_icon_grid_image(mod_id):
    """Replace an icon grid mod's preview screenshot with an uploaded image."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        f = request.files.get('screenshot') or request.files.get('file')
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400

        mod_dir = ICON_GRID_PATH / mod_id
        mod_dir.mkdir(parents=True, exist_ok=True)
        f.save(str(mod_dir / 'screenshot.png'))
        mod['screenshot'] = 'screenshot.png'
        _save_mod_json(mod_id, mod)

        # The list reads the catalog entry's screenshot name for the static URL.
        catalog = _load_catalog()
        for entry in catalog.get('mods', []):
            if entry.get('id') == mod_id:
                entry['screenshot'] = 'screenshot.png'
                break
        _save_catalog(catalog)

        return jsonify({'success': True,
                        'screenshotUrl': f'/storage/menus/css/icon_grid/{mod_id}/screenshot.png'})
    except Exception as e:
        logger.error(f'Set icon grid image error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/export', methods=['GET'])
def export_icon_grid_mod(mod_id):
    """Download an icon grid mod's files as a zip."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return send_mod_zip(ICON_GRID_PATH / mod_id, mod.get('name') or mod_id)
    except Exception as e:
        logger.error(f'Export icon grid mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/relabel', methods=['POST'])
def relabel_icon(mod_id):
    """Change the character label on a single icon tile.

    Body: {old_character: "Mario", new_character: "Ganondorf"}
    Renames the file on disk + updates mod.json.
    """
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.json or {}
        old_char = (payload.get('old_character') or '').strip()
        new_char = (payload.get('new_character') or '').strip()
        if not old_char or not new_char:
            return jsonify({'success': False, 'error': 'old_character and new_character required'}), 400
        if old_char == new_char:
            return jsonify({'success': True, 'mod': _attach_urls(mod)})

        icons_dir = ICON_GRID_PATH / mod_id / 'icons'
        entry = next((e for e in mod.get('icons', []) if e.get('character') == old_char), None)
        if not entry:
            return jsonify({'success': False, 'error': f'No icon labeled "{old_char}"'}), 404

        old_file = icons_dir / entry['icon']
        new_file_name = f'{_safe_filename(new_char)}.png'
        new_file = icons_dir / new_file_name

        if old_file.exists():
            old_file.rename(new_file)

        entry['character'] = new_char
        entry['icon'] = new_file_name
        _save_mod_json(mod_id, mod)

        return jsonify({'success': True, 'mod': _attach_urls(mod)})
    except Exception as e:
        logger.error(f'Relabel icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/replace_icon', methods=['POST'])
def replace_icon(mod_id):
    """Replace a single icon image. Multipart form: character + file (image)."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        character = (request.form.get('character') or '').strip()
        if not character:
            return jsonify({'success': False, 'error': 'character is required'}), 400
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        img = request.files['file']
        if not img.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        entry = next((e for e in mod.get('icons', []) if e.get('character') == character), None)
        if not entry:
            return jsonify({'success': False, 'error': f'No icon labeled "{character}"'}), 404

        icons_dir = ICON_GRID_PATH / mod_id / 'icons'
        icon_name = entry['icon']
        dest = icons_dir / icon_name
        img.save(str(dest))

        _save_mod_json(mod_id, mod)
        return jsonify({'success': True, 'mod': _attach_urls(mod)})
    except Exception as e:
        logger.error(f'Replace icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/delete_icon', methods=['POST'])
def delete_icon(mod_id):
    """Delete a single icon from the mod. Body: {character: "Mario"}."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.json or {}
        character = (payload.get('character') or '').strip()
        if not character:
            return jsonify({'success': False, 'error': 'character is required'}), 400

        icons = mod.get('icons', [])
        entry = next((e for e in icons if e.get('character') == character), None)
        if not entry:
            return jsonify({'success': False, 'error': f'No icon labeled "{character}"'}), 404

        icons_dir = ICON_GRID_PATH / mod_id / 'icons'
        icon_file = icons_dir / entry['icon']
        if icon_file.exists():
            icon_file.unlink()

        mod['icons'] = [e for e in icons if e.get('character') != character]
        _save_mod_json(mod_id, mod)

        catalog = _load_catalog()
        for cat_entry in catalog.get('mods', []):
            if cat_entry.get('id') == mod_id:
                cat_entry['icon_count'] = len(mod['icons'])
                break
        _save_catalog(catalog)

        return jsonify({'success': True, 'mod': _attach_urls(mod)})
    except Exception as e:
        logger.error(f'Delete icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/<mod_id>/add_icon', methods=['POST'])
def add_icon(mod_id):
    """Add a new icon to the mod. Multipart form: character + file (image)."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        character = (request.form.get('character') or '').strip()
        if not character:
            return jsonify({'success': False, 'error': 'character is required'}), 400
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        img = request.files['file']
        if not img.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        existing = next((e for e in mod.get('icons', []) if e.get('character') == character), None)
        if existing:
            return jsonify({'success': False, 'error': f'Icon for "{character}" already exists. Use replace instead.'}), 400

        icons_dir = ICON_GRID_PATH / mod_id / 'icons'
        icons_dir.mkdir(parents=True, exist_ok=True)
        icon_name = f'{_safe_filename(character)}.png'
        dest = icons_dir / icon_name
        img.save(str(dest))

        mod.setdefault('icons', []).append({'character': character, 'icon': icon_name})
        _save_mod_json(mod_id, mod)

        catalog = _load_catalog()
        for cat_entry in catalog.get('mods', []):
            if cat_entry.get('id') == mod_id:
                cat_entry['icon_count'] = len(mod['icons'])
                break
        _save_catalog(catalog)

        return jsonify({'success': True, 'mod': _attach_urls(mod)})
    except Exception as e:
        logger.error(f'Add icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/icon_grid/delete/<mod_id>', methods=['POST'])
def delete_icon_grid_mod(mod_id):
    """Delete an icon grid mod and its files."""
    try:
        catalog = _load_catalog()
        mods = catalog.get('mods', [])
        idx = next((i for i, m in enumerate(mods) if m.get('id') == mod_id), -1)
        if idx < 0:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        mod_dir = ICON_GRID_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(mod_dir, ignore_errors=True)

        mods.pop(idx)
        _save_catalog(catalog)
        logger.info(f'[OK] Deleted icon grid mod: {mod_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Delete icon grid mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
