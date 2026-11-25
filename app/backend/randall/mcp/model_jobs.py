"""The model import over MCP: ``import_model`` and ``fix_import`` start an app job (core/jobs.py) and answer at
once with its id; ``job_status`` reports it (and the call jobs of calls.py).

The job runs the chat's own import (``studio_import.run_import`` -> ``import_job.run``: rigswap as a subprocess,
the costume saved to the vault, the Slippi fix applied), so an import made over MCP is the same import as one made
in a chat. One import runs at a time, and a restart marks an unfinished one interrupted.

While it runs, the window shows a chip in its header: what the user's AI is importing, onto which fighter, where the
import is in a few plain words, and Cancel (frontend randall/assistant/McpImportChip.jsx, fed by the ``job`` socket
event; the job's ``extra`` carries ``model``, the name the costume is saved under, ``fighter``, ``change``, ``step``,
the running card's step in words (import_job.STEPS), and ``asking``, whether an ask waits on the user's AI). The
record's ``detail`` stays rigswap's newest line as it printed it, for ``job_status``; the chip never shows it.
Cancel is ``POST /api/jobs/<id>/cancel``;
``cancel_import`` is the same stop for the user's AI. Either ends rigswap (its process tree, by PID) and saves
nothing: the job ends ``cancelled``, and the chip says so and goes. A stop that comes after the costume was saved
leaves the job ``done`` with it, so "stopped" always means nothing was saved. A job that ends with a costume saved
makes the window read the vault again (App.jsx, ``useMcpImportSaved``), as an import in the chat does.

``source`` is a local file path: the caller is the user's own AI on their own computer, not the chat model, so the
chat's attachments-only rule does not apply. Before a job starts, the texture files the model names are looked for
beside it (or in its ZIP) as in a chat (``import_job.textures_reply``): some missing answers at once with status
``needs_textures`` and starts nothing, unless the call says ``untextured``. A packaged app whose model import tools
are not downloaded (or are out of date) answers ``needs_tools`` at once (``import_job.tools_reply``), in words that
send the user to Settings; the MCP never starts that download itself (docs/dev/MODEL_IMPORT_TOOLS.md).

rigswap's AI asks (which way is up, which part is the head, which fighter fits...) are answered by that same AI,
not by Randall's model and not on anyone's Randall usage: Randall's AI is for Randall in the app. The job gives
rigswap a relay folder (import_job.RELAY_ENV; rigswap/ai.py ``relay``): each ask is written there as
``ask-<id>.json`` (instructions, question, answer schema, the paths of the pictures it would have sent).
``job_status`` shows the open ones with their pictures (status ``needs_answers``) and ``answer_import`` writes the
replies as ``answer-<id>.json``. rigswap checks each against the schema and hands a misfit back
(``problem-<id>.json``, shown as ``refused_answer``); ``done-<id>.json`` closes an ask. Before it writes an answer,
``answer_import`` holds a skeleton answer to the rules rigswap's skeleton reading holds it to after the schema
(model_import/chat/ask_checks.py: an arm named without its hand...) and refuses one that breaks them at once, in
rigswap's words; rigswap would take it and only say so in a new ask. An ask left unanswered for
import_job.RELAY_WAIT_S takes rigswap's default.
"""
import json
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from core import jobs

from . import calls, content

KIND = 'mcp_model_import'
jobs.register_kind(KIND, label='Model import')

WAIT_DEFAULT = 25      # job_status waits this long for a running job by default: a client needs no sleep tool
WAIT_MAX = 50
ASK_PICTURES = content.MAX_IMAGES   # pictures one job_status carries; asks past them wait for the next call
ANSWER_WAIT = 3.0      # answer_import waits this long for rigswap to read its answers (it looks every 0.25 s)
CANCEL_WAIT = 15.0     # cancel_import waits this long for the job to end (import_job: a stop is seen within 0.5 s,
                       # and rigswap's process group gets STOP_GRACE to end on macOS and Linux)
ASK_POLL = 0.5         # seconds: how often a running import's relay is read for an ask waiting on the caller
NEEDS_ANSWERS = 'needs_answers'
_ASKING = ('The importer is waiting on you. For each ask, look at its pictures (attached below, in order, after a '
           'line naming the ask) and answer with answer_import: one JSON object that fits its answer_schema, as its '
           'instructions say. Answer only from what the pictures show; where they do not show it, give the '
           "schema's \"can't tell\" answer. Then call job_status again.")

