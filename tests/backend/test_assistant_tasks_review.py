"""One test per finding in ASTRA-REVIEW-S1.md, reproducing the reviewer's probe.

Each test names the item it pins. They are kept apart from the original
coordinator tests so the relationship between a finding and its regression stays
readable: if one of these fails again, the review item it names has come back.
"""
import base64
import json
import threading
import time

import pytest
import requests

from randall.assistant.tasks import (content_hash, contracts, coordinator, events, stage_journal,
                                     store)
from randall.assistant.tasks.contracts import UNKNOWN, CheckResult, TaskResult


@pytest.fixture(autouse=True)
def fresh(vault):
    store.close()
    coordinator.CURRENT.set(None)
    yield vault
    store.close()


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f'HTTP {status}', response=response)


# ---------------------------------------------------------------- item 1

def test_a_structured_provider_http_error_is_classified_as_transient():
    """review item 1: a bare RuntimeError made every 502 look permanent."""
    assert coordinator.classify(coordinator.ProviderHTTPError('x', http_status=502)) == 'transient'
    assert coordinator.classify(coordinator.ProviderHTTPError('x', http_status=401)) == 'permanent'
    # The plain RuntimeError the adapter used to raise is, correctly, permanent:
    # nothing in it says which failure it was. That is why the adapter changed.
    assert coordinator.classify(RuntimeError('AI provider returned HTTP 502.')) == 'permanent'
    # It still subclasses RuntimeError, so the engine's user-facing error
    # handling is unchanged.
    assert isinstance(coordinator.ProviderHTTPError('x', http_status=502), RuntimeError)


