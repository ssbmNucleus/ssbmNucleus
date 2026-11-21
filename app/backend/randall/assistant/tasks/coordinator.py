"""Task lifecycle and the span helpers that instrument the real critical path.

The coordinator is a backend service that outlives one model turn (spec section
4). A Randall request attaches to a task context; stages and model requests open
spans under it; a user revision bumps the revision, invalidates pending
approvals and stops obsolete work at the next boundary; Stop lands at a safe
boundary; a restart resumes from recorded stages rather than replaying a commit.

Where the line between "diagnostic" and "authoritative" falls, because the first
version of this module put it in the wrong place:

* **Authoritative state raises.** Task state, revisions, approval settlement and
  the side-effect journal are correctness. If one of them cannot be written, the
  operation fails; it does not proceed with a stale or invented answer. A
  swallowed validation error is how `finish('success')` once published a success
  event for a task SQLite still called `running`.
* **Diagnostics are best-effort.** A span row, an event, a cost annotation. Only
  these go through `_guard`. Losing a trace must not lose the user's work.

Three properties this module exists to guarantee, each of which the measured
experiment lost at least once:

1. **Every model request is recorded, including the ones that failed** -- and the
   row is written BEFORE dispatch, so a crash mid-request leaves an `unresolved`
   attempt rather than no attempt at all.
2. **A retry re-sends the request, never a completed side effect.** One logical
   decision keeps one `decision_id` across its attempts. Tool execution is
   journalled by operation id, so a repeated model answer cannot download twice.
3. **Waiting is measured apart from working**, by what was waited on.
"""

import contextlib
import contextvars
import copy
import json
import logging
import random
import threading
import time

from . import contracts, events, store
from .contracts import ModelSpan, NextRequest, StageSpan, TaskResult, UNKNOWN, new_id

# `canonical_hash` is re-exported: the AI engine records spans through `coordinator` alone.
from .content_hash import canonical_hash, _image_hashes, _message_content_hash, schema_hash


logger = logging.getLogger(__name__)

COORDINATOR_VERSION = '2'
# At most two retries on a transient provider failure (spec section 3), so at
# most three attempts for one logical request. This is a CLAMP, not a default: a
# caller asking for five gets three.
MAX_ATTEMPTS = 3
# One extra attempt is allowed to repair a response that arrived but did not
# validate. It is counted separately from transient retries so "the provider was
# down" and "the model answered badly" never share a budget -- and it is a CLAMP
# as well as a default: `repairs=10` used to buy eleven dispatches, and a repair
# used to consume the transient counter, so `invalid -> transient -> transient`
# gave up before the attempt that would have succeeded.
MAX_REPAIR_ATTEMPTS = 1
BASE_BACKOFF_S = 0.5
MAX_BACKOFF_S = 8.0
# Retryable HTTP: rate limit, and the provider-side 5xx family OpenRouter
# returns as `provider_unavailable`. 400/401/403/404 are our fault or our key's
# and will fail identically forever.
TRANSIENT_HTTP = frozenset((408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524))
# The default ceiling on one task's model requests and spend. A workflow may
# lower it; nothing raises it implicitly.
DEFAULT_CALL_BUDGET = 400
DEFAULT_COST_BUDGET_USD = 1.00
# What one dispatch of each role is assumed to cost while its real charge is
# unknown. A chat round and an image generation differ by more than an order of
# magnitude, and reserving a chat round for an image admitted a $0.12 request
# under a $0.01 budget. These are RESERVATIONS, so the limit they enforce is
# approximate: the budget bounds what is COMMITTED before a dispatch, not what
# a provider ultimately charges for it.
ROLE_RESERVE_USD = {'jev': 0.0005, 'fast_lane': 0.0005, 'main': 0.003,
                    'vision': 0.005, 'image': 0.05}

# The task whose spans the current call stack belongs to. A contextvar rather
# than an argument so `decisions`, `fast_lane` and `image_api` can be
# instrumented without changing their signatures or their callers.
CURRENT = contextvars.ContextVar('randall_task', default=None)
# Span ancestry is context-local, NOT task-local. Two threads working on the
# same task each have their own stack; sharing one produced spans nested under
# whichever unrelated request happened to be open in the other thread.
_ANCESTRY = contextvars.ContextVar('randall_span_stack', default=())
# The revision the CURRENT unit of work was started for. Boundaries default to
# this rather than to the context's live revision, so work begun under revision
# 1 is still recognised as obsolete at its next checkpoint after the user
# revised -- taking the live value made every boundary trivially satisfied.
_WORK_REVISION = contextvars.ContextVar('randall_work_revision', default=None)


class TaskCancelled(Exception):
    """Raised at a safe boundary once the user asked the task to stop."""


class RevisionSuperseded(Exception):
    """Raised at a safe boundary when the work belongs to an older revision."""

    def __init__(self, expected, current):
        super().__init__(f'this work was started for revision {expected}; the task is now at {current}')
        self.expected, self.current = expected, current


class BudgetExceeded(RuntimeError):
    """The task has spent its allowance of model requests or money.

    `kind` says which: 'spending' (money), 'requests' (the call budget) or 'images'
    (`ImageAllowanceReached`). The refused dispatch was never sent, so it cost nothing.
    The message is plain (users never see dollar amounts); `diagnostic` carries the
    figures for the log and "Report this chat".
    """

    def __init__(self, message, *, kind='spending', diagnostic=None):
        super().__init__(message)
        self.kind = kind
        self.diagnostic = diagnostic


