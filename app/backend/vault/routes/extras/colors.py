"""
Color extras - character effect color modifications (lasers, side-B, shine, etc.).

The stored color extras library: list, create, delete. Reading, installing and
restoring them in the open project is projects/routes/extras.py; applying every selected
extra at export time is vault/extras/apply.py.
"""

import uuid
import logging
from datetime import datetime
from flask import request, jsonify

from core.metadata import load_metadata, save_metadata
from core.extra_lookup import get_extra_types, get_extra_type, has_extras, get_storage_character
from vault.extras.unit_parts import fold_part_mods_into_units

from . import extras_bp
from vault.extras import helpers, effect_model, sideb_model
from vault.extras.models import remove_model_files

logger = logging.getLogger(__name__)


# =============================================================================
# API ROUTES
# =============================================================================

@extras_bp.route('/api/mex/storage/extras/list/<character>', methods=['GET'])
def list_extras(character):
    """List all extras for a character from metadata.json.

    For shared extras, retrieves mods from the owner character's storage.
    """
    try:
        # Check if character has extras defined
        if not has_extras(character):
            return jsonify({
                'success': True,
                'extras': {},
                'message': f'No extras defined for {character}'
            })

        # Load metadata (via the core.metadata DAL)
        metadata = load_metadata()
        if not metadata:
            return jsonify({
                'success': True,
                'extras': {}
            })

        # Mods saved under a part type on its own (pre-unit vaults) become
        # unit mods carrying just that part -- once, persisted.
        if fold_part_mods_into_units(metadata):
            save_metadata(metadata)

        # Build extras dict, pulling shared extras from owner characters
        extras = {}
        char_extra_types = get_extra_types(character)

        for extra_type in char_extra_types:
            type_id = extra_type['id']
            if extra_type.get('part_of'):
                continue  # parts are edited inside their unit's mods
            # Get the storage character (owner for shared extras)
            storage_char = get_storage_character(character, type_id)

            # Get mods from the appropriate character's storage
            char_data = metadata.get('characters', {}).get(storage_char, {})
            type_mods = char_data.get('extras', {}).get(type_id, [])

            if type_mods:
                extras[type_id] = type_mods

        return jsonify({
            'success': True,
            'extras': extras
        })

    except Exception as e:
        logger.error(f"List extras error for {character}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@extras_bp.route('/api/mex/storage/extras/create', methods=['POST'])
def create_extra():
    """Create a color recipe, or update the recipe identified by modId.

    For shared extras, stores under the owner character.

    Request body:
    {
        "character": "Falco",
        "extraType": "laser",
        "name": "Red Laser",
        "modifications": {
            "wide": { "color": "FC00" },
            "thin": { "color": "FC00" },
            "outline": { "color": "FC00" }
        }
    }
    """
    try:
        data = request.json
        character = data.get('character')
        extra_type = data.get('extraType')
        name = data.get('name', 'New Extra')
        modifications = data.get('modifications', {})
        editing_id = data.get('modId')

        if not character or not extra_type:
            return jsonify({
                'success': False,
                'error': 'Missing character or extraType parameter'
            }), 400

        # Verify this extra type exists for the character
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        # Get the storage character (owner for shared extras)
        storage_char = get_storage_character(character, extra_type)

        # Load metadata (via the core.metadata DAL)
        metadata = load_metadata(default={'characters': {}})

        # Ensure storage character exists in metadata
        if storage_char not in metadata.get('characters', {}):
            metadata['characters'][storage_char] = {'skins': [], 'extras': {}}

        char_data = metadata['characters'][storage_char]

        # Ensure extras structure exists
        if 'extras' not in char_data:
            char_data['extras'] = {}

        if extra_type not in char_data['extras']:
            char_data['extras'][extra_type] = []

        if editing_id:
            existing = next((mod for mod in char_data['extras'][extra_type]
                             if mod.get('id') == editing_id), None)
            if existing is None:
                return jsonify({'success': False,
                                'error': f'Mod {editing_id} not found'}), 404
            if effect_model.is_image_mod(existing):
                return jsonify({'success': False,
                                'error': 'Save color changes as a new color mod; this mod contains an image.'}), 400
            if sideb_model.is_model_mod(existing) and modifications != existing.get('modifications'):
                return jsonify({'success': False,
                                'error': 'This mod contains an afterimage model. Create a separate color mod to change colors.'}), 400
            # Preserve identity, active selections, imported source assets,
            # and creation history. Replace the complete recipe so removing
            # an optional layer in the editor removes its saved override.
            existing['name'] = name
            existing['modifications'] = modifications
            save_metadata(metadata)
            logger.info(f"[OK] Updated extra mod '{name}' ({extra_type}) for {storage_char}")
            return jsonify({'success': True, 'mod': existing})

        # Generate unique ID
        mod_id = f"{extra_type}_{uuid.uuid4().hex[:8]}"

        # Create new mod entry
        new_mod = {
            'id': mod_id,
            'name': name,
            'date_added': datetime.now().isoformat(),
            'source': 'created',
            'modifications': modifications
        }

        # Add to list
        char_data['extras'][extra_type].append(new_mod)

        # Save metadata (atomic, via the DAL)
        save_metadata(metadata)

        logger.info(f"[OK] Created extra mod '{name}' ({extra_type}) for {storage_char}" +
                   (f" (shared from {character})" if storage_char != character else ""))

        return jsonify({
            'success': True,
            'mod': new_mod
        })

    except Exception as e:
        logger.error(f"Create extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@extras_bp.route('/api/mex/storage/extras/delete', methods=['POST'])
def delete_extra():
    """Delete an extra mod.

    For shared extras, deletes from the owner character's storage.

    Request body:
    {
        "character": "Falco",
        "extraType": "laser",
        "modId": "laser_abc12345"
    }
    """
    try:
        data = request.json
        character = data.get('character')
        extra_type = data.get('extraType')
        mod_id = data.get('modId')

        if not character or not extra_type or not mod_id:
            return jsonify({
                'success': False,
                'error': 'Missing character, extraType, or modId parameter'
            }), 400

        # Get the storage character (owner for shared extras)
        storage_char = get_storage_character(character, extra_type)

        # Load metadata (via the core.metadata DAL)
        metadata = load_metadata()
        if metadata is None:
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        # Get storage character extras
        char_data = metadata.get('characters', {}).get(storage_char, {})
        extras = char_data.get('extras', {})
        mods = extras.get(extra_type, [])

        # Find and remove the mod
        original_count = len(mods)
        removed = [m for m in mods if m.get('id') == mod_id]
        mods = [m for m in mods if m.get('id') != mod_id]

        if len(mods) == original_count:
            return jsonify({
                'success': False,
                'error': f'Mod {mod_id} not found'
            }), 404

        # Remove the mod's stored files (imported effect DATs, encoded
        # texture regions, preview screenshots) -- metadata-only deletion
        # used to leave these orphaned under <owner>/models/.
        for mod in removed:
            for key in ('model_file', 'texture_file', 'image_file', 'screenshot'):
                rel = mod.get(key)
                if not rel:
                    continue
                p = helpers.STORAGE_PATH / storage_char / rel
                try:
                    if key == 'model_file' and p.suffix.lower() == '.dae':
                        # an exported model: its folder, or its sidecars
                        remove_model_files(helpers.STORAGE_PATH / storage_char, rel, mod.get('id'))
                    elif p.exists():
                        p.unlink()
                        logger.info(f"Deleted mod file: {p}")
                except OSError as e:
                    logger.warning(f"Could not delete mod file {p}: {e}")

        # Update metadata
        extras[extra_type] = mods

        # Save metadata (atomic, via the DAL)
        save_metadata(metadata)

        logger.info(f"[OK] Deleted extra mod {mod_id} ({extra_type}) from {storage_char}")

        return jsonify({
            'success': True
        })

    except Exception as e:
        logger.error(f"Delete extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


