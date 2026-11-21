"""Acceptance: one ordinary Randall task produces one complete trace.

From ASTRA-CONSULT-2.md, session 1:

    "one ordinary Randall task produces a trace covering Jev, main/vision calls,
     a local stage, and a simulated 502 retry; charges and attempts are not lost
     or double-counted."

Every OpenRouter call is monkeypatched, so this costs nothing and is
deterministic -- but the pipeline underneath is real: `engine.start` runs the
actual turn loop, the tool call goes through the real `tools.prepare` /
`tools.execute`, the local stage hashes real bytes from disk, and the Jev and
main spans come from the production hooks in `shared/aiengine/decisions.py` and
`assistant/engine.py` rather than from anything this test wrote. (The vision
request the consult named was the old model import's; it went with it.)
"""
import json
import shutil

import pytest
import requests

from shared.aiengine import decisions
from randall.assistant import engine, live_runs, main_model, tools, turn_facts
from randall.assistant.tasks import contracts, coordinator, events, stage_journal, store

class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}', response=self)


def emit(text='', calls=None, usage=None, cost=None):
    if text:
        yield {'type': 'delta', 'content': text}
    event = {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
             'message': {'role': 'assistant', 'content': text or None,
                         **({'tool_calls': calls} if calls else {})}}
    if usage is not None:
        event['usage'] = usage
    if cost is not None:
        event['cost_usd'] = cost
    yield event


def http_502():
    response = requests.Response()
    response.status_code = 502
    return requests.HTTPError('HTTP 502 provider_unavailable', response=response)


@pytest.fixture
def stage_input(tmp_path):
    """The local stage's real input. Any file will do: the stage copies and hashes it."""
    path = tmp_path / 'costume.zip'
    path.write_bytes(bytes(range(256)) * 4)
    return path


@pytest.fixture
def randall(vault, monkeypatch, tmp_path, stage_input):
    """One turn's worth of stand-ins for every paid call the turn would make."""
    store.close()
    coordinator.CURRENT.set(None)
    decisions.reset()
    for _mod in (engine, main_model):
        monkeypatch.setattr(_mod, 'MODEL', 'z-ai/glm-5.3-flash')
    calls = {'jev': 0, 'main': 0}

    # -- Jev: the turn's first paid request, through the real decisions._ask.
    class JevSession:
        def post(self, url, **kwargs):
            calls['jev'] += 1
            return FakeResponse({
                'id': 'gen-jev-1', 'model': decisions.MODEL,
                'answers': {name: {'type': 'noul', 'noul': 0.9} for name in
                            ('wants_vanilla', 'wants_website', 'variant_named')},
                'usage': {'prompt_tokens': 420, 'completion_tokens': 8, 'cost': 0.00012}})

    monkeypatch.setattr(decisions, '_session', JevSession)
    monkeypatch.setattr(decisions, 'enabled', lambda: True)

    # -- Main model: the first request dies on a provider 502 BEFORE it streams
    #    anything, which is exactly the failure that killed two runs in the
    #    measured experiment. The traced provider re-sends it.
    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        calls['main'] += 1
        if calls['main'] == 1:
            raise http_502()
        if calls['main'] == 2:
            yield from emit('Looking for that costume.',
                            calls=[{'id': 'c1', 'type': 'function', 'function': {
                                'name': 'search_vault', 'arguments': json.dumps({'query': 'goku'})}}],
                            usage={'prompt_tokens': 9000, 'completion_tokens': 40,
                                   'prompt_tokens_details': {'cached_tokens': 7000}},
                            cost=0.0021)
            return
        yield from emit('The Goku Fox costume is in your vault.',
                        usage={'prompt_tokens': 9600, 'completion_tokens': 60}, cost=0.0013)

    monkeypatch.setattr(engine, '_provider', provider)

    # -- The tool round does what a workflow will do in a later session: a real
    #    local stage over real bytes.
    #    Wrapping `tools.execute` (rather than replacing it) keeps the actual
    #    prepare/validate/execute path in the turn.
    real_execute = tools.execute

    def execute(call, grant=None, **options):
        with stage_journal.stage('stage_costume', version='1',
                                 parameters={'query': 'goku'}) as span:
            result = real_execute(call, grant, **options)
            staged = store.artifact_dir(coordinator.current().task_id) / stage_input.name
            shutil.copyfile(stage_input, staged)
            span.output_artifact_hashes = [contracts.digest(staged.read_bytes())]
            span.cleanup_result = 'none needed'
        return result

    monkeypatch.setattr(tools, 'execute', execute)
    return calls