class ImageAllowanceReached(BudgetExceeded):
    """This turn has generated every image its own allowance holds (`TaskContext.allow_images`)."""

    def __init__(self, allowance):
        super().__init__(f'This turn already generated its {allowance} allowed images.', kind='images')
        self.allowance = allowance


class TaskFinished(RuntimeError):
    """An attempt to change a task that has already reached a terminal state."""


class DispatchNotRecorded(RuntimeError):
    """The attempt row could not be written, so the request was not sent."""


class TransientProviderError(RuntimeError):
    """A provider failure worth retrying: the request never produced an answer."""

    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


def _detail(exc, limit):
    """An exception as the trace records it. One whose message is the user's plain sentence carries the
    technical one as `diagnostic` (ProviderHTTPError, BudgetExceeded, image_api.ImageUnavailable)."""
    return f'{type(exc).__name__}: {str(getattr(exc, "diagnostic", None) or exc)[:limit]}'


class ProviderHTTPError(RuntimeError):
    """A non-200 from the provider, carrying the status so it can be classified.

    The production adapter used to collapse every HTTP failure into a plain
    `RuntimeError`, which made a 502 indistinguishable from a bad key -- so the
    retry logic correctly refused to retry it, and the acceptance test only
    passed because its stand-in raised something else. Subclassing RuntimeError
    keeps the engine's existing user-facing error handling unchanged. The message
    is what the user reads; `diagnostic` (the provider's status) is what the span
    records, when given.
    """

    def __init__(self, message, *, http_status=None, provider_code='', diagnostic=None):
        super().__init__(message)
        self.http_status = http_status
        self.provider_code = provider_code
        self.diagnostic = diagnostic


class InvalidResponse(ValueError):
    """A response that arrived and did not validate: repairable, not transient."""


def classify(exc, *, http_status=None):
    """`transient | permanent | cancelled | invalid_response` for one failure.

    Classification decides whether the request may be re-sent, so it is
    deliberately narrow: anything unrecognised is permanent. Retrying a
    permanent failure buys a second identical error and a second charge.
    """
    if isinstance(exc, (TaskCancelled, RevisionSuperseded)):
        return 'cancelled'
    if isinstance(exc, TransientProviderError):
        return 'transient'
    # A call site that knows its provider's quirks may say so outright. The
    # image endpoint returns 400 for a busy provider, which is transient there
    # and permanent everywhere else; the status alone cannot express that.
    if getattr(exc, 'transient', None) is True:
        return 'transient'
    if isinstance(exc, InvalidResponse):
        return 'invalid_response'
    if isinstance(exc, BudgetExceeded):
        return 'permanent'
    status = http_status
    if status is None:
        # `.http_status` is ours; `.status` is what shared.aiengine.image_api's
        # _Transient carries; `.response.status_code` is requests'.
        for attribute in ('http_status', 'status', 'status_code'):
            status = getattr(exc, attribute, None)
            if status is not None:
                break
    if status is None:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
    if isinstance(status, bool):
        status = None
    if isinstance(status, int):
        return 'transient' if status in TRANSIENT_HTTP else 'permanent'
    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None and isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return 'transient'
    if isinstance(exc, (ValueError, KeyError, TypeError, IndexError)):
        return 'invalid_response'
    return 'permanent'


def _upload_broke(exc):
    """Whether `exc` is a request body that broke off part way up (a slow
    uplink), which a smaller body may get past. -> bool"""
    from shared.aiengine.model_upload import UploadFailed
    return isinstance(exc, UploadFailed)


def backoff(attempt):
    """Exponential backoff with full jitter, capped.

    Jitter matters because a burst of provider errors hits every concurrent
    import at once; synchronised retries reproduce the outage.
    """
    ceiling = min(MAX_BACKOFF_S, BASE_BACKOFF_S * (2 ** max(0, attempt - 1)))
    return random.uniform(0, ceiling)


def _guard(action, *args, **kwargs):
    """Run a DIAGNOSTIC write; its failure is logged, never raised at a turn.

    Never wrap authoritative state in this. See the module docstring.
    """
    try:
        return action(*args, **kwargs)
    except Exception:
        logger.debug('task trace write failed (%s)', getattr(action, '__name__', action), exc_info=True)
        return None


# ------------------------------------------------------------------- context

