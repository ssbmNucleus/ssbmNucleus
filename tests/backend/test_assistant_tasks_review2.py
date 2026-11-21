"""One test per finding in ASTRA-REVIEW-S1-2.md, reproducing the reviewer's probe.

Kept apart from the first review's regressions so each finding stays traceable
to the run that found it: if one of these fails again, the item it names is back.
"""
import json
import threading

import pytest
import requests

from randall.assistant import engine, live_runs, prompt, recipes, tool_stage, tools, turn_facts
from randall.assistant.tasks import contracts, coordinator, stage_journal, store
from randall.assistant.tasks.contracts import UNKNOWN, CheckResult


@pytest.fixture(autouse=True)
def fresh(vault):
    store.close()
    coordinator.CURRENT.set(None)
    yield vault
    store.close()


class _Never:
    def is_set(self):
        return False


def emit(text='', calls=None, cost=None):
    yield {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
           **({'cost_usd': cost} if cost is not None else {}),
           'message': {'role': 'assistant', 'content': text or None,
                       **({'tool_calls': calls} if calls else {})}}


# ================================================================== item 1

def test_a_queued_follow_up_continues_the_task_instead_of_reviving_a_dead_one(vault, monkeypatch):
    """Probe: two paid spans under revision 1, and the durable task still said
    `success` from the first turn while the second answer failed."""
    from shared.aiengine import decisions
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        if len(rounds) == 1:
            yield from emit('First answer.', cost=0.001)
            return
        raise RuntimeError('the provider refused the follow-up')

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'first request', {}, request_key='k')
    # Queue a follow-up the way the UI does, while the first turn is in flight.
    live_runs.submit_input(run.chat_id, 'input-2', 'and also this', {}, 'queue')
    list(live_runs.stream(run))

    task_id = run.answer['task_id']
    saved = store.load_task(task_id)
    assert saved is not None
    # The follow-up ran under revision 2 of the SAME task...
    assert saved.revision == 2
    # ...and the durable outcome is the one the run actually ended with, not the
    # first turn's success left behind by a per-turn close.
    assert saved.outcome == 'failed' and saved.state == 'failed'
    assert len(store.model_spans(task_id)) == 2
    assert {s.task_revision for s in store.model_spans(task_id)} == {1, 2}


def test_a_finished_task_refuses_to_buy_anything_more():
    """Dispatch admission did not reject a terminal task."""
    task = coordinator.start('randall_turn')
    task.finish('success')
    with coordinator.attach(task):
        with pytest.raises(coordinator.TaskFinished):
            coordinator.run_model_request('main', lambda span: span.record_cost(0.001))
    assert store.model_spans(task.task_id) == []


def test_an_authoritative_task_failure_is_surfaced_not_swallowed(vault, monkeypatch):
    """`_guard` hid a refused revision, so nobody learned the record was stale."""
    from shared.aiengine import decisions
    monkeypatch.setattr(decisions, 'enabled', lambda: False)

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        yield from emit('Fine.', cost=0.001)

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'hello', {}, request_key='k')
    list(live_runs.stream(run))
    # A close that cannot persist must report itself on the answer.
    boom = coordinator.start('randall_turn')
    fake = type('R', (), {'answer': {'status': 'done', 'tools': []}, 'task': boom})()
    monkeypatch.setattr(boom, 'finish', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('nope')))
    engine._close_objective(fake)
    assert fake.answer['task_errors'][0]['stage'] == 'close'
    assert 'RuntimeError' in fake.answer['task_errors'][0]['error']


# ================================================================== item 2

