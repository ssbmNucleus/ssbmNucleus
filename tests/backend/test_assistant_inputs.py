import json
import threading
import uuid

import pytest
from flask import Flask
from randall.assistant import engine, live_runs, store, tools
from randall.routes.assistant_bp import assistant_bp
from tests.backend.test_assistant_approvals import pending


def finish(run):
    events = []
    while True:
        event = run.events.get(timeout=8)
        events.append(event)
        if event['type'] == 'done':
            return events


def add(run, text, mode='queue'):
    ident = uuid.uuid4().hex
    live_runs.submit_input(run.chat_id, ident, text, {'page': 'vault'}, mode)
    return ident


@pytest.mark.parametrize('mode', ['queue', 'steer'])
def test_inputs_continue_in_same_stream_and_keep_history(vault, monkeypatch, mode):
    entered, release = threading.Event(), threading.Event()
    contexts = []
    def provider(messages, schemas, key, cancelled):
        contexts.append(messages)
        if len(contexts) == 1:
            yield {'type': 'delta', 'content': 'Original direction.'}
            entered.set()
            while not release.wait(.01):
                if cancelled.is_set():
                    return
        else:
            yield {'type': 'delta', 'content': 'Follow-up finished.'}
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Finished.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Make wood Mario', {}, request_key='private-key')
    try:
        assert entered.wait(5)
        ident = add(run, 'Use darker wood', mode)
        if mode == 'queue':
            assert not run.interrupted()
        release.set()
        events = finish(run)
        saved = store.get(run.chat_id)['messages']
        assert [m['content'] for m in saved if m['role'] == 'user'] == ['Make wood Mario', 'Use darker wood']
        assert saved[1]['status'] == ('steered' if mode == 'steer' else 'done')
        assert saved[2]['id'] == ident and saved[-1]['status'] == 'done'
        assert any(e['type'] == 'input_applied' for e in events)
        assert store.pending_inputs(run.chat_id) == [] and not run.key
        assert 'Make wood Mario' in json.dumps(contexts[-1])
        assert 'private-key' not in json.dumps(saved)
        live_runs.submit_input(run.chat_id, ident, 'Use darker wood', {'page': 'vault'}, mode)
        assert not store.pending_inputs(run.chat_id), 'A lost POST response must not duplicate an already-delivered message'
    finally:
        release.set()
        if run.id in live_runs._runs:
            live_runs.cancel(run.id); finish(run)


def test_steering_waits_for_current_tool_but_skips_old_remaining_calls(vault, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    actual_execute, executed, turns = tools.execute, [], []
    def execute(call, *args, **kwargs):
        executed.append(call.name); entered.set()
        assert release.wait(5)
        return actual_execute(call, *args, **kwargs)
    def provider(messages, *args):
        turns.append(messages)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Proceeding', **(
            {'tool_calls': [{'id': str(i), 'function': {'name': 'search_vault', 'arguments': '{}'}} for i in range(2)]}
            if len(turns) == 1 else {})}}
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(tools, 'execute', execute)
    run = engine.start(None, 'Look', {}, request_key='test')
    try:
        assert entered.wait(5)
        add(run, 'Change direction', 'steer')
        assert executed == ['search_vault'] and run.id in live_runs._runs
        release.set(); finish(run)
        assert executed == ['search_vault']
        saved = store.get(run.chat_id)['messages']
        assert saved[1]['tools'][0]['status'] == 'done'
        assert saved[1]['tools'][0]['elapsed_ms'] >= 0
        assert 'search_vault' in json.dumps(turns[-1]), 'Completed tool state reaches the correction'
    finally:
        release.set()
        if run.id in live_runs._runs:
            live_runs.cancel(run.id); finish(run)


def test_stop_pauses_queue_and_resume_consumes_stored_context(vault, monkeypatch):
    entered = threading.Event()
    def provider(messages, schemas, key, cancelled):
        entered.set()
        if len([m for m in messages if m['role'] == 'user']) == 1:
            while not cancelled.is_set():
                threading.Event().wait(.01)
            return
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Resumed'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Start', {}, request_key='test')
    assert entered.wait(5)
    ident = add(run, 'Queued')
    live_runs.cancel(run.id); finish(run)
    assert store.pending_inputs(run.chat_id)[0]['id'] == ident
    resumed = engine.start(run.chat_id, 'Forged replacement', {'page': 'wrong'}, request_key='fresh', input_id=ident)
    finish(resumed)
    saved = store.get(run.chat_id)['messages']
    assert saved[-2]['content'] == 'Queued' and saved[-2]['context'] == {'page': 'vault'}
    assert not store.pending_inputs(run.chat_id)


