"""A retexture is saved to the vault by code when the turn that made it ends (randall/recolor/autosave.py).

No model request runs and no renderer starts: the provider is a script of tool calls and a final reply, the
labs' sessions are fake renderers whose exported file changes with each edit, and the costume importer (its
portrait render and Slippi check) is a stand-in that writes the same files and vault entry the real one does.
The vault writes around it (the new item, the update in place, the ownership marker) are the real code.
"""
import hashlib
import io
import json
import re
import struct
import time
import uuid
import zipfile

import pytest
from PIL import Image

from core import config
from core.metadata import load_metadata, metadata_transaction
from shared.aiengine import decisions
from shared.rendering import stage_editor
from randall.assistant import engine, hsdraw, live_runs, refusals, store, tools
from shared import mod_files
from randall.recolor import autosave, stage_lab, skin_lab


def dat(value=0):
    """A minimal stage DAT (a `map_head` root) whose body is `value`."""
    body = bytes([value]) * 32
    name = b'map_head\0'
    return struct.pack('>5I', 32 + len(body) + 8 + len(name), len(body), 0, 1, 0) + bytes(12) + body + \
        struct.pack('>2I', 0, 0) + name


def png(value=0):
    out = io.BytesIO()
    Image.new('RGB', (8, 8), (value * 40 % 256, 20, 30)).save(out, format='PNG')
    return out.getvalue()


class Viewer:
    """A lab renderer: every edit changes what it exports."""
    textures = [{'index': 0, 'name': 'Group 0 / Texture 0', 'width': 8, 'height': 8}]

    def __init__(self, kind, value=0):
        self.kind, self.value = kind, value

    def alive(self):
        return True

    def export_dat(self):
        return dat(self.value) if self.kind == 'stage' else b'COSTUME' + bytes([self.value]) * 64

    def grab_frame(self):
        return png(self.value)

    def get_full_texture(self, index):
        return png(self.value)

    def material_command(self, command):
        return {'materials': []}

    def close(self):
        pass


# ------------------------------------------------------------------ the chat

@pytest.fixture
def chat(vault, monkeypatch):
    """Run turns against a scripted provider. `say(rounds, text, chat_id=None)` -> (run, provider messages).
    Each round is a reply text, or (tool, arguments) for one call."""
    from randall.assistant.tasks import coordinator, store as taskstore
    taskstore.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    monkeypatch.setattr(tools, 'vanilla_assets_ready', lambda: False)

    def say(rounds, text, chat_id=None, context=None):
        queue, seen = list(rounds), []

        def provider(messages, schemas, key, cancelled, *args, **kwargs):
            seen.append(list(messages))
            step = queue.pop(0) if queue else 'Done.'
            if callable(step):
                step = step(cancelled)
            if isinstance(step, str):
                yield {'type': 'delta', 'content': step}
                yield {'type': 'completion', 'finish_reason': 'stop',
                       'message': {'role': 'assistant', 'content': step}}
                return
            name, arguments = step
            yield {'type': 'completion', 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': uuid.uuid4().hex, 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}
        monkeypatch.setattr(engine, '_provider', provider)
        run = engine.start(chat_id, text, context or {}, request_key='k')
        list(live_runs.stream(run))
        return run, seen
    return say


def saves(run):
    return [r for r in run.answer['tools'] if r.get('auto_save')]


def tool_results(seen):
    return [json.loads(m['content']) for messages in seen for m in messages if m.get('role') == 'tool']


# ------------------------------------------------------------------ a stage session

@pytest.fixture
def stage(vault, monkeypatch):
    """A Stage Lab session on the vault variant `source` of Dreamland (a stand-in renderer), and the Stage Lab
    tool with `apply` stood in: each apply changes the exported stage; a failing one raises as the batch does."""
    folder = config.STORAGE_PATH / 'das' / 'dreamland'
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / 'source.zip', 'w') as archive:
        archive.writestr('GrOp-custom.dat', dat())
        archive.writestr('companion.bin', b'untouched')
    with metadata_transaction(default={}) as metadata:
        metadata.setdefault('stages', {})['dreamland'] = {'variants': [
            {'id': 'source', 'name': 'Source', 'filename': 'source.zip', 'has_screenshot': False}]}
    workspace = stage_editor.open_stage('GrOp', 'source')
    sid = workspace['id']
    viewer = Viewer('stage')
    stage_lab._sessions[sid] = {'viewer': viewer, 'source': workspace, 'used': time.monotonic(), 'kind': 'stage'}
    real = stage_lab.stage_lab

    def lab(session_id, action, edits=None, name=None, chat_id=None, **rest):
        if action == 'apply':
            if edits == [{'kind': 'recolor', 'texture_index': 99}]:
                raise ValueError('No edit applied: texture 99 is not a live texture.')
            with stage_lab._lock:
                stage_lab._session(session_id)['viewer'].value += 1      # a closed session reopens first
            return {'applied': [0], 'failed': [], 'changed_textures': [0], 'files': []}
        return real(session_id, action, name=name, chat_id=chat_id, **rest)
    monkeypatch.setitem(tools.REGISTRY, 'stage_lab', tools.ToolSpec('automatic', lab))
    yield sid, viewer, folder
    stage_lab._sessions.pop(sid, None)


