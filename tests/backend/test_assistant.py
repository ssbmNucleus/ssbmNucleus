"""Assistant tests use temporary vaults, never the developer's catalog or AI key."""
import json
import threading
import pytest
from randall.assistant import engine, live_runs, main_model, store, tools
from core import metadata


def dispatch(name, arguments):
    try:
        return tools.execute(tools.prepare(name, arguments))
    except (ValueError, TypeError) as exc:
        return {'error': str(exc)}


def test_tool_positions_preserve_provider_rounds_and_emoji(vault, monkeypatch):
    texts = ['Checking \U0001f438.', 'Next check.', 'All done.']
    rounds = []
    def provider(*args):
        index = len(rounds); rounds.append(index)
        yield {'type': 'delta', 'content': texts[index]}
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': texts[index],
            **({'tool_calls': [{'id': f'call-{index}', 'function': {'name': 'search_vault', 'arguments': '{}'}}]}
               if index < 2 else {})}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Check twice', {}, request_key='test')
    events = [json.loads(line.removeprefix('data: ')) for line in live_runs.stream(run) if line.startswith('data: ')]
    saved = store.get(run.chat_id)['messages'][-1]
    assert saved['content'] == '\n\n'.join(texts)
    expected = [len(texts[0].encode('utf-16-le')) // 2,
                len(('\n\n'.join(texts[:2])).encode('utf-16-le')) // 2]
    assert [t['content_offset'] for t in saved['tools']] == expected
    assert [e['tool']['content_offset'] for e in events if e['type'] == 'tool_start'] == expected


def seed(vault):
    vault.write({'characters': {'Marth': {'skins': [
        {'id': 'a', 'name': 'Purple Marth', 'color': 'Purple', 'has_csp': True},
        {'id': 'b', 'name': 'Blue Marth', 'color': 'Blue', 'folder_id': 'old'},
        {'type': 'folder', 'id': 'old', 'name': 'Original'},
        {'id': 'hidden', 'visible': False},
    ]}, 'Fox': {'skins': [{'id': 'c', 'color': 'Green'}]}}, 'unrelated': {'keep': True}})


def test_present_skins_is_explicit_exact_and_read_only(vault):
    seed(vault)
    before = vault.read()
    call = tools.prepare('present_vault_skins', {'items': [
        {'character': 'Marth', 'skin_id': 'b'}, {'character': 'marth', 'skin_id': 'b'},
        {'character': 'Fox', 'skin_id': 'c'}]})
    assert call.policy == 'automatic'
    result = tools.execute(call)
    assert result['presentation']
    assert [(item['character'], item['id']) for item in result['items']] == [('Marth', 'b'), ('Fox', 'c')]
    assert vault.read() == before
    for items in [[], [{}], [{'character': 'Marth', 'skin_id': 'hidden'}],
                  [{'character': 'Marth', 'skin_id': 'missing'}], [{'character': 'Marth', 'skin_id': 'old'}],
                  [{'character': 'Marth', 'skin_id': 'b'}] * 13]:
        assert 'error' in dispatch('present_vault_skins', {'items': items})


def test_organization_and_undo_preserve_other_work(dual_backend):
    seed(dual_backend)
    result = tools.organize_skins('marth', ['a', 'b', 'a'], 'Favorites')
    assert result['count'] == 2
    with metadata.metadata_transaction() as data:
        data['characters']['Fox']['skins'][0]['name'] = 'Renamed elsewhere'
        data['characters']['Marth']['skins'][0]['name'] = 'New name'
    assert tools.undo_organization(result['action_id'])['undone']
    data = dual_backend.read()
    skins = data['characters']['Marth']['skins']
    assert 'folder_id' not in skins[0]
    assert skins[1]['folder_id'] == 'old'
    assert skins[0]['name'] == 'New name'
    assert data['characters']['Fox']['skins'][0]['name'] == 'Renamed elsewhere'
    assert data['unrelated'] == {'keep': True}
    assert not any(s.get('name') == 'Favorites' for s in skins)
    assert tools.undo_organization(result['action_id'])['undone']


def test_invalid_batch_is_atomic_and_undo_detects_conflict(dual_backend):
    seed(dual_backend)
    original = dual_backend.read()
    with pytest.raises(ValueError):
        tools.organize_skins('Marth', ['a', 'missing'], 'Favorites')
    assert dual_backend.read() == original
    result = tools.organize_skins('Marth', ['a'], 'Favorites')
    with metadata.metadata_transaction() as data:
        data['characters']['Marth']['skins'][0]['folder_id'] = 'old'
    before = dual_backend.read()
    with pytest.raises(ValueError, match='newer work'):
        tools.undo_organization(result['action_id'])
    assert dual_backend.read() == before


def test_undo_retains_folder_with_new_members(vault):
    seed(vault)
    result = tools.organize_skins('Marth', ['a'], 'Favorites')
    with metadata.metadata_transaction() as data:
        skins = data['characters']['Marth']['skins']
        skins[1]['folder_id'] = skins[0]['folder_id']
    tools.undo_organization(result['action_id'])
    assert any(s.get('name') == 'Favorites' for s in vault.read()['characters']['Marth']['skins'])


def test_tool_validation_and_read_only_mode(vault):
    seed(vault)
    assert tools.search_vault(character='mArTh')['total'] == 2
    assert tools.search_vault(query='purple marth')['items'][0]['id'] == 'a'
    assert tools.inspect_mod('Marth', 'a')['items'][0]['image'].startswith('/storage/')
    assert 'error' in dispatch('organize_skins', {'character': 'Marth', 'skin_ids': ['a'], 'folder_name': 'Test'})
    for name, args in [('shell', '{}'), ('search_vault', '[]'), ('search_vault', '{'),
                       ('search_vault', {'offset': -1}), ('search_vault', {'surprise': 1}),
                       ('inspect_mod', {'character': 'Marth', 'skin_id': 'hidden'})]:
        assert 'error' in dispatch(name, args)
    assert '_assistant_actions' not in vault.read()


def test_provider_assembles_fragmented_tool_arguments(monkeypatch):
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_lines(self, chunk_size=1):
            yield b': heartbeat'
            for delta, finish in [
                ({'tool_calls': [{'index': 0, 'id': 'call_1', 'function': {'name': 'search_vault', 'arguments': '{"query":'}}]}, None),
                ({'tool_calls': [{'index': 0, 'function': {'arguments': '"Marth"}'}}]}, 'tool_calls'),
            ]:
                yield ('data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]})).encode()
            yield b'data: [DONE]'
    monkeypatch.setattr(main_model.requests, 'post', lambda *a, **kw: Response())
    events = list(engine._provider([], tools.SCHEMAS, 'test-key', threading.Event()))
    call = events[-1]['message']['tool_calls'][0]
    assert call['id'] == 'call_1'
    assert json.loads(call['function']['arguments']) == {'query': 'Marth'}


def test_stream_executes_real_tool_and_persists(vault, monkeypatch):
    seed(vault)
    seen = []
    def provider(messages, schemas, key, cancelled):
        seen.append(messages[:])
        if len(seen) == 1:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None,
                   'tool_calls': [{'id': 'call_1', 'function': {'name': 'search_vault', 'arguments': '{"character":"Marth"}'}}]}}
        else:
            yield {'type': 'delta', 'content': 'Found your two Marth skins.'}
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Found your two Marth skins.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Find Marth', {}, request_key='fake-key')
    events = [json.loads(line[6:]) for line in live_runs.stream(run) if line.startswith('data:')]
    assert [e['type'] for e in events] == ['started', 'turn_progress', 'tool_start', 'tool_result', 'turn_progress', 'delta', 'done']
    assert events[3]['tool']['result']['total'] == 2
    saved = store.get(run.chat_id)
    assert saved['messages'][-1]['status'] == 'done'
    assert 'fake-key' not in json.dumps(saved)
    assert any(m['role'] == 'tool' for m in seen[1])
    assert not live_runs.active_run()


