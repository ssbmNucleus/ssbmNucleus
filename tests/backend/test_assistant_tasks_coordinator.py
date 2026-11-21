"""Task lifecycle, span helpers, bounded retries and the side-effect journal."""
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
    """A requests error shaped like the one OpenRouter raises on a 502."""
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f'HTTP {status}', response=response)


def emit(text='', calls=None, usage=None, cost='absent'):
    if text:
        yield {'type': 'delta', 'content': text}
    event = {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
             'message': {'role': 'assistant', 'content': text or None,
                         **({'tool_calls': calls} if calls else {})}}
    if usage is not None:
        event['usage'] = usage
    if cost != 'absent':
        event['cost_usd'] = cost
    yield event


# ------------------------------------------------------------------ lifecycle

def test_a_task_is_persisted_on_start_and_is_the_current_context():
    assert not coordinator.tracking()
    with coordinator.attach(coordinator.start(request='make the hair blue', chat_id='c1',
                                                family='texture')) as task:
        assert coordinator.tracking() and coordinator.current() is task
        assert store.load_task(task.task_id).state == 'running'
        assert store.task_row(task.task_id)['request'] == 'make the hair blue'
    assert not coordinator.tracking()
    # Outside a task the null context records nothing but still answers.
    assert coordinator.current().task_id == 'task_untracked'


def test_finishing_sets_state_and_outcome_together():
    task = coordinator.start('recolor_part', family='texture')
    task.envelope.achieved['prepared'] = True
    task.finish('partial')
    saved = store.load_task(task.task_id)
    assert (saved.state, saved.outcome) == ('completed', 'partial')
    assert store.unfinished_tasks() == []


def test_a_failed_task_without_a_reason_still_persists_as_failed():
    """An unsaveable envelope would leave the row reading `running` forever."""
    task = coordinator.start('model_import')
    task.finish('failed')
    saved = store.load_task(task.task_id)
    assert (saved.state, saved.outcome) == ('failed', 'failed') and saved.error
    assert store.unfinished_tasks() == []


def test_a_revision_invalidates_a_pending_approval():
    task = coordinator.start('menu_background_replace')
    request = task.ask('approval', prompt='Install into the build you play?',
                       allowed_responses=['approve', 'deny'],
                       operation_id='op1', operation_digest='sha256:sealed')
    assert task.envelope.state == 'waiting_approval'
    assert store.request_status(request.id) == 'pending'

    revision = task.revise('user_revision', 'actually use the Halo one')
    assert revision == 2 and task.revision == 2
    assert store.request_status(request.id) == 'invalidated'
    assert task.envelope.next is None and task.envelope.state == 'running'
    assert store.pending_requests(task.task_id) == []
    # A click that arrives after the revision cannot authorize anything.
    with pytest.raises(store.SettlementRefused, match='stale'):
        task.settle(request.id, 'approve')
    kinds = [e['type'] for e in store.events(task.task_id)]
    assert events.APPROVAL_INVALIDATED in kinds and events.TASK_REVISED in kinds


def test_a_request_raised_after_the_revision_still_settles():
    task = coordinator.start('menu_background_replace')
    task.revise('user_revision', 'blue instead')
    request = task.ask('approval', allowed_responses=['approve', 'deny'],
                       operation_digest='sha256:b')
    assert request.task_revision == 2
    assert task.settle(request.id, 'approve') == 'approve'
    assert store.request_status(request.id) == 'approve'
    assert task.envelope.state == 'running'


def test_cancel_lands_at_the_next_safe_boundary_not_mid_stage():
    task = coordinator.start('model_import')
    reached = []
    with coordinator.attach(task):
        with stage_journal.stage('fit', version='2') as span:
            task.request_cancel()
            reached.append('stage body finished')   # the running stage is NOT torn apart
        assert span.status == 'ok'
        with pytest.raises(coordinator.TaskCancelled):
            with stage_journal.stage('export'):
                reached.append('never')
    assert reached == ['stage body finished']
    assert task.cancelled
    assert events.TASK_CANCELLING in [e['type'] for e in store.events(task.task_id)]


def test_a_cancelled_stage_acknowledges_the_cancellation():
    task = coordinator.start('model_import')
    with coordinator.attach(task):
        with pytest.raises(coordinator.TaskCancelled):
            with stage_journal.stage('render'):
                task.request_cancel()
                task.checkpoint()
    span = store.stage_spans(task.task_id)[0]
    assert span.status == 'cancelled' and span.cancellation_acknowledged is True


