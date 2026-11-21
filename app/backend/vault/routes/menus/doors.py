"""
CSS Doors endpoints.

A door mod is a single `door.png` texture installed into MnSlChr.usd via
HSDRawViewer --css-doors import:

    storage/menus/css/doors/
        metadata.json               # list of installed door mods
        <mod_id>/
            door.png
"""

import shutil
import logging
from pathlib import Path
from flask import request, jsonify, send_file


from . import menus_bp
from vault.menus.store import DOORS_PATH
from vault.menus.files import send_mod_zip
from vault.menus.doors import _load_doors_metadata, _save_doors_metadata, import_door_image

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/css/doors/list', methods=['GET'])
def list_door_mods():
    try:
        mods = _load_doors_metadata()
        for mod in mods:
            mod_dir = DOORS_PATH / mod['id']
            img = mod_dir / 'door.png'
            if img.exists():
                mod['imageUrl'] = f'/api/mex/menus/css/doors/image/{mod["id"]}'
        return jsonify({'success': True, 'mods': mods})
    except Exception as e:
        logger.error(f'List door mods error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/doors/image/<mod_id>', methods=['GET'])
def get_door_image(mod_id):
    try:
        img = DOORS_PATH / mod_id / 'door.png'
        if not img.exists():
            return jsonify({'success': False, 'error': 'Not found'}), 404
        return send_file(str(img), mimetype='image/png', max_age=0)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/doors/import', methods=['POST'])
def import_door_mod():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({'success': False, 'error': 'Empty filename'}), 400
        name = request.form.get('name', Path(f.filename).stem)
        mod = import_door_image(f.read(), name)
        return jsonify({'success': True, 'mod': mod})
    except Exception as e:
        logger.error(f'Import door mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/doors/delete/<mod_id>', methods=['POST'])
def delete_door_mod(mod_id):
    try:
        mods = _load_doors_metadata()
        mods = [m for m in mods if m['id'] != mod_id]
        _save_doors_metadata(mods)
        mod_dir = DOORS_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(str(mod_dir))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Delete door mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/doors/rename/<mod_id>', methods=['POST'])
def rename_door_mod(mod_id):
    """Rename a door mod. Body: {name}."""
    try:
        mods = _load_doors_metadata()
        mod = next((m for m in mods if m['id'] == mod_id), None)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        payload = request.get_json(silent=True) or {}
        name = (payload.get('name') or '').strip()
        if name:
            mod['name'] = name
        _save_doors_metadata(mods)
        mod['imageUrl'] = f'/api/mex/menus/css/doors/image/{mod_id}'
        return jsonify({'success': True, 'mod': mod})
    except Exception as e:
        logger.error(f'Rename door mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/doors/<mod_id>/screenshot', methods=['POST'])
def set_door_image(mod_id):
    """Replace a door mod's texture (door.png) with an uploaded image. For doors
    the preview IS the texture, so editing the image edits the door itself."""
    try:
        mods = _load_doors_metadata()
        mod = next((m for m in mods if m['id'] == mod_id), None)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        f = request.files.get('screenshot') or request.files.get('file')
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400
        mod_dir = DOORS_PATH / mod_id
        mod_dir.mkdir(parents=True, exist_ok=True)
        f.save(str(mod_dir / 'door.png'))
        return jsonify({'success': True, 'imageUrl': f'/api/mex/menus/css/doors/image/{mod_id}'})
    except Exception as e:
        logger.error(f'Set door image error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/doors/<mod_id>/export', methods=['GET'])
def export_door_mod(mod_id):
    """Download a door mod's files as a zip."""
    try:
        mods = _load_doors_metadata()
        mod = next((m for m in mods if m['id'] == mod_id), None)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return send_mod_zip(DOORS_PATH / mod_id, mod.get('name') or mod_id)
    except Exception as e:
        logger.error(f'Export door mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
