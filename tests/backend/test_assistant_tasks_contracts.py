"""The result envelope refuses to describe a success it did not earn."""
import json

import pytest

from randall.assistant.tasks import contracts
from randall.assistant.tasks.contracts import (UNKNOWN, CheckResult, CostRoll, ModelSpan, NextRequest,
                                       StageSpan, TaskResult, Wish, money)


def check(status='pass', **extra):
    return CheckResult(check_id='extent_v1', implementation_version='1.0', status=status, **extra)


def test_a_running_task_has_no_outcome_and_a_finished_one_must():
    TaskResult().validate()
    with pytest.raises(ValueError, match='no outcome yet'):
        TaskResult(outcome='success').validate()
    with pytest.raises(ValueError, match='must state its outcome'):
        TaskResult(state='completed').validate()
    TaskResult(state='completed', outcome='partial').validate()


def test_terminal_states_and_outcomes_are_the_spec_vocabulary():
    assert contracts.STATES == {'running', 'waiting_decision', 'waiting_approval',
                                'completed', 'failed', 'cancelled'}
    assert contracts.OUTCOMES == {'success', 'partial', 'blocked', 'denied', 'failed', 'cancelled'}
    with pytest.raises(ValueError):
        TaskResult(state='validated').validate()
    with pytest.raises(ValueError):
        TaskResult(state='completed', outcome='ok').validate()


def test_achieved_is_exactly_the_four_postconditions():
    assert set(contracts.POSTCONDITIONS) == {'prepared', 'exported', 'installed', 'previewed'}
    envelope = TaskResult()
    envelope.achieved.pop('previewed')
    with pytest.raises(ValueError, match='achieved must carry'):
        envelope.validate()
    envelope = TaskResult()
    envelope.achieved['previewed'] = 1
    with pytest.raises(ValueError, match='booleans'):
        envelope.validate()


def test_installed_cannot_be_claimed_without_prepared():
    envelope = TaskResult(state='completed', outcome='success')
    envelope.achieved.update(installed=True)
    with pytest.raises(ValueError, match='installed cannot be true without prepared'):
        envelope.validate()
    envelope.achieved.update(prepared=True)
    envelope.validate()


def test_a_failed_or_unknown_required_check_cannot_report_success():
    for status in ('fail', 'unknown'):
        envelope = TaskResult(state='completed', outcome='success', checks=[check(status)])
        with pytest.raises(ValueError, match='cannot report success'):
            envelope.validate()
        assert envelope.blocking_checks[0].status == status
    # partial/blocked are the honest answers, and warn does not block.
    TaskResult(state='completed', outcome='blocked', checks=[check('fail')]).validate()
    TaskResult(state='completed', outcome='success', checks=[check('warn')]).validate()


def test_an_optional_check_does_not_block_but_stays_visible():
    envelope = TaskResult(state='completed', outcome='success',
                          checks=[check('unknown', required=False)])
    envelope.validate()
    assert envelope.blocking_checks == []
    assert envelope.checks[0].status == 'unknown'


def test_not_applicable_needs_a_reason_and_version_is_mandatory():
    with pytest.raises(ValueError, match='reason'):
        CheckResult(check_id='posture_v1', implementation_version='1', status='not_applicable').validate()
    with pytest.raises(ValueError, match='implementation_version'):
        CheckResult(check_id='posture_v1', status='pass').validate()


def test_waiting_states_require_a_matching_typed_request():
    with pytest.raises(ValueError, match='requires a typed next request'):
        TaskResult(state='waiting_approval').validate()
    decision = NextRequest(kind='decision', allowed_responses=['hair', 'hair_and_fur', 'stop'])
    with pytest.raises(ValueError, match='requires a approval request'):
        TaskResult(state='waiting_approval', next=decision).validate()
    TaskResult(state='waiting_decision', next=decision).validate()


def test_an_approval_request_must_name_its_sealed_subject():
    with pytest.raises(ValueError, match='sealed operation'):
        NextRequest(kind='approval', allowed_responses=['approve', 'deny']).validate()
    NextRequest(kind='approval', allowed_responses=['approve', 'deny'],
                operation_digest='sha256:abc').validate()


def test_a_request_from_an_earlier_revision_is_stale():
    stale = NextRequest(kind='decision', task_revision=1, allowed_responses=['a', 'b'])
    with pytest.raises(ValueError, match='stale'):
        TaskResult(revision=2, state='waiting_decision', next=stale).validate()


def test_a_failed_task_carries_its_error():
    with pytest.raises(ValueError, match='must carry its error'):
        TaskResult(state='failed', outcome='failed').validate()
    TaskResult(state='failed', outcome='failed', error={'kind': 'provider'}).validate()


def test_envelope_round_trips_through_json():
    envelope = TaskResult(workflow='recolor_part', state='waiting_decision',
                          next=NextRequest(kind='decision', allowed_responses=['both', 'stop']),
                          checks=[check('warn')])
    envelope.validate()
    data = json.loads(json.dumps(envelope.to_dict()))
    assert data['contracts_version'] == contracts.CONTRACTS_VERSION
    restored = TaskResult.from_dict(data)
    restored.validate()
    assert isinstance(restored.next, NextRequest) and restored.next.kind == 'decision'
    assert isinstance(restored.checks[0], CheckResult) and restored.checks[0].status == 'warn'


