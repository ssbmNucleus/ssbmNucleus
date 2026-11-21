"""
Percent font (IfAll HUD) mod endpoints.

The in-game damage percent font lives in IfAll.dat/.usd (`.usd` = English,
the file a US 1.02 build reads). Digits 0-9 are 32x36 IA4 texture-swap
animation frames under the `DmgNum_scene_models` root (3 banks of 32 frames:
digits 0-9 three times + the 32x24 "%" and "HP" glyphs); the faded franchise
emblem behind the percent is `DmgMrk_scene_models`. Typeface mods often also
retouch the other HUD roots (timer, READY/GO, P1-P4 badges), so a mod stores
*every* slot that differs from vanilla, not just the digits.

Mods arrive in two flavors and are normalized on import:

  1. Compiled IfAll.dat/.usd (alone or in a zip) — exported with
     HSDRawViewer --hud-textures and diffed against the committed vanilla
     manifest (raw-buffer md5 per slot); only differing slots are stored.
     Slots are keyed (root, kind, ordinal) so a mod built from the Japanese
     IfAll.dat still lands on the right slots in the project's IfAll.usd
     (the only structural difference between regions is the usd-only
     Eblm_matanim_joint root).
  2. A glyph pack — loose images named per glyph (`0zero.png`, `7.png`,
     `percent.png`, `HP.png`, ...). Each glyph maps to every DmgNum slot
     whose vanilla pixels show that glyph, and installs as RGB5A3 so color
     survives (vanilla glyphs are grayscale IA4).

    storage/menus/percent/
        metadata.json                   # catalog of installed mods
        <mod_id>/
            mod.json                    # manifest (source + slot list)
            screenshot.png              # optional preview from the zip
            preview.png                 # composed 0-9% strip
            textures/s<n>.png           # one PNG per stored slot

Install runs HSDRawViewer --hud-textures import against the loaded project's
IfAll.usd with a spec.json of index→png replacements.
"""

import shutil
import tempfile
import uuid
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from flask import request, jsonify, send_file

import file_retry
from core.hud_words import WORD_KEYS, GLYPH_KEYS, group_slots as _group_slots

from . import menus_bp
from vault.menus.store import PERCENT_PATH, load_mod_json, save_mod_json
from vault.menus.files import send_mod_zip
from vault.menus.percent import (VANILLA_MANIFEST_DIR, ALL_EDIT_KEYS, _load_vanilla_manifest,
    _load_percent_catalog, _update_catalog_categories, _save_percent_catalog,
    _attach_percent_urls, _compose_preview, install_percent_mods_from_zip,
    catalog_mods_with_categories, percent_preview_path, _mod_glyph_state, _glyph_listing)

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/percent/list', methods=['GET'])
def list_percent_mods():
    """List HUD typeface mods. ?category=percent|readygo filters to mods
    touching that sub-category (a full typeface mod can be in both)."""
    try:
        category = (request.args.get('category') or '').strip().lower()
        mods = [_attach_percent_urls(m) for m in catalog_mods_with_categories()
                if not category or category in m['categories']]
        return jsonify({'success': True, 'mods': mods})
    except Exception as e:
        logger.error(f'List percent mods error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/image/<mod_id>', methods=['GET'])
