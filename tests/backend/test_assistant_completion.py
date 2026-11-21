"""Long tasks keep running; a promised action or cut-off stream is not completion."""
import json
import math
import re
import threading

import pytest

from shared.aiengine import model_upload
from randall.assistant import engine, live_runs, main_model, store, tools
from randall.assistant.tasks import coordinator as taskflow


def sent_payload(kwargs):
    """The JSON body a faked `requests.post` was handed by `model_upload.post_json`."""
    if kwargs.get('json') is not None:
        return kwargs['json']
    data = kwargs.get('data')
    if isinstance(data, model_upload._Body):
        data = bytes(data._data)
    return json.loads(bytes(data).decode('utf-8'))


def tool_call(index=0):
    return {'id': f'call-{index}', 'type': 'function', 'function': {
        'name': 'search_vault', 'arguments': json.dumps({'query': f'case-{index}'})}}


def emit(text='', calls=None):
    if text:
        yield {'type': 'delta', 'content': text}
    yield {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
           'message': {'role': 'assistant', 'content': text or None, **({'tool_calls': calls} if calls else {})}}


@pytest.mark.parametrize('text', [
    "Let me inspect the actual textures:", "I'll apply that recolor now.",
    "Now I'm going to export the edited costume:",
    'The palette is clean. Shifting only the body greens to scarlet, and explicitly zeroing group 2:',
])
def test_unfulfilled_action_language_is_detected(text):
    assert engine._announced_action(text)


@pytest.mark.parametrize('text', [
    'The recolor is ready. I preserved the eyes.', 'Which Kermit costume should I use?',
    "I'll apply it after you approve the download.", 'Please choose the source costume first.',
    "If you want, I'll make another version.", 'I cannot inspect the missing file.',
    'Here are the steps:\n\n1. Open the costume.\n2. Recolor it.',
    "Earlier I said I'll apply it. The exported file is now ready.",
    '```python\n# let me inspect:\n```',
])
def test_answers_questions_and_blockers_do_not_auto_continue(text):
    assert not engine._announced_action(text)


def test_long_workflow_keeps_all_tools_past_both_old_round_caps(vault, monkeypatch):
    requests = []
    def provider(messages, schemas, *args):
        index = len(requests); requests.append(schemas)
        yield from emit(calls=[tool_call(index)]) if index < 40 else emit('All requested checks completed.')
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Check the requested items', {}, request_key='test')
    events = [json.loads(line[6:]) for line in live_runs.stream(run) if line.startswith('data: ')]
    assert run.answer['status'] == 'done'
    assert len(run.answer['tools']) == 40 and run.answer['model_rounds'] == 41
    assert all(requests)
    progress = [e for e in events if e['type'] == 'turn_progress']
    assert [e['model_rounds'] for e in progress] == list(range(1, 42))
    assert {e['message_id'] for e in progress} == {run.answer['id']}
    assert {e['started_at'] for e in progress} == {run.answer['started_at']}
    saved = store.get(run.chat_id)['messages'][-1]
    assert saved['started_at'] == run.answer['started_at'] and saved['model_rounds'] == 41


def test_user_can_stop_a_long_task_and_keeps_completed_work(vault, monkeypatch):
    requests = []
    def provider(messages, schemas, key, cancelled):
        requests.append(schemas)
        assert schemas
        if len(requests) == 35:
            cancelled.set()
        yield from emit(calls=[tool_call(len(requests))])
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Check the requested items', {}, request_key='test')
    list(live_runs.stream(run))
    saved = store.get(run.chat_id)['messages'][-1]
    assert saved['status'] == 'cancelled' and 'error' not in saved
    assert saved['model_rounds'] == 35
    assert len(requests) == 35 and len(saved['tools']) == 34
    assert all(t['status'] == 'done' for t in saved['tools'])


