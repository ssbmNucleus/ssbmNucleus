"""
Melee Unlocked export routes: fighter plugins for the open project's custom
fighters (the engine is projects/install/melee_unlocked.py).

GET  /api/mex/melee-unlocked/fighters   which custom fighters have C source in the Vault, and whose is unconfirmed
POST /api/mex/melee-unlocked/export     start the job that builds their plugins into <destination>/fighters/
POST /api/mex/melee-unlocked/verify     check a kit folder and a compiler folder
POST /api/mex/melee-unlocked/source/<slug>     attach: keep a folder's C as that Vault character's source
POST /api/mex/melee-unlocked/source/<slug>/confirm   allow building imported source the window showed
DELETE /api/mex/melee-unlocked/source/<slug>   drop it

The kit folder and the compiler's bin folder are the user's own paths, sent in
the request body like the other tool paths the frontend keeps. The export runs
the kit's Python and compiles fighter C into native code the game runs, so every
route but the list needs the window's own key (`X-Nucleus-UI-Key`,
core/ui_channel.py): a person clicked it in the Nucleus window, not something
else holding the backend token. Source that came in a package is built only
after its confirmation (projects/install/fighter_source.py). Every folder goes
through the request-path gate (core/path_safety.py).
"""

import logging
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request

from core import jobs, path_safety, ui_channel
from core.config import CUSTOM_CHARACTERS_PATH
from core.state import get_current_project_path
from projects.install import melee_unlocked

logger = logging.getLogger(__name__)

melee_unlocked_bp = Blueprint('melee_unlocked', __name__)

# The export owns nothing that outlives it (its work folder is a temporary directory it removes
# itself), so its records stay in memory.
EXPORT_KIND = 'melee_unlocked_export'
jobs.register_kind(EXPORT_KIND, label='Melee Unlocked export', keep=5)


def _character_dir(slug):
    """The Vault folder of a custom character, or None for a slug that is not one."""
    if not slug or slug != Path(slug).name or slug in ('.', '..'):
        return None
    folder = Path(CUSTOM_CHARACTERS_PATH) / slug
    return folder if (folder / 'fighter.json').is_file() else None


def _window_only():
    """Refuse a request that is not the app's own window (core/ui_channel.py), else None."""
    refusal = ui_channel.window_refusal(request.headers)
    if refusal is None:
        return None
    code, status = refusal
    if code == 'automation_caller':
        error = 'Melee Unlocked fighter plugins are built from the Nucleus window, not by an agent.'
    elif code == 'ui_approval_channel_unavailable':
        error = 'This Nucleus has no window channel to check, so it cannot build fighter plugins here.'
    else:
        error = 'Only the Nucleus window can do that.'
    return jsonify({'success': False, 'error': error, 'code': code}), status


@melee_unlocked_bp.route('/api/mex/melee-unlocked/verify', methods=['POST'])
def verify_paths():
    """Check the two folders the export needs. Body: {kitPath, gccBin}; either may be empty.
    Answers {kit: {valid, abi|error}, compiler: {valid, error}}."""
    refused = _window_only()
    if refused:
        return refused
    body = request.json or {}
    out = {'success': True, 'kit': {'valid': False}, 'compiler': {'valid': False}}
    try:
        out['kit'] = {'valid': True, 'abi': melee_unlocked.read_kit(body.get('kitPath'))['abi']}
    except melee_unlocked.MeleeUnlockedError as e:
        out['kit'] = {'valid': False, 'error': str(e)}
    try:
        melee_unlocked.check_compiler(body.get('gccBin'))
        out['compiler'] = {'valid': True}
    except melee_unlocked.MeleeUnlockedError as e:
        out['compiler'] = {'valid': False, 'error': str(e)}
    return jsonify(out)


@melee_unlocked_bp.route('/api/mex/melee-unlocked/source/<slug>', methods=['POST', 'DELETE'])
def character_source(slug):
    """POST {folder}: the attach action. Copy the C in a folder (or its `code` subfolder) into the
    character's Vault folder, recorded as attached by the user, so the export builds it. DELETE:
    remove the character's stored source. Window only."""
    refused = _window_only()
    if refused:
        return refused
    char_dir = _character_dir(slug)
    if char_dir is None:
        return jsonify({'success': False, 'error': 'Custom character not found.'}), 404
    try:
        if request.method == 'DELETE':
            melee_unlocked.drop_source(char_dir)
            return jsonify({'success': True, 'files': []})
        folder = ((request.json or {}).get('folder') or '').strip()
        if not folder:
            return jsonify({'success': False, 'error': 'No folder was given.'}), 400
        folder = path_safety.resolve_local(folder, field='folder')
        files = melee_unlocked.attach_source(char_dir, folder)
        return jsonify({'success': True, 'files': files})
    except path_safety.NotLocalPath as e:
        return jsonify({'success': False, 'error': str(e), 'code': 'not_a_local_path'}), 400
    except melee_unlocked.MeleeUnlockedError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Melee Unlocked source update failed: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@melee_unlocked_bp.route('/api/mex/melee-unlocked/source/<slug>/confirm', methods=['POST'])
