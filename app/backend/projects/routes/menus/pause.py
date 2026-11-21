"""
Pause screen (GmPause) mods, project side: install a vault pause mod into the
open project's GmPause.usd (the write itself is pause_install.apply_pause_mod).

Registers on `menus_bp` (vault/routes/menus/). The pause mod store, import and
editing are vault/routes/menus/pause.py.
"""

import logging
from pathlib import Path
from flask import jsonify

from core.state import get_project_files_dir, get_current_project_path

from vault.routes.menus import menus_bp
from vault.menus.store import PAUSE_PATH, load_mod_json
from vault.menus.pause import _attach_pause_urls
from vault.menus.pause_install import apply_pause_mod

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/pause/install/<mod_id>', methods=['POST'])
def install_pause_mod(mod_id):
    """Install a pause mod into the loaded project's GmPause.usd via
    HSDRawViewer --pause-screen import."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400

        try:
            apply_pause_mod(mod_id, Path(files_dir) / 'GmPause.usd')
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        logger.info('  Replaced GmPause.usd with modded pause screen')

        from vault.menus.installed import record_installed_menu_mod
        record_installed_menu_mod('hud:pause_screen', 'pause_screen', _attach_pause_urls(mod))
        msg = f'Installed pause screen "{mod["name"]}". Rebuild ISO to apply.'
        logger.info(f'[OK] Installed pause mod {mod_id}')
        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        logger.error(f'Install pause mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
