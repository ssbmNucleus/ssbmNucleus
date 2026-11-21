"""
Storage Stages Blueprint - Storage vault stage operations.

Handles deleting, renaming, reordering, screenshot updates, bulk preview
rendering, and Slippi status for stored stage variants.
"""

import re
import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file

import file_retry
from core.config import STORAGE_PATH
from core.metadata import load_metadata, save_metadata, metadata_write_transaction
from core.stages import ALL_STAGES
from core import jobs
from shared.rendering.job_previews import (clean_previews, prepare_previews,
    preview_file, delete_previews)
from vault.importing.stage_previews import (
    SUPPORTED_STAGE_CODES, render_vault_variants)

logger = logging.getLogger(__name__)

storage_stages_bp = Blueprint('storage_stages', __name__)

# One bulk render at a time: the renderer pool already saturates the GPU, and
# two batches would only fight over it.
RENDER_KIND = 'stage_render'
jobs.register_kind(RENDER_KIND, label='Stage render', cleanup=clean_previews)


def sanitize_filename(name):
    """Sanitize filename by removing/replacing invalid characters."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def find_folder_in_variants(variants, folder_id):
    """Find a folder by ID in a stage's variants list."""
    for i, item in enumerate(variants):
        if item.get('type') == 'folder' and item.get('id') == folder_id:
            return item, i
    return None, -1


def display_ordered_stage_variants(stage_data, stage_folder):
    """Rebuild a stage's variant list in the SAME order the DAS variants endpoint
    shows it, so reorder fromIndex/toIndex (which the frontend computes against
    that displayed list) line up with what we mutate here.

    Order mirrors das_list_storage_variants: folder entries + metadata variants
    that exist on disk, in metadata order, followed by any on-disk zips that have
    no metadata entry yet ("disk-only" variants, appended at the end). Returns
    (display, hidden) where `hidden` are metadata variants whose zip is missing
    (not shown by the endpoint) so the caller can keep them instead of dropping
    them. Disk-only entries come back as fresh {'id','name'} dicts; persisting
    them after a move promotes them to real metadata variants so the order sticks.
    """
    variants = stage_data.get('variants', [])
    storage_path = STORAGE_PATH / "das" / stage_folder
    if not storage_path.exists():
        return list(variants), []
    # sorted: glob order is filesystem-dependent (inode order on ext4), and the
    # appended disk-only entries must match das_list_storage_variants' order
    zip_files = {p.stem: p for p in sorted(storage_path.glob('*.zip'))}
    display, hidden, consumed = [], [], set()
    for item in variants:
        if item.get('type') == 'folder':
            display.append(item)
        elif item.get('id') in zip_files:
            display.append(item)
            consumed.add(item.get('id'))
        else:
            hidden.append(item)  # metadata variant with no zip on disk → not shown
    for zid in zip_files:
        if zid not in consumed:
            display.append({'id': zid, 'name': zid})  # disk-only → synth entry
    return display, hidden