def get_percent_image(mod_id):
    """Serve the best preview for a percent mod: zip screenshot, composed
    glyph strip, or the largest stored texture."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        path = percent_preview_path(mod_id, mod)
        if path is not None:
            return send_file(str(path), max_age=0)
        return jsonify({'success': False, 'error': 'No preview available'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/import', methods=['POST'])
def import_percent_mod():
    """Import a percent font mod. Accepts .zip (IfAll dat/usd or a digit glyph
    pack) or a raw IfAll .dat/.usd."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        fname_lower = file.filename.lower()
        name = (request.form.get('name') or '').strip() or Path(file.filename).stem
        description = (request.form.get('description') or '').strip()

        is_zip = fname_lower.endswith('.zip')
        is_dat = fname_lower.endswith(('.dat', '.usd'))
        if not (is_zip or is_dat):
            return jsonify({'success': False,
                            'error': 'File must be .zip or an IfAll .dat/.usd'}), 400

        with tempfile.TemporaryDirectory(prefix='percent_upload_') as tmp:
            # Wrap a raw dat in a zip so one code path handles both
            zip_path = Path(tmp) / 'upload.zip'
            if is_zip:
                file.save(str(zip_path))
            else:
                raw = file.read()
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    zf.writestr(file.filename, raw)
            try:
                mods = install_percent_mods_from_zip(zip_path, name=name, description=description)
            except zipfile.BadZipFile:
                return jsonify({'success': False, 'error': 'Invalid or corrupt zip file'}), 400
            except RuntimeError as e:
                return jsonify({'success': False, 'error': str(e)}), 400

        return jsonify({'success': True, 'mods': mods, 'imported_count': len(mods)})
    except Exception as e:
        logger.error(f'Import percent mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/create', methods=['POST'])
def create_percent_mod():
    """Create a fresh HUD typeface mod — a blank canvas for the glyph/word
    editor. Starts with no slots (= vanilla everywhere); edits add slots.
    Body: {name?, category?: 'percent'|'readygo', draft?}.

    When `draft` is true the mod folder is created but NOT added to the catalog,
    so it stays invisible in the vault until the editor commits it via /save."""
    try:
        payload = request.get_json(silent=True) or {}
        category = (payload.get('category') or 'percent').strip().lower()
        if category not in ('percent', 'readygo'):
            category = 'percent'
        default_name = 'New Ready/Go Pack' if category == 'readygo' else 'New Percent Font'
        name = (payload.get('name') or '').strip() or default_name
        is_draft = bool(payload.get('draft'))

        mod_id = str(uuid.uuid4())[:8]
        mod = {
            'id': mod_id,
            'name': name,
            'description': '',
            'source': 'custom',
            'region': 'usd',
            'origin_category': category,
            'slots': [],
            'created': datetime.now().isoformat(),
        }
        if is_draft:
            mod['draft'] = True
        save_mod_json(PERCENT_PATH, mod_id, mod)
        if not is_draft:
            catalog = _load_percent_catalog()
            catalog.setdefault('mods', []).append({
                'id': mod_id,
                'name': name,
                'description': '',
                'source': 'custom',
                'categories': [category],
                'created': mod['created'],
            })
            _save_percent_catalog(catalog)

        logger.info(f'[OK] Created {"draft " if is_draft else ""}percent font mod: {name} ({mod_id})')
        return jsonify({'success': True, 'mod': _attach_percent_urls(mod), 'draft': is_draft})
    except Exception as e:
        logger.error(f'Create percent mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/save', methods=['POST'])
def save_percent_mod(mod_id):
    """Commit a draft to the vault and/or rename a mod. Body: {name?}."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.get_json(silent=True) or {}
        name = (payload.get('name') or '').strip()
        if name:
            mod['name'] = name
        mod.pop('draft', None)
        save_mod_json(PERCENT_PATH, mod_id, mod)

        category = mod.get('origin_category', 'percent')
        catalog = _load_percent_catalog()
        mods = catalog.setdefault('mods', [])
        entry = next((m for m in mods if m.get('id') == mod_id), None)
        if entry is None:
            mods.append({
                'id': mod_id,
                'name': mod['name'],
                'description': mod.get('description', ''),
                'source': mod.get('source', 'custom'),
                'categories': [category],
                'created': mod.get('created'),
            })
        else:
            entry['name'] = mod['name']
        _save_percent_catalog(catalog)

        logger.info(f'[OK] Saved percent font mod: {mod["name"]} ({mod_id})')
        return jsonify({'success': True, 'mod': _attach_percent_urls(mod)})
    except Exception as e:
        logger.error(f'Save percent mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/discard', methods=['POST'])
def discard_percent_draft(mod_id):
    """Discard an uncommitted draft (delete its folder). No-op once committed."""
    try:
        catalog = _load_percent_catalog()
        if any(m.get('id') == mod_id for m in catalog.get('mods', [])):
            return jsonify({'success': True, 'committed': True})
        mod_dir = PERCENT_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(str(mod_dir), ignore_errors=True)
        logger.info(f'[OK] Discarded percent draft: {mod_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Discard percent draft error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/glyphs', methods=['GET'])
def list_percent_glyphs(mod_id):
    """Glyph listing for the percent editor: 0-9, percent, HP with current
    image URLs and whether the mod overrides them."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return jsonify({'success': True,
                        'glyphs': _glyph_listing(mod_id, mod, GLYPH_KEYS),
                        'mod': _attach_percent_urls(mod)})
    except Exception as e:
        logger.error(f'List percent glyphs error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/words', methods=['GET'])
