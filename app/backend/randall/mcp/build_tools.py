"""Collection and build tools over MCP: what the app's Import button, Install page and Export page do, for the
user's own AI (docs/dev/APP_MCP.md "Collection and builds").

Randall's own tools cover costumes (search_vault, install_project_mods, deliver_to_game). These add the rest of
"manage your mods and make builds": importing any mod file from this computer, putting stage skins, custom
characters, custom stages and character extras into a build, the build's music playlists, and exporting the build
as an ISO.

Nothing here re-implements an app operation. Each tool calls the Flask handler behind the button it stands for,
in-process (``_route``; the pattern of randall/delivery/game_tests.py ``_invoke``):

* The vault import is ``POST /api/mex/import/file`` (vault/routes/import_unified) with the file uploaded as the
  window uploads it. The importer's questions are answered the way the app answers them in a batch import
  (frontend ``useFileImport.js`` ``importWithAutoAnswers``): fix Slippi problems, skip what the vault already has,
  take the importer's default kind. Each answer is an optional argument, with that default.
* Install and music handlers act on "the open project". Randall never switches the window's project
  (randall/delivery/projects.py), so the call pins the project the AI named for that one request only: the
  request's ``g.nucleus_project``, which ``core.state._request_project`` reads before the open project (it is what
  ``pin_request_project`` sets for every real request). The window keeps its own project.
* After installing custom characters or stages the Install page re-fits the select-screen grid; that math lives
  in the window, so menu_grid.py is its port, saved through the same layout handlers.
* The export is ``run_export_job`` (the Build button's function) as a background ``iso_export`` app job, shown in
  the app's jobs list; ``job_status`` follows it (server.py hands export job ids here) and ``save_build_iso`` is the
  Save button (``POST /api/mex/export/save``).

Approval: in the app these are buttons the user clicks. Over MCP the client asks its user before each call, so a
call that changes something runs when called (APP_MCP.md "Approval mapping"). Calls that change things run one at
a time (``_lock``).
"""
import threading
import time
from datetime import datetime
from pathlib import Path

from core import config, jobs, state
from core.metadata import load_metadata
from core.stages import ALL_STAGES, LEGAL_STAGE_CODES, STAGES_BY_CODE, slot_mode

from . import content, menu_grid, window
from .model_jobs import WAIT_DEFAULT, WAIT_MAX

_lock = threading.Lock()

_CHANGES = (' It changes the build when called: your client asks the user first, and that is the approval, so say '
            'what it will do before calling it.')
_PROJECT = {'type': 'string', 'description': 'The build: a project id from list_projects (or create_project).'}
_PLAYLIST = {'type': 'string', 'description': (
    'Whose playlist: "menu" (the one menu playlist all menus share) or a tournament stage code: '
    + ', '.join(f"{ALL_STAGES[code]['name']} {code}" for code in LEGAL_STAGE_CODES)
    + '. Other stages have no playlist editor in Nucleus.')}


def _obj(properties, required=()):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            **({'required': list(required)} if required else {})}


def _hints(title, read_only=False, destructive=False):
    hints = {'title': title, 'readOnlyHint': read_only}
    if not read_only:
        hints['destructiveHint'] = destructive
    hints['openWorldHint'] = False
    return hints


