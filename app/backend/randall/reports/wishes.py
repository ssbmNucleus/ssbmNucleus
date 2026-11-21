"""A wish: a locally recorded, CONFIRMED missing capability -- and nothing else.

Design source: artifacts/harness-experiment-20260922/ASTRA-WISH.md.
Review answered here: artifacts/harness-experiment-20260922/ASTRA-REVIEW-WISHES.md.

This module owns everything the design says needs no model inference:
classifying a blocker, recording the gap, counting demand, rendering the
sentence Randall says about it, and the whole submission state machine. The
capability data lives in `assistant/capabilities.py`; `randall/routes/wishes.py` is
the HTTP surface and supplies the network.

THIS MODULE IS THE ONLY RECORDER
--------------------------------
Two public entry points, and nothing else may write a wish or send one:

* :func:`record_wish` -- the single front door for every call site. It accepts a
  task context OR a bare task id, classifies the blocker if the caller has not,
  and returns a :class:`WishRecord` whose `recorded` flag is the database
  write's own result.
* :func:`submit` -- the single way a wish leaves the machine.

Call sites must NOT construct a `contracts.Wish` and call `store.record_wish()`
directly. Three things go wrong when they do, and all three were live in this
tree: the grouping key ends up a versionless facade string, so shipping the
implementation silently closes the old backlog row instead of opening a new one;
the write's failure is swallowed and a wish id is returned anyway, so a receipt
says "recorded" for something that was never recorded; and demand is counted per
task, which the engine creates fresh every turn.

Five guarantees are enforced here rather than by convention. Each one is a
review finding that had a reproducing probe, so each has a test.

1. **Classification is driven by TYPED evidence, never by English.** Every input
   is an :class:`Observation` carrying a code from a closed vocabulary. Nothing
   here reads a `note`, a `limitations` string, an exception message or a model
   reply. Untyped evidence is refused, not guessed at.

2. **Nothing that leaves the machine is free text.** Every field of
   :func:`public_summary` and :func:`build_payload` is an enum, a validated
   identifier, a number, or a sentence taken from `assistant/capabilities.py`.
   A caller-supplied `requested_outcome`, `available_alternative` or `workflow`
   is NEVER copied through: the projection rebuilds them from the catalogue and
   maps an unrecognised workflow to `other`. An undeclared capability is
   rejected outright rather than projected with whatever strings it carried.

3. **Consent authorises the COMPLETE outgoing contents, frozen.**
   :func:`prepare_submission` builds the payload, the identity choice, and the
   attachment bytes, writes the finished ZIP to disk, and hashes all of it into
   one `approval_hash`. :func:`submit` sends exactly those frozen bytes.
   Changing the count, the identity choice, an attachment selection or an
   attachment's CONTENTS changes the hash and invalidates the approval. Booleans
   must be real booleans -- the JSON string `"false"` is not consent.

4. **Sending is exclusive, leased, and idempotent.** The rate check, the consent
   check and claiming the send happen in ONE `BEGIN IMMEDIATE` transaction that
   ends by writing a lease, so two concurrent clicks cannot both reach the
   network. An approved submission is frozen: review will not rewrite it and
   decline will not cancel it while a live lease exists. A lease that dies with
   the process EXPIRES rather than blocking sending forever. The remote id from
   the create call is persisted BEFORE the upload, so a lost acknowledgment
   retries into the same remote report instead of filing a second one, and
   `retry_after` plus a two-retry ceiling are enforced; exhaustion becomes the
   truthful terminal state `local_only`.

5. **This module never commits somebody else's transaction.** Its tables live in
   the same `tasks.db`, but on its OWN connection, created once and versioned in
   `wish_meta`. A read here cannot commit a half-finished owner transaction --
   which a shared connection running `executescript()` per call did.

Storage. The Session-1 store (`assistant/tasks/store.py`) owns the `wishes`
table and `export_trace` reads it, so each observation is still mirrored there.
The authority for uniqueness and counting is this module's own
`wish_observations` ledger: the mirror is written only after the ledger claim
succeeds, and a failed mirror rolls the claim back, so the two cannot diverge
and a race cannot double-count. Legacy `queued` rows from before this module are
migrated once to local-only and shown in the backlog WITHOUT inventing
conversation demand for them.

Release gate. `NUCLEUS_WISH_SUBMIT=0` closes SUBMISSION only. Wishes are still
classified, recorded and counted -- the backlog is how the owner finds out what
to build, and turning it off would lose exactly the data the gate exists to
collect. What the gate stops is anything leaving the machine, and anything
CLAIMING that something left it: :func:`submit` refuses with the typed state
`submission_disabled` before it prepares or collects anything, and the footer
offers no "Review and send".
"""

# The public wish API, re-exported: callers use `wishes.<name>`; the code lives in the wish_* modules.
from .wish_evidence import Classification, Observation, Requirement, classify_blocker
from .wish_gate import SUBMIT_GATE, submit_enabled
from .wish_keys import (canonical_payload, dedupe_key, key_for, safe_app_version, safe_workflow,
                        short_key, strict_bool, valid_key)
from .wish_ledger import (UNKNOWN_CONVERSATION, WishRecord, backlog, close, connection,
                          is_suppressed, latest_submission, record, record_wish,
                          requesting_conversations, submission, suppress, total_encounters)
from .wish_submit import (MAX_SEND_ATTEMPTS, PAYLOAD_MAX_BYTES, SubmissionBusy, TransportRefused,
                          availability, claim_send, decline, prepare_submission, rate_limit,
                          recover_stale_sends, submit)
from .wish_text import (FOOTER_ACTION, FOOTER_ALREADY, FOOTER_SAVED, FOOTER_SENT, PUBLIC_FIELDS,
                        WITHHELD_FIELDS, footer, public_summary)


# ---------------------------------------------------------------------------
# Unmet requirements -- the outcome signal, independent of storage
# ---------------------------------------------------------------------------

#: Where an unmet required operation is recorded on the envelope.
UNMET_FACT = 'unmet_requirements'


def unmet_requirements(envelope):
    """The required operations this build did not have, as typed entries."""
    facts = getattr(envelope, 'facts', None) or {}
    return list(facts.get(UNMET_FACT) or [])
