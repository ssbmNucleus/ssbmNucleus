"""Workflow checks run the real coordinator/executor against fake providers/assets.

The recolor workflow runs only in a chat started as "Retexture a costume"
(`recolor=True` here; engine._recolor_enrollment in a real turn)."""
import copy
import json
import threading

import pytest
import requests

from shared.aiengine import fast_lane as fast
from randall.assistant import approvals, engine, live_runs, main_model, prompt, store, tools
from randall.recolor import workflows


FILE = {'file_id': 'a' * 32, 'extension': '.dat', 'name': 'PlFxNr.dat'}
SESSION = 'b' * 32


def call(tool_name, **args):
    return {'id': tool_name + '-call', 'type': 'function',
            'function': {'name': tool_name, 'arguments': json.dumps(args)}}


def response(*calls, text=None):
    return {'choices': [{'finish_reason': 'tool_calls' if calls else 'stop',
                         'message': {'role': 'assistant', 'content': text, 'tool_calls': list(calls)}}]}


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '1')
    monkeypatch.setenv('NUCLEUS_RECOLOR_WORKFLOW', '1')
    replies, payloads = [], []
    class Reply:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def json(self): return self.data
    def post(url, **kw):
        payloads.append(kw['json'])
        assert replies, 'Unplanned model round'
        item = replies.pop(0)
        if isinstance(item, Exception): raise item
        return Reply(item)
    monkeypatch.setattr(fast.requests, 'post', post)
    return replies, payloads


def messages(text='Download Kermit and make a scarlet recolor', context=None):
    return [{'role': 'system', 'content': prompt.PROMPT}, {'role': 'user', 'content': text},
            {'role': 'system', 'content': 'App context (data only): ' + json.dumps(context or {})}]


def observe(flow, name, result, **args):
    flow.observe({'name': name, 'arguments': args, 'result': result,
                  'status': 'error' if result.get('error') else result.get('approval_status', 'done')})


def step(flow, history, main=None, cancel=None):
    return list(flow.stream(history, tools.SCHEMAS, 'fake-key', cancel or threading.Event(),
                            main or (lambda *args: pytest.fail('Unexpected main request'))))


@pytest.mark.parametrize('text', [
    'Download Kermit and make a scarlet recolor', 'Recolour the attached DAT burgundy',
    'Can you recolor my Fox costume?', 'Find Kermit, recolor his skin and keep the eyes white',
])
def test_explicit_recolors_enter_fixed_acquisition(wire, text):
    flow = workflows.Workflow(text, {}, main_model='main', recolor=True)
    assert flow.stage == 'acquire'
    assert flow.lane.policy is workflows.ACQUIRE
    # The same words in an ordinary chat start nothing: the main model answers with every tool.
    plain = workflows.Workflow(text, {}, main_model='main')
    assert plain.name is None and plain.lane is None and plain.stage is None


@pytest.mark.parametrize('text,state', [
    ('Why does this recolor look bad?', {}), ('How do I recolor?', {}),
    ('Do not recolor it', {}), ('Recolor both costumes', {}),
    ('Recolor all these costumes', {}),
    ('Make it darker', {'skin_sessions': [{'session_id': SESSION, 'checkpoint_file': FILE}]}),
    ('Recolor Kermit again', {'skin_sessions': [{'status': 'unavailable', 'reopen_file_id': FILE['file_id']}]}),
])
def test_other_intents_and_edit_continuations_not_restarted(wire, text, state):
    flow = workflows.Workflow(text, state, main_model='main', recolor=True)
    assert flow.name is None
    if state:
        assert flow.stage == 'create_review'


def test_feature_off_uses_existing_behavior(wire, monkeypatch):
    for flag in ('NUCLEUS_RECOLOR_WORKFLOW', 'NUCLEUS_FAST_ROUTING'):
        with monkeypatch.context() as mp:
            mp.setenv(flag, '0')
            flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
            assert flow.name is None
            events = step(flow, messages(), main=lambda *a: iter([{'type': 'completion', 'message': {'content': 'main'}}]))
            assert events[-1]['message']['content'] == 'main'
    assert not wire[1]


