"""The app's MCP server: POST /api/mcp (shared/routes/mcp.py) and randall/mcp (docs/dev/APP_MCP.md).

The route runs behind the REAL backend-token check, lifted out of app.py the way test_patch_download_auth does,
so a request without the token is refused exactly as the app refuses it. Tools run on the test vault.
"""
import ast
import base64
import hmac
import io
import json
import sys
import time
from pathlib import Path

import jsonschema
import pytest
from flask import Flask, jsonify, request

from tests.paths import BACKEND, REPO

from core import config, jobs
from randall.assistant import tools
from randall.mcp import calls, credits, model_jobs, randall_tools, server, toolkit, window
from shared.routes import mcp as route

TOKEN = 'synthetic-mcp-token'


def _answer(path):
    """The answer in rigswap's relay file, as a fake rigswap reads it. On Windows the file can still be held
    for a moment just after the app renames it into place (a virus scan of the new file): the open is then
    refused and is tried again, as the real rigswap asks again for an answer it could not read."""
    for _ in range(50):
        try:
            return json.loads(path.read_text(encoding='utf-8'))['answer']
        except PermissionError:
            time.sleep(0.02)
    return json.loads(path.read_text(encoding='utf-8'))['answer']


def _png():
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGBA', (4, 4), (200, 40, 40, 255)).save(out, format='PNG')
    return out.getvalue()


PNG = _png()


def guarded_app():
    app = Flask('app-mcp-test')
    scope = dict(app=app, hmac=hmac, request=request, jsonify=jsonify, _backend_token=TOKEN,
                 _PUBLIC_MEDIA_PREFIXES=())
    tree = ast.parse((BACKEND / 'app.py').read_text(encoding='utf-8'))
    names = {'_valid_backend_token', 'require_backend_token'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BACKEND / 'app.py'), 'exec'), scope)
    app.register_blueprint(route.mcp_bp)
    return app


# The window's own key (core/ui_channel.py): what the app's window sends with what only it may do, and the
# MCP client (holding the backend token only) does not have.
UI_KEY = 'window-only-key'
WINDOW = {'X-Nucleus-Token': TOKEN, 'X-Nucleus-UI-Key': UI_KEY}


@pytest.fixture
def client(vault, tmp_path, monkeypatch):
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(config, 'LOGS_PATH', tmp_path / 'logs')
    monkeypatch.delenv('NUCLEUS_ASSISTANT', raising=False)
    # Nobody signed in and no machine key, whatever this computer has: each test says whose usage it spends.
    credits.clear()
    monkeypatch.setattr(credits, '_machine_key', lambda: None)
    monkeypatch.setattr(credits, '_entitlement', _no_network)
    app = guarded_app()
    assert not app.testing          # the real token check, not the testing bypass
    yield app.test_client()
    toolkit.stop()
    credits.clear()
    window.clear()


def _no_network(token):
    raise AssertionError('ai-entitlement must not be asked here')


def rpc(client, method, params=None, request_id=1, token=TOKEN):
    body = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
    if params is not None:
        body['params'] = params
    return client.post('/api/mcp', json=body, headers={'X-Nucleus-Token': token} if token else {})


def call(client, name, arguments=None):
    response = rpc(client, 'tools/call', {'name': name, 'arguments': arguments or {}})
    assert response.status_code == 200
    answer = response.get_json()
    assert 'error' not in answer, answer
    return answer['result']


def payload(result):
    return json.loads(result['content'][0]['text'])


def seed(vault):
    vault.write({'characters': {'Marth': {'skins': [
        {'id': 'a', 'name': 'Purple Marth', 'color': 'Purple', 'has_csp': True},
        {'id': 'b', 'name': 'Blue Marth', 'color': 'Blue', 'folder_id': 'old'},
        {'type': 'folder', 'id': 'old', 'name': 'Original'},
    ]}, 'Fox': {'skins': [{'id': 'c', 'name': 'Green Fox', 'color': 'Green'}]}}})


# ------------------------------------------------------------------ transport

def test_requests_without_the_backend_token_are_refused(client):
    assert rpc(client, 'ping', token=None).status_code == 401
    assert rpc(client, 'ping', token='wrong').status_code == 401
    assert rpc(client, 'ping').get_json() == {'jsonrpc': '2.0', 'id': 1, 'result': {}}


def test_initialize_echoes_a_known_protocol_and_names_the_server(client):
    for asked, answered in (('2025-06-18', '2025-06-18'), ('2025-03-26', '2025-03-26'),
                            ('2099-01-01', '2025-06-18'), (None, '2025-06-18')):
        result = rpc(client, 'initialize', {'protocolVersion': asked, 'capabilities': {},
                                            'clientInfo': {'name': 't', 'version': '1'}}).get_json()['result']
        assert result['protocolVersion'] == answered
        assert result['serverInfo']['name'] == 'ssbm-nucleus'
        assert 'tools' in result['capabilities']


