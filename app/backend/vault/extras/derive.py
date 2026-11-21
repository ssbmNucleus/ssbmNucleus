"""
Remaking an extra from a modded DAT: read every color layer the extra type
defines and turn it into the modifications a stored extra carries.
"""

import os
import logging
from pathlib import Path
from vault.extras.offsets import get_dynamic_offsets
from vault.extras.color_read import (read_shine_gradient_colors, read_shine_sparkle_color,
    read_current_colors)

logger = logging.getLogger(__name__)


def derive_modifications_from_dat(dat_path, extra_type_id, type_config):
    """Read a modded effect DAT's colors into a create-shaped modifications dict.

    Website effect zips carry a full modded DAT, not the {layer: {color}}
    dict that install/apply patch from -- so an imported color mod used to
    sit in metadata with no 'modifications' and install as a silent no-op.
    This reads the mod DAT with the same offset system get_current uses
    (dynamic detection runs against the MOD file, so shifted layouts
    self-locate) and remakes the mod as if it had been created in the app.

    Args:
        dat_path: Path to the imported/stored mod DAT
        extra_type_id: The extra type ID (e.g. 'laser', 'sideb', 'shine')
        type_config: The extra type config from get_extra_type()

    Returns:
        {layer_id: {'color': 'HEX'}} dict, empty when the type has no
        readable colors (model/texture/texture_region types) or reading
        fails. Layer color strings are in each layer's native byte format
        (RGBY 2-byte, RGB 3-byte, 42_48 12-byte...), exactly as
        read_current_colors reports and apply_hex_patches expects.

        OR {'image': {...}} when the mod turns out to be an IMAGE effect
        rather than a color one (image_model extras only -- see below and
        vault/routes/extras/effect_model.py). The two shapes never mix: an
        image effect has no color operands to read.
    """
    fmt = type_config.get('format')
    if type_config.get('type') in ('model', 'texture') or fmt == 'texture_region':
        return {}

    # A replacement Phantasm mesh can still contain the old color marker.
    # Detect its structure before reducing it to a three-color recipe.
    from . import sideb_model
    if sideb_model.supports(type_config):
        try:
            model_recipe = sideb_model.replacement_recipe(Path(dat_path).read_bytes())
            if model_recipe:
                return model_recipe
            return {key: {'color': value} for key, value in
                    sideb_model.colors(Path(dat_path).read_bytes()).items()}
        except (OSError, ValueError):
            # Keep this reader's never-raise contract. Public DAT import also
            # validates the archive explicitly before storing anything.
            pass

    # An image-based effect (NERV/Honeycomb-style image shines) has no colors
    # at all -- reading the config offsets out of its rebuilt file returns
    # garbage. Mark it as an image instead of returning {} (which install
    # reports as "no color data Nucleus can apply"), so install/apply route it
    # through vault/routes/extras/effect_model.py. This is why the return type is
    # a UNION: {layer: {'color': hex}} for color mods, {'image': {...}} for
    # image mods. Callers store it verbatim and both consumers branch on the
    # key they own.
    from . import effect_model
    if effect_model.supports(type_config):
        try:
            kind, detail = effect_model.classify_model(
                Path(dat_path).read_bytes(), type_config)
            if kind == effect_model.CLASSIFY_IMAGE:
                logger.info(f"[Derive] {extra_type_id} in {dat_path} is an "
                            f"image effect ({detail['width']}x"
                            f"{detail['height']} fmt {detail['gx_format']})")
                return {'image': {'width': detail['width'],
                                  'height': detail['height'],
                                  'gx_format': detail['gx_format'],
                                  'imported_from': 'dat'}}
            if kind == effect_model.CLASSIFY_MODEL:
                logger.warning(
                    f"[Derive] {dat_path} replaces the {extra_type_id} "
                    f"GEOMETRY ({detail['dobjs']} meshes, {detail['tobjs']} "
                    f"textures), which is neither a color nor an image mod "
                    f"-- not deriving anything")
                return {}
        except Exception as e:
            # Same never-raise contract as the color path below: an
            # unreadable/foreign file just means "not an image effect", and
            # the color reader gets its turn to fail honestly.
            logger.debug(f"[Derive] {extra_type_id} image probe skipped: {e}")

    try:
        if fmt == 'texture_recolor':
            from .texture_recolor import read_current_dominant_color
            tex_cfg = dict(type_config['texture'])
            tex_cfg['_target_file'] = type_config['target_file']
            prop_id = type_config['properties'][0]['id']
            color = read_current_dominant_color(dat_path, tex_cfg)
            return {prop_id: {'color': color}} if color else {}

        config_offsets = type_config.get('offsets') or {}

        # Hardcoded config offsets assume the vanilla file layout. Image/
        # texture mods (e.g. NERV/Honeycomb image shines) are REBUILT DATs
        # -- different size, moved matrices -- where a raw offset read
        # returns garbage colors, so only trust hardcoded positions when
        # the mod DAT is vanilla-sized (unknown when no ISO is recorded).
        vanilla_sized = None
        try:
            from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
            ref = ensure_vanilla_ref(type_config['target_file'])
            if ref:
                vanilla_sized = (os.path.getsize(dat_path)
                                 == os.path.getsize(ref))
        except Exception:
            pass

        detectable = extra_type_id in ('laser', 'sideb', 'upb', 'shine',
                                       'laser_ring')
        if detectable:
            # fallback=None so a detection failure is visible instead of
            # silently reading vanilla-layout offsets from a rebuilt file
            detected = get_dynamic_offsets(dat_path, extra_type_id, None)
            if not detected:
                logger.warning(f"[Derive] {extra_type_id} layout not found "
                               f"in {dat_path} (rebuilt/texture-based mod?)"
                               f" -- not deriving colors")
                return {}
            offsets = ({**config_offsets, **detected}
                       if vanilla_sized is not False else detected)
        else:
            if vanilla_sized is False:
                logger.warning(f"[Derive] {dat_path} is not vanilla-sized "
                               f"and {extra_type_id} has no dynamic "
                               f"detection -- not deriving colors")
                return {}
            offsets = config_offsets
        if not offsets:
            return {}

        if fmt == 'shine_gradient':
            grad = read_shine_gradient_colors(dat_path, offsets.get('hex', {}))
            mods = {
                'primary': {'color': grad['primary']},
                'secondary': {'color': grad['secondary']},
            }
            # sparkles records are marker-verified (CF check) so the config
            # offsets are safe to try even on a detected-only offsets dict
            sparkles_offset = (offsets.get('sparkles')
                               or config_offsets.get('sparkles', {}))
            if sparkles_offset:
                # default=None: a failed read must not become a white tint
                spark = read_shine_sparkle_color(dat_path, sparkles_offset,
                                                 default=None)
                if spark:
                    mods['sparkles'] = {'color': spark}
            return mods

        colors = read_current_colors(dat_path, offsets)
        return {layer: {'color': color}
                for layer, color in colors.items() if color}
    except Exception as e:
        logger.warning(f"[Derive] Could not derive {extra_type_id} "
                       f"modifications from {dat_path}: {e}")
        return {}
