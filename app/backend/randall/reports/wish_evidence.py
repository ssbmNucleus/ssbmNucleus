"""Typed evidence and the verdict: the closed vocabulary of observations, what the user required,
and `classify_blocker`, the first-match decision of what kind of thing stopped a task."""

from dataclasses import dataclass, field

from randall.assistant import capabilities


# ---------------------------------------------------------------------------
# Typed evidence
# ---------------------------------------------------------------------------

#: The closed vocabulary of things a caller may have OBSERVED. A caller that
#: cannot name its failure in these terms has not typed it, and an untyped
#: failure must not be classified -- that is the whole point.
EVIDENCE_CODES = frozenset((
    # the user
    'user_denied', 'cancelled',
    # something is missing from the request
    'missing_input', 'ambiguous_selection', 'unresolved_identification',
    # a search ran and returned nothing
    'search_completed_no_match',
    # the shipped package is incomplete
    'missing_dependency', 'unloadable_dependency',
    # the world outside the app
    'provider_failure', 'invalid_credentials', 'missing_user_configuration',
    # a supported operation broke its own contract
    'contract_violation', 'corrupt_output', 'incorrect_measurement',
    'failed_round_trip', 'unexpected_exception', 'undispatchable_advertised_tool',
    # the model called something that does not exist, or that is switched off
    'unknown_tool', 'disabled_operation',
    # a valid check rejected THIS input or THIS candidate
    'input_rejected', 'quality_rejected',
    # the capability itself
    'operation_unavailable', 'out_of_scope_request',
))

#: Every outcome :func:`classify_blocker` can return, in decision order.
OUTCOMES = ('denial', 'cancelled', 'needs_decision', 'no_match', 'packaging_defect',
            'outage', 'needs_setup', 'bug', 'blocked_input', 'quality_blocked',
            'wish', 'outside_scope', 'not_a_blocker', 'unclassified_failure')

#: The one outcome that creates a wish. Kept as a constant so a future branch
#: cannot quietly add a second path into the backlog.
WISH = 'wish'


@dataclass(frozen=True)
class Observation:
    """What actually happened, in typed terms.

    `facts` is for BOOLEANS AND NUMBERS a domain operation measured (e.g.
    ``{'separable_by_mask': False, 'mask_available': False}`` straight out of
    `part_identity._required_mask`). It is never prose and never chat text; the
    public projection drops it entirely.
    """
    evidence: str
    operation: str = ''
    variant: str = ''
    #: For `provider_failure` only: was the failure transient? `None` means
    #: nobody established it, and an unestablished transience is not an outage.
    transient: object = None
    #: Typed evidence codes, never paths or filenames. `record` refuses ids that
    #: are not in EVIDENCE_CODES, so a workspace path cannot ride along.
    evidence_codes: tuple = ()
    facts: dict = field(default_factory=dict)

    def validate(self):
        if self.evidence not in EVIDENCE_CODES:
            raise ValueError(f'{self.evidence!r} is not a typed evidence code; '
                             'classify nothing rather than guess from a message')
        return self


@dataclass(frozen=True)
class Requirement:
    """What the USER was trying to get, and whether this operation was needed.

    `required_for_outcome` is the field that stops manufactured demand. Merely
    encountering "no menu renderer" while preparing a build leaves it False, and
    a preparation that never needed to install leaves it False for the build
    commit gap too. It is set True only at a workflow checkpoint where the
    operation is genuinely required for what the user asked for.
    """
    operation: str = ''
    required_for_outcome: bool = False
    requested_outcome: str = ''
    workflow: str = ''
    #: 'melee' (inside the product's domain) or 'outside'.
    domain: str = 'melee'
    variant: str = ''


@dataclass(frozen=True)
class Classification:
    """The verdict. `creates_wish` is true for exactly one outcome."""
    outcome: str
    reason: str                       # a typed reason code, never a sentence
    creates_wish: bool = False
    capability: str = ''
    blocked_operation: str = ''
    implementation_version: str = ''
    variant: str = ''
    evidence: str = ''
    #: 'bounded_tool_repair' when the loop should retry once with the real
    #: operations. Empty otherwise.
    repair: str = ''

    def to_dict(self):
        return {'outcome': self.outcome, 'reason': self.reason, 'creates_wish': self.creates_wish,
                'capability': self.capability, 'blocked_operation': self.blocked_operation,
                'implementation_version': self.implementation_version, 'variant': self.variant,
                'evidence': self.evidence, 'repair': self.repair}


def _verdict(outcome, reason, observation, **extra):
    return Classification(outcome=outcome, reason=reason, evidence=observation.evidence, **extra)