def test_notifications_and_client_responses_get_202_and_no_body(client):
    headers = {'X-Nucleus-Token': TOKEN}
    for body in ({'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                 {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 3}},
                 {'jsonrpc': '2.0', 'id': 9, 'result': {}}):
        response = client.post('/api/mcp', json=body, headers=headers)
        assert response.status_code == 202 and response.data == b''


def test_bad_messages_are_json_rpc_errors_never_http_errors(client):
    headers = {'X-Nucleus-Token': TOKEN}
    assert client.post('/api/mcp', data='{nope', headers=dict(headers, **{'Content-Type': 'application/json'})
                       ).get_json()['error']['code'] == -32700
    assert client.post('/api/mcp', json=[{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}],
                       headers=headers).get_json()['error']['code'] == -32600
    assert rpc(client, 'resources/list').get_json()['error']['code'] == -32601
    assert client.get('/api/mcp', headers=headers).status_code == 405


def test_a_build_without_the_assistant_says_so(client, monkeypatch):
    monkeypatch.setenv('NUCLEUS_ASSISTANT', '0')
    for method in ('initialize', 'tools/list', 'tools/call'):
        answer = rpc(client, method, {}).get_json()
        assert answer['id'] == 1 and answer['error']['code'] == route.ASSISTANT_OFF
        assert 'assistant switched off' in answer['error']['message']
    response = client.post('/api/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                           headers={'X-Nucleus-Token': TOKEN})
    assert response.status_code == 202


def test_app_registers_the_route_for_every_build():
    source = (BACKEND / 'app.py').read_text(encoding='utf-8')
    assert 'from shared.routes.mcp import mcp_bp' in source
    assert '\napp.register_blueprint(mcp_bp)\n' in source       # not inside the assistant's gated block


# ------------------------------------------------------------------ tools/list

def test_tools_list_offers_randalls_tools_the_import_and_the_toolkit(client):
    listed = rpc(client, 'tools/list').get_json()['result']['tools']
    by_name = {tool['name']: tool for tool in listed}
    assert len(by_name) == len(listed)
    advertised = {s['function']['name'] for s in tools.SCHEMAS} & set(tools.REGISTRY)
    assert advertised - randall_tools.HIDDEN <= set(by_name)
    assert 'set_website_mod_like' not in by_name        # needs the window's account sign-in
    assert {'search_vault', 'import_model', 'fix_import', 'job_status', 'answer_import', 'undo_organization',
            'attach_file',
            'native_port', 'stage_workbench', 'connect_creation_toolkit', 'creation_toolkit_status'} <= set(by_name)
    for tool in listed:
        schema = tool['inputSchema']
        assert schema['type'] == 'object' and isinstance(schema.get('properties'), dict), tool['name']
        jsonschema.Draft202012Validator.check_schema(schema)
        assert tool['description'].strip()
    assert by_name['import_model']['inputSchema']['required'] == ['source']
    assert by_name['search_vault']['annotations']['readOnlyHint'] is True
    for name in ('deliver_to_game', 'undo_delivery', 'organize_skins', 'install_project_mods'):
        assert by_name[name]['annotations']['destructiveHint'] is True, name
    assert '[MCP]' in by_name['deliver_to_game']['description']        # approval tools say how approval maps
    for name in toolkit.FORWARDED:
        assert by_name[name]['description'].startswith(toolkit.NEEDS)
    # The game runs the Dolphin set in Settings; no AI names a program to start (security review 11-19, M1).
    assert 'slippi_dolphin_path' not in by_name['test_in_game']['inputSchema']['properties']


# ------------------------------------------------------------------ tools/call

def test_search_vault_runs_on_the_vault(client, vault):
    seed(vault)
    result = call(client, 'search_vault', {'query': 'marth'})
    assert result['isError'] is False
    found = payload(result)
    assert found['total'] == 2
    assert {item['id'] for item in found['items']} == {'a', 'b'}


def test_search_vault_stages_lists_stage_skins_and_every_stage_code(client, vault):
    vault.write({'characters': {}, 'stages': {
        'final_destination': {'variants': [
            {'id': 'purple-fd-1', 'name': 'Purple FD', 'filename': 'purple-fd-1.zip', 'slippi_tested': False},
            {'id': 'hidden', 'name': 'Hidden FD', 'visible': False},
            {'type': 'folder', 'id': 'f1', 'name': 'Old'}]},
        'peachs_castle': {'variants': [{'id': 'pink', 'name': 'Pink Castle'}]}}})
    found = payload(call(client, 'search_vault_stages'))
    by_code = {row['stage_code']: row for row in found['stages']}
    assert set(by_code) == {'GrNBa', 'GrNLa', 'GrSt', 'GrOp', 'GrPs', 'GrIz', 'GrCs'}   # legal six + any with a skin
    assert [v['variant_id'] for v in by_code['GrNLa']['variants']] == ['purple-fd-1']
    assert by_code['GrNLa']['stage'] == 'Final Destination' and found['total_variants'] == 2
    assert found['all_stage_codes']['Final Destination'] == 'GrNLa' and len(found['all_stage_codes']) == 29
    purple = payload(call(client, 'search_vault_stages', {'query': 'purple'}))
    assert [row['stage_code'] for row in purple['stages']] == ['GrNLa']
    named = payload(call(client, 'search_vault_stages', {'query': 'final destination'}))
    assert [row['stage_code'] for row in named['stages']] == ['GrNLa']
    assert call(client, 'search_vault_stages', {'stage': 'x'})['isError'] is True


def test_stage_lab_open_says_the_stage_codes_over_mcp(client):
    listed = {t['name']: t for t in rpc(client, 'tools/list').get_json()['result']['tools']}
    assert 'Final Destination GrNLa' in listed['stage_lab_open']['description']
    assert 'search_vault_stages' in listed['stage_lab_open']['description']
    assert listed['search_vault_stages']['annotations']['readOnlyHint'] is True


def test_unknown_tools_and_bad_arguments_are_is_error(client, vault):
    seed(vault)
    result = call(client, 'make_coffee')
    assert result['isError'] is True and 'Unknown tool' in result['content'][0]['text']
    result = call(client, 'search_vault', {'offset': -1})
    assert result['isError'] is True and 'offset' in result['content'][0]['text']
    result = call(client, 'search_vault', {'nonsense': 1})
    assert result['isError'] is True and 'not a parameter' in result['content'][0]['text']


def test_present_vault_skins_returns_the_portraits_as_images(client, vault):
    seed(vault)
    (vault.storage / 'Marth').mkdir(parents=True, exist_ok=True)
    (vault.storage / 'Marth' / 'a_csp.png').write_bytes(PNG)
    result = call(client, 'present_vault_skins', {'items': [{'character': 'Marth', 'skin_id': 'a'}]})
    images = [part for part in result['content'] if part['type'] == 'image']
    assert len(images) == 1 and images[0]['mimeType'] == 'image/png'
    assert base64.b64decode(images[0]['data']) == PNG


def test_an_approval_tool_runs_prepare_and_apply_in_one_call_and_can_be_undone(client, vault):
    seed(vault)
    result = call(client, 'organize_skins', {'character': 'Marth', 'skin_ids': ['a'], 'folder_name': 'Picks'})
    done = payload(result)
    assert result['isError'] is False and done['count'] == 1
    assert done['approved']['title'] == 'Move 1 skin into Picks'
    skins = vault.read()['characters']['Marth']['skins']
    folder = next(s for s in skins if s.get('type') == 'folder' and s['name'] == 'Picks')
    assert next(s for s in skins if s['id'] == 'a')['folder_id'] == folder['id']
    undone = payload(call(client, 'undo_organization', {'action_id': done['action_id']}))
    assert undone['undone'] is True
    assert 'folder_id' not in next(s for s in vault.read()['characters']['Marth']['skins'] if s['id'] == 'a')


def test_an_offered_choice_must_be_one_the_preview_offers(client, vault, monkeypatch):
    seed(vault)
    result = call(client, 'organize_skins', {'character': 'Marth', 'skin_ids': ['a'], 'folder_name': 'X',
                                             'choice': 'all'})
    assert result['isError'] is True        # organize offers no options, and choice is not one of its arguments


def test_attach_file_makes_a_working_copy(client, vault, tmp_path):
    picture = tmp_path / 'texture.png'
    picture.write_bytes(PNG)
    attached = payload(call(client, 'attach_file', {'path': str(picture)}))['file']
    assert attached['extension'] == '.png' and len(attached['file_id']) == 32
    assert call(client, 'attach_file', {'path': 'texture.png'})['isError'] is True


def test_a_slow_call_answers_with_a_job_and_job_status_returns_its_result(client, vault, monkeypatch):
    seed(vault)
    monkeypatch.setattr(calls, 'INLINE_SECONDS', 0.05)
    real = randall_tools.call

    def slow(name, arguments, *, app):
        time.sleep(0.4)
        return real(name, arguments, app=app)
    monkeypatch.setattr(randall_tools, 'call', slow)
    started = payload(call(client, 'search_vault', {'query': 'fox'}))
    assert started['status'] == 'running' and started['job_id'].startswith(calls.PREFIX)
    for _ in range(100):
        polled = call(client, 'job_status', {'job_id': started['job_id']})
        head = payload(polled)
        if head['status'] == 'done':
            break
        time.sleep(0.05)
    assert head['status'] == 'done' and head['tool'] == 'search_vault'
    assert json.loads(polled['content'][1]['text'])['total'] == 1


def test_job_status_waits_for_a_running_job_so_a_client_needs_no_sleep(client, vault, monkeypatch):
    seed(vault)
    monkeypatch.setattr(calls, 'INLINE_SECONDS', 0.05)
    real = randall_tools.call

    def slow(name, arguments, *, app):
        time.sleep(0.6)
        return real(name, arguments, app=app)
    monkeypatch.setattr(randall_tools, 'call', slow)
    started = payload(call(client, 'search_vault', {'query': 'fox'}))
    assert started['status'] == 'running'
    assert payload(call(client, 'job_status', {'job_id': started['job_id'], 'wait_seconds': 0}))['status'] == 'running'
    assert payload(call(client, 'job_status', {'job_id': started['job_id'], 'wait_seconds': 10}))['status'] == 'done'
    for bad in (-1, 51, 2.5, '5', True):
        assert call(client, 'job_status', {'job_id': started['job_id'], 'wait_seconds': bad})['isError'] is True


def test_the_import_results_next_is_said_for_mcp_not_the_chat():
    from randall.model_import.chat import import_job
    done = import_job.DONE_NEXT.format(fighter='Marth', picked='', project='neos-1', warned='')
    changed = import_job.CHANGED_NEXT.format(changed='left out: Barreljet', why='', project='neos-1', warned='')
    for text in (done, changed):
        said = model_jobs.mcp_next(text)
        assert 'card above your reply' not in said and 'import_model with project' not in said
        assert 'call fix_import with project "neos-1" and change' in said


# ------------------------------------------------------------------ model import

def test_import_model_refuses_what_it_cannot_start(client, vault, tmp_path):
    assert call(client, 'import_model', {'source': 'model.glb'})['isError'] is True
    assert call(client, 'import_model', {'source': str(tmp_path / 'missing.glb')})['isError'] is True
    model = tmp_path / 'model.glb'
    model.write_bytes(b'glTF')
    result = call(client, 'import_model', {'source': str(model), 'fighter': 'Goku'})
    assert result['isError'] is True
    assert call(client, 'fix_import', {'project': 'nope', 'change': 'legs'})['isError'] is True
    assert call(client, 'job_status', {'job_id': 'no-such-job'})['isError'] is True
    smd = tmp_path / 'model.smd'                # the one model kind the importer cannot read
    smd.write_text('version 1\n', encoding='utf-8')
    refused = call(client, 'import_model', {'source': str(smd)})
    assert refused['isError'] is True and '.fbx' in refused['content'][0]['text']


def test_import_model_over_mcp_takes_an_fbx(client, vault, tmp_path, monkeypatch):
    """0.9.0 smoke test: FBX is a model like the others everywhere one is taken."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Scorpion.FBX'
    model.write_bytes(b'Kaydara FBX Binary  \0')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    monkeypatch.setattr(studio_import, 'run_import', lambda args, **_: {'status': 'done', 'project': 'scorpion-1'})
    started = payload(call(client, 'import_model', {'source': str(model)}))
    assert started['status'] == 'running'
    for _ in range(100):
        if payload(call(client, 'job_status', {'job_id': started['job_id'], 'wait_seconds': 0}))['status'] == 'done':
            break
        time.sleep(0.05)


def test_import_model_over_mcp_says_at_once_when_the_tools_are_not_downloaded(client, vault, tmp_path,
                                                                             monkeypatch):
    """The packaged app's model import tools (Blender, rigswap's Python) are a download the user starts in
    Settings: over MCP an import or a change says so at once, starts no job and never fetches them itself."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Scorpion.FBX'
    model.write_bytes(b'Kaydara FBX Binary  \0')
    need = {'state': 'not_installed', 'download_bytes': 779_000_000, 'needed_bytes': 779_000_000,
            'disk_bytes': 2_200_000_000}
    monkeypatch.setattr(import_job, 'tools_needed', lambda: need)

    def never(*args, **kwargs):
        raise AssertionError('nothing may start without the tools')
    monkeypatch.setattr(studio_import, 'run_import', never)
    monkeypatch.setattr(import_job, 'setup', never)
    before = [j['id'] for j in jobs.list_jobs(kind=model_jobs.KIND)]     # another test's, in this worker
    result = call(client, 'import_model', {'source': str(model)})
    assert result['isError'] is False
    said = payload(result)
    assert said['status'] == 'needs_tools' and said['tools'] == need
    assert 'Settings > AI > Model import tools' in said['next']
    assert 'Do not try to download them yourself' in said['next'] and 'card above' not in said['next']
    assert [j['id'] for j in jobs.list_jobs(kind=model_jobs.KIND)] == before, 'no job started'
    (studio_import.root() / 'neos-1').mkdir(parents=True, exist_ok=True)
    fixed = payload(call(client, 'fix_import', {'project': 'neos-1', 'change': 'the legs look wrong'}))
    assert fixed['status'] == 'needs_tools'
    assert [j['id'] for j in jobs.list_jobs(kind=model_jobs.KIND)] == before, 'no job started'


def test_import_model_over_mcp_says_at_once_which_texture_files_are_missing(client, vault, tmp_path, monkeypatch):
    """0.9.0 smoke test: a bare OBJ without its .mtl was imported all white. Over MCP the user's AI hears it before
    any job starts, and untextured true goes on without them."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Clank.obj'
    model.write_bytes(b'mtllib Clank.mtl\nv 0 0 0\n')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    started = []
    monkeypatch.setattr(studio_import, 'run_import', lambda args, **_: started.append(args) or {'status': 'done'})
    result = call(client, 'import_model', {'source': str(model)})
    answer = payload(result)
    assert result['isError'] is False and answer['status'] == 'needs_textures' and answer['textures'] == ['Clank.mtl']
    assert answer['warning'].startswith('Clank.obj came without the materials file Clank.mtl.')
    assert 'a materials file is not a texture' in answer['next']
    assert 'put those files beside the model' in answer['next'] and not started
    assert call(client, 'import_model', {'source': str(model), 'untextured': 'yes'})['isError'] is True
    job = payload(call(client, 'import_model', {'source': str(model), 'untextured': True}))
    assert job['status'] == 'running'
    for _ in range(100):
        if payload(call(client, 'job_status', {'job_id': job['job_id'], 'wait_seconds': 0}))['status'] == 'done':
            break
        time.sleep(0.05)
    assert started == [{'source': str(model.resolve()), 'untextured': True}]


def test_import_model_is_an_app_job_that_job_status_follows(client, vault, tmp_path, monkeypatch):
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    seen = {}       # nobody signed in: the import spends no Randall usage, its asks are the caller's to answer

    def run_import(args, *, key=None, progress=None, cancelled=None, source_is_attachment=False, relay=None):
        seen.update(args=args, attachment=source_is_attachment, key=key, relay_was_a_folder=relay.is_dir())
        seen['relay'] = relay
        progress({'progress': ['loading', 'swapping'], 'seconds': 1.0, 'project': 'neos-1'})
        return {'status': 'done', 'project': 'neos-1', 'fighter': 'Marth',
                'saved': {'name': 'Neos', 'character': 'Marth', 'skin_id': 'neos'}}
    monkeypatch.setattr(studio_import, 'run_import', run_import)
    started = payload(call(client, 'import_model', {'source': str(model), 'fighter': 'marth', 'name': 'Neos'}))
    assert started['status'] == 'running'
    for _ in range(100):
        status = payload(call(client, 'job_status', {'job_id': started['job_id']}))
        if status['status'] not in ('queued', 'running'):
            break
        time.sleep(0.05)
    assert status['status'] == 'done'
    assert status['result']['saved']['skin_id'] == 'neos'
    assert status['progress'] == ['loading', 'swapping']
    relay = seen.pop('relay')
    assert seen == {'args': {'source': str(model.resolve()), 'fighter': 'Marth', 'name': 'Neos'},
                    'attachment': False, 'key': None, 'relay_was_a_folder': True}
    assert not relay.exists(), 'the relay folder goes with the job'
    assert jobs.get(started['job_id'])['kind'] == model_jobs.KIND


def _rigswap_asking(asks, answered, picture):
    """A stand-in run_import that asks as rigswap/ai.py ``_relayed`` does: each ask written to the relay, an
    answer read and checked (``up`` must be '+z' or '-z'), a misfit handed back, done-<id> once over."""
    def run_import(args, *, key=None, progress=None, cancelled=None, source_is_attachment=False, relay=None):
        for n, question in enumerate(asks, 1):
            ask_id = f'7-{n}'
            (relay / f'ask-{ask_id}.json').write_text(json.dumps({
                'id': ask_id, 'round': 'describe round 1', 'instructions': 'Reply with one JSON object.',
                'question': question, 'schema': {'type': 'object', 'required': ['up']},
                'pictures': [str(picture)]}), encoding='utf-8')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                path = relay / f'answer-{ask_id}.json'
                if path.is_file():
                    answer = _answer(path)
                    path.unlink()
                    if answer.get('up') in ('+z', '-z'):
                        answered.append(answer)
                        break
                    (relay / f'problem-{ask_id}.json').write_text(json.dumps(
                        {'problem': f"answer.up={answer.get('up')!r} not in ['+z', '-z']", 'answer': answer,
                         'tries_left': 2}), encoding='utf-8')
                time.sleep(0.02)
            (relay / f'done-{ask_id}.json').write_text(json.dumps({'answered': True}), encoding='utf-8')
        time.sleep(0.3)         # the build and the vault save after the last ask
        return {'status': 'done', 'project': 'neos-1', 'fighter': 'Marth',
                'saved': {'name': 'Neos', 'character': 'Marth', 'skin_id': 'neos'}}
    return run_import


def test_the_imports_asks_are_answered_by_the_caller_with_their_pictures(client, vault, tmp_path, monkeypatch):
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    picture = tmp_path / 'sent-1.png'
    picture.write_bytes(PNG)
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    answered = []
    monkeypatch.setattr(studio_import, 'run_import',
                        _rigswap_asking(['Which way is up?', 'Which is the head?'], answered, picture))
    job_id = payload(call(client, 'import_model', {'source': str(model), 'fighter': 'marth'}))['job_id']
    polled = call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 10})
    head = payload(polled)
    assert head['status'] == model_jobs.NEEDS_ANSWERS and polled['isError'] is False
    [ask] = head['asks']
    assert ask['ask_id'] == '7-1' and ask['question'] == 'Which way is up?' and ask['pictures'] == 1
    assert ask['answer_schema'] == {'type': 'object', 'required': ['up']} and 'answer_import' in head['note']
    assert [b['type'] for b in polled['content'][1:]] == ['text', 'image']
    assert polled['content'][2]['data'] == base64.b64encode(PNG).decode('ascii')
    # A misfit is refused at once, with the reason; the ask stays open for another answer.
    said = payload(call(client, 'answer_import', {'job_id': job_id,
                                                  'answers': [{'ask_id': '7-1', 'answer': {'up': 'sideways'}}]}))
    assert said['answers'][0]['status'] == 'refused' and 'sideways' in said['answers'][0]['problem']
    again = payload(call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 0}))
    assert again['asks'][0]['refused_answer']['your_answer'] == {'up': 'sideways'}
    said = payload(call(client, 'answer_import', {'job_id': job_id,      # an object sent as its JSON text is read
                                                  'answers': [{'ask_id': '7-1', 'answer': '{"up": "-z"}'}]}))
    assert said['answers'][0]['status'] == 'accepted'
    nxt = payload(call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 10}))
    assert nxt['status'] == model_jobs.NEEDS_ANSWERS and nxt['asks'][0]['ask_id'] == '7-2'
    assert 'refused_answer' not in nxt['asks'][0]
    stale = payload(call(client, 'answer_import', {'job_id': job_id,
                                                   'answers': [{'ask_id': '7-1', 'answer': {'up': '+z'}},
                                                               {'ask_id': '7-2', 'answer': {'up': '+z'}}]}))
    assert [a['status'] for a in stale['answers']] == ['not waiting', 'accepted']
    for _ in range(100):
        status = payload(call(client, 'job_status', {'job_id': job_id}))
        if status['status'] not in ('queued', 'running'):
            break
    assert status['status'] == 'done' and answered == [{'up': '-z'}, {'up': '+z'}]
    assert call(client, 'answer_import', {'job_id': job_id, 'answers': [{'ask_id': '7-1', 'answer': {}}]})[
        'isError'] is True, 'a finished job asks nothing'
    assert call(client, 'answer_import', {'job_id': 'nope', 'answers': []})['isError'] is True


# rigswap's whole-body skeleton ask (rigswap/core/fill.py QUESTION), cut to its table: what ask_checks reads.
_FILL_QUESTION = '''Say which of the model's own joints is each joint of a body.

  n  parent  across    deep    high  skin  below  names
  1       -     0.0     0.0    50.0   120      9  hips
  2       1     0.0     0.0    70.0    80      7  chest
  3       2     0.0     0.0    90.0    40      1  head
  4       3     0.0     0.0    95.0    40      0  skull
  5       2    10.0     0.0    75.0    30      1  arm_l
  6       5    20.0     0.0    70.0    20      0  hand_l
  7       2   -10.0     0.0    75.0    30      1  arm_r
  8       7   -20.0     0.0    70.0    20      0  hand_r
  9       1     5.0     0.0    30.0    50      0  leg_l
 10       1    -5.0     0.0    30.0    50      0  leg_r

What to answer:'''


def _skeleton_answer(**changes):
    limb = lambda **joints: {p: joints.get(p) for p in ('clavicle', 'shoulder', 'elbow', 'hand')}  # noqa: E731
    leg = lambda hip, ankle: {'hip': hip, 'knee': None, 'ankle': ankle, 'toe': None}  # noqa: E731
    answer = {'character': 'Neos', 'front_view': 'A', 'plan': 'biped', 'hips': 1, 'chest': 2, 'neck': 3, 'skull': 4,
              'legs': {'left': leg(1, 9), 'right': leg(1, 10)},
              'arms': {'left': limb(shoulder=5, hand=6), 'right': limb(shoulder=7, hand=8)}}
    answer.update(changes)
    return answer


def test_a_skeleton_answer_rigswap_could_not_use_is_refused_at_once_in_its_words(client, vault, tmp_path,
                                                                                monkeypatch):
    """0.9.0 build 3 smoke: answer_import said "accepted" for a skeleton whose left arm named no hand (the schema
    allows null), and rigswap asked a whole new round: "An earlier answer could not be used: the left arm names no
    hand." Now the answer is refused at once, with that reason, and never reaches rigswap."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    read = []

    def run_import(args, *, key=None, progress=None, cancelled=None, source_is_attachment=False, relay=None):
        (relay / 'ask-9-1.json').write_text(json.dumps({
            'id': '9-1', 'round': 'core fill', 'instructions': 'Reply with one JSON object.',
            'question': _FILL_QUESTION, 'schema': {'type': 'object'}, 'pictures': []}), encoding='utf-8')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            path = relay / 'answer-9-1.json'
            if path.is_file():
                read.append(_answer(path))
                path.unlink()
                (relay / 'done-9-1.json').write_text(json.dumps({'answered': True}), encoding='utf-8')
                break
            time.sleep(0.02)
        time.sleep(0.5)         # the build after the last ask: the relay folder goes when the job ends
        return {'status': 'done', 'project': 'neos-1', 'fighter': 'Marth', 'saved': None}
    monkeypatch.setattr(studio_import, 'run_import', run_import)
    job_id = payload(call(client, 'import_model', {'source': str(model), 'fighter': 'marth'}))['job_id']
    assert payload(call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 10}))['status'] == \
        model_jobs.NEEDS_ANSWERS
    handless = _skeleton_answer()
    handless['arms']['left']['hand'] = None
    said = payload(call(client, 'answer_import', {'job_id': job_id,
                                                  'answers': [{'ask_id': '9-1', 'answer': handless}]}))
    [entry] = said['answers']
    assert entry['status'] == 'refused' and entry['problem'] == 'the left arm names no hand'
    assert 'tries_left' not in entry and 'Answer the refused asks again' in said['next']
    time.sleep(0.3)
    assert read == [], 'rigswap never saw it'
    still = payload(call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 0}))
    assert still['status'] == model_jobs.NEEDS_ANSWERS and still['asks'][0]['ask_id'] == '9-1'
    said = payload(call(client, 'answer_import', {'job_id': job_id,
                                                  'answers': [{'ask_id': '9-1', 'answer': _skeleton_answer()}]}))
    # 'taken' is the same success seen late: the stand-in finishes 0.5 s after the answer and its relay folder goes
    # with the job, so on a loaded machine answer_import's next look can find the folder gone instead of done-<id>.
    assert said['answers'][0]['status'] in ('accepted', 'taken') and read == [_skeleton_answer()]
    assert payload(call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 10}))['status'] == 'done'


