"""
Play routes (the engines are play/shelf.py, play/client.py, play/launch.py).

GET    /api/play/shelf                 the shelf: every entry, plus what Play needs to know to start one
GET    /api/play/client                the client games start from (the hand-picked folder, else the installed
                                       Nucleus) and whether it is usable
POST   /api/play/client                {folder}: verify and save a hand-picked folder ('' forgets it)
POST   /api/play/client/verify         {folder}: verify without saving
GET    /api/play/client/managed        the Nucleus client Play installs itself (play/managed.py status): not
                                       installed, installing (progress), installed (version), update
                                       available, failed (reason). Reads no network
POST   /api/play/client/managed/check  {force}: read the signed client feed now (at most every 30 minutes
                                       unless force) and answer the status
POST   /api/play/client/managed/install  install the newest Nucleus (a play_client_install job)
POST   /api/play/client/managed/update   update the installed Nucleus (the same job; the installed one plays on)
POST   /api/play/client/managed/cancel   stop the running install or update (what it downloaded is removed)
GET    /api/play/account               the Slippi account the games sign in with (name and code only)
POST   /api/play/launch/<id>           {target, slippiPath}: start a play_launch job
POST   /api/play/settings-window       open the game's own settings window (a play_launch job)
GET    /api/play/replay                whether a Tracker replay can be watched in Melee Unlocked now
POST   /api/play/replay                {path}: watch a Tracker replay there (a play_launch job)
POST   /api/play/reveal/<id>           open an entry's data folder (saves, log, crash files)
POST   /api/play/shelf/add             {artifactId | patchId | bundleId, name, description, replace}: put a
                                       finished export, or a Vault patch or bundle, on the shelf
                                       (a shelf_add job, play/adding.py); multipart with a `cover`
                                       picture when one was chosen. 409 code already_on_shelf when
                                       an added game has that name; `replace` (its id) replaces it
GET    /api/play/shelf/same?name=      the added game a new one of that name would replace, or null
PATCH  /api/play/shelf/<id>          {name, description, engine}: rename or describe an added game,
                                     or choose its engine ('auto', 'source', 'compat')
DELETE /api/play/shelf/<id>            remove an added game, its disc and its saves
GET    /api/play/shelf/<id>/cover      an added game's cover (PNG); for the built-in Vanilla, the banner of
                                       the user's own disc (adding.disc_banner)
POST   /api/play/shelf/<id>/cover      multipart `cover`: a new cover, decoded and kept as PNG

Every <id> is looked up on the shelf (shelf.get); no route makes a path from a request
string. Everything that changes what runs, starts a program, or changes the shelf is
the window's alone: it needs the window's own key (core/ui_channel.py), not only the
backend token.
"""

import logging
import os
import subprocess
import sys

from flask import Blueprint, jsonify, request, send_file

from core import jobs, ui_channel
from core.child_env import child_environment
from play import adding, client, launch, managed, routing, shelf

logger = logging.getLogger(__name__)

play_bp = Blueprint('play', __name__)


def _error(message, status=400, **extra):
    return jsonify({'success': False, 'error': message, **extra}), status


def _window_only():
    """Refuse a request that is not the app's own window (core/ui_channel.py), else None."""
    refusal = ui_channel.window_refusal(request.headers)
    if refusal is None:
        return None
    code, status = refusal
    if code == 'automation_caller':
        return _error('Games are started and changed from the Nucleus window, not by an agent.', status, code=code)
    if code == 'ui_approval_channel_unavailable':
        return _error('This Nucleus has no window channel to check, so Unlocked cannot start or change anything here.',
                      status, code=code)
    return _error('Only the Nucleus window can do that.', status, code=code)


def _body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _platform():
    if client.supported():
        return {'supported': True, 'message': None}
    return {'supported': False, 'message': 'Nucleus Unlocked is Windows only for now.'}


@play_bp.route('/api/play/shelf', methods=['GET'])
def get_shelf():
    folder = client.configured()
    try:
        entries = [routing.with_engine(shelf.public(e), e, folder) for e in shelf.entries()]
    except shelf.ShelfError as e:
        return _error(str(e), e.status)
    has_disc = launch.retail_iso() is not None
    gone = None if has_disc else launch.missing_iso()   # a recorded disc whose file is no longer there
    for entry in entries:
        if entry['id'] == shelf.VANILLA_ID:
            entry['hasCover'] = has_disc        # the disc's banner, read when it is first asked for
    return jsonify({'success': True, 'entries': entries, 'platform': _platform(),
                    'client': client.status(), 'managed': managed.status(),
                    'retailIso': {'set': has_disc, 'missing': str(gone) if gone is not None else None},
                    'gameSettings': shelf.game_settings_status(folder),
                    'running': launch.running_entry()})


