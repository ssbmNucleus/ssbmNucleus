"""Local Nucleus assistant API. Protected by the app's normal backend auth."""
import json
import copy
import re
from flask import Blueprint, jsonify, request, Response, send_file, current_app
from core import config, gates
from randall.assistant import approvals, engine, live_runs, main_model, recipes, store, tools
from randall.website import website_posts
from shared import mod_files
from randall.delivery import game_tests
from randall.recolor import stage_lab

assistant_bp = Blueprint('assistant', __name__, url_prefix='/api/assistant')

# No arbitrary context instructions; only these app-owned fields are used.
CONTEXT_FIELDS = ('page', 'character', 'stage', 'selection', 'files', 'editor', 'task', 'fighter')


def import_fighters():
    """The fighters a model import can target, by the app's names, sorted.

    The fighters rigswap targets (model_import/chat/import_job.fighters: every
    fighter but the Ice Climbers pair). The panel's fighter picker offers exactly
    these (/status `import_fighters`).
    """
    from randall.model_import.chat.import_job import fighters
    return sorted(fighters())


def _import_fighter(value):
    """`value` as one of `import_fighters()` (any case; the catalog's long-name
    aliases such as 'Captain Falcon' allowed), else None."""
    if not isinstance(value, str) or not value.strip() or len(value) > 40:
        return None
    from shared.modellab.fighter_catalog import _canonical
    wanted = ' '.join(value.split()).casefold()
    for name in import_fighters():
        if name.casefold() == wanted:
            return name
    alias = _canonical(' '.join(value.split()))
    return alias if alias in import_fighters() else None


# A vault stage variant id, exactly as shared/rendering/stage_editor.open_stage accepts one.
_VARIANT_ID = re.compile(r'[\w .()-]{1,180}')


def _stage_item(item):
    """One `selection` entry of kind 'stage' as the Stage Lab can open it, else None.

    The panel's stage picker sends one of two shapes (recolor/stage_start.picked_stage):
    a vault stage variant {kind: 'stage', stage, id, name}, whose archive is
    <storage>/das/<folder>/<id>.zip (the id the Vault's stage list serves), or the
    stock stage {kind: 'stage', stage, vanilla: true, name}. `stage` is a stage code
    the Stage Lab supports (/status `recolor_stages`; its vault folder is read as the
    code). The entry comes back with exactly those keys, `name` trimmed (the stage's
    own name when missing). A stage it does not support, a malformed or missing
    variant, or an entry that is both a variant and stock is None.
    """
    stages = stage_lab.supported_stages()
    wanted = item.get('stage')
    row = next((s for s in stages if wanted in (s['code'], s['folder'])), None) if isinstance(wanted, str) else None
    if row is None:
        return None
    name = item.get('name')
    name = ' '.join(name.split())[:120] if isinstance(name, str) and name.strip() else row['name']
    variant = item.get('id')
    if item.get('vanilla') is True:
        return {'kind': 'stage', 'stage': row['code'], 'vanilla': True, 'name': name} if variant is None else None
    if (isinstance(variant, str) and _VARIANT_ID.fullmatch(variant) and variant.strip(' .')
            and (config.STORAGE_PATH / 'das' / row['folder'] / f'{variant}.zip').is_file()):
        return {'kind': 'stage', 'stage': row['code'], 'id': variant, 'name': name}
    return None


def _selection(selection):
    """`selection` with each stage entry checked by `_stage_item` (dropped when it fails).

    Every other entry (a vault costume, a stock costume, a website variant) is
    passed through untouched, exactly as before stages could be picked.
    """
    kept = []
    for item in selection:
        if isinstance(item, dict) and item.get('kind') == 'stage':
            item = _stage_item(item)
            if item is None:
                continue
        kept.append(item)
    return kept


