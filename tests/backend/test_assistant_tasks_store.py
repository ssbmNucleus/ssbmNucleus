"""The durable journal: round trip, append-only attempts, and the JSONL export."""
import json

import pytest

from core import config
from randall.assistant.tasks import store
from randall.assistant.tasks.contracts import (UNKNOWN, CheckResult, ModelSpan, NextRequest,
                                       StageSpan, TaskResult, Wish)


@pytest.fixture(autouse=True)
def fresh(vault):
    """Every test gets its own storage root; drop the cached connection with it."""
    store.close()
    yield vault
    store.close()


def span(**extra):
    return ModelSpan(task_id=extra.pop('task_id', 't1'), role='main', **extra)


def test_the_journal_lives_under_the_apps_storage_root_not_a_temp_dir(vault):
    assert store.root() == vault.storage / 'assistant' / 'tasks'
    assert store.artifact_dir('task_x') == store.root() / 'artifacts' / 'task_x'
    assert store.artifact_dir('task_x').is_dir()
    store.connect()
    assert (store.root() / 'tasks.db').is_file()


def test_task_round_trip_and_idempotent_creation():
    envelope = TaskResult(task_id='t1', workflow='recolor_part')
    store.create_task(envelope, chat_id='chat1', family='texture', request='make the hair blue')
    store.create_task(envelope, chat_id='chat1', family='texture')      # replayed start
    loaded = store.load_task('t1')
    assert loaded.task_id == 't1' and loaded.workflow == 'recolor_part' and loaded.state == 'running'
    assert store.task_row('t1')['request'] == 'make the hair blue'
    envelope.state, envelope.outcome = 'completed', 'partial'
    envelope.achieved['prepared'] = True
    store.save_task(envelope)
    again = store.load_task('t1')
    assert (again.state, again.outcome) == ('completed', 'partial') and again.achieved['prepared']
    assert store.load_task('missing') is None


def test_a_saved_envelope_is_validated_before_it_lands():
    with pytest.raises(ValueError):
        store.create_task(TaskResult(task_id='bad', state='completed'))
    assert store.load_task('bad') is None


def test_spans_are_append_only_per_attempt():
    store.create_task(TaskResult(task_id='t1'))
    one = span(decision_id='d1', attempt=1).record_cost(0.004)
    one.finish('error')
    two = span(decision_id='d1', attempt=2).record_cost(0.006)
    two.finish('ok')
    two.span_id = one.span_id            # same logical request, retried
    store.record_span(one)
    store.record_span(two)
    rows = store.spans('t1', kind='model')
    assert len(rows) == 2 and [r['attempt'] for r in rows] == [1, 2]
    assert {r['status'] for r in rows} == {'error', 'ok'}


def test_an_unknown_charge_survives_the_round_trip_as_unknown():
    store.create_task(TaskResult(task_id='t1'))
    unknown = span(decision_id='d1')
    unknown.record_usage({'prompt_tokens': 10})          # provider reported no cost
    unknown.finish('ok')
    store.record_span(unknown)
    restored = store.model_spans('t1')[0]
    assert restored.reported_cost_usd is UNKNOWN and restored.cost_status == 'unknown'
    book = store.accounting('t1')
    assert book['unknown_requests'] == 1 and book['reported_usd'] == 0.0
    assert book['total_usd'] == 'unknown' and book['coverage'] == 0.0


def test_accounting_separates_logical_decisions_from_attempts():
    store.create_task(TaskResult(task_id='t1'))
    for attempt, cost in ((1, 0.004), (2, 0.006)):
        entry = span(decision_id='d1', attempt=attempt).record_cost(cost)
        entry.finish('ok')
        store.record_span(entry)
    other = span(decision_id='d2').record_cost(0.01)
    other.finish('ok')
    store.record_span(other)
    book = store.accounting('t1')
    assert book['attempts'] == 3 and book['logical_decisions'] == 2
    assert book['reported_usd'] == 0.02 and book['unknown_requests'] == 0
    assert book['coverage'] == 1.0 and book['total_usd'] == 0.02


