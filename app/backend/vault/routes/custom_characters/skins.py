"""
Custom character skins and bundled costumes (vault editing).

Added skins live under storage/custom_characters/<slug>/skins/ with their
entries in `entry['added_skins']`; bundled costumes are the ones inside
fighter.zip, mirrored into costumes/<stem>.zip + `entry['costume_meta']` so the
shared skin-edit stack can open them. Also: moving a costume between the two,
the default CSP pose, and routing an imported special-fighter costume (Giga
Bowser, wireframes, hands, Sandbag) to its custom character.

Registers on `custom_characters_bp` (vault/routes/custom_characters/__init__.py).
"""

import json
import re
import shutil
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from flask import request, jsonify, send_file

import file_retry
from core.config import STORAGE_PATH, CUSTOM_CHARACTERS_PATH
from vault.importing.custom_character_package import sync_costume_meta as _sync_costume_meta
from vault.catalog.custom_characters import (
    _active_csp_path_for_skin, _find_entry, _read_metadata, _rewrite_fighter_zip,
    _update_fighter_json_everywhere, _write_metadata,
)

from . import custom_characters_bp
from vault.catalog.custom_character_skins import (_validate_costume_zip,
    _extract_skin_previews, _custom_pose_path, _main_csp_filename,
    _ensure_custom_skin_main_csp, _store_custom_skin)

logger = logging.getLogger(__name__)


# ============= Custom skins (vault, per custom character) =============