@play_bp.route('/api/play/client', methods=['GET'])
def get_client():
    return jsonify({'success': True, 'client': client.status()})


@play_bp.route('/api/play/client', methods=['POST'])
def set_client():
    refused = _window_only()
    if refused:
        return refused
    try:
        return jsonify({'success': True, 'client': client.save(_body().get('folder'))})
    except client.ClientError as e:
        return _error(str(e))


@play_bp.route('/api/play/client/verify', methods=['POST'])
def verify_client():
    refused = _window_only()
    if refused:
        return refused
    return jsonify({'success': True, **client.verify(_body().get('folder'))})


@play_bp.route('/api/play/client/managed', methods=['GET'])
def managed_status():
    return jsonify({'success': True, 'managed': managed.status()})


@play_bp.route('/api/play/client/managed/check', methods=['POST'])
def managed_check():
    refused = _window_only()
    if refused:
        return refused
    return jsonify({'success': True, 'managed': managed.check(force=_body().get('force') is True)})


def _managed_start(action):
    refused = _window_only()
    if refused:
        return refused
    try:
        return jsonify({'success': True, 'job_id': managed.start(action)})
    except jobs.JobBusy as busy:
        return _error('Nucleus Unlocked is already being installed. Wait for it to finish.', 409, job_id=busy.job_id)
    except managed.InstallError as e:
        return _error(str(e), e.status)


@play_bp.route('/api/play/client/managed/install', methods=['POST'])
def managed_install():
    return _managed_start('install')


@play_bp.route('/api/play/client/managed/update', methods=['POST'])
def managed_update():
    return _managed_start('update')


@play_bp.route('/api/play/client/managed/cancel', methods=['POST'])
def managed_cancel():
    refused = _window_only()
    if refused:
        return refused
    return jsonify({'success': True, 'cancelled': managed.cancel()})


@play_bp.route('/api/play/account', methods=['GET'])
def account():
    from tracker.store.identity import get_netplay_identity
    try:
        identity = get_netplay_identity()
    except Exception:  # noqa: BLE001 - no Slippi setup reads as "not signed in"
        logger.debug('Play: Slippi identity not read', exc_info=True)
        identity = {}
    name, code = identity.get('displayName'), identity.get('connectCode')
    return jsonify({'success': True, 'signedIn': bool(name or code), 'displayName': name or None,
                    'connectCode': code or None})


@play_bp.route('/api/play/launch/<entry_id>', methods=['POST'])
def launch_entry(entry_id):
    refused = _window_only()
    if refused:
        return refused
    body = _body()
    target = body.get('target')
    if target is not None and target not in shelf.TARGETS:
        return _error('That game cannot be played there.')
    try:
        job_id = launch.launch(entry_id, target=target, slippi_path=body.get('slippiPath'))
        return jsonify({'success': True, 'job_id': job_id})
    except jobs.JobBusy as busy:
        return _error('A game is already running. Close it first.', 409, job_id=busy.job_id)
    except (launch.PlayError, shelf.ShelfError) as e:
        return _error(str(e), e.status)


@play_bp.route('/api/play/settings-window', methods=['POST'])
def settings_window():
    refused = _window_only()
    if refused:
        return refused
    try:
        return jsonify({'success': True, 'job_id': launch.open_settings_window()})
    except jobs.JobBusy as busy:
        return _error("A game is running. Its settings are in the game's own menu (F1).", 409, job_id=busy.job_id)
    except launch.PlayError as e:
        return _error(str(e), e.status)


@play_bp.route('/api/play/replay', methods=['GET'])
def replay_status():
    if not client.supported():
        return jsonify({'success': True, 'available': False, 'reason': 'Nucleus Unlocked is Windows only for now.'})
    return jsonify({'success': True, **launch.replay_status()})


@play_bp.route('/api/play/replay', methods=['POST'])
def watch_replay():
    refused = _window_only()
    if refused:
        return refused
    try:
        return jsonify({'success': True, 'job_id': launch.watch_replay(_body().get('path'))})
    except jobs.JobBusy as busy:
        return _error('A game is running. Close it first.', 409, job_id=busy.job_id)
    except launch.PlayError as e:
        return _error(str(e), e.status)


@play_bp.route('/api/play/reveal/<entry_id>', methods=['POST'])
def reveal(entry_id):
    refused = _window_only()
    if refused:
        return refused
    try:
        folder = shelf.data_dir(shelf.get(entry_id))
    except shelf.ShelfError as e:
        return _error(str(e), e.status)
    folder.mkdir(parents=True, exist_ok=True)
    path = os.path.normpath(str(folder))
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', path], env=child_environment())
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path], env=child_environment())
    else:
        subprocess.Popen(['xdg-open', path], env=child_environment())
    return jsonify({'success': True})


