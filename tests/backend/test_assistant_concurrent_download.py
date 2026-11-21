import threading

import pytest
from flask import Flask

from randall.assistant import engine, live_runs, store
from randall.routes.assistant_bp import assistant_bp
from tests.backend.test_assistant_website import catalog
from tests.backend.test_assistant_slippi import unsafe_download


@pytest.mark.parametrize('order', ['reply_first', 'download_first', 'cancel_reply', 'cancel_download'])
def test_download_and_safety_approval_during_reply(vault, unsafe_download, monkeypatch, order):
    release, started = threading.Event(), threading.Event()
    provider_calls = []
    def provider(messages, schemas, key, cancelled):
        provider_calls.append(1)
        yield {'type': 'delta', 'content': 'First '}
        started.set()
        while not release.wait(.01):
            if cancelled.is_set(): return
        yield {'type': 'delta', 'content': 'last.'}
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'First last.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    reply = engine.start(None, 'Explain this mod', {}, request_key='fake')
    download = None
    def wait_approval(run):
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': return event['tool']['approval']
    def approve(approval, choice=None):
        body = {'decision': 'approve', **({'choice': choice} if choice else {})}
        response = client.post(f"/api/assistant/chats/{reply.chat_id}/approvals/{approval['id']}", json=body)
        assert response.status_code == 200, response.get_json()
    try:
        assert started.wait(5)
        response = client.post('/api/assistant/website/download', json={'chat_id': reply.chat_id, 'post_id': 123})
        assert response.status_code == 200
        download = live_runs._runs[response.get_json()['run_id']]
        assert download.messages is reply.messages and download.answer is not reply.answer
        approval = wait_approval(download)
        snapshot = client.get(f'/api/assistant/chats/{reply.chat_id}').get_json()
        assert snapshot['reply_run_id'] == reply.id and snapshot['download_run_ids'] == [download.id]
        assert snapshot['messages'][-2]['content'] == 'First '
        assert client.get(f"/api/assistant/chats/{reply.chat_id}/approvals/{approval['id']}/files").status_code == 200
        approve(approval)
        safety = wait_approval(download)
        assert not unsafe_download[1]
        if order in ('reply_first', 'cancel_reply'):
            if order == 'cancel_reply': live_runs.cancel(reply.id)
            release.set(); list(live_runs.stream(reply))
            assert download.id in live_runs._runs
            approve(safety, 'fix'); list(live_runs.stream(download))
        else:
            if order == 'cancel_download': live_runs.cancel(download.id)
            else: approve(safety, 'fix')
            list(live_runs.stream(download))
            assert reply.id in live_runs._runs and not reply.cancelled.is_set()
            release.set(); list(live_runs.stream(reply))
        saved = store.get(reply.chat_id)['messages']
        text = next(message for message in saved if message.get('id') == reply.answer['id'])
        receipt = next(message for message in saved if message.get('id') == download.answer['id'])
        assert text['content'] == ('First ' if order == 'cancel_reply' else 'First last.')
        assert text['tools'] == [] and receipt['content'] == ''
        assert unsafe_download[1] == ([] if order == 'cancel_download' else ['fix'])
        assert len(provider_calls) == 1
        assert len({message.get('id') for message in saved if message['role'] == 'assistant'}) == 2
    finally:
        release.set()
        for run in (reply, download):
            if run and run.id in live_runs._runs:
                live_runs.cancel(run.id); list(live_runs.stream(run))
