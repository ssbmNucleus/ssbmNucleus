"""A run's leftovers after the app died (F-D-1), and a Stop pressed before the backend's `started` event (F-D-5)."""
import threading
import time
import uuid

from flask import Flask

from randall.assistant import engine, live_runs, store


def _client():
    from randall.routes.assistant_bp import assistant_bp
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    return app.test_client()


def _wait_idle():
    deadline = time.time() + 5
    while live_runs.active_run() and time.time() < deadline:
        time.sleep(.01)
    assert not live_runs.active_run()


def _left_by_a_dead_run():
    return [
        {'role': 'user', 'content': 'download it'},
        {'id': 'a' * 32, 'role': 'assistant', 'status': 'running', 'tools': [
            # Approved, but the app died before the run set it running: it never ran.
            {'id': 't1', 'name': 'download_website_mod', 'status': 'awaiting_approval',
             'approval': {'id': 'p1', 'status': 'approved'}},
            {'id': 't2', 'name': 'organize_skins', 'status': 'awaiting_approval',
             'approval': {'id': 'p2', 'status': 'pending'}},
            {'id': 't3', 'name': 'import_model', 'status': 'running'},
            {'id': 't4', 'name': 'list_skins', 'status': 'done', 'result': {'count': 3}},
        ]},
    ]


def test_settle_dead_run_closes_every_open_tool():
    messages = _left_by_a_dead_run()
    live_runs.settle_dead_run(messages)
    answer = messages[-1]
    approved, pending, running, done = answer['tools']
    assert answer['status'] == 'interrupted'
    # A decided approval whose tool never ran no longer reads as "waiting", which kept a chat's downloads blocked.
    assert approved['status'] == 'interrupted' and approved['approval']['status'] == 'approved'
    assert 'Nothing was executed' in approved['result']['note']
    assert pending['status'] == 'interrupted' and pending['approval']['status'] == 'interrupted'
    assert running['status'] == 'error' and 'interrupted' in running['result']['error']
    assert done == {'id': 't4', 'name': 'list_skins', 'status': 'done', 'result': {'count': 3}}


def test_reopened_chat_and_next_turn_settle_the_same_way(vault, monkeypatch):
    chat_id = store.save(None, _left_by_a_dead_run())
    shown = _client().get(f'/api/assistant/chats/{chat_id}').get_json()
    assert [tool['status'] for tool in shown['messages'][-1]['tools']] == ['interrupted', 'interrupted', 'error', 'done']

    def provider(*args):
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Okay.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(chat_id, 'carry on', {}, request_key='fake-key')
    list(live_runs.stream(run))
    _wait_idle()
    old = store.get(chat_id)['messages'][1]
    assert [tool['status'] for tool in old['tools']] == ['interrupted', 'interrupted', 'error', 'done']


def test_stop_before_start_refuses_the_run_and_saves_nothing(vault, monkeypatch):
    monkeypatch.setattr(engine, '_provider', lambda *args: iter(()))
    client = _client()
    run_id = uuid.uuid4().hex
    before = {chat["id"] for chat in store.list_chats()}
    assert client.post(f'/api/assistant/runs/{run_id}/cancel', json={}).get_json() == {'cancelled': False}
    response = client.post('/api/assistant/chat', json={'message': 'hello', 'api_key': 'fake-key', 'run_id': run_id})
    assert response.status_code == 409
    assert not live_runs.active_run()
    assert {chat['id'] for chat in store.list_chats()} == before
    # The early Stop is spent: the same id can start a run once.
    assert not live_runs.stopped_before_start(run_id)


def test_window_run_id_names_the_run_so_stop_reaches_it(vault, monkeypatch):
    release = threading.Event()

    def provider(*args, **kwargs):
        release.wait(5)   # busy until the test lets it finish
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Okay.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run_id = uuid.uuid4().hex
    run = engine.start(None, 'hello', {}, request_key='fake-key', run_id=run_id)
    try:
        assert run.id == run_id and live_runs.active_run().id == run_id
        assert _client().post(f'/api/assistant/runs/{run_id}/cancel', json={}).get_json() == {'cancelled': True}
        assert run.cancelled.is_set()
    finally:
        release.set()
        list(live_runs.stream(run))
        _wait_idle()


def test_run_ids_are_checked():
    client = _client()
    assert client.post('/api/assistant/runs/not-a-run/cancel', json={}).status_code == 400
    response = client.post('/api/assistant/chat', json={'message': 'hello', 'api_key': 'fake-key', 'run_id': '../x'})
    assert response.status_code == 400