class TaskContext:
    """One durable task: its envelope, its revision, its spans and its stop flag."""

    def __init__(self, envelope, *, chat_id=None, family='', request='', config_snapshot=None,
                 bus=None, persist=True, call_budget=DEFAULT_CALL_BUDGET,
                 cost_budget_usd=DEFAULT_COST_BUDGET_USD, carried_usd=0.0, carried_calls=0):
        self.envelope = envelope
        self.chat_id = chat_id
        self.family = family
        self.request = request
        self.bus = bus or events.BUS
        self.persist = persist
        # A configuration snapshot taken when the task STARTS: changing the app
        # setting must affect new tasks, not a half-finished review.
        #
        # The carried debt is written into it HERE rather than by whoever calls
        # `start`: `store.accounting` reconstructs a task's committed total from
        # this snapshot, and a continuation that is refused before it dispatches
        # has no spans to reconstruct from. Leaving it to the caller meant the
        # chain reset to zero on the next continuation.
        self.config_snapshot = dict(config_snapshot or {})
        self.config_snapshot.setdefault('carried_usd', round(max(0.0, carried_usd), 8))
        self.config_snapshot.setdefault('carried_calls', max(0, int(carried_calls)))
        # The process running it: a restart closes only tasks no live process owns.
        from core import jobs
        self.config_snapshot.setdefault('owner', jobs.process_owner())
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        # One authoritative ledger for this task. Spending guards, the UI total
        # and the trace all read it; nothing keeps a private second count.
        self.costs = contracts.CostRoll(carried_usd=round(max(0.0, carried_usd), 8))
        # Admission control. `reserved_calls` counts dispatches admitted, not
        # completed, so a crash cannot make the budget look free again.
        # `carried_calls` is an earlier task's spend on the SAME unresolved
        # objective: a fresh "continue" must not hand out a fresh allowance.
        self.call_budget = call_budget
        self.cost_budget_usd = cost_budget_usd
        self.reserved_calls = max(0, int(carried_calls))
        # Generated images' own allowance, counted in IMAGES per user turn, not in
        # dollars (`allow_images`; the engine sets it every turn). None: an image is
        # admitted against the money budget like any request. While it is set, an
        # image never reads the money budget and the money budget never counts an
        # image: `image_costs` is the images' share of `costs` (which still holds
        # every charge, for the trace, the UI total and the accounting), and the
        # money check reads `text_committed_usd`. A stage turn's text rounds used to
        # leave too little of its 10 cents for the image's 5-cent reservation, so
        # every material was refused before it was sent.
        self.image_allowance = None
        self.images_admitted = 0
        self._images_open = 0
        self.image_costs = contracts.CostRoll()
        if self.persist:
            store.create_task(envelope, chat_id=chat_id, family=family, request=request,
                              config_snapshot=self.config_snapshot)
        self.emit(events.TASK_STARTED, workflow=envelope.workflow, family=family)

    # ------------------------------------------------------------- identity
    @property
    def task_id(self):
        return self.envelope.task_id

    @property
    def revision(self):
        return self.envelope.revision

    @property
    def cancelled(self):
        return self._cancel.is_set()

    @property
    def finished(self):
        return self.envelope.state in contracts.TERMINAL_STATES

    def emit(self, kind, **payload):
        """Publish a coordinator event. The bus persists it before delivering."""
        return self.bus.emit(kind, self.task_id, revision=self.revision, **payload)

    def save(self, *, expect_revision=None):
        """Persist the envelope. Raises: task state is authoritative."""
        if self.persist:
            store.save_task(self.envelope, expect_revision=expect_revision)
        return self.envelope

    # -------------------------------------------------------------- lifecycle
    def revise(self, reason='user_revision', request=''):
        """The user changed the request: bump the revision, stale the approvals.

        One commit (`store.revise_task`) covers the revision row, the envelope
        and every invalidation, because any intermediate state is a lie the app
        would act on. Everything bound to the old revision stops being
        authorization. Content-addressed artifacts survive: they are identified
        by their bytes, not by the revision that produced them.
        """
        with self._lock:
            if self.finished:
                raise TaskFinished('That task has finished; start a new one instead of revising it.')
            if self.persist:
                revision, stale = store.revise_task(self.task_id, reason, request, self.envelope)
            else:
                stale = [self.envelope.next.id] if self.envelope.next is not None else []
                self.envelope.revision += 1
                self.envelope.next = None
                if self.envelope.state in ('waiting_decision', 'waiting_approval'):
                    self.envelope.state = 'running'
                revision = self.envelope.revision
        for request_id in stale:
            self.emit(events.APPROVAL_INVALIDATED, request_id=request_id)
        self.emit(events.TASK_REVISED, reason=reason, new_revision=revision)
        return revision

    def request_cancel(self, reason='user_stop'):
        """Ask the task to stop. It lands at the next `checkpoint()`."""
        self._cancel.set()
        self.emit(events.TASK_CANCELLING, reason=reason)

    def checkpoint(self, expected_revision=None):
        """A safe boundary: stop if cancelled, or if this work is obsolete.

        Placed between stages, never inside one -- stopping mid-write is how a
        half-applied build commit happens.

        The revision is compared against DURABLE state, not only this object's
        memory: a separately loaded context holding revision 1 passed its own
        checkpoint long after SQLite had advanced to 2, because it was asking
        itself. `expected_revision` defaults to the revision the current unit of
        work began under (`work_unit`), so a boundary reached later in the same
        piece of work still recognises that the request changed underneath it.
        """
        if self._cancel.is_set():
            raise TaskCancelled('The task was cancelled.')
        if expected_revision is None:
            expected_revision = _WORK_REVISION.get()
        if expected_revision is None:
            return
        current = self.revision
        if self.persist:
            durable = _guard(store.current_revision, self.task_id)
            if durable is not None:
                current = durable
                if durable != self.envelope.revision:
                    self.envelope.revision = durable   # believe the database
        if expected_revision != current:
            raise RevisionSuperseded(expected_revision, current)

    def admit(self, *, cost_estimate=None, role='main'):
        """Reserve one model dispatch against the task budget, or refuse.

        This is the ONE admission point for paid work, and it runs before EVERY
        dispatch -- the routing decision, the fast lane, the main round, a nested
        vision labeller, an image generation and every retry of any of them.

        Money is reserved, not assumed free, and the reservation is chosen by
        ROLE: reserving a chat round's price for an image admitted a $0.12
        request under a $0.01 budget. Returns the reserved amount, which the
        caller settles with `settle_dispatch`.

        An image while `image_allowance` is set is admitted by COUNT instead of
        against the money budget (see `allow_images`), so one image is always
        admissible while the turn has images left, however much text it spent.
        """
        with self._lock:
            # A finished task may not buy anything. Queued follow-ups used to
            # run against a terminalized task and spend under its dead revision.
            if self.finished:
                raise TaskFinished(
                    f'That task already finished as {self.envelope.outcome}; it cannot spend more.')
            if self.reserved_calls >= self.call_budget:
                raise BudgetExceeded(
                    f'This task reached its limit of {self.call_budget} model requests.', kind='requests')
            reserve = (ROLE_RESERVE_USD.get(role, contracts.UNKNOWN_CHARGE_RESERVE_USD)
                       if cost_estimate is None else max(0.0, float(cost_estimate)))
            if role == 'image' and self.image_allowance is not None:
                if self.images_admitted >= self.image_allowance:
                    raise ImageAllowanceReached(self.image_allowance)
                self.images_admitted += 1
                self._images_open += 1
                self.reserved_calls += 1
                self.image_costs.reserve(reserve)
                return self.costs.reserve(reserve)
            if (self.cost_budget_usd is not None
                    and self._text_committed() + reserve > self.cost_budget_usd):
                raise BudgetExceeded(
                    'This task hit its usage limit.',
                    diagnostic=f'cost budget ${self.cost_budget_usd:.2f}: ${self._text_committed():.4f} committed, '
                               f'${reserve:.4f} more reserved for this {role} request')
            self.reserved_calls += 1
            return self.costs.reserve(reserve)

    def settle_dispatch(self, reserved, reported, *, role='main', billed=True):
        """Book one dispatch's real charge against its reservation.

        An image admitted under the image allowance is booked to `image_costs` as
        well; one that was not billed (the provider answered with an error status:
        nothing was generated) gives its image back to the turn's allowance.
        """
        with self._lock:
            self.costs.release(reserved, reported)
            if role == 'image' and self._images_open > 0:
                self._images_open -= 1
                self.image_costs.release(reserved, reported)
                if not billed:
                    self.images_admitted = max(0, self.images_admitted - 1)
            return self.costs

    def allow_images(self, count):
        """Give this turn its own allowance of `count` generated images (None: no
        allowance, images spend from the money budget). Called once per user turn:
        the count starts again at zero; the images' share of the spend is kept."""
        with self._lock:
            self.image_allowance = None if count is None else max(0, int(count))
            self.images_admitted = 0

    def images_left(self):
        """Images this turn may still generate, or None when images have no allowance of their own."""
        with self._lock:
            if self.image_allowance is None:
                return None
            return max(0, self.image_allowance - self.images_admitted)

    @property
    def committed_usd(self):
        """What the UI and the accounting read: every charge, generated images included."""
        with self._lock:
            return self.costs.committed_usd

    @property
    def text_committed_usd(self):
        """What the money guards read: the committed spend less the images admitted
        under their own allowance (`allow_images`)."""
        with self._lock:
            return self._text_committed()

    def _text_committed(self):
        return round(max(0.0, self.costs.committed_usd - self.image_costs.committed_usd), 8)

    def finish(self, outcome, *, state=None, error=None, achieved=None, receipts=None):
        """Reach a terminal state: validate, persist, THEN publish.

        In that order, and with failures propagating. Changing memory first and
        swallowing the persistence error is how a task with a failed required
        check published `TASK_FINISHED(outcome='success')` while SQLite still
        said `running`.
        """
        with self._lock:
            if self.finished and self.envelope.outcome == outcome:
                return self.envelope                      # idempotent re-finish
            if self.finished:
                raise TaskFinished(
                    f'That task already finished as {self.envelope.outcome}.')
            proposed = copy.deepcopy(self.envelope)
            proposed.state = state or ('cancelled' if outcome == 'cancelled'
                                       else 'failed' if outcome == 'failed' else 'completed')
            proposed.outcome = outcome
            if achieved:
                proposed.achieved.update(achieved)
            if receipts is not None:
                proposed.receipts = list(receipts)
            if error is not None:
                proposed.error = error
            if proposed.state == 'failed' and proposed.error is None:
                proposed.error = {'kind': 'unspecified',
                                  'detail': 'The task failed without a recorded reason.'}
            proposed.next = None
            proposed.validate()                           # raises before anything changes
            if self.persist:
                # ONE commit: the terminal envelope and the retirement of every
                # pending approval. Two commits left a window in which a
                # cancelled task still held a pending approval, and a click
                # arriving in that window was accepted.
                store.finish_task(proposed, 'cancelled')
            self.envelope = proposed
        self.emit(events.TASK_FINISHED, outcome=outcome,
                  achieved=dict(self.envelope.achieved), accounting=self.accounting())
        return self.envelope

    # ------------------------------------------------------- decisions/approvals
    def ask(self, kind, *, prompt='', allowed_responses=(), evidence_ids=(), schema=None,
            operation_id='', operation_digest=''):
        """Raise a typed decision or approval bound to THIS revision."""
        with self._lock:
            if self.finished:
                raise TaskFinished('That task has finished; it cannot ask for anything more.')
            request = NextRequest(kind=kind, task_revision=self.revision, prompt=prompt,
                                  allowed_responses=list(allowed_responses),
                                  evidence_ids=list(evidence_ids), schema=schema or {},
                                  operation_id=operation_id,
                                  operation_digest=operation_digest).validate()
            previous_next, previous_state = self.envelope.next, self.envelope.state
            self.envelope.next = request
            self.envelope.state = 'waiting_approval' if kind == 'approval' else 'waiting_decision'
            try:
                if self.persist:
                    store.record_request(self.task_id, request)
                self.save()
            except Exception:
                self.envelope.next, self.envelope.state = previous_next, previous_state
                raise
        self.emit(events.APPROVAL_NEEDED if kind == 'approval' else events.DECISION_NEEDED,
                  request_id=request.id, prompt=prompt, allowed_responses=list(allowed_responses))
        return request

    def settle(self, request_id, response):
        """Answer a pending request of THIS task, atomically.

        Ownership, current revision, pending status and the offered responses
        are all checked inside the transaction that records the answer -- see
        `store.settle_request`. A repeat of the same answer is idempotent; a
        different one is a conflict, not an overwrite.
        """
        with self._lock:
            kind = (self.envelope.next.kind
                    if self.envelope.next is not None and self.envelope.next.id == request_id
                    else 'decision')
            if self.persist:
                disposition, response = store.settle_request(
                    request_id, response, task_id=self.task_id, expect_revision=self.revision)
            else:
                disposition = 'settled'
            if self.envelope.next is not None and self.envelope.next.id == request_id:
                self.envelope.next = None
                if self.envelope.state in ('waiting_decision', 'waiting_approval'):
                    self.envelope.state = 'running'
                self.save()
        if disposition == 'settled':
            self.emit(events.APPROVAL_SETTLED if kind == 'approval' else events.DECISION_ANSWERED,
                      request_id=request_id, status=response)
        return response

    # ---------------------------------------------------------------- results

    def accounting(self):
        if not self.persist:
            return self.costs.to_dict()
        return _guard(store.accounting, self.task_id) or self.costs.to_dict()

    def charge(self, amount):
        """Fold one attempt's charge into the task roll, under the lock.

        Concurrent background work shares this roll; an unlocked read-modify-
        write loses charges in exactly the accounting the report depends on.
        """
        with self._lock:
            self.costs.charge(amount)
            return self.costs

    # ------------------------------------------------------------------ spans
    def record_span(self, span, *, name=''):
        if self.persist:
            _guard(store.record_span, span, name=name)
        return span

    @contextlib.contextmanager
    def waiting(self, kind, detail=''):
        """Measure one wait, tagged by what it waited on.

        User waiting, approval waiting, Dolphin-lock waiting, model service time
        and local processing are reported separately: overlapping spans cannot
        be added up to explain wall time.
        """
        if kind not in contracts.WAIT_KINDS:
            raise ValueError(f'wait kind must be one of {sorted(contracts.WAIT_KINDS)}')
        started = time.monotonic()
        self.emit(events.WAIT_STARTED, wait_kind=kind, detail=detail)
        try:
            yield
        finally:
            elapsed = round((time.monotonic() - started) * 1000, 3)
            self.emit(events.WAIT_ENDED, wait_kind=kind, detail=detail, waited_ms=elapsed)


