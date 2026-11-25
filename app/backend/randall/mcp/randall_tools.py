"""Randall's own tools (assistant/tools.py) as MCP tools: the same schemas, the same ``tools.prepare`` and
``tools.execute``. Nothing here re-implements a tool.

* **Listed:** every name in ``tools.REGISTRY`` that ``tools.SCHEMAS`` advertises, minus ``HIDDEN``, with its
  description, its parameters as the inputSchema, MCP annotations, and a few MCP-only arguments (``EXTRA_ARGS``)
  for what the chat gets from the window instead (a download option, the Slippi Dolphin folder).
* **Approval tools:** in the app an approval tool shows a preview card and runs only after the user's click. An
  MCP client asks its user before every tool call, so that ask IS the approval: the call is prepared and applied
  in one go through the same path as the card (``tools.prepare`` -> ``approvals.Grant`` -> ``tools.execute``),
  taking the option the card would preselect unless ``choice`` names another. The reply says what was approved.
* **One at a time:** the app runs one chat reply at a time, so its tools never run concurrently; MCP calls take
  the same turn here (``_lock``), whatever the client sends in parallel.
"""
import json
import logging
import threading
import time

from core.metadata import load_metadata
from core.stages import ALL_STAGES, LEGAL_STAGES
from randall.assistant import approvals, refusals, tools

from . import content, credits, window

# Not offered over MCP: liking a website mod needs the Nucleus account sign-in the app's window holds (the chat
# hides it too when the window sent no account token).
HIDDEN = frozenset({'set_website_mod_like'})
READ_ONLY = frozenset({'search_vault', 'search_vault_stages', 'game_screenshot', 'inspect_mod',
                       'present_vault_skins', 'search_docs', 'search_website_mods', 'inspect_website_mod', 'list_projects', 'inspect_project', 'hsdraw_capabilities',
                       'inspect_mod_file'})
DESTRUCTIVE = frozenset({'deliver_to_game', 'undo_delivery', 'organize_skins', 'install_project_mods',
                         'undo_organization'})
OPEN_WORLD = frozenset({'search_website_mods', 'inspect_website_mod', 'download_website_mod',
                        'download_website_mods', 'generate_material'})
# The chat the play sessions of MCP calls run under (game_tests keys its sessions by chat).
MCP_CHAT = 'mcp'

_CHOICE = {'type': 'string', 'description': (
    'MCP only. The option to take when this download offers one (the app shows them on its approval card): '
    '"default" (default variant only) or "all" (every variant) for a mod with colour variants, or the key of an '
    'importer question. Omit it to take the option the app preselects.')}
EXTRA_ARGS = {
    'download_website_mod': {
        'choice': _CHOICE,
        'slippi': {'type': 'string', 'enum': ['fix', 'import_as_is'], 'description': (
            'MCP only. When the download holds costumes that are not Slippi-safe: "fix" them (default, as the app '
            'preselects) or add them "import_as_is".')}},
    'download_website_mods': {
        'choice': {'type': 'string', 'enum': ['fix', 'import_as_is'], 'description': (
            'MCP only. "fix" unsafe skins throughout the batch (default) or keep the original files '
            '("import_as_is").')}},
    # No Dolphin argument: the game runs the Slippi Dolphin set in Nucleus Settings (else Slippi Launcher's own),
    # never a program an AI names (security review 11-19, M1).
    'test_in_game': {
        'vanilla_iso_path': {'type': 'string', 'description': (
            'MCP only. The clean Melee 1.02 disc; defaults to the one Nucleus recorded.')},
        'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': 40, 'description': (
            'MCP only, with action=status: wait up to this long for the session to start playing (or end) before '
            'answering, so no sleeping between status calls is needed.')}},
}
GAME_WAIT_MAX = 40      # under calls.INLINE_SECONDS: a waiting status call answers itself, never as a call job

# The chat's own words that are wrong over MCP (no chat turns, no live card), replaced in what tools/list says.
# A test checks each old text is still in the chat's schema, so rewording the chat cannot drop these silently.
REWORD = {
    'test_in_game': (
        ('Start returns a session_id immediately while building; do not poll repeatedly or wait for the user to '
         'finish. The live card shows progress.',
         'Start returns a session_id at once while its test copy builds (a couple of minutes): call action=status '
         'with wait_seconds, or job_status with that session_id, until it is playing; then game_screenshot shows '
         'the game. Do not wait for the user to finish playing.'),
        ('This tool cannot automate moves or inspect live game images.',
         'This tool cannot automate moves; game_screenshot shows the game window.'),
    ),
    'save_mod_copy': (
        ('a Skin Lab result is saved to the vault automatically when the turn ends, so use this for a separate '
         'copy',
         'over MCP nothing is saved automatically, so this is how a Skin Lab result is kept (skin_lab export, then '
         'this)'),
    ),
}
PARAM_REWORD = {
    ('skin_lab', 'name'): ('apply: a short name for the result ("Fox - Lava"). Over MCP nothing is saved '
                           'automatically: to keep the result, export it and pass the file and a name to '
                           'save_mod_copy.'),
    ('stage_lab', 'name'): ("save: the new vault variant's name. apply: a short name for the result "
                            '("Dreamland - Candy"). Over MCP nothing is saved automatically: to keep the result, '
                            'call action=save with a name.'),
}

