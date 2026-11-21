"""The model import in Randall's chat engine (model_import/chat/studio_import.py): routing and roster.

An import turn is offered ``import_model`` (its job is covered by tests/backend/test_assistant_import_job.py)
and the few app tools an import uses; every other turn, one about a model imported earlier included,
is a normal Randall turn: the app's own roster and no import card.

No model request and no real rigswap run: the provider is a stand-in, and so is import_model's job
(it writes the project folder and a picture, the way the real one does).
"""
import json
from pathlib import Path

import pytest
from PIL import Image

from randall.assistant import engine, live_runs, store, tools, vision
from shared import mod_files
from randall.model_import.chat import import_job, studio_import, textures


@pytest.fixture
def studio_root(vault, tmp_path, monkeypatch):
    root = tmp_path / 'imports'
    monkeypatch.setenv(studio_import.ROOT_ENV, str(root))
    return root


def _png(path, colour=(200, 40, 40)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (160, 120), colour).save(path)
    return path


def _attached_zip():
    return mod_files.register(b'PK\x05\x06' + b'\0' * 18, 'mokey.zip')


IMPORT_TURN = 'import this model onto Pikachu'


def _imported(monkeypatch, studio_root, import_id='mokey', cost=0.):
    """import_model's stand-in: the project folder, a picture and a done reply. -> the tool call that imports it."""
    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        folder = studio_root / import_id
        folder.mkdir(parents=True, exist_ok=True)
        picture = _png(folder / 'finish' / 'csp.png')
        return dict(status='done', project=import_id, pictures=[str(picture)], cost_usd=cost)
    monkeypatch.setattr(import_job, 'run', run)
    source = _attached_zip()
    return source, ('import_model', {'source': source['file_id'], 'fighter': 'Pikachu'})


