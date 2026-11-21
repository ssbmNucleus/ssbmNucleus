"""
CSS icon grid mods, project side: install a vault icon grid into the open
project, one icon per fighter (`mexcli set-css-icon`, under the build lock),
and record the grid as the css:icon_grid occupant once an icon really lands.

Registers on `menus_bp` (vault/routes/menus/). The icon grid store, import and
editing are vault/routes/menus/icons.py.
"""

import subprocess
import uuid
import logging
from pathlib import Path
from flask import request, jsonify

from core.config import MEXCLI_PATH, get_subprocess_args
from core.state import get_current_project_path

from vault.routes.menus import menus_bp
from vault.menus.store import ICON_GRID_PATH
from vault.menus.icons import EXTRA_ICON_PREFIX, _attach_urls, _load_mod_json

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/css/icon_grid/install/<mod_id>', methods=['POST'])
def install_icon_grid_to_mex(mod_id):
    """Return the install plan (list of icons to install) without executing."""
    try:
        mod = _load_mod_json(mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        install_list = list(mod.get('icons', []))
        has_zelda = any(e.get('character') == 'Zelda' for e in install_list)
        has_sheik = any(e.get('character') == 'Sheik' for e in install_list)
        if has_zelda and not has_sheik:
            zelda_entry = next(e for e in install_list if e.get('character') == 'Zelda')
            install_list.append({'character': 'Sheik', 'icon': zelda_entry['icon']})
        elif has_sheik and not has_zelda:
            sheik_entry = next(e for e in install_list if e.get('character') == 'Sheik')
            install_list.append({'character': 'Zelda', 'icon': sheik_entry['icon']})

        valid = []
        icons_dir = ICON_GRID_PATH / mod_id / 'icons'
        for entry in install_list:
            character = entry.get('character')
            icon_file = entry.get('icon')
            if character and character.startswith(EXTRA_ICON_PREFIX):
                continue  # unnamed placeholder: no fighter to target until relabeled
            if character and icon_file and (icons_dir / icon_file).exists():
                valid.append({'character': character, 'icon': icon_file})

        # Nothing is patched yet: the per-icon step records the grid as the
        # slot's occupant once an icon really lands (a failed install used to
        # show as installed). The plan id + total ride along in each icon
        # entry so those steps can tell a partial install from a full one.
        plan_id = uuid.uuid4().hex[:12]
        for entry in valid:
            entry['plan'] = plan_id
            entry['total'] = len(valid)
        return jsonify({'success': True, 'icons': valid, 'total': len(valid)})
    except Exception as e:
        logger.error(f'Icon grid install plan error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _record_icon_installed(mod_id, character, plan=None, total=None):
    """Record the grid as css:icon_grid after one of its icons really landed.
    Icons of the same install plan accumulate, so the record says how many
    of the planned icons made it. Best-effort: never raises."""
    try:
        from vault.menus.installed import load_installed_menu_mods, record_installed_menu_mod
        mod = _load_mod_json(mod_id)
        if not mod:
            return
        prev = load_installed_menu_mods().get('css:icon_grid') or {}
        done = []
        if prev.get('id') == mod_id and prev.get('plan') == plan:
            done = [c for c in (prev.get('icons_installed') or []) if isinstance(c, str)]
        if character not in done:
            done.append(character)
        entry = {**_attach_urls(mod), 'plan': plan, 'icons_installed': done}
        if isinstance(total, int) and total > 0:
            entry['icons_total'] = total
        record_installed_menu_mod('css:icon_grid', 'css_icon_grid', entry)
    except Exception as e:  # pragma: no cover - bookkeeping must not fail an install
        logger.warning(f'Could not record icon grid install for {mod_id}: {e}')


@menus_bp.route('/api/mex/menus/css/icon_grid/install/<mod_id>/icon', methods=['POST'])
def install_single_css_icon(mod_id):
    """Install a single CSS icon for one fighter."""
    try:
        data = request.get_json()
        character = data.get('character')
        icon_file = data.get('icon')
        if not character or not icon_file:
            return jsonify({'success': False, 'error': 'Missing character or icon'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        if not MEXCLI_PATH.exists():
            return jsonify({'success': False, 'error': 'MexCLI not found'}), 500

        icons_dir = ICON_GRID_PATH / mod_id / 'icons'
        src = icons_dir / icon_file
        if not src.exists():
            return jsonify({'success': False, 'error': f'Icon file not found: {icon_file}'}), 404

        # set-css-icon opens and SAVES the whole MexManager workspace
        # (SetCssIconCommand.cs). Two of those at once corrupts the project, and
        # the other one may be in a different Nucleus process, so it takes the
        # same build lock every other writer does -- and recovers an interrupted
        # change before writing on top of it.
        from core import build_access
        try:
            with build_access.build_session(Path(project_path).parent,
                                            timeout=120.0) as session:
                # A whole-workspace save, bracketed so an interrupted one is
                # detected rather than leaving a project nobody can account for.
                with session.external_save('mexcli set-css-icon'):
                    result = subprocess.run(
                        [str(MEXCLI_PATH), 'set-css-icon',
                         str(project_path), character, str(src)],
                        capture_output=True, text=True, timeout=30,
                        **get_subprocess_args()
                    )
                    if result.returncode != 0:
                        raise build_access.TransactionError(
                            'set_css_icon_failed',
                            result.stdout.strip() or result.stderr.strip() or
                            f'mexcli set-css-icon exited {result.returncode}')
                _record_icon_installed(mod_id, character, data.get('plan'), data.get('total'))
        except build_access.BuildBusyError as busy:
            return jsonify({'success': False, 'error': str(busy)}), 409
        except build_access.BuildQuarantined as blocked:
            return jsonify({'success': False, 'error': str(blocked)}), 409
        except build_access.TransactionError as failed:
            return jsonify({'success': False, 'error': str(failed)}), 500
        if result.returncode == 0:
            return jsonify({'success': True, 'character': character})
        else:
            err_msg = result.stdout.strip() or result.stderr.strip()
            return jsonify({'success': False, 'error': err_msg}), 500
    except Exception as e:
        logger.error(f'Install single CSS icon error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
