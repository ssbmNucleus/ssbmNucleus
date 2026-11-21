"""The live runs: the in-memory registry and its locks, cancelling, queued and steering inputs,
approvals (publishing a receipt, waiting for a decision, paging a download's files), and the SSE stream."""

import contextlib
import json
import queue
import threading
import uuid
import copy
import time
from dataclasses import dataclass, field

from . import store, tools, approvals
from .tasks import coordinator as taskflow


@dataclass
class Run:
    chat_id: str
    messages: list
    context: dict
    key: str = field(repr=False)
    account_token: str = field(default=None, repr=False)
    game_runtime: dict = field(default=None, repr=False)
    direct_call: dict = field(default=None, repr=False)
    answer: dict = field(default=None, repr=False)
    download_plans: dict = field(default_factory=dict, repr=False)
    task: object = field(default=None, repr=False)   # this turn's coordinator TaskContext
    # One bounded repair per turn for an invented tool name. A second is a
    # loop, and an invalid model call must never end the turn silently.
    tool_repairs: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    events: queue.Queue = field(default_factory=queue.Queue)
    cancelled: threading.Event = field(default_factory=threading.Event)
    steering: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    start_message_id: str = ''

    def interrupted(self):
        return self.cancelled.is_set() or self.steering.is_set()


class _Interruption:
    """Provider-compatible cancellation that also observes a steering boundary."""
    def __init__(self, run):
        self.run = run

    def is_set(self):
        return self.run.interrupted()

    def set(self):
        self.run.cancelled.set()


_lock = threading.RLock()
_save_lock = threading.RLock()
_runs = {}
# Run ids a Stop named before their run existed: the window picks a reply's run id itself and sends it with the
# message, so a Stop pressed before the `started` event can still name the run. `engine.start` refuses those.
_stopped_early = {}
_STOPPED_EARLY_KEPT = 64


def active_run(chat_id=None):
    with _lock:
        return next((r for r in _runs.values() if chat_id is None or r.chat_id == chat_id), None)


def cancel(run_id):
    with _lock:
        run = _runs.get(run_id)
        if run:
            run.cancelled.set()
            # Stop is a task-level instruction, not just a flag this loop reads:
            # the coordinator has to stop stages and refuse further dispatches
            # at their next safe boundary, and record when it was asked.
            if run.task is not None:
                taskflow._guard(run.task.request_cancel, 'user_stop')
            with run.condition:
                run.condition.notify_all()
        else:
            _stopped_early[run_id] = time.time()
            for old in sorted(_stopped_early, key=_stopped_early.get)[:-_STOPPED_EARLY_KEPT]:
                del _stopped_early[old]
        return bool(run)


def stopped_before_start(run_id):
    """Whether a Stop named this run id before its run started (once: the id is forgotten)."""
    with _lock:
        return _stopped_early.pop(run_id, None) is not None


def settle_dead_run(messages):
    """Settle what a run that no longer exists left open in its transcript (the app quit or crashed mid-turn).

    An answer still `running` is interrupted. A tool waiting for approval never ran, whether or not the approval
    was decided before the run died, so it is interrupted with nothing executed. A tool still `running` may have
    changed things, so it is an error that says to look before retrying.
    """
    for message in messages:
        if message.get('status') == 'running':
            message['status'] = 'interrupted'
        for receipt in message.get('tools', []):
            approval = receipt.get('approval')
            pending = bool(approval) and approval.get('status') == 'pending'
            if pending:
                approval['status'] = 'interrupted'
            if pending or receipt.get('status') == 'awaiting_approval':
                receipt.update(status='interrupted', result={'note': 'Interrupted by an app restart before it ran. Nothing was executed.'})
            elif receipt.get('status') == 'running':
                receipt.update(status='error', result={'error': 'This tool was interrupted. Inspect its working state before retrying.'})


def _inputs_changed(chat_id):
    pending = store.pending_inputs(chat_id)
    run = next((r for r in _runs.values() if r.chat_id == chat_id and not r.direct_call), None)
    if run:
        if any(item['mode'] == 'steer' for item in pending):
            run.steering.set()
        else:
            run.steering.clear()
        with run.condition:
            run.condition.notify_all()
        run.events.put({'type': 'inputs_changed', 'pending_inputs': pending})
    return {'pending_inputs': pending, 'reply_run_id': run.id if run else None}


def submit_input(chat_id, input_id, message, context, mode):
    with _lock:
        store.add_input(chat_id, input_id, message, context, mode)
        return _inputs_changed(chat_id)


def change_input(chat_id, input_id, **changes):
    with _lock:
        store.change_input(chat_id, input_id, **changes)
        return _inputs_changed(chat_id)


