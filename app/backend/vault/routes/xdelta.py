"""
XDelta Blueprint - XDelta patch management, vault side.

Handles importing, editing, deleting and downloading the XDelta patches kept in
the vault. Building an ISO from a patch, playing it and creating a new patch
from a modded ISO are in projects/routes/xdelta.py, on this same `xdelta_bp`.
"""

import os
import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file

from projects.install.xdelta import (
    XDELTA_PATH, load_xdelta_metadata,
    save_xdelta_metadata,
)

logger = logging.getLogger(__name__)

xdelta_bp = Blueprint('xdelta', __name__)


@xdelta_bp.route('/api/mex/xdelta/list', methods=['GET'])
def list_xdelta_patches():
    """List all xdelta patches in storage"""
    try:
        patches = load_xdelta_metadata()

        # Add image URLs
        for patch in patches:
            patch_id = patch.get('id')
            if patch_id:
                image_path = XDELTA_PATH / f"{patch_id}.png"
                if image_path.exists():
                    patch['imageUrl'] = f"/storage/xdelta/{patch_id}.png"
                else:
                    patch['imageUrl'] = None

        return jsonify({
            'success': True,
            'patches': patches
        })
    except Exception as e:
        logger.error(f"List xdelta patches error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/import', methods=['POST'])
def import_xdelta_patch():
    """Import a new xdelta patch"""
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No xdelta file uploaded'
            }), 400

        file = request.files['file']
        name = request.form.get('name', 'Unnamed Patch')
        description = request.form.get('description', '')

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Validate file extension
        if not file.filename.lower().endswith('.xdelta'):
            return jsonify({
                'success': False,
                'error': 'File must be an .xdelta file'
            }), 400

        # Generate unique ID
        patch_id = str(uuid.uuid4())[:8]

        # Save xdelta file
        xdelta_filename = f"{patch_id}.xdelta"
        xdelta_path = XDELTA_PATH / xdelta_filename
        file.save(str(xdelta_path))

        # Save image if provided
        if 'image' in request.files:
            image_file = request.files['image']
            if image_file.filename:
                image_path = XDELTA_PATH / f"{patch_id}.png"
                image_file.save(str(image_path))

        # Add to metadata
        patches = load_xdelta_metadata()
        patches.append({
            'id': patch_id,
            'name': name,
            'description': description,
            'filename': file.filename,
            'created': datetime.now().isoformat()
        })
        save_xdelta_metadata(patches)

        logger.info(f"[OK] Imported xdelta patch: {name} ({patch_id})")

        return jsonify({
            'success': True,
            'patch': {
                'id': patch_id,
                'name': name,
                'description': description
            }
        })
    except Exception as e:
        logger.error(f"Import xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/update/<patch_id>', methods=['POST'])
def update_xdelta_patch(patch_id):
    """Update an xdelta patch's metadata"""
    try:
        data = request.json or {}
        name = data.get('name')
        description = data.get('description')

        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        if name is not None:
            patch['name'] = name
        if description is not None:
            patch['description'] = description

        save_xdelta_metadata(patches)

        return jsonify({
            'success': True,
            'patch': patch
        })
    except Exception as e:
        logger.error(f"Update xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/update-image/<patch_id>', methods=['POST'])
def update_xdelta_image(patch_id):
    """Update an xdelta patch's image"""
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No image file uploaded'
            }), 400

        image_file = request.files['image']
        if image_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        # Verify patch exists
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        # Save image
        image_path = XDELTA_PATH / f"{patch_id}.png"
        image_file.save(str(image_path))

        return jsonify({
            'success': True,
            'imageUrl': f"/storage/xdelta/{patch_id}.png"
        })
    except Exception as e:
        logger.error(f"Update xdelta image error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/delete/<patch_id>', methods=['POST'])
def delete_xdelta_patch(patch_id):
    """Delete an xdelta patch"""
    try:
        # Remove from metadata
        patches = load_xdelta_metadata()
        patches = [p for p in patches if p['id'] != patch_id]
        save_xdelta_metadata(patches)

        # Delete files
        xdelta_path = XDELTA_PATH / f"{patch_id}.xdelta"
        image_path = XDELTA_PATH / f"{patch_id}.png"

        if xdelta_path.exists():
            os.remove(xdelta_path)
        if image_path.exists():
            os.remove(image_path)

        logger.info(f"[OK] Deleted xdelta patch: {patch_id}")

        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Delete xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/download-patch/<patch_id>', methods=['GET'])
def download_xdelta_patch(patch_id):
    """Download an xdelta patch file"""
    try:
        # Get patch info
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        file_path = XDELTA_PATH / f"{patch_id}.xdelta"

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': 'Patch file not found'
            }), 404

        # Use the original name for the download
        download_name = f"{patch['name']}.xdelta"

        return send_file(
            file_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Download xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# The build half of this blueprint (build an ISO from a patch, play it, download
# the built ISO, create a patch from a modded ISO) lives in
# projects/routes/xdelta.py and adds its routes to xdelta_bp. Importing it here
# makes the blueprint complete before anything registers it: Flask refuses
# routes added after registration.
from projects.routes import xdelta as _project_routes  # noqa: E402,F401
