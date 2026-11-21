"""The shared vocabulary of a Randall task: its result envelope, the shape a
check returns, the wish a capability gap becomes, and the two span records the
tracer writes.

Design source: artifacts/harness-experiment-20260922/ASTRA-CONSULT-2.md
(sections 2, 3 and 7). Every field list here is the spec's, kept verbatim so a
grader reading the trace and a reader reading the spec see the same names.

Nothing in this module touches SQLite, the network or the engine: it is types
and validation only, so `store` and `coordinator` can be swapped or tested
without it, and so a workflow can build an envelope with no task running.

Two rules are load-bearing and are enforced here rather than by convention:

* **Execution state is not outcome.** `state` says where the task is; `outcome`
  says what the user got. A task that is still `running` has no outcome, and a
  terminal state must have one. Nothing may report `completed` with a null
  outcome, which is how "it finished" quietly becomes "it worked".
* **A missing cost is `unknown`, never zero.** `UNKNOWN` is a distinct sentinel
  and `CostRoll` keeps it apart rather than adding it away. An unreported charge is an accounting
  hole to be reconciled later, and zero is a lie that balances.
"""
import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass, field, asdict, fields

CONTRACTS_VERSION = 1

# ---------------------------------------------------------------- enumerations

# Where the task is. Separate from what it achieved (see OUTCOMES).
STATES = frozenset(('running', 'waiting_decision', 'waiting_approval',
                    'completed', 'failed', 'cancelled'))
# A state that ends the task and therefore requires an outcome.
TERMINAL_STATES = frozenset(('completed', 'failed', 'cancelled'))
OUTCOMES = frozenset(('success', 'partial', 'blocked', 'denied', 'failed', 'cancelled'))
# The four postconditions a grader compares against the request. Definitions
# (spec section 2): prepared = staged bytes passed the applicable preparation
# checks; exported = sealed bytes promoted to the approved export destination;
# installed = the intended playable build was changed AND verified; previewed =
# an image was generated from the produced artifact -- an author's screenshot
# of their own mod never qualifies.
POSTCONDITIONS = ('prepared', 'exported', 'installed', 'previewed')

CHECK_STATUSES = frozenset(('pass', 'warn', 'fail', 'unknown', 'not_applicable'))
# A required check that could not run is `unknown`. Only trusted code may
# declare `not_applicable`, and only with a reason the policy defines.
UNKNOWN_IS_NOT_PASS = frozenset(('fail', 'unknown'))

# What `next` can be. A decision is Randall's or the user's choice between
# bounded alternatives; an approval is authorization for a sealed operation and
# can only ever be granted by the user-facing approval endpoint.
NEXT_KINDS = frozenset(('decision', 'approval'))

# `unresolved` is what an attempt becomes when the process died while it was in
# flight: it was dispatched, it may have billed, and nobody saw how it ended.
# It is not an error and it is certainly not a success -- it is an open charge.
SPAN_STATUSES = frozenset(('running', 'ok', 'error', 'cancelled', 'timeout', 'refused', 'unresolved'))

# How a side effect stands in the journal. `unresolved` survives restarts until
# something explicitly reconciles it against the destination.
JOURNAL_STATUSES = frozenset(('started', 'completed', 'failed', 'cancelled', 'unresolved', 'reconciled'))
OPEN_JOURNAL_STATUSES = frozenset(('started', 'unresolved'))

# How a failed model request was classified, which decides whether it may be
# retried. Only `transient` may be.
RETRY_CLASSES = frozenset(('transient', 'permanent', 'cancelled', 'invalid_response', 'none'))

# Cost accounting. `reported` is the provider's own number; `estimated` is ours
# and is never mixed into a reported total; `unknown` means the provider told us
# nothing and the charge is still outstanding.
COST_STATUSES = frozenset(('reported', 'reconciled', 'estimated', 'unknown', 'free'))