def test_acquisition_gets_no_creative_tools_or_images(wire):
    wire[0].append(response(call('search_vault', query='Kermit')))
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    history = messages()
    history.append({'role': 'user', 'content': [{'type': 'text', 'text': 'image label'},
                                               {'type': 'image_url', 'image_url': {'url': 'private-image'}}]})
    before = copy.deepcopy(history)
    step(flow, history)
    payload = wire[1][0]
    offered = {s['function']['name'] for s in payload['tools']}
    assert offered <= workflows.ACQUISITION_TOOLS | {fast.HANDOFF}
    assert 'search_vault' in offered and 'skin_lab' not in offered
    assert payload['model'] == fast.MODEL
    assert 'private-image' not in json.dumps(payload)
    assert 'scarlet' in json.dumps(payload)
    assert history == before


@pytest.mark.parametrize('bad', [
    response(call('skin_lab', session_id=SESSION, action='recolor', adjustments=[])),
    response(call('save_mod_copy', file_id=FILE['file_id'], name='Bad')),
    response(call(fast.FINISH, answer='Recolor done')),
    response(text='Recolor completed.'),
    response(call('open_vault_file', character='Fox', skin_id='invented')),
    response(call('download_website_mod', post_id=99999)),
    response(call('search_vault'), call('search_website_mods')),
    requests.Timeout('timeout'),
])
def test_rejected_acquisition_is_sticky_and_preserves_goal(wire, bad):
    wire[0].append(bad)
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    captured = []
    def main(history, *args):
        captured.append(history)
        yield {'type': 'completion', 'message': {'content': 'clarify'}}
    history = messages()
    step(flow, history, main=main)
    step(flow, history, main=main)
    assert len(wire[1]) == 1 and len(captured) == 2
    assert captured[0][:-1] == history
    assert not flow.pending


@pytest.mark.parametrize('result', [
    {'error': 'stale source'}, {'approval_status': 'denied'},
    {'approval_status': 'cancelled'}, {'approval_status': 'expired'},
    {'imported_items': [{'id': 'one'}], 'failed': [{'name': 'two'}]},
])
def test_failure_denial_or_partial_import_stops_acquisition(wire, result):
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    observe(flow, 'download_website_mod', result, post_id=17)
    assert flow.stage == 'create_review'
    assert not flow.pending
    assert wire[1] == []


@pytest.mark.parametrize('known', [True, False])
def test_setup_advances_by_exact_receipts_without_model_calls(wire, known):
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    observe(flow, 'open_vault_file', {'files': [{'file_id': 'zip', 'extension': '.zip'}, FILE]})
    # Two code rounds: the open, then usage and the first sheet together in one round. A costume no known
    # part map covers (a model import, a restructured mod) gets the identify map first in that round.
    opened = {'session_id': SESSION, **({'known_parts': {'parts': {'skin': [0]}}} if known else {})}
    identify = [] if known else [('skin_lab', {'session_id': SESSION, 'action': 'identify'}, {'error': 'no frame'})]
    expected = [[('skin_lab_open', {'file_id': FILE['file_id']}, opened)],
                [*identify,
                 ('skin_lab', {'session_id': SESSION, 'action': 'texture_usage'}, {'textures': []}),
                 ('skin_lab', {'session_id': SESSION, 'action': 'texture_sheet', 'page': 0}, {'total_pages': 3})]]
    for batch in expected:
        assert flow.code_round(tools.SCHEMAS)
        events = step(flow, messages())
        calls = events[0]['message']['tool_calls']
        assert [(c['function']['name'], json.loads(c['function']['arguments'])) for c in calls] == \
            [(name, args) for name, args, _ in batch]
        assert flow.receipt_context()['workflow']['requested_by'] == 'code'
        for name, args, result in batch:
            assert flow.stage == 'prepare'
            observe(flow, name, result, **args)
    assert flow.stage == 'create_review' and flow.reason == 'evidence_ready'
    assert wire[1] == []


def test_ambiguous_archive_is_never_auto_selected(wire):
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    observe(flow, 'open_vault_file', {'files': [{'file_id': 'zip', 'extension': '.zip'}],
                                     'members': [{'name': 'red.dat'}, {'name': 'blue.dat'}]})
    assert flow.stage == 'acquire' and not flow.pending
    observe(flow, 'inspect_mod_file', {'files': [FILE, {**FILE, 'file_id': 'c' * 32}]})
    assert flow.stage == 'create_review' and not flow.pending


def test_setup_error_stops_remaining_automatic_steps(wire):
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    observe(flow, 'inspect_mod_file', {'file': FILE})
    step(flow, messages())
    observe(flow, 'skin_lab_open', {'error': 'not a fighter DAT'})
    assert flow.stage == 'create_review' and not flow.pending


