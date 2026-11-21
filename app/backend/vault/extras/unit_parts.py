"""
Unit parts: a move is ONE extra whose mod carries nested part recipes.

    upb mod
      modifications:
        tip / body / trail / ...        the primary's own layers
        fire: {color}                   legacy nested texture (upb_texture)
        parts:
          upb_charge_fire: {color1: {color}}          flight puff texture
          charge_flames:   {flame_c1: {color}, ...}   Fox's rising charge flames

Which types are parts of which unit is `core.extra_types.UNIT_PARTS`. This
module applies / restores / migrates those nested parts using the SAME
guarded write paths the part types use on their own (hex patches with
offset safety, texture recolors), so a part inside a unit and a part on its
own patch identical bytes. Nothing here knows about Flask.
"""

import logging
import shutil
from datetime import datetime

import file_retry
from core.extra_types import PART_OWNER
from core.extra_lookup import get_extra_type, get_unit_parts

from vault.extras.helpers import find_dat_file, make_write_safety, restore_extra_color_bytes
from vault.extras.offsets import get_dynamic_offsets
from vault.extras.color_patch import apply_hex_patches
from .texture_recolor import apply_texture_recolor, restore_texture_recolor

logger = logging.getLogger(__name__)


def own_modifications(modifications):
    """The primary's own layers (everything except the nested parts)."""
    return {k: v for k, v in (modifications or {}).items() if k != 'parts'}


def part_modifications(modifications):
    """{part_id: {layer: {color}}} nested in a unit mod (empty when none)."""
    parts = (modifications or {}).get('parts') or {}
    return {k: v for k, v in parts.items() if v}


def apply_parts(character, modifications, files_dir):
    """Write every nested part into its target file in the project.

    Each part patches an isolated copy of its target and swaps it in, exactly
    like install_extra does for the primary. Returns
    {'applied': [...], 'skipped': [...], 'errors': [...], 'offset_skips': [...]}.
    A failing part never aborts the others.
    """
    out = {'applied': [], 'skipped': [], 'errors': [], 'offset_skips': []}
    for part_id, part_mods in part_modifications(modifications).items():
        cfg = get_extra_type(character, part_id)
        if not cfg:
            out['skipped'].append(f'{part_id}: not defined for {character}')
            continue
        dat_path = find_dat_file(files_dir, cfg['target_file'])
        if not dat_path or not dat_path.exists():
            out['skipped'].append(f"{part_id}: {cfg['target_file']} not in project")
            continue
        try:
            out['offset_skips'].extend(_apply_one_part(part_id, cfg, part_mods, dat_path))
            out['applied'].append(part_id)
            logger.info(f"[OK] Applied part {part_id} to {cfg['target_file']}")
        except Exception as e:
            logger.error(f'[Parts] {part_id} failed: {e}', exc_info=True)
            out['errors'].append(f'{part_id}: {e}')
    return out


def _apply_one_part(part_id, cfg, part_mods, dat_path):
    patch_path = dat_path.with_name(dat_path.name + '.patching')
    shutil.copy2(dat_path, patch_path)
    try:
        skips = []
        if cfg.get('format') == 'texture_recolor':
            prop_id = cfg['properties'][0]['id']
            color = (part_mods.get(prop_id) or {}).get('color')
            if not color:
                raise ValueError(f'no {prop_id} color saved')
            tex_cfg = dict(cfg['texture'])
            tex_cfg['_target_file'] = cfg['target_file']
            apply_texture_recolor(patch_path, tex_cfg, color,
                                  vanilla_hue=cfg.get('vanilla_dominant_hue'))
        else:
            offsets = get_dynamic_offsets(patch_path, part_id, cfg.get('offsets', {}))
            safety = make_write_safety(patch_path, part_id, cfg['target_file'], cfg.get('vanilla'))
            skips = apply_hex_patches(patch_path, offsets, part_mods, safety=safety) or []
        file_retry.replace(patch_path, dat_path)
        return skips
    finally:
        if patch_path.exists():
            patch_path.unlink()


def restore_parts(character, extra_type, files_dir, report):
    """Restore every part of a unit to vanilla (the unit's Restore Vanilla).
    Records what happened in `report` (restored_components / failed_spans)."""
    for part_id, cfg in get_unit_parts(character, extra_type):
        dat_path = find_dat_file(files_dir, cfg['target_file'])
        if not dat_path or not dat_path.exists():
            # A part whose file the project simply doesn't have (a build
            # without the common effect bank) has nothing to restore; that is
            # not a failed restore of the move.
            logger.info(f"[RestoreVanilla] part {part_id}: {cfg['target_file']} not in project, nothing to restore")
            report.setdefault('skipped_components', []).append(part_id)
            continue
        try:
            if cfg.get('format') == 'texture_recolor':
                tex_cfg = dict(cfg['texture'])
                tex_cfg['_target_file'] = cfg['target_file']
                restore_texture_recolor(dat_path, tex_cfg)
            else:
                skips = restore_extra_color_bytes(dat_path, cfg, report=report) or []
                report['failed_spans'].extend(skips)
            report['restored_components'].append(part_id)
            logger.info(f'[OK] Restored vanilla part {part_id} for {character}')
        except Exception as e:
            logger.error(f'[RestoreVanilla] part {part_id} failed: {e}')
            report['failed_spans'].append({'layer_id': part_id, 'reason': str(e)})


def fold_part_mods_into_units(metadata):
    """Migrate mods saved under a part type on its own (pre-unit vault) into
    unit mods that carry just that part. Mutates `metadata`; returns True
    when something moved (caller persists)."""
    changed = False
    for storage_char, char_data in (metadata.get('characters') or {}).items():
        extras = (char_data or {}).get('extras') or {}
        for part_id, primary in PART_OWNER.items():
            legacy = extras.get(part_id)
            if not legacy:
                continue
            unit_list = extras.setdefault(primary, [])
            for mod in legacy:
                moved = {
                    'id': mod.get('id') or f'{part_id}_migrated',
                    'name': mod.get('name') or part_id,
                    'date_added': mod.get('date_added') or datetime.now().isoformat(),
                    'source': mod.get('source', 'created'),
                    'migrated_from': part_id,
                    'modifications': {'parts': {part_id: own_modifications(mod.get('modifications'))}},
                }
                for key in ('active', 'model_file', 'file_hash', 'screenshot'):
                    if key in mod:
                        moved[key] = mod[key]
                unit_list.append(moved)
                logger.info(f"[Parts] Folded {storage_char}/{part_id} mod '{moved['name']}' into {primary}")
            del extras[part_id]
            changed = True
    return changed


def attach_part(metadata, storage_char, primary, mod_id, part_id, part_mods):
    """Set one nested part recipe on an existing unit mod. Returns the mod or
    None when it does not exist."""
    mods = ((metadata.get('characters') or {}).get(storage_char) or {}).get('extras', {}).get(primary, [])
    mod = next((m for m in mods if m.get('id') == mod_id), None)
    if mod is None:
        return None
    mod.setdefault('modifications', {}).setdefault('parts', {})[part_id] = part_mods
    return mod
