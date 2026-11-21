""""Report this chat": payload, scrubbing, size cap, frozen two-stage submit.

Nothing here touches the network: the transport is either a fake pair of
callables or `requests` monkeypatched under the report transport that the real
blueprint uses, pointed at example.invalid.
"""
from tests.gated import needs
from tests.paths import REPO
import io
import json
import re
import time
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from randall.reports import chat_report
from randall.routes import chat_reports as chat_reports_module
from shared.diagnostics import bug_report
from randall.reports import report_transport

OPENROUTER_KEY = 'sk-or-v1-' + '0123456789abcdef' * 4
CUSTOM_SECRET = 'zz-custom-provider-credential-9f8e7d6c'
HOME_PATH = str(Path.home() / 'Documents' / 'melee' / 'Fox.dat')


def mods_chat(**extra):
    now = time.time()
    messages = [
        {'role': 'user', 'content': 'Recolor my Fox blue', 'at': now - 60,
         'context': {'page': 'vault', 'selection': [{'id': 1}], 'files': [{'name': 'PlFxNr.dat', 'size': 1234}]}},
        {'id': 'a1', 'role': 'assistant', 'content': 'Done, but the tail stayed red.', 'status': 'done',
         'started_at': now - 58, 'cost_usd': 0.0123, 'cost_parts': {'main': 0.01, 'decision': 0.0023},
         'tokens': {'prompt': 900, 'cached': 100, 'completion': 50}, 'model_rounds': 3,
         'task_id': 'task_1', 'task_revision': 1,
         'routing': {'router': 'jev', 'router_model': 'typesafe/jev-1.13', 'main_model': 'z-ai/glm-5.3-flash',
                     'workflow': 'recolor', 'decision': {'effort': 'low'}},
         'tools': [
             {'id': 't1', 'name': 'skin_lab', 'status': 'done', 'started_at': now - 57, 'elapsed_ms': 812,
              'arguments': {'action': 'recolor', 'path': HOME_PATH},
              'result': {'ok': True, 'image': 'data:image/png;base64,' + 'A' * 5000}},
             {'id': 't2', 'name': 'search_vault', 'status': 'error', 'started_at': now - 50,
              'arguments': {'character': 'Fox'}, 'result': {'error': 'vault locked'}},
         ]},
    ]
    return {'id': 'c' * 32, 'title': 'Recolor my Fox blue', 'messages': messages, 'running': False, **extra}


def tracker_chat():
    return {'id': 7, 'title': 'Worst matchup', 'running': False, 'messages': [
        {'role': 'user', 'content': "Who's my worst matchup?", 'at': 1_700_000_000.0},
        {'role': 'assistant', 'content': 'Marth, 3-9.', 'model': 'minimax', 'at': 1_700_000_020.0,
         'trace': {'mode': 'minimax', 'model': 'minimax/minimax-m3',
                   'rounds': [{'lane': 'fast_lane', 'model': 'google/gemini', 'cost_usd': 0.001},
                              {'lane': 'main', 'model': 'minimax/minimax-m3', 'cost_usd': 0.004}],
                   'tools': [{'id': 'x', 'name': 'corpus_stats', 'arguments': '{"section": "matchups"}',
                              'result': '{"rows": 12}'}]}},
        {'role': 'assistant', 'content': '⚠️ HTTP 500', 'isError': True, 'model': 'glm'},
    ]}


@pytest.fixture
def storage(vault, monkeypatch):
    monkeypatch.setattr(chat_report, '_model_requests', lambda ids: {i: [
        {'role': 'jev', 'requested_model': 'typesafe/jev-1.13', 'resolved_provider': 'typesafe',
         'input_tokens': 120, 'reported_cost_usd': 0.0001, 'status': 'ok'},
        {'role': 'main', 'requested_model': 'z-ai/glm-5.3-flash', 'resolved_provider': 'fireworks',
         'input_tokens': 900, 'output_tokens': 50, 'reported_cost_usd': 0.012, 'status': 'ok'}] for i in ids})
    monkeypatch.setattr(chat_report, '_randall_config', lambda surface: {'main_model': 'z-ai/glm-5.3-flash'}
                        if surface == 'mods' else {'default': 'minimax'})
    return vault


@pytest.fixture
def chats(monkeypatch):
    held = {'mods': mods_chat(), 'tracker': tracker_chat()}
    monkeypatch.setattr(chat_report, '_load_mods_chat', lambda cid: held['mods'] if cid == 'c' * 32 else None)
    monkeypatch.setattr(chat_report, '_load_tracker_chat', lambda cid: held['tracker'] if cid == '7' else None)
    return held


class Transport:
    """A scriptable fake of the worker's two stages."""

    def __init__(self):
        self.creates, self.uploads = [], []
        self.upload_script = []   # exceptions / receipts to return, in order

    def create(self, meta):
        self.creates.append(meta)
        return f'{len(self.creates):032x}'

    def upload(self, remote_id, data):
        self.uploads.append((remote_id, data))
        if self.upload_script:
            item = self.upload_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {'notified': True}


@pytest.fixture
def transport(monkeypatch):
    fake = Transport()
    monkeypatch.setattr(chat_reports_module, '_transport', lambda: (fake.create, fake.upload))
    return fake


@pytest.fixture
def client(storage, chats):
    app = Flask(__name__)
    app.register_blueprint(chat_reports_module.chat_reports_bp)
    return app.test_client()


def review(client, surface='mods', conversation_id='c' * 32, **extra):
    body = {'surface': surface, 'conversation_id': conversation_id, 'app_version': '0.9.1', **extra}
    return client.post('/api/mex/chat-reports/review', json=body)


def send(client, snapshot, **extra):
    body = {'submission_id': snapshot['submission_id'], 'approval_hash': snapshot['approval_hash'],
            'consent': True, **extra}
    return client.post('/api/mex/chat-reports/submit', json=body)


def members(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name).decode('utf-8') for name in archive.namelist()}


@pytest.fixture(autouse=True)
def no_app_version_env(monkeypatch):
    monkeypatch.delenv('NUCLEUS_APP_VERSION', raising=False)


# --- payload ------------------------------------------------------------------

def test_the_bundle_carries_everything_needed_to_debug_the_turn(storage, chats):
    blob, listed, report, conversation = chat_report.build_bundle(
        'mods', chats['mods'], note='It ignored the tail', app_version='0.9.1',
        budget={'source': 'patreon', 'active': True, 'period_budget': 5, 'remaining': 3.2,
                'resets_at': '2026-11-01T00:00:00Z', 'weekly_allowance': 5, 'last_topup_at': 'x'})
    files = members(blob)
    assert [m['name'] for m in listed] == ['report.json', 'conversation.json', 'transcript.md']
    data = json.loads(files['conversation.json'])
    user, reply = data['messages']
    assert data['kind'] == 'chat' and data['surface'] == 'mods'
    assert data['conversation_id'] == 'c' * 32
    assert user['at'] and reply['at'] and user['content'] == 'Recolor my Fox blue'
    assert user['context']['files'] == [{'name': 'PlFxNr.dat', 'bytes': 1234}]
    assert reply['routing']['workflow'] == 'recolor' and reply['routing']['decision']['effort'] == 'low'
    assert reply['cost_usd'] == 0.0123 and reply['tokens']['completion'] == 50
    assert reply['tools'][0]['arguments']['action'] == 'recolor' and reply['tools'][0]['elapsed_ms'] == 812
    assert data['model_requests']['task_1'][1]['resolved_provider'] == 'fireworks'
    assert {'message_index': 1, 'where': 'tool:search_vault', 'error': 'vault locked'} in data['errors']
    assert data['app']['version'] == '0.9.1' and data['app']['platform'] in ('windows', 'mac', 'linux')
    # ai-entitlement's current fields; the retired weekly ones are not carried.
    assert data['budget'] == {'source': 'patreon', 'active': True, 'period_budget': 5, 'remaining': 3.2,
                              'resets_at': '2026-11-01T00:00:00Z'}
    assert json.loads(files['report.json'])['note'] == 'It ignored the tail'
    assert 'It ignored the tail' in files['transcript.md'] and '`skin_lab`' in files['transcript.md']
    # The note is NOT in conversation.json, so its hash names the conversation alone.
    assert 'It ignored the tail' not in files['conversation.json']


