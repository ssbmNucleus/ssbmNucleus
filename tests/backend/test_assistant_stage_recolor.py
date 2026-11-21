"""The five starting points (docs/dev/RANDALL.md): "Retexture a stage" and the two stubs ("Import a stage model", "Create a character").

* /status serves the five launchable rows with `picker` and `available`, and the
  Stage Lab's own stage list as `recolor_stages`.
* A stub is listed but can never be started: the blueprint drops its id, and a
  chat that claims it reads as an ordinary chat.
* A picked stage is one `context.selection` entry, checked by the blueprint.
* On turn one of a stage recolor chat with one picked stage, code opens it in the
  Stage Lab (no search, no model round); the main model then works with the card.

No model request runs: the provider is a stand-in that records what it was given,
and the Stage Lab's open is a stub (no viewer process starts).
"""
import json
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask

from core import config
from core.stages import ALL_STAGES, LEGAL_STAGE_CODES
from shared.aiengine import decisions
from randall.assistant import engine, live_runs, recipes, store, tools
from randall.recolor import stage_lab
from randall.recolor.stage_start import StageStart, picked_stage
from randall.routes import assistant_bp as routes


# ------------------------------------------------------------------ the catalog and /status

@pytest.fixture
def client(vault):
    app = Flask(__name__)
    app.register_blueprint(routes.assistant_bp)
    return app.test_client()


def test_status_serves_five_starting_points_with_their_picker_and_availability(client):
    body = client.get('/api/assistant/status').get_json()
    assert [(t['id'], t['label'], t['picker'], t['available']) for t in body['tasks']] == [
        ('recolor_part', 'Retexture a costume', 'costume', True),
        ('model_import', 'Import a character model', 'fighter', True),
        ('create_character', 'Create a character', None, False),
        ('recolor_stage', 'Retexture a stage', 'stage', True),
        ('stage_import', 'Import a stage model', None, False),
    ]
    assert [t['group'] for t in body['tasks']] == ['Characters'] * 3 + ['Stages'] * 2
    for stub in (body['tasks'][2], body['tasks'][4]):
        assert stub['hint'].startswith('Use MCP (Settings > AI): ') and stub['placeholder'] is None
    assert body['tasks'][2]['hint'] == 'Use MCP (Settings > AI): build a whole new fighter, starting from a model.'
    # The stage picker offers exactly what the Stage Lab opens.
    assert body['recolor_stages'] == stage_lab.supported_stages()


def test_the_stage_list_is_the_stage_labs_own():
    rows = stage_lab.supported_stages()
    assert [row['code'] for row in rows] == list(ALL_STAGES)          # open_stage's own table
    assert len(rows) == 29 and [row['code'] for row in rows[:6]] == list(LEGAL_STAGE_CODES)
    for row in rows:
        assert set(row) == {'code', 'name', 'folder', 'legal', 'art'}
        assert row['legal'] == (row['code'] in LEGAL_STAGE_CODES)
        assert row['art'].startswith(('/vanilla/stages/', '/api/mex/stages/'))
    from shared.rendering.stage_editor import open_stage
    with pytest.raises(ValueError, match='supported stage code'):
        open_stage('GrXx')


def test_the_stage_card_names_only_the_stage_labs_operations():
    card = recipes.card('recolor_stage', tools.SCHEMAS)
    assert card.startswith('TASK RECIPE -- RECOLOR A STAGE')
    assert 'stage_lab_open(' in card and 'stage_lab(' in card
    assert 'skin_lab(' not in card and 'save_mod_copy(' not in card and 'test_in_game(' not in card
    assert 'Code saves the result to the user\'s vault when your turn ends' in card
    assert 'never offer to save it' in card and 'never claim how the stage looks or plays in game' in card
    # The first Stage Lab call brings this card; no other family's card moved.
    assert recipes.family_for_tool('stage_lab_open') == recipes.family_for_tool('stage_lab') == 'recolor_stage'
    assert recipes.family_for_tool('skin_lab') == 'recolor_part'
    assert recipes.family_for_tool('test_in_game') == 'verify_in_game'


# ------------------------------------------------------------------ the stub

@pytest.fixture
def started(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, 'start', lambda chat_id, message, context, **_: seen.append(context)
                        or SimpleNamespace())
    monkeypatch.setattr(live_runs, 'stream', lambda run: iter(()))
    return seen


STUBS = ('stage_import', 'create_character')