def _cancellable(seen, *, save_anyway=False):
    """A stand-in run_import that works until it is told to stop (``cancelled``, as import_job polls it while
    rigswap runs), then answers as import_job does: ``_stopped`` (nothing saved), or, ``save_anyway``, a costume
    saved before the stop reached it."""
    def run_import(args, *, key=None, progress=None, cancelled=None, source_is_attachment=False, relay=None):
        progress({'progress': ['import Neos.glb onto the fighter it fits best', 'rigswap: fitting'],
                  'step': 'loading the model', 'seconds': 1.0, 'project': 'neos-1'})
        deadline = time.monotonic() + 10
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.02)
        seen.append(cancelled())
        if save_anyway:
            return {'status': 'done', 'project': 'neos-1', 'fighter': 'Marth', 'vault_changed': True,
                    'saved': {'name': 'Neos', 'character': 'Marth', 'skin_id': 'neos'}}
        return {'status': 'cancelled', 'project': 'neos-1', 'fighter': None, 'saved': None}
    return run_import


def _wait_running(client, job_id):
    for _ in range(100):
        record = jobs.get(job_id)
        if record.get('extra', {}).get('progress_lines'):
            return record
        time.sleep(0.02)
    raise AssertionError('the import did not start')


def test_cancel_import_stops_an_import_and_says_nothing_was_saved(client, vault, tmp_path, monkeypatch):
    """The window's chip has Cancel (POST /api/jobs/<id>/cancel); cancel_import is the same stop for the AI."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    seen = []
    monkeypatch.setattr(studio_import, 'run_import', _cancellable(seen))
    job_id = payload(call(client, 'import_model', {'source': str(model)}))['job_id']
    running = _wait_running(client, job_id)
    # What the chip shows comes on the job's record (and its `job` event): the name the costume is saved under, no
    # fighter yet, the card's step in words, no ask open. The detail stays rigswap's newest line, for job_status.
    extra = running['extra']
    assert extra['model'] == 'Neos' and extra['fighter'] is None and extra['change'] is None
    assert extra['step'] == 'loading the model' and extra['asking'] is False
    assert running['detail'] == 'rigswap: fitting'
    result = call(client, 'cancel_import', {'job_id': job_id})
    said = payload(result)
    assert result['isError'] is False
    assert said['status'] == 'stopped' and said['saved'] is None and 'nothing was saved' in said['note']
    record = jobs.get(job_id)
    assert record['status'] == 'cancelled' and record['extra']['stopping'] is True and seen == [True]
    again = payload(call(client, 'cancel_import', {'job_id': job_id}))
    assert again['status'] == 'already_stopped' and again['job_status'] == 'cancelled'
    assert call(client, 'cancel_import', {'job_id': 'nope'})['isError'] is True
    assert call(client, 'cancel_import', {})['isError'] is True


def test_a_stop_after_the_save_leaves_the_import_done_with_its_costume(client, vault, tmp_path, monkeypatch):
    """"Stopped: nothing saved" is only ever said of an import that saved nothing: a Cancel that came after the vault
    save ends the job done, and cancel_import says what was saved."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    monkeypatch.setattr(studio_import, 'run_import', _cancellable([], save_anyway=True))
    job_id = payload(call(client, 'import_model', {'source': str(model), 'fighter': 'marth'}))['job_id']
    assert _wait_running(client, job_id)['extra']['fighter'] == 'Marth'
    said = payload(call(client, 'cancel_import', {'job_id': job_id}))
    assert said['status'] == 'already_finished' and said['saved']['skin_id'] == 'neos'
    assert '"Neos" was saved' in said['note']
    record = jobs.get(job_id)
    assert record['status'] == 'done' and record['result']['vault_changed'] is True
    later = payload(call(client, 'cancel_import', {'job_id': job_id}))
    assert later['status'] == 'already_finished' and later['saved']['name'] == 'Neos'


