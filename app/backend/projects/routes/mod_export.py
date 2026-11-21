"""
Mod Export Blueprint - Export costumes and stages as ZIP files.

Handles exporting individual costumes and stage variants for sharing.
"""

import os
import zipfile
import logging
import re
import uuid
from flask import Blueprint, request, jsonify

import file_retry
from core.config import STORAGE_PATH, OUTPUT_PATH
from core.costume_files import is_costume_archive_filename
from core.metadata import load_metadata
from core.stages import ALL_STAGES
from core.path_safety import resolve_under_root, validate_path_segment
from core.temporary_download import send_temporary_zip

logger = logging.getLogger(__name__)

mod_export_bp = Blueprint('mod_export', __name__)

# Every versus stage whose skins live in storage/das/<folder>/ (the six DAS
# stages plus the replace-slot stages; see core/stages.py).
DAS_STAGES = ALL_STAGES

_STADIUM_FORM_RE = re.compile(r'(?:^|/)([^/]+)/GrPs([1-4])\.dat$', re.IGNORECASE)


def _remove_failed_export(path):
    if path is not None:
        try:
            file_retry.retry_locked(path.unlink, missing_ok=True)
        except OSError:
            logger.exception('Could not remove failed mod export %s', path)


def costume_export_members(names):
    """Return shareable costume members, including engine-side G&W colors."""
    return [name for name in names
            if is_costume_archive_filename(name)
            or os.path.basename(name).lower() == 'gaw.json']


def stage_export_members(stage_code, names):
    """Return stage data and any complete per-variant Stadium form bundle."""
    if stage_code != 'GrPs':
        return [name for name in names if name.lower().endswith('.dat')]

    base_members = []
    forms = {}
    for name in names:
        normalized = name.replace('\\', '/')
        match = _STADIUM_FORM_RE.search(normalized)
        if match:
            forms.setdefault(match.group(1).lower(), {})[int(match.group(2))] = name
        elif '/' not in normalized and normalized.lower().endswith(('.dat', '.usd')):
            base_members.append(name)

    selected = list(base_members)
    base_stems = {os.path.splitext(os.path.basename(name))[0].lower()
                  for name in base_members}
    for stem in sorted(base_stems):
        bundle = forms.get(stem, {})
        if set(bundle) == {1, 2, 3, 4}:
            selected.extend(bundle[index] for index in range(1, 5))
    return selected