@pytest.mark.parametrize('stub', STUBS)
def test_a_stub_is_never_startable(stub):
    assert recipes.task_id(stub) is None and stub not in recipes.TASK_LABELS
    assert recipes.startable(tools.SCHEMAS) == {'recolor_part', 'model_import', 'recolor_stage'}
    assert stub not in recipes.CARDS and stub not in recipes.FAMILY_TOOLS
    assert recipes.chat_task([{'role': 'user', 'content': 'a', 'context': {'task': stub}}]) is None


def test_create_character_is_not_the_clone_ability():
    # The ordinary ability that clones an existing fighter is its own tool, not this stub.
    assert 'create_character' not in [s['function']['name'] for s in tools.SCHEMAS]


@pytest.mark.parametrize('stub', STUBS)
def test_a_crafted_request_cannot_start_a_stub(client, started, stub):
    response = client.post('/api/assistant/chat', json={
        'message': 'turn this into a stage', 'api_key': 'k', 'context': {'page': 'vault', 'task': stub}})
    assert response.status_code == 200, 'dropped silently, never refused'
    assert started == [{'page': 'vault'}]
    chat_id = store.save(None, [{'role': 'user', 'content': 'hello', 'context': {}}])
    response = client.post(f'/api/assistant/chats/{chat_id}/inputs', json={
        'id': uuid.uuid4().hex, 'message': 'a stage', 'context': {'task': stub}})
    assert response.status_code == 200 and store.pending_inputs(chat_id)[0]['context'] == {}


@pytest.mark.parametrize('stub', STUBS)
def test_a_chat_stored_with_a_stub_reads_as_a_normal_chat(client, stub):
    chat_id = store.save(None, [{'role': 'user', 'content': 'a stage', 'context': {'task': stub}}])
    assert store.get(chat_id)['task'] is None
    assert {row['id']: row['task'] for row in client.get('/api/assistant/chats').get_json()['chats']}[chat_id] is None


# ------------------------------------------------------------------ the stage selection

@pytest.fixture
def variant(vault):
    """A vault stage variant on disk, as the Vault's stage list serves it (id = archive stem)."""
    folder = config.STORAGE_PATH / 'das' / 'battlefield'
    folder.mkdir(parents=True)
    (folder / 'night-sky.zip').write_bytes(b'PK\x05\x06' + bytes(18))
    return 'night-sky'


@pytest.mark.parametrize('item,kept', [
    # A vault variant and the stock stage, exactly as the picker sends them.
    ({'kind': 'stage', 'stage': 'GrNBa', 'id': 'night-sky', 'name': 'Battlefield · Night Sky'},
     {'kind': 'stage', 'stage': 'GrNBa', 'id': 'night-sky', 'name': 'Battlefield · Night Sky'}),
    ({'kind': 'stage', 'stage': 'GrNLa', 'vanilla': True, 'name': 'Final Destination (stock)'},
     {'kind': 'stage', 'stage': 'GrNLa', 'vanilla': True, 'name': 'Final Destination (stock)'}),
    # The vault folder names the stage too; a missing name becomes the stage's own; extra keys go.
    ({'kind': 'stage', 'stage': 'battlefield', 'id': 'night-sky', 'secret': 'x'},
     {'kind': 'stage', 'stage': 'GrNBa', 'id': 'night-sky', 'name': 'Battlefield'}),
    ({'kind': 'stage', 'stage': 'GrCn', 'vanilla': True, 'name': '  Corneria   (stock) '},
     {'kind': 'stage', 'stage': 'GrCn', 'vanilla': True, 'name': 'Corneria (stock)'}),
    # Dropped: a stage the Stage Lab does not open, a variant not in the vault, a path, both shapes at once.
    ({'kind': 'stage', 'stage': 'GrXx', 'vanilla': True}, None),
    ({'kind': 'stage', 'stage': 'GrNBa', 'id': 'not-there'}, None),
    ({'kind': 'stage', 'stage': 'GrNBa', 'id': '../battlefield/night-sky'}, None),
    ({'kind': 'stage', 'stage': 'GrNBa', 'id': '..'}, None),
    ({'kind': 'stage', 'stage': 'GrNBa', 'id': 'night-sky', 'vanilla': True}, None),
    ({'kind': 'stage', 'stage': 'GrNBa'}, None),
    ({'kind': 'stage', 'stage': ['GrNBa'], 'vanilla': True}, None),
    ({'kind': 'stage', 'stage': 'GrNBa', 'id': 7}, None),
])
def test_the_blueprint_keeps_a_stage_the_stage_lab_can_open_and_drops_anything_else(
        client, started, variant, item, kept):
    response = client.post('/api/assistant/chat', json={'message': 'make it purple', 'api_key': 'k',
                                                         'context': {'task': 'recolor_stage', 'selection': [item]}})
    assert response.status_code == 200
    assert started == [{'task': 'recolor_stage', 'selection': [kept] if kept else []}]