_ADD_FIELDS = ('artifactId', 'patchId', 'bundleId', 'name', 'description', 'replace')
_TOO_LARGE = f'That picture is too large. The limit is {shelf.MAX_COVER_BYTES // (1024 * 1024)} MB.'


def _add_request():
    """(fields, cover) of an add: JSON, or multipart when a cover picture was chosen. The cover
    comes back decoded and re-encoded as PNG (shelf.encode_cover) or None; it is bytes, never a
    path. Raises ShelfError for a picture that is too large or not one."""
    if request.mimetype != 'multipart/form-data':
        return _body(), None
    if (request.content_length or 0) > shelf.MAX_COVER_BYTES + 64 * 1024:
        raise shelf.ShelfError(_TOO_LARGE, 413)
    fields = {key: request.form.get(key) for key in _ADD_FIELDS if request.form.get(key) is not None}
    upload = request.files.get('cover')
    if upload is None:
        return fields, None
    return fields, shelf.encode_cover(upload.stream.read(shelf.MAX_COVER_BYTES + 1))


@play_bp.route('/api/play/shelf/add', methods=['POST'])
def add_entry():
    refused = _window_only()
    if refused:
        return refused
    try:
        body, cover = _add_request()
    except shelf.ShelfError as e:
        return _error(str(e), e.status)
    sources = [key for key in ('artifactId', 'patchId', 'bundleId') if body.get(key) is not None]
    if len(sources) != 1:
        return _error('Say which export, Vault patch or Vault bundle to add.')
    common = {'name': body.get('name'), 'description': body.get('description'), 'cover': cover,
              'replace': body.get('replace')}
    try:
        if sources[0] == 'artifactId':
            job_id = adding.start(body['artifactId'], **common)
        else:
            job_id = adding.start_from_vault('patch' if sources[0] == 'patchId' else 'bundle', body[sources[0]],
                                             **common)
        return jsonify({'success': True, 'job_id': job_id})
    except jobs.JobBusy as busy:
        return _error('A game is already being added to the shelf. Wait for it to finish.', 409, job_id=busy.job_id)
    except shelf.ShelfError as e:
        return _error(str(e), e.status, **e.details())


@play_bp.route('/api/play/shelf/same', methods=['GET'])
def same_game():
    """The added game a new one called `name` would replace (the export page asks before it builds)."""
    existing = shelf.same_game(request.args.get('name', ''))
    if existing is not None:
        existing = {**existing, 'running': existing['id'] == launch.running_entry()}
    return jsonify({'success': True, 'existing': existing})


@play_bp.route('/api/play/shelf/<entry_id>', methods=['PATCH'])
def change_entry(entry_id):
    refused = _window_only()
    if refused:
        return refused
    body = _body()
    try:
        entry = shelf.update(entry_id, name=body.get('name'), description=body.get('description'),
                             engine_choice=body.get('engine'))
        return jsonify({'success': True, 'entry': routing.with_engine(shelf.public(entry), entry,
                                                                      client.configured())})
    except shelf.ShelfError as e:
        return _error(str(e), e.status)


@play_bp.route('/api/play/shelf/<entry_id>', methods=['DELETE'])
def remove_entry(entry_id):
    refused = _window_only()
    if refused:
        return refused
    if entry_id and entry_id == launch.running_entry():
        return _error('That game is running. Close it first.', 409)
    try:
        shelf.remove(entry_id)
        return jsonify({'success': True})
    except shelf.ShelfError as e:
        return _error(str(e), e.status)


@play_bp.route('/api/play/shelf/<entry_id>/cover', methods=['GET'])
def get_cover(entry_id):
    entry = shelf.find(entry_id)
    if entry is not None and entry['id'] == shelf.VANILLA_ID:
        path = adding.disc_banner()
    else:
        path = shelf.cover_path(entry) if entry is not None else None
    if path is None:
        return _error('No cover.', 404)
    response = send_file(path, mimetype='image/png', max_age=0)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@play_bp.route('/api/play/shelf/<entry_id>/cover', methods=['POST'])
def set_cover(entry_id):
    refused = _window_only()
    if refused:
        return refused
    if (request.content_length or 0) > shelf.MAX_COVER_BYTES + 64 * 1024:
        return _error(_TOO_LARGE, 413)
    upload = request.files.get('cover')
    if upload is None:
        return _error('No picture was sent.')
    raw = upload.stream.read(shelf.MAX_COVER_BYTES + 1)
    try:
        entry = shelf.set_cover(entry_id, raw)
        return jsonify({'success': True, 'entry': shelf.public(entry)})
    except shelf.ShelfError as e:
        return _error(str(e), e.status)
