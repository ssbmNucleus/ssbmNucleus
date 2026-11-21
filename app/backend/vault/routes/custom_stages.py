"""
Custom Stages Blueprint - Manage m-ex custom stages in the vault.

Custom stages are entirely new stages (not DAS texture variants). They come in
through the unified import (/api/mex/import/file: MexManager-exported ZIP
packages) or the m-ex content ISO scan (/api/mex/scan-iso/mex-content, in the
custom characters blueprint). Each stage is stored as:

    storage/custom_stages/<slug>/
        stage.zip       (original ZIP preserved for re-export)
        icon.png        (extracted for fast serving)
        banner.png      (extracted for detail view)
        stage.json      (extracted metadata)

Metadata is tracked under metadata.json["custom_stages"] (list of objects).

Installing stages into the open project, removing them and listing the ones it
carries are in projects/routes/custom_stages.py, on this same
`custom_stages_bp`; the index reads both share are vault/catalog/custom_stages.py.
"""

import json
import re
import shutil
import tempfile
import uuid
import zipfile
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file

import file_retry
import mexcli.commands
from core.images import normalized_png
# Where the vault keeps stages is owned by the vault import engine.
from vault.importing.custom_stage_package import CUSTOM_STAGES_PATH
from vault.catalog.custom_stages import _find_stage_entry, _is_folder, _read_metadata
from vault.catalog.custom_stages import _write_metadata

logger = logging.getLogger(__name__)

custom_stages_bp = Blueprint('custom_stages', __name__)

CUSTOM_STAGES_PATH.mkdir(parents=True, exist_ok=True)


def _find_folder(items, folder_id):
    for i, item in enumerate(items):
        if _is_folder(item) and item.get('id') == folder_id:
            return item, i
    return None, -1


def _folder_id_at_position(items, position):
    """Determine folder membership for a stage placed at `position`.

    Mirrors get_folder_id_at_position from storage_costumes: look backwards
    until we find either a folder header (we're in it) or a root-level stage
    (we're at root).
    """
    for i in range(position - 1, -1, -1):
        item = items[i]
        if _is_folder(item):
            return item['id']
        if item.get('folder_id'):
            return item['folder_id']
        return None
    return None


