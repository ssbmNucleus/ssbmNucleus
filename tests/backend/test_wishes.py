"""Wishes: the classifier's boundaries, the counting, the projection, the consent.

The point of these tests is NOT that the sentences read nicely. It is that the
three things a wish can lie about cannot happen:

* a failure that is not a missing capability becoming a backlog row,
* a count that grows because the engine opened another task, and
* the word "saved" or a sent report appearing without the write or the consent
  that would justify it.

Every classifier case is driven by TYPED evidence; nothing here matches English.
"""
import json
import threading
import time
import zipfile
from dataclasses import replace
from io import BytesIO

import pytest
from flask import Flask

from randall.assistant import capabilities
from randall.assistant.tasks import store
from randall.reports import wish_submit, wishes as wishlib
from randall.reports.wishes import Classification, Observation, Requirement, classify_blocker
from randall.routes import wishes as wishes_module
from randall.reports import report_transport


@pytest.fixture(autouse=True)
def fresh(vault):
    """Own storage root per test; drop BOTH cached connections with it.

    The wish tables live in the same file on their own handle, so a stale
    handle would point at the previous test's temp directory.
    """
    store.close()
    wishlib.close()
    yield vault
    store.close()
    wishlib.close()


def build_requirement(**extra):
    base = dict(operation='builds.commit_change', required_for_outcome=True,
                requested_outcome='Install a prepared change into this build',
                workflow='install_menu')
    base.update(extra)
    return Requirement(**base)


# ---------------------------------------------------------------- classification

def test_an_explicit_user_rejection_is_a_denial_and_never_a_wish():
    verdict = classify_blocker(Observation(evidence='user_denied'), build_requirement())
    assert verdict.outcome == 'denial' and verdict.creates_wish is False


def test_a_cancelled_task_is_a_cancellation_even_mid_capability_gap():
    verdict = classify_blocker(Observation(evidence='cancelled',
                                           operation='builds.commit_change'),
                               build_requirement())
    assert verdict.outcome == 'cancelled' and verdict.creates_wish is False


@pytest.mark.parametrize('evidence', ['missing_input', 'ambiguous_selection',
                                      'unresolved_identification'])
def test_missing_ambiguous_or_unresolved_input_asks_instead_of_filing(evidence):
    verdict = classify_blocker(Observation(evidence=evidence), build_requirement())
    assert verdict.outcome == 'needs_decision' and verdict.creates_wish is False


def test_a_search_that_ran_and_matched_nothing_is_no_match():
    verdict = classify_blocker(Observation(evidence='search_completed_no_match'),
                               build_requirement())
    assert verdict.outcome == 'no_match' and verdict.creates_wish is False


@pytest.mark.parametrize('evidence', ['missing_dependency', 'unloadable_dependency'])
def test_a_missing_bundled_dependency_is_a_packaging_defect(evidence):
    verdict = classify_blocker(Observation(evidence=evidence), build_requirement())
    assert verdict.outcome == 'packaging_defect' and verdict.creates_wish is False


def test_a_transient_provider_failure_is_an_outage():
    verdict = classify_blocker(Observation(evidence='provider_failure', transient=True,
                                           facts={'http_status': 502}), build_requirement())
    assert verdict.outcome == 'outage' and verdict.creates_wish is False


def test_a_provider_failure_nobody_classified_stays_unclassified():
    """Transience must be established, not assumed: an unknown 500 is not an outage."""
    verdict = classify_blocker(Observation(evidence='provider_failure', transient=None),
                               build_requirement())
    assert verdict.outcome == 'unclassified_failure' and verdict.creates_wish is False


@pytest.mark.parametrize('evidence', ['invalid_credentials', 'missing_user_configuration',
                                      'disabled_operation'])
def test_credentials_and_configuration_are_setup_not_demand(evidence):
    verdict = classify_blocker(Observation(evidence=evidence), build_requirement())
    assert verdict.outcome == 'needs_setup' and verdict.creates_wish is False


@pytest.mark.parametrize('evidence', ['contract_violation', 'corrupt_output',
                                      'incorrect_measurement', 'failed_round_trip',
                                      'unexpected_exception'])
def test_a_supported_operation_breaking_its_contract_is_a_bug(evidence):
    verdict = classify_blocker(Observation(evidence=evidence), build_requirement())
    assert verdict.outcome == 'bug' and verdict.creates_wish is False


def test_an_invented_tool_name_gets_a_bounded_repair_and_claims_nothing():
    verdict = classify_blocker(Observation(evidence='unknown_tool', operation='make_it_cool'),
                               Requirement())
    assert verdict.outcome == 'blocked_input'
    assert verdict.repair == 'bounded_tool_repair' and verdict.creates_wish is False


def test_an_advertised_tool_that_cannot_dispatch_is_a_bug_not_a_wish():
    verdict = classify_blocker(
        Observation(evidence='undispatchable_advertised_tool', operation='search_vault'),
        Requirement(operation='search_vault', required_for_outcome=True))
    assert verdict.outcome == 'bug' and verdict.creates_wish is False


def test_a_rejected_input_and_a_rejected_candidate_are_separate_outcomes():
    rejected = classify_blocker(Observation(evidence='input_rejected'), build_requirement())
    unshippable = classify_blocker(Observation(evidence='quality_rejected'), build_requirement())
    assert rejected.outcome == 'blocked_input' and unshippable.outcome == 'quality_blocked'
    assert not rejected.creates_wish and not unshippable.creates_wish


def test_a_confirmed_required_unsupported_operation_is_a_wish():
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='builds.commit_change',
                    variant='extracted_iso'), build_requirement())
    assert verdict.outcome == 'wish' and verdict.creates_wish is True
    assert verdict.capability == 'unsupported_build_commit'
    assert verdict.implementation_version == 'builds.commit_change@1'
    assert verdict.variant == 'extracted_iso'


def test_preparation_alone_does_not_require_the_install_capability():
    """`prepare_change` meeting an uncommittable build is not a request to install."""
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='builds.commit_change',
                    variant='extracted_iso'),
        build_requirement(required_for_outcome=False))
    assert verdict.outcome == 'not_a_blocker' and verdict.creates_wish is False


def test_an_incidental_unavailable_menu_preview_manufactures_no_demand():
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='render_menu_artifact'),
        Requirement(operation='render_menu_artifact', required_for_outcome=False))
    assert verdict.outcome == 'not_a_blocker' and verdict.creates_wish is False


def test_a_requested_menu_preview_is_a_wish():
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='render_menu_artifact',
                    variant='character_select'),
        Requirement(operation='render_menu_artifact', required_for_outcome=True,
                    workflow='install_menu'))
    assert verdict.outcome == 'wish' and verdict.capability == 'menu_output_preview'


