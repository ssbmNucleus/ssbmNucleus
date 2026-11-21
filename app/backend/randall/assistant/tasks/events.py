"""Coordinator events: what drives a progress card without paying for a model call.

The measured failure this exists to prevent (REPORT.md, and spec section 4) is
an engine that learns a long task's state by asking the model about it. A model
round costs seconds and cents and can be wrong; an event is free and is emitted
by the code that actually did the thing.

So: application code emits into the task journal (`store.events`), and the
model is woken only at a genuine decision checkpoint (`DECISION_NEEDED` /
`APPROVAL_NEEDED`). Nothing here calls a provider. Chat progress reaches the
window through `live_runs`, not through this module.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# -- lifecycle
TASK_STARTED = 'task_started'
TASK_REVISED = 'task_revised'            # the user changed the request; revision bumped
TASK_RESUMED = 'task_resumed'            # picked up from recorded stages after a restart
TASK_FINISHED = 'task_finished'
TASK_CANCELLING = 'task_cancelling'      # stopping at the next safe boundary
TASK_CANCELLED = 'task_cancelled'
# -- progress, the card's own feed
STAGE_STARTED = 'stage_started'
STAGE_PROGRESS = 'stage_progress'
STAGE_FINISHED = 'stage_finished'
# -- waiting, separated because the report separates them
WAIT_STARTED = 'wait_started'
WAIT_ENDED = 'wait_ended'
# -- checkpoints that genuinely need an answer
DECISION_NEEDED = 'decision_needed'
DECISION_ANSWERED = 'decision_answered'
APPROVAL_NEEDED = 'approval_needed'
APPROVAL_SETTLED = 'approval_settled'
APPROVAL_INVALIDATED = 'approval_invalidated'   # a revision made it stale
# -- accounting and diagnosis
MODEL_REQUEST_STARTED = 'model_request_started'
MODEL_REQUEST_FINISHED = 'model_request_finished'
MODEL_REQUEST_RETRIED = 'model_request_retried'

KINDS = frozenset((
    TASK_STARTED, TASK_REVISED, TASK_RESUMED, TASK_FINISHED, TASK_CANCELLING, TASK_CANCELLED,
    STAGE_STARTED, STAGE_PROGRESS, STAGE_FINISHED, WAIT_STARTED, WAIT_ENDED,
    DECISION_NEEDED, DECISION_ANSWERED, APPROVAL_NEEDED, APPROVAL_SETTLED, APPROVAL_INVALIDATED,
    MODEL_REQUEST_STARTED, MODEL_REQUEST_FINISHED, MODEL_REQUEST_RETRIED))

# The kinds a progress card renders directly. Everything else is trace.
# APPROVAL_INVALIDATED belongs here: a card showing an approval that a revision
# has since staled must be retired on screen, not left inviting a click.
PROGRESS_KINDS = frozenset((TASK_STARTED, TASK_REVISED, TASK_RESUMED, TASK_FINISHED,
                            TASK_CANCELLING, TASK_CANCELLED, STAGE_STARTED, STAGE_PROGRESS,
                            STAGE_FINISHED, WAIT_STARTED, WAIT_ENDED,
                            DECISION_NEEDED, APPROVAL_NEEDED, APPROVAL_SETTLED,
                            APPROVAL_INVALIDATED))


def event(kind, task_id, *, revision=1, **payload):
    if kind not in KINDS:
        raise ValueError(f'unknown coordinator event {kind!r}')
    return {'type': kind, 'task_id': task_id, 'revision': revision, 'at': time.time(), **payload}


class Bus:
    """Stamps a task's events in ONE durable order.

    Persisting and stamping happen in one critical section: assigning the
    durable sequence in one section and handing the event on in another let a
    publisher that committed first come out second (a controlled probe saw 2
    before 1). The sequence is the store's rowid, so a reader resuming from
    `store.events(task_id, after=seq)` picks up across a restart.
    """

    def __init__(self, persist=None):
        self._lock = threading.Lock()
        self._fallback_sequence = 0
        self._persist = persist

    def publish(self, message):
        """Persist and stamp, inside one critical section."""
        with self._lock:
            stored = None
            if self._persist is not None:
                try:
                    stored = self._persist(message)
                except Exception:
                    # Losing the durable copy must not fail the task, but the
                    # message then carries no durable cursor and says so.
                    logger.debug('task event could not be persisted', exc_info=True)
            if stored is not None and stored.get('seq') is not None:
                return stored
            self._fallback_sequence += 1
            return {**message, 'seq': None, 'local_seq': self._fallback_sequence}

    def emit(self, kind, task_id, *, revision=1, **payload):
        return self.publish(event(kind, task_id, revision=revision, **payload))


def _persist(message):
    from . import store
    return store.record_event(message)


# One process-wide bus, writing through to the journal.
BUS = Bus(persist=_persist)