@custom_stages_bp.route('/api/mex/custom-stages/list', methods=['GET'])
def list_custom_stages():
    try:
        metadata = _read_metadata()
        items = metadata.get('custom_stages', [])
        for item in items:
            if _is_folder(item):
                continue
            # Stages keep slug as their stable identifier, but the frontend
            # drag/drop code uses `id` uniformly. Mirror slug → id.
            item['id'] = item.get('slug')
            item['icon_url'] = f"/api/mex/custom-stages/{item['slug']}/icon"
        return jsonify({'success': True, 'stages': items})
    except Exception as e:
        logger.error(f"List custom stages error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/icon', methods=['GET'])
def get_custom_stage_icon(slug):
    icon_path = CUSTOM_STAGES_PATH / slug / 'icon.png'
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Icon not found'}), 404


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/banner', methods=['GET'])
def get_custom_stage_banner(slug):
    banner_path = CUSTOM_STAGES_PATH / slug / 'banner.png'
    if banner_path.exists():
        return send_file(banner_path, mimetype='image/png')
    return jsonify({'success': False, 'error': 'Banner not found'}), 404


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/audio/track/<int:index>', methods=['GET'])
def get_stage_track_audio(slug, index):
    """Decode a stage playlist track (extracted at scan) to WAV."""
    stage_dir = CUSTOM_STAGES_PATH / slug
    cache = stage_dir / 'audio_cache' / f'track_{index}.wav'
    if not cache.exists():
        hps = stage_dir / f'music_{index}.hps'
        if not hps.exists():
            return jsonify({'success': False, 'error': 'Track not extracted — rescan the source ISO'}), 404
        cache.parent.mkdir(exist_ok=True)
        out = mexcli.commands.run_json(['hps-to-wav', hps, cache])
        if not out.get('success') or not cache.exists():
            return jsonify({'success': False, 'error': out.get('error', 'HPS decode failed')}), 500
    return send_file(cache, mimetype='audio/wav')


# ============= Playlist editing (vault-level; ported on install) =============

# Formats MexCLI audio-to-hps decodes directly. The frontend uploads the
# original file; every format takes the same validation/normalization path.
MUSIC_IMPORT_EXTS = {
    '.wav', '.mp3', '.ogg', '.m4a', '.flac', '.hps', '.brstm', '.dsp',
}


def _invalidate_track_cache(stage_dir):
    cache_dir = stage_dir / 'audio_cache'
    if cache_dir.exists():
        for f in cache_dir.glob('track_*.wav'):
            f.unlink(missing_ok=True)


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/playlist', methods=['GET'])
def get_stage_playlist(slug):
    """List the stage's vault playlist (what install ports into a build)."""
    metadata = _read_metadata()
    entry = _find_stage_entry(metadata, slug)
    if entry is None:
        return jsonify({'success': False, 'error': 'Stage not found'}), 404
    stage_dir = CUSTOM_STAGES_PATH / slug
    tracks = []
    for i, t in enumerate(entry.get('playlist') or []):
        tracks.append({
            'index': i,
            'name': t.get('name') or f'track_{i}',
            'chance': t.get('chance', 50),
            'has_file': (stage_dir / f'music_{i}.hps').exists(),
            'url': f"/api/mex/custom-stages/{slug}/audio/track/{i}",
        })
    return jsonify({'success': True, 'tracks': tracks})


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/playlist/add', methods=['POST'])
def add_stage_track(slug):
    """Add a validated, loop-normalized song to the stage's playlist."""
    try:
        metadata = _read_metadata()
        entry = _find_stage_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Stage not found'}), 404
        stage_dir = CUSTOM_STAGES_PATH / slug
        stage_dir_existed = stage_dir.exists()

        file = request.files.get('file')
        if file is None or not file.filename:
            return jsonify({'success': False, 'error': 'No audio file uploaded'}), 400
        ext = Path(file.filename).suffix.lower()
        if ext not in MUSIC_IMPORT_EXTS:
            return jsonify({'success': False,
                            'error': f"Unsupported format '{ext}' — use one of: "
                                     + ', '.join(sorted(MUSIC_IMPORT_EXTS))}), 400

        name = (request.form.get('name') or '').strip() or Path(file.filename).stem
        try:
            chance = max(0, min(100, int(request.form.get('chance', 50))))
        except ValueError:
            chance = 50

        playlist = entry.setdefault('playlist', [])
        index = len(playlist)
        hps_path = stage_dir / f'music_{index}.hps'
        if hps_path.exists():
            return jsonify({'success': False,
                            'error': f'Track file {hps_path.name} already exists; rescan or repair the stage'}), 409

        # Native HPS must take the same path as WAV/DSP/BRSTM: the converter
        # validates it and rewrites it with normalized stereo/loop metadata.
        # Its output stays temporary until it is known-good, so a failed tool
        # cannot leave a partial music_N.hps in the vault.
        with tempfile.TemporaryDirectory() as td:
            upload = Path(td) / f'upload{ext}'
            normalized = Path(td) / 'normalized.hps'
            file.save(upload)
            out = mexcli.commands.run_json(['audio-to-hps', upload, normalized])
            if not out.get('success') or not normalized.exists():
                return jsonify({'success': False,
                                'error': out.get('error', 'Audio conversion failed')}), 400
            stage_dir.mkdir(parents=True, exist_ok=True)
            file_retry.replace(normalized, hps_path)

        playlist.append({'name': name, 'chance': chance})
        try:
            _write_metadata(metadata)
        except Exception:
            # Keep the file and metadata as one logical commit. This index is
            # newly allocated, so removing it cannot disturb another track.
            playlist.pop()
            hps_path.unlink(missing_ok=True)
            if not stage_dir_existed:
                try:
                    stage_dir.rmdir()
                except OSError:
                    pass
            raise
        _invalidate_track_cache(stage_dir)

        logger.info(f"[OK] Added track '{name}' to custom stage '{slug}'")
        return jsonify({'success': True, 'track': {
            'index': index, 'name': name, 'chance': chance, 'has_file': True,
            'url': f"/api/mex/custom-stages/{slug}/audio/track/{index}",
        }})
    except Exception as e:
        logger.error(f"Add stage track error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/playlist/<int:index>/update', methods=['POST'])
def update_stage_track(slug, index):
    """Update a track's name and/or play chance (%)."""
    try:
        metadata = _read_metadata()
        entry = _find_stage_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Stage not found'}), 404
        playlist = entry.get('playlist') or []
        if not (0 <= index < len(playlist)):
            return jsonify({'success': False, 'error': f'Track {index} out of range'}), 404

        data = request.get_json(silent=True) or {}
        if 'chance' in data:
            try:
                playlist[index]['chance'] = max(0, min(100, int(data['chance'])))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'chance must be a number 0..100'}), 400
        if isinstance(data.get('name'), str) and data['name'].strip():
            playlist[index]['name'] = data['name'].strip()

        _write_metadata(metadata)
        return jsonify({'success': True, 'track': {'index': index, **playlist[index]}})
    except Exception as e:
        logger.error(f"Update stage track error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/playlist/<int:index>/remove', methods=['POST'])
def remove_stage_track(slug, index):
    """Remove a track and renumber the music_N.hps files after it."""
    try:
        metadata = _read_metadata()
        entry = _find_stage_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Stage not found'}), 404
        playlist = entry.get('playlist') or []
        if not (0 <= index < len(playlist)):
            return jsonify({'success': False, 'error': f'Track {index} out of range'}), 404

        stage_dir = CUSTOM_STAGES_PATH / slug
        (stage_dir / f'music_{index}.hps').unlink(missing_ok=True)
        for j in range(index + 1, len(playlist)):
            src = stage_dir / f'music_{j}.hps'
            if src.exists():
                src.rename(stage_dir / f'music_{j - 1}.hps')

        playlist.pop(index)
        _write_metadata(metadata)
        _invalidate_track_cache(stage_dir)

        logger.info(f"[OK] Removed track {index} from custom stage '{slug}'")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Remove stage track error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============= Stage assets (vault editing) =============

# fixed entry names + canonical sizes from MexStageAssets
STAGE_ASSET_SPECS = {
    'icon': ('icon.png', (64, 56)),
    'banner': ('banner.png', (224, 56)),
}


def _set_stage_zip_entry(zip_path, entry_name, new_bytes):
    """Replace the stage.zip entry whose basename matches, or add it at the
    root if absent. add-stage (MexStage.FromPackage) reads assets by these
    fixed names, so vault-side asset edits must land here to survive install."""
    tmp = zip_path.with_suffix('.tmp')
    matched = False
    with zipfile.ZipFile(zip_path) as zin, \
            zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename.split('/')[-1].lower() == entry_name:
                zout.writestr(item, new_bytes)
                matched = True
            else:
                zout.writestr(item, zin.read(item.filename))
        if not matched:
            zout.writestr(entry_name, new_bytes)
    file_retry.replace(tmp, zip_path)


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/replace-asset/<which>', methods=['POST'])
def replace_stage_asset(slug, which):
    """Replace the SSS icon or banner with an uploaded image. Writes both the
    vault display copy and the stage.zip entry (what installs read)."""
    try:
        spec = STAGE_ASSET_SPECS.get(which)
        if spec is None:
            return jsonify({'success': False, 'error': f'Unknown asset {which}'}), 400
        entry_name, size = spec

        metadata = _read_metadata()
        entry = _find_stage_entry(metadata, slug)
        if entry is None:
            return jsonify({'success': False, 'error': 'Stage not found'}), 404
        stage_dir = CUSTOM_STAGES_PATH / slug
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        raw = request.files['file'].read()
        try:
            png = normalized_png(raw, size)
        except Exception:
            return jsonify({'success': False, 'error': 'File is not a valid image'}), 400

        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / entry_name).write_bytes(png)
        zip_path = stage_dir / 'stage.zip'
        if zip_path.exists():
            _set_stage_zip_entry(zip_path, entry_name, png)

        entry[f'has_{which}'] = True
        _write_metadata(metadata)

        logger.info(f"[OK] Replaced {which} asset for custom stage '{slug}'")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Replace stage asset error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/delete', methods=['POST'])
