"""
The menus "Currently in MEX" record, project side: which vault menu mod each
slot of the open project holds (the project's nucleus_menus.json), optional
checks that the files still carry them, and the per-slot preview snapshots.

Registers on `menus_bp` (vault/routes/menus/). The vault Menus sidebar counts
are vault/routes/menus/summary.py.
"""

import logging
from pathlib import Path

from flask import jsonify, request, send_file

from vault.routes.menus import menus_bp
from vault.menus import hud_verify
from vault.menus.installed import (
    load_installed_menu_mods, save_installed_menu_mods, add_installed_menu_fields,
    installed_preview_file)
from vault.menus.percent_install import repair_hud_install_records

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/installed', methods=['GET'])
def menus_installed():
    """What each menu slot of the OPEN project currently holds, as recorded by
    the install routes: {slot_key: mod}. Slot keys are "<menu>:<submod>"
    (css:background, sss:background, css:doors, css:icon_grid,
    hud:pause_screen, hud:percent_font, hud:ready_go). Slots never installed
    through the app are absent (the project is on its vanilla scene there).

    ?verify=<menus> (comma list of hud, css, sss) also reads those menus'
    slots from the project files -- the HUD typefaces from IfAll.usd
    (hud_verify.py), the pause screen, doors, icon grid and backgrounds via
    menu_checks.py; seconds on a cache miss, so the tab asks for it
    separately -- and adds {verification: {slot_key: {state, stale?,
    unverified?}}}. Slots it cannot check are left out."""
    try:
        installed = load_installed_menu_mods()
        try:
            if repair_hud_install_records(installed):
                save_installed_menu_mods(installed)
        except Exception as e:  # a repair must never hide the record
            logger.warning(f'HUD install record repair skipped: {e}')

        body = {'success': True}
        menus = [m.strip() for m in (request.args.get('verify') or '').lower().split(',')
                 if m.strip() in ('hud', 'css', 'sss')]
        if menus:
            verification = _verify_hud(installed) if 'hud' in menus else {}
            verification.update(_verify_menus(menus, installed))
            body['verification'] = verification

        body['installed'] = {
            k: ({f: v for f, v in e.items() if f not in hud_verify.INTERNAL_FIELDS}
                if isinstance(e, dict) else e)
            for k, e in installed.items()}
        return jsonify(body)
    except Exception as e:
        logger.error(f'menus installed error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _verify_menus(menus, installed):
    """menu_checks for the open project; {} when there is nothing to check."""
    try:
        from core.state import get_current_project_path
        project = get_current_project_path()
        if project is None:
            return {}
        from vault.menus import menu_checks
        return menu_checks.verify_menu_slots(menus, installed, Path(project).parent)
    except Exception as e:  # the check must never break the record
        logger.warning(f'Menu checks skipped: {e}')
        return {}


def _verify_hud(installed):
    """hud_verify for the open project; {} when there is nothing to check."""
    try:
        from core.state import get_current_project_path
        project = get_current_project_path()
        if project is None:
            return {}
        ifall = Path(project).parent / 'files' / 'IfAll.usd'
        verification, fingerprints = hud_verify.verify_hud_slots(installed, ifall)
        if fingerprints:
            add_installed_menu_fields({
                slot_key: (installed[slot_key].get('id'), installed[slot_key].get('installed'),
                           {'hud_fingerprint': fp})
                for slot_key, fp in fingerprints.items()})
        return verification
    except Exception as e:  # the check must never break the record
        logger.warning(f'HUD verify skipped: {e}')
        return {}


@menus_bp.route('/api/mex/menus/installed/preview/<menu>/<submod>', methods=['GET'])
def menus_installed_preview(menu, submod):
    """The preview snapshot taken when the mod in <menu>:<submod> was
    installed (a copy in the project, so vault edits/deletes don't change
    it). 404 when that install predates snapshots; the panel then falls back
    to the vault URL."""
    try:
        path = installed_preview_file(f'{menu}:{submod}')
        if path is None:
            return jsonify({'success': False, 'error': 'No preview snapshot'}), 404
        return send_file(str(path), max_age=0)
    except Exception as e:
        logger.error(f'menus installed preview error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