def test_an_out_of_domain_request_is_outside_scope_and_never_reaches_the_backlog():
    verdict = classify_blocker(
        Observation(evidence='out_of_scope_request', operation='other_game.modify'),
        Requirement(operation='other_game.modify', required_for_outcome=True, domain='outside'))
    assert verdict.outcome == 'outside_scope' and verdict.creates_wish is False


def test_outside_todays_capabilities_but_inside_melee_is_a_legitimate_wish():
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='fighter.author_moveset'),
        Requirement(operation='fighter.author_moveset', required_for_outcome=True))
    assert verdict.outcome == 'wish' and verdict.capability == 'moveset_authoring'


def test_an_operation_no_definition_covers_is_unclassified_not_a_wish():
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='fighter.make_it_rain'),
        Requirement(operation='fighter.make_it_rain', required_for_outcome=True))
    assert verdict.outcome == 'unclassified_failure' and verdict.creates_wish is False


def test_a_declared_supported_operation_that_did_not_run_is_a_bug():
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='assistant.tools.dispatch'),
        Requirement(operation='assistant.tools.dispatch', required_for_outcome=True))
    assert verdict.outcome == 'bug' and verdict.creates_wish is False


def test_untyped_evidence_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        classify_blocker(Observation(evidence='the renderer blew up'), build_requirement())


def test_an_undeclared_variant_cannot_widen_the_grouping_key():
    """An input nobody declared is not evidence: it is refused, not rounded."""
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='builds.commit_change',
                    variant='PlFxNr.dat'), build_requirement())
    assert verdict.outcome == 'unclassified_failure' and verdict.creates_wish is False
    assert verdict.reason == 'capability_status_unknown'


# ------------------------------------------------------- dedupe and occurrences

def recolor_wish(variant='per_mesh_mask'):
    return classify_blocker(
        Observation(evidence='operation_unavailable',
                    operation='skinlab.recolor_part_in_isolation', variant=variant,
                    facts={'separable_by_mask': False, 'mask_available': False}),
        Requirement(operation='skinlab.recolor_part_in_isolation', required_for_outcome=True,
                    workflow='recolor_part'))


def test_the_grouping_key_ignores_wording_app_release_and_identity():
    one = wishlib.dedupe_key('menu_output_preview', 'render_menu_artifact', 'menus.preview@1')
    two = wishlib.dedupe_key('menu_output_preview', 'render_menu_artifact', 'menus.preview@1')
    assert one == two and one.startswith('sha256:')
    # A changed IMPLEMENTATION groups separately; a variant does too.
    assert one != wishlib.dedupe_key('menu_output_preview', 'render_menu_artifact',
                                     'menus.preview@2')
    assert one != wishlib.dedupe_key('menu_output_preview', 'render_menu_artifact',
                                     'menus.preview@1', 'stage_select')


def test_two_variants_of_the_same_capability_are_two_rows():
    assert wishlib.key_for(recolor_wish('per_mesh_mask')) != wishlib.key_for(
        recolor_wish('separate_overlapping_texture_usage'))


def test_repeated_calls_in_one_conversation_count_once():
    verdict = recolor_wish()
    for turn in range(4):
        # The engine opens a FRESH task every turn: task ids differ, the
        # conversation does not.
        record = wishlib.record(verdict, task_id=f'task_{turn}', conversation_id='chat_1')
        assert record.persisted
    assert record.requesting_conversations == 1
    assert wishlib.total_encounters(record.dedupe_key) == 4


def test_a_different_conversation_is_another_requesting_conversation():
    verdict = recolor_wish()
    wishlib.record(verdict, task_id='t1', conversation_id='chat_1')
    record = wishlib.record(verdict, task_id='t2', conversation_id='chat_2')
    assert record.requesting_conversations == 2


def test_a_repeated_call_in_one_task_revision_reuses_the_same_observation():
    verdict = recolor_wish()
    first = wishlib.record(verdict, task_id='t1', task_revision=1, conversation_id='chat_1')
    again = wishlib.record(verdict, task_id='t1', task_revision=1, conversation_id='chat_1')
    assert again.already_recorded and again.wish.wish_id == first.wish.wish_id
    assert len([w for w in store.wishes('t1')]) == 1


def test_a_new_revision_keeps_its_own_evidence_without_adding_demand():
    verdict = recolor_wish()
    wishlib.record(verdict, task_id='t1', task_revision=1, conversation_id='chat_1')
    record = wishlib.record(verdict, task_id='t1', task_revision=2, conversation_id='chat_1')
    assert not record.already_recorded
    assert len(store.wishes('t1')) == 2
    assert record.requesting_conversations == 1


def test_counts_survive_a_restart():
    verdict = recolor_wish()
    wishlib.record(verdict, task_id='t1', conversation_id='chat_1')
    store.close()                                     # restart
    assert wishlib.requesting_conversations(wishlib.key_for(verdict)) == 1


def test_only_a_wish_may_be_recorded():
    outage = classify_blocker(Observation(evidence='provider_failure', transient=True),
                              build_requirement())
    with pytest.raises(ValueError):
        wishlib.record(outage, task_id='t1', conversation_id='chat_1')


def test_a_failed_local_write_never_reports_persisted(monkeypatch):
    def explode(_wish):
        raise RuntimeError('disk is gone')
    monkeypatch.setattr(store, 'record_wish', explode)
    record = wishlib.record(recolor_wish(), task_id='t1', conversation_id='chat_1')
    assert record.persisted is False and 'disk is gone' in record.error
    assert record.wish is not None                    # the user's work is not lost


# --------------------------------------------------------------- the projection
#
# Review finding 5: the projection copied caller-supplied strings, and the old
# canaries only seeded identity/evidence fields. Every field is now an enum, a
# validated id, a number or catalogue text -- and every field gets a canary.

CANARY = 'CANARY-7f3a-chat-text'


def tainted_wish(**extra):
    """A recorded wish with a canary in every field a caller can influence."""
    verdict = recolor_wish()
    record = wishlib.record(verdict, task_id='task_secret', conversation_id='chat_secret',
                            workflow=f'{CANARY}-workflow')
    wish = record.wish
    wish.requested_outcome = f'{CANARY} requested outcome'
    wish.available_alternative = f'{CANARY} alternative'
    wish.workflow = f'{CANARY}-workflow'
    wish.evidence_ids = ['C:/Users/someone/storage/PlFxNr.dat', 'sk-live-TOKEN',
                         f'{CANARY}-evidence', 'operation_unavailable']
    wish.app_version = f'{CANARY} 1.0'
    wish.record_status = f'{CANARY}-status'
    for key, value in extra.items():
        setattr(wish, key, value)
    return verdict, wish