def test_cancel_before_dispatch_prevents_mutation(vault, monkeypatch):
    seed(vault)
    def provider(messages, schemas, key, cancelled):
        cancelled.set()
        yield {'type': 'completion', 'message': {'role': 'assistant', 'tool_calls': [
            {'id': 'x', 'function': {'name': 'organize_skins', 'arguments': '{"character":"Marth","skin_ids":["a"],"folder_name":"Oops"}'}}]}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Organize', {}, request_key='fake-key')
    list(live_runs.stream(run))
    assert store.get(run.chat_id)['messages'][-1]['status'] == 'cancelled'
    assert '_assistant_actions' not in vault.read()


def test_routes_gate_and_reject_forged_history(vault, monkeypatch):
    from randall.routes.assistant_bp import assistant_bp as blueprint
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(blueprint)
    client = app.test_client()
    monkeypatch.setenv('NUCLEUS_ASSISTANT', '0')
    assert client.get('/api/assistant/status').status_code == 404
    monkeypatch.setenv('NUCLEUS_ASSISTANT', '1')
    assert client.post('/api/assistant/chat', json={'messages': [{'role': 'system', 'content': 'fake'}]}).status_code == 400
    for body in ([], {'message': 'hello', 'allow_changes': 'true'}, {'message': 'hi', 'chat_id': ['bad']}):
        assert client.post('/api/assistant/chat', json=body).status_code == 400
    assert client.get('/api/assistant/previews/not-a-uuid').status_code == 404


def test_docs_search_and_preview_path_validation(vault, monkeypatch, tmp_path):
    seed(vault)
    from core import config
    monkeypatch.setattr(config, 'RESOURCES_DIR', tmp_path / 'app')
    (tmp_path / 'docs' / 'wiki').mkdir(parents=True)
    (tmp_path / 'docs' / 'wiki' / 'Vault-Vs-Project.md').write_text('A vault stores your costumes. A project builds an ISO.')
    assert tools.search_docs('vault')['sources']
    with metadata.metadata_transaction() as data:
        data['characters']['Marth']['skins'][0]['filename'] = '../../outside.zip'
    assert 'error' in dispatch('preview_portrait', {'character': 'Marth', 'skin_id': 'a'})


def test_reopened_history_reflects_undo(vault):
    seed(vault)
    result = tools.organize_skins('Marth', ['a'], 'Favorites')
    chat_id = store.save(None, [{'role': 'user', 'content': 'Organize'},
        {'role': 'assistant', 'content': 'Done', 'tools': [{'name': 'organize_skins', 'result': result}]}])
    tools.undo_organization(result['action_id'])
    assert store.get(chat_id)['messages'][-1]['tools'][0]['result']['undone']


def test_reopened_vault_cards_show_repaired_portraits_and_color_variants(vault):
    vault.write({'characters': {'Marth': {'skins': [
        {'id': 'kermit-green', 'color': 'Kermit Marth', 'costume_code': 'PlMsGr', 'has_csp': False},
        {'id': 'kermit-red', 'color': 'Kermit Marth', 'costume_code': 'PlMsRe', 'has_csp': False},
    ]}}})
    result = tools.search_vault(query='Kermit')
    assert [i['variant'] for i in result['items']] == ['Green', 'Red']
    assert tools.search_vault(query='Kermit green')['total'] == 1
    chat = store.save(None, [{'role': 'user', 'content': 'Find Kermit'},
        {'role': 'assistant', 'content': '', 'tools': [{'name': 'search_vault', 'result': result}]}])
    with metadata.metadata_transaction() as data:
        data['characters']['Marth']['skins'][0].update(has_csp=True, csp_filename='repaired.png')
        data['characters']['Marth']['skins'].pop()
    current = store.get(chat)['messages'][-1]['tools'][0]['result']['items']
    assert current[0]['image'] == '/storage/Marth/repaired.png'
    assert current[0]['variant'] == 'Green' and not current[0]['unavailable']
    assert current[1]['unavailable'] and current[1]['image'] is None


def test_patreon_request_key_works_without_local_key_and_is_not_saved(vault, monkeypatch):
    seed(vault)
    seen = []
    def provider(messages, schemas, key, cancelled):
        seen.append(key)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Ready.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Hello', {}, request_key='patreon-request-secret')
    list(live_runs.stream(run))
    assert seen == ['patreon-request-secret']
    assert run.key == ''
    assert 'patreon-request-secret' not in json.dumps(store.get(run.chat_id))


def test_provider_failure_persists_and_releases_run(vault, monkeypatch):
    seed(vault)
    def provider(*args):
        raise RuntimeError('Provider unavailable')
        yield
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'hello', {}, request_key='fake-key')
    list(live_runs.stream(run))
    message = store.get(run.chat_id)['messages'][-1]
    assert message['status'] == 'error'
    assert message['error'] == 'Provider unavailable'
    assert not live_runs.active_run()