def apply(sid, hue=300, **extra):
    return ('stage_lab', {'session_id': sid, 'action': 'apply',
                          'edits': [{'kind': 'recolor', 'texture_index': 0, 'set_hue': hue}], **extra})


def variants():
    return load_metadata(default={}).get('stages', {}).get('dreamland', {}).get('variants', [])


def test_a_stage_turn_saves_a_new_variant_then_the_next_turn_updates_that_same_one(chat, stage):
    sid, viewer, folder = stage
    run, seen = chat([apply(sid, name='Dreamland - Candy'), 'Your candy Dreamland is in your vault.'],
                     'make dream land candy themed')
    assert run.answer['status'] == 'done'
    # The model was told, on its edit, what code saves and under which name.
    assert 'saves the result to the user\'s vault as the new stage variant "Dreamland - Candy"' in \
        tool_results(seen)[0]['vault']
    [receipt] = saves(run)
    assert receipt['name'] == 'stage_lab' and receipt['status'] == 'done'
    assert receipt['arguments'] == {'session_id': sid, 'action': 'save', 'name': 'Dreamland - Candy'}
    result = receipt['result']
    assert result['autosave'] == 'saved' and result['vault_changed'] and result['name'] == 'Dreamland - Candy'
    assert result['files'][0]['extension'] == '.png'                  # the card's picture: the screenshot
    # The card sits after the reply's words: they were on screen before the save ran.
    assert receipt['content_offset'] == len(run.answer['content'])
    new = [v for v in variants() if v['id'] != 'source']
    assert len(new) == 1 and new[0]['id'] == result['variantId'] and new[0]['randall_chat'] == run.chat_id
    assert new[0]['has_screenshot'] and (folder / new[0]['screenshot_filename']).is_file()
    with zipfile.ZipFile(folder / new[0]['filename']) as archive:
        assert archive.read('GrOp-custom.dat') == dat(1) and archive.read('companion.bin') == b'untouched'
    first_shot = (folder / new[0]['screenshot_filename']).read_bytes()

    again, seen = chat([apply(sid), 'Darker now.'], 'make the tree darker', chat_id=run.chat_id)
    assert 'updates the stage variant "Dreamland - Candy"' in tool_results(seen)[0]['vault']
    [receipt] = saves(again)
    assert receipt['result']['autosave'] == 'updated' and receipt['result']['variantId'] == new[0]['id']
    after = [v for v in variants() if v['id'] != 'source']
    assert [v['id'] for v in after] == [new[0]['id']], 'one item per chat session'
    assert after[0]['name'] == 'Dreamland - Candy' and after[0].get('date_modified')
    with zipfile.ZipFile(folder / after[0]['filename']) as archive:
        assert archive.read('GrOp-custom.dat') == dat(2) and archive.read('companion.bin') == b'untouched'
    assert (folder / after[0]['screenshot_filename']).read_bytes() != first_shot
    assert sorted(p.name for p in folder.glob('*.zip')) == sorted(['source.zip', after[0]['filename']])
    assert not list(folder.glob('*.part'))
    # The source variant is as it was.
    with zipfile.ZipFile(folder / 'source.zip') as archive:
        assert archive.read('GrOp-custom.dat') == dat()


