"""Declared tasks: a chat started as one task routes by that task, never by its words.

Contract: git history before 2026-10-03: randall-task-modes-contract.md; the two
starting points since 2026-10-03 (docs/dev/RANDALL.md). The catalog is
recipes.LAUNCHABLE (the four starting points, one of them a stub); the blueprint whitelists
`context.task` against it; the store keeps the chat's task in `chats.task`; the
engine routes a declared chat deterministically and nudges a recolor chat whose
message attaches a model file. An ordinary chat gets no task from its words.

No model request runs: the provider is a stand-in that records what it was given.
"""
import json
import sqlite3
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask

from shared.aiengine import decisions
from shared.aiengine.decisions import Turn
from core import config
from randall.assistant import engine, live_runs, recipes, store, tools, turn_facts
from shared import mod_files
from randall.model_import.chat import import_job, studio_import
from randall.recolor import workflows

CONTRACT_TABLE = [
    ('recolor_part', 'Retexture a costume', 'Which costume, and what look?',
     'Pick a costume from your vault or the stock roster, or describe one in words, and say the new look.'),
    ('model_import', 'Import a character model', 'Attach a model and say which fighter it goes on.',
     'Turn a 3D model (.zip, .glb, .obj, .fbx, .dae) into a Melee costume.'),
    ('create_character', 'Create a character', None,
     'Use MCP (Settings > AI): build a whole new fighter, starting from a model.'),
    ('recolor_stage', 'Retexture a stage', 'Which stage, and what colors?',
     'Pick a stage from your vault or the stock stages and describe the new colors.'),
    ('stage_import', 'Import a stage model', None,
     'Use MCP (Settings > AI): turn a 3D model into a playable stage.'),
]
# Shown but not built: listed by /status, never startable (test_assistant_stage_recolor.py).
STUBS = ('stage_import', 'create_character')
# The recolor's own operations: without them a recolor chat cannot run.
RECOLOR_TOOLS = recipes.FAMILY_TOOLS['recolor_part']
# Starting points until 2026-10-03; a chat stored with one opens as an ordinary chat.
RETIRED = ('find_mod', 'menu_background')


# ------------------------------------------------------------------ the catalog

def test_the_catalog_is_the_contract_table_in_display_order():
    assert [(t['id'], t['label'], t['placeholder'], t['hint']) for t in recipes.LAUNCHABLE] == CONTRACT_TABLE
    assert [t['id'] for t in recipes.launchable()] == [row[0] for row in CONTRACT_TABLE]


def test_follow_up_families_are_not_launchable():
    ids = {t['id'] for t in recipes.LAUNCHABLE}
    assert not ids & {'deliver_to_game', 'verify_in_game'}
    # Every startable task is a family the recipes know (the import's card is the engine's).
    assert ids - set(STUBS) <= set(recipes.FAMILY_TOOLS) | {'model_import'}


def test_launchable_returns_copies_the_caller_cannot_edit_the_catalog_through():
    recipes.launchable()[0]['label'] = 'changed'
    assert recipes.LAUNCHABLE[0]['label'] == 'Retexture a costume'


def test_a_task_whose_operations_are_off_in_this_build_is_not_offered(monkeypatch):
    without = [s for s in tools.SCHEMAS if s['function']['name'] not in RECOLOR_TOOLS]
    assert [t['id'] for t in recipes.launchable(without)] == ['model_import', 'create_character', 'recolor_stage', 'stage_import']
    for name in RECOLOR_TOOLS:
        monkeypatch.delitem(tools.REGISTRY, name)
    assert [t['id'] for t in recipes.launchable()] == ['model_import', 'create_character', 'recolor_stage', 'stage_import']
    # The import is the engine's own job; no app roster can withhold it.
    assert [t['id'] for t in recipes.launchable([])] == ['model_import', 'create_character', 'stage_import']
    assert recipes.startable([]) == {'model_import'}


@pytest.mark.parametrize('task', RETIRED)
def test_find_a_mod_and_menu_background_are_no_longer_starting_points(task):
    assert recipes.task_id(task) is None and task not in recipes.TASK_LABELS
    # Menu background is gone as a family; finding a mod is an ordinary ability
    # whose card follows the website tools (test_assistant_prompt.py).
    assert 'menu_background' not in recipes.FAMILY_TOOLS and 'menu_background' not in recipes.CARDS


@pytest.mark.parametrize('messages,task', [
    ([], None),
    ([{'role': 'user', 'content': 'hi'}], None),                       # no context at all
    ([{'role': 'user', 'content': 'hi', 'context': {'task': 'recolor_part'}}], 'recolor_part'),
    # The first user message's task, never a later one's.
    ([{'role': 'assistant', 'content': 'welcome'},
      {'role': 'user', 'content': 'a', 'context': {'task': 'model_import'}},
      {'role': 'user', 'content': 'b', 'context': {'task': 'recolor_part'}}], 'model_import'),
    # An Ask chat never becomes declared half way through.
    ([{'role': 'user', 'content': 'a', 'context': {'page': 'vault'}},
      {'role': 'assistant', 'content': 'b'},
      {'role': 'user', 'content': 'c', 'context': {'task': 'recolor_part'}}], None),
    # Not a launchable task: counts as absent, exactly as the whitelist drops it.
    ([{'role': 'user', 'content': 'a', 'context': {'task': 'deliver_to_game'}}], None),
    # A retired starting point: the chat is an ordinary one.
    ([{'role': 'user', 'content': 'a', 'context': {'task': 'find_mod'}},
      {'role': 'user', 'content': 'b', 'context': {'task': 'recolor_part'}}], None),
    ([{'role': 'user', 'content': 'a', 'context': {'task': 'menu_background'}}], None),
    ([{'role': 'user', 'content': 'b', 'context': {'task': ['recolor_part']}}], None),
    ([{'role': 'user', 'content': 'c', 'context': 'not a dict'}], None),
    # An assistant message never declares anything.
    ([{'role': 'assistant', 'content': 'a', 'context': {'task': 'recolor_part'}}], None),
])
def test_a_chats_task_is_its_first_user_messages(messages, task):
    assert recipes.chat_task(messages) == task