def _app_context(context):
    """A message's context cut down to the app-owned fields.

    `task` is the chat's declared task. An id this build does not offer as a
    startable task (recipes.startable: /status `tasks` with `available` true) is
    dropped silently: the chat is then an ordinary chat rather than a refused
    message. A starting point that is not built yet (stage_import, create_character) is dropped the
    same way, so a crafted request cannot start one.

    `fighter` is the fighter picked for a model import (the panel's fighter
    picker). It is kept as the roster's own name, or dropped silently when it
    names no fighter an import can target (the import then asks, as it does for
    a chat without a pick).

    `selection`: a picked stage is checked here (`_stage_item`); costume entries
    are passed through as they always were.
    """
    kept = {k: context[k] for k in CONTEXT_FIELDS if k in context}
    if 'task' in kept and recipes.task_id(kept['task']) not in recipes.startable(tools.SCHEMAS):
        del kept['task']
    if isinstance(kept.get('selection'), list):
        kept['selection'] = _selection(kept['selection'])
    if 'fighter' in kept:
        fighter = _import_fighter(kept['fighter'])
        if fighter:
            kept['fighter'] = fighter
        else:
            del kept['fighter']
    return kept


@assistant_bp.before_request
def check_enabled():
    if not gates.enabled('assistant'):
        return jsonify(error='The assistant is not available in this build.'), 404


@assistant_bp.get('/status')
def status():
    return jsonify(ready=True, credential_source='patreon', model=main_model.MODEL,
                   tools=[s['function']['name'] for s in tools.SCHEMAS],
                   # What a chat can be started as: the empty-state tiles render
                   # this list, in this order; a row with `available` false is
                   # shown disabled ("Use MCP") and is never startable.
                   tasks=recipes.launchable(tools.SCHEMAS),
                   # The fighters the "Import a character model" picker offers (and `fighter` accepts).
                   import_fighters=import_fighters(),
                   # The stages the "Retexture a stage" picker offers (and a picked stage must be one of).
                   recolor_stages=stage_lab.supported_stages(),
                   active_run_id=getattr(live_runs.active_run(), 'id', None))


@assistant_bp.get('/app-context')
def app_context_read():
    """One live application snapshot for the panel and for the turn about to start.

    Local API auth only -- no AI credential, no model call, no writes. The engine
    reads the same function directly rather than spending a round asking Randall
    to look up state the app already has.
    """
    from randall.assistant import app_context
    return jsonify(app_context.read())


@assistant_bp.get('/deliveries')
def deliveries_list():
    """What Randall has put into the user's game, newest first.

    The public view: names, states and receipt IDs, no absolute paths. Each row
    carries a live `achieved` and `can_undo`, both derived by re-reading what is
    actually on disk rather than from a stored flag.
    """
    from randall.delivery import deliver
    return jsonify(deliveries=deliver.public_deliveries(
        project_id=request.args.get('project_id') or None,
        limit=min(int(request.args.get('limit', 20) or 20), 100)))


@assistant_bp.post('/deliveries/<receipt_id>/undo')
def delivery_undo(receipt_id):
    """Take one delivery back out, from the card, without spending a model turn.

    Returns the SAME envelope the `undo_delivery` tool returns, so the result
    card renders one shape whichever way the undo was asked for. The work is a
    restoration of a change the user already approved, which is why it needs no
    second approval -- and it is itself resumable, so a card may call it again.
    """
    from randall.delivery import deliver
    try:
        return jsonify(deliver.undo_delivery(receipt_id))
    except deliver.DeliveryError as exc:
        return jsonify(error=str(exc)), 400


@assistant_bp.post('/destination')
def designate_destination():
    """Record "this is my game" from an explicit user action in the UI.

    Body: {kind, label?, project_id?, output_iso_path?, play_mode?,
           played_iso_path?, start_from_clean?, player_path?, make_default?}.
    A refusal here is the played-ISO rule talking: its message is the question
    the user has to answer, not an error to retry.
    """
    from randall.delivery import destination as destinations
    data = request.json or {}
    try:
        record = destinations.designate(
            data.get('kind'), label=data.get('label'), project_id=data.get('project_id'),
            output_iso_path=data.get('output_iso_path'), play_mode=data.get('play_mode'),
            played_iso_path=data.get('played_iso_path'),
            start_from_clean=bool(data.get('start_from_clean')),
            player_path=data.get('player_path'),
            make_default=data.get('make_default', True),
            destination_id=data.get('destination_id'))
    except destinations.DestinationError as exc:
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(success=True, destination=destinations.public(record))