def test_inline_images_are_dropped_not_shipped(storage, chats):
    blob, *_ = chat_report.build_bundle('mods', chats['mods'], app_version='0.9.1')
    text = members(blob)['conversation.json']
    assert 'A' * 500 not in text and '[inline data omitted' in text


def test_the_tracker_conversation_keeps_its_route_and_tools(storage, chats):
    blob, _members, report, conversation = chat_report.build_bundle('tracker', chats['tracker'],
                                                                     app_version='0.9.1')
    reply = conversation['messages'][1]
    assert reply['model_key'] == 'minimax'
    assert [r['lane'] for r in reply['trace']['rounds']] == ['fast_lane', 'main']
    assert reply['trace']['tools'][0]['name'] == 'corpus_stats'
    assert conversation['counts'] == {'messages': 3, 'user': 1, 'assistant': 2, 'tool_calls': 1}
    assert conversation['errors'][0]['message_index'] == 2


# --- scrubbing ----------------------------------------------------------------

def test_an_openrouter_key_never_reaches_the_bundle_or_the_meta(client, chats, transport, monkeypatch):
    monkeypatch.setenv('SOME_PROVIDER_API_KEY', CUSTOM_SECRET)
    chat = chats['mods']
    chat['messages'][0]['content'] += f' my key is {OPENROUTER_KEY}'
    chat['messages'][1]['tools'][0]['arguments']['api_key'] = OPENROUTER_KEY
    chat['messages'][1]['tools'][0]['result']['echo'] = f'Authorization: Bearer {OPENROUTER_KEY}'
    chat['messages'][1]['tools'][1]['result']['error'] = f'401 for key {OPENROUTER_KEY} ({CUSTOM_SECRET})'
    chat['messages'][1]['error'] = f'provider said {OPENROUTER_KEY}'
    snapshot = review(client, note=f'here: {OPENROUTER_KEY}', contact=OPENROUTER_KEY,
                      budget={'source': 'patreon', 'api_key': OPENROUTER_KEY, 'tier': OPENROUTER_KEY}).get_json()
    assert snapshot['success'], snapshot
    assert send(client, snapshot).status_code == 200
    (_id, uploaded), = transport.uploads
    everything = json.dumps(transport.creates) + json.dumps(snapshot) + ''.join(members(uploaded).values())
    assert OPENROUTER_KEY not in everything
    assert OPENROUTER_KEY[9:40] not in everything          # not even a fragment of the secret part
    assert CUSTOM_SECRET not in everything
    assert 'sk-or-v1-***' in everything                     # redacted in place, visibly


@pytest.mark.parametrize('padding', ['short', 'row: ' * 2000], ids=['under-cap', 'over-cap'])
def test_credential_keys_are_masked_above_and_below_the_size_cap(storage, chats, padding):
    secret = {'password': 'example-password', 'padding': padding}
    chats['mods']['messages'][1]['tools'][1]['arguments'] = dict(secret)
    chats['mods']['messages'][1]['tools'][1]['result'] = dict(secret)
    chats['mods']['messages'][1]['tools'][0]['result'] = json.dumps(secret)   # JSON text
    trace_tool = chats['tracker']['messages'][1]['trace']['tools'][0]
    trace_tool['arguments'] = json.dumps(secret)
    trace_tool['result'] = json.dumps(secret)
    for surface in ('mods', 'tracker'):
        blob, *_ = chat_report.build_bundle(surface, chats[surface], app_version='0.9.1')
        text = ''.join(members(blob).values())
        assert 'example-password' not in text, (surface, len(padding))
        assert '"password": "***"' in text or '\\"password\\": \\"***\\"' in text


def test_a_secret_is_scrubbed_before_a_cut_could_split_it(storage, chats):
    # The key straddles the cap: cut first, only ~12 of its secret characters
    # survive -- too few for the sk-or pattern -- and they would ship.
    result = 'x' * (chat_report.RESULT_MAX - 22) + f' {OPENROUTER_KEY} ' + 'y' * 5000
    chats['mods']['messages'][1]['tools'][1]['result'] = result
    chats['tracker']['messages'][1]['trace']['tools'][0]['result'] = result
    for surface in ('mods', 'tracker'):
        blob, *_ = chat_report.build_bundle(surface, chats[surface], app_version='0.9.1')
        text = ''.join(members(blob).values())
        assert OPENROUTER_KEY[9:19] not in text, surface


def test_the_home_directory_username_is_masked(storage, chats):
    blob, *_ = chat_report.build_bundle('mods', chats['mods'], app_version='0.9.1')
    text = ''.join(members(blob).values())
    assert str(Path.home()) not in text and str(Path.home()).replace('\\', '/') not in text
    assert 'Fox.dat' in text



@pytest.mark.parametrize('account', ['user', 'User', 'counts'])
def test_a_username_that_is_also_a_word_or_key_does_not_break_the_report(client, monkeypatch, account):
    """preview.8 tester: Windows account "user". The standalone-username mask
    rewrote the report's own "user" keys and every chat role to "<user>", and
    review crashed with KeyError('<user>'). A generic name is not masked as a
    word; a structural key is never rewritten whatever the username is."""
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: Path('C:/Users') / account))
    body = review(client).get_json()
    assert body['success'], body
    assert 'Recolor my Fox blue' in body['transcript']
    assert body['meta']['chat']['message_count'] == 2


# --- size cap -----------------------------------------------------------------

def test_big_tool_output_is_truncated_with_a_marker_to_fit_the_budget(storage, chats):
    chats['mods']['messages'][1]['tools'][1]['result'] = {'rows': ['row %d ' % i * 20 for i in range(20000)]}
    blob, listed, report, conversation = chat_report.build_bundle(
        'mods', chats['mods'], app_version='0.9.1')
    assert report['truncated'] is True                   # the per-result cap alone
    assert '…[truncated ' in members(blob)['conversation.json']
    # A tight budget shrinks the caps further until the bundle fits.
    budget = 9_000
    blob, listed, report, conversation = chat_report.build_bundle(
        'mods', chats['mods'], app_version='0.9.1', byte_budget=budget)
    assert sum(m['bytes'] for m in listed if m['name'] != 'report.json') <= budget
    assert conversation['caps']['result'] < chat_report.RESULT_MAX
    assert report['truncated'] is True
    assert len(conversation['messages']) == 2            # nothing dropped: shrinking was enough


def test_the_default_budget_is_the_bug_report_zip_budget():
    assert chat_report.bundle_budget() == bug_report._BUGREPORT_ZIP_BUDGET


# --- review / submit ----------------------------------------------------------

def test_review_sends_nothing_and_describes_the_contents(client, transport):
    body = review(client).get_json()
    assert body['success'] and transport.creates == [] and transport.uploads == []
    assert [m['name'] for m in body['manifest']['members']] == ['report.json', 'conversation.json', 'transcript.md']
    assert any('tool call' in line for line in body['includes'])
    assert any('API key' in line for line in body['not_included'])
    assert 'Recolor my Fox blue' in body['transcript']
    assert body['meta']['kind'] == 'chat' and body['meta']['chat']['message_count'] == 2