def classify_blocker(observation, requirement=None, capability_definition=None):
    """First-match decision function: what KIND of thing just stopped the task.

    Args:
        observation: an :class:`Observation`. Typed; required.
        requirement: a :class:`Requirement` describing what the user was after
            and whether this operation was required for it. Defaults to a
            requirement that needs nothing, which can never produce a wish.
        capability_definition: an `assistant.capabilities.Capability`, or None
            to look one up by the observation's operation. Passing it explicitly
            is how a caller pins the definition it actually consulted.

    Returns:
        Classification. `creates_wish` is True only for `wish`.

    The order below is the design's, and it is a first match: a cancellation
    during a capability gap is a cancellation, and an outage while a required
    operation is missing is an outage. Ranking the user and the environment
    above the backlog is what keeps the backlog meaningful.
    """
    observation = observation.validate()
    requirement = requirement or Requirement()
    evidence = observation.evidence

    # 1. The user. Neither creates a wish; a refusal is not demand.
    if evidence == 'user_denied':
        return _verdict('denial', 'user_rejected_the_operation', observation)
    if evidence == 'cancelled':
        return _verdict('cancelled', 'task_cancelled', observation)

    # 2. The request is incomplete or ambiguous: ask, do not file.
    if evidence in ('missing_input', 'ambiguous_selection', 'unresolved_identification'):
        return _verdict('needs_decision', evidence, observation)

    # 3. A search that RAN and found nothing is a fact about the corpus.
    if evidence == 'search_completed_no_match':
        return _verdict('no_match', 'search_returned_no_qualifying_result', observation)

    # 4. The shipped implementation's own dependency is absent: that is a
    #    packaging defect, not a capability the product lacks.
    if evidence in ('missing_dependency', 'unloadable_dependency'):
        return _verdict('packaging_defect', evidence, observation)

    # 5. The world outside the app.
    if evidence == 'provider_failure':
        if observation.transient is True:
            return _verdict('outage', 'transient_provider_failure', observation)
        # Nobody established transience, so nobody may call it an outage.
        return _verdict('unclassified_failure', 'provider_failure_transience_unknown', observation)
    if evidence in ('invalid_credentials', 'missing_user_configuration', 'disabled_operation'):
        return _verdict('needs_setup', evidence, observation)

    # 6. A supported operation violated its contract. An operation that was
    #    ADVERTISED this turn but could not dispatch is an integration bug --
    #    the model did nothing wrong and the product is not missing a feature.
    if evidence in ('contract_violation', 'corrupt_output', 'incorrect_measurement',
                    'failed_round_trip', 'unexpected_exception', 'undispatchable_advertised_tool'):
        return _verdict('bug', evidence, observation)

    # 7. A valid check rejected THIS input or THIS candidate. An invented tool
    #    name is an invalid call of exactly this kind: give the loop one bounded
    #    repair against the real operations and claim nothing.
    if evidence == 'unknown_tool':
        return _verdict('blocked_input', 'model_called_an_unknown_tool', observation,
                        repair='bounded_tool_repair')
    if evidence == 'input_rejected':
        return _verdict('blocked_input', 'input_rejected_by_a_valid_check', observation)
    if evidence == 'quality_rejected':
        return _verdict('quality_blocked', 'candidate_rejected_by_a_valid_check', observation)

    # 8. The capability itself. Three independent typed facts, all required.
    if evidence in ('operation_unavailable', 'out_of_scope_request'):
        operation = observation.operation or requirement.operation
        definition = capability_definition or capabilities.by_operation(operation)
        if definition is None:
            # Nothing trusted says this operation is missing. Preserve the
            # diagnostics; an unknown proposal goes to the manual form.
            return _verdict('unclassified_failure', 'no_capability_definition', observation)
        if definition.domain == 'outside' or definition.status == 'outside_scope':
            return _verdict('outside_scope', 'request_outside_the_products_domain', observation,
                            capability=definition.name, blocked_operation=definition.operation,
                            implementation_version=definition.implementation_version)
        if requirement.domain == 'outside':
            return _verdict('outside_scope', 'request_outside_the_products_domain', observation,
                            capability=definition.name, blocked_operation=definition.operation,
                            implementation_version=definition.implementation_version)
        # SCOPE decides, not the operation as a whole. `builds.commit_change`
        # works -- for a Nucleus project -- and is missing only for the other
        # build formats, so asking "is this operation supported?" without the
        # format is the wrong question and answering it globally made Randall
        # claim it could not install anything.
        scope = observation.variant or requirement.variant
        status = definition.status_for(scope)
        if status == 'supported':
            # Declared present for THIS input but it did not run: that is a
            # defect in the implementation, not an absent feature.
            return _verdict('bug', 'declared_supported_operation_did_not_run', observation,
                            capability=definition.name, blocked_operation=definition.operation,
                            implementation_version=definition.implementation_version)
        if status != 'unsupported':
            # An input nobody declared. Rounding it to the nearest known case
            # would file a gap that was never demonstrated.
            return _verdict('unclassified_failure', 'capability_status_unknown', observation,
                            capability=definition.name, blocked_operation=definition.operation)
        if observation.evidence not in (definition.evidence_codes or ('operation_unavailable',)):
            return _verdict('unclassified_failure', 'evidence_does_not_belong_to_capability',
                            observation, capability=definition.name,
                            blocked_operation=definition.operation)
        if not requirement.required_for_outcome:
            # Encountering an unavailable operation nobody needed is not a
            # blocker and must not manufacture demand.
            return _verdict('not_a_blocker', 'operation_not_required_for_the_outcome', observation,
                            capability=definition.name, blocked_operation=definition.operation,
                            implementation_version=definition.implementation_version)
        variant = definition.variant_or_refuse(scope)
        return _verdict(WISH, 'confirmed_unsupported_required_operation', observation,
                        creates_wish=True, capability=definition.name,
                        blocked_operation=definition.operation,
                        implementation_version=definition.implementation_version,
                        variant=variant)

    return _verdict('unclassified_failure', 'unrecognised_evidence', observation)