def test_the_public_summary_carries_no_caller_text_at_all():
    verdict, wish = tainted_wish()
    summary = wishlib.public_summary(wish, classification=verdict, include_counts=True)
    blob = json.dumps(summary)
    for canary in (CANARY, 'task_secret', 'chat_secret', 'PlFxNr', 'sk-live', 'C:/Users'):
        assert canary not in blob, f'{canary} survived the projection'
    for withheld in wishlib.WITHHELD_FIELDS:
        assert withheld not in summary
    assert summary['evidence_codes'] == ['operation_unavailable']
    assert summary['capability'] == 'independent_part_recolor'
    assert summary['requesting_conversations'] == 1


def test_every_projected_field_comes_from_the_catalogue_or_a_closed_set():
    verdict, wish = tainted_wish()
    definition = capabilities.by_name('independent_part_recolor')
    summary = wishlib.public_summary(wish, classification=verdict)
    assert summary['requested_outcome'] == definition.requested_outcome
    assert summary['limitation'] == definition.limitation
    assert summary['alternatives'] == list(definition.alternatives)
    assert summary['blocked_operation'] == definition.operation
    assert summary['implementation_version'] == definition.implementation_version
    assert summary['workflow'] == 'other'            # the canary workflow is not known
    assert summary['app_version'] == 'unknown'       # the canary version is not a version
    assert summary['record_status'] == 'queued'
    assert summary['kind'] == 'capability_gap'


def test_an_undeclared_capability_is_rejected_rather_than_projected():
    """Without a definition there is no trusted text, so there is no projection."""
    verdict, wish = tainted_wish()
    wish.capability = 'something_nobody_declared'
    with pytest.raises(ValueError):
        wishlib.public_summary(wish)


def test_a_wish_without_an_authoritative_key_is_rejected():
    verdict, wish = tainted_wish()
    wish.dedupe_key = 'independent_part_recolor'      # the old facade key
    with pytest.raises(ValueError):
        wishlib.public_summary(wish, classification=verdict)


def test_the_projection_is_an_allowlist():
    verdict, wish = tainted_wish()
    summary = wishlib.public_summary(wish, classification=verdict)
    assert set(summary) <= set(wishlib.PUBLIC_FIELDS)


def test_an_unknown_workflow_never_travels_as_free_text():
    assert wishlib.safe_workflow(f'{CANARY}') == 'other'
    assert wishlib.safe_workflow('recolor_part') == 'recolor_part'
    assert wishlib.safe_workflow('') == 'other'


def test_an_implausible_app_version_becomes_unknown(monkeypatch):
    monkeypatch.setenv('NUCLEUS_APP_VERSION', 'x' * 80)
    assert wishlib.safe_app_version() == 'unknown'
    monkeypatch.setenv('NUCLEUS_APP_VERSION', '0.8.9')
    assert wishlib.safe_app_version() == '0.8.9'


# ------------------------------------------------------------ capability_status
#
# Review finding 11: availability is scope-aware. `builds.commit_change` WORKS,
# and is missing only for a build that is not a Nucleus project.

@pytest.mark.parametrize('operation,scope,expected', [
    ('builds.commit_change', '', 'supported'),
    ('builds.commit_change', 'mex_project', 'supported'),
    ('builds.commit_change', 'extracted_iso', 'unsupported'),
    ('builds.commit_change', 'some_new_container', 'unknown'),
    ('render_menu_artifact', '', 'unsupported'),
    ('render_menu_artifact', 'character_select', 'unsupported'),
    ('skinlab.recolor_part_in_isolation', '', 'unsupported'),
    ('skinlab.select_part_within_texture', '', 'unsupported'),
    ('fighter.author_moveset', '', 'unsupported'),
    ('assistant.tools.dispatch', '', 'supported'),
    ('other_game.modify', '', 'outside_scope'),
    ('general.assistant_chat', '', 'outside_scope'),
    ('fighter.make_it_rain', '', 'unknown'),
])
def test_capability_status_for_each_seeded_definition(operation, scope, expected):
    assert capabilities.capability_status(operation, scope) == expected


def test_an_unrecognised_build_format_is_refused_not_rounded():
    """Rounding an unknown container to a known one would file a fictional gap."""
    verdict = classify_blocker(
        Observation(evidence='operation_unavailable', operation='builds.commit_change',
                    variant='some_new_container'), build_requirement())
    assert verdict.outcome == 'unclassified_failure' and verdict.creates_wish is False


def test_a_declared_variant_is_still_required_for_the_key():
    definition = capabilities.by_name('unsupported_build_commit')
    assert definition.variant_or_refuse('extracted_iso') == 'extracted_iso'
    with pytest.raises(ValueError):
        definition.variant_or_refuse('PlFxNr.dat')


def test_every_seeded_definition_is_internally_consistent():
    for definition in capabilities.CAPABILITIES:
        assert definition.status in capabilities.STATUSES
        assert definition.domain in capabilities.DOMAINS
        assert definition.limitation.endswith(('.', '!'))
        assert definition.implementation_version
        if definition.status == 'unsupported' or definition.unsupported_scopes:
            assert definition.alternatives, f'{definition.name} offers no real alternative'
        for term in ('library', 'tool', '_id', 'dedupe'):
            assert term not in definition.limitation.lower()
        # A scope may not be declared both ways.
        assert not (set(definition.supported_scopes) & set(definition.unsupported_scopes))


# ---------------------------------------------------------------------- footer


def test_there_is_no_footer_without_a_write():
    assert wishlib.footer(recorded=False) is None
    assert wishlib.footer(recorded=True)['text'] == wishlib.FOOTER_SAVED
    assert wishlib.footer(recorded=True)['action'] == wishlib.FOOTER_ACTION
    assert wishlib.footer(recorded=True, suppressed=True)['action'] is None


# ------------------------------------------------------------------- endpoints

class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class FakeSetup:
    """Stands in for `shared.diagnostics.bug_report`: same names, no logs, no network."""
    _BUGREPORT_URL = 'https://example.invalid/bugreport'
    #: Mutable so a test can change what the log collector would return BETWEEN
    #: review and send -- that is the point of freezing the bytes.
    log_text = 'chat text canary'

    @staticmethod
    def bugreport_channel():
        return 'windows'

    @staticmethod
    def _bugreport_auth_headers():
        return {'Authorization': 'Bearer friends-session'}

    @classmethod
    def _build_logs_zip(cls, slippi_path='', extra_files=None, budget_bytes=None):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('logs/app.log', cls.log_text)
        buffer.seek(0)
        return buffer, 1, 0, False


@pytest.fixture
def client(vault, monkeypatch):
    FakeSetup.log_text = 'chat text canary'
    monkeypatch.setattr(wishes_module, '_transport', lambda: FakeSetup)
    app = Flask(__name__)
    app.register_blueprint(wishes_module.wishes_bp)
    return app.test_client()