def test_the_preview_shows_no_dollar_cost_and_the_developers_copy_keeps_it(client, transport):
    """Owner's rule (2026-10-07): users never see dollar amounts. The preview leaves out each reply's cost; the
    transcript.md that goes to the developer keeps it, and the list of what is sent names it as usage figures."""
    snapshot = review(client, note='tail stayed red').get_json()
    assert 'Done, but the tail stayed red.' in snapshot['transcript'] and '## What went wrong' in snapshot['transcript']
    assert '$' not in snapshot['transcript'] and '0.0123' not in snapshot['transcript']
    assert 'workflow recolor' in snapshot['transcript']
    assert any('usage figures for debugging' in line for line in snapshot['includes'])
    assert not any(re.search(r'\bcosts?\b|\$', line) for line in snapshot['includes'])
    send(client, snapshot)
    (_id, uploaded), = transport.uploads
    sent = members(uploaded)
    assert '$0.0123' in sent['transcript.md'] and json.loads(sent['conversation.json'])['messages'][1]['cost_usd'] == 0.0123


def test_submit_uploads_exactly_the_frozen_bytes(client, chats, transport):
    snapshot = review(client, note='tail stayed red').get_json()
    chats['mods']['messages'].append({'role': 'user', 'content': 'LATER MESSAGE'})
    resp = send(client, snapshot)
    assert resp.status_code == 200 and resp.get_json()['state'] == 'sent'
    (meta,) = transport.creates
    (remote_id, uploaded), = transport.uploads
    assert meta['kind'] == 'chat' and meta['description'] == 'tail stayed red'
    assert meta['chat']['surface'] == 'mods' and meta['zip_size'] == len(uploaded)
    import hashlib
    assert hashlib.sha256(uploaded).hexdigest() == snapshot['manifest']['bundle']['sha256']
    assert 'LATER MESSAGE' not in ''.join(members(uploaded).values())


def test_an_empty_note_still_files_with_a_description(client, transport):
    send(client, review(client).get_json())
    assert transport.creates[0]['description'] == 'Randall chat report (no note)'


def test_consent_must_be_the_boolean_true(client, transport):
    snapshot = review(client).get_json()
    for value in ('true', 1, None, False):
        resp = send(client, snapshot, consent=value)
        assert resp.status_code == 400
    assert transport.creates == []


def test_a_wrong_hash_is_refused(client, transport):
    snapshot = review(client).get_json()
    resp = send(client, {**snapshot, 'approval_hash': 'f' * 64})
    assert resp.status_code == 409 and resp.get_json()['error'] == 'consent_invalid'
    assert transport.creates == []


def test_a_tampered_bundle_is_not_sent(client, transport):
    snapshot = review(client).get_json()
    row = chat_report.submission(snapshot['submission_id'])
    Path(row['bundle_path']).write_bytes(b'PK changed')
    resp = send(client, snapshot)
    assert resp.status_code == 409 and resp.get_json()['error'] == 'bundle_changed'
    assert transport.creates == [] and transport.uploads == []


def test_a_failed_upload_retries_into_the_same_remote_report(client, transport):
    snapshot = review(client).get_json()
    transport.upload_script = [RuntimeError('connection reset')]
    first = send(client, snapshot)
    assert first.status_code == 502 and first.get_json()['retry'] is True
    second = send(client, snapshot)
    assert second.status_code == 200
    assert len(transport.creates) == 1                              # no second report filed
    assert transport.uploads[0][0] == transport.uploads[1][0]       # same remote id
    assert transport.uploads[0][1] == transport.uploads[1][1]       # same bytes
    third = send(client, snapshot)                                  # a repeated click
    assert third.status_code == 200 and third.get_json()['reason'] == 'already_sent'
    assert len(transport.uploads) == 2


def test_a_lost_acknowledgment_is_not_filed_twice(client, transport):
    snapshot = review(client).get_json()
    # The server stored it, then the reply was lost; the worker answers the
    # retry into the same id from its delivery receipt.
    transport.upload_script = [RuntimeError('read timed out'), {'notified': True}]
    send(client, snapshot)
    resp = send(client, snapshot).get_json()
    assert resp['state'] == 'sent' and resp['confirmed'] is True
    assert len(transport.creates) == 1
    assert transport.uploads[0][0] == transport.uploads[1][0]


def test_a_404_after_an_earlier_upload_is_not_recorded_as_delivered(client, transport):
    snapshot = review(client).get_json()
    # An upload fails; a later retry reaches the expired slot, which the worker
    # deletes, but its 410 is lost; the next retry gets 404. Nothing is stored.
    transport.upload_script = [RuntimeError('connection reset'), RuntimeError('410 reply lost'),
                               chat_report.TransportRefused('unknown report', status=404)]
    assert send(client, snapshot).get_json()['reason'] == 'transport_error'
    assert send(client, snapshot).get_json()['reason'] == 'transport_error'
    third = send(client, snapshot)
    assert third.status_code == 502
    assert third.get_json()['state'] == 'failed' and third.get_json()['reason'] == 'slot_expired'
    row = chat_report.submission(snapshot['submission_id'])
    assert row['state'] == 'failed' and row['receipt'] is None and row['remote_id'] is None
    fourth = send(client, snapshot).get_json()                      # files a NEW report
    assert fourth['state'] == 'sent' and fourth['confirmed'] is True
    assert len(transport.creates) == 2
    assert fourth['id'] == transport.uploads[-1][0] != transport.uploads[0][0]


def test_an_expired_slot_is_recreated_on_the_next_attempt(client, transport):
    snapshot = review(client).get_json()
    transport.upload_script = [chat_report.TransportRefused('slot expired', status=410)]
    assert send(client, snapshot).get_json()['reason'] == 'slot_expired'
    assert send(client, snapshot).status_code == 200
    assert len(transport.creates) == 2


def test_unknown_conversations_and_versions_are_refused(client):
    assert review(client, conversation_id='d' * 32).status_code == 404
    assert review(client, app_version='dev').status_code == 400
    assert review(client, surface='elsewhere').status_code == 400


def test_a_tracker_report_is_prepared_from_its_own_store(client, transport):
    snapshot = review(client, surface='tracker', conversation_id='7').get_json()
    assert snapshot['success'] and snapshot['meta']['chat']['model'] == 'glm'
    send(client, snapshot)
    assert transport.creates[0]['chat']['surface'] == 'tracker'


# --- the real transport helpers, network faked ---------------------------------

class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def wire(storage, chats, monkeypatch):
    monkeypatch.setattr(bug_report, '_BUGREPORT_URL', 'https://example.invalid/bugreport')
    sent = {'post': [], 'put': []}
    replies = {'post': [], 'put': []}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent['post'].append({'url': url, 'meta': json, 'headers': headers})
        return replies['post'].pop(0) if replies['post'] else FakeResponse(200, {'id': 'a' * 32})

    def fake_put(url, data=None, headers=None, timeout=None):
        sent['put'].append({'url': url, 'data': data})
        return replies['put'].pop(0) if replies['put'] else FakeResponse(200, {'ok': True, 'notified': True})

    monkeypatch.setattr(report_transport.requests, 'post', fake_post)
    monkeypatch.setattr(report_transport.requests, 'put', fake_put)
    app = Flask(__name__)
    app.register_blueprint(chat_reports_module.chat_reports_bp)
    return app.test_client(), sent, replies


def test_the_real_transport_is_anonymous_and_two_stage(wire):
    client, sent, _ = wire
    resp = send(client, review(client).get_json())
    assert resp.status_code == 200 and resp.get_json()['notified'] is True
    assert sent['post'][0]['url'] == 'https://example.invalid/bugreport'
    assert sent['post'][0]['headers'] == {}                      # no Discord bearer
    assert sent['put'][0]['url'] == f"https://example.invalid/bugreport/{'a' * 32}/zip"


def test_the_version_gate_passes_through_as_426(wire):
    client, sent, replies = wire
    replies['post'].append(FakeResponse(426, {'error': 'outdated', 'latest': '0.9.4',
                                              'url': 'https://releases.example/x.exe'}))
    resp = send(client, review(client).get_json())
    body = resp.get_json()
    assert resp.status_code == 426 and body['error'] == 'update_required'
    assert body['latest'] == '0.9.4' and body['url'].endswith('x.exe')
    assert sent['put'] == []


