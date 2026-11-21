"""
Percent font (IfAll HUD) mods, project side: install a vault typeface into the
open project's IfAll.usd and put the vanilla Percent Font or Ready/Go pictures
back.

Install runs HSDRawViewer --hud-textures import against the loaded project's
IfAll.usd with a spec.json of index->png replacements, mapping each stored
(root, kind, ordinal) slot onto the file's global texture index. The slots the
mod's categories cover are reset to vanilla in the same write, so the previous
typeface leaves nothing behind.

Registers on `menus_bp` (vault/routes/menus/). The install engine is
vault/menus/percent_install.py; the HUD mod store, import and glyph editing are
vault/routes/menus/percent.py over vault/menus/percent.py.
"""

import logging
from pathlib import Path
from flask import request, jsonify

from core.config import HSDRAW_EXE
from core.state import get_project_files_dir, get_current_project_path

from vault.routes.menus import menus_bp
from vault.menus.store import PERCENT_PATH, load_mod_json
from vault.menus.percent import _attach_percent_urls, _mod_categories
from vault.menus.percent_install import (hud_reset_keys, _vanilla_reset_replacements,
    _run_hud_import, apply_percent_mod, HUD_SLOT_BY_CATEGORY, _install_slot_keys,
    _recorded_hud_mods)

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/percent/install/<mod_id>', methods=['POST'])
def install_percent_mod(mod_id):
    """Install a percent font mod into the loaded project's IfAll.usd."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400

        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400

        ifall_path = Path(files_dir) / 'IfAll.usd'
        categories = _mod_categories(mod)
        # Put the categories this mod covers back to vanilla in the same
        # write, so the previous typeface leaves nothing behind (an emblem,
        # a READY banner) where this one has no picture.
        reset_keys = hud_reset_keys(categories, _recorded_hud_mods(categories))
        try:
            reset_notes = []
            apply_percent_mod(mod_id, ifall_path, reset_keys=reset_keys, notes=reset_notes)
            reset_note = reset_notes[0] if reset_notes else None
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        logger.info('  Replaced IfAll.usd with modded HUD textures')

        from vault.menus.installed import record_installed_menu_mod
        payload = request.get_json(silent=True) or {}
        requested = payload.get('slot') or request.args.get('slot')
        # the file as this install left it: the Menus tab's file check takes
        # the mod's fingerprint while the file still matches (hud_verify.py)
        try:
            st = ifall_path.stat()
            file_stat = [st.st_mtime_ns, st.st_size]
        except OSError:
            file_stat = None
        recorded = {}
        for slot_key in _install_slot_keys(categories, requested):
            entry = record_installed_menu_mod(
                slot_key, slot_key.split(':')[1],
                {**_attach_percent_urls(mod), 'categories': categories,
                 'file_stat': file_stat})
            if entry is not None:
                recorded[slot_key] = entry
        msg = f'Installed percent font "{mod["name"]}". Rebuild ISO to apply.'
        if reset_note:
            msg += (' The previous HUD textures were not cleared first ('
                    f'{reset_note.rstrip(".")}), so parts of an older mod may remain.')
        logger.info(f'[OK] Installed percent mod {mod_id} -> {sorted(recorded) or "no record"}')
        return jsonify({'success': True, 'message': msg, 'installed': recorded,
                        'resetSkipped': bool(reset_note)})
    except Exception as e:
        logger.error(f'Install percent mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


_RESTORE_CATEGORY = {'percent_font': 'percent', 'hud:percent_font': 'percent', 'percent': 'percent',
                     'ready_go': 'readygo', 'hud:ready_go': 'readygo', 'readygo': 'readygo'}


@menus_bp.route('/api/mex/menus/percent/restore-vanilla', methods=['POST'])
def restore_vanilla_hud_slot():
    """Put the vanilla Percent Font or Ready/Go pictures back into the open
    project's IfAll.usd. Body: {slot: 'percent_font'|'ready_go'}.

    The slots come from the vanilla IfAll.usd on the user's vanilla ISO and
    are re-encoded into the project's slots (not byte-identical when a mod
    changed a slot's texture format, but the same picture; the Menus tab's
    file check reads it as vanilla). Only that category's slots, plus the
    ones the recorded mod wrote for it, change; stock icons, emblems and the
    other category stay as they are. Clears the slot's record."""
    try:
        payload = request.get_json(silent=True) or {}
        category = _RESTORE_CATEGORY.get(str(payload.get('slot') or '').strip().lower())
        if category is None:
            return jsonify({'success': False, 'error': "slot must be 'percent_font' or 'ready_go'"}), 400
        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No MEX project loaded'}), 400
        files_dir = get_project_files_dir()
        if files_dir is None:
            return jsonify({'success': False, 'error': 'No project files directory'}), 400
        ifall_path = Path(files_dir) / 'IfAll.usd'
        if not ifall_path.exists():
            return jsonify({'success': False, 'error': f'IfAll.usd not found at {ifall_path}'}), 400
        if not HSDRAW_EXE.exists():
            return jsonify({'success': False, 'error': f'HSDRawViewer not found at {HSDRAW_EXE}'}), 500

        keys = hud_reset_keys([category], _recorded_hud_mods([category]))
        try:
            replacements = _vanilla_reset_replacements(keys, 'usd')
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        if not replacements:
            return jsonify({'success': False, 'error': 'Vanilla HUD pictures unavailable'}), 500
        try:
            _run_hud_import(ifall_path, replacements)
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 500

        from vault.menus.installed import clear_installed_menu_mod
        slot_key = HUD_SLOT_BY_CATEGORY[category]
        clear_installed_menu_mod(slot_key)
        label = 'percent font' if category == 'percent' else 'Ready / Go / Game graphics'
        logger.info(f'[OK] Restored vanilla {label} ({len(replacements)} slots)')
        return jsonify({'success': True, 'cleared': slot_key,
                        'message': f'Restored the vanilla {label}. Rebuild ISO to apply.'})
    except Exception as e:
        logger.error(f'Restore vanilla HUD error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