@pytest.fixture
def transport(monkeypatch):
    """Capture the two-stage POST/PUT without touching the network."""
    sent = {'post': [], 'put': []}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent['post'].append({'url': url, 'meta': json, 'headers': headers or {}})
        return FakeResponse(200, {'id': f'rep_{len(sent["post"])}'})

    def fake_put(url, data=None, headers=None, timeout=None):
        sent['put'].append({'url': url, 'data': data})
        return FakeResponse(200, {'notified': True})

    monkeypatch.setattr(report_transport.requests, 'post', fake_post)
    monkeypatch.setattr(report_transport.requests, 'put', fake_put)
    return sent


def seed(conversation='chat_1', task='t1'):
    verdict = recolor_wish()
    record = wishlib.record_wish(task, verdict, conversation_id=conversation)
    return record.dedupe_key.split(':')[-1]


def review(client, key, **params):
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    return client.get(f'/api/mex/wishes/{key}/review' + (f'?{query}' if query else '')).get_json()


def send(client, key, snapshot, **extra):
    body = {'consent': True, 'submission_id': snapshot['submission_id'],
            'approval_hash': snapshot['approval_hash']}
    body.update(extra)
    return client.post(f'/api/mex/wishes/{key}/submit', json=body)


def zip_members(blob):
    """Every member of the uploaded bundle, decompressed -- names AND contents."""
    archive = zipfile.ZipFile(BytesIO(blob))
    return {name: archive.read(name).decode('utf-8', 'replace') for name in archive.namelist()}


def test_the_backlog_lists_gaps_with_their_counts(client):
    seed('chat_1', 't1')
    seed('chat_2', 't2')
    body = client.get('/api/mex/wishes').get_json()
    assert body['success'] and body['count'] == 1
    row = body['wishes'][0]
    assert row['capability'] == 'independent_part_recolor'
    assert row['conversations'] == 2 and row['encounters'] == 2
    assert row['variant'] == 'per_mesh_mask' and row['suppressed'] is False
    assert row['still_unsupported'] is True and row['legacy'] is False


def test_capability_status_endpoint_answers_from_the_same_definitions(client):
    body = client.get('/api/mex/wishes/capability_status?operation=render_menu_artifact').get_json()
    assert body['status'] == 'unsupported' and body['capability'] == 'menu_output_preview'
    scoped = client.get('/api/mex/wishes/capability_status?operation=builds.commit_change'
                        '&scope=extracted_iso').get_json()
    assert scoped['status'] == 'unsupported'
    project = client.get('/api/mex/wishes/capability_status?operation=builds.commit_change'
                         '&scope=mex_project').get_json()
    assert project['status'] == 'supported'
    unknown = client.get('/api/mex/wishes/capability_status?operation=nope').get_json()
    assert unknown['status'] == 'unknown'


def test_review_freezes_the_contents_and_sends_nothing(client, transport):
    key = seed()
    body = review(client, key)
    assert body['success'] and body['approval_hash'].startswith('sha256:')
    assert body['payload']['kind'] == 'capability_gap'
    assert body['payload']['requesting_conversations'] == 1
    assert body['manifest']['include_discord_identity'] is False
    assert [m['name'] for m in body['manifest']['members']] == ['wish.json']
    assert body['manifest']['bundle']['sha256'].startswith('sha256:')
    assert 'No conversation or files included.' in body['consent_text']
    assert transport['post'] == [] and transport['put'] == []


def test_submitting_sends_a_summary_only_bundle(client, transport):
    key = seed()
    snapshot = review(client, key)
    body = send(client, key, snapshot).get_json()
    assert body['success'] and body['state'] == 'sent' and body['id'] == 'rep_1'
    meta = transport['post'][0]['meta']
    assert meta['kind'] == 'capability_gap'
    assert meta['wish']['capability'] == 'independent_part_recolor'
    # Default submission is anonymous: the Discord session is NOT forwarded.
    assert transport['post'][0]['headers'] == {}
    members = zip_members(transport['put'][0]['data'])
    assert list(members) == ['wish.json']
    blob = json.dumps(meta) + json.dumps(members)
    for canary in ('chat_1', 't1', 'chat text canary', 'C:/Users', CANARY):
        assert canary not in blob


def test_a_caller_supplied_workflow_never_reaches_the_report(client, transport):
    """Review finding 5's own probe: the workflow arrives over HTTP."""
    key = seed()
    snapshot = review(client, key, workflow=f'{CANARY}-workflow')
    send(client, key, snapshot)
    meta = transport['post'][0]['meta']
    members = zip_members(transport['put'][0]['data'])
    assert meta['wish']['workflow'] == 'other'
    assert json.loads(members['wish.json'])['workflow'] == 'other'
    # Every member, decompressed, not a substring search over compressed bytes.
    for name, text in members.items():
        assert CANARY not in text, f'{CANARY} reached {name}'


# ------------------------------------------------ consent covers the contents

def test_identity_and_attachments_change_the_approval_hash(client):
    """Review finding 2: an anonymous review and one with identity + logs
    produced the SAME hash, so the click authorised bytes it never saw."""
    key = seed()
    plain = review(client, key)
    with_identity = review(client, key, identity=1)
    with_logs = review(client, key, attachments='app_logs')
    assert plain['approval_hash'] != with_identity['approval_hash']
    assert plain['approval_hash'] != with_logs['approval_hash']
    assert with_identity['approval_hash'] != with_logs['approval_hash']


def test_attachment_bytes_are_frozen_at_review(client, transport):
    """Logs that change between review and send cannot ride along unapproved."""
    key = seed()
    snapshot = review(client, key, attachments='app_logs')
    approved = [m for m in snapshot['manifest']['members'] if m['name'] == 'app_logs'][0]
    FakeSetup.log_text = 'SOMETHING ELSE ENTIRELY'
    send(client, key, snapshot)
    members = zip_members(transport['put'][0]['data'])
    inner = zipfile.ZipFile(BytesIO(zipfile.ZipFile(
        BytesIO(transport['put'][0]['data'])).read('app_logs')))
    assert inner.read('logs/app.log').decode() == 'chat text canary'
    assert approved['bytes'] > 0 and sorted(members) == ['app_logs', 'wish.json']


def test_the_manifest_discloses_every_member_before_approval(client):
    key = seed()
    snapshot = review(client, key, attachments='app_logs', identity=1)
    names = {m['name'] for m in snapshot['manifest']['members']}
    assert names == {'wish.json', 'app_logs'}
    for member in snapshot['manifest']['members']:
        assert member['bytes'] > 0 and member['sha256'].startswith('sha256:')
    assert snapshot['manifest']['include_discord_identity'] is True
    assert 'app_logs' in snapshot['consent_text']
    assert 'Your Discord identity is included.' in snapshot['consent_text']


