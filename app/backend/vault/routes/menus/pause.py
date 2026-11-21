"""
Pause screen (GmPause) mod endpoints.

A pause mod replaces textures in the in-game pause overlay (GmPause.usd).
Mods arrive in two flavors and are normalized on import:

  1. Compiled GmPause.dat/.usd (alone or in a zip) — every texture is dumped
     to PNG via HSDRawViewer --pause-screen export and stored by index. A zip
     can ship several GmPause variants (e.g. white/black/silver controller
     colors); each becomes its own mod.
  2. A plain picture (png/jpg/webp) — stored as-is. On install it replaces
     the central 88x72 pause graphic (the camera-control icon), re-encoded
     as RGB5A3 so color survives (the vanilla texture is grayscale IA4).

    storage/menus/pause/
        metadata.json                   # catalog of installed mods
        <mod_id>/
            mod.json                    # manifest (source + texture list)
            screenshot.png              # optional preview from the zip
            picture.png                 # image-sourced mods
            textures/t<index>.png       # dat-sourced mods

Install runs HSDRawViewer --pause-screen import against the loaded project's
GmPause.usd with a spec.json describing the replacements.
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

from . import menus_bp
from vault.menus.store import PAUSE_PATH, load_mod_json, save_mod_json
from vault.menus.files import send_mod_zip
# Writing a stored mod into GmPause.usd is the install engine (pause_install.py),
# shared with the in-game capture build.
from vault.menus.pause_install import set_mod_screenshot
from vault.menus.pause import (IMAGE_SUFFIXES, VANILLA_TEX_DIR, _load_pause_catalog,
    _save_pause_catalog, _attach_pause_urls, install_pause_mods_from_zip, pause_preview_path,
    import_pause_picture, _main_pair_indices, _ensure_textures)

logger = logging.getLogger(__name__)


@menus_bp.route('/api/mex/menus/pause/list', methods=['GET'])
def list_pause_mods():
    try:
        catalog = _load_pause_catalog()
        mods = [_attach_pause_urls(m) for m in catalog.get('mods', []) if m.get('id')]
        return jsonify({'success': True, 'mods': mods})
    except Exception as e:
        logger.error(f'List pause mods error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/image/<mod_id>', methods=['GET'])
def get_pause_image(mod_id):
    """Serve the best preview for a pause mod: zip screenshot, uploaded
    picture, or the main (largest) extracted texture."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        path = pause_preview_path(mod_id, mod)
        if path is not None:
            return send_file(str(path), max_age=0)
        return jsonify({'success': False, 'error': 'No preview available'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/import', methods=['POST'])
def import_pause_mod():
    """Import a pause screen mod. Accepts .zip (containing GmPause dat/usd),
    a raw GmPause .dat/.usd, or a plain picture (png/jpg/webp)."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        fname_lower = file.filename.lower()
        name = (request.form.get('name') or '').strip() or Path(file.filename).stem
        description = (request.form.get('description') or '').strip()

        # Plain picture → stored as-is, replaces the main pause graphic on install
        if fname_lower.endswith(IMAGE_SUFFIXES):
            mod = import_pause_picture(file.read(), name, description)
            return jsonify({'success': True, 'mods': [mod], 'imported_count': 1})

        is_zip = fname_lower.endswith('.zip')
        is_dat = fname_lower.endswith(('.dat', '.usd'))
        if not (is_zip or is_dat):
            return jsonify({'success': False,
                            'error': 'File must be .zip, .dat, .usd, or an image (.png/.jpg/.webp)'}), 400

        with tempfile.TemporaryDirectory(prefix='pause_upload_') as tmp:
            # Wrap a raw dat in a zip so one code path handles both
            zip_path = Path(tmp) / 'upload.zip'
            if is_zip:
                file.save(str(zip_path))
            else:
                raw = file.read()
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    zf.writestr(file.filename, raw)
            try:
                mods = install_pause_mods_from_zip(zip_path, name=name, description=description)
            except zipfile.BadZipFile:
                return jsonify({'success': False, 'error': 'Invalid or corrupt zip file'}), 400
            except RuntimeError as e:
                return jsonify({'success': False, 'error': str(e)}), 400

        return jsonify({'success': True, 'mods': mods, 'imported_count': len(mods)})
    except Exception as e:
        logger.error(f'Import pause mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/create', methods=['POST'])
def create_pause_mod():
    """Create a fresh pause mod seeded with the vanilla textures — a blank
    canvas for the per-texture editor. Body: {name?, draft?}.

    When `draft` is true the mod folder is created and seeded but NOT added to
    the catalog, so it stays invisible in the vault until the editor commits it
    via /save. Leaving the editor calls /discard to clean it up."""
    try:
        payload = request.get_json(silent=True) or {}
        name = (payload.get('name') or '').strip() or 'New Pause Mod'
        is_draft = bool(payload.get('draft'))

        mod_id = str(uuid.uuid4())[:8]
        mod = {
            'id': mod_id,
            'name': name,
            'description': '',
            'source': 'custom',
            'created': datetime.now().isoformat(),
        }
        if is_draft:
            mod['draft'] = True
        save_mod_json(PAUSE_PATH, mod_id, mod)
        try:
            mod = _ensure_textures(mod)   # seed the full vanilla set
        except RuntimeError as e:
            shutil.rmtree(str(PAUSE_PATH / mod_id), ignore_errors=True)
            return jsonify({'success': False, 'error': str(e)}), 500

        if not is_draft:
            catalog = _load_pause_catalog()
            catalog.setdefault('mods', []).append({
                'id': mod_id,
                'name': name,
                'description': '',
                'source': 'custom',
                'created': mod['created'],
            })
            _save_pause_catalog(catalog)

        logger.info(f'[OK] Created {"draft " if is_draft else ""}pause mod: {name} ({mod_id})')
        return jsonify({'success': True, 'mod': _attach_pause_urls(mod), 'draft': is_draft})
    except Exception as e:
        logger.error(f'Create pause mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/save', methods=['POST'])
def save_pause_mod(mod_id):
    """Commit a draft to the vault and/or rename a mod. Body: {name?}.

    Used by the edit modal's Save: for a draft it adds the catalog entry (the
    edits already live in the mod folder); for an existing mod it just updates
    the name."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.get_json(silent=True) or {}
        name = (payload.get('name') or '').strip()
        if name:
            mod['name'] = name
        mod.pop('draft', None)
        save_mod_json(PAUSE_PATH, mod_id, mod)

        catalog = _load_pause_catalog()
        mods = catalog.setdefault('mods', [])
        entry = next((m for m in mods if m.get('id') == mod_id), None)
        if entry is None:
            mods.append({
                'id': mod_id,
                'name': mod['name'],
                'description': mod.get('description', ''),
                'source': mod.get('source', 'custom'),
                'created': mod.get('created'),
            })
        else:
            entry['name'] = mod['name']
        _save_pause_catalog(catalog)

        logger.info(f'[OK] Saved pause mod: {mod["name"]} ({mod_id})')
        return jsonify({'success': True, 'mod': _attach_pause_urls(mod)})
    except Exception as e:
        logger.error(f'Save pause mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/discard', methods=['POST'])
def discard_pause_draft(mod_id):
    """Discard an uncommitted draft (delete its folder). No-op for mods that
    are already in the catalog, so it's safe to call on editor exit."""
    try:
        catalog = _load_pause_catalog()
        if any(m.get('id') == mod_id for m in catalog.get('mods', [])):
            return jsonify({'success': True, 'committed': True})
        mod_dir = PAUSE_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(str(mod_dir), ignore_errors=True)
        logger.info(f'[OK] Discarded pause draft: {mod_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Discard pause draft error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/textures', methods=['GET'])
def list_pause_textures(mod_id):
    """Full per-slot texture listing for the editor. Seeds picture-only mods
    with the vanilla texture set on first call."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        try:
            mod = _ensure_textures(mod)
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

        out = []
        for tex in mod.get('textures', []):
            out.append({
                'index': tex['index'],
                'width': tex['width'],
                'height': tex['height'],
                'format': tex['format'],
                'replaced': bool(tex.get('replaced')),
                'url': f"/api/mex/menus/pause/texture/{mod_id}/{tex['index']}",
            })
        return jsonify({'success': True, 'textures': out, 'mod': _attach_pause_urls(mod)})
    except Exception as e:
        logger.error(f'List pause textures error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/texture/<mod_id>/<int:index>', methods=['GET'])
def get_pause_texture(mod_id, index):
    try:
        tex_path = PAUSE_PATH / mod_id / 'textures' / f't{index}.png'
        if not tex_path.exists():
            # Not seeded yet (or never edited): fall back to the vanilla texture
            tex_path = VANILLA_TEX_DIR() / f't{index}.png'
        if not tex_path.exists():
            return jsonify({'success': False, 'error': 'Texture not found'}), 404
        return send_file(str(tex_path), mimetype='image/png', max_age=0)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/replace_texture', methods=['POST'])
def replace_pause_texture(mod_id):
    """Replace a single texture slot with an uploaded image.
    Multipart form: index + file. The first replacement of a slot backs up the
    previous texture (t<i>.orig.png) so it can be reverted."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        try:
            index = int(request.form.get('index', ''))
        except ValueError:
            return jsonify({'success': False, 'error': 'index is required'}), 400
        if 'file' not in request.files or not request.files['file'].filename:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        try:
            mod = _ensure_textures(mod)
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

        entry = next((t for t in mod['textures'] if t['index'] == index), None)
        if entry is None:
            return jsonify({'success': False, 'error': f'No texture slot {index}'}), 404

        # The game draws the two 88x72 main-graphic slots layered at the same
        # position; replacing only one leaves the vanilla icon on top of the
        # new image, so a main-slot edit applies to the whole pair.
        main_pair = _main_pair_indices(mod)
        indices = main_pair if index in main_pair else [index]

        tex_dir = PAUSE_PATH / mod_id / 'textures'
        upload = request.files['file'].read()
        for idx in indices:
            pair_entry = next(t for t in mod['textures'] if t['index'] == idx)
            tex_path = tex_dir / pair_entry['file']
            orig_path = tex_dir / f't{idx}.orig.png'
            if tex_path.exists() and not orig_path.exists():
                shutil.copy(str(tex_path), str(orig_path))
                pair_entry['orig_replaced'] = bool(pair_entry.get('replaced'))
            file_retry.retry_locked(tex_path.write_bytes, upload)
            pair_entry['replaced'] = True
        save_mod_json(PAUSE_PATH, mod_id, mod)

        logger.info(f'[OK] Replaced pause texture t{index} on mod {mod_id}'
                    + (f' (paired: {indices})' if len(indices) > 1 else ''))
        return jsonify({'success': True, 'index': index,
                        'url': f'/api/mex/menus/pause/texture/{mod_id}/{index}'})
    except Exception as e:
        logger.error(f'Replace pause texture error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/revert_texture', methods=['POST'])
def revert_pause_texture(mod_id):
    """Undo a user texture replacement. Body: {index}. Restores the backed-up
    original when one exists, otherwise the vanilla texture."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        payload = request.get_json(silent=True) or {}
        try:
            index = int(payload.get('index'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'index is required'}), 400

        entry = next((t for t in mod.get('textures', []) if t['index'] == index), None)
        if entry is None:
            return jsonify({'success': False, 'error': f'No texture slot {index}'}), 404

        # Main-graphic slots are edited as a pair (see replace_pause_texture).
        main_pair = _main_pair_indices(mod)
        indices = main_pair if index in main_pair else [index]

        tex_dir = PAUSE_PATH / mod_id / 'textures'
        for idx in indices:
            pair_entry = next(t for t in mod['textures'] if t['index'] == idx)
            tex_path = tex_dir / pair_entry['file']
            orig_path = tex_dir / f't{idx}.orig.png'

            if orig_path.exists():
                file_retry.retry_locked(shutil.move, str(orig_path), str(tex_path))
                pair_entry['replaced'] = pair_entry.pop('orig_replaced', False)
            else:
                vanilla_tex = VANILLA_TEX_DIR() / f't{idx}.png'
                if not vanilla_tex.exists():
                    return jsonify({'success': False, 'error': 'Nothing to revert to'}), 400
                file_retry.retry_locked(shutil.copy, str(vanilla_tex), str(tex_path))
                pair_entry['replaced'] = False
                pair_entry.pop('orig_replaced', None)
        save_mod_json(PAUSE_PATH, mod_id, mod)

        logger.info(f'[OK] Reverted pause texture t{index} on mod {mod_id}')
        return jsonify({'success': True, 'index': index,
                        'url': f'/api/mex/menus/pause/texture/{mod_id}/{index}'})
    except Exception as e:
        logger.error(f'Revert pause texture error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/delete/<mod_id>', methods=['POST'])
def delete_pause_mod(mod_id):
    try:
        catalog = _load_pause_catalog()
        mods = catalog.get('mods', [])
        idx = next((i for i, m in enumerate(mods) if m.get('id') == mod_id), -1)
        if idx < 0:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404

        mod_dir = PAUSE_PATH / mod_id
        if mod_dir.exists():
            shutil.rmtree(str(mod_dir), ignore_errors=True)

        mods.pop(idx)
        _save_pause_catalog(catalog)
        logger.info(f'[OK] Deleted pause mod: {mod_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'Delete pause mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/screenshot', methods=['POST'])
def upload_pause_screenshot(mod_id):
    """Replace a pause mod's preview screenshot with an uploaded image."""
    try:
        if not load_mod_json(PAUSE_PATH, mod_id):
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        f = request.files.get('screenshot') or request.files.get('file')
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400
        set_mod_screenshot(mod_id, f.read())
        return jsonify({'success': True, 'imageUrl': f'/api/mex/menus/pause/image/{mod_id}'})
    except Exception as e:
        logger.error(f'Upload pause screenshot error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@menus_bp.route('/api/mex/menus/pause/<mod_id>/export', methods=['GET'])
def export_pause_mod(mod_id):
    """Download a pause mod's files as a zip."""
    try:
        mod = load_mod_json(PAUSE_PATH, mod_id)
        if not mod:
            return jsonify({'success': False, 'error': 'Mod not found'}), 404
        return send_mod_zip(PAUSE_PATH / mod_id, mod.get('name') or mod_id)
    except Exception as e:
        logger.error(f'Export pause mod error: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