def test_the_durable_ledger_carries_spend_through_a_second_continuation():
    """Probe: $0.149 -> blocked continuation -> $0 carried into the third task."""
    first = coordinator.start('model_import', chat_id='chat1', cost_budget_usd=0.2)
    with coordinator.attach(first):
        coordinator.run_model_request('main', lambda s: s.record_cost(0.149))
    first.envelope.facts['budget_exhausted'] = True
    first.finish('blocked')

    carried, calls = turn_facts._carried_ledger('chat1')
    assert carried == pytest.approx(0.149)

    # The SECOND task is refused before it dispatches, so it has no spans at all.
    second = coordinator.start('model_import', chat_id='chat1', cost_budget_usd=0.15,
                               carried_usd=carried, carried_calls=calls)
    with coordinator.attach(second):
        with pytest.raises(coordinator.BudgetExceeded):
            coordinator.run_model_request('main', lambda s: s.record_cost(0.01))
    second.envelope.facts['budget_exhausted'] = True
    second.finish('blocked')

    # ...and the THIRD continuation must still see the money, reconstructed
    # from the snapshot rather than from spans that do not exist.
    again, _calls = turn_facts._carried_ledger('chat1')
    assert again == pytest.approx(0.149), 'a spanless continuation dropped the carry'
    assert store.accounting(second.task_id)['committed_usd'] == pytest.approx(0.149)


def test_an_image_reserves_an_image_sized_amount_not_a_chat_round():
    """A $0.12 request was admitted under a $0.01 budget on a $0.003 reserve."""
    assert coordinator.ROLE_RESERVE_USD['image'] > coordinator.ROLE_RESERVE_USD['main']
    task = coordinator.start('recolor', cost_budget_usd=0.01)
    with coordinator.attach(task):
        with pytest.raises(coordinator.BudgetExceeded):
            coordinator.run_model_request('image', lambda s: s.record_cost(0.12))
    # The same budget still admits an ordinary chat round.
    with coordinator.attach(task):
        coordinator.run_model_request('main', lambda s: s.record_cost(0.001))


# ================================================================== item 3

def test_a_terminal_task_cannot_have_an_approval_settled_afterwards():
    """Probe: a durably cancelled task returned ('settled', 'approved')."""
    task = coordinator.start('menu_background_replace')
    request = task.ask('approval', allowed_responses=['approve', 'deny'],
                       operation_digest='sha256:a')
    task.finish('cancelled')
    with pytest.raises(store.SettlementRefused, match='already cancelled'):
        store.settle_request(request.id, 'approve', task_id=task.task_id)


def test_the_terminal_envelope_and_its_retirements_are_one_commit():
    """Interrupted between the two, SQLite held a cancelled task AND a pending
    approval -- and the approval was accepted."""
    task = coordinator.start('menu_background_replace')
    request = task.ask('approval', allowed_responses=['approve', 'deny'],
                       operation_digest='sha256:a')
    envelope = store.load_task(task.task_id)
    envelope.state, envelope.outcome = 'cancelled', 'cancelled'
    assert store.finish_task(envelope) == [request.id]
    row = store.task_row(task.task_id)
    assert row['state'] == 'cancelled'
    assert store.request_status(request.id) == 'cancelled'
    assert store.pending_requests(task.task_id) == []


# ================================================================== item 4

def test_a_billed_round_that_fails_validation_keeps_its_charge_and_identity():
    """Probe: a stream with a generation id and $0.04 of usage, then an invalid
    tool call, produced unknown cost and an empty generation id."""
    task = coordinator.start('randall_turn')

    def provider(*args, **kwargs):
        yield {'type': 'billing', 'generation_id': 'gen-9', 'model': 'glm', 'provider': 'fireworks'}
        yield {'type': 'billing', 'usage': {'prompt_tokens': 900, 'cost': 0.04},
               'cost_usd': 0.04, 'generation_id': 'gen-9'}
        raise RuntimeError('the provider returned an incomplete tool call')

    with coordinator.attach(task):
        with pytest.raises(RuntimeError):
            list(coordinator.traced_provider(provider, role='main')([], [], 'k', _Never()))
    span = store.model_spans(task.task_id)[0]
    assert span.status == 'error'
    assert span.reported_cost_usd == pytest.approx(0.04)
    assert span.provider_generation_id == 'gen-9' and span.resolved_provider == 'fireworks'
    assert store.accounting(task.task_id)['reported_usd'] == pytest.approx(0.04)