class _Unknown:
    """A cost the provider did not report.

    Deliberately not 0, not None and not float('nan'): it compares equal only to
    itself, refuses arithmetic, and serialises to the string "unknown" so a
    JSONL trace and a SQLite row both carry the hole forward instead of closing
    it.
    """
    __slots__ = ()

    def __repr__(self):
        return 'UNKNOWN'

    def __bool__(self):
        return False

    def __eq__(self, other):
        return other is self or other == 'unknown'

    def __hash__(self):
        return hash('unknown')

    def __add__(self, other):
        raise TypeError('an unknown cost cannot be summed; reconcile it first')

    __radd__ = __add__


UNKNOWN = _Unknown()


def money(value):
    """A provider-reported USD amount, or UNKNOWN.

    Anything non-finite, negative or non-numeric is a missing number, not zero.
    A real reported 0.0 (a free model) stays 0.0 -- that is a measurement.
    """
    if isinstance(value, _Unknown) or value is None:
        return UNKNOWN
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return UNKNOWN
    return float(value)


# What one unreported model charge is assumed to have cost, for the purpose of
# staying under a budget. It is a RESERVATION, never a measurement: it is only
# ever compared against the limit, never reported as spend, and it never appears
# in `total_usd`.
#
# The number is the measured per-request cost of the experiment's own runs, not
# a guess: GLM flash billed $0.073 over 33 requests in T1 (~$0.0022) and $0.306
# over 87 in T4 (~$0.0035). Reserving $0.003 keeps a silent provider honestly
# bounded while leaving the round budgets -- which are tighter at this rate --
# the ones that normally bind.
UNKNOWN_CHARGE_RESERVE_USD = 0.003


@dataclass
class CostRoll:
    """Charges across a task: what was reported, what is reserved, what is missing.

    The spec asks for "cost-accounting coverage and unresolved charges" as
    reported numbers, so the three are tracked separately rather than folded
    into one figure that hides the gap. Two different questions get two
    different answers, and conflating them is how a spending limit silently
    stops limiting:

    * **What did this cost?** `total_usd`. UNKNOWN while any charge is open,
      because the honest answer to "how much did we spend" is not a number we
      can defend when a provider never told us.
    * **How much of the budget is gone?** `committed_usd` = reported + still
      reserved. An unreported charge counts against the limit as PENDING. The
      engine's old accumulator dropped an absent cost, so a provider that
      stopped reporting costs made every spending guard free.
    """
    reported_usd: float = 0.0
    reported_requests: int = 0
    unknown_requests: int = 0
    pending_usd: float = 0.0          # reserved for charges that never arrived
    open_usd: float = 0.0             # reserved for requests still in flight
    # Spend carried in from an earlier task for the same unresolved objective,
    # so a fresh "continue" cannot hand the user a fresh allowance.
    carried_usd: float = 0.0

    def reserve(self, amount=UNKNOWN_CHARGE_RESERVE_USD):
        """Hold budget for a dispatch that has not reported yet."""
        amount = max(0.0, float(amount or 0.0))
        self.open_usd = round(self.open_usd + amount, 8)
        return amount

    def release(self, reserved, reported):
        """Settle one dispatch: drop its reservation, book what it really cost.

        A charge the provider never reported keeps its reservation as `pending`.
        Dropping it would mean an unreported charge costs the budget nothing,
        which is exactly the hole the reviewer found.
        """
        reserved = max(0.0, float(reserved or 0.0))
        self.open_usd = round(max(0.0, self.open_usd - reserved), 8)
        amount = money(reported)
        if isinstance(amount, _Unknown):
            self.unknown_requests += 1
            self.pending_usd = round(self.pending_usd + reserved, 8)
        else:
            self.reported_usd = round(self.reported_usd + amount, 8)
            self.reported_requests += 1
        return self

    def charge(self, amount):
        """Book a charge with no prior reservation (an untracked call site)."""
        return self.release(0.0, amount)

    @property
    def coverage(self):
        """Fraction of requests whose charge the provider actually reported."""
        total = self.reported_requests + self.unknown_requests
        return 1.0 if not total else round(self.reported_requests / total, 6)

    @property
    def total_usd(self):
        """The honest total: UNKNOWN while any charge is unresolved."""
        known = round(self.reported_usd + self.carried_usd, 8)
        return known if not self.unknown_requests else UNKNOWN

    @property
    def committed_usd(self):
        """What a budget check must read: reported + carried + still-open money."""
        return round(self.reported_usd + self.carried_usd + self.pending_usd + self.open_usd, 8)

    def to_dict(self):
        return {'reported_usd': self.reported_usd, 'reported_requests': self.reported_requests,
                'unknown_requests': self.unknown_requests, 'pending_usd': self.pending_usd,
                'open_usd': self.open_usd, 'carried_usd': self.carried_usd,
                'committed_usd': self.committed_usd, 'coverage': self.coverage,
                'total_usd': _plain(self.total_usd)}


