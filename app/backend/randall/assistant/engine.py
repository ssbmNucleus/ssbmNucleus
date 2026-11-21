"""Streaming tool loop with progress, local history and cancellation.

Wire format follows https://openrouter.ai/docs/guides/features/tool-calling .
Only the app's registry executes tools; transcripts from the client are never trusted.
"""

import json
import logging
import math
import os
import threading
import uuid
import copy
import time
import re

from shared.aiengine import decisions
from randall.recolor.workflows import Workflow
from randall.recolor.stage_start import StageStart
from randall.model_import.chat.attached_model import attached_model_waiting
from . import refusals, store, tools
from .vision import tool_images, context_images, attachment_images
from .continuity import working_context
from . import recipes
from . import compaction
from randall.model_import.chat import studio_import
from .tasks import content_hash, coordinator as taskflow

from .live_runs import (_Interruption, Run, active_run, _await_approval, _lock, _publish,
                        _review_download_safety, _runs, _save_lock, _task_card, settle_dead_run, stopped_before_start)
from .main_model import (ALREADY_FINISHED, FAST_LANE_MODEL, KEPT, LIMIT_REACHED, MODEL, PROVIDER_ORDER, _REASONING,
                         TurnStopped, _provider)
from .prompt import PROMPT
from .tool_stage import _execute_tool
from .turn_facts import _carried_ledger, _pinned_task, _receipt_summary, _turn_family, _turn_outcome


MAX_CONSECUTIVE_ACTION_CONTINUATIONS = 1
MAX_EMPTY_ROUNDS = 2            # a completion with no tool call and no words
# The same tool call (same arguments) failing with the same error: warn on the
# second failure, stop the turn on the third.
REPEAT_FAILURE_STOP = 3
# A skin edit's round budget. Good runs finish in 7-14 model rounds; a measured
# lava-Bowser run spent 35 rounds (744 s, 18 cents) re-checking one part and
# still timed out. At SKIN_WRAP_UP the model is told to finish; at SKIN_MAX or
# SKIN_MAX_COST the turn stops with its completed work kept.
SKIN_WRAP_UP = 15
SKIN_MAX_ROUNDS = 20
# A backstop for unusually heavy rounds, not the runaway guard (the round cap
# is). 6 cents stopped a 13-part zombie-Link theme mid-way at round 15. Text
# spend only: generated images have their own allowance (IMAGE_ALLOWANCE).
SKIN_MAX_COST = 0.10
# Generated images a user turn may make, any turn (a retexture or an ordinary
# chat), counted in billed images, not dollars (coordinator.TaskContext.allow_images):
# one generate_material sheet is one image and up to four swatches; style=artwork is
# one image per prompt. The text cap above never refuses an image and an image never
# spends the text cap: a Dream Land retexture's recolour rounds left too little of its
# 10 cents for the image's 5-cent reservation, so every material was refused unsent.
# The real charge still counts everywhere it did (cost_parts.images, the task's
# accounting, the OpenRouter key's own limit).
IMAGE_ALLOWANCE = max(0, int(os.environ.get('NUCLEUS_IMAGE_ALLOWANCE', '3')))
# Once a skin session is open, a skin turn sees only these. The full list is
# ~14k tokens re-read every round, over half of it model-import tools a skin
# edit never calls; this set is ~3k.
SKIN_TOOLS = frozenset(('create_clone_character test_in_game skin_lab_open skin_lab skin_material generate_material save_mod_copy '
                        'open_vanilla_file open_vault_file search_vault inspect_mod_file '
                        'unpack_mod_file').split())
WRAP_UP_NOTE = ('Round budget reached. Finish now in as few calls as possible: if the skin '
                'already looks close to the request, stop editing (code saves it to the vault when '
                'the turn ends) and reply with what was done plus anything still imperfect. Do '
                'not start new investigations or re-verify parts already checked.')
# A stage edit gets the same allowance (it had none: a stage turn ran until the
# turn's own limits), the same once-open roster narrowing (~14k tokens of schemas
# re-read every round, most of them model-import tools a stage never calls) and
# the same latest-image-only evidence.
STAGE_TOOLS = frozenset(('stage_lab_open stage_lab skin_material generate_material test_in_game '
                         'search_vault inspect_mod_file').split())
STAGE_WRAP_UP_NOTE = ('Round budget reached. Finish now in as few calls as possible: if the stage '
                      'already looks close to the request, stop editing (code saves it to the vault when '
                      'the turn ends) and reply with what was done plus anything still imperfect. Do not '
                      'start new investigations or re-check textures already checked.')


def _stage_coverage(result, name, args):
    """A whole-stage theme's edit says which surfaces are still unedited, the major ones first (stage_lab.coverage):
    the model sees what remains without spending a round on it."""
    from randall.recolor import stage_lab
    from .continuity import STAGE_EDIT_ACTIONS
    if (isinstance(result, dict) and not result.get('error') and name in ('stage_lab', 'skin_material')
            and args.get('action') in STAGE_EDIT_ACTIONS):
        line = stage_lab.coverage(args.get('session_id'))
        if line:
            result['coverage'] = line


def _vault_note(run, result, name, args, receipts, texts):
    """A successful lab edit's result says what code saves to the vault when the turn ends, and under which name
    (`vault`, randall/recolor/autosave.note), so the reply tells the user it is in their vault instead of
    offering to save it."""
    if run.direct_call or result.get('error'):
        return
    try:
        from randall.recolor import autosave
        line = autosave.note(name, args, result, receipts, texts, run.chat_id)
    except Exception:
        logging.getLogger(__name__).debug('no vault note for %s', name, exc_info=True)
        return
    if line:
        result['vault'] = line


def _latest_stage_coverage(receipts):
    from randall.recolor import stage_lab
    sid = next((((r.get('result') or {}).get('session_id') or (r.get('arguments') or {}).get('session_id'))
                for r in reversed(receipts) if str(r.get('name') or '').startswith('stage_lab')), None)
    return stage_lab.coverage(sid) if sid else None
# A model import's budgets are the studio's (model_import/chat/studio_import.py:
# MAX_ROUNDS, MAX_COST and the wrap-up point).
# A round that only collected tool refusals bought the user nothing, so it does
# not spend the allowance meant for repairing a costume. Bounded, and never a
# refund against cost: refusals are not free, and an unlimited credit would pay
# a loop to keep going. A Gabite import finished its draft and then spent its
# last four rounds being told the same thing about the same argument.
MODEL_RECOVERY_ROUNDS = 3
# Every round is capped at medium unless the turn's decision chose lower. At the
# model's default depth a single response can run past the 3-minute cap and
# kill the turn with nothing said: an Aztec-Mario round did it after the first
# round, and on 2026-09-22 "move the staff to her back" did it on the FIRST
# round twice in a row (48k-token context, 190 s, no reply). Capped at medium
# the same turn finished in 73 s with four tool calls.
EXECUTION_REASONING = {'effort': 'medium'}


def _add_cost(answer, part, cost):
    """Accumulate OpenRouter's reported USD cost on the answer, per source.

    Nothing is estimated here: a call that reports no cost adds nothing to what
    is SHOWN, because showing an invented number is worse than showing less.
    This is the display total only. The spending limits read
    `_committed(answer)`, which also counts a charge the provider never reported
    -- otherwise a provider that stops reporting costs makes every guard free.
    """
    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
        return
    parts = answer.setdefault('cost_parts', {})
    parts[part] = round(parts.get(part, 0.0) + cost, 6)
    answer['cost_usd'] = round(sum(parts.values()), 6)