APPROVAL_NOTE = (' [MCP] In the app this waits for the user to approve a preview card. Over MCP your client asks '
                 'the user before each call and that is the approval: the preview and the action run in one call, '
                 'and the result says what was approved. Call it only once the user has agreed.')
NOTES = {
    'skin_lab': (' [MCP] There are no chat turns over MCP, so nothing is saved to the vault automatically: to '
                 'keep a result, export it and pass the file to save_mod_copy.'),
    'stage_lab_open': (" [MCP] stage_code is the stage's file code, never a guess: "
                       + ', '.join(f"{stage['name']} {code}" for code, stage in LEGAL_STAGES.items())
                       + '. search_vault_stages lists every code and the stage mods the user saved (variant_id).'),
    'stage_lab': (' [MCP] There are no chat turns over MCP, so nothing is saved to the vault automatically: to '
                  'keep a result, use action=save with a name, then close. In identify, `area` is a surface\'s '
                  'largest share over the game-camera and raised views and `views` gives each: for what a player '
                  'sees (a background, the sky) go by the game camera, views[0], or identify points on that spot. A '
                  'spot with no id is one the id picture cannot read (a glowing or fogged backdrop, such as Final '
                  "Destination's sky), not proof that nothing there can be edited: colour_sources lists every "
                  'object\'s colours ("Group g:i") and highlight shows where a texture is. Describe the result only '
                  'from the render after apply, and say plainly when the render does not show what the user '
                  'asked for.'),
    'test_in_game': (" [MCP] The game opens in its own Dolphin window on the user's screen (there is no chat panel "
                     'or play card over MCP): use action=status to follow a session, and game_screenshot with its '
                     'session_id to see what it shows once it is playing.'),
    'generate_material': (" [MCP] Billed to the signed-in person's Randall usage, as in the app's chat; when "
                          'nobody is signed in to SSBM Nucleus it says so and generates nothing.'),
    'organize_skins': ' [MCP] undo_organization with the returned action_id puts the skins back.',
}

# MCP-only tools for what the chat gets from its window: the Undo on an organize card, attaching a file, and
# the vault's stage list (the chat's stage picker; search_vault is costumes only).
UNDO_ORGANIZATION = {
    'name': 'undo_organization',
    'description': ('Undo one organize_skins action: put the skins back in the folders they were in before. Needs '
                    'the exact action_id organize_skins returned; refuses when the skins changed since.'),
    'inputSchema': {'type': 'object', 'properties': {'action_id': {'type': 'string'}}, 'required': ['action_id'],
                    'additionalProperties': False},
}
ATTACH_FILE = {
    'name': 'attach_file',
    'description': ('Hand Nucleus a file from this computer, the way a user attaches one to a chat: a DAT, ZIP, '
                    'PNG, GLB/glTF, OBJ, SMD, DAE or animation file becomes a working-copy file ID that the file '
                    'tools take (inspect_mod_file, unpack_mod_file, skin_lab_open, hsdraw replace_texture, '
                    'save_mod_copy, ...). The original file is not changed. For a model to import as a costume use '
                    'import_model with the path instead.'),
    'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string',
                                                              'description': 'Absolute path of the file.'}},
                    'required': ['path'], 'additionalProperties': False},
}
SEARCH_VAULT_STAGES = {
    'name': 'search_vault_stages',
    'description': ('Find the stage mods the user already owns (stage skins saved in the vault) and the stage codes '
                    'the Stage Lab takes. One row per stage: name, stage_code, and its saved variants (variant_id, '
                    'name, date added, Slippi result). query matches stage and variant names; omit it for the six '
                    'legal stages plus every stage with a saved variant. Pass stage_code (and variant_id to start '
                    'from a saved one) to stage_lab_open, or to test_in_game kind=stage_skin. search_vault covers '
                    'costumes only. Searching changes nothing.'),
    'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 160}},
                    'additionalProperties': False},
}
GAME_SCREENSHOT = {
    'name': 'game_screenshot',
    'description': ('A picture of a running test_in_game play session: what its Dolphin window shows right now (the '
                    'match, or a menu while it starts). session_id is the one test_in_game start returned; it works '
                    'while status says the session is running. It only reads the window. One moment of the game is '
                    'not a check of the costume, its moves or its Slippi safety.'),
    'inputSchema': {'type': 'object', 'properties': {'session_id': {'type': 'string'}}, 'required': ['session_id'],
                    'additionalProperties': False},
}
EXTRA_TOOLS = (UNDO_ORGANIZATION, ATTACH_FILE, SEARCH_VAULT_STAGES, GAME_SCREENSHOT)