def test_a_dispatch_whose_attempt_row_cannot_be_written_does_not_happen(monkeypatch):
    """The crash-accounting guarantee must not rest on a best-effort write."""
    task = coordinator.start('randall_turn')
    sent = []
    monkeypatch.setattr(store, 'record_span',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('disk full')))
    with coordinator.attach(task):
        with pytest.raises(coordinator.DispatchNotRecorded):
            coordinator.run_model_request('main', lambda span: sent.append(1))
    assert sent == []
    # The reservation was released, so a later dispatch is not blocked by it.
    assert task.costs.open_usd == 0


def test_the_production_adapter_emits_its_charge_before_it_validates():
    """The `billing` event exists so the engine never has to wait for a
    completion that may never come."""
    import inspect
    source = inspect.getsource(engine._provider)
    assert "'type': 'billing'" in source
    billing = source.index("'type': 'billing'")
    completion = source.index("'type': 'completion'")
    assert billing < completion, 'the charge is handed over first'


# ================================================================== item 5

def test_a_failed_revision_leaves_memory_and_storage_agreeing():
    """Probe: an injected validation failure left live revision 2 / durable 1."""
    task = coordinator.start('menu_background_replace')
    task.envelope.achieved['installed'] = True        # invalid without `prepared`
    with pytest.raises(ValueError):
        task.revise('user_revision', 'changed')
    assert task.revision == 1
    assert store.current_revision(task.task_id) == 1
    assert store.load_task(task.task_id).revision == 1


def test_a_stale_context_fails_its_checkpoint_against_durable_state():
    """Probe: a separately loaded revision-1 context passed `checkpoint(1)`
    after SQLite had advanced to 2, because it was asking itself."""
    task = coordinator.start('menu_background_replace', task_id='t-shared')
    stale = coordinator.TaskContext(store.load_task('t-shared'))   # another holder
    task.revise('user_revision', 'the other build')
    assert stale.envelope.revision == 1                # its own memory is behind
    with pytest.raises(coordinator.RevisionSuperseded):
        stale.checkpoint(1)


def test_a_boundary_defaults_to_the_revision_its_work_began_under():
    """Capturing the CURRENT revision made every later boundary trivially true."""
    task = coordinator.start('menu_background_replace')
    with coordinator.attach(task), coordinator.work_unit(task.revision):
        task.checkpoint()                              # fine
        task.revise('user_revision', 'changed')
        with pytest.raises(coordinator.RevisionSuperseded):
            task.checkpoint()                          # no argument: still knows
        with pytest.raises(coordinator.RevisionSuperseded):
            stage_journal.run_stage('prepare', lambda _s: 'never', parameters={'a': 1})


# ================================================================== item 6

def test_a_blocking_check_outranks_a_failed_tool():
    """Probe: a required failed check plus a failed receipt returned `partial`."""
    task = coordinator.start('model_import')
    task.envelope.checks.append(CheckResult(check_id='extent_v1', implementation_version='1',
                                            status='fail'))
    run = type('R', (), {'answer': {'status': 'done', 'tools': [
        {'name': 'model_fit', 'status': 'error', 'result': {'error': 'no fit'}}]}})()
    assert turn_facts._turn_outcome(run, task)[0] == 'blocked'


def test_a_structured_blocked_result_without_a_top_level_error_is_not_success():
    """A tool returning its own envelope used to fall through to success."""
    task = coordinator.start('deliver_to_game')
    run = type('R', (), {'answer': {'status': 'done', 'tools': [
        {'name': 'deliver_to_game', 'status': 'done',
         'result': {'task_id': 't', 'state': 'completed', 'outcome': 'blocked',
                    'achieved': {'prepared': True, 'exported': False,
                                 'installed': False, 'previewed': False}}}]}})()
    assert turn_facts._turn_outcome(run, task)[0] == 'blocked'


@pytest.mark.parametrize('receipts,expected', [
    ([], 'success'),
    ([{'name': 'search_vault', 'status': 'done', 'result': {'items': []}}], 'success'),
    ([{'name': 'download_website_mod', 'status': 'cancelled',
       'result': {'approval_status': 'denied'}}], 'denied'),
    ([{'name': 'a', 'status': 'error', 'result': {'error': 'x'}},
      {'name': 'b', 'status': 'done', 'result': {}}], 'partial'),
    ([{'name': 'a', 'status': 'cancelled', 'result': {'approval_status': 'denied'}},
      {'name': 'b', 'status': 'error', 'result': {'error': 'x'}}], 'partial'),
])
def test_the_outcome_is_the_worst_thing_that_happened(receipts, expected):
    task = coordinator.start('randall_turn')
    run = type('R', (), {'answer': {'status': 'done', 'tools': receipts}})()
    assert turn_facts._turn_outcome(run, task)[0] == expected