TOOLS = [
    {'name': 'import_to_vault',
     'description': (
         "Add a mod file from this computer to the user's vault with Nucleus's own importer (the app's Import "
         'button). It works out what the file is: costumes, stage skins, custom characters and custom stages '
         '(m-ex packages, classic fighter.yml/stage.yml packages too), xdelta patches, .ssbm bundles, menu mods, '
         'character effects, sound banks, and archives of archives. Takes .zip, .7z, .rar, .dat, .usd, .xdelta, '
         '.ssbm and pictures (.png, .jpg, .webp). path is an absolute path; paths takes several files: pictures '
         'picked together go in as one set (a digit pack), anything else is imported one file at a time. The '
         "original file is not changed. When the importer would ask the user something it takes the app's own "
         'answer unless you pass another: slippi (costumes that are not Slippi-safe: "fix", default, or '
         '"import_as_is"), duplicates (already in the vault: "skip", default, or "import_anyway"), kind (a file '
         'that could be more than one kind of mod: the option key; default the importer\'s pick). The result says '
         'what was added with the ids the install tools take, what was asked and answered, and what to call '
         'next. It does not put anything into a build. A big archive can take a while: the call may answer with a '
         'job_id, then poll job_status.'),
     'inputSchema': _obj({
         'path': {'type': 'string', 'description': 'Absolute path of the mod file.'},
         'paths': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {'type': 'string'},
                   'description': 'Several absolute paths, instead of path.'},
         'slippi': {'type': 'string', 'enum': ['fix', 'import_as_is'], 'description': (
             'Costumes that are not Slippi-safe: "fix" them (default, as the app does) or add them as they are.')},
         'duplicates': {'type': 'string', 'enum': ['skip', 'import_anyway'], 'description': (
             'What the vault already has: "skip" it (default) or add a second copy.')},
         'kind': {'type': 'string', 'maxLength': 120, 'description': (
             'Only when the importer asks what the file is (the result of a first call lists the options): the '
             'option key to take.')},
         'title': {'type': 'string', 'maxLength': 120, 'description': (
             'The name for what is imported (default: from the file).')}}),
     'annotations': _hints('Import to vault')},
    {'name': 'search_vault_mods',
     'description': (
         "List the vault's custom characters, custom stages or character extras (effect colours and models), with "
         'the ids the install tools take: kind "custom_characters" (slug, for install_custom_characters), '
         '"custom_stages" (slug, for install_custom_stages) or "extras" (needs character; each extra_type with '
         'its saved extras, extra_id, for install_extra). query filters by name. Costumes are search_vault, stage '
         'skins search_vault_stages. Reading changes nothing.'),
     'inputSchema': _obj({
         'kind': {'type': 'string', 'enum': ['custom_characters', 'custom_stages', 'extras']},
         'query': {'type': 'string', 'maxLength': 160},
         'character': {'type': 'string', 'description': 'For kind extras: the fighter, e.g. "Fox", "Falco".'}},
         ['kind']),
     'annotations': _hints('Search vault mods', read_only=True)},
    {'name': 'install_stage_skin',
     'description': (
         'Put a stage skin from the vault into a build (the Install page > Stages). stage_code and variant_id '
         'come from search_vault_stages. On the six tournament stages it is added as one more alternate of the '
         "stage through Dynamic Alternate Stages, beside the vanilla look and the build's other alternates; if "
         'the build does not have Dynamic Alternate Stages yet it is set up first (the app asks for that once per '
         'build; the result says so). On every other stage the skin replaces the stage in that build (the app '
         'can put the vanilla stage back). Stages added as new stages are custom stages: install_custom_stages. '
         'Only the build changes; to play it call export_build (or deliver_to_game for costumes). '
         'inspect_project_stages shows what a build has.' + _CHANGES),
     'inputSchema': _obj({'project_id': _PROJECT,
                          'stage_code': {'type': 'string', 'description': 'e.g. GrNBa (search_vault_stages).'},
                          'variant_id': {'type': 'string', 'description': "The stage skin's variant_id."}},
                         ['project_id', 'stage_code', 'variant_id']),
     'annotations': _hints('Install stage skin', destructive=True)},
    {'name': 'install_custom_characters',
     'description': (
         "Add custom characters from the vault to a build as new fighters, with their costumes, victory theme and "
         'announcer call (the Install page > Add character). slugs come from search_vault_mods '
         'kind=custom_characters. Then, as the app does, the character select grid is re-fitted to the new '
         'roster, which moves every icon to the automatic layout (a hand-made layout is replaced). It takes a '
         'minute or more: the call may answer with a job_id, then poll job_status.' + _CHANGES),
     'inputSchema': _obj({'project_id': _PROJECT,
                          'slugs': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {'type': 'string'}}},
                         ['project_id', 'slugs']),
     'annotations': _hints('Install custom characters', destructive=True)},
    {'name': 'install_custom_stages',
     'description': (
         'Add custom stages from the vault to a build as new stages, with their music (the Install page > '
         'Stages > Custom stages). slugs come from search_vault_mods kind=custom_stages. Then, as the app does, '
         'the stage select pages after the first are re-fitted six icons wide (their hand-made layout is '
         'replaced; the vanilla page stays).' + _CHANGES),
     'inputSchema': _obj({'project_id': _PROJECT,
                          'slugs': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {'type': 'string'}}},
                         ['project_id', 'slugs']),
     'annotations': _hints('Install custom stages', destructive=True)},
    {'name': 'install_extra',
     'description': (
         "Put a saved character extra (an effect's colours, such as Fox's laser or Falco's shine, or a model "
         "such as Falco's gun) into a build (the Install page > a fighter > Extras). character, extra_type and "
         "extra_id come from search_vault_mods kind=extras. It replaces that effect's current look in the build "
         '(the app can put the vanilla one back).' + _CHANGES),
     'inputSchema': _obj({'project_id': _PROJECT, 'character': {'type': 'string'},
                          'extra_type': {'type': 'string'}, 'extra_id': {'type': 'string'}},
                         ['project_id', 'character', 'extra_type', 'extra_id']),
     'annotations': _hints('Install extra', destructive=True)},
    {'name': 'inspect_project_stages',
     'description': (
         "What a build has on its stages: per tournament stage whether Dynamic Alternate Stages is set up and its "
         'alternates; the other stages whose skin is not vanilla (with a count per state); and the custom stages '
         'added to it. Fighters and costumes are inspect_project. It changes nothing, except what the Stages page '
         'also does when it lists alternates: old-style .usd alternate files are renamed to .dat.'),
     'inputSchema': _obj({'project_id': _PROJECT}, ['project_id']),
     'annotations': _hints('Inspect project stages', read_only=True)},
    {'name': 'get_music_playlist',
     'description': (
         "A build's music playlist: the menu playlist, or a tournament stage's. Each track has music_id, name and "
         'chance (play chances add up to 100). For a stage with no playlist of its own the tracks are its '
         'vanilla songs and vanilla is true. Reading changes nothing.'),
     'inputSchema': _obj({'project_id': _PROJECT, 'playlist': _PLAYLIST}, ['project_id', 'playlist']),
     'annotations': _hints('Get music playlist', read_only=True)},
    {'name': 'set_music_playlist',
     'description': (
         "Replace a build's playlist with entries [{music_id, chance}] (the music editor's weights, remove and "
         'Restore Vanilla). music_ids are the ones get_music_playlist shows (any playlist of this build). '
         'Chances are rescaled to add up to 100. An empty list puts a stage back to its vanilla music; the menu '
         'playlist needs at least one song. To add a new song use add_music_track.' + _CHANGES),
     'inputSchema': _obj({'project_id': _PROJECT, 'playlist': _PLAYLIST,
                          'entries': {'type': 'array', 'maxItems': 64, 'items': _obj({
                              'music_id': {'type': 'integer', 'minimum': 0},
                              'chance': {'type': 'integer', 'minimum': 0, 'maximum': 100}},
                              ['music_id', 'chance'])}},
                         ['project_id', 'playlist', 'entries']),
     'annotations': _hints('Set music playlist', destructive=True)},
    {'name': 'add_music_track',
     'description': (
         "Add a song from this computer to a build's playlist (the music editor's Add songs): path is an absolute "
         'path to a .wav, .mp3, .ogg, .m4a, .flac, .hps, .brstm or .dsp file. Nucleus converts it to game music '
         "and appends it at an equal share; the other songs' chances shrink to fit. A stage still on vanilla "
         'music keeps its vanilla songs beside it. One song per call: add several one after another, never in '
         'parallel.' + _CHANGES),
     'inputSchema': _obj({'project_id': _PROJECT, 'playlist': _PLAYLIST,
                          'path': {'type': 'string', 'description': 'Absolute path of the audio file.'},
                          'name': {'type': 'string', 'maxLength': 80,
                                   'description': 'The track name (default: the file name).'}},
                         ['project_id', 'playlist', 'path']),
     'annotations': _hints('Add music track')},
    {'name': 'export_build',
     'description': (
         'Build a playable ISO from a build (the Export page > Build ISO). It starts an export job in Nucleus and '
         'answers with its job_id at once: call job_status with it until status is done (each call waits up to '
         f'{WAIT_DEFAULT} s; an export takes a few minutes), then save_build_iso to put the ISO where the user '
         'wants it. Until then the ISO sits in Nucleus\'s own output folder, which is emptied when Nucleus starts. '
         'csp_compression (0.1 to 1.0) defaults to what the app recommends for the build\'s costume count; '
         "color_smash defaults to false. The build's mods are not changed; like the Build button it first applies "
         'its routine repairs to the build (the codes every build needs, old alternate-stage file names).'),
     'inputSchema': _obj({'project_id': _PROJECT,
                          'filename': {'type': 'string', 'maxLength': 120, 'description': (
                              'The ISO file name (default: the build name and the date).')},
                          'csp_compression': {'type': 'number', 'minimum': 0.1, 'maximum': 1.0},
                          'color_smash': {'type': 'boolean'}},
                         ['project_id']),
     'annotations': _hints('Export build')},
    {'name': 'save_build_iso',
     'description': (
         "Save a finished export_build ISO to a place on this computer (the Export page's Save). destination is "
         'an absolute path: a folder (the ISO keeps its file name) or a path ending in .iso. It writes over a '
         'file only if Nucleus saved that file before; it refuses to touch the clean Melee ISO or any file '
         'Nucleus did not make.' + ' Your client asks the user first, and that is the approval.'),
     'inputSchema': _obj({'job_id': {'type': 'string', 'description': "export_build's job_id."},
                          'destination': {'type': 'string'}}, ['job_id', 'destination']),
     'annotations': _hints('Save build ISO', destructive=True)},
]
NAMES = tuple(tool['name'] for tool in TOOLS)
READ_ONLY = frozenset(tool['name'] for tool in TOOLS if tool['annotations']['readOnlyHint'])