def test_a_turn_that_edited_nothing_or_whose_edits_all_failed_saves_nothing(chat, stage):
    sid, viewer, folder = stage
    run, _ = chat(['Dreamland has a tree, platforms and a sky.'], 'what is on this stage?')
    assert not saves(run)
    failed, _ = chat([('stage_lab', {'session_id': sid, 'action': 'apply',
                                     'edits': [{'kind': 'recolor', 'texture_index': 99}]}), 'That did not work.'],
                     'make it purple', chat_id=run.chat_id)
    assert failed.answer['tools'][0]['status'] == 'error' and not saves(failed)
    looked, _ = chat([('stage_lab', {'session_id': sid, 'action': 'frame'}), 'Here it is.'], 'show me',
                     chat_id=run.chat_id)
    assert not saves(looked)
    assert [v['id'] for v in variants()] == ['source']


def test_an_asked_for_separate_copy_is_kept_and_auto_save_updates_the_newest(chat, stage):
    sid, viewer, folder = stage
    first, _ = chat([apply(sid, name='Dreamland - Candy'), 'Saved.'], 'make it candy')
    candy = saves(first)[0]['result']['variantId']
    # "Keep both: save this as a new one": the model's own save, after the edit; code adds no second save.
    second, _ = chat([apply(sid), ('stage_lab', {'session_id': sid, 'action': 'save', 'name': 'Dreamland - Night'}),
                      'Both are in your vault.'], 'make it night, and keep both', chat_id=first.chat_id)
    assert not saves(second)
    night = second.answer['tools'][1]['result']['variantId']
    assert night != candy and {v['id'] for v in variants()} == {'source', candy, night}
    assert next(v for v in variants() if v['id'] == night)['randall_chat'] == first.chat_id
    third, _ = chat([apply(sid), 'Brighter.'], 'brighter', chat_id=first.chat_id)
    [receipt] = saves(third)
    assert receipt['result']['autosave'] == 'updated' and receipt['result']['variantId'] == night
    with zipfile.ZipFile(folder / f'{candy}.zip') as archive:
        assert archive.read('GrOp-custom.dat') == dat(1), 'the earlier copy is left as it was'
    with zipfile.ZipFile(folder / f'{night}.zip') as archive:
        assert archive.read('GrOp-custom.dat') == dat(3)


