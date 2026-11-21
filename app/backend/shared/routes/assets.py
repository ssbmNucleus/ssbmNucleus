"""
Assets Blueprint - Static file serving routes.

Handles serving static files from storage, vanilla assets, utility assets,
and project assets.
"""

import os
import logging
from flask import Blueprint, jsonify, send_file

from core.config import STORAGE_PATH, VANILLA_ASSETS_DIR, BASE_PATH, PROJECT_ROOT
from core.state import get_current_project_path
from core.path_safety import resolve_under_root

logger = logging.getLogger(__name__)

assets_bp = Blueprint('assets', __name__)


@assets_bp.route('/api/mex/assets/<path:asset_path>', methods=['GET'])
def serve_mex_asset(asset_path):
    """Serve MEX asset files (CSP, stock icons, etc.)"""
    try:
        # Get the currently loaded project's directory
        current_project_path = get_current_project_path()
        if current_project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded'}), 400

        project_dir = current_project_path.parent

        # Asset path already includes the extension from the URL
        full_path = resolve_under_root(project_dir, asset_path, field='asset path')

        if not full_path.exists():
            return jsonify({'success': False, 'error': f'Asset not found: {asset_path}'}), 404

        return send_file(full_path, mimetype='image/png')
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@assets_bp.route('/storage/<path:file_path>', methods=['GET'])
def serve_storage(file_path):
    """Serve files from storage folder (costumes, stages, screenshots, etc.)"""
    try:
        logger.info(f"========== STORAGE REQUEST ==========")
        logger.info(f"Requested file_path: {file_path}")
        logger.info(f"STORAGE_PATH: {STORAGE_PATH}")

        full_path = resolve_under_root(STORAGE_PATH, file_path, field='storage path')

        logger.info(f"Full path: {full_path}")
        logger.info(f"File exists: {full_path.exists()}")

        if not full_path.exists():
            # Log what's in the parent directory
            parent_dir = full_path.parent
            logger.warning(f"Storage file NOT FOUND: {full_path}")
            logger.warning(f"Parent directory: {parent_dir}")
            if parent_dir.exists():
                files = list(parent_dir.glob('*'))[:10]
                logger.warning(f"Files in parent dir: {[f.name for f in files]}")
            else:
                logger.warning(f"Parent directory does not exist!")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype based on extension
        ext = os.path.splitext(file_path.lower())[1]
        mimetype_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.zip': 'application/zip'
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')

        logger.info(f"[OK] Serving storage file: {full_path}")
        return send_file(full_path, mimetype=mimetype)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error(f"EXCEPTION serving storage file {file_path}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@assets_bp.route('/vanilla/<path:file_path>', methods=['GET'])
def serve_vanilla(file_path):
    """Serve vanilla Melee assets (CSPs, stage images, etc.)"""
    try:
        # Stage icons are EXTRACTED from the user's ISO at first-run setup into
        # PROJECT_ROOT/utility/assets/stages (user-data) — see
        # first_run_setup._copy_stage_images. That is the only source: no
        # platform bundles utility/assets/stages any more, so the BASE_PATH
        # branch below is a dead guard, not a real fallback.
        if file_path.startswith('stages/'):
            project_assets = PROJECT_ROOT / "utility" / "assets"
            full_path = resolve_under_root(project_assets, file_path, field='vanilla asset path')
            if not full_path.exists():
                bundled_assets = BASE_PATH / "utility" / "assets"
                full_path = resolve_under_root(bundled_assets, file_path, field='vanilla asset path')
        else:
            # Character assets are in utility/assets/vanilla/
            full_path = resolve_under_root(VANILLA_ASSETS_DIR, file_path, field='vanilla asset path')

        if not full_path.exists():
            logger.warning(f"Vanilla asset not found: {file_path}")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype
        ext = file_path.lower().split('.')[-1]
        mimetype_map = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'gif': 'image/gif',
            'wav': 'audio/wav'
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')

        return send_file(full_path, mimetype=mimetype)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error serving vanilla asset {file_path}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@assets_bp.route('/utility/<path:file_path>', methods=['GET'])
def serve_utility_assets(file_path):
    """Serve utility assets (button icons, etc.)"""
    try:
        # Serve files from utility/assets/
        full_path = resolve_under_root(
            BASE_PATH / "utility" / "assets", file_path, field='utility asset path')

        if not full_path.exists():
            logger.warning(f"Utility asset not found: {file_path}")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype
        ext = file_path.lower().split('.')[-1]
        mimetype_map = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'gif': 'image/gif',
            'svg': 'image/svg+xml'
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')

        return send_file(full_path, mimetype=mimetype)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error serving utility asset: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@assets_bp.route('/assets/<path:file_path>', methods=['GET'])
def serve_mex_assets(file_path):
    """Serve MEX project assets (CSPs, stock icons from currently opened project)"""
    try:
        logger.info(f"========== ASSET REQUEST ==========")
        logger.info(f"Requested file_path: {file_path}")

        # Check if a project is loaded
        current_project_path = get_current_project_path()
        logger.info(f"current_project_path: {current_project_path}")

        if current_project_path is None:
            logger.error("ERROR: No MEX project loaded!")
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        # Use the currently opened project's directory
        # Flask route strips "/assets/" so we need to add it back
        # Route receives: "csp/csp_038.png", we need: "assets/csp/csp_038.png"
        project_dir = current_project_path.parent
        full_path = resolve_under_root(
            project_dir / "assets", file_path, field='project asset path')

        logger.info(f"project_dir: {project_dir}")
        logger.info(f"full_path: {full_path}")
        logger.info(f"File exists: {full_path.exists()}")

        if not full_path.exists():
            # Log what files ARE in the parent directory
            parent_dir = full_path.parent
            logger.warning(f"File NOT FOUND: {full_path}")
            logger.warning(f"Parent directory: {parent_dir}")
            if parent_dir.exists():
                files = list(parent_dir.glob('*'))[:10]  # First 10 files
                logger.warning(f"Files in parent dir: {[f.name for f in files]}")
            else:
                logger.warning(f"Parent directory does not exist!")
            return jsonify({'success': False, 'error': f'File not found: {file_path}'}), 404

        # Determine mimetype based on extension
        ext = file_path.lower().split('.')[-1]
        if ext in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
            mimetype = f'image/{ext if ext != "jpg" else "jpeg"}'
        else:
            mimetype = 'application/octet-stream'

        logger.info(f"[OK] Serving file: {full_path}")
        return send_file(full_path, mimetype=mimetype)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error(f"EXCEPTION serving MEX asset {file_path}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
