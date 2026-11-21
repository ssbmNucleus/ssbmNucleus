"""Running one tool call as a journalled task stage, and telling a call that changes something
(journalled, never run twice) from a lookup (only traced)."""

import json

from . import tools
from .tasks import content_hash, stage_journal


# Tools that change something outside this process: a download, a vault write,
# a build, an export. These are journalled so a repeated model answer cannot run
# them twice. Everything else is a lookup and is only traced.
EFFECTFUL_TOOLS = frozenset(('download_website_mod download_website_mods save_mod_copy '
                             'create_clone_character deliver_to_game '
                             'undo_delivery set_website_mod_like install_project_mods '
                             'generate_material').split())
# Some tools are a whole family of operations behind one name, and only some of
# those operations change anything. Journalling by tool NAME made
# `test_in_game(action='status')` a side effect: the second status call was
# refused and handed back the FIRST call's stale snapshot.
# ...so the decision is made from an ALLOWLIST of the actions that change
# something, never from a denylist of the ones that do not: `texture_sheet` was
# missing from the read-only list and was therefore journalled as an effect,
# which is both wrong and expensive.
EFFECTFUL_ACTIONS = {
    'test_in_game': frozenset({'start', 'launch', 'boot', 'run', 'play', 'build'}),
    'skin_lab': frozenset({'recolor', 'apply', 'paint', 'replace', 'import', 'export',
                           'save', 'undo', 'redo', 'reset'}),
    'stage_lab': frozenset({'apply', 'replace', 'import', 'export', 'save', 'undo', 'reset'}),
}


def _is_effectful(prepared):
    """Whether THIS call changes something outside the process.

    An approval-gated call always does. Otherwise the decision is per operation,
    not per tool name, so a read-only action inside an effectful tool is neither
    journalled nor deduplicated.
    """
    if prepared.policy == 'approval':
        return True
    actions = EFFECTFUL_ACTIONS.get(prepared.name)
    if actions is not None:
        try:
            return str((json.loads(prepared.arguments) or {}).get('action') or '') in actions
        except (ValueError, TypeError, AttributeError):
            return True                       # unreadable arguments: assume it acts
    return prepared.name in EFFECTFUL_TOOLS


def _execute_tool(run, prepared, grant, options):
    """Run one tool as a journalled task stage.

    Two things the loop did not have before:

    * **A stage span**, so local tool time is measured as local time and sits in
      the trace beside the model requests that asked for it.
    * **A journal entry** for a call that actually CHANGES something, so a model
      repeating the same effectful call after a retry or a reconnect cannot run
      it twice. Read-only calls are traced and never journalled: journalling by
      tool name alone turned a second `test_in_game(action='status')` into a
      refusal that returned the first call's stale snapshot.

    Returns (result, reused). `reused` is what stops a replayed result from
    being charged a second time.
    """
    task = getattr(run, 'task', None)
    if task is None:
        return tools.execute(prepared, grant, **options), False
    effectful = _is_effectful(prepared)
    fingerprint = getattr(prepared, 'fingerprint', None) if effectful else None
    if effectful and not fingerprint:
        fingerprint = content_hash.canonical_hash([prepared.name, prepared.arguments])

    def body(span):
        span.input_artifact_hashes = [content_hash.canonical_hash(prepared.arguments)]
        result = tools.execute(prepared, grant, **options)
        if isinstance(result, dict):
            span.output_artifact_hashes = [content_hash.canonical_hash(
                sorted((result.get('files') or []), key=str))] if result.get('files') else []
            if result.get('error'):
                # A tool that returned an error did not succeed, whatever the
                # call did. Recording the stage `ok` made failures invisible in
                # the trace AND polluted the duration estimates with them.
                span.error_type, span.error_detail = 'tool_error', str(result['error'])[:500]
                raise _ToolReturnedError(result)
        return result

    def traced():
        try:
            return stage_journal.run_stage(f'tool:{prepared.name}', body, version='1',
                                           parameters={'arguments': prepared.arguments},
                                           resume=False, task=task)
        except _ToolReturnedError as failure:
            return failure.result

    if not effectful:
        return traced(), False
    with stage_journal.journal_tool(prepared.name, fingerprint, task=task) as claim:
        if not claim.claimed:
            previous = claim.result
            if previous is not None:
                # The same effect, already done. Hand back what it produced and
                # tell the caller it is a REPLAY: charging its cost again showed
                # one $0.04 image as $0.08 spent.
                return previous, True
            return {'error': 'That exact action is already in progress or was not recorded as '
                             'finished. It was not run a second time.'}, False
        result = traced()
        if isinstance(result, dict) and result.get('error'):
            claim.fail(result['error'])       # a failure is not a completed effect
        else:
            claim.complete(_effect_receipt(result))
        return result, False


def _effect_receipt(result):
    """What the journal keeps of a completed effect: identity, not payload.

    A tool result can carry megabytes of base64 images. Storing the whole thing
    made the journal the largest table in the database, and a single oversized
    write took a live turn down with it. What a replay actually needs is what
    the effect PRODUCED -- ids, hashes, counts -- so that is what is kept, with
    the payload reduced to a hash that proves two results are the same.
    """
    if not isinstance(result, dict):
        return {'result': str(result)[:2000]}
    keep = {}
    for key, value in result.items():
        if key in ('files', 'items', 'imported_items', 'imported_stages', 'downloads'):
            keep[key] = f'{len(value)} item(s)' if isinstance(value, (list, tuple)) else 'present'
        elif isinstance(value, (str, int, float, bool)) or value is None:
            keep[key] = value if not isinstance(value, str) or len(value) <= 500 else value[:500]
        else:
            keep[key] = content_hash.canonical_hash(value)
    return keep


class _ToolReturnedError(Exception):
    """A tool that answered with `{'error': ...}`: a failed stage, not a crash."""

    def __init__(self, result):
        super().__init__(str(result.get('error'))[:200])
        self.result = result