def test_cancellation_prevents_automatic_dispatch(wire):
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    observe(flow, 'inspect_mod_file', {'file': FILE})
    cancel = threading.Event(); cancel.set()
    assert step(flow, messages(), cancel=cancel) == []
    assert wire[1] == []


@pytest.mark.parametrize('counts', [{'imported_count': 1}, {'skipped_count': 1},
                                  {'imported_count': 1, 'failed': [{'name': 'another'}]}])
def test_successful_prior_download_is_not_replayed(wire, counts):
    receipt = {'name': 'download_website_mod', 'arguments': {'post_id': 17},
               'result': {**counts, 'imported_items': [{'id': 'kermit', 'character': 'Fox'}]}}
    flow = workflows.Workflow('Download Kermit and recolor it', {}, main_model='main', receipts=[receipt], recolor=True)
    wire[0].append(response(call('download_website_mod', post_id=17)))
    seen = []
    def main(history, *args):
        seen.append(history)
        yield {'type': 'completion', 'message': {'content': 'Use the existing import'}}
    events = step(flow, messages(context={'view': {'selection': [{'post_id': 17, 'file_id': 23}]}}), main=main)
    assert not events[0]['message'].get('tool_calls')
    assert flow.reason == 'download_already_completed'
    assert 'kermit' in json.dumps(seen[0][-1])


def test_round_limit_hands_off_with_completed_receipts(wire):
    flow = workflows.Workflow('Recolor Kermit', {}, main_model='main', recolor=True)
    flow.lane.requests = workflows.ACQUIRE.max_requests
    history = messages()
    history.extend([{'role': 'assistant', 'content': None, 'tool_calls': [call('download_website_mod', post_id=17)]},
                    {'role': 'tool', 'tool_call_id': 'download_website_mod-call',
                     'content': json.dumps({'imported_items': [{'id': 'kermit'}]})}])
    seen = []
    def main(context, *args):
        seen.append(context)
        yield {'type': 'completion', 'message': {'content': 'Continue'}}
    step(flow, history, main=main)
    assert seen[0][:-1] == history and not wire[1]


def test_followup_uses_checkpoint_without_gemini(wire):
    state = {'skin_sessions': [{'status': 'unavailable', 'checkpoint_file': FILE, 'reopen_file_id': FILE['file_id']}]}
    flow = workflows.Workflow('Make it darker', state, main_model='main')
    seen = []
    def main(context, *args):
        seen.append(context)
        yield {'type': 'completion', 'message': {'content': 'Reopen checkpoint'}}
    history = messages('Make it darker', state)
    step(flow, history, main=main)
    assert seen == [history] and not wire[1]


def with_result(name, args, result, context=None, text=None):
    invocation = call(name, **args)
    return [*messages(text or 'Download Kermit and make a scarlet recolor', context),
            {'role': 'assistant', 'content': None, 'tool_calls': [invocation]},
            {'role': 'tool', 'tool_call_id': invocation['id'], 'content': json.dumps(result)}]


def test_source_ids_are_typed_and_schemas_do_not_alias(wire):
    post = {'post_id': 17, 'files': [{'file_id': 23, 'character': 'Fox', 'color': 'Red'}]}
    history = with_result('inspect_website_mod', {'post_id': 17}, {'website_mods': [post]})
    wire[0].append(response(call('open_vault_file', character='Fox', skin_id='23')))
    before = copy.deepcopy(tools.SCHEMAS)
    lane = fast.FastLane('mod', policy=workflows.ACQUIRE)
    assert lane.request(history, tools.SCHEMAS, 'key') is None
    assert lane.last_reason == 'unsupported_tool'
    offered = {s['function']['name']: s['function']['parameters']['properties'] for s in wire[1][0]['tools']}
    assert 'enum' not in offered['search_vault']['query']
    assert 'enum' in offered['search_vault']['character']
    assert 'enum' not in offered['download_website_mod']['post_id']
    assert tools.SCHEMAS == before


@pytest.mark.parametrize('text,expected', [('Recolor scarlet', 'source_variant_not_explicit'),
                                        ('Use the Red-slot variant and recolor scarlet', None)])