# ================================================================== item 7


# ================================================================== item 8

def test_repairs_are_clamped_however_many_a_caller_asks_for():
    """Probe: `repairs=10` allowed 11 dispatches."""
    task = coordinator.start('randall_turn')
    attempts = []

    def call(span):
        attempts.append(span.attempt)
        raise coordinator.InvalidResponse('did not parse')

    with coordinator.attach(task):
        with pytest.raises(coordinator.InvalidResponse):
            coordinator.run_model_request('vision', call, repairs=10, sleep=lambda _s: None)
    assert len(attempts) == 1 + coordinator.MAX_REPAIR_ATTEMPTS == 2


def test_a_repair_does_not_spend_the_outage_allowance():
    """Probe: `invalid -> transient -> transient` stopped before the fourth."""
    task = coordinator.start('randall_turn')
    attempts = []
    script = [coordinator.InvalidResponse('bad json'),
              coordinator.ProviderHTTPError('502', http_status=502),
              coordinator.ProviderHTTPError('502', http_status=502)]

    def call(span):
        attempts.append(span.attempt)
        if script:
            raise script.pop(0)
        return 'answer'

    with coordinator.attach(task):
        assert coordinator.run_model_request('vision', call, sleep=lambda _s: None) == 'answer'
    assert len(attempts) == 4, 'one repair plus the full two-retry outage allowance'


def test_an_image_transport_timeout_keeps_its_transient_classification():
    from shared.aiengine import image_api
    transient = image_api._Transient(400)
    assert coordinator.classify(transient) == 'transient'
    assert getattr(transient, 'transient', None) is True


# ================================================================== item 9

def test_a_read_only_action_inside_an_effectful_tool_is_not_journalled():
    """Probe: a second `test_in_game(action='status')` returned the FIRST
    snapshot and executed only once."""
    status = tools.PreparedCall('test_in_game', json.dumps({'action': 'status'}),
                                '{}', '{}', 'automatic')
    launch = tools.PreparedCall('test_in_game', json.dumps({'action': 'start'}),
                                '{}', '{}', 'automatic')
    assert tool_stage._is_effectful(status) is False
    assert tool_stage._is_effectful(launch) is True


def test_a_tool_that_returned_an_error_is_a_failed_stage_and_a_failed_effect(vault, monkeypatch):
    from shared.aiengine import decisions
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    monkeypatch.setitem(tools.REGISTRY, 'save_mod_copy',
                        tools.ToolSpec('automatic', lambda **_: {'error': 'no such file'}))
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        if len(rounds) == 1:
            yield from emit('Saving.', calls=[{'id': 'c1', 'type': 'function', 'function': {
                'name': 'save_mod_copy',
                'arguments': json.dumps({'file_id': 'f', 'name': 'n'})}}])
            return
        yield from emit('It did not work.')

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'save a copy', {}, request_key='k')
    list(live_runs.stream(run))
    stage = next(s for s in store.stage_spans(run.answer['task_id'])
                 if s.stage_name == 'tool:save_mod_copy')
    assert stage.status == 'error' and stage.error_type == 'tool_error'
    # ...and it is not journalled as a completed effect, so a retry may run it.
    entries = store.connect().execute(
        'SELECT status FROM tool_journal WHERE task_id=?', (run.answer['task_id'],)).fetchall()
    assert [row['status'] for row in entries] == ['failed']


def test_a_failed_stage_never_enters_a_duration_estimate():
    task = coordinator.start('randall_turn')
    with coordinator.attach(task):
        for _ in range(5):
            with pytest.raises(RuntimeError):
                with stage_journal.stage('tool:flaky'):
                    raise RuntimeError('no')
    assert store.stage_duration_estimate('tool:flaky') == (None, 0)