class _NullContext(TaskContext):
    """The context used when instrumented code runs outside any task.

    `decisions`, `fast_lane` and `image_api` are called from places that
    have no task -- eval scripts, other tools, the tests that predate this
    module. They must keep working and must not write SQLite rows, so the null
    context emits nothing, persists nothing and never refuses a dispatch.
    """

    def __init__(self):
        super().__init__(TaskResult(task_id='task_untracked', workflow=''), persist=False,
                         bus=events.Bus(), call_budget=float('inf'), cost_budget_usd=None)

    def emit(self, kind, **payload):
        return {'type': kind, 'task_id': self.task_id, 'revision': self.revision, **payload}

    def save(self, *, expect_revision=None):
        return self.envelope

    def admit(self, *, cost_estimate=None, role='main'):
        return 0.0

    def settle_dispatch(self, reserved, reported, *, role='main', billed=True):
        return self.costs

    def allow_images(self, count):
        return None


_NULL = None
_NULL_LOCK = threading.Lock()


def current():
    """The task this call belongs to, or a null context that records nothing."""
    global _NULL
    task = CURRENT.get()
    if task is not None:
        return task
    with _NULL_LOCK:
        if _NULL is None:
            _NULL = _NullContext()
    return _NULL


def tracking():
    """True when a real task is attached. Cheap test for hot paths."""
    return CURRENT.get() is not None


