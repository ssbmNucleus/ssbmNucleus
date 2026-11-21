"""A retexture goes into the vault by itself when the turn that made it ends: code saves it, never the model.

When a reply turn ends (the model's final words, a stop at the round or cost budget, the user's stop, a newer
message steering in) every Skin Lab or Stage Lab session the turn edited successfully is saved
(`plan`), as the engine's last step (`assistant/engine._autosave`): no model round, no approval. A turn that
made no edit, or whose edits all failed, saves nothing; a session whose bytes are what was last saved (or, before
any save, the source's) saves nothing either.

**One vault item per chat session.** The first save makes a NEW costume or stage variant through the same save a
request makes (`assistant/hsdraw.save_mod_copy`; `shared/rendering/stage_editor.save_copy`): never the source,
never anything that was in the vault before. Later turns on the same session UPDATE that item in place
(`hsdraw.update_mod_copy`, `stage_editor.update_copy`: same id and name, files replaced atomically, portrait and
stock icon or screenshot made again). Which item a session owns is read from the chat's own receipts (`_history`:
server-owned, kept in chats.db, so it survives a session resume and an app restart): the newest successful save of
that session, automatic or asked for. "Save this as a new one" is the model's save_mod_copy / stage_lab save, and
from then on the auto-save updates that newer item. The item itself must say it was made in this chat
(`randall_chat`, written by both saves); an item that is gone, or says otherwise, is never touched: a new one is
made instead.

**Naming.** The model may name the result in its edit call (`name` on skin_lab / stage_lab apply); otherwise
"<fighter or stage> - <a few words of the request>" (`fallback_name`). An update keeps the item's own name.

**Failure.** A save that fails (paired Ice Climbers, a disk error, a working copy that cannot be reopened) gives a
failed receipt with one plain sentence (`assistant/refusals.not_saved`), which the engine also adds to the reply;
the session and its edits stay as they are, and the next turn tries again (`retry`; a refusal no retry can get
past, such as the climbers, waits for the next edit).

What the receipts carry: the receipt is the one a manual save makes (`save_mod_copy` with `file_id` and `name`;
`stage_lab` with `action: save`), so the cards, "Put it in my game" and "Start another" read it as a save
(frontend `taskModes.js`); its result adds `autosave` ('saved' or 'updated') for the card. The bookkeeping is on
the receipt, never in what the model reads: `auto_save` {session_id, kind, mode, sha256 of the bytes saved,
retry, seconds}.
"""
import hashlib
import logging
import re
import time

log = logging.getLogger(__name__)

COSTUME, STAGE = 'costume', 'stage'
TOOL = {COSTUME: 'save_mod_copy', STAGE: 'stage_lab'}
NAME_MAX = {COSTUME: 80, STAGE: 120}
WORKING = {COSTUME: ('Saving the costume to your vault', 'Updating the costume in your vault'),
           STAGE: ('Saving the stage to your vault', 'Updating the stage in your vault')}

# Words a request uses that say nothing about the look (a fallback name keeps the rest).
_FILLER = frozenset('''
a an the it its it's this that these those me my mine you your yours please can could would will should shall
make made making turn turned give change changed changing recolor recolour recolored recoloured retexture
retextured texture textures colour color colours colors coloured colored theme themed themes version style styled
look looks looking like into in on of off to for from with and or but so all whole entire some more less bit
little just be is are was were now also too then i i'm want wanna need let lets let's us do does did use using new
edition alt alternate skin skins costume costumes stage stages outfit him her them they he she paint painted hey
hi ok okay yes yeah go ahead instead same one again same thing something kind sort very really slightly bit
'''.split())


# ------------------------------------------------------------------ what the chat's receipts say

def _args(receipt):
    args = receipt.get('arguments')
    return args if isinstance(args, dict) else {}


def _result(receipt):
    result = receipt.get('result')
    return result if isinstance(result, dict) else {}


