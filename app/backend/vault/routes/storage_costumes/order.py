"""
Ordering a character's costumes and grouping them in folders: reorder, move to
the top or bottom, and create, rename, delete, collapse or assign folders.

Registers on `storage_costumes_bp` (vault/routes/storage_costumes/).
"""

import uuid
import logging
from flask import jsonify, request
from core.config import STORAGE_PATH
from core.metadata import load_metadata, metadata_write_transaction, save_metadata
from . import storage_costumes_bp
from vault.catalog.costume_folders import find_folder_in_skins, get_folder_id_at_position

logger = logging.getLogger(__name__)


@storage_costumes_bp.route('/api/mex/storage/costumes/reorder', methods=['POST'])
@metadata_write_transaction
def reorder_costumes():
    """Reorder character skins in storage."""
    try:
        data = request.json
        character = data.get('character')
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        if character is None or from_index is None or to_index is None:
            return jsonify({'success': False, 'error': 'Missing character, fromIndex, or toIndex parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        if from_index < 0 or from_index >= len(skins) or to_index < 0 or to_index >= len(skins):
            return jsonify({'success': False, 'error': 'Invalid fromIndex or toIndex'}), 400

        item = skins.pop(from_index)
        skins.insert(to_index, item)

        if item.get('type') != 'folder':
            new_folder_id = get_folder_id_at_position(skins, to_index)
            if new_folder_id:
                item['folder_id'] = new_folder_id
            elif 'folder_id' in item:
                del item['folder_id']

        save_metadata(metadata)

        logger.info(f"[OK] Reordered {character} skins: moved index {from_index} to {to_index}")
        return jsonify({'success': True, 'skins': skins})
    except Exception as e:
        logger.error(f"Reorder costumes error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/move-to-top', methods=['POST'])
@metadata_write_transaction
def move_costume_to_top():
    """Move a character skin to the top of the list"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        skin_index = None
        for i, skin in enumerate(skins):
            if skin['id'] == skin_id:
                skin_index = i
                break

        if skin_index is None:
            return jsonify({'success': False, 'error': f'Skin {skin_id} not found'}), 404

        if skin_index > 0:
            skin = skins.pop(skin_index)
            skins.insert(0, skin)
            save_metadata(metadata)
            logger.info(f"[OK] Moved {character} skin {skin_id} to top")

        return jsonify({'success': True, 'skins': skins})
    except Exception as e:
        logger.error(f"Move costume to top error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/move-to-bottom', methods=['POST'])
@metadata_write_transaction
def move_costume_to_bottom():
    """Move a character skin to the bottom of the list"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        skin_index = None
        for i, skin in enumerate(skins):
            if skin['id'] == skin_id:
                skin_index = i
                break

        if skin_index is None:
            return jsonify({'success': False, 'error': f'Skin {skin_id} not found'}), 404

        if skin_index < len(skins) - 1:
            skin = skins.pop(skin_index)
            skins.append(skin)
            save_metadata(metadata)
            logger.info(f"[OK] Moved {character} skin {skin_id} to bottom")

        return jsonify({'success': True, 'skins': skins})
    except Exception as e:
        logger.error(f"Move costume to bottom error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============= Folder Management Endpoints =============

@storage_costumes_bp.route('/api/mex/storage/folders/create', methods=['POST'])
@metadata_write_transaction
def create_folder():
    """Create a new folder for organizing skins."""
    try:
        data = request.json
        character = data.get('character')
        name = data.get('name', 'New Folder')

        if not character:
            return jsonify({'success': False, 'error': 'Missing character parameter'}), 400

        STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        metadata = load_metadata(default={'characters': {}})

        characters = metadata.setdefault('characters', {})
        character_data = characters.setdefault(character, {})
        skins = character_data.setdefault('skins', [])

        folder_id = f"folder_{uuid.uuid4().hex[:8]}"
        new_folder = {'type': 'folder', 'id': folder_id, 'name': name, 'expanded': True}

        skins.append(new_folder)

        save_metadata(metadata)

        logger.info(f"[OK] Created folder '{name}' for {character}")
        return jsonify({'success': True, 'folder': new_folder, 'skins': skins})
    except Exception as e:
        logger.error(f"Create folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/folders/rename', methods=['POST'])
@metadata_write_transaction
def rename_folder():
    """Rename a folder"""
    try:
        data = request.json
        character = data.get('character')
        folder_id = data.get('folderId')
        new_name = data.get('newName')

        if not character or not folder_id or not new_name:
            return jsonify({'success': False, 'error': 'Missing character, folderId, or newName parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        folder, idx = find_folder_in_skins(skins, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        folder['name'] = new_name

        save_metadata(metadata)

        logger.info(f"[OK] Renamed folder {folder_id} to '{new_name}'")
        return jsonify({'success': True, 'skins': skins})
    except Exception as e:
        logger.error(f"Rename folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/folders/delete', methods=['POST'])
@metadata_write_transaction
def delete_folder():
    """Delete a folder. Does NOT delete the skins themselves."""
    try:
        data = request.json
        character = data.get('character')
        folder_id = data.get('folderId')

        if not character or not folder_id:
            return jsonify({'success': False, 'error': 'Missing character or folderId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        folder, folder_idx = find_folder_in_skins(skins, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        for skin in skins:
            if skin.get('folder_id') == folder_id:
                del skin['folder_id']

        skins.pop(folder_idx)

        save_metadata(metadata)

        logger.info(f"[OK] Deleted folder {folder_id}")
        return jsonify({'success': True, 'skins': skins})
    except Exception as e:
        logger.error(f"Delete folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/folders/toggle', methods=['POST'])
@metadata_write_transaction
def toggle_folder():
    """Toggle folder expanded state"""
    try:
        data = request.json
        character = data.get('character')
        folder_id = data.get('folderId')

        if not character or not folder_id:
            return jsonify({'success': False, 'error': 'Missing character or folderId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        folder, idx = find_folder_in_skins(skins, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        folder['expanded'] = not folder.get('expanded', True)

        save_metadata(metadata)

        logger.info(f"[OK] Toggled folder {folder_id} expanded: {folder['expanded']}")
        return jsonify({'success': True, 'expanded': folder['expanded'], 'skins': skins})
    except Exception as e:
        logger.error(f"Toggle folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/skins/set-folder', methods=['POST'])
@metadata_write_transaction
def set_skin_folder():
    """Assign or unassign a skin to a folder"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        folder_id = data.get('folderId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if character not in metadata.get('characters', {}):
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        character_data = metadata['characters'][character]
        skins = character_data.get('skins', [])

        skin = None
        for s in skins:
            if s.get('id') == skin_id and s.get('type') != 'folder':
                skin = s
                break

        if not skin:
            return jsonify({'success': False, 'error': f'Skin {skin_id} not found'}), 404

        if folder_id:
            folder, _ = find_folder_in_skins(skins, folder_id)
            if not folder:
                return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        if folder_id:
            skin['folder_id'] = folder_id
        elif 'folder_id' in skin:
            del skin['folder_id']

        save_metadata(metadata)

        logger.info(f"[OK] Set skin {skin_id} folder to {folder_id}")
        return jsonify({'success': True, 'skins': skins})
    except Exception as e:
        logger.error(f"Set skin folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