def test_rate_limits_pass_through_as_429(wire):
    client, _sent, replies = wire
    replies['post'].append(FakeResponse(429, {'error': 'rate_limited', 'retry_after': 60}))
    resp = send(client, review(client).get_json())
    assert resp.status_code == 429 and resp.get_json()['retry_after'] == 60


# --- what the stores and the engine record for the report ------------------------

@needs('randall')
def test_the_tracker_store_keeps_timestamps_and_the_bounded_trace(tmp_path, monkeypatch):
    from tracker.store import indexer
    from randall.coach import coach_store
    monkeypatch.setattr(indexer, 'DB_PATH', tmp_path / 'nucleome.db')
    chat = tracker_chat()
    huge = {'role': 'assistant', 'content': 'big', 'trace': {'tools': [{'result': 'x' * 70_000}]}}
    chat_id = coach_store.save_chat(None, [*chat['messages'], huge, {'role': 'tool', 'content': 'dropped'}])
    saved = coach_store.get_chat(chat_id)['messages']
    assert saved[0]['at'] == 1_700_000_000.0
    assert saved[1]['trace']['rounds'][1]['lane'] == 'main'
    assert saved[3]['trace'] == {'dropped': 'trace too large to keep'}
    assert len(saved) == 4                               # tool-role rows are still never persisted


# --- what the engine records for the report ------------------------------------

def test_the_engine_records_this_turns_routing_as_plain_data():
    from types import SimpleNamespace
    from shared.aiengine import decisions
    from randall.assistant import engine, main_model
    turn = decisions.Turn(effort='low', vanilla=0.9, cost=0.0002, seconds=0.4)
    workflow = SimpleNamespace(name='recolor', lane=SimpleNamespace(active=True))
    record = engine._routing_record(turn, workflow, SimpleNamespace(direct_call=False))
    assert record['router'] == 'jev' and record['workflow'] == 'recolor'
    assert record['decision'] == {'effort': 'low', 'vanilla': 0.9, 'website': None, 'variant': None,
                                  'cost': 0.0002, 'seconds': 0.4}
    assert record['main_model'] == main_model.MODEL and record['fast_lane_active'] is True
    json.dumps(record)                                   # storable as-is
    # An ordinary turn: no workflow and no lane at all.
    off = engine._routing_record(None, SimpleNamespace(name=None, lane=None), SimpleNamespace(direct_call=False))
    assert off['router'] == 'none' and 'decision' not in off and off['fast_lane_active'] is False


def test_a_preview_build_version_is_accepted():
    """Secret-link test builds are stamped X.Y.Z-preview.N; their reports must go through."""
    assert chat_report.valid_app_version('0.9.0-preview.7') == '0.9.0-preview.7'
    assert chat_report.valid_app_version('0.9.1') == '0.9.1'
    assert chat_report.valid_app_version('0.9.0-') == ''
    assert chat_report.valid_app_version('0.9.0-pre view') == ''
    assert chat_report.valid_app_version('dev') == ''


# --- attached files and model-import artifacts ----------------------------------
# A report said "it couldn't find the textures in the zip" and carried only the
# transcript: the zip was not in it, so nothing could be reproduced.