# ------------------------------------------------------------------ the blueprint

@pytest.fixture
def client(vault):
    from randall.routes.assistant_bp import assistant_bp
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    return app.test_client()


def test_status_serves_the_launchable_tasks(client):
    body = client.get('/api/assistant/status').get_json()
    assert body['tasks'] == recipes.launchable(tools.SCHEMAS)
    assert [t['id'] for t in body['tasks']] == [row[0] for row in CONTRACT_TABLE]
    assert all(set(task) == {'id', 'label', 'group', 'placeholder', 'hint', 'picker', 'available'} for task in body['tasks'])


def test_each_starting_point_names_the_picker_the_panel_shows():
    """The frontend reads `status.tasks[].picker`: a recolor starts from a costume,
    an import from a fighter, a stage recolor from a stage; the stub has none."""
    assert {t['id']: t['picker'] for t in recipes.launchable(tools.SCHEMAS)} == {
        'recolor_part': 'costume', 'model_import': 'fighter', 'create_character': None,
        'recolor_stage': 'stage', 'stage_import': None}


@pytest.mark.parametrize('task,kept', [
    ('recolor_part', 'recolor_part'), ('model_import', 'model_import'),
    ('deliver_to_game', None), ('bogus', None), (['recolor_part'], None), ({'id': 'find_mod'}, None), (7, None),
    ('find_mod', None), ('menu_background', None),
])
def test_chat_whitelist_keeps_a_launchable_task_and_drops_anything_else(client, monkeypatch, task, kept):
    seen = []
    monkeypatch.setattr(engine, 'start', lambda chat_id, message, context, **_: seen.append(context)
                        or SimpleNamespace())
    monkeypatch.setattr(live_runs, 'stream', lambda run: iter(()))
    response = client.post('/api/assistant/chat', json={
        'message': 'hello', 'api_key': 'k', 'context': {'page': 'vault', 'task': task, 'secret': 'x'}})
    assert response.status_code == 200, 'an invalid task is dropped silently, never refused'
    expected = {'page': 'vault', **({'task': kept} if kept else {})}
    assert seen == [expected]


@pytest.mark.parametrize('task,kept', [('model_import', 'model_import'), ('find_mod', None),
                                       ('verify_in_game', None), (None, None)])
def test_queued_input_whitelist_keeps_a_launchable_task_and_drops_anything_else(client, task, kept):
    chat_id = store.save(None, [{'role': 'user', 'content': 'Wood Mario'}])
    response = client.post(f'/api/assistant/chats/{chat_id}/inputs', json={
        'id': uuid.uuid4().hex, 'message': 'also the hat', 'context': {'page': 'vault', 'task': task}})
    assert response.status_code == 200
    assert store.pending_inputs(chat_id)[0]['context'] == {'page': 'vault', **({'task': kept} if kept else {})}


def test_a_task_this_build_does_not_offer_is_dropped(client, monkeypatch):
    for name in RECOLOR_TOOLS:
        monkeypatch.delitem(tools.REGISTRY, name)
    seen = []
    monkeypatch.setattr(engine, 'start', lambda chat_id, message, context, **_: seen.append(context)
                        or SimpleNamespace())
    monkeypatch.setattr(live_runs, 'stream', lambda run: iter(()))
    client.post('/api/assistant/chat', json={'message': 'hi', 'api_key': 'k', 'context': {'task': 'recolor_part'}})
    assert seen == [{}]


def test_chat_rows_and_transcripts_carry_the_task(client):
    declared = store.save(None, [{'role': 'user', 'content': 'spooky', 'context': {'task': 'recolor_part'}}])
    plain = store.save(None, [{'role': 'user', 'content': 'hello', 'context': {}}])
    rows = {row['id']: row for row in client.get('/api/assistant/chats').get_json()['chats']}
    assert rows[declared]['task'] == 'recolor_part' and rows[plain]['task'] is None
    assert client.get(f'/api/assistant/chats/{declared}').get_json()['task'] == 'recolor_part'
    assert client.get(f'/api/assistant/chats/{plain}').get_json()['task'] is None


# ------------------------------------------------------------------ the store

def test_an_existing_chats_db_gains_the_task_column_and_keeps_its_history(vault):
    path = config.STORAGE_PATH / 'assistant' / 'chats.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(path)
    old.execute('CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT, messages TEXT, updated REAL)')
    messages = [{'role': 'user', 'content': 'old chat'}]
    old.execute('INSERT INTO chats VALUES (?,?,?,?)', ('a' * 32, 'old chat', json.dumps(messages), 1.0))
    old.commit()
    old.close()

    assert store.list_chats() == [{'id': 'a' * 32, 'title': 'old chat', 'updated': 1.0, 'task': None}]
    chat = store.get('a' * 32)
    assert chat['task'] is None and chat['messages'] == messages
    # A pre-task chat saved again stays undeclared...
    store.save('a' * 32, [*messages, {'role': 'assistant', 'content': 'ok'}])
    assert store.get('a' * 32)['task'] is None
    # ...and opening twice does not try to add the column twice.
    store.list_chats()
    check = sqlite3.connect(path)
    try:
        columns = [row[1] for row in check.execute('PRAGMA table_info(chats)')]
    finally:
        check.close()
    assert columns.count('task') == 1