def test_the_chip_names_the_model_as_the_import_saves_it(tmp_path, monkeypatch):
    """The chip's ``model`` is the costume's name ('Clank', never 'Clank.zip'): the call's name, else the one the
    import makes from the file; a change names the import's own."""
    from randall.model_import.chat import import_job, studio_import
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    for project, record in (('neos-1', {'name': 'Neos', 'source': 'Neos.glb', 'fighter': 'Marth'}),
                            ('clank-2', {'source': str(tmp_path / 'clank-rift-apart.zip'), 'fighter': 'Kirby'})):
        workflow = studio_import._folder(project) / 'workflow'
        workflow.mkdir(parents=True)
        (workflow / import_job.JOB).write_text(json.dumps(record), encoding='utf-8')
    assert model_jobs.shown({'project': 'neos-1', 'change': 'the legs look wrong'}) == {
        'model': 'Neos', 'fighter': 'Marth', 'change': 'the legs look wrong'}
    assert model_jobs.shown({'project': 'clank-2', 'change': 'x'})['model'] == 'Clank Rift Apart'
    assert model_jobs.shown({'project': 'gone-2', 'change': 'x'})['model'] == 'gone-2'
    assert model_jobs.shown({'source': str(tmp_path / 'Neos.fbx')}) == {'model': 'Neos', 'fighter': None,
                                                                       'change': None}
    assert model_jobs.shown({'source': str(tmp_path / 'clank.zip'), 'name': ' My Clank ', 'fighter': 'Kirby'}) == {
        'model': 'My Clank', 'fighter': 'Kirby', 'change': None}