def run_turn():
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    list(live_runs.stream(run))
    return run


def test_one_randall_turn_produces_one_complete_trace(randall, stage_input):
    run = run_turn()
    assert run.answer['status'] == 'done'
    assert run.answer['task_id'] and run.task is not None
    task_id = run.answer['task_id']

    # -- the task itself
    saved = store.load_task(task_id)
    assert saved.state == 'completed' and saved.outcome == 'success'
    assert store.task_row(task_id)['request'] == 'Find my Goku Fox costume'
    assert store.task_row(task_id)['chat_id'] == run.chat_id
    snapshot = json.loads(store.task_row(task_id)['config_snapshot'])
    assert snapshot['main_model'] == 'z-ai/glm-5.3-flash'

    # -- every role the turn used is in the trace
    spans = store.model_spans(task_id)
    roles = [s.role for s in spans]
    assert 'jev' in roles and 'main' in roles
    assert randall == {'jev': 1, 'main': 3}
    assert saved.receipts and saved.receipts[0]['tool'] == 'search_vault'
    assert snapshot['jev_model'] and snapshot['fast_lane_model']
    assert snapshot['prompt_version'] and snapshot['tool_schema_version']

    jev = next(s for s in spans if s.role == 'jev')
    assert jev.requested_model == decisions.MODEL and jev.provider_generation_id == 'gen-jev-1'
    assert jev.input_tokens == 420 and jev.reported_cost_usd == 0.00012
    assert jev.response_validation == 'valid' and jev.status == 'ok'

    # -- the local stage, with its real input and output hashes
    stages = store.stage_spans(task_id)
    # Two overlapping stages: the engine's own tool stage (review item 6) and
    # the local stage the tool opens inside it. Their start times are within one
    # clock tick of each other, so they are compared as a set -- overlapping
    # spans have no total order, which is exactly why the report separates them.
    assert {s.stage_name for s in stages} == {'tool:search_vault', 'stage_costume'}
    stage = next(s for s in stages if s.stage_name == 'stage_costume')
    assert stage.status == 'ok' and stage.duration_ms >= 0
    assert stage.output_artifact_hashes == [contracts.digest(stage_input.read_bytes())]
    assert stage.parameter_hash == contracts.digest({'query': 'goku'})
    assert stage.worker_identity and stage.cpu_time_ms is not None
    assert (store.artifact_dir(task_id) / stage_input.name).is_file()

    # -- the tool really ran through prepare/execute
    receipts = run.answer['tools']
    assert [r['name'] for r in receipts] == ['search_vault']
    assert receipts[0]['status'] == 'done' and 'error' not in receipts[0]['result']


