"""
Slippi Blueprint - Slippi/Dolphin integration and texture pack endpoints.

Handles Slippi path verification, Dolphin configuration, and texture pack management.
"""

import shutil
import configparser
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify

import file_retry
from core import jobs
from core.config import STORAGE_PATH, OUTPUT_PATH
from shared.ingame.boot import slippi_user_dir
from core.helpers import convert_windows_to_wsl_path

logger = logging.getLogger(__name__)

slippi_bp = Blueprint('slippi', __name__)

MATCH_KIND = 'texture_matching'


def _clean_texture_matching(name, value):
    if name == 'dump_settings':
        path = get_dolphin_gfx_ini_path(value['slippi_path'])
        config = configparser.ConfigParser()
        config.optionxform = str
        if path.exists():
            config.read(path, encoding='utf-8')
        previous = value['dump_textures']
        if previous is None:
            config.remove_option('Settings', 'DumpTextures')
        else:
            if 'Settings' not in config:
                config['Settings'] = {}
            config['Settings']['DumpTextures'] = 'True' if previous else 'False'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as stream:
            config.write(stream)
        return 'Restored Dolphin texture dumping.'
    if name in ('partial', 'mapping_partial'):
        path = Path(value)
        if path.name.startswith('texture-match-') and path.name.endswith('.part'):
            path.unlink(missing_ok=True)


jobs.register_kind(MATCH_KIND, label='Texture matching', cleanup=_clean_texture_matching)


def get_dolphin_gfx_ini_path(slippi_path: str) -> Path:
    """Get path to Dolphin's GFX.ini configuration file."""
    return slippi_user_dir(slippi_path) / "Config" / "GFX.ini"


def get_dolphin_ini_path(slippi_path: str) -> Path:
    """Get path to Dolphin's main Dolphin.ini configuration file."""
    return slippi_user_dir(slippi_path) / "Config" / "Dolphin.ini"


def disable_dolphin_panic_handlers(slippi_path: str) -> bool:
    """Force UsePanicHandlers=False in Dolphin.ini.

    Why: panic dialogs from Dolphin's emulation core (notably the recurring
    Pokemon Stadium issue) interrupt gameplay and crash sessions. Disabling
    the handler suppresses the dialog and lets emulation continue.
    """
    dolphin_ini = get_dolphin_ini_path(slippi_path)

    if not dolphin_ini.parent.exists():
        logger.warning(f"Config dir missing, skipping panic-handler patch: {dolphin_ini.parent}")
        return False

    config = configparser.ConfigParser()
    config.optionxform = str

    try:
        if dolphin_ini.exists():
            config.read(dolphin_ini, encoding='utf-8')

        if 'Interface' not in config:
            config['Interface'] = {}

        if config['Interface'].get('UsePanicHandlers') == 'False':
            return True

        config['Interface']['UsePanicHandlers'] = 'False'

        with open(dolphin_ini, 'w', encoding='utf-8') as f:
            config.write(f)

        logger.info(f"Disabled UsePanicHandlers in {dolphin_ini}")
        return True
    except Exception as e:
        logger.error(f"Error disabling UsePanicHandlers: {e}")
        return False


def get_dolphin_texture_settings(slippi_path: str) -> dict:
    """Read current texture settings from Dolphin's GFX.ini."""
    gfx_ini = get_dolphin_gfx_ini_path(slippi_path)

    result = {
        'dump_textures': None,
        'hires_textures': None
    }

    if not gfx_ini.exists():
        logger.warning(f"GFX.ini not found at {gfx_ini}")
        return result

    config = configparser.ConfigParser()
    config.optionxform = str  # Preserve case of keys

    try:
        config.read(gfx_ini)

        if 'Settings' in config:
            if 'DumpTextures' in config['Settings']:
                result['dump_textures'] = config['Settings']['DumpTextures'].lower() == 'true'
            if 'HiresTextures' in config['Settings']:
                result['hires_textures'] = config['Settings']['HiresTextures'].lower() == 'true'

    except Exception as e:
        logger.error(f"Error reading GFX.ini: {e}")

    return result


def set_dolphin_texture_settings(slippi_path: str, dump_textures: bool = None, hires_textures: bool = None) -> bool:
    """Modify texture settings in Dolphin's GFX.ini."""
    gfx_ini = get_dolphin_gfx_ini_path(slippi_path)

    # Ensure directory exists
    gfx_ini.parent.mkdir(parents=True, exist_ok=True)

    config = configparser.ConfigParser()
    config.optionxform = str  # Preserve case of keys

    try:
        # Read existing config if it exists
        if gfx_ini.exists():
            config.read(gfx_ini)

        # Ensure Settings section exists
        if 'Settings' not in config:
            config['Settings'] = {}

        # Update requested settings
        if dump_textures is not None:
            config['Settings']['DumpTextures'] = 'True' if dump_textures else 'False'
            logger.info(f"Set DumpTextures = {dump_textures}")

        if hires_textures is not None:
            config['Settings']['HiresTextures'] = 'True' if hires_textures else 'False'
            logger.info(f"Set HiresTextures = {hires_textures}")

        # Write back
        with open(gfx_ini, 'w') as f:
            config.write(f)

        logger.info(f"Updated GFX.ini at {gfx_ini}")
        return True

    except Exception as e:
        logger.error(f"Error writing GFX.ini: {e}")
        return False