def test_a_completed_stage_is_resumable_only_for_the_same_inputs():
    store.create_task(TaskResult(task_id='t1'))
    store.record_stage('t1', 'prepare', 'op-a', output={'output_artifact_hashes': ['sha256:1']})
    assert store.completed_stage('t1', 'prepare', 'op-a') == {'output_artifact_hashes': ['sha256:1']}
    assert store.completed_stage('t1', 'prepare', 'op-b') is None
    store.record_stage('t1', 'export', 'op-c', status='running')
    assert store.completed_stage('t1', 'export', 'op-c') is None
    assert {s['stage_name'] for s in store.stages('t1')} == {'prepare', 'export'}


def test_the_tool_journal_refuses_a_second_execution_of_the_same_effect():
    store.create_task(TaskResult(task_id='t1'))
    claimed, previous = store.begin_tool('op1', 'download_website_mod', 'fp1', task_id='t1')
    assert claimed and previous is None
    store.finish_tool('op1', 'completed', {'file': 'halo.zip'})
    again, record = store.begin_tool('op1', 'download_website_mod', 'fp1', task_id='t1')
    assert not again and record['status'] == 'completed'
    assert store.tool_record('op1')['result'] == {'file': 'halo.zip'}


def test_an_effect_that_started_and_never_reported_is_listed_for_reconciliation():
    store.create_task(TaskResult(task_id='t1'))
    store.begin_tool('op2', 'commit_change', 'fp2', task_id='t1')
    pending = store.open_tools('t1')
    assert [p['operation_id'] for p in pending] == ['op2'] and pending[0]['status'] == 'started'
    store.finish_tool('op2', 'completed', {'build_revision': 7})
    assert store.open_tools('t1') == []


def test_a_revision_invalidates_pending_requests_in_one_commit():
    """Revision, envelope and invalidations must land together (review item 3)."""
    envelope = TaskResult(task_id='t1')
    store.create_task(envelope)
    old = NextRequest(kind='approval', task_revision=1, allowed_responses=['approve', 'deny'],
                      operation_digest='sha256:a')
    store.record_request('t1', old)
    revision, stale = store.revise_task('t1', 'user_revision', 'blue instead', envelope)
    assert revision == 2 and stale == [old.id]
    assert store.request_status(old.id) == 'invalidated'
    # The envelope in the row already carries the new revision: no window in
    # which the revision column is ahead of what it describes.
    assert store.load_task('t1').revision == 2 and store.current_revision('t1') == 2
    fresh_request = NextRequest(kind='approval', task_revision=2, allowed_responses=['approve'],
                                operation_digest='sha256:b')
    store.record_request('t1', fresh_request)
    assert [r['id'] for r in store.pending_requests('t1')] == [fresh_request.id]


def test_a_finished_task_cannot_be_revised():
    envelope = TaskResult(task_id='t1', state='completed', outcome='success')
    store.create_task(envelope)
    store.save_task(envelope)
    with pytest.raises(ValueError, match='finished'):
        store.revise_task('t1', 'user_revision', 'again', envelope)


def test_a_stale_writer_cannot_overwrite_a_newer_revision():
    """review item 3: an older context must not win the race."""
    envelope = TaskResult(task_id='t1')
    store.create_task(envelope)
    stale_writer = store.load_task('t1')                # a context holding revision 1
    store.revise_task('t1', 'user_revision', 'blue instead', envelope)
    stale_writer.facts['from'] = 'revision 1'
    with pytest.raises(store.StaleRevision):
        store.save_task(stale_writer)
    with pytest.raises(store.StaleRevision):
        store.save_task(envelope, expect_revision=1)
    assert store.load_task('t1').facts == {}


def test_settlement_is_scoped_to_its_task_and_its_offered_responses():
    """review item 2: settle accepted foreign, unknown and settled requests."""
    store.create_task(TaskResult(task_id='t1'))
    store.create_task(TaskResult(task_id='t2'))
    request = NextRequest(kind='approval', task_revision=1, allowed_responses=['approve', 'deny'],
                          operation_digest='sha256:a')
    store.record_request('t1', request)
    with pytest.raises(store.SettlementRefused, match='different task'):
        store.settle_request(request.id, 'approve', task_id='t2')
    with pytest.raises(store.SettlementRefused, match='not known'):
        store.settle_request('no-such-request', 'approve', task_id='t1')
    with pytest.raises(store.SettlementRefused, match='not one of the responses'):
        store.settle_request(request.id, 'ship it anyway', task_id='t1')
    assert store.settle_request(request.id, 'approve', task_id='t1') == ('settled', 'approve')
    # The same answer again is the same answer; a different one is a conflict.
    assert store.settle_request(request.id, 'approve', task_id='t1') == ('idempotent', 'approve')
    with pytest.raises(store.SettlementRefused, match='already approve'):
        store.settle_request(request.id, 'deny', task_id='t1')