def test_costume_entries_beside_a_stage_pass_through_untouched(client, started, variant):
    costume = {'id': 'fox-blue-1', 'character': 'Fox', 'name': 'Blue Hoodie', 'whatever': 1}
    website = {'post_id': 7, 'file_id': 9}
    client.post('/api/assistant/chat', json={'message': 'hi', 'api_key': 'k', 'context': {'selection': [
        costume, {'kind': 'stage', 'stage': 'GrXx', 'vanilla': True}, website, 'odd']}})
    assert started == [{'selection': [costume, website, 'odd']}]


@pytest.mark.parametrize('view,picked', [
    ({'selection': [{'kind': 'stage', 'stage': 'GrNBa', 'id': 'night-sky', 'name': 'x'}]},
     {'stage_code': 'GrNBa', 'variant_id': 'night-sky'}),
    ({'selection': [{'kind': 'stage', 'stage': 'GrNLa', 'vanilla': True, 'name': 'x'}]}, {'stage_code': 'GrNLa'}),
    # Not one stage: several entries, a costume, an ambiguous or empty entry.
    ({'selection': [{'kind': 'stage', 'stage': 'GrNLa', 'vanilla': True}] * 2}, None),
    ({'selection': [{'character': 'Fox', 'id': 'a'}]}, None),
    ({'selection': [{'kind': 'stage', 'stage': 'GrNBa', 'id': 'a', 'vanilla': True}]}, None),
    ({'selection': [{'kind': 'stage', 'stage': 'GrNBa'}]}, None),
    ({'selection': []}, None), ({}, None), (None, None),
])
def test_picked_stage_reads_the_one_stage_entry(view, picked):
    assert picked_stage(view) == picked


# ------------------------------------------------------------------ the engine

NIGHT = {'kind': 'stage', 'stage': 'GrNBa', 'id': 'night-sky', 'name': 'Battlefield · Night Sky'}
STOCK_FD = {'kind': 'stage', 'stage': 'GrNLa', 'vanilla': True, 'name': 'Final Destination (stock)'}


def emit(text='', calls=None):
    yield {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
           'message': {'role': 'assistant', 'content': text or None, **({'tool_calls': calls} if calls else {})}}


@pytest.fixture
def opened(monkeypatch):
    """The Stage Lab's open, stubbed: records its arguments, starts no viewer."""
    calls = []

    def stage_lab_open(stage_code, variant_id=None):
        calls.append({'stage_code': stage_code, **({'variant_id': variant_id} if variant_id else {})})
        return {'session_id': 'a' * 32, 'stage': stage_code, 'textures': [{'index': 0, 'name': 'Group 0 / Texture 0'}]}
    monkeypatch.setitem(tools.REGISTRY, 'stage_lab_open', tools.ToolSpec('automatic', stage_lab_open))
    return calls


@pytest.fixture
def turn(vault, monkeypatch):
    """Run one turn against a recording provider. -> (run, [(system texts, offered names), ...])"""
    from randall.assistant.tasks import coordinator, store as taskstore
    taskstore.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    monkeypatch.setattr(tools, 'vanilla_assets_ready', lambda: False)

    def run_turn(text, context=None, *, chat_id=None):
        seen = []

        def provider(messages, schemas, key, cancelled, *args, **kwargs):
            seen.append(([m['content'] for m in messages if m['role'] == 'system'],
                         [s['function']['name'] for s in schemas]))
            yield from emit('Done.')
        monkeypatch.setattr(engine, '_provider', provider)
        run = engine.start(chat_id, text, context or {}, request_key='k')
        list(live_runs.stream(run))
        assert run.answer['status'] == 'done', run.answer.get('error')
        return run, seen
    return run_turn