_FIGHTER = ('The Melee fighter to put the model on, as the app names it (e.g. "Marth", "C. Falcon"). Omit it '
            'and the import picks the fighter the model fits best, and says which and why.')
TOOLS = [
    {'name': 'import_model',
     'description': (
         "Import a 3D model as a Melee costume with Nucleus's model importer and save it to the user's vault as a "
         'new costume (Slippi fix applied). source is an absolute path to the model on this computer: a .zip, '
         'or a GLB/glTF, FBX, DAE or OBJ file (not SMD). It takes a few minutes, so it starts a job and answers '
         'at once with a job_id: call job_status with it until the status is done (each call waits up to '
         f'{WAIT_DEFAULT} seconds for the job, so call it again right away), then read result (saved = the vault '
         'costume; next = what to tell the user). While it runs the importer asks you about the model: '
         f'job_status answers with status {NEEDS_ANSWERS} and the questions with their pictures, and you answer '
         'them with answer_import (you are its AI; no Randall usage is spent). To put the same model on another '
         'fighter, call it again with that fighter: a second costume is saved and the first stays. One import '
         'runs at a time. A model whose materials file or textures are not beside it (or in its ZIP) starts '
         'nothing: the answer has status needs_textures and says which files are missing. When the app has not '
         'downloaded its model '
         'import tools yet, the answer is status needs_tools at once: tell the user to download them in Nucleus '
         '(Settings > AI > Model import tools), then call it again. While it runs the Nucleus window '
         'shows it with a Cancel button; cancel_import stops it from here.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['source'], 'properties': {
         'source': {'type': 'string', 'description': 'Absolute path to the model file or archive.'},
         'fighter': {'type': 'string', 'description': _FIGHTER},
         'name': {'type': 'string', 'description': "The costume's name in the vault (default: the file name)."},
         'untextured': {'type': 'boolean', 'description': (
             'true only when an import_model answer said needs_textures and the user said to import it without '
             'those files anyway.')}}},
     'annotations': {'title': 'Import model', 'readOnlyHint': False, 'destructiveHint': False,
                     'openWorldHint': True}},
    {'name': 'fix_import',
     'description': (
         'Change one thing about a finished import that looks wrong (a part too big or too thin, bent or twisted, '
         'facing backwards, "the legs look wrong", a piece that should not be there or is missing, hair, cloth or '
         'a tail that should swing or hold still): the importer rebuilds it with that change and saves it as a '
         'second costume; the first stays. project is the import\'s project from its job result. It cannot '
         'change textures or colours or add a piece the model never had. Like import_model it starts a job: '
         f'poll job_status and answer its questions ({NEEDS_ANSWERS}) with answer_import.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['project', 'change'],
                     'properties': {
         'project': {'type': 'string', 'description': "The finished import's project id (result.project)."},
         'change': {'type': 'string', 'description': 'What looks wrong, one thing, with the body part named.'},
         'said': {'type': 'string', 'description': "The user's own words, when change is your wording of them."},
         'name': {'type': 'string', 'description': "The new costume's name (default: the import's name and a "
                                                   'number).'}}},
     'annotations': {'title': 'Fix import', 'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}},
    {'name': 'job_status',
     'description': ('The state of a job a tool answered with (import_model, fix_import, export_build, or any call '
                     'that was still running after a while; a test_in_game session_id waits until that game is '
                     'playing): status (queued, running, done, failed, cancelled, '
                     f'interrupted, or {NEEDS_ANSWERS}: an import waiting on your answers, see asks), progress '
                     'lines, and when done its result with its pictures. It waits up to '
                     f'wait_seconds (default {WAIT_DEFAULT}) for a running job to end or ask something before '
                     'answering, so while it runs just call job_status again; no sleeping in between is needed.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['job_id'],
                     'properties': {'job_id': {'type': 'string'},
                                    'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': WAIT_MAX,
                                                     'description': 'How long to wait for a running job to end '
                                                                    f'(default {WAIT_DEFAULT}; 0 answers at once).'}}},
     'annotations': {'title': 'Job status', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'answer_import',
     'description': (
         f'Answer the questions a running import_model or fix_import job asks (job_status status {NEEDS_ANSWERS}, '
         'its asks): for each, one JSON object that fits that ask\'s answer_schema, from what its pictures show. '
         'Several asks can be answered in one call. Each answer is checked at once, against its schema and, for '
         'a skeleton ask, against the rules the importer holds it to (an arm or leg that is named names both its '
         'ends, on joints of the table): accepted, or refused with the reason (answer that ask again; a schema '
         'misfit takes a few tries before the importer uses its default). An ask left unanswered for '
         'ten minutes takes the importer\'s default.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['job_id', 'answers'],
                     'properties': {
         'job_id': {'type': 'string'},
         'answers': {'type': 'array', 'minItems': 1, 'items': {
             'type': 'object', 'additionalProperties': False, 'required': ['ask_id', 'answer'],
             'properties': {'ask_id': {'type': 'string'},
                            'answer': {'type': 'object', 'description': 'The JSON object the ask asked for.'}}}}}},
     'annotations': {'title': 'Answer import', 'readOnlyHint': False, 'destructiveHint': False,
                     'openWorldHint': False}},
    {'name': 'cancel_import',
     'description': (
         'Stop a running import_model or fix_import job: when the user says to stop it, or it is no longer wanted '
         '(the wrong file or fighter, started by mistake). Not for an import that is only slow or waiting on your '
         'answers: answer them instead. The importer stops and nothing is saved. It answers what happened: '
         'stopped (nothing saved), or that the job had already finished, failed or stopped, with what it saved. '
         'The user can also press Cancel on the import shown in the Nucleus window.'),
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['job_id'],
                     'properties': {'job_id': {'type': 'string', 'description': 'The import job (job_id).'}}},
     'annotations': {'title': 'Cancel import', 'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': False}},
]
NAMES = tuple(tool['name'] for tool in TOOLS)