def test_the_job_says_when_an_ask_waits_on_the_users_ai(client, vault, tmp_path, monkeypatch):
    """rigswap prints nothing when it asks: the job's ``asking`` (the chip's "waiting on your AI's answer") is read
    from the relay folder while the import runs, true while an ask is open and false again once it is answered."""
    from randall.model_import.chat import import_job, studio_import
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    picture = tmp_path / 'sent-1.png'
    picture.write_bytes(PNG)
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    monkeypatch.setattr(model_jobs, 'ASK_POLL', 0.02)
    answered = []
    monkeypatch.setattr(studio_import, 'run_import', _rigswap_asking(['Which way is up?'], answered, picture))
    job_id = payload(call(client, 'import_model', {'source': str(model), 'fighter': 'marth'}))['job_id']

    def wait_for(asking):
        for _ in range(250):
            if jobs.get(job_id).get('extra', {}).get('asking') is asking:
                return True
            time.sleep(0.02)
        return False
    assert wait_for(True), 'an open ask shows'
    said = payload(call(client, 'answer_import', {'job_id': job_id,
                                                  'answers': [{'ask_id': '7-1', 'answer': {'up': '+z'}}]}))
    # 'taken': the same success seen late (the stand-in's run ends 0.3 s after its one ask, the relay folder with it).
    assert said['answers'][0]['status'] in ('accepted', 'taken')
    assert wait_for(False), 'answered, it goes'
    assert payload(call(client, 'job_status', {'job_id': job_id, 'wait_seconds': 10}))['status'] == 'done'
    assert answered == [{'up': '+z'}] and jobs.get(job_id)['extra']['asking'] is False


def test_the_documented_tool_count_is_the_served_one(client):
    listed = rpc(client, 'tools/list').get_json()['result']['tools']
    doc = (REPO / 'docs' / 'dev' / 'APP_MCP.md').read_text(encoding='utf-8')
    import re
    assert f'`tools/list` gives {len(listed)} tools' in doc, re.search(r'`tools/list` gives \d+ tools', doc)
    assert 'cancel_import' in {tool['name'] for tool in listed} and '`cancel_import`' in doc


# ------------------------------------------------------------------ whose AI usage MCP calls spend

def account(client, token, header=TOKEN):
    """The window hands over its token (the backend token and the window's own key)."""
    return client.post('/api/mcp/account', json={'token': token},
                       headers={'X-Nucleus-Token': header, 'X-Nucleus-UI-Key': UI_KEY} if header else {})


def sign_in(client, monkeypatch, entitlement):
    """The window hands over its Patreon token; ai-entitlement (mocked) answers ``entitlement`` for it."""
    asked = []

    def answer(token):
        asked.append(token)
        return dict(entitlement)
    monkeypatch.setattr(credits, '_entitlement', answer)
    response = account(client, 'patreon-app-token')
    assert response.status_code == 200 and response.get_json() == {'signed_in': True}
    assert 'patreon-app-token' not in response.get_data(as_text=True)
    return asked


def provider(monkeypatch):
    """The image provider, mocked: records the key each generate_material call was billed to."""
    from randall.recolor import texture_material
    keys = []

    def sheet(prompts, *, key=None, style='swatch'):
        keys.append(key)
        return [PNG for _ in prompts], {'model': 'mock-image-model'}
    monkeypatch.setattr(texture_material, 'generate_material_sheet', sheet)
    return keys


def test_ai_tools_without_a_sign_in_say_to_open_nucleus_and_sign_in(client, vault, tmp_path, monkeypatch):
    from randall.model_import.chat import import_job, studio_import
    keys = provider(monkeypatch)
    result = call(client, 'generate_material', {'prompts': ['red brick']})
    assert result['isError'] is True
    assert result['content'][0]['text'] == credits.SIGN_IN
    assert 'open SSBM Nucleus' in credits.SIGN_IN and 'signed in' in credits.SIGN_IN
    model = tmp_path / 'Neos.glb'
    model.write_bytes(b'glTF')
    monkeypatch.setattr(import_job, 'setup', lambda: (Path(sys.executable), tmp_path))
    monkeypatch.setattr(studio_import, 'run_import', lambda *args, **kwargs: {'status': 'done'})
    # The model import is not one of them: its asks are the caller's own AI's to answer (no Randall usage).
    assert call(client, 'import_model', {'source': str(model), 'fighter': 'marth'})['isError'] is False
    assert keys == [] and {'import_model', 'fix_import'}.isdisjoint(credits.AI_TOOLS)
    # Everything without AI still works.
    assert call(client, 'search_vault')['isError'] is False


def test_the_windows_token_bills_ai_calls_and_sign_out_clears_it(client, vault, monkeypatch):
    keys = provider(monkeypatch)
    asked = sign_in(client, monkeypatch, {'active': True, 'api_key': 'sk-patron', 'remaining': 2.5,
                                          'period_budget': 5})
    result = call(client, 'generate_material', {'prompts': ['red brick']})
    assert result['isError'] is False, result
    assert keys == ['sk-patron'] and asked == ['patreon-app-token']
    assert 'sk-patron' not in json.dumps(result) and 'patreon-app-token' not in json.dumps(result)
    response = account(client, None)
    assert response.status_code == 200 and response.get_json() == {'signed_in': False}
    result = call(client, 'generate_material', {'prompts': ['red brick']})
    assert result['isError'] is True and result['content'][0]['text'] == credits.SIGN_IN
    assert keys == ['sk-patron'] and asked == ['patreon-app-token']


def test_each_ai_call_rechecks_the_entitlement_like_a_chat_turn(client, vault, monkeypatch):
    keys = provider(monkeypatch)
    monkeypatch.setattr(credits, '_machine_key', lambda: 'sk-machine')     # never used for a signed-in person
    cases = [({'active': True, 'api_key': 'k', 'remaining': 0, 'resets_at': '2026-12-01T00:00:00Z'},
              "reached this month's Randall limit. It resets on Dec 1"),
             ({'active': True, 'api_key': 'k', 'remaining': '0', 'monthly_budget': 0,
               'free_refills_at': '2026-11-20T00:00:00Z'}, 'free Randall usage. It refills on Nov 20'),
             ({'paused': True, 'linked': True}, 'paused'),
             ({'linked': True, 'reason': 'campaign_membership_required'}, 'Join sc00p on Patreon'),
             ({'linked': True, 'active': False}, 'does not have Randall access'),
             ({'active': True, 'remaining': 1}, 'not ready yet'),
             ({'linked': False, 'active': False}, credits.SIGN_IN)]
    for answer, words in cases:
        asked = sign_in(client, monkeypatch, answer)
        result = call(client, 'generate_material', {'prompts': ['red brick']})
        assert result['isError'] is True and words in result['content'][0]['text'], (answer, result)
        assert asked == ['patreon-app-token']
    assert keys == []

    def offline(token):
        raise OSError('unreachable')
    monkeypatch.setattr(credits, '_entitlement', offline)
    result = call(client, 'generate_material', {'prompts': ['red brick']})
    assert result['isError'] is True and 'Could not check your Patreon link' in result['content'][0]['text']
    monkeypatch.setattr(credits, '_entitlement', lambda token: {'invalid_token': True})
    result = call(client, 'generate_material', {'prompts': ['red brick']})
    assert result['isError'] is True and 'connect Patreon again' in result['content'][0]['text']
    assert credits.signed_in() is False and keys == []