def test_settlement_refuses_a_request_raised_before_a_revision():
    """review item 2: the read and the write must be one transaction."""
    envelope = TaskResult(task_id='t1')
    store.create_task(envelope)
    request = NextRequest(kind='approval', task_revision=1, allowed_responses=['approve', 'deny'],
                          operation_digest='sha256:a')
    store.record_request('t1', request)
    store.revise_task('t1', 'user_revision', 'the other build', envelope)
    with pytest.raises(store.SettlementRefused, match='stale'):
        store.settle_request(request.id, 'approve', task_id='t1')
    assert store.request_status(request.id) == 'invalidated'


def test_an_unresolved_effect_stays_discoverable_across_restarts():
    """review item 9: a second recovery found nothing still to reconcile."""
    store.create_task(TaskResult(task_id='t1'))
    store.begin_tool('op1', 'commit_change', 'fp1', task_id='t1')
    store.finish_tool('op1', 'unresolved', {'note': 'crashed mid-commit'})
    assert [e['operation_id'] for e in store.open_tools('t1')] == ['op1']
    assert [e['operation_id'] for e in store.open_tools('t1')] == ['op1']   # and again
    store.finish_tool('op1', 'reconciled', {'checked': 'destination unchanged'})
    assert store.open_tools('t1') == []


def test_a_journal_record_is_the_same_decoded_type_from_either_reader():
    """review item 9: begin_tool returned JSON strings, tool_record objects."""
    store.create_task(TaskResult(task_id='t1'))
    store.begin_tool('op1', 'download_website_mod', 'fp1', task_id='t1')
    store.finish_tool('op1', 'completed', {'file': 'halo.zip'})
    _, reused = store.begin_tool('op1', 'download_website_mod', 'fp1', task_id='t1')
    assert reused['result'] == store.tool_record('op1')['result'] == {'file': 'halo.zip'}


def test_an_operation_id_reused_for_different_work_is_a_conflict():
    store.create_task(TaskResult(task_id='t1'))
    store.begin_tool('op1', 'download_website_mod', 'fp1', task_id='t1')
    with pytest.raises(store.JournalConflict):
        store.begin_tool('op1', 'commit_change', 'fp1', task_id='t1')
    with pytest.raises(store.JournalConflict):
        store.begin_tool('op1', 'download_website_mod', 'other', task_id='t1')


def test_completing_an_operation_requires_a_receipt():
    store.create_task(TaskResult(task_id='t1'))
    store.begin_tool('op1', 'commit_change', 'fp1', task_id='t1')
    with pytest.raises(ValueError, match='must record its result'):
        store.finish_tool('op1', 'completed')
    store.finish_tool('op1', 'completed', {'build_revision': 7})
    assert store.tool_record('op1')['result'] == {'build_revision': 7}


def test_a_dispatched_attempt_survives_a_crash_as_unresolved():
    """review item 7: a crash mid-request lost the attempt from accounting."""
    store.create_task(TaskResult(task_id='t1'))
    flight = span(decision_id='d1')                 # written before dispatch, never finished
    store.record_span(flight)
    assert store.model_spans('t1')[0].status == 'running'
    assert store.reconcile_open_spans('t1') == [(flight.span_id, 1)]
    assert store.model_spans('t1')[0].status == 'unresolved'
    book = store.accounting('t1')
    assert book['unresolved_attempts'] == 1 and book['total_usd'] == 'unknown'


def test_events_carry_the_durable_sequence_and_replay_from_it():
    """review item 11: the bus counter reset on restart; the rowid does not."""
    store.create_task(TaskResult(task_id='t1'))
    first = store.record_event({'type': 'stage_started', 'task_id': 't1', 'revision': 1,
                                'at': 1.0, 'stage': 'fit'})
    second = store.record_event({'type': 'stage_finished', 'task_id': 't1', 'revision': 1,
                                 'at': 2.0, 'stage': 'fit'})
    assert first['seq'] < second['seq']
    assert [e['type'] for e in store.events('t1', after=first['seq'])] == ['stage_finished']
    assert [e['seq'] for e in store.events('t1')] == [first['seq'], second['seq']]


