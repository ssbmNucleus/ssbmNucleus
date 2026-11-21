"""
CSS (Character Select Screen) layout editor endpoints.

Layout reads/writes go through the loaded MEX project's manager; fighter icons
are served straight from the project assets directory.
"""

import logging
from pathlib import Path
from flask import request, jsonify, send_file

from core import build_access
from core.state import get_current_project_path, get_mex_manager

from vault.routes.menus import menus_bp

logger = logging.getLogger(__name__)


def _lload_info(fighters, icons):
    """The project's L-load groups for the editor: names, plus the external ids
    of bases and of alternates (whose icons are tucked, never drawn or gridded).
    Only groups in effect count (lload_groups.normalize decides, as at export)."""
    from projects.lload import groups as lload_groups
    groups, problems = lload_groups.normalize(
        lload_groups.load(get_current_project_path()), fighters, icons)
    resolved = lload_groups.resolve(groups, fighters)
    return {
        'groups': groups,
        'problems': problems,
        'baseExternalIds': [g['base'] for g in resolved],
        'altExternalIds': [a for g in resolved for a in g['alts']],
        'eligible': [{'name': f['name'], 'externalId': f['externalId']}
                     for f in lload_groups.selectable(fighters)],
    }


@menus_bp.route('/api/mex/menus/css/layout', methods=['GET'])
def get_css_layout():
    """Get the full CSS layout from the current MEX project, with its L-load
    groups under `lload`."""
    try:
        mex = get_mex_manager()
        if mex is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        result = mex.get_css_layout()
        if result.get('fighters'):
            result['lload'] = _lload_info(result['fighters'], result.get('icons') or [])
        return jsonify(result)
    except Exception as e:
        logger.error(f'Get CSS layout error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/layout', methods=['POST'])
def set_css_layout():
    """Save CSS layout changes to the MEX project. L-load alternates are
    re-tucked behind their bases whatever the editor sent."""
    try:
        mex = get_mex_manager()
        if mex is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        layout_data = request.get_json()
        if not layout_data or 'icons' not in layout_data:
            return jsonify({'success': False, 'error': 'Missing icons data'}), 400

        from projects.lload import groups as lload_groups, layout as lload_layout
        import json as _json
        # set-css-layout saves the whole workspace, and the L code bakes icon
        # numbers in at export, so this waits for a running export (same build
        # lock as every other workspace writer).
        project_path = get_current_project_path()
        with build_access.build_session(Path(project_path).parent, timeout=120.0) as session:
            with session.external_save('mexcli set-css-layout'):
                stored = lload_groups.load(project_path)
                if stored:
                    fighters = mex.get_css_layout().get('fighters') or []
                    groups, _ = lload_groups.normalize(stored, fighters, layout_data['icons'])
                    icons, _ = lload_layout.tuck(layout_data['icons'],
                                                 lload_groups.resolve(groups, fighters))
                    layout_data = {**layout_data, 'icons': icons}
                result = mex.set_css_layout(_json.dumps(layout_data))
        return jsonify(result)
    except Exception as e:
        logger.error(f'Set CSS layout error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/lload', methods=['GET'])
def get_css_lload():
    """The project's L-load groups and the fighters that can be in one."""
    try:
        mex = get_mex_manager()
        if mex is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        layout = mex.get_css_layout()
        return jsonify({'success': True,
                        **_lload_info(layout.get('fighters') or [], layout.get('icons') or [])})
    except Exception as e:
        logger.error(f'Get L-load groups error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/lload', methods=['POST'])
def set_css_lload():
    """Save L-load groups ({groups: [{base, alts: [...]}]}, by fighter name) and
    tuck the alternates' icons now, so the editor shows the result at once.
    Unknown, blocked or duplicate names are dropped and reported in `problems`."""
    try:
        mex = get_mex_manager()
        if mex is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        body = request.get_json() or {}
        if not isinstance(body.get('groups'), list):
            return jsonify({'success': False, 'error': 'Missing groups'}), 400

        from projects.lload import groups as lload_groups, layout as lload_layout
        import json as _json
        project_path = get_current_project_path()
        with build_access.build_session(Path(project_path).parent, timeout=120.0) as session:
            with session.external_save('mexcli set-css-layout (L alternates)'):
                current = mex.get_css_layout()
                fighters = current.get('fighters') or []
                icons = current.get('icons') or []
                groups, problems = lload_groups.normalize(body['groups'], fighters, icons)
                lload_groups.save(project_path, groups)
                tucked, _ = lload_layout.tuck(icons, lload_groups.resolve(groups, fighters))
                if lload_layout.changed(icons, tucked):
                    mex.set_css_layout(_json.dumps({'icons': tucked}))
                    icons = mex.get_css_layout().get('icons') or []
        return jsonify({'success': True, **_lload_info(fighters, icons), 'problems': problems})
    except Exception as e:
        logger.error(f'Save L-load groups error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/fighter-icon', methods=['GET'])
def get_css_fighter_icon():
    """Serve a fighter icon PNG from the MEX project assets directory."""
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

        return send_file(str(icon_file), mimetype='image/png', max_age=0)
    except Exception as e:
        logger.error(f'Get CSS fighter icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/css/backdrop', methods=['GET'])
def get_css_backdrop():
    """The CSS layout editor's backdrop: the character select screen
    rendered from the user's own game (shared/vanilla_extract/menu_backdrops.py).
    404 when it cannot be made; the editor then draws a plain background."""
    from shared.vanilla_extract.menu_backdrops import backdrop_path
    path = backdrop_path('css')
    if path is None:
        return jsonify({'success': False, 'error': 'No backdrop for this screen'}), 404
    return send_file(str(path), mimetype='image/png', max_age=0)