def _png_bytes(color=(200, 30, 30)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(buffer, format='PNG')
    return buffer.getvalue()


def _zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _raw_file(name, data, extension, origin=None):
    """A stored attachment written by hand (for types register() refuses)."""
    import hashlib
    import uuid
    from shared import mod_files
    file_id = uuid.uuid4().hex
    directory = mod_files.root() / file_id
    directory.mkdir()
    (directory / 'content').write_bytes(data)
    info = {'file_id': file_id, 'name': name, 'size': len(data), 'extension': extension,
            'sha256': hashlib.sha256(data).hexdigest(), 'origin': origin, 'edited': False}
    (directory / 'metadata.json').write_text(json.dumps(info), encoding='utf-8')
    return mod_files.describe(info)


class ImportChat:
    """A mods conversation where the user attached a model ZIP and Randall fitted it."""

    def __init__(self):
        from shared import mod_files
        self.zip_data = _zip_bytes({'Rapunzel/model.dae': '<COLLADA>' + 'x' * 4000 + '</COLLADA>',
                                    'Rapunzel/tex/hair.png': 'not really a png'})
        self.zip = mod_files.register(self.zip_data, 'rapunzel.zip')
        self.pose_png = mod_files.register(_png_bytes(), 'Zelda poses 1-3 - offline.png')
        self.placement_png = mod_files.register(_png_bytes((0, 90, 200)), 'Zelda bind placement over target.png')
        models = mod_files.root().parent / 'models'
        models.mkdir(exist_ok=True)
        work = models / ('c' * 32)
        work.mkdir()
        rigged = work / 'rigged.smd'
        rigged.write_text('version 1\n', encoding='utf-8')
        Path(str(rigged) + '.fit.json').write_text(json.dumps({
            'corner_source_bones': [1, 2, 3], 'provider': {'api_key': OPENROUTER_KEY},
            'source': HOME_PATH, 'note': f'fitted with {OPENROUTER_KEY}'}), encoding='utf-8')
        (work / 'assistant-result.json').write_text(json.dumps({'operation': 'fit', 'path': HOME_PATH}),
                                                    encoding='utf-8')
        (work / 'fit.log').write_text(f'textures missing under {HOME_PATH}\n', encoding='utf-8')
        record = {'candidate_id': 'a' * 32, 'source_file_id': self.zip['file_id'], 'directory': str(work),
                  'candidate': {'character': 'Zelda', 'rigged_smd': str(rigged),
                                # Real records key their asset hashes by absolute path.
                                'asset_hashes': {HOME_PATH: 'f' * 64}},
                  'files': [self.pose_png, self.placement_png], 'source_preview': [],
                  'fit_context': {'alignment_id': 'b' * 32},
                  'review': {'record': {'severe': 1}}, 'export': {'native_validation': {'status': 'ok'}}}
        (models / ('a' * 32 + '.json')).write_text(json.dumps(record), encoding='utf-8')
        (models / ('b' * 32 + '.alignment.json')).write_text(json.dumps({'spec': {'up_axis': 'y'}}),
                                                             encoding='utf-8')
        now = time.time()
        self.chat = {'id': 'c' * 32, 'title': 'Import Rapunzel', 'running': False, 'messages': [
            {'role': 'user', 'content': 'Put Rapunzel on Zelda', 'at': now - 60,
             'context': {'page': 'vault', 'files': [self.zip]}},
            {'id': 'a1', 'role': 'assistant', 'content': "I couldn't find the textures in the zip.",
             'status': 'done', 'started_at': now - 58, 'tools': [
                 {'id': 't1', 'name': 'model_fit', 'status': 'done',
                  'arguments': {'file_id': self.zip['file_id'], 'characters': ['Zelda']},
                  'result': {'candidates': [{'candidate_id': 'a' * 32,
                                             'files': [self.pose_png, self.placement_png]}],
                             'alignment_id': 'b' * 32,
                             'files': [self.pose_png, self.placement_png]}}]},
        ]}

    def attach(self, *files):
        self.chat['messages'][0]['context']['files'] += list(files)


@pytest.fixture
def import_chat(storage, chats):
    held = ImportChat()
    chats['mods'] = held.chat
    return held


def _unzip(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _frozen(snapshot):
    return Path(chat_report.submission(snapshot['submission_id'])['bundle_path']).read_bytes()


def test_attached_files_and_import_artifacts_are_included_and_listed(client, import_chat, transport):
    snapshot = review(client, include_files=True).get_json()
    assert snapshot['success'], snapshot
    files = _unzip(_frozen(snapshot))
    zip_id, pose_id = import_chat.zip['file_id'], import_chat.pose_png['file_id']
    # The user's ZIP, byte for byte: the thing the developer needs to reproduce it.
    assert files[f'files/attached/{zip_id[:8]}-rapunzel.zip'] == import_chat.zip_data
    assert f'files/images/{pose_id[:8]}-Zelda poses 1-3 - offline.png' in files
    for record in (f'candidate-{"a" * 32}.json', f'candidate-{"a" * 32}.fit.json',
                   f'fit-{"a" * 32}.assistant-result.json', f'fit-{"a" * 32}.log',
                   f'alignment-{"b" * 32}.json'):
        assert f'files/records/{record}' in files, record
    manifest = json.loads(files['files/manifest.json'])
    assert manifest['include_files'] is True
    attached = next(f for f in manifest['files'] if f['name'] == 'rapunzel.zip')
    assert attached['status'] == 'included' and attached['bytes'] == len(import_chat.zip_data)
    # The review lists every member it froze, with sizes, and says so in words.
    listed = {m['name']: m['bytes'] for m in snapshot['manifest']['members']}
    assert listed[f'files/attached/{zip_id[:8]}-rapunzel.zip'] == len(import_chat.zip_data)
    assert any(line.startswith('The file(s) you attached, exactly as they are: rapunzel.zip (')
               for line in snapshot['includes'])
    assert any(line.startswith('2 preview picture(s) Randall made of your model') for line in snapshot['includes'])
    assert snapshot['files']['offer_count'] == 3
    assert snapshot['files']['send_bytes'] > len(import_chat.zip_data)
    # And that is what is uploaded.
    assert send(client, snapshot).status_code == 200
    (_id, uploaded), = transport.uploads
    assert _unzip(uploaded)[f'files/attached/{zip_id[:8]}-rapunzel.zip'] == import_chat.zip_data


def test_the_budget_lists_files_that_do_not_fit_instead_of_sending_them(storage, import_chat):
    import os
    from shared import mod_files
    big_data = _zip_bytes({f'outfit{i}/model.dae': os.urandom(300_000) for i in range(4)})
    big = mod_files.register(big_data, 'kh3-rapunzel-all-outfits.zip')
    small = mod_files.register(b'\x00' * 64 + b'small dat' * 10, 'PlZdNr-edit.dat')
    import_chat.attach(big, small)
    budget = len(big_data) // 2
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True, files_budget=budget)
    assert len(blob) <= budget
    names = [m['name'] for m in listed]
    assert f"files/attached/{small['file_id'][:8]}-PlZdNr-edit.dat" in names       # smallest first
    assert f"files/attached/{import_chat.zip['file_id'][:8]}-rapunzel.zip" in names
    assert not any('kh3-rapunzel' in n for n in names)
    manifest = json.loads(_unzip(blob)['files/manifest.json'])
    entry = next(f for f in manifest['files'] if f['name'] == 'kh3-rapunzel-all-outfits.zip')
    assert entry['status'] == 'too_large' and entry['bytes'] == len(big_data)
    assert entry['sha256'] == big['sha256']
    assert [m['name'] for m in entry['archive']['members']] == [f'outfit{i}/model.dae' for i in range(4)]
    size = f'{len(big_data) / (1024 * 1024):.1f} MB'
    assert (f'Too large to include: kh3-rapunzel-all-outfits.zip ({size}). '
            'Only its name, size and list of contents are sent.') in chat_report.describe_files(
                report['_files']['summary'])


def test_the_default_budget_keeps_the_zip_under_the_worker_cap():
    worker = REPO / 'services' / 'cloudflare' / 'bugreport-worker' / 'src' / 'index.js'
    assert 'intVar(env.MAX_ZIP_BYTES, 64 * 1024 * 1024)' in worker.read_text(encoding='utf-8')
    assert chat_report.report_files.FILES_BUDGET <= 45 * 1024 * 1024


def test_scrubbing_still_applies_to_the_text_artifacts(storage, import_chat):
    blob, *_ = chat_report.build_bundle('mods', import_chat.chat, app_version='0.9.1', include_files=True)
    files = _unzip(blob)
    text = b''.join(data for name, data in files.items()
                    if name.startswith('files/records/') or name == 'files/manifest.json').decode('utf-8')
    assert OPENROUTER_KEY not in text and OPENROUTER_KEY[9:40] not in text
    assert str(Path.home()) not in text and str(Path.home()).replace('\\', '/') not in text
    record = json.loads(files[f'files/records/candidate-{"a" * 32}.json'])
    assert list(record['candidate']['asset_hashes'].values()) == ['f' * 64]
    fit = json.loads(files[f'files/records/candidate-{"a" * 32}.fit.json'])
    assert fit['provider']['api_key'] == '***'
    assert fit['corner_source_bones'] == [1, 2, 3]            # the data itself is intact
    assert 'textures missing under' in files[f'files/records/fit-{"a" * 32}.log'].decode('utf-8')


def test_turning_the_files_off_leaves_them_out_and_changes_the_approval(client, import_chat):
    on = review(client, include_files=True).get_json()
    off = review(client, include_files=False).get_json()
    default = review(client).get_json()                    # no field: nothing attached goes
    assert on['approval_hash'] != off['approval_hash']
    assert on['files_sha256'] != off['files_sha256']
    assert on['conversation_sha256'] == off['conversation_sha256']
    for snapshot in (off, default):
        names = [m['name'] for m in snapshot['manifest']['members']]
        assert not any(n.startswith(('files/attached/', 'files/images/')) for n in names)
        assert any(n.startswith('files/records/') for n in names)          # records still go
        assert snapshot['manifest']['include_files'] is False
        assert any(line.startswith('You turned off your attached files') for line in snapshot['includes'])
        assert import_chat.zip_data not in _frozen(snapshot)
    assert default['approval_hash'] != on['approval_hash']
    # A non-boolean is not a yes.
    assert review(client, include_files='true').get_json()['manifest']['include_files'] is False


def test_vanilla_vault_and_out_of_storage_files_are_never_included(storage, import_chat, tmp_path, monkeypatch):
    from core import config
    from shared import mod_files
    vanilla_dir = tmp_path / 'vanilla'
    (vanilla_dir / 'Fox' / 'PlFxNr').mkdir(parents=True)
    vanilla_bytes = b'VANILLA-FOX-DAT' * 500
    (vanilla_dir / 'Fox' / 'PlFxNr' / 'PlFxNr.dat').write_bytes(vanilla_bytes)
    monkeypatch.setattr(config, 'VANILLA_ASSETS_DIR', vanilla_dir, raising=False)
    # Randall's copy of a vanilla costume, a vault item, a user attachment that
    # is byte-for-byte the vanilla DAT, a disc image, a draft DAT export.
    opened = mod_files.register(vanilla_bytes, 'PlFxNr.dat',
                                origin={'character': 'Fox', 'vanilla_color': 'Nr', 'costume_code': 'PlFxNr'})
    vault_item = mod_files.register(b'VAULT-ZIP' * 50, 'blue-fox.zip',
                                    origin={'character': 'Fox', 'skin_id': 'fox-blue', 'costume_code': 'PlFxBu'})
    renamed = mod_files.register(vanilla_bytes, 'my fox.dat')
    iso = _raw_file('Melee.iso', b'GALE01' + b'\x00' * 1000, '.iso')
    export = mod_files.register(b'EXPORTED-DAT' * 40, 'PlZdNr.dat', edited=True,
                                origin={'character': 'Zelda', 'vanilla_color': 'Nr',
                                        'model_candidate_id': 'a' * 32})
    import_chat.attach(renamed, iso, vault_item)
    import_chat.chat['messages'][1]['tools'].append(
        {'id': 't2', 'name': 'model_candidate', 'status': 'done',
         'arguments': {'candidate_id': 'a' * 32, 'action': 'export'},
         'result': {'files': [export, opened]}})
    # A candidate whose record points its working files at a rig kit outside storage.
    outside = tmp_path / 'rigkits' / 'Zelda'
    outside.mkdir(parents=True)
    (outside / 'rig.smd.fit.json').write_text('{"rig": "vanilla"}', encoding='utf-8')
    models = mod_files.root().parent / 'models'
    (models / ('d' * 32 + '.json')).write_text(json.dumps({
        'candidate_id': 'd' * 32, 'directory': str(outside),
        'candidate': {'rigged_smd': str(outside / 'rig.smd')}}), encoding='utf-8')
    import_chat.chat['messages'][1]['tools'][0]['result']['candidates'].append({'candidate_id': 'd' * 32})
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True)
    unpacked = _unzip(blob)
    for secret in (vanilla_bytes, b'VAULT-ZIP' * 50, b'GALE01', b'EXPORTED-DAT' * 40, b'"rig": "vanilla"'):
        assert secret not in blob and all(secret not in data for data in unpacked.values())
    names = [m['name'] for m in listed]
    assert not any(n.endswith(('.iso', 'PlFxNr.dat', 'my fox.dat', 'blue-fox.zip', 'PlZdNr.dat')) for n in names)
    assert f"files/attached/{import_chat.zip['file_id'][:8]}-rapunzel.zip" in names   # the real upload still goes
    left_out = {e['name']: e['reason'] for e in report['_files']['summary']['excluded']}
    assert left_out['PlFxNr.dat'] == 'a game file from your ISO'
    assert left_out['my fox.dat'] == 'a game file from your ISO'
    assert left_out['Melee.iso'] == 'a game disc image'
    assert left_out['blue-fox.zip'] == 'from your vault'
    assert left_out['PlZdNr.dat'] == 'a game file from your ISO'
    assert left_out[f'candidate-{"d" * 32} working folder'] == "outside the app's own folder"
    assert 'Never sent: Melee.iso (a game disc image).' in chat_report.describe_files(report['_files']['summary'])