_lock = threading.Lock()
_log = logging.getLogger(__name__)


def _title(name):
    return name.replace('_', ' ').capitalize()


def annotations(name):
    read_only = name in READ_ONLY
    return {'title': _title(name), 'readOnlyHint': read_only,
            **({} if read_only else {'destructiveHint': name in DESTRUCTIVE}),
            'openWorldHint': name in OPEN_WORLD}


def names():
    """The Randall tool names offered over MCP, in the chat's order."""
    advertised = [s['function']['name'] for s in tools.SCHEMAS]
    return [n for n in advertised if n in tools.REGISTRY and n not in HIDDEN] + [t['name'] for t in EXTRA_TOOLS]


def listed():
    """tools/list entries for Randall's tools."""
    out = []
    for schema in tools.SCHEMAS:
        fn = schema['function']
        name = fn['name']
        if name not in tools.REGISTRY or name in HIDDEN:
            continue
        params = json.loads(json.dumps(fn['parameters']))
        params.setdefault('type', 'object')
        params.setdefault('properties', {})
        params['properties'].update(json.loads(json.dumps(EXTRA_ARGS.get(name, {}))))
        description = fn['description']
        for old, new in REWORD.get(name, ()):
            description = description.replace(old, new)
        description += NOTES.get(name, '')
        for (tool, key), text in PARAM_REWORD.items():
            if tool == name and isinstance(params['properties'].get(key), dict):
                params['properties'][key] = dict(params['properties'][key], description=text)
        if tools.REGISTRY[name].policy == 'approval':
            description += APPROVAL_NOTE
        out.append({'name': name, 'description': description, 'inputSchema': params,
                    'annotations': annotations(name)})
    out.extend(dict(tool, annotations=annotations(tool['name'])) for tool in EXTRA_TOOLS)
    return out


def _attach(arguments):
    from pathlib import Path
    from core.path_safety import NotLocalPath, local_path
    from shared import mod_files
    if set(arguments) != {'path'} or not isinstance(arguments['path'], str):
        raise ValueError("Invalid tool arguments. attach_file takes exactly 'path'.")
    try:
        path = Path(local_path(arguments['path'], field='path'))
    except NotLocalPath as refused:
        if refused.reason == 'network':
            raise
        raise ValueError(f"path must be an absolute path: {arguments['path'].strip()}")
    if not path.is_absolute():
        raise ValueError(f'path must be an absolute path: {path}')
    if not path.is_file():
        raise ValueError(f'No file at {path}.')
    with open(path, 'rb') as stream:
        return {'file': mod_files.register_stream(stream, path.name),
                'note': 'A working copy; the original file is unchanged. Pass file.file_id to the file tools.'}


def _game_settings(extras):
    from randall.delivery import game_tests
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    iso = extras.get('vanilla_iso_path')
    if not iso:
        recorded = known_vanilla_iso()
        iso = str(recorded) if recorded else ''
    dolphin = window.slippi_dolphin_path() or ''        # the app's own setting; the AI cannot name a program
    return game_tests.settings({'vanillaIsoPath': str(iso), 'slippiDolphinPath': str(dolphin)})


def _options(name, extras, app):
    """What the chat hands ``tools.execute`` from its run, for an MCP call."""
    if name == 'test_in_game':
        return {'game_runtime': {'app': app, 'settings': _game_settings(extras)}, 'chat_id': MCP_CHAT}
    if name in credits.AI_TOOLS:
        # The chat's own key rule (engine.py image_key), checked now: NoCredits says why nothing was sent.
        return {'image_key': credits.ai_key()}
    if name == 'download_website_mod':
        action = extras.get('slippi') or 'fix'
        return {'safety_review': lambda safety, mod: {'action': action, 'status': 'approved'},
                'cancelled': lambda: False}
    return {}