# ---------------------------------------------------------------- ancestry

def _push_span(span):
    """Open a span in THIS context's ancestry and return the reset token."""
    stack = _ANCESTRY.get()
    span.parent_span_id = stack[-1].span_id if stack else ''
    return _ANCESTRY.set((*stack, span))


def _pop_span(token):
    _ANCESTRY.reset(token)


def open_span():
    """The innermost span in this context, or None. Used to attach children."""
    stack = _ANCESTRY.get()
    return stack[-1] if stack else None


@contextlib.contextmanager
def work_unit(revision=None, task=None):
    """Mark the revision this unit of work belongs to.

    Everything inside -- stages, dispatches, their retries -- defaults to
    checking against THIS revision, so a boundary reached after the user revised
    stops rather than quietly adopting the new number.
    """
    task = task or current()
    token = _WORK_REVISION.set(task.revision if revision is None else revision)
    try:
        yield _WORK_REVISION.get()
    finally:
        _WORK_REVISION.reset(token)


# ------------------------------------------------------------------ lifecycle

def start(workflow='', *, chat_id=None, family='', request='', workflow_version=1,
          config_snapshot=None, task_id=None, call_budget=DEFAULT_CALL_BUDGET,
          cost_budget_usd=DEFAULT_COST_BUDGET_USD, carried_usd=0.0, carried_calls=0):
    envelope = TaskResult(workflow=workflow, workflow_version=workflow_version,
                          **({'task_id': task_id} if task_id else {}))
    return TaskContext(envelope, chat_id=chat_id, family=family, request=request,
                       config_snapshot=config_snapshot, call_budget=call_budget,
                       cost_budget_usd=cost_budget_usd, carried_usd=carried_usd,
                       carried_calls=carried_calls)


