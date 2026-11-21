"""
SSS (Stage Select Screen) layout editor endpoints.

Layout reads/writes go through the loaded MEX project's manager; stage icons
are served straight from the project assets directory.
"""

import logging
from pathlib import Path
from flask import request, jsonify, send_file

from core.state import get_current_project_path, get_mex_manager

from vault.routes.menus import menus_bp

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/sss/layout', methods=['GET'])
def get_sss_layout():
    """Get the full SSS layout from the current MEX project."""
    try:
        mex = get_mex_manager()
        if mex is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        result = mex.get_sss_layout()
        return jsonify(result)
    except Exception as e:
        logger.error(f'Get SSS layout error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/sss/layout', methods=['POST'])
def set_sss_layout():
    """Save SSS layout changes to the MEX project."""
    try:
        mex = get_mex_manager()
        if mex is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        layout_data = request.get_json()
        if not layout_data or 'pages' not in layout_data:
            return jsonify({'success': False, 'error': 'Missing pages data'}), 400

        import json as _json
        result = mex.set_sss_layout(_json.dumps(layout_data))
        return jsonify(result)
    except Exception as e:
        logger.error(f'Set SSS layout error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/sss/stage-icon', methods=['GET'])
def get_sss_stage_icon():
    """Serve a stage icon PNG from the MEX project assets directory."""
    try:
        icon_path = request.args.get('path')
        if not icon_path:
            return jsonify({'success': False, 'error': 'Missing path parameter'}), 400

        icon_file = Path(icon_path)

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        project_dir = project_path.parent.resolve()
        try:
            icon_file.resolve().relative_to(project_dir)
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid path'}), 403

        if not icon_file.exists():
            return jsonify({'success': False, 'error': 'Icon file not found'}), 404

        return send_file(str(icon_file), mimetype='image/png',
                         max_age=0)
    except Exception as e:
        logger.error(f'Get SSS stage icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/sss/backdrop', methods=['GET'])
def get_sss_backdrop():
    """The SSS layout editor's backdrop: the stage select screen
    rendered from the user's own game (shared/vanilla_extract/menu_backdrops.py).
    404 when it cannot be made; the editor then draws a plain background."""
    from shared.vanilla_extract.menu_backdrops import backdrop_path
    path = backdrop_path('sss')
    if path is None:
        return jsonify({'success': False, 'error': 'No backdrop for this screen'}), 404
    return send_file(str(path), mimetype='image/png', max_age=0)