def test_the_string_false_is_not_a_boolean_choice(client, transport):
    """Review finding 2: `"false"` satisfied both the consent and identity checks."""
    key = seed()
    snapshot = review(client, key)
    refused = client.post(f'/api/mex/wishes/{key}/submit',
                          json={'consent': 'false', 'submission_id': snapshot['submission_id'],
                                'approval_hash': snapshot['approval_hash']})
    assert refused.status_code == 400
    assert refused.get_json()['error'] == 'invalid_choice'
    assert transport['post'] == []
    with pytest.raises(ValueError):
        wishlib.strict_bool('false')
    with pytest.raises(ValueError):
        wishlib.strict_bool(0)


def test_identity_is_attached_only_when_the_frozen_manifest_approved_it(client, transport):
    key = seed()
    anonymous = review(client, key)
    send(client, key, anonymous)
    assert transport['post'][0]['headers'] == {}


def test_identity_travels_when_it_was_approved(client, transport):
    key = seed()
    snapshot = review(client, key, identity=1)
    send(client, key, snapshot)
    assert transport['post'][0]['headers']['Authorization'] == 'Bearer friends-session'


def test_an_unsupported_attachment_is_refused_not_silently_dropped(client, transport):
    key = seed()
    response = client.get(f'/api/mex/wishes/{key}/review?attachments=conversation')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'unsupported_attachment'
    assert transport['post'] == []


def test_without_consent_nothing_leaves_the_machine(client, transport):
    key = seed()
    snapshot = review(client, key)
    response = client.post(f'/api/mex/wishes/{key}/submit',
                           json={'submission_id': snapshot['submission_id'],
                                 'approval_hash': snapshot['approval_hash']})
    assert response.status_code == 400 and transport['post'] == []


def test_an_approved_snapshot_sends_the_count_that_was_approved(client, transport):
    """Future occurrences never silently update an approved report.

    The snapshot is frozen, so a later occurrence changes neither the bytes nor
    the hash: what goes is the count the user saw.
    """
    key = seed('chat_1', 't1')
    approved = review(client, key)
    assert approved['payload']['requesting_conversations'] == 1
    seed('chat_2', 't2')                         # another conversation arrives
    assert send(client, key, approved).get_json()['success']
    assert transport['post'][0]['meta']['wish']['requesting_conversations'] == 1


def test_a_refreshed_review_invalidates_the_earlier_approval(client, transport):
    """Once the user is shown the NEW contents, the old hash stops working."""
    key = seed('chat_1', 't1')
    stale = review(client, key)
    seed('chat_2', 't2')
    refreshed = review(client, key)              # the UI shows the new count
    assert refreshed['approval_hash'] != stale['approval_hash']
    assert refreshed['payload']['requesting_conversations'] == 2
    response = send(client, key, stale)
    assert response.status_code == 409
    assert response.get_json()['error'] == 'consent_invalid'
    assert transport['post'] == []


def test_a_hash_from_another_submission_cannot_collect_a_receipt(client, transport):
    """Review finding 10: any non-empty hash retrieved the latest sent receipt."""
    key = seed()
    snapshot = review(client, key)
    send(client, key, snapshot)
    other = review(client, key, identity=1)      # a different, unapproved snapshot
    response = client.post(f'/api/mex/wishes/{key}/submit',
                           json={'consent': True, 'submission_id': other['submission_id'],
                                 'approval_hash': snapshot['approval_hash']})
    assert response.status_code == 409
    assert response.get_json()['error'] == 'consent_invalid'
    assert len(transport['post']) == 1


# ------------------------------------------------- exclusive, leased sending