@contextlib.contextmanager
def attach(task):
    """Make `task` the current context for this call stack.

    Ancestry is reset too: a task attached on a fresh stack starts at the root,
    never under whatever span the previous attachment left open.
    """
    token = CURRENT.set(task)
    ancestry = _ANCESTRY.set(())
    try:
        yield task
    finally:
        _ANCESTRY.reset(ancestry)
        CURRENT.reset(token)


INTERRUPTED = {'kind': 'interrupted', 'detail': 'Nucleus stopped while this task was running.'}


def _close_interrupted(row):
    """Close a task whose process died: failed, `interrupted`, and marked so a
    continuation carries its spend (turn_facts._carried_ledger)."""
    envelope = TaskResult.from_dict(json.loads(row['envelope']))
    envelope.state, envelope.outcome, envelope.next = 'failed', 'failed', None
    envelope.error = dict(INTERRUPTED)
    envelope.facts['interrupted'] = True
    store.finish_task(envelope, 'cancelled')
    return envelope


def resume_pending():
    """Reconcile tasks that were in flight when the process died.

    Recorded stages are reused; dispatched-but-unseen model attempts become
    `unresolved` open charges; incomplete side effects become `unresolved` and
    STAY discoverable until something reconciles them against the destination.
    Nothing is replayed here -- a build commit that may or may not have landed
    is checked by the workflow that owns it, never repeated by the coordinator.
    The task itself is closed as interrupted: no process will ever finish it.
    A task whose owning process still runs (another backend) is left alone.
    """
    from core import jobs
    rows = list(_guard(store.unfinished_tasks) or [])
    # A task an earlier restart closed still reports what it left unresolved.
    listed = {row['task_id'] for row in rows}
    for entry in _guard(store.open_tools) or []:
        if entry.get('task_id') and entry['task_id'] not in listed:
            row = _guard(store.task_row, entry['task_id'])
            if row:
                rows.append(row)
                listed.add(row['task_id'])
    resumed = []
    for row in rows:
        task_id = row['task_id']
        try:
            owner = json.loads(row.get('config_snapshot') or '{}').get('owner')
        except (TypeError, ValueError):
            owner = None
        if jobs.owner_alive(owner):
            continue
        pending = _guard(store.open_tools, task_id) or []
        for entry in pending:
            if entry['status'] == 'started':
                _guard(store.finish_tool, entry['operation_id'], 'unresolved')
        spans = _guard(store.reconcile_open_spans, task_id) or []
        message = events.BUS.emit(events.TASK_RESUMED, task_id, revision=row['revision'],
                                  stages=len(_guard(store.stages, task_id) or []),
                                  unresolved=[e['operation_id'] for e in pending],
                                  unresolved_attempts=len(spans))
        if row['state'] not in contracts.TERMINAL_STATES:
            try:
                _close_interrupted(row)
            except Exception:
                logger.warning('could not close interrupted task %s', task_id, exc_info=True)
        resumed.append({'task_id': task_id, 'revision': row['revision'], 'state': row['state'],
                        'unresolved': _guard(store.open_tools, task_id) or [],
                        'unresolved_attempts': spans, 'event': message})
    return resumed


# ---------------------------------------------------------- model-request spans