def confirm_character_source(slug):
    """Allow the export to build source that came in a package. Body: {sha256}, the digest the
    window showed with the question (the fighters list's `unconfirmed[].sha256` and
    `confirmText`, which names the fighter and where its package came from). A confirmation
    covers those bytes only: when the source changed since, nothing is confirmed (409).
    Window only: an agent cannot vouch for code on the user's behalf."""
    refused = _window_only()
    if refused:
        return refused
    char_dir = _character_dir(slug)
    if char_dir is None:
        return jsonify({'success': False, 'error': 'Custom character not found.'}), 404
    shown = str((request.json or {}).get('sha256') or '').strip().lower()
    if not shown:
        return jsonify({'success': False, 'error': 'Say which source you were shown (sha256).'}), 400
    try:
        record = melee_unlocked.confirm_source(char_dir, shown)
        logger.info(f'Melee Unlocked: the user confirmed the source of {slug} ({record["sha256"][:12]}) '
                    f'from {record["origin"]}')
        return jsonify({'success': True, 'source': record})
    except melee_unlocked.MeleeUnlockedError as e:
        return jsonify({'success': False, 'error': str(e), 'code': 'source_changed'}), 409


def _rows(rows):
    return [{'name': r['name'], 'slug': r['slug'], 'plugin': r['ident'] + melee_unlocked.PLUGIN_EXTENSION}
            for r in rows]


@melee_unlocked_bp.route('/api/mex/melee-unlocked/fighters', methods=['GET'])
def list_fighters():
    """The open project's custom fighters: those a plugin can be built for (their C is in the
    Vault and a person vouched for it), those whose C came in a package and waits for the
    user's confirmation (`unconfirmed`: origin, sha256, reason, confirmText) and those with no
    C at all."""
    project_path = get_current_project_path()
    if not project_path:
        return jsonify({'success': False, 'error': 'No project is open.'}), 400
    try:
        with_source, without_source = melee_unlocked.collect_fighters(project_path, CUSTOM_CHARACTERS_PATH)
        trusted, unconfirmed = melee_unlocked.split_by_trust(with_source)
        return jsonify({'success': True, 'buildable': _rows(trusted), 'withoutSource': _rows(without_source),
                        'unconfirmed': [{**melee_unlocked.unconfirmed_row(r), 'plugin': row['plugin']}
                                        for r, row in zip(unconfirmed, _rows(unconfirmed))]})
    except Exception as e:
        logger.error(f'Melee Unlocked fighter list failed: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@melee_unlocked_bp.route('/api/mex/melee-unlocked/export', methods=['POST'])
def export_fighters():
    """Start a `melee_unlocked_export` job that builds the plugins. Body: {destination, kitPath,
    gccBin}. The plugins land in <destination>/fighters/, the folder Melee Unlocked reads beside
    its game library. Returns {success, job_id}; the job reports each fighter as it is built
    (`progress`, `detail`) and its result is {abi, folder, built, failed, unconfirmed,
    withoutSource}: `unconfirmed` are the fighters not built because their source came in a
    package and was not confirmed, with the reason.

    The folders are checked before the job starts, so a wrong one is a 400 here and not a
    failed job."""
    refused = _window_only()
    if refused:
        return refused
    project_path = get_current_project_path()
    if not project_path:
        return jsonify({'success': False, 'error': 'No project is open.'}), 400
    body = request.json or {}
    destination = (body.get('destination') or '').strip()
    if not destination:
        return jsonify({'success': False, 'error': 'No destination folder was given.'}), 400
    kit_path, gcc_bin = body.get('kitPath'), body.get('gccBin')
    try:
        path_safety.local_path(destination, field='destination')
        melee_unlocked.read_kit(kit_path)
        with_source, _without = melee_unlocked.collect_fighters(project_path, CUSTOM_CHARACTERS_PATH)
        buildable, _unconfirmed = melee_unlocked.split_by_trust(with_source)
        if buildable:
            melee_unlocked.check_compiler(gcc_bin)

        def run(job):
            with tempfile.TemporaryDirectory(prefix='nucleus_mu_') as work:
                return melee_unlocked.export_plugins(
                    project_path, CUSTOM_CHARACTERS_PATH, kit_path, gcc_bin, destination, work,
                    progress=lambda fraction, detail: job.progress(fraction, detail))

        job_id = jobs.start(EXPORT_KIND, run, label='Melee Unlocked export', single=True,
                            params={'destination': destination, 'fighters': len(buildable)})
        return jsonify({'success': True, 'job_id': job_id})
    except jobs.JobBusy as busy:
        return jsonify({'success': False, 'error': 'A Melee Unlocked export is already running.',
                        'job_id': busy.job_id}), 409
    except path_safety.NotLocalPath as e:
        return jsonify({'success': False, 'error': str(e), 'code': 'not_a_local_path'}), 400
    except melee_unlocked.MeleeUnlockedError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Melee Unlocked export failed: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