@storage_stages_bp.route('/api/mex/storage/stages/delete', methods=['POST'])
def delete_storage_stage():
    """Delete stage variant from storage"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or variantId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])
        variant_to_delete = None
        variant_index = None

        for idx, variant in enumerate(variants):
            if variant['id'] == variant_id:
                variant_to_delete = variant
                variant_index = idx
                break

        if not variant_to_delete:
            return jsonify({'success': False, 'error': f'Variant {variant_id} not found in {stage_folder}'}), 404

        das_folder = STORAGE_PATH / 'das' / stage_folder
        # ISO-scan-imported variants store no 'filename' key; the zip follows the
        # <id>.zip convention, so fall back to that instead of KeyError'ing.
        zip_name = variant_to_delete.get('filename') or f"{variant_id}.zip"
        zip_file = das_folder / zip_name

        deleted_files = []
        if zip_file.exists():
            zip_file.unlink()
            deleted_files.append(str(zip_file))
        # screenshots may be saved with any image extension
        for shot in das_folder.glob(f"{variant_id}_screenshot.*"):
            shot.unlink()
            deleted_files.append(str(shot))

        variants.pop(variant_index)

        save_metadata(metadata)

        logger.info(f"[OK] Deleted stage variant {variant_id} from {stage_folder}")
        return jsonify({'success': True, 'message': f'Successfully deleted {variant_id}', 'deleted_files': deleted_files})
    except Exception as e:
        logger.error(f"Delete stage variant error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stages/rename', methods=['POST'])
@metadata_write_transaction
def rename_storage_stage():
    """Rename stage variant (update name field)"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')
        new_name = data.get('newName')

        if not stage_folder or not variant_id or not new_name:
            return jsonify({'success': False, 'error': 'Missing stageFolder, variantId, or newName parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])

        sanitized_new_name = sanitize_filename(new_name).lower()
        for variant in variants:
            if variant['id'] != variant_id:
                existing_name = sanitize_filename(variant.get('name', '')).lower()
                if existing_name == sanitized_new_name:
                    return jsonify({'success': False, 'error': f"A variant named '{variant['name']}' already exists in this stage"}), 400

        variant_found = False
        for variant in variants:
            if variant['id'] == variant_id:
                variant['name'] = new_name
                variant_found = True
                break

        if not variant_found:
            return jsonify({'success': False, 'error': f'Variant {variant_id} not found in {stage_folder}'}), 404

        save_metadata(metadata)

        logger.info(f"[OK] Renamed stage variant {variant_id} to '{new_name}'")
        return jsonify({'success': True, 'message': f'Successfully renamed to {new_name}'})
    except Exception as e:
        logger.error(f"Rename stage variant error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stages/update-screenshot', methods=['POST'])
def update_stage_screenshot():
    """Update screenshot for a stage variant"""
    try:
        stage_folder = request.form.get('stageFolder')
        variant_id = request.form.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or variantId parameter'}), 400

        if 'screenshot' not in request.files:
            return jsonify({'success': False, 'error': 'No screenshot file provided'}), 400

        screenshot_file = request.files['screenshot']
        if screenshot_file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        screenshot_data = screenshot_file.read()

        das_folder = STORAGE_PATH / 'das' / stage_folder
        das_folder.mkdir(parents=True, exist_ok=True)
        # Remove any existing screenshot of ANY extension first, so a stale .jpg
        # can't shadow the new .png (the listing serves whichever file it finds).
        for old in das_folder.glob(f"{variant_id}_screenshot.*"):
            try:
                old.unlink()
            except OSError:
                pass
        storage_screenshot_path = das_folder / f"{variant_id}_screenshot.png"
        file_retry.retry_locked(storage_screenshot_path.write_bytes, screenshot_data)

        metadata = load_metadata()
        if metadata is not None:
            if stage_folder in metadata.get('stages', {}):
                stage_data = metadata['stages'][stage_folder]
                variants = stage_data.get('variants', [])

                for variant in variants:
                    if variant['id'] == variant_id:
                        variant['has_screenshot'] = True
                        # keep metadata's recorded filename in sync (now always .png)
                        variant['screenshot_filename'] = f"{variant_id}_screenshot.png"
                        break

                save_metadata(metadata)

        logger.info(f"[OK] Updated screenshot for {stage_folder}/{variant_id}")
        return jsonify({'success': True, 'message': 'Screenshot updated successfully', 'screenshotUrl': f"/storage/das/{stage_folder}/{variant_id}_screenshot.png"})
    except Exception as e:
        logger.error(f"Update screenshot error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stages/set-slippi', methods=['POST'])
def set_stage_slippi():
    """Manually set slippi safety status for a stage variant.

    `slippiSafe`: true / false, or an explicit null to clear the status back
    to "unknown" (stages can't be auto-tested, so unknown is a real state)."""
    try:
        data = request.json or {}
        stage_name = data.get('stageName')
        variant_id = data.get('variantId')
        slippi_safe = data.get('slippiSafe')

        if not stage_name or not variant_id or 'slippiSafe' not in data:
            return jsonify({'success': False, 'error': 'Missing stageName, variantId, or slippiSafe parameter'}), 400
        if slippi_safe is not None and not isinstance(slippi_safe, bool):
            return jsonify({'success': False, 'error': 'slippiSafe must be true, false, or null'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_name not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage {stage_name} not found in metadata'}), 404

        variant_found = False
        for variant in metadata['stages'][stage_name].get('variants', []):
            if variant['id'] == variant_id:
                if slippi_safe is None:
                    # back to unknown: no verdict, no override
                    variant['slippi_safe'] = None
                    variant['slippi_manual_override'] = False
                    variant.pop('slippi_test_date', None)
                else:
                    variant['slippi_safe'] = slippi_safe
                    variant['slippi_manual_override'] = True
                    variant['slippi_test_date'] = datetime.now().isoformat()
                variant_found = True
                break

        if not variant_found:
            return jsonify({'success': False, 'error': f'Variant {variant_id} not found for {stage_name}'}), 404

        save_metadata(metadata)

        logger.info(f"[OK] Manually set slippi status for {stage_name} - {variant_id}: {slippi_safe}")
        label = ('Unknown' if slippi_safe is None
                 else 'Slippi Safe' if slippi_safe else 'Not Slippi Safe')
        return jsonify({
            'success': True,
            'slippi_safe': slippi_safe,
            'message': f"Manually set to {label}"
        })
    except Exception as e:
        logger.error(f"Set stage slippi error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stages/reorder', methods=['POST'])
@metadata_write_transaction
def reorder_stages():
    """Reorder stage variants in storage"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        if stage_folder is None or from_index is None or to_index is None:
            return jsonify({'success': False, 'error': 'Missing stageFolder, fromIndex, or toIndex parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        stage_data = metadata['stages'][stage_folder]

        # Reorder against the SAME ordered view the frontend sees (metadata
        # variants present on disk + disk-only zips appended), not the raw
        # metadata list. Otherwise dragging — or dropping onto — a disk-only
        # variant sends an index past the metadata list and 400s here.
        display, hidden = display_ordered_stage_variants(stage_data, stage_folder)

        if from_index < 0 or from_index >= len(display) or to_index < 0 or to_index >= len(display):
            return jsonify({'success': False, 'error': 'Invalid fromIndex or toIndex'}), 400

        entry = display.pop(from_index)
        display.insert(to_index, entry)

        # Persist the new order. A moved disk-only entry is now a real metadata
        # variant (so its position sticks); metadata variants whose zip is
        # missing (not shown) are kept at the end so they aren't lost.
        stage_data['variants'] = display + hidden
        save_metadata(metadata)

        logger.info(f"[OK] Reordered {stage_folder} variants: moved index {from_index} to {to_index}")
        return jsonify({'success': True, 'variants': stage_data['variants']})
    except Exception as e:
        logger.error(f"Reorder stages error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stages/move-to-top', methods=['POST'])
@metadata_write_transaction
def move_stage_to_top():
    """Move a stage variant to the top of the list"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or variantId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])

        variant_index = None
        for i, variant in enumerate(variants):
            if variant['id'] == variant_id:
                variant_index = i
                break

        if variant_index is None:
            return jsonify({'success': False, 'error': f'Variant {variant_id} not found'}), 404

        if variant_index > 0:
            variant = variants.pop(variant_index)
            variants.insert(0, variant)
            save_metadata(metadata)
            logger.info(f"[OK] Moved {stage_folder} variant {variant_id} to top")

        return jsonify({'success': True, 'variants': variants})
    except Exception as e:
        logger.error(f"Move stage to top error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stages/move-to-bottom', methods=['POST'])
@metadata_write_transaction
def move_stage_to_bottom():
    """Move a stage variant to the bottom of the list"""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')

        if not stage_folder or not variant_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or variantId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        stage_data = metadata['stages'][stage_folder]
        variants = stage_data.get('variants', [])

        variant_index = None
        for i, variant in enumerate(variants):
            if variant['id'] == variant_id:
                variant_index = i
                break

        if variant_index is None:
            return jsonify({'success': False, 'error': f'Variant {variant_id} not found'}), 404

        if variant_index < len(variants) - 1:
            variant = variants.pop(variant_index)
            variants.append(variant)
            save_metadata(metadata)
            logger.info(f"[OK] Moved {stage_folder} variant {variant_id} to bottom")

        return jsonify({'success': True, 'variants': variants})
    except Exception as e:
        logger.error(f"Move stage to bottom error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Stage variant folders — mirrors the costume folder system. Folder entries live
# inline in metadata['stages'][folder]['variants'] as {'type':'folder', ...};
# variants carry a 'folder_id'. The das variants endpoint emits both so the
# frontend can render the same folder UI it uses for character skins.
# ─────────────────────────────────────────────────────────────────────────────

@storage_stages_bp.route('/api/mex/storage/stage-folders/create', methods=['POST'])
@metadata_write_transaction
def create_stage_folder():
    """Create a new folder for organizing a stage's variants."""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        name = data.get('name', 'New Folder')

        if not stage_folder:
            return jsonify({'success': False, 'error': 'Missing stageFolder parameter'}), 400

        STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        metadata = load_metadata(default={'stages': {}})

        stages = metadata.setdefault('stages', {})
        stage_data = stages.setdefault(stage_folder, {})
        variants = stage_data.setdefault('variants', [])

        folder_id = f"folder_{uuid.uuid4().hex[:8]}"
        new_folder = {'type': 'folder', 'id': folder_id, 'name': name, 'expanded': True}

        variants.append(new_folder)

        save_metadata(metadata)

        logger.info(f"[OK] Created stage folder '{name}' for {stage_folder}")
        return jsonify({'success': True, 'folder': new_folder, 'variants': variants})
    except Exception as e:
        logger.error(f"Create stage folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stage-folders/rename', methods=['POST'])
@metadata_write_transaction
def rename_stage_folder():
    """Rename a stage folder."""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        folder_id = data.get('folderId')
        new_name = data.get('newName')

        if not stage_folder or not folder_id or not new_name:
            return jsonify({'success': False, 'error': 'Missing stageFolder, folderId, or newName parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        variants = metadata['stages'][stage_folder].get('variants', [])

        folder, idx = find_folder_in_variants(variants, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        folder['name'] = new_name

        save_metadata(metadata)

        logger.info(f"[OK] Renamed stage folder {folder_id} to '{new_name}'")
        return jsonify({'success': True, 'variants': variants})
    except Exception as e:
        logger.error(f"Rename stage folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stage-folders/delete', methods=['POST'])
@metadata_write_transaction
def delete_stage_folder():
    """Delete a stage folder. Does NOT delete the variants themselves."""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        folder_id = data.get('folderId')

        if not stage_folder or not folder_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or folderId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        variants = metadata['stages'][stage_folder].get('variants', [])

        folder, folder_idx = find_folder_in_variants(variants, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        for variant in variants:
            if variant.get('folder_id') == folder_id:
                del variant['folder_id']

        variants.pop(folder_idx)

        save_metadata(metadata)

        logger.info(f"[OK] Deleted stage folder {folder_id}")
        return jsonify({'success': True, 'variants': variants})
    except Exception as e:
        logger.error(f"Delete stage folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stage-folders/toggle', methods=['POST'])
@metadata_write_transaction
def toggle_stage_folder():
    """Toggle a stage folder's expanded state."""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        folder_id = data.get('folderId')

        if not stage_folder or not folder_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or folderId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        variants = metadata['stages'][stage_folder].get('variants', [])

        folder, idx = find_folder_in_variants(variants, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        folder['expanded'] = not folder.get('expanded', True)

        save_metadata(metadata)

        logger.info(f"[OK] Toggled stage folder {folder_id} expanded: {folder['expanded']}")
        return jsonify({'success': True, 'expanded': folder['expanded'], 'variants': variants})
    except Exception as e:
        logger.error(f"Toggle stage folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_stages_bp.route('/api/mex/storage/stage-variants/set-folder', methods=['POST'])
@metadata_write_transaction
def set_stage_variant_folder():
    """Assign or unassign a stage variant to a folder."""
    try:
        data = request.json
        stage_folder = data.get('stageFolder')
        variant_id = data.get('variantId')
        folder_id = data.get('folderId')

        if not stage_folder or not variant_id:
            return jsonify({'success': False, 'error': 'Missing stageFolder or variantId parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        if stage_folder not in metadata.get('stages', {}):
            return jsonify({'success': False, 'error': f'Stage folder {stage_folder} not found in metadata'}), 404

        variants = metadata['stages'][stage_folder].get('variants', [])

        variant = None
        for v in variants:
            if v.get('id') == variant_id and v.get('type') != 'folder':
                variant = v
                break

        if not variant:
            return jsonify({'success': False, 'error': f'Variant {variant_id} not found'}), 404

        if folder_id:
            folder, _ = find_folder_in_variants(variants, folder_id)
            if not folder:
                return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404
            variant['folder_id'] = folder_id
        elif 'folder_id' in variant:
            del variant['folder_id']

        save_metadata(metadata)

        logger.info(f"[OK] Set stage variant {variant_id} folder to {folder_id}")
        return jsonify({'success': True, 'variants': variants})
    except Exception as e:
        logger.error(f"Set stage variant folder error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _render_identity(variant):
    """Identity fields echoed back for each variant of a render batch."""
    stage_code = variant.get('stageCode')
    return {'stageCode': stage_code,
            'stageFolder': ALL_STAGES.get(stage_code, {}).get('folder'),
            'variantId': variant.get('variantId'),
            'name': variant.get('name')}


@storage_stages_bp.route('/api/mex/storage/stages/render-screenshots', methods=['POST'])
def render_stage_screenshots():
    """Bulk-render previews for selected stage variants with the offline HSD
    stage renderer -- no test ISO build and no Dolphin boot (which is what this
    replaced). Each variant is drawn straight from its vault zip on a warm
    `--stage-render` worker, about a second apiece. Mirrors the bulk CSP retake
    flow (one vault-wide button, grouped by stage).

    The shared stage_render job holds preview links and the final result.
    Body: {variants: [{stageCode, variantId, name}, ...]}. Returns immediately;
    saving the reviewed previews still uses /storage/stages/update-screenshot.
    """
    data = request.json or {}
    variants = [v for v in (data.get('variants') or [])
                if isinstance(v, dict) and v.get('stageCode') and v.get('variantId')]
    if not variants:
        return jsonify({'success': False, 'error': 'No valid variants selected.'}), 400

    try:
        job_id = jobs.start(RENDER_KIND, lambda job: run_stage_render(job, variants),
                            single=True, params={'total': len(variants)})
    except jobs.JobBusy as e:
        return jsonify({'success': False, 'error': 'A bulk stage render is already running.',
                        'job_id': e.job_id}), 409
    unsupported = sorted({v['stageCode'] for v in variants
                          if v['stageCode'] not in SUPPORTED_STAGE_CODES})
    return jsonify({'success': True, 'job_id': job_id, 'count': len(variants),
                    'unsupportedStages': unsupported})


def run_stage_render(job, variants):
    work = prepare_previews(job)
    total = len(variants)
    items, failures = [], []
    rendered = 0
    job.check_stop()
    # Closing the generator before finishing also closes its pool and scratch dir.
    from contextlib import closing
    with closing(render_vault_variants(variants, STORAGE_PATH / 'das',
                                     stop=job.stop_event, work_dir=work)) as previews:
        for variant, png, reason in previews:
            index = len(items)
            item = {**_render_identity(variant), 'done': index + 1, 'total': total}
            if png:
                (work / f'{index}.png').write_bytes(png)
                rendered += 1
                item.update(ok=True,
                            previewUrl=f'/api/mex/storage/stages/render-screenshots/{job.id}/{index}.png')
            else:
                item.update(ok=False, error=reason or 'render failed')
                failures.append(item)
            items.append(item)
            job.progress(len(items) / total, f'Rendering {len(items)}/{total}…',
                         items=list(items), done=len(items), total=total)
            if job.should_stop():
                break
    summary = {'total': total, 'rendered': rendered, 'stopped': job.should_stop(),
               'failures': failures, 'items': items}
    # Stop retains the previews already drawn, as the review flow always has.
    job.progress(summary=summary)
    job.release('previews')
    job.check_stop()
    return summary


@storage_stages_bp.route('/api/mex/storage/stages/render-screenshots/<job_id>/<int:index>.png')
def stage_render_preview(job_id, index):
    path = preview_file(job_id, index, RENDER_KIND)
    if path is None:
        return jsonify({'success': False, 'error': 'Preview not found'}), 404
    return send_file(path, mimetype='image/png')


@storage_stages_bp.route('/api/mex/storage/stages/render-screenshots/<job_id>', methods=['DELETE'])
def delete_stage_render_previews(job_id):
    if not delete_previews(job_id, RENDER_KIND):
        return jsonify({'success': False, 'error': 'No finished render found'}), 409
    return jsonify({'success': True})