def test_one_logical_round_keeps_one_decision_id_across_its_attempts():
    """review item 1: a fresh decision id per attempt inflated the count."""
    task = coordinator.start('randall_turn')
    attempts = []

    def provider(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise coordinator.ProviderHTTPError('502', http_status=502)
        yield {'type': 'completion', 'finish_reason': 'stop', 'cost_usd': 0.002,
               'message': {'role': 'assistant', 'content': 'done'}}

    with coordinator.attach(task):
        list(coordinator.traced_provider(provider, role='main')([], [], 'k', _Never()))
    spans = store.model_spans(task.task_id)
    assert [s.attempt for s in spans] == [1, 2, 3]
    assert len({s.decision_id for s in spans}) == 1
    book = store.accounting(task.task_id)
    assert book['attempts'] == 3 and book['logical_decisions'] == 1


def test_cancellation_is_checked_before_every_dispatch_not_only_the_first():
    """review item 1: a retry loop kept dispatching after Stop."""
    task = coordinator.start('randall_turn')
    attempts = []

    def call(span):
        attempts.append(span.attempt)
        task.request_cancel()
        raise coordinator.ProviderHTTPError('502', http_status=502)

    with coordinator.attach(task):
        with pytest.raises(coordinator.TaskCancelled):
            coordinator.run_model_request('main', call, sleep=lambda _s: None)
    assert attempts == [1]


class _Never:
    def is_set(self):
        return False


# ---------------------------------------------------------------- item 3

def test_work_started_under_an_older_revision_stops_at_the_next_boundary():
    """review item 3: checkpoint only looked at cancellation."""
    task = coordinator.start('menu_background_replace')
    started_at = task.revision
    with coordinator.attach(task):
        task.checkpoint(started_at)                       # fine so far
        task.revise('user_revision', 'the other build')
        with pytest.raises(coordinator.RevisionSuperseded) as raised:
            task.checkpoint(started_at)
    assert raised.value.expected == 1 and raised.value.current == 2


def test_a_stage_records_the_revision_it_ran_under_not_the_current_one():
    """review item 3: completion recorded whatever revision happened to be live."""
    task = coordinator.start('menu_background_replace')
    with coordinator.attach(task):
        def body(_span):
            task.revise('user_revision', 'changed mid-stage')
            return {'ok': True}
        stage_journal.run_stage('prepare', body, parameters={'menu': 'css'},
                                expected_revision=1)
    rows = store.stages(task.task_id)
    assert [r['revision'] for r in rows] == [1]
    assert store.stage_spans(task.task_id)[0].task_revision == 1


def test_an_obsolete_stage_refuses_to_start():
    task = coordinator.start('menu_background_replace')
    with coordinator.attach(task):
        task.revise('user_revision', 'changed')
        with pytest.raises(coordinator.RevisionSuperseded):
            stage_journal.run_stage('prepare', lambda _s: 'never',
                                    parameters={'menu': 'css'}, expected_revision=1)


# ---------------------------------------------------------------- item 5

def test_finishing_with_a_failed_required_check_cannot_claim_success():
    """review item 5: the validation error was swallowed and success published."""
    task = coordinator.start('model_import')
    task.envelope.checks.append(CheckResult(check_id='extent_v1', implementation_version='1',
                                            status='fail'))
    with pytest.raises(ValueError, match='cannot report success'):
        task.finish('success')
    seen = store.events(task.task_id)
    # Nothing was published, nothing was persisted, and live state is untouched.
    assert [m for m in seen if m['type'] == events.TASK_FINISHED] == []
    assert store.load_task(task.task_id).state == 'running'
    assert task.envelope.state == 'running' and task.envelope.outcome is None
    # The honest outcome still works.
    task.finish('blocked')
    assert store.load_task(task.task_id).outcome == 'blocked'


def test_a_finished_task_refuses_further_changes():
    """review item 5: `ask` could mutate a task that had already finished."""
    task = coordinator.start('model_import')
    task.finish('success')
    with pytest.raises(coordinator.TaskFinished):
        task.ask('approval', allowed_responses=['approve'], operation_digest='sha256:a')
    with pytest.raises(coordinator.TaskFinished):
        task.revise('user_revision', 'more please')
    with pytest.raises(coordinator.TaskFinished):
        task.finish('failed')
    assert task.finish('success').outcome == 'success'     # the same answer is idempotent


def test_a_terminal_task_retires_the_approval_it_was_waiting_on():
    task = coordinator.start('menu_background_replace')
    request = task.ask('approval', allowed_responses=['approve', 'deny'],
                       operation_digest='sha256:a')
    task.finish('cancelled')
    assert store.request_status(request.id) == 'cancelled'
    assert store.pending_requests(task.task_id) == []


# ---------------------------------------------------------------- item 8

def test_the_attempt_clamp_is_enforced_whatever_a_caller_asks_for():
    """review item 8: attempts=5 ran five times against a documented max of 3."""
    task = coordinator.start('randall_turn')
    attempts = []

    def call(span):
        attempts.append(span.attempt)
        raise coordinator.ProviderHTTPError('502', http_status=502)

    with coordinator.attach(task):
        with pytest.raises(coordinator.ProviderHTTPError):
            coordinator.run_model_request('main', call, attempts=5, sleep=lambda _s: None)
    assert attempts == [1, 2, 3] and len(attempts) == coordinator.MAX_ATTEMPTS
    assert store.model_spans(task.task_id)[0].max_attempts == coordinator.MAX_ATTEMPTS


def test_a_malformed_reply_gets_one_bounded_repair_not_the_outage_allowance():
    """review item 8: the labeller retried a bad parse like a provider outage."""
    task = coordinator.start('model_import')
    attempts = []

    def call(span):
        attempts.append(span.attempt)
        raise coordinator.InvalidResponse('did not parse')

    with coordinator.attach(task):
        with pytest.raises(coordinator.InvalidResponse):
            coordinator.run_model_request('vision', call, sleep=lambda _s: None)
    assert attempts == [1, 2]      # one repair, counted apart from transient retries


def test_budget_is_reserved_before_every_dispatch_including_nested_ones():
    """addendum (a): the round loop's guard missed nested and automatic calls."""
    task = coordinator.start('model_import', cost_budget_usd=0.02)
    charged = []

    def call(span):
        span.record_cost(0.009)
        charged.append(span.attempt)
        return 'ok'

    with coordinator.attach(task):
        coordinator.run_model_request('main', call)
        coordinator.run_model_request('vision', call)      # a NESTED helper
        with pytest.raises(coordinator.BudgetExceeded):
            coordinator.run_model_request('image', call)
    assert len(charged) == 2
    # The refused dispatch never produced a span: it was stopped before it left.
    assert len(store.model_spans(task.task_id)) == 2


def test_an_unreported_charge_counts_against_the_limit_as_pending():
    """addendum (b): an absent cost used to make every spending guard free."""
    reserve = contracts.UNKNOWN_CHARGE_RESERVE_USD
    task = coordinator.start('randall_turn', cost_budget_usd=reserve * 3.5)

    def silent(span):
        span.record_usage({'prompt_tokens': 100})          # no cost reported
        return 'ok'

    with coordinator.attach(task):
        for _ in range(3):
            coordinator.run_model_request('main', silent)
        assert task.committed_usd == round(3 * reserve, 8)
        with pytest.raises(coordinator.BudgetExceeded):
            coordinator.run_model_request('main', silent)
    book = store.accounting(task.task_id)
    assert book['unknown_requests'] == 3 and book['reported_usd'] == 0.0
    assert task.costs.total_usd is UNKNOWN            # still unknown, never zero


def test_a_call_budget_is_enforced_across_every_role():
    task = coordinator.start('randall_turn', call_budget=2)
    with coordinator.attach(task):
        coordinator.run_model_request('jev', lambda s: s.record_cost(0.0))
        coordinator.run_model_request('main', lambda s: s.record_cost(0.0))
        with pytest.raises(coordinator.BudgetExceeded):
            coordinator.run_model_request('vision', lambda s: s.record_cost(0.0))


def test_a_continued_objective_starts_from_the_spend_it_already_made():
    """addendum (c): a fresh continue must not hand out a fresh allowance."""
    first = coordinator.start('model_import', chat_id='chat1', cost_budget_usd=0.02)
    with coordinator.attach(first):
        coordinator.run_model_request('main', lambda s: s.record_cost(0.018))
    first.envelope.facts['budget_exhausted'] = True
    first.finish('blocked')

    previous = store.last_task_for_chat('chat1')
    carried = previous['accounting']['committed_usd']
    assert carried == 0.018
    continued = coordinator.start('model_import', chat_id='chat1', cost_budget_usd=0.02,
                                  carried_usd=carried)
    assert continued.committed_usd == 0.018
    with coordinator.attach(continued):
        with pytest.raises(coordinator.BudgetExceeded):
            coordinator.run_model_request('main', lambda s: s.record_cost(0.01))


# --------------------------------------------------------------- item 7

def test_the_attempt_row_exists_before_the_request_returns():
    """review item 7: a crash mid-request left no attempt at all."""
    task = coordinator.start('randall_turn')
    seen = {}

    def call(span):
        # Mid-flight: the row must already be durable and marked running.
        seen['rows'] = store.spans(task.task_id, kind='model')
        span.record_cost(0.004)
        return 'ok'

    with coordinator.attach(task):
        coordinator.run_model_request('main', call)
    assert len(seen['rows']) == 1 and seen['rows'][0]['status'] == 'running'
    assert store.model_spans(task.task_id)[0].status == 'ok'


def test_a_billed_response_that_fails_validation_keeps_its_charge():
    """review item 7: usage recorded after validation lost a known cost."""
    task = coordinator.start('randall_turn')

    def call(span):
        span.record_usage({'prompt_tokens': 900, 'cost': 0.0031})   # billed
        raise coordinator.InvalidResponse('the answer did not validate')

    with coordinator.attach(task):
        with pytest.raises(coordinator.InvalidResponse):
            coordinator.run_model_request('jev', call, repairs=0)
    span = store.model_spans(task.task_id)[0]
    assert span.status == 'error' and span.reported_cost_usd == 0.0031
    assert store.accounting(task.task_id)['reported_usd'] == 0.0031


# --------------------------------------------------------------- item 10

def test_two_threads_on_one_task_do_not_nest_under_each_other():
    """review item 10: the span stack lived on the shared task object."""
    task = coordinator.start('model_import')
    both_open = threading.Barrier(2, timeout=5)
    parents = {}

    def worker(name):
        with coordinator.attach(task):
            with stage_journal.stage(f'stage-{name}') as outer:
                both_open.wait()
                with coordinator.model_request('main', task=task) as inner:
                    parents[name] = (outer.span_id, inner.parent_span_id)

    threads = [threading.Thread(target=worker, args=(n,)) for n in ('a', 'b')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(parents) == 2
    for outer_id, parent_id in parents.values():
        assert parent_id == outer_id            # each child under ITS OWN stage


def test_concurrent_charges_are_not_lost_from_the_shared_ledger():
    task = coordinator.start('model_import', call_budget=200, cost_budget_usd=None)

    def spend():
        with coordinator.attach(task):
            for _ in range(20):
                coordinator.run_model_request('main', lambda s: s.record_cost(0.001))

    threads = [threading.Thread(target=spend) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert task.costs.reported_requests == 80
    assert task.costs.reported_usd == pytest.approx(0.08)


# --------------------------------------------------------------- item 11


def test_an_event_is_persisted_before_it_is_delivered():
    """review item 11: an event must not be handed on before the journal holds it."""
    store.create_task(TaskResult(task_id='t1'))
    bus = events.Bus(persist=store.record_event)
    message = bus.emit(events.STAGE_STARTED, 't1', stage='fit')
    # What the emitter gets back already carries the durable cursor.
    assert message['seq'] is not None
    assert [e['seq'] for e in store.events('t1')] == [message['seq']]


def test_approval_invalidation_is_a_progress_event():
    """review item 11: a stale approval card was never told to retire."""
    assert events.APPROVAL_INVALIDATED in events.PROGRESS_KINDS


# --------------------------------------------------------------- item 12

def test_tool_schema_versions_distinguish_different_schemas_with_equal_names():
    """review item 12: hashing only the names made different contracts collide."""
    one = [{'type': 'function', 'function': {'name': 'search_vault',
                                             'parameters': {'properties': {'query': {'type': 'string'}}}}}]
    two = [{'type': 'function', 'function': {'name': 'search_vault',
                                             'parameters': {'properties': {'query': {'type': 'integer'}}}}}]
    assert content_hash.schema_hash(one) != content_hash.schema_hash(two)
    assert content_hash.schema_hash(one) == content_hash.schema_hash(list(one))


def test_request_hashes_distinguish_different_messages_of_the_same_shape():
    """review item 12: hashing roles and lengths collided on equal-length text."""
    left = [{'role': 'user', 'content': 'make the hair blue'}]
    right = [{'role': 'user', 'content': 'make the hair pink'}]
    assert content_hash._message_content_hash(left) != content_hash._message_content_hash(right)
    # And it is a hash, not the prose: nothing readable is retained.
    assert 'hair' not in content_hash._message_content_hash(left)


def test_the_same_picture_hashes_alike_from_bytes_base64_or_a_data_url():
    raw = bytes([0x89]) + b'PNG payload'
    encoded = base64.b64encode(raw).decode()
    expected = content_hash.image_bytes_hash(raw)
    assert content_hash.image_bytes_hash(encoded) == expected
    assert content_hash.image_bytes_hash('data:image/png;base64,' + encoded) == expected


def test_a_model_span_records_the_dependency_it_was_asked_after():
    task = coordinator.start('randall_turn')
    with coordinator.attach(task):
        with coordinator.model_request('jev', requested_model='jev') as routing:
            routing.record_cost(0.0001)
        with coordinator.model_request('main', requested_model='glm',
                                       dependency_ids=[routing.span_id]) as main:
            main.record_cost(0.002)
    spans = {s.role: s for s in store.model_spans(task.task_id)}
    assert spans['main'].dependency_ids == [spans['jev'].span_id]