# ------------------------------------------------------------------ arguments

def _allowed(arguments, names):
    extra = sorted(set(arguments) - set(names))
    if extra:
        raise ValueError(f"Unknown arguments: {', '.join(extra)}. Accepted: {', '.join(names)}.")


def _text(arguments, key, *, required=True, limit=400):
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} must be a nonempty string.')
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f'{key} is too long (at most {limit} characters).')
    return value


def _choice(arguments, key, allowed, default):
    value = arguments.get(key, default)
    if value not in allowed:
        raise ValueError(f"{key} must be one of: {', '.join(allowed)}.")
    return value


def _file(value, key='path'):
    from core.path_safety import NotLocalPath, local_path
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} must be an absolute file path.')
    # The request-path gate, before anything opens it: an SMB open offers the user's hash, and \??\UNC\...
    # reaches a share without looking absolute.
    try:
        path = Path(local_path(value, field=key))
    except NotLocalPath as refused:
        if refused.reason == 'network':
            raise
        raise ValueError(f'{key} must be an absolute path: {value.strip()}')
    if not path.is_absolute():
        raise ValueError(f'{key} must be an absolute path: {path}')
    if not path.is_file():
        raise ValueError(f'No file at {path}.')
    return path


def _project(project_id):
    """The build list_projects named ``project_id``: {id, name, path, current}."""
    from randall.delivery import projects
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError('project_id must be a project id from list_projects.')
    match = next((p for p in projects.list_projects()['projects'] if p['id'] == project_id.strip()), None)
    if match is None:
        raise ValueError('No project with that id. Call list_projects for the ids.')
    return match


def _about(project):
    return {'id': project['id'], 'name': project['name']}


