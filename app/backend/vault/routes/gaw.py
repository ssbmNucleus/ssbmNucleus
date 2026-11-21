"""
G&W Blueprint - Mr. Game & Watch color-mod creation.

G&W's costume colors are engine-side (the m-ex MxDt GawColors table), not in
his DAT, so the texture-painting skin creator can't make mods for him. A "G&W
color mod" is a normal vault skin whose zip wraps the vanilla PlGwNr.dat plus a
`gaw.json` sidecar ({"fill": "#AARRGGBB", "outline": "#AARRGGBB"}); on install
MexCLI's import-costume reads the sidecar and appends the matching row to the
project's GawColors table (kept in lockstep by remove/reorder). CSP + stock are
recolors of the vanilla art via the standard render pipeline (gw_colors).
"""

import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify

from core.config import STORAGE_PATH, VANILLA_ASSETS_DIR
from core.gaw_colors import (
    DEFAULT_FILL, DEFAULT_OUTLINE, format_hex_color, gw_colors_from_hex,
    parse_hex_color,
)
from core.metadata import metadata_transaction, load_metadata

logger = logging.getLogger(__name__)

gaw_bp = Blueprint('gaw', __name__)

GW_CHARACTER = 'Mr. Game & Watch'
GW_COSTUME_CODE = 'PlGwNr'


def _vanilla_gw_dat() -> Path:
    return VANILLA_ASSETS_DIR / GW_CHARACTER / GW_COSTUME_CODE / f"{GW_COSTUME_CODE}.dat"