def test_recolor_shade_cannot_select_a_source_variant(wire, text, expected):
    history = with_result('inspect_website_mod', {'post_id': 17}, {'website_mods': [
        {'post_id': 17, 'files': [{'file_id': 23}]}]}, text=text)
    wire[0].append(response(call('download_website_mod', post_id=17, file_id=23)))
    lane = fast.FastLane('mod', policy=workflows.ACQUIRE)
    reply = lane.request(history, tools.SCHEMAS, 'key')
    assert lane.last_reason == expected
    assert bool(reply) == (expected is None)


def test_variant_must_belong_to_its_post(wire):
    history = with_result('inspect_website_mod', {'post_id': 17}, {'website_mods': [
        {'post_id': 17, 'files': [{'file_id': 23}]}, {'post_id': 18, 'files': [{'file_id': 24}]}]},
        text='Use this variant for a recolor')
    wire[0].append(response(call('download_website_mod', post_id=17, file_id=24)))
    lane = fast.FastLane('mod', policy=workflows.ACQUIRE)
    assert lane.request(history, tools.SCHEMAS, 'key') is None
    assert lane.last_reason == 'unknown_website_variant'


def test_duplicate_receipt_only_offers_vault_recovery(wire):
    history = with_result('download_website_mod', {'post_id': 17}, {'skipped_count': 1, 'website_mods': [{'post_id': 17}]})
    wire[0].append(response(call('search_vault', query='Kermit')))
    assert fast.FastLane('mod', policy=workflows.ACQUIRE).request(history, tools.SCHEMAS, 'key')
    assert {s['function']['name'] for s in wire[1][0]['tools']} == {'search_vault', fast.HANDOFF}


def test_ambiguous_matches_skip_gemini_entirely(wire):
    history = with_result('search_vault', {'query': 'Kermit'}, {'items': [
        {'id': 'one', 'character': 'Fox'}, {'id': 'two', 'character': 'Marth'}]})
    lane = fast.FastLane('mod', policy=workflows.ACQUIRE)
    assert lane.request(history, tools.SCHEMAS, 'key') is None
    assert lane.last_reason == 'no_tools' and not wire[1]


def test_latest_query_replaces_unrelated_old_selection(wire):
    history = with_result('search_vault', {'query': 'Kermit'}, {'items': [{'id': 'kermit', 'character': 'Fox'}]},
                          {'view': {'selection': [{'id': 'old-marth', 'character': 'Marth'}]}})
    wire[0].append(response(call('open_vault_file', character='Fox', skin_id='kermit')))
    assert fast.FastLane('mod', policy=workflows.ACQUIRE).request(history, tools.SCHEMAS, 'key')


def test_untrusted_malformed_context_falls_back(wire):
    lane = fast.FastLane('mod', policy=workflows.ACQUIRE)
    assert lane.request(messages(context={'view': {'selection': ['bad']}}), tools.SCHEMAS, 'key') is None
    assert lane.last_reason == 'invalid_context' and not wire[1]


@pytest.fixture
def fake_labs(monkeypatch):
    calls = []
    def opened(**args):
        calls.append(('skin_lab_open', args))
        return {'session_id': SESSION, 'source_file_id': args['file_id'], 'files': [
            {'file_id': 'render', 'extension': '.png'}]}
    def lab(**args):
        calls.append(('skin_lab', args))
        return {'session_id': SESSION, 'action': args['action'], 'files': [
            {'file_id': 'sheet', 'extension': '.png'}] if args['action'] == 'texture_sheet' else []}
    monkeypatch.setitem(tools.REGISTRY, 'skin_lab_open', tools.ToolSpec('automatic', opened))
    monkeypatch.setitem(tools.REGISTRY, 'skin_lab', tools.ToolSpec('automatic', lab))
    monkeypatch.setattr(engine, 'tool_images', lambda name, result: [
        {'type': 'image_url', 'image_url': {'url': 'data:' + f['file_id']}} for f in result.get('files', [])
        if f['extension'] == '.png'])
    return calls


