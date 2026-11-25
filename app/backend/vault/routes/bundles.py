"""
Bundles Blueprint - .ssbm mod bundle management, vault side.

Handles listing, importing, previewing, editing, downloading and deleting the
.ssbm mod bundles kept in the vault (storage and index: vault/catalog/bundles.py).
Exporting a build as a bundle, installing one into Slippi and playing one are in
projects/routes/bundles.py, on this same `bundles_bp`.
"""

import os
import re
import json
import zipfile
import tempfile
import logging
from flask import Blueprint, request, jsonify, send_file

from vault.catalog.bundles import BUNDLE_PATH, load_bundle_metadata, save_bundle_metadata
from vault.catalog.bundles import import_bundle_file, read_manifest

logger = logging.getLogger(__name__)

bundles_bp = Blueprint('bundles', __name__)


@bundles_bp.route('/api/mex/bundle/list', methods=['GET'])
def list_bundles():
    """List all bundles in storage"""
    try:
        bundles = load_bundle_metadata()

        # Add image URLs
        for bundle in bundles:
            bundle_id = bundle.get('id')
            if bundle_id:
                image_path = BUNDLE_PATH / f"{bundle_id}.png"
                if image_path.exists():
                    bundle['imageUrl'] = f"/storage/bundles/{bundle_id}.png"
                else:
                    bundle['imageUrl'] = None

        return jsonify({
            'success': True,
            'bundles': bundles
        })
    except Exception as e:
        logger.error(f"List bundles error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/delete/<bundle_id>', methods=['POST'])
def delete_bundle(bundle_id):
    """Delete a bundle"""
    try:
        # Remove from metadata
        bundles = load_bundle_metadata()
        bundles = [b for b in bundles if b['id'] != bundle_id]
        save_bundle_metadata(bundles)

        # Delete files
        bundle_path = BUNDLE_PATH / f"{bundle_id}.ssbm"
        image_path = BUNDLE_PATH / f"{bundle_id}.png"

        if bundle_path.exists():
            os.remove(bundle_path)
        if image_path.exists():
            os.remove(image_path)

        logger.info(f"[OK] Deleted bundle: {bundle_id}")

        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Delete bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/update/<bundle_id>', methods=['POST'])
def update_bundle(bundle_id):
    """Update a bundle's name and description"""
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description', '')

        if not name:
            return jsonify({
                'success': False,
                'error': 'Name is required'
            }), 400

        bundles = load_bundle_metadata()
        bundle = next((b for b in bundles if b['id'] == bundle_id), None)

        if not bundle:
            return jsonify({
                'success': False,
                'error': 'Bundle not found'
            }), 404

        bundle['name'] = name
        bundle['description'] = description
        save_bundle_metadata(bundles)

        logger.info(f"[OK] Updated bundle: {bundle_id}")

        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Update bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/update-image/<bundle_id>', methods=['POST'])
def update_bundle_image(bundle_id):
    """Update a bundle's image"""
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No image file provided'
            }), 400

        image_file = request.files['image']

        # Verify bundle exists
        bundles = load_bundle_metadata()
        bundle = next((b for b in bundles if b['id'] == bundle_id), None)

        if not bundle:
            return jsonify({
                'success': False,
                'error': 'Bundle not found'
            }), 404

        # Save image
        image_path = BUNDLE_PATH / f"{bundle_id}.png"
        image_file.save(str(image_path))

        return jsonify({
            'success': True,
            'imageUrl': f"/storage/bundles/{bundle_id}.png"
        })
    except Exception as e:
        logger.error(f"Update bundle image error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/download/<bundle_id>', methods=['GET'])
def download_bundle(bundle_id):
    """Download a .ssbm bundle file"""
    try:
        # Look up bundle in metadata to get the name for download
        bundles = load_bundle_metadata()
        bundle = next((b for b in bundles if b['id'] == bundle_id), None)

        # Try .ssbm extension
        file_path = BUNDLE_PATH / f"{bundle_id}.ssbm"

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': 'Bundle file not found'
            }), 404

        # Use bundle name for download filename
        if bundle:
            safe_name = re.sub(r'[^\w\-_]', '_', bundle['name'])
            download_name = f"{safe_name}.ssbm"
        else:
            download_name = f"{bundle_id}.ssbm"

        return send_file(
            file_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Download bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/import', methods=['POST'])
def import_bundle():
    """Import a .ssbm bundle to storage (saves file + metadata, does NOT install)"""
    try:
        # Check if file was uploaded
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

        if not file.filename.lower().endswith('.ssbm'):
            return jsonify({
                'success': False,
                'error': 'File must be a .ssbm bundle'
            }), 400

        with tempfile.NamedTemporaryFile(suffix='.ssbm', delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        try:
            result = import_bundle_file(tmp_path, file.filename.replace('.ssbm', ''))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return jsonify({
            'success': True,
            'bundle_id': result['bundle_id'],
            'name': result['name'],
            'message': 'Bundle saved to storage'
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Import bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bundles_bp.route('/api/mex/bundle/preview', methods=['POST'])
def preview_bundle():
    """Preview a .ssbm bundle without importing it"""
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400

        file = request.files['file']

        if not file.filename or not file.filename.lower().endswith('.ssbm'):
            return jsonify({
                'success': False,
                'error': 'File must be a .ssbm bundle'
            }), 400

        # Read manifest from ZIP without extracting
        try:
            with zipfile.ZipFile(file, 'r') as zf:
                if 'manifest.json' not in zf.namelist():
                    return jsonify({
                        'success': False,
                        'error': 'Invalid bundle: manifest.json not found'
                    }), 400

                try:
                    manifest = read_manifest(zf)
                except ValueError as e:
                    return jsonify({'success': False, 'error': f'Invalid bundle: {e}'}), 400

                # Check for patch.xdelta
                has_patch = 'patch.xdelta' in zf.namelist()

                # Count textures
                texture_count = len([n for n in zf.namelist() if n.startswith('textures/') and n.endswith('.png')])

            return jsonify({
                'success': True,
                'manifest': manifest,
                'has_patch': has_patch,
                'texture_count': texture_count
            })
        except zipfile.BadZipFile:
            return jsonify({
                'success': False,
                'error': 'Invalid bundle: not a valid ZIP file'
            }), 400

    except Exception as e:
        logger.error(f"Preview bundle error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# The build half of this blueprint (export a build as a bundle, install a
# bundle into Slippi, play one) lives in projects/routes/bundles.py and adds its
# routes to bundles_bp. Importing it here makes the blueprint complete before
# anything registers it: Flask refuses routes added after registration.
from projects.routes import bundles as _project_routes  # noqa: E402,F401