def _text(arguments, key, required=False):
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} must be a nonempty string.')
    return value.strip()


def _unknown(arguments, allowed):
    extra = sorted(set(arguments) - set(allowed))
    if extra:
        raise ValueError(f"Unknown arguments: {', '.join(extra)}. Accepted: {', '.join(allowed)}.")


def _setup_error():
    from randall.model_import.chat import import_job
    found = import_job.setup()
    if isinstance(found, str):
        return ('The model importer is not set up in this copy of Nucleus, so nothing was started '
                f'({found}).')
    return None


def shown(args):
    """What the window's chip names (the job's ``extra``): ``model``, the name the costume is saved under (the call's
    ``name``, else the one the import makes from the file: 'Clank.zip' -> 'Clank'; a change: the import's own),
    ``fighter`` when one is known before rigswap picks, and ``change``, a fix's words."""
    from randall.model_import.chat import import_job, studio_import
    if not args.get('project'):
        name = (args.get('name') or '').strip() or import_job.costume_name(Path(args['source']).name)
        return {'model': name, 'fighter': args.get('fighter'), 'change': None}
    try:
        record = json.loads((studio_import._folder(args['project']) / 'workflow' / import_job.JOB)
                            .read_text(encoding='utf-8'))
    except (OSError, ValueError):
        record = None
    record = record if isinstance(record, dict) else {}
    source = record.get('source')
    return {'model': record.get('name') or (import_job.costume_name(source) if source else args['project']),
            'fighter': record.get('fighter'), 'change': args.get('change')}


def _watch_asks(job, folder, over):
    """While the import runs (until ``over`` is set): ``asking`` on the job's record says whether an ask in relay
    ``folder`` waits on the caller's answer, set each time that changes (the window's chip then says the import is
    waiting on the user's AI). rigswap prints nothing when it asks, so its progress lines cannot say it."""
    asking = False
    while not over.wait(ASK_POLL):
        try:
            now = bool(open_asks(folder))
        except OSError:         # the run ended and its relay folder is going
            now = False
        if now != asking and not over.is_set():
            asking = now
            job.progress(asking=now)