def _committed(run):
    """What the turn's spending guards must read: the coordinator's ledger.

    Reported spend plus money reserved for charges that never came back, plus
    anything carried in from an earlier budget-blocked attempt at the same
    objective. Falls back to the displayed total only when no task is attached.
    """
    task = getattr(run, 'task', None)
    if task is None:
        return run.answer.get('cost_usd', 0) or 0
    committed = task.committed_usd
    run.answer['committed_usd'] = committed
    return committed


def _text_spent(run):
    """What a turn's money caps read: `_committed` less its generated images, which
    have their own allowance (IMAGE_ALLOWANCE). The answer keeps the whole figure."""
    committed = _committed(run)
    task = getattr(run, 'task', None)
    if task is None:
        return max(0.0, committed - ((run.answer.get('cost_parts') or {}).get('images') or 0))
    return task.text_committed_usd


def _add_tokens(answer, usage):
    """Prompt/cached/completion token totals, to see whether caching is hit."""
    if not isinstance(usage, dict):
        return
    tokens = answer.setdefault('tokens', {'prompt': 0, 'cached': 0, 'completion': 0})
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    for name, value in (('prompt', usage.get('prompt_tokens')), ('cached', cached),
                        ('completion', usage.get('completion_tokens'))):
        if type(value) is int and value >= 0:
            tokens[name] += value


def _round_reasoning(decided, round_number):
    return decided or EXECUTION_REASONING


def _announced_action(text):
    """Conservative recovery for a final promise with no accompanying tool call."""
    tail = (text or '').strip().split('\n\n')[-1][-1600:]
    if not tail or '?' in tail or '```' in tail or re.search(
            r"\b(please|approval|approve|confirm|choose|waiting|cannot|unable)\b|\bafter you\b|\bif you\b|\bcan['\u2019]t\b", tail, re.I):
        return False
    verbs = r'(?:apply|adjust|analy[sz]e|check|close|download|edit|export|fetch|find|inspect|look|map|open|recolou?r|render|reset|save|search|shift|test|verify)'
    promise = rf"\b(?:I['\u2019]ll|I will|let me|I['\u2019]m going to|I am going to)\s+(?:now\s+)?{verbs}\b[^.!?]*(?:[.!]|\u2026)?$"
    action = r'(?:^|[.!]\s+)(?:Now\s+)?(?:Applying|Adjusting|Analy[sz]ing|Checking|Downloading|Editing|Exporting|Fetching|Inspecting|Opening|Recolou?ring|Rendering|Saving|Searching|Shifting|Testing|Verifying)\b[^.!?]*:$'
    return bool(re.search(promise, tail, re.I) or re.search(action, tail, re.I))


def start(chat_id, message, context, request_key=None, account_token=None, *, _direct_call=None, input_id=None, game_runtime=None,
          run_id=None):
    # Provisioned Patreon keys are request-scoped, like Tracker's. Never save
    # them into the personal keystore, transcript, context or status response.
    key = request_key
    if not key and _direct_call is None:
        raise ValueError('Link an active Patreon membership to start chatting.')
    with _lock:
        # `run_id`: the window names its reply's run itself, so its Stop can reach the run before `started` arrives.
        if run_id is not None and run_id in _runs:
            raise ValueError('That run id is already in use.')
        if run_id is not None and stopped_before_start(run_id):
            raise RuntimeError('Stopped before it started.')
        if any(bool(r.direct_call) == bool(_direct_call) for r in _runs.values()):
            raise RuntimeError('Another download is still running.' if _direct_call else "I'm still finishing my last reply. Try again in a moment.")
        chat = store.get(chat_id) if chat_id else None
        if chat_id and not chat:
            raise ValueError('Conversation not found.')
        existing = active_run(chat_id) if chat_id else None
        # Concurrent workers share the transcript but own distinct answer objects.
        messages = existing.messages if existing else chat['messages'] if chat else []
        if not existing:
            settle_dead_run(messages)
        answer = {'id': uuid.uuid4().hex, 'role': 'assistant', 'content': '', 'tools': [],
                  'status': 'running', 'started_at': time.time(),
                  'run_kind': 'download' if _direct_call else 'reply'}
        with _save_lock:
            if input_id:
                pending = store.pending_inputs(chat_id)
                selected = next((item for item in pending if item['id'] == input_id), None)
                ids = ([item['id'] for item in pending if item['mode'] == 'steer']
                       if selected and selected['mode'] == 'steer' else [input_id])
                users = store.deliver_inputs(chat_id, ids, messages, answer)
                context = users[-1]['context']
                messages.extend([*users, answer])
            else:
                if message:
                    messages.append({'role': 'user', 'content': message, 'context': context, 'at': time.time()})
                messages.append(answer)
                chat_id = store.save(chat_id, messages)
        run = Run(chat_id, messages, context, key, account_token=account_token, game_runtime=game_runtime, direct_call=_direct_call, answer=answer,
                  **({'id': run_id} if run_id else {}))
        run.start_message_id = answer['id']
        _runs[run.id] = run
        threading.Thread(target=_work, args=(run,), daemon=True, name='nucleus-assistant').start()
        return run


def start_download(chat_id, post_id, file_id=None):
    """Open a download review directly, without a provider request."""
    from randall.website.website_posts import _id
    args = {'post_id': _id(post_id, 'post_id')}
    if file_id is not None:
        args['file_id'] = _id(file_id, 'file_id')
    return start(chat_id, None, {}, _direct_call={
        'id': uuid.uuid4().hex, 'type': 'function',
        'function': {'name': 'download_website_mod', 'arguments': json.dumps(args)}})


def start_bulk_download(chat_id, items):
    from randall.website.website_bulk import validate_items
    validate_items(items)
    return start(chat_id, None, {}, _direct_call={
        'id': uuid.uuid4().hex, 'type': 'function',
        'function': {'name': 'download_website_mods', 'arguments': json.dumps({'items': items})}})


def _app_snapshot():
    """The live application state a turn starts from, or None if unavailable.

    Read-only and cheap (assistant/app_context.py). A failure here must not fail
    a turn: the model then works without the snapshot exactly as it used to.
    """
    try:
        from . import app_context
        return app_context.public()
    except Exception:
        logging.getLogger(__name__).debug('app context unavailable', exc_info=True)
        return None