def delete_custom_stage(slug):
    try:
        stage_dir = CUSTOM_STAGES_PATH / slug
        if stage_dir.exists():
            shutil.rmtree(stage_dir)

        metadata = _read_metadata()
        metadata['custom_stages'] = [
            s for s in metadata.get('custom_stages', []) if s.get('slug') != slug
        ]
        _write_metadata(metadata)

        logger.info(f"[OK] Deleted custom stage '{slug}'")
        return jsonify({'success': True, 'message': f'Deleted {slug}'})
    except Exception as e:
        logger.error(f"Delete custom stage error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/rename', methods=['POST'])
def rename_custom_stage(slug):
    try:
        data = request.json
        new_name = data.get('newName', '').strip()
        if not new_name:
            return jsonify({'success': False, 'error': 'New name is required'}), 400

        metadata = _read_metadata()

        for existing in metadata.get('custom_stages', []):
            if _is_folder(existing):
                continue
            if existing.get('slug') != slug and existing.get('name', '').lower() == new_name.lower():
                return jsonify({'success': False, 'error': f"A stage named '{existing['name']}' already exists"}), 400

        stage_entry = None
        for s in metadata.get('custom_stages', []):
            if _is_folder(s):
                continue
            if s.get('slug') == slug:
                s['name'] = new_name
                stage_entry = s
                break

        if not stage_entry:
            return jsonify({'success': False, 'error': f'Stage {slug} not found'}), 404

        stage_json_path = CUSTOM_STAGES_PATH / slug / 'stage.json'
        if stage_json_path.exists():
            with open(stage_json_path, 'r') as f:
                stage_data = json.load(f)
            stage_data['name'] = new_name
            with file_retry.retry_locked(open, stage_json_path, 'w') as f:
                json.dump(stage_data, f, indent=2)

        _write_metadata(metadata)

        logger.info(f"[OK] Renamed custom stage '{slug}' to '{new_name}'")
        return jsonify({'success': True, 'stage': stage_entry})
    except Exception as e:
        logger.error(f"Rename custom stage error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/<slug>/export', methods=['GET'])
def export_custom_stage(slug):
    stage_dir = CUSTOM_STAGES_PATH / slug
    zip_path = stage_dir / 'stage.zip'
    if zip_path.exists():
        try:
            metadata = _read_metadata()
            entry = _find_stage_entry(metadata, slug)
            if entry is None:
                return jsonify({'success': False, 'error': 'Stage not found'}), 404
            package = _serialize_custom_stage_export(stage_dir, entry)
            return send_file(package, as_attachment=True,
                             download_name=f'{slug}.zip', mimetype='application/zip')
        except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as e:
            logger.error(f"Custom stage export error for '{slug}': {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': False, 'error': 'Stage ZIP not found (imported from project scan?)'}), 404


def _serialize_custom_stage_export(stage_dir, entry):
    """Build a package from the original assets and current vault metadata."""
    import io

    source_path = stage_dir / 'stage.zip'
    current_json = stage_dir / 'stage.json'
    with open(current_json, 'r', encoding='utf-8') as f:
        stage_data = json.load(f)
    if not isinstance(stage_data, dict):
        raise ValueError('stage.json must contain an object')

    # These names match MexJsonSerializer's camel-case MexStage/MexPlaylist
    # fields. Extra name/fileName fields are ignored by native MexStage readers,
    # while retaining enough information for a Nucleus round trip.
    stage_data['name'] = entry.get('name') or stage_data.get('name', '')
    playlist_entries = []
    for index, track in enumerate(entry.get('playlist') or []):
        try:
            chance = max(0, min(100, int(track.get('chance', 50))))
        except (TypeError, ValueError):
            chance = 50
        hps_name = f'music_{index}.hps'
        playlist_entry = {
            'musicID': index,
            'chanceToPlay': chance,
            'name': track.get('name') or f'track_{index}',
        }
        if (stage_dir / hps_name).is_file():
            playlist_entry['fileName'] = hps_name
        playlist_entries.append(playlist_entry)
    stage_data['playlist'] = {'entries': playlist_entries}

    output = io.BytesIO()
    with zipfile.ZipFile(source_path, 'r') as source, \
            zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename == 'stage.json':
                continue
            if re.fullmatch(r'music_\d+\.hps', info.filename, re.IGNORECASE):
                continue
            target.writestr(info, source.read(info.filename))
        target.writestr('stage.json', json.dumps(stage_data, indent=2))
        for index, _track in enumerate(entry.get('playlist') or []):
            hps = stage_dir / f'music_{index}.hps'
            if hps.is_file():
                target.write(hps, hps.name)
    output.seek(0)
    return output


# ============= Reorder + Folder Endpoints =============

@custom_stages_bp.route('/api/mex/custom-stages/reorder', methods=['POST'])
def reorder_custom_stages():
    """Reorder items (stages or folders) in the custom_stages list."""
    try:
        data = request.json or {}
        from_index = data.get('fromIndex')
        to_index = data.get('toIndex')

        if from_index is None or to_index is None:
            return jsonify({'success': False, 'error': 'Missing fromIndex or toIndex'}), 400

        metadata = _read_metadata()
        items = metadata.get('custom_stages', [])

        if from_index < 0 or from_index >= len(items) or to_index < 0 or to_index >= len(items):
            return jsonify({'success': False, 'error': 'Invalid fromIndex or toIndex'}), 400

        item = items.pop(from_index)
        items.insert(to_index, item)

        # Update folder membership for stages (not folders)
        if not _is_folder(item):
            new_folder_id = _folder_id_at_position(items, to_index)
            if new_folder_id:
                item['folder_id'] = new_folder_id
            elif 'folder_id' in item:
                del item['folder_id']

        metadata['custom_stages'] = items
        _write_metadata(metadata)

        logger.info(f"[OK] Reordered custom stages: {from_index} -> {to_index}")
        return jsonify({'success': True, 'stages': items})
    except Exception as e:
        logger.error(f"Reorder custom stages error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/folders/create', methods=['POST'])
def create_custom_stage_folder():
    try:
        data = request.json or {}
        name = data.get('name', 'New Folder')

        metadata = _read_metadata()
        items = metadata.setdefault('custom_stages', [])

        folder_id = f"folder_{uuid.uuid4().hex[:8]}"
        new_folder = {'type': 'folder', 'id': folder_id, 'name': name, 'expanded': True}
        items.append(new_folder)

        _write_metadata(metadata)
        logger.info(f"[OK] Created custom-stage folder '{name}'")
        return jsonify({'success': True, 'folder': new_folder})
    except Exception as e:
        logger.error(f"Create custom-stage folder error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/folders/rename', methods=['POST'])
def rename_custom_stage_folder():
    try:
        data = request.json or {}
        folder_id = data.get('folderId')
        new_name = data.get('newName')

        if not folder_id or not new_name:
            return jsonify({'success': False, 'error': 'Missing folderId or newName'}), 400

        metadata = _read_metadata()
        items = metadata.get('custom_stages', [])

        folder, _idx = _find_folder(items, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        folder['name'] = new_name
        _write_metadata(metadata)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Rename custom-stage folder error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/folders/delete', methods=['POST'])
def delete_custom_stage_folder():
    """Delete a folder. Stages inside lose their folder_id but are kept."""
    try:
        data = request.json or {}
        folder_id = data.get('folderId')
        if not folder_id:
            return jsonify({'success': False, 'error': 'Missing folderId'}), 400

        metadata = _read_metadata()
        items = metadata.get('custom_stages', [])

        folder, folder_idx = _find_folder(items, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        for it in items:
            if not _is_folder(it) and it.get('folder_id') == folder_id:
                del it['folder_id']

        items.pop(folder_idx)
        _write_metadata(metadata)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Delete custom-stage folder error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/set-folder', methods=['POST'])
def set_custom_stage_folder():
    """Assign or unassign a custom stage to a folder (drag-into-folder)."""
    try:
        data = request.json or {}
        stage_id = data.get('stageId')
        folder_id = data.get('folderId')

        if not stage_id:
            return jsonify({'success': False, 'error': 'Missing stageId'}), 400

        metadata = _read_metadata()
        items = metadata.get('custom_stages', [])

        # Custom-stage entries are keyed by 'slug' (no 'id' field); the grid
        # sends the slug as stageId. Match either so drag-into-folder works.
        stage = next((it for it in items if not _is_folder(it)
                      and (it.get('slug') == stage_id or it.get('id') == stage_id)), None)
        if not stage:
            return jsonify({'success': False, 'error': f'Stage {stage_id} not found'}), 404

        if folder_id:
            folder, _idx = _find_folder(items, folder_id)
            if not folder:
                return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404
            stage['folder_id'] = folder_id
        elif 'folder_id' in stage:
            del stage['folder_id']

        _write_metadata(metadata)
        logger.info(f"[OK] Set custom stage {stage_id} folder to {folder_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Set custom-stage folder error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/folders/toggle', methods=['POST'])
def toggle_custom_stage_folder():
    try:
        data = request.json or {}
        folder_id = data.get('folderId')
        if not folder_id:
            return jsonify({'success': False, 'error': 'Missing folderId'}), 400

        metadata = _read_metadata()
        items = metadata.get('custom_stages', [])
        folder, _idx = _find_folder(items, folder_id)
        if not folder:
            return jsonify({'success': False, 'error': f'Folder {folder_id} not found'}), 404

        folder['expanded'] = not folder.get('expanded', True)
        _write_metadata(metadata)
        return jsonify({'success': True, 'expanded': folder['expanded']})
    except Exception as e:
        logger.error(f"Toggle custom-stage folder error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# The project half of this blueprint (stages in the open project: list,
# install, batch install, remove) lives in projects/routes/custom_stages.py and
# adds its routes to custom_stages_bp. Importing it here makes the blueprint
# complete before anything registers it: Flask refuses routes added after
# registration.
from projects.routes import custom_stages as _project_routes  # noqa: E402,F401