def test_the_502_is_two_attempts_and_the_charges_are_not_double_counted(randall):
    run = run_turn()
    task_id = run.answer['task_id']
    main = [s for s in store.model_spans(task_id) if s.role == 'main']

    # The failed attempt and its retry are separate spans of the SAME round.
    assert [s.attempt for s in main] == [1, 2, 1]
    assert [s.status for s in main] == ['error', 'ok', 'ok']
    failed = main[0]
    assert failed.retry_classification == 'transient' and '502' in failed.provider_error
    assert failed.reported_cost_usd is contracts.UNKNOWN      # it never billed: not zero, unknown
    assert main[1].retry_delay_ms is not None                 # the backoff actually happened

    # Two paid rounds, charged once each. Nothing is lost, nothing is doubled.
    book = store.accounting(task_id)
    assert book['attempts'] == 4                              # jev + 3 main
    assert book['billed_attempts'] == 3
    assert book['reported_usd'] == round(0.00012 + 0.0021 + 0.0013, 8)
    assert book['unknown_requests'] == 1 and book['total_usd'] == 'unknown'
    assert book['coverage'] == 0.75
    # addendum (b): the unreported charge is held against the budget as pending,
    # not dropped -- so a provider that stops reporting cannot make the guard free.
    assert book['pending_usd'] > 0
    assert book['committed_usd'] == round(book['reported_usd'] + book['pending_usd'], 8)

    # The engine's own per-answer total is the same money seen from the other side.
    assert run.answer['cost_parts']['main'] == round(0.0021 + 0.0013, 6)
    assert run.answer['tokens']['cached'] == 7000

    retried = [e for e in store.events(task_id) if e['type'] == events.MODEL_REQUEST_RETRIED]
    assert len(retried) == 1 and retried[0]['attempt'] == 1 and retried[0]['delay_ms'] >= 0


def test_the_trace_exports_as_jsonl_a_grader_can_read(randall, tmp_path):
    run = run_turn()
    task_id = run.answer['task_id']
    path = store.export_trace(task_id, tmp_path / 'turn.jsonl')
    lines = store.read_trace(path)

    head = lines[0]
    assert head['record'] == 'task' and head['task']['task_id'] == task_id
    assert head['task']['outcome'] == 'success'
    assert head['accounting']['attempts'] == 4
    assert head['accounting']['unresolved_attempts'] == 0
    assert head['accounting']['total_usd'] == 'unknown'       # the 502's charge is still open
    assert head['contracts_version'] == contracts.CONTRACTS_VERSION

    spans = [line for line in lines if line['record'] == 'span']
    assert {s['role'] for s in spans if s['kind'] == 'model'} == {'jev', 'main'}
    # The REAL tool execution is a stage of its own now (review item 6), beside
    # the local stage this test's tool wrapper opens.
    assert {s['stage_name'] for s in spans if s['kind'] == 'stage'} ==         {'tool:search_vault', 'stage_costume'}
    # The missing charge is visible as the word, not as a plausible 0.0.
    assert any(s.get('reported_cost_usd') == 'unknown' for s in spans)

    kinds = {line['record'] for line in lines}
    assert {'task', 'revision', 'span', 'stage', 'event'} <= kinds
    assert all(json.loads(raw)['record'] for raw in path.read_text(encoding='utf-8').strip().split('\n'))


def test_a_second_turn_is_a_second_task_not_an_appended_one(randall):
    first = run_turn()
    randall.update(jev=0, main=0)      # the stand-in replays the same script
    second = run_turn()
    assert first.answer['task_id'] != second.answer['task_id']
    # Each turn's four requests are attributed to its own task, not pooled.
    assert len(store.model_spans(first.answer['task_id'])) == 4
    assert len(store.model_spans(second.answer['task_id'])) == 4
    assert store.accounting(first.answer['task_id']) == store.accounting(second.answer['task_id'])
    assert store.unfinished_tasks() == []


def test_a_cancelled_turn_finishes_its_task_as_cancelled(vault, monkeypatch):
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        cancelled.set()
        yield from emit('stopping', cost=0.0005)

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'cancelled'
    saved = store.load_task(run.answer['task_id'])
    assert (saved.state, saved.outcome) == ('cancelled', 'cancelled')


def test_a_failing_turn_records_the_failure_rather_than_a_silent_success(vault, monkeypatch):
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        raise RuntimeError('the provider refused this key')
        yield                                           # pragma: no cover - generator marker

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    list(live_runs.stream(run))
    assert run.answer['status'] == 'error'
    saved = store.load_task(run.answer['task_id'])
    assert (saved.state, saved.outcome) == ('failed', 'failed') and saved.error
    span = store.model_spans(run.answer['task_id'])[0]
    assert span.status == 'error' and span.retry_classification == 'permanent'


# --------------------------------------------------------- review item 1