@assistant_bp.post('/destination/<destination_id>/activation')
def destination_activation(destination_id):
    """Re-check the Slippi Launcher selection, or record "I selected this file".

    `by_user` is the user's word and is recorded as `user_confirmed` -- never as
    a check that passed.
    """
    from randall.delivery import destination as destinations
    try:
        state = destinations.confirm_activation(
            destination_id, by_user=bool((request.json or {}).get('by_user')))
    except destinations.DestinationError as exc:
        return jsonify(success=False, error=str(exc)), 404
    return jsonify(success=True, activation=state)


@assistant_bp.get('/chats')
def chats():
    return jsonify(chats=store.list_chats())


@assistant_bp.get('/chats/<chat_id>')
def chat_get(chat_id):
    chat = store.get(chat_id)
    if not chat:
        return jsonify(error='Conversation not found.'), 404
    with live_runs._lock:
        runs = [run for run in live_runs._runs.values() if run.chat_id == chat_id]
        if runs:
            chat['messages'] = copy.deepcopy(runs[0].messages)
        else:
            chat = store.get(chat_id) or chat
    active = runs[0] if runs else None
    if not active:
        live_runs.settle_dead_run(chat['messages'])
    return jsonify(**chat, active_run_id=getattr(active, 'id', None),
                   pending_inputs=store.pending_inputs(chat_id),
                   reply_run_id=next((run.id for run in runs if not run.direct_call), None),
                   download_run_ids=[run.id for run in runs if run.direct_call])


@assistant_bp.delete('/chats/<chat_id>')
def chat_delete(chat_id):
    with live_runs._lock:
        if live_runs.active_run(chat_id):
            return jsonify(error='Stop the running turn before deleting this conversation.'), 409
        if game_tests.has_active_session(current_app._get_current_object(), chat_id):
            return jsonify(error='Stop the in-game session before deleting this conversation.'), 409
        store.delete(chat_id)
    return jsonify(success=True)