def test_auto_save_never_updates_an_item_this_chat_did_not_make(chat, stage):
    sid, viewer, folder = stage
    # A variant that was in the vault before, which an old (or forged) receipt of this chat claims was saved
    # from this session: it carries no mark of this chat, so it is never touched.
    (folder / 'older.zip').write_bytes(b'older archive')
    with metadata_transaction(default={}) as metadata:
        metadata['stages']['dreamland']['variants'].append(
            {'id': 'older', 'name': 'Older', 'filename': 'older.zip', 'randall_chat': 'another-chat'})
    claimed = {'id': uuid.uuid4().hex, 'name': 'stage_lab', 'status': 'done',
               'arguments': {'session_id': sid, 'action': 'save', 'name': 'Older'},
               'result': {'variantId': 'older', 'folder': 'dreamland', 'name': 'Older', 'vault_changed': True}}
    chat_id = store.save(None, [{'role': 'user', 'content': 'make it gold', 'context': {}},
                                {'role': 'assistant', 'content': 'Saved.', 'tools': [claimed], 'status': 'done'}])
    run, _ = chat([apply(sid), 'Gold.'], 'more gold', chat_id=chat_id)
    [receipt] = saves(run)
    assert receipt['result']['autosave'] == 'saved' and receipt['result']['variantId'] not in ('older', 'source')
    assert (folder / 'older.zip').read_bytes() == b'older archive'
    assert next(v for v in variants() if v['id'] == 'older') == {
        'id': 'older', 'name': 'Older', 'filename': 'older.zip', 'randall_chat': 'another-chat'}
    with pytest.raises(ValueError, match='not made in this chat'):
        stage_editor.update_copy(sid, dat(9), 'older', png(), chat_id=chat_id)
    with pytest.raises(ValueError, match='not made in this chat'):
        stage_editor.update_copy(sid, dat(9), 'source', png(), chat_id=chat_id)
    assert (folder / 'older.zip').read_bytes() == b'older archive'


def test_ownership_survives_a_session_resume_and_an_app_restart(chat, stage, monkeypatch):
    sid, viewer, folder = stage
    first, _ = chat([apply(sid, name='Dreamland - Candy'), 'Saved.'], 'make it candy')
    variant = saves(first)[0]['result']['variantId']
    # The app restarts: the live session is gone and reopens from its workspace under the same id; the chat's
    # receipts are read back from chats.db.
    stage_lab._sessions.pop(sid)
    assert (folder.parent.parent / 'stage_editor' / sid / 'resume.json').is_file()
    reopened = Viewer('stage', value=viewer.value)
    workspace = stage_editor.resolve(sid)[1]
    monkeypatch.setattr(stage_lab, '_resume', lambda session_id, directory, record: {
        'viewer': reopened, 'source': {**workspace, 'datFile': str(directory / 'source.dat')}, 'kind': 'stage'})
    stored = [t for m in store.get(first.chat_id)['messages'] for t in m.get('tools', [])]
    assert autosave.owned(stored, sid)['id'] == variant
    again, _ = chat([apply(sid), 'Darker.'], 'darker', chat_id=first.chat_id)
    [receipt] = saves(again)
    assert receipt['result']['autosave'] == 'updated' and receipt['result']['variantId'] == variant
    assert stage_lab._sessions[sid]['resumed']
    with zipfile.ZipFile(folder / f'{variant}.zip') as archive:
        assert archive.read('GrOp-custom.dat') == dat(2)


def test_a_turn_stopped_by_its_budget_or_by_the_user_still_saves_its_completed_edits(chat, stage, monkeypatch):
    sid, viewer, folder = stage
    monkeypatch.setattr(engine, 'SKIN_MAX_ROUNDS', 3)
    monkeypatch.setattr(engine, 'SKIN_WRAP_UP', 2)
    # A stage job: the turn opens the chat's first Stage Lab session itself (budgeted from then on).
    monkeypatch.setitem(tools.REGISTRY, 'stage_lab_open', tools.ToolSpec(
        'automatic', lambda stage_code, variant_id=None: {'session_id': sid, 'stage': stage_code, 'textures': []}))
    run, _ = chat([('stage_lab_open', {'stage_code': 'GrOp', 'variant_id': 'source'})]
                  + [apply(sid, hue) for hue in range(10, 110, 10)], 'make it lava')
    assert run.answer['stop_reason'] == 'round_budget' and run.answer['status'] == 'error'
    [receipt] = saves(run)
    assert receipt['status'] == 'done' and receipt['result']['autosave'] == 'saved'

    def stop(cancelled):
        cancelled.run.cancelled.set()          # the user presses Stop while the next round is being asked for
        return apply(sid, 200)
    stopped, _ = chat([apply(sid, 190), stop], 'more lava', chat_id=run.chat_id)
    assert stopped.answer['status'] == 'cancelled'
    [receipt] = saves(stopped)
    assert receipt['result']['autosave'] == 'updated'
    assert len([v for v in variants() if v['id'] != 'source']) == 1