def test_a_real_openrouter_502_is_retried_by_the_production_adapter(vault, monkeypatch):
    """review item 1: only HTTP transport is replaced, so `_provider` is real.

    The previous acceptance test swapped `_provider` for a stand-in that raised
    `requests.HTTPError`, which hid the fact that the real adapter turned every
    HTTP failure into a plain RuntimeError the retry policy called permanent.
    Executing the repository's own provider with a faked 502 produced exactly
    one request.
    """
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    # An ordinary turn never reaches the fast lane, so the transport stub below
    # sees the MAIN adapter's requests only.
    posts = []

    class Stream:
        """The minimum `requests.post(..., stream=True)` contract `_provider` uses."""

        def __init__(self, status, lines=()):
            self.status_code = status
            self._lines = list(lines)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_lines(self, chunk_size=1):
            return iter(self._lines)

    def post(url, **kwargs):
        posts.append(url)
        if len(posts) == 1:
            return Stream(502)                        # provider_unavailable
        chunks = [
            b'data: ' + json.dumps({'id': 'gen-real-1', 'model': 'z-ai/glm-5.3-flash',
                                    'provider': 'fireworks',
                                    'choices': [{'delta': {'content': 'Recovered.'}}]}).encode(),
            b'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}],
                                    'usage': {'prompt_tokens': 12, 'completion_tokens': 3,
                                              'cost': 0.0007}}).encode(),
            b'data: [DONE]']
        return Stream(200, chunks)

    monkeypatch.setattr(main_model.requests, 'post', post)
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    list(live_runs.stream(run))

    assert run.answer['status'] == 'done'
    assert len(posts) == 2                            # the 502 WAS retried
    spans = store.model_spans(run.answer['task_id'])
    main = [s for s in spans if s.role == 'main']
    assert [s.attempt for s in main] == [1, 2]
    assert main[0].status == 'error' and main[0].retry_classification == 'transient'
    assert main[0].http_status is None or main[0].http_status == 502
    assert len({s.decision_id for s in main}) == 1     # one round, two requests
    # review item 7: the adapter keeps the provider's own identity.
    assert main[1].provider_generation_id == 'gen-real-1'
    assert main[1].resolved_provider == 'fireworks'
    assert main[1].reported_cost_usd == 0.0007


def test_a_real_permanent_http_failure_is_not_retried(vault, monkeypatch):
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    posts = []

    class Stream:
        status_code = 401

        def __enter__(self):
            posts.append(1)
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(main_model.requests, 'post', lambda url, **kwargs: Stream())
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    list(live_runs.stream(run))
    assert len(posts) == 1                            # a bad key is not an outage
    assert run.answer['status'] == 'error'
    span = store.model_spans(run.answer['task_id'])[0]
    assert span.retry_classification == 'permanent'


# --------------------------------------------------------- review item 6

def test_a_reply_explaining_a_failed_tool_is_not_a_successful_task(randall, monkeypatch):
    """review item 6: `answer.status == done` was mapped straight to success."""
    from randall.assistant import tools
    monkeypatch.setitem(tools.REGISTRY, 'search_vault',
                        tools.ToolSpec('automatic', lambda **_: {'error': 'no such costume'}))
    run = run_turn()
    assert run.answer['status'] == 'done'             # Randall answered politely
    saved = store.load_task(run.answer['task_id'])
    assert saved.outcome == 'partial'                 # but nothing was achieved
    assert saved.achieved == {'prepared': False, 'exported': False,
                              'installed': False, 'previewed': False}
    assert saved.receipts[0]['failed'] is True


def test_real_tool_execution_is_a_stage_in_the_trace(vault, monkeypatch):
    """review item 6: the acceptance test used to supply its own stage."""
    # Not the `randall` fixture: its wrapper is not wanted here, and undoing it
    # with monkeypatch.undo() also undid `vault`, so the turn wrote its chat and
    # searched the metadata in the developer's real storage.
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        if len(rounds) == 1:
            yield from emit('Looking.', calls=[{'id': 'c1', 'type': 'function', 'function': {
                'name': 'search_vault', 'arguments': json.dumps({'query': 'goku'})}}], cost=0.001)
            return
        yield from emit('Found it.', cost=0.001)

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    list(live_runs.stream(run))
    stages = store.stage_spans(run.answer['task_id'])
    assert [s.stage_name for s in stages] == ['tool:search_vault']
    assert stages[0].status == 'ok' and stages[0].duration_ms >= 0
    assert stages[0].input_artifact_hashes                 # the arguments, hashed