# ---------------------------------------------------------------- stage spans

def test_a_stage_records_the_section_three_fields():
    task = coordinator.start('recolor_part')
    with coordinator.attach(task):
        with stage_journal.stage('recolor', version='3', parameters={'hue': 210},
                                 inputs=['sha256:source']) as span:
            span.output_artifact_hashes = ['sha256:out']
            span.check_results = [CheckResult(check_id='unrelated_unchanged_v1',
                                              implementation_version='1', status='pass')]
            span.cleanup_result = 'temp removed'
    stored = store.spans(task.task_id, kind='stage')[0]
    assert stored['stage_name'] == 'recolor' and stored['stage_version'] == '3'
    assert stored['parameter_hash'] == contracts.digest({'hue': 210})
    assert stored['input_artifact_hashes'] == ['sha256:source']
    assert stored['output_artifact_hashes'] == ['sha256:out']
    assert stored['worker_identity'] and stored['cpu_time_ms'] is not None
    assert stored['running_at'] and stored['completed_at'] and stored['duration_ms'] >= 0
    assert stored['check_results'][0]['check_id'] == 'unrelated_unchanged_v1'
    assert stored['cleanup_result'] == 'temp removed' and stored['status'] == 'ok'


def test_a_resumed_stage_does_not_execute_its_body_again():
    """review item 4: the cache-hit branch still yielded, so the body ran twice."""
    task = coordinator.start('model_import', task_id='t-resume')
    runs = []

    def fit(span):
        runs.append('ran')
        span.output_artifact_hashes = ['sha256:candidate']
        return {'candidate_id': 'c1'}

    with coordinator.attach(task):
        first = stage_journal.run_stage('fit', fit, parameters={'donor': 'falcon'})
        second = stage_journal.run_stage('fit', fit, parameters={'donor': 'falcon'})
    assert runs == ['ran']                       # the body ran exactly once
    assert first == second == {'candidate_id': 'c1'}
    recorded = store.stage_spans('t-resume')
    assert [s.cache_hit for s in recorded] == [False, True]
    assert recorded[1].output_artifact_hashes == ['sha256:candidate']
    # Different parameters are a different operation and do run.
    with coordinator.attach(task):
        stage_journal.run_stage('fit', fit, parameters={'donor': 'fox'})
    assert runs == ['ran', 'ran']


def test_a_stage_context_manager_always_executes_its_body():
    """The tracing CM is separate from resume: it never skips (review item 4)."""
    task = coordinator.start('model_import')
    runs = []
    for _ in range(2):
        with coordinator.attach(task):
            with stage_journal.stage('render', parameters={'pose': 'idle'}):
                runs.append('ran')
    assert runs == ['ran', 'ran']
    assert [s.cache_hit for s in store.stage_spans(task.task_id)] == [None, None]


def test_a_cached_result_that_no_longer_verifies_is_recomputed():
    """A stale artifact must never be handed back as a fresh one."""
    task = coordinator.start('model_import')
    runs = []

    def build(span):
        runs.append('ran')
        return {'path': 'out.dat'}

    with coordinator.attach(task):
        stage_journal.run_stage('export', build, parameters={'slot': 4})
        stage_journal.run_stage('export', build, parameters={'slot': 4}, verify=lambda _r: False)
    assert runs == ['ran', 'ran']


def test_a_failing_resumable_stage_records_nothing_reusable():
    task = coordinator.start('model_import')

    def boom(_span):
        raise RuntimeError('the writer refused')

    with coordinator.attach(task):
        with pytest.raises(RuntimeError):
            stage_journal.run_stage('export', boom, parameters={'slot': 4})
        runs = []
        stage_journal.run_stage('export', lambda _s: runs.append('ran'), parameters={'slot': 4})
    assert runs == ['ran']                       # the failure was not cached as success


def test_a_failing_stage_records_its_typed_error_and_reraises():
    task = coordinator.start('model_import')
    with coordinator.attach(task):
        with pytest.raises(RuntimeError):
            with stage_journal.stage('export'):
                raise RuntimeError('writer refused the candidate')
    span = store.stage_spans(task.task_id)[0]
    assert span.status == 'error' and span.error_type == 'RuntimeError'
    assert 'writer refused' in span.error_detail