def _sid(receipt):
    return _result(receipt).get('session_id') or _args(receipt).get('session_id')


def edit_kind(name, args, result, status='done'):
    """COSTUME or STAGE for a lab edit that succeeded (a checkpointed edit: continuity's action sets), else None."""
    from randall.assistant.continuity import EDIT_ACTIONS, STAGE_EDIT_ACTIONS
    if status != 'done' or not isinstance(result, dict) or result.get('error'):
        return None
    action = (args or {}).get('action')
    if name == 'skin_lab' and action in EDIT_ACTIONS:
        return COSTUME
    if name == 'stage_lab' and action in STAGE_EDIT_ACTIONS:
        return STAGE
    if name == 'skin_material' and action in ('apply', 'reset'):
        if result.get('stage_target'):
            return STAGE
        from .lab_common import is_stage
        return STAGE if is_stage(result.get('session_id') or (args or {}).get('session_id')) else COSTUME
    return None


def _save_record(receipt, exported):
    """(session id, {kind, id, character|folder, name, sha256}) for a successful save of a lab result, else None.
    A manual save_mod_copy belongs to the session whose export or checkpoint it saved (`exported`)."""
    if receipt.get('status') != 'done':
        return None
    result, args, marker = _result(receipt), _args(receipt), receipt.get('auto_save') or {}
    if result.get('error'):
        return None
    if receipt.get('name') == 'stage_lab' and result.get('variantId') and (args.get('action') == 'save' or marker):
        return (marker.get('session_id') or args.get('session_id'),
                {'kind': STAGE, 'id': result['variantId'], 'folder': result.get('folder'), 'name': result.get('name'),
                 'sha256': marker.get('sha256')})
    items = result.get('items')
    if receipt.get('name') == 'save_mod_copy' and isinstance(items, list) and items and isinstance(items[0], dict):
        return (marker.get('session_id') or exported.get(args.get('file_id')),
                {'kind': COSTUME, 'id': items[0].get('id'), 'character': items[0].get('character'),
                 'name': items[0].get('name'), 'sha256': marker.get('sha256')})
    return None


def _history(receipts):
    """Per lab session: {kind, edited: index of its last successful edit, saved: (index, record) of its newest
    successful save, attempt: (index, receipt) of its newest auto-save}."""
    exported, state = {}, {}
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict):
            continue
        sid, result, name = _sid(receipt), _result(receipt), receipt.get('name')
        if sid and name in ('skin_lab', 'skin_material', 'skin_lab_open'):
            checkpoint = result.get('checkpoint_file')
            if isinstance(checkpoint, dict) and checkpoint.get('file_id'):
                exported[checkpoint['file_id']] = sid
            if _args(receipt).get('action') == 'export':
                for file in result.get('files') or []:
                    if isinstance(file, dict) and file.get('file_id'):
                        exported[file['file_id']] = sid
        if receipt.get('auto_save'):
            marker = receipt['auto_save']
            if marker.get('session_id'):
                state.setdefault(marker['session_id'], {'kind': marker.get('kind')})['attempt'] = (index, receipt)
        kind = None if receipt.get('auto_save') else edit_kind(name, _args(receipt), result, receipt.get('status'))
        if kind and sid:
            state.setdefault(sid, {'kind': kind}).update(kind=kind, edited=index)
        saved = _save_record(receipt, exported)
        if saved and saved[0]:
            state.setdefault(saved[0], {'kind': saved[1]['kind']})['saved'] = (index, saved[1])
    return state