# ------------------------------------------------------------------ a costume session

@pytest.fixture
def costume(vault, monkeypatch):
    """A Skin Lab session on stock Fox (a stand-in renderer), the Skin Lab's apply stood in, and the vault's
    costume importer stood in by one that writes the archive, portrait, stock icon and entry it would."""
    origin = {'character': 'Fox', 'vanilla_color': 'Nr', 'costume_code': 'PlFxNr'}
    source = b'COSTUME' + bytes(64)
    _, info = mod_files.resolve(mod_files.register(source, 'PlFxNr.dat', origin=origin)['file_id'])
    sid = uuid.uuid4().hex
    viewer = Viewer('costume')
    skin_lab._sessions[sid] = {'viewer': viewer, 'source': info, 'used': time.monotonic(), 'edited': False,
                               'palette': None, 'source_sha256': hashlib.sha256(source).hexdigest()}
    imported, failures = [], []

    def import_copy(path, origin, name):
        if failures:
            raise failures.pop(0)
        data = path.read_bytes()
        folder = config.STORAGE_PATH / origin['character']
        folder.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        with metadata_transaction(default={}) as metadata:
            skins = metadata.setdefault('characters', {}).setdefault(origin['character'], {}).setdefault('skins', [])
            skin_id = f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}-{uuid.uuid4().hex[:6]}"
            (folder / f'{skin_id}.zip').write_bytes(data)
            (folder / f'{skin_id}_csp.png').write_bytes(b'csp of ' + digest.encode())
            (folder / f'{skin_id}_stc.png').write_bytes(b'stock of ' + digest.encode())
            skins.append({'id': skin_id, 'color': name, 'costume_code': origin['costume_code'],
                          'filename': f'{skin_id}.zip', 'has_csp': True, 'has_stock': True, 'dat_hash': digest,
                          'slippi_safe': True, 'slippi_tested': True, 'date_added': 'now'})
        imported.append(name)
        return skin_id, None
    monkeypatch.setattr(hsdraw, '_import_copy', import_copy)
    real = skin_lab.skin_lab

    def lab(session_id, action, edits=None, name=None, **rest):
        item = skin_lab._sessions[session_id]
        if action == 'apply':
            item['viewer'].value += 1
            item['edited'] = True
            return {'applied': [0], 'failed': [], 'files': []}
        return real(session_id, action, **rest)
    monkeypatch.setitem(tools.REGISTRY, 'skin_lab', tools.ToolSpec('automatic', lab))
    yield sid, viewer, imported, failures
    skin_lab._sessions.pop(sid, None)


def skin_apply(sid, **extra):
    return ('skin_lab', {'session_id': sid, 'action': 'apply',
                         'edits': [{'kind': 'recolor', 'texture_index': 0, 'set_hue': 20}], **extra})


def fox():
    return load_metadata(default={}).get('characters', {}).get('Fox', {}).get('skins', [])