def test_waits_are_measured_separately_by_what_they_waited_on():
    task = coordinator.start('costume_verification_v1')
    with task.waiting('dolphin', 'machine-wide lock'):
        pass
    with task.waiting('approval'):
        pass
    with pytest.raises(ValueError):
        with task.waiting('vibes'):
            pass
    kinds = [(e['type'], e.get('wait_kind')) for e in store.events(task.task_id)]
    assert (events.WAIT_ENDED, 'dolphin') in kinds


# ------------------------------------------------------------- model requests

def test_a_model_request_records_resolution_tokens_and_charge():
    task = coordinator.start('randall_turn')
    with coordinator.attach(task):
        with coordinator.model_request('jev', requested_model='typesafe/jev-1.13',
                                       task_family='routing', timeout_s=5) as span:
            span.resolved_provider = 'typesafe'
            span.provider_generation_id = 'gen-1'
            span.record_usage({'prompt_tokens': 300, 'completion_tokens': 12, 'cost': 0.0004})
            span.response_validation = 'valid'
    stored = store.model_spans(task.task_id)[0]
    assert stored.role == 'jev' and stored.requested_model == 'typesafe/jev-1.13'
    assert stored.provider_generation_id == 'gen-1' and stored.resolved_provider == 'typesafe'
    assert stored.input_tokens == 300 and stored.reported_cost_usd == 0.0004
    assert stored.cost_status == 'reported' and stored.status == 'ok'
    assert stored.dispatch_ms is not None and stored.completion_ms is not None


def test_a_request_whose_charge_the_provider_omitted_stays_unknown():
    task = coordinator.start('randall_turn')
    with coordinator.attach(task):
        with coordinator.model_request('main', requested_model='glm') as span:
            span.record_usage({'prompt_tokens': 10})
    book = store.accounting(task.task_id)
    assert book['unknown_requests'] == 1 and book['total_usd'] == 'unknown'
    assert store.model_spans(task.task_id)[0].reported_cost_usd is UNKNOWN


def test_a_raising_request_is_classified_and_still_recorded():
    task = coordinator.start('randall_turn')
    with coordinator.attach(task):
        with pytest.raises(requests.HTTPError):
            with coordinator.model_request('main', requested_model='glm') as span:
                span.http_status = 502
                raise http_error(502)
    stored = store.model_spans(task.task_id)[0]
    assert stored.status == 'error' and stored.retry_classification == 'transient'
    assert '502' in stored.provider_error


def test_classification_only_retries_what_is_worth_retrying():
    assert coordinator.classify(http_error(502)) == 'transient'
    assert coordinator.classify(http_error(429)) == 'transient'
    assert coordinator.classify(http_error(401)) == 'permanent'
    assert coordinator.classify(http_error(404)) == 'permanent'
    assert coordinator.classify(requests.ConnectionError()) == 'transient'
    assert coordinator.classify(ValueError('bad json')) == 'invalid_response'
    assert coordinator.classify(coordinator.TaskCancelled()) == 'cancelled'
    assert coordinator.classify(RuntimeError('nope')) == 'permanent'


def test_backoff_is_bounded_and_jittered():
    values = {coordinator.backoff(3) for _ in range(40)}
    assert len(values) > 1                                   # jitter, not a fixed delay
    assert all(0 <= v <= coordinator.MAX_BACKOFF_S for v in values)
    assert coordinator.backoff(99) <= coordinator.MAX_BACKOFF_S


def test_a_simulated_502_retries_twice_at_most_and_keeps_every_attempt():
    task = coordinator.start('randall_turn')
    attempts = []
    slept = []

    def call(span):
        attempts.append(span.attempt)
        span.http_status = 502
        span.record_cost(0.001)              # the failed attempt still generated tokens
        raise http_error(502)

    with coordinator.attach(task):
        with pytest.raises(requests.HTTPError):
            coordinator.run_model_request('main', call, requested_model='glm', sleep=slept.append)
    assert attempts == [1, 2, 3] == list(range(1, coordinator.MAX_ATTEMPTS + 1))
    assert len(slept) == 2 and all(0 <= s <= coordinator.MAX_BACKOFF_S for s in slept)
    spans = store.model_spans(task.task_id)
    assert len(spans) == 3 and {s.decision_id for s in spans} == {spans[0].decision_id}
    book = store.accounting(task.task_id)
    assert book['attempts'] == 3 and book['logical_decisions'] == 1
    assert book['reported_usd'] == 0.003          # three attempts, three charges, none lost


