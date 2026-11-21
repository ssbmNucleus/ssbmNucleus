"""
The Vault's costume list: the metadata the costume grid reads, listing a
character's costumes, deleting and renaming one.

Registers on `storage_costumes_bp` (vault/routes/storage_costumes/).
"""

import os
import logging
from pathlib import Path
from flask import jsonify, request
from core.config import PROJECT_ROOT, STORAGE_PATH
from core.path_safety import portable_path_parts, validate_path_segment
from core.metadata import (get_char_data, load_metadata, metadata_write_transaction,
    sanitize_skin_metadata, save_metadata)
from . import storage_costumes_bp
from vault.catalog.costume_folders import order_skins_like_vault

logger = logging.getLogger(__name__)


@storage_costumes_bp.route('/api/mex/storage/metadata', methods=['GET'])
def get_storage_metadata():
    """Get storage metadata.json"""
    try:
        # Heal any partial skin entries (missing color/has_csp/...) before
        # handing metadata to the viewer, which indexes those fields.
        metadata = sanitize_skin_metadata(default={'characters': {}})
        # Special fighters (Giga Bowser, wireframes, hands, Sandbag) are custom
        # characters, not grid tiles. Older imports filed their costumes here
        # and the grid drew a nameless "G" card for them; keep such entries
        # out of the grid without touching the stored data.
        from vault.catalog.custom_character_skins import SPECIAL_FIGHTER_NAMES
        chars = metadata.get('characters') or {}
        if any(name in chars for name in SPECIAL_FIGHTER_NAMES):
            metadata = dict(metadata)
            metadata['characters'] = {k: v for k, v in chars.items()
                                      if k not in SPECIAL_FIGHTER_NAMES}

        return jsonify({
            'success': True,
            'metadata': metadata
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@storage_costumes_bp.route('/api/mex/storage/costumes', methods=['GET'])
def list_storage_costumes():
    """List all costumes in storage with MEX-compatible ZIPs."""
    try:
        character = request.args.get('character')
        costumes = []

        # Repair partial skin entries before serving the import list, so a
        # half-written row can't crash the viewer via a missing `color`.
        metadata = sanitize_skin_metadata()
        if metadata is None:
            return jsonify({'success': True, 'costumes': []})

        characters_data = metadata.get('characters', {})
        if character:
            if character in characters_data:
                characters_data = {character: characters_data[character]}
            else:
                # custom-character pseudo keys (.../skins, .../costumes)
                characters_data = {character: get_char_data(metadata, character) or {}}

        for char_name, char_data in characters_data.items():
            skins = char_data.get('skins', [])

            # Present skins in the SAME order the vault (storage tab) shows them
            # -- folder members grouped at their folder's position -- so the flat
            # "Available to Import" list and the vault don't disagree on order.
            # order_skins_like_vault drops folder entries and returns every real
            # skin exactly once, so no `type == 'folder'` guard is needed here.
            for skin in order_skins_like_vault(skins):
                # NOTE: We do NOT filter `visible: False` here. The frontend
                # (CharacterMode.jsx) already filters `!c.isNana` for the
                # displayed costume grid, so hidden Nana entries don't appear
                # as separate tiles — but they DO need to be in the array so
                # the IC install path can find them via
                # `storageCostumes.find(c => c.folder === pairedNanaId)`.
                # Filtering them out here is what was causing "Paired Nana
                # costume not found" → batch-install fail with no HTTP request
                # ever leaving the renderer.

                zip_path = STORAGE_PATH / char_name / skin.get('filename', '')
                if zip_path.exists():
                    alternate_csps = []
                    for alt in skin.get('alternate_csps', []):
                        alternate_csps.append({
                            'id': alt.get('id'),
                            'url': f"/storage/{char_name}/{alt.get('filename')}",
                            'pose_name': alt.get('pose_name'),
                            'is_hd': alt.get('is_hd', False),
                            'timestamp': alt.get('timestamp')
                        })
                    active_csp_id = skin.get('active_csp_id')
                    active_alt = next((a for a in alternate_csps if a.get('id') == active_csp_id), None)
                    if active_alt and active_alt.get('is_hd'):
                        active_alt = next((a for a in alternate_csps
                                           if a.get('pose_name') == active_alt.get('pose_name')
                                           and not a.get('is_hd')), None)
                    csp_url = f"/storage/{char_name}/{skin['id']}_csp.png" if skin.get('has_csp') else None
                    if active_alt and active_alt.get('url'):
                        csp_url = active_alt['url']

                    costume_data = {
                        'character': char_name,
                        'name': f"{char_name} - {skin.get('color', 'Custom')}",
                        'folder': skin['id'],
                        # custom-character skins have no costume_code; fall back
                        # to the DAT stem so the UI still shows something useful
                        'costumeCode': skin.get('costume_code') or Path(skin.get('dat_name', '')).stem,
                        'zipPath': str(zip_path.relative_to(PROJECT_ROOT)),
                        'cspUrl': csp_url,
                        'stockUrl': f"/storage/{char_name}/{skin['id']}_stc.png" if skin.get('has_stock') else None,
                        'alternateCsps': alternate_csps,
                        'activeCspId': skin.get('active_csp_id'),
                        'isPopo': skin.get('is_popo', False),
                        'isNana': skin.get('is_nana', False),
                        'pairedNanaId': skin.get('paired_nana_id'),
                        'pairedPopoId': skin.get('paired_popo_id'),
                        'slippiSafe': skin.get('slippi_safe', False),
                    }
                    costumes.append(costume_data)

        # Custom-character added skins surface here too, so an installed custom
        # fighter shows its extra skins in the same "Available to Import" list
        # as vanilla characters (chosen per-skin instead of force-installed).
        custom_root = STORAGE_PATH / 'custom_characters'
        for cc in metadata.get('custom_characters', []):
            cc_name = cc.get('name')
            cc_slug = cc.get('slug')
            if character and character not in (cc_name, cc_slug):
                continue
            skins_dir = custom_root / cc_slug / 'skins'
            for skin in cc.get('added_skins', []):
                sid = skin.get('id')
                zp = skins_dir / skin.get('filename', f"{sid}.zip")
                if not zp.exists():
                    continue
                alternate_csps = []
                for alt in skin.get('alternate_csps', []):
                    alternate_csps.append({
                        'id': alt.get('id'),
                        'url': f"/storage/custom_characters/{cc_slug}/skins/{alt.get('filename')}",
                        'pose_name': alt.get('pose_name'),
                        'is_hd': alt.get('is_hd', False),
                        'timestamp': alt.get('timestamp')
                    })
                active_csp_id = skin.get('active_csp_id')
                active_alt = next((a for a in alternate_csps if a.get('id') == active_csp_id), None)
                if active_alt and active_alt.get('is_hd'):
                    active_alt = next((a for a in alternate_csps
                                       if a.get('pose_name') == active_alt.get('pose_name')
                                       and not a.get('is_hd')), None)
                csp_url = f"/api/mex/custom-characters/{cc_slug}/skins/{sid}/csp" if skin.get('has_csp') else None
                if active_alt and active_alt.get('url'):
                    csp_url = active_alt['url']
                costumes.append({
                    'character': cc_name,
                    'name': f"{cc_name} - {skin.get('color') or skin.get('name') or 'Custom Skin'}",
                    'folder': sid,
                    'costumeCode': '',
                    'zipPath': str(zp.relative_to(PROJECT_ROOT)),
                    'cspUrl': csp_url,
                    'stockUrl': f"/api/mex/custom-characters/{cc_slug}/skins/{sid}/stock" if skin.get('has_stock') else None,
                    'alternateCsps': alternate_csps,
                    'activeCspId': active_csp_id,
                    'isPopo': False,
                    'isNana': False,
                    'pairedNanaId': None,
                    'pairedPopoId': None,
                    'slippiSafe': False,
                    # routing markers: these import via MexCLI import-costume,
                    # not the vanilla /import path
                    'isCustomCharSkin': True,
                    'customSlug': cc_slug,
                    'skinId': sid,
                })

        return jsonify({'success': True, 'costumes': costumes})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/delete', methods=['POST'])
@metadata_write_transaction
def delete_storage_costume():
    """Delete character costume from storage"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId parameter'}), 400
        try:
            # A fighter name, or a custom character's 'custom_characters/<slug>/skins': relative, inside the Vault.
            portable_path_parts(character, field='character')
            validate_path_segment(skin_id, field='skinId')
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        char_data = get_char_data(metadata, character)
        if char_data is None:
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        skins = char_data.get('skins', [])
        # Older overlapping imports could publish the same identity twice.
        # They own the same ZIP: deleting one row must not leave its duplicate
        # selectable after those files have gone.
        matches = [skin for skin in skins if skin.get('id') == skin_id and skin.get('type') != 'folder']
        if not matches:
            return jsonify({'success': False, 'error': f'Skin {skin_id} not found for {character}'}), 404

        char_folder = STORAGE_PATH / character

        # Every on-disk file this skin owns: the costume zip plus ALL derived
        # portraits — SD CSP, HD CSP, stock, and every alternate-pose CSP.
        # Older deletes only removed _csp.png/_stc.png, which orphaned the HD
        # and alternate PNGs in the character folder; collect them all here.
        names = {
            f"{skin_id}.zip",
            f"{skin_id}_csp.png",
            f"{skin_id}_csp_hd.png",
            f"{skin_id}_stc.png",
        }
        for skin in matches:
            for key in ('filename', 'csp_filename', 'hd_csp_filename'):
                if skin.get(key):
                    names.add(skin[key])
            for alt in skin.get('alternate_csps', []):
                if alt.get('filename'):
                    names.add(alt['filename'])

        # A name from the catalog is a plain file name in this character's folder. One that is not (``..``, an
        # absolute path: a crafted backup's catalog) is refused, and nothing outside the folder is deleted.
        deleted_files = []
        refused_files = []
        folder = char_folder.resolve()
        for name in names:
            try:
                validate_path_segment(name, field='costume file name')
                f = char_folder / name
                if f.resolve().parent != folder:
                    raise ValueError('costume file name leaves the character folder')
            except (TypeError, ValueError):
                logger.warning('Skin %s/%s names a file outside its folder; not deleted: %r',
                               character, skin_id, name)
                refused_files.append(str(name))
                continue
            if f.is_file() and not f.is_symlink():
                f.unlink()
                deleted_files.append(str(f))

        # Belt-and-suspenders: sweep any alternate CSP PNGs that match this
        # skin's id but weren't tracked in metadata. The literal `_csp_alt_`
        # anchor keeps it from matching a longer sibling id; glob.escape guards
        # ids containing glob specials (e.g. "plmrbu[mrsonic]").
        import glob as _glob
        for p in _glob.glob(_glob.escape(str(char_folder / skin_id)) + '_csp_alt_*.png'):
            if p not in deleted_files:
                os.unlink(p)
                deleted_files.append(p)

        skins[:] = [skin for skin in skins if skin not in matches]

        save_metadata(metadata)

        logger.info(f"[OK] Deleted costume {skin_id} for {character}")
        answer = {'success': True, 'message': f'Successfully deleted {skin_id}', 'deleted_files': deleted_files}
        if refused_files:
            answer['refused_files'] = refused_files
        return jsonify(answer)
    except Exception as e:
        logger.error(f"Delete costume error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@storage_costumes_bp.route('/api/mex/storage/costumes/rename', methods=['POST'])
@metadata_write_transaction
def rename_storage_costume():
    """Rename character costume (update color field)"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')
        new_name = data.get('newName')

        if not character or not skin_id or not new_name:
            return jsonify({'success': False, 'error': 'Missing character, skinId, or newName parameter'}), 400

        metadata = load_metadata()
        if metadata is None:
            return jsonify({'success': False, 'error': 'Metadata file not found'}), 404

        char_data = get_char_data(metadata, character)
        if char_data is None:
            return jsonify({'success': False, 'error': f'Character {character} not found in metadata'}), 404

        skins = char_data.get('skins', [])
        skin_found = False

        for skin in skins:
            if skin['id'] == skin_id:
                skin['color'] = new_name
                skin_found = True
                break

        if not skin_found:
            return jsonify({'success': False, 'error': f'Skin {skin_id} not found for {character}'}), 404

        save_metadata(metadata)

        logger.info(f"[OK] Renamed costume {skin_id} to '{new_name}'")
        return jsonify({'success': True, 'message': f'Successfully renamed to {new_name}'})
    except Exception as e:
        logger.error(f"Rename costume error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