def _start(args, label):
    from randall.model_import.chat import studio_import
    asks = Path(tempfile.mkdtemp(prefix='nucleus-import-asks-'))     # the relay: the caller answers rigswap's asks
    chip = shown(args)

    def work(job):
        job.progress(asks=str(asks), asking=False, **chip)
        over = threading.Event()
        watcher = threading.Thread(target=_watch_asks, args=(job, asks, over), daemon=True, name='mcp-import-asks')
        watcher.start()
        told = []

        def stopping():
            """The import's ``cancelled`` (polled while rigswap runs): the first time it is true the record says
            ``stopping``, so the chip shows the stop however it was asked for (its Cancel, or cancel_import)."""
            if not job.should_stop():
                return False
            if not told:
                told.append(True)
                job.progress(stopping=True)
            return True

        def progress(card):
            # detail: rigswap's newest line as printed (job_status gives it to the AI); step: the chip's words
            lines = [str(line) for line in card.get('progress') or []]
            fighter = {'fighter': card['fighter']} if card.get('fighter') else {}
            job.progress(detail=lines[-1] if lines else None, progress_lines=lines, step=card.get('step'),
                         seconds=card.get('seconds'), project=card.get('project'), **fighter)
        try:
            reply = studio_import.run_import(dict(args), relay=asks, progress=progress, cancelled=stopping)
        finally:
            over.set()
            watcher.join(timeout=4 * ASK_POLL)
            shutil.rmtree(asks, ignore_errors=True)
            # The watcher looks every ASK_POLL: a run that ends right after an answer can end before it saw the ask
            # close, which left ``asking`` true on a finished job. Nothing waits on the user's AI once the run is over.
            job.progress(asking=False)
        # A stop that came after the vault save leaves the costume saved: the job is done with it, never
        # "cancelled" over a costume that is in the vault (cancel_import and the chip say "nothing saved").
        if job.should_stop() and not (isinstance(reply, dict) and reply.get('saved')):
            raise jobs.Cancelled()
        return reply

    params = {k: v for k, v in args.items() if k != 'said'}
    try:
        job_id = jobs.start(KIND, work, label=label, params=params, single=True, thread_name='mcp-model-import')
    except jobs.JobBusy as busy:
        shutil.rmtree(asks, ignore_errors=True)
        return content.error(f'Another model import is running (job_id {busy.job_id}). Poll job_status until it '
                             'ends, then start this one.')
    return content.tool_result('import_model', {
        'job_id': job_id, 'status': 'running',
        'note': f'Started. Call job_status with this job_id until it is done (each call waits up to {WAIT_DEFAULT} '
                's); an import usually takes a few minutes.'})


def import_model(arguments):
    from randall.model_import.chat import import_job
    _unknown(arguments, ('source', 'fighter', 'name', 'untextured'))
    from core.path_safety import NotLocalPath, local_path
    text = _text(arguments, 'source', required=True)
    try:
        source = Path(local_path(text, field='source'))
    except NotLocalPath as refused:
        if refused.reason == 'network':
            raise
        raise ValueError(f'source must be an absolute path: {text}')
    if not source.is_absolute():
        raise ValueError(f'source must be an absolute path: {source}')
    if not source.is_file():
        raise ValueError(f'No file at {source}.')
    if source.suffix.lower() not in import_job.SOURCES:
        raise ValueError(f'{source.name} is not a model the importer reads: give a .zip, or a '
                         f'{", ".join(sorted(import_job.SOURCES - {".zip"}))} file (not SMD).')
    args = {'source': str(source.resolve())}
    for key in ('fighter', 'name'):
        value = _text(arguments, key)
        if value:
            args[key] = value
    untextured = arguments.get('untextured', False)
    if not isinstance(untextured, bool):
        raise ValueError('untextured must be true or false.')
    if untextured:
        args['untextured'] = True
    args = import_job.check(args)        # a fighter the importer does not target is refused here, in words
    need = import_job.tools_needed()
    if need:            # the app's model import tools are not downloaded (or out of date): said at once, never fetched
        return content.tool_result('import_model', import_job.tools_reply(need, mcp=True), is_error=False)
    problem = _setup_error()
    if problem:
        return content.error(problem)
    gap = None if untextured else import_job.textures.missing(source)
    if gap:     # the texture files the model names are not with it: said at once, nothing started
        return content.tool_result('import_model', import_job.textures_reply(gap, mcp=True), is_error=False)
    return _start(args, f'Model import: {source.name}')