def test_engine_selected_costume_prepares_then_main_edits_in_same_chat(vault, monkeypatch, wire, fake_labs):
    """The costume picked when the recolor chat started (context.selection, one vault costume) is opened
    exactly, by code: no search, no fast-lane round (`wire` refuses any it was not told of)."""
    opened = []
    monkeypatch.setitem(tools.REGISTRY, 'open_vault_file', tools.ToolSpec(
        'automatic', lambda **a: opened.append(a) or {'files': [FILE]}))
    main_requests = []
    def main(history, schemas, *args):
        main_requests.append(copy.deepcopy(history))
        if len(main_requests) == 1:
            yield {'type': 'completion', 'message': response(call('skin_lab', session_id=SESSION,
                action='analyze_palette', texture_indices=[2], include_materials=False))['choices'][0]['message']}
        else:
            yield {'type': 'delta', 'content': 'Reviewing the requested scarlet shade.'}
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Reviewing the requested scarlet shade.'}}
    monkeypatch.setattr(engine, '_provider', main)
    # Count only AI rounds in progress metadata, not the three code batches.
    run = engine.start(None, 'Recolor the selected Kermit scarlet, keep the eyes white',
                       {'task': 'recolor_part', 'selection': [{'character': 'Fox', 'skin_id': 'kermit'}]},
                       request_key='secret')
    list(live_runs.stream(run))
    saved = store.get(run.chat_id)['messages'][-1]
    assert saved['status'] == 'done'
    assert not wire[1] and len(main_requests) == 2
    assert opened == [{'character': 'Fox', 'skin_id': 'kermit'}]
    assert saved['model_rounds'] == 2, 'code opened and prepared it: only the main rounds count'
    receipts = saved['tools']
    assert [r['name'] for r in receipts] == ['open_vault_file', 'skin_lab_open'] + ['skin_lab'] * 4
    assert [r['workflow']['requested_by'] for r in receipts] == ['code'] * 5 + [main_model.MODEL]
    # No known part map in the open's result: the identify map comes first in the prepare round.
    assert [c[1].get('action') for c in fake_labs] == [None, 'identify', 'texture_usage', 'texture_sheet',
                                                       'analyze_palette']
    assert 'data:render' in json.dumps(main_requests[0]) and 'data:sheet' in json.dumps(main_requests[0])
    assert 'keep the eyes white' in json.dumps(main_requests[0])
    assert run.key == '' and 'secret' not in json.dumps(store.get(run.chat_id))