def test_save_fills_the_task_once_and_never_overwrites_it(vault):
    first = {'role': 'user', 'content': 'spooky Fox', 'context': {'task': 'recolor_part'}}
    chat_id = store.save(None, [first])
    assert store.get(chat_id)['task'] == 'recolor_part'
    # A later save whose transcript would derive another task keeps the stored one.
    store.save(chat_id, [{**first, 'context': {'task': 'model_import'}}])
    assert store.get(chat_id)['task'] == 'recolor_part'
    store.save(chat_id, [{'role': 'user', 'content': 'spooky Fox'}])
    assert store.get(chat_id)['task'] == 'recolor_part'


def test_an_ask_chat_is_never_declared_by_a_later_message(vault):
    chat_id = store.save(None, [{'role': 'user', 'content': 'hello', 'context': {}}])
    assert store.get(chat_id)['task'] is None
    store.save(chat_id, [{'role': 'user', 'content': 'hello', 'context': {}},
                         {'role': 'user', 'content': 'a recolor', 'context': {'task': 'recolor_part'}}])
    assert store.get(chat_id)['task'] is None


class _Connection:
    """A real sqlite3 connection whose task-column ALTER fails the way `error` says."""

    def __init__(self, conn, error, apply_first):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_error', error)
        object.__setattr__(self, '_apply_first', apply_first)

    def execute(self, sql, *args):
        if sql.startswith('ALTER TABLE chats ADD COLUMN task'):
            if self._apply_first:           # another connection won the race
                self._conn.execute(sql, *args)
            raise sqlite3.OperationalError(self._error)
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


@pytest.mark.parametrize('error,apply_first,survives', [
    ('duplicate column name: task', True, True),     # the race: benign
    ('database is locked', False, False),            # anything else surfaces
    ('attempt to write a readonly database', False, False),
])
def test_the_migration_only_forgives_a_column_another_connection_added(vault, monkeypatch, error, apply_first,
                                                                        survives):
    connect = sqlite3.connect
    monkeypatch.setattr(store.sqlite3, 'connect',
                        lambda *a, **k: _Connection(connect(*a, **k), error, apply_first))
    if survives:
        assert store.list_chats() == []
    else:
        with pytest.raises(sqlite3.OperationalError, match=error):
            store.list_chats()


# ------------------------------------------------------------------ the workflow

@pytest.fixture
def lane(monkeypatch):
    """The fast lane switched on, as it is in a real build (no request is made here)."""
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '1')
    monkeypatch.setenv('NUCLEUS_RECOLOR_WORKFLOW', '1')


@pytest.mark.parametrize('text', ['have a go at this one', 'Recolor my Fox costume', 'give fox a lava look',
                                  'make a lava Bowser skin'])
def test_only_a_declared_recolor_enrolls_and_then_whatever_the_words_say(lane, text):
    """The words of an ordinary chat never start the recolor workflow; a recolor chat's always may."""
    assert workflows.Workflow(text, {}, main_model='main').name is None
    assert workflows.Workflow(text, {}, main_model='main', recolor=False).name is None
    flow = workflows.Workflow(text, {}, main_model='main', recolor=True)
    assert flow.name == 'recolor' and flow.stage == 'acquire'


@pytest.mark.parametrize('text', [
    "Don't change anything yet. How should I recolor Fox?",       # a question
    'Never mind, do not recolor Fox after all',                      # a refusal
    'Recolor both Fox costumes',                                     # several costumes
    'give all my Fox costumes a lava look',
])
def test_a_declared_recolor_still_leaves_questions_refusals_and_several_costumes_out(lane, text):
    assert workflows.Workflow(text, {}, main_model='main', recolor=True).name is None


def test_a_declared_recolor_with_an_open_skin_session_is_a_follow_up_edit(lane):
    state = {'skin_sessions': [{'session_id': 'b' * 32}]}
    flow = workflows.Workflow('make it darker', state, main_model='main', recolor=True)
    assert flow.name is None and flow.stage == 'create_review'


@pytest.mark.parametrize('text,source', [('Fox but spooky', 'Fox'), ('my Fox costume, spooky', None)])
def test_a_declared_recolor_still_starts_from_the_default_costume_the_words_name(lane, text, source):
    assert workflows.Workflow(text, {}, main_model='main', recolor=True).default_source == source


# ------------------------------------------------------------------ the mismatch rule

GLB = {'file_id': 'f' * 32, 'name': 'goku.glb', 'extension': '.glb'}
ZIP = {'file_id': 'e' * 32, 'name': 'pack.zip', 'extension': '.zip'}


@pytest.mark.parametrize('declared,text', [
    ('recolor_part', 'change the css background to a forest'),
    ('recolor_part', 'import a model of goku'),
    ('model_import', 'recolor my Fox costume red'),
    ('model_import', 'find me a Falco skin to download'),
    (None, 'import a model of goku'),
])
def test_words_never_make_a_mismatch(declared, text):
    """Only an attached model file does: the words of a message never send the user to another chat."""
    assert recipes.task_mismatch(declared) is None
    assert recipes.turn_family(declared, text) == declared