def test_one_502_then_success_is_two_attempts_and_one_charge():
    task = coordinator.start('randall_turn')
    calls = []

    def call(span):
        calls.append(span.attempt)
        if span.attempt == 1:
            span.http_status = 502
            raise http_error(502)             # failed before the provider billed anything
        span.record_cost(0.004)
        return 'answer'

    with coordinator.attach(task):
        assert coordinator.run_model_request('main', call, requested_model='glm',
                                             sleep=lambda _s: None) == 'answer'
    spans = store.model_spans(task.task_id)
    assert calls == [1, 2] and [s.attempt for s in spans] == [1, 2]
    assert [s.status for s in spans] == ['error', 'ok']
    book = store.accounting(task.task_id)
    assert book['attempts'] == 2 and book['logical_decisions'] == 1
    assert book['billed_attempts'] == 1 and book['reported_usd'] == 0.004
    assert book['coverage'] == 0.5 and book['total_usd'] == 'unknown'
    assert spans[1].retry_delay_ms is not None


def test_a_permanent_failure_is_not_retried():
    task = coordinator.start('randall_turn')
    attempts = []

    def call(span):
        attempts.append(span.attempt)
        raise http_error(401)

    with coordinator.attach(task):
        with pytest.raises(requests.HTTPError):
            coordinator.run_model_request('main', call, sleep=lambda _s: None)
    assert attempts == [1] and len(store.model_spans(task.task_id)) == 1


def test_cancellation_stops_a_retry_loop_immediately():
    task = coordinator.start('randall_turn')
    attempts = []

    def call(span):
        attempts.append(span.attempt)
        task.request_cancel()
        raise http_error(502)

    with coordinator.attach(task):
        with pytest.raises(coordinator.TaskCancelled):
            coordinator.run_model_request('main', call, sleep=lambda _s: None)
    assert attempts == [1]


# ------------------------------------------------------- the provider wrapper

def test_the_traced_provider_records_the_round_it_serves():
    task = coordinator.start('randall_turn')
    calls = [{'id': 'c1', 'type': 'function',
              'function': {'name': 'search_vault', 'arguments': '{}'}}]

    def provider(messages, schemas, key, cancelled, *args):
        yield from emit('working on it', calls=calls,
                        usage={'prompt_tokens': 800, 'completion_tokens': 30}, cost=0.002)

    traced = coordinator.traced_provider(provider, role='main', requested_model='glm')
    with coordinator.attach(task):
        produced = list(traced([{'role': 'user', 'content': 'hi'}],
                               [{'function': {'name': 'search_vault'}}], 'key', _Never()))
    assert [e['type'] for e in produced] == ['delta', 'completion']
    span = store.model_spans(task.task_id)[0]
    assert span.role == 'main' and span.finish_reason == 'tool_calls'
    assert span.input_tokens == 800 and span.reported_cost_usd == 0.002
    assert span.first_token_ms is not None and span.response_validation == 'valid'
    assert span.tool_schema_version and span.input_artifact_hashes


def test_a_provider_that_returns_at_a_stop_is_a_cancelled_attempt():
    """F-D-7: no completion came, so the attempt is not `ok` and has no completion time."""
    task = coordinator.start('randall_turn')

    class _Stopped:
        def is_set(self):
            return stopped

    stopped = False

    def provider(messages, schemas, key, cancelled, *args):
        nonlocal stopped
        yield {'type': 'delta', 'content': 'work'}
        stopped = True              # the user pressed Stop; the provider returns on its next line

    with coordinator.attach(task):
        produced = list(coordinator.traced_provider(provider, role='main')([], [], 'k', _Stopped()))
    assert [e['type'] for e in produced] == ['delta']
    span = store.model_spans(task.task_id)[0]
    assert span.status == 'cancelled' and span.completion_ms is None
    assert span.retry_classification == 'cancelled'