def plan(earlier, turn):
    """[(kind, session id)] to save as this turn ends, in the order the turn first edited them: every session this
    turn edited, and every session whose last auto-save failed after its last edit and may be retried. Not one
    that was saved after its last edit (a save the user asked for in this turn)."""
    earlier, turn = list(earlier or []), list(turn or [])
    start, chosen = len(earlier), []
    for sid, entry in _history(earlier + turn).items():
        edited = entry.get('edited')
        if edited is None or (entry.get('saved') or (-1,))[0] > edited:
            continue
        attempt = entry.get('attempt')
        retry = bool(attempt and attempt[0] > edited and attempt[1].get('status') == 'error'
                     and (attempt[1].get('auto_save') or {}).get('retry'))
        if edited >= start or retry:
            chosen.append((edited, entry['kind'], sid))
    return [(kind, sid) for _, kind, sid in sorted(chosen)]


def owned(receipts, sid):
    """The record of the newest successful save of this session in this chat, or None."""
    saved = _history(receipts).get(sid, {}).get('saved')
    return saved[1] if saved else None


def _vault_entry(record, chat_id):
    """The vault entry `record` names when it is still there and was made in this chat, else None."""
    from core.metadata import load_metadata
    if not record or not chat_id:
        return None
    data = load_metadata(default={})
    if record['kind'] == COSTUME:
        rows = data.get('characters', {}).get(record.get('character'), {}).get('skins', [])
    else:
        rows = data.get('stages', {}).get(record.get('folder'), {}).get('variants', [])
    found = next((row for row in rows if isinstance(row, dict) and row.get('id') == record.get('id')), None)
    return found if found is not None and found.get('randall_chat') == chat_id else None


# ------------------------------------------------------------------ naming

def _clean(name, kind):
    name = re.sub(r'\s+', ' ', str(name or '')).strip()
    return name[:NAME_MAX[kind]].strip() or None


def model_name(receipts, sid, kind):
    """The newest name the model gave this session's result (`name` on a lab edit call), or None."""
    for receipt in reversed(receipts or []):
        if isinstance(receipt, dict) and receipt.get('name') in ('skin_lab', 'stage_lab') and _sid(receipt) == sid:
            args = _args(receipt)
            if args.get('action') != 'save' and isinstance(args.get('name'), str):
                name = _clean(args['name'], kind)
                if name:
                    return name
    return None


def planned_name(receipts, sid, kind, label, texts):
    """The name a new item of this session gets: the model's, else the one an earlier auto-save of it tried (a
    retry keeps its name), else the fallback from the request."""
    attempt = _history(receipts).get(sid, {}).get('attempt')
    tried = _clean(_args(attempt[1]).get('name'), kind) if attempt else None
    return model_name(receipts, sid, kind) or tried or fallback_name(label, texts, kind)


def title(text, source=''):
    """A few words of the request that say what the look is ("make dream land candy themed" -> "Candy")."""
    squashed = re.sub(r'[^a-z0-9]', '', (source or '').lower())
    words = []
    for word in re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text or ''):
        lower = word.lower()
        if lower in _FILLER or (len(lower) >= 3 and lower in squashed) or len(word) > 20:
            continue
        words.append(word if word.isupper() and len(word) > 1 else word.capitalize())
        if len(words) == 3:
            break
    return ' '.join(words)


def fallback_name(source, texts, kind):
    """"<source> - <title>" from the first of `texts` (this turn's request, then the chat's first) with one."""
    for text in texts or ():
        found = title(text, source)
        if found:
            return _clean(f'{source} - {found}', kind)
    return _clean(f'{source} - Retexture', kind)


# ------------------------------------------------------------------ the session's current result

def _source_label(kind, item):
    if kind == COSTUME:
        from shared.mod_files import origin_of
        return origin_of(item.get('source') or {}).get('character') or 'Costume'
    from core.stages import ALL_STAGES
    code = (item.get('source') or {}).get('stage_code')
    return (ALL_STAGES.get(code) or {}).get('name') or code or 'Stage'