@slippi_bp.route('/api/mex/settings/slippi-path/verify', methods=['POST'])
def verify_slippi_path():
    """Verify that a Slippi Dolphin path is valid."""
    try:
        data = request.json or {}
        slippi_path = data.get('slippiPath')

        if not slippi_path:
            return jsonify({
                'success': False,
                'error': 'No slippiPath provided'
            }), 400

        slippi_dir = Path(slippi_path)

        # Check if directory exists
        if not slippi_dir.exists():
            return jsonify({
                'success': False,
                'valid': False,
                'error': 'Directory does not exist'
            })

        # Check for User folder
        user_dir = slippi_user_dir(slippi_path)
        if not user_dir.exists() or not user_dir.is_dir():
            return jsonify({
                'success': False,
                'valid': False,
                'error': 'User folder not found'
            })

        # Check for Config folder
        config_dir = user_dir / 'Config'
        if not config_dir.exists():
            return jsonify({
                'success': False,
                'valid': False,
                'error': 'Config folder not found'
            })

        # Check for Dolphin.ini
        dolphin_ini = config_dir / 'Dolphin.ini'
        has_dolphin_ini = dolphin_ini.exists()

        disable_dolphin_panic_handlers(slippi_path)

        return jsonify({
            'success': True,
            'valid': True,
            'hasDolphinIni': has_dolphin_ini
        })

    except Exception as e:
        logger.error(f"Verify Slippi path error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@slippi_bp.route('/api/mex/texture-pack/stats', methods=['GET'])
def get_texture_pack_stats():
    """Get texture pack folder statistics."""
    try:
        slippi_path = request.args.get('slippiPath', '')

        if not slippi_path:
            return jsonify({
                'success': True,
                'stats': {
                    'size': 0,
                    'fileCount': 0,
                    'path': '',
                    'exists': False
                }
            })

        # Texture pack folder is at <Slippi>/User/Load/Textures/GALE01/ssbm-nucleus
        texture_path = slippi_user_dir(slippi_path) / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'

        if not texture_path.exists():
            return jsonify({
                'success': True,
                'stats': {
                    'size': 0,
                    'fileCount': 0,
                    'path': str(texture_path),
                    'exists': False
                }
            })

        # Calculate size and file count
        total_size = 0
        file_count = 0
        for item in texture_path.rglob('*'):
            if item.is_file():
                total_size += item.stat().st_size
                file_count += 1

        return jsonify({
            'success': True,
            'stats': {
                'size': total_size,
                'fileCount': file_count,
                'path': str(texture_path),
                'exists': True
            }
        })
    except Exception as e:
        logger.error(f"Error getting texture pack stats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@slippi_bp.route('/api/mex/texture-pack/clear', methods=['POST'])
def clear_texture_pack():
    """Clear texture pack folder contents."""
    try:
        data = request.json or {}
        slippi_path = data.get('slippiPath', '')

        if not slippi_path:
            return jsonify({
                'success': False,
                'error': 'slippiPath is required'
            }), 400

        # The running listener believes what it already matched is installed;
        # deleting it underneath would leave those textures missing for good.
        active = jobs.active_job(MATCH_KIND)
        if (active is not None
                and active.params['slippiPath'] == convert_windows_to_wsl_path(slippi_path)):
            return jsonify({
                'success': False,
                'error': 'The texture listener is running for this Slippi folder. Stop it first.'
            }), 409

        # Only clear our subfolder — leave other user textures untouched
        texture_path = slippi_user_dir(slippi_path) / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'

        if not texture_path.exists():
            return jsonify({
                'success': True,
                'deletedCount': 0,
                'message': 'Texture pack folder does not exist'
            })

        # Delete all contents
        deleted_count = 0
        for item in texture_path.iterdir():
            if item.is_file():
                item.unlink()
                deleted_count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                deleted_count += 1

        logger.info(f"Cleared texture pack folder: {deleted_count} items deleted from {texture_path}")

        return jsonify({
            'success': True,
            'deletedCount': deleted_count,
            'message': f'Deleted {deleted_count} items from texture pack folder'
        })
    except Exception as e:
        logger.error(f"Error clearing texture pack: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def run_texture_matching(job, mapping, mapping_file, slippi_path):
    from projects.install.texture_pack import TexturePackMatcher

    job.check_stop()
    previous = get_dolphin_texture_settings(slippi_path)['dump_textures']
    job.own('dump_settings', {'slippi_path': slippi_path, 'dump_textures': previous})
    if not set_dolphin_texture_settings(slippi_path, dump_textures=True, hires_textures=True):
        raise RuntimeError("Could not enable texture dumping in Dolphin's GFX.ini")
    user_dir = slippi_user_dir(slippi_path)
    dump_path = user_dir / 'Dump' / 'Textures' / 'GALE01'
    load_path = user_dir / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'
    dump_path.mkdir(parents=True, exist_ok=True)
    load_path.mkdir(parents=True, exist_ok=True)

    def progress(matched, total):
        job.progress(matched / total if total else 1, f'Matched {matched}/{total} textures',
                     matched=matched, total=total)

    def matched(costume):
        job.progress(last_match={'character': costume['character'],
                                'costumeIndex': costume['costume_index'],
                                'skinId': costume['skin_id'],
                                'filename': costume['dumped_filename']})

    matcher = TexturePackMatcher(dump_path, load_path, mapping, STORAGE_PATH,
                                 on_match=matched, on_progress=progress, job=job)
    total = len(mapping.costumes)
    progress(mapping.get_matched_count(), total)

    def save_mapping():
        partial = mapping_file.with_name(f'texture-match-{job.id}.json.part')
        job.own('mapping_partial', str(partial))
        mapping.save(partial)
        file_retry.replace(partial, mapping_file)
        job.release('mapping_partial')

    while not job.should_stop() and mapping.get_unmatched_count():
        before = mapping.get_matched_count()
        matcher.scan()
        if mapping.get_matched_count() != before:
            save_mapping()
        if not mapping.get_unmatched_count():
            break
        job.stop_event.wait(0.5)
    save_mapping()
    # Stopping finalizes the matches collected so far, like replay playback Stop.
    return {'matchedCount': mapping.get_matched_count(), 'totalCount': total,
            'texturePackPath': str(load_path / mapping.build_name),
            'stopped': job.should_stop()}


@slippi_bp.route('/api/mex/texture-pack/start-listening', methods=['POST'])
def start_texture_listening():
    """Start a texture_matching job; stop/finalize through the shared cancel API."""
    try:
        data = request.json or {}
        build_id, slippi_path = data.get('buildId'), data.get('slippiPath')
        if not build_id or not slippi_path:
            return jsonify({'success': False, 'error': 'buildId and slippiPath are required'}), 400
        slippi_path = convert_windows_to_wsl_path(slippi_path)
        mapping_file = OUTPUT_PATH / f'{build_id}_texture_mapping.json'
        if not mapping_file.is_file():
            return jsonify({'success': False, 'error': f'Mapping file not found for build: {build_id}'}), 404
        from projects.install.texture_pack import TexturePackMapping
        mapping = TexturePackMapping.load(mapping_file)
        job_id = jobs.start(MATCH_KIND,
                            lambda job: run_texture_matching(job, mapping, mapping_file, slippi_path),
                            single=True, params={'buildId': build_id, 'slippiPath': slippi_path,
                                                 'total': len(mapping.costumes)})
        return jsonify({'success': True, 'job_id': job_id})
    except jobs.JobBusy as e:
        return jsonify({'success': False, 'error': 'Texture matching is already running',
                        'job_id': e.job_id}), 409
    except Exception as e:
        logger.error('Start texture matching error: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@slippi_bp.route('/api/mex/texture-pack/apply-offline', methods=['POST'])
def apply_texture_pack_offline():
    """Name a build's texture pack from a harvested index->filename table -- NO
    ISO boot, NO CSS scroll. The 16x16 placeholder for a global costume index is
    byte-identical in every build, so the Dolphin load filename it produces is a
    pure function of the index. Given that table (harvested once via the texture
    harness), copy each real CSP straight into Load/ under table[index].

    Body: { buildId, slippiPath, tablePath }
    """
    try:
        import json as _json
        from pathlib import Path as _Path

        data = request.json or {}
        build_id = data.get('buildId')
        slippi_path = data.get('slippiPath')
        table_path = data.get('tablePath')
        if not build_id or not slippi_path or not table_path:
            return jsonify({'success': False, 'error': 'buildId, slippiPath and tablePath are required'}), 400

        slippi_path = convert_windows_to_wsl_path(slippi_path)
        mapping_file = OUTPUT_PATH / f"{build_id}_texture_mapping.json"
        if not mapping_file.exists():
            return jsonify({'success': False, 'error': f'Mapping not found for build {build_id}'}), 404
        table_file = _Path(convert_windows_to_wsl_path(table_path))
        if not table_file.exists():
            return jsonify({'success': False, 'error': f'Table not found: {table_file}'}), 404

        from projects.install.texture_pack import TexturePackMapping, apply_offline_texture_pack
        mapping = TexturePackMapping.load(mapping_file)
        with open(table_file, 'r') as f:
            table = _json.load(f)
        entries = table.get('entries', table)  # accept {"entries":{...}} or a bare index->record map

        load_path = slippi_user_dir(slippi_path) / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'
        # Hires load on (so the pack appears next boot), dumping off (not needed here).
        set_dolphin_texture_settings(slippi_path, dump_textures=False, hires_textures=True)

        result = apply_offline_texture_pack(mapping, entries, load_path, STORAGE_PATH)
        mapping.save(mapping_file)
        result['success'] = True
        logger.info(f"Offline texture pack for {build_id}: matched {result['matched']}/{result['total']} "
                    f"({len(result['missingFromTable'])} missing from table, {len(result['copyFailed'])} copy-failed)")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Apply offline texture pack error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


TEXTURE_PACK_KIND = 'texture_pack'
jobs.register_kind(TEXTURE_PACK_KIND, label='HD texture pack')


@slippi_bp.route('/api/mex/texture-pack/auto-apply', methods=['POST'])
def auto_apply_texture_pack():
    """Name a texture-pack build's entire pack with NO Dolphin and NO scrolling.

    The 16x16 placeholder for each global costume index is byte-identical in every
    build, so its Dolphin load filename is a pure function of the index. We keep a
    managed, build-independent index->filename table (seeded from a shipped, proven
    table and extended on demand by pure computation), look up every costume in this
    build's mapping, and copy each real HD CSP straight into Load/ under its name.

    Runs as a `texture_pack` job (core/jobs.py); the job's result is
    { buildId, matched, total, computed, missingFromTable, copyFailed, texturePackPath }.

    Body: { buildId, slippiPath }. Returns { success, job_id }.
    """
    try:
        data = request.json or {}
        build_id = data.get('buildId')
        slippi_path = data.get('slippiPath')
        if not build_id or not slippi_path:
            return jsonify({'success': False, 'error': 'buildId and slippiPath are required'}), 400

        slippi_path = convert_windows_to_wsl_path(slippi_path)
        mapping_file = OUTPUT_PATH / f"{build_id}_texture_mapping.json"
        if not mapping_file.exists():
            return jsonify({'success': False, 'error': f'Mapping not found for build {build_id}'}), 404

        def run(job):
            from projects.install.texture_pack import TexturePackMapping, apply_offline_texture_pack
            from projects.install.texture_filename_table import ensure_table_covers

            job.progress(0.03, 'Reading build mapping…')
            mapping = TexturePackMapping.load(mapping_file)
            indices = [c['index'] for c in mapping.costumes]
            total = len(indices)
            if total == 0:
                raise RuntimeError('This build has no costume CSPs to name.')

            # Most indices are already in the table (instant); only new ones are
            # computed (a few seconds each, paid once). Map compute work to 5..85%.
            def compute_progress(done, missing_total, index):
                fraction = 0.05 + (done / missing_total) * 0.8 if missing_total else 0.85
                job.progress(fraction, f'Computing texture names ({done}/{missing_total})…')

            job.progress(0.05, 'Looking up texture names…')
            entries, computed = ensure_table_covers(indices, compute_progress)

            job.progress(0.9, f'Placing {total} HD portraits…')
            load_path = slippi_user_dir(slippi_path) / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'
            # Hires load on so the pack appears next boot; dumping off (not needed).
            if not set_dolphin_texture_settings(slippi_path, dump_textures=False, hires_textures=True):
                raise RuntimeError("Could not turn on HD textures in Dolphin's GFX.ini.")

            result = apply_offline_texture_pack(mapping, entries, load_path, STORAGE_PATH)
            mapping.save(mapping_file)

            logger.info(f"Auto texture pack for {build_id}: matched {result['matched']}/{result['total']} "
                        f"({len(computed)} indices computed, {len(result['missingFromTable'])} missing, "
                        f"{len(result['copyFailed'])} copy-failed)")
            return {
                'buildId': build_id,
                'matched': result['matched'],
                'total': result['total'],
                'computed': len(computed),
                'missingFromTable': result['missingFromTable'],
                'copyFailed': result['copyFailed'],
                'texturePackPath': result['texturePackPath'],
            }

        job_id = jobs.start(TEXTURE_PACK_KIND, run, label='HD texture pack',
                            params={'buildId': build_id})
        return jsonify({'success': True, 'job_id': job_id})

    except Exception as e:
        logger.error(f"Auto texture pack start error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