@contextlib.contextmanager
def model_request(role, *, requested_model='', decision_id='', attempt=1, task=None,
                  task_family='', prompt_template_version='', configuration_version='',
                  tool_schema_version='', dependency_ids=(), input_artifacts=(),
                  attached_images=(), timeout_s=None, retry_delay_ms=None, operation_id='',
                  retry_policy='bounded_transient', max_attempts=None, admit=True,
                  expected_revision=None):
    """Record ONE model request attempt, whatever provider serves it.

    The row is written BEFORE dispatch. A process that dies mid-request then
    leaves a `running` attempt that `resume_pending` turns into `unresolved` --
    an open charge -- instead of leaving no evidence that money was spent.

    The body fills in what only it can know (resolved model/provider, generation
    id, first-token time, usage, reported cost) and should do so AS SOON AS the
    provider says it, before validating the answer: a response that billed and
    then failed validation is still a charge.
    """
    task = task or current()
    if expected_revision is None:
        # The unit of work's revision, not the live one: see `work_unit`.
        expected_revision = _WORK_REVISION.get()
    if expected_revision is None:
        expected_revision = task.revision
    task.checkpoint(expected_revision)
    reserved = task.admit(role=role) if admit else 0.0
    span = ModelSpan(task_id=task.task_id, task_revision=expected_revision, attempt=attempt,
                     operation_id=operation_id or decision_id or new_id('op'),
                     component_version=COORDINATOR_VERSION, role=role,
                     decision_id=decision_id or new_id('decision'), task_family=task_family or task.family,
                     requested_model=requested_model, resolved_model=requested_model,
                     configuration_version=configuration_version,
                     prompt_template_version=prompt_template_version,
                     tool_schema_version=tool_schema_version, dependency_ids=list(dependency_ids),
                     input_artifact_hashes=list(input_artifacts), attached_image_hashes=list(attached_images),
                     timeout_s=timeout_s, retry_delay_ms=retry_delay_ms,
                     retry_policy=retry_policy, max_attempts=max_attempts,
                     reserved_cost_usd=reserved)
    parent = open_span()
    if isinstance(parent, StageSpan):
        parent.child_span_ids.append(span.span_id)
    token = _push_span(span)
    # Durable BEFORE the request leaves, and AUTHORITATIVE: a guarded write that
    # quietly failed still let the dispatch go, so the advertised crash-
    # accounting guarantee rested on a best-effort row. No row, no request.
    if task.persist:
        try:
            store.record_span(span, name=role)
        except Exception as exc:
            _pop_span(token)
            task.settle_dispatch(reserved, UNKNOWN, role=role, billed=False)
            raise DispatchNotRecorded(
                'the attempt could not be journalled, so it was not sent') from exc
    else:
        task.record_span(span, name=role)
    task.emit(events.MODEL_REQUEST_STARTED, role=role, decision_id=span.decision_id,
              attempt=attempt, requested_model=requested_model)
    span.dispatch_ms = round((time.monotonic() - span.monotonic_start) * 1000, 3)
    try:
        yield span
    except (TaskCancelled, RevisionSuperseded):
        span.retry_classification = 'cancelled'
        span.cancelled_after_ms = round((time.monotonic() - span.monotonic_start) * 1000, 3)
        span.finish('cancelled')
        raise
    except BaseException as exc:
        span.provider_error = _detail(exc, 300)
        span.retry_classification = classify(exc, http_status=span.http_status)
        span.finish('cancelled' if span.retry_classification == 'cancelled' else 'error')
        raise
    else:
        if span.retry_classification == 'cancelled':
            # The body saw a Stop and returned without an answer: not completed.
            span.finish('cancelled')
        else:
            if span.completion_ms is None:
                span.completion_ms = round((time.monotonic() - span.monotonic_start) * 1000, 3)
            # A body that recorded a provider error and returned normally still
            # failed this attempt; reporting it `ok` would hide a charged failure.
            span.finish('error' if span.provider_error else 'ok')
    finally:
        _pop_span(token)
        task.record_span(span, name=role)
        # A provider that ANSWERED with an error status generated nothing and billed
        # nothing; a request that never got an answer (a timeout) may have been billed.
        refused = (span.status == 'error' and type(span.http_status) is int and span.http_status != 200)
        task.settle_dispatch(reserved, span.reconciled_cost_usd if span.cost_status == 'reconciled'
                             else span.reported_cost_usd, role=role, billed=not refused)
        task.emit(events.MODEL_REQUEST_FINISHED, role=role, decision_id=span.decision_id,
                  attempt=attempt, status=span.status, cost_status=span.cost_status,
                  reported_cost_usd=contracts._plain(span.reported_cost_usd),
                  duration_ms=span.duration_ms, finish_reason=span.finish_reason,
                  retry_classification=span.retry_classification)


def run_model_request(role, call, *, attempts=MAX_ATTEMPTS, repairs=MAX_REPAIR_ATTEMPTS,
                      sleep=time.sleep, **fields):
    """One logical model decision: call `call(span)`, retrying within policy.

    This is the single admission point for a retried model request. It:

    * clamps `attempts` to `MAX_ATTEMPTS` -- a caller asking for five gets three;
    * keeps ONE `decision_id` across attempts, so the trace reads "one decision,
      three requests" rather than three unrelated decisions;
    * checks cancellation and revision before EVERY dispatch, not just the first;
    * retries transient failures with backoff and jitter, and allows at most
      `repairs` further attempts for a response that arrived and did not
      validate -- a separate, separately counted allowance.

    Only the model REQUEST is retried. `call` must be free of side effects;
    that is what `journal_tool` is for.
    """
    task = fields.pop('task', None) or current()
    expected_revision = fields.pop('expected_revision', None)
    if expected_revision is None:
        expected_revision = _WORK_REVISION.get()
    if expected_revision is None:
        expected_revision = task.revision
    decision_id = fields.pop('decision_id', '') or new_id('decision')
    limit = max(1, min(int(attempts), MAX_ATTEMPTS))
    repair_limit = max(0, min(int(repairs), MAX_REPAIR_ATTEMPTS))
    # Two counters, never one. `transient_used` is the outage allowance and
    # `repairs_used` is the bad-answer allowance; sharing them meant one
    # malformed reply spent a retry the next provider hiccup needed, and an
    # unclamped `repairs` bought as many dispatches as a caller asked for.
    transient_used = repairs_used = 0
    attempt, last = 1, None
    while True:
        task.checkpoint(expected_revision)
        try:
            with model_request(role, decision_id=decision_id, attempt=attempt, task=task,
                               max_attempts=limit, expected_revision=expected_revision,
                               **fields) as span:
                if repairs_used:
                    span.retry_policy = 'bounded_repair'
                return call(span)
        except (TaskCancelled, RevisionSuperseded, DispatchNotRecorded, BudgetExceeded):
            raise
        except Exception as exc:
            last = exc
            kind = classify(exc)
            if kind == 'transient' and transient_used < limit - 1:
                transient_used += 1
            elif kind == 'invalid_response' and repairs_used < repair_limit:
                repairs_used += 1
            else:
                raise
            delay = backoff(attempt)
            task.emit(events.MODEL_REQUEST_RETRIED, role=role, decision_id=decision_id,
                      attempt=attempt, next_attempt=attempt + 1, delay_ms=round(delay * 1000, 3),
                      classification=kind, transient_used=transient_used,
                      repairs_used=repairs_used,
                      reason=_detail(exc, 200))
            sleep(delay)
            fields['retry_delay_ms'] = round(delay * 1000, 3)
            attempt += 1
    raise last