def test_a_tracker_report_has_no_files_and_is_unchanged(client, transport):
    body = review(client, surface='tracker', conversation_id='7', include_files=True).get_json()
    assert [m['name'] for m in body['manifest']['members']] == ['report.json', 'conversation.json', 'transcript.md']
    assert body['files']['offer_count'] == 0


def test_old_frozen_bundles_are_pruned(client, monkeypatch):
    first = review(client).get_json()
    path = Path(chat_report.submission(first['submission_id'])['bundle_path'])
    assert path.is_file()
    later = time.time() + chat_report.UNSENT_KEEP_SECONDS + 60
    monkeypatch.setattr(chat_report.time, 'time', lambda: later)
    review(client)
    assert not path.exists()


# --- review fixes (Astra, on ca5691b2) -------------------------------------------

@pytest.fixture
def game_files(storage, tmp_path, monkeypatch):
    """Reference game files: an extracted vanilla costume and a rig kit."""
    from core import config
    vanilla = tmp_path / 'vanilla'
    (vanilla / 'Fox' / 'PlFxNr').mkdir(parents=True)
    fox = b'VANILLA-FOX-DAT' * 500
    (vanilla / 'Fox' / 'PlFxNr' / 'PlFxNr.dat').write_bytes(fox)
    monkeypatch.setattr(config, 'VANILLA_ASSETS_DIR', vanilla, raising=False)
    kit_dir = Path(config.STORAGE_PATH) / 'modellab' / 'rigkits' / 'Zelda'
    kit_dir.mkdir(parents=True)
    kit = b'version 1\nnodes\n0 "JOBJ_0" -1\nend\n' * 40
    (kit_dir / 'rigkit.smd').write_bytes(kit)
    return {'fox': fox, 'kit': kit}


def _names(listed):
    return [m['name'] for m in listed]


def test_a_zip_holding_game_files_or_a_disc_image_is_not_sent(import_chat, game_files):
    from shared import mod_files
    hidden = mod_files.register(_zip_bytes({'model.dae': '<COLLADA/>', 'misc/body.bin': game_files['fox']}),
                                'hidden-fox.zip')
    nested = mod_files.register(_zip_bytes({'inner.zip': _zip_bytes({'a/PlFxNr.dat': game_files['fox']})}),
                                'nested.zip')
    disc = mod_files.register(_zip_bytes({'model.dae': '<COLLADA/>', 'GALE01.iso': b'GALE01' + b'\x00' * 100}),
                              'with-disc.zip')
    import_chat.attach(hidden, nested, disc)
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True)
    assert game_files['fox'] not in blob and b'GALE01' not in blob
    assert not any(n.endswith(('hidden-fox.zip', 'nested.zip', 'with-disc.zip')) for n in _names(listed))
    left_out = {e['name']: e['reason'] for e in report['_files']['summary']['excluded']}
    for name in ('hidden-fox.zip', 'nested.zip', 'with-disc.zip'):
        assert left_out[name] == 'contains game files from your ISO', name
    assert f"files/attached/{import_chat.zip['file_id'][:8]}-rapunzel.zip" in _names(listed)
    assert 'Never sent: hidden-fox.zip (contains game files from your ISO).' in \
        chat_report.describe_files(report['_files']['summary'])


def test_a_game_file_is_caught_under_any_name_and_extension(import_chat, game_files):
    from shared import mod_files
    as_smd = mod_files.register(game_files['fox'], 'body.smd')
    as_png_name = _raw_file('texture.png', game_files['fox'], '.png')
    kit_copy = mod_files.register(game_files['kit'], 'my zelda rig.smd')
    import_chat.attach(as_smd, as_png_name, kit_copy)
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True)
    assert game_files['fox'] not in blob and game_files['kit'] not in blob
    left_out = {e['name']: e['reason'] for e in report['_files']['summary']['excluded']}
    assert left_out == {'body.smd': 'a game file from your ISO', 'texture.png': 'a game file from your ISO',
                        'my zelda rig.smd': 'a game file from your ISO'}


def test_an_allowed_root_or_file_that_resolves_outside_storage_contributes_nothing(
        import_chat, tmp_path, monkeypatch):
    from randall.reports import chat_report_files
    from shared import mod_files
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    models = mod_files.root().parent / 'models'
    real_resolve = Path.resolve

    def junction_at_models(path):
        # storage/assistant/models is a junction to a folder outside storage.
        resolved = real_resolve(Path(path))
        if resolved == real_resolve(models) or resolved.is_relative_to(real_resolve(models)):
            return elsewhere / resolved.relative_to(real_resolve(models))
        return resolved
    monkeypatch.setattr(chat_report_files, '_resolve', junction_at_models)
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True)
    assert not any(n.startswith('files/records/') for n in _names(listed))
    assert b'corner_source_bones' not in b''.join(_unzip(blob).values())
    assert {'name': 'model import records', 'reason': "outside the app's own folder"} in \
        report['_files']['summary']['excluded']
    # One attachment whose content is a link out of storage is left out too.
    content = mod_files.root() / import_chat.zip['file_id'] / 'content'

    def junction_at_one_file(path):
        resolved = real_resolve(Path(path))
        return elsewhere / 'content' if resolved == real_resolve(content) else resolved
    monkeypatch.setattr(chat_report_files, '_resolve', junction_at_one_file)
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True)
    assert import_chat.zip_data not in blob
    assert {'name': 'rapunzel.zip', 'reason': "outside the app's own folder"} in \
        report['_files']['summary']['excluded']