def test_an_effectful_tool_is_journalled_and_never_runs_twice(vault, monkeypatch):
    """review item 6 / the journal guarantee, through the real engine loop."""
    from randall.assistant import tools
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    saves = []
    monkeypatch.setitem(tools.REGISTRY, 'save_mod_copy', tools.ToolSpec(
        'automatic', lambda **kwargs: saves.append(kwargs) or {'saved': 'copy-1'}))
    monkeypatch.setattr(tools, 'SCHEMAS', [s for s in tools.SCHEMAS], raising=False)
    call = {'id': 'c1', 'type': 'function', 'function': {
        'name': 'save_mod_copy', 'arguments': json.dumps({'file_id': 'edited-goku', 'name': 'Goku copy'})}}
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        if len(rounds) <= 2:
            yield from emit('Saving.', calls=[dict(call, id=f'c{len(rounds)}')], cost=0.001)
            return
        yield from emit('Saved.', cost=0.001)

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'Save a copy of the goku costume', {}, request_key='test-key')
    list(live_runs.stream(run))
    # The model asked twice with identical arguments; the effect happened once.
    receipts = [r for r in run.answer['tools'] if r['name'] == 'save_mod_copy']
    assert len(receipts) == 2 and len(saves) == 1
    assert receipts[1]['result'] == {'saved': 'copy-1'}        # the first run's record


# --------------------------------------------------- addendum (a)/(b)/(d)

def test_the_spending_guard_reads_the_coordinator_ledger(vault, monkeypatch):
    """addendum (b): an unreported charge must still count against the limit."""
    from randall.model_import.chat import studio_import
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    monkeypatch.setattr(studio_import, 'execute', lambda call, key=None, progress=None, cancelled=None: {'studio_import': {
        'tool': call.name[len(studio_import.PREFIX):], 'id': json.loads(call.arguments)['source']}})
    # A model import turn: import_model and the import budget.
    rounds = []

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        rounds.append(1)
        yield from emit('Working.', calls=[{'id': f'c{len(rounds)}', 'type': 'function', 'function': {
            'name': 'import_model', 'arguments': json.dumps({'source': f'p{len(rounds)}'})}}])
        # no cost reported at all

    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'import this model', {'task': 'model_import'}, request_key='test-key')
    list(live_runs.stream(run))
    # The turn stops: unreported charges accumulate as pending against the cap
    # instead of reading as free.
    assert run.answer.get('cost_usd', 0) == 0          # nothing was ever REPORTED
    assert run.answer['committed_usd'] > 0             # but the ledger is not empty
    assert run.answer['stop_reason'] in ('cost_budget', 'round_budget')


def test_the_import_wrap_up_never_asks_for_an_export_to_meet_a_budget():
    """addendum (d): a budget must not buy a weaker acceptance bar."""
    from randall.model_import.chat import studio_import
    note = studio_import.WRAP_UP_NOTE.lower()
    assert 'call no more tools' in note and 'export' not in note     # it stops; it never asks for an export


def test_a_budget_blocked_turn_carries_its_spend_into_the_next_one(vault, monkeypatch):
    """addendum (c): "continue" must not silently reset the limit."""
    store.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)

    def provider(messages, schemas, key, cancelled, *args, **kwargs):
        yield from emit('Done.', cost=0.0)

    monkeypatch.setattr(engine, '_provider', provider)
    first = engine.start(None, 'import this model', {}, request_key='test-key')
    list(live_runs.stream(first))
    task = store.load_task(first.answer['task_id'])
    # Mark it as the budget-blocked attempt the user is about to continue.
    task.facts['budget_exhausted'] = True
    task.state, task.outcome = 'completed', 'blocked'
    store.save_task(task)
    carried, calls = turn_facts._carried_ledger(first.chat_id)
    assert carried >= 0 and calls >= 1
    # A brand new conversation starts clean; the same one does not.
    assert turn_facts._carried_ledger('a-different-chat') == (0.0, 0)


