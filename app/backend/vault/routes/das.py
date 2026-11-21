"""
DAS Blueprint - Dynamic Alternate Stages endpoints, vault side.

Lists the stage variants (skins) kept in the vault and imports new ones from an
ISO. Installing the DAS framework and installing, renaming and removing
variants in the open project are in projects/routes/das.py, on this same
`das_bp`; the shared naming and archive helpers are projects/install/das.py.
"""

import shutil
import zipfile
import logging
import tempfile
from collections import Counter
from pathlib import Path
from flask import Blueprint, request, jsonify

from vault.importing import das_scan
from vault.importing.stage_previews import (
    SUPPORTED_STAGE_CODES, render_imported_stage_previews)
from core.config import PROJECT_ROOT, STORAGE_PATH
from core.metadata import load_metadata, metadata_transaction
from core.stages import ALL_STAGES
from projects.install.das import (
    DAS_STAGES, find_stage_screenshot, stadium_transformation_members,
)

logger = logging.getLogger(__name__)

das_bp = Blueprint('das', __name__)


@das_bp.route('/api/mex/das/storage/variants', methods=['GET'])
def das_list_storage_variants():
    """List all DAS variants in storage"""
    try:
        stage_code = request.args.get('stage')
        variants = []

        # Load metadata to get proper names
        metadata = load_metadata(default={})

        # Determine which stages to scan. The vault holds skins for EVERY
        # versus stage (storage/das/<folder>/), not just the six DAS stages;
        # the project-side install routes below stay DAS-only.
        stages_to_scan = {stage_code: ALL_STAGES[stage_code]} if stage_code and stage_code in ALL_STAGES else ALL_STAGES

        for code, stage_info in stages_to_scan.items():
            stage_folder = stage_info['folder']
            stage_storage_path = STORAGE_PATH / "das" / stage_folder

            # Get variants from metadata for this stage
            stage_metadata = metadata.get('stages', {}).get(stage_folder, {})
            metadata_variants_list = stage_metadata.get('variants', [])

            if stage_storage_path.exists():
                # Build a lookup of all zip files that exist on disk (sorted:
                # glob order is filesystem-dependent, and disk-only variants
                # are appended in this order — must match storage_stages)
                zip_files = {zip_file.stem: zip_file for zip_file in sorted(stage_storage_path.glob('*.zip'))}

                # First, add variants in metadata order (if they exist on disk)
                for variant_meta in metadata_variants_list:
                    # Folder entries are virtual (no zip on disk) — emit them inline
                    # so the frontend can render the folder organization UI.
                    if variant_meta.get('type') == 'folder':
                        variants.append({
                            'type': 'folder',
                            'stageCode': code,
                            'id': variant_meta['id'],
                            'name': variant_meta.get('name', 'Folder'),
                            'expanded': variant_meta.get('expanded', True)
                        })
                        continue

                    variant_id = variant_meta['id']
                    zip_file = zip_files.get(variant_id)

                    # Only add if the zip file actually exists
                    if zip_file:
                        variant_name = variant_meta.get('name', variant_id)

                        # Check for screenshot in storage
                        has_screenshot, screenshot_path, screenshot_ext = find_stage_screenshot(stage_storage_path, variant_id)

                        # Only Stadium can carry per-transformation skins. Read
                        # it off the zip rather than metadata so variants that
                        # predate the field still report correctly (the central
                        # directory is cheap -- no member is decompressed).
                        transformation_skins = 0
                        if code == 'GrPs':
                            try:
                                with zipfile.ZipFile(zip_file) as probe:
                                    transformation_skins = len(
                                        stadium_transformation_members(
                                            probe.namelist()))
                            except (zipfile.BadZipFile, OSError, ValueError):
                                transformation_skins = 0

                        variants.append({
                            'stageCode': code,
                            'stageName': stage_info['name'],
                            'id': variant_id,
                            'name': variant_name,
                            'folder_id': variant_meta.get('folder_id'),
                            'zipPath': str(zip_file.relative_to(PROJECT_ROOT)),
                            'transformationSkins': transformation_skins,
                            'canRender': code in SUPPORTED_STAGE_CODES,
                            'hasScreenshot': has_screenshot,
                            'screenshotUrl': f"/storage/das/{stage_info['folder']}/{variant_id}_screenshot{screenshot_ext}" if has_screenshot else None,
                            'slippi_safe': variant_meta.get('slippi_safe'),
                            'slippi_tested': variant_meta.get('slippi_tested', False),
                            'slippi_test_date': variant_meta.get('slippi_test_date'),
                            'date_added': variant_meta.get('date_added')
                        })

                        # Remove from zip_files so we don't add it again
                        del zip_files[variant_id]

                # Then, add any remaining zip files that aren't in metadata
                for variant_id, zip_file in zip_files.items():
                    has_screenshot, screenshot_path, screenshot_ext = find_stage_screenshot(stage_storage_path, variant_id)

                    variants.append({
                        'stageCode': code,
                        'stageName': stage_info['name'],
                        'id': variant_id,
                        'name': variant_id,
                        'zipPath': str(zip_file.relative_to(PROJECT_ROOT)),
                        'canRender': code in SUPPORTED_STAGE_CODES,
                        'hasScreenshot': has_screenshot,
                        'screenshotUrl': f"/storage/das/{stage_info['folder']}/{variant_id}_screenshot{screenshot_ext}" if has_screenshot else None,
                        'slippi_safe': None,
                        'slippi_tested': False,
                        'slippi_test_date': None,
                        'date_added': None
                    })

        return jsonify({
            'success': True,
            'variants': variants
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/scan-iso', methods=['POST'])
def das_scan_iso():
    """Extract an ISO's stage files and import any NEW DAS alternate stages
    into the vault. Handles both the m-ex DAS folder layout and the 20XX flat
    Gr<code>.<X>at layout (see das_scan.detect_das_variants)."""
    try:
        data = request.json or {}
        iso_path = (data.get('isoPath') or '').strip()
        if not iso_path:
            return jsonify({'success': False, 'error': 'Missing isoPath parameter'}), 400

        iso_file = Path(iso_path)
        if not iso_file.exists():
            return jsonify({'success': False, 'error': f'ISO not found: {iso_path}'}), 404
        if iso_file.suffix.lower() not in ('.iso', '.gcm'):
            return jsonify({'success': False, 'error': 'File must be an .iso or .gcm'}), 400
        if '.nkit' in iso_file.name.lower():
            logger.info(f"Skipping NKit ISO for DAS scan: {iso_path}")
            return jsonify({'success': True, 'imported': [], 'importedCount': 0,
                            'skipped': [iso_file.name], 'message': 'Skipped NKit ISO (not supported)'})

        from shared.vanilla_extract.vanilla_refs import extract_iso_files

        das_root = STORAGE_PATH / 'das'
        temp_dir = tempfile.mkdtemp(prefix='nucleus_das_scan_')
        try:
            # Native FST extraction of just the stage files (Gr*) -- far lighter
            # than a full rip, and works on every platform.
            extract_dir = Path(temp_dir) / 'fst'
            try:
                n = extract_iso_files(iso_file, extract_dir, name_glob='gr*', include_matching_dirs=True)
            except Exception as e:
                n = 0
                logger.warning(f"native stage extract failed: {e}")
            if n == 0:
                return jsonify({'success': False,
                                'error': 'Could not read stage files from this ISO.'}), 500

            # The FST lands under a `files` dir; find the one with Gr files.
            files_dir = next(
                (d for d in extract_dir.rglob('files')
                 if d.is_dir() and any(d.glob('Gr*'))),
                None,
            )
            if files_dir is None:
                return jsonify({'success': True, 'imported': [], 'importedCount': 0,
                                'message': 'No stage files found in ISO'})

            skip = das_scan.vault_variant_md5s(das_root)
            variants = das_scan.detect_das_variants(files_dir)

            # Locked read-modify-write via the DAL transaction so this can't race
            # a concurrent import and clobber custom_characters etc.
            imported = []
            skipped = []
            preview_jobs = []
            with metadata_transaction(default={}) as metadata:
                stages_meta = metadata.setdefault('stages', {})

                for v in variants:
                    stage_meta = stages_meta.setdefault(v.folder, {})
                    vlist = stage_meta.setdefault('variants', [])
                    if v.md5 in skip:
                        # Older ISO imports have the DAT but no preview. A
                        # rescan fills that gap without importing another copy.
                        existing = next((e for e in vlist if isinstance(e, dict) and e.get('md5') == v.md5), None)
                        if existing:
                            has_image, _, ext = find_stage_screenshot(das_root / v.folder, existing['id'])
                            skipped.append({'stageCode': v.stage_code, 'stageName': v.stage_name,
                                            'name': existing['name'], 'id': existing['id'],
                                            'screenshotUrl': f"/storage/das/{v.folder}/{existing['id']}_screenshot{ext}" if has_image else None})
                            if not has_image:
                                preview_jobs.append((v, existing))
                        continue
                    taken = {e.get('id') for e in vlist if isinstance(e, dict)}
                    entry = das_scan.import_variant_to_vault(v, das_root, taken_ids=taken)
                    vlist.append(entry)
                    preview_jobs.append((v, entry))
                    imported.append({'stageCode': v.stage_code, 'stageName': v.stage_name,
                                     'name': entry['name'], 'id': entry['id'], 'source': v.source})

            previews = render_imported_stage_previews(preview_jobs, das_root)
            if previews:
                with metadata_transaction(default={}) as metadata:
                    for variant, entry in preview_jobs:
                        if (variant.folder, entry['id']) not in previews:
                            continue
                        for saved in metadata.get('stages', {}).get(variant.folder, {}).get('variants', []):
                            if saved.get('id') == entry['id']:
                                saved['has_screenshot'] = True
                                saved['screenshot_filename'] = f"{entry['id']}_screenshot.png"
                                break
                for result in imported + skipped:
                    folder = DAS_STAGES[result['stageCode']]['folder']
                    url = previews.get((folder, result['id']))
                    if url:
                        result['screenshotUrl'] = url

            by_stage = dict(Counter(i['stageName'] for i in imported))
            logger.info(f"[OK] DAS ISO scan: imported {len(imported)} variants {by_stage}")
            return jsonify({'success': True, 'imported': imported, 'skipped': skipped,
                            'importedCount': len(imported), 'byStage': by_stage})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"DAS ISO scan error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# The project half of this blueprint (DAS framework status/install, the
# variants installed in the open project: import, rename, remove, Stadium
# freeze, restore vanilla) lives in projects/routes/das.py and adds its routes
# to das_bp. Importing it here makes the blueprint complete before anything
# registers it: Flask refuses routes added after registration.
from projects.routes import das as _project_routes  # noqa: E402,F401
