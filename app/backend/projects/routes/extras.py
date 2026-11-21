"""
Color extras in the open project: the colors an extra has in the project's DAT
now, installing a stored extra into it, and putting the vanilla colors back.
restore-vanilla also serves model extras (Fox's and Falco's gun): it copies the
vanilla model back from the vanilla reference DAT. Installing a model extra is
vault/routes/extras/models.py.

These routes register on `extras_bp` from vault/routes/extras/ (the stored
extras library: colors.py lists, creates and deletes color extras), which
imports this module on its last line so the blueprint is complete before it is
registered; URLs and endpoint names are unchanged. The engine is vault/extras/.
"""

import os
import logging
import shutil
import file_retry
from flask import jsonify, make_response, request
from core.metadata import load_metadata, save_metadata
from core.extra_lookup import get_extra_type, get_storage_character, get_unit_parts
from vault.extras.unit_parts import apply_parts, own_modifications, part_modifications, restore_parts
from vault.routes.extras import extras_bp
from vault.extras import helpers, texture_region, effect_model, sideb_model
from vault.extras.color_patch import (
    apply_hex_patches, ensure_laser_ring_anim_disabled, patch_shine_sparkle_color)
from vault.extras.color_read import (
    current_verdict, read_shine_colors_resolved, read_shine_gradient_colors,
    read_shine_sparkle_color, read_shine_sparkle_resolved)
from vault.extras.helpers import find_dat_file, make_write_safety, resolve_current_colors
from vault.extras.offsets import get_dynamic_offsets
from vault.extras.textures import apply_texture_extra_hue, restore_texture_extra
from vault.extras.texture_recolor import (
    apply_texture_recolor, read_current_dominant_color, restore_texture_recolor)
from vault.extras.texture_region import TextureRegionError
from vault.extras.effect_model import EffectModelError
from vault.extras.models import ModelToolError, restore_vanilla_model
from vault.extras.apply import SIBLING_TEXTURE_EXTRAS

logger = logging.getLogger(__name__)


@extras_bp.route('/api/mex/storage/extras/current/<character>/<extra_type>', methods=['GET'])
def get_current_extra(character, extra_type):
    """Read current colors from the .dat file in MEX project.

    Returns the actual colors currently in the build, read where a guarded
    install would write them. `status` is 'vanilla' | 'custom' | 'unknown'
    ('unknown' = a compared layer could not be located in this file; those
    ids are in `unknownLayers`, and `layoutVerified` is False when no
    vanilla reference was available to check positions against).
    `isVanilla` is true only for a confirmed vanilla reading. For a unit,
    `parts` carries the same reading for each nested part
    ({part_id: {colors, isVanilla, status, unknownLayers, vanilla}}) and the
    unit's `status` is custom if any piece is, else unknown if any piece is.
    """
    # make_response: error branches return (body, status) tuples, which have
    # no .status_code -- a unit whose read failed used to 500 here.
    response = make_response(_current_extra_response(character, extra_type))
    parts = get_unit_parts(character, extra_type)
    if not parts or response.status_code != 200:
        return response
    payload = response.get_json()
    if not payload.get('success'):
        return response
    payload['parts'] = {}
    statuses = [_reading_status(payload)]
    for part_id, _cfg in parts:
        part_response = make_response(_current_extra_response(character, part_id))
        part_payload = part_response.get_json() if part_response.status_code == 200 else None
        if part_payload and part_payload.get('success'):
            part_status = _reading_status(part_payload)
            payload['parts'][part_id] = {
                'colors': part_payload.get('colors', {}),
                'isVanilla': part_payload.get('isVanilla', True),
                'status': part_status,
                'unknownLayers': part_payload.get('unknownLayers', []),
                'vanilla': part_payload.get('vanilla', {}),
            }
            statuses.append(part_status)
            if not part_payload.get('isVanilla', True):
                payload['isVanilla'] = False
    # The move as a whole: any custom part makes it Custom; otherwise any
    # unreadable part makes it Unknown.
    payload['status'] = ('custom' if 'custom' in statuses
                         else 'unknown' if 'unknown' in statuses else 'vanilla')
    payload['isVanilla'] = payload['status'] == 'vanilla'
    return jsonify(payload)