def change_inputs(chat_id, input_ids, *, remove=False):
    with _lock:
        active = any(r.chat_id == chat_id and not r.direct_call for r in _runs.values())
        store.change_inputs(chat_id, input_ids, remove=remove, mode='steer' if active else 'queue')
        return _inputs_changed(chat_id)


def _task_card(run, tool_name='', *, parameters=None):
    """The envelope payload the cards read, in the shape they actually read it.

    B2's `envelopeOf` (frontend taskEnvelope.js) looks inside the TOOL for
    `result.task_result`, `result.envelope`, `result.task` and `tool.task`; the
    SSE reducer keeps `event.tool` and discards a sibling `event.task`. So the
    envelope rides on the receipt, not beside it. `estimate_seconds` and
    `round_limit` are read from the message or from envelope FACTS, so they go
    in facts as well -- `applyTurnProgress` drops unknown event fields.
    """
    task = getattr(run, 'task', None)
    if task is None:
        return None
    envelope = task.envelope.to_dict()
    facts = dict(envelope.get('facts') or {})
    if run.answer.get('round_limit') is not None:
        facts['round_limit'] = run.answer['round_limit']
    if tool_name:
        estimate, samples = taskflow._guard(
            taskflow.store.stage_duration_estimate, f'tool:{tool_name}',
            parameter_hash=taskflow.contracts.digest({'arguments': parameters})
            if parameters is not None else None) or (None, 0)
        if estimate is not None:
            facts['estimate_seconds'] = estimate
            facts['estimate_samples'] = samples
    envelope['facts'] = facts
    envelope['committed_usd'] = task.committed_usd
    return envelope


def _publish(run, receipt, kind='tool_result'):
    card = _task_card(run, receipt.get('name', ''), parameters=receipt.get('arguments'))
    if card is not None:
        receipt['task'] = card            # inside the receipt: see _task_card
        if card['facts'].get('estimate_seconds') is not None:
            receipt['estimate_seconds'] = card['facts']['estimate_seconds']
            receipt['estimate_samples'] = card['facts'].get('estimate_samples')
    with _save_lock:
        store.save(run.chat_id, run.messages)
    event = {'type': kind, 'tool': copy.deepcopy(receipt)}
    if card is not None:
        event['task'] = card              # kept for a consumer that reads siblings
    run.events.put(event)


def decide_approval(chat_id, approval_id, decision, choice=None):
    if decision not in ('approve', 'deny'):
        raise ValueError('Decision must be approve or deny.')
    with _lock:
        run = next((r for r in _runs.values() if r.chat_id == chat_id and any(
            t.get('approval', {}).get('id') == approval_id for t in r.answer.get('tools', []))), None)
        if run:
            with run.condition:
                receipt = next((t for t in run.answer.get('tools', [])
                                if t.get('approval', {}).get('id') == approval_id), None)
                if not receipt:
                    raise ValueError('Approval not found in this conversation.')
                approval = receipt['approval']
                if run.cancelled.is_set() and approval['status'] == 'pending':
                    raise RuntimeError('This turn has been stopped.')
                previous = dict(approval)
                if approvals.decide(approval, decision, choice):
                    try:
                        _publish(run, receipt, 'approval_update')
                    except Exception:
                        approval.clear(); approval.update(previous)
                        raise
                    run.condition.notify_all()
                return copy.deepcopy(receipt)
        # A lost HTTP response can be retried even after the worker finished.
        chat = store.get(chat_id)
        receipt = next((t for m in (chat or {}).get('messages', []) for t in m.get('tools', [])
                        if t.get('approval', {}).get('id') == approval_id), None)
        if not receipt:
            raise ValueError('Approval not found in this conversation.')
        target = 'approved' if decision == 'approve' else 'denied'
        if receipt['approval']['status'] != target:
            raise RuntimeError('This approval is no longer pending. Request a fresh action.')
        approvals.decide(receipt['approval'], decision, choice)
        return receipt