def _check_extras(name, extras):
    for key, value in extras.items():
        spec = EXTRA_ARGS[name][key]
        if spec.get('type') == 'integer':
            if type(value) is not int or not spec['minimum'] <= value <= spec['maximum']:
                raise ValueError(f"{key} must be a whole number from {spec['minimum']} to {spec['maximum']}.")
            continue
        if not isinstance(value, str) or ('enum' in spec and value not in spec['enum']):
            allowed = f": one of {', '.join(spec['enum'])}" if 'enum' in spec else ''
            raise ValueError(f'{key} must be a string{allowed}.')


def search_vault_stages(arguments):
    """The user's stage skins by stage, from the vault metadata (storage/das/<folder>, stages.<folder>.variants)."""
    if set(arguments) - {'query'}:
        raise ValueError("Invalid tool arguments. search_vault_stages takes only 'query'.")
    query = arguments.get('query', '')
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError('query must be text of at most 160 characters.')
    terms = query.casefold().split()
    saved = load_metadata(default={}).get('stages')
    saved = saved if isinstance(saved, dict) else {}
    rows, total = [], 0
    for code, stage in ALL_STAGES.items():
        entry = saved.get(stage['folder'])
        variants = []
        for variant in (entry.get('variants') if isinstance(entry, dict) else None) or []:
            if (not isinstance(variant, dict) or not isinstance(variant.get('id'), str)
                    or variant.get('type') == 'folder' or variant.get('visible') is False):
                continue
            text = f"{stage['name']} {code} {variant.get('name', '')} {variant['id']}".casefold()
            if all(term in text for term in terms):
                variants.append({'variant_id': variant['id'], 'name': variant.get('name') or variant['id'],
                                 'date_added': variant.get('date_added'),
                                 'slippi_tested': variant.get('slippi_tested'),
                                 'slippi_safe': variant.get('slippi_safe')})
        named = bool(terms) and all(term in f"{stage['name']} {code}".casefold() for term in terms)
        if variants or named or (not terms and code in LEGAL_STAGES):
            rows.append({'stage': stage['name'], 'stage_code': code, 'saved_variants': len(variants),
                         'variants': variants[:50]})
            total += len(variants)
    return {'stages': rows, 'total_variants': total,
            'all_stage_codes': {stage['name']: code for code, stage in ALL_STAGES.items()}}


_PANEL = 'in the panel on the right'