@assistant_bp.post('/chat')
def chat():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='A JSON object is required.'), 400
    message = body.get('message')
    context = body.get('context', {})
    chat_id = body.get('chat_id')
    input_id = body.get('input_id')
    if input_id is not None and (not chat_id or not isinstance(input_id, str) or not re.fullmatch(r'[a-f0-9]{32}', input_id)):
        return jsonify(error='Invalid queued message.'), 400
    run_id = body.get('run_id')
    if run_id is not None and (not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id)):
        return jsonify(error='Invalid run id.'), 400
    request_key = body.get('api_key')
    account_token = body.get('account_token')
    if account_token is not None:
        try:
            website_posts._account_token(account_token)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    if request_key is not None and (not isinstance(request_key, str) or not request_key.strip()
                                   or len(request_key) > 512 or '\n' in request_key or '\r' in request_key):
        return jsonify(error='Invalid AI credential.'), 400
    if (not isinstance(message, str) or not message.strip() or len(message) > 8000
            or not isinstance(context, dict) or len(json.dumps(context)) > 12000
            or (chat_id is not None and (not isinstance(chat_id, str) or not re.fullmatch(r'[a-f0-9]{32}', chat_id)))
            or 'allow_changes' in body):
        return jsonify(error='Invalid message, conversation or context.'), 400
    context = _app_context(context)
    try:
        if 'files' in context:
            context['files'] = mod_files.attachment_context(context['files'])
        runtime = {'app': current_app._get_current_object(), 'settings': game_tests.settings(body.get('game_settings'))}
        run = engine.start(chat_id, message.strip(), context, request_key=request_key, account_token=account_token, input_id=input_id,
                           game_runtime=runtime, run_id=run_id)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409
    return Response(live_runs.stream(run), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@assistant_bp.route('/chats/<chat_id>/game-tests/<session_id>', methods=['GET', 'DELETE'])
def game_test_session(chat_id, session_id):
    try:
        return jsonify(game_tests.snapshot(current_app._get_current_object(), chat_id, session_id,
                                            stop=request.method == 'DELETE'))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@assistant_bp.post('/chats/<chat_id>/inputs')
def input_add(chat_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {'id', 'message', 'context', 'mode'}:
        return jsonify(error='Provide a message, context and queue or steer mode.'), 400
    input_id, message, context, mode = body.get('id'), body.get('message'), body.get('context', {}), body.get('mode', 'queue')
    if (not re.fullmatch(r'[a-f0-9]{32}', chat_id) or not isinstance(input_id, str)
            or not re.fullmatch(r'[a-f0-9]{32}', input_id) or not isinstance(message, str)
            or not message.strip() or len(message) > 8000 or not isinstance(context, dict)
            or len(json.dumps(context)) > 12000 or mode not in ('queue', 'steer')):
        return jsonify(error='Invalid queued message or context.'), 400
    context = _app_context(context)
    try:
        if 'files' in context:
            context['files'] = mod_files.attachment_context(context['files'])
        return jsonify(**live_runs.submit_input(chat_id, input_id, message.strip(), context, mode))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@assistant_bp.route('/chats/<chat_id>/inputs/<input_id>', methods=['PATCH', 'DELETE'])
def input_change(chat_id, input_id):
    changes = {'remove': True}
    if request.method == 'PATCH':
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or not body or set(body) - {'message', 'mode'}
                or ('message' in body and (not isinstance(body['message'], str) or not body['message'].strip() or len(body['message']) > 8000))
                or ('mode' in body and body['mode'] not in ('queue', 'steer'))):
            return jsonify(error='Edit the message or choose queue or steer mode.'), 400
        changes = {**({'content': body['message'].strip()} if 'message' in body else {}),
                   **({'mode': body['mode']} if 'mode' in body else {})}
    try:
        return jsonify(**live_runs.change_input(chat_id, input_id, **changes))
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409


@assistant_bp.post('/chats/<chat_id>/inputs/batch')
def input_batch(chat_id):
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or set(body) != {'ids', 'action'} or body['action'] not in ('send', 'clear')
            or not isinstance(body['ids'], list) or not 1 <= len(body['ids']) <= 20
            or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value) for value in body['ids'])):
        return jsonify(error='Choose queued message IDs and send or clear.'), 400
    return jsonify(**live_runs.change_inputs(chat_id, body['ids'], remove=body['action'] == 'clear'))


@assistant_bp.post('/runs/<run_id>/cancel')
def cancel(run_id):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        return jsonify(error='Invalid run id.'), 400
    return jsonify(cancelled=live_runs.cancel(run_id))


@assistant_bp.post('/website/vault-status')
def website_vault_status():
    from randall.website.vault_presence import recover_history, vault_status
    body = request.get_json(silent=True)
    ids = body.get('post_ids') if isinstance(body, dict) else None
    if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(
            type(value) is not int or not 0 < value < 2 ** 31 for value in ids):
        return jsonify(error='Choose between 1 and 500 website post IDs.'), 400
    recover_history()
    return jsonify(in_vault=vault_status(ids))


@assistant_bp.post('/website/like-status')
def website_like_status():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {'post_id', 'account_token'}:
        return jsonify(error='Provide a post ID and Nucleus account session.'), 400
    try:
        return jsonify(website_posts.website_like_status(**body))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@assistant_bp.post('/website/download')
def website_download():
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or set(body) - {'chat_id', 'post_id', 'file_id', 'items'}
            or ('items' in body and ('post_id' in body or 'file_id' in body))
            or ('post_id' not in body and 'items' not in body)
            or (body.get('chat_id') is not None and (not isinstance(body['chat_id'], str)
                or not re.fullmatch(r'[a-f0-9]{32}', body['chat_id'])))):
        return jsonify(error='Provide a website post ID and optional conversation/file ID.'), 400
    try:
        run = (engine.start_bulk_download(body.get('chat_id'), body['items']) if 'items' in body
               else engine.start_download(body.get('chat_id'), body['post_id'], body.get('file_id')))
        return jsonify(chat_id=run.chat_id, run_id=run.id)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409