def test_pending_routes_persist_edit_promote_remove_and_reject_credentials(vault):
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    cid = store.save(None, [{'role': 'user', 'content': 'Wood Mario'}])
    root = f'/api/assistant/chats/{cid}/inputs'
    ident = uuid.uuid4().hex
    payload = {'id': ident, 'message': 'Also the hat', 'context': {'page': 'vault', 'api_key': 'secret'}}
    assert client.post(root, json={**payload, 'api_key': 'secret'}).status_code == 400
    assert client.post(root, json=payload).status_code == 200
    assert client.post(root, json=payload).status_code == 200
    pending = client.get(f'/api/assistant/chats/{cid}').get_json()['pending_inputs']
    assert len(pending) == 1 and 'secret' not in json.dumps(pending)
    assert client.patch(f'{root}/{ident}', json={'message': 'Make it oak', 'mode': 'steer'}).status_code == 200
    assert store.pending_inputs(cid)[0]['content'] == 'Make it oak'
    assert client.delete(f'{root}/{ident}').status_code == 200
    assert client.patch(f'{root}/{ident}', json={'message': 'Too late'}).status_code == 409
    assert not store.pending_inputs(cid)


def test_send_all_steers_every_message_oldest_first_once(vault, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    requests = []
    def provider(messages, schemas, key, cancelled):
        requests.append(messages)
        if len(requests) == 1:
            entered.set()
            while not release.wait(.01):
                if cancelled.is_set(): return
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Done'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Original', {}, request_key='test')
    try:
        assert entered.wait(5)
        ids = [add(run, text) for text in ('Second', 'Third', 'Fourth')]
        live_runs.change_inputs(run.chat_id, list(reversed(ids)))
        release.set()
        events = finish(run)
        users = [m for m in store.get(run.chat_id)['messages'] if m['role'] == 'user']
        assert [m['content'] for m in users] == ['Original', 'Second', 'Third', 'Fourth']
        assert len(requests) == 2
        applied = [event for event in events if event['type'] == 'input_applied']
        assert len(applied) == 1 and [m['id'] for m in applied[0]['users']] == ids
        live_runs.change_inputs(run.chat_id, ids)
        assert not store.pending_inputs(run.chat_id)
    finally:
        release.set()
        if run.id in live_runs._runs: live_runs.cancel(run.id); finish(run)


def test_delivery_is_atomic_and_failed_lookup_does_not_lose_inputs(vault):
    cid = store.save(None, [{'role': 'user', 'content': 'Original'}])
    ident = uuid.uuid4().hex
    store.add_input(cid, ident, 'Pending', {}, 'queue')
    with pytest.raises(RuntimeError):
        store.deliver_inputs(cid, [ident, uuid.uuid4().hex], store.get(cid)['messages'], {'role': 'assistant'})
    assert store.pending_inputs(cid)[0]['id'] == ident
    assert len(store.get(cid)['messages']) == 1


def test_steering_cancels_old_approval_without_executing_it(vault, pending):
    run, approval = pending
    add(run, 'Leave those folders alone', 'steer')
    finish(run)
    saved = store.get(run.chat_id)['messages']
    assert saved[1]['tools'][0]['approval']['status'] == 'cancelled'
    assert '_assistant_actions' not in vault.read()
    with pytest.raises(RuntimeError):
        live_runs.decide_approval(run.chat_id, approval['id'], 'approve')


def test_resume_after_restart_settles_interrupted_history(vault, monkeypatch):
    cid = store.save(None, [{'role': 'user', 'content': 'Original'},
                           {'id': 'old', 'role': 'assistant', 'content': 'Working', 'status': 'running', 'tools': []}])
    ident = uuid.uuid4().hex
    store.add_input(cid, ident, 'Continue', {'files': []}, 'queue')
    def provider(*args):
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Finished'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(cid, 'Continue', {}, request_key='fresh', input_id=ident)
    finish(run)
    assert store.get(cid)['messages'][1]['status'] == 'interrupted'