def test_a_reused_result_is_not_charged_a_second_time(vault, monkeypatch):
    """Probe: one $0.04 dispatch; ledger $0.04; displayed cost $0.08."""
    from shared.aiengine import decisions
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    calls = []
    monkeypatch.setitem(tools.REGISTRY, 'generate_material', tools.ToolSpec(
        'automatic', lambda **kw: calls.append(1) or {'cost_usd': 0.04, 'material_file_id': 'm1'}))
    arguments = json.dumps({'prompt': 'denim'})
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        if len(rounds) <= 2:
            yield from emit('Generating.', calls=[{'id': f'c{len(rounds)}', 'type': 'function',
                                                   'function': {'name': 'generate_material',
                                                                'arguments': arguments}}])
            return
        yield from emit('Done.')

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'make a denim material', {}, request_key='k')
    list(live_runs.stream(run))
    assert len(calls) == 1, 'the second identical request reused the first'
    assert run.answer['cost_parts'].get('images') == pytest.approx(0.04)
    assert run.answer['tools'][1].get('reused_operation') is True


# ================================================================== item 10

def test_the_envelope_travels_inside_the_receipt_where_the_cards_read_it(randall_run):
    """B2's reducer keeps `event.tool` and discards a sibling `event.task`, and
    `envelopeOf` looks at `tool.task`."""
    run, seen = randall_run
    tool_events = [e for e in seen if e['type'] in ('tool_start', 'tool_result')]
    assert tool_events
    for event in tool_events:
        envelope = event['tool'].get('task')
        assert envelope is not None, 'the card reads the envelope off the TOOL'
        assert envelope['task_id'] == run.answer['task_id']
        assert set(envelope) >= {'state', 'outcome', 'achieved', 'checks', 'limitations',
                                 'next', 'receipts', 'wish_ids', 'facts', 'artifacts',
                                 'workflow', 'error'}


def test_the_round_limit_reaches_the_card_through_envelope_facts(randall_run):
    """`applyTurnProgress` drops `round_limit`, so facts carry it."""
    run, seen = randall_run
    assert run.answer.get('round_limit') is None or isinstance(run.answer['round_limit'], int)
    envelopes = [e['tool']['task'] for e in seen
                 if e['type'] == 'tool_result' and e['tool'].get('task')]
    assert envelopes
    assert all('facts' in envelope for envelope in envelopes)


def test_the_final_envelope_is_published_after_the_task_actually_closed(randall_run):
    run, seen = randall_run
    done = [e for e in seen if e['type'] == 'done'][-1]
    envelope = done['message'].get('task')
    assert envelope is not None
    assert envelope['state'] in contracts.TERMINAL_STATES
    assert envelope['outcome'] == store.load_task(run.answer['task_id']).outcome


def test_a_stop_accepted_while_the_turn_finishes_ends_it_cancelled(vault, monkeypatch):
    """F-D-2: a Stop during the final autosave (anything in the turn's finally) is not lost."""
    from shared.aiengine import decisions
    from randall.model_import.chat import studio_import
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    holder, ready = {}, threading.Event()

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        ready.wait(5)
        yield from emit('Done.')

    def stop_while_finishing(answer, **kwargs):
        holder['run'].cancelled.set()       # the Stop route, while the finalizer still runs
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(studio_import, 'record_turn', stop_while_finishing)
    run = engine.start(None, 'hello', {}, request_key='k')
    holder['run'] = run
    ready.set()
    list(live_runs.stream(run))
    assert run.answer['status'] == 'cancelled'
    assert store.load_task(run.answer['task_id']).outcome == 'cancelled'


def test_the_saved_chat_has_the_final_envelope_the_stream_ended_with(randall_run):
    """F-D-8: the reload right after `done` reads the chat store, so the
    terminal card must be saved there, not only sent on the stream."""
    from randall.assistant import store as chat_store
    run, seen = randall_run
    done = [e for e in seen if e['type'] == 'done'][-1]['message']
    saved = [m for m in chat_store.get(run.chat_id)['messages'] if m.get('id') == done['id']]
    assert saved and saved[0].get('task') == done['task']
    assert saved[0]['task']['state'] in contracts.TERMINAL_STATES


