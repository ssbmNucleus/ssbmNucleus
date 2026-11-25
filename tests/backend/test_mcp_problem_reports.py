"""report_problem over MCP (randall/mcp/report_tools.py, randall/reports/problem_report.py, docs/dev/APP_MCP.md).

The user's own AI writes a problem report; nothing is sent by the call. The person at the window reads it, ticks
what goes, and sends it through the chat report's own submit, or discards it. The app here runs behind the REAL
backend-token check (test_app_mcp.guarded_app) with the chat report blueprint beside the MCP one, and the network is
`requests` replaced by a recorder, so a send goes through the real transport (report_transport) and the real
submit (chat_report.submit).
"""
import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from core import config, jobs
from randall.mcp import credits, window
from randall.reports import chat_report, problem_report
from randall.routes import chat_reports as chat_reports_module
from shared.diagnostics import bug_report
from tests.backend.test_app_mcp import TOKEN, UI_KEY, WINDOW, PNG, call, guarded_app, payload

KEY = 'sk-or-v1-' + '0123456789abcdef' * 4
HOME = str(Path.home() / 'Documents' / 'models' / 'Clank.glb')
TOKEN_ONLY = {'X-Nucleus-Token': TOKEN}


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300

    def json(self):
        return self._body


class Network:
    """`requests.post`/`put` as the bug-report worker would answer them, recorded."""

    def __init__(self):
        self.posts, self.puts = [], []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({'url': url, 'meta': json})
        return _Response(200, {'id': 'ab' * 16})

    def put(self, url, data=None, headers=None, timeout=None):
        self.puts.append({'url': url, 'data': data})
        return _Response(200, {'notified': True})


@pytest.fixture
def network(monkeypatch):
    fake = Network()
    monkeypatch.setattr('requests.post', fake.post)
    monkeypatch.setattr('requests.put', fake.put)
    monkeypatch.setattr(bug_report, '_BUGREPORT_URL', 'https://reports.invalid/bugreport')
    return fake


@pytest.fixture
def web(vault, tmp_path, monkeypatch, network):
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    monkeypatch.delenv('NUCLEUS_APP_VERSION', raising=False)
    monkeypatch.delenv('NUCLEUS_ASSISTANT', raising=False)
    monkeypatch.setenv('NUCLEUS_STUDIO_ROOT', str(tmp_path / 'imports'))
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'mex_api_20261122.log').write_text('old day\n', encoding='utf-8')
    (logs / 'mex_api_20261123.log').write_text(f'INFO opened {HOME}\nERROR key {KEY}\n', encoding='utf-8')
    monkeypatch.setattr(config, 'LOGS_PATH', logs)
    credits.clear()
    app = guarded_app()
    app.register_blueprint(chat_reports_module.chat_reports_bp)
    yield app.test_client()
    window.clear()


@pytest.fixture
def an_import(tmp_path):
    """A failed MCP model import: its job record on disk, its folder under the imports root, its source model."""
    model = tmp_path / 'models' / 'Clank.glb'
    model.parent.mkdir()
    model.write_bytes(b'glTF' + bytes(2000))
    folder = tmp_path / 'imports' / 'clank-1'
    (folder / 'workflow').mkdir(parents=True)
    (folder / 'rigswap').mkdir()
    (folder / 'workflow' / 'job.json').write_text(json.dumps(
        {'name': 'Clank', 'source': 'Clank.glb', 'download': str(model), 'fighter': 'Fox'}), encoding='utf-8')
    (folder / 'workflow' / 'job.log').write_text(
        ''.join(f'line {n}\n' for n in range(60)) + f'rigswap: could not read {HOME}\n', encoding='utf-8')
    (folder / 'rigswap' / 'result.json').write_text(json.dumps({'status': 'failed', 'error': 'no skeleton'}),
                                                    encoding='utf-8')
    (folder / 'randall.jsonl').write_text(json.dumps({'model': 'mock-model', 'rounds': 3}) + '\n', encoding='utf-8')
    (folder / 'portrait.png').write_bytes(PNG)
    now = time.time()
    record = {'id': 'job1', 'kind': 'mcp_model_import', 'label': 'Import Clank', 'status': 'failed',
              'error': f'rigswap ended with an error reading {HOME}', 'params': {'source': str(model)},
              'extra': {'project': 'clank-1', 'seconds': 12.5, 'asks': str(tmp_path / 'relay')},
              'result': {'project': 'clank-1', 'error': 'the skeleton could not be read',
                         'pictures': [str(folder / 'portrait.png')]},
              'created_at': now - 20, 'started_at': now - 19, 'ended_at': now - 6}
    jobs_dir = Path(jobs._root_override)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / 'job1.json').write_text(json.dumps(record), encoding='utf-8')
    return {'model': model, 'folder': folder}


