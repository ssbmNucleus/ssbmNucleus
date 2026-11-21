"""
Custom stages, project side: install vault custom stages into the open m-ex
project, remove them, and list the ones it carries.

Every install/remove is a workspace-mutating MexCLI call under mexcli_lock.
These routes register on `custom_stages_bp` from vault/routes/custom_stages.py
(the vault's custom stage list), so URLs and endpoint names are unchanged; the
index reads both share are vault/catalog/custom_stages.py.
"""

import json
import os
import subprocess
import tempfile
import logging
from pathlib import Path
from flask import request, jsonify

import file_retry
from core.config import MEXCLI_PATH, PROJECT_ROOT, get_subprocess_args
import mexcli.commands
from core.state import get_current_project_path, reload_mex_manager, get_socketio, mexcli_lock
from vault.importing.custom_stage_package import CUSTOM_STAGES_PATH
from vault.catalog.custom_stages import _find_stage_entry, _is_folder, _read_metadata
from vault.routes.custom_stages import custom_stages_bp

logger = logging.getLogger(__name__)


@custom_stages_bp.route('/api/mex/custom-stages/in-project', methods=['GET'])
def list_custom_stages_in_project():
    """List custom stages currently installed in the open project (index > 70)."""
    try:
        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': True, 'stages': []})

        project_dir = project_path.parent
        stages_dir = project_dir / 'data' / 'stages'

        if not stages_dir.exists() or not project_path.exists():
            return jsonify({'success': True, 'stages': []})

        with open(project_path, 'r') as f:
            proj_data = json.load(f)

        stage_files = proj_data.get('stageSaveMap', {}).get('filePaths', [])
        assets_dir = project_dir / 'assets'
        stages = []

        for i, stage_file in enumerate(stage_files):
            if i <= 70:
                continue
            stage_json_path = stages_dir / stage_file
            if not stage_json_path.exists():
                continue
            try:
                with open(stage_json_path, 'r') as f:
                    stage_data = json.load(f)
                name = stage_data.get('name', f'Stage {i}')
                icon_ref = stage_data.get('assets', {}).get('icon')
                icon_url = None
                if icon_ref:
                    icon_url = f"/assets/{icon_ref.replace(chr(92), '/')}.png"
                stages.append({
                    'index': i,
                    'name': name,
                    'icon_url': icon_url,
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return jsonify({'success': True, 'stages': stages})
    except Exception as e:
        logger.error(f"List project custom stages error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _apply_vanilla_stage_fixups(project_path, internal_id, vanilla_stage):
    """Re-apply what MexStage.FromPackage resets when a vanilla-stage mod is
    installed: the stage's vanilla sound bank (stage SFX) and vanilla music
    playlist. Edits the project's stage json directly -- every MexCLI run
    re-opens the workspace from disk, and export always recompiles MxDt from
    these files, so the edit is picked up without an extra Save. Caller must
    hold mexcli_lock. Returns True when a fixup was written."""
    try:
        with open(project_path, 'r') as f:
            proj = json.load(f)
        file_paths = proj.get('stageSaveMap', {}).get('filePaths', [])
        if not (isinstance(internal_id, int) and 0 <= internal_id < len(file_paths)):
            logger.warning(f"vanilla stage fixup: internalId {internal_id} not in project stage map")
            return False
        stage_json_path = project_path.parent / 'data' / 'stages' / file_paths[internal_id]
        with open(stage_json_path, 'r') as f:
            stage_data = json.load(f)

        if vanilla_stage.get('soundBank') is not None:
            stage_data['soundBank'] = int(vanilla_stage['soundBank'])
        playlist = vanilla_stage.get('playlist') or []
        if playlist:
            stage_data['playlist'] = {'entries': [
                {'musicID': int(e['musicID']),
                 'chanceToPlay': int(e.get('chanceToPlay', 50))}
                for e in playlist if e.get('musicID') is not None
            ]}

        with file_retry.retry_locked(open, stage_json_path, 'w') as f:
            json.dump(stage_data, f, indent=2)
        logger.info(f"[OK] Applied vanilla stage fixups (bank {vanilla_stage.get('soundBank')}, "
                    f"{len(playlist)} track(s)) to stage {internal_id}")
        return True
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f"vanilla stage fixup failed for stage {internal_id}: {e}")
        return False


@custom_stages_bp.route('/api/mex/custom-stages/install', methods=['POST'])
def install_custom_stage():
    """Install a custom stage from the vault into the currently open project."""
    try:
        data = request.json or {}
        slug = data.get('slug', '').strip()
        if not slug:
            return jsonify({'success': False, 'error': 'Missing slug parameter'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded. Open a project first.'}), 400

        zip_path = CUSTOM_STAGES_PATH / slug / 'stage.zip'
        if not zip_path.exists():
            return jsonify({'success': False, 'error': f'Stage ZIP not found for "{slug}". Re-scan the ISO to generate it.'}), 404

        mexcli_path = str(MEXCLI_PATH)
        if not Path(mexcli_path).exists():
            return jsonify({'success': False, 'error': 'MexCLI not found'}), 500

        cmd = [mexcli_path, 'add-stage', str(project_path), str(zip_path)]
        logger.info(f"Installing custom stage '{slug}': {' '.join(cmd)}")

        # Workspace-mutating MexCLI call -- hold the project lock so it can't run
        # concurrently with a background costume reorder / export.
        with mexcli_lock:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), **get_subprocess_args()
            )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"add-stage failed: {error_msg}")
            return jsonify({'success': False, 'error': f'Failed to add stage: {error_msg}'}), 500

        cli_output = mexcli.commands.parse_json(result.stdout)
        stage_name = cli_output.get('name', slug)

        metadata = _read_metadata()
        entry = next((s for s in metadata.get('custom_stages', [])
                      if not _is_folder(s) and s.get('slug') == slug), None)

        # Vanilla-stage mods: restore the vanilla sound bank + music playlist
        # that FromPackage reset (a vault hps playlist below still overrides).
        if entry and isinstance(entry.get('vanilla_stage'), dict):
            with mexcli_lock:
                _apply_vanilla_stage_fixups(
                    project_path, cli_output.get('internalId'), entry['vanilla_stage'])

        # Port the stage's music playlist: add each track to the target
        # project (reusing same-named ones), then point the stage at them —
        # add-stage itself resets the playlist to a single default track
        warnings = []
        playlist_ported = 0
        playlist = (entry or {}).get('playlist') or []
        if playlist:
            stage_dir = CUSTOM_STAGES_PATH / slug
            cli_entries = []
            for i, track in enumerate(playlist):
                hps = stage_dir / f'music_{i}.hps'
                if not hps.exists() or not track.get('name'):
                    warnings.append(f"Track '{track.get('name')}' file missing, skipped")
                    continue
                with mexcli_lock:
                    music_out = mexcli.commands.run_json(['add-music', project_path, hps, track['name']])
                if music_out.get('success') and 'musicId' in music_out:
                    cli_entries.append({'musicId': music_out['musicId'],
                                        'chance': track.get('chance', 50)})
                else:
                    warnings.append(f"Track '{track['name']}' could not be added")
            if cli_entries:
                with mexcli_lock:
                    pl_result = subprocess.run(
                        [str(MEXCLI_PATH), 'set-stage-playlist', str(project_path), stage_name],
                        input=json.dumps(cli_entries),
                        capture_output=True, text=True,
                        cwd=str(PROJECT_ROOT), **get_subprocess_args()
                    )
                if pl_result.returncode == 0 and mexcli.commands.parse_json(pl_result.stdout).get('success'):
                    playlist_ported = len(cli_entries)
                    logger.info(f"Ported {playlist_ported} playlist track(s) for stage '{stage_name}'")
                else:
                    warnings.append('Stage playlist could not be set')
                    logger.warning(f"set-stage-playlist failed: {pl_result.stdout or pl_result.stderr}")

        import time
        time.sleep(0.15)
        reload_mex_manager()

        message = f"Added {stage_name} to project"
        if playlist_ported:
            message += f" with {playlist_ported} music track(s)"
        logger.info(f"[OK] Installed custom stage '{slug}' into project")
        return jsonify({
            'success': True,
            'message': message,
            'name': stage_name,
            'playlistPorted': playlist_ported,
            'warnings': warnings,
        })
    except Exception as e:
        logger.error(f"Install custom stage error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _stage_manifest_entry(slug):
    """Build the add-stages manifest entry for a vault stage: the raw stage.zip plus
    its playlist (hps path + name + chance per track), mirroring install_custom_stage.
    Returns (entry_dict, warnings) or (None, [error])."""
    zip_path = CUSTOM_STAGES_PATH / slug / 'stage.zip'
    if not zip_path.exists():
        return None, [f'Stage ZIP not found for "{slug}". Re-scan the ISO to generate it.']

    e = {'zip': str(zip_path)}
    warnings = []
    metadata = _read_metadata()
    entry = next((s for s in metadata.get('custom_stages', [])
                  if not _is_folder(s) and s.get('slug') == slug), None)
    playlist = (entry or {}).get('playlist') or []
    if playlist:
        stage_dir = CUSTOM_STAGES_PATH / slug
        tracks = []
        for i, track in enumerate(playlist):
            hps = stage_dir / f'music_{i}.hps'
            if not hps.exists() or not track.get('name'):
                warnings.append(f"{slug}: track '{track.get('name')}' file missing, skipped")
                continue
            tracks.append({'hps': str(hps), 'name': track['name'],
                           'chance': track.get('chance', 50)})
        if tracks:
            e['playlist'] = tracks
    return e, warnings


@custom_stages_bp.route('/api/mex/custom-stages/install-batch', methods=['POST'])
def install_custom_stages_batch():
    """Bulk-install several vault custom stages in ONE `add-stages` call -- one
    workspace Save instead of add-stage + (one add-music per track) + set-stage-playlist
    PER stage. Byte-identical to N sequential installs (validated full-tree).

    Body: { "slugs": ["awakening-wood-2", ...] }
    """
    try:
        data = request.json or {}
        slugs = [s.strip() for s in (data.get('slugs') or []) if s and s.strip()]
        if not slugs:
            return jsonify({'success': False, 'error': 'No slugs provided'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded. Open a project first.'}), 400
        mexcli_path = str(MEXCLI_PATH)
        if not Path(mexcli_path).exists():
            return jsonify({'success': False, 'error': 'MexCLI not found'}), 500

        # Stream progress so the UI doesn't sit at 0/N (same as the character
        # batch). Stages prepare fast, but the compile is one step — show it.
        socketio = get_socketio()
        total = len(slugs)

        def _emit(current, phase, name=None, message=None):
            try:
                socketio.emit('custom_stage_install_progress', {
                    'current': current, 'total': total,
                    'phase': phase, 'name': name, 'message': message})
            except Exception:
                pass

        manifest_stages, manifest_slugs, failed, warnings = [], [], [], []
        for i, slug in enumerate(slugs):
            _emit(i + 1, 'preparing', name=slug)
            entry, warns = _stage_manifest_entry(slug)
            if entry is None:
                failed.append({'slug': slug, 'error': warns[0] if warns else 'prepare failed'})
                continue
            manifest_stages.append(entry)
            manifest_slugs.append(slug)
            warnings += warns

        if not manifest_stages:
            return jsonify({'success': False, 'error': 'No installable stages', 'failed': failed}), 400

        logger.info(f"=== BATCH STAGE INSTALL ({len(manifest_stages)} stages) ===")
        _emit(total, 'compiling', message='Building project…')
        fd, manifest_path = tempfile.mkstemp(suffix='.json', prefix='nucleus_stages_batch_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump({'stages': manifest_stages}, f)
            with mexcli_lock:
                result = subprocess.run(
                    [mexcli_path, 'add-stages', str(project_path), manifest_path],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT), **get_subprocess_args())
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass

        if result.returncode != 0:
            err = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"add-stages batch failed: {err}")
            return jsonify({'success': False, 'error': f'Batch add failed: {err}'}), 500

        cli = mexcli.commands.parse_json(result.stdout)
        for sr in cli.get('stages', []):
            for w in (sr.get('warnings') or []):
                warnings.append(f"{sr.get('name', '?')}: {w}")

        # Vanilla-stage mods: restore what FromPackage reset. add-stages
        # returns one result per manifest entry, in order, so pair by index.
        vault = _read_metadata()
        for slug, sr in zip(manifest_slugs, cli.get('stages', [])):
            if not sr.get('success'):
                continue
            entry = _find_stage_entry(vault, slug)
            if not (entry and isinstance(entry.get('vanilla_stage'), dict)):
                continue
            fixup = dict(entry['vanilla_stage'])
            if entry.get('playlist'):
                # the batch already ported the vault's own hps playlist;
                # only the sound bank still needs restoring
                fixup.pop('playlist', None)
            with mexcli_lock:
                _apply_vanilla_stage_fixups(project_path, sr.get('internalId'), fixup)

        import time
        time.sleep(0.15)
        reload_mex_manager()

        added = cli.get('totalAdded', 0)
        logger.info(f"[OK] Batch-installed {added} custom stage(s)")
        _emit(total, 'done')
        return jsonify({
            'success': True,
            'message': f"Added {added} stage(s) to project",
            'totalAdded': added,
            'totalFailed': cli.get('totalFailed', 0) + len(failed),
            'totalTracks': cli.get('totalTracks', 0),
            'stages': cli.get('stages', []),
            'failed': failed,
            'warnings': warnings,
        })
    except Exception as e:
        logger.error(f"Batch stage install error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/remove-from-project', methods=['POST'])
def remove_custom_stage_from_project():
    """Remove a custom stage from the currently open project."""
    try:
        data = request.json or {}
        stage_name = data.get('name', '').strip()
        if not stage_name:
            return jsonify({'success': False, 'error': 'Missing name parameter'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded.'}), 400

        mexcli_path = str(MEXCLI_PATH)
        cmd = [mexcli_path, 'remove-stage', str(project_path), stage_name]
        logger.info(f"Removing stage '{stage_name}': {' '.join(cmd)}")

        with mexcli_lock:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), **get_subprocess_args()
            )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            return jsonify({'success': False, 'error': f'Failed to remove stage: {error_msg}'}), 500

        import time
        time.sleep(0.15)
        reload_mex_manager()

        logger.info(f"[OK] Removed stage '{stage_name}' from project")
        return jsonify({'success': True, 'message': f'Removed {stage_name}'})
    except Exception as e:
        logger.error(f"Remove stage error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@custom_stages_bp.route('/api/mex/custom-stages/remove-batch', methods=['POST'])
def remove_custom_stages_batch():
    """Bulk-remove several custom stages in ONE `remove-stages` call -- one workspace
    Save instead of one per stage. Byte-identical to N sequential removes (the live
    project matches; only a stale, never-loaded orphan stage json can differ).

    Body: { "names": ["My Stage", ...] }
    """
    try:
        data = request.json or {}
        names = [n.strip() for n in (data.get('names') or []) if n and n.strip()]
        if not names:
            return jsonify({'success': False, 'error': 'No names provided'}), 400

        project_path = get_current_project_path()
        if project_path is None:
            return jsonify({'success': False, 'error': 'No project loaded.'}), 400
        mexcli_path = str(MEXCLI_PATH)
        if not Path(mexcli_path).exists():
            return jsonify({'success': False, 'error': 'MexCLI not found'}), 500

        logger.info(f"=== BATCH STAGE REMOVE ({len(names)} stages) ===")
        fd, manifest_path = tempfile.mkstemp(suffix='.json', prefix='nucleus_stages_rm_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump({'stages': names}, f)
            with mexcli_lock:
                result = subprocess.run(
                    [mexcli_path, 'remove-stages', str(project_path), manifest_path],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT), **get_subprocess_args())
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass

        if result.returncode != 0:
            err = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"remove-stages batch failed: {err}")
            return jsonify({'success': False, 'error': f'Batch remove failed: {err}'}), 500

        cli = mexcli.commands.parse_json(result.stdout)
        import time
        time.sleep(0.15)
        reload_mex_manager()

        removed = cli.get('totalRemoved', 0)
        logger.info(f"[OK] Batch-removed {removed} custom stage(s)")
        return jsonify({
            'success': True,
            'message': f'Removed {removed} stage(s)',
            'totalRemoved': removed,
            'totalFailed': cli.get('totalFailed', 0),
            'stages': cli.get('stages', []),
        })
    except Exception as e:
        logger.error(f"Batch stage remove error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