# ------------------------------------------------------------------ money

def test_an_unreported_cost_is_unknown_and_never_zero():
    assert money(None) is UNKNOWN and money(float('nan')) is UNKNOWN and money(-1) is UNKNOWN
    assert money('0.01') is UNKNOWN
    assert money(0.0) == 0.0 and money(0.02) == 0.02     # a real free model stays a measurement
    assert UNKNOWN != 0 and not UNKNOWN
    assert UNKNOWN == 'unknown'


def test_unknown_poisons_a_total_instead_of_vanishing_from_it():
    with pytest.raises(TypeError):
        UNKNOWN + 0.02


def test_cost_roll_reports_coverage_separately_from_the_total():
    roll = CostRoll().charge(0.02).charge(UNKNOWN).charge(0.01)
    assert roll.reported_usd == 0.03 and roll.reported_requests == 2 and roll.unknown_requests == 1
    assert roll.total_usd is UNKNOWN                 # one charge is still outstanding
    assert roll.coverage == round(2 / 3, 6)
    assert roll.to_dict()['total_usd'] == 'unknown'
    assert CostRoll().charge(0.02).total_usd == 0.02


def test_model_span_reads_openrouter_usage_without_inventing_anything():
    span = ModelSpan(role='main')
    span.record_usage({'prompt_tokens': 1200, 'completion_tokens': 80,
                       'prompt_tokens_details': {'cached_tokens': 900},
                       'completion_tokens_details': {'reasoning_tokens': 40},
                       'cost': 0.0031})
    assert (span.input_tokens, span.output_tokens) == (1200, 80)
    assert span.cached_input_tokens == 900 and span.reasoning_tokens == 40
    assert span.reported_cost_usd == 0.0031 and span.cost_status == 'reported'
    # A usage block with no cost leaves the charge unknown, not zero.
    bare = ModelSpan(role='main')
    bare.record_usage({'prompt_tokens': 5})
    assert bare.reported_cost_usd is UNKNOWN and bare.cost_status == 'unknown'
    assert bare.input_tokens == 5 and bare.cached_input_tokens is None


def test_a_reconciled_charge_wins_and_a_free_model_is_not_unknown():
    span = ModelSpan(role='jev')
    span.record_cost(0.004, reconciled=0.0042)
    assert span.cost_status == 'reconciled' and span.reconciled_cost_usd == 0.0042
    # A provider that reported 0.0 is `free`: measured, not missing.
    free = ModelSpan(role='jev').record_cost(0.0)
    assert free.cost_status == 'free'


def test_span_finish_measures_and_rejects_an_unknown_status():
    span = StageSpan(stage_name='prepare', stage_version='1')
    span.finish('ok')
    assert span.status == 'ok' and span.duration_ms >= 0
    with pytest.raises(ValueError):
        StageSpan().finish('probably_fine')


def test_span_field_lists_match_the_spec():
    model = set(ModelSpan.__dataclass_fields__)
    for name in ('decision_id', 'role', 'task_family', 'dependency_ids', 'requested_model',
                 'resolved_model', 'resolved_provider', 'configuration_version',
                 'prompt_template_version', 'provider_request_id', 'provider_generation_id',
                 'queue_ms', 'dispatch_ms', 'first_token_ms', 'completion_ms', 'timeout_s',
                 'retry_delay_ms', 'input_tokens', 'output_tokens', 'cached_input_tokens',
                 'reasoning_tokens', 'reserved_cost_usd', 'reported_cost_usd',
                 'reconciled_cost_usd', 'cost_status', 'finish_reason', 'http_status',
                 'provider_error', 'retry_classification', 'input_artifact_hashes',
                 'attached_image_hashes', 'tool_schema_version', 'response_validation',
                 'cancelled_after_ms', 'span_id', 'parent_span_id', 'operation_id', 'attempt',
                 'component_version', 'start_utc', 'monotonic_start', 'duration_ms', 'status'):
        assert name in model, name
    stage = set(StageSpan.__dataclass_fields__)
    for name in ('stage_name', 'stage_version', 'parameter_hash', 'input_artifact_hashes',
                 'output_artifact_hashes', 'queued_at', 'lock_wait_ms', 'running_at',
                 'completed_at', 'cache_hit', 'reused_operation_id', 'worker_identity',
                 'worker_exit_status', 'cpu_time_ms', 'peak_memory_bytes', 'check_results',
                 'error_type', 'cancellation_acknowledged', 'cleanup_result', 'child_span_ids'):
        assert name in stage, name


def test_a_wish_names_a_missing_operation_and_dedupes_by_capability():
    wish = Wish(capability='menu_output_preview', blocked_operation='render_menu_artifact',
                app_version='0.8.9')
    wish.validate()
    same = Wish(capability='menu_output_preview', blocked_operation='render_menu_artifact',
                app_version='0.8.9', task_id='other')
    assert wish.dedupe_key == same.dedupe_key
    assert Wish(capability='menu_output_preview', blocked_operation='render_menu_artifact',
                app_version='0.9.0').dedupe_key != wish.dedupe_key
    with pytest.raises(ValueError, match='missing capability'):
        Wish(blocked_operation='x').validate()
    with pytest.raises(ValueError, match='operation it blocked'):
        Wish(capability='x').validate()