def fix_import(arguments):
    from randall.model_import.chat import import_job, studio_import
    _unknown(arguments, ('project', 'change', 'said', 'name'))
    args = {key: _text(arguments, key, required=key in ('project', 'change'))
            for key in ('project', 'change', 'said', 'name')}
    args = import_job.check({k: v for k, v in args.items() if v})
    if not studio_import._folder(args['project']).is_dir():
        raise ValueError(f"There is no import {args['project']!r} here. project is the one an import_model "
                         "job's result gave.")
    need = import_job.tools_needed()
    if need:
        return content.tool_result('fix_import', import_job.tools_reply(need, mcp=True), is_error=False)
    problem = _setup_error()
    if problem:
        return content.error(problem)
    return _start(args, f"Model import change: {args['project']}")


# The result's ``next`` is written for the in-app chat (import_job.DONE_NEXT, CHANGED_NEXT): over MCP there is no
# card above the reply, and a change is fix_import, not import_model with project and change.
_CARD = ('The card above your reply already shows the saved name, the fighter and its portrait, so do not repeat '
         'them. ')
_CHANGE = re.compile(r'call import_model (?:again )?with project ("[^"]*") and change')


def mcp_next(text):
    text = text.replace(_CARD, 'There is no card over MCP: say the saved name and the fighter. ')
    return _CHANGE.sub(lambda m: f'call fix_import with project {m.group(1)} and change', text)


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _order(ask_id):
    return tuple(int(part) if part.isdigit() else 0 for part in ask_id.split('-'))


def _relay(record):
    """The relay folder of an import job that is still running, else None."""
    if record is None or record.get('kind') != KIND or record.get('status') not in jobs.ACTIVE:
        return None
    folder = (record.get('extra') or {}).get('asks')
    return Path(folder) if folder and Path(folder).is_dir() else None


def open_asks(folder):
    """The asks in relay ``folder`` that wait on an answer (none written yet, not closed), oldest first: each its
    ``ask-<id>.json`` record, plus ``problem``: why its last answer was refused, if it was."""
    found = []
    for path in Path(folder).glob('ask-*.json') if folder else ():
        ask_id = path.stem.removeprefix('ask-')
        if (folder / f'done-{ask_id}.json').exists() or (folder / f'answer-{ask_id}.json').exists():
            continue
        record = _read(path)
        if isinstance(record, dict) and record.get('id') == ask_id:
            found.append(dict(record, problem=_read(folder / f'problem-{ask_id}.json')))
    return sorted(found, key=lambda ask: _order(ask['id']))


def _asked(folder):
    """The open asks as job_status shows them: (their summaries, their picture blocks). Asks whose pictures do not
    fit in ASK_PICTURES are counted, not shown; they come with a later call."""
    shown, blocks, waiting = [], [], 0
    for ask in open_asks(folder):
        pictures = [Path(p) for p in ask.get('pictures') or []]
        if shown and len(blocks) + 2 * len(pictures) > 2 * ASK_PICTURES:
            waiting += 1
            continue
        summary = {'ask_id': ask['id'], 'round': ask.get('round'), 'instructions': ask.get('instructions'),
                   'question': ask.get('question'), 'answer_schema': ask.get('schema'), 'pictures': len(pictures)}
        problem = ask.get('problem')
        if isinstance(problem, dict):
            summary['refused_answer'] = {'problem': problem.get('problem'), 'your_answer': problem.get('answer'),
                                         'tries_left': problem.get('tries_left')}
        shown.append(summary)
        for n, path in enumerate(pictures, 1):
            try:
                image = content._file_image(path)
            except OSError:
                image = None
            if image:
                blocks += [content.text(f"Ask {ask['id']}, picture {n} of {len(pictures)}:"), image]
    return shown, blocks, waiting