def _plain(value):
    """JSON-safe rendering that keeps UNKNOWN visible as itself."""
    if isinstance(value, _Unknown):
        return 'unknown'
    return value


def new_id(prefix):
    return f'{prefix}_{uuid.uuid4().hex[:16]}'


def digest(data):
    """A content hash for an artifact, an image or a normalised parameter set.

    Hashes, not contents: the spec keeps full prompt/content logging opt-in, and
    a hash plus a template version is enough for ordinary telemetry.
    """
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    elif isinstance(data, str):
        raw = data.encode('utf-8', 'surrogatepass')
    else:
        raw = json.dumps(data, sort_keys=True, default=str).encode()
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------- envelope

@dataclass
class NextRequest:
    """The typed decision or approval a task is waiting on.

    Bound to `task_revision`: a user revision invalidates it (see
    `coordinator.revise`), which is what stops an approval granted for one
    candidate from authorizing a different one.
    """
    id: str = field(default_factory=lambda: new_id('next'))
    kind: str = 'decision'                    # decision | approval
    task_revision: int = 1
    prompt: str = ''                          # the descriptive sentence that may accompany it
    allowed_responses: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    schema: dict = field(default_factory=dict)
    # Approvals only: the sealed operation this authorizes. An approval that
    # does not name its subject cannot be revalidated against it later.
    operation_id: str = ''
    operation_digest: str = ''
    status: str = 'pending'                   # pending | answered | invalidated | cancelled
    created_at: float = field(default_factory=time.time)

    def validate(self):
        if self.kind not in NEXT_KINDS:
            raise ValueError(f'next.kind must be one of {sorted(NEXT_KINDS)}')
        if not self.id:
            raise ValueError('next.id is required')
        if not isinstance(self.allowed_responses, list) or not self.allowed_responses:
            raise ValueError('next must state the allowed responses')
        if self.kind == 'approval' and not self.operation_digest:
            raise ValueError('an approval request must name the sealed operation it authorizes')
        return self

    def to_dict(self):
        return asdict(self)


@dataclass
class CheckResult:
    """One measurement, in the spec's exact field list.

    `status` is the measurement's own verdict. A model's opinion about an image
    is a visual assessment and is NOT a check -- it never arrives here.
    """
    check_id: str = ''
    implementation_version: str = ''
    status: str = 'unknown'
    measured_values: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    affected_parts: list = field(default_factory=list)
    pose_ids: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    # Why a trusted implementation declared this inapplicable, or why it could
    # not be measured. Required for not_applicable; policy-defined.
    reason: str = ''
    required: bool = True

    def validate(self):
        if not self.check_id:
            raise ValueError('check_id is required')
        if self.status not in CHECK_STATUSES:
            raise ValueError(f'check status must be one of {sorted(CHECK_STATUSES)}')
        if not self.implementation_version:
            raise ValueError(f'check {self.check_id} must state its implementation_version')
        if self.status == 'not_applicable' and not self.reason:
            raise ValueError('not_applicable requires a policy-defined reason')
        return self

    @property
    def blocks_release(self):
        """A required check that failed or could not be measured blocks release.

        `unknown` is not `pass`: a measurement that failed to run is missing
        evidence, and missing evidence is the exact failure mode the report's
        false success came from.
        """
        return self.required and self.status in UNKNOWN_IS_NOT_PASS

    def to_dict(self):
        return asdict(self)