def _rewrite_same_size_and_time(path, data):
    import os
    stat = path.stat()
    assert len(data) == stat.st_size
    path.write_bytes(data)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def test_send_reuses_the_previewed_files_byte_for_byte(client, import_chat, transport):
    from shared import mod_files
    preview = review(client, include_files=True).get_json()
    content = mod_files.root() / import_chat.zip['file_id'] / 'content'
    swapped = bytes(b ^ 0xFF for b in import_chat.zip_data)
    _rewrite_same_size_and_time(content, swapped)            # the size/mtime hash cache cannot see this
    zip_member = f"files/attached/{import_chat.zip['file_id'][:8]}-rapunzel.zip"
    # Send re-freezes against the preview: the files part is the previewed bytes.
    again = review(client, include_files=True, note='it broke', base_submission=preview['submission_id']).get_json()
    assert again['success'], again
    assert again['files_sha256'] == preview['files_sha256']
    assert _unzip(_frozen(again))[zip_member] == import_chat.zip_data
    assert send(client, again).status_code == 200
    (_id, uploaded), = transport.uploads
    assert _unzip(uploaded)[zip_member] == import_chat.zip_data and swapped not in uploaded


def test_a_fresh_freeze_hashes_what_it_writes_so_changed_bytes_change_the_files_hash(client, import_chat):
    from shared import mod_files
    preview = review(client, include_files=True).get_json()
    content = mod_files.root() / import_chat.zip['file_id'] / 'content'
    swapped = bytes(b ^ 0xFF for b in import_chat.zip_data)
    _rewrite_same_size_and_time(content, swapped)
    fresh = review(client, include_files=True).get_json()
    assert fresh['success'], fresh
    assert fresh['files_sha256'] != preview['files_sha256']   # the frontend stops and shows this preview
    zip_member = f"files/attached/{import_chat.zip['file_id'][:8]}-rapunzel.zip"
    import hashlib
    written = next(m for m in fresh['manifest']['members'] if m['name'] == zip_member)
    assert written['sha256'] == hashlib.sha256(swapped).hexdigest()
    assert _unzip(_frozen(fresh))[zip_member] == swapped


def test_a_previewed_freeze_that_cannot_be_reused_asks_for_a_new_review(client, import_chat):
    preview = review(client, include_files=True).get_json()
    Path(chat_report.submission(preview['submission_id'])['bundle_path']).unlink()
    resp = review(client, include_files=True, base_submission=preview['submission_id'])
    assert resp.status_code == 409 and resp.get_json()['error'] == 'review_again'
    # Nor across the toggle: a preview with files on is not an approval for off.
    other = review(client, include_files=True).get_json()
    resp = review(client, include_files=False, base_submission=other['submission_id'])
    assert resp.status_code == 409 and resp.get_json()['error'] == 'review_again'


def test_the_manifest_is_capped_and_the_bundle_never_exceeds_the_budget(storage, import_chat, monkeypatch):
    import os
    from shared import mod_files
    names = {f'{os.urandom(150).hex()}/{i}.dae': b'x' for i in range(1000)}
    names['zz-padding.bin'] = os.urandom(200_000)
    big_data = _zip_bytes(names)
    big = _raw_file('huge-listing.zip', big_data, '.zip')
    import_chat.attach(big)
    small_budget = len(big_data) // 2
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True, files_budget=small_budget)
    manifest = json.loads(_unzip(blob)['files/manifest.json'])
    entry = next(f for f in manifest['files'] if f['name'] == 'huge-listing.zip')
    assert entry['status'] == 'too_large'
    assert len(entry['archive']['members']) == 200 and entry['archive']['more'] == '+801 more'
    assert all(len(m['name']) <= 201 for m in entry['archive']['members'])
    # With room for the conversation but not for that list: no files part at all.
    with monkeypatch.context() as patched:
        patched.setattr(chat_report.report_files, 'collect', lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
        bare, *_ = chat_report.build_bundle('mods', import_chat.chat, app_version='0.9.1', include_files=False)
    budget = len(bare) + 3000
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True, files_budget=budget)
    assert len(blob) <= budget
    assert not any(n.startswith('files/') for n in _names(listed))
    assert report['_files']['dropped'] is True
    assert json.loads(_unzip(blob)['report.json'])['files']['dropped']
    assert chat_report.describe_files(report['_files']['summary'], dropped=True) == [
        'The list of files in this chat was too long to send, so only the conversation is sent.']


def test_lowercase_home_paths_and_other_drive_paths_are_masked_in_records(storage, import_chat):
    from shared import mod_files
    models = mod_files.root().parent / 'models'
    pointer = models / ('a' * 32 + '.json')
    record = json.loads(pointer.read_text(encoding='utf-8'))
    record['candidate']['asset_hashes'] = {'C:\\users\\Alice\\Documents\\model\\rigged.smd': 'e' * 64}
    record['candidate']['texture_source'] = 'D:\\Games\\Melee Mods\\textures\\hair.png'
    record['candidate']['posix'] = '/HOME/alice/models/x.smd'
    pointer.write_text(json.dumps(record), encoding='utf-8')
    blob, *_ = chat_report.build_bundle('mods', import_chat.chat, app_version='0.9.1', include_files=True)
    text = _unzip(blob)[f'files/records/candidate-{"a" * 32}.json'].decode('utf-8')
    assert 'Alice' not in text and 'alice' not in text and 'Melee Mods' not in text
    assert '<path>/rigged.smd' in text and '<path>/hair.png' in text
    assert 'x.smd' in text
    # The shared scrubber too, for every report and log.
    assert 'Alice' not in bug_report._redact_log_text('opened c:\\users\\Alice\\Desktop\\a.dat')
    assert 'alice' not in bug_report._redact_log_text('/Users/alice/a.dat and /HOME/alice/b.dat').lower().replace('<user>', '')


def test_malformed_records_and_attachments_never_fail_the_review(client, import_chat, monkeypatch):
    from shared import mod_files
    models = mod_files.root().parent / 'models'
    (models / ('e' * 32 + '.json')).write_text('[1, 2]', encoding='utf-8')
    (models / ('f' * 32 + '.json')).write_text(json.dumps(
        {'candidate_id': 'f' * 32, 'directory': 7, 'candidate': 'oops', 'fit_context': 'x', 'files': 'y'}),
        encoding='utf-8')
    broken = _raw_file('broken.zip', b'PK', '.zip')
    (mod_files.root() / broken['file_id'] / 'metadata.json').write_text('[]', encoding='utf-8')
    import_chat.attach(broken)
    import_chat.chat['messages'][1]['tools'][0]['result']['candidates'] += [
        {'candidate_id': 'e' * 32}, {'candidate_id': 'f' * 32}]
    resp = review(client, include_files=True)
    body = resp.get_json()
    assert resp.status_code == 200 and body['success'], body
    manifest = json.loads(_unzip(_frozen(body))['files/manifest.json'])
    unavailable = {e['name'] for e in manifest['unavailable']}
    assert {f'candidate-{"e" * 32}', 'broken.zip'} <= unavailable
    assert f"files/attached/{import_chat.zip['file_id'][:8]}-rapunzel.zip" in _unzip(_frozen(body))
    # A collection that fails outright: the conversation alone still goes when files are off...
    monkeypatch.setattr(chat_report.report_files, 'collect', lambda *a, **k: (_ for _ in ()).throw(KeyError('x')))
    off = review(client, include_files=False)
    assert off.status_code == 200
    assert [m['name'] for m in off.get_json()['manifest']['members']] == \
        ['report.json', 'conversation.json', 'transcript.md']
    # ...and with files on it says so plainly instead of a 500.
    on = review(client, include_files=True)
    assert on.status_code == 400 and on.get_json()['error'] == 'files_unavailable'


# --- second review (Astra, on 5cc9475c) ------------------------------------------