def answer_import(arguments):
    """Write the caller's answers to the job's relay, then wait up to ANSWER_WAIT for rigswap to read them."""
    _unknown(arguments, ('job_id', 'answers'))
    job_id = _text(arguments, 'job_id', required=True)
    record = jobs.get(job_id)
    if record is None or record.get('kind') != KIND:
        return content.error(f'No import job {job_id}.')
    folder = _relay(record)
    if folder is None:
        return content.error(f"Job {job_id} is {record.get('status')} and asks nothing now; call job_status.")
    answers = arguments.get('answers')
    if not isinstance(answers, list) or not answers:
        raise ValueError('answers must be a nonempty list of {ask_id, answer}.')
    from randall.model_import.chat import ask_checks
    waiting = {ask['id']: ask for ask in open_asks(folder)}
    said = []
    for item in answers:
        ask_id = item.get('ask_id') if isinstance(item, dict) else None
        answer = item.get('answer') if isinstance(item, dict) else None
        if isinstance(answer, str):         # some clients send an object argument as its JSON text
            try:
                answer = json.loads(answer)
            except ValueError:
                pass
        if not isinstance(ask_id, str) or ask_id not in waiting:
            said.append({'ask_id': ask_id, 'status': 'not waiting',
                         'note': 'No open ask has this id (answered already, or past its wait); see job_status.'})
            continue
        if not isinstance(answer, dict):
            said.append({'ask_id': ask_id, 'status': 'refused', 'problem': 'answer must be a JSON object'})
            continue
        fault = ask_checks.fault(waiting[ask_id], answer)
        if fault:       # rigswap would take it and only say so in a new ask: said now, in its words, nothing written
            said.append({'ask_id': ask_id, 'status': 'refused', 'problem': fault,
                         'note': 'The importer could not use this answer, so it was not passed on: answer this ask '
                                 'again with that put right.'})
            continue
        (folder / f'problem-{ask_id}.json').unlink(missing_ok=True)
        target = folder / f'answer-{ask_id}.json'
        temporary = target.with_name(target.name + '.tmp')
        temporary.write_text(json.dumps({'answer': answer}), encoding='utf-8')
        temporary.replace(target)
        said.append({'ask_id': ask_id, 'status': 'sent'})
    deadline = time.monotonic() + ANSWER_WAIT
    for entry in said:
        if entry['status'] != 'sent':
            continue
        ask_id = entry['ask_id']
        while True:
            problem = _read(folder / f'problem-{ask_id}.json')
            if isinstance(problem, dict):
                entry.update(status='refused', problem=problem.get('problem'), tries_left=problem.get('tries_left'))
                if not problem.get('tries_left'):
                    entry['note'] = 'No tries left: the importer used its default for this ask.'
                break
            if (folder / f'done-{ask_id}.json').exists():
                done = _read(folder / f'done-{ask_id}.json') or {}
                entry['status'] = 'accepted' if done.get('answered') else 'closed'
                break
            if not folder.is_dir():         # the run ended (its folder goes with it): nothing left to refuse it
                entry.update(status='taken', note='The import has moved on; job_status gives its result.')
                break
            if time.monotonic() >= deadline:
                entry['status'] = 'sent'
                entry['note'] = 'Not read yet; job_status shows whether it was taken.'
                break
            time.sleep(0.1)
    # Refused here (no tries_left: rigswap never saw it) or by rigswap with tries left: the ask is open again.
    refused = any(entry['status'] == 'refused' and entry.get('tries_left', 1) for entry in said)
    return content.tool_result('answer_import', {
        'job_id': job_id, 'answers': said,
        'next': ('Answer the refused asks again with answer_import, then call job_status.' if refused
                 else 'Call job_status for the next questions or the result.')})


def job_status(arguments):
    _unknown(arguments, ('job_id', 'wait_seconds'))
    job_id = _text(arguments, 'job_id', required=True)
    wait = arguments.get('wait_seconds', WAIT_DEFAULT)
    if type(wait) is not int or not 0 <= wait <= WAIT_MAX:
        raise ValueError(f'wait_seconds must be a whole number from 0 to {WAIT_MAX}.')
    if job_id.startswith(calls.PREFIX):
        found = calls.status(job_id, wait=wait)
        return found or content.error(f'No job {job_id} in this session of Nucleus (call jobs are forgotten when '
                                      'the app restarts).')
    record = jobs.get(job_id)
    if record is None or record.get('kind') != KIND:
        return content.error(f'No job {job_id}.')
    deadline = time.monotonic() + wait
    while record.get('status') in jobs.ACTIVE and not open_asks(_relay(record)) and time.monotonic() < deadline:
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        record = jobs.get(job_id) or record
    extra = record.get('extra') or {}
    summary = {'job_id': job_id, 'status': record.get('status'), 'label': record.get('label'),
               'detail': record.get('detail') or None, 'progress': extra.get('progress_lines') or [],
               'seconds': extra.get('seconds'), 'project': extra.get('project')}
    asks, pictures, waiting = _asked(_relay(record))
    if asks:
        summary.update(status=NEEDS_ANSWERS, asks=asks, note=_ASKING)
        if waiting:
            summary['more_asks'] = (f'{waiting} more ask(s) wait; their pictures come with the next job_status '
                                    'after you answer these.')
        result = content.tool_result('import_model', summary, is_error=False)
        result['content'].extend(pictures)
        return result
    if record.get('error'):
        summary['job_error'] = record['error']
    reply = record.get('result') if isinstance(record.get('result'), dict) else None
    if reply is not None:
        reply = dict(reply, next=mcp_next(reply['next'])) if isinstance(reply.get('next'), str) else reply
        summary['result'] = reply
        summary['project'] = reply.get('project') or summary['project']
    result = content.tool_result('import_model', summary, is_error=record.get('status') in ('failed', 'interrupted'))
    if reply is not None:
        result['content'].extend(content.images('import_model', reply))
    return result