@pytest.mark.parametrize('declared,attached,other', [
    ('recolor_part', GLB, 'model_import'),
    # A .zip never counts: "import" is also how a costume pack is added to the vault.
    ('recolor_part', ZIP, None),
    # An import chat, an ordinary chat, or nothing attached: nothing to point elsewhere.
    ('model_import', GLB, None),
    (None, GLB, None),
    ('recolor_part', None, None),
])
def test_an_attached_model_in_a_recolor_chat_is_a_model_import_mismatch(declared, attached, other):
    assert recipes.task_mismatch(declared, attached_model=attached) == other


def test_the_mismatch_line_is_the_contracts_wording():
    assert recipes.mismatch_note('recolor_part', 'model_import') == (
        "This chat is a Retexture a costume chat. The user's message asks for Import a character model. "
        'Do not start that work here; tell them in one sentence to start a new Import a character model chat, '
        'then stop.')


@pytest.mark.parametrize('declared,text,family', [
    (None, 'put it in my game', 'deliver_to_game'),
    (None, 'now test it in game', 'verify_in_game'),
    (None, 'Fox but spooky', None),
    # An ordinary chat's words pick no task: the card follows the first called tool.
    (None, 'find me a Falco skin to download', None),
    (None, 'Recolor my Fox costume red', None),
    (None, 'Import the dragon model onto the fighter it suits best', None),
    (None, 'change the css background to a forest', None),
    ('recolor_part', 'Fox but spooky', 'recolor_part'),
    # A follow-up on what the chat made still routes there...
    ('recolor_part', 'put it in my game', 'deliver_to_game'),
    ('recolor_part', 'now test it in game', 'verify_in_game'),
    # (an import chat's follow-ups route the same way once its costume is saved: _pinned_task lets go, so the
    # declared task reaching here is None)
    (None, 'show me him in game', 'verify_in_game'),
    (None, 'let me play him', 'verify_in_game'),
    (None, 'I want to play it', 'verify_in_game'),
    (None, 'put him in my game', 'deliver_to_game'),
    # ...anything else stays the chat's task.
    ('recolor_part', 'change the css background to a forest', 'recolor_part'),
    ('model_import', 'here is goku, put him on falcon', 'model_import'),
    # An import not saved yet has made nothing to follow up on: asking to test it in game (or put it in the game)
    # is part of the import request, never a turn without the import tool.
    ('model_import', 'put it in my game', 'model_import'),
    ('model_import', 'this is tung tung tung sahur. put him in melee on whichever fighter he actually fits, keep '
                     'his textures, save him to my vault and test him in game.', 'model_import'),
    ('model_import', 'save him to my vault and show me him in game', 'model_import'),
])
def test_a_declared_task_or_a_follow_up_is_the_only_card_before_a_call(declared, text, family):
    assert recipes.turn_family(declared, text) == family


# ------------------------------------------------------------------ the engine

def emit(text='', calls=None):
    yield {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
           'message': {'role': 'assistant', 'content': text or None,
                       **({'tool_calls': calls} if calls else {})}}


@pytest.fixture
def turn(vault, monkeypatch):
    """Run one turn against a recording provider. -> (run, [(system texts, offered names), ...])"""
    from randall.assistant.tasks import coordinator, store as taskstore
    taskstore.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    # No extracted vanilla assets: a recolor's default costume is not opened by code,
    # so the declared recolor goes straight to the (recorded) main model.
    monkeypatch.setattr(tools, 'vanilla_assets_ready', lambda: False)

    def run_turn(text, context=None, *, chat_id=None, plan=()):
        seen, plan = [], list(plan)

        def provider(messages, schemas, key, cancelled, *args, **kwargs):
            seen.append(([m['content'] for m in messages if m['role'] == 'system'],
                         [s['function']['name'] for s in schemas]))
            if plan:
                yield from emit('Working.', calls=[plan.pop(0)])
                return
            yield from emit('Done.')
        monkeypatch.setattr(engine, '_provider', provider)
        run = engine.start(chat_id, text, context or {}, request_key='k')
        list(live_runs.stream(run))
        assert run.answer['status'] == 'done', run.answer.get('error')
        return run, seen
    return run_turn


@pytest.mark.parametrize('text', ['Fox but spooky', 'make a lava Fox skin', 'find me a Falco skin to download',
                                  'Import the dragon model onto the fighter it suits best'])
def test_an_undeclared_turn_has_no_task_no_workflow_and_no_card_before_a_call(turn, text):
    run, seen = turn(text)
    routing = run.answer['routing']
    assert routing['declared_task'] is None and 'task_mismatch' not in routing
    assert routing['workflow'] is None and routing['fast_lane_active'] is False
    assert 'model_import_mode' not in routing
    assert not any('TASK RECIPE' in text for text in seen[0][0])
    assert 'import_model' not in seen[0][1] and 'search_website_mods' in seen[0][1], 'the whole roster'


def test_a_declared_recolor_routes_as_a_recolor_on_turn_one(turn):
    run, seen = turn('Fox but spooky', {'task': 'recolor_part'})
    routing = run.answer['routing']
    assert routing['declared_task'] == 'recolor_part' and routing['workflow'] == 'recolor'
    assert any('TASK RECIPE -- RECOLOR A PART' in text for text in seen[0][0])
    assert run.answer['recipes'][0]['family'] == 'recolor_part'
    assert store.get(run.chat_id)['task'] == 'recolor_part'


