import copy
import json
import threading
import pytest
from randall.assistant import approvals, engine, live_runs, main_model, tools
from randall.website import website, website_bulk, website_posts
from tests.backend import website_site
from tests.backend.website_site import media
from tests.backend.test_assistant_website import catalog
from flask import Flask
from randall.routes.assistant_bp import assistant_bp


@pytest.fixture
def batch(catalog, monkeypatch):
    post, _ = catalog
    original = copy.deepcopy(post)
    def api(path, params=None):
        result = website_site.published(original)
        result['id'] = int(path.rsplit('/', 1)[-1])
        result['title'] = f"Mod {result['id']}"
        result['download_url'] = website_site.counted(result['id'])
        for file in result['files']:
            file['download_url'] = website_site.counted(result['id'], file['id'])
        return {'data': result}
    monkeypatch.setattr(website_posts, '_api', api)
    return {'items': [{'post_id': 123}, {'post_id': 124}]}


def test_batch_has_one_approval_with_default_fix(batch, monkeypatch):
    call = tools.prepare('download_website_mods', batch)
    review = json.loads(call.preview)
    assert review['default_choice'] == 'fix' and review['bulk_download']
    assert len(review['website_mods']) == 2
    assert 'approval' in tools.execute(call)['error']
    assert tools.execute(call, approvals.Grant(call.fingerprint))['error']


@pytest.mark.parametrize('decision', ['approve', 'deny'])
def test_direct_batch_api_one_keyless_approval(vault, batch, monkeypatch, decision):
    monkeypatch.setattr(engine, '_provider', lambda *args: pytest.fail('Direct download called provider'))
    imported = []
    def download(args, plan, **kwargs):
        imported.append(args['post_id'])
        return {'imported_count': 1, 'vault_changed': True}
    monkeypatch.setattr(website, 'apply_download', download)
    app = Flask(__name__); app.register_blueprint(assistant_bp)
    client = app.test_client()
    response = client.post('/api/assistant/website/download', json=batch)
    assert response.status_code == 200, response.get_json()
    run = live_runs._runs[response.get_json()['run_id']]
    try:
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested':
                approval = event['tool']['approval']; break
        assert not imported and approval['default_choice'] == 'fix'
        endpoint = f"/api/assistant/chats/{run.chat_id}/approvals/{approval['id']}"
        assert client.get(endpoint + '/files?choice=all').status_code == 200
        body = {'decision': decision, **({'choice': 'fix'} if decision == 'approve' else {})}
        assert client.post(endpoint, json=body).status_code == 200
        events = list(live_runs.stream(run))
        assert not any('approval_requested' in e for e in events)
        assert imported == ([123, 124] if decision == 'approve' else [])
    finally:
        if run.id in live_runs._runs:
            live_runs.cancel(run.id); list(live_runs.stream(run))


@pytest.mark.parametrize('choice', ['fix', 'import_as_is'])
def test_batch_executes_each_approved_item_with_same_safety_choice(batch, monkeypatch, choice):
    seen, progress = [], []
    def download(args, plan, safety_review, cancelled):
        decision = safety_review({'unsafe_costumes': [{}]}, plan['mod'])
        seen.append((args['post_id'], decision['action']))
        return {'imported_count': 1, 'fixed_count': int(choice == 'fix'), 'vault_changed': True}
    monkeypatch.setattr(website, 'apply_download', download)
    call = tools.prepare('download_website_mods', batch)
    grant = approvals.Grant(call.fingerprint, choice)
    result = tools.execute(call, grant, progress=progress.append)
    assert seen == [(123, choice), (124, choice)]
    assert result['imported_count'] == 2 and result['completed_count'] == 2
    assert result['fixed_count'] == (2 if choice == 'fix' else 0)
    assert progress[0]['downloads'][1]['status'] == 'queued'
    assert progress[1]['imported_count'] == 1
    assert 'approval' in tools.execute(call, grant)['error']
    assert len(seen) == 2


def test_failures_and_cancellation_preserve_completed_downloads(batch, monkeypatch):
    stopped = threading.Event()
    def download(args, plan, **kwargs):
        stopped.set()
        return {'imported_count': 1, 'vault_changed': True}
    monkeypatch.setattr(website, 'apply_download', download)
    call = tools.prepare('download_website_mods', batch)
    result = tools.execute(call, approvals.Grant(call.fingerprint, 'fix'), cancelled=stopped.is_set)
    assert result['imported_count'] == 1 and result['cancelled']
    assert result['downloads'][1]['status'] == 'cancelled'
    def fail_first(args, plan, **kwargs):
        if args['post_id'] == 123:
            raise ValueError('This mod changed while approval was pending.')
        return {'imported_count': 1, 'vault_changed': True}
    monkeypatch.setattr(website, 'apply_download', fail_first)
    result = tools.execute(call, approvals.Grant(call.fingerprint, 'fix'))
    assert result['imported_count'] == 1 and result['completed_count'] == 2
    assert result['error'] and result['downloads'][0]['status'] == 'error'
    assert result['downloads'][1]['status'] == 'done'


@pytest.mark.parametrize('items', [[], [{}], [{'post_id': True}], [{'post_id': 1}]*2,
    [{'post_id': i} for i in range(1, 26)], [{'post_id': 1, 'url': 'bad'}],
    [{'post_id': 1, 'variants': 'bad'}], [{'post_id': 1, 'file_id': 2, 'variants': 'all'}]])
def test_bulk_input_is_bounded_and_exact(items):
    with pytest.raises(ValueError):
        website_bulk.validate_items(items)


def test_default_variant_is_bound_in_batch(catalog, monkeypatch):
    post, _ = catalog
    post['files'] = [{'id': i, 'filename': f'PlMs{color}.dat', 'character': 'Marth', 'file_type': 'character_dat'}
                     for i, color in [(1, 'Nr'), (2, 'Bu')]]
    plan, review = website_bulk.prepare_batch({'items': [{'post_id': 123}]})
    assert plan['plans'][0]['file_id'] == 1
    assert review['website_mods'][0]['selected_file']['name'] == 'PlMsNr.dat'
    plan, _ = website_bulk.prepare_batch({'items': [{'post_id': 123, 'variants': 'all'}]})
    assert plan['plans'][0]['file_id'] is None


def test_stream_limit_counts_reply_not_repeated_transport_metadata(monkeypatch):
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_lines(self, chunk_size=1):
            for i in range(1200):
                data = {'id': 'x'*500, 'choices': [{'delta': {'content': 'a'}, 'finish_reason': None}]}
                yield ('data: ' + json.dumps(data)).encode()
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
            yield b'data: [DONE]'
    monkeypatch.setattr(main_model.requests, 'post', lambda *a, **kw: Response())
    events = list(engine._provider([], [], 'test', threading.Event()))
    assert events[-1]['message']['content'] == 'a'*1200


def test_stream_still_rejects_oversized_tool_arguments(monkeypatch):
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_lines(self, chunk_size=1):
            yield ('data: ' + json.dumps({'choices': [{'delta': {'tool_calls': [{'index': 0,
                'function': {'name': 'search_vault', 'arguments': 'x'*500_001}}]}}]})).encode()
    monkeypatch.setattr(main_model.requests, 'post', lambda *a, **kw: Response())
    with pytest.raises(RuntimeError, match='reply got too long'):
        list(engine._provider([], [], 'test', threading.Event()))
