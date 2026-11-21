"""
Viewer Blueprint - 3D model viewer endpoints.

Resolves the files the 3D model viewer opens; the frontend launches the viewer
itself through /viewer/paths*.
"""

import os
import re
import base64
import time
import shutil
import threading
import zipfile
import tempfile
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify

from core.config import STORAGE_PATH, VANILLA_ASSETS_DIR, LOGS_PATH
from core.constants import VANILLA_CSS_COLOR_ORDER
from core.costume_files import find_costume_archive_name
from core.viewer_tools import (
    custom_character_based_on, extract_custom_character_aj, extract_custom_character_data,
    find_aj_file, find_fighter_data_file, find_scene_file,
    find_vanilla_costume_file,
)

logger = logging.getLogger(__name__)

viewer_bp = Blueprint('viewer', __name__)


def to_windows_path(path):
    """Convert paths for Windows if running in WSL"""
    path_str = str(path)
    if os.name != 'nt' and path_str.startswith('/mnt/'):
        # Convert WSL path to Windows path
        drive = path_str[5].upper()
        return f"{drive}:{path_str[6:]}".replace('/', '\\')
    return path_str


def extract_costume_archive(zip_path, temp_prefix):
    """Extract the primary costume archive from a storage ZIP into a temp directory (a viewer folder of this
    backend's, ``_new_viewer_folder``)."""
    temp_dir = _new_viewer_folder(temp_prefix)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        archive_name = find_costume_archive_name(zf.namelist())
        if not archive_name:
            return temp_dir, None

        zf.extract(archive_name, temp_dir)
        return temp_dir, temp_dir / archive_name


def _texture_models(dat_path, data_path, character, costume_code=None):
    """Which model -- high-poly, low-poly or both -- draws each texture the viewer
    will list for this costume (shared.rendering.lowpoly.texture_models), so the
    Skin Creator can section its texture list. The costume slot comes from the
    costume code (the DAT's own name when none is given). None when unknown:
    the editor then shows one list."""
    if not dat_path or not data_path:
        return None
    try:   # an extra for the editor: never the reason a viewer cannot open
        from shared.rendering.lowpoly import texture_models
        from shared.rendering.lowpoly_promote import costume_slot_for_code
        code = costume_code if isinstance(costume_code, str) and costume_code else Path(dat_path).name
        match = re.match(r'^Pl[A-Za-z]{2}([A-Za-z]{2})', code)
        slot = costume_slot_for_code(character, match.group(1)) if match else 0
        return texture_models(dat_path, data_path, slot)
    except Exception:
        logger.info('[viewer] no texture models for %s', dat_path, exc_info=True)
        return None


def _paint_members(dat_path, *, costume_id=None, output_dir=None, include_bytes=True):
    """Pair paths for every preview; original bytes are included only for painting."""
    from shared.rendering.paint_pair import find_paint_partner
    from core.metadata import load_metadata
    partner = find_paint_partner(
        dat_path, find_vanilla=find_vanilla_costume_file, storage_root=STORAGE_PATH,
        costume_id=costume_id,
        metadata=load_metadata(default={}) if costume_id else None,
        output_dir=output_dir,
    )
    popo, nana = (dat_path, partner) if dat_path.name.lower().startswith('plpp') else (partner, dat_path)
    members = []
    for label, character, path in [('Popo', 'Ice Climbers', popo), ('Nana', 'Nana', nana)]:
        scene = find_scene_file(f'Ice Climbers ({label})') or find_scene_file(character)
        aj = find_aj_file(character)
        data = find_fighter_data_file(character)
        members.append({
            'memberId': label.lower(), 'name': label, 'datName': path.name,
            **({'datBase64': base64.b64encode(path.read_bytes()).decode('ascii')} if include_bytes else {}),
            'datFile': to_windows_path(path),
            'sceneFile': to_windows_path(scene) if scene else None,
            'ajFile': to_windows_path(aj) if aj else None,
            'dataFile': to_windows_path(data) if data else None,
            'logsPath': to_windows_path(LOGS_PATH),
            **({'textureModels': _texture_models(path, data, character)} if include_bytes else {}),
        })
    return members