def test_the_previous_task_for_a_chat_carries_its_spend_forward():
    """addendum (c): a fresh continue must not reset a spending limit."""
    envelope = TaskResult(task_id='t1', state='completed', outcome='blocked')
    envelope.facts['budget_exhausted'] = True
    store.create_task(envelope, chat_id='chat1')
    store.save_task(envelope)
    charged = span(decision_id='d1').record_cost(0.09)
    charged.finish('ok')
    store.record_span(charged)
    previous = store.last_task_for_chat('chat1')
    assert previous['facts']['budget_exhausted'] is True
    assert previous['accounting']['committed_usd'] == 0.09
    assert store.last_task_for_chat('other') is None


def test_wishes_dedupe_by_capability_while_keeping_every_occurrence():
    store.create_task(TaskResult(task_id='t1'))
    first = Wish(capability='menu_output_preview', blocked_operation='render_menu_artifact',
                 task_id='t1', app_version='0.8.9')
    second = Wish(capability='menu_output_preview', blocked_operation='render_menu_artifact',
                  task_id='t1', app_version='0.8.9')
    store.record_wish(first)
    store.record_wish(second)
    recorded = store.wishes('t1')
    assert len(recorded) == 2                               # both occurrences are counted
    assert {w.record_status for w in recorded} == {'queued', 'duplicate'}


def test_unfinished_tasks_are_the_ones_a_restart_must_reconcile():
    store.create_task(TaskResult(task_id='live'))
    done = TaskResult(task_id='done', state='completed', outcome='success')
    store.create_task(done)
    store.save_task(done)
    assert [t['task_id'] for t in store.unfinished_tasks()] == ['live']


def test_jsonl_export_carries_the_whole_trace_one_record_per_line(tmp_path):
    envelope = TaskResult(task_id='t1', workflow='model_import')
    store.create_task(envelope, chat_id='chat1', family='import', request='import the dragon')
    entry = span(decision_id='d1').record_cost(0.004)
    entry.finish('ok')
    store.record_span(entry)
    stage = StageSpan(task_id='t1', stage_name='fit', stage_version='2')
    stage.finish('ok')
    store.record_span(stage)
    store.record_stage('t1', 'fit', 'op-a', output={'output_artifact_hashes': ['sha256:1']})
    store.begin_tool('op1', 'model_fit', 'fp1', task_id='t1')
    store.finish_tool('op1', 'completed', {'candidate': 'c1'})
    store.record_request('t1', NextRequest(kind='decision', allowed_responses=['a', 'b']))
    store.record_event({'type': 'stage_started', 'task_id': 't1', 'revision': 1,
                        'at': 1.0, 'stage': 'fit'})
    store.record_wish(Wish(capability='independent_part_recolor', task_id='t1',
                           blocked_operation='mask_shared_texels'))
    envelope.state, envelope.outcome = 'completed', 'blocked'
    envelope.checks = [CheckResult(check_id='extent_v1', implementation_version='1', status='fail')]
    store.save_task(envelope)

    path = store.export_trace('t1', tmp_path / 'trace.jsonl')
    lines = store.read_trace(path)
    kinds = [line['record'] for line in lines]
    assert kinds[0] == 'task'
    for expected in ('revision', 'span', 'stage', 'tool', 'approval', 'event', 'wish'):
        assert expected in kinds, expected
    head = lines[0]
    assert head['task']['outcome'] == 'blocked' and head['family'] == 'import'
    assert head['accounting']['reported_usd'] == 0.004 and head['accounting']['attempts'] == 1
    assert head['schema_version'] == store.SCHEMA_VERSION
    # Every line is independently parseable JSON with a self-describing record.
    raw = path.read_text(encoding='utf-8').strip().split('\n')
    assert len(raw) == len(lines) and all(json.loads(line)['record'] for line in raw)


def test_export_names_the_default_trace_location_when_none_is_given():
    store.create_task(TaskResult(task_id='t1'))
    path = store.export_trace('t1')
    assert path == store.trace_dir() / 't1.jsonl' and path.is_file()
    with pytest.raises(ValueError):
        store.export_trace('nope')
