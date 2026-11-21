"""Shrink tool results the model has already read.

A model-import reply is often 20-110 KB of JSON (a mesh inventory, every region, a
joint list), and every one of them used to stay in the conversation in full.
One follow-up turn on a Dark Magician draft grew from 48k to 110k tokens of
context in ten tool calls, which is slower and dearer on every later round.

The newest results stay whole. Older ones keep what later steps actually need
-- which tool ran, whether it worked, every id, the error, the note, the
warnings, what was chosen -- and drop the bulk data, naming what was dropped so
the model knows to call the tool again if it needs it.

Some of a result is for the chat's cards only (``UI_ONLY``: import_model's
``flow``, the import's phases with every decision and the pictures each one
looked at, as chat file IDs). The transcript keeps it whole; the model never
gets it (``model_view``): every way a result reaches the model goes through
``fit_fresh`` (a new result) or ``compact_result`` (an older one, an earlier
turn's receipt in the app context), and both start from ``model_view``. The
vision layer attaches only a result's ``files``, never what ``UI_ONLY`` names.
"""
import json

KEEP_WHOLE = 2           # newest tool results in a turn that stay untouched
SMALL = 1500             # a result this size (chars of JSON) is never shortened
TEXT = 400               # longest string kept in a shortened result
LIST = 8                 # longest list of plain values kept
FRESH_BUDGET = 24000     # chars of JSON (~6k tokens) a NEW tool result may take
# Keys of a tool result that are for the chat's cards only (the module doc): never sent to the model.
UI_ONLY = ('flow',)
# The same for any tool's result: a lab checkpoint's `viewer_update` (the textures the
# workbench's 3D view swaps in place, assistant/continuity.py) is the view's, not the model's;
# ``diagnostic`` is the exception behind a failed import or an unexpected tool failure
# (assistant/refusals.py), for "Report this chat" (reports/chat_report.py keeps it).
# A result's dollar cost (generate_material's, import_model's) and generate_material's provider
# are the developer's: users never see dollar amounts or the provider's name (owner's rule,
# 2026-10-07), so Randall is never handed one to repeat. The engine books the cost from the whole
# result, and Developer details shows it on the card.
UI_ONLY_ANY = ('viewer_update', 'diagnostic', 'cost_usd', 'cost_per_material_usd', 'provider')
# A Stage Lab result (tagged `stage_target`, continuity.record_stage_result: stage_lab and
# skin_material on a stage) carries the checkpoint the workbench loads. The model never
# uses it: a closed session reopens from its workspace by its session_id alone.
STAGE_UI_ONLY = ('checkpoint_file', 'revision', 'stage_target')

# Always kept (shortened if long), whatever their size.
ALWAYS = ('error', 'note', 'warnings', 'summary', 'operation', 'status', 'state',
          'character', 'verdict', 'headline', 'next', 'vault_changed',
          'correction', 'attempts',
          # import_model's end summary: what a later turn's change names (its ids and values)
          'choices', 'project')


DROP = object()          # "this is bulk data", distinct from a real None


def _short(value, depth=0):
    """A value cut down to something small, or DROP when it is bulk data."""
    if isinstance(value, str):
        return value if len(value) <= TEXT else value[:TEXT] + '...'
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        if len(value) <= LIST and all(v is None or isinstance(v, (str, bool, int, float)) for v in value):
            return [_short(v) for v in value]
        if depth == 0 and len(value) <= LIST:
            kept = [_short(v, depth + 1) for v in value]
            if all(k is not DROP for k in kept) and len(json.dumps(kept, default=str)) <= SMALL:
                return kept
        return DROP
    if isinstance(value, dict) and depth < 2:
        kept = {k: _short(v, depth + 1) for k, v in value.items()}
        if any(v is DROP for v in kept.values()):
            return DROP
        return kept if len(json.dumps(kept, default=str)) <= SMALL else DROP
    return DROP