def test_the_machine_key_is_the_fallback_when_nobody_is_signed_in(client, vault, monkeypatch):
    keys = provider(monkeypatch)
    monkeypatch.setattr(credits, '_machine_key', lambda: 'sk-machine')
    assert call(client, 'generate_material', {'prompts': ['red brick']})['isError'] is False
    assert keys == ['sk-machine']


def test_the_account_route_is_guarded_and_checks_what_it_is_sent(client, monkeypatch):
    assert account(client, 'patreon-app-token', header=None).status_code == 401
    assert credits.signed_in() is False
    for body in ({}, {'token': 'a', 'extra': 1}, {'token': 5}, {'token': 'has space'}, {'token': 'x' * 5000}):
        response = client.post('/api/mcp/account', json=body, headers=WINDOW)
        assert response.status_code == 400, body
    assert credits.signed_in() is False
    monkeypatch.setenv('NUCLEUS_ASSISTANT', '0')
    assert account(client, 'patreon-app-token').status_code == 404
    assert credits.signed_in() is False


# ------------------------------------------------------------------ test_in_game over MCP

def test_test_in_game_takes_the_settings_dolphin_folder_then_slippi_launchers(client, monkeypatch, tmp_path):
    monkeypatch.setattr(window, 'launcher_dolphin', lambda: None)
    assert randall_tools._game_settings({})['slippiDolphinPath'] == ''
    monkeypatch.setattr(window, 'launcher_dolphin', lambda: str(tmp_path / 'netplay'))
    assert randall_tools._game_settings({})['slippiDolphinPath'] == str(tmp_path / 'netplay')
    sent = client.post('/api/mcp/window', json={'slippi_dolphin_path': 'D:/Slippi'}, headers=WINDOW)
    assert sent.status_code == 200
    assert randall_tools._game_settings({})['slippiDolphinPath'] == 'D:/Slippi'
    refused = call(client, 'test_in_game', {'action': 'status', 'slippi_dolphin_path': 'E:/Other'})
    assert refused['isError'] is True                                    # the AI cannot name another Dolphin
    assert randall_tools._game_settings({})['slippiDolphinPath'] == 'D:/Slippi'
    client.post('/api/mcp/window', json={'slippi_dolphin_path': None}, headers=WINDOW)
    assert randall_tools._game_settings({})['slippiDolphinPath'] == str(tmp_path / 'netplay')


def test_the_window_route_is_guarded_and_checks_what_it_is_sent(client, monkeypatch):
    assert client.post('/api/mcp/window', json={'slippi_dolphin_path': 'D:/x'}).status_code == 401
    for body in ({}, {'slippi_dolphin_path': 5}, {'slippi_dolphin_path': 'x' * 2000}, {'slippi_dolphin_path': 'a', 'b': 1},
                 {'slippi_dolphin_path': r'\\evil\share'}, {'slippi_dolphin_path': '//evil/share'}):
        assert client.post('/api/mcp/window', json=body, headers=WINDOW).status_code == 400, body
    monkeypatch.setenv('NUCLEUS_ASSISTANT', '0')
    assert client.post('/api/mcp/window', json={'slippi_dolphin_path': 'D:/x'}, headers=WINDOW).status_code == 404


def test_only_the_window_sets_whose_account_and_which_dolphin_mcp_calls_use(client, monkeypatch):
    """The MCP client holds the backend token too. Before, it could hand the backend any Patreon token (whose
    usage its calls then spent) and name any folder as the user's Slippi Dolphin, which test_in_game then ran."""
    token = {'X-Nucleus-Token': TOKEN}
    sent = {'/api/mcp/account': {'token': 'someone-elses-token'}, '/api/mcp/window': {'slippi_dolphin_path': 'C:/UnapprovedSlippi'}}
    for url, body in sent.items():
        refused = client.post(url, json=body, headers=token)
        assert refused.status_code == 403 and refused.get_json()['code'] == 'not_the_app_window', url
        agent = client.post(url, json=body, headers=dict(WINDOW, **{'X-Nucleus-Agent': '1'}))
        assert agent.status_code == 403 and agent.get_json()['code'] == 'automation_caller', url
        wrong = client.post(url, json=body, headers=dict(token, **{'X-Nucleus-UI-Key': 'guess'}))
        assert wrong.status_code == 403, url
    assert credits.signed_in() is False
    assert randall_tools._game_settings({})['slippiDolphinPath'] != 'C:/UnapprovedSlippi'
    monkeypatch.delenv('NUCLEUS_UI_APPROVAL_KEY')
    for url, body in sent.items():
        assert client.post(url, json=body, headers=WINDOW).status_code == 503, url     # no key: fail closed


def test_play_notes_say_its_own_window_over_mcp():
    note = {'game_test': {'note': 'Interactive play session, live in the panel on the right: ...', 'n': 1}}
    assert randall_tools._no_panel(note) == {
        'game_test': {'note': 'Interactive play session, live in its own Dolphin window on their screen: ...', 'n': 1}}
    listed = {t['name']: t for t in randall_tools.listed()}
    assert 'game_screenshot' in listed['test_in_game']['description']
    assert listed['game_screenshot']['annotations']['readOnlyHint'] is True


def test_game_screenshot_reads_only_a_running_play_sessions_own_dolphin(client, monkeypatch):
    from shared.ingame import screenshot
    sessions = {
        'live': {'kind': 'ingame', 'status': 'running', 'owned': {'dolphin:4242': {'pid': 4242}}},
        'booting': {'kind': 'ingame', 'status': 'running', 'owned': {}},
        'ended': {'kind': 'ingame', 'status': 'done', 'owned': {'dolphin:4242': {'pid': 4242}}},
        'other': {'kind': 'mcp_model_import', 'status': 'running', 'owned': {'dolphin:7': {'pid': 7}}},
    }
    monkeypatch.setattr(jobs, 'get', sessions.get)
    grabbed = []
    monkeypatch.setattr(screenshot, 'capture_via_printwindow', lambda pid, **kw: grabbed.append(pid) or _png())
    result = call(client, 'game_screenshot', {'session_id': 'live'})
    assert result['isError'] is False and grabbed == [4242]
    assert result['content'][1]['type'] == 'image' and result['content'][1]['mimeType'] == 'image/png'
    for session_id in ('booting', 'ended', 'other', 'missing'):
        assert call(client, 'game_screenshot', {'session_id': session_id})['isError'] is True, session_id
    assert grabbed == [4242]
    assert call(client, 'game_screenshot', {})['isError'] is True


def test_a_play_session_can_be_waited_for_with_status_or_job_status(client, monkeypatch):
    from randall.mcp import randall_tools
    phases = iter(['loading', 'loading', 'playing'])
    seen = []

    def run(name, arguments, app):
        seen.append(dict(arguments))
        return {'game_test': {'session_id': 's1', 'running': True, 'status': {'phase': next(phases)}}}
    monkeypatch.setattr(randall_tools, '_run', run)
    monkeypatch.setattr(randall_tools.time, 'sleep', lambda seconds: None)
    result = call(client, 'test_in_game', {'action': 'status', 'session_id': 's1', 'wait_seconds': 30})
    assert payload(result)['game_test']['status']['phase'] == 'playing' and len(seen) == 3
    assert call(client, 'test_in_game', {'action': 'start', 'wait_seconds': 5})['isError'] is True

    monkeypatch.setattr(jobs, 'get', {'s1': {'kind': 'ingame', 'status': 'running'}}.get)
    phases, seen[:] = iter(['loading', 'playing']), []
    result = call(client, 'job_status', {'job_id': 's1', 'wait_seconds': 50})
    assert payload(result)['game_test']['status']['phase'] == 'playing'
    assert seen[0] == {'action': 'status', 'session_id': 's1', 'wait_seconds': randall_tools.GAME_WAIT_MAX}
    assert 'No job' in call(client, 'job_status', {'job_id': 'nothing'})['content'][0]['text']