@dataclass
class Wish:
    """A structured capability gap (spec section 7).

    A wish is an observed missing OPERATION needed for the user's request -- not
    a synonym for every failure. A provider outage is a transient failure, a
    missing bundled dependency is a packaging defect, a broken export is a bug,
    and a user saying no is a denial. Filing one of those as a wish is how a
    real gap gets buried in noise.
    """
    wish_id: str = field(default_factory=lambda: new_id('wish'))
    kind: str = 'capability_gap'
    capability: str = ''
    task_id: str = ''
    task_revision: int = 1
    workflow: str = ''
    requested_outcome: str = ''
    blocked_operation: str = ''
    available_alternative: str = ''
    evidence_ids: list = field(default_factory=list)
    app_version: str = ''
    api_version: str = ''
    dedupe_key: str = ''
    record_status: str = 'queued'             # queued | submitted | declined | duplicate

    def __post_init__(self):
        if not self.dedupe_key:
            # Deduplicated by capability and the implementation version that
            # lacks it, so demand can be counted without repeat tickets.
            self.dedupe_key = digest([self.kind, self.capability, self.blocked_operation, self.app_version])

    def validate(self):
        if not self.capability:
            raise ValueError('a wish must name the missing capability')
        if not self.blocked_operation:
            raise ValueError('a wish must name the operation it blocked')
        return self

    def to_dict(self):
        return asdict(self)


@dataclass
class TaskResult:
    """The shared result envelope, field-for-field from spec section 2."""
    task_id: str = field(default_factory=lambda: new_id('task'))
    revision: int = 1
    workflow: str = ''
    workflow_version: int = 1
    state: str = 'running'
    outcome: str = None
    achieved: dict = field(default_factory=lambda: dict.fromkeys(POSTCONDITIONS, False))
    facts: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    next: object = None                       # NextRequest | None
    receipts: list = field(default_factory=list)
    error: object = None
    wish_ids: list = field(default_factory=list)

    def validate(self):
        """Refuse an envelope that could be read as a success it did not earn."""
        if self.state not in STATES:
            raise ValueError(f'state must be one of {sorted(STATES)}')
        if self.outcome is not None and self.outcome not in OUTCOMES:
            raise ValueError(f'outcome must be one of {sorted(OUTCOMES)}')
        if self.state in TERMINAL_STATES and self.outcome is None:
            raise ValueError(f'a {self.state} task must state its outcome')
        if self.state not in TERMINAL_STATES and self.outcome is not None:
            raise ValueError('a task still in flight has no outcome yet')
        if set(self.achieved) != set(POSTCONDITIONS):
            raise ValueError(f'achieved must carry exactly {list(POSTCONDITIONS)}')
        if any(not isinstance(v, bool) for v in self.achieved.values()):
            raise ValueError('achieved values are booleans, not counts or prose')
        # "Installed" means the playable build changed AND was verified, so it
        # cannot be claimed by a task that never prepared anything.
        if self.achieved['installed'] and not self.achieved['prepared']:
            raise ValueError('installed cannot be true without prepared')
        if self.state in ('waiting_decision', 'waiting_approval') and self.next is None:
            raise ValueError(f'{self.state} requires a typed next request')
        if self.next is not None:
            want = 'approval' if self.state == 'waiting_approval' else 'decision'
            nxt = self.next if isinstance(self.next, NextRequest) else NextRequest(**self.next)
            nxt.validate()
            if self.state in ('waiting_decision', 'waiting_approval') and nxt.kind != want:
                raise ValueError(f'{self.state} requires a {want} request, not a {nxt.kind}')
            if nxt.task_revision != self.revision:
                raise ValueError('a pending request from an earlier revision is stale')
        for check in self.checks:
            (check if isinstance(check, CheckResult) else CheckResult(**check)).validate()
        # A blocked measurement cannot coexist with an unqualified success.
        if self.outcome == 'success' and any(self._as_check(c).blocks_release for c in self.checks):
            raise ValueError('a required check that failed or is unknown cannot report success')
        if self.state == 'failed' and self.error is None:
            raise ValueError('a failed task must carry its error')
        return self

    @staticmethod
    def _as_check(check):
        return check if isinstance(check, CheckResult) else CheckResult(**check)

    @property
    def blocking_checks(self):
        return [self._as_check(c) for c in self.checks if self._as_check(c).blocks_release]

    def to_dict(self):
        data = asdict(self) if not isinstance(self.next, NextRequest) else {
            **{f.name: getattr(self, f.name) for f in fields(self) if f.name != 'next'},
            'next': self.next.to_dict()}
        data['checks'] = [c.to_dict() if isinstance(c, CheckResult) else c for c in self.checks]
        data['contracts_version'] = CONTRACTS_VERSION
        return json.loads(json.dumps(data, default=_plain))

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data.pop('contracts_version', None)
        known = {f.name for f in fields(cls)}
        result = cls(**{k: v for k, v in data.items() if k in known})
        if isinstance(result.next, dict):
            result.next = NextRequest(**result.next)
        result.checks = [CheckResult(**c) if isinstance(c, dict) else c for c in result.checks]
        return result