def model_view(result):
    """The part of a tool result the model sees: everything but the card-only keys (``UI_ONLY``) of a model
    import's result (tagged ``studio_import``: import_model's replies; another tool's key of the same name is its own,
    left for the model), ``UI_ONLY_ANY`` and a Stage Lab result's checkpoint keys (``STAGE_UI_ONLY``). -> result (the
    same object when it has none of them; else a shallow copy without them, the transcript's left whole)"""
    if not isinstance(result, dict):
        return result
    hidden = (UI_ONLY_ANY + (UI_ONLY if isinstance(result.get('studio_import'), dict) else ())
              + (STAGE_UI_ONLY if isinstance(result.get('stage_target'), dict) else ()))
    if not any(key in result for key in hidden):
        return result
    return {key: value for key, value in result.items() if key not in hidden}


def compact_result(result):
    """A shortened copy of one tool result, or the result itself when it is small."""
    result = model_view(result)
    if not isinstance(result, dict):
        return result
    if len(json.dumps(result, default=str)) <= SMALL:
        return result
    out, dropped = {}, []
    for key, value in result.items():
        if key == 'files' and isinstance(value, list):
            out['files'] = [{k: f.get(k) for k in ('file_id', 'name') if isinstance(f, dict) and k in f}
                            for f in value[:LIST]]
            continue
        if key in ALWAYS or key.endswith('_id') or key.endswith('_ids'):
            short = _short(value)
            if short is DROP:       # a long list of ids or sentences: keep the head
                short = value[:LIST] if isinstance(value, list) else str(value)[:TEXT]
            out[key] = short
            continue
        short = _short(value)
        if short is DROP:
            dropped.append(key)
        else:
            out[key] = short
    if dropped:
        out['shortened'] = ('Older result shortened to save context. Dropped: ' + ', '.join(dropped[:20])
                            + '. Call the tool again if you need those details.')
    return out


def compact_receipt(receipt):
    """An earlier turn's tool receipt, shortened for the app context."""
    arguments = receipt.get('arguments')
    text = json.dumps(arguments, default=str) if arguments is not None else ''
    return {'name': receipt.get('name'), 'status': receipt.get('status'),
            'arguments': arguments if len(text) <= TEXT else text[:TEXT] + '...',
            'result': compact_result(receipt.get('result') or {})}


def compact_older(tool_messages, keep=KEEP_WHOLE):
    """Shorten every message in `tool_messages` except the newest `keep`. In place.

    `tool_messages` are this turn's tool messages, oldest first, as the same
    dict objects that sit in the conversation (positions shift when a recipe
    card is inserted near the top). A shortened message leaves the list.
    """
    while len(tool_messages) > keep:
        message = tool_messages.pop(0)
        try:
            result = json.loads(message['content'])
        except (ValueError, TypeError, KeyError):
            continue
        message['content'] = json.dumps(compact_result(result), default=str)


def fit_fresh(result, budget=FRESH_BUDGET):
    """A new tool result cut to `budget` by trimming its biggest lists. -> result.

    Even the newest result can be too big: one 60 KB mesh inventory put MiMo
    past the three-minute response cap on 2026-09-22. The largest list (or
    dict) is halved until the whole fits, and every cut is named with how many
    entries it left out, so the model can ask for a narrower selection.
    The card-only keys (``UI_ONLY``) are left out first: the model never gets them.
    """
    result = model_view(result)
    if not isinstance(result, dict) or len(json.dumps(result, default=str)) <= budget:
        return result
    out, cuts = dict(result), {}
    for _ in range(40):
        sizes = sorted(((len(json.dumps(v, default=str)), k) for k, v in out.items()
                        if isinstance(v, (list, dict)) and len(v) > 1 and k != 'files'),
                       reverse=True)
        if not sizes or len(json.dumps(out, default=str)) <= budget:
            break
        _, key = sizes[0]
        value = out[key]
        total = cuts.get(key, (None, len(value)))[1]
        keep = max(1, len(value) // 2)
        out[key] = value[:keep] if isinstance(value, list) else dict(list(value.items())[:keep])
        cuts[key] = (keep, total)
    if len(json.dumps(out, default=str)) > budget:
        return compact_result(result)
    if cuts:
        out['trimmed'] = ('Long lists shortened to fit: ' + ', '.join(
            f'{k} (first {keep} of {total})' for k, (keep, total) in cuts.items())
            + '. Narrow the request (a selection, a region, a name) to see the rest.')
    return out
