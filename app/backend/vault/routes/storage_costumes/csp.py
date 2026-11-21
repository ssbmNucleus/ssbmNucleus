"""
A costume's character select portrait: upload a replacement, capture the HD
portrait, manage alternate portraits, re-render it from a pose, and retake the
portraits of many costumes in one background batch.

Registers on `storage_costumes_bp` (vault/routes/storage_costumes/).
"""

import os
import time
import re
import shutil
import zipfile
import tempfile
import logging
import file_retry
from datetime import datetime
from pathlib import Path
from flask import jsonify, request, send_file
from core.config import STORAGE_PATH
from core import jobs
from shared.rendering.job_previews import (clean_previews, prepare_previews,
    preview_file, delete_previews)
from core.costume_files import find_extracted_costume_archive
from core.metadata import get_char_data, load_metadata, save_metadata
from core.safe_archive import safe_extract_zip
from core.atomic_archive import rewrite_zip_atomic
from core.active_portrait import (resolve_active_portrait as _resolve_active_portrait,
    next_alt_csp_number, put_pose_portrait, show_pose_portrait)
from core.path_safety import resolve_under_root
from shared.rendering.portrait import (render_portrait, poses_root as _poses_root,
    pose_character_key as _pose_character_key)
# The costume portrait preview (render without writing) is shared with
# Randall's preview_portrait tool; the names below are this module's seams.
from shared.rendering.costume_preview import (gw_colors_from_zip as _gw_colors_from_zip,
    paired_nana_zip as _paired_nana_zip, render_costume_preview as _render_costume_preview)
from . import storage_costumes_bp
from shared.rendering.csp_frame import derive_csp_versions

logger = logging.getLogger(__name__)