def test_one_continuation_executes_missing_action_without_restarting(vault, monkeypatch):
    histories = []
    def provider(messages, *args):
        histories.append(json.loads(json.dumps(messages)))
        index = len(histories)
        if index == 1:
            yield from emit(calls=[tool_call(1)])
        elif index == 2:
            yield from emit("Now let me inspect the next item:")
        elif index == 3:
            assert any(m.get('role') == 'tool' for m in messages)
            assert 'no tool call' in messages[-1]['content']
            yield from emit(calls=[tool_call(2)])
        else:
            yield from emit('Both checks are complete.')
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Check both items', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done' and run.answer['action_continuations'] == 1
    assert len(run.answer['tools']) == 2 and len(histories) == 4
    assert run.answer['last_finish_reason'] == 'stop'
    assert run.answer['content'].endswith('\n\nBoth checks are complete.')


def test_repeated_empty_promise_pauses_instead_of_looping(vault, monkeypatch):
    requests = []
    def provider(*args):
        requests.append(1)
        yield from emit("I'll inspect the model now:")
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Inspect the model', {}, request_key='test')
    list(live_runs.stream(run))
    assert len(requests) == 2
    assert run.answer['status'] == 'error' and run.answer['stop_reason'] == 'missing_action'
    assert not run.answer['tools']


def test_successful_work_allows_later_missing_action_recovery(vault, monkeypatch):
    requests = []
    def provider(*args):
        requests.append(1)
        index = len(requests)
        if index in {1, 3, 5}:
            yield from emit("I'll inspect the next item:")
        elif index in {2, 4, 6}:
            yield from emit(calls=[tool_call(index)])
        else:
            yield from emit('All checks are complete.')
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Inspect these items', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done' and run.answer['action_continuations'] == 3
    assert len(run.answer['tools']) == 3 and len(requests) == 7


def test_announcement_with_a_tool_call_does_not_need_recovery(vault, monkeypatch):
    calls = []
    def provider(*args):
        calls.append(1)
        yield from (emit('Let me inspect it:', [tool_call()]) if len(calls) == 1 else emit('Checked.'))
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Inspect it', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done' and len(calls) == 2
    assert 'action_continuations' not in run.answer


def fake_wire(monkeypatch, packets):
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_lines(self, chunk_size=1):
            for packet in packets:
                yield b'data: [DONE]' if packet == 'DONE' else ('data: ' + json.dumps(packet)).encode()
    monkeypatch.setattr(main_model.requests, 'post', lambda *a, **kw: Response())


def packet(text=None, finish=None, calls=None):
    return {'choices': [{'delta': {**({'content': text} if text else {}), **({'tool_calls': calls} if calls else {})},
                         'finish_reason': finish}]}


@pytest.mark.parametrize('packets,reason', [
    ([packet('Partial response'), 'DONE'], 'incomplete_stream'),
    ([packet('Partial response')], 'incomplete_stream'),
    ([packet('Partial response', 'length'), 'DONE'], 'output_limit'),
    ([packet(finish='stop'), 'DONE'], 'empty_response'),
    ([packet(finish='tool_calls'), 'DONE'], 'empty_response'),
    ([packet(finish='tool_calls', calls=[{'index': 0, 'id': 'call', 'function': {'name': 'search_vault', 'arguments': '{'}}]), 'DONE'], 'incomplete_tool_call'),
])
def test_incomplete_provider_replies_are_explicitly_unfinished(monkeypatch, packets, reason):
    fake_wire(monkeypatch, packets)
    with pytest.raises(main_model.TurnStopped) as error:
        list(engine._provider([], tools.SCHEMAS, 'test', threading.Event()))
    assert error.value.reason == reason


@pytest.mark.parametrize('status,sentence', [(402, main_model.USED_UP), (401, main_model.UNREACHABLE)])
def test_a_provider_error_status_reads_plainly_and_keeps_the_status_for_the_trace(monkeypatch, status, sentence):
    """Owner's rule (2026-10-07): the chat never names the provider, keys, credits or money. The old line was
    "AI provider returned HTTP 402. Check your AI key and credits in Settings."."""
    class Response:
        status_code = status
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(main_model.requests, 'post', lambda *a, **kw: Response())
    with pytest.raises(taskflow.ProviderHTTPError) as error:
        list(engine._provider([], tools.SCHEMAS, 'test', threading.Event()))
    assert str(error.value) == sentence and error.value.http_status == status
    assert error.value.diagnostic == f'AI provider returned HTTP {status}'
    assert not re.search(r'key|credit|\$|openrouter|HTTP', sentence, re.IGNORECASE)


