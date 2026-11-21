"""Facts about a turn read from its chat and its receipts: the task that pins it, its budget family,
spend carried from a blocked attempt, its typed outcome, and the receipt summary the envelope keeps."""

from . import recipes
from randall.model_import.chat import studio_import
from randall.model_import.chat.attached_model import attached_model_waiting
from .tasks import coordinator as taskflow
from .tasks.contracts import OUTCOMES as contracts_OUTCOMES
from randall.reports import wishes


def _import_done(receipts):
    """True when this chat's newest import_model reply is a finished import (status done).

    Read from the replies studio_import reads (``_newest_import``): one the import
    tagged with its project (`studio_import.id`). A call refused before it ran
    (no id) is not an import reply, and an `error` reply with no status (a call
    that failed outside the job) changes nothing, so neither pins a finished
    import's chat back to the studio. An import that failed at a stage, or one
    from before this version that stopped on a question, is not done: the chat
    is still trying."""
    result = studio_import._newest_import(receipts)
    return result is not None and result.get('status') == 'done'


def _pinned_task(declared, receipts):
    """The declared task that pins this turn's routing, or None.

    A model import pins its chat to the studio only until the import has made
    its costume. After that, a turn about the costume ("search my vault for the
    goku you made") is a normal turn, exactly as studio_import.turn_mode treats
    one in an undeclared chat (offered import_model for a change to it)."""
    if declared == 'model_import' and _import_done(receipts):
        return None
    return declared


def _turn_family(text, receipts, declared=None, attachments=()):
    """A coarse family for this turn, used only to pick its budget.

    The same signals that make the engine's turn an import turn, never its
    words alone: `declared`, the task pinning this turn (`_pinned_task`), and
    `attachments`, the files the chat's recent messages carry."""
    # A chat started as an import is budgeted as one whatever its words ("here
    # is goku, put him on falcon"), until its costume is saved (`_pinned_task`
    # lets go then, and a follow-up turn on the result is a normal turn); an
    # ordinary chat is one when a model it carries is waiting to be imported,
    # whether or not the words also ask to test it in game (engine._run_turn).
    family = recipes.turn_family(declared, text)
    if family == 'model_import':
        return 'model_import'
    if (family is None or (family in recipes.FOLLOW_UP_FAMILIES and declared is None)) \
            and attached_model_waiting(text, attachments, receipts):
        return 'model_import'
    return 'randall_turn'


def _carried_ledger(chat_id):
    """Spend to carry forward from an earlier budget-blocked attempt.

    A user typing "continue" after Randall stopped at a spending limit is
    continuing the SAME unresolved objective. Giving that turn a fresh
    allowance is how a capped import quietly costs three caps. Only a new
    conversation, or a task that actually finished, starts the ledger at zero.
    A task Nucleus closed as interrupted at startup did not finish either.
    """
    if not chat_id:
        return 0.0, 0
    previous = taskflow._guard(taskflow.store.last_task_for_chat, chat_id)
    facts = (previous or {}).get('facts') or {}
    if not previous or not (facts.get('budget_exhausted') or facts.get('interrupted')):
        return 0.0, 0
    book = previous.get('accounting') or {}
    carried = float(book.get('committed_usd') or 0.0)
    calls = int(book.get('attempts') or 0)
    if not carried:
        # A continuation refused BEFORE it dispatched has no spans of its own,
        # so its reconstruction is empty -- but it still inherited a debt. Fall
        # back to what it was told to carry, or the whole chain resets to zero
        # on the third attempt at the same objective.
        inherited_usd, inherited_calls = taskflow._guard(
            taskflow.store.carried_ledger, previous['task_id']) or (0.0, 0)
        carried, calls = max(carried, inherited_usd), max(calls, inherited_calls)
    return carried, calls


# Terminal outcomes, worst first. A turn is graded at the WORST thing that
# happened to it, because a reader who is told "partly done" stops looking for
# the part that could not be measured at all.
OUTCOME_ORDER = ('failed', 'cancelled', 'blocked', 'denied', 'partial', 'success')


def _worst(outcomes):
    for outcome in OUTCOME_ORDER:
        if outcome in outcomes:
            return outcome
    return 'success'


def _receipt_outcome(receipt):
    """The typed outcome one tool receipt carries, or None.

    Tools increasingly return a task envelope of their own (`deliver_to_game`
    returns one straight out of `delivery/deliver.py`). A structured `blocked`
    with no top-level `error` used to fall through every check here and be read
    as a success.
    """
    result = receipt.get('result')
    if not isinstance(result, dict):
        return None
    approval = result.get('approval_status')
    if approval in {'denied', 'cancelled', 'expired', 'interrupted'}:
        return 'denied'
    if result.get('error'):
        return 'partial'
    for holder in (result, result.get('task_result'), result.get('envelope'), result.get('task')):
        if isinstance(holder, dict) and holder.get('outcome') in contracts_OUTCOMES:
            return holder['outcome']
    return None


def _turn_outcome(run, task=None):
    """The task outcome for a finished turn, read from what actually happened.

    A conversational reply that finished is NOT a completed task: Randall
    explaining that a download was denied, or that a fit failed, ends the turn
    `done` and achieves nothing the user asked for.

    Everything that happened is collected and the WORST is chosen, rather than
    the first branch that matches. The previous ladder returned `partial` when a
    required check had failed AND a tool had failed, because the tool branch ran
    first -- so the blocking check, the more serious of the two, disappeared.
    """
    answer = run.answer
    status = answer.get('status')
    if status == 'cancelled':
        return 'cancelled', None
    if status == 'error':
        return 'failed', {'kind': answer.get('stop_reason') or 'error',
                          'detail': answer.get('error') or 'The turn did not complete.'}
    seen = set()
    envelope = getattr(task, 'envelope', None)
    if envelope is not None:
        # A required check that failed or could not be measured, and a required
        # operation this build does not have, both mean nobody knows whether
        # what did run was correct.
        if envelope.blocking_checks:
            seen.add('blocked')
        if wishes.unmet_requirements(envelope):
            seen.add('blocked')
    receipts = answer.get('tools') or []
    outcomes = [_receipt_outcome(receipt) for receipt in receipts]
    refused = [o for o in outcomes if o == 'denied']
    if receipts and len(refused) == len(receipts):
        # Nothing was attempted against the user's wishes; that is a denial of
        # the turn, not a failure of the build.
        seen.add('denied')
    # A single refused action among several is a PARTIAL turn: the rest still
    # ran. Only a turn whose every action was refused is a denial.
    seen.update(o if o != 'denied' else 'partial' for o in outcomes if o)
    if status == 'steered':
        seen.add('partial')
    if not seen:
        return 'success', None
    return _worst(seen), None


def _receipt_summary(receipts):
    """What the envelope keeps of a turn's tool calls: identity, not payloads."""
    return [{'id': r.get('id'), 'tool': r.get('name'), 'status': r.get('status'),
             'approval_status': (r.get('result') or {}).get('approval_status'),
             'failed': bool((r.get('result') or {}).get('error')),
             'elapsed_ms': r.get('elapsed_ms')}
            for r in receipts or []]