def _work(run):
    try:
        while True:
            _work_turn(run)
            with _lock:
                # Stop/errors pause the queue. Reloads preserve it, but a fresh
                # credential is required to resume after the worker exits.
                pending = (store.pending_inputs(run.chat_id) if not run.direct_call
                           and not run.cancelled.is_set() and run.answer['status'] in {'done', 'steered'} else [])
                if not pending:
                    _runs.pop(run.id, None)
                    break
                previous = copy.deepcopy(run.answer)
                answer = {'id': uuid.uuid4().hex, 'role': 'assistant', 'content': '', 'tools': [],
                          'status': 'running', 'started_at': time.time(), 'run_kind': 'reply'}
                with _save_lock:
                    selected = ([item for item in pending if item['mode'] == 'steer']
                                if pending[0]['mode'] == 'steer' else pending[:1])
                    users = store.deliver_inputs(run.chat_id, [item['id'] for item in selected], run.messages, answer)
                    run.messages.extend([*users, answer])
                run.answer, run.context = answer, users[-1]['context']
                run.steering.clear()
                run.events.put({'type': 'turn_done', 'message': previous})
                run.events.put({'type': 'input_applied', 'user': users[-1], 'users': users, 'message': copy.deepcopy(answer),
                                'pending_inputs': store.pending_inputs(run.chat_id)})
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).exception('Randall worker failed')
        run.answer.update(status='error', error='The assistant could not continue. Pending messages are kept; reopen the chat to resume.')
        with _save_lock:
            store.save(run.chat_id, run.messages)
    finally:
        # The objective ends with the RUN, not with a turn. Closing it here
        # means every queued follow-up has already had its chance to continue
        # the same task, and the final envelope on the `done` message is the
        # one that actually persisted.
        _close_objective(run)
        # The turn's own save ran before its task was recorded and closed. Save
        # the final card (and any record/close error) while the run still owns
        # the chat, so the reload right after `done` reads it.
        try:
            with _save_lock:
                store.save(run.chat_id, run.messages)
        except Exception:
            logging.getLogger(__name__).exception('final chat save failed')
        run.key = ''
        run.account_token = None
        run.game_runtime = None
        with _lock:
            _runs.pop(run.id, None)
        run.events.put({'type': 'done', 'message': copy.deepcopy(run.answer)})


# What a turn is spending against, by family (turn_facts._turn_family). These are the
# same numbers the round loop has always used; the difference is that the coordinator
# now reserves against them before EVERY paid dispatch -- Jev, the fast lane, a nested
# vision labeller, an image generation and every retry -- instead of the round loop
# checking a display total between main-model rounds only. A skin or stage edit has no
# entry: whether a turn is one is only known once it opens a lab session (or code
# does), and the round loop lowers the task's ceiling to SKIN_MAX_COST from then on.
FAMILY_COST_BUDGET = {'model_import': studio_import.MAX_COST}


def _start_task(run, user_text):
    """Open the objective this run is about, carrying any earlier spend."""
    receipts = [t for m in run.messages for t in m.get('tools', [])]
    family = _turn_family(user_text, receipts, _pinned_task(recipes.chat_task(run.messages), receipts),
                          attachments=_attachments([m for m in run.messages if m is not run.answer]))
    carried_usd, carried_calls = _carried_ledger(run.chat_id)
    return taskflow.start(
        '', chat_id=run.chat_id, family=family, request=user_text,
        cost_budget_usd=FAMILY_COST_BUDGET.get(family, taskflow.DEFAULT_COST_BUDGET_USD),
        carried_usd=carried_usd, carried_calls=carried_calls,
        # Every participating role, so a run is reproducible against the whole
        # roster that served it rather than against the main model alone.
        config_snapshot={'main_model': MODEL, 'providers': list(PROVIDER_ORDER),
                         'jev_model': decisions.MODEL, 'jev_enabled': decisions.enabled(),
                         'fast_lane_model': FAST_LANE_MODEL,
                         'image_model': os.environ.get('NUCLEUS_MATERIAL_MODEL', ''),
                         'image_allowance': IMAGE_ALLOWANCE,
                         'prompt_version': content_hash.canonical_hash(PROMPT),
                         'recipes_version': recipes.RECIPES_VERSION,
                         'tool_schema_version': content_hash.schema_hash(tools.SCHEMAS),
                         'coordinator_version': taskflow.COORDINATOR_VERSION,
                         'family': family, 'direct_call': bool(run.direct_call),
                         'carried_usd': carried_usd, 'carried_calls': carried_calls})


