"""
Texture extras routes.

  /api/mex/storage/textures/current|install   hue-shifted CLI textures (textures.py)
  /api/mex/storage/extras/import              the extras page's "Import .dat"
  /api/mex/storage/extras/texture-region/*    texture_region previews
                                              (texture_region.py)

The engines (textures.py, texture_recolor.py, texture_region.py) live in
vault/extras/; texture_recolor has no route of its own: the color extras, the unified importer and
the devtools (extras_audit, extras_doctor, texture_coverage) import them directly.
"""

import logging
from pathlib import Path

from flask import request, jsonify, Response

from core.metadata import load_metadata
from core.extra_lookup import get_extra_type, get_storage_character

from . import extras_bp
from vault.extras import helpers
from vault.extras.helpers import find_dat_file
from vault.extras.textures import (
    get_texture_targets, export_texture, detect_texture_hue, resolve_hue_shift,
    apply_texture_extra_hue)
from vault.extras.texture_region import (
    IMAGE_EXTS, TextureRegionError, import_texture_region_bytes, read_region, region_from_mod,
    region_to_png_bytes, vanilla_region)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Hue-shifted textures (type: "texture")
# --------------------------------------------------------------------------- #
@extras_bp.route('/api/mex/storage/textures/current/<character>/<extra_type>', methods=['GET'])
def get_current_texture_hue(character, extra_type):
    """Get the current hue of a texture extra by exporting and analyzing it.

    This is lazy-loaded - only called when user views the extra panel.
    """
    try:
        # Get extra type config
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        if type_config.get('type') != 'texture':
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" is not a texture type'
            }), 400

        # Find the target DAT file
        try:
            files_dir = helpers.get_project_files_dir()
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        target_file = type_config['target_file']
        dat_path = find_dat_file(files_dir, target_file)

        if not dat_path or not dat_path.exists():
            return jsonify({
                'success': False,
                'error': f'Could not find {target_file} in MEX project'
            }), 404

        # Get storage character for cache directory
        storage_char = get_storage_character(character, extra_type)
        textures_dir = helpers.STORAGE_PATH / storage_char / 'textures'
        textures_dir.mkdir(parents=True, exist_ok=True)

        # Check if we have a cached export that's still valid
        current_png = textures_dir / f"{extra_type}_current.png"
        cache_valid = False

        if current_png.exists():
            # Check if DAT is newer than our cached export
            dat_mtime = dat_path.stat().st_mtime
            cache_mtime = current_png.stat().st_mtime
            cache_valid = cache_mtime > dat_mtime

        if not cache_valid:
            # Export current texture from DAT (canonical = first target)
            node_path, tex_index = get_texture_targets(type_config)[0]

            try:
                export_texture(dat_path, node_path, tex_index, current_png)
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Failed to export texture: {e}'
                }), 500

        # Detect the hue
        current_hue = detect_texture_hue(str(current_png))
        vanilla_hue = type_config.get('vanilla_hue', 30)

        # Also express the current hue as an RGB color for the ColorPicker
        # UI (full saturation/value swatch, same convention as
        # texture_recolor.read_current_dominant_color).
        current_color = None
        if current_hue is not None:
            import colorsys
            r, g, b = colorsys.hls_to_rgb(current_hue / 360, 0.5, 1.0)
            current_color = f'{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}'

        return jsonify({
            'success': True,
            'hue': current_hue,
            'color': current_color,
            'vanillaHue': vanilla_hue,
            'isVanilla': current_hue is not None and abs(current_hue - vanilla_hue) < 10
        })

    except Exception as e:
        logger.error(f"Get current texture hue error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@extras_bp.route('/api/mex/storage/textures/install', methods=['POST'])
def install_texture_extra():
    """Install a texture extra by applying a hue shift and importing into DAT.

    For texture extras, the resolved hue is applied to the vanilla reference
    texture and the result is imported into the target DAT file.

    Request body (either shape accepted -- see resolve_hue_shift):
    {
        "character": "Fox",
        "extraType": "upb_texture",
        "color": "00FF00"  // NEW: target RGB color (ColorPicker)
    }
    OR (BACK-COMPAT, old saved mods / old callers):
    {
        "character": "Fox",
        "extraType": "upb_texture",
        "hue": 180  // Absolute target hue in degrees (0-360)
    }
    """
    try:
        data = request.json
        character = data.get('character')
        extra_type = data.get('extraType')

        if not character or not extra_type:
            return jsonify({
                'success': False,
                'error': 'Missing character or extraType parameter'
            }), 400

        # Get extra type config
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        if type_config.get('type') != 'texture':
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" is not a texture type'
            }), 400

        # Accept BOTH {"color": "RRGGBB"} (new) and {"hue": degrees} (old,
        # back-compat) -- resolve_hue_shift returns an absolute target hue
        # either way.
        hue = resolve_hue_shift(character, extra_type, type_config, data)
        if hue is None:
            hue = 0

        # Find the target DAT file
        try:
            files_dir = helpers.get_project_files_dir()
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        target_file = type_config['target_file']
        dat_path = find_dat_file(files_dir, target_file)

        if not dat_path or not dat_path.exists():
            return jsonify({
                'success': False,
                'error': f'Could not find {target_file} in MEX project'
            }), 404

        # Hue-shift every target texture of the extra (from vanilla refs)
        apply_texture_extra_hue(character, extra_type, type_config, hue, dat_path)

        return jsonify({
            'success': True,
            'hue': hue
        })

    except Exception as e:
        logger.error(f"Install texture extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# --------------------------------------------------------------------------- #
# texture_region: extras import + region previews
# --------------------------------------------------------------------------- #
@extras_bp.route('/api/mex/storage/extras/import', methods=['POST'])
def import_texture_region_mod():
    """Import a supported DAT or image into the selected effect.

    Multipart form: file (a full modded DAT, or an image to encode),
    character, extraType, optional name. This is the extras page's
    "Import .dat" flow. DATs use the shared effect importer; images support:
      - `texture_region` (the shield bubble): handled below
      - `image_model` extras (Fox/Falco image shines): delegated to
        vault/routes/extras/effect_model.py, which decodes/encodes a whole
        effect model rather than a fixed byte region
    Color DATs are derived into the same recipes used by their color editors.
    """
    try:
        file = request.files.get('file')
        character = request.form.get('character')
        extra_type = request.form.get('extraType')
        name = (request.form.get('name') or '').strip()

        if not file or not character or not extra_type:
            return jsonify({'success': False,
                            'error': 'Missing file, character, or extraType'}), 400

        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({'success': False,
                            'error': f'Extra type "{extra_type}" not defined for {character}'}), 400
        from vault.extras import effect_model
        if (Path(file.filename or '').suffix.lower() == '.dat'
                and type_config.get('format') != 'texture_region'):
            # Local DAT imports use the same validation/derivation as website links.
            import tempfile
            import zipfile
            from vault.importing.unified.effects import _import_effect_mod
            with tempfile.TemporaryDirectory(prefix='effect_import_') as tmp:
                archive = Path(tmp) / 'effect.zip'
                with zipfile.ZipFile(archive, 'w') as zf:
                    zf.writestr(Path(file.filename).name, file.read())
                result = _import_effect_mod(archive, f'{character}_Default.zip', extra_type,
                                            custom_title=name or Path(file.filename).stem)
            if not result or not result.get('success'):
                return jsonify(result or {'success': False, 'error': 'No supported effect DAT found'}), 400
            metadata = load_metadata(default={'characters': {}})
            storage_char = get_storage_character(character, extra_type)
            mod = next(m for m in metadata['characters'][storage_char]['extras'][extra_type]
                       if m['id'] == result['id'])
            return jsonify({'success': True, 'mod': mod})
        if effect_model.supports(type_config):
            try:
                mod = effect_model.import_image_mod(file, character, extra_type,
                                                   type_config, name)
            except effect_model.EffectModelError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
            return jsonify({'success': True, 'mod': mod})
        if type_config.get('format') != 'texture_region':
            return jsonify({'success': False,
                            'error': ('Direct file import is only supported for '
                                      'texture extras; use the color editor for this type')}), 400

        raw = file.read()
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in IMAGE_EXTS and suffix != '.dat':
            return jsonify({'success': False,
                            'error': f'Unsupported file type "{suffix}" (use .dat or an image)'}), 400
        mod = import_texture_region_bytes(
            raw, suffix, character, extra_type, type_config,
            name or Path(file.filename or 'texture').stem)
        return jsonify({'success': True, 'mod': mod})

    except TextureRegionError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"texture_region import error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@extras_bp.route('/api/mex/storage/extras/texture-region/<character>/<extra_type>',
                 methods=['GET'])
def get_texture_region_png(character, extra_type):
    """The texture region decoded to PNG. ?mod=<id> previews a stored mod's
    texture; ?source=vanilla the vanilla reference; default = the current
    project file (what is installed right now)."""
    try:
        type_config = get_extra_type(character, extra_type)
        if not type_config or type_config.get('format') != 'texture_region':
            return jsonify({'success': False,
                            'error': f'"{extra_type}" is not a texture_region extra'}), 400
        target_file = type_config['target_file']
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
            region = region_from_mod(helpers.STORAGE_PATH / storage_char,
                                     found, type_config)
        elif request.args.get('source') == 'vanilla':
            region = vanilla_region(type_config, target_file)
            if region is None:
                return jsonify({'success': False,
                                'error': 'No vanilla reference available'}), 404
        else:
            files_dir = helpers.get_project_files_dir()
            from vault.extras.helpers import find_dat_file
            dat_path = find_dat_file(files_dir, target_file)
            if not dat_path:
                return jsonify({'success': False,
                                'error': f'{target_file} not in project'}), 404
            region = read_region(dat_path, type_config)

        return Response(region_to_png_bytes(region, type_config),
                        mimetype='image/png')

    except TextureRegionError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        logger.error(f"texture_region png error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
