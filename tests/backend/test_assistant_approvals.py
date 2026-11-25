import json
import queue
import time
import pytest
from flask import Flask
from randall.assistant import approvals, engine, live_runs, store, tools
from core import metadata
from tests.backend.test_assistant import seed
from tests.backend.window_key import UI_KEY, WINDOW, as_the_window  # noqa: F401

pytestmark = pytest.mark.usefixtures('as_the_window')

ARGS = {'character': 'Marth', 'skin_ids': ['a', 'b'], 'folder_name': 'Favorites'}


@pytest.fixture
def pending(vault, monkeypatch):
    seed(vault)
    turns = []
    def provider(*args):
        turns.append(1)
        if len(turns) == 1:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'provider-call', 'function': {'name': 'organize_skins', 'arguments': json.dumps(ARGS)}}]}}
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Finished.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Move these into Favorites', {}, request_key='fake-key')
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested':
                break
        yield run, event['tool']['approval']
    finally:
        live_runs.cancel(run.id)
        deadline = time.time() + 5
        while live_runs.active_run() and time.time() < deadline:
            time.sleep(.01)
        assert not live_runs.active_run()


def finish(run):
    list(live_runs.stream(run))
    return store.get(run.chat_id)['messages'][-1]['tools'][0]


def test_approval_waits_previews_and_executes_once(vault, pending):
    run, approval = pending
    assert '_assistant_actions' not in vault.read()
    assert approval['changes'][1] == {'item': 'Blue Marth', 'from': 'Original', 'to': 'Favorites'}
    assert store.get(run.chat_id)['messages'][-1]['tools'][0]['status'] == 'awaiting_approval'
    live_runs.decide_approval(run.chat_id, approval['id'], 'approve')
    receipt = finish(run)
    assert receipt['status'] == 'done' and receipt['result']['count'] == 2
    live_runs.decide_approval(run.chat_id, approval['id'], 'approve')
    assert len(vault.read()['_assistant_actions']) == 1
    with pytest.raises(RuntimeError):
        live_runs.decide_approval(run.chat_id, approval['id'], 'deny')


def test_deny_and_duplicate_deny_do_not_mutate(vault, pending):
    run, approval = pending
    live_runs.decide_approval(run.chat_id, approval['id'], 'deny')
    assert finish(run)['status'] == 'denied'
    live_runs.decide_approval(run.chat_id, approval['id'], 'deny')
    assert '_assistant_actions' not in vault.read()


def test_stop_wakes_pending_request_and_late_approve_is_rejected(vault, pending):
    run, approval = pending
    live_runs.cancel(run.id)
    assert finish(run)['approval']['status'] == 'cancelled'
    with pytest.raises(RuntimeError):
        live_runs.decide_approval(run.chat_id, approval['id'], 'approve')
    assert '_assistant_actions' not in vault.read()


def test_expired_approval_cannot_execute(vault, pending):
    run, approval = pending
    with run.condition:
        run.messages[-1]['tools'][0]['approval']['expires_at'] = time.time() - 1
        run.condition.notify_all()
    assert finish(run)['approval']['status'] == 'expired'
    assert '_assistant_actions' not in vault.read()


def test_stale_selection_rejects_even_approved_action(vault, pending):
    run, approval = pending
    with metadata.metadata_transaction() as data:
        data['characters']['Marth']['skins'][0]['folder_id'] = 'old'
    live_runs.decide_approval(run.chat_id, approval['id'], 'approve')
    receipt = finish(run)
    assert receipt['status'] == 'error'
    assert 'changed while approval' in receipt['result']['error']
    assert '_assistant_actions' not in vault.read()


def test_reload_and_scoped_decision_endpoint(vault, pending, monkeypatch):
    from randall.routes.assistant_bp import assistant_bp
    run, approval = pending
    stream = live_runs.stream(run)
    next(stream); stream.close()
    assert not run.cancelled.is_set()
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    chat = client.get(f'/api/assistant/chats/{run.chat_id}').get_json()
    assert chat['active_run_id'] == run.id
    assert chat['messages'][-1]['tools'][0]['approval']['id'] == approval['id']
    route = f'/api/assistant/chats/{run.chat_id}/approvals/{approval["id"]}'
    assert client.post(route, headers=WINDOW, json={'decision': 'approve', 'arguments': {'folder_name': 'Injected'}}).status_code == 400
    assert client.post(route.replace(run.chat_id, 'b' * 32), headers=WINDOW, json={'decision': 'approve'}).status_code == 404
    # Only the person at the window answers: the user's own AI over MCP, or a script, holds the backend token too
    # but not the window's key, and an agent's request says it is one.
    callers = (({}, 403, 'not_the_app_window'), ({'X-Nucleus-UI-Key': 'guess'}, 403, 'not_the_app_window'),
               (dict(WINDOW, **{'X-Nucleus-Agent': '1'}), 403, 'automation_caller'))
    for headers, status, code in callers:
        refused = client.post(route, headers=headers, json={'decision': 'approve'})
        assert (refused.status_code, refused.get_json()['code']) == (status, code), headers
    monkeypatch.delenv('NUCLEUS_UI_APPROVAL_KEY')                     # no key handed over: fail closed
    refused = client.post(route, headers=WINDOW, json={'decision': 'approve'})
    assert (refused.status_code, refused.get_json()['code']) == (503, 'ui_approval_channel_unavailable')
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    assert '_assistant_actions' not in vault.read()                   # none of those moved anything
    assert client.post(route, headers=WINDOW, json={'decision': 'approve'}).status_code == 200
    finish(run)
    assert client.post(route, headers=WINDOW, json={'decision': 'approve'}).status_code == 200


def test_grants_bound_to_exact_call_and_single_use(vault):
    seed(vault)
    call = tools.prepare('organize_skins', ARGS)
    other = tools.prepare('organize_skins', {**ARGS, 'folder_name': 'Other'})
    grant = approvals.Grant(call.fingerprint)
    assert 'error' in tools.execute(other, grant)
    assert 'error' in tools.execute(call, True)
    assert 'error' in tools.execute(call)
    assert tools.execute(call, grant)['count'] == 2
    assert 'error' in tools.execute(call, grant)
    assert len(vault.read()['_assistant_actions']) == 1


def test_future_tools_require_explicit_policy_and_guarded_executor(monkeypatch):
    monkeypatch.setitem(tools.REGISTRY, 'future', tools.ToolSpec('unknown', lambda: {}))
    with pytest.raises(ValueError, match='not available'):
        tools.prepare('future', {})
    monkeypatch.setitem(tools.REGISTRY, 'future', tools.ToolSpec('approval', lambda: {}))
    monkeypatch.setattr(tools, 'SCHEMAS', [*tools.SCHEMAS, tools._schema('future', 'test', {})])
    with pytest.raises(ValueError, match='guarded executor'):
        tools.prepare('future', {})
    called = []
    monkeypatch.setitem(tools.REGISTRY, 'future', tools.ToolSpec('approval', None,
        lambda args: ({'revision': 1}, {'title': 'Future operation'}),
        lambda args, plan: called.append(plan) or {'note': 'Done'}))
    call = tools.prepare('future', {})
    assert 'error' in tools.execute(call)
    assert tools.execute(call, approvals.Grant(call.fingerprint))['note'] == 'Done'
    assert called == [{'revision': 1}]