@storage_costumes_bp.route('/api/mex/storage/costumes/update-csp', methods=['POST'])
def update_costume_csp():
    """Update CSP image for a character costume.

    With auto=true, one uploaded image is split into both versions: shrunk to
    the in-game 136x188 texture, and kept (up to 4x) as the HD vault preview.
    The legacy isHd flag updates just one of the two files.
    """
    try:
        character = request.form.get('character')
        skin_id = request.form.get('skinId')
        is_hd = request.form.get('isHd', '').lower() == 'true'
        auto = request.form.get('auto', '').lower() == 'true'

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        if 'csp' not in request.files:
            return jsonify({'success': False, 'error': 'No CSP file provided'}), 400

        csp_file = request.files['csp']
        if csp_file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not csp_file.content_type.startswith('image/'):
            return jsonify({'success': False, 'error': 'File must be an image'}), 400

        csp_data = csp_file.read()
        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"

        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume zip not found: {skin_id}'}), 404

        # Derive file extension from MIME type to preserve original format (e.g. GIF)
        ext_map = {
            'image/gif': '.gif', 'image/png': '.png', 'image/jpeg': '.jpg',
            'image/webp': '.webp', 'image/bmp': '.bmp'
        }
        ext = ext_map.get(csp_file.content_type, '.png')

        # Auto mode: derive both SD (in-game) and HD (preview) from one image.
        # Animated GIFs fall through to the legacy as-is path.
        if auto and csp_file.content_type != 'image/gif':
            sd_data, hd_data = derive_csp_versions(csp_data)

            csp_filename = f"{skin_id}_csp.png"
            file_retry.retry_locked((char_folder / csp_filename).write_bytes, sd_data)

            def replace_csp(source_zip, dest_zip):
                for item in source_zip.infolist():
                    if item.filename.lower() not in ['csp.png', 'csp']:
                        dest_zip.writestr(item, source_zip.read(item.filename))
                dest_zip.writestr('csp.png', sd_data)
            rewrite_zip_atomic(zip_path, replace_csp)

            hd_filename = None
            hd_size = None
            if hd_data:
                hd_filename = f"{skin_id}_csp_hd.png"
                file_retry.retry_locked((char_folder / hd_filename).write_bytes, hd_data)
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(hd_data)) as img:
                    hd_size = f"{img.size[0]}x{img.size[1]}"

            metadata = load_metadata()
            if metadata is not None:
                char_data = get_char_data(metadata, character)
                if char_data is not None:
                    for skin in char_data.get('skins', []):
                        if skin['id'] == skin_id:
                            skin['has_csp'] = True
                            skin['csp_source'] = 'custom'
                            skin['csp_filename'] = csp_filename
                            skin.pop('csp_pose_name', None)
                            if hd_filename:
                                skin['has_hd_csp'] = True
                                skin['hd_csp_source'] = 'custom'
                                skin['hd_csp_filename'] = hd_filename
                                skin['hd_csp_resolution'] = 'custom'
                                skin['hd_csp_size'] = hd_size
                            break
                    save_metadata(metadata)

            logger.info(f"[OK] Updated CSP for {character} - {skin_id} (auto, hd={'yes' if hd_data else 'no'})")
            return jsonify({'success': True, 'message': 'CSP updated successfully', 'hasHd': bool(hd_data)})

        if is_hd:
            hd_csp_filename = f"{skin_id}_csp_hd{ext}"
            standalone_hd_csp = char_folder / hd_csp_filename
            with file_retry.retry_locked(open, standalone_hd_csp, 'wb') as f:
                f.write(csp_data)

            metadata = load_metadata()
            if metadata is not None:
                char_data = get_char_data(metadata, character)
                if char_data is not None:
                    for skin in char_data.get('skins', []):
                        if skin['id'] == skin_id:
                            skin['has_hd_csp'] = True
                            skin['hd_csp_source'] = 'custom'
                            skin['hd_csp_filename'] = hd_csp_filename
                            break

                    save_metadata(metadata)

            logger.info(f"[OK] Updated HD CSP for {character} - {skin_id}")
        else:
            csp_filename = f"{skin_id}_csp{ext}"
            standalone_csp = char_folder / csp_filename
            with file_retry.retry_locked(open, standalone_csp, 'wb') as f:
                f.write(csp_data)

            def replace_csp(source_zip, dest_zip):
                for item in source_zip.infolist():
                    if item.filename.lower() not in ['csp.png', 'csp']:
                        dest_zip.writestr(item, source_zip.read(item.filename))
                dest_zip.writestr('csp.png', csp_data)
            rewrite_zip_atomic(zip_path, replace_csp)

            metadata = load_metadata()
            if metadata is not None:
                char_data = get_char_data(metadata, character)
                if char_data is not None:
                    for skin in char_data.get('skins', []):
                        if skin['id'] == skin_id:
                            skin['has_csp'] = True
                            skin['csp_source'] = 'custom'
                            skin['csp_filename'] = csp_filename
                            skin.pop('csp_pose_name', None)
                            break

                    save_metadata(metadata)

            logger.info(f"[OK] Updated CSP for {character} - {skin_id}")

        return jsonify({'success': True, 'message': 'CSP updated successfully', 'isHd': is_hd})
    except Exception as e:
        logger.error(f"Update CSP error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/<path:character>/<skin_id>/csp/manage', methods=['POST', 'OPTIONS'])
def manage_csp(character, skin_id):
    """Manage CSPs for a skin - swap, remove, add alternatives, regenerate HD"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            action = request.form.get('action')
            alt_id = request.form.get('altId')
            scale = int(request.form.get('scale', 4))
            file = request.files.get('file')
        else:
            data = request.get_json() or {}
            action = data.get('action')
            alt_id = data.get('altId')
            scale = data.get('scale', 4)
            target = data.get('target')
            file = None

        logger.info(f"[CSP Manage] {character}/{skin_id} action={action} altId={alt_id}")

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata not found'}), 404

        char_data = get_char_data(metadata, character) or {}
        skins = char_data.get('skins', [])
        skin = next((s for s in skins if s.get('id') == skin_id), None)

        if not skin:
            return jsonify({'success': False, 'error': 'Skin not found'}), 404

        if action == 'swap':
            alt_csps = skin.get('alternate_csps', [])
            alt = next((a for a in alt_csps if a.get('id') == alt_id), None)
            if not alt:
                return jsonify({'success': False, 'error': 'Alt CSP not found'}), 404

            alt_pose = alt.get('pose_name')
            non_hd_alt = next((a for a in alt_csps if a.get('pose_name') == alt_pose and not a.get('is_hd', False)), None)

            if non_hd_alt:
                skin['active_csp_id'] = non_hd_alt.get('id')
            else:
                skin['active_csp_id'] = alt_id

            save_metadata(metadata)

            logger.info(f"[OK] Set active CSP to: {skin['active_csp_id']}")
            return jsonify({'success': True, 'message': 'Active CSP updated', 'activeCspId': skin['active_csp_id']})

        elif action == 'reset':
            skin['active_csp_id'] = None
            save_metadata(metadata)
            return jsonify({'success': True, 'message': 'Reset to original CSP', 'activeCspId': None})

        elif action == 'remove':
            alt_csps = skin.get('alternate_csps', [])
            alt = next((a for a in alt_csps if a.get('id') == alt_id), None)
            if not alt:
                return jsonify({'success': False, 'error': 'Alt CSP not found'}), 404

            alt_csp_path = STORAGE_PATH / character / alt.get('filename')
            if alt_csp_path.exists():
                alt_csp_path.unlink()

            skin['alternate_csps'] = [a for a in alt_csps if a.get('id') != alt_id]

            save_metadata(metadata)

            return jsonify({'success': True, 'message': 'Alt CSP removed'})

        elif action == 'add':
            if not file:
                return jsonify({'success': False, 'error': 'No file provided'}), 400

            is_hd_upload = request.form.get('isHd', '').lower() == 'true'
            auto = request.form.get('auto', '').lower() == 'true'
            alt_csps = skin.get('alternate_csps', [])

            # Auto mode: one image becomes an SD + HD pair, grouped by a name
            # derived from the uploaded filename (animated GIFs stay as-is below)
            if auto and file.content_type != 'image/gif':
                if 'alternate_csps' not in skin:
                    skin['alternate_csps'] = []
                    alt_csps = skin['alternate_csps']

                sd_data, hd_data = derive_csp_versions(file.read())

                stem = re.sub(r'[^\w\- ]', '', Path(file.filename or '').stem).strip() or 'custom'
                existing_names = {a.get('pose_name') for a in alt_csps}
                group_name = stem
                suffix = 2
                while group_name in existing_names:
                    group_name = f"{stem} {suffix}"
                    suffix += 1

                ts = int(time.time())
                n = next_alt_csp_number(alt_csps)
                now = datetime.now().isoformat()

                sd_id = f"alt_{ts}"
                sd_filename = f"{skin_id}_csp_alt_{n}.png"
                (STORAGE_PATH / character / sd_filename).write_bytes(sd_data)
                skin['alternate_csps'].append({
                    'id': sd_id,
                    'filename': sd_filename,
                    'pose_name': group_name,
                    'is_hd': False,
                    'timestamp': now
                })

                if hd_data:
                    hd_filename = f"{skin_id}_csp_alt_{n}_hd.png"
                    (STORAGE_PATH / character / hd_filename).write_bytes(hd_data)
                    skin['alternate_csps'].append({
                        'id': f"alt_{ts}_hd",
                        'filename': hd_filename,
                        'pose_name': group_name,
                        'is_hd': True,
                        'timestamp': now
                    })

                save_metadata(metadata)

                return jsonify({
                    'success': True,
                    'message': 'Alt CSP added',
                    'altId': sd_id,
                    'url': f"/storage/{character}/{sd_filename}",
                    'isHd': False,
                    'hasHd': bool(hd_data),
                    'poseName': group_name
                })

            new_alt_id = f"alt_{int(time.time())}{'_hd' if is_hd_upload else ''}"

            # Preserve original file extension (e.g. .gif for animated GIFs)
            alt_ext_map = {
                'image/gif': '.gif', 'image/png': '.png', 'image/jpeg': '.jpg',
                'image/webp': '.webp', 'image/bmp': '.bmp'
            }
            alt_ext = alt_ext_map.get(file.content_type, '.png')

            alt_num = next_alt_csp_number(alt_csps)
            if is_hd_upload:
                new_alt_filename = f"{skin_id}_csp_alt_{alt_num}_hd{alt_ext}"
            else:
                new_alt_filename = f"{skin_id}_csp_alt_{alt_num}{alt_ext}"

            new_alt_path = STORAGE_PATH / character / new_alt_filename
            file.save(new_alt_path)

            if 'alternate_csps' not in skin:
                skin['alternate_csps'] = []

            skin['alternate_csps'].append({
                'id': new_alt_id,
                'filename': new_alt_filename,
                'pose_name': None,
                'is_hd': is_hd_upload,
                'timestamp': datetime.now().isoformat()
            })

            save_metadata(metadata)

            return jsonify({
                'success': True,
                'message': 'Alt CSP added',
                'altId': new_alt_id,
                'url': f"/storage/{character}/{new_alt_filename}",
                'isHd': is_hd_upload
            })

        elif action == 'regenerate-hd':
            zip_path = STORAGE_PATH / character / skin.get('filename', '')
            if not zip_path.exists():
                return jsonify({'success': False, 'error': 'Skin ZIP not found'}), 404

            pose_name = None
            is_main = target == 'main' or not alt_id

            if not is_main:
                alt_csps = skin.get('alternate_csps', [])
                alt = next((a for a in alt_csps if a.get('id') == alt_id), None)
                if not alt:
                    return jsonify({'success': False, 'error': 'Alt CSP not found'}), 404
                pose_name = alt.get('pose_name')

            temp_dir = tempfile.mkdtemp(prefix='csp_regen_')
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    safe_extract_zip(zf, temp_dir)

                dat_file = find_extracted_costume_archive(Path(temp_dir))
                if not dat_file:
                    return jsonify({'success': False, 'error': 'No costume archive found in ZIP'}), 400

                # The one renderer (shared/rendering/portrait.py) — it resolves the pose,
                # falls back to the character default when there is none, and
                # applies the per-character layers itself.
                rendered = render_portrait(
                    dat_file, character, pose_name=pose_name, scale=scale,
                    gw_colors=_gw_colors_from_zip(zip_path))
                csp_output = rendered.path

                if pose_name and not rendered.pose_applied:
                    # Writing the DEFAULT portrait into an alternate that is
                    # defined by its pose would silently replace the user's
                    # posed art. Fail instead.
                    return jsonify({'success': False,
                                    'error': f"Could not render pose '{pose_name}'"}), 500
                if not csp_output or not Path(csp_output).exists():
                    return jsonify({'success': False, 'error': 'CSP generation failed'}), 500

                if is_main:
                    output_path = STORAGE_PATH / character / f"{skin_id}_csp_hd.png"
                    from PIL import Image
                    with Image.open(csp_output) as img:
                        width, height = img.size
                    skin['has_hd_csp'] = True
                    skin['hd_csp_resolution'] = f"{scale}x"
                    skin['hd_csp_size'] = f"{width}x{height}"
                    file_retry.retry_locked(shutil.move, csp_output, output_path)
                else:
                    alt_csps = skin.get('alternate_csps', [])
                    existing_hd = next((a for a in alt_csps if a.get('pose_name') == pose_name and a.get('is_hd', False)), None)

                    if existing_hd:
                        output_path = STORAGE_PATH / character / existing_hd.get('filename')
                        file_retry.retry_locked(shutil.move, csp_output, output_path)
                    else:
                        new_hd_id = f"alt_{int(time.time())}_hd"
                        new_hd_filename = f"{skin_id}_csp_alt_{next_alt_csp_number(alt_csps)}_hd.png"
                        output_path = STORAGE_PATH / character / new_hd_filename
                        shutil.move(csp_output, output_path)
                        alt_csps.append({
                            'id': new_hd_id,
                            'filename': new_hd_filename,
                            'pose_name': pose_name,
                            'is_hd': True,
                            'timestamp': datetime.now().isoformat()
                        })
                        skin['alternate_csps'] = alt_csps

                save_metadata(metadata)

                return jsonify({'success': True, 'message': f'HD CSP regenerated at {scale}x', 'isHd': True, 'isMain': is_main})

            finally:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)

        else:
            return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400

    except Exception as e:
        logger.error(f"CSP manage error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/generate-csp', methods=['POST'])
def generate_costume_csp():
    """Re-render ("retake") a vault costume's character-select portrait with the
    headless HSDRaw renderer, using whichever pose is currently active for the
    skin -- the original/default pose unless a custom-pose alternate is the
    active portrait in the CSP manager.

    Two-step flow so nothing is overwritten without the user's say-so (mirrors
    generate-stock):
      {character, skinId}                   -> preview: {dataUri, poseName};
                                               nothing is written
      {character, skinId, apply, imageData} -> writes the previewed portrait to
                                               the active portrait (original CSP
                                               + HD, or the active pose alternate)

    Both steps take an optional `poseName`: that pose is rendered instead of
    the active one, and applying it makes it the portrait the skin shows (null
    is the default pose: the original portrait, shown again).
    """
    try:
        import base64

        data = request.json or {}
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400

        char_folder = STORAGE_PATH / character
        zip_path = char_folder / f"{skin_id}.zip"
        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume zip not found: {skin_id}'}), 404

        metadata = load_metadata()
        skin_meta = None
        if metadata is not None:
            char_data = get_char_data(metadata, character)
            if char_data is not None:
                skin_meta = next((s for s in char_data.get('skins', [])
                                  if s['id'] == skin_id), None)

        active_alt, pose_name = _resolve_active_portrait(skin_meta)

        # A pose named in the request is the pose to take AND the one the skin
        # shows once it is applied (null: the default pose, back on the
        # original portrait). Without one this retakes whatever is showing.
        chosen = 'poseName' in data
        if chosen:
            active_alt, pose_name = None, (data.get('poseName') or None)
        if chosen and pose_name:
            try:
                # Both names come from the client: the pose must be one of
                # this character's own (as vault/routes/poses.py checks it).
                pose_file = resolve_under_root(
                    resolve_under_root(_poses_root(), _pose_character_key(character),
                                       field='character'),
                    f"{pose_name}.yml", field='pose name')
            except ValueError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
            if not pose_file.exists():
                return jsonify({'success': False, 'error': f'Pose {pose_name} not found'}), 404
            if skin_meta is None:
                return jsonify({'success': False, 'error': f'Skin not found: {skin_id}'}), 404

        # ---- apply: write the render the user already previewed -------------
        if data.get('apply'):
            image_data = data.get('imageData') or ''
            if ',' in image_data:
                image_data = image_data.split(',', 1)[1]
            try:
                raw = base64.b64decode(image_data)
            except Exception:
                raw = b''
            if not raw:
                return jsonify({'success': False, 'error': 'No previewed portrait to apply'}), 400

            # The preview is the HD render; split it into the in-game SD texture
            # and the (capped) HD vault preview, exactly like a manual upload.
            sd_data, hd_data = derive_csp_versions(raw)
            alt_csps = (skin_meta or {}).get('alternate_csps', [])

            if chosen and pose_name:
                # The pose's own portrait (one per pose), now the one on show.
                def into(payload):
                    return lambda name: file_retry.retry_locked(
                        (char_folder / name).write_bytes, payload)
                sd_alt = put_pose_portrait(skin_meta, skin_id, pose_name, False, into(sd_data))
                if hd_data:
                    put_pose_portrait(skin_meta, skin_id, pose_name, True, into(hd_data))
                show_pose_portrait(skin_meta, pose_name)
                save_metadata(metadata)
                logger.info(f"[OK] Took CSP for {character} - {skin_id} with pose '{pose_name}', now showing")
                return jsonify({'success': True,
                                'cspUrl': f"/storage/{character}/{sd_alt['filename']}",
                                'activeCspId': skin_meta.get('active_csp_id')})

            if active_alt:
                # Active custom-pose alternate: overwrite its SD (+ HD) in place.
                sd_filename = active_alt.get('filename')
                file_retry.retry_locked((char_folder / sd_filename).write_bytes, sd_data)
                active_alt['timestamp'] = datetime.now().isoformat()
                if hd_data:
                    hd_alt = next((a for a in alt_csps
                                   if a.get('pose_name') == pose_name and a.get('is_hd')), None)
                    if hd_alt:
                        file_retry.retry_locked((char_folder / hd_alt.get('filename')).write_bytes, hd_data)
                        hd_alt['timestamp'] = datetime.now().isoformat()
                    else:
                        hd_filename = f"{skin_id}_csp_alt_{next_alt_csp_number(alt_csps)}_hd.png"
                        (char_folder / hd_filename).write_bytes(hd_data)
                        alt_csps.append({
                            'id': f"alt_{int(time.time())}_hd",
                            'filename': hd_filename,
                            'pose_name': pose_name,
                            'is_hd': True,
                            'timestamp': datetime.now().isoformat()
                        })
                if metadata is not None:
                    save_metadata(metadata)
                logger.info(f"[OK] Retook CSP for {character} - {skin_id} (pose '{pose_name}')")
                return jsonify({'success': True,
                                'cspUrl': f"/storage/{character}/{sd_filename}"})

            # Original/default portrait: SD into standalone + zip, HD standalone.
            csp_filename = f"{skin_id}_csp.png"
            file_retry.retry_locked((char_folder / csp_filename).write_bytes, sd_data)
            def replace_csp(source_zip, dest_zip):
                for item in source_zip.infolist():
                    if item.filename.lower() not in ['csp.png', 'csp']:
                        dest_zip.writestr(item, source_zip.read(item.filename))
                dest_zip.writestr('csp.png', sd_data)
            rewrite_zip_atomic(zip_path, replace_csp)

            hd_filename = None
            hd_size = None
            if hd_data:
                hd_filename = f"{skin_id}_csp_hd.png"
                file_retry.retry_locked((char_folder / hd_filename).write_bytes, hd_data)
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(hd_data)) as img:
                    hd_size = f"{img.size[0]}x{img.size[1]}"

            if metadata is not None and skin_meta is not None:
                skin_meta['has_csp'] = True
                skin_meta['csp_source'] = 'generated'
                skin_meta['csp_filename'] = csp_filename
                skin_meta.pop('csp_pose_name', None)
                if chosen:
                    skin_meta['active_csp_id'] = None  # the default pose was asked for by name
                if hd_filename:
                    skin_meta['has_hd_csp'] = True
                    skin_meta['hd_csp_source'] = 'generated'
                    skin_meta['hd_csp_filename'] = hd_filename
                    skin_meta['hd_csp_resolution'] = '4x'
                    skin_meta['hd_csp_size'] = hd_size
                save_metadata(metadata)

            logger.info(f"[OK] Retook CSP for {character} - {skin_id} (default pose)")
            return jsonify({'success': True,
                            'cspUrl': f"/storage/{character}/{csp_filename}",
                            'hasHd': bool(hd_data)})

        # ---- preview: render now at HD, return a data URI, write nothing ----
        nana_zip = _paired_nana_zip(metadata, skin_meta)
        png_bytes, pose_label = _render_costume_preview(
            character, zip_path, pose_name, nana_zip_path=nana_zip)
        if chosen and pose_name and pose_label != pose_name:
            # A pose asked for by name is never answered with the default one.
            why = ('Ice Climbers portraits keep both climbers, so they cannot take a pose'
                   if nana_zip else f"Could not render pose '{pose_name}' for this costume")
            return jsonify({'success': False, 'error': why}), 500
        logger.info(f"[OK] Previewed retaken CSP for {character} - {skin_id} (pose '{pose_label}')")
        return jsonify({'success': True, 'poseName': pose_label,
                        'dataUri': 'data:image/png;base64,'
                                   + base64.b64encode(png_bytes).decode('ascii')})
    except Exception as e:
        logger.error(f"Generate CSP error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# One bulk retake at a time: active_pool installs a process-global CSP pool, so
# two concurrent batches would clobber each other's pool.
RETAKE_KIND = 'csp_retake'
jobs.register_kind(RETAKE_KIND, label='Portrait retake', cleanup=clean_previews)


@storage_costumes_bp.route('/api/mex/storage/costumes/batch-retake-csp', methods=['POST'])
def batch_retake_csp():
    """Bulk-retake selected costumes' portraits -- across ANY number of
    characters -- each with its OWN active pose, through the persistent CSP
    render pool. Renders only -- nothing is written; the frontend reviews the
    before/after grid and applies the kept ones via /generate-csp (apply), which
    saves both the in-game SD portrait and the HD one. Mirrors the stage
    bulk-capture flow (one vault-wide button, grouped by character).

    Returns {success, job_id, count}. The shared job record carries progress,
    preview links and the final result. Body: {items: [{character, skinId}]} or
    {character, skinIds}."""
    data = request.json or {}
    items = []
    for it in data.get('items') or []:
        if isinstance(it, dict) and it.get('character') and it.get('skinId'):
            items.append((it['character'], it['skinId']))
    if not items and data.get('character'):
        items = [(data['character'], sid) for sid in (data.get('skinIds') or [])]
    if not items:
        return jsonify({'success': False,
                        'error': 'Missing items (or character + skinIds)'}), 400

    # Snapshot the skins' metadata on the request thread (don't touch Flask state
    # from the worker); each costume keeps its own active-portrait/pose.
    metadata = load_metadata()
    skin_lookups = {}
    for character, _sid in items:
        if character not in skin_lookups:
            char_data = get_char_data(metadata, character) if metadata else None
            skins = (char_data or {}).get('skins', [])
            skin_lookups[character] = {s['id']: s for s in skins
                                       if s.get('type') != 'folder'}
    costumes = [(character, sid, skin_lookups[character].get(sid),
             _paired_nana_zip(metadata, skin_lookups[character].get(sid)))
            for character, sid in items]

    try:
        job_id = jobs.start(RETAKE_KIND, lambda job: run_csp_retake(job, costumes),
                            single=True, params={'total': len(costumes)})
    except jobs.JobBusy as e:
        return jsonify({'success': False, 'error': 'A bulk CSP retake is already running.',
                        'job_id': e.job_id}), 409
    return jsonify({'success': True, 'job_id': job_id, 'count': len(costumes)})


def run_csp_retake(job, costumes):
    from shared.rendering.csp_pool import active_pool
    work = prepare_previews(job)
    total = len(costumes)
    rendered = 0
    items = []
    job.check_stop()
    # Sequential submissions need just one warm renderer.
    with active_pool(workers=1):
        for i, (character, sid, skin_meta, nana_zip) in enumerate(costumes):
            job.check_stop()
            item = {'character': character, 'skinId': sid, 'done': i + 1, 'total': total}
            try:
                if skin_meta is None:
                    raise ValueError('Skin not found')
                zip_path = STORAGE_PATH / character / f"{sid}.zip"
                if not zip_path.exists():
                    raise FileNotFoundError('Costume zip not found')
                _active_alt, pose_name = _resolve_active_portrait(skin_meta)
                png_bytes, pose_label = _render_costume_preview(
                    character, zip_path, pose_name, nana_zip_path=nana_zip, work_dir=work)
                (work / f'{i}.png').write_bytes(png_bytes)
                item.update(ok=True, poseName=pose_label,
                            previewUrl=f'/api/mex/storage/costumes/batch-retake-csp/{job.id}/{i}.png')
                rendered += 1
            except Exception as e:  # one bad costume must not stop the batch
                item.update(ok=False, error=str(e))
                logger.warning('Batch retake: %s/%s failed: %s', character, sid, e)
            items.append(item)
            job.progress((i + 1) / total, f'Retaking {i + 1}/{total}…',
                         items=list(items), done=i + 1, total=total)
    job.check_stop()
    job.release('previews')
    return {'total': total, 'rendered': rendered, 'items': items}


@storage_costumes_bp.route('/api/mex/storage/costumes/batch-retake-csp/<job_id>/<int:index>.png')
def retake_preview(job_id, index):
    path = preview_file(job_id, index, RETAKE_KIND)
    if path is None:
        return jsonify({'success': False, 'error': 'Preview not found'}), 404
    return send_file(path, mimetype='image/png')


@storage_costumes_bp.route('/api/mex/storage/costumes/batch-retake-csp/<job_id>', methods=['DELETE'])
def delete_retake_previews(job_id):
    if not delete_previews(job_id, RETAKE_KIND):
        return jsonify({'success': False, 'error': 'No finished retake found'}), 409
    return jsonify({'success': True})