def _await_approval(run, receipt, call):
    with run.condition:
        preview = json.loads(call.preview)
        if (run.direct_call and call.name == 'download_website_mod'
                and any(option['id'] == 'all' for option in preview.get('choices') or [])):
            # Preserve "All variants" selected on the original card -- but only
            # where that is an offered id. A menu approval offers icon grid vs
            # background, and overwriting its default with 'all' made the card
            # arrive preselecting something nobody offered (review JJ, 5).
            preview['default_choice'] = 'all'
        receipt.update(status='awaiting_approval', approval=approvals.request({
            **preview, 'tool': call.name, 'arguments': json.loads(call.arguments)}))
        if call.name in ('download_website_mod', 'download_website_mods'):
            run.download_plans[receipt['approval']['id']] = json.loads(call.plan)
        _publish(run, receipt, 'approval_requested')
        approval = receipt['approval']
        # Time spent waiting for a person is not time spent working, and the
        # report states them separately: a 25-minute import that was 20 minutes
        # of waiting for one click is a different problem from a slow pipeline.
        task = getattr(run, 'task', None)
        waiting = (task.waiting('approval', call.name) if task is not None
                   else contextlib.nullcontext())
        with waiting:
            while approval['status'] == 'pending' and not run.interrupted():
                remaining = approval['expires_at'] - time.time()
                if remaining <= 0:
                    approval.update(status='expired', decided_at=time.time())
                    break
                run.condition.wait(timeout=min(remaining, 1))
        if run.interrupted():
            approval.update(status='cancelled', decided_at=time.time())
        _publish(run, receipt, 'approval_update')
        if approval['status'] == 'approved':
            return approvals.Grant(call.fingerprint, approval.get('choice'))
        return None


def download_files(chat_id, approval_id, choice='all', query='', offset=0, kind='mods'):
    # `choice` here selects an INVENTORY SCOPE, which only a variant approval
    # has. A menu approval's choice is an import interpretation of one object;
    # rejecting it disabled the dialog's confirm button, so an ambiguous menu
    # file could not be approved at all (2026-09-22 review JJ, 5).
    if kind not in ('mods', 'files') or len(query) > 160 or offset < 0:
        raise ValueError('Invalid file list filter.')
    if choice not in ('all', 'default'):
        choice = 'all'
    with _lock:
        run = next((r for r in _runs.values() if r.chat_id == chat_id and approval_id in r.download_plans), None)
        if not run:
            raise RuntimeError('This download review is no longer active.')
        with run.condition:
            plan = run.download_plans.get(approval_id)
            if not plan:
                raise ValueError('Download review not found.')
            if choice == 'default':
                plan = plan.get('default_variant')
                if not plan:
                    raise ValueError('No default-variant option is available for this review.')
            contents = plan['contents']
            rows = contents[kind]
            if query.strip():
                needle = query.strip().casefold()
                rows = [row for row in rows if needle in ' '.join(str(row.get(k) or '') for k in ('name', 'character', 'color', 'type')).casefold()]
            return {'items': rows[offset:offset + 20], 'total': len(rows), 'offset': offset,
                    'summary': contents['summary'],
                    'next_offset': offset + 20 if offset + 20 < len(rows) else None}


def _review_download_safety(run, safety, mod):
    # A separate receipt preserves the original download approval and its retry
    # semantics. The grant is bound to the bytes kept in this worker's temp dir.
    receipt = {'id': uuid.uuid4().hex, 'name': 'review_download_safety', 'status': 'running',
               'content_offset': len(run.answer['content'].encode('utf-16-le', errors='surrogatepass')) // 2}
    run.answer['tools'].append(receipt)
    preview = {'title': 'Slippi safety', 'slippi_review': True, 'mod_title': mod['title'],
               'post_id': mod.get('post_id'), 'mod_image': mod.get('image'),
               'unsafe_costumes': safety['unsafe_costumes'], 'default_choice': 'fix',
               'choices': [{'id': 'fix', 'label': 'Fix and add to vault'},
                           {'id': 'import_as_is', 'label': 'Add without fixing'}]}
    call = tools.PreparedCall('review_download_safety', '{}', json.dumps(safety), json.dumps(preview), 'approval')
    grant = _await_approval(run, receipt, call)
    action = grant.choice if grant and grant.consume(call.fingerprint) else None
    receipt['status'] = 'done' if action else receipt['approval']['status']
    receipt['result'] = {'slippi_action': action, 'approval_status': receipt['approval']['status']}
    _publish(run, receipt)
    return {'action': action, 'status': receipt['approval']['status']}


def stream(run):
    try:
        yield 'data: ' + json.dumps({'type': 'started', 'run_id': run.id, 'chat_id': run.chat_id, 'message_id': run.start_message_id or run.answer['id']}) + '\n\n'
        while True:
            try:
                event = run.events.get(timeout=1)
            except queue.Empty:
                yield ': heartbeat\n\n'
                continue
            yield 'data: ' + json.dumps(event) + '\n\n'
            if event['type'] == 'done':
                break
    finally:
        # A browser reload must not decide or discard a pending approval.
        # The stored receipt + chat polling recover it; explicit Stop cancels.
        pass
