"""
Effect model extras route: the effect's image as PNG, from a stored mod or from
the open project's DAT. The image effect model engine (Fox/Falco image shines)
is vault/extras/effect_model.py.
"""

import logging
from pathlib import Path

from flask import request, jsonify, Response

from core.metadata import load_metadata
from core.extra_lookup import get_extra_type, get_storage_character

from . import extras_bp
from vault.extras import helpers
from vault.extras.effect_model import (EffectModelError, parse_cfg, supports, EffectDat,
                                       read_texture, png_from_dat, png_from_mod)

logger = logging.getLogger(__name__)


@extras_bp.route('/api/mex/storage/extras/effect-image/<character>/<extra_type>',
                 methods=['GET'])
def get_effect_image_png(character, extra_type):
    """The effect model's image as PNG.

    `?mod=<id>` previews a stored mod's image; default = whatever is in the
    current project file, which 404s with `installed: false` when the model
    is still the vanilla (untextured) one -- that is how the editor knows
    whether an image shine is live.
    """
    try:
        type_config = get_extra_type(character, extra_type)
        if not supports(type_config):
            return jsonify({'success': False,
                            'error': f'"{extra_type}" has no image support'}), 400
        storage_char = get_storage_character(character, extra_type)

        mod_id = request.args.get('mod')
        if mod_id:
            metadata = load_metadata() or {}
            mods = (metadata.get('characters', {}).get(storage_char, {})
                    .get('extras', {}).get(extra_type, []))
            found = next((m for m in mods if m.get('id') == mod_id), None)
            if not found:
                return jsonify({'success': False,
                                'error': f'Mod {mod_id} not found'}), 404
            png = png_from_mod(helpers.STORAGE_PATH / storage_char,
                              found, type_config)
        else:
            from vault.extras.helpers import find_dat_file
            files_dir = helpers.get_project_files_dir()
            dat_path = find_dat_file(files_dir, type_config['target_file'])
            if not dat_path:
                return jsonify({
                    'success': False,
                    'error': f'{type_config["target_file"]} not in project'}), 404
            raw = Path(dat_path).read_bytes()
            if read_texture(EffectDat(raw), parse_cfg(type_config)) is None:
                return jsonify({'success': False, 'installed': False,
                                'error': 'no image effect is installed'}), 404
            png = png_from_dat(raw, type_config)

        return Response(png, mimetype='image/png')

    except EffectModelError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f'effect image png error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