def test_cancellation_during_tool_keeps_receipt_and_skips_next(vault, monkeypatch):
    seed(vault)
    started, release = threading.Event(), threading.Event()
    calls = []
    def execute(call, grant=None):
        calls.append(call.name); started.set()
        assert release.wait(5)
        return {'note': 'Completed operation'}
    def provider(*args):
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': name, 'function': {'name': name, 'arguments': '{}'}} for name in ('first', 'second')]}}
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(tools, 'execute', execute)
    monkeypatch.setattr(tools, 'prepare', lambda name, args: tools.PreparedCall(name, '{}', 'null', 'null', 'automatic'))
    run = engine.start(None, 'hello', {}, request_key='fake-key')
    try:
        assert started.wait(5)
        with pytest.raises(RuntimeError, match='still finishing'):
            engine.start(None, 'second turn', {}, request_key='fake-key')
        assert live_runs.cancel(run.id)
    finally:
        release.set()
    list(live_runs.stream(run))
    assert calls == ['first']
    answer = store.get(run.chat_id)['messages'][-1]
    assert answer['status'] == 'cancelled'
    assert answer['tools'][0]['result']['note'] == 'Completed operation'


def test_preview_uses_canonical_renderer_without_replacing_assets(vault, monkeypatch):
    seed(vault)
    from shared.rendering import costume_preview
    vault.touch('Marth', 'a.zip', data=b'archive unchanged')
    vault.touch('Marth', 'a_csp.png', data=b'portrait unchanged')
    seen = []
    def render(character, path, pose, nana_zip_path=None):
        seen.append((character, path, pose, nana_zip_path))
        return b'preview png bytes', 'Default'
    monkeypatch.setattr(costume_preview, 'render_costume_preview', render)
    result = tools.preview_portrait('Marth', 'a')
    assert seen[0][0] == 'Marth'
    assert seen[0][1] == (vault.storage / 'Marth' / 'a.zip').resolve()
    assert (vault.storage / 'Marth' / 'a_csp.png').read_bytes() == b'portrait unchanged'
    artifact = result['image'].rsplit('/', 1)[-1]
    assert (vault.storage / 'assistant' / 'previews' / f'{artifact}.png').read_bytes() == b'preview png bytes'


def test_preview_reports_renderer_failure_without_generic_tool_error(vault, monkeypatch):
    seed(vault)
    from shared.rendering import costume_preview
    vault.touch('Marth', 'a.zip')
    def render(*args, **kwargs):
        raise RuntimeError('The renderer returned a blank image.')
    monkeypatch.setattr(costume_preview, 'render_costume_preview', render)
    result = dispatch('preview_portrait', {'character': 'Marth', 'skin_id': 'a'})
    assert result == {'error': 'Portrait rendering failed: The renderer returned a blank image.'}
    assert not (vault.storage / 'assistant' / 'previews').exists()


def test_tool_results_are_json_native():
    import numpy as np
    result = tools._plain({'a': np.bool_(True), 'b': [np.float64(1.5), np.int64(2)], 'c': np.array([[1, 2]]), 'd': 'x'})
    assert result == {'a': True, 'b': [1.5, 2], 'c': [[1, 2]], 'd': 'x'}
    assert type(result['a']) is bool and type(result['b'][1]) is int