def list_percent_words(mod_id):
    """Word-banner listing for the Ready/Go/Game editor."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return jsonify({'success': True,
                        'glyphs': _glyph_listing(mod_id, mod, WORD_KEYS),
                        'mod': _attach_percent_urls(mod)})
    except Exception as e:
        logger.error(f'List percent words error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/glyph/<mod_id>/<key>', methods=['GET'])
def get_percent_glyph(mod_id, key):
    try:
        if key not in ALL_EDIT_KEYS:
            return jsonify({'success': False, 'error': 'Unknown glyph'}), 404
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if mod:
            slot = _mod_glyph_state(mod).get(key)
            if slot:
                tex_path = PERCENT_PATH / mod_id / 'textures' / slot['file']
                if tex_path.exists():
                    return send_file(str(tex_path), mimetype='image/png', max_age=0)
        vanilla_glyph = VANILLA_MANIFEST_DIR() / f'glyph_{key}.png'
        if vanilla_glyph.exists():
            return send_file(str(vanilla_glyph), mimetype='image/png', max_age=0)
        return jsonify({'success': False, 'error': 'Glyph not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/replace_glyph', methods=['POST'])
def replace_percent_glyph(mod_id):
    """Replace one glyph (0-9 / percent / hp) with an uploaded image — lands on
    every DmgNum slot showing that glyph. Multipart form: key + file. The first
    edit of a dat-sourced slot backs up its texture so it can be reverted."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        key = (request.form.get('key') or '').strip().lower()
        if key not in ALL_EDIT_KEYS:
            return jsonify({'success': False, 'error': f'key must be one of {ALL_EDIT_KEYS}'}), 400
        if 'file' not in request.files or not request.files['file'].filename:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        vanilla = _load_vanilla_manifest('usd')
        groups = _group_slots(vanilla)
        entries = groups.get(key, [])
        if not entries:
            return jsonify({'success': False, 'error': 'Vanilla HUD manifest unavailable'}), 500

        upload = request.files['file'].read()
        mod_dir = PERCENT_PATH / mod_id
        tex_dir = mod_dir / 'textures'
        tex_dir.mkdir(parents=True, exist_ok=True)
        slots = mod.setdefault('slots', [])
        slot_index = {(s['root'], s['kind'], s['ordinal']): s for s in slots}

        next_n = max([int(s['file'][1:-4]) for s in slots if s['file'][1:-4].isdigit()] or [-1]) + 1
        for e in entries:
            slot = slot_index.get((e['root'], e['kind'], e['ordinal']))
            if slot is None:
                slot = {
                    'root': e['root'],
                    'kind': e['kind'],
                    'ordinal': e['ordinal'],
                    'width': e['width'],
                    'height': e['height'],
                    'format': e['format'],
                    'file': f's{next_n}.png',
                    'added_by_glyph': True,
                }
                next_n += 1
                slots.append(slot)
            else:
                tex_path = tex_dir / slot['file']
                orig_path = tex_dir / f"{slot['file'][:-4]}.orig.png"
                if tex_path.exists() and not orig_path.exists() and not slot.get('added_by_glyph'):
                    shutil.copy(str(tex_path), str(orig_path))
                    slot['orig_replaced'] = bool(slot.get('replaced'))
            file_retry.retry_locked((tex_dir / slot['file']).write_bytes, upload)
            slot['replaced'] = True
            slot['glyph'] = key

        save_mod_json(PERCENT_PATH, mod_id, mod)
        _update_catalog_categories(mod)
        _compose_preview(mod_dir, slots)
        logger.info(f'[OK] Replaced percent glyph "{key}" on mod {mod_id} ({len(entries)} slots)')
        return jsonify({'success': True, 'key': key,
                        'url': f'/api/mex/menus/percent/glyph/{mod_id}/{key}'})
    except Exception as e:
        logger.error(f'Replace percent glyph error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/screenshot', methods=['POST'])