def test_a_costume_turn_saves_a_new_costume_with_its_portrait_and_the_next_updates_it(chat, costume):
    sid, viewer, imported, _ = costume
    run, seen = chat([skin_apply(sid), 'It is in your vault as Fox - Lava.'], 'make fox lava')
    assert 'as the new costume "Fox - Lava"' in tool_results(seen)[0]['vault']
    [receipt] = saves(run)
    assert receipt['name'] == 'save_mod_copy' and receipt['status'] == 'done'
    assert receipt['arguments']['name'] == 'Fox - Lava'
    exported = mod_files.resolve(receipt['arguments']['file_id'])[0].read_bytes()
    assert exported == b'COSTUME' + bytes([1]) * 64
    [item] = receipt['result']['items']
    assert receipt['result']['autosave'] == 'saved' and item['character'] == 'Fox' and item['name'] == 'Fox - Lava'
    assert item['image'].endswith(f"{item['id']}_csp.png")                 # the portrait, as a save makes it
    [skin] = fox()
    assert skin['id'] == item['id'] and skin['randall_chat'] == run.chat_id and skin['name'] == 'Fox - Lava'
    folder = config.STORAGE_PATH / 'Fox'
    portrait = (folder / f"{skin['id']}_csp.png").read_bytes()

    again, _ = chat([skin_apply(sid), 'Hotter now.'], 'make it hotter', chat_id=run.chat_id)
    [receipt] = saves(again)
    assert receipt['result']['autosave'] == 'updated'
    [updated] = fox()
    assert updated['id'] == skin['id'] and updated['name'] == 'Fox - Lava' and updated['date_modified']
    assert updated['dat_hash'] != skin['dat_hash'] and updated['randall_chat'] == run.chat_id
    assert (folder / f"{skin['id']}.zip").read_bytes() == b'COSTUME' + bytes([2]) * 64
    assert (folder / f"{skin['id']}_csp.png").read_bytes() != portrait, 'the portrait is made again'
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [f"{skin['id']}.zip", f"{skin['id']}_csp.png", f"{skin['id']}_stc.png"]), 'no throwaway import is left'
    assert '?v=' in receipt['result']['items'][0]['image']
    assert len(imported) == 2


def test_an_asked_for_costume_copy_becomes_the_one_auto_save_updates(chat, costume):
    sid, viewer, imported, _ = costume
    first, _ = chat([skin_apply(sid, name='Fox - Lava'), 'Saved.'], 'make fox lava')
    lava = saves(first)[0]['result']['items'][0]['id']

    def save_the_export(cancelled):
        export = next(r for r in reversed(cancelled.run.answer['tools']) if r['name'] == 'skin_lab')
        return ('save_mod_copy', {'file_id': export['result']['files'][0]['file_id'], 'name': 'Fox - Ice'})
    # "Keep both": the model exports and saves a copy itself, after the edit; code adds no second save.
    second, _ = chat([skin_apply(sid), ('skin_lab', {'session_id': sid, 'action': 'export'}), save_the_export,
                      'Both are saved.'], 'make it ice and keep both', chat_id=first.chat_id)
    assert not saves(second)
    ice = second.answer['tools'][2]['result']['items'][0]['id']
    assert ice != lava and {s['id'] for s in fox()} == {lava, ice}
    third, _ = chat([skin_apply(sid), 'Bluer.'], 'bluer', chat_id=first.chat_id)
    [receipt] = saves(third)
    assert receipt['result']['autosave'] == 'updated' and receipt['result']['items'][0]['id'] == ice
    folder = config.STORAGE_PATH / 'Fox'
    assert (folder / f'{lava}.zip').read_bytes() == b'COSTUME' + bytes([1]) * 64


def test_a_costume_that_cannot_be_saved_says_so_and_keeps_its_edits(chat, costume):
    sid, viewer, imported, _ = costume
    item = skin_lab._sessions[sid]
    item['source'] = {**item['source'], 'origin': {'character': 'Ice Climbers', 'vanilla_color': 'Nr',
                                                   'costume_code': 'PlPpNr'}}
    run, seen = chat([skin_apply(sid), 'Done.'], 'make the climbers pink')
    assert 'cannot be saved to the vault' in tool_results(seen)[0]['vault']
    [receipt] = saves(run)
    assert receipt['status'] == 'error' and receipt['result']['refusal'] == 'not_saved'
    assert receipt['auto_save']['retry'] is False
    sentence = receipt['result']['error']
    assert sentence.startswith('Not saved to your vault: save paired climber copies together in the Texture Lab')
    assert run.answer['content'].endswith(sentence)
    assert receipt['result']['files'][0]['extension'] == '.dat'        # the edited file, still downloadable
    assert not fox() and not imported and sid in skin_lab._sessions
    # A refusal no retry can get past waits for the next edit.
    later, _ = chat(['Sure.'], 'thanks', chat_id=run.chat_id)
    assert not saves(later)