# ----------------------------------------------------------------- span shapes

@dataclass
class Span:
    """The fields every span carries, whatever it measures (spec section 3).

    Wall time is recorded twice on purpose: `start_utc` places the span on a
    human timeline, `monotonic_start`/`duration_ms` measure it. Clock changes
    during a 25-minute import must not produce a negative duration.
    """
    span_id: str = field(default_factory=lambda: new_id('span'))
    task_id: str = ''
    task_revision: int = 1
    parent_span_id: str = ''
    operation_id: str = ''
    attempt: int = 1
    component_version: str = ''
    start_utc: float = field(default_factory=time.time)
    monotonic_start: float = field(default_factory=time.monotonic)
    duration_ms: float = None
    status: str = 'running'

    def finish(self, status='ok'):
        if status not in SPAN_STATUSES:
            raise ValueError(f'span status must be one of {sorted(SPAN_STATUSES)}')
        self.duration_ms = round((time.monotonic() - self.monotonic_start) * 1000, 3)
        self.status = status
        return self

    def to_dict(self):
        return json.loads(json.dumps(asdict(self), default=_plain))


@dataclass
class ModelSpan(Span):
    """One model REQUEST -- not one logical decision.

    A logical decision that took three attempts is one `decision_id` and three
    spans with `attempt` 1..3. The report needs both numbers ("logical model
    decisions and actual requests, including retries"), and collapsing them is
    exactly how a retried charge gets counted once or not at all.

    Field list is the spec's, in its order.
    """
    kind: str = 'model'
    # -- logical identity
    decision_id: str = ''
    role: str = ''                            # main | jev | fast_lane | vision | image | piece_judge
    task_family: str = ''
    dependency_ids: list = field(default_factory=list)
    # -- resolution
    requested_model: str = ''
    resolved_model: str = ''
    resolved_provider: str = ''
    configuration_version: str = ''
    prompt_template_version: str = ''
    # -- provider identity
    provider_request_id: str = ''
    provider_generation_id: str = ''
    # -- timing (seconds since the span's monotonic_start, or None if never reached)
    queue_ms: float = None
    dispatch_ms: float = None
    first_token_ms: float = None
    completion_ms: float = None
    timeout_s: float = None
    retry_delay_ms: float = None
    # -- tokens; cache and reasoning kept as their own provider fields, never
    #    folded into prompt/completion totals.
    input_tokens: int = None
    output_tokens: int = None
    cached_input_tokens: int = None
    reasoning_tokens: int = None
    # -- money. reserved = what we set aside, reported = the provider's own
    #    number, reconciled = what a later generation lookup confirmed.
    reserved_cost_usd: object = UNKNOWN
    reported_cost_usd: object = UNKNOWN
    reconciled_cost_usd: object = UNKNOWN
    cost_status: str = 'unknown'
    # -- how it ended
    finish_reason: str = ''
    http_status: int = None
    provider_error: str = ''
    retry_classification: str = 'none'
    # -- inputs actually sent
    input_artifact_hashes: list = field(default_factory=list)
    attached_image_hashes: list = field(default_factory=list)
    # -- contract checks around the call
    tool_schema_version: str = ''
    response_validation: str = ''             # valid | invalid_* | not_checked
    cancelled_after_ms: float = None
    # The policy this call site applies, not the outcome of applying it.
    retry_policy: str = 'bounded_transient'
    max_attempts: int = None

    def record_cost(self, reported, *, reserved=None, reconciled=None):
        """Attach the provider's charge, keeping a missing one visible."""
        self.reported_cost_usd = money(reported)
        if reserved is not None:
            self.reserved_cost_usd = money(reserved)
        if reconciled is not None:
            self.reconciled_cost_usd = money(reconciled)
        if not isinstance(self.reconciled_cost_usd, _Unknown):
            self.cost_status = 'reconciled'
        elif isinstance(self.reported_cost_usd, _Unknown):
            self.cost_status = 'unknown'
        elif self.reported_cost_usd == 0.0:
            self.cost_status = 'free'
        else:
            self.cost_status = 'reported'
        return self

    def record_usage(self, usage):
        """Read OpenRouter's usage block without inventing anything it omitted.

        https://openrouter.ai/docs/cookbook/administration/usage-accounting
        """
        if not isinstance(usage, dict):
            return self
        details = usage.get('prompt_tokens_details') or {}
        completion_details = usage.get('completion_tokens_details') or {}
        for attribute, value in (
                ('input_tokens', usage.get('prompt_tokens')),
                ('output_tokens', usage.get('completion_tokens')),
                ('cached_input_tokens', details.get('cached_tokens')),
                ('reasoning_tokens', completion_details.get('reasoning_tokens'))):
            if type(value) is int and value >= 0:
                setattr(self, attribute, value)
        if 'cost' in usage:
            self.record_cost(usage.get('cost'))
        return self


