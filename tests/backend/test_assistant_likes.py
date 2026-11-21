import copy
import json
import pytest
from randall.assistant import engine, live_runs, store, tools
from randall.website import website, website_posts
from tests.backend import website_site
from tests.backend.website_site import media


@pytest.fixture
def likes(monkeypatch):
    state = {'liked': False, 'like_count': 10}
    calls = []
    website_site.install(monkeypatch, {'id': 123, 'title': 'Kermit', 'like_count': state['like_count']})

    def rpc(name, args, account_token=None):
        calls.append((name, account_token))
        assert account_token == 'test-account-secret'
        if name == 'api_toggle_like':
            state['liked'] = not state['liked']
            state['like_count'] += 1 if state['liked'] else -1
        return copy.deepcopy(state)
    for _mod in (website, website_posts):
        monkeypatch.setattr(_mod, '_rpc', rpc)
    return state, calls


def test_like_unlike_and_retries_use_account_and_desired_state(likes):
    state, calls = likes
    call = tools.prepare('set_website_mod_like', {'post_id': 123, 'liked': True})
    assert 'Sign in' in tools.execute(call)['error']
    assert calls == []
    for _ in range(2):
        result = tools.execute(call, account_token='test-account-secret')
        assert result['liked'] and result['like_count'] == 11
    assert [name for name, _ in calls].count('api_toggle_like') == 1
    result = website_posts.set_website_mod_like(123, False, 'test-account-secret')
    assert result['liked'] is False and result['like_count'] == 10
    assert 'test-account-secret' not in json.dumps(result)


def test_failed_toggle_is_not_retried_or_claimed_as_success(likes, monkeypatch):
    original = website._rpc
    toggles = []
    def rpc(name, *args):
        if name == 'api_toggle_like':
            toggles.append(name)
            raise ValueError('Connection interrupted')
        return original(name, *args)
    for _mod in (website, website_posts):
        monkeypatch.setattr(_mod, '_rpc', rpc)
    call = tools.prepare('set_website_mod_like', {'post_id': 123, 'liked': True})
    result = tools.execute(call, account_token='test-account-secret')
    assert 'error' in result and len(toggles) == 1


@pytest.mark.parametrize('signed_in', [False, True])
def test_agent_account_token_is_private_and_cleared(likes, vault, monkeypatch, signed_in):
    rounds = []
    def provider(messages, schemas, key, cancelled):
        assert 'test-account-secret' not in json.dumps(messages)
        assert ('set_website_mod_like' in [s['function']['name'] for s in schemas]) == signed_in
        rounds.append(1)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'like', 'function': {'name': 'set_website_mod_like',
                'arguments': json.dumps({'post_id': 123, 'liked': True})}}]} if len(rounds) == 1 else
            {'role': 'assistant', 'content': 'Done.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Like Kermit', {}, request_key='test-key',
                       account_token='test-account-secret' if signed_in else None)
    list(live_runs.stream(run))
    assert run.account_token is None
    saved = store.get(run.chat_id)
    assert 'test-account-secret' not in json.dumps(saved)
    result = saved['messages'][-1]['tools'][0]['result']
    assert (result.get('liked') is True) == signed_in


def test_like_routes_require_account_and_reject_extra_fields(likes, vault):
    from flask import Flask
    from randall.routes.assistant_bp import assistant_bp
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    body = {'post_id': 123, 'account_token': 'test-account-secret'}
    assert client.post('/api/assistant/website/like-status', json=body).get_json()['liked'] is False
    for change in ({'liked': True, 'url': 'https://other.test'}, {'liked': 'yes'}, {'liked': True, 'account_token': None}):
        assert client.post('/api/assistant/website/like', json={**body, **change}).status_code == 400
    assert client.post('/api/assistant/website/like', json={**body, 'liked': True}).get_json()['liked'] is True
