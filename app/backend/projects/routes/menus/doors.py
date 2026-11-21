"""
CSS door texture mods, project side: install a vault door mod into the open
project's CSS file.

Registers on `menus_bp` (vault/routes/menus/). The door store, import and
editing are vault/routes/menus/doors.py.
"""

import tempfile
import logging
from pathlib import Path
from flask import jsonify

from core.config import HSDRAW_EXE
from core.state import get_project_files_dir, get_current_project_path

from vault.routes.menus import menus_bp
from vault.menus.store import DOORS_PATH
from vault.menus.hsd import _run_hsd_cli
from vault.menus.doors import _load_doors_metadata

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/css/doors/install/<mod_id>', methods=['POST'])
def install_door_mod(mod_id):
    """Install a door texture into MnSlChr.usd using HSDRawViewer --css-doors import."""
    try:
        mods = _load_doors_metadata()
        mod = next((m for m in mods if m['id'] == mod_id), None)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        door_png = DOORS_PATH / mod_id / 'door.png'
        if not door_png.exists():
            return jsonify({'success': False, 'error': 'door.png missing from mod'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400

        mnslchr = Path(files_dir) / 'MnSlChr.usd'
        if not mnslchr.exists():
            return jsonify({'success': False, 'error': f'MnSlChr.usd not found at {mnslchr}'}), 400

        if not HSDRAW_EXE.exists():
            return jsonify({'success': False, 'error': f'HSDRawViewer not found'}), 500

        # MnSlChr.usd is a file the played build boots from, and the background
        # installer writes it too. Both go through the one build-access service:
        # locked against the other Nucleus process, recovered first, journaled
        # so a death mid-copy does not leave a half-written menu.
        from core import build_access
        build_dir = Path(get_current_project_path()).parent
        try:
            with build_access.build_session(build_dir) as session:
                # A scanner may still hold the output in here; scratch left behind must not fail the install.
                with tempfile.TemporaryDirectory(prefix='cssdoors_', ignore_cleanup_errors=True) as tmp:
                    output_usd = Path(tmp) / 'MnSlChr.usd'
                    result = _run_hsd_cli([
                        '--css-doors', 'import',
                        str(mnslchr), str(door_png), str(output_usd)
                    ])
                    if result is None:
                        return jsonify({'success': False, 'error': 'HSDRawViewer --css-doors import failed'}), 500

                    if not output_usd.exists() or not output_usd.stat().st_size:
                        return jsonify({'success': False, 'error': 'Import produced no output file'}), 500

                    session.replace_file('files/MnSlChr.usd', output_usd,
                                         label=f'css doors {mod_id}')
        except build_access.BuildBusyError as busy:
            return jsonify({'success': False, 'error': str(busy)}), 409
        except build_access.TransactionError as failed:
            logger.error('CSS door install rolled back: %s', failed)
            return jsonify({'success': False, 'error': str(failed)}), 500

        from vault.menus.installed import record_installed_menu_mod
        record_installed_menu_mod('css:doors', 'css_doors',
                                  {**mod, 'imageUrl': f'/api/mex/menus/css/doors/image/{mod_id}'})
        msg = f'Installed door "{mod["name"]}". Rebuild ISO to apply.'
        logger.info(f'[OK] Installed CSS door mod {mod_id}')
        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        logger.error(f'Install door mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
