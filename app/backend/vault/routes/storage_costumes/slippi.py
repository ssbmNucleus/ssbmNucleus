"""
A costume's Slippi safety verdict: run the check again (fixing what it can) or
record the user's override.

Registers on `storage_costumes_bp` (vault/routes/storage_costumes/).
"""

import os
import zipfile
import tempfile
import logging
from datetime import datetime
from flask import jsonify, request
from core.config import STORAGE_PATH
from core.costume_files import find_costume_archive_name
from core.metadata import get_char_data, load_metadata, save_metadata
from core.atomic_archive import rewrite_zip_atomic
from dat_processor import validate_for_slippi
from . import storage_costumes_bp

logger = logging.getLogger(__name__)


@storage_costumes_bp.route('/api/mex/storage/costumes/retest-slippi', methods=['POST'])
def retest_costume_slippi():
    """Retest a character costume for slippi safety and optionally apply fix"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        auto_fix = data.get('autoFix', False)

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"

        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume zip not found: {skin_id}'}), 404

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            dat_filename = find_costume_archive_name(zip_ref.namelist())
            if not dat_filename:
                return jsonify({'success': False, 'error': 'No costume archive found in costume ZIP'}), 400

            dat_data = zip_ref.read(dat_filename)

        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as tmp_dat:
            tmp_dat.write(dat_data)
            tmp_dat_path = tmp_dat.name

        try:
            validation = validate_for_slippi(tmp_dat_path, auto_fix=auto_fix)

            # The validator couldn't reach a verdict. Reporting that as "not
            # Slippi safe" is what made this a dead end: the costume looked
            # unsafe, the offered Fix had nothing to fix, and clicking it just
            # said "Not Slippi Safe" again. Say what actually went wrong, and
            # leave the stored status alone rather than recording a guess.
            if validation.get('error'):
                logger.error(f"Slippi validation error for {character}/{skin_id}: {validation['error']}")
                return jsonify({
                    'success': False,
                    'error': f"Couldn't check this costume: {validation['error']}"
                }), 500

            if auto_fix and validation.get('fix_applied'):
                with open(tmp_dat_path, 'rb') as f:
                    fixed_dat_data = f.read()

                def replace_dat(source_zip, dest_zip):
                    for item in source_zip.infolist():
                        if item.filename == dat_filename:
                            dest_zip.writestr(item.filename, fixed_dat_data)
                        else:
                            dest_zip.writestr(item, source_zip.read(item.filename))
                rewrite_zip_atomic(zip_path, replace_dat)

        finally:
            try:
                os.unlink(tmp_dat_path)
            except:
                pass

        metadata = load_metadata()
        if metadata is not None:
            char_data = get_char_data(metadata, character)
            if char_data is not None:
                for skin in char_data.get('skins', []):
                    if skin['id'] == skin_id:
                        skin['slippi_safe'] = validation['slippi_safe']
                        skin['slippi_tested'] = True
                        skin['slippi_test_date'] = datetime.now().isoformat()
                        skin['slippi_manual_override'] = None
                        break

                save_metadata(metadata)

        logger.info(f"[OK] Retested slippi for {character} - {skin_id}: {validation['slippi_safe']}")
        return jsonify({
            'success': True,
            'slippi_safe': validation['slippi_safe'],
            'message': 'Slippi Safe' if validation['slippi_safe'] else 'Not Slippi Safe'
        })
    except Exception as e:
        logger.error(f"Retest slippi error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/override-slippi', methods=['POST'])
def override_costume_slippi():
    """Manually override slippi safety status for a character costume"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        slippi_safe = data.get('slippiSafe')

        if not character or not skin_id or slippi_safe is None:
            return jsonify({'success': False, 'error': 'Missing character, skinId, or slippiSafe parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        char_data = get_char_data(metadata, character)
        if char_data is None:
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        skin_found = False
        for skin in char_data.get('skins', []):
            if skin['id'] == skin_id:
                skin['slippi_safe'] = slippi_safe
                skin['slippi_manual_override'] = True
                skin['slippi_test_date'] = datetime.now().isoformat()
                skin_found = True
                break

        if not skin_found:
            return jsonify({'success': False, 'error': f'Skin {skin_id} not found for {character}'}), 404

        save_metadata(metadata)

        logger.info(f"[OK] Manually set slippi status for {character} - {skin_id}: {slippi_safe}")
        return jsonify({
            'success': True,
            'slippi_safe': slippi_safe,
            'message': f"Manually set to {'Slippi Safe' if slippi_safe else 'Not Slippi Safe'}"
        })
    except Exception as e:
        logger.error(f"Override slippi error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