def test_a_failed_save_says_why_and_the_next_turn_tries_again(chat, costume):
    sid, viewer, imported, failures = costume
    failures.append(OSError('disk full'))
    run, _ = chat([skin_apply(sid), 'It is in your vault.'], 'make fox lava')
    [receipt] = saves(run)
    assert receipt['status'] == 'error' and receipt['auto_save']['retry'] is True
    assert receipt['result']['error'] == ('Not saved to your vault: the vault could not be written (OSError). '
                                          'Your edits are kept, and the next message tries again.')
    assert run.answer['content'] == 'It is in your vault.\n\n' + receipt['result']['error']
    assert not fox()
    later, _ = chat(['Glad you like it.'], 'nice', chat_id=run.chat_id)
    [receipt] = saves(later)
    assert receipt['status'] == 'done' and receipt['result']['autosave'] == 'saved'
    assert [s['name'] for s in fox()] == ['Fox - Lava']
    # Saved now: a further turn with no edit has nothing to save.
    quiet, _ = chat(['Yes.'], 'cool', chat_id=run.chat_id)
    assert not saves(quiet)


def test_an_update_never_reaches_a_costume_another_chat_made(costume):
    sid, viewer, imported, _ = costume
    edited = mod_files.register(b'COSTUME' + bytes([5]) * 64, 'PlFxNr.dat',
                                origin={'character': 'Fox', 'vanilla_color': 'Nr', 'costume_code': 'PlFxNr'},
                                edited=True)
    made = hsdraw.save_mod_copy(edited['file_id'], 'Theirs', chat_id='chat-a')['items'][0]
    with pytest.raises(ValueError, match='not made in this chat'):
        hsdraw.update_mod_copy(edited['file_id'], 'Fox', made['id'], 'chat-b')
    with pytest.raises(ValueError, match='not made in this chat'):
        hsdraw.update_mod_copy(edited['file_id'], 'Fox', made['id'], None)
    assert [s['id'] for s in fox()] == [made['id']] and len(imported) == 1


# ------------------------------------------------------------------ naming and the refusal sentence

@pytest.mark.parametrize('texts,source,name', [
    (['make dream land candy themed'], 'Dreamland', 'Dreamland - Candy'),
    (['make fox lava'], 'Fox', 'Fox - Lava'),
    (['Can you make the tree darker please'], 'Dreamland', 'Dreamland - Tree Darker'),
    (['do it', 'retexture fox to look like a zombie'], 'Fox', 'Fox - Zombie'),
    (['ok'], 'Fox', 'Fox - Retexture'),
])
def test_a_fallback_name_is_the_source_and_a_few_words_of_the_request(texts, source, name):
    assert autosave.fallback_name(source, texts, 'costume') == name


def test_the_not_saved_sentence_is_plain():
    result = refusals.not_saved('costume', 'The vault could not be written.', retry=True)
    assert result['error'] == ('Not saved to your vault: the vault could not be written. Your edits are kept, and '
                               'the next message tries again.')
    assert result['refusal'] == 'not_saved' and 'Do not say it is in the vault' in result['next']


def test_a_replayed_result_whose_files_is_a_summary_string_attaches_no_picture_and_does_not_crash():
    """The stage journal replays a repeated identical lab call with `files` as a
    summary string. Collecting its pictures used to iterate the string and fail
    the whole turn."""
    from randall.assistant import vision
    assert vision.tool_images('stage_lab', {'action': 'apply', 'files': '2 files'}) == []
    assert vision.tool_images('skin_lab', {'action': 'apply', 'files': None}) == []