def test_chat_words_that_are_wrong_over_mcp_are_replaced():
    from randall.assistant import tools as chat_tools
    from randall.mcp import randall_tools
    chat = {s['function']['name']: s['function'] for s in chat_tools.SCHEMAS}
    listed = {t['name']: t for t in randall_tools.listed()}
    for name, pairs in randall_tools.REWORD.items():
        for old, new in pairs:
            assert old in chat[name]['description'], (name, old)        # the chat still says it: keep in step
            assert old not in listed[name]['description'] and new in listed[name]['description']
    for (name, key), text in randall_tools.PARAM_REWORD.items():
        assert 'turn ends' in chat[name]['parameters']['properties'][key]['description']
        assert listed[name]['inputSchema']['properties'][key]['description'] == text
    assert 'turn ends' not in json.dumps([listed[n] for n in ('skin_lab', 'stage_lab', 'save_mod_copy')])
    assert 'has no surface the lab can edit' not in listed['stage_lab']['description']
    assert listed['test_in_game']['inputSchema']['properties']['wait_seconds']['maximum'] == randall_tools.GAME_WAIT_MAX


# ------------------------------------------------------------------ the creation toolkit

FAKE_HARNESS = r'''
import json, os, sys
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg:
        continue
    if msg['method'] == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fake'}}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/progress',
                          'params': {'progressToken': 1, 'progress': 1}}), flush=True)
        result = {'content': [{'type': 'text', 'text': json.dumps({'pid': os.getpid(), 'echo': msg['params'],
                  'nucleus_env': sorted(k for k in os.environ if k.startswith('NUCLEUS_'))})}], 'isError': False}
    print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}), flush=True)
'''


@pytest.fixture
def allow_in_window(monkeypatch):
    """The person in the window clicks Allow on every question; the questions asked are recorded."""
    asked = []

    def confirm(kind, **question):
        asked.append(dict(question, kind=kind))
        return True
    monkeypatch.setattr(window, 'confirm', confirm)
    return asked


def test_unconfigured_toolkit_tools_say_how_to_set_it_up(client):
    for name in toolkit.FORWARDED:
        result = call(client, name, {'op': 'info'})
        text = result['content'][0]['text']
        assert result['isError'] is True
        assert toolkit.REPO_URL in text and 'setup.ps1' in text and 'connect_creation_toolkit' in text
        assert 'Can I clone the Nucleus creation toolkit and set it up?' in text
        assert 'Settings > AI > Creation toolkit' in text   # an AI with no shell points the user at the guide
    status = payload(call(client, 'creation_toolkit_status'))
    assert status['configured'] is False and status['setup']


def test_connect_refuses_a_folder_that_is_not_a_toolkit(client, tmp_path):
    for path in ('relative/folder', str(tmp_path / 'missing'), str(tmp_path)):
        result = call(client, 'connect_creation_toolkit', {'path': path})
        assert result['isError'] is True, path
    (tmp_path / 'tools' / 'harness').mkdir(parents=True)
    (tmp_path / 'tools' / 'harness' / 'harness_mcp.py').write_text('')
    result = call(client, 'connect_creation_toolkit', {'path': str(tmp_path)})
    assert result['isError'] is True and 'Python' in result['content'][0]['text']
    assert toolkit.saved_path() is None


def test_a_connected_toolkit_gets_the_call_and_restarts_when_it_died(client, allow_in_window, tmp_path, monkeypatch):
    harness = tmp_path / 'kit' / 'tools' / 'harness' / 'harness_mcp.py'
    harness.parent.mkdir(parents=True)
    harness.write_text(FAKE_HARNESS)
    monkeypatch.setattr(toolkit, 'PYTHONS', (sys.executable,))      # an absolute path joins as itself
    monkeypatch.setenv('NUCLEUS_BACKEND_TOKEN', 'secret-the-child-must-not-see')
    connected = payload(call(client, 'connect_creation_toolkit', {'path': str(tmp_path / 'kit')}))
    assert connected['connected'] is True and connected['python'] == sys.executable
    assert toolkit.saved_path() == str((tmp_path / 'kit').resolve())
    first = payload(call(client, 'stage_workbench', {'op': 'guide'}))
    assert first['echo'] == {'name': 'stage_workbench', 'arguments': {'op': 'guide'}}
    assert first['nucleus_env'] == []
    toolkit._child.process.kill()
    toolkit._child.process.wait(timeout=10)
    second = payload(call(client, 'native_port', {'op': 'info'}))
    assert second['echo']['name'] == 'native_port' and second['pid'] != first['pid']
    status = payload(call(client, 'creation_toolkit_status'))
    assert status['valid'] is True and status['running'] is True


def test_connect_reports_toolkit_packages_its_python_lacks(client, allow_in_window, tmp_path, monkeypatch):
    harness = tmp_path / 'kit' / 'tools' / 'harness' / 'harness_mcp.py'
    harness.parent.mkdir(parents=True)
    harness.write_text(FAKE_HARNESS)
    monkeypatch.setattr(toolkit, 'PYTHONS', (sys.executable,))
    monkeypatch.setattr(toolkit, '_PROBE', toolkit._PROBE.replace(repr(list(toolkit.MODULES)),
                                                                   repr(['json', 'no_such_module_xyz'])))
    connected = payload(call(client, 'connect_creation_toolkit', {'path': str(tmp_path / 'kit')}))
    assert connected['connected'] is True and connected['missing_packages'] == ['no_such_module_xyz']
    assert 'no_such_module_xyz' in connected['note'] and 'settings.json' in connected['note']


LISTING_HARNESS = r'''
import json, sys
TOOLS = [{'name': n, 'description': n + ' does a thing. More detail here.', 'inputSchema': {'type': 'object'}}
         for n in ('frameshot', 'netplay_desync', 'api', 'write_ram', 'native_port')]
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg:
        continue
    if msg['method'] == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fake'}}
    elif msg['method'] == 'tools/list':
        result = {'tools': TOOLS}
    else:
        result = {'content': [{'type': 'text', 'text': json.dumps({'echo': msg['params']})}], 'isError': False}
    print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}), flush=True)
'''


def test_toolkit_passthrough_needs_the_toolkit_and_says_how_to_set_it_up(client):
    for name, args in (('toolkit_tools', {}), ('toolkit_call', {'tool': 'frameshot'})):
        result = call(client, name, args)
        assert result['isError'] is True and 'connect_creation_toolkit' in result['content'][0]['text'], name


def test_toolkit_passthrough_lists_and_runs_only_the_offered_harness_tools(client, allow_in_window, tmp_path, monkeypatch):
    harness = tmp_path / 'kit' / 'tools' / 'harness' / 'harness_mcp.py'
    harness.parent.mkdir(parents=True)
    harness.write_text(LISTING_HARNESS)
    monkeypatch.setattr(toolkit, 'PYTHONS', (sys.executable,))
    assert payload(call(client, 'connect_creation_toolkit', {'path': str(tmp_path / 'kit')}))['connected'] is True
    listing = payload(call(client, 'toolkit_tools'))
    assert [t['name'] for t in listing['tools']] == ['frameshot', 'netplay_desync']     # api, write_ram: dev only
    assert listing['tools'][0]['summary'] == 'frameshot does a thing'
    assert 'stage_shot' in listing['not_in_this_toolkit']
    full = payload(call(client, 'toolkit_tools', {'names': ['netplay_desync']}))
    assert full['tools'] == [{'name': 'netplay_desync', 'description': 'netplay_desync does a thing. More detail here.',
                              'inputSchema': {'type': 'object'}}]
    ran = payload(call(client, 'toolkit_call', {'tool': 'frameshot', 'arguments': {'char': 'marth'}}))
    assert ran['echo'] == {'name': 'frameshot', 'arguments': {'char': 'marth'}}
    for refused in ({'tool': 'api'}, {'tool': 'write_ram'}, {'tool': 'frameshot', 'arguments': []}, {},
                    {'tool': 'frameshot', 'x': 1}):
        assert call(client, 'toolkit_call', refused)['isError'] is True, refused
    assert call(client, 'toolkit_tools', {'names': ['api']})['isError'] is True
    listed = {t['name']: t for t in rpc(client, 'tools/list').get_json()['result']['tools']}
    assert listed['toolkit_call']['inputSchema']['properties']['tool']['enum'] == list(toolkit.PASSTHROUGH)
    assert listed['toolkit_tools']['annotations']['readOnlyHint'] is True