@pytest.fixture
def randall_run(vault, monkeypatch):
    from shared.aiengine import decisions
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        if len(rounds) == 1:
            yield from emit('Looking.', calls=[{'id': 'c1', 'type': 'function', 'function': {
                'name': 'search_vault', 'arguments': json.dumps({'query': 'goku'})}}])
            return
        yield from emit('Found it.')

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'find my goku costume', {}, request_key='k')
    seen = [json.loads(line[6:]) for line in live_runs.stream(run) if line.startswith('data: ')]
    return run, seen


# ================================================================== item 11

def test_an_estimate_needs_three_comparable_successful_samples():
    task = coordinator.start('randall_turn')
    parameters = {'arguments': '{"query": "a"}'}
    with coordinator.attach(task):
        for _ in range(2):
            with stage_journal.stage('tool:search_vault', parameters=parameters):
                pass
    assert store.stage_duration_estimate('tool:search_vault')[0] is None
    with coordinator.attach(task):
        with stage_journal.stage('tool:search_vault', parameters=parameters):
            pass
    estimate, samples = store.stage_duration_estimate('tool:search_vault')
    assert estimate is not None and samples == 3


def test_different_parameters_do_not_share_one_estimate():
    task = coordinator.start('randall_turn')
    with coordinator.attach(task):
        for _ in range(4):
            with stage_journal.stage('tool:model_render', parameters={'poses': 1}):
                pass
    assert store.stage_duration_estimate('tool:model_render', parameter_hash=contracts.digest(
        {'poses': 1}))[1] == 4
    assert store.stage_duration_estimate('tool:model_render', parameter_hash=contracts.digest(
        {'poses': 9}))[1] == 0


def test_a_reused_stage_contributes_nothing_to_an_estimate():
    task = coordinator.start('model_import', task_id='t-est')
    with coordinator.attach(task):
        for _ in range(4):
            stage_journal.run_stage('fit', lambda _s: {'ok': True}, parameters={'donor': 'fox'})
    # One real execution and three reuses: not enough real samples.
    assert store.stage_duration_estimate(
        'fit', parameter_hash=contracts.digest({'donor': 'fox'})) == (None, 1)


def test_the_configuration_snapshot_pins_every_participating_role(randall_run):
    run, _seen = randall_run
    snapshot = json.loads(store.task_row(run.answer['task_id'])['config_snapshot'])
    for key in ('main_model', 'jev_model', 'jev_enabled', 'fast_lane_model', 'image_model',
                'prompt_version', 'recipes_version', 'tool_schema_version',
                'coordinator_version'):
        assert key in snapshot, key


# =================================================== prompt-review items 1-3

def test_the_recolor_card_says_edits_are_made_and_report_their_reach():
    # 2026-10-04: the scope refusal and its ask-the-user step are gone (test_assistant_prompt has the rest).
    card = ' '.join(recipes.CARDS['recolor_part'].split())
    assert 'Every edit is made' in card and 'also_changed' in card
    assert 'refuses' not in card and 'ask FIRST' not in card


def test_a_card_drops_an_operation_a_gate_switched_off(monkeypatch):
    spec = tools.REGISTRY['generate_material']
    monkeypatch.setitem(tools.REGISTRY, 'generate_material',
                        spec.__class__('disabled', spec.run, None, None))
    card = recipes.card('recolor_part', tools.SCHEMAS)
    assert 'skin_material(' in card and 'generate_material(' not in card


def test_both_generated_code_entry_points_are_refused_by_the_executor():
    # The old import's two code-running tools are gone with it: a remembered name is refused.
    with pytest.raises(tools.UnknownTool):
        tools.prepare('model_script', json.dumps({'candidate_id': 'c', 'script': 'x'}))
    with pytest.raises(tools.UnknownTool):
        tools.prepare('model_probe', json.dumps({'candidate_id': 'c', 'script': 'x'}))
    offered = {s['function']['name'] for s in tools.SCHEMAS}
    assert 'model_script' not in offered
    assert 'There is no generated-code mode.' in prompt.PROMPT


# =============================================== S2 release approval transport