def traced_provider(provider, *, role='main', requested_model='', task=None, **fields):
    """Wrap a streaming provider so every round it serves is a recorded span.

    Wrapping the FUNCTION rather than editing its body keeps the engine diff to
    one line and keeps the instrumentation in place when a test monkeypatches
    the provider.

    Retry is bounded to the part of the stream that has produced no output yet:
    once a delta has been handed downstream it is in the user's transcript, and
    re-sending would duplicate prose and could re-issue a tool call. Every
    attempt of one round shares one `decision_id`, and cancellation is checked
    before each dispatch. A round whose request body broke off part way up is
    re-sent once with its pictures re-encoded smaller.
    """
    def traced(messages, schemas, key, cancelled, *args, **kwargs):
        owner = task or current()
        expected_revision = owner.revision
        decision_id = new_id('decision')          # one logical round, N attempts
        attempt, delay_ms = 1, None
        shrunk = False
        content_hash = _message_content_hash(messages)
        images = _image_hashes(messages)
        tools_hash = schema_hash(schemas)
        while True:
            span = None
            emitted = False
            if cancelled is not None and cancelled.is_set():
                return
            owner.checkpoint(expected_revision)
            try:
                with model_request(role, requested_model=requested_model, task=owner,
                                   decision_id=decision_id, attempt=attempt,
                                   retry_delay_ms=delay_ms, max_attempts=MAX_ATTEMPTS,
                                   expected_revision=expected_revision,
                                   tool_schema_version=tools_hash,
                                   input_artifacts=[content_hash],
                                   attached_images=images, **fields) as span:
                    for event in provider(messages, schemas, key, cancelled, *args, **kwargs):
                        if event.get('type') == 'billing':
                            # The charge and the provider's identity, handed over
                            # the moment they exist. Waiting for a validated
                            # completion lost both when the answer turned out to
                            # be malformed -- and an unknown charge with no
                            # generation id can never be reconciled afterwards.
                            span.record_usage(event.get('usage'))
                            if event.get('cost_usd') is not None:
                                span.record_cost(event.get('cost_usd'))
                            span.provider_generation_id = (event.get('generation_id')
                                                           or span.provider_generation_id)
                            span.resolved_model = event.get('model') or span.resolved_model
                            span.resolved_provider = (event.get('provider')
                                                      or span.resolved_provider)
                            # ...and handed on: the completion that follows says
                            # `billed_early`, so the turn counts the charge only
                            # here. Swallowing it left every real round out of the
                            # turn's cost_usd (it showed the router's cost alone).
                            # Not `emitted`: a charge is not an answer, so a
                            # transient failure after it may still retry.
                            yield event
                            continue
                        if event.get('type') == 'delta':
                            if span.first_token_ms is None:
                                span.first_token_ms = round((time.monotonic() - span.monotonic_start) * 1000, 3)
                            emitted = True
                            yield event
                            continue
                        if event.get('type') == 'completion':
                            span.finish_reason = event.get('finish_reason') or ''
                            span.record_usage(event.get('usage'))
                            if 'cost_usd' in event:
                                span.record_cost(event.get('cost_usd'))
                            message = event.get('message') or {}
                            span.resolved_model = event.get('model') or span.resolved_model
                            span.resolved_provider = event.get('provider') or span.resolved_provider
                            span.provider_generation_id = event.get('generation_id') or event.get('id') or ''
                            span.response_validation = 'valid' if (
                                message.get('content') or message.get('tool_calls')) else 'empty'
                            span.completion_ms = round((time.monotonic() - span.monotonic_start) * 1000, 3)
                        emitted = True
                        yield event
                    if span.completion_ms is None and cancelled is not None and cancelled.is_set():
                        # A provider stops at a Stop by returning, not raising.
                        span.retry_classification = 'cancelled'
                        span.cancelled_after_ms = round((time.monotonic() - span.monotonic_start) * 1000, 3)
                return
            except GeneratorExit:
                raise
            except (TaskCancelled, RevisionSuperseded):
                raise
            except Exception as exc:
                if emitted or attempt >= MAX_ATTEMPTS or classify(exc) != 'transient':
                    raise
                reason = _detail(exc, 200)
                if not shrunk and _upload_broke(exc):
                    # The body broke off part way up: a slow uplink, not a busy
                    # provider. Resend this round once with smaller pictures;
                    # the conversation itself keeps its own.
                    from shared.aiengine import model_upload
                    smaller = model_upload.shrink_messages(messages)
                    if smaller is not None:
                        messages, shrunk = smaller, True
                        content_hash = _message_content_hash(messages)
                        images = _image_hashes(messages)
                        reason += ' (retrying with smaller images)'
                delay = backoff(attempt)
                owner.emit(events.MODEL_REQUEST_RETRIED, role=role, decision_id=decision_id,
                           attempt=attempt, next_attempt=attempt + 1, delay_ms=round(delay * 1000, 3),
                           classification='transient', reason=reason)
                time.sleep(delay)
                attempt, delay_ms = attempt + 1, round(delay * 1000, 3)

    traced.wrapped = provider
    return traced