def test_two_concurrent_clicks_produce_one_report(client, transport):
    """Review finding 3: interleaving produced two POSTs and two PUTs.

    Either the second click loses the race and is told so (429), or it arrives
    after the first finished and gets that same receipt back (200). What must
    never happen is a second report, so the network count is the real
    assertion.
    """
    key = seed()
    snapshot = review(client, key)
    start = threading.Barrier(2)
    results = []

    def click():
        start.wait()
        try:
            response = send(client, key, snapshot)
            results.append((response.status_code, response.get_json()))
        finally:
            wishlib.close()

    threads = [threading.Thread(target=click) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(transport['post']) == 1 and len(transport['put']) == 1
    codes = sorted(code for code, _body in results)
    assert codes in ([200, 200], [200, 429]), codes
    ids = {body.get('id') for code, body in results if code == 200}
    assert ids == {'rep_1'}
    for code, body in results:
        if code == 429:
            assert body['reason'] in ('already_claimed', 'another_submission_in_flight')


def test_review_does_not_rewrite_an_upload_in_flight(client, transport, monkeypatch):
    """Review finding 3: a review during an upload changed the stored payload,
    cleared consent and reopened sending; completion then marked it sent."""
    key = seed()
    snapshot = review(client, key)
    seen = {}

    def slow_put(url, data=None, headers=None, timeout=None):
        seed('chat_2', 't2')                     # another occurrence arrives
        seen['during'] = review(client, key)     # and the UI refreshes
        return FakeResponse(200, {'notified': True})

    monkeypatch.setattr(report_transport.requests, 'put', slow_put)
    body = send(client, key, snapshot).get_json()
    assert body['success'] and body['state'] == 'sent'
    assert seen['during']['active'] is True
    assert seen['during']['submission_id'] == snapshot['submission_id']
    assert seen['during']['approval_hash'] == snapshot['approval_hash']
    assert seen['during']['can_send'] is False
    assert seen['during']['blocked_reason'] == 'another_submission_in_flight'
    row = wishlib.submission(snapshot['submission_id'])
    assert row['state'] == 'sent' and row['approved_count'] == 1


def test_decline_refuses_to_cancel_an_upload_in_flight(client, transport, monkeypatch):
    key = seed()
    snapshot = review(client, key)
    seen = {}

    def slow_put(url, data=None, headers=None, timeout=None):
        seen['decline'] = client.post(f'/api/mex/wishes/{key}/decline', json={})
        return FakeResponse(200, {'notified': True})

    monkeypatch.setattr(report_transport.requests, 'put', slow_put)
    send(client, key, snapshot)
    assert seen['decline'].status_code == 409
    assert seen['decline'].get_json()['error'] == 'another_submission_in_flight'
    assert wishlib.submission(snapshot['submission_id'])['state'] == 'sent'


def test_a_crashed_upload_does_not_disable_sending_forever(client, transport):
    """Review finding 3: an interrupted `sending` row blocked every future send."""
    key = seed()
    snapshot = review(client, key)
    # Simulate the process dying mid-upload: a claimed lease, then nothing.
    lease, reason, _row = wishlib.claim_send(snapshot['submission_id'],
                                             snapshot['approval_hash'], consent=True)
    assert lease and not reason
    assert wishlib.rate_limit(f'sha256:{key}')[1] == 'another_submission_in_flight'
    # ...and the lease expires.
    conn = wishlib.connection()
    with conn:
        conn.execute('UPDATE wish_submissions SET lease_expires_at=? WHERE submission_id=?',
                     (time.time() - 1, snapshot['submission_id']))
    assert wishlib.recover_stale_sends() == 1
    assert wishlib.rate_limit(f'sha256:{key}')[0] is True
    body = send(client, key, snapshot).get_json()
    assert body['success'] and body['state'] == 'sent'


# ---------------------------------------------- interrupted uploads and retries

def test_a_lost_upload_acknowledgment_retries_into_the_same_report(client, monkeypatch):
    """Review finding 4: the next attempt created a SECOND remote report."""
    key = seed()
    snapshot = review(client, key)
    posts, puts = [], []

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append(json)
        return FakeResponse(200, {'id': f'rep_{len(posts)}'})

    def flaky_put(url, data=None, headers=None, timeout=None):
        puts.append(url)
        if len(puts) == 1:
            raise report_transport.requests.RequestException('connection reset')
        return FakeResponse(200, {'notified': True})

    monkeypatch.setattr(report_transport.requests, 'post', fake_post)
    monkeypatch.setattr(report_transport.requests, 'put', flaky_put)
    first = send(client, key, snapshot).get_json()
    assert first['success'] is False and first['state'] == 'failed'
    assert wishlib.submission(snapshot['submission_id'])['remote_id'] == 'rep_1'
    # Clear the backoff the failure set, then retry.
    _clear_backoff(snapshot['submission_id'])
    second = send(client, key, snapshot).get_json()
    assert second['success'] and second['id'] == 'rep_1'
    assert len(posts) == 1 and [u.split('/')[-2] for u in puts] == ['rep_1', 'rep_1']


def _clear_backoff(submission_id):
    conn = wishlib.connection()
    with conn:
        conn.execute('UPDATE wish_submissions SET retry_not_before=NULL WHERE submission_id=?',
                     (submission_id,))


def test_retry_after_is_enforced_not_merely_stored(client, monkeypatch):
    """Review finding 4: four immediate attempts reached transport despite a
    600-second delay."""
    key = seed()
    snapshot = review(client, key)
    reached = []

    def refuse(url, json=None, headers=None, timeout=None):
        reached.append(url)
        return FakeResponse(429, {'retry_after': 600})

    monkeypatch.setattr(report_transport.requests, 'post', refuse)
    first = send(client, key, snapshot)
    assert first.status_code == 429
    assert wishlib.submission(snapshot['submission_id'])['retry_not_before'] > time.time() + 500
    for _ in range(3):
        again = send(client, key, snapshot)
        assert again.status_code == 429
        assert again.get_json()['reason'] == 'retry_too_soon'
    assert len(reached) == 1


def test_three_attempts_become_a_truthful_local_only_state(client, monkeypatch):
    key = seed()
    snapshot = review(client, key)
    monkeypatch.setattr(report_transport.requests, 'post',
                        lambda *a, **k: FakeResponse(500, {}))
    for attempt in range(wishlib.MAX_SEND_ATTEMPTS):
        response = send(client, key, snapshot)
        _clear_backoff(snapshot['submission_id'])
        assert response.status_code in (409, 502)
    row = wishlib.submission(snapshot['submission_id'])
    assert row['state'] == 'local_only' and row['attempts'] == wishlib.MAX_SEND_ATTEMPTS
    final = send(client, key, snapshot).get_json()
    assert final['state'] == 'local_only' and final['reason'] == 'retries_exhausted'


def test_a_completed_upload_returns_its_previous_receipt_instead_of_refiling(client, transport):
    key = seed()
    snapshot = review(client, key)
    first = send(client, key, snapshot).get_json()
    again = send(client, key, snapshot).get_json()
    assert again['success'] and again['state'] == 'sent' and again['id'] == first['id']
    assert len(transport['post']) == 1 and len(transport['put']) == 1


def test_review_after_a_send_still_shows_the_receipt(client, transport):
    """Review finding 10: a fresh review hid the completed row, and repeating the
    original click then answered 429 instead of returning its receipt."""
    key = seed()
    snapshot = review(client, key)
    sent = send(client, key, snapshot).get_json()
    after = review(client, key)
    assert after['state'] == 'sent' and after['receipt']['id'] == sent['id']
    assert after['submission_id'] == snapshot['submission_id']
    assert send(client, key, snapshot).get_json()['id'] == sent['id']


def test_notified_false_is_still_an_accepted_report(client, monkeypatch):
    key = seed()
    snapshot = review(client, key)
    monkeypatch.setattr(report_transport.requests, 'post',
                        lambda *a, **k: FakeResponse(200, {'id': 'rep_1'}))
    monkeypatch.setattr(report_transport.requests, 'put',
                        lambda *a, **k: FakeResponse(200, {'notified': False}))
    body = send(client, key, snapshot).get_json()
    assert body['success'] and body['state'] == 'sent' and body['notified'] is False


# ------------------------------------------------------------ availability

def test_a_gap_the_build_has_since_closed_is_not_sent(client, transport, monkeypatch):
    key = seed()
    snapshot = review(client, key)
    shipped = replace(capabilities.by_name('independent_part_recolor'), status='supported')
    monkeypatch.setattr(capabilities, '_BY_NAME',
                        {**capabilities._BY_NAME, 'independent_part_recolor': shipped})
    refreshed = review(client, key)
    assert refreshed['still_unsupported'] is False
    assert refreshed['blocked_reason'] == 'capability_now_supported'
    response = send(client, key, snapshot)
    assert response.status_code == 409
    assert response.get_json()['error'] == 'capability_now_supported'
    assert transport['post'] == []


# ------------------------------------------------------------------ declining

def test_declining_sends_nothing_and_can_suppress_the_invitation(client, transport):
    key = seed()
    review(client, key)
    body = client.post(f'/api/mex/wishes/{key}/decline', json={'suppress': True}).get_json()
    assert body['success'] and body['suppressed'] is True
    assert transport['post'] == [] and transport['put'] == []
    # Local counting continues: the gap has not stopped being real.
    assert client.get('/api/mex/wishes').get_json()['wishes'][0]['conversations'] == 1


def test_one_successful_submission_per_key_per_day(client, transport):
    key = seed()
    snapshot = review(client, key)
    send(client, key, snapshot)
    allowed, reason, retry_after = wishlib.rate_limit(f'sha256:{key}')
    assert allowed is False and reason == 'already_sent_today' and retry_after > 0
    assert len(transport['post']) == 1


def test_the_daily_submission_allowance_is_bounded(client, transport, monkeypatch):
    monkeypatch.setattr(wish_submit, 'DAILY_SUBMISSION_LIMIT', 1)
    key = seed()
    send(client, key, review(client, key))
    other = wishlib.key_for(recolor_wish('separate_overlapping_texture_usage'))
    wishlib.record_wish('t9', recolor_wish('separate_overlapping_texture_usage'),
                        conversation_id='chat_9')
    allowed, reason, _ = wishlib.rate_limit(other)
    assert allowed is False and reason == 'daily_limit_reached'


def test_the_outgoing_metadata_stays_within_its_budget(client):
    key = seed()
    snapshot = review(client, key)
    encoded = wishlib.canonical_payload(snapshot['payload']).encode('utf-8')
    assert len(encoded) <= wishlib.PAYLOAD_MAX_BYTES
    assert set(snapshot['payload']) == {
        'schema_version', 'kind', 'submission_id', 'contribution_id', 'dedupe_key',
        'capability', 'blocked_operation', 'implementation_version', 'variant',
        'app_version', 'api_version', 'platform', 'workflow', 'requested_outcome',
        'limitation', 'alternative', 'requesting_conversations', 'evidence_codes'}


# --------------------------------------------- the single public recorder

class FakeTask:
    """The shape `record_wish` reads off a real TaskContext."""

    class _Envelope:
        workflow = 'recolor_part'

    def __init__(self, task_id='t1', revision=1, chat_id='chat_1'):
        self.task_id = task_id
        self.revision = revision
        self.chat_id = chat_id
        self.envelope = self._Envelope()


def test_record_wish_accepts_a_task_context():
    record = wishlib.record_wish(FakeTask(), recolor_wish())
    assert record.recorded and record.wish.task_id == 't1'
    assert record.wish.workflow == 'recolor_part'
    assert record.requesting_conversations == 1


def test_record_wish_accepts_a_bare_task_id_for_a_facade_with_no_context():
    """`deliver.py` and `menus.py` have no TaskContext; they still get one door."""
    record = wishlib.record_wish('t1', recolor_wish(), conversation_id='chat_1')
    assert record.recorded and record.wish.task_id == 't1'


def test_record_wish_classifies_when_the_caller_has_not():
    record = wishlib.record_wish(FakeTask(), operation='fighter.author_moveset')
    assert record.recorded and record.wish.capability == 'moveset_authoring'
    assert record.classification.outcome == 'wish'


def test_an_unset_user_preference_can_never_become_a_backlog_row():
    """`deliver.py`'s "I can't tell which file you launch" is NOT a capability gap.

    The app CAN write a build into a copy the user names; what is missing is the
    user's choice of that file, and an unset preference with an existing
    alternative is a decision. Nothing declares it, so even a caller that tried
    to file it gets `unclassified_failure` and an empty backlog. The absence of
    a definition is the safeguard, so it is asserted like one.
    """
    assert capabilities.capability_status('deliver.write_to_designated_play_copy') == 'unknown'
    record = wishlib.record_wish(FakeTask(task_id='deliver_1', chat_id='chat_7'),
                                 operation='deliver.write_to_designated_play_copy',
                                 workflow='deliver_to_game')
    assert record.recorded is False and record.wish is None
    assert record.classification.outcome == 'unclassified_failure'
    assert wishlib.backlog() == []


def test_record_wish_returns_a_typed_record_instead_of_raising_on_a_non_wish():
    """Bookkeeping must never kill the delivery it is describing."""
    record = wishlib.record_wish(FakeTask(), operation='render_menu_artifact',
                                 required_for_outcome=False)
    assert record.recorded is False and record.wish is None
    assert record.classification.outcome == 'not_a_blocker'
    assert wishlib.backlog() == []


def test_record_wish_survives_a_storage_failure_without_claiming_success(monkeypatch):
    def explode(_wish):
        raise RuntimeError('disk is gone')
    monkeypatch.setattr(store, 'record_wish', explode)
    record = wishlib.record_wish(FakeTask(), recolor_wish())
    assert record.recorded is False and 'disk is gone' in record.error


# ----------------------------------------------------- NUCLEUS_WISH_SUBMIT

@pytest.fixture
def submit_off(monkeypatch):
    monkeypatch.setenv('NUCLEUS_WISH_SUBMIT', '0')
    return monkeypatch


def test_the_gate_is_open_by_default(monkeypatch):
    monkeypatch.delenv('NUCLEUS_WISH_SUBMIT', raising=False)
    assert wishlib.submit_enabled() is True


def test_only_the_exact_string_zero_closes_the_gate(monkeypatch):
    for value, expected in (('0', False), ('1', True), ('false', True), ('', True)):
        monkeypatch.setenv('NUCLEUS_WISH_SUBMIT', value)
        assert wishlib.submit_enabled() is expected


def test_the_gate_table_is_the_authority(monkeypatch):
    """`core.gates` decides; a row swapped in for the test is what submit_enabled reads."""
    from core import gates
    monkeypatch.setitem(gates.GATES, wishlib.SUBMIT_GATE,
                        gates.Gate(env='NUCLEUS_WISH_SUBMIT', packaged_off=True,
                                   covers='sending a recorded feature request', ui='review'))
    monkeypatch.setenv('NUCLEUS_WISH_SUBMIT', '0')
    assert wishlib.submit_enabled() is False
    monkeypatch.setenv('NUCLEUS_WISH_SUBMIT', '1')
    assert wishlib.submit_enabled() is True


def test_with_submission_off_wishes_are_still_recorded_and_counted(submit_off):
    wishlib.record_wish(FakeTask(task_id='t1', chat_id='chat_1'), recolor_wish())
    record = wishlib.record_wish(FakeTask(task_id='t2', chat_id='chat_2'), recolor_wish())
    assert record.recorded and record.requesting_conversations == 2
    row = wishlib.backlog()[0]
    assert row['conversations'] == 2 and row['capability'] == 'independent_part_recolor'


def test_with_submission_off_submit_refuses_without_touching_the_network(client, transport,
                                                                        submit_off):
    key = seed()
    snapshot = review(client, key)
    response = send(client, key, snapshot)
    assert response.status_code == 403
    body = response.get_json()
    assert body['error'] == 'submission_disabled' and body['state'] == 'submission_disabled'
    assert transport['post'] == [] and transport['put'] == []
    # And it left no row that looks like an attempt: `review` prepared one,
    # `submit` did not advance it and counted no attempt against it.
    row = wishlib.latest_submission(f'sha256:{key}')
    assert row['state'] == 'prepared' and row['attempts'] == 0
    assert row['consented_at'] is None


def test_with_submission_off_review_still_shows_what_was_recorded(client, submit_off):
    key = seed()
    body = client.get(f'/api/mex/wishes/{key}/review').get_json()
    assert body['success'] and body['payload']['capability'] == 'independent_part_recolor'
    assert body['can_send'] is False and body['blocked_reason'] == 'submission_disabled'
    assert body['submission_enabled'] is False
    assert client.get('/api/mex/wishes').get_json()['submission_enabled'] is False


def test_with_submission_off_the_footer_offers_no_send_action(submit_off):
    assert wishlib.footer(recorded=True) == {'text': wishlib.FOOTER_SAVED, 'action': None}
    assert wishlib.footer(already_recorded=True)['action'] is None


def test_sent_is_a_claim_about_an_accepted_receipt(monkeypatch):
    monkeypatch.setenv('NUCLEUS_WISH_SUBMIT', '1')
    assert wishlib.footer(recorded=True, sent=True) == {'text': wishlib.FOOTER_SENT,
                                                        'action': None}


def test_submit_reports_the_gate_before_it_claims_anything(submit_off):
    """With the gate closed nothing is claimed, so no attempt is counted."""
    verdict = recolor_wish()
    wishlib.record_wish(FakeTask(), verdict)
    calls = []
    result = wishlib.submit('wsub_' + '0' * 16, approval_hash_presented='sha256:whatever',
                            consent=True,
                            create=lambda meta, headers: calls.append(meta),
                            upload=lambda report_id, blob: calls.append(report_id))
    assert result.state == 'submission_disabled' and result.sent is False
    assert calls == [] and wishlib.latest_submission(wishlib.key_for(verdict)) is None


# ------------------------------------------- storage: transactions and races
#
# Review findings 6, 7 and 13.

def test_a_wish_read_never_commits_somebody_elses_transaction():
    """Review finding 6: `connection()` ran executescript+commit on the store's
    own per-thread handle, so a plain read committed the caller's open
    transaction and a row survived a rollback."""
    wishlib.connection()                       # ensure the schema exists first
    owner = store.connect()
    owner.execute('BEGIN')
    owner.execute("INSERT INTO events (task_id,revision,kind,at,payload) VALUES (?,?,?,?,?)",
                  ('t_rollback', 1, 'task_started', time.time(), '{}'))
    wishlib.requesting_conversations('sha256:' + '0' * 64)     # a plain read
    wishlib.backlog()                                          # and a bigger one
    owner.rollback()
    left = owner.execute("SELECT COUNT(*) AS n FROM events WHERE task_id='t_rollback'"
                         ).fetchone()['n']
    assert left == 0, 'a wish read committed the owner transaction'


def test_concurrent_records_for_one_task_produce_one_observation():
    """Review finding 7: the check and the insert were separate, and an
    interleaving produced two observations and two counted conversations."""
    verdict = recolor_wish()
    start = threading.Barrier(4)
    records = []

    def worker():
        start.wait()
        try:
            records.append(wishlib.record_wish('t1', verdict, conversation_id='chat_1'))
        finally:
            wishlib.close()
            store.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(records) == 4 and all(r.recorded for r in records)
    assert len({r.wish.wish_id for r in records}) == 1
    key = wishlib.key_for(verdict)
    assert wishlib.requesting_conversations(key) == 1
    assert len(store.wishes('t1')) == 1


def test_a_failed_mirror_rolls_the_claim_and_the_count_back(monkeypatch):
    """The ledger, the counts and the trace cannot diverge.

    `monkeypatch.undo()` is deliberately NOT used to restore the mirror: it
    would also undo the `vault` fixture's STORAGE_PATH redirect and point the
    rest of the test at the real journal.
    """
    verdict = recolor_wish()
    real, failing = store.record_wish, {'yes': True}

    def flaky(wish):
        if failing['yes']:
            raise RuntimeError('disk is gone')
        return real(wish)

    monkeypatch.setattr(store, 'record_wish', flaky)
    record = wishlib.record_wish('t1', verdict, conversation_id='chat_1')
    assert record.recorded is False and 'disk is gone' in record.error
    key = wishlib.key_for(verdict)
    assert wishlib.requesting_conversations(key) == 0
    assert wishlib.backlog() == []
    assert store.wishes('t1') == []
    # And the claim is free again, so a later attempt is not told "already".
    failing['yes'] = False
    again = wishlib.record_wish('t1', verdict, conversation_id='chat_1')
    assert again.recorded and again.already_recorded is False
    assert wishlib.requesting_conversations(key) == 1


def test_a_missing_conversation_id_never_becomes_task_based_demand():
    """Review finding 7: falling back to the task id counts every TURN of one
    conversation as a separate requesting conversation."""
    verdict = recolor_wish()
    for turn in range(5):
        wishlib.record_wish(f'task_{turn}', verdict)          # no conversation id
    key = wishlib.key_for(verdict)
    assert wishlib.requesting_conversations(key) == 1
    assert wishlib.total_encounters(key) == 5
    row = wishlib.connection().execute(
        'SELECT conversation_id FROM wish_occurrences WHERE dedupe_key=?', (key,)).fetchone()
    assert row['conversation_id'] == wishlib.UNKNOWN_CONVERSATION


def test_legacy_queued_wishes_become_local_only_history(vault):
    """Review finding 13: pre-module observations stayed `queued` and vanished
    from the backlog, implying a submission nobody consented to."""
    from randall.assistant.tasks.contracts import Wish
    wishlib.close()
    store.close()
    legacy = Wish(capability='menu_output_preview', blocked_operation='render_menu_artifact',
                  dedupe_key='menu_output_preview', record_status='queued')
    store.record_wish(legacy)
    rows = wishlib.backlog()
    assert len(rows) == 1
    old = rows[0]
    assert old['legacy'] is True and old['conversations'] == 0 and old['encounters'] == 0
    assert old['submission'] is None and old['still_unsupported'] is False
    # Idempotent: a second pass adds nothing.
    wishlib.close()
    assert len(wishlib.backlog()) == 1


def test_the_migration_leaves_authoritative_keys_alone():
    wishlib.record_wish('t1', recolor_wish(), conversation_id='chat_1')
    wishlib.close()
    rows = wishlib.backlog()
    assert [r['legacy'] for r in rows] == [False]
    assert rows[0]['conversations'] == 1


# ----------------------------------------- unmet requirements vs. persistence
#
# Review finding 8: missing-capability detection read `wish_ids`, so a failed
# write -- or a facade that records its own gap without the coordinator -- lost
# the signal and a missing required operation could finish as `success`.

class FakeEnvelope:
    def __init__(self):
        self.facts = {}
        self.wish_ids = []


def test_unmet_requirements_are_read_from_the_envelope_facts():
    envelope = FakeEnvelope()
    assert wishlib.unmet_requirements(envelope) == []
    envelope.facts[wishlib.UNMET_FACT] = [{'capability': 'independent_part_recolor'}]
    assert wishlib.unmet_requirements(envelope) == [{'capability': 'independent_part_recolor'}]
    assert envelope.wish_ids == []          # storage is a separate question