def report(web, **arguments):
    body = {'title': 'Import of Clank failed', 'markdown': f'# It failed\nThe model at {HOME} did not load.\n'
            f'My key was {KEY}.', **arguments}
    return call(web, 'report_problem', body)


def reports_on_disk():
    root = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports'
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def members(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


# ------------------------------------------------------------------ the call sends nothing


def test_the_call_assembles_a_report_here_and_sends_nothing(web, network, an_import):
    result = report(web, job_id='job1', model='claude-opus-5-5', effort='high')
    assert result['isError'] is False, result
    made = payload(result)
    assert made['status'] == 'waiting_for_user' and made['sent'] is False
    assert made['note'].startswith('Waiting for you to confirm in Nucleus')
    parts = {a['name']: a for a in made['attachments']}
    assert set(parts) == {'report.md', 'metadata.json', 'import/mcp-job.json', 'import/job.json',
                          'import/result.json', 'import/randall.jsonl', 'import/job.log', 'logs/nucleus.log',
                          'previews/portrait.png', 'source/Clank.glb'}
    assert parts['report.md']['optional'] is False and parts['metadata.json']['optional'] is False
    assert parts['source/Clank.glb'] == {'name': 'source/Clank.glb', 'label': 'The model file it was made from',
                                         'kind': 'source', 'bytes': 2004, 'optional': True, 'include': False,
                                         'too_large': False}
    assert all(parts[n]['include'] for n in parts if n != 'source/Clank.glb')
    assert network.posts == [] and network.puts == []            # nothing left the computer
    status = payload(call(web, 'problem_report_status', {'report_id': made['report_id']}))
    assert status['status'] == 'waiting_for_user' and 'Nothing has been sent' in status['note']

    # What waits on disk is scrubbed: no home folder, no key; the error output and versions are in metadata.json.
    folder = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports' / made['report_id']
    record = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    texts = {e['name']: (folder / 'files' / e['file']).read_bytes().decode('utf-8', 'replace')
             for e in record['attachments'] if e['file'] and not e['name'].endswith(('.png', '.glb'))}
    for name, text in texts.items():
        assert str(Path.home()) not in text and KEY not in text, name
    assert 'did not load' in texts['report.md']
    metadata = json.loads(texts['metadata.json'])
    assert metadata['reported_by'] == {'model': 'claude-opus-5-5', 'effort': 'high', 'via': "MCP (the user's own AI)"}
    assert metadata['refs'] == {'job_id': 'job1', 'import_id': 'clank-1'}
    assert metadata['timings']['job']['seconds'] == 13.0 and metadata['timings']['import_seconds'] == 12.5
    assert metadata['errors']['importer'] == {'error': 'the skeleton could not be read'}
    assert metadata['errors']['import_log_tail'][-1].startswith('rigswap: could not read ')
    assert len(metadata['errors']['import_log_tail']) == problem_report.LOG_LINES
    assert metadata['versions']['python'] and metadata['versions']['model_import_tools']
    assert 'ERROR key' in texts['logs/nucleus.log'] and 'old day' not in texts['logs/nucleus.log']
    assert 'asks' not in json.loads(texts['import/mcp-job.json'])['extra']       # the relay folder is not read


def test_a_token_only_caller_can_neither_read_send_nor_discard(web, network, an_import):
    made = payload(report(web, job_id='job1'))
    base = f"/api/mcp/window/problem-reports/{made['report_id']}"
    assert web.get('/api/mcp/window/problem-reports', headers=TOKEN_ONLY).status_code == 403
    assert web.post(f'{base}/review', json={'include': []}, headers=TOKEN_ONLY).status_code == 403
    assert web.post(f'{base}/discard', headers=TOKEN_ONLY).status_code == 403
    agent = dict(WINDOW, **{'X-Nucleus-Agent': 'mcp'})            # the key with the AI's own mark is not the window
    assert web.post(f'{base}/review', json={'include': []}, headers=agent).status_code == 403
    frozen = web.post(f'{base}/review', json={'include': [], 'app_version': '0.10.0'}, headers=WINDOW).get_json()
    sent = web.post('/api/mex/chat-reports/submit', headers=TOKEN_ONLY,
                    json={'submission_id': frozen['submission_id'], 'approval_hash': frozen['approval_hash'],
                          'consent': True})
    assert sent.status_code == 403
    assert network.posts == [] and network.puts == []
    assert payload(call(web, 'problem_report_status', {'report_id': made['report_id']}))['status'] == 'waiting_for_user'
    assert web.get('/api/mcp/window/problem-reports', headers={}).status_code == 401          # no token at all


# ------------------------------------------------------------------ never a path


@pytest.mark.parametrize('arguments, words', [
    ({'source': 'C:/models/Clank.glb'}, 'Unknown arguments: source'),
    ({'files': ['C:/x.log']}, 'Unknown arguments: files'),
    ({'job_id': r'C:\Users\me\jobs\job1.json'}, 'not a path'),
    ({'job_id': '/home/me/job1'}, 'not a path'),
    ({'import_id': '../clank-1'}, 'not a path'),
    ({'import_id': 'clank-1/../../x'}, 'not a path'),
    ({'chat_id': '~/chats/c1'}, 'not a path'),
    ({'model': r'C:\models\me'}, 'not a path'),
    ({'job_id': r'\\host\share\job1'}, 'network path'),
    ({'chat_id': '//host/share/c'}, 'network path'),
    ({'job_id': 'nope'}, 'No model import job nope'),
    ({'import_id': 'missing-1'}, 'No model import missing-1'),
    ({'chat_id': 'c' * 32}, 'No Randall chat'),
])
def test_paths_and_unknown_ids_are_refused_and_nothing_is_made(web, network, an_import, arguments, words):
    result = report(web, **arguments)
    assert result['isError'] is True and words in result['content'][0]['text'], result
    assert reports_on_disk() == [] and network.posts == []


# ------------------------------------------------------------------ caps and rate limits


def test_the_write_up_and_title_are_capped(web, an_import):
    big = 'x' * (problem_report.MARKDOWN_MAX + 1)
    result = call(web, 'report_problem', {'title': 'Big', 'markdown': big})
    assert result['isError'] and 'at most 204800' in result['content'][0]['text']
    assert call(web, 'report_problem', {'title': 'Big', 'markdown': 'x' * problem_report.MARKDOWN_MAX})['isError'] \
        is False
    result = call(web, 'report_problem', {'title': 't' * (problem_report.TITLE_MAX + 1), 'markdown': 'm'})
    assert result['isError'] and 'title is 121 characters' in result['content'][0]['text']
    assert call(web, 'report_problem', {'title': 'x', 'markdown': '  '})['isError']


def test_waiting_reports_and_reports_per_hour_are_limited(web, network, an_import, monkeypatch):
    made = [payload(report(web))['report_id'] for _ in range(problem_report.PENDING_MAX)]
    refused = report(web)
    assert refused['isError'] and 'already wait for the user' in refused['content'][0]['text']
    assert len(reports_on_disk()) == problem_report.PENDING_MAX
    assert web.post(f'/api/mcp/window/problem-reports/{made[0]}/discard', headers=WINDOW).status_code == 200
    assert report(web)['isError'] is False                     # one went, one more may wait
    monkeypatch.setattr(problem_report, 'PER_HOUR', problem_report.PENDING_MAX + 1)
    web.post(f'/api/mcp/window/problem-reports/{made[1]}/discard', headers=WINDOW)
    refused = report(web)
    assert refused['isError'] and 'made in the last hour' in refused['content'][0]['text']
    assert network.posts == []


def test_attachments_over_the_caps_are_listed_and_never_sent(web, network, an_import, monkeypatch):
    monkeypatch.setattr(problem_report, 'ATTACHMENT_MAX', 1500)             # the 2004-byte model is too large
    made = payload(report(web, job_id='job1'))
    parts = {a['name']: a for a in made['attachments']}
    assert parts['source/Clank.glb']['too_large'] is True and parts['source/Clank.glb']['include'] is False
    folder = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports' / made['report_id']
    assert not any(p.suffix == '.glb' for p in (folder / 'files').iterdir())       # never copied in
    frozen = web.post(f"/api/mcp/window/problem-reports/{made['report_id']}/review", headers=WINDOW,
                      json={'include': ['source/Clank.glb', 'previews/portrait.png'], 'app_version': '0.10.0'})
    assert frozen.status_code == 200
    names = [m['name'] for m in frozen.get_json()['manifest']['members']]
    assert 'source/Clank.glb' not in names and 'previews/portrait.png' in names
    assert {'name': 'source/Clank.glb', 'bytes': 2004, 'why': 'too large'} in frozen.get_json()['manifest']['left_out']

    monkeypatch.setattr(problem_report, 'ATTACHMENT_MAX', 24 * 1024 * 1024)
    monkeypatch.setattr(problem_report, 'TOTAL_MAX', 600)                  # the first few records use it up
    capped = payload(report(web, job_id='job1'))
    kept = [a for a in capped['attachments'] if a['optional'] and not a['too_large']]
    assert sum(a['bytes'] for a in kept) <= 600
    assert any(a['too_large'] for a in capped['attachments'])
    assert not [a for a in capped['attachments'] if not a['optional'] and a['too_large']]      # report.md always goes


# ------------------------------------------------------------------ Send and Discard in the window


def test_send_goes_through_the_chat_reports_own_submit(web, network, an_import):
    made = payload(report(web, job_id='job1', model='claude-opus-5-5', effort='high'))
    listed = web.get('/api/mcp/window/problem-reports', headers=WINDOW).get_json()['pending']
    assert [r['id'] for r in listed] == [made['report_id']]
    shown = listed[0]
    assert shown['title'] == 'Import of Clank failed' and 'did not load' in shown['markdown']
    assert str(Path.home()) not in shown['markdown'] and KEY not in shown['markdown']
    assert all(isinstance(a['bytes'], int) and a['bytes'] > 0 for a in shown['attachments'])
    include = [a['name'] for a in shown['attachments'] if a['optional'] and a['name'] != 'logs/nucleus.log']
    base = f"/api/mcp/window/problem-reports/{made['report_id']}"
    assert web.post(f'{base}/review', json={'include': ['C:/Windows/win.ini'], 'app_version': '0.10.0'},
                    headers=WINDOW).status_code == 400                  # only the report's own parts
    assert web.post(f'{base}/review', json={'include': []}, headers=WINDOW).get_json()['error'] \
        == 'app_version_unknown'
    frozen = web.post(f'{base}/review', json={'include': include, 'app_version': '0.10.0'}, headers=WINDOW).get_json()
    assert network.posts == [] and network.puts == []                    # frozen, not sent
    sent = web.post('/api/mex/chat-reports/submit', headers=WINDOW,
                    json={'submission_id': frozen['submission_id'], 'approval_hash': frozen['approval_hash'],
                          'consent': True})
    assert sent.status_code == 200 and sent.get_json()['state'] == 'sent'

    [posted] = network.posts
    assert posted['url'] == 'https://reports.invalid/bugreport'
    meta = posted['meta']
    assert meta['kind'] == 'chat' and meta['description'] == 'AI problem report: Import of Clank failed'
    assert meta['chat'] == {'surface': 'mcp', 'message_count': None, 'tool_calls': None, 'errors': None,
                            'conversation_id': made['report_id'], 'model': 'claude-opus-5-5'}
    assert meta['app_version'] == '0.10.0' and meta['contact'] == ''
    [put] = network.puts
    assert put['url'] == f"https://reports.invalid/bugreport/{'ab' * 16}/zip"
    files = members(put['data'])
    assert set(files) == {'report.json', 'report.md', 'metadata.json', *include}
    assert files['source/Clank.glb'] == an_import['model'].read_bytes()           # the user ticked it
    assert files['previews/portrait.png'] == PNG
    summary = json.loads(files['report.json'])
    assert summary['left_out'] == [{'name': 'logs/nucleus.log', 'bytes': summary['left_out'][0]['bytes'],
                                    'why': 'not chosen'}]
    for name, data in files.items():
        if not name.endswith(('.png', '.glb')):
            text = data.decode('utf-8')
            assert str(Path.home()) not in text and KEY not in text, name

    status = payload(call(web, 'problem_report_status', {'report_id': made['report_id']}))
    assert status == {'report_id': made['report_id'], 'status': 'sent', 'title': 'Import of Clank failed',
                      'note': 'The user sent it to the Nucleus developer.', 'reference': 'abababab'}
    assert web.get('/api/mcp/window/problem-reports', headers=WINDOW).get_json()['pending'] == []
    again = web.post(f'{base}/review', json={'include': [], 'app_version': '0.10.0'}, headers=WINDOW)
    assert again.status_code == 409 and again.get_json()['error'] == 'report_sent'
    folder = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports' / made['report_id']
    assert not (folder / 'files').exists()                    # its copies are let go once it is sent


def test_discard_sends_nothing_and_deletes_the_parts(web, network, an_import):
    made = payload(report(web, job_id='job1'))
    base = f"/api/mcp/window/problem-reports/{made['report_id']}"
    assert web.post(f'{base}/discard', headers=WINDOW).get_json() == {'ok': True}
    status = payload(call(web, 'problem_report_status', {'report_id': made['report_id'], 'wait_seconds': 0}))
    assert status['status'] == 'discarded' and 'nothing was sent' in status['note']
    folder = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports' / made['report_id']
    assert not (folder / 'files').exists()
    assert web.post(f'{base}/discard', headers=WINDOW).status_code == 409
    assert web.post(f'{base}/review', json={'include': [], 'app_version': '0.10.0'}, headers=WINDOW).status_code == 409
    assert web.post('/api/mcp/window/problem-reports/' + 'f' * 32 + '/discard', headers=WINDOW).status_code == 404
    assert network.posts == [] and network.puts == []


def test_status_waits_for_the_user_and_old_reports_expire(web, network, an_import, monkeypatch):
    import threading
    made = payload(report(web))
    later = threading.Timer(0.6, lambda: web.post(f"/api/mcp/window/problem-reports/{made['report_id']}/discard",
                                                  headers=WINDOW))
    later.start()
    started = time.monotonic()
    status = payload(call(web, 'problem_report_status', {'report_id': made['report_id'], 'wait_seconds': 10}))
    later.join()
    assert status['status'] == 'discarded' and time.monotonic() - started < 8
    for bad in ({'report_id': made['report_id'], 'wait_seconds': 99}, {'report_id': 'x', 'path': 'C:/x'}):
        assert call(web, 'problem_report_status', bad)['isError'] is True
    assert call(web, 'problem_report_status', {'report_id': 'C:/x'})['isError'] is True

    old = payload(report(web))
    monkeypatch.setattr(problem_report, 'PENDING_KEEP', -1)
    status = payload(call(web, 'problem_report_status', {'report_id': old['report_id']}))
    assert status['status'] == 'expired' and 'nothing was sent' in status['note']
    assert web.get('/api/mcp/window/problem-reports', headers=WINDOW).get_json()['pending'] == []
    assert network.posts == []


def test_a_randall_chat_goes_by_its_id_as_its_transcript(web, network, monkeypatch):
    from tests.backend.test_chat_reports import mods_chat
    monkeypatch.setattr(chat_report, '_load_mods_chat', lambda cid: mods_chat() if cid == 'c' * 32 else None)
    monkeypatch.setattr(chat_report, '_model_requests', lambda ids: {})
    monkeypatch.setattr(chat_report, '_randall_config', lambda surface: {'main_model': 'z-ai/glm-5.3-flash'})
    made = payload(report(web, chat_id='c' * 32))
    [transcript] = [a for a in made['attachments'] if a['name'] == 'chat/transcript.md']
    assert transcript['kind'] == 'transcript' and transcript['include'] is True
    folder = Path(config.STORAGE_PATH) / 'assistant' / 'problem_reports' / made['report_id']
    record = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    [entry] = [e for e in record['attachments'] if e['name'] == 'chat/transcript.md']
    text = (folder / 'files' / entry['file']).read_text(encoding='utf-8')
    assert 'Recolor my Fox blue' in text and str(Path.home()) not in text


def test_the_tools_are_listed_with_their_annotations(web):
    from tests.backend.test_app_mcp import rpc
    listed = {t['name']: t for t in rpc(web, 'tools/list').get_json()['result']['tools']}
    assert listed['report_problem']['inputSchema']['required'] == ['title', 'markdown']
    assert listed['report_problem']['annotations']['openWorldHint'] is False      # it sends nothing
    assert listed['problem_report_status']['annotations']['readOnlyHint'] is True
    assert not {'path', 'source', 'file', 'files'} & set(listed['report_problem']['inputSchema']['properties'])