def _snapshot(kind, sid):
    """The session's result now: {data, sha256, source_sha256, label, origin, name, screenshot}. A closed session
    reopens from its workspace (lab_common.live); ValueError when it cannot."""
    from . import skin_lab, stage_lab
    module = skin_lab if kind == COSTUME else stage_lab
    with module._lock:
        item = module._session(sid)
        viewer = item['viewer']
        screenshot = viewer.grab_frame() if kind == STAGE else None
        data = viewer.export_dat()
        source = item.get('source') or {}
        snapshot = {'data': data, 'sha256': hashlib.sha256(data).hexdigest(), 'label': _source_label(kind, item),
                    'origin': source.get('origin'), 'name': source.get('name'), 'screenshot': screenshot,
                    'source_sha256': item.get('source_sha256') if kind == COSTUME else source.get('sha256')}
    return snapshot


def refusal(sid):
    """Why this costume session's result cannot be saved at all (hsdraw.save_refusal: paired climbers, a file with
    no costume of its own), or None. A stage is always saveable."""
    from . import skin_lab
    from randall.assistant.hsdraw import save_refusal
    with skin_lab._lock:
        item = skin_lab._sessions.get(sid)
        origin = (item.get('source') or {}).get('origin') if item else None
    if item is None:
        return None
    return save_refusal({'edited': True, 'origin': origin})


def note(name, args, result, receipts, texts, chat_id=None):
    """The line a successful lab edit's result gets for the model: what code will save, and under which name,
    when the turn ends (`vault`). None for anything else."""
    kind = edit_kind(name, args, result)
    sid = (result or {}).get('session_id') or (args or {}).get('session_id')
    if not kind or not sid:
        return None
    if kind == COSTUME:
        refused = refusal(sid)
        if refused:
            return f'This costume cannot be saved to the vault ({refused}); say so in your reply.'
    record = owned(receipts, sid)
    what = 'costume' if kind == COSTUME else 'stage variant'
    if record and record.get('name'):
        return (f'When this turn ends, code updates the {what} "{record["name"]}" in the user\'s vault with the '
                'result. Do not offer to save it.')
    given = (_clean((args or {}).get('name'), kind) if isinstance((args or {}).get('name'), str) else None)
    name_now = given
    if not name_now:
        from . import skin_lab, stage_lab
        module = skin_lab if kind == COSTUME else stage_lab
        with module._lock:
            item = module._sessions.get(sid)
            label = _source_label(kind, item) if item else ('Costume' if kind == COSTUME else 'Stage')
        name_now = planned_name(receipts, sid, kind, label, texts)
    return (f'When this turn ends, code saves the result to the user\'s vault as the new {what} "{name_now}" '
            '(name it with `name` on apply). Do not offer to save it.')


# ------------------------------------------------------------------ the save

