"""
Stage mod import - vault storage under storage/das/ with screenshot previews.
"""

import os
import zipfile
import logging
from pathlib import Path
from datetime import datetime

from core.config import STORAGE_PATH
from core.metadata import load_metadata, save_metadata

from .helpers import sanitize_filename, compute_dat_hash

logger = logging.getLogger(__name__)


def import_stage_mod(zip_path: str, stage_info: dict, original_filename: str, custom_name: str = None) -> dict:
    """Import a stage mod to storage"""
    try:
        # Load metadata
        metadata = load_metadata(default={'characters': {}, 'stages': {}})

        # Ensure 'stages' section exists
        if 'stages' not in metadata:
            metadata['stages'] = {}

        stage_folder_name = stage_info['folder']
        stage_name = stage_info['stage_name']

        # Create stage folder in storage/das/
        das_folder = STORAGE_PATH / 'das' / stage_folder_name
        das_folder.mkdir(parents=True, exist_ok=True)

        # Generate unique ID for this variant
        stage_data = metadata.get('stages', {}).get(stage_folder_name, {'variants': []})
        existing_ids = [v['id'] for v in stage_data.get('variants', [])]

        # Generate sequential ID based on custom_name or original filename
        if custom_name:
            # Sanitize and limit stage names to 10 characters to prevent crashes
            base_name = sanitize_filename(custom_name)[:10].lower().replace(' ', '-')
        else:
            base_name = sanitize_filename(Path(original_filename).stem)[:10].lower().replace(' ', '-')

        variant_id = base_name
        counter = 1
        while variant_id in existing_ids:
            variant_id = f"{base_name}-{counter:03d}"
            counter += 1

        # Final paths
        final_zip = das_folder / f"{variant_id}.zip"

        # Create a new ZIP with only this stage's files
        transformation_count = 0
        with zipfile.ZipFile(zip_path, 'r') as source_zf:
            with zipfile.ZipFile(final_zip, 'w', zipfile.ZIP_DEFLATED) as dest_zf:
                # Add the specific stage DAT file
                stage_file_data = source_zf.read(stage_info['stage_file'])
                stage_file_basename = os.path.basename(stage_info['stage_file'])
                dest_zf.writestr(stage_file_basename, stage_file_data)
                logger.info(f"[OK] Added stage file to ZIP: {stage_file_basename}")

                # Pokemon Stadium skins may ship a per-transformation sidecar
                # set (GrPs1-4). The stage detector never reports those -- it
                # requires .usd for GrPs -- so without this they were silently
                # dropped and only the normal form survived into the vault.
                # Imported lazily, as it was from the DAS routes module.
                from projects.install.das import stadium_transformation_members
                try:
                    members = stadium_transformation_members(source_zf.namelist())
                except ValueError as err:
                    logger.warning(f"Stadium transformation set rejected: {err}")
                    members = {}
                if members and len(members) != 4:
                    logger.warning(
                        f"Ignoring partial Stadium transformation set "
                        f"({sorted(members)}); the loader needs all four")
                    members = {}
                if members:
                    stem = os.path.splitext(stage_file_basename)[0]
                    for index in sorted(members):
                        dest_zf.writestr(f"{stem}/GrPs{index}.dat",
                                         source_zf.read(members[index]))
                    transformation_count = len(members)
                    logger.info(f"[OK] Added {transformation_count} Stadium "
                                f"transformation skins under {stem}/")

                # Add screenshot to ZIP if available
                if stage_info['screenshot']:
                    screenshot_data = source_zf.read(stage_info['screenshot'])
                    screenshot_basename = os.path.basename(stage_info['screenshot'])
                    dest_zf.writestr(screenshot_basename, screenshot_data)
                    logger.info(f"[OK] Added screenshot to ZIP: {screenshot_basename}")

        # Extract screenshot to storage folder for preview
        has_screenshot = False
        if stage_info['screenshot']:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                screenshot_data = zf.read(stage_info['screenshot'])
                screenshot_ext = os.path.splitext(stage_info['screenshot'])[1]

                # Save to storage folder
                screenshot_path = das_folder / f"{variant_id}_screenshot{screenshot_ext}"
                screenshot_path.write_bytes(screenshot_data)

                has_screenshot = True
                logger.info(f"[OK] Saved screenshot preview: {screenshot_path}")

        # Update metadata
        if stage_folder_name not in metadata['stages']:
            metadata['stages'][stage_folder_name] = {'variants': []}

        # Use variant_id as display name (it's already limited to 10 chars and uses custom_name if provided)
        display_name = variant_id

        metadata['stages'][stage_folder_name]['variants'].append({
            'id': variant_id,
            'name': display_name,
            'filename': f"{variant_id}.zip",
            'has_screenshot': has_screenshot,
            'dat_hash': compute_dat_hash(stage_file_data),
            'screenshot_filename': f"{variant_id}_screenshot{screenshot_ext}" if has_screenshot else None,
            'transformation_skins': transformation_count or None,
            'date_added': datetime.now().isoformat()
            # No default slippi status - will show as "Unknown" until manually set
        })

        # Save metadata
        save_metadata(metadata)

        logger.info(f"[OK] Saved stage mod: {final_zip}")

        message = f"Imported {stage_name} stage variant"
        if transformation_count:
            message += f" with {transformation_count} transformation skins"
        return {
            'success': True,
            'type': 'stage',
            'stage': stage_name,
            'variant_id': variant_id,
            'transformation_skins': transformation_count,
            'message': message
        }

    except Exception as e:
        logger.error(f"Stage import error: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