def test_a_declared_model_import_is_an_import_turn(turn, tmp_path, monkeypatch):
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    run, _ = turn('goku please')
    assert 'model_import_mode' not in run.answer['routing']
    run, seen = turn('goku please', {'task': 'model_import'})
    routing = run.answer['routing']
    assert routing['declared_task'] == 'model_import' and routing['model_import_mode'] == 'import'
    assert set(seen[0][1]) == {'import_model', *studio_import.IMPORT_APP_TOOLS}
    assert any('TASK RECIPE -- IMPORT A MODEL' in text for text in seen[0][0])


def _stub(monkeypatch, name, result):
    monkeypatch.setitem(tools.REGISTRY, name, tools.ToolSpec('automatic', lambda **_: result))


def _call(name, arguments):
    return {'id': 'c1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}


def _cards(seen):
    return [text for systems, _ in seen for text in systems if text.startswith('TASK RECIPE')]


@pytest.mark.parametrize('task,card', [('recolor_part', 'TASK RECIPE -- RECOLOR A PART'), (None, None)])
def test_a_test_in_game_call_switches_the_card_to_verify_in_game(turn, monkeypatch, task, card):
    """A follow-up family is not a launchable task, so a declared chat lets the
    call switch the card to it exactly as an undeclared one does (test_assistant_prompt.py)."""
    _stub(monkeypatch, 'test_in_game', {'items': []})
    run, seen = turn('have a go at this one', {'task': task} if task else {},
                     plan=[_call('test_in_game', {'action': 'list'})])
    assert len(seen) == 2
    first = _cards([seen[0]])
    assert first == [] if card is None else any(card in text for text in first)
    assert any('TASK RECIPE -- VERIFY IN GAME' in text for text in seen[1][0])
    assert [r['family'] for r in run.answer['recipes']] == [f for f in (task, 'verify_in_game') if f]
    assert run.answer['routing']['declared_task'] == task


def test_a_called_tool_switches_the_card_to_any_family_in_a_declared_chat(turn, monkeypatch):
    """The declared task pins only the turn-one card. The called tool is the
    definitive answer, and its card carries the scope rules that tool needs, so
    present_vault_skins (find_mod's alone) moves a recolor chat's card to find_mod
    exactly as it does in an undeclared chat."""
    _stub(monkeypatch, 'present_vault_skins', {'items': []})
    call = _call('present_vault_skins', {'items': [{'character': 'Fox', 'skin_id': 'a'}]})
    run, seen = turn('have a go at this one', {'task': 'recolor_part'}, plan=[call])
    assert len(seen) == 2
    assert any('TASK RECIPE -- RECOLOR A PART' in text for text in seen[0][0])
    assert any('TASK RECIPE -- FIND / DOWNLOAD A MOD' in text for text in seen[1][0])
    assert [r['family'] for r in run.answer['recipes']] == ['recolor_part', 'find_mod']
    assert run.answer['routing']['declared_task'] == 'recolor_part'


@pytest.fixture
def lane_on(monkeypatch):
    """The fast lane on, as in a real build, answering nothing (every request hands off)."""
    from shared.aiengine import fast_lane
    monkeypatch.setenv('NUCLEUS_FAST_ROUTING', '1')
    monkeypatch.setattr(fast_lane.FastLane, 'request', lambda self, *a, **k: None)


def test_put_it_in_my_game_in_a_declared_recolor_chat_is_a_delivery_turn(turn, lane_on):
    """The recolor chat's natural ending. This chat has no recorded Skin Lab
    session (working_context lists every session a chat ever opened, and any one
    of them blocks enrollment on its own), so only the routing keeps a fresh
    acquisition from starting: the fast lane is on (as in a real build) and
    would have enrolled a forced recolor."""
    first, _ = turn('Fox but spooky', {'task': 'recolor_part'})
    assert first.answer['routing']['workflow'] == 'recolor'
    run, seen = turn('put it in my game', chat_id=first.chat_id)
    routing = run.answer['routing']
    assert routing['declared_task'] == 'recolor_part' and 'task_mismatch' not in routing
    assert routing['workflow'] is None, 'a follow-up never re-enrolls the recolor acquisition'
    cards = _cards(seen)
    assert any('TASK RECIPE -- PUT IT IN MY GAME' in text for text in cards)
    assert not any('TASK RECIPE -- RECOLOR A PART' in text for text in cards)
    assert [r['family'] for r in run.answer['recipes']] == ['deliver_to_game']


def test_a_declared_import_chat_gets_the_import_budget(turn, tmp_path, monkeypatch):
    from randall.assistant.tasks import coordinator
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    plain, _ = turn('here is goku, put him on falcon')
    assert plain.task.family == 'randall_turn'
    assert plain.task.cost_budget_usd == coordinator.DEFAULT_COST_BUDGET_USD
    run, _ = turn('here is goku, put him on falcon', {'task': 'model_import'})
    assert run.task.family == 'model_import'
    assert run.task.cost_budget_usd == studio_import.MAX_COST
    assert run.answer['routing']['model_import_mode'] == 'import'


def test_an_ordinary_chats_attached_model_gets_the_import_budget(turn, tmp_path, monkeypatch):
    """The budget follows what makes the turn an import (the attachment), never the words alone."""
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    words, _ = turn('import this model please')
    assert words.task.family == 'randall_turn' and 'model_import_mode' not in words.answer['routing']
    run, seen = turn('import this', {'files': [GLB]})
    assert run.task.family == 'model_import' and run.task.cost_budget_usd == studio_import.MAX_COST
    assert run.answer['routing']['model_import_mode'] == 'import'
    assert set(seen[0][1]) == {'import_model', *studio_import.IMPORT_APP_TOOLS}


def test_the_budget_family_follows_the_declared_task_and_the_attachment():
    assert turn_facts._turn_family('here is goku, put him on falcon', [], 'model_import') == 'model_import'
    assert turn_facts._turn_family('here is goku, put him on falcon', [], None) == 'randall_turn'
    # A follow-up on the saved import is not an import, as in an undeclared chat (_pinned_task lets go once it is
    # done, so the declared task reaching here is None)...
    done = [{'name': 'import_model', 'arguments': {'source': GLB['file_id']},
             'result': {'status': 'done', 'studio_import': {'tool': 'import_model', 'id': 'goku-1'}}}]
    assert turn_facts._turn_family('put it in my game', done,
                                   turn_facts._pinned_task('model_import', done)) == 'randall_turn'
    # ...but before the import is done, testing it in game is part of the import request.
    assert turn_facts._turn_family('put it in my game', [], 'model_import') == 'model_import'
    assert turn_facts._turn_family('save him and test him in game', [], 'model_import') == 'model_import'
    assert turn_facts._turn_family('import this and test him in game', [], None,
                                   attachments=[GLB]) == 'model_import'
    # Other declared tasks: a recolor chat is never budgeted as an import.
    assert turn_facts._turn_family('Fox but spooky', [], 'recolor_part') == 'randall_turn'
    assert turn_facts._turn_family('import this', [], 'recolor_part', attachments=[GLB]) == 'randall_turn'
    # An ordinary chat: an attached model it asks to act on, not the words "import" and "model".
    assert turn_facts._turn_family('import this model', [], None) == 'randall_turn'
    assert turn_facts._turn_family('import this', [], None, attachments=[GLB]) == 'model_import'


def test_the_task_is_the_chats_not_only_this_turns(turn):
    first, _ = turn('Fox but spooky', {'task': 'recolor_part'})
    # A follow-up sent without a pill, and one from a stale client naming another task.
    for context in ({}, {'task': 'model_import'}):
        run, seen = turn('more purple please', context, chat_id=first.chat_id)
        assert run.answer['routing']['declared_task'] == 'recolor_part'
        assert any('TASK RECIPE -- RECOLOR A PART' in text for text in seen[0][0])
    assert store.get(first.chat_id)['task'] == 'recolor_part'


@pytest.mark.parametrize('task,text', [('recolor_part', 'change the css background to a forest'),
                                       ('recolor_part', 'import a model of goku'),
                                       ('model_import', 'recolor my Fox costume red')])
def test_another_tasks_words_get_no_nudge(turn, tmp_path, monkeypatch, task, text):
    """Words never send the user to another chat; the chat's own task and card stay."""
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    run, seen = turn(text, {'task': task})
    routing = run.answer['routing']
    assert routing['declared_task'] == task and 'task_mismatch' not in routing
    assert not any(line.startswith('This chat is a ') for line in seen[0][0])


def test_a_question_in_a_declared_recolor_chat_does_not_open_the_costume(turn):
    """Without the exclusions the named fighter's stock costume is opened by code."""
    run, _ = turn("Don't change anything yet. How should I recolor Fox?", {'task': 'recolor_part'})
    assert run.answer['routing']['workflow'] is None and not run.answer['tools']
    run, _ = turn('give fox a lava look', {'task': 'recolor_part'})
    assert run.answer['routing']['workflow'] == 'recolor'


@pytest.mark.parametrize('task', RETIRED)
def test_a_chat_stored_with_a_retired_task_opens_as_an_ordinary_chat(turn, client, task):
    """A Find a mod or Menu background chat from before 2026-10-03 still loads, reports no task and
    routes as an ordinary chat: no card from its old task, no nudge, even with a model file attached."""
    chat_id = 'c' * 32
    messages = [{'role': 'user', 'content': 'find me a menu background', 'context': {'task': task}},
                {'role': 'assistant', 'content': 'Here are some.', 'tools': []}]
    store.list_chats()      # creates chats.db, with the task column
    conn = sqlite3.connect(config.STORAGE_PATH / 'assistant' / 'chats.db')
    try:
        conn.execute('INSERT INTO chats (id,title,messages,updated,task) VALUES (?,?,?,?,?)',
                     (chat_id, 'old', json.dumps(messages), 1.0, task))
        conn.commit()
    finally:
        conn.close()
    assert [row['task'] for row in client.get('/api/assistant/chats').get_json()['chats']] == [None]
    body = client.get(f'/api/assistant/chats/{chat_id}').get_json()
    assert body['task'] is None and body['messages'][0]['context']['task'] == task
    run, seen = turn('make it purple', chat_id=chat_id)
    routing = run.answer['routing']
    assert routing['declared_task'] is None and 'task_mismatch' not in routing
    assert routing['workflow'] is None and not _cards(seen)
    run, seen = turn('use this', {'files': [GLB]}, chat_id=chat_id)
    routing = run.answer['routing']
    assert 'task_mismatch' not in routing and routing['model_import_mode'] == 'import'
    assert not any(line.startswith('This chat is a ') for line in seen[0][0])


def test_a_model_file_with_recolor_words_in_a_recolor_chat_is_still_an_import(turn, lane_on):
    run, seen = turn('import this model and make it red', {'task': 'recolor_part', 'files': [GLB]})
    routing = run.answer['routing']
    assert routing['task_mismatch'] == 'model_import'
    assert routing['workflow'] is None, 'the lane never runs on a model file'
    assert recipes.mismatch_note('recolor_part', 'model_import') in seen[0][0]


@pytest.mark.parametrize('text,workflow', [
    ('Fox but spooky', 'recolor'),
    # Other words beside the recolor's own no longer hold it back...
    ('Fox but spooky, like his character select portrait', 'recolor'),
    ('make Fox look like his character select portrait but red', 'recolor'),
    # ...only the exclusions do.
    ("Don't change anything yet. How should I recolor Fox?", None),
])
def test_a_recolor_chat_runs_its_workflow_on_any_recolor_request(turn, lane_on, text, workflow):
    run, _ = turn(text, {'task': 'recolor_part'})
    assert 'task_mismatch' not in run.answer['routing']
    assert run.answer['routing']['workflow'] == workflow


@pytest.mark.parametrize('context', [{}, {'task': 'model_import'}, {'task': 'find_mod'}])
def test_the_recolor_workflow_never_runs_outside_a_recolor_chat(turn, lane_on, tmp_path, monkeypatch, context):
    monkeypatch.setenv(studio_import.ROOT_ENV, str(tmp_path / 'imports'))
    for text in ('make a lava Fox skin', 'recolor my Fox costume red', 'make the menu background a lava texture'):
        run, _ = turn(text, context)
        assert run.answer['routing']['workflow'] is None


@pytest.mark.parametrize('text,workflow', [('make Fox red', None), ('recolor Fox red', 'recolor')])
def test_a_model_attached_earlier_does_not_nudge_every_later_message(turn, text, workflow):
    """The GLB is still un-imported and inside the 20-message window the import
    path scans, but it was attached to message 1 (and nudged there). Message 2
    attaches nothing, so it is the recolor chat's own work: the recolor card, no
    nudge. The workflow stays off while a message may be about that model file
    ("make Fox red" acts on something, attached_model.attached_model_waiting)."""
    first, _ = turn('import this', {'task': 'recolor_part', 'files': [GLB]})
    assert first.answer['routing']['task_mismatch'] == 'model_import'
    run, seen = turn(text, chat_id=first.chat_id)
    routing = run.answer['routing']
    assert routing['declared_task'] == 'recolor_part' and 'task_mismatch' not in routing
    assert not any(line.startswith('This chat is a ') for line in seen[0][0])
    assert run.answer['recipes'][0]['family'] == 'recolor_part'
    assert routing['workflow'] == workflow


def test_a_zip_import_in_a_recolor_chat_is_the_chats_own_work(turn):
    zip_file = {'file_id': 'e' * 32, 'name': 'kermit.zip', 'extension': '.zip'}
    run, seen = turn('import this zip and recolor Kermit red', {'task': 'recolor_part', 'files': [zip_file]})
    assert 'task_mismatch' not in run.answer['routing']
    assert run.answer['recipes'][0]['family'] == 'recolor_part'


def test_an_attached_model_in_a_recolor_chat_gets_the_import_nudge(turn):
    run, seen = turn('import this', {'task': 'recolor_part', 'files': [GLB]})
    routing = run.answer['routing']
    assert routing['task_mismatch'] == 'model_import' and routing['attached_model'] is True
    assert recipes.mismatch_note('recolor_part', 'model_import') in seen[0][0]
    assert routing['workflow'] is None and routing['fast_lane_active'] is False
    assert 'model_import_mode' not in routing, 'no import starts here'
    assert 'import_model' not in seen[0][1]


def _done_import(monkeypatch, root, status='done'):
    """import_model's stand-in (its job is tests/backend/test_assistant_import_job.py). -> its call."""
    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        (root / 'goku').mkdir(parents=True, exist_ok=True)
        (root / 'goku' / 'project.json').write_text('{}', encoding='utf-8')
        reply = dict(status=status, project='goku', stages=[], decisions=[], pictures=[], cost_usd=0.)
        if status == 'needs_user':
            reply['question'] = {'title': 'Which fighter?', 'options': ['Falcon', 'Fox']}
        return reply
    monkeypatch.setattr(import_job, 'run', run)
    source = mod_files.register(b'PK\x05\x06' + b'\0' * 18, 'goku.zip')
    return _call('import_model', {'source': source['file_id'], 'fighter': 'Falcon'})


@pytest.mark.parametrize('status,pinned', [('done', False), ('needs_user', True), ('failed', True)])
def test_a_declared_import_chat_lets_go_once_its_import_is_done(turn, tmp_path, monkeypatch, status, pinned):
    root = tmp_path / 'imports'
    monkeypatch.setenv(studio_import.ROOT_ENV, str(root))
    first, seen = turn('goku on falcon', {'task': 'model_import'}, plan=[_done_import(monkeypatch, root, status)])
    assert first.answer['tools'][0]['result']['status'] == status
    run, seen = turn('search my vault for the goku you made', chat_id=first.chat_id)
    routing = run.answer['routing']
    assert routing['declared_task'] == 'model_import'
    if pinned:      # still importing: the studio's roster
        assert routing['model_import_mode'] == 'import'
        assert set(seen[0][1]) == {'import_model', *studio_import.IMPORT_APP_TOOLS}
    else:           # a turn about the costume it made: the app's own roster, and import_model for another fighter
        assert 'model_import_mode' not in routing
        assert 'search_vault' in seen[0][1] and 'import_model' in seen[0][1]
        assert run.task.family == 'randall_turn'


def _import_reply(status=None, project='goku', **fields):
    """An import_model receipt as the transcript keeps it, tagged as studio_import._execute_import tags it
    (`id` None: refused before the import ran)."""
    result = dict(fields, studio_import={'tool': 'import_model', 'id': project})
    if status:
        result['status'] = status
    return {'name': 'import_model', 'status': 'done', 'result': result}


QUESTION = {'title': 'Which fighter?', 'options': ['Falcon', 'Fox']}


@pytest.mark.parametrize('later,done', [
    ([], True),
    ([_import_reply(project=None, error='source must be the file ID of the attached model')], True),
    ([_import_reply(error='RuntimeError: the import crashed')], True),
    ([_import_reply('needs_user', question=QUESTION)], False),
    ([_import_reply('needs_user', question=QUESTION, error='That answer was not taken')], False),
    ([_import_reply('needs_user', question=QUESTION), _import_reply(error='RuntimeError: crashed')], False),
    ([_import_reply('failed')], False),
    ([_import_reply('refused')], False),
], ids=['done', 'refused-before-it-ran', 'error', 'question', 'refused-answer', 'question-then-error',
        'failed', 'refused-source'])
def test_an_import_is_done_by_its_newest_reply_as_studio_import_reads_it(later, done):
    """A call refused before it ran (no project) or an `error` reply after a finished import
    neither re-pins the chat nor asks anything; an older import that stopped on a question (or refused its
    model), or a failed one, does pin it."""
    receipts = [_import_reply('done'), *later]
    assert turn_facts._import_done(receipts) is done
    assert turn_facts._pinned_task('model_import', receipts) == (None if done else 'model_import')
    assert turn_facts._pinned_task('recolor_part', receipts) == 'recolor_part'


def test_a_refused_import_call_after_a_finished_import_does_not_pin_the_chat_again(turn, tmp_path, monkeypatch):
    root = tmp_path / 'imports'
    monkeypatch.setenv(studio_import.ROOT_ENV, str(root))
    first, _ = turn('goku on falcon', {'task': 'model_import'}, plan=[_done_import(monkeypatch, root)])
    # An import turn by its attached model, whose import_model call is refused before it runs (not the
    # attached file's ID).
    second, _ = turn('import this', {'files': [GLB]}, chat_id=first.chat_id,
                     plan=[_call('import_model', {'source': 'vegeta.glb', 'fighter': 'Falcon'})])
    assert second.answer['routing']['model_import_mode'] == 'import'
    refused = second.answer['tools'][0]['result']
    assert refused['error'] and refused['studio_import'] == {'tool': 'import_model', 'id': None}
    run, seen = turn('search my vault for the goku you made', chat_id=first.chat_id)
    routing = run.answer['routing']
    assert routing['declared_task'] == 'model_import' and 'model_import_mode' not in routing
    assert 'search_vault' in seen[0][1] and 'import_model' in seen[0][1], 'offered for another fighter'
    assert run.task.family == 'randall_turn'


# Recolor words in an import chat whose import has not finished: still an import chat.
BELT = 'keep the cape but make the belt red'


@pytest.mark.parametrize('status', ['needs_user', 'failed'])
def test_a_message_after_an_import_that_did_not_finish_stays_in_the_import_never_a_mismatch(turn, tmp_path,
                                                                                         monkeypatch, status):
    """The chat is still trying to import, whatever task the next message's words name: no nudge (and no "Start a
    Recolor chat" button). An import from before rigswap that stopped on a question is not carried on (there is no
    question to answer any more): it is one that did not finish, like a failed one, and gets no card of its own."""
    root = tmp_path / 'imports'
    monkeypatch.setenv(studio_import.ROOT_ENV, str(root))
    first, _ = turn('goku on falcon', {'task': 'model_import'}, plan=[_done_import(monkeypatch, root, status)])
    run, seen = turn(BELT, chat_id=first.chat_id)
    routing = run.answer['routing']
    assert routing['declared_task'] == 'model_import' and 'task_mismatch' not in routing
    assert not any(line.startswith('This chat is a ') for line in seen[0][0])
    assert routing['model_import_mode'] == 'import'
    assert set(seen[0][1]) == {'import_model', *studio_import.IMPORT_APP_TOOLS}
    assert not [line for line in _cards(seen) if 'AN UNFINISHED IMPORT' in line]
    assert run.task.family == 'model_import'


def test_a_card_button_download_in_a_declared_recolor_chat_enrolls_nothing(turn, monkeypatch):
    first, _ = turn('Fox but spooky', {'task': 'recolor_part'})
    assert first.answer['routing']['workflow'] == 'recolor'
    _stub(monkeypatch, 'download_website_mod', {'imported_count': 0, 'note': 'stub'})
    run = engine.start_download(first.chat_id, 123)
    list(live_runs.stream(run))
    assert run.answer['routing']['declared_task'] == 'recolor_part'
    assert run.answer['routing']['workflow'] is None


def test_an_ask_chat_is_not_declared_by_a_later_turn(turn):
    first, _ = turn('hello there')
    run, seen = turn('Fox but spooky', {'task': 'recolor_part'}, chat_id=first.chat_id)
    assert run.answer['routing']['declared_task'] is None
    assert run.answer['routing']['workflow'] is None
    assert store.get(first.chat_id)['task'] is None


@pytest.mark.parametrize('text', ['Fox but spooky', 'put it in my game',
                                  'download the Kermit skin and give it a lava look',
                                  'recolor fox to match the css'])
def test_no_nudge_without_a_confident_other_task(turn, text):
    run, seen = turn(text, {'task': 'recolor_part'})
    assert 'task_mismatch' not in run.answer['routing']
    assert not any(line.startswith('This chat is a ') for line in seen[0][0])