def test_the_traced_provider_hashes_the_image_bytes_it_actually_attached():
    """review item 12: a data-URL hash could not be compared with a file hash."""
    import base64
    raw = bytes([0x89]) + b'PNG' + bytes([13, 10, 26, 10]) + b' fake pixels'
    encoded = base64.b64encode(raw).decode()
    task = coordinator.start('randall_turn')
    messages = [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + encoded}},
        {'type': 'text', 'text': 'which piece is the head?'}]}]

    def provider(*args, **kwargs):
        yield from emit('the head is piece 3')

    with coordinator.attach(task):
        list(coordinator.traced_provider(provider, role='vision')(messages, [], 'k', _Never()))
    span = store.model_spans(task.task_id)[0]
    # The hash is of the decoded BYTES, so the same picture hashes identically
    # whether it arrived as a data URL, as base64, or as a file on disk.
    assert span.attached_image_hashes == [content_hash.image_bytes_hash(raw)]
    assert content_hash.image_bytes_hash(encoded) == content_hash.image_bytes_hash(raw)
    assert content_hash.image_bytes_hash('data:image/png;base64,' + encoded) ==         content_hash.image_bytes_hash(raw)


def test_the_traced_provider_retries_a_502_before_any_output_is_streamed():
    task = coordinator.start('randall_turn')
    attempts = []

    def provider(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise http_error(502)
        yield from emit('recovered', cost=0.003)

    with coordinator.attach(task):
        produced = list(coordinator.traced_provider(
            provider, role='main', requested_model='glm')([], [], 'k', _Never()))
    assert len(attempts) == 2 and produced[0]['content'] == 'recovered'
    spans = store.model_spans(task.task_id)
    assert [s.attempt for s in spans] == [1, 2] and [s.status for s in spans] == ['error', 'ok']
    # review item 1: both attempts are ONE logical round. Minting a fresh
    # decision id per attempt reported two decisions for one question and made
    # "logical decisions vs actual requests" meaningless.
    assert len({s.decision_id for s in spans}) == 1
    assert store.accounting(task.task_id)['logical_decisions'] == 1
    assert store.accounting(task.task_id)['attempts'] == 2


def test_a_round_that_already_streamed_prose_is_never_re_sent():
    """Re-sending would duplicate text the user already has and could re-issue a tool call."""
    task = coordinator.start('randall_turn')
    attempts = []

    def provider(*args, **kwargs):
        attempts.append(1)
        yield {'type': 'delta', 'content': 'half an answer'}
        raise http_error(502)

    with coordinator.attach(task):
        with pytest.raises(requests.HTTPError):
            list(coordinator.traced_provider(provider, role='main')([], [], 'k', _Never()))
    assert len(attempts) == 1
    assert store.model_spans(task.task_id)[0].status == 'error'


def test_tracing_a_provider_outside_a_task_records_nothing_and_still_works():
    def provider(*args, **kwargs):
        yield from emit('fine', cost=0.001)

    produced = list(coordinator.traced_provider(provider, role='main')([], [], 'k', _Never()))
    assert produced[-1]['type'] == 'completion'
    assert store.spans('task_untracked') == []


class _Never:
    def is_set(self):
        return False


# -------------------------------------------------------- side-effect journal

def test_the_journal_stops_a_repeated_model_answer_from_downloading_twice():
    downloads = []
    with coordinator.attach(coordinator.start(request='get the halo menu')) as task:
        for _ in range(2):
            with stage_journal.journal_tool('download_website_mod', 'fp-halo') as claim:
                if not claim.claimed:
                    assert claim.record['status'] == 'completed'
                    assert claim.result == {'file': 'halo.zip'}
                    continue
                downloads.append('halo.zip')
                claim.complete({'file': 'halo.zip'})
        assert downloads == ['halo.zip']
        entries = store.connect().execute(
            'SELECT status FROM tool_journal WHERE task_id=?', (task.task_id,)).fetchall()
        assert [row['status'] for row in entries] == ['completed']


def test_a_failed_effect_is_journalled_as_failed_not_silently_retryable():
    with coordinator.attach(coordinator.start(request='commit the menu')) as task:
        operation = contracts.digest([task.task_id, task.revision, 'commit_change', 'fp1'])
        with pytest.raises(RuntimeError):
            with stage_journal.journal_tool('commit_change', 'fp1'):
                raise RuntimeError('the writer died mid-commit')
        record = store.tool_record(operation)
        assert record['status'] == 'failed' and 'writer died' in record['result']['error']
        # It is not re-claimable: reconciliation decides, not a blind replay.
        claimed, _ = store.begin_tool(operation, 'commit_change', 'fp1', task_id=task.task_id)
        assert not claimed


def test_a_different_revision_is_a_different_operation():
    with coordinator.attach(coordinator.start(request='install it')) as task:
        with stage_journal.journal_tool('commit_change', 'fp1') as claim:
            assert claim.claimed
            claim.complete({'build_revision': 7})
        task.revise('user_revision', 'the other build')
        with stage_journal.journal_tool('commit_change', 'fp1') as claim:
            assert claim.claimed    # a new revision means a new, genuine operation
            claim.complete({'build_revision': 8})


# -------------------------------------------------------------------- resume

def test_restart_resumes_recorded_stages_and_flags_unresolved_effects(monkeypatch):
    from core import jobs
    task = coordinator.start('menu_background_replace', task_id='t-crash')
    with coordinator.attach(task):
        def prepare(span):
            span.output_artifact_hashes = ['sha256:prepared']
            return {'menu': 'css'}
        stage_journal.run_stage('prepare', prepare, parameters={'menu': 'css'})
        store.begin_tool('op-commit', 'commit_change', 'fp1', task_id='t-crash')
    # A task this live process runs is not touched by a restart elsewhere.
    assert coordinator.resume_pending() == []
    assert store.task_row('t-crash')['state'] == 'running'
    # ... the process dies here, mid-commit ...
    monkeypatch.setattr(jobs, 'owner_alive', lambda owner: False)
    resumed = coordinator.resume_pending()
    assert [r['task_id'] for r in resumed] == ['t-crash']
    assert [e['operation_id'] for e in resumed[0]['unresolved']] == ['op-commit']
    assert store.tool_record('op-commit')['status'] == 'unresolved'
    # The completed stage is still resumable; the commit is NOT replayed.
    assert store.completed_stage(
        't-crash', 'prepare', stage_journal.stage_operation_id('prepare', '1', {'menu': 'css'}, ()))
    assert events.TASK_RESUMED in [e['type'] for e in store.events('t-crash')]
    # F-D-6: no process will finish it, so it is closed as interrupted.
    closed = store.load_task('t-crash')
    assert (closed.state, closed.outcome) == ('failed', 'failed')
    assert closed.error['kind'] == 'interrupted' and closed.facts['interrupted'] is True
    # review item 9: a SECOND restart still finds the unresolved operation.
    again = coordinator.resume_pending()
    assert [e['operation_id'] for e in again[0]['unresolved']] == ['op-commit']


def test_a_continuation_of_an_interrupted_objective_carries_its_spend(monkeypatch):
    from core import jobs
    from randall.assistant import turn_facts
    task = coordinator.start('', chat_id='chat-crash', task_id='t-spent')
    span = contracts.ModelSpan(task_id='t-spent', role='main', status='ok')
    span.record_cost(0.25, reserved=0.25)
    store.record_span(span)
    assert turn_facts._carried_ledger('chat-crash') == (0.0, 0), 'a live objective carries nothing yet'
    monkeypatch.setattr(jobs, 'owner_alive', lambda owner: False)
    coordinator.resume_pending()
    carried_usd, _calls = turn_facts._carried_ledger('chat-crash')
    assert carried_usd == pytest.approx(0.25)


# ------------------------------------------------------------- results/wishes

def test_a_recorded_check_lands_on_the_envelope_and_blocks_a_success_claim():
    task = coordinator.start('model_import')
    task.envelope.checks.append(CheckResult(check_id='posture_v1', implementation_version='1',
                                            status='unknown'))
    assert task.envelope.blocking_checks[0].check_id == 'posture_v1'
    with pytest.raises(ValueError, match='cannot report success'):
        task.envelope.state, task.envelope.outcome = 'completed', 'success'
        task.envelope.validate()


def test_a_coordinator_event_carries_progress_without_a_model_call():
    task = coordinator.start('recolor_part')
    with coordinator.attach(task):
        with stage_journal.stage('recolor'):
            pass
    seen = store.events(task.task_id)
    kinds = [m['type'] for m in seen]
    assert events.STAGE_STARTED in kinds and events.STAGE_FINISHED in kinds
    assert all(m['task_id'] == task.task_id for m in seen)
    assert events.PROGRESS_KINDS >= {events.STAGE_STARTED, events.STAGE_FINISHED}


def test_an_unknown_event_kind_is_refused():
    with pytest.raises(ValueError):
        events.event('not_a_kind', 't1')