def test_token_cutoff_keeps_streamed_text_but_does_not_store_done(vault, monkeypatch):
    fake_wire(monkeypatch, [packet('The visible body is green.', 'length'), 'DONE'])
    run = engine.start(None, 'Inspect the costume', {}, request_key='test')
    list(live_runs.stream(run))
    saved = store.get(run.chat_id)['messages'][-1]
    assert saved['content'] == 'The visible body is green.'
    assert saved['status'] == 'error' and saved['stop_reason'] == 'output_limit'
    assert 'continue' in saved['error']


def test_malformed_second_call_cannot_partially_execute_a_batch(vault, monkeypatch):
    good = tool_call()
    fake_wire(monkeypatch, [packet(finish='tool_calls', calls=[{'index': 0, **good},
        {'index': 1, 'id': 'bad', 'function': {'name': 'search_vault', 'arguments': '{'}}]), 'DONE'])
    run = engine.start(None, 'Inspect the costumes', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'error' and run.answer['stop_reason'] == 'incomplete_tool_call'
    assert not run.answer['tools']


def test_a_long_streaming_response_is_not_cut_off_by_the_clock(monkeypatch):
    """The three-minute streaming cap is gone (owner, 2026-09-25: Randall does not
    loop like that). Ten minutes of steady output followed by an answer is an answer."""
    fake_wire(monkeypatch, [packet(), packet(), packet('late', 'stop'), 'DONE'])
    clock = iter(range(0, 10 ** 6, 120))
    monkeypatch.setattr(engine.time, 'monotonic', lambda: next(clock))
    events = list(engine._provider([], [], 'test', threading.Event()))
    done = [e for e in events if e['type'] == 'completion']
    assert done and done[-1]['message']['content'] == 'late'


def test_the_stream_transfer_cap_still_stands(monkeypatch):
    fake_wire(monkeypatch, [packet('x' * 16_000_001), packet('late', 'stop'), 'DONE'])
    with pytest.raises(RuntimeError, match='too big for me to finish'):
        list(engine._provider([], [], 'test', threading.Event()))


def test_the_silent_socket_read_timeout_still_stands(monkeypatch):
    seen = {}
    real = main_model.model_upload.post_json
    def post_json(*args, **kwargs):
        seen['timeout'] = kwargs.get('timeout')
        return real(*args, **kwargs)
    fake_wire(monkeypatch, [packet('ok', 'stop'), 'DONE'])
    monkeypatch.setattr(main_model.model_upload, 'post_json', post_json)
    list(engine._provider([], [], 'test', threading.Event()))
    assert seen['timeout'] == (10, 60)


@pytest.mark.parametrize('model,expected', [('deepseek/deepseek-v4.1-flash', {'effort': 'low'}), ('other/model', None)])
def test_deepseek_reasoning_setting_leaves_other_models_unchanged(monkeypatch, model, expected):
    fake_wire(monkeypatch, [packet('done', 'stop')])
    original = main_model.requests.post
    seen = {}
    def post(*args, **kwargs):
        seen.update(sent_payload(kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(main_model.requests, 'post', post)
    for _mod in (engine, main_model):
        monkeypatch.setattr(_mod, 'MODEL', model)
    list(engine._provider([], [], 'test', threading.Event()))
    assert seen.get('reasoning') == expected
    assert seen['max_tokens'] == 16384


def _endless(requests, cost=None):
    def provider(messages, *args):
        requests.append(list(messages))
        yield {'type': 'completion', 'finish_reason': 'tool_calls', 'cost_usd': cost,
               'message': {'role': 'assistant', 'content': None, 'tool_calls': [tool_call(len(requests))]}}
    return provider


def _open_session(monkeypatch):
    state = {'skin_sessions': [{'session_id': 'b' * 32, 'checkpoint_file': {'file_id': 'a' * 32}}]}
    monkeypatch.setattr(engine, 'working_context', lambda receipts: state)


def _skin_turn(monkeypatch):
    """A turn enrolled as a skin job whose session is open."""
    real = engine.Workflow
    class SkinTurn(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.name, self.stage, self.session_id = 'recolor', 'create_review', 'b' * 32
    monkeypatch.setattr(engine, 'Workflow', SkinTurn)


def test_a_skin_edit_is_told_to_wrap_up_then_stopped_at_its_round_budget(vault, monkeypatch):
    _skin_turn(monkeypatch)
    requests = []
    monkeypatch.setattr(engine, '_provider', _endless(requests))
    run = engine.start(None, 'Make the shell darker', {}, request_key='test')
    list(live_runs.stream(run))
    assert len(requests) == engine.SKIN_MAX_ROUNDS
    notes = [i for i, m in enumerate(requests) if any(x.get('content') == engine.WRAP_UP_NOTE for x in m)]
    assert notes[0] == engine.SKIN_WRAP_UP, 'the note arrives with the round after the budget'
    assert run.answer['stop_reason'] == 'round_budget'
    assert len(run.answer['tools']) == engine.SKIN_MAX_ROUNDS, 'completed work is kept'


def test_a_skin_edit_stops_at_its_cost_ceiling(vault, monkeypatch):
    _skin_turn(monkeypatch)
    requests = []
    monkeypatch.setattr(engine, '_provider', _endless(requests, cost=0.02))
    run = engine.start(None, 'Make the shell darker', {}, request_key='test')
    list(live_runs.stream(run))
    rounds = round(engine.SKIN_MAX_COST / 0.02)
    assert len(requests) == rounds and run.answer['stop_reason'] == 'round_budget'
    assert run.answer['cost_usd'] == pytest.approx(engine.SKIN_MAX_COST)


def test_other_turns_have_no_round_budget(vault, monkeypatch):
    requests = []
    def provider(messages, *args):
        if len(requests) >= engine.SKIN_MAX_ROUNDS + 5:
            requests.append(messages)
            yield from emit('Done checking.')
            return
        yield from _endless(requests)(messages)
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Check every item', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done' and len(requests) == engine.SKIN_MAX_ROUNDS + 6


@pytest.mark.parametrize('skin', [True, False])
def test_an_open_skin_session_offers_only_the_skin_tools(vault, monkeypatch, skin):
    if skin:
        _skin_turn(monkeypatch)
    offered = []
    def provider(messages, schemas, *args):
        offered.append({s['function']['name'] for s in schemas})
        yield from emit('Done.')
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Make the shell darker', {}, request_key='test')
    list(live_runs.stream(run))
    if skin:
        assert offered[0] <= engine.SKIN_TOOLS and {'skin_lab', 'skin_material'} <= offered[0]
    else:
        assert 'deliver_to_game' in offered[0] and not offered[0] <= engine.SKIN_TOOLS


def test_token_totals_record_cached_input():
    answer = {}
    engine._add_tokens(answer, {'prompt_tokens': 1000, 'completion_tokens': 50,
                                'prompt_tokens_details': {'cached_tokens': 800}})
    engine._add_tokens(answer, {'prompt_tokens': 1200, 'completion_tokens': 30})
    engine._add_tokens(answer, None)
    assert answer['tokens'] == {'prompt': 2200, 'cached': 800, 'completion': 80}




def test_a_session_left_open_by_an_earlier_turn_hides_nothing(vault, monkeypatch):
    """"lets do a model import of goku next" after a recolour saw only the skin
    tools, and Randall said it had no model-import tools. (An ordinary chat
    reaches the import by its attached model: the words alone route nowhere.)"""
    _open_session(monkeypatch)
    offered, requests = [], []
    def provider(messages, schemas, *args):
        offered.append({s['function']['name'] for s in schemas})
        if len(offered) > engine.SKIN_MAX_ROUNDS + 2:
            yield from emit('Done.')
            return
        yield from _endless(requests)(messages)
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'lets do a model import of goku next',
                       {'files': [{'file_id': 'c' * 32, 'name': 'goku.glb'}]}, request_key='test')
    list(live_runs.stream(run))
    assert 'import_model' in offered[0] and not offered[0] <= engine.SKIN_TOOLS, 'the import tools are offered'
    assert run.answer['status'] == 'done', 'and the skin round budget does not apply'



def test_an_identical_failing_call_is_warned_then_stopped(vault, monkeypatch):
    """A Homer import sent one rejected call sixty times running."""
    requests = []
    def provider(messages, *args):
        requests.append(list(messages))
        yield {'type': 'completion', 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
               'tool_calls': [{'id': f'c{len(requests)}', 'type': 'function', 'function': {
                   'name': 'inspect_mod', 'arguments': json.dumps({'character': 'Nobody', 'skin_id': 'x'})}}]}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'look at that skin', {}, request_key='test')
    list(live_runs.stream(run))
    assert len(requests) == engine.REPEAT_FAILURE_STOP
    assert run.answer['stop_reason'] == 'repeated_failure'
    assert any('failed identically' in (m.get('content') or '') for m in requests[-1] if m.get('role') == 'system')
    assert len(run.answer['tools']) == engine.REPEAT_FAILURE_STOP, 'every attempt is kept on record'


def test_a_failing_call_that_changes_is_not_stopped(vault, monkeypatch):
    requests = []
    def provider(messages, *args):
        requests.append(1)
        if len(requests) > 5:
            yield from emit('Giving up; nothing matches.')
            return
        yield {'type': 'completion', 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
               'tool_calls': [{'id': f'c{len(requests)}', 'type': 'function', 'function': {
                   'name': 'inspect_mod', 'arguments': json.dumps({'character': f'Nobody{len(requests)}', 'skin_id': 'x'})}}]}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'look at that skin', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done' and len(requests) == 6


def _studio_calls(monkeypatch, requests, offered, cost=None, refused=False):
    """A model import turn (IMPORT_TURN) that never stops calling import_model. Each call
    names a different source, so the repeated-failure brake does not fire first."""
    from randall.model_import.chat import studio_import
    def execute(call, key=None, progress=None, cancelled=None):
        project = json.loads(call.arguments)['source']
        reply = {'error': f'No import named {project!r}.'} if refused else {}
        return {**reply, 'studio_import': {'tool': call.name[len(studio_import.PREFIX):], 'id': project}}
    monkeypatch.setattr(studio_import, 'execute', execute)
    def provider(messages, schemas, *args):
        index = len(requests)
        requests.append(list(messages))
        offered.append({s['function']['name'] for s in schemas})
        call = {'id': f'call-{index}', 'type': 'function', 'function': {
            'name': 'import_model', 'arguments': json.dumps({'source': f'p{index}'})}}
        yield {'type': 'completion', 'finish_reason': 'tool_calls', 'cost_usd': cost,
               'message': {'role': 'assistant', 'content': None, 'tool_calls': [call]}}
    return provider


IMPORT_TURN = 'import this model'
IMPORT_CHAT = {'task': 'model_import'}      # an "Import a model" chat: its turns are import turns


def test_a_model_import_wraps_up_then_stops(vault, monkeypatch):
    from randall.model_import.chat import studio_import
    requests, offered = [], []
    monkeypatch.setattr(engine, '_provider', _studio_calls(monkeypatch, requests, offered))
    run = engine.start(None, IMPORT_TURN, IMPORT_CHAT, request_key='test')
    list(live_runs.stream(run))
    assert len(requests) == studio_import.MAX_ROUNDS and run.answer['stop_reason'] == 'round_budget'
    notes = [i for i, m in enumerate(requests) if any(x.get('content') == studio_import.WRAP_UP_NOTE for x in m)]
    assert notes[0] == studio_import.WRAP_UP_ROUNDS
    assert 'import_model' in offered[notes[0]]


def test_a_model_import_wraps_up_at_its_cost_point(vault, monkeypatch):
    from randall.model_import.chat import studio_import
    requests, offered = [], []
    monkeypatch.setattr(engine, '_provider', _studio_calls(monkeypatch, requests, offered, cost=0.02))
    run = engine.start(None, IMPORT_TURN, IMPORT_CHAT, request_key='test')
    list(live_runs.stream(run))
    wrap = math.ceil(studio_import.WRAP_UP_COST / 0.02 - 1e-9)     # the first round past the wrap-up spend
    assert any(x.get('content') == studio_import.WRAP_UP_NOTE for x in requests[wrap])
    assert run.answer['cost_usd'] == pytest.approx(studio_import.MAX_COST, abs=0.021)


def test_refused_rounds_do_not_spend_the_allowance_meant_for_repairs(vault, monkeypatch):
    """A Gabite import finished its draft and then spent its last four rounds
    being refused over one argument. Refusals buy the user nothing, so a bounded
    number of them are credited back -- against rounds only, never cost."""
    from randall.model_import.chat import studio_import
    requests = []
    monkeypatch.setattr(engine, '_provider', _studio_calls(monkeypatch, requests, [], refused=True))
    run = engine.start(None, IMPORT_TURN, IMPORT_CHAT, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['stop_reason'] == 'round_budget'
    assert all((r.get('result') or {}).get('error') for r in run.answer['tools'])
    assert len(requests) == studio_import.MAX_ROUNDS + engine.MODEL_RECOVERY_ROUNDS


def test_the_recovery_allowance_is_not_a_refund_against_spending(vault, monkeypatch):
    from randall.model_import.chat import studio_import
    requests = []
    provider = _studio_calls(monkeypatch, requests, [], refused=True)
    def costly(messages, *args):
        for event in provider(messages, *args):
            yield {**event, 'cost_usd': studio_import.MAX_COST}
    monkeypatch.setattr(engine, '_provider', costly)
    run = engine.start(None, IMPORT_TURN, IMPORT_CHAT, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['stop_reason'] == 'cost_budget' and len(requests) < studio_import.MAX_ROUNDS
    assert run.answer['error'] == main_model.LIMIT_REACHED, 'a limit is said in plain words, as Randall'


@pytest.mark.parametrize('refusal, line', [
    (lambda: taskflow.BudgetExceeded('This task hit its usage limit.'), main_model.LIMIT_REACHED),
    (lambda: taskflow.TaskFinished('That task already finished as partial; it cannot spend more.'),
     main_model.ALREADY_FINISHED),
])
def test_a_refused_round_ends_the_turn_in_plain_words(vault, monkeypatch, refusal, line):
    """The coordinator's own sentences ("That task already finished as partial; it cannot spend more.") were the
    chat's last line in the 2026-10-06 runs. The turn still stops; the user reads Randall, not the task ledger."""
    def provider(messages, schemas, key, cancelled):
        raise refusal()
        yield
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Look at it', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'error' and run.answer['error'] == line
    assert 'task' not in line.lower() and 'ask again' in line.lower()


def test_an_empty_completion_is_nudged_instead_of_ending_the_turn(vault, monkeypatch):
    # After two large model tool
    # results the model spent its whole completion allowance thinking and came
    # back with no tool call and no words. `_announced_action('')` is False, so
    # the loop broke and the user was told nothing at all -- not what had been
    # done, not that anything had gone wrong.
    histories = []
    def provider(messages, *args):
        histories.append(len(messages))
        index = len(histories)
        if index == 1:
            yield from emit(calls=[tool_call(1)])
        elif index == 2:
            yield from emit('')
        else:
            assert 'empty' in messages[-1]['content']
            yield from emit('I looked at the mesh; here is what I found.')
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Look at it', {}, request_key='test')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done' and run.answer['empty_rounds'] == 1
    assert run.answer['content'].strip().endswith('here is what I found.')


def test_a_model_that_keeps_returning_nothing_stops_instead_of_looping(vault, monkeypatch):
    rounds = []
    def provider(messages, *args):
        rounds.append(1)
        yield from emit('')
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Look at it', {}, request_key='test')
    list(live_runs.stream(run))
    assert len(rounds) == engine.MAX_EMPTY_ROUNDS + 1
    assert run.answer['empty_rounds'] == engine.MAX_EMPTY_ROUNDS
