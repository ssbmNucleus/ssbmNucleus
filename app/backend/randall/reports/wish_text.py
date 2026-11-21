"""What a wish says: the chat-free public projection, and the footer a receipt carries."""

from randall.assistant import capabilities

from .wish_evidence import EVIDENCE_CODES
from .wish_gate import submit_enabled
from .wish_keys import api_version, dedupe_key, safe_app_version, safe_workflow, valid_key
from .wish_ledger import requesting_conversations


# ---------------------------------------------------------------------------
# The public projection -- enums, validated ids, numbers, catalogue sentences
# ---------------------------------------------------------------------------

#: Everything a wish may ever show or send. An allowlist, not a denylist: a
#: field added to `Wish` later is invisible here until someone adds it on
#: purpose, which is the right default for anything that leaves the machine.
PUBLIC_FIELDS = ('kind', 'capability', 'blocked_operation', 'implementation_version',
                 'variant', 'dedupe_key', 'requested_outcome', 'limitation',
                 'alternatives', 'evidence_codes', 'app_version', 'api_version',
                 'workflow', 'record_status')

#: Never projected, even if a caller puts something in them: task identity and
#: anything that could carry a path, a filename or chat text.
WITHHELD_FIELDS = ('wish_id', 'task_id', 'task_revision', 'evidence_ids')

_RECORD_STATUSES = frozenset(('queued', 'submitted', 'declined', 'duplicate'))


def public_summary(wish, *, classification=None, include_counts=False):
    """The chat-free projection of a wish. Catalogue text and typed codes ONLY.

    Every field is one of four things: a literal enum, a validated identifier, a
    number, or a sentence read out of `assistant/capabilities.py`. Nothing the
    caller wrote survives the projection --

    * `requested_outcome`, `limitation` and `alternatives` come from the
      DEFINITION, never from `wish.requested_outcome` /
      `wish.available_alternative`. The review's probe put a canary in the
      caller-supplied outcome and watched it reach `wish.json`.
    * `workflow` is mapped through :func:`safe_workflow`, so an unrecognised
      one becomes `other` rather than travelling as free text.
    * `evidence_codes` is intersected with the closed vocabulary, so a path
      someone stuffed into `evidence_ids` cannot survive.
    * `app_version` is pattern-checked; anything else becomes `unknown`.

    An UNDECLARED capability is rejected rather than projected: without a
    definition there is no trusted text to use, and falling back to the wish's
    own strings is exactly the hole this closes.
    """
    definition = capabilities.by_name(wish.capability)
    if definition is None:
        raise ValueError(f'{wish.capability!r} has no capability definition; '
                         'there is no trusted text to project')
    variant = classification.variant if classification is not None else _variant_of(wish)
    variant = definition.variant_or_refuse(variant)
    if not valid_key(wish.dedupe_key):
        raise ValueError('that wish does not carry an authoritative grouping key')
    projected = {
        'kind': 'capability_gap',
        'capability': definition.name,
        'blocked_operation': definition.operation,
        'implementation_version': definition.implementation_version,
        'variant': variant,
        'dedupe_key': wish.dedupe_key,
        'requested_outcome': definition.requested_outcome,
        'limitation': definition.limitation,
        'alternatives': list(definition.alternatives),
        'evidence_codes': sorted({c for c in (wish.evidence_ids or [])
                                  if c in EVIDENCE_CODES}),
        'app_version': safe_app_version(),
        'api_version': api_version(),
        'workflow': safe_workflow(wish.workflow),
        'record_status': (wish.record_status if wish.record_status in _RECORD_STATUSES
                          else 'queued'),
    }
    projected = {key: projected[key] for key in PUBLIC_FIELDS}
    if include_counts:
        projected['requesting_conversations'] = requesting_conversations(wish.dedupe_key)
    return projected


def _variant_of(wish):
    """Recover the variant from the stored grouping key, without guessing.

    The key is a hash, so the variant is found by re-deriving the key for each
    declared variant of the capability and matching. A variant that is not
    declared cannot be in the key, so this is exhaustive.
    """
    definition = capabilities.by_name(wish.capability)
    if definition is None:
        return ''
    for variant in ('',) + tuple(definition.variants):
        if dedupe_key(wish.capability, wish.blocked_operation,
                      definition.implementation_version, variant) == wish.dedupe_key:
            return variant
    return ''


# ---------------------------------------------------------------------------
# The footer
# ---------------------------------------------------------------------------

#: The footer the design specifies, verbatim.
FOOTER_SAVED = 'Feature request saved on this device.'
FOOTER_ALREADY = 'Already saved.'
FOOTER_ACTION = 'Review and send.'
#: Only ever used after an ACCEPTED report receipt, and only while submission
#: is open. There is no other string in this module that claims anything was
#: sent, which is what makes the gate's promise checkable.
FOOTER_SENT = 'Feature request sent privately to the developer.'


def footer(*, recorded=False, already_recorded=False, suppressed=False, sent=False):
    """The small, consistent footer a receipt carries, or None.

    Returns None unless something was actually saved: there is no footer for a
    failure, and none for a save that did not happen.

    The "Review and send" action disappears when the user suppressed this
    feature's invitation, when it has already been sent, and when
    `NUCLEUS_WISH_SUBMIT=0` -- offering an action the build will refuse is the
    same lie in a smaller space. The gap is still saved and still counted, and
    the footer still says so.
    """
    if sent:
        return {'text': FOOTER_SENT, 'action': None}
    offer = FOOTER_ACTION if (not suppressed and submit_enabled()) else None
    if recorded:
        return {'text': FOOTER_SAVED, 'action': offer}
    if already_recorded:
        return {'text': FOOTER_ALREADY, 'action': offer}
    return None
