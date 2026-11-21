"""
Vault-wide menu mod summary: how many mods each menu kind holds.

Feeds the count badges in the vault's Menus sidebar with ONE request instead
of seven list calls. The kind keys are the vault's menu-kind ids (shared with
the frontend registry `vault/menus/menuKinds.js` and with the unified
importer's `menu_mod_type` values):

    css_icon_grid   css_background   css_doors
    sss_background
    pause_screen    percent_font     ready_go
"""

import logging

from flask import jsonify

from . import menus_bp
from vault.menus.icons import _load_catalog as _load_icon_catalog
from vault.menus.backgrounds import _load_bg_catalog
from vault.menus.doors import _load_doors_metadata
from vault.menus.pause import _load_pause_catalog
from vault.menus.percent import catalog_mods_with_categories

logger = logging.getLogger(__name__)


def menu_mod_counts():
    """{kind_key: count} for every menu kind. Mirrors each kind's list route
    exactly (a background with no recorded source shows on both screens; a
    full HUD typeface counts under both percent and ready/go)."""
    icons = [m for m in _load_icon_catalog().get('mods', []) if m.get('id')]

    bg_css = bg_sss = 0
    for m in _load_bg_catalog().get('mods', []):
        if not m.get('id'):
            continue
        src = m.get('source')
        if src != 'sss':
            bg_css += 1
        if src != 'css':
            bg_sss += 1

    doors = [m for m in _load_doors_metadata() if m.get('id')]
    pause = [m for m in _load_pause_catalog().get('mods', []) if m.get('id')]
    percent = catalog_mods_with_categories()

    return {
        'css_icon_grid': len(icons),
        'css_background': bg_css,
        'css_doors': len(doors),
        'sss_background': bg_sss,
        'pause_screen': len(pause),
        'percent_font': sum(1 for m in percent if 'percent' in m['categories']),
        'ready_go': sum(1 for m in percent if 'readygo' in m['categories']),
    }


@menus_bp.route('/api/mex/menus/summary', methods=['GET'])
def menus_summary():
    try:
        return jsonify({'success': True, 'counts': menu_mod_counts()})
    except Exception as e:
        logger.error(f'Menus summary error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