@viewer_bp.route('/api/viewer/paths', methods=['POST'])
def get_viewer_paths():
    """Get file paths for embedded 3D viewer (no streaming, just paths for Electron IPC)"""
    try:
        data = request.json
        character = data.get('character')
        skin_id = data.get('skinId')

        if not character or not skin_id:
            return jsonify({'success': False, 'error': 'Missing character or skinId'}), 400

        # Find the costume in metadata
        from core.metadata import load_metadata
        metadata = load_metadata(default=None)
        if metadata is None:
            return jsonify({'success': False, 'error': 'No costumes in storage'}), 404

        # Find the costume (canonical character, or a custom character's
        # skin library via the 'custom_characters/<slug>/skins' pseudo key)
        from core.metadata import get_char_data, custom_character_slug
        char_data = get_char_data(metadata, character)
        if char_data is None:
            return jsonify({'success': False, 'error': f'Character {character} not found'}), 404

        skins = char_data.get('skins', [])
        costume = None
        for skin in skins:
            if skin.get('id') == skin_id:
                costume = skin
                break

        if costume is None:
            return jsonify({'success': False, 'error': f'Costume {skin_id} not found'}), 404

        # Get the ZIP file path
        zip_path = STORAGE_PATH / character / costume['filename']
        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume file not found: {zip_path}'}), 404

        temp_dir, dat_path = extract_costume_archive(zip_path, VIEWER_PREFIX)
        if dat_path is None or not dat_path.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({'success': False, 'error': 'No costume archive found in costume ZIP'}), 404

        # Convert paths
        dat_windows_path = to_windows_path(dat_path)
        logs_windows_path = to_windows_path(LOGS_PATH)

        # Find scene file
        scene_path = find_scene_file(character)

        # Find AJ file
        aj_path = find_aj_file(character)

        # Custom characters: animations come from their own AJ inside
        # fighter.zip; the scene config falls back to the donor skeleton
        slug = custom_character_slug(character)
        if slug:
            if aj_path is None:
                aj_path = extract_custom_character_aj(slug)
            if scene_path is None:
                based_on = custom_character_based_on(slug)
                if based_on:
                    scene_path = find_scene_file(based_on)

        scene_windows_path = to_windows_path(scene_path) if scene_path else None
        aj_windows_path = to_windows_path(aj_path) if aj_path else None

        # fighter-data dat (ftData) -> per-animation mesh-part visibility
        data_path = find_fighter_data_file(character) or (
            extract_custom_character_data(slug) if slug else None)
        data_windows_path = to_windows_path(data_path) if data_path else None

        return jsonify({
            'success': True,
            'datFile': dat_windows_path,
            'sceneFile': scene_windows_path,
            'ajFile': aj_windows_path,
            'dataFile': data_windows_path,
            'logsPath': logs_windows_path,
            **({'members': _paint_members(dat_path, costume_id=skin_id, output_dir=temp_dir,
                                         include_bytes=bool(data.get('paintPair')))}
               if character in ('Ice Climbers', 'Nana') else {}),
            'tempDir': str(temp_dir)  # For cleanup later if needed
        })

    except Exception as e:
        logger.error(f"Get viewer paths error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@viewer_bp.route('/api/mex/viewer/paths-vanilla', methods=['POST'])
def get_viewer_paths_vanilla():
    """Get file paths for vanilla costume viewer (Electron IPC, no spawning)"""
    try:
        data = request.json
        character = data.get('character')
        costume_code = data.get('costumeCode')  # e.g., "PlFxNr"

        if not character or not costume_code:
            return jsonify({'success': False, 'error': 'Missing character or costumeCode'}), 400

        dat_path = find_vanilla_costume_file(character, costume_code)
        if not dat_path or not dat_path.exists():
            return jsonify({'success': False, 'error': f'Vanilla costume not found: {dat_path}'}), 404

        dat_windows_path = to_windows_path(dat_path)
        logs_windows_path = to_windows_path(LOGS_PATH)

        # Find scene file
        scene_path = find_scene_file(character)
        scene_windows_path = to_windows_path(scene_path) if scene_path else None

        # Find AJ file
        aj_path = find_aj_file(character)
        aj_windows_path = to_windows_path(aj_path) if aj_path else None

        # fighter-data dat (ftData) -> per-animation mesh-part visibility
        data_path = find_fighter_data_file(character)
        data_windows_path = to_windows_path(data_path) if data_path else None

        return jsonify({
            'success': True,
            **({'members': _paint_members(dat_path, include_bytes=bool(data.get('paintPair')))}
               if character in ('Ice Climbers', 'Nana') else {}),
            'datFile': dat_windows_path,
            'sceneFile': scene_windows_path,
            'ajFile': aj_windows_path,
            'dataFile': data_windows_path,
            'logsPath': logs_windows_path,
            'textureModels': _texture_models(dat_path, data_path, character, costume_code),
        })

    except Exception as e:
        logger.error(f"Get vanilla viewer paths error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# Every viewer open puts the file it shows in a fresh temp folder of the data scratch: a
# vault costume taken out of its ZIP (``viewer_<8>``: /api/viewer/paths; ``viewer_vault_<8>``:
# paths-vault), or a workbench load's copy of its working DAT (``viewer_checkpoint_<8>``; the
# renderer holds its file open, so a running viewer and the next one never share a copy).
# Nothing deleted them: one folder per open (a costume or stage is 0.4-1.5 MB) for as long as
# the app ran, and on after it. Now: a workbench load prunes checkpoint copies older than an
# hour; the backend removes every viewer folder it made when it shuts down
# (``remove_own_viewer_folders``: the shutdown route, cleanup_on_exit); and a start removes
# every one an earlier run left (``sweep_viewer_folders``: one a viewer still held as the app
# closed, or a crash's), never one this backend made (a live viewer's). 0.9.0 smoke tests:
# checkpoint copies (build 2), then a costume viewer's folder (build 4, macOS, the app quit
# with the 3D viewer open) were left in the data folder's scratch after the app had quit.
VIEWER_PREFIX = 'viewer_'
VAULT_PREFIX = 'viewer_vault_'
CHECKPOINT_COPY_PREFIX = 'viewer_checkpoint_'
CHECKPOINT_COPY_SECONDS = 3600
# A viewer folder's name as tempfile.mkdtemp makes it: exactly its eight random characters after
# the plain prefix (the scratch is every feature's temp folder, so never any viewer_*), any after
# the two longer ones.
_VIEWER_FOLDER = re.compile(r'^viewer_(?:(?:checkpoint|vault)_[a-z0-9_]+|[a-z0-9_]{8})$')
_made = set()           # this backend's viewer folders, removed when it shuts down
_made_lock = threading.Lock()


def _is_link(path):
    """A symlink or a Windows junction (os.path.isjunction: Python 3.12+): a sweep never follows one."""
    isjunction = getattr(os.path, 'isjunction', None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def _new_viewer_folder(prefix):
    """A fresh viewer folder in the data scratch, kept as this backend's (``_made``)."""
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    with _made_lock:
        _made.add(folder)
    return folder


def _prune_checkpoint_copies(keep_seconds=CHECKPOINT_COPY_SECONDS):
    """Delete checkpoint copies older than ``keep_seconds`` (a copy a live viewer still holds stays: Windows will
    not delete a file that is open). -> how many went."""
    cutoff = time.time() - keep_seconds
    gone = 0
    for entry in Path(tempfile.gettempdir()).glob(CHECKPOINT_COPY_PREFIX + '*'):
        try:
            if entry.is_dir() and entry.stat().st_mtime <= cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                gone += not entry.exists()
        except OSError:
            pass
    return gone


def sweep_viewer_folders(folder=None):
    """At the backend's start: every viewer folder an earlier run left in ``folder`` (default: the data scratch),
    however new. Never one this backend made (a live viewer's: nothing of this run has one yet at the start), and one
    an earlier run's viewer still holds open stays (Windows will not delete an open file). -> how many went."""
    root = Path(folder) if folder is not None else Path(tempfile.gettempdir())
    with _made_lock:
        own = {made.name for made in _made}
    gone = 0
    try:
        entries = list(root.glob(VIEWER_PREFIX + '*'))
    except OSError:
        return 0
    for entry in entries:
        if not _VIEWER_FOLDER.match(entry.name) or entry.name in own:
            continue
        try:
            if entry.is_dir() and not _is_link(entry):
                shutil.rmtree(entry, ignore_errors=True)
                gone += not entry.exists()
        except OSError:
            pass
    return gone


def remove_own_viewer_folders():
    """At shutdown: the viewer folders this backend made (one its viewer still holds stays; the next start sweeps
    it)."""
    with _made_lock:
        made = list(_made)
    for folder in made:
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            with _made_lock:
                _made.discard(folder)


@viewer_bp.route('/api/mex/viewer/paths-checkpoint', methods=['POST'])
def get_viewer_paths_checkpoint():
    """File paths for one of Randall's working copies, so an open editor can
    show the edit it just made without the user reopening anything. The file is
    a private working DAT, never a vault entry: nothing is saved to show it."""
    try:
        data = request.json or {}
        character, file_id = data.get('character'), data.get('fileId')
        stage_code = data.get('stageCode')
        if not (character or stage_code) or not file_id:
            return jsonify({'success': False, 'error': 'Missing character or fileId'}), 400
        from shared import mod_files
        try:
            source, info = mod_files.resolve(file_id)
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 404
        # .usd: Pokemon Stadium's stage file (GrPs.usd) and localized costumes are DATs too.
        if info.get('extension') not in ('.dat', '.usd'):
            return jsonify({'success': False, 'error': 'That working file is not a DAT.'}), 400
        _prune_checkpoint_copies()
        temp_dir = _new_viewer_folder(CHECKPOINT_COPY_PREFIX)
        dat_path = temp_dir / Path(info['name']).name
        shutil.copyfile(source, dat_path)
        if not character:
            # A Stage Lab working copy: a stage has no fighter scene or animations.
            return jsonify({'success': True, 'datFile': to_windows_path(dat_path),
                            'logsPath': to_windows_path(LOGS_PATH), 'tempDir': str(temp_dir)})
        scene_path = find_scene_file(character)
        aj_path = find_aj_file(character)
        data_path = find_fighter_data_file(character)
        return jsonify({
            'success': True,
            'datFile': to_windows_path(dat_path),
            'sceneFile': to_windows_path(scene_path) if scene_path else None,
            'ajFile': to_windows_path(aj_path) if aj_path else None,
            'dataFile': to_windows_path(data_path) if data_path else None,
            'logsPath': to_windows_path(LOGS_PATH),
            'tempDir': str(temp_dir),
            'textureModels': _texture_models(dat_path, data_path, character,
                                             mod_files.origin_of(info).get('costume_code')),
        })
    except Exception as e:
        logger.error(f"Get checkpoint viewer paths error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@viewer_bp.route('/api/mex/viewer/paths-vault', methods=['POST'])
def get_viewer_paths_vault():
    """Get file paths for vault costume viewer (Electron IPC, no spawning)"""
    try:
        data = request.json
        character = data.get('character')
        costume_id = data.get('costumeId')

        if not character or not costume_id:
            return jsonify({'success': False, 'error': 'Missing character or costumeId'}), 400

        # Find the costume in the vault
        char_storage = STORAGE_PATH / character
        zip_path = char_storage / f"{costume_id}.zip"

        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Costume not found in vault: {costume_id}'}), 404

        temp_dir, dat_path = extract_costume_archive(zip_path, VAULT_PREFIX)
        if not dat_path or not dat_path.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({'success': False, 'error': 'No costume archive found in vault costume ZIP'}), 400

        dat_windows_path = to_windows_path(dat_path)
        logs_windows_path = to_windows_path(LOGS_PATH)

        # Find scene file
        scene_path = find_scene_file(character)

        # Find AJ file
        aj_path = find_aj_file(character)

        # Custom characters (pseudo keys like custom_characters/<slug>/skins):
        # animations come from their own AJ inside fighter.zip; the scene config
        # falls back to the donor skeleton
        from core.metadata import custom_character_slug
        slug = custom_character_slug(character)
        if slug:
            if aj_path is None:
                aj_path = extract_custom_character_aj(slug)
            if scene_path is None:
                based_on = custom_character_based_on(slug)
                if based_on:
                    scene_path = find_scene_file(based_on)

        scene_windows_path = to_windows_path(scene_path) if scene_path else None
        aj_windows_path = to_windows_path(aj_path) if aj_path else None

        # fighter-data dat (ftData) -> per-animation mesh-part visibility
        data_path = find_fighter_data_file(character) or (
            extract_custom_character_data(slug) if slug else None)
        data_windows_path = to_windows_path(data_path) if data_path else None

        return jsonify({
            'success': True,
            **({'members': _paint_members(dat_path, costume_id=costume_id, output_dir=temp_dir,
                                         include_bytes=bool(data.get('paintPair')))}
               if character in ('Ice Climbers', 'Nana') else {}),
            'datFile': dat_windows_path,
            'sceneFile': scene_windows_path,
            'ajFile': aj_windows_path,
            'dataFile': data_windows_path,
            'logsPath': logs_windows_path,
            'tempDir': str(temp_dir),
            'textureModels': _texture_models(dat_path, data_path, character),
        })

    except Exception as e:
        logger.error(f"Get vault viewer paths error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@viewer_bp.route('/api/mex/vanilla/costumes/<character>', methods=['GET'])
def get_vanilla_costumes(character):
    """Get list of vanilla costumes for a character"""
    try:
        char_dir = VANILLA_ASSETS_DIR / character
        if not char_dir.exists():
            return jsonify({'success': False, 'error': f'Character {character} not found'}), 404

        costumes = []
        for folder in char_dir.iterdir():
            if folder.is_dir() and folder.name.startswith('Pl'):
                costume_code = Path(folder.name).stem
                archive_file = find_vanilla_costume_file(character, costume_code)
                if archive_file:
                    # Get color code from folder name (last 2 chars)
                    color_code = costume_code[-2:]
                    color_names = {
                        'Nr': 'Default', 'Bu': 'Blue', 'Re': 'Red', 'Rd': 'Red', 'Gr': 'Green',
                        'Ye': 'Yellow', 'Bk': 'Black', 'Wh': 'White', 'Pi': 'Pink',
                        'Or': 'Orange', 'La': 'Lavender', 'Aq': 'Aqua', 'Gy': 'Grey',
                        'Cy': 'Cyan', 'Pr': 'Purple', 'Br': 'Brown'
                    }
                    costumes.append({
                        'code': costume_code,
                        'colorCode': color_code,
                        'colorName': color_names.get(color_code, color_code),
                        'hasCsp': (folder / 'csp.png').exists(),
                        'hasStock': (folder / 'stock.png').exists()
                    })

        css_order = VANILLA_CSS_COLOR_ORDER.get(character, [])
        def css_sort_key(c):
            try:
                return css_order.index(c['colorCode'])
            except ValueError:
                return len(css_order)
        costumes.sort(key=css_sort_key)

        return jsonify({'success': True, 'costumes': costumes})

    except Exception as e:
        logger.error(f"Get vanilla costumes error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