@dataclass
class StageSpan(Span):
    """One local pipeline stage (spec section 3, second field list).

    Waiting is separated from working: user waiting, approval waiting, Dolphin
    lock waiting, model service time and local processing are different lines in
    the report and overlapping spans cannot simply be summed to explain wall
    time.
    """
    kind: str = 'stage'
    stage_name: str = ''
    stage_version: str = ''
    parameter_hash: str = ''
    input_artifact_hashes: list = field(default_factory=list)
    output_artifact_hashes: list = field(default_factory=list)
    queued_at: float = None
    lock_wait_ms: float = None
    running_at: float = None
    completed_at: float = None
    cache_hit: bool = None
    reused_operation_id: str = ''
    worker_identity: str = ''
    worker_exit_status: object = None
    cpu_time_ms: float = None
    peak_memory_bytes: int = None
    check_results: list = field(default_factory=list)
    error_type: str = ''
    error_detail: str = ''
    cancellation_acknowledged: bool = None
    cleanup_result: str = ''
    child_span_ids: list = field(default_factory=list)

    def to_dict(self):
        data = super().to_dict()
        data['check_results'] = [c.to_dict() if isinstance(c, CheckResult) else c for c in self.check_results]
        return data


# What a wait was spent on, so the report can separate them (spec section 3).
WAIT_KINDS = frozenset(('user', 'approval', 'dolphin', 'model', 'local', 'lock'))