@pytest.mark.parametrize('item,arguments', [
    (NIGHT, {'stage_code': 'GrNBa', 'variant_id': 'night-sky'}),
    (STOCK_FD, {'stage_code': 'GrNLa'}),
])
def test_a_picked_stage_reaches_the_stage_lab_directly(turn, opened, item, arguments):
    run, seen = turn('make the platforms purple', {'task': 'recolor_stage', 'selection': [item]})
    receipt = run.answer['tools'][0]
    assert receipt['name'] == 'stage_lab_open' and receipt['arguments'] == arguments
    assert receipt['workflow'] == {'name': 'recolor_stage', 'stage': 'open', 'requested_by': 'code'}
    assert opened == [arguments] and len(run.answer['tools']) == 1
    # Code's open is not a model round: the one provider round came after it.
    assert len(seen) == 1 and run.answer['model_rounds'] == 1
    systems = seen[0][0]
    assert any(text.startswith('TASK RECIPE -- RECOLOR A STAGE') for text in systems)
    note = next(text for text in systems if text.startswith('Code workflow state: '))
    state = json.loads(note[len('Code workflow state: '):].split('\n', 1)[0])
    assert state == {'workflow': 'recolor_stage', 'stage': 'create_review', 'reason': 'stage_opened',
                     **arguments, 'session_id': 'a' * 32}
    assert 'do not open it again' in note
    routing = run.answer['routing']
    assert routing['declared_task'] == 'recolor_stage' and routing['workflow'] == 'recolor_stage'
    assert run.answer['recipes'][0]['family'] == 'recolor_stage'
    assert store.get(run.chat_id)['task'] == 'recolor_stage'


def test_a_failed_open_goes_to_the_main_model_with_the_reason(turn, monkeypatch):
    def refuse(stage_code, variant_id=None):
        raise ValueError('Vanilla stage is unavailable; complete game-file setup first')
    monkeypatch.setitem(tools.REGISTRY, 'stage_lab_open', tools.ToolSpec('automatic', refuse))
    run, seen = turn('make it purple', {'task': 'recolor_stage', 'selection': [STOCK_FD]})
    assert run.answer['tools'][0]['result'] == {'error': 'Vanilla stage is unavailable; complete game-file setup first'}
    note = next(text for text in seen[0][0] if text.startswith('Code workflow state: '))
    assert '"reason": "open_failed"' in note and 'Do not repeat the same call' in note


@pytest.mark.parametrize('text,context', [
    # No pick: the main model finds the stage with the ordinary tools.
    ('make battlefield purple', {'task': 'recolor_stage'}),
    # A question, a follow-up, or an ordinary chat carrying a stage.
    ('How should I recolor this stage?', {'task': 'recolor_stage', 'selection': [NIGHT]}),
    ('put it in my game', {'task': 'recolor_stage', 'selection': [NIGHT]}),
    ('make it purple', {'selection': [NIGHT]}),
    # A costume recolor chat never opens a stage.
    ('make it purple', {'task': 'recolor_part', 'selection': [NIGHT]}),
])
def test_code_opens_nothing_otherwise(turn, opened, text, context):
    run, seen = turn(text, context)
    assert opened == [] and not run.answer['tools']
    assert run.answer['routing']['workflow'] != 'recolor_stage'
    assert not any(text.startswith('Code workflow state: ') and 'recolor_stage' in text for text in seen[0][0])


def test_a_chat_whose_stage_is_open_never_opens_it_again(turn, opened):
    first, _ = turn('make the platforms purple', {'task': 'recolor_stage', 'selection': [NIGHT]})
    assert len(opened) == 1
    run, _ = turn('now the background too', {'selection': [NIGHT]}, chat_id=first.chat_id)
    assert len(opened) == 1 and not run.answer['tools']
    assert run.answer['routing']['declared_task'] == 'recolor_stage'


def test_stage_start_only_runs_when_both_halves_agree():
    view = {'selection': [NIGHT]}
    assert StageStart('make it purple', view=view, main_model='m', enrolled=True).name == 'recolor_stage'
    assert StageStart('make it purple', view=view, main_model='m', enrolled=False).name is None
    done = [{'name': 'stage_lab_open', 'status': 'done', 'result': {'session_id': 'b' * 32}}]
    assert StageStart('make it purple', done, view=view, main_model='m', enrolled=True).name is None
    # A failed open earlier does not count as an open stage.
    failed = [{'name': 'stage_lab_open', 'status': 'error', 'result': {'error': 'no'}}]
    assert StageStart('make it purple', failed, view=view, main_model='m', enrolled=True).name == 'recolor_stage'
    start = StageStart('make it purple', view=view, main_model='m', enrolled=True)
    assert start.code_round([]) is False, 'not offered: nothing for code to do'