@custom_characters_bp.route('/api/mex/custom-characters/<slug>/skins/add', methods=['POST'])
def add_custom_character_skin(slug):
    """Add a custom skin to a vault custom character.

    Accepts either:
      - multipart upload: 'file' = costume .zip (PlXxYy.dat + csp.png/stc.png)
        or a bare .dat, optional 'name' field
      - JSON {character, skinId}: copy a canonical skin from the vault
        (used by drag-and-drop from a canonical character)
    """
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if not (char_dir / 'fighter.json').exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found in metadata'}), 404

        skin_name = None
        source_character = None
        src_skin = None
        requested_pose = ''

        if 'file' in request.files:
            uploaded = request.files['file']
            fname = (uploaded.filename or '').lower()
            raw = uploaded.read()
            skin_name = (request.form.get('name') or Path(uploaded.filename).stem).strip()
            requested_pose = (request.form.get('poseName') or '').strip()
            if fname.endswith(('.dat', '.usd')):
                # wrap a bare DAT into a costume zip
                import io
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(Path(uploaded.filename).name, raw)
                zip_bytes = buf.getvalue()
            elif fname.endswith('.zip'):
                zip_bytes = raw
            else:
                return jsonify({'success': False, 'error': 'File must be a .zip or .dat costume'}), 400
        else:
            data = request.get_json(silent=True) or {}
            source_character = (data.get('character') or '').strip()
            skin_id_src = (data.get('skinId') or '').strip()
            requested_pose = (data.get('poseName') or '').strip()
            if not source_character or not skin_id_src:
                return jsonify({'success': False, 'error': 'Provide a file or {character, skinId}'}), 400

            char_meta = metadata.get('characters', {}).get(source_character)
            if not char_meta:
                return jsonify({'success': False, 'error': f'Character {source_character} not found'}), 404
            src_skin = next((s for s in char_meta.get('skins', [])
                             if s.get('id') == skin_id_src and s.get('type') != 'folder'), None)
            if not src_skin:
                return jsonify({'success': False, 'error': f'Skin {skin_id_src} not found'}), 404
            src_zip = STORAGE_PATH / source_character / src_skin['filename']
            if not src_zip.exists():
                return jsonify({'success': False, 'error': f'Skin zip missing: {src_skin["filename"]}'}), 404
            zip_bytes = src_zip.read_bytes()
            skin_name = src_skin.get('color') or Path(src_skin['filename']).stem

        dat_name, err = _validate_costume_zip(zip_bytes)
        if err:
            return jsonify({'success': False, 'error': err}), 400

        skin_entry = _store_custom_skin(
            slug, char_dir, entry, zip_bytes, dat_name, skin_name,
            source_character=source_character, src_skin=src_skin,
            requested_pose=requested_pose)
        _write_metadata(metadata)
        skin_id, has_csp, has_stock = skin_entry['id'], skin_entry['has_csp'], skin_entry['has_stock']

        logger.info(f"[OK] Added custom skin '{skin_entry['color']}' to {slug}")
        return jsonify({'success': True, 'skin': {
            **skin_entry,
            'name': skin_entry['color'],
            'csp_url': f"/api/mex/custom-characters/{slug}/skins/{skin_id}/csp" if has_csp else None,
            'stock_url': f"/api/mex/custom-characters/{slug}/skins/{skin_id}/stock" if has_stock else None,
        }})
    except Exception as e:
        logger.error(f"Add custom skin error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/skins/<skin_id>/remove', methods=['POST'])
def remove_custom_character_skin(slug, skin_id):
    try:
        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        skins = entry.get('added_skins', [])
        skin = next((s for s in skins if s['id'] == skin_id), None)
        if skin is None:
            return jsonify({'success': False, 'error': 'Skin not found'}), 404

        # remove the zip + every derived file (csp/stc/HD/alt csps)
        skins_dir = CUSTOM_CHARACTERS_PATH / slug / 'skins'
        if skins_dir.exists():
            for p in skins_dir.glob(f'{skin_id}*'):
                p.unlink()

        entry['added_skins'] = [s for s in skins if s['id'] != skin_id]
        _write_metadata(metadata)

        logger.info(f"[OK] Removed custom skin '{skin.get('color') or skin.get('name')}' from {slug}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Remove custom skin error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/skins/reorder', methods=['POST'])
def reorder_custom_character_skins(slug):
    """Reorder a custom character's added skins. Body: {order: [skin_id, ...]}.
    Ids not present in `order` (or unknown) keep their relative order at the end,
    so a partial/stale list never drops skins."""
    try:
        order = (request.get_json(silent=True) or {}).get('order') or []
        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        skins = entry.get('added_skins', [])
        by_id = {s.get('id'): s for s in skins}
        seen = set()
        new_list = []
        for sid in order:
            s = by_id.get(sid)
            if s is not None and sid not in seen:
                new_list.append(s)
                seen.add(sid)
        for s in skins:  # append any not named in `order`
            if s.get('id') not in seen:
                new_list.append(s)
        entry['added_skins'] = new_list
        _write_metadata(metadata)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Reorder custom skins error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/skins/<skin_id>/csp', methods=['GET'])
def get_custom_character_skin_csp(slug, skin_id):
    metadata = _read_metadata()
    entry = _find_entry(metadata, slug) or {}
    skin = next((s for s in entry.get('added_skins', [])
                 if s.get('id') == skin_id), None)
    if skin:
        active_path = _active_csp_path_for_skin(f'custom_characters/{slug}/skins', skin)
        if active_path:
            return send_file(active_path, mimetype='image/png')
    p = CUSTOM_CHARACTERS_PATH / slug / 'skins' / f'{skin_id}_csp.png'
    if p.exists():
        return send_file(p, mimetype='image/png')
    return jsonify({'success': False, 'error': 'CSP not found'}), 404


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/skins/<skin_id>/stock', methods=['GET'])
def get_custom_character_skin_stock(slug, skin_id):
    for fname in (f'{skin_id}_stc.png', f'{skin_id}_stock.png'):
        p = CUSTOM_CHARACTERS_PATH / slug / 'skins' / fname
        if p.exists():
            return send_file(p, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Stock icon not found'}), 404


def _drop_bundled_costume(char_dir, fighter_data, index):
    """Remove costume `index` from storage fighter.json, the fighter.zip
    (embedded fighter.json + inner costume zip — add-fighter re-reads both)
    and shift csp_N/stock_N previews. Returns the removed costume dict."""
    removed = fighter_data['costumes'].pop(index)
    dat_name = (removed.get('file') or {}).get('fileName', '')
    inner_zip = f"{Path(dat_name).stem}.zip" if dat_name else None

    with file_retry.retry_locked(open, char_dir / 'fighter.json', 'w', encoding='utf-8') as f:
        json.dump(fighter_data, f, indent=2)

    def _drop_costume(meta):
        zcost = meta.get('costumes', [])
        if index < len(zcost):
            zcost.pop(index)
        return meta
    _rewrite_fighter_zip(char_dir, mutate_json=_drop_costume,
                         drop_entries=[inner_zip] if inner_zip else None)

    for prefix in ('csp', 'stock'):
        removed_png = char_dir / f'{prefix}_{index}.png'
        if removed_png.exists():
            removed_png.unlink()
        i = index + 1
        while (char_dir / f'{prefix}_{i}.png').exists():
            (char_dir / f'{prefix}_{i}.png').rename(char_dir / f'{prefix}_{i - 1}.png')
            i += 1

    return removed


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/costumes/<int:index>/remove', methods=['POST'])
def remove_bundled_costume(slug, index):
    """Remove one of the costumes bundled in fighter.zip."""
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json_path = char_dir / 'fighter.json'
        if not fighter_json_path.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        with open(fighter_json_path, 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)

        costumes = fighter_data.get('costumes', [])
        if index < 0 or index >= len(costumes):
            return jsonify({'success': False, 'error': f'Invalid costume index {index}'}), 400
        if len(costumes) <= 1:
            return jsonify({'success': False, 'error': 'A fighter needs at least one costume'}), 400

        removed = _drop_bundled_costume(char_dir, fighter_data, index)

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is not None:
            entry['costume_count'] = len(costumes)
            _write_metadata(metadata)

        dat_name = (removed.get('file') or {}).get('fileName', '')
        logger.info(f"[OK] Removed bundled costume {index} ({dat_name}) from {slug}")
        return jsonify({'success': True, 'costume_count': len(costumes)})
    except Exception as e:
        logger.error(f"Remove bundled costume error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/costumes/<int:index>/to-skin', methods=['POST'])
def bundled_costume_to_skin(slug, index):
    """Move a bundled costume into the Custom Skins area (drag-down in the
    UI). The costume's inner zip is lifted out of fighter.zip into skins/;
    on install it comes back via import-costume like any added skin."""
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json_path = char_dir / 'fighter.json'
        if not fighter_json_path.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found in metadata'}), 404

        with open(fighter_json_path, 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)

        costumes = fighter_data.get('costumes', [])
        if index < 0 or index >= len(costumes):
            return jsonify({'success': False, 'error': f'Invalid costume index {index}'}), 400
        if len(costumes) <= 1:
            return jsonify({'success': False, 'error': 'A fighter needs at least one bundled costume'}), 400

        costume = costumes[index]
        dat_name = (costume.get('file') or {}).get('fileName', '')
        if not dat_name:
            return jsonify({'success': False, 'error': 'Costume has no DAT file'}), 400
        stem = Path(dat_name).stem
        inner_name = f"{stem}.zip"
        costume_meta = next((m for m in entry.get('costume_meta', []) if m.get('id') == stem), None)

        zip_bytes = None
        with zipfile.ZipFile(char_dir / 'fighter.zip') as zf:
            for n in zf.namelist():
                if n.split('/')[-1].lower() == inner_name.lower():
                    zip_bytes = zf.read(n)
                    break
        if zip_bytes is None:
            return jsonify({'success': False, 'error': f'Costume zip {inner_name} not found in fighter.zip'}), 404

        _, err = _validate_costume_zip(zip_bytes)
        if err:
            return jsonify({'success': False, 'error': err}), 400

        import uuid
        skin_id = uuid.uuid4().hex[:8]
        skins_dir = char_dir / 'skins'
        skins_dir.mkdir(exist_ok=True)
        (skins_dir / f'{skin_id}.zip').write_bytes(zip_bytes)
        has_csp, has_stock = _extract_skin_previews(skins_dir, skin_id, zip_bytes)

        # Inner costume zips usually carry csp/stc, but fall back to the
        # character-dir previews before they get shifted by the removal
        if not has_csp and (char_dir / f'csp_{index}.png').exists():
            shutil.copy2(char_dir / f'csp_{index}.png', skins_dir / f'{skin_id}_csp.png')
            has_csp = True
        if not has_stock and (char_dir / f'stock_{index}.png').exists():
            shutil.copy2(char_dir / f'stock_{index}.png', skins_dir / f'{skin_id}_stc.png')
            has_stock = True
        hd_src = char_dir / 'costumes' / f'{stem}_csp_hd.png'
        has_hd_csp = False
        if hd_src.exists():
            shutil.copy2(hd_src, skins_dir / f'{skin_id}_csp_hd.png')
            has_hd_csp = True

        skin_entry = {
            'id': skin_id,
            'color': costume.get('name') or Path(dat_name).stem,
            'filename': f'{skin_id}.zip',
            'dat_name': dat_name,
            'has_csp': has_csp,
            'has_stock': has_stock,
            'source_character': None,
            'date_added': datetime.now().isoformat(),
        }
        if has_csp:
            skin_entry['csp_source'] = (costume_meta or {}).get('csp_source') or 'uploaded'
        if has_hd_csp:
            skin_entry['has_hd_csp'] = True
            skin_entry['hd_csp_source'] = (costume_meta or {}).get('hd_csp_source') or skin_entry.get('csp_source')
            skin_entry['hd_csp_resolution'] = (costume_meta or {}).get('hd_csp_resolution') or '4x'
            skin_entry['hd_csp_size'] = (costume_meta or {}).get('hd_csp_size') or '544x752'
        if costume_meta and costume_meta.get('csp_pose_name'):
            skin_entry['csp_pose_name'] = costume_meta['csp_pose_name']

        _drop_bundled_costume(char_dir, fighter_data, index)

        entry.setdefault('added_skins', []).append(skin_entry)
        entry['costume_count'] = len(fighter_data.get('costumes', []))
        _write_metadata(metadata)

        logger.info(f"[OK] Moved bundled costume {index} ({dat_name}) of {slug} to custom skins")
        return jsonify({'success': True, 'skin': {
            **skin_entry,
            'name': skin_entry['color'],
            'csp_url': f"/api/mex/custom-characters/{slug}/skins/{skin_id}/csp" if has_csp else None,
            'stock_url': f"/api/mex/custom-characters/{slug}/skins/{skin_id}/stock" if has_stock else None,
        }, 'costume_count': len(fighter_data.get('costumes', []))})
    except Exception as e:
        logger.error(f"Costume to skin error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/costumes/reorder', methods=['POST'])
def reorder_bundled_costumes(slug):
    """Reorder a custom character's bundled costumes. Body: {order: [stem,...]}
    (DAT stems, i.e. the frontend's costume edit_id). Rewrites fighter.json
    (storage + embedded), fixes visibilityIndex, and reshuffles the positional
    csp_N/stock_N previews to follow."""
    try:
        order = (request.get_json(silent=True) or {}).get('order') or []
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json_path = char_dir / 'fighter.json'
        if not fighter_json_path.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        with open(fighter_json_path, 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)
        costumes = fighter_data.get('costumes', [])

        def _stem(c):
            return Path((c.get('file') or {}).get('fileName') or '').stem

        by_stem = {_stem(c): c for c in costumes}
        # snapshot positional previews by stem before reordering
        prev = {}
        for i, c in enumerate(costumes):
            for kind in ('csp', 'stock'):
                p = char_dir / f'{kind}_{i}.png'
                if p.exists():
                    prev[(_stem(c), kind)] = p.read_bytes()

        seen, new_costumes = set(), []
        for s in order:
            c = by_stem.get(s)
            if c is not None and s not in seen:
                new_costumes.append(c); seen.add(s)
        for c in costumes:  # keep any not named in order
            if _stem(c) not in seen:
                new_costumes.append(c)

        for i, c in enumerate(new_costumes):
            c.setdefault('file', {})['visibilityIndex'] = i
        fighter_data['costumes'] = new_costumes

        with file_retry.retry_locked(open, fighter_json_path, 'w', encoding='utf-8') as f:
            json.dump(fighter_data, f, indent=2)
        _rewrite_fighter_zip(char_dir,
                             mutate_json=lambda m: ({**m, 'costumes': new_costumes}))

        # rewrite positional previews in the new order
        for i, c in enumerate(new_costumes):
            for kind in ('csp', 'stock'):
                data = prev.get((_stem(c), kind))
                target = char_dir / f'{kind}_{i}.png'
                if data is not None:
                    target.write_bytes(data)
                elif target.exists():
                    target.unlink()

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is not None:
            # reorder costume_meta to match (cosmetic; _sync rebuilds by stem)
            cm = {m['id']: m for m in entry.get('costume_meta', [])}
            entry['costume_meta'] = [cm[s] for c in new_costumes
                                     if (s := _stem(c)) in cm]
            _write_metadata(metadata)

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Reorder bundled costumes error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/skins/<skin_id>/to-costume', methods=['POST'])
def skin_to_bundled_costume(slug, skin_id):
    """Promote an added skin to a bundled costume (drag a custom skin UP into
    Costumes). Inverse of bundled_costume_to_skin: the skin's zip is folded
    back into fighter.zip and a new costume entry is appended to fighter.json.
    The jointSymbol is read straight from the DAT so the model's real root is
    used (recolors can differ). icon/csp are left null — install regenerates
    them from the DAT like any imported costume."""
    try:
        import io
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        fighter_json_path = char_dir / 'fighter.json'
        if not fighter_json_path.exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404

        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found in metadata'}), 404

        skins = entry.get('added_skins', [])
        skin = next((s for s in skins if s.get('id') == skin_id), None)
        if skin is None:
            return jsonify({'success': False, 'error': 'Skin not found'}), 404

        skins_dir = char_dir / 'skins'
        skin_zip_path = skins_dir / skin.get('filename', f'{skin_id}.zip')
        if not skin_zip_path.exists():
            return jsonify({'success': False, 'error': 'Skin zip missing'}), 404
        zip_bytes = skin_zip_path.read_bytes()
        dat_name, err = _validate_costume_zip(zip_bytes)
        if err:
            return jsonify({'success': False, 'error': err}), 400
        stem = Path(dat_name).stem
        inner_name = f'{stem}.zip'

        with open(fighter_json_path, 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)
        costumes = fighter_data.setdefault('costumes', [])

        existing = {Path((c.get('file') or {}).get('fileName') or '').stem for c in costumes}
        if stem in existing:
            return jsonify({'success': False,
                            'error': f'A bundled costume named {stem} already exists'}), 400

        # jointSymbol from the DAT itself (its embedded root symbol)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            dat_bytes = zf.read(next(n for n in zf.namelist()
                                     if n.lower().endswith(('.dat', '.usd'))))
        m = re.search(rb'Ply[A-Za-z0-9]+_Share_joint', dat_bytes)
        joint = (m.group(0).decode() if m
                 else (costumes[0].get('file') or {}).get('jointSymbol') if costumes else None)

        template = costumes[0] if costumes else {}
        new_index = len(costumes)
        new_costume = {
            'name': skin.get('color') or stem,
            'colorSmashGroup': template.get('colorSmashGroup', -1),
            'file': {
                'visibilityIndex': new_index,
                'fileName': dat_name,
                'jointSymbol': joint,
                'materialSymbol': None,
            },
            'icon': None,
            'csp': None,
        }

        def _add(meta):
            meta.setdefault('costumes', []).append(new_costume)
            return meta

        costumes.append(new_costume)
        with file_retry.retry_locked(open, fighter_json_path, 'w', encoding='utf-8') as f:
            json.dump(fighter_data, f, indent=2)
        _rewrite_fighter_zip(char_dir, mutate_json=_add, replace_entries={inner_name: zip_bytes})

        # materialize the bundled costume + previews (reuse the posed skin CSP)
        costumes_dir = char_dir / 'costumes'
        costumes_dir.mkdir(exist_ok=True)
        (costumes_dir / inner_name).write_bytes(zip_bytes)
        if (skins_dir / f'{skin_id}_csp.png').exists():
            shutil.copy2(skins_dir / f'{skin_id}_csp.png', costumes_dir / f'{stem}_csp.png')
            shutil.copy2(skins_dir / f'{skin_id}_csp.png', char_dir / f'csp_{new_index}.png')
        if (skins_dir / f'{skin_id}_csp_hd.png').exists():
            shutil.copy2(skins_dir / f'{skin_id}_csp_hd.png', costumes_dir / f'{stem}_csp_hd.png')
        if (skins_dir / f'{skin_id}_stc.png').exists():
            shutil.copy2(skins_dir / f'{skin_id}_stc.png', costumes_dir / f'{stem}_stc.png')
            shutil.copy2(skins_dir / f'{skin_id}_stc.png', char_dir / f'stock_{new_index}.png')

        for p in skins_dir.glob(f'{skin_id}*'):
            p.unlink()
        entry['added_skins'] = [s for s in skins if s.get('id') != skin_id]
        entry['costume_count'] = len(costumes)
        _sync_costume_meta(entry, char_dir, fighter_data)
        new_meta = next((m for m in entry.get('costume_meta', []) if m.get('id') == stem), None)
        if new_meta is not None:
            for field in (
                'csp_source', 'csp_pose_name', 'has_hd_csp',
                'hd_csp_source', 'hd_csp_resolution', 'hd_csp_size'
            ):
                if field in skin:
                    new_meta[field] = skin[field]
        _write_metadata(metadata)

        logger.info(f"[OK] Promoted skin {skin_id} ({dat_name}) of {slug} to bundled costume {new_index}")
        return jsonify({'success': True, 'costume_count': len(costumes)})
    except Exception as e:
        logger.error(f"Skin to costume error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/default-pose', methods=['POST'])
def set_custom_character_default_pose(slug):
    """Set the character's default CSP pose.

    By default this fills only missing main CSPs. Existing portraits and active
    alternates are left untouched so choosing a default cannot silently duplicate
    an alternate or mismatch a user's selected portrait. Callers may pass
    renderExisting=true to intentionally regenerate existing main CSPs.
    """
    try:
        payload = request.get_json(silent=True) or {}
        pose_name = (payload.get('poseName') or '').strip()
        render_existing = bool(payload.get('renderExisting'))
        if not pose_name:
            return jsonify({'success': False, 'error': 'Missing poseName'}), 400

        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if not (char_dir / 'fighter.json').exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404
        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Character not found in metadata'}), 404

        try:
            pose_path = _custom_pose_path(slug, pose_name)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        if not pose_path.exists():
            return jsonify({'success': False, 'error': f'Pose {pose_name} not found'}), 404

        with open(char_dir / 'fighter.json', 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)
        costumes_dir = char_dir / 'costumes'
        costumes_dir.mkdir(exist_ok=True)
        skins_dir = char_dir / 'skins'
        _sync_costume_meta(entry, char_dir, fighter_data)
        meta_by_id = {m.get('id'): m for m in entry.get('costume_meta', [])}
        filled = 0
        generated = 0
        copied = 0
        skipped = 0

        def _count(result):
            nonlocal filled, generated, copied, skipped
            if result.get('filled'):
                filled += 1
                if result.get('source') == 'alternate':
                    copied += 1
                elif result.get('source') == 'generated':
                    generated += 1
            elif result.get('source') == 'existing':
                skipped += 1

        # bundled costumes
        for i, costume in enumerate(fighter_data.get('costumes', [])):
            dat_name = (costume.get('file') or {}).get('fileName') or ''
            stem = Path(dat_name).stem
            if not stem:
                continue
            meta = meta_by_id.get(stem)
            if meta is None:
                continue
            src = costumes_dir / f'{stem}.zip'
            if not src.exists():
                continue
            result = _ensure_custom_skin_main_csp(
                slug,
                costumes_dir,
                meta,
                src,
                src.read_bytes(),
                pose_name,
                replace_existing=render_existing
            )
            _count(result)
            if result.get('filled'):
                main_path = costumes_dir / _main_csp_filename(meta)
                if main_path.exists():
                    (char_dir / f'csp_{i}.png').write_bytes(main_path.read_bytes())
                _rewrite_fighter_zip(char_dir, replace_entries={f'{stem}.zip': src.read_bytes()})

        # added skins
        for skin in entry.get('added_skins', []):
            sid = skin.get('id')
            src = skins_dir / skin.get('filename', f'{sid}.zip')
            if not src.exists():
                continue
            result = _ensure_custom_skin_main_csp(
                slug,
                skins_dir,
                skin,
                src,
                src.read_bytes(),
                pose_name,
                replace_existing=render_existing
            )
            _count(result)

        entry['default_pose'] = pose_name
        _write_metadata(metadata)
        logger.info(
            f"[OK] Set default pose '{pose_name}' for {slug}; "
            f"filled={filled} generated={generated} copied={copied} skipped={skipped}"
        )
        return jsonify({
            'success': True,
            'default_pose': pose_name,
            'rendered': filled,
            'filled': filled,
            'generated': generated,
            'copied': copied,
            'skipped': skipped,
        })
    except Exception as e:
        logger.error(f"Set default pose error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_characters_bp.route('/api/mex/custom-characters/<slug>/costumes/<int:index>/rename', methods=['POST'])
def rename_bundled_costume(slug, index):
    try:
        char_dir = CUSTOM_CHARACTERS_PATH / slug
        if not (char_dir / 'fighter.json').exists():
            return jsonify({'success': False, 'error': 'Character not found'}), 404
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'}), 400

        with open(char_dir / 'fighter.json', 'r', encoding='utf-8') as f:
            fighter_data = json.load(f)
        costumes = fighter_data.get('costumes', [])
        if index < 0 or index >= len(costumes):
            return jsonify({'success': False, 'error': f'Invalid costume index {index}'}), 400

        def _set(meta):
            metac = meta.get('costumes', [])
            if index < len(metac):
                metac[index]['name'] = name
        _update_fighter_json_everywhere(char_dir, _set)

        # keep the costume mirror's display name in sync
        dat = (costumes[index].get('file') or {}).get('fileName') or ''
        stem = Path(dat).stem
        metadata = _read_metadata()
        entry = _find_entry(metadata, slug)
        if entry is not None:
            for m in entry.get('costume_meta', []):
                if m['id'] == stem:
                    m['color'] = name
                    _write_metadata(metadata)
                    break

        logger.info(f"[OK] Renamed {slug} costume {index} to '{name}'")
        return jsonify({'success': True, 'name': name})
    except Exception as e:
        logger.error(f"Rename costume error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
