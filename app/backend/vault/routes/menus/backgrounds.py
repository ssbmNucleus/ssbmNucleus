"""
Menu background mods (shared CSS/SSS pool).

A background mod is a normalized `background.dat` bundle (extracted from a
MnSlChr or MnSlMap dat via HSDRawViewer) plus an optional screenshot:

    storage/menus/css/background/
        metadata.json               # catalog of installed mods
        <mod_id>/
            mod.json                # per-mod manifest
            background.dat          # the model/animation bundle
            screenshot.png          # optional preview

The same pool installs into either the CSS (MnSlChr.usd) or the SSS
(MnSlMap.usd) of the currently loaded MEX project.
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from flask import request, jsonify

from . import menus_bp
from vault.menus.store import BG_PATH
from vault.menus.files import send_mod_zip
from vault.menus.backgrounds import (_load_bg_catalog, _save_bg_catalog, _load_bg_mod_json,
    _save_bg_mod_json, _attach_bg_urls, import_bg_archive)

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/css/background/list', methods=['GET'])
@menus_bp.route('/api/mex/menus/background/list', methods=['GET'])
def list_bg_mods():
    """List installed background mods. ?menu_type=css|sss filters to that
    screen's backgrounds (a CSS backdrop and an SSS backdrop are different
    models); entries imported before the source was recorded show on both."""
    try:
        menu_type = request.args.get('menu_type')
        catalog = _load_bg_catalog()
        mods = []
        for entry in catalog.get('mods', []):
            mod_id = entry.get('id')
            if not mod_id:
                continue
            src = entry.get('source')
            if menu_type in ('css', 'sss') and src and src != menu_type:
                continue
            out = dict(entry)
            if entry.get('screenshot'):
                out['screenshotUrl'] = f"/storage/menus/css/background/{mod_id}/{entry['screenshot']}"
            mod_json = _load_bg_mod_json(mod_id)
            if mod_json:
                out['includeScene'] = mod_json.get('includeScene', False)
            mods.append(out)
        return jsonify({'success': True, 'mods': mods})
    except Exception as e:
        logger.error(f'List bg mods error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/background/import', methods=['POST'])
@menus_bp.route('/api/mex/menus/background/import', methods=['POST'])
def import_bg_mod():
    """Import a menu background mod (shared CSS/SSS pool)."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        fname_lower = file.filename.lower()
        if not fname_lower.endswith(('.zip', '.dat', '.usd')):
            return jsonify({'success': False, 'error': 'File must be .zip, .dat, or .usd'}), 400

        suffix = Path(file.filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        try:
            mod = import_bg_archive(tmp_path, file.filename,
                                    name=request.form.get('name'),
                                    description=request.form.get('description'),
                                    menu_type=request.form.get('menuType'))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return jsonify({'success': True, 'mod': _attach_bg_urls(mod)})

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error(f'Import bg mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/background/delete/<mod_id>', methods=['POST'])
@menus_bp.route('/api/mex/menus/background/delete/<mod_id>', methods=['POST'])
def delete_bg_mod(mod_id):
    """Delete a background mod and its files."""
    try:
        catalog = _load_bg_catalog()
        mods = catalog.get('mods', [])
        idx = next((i for i, m in enumerate(mods) if m.get('id') == mod_id), -1)
        if idx < 0:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        mod_dir = BG_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(mod_dir, ignore_errors=True)

        mods.pop(idx)
        _save_bg_catalog(catalog)
        logger.info(f'[OK] Deleted background mod: {mod_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Delete bg mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/background/update/<mod_id>', methods=['POST'])
def update_bg_mod_settings(mod_id):
    """Update settings for a background mod (e.g. includeScene toggle)."""
    try:
        mod = _load_bg_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        data = request.get_json(silent=True) or {}
        if 'includeScene' in data:
            mod['includeScene'] = bool(data['includeScene'])
        renamed = False
        if 'name' in data and data['name'] is not None:
            new_name = str(data['name']).strip()
            if new_name:
                mod['name'] = new_name
                renamed = True

        _save_bg_mod_json(mod_id, mod)

        # Keep the catalog summary (what `list` reads) in sync on rename.
        if renamed:
            catalog = _load_bg_catalog()
            entry = next((m for m in catalog.get('mods', []) if m.get('id') == mod_id), None)
            if entry is not None:
                entry['name'] = mod['name']
                _save_bg_catalog(catalog)

        return jsonify({'success': True, 'mod': _attach_bg_urls(mod)})
    except Exception as e:
        logger.error(f'Update bg mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/background/<mod_id>/screenshot', methods=['POST'])
def set_bg_image(mod_id):
    """Replace a background mod's preview screenshot with an uploaded image."""
    try:
        mod = _load_bg_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        f = request.files.get('screenshot') or request.files.get('file')
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400

        mod_dir = BG_PATH / mod_id
        mod_dir.mkdir(parents=True, exist_ok=True)
        f.save(str(mod_dir / 'screenshot.png'))
        mod['screenshot'] = 'screenshot.png'
        _save_bg_mod_json(mod_id, mod)

        # The list reads the catalog entry's screenshot name for the static URL.
        catalog = _load_bg_catalog()
        entry = next((m for m in catalog.get('mods', []) if m.get('id') == mod_id), None)
        if entry is not None:
            entry['screenshot'] = 'screenshot.png'
            _save_bg_catalog(catalog)

        return jsonify({'success': True,
                        'screenshotUrl': f'/storage/menus/css/background/{mod_id}/screenshot.png'})
    except Exception as e:
        logger.error(f'Set bg image error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/background/<mod_id>/export', methods=['GET'])
def export_bg_mod(mod_id):
    """Download a background mod's files as a zip."""
    try:
        mod = _load_bg_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return send_mod_zip(BG_PATH / mod_id, mod.get('name') or mod_id)
    except Exception as e:
        logger.error(f'Export bg mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