@pytest.mark.parametrize('approved', [True, False])
def test_engine_download_keeps_real_grant_gate(vault, monkeypatch, wire, fake_labs, approved):
    wire[0].append(response(call('download_website_mod', post_id=17, file_id=23)))
    if approved:
        wire[0].append(response(call('open_vault_file', character='Fox', skin_id='downloaded')))
    imports, approvals_seen = [], []
    def apply(args, plan, **kw):
        imports.append((args, plan))
        return {'imported_count': 1, 'imported_items': [{'id': 'downloaded', 'character': 'Fox'}]}
    spec = tools.ToolSpec('approval', None, lambda args: ({'post_id': 17, 'file_id': 23}, {'title': 'Download?'}), apply)
    monkeypatch.setitem(tools.REGISTRY, 'download_website_mod', spec)
    monkeypatch.setitem(tools.REGISTRY, 'open_vault_file', tools.ToolSpec('automatic', lambda **a: {'files': [FILE]}))
    def approve(run, receipt, prepared):
        approvals_seen.append(prepared)
        receipt['approval'] = {'status': 'approved' if approved else 'denied'}
        return approvals.Grant(prepared.fingerprint) if approved else None
    for _mod in (engine, live_runs):
        monkeypatch.setattr(_mod, '_await_approval', approve)
    monkeypatch.setattr(engine, '_provider', lambda *args: iter([
        {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Main continues from receipts.'}}]))
    run = engine.start(None, 'Download this Kermit variant and recolor it scarlet',
                       {'task': 'recolor_part', 'selection': [{'post_id': 17, 'file_id': 23}]}, request_key='key')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done', run.answer
    assert len(approvals_seen) == 1
    assert len(imports) == int(approved)
    assert len(fake_labs) == (4 if approved else 0)          # open, identify (no known parts), usage, sheet
    assert run.answer['tools'][0]['status'] == ('done' if approved else 'denied')


def test_engine_full_acquisition_approval_setup_and_creative_handoff(vault, monkeypatch, wire, fake_labs):
    post = {'post_id': 17, 'title': 'Kermit for Fox', 'files': [{'file_id': 23, 'name': 'PlFxNr.dat'}]}
    sequence = [call('search_vault', query='Kermit'), call('search_website_mods', query='Kermit'),
                call('inspect_website_mod', post_id=17), call('download_website_mod', post_id=17),
                call('open_vault_file', character='Fox', skin_id='kermit')]
    wire[0].extend(response(c) for c in sequence)
    for name, result in [('search_vault', {'items': [], 'total': 0}),
                         ('search_website_mods', {'website_mods': [post]}),
                         ('inspect_website_mod', {'website_mods': [post]}),
                         ('open_vault_file', {'files': [FILE]})]:
        monkeypatch.setitem(tools.REGISTRY, name, tools.ToolSpec('automatic', lambda _r=result, **a: copy.deepcopy(_r)))
    monkeypatch.setitem(tools.REGISTRY, 'download_website_mod', tools.ToolSpec('approval', None,
        lambda args: ({'post_id': 17}, {'title': 'Download Kermit?'}),
        lambda *a, **kw: {'imported_count': 1, 'imported_items': [{'id': 'kermit', 'character': 'Fox'}]}))
    seen_approvals, main_requests = [], []
    def approve(run, receipt, prepared):
        seen_approvals.append(prepared)
        receipt['approval'] = {'status': 'approved'}
        return approvals.Grant(prepared.fingerprint)
    def main(history, *args):
        main_requests.append(history)
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Ready to choose the scarlet palette.'}}
    for _mod in (engine, live_runs):
        monkeypatch.setattr(_mod, '_await_approval', approve)
    monkeypatch.setattr(engine, '_provider', main)
    run = engine.start(None, 'Find Kermit, download him if needed, and make a scarlet recolor.',
                       {'task': 'recolor_part'}, request_key='key')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done'
    assert len(wire[1]) == 5 and len(main_requests) == 1 and len(seen_approvals) == 1
    assert [r['name'] for r in run.answer['tools']] == [c['function']['name'] for c in sequence] + [
        'skin_lab_open', 'skin_lab', 'skin_lab', 'skin_lab']       # identify (no known parts), usage, sheet
    assert 'data:sheet' in json.dumps(main_requests[0])


@pytest.mark.parametrize('text,fighter', [
    ('Can you make like a lava bowser skin', 'Bowser'),
    ('lets make an aztec style mario texture hack', 'Mario'),
    ('recolor vanilla mario so his overalls are green', 'Mario'),
    ('make a dr mario skin', 'Dr. Mario'), ('make a young link camo skin', 'Young Link'),
    ('make bowser a red costume', 'Bowser'),   # the result colour is not a source slot
])
def test_a_named_fighter_skin_opens_the_vanilla_default_without_a_model(wire, text, fighter):
    flow = workflows.Workflow(text, {}, main_model='main', recolor=True)
    assert flow.code_round(tools.SCHEMAS), 'code opens it: not a model round'
    events = step(flow, messages(text))
    (opened,) = events[-1]['message']['tool_calls']
    assert opened['function']['name'] == 'open_vanilla_file'
    assert json.loads(opened['function']['arguments']) == {'character': fighter}
    assert not wire[1], 'no fast-lane or main-model round'
    # From here the normal receipt chain prepares the lab.
    observe(flow, 'open_vanilla_file', {'files': [FILE]}, character=fighter)
    assert flow.pending[0]['function']['name'] == 'skin_lab_open'


@pytest.mark.parametrize('text,view', [
    ('recolor my kermit fox skin', None), ('download a fox skin and recolor it', None),
    ('recolor the red slot bowser', None), ('make a lava skin for it', None),
    ('make a lava bowser skin', {'files': [FILE]}),
    ('make a lava bowser skin', {'selection': [{'character': 'Bowser', 'skin_id': 'x1'},
                                               {'character': 'Bowser', 'skin_id': 'x2'}]}),
    ('make a lava bowser skin', {'selection': [{'post_id': 17, 'file_id': 23}]}),
    ('recolor mario and luigi', None),
])
def test_a_named_or_attached_source_still_goes_to_acquisition(wire, text, view):
    wire[0].append(response(call(fast.HANDOFF)))
    flow = workflows.Workflow(text, {}, main_model='main', recolor=True, view=view)
    assert not flow.code_round(tools.SCHEMAS)
    main = lambda *a: iter([{'type': 'completion', 'message': {'role': 'assistant', 'content': 'main'}}])
    events = step(flow, messages(text, {'view': view} if view else None), main=main)
    assert not any(flow.requested_by == 'code'
                   for e in events for c in (e.get('message') or {}).get('tool_calls') or [])


@pytest.mark.parametrize('view,opened', [
    # A vault costume: exactly that pair (`id` is read as skin_id, as search results carry it).
    ({'selection': [{'character': 'Fox', 'skin_id': 'kermit', 'name': 'Kermit'}]},
     ('open_vault_file', {'character': 'Fox', 'skin_id': 'kermit'})),
    ({'selection': [{'character': 'Fox', 'id': 'kermit'}]},
     ('open_vault_file', {'character': 'Fox', 'skin_id': 'kermit'})),
    # A stock costume, with or without its slot.
    ({'selection': [{'character': 'Bowser', 'vanilla': True}]}, ('open_vanilla_file', {'character': 'Bowser'})),
    ({'selection': [{'character': 'Bowser', 'vanilla': True, 'color': 'Re'}]},
     ('open_vanilla_file', {'character': 'Bowser', 'color': 'Re'})),
])
@pytest.mark.parametrize('text', ['make it lava', 'recolor Marth red', 'download Kermit from the website'])
def test_the_picked_costume_is_opened_exactly_and_never_searched_for(wire, view, opened, text):
    """The costume the user picked when starting the recolor chat (context.selection) is the source:
    code opens it, whatever the words name, and no model is asked (`wire` refuses an unplanned round)."""
    flow = workflows.Workflow(text, {}, main_model='main', recolor=True, view=view)
    assert flow.name == 'recolor' and flow.code_round(tools.SCHEMAS)
    events = step(flow, messages(text, {'view': view}))
    (call_,) = events[-1]['message']['tool_calls']
    assert (call_['function']['name'], json.loads(call_['function']['arguments'])) == opened
    assert flow.requested_by == 'code' and not wire[1]
    observe(flow, opened[0], {'files': [FILE]}, **opened[1])
    assert flow.pending[0]['function']['name'] == 'skin_lab_open'


def test_a_picked_costume_opens_by_code_even_with_the_fast_lane_off(monkeypatch):
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '0')
    view = {'selection': [{'character': 'Fox', 'skin_id': 'kermit'}]}
    assert workflows.Workflow('make it lava', {}, main_model='main', recolor=True).name is None
    flow = workflows.Workflow('make it lava', {}, main_model='main', recolor=True, view=view)
    assert flow.name == 'recolor' and flow.code_round(tools.SCHEMAS)


@pytest.mark.parametrize('view', [None, {}, {'selection': []}, {'selection': 'Fox'}, {'selection': [None]},
                                  {'selection': [{'skin_id': 'kermit'}]}, {'selection': [{'character': 'Fox'}]},
                                  {'selection': [{'character': 'Fox', 'vanilla': 'yes'}]}])
def test_anything_else_is_not_a_picked_costume(view):
    assert workflows.picked_costume(view) is None


def test_without_extracted_vanilla_assets_the_lane_decides(wire):
    wire[0].append(response(call(fast.HANDOFF)))
    flow = workflows.Workflow('make a lava bowser skin', {}, main_model='main', recolor=True)
    schemas = [s for s in tools.SCHEMAS if s['function']['name'] != 'open_vanilla_file']
    main = lambda *a: iter([{'type': 'completion', 'message': {'role': 'assistant', 'content': 'main'}}])
    events = list(flow.stream(messages('make a lava bowser skin'), schemas, 'k', threading.Event(), main))
    assert events[-1]['message']['content'] == 'main'


def test_surface_themes_are_named_to_the_main_model(wire):
    assert workflows.surface_themes('make a lava bowser skin') == ['lava']
    assert workflows.surface_themes('recolor ice climbers blue') == []
    assert workflows.surface_themes('make mario gold') == []
    flow = workflows.Workflow('make a lava bowser skin', {}, main_model='main', recolor=True)
    flow._main('evidence_ready')
    seen = []
    step(flow, messages('make a lava bowser skin'),
         main=lambda history, *a: seen.append(history) or iter([{'type': 'completion', 'message': {'content': 'ok'}}]))
    note = seen[0][-1]['content']
    assert '"surface_themes": ["lava"]' in note and 'generate_material' in note


def test_turn_cost_accumulates_reported_costs_by_source():
    answer = {}
    engine._add_cost(answer, 'main', 0.004)
    engine._add_cost(answer, 'main', 0.001)
    engine._add_cost(answer, 'images', 0.01)
    for junk in (None, 'free', float('nan'), -1, True):
        engine._add_cost(answer, 'main', junk)
    assert answer['cost_parts'] == {'main': 0.005, 'images': 0.01}
    assert answer['cost_usd'] == 0.015