def _reading_status(payload):
    """A current-read payload's verdict; readings that predate `status`
    (or have no layers to prove) fall back to their isVanilla flag."""
    return payload.get('status') or ('vanilla' if payload.get('isVanilla') else 'custom')


def _current_extra_response(character, extra_type):
    """One extra type's current colors as a Flask response (the body of
    GET /storage/extras/current before units existed)."""
    try:
        # Get extra type config
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        # Find the .dat file in MEX project
        try:
            files_dir = helpers.get_project_files_dir()
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        target_file = type_config['target_file']
        vanilla = type_config.get('vanilla', {})
        dat_path = find_dat_file(files_dir, target_file)

        if not dat_path or not dat_path.exists():
            return jsonify({
                'success': False,
                'error': f'Could not find {target_file} in MEX project'
            }), 404

        if sideb_model.supports(type_config):
            try:
                recipe = sideb_model.replacement_recipe(dat_path.read_bytes())
            except sideb_model.SideBModelError as error:
                return jsonify({'success': True, 'colors': {}, 'isVanilla': False,
                                'status': 'unknown', 'detail': str(error), 'vanilla': vanilla})
            if recipe:
                return jsonify({'success': True, 'colors': {}, 'isVanilla': False,
                                'status': 'custom', 'sidebModel': recipe['sideb_model'],
                                'vanilla': vanilla})
            current_colors = sideb_model.colors(dat_path.read_bytes())
            is_vanilla = current_colors == vanilla
            return jsonify({'success': True, 'colors': current_colors, 'isVanilla': is_vanilla,
                            'status': 'vanilla' if is_vanilla else 'custom',
                            'layoutVerified': True, 'unknownLayers': [], 'vanilla': vanilla})

        # image_model extras: when an image effect is installed the colors
        # below describe a model the game no longer draws, so answer with the
        # image instead. `imageInstalled` is what the editor opens in image
        # mode on (vault/routes/extras/effect_model.py).
        if effect_model.supports(type_config):
            try:
                image = effect_model.read_texture(
                    effect_model.EffectDat(dat_path.read_bytes()),
                    effect_model.parse_cfg(type_config))
            except EffectModelError as e:
                logger.warning(f"[GetCurrent] image probe failed for "
                               f"{character}/{extra_type}: {e}")
                image = None
            if image is not None:
                return jsonify({
                    'success': True,
                    'colors': {},
                    'isVanilla': False,
                    'vanilla': vanilla,
                    'imageInstalled': True,
                    'image': {'width': image['width'],
                              'height': image['height'],
                              'gxFormat': image['gx_format']},
                })

        # texture_region: no colors to read -- report whether the region
        # bytes still match vanilla (see vault/extras/texture_region.py).
        # Without a vanilla reference there is nothing to compare: unknown.
        if type_config.get('format') == 'texture_region':
            try:
                current = texture_region.read_region(dat_path, type_config)
            except TextureRegionError as e:
                return jsonify({'success': False, 'error': str(e)}), 500
            van = texture_region.vanilla_region(type_config, target_file)
            status = ('unknown' if van is None
                      else 'vanilla' if current == van else 'custom')
            body = {
                'success': True,
                'colors': {},
                'isVanilla': status == 'vanilla',
                'status': status,
                'vanilla': {}
            }
            if van is None:
                body['detail'] = 'No vanilla reference to compare the texture with'
            return jsonify(body)

        # texture_recolor: vanilla/custom from the texture's exact bytes
        # (helpers.texture_recolor_status); the swatch is the dominant hue
        # of what is installed -- an approximation, flagged as such.
        if type_config.get('format') == 'texture_recolor':
            tex_cfg = dict(type_config['texture'])
            tex_cfg['_target_file'] = target_file
            prop_id = type_config['properties'][0]['id']
            vanilla_color = vanilla.get(prop_id)
            status = helpers.texture_recolor_status(dat_path, type_config)
            if status == 'vanilla':
                colors = {prop_id: vanilla_color} if vanilla_color else {}
            elif status == 'custom':
                current_color = read_current_dominant_color(dat_path, tex_cfg)
                colors = {prop_id: current_color} if current_color else {}
            else:
                colors = {}
            body = {
                'success': True,
                'colors': colors,
                'isVanilla': status == 'vanilla',
                'status': status,
                'approximate': status == 'custom',
                'vanilla': vanilla
            }
            if status == 'unknown':
                body['detail'] = "Couldn't locate this texture in the project file"
            return jsonify(body)

        # Model-type extras (e.g. gun) have no offsets/colors to read:
        # which model is installed is not something Nucleus can detect, so
        # say so instead of claiming vanilla.
        if 'offsets' not in type_config:
            return jsonify({
                'success': True,
                'colors': {},
                'isVanilla': False,
                'status': 'unknown',
                'detail': "Nucleus can't detect which model is installed",
                'vanilla': vanilla
            })

        fallback_offsets = type_config['offsets']
        # Use dynamic offset detection for laser/sideb, fallback to hardcoded
        offsets = get_dynamic_offsets(dat_path, extra_type, fallback_offsets)

        # Both branches below read where a guarded install would write (see
        # helpers.resolve_current_colors). `status` is the honest verdict --
        # 'unknown' when a compared layer could not be located -- and
        # `isVanilla` stays a plain "confirmed vanilla" boolean.

        # Special handling for shine_gradient format (two-color gradient)
        if type_config.get('format') == 'shine_gradient':
            safety = make_write_safety(dat_path, extra_type, target_file, vanilla)
            vanilla_path = safety.get('vanilla_path')
            verified = bool(vanilla_path and os.path.exists(vanilla_path))
            hex_offset = offsets.get('hex', {})
            sparkles_offset = offsets.get('sparkles', {})
            unknown = []
            if verified:
                # Same vertex-identity slots patch_shine_color_slots writes.
                try:
                    current_colors = read_shine_colors_resolved(dat_path, type_config, vanilla_path)
                except ValueError as e:
                    logger.warning(f"[GetCurrent] {character}/{extra_type}: {e}")
                    current_colors = {}
                unknown += [c for c in ('primary', 'secondary') if c not in current_colors]
                if sparkles_offset:
                    sparkle = read_shine_sparkle_resolved(dat_path, sparkles_offset, safety)
                    if sparkle:
                        current_colors['sparkles'] = sparkle
                    else:
                        unknown.append('sparkles')
            else:
                current_colors = read_shine_gradient_colors(dat_path, hex_offset)
                if sparkles_offset:
                    current_colors['sparkles'] = read_shine_sparkle_color(dat_path, sparkles_offset)

            compared = {'primary': vanilla.get('primary', ''),
                        'secondary': vanilla.get('secondary', '')}
            if sparkles_offset and 'sparkles' in vanilla:
                compared['sparkles'] = vanilla['sparkles']
            status = current_verdict(current_colors, compared,
                                     {layer: True for layer in compared}, unknown)
            return jsonify({
                'success': True,
                'colors': current_colors,
                'isVanilla': status == 'vanilla',
                'status': status,
                'unknownLayers': unknown,
                'layoutVerified': verified,
                'vanilla': vanilla
            })

        # Layers dynamic detection located by content in THIS file are read
        # where it found them; config offsets go through write resolution.
        trusted = {layer for layer, info in offsets.items()
                   if fallback_offsets.get(layer) != info}
        current_colors, unresolved, verified, reference = resolve_current_colors(
            dat_path, offsets, extra_type, target_file, vanilla, trusted,
            config_offsets=fallback_offsets)
        for skip in unresolved:
            logger.warning(f"[GetCurrent] {character}/{extra_type}/{skip['layer_id']}: "
                           f"not read ({skip['reason']})")
        unknown = [skip['layer_id'] for skip in unresolved]
        status = current_verdict(current_colors, vanilla, offsets, unknown, reference)

        return jsonify({
            'success': True,
            'colors': current_colors,
            'isVanilla': status == 'vanilla',
            'status': status,
            'unknownLayers': unknown,
            'layoutVerified': verified,
            'vanilla': vanilla
        })

    except Exception as e:
        logger.error(f"Get current extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@extras_bp.route('/api/mex/storage/extras/install', methods=['POST'])
def install_extra():
    """Install an extra mod by patching the .dat file.

    For shared extras, retrieves mod from owner character's storage.

    Request body:
    {
        "character": "Falco",
        "extraType": "laser",
        "modId": "laser_abc123"
    }
    """
    try:
        data = request.json
        character = data.get('character')
        extra_type = data.get('extraType')
        mod_id = data.get('modId')

        if not character or not extra_type or not mod_id:
            return jsonify({
                'success': False,
                'error': 'Missing character, extraType, or modId parameter'
            }), 400

        # Get extra type config
        type_config = get_extra_type(character, extra_type)
        if not type_config:
            return jsonify({
                'success': False,
                'error': f'Extra type "{extra_type}" not defined for {character}'
            }), 400

        # Get the storage character (owner for shared extras)
        storage_char = get_storage_character(character, extra_type)

        # Find the .dat file in MEX project
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

        is_texture_recolor = type_config.get('format') == 'texture_recolor'
        is_texture_region = type_config.get('format') == 'texture_region'
        offsets = {}
        if not is_texture_recolor and not is_texture_region and not sideb_model.supports(type_config):
            fallback_offsets = type_config['offsets']
            # Use dynamic offset detection for laser/sideb, fallback to hardcoded
            offsets = get_dynamic_offsets(dat_path, extra_type, fallback_offsets)

        # Load metadata to find the mod (via the core.metadata DAL)
        metadata = load_metadata()
        if metadata is None:
            return jsonify({
                'success': False,
                'error': 'Metadata file not found'
            }), 404

        # Find the mod (from storage character)
        char_data = metadata.get('characters', {}).get(storage_char, {})
        extras = char_data.get('extras', {})
        mods = extras.get(extra_type, [])

        found_mod = None
        for mod in mods:
            if mod.get('id') == mod_id:
                found_mod = mod
                break

        if not found_mod:
            return jsonify({
                'success': False,
                'error': f'Mod {mod_id} not found'
            }), 404

        # texture_region: the mod IS its stored source (a full modded DAT
        # from the website effect import, or an encoded PNG region) -- no
        # 'modifications' dict exists or is needed. Copy the region bytes
        # into the target on an isolated temp copy, then swap atomically.
        if is_texture_region:
            try:
                region = texture_region.region_from_mod(
                    helpers.STORAGE_PATH / storage_char, found_mod,
                    type_config)
                patch_path = dat_path.with_name(dat_path.name + '.patching')
                shutil.copy2(dat_path, patch_path)
                texture_region.write_region(patch_path, type_config, region)
                file_retry.replace(patch_path, dat_path)
            except (TextureRegionError, OSError) as e:
                logger.error(f"[Install] texture_region {extra_type} failed: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
            logger.info(f"[OK] Installed {found_mod['name']} (texture_region) "
                        f"to {target_file} at {dat_path}")
            return jsonify({'success': True})

        # Heal mods imported before modifications were derived at import
        # time (website effect zips stored only the modded DAT): remake the
        # mod's colors from its stored DAT once and persist them, so old
        # imports stop installing as silent no-ops.
        if not found_mod.get('modifications') and found_mod.get('model_file'):
            stored_dat = helpers.STORAGE_PATH / storage_char / found_mod['model_file']
            if stored_dat.suffix.lower() == '.dat' and stored_dat.exists():
                derived = helpers.derive_modifications_from_dat(
                    stored_dat, extra_type, type_config)
                if derived:
                    found_mod['modifications'] = derived
                    save_metadata(metadata)
                    logger.info(f"[Install] Backfilled modifications for "
                                f"{mod_id} from {found_mod['model_file']}: {derived}")

        if sideb_model.supports(type_config):
            try:
                if sideb_model.is_model_mod(found_mod):
                    sideb_model.install_mod(dat_path, helpers.STORAGE_PATH / storage_char, found_mod)
                else:
                    sideb_model.apply_colors(dat_path, found_mod.get('modifications', {}))
            except (sideb_model.SideBModelError, OSError) as error:
                return jsonify({'success': False, 'error': str(error)}), 409
            return jsonify({'success': True})

        # image_model extras (Fox/Falco image shines): the mod IS an image, not
        # a color dict, so it installs by rebuilding the effect model around
        # that image (vault/routes/extras/effect_model.py). Checked AFTER the
        # heal above so a pre-2026-09 website import -- stored DAT, no
        # modifications -- is recognized once derive marks it as an image.
        if effect_model.supports(type_config) and effect_model.is_image_mod(found_mod):
            try:
                effect_model.install_mod(
                    dat_path, helpers.STORAGE_PATH / storage_char,
                    found_mod, type_config)
            except (EffectModelError, OSError) as e:
                logger.error(f"[Install] image {extra_type} failed: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
            logger.info(f"[OK] Installed {found_mod['name']} (image "
                        f"{extra_type}) to {target_file} at {dat_path}")
            return jsonify({'success': True})

        # Apply the patch. A unit mod's nested parts (modifications['parts'])
        # are written after the primary's own layers, below.
        all_modifications = found_mod.get('modifications', {}) or {}
        nested_parts = part_modifications(all_modifications)
        modifications = ensure_laser_ring_anim_disabled(
            extra_type, own_modifications(all_modifications))
        logger.info(f"[Install] {extra_type} for {character}: offsets={offsets}, modifications={modifications}")
        offset_skips = []
        part_errors = []
        if modifications:
            # Patch an isolated temp copy, then atomically swap it in below:
            # an exception between layer writes must never leave the project
            # file half-patched. (A stale .patching file from a failed run is
            # harmless -- find_dat_file matches exact names and the next
            # install's copy2 overwrites it.)
            patch_path = dat_path.with_name(dat_path.name + '.patching')
            shutil.copy2(dat_path, patch_path)
            # A previously installed image shine REPLACES the very model the
            # gradient colors live on, so a color install onto it would write
            # bytes nothing draws. Take the image back out first (no-op when
            # none is installed) -- see vault/routes/extras/effect_model.py.
            if effect_model.supports(type_config):
                try:
                    if effect_model.revert_installed(patch_path, type_config):
                        logger.info(f"[Install] removed the installed image "
                                    f"{extra_type} before applying colors")
                except EffectModelError as e:
                    # Refusing beats writing colors onto a model the game no
                    # longer draws and reporting success.
                    logger.error(f"[Install] cannot remove the installed "
                                 f"image {extra_type}: {e}")
                    patch_path.unlink(missing_ok=True)
                    return jsonify({'success': False, 'error': str(e)}), 409
            # texture_recolor: raw-texel hue-rotate patch (no offsets dict)
            if is_texture_recolor:
                tex_cfg = dict(type_config['texture'])
                tex_cfg['_target_file'] = target_file
                prop_id = type_config['properties'][0]['id']
                color = modifications.get(prop_id, {}).get('color')
                if color:
                    apply_texture_recolor(
                        patch_path, tex_cfg, color,
                        vanilla_hue=type_config.get('vanilla_dominant_hue'))
                    logger.info(f"[OK] Installed {found_mod['name']} (texture_recolor) to {target_file} at {dat_path}")
                else:
                    logger.warning(f"[Install] texture_recolor {extra_type} mod {mod_id} has no '{prop_id}' color")
            # Special handling for shine_gradient format (two-color gradient + optional flash)
            elif type_config.get('format') == 'shine_gradient':
                hex_offset = offsets.get('hex', {})

                # Read CURRENT colors from the file (might be vanilla or from another mod)
                current_colors = read_shine_gradient_colors(patch_path, hex_offset)
                current_primary = current_colors.get('primary', '621F')
                current_secondary = current_colors.get('secondary', 'AB9F')

                # Get new colors from modifications
                vanilla = type_config.get('vanilla', {})
                new_primary = modifications.get('primary', {}).get('color', vanilla.get('primary', '621F'))
                new_secondary = modifications.get('secondary', {}).get('color', vanilla.get('secondary', 'AB9F'))

                # Slot identity survives repeated and uniform recolors.
                helpers.patch_shine_color_slots(
                    patch_path, type_config, dict(modifications,
                        primary={'color': new_primary},
                        secondary={'color': new_secondary}))

                # Patch sparkle color if provided (CF-multi records)
                sparkles_mod = modifications.get('sparkles', {}).get('color')
                if sparkles_mod:
                    sparkles_offset = offsets.get('sparkles', {})
                    if sparkles_offset:
                        sparkle_safety = make_write_safety(
                            patch_path, extra_type, target_file,
                            type_config.get('vanilla'))
                        patch_shine_sparkle_color(patch_path, sparkles_offset,
                                                  sparkles_mod, safety=sparkle_safety)
                        offset_skips.extend(sparkle_safety['skipped'])

                logger.info(f"[OK] Installed shine gradient {found_mod['name']}: {current_primary}->{new_primary}, {current_secondary}->{new_secondary}")
            else:
                safety = make_write_safety(patch_path, extra_type, target_file,
                                           type_config.get('vanilla'))
                # The nested sibling texture key (falcon_punch/upb 'fire') is
                # the sibling texture extra's colour, applied below; it is not
                # a colour layer of this extra.
                sibling = SIBLING_TEXTURE_EXTRAS.get(extra_type)
                color_layers = {key: value for key, value in modifications.items()
                                if not sibling or key != sibling[0]}
                offset_skips.extend(apply_hex_patches(patch_path, offsets, color_layers,
                                                       safety=safety) or [])
                logger.info(f"[OK] Installed {found_mod['name']} to {target_file} at {dat_path}")

            # All hex/texel patches succeeded on the temp copy -- swap it into
            # place (atomic on the same volume; readers/exports never observe
            # a half-patched file).
            file_retry.replace(patch_path, dat_path)

            # Handle a nested sibling texture extra if present (upb -> fire ->
            # upb_texture; falcon_punch -> fire -> punch_texture). Accepts
            # BOTH the old {"hue": degrees} shape and the new
            # {"color": "RRGGBB"} shape -- resolve_hue_shift is the single
            # back-compat conversion point (see textures.py module docstring).
            # (Runs on the real file AFTER the swap: its writer is the
            # HSDRawViewer import pipeline, which does its own full re-save,
            # and its failure is deliberately non-fatal.)
            sibling = SIBLING_TEXTURE_EXTRAS.get(extra_type)
            if sibling:
                nested_key, texture_extra_id = sibling
                nested_mod = modifications.get(nested_key)
                if nested_mod:
                    from vault.extras.textures import resolve_hue_shift
                    hue = resolve_hue_shift(character, texture_extra_id,
                                            get_extra_type(character, texture_extra_id) or {},
                                            nested_mod)
                    if hue is not None:
                        logger.info(f"[Install] Applying {texture_extra_id} target hue: {hue}")
                        try:
                            texture_config = get_extra_type(character, texture_extra_id)
                            if texture_config:
                                # Hue-shift every target texture (one target
                                # per unique image node, audit 2026-07)
                                apply_texture_extra_hue(character, texture_extra_id,
                                                        texture_config, hue,
                                                        dat_path)
                                logger.info(f"[OK] Applied {texture_extra_id} hue {hue} to {target_file}")
                        except Exception as tex_err:
                            logger.error(f"[Install] {texture_extra_id} hue failed: {tex_err}")
                            # Don't fail the whole install, just log the error
        elif not nested_parts:
            # Nothing to apply and nothing derivable from the stored DAT --
            # an honest error beats the pre-2026-08 behavior of reporting
            # success while the game stayed vanilla. Typical cause: an
            # image/texture-based effect (rebuilt DAT) imported into a
            # color-format extra type.
            logger.warning(f"[Install] No modifications found in mod {mod_id}")
            return jsonify({
                'success': False,
                'error': ('This mod has no color data Nucleus can apply -- '
                          'it may be an image/texture-based effect, which '
                          'this effect type does not support yet.')
            }), 422

        # Nested parts (the unit's other pieces: flight puff texture, charge
        # flames, fireball aura...) each patch their own target file.
        if nested_parts:
            part_result = apply_parts(character, all_modifications, files_dir)
            offset_skips.extend(part_result['offset_skips'])
            part_errors.extend(part_result['errors'] + part_result['skipped'])
            if part_result['applied']:
                logger.info(f"[OK] Installed parts {part_result['applied']} of {found_mod['name']}")

        response = {'success': True}
        if part_errors:
            response['partErrors'] = part_errors
        if offset_skips:
            # Additive field: layers whose offset guard failed and could not
            # be relocated (docs/dev/EXTRAS_AUDIT.md "Offset safety: guard +
            # relocation"). install still reports success=True -- other
            # layers wrote fine -- but the caller can surface which layers
            # silently kept their prior/vanilla bytes instead of the new color.
            response['offsetSkips'] = offset_skips
        return jsonify(response)

    except Exception as e:
        logger.error(f"Install extra error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _restore_vanilla_model(character, extra_type, type_config):
    """restore-vanilla for a model extra: the vanilla model, exactly as the
    game ships it, copied into the project's DAT (vault/extras/models.py)."""
    try:
        files_dir = helpers.get_project_files_dir()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    target_file = type_config['target_file']
    dat_path = find_dat_file(files_dir, target_file)
    if not dat_path or not dat_path.exists():
        return jsonify({'success': False,
                        'error': f'Could not find {target_file} in MEX project'}), 404
    try:
        restore_vanilla_model(dat_path, type_config)
    except ModelToolError as e:
        logger.error(f"[RestoreVanilla] {character}/{extra_type}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 409
    logger.info(f"[OK] Restored the vanilla {type_config.get('name', extra_type)} "
                f"for {character} in {target_file}")
    return jsonify({'success': True, 'restored_components': ['model']})


@extras_bp.route('/api/mex/storage/extras/restore-vanilla', methods=['POST'])
def restore_vanilla_extra():
    """Restore vanilla colors from config.

    Request body:
    {
        "character": "Falco",
        "extraType": "laser"
    }
    """
    restore_details = {'restored_spans': 0, 'failed_spans': [], 'restored_components': []}
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

        # Model extras (a gun) have no colors: the vanilla model is copied
        # back from the vanilla reference of the same file.
        if type_config.get('type') == 'model':
            return _restore_vanilla_model(character, extra_type, type_config)

        vanilla = type_config.get('vanilla', {})
        # texture_region extras restore from the vanilla reference DAT, not
        # from config color values -- an empty vanilla map is expected there.
        if not vanilla and type_config.get('format') != 'texture_region':
            return jsonify({
                'success': False,
                'error': f'No vanilla colors defined for {character}/{extra_type}'
            }), 400

        # Find the .dat file in MEX project
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

        # image_model extras: an installed image effect must come out before
        # (or instead of) restoring colors, otherwise "restore vanilla" would
        # leave the picture on screen. Reverting also puts back the gradient
        # bytes exactly as they were, so the color restore below still runs.
        if sideb_model.supports(type_config):
            try:
                restore_details['restored_spans'] = sideb_model.apply_colors(
                    dat_path, {key: {'color': value} for key, value in vanilla.items()})
                restore_details['restored_components'].append('sideb_model')
                return jsonify({'success': True, **restore_details})
            except sideb_model.SideBModelError as error:
                restore_details['failed_spans'].append({'layer_id': 'sideb_model', 'reason': str(error)})
                return jsonify({'success': False, 'error': str(error), **restore_details}), 409

        if effect_model.supports(type_config):
            try:
                if effect_model.revert_installed(dat_path, type_config):
                    restore_details['restored_components'].append('image_model')
                    logger.info(f"[RestoreVanilla] removed the installed image "
                                f"{extra_type} for {character}")
            except EffectModelError as e:
                logger.error(f"[RestoreVanilla] cannot remove the installed "
                             f"image {extra_type}: {e}")
                restore_details['failed_spans'].append({'layer_id': 'image_model', 'reason': str(e)})
                return jsonify({'success': False, 'error': str(e), **restore_details}), 409

        # texture_recolor: restore vanilla texel bytes from the reference DAT
        # (no 'offsets' dict -- see vault/extras/texture_recolor.py)
        if type_config.get('format') == 'texture_recolor':
            tex_cfg = dict(type_config['texture'])
            tex_cfg['_target_file'] = target_file
            restore_texture_recolor(dat_path, tex_cfg)
            logger.info(f"[OK] Restored vanilla texture_recolor for {character}/{extra_type}")
            return jsonify({'success': True})

        # texture_region: copy the vanilla region bytes back from the
        # vanilla reference DAT (see vault/extras/texture_region.py)
        if type_config.get('format') == 'texture_region':
            van = texture_region.vanilla_region(type_config, target_file)
            if van is None:
                return jsonify({
                    'success': False,
                    'error': ('No vanilla reference available for '
                              f'{target_file} (record a vanilla ISO first)')
                }), 400
            try:
                texture_region.write_region(dat_path, type_config, van)
            except TextureRegionError as e:
                restore_details['failed_spans'].append({'layer_id': extra_type, 'reason': str(e)})
                return jsonify({'success': False, 'error': str(e), **restore_details}), 409
            logger.info(f"[OK] Restored vanilla texture_region for {character}/{extra_type}")
            return jsonify({'success': True})

        # Special handling for shine_gradient format (two-color gradient + flash)
        if type_config.get('format') == 'shine_gradient':
            restore_details['restored_spans'] += helpers.patch_shine_color_slots(
                dat_path, type_config,
                {key: {'color': vanilla[key]} for key in
                 ('primary', 'secondary', 'flash1', 'flash2')})

            # Restore sparkle color to vanilla (CF-multi records)
            sparkle_skips = helpers.restore_extra_color_bytes(
                dat_path, type_config, {'sparkles': type_config['offsets']['sparkles']},
                report=restore_details)
            restore_details['failed_spans'].extend(sparkle_skips)
            if sparkle_skips:
                logger.warning(f"[RestoreVanilla] shine sparkle spans skipped: {sparkle_skips}")

            logger.info(f"[OK] Restored vanilla shine gradient for {character}")
        else:
            # Apply vanilla colors (standard format), with the same
            # guard+relocate safety as install: current bytes are a mod's
            # colors (that's the point of restoring), so the context guard /
            # ptcl identity proves the offsets rather than vanilla-byte match.
            restore_skips = helpers.restore_extra_color_bytes(dat_path, type_config, report=restore_details)
            restore_details['failed_spans'].extend(restore_skips)
            if restore_skips:
                logger.warning(f"[RestoreVanilla] {len(restore_skips)} layer(s) "
                               f"skipped for {character}/{extra_type}")
            logger.info(f"[OK] Restored vanilla colors for {character}/{extra_type}")

        # A unit restores its parts too (flight puff texture, charge flames,
        # fireball aura...), each in its own target file.
        restore_parts(character, extra_type, files_dir, restore_details)

        # Also restore a nested sibling texture extra, if this extra has one
        # (upb -> upb_texture; falcon_punch -> punch_texture).
        sibling = SIBLING_TEXTURE_EXTRAS.get(extra_type)
        if sibling:
            _nested_key, texture_extra_id = sibling
            try:
                texture_config = get_extra_type(character, texture_extra_id)
                if not texture_config:
                    raise ValueError(f'Texture extra {texture_extra_id} is not configured')
                restore_texture_extra(character, texture_extra_id,
                                      texture_config, dat_path)
                restore_details['restored_components'].append(texture_extra_id)
                logger.info(f"[OK] Restored vanilla {texture_extra_id} for {character}")
            except Exception as tex_err:
                logger.error(f"[RestoreVanilla] {texture_extra_id} restore failed: {tex_err}")
                restore_details['failed_spans'].append(
                    {'layer_id': texture_extra_id, 'reason': str(tex_err)})

        if restore_details['failed_spans']:
            return jsonify({
                'success': False,
                'error': f"Restore incomplete: {restore_details['restored_spans']} color spans restored; "
                         f"{len(restore_details['failed_spans'])} spans or components could not be restored.",
                **restore_details,
            }), 409

        return jsonify({
            'success': True, **restore_details,
        })

    except Exception as e:
        logger.error(f"Restore vanilla error: {str(e)}", exc_info=True)
        restore_details['failed_spans'].append({'layer_id': 'restore', 'reason': str(e)})
        return jsonify({
            'success': False,
            'error': f"Restore incomplete after {restore_details['restored_spans']} color spans: {str(e)}",
            **restore_details,
        }), 409