def upload_percent_screenshot(mod_id):
    """Replace a percent mod's preview screenshot with an uploaded image."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        f = request.files.get('screenshot') or request.files.get('file')
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400

        mod_dir = PERCENT_PATH / mod_id
        mod_dir.mkdir(parents=True, exist_ok=True)
        f.save(str(mod_dir / 'screenshot.png'))
        mod['screenshot'] = 'screenshot.png'   # get_percent_image prefers this
        save_mod_json(PERCENT_PATH, mod_id, mod)
        return jsonify({'success': True, 'imageUrl': f'/api/mex/menus/percent/image/{mod_id}'})
    except Exception as e:
        logger.error(f'Upload percent screenshot error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/export', methods=['GET'])
def export_percent_mod(mod_id):
    """Download a percent mod's files as a zip."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return send_mod_zip(PERCENT_PATH / mod_id, mod.get('name') or mod_id)
    except Exception as e:
        logger.error(f'Export percent mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/<mod_id>/revert_glyph', methods=['POST'])
def revert_percent_glyph(mod_id):
    """Undo a glyph edit. Body: {key}. Slots created by the edit are removed
    (back to vanilla); dat-sourced slots restore their backed-up texture."""
    try:
        mod = load_mod_json(PERCENT_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.get_json(silent=True) or {}
        key = (payload.get('key') or '').strip().lower()
        if key not in ALL_EDIT_KEYS:
            return jsonify({'success': False, 'error': f'key must be one of {ALL_EDIT_KEYS}'}), 400

        mod_dir = PERCENT_PATH / mod_id
        tex_dir = mod_dir / 'textures'
        slots = mod.get('slots', [])
        keep = []
        reverted = 0
        for slot in slots:
            if slot.get('glyph') != key:
                keep.append(slot)
                continue
            tex_path = tex_dir / slot['file']
            orig_path = tex_dir / f"{slot['file'][:-4]}.orig.png"
            if orig_path.exists():
                file_retry.retry_locked(shutil.move, str(orig_path), str(tex_path))
                slot['replaced'] = slot.pop('orig_replaced', False)
                slot.pop('glyph', None)
                keep.append(slot)
            else:
                file_retry.retry_locked(tex_path.unlink, missing_ok=True)
            reverted += 1
        if not reverted:
            return jsonify({'success': False, 'error': 'Nothing to revert for this glyph'}), 400

        mod['slots'] = keep
        save_mod_json(PERCENT_PATH, mod_id, mod)
        _update_catalog_categories(mod)
        _compose_preview(mod_dir, keep)
        logger.info(f'[OK] Reverted percent glyph "{key}" on mod {mod_id}')
        return jsonify({'success': True, 'key': key,
                        'url': f'/api/mex/menus/percent/glyph/{mod_id}/{key}'})
    except Exception as e:
        logger.error(f'Revert percent glyph error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/percent/delete/<mod_id>', methods=['POST'])
def delete_percent_mod(mod_id):
    try:
        catalog = _load_percent_catalog()
        mods = catalog.get('mods', [])
        idx = next((i for i, m in enumerate(mods) if m.get('id') == mod_id), -1)
        if idx < 0:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        mod_dir = PERCENT_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(str(mod_dir), ignore_errors=True)

        mods.pop(idx)
        _save_percent_catalog(catalog)
        logger.info(f'[OK] Deleted percent mod: {mod_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Delete percent mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