@mod_export_bp.route('/api/mex/storage/costumes/export', methods=['POST'])
def export_costume():
    """Export a single costume as a ZIP file"""
    export_path = None
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        color_name = data.get('colorName', 'costume')

        logger.info("=== COSTUME EXPORT REQUEST ===")
        logger.info(f"Character: {character}, Skin ID: {skin_id}")

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        csp_path = char_folder / f"{skin_id}_csp.png"
        stock_path = char_folder / f"{skin_id}_stc.png"

        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume not found: {skin_id}'}), 404

        # Check if this is Ice Climbers Popo with paired Nana
        paired_nana_id = None
        metadata = load_metadata(default={})
        if metadata:
            if character in metadata.get('characters', {}):
                for skin in metadata['characters'][character]['skins']:
                    if skin['id'] == skin_id:
                        if skin.get('is_popo') and skin.get('paired_nana_id'):
                            paired_nana_id = skin['paired_nana_id']
                            logger.info(f"Ice Climbers Popo detected, paired Nana: {paired_nana_id}")
                        break

        export_dir = OUTPUT_PATH / "mod_exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        safe_character = "".join(c for c in character if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        safe_color = "".join(c for c in color_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        # Each request owns its archive, even when display names are identical.
        export_filename = f"{safe_character}_{safe_color}_{uuid.uuid4().hex}.zip"
        export_path = export_dir / export_filename

        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as export_zip:
            with zipfile.ZipFile(zip_path, 'r') as source_zip:
                for item in costume_export_members(source_zip.namelist()):
                    dat_data = source_zip.read(item)
                    export_zip.writestr(item, dat_data)
                    logger.info(f"  Added: {item}")

            if csp_path.exists():
                export_zip.write(csp_path, 'csp.png')
                logger.info(f"  Added: csp.png")

            if stock_path.exists():
                export_zip.write(stock_path, 'stc.png')
                logger.info(f"  Added: stc.png")

            if paired_nana_id:
                nana_zip_path = char_folder / f"{paired_nana_id}.zip"
                if nana_zip_path.exists():
                    with zipfile.ZipFile(nana_zip_path, 'r') as nana_zip:
                        for item in costume_export_members(nana_zip.namelist()):
                            nana_dat_data = nana_zip.read(item)
                            export_zip.writestr(item, nana_dat_data)
                            logger.info(f"  Added Nana: {item}")

        logger.info(f"[OK] Costume exported: {export_filename}")
        return jsonify({'success': True, 'filename': export_filename})
    except Exception as e:
        _remove_failed_export(export_path)
        logger.error(f"Costume export error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@mod_export_bp.route('/api/mex/storage/stages/export', methods=['POST'])
def export_stage():
    """Export a single stage variant as a ZIP file"""
    export_path = None
    try:
        data = request.json
        stage_code = data.get('stageCode')
        stage_name = data.get('stageName', 'stage')
        variant_id = data.get('variantId')
        variant_name = data.get('variantName', 'variant')

        logger.info("=== STAGE EXPORT REQUEST ===")
        logger.info(f"Stage Code: {stage_code}, Variant ID: {variant_id}")

        if not stage_code or not variant_id:
            return jsonify({'success': False, 'error': 'Missing stageCode or variantId parameter'}), 400

        if stage_code not in DAS_STAGES:
            return jsonify({'success': False, 'error': f'Unknown stage code: {stage_code}'}), 400

        stage_info = DAS_STAGES[stage_code]
        stage_folder = stage_info['folder']
        storage_stage_path = STORAGE_PATH / 'das' / stage_folder
        stage_zip_path = storage_stage_path / f"{variant_id}.zip"
        screenshot_path = storage_stage_path / f"{variant_id}_screenshot.png"

        if not stage_zip_path.exists():
            return jsonify({'success': False, 'error': f'Stage variant not found in storage: {variant_id}'}), 404

        export_dir = OUTPUT_PATH / "mod_exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        safe_stage = "".join(c for c in stage_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        safe_variant = "".join(c for c in variant_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        export_filename = f"{safe_stage}_{safe_variant}_{uuid.uuid4().hex}.zip"
        export_path = export_dir / export_filename

        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as export_zip:
            with zipfile.ZipFile(stage_zip_path, 'r') as source_zip:
                for item in stage_export_members(stage_code, source_zip.namelist()):
                    stage_data = source_zip.read(item)
                    export_zip.writestr(item, stage_data)
                    logger.info(f"  Added: {item}")

            if screenshot_path.exists():
                export_zip.write(screenshot_path, 'screenshot.png')
                logger.info(f"  Added: screenshot.png")

        logger.info(f"[OK] Stage exported: {export_filename}")
        return jsonify({'success': True, 'filename': export_filename})
    except Exception as e:
        _remove_failed_export(export_path)
        logger.error(f"Stage export error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@mod_export_bp.route('/api/mex/export/mod/<filename>', methods=['GET'])
def download_mod(filename):
    """Download an exported mod file"""
    try:
        export_dir = OUTPUT_PATH / "mod_exports"
        validate_path_segment(filename, field='export filename')
        if not filename.lower().endswith('.zip') or filename.lower() == '.zip':
            return jsonify({'success': False, 'error': 'Invalid export filename'}), 400
        if (export_dir / filename).is_symlink():
            return jsonify({'success': False, 'error': 'Export file not found'}), 404
        file_path = resolve_under_root(export_dir, filename, field='export filename')

        if not file_path.is_file():
            return jsonify({'success': False, 'error': 'Export file not found'}), 404

        # The lookup token isolates concurrent exports; the saved ZIP keeps its
        # readable name. Legacy exports without a token remain downloadable.
        download_name = re.sub(r'_[0-9a-f]{32}(?=\.zip$)', '', filename)
        return send_temporary_zip(file_path, download_name=download_name)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Mod download error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