def _tool_call(index, name, arguments, **extra):
    return {'type': 'completion', **extra, 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': f'c{index}', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}


def _names(roster):
    return [s['function']['name'] for s in roster]


def _systems(messages):
    return [str(m.get('content') or '') for m in messages if m['role'] == 'system']


IMPORT_ROSTER = {'import_model'} | set(studio_import.IMPORT_APP_TOOLS)


# ------------------------------------------------------------------ routing

def test_a_turn_about_an_imported_model_is_a_normal_turn(studio_root, monkeypatch):
    """No fix mode: after the import, "the tail clips through the floor" gets the app's own roster (and import_model,
    for the same model on another fighter) and no import card."""
    source, call = _imported(monkeypatch, studio_root)
    seen, plan = [], [call]

    def provider(messages, schemas, key, cancelled):
        seen.append((_names(schemas), messages[:]))
        yield _tool_call(len(seen), *plan.pop()) if plan else {
            'type': 'completion', 'message': {'role': 'assistant', 'content': 'Okay.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, IMPORT_TURN, {'files': [source]}, request_key='k')
    list(live_runs.stream(run))
    assert set(seen[0][0]) == IMPORT_ROSTER
    asked = len(seen)
    list(live_runs.stream(engine.start(run.chat_id, 'the tail clips through the floor', {}, request_key='k')))
    names, messages = seen[asked]
    assert set(names) - {'import_model'} <= set(_names(tools.SCHEMAS)), "the app's own roster"
    assert 'search_vault' in names and 'import_model' in names, 'import_model for another fighter'
    assert names.count('test_in_game') <= 1
    system = _systems(messages)
    assert not any('TASK RECIPE -- IMPORT A MODEL' in text for text in system)
    saved = store.get(run.chat_id)['messages'][-1]
    assert 'model_import_mode' not in saved['routing'] and not saved['routing'].get('model_import_v2')


def test_other_turns_keep_the_apps_roster(studio_root, monkeypatch):
    seen = []

    def provider(messages, schemas, key, cancelled):
        seen.append(_names(schemas))
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Okay.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'find my Marth skins', {}, request_key='k')
    list(live_runs.stream(run))
    assert set(seen[0]) <= set(_names(tools.SCHEMAS))   # the app's own roster
    assert 'clean_source' not in seen[0] and 'search_vault' in seen[0]


def test_each_turn_of_an_import_chat_picks_its_own_roster(studio_root, monkeypatch):
    """Routing is per turn. After an import, words that name no task ("keep going"), words that name
    another task and words that ask for a model import are all normal turns (offered import_model for the same model on
    another fighter); a new model attached and asked about is an import turn again."""
    source, call = _imported(monkeypatch, studio_root, 'm1')
    rounds = []

    def provider(messages, schemas, key, cancelled):
        rounds.append(_names(schemas))
        if len(rounds) == 1:
            yield _tool_call(0, *call)
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Okay.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, IMPORT_TURN, {'files': [source]}, request_key='k')
    list(live_runs.stream(run))
    assert set(rounds[0]) == IMPORT_ROSTER
    second = mod_files.register(b'PK\x05\x06' + b'\0' * 18, 'second.zip')
    for text, context, importing in (('keep going', {}, False),
                                     ('search the website for a Marth costume', {}, False),
                                     ('lets do another model import', {}, False),
                                     ('import this one too', {'files': [second]}, True),
                                     ('keep going', {}, False)):
        asked = len(rounds)
        list(live_runs.stream(engine.start(run.chat_id, text, context, request_key='k')))
        assert len(rounds) == asked + 1, text
        if importing:
            assert set(rounds[-1]) == IMPORT_ROSTER, text
        else:
            assert 'search_vault' in rounds[-1] and 'import_model' in rounds[-1], text


# ------------------------------------------------------------------ roster

def test_an_import_turn_is_offered_import_model_and_its_few_app_tools_only():
    offered = studio_import.offer(tools.SCHEMAS)
    names = _names(offered)
    assert len(names) == len(set(names))
    assert set(names) == IMPORT_ROSTER
    assert studio_import.names() == {'import_model'}
    assert offered[0] == import_job.SCHEMA


def test_the_import_app_tools_are_app_tools_import_model_does_not_replace():
    assert set(studio_import.IMPORT_APP_TOOLS) <= set(_names(tools.SCHEMAS))
    assert not set(studio_import.IMPORT_APP_TOOLS) & studio_import.names()
    # The old import tools are gone from the app's roster.
    assert not [name for name in _names(tools.SCHEMAS) if name == 'import_model' or name.startswith('model_')]


def test_an_app_tool_the_turn_withheld_stays_withheld():
    roster = [s for s in tools.SCHEMAS if s['function']['name'] not in studio_import.IMPORT_APP_TOOLS]
    assert set(_names(studio_import.offer(roster))) == {'import_model'}


def test_a_studio_tool_is_not_a_model_import_tool(studio_root):
    for name in ('line_up', 'clean_source', 'fresh_eyes', 'import_status'):
        with pytest.raises(ValueError, match='not a model-import tool'):
            studio_import.prepare(name, {'project': 'a'})
    reply = studio_import.execute(tools.PreparedCall(studio_import.PREFIX + 'line_up', '{"project": "a"}',
                                                     'null', 'null', 'automatic'))
    assert 'not a model-import tool' in reply['error']


def test_the_import_card_offers_no_fix_tools():
    card = studio_import.card()
    assert card.startswith('TASK RECIPE -- IMPORT A MODEL')
    assert 'fix tools' not in card and 'fix mode' not in card.lower()
    assert studio_import.describe()['operations'] == ['import_model']
    assert 'FIGHTER PICKED' not in card


# ------------------------------------------------------------------ the picked fighter (context.fighter)

@pytest.mark.parametrize('value,fighter', [
    ('Fox', 'Fox'), ('fox', 'Fox'), ('C. Falcon', 'C. Falcon'), ('captain falcon', 'C. Falcon'),
    ('falcon', 'C. Falcon'), ('Mr. Game & Watch', 'Mr. Game & Watch'), ('young_link', 'Young Link'),
    ('Ice Climbers', 'Ice Climbers'),                  # the import refuses it, with its reason
    ('Goku', None), ('', None), ('   ', None), (None, None), (7, None), (['Fox'], None), ('x' * 41, None),
])
def test_a_picked_fighter_is_read_as_the_importer_names_it(value, fighter):
    assert studio_import.fighter_choice(value) == fighter


def test_the_chats_picked_fighter_is_its_newest_user_messages_known_one():
    assert studio_import.chosen_fighter([]) is None
    messages = [{'role': 'user', 'content': 'goku', 'context': {'task': 'model_import', 'fighter': 'falcon'}},
                {'role': 'assistant', 'content': 'ok', 'context': {'fighter': 'Fox'}},     # never an assistant's
                {'role': 'user', 'content': 'go', 'context': {}},
                {'role': 'user', 'content': 'go', 'context': {'fighter': 'not a fighter'}},
                {'role': 'user', 'content': 'go', 'context': 'not a dict'}]
    assert studio_import.chosen_fighter(messages) == 'C. Falcon'
    messages.append({'role': 'user', 'content': 'actually', 'context': {'fighter': 'Marth'}})
    assert studio_import.chosen_fighter(messages) == 'Marth'


def test_a_new_import_that_names_no_fighter_goes_on_the_picked_one():
    source = 'a' * 32

    def prepared(arguments, fighter):
        return json.loads(studio_import.prepare('import_model', arguments, fighter=fighter).arguments)
    assert prepared({'source': source}, 'C. Falcon') == {'source': source, 'fighter': 'C. Falcon'}
    assert prepared({'source': source, 'fighter': ''}, 'C. Falcon')['fighter'] == 'C. Falcon'
    # A fighter the call names is the user's word in the chat: it stays.
    assert prepared({'source': source, 'fighter': 'Marth'}, 'C. Falcon')['fighter'] == 'Marth'
    # Nothing picked changes nothing. A change to a finished import is what looks wrong, in words: another fighter is
    # a new import, never a change (the old importer's {kind, value} is refused).
    assert prepared({'source': source}, None) == {'source': source}
    with pytest.raises(ValueError, match='change is what the user says looks wrong, in words'):
        prepared({'project': 'goku-1', 'change': {'kind': 'fighter', 'value': 'Fox'}}, 'C. Falcon')


def test_the_import_card_names_the_picked_fighter():
    card = studio_import.card(fighter='C. Falcon')
    assert 'FIGHTER PICKED BY THE USER (data): C. Falcon.' in card and 'do not ask which fighter' in card


def test_the_import_card_says_when_the_tools_are_not_ready_and_any_import_then_starts_nothing(monkeypatch):
    """A packaged app whose model import tools are not downloaded: the card says so before the first round, and the
    engine drops the words written before an import_model call, which only comes back needs_tools."""
    from randall.model_import.chat import import_job
    need = {'state': 'not_installed', 'download_bytes': 779_000_000, 'needed_bytes': 779_000_000,
            'disk_bytes': 2_200_000_000}
    card = studio_import.card(tools=need)
    assert "THE IMPORT'S TOOLS ARE NOT READY" in card and import_job.TOOLS_MISSING in card
    assert 'never "Starting now"' in card
    assert "TOOLS ARE NOT READY" not in studio_import.card()
    assert import_job.TOOLS_OUTDATED in studio_import.card(tools=dict(need, state='update_needed'))
    new = {'name': 'import_model', 'arguments': {'source': 'a' * 32}}
    change = {'name': 'import_model', 'arguments': '{"project": "neos-1", "change": "the legs"}'}
    assert studio_import.starts_nothing(new, None, need) and studio_import.starts_nothing(change, None, need)
    assert not studio_import.starts_nothing(new, None, None), 'tools ready, textures not asked: it starts'
    assert not studio_import.starts_nothing({'name': 'search_vault', 'arguments': {}}, None, need)
    monkeypatch.setattr(import_job, 'tools_needed', lambda: need)
    assert studio_import.tools_missing() == need


def test_an_import_chat_started_with_a_picked_fighter_imports_onto_it(studio_root, monkeypatch):
    """The fighter picker's choice (context.fighter on the chat's first message) reaches the job when the model
    leaves fighter out, so the import never asks which fighter (D2 runs only when no fighter was named)."""
    jobs, seen = [], []

    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        jobs.append(dict(args))
        (studio_root / 'm1').mkdir(parents=True, exist_ok=True)
        return dict(status='done', project='m1', fighter=args.get('fighter'), pictures=[], cost_usd=0.)
    monkeypatch.setattr(import_job, 'run', run)
    source = _attached_zip()
    plan = [('import_model', {'source': source['file_id']})]

    def provider(messages, schemas, key, cancelled):
        seen.append(_systems(messages))
        yield _tool_call(len(seen), *plan.pop()) if plan else {
            'type': 'completion', 'message': {'role': 'assistant', 'content': 'Done.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run_ = engine.start(None, 'here is goku', {'task': 'model_import', 'fighter': 'captain falcon',
                                               'files': [source]}, request_key='k')
    list(live_runs.stream(run_))
    assert [job.get('fighter') for job in jobs] == ['C. Falcon']
    assert any('FIGHTER PICKED BY THE USER (data): C. Falcon.' in text for text in seen[0])
    receipt = run_.answer['tools'][0]
    assert receipt['arguments']['fighter'] == 'C. Falcon', 'the receipt shows what the import was given'


# ------------------------------------------------------------------ an import turn

def test_an_import_turn_shows_its_pictures_and_keeps_the_ledger(studio_root, monkeypatch):
    source, call = _imported(monkeypatch, studio_root, cost=0.004)
    seen, plan = [], [call]

    def provider(messages, schemas, key, cancelled):
        seen.append(messages[:])
        yield (_tool_call(len(seen), *plan.pop(), cost_usd=0.01, usage={'prompt_tokens': 100, 'completion_tokens': 10})
               if plan else {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Imported.'}})
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, IMPORT_TURN, {'files': [source]}, request_key='k')
    list(live_runs.stream(run))
    answer = store.get(run.chat_id)['messages'][-1]
    assert [t['name'] for t in answer['tools']] == ['import_model'] and answer['tools'][0]['status'] == 'done'
    assert (answer.get('cost_parts') or {}).get('model_import') == pytest.approx(0.004)
    # The pictures reached the next request as images, labelled with their paths.
    images = [part for message in seen[1] if message['role'] == 'user' and isinstance(message['content'], list)
              for part in message['content']]
    assert any(p['type'] == 'image_url' for p in images)
    assert any(p['type'] == 'text' and 'csp.png' in p['text'] for p in images)
    folder = studio_root / 'mokey'
    row = json.loads((folder / 'randall.jsonl').read_text().splitlines()[-1])
    assert row['tool_calls'] == 1 and row['tools'] == {'import_model': 1}


def test_the_costume_file_is_attached_only_from_inside_the_import(studio_root):
    folder = studio_root / 'c'
    dat = folder / 'rigswap' / 'PlFxNr.dat'
    dat.parent.mkdir(parents=True)
    dat.write_bytes(b'HSD costume stand-in' * 8)
    reply = {'status': 'done', 'dat': str(dat), 'files': [{'file_id': 'p', 'extension': '.png'}]}
    studio_import._attach_costume(reply, folder.resolve())
    assert [f['extension'] for f in reply['files']] == ['.png', '.dat'], 'after the pictures'
    assert reply['files'][1]['name'] == 'PlFxNr.dat' and reply['files'][1]['path'] == str(dat.resolve())
    elsewhere = studio_root / 'other.dat'
    elsewhere.write_bytes(b'x' * 32)
    for value in (str(elsewhere), str(folder / 'missing.dat'), str(folder / 'pictures' / 'a.png'), None):
        other = {'dat': value}
        studio_import._attach_costume(other, folder.resolve())
        assert 'files' not in other, value


def test_a_failed_import_still_shows_its_pictures(studio_root):
    folder = studio_root / 'f'
    picture = _png(folder / 'rigswap' / 'failure.png')
    reply = {'status': 'failed', 'error': 'weights not read', 'pictures': [str(picture)],
             'studio_import': {'tool': 'import_model', 'id': 'f'}}
    studio_import._attach_pictures(reply, folder.resolve())
    blocks = vision.tool_images('import_model', reply)
    assert [b['type'] for b in blocks] == ['text', 'image_url']
    assert str(picture.resolve()) in blocks[0]['text']


# ------------------------------------------------------------------ "...and test him in game"

def test_an_import_request_that_asks_to_test_in_game_plays_it_in_the_same_turn(studio_root, monkeypatch):
    """The words "test him in game" in the import request used to leave the import turn without a play-session tool,
    so Randall could only promise the test for later (and talked about game copies it does not need). The import
    turn is offered test_in_game, and the call after the import reaches the play session in the same turn."""
    source, call = _imported(monkeypatch, studio_root)
    started = []

    def play(**args):
        started.append({key: value for key, value in args.items() if key not in ('runtime', 'chat_id')})
        return {'game_test': {'session_id': 's1', 'running': True}}
    monkeypatch.setitem(tools.REGISTRY, 'test_in_game', tools.ToolSpec('automatic', play))
    rounds = []
    plan = [call, ('test_in_game', {'action': 'start', 'kind': 'costume', 'character': 'Pikachu',
                                    'skin_id': 'mokey-1'})]

    def provider(messages, schemas, key, cancelled):
        rounds.append((_names(schemas), messages[:]))
        if len(rounds) <= len(plan):
            yield _tool_call(len(rounds), *plan[len(rounds) - 1])
        else:
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'He is saved; playing now.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    text = 'import this model onto Pikachu, save him to my vault and test him in game'
    run = engine.start(None, text, {'files': [source], 'task': 'model_import'}, request_key='k')
    list(live_runs.stream(run))
    names, messages = rounds[0]
    assert set(names) == IMPORT_ROSTER and 'test_in_game' in names
    assert any('TASK RECIPE -- IMPORT A MODEL' in system and 'test_in_game' in system
               for system in _systems(messages))
    assert run.answer['routing'].get('model_import_mode') == 'import'
    assert started == [{'action': 'start', 'kind': 'costume', 'character': 'Pikachu', 'skin_id': 'mokey-1'}]
    assert [tool['name'] for tool in run.answer['tools']] == ['import_model', 'test_in_game']
    assert run.answer['status'] == 'done' and not run.answer.get('error')


def test_a_saved_import_tells_the_chat_how_to_start_its_play_session(monkeypatch, tmp_path):
    monkeypatch.setattr(import_job, '_save', lambda folder, dat, fighter, name, receipts: {
        'vault': {'name': 'Tung', 'character': 'Young Link', 'skin_id': 'tung-1'}, 'installable': True})
    reply = import_job._outcome('tung-1a', tmp_path, dict(status='done', fighter='YoungLink', seconds=80.),
                                fighter='Young Link', name='Tung', log=lambda *_: None)
    hint = reply['next']
    assert 'test_in_game' in hint and '"Young Link"' in hint and '"tung-1"' in hint
    assert 'needs no game copy' in hint
    assert hint.count('The in-game test runs only if they ask for it.') == 0
    assert hint.endswith('the in-game test runs only if they ask for it.')
    # take4 (2026-10-06): the summary was written, test_in_game called in the same response, then the summary again.
    # The play instruction comes first and holds the one closing reply until the session has started.
    assert hint.startswith('First, in game:') and 'no text before the call' in hint
    assert hint.index('test_in_game') < hint.index('do not repeat them')
    assert 'never say it is running' in hint
    assert 'Want to see him in a match?' in hint, 'otherwise it is offered in a few words, not started'


# ------------------------------------------------------------------ the fighter is the user's, or the import's

TUNG = ('this is tung tung tung sahur. put him in melee on whichever fighter he actually fits, keep his textures, '
        'save him to my vault and test him in game.')


@pytest.mark.parametrize('text,fighter', [
    (TUNG, None), ('import this please', None), ('make him a costume, keep his colours', None),
    ('put him on Young Link', 'Young Link'), ('falcon pls', 'C. Falcon'), ('Captain Falcon!', 'C. Falcon'),
    ('on mr. game & watch', 'Mr. Game & Watch'), ("make it marth's costume", 'Marth'),
    ('put him on g&w', 'Mr. Game & Watch'), ('use dr_mario', 'Dr. Mario'), ('YL', 'Young Link'),
    ('foxglove texture', None), ('a marthian', None),          # whole words only
])
def test_a_fighter_the_user_names_is_found_in_their_words(text, fighter):
    assert studio_import.named_fighter(text) == fighter
    assert studio_import.named_fighter(['first message', text]) == fighter


def test_a_fighter_the_model_chose_itself_is_dropped_so_the_import_fits_him():
    """2026-10-06: "...on whichever fighter he actually fits..." was sent as fighter "Mr. Game & Watch": the import's
    fit step was skipped (D2: requested, nothing to ask) and G&W drew him as a black silhouette."""
    source = 'a' * 32

    def prepared(arguments, words, fighter=None):
        return json.loads(studio_import.prepare('import_model', arguments, fighter=fighter, words=words).arguments)
    guessed = {'source': source, 'fighter': 'Mr. Game & Watch'}
    # Unnamed and unpicked: dropped, the import's fit decides.
    assert prepared(guessed, [TUNG]) == {'source': source}
    # Named in the user's words (this message or an earlier one): kept.
    assert prepared({'source': source, 'fighter': 'Young Link'}, ['put him on Young Link'])['fighter'] == 'Young Link'
    assert prepared({'source': source, 'fighter': 'C. Falcon'}, ['falcon', 'go'])['fighter'] == 'C. Falcon'
    # Picked in the chooser: the picked one, whatever the model guessed.
    assert prepared({'source': source, 'fighter': 'C. Falcon'}, [TUNG], 'C. Falcon')['fighter'] == 'C. Falcon'
    assert prepared(guessed, [TUNG], 'Young Link')['fighter'] == 'Young Link'
    assert prepared({'source': source}, [TUNG], 'Young Link')['fighter'] == 'Young Link'
    # Words not known (no chat): the call's own fighter stays, as before.
    assert prepared(guessed, None)['fighter'] == 'Mr. Game & Watch'
    # A fighter rigswap does not target is refused at once, naming the ones it does.
    with pytest.raises(ValueError, match='cannot go on Ice Climbers'):
        prepared({'source': source, 'fighter': 'Ice Climbers'}, ['put him on the ice climbers'])


def test_an_import_turn_drops_a_fighter_the_user_never_named(studio_root, monkeypatch):
    jobs = []

    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        jobs.append(dict(args))
        (studio_root / 't1').mkdir(parents=True, exist_ok=True)
        return dict(status='done', project='t1', fighter='Young Link', pictures=[],
                    cost_usd=0.)
    monkeypatch.setattr(import_job, 'run', run)
    source = _attached_zip()
    plan = [('import_model', {'source': source['file_id'], 'fighter': 'Mr. Game & Watch'})]

    def provider(messages, schemas, key, cancelled):
        yield _tool_call(1, *plan.pop()) if plan else {
            'type': 'completion', 'message': {'role': 'assistant', 'content': 'Done.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    run_ = engine.start(None, TUNG, {'task': 'model_import', 'files': [source]}, request_key='k')
    list(live_runs.stream(run_))
    assert [job.get('fighter') for job in jobs] == [None]
    assert 'fighter' not in run_.answer['tools'][0]['arguments'], 'the receipt shows what the import was given'


# ------------------------------------------------------------------ one closing reply for import + play

CLOSING = 'He is on Young Link and in your vault; the match opens on the right.'


def _import_then_play(monkeypatch, studio_root, interim, play=True):
    """An import turn whose round after the saved import writes `interim` (and calls test_in_game when `play`),
    then a closing reply. -> (run, events, each round's messages)"""
    def run_job(args, *, key=None, progress=None, cancelled=None, relay=None):
        (studio_root / 'tung').mkdir(parents=True, exist_ok=True)
        return dict(status='done', project='tung', pictures=[], cost_usd=0.,
                    saved={'character': 'Young Link', 'skin_id': 'tung-1', 'name': 'Tung'})
    monkeypatch.setattr(import_job, 'run', run_job)
    monkeypatch.setitem(tools.REGISTRY, 'test_in_game', tools.ToolSpec(
        'automatic', lambda **args: {'game_test': {'session_id': 's1', 'running': True}}))
    source = _attached_zip()
    rounds = []

    def said(text, calls=None):
        yield {'type': 'delta', 'content': text[:5]}
        yield {'type': 'delta', 'content': text[5:]}
        yield {'type': 'completion', 'message': {'role': 'assistant', 'content': text,
                                                 **({'tool_calls': calls} if calls else {})}}

    def provider(messages, schemas, key, cancelled):
        rounds.append(messages[:])
        if len(rounds) == 1:
            yield from said('Starting now.', [{'id': 'c1', 'function': {
                'name': 'import_model', 'arguments': json.dumps({'source': source['file_id']})}}])
        elif len(rounds) == 2:
            yield from said(interim, [{'id': 'c2', 'function': {'name': 'test_in_game', 'arguments': json.dumps(
                {'action': 'start', 'kind': 'costume', 'character': 'Young Link', 'skin_id': 'tung-1'})}}]
                if play else None)
        else:
            yield from said(CLOSING)
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, TUNG, {'task': 'model_import', 'files': [source]}, request_key='k')
    events = list(live_runs.stream(run))
    return run, events, rounds


def _streamed(events):
    """The text the stream sent (its delta events, as server-sent lines)."""
    sent = [json.loads(line[len('data: '):]) for line in events if line.startswith('data: ')]
    return ''.join(e.get('content') or '' for e in sent if e.get('type') == 'delta')


@pytest.mark.parametrize('interim', [
    'Now the in-game test.',
    'Tung Tung Tung Sahur is saved to your vault on Young Link, textures kept. Starting the in-game test now.'])
def test_words_before_the_play_session_are_not_a_second_reply(studio_root, monkeypatch, interim):
    """2026-10-06 live runs: after the import the model wrote a line (or its whole summary) with the test_in_game
    call, then the closing reply after it: two near-duplicate messages. Only the closing one shows."""
    run, events, rounds = _import_then_play(monkeypatch, studio_root, interim)
    answer = store.get(run.chat_id)['messages'][-1]
    assert [t['name'] for t in answer['tools']] == ['import_model', 'test_in_game']
    assert answer['content'] == 'Starting now.\n\n' + CLOSING
    assert interim not in _streamed(events), 'never streamed either'
    # Both cards sit between the opening line and the one closing reply.
    assert [t['content_offset'] for t in answer['tools']] == [len('Starting now.'), len('Starting now.\n\n')]
    assert answer['dropped_interim'] == [interim]
    # The model's own context keeps what it said.
    assert any(m.get('role') == 'assistant' and m.get('content') == interim for m in rounds[2])


def test_words_after_an_import_with_no_play_session_are_the_reply(studio_root, monkeypatch):
    run, events, _ = _import_then_play(monkeypatch, studio_root, 'He is saved on Young Link. Want to see him?',
                                       play=False)
    answer = store.get(run.chat_id)['messages'][-1]
    assert answer['content'] == 'Starting now.\n\nHe is saved on Young Link. Want to see him?'
    assert 'dropped_interim' not in answer
    assert 'He is saved on Young Link. Want to see him?' in _streamed(events)


# ------------------------------------------------------------------ a model without its textures: nothing starts

# 0.9.0 smoke (a bare sack_boy.fbx, a bare Clank.obj): the card asked for "Starting now: ..." before import_model,
# and the call then came back needs_textures: "Starting now: I'll put Sack Boy on Ness and save him to your vault.
# ... nothing was imported yet."
STARTING = "Starting now: I'll put Clank on Fox and save him to your vault."
ASKED = 'Clank came without Clank.mtl, so nothing was imported yet. Attach a ZIP with it, or say to go on without it.'


def _bare_obj(name='Clank.obj', body=b'mtllib Clank.mtl\r\nv 0 0 0\r\n'):
    return mod_files.register(body, name)


def _textures_job(monkeypatch, studio_root, jobs):
    """import_model's stand-in, with the import's own texture check (import_job.start): needs_textures for a model
    that lacks what it names, unless untextured; else a done import."""
    def run(args, *, key=None, progress=None, cancelled=None, relay=None):
        jobs.append(dict(args))
        gap = None if args.get('untextured') else textures.missing(args['source'])
        if gap:
            return import_job.textures_reply(gap)
        (studio_root / 'clank').mkdir(parents=True, exist_ok=True)
        return dict(status='done', project='clank', pictures=[], cost_usd=0.)
    monkeypatch.setattr(import_job, 'run', run)


def _says(text, calls=None):
    yield {'type': 'delta', 'content': text[:9]}
    yield {'type': 'delta', 'content': text[9:]}
    yield {'type': 'completion', 'message': {'role': 'assistant', 'content': text,
                                             **({'tool_calls': calls} if calls else {})}}


def _import_call(index, **arguments):
    return [{'id': f'c{index}', 'function': {'name': 'import_model', 'arguments': json.dumps(arguments)}}]


def test_a_model_without_its_textures_is_known_before_the_turn_and_named_on_the_card(studio_root):
    bare, whole = _bare_obj(), _bare_obj('Whole.obj', b'v 0 0 0\r\n')
    attached = [dict(bare), dict(whole), {'file_id': 'e' * 32, 'name': 'notes.png', 'extension': '.png'}]
    found = studio_import.without_textures(attached, [])
    assert found == {bare['file_id']: {'name': 'Clank.obj', 'warning': (
        'Clank.obj came without the materials file Clank.mtl. Without it the model would import with no textures '
        '(all white).')}}
    # Checked where the import checks it: the staged upload, alone in its folder.
    assert (studio_root / '.uploads' / bare['file_id'] / 'Clank.obj').is_file()
    # One imported already (its call made a project) is not waiting; one that only asked for textures still is.
    imported = [dict(name='import_model', arguments={'source': bare['file_id']},
                     result={'status': 'done', 'studio_import': {'tool': 'import_model', 'id': 'clank'}})]
    assert studio_import.without_textures(attached, imported) == {}
    asked = [dict(name='import_model', arguments={'source': bare['file_id']},
                  result={'status': 'needs_textures', 'studio_import': {'tool': 'import_model', 'id': None}})]
    assert list(studio_import.without_textures(attached, asked)) == [bare['file_id']]
    # A file that is not a chat file here is left out, never an error.
    assert studio_import.without_textures([{'file_id': 'f' * 32, 'name': 'gone.obj'}], []) == {}
    card = studio_import.card(bare=found)
    assert 'unless this card says below that the model came without files it needs' in studio_import.IMPORT_CARD
    # 0.9.0 smoke: Randall called the missing Clank.mtl "a texture file"; the card and the recipe name it for what it
    # is.
    assert (f"CAME WITHOUT FILES IT NEEDS (data, checked by the app just now): Clank.obj (file ID {bare['file_id']}). "
            'Clank.obj came without the materials file Clank.mtl.') in card
    assert "an OBJ's .mtl is its materials file, not a texture" in studio_import.IMPORT_CARD
    assert 'names texture files' not in studio_import.IMPORT_CARD
    assert 'write no words before that call (never "Starting now"' in card
    assert 'CAME WITHOUT' not in studio_import.card()


def test_only_a_call_that_will_ask_for_textures_counts():
    bare = {'a' * 32: {'name': 'Clank.obj', 'warning': 'w'}}

    def asks(arguments, name='import_model', found=bare):
        return studio_import.asks_for_textures({'name': name, 'arguments': json.dumps(arguments)}, found)
    assert asks({'source': 'a' * 32})
    assert asks({'source': 'a' * 32, 'fighter': 'Fox', 'untextured': False})
    assert studio_import.asks_for_textures({'name': 'import_model', 'arguments': {'source': 'a' * 32}}, bare)
    assert not asks({'source': 'a' * 32, 'untextured': True}), 'the user said to go on without them: it starts'
    assert not asks({'source': 'a' * 32, 'untextured': 'true'})
    assert not asks({'source': 'b' * 32}), 'another file (a ZIP with the textures)'
    assert not asks({'project': 'clank', 'change': 'the legs look wrong'})
    assert not asks({'source': 'a' * 32}, name='test_in_game')
    assert not asks({'source': 'a' * 32}, found={})
    assert not studio_import.asks_for_textures({'name': 'import_model', 'arguments': '{not json'}, bare)


def test_an_import_of_a_model_without_its_textures_never_says_it_is_starting(studio_root, monkeypatch):
    """The words before a call that will only ask for the textures are dropped, never streamed; the user's answer
    ("go ahead without them") starts the import, and then "Starting now" is said as usual."""
    jobs, rounds = [], []
    _textures_job(monkeypatch, studio_root, jobs)
    clank = _bare_obj()
    plan = [lambda: _says(STARTING, _import_call(1, source=clank['file_id'])),
            lambda: _says(ASKED),
            lambda: _says(STARTING, _import_call(2, source=clank['file_id'], untextured=True)),
            lambda: _says('He is on Fox and in your vault, with no textures.')]

    def provider(messages, schemas, key, cancelled):
        rounds.append(_systems(messages))
        yield from plan[len(rounds) - 1]()
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'import this onto Fox', {'files': [clank]}, request_key='k')
    events = list(live_runs.stream(run))
    answer = store.get(run.chat_id)['messages'][-1]
    assert [t['result']['status'] for t in answer['tools']] == ['needs_textures']
    assert answer['content'] == ASKED, 'only the reply after the call'
    assert 'Starting now' not in _streamed(events), 'never streamed either'
    assert answer['dropped_interim'] == [STARTING]
    assert any(f"CAME WITHOUT FILES IT NEEDS (data, checked by the app just now): Clank.obj (file ID "
               f"{clank['file_id']})" in text for text in rounds[0])
    # The answer: the same source with untextured starts the import, and its opening line is said.
    run = engine.start(run.chat_id, 'nah just go ahead without them', {}, request_key='k')
    events = list(live_runs.stream(run))
    answer = store.get(run.chat_id)['messages'][-1]
    assert [t['result']['status'] for t in answer['tools']] == ['done']
    assert answer['content'] == STARTING + '\n\nHe is on Fox and in your vault, with no textures.'
    assert STARTING in _streamed(events) and 'dropped_interim' not in answer
    assert [bool(job.get('untextured')) for job in jobs] == [False, True]


def test_an_import_of_a_model_with_its_textures_streams_its_opening_line(studio_root, monkeypatch):
    jobs, rounds = [], []
    _textures_job(monkeypatch, studio_root, jobs)
    whole = _bare_obj('Whole.obj', b'v 0 0 0\r\n')
    plan = [lambda: _says(STARTING, _import_call(1, source=whole['file_id'])), lambda: _says('He is in your vault.')]

    def provider(messages, schemas, key, cancelled):
        rounds.append(_systems(messages))
        yield from plan[len(rounds) - 1]()
    monkeypatch.setattr(engine, '_provider', provider)
    run = engine.start(None, 'import this onto Fox', {'files': [whole]}, request_key='k')
    events = list(live_runs.stream(run))
    answer = store.get(run.chat_id)['messages'][-1]
    assert answer['content'] == STARTING + '\n\nHe is in your vault.' and 'dropped_interim' not in answer
    # streamed as it came, not held for the round's calls
    sent = [json.loads(line[len('data: '):]) for line in events if line.startswith('data: ')]
    assert [e['content'] for e in sent if e.get('type') == 'delta'][:2] == [STARTING[:9], STARTING[9:]]
    assert not any('CAME WITHOUT' in text for text in rounds[0])