@assistant_bp.post('/website/like')
def website_like():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {'post_id', 'liked', 'account_token'}:
        return jsonify(error='Provide a post ID, desired like state and Nucleus account session.'), 400
    try:
        return jsonify(website_posts.set_website_mod_like(**body))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@assistant_bp.post('/chats/<chat_id>/approvals/<approval_id>')
def approval_decide(chat_id, approval_id):
    body = request.get_json(silent=True)
    # The choice is checked against what THIS approval offered (approvals.decide
    # does that, with the stored option ids). A hardcoded list here predated the
    # menu choices and returned 400 for legitimate ones, so an ambiguous menu
    # file could never be confirmed (2026-09-22 review JJ, 5).
    if (not isinstance(body, dict) or set(body) - {'decision', 'choice'}
            or body.get('decision') not in ('approve', 'deny')
            or ('choice' in body and not isinstance(body['choice'], str))
            or ('choice' in body and not 0 < len(body['choice']) <= 60)):
        return jsonify(error='Provide approve or deny, and an offered download choice if applicable.'), 400
    try:
        return jsonify(tool=live_runs.decide_approval(chat_id, approval_id, body['decision'], body.get('choice')))
    except approvals.UnofferedChoice as exc:
        return jsonify(error=str(exc)), 400
    except ValueError as exc:
        return jsonify(error=str(exc)), 404
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409


@assistant_bp.get('/chats/<chat_id>/approvals/<approval_id>/files')
def approval_files(chat_id, approval_id):
    try:
        return jsonify(live_runs.download_files(chat_id, approval_id,
            choice=request.args.get('choice', 'all'), query=request.args.get('query', ''),
            offset=int(request.args.get('offset', 0)), kind=request.args.get('kind', 'mods')))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409


@assistant_bp.post('/actions/<action_id>/undo')
def undo(action_id):
    with live_runs._lock:
        if live_runs.active_run():
            return jsonify(error='Wait for the current turn to finish before undoing.'), 409
        try:
            return jsonify(tools.undo_organization(action_id))
        except ValueError as exc:
            return jsonify(error=str(exc)), 409


@assistant_bp.get('/previews/<artifact_id>')
def preview(artifact_id):
    if not re.fullmatch(r'[a-f0-9]{32}', artifact_id):
        return jsonify(error='Preview not found.'), 404
    path = config.STORAGE_PATH / 'assistant' / 'previews' / f'{artifact_id}.png'
    if not path.is_file():
        return jsonify(error='Preview not found.'), 404
    return send_file(path, mimetype='image/png')


@assistant_bp.get('/viewer-updates/<update_id>')
def viewer_update_colours(update_id):
    """The stream messages of a colour edit the lab's renderer took in place (continuity.keep_colours):
    the workbench's 3D view sends them to its own renderer."""
    from randall.assistant import continuity
    path = continuity.colours_file(update_id)
    if path is None:
        return jsonify(error='Viewer update not found.'), 404
    return send_file(path, mimetype='application/json')


@assistant_bp.post('/files')
def attach_file():
    upload = request.files.get('file')
    if upload is None:
        return jsonify(error='Choose a file to attach.'), 400
    try:
        return jsonify(file=mod_files.register_stream(upload.stream, upload.filename))
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400


@assistant_bp.get('/files/<file_id>')
def mod_file(file_id):
    try:
        path, info = mod_files.resolve(file_id)
        image = info['extension'] == '.png' and request.args.get('preview') == '1'
        response = send_file(path, mimetype='image/png' if image else 'application/octet-stream',
                            as_attachment=not image, download_name=info['name'])
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    except ValueError as exc:
        return jsonify(error=str(exc)), 404