@gaw_bp.route('/api/mex/gaw/create', methods=['POST'])
def create_gaw_color_mod():
    """
    Create a G&W color mod in the vault.

    Body: { "name": "Lavender", "fill": "#FFB48EAD", "outline": "#80FFFFFF" }
    (outline optional -> vanilla semi-transparent white)
    """
    try:
        from vault.importing.unified.helpers import compute_dat_hash, sanitize_filename
        from shared.rendering.costume_assets import build_csp_and_stock
        from generate_csp import generate_csp

        data = request.json or {}
        name = (data.get('name') or '').strip()
        fill_hex = data.get('fill')
        outline_hex = data.get('outline') or DEFAULT_OUTLINE

        if not name:
            return jsonify({'success': False, 'error': 'Missing name'}), 400
        fill = parse_hex_color(fill_hex)
        if fill is None:
            return jsonify({'success': False,
                            'error': f'Invalid fill color: {fill_hex} (expected #AARRGGBB)'}), 400
        outline = parse_hex_color(outline_hex)
        if outline is None:
            return jsonify({'success': False,
                            'error': f'Invalid outline color: {outline_hex} (expected #AARRGGBB)'}), 400
        fill_hex, outline_hex = format_hex_color(fill), format_hex_color(outline)

        vanilla_dat = _vanilla_gw_dat()
        if not vanilla_dat.exists():
            return jsonify({
                'success': False,
                'error': ("Vanilla G&W costume not found in assets. Run first-time "
                          "setup with a vanilla ISO so the vanilla bank is extracted."),
            }), 409
        dat_data = vanilla_dat.read_bytes()

        gw_colors = gw_colors_from_hex(fill_hex, outline_hex)

        # ---- unique skin id ------------------------------------------------
        metadata = load_metadata(default={'characters': {}, 'stages': {}})
        existing_ids = [s.get('id') for s in
                        metadata.get('characters', {}).get(GW_CHARACTER, {}).get('skins', [])]
        base_id = sanitize_filename(name).lower().replace(' ', '-') or 'gw-color'
        skin_id = base_id
        counter = 1
        while skin_id in existing_ids:
            skin_id = f"{base_id}{counter:02d}"
            counter += 1

        char_folder = STORAGE_PATH / GW_CHARACTER
        char_folder.mkdir(parents=True, exist_ok=True)

        # ---- render CSP (SD) + stock through the ONE canonical path --------
        assets = build_csp_and_stock(
            GW_CHARACTER, GW_COSTUME_CODE, dat_data,
            gw_colors=gw_colors, log=logger)
        csp_data, csp_source = assets['csp'], assets['csp_source']
        stock_data, stock_source = assets['stock'], assets['stock_source']
        if csp_data is None:
            return jsonify({'success': False,
                            'error': 'CSP render failed (see backend log)'}), 500

        # ---- HD CSP (4x): same render at scale 4 so exports get a colored
        # HD portrait without an export-time render.
        hd_data = None
        tmp_dir = tempfile.mkdtemp(prefix="gaw_hd_")
        try:
            tmp_dat = os.path.join(tmp_dir, f"{GW_COSTUME_CODE}.dat")
            with open(tmp_dat, 'wb') as f:
                f.write(dat_data)
            # Through the HD cache: identical render (it calls generate_csp
            # with these same arguments, and folds gw_colors into the cache
            # key), and it warms the entry the texture-pack export reads.
            from shared.rendering.hd_csp_cache import get_or_render_hd
            hd_out = get_or_render_hd(tmp_dat, scale=4, gw_colors=gw_colors)
            if hd_out and os.path.exists(hd_out):
                with open(hd_out, 'rb') as f:
                    hd_data = f.read()
        except Exception as e:  # noqa: BLE001 - HD is an upgrade, never a gate
            logger.warning(f"G&W HD CSP render failed for '{skin_id}': {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # ---- write the costume zip -----------------------------------------
        gaw_sidecar = json.dumps({'fill': fill_hex, 'outline': outline_hex}, indent=2)
        final_zip = char_folder / f"{skin_id}.zip"
        with zipfile.ZipFile(final_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{GW_COSTUME_CODE}Mod.dat", dat_data)
            zf.writestr('gaw.json', gaw_sidecar)
            zf.writestr('csp.png', csp_data)
            if stock_data:
                zf.writestr('stc.png', stock_data)

        # ---- standalone preview assets --------------------------------------
        (char_folder / f"{skin_id}_csp.png").write_bytes(csp_data)
        if stock_data:
            (char_folder / f"{skin_id}_stc.png").write_bytes(stock_data)
        if hd_data:
            (char_folder / f"{skin_id}_csp_hd.png").write_bytes(hd_data)

        # ---- metadata entry (same shape as import_character_costume) --------
        skin_entry = {
            'id': skin_id,
            'color': name,
            'costume_code': GW_COSTUME_CODE,
            'filename': f"{skin_id}.zip",
            'has_csp': True,
            'has_stock': stock_data is not None,
            'csp_source': csp_source,
            'stock_source': stock_source if stock_data else None,
            'date_added': datetime.now().isoformat(),
            'dat_hash': compute_dat_hash(dat_data),
            # The DAT is byte-identical vanilla; the colors live in the build's
            # MxDt, so the costume itself is trivially slippi-safe.
            'slippi_safe': True,
            'slippi_tested': True,
            'slippi_test_date': datetime.now().isoformat(),
            'slippi_manual_override': None,
            'gaw_colors': {'fill': fill_hex, 'outline': outline_hex},
        }
        if hd_data:
            skin_entry['has_hd_csp'] = True
            skin_entry['hd_csp_source'] = 'generated'
            skin_entry['hd_csp_filename'] = f"{skin_id}_csp_hd.png"
            skin_entry['hd_csp_resolution'] = '4x'

        with metadata_transaction(default={'characters': {}, 'stages': {}}) as live:
            live.setdefault('characters', {})
            if GW_CHARACTER not in live['characters']:
                live['characters'][GW_CHARACTER] = {'skins': []}
            live['characters'][GW_CHARACTER].setdefault('skins', []).append(skin_entry)

        logger.info(f"[OK] Created G&W color mod '{name}' ({skin_id}): "
                    f"fill {fill_hex}, outline {outline_hex}")
        return jsonify({
            'success': True,
            'character': GW_CHARACTER,
            'skin_id': skin_id,
            'name': name,
            'fill': fill_hex,
            'outline': outline_hex,
            'has_hd_csp': bool(hd_data),
        })

    except Exception as e:
        logger.error(f"G&W color mod creation error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@gaw_bp.route('/api/mex/gaw/preview-source', methods=['GET'])
def gaw_preview_source():
    """The vanilla black G&W CSP as PNG — the creator modal recolors this
    client-side for its live preview."""
    csp = VANILLA_ASSETS_DIR / GW_CHARACTER / GW_COSTUME_CODE / 'csp.png'
    if not csp.exists():
        return jsonify({'success': False, 'error': 'Vanilla G&W CSP not found'}), 404
    from flask import send_file
    return send_file(csp, mimetype='image/png')
