"""
Model extras - for 3D model replacements (gun, etc.).

The /api/mex/storage/models/* routes; the model extract/import through the
HSDRawViewer CLI is vault/extras/models.py. Putting the vanilla model back is
the shared /api/mex/storage/extras/restore-vanilla (projects/routes/extras.py).
"""

import uuid
import logging
import shutil
from datetime import datetime
from pathlib import Path
from flask import request, jsonify
from werkzeug.utils import secure_filename

import file_retry
from core.extra_lookup import get_extra_type, get_storage_character
from core.metadata import load_metadata, save_metadata

from . import extras_bp
from vault.extras import helpers
from vault.extras.helpers import find_dat_file
from vault.extras.models import (ModelNotInDat, extract_model_from_dat, import_model_to_dat,
                                 model_extra_location, remove_model_files)

logger = logging.getLogger(__name__)


@extras_bp.route('/api/mex/storage/models/create', methods=['POST'])
def create_model_extra():
    """Create a new model extra from an uploaded .dae or .dat file.

    For .dat files, extracts the model as .dae first.
    Stores the .dae, and the textures its export writes beside it, in a folder
    of its own: storage/[Character]/models/[mod_id]/[mod_id].dae

    Request: multipart/form-data with:
        - character: Character name (e.g., "Falco")
        - extraType: Extra type ID (e.g., "gun")
        - name: Display name for the mod
        - file: The .dae or .dat file
    """
    try:
        character = request.form.get('character')
        extra_type = request.form.get('extraType')
        name = request.form.get('name', 'Custom Model')

        if not character or not extra_type:
            return jsonify({
                'success': False,
                'error': 'Missing character or extraType parameter'
            }), 400

        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Verify this extra type exists and is a model type
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        if type_config.get('type') != 'model':
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" is not a model type'
            }), 400

        # Get storage character
        storage_char = get_storage_character(character, extra_type)

        filename = secure_filename(file.filename)
        file_ext = Path(filename).suffix.lower()
        if file_ext not in ('.dae', '.dat'):
            return jsonify({
                'success': False,
                'error': f'Unsupported file type: {file_ext}. Use .dae or .dat'
            }), 400
        jobj_path = type_config.get('model_path')
        if file_ext == '.dat' and not jobj_path:
            return jsonify({
                'success': False,
                'error': 'Model path not configured for this extra type'
            }), 400

        # The model gets a folder of its own: the export writes its textures
        # beside the .dae under fixed names. A failed upload leaves nothing.
        mod_id = f"{extra_type}_{uuid.uuid4().hex[:8]}"
        models_dir, model_file = model_extra_location(helpers.STORAGE_PATH / storage_char, mod_id)
        models_dir.mkdir(parents=True, exist_ok=True)
        dae_path = models_dir / f"{mod_id}.dae"
        try:
            if file_ext == '.dae':
                file.save(str(dae_path))
                logger.info(f"Saved .dae model to {dae_path}")
            else:
                # .dat upload: extract the model at the type's joint path
                temp_dat = models_dir / f"{mod_id}_temp.dat"
                file.save(str(temp_dat))
                try:
                    extract_model_from_dat(temp_dat, jobj_path, dae_path)
                finally:
                    temp_dat.unlink(missing_ok=True)
                logger.info(f"Extracted model from .dat to {dae_path}")
        except ModelNotInDat:
            shutil.rmtree(models_dir, ignore_errors=True)
            # A costume or other file with no such model: say which file the
            # editor needs instead of HSDRawViewer's path.
            return jsonify({
                'success': False,
                'error': (f"{filename} has no {type_config.get('name', 'model')} in it. "
                          f"Upload the {type_config['target_file']} that has the custom "
                          "model inside; a costume .dat does not carry one.")
            }), 400
        except Exception:
            shutil.rmtree(models_dir, ignore_errors=True)
            raise

        # Load metadata (via the core.metadata DAL)
        metadata = load_metadata(default={'characters': {}})

        # Ensure character structure exists
        if storage_char not in metadata.get('characters', {}):
            metadata['characters'][storage_char] = {'skins': [], 'extras': {}}

        char_data = metadata['characters'][storage_char]
        if 'extras' not in char_data:
            char_data['extras'] = {}
        if extra_type not in char_data['extras']:
            char_data['extras'][extra_type] = []

        # Create mod entry
        new_mod = {
            'id': mod_id,
            'name': name,
            'type': 'model',
            'date_added': datetime.now().isoformat(),
            'source': 'uploaded',
            'model_file': model_file
        }

        char_data['extras'][extra_type].append(new_mod)

        # Save metadata (atomic, via the DAL)
        save_metadata(metadata)

        logger.info(f"[OK] Created model extra '{name}' ({extra_type}) for {storage_char}")

        return jsonify({
            'success': True,
            'mod': new_mod
        })

    except Exception as e:
        logger.error(f"Create model extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@extras_bp.route('/api/mex/storage/models/install', methods=['POST'])
def install_model_extra():
    """Install a model extra by importing the .dae into the target .dat file.

    Request body:
    {
        "character": "Falco",
        "extraType": "gun",
        "modId": "gun_abc123"
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

        # Get extra type config
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        if type_config.get('type') != 'model':
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" is not a model type'
            }), 400

        # Get storage character
        storage_char = get_storage_character(character, extra_type)

        # Find the .dat file in MEX project
        try:
            files_dir = helpers.get_project_files_dir()
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        target_file = type_config['target_file']
        jobj_path = type_config.get('model_path')

        if not jobj_path:
            return jsonify({
                'success': False,
                'error': 'Model path not configured for this extra type'
            }), 400

        dat_path = find_dat_file(files_dir, target_file)
        if not dat_path or not dat_path.exists():
            return jsonify({
                'success': False,
                'error': f'Could not find {target_file} in MEX project'
            }), 404

        # Load metadata to find the mod (via the core.metadata DAL)
        metadata = load_metadata()
        if metadata is None:
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        # Find the mod
        char_data = metadata.get('characters', {}).get(storage_char, {})
        extras = char_data.get('extras', {})
        mods = extras.get(extra_type, [])

        found_mod = None
        for mod in mods:
            if mod.get('id') == mod_id:
                found_mod = mod
                break

        if not found_mod:
            return jsonify({
                'success': False,
                'error': f'Mod {mod_id} not found'
            }), 404

        # Get the .dae file path
        model_file = found_mod.get('model_file')
        if not model_file:
            return jsonify({
                'success': False,
                'error': 'Model file not found in mod metadata'
            }), 400

        dae_path = helpers.STORAGE_PATH / storage_char / model_file
        if not dae_path.exists():
            return jsonify({
                'success': False,
                'error': f'Model file not found: {dae_path}'
            }), 404

        # Import the model into the .dat file (in place)
        # We'll write to a temp file then replace the original
        temp_output = dat_path.parent / f"{dat_path.stem}_temp{dat_path.suffix}"

        try:
            import_model_to_dat(dat_path, jobj_path, dae_path, temp_output)

            # Replace original with modified
            file_retry.replace(str(temp_output), str(dat_path))
            logger.info(f"[OK] Installed model '{found_mod['name']}' to {target_file}")

        except Exception as e:
            # Clean up temp file on failure
            if temp_output.exists():
                temp_output.unlink()
            raise

        return jsonify({
            'success': True
        })

    except Exception as e:
        logger.error(f"Install model extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@extras_bp.route('/api/mex/storage/models/delete', methods=['POST'])
def delete_model_extra():
    """Delete a model extra and its .dae file.

    Request body:
    {
        "character": "Falco",
        "extraType": "gun",
        "modId": "gun_abc123"
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

        # Get storage character
        storage_char = get_storage_character(character, extra_type)

        # Load metadata (via the core.metadata DAL)
        metadata = load_metadata()
        if metadata is None:
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        # Find the mod
        char_data = metadata.get('characters', {}).get(storage_char, {})
        extras = char_data.get('extras', {})
        mods = extras.get(extra_type, [])

        # Find and remove the mod
        found_mod = None
        new_mods = []
        for mod in mods:
            if mod.get('id') == mod_id:
                found_mod = mod
            else:
                new_mods.append(mod)

        if not found_mod:
            return jsonify({
                'success': False,
                'error': f'Mod {mod_id} not found'
            }), 404

        # Delete the model and what its export wrote with it
        model_file = found_mod.get('model_file')
        if model_file:
            remove_model_files(helpers.STORAGE_PATH / storage_char, model_file, mod_id)

        # Update metadata
        extras[extra_type] = new_mods

        # Save metadata (atomic, via the DAL)
        save_metadata(metadata)

        logger.info(f"[OK] Deleted model extra {mod_id} from {storage_char}")

        return jsonify({
            'success': True
        })

    except Exception as e:
        logger.error(f"Delete model extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