def test_send_streams_the_previewed_files_instead_of_holding_them(client, import_chat):
    import tracemalloc
    line = b'0 0.000000 0.000000 0.000000 0.000000 0.000000 0.000000 1 0 1.0\n'
    data = b'version 1\n' + line * ((48 * 1024 * 1024) // len(line))
    body = _raw_file('body.smd', data, '.smd')
    size = len(data)
    del data
    import_chat.attach(body)
    preview = review(client, include_files=True).get_json()
    member = f"files/attached/{body['file_id'][:8]}-body.smd"
    assert any(m['name'] == member for m in preview['manifest']['members'])
    tracemalloc.start()
    try:
        again = review(client, include_files=True, note='it broke',
                       base_submission=preview['submission_id']).get_json()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert again['success'], again
    assert again['files_sha256'] == preview['files_sha256']
    assert peak < 16 * 1024 * 1024, f'peak {peak / 1e6:.1f} MB for a {size / 1e6:.1f} MB member'
    with zipfile.ZipFile(Path(chat_report.submission(again['submission_id'])['bundle_path'])) as archive:
        assert archive.getinfo(member).file_size == size


def test_with_the_toggle_off_nothing_is_screened_for_game_files(import_chat, game_files, monkeypatch):
    from randall.reports import chat_report_files
    from shared import mod_files
    calls = []
    for name in ('archive_reason', 'file_is_game_file'):
        original = getattr(chat_report_files.GameFiles, name)
        monkeypatch.setattr(chat_report_files.GameFiles, name,
                            lambda self, *a, _name=name, _original=original, **k: (calls.append(_name),
                                                                                   _original(self, *a, **k))[1])
    zipped = mod_files.register(_zip_bytes({f'm{i}.dae': b'<COLLADA/>' for i in range(20)}), 'many.zip')
    import_chat.attach(zipped)
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=False)
    assert calls == []                                    # not sent, so not opened
    assert not any(n.startswith('files/attached/') for n in _names(listed))
    chat_report.build_bundle('mods', import_chat.chat, app_version='0.9.1', include_files=True)
    assert 'archive_reason' in calls                      # sent: screened


def test_each_member_is_hashed_once_against_a_cached_reference_set(import_chat, storage, tmp_path, monkeypatch):
    from core import config
    from randall.reports import chat_report_files
    from shared import mod_files
    size = 4096
    vanilla = tmp_path / 'vanilla-bucket'
    for i in range(30):                                   # thirty reference files of one size
        folder = vanilla / 'Fox' / f'PlFx{i:02d}'
        folder.mkdir(parents=True)
        (folder / f'PlFx{i:02d}.dat').write_bytes(bytes([i]) * size)
    monkeypatch.setattr(config, 'VANILLA_ASSETS_DIR', vanilla, raising=False)
    members = {f'part{i}.dat': bytes([200 + i % 50]) + b'm' * (size - 1) for i in range(40)}
    zipped = mod_files.register(_zip_bytes(members), 'forty-parts.zip')
    import_chat.attach(zipped)
    counts = {'file': 0, 'stream': 0}
    original_file, original_stream = chat_report_files._sha256_file, chat_report_files._sha256_stream

    def count_file(path):
        counts['file'] += 1
        return original_file(path)

    def count_stream(stream):
        counts['stream'] += 1
        return original_stream(stream)
    monkeypatch.setattr(chat_report_files, '_sha256_file', count_file)
    monkeypatch.setattr(chat_report_files, '_sha256_stream', count_stream)
    blob, listed, report, _conversation = chat_report.build_bundle(
        'mods', import_chat.chat, app_version='0.9.1', include_files=True)
    assert f"files/attached/{zipped['file_id'][:8]}-forty-parts.zip" in _names(listed)
    # 30 reference hashes + 40 member hashes, plus a handful for the files planned.
    assert counts['file'] + counts['stream'] <= 30 + 40 + 10, counts


def test_a_new_attachment_after_the_preview_is_not_left_out_of_the_send(client, import_chat, transport):
    from shared import mod_files
    preview = review(client, include_files=True).get_json()
    second = mod_files.register(b'version 1\nnodes\nend\n' * 10, 'b.smd')
    import_chat.chat['messages'].append({'role': 'user', 'content': 'and this one', 'at': time.time(),
                                         'context': {'files': [second]}})
    # Send against the old preview: its files part no longer matches this chat.
    stale = review(client, include_files=True, base_submission=preview['submission_id'])
    assert stale.status_code == 409 and stale.get_json()['error'] == 'review_again'
    fresh = review(client, include_files=True).get_json()
    member = f"files/attached/{second['file_id'][:8]}-b.smd"
    assert any(m['name'] == member for m in fresh['manifest']['members'])
    again = review(client, include_files=True, base_submission=fresh['submission_id']).get_json()
    assert again['success'] and any(m['name'] == member for m in again['manifest']['members'])
    assert send(client, again).status_code == 200
    (_id, uploaded), = transport.uploads
    assert member in _unzip(uploaded)


def test_unc_and_posix_paths_are_cut_to_the_file_name_in_records(storage, import_chat):
    from shared import mod_files
    pointer = mod_files.root().parent / 'models' / ('a' * 32 + '.json')
    record = json.loads(pointer.read_text(encoding='utf-8'))
    record['candidate']['unc'] = '\\\\nas\\Users\\Alice\\secret\\body.smd'
    record['candidate']['posix'] = '/mnt/team/Alice/private/model.dae'
    record['candidate']['unc_forward'] = '//nas/share/Alice/secret/arm.smd'
    record['candidate']['url'] = 'https://models.example/a/b/c.png'
    pointer.write_text(json.dumps(record), encoding='utf-8')
    blob, *_ = chat_report.build_bundle('mods', import_chat.chat, app_version='0.9.1', include_files=True)
    candidate = json.loads(_unzip(blob)[f'files/records/candidate-{"a" * 32}.json'])['candidate']
    assert candidate['unc'] == '<path>/body.smd'
    assert candidate['posix'] == '<path>/model.dae'
    assert candidate['unc_forward'] == '<path>/arm.smd'
    assert candidate['url'] == 'https://models.example/a/b/c.png'     # a URL is not a path
    text = json.dumps(candidate)
    for word in ('Alice', 'secret', 'private', 'team', 'nas'):
        assert word not in text, word


def test_a_reports_tool_results_are_what_the_model_saw_not_the_cards_flow():
    """import_model's flow (the card's, ~50 KB) would spend the whole result cap: a report keeps the result the model
    saw (compaction.model_view)."""
    from randall.reports import chat_report
    message = dict(role='assistant', content='Imported.', tools=[dict(
        id='t1', name='import_model', status='done', arguments={'source': 'a' * 32},
        result={'status': 'done', 'decisions': ['Line-up: draft (D3)'], 'flow': {'phases': ['x' * 9000]},
                'studio_import': {'tool': 'import_model', 'id': 'neos'}})])
    entry = chat_report._mods_message(0, message, {'content': 8000, 'args': 2000, 'result': 8000})['tools'][0]
    assert isinstance(entry['result'], dict) and 'flow' not in entry['result']
    assert entry['result']['decisions'] == ['Line-up: draft (D3)'], 'the rest kept whole, under the cap'


def test_a_failed_imports_exception_reaches_the_report_though_the_model_never_saw_it():
    """The user and the chat model get the failure in plain words; the exception behind it (the reply's card-only
    ``diagnostic``) goes to the developer with the report."""
    from randall.reports import chat_report
    error = 'ValueError: Source skin is already posed relative to its bind matrices.'
    message = dict(role='assistant', content='It stopped.', tools=[dict(
        id='t1', name='import_model', status='done', arguments={'source': 'a' * 32},
        result={'status': 'failed', 'failed': {'cause': 'an internal error in the importer while it was loading '
                                                         'the model'},
                'diagnostic': error, 'studio_import': {'tool': 'import_model', 'id': 'barbarian'}})])
    entry = chat_report._mods_message(0, message, {'content': 8000, 'args': 2000, 'result': 8000})['tools'][0]
    assert 'diagnostic' not in entry['result'] and entry['diagnostic'] == error