_ENDED = {'done': ('already_finished', 'It had already finished.'),
          'failed': ('already_failed', 'It had already failed; nothing was saved.'),
          'cancelled': ('already_stopped', 'It had already been stopped; nothing was saved.'),
          'interrupted': ('already_ended', 'It had already ended: Nucleus closed while it ran; nothing was saved.')}


def ended_words(record, *, asked):
    """cancel_import's answer for an import job that is not running (any more): ``asked``, whether this call asked it
    to stop."""
    status = record.get('status')
    reply = record.get('result') if isinstance(record.get('result'), dict) else {}
    saved = reply.get('saved') if isinstance(reply.get('saved'), dict) else None
    if status == 'cancelled' and asked:
        return {'status': 'stopped', 'saved': None,
                'note': 'Stopped: nothing was saved. Tell the user the import was stopped.'}
    said, note = _ENDED.get(status, ('already_ended', 'It is not running.'))
    if status == 'done':
        if saved:
            note = (f"It had already finished: the costume \"{saved.get('name') or 'its costume'}\" was saved to the "
                    'vault before it could be stopped. It stays there; the user can delete it in the Vault.')
        elif asked:
            note = 'It had already finished before it could be stopped; nothing was saved.'
        else:
            note = 'It had already finished; nothing was saved.'
    return {'status': said, 'job_status': status, 'saved': saved, 'note': note}


def cancel_import(arguments):
    """Stop an import job (the window's Cancel: jobs.cancel, which import_job sees and ends rigswap on), then wait up
    to CANCEL_WAIT for it to end and say how it ended."""
    _unknown(arguments, ('job_id',))
    job_id = _text(arguments, 'job_id', required=True)
    record = jobs.get(job_id)
    if record is None or record.get('kind') != KIND:
        return content.error(f'No import job {job_id}. job_id is the one import_model or fix_import answered with.')
    if record.get('status') not in jobs.ACTIVE:
        return content.tool_result('cancel_import', dict(ended_words(record, asked=False), job_id=job_id))
    if not jobs.cancel(job_id):         # not this app's job (a record left by another run): nothing here runs it
        record = jobs.get(job_id) or record
        if record.get('status') in jobs.ACTIVE:
            return content.error(f'Job {job_id} is not running in this Nucleus, so it cannot be stopped from here.')
        return content.tool_result('cancel_import', dict(ended_words(record, asked=False), job_id=job_id))
    deadline = time.monotonic() + CANCEL_WAIT
    while record.get('status') in jobs.ACTIVE and time.monotonic() < deadline:
        time.sleep(0.1)
        record = jobs.get(job_id) or record
    if record.get('status') in jobs.ACTIVE:
        return content.tool_result('cancel_import', {
            'job_id': job_id, 'status': 'stopping', 'saved': None,
            'note': 'Told to stop, and still stopping. Call job_status with this job_id to see how it ended '
                    '(cancelled: nothing saved).'})
    return content.tool_result('cancel_import', dict(ended_words(record, asked=True), job_id=job_id))


def call(name, arguments):
    if not isinstance(arguments, dict):
        return content.error('Tool arguments must be an object.')
    try:
        return {'import_model': import_model, 'fix_import': fix_import, 'job_status': job_status,
                'answer_import': answer_import, 'cancel_import': cancel_import}[name](arguments)
    except ValueError as exc:
        return content.error(str(exc))
