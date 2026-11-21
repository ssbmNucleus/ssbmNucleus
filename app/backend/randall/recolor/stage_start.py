"""How a "Recolor a stage" chat starts: code opens the picked stage, then the main model works.

The stage recolor has no acquisition lane, and its prepare step is the open
itself: `stage_lab_open` returns the first rendered picture, labelled texture
sheets and one row per texture (size, triangles, greyscale slot), the evidence
the costume workflow's prepare stage collects with separate code rounds. So the
main model's first round can already edit. On turn one of a chat started as
"Recolor a stage" (recipes.LAUNCHABLE `recolor_stage`) with exactly one picked
stage, code issues `stage_lab_open` for it through the normal tool path (no
search, no model round); every later round is the main model with the stage card
(recipes.CARDS). Without a pick, or on any other turn, nothing here runs: the
main model finds and opens the stage with the ordinary tools.

The engine (assistant/engine.py) uses `StageStart` in place of the costume
`workflows.Workflow` for that one turn, through the same four calls: `code_round`,
`stream`, `observe`, `receipt_context`. Like the costume workflow it keeps no state
between turns and never runs a tool itself.
"""
import json
import uuid

from .workflows import one_recolor


def picked_stage(view):
    """The ONE stage the message's context picks, as `stage_lab_open` arguments, else None.

    The panel's stage picker (recipes.LAUNCHABLE `picker: 'stage'`) sends it as the
    only `context.selection` entry, already checked by the blueprint
    (routes/assistant_bp._stage_item):

    * a vault stage variant: {"kind": "stage", "stage": "GrNBa", "id": "<variant id>", "name"};
    * the stock stage: {"kind": "stage", "stage": "GrNBa", "vanilla": true, "name"}.

    -> {'stage_code': 'GrNBa', 'variant_id': '<id>'} | {'stage_code': 'GrNBa'} | None.
    Several entries, a costume, or anything else is None.
    """
    selection = view.get('selection') if isinstance(view, dict) else None
    if not isinstance(selection, list) or len(selection) != 1 or not isinstance(selection[0], dict):
        return None
    item = selection[0]
    stage = item.get('stage')
    if item.get('kind') != 'stage' or not isinstance(stage, str) or not stage.strip():
        return None
    variant = item.get('id')
    if item.get('vanilla') is True:
        return {'stage_code': stage} if variant is None else None
    if isinstance(variant, str) and variant.strip():
        return {'stage_code': stage, 'variant_id': variant}
    return None


def _opened(receipts):
    """True once this chat has a Stage Lab session that opened."""
    return any(isinstance(r, dict) and r.get('name') == 'stage_lab_open' and r.get('status') == 'done'
               and not (r.get('result') or {}).get('error') for r in receipts or ())


class StageStart:
    """Per-turn: code opens the picked stage once, then hands every round to the main model.

    `enrolled` is the engine's half of the rule (engine._stage_enrollment: a chat
    started as "Recolor a stage", a turn about the recolor itself, no card-button
    download, no model file waiting). This half: exactly one picked stage in the
    message (`picked_stage`), no Stage Lab session opened in this chat before, and
    a message that is one recolor to do now rather than a question or a refusal
    (`workflows.one_recolor`, the costume workflow's own exclusions). `name` is
    None when either half says no; the engine then keeps the costume Workflow,
    which does nothing in a stage chat.
    """
    def __init__(self, user_text, receipts=(), *, view=None, main_model, enrolled=False):
        self.main_model = main_model
        picked = picked_stage(view) if enrolled else None
        if picked and (_opened(receipts) or not one_recolor(user_text)):
            picked = None
        self.picked = picked
        self.name = 'recolor_stage' if picked else None
        self.lane = None                # no acquisition lane (routing record)
        self.stage = 'open' if picked else None
        self.opened = False             # the opening has been issued (or found not offered)
        self.opening = None             # the opening call once looked up (False: not offered)
        self.session_id = None
        self.reason = None
        self.requested_by = 'code'
        self.requested_stage = self.stage

    def _opening_call(self, schemas):
        """`stage_lab_open` for the picked stage, or None when this turn does not offer it."""
        if 'stage_lab_open' not in {s['function']['name'] for s in schemas}:
            return None
        return {'id': uuid.uuid4().hex, 'type': 'function',
                'function': {'name': 'stage_lab_open', 'arguments': json.dumps(self.picked)}}

    def code_round(self, schemas):
        """True when the next round is code's own call (opening the picked stage): no model round."""
        if not self.name or self.opened:
            return False
        if self.opening is None:
            self.opening = self._opening_call(schemas) or False
        return bool(self.opening)

    def observe(self, receipt):
        """Advance only from the opening's executed receipt."""
        if not self.name or self.session_id or receipt.get('name') != 'stage_lab_open':
            return
        result = receipt.get('result') or {}
        if receipt.get('status') == 'done' and not result.get('error') and result.get('session_id'):
            self.session_id = result['session_id']
            self.reason = 'stage_opened'
        else:
            self.reason = 'open_failed'
        self.stage = 'create_review'

    def receipt_context(self):
        return ({'workflow': {'name': self.name, 'stage': self.requested_stage,
                              'requested_by': self.requested_by}} if self.name else {})

    def stream(self, messages, schemas, key, cancelled, main):
        if cancelled.is_set():
            return
        self.requested_stage = self.stage
        if self.name and not self.opened:
            self.opened = True
            call = self.opening if self.opening is not None else self._opening_call(schemas)
            if call:
                self.requested_by = 'code'
                yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [call]}}
                return
            self.stage, self.reason = 'create_review', 'open_not_offered'
        self.requested_by = self.main_model
        self.requested_stage = self.stage
        if self.name:
            note = {'workflow': self.name, 'stage': self.stage, 'reason': self.reason,
                    **self.picked, 'session_id': self.session_id}
            outcome = {
                'stage_opened': 'Code opened the picked stage in the Stage Lab: use this session_id and do '
                                'not open it again. Its result already shows the stage, its labelled texture '
                                'sheets and texture rows: edit from them, several textures per recolor call. '
                                'No color, texture, edit or save has been chosen by code. ',
                'open_failed': 'Code could not open the picked stage; its receipt says why. Do not repeat the '
                               'same call: tell the user in one sentence what blocks it. ',
            }.get(self.reason, '')
            messages = [*messages, {'role': 'system', 'content':
                'Code workflow state: ' + json.dumps(note) + '\nContinue the full original user request with '
                'the stage recipe. ' + outcome + 'Code saves the result to the vault when the turn ends.'}]
        yield from main(messages, schemas, key, cancelled)