def test_toolkit_results_carry_the_pictures_they_name(tmp_path):
    from PIL import Image
    shots = []
    for i, size in enumerate(((1280, 960), (64, 48), (64, 48), (64, 48), (64, 48))):
        path = tmp_path / f'shot{i}.png'
        Image.new('RGB', size, (200, 30, 30)).save(path)
        shots.append(str(path))
    text = json.dumps({'ok': True, 'shots': [{'path': shots[0]}, shots[1]], 'more': shots[2:],
                       'missing': str(tmp_path / 'gone.png'), 'log': 'not a picture.txt'})
    result = toolkit.with_pictures({'content': [{'type': 'text', 'text': text}], 'isError': False})
    images = [b for b in result['content'] if b['type'] == 'image']
    assert len(images) == toolkit.PICTURES == 4
    first = Image.open(io.BytesIO(base64.b64decode(images[0]['data'])))
    assert first.width == toolkit.PICTURE_WIDTH                      # big captures are scaled down
    assert '4 of the 5 pictures' in result['content'][1]['text']
    failed = {'content': [{'type': 'text', 'text': text}], 'isError': True}
    assert toolkit.with_pictures(failed) is failed
    plain = {'content': [{'type': 'text', 'text': '{"ok": true}'}], 'isError': False}
    assert toolkit.with_pictures(plain) is plain


def test_every_passthrough_tool_is_in_this_checkouts_harness():
    sys.path.insert(0, str(REPO / 'tools' / 'harness'))
    import harness_mcp
    assert set(toolkit.PASSTHROUGH) <= set(harness_mcp.HANDLERS)


@pytest.mark.slow
def test_this_checkout_is_a_toolkit_that_answers_stage_workbench_guide(client, allow_in_window):
    """The real harness, started from this checkout's own venv (needs app/venv)."""
    python = REPO / 'app' / 'venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        pytest.skip('no app/venv in this checkout')
    assert payload(call(client, 'connect_creation_toolkit', {'path': str(REPO)}))['connected'] is True
    result = call(client, 'stage_workbench', {'op': 'guide'})
    assert result['isError'] is False
    assert 'graft' in result['content'][0]['text']


# ------------------------------------------------------------------ security review 11-19, M1

NETWORK_PATHS = (r'\\attacker\share\kit', r'\\attacker@SSL\DavWWWRoot\kit', r'\\?\UNC\attacker\share\kit',
                 '//attacker/share/kit', 'file://attacker/share/kit.zip',
                 # the NT namespace: not absolute to pathlib, but CreateFileW opens the share (review 11-22)
                 r'\??\UNC\attacker@SSL\DavWWWRoot\kit', '/??/UNC/attacker/share/kit')


def _kit(tmp_path, source=FAKE_HARNESS):
    harness = tmp_path / 'kit' / 'tools' / 'harness' / 'harness_mcp.py'
    harness.parent.mkdir(parents=True)
    harness.write_text(source)
    return tmp_path / 'kit'


def test_no_tool_takes_a_network_path_and_nothing_is_opened(client, vault, monkeypatch):
    from core.path_safety import is_network_path
    for path in NETWORK_PATHS:
        assert is_network_path(path), path
    for path in ('C:/Users/me/kit', r'D:\mods\a.zip', '/home/me/kit', 'file:///C:/x', 'relative'):
        assert not is_network_path(path), path
    opened = []
    monkeypatch.setattr('pathlib.Path.is_file', lambda self: opened.append(self) or False)
    monkeypatch.setattr('pathlib.Path.is_dir', lambda self: opened.append(self) or False)
    for path in NETWORK_PATHS:
        for name, arguments in (('connect_creation_toolkit', {'path': path}), ('attach_file', {'path': path}),
                                ('import_to_vault', {'path': path}), ('import_to_vault', {'paths': ['C:/a', path]}),
                                ('import_model', {'source': path}),
                                ('test_in_game', {'action': 'start', 'vanilla_iso_path': path}),
                                ('save_build_iso', {'job_id': 'x', 'destination': path})):
            result = call(client, name, arguments)
            assert result['isError'] is True, (name, path)
            assert 'network path' in result['content'][0]['text'], (name, path)
    assert opened == []                     # refused before any filesystem call reached the host
    assert toolkit.saved_path() is None


def test_the_shared_helper_also_guards_each_tool_on_its_own(tmp_path):
    from randall.mcp import build_tools
    for path in NETWORK_PATHS:
        with pytest.raises(ValueError, match='network path'):
            randall_tools._attach({'path': path})
        with pytest.raises(ValueError, match='network path'):
            build_tools._file(path)
        assert toolkit.inspect(path)['valid'] is False      # a network folder saved earlier (old backup) never runs
        with pytest.raises(ValueError):
            window.set_slippi_dolphin_path(path)


def test_toolkit_status_is_read_only_and_runs_nothing(client, tmp_path, monkeypatch, allow_in_window):
    kit = _kit(tmp_path)
    monkeypatch.setattr(toolkit, 'PYTHONS', (sys.executable,))
    assert payload(call(client, 'connect_creation_toolkit', {'path': str(kit)}))['connected'] is True
    toolkit.stop()
    ran = []
    monkeypatch.setattr(toolkit.subprocess, 'run', lambda *a, **k: ran.append(a) or pytest.fail('ran a program'))
    monkeypatch.setattr(toolkit.subprocess, 'Popen', lambda *a, **k: ran.append(a) or pytest.fail('ran a program'))
    status = payload(call(client, 'creation_toolkit_status'))
    assert status['valid'] is True and status['running'] is False and ran == []


def test_connecting_a_toolkit_asks_the_person_in_the_window_first(client, tmp_path, monkeypatch):
    kit = _kit(tmp_path)
    monkeypatch.setattr(toolkit, 'PYTHONS', (sys.executable,))
    ran = []
    real_run = toolkit.subprocess.run
    monkeypatch.setattr(toolkit.subprocess, 'run', lambda *a, **k: ran.append(a) or real_run(*a, **k))
    for answer, words in ((False, 'declined'), (None, 'Nobody answered')):
        monkeypatch.setattr(window, 'confirm', lambda kind, answer=answer, **q: answer)
        result = call(client, 'connect_creation_toolkit', {'path': str(kit)})
        assert result['isError'] is True and words in result['content'][0]['text']
        assert toolkit.saved_path() is None and ran == []       # nothing saved, its Python never ran
    asked = []
    monkeypatch.setattr(window, 'confirm', lambda kind, **q: asked.append(dict(q, kind=kind)) or True)
    assert payload(call(client, 'connect_creation_toolkit', {'path': str(kit)}))['connected'] is True
    assert asked[0]['kind'] == 'creation_toolkit' and str(kit.resolve()) in asked[0]['message']
    assert asked[0]['detail']['python'] == sys.executable and len(ran) == 1


def test_only_the_window_can_see_and_answer_the_question(client, monkeypatch):
    import threading
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', 'window-only-key')
    answers = []
    asking = threading.Thread(target=lambda: answers.append(window.confirm(
        'creation_toolkit', title='Connect?', message='Run C:/kit/python.exe?', timeout=20)))
    asking.start()
    deadline = time.monotonic() + 10
    while not window.pending() and time.monotonic() < deadline:
        time.sleep(0.02)
    [question] = window.pending()
    url = f"/api/mcp/window/confirmations/{question['id']}"
    token = {'X-Nucleus-Token': TOKEN}
    ui = dict(token, **{'X-Nucleus-UI-Key': 'window-only-key'})
    # the backend token alone (what the AI client and the harness hold) can neither read nor answer it
    assert client.get('/api/mcp/window/confirmations', headers=token).status_code == 403
    assert client.post(url, json={'allowed': True}, headers=token).status_code == 403
    assert client.post(url, json={'allowed': True},
                       headers=dict(ui, **{'X-Nucleus-Agent': '1'})).status_code == 403
    assert client.post(url, json={'allowed': 'yes'}, headers=ui).status_code == 400
    listed = client.get('/api/mcp/window/confirmations', headers=ui).get_json()['pending']
    assert [q['id'] for q in listed] == [question['id']] and listed[0]['message'] == 'Run C:/kit/python.exe?'
    assert client.post(url, json={'allowed': True}, headers=ui).status_code == 200
    asking.join(10)
    assert answers == [True] and window.pending() == []
    assert client.post(url, json={'allowed': False}, headers=ui).status_code == 404       # answered once
    monkeypatch.delenv('NUCLEUS_UI_APPROVAL_KEY')
    assert client.get('/api/mcp/window/confirmations', headers=ui).status_code == 503     # no key: fail closed
    assert window.confirm('creation_toolkit', title='t', message='m', timeout=0.05) is None    # unanswered