class Save:
    """One session's save at the end of a turn: `prepare` reads the session (fast), `run` writes the vault (a
    costume renders its portrait: seconds). `arguments` and `working` are the receipt's while it runs."""

    def __init__(self, chat_id, kind, sid, receipts, texts):
        self.chat_id, self.kind, self.sid = chat_id, kind, sid
        self.receipts, self.texts = list(receipts or []), list(texts or [])
        self.failure = None          # (reason, retry) known before the save runs
        self.snapshot = self.file = self.entry = None
        self.record = owned(self.receipts, sid)
        self.mode, self.name = 'saved', None

    def prepare(self):
        """False when there is nothing new to save (the bytes are those last saved, or the source's)."""
        try:
            self.snapshot = _snapshot(self.kind, self.sid)
        except ValueError as exc:
            log.info('auto-save: session %s cannot be read: %s', self.sid, exc)
            self.failure = ('its working copy has closed and cannot be reopened', False)
            return True
        except Exception:
            log.exception('auto-save: session %s could not be exported', self.sid)
            self.failure = ('the edited file could not be read from the renderer', True)
            return True
        sha = self.snapshot['sha256']
        if self.record and self.record.get('sha256') == sha:
            return False
        if not self.record and sha == self.snapshot.get('source_sha256'):
            return False
        try:
            self.entry = _vault_entry(self.record, self.chat_id)
        except Exception:
            log.warning('auto-save: vault metadata unreadable', exc_info=True)
            self.entry = None
        if self.entry is not None:
            self.mode = 'updated'
            self.name = _clean(self.entry.get('name') or self.entry.get('color') or self.record.get('name'), self.kind)
        self.name = self.name or planned_name(self.receipts, self.sid, self.kind, self.snapshot['label'], self.texts)
        if self.kind == COSTUME:
            from shared import mod_files
            from randall.assistant.hsdraw import save_refusal
            refused = save_refusal({'edited': True, 'origin': self.snapshot['origin']})
            try:
                self.file = mod_files.register(self.snapshot['data'], self.snapshot['name'] or 'costume.dat',
                                               origin=self.snapshot['origin'], edited=True)
            except Exception:
                log.exception('auto-save: export not registered')
                self.failure = ('the edited file could not be written', True)
                return True
            if refused:
                self.failure = (refused, False)
        return True

    @property
    def arguments(self):
        if self.kind == COSTUME:
            return {'file_id': (self.file or {}).get('file_id'), 'name': self.name}
        return {'session_id': self.sid, 'action': 'save', 'name': self.name}

    @property
    def working(self):
        return WORKING[self.kind][self.mode == 'updated']

    def run(self):
        """-> (result, marker): the receipt's result, as a manual save's plus `autosave`, and its `auto_save`."""
        started = time.perf_counter()
        marker = {'session_id': self.sid, 'kind': self.kind, 'mode': self.mode,
                  'sha256': (self.snapshot or {}).get('sha256')}
        if self.failure is None:
            try:
                result = self._write()
            except ValueError as exc:
                self.failure = (str(exc), True)
            except Exception as exc:
                log.exception('auto-save of %s %s failed', self.kind, self.sid)
                self.failure = (f'the vault could not be written ({type(exc).__name__})', True)
        if self.failure is not None:
            from randall.assistant import refusals
            reason, retry = self.failure
            result = refusals.not_saved(self.kind, reason, retry=retry)
            if self.file:
                result['files'] = [self.file]        # the edited costume, still downloadable from the card
            marker.update(mode='failed', retry=retry)
        else:
            result.update(autosave=self.mode, session_id=self.sid, note=self._note(result))
        marker['seconds'] = round(time.perf_counter() - started, 2)
        return result, marker

    def _write(self):
        if self.kind == COSTUME:
            from randall.assistant import hsdraw
            if self.mode == 'updated':
                return hsdraw.update_mod_copy(self.file['file_id'], self.record['character'], self.record['id'],
                                              self.chat_id)
            return hsdraw.save_mod_copy(self.file['file_id'], self.name, chat_id=self.chat_id)
        from shared.rendering import stage_editor
        from .lab_common import image_file
        shot, data = self.snapshot['screenshot'], self.snapshot['data']
        if self.mode == 'updated':
            result = stage_editor.update_copy(self.sid, data, self.record['id'], shot, chat_id=self.chat_id)
            result['files'] = [image_file(shot, 'Updated in vault.png')] if shot else []
        else:
            result = stage_editor.save_copy(self.sid, data, self.name, shot, chat_id=self.chat_id)
            result['files'] = [image_file(shot, 'Added to vault.png')] if shot else []
        return result

    def _note(self, result):
        what = 'costume' if self.kind == COSTUME else 'stage variant'
        name = self.name
        if self.kind == COSTUME and (result.get('items') or [{}])[0].get('name'):
            name = result['items'][0]['name']
        elif self.kind == STAGE and result.get('name'):
            name = result['name']
        if self.mode == 'updated':
            return (f'Updated automatically when the turn ended: the {what} "{name}" in the vault now has this result '
                    '(same item, new files). Later turns on this session update it again.')
        return (f'Saved automatically when the turn ended, as the new {what} "{name}" in the vault (the source was not '
                'changed). Later turns on this session update this same item.')
