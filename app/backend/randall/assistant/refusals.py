"""A tool call refused for a reason Randall can explain, as the result the model and the tool card read.

The coordinator refuses a paid request before it is sent: the turn's spending limit, its limit of
model requests, its own allowance of generated images, a request that was stopped, replaced by a
newer message or already finished, a dispatch that could not be recorded first
(`tasks/coordinator.py`). Each of those used to reach the model and the card as "The tool could not
complete ... check the backend log", so the model retried the same call blindly and told the user
the tool "keeps failing" (a Dream Land retexture, 2026-10-04: three `generate_material` calls, each
refused at the 10-cent cap before reaching the provider).

`explain(exc)` turns a known refusal into its own result:

* ``error``: one plain sentence the tool card shows and the model reads (what did not happen, why,
  and what the user can do); a stop is a ``note`` with ``approval_status: cancelled`` instead, like
  the engine's own interrupted call.
* ``refusal``: its kind, a tag the card uses to leave out the generic "try again" line.
* ``next``: for the model only in practice (no card shows it): that retrying cannot work in this
  turn and what to do instead.

Anything else is unexpected (`unexpected`): the generic sentence, with the exception itself in
``diagnostic`` (card-only, `compaction.UI_ONLY_ANY`; "Report this chat" keeps it), never in what the
model reads.

A refusal that holds for the rest of the turn (`LASTS_THE_TURN`) is remembered by the engine for
the tool's paid family (`PAID_FAMILY`): a later call of that family in the same turn gets the same
result without running (`held`), so it cannot reach the provider or cost a retry.
"""

GENERIC = 'The tool could not complete. Your request was not reported as successful; check the backend log.'

# Tools whose call is a paid request of one kind. Only generated images today: every other paid
# request a tool makes (import_model's decision points) handles its own refusal.
PAID_FAMILY = {'generate_material': 'image'}
# Refusals no further call can get past in this turn; the next user message starts a new turn.
LASTS_THE_TURN = frozenset({'image_allowance', 'spending_limit', 'request_limit', 'finished'})

_WORDS = ('no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')

_TELL = ('Tell the user plainly what was done and what was not, and that they can ask again in a new '
         'message to continue.')


def _count(number):
    return _WORDS[number] if 0 <= number < len(_WORDS) else str(number)


def image_allowance(allowance):
    """The result for a turn whose images are used up (or switched off: allowance 0)."""
    if not allowance:
        return {'error': 'Generating images is switched off in this installation, so no image was made.',
                'refusal': 'image_allowance',
                'next': 'Do not call generate_material: it is switched off here. Use saved swatches or '
                        'palette edits instead, and tell the user plainly what was done and what was not.'}
    plural = '' if allowance == 1 else 's'
    return {'error': f'This request already generated its {_count(allowance)} image{plural}; ask again in a '
                     'new message to make more.',
            'refusal': 'image_allowance',
            'next': f'This turn may generate {allowance} image{plural} and has, so every further image in it '
                    'is refused before it reaches the provider: do not call generate_material again now. Use '
                    'the swatches already generated (or saved ones), or finish without a new one. Tell the '
                    'user plainly what was done and what was not, and that they can ask again in a new '
                    'message to make more.'}


def explain(exc):
    """The result for a refusal the coordinator raised, or None when `exc` is not one."""
    from .tasks import coordinator as taskflow
    if isinstance(exc, taskflow.ImageAllowanceReached):
        return image_allowance(exc.allowance)
    if isinstance(exc, taskflow.BudgetExceeded):
        if getattr(exc, 'kind', 'spending') == 'requests':
            return {'error': 'This request reached its limit of AI requests, so this step did not run; send '
                             'a new message to carry on.',
                    'refusal': 'request_limit',
                    'next': 'This request reached its limit of model requests: every further AI call in '
                            'this turn is refused the same way before it reaches the provider, so do not '
                            'retry it. ' + _TELL}
        result = {'error': 'This request reached its usage limit, so this step did not run; send a new message '
                           'to carry on.',
                  'refusal': 'spending_limit',
                  'next': 'This request reached its usage limit: retrying this call, or another AI call '
                          'of the same kind, in this turn is refused the same way before it reaches the '
                          'provider, so do not retry it. ' + _TELL}
        # The budget's figures stay off the card and the model ("Report this chat" keeps them).
        if getattr(exc, 'diagnostic', None):
            result['diagnostic'] = exc.diagnostic
        return result
    if isinstance(exc, taskflow.TaskCancelled):
        return {'note': 'You stopped this request, so this step did not finish.',
                'approval_status': 'cancelled', 'refusal': 'stopped'}
    if isinstance(exc, taskflow.RevisionSuperseded):
        return {'error': 'A newer message replaced this request, so this step was set aside.',
                'refusal': 'superseded',
                'next': 'Work on the newest message; do not repeat this call for the earlier request.'}
    if isinstance(exc, taskflow.TaskFinished):
        return {'error': 'This request had already finished, so this step did not run; send a new message '
                         'to carry on.',
                'refusal': 'finished',
                'next': 'Nothing more can run under this request, so do not retry it. ' + _TELL}
    if isinstance(exc, taskflow.DispatchNotRecorded):
        return {'error': 'Nucleus could not record this step before sending it, so it was not sent and used '
                         'none of your Randall usage; send a new message to try again.',
                'refusal': 'not_recorded',
                'next': 'Do not retry it in this turn. Tell the user plainly what was done and what was not.',
                'diagnostic': _detail(exc.__cause__ or exc)}
    return None


def not_saved(what, reason, *, retry=True):
    """The result of a retexture auto-save that did not save (randall/recolor/autosave.py): `what` is "costume"
    or "stage", `reason` the save's own plain sentence. The same sentence ends the turn's reply."""
    reason = str(reason or 'the save did not say why').strip().rstrip('.')
    if len(reason) > 1 and reason[0].isupper() and reason[1].islower():
        reason = reason[0].lower() + reason[1:]
    tail = ' Your edits are kept, and the next message tries again.' if retry else ' Your edits are kept.'
    return {'error': f'Not saved to your vault: {reason}.{tail}', 'refusal': 'not_saved',
            'next': f'The {what} was not saved to the vault. Do not say it is in the vault; say why it was not.'}


def unexpected(exc):
    """The result for an exception nobody expected: the generic sentence, the detail kept off the model."""
    return {'error': GENERIC, 'diagnostic': _detail(exc)}


def _detail(exc):
    return f'{type(exc).__name__}: {str(exc)[:800]}'


def remember(refused, tool, result):
    """Hold `result` for the rest of the turn when it is a refusal no later call of its family can get
    past (`refused`: the turn's {family: result})."""
    family = PAID_FAMILY.get(tool)
    if family and isinstance(result, dict) and result.get('refusal') in LASTS_THE_TURN:
        refused.setdefault(family, dict(result))


def held(refused, tool):
    """A copy of the refusal this turn already holds for the tool's family, or None."""
    result = refused.get(PAID_FAMILY.get(tool))
    return dict(result) if result is not None else None