def _stage_code(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('stage_code must be a stage code such as GrNBa (search_vault_stages lists them).')
    wanted = value.strip().casefold()
    code = next((c for c in STAGES_BY_CODE if c.casefold() == wanted), None)
    if code is None:
        raise ValueError(f'{value!r} is not a stage code. search_vault_stages lists every code.')
    return code


def _playlist(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('playlist must be "menu" or a tournament stage code.')
    wanted = value.strip().casefold()
    if wanted == 'menu':
        return 'menu'
    code = next((c for c in LEGAL_STAGE_CODES if c.casefold() == wanted), None)
    if code is None:
        raise ValueError('playlist must be "menu" or one of the tournament stage codes: '
                         + ', '.join(LEGAL_STAGE_CODES) + '. Other stages have no playlist editor in Nucleus.')
    return code


# ------------------------------------------------------------------ the app's handlers, in-process

def _route(app, view, *, project=None, method='POST', body=None, form=None, files=None, query=None, args=None):
    """Run one of the app's own route handlers in this process, as the window's request would. -> (status, json).

    ``project`` pins the build this request acts on (``g.nucleus_project``, read by core.state before the open
    project), so a handler written for the open project acts on that one and the window keeps its own. ``files``
    is [(stream, filename)], sent as the multipart ``file`` field the way the window uploads."""
    from flask import g
    options = {'method': method}
    if query:
        options['query_string'] = query
    if files is not None:
        data = dict(form or {})
        data['file'] = list(files)
        options['data'] = data
        options['content_type'] = 'multipart/form-data'
    elif method != 'GET':
        options['json'] = body if body is not None else {}
    with app.test_request_context('/', **options):
        if project is not None:
            g.nucleus_project = (Path(project), state.get_project_generation())
        response = app.make_response(view(**(args or {})))
        data = response.get_json(silent=True)
        return response.status_code, data if isinstance(data, dict) else {}


def _check(status, data, what):
    """A handler's answer, or ValueError with its own words."""
    if status >= 400 or data.get('success') is False:
        failed = '; '.join(f"{f.get('slug') or f.get('name')}: {f.get('error')}"
                           for f in (data.get('failed') or [])[:10] if isinstance(f, dict))
        message = str(data.get('error') or f'{what} failed (HTTP {status}).')
        raise ValueError((message + (f' ({failed})' if failed else ''))[:1000])
    return data


def _upload(app, view, paths, *, project=None, form=None, args=None):
    handles = [open(path, 'rb') for path in paths]
    try:
        return _route(app, view, project=project, form=form, args=args,
                      files=[(handle, path.name) for handle, path in zip(handles, paths)])
    finally:
        for handle in handles:
            handle.close()


# ------------------------------------------------------------------ import_to_vault

_STAGE_CODES_BY_NAME = {stage['name']: code for code, stage in ALL_STAGES.items()}
_MAX_ASKS = 4      # one file can trip more than one question (useFileImport.js loops four times too)


def _import_unit(app, paths, *, slippi, duplicates, kind, title):
    from vault.routes.import_unified import routes as import_routes
    actions, answered, notes = {}, {}, []
    for _ in range(_MAX_ASKS):
        form = {}
        if 'slippi' in actions:
            form['slippi_action'] = actions['slippi']
        if 'duplicates' in actions:
            form['duplicate_action'] = actions['duplicates']
        for key, value in (actions.get('hints') or {}).items():
            if value is not None:
                form[key] = str(value)
        if title:
            form['custom_title'] = title
        status, data = _upload(app, import_routes.import_file, paths, form=form)
        asked = data.get('type')
        if asked == 'slippi_dialog' and 'slippi' not in actions:
            actions['slippi'] = slippi
            answered['slippi'] = {'question': 'Some costumes are not Slippi-safe.', 'answer': slippi,
                                  'unsafe': [f"{c.get('character')} {c.get('color')}"
                                             for c in (data.get('unsafe_costumes') or [])[:20]]}
            continue
        if asked == 'duplicate_dialog' and 'duplicates' not in actions:
            actions['duplicates'] = duplicates
            answered['duplicates'] = {'question': str(data.get('message') or 'Already in the vault.'),
                                      'answer': duplicates}
            continue
        if asked == 'choice_dialog' and 'hints' not in actions:
            options = [o for o in data.get('options') or [] if isinstance(o, dict) and o.get('key')]
            offered = [str(o['key']) for o in options]
            question = {'question': str(data.get('question') or '')[:500], 'default': data.get('default'),
                        'options': [{'key': str(o['key'])[:120], 'label': str(o.get('label') or '')[:160],
                                     'description': str(o.get('description') or '')[:300]} for o in options[:12]]}
            if kind is not None and kind not in offered:
                return {'files': [p.name for p in paths], 'imported_count': 0, 'vault_changed': False,
                        'error': f'kind {kind!r} is not one of the options the importer offers for this file. '
                                 'Nothing was imported.', 'asked': question}
            key = kind or (data.get('default') if data.get('default') in offered else offered[0] if offered else None)
            if key is None:
                break
            actions['hints'] = next(o.get('hints') or {} for o in options if str(o['key']) == key)
            answered['kind'] = dict(question, answer=key)
            continue
        break
    else:
        return {'files': [p.name for p in paths], 'imported_count': 0, 'vault_changed': False,
                'error': 'The importer kept asking questions; nothing more was imported. Import it in the app.',
                'answered': answered}
    if kind is not None and 'kind' not in answered:
        notes.append('kind was not needed: the importer recognised the file by itself.')
    summary = _import_summary(data, status)
    summary['files'] = [p.name for p in paths]
    if answered:
        summary['answered'] = answered
    if notes:
        summary['notes'] = notes
    return summary


def _import_summary(payload, status):
    """The importer's answer, trimmed, with what was added named by the ids the other tools take."""
    kind = payload.get('type')
    imported = payload.get('imported_count', 1 if payload.get('success') else 0)
    out = {'type': kind, 'imported_count': imported,
           'message': str(payload.get('message') or payload.get('error') or '')[:1000]}
    for key in ('types', 'skipped_count', 'fixed_count', 'menu_mod_type', 'converted_from'):
        if payload.get(key) not in (None, [], 0):
            out[key] = payload[key]
    added = {}
    costumes = [{'character': c.get('character'), 'skin_id': c.get('id'), 'color': c.get('color')}
                for c in payload.get('costumes') or [] if isinstance(c, dict) and c.get('id')]
    if costumes:
        added['costumes'] = costumes[:100]
    if kind == 'stage':
        added['stage_skins'] = [{'stage': s.get('stage'), 'stage_code': _STAGE_CODES_BY_NAME.get(s.get('stage')),
                                 'variant_id': s.get('variant')}
                                for s in payload.get('stages') or [] if isinstance(s, dict) and s.get('variant')]
    if kind == 'custom_character' and isinstance(payload.get('character'), dict):
        added['custom_characters'] = [{'slug': payload['character'].get('slug'),
                                       'name': payload['character'].get('name')}]
    if kind == 'custom_stage':
        entries = payload.get('custom_stages') or [payload.get('stage')]
        added['custom_stages'] = [{'slug': e.get('slug'), 'name': e.get('name')}
                                  for e in entries if isinstance(e, dict)]
    if kind == 'bundle' and payload.get('bundle_id'):
        added['bundles'] = [{'bundle_id': payload['bundle_id'], 'name': payload.get('name')}]
    if kind == 'patch':
        added['patches'] = [{'id': p.get('id'), 'name': p.get('name')} for p in payload.get('patches') or []
                            if isinstance(p, dict)]
    if kind == 'menu_mod':
        added['menu_mods'] = [{'id': m.get('id'), 'name': m.get('name')} for m in payload.get('mods') or []
                              if isinstance(m, dict)][:50]
    if kind == 'effect':
        effects = payload.get('effects') or ([payload] if payload.get('id') else [])
        added['extras'] = [{'character': e.get('character'), 'extra_type': e.get('effect_type'),
                            'extra_id': e.get('id')} for e in effects if isinstance(e, dict) and e.get('id')]
    added = {key: rows for key, rows in added.items() if rows}
    if added:
        out['added'] = added
    if 'imported_count' not in payload:
        out['imported_count'] = sum(len(rows) for rows in added.values()) or imported
    skipped = [{'of': d.get('character'), 'existing_id': (d.get('existing_skin') or {}).get('id'),
                'name': (d.get('existing_skin') or {}).get('name')}
               for d in payload.get('skipped_duplicates') or [] if isinstance(d, dict)]
    if skipped:
        out['already_in_vault'] = skipped[:50]
    failed = [{'name': str(f.get('name') or 'file')[:160], 'error': str(f.get('error') or 'not imported')[:500]}
              for f in payload.get('failed') or [] if isinstance(f, dict)]
    if failed:
        out['failed'] = failed[:20]
    ok = status < 400 and bool(payload.get('success'))
    out['vault_changed'] = bool(ok and out['imported_count'])
    if not ok:
        out['error'] = str(payload.get('error') or payload.get('message') or 'Nothing was imported.')[:1000]
    out['next'] = _import_next(out)
    return out


def _import_next(summary):
    added = summary.get('added') or {}
    steps = []
    if added.get('costumes'):
        steps.append('Costumes: install_project_mods with items [{character, skin_id}] puts them in a build, '
                     'or deliver_to_game updates My game.')
    if added.get('stage_skins'):
        steps.append('Stage skins: install_stage_skin with stage_code and variant_id.')
    if added.get('custom_characters'):
        steps.append('Custom characters: install_custom_characters with the slug.')
    if added.get('custom_stages'):
        steps.append('Custom stages: install_custom_stages with the slug.')
    if added.get('extras'):
        steps.append('Effects: install_extra with character, extra_type and extra_id.')
    if added.get('patches') or added.get('bundles'):
        steps.append('Patches and bundles make a whole game from the clean Melee ISO; they are played from the '
                     "app's vault, not put into a build.")
    if added.get('menu_mods'):
        steps.append("Menu mods are put into a build on the app's Install page > Menus.")
    if summary.get('type') == 'multi':
        steps.append('An archive of archives names only its costumes here: search_vault_stages and '
                     'search_vault_mods show the rest.')
    if not steps and not summary.get('error'):
        steps.append('Nothing new was added (already_in_vault lists what the vault had).')
    return ' '.join(steps)


def import_to_vault(arguments, app):
    from vault.importing.unified.detection import IMAGE_EXTS
    _allowed(arguments, ('path', 'paths', 'slippi', 'duplicates', 'kind', 'title'))
    if ('path' in arguments) == ('paths' in arguments):
        raise ValueError('Pass path (one file) or paths (several), not both and not neither.')
    if 'path' in arguments:
        paths = [_file(arguments['path'])]
    else:
        raw = arguments['paths']
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
            raise ValueError('paths must be a list of 1 to 20 absolute file paths.')
        paths = [_file(value, 'paths') for value in raw]
    options = {'slippi': _choice(arguments, 'slippi', ('fix', 'import_as_is'), 'fix'),
               'duplicates': _choice(arguments, 'duplicates', ('skip', 'import_anyway'), 'skip'),
               'kind': _text(arguments, 'kind', required=False, limit=120),
               'title': _text(arguments, 'title', required=False, limit=120)}
    # The window's rule (useFileImport.js toUnits): pictures picked together are one import, anything else one each.
    if len(paths) > 1 and all(path.suffix.lower() in IMAGE_EXTS for path in paths):
        units = [paths]
    else:
        units = [[path] for path in paths]
    results = [_import_unit(app, unit, **options) for unit in units]
    if len(results) == 1:
        return results[0]
    return {'imported_count': sum(r.get('imported_count') or 0 for r in results),
            'vault_changed': any(r.get('vault_changed') for r in results), 'results': results,
            **({'error': 'None of the files could be imported.'}
               if all(r.get('error') for r in results) else {})}


# ------------------------------------------------------------------ search_vault_mods

def _matches(terms, *values):
    text = ' '.join(str(v or '') for v in values).casefold()
    return all(term in text for term in terms)


def search_vault_mods(arguments):
    from core.extra_lookup import get_extra_types, get_storage_character
    from core.extra_types import EXTRA_TYPES
    _allowed(arguments, ('kind', 'query', 'character'))
    kind = _choice(arguments, 'kind', ('custom_characters', 'custom_stages', 'extras'), None)
    query = arguments.get('query', '')
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError('query must be text of at most 160 characters.')
    terms = query.casefold().split()
    data = load_metadata(default={}) or {}
    if kind == 'custom_characters':
        rows = [{'slug': c.get('slug'), 'name': c.get('name'), 'costumes': c.get('costume_count'),
                 'victory_theme': (c.get('victory_theme') or {}).get('name'),
                 'has_announcer': bool(c.get('has_announcer')), 'date_added': c.get('date_added')}
                for c in data.get('custom_characters') or []
                if isinstance(c, dict) and c.get('slug') and c.get('type') != 'folder'
                and _matches(terms, c.get('name'), c.get('slug'))]
        return {'kind': kind, 'total': len(rows), 'custom_characters': rows[:100]}
    if kind == 'custom_stages':
        rows = [{'slug': s.get('slug'), 'name': s.get('name'), 'music_tracks': len(s.get('playlist') or []),
                 'date_added': s.get('date_added')}
                for s in data.get('custom_stages') or []
                if isinstance(s, dict) and s.get('slug') and s.get('type') != 'folder'
                and _matches(terms, s.get('name'), s.get('slug'))]
        return {'kind': kind, 'total': len(rows), 'custom_stages': rows[:100]}
    wanted = _text(arguments, 'character', limit=60).casefold()
    known = sorted({name for name in EXTRA_TYPES}
                   | {other for types in EXTRA_TYPES.values() for t in types for other in t.get('sharedWith', [])})
    character = next((name for name in known if name.casefold() == wanted), None)
    if character is None:
        return {'kind': kind, 'character': arguments['character'], 'extra_types': [],
                'note': 'Nucleus has no extras for that fighter. Fighters with extras: ' + ', '.join(known) + '.'}
    characters = data.get('characters') or {}
    types = []
    for extra in get_extra_types(character):
        if extra.get('part_of'):
            continue                     # edited inside their unit's extras, as the app lists them
        owner = get_storage_character(character, extra['id'])
        saved = ((characters.get(owner) or {}).get('extras') or {}).get(extra['id']) or []
        mods = [{'extra_id': m.get('id'), 'name': m.get('name')} for m in saved
                if isinstance(m, dict) and m.get('id') and _matches(terms, m.get('name'), extra.get('name'))]
        types.append({'extra_type': extra['id'], 'name': extra.get('name'), 'kind': extra.get('type', 'colors'),
                      'saved': mods[:50]})
    return {'kind': kind, 'character': character, 'extra_types': types}


# ------------------------------------------------------------------ install tools

def install_stage_skin(arguments, app):
    from projects.routes import das as das_routes, stage_slots
    from vault.routes import das as vault_das
    _allowed(arguments, ('project_id', 'stage_code', 'variant_id'))
    project = _project(arguments.get('project_id'))
    code = _stage_code(arguments.get('stage_code'))
    variant_id = _text(arguments, 'variant_id', limit=200)
    stage = STAGES_BY_CODE[code]
    path = project['path']
    result = {'project': _about(project), 'stage': stage['name'], 'stage_code': code, 'variant_id': variant_id}
    if slot_mode(code) == 'das':
        status = _check(*_route(app, das_routes.das_get_status, project=path, method='GET'),
                        'Checking Dynamic Alternate Stages')
        set_up = code not in (status.get('installedStages') or [])
        if set_up:
            _check(*_route(app, das_routes.das_install, project=path), 'Setting up Dynamic Alternate Stages')
        listing = _check(*_route(app, vault_das.das_list_storage_variants, method='GET', query={'stage': code}),
                         'Reading the vault')
        variant = next((v for v in listing.get('variants') or []
                        if v.get('type') != 'folder' and v.get('id') == variant_id), None)
        if variant is None:
            raise ValueError(f"'{variant_id}' is not a {stage['name']} skin in the vault. search_vault_stages "
                             'lists them.')
        done = _check(*_route(app, das_routes.das_import_variant, project=path,
                              body={'stageCode': code, 'variantPath': variant['zipPath']}), 'Installing the skin')
        result.update(installed=True, mode='alternate', name=variant.get('name'),
                      file=Path(str(done.get('path') or '')).name or None,
                      dynamic_alternate_stages_set_up_now=set_up,
                      note=(f"Added as an alternate of {stage['name']} in this build"
                            + (' (Dynamic Alternate Stages was set up in it first)' if set_up else '') + '.'))
        if done.get('transformFix'):
            result['stadium_transformations'] = done['transformFix']
            if done['transformFix'].get('recommendation') == 'freeze':
                result['note'] += (" Some of this skin's geometry stays visible during Pokemon Stadium's "
                                   'transformations; the app\'s Stages page can freeze the transformations for '
                                   'this build (not offered over MCP).')
        if done.get('transformationSkins'):
            result['stadium_transformation_skins'] = done['transformationSkins']
    else:
        done = _check(*_route(app, stage_slots.stage_slot_install, project=path, body={'variantId': variant_id},
                              args={'code': code}), 'Installing the skin')
        result.update(installed=True, mode='replace', note=str(done.get('message') or ''),
                      slot={k: v for k, v in (done.get('slot') or {}).items() if k in ('state', 'installed')})
    result['next'] = 'export_build makes a playable ISO of the build.'
    return result


def _refit_css(app, path, added=()):
    from projects.routes.menus import layout as layout_routes
    status, data = _route(app, layout_routes.get_css_layout, project=path, method='GET')
    if status >= 400 or data.get('success') is False:
        return {'refitted': False, 'error': str(data.get('error') or f'HTTP {status}')[:300]}
    icons, template = data.get('icons'), data.get('template')
    if not icons or not template:
        return {'refitted': False, 'note': 'The build has no character select icons to lay out.'}
    alts = (data.get('lload') or {}).get('altExternalIds') or []
    layout = menu_grid.auto_css_layout(icons, template, alts)
    status, saved = _route(app, layout_routes.set_css_layout, project=path, body=layout)
    if status >= 400 or saved.get('success') is False:
        return {'refitted': False, 'error': str(saved.get('error') or f'HTTP {status}')[:300]}
    names = {f.get('externalId'): f.get('name') for f in data.get('fighters') or [] if isinstance(f, dict)}
    order = [names.get(icon.get('fighter')) or f"fighter {icon.get('fighter')}"
             for icon in menu_grid.grid_icons(layout['icons'], alts)]
    cols = layout['template']['iconsPerRow']
    rows = [order[i:i + cols] for i in range(0, len(order), cols)]
    grid = {'refitted': True, 'icons': len(order), 'columns': cols,
            'rows': rows, 'note': 'rows: the select screen top to bottom, each left to right.'}
    where = {name: {'row': i // cols + 1, 'column': i % cols + 1, 'icons_in_row': len(rows[i // cols])}
             for i, name in enumerate(order) if name in set(added)}
    if where:
        grid['added_at'] = where
    return grid


def _refit_sss(app, path):
    from projects.routes.menus import sss as sss_routes
    status, data = _route(app, sss_routes.get_sss_layout, project=path, method='GET')
    if status >= 400 or data.get('success') is False:
        return {'refitted': False, 'error': str(data.get('error') or f'HTTP {status}')[:300]}
    if not data.get('pages'):
        return {'refitted': False, 'note': 'The build has no stage select pages to lay out.'}
    status, saved = _route(app, sss_routes.set_sss_layout, project=path,
                           body={'pages': menu_grid.auto_sss_pages(data['pages'])})
    if status >= 400 or saved.get('success') is False:
        return {'refitted': False, 'error': str(saved.get('error') or f'HTTP {status}')[:300]}
    return {'refitted': True, 'pages': len(data['pages'])}


def _slugs(arguments, section, what):
    raw = arguments.get('slugs')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20 or not all(isinstance(s, str) and s.strip()
                                                                        for s in raw):
        raise ValueError('slugs must be a list of 1 to 20 slugs.')
    slugs = list(dict.fromkeys(s.strip() for s in raw))
    known = {e.get('slug') for e in (load_metadata(default={}) or {}).get(section) or [] if isinstance(e, dict)}
    missing = [s for s in slugs if s not in known]
    if missing:
        raise ValueError(f"Not a {what} in the vault: {', '.join(missing)}. search_vault_mods kind={section} "
                         'lists the slugs.')
    return slugs


def _batch_result(project, data, items_key, grid_key, grid):
    rows = [{k: item.get(k) for k in ('name', 'success', 'internalId', 'error') if item.get(k) is not None}
            for item in data.get(items_key) or [] if isinstance(item, dict)]
    result = {'project': _about(project), 'added': data.get('totalAdded', 0), items_key: rows,
              'message': str(data.get('message') or ''), grid_key: grid}
    if data.get('failed'):
        result['failed'] = data['failed'][:20]
    if data.get('warnings'):
        result['warnings'] = [str(w)[:300] for w in data['warnings'][:20]]
    if not data.get('totalAdded'):
        result['error'] = 'Nothing was added. ' + '; '.join(
            f"{f.get('slug')}: {f.get('error')}" for f in (data.get('failed') or [])[:5])
    result['next'] = 'export_build makes a playable ISO of the build.'
    return result


def install_custom_characters(arguments, app):
    from projects.routes import custom_characters as routes
    _allowed(arguments, ('project_id', 'slugs'))
    project = _project(arguments.get('project_id'))
    slugs = _slugs(arguments, 'custom_characters', 'custom character')
    data = _check(*_route(app, routes.install_custom_characters_batch, project=project['path'],
                          body={'slugs': slugs}), 'Adding the characters')
    added = [f.get('name') for f in data.get('fighters') or [] if isinstance(f, dict) and f.get('success')]
    grid = _refit_css(app, project['path'], added) if data.get('totalAdded') else {'refitted': False}
    return _batch_result(project, data, 'fighters', 'character_select_grid', grid)


def install_custom_stages(arguments, app):
    from projects.routes import custom_stages as routes
    _allowed(arguments, ('project_id', 'slugs'))
    project = _project(arguments.get('project_id'))
    slugs = _slugs(arguments, 'custom_stages', 'custom stage')
    data = _check(*_route(app, routes.install_custom_stages_batch, project=project['path'],
                          body={'slugs': slugs}), 'Adding the stages')
    grid = _refit_sss(app, project['path']) if data.get('totalAdded') else {'refitted': False}
    return _batch_result(project, data, 'stages', 'stage_select_grid', grid)


def install_extra(arguments, app):
    from core.extra_lookup import get_extra_type, get_extra_types
    from projects.routes import extras as extras_routes
    from vault.routes.extras import models as model_routes
    _allowed(arguments, ('project_id', 'character', 'extra_type', 'extra_id'))
    project = _project(arguments.get('project_id'))
    character = _text(arguments, 'character', limit=60)
    extra_type = _text(arguments, 'extra_type', limit=80)
    extra_id = _text(arguments, 'extra_id', limit=200)
    config_ = get_extra_type(character, extra_type)
    if config_ is None:
        offered = ', '.join(t['id'] for t in get_extra_types(character) if not t.get('part_of'))
        raise ValueError(f'{character} has no extra {extra_type!r}. '
                         + (f'Its extras: {offered}.' if offered else 'search_vault_mods kind=extras lists them.'))
    view = model_routes.install_model_extra if config_.get('type') == 'model' else extras_routes.install_extra
    done = _check(*_route(app, view, project=project['path'],
                          body={'character': character, 'extraType': extra_type, 'modId': extra_id}),
                  'Installing the extra')
    result = {'project': _about(project), 'installed': True, 'character': character, 'extra_type': extra_type,
              'extra_id': extra_id, 'next': 'export_build makes a playable ISO of the build.'}
    if done.get('offsetSkips'):
        result['not_written'] = done['offsetSkips'][:20]
        result['note'] = ('Some layers could not be written safely and kept their previous colours (the app '
                          'says the same).')
    return result


def inspect_project_stages(arguments, app):
    from projects.routes import custom_stages as custom_routes, das as das_routes, stage_slots
    _allowed(arguments, ('project_id',))
    project = _project(arguments.get('project_id'))
    path = project['path']
    das = _check(*_route(app, das_routes.das_get_status, project=path, method='GET'), 'Reading the build')
    set_up = set(das.get('installedStages') or [])
    tournament = []
    for code in LEGAL_STAGE_CODES:
        row = {'stage': ALL_STAGES[code]['name'], 'stage_code': code,
               'dynamic_alternate_stages': code in set_up, 'alternates': []}
        if code in set_up:
            listed = _check(*_route(app, das_routes.das_get_stage_variants, project=path, method='GET',
                                    args={'stage_code': code}), 'Reading the build')
            row['alternates'] = [{'name': v.get('displayName') or v.get('name'), 'file': v.get('filename'),
                                  'button': v.get('button')} for v in listed.get('variants') or []]
        tournament.append(row)
    slots = _check(*_route(app, stage_slots.stages_slots, project=path, method='GET'), 'Reading the build')
    changed, counts = [], {}
    for code, slot in (slots.get('slots') or {}).items():
        state_ = slot.get('state') or 'unknown'
        counts[state_] = counts.get(state_, 0) + 1
        if state_ not in ('installed', 'modified'):
            continue
        installed = slot.get('installed') or {}
        changed.append({'stage': ALL_STAGES.get(code, {}).get('name', code), 'stage_code': code, 'state': state_,
                        'skin': {'variant_id': installed.get('id'), 'name': installed.get('name')}
                        if installed else None})
    other = {'changed': changed, 'counts': counts}
    if counts.get('unknown'):
        other['note'] = ('"unknown": Nucleus has no record of the clean Melee ISO to compare with, so it cannot tell '
                         'a vanilla stage from a changed one.')
    custom = _check(*_route(app, custom_routes.list_custom_stages_in_project, project=path, method='GET'),
                    'Reading the build')
    return {'project': _about(project), 'tournament_stages': tournament, 'other_stages': other,
            'custom_stages': [{'name': s.get('name'), 'index': s.get('index')} for s in custom.get('stages') or []]}


# ------------------------------------------------------------------ music

def _music_view(playlist, action):
    from projects.routes import music_playlists as music
    views = {'get': (music.get_menu_music, music.get_stage_music),
             'set': (music.set_menu_music, music.set_stage_music),
             'add': (music.add_menu_track, music.add_stage_track)}[action]
    if playlist == 'menu':
        return views[0], {}
    return views[1], {'stage': playlist}


def _music_result(project, playlist, data):
    result = {'project': _about(project), 'playlist': playlist,
              'tracks': [{k: t.get(k) for k in ('music_id', 'name', 'chance', 'has_file')}
                         for t in data.get('tracks') or [] if isinstance(t, dict)]}
    if playlist != 'menu':
        result['stage'] = ALL_STAGES[playlist]['name']
        result['vanilla'] = bool(data.get('vanilla'))
    return result


def get_music_playlist(arguments, app):
    _allowed(arguments, ('project_id', 'playlist'))
    project = _project(arguments.get('project_id'))
    playlist = _playlist(arguments.get('playlist'))
    view, args = _music_view(playlist, 'get')
    data = _check(*_route(app, view, project=project['path'], method='GET', args=args), 'Reading the playlist')
    return _music_result(project, playlist, data)


def set_music_playlist(arguments, app):
    _allowed(arguments, ('project_id', 'playlist', 'entries'))
    project = _project(arguments.get('project_id'))
    playlist = _playlist(arguments.get('playlist'))
    raw = arguments.get('entries')
    if not isinstance(raw, list) or len(raw) > 64:
        raise ValueError('entries must be a list of at most 64 {music_id, chance}.')
    entries = []
    for entry in raw:
        if (not isinstance(entry, dict) or set(entry) != {'music_id', 'chance'}
                or type(entry['music_id']) is not int or type(entry['chance']) is not int
                or entry['music_id'] < 0 or not 0 <= entry['chance'] <= 100):
            raise ValueError('Each entry is {music_id: a whole number, chance: 0 to 100}.')
        entries.append({'music_id': entry['music_id'], 'chance': entry['chance']})
    view, args = _music_view(playlist, 'set')
    data = _check(*_route(app, view, project=project['path'], body={'entries': entries}, args=args),
                  'Saving the playlist')
    return _music_result(project, playlist, data)


def add_music_track(arguments, app):
    from projects.routes.music_playlists import MUSIC_IMPORT_EXTS
    _allowed(arguments, ('project_id', 'playlist', 'path', 'name'))
    project = _project(arguments.get('project_id'))
    playlist = _playlist(arguments.get('playlist'))
    source = _file(arguments.get('path'))
    if source.suffix.lower() not in MUSIC_IMPORT_EXTS:
        raise ValueError(f"{source.name} is not a song file Nucleus converts: use one of "
                         + ', '.join(sorted(MUSIC_IMPORT_EXTS)) + '.')
    name = _text(arguments, 'name', required=False, limit=80) or source.stem
    view, args = _music_view(playlist, 'add')
    data = _check(*_upload(app, view, [source], project=project['path'], form={'name': name}, args=args),
                  'Adding the song')
    result = _music_result(project, playlist, data)
    result['added'] = name
    return result


# ------------------------------------------------------------------ export

def _iso_name(arguments, project):
    from werkzeug.utils import secure_filename
    given = _text(arguments, 'filename', required=False, limit=120)
    if given:
        stem = given[:-4] if given.lower().endswith('.iso') else given
    else:
        stem = f"{project['name']}_{datetime.now().strftime('%Y-%m-%d_%H-%M')}"     # the Export page's default
    stem = secure_filename(stem) or 'game'
    return f'{stem[:100]}.iso'


def export_build(arguments, app):
    from mexcli.project import MexManager, MexManagerError
    from projects.install.export_job import ExportRequestError, run_export_job
    from projects.routes import project as project_routes
    _allowed(arguments, ('project_id', 'filename', 'csp_compression', 'color_smash'))
    project = _project(arguments.get('project_id'))
    filename = _iso_name(arguments, project)
    compression = arguments.get('csp_compression')
    if compression is None:
        # The Export page seeds its slider from this route; its own fallback is 1.0.
        status, data = _route(app, project_routes.get_recommended_compression, project=project['path'],
                              method='GET')
        compression = data.get('ratio') if status < 400 and isinstance(data.get('ratio'), (int, float)) else 1.0
    elif type(compression) not in (int, float) or not 0.1 <= compression <= 1.0:
        raise ValueError('csp_compression must be a number from 0.1 to 1.0.')
    color_smash = arguments.get('color_smash', False)
    if not isinstance(color_smash, bool):
        raise ValueError('color_smash must be true or false.')
    try:
        manager = MexManager(str(config.MEXCLI_PATH), project['path'])
        started = run_export_job({'filename': filename, 'cspCompression': compression,
                                  'useColorSmash': color_smash, 'texturePackMode': False},
                                 background=True, project_path=Path(project['path']), mex_manager=manager)
    except (ExportRequestError, MexManagerError) as exc:
        raise ValueError(f'The export could not start: {exc}') from exc
    return {'job_id': started['artifactId'], 'status': 'running', 'project': _about(project),
            'filename': filename, 'csp_compression': compression, 'color_smash': color_smash,
            'note': (f'Started; it shows in the app\'s jobs list. Call job_status with this job_id until it is done '
                     f'(each call waits up to {WAIT_DEFAULT} s), then save_build_iso with a destination.')}


def save_build_iso(arguments, app):
    from projects.install.export_job import export_job
    from projects.routes import export as export_routes
    _allowed(arguments, ('job_id', 'destination'))
    job_id = _text(arguments, 'job_id', limit=200)
    record = export_job(job_id)
    if record is None:
        raise ValueError(f'No ISO export {job_id}. Use the job_id export_build gave (exports are forgotten when '
                         'Nucleus restarts).')
    if record.get('status') in jobs.ACTIVE:
        raise ValueError('That ISO is still building. Call job_status with its job_id until it is done.')
    if record.get('status') != 'done':
        raise ValueError(f"That export did not finish ({record.get('status')}): "
                         f"{record.get('error') or 'no ISO was made'}. Run export_build again.")
    filename = (record.get('result') or {}).get('filename') or (record.get('params') or {}).get('filename')
    from core.path_safety import NotLocalPath, local_path
    destination = _text(arguments, 'destination', limit=1000)
    try:
        target = Path(local_path(destination, field='destination'))
    except NotLocalPath as refused:
        if refused.reason == 'network':
            raise
        raise ValueError(f'destination must be an absolute path: {destination}')
    if not target.is_absolute():
        raise ValueError(f'destination must be an absolute path: {target}')
    if target.is_dir():
        target = target / filename
    elif target.suffix.lower() != '.iso':
        raise ValueError('destination must be an existing folder or a path ending in .iso.')
    done = _check(*_route(app, export_routes.save_iso, body={'artifactId': job_id, 'filename': filename,
                                                              'destination': str(target)}), 'Saving the ISO')
    return {'saved': True, 'path': done.get('path') or str(target), 'bytes': done.get('bytes'),
            'note': 'A playable Melee ISO: open it in Slippi Dolphin (or set it as the game in Slippi Launcher).'}


def is_export_job(arguments):
    """True when job_status is asked about an ISO export (server.py routes those here)."""
    from projects.install.export_job import export_job
    job_id = arguments.get('job_id') if isinstance(arguments, dict) else None
    return isinstance(job_id, str) and export_job(job_id.strip()) is not None


def export_status(arguments):
    """job_status for an export_build job: it long-polls like model_jobs.job_status."""
    from projects.install.export_job import export_job
    _allowed(arguments, ('job_id', 'wait_seconds'))
    job_id = _text(arguments, 'job_id', limit=200)
    wait = arguments.get('wait_seconds', WAIT_DEFAULT)
    if type(wait) is not int or not 0 <= wait <= WAIT_MAX:
        raise ValueError(f'wait_seconds must be a whole number from 0 to {WAIT_MAX}.')
    record = export_job(job_id)
    if record is None:
        raise ValueError(f'No ISO export {job_id}.')
    deadline = time.monotonic() + wait
    while record and record.get('status') in jobs.ACTIVE and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        record = export_job(job_id) or record
    progress = record.get('progress')
    summary = {'job_id': job_id, 'status': record.get('status'), 'label': record.get('label'),
               'percent': round(progress * 100) if isinstance(progress, (int, float)) else None,
               'detail': record.get('detail') or None,
               'seconds': round(((record.get('ended_at') or time.time()) - record['started_at']), 1)
               if record.get('started_at') else None}
    if record.get('status') == 'done':
        result = record.get('result') or {}
        summary['result'] = {'filename': result.get('filename'), 'bytes': _size(result.get('path')),
                             'csp_compression': result.get('cspCompression'),
                             'costumes': result.get('costumeCount'),
                             'warnings': [str(w)[:300] for w in (result.get('warnings') or [])[:20]]}
        summary['next'] = ('Call save_build_iso with this job_id and a destination folder or .iso path the user '
                           'chose. The ISO is not kept after Nucleus restarts until it is saved.')
    elif record.get('error'):
        summary['job_error'] = record['error']
    elif record.get('status') in jobs.ACTIVE:
        summary['note'] = 'Still building. Call job_status again.'
    return content.tool_result('export_build', summary,
                               is_error=record.get('status') in ('failed', 'interrupted', 'cancelled'))


def _size(path):
    try:
        return Path(path).stat().st_size if path else None
    except OSError:
        return None


# ------------------------------------------------------------------ dispatch

_RUN = {'import_to_vault': import_to_vault, 'install_stage_skin': install_stage_skin,
        'install_custom_characters': install_custom_characters, 'install_custom_stages': install_custom_stages,
        'install_extra': install_extra, 'inspect_project_stages': inspect_project_stages,
        'get_music_playlist': get_music_playlist, 'set_music_playlist': set_music_playlist,
        'add_music_track': add_music_track, 'export_build': export_build, 'save_build_iso': save_build_iso}


def call(name, arguments, *, app):
    """One build tool call. -> MCP tools/call result."""
    if not isinstance(arguments, dict):
        return content.error('Tool arguments must be an object.')
    try:
        if name == 'search_vault_mods':
            result = search_vault_mods(arguments)
        elif name in READ_ONLY:
            result = _RUN[name](arguments, app)
        else:
            with _lock:          # one change at a time, like the window's own buttons
                result = _RUN[name](arguments, app)
    except (ValueError, TypeError, OSError) as exc:
        return content.error(str(exc) or type(exc).__name__)
    window.vault_changed(name, result)
    return content.tool_result(name, result)


def job_status(arguments):
    try:
        return export_status(arguments)
    except ValueError as exc:
        return content.error(str(exc))