# ------------------------- builder W's outcome precedence (also review item 6)

def test_a_turn_that_recorded_a_blocking_check_is_blocked_not_successful(randall):
    """A required check nobody could measure means nobody knows it worked."""
    from randall.assistant.tasks.contracts import CheckResult
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    # The task exists as soon as the worker attaches it; record against it the
    # way a workflow would, before the turn settles.
    while run.task is None and run.answer['status'] == 'running':
        pass
    run.task.envelope.checks.append(CheckResult(check_id='extent_v1', implementation_version='1',
                                                status='unknown'))
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done'            # the reply itself finished fine
    assert store.load_task(run.answer['task_id']).outcome == 'blocked'


def _note_unmet(envelope, classification):
    """Write the envelope fact `turn_facts` reads for a missing required operation."""
    from randall.reports import wishes as wishlib
    envelope.facts.setdefault(wishlib.UNMET_FACT, []).append(
        {'capability': classification.capability,
         'blocked_operation': classification.blocked_operation,
         'implementation_version': classification.implementation_version,
         'variant': classification.variant})


def test_a_turn_that_lacked_a_required_operation_is_blocked_not_successful(randall):
    """A turn that hit a capability gap did not do what was asked.

    Read from the ENVELOPE's typed fact, not from `wish_ids`: builder W's point
    is that the outcome must not depend on whether the wish row reached SQLite,
    and a facade that records its own gap never touches this task at all.
    """
    from randall.reports import wishes as wishlib
    run = engine.start(None, 'Find my Goku Fox costume', {}, request_key='test-key')
    while run.task is None and run.answer['status'] == 'running':
        pass
    verdict = wishlib.classify_blocker(
        wishlib.Observation(evidence='operation_unavailable', operation='render_menu_artifact',
                            variant='character_select'),
        wishlib.Requirement(operation='render_menu_artifact', required_for_outcome=True,
                            workflow='install_menu'))
    _note_unmet(run.task.envelope, verdict)
    list(live_runs.stream(run))
    assert run.answer['status'] == 'done'            # the reply itself finished fine
    assert store.load_task(run.answer['task_id']).outcome == 'blocked'


def test_outcome_precedence_is_blocked_then_partial_then_success():
    """Builder W's ordering, checked directly.

    A failed or unmeasured required check and a missing required operation both
    mean nobody knows whether what ran was correct, so neither may be softened
    into `partial` by a later branch.
    """
    from randall.reports import wishes as wishlib
    from randall.assistant.tasks.contracts import CheckResult
    from types import SimpleNamespace
    clean = SimpleNamespace(answer={'status': 'done', 'tools': []}, task=None)
    assert turn_facts._turn_outcome(clean, None) == ('success', None)

    task = coordinator.start('randall_turn', chat_id=None)
    assert turn_facts._turn_outcome(clean, task)[0] == 'success'
    _note_unmet(task.envelope, wishlib.classify_blocker(
        wishlib.Observation(evidence='operation_unavailable', operation='render_menu_artifact'),
        wishlib.Requirement(operation='render_menu_artifact', required_for_outcome=True)))
    assert turn_facts._turn_outcome(clean, task)[0] == 'blocked'

    checked = coordinator.start('randall_turn', chat_id=None)
    checked.envelope.checks.append(CheckResult(check_id='extent_v1', implementation_version='1',
                                               status='fail'))
    assert turn_facts._turn_outcome(clean, checked)[0] == 'blocked'

    # A turn whose tool failed but which lacked nothing required is partial.
    partial = SimpleNamespace(
        answer={'status': 'done', 'tools': [{'name': 'search_vault', 'status': 'error',
                                             'result': {'error': 'no such costume'}}]},
        task=None)
    assert turn_facts._turn_outcome(partial, coordinator.start('randall_turn'))[0] == 'partial'