def _no_panel(value):
    """test_in_game's notes say where the game opens for the chat (game_tests._play_note): over MCP it is its own
    Dolphin window."""
    if isinstance(value, str):
        return value.replace(_PANEL, 'in its own Dolphin window on their screen')
    if isinstance(value, dict):
        return {key: _no_panel(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_no_panel(item) for item in value]
    return value


def game_screenshot(arguments):
    """A picture of a running test_in_game play session's Dolphin window. -> an MCP result with the image."""
    import base64
    from core import jobs
    from projects.routes.test_in_game import INGAME_KIND
    from shared.ingame import screenshot
    if set(arguments) != {'session_id'} or not isinstance(arguments['session_id'], str):
        raise ValueError("Invalid tool arguments. game_screenshot takes exactly 'session_id'.")
    session_id = arguments['session_id'].strip()
    record = jobs.get(session_id) if session_id else None
    if not record or record.get('kind') != INGAME_KIND:
        return content.error(f'No in-game test session {session_id!r}. Use the session_id test_in_game start gave.')
    if record.get('status') not in jobs.ACTIVE:
        return content.error(f"That session is not running (it is {record.get('status')}); start it again with "
                             'test_in_game to look at it.')
    pids = [int(value['pid']) for key, value in (record.get('owned') or {}).items()
            if key.startswith('dolphin:') and isinstance(value, dict) and value.get('pid')]
    if not pids:
        return content.error('Its game has not opened yet. Check test_in_game action=status and try again once it '
                             'is playing.')
    for pid in pids:
        png = screenshot.capture_via_printwindow(pid, max_width=960) or screenshot.capture_png(pid, max_width=960)
        if png:
            return {'content': [content.text({'session_id': session_id, 'note': (
                        'What the game window shows now. A picture of one moment: not a check of the costume, '
                        'its moves or its Slippi safety.')}),
                    {'type': 'image', 'data': base64.b64encode(png).decode('ascii'), 'mimeType': 'image/png'}],
                    'isError': False}
    return content.error('Could not capture the game window (it may be minimised or still starting). Try again in a '
                         'moment.')


def _run(name, arguments, app):
    if name == SEARCH_VAULT_STAGES['name']:
        return search_vault_stages(arguments)
    if name == UNDO_ORGANIZATION['name']:
        if set(arguments) != {'action_id'}:
            raise ValueError("Invalid tool arguments. undo_organization takes exactly 'action_id'.")
        return tools.undo_organization(arguments['action_id'])
    if name == ATTACH_FILE['name']:
        return _attach(arguments)
    args = dict(arguments)
    extras = {key: args.pop(key) for key in list(args) if key in EXTRA_ARGS.get(name, {})}
    _check_extras(name, extras)
    extras.pop('wait_seconds', None)        # call() waits; the chat's tool never sees it
    prepared = tools.prepare(name, args)
    grant = approved = None
    if prepared.policy == 'approval':
        preview = json.loads(prepared.preview) or {}
        offered = [option.get('id') for option in preview.get('choices') or [] if isinstance(option, dict)]
        choice = extras.get('choice')
        if choice is not None and choice not in offered:
            raise ValueError(f"choice {choice!r} is not offered here. "
                             + (f"Offered: {', '.join(map(str, offered))}." if offered else 'This call offers none.'))
        if choice is None and offered:
            choice = preview.get('default_choice') if preview.get('default_choice') in offered else offered[0]
        grant = approvals.Grant(prepared.fingerprint, choice)
        approved = {key: preview[key] for key in ('title', 'description', 'question', 'consequence')
                    if preview.get(key)}
        if offered:
            approved['choice'] = choice
            approved['offered'] = offered
    result = tools.execute(prepared, grant, **_options(name, extras, app))
    if name == 'test_in_game':
        result = _no_panel(result)
    if approved and isinstance(result, dict):
        result = {**result, 'approved': approved}
    return result


def call(name, arguments, *, app):
    """One Randall tool call. -> MCP tools/call result."""
    if not isinstance(arguments, dict):
        return content.error('Tool arguments must be an object.')
    if name == GAME_SCREENSHOT['name']:       # only reads a window: it does not wait for another tool's turn
        try:
            return game_screenshot(arguments)
        except ValueError as exc:
            return content.error(str(exc))
    wait = arguments.get('wait_seconds', 0) if name == 'test_in_game' else 0
    if wait and arguments.get('action') != 'status':
        return content.error('wait_seconds goes with action=status.')
    deadline = time.monotonic() + (wait if type(wait) is int and wait > 0 else 0)
    while True:
        result = _locked(name, arguments, app)
        if result is None or time.monotonic() >= deadline or _game_settled(result):
            break
        time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))   # outside the lock: other tools run
    if result is None:
        return _last_error.pop(threading.get_ident())
    window.vault_changed(name, result)
    return content.tool_result(name, result if isinstance(result, dict) else {'result': result})


_last_error = {}


def _locked(name, arguments, app):
    """One run of a tool under the chat's turn lock. -> its result, or None with the MCP error in _last_error."""
    with _lock:
        try:
            return _run(name, arguments, app)
        except (ValueError, TypeError, OSError) as exc:
            _last_error[threading.get_ident()] = content.error(str(exc) or type(exc).__name__)
            return None
        except Exception as exc:  # noqa: BLE001 - said as the chat says it, detail kept for the log
            known = refusals.explain(exc)
            if known is None:
                _log.exception('MCP tool %s failed', name)
                known = refusals.unexpected(exc)
            return known


def _game_settled(result):
    """A test_in_game status that needs no more waiting: playing, ended, or not a session at all."""
    game = result.get('game_test') if isinstance(result, dict) else None
    if not isinstance(game, dict):
        return True
    status = game.get('status') if isinstance(game.get('status'), dict) else {}
    return not game.get('running') or status.get('phase') == 'playing'


def is_game_session(arguments):
    """True when job_status is asked about a test_in_game play session (server.py routes those here)."""
    from core import jobs
    from projects.routes.test_in_game import INGAME_KIND
    job_id = arguments.get('job_id') if isinstance(arguments, dict) else None
    record = jobs.get(job_id.strip()) if isinstance(job_id, str) and job_id.strip() else None
    return bool(record) and record.get('kind') == INGAME_KIND


def game_status(arguments, *, app):
    """job_status for a play session: test_in_game action=status, waiting until it plays (at most GAME_WAIT_MAX)."""
    if set(arguments) - {'job_id', 'wait_seconds'}:
        return content.error("job_status takes 'job_id' and optional 'wait_seconds'.")
    wait = arguments.get('wait_seconds', 25)
    if type(wait) is not int or not 0 <= wait <= 50:
        return content.error('wait_seconds must be a whole number from 0 to 50.')
    return call('test_in_game', {'action': 'status', 'session_id': arguments['job_id'].strip(),
                                 'wait_seconds': min(wait, GAME_WAIT_MAX)}, app=app)