def _surface_task_failure(run, what, exc):
    """Never silent. An authoritative write that failed is reported, not hidden.

    Every one of these used to run through a best-effort guard, so a refused
    revision or a refused close left memory and SQLite disagreeing with nobody
    the wiser -- and the durable record kept an earlier turn's `success`.
    """
    logging.getLogger(__name__).error('task %s failed: %s', what, exc, exc_info=True)
    run.answer.setdefault('task_errors', []).append(
        {'stage': what, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'})


def _work_turn(run):
    """One turn, attached to the run's task so its model requests are traced.

    The task outlives the model round (spec section 4). Attaching before the Jev
    decision means the turn's FIRST paid request is already inside the trace,
    and every later dispatch -- nested helpers and retries included -- reserves
    against one budget.

    A follow-up message continues the SAME task as a new revision. The task is
    NOT closed here: a turn ending is not the objective ending, and closing it
    per turn meant a queued follow-up ran against a terminal task while the
    durable record still reported the first turn's outcome. `_close_objective`
    closes it when the run is really over.
    """
    user_text = next((m['content'] for m in reversed(run.messages)
                      if m['role'] == 'user' and m.get('content')), '')
    if run.task is None:
        run.task = _start_task(run, user_text)
    else:
        try:
            run.task.revise('user_message', user_text)
        except Exception as exc:
            # Authoritative: the task is finished, or the revision would not
            # commit. Either way this turn gets its own task rather than
            # spending under a revision that no longer exists.
            _surface_task_failure(run, 'revise', exc)
            run.task = _start_task(run, user_text)
    task = run.task
    # Every user turn starts with its own allowance of generated images (IMAGE_ALLOWANCE).
    task.allow_images(IMAGE_ALLOWANCE)
    run.answer['task_id'] = task.task_id
    run.answer['task_revision'] = task.revision
    with taskflow.attach(task), taskflow.work_unit(task.revision):
        try:
            _run_turn(run)
        finally:
            _record_turn(task, run)


def _record_turn(task, run):
    """Fold this turn's verified result into the task without closing it."""
    outcome, _error = _turn_outcome(run, task)
    facts = {'stop_reason': run.answer.get('stop_reason'),
             'model_rounds': run.answer.get('model_rounds'),
             'round_limit': run.answer.get('round_limit'),
             'budget_exhausted': run.answer.get('stop_reason') in ('cost_budget', 'round_budget'),
             'committed_usd': task.committed_usd,
             'turn_outcome': outcome}
    try:
        task.envelope.facts.update({k: v for k, v in facts.items() if v is not None})
        task.envelope.receipts = _receipt_summary(run.answer.get('tools'))
        task.save()
    except Exception as exc:
        _surface_task_failure(run, 'record', exc)
    run.answer['task'] = _task_card(run)


def _close_objective(run):
    """Close the run's task once, when no further turn will continue it."""
    task = getattr(run, 'task', None)
    if task is None or task.finished:
        return
    outcome, error = _turn_outcome(run, task)
    try:
        task.finish(outcome, error=error, receipts=_receipt_summary(run.answer.get('tools')))
    except Exception as exc:
        _surface_task_failure(run, 'close', exc)
    # The FINAL envelope, published after the close has actually persisted.
    run.answer['task'] = _task_card(run)


def _recolor_enrollment(run, declared, recipe_family, mismatch, attached):
    """True when this turn may run the recolor workflow (workflows.Workflow `recolor`).

    Only a chat started as "Recolor a costume" runs it, and only on a turn about
    the recolor itself: not a follow-up ("put it in my game" pins the delivery
    family, and a chat whose recolor never opened a session has nothing else
    stopping a fresh acquisition), not a mismatched turn (a model file attached
    to this message), not while an attached model is waiting to be imported
    (`attached`: any un-imported model the chat's recent messages carry, which
    this message may be about), and never for a card-button download. An
    ordinary chat never runs it: its words do not pick a task.
    """
    return bool(not run.direct_call and declared == 'recolor_part' and recipe_family == 'recolor_part'
                and not mismatch and not attached)


def _stage_enrollment(run, declared, recipe_family, mismatch, attached):
    """True when code may open this turn's picked stage (stage_start.StageStart).

    The same rule as `_recolor_enrollment`, for a chat started as "Recolor a
    stage": a turn about the recolor itself (not a follow-up), no model file
    attached or waiting, never a card-button download. StageStart adds the rest
    (one picked stage, no Stage Lab session yet, not a question or a refusal).
    """
    return bool(not run.direct_call and declared == 'recolor_stage' and recipe_family == 'recolor_stage'
                and not mismatch and not attached)


def _after_import(answer, offered):
    """Whether this round comes right after an import this turn saved, with the play session on offer: its words are
    held until the round's calls are known, and dropped when it calls test_in_game, so an import that also plays
    ends in ONE closing reply, the one after test_in_game (studio_import.IMPORT_CARD, import_job.PLAY_FIRST).
    2026-10-06: the model still wrote "Now the in-game test." once and a whole summary another time before the
    call, then the closing reply: two near-duplicate messages. Any other round streams as it comes."""
    tools_ = answer.get('tools') or []
    last = tools_[-1] if tools_ else {}
    result = last.get('result') if isinstance(last.get('result'), dict) else {}
    return (last.get('name') == 'import_model' and last.get('status') == 'done' and result.get('status') == 'done'
            and bool(result.get('saved'))
            and any(s['function']['name'] == 'test_in_game' for s in offered))


def _attachments(messages):
    """The files the last 20 messages carry, oldest first (what an attached model is looked for in)."""
    return [file for message in messages[-20:] for file in (message.get('context') or {}).get('files') or []]


def _routing_record(decision, workflow, run):
    """This turn's routing, as plain data: the decision's answers (None when the
    router was off or failed), the workflow it enrolled in, and the configured
    models. Never includes a key or any user text."""
    try:
        lane = getattr(workflow, 'lane', None)
        record = {'router': 'jev' if decision is not None else ('direct_call' if run.direct_call else 'none'),
                  'router_model': decisions.MODEL if decision is not None else None,
                  'main_model': MODEL, 'providers': list(PROVIDER_ORDER),
                  'workflow': getattr(workflow, 'name', None) or None,
                  'fast_lane_model': FAST_LANE_MODEL,
                  'fast_lane_active': bool(getattr(lane, 'active', False))}
        if decision is not None:
            plain = (int, float, str, bool, type(None))
            record['decision'] = {name: value for name in
                                  ('effort', 'vanilla', 'website', 'variant', 'cost', 'seconds')
                                  if isinstance(value := getattr(decision, name, None), plain)}
        return record
    except Exception:  # diagnostics must never cost a turn
        return {'router': 'unrecorded'}


def _autosave(run, earlier, texts):
    """Save every lab session this turn edited to the vault, as the turn's last step (randall/recolor/autosave.py).

    Code, not the model: no round and no approval. Each save is one receipt, the one a manual save makes
    (save_mod_copy, or stage_lab action=save) with `autosave` saved/updated on its result, shown running with its
    progress line while the portrait or screenshot is made: the reply's words are already on screen. A save that
    fails ends the reply with one plain sentence saying it was not saved and why; the edits stay, and the next turn
    tries again."""
    from randall.recolor import autosave
    answer = run.answer
    turn = list(answer.get('tools') or [])
    for kind, sid in autosave.plan(earlier, turn):
        job = autosave.Save(run.chat_id, kind, sid, list(earlier) + list(answer.get('tools') or []), texts)
        if not job.prepare():
            continue          # nothing new since the last save (or since the source)
        receipt = {'id': uuid.uuid4().hex, 'name': autosave.TOOL[kind], 'status': 'running',
                   'arguments': job.arguments, 'result': {'progress_label': job.working},
                   'auto_save': {'session_id': sid, 'kind': kind},
                   'started_at': time.time(),
                   'content_offset': len(answer['content'].encode('utf-16-le', errors='surrogatepass')) // 2}
        answer['tools'].append(receipt)
        run.events.put({'type': 'tool_start', 'tool': copy.deepcopy(receipt)})
        result, marker = job.run()
        receipt['completed_at'] = time.time()
        receipt['elapsed_ms'] = round((receipt['completed_at'] - receipt['started_at']) * 1000)
        receipt.update(arguments=job.arguments, result=result, auto_save=marker,
                       status='error' if result.get('error') else 'done')
        _publish(run, receipt)
        if result.get('error'):
            sentence = ('\n\n' if answer['content'].strip() else '') + result['error']
            answer['content'] += sentence
            run.events.put({'type': 'delta', 'content': sentence})


def _run_turn(run):
    answer = run.answer
    # What the end-of-turn vault save reads (_autosave): the chat's receipts before this turn, and the words its
    # fallback name comes from (this turn's request, then the chat's first).
    autosave_receipts, autosave_texts = None, ()
    try:
        earlier = run.messages[:next(i for i, m in enumerate(run.messages) if m is answer)]
        history = [{'role': m['role'], 'content': m['content'][:12000]}
                   for m in earlier[-20:] if m.get('content')]
        # Previous tool receipts are server-owned and survive reopening a chat.
        receipts = [t for m in earlier for t in m.get('tools', [])]
        attachments = _attachments(earlier)
        state = working_context(receipts)
        user_text = next((m['content'] for m in reversed(earlier) if m['role'] == 'user'), '')
        autosave_receipts = list(receipts)
        autosave_texts = (user_text, next((m['content'] for m in earlier if m['role'] == 'user'), ''))
        # The task the chat was started as (recipes.LAUNCHABLE), read from the
        # chat's FIRST user message -- the chat's task, not this turn's: a
        # follow-up queued without a pill keeps it. store.save() keeps the same
        # value in chats.task. `pinned` is the task routing is held to this turn
        # (a finished model import lets go).
        declared = recipes.chat_task(earlier)
        pinned = _pinned_task(declared, receipts)
        # One typed decision for the whole turn: the reasoning budget and a
        # recolor's acquisition gates are answered against the same small state.
        # A direct call is an already-chosen tool, so there is nothing to decide.
        decision = None if run.direct_call else decisions.decide(
            decisions.turn_state(user_text, state, receipts, run.context), run.key)
        # The main rounds depend on the routing answer; recording the edge is
        # what makes "longest dependent chain of model requests" computable.
        decision_span_id = getattr(decision, 'span_id', '') if decision is not None else ''
        if decision is not None:
            _add_cost(answer, 'decision', decision.cost)
        # An attached model the chat has not imported, and a message asking to
        # act on it ("import this"): read from the files, never from the words
        # alone (attached_model.attached_model_waiting). It is how an ordinary chat
        # reaches import_model.
        attached = None if run.direct_call else attached_model_waiting(user_text, attachments, receipts)
        # A recolor chat whose message attaches a model file is answered with
        # one sentence pointing at a new import chat; the UI puts a button
        # under that reply (recipes.task_mismatch). Only a model file attached
        # to THIS message counts: the import path above scans the last 20
        # messages, so one model attached (and nudged) once would otherwise
        # refuse "make Fox red", "go ahead" and every later message.
        current = next((m for m in reversed(earlier) if m['role'] == 'user'), {})
        attached_now = None if run.direct_call else attached_model_waiting(
            user_text, [f for f in (current.get('context') or {}).get('files') or []
                        if recipes.model_file(f)], receipts)
        mismatch = None if run.direct_call else recipes.task_mismatch(declared, attached_model=attached_now)
        # Three documentation levels: the index is always in PROMPT, this turn's
        # recipe and signatures are attached once before the first call, and
        # anything further is fetched by the operations themselves. The card
        # before the first call is the declared task's, or a follow-up's its
        # words ask for (recipes.turn_family); an ordinary chat has none until
        # it calls a tool, and the card follows the first called tool below. A
        # model import declared here also makes studio_import.turn_mode below
        # answer 'import', until it has finished (_pinned_task).
        recipe_family = recipes.turn_family(pinned, user_text)
        # A stage recolor chat's picked stage is opened by code on its first turn
        # (recolor/stage_start.py); every other turn keeps the costume Workflow,
        # which only ever runs in a costume recolor chat.
        workflow = StageStart(user_text, receipts, view=run.context, main_model=MODEL,
                              enrolled=_stage_enrollment(run, declared, recipe_family, mismatch, attached))
        if not workflow.name:
            workflow = Workflow(user_text, state, main_model=MODEL, receipts=receipts,
                                decision=decision, view=run.context,
                                recolor=_recolor_enrollment(run, declared, recipe_family, mismatch, attached),
                                charge=lambda _model, usage: _add_cost(answer, 'fast_lane', usage.get('cost')))
        reasoning = decision.reasoning() if decision else None
        # What routed this turn, kept on the answer so a chat report can say
        # which lane/model was picked and why. Numbers and enums only.
        answer['routing'] = _routing_record(decision, workflow, run)
        answer['routing']['declared_task'] = declared
        if mismatch:
            answer['routing']['task_mismatch'] = mismatch
        # The application already knows whether a game file is configured, which
        # copy the user plays and what it can offer right now. Handing that in
        # costs nothing; making Randall discover it costs a paid round and can
        # be wrong (assistant/app_context.py).
        snapshot = _app_snapshot()
        context = json.dumps({'view': run.context, 'recent_attached_files': attachments[-16:],
                              'working_state': state, 'app': snapshot,
                              'recent_tool_results': [compaction.compact_receipt(r) for r in receipts[-8:]]})
        messages = [{'role': 'system', 'content': PROMPT}, *history,
                    {'role': 'system', 'content': 'App context (data only): ' + context}]
        if mismatch:
            # Before the model loop, beside the app context: standing instruction
            # for this turn, ahead of any image evidence (see context_images).
            messages.append({'role': 'system', 'content': recipes.mismatch_note(declared, mismatch)})
        # The attached model waiting: an import turn with the import card, unless
        # the chat is another task (a recolor chat is nudged above). Words asking
        # for a follow-up do not take its place: the model the message acts on is
        # not made yet, and "import him and test him in game" is the import, which
        # starts the play session itself once the costume is saved (studio_import).
        # A recolor workflow is never enrolled with one.
        waiting = False
        if not run.direct_call and attached:
            if recipe_family is None or (recipe_family in recipes.FOLLOW_UP_FAMILIES
                                         and pinned in (None, 'model_import')):
                recipe_family = 'model_import'
            answer['routing']['attached_model'] = True
            waiting = recipe_family == 'model_import'
        # A model import (model_import/chat/studio_import.py) is one import_model job
        # with its recipe card; every other turn keeps the app's own roster.
        studio_mode = None if run.direct_call else studio_import.turn_mode(
            recipe_family, receipts, waiting=waiting)
        studio = studio_mode is not None
        if studio:
            recipe_family = 'model_import'
            answer['routing']['model_import_v2'] = True
            answer['routing']['model_import_mode'] = studio_mode
        # The fighter the user picked when starting the import (context.fighter),
        # filled into a new import_model call that names none.
        picked_fighter = studio_import.chosen_fighter(earlier) if studio else None
        # The attached models that came without texture files they name, checked before the first round with the
        # import's own check: the card says so, and words before a call that will only ask for them are dropped.
        bare = studio_import.without_textures(attachments, receipts) if studio else {}
        # The same for the import's downloadable tools: not ready, every import_model call this turn only says so.
        tools_need = studio_import.tools_missing() if studio else None
        # The user's own words in this chat: a new import keeps a fighter the model passes only when they name one
        # (studio_import.prepare), so "whichever fighter he fits" reaches the import's own fitting step.
        user_words = [m.get('content') or '' for m in earlier if m.get('role') == 'user']
        model_max_rounds, model_max_cost = studio_import.MAX_ROUNDS, studio_import.MAX_COST
        model_wrap_rounds, model_wrap_cost, model_wrap_note = (
            studio_import.WRAP_UP_ROUNDS, studio_import.WRAP_UP_COST, studio_import.WRAP_UP_NOTE)
        recipe_loaded = set()
        turn_tool_messages = []
        # Only a turn that IS a skin job is budgeted and scoped (see SKIN_WRAP_UP,
        # SKIN_TOOLS): a recolor chat's workflow turn, or a turn that opens a
        # chat's first skin session itself (an ordinary chat's recolor: from
        # that call on, below). A skin session left open by an earlier turn is
        # not one: keying on it hid the model-import tools from "lets do a model
        # import of goku next", so Randall said it had none.
        budgeted = workflow.name in ('recolor', 'recolor_stage')
        first_skin_session = not state.get('skin_sessions')
        # The same for a stage: a stage chat's code-opened turn, or a turn that opens
        # the chat's first Stage Lab session itself (from that call on, below).
        stage_job = workflow.name == 'recolor_stage'
        # A theme for the whole stage, not a surface the request names: its edits carry the coverage line.
        from randall.recolor.stage_lab import whole_stage_request
        whole_stage = whole_stage_request(user_text)
        first_stage_session = not any(r.get('name') == 'stage_lab_open' and r.get('status') == 'done'
                                      for r in receipts)
        # Skin and stage edits -- this turn's, or one resumed from an open session -- see
        # only the latest image evidence (see vision.context_images).
        latest_only = budgeted or bool(state.get('skin_sessions')) or not first_stage_session
        # The roster narrows to the lab's tools (SKIN_TOOLS / STAGE_TOOLS) once a lab session
        # is open on a budgeted turn: one code opened (workflow.session_id) or one this
        # turn's model opened itself (below). The escape is the workflow path's own: only
        # that turn is narrowed, so the user's next message -- any unrelated work they ask
        # for while the session is still open -- gets the whole roster again.
        lab_open = False
        evidence = context_images(receipts, loader=tool_images, latest_only=latest_only)
        if evidence:
            messages.append({'role': 'user', 'content': evidence})
        # Pictures attached to this very message (a workbench render dragged onto
        # the message bar) are shown, not only named in recent_attached_files.
        pointed = attachment_images((run.context or {}).get('files') or [])
        if pointed:
            messages.append({'role': 'user', 'content': pointed})
        # Offering a tool whose assets were never extracted just buys a failed
        # call and an apology, so it is withheld until the ISO has been read.
        vanilla_ready = tools.vanilla_assets_ready()
        schemas = [s for s in tools.SCHEMAS
                   if (run.account_token or s['function']['name'] != 'set_website_mod_like')
                   and (vanilla_ready or s['function']['name'] != 'open_vanilla_file')]
        if studio:
            schemas = studio_import.offer(schemas)
        elif not run.direct_call and studio_import.changeable(receipts):
            # A finished import in this chat: another fighter the user asks for ("put it on Marth instead") is
            # import_model again with the same source and that fighter (it saves a second costume).
            schemas = schemas + studio_import.import_schemas()
        import_offered = studio or any(s['function']['name'] in studio_import.names() for s in schemas)
        declined_actions = set()
        # Paid family -> the refusal that holds for the rest of this turn (its images
        # used up, a spending limit): a later call of that family gets the same result
        # without running, so it never reaches the provider (assistant/refusals.py).
        refused = {}
        # (tool, exact arguments, error) -> how many times it has failed alike.
        # A Homer import sent one rejected model_fit sixty times running.
        repeated_failures = {}
        wrapped_up = False
        model_wrapped_up = False
        model_rounds = 0
        recovery_credits = 0          # refused rounds not charged to the repair allowance
        reported_receipts = 0
        consecutive_continuations = 0
        empty_rounds = 0
        while True:
            if run.interrupted():
                break
            completion = None
            # Code's own calls (opening the picked costume or stage, the prepare steps) are not model rounds.
            automatic = not run.direct_call and workflow.code_round(schemas)
            if not automatic and not run.direct_call and budgeted:
                if (model_rounds >= SKIN_MAX_ROUNDS
                        or _text_spent(run) >= SKIN_MAX_COST):
                    raise TurnStopped('round_budget', "That's as far as I can take this "
                                      f'{"stage" if stage_job else "costume"} edit in one go. Your changes are '
                                      'kept. Say "continue" and I' + "'ll keep refining.")
                if model_rounds >= SKIN_WRAP_UP and not wrapped_up:
                    wrapped_up = True
                    answer['wrap_up_round'] = model_rounds + 1
                    left = _latest_stage_coverage(receipts) if stage_job and whole_stage else None
                    messages.append({'role': 'system', 'content': (STAGE_WRAP_UP_NOTE + (' ' + left if left else ''))
                                     if stage_job else WRAP_UP_NOTE})
            # A turn becomes a model import once it calls a model-import tool.
            # NB: `receipts` above is the earlier chat's, still read each round.
            turn_receipts = answer.get('tools') or []
            importing = studio and any(studio_import.is_studio_result(r.get('result')) for r in turn_receipts)
            # The family is only certain once the turn calls a model/skin tool.
            # Narrowing the coordinator's ceiling here means the nested labeller
            # and image calls are admitted against the SAME limit the round loop
            # enforces, instead of against the generic per-task default.
            if run.task is not None:
                ceiling = SKIN_MAX_COST if budgeted else model_max_cost if importing else None
                if ceiling is not None and (run.task.cost_budget_usd or 0) > ceiling:
                    run.task.cost_budget_usd = ceiling
            # A round whose every tool call was refused advanced nothing, so it is
            # credited back against the round allowance (never against cost).
            round_receipts = turn_receipts[reported_receipts:]
            if (round_receipts and all((r.get('result') or {}).get('error') for r in round_receipts)
                    and recovery_credits < MODEL_RECOVERY_ROUNDS):
                recovery_credits += 1
            reported_receipts = len(turn_receipts)
            spent = model_rounds - recovery_credits
            if not automatic and not run.direct_call and importing and not budgeted:
                if _text_spent(run) >= model_max_cost:
                    raise TurnStopped('cost_budget', LIMIT_REACHED)
                if spent >= model_max_rounds:
                    raise TurnStopped('round_budget', LIMIT_REACHED)
                if not model_wrapped_up and (spent >= model_wrap_rounds
                                             or _text_spent(run) >= model_wrap_cost):
                    model_wrapped_up = True
                    answer['wrap_up_round'] = model_rounds + 1
                    messages.append({'role': 'system', 'content': model_wrap_note})
            if not automatic and not run.direct_call:
                model_rounds += 1
                _REASONING.set(_round_reasoning(reasoning, model_rounds))
                answer['model_rounds'] = model_rounds
                # The notice has to be able to say the REAL limit, which depends
                # on what this turn turned out to be (a skin edit and a model
                # import have different allowances).
                round_limit = (SKIN_MAX_ROUNDS if budgeted
                               else model_max_rounds if importing else None)
                answer['round_limit'] = round_limit
                run.events.put({'type': 'turn_progress', 'message_id': answer['id'],
                                'started_at': answer['started_at'], 'model_rounds': model_rounds,
                                'round_limit': round_limit, 'max_rounds': round_limit})
            offered = (schemas if not (budgeted and (lab_open or workflow.session_id))
                       else [s for s in schemas if s['function']['name'] in
                             (STAGE_TOOLS if stage_job else SKIN_TOOLS)])
            if recipe_family and recipe_family not in recipe_loaded:
                # A model import's card: import_model's recipe (and the fighter the user picked).
                recipe_card = (studio_import.card(app_context=snapshot, fighter=picked_fighter, bare=bare,
                                                  tools=tools_need)
                               if studio and recipe_family == 'model_import'
                               else recipes.card(recipe_family, offered, app_context=snapshot))
                recipe_loaded.add(recipe_family)      # once, whether or not it existed
                if recipe_card:
                    # Right after the prompt, never at the end: the tail of the
                    # conversation is tool replies followed by image evidence,
                    # and that pairing has to stay contiguous (see context_images).
                    # A recipe is standing instruction, so it belongs with them.
                    messages.insert(1, {'role': 'system', 'content': recipe_card})
                    answer.setdefault('recipes', []).append(
                        studio_import.describe() if studio and recipe_family == 'model_import'
                        else recipes.describe(recipe_family, offered))
            source = ([{'type': 'completion', 'message': {'role': 'assistant', 'content': None,
                       'tool_calls': [run.direct_call]}}] if run.direct_call else
                      workflow.stream(messages, offered, run.key, _Interruption(run),
                                       taskflow.traced_provider(
                                           _provider, role='main', requested_model=MODEL,
                                           task_family=run.task.family if run.task else '',
                                           prompt_template_version=content_hash.canonical_hash(PROMPT),
                                           configuration_version=','.join(PROVIDER_ORDER),
                                           dependency_ids=[d for d in (decision_span_id,) if d])))
            # Right after an import this turn saved, the model's words wait for its call: words written before
            # test_in_game are dropped, so the one closing reply after it is the only one shown (_after_import).
            # Before the first import call of a turn with a model that came without its textures, the same: words
            # written before a call that will only ask for them are dropped (studio_import.asks_for_textures). 0.9.0
            # smoke: "Starting now: I'll put Sack Boy on Ness and save him to your vault." above "nothing was
            # imported yet".
            before_bare = (bool(bare) or bool(tools_need)) and not importing
            held = [] if _after_import(answer, offered) or before_bare else None
            for event in source:
                if run.interrupted():
                    break
                if event['type'] == 'delta':
                    if held is not None:
                        held.append(event['content'])
                        continue
                    answer['content'] += event['content']
                    run.events.put(event)
                elif event['type'] == 'billing':
                    # The charge, handed over as soon as the provider stated it.
                    # The tracer has already recorded it; the turn counts it here
                    # so a round that bills and then fails validation is not free.
                    _add_cost(answer, 'main', event.get('cost_usd'))
                    _add_tokens(answer, event.get('usage'))
                else:
                    completion = event['message']
                    if 'cost_usd' in event and not event.get('billed_early'):
                        _add_cost(answer, 'main', event.get('cost_usd'))
                    if not event.get('billed_early'):
                        _add_tokens(answer, event.get('usage'))
                    if event.get('finish_reason'):
                        answer['last_finish_reason'] = event['finish_reason']
            calls = (completion or {}).get('tool_calls') or []
            interim = ''.join(held or ())
            dropped = bool(interim) and not run.interrupted() and any(
                (c.get('function') or {}).get('name') == 'test_in_game'
                or (before_bare and studio_import.starts_nothing(c.get('function') or {}, bare, tools_need))
                for c in calls)
            if dropped:
                # Kept in the model's own context (the completion below) and on the answer for a chat report;
                # never in the reply the user reads.
                answer.setdefault('dropped_interim', []).append(interim)
            elif interim:
                answer['content'] += interim
                run.events.put({'type': 'delta', 'content': interim})
            if run.interrupted():
                break
            if completion is None:
                raise RuntimeError('My reply came through incomplete. Please try again.')
            messages.append(completion)
            if not calls:
                # Neither a tool call nor a word is not an answer, and breaking
                # on it ends the turn with an empty reply. Measured in the edit
                # eval: after two large model tool results the model spent its
                # whole completion allowance thinking and came back with
                # nothing -- twice -- and a user who asked for a repair was told
                # neither what had been done nor that anything had failed. One
                # nudge recovers it; past that it is a dead round, not a slow one.
                if not (completion.get('content') or '').strip() and empty_rounds < MAX_EMPTY_ROUNDS:
                    empty_rounds += 1
                    answer['empty_rounds'] = empty_rounds
                    messages.append({'role': 'system', 'content':
                        'Your last reply was empty. Tell the user in plain words what you have done so far, what '
                        'you found and what is left -- or issue the next tool call. Do not repeat completed actions.'})
                    continue
                if not run.direct_call and _announced_action(completion.get('content')):
                    if consecutive_continuations >= MAX_CONSECUTIVE_ACTION_CONTINUATIONS:
                        raise TurnStopped('missing_action', 'I stopped before finishing that step. ' + KEPT)
                    consecutive_continuations += 1
                    answer['action_continuations'] = answer.get('action_continuations', 0) + 1
                    messages.append({'role': 'system', 'content':
                        'Your last reply announced a next action but contained no tool call. The task is still unfinished. '
                        'Continue from the completed receipts: issue the next needed tool call now, or state the actual '
                        'blocker/ask the necessary question. Do not repeat completed actions or bypass an approval.'})
                    answer['content'] += '\n\n'
                    run.events.put({'type': 'delta', 'content': '\n\n'})
                    continue
                break
            visual_content = []
            repeat_notes = []   # after the whole batch: tool results must stay contiguous
            batch_start = len(receipts)
            for call in calls:
                if run.interrupted():
                    break
                fn = call['function']
                # Browser string offsets keep text and tool cards in the order
                # they arrived, including emoji and subsequent provider rounds.
                receipt = {'id': uuid.uuid4().hex, 'name': fn['name'], 'status': 'running',
                           **(workflow.receipt_context() if not run.direct_call else {}),
                           'started_at': time.time(),
                           'content_offset': len(answer['content'].encode('utf-16-le', errors='surrogatepass')) // 2}
                answer['tools'].append(receipt)
                card = _task_card(run, fn['name'], parameters=receipt.get('arguments'))
                if card is not None:
                    receipt['task'] = card
                    estimate = card['facts'].get('estimate_seconds')
                    if estimate is not None:
                        receipt['estimate_seconds'] = estimate
                        receipt['estimate_samples'] = card['facts'].get('estimate_samples')
                # A tool's running updates (update_batch, on its own threads) and its result (below) take turns: once
                # the result is in, an update that comes late never replaces it.
                receipt_lock = threading.Lock()
                start_event = {'type': 'tool_start', 'tool': dict(receipt)}
                if card is not None:
                    start_event['task'] = card
                run.events.put(start_event)
                try:
                    prepared = (studio_import.prepare(fn['name'], fn['arguments'], fighter=picked_fighter,
                                                      words=user_words)
                                if import_offered and fn['name'] in studio_import.names()
                                else tools.prepare(fn['name'], fn['arguments']))
                    # Validated tool arguments contain handles/controls, never
                    # request-scoped credentials. Persist them for recovery and
                    # diagnosis instead of replaying the model's narration.
                    receipt['arguments'] = json.loads(prepared.arguments)
                    grant = None
                    action_key = (prepared.name, prepared.arguments)
                    if action_key in declined_actions:
                        raise ValueError('The user did not approve this action. Do not request it again this turn.')
                    held = refusals.held(refused, prepared.name)
                    if prepared.policy == 'approval' and held is None:
                        grant = _await_approval(run, receipt, prepared)
                    if held is not None:
                        result = held
                    elif run.interrupted():
                        result = {'note': 'Action cancelled. Nothing was executed.', 'approval_status': 'cancelled'}
                    elif prepared.policy == 'approval' and grant is None:
                        outcome = receipt['approval']['status']
                        declined_actions.add(action_key)
                        result = {'note': f'Action {outcome}. Nothing was executed.', 'approval_status': outcome}
                    else:
                        receipt['status'] = 'running'
                        if grant is not None:
                            _publish(run, receipt)
                        options = {'account_token': run.account_token} if run.account_token else {}
                        if prepared.name == 'test_in_game':
                            options.update(game_runtime=run.game_runtime, chat_id=run.chat_id)
                        if prepared.name in ('save_mod_copy', 'stage_lab'):
                            # A save records the chat it was made in: only that chat's auto-save updates it.
                            options['chat_id'] = run.chat_id
                        if prepared.name in ('generate_material', studio_import.PREFIX + 'import_model'):
                            # import_model's decision points ask on the turn's own key.
                            options['image_key'] = run.key
                        if prepared.name == 'download_website_mod':
                            options.update(safety_review=lambda safety, mod: _review_download_safety(run, safety, mod),
                                           cancelled=run.interrupted)
                        if prepared.name in {'create_clone_character', 'download_website_mods',
                                             studio_import.PREFIX + 'import_model'}:
                            # Bound now: a late update must reach its own call's receipt, never the call this loop
                            # has moved on to.
                            def update_batch(result, receipt=receipt, receipt_lock=receipt_lock):
                                with receipt_lock:
                                    # The call's result is in: a running update that comes late (an import's card
                                    # whose send hung past its reply) is dropped, never written over the result.
                                    if receipt.get('status') != 'running':
                                        return
                                    receipt['result'] = result
                                    _publish(run, receipt)
                            options.update(progress=update_batch, cancelled=run.cancelled.is_set)
                        result, reused = _execute_tool(run, prepared, grant, options)
                        # A replayed result made no new request, so it costs
                        # nothing new. Adding its recorded charge again reported
                        # one $0.04 image generation as $0.08 of spend.
                        if not reused and isinstance(result, dict):
                            if prepared.name == 'generate_material':
                                _add_cost(answer, 'images', result.get('cost_usd'))
                            if studio_import.is_studio_result(result) and result.get('cost_usd'):
                                # import_model's own asks (rigswap's).
                                _add_cost(answer, 'model_import', result.get('cost_usd'))
                        if reused:
                            receipt['reused_operation'] = True
                        if stage_job and whole_stage:
                            _stage_coverage(result, prepared.name, receipt['arguments'])
                        if isinstance(result, dict) and not reused:
                            _vault_note(run, result, prepared.name, receipt['arguments'], receipts,
                                        autosave_texts)
                except (ValueError, TypeError) as exc:
                    # Preserve the TYPED evidence through the conversion. Adding
                    # ValueError subclasses in tools.py achieved nothing while
                    # this line flattened them to a sentence, and
                    # `wishes.classify_blocker` refuses to read English.
                    result = {'error': str(exc)}
                    evidence = getattr(exc, 'evidence', '')
                    if evidence:
                        result['evidence'] = evidence
                    # ONE bounded repair for an invented tool name, using the
                    # operations actually advertised this turn. An invalid model
                    # call is not feature demand and must not end the turn; a
                    # second one is a loop, so the budget is one.
                    if evidence == 'unknown_tool' and not run.tool_repairs:
                        run.tool_repairs += 1
                        result['repair'] = 'bounded_tool_repair'
                        result['available_operations'] = sorted(
                            s['function']['name'] for s in tools.SCHEMAS)
                except Exception as exc:
                    # A tool that fails in an UNEXPECTED way ends that call, not
                    # the conversation. Catching only ValueError/TypeError meant
                    # anything else left the receipt `running` and took the whole
                    # turn down -- losing every completed action with it. A refusal
                    # the coordinator raised around the call (a stop, a newer
                    # message) is said as itself (assistant/refusals.py).
                    result = refusals.explain(exc)
                    if result is None:
                        logging.getLogger(__name__).exception('tool %s failed', fn['name'])
                        result = refusals.unexpected(exc)
                refusals.remember(refused, fn['name'], result)
                # The first call is the definitive answer to "which task is
                # this": a provisional guess from the words can be wrong, and a
                # wrong guess must cost one extra card, never a wrong action.
                # A declared task pinned only the turn-one guess: the card still
                # follows the called tool, any family, because it carries the
                # scope rules that tool needs.
                called_family = None if studio else recipes.family_for_tool(fn['name'])
                if called_family and called_family != recipe_family:
                    recipe_family = called_family
                with receipt_lock:      # a running update still being published goes first; a later one is dropped
                    receipt['completed_at'] = time.time()
                    receipt['elapsed_ms'] = round((receipt['completed_at'] - receipt['started_at']) * 1000)
                    receipt.update(result=result, status=result.get('approval_status')
                                   or ('error' if result.get('error') else 'done'))
                if receipt['status'] == 'done':
                    consecutive_continuations = 0
                _publish(run, receipt)
                messages.append({'role': 'tool', 'tool_call_id': call['id'],
                                 'content': json.dumps(compaction.fit_fresh(result), default=str)})
                # Older results this turn shrink to their essentials once two
                # newer ones exist (assistant/compaction.py).
                turn_tool_messages.append(messages[-1])
                compaction.compact_older(turn_tool_messages)
                if result.get('error') and not run.direct_call:
                    failure = (fn['name'], json.dumps(receipt.get('arguments', fn['arguments']), sort_keys=True),
                               str(result['error']))
                    repeated_failures[failure] = repeated_failures.get(failure, 0) + 1
                    if repeated_failures[failure] >= REPEAT_FAILURE_STOP:
                        receipts.append(receipt)
                        raise TurnStopped('repeated_failure',
                            'I kept running into the same problem, so I stopped: '
                            f'{str(result["error"])[:200].rstrip(".")}. Everything so far is kept.')
                    if repeated_failures[failure] == REPEAT_FAILURE_STOP - 1:
                        repeat_notes.append({'role': 'system', 'content':
                            f'That exact {fn["name"]} call has now failed identically {repeated_failures[failure]} '
                            'times. Repeating it will fail again. Change the arguments as the error says, use a '
                            'different approach, or stop and tell the user what is blocking.'})
                receipts.append(receipt)
                if not run.direct_call:
                    workflow.observe(receipt)
                    opened = receipt['status'] == 'done' and fn['name'] in ('skin_lab_open', 'stage_lab_open')
                    if opened and not budgeted and first_skin_session and fn['name'] == 'skin_lab_open':
                        # This turn started the chat's first recolor itself:
                        # from here on it is a skin job like a workflow turn.
                        budgeted = latest_only = True
                    if opened and not budgeted and first_stage_session and fn['name'] == 'stage_lab_open':
                        # Likewise the chat's first stage session, opened by the model itself.
                        budgeted = latest_only = stage_job = True
                    if opened and budgeted and fn['name'] == ('stage_lab_open' if stage_job else 'skin_lab_open'):
                        lab_open = True      # its roster narrows like a workflow turn's (above)
                visual_content.extend(tool_images(fn['name'], result))
            messages.extend(repeat_notes)
            if visual_content:
                # All tool replies precede image evidence. Rehydrate a bounded
                # history by file handle; never silently slice text/image pairs.
                messages = [m for m in messages if not (m['role'] == 'user' and isinstance(m.get('content'), list))]
                messages.append({'role': 'user', 'content': context_images(
                    receipts, loader=tool_images, fresh_receipts=receipts[batch_start:],
                    latest_only=latest_only) or visual_content})
            if completion.get('content') and not dropped:
                answer['content'] += '\n\n'
                run.events.put({'type': 'delta', 'content': '\n\n'})
            if run.direct_call:
                break
        answer['status'] = 'cancelled' if run.cancelled.is_set() else 'steered' if run.steering.is_set() else 'done'
        if not answer['content'] and answer['status'] == 'done' and not answer['tools']:
            answer['content'] = 'The tool results are ready above.'
    except Exception as exc:
        # A refused dispatch is a budget stop, not a crash: the user keeps the
        # completed work and is told why it stopped. It reaches here from deep
        # inside a provider generator, so it is mapped once, at the boundary.
        if isinstance(exc, taskflow.BudgetExceeded):
            exc = TurnStopped('cost_budget', LIMIT_REACHED)
        if isinstance(exc, taskflow.TaskFinished):
            exc = RuntimeError(ALREADY_FINISHED)
        if isinstance(exc, taskflow.TaskCancelled):
            run.cancelled.set()
        answer['status'] = 'cancelled' if run.cancelled.is_set() else 'steered' if run.steering.is_set() else 'error'
        if isinstance(exc, TurnStopped):
            answer['stop_reason'] = exc.reason
        answer['error'] = str(exc) if isinstance(exc, RuntimeError) else 'Something went wrong on my side, so I stopped. Please try again.'
    finally:
        if autosave_receipts is not None and not run.direct_call:
            try:
                _autosave(run, autosave_receipts, autosave_texts)
            except Exception:
                # A save that could not even be attempted never costs the turn its reply.
                logging.getLogger(__name__).exception('retexture auto-save failed')
        try:
            studio_import.record_turn(answer, chat_id=run.chat_id, model=MODEL)
        except Exception:
            logging.getLogger(__name__).exception('model-import ledger row not written')
        # A Stop accepted while the turn finished (an autosave still running) is kept: what was saved stays
        # saved, and the turn ends stopped instead of reporting a normal finish.
        if run.cancelled.is_set() and answer.get('status') in ('done', 'steered'):
            answer['status'] = 'cancelled'
        for receipt in answer['tools']:
            if receipt.get('approval', {}).get('status') == 'pending':
                receipt['approval'].update(status='cancelled' if run.interrupted() else 'interrupted', decided_at=time.time())
                receipt.update(status='cancelled', result={'note': 'Action was not executed.'})
        with _save_lock:
            store.save(run.chat_id, run.messages)
