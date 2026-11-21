"""`context.fighter`: the fighter picked for a model import (the panel's
"Import a model" starting point, docs/dev/RANDALL.md "Starting-point pickers").

The blueprint whitelists it like `task`: a fighter a model import can target is
kept under the roster's own name, anything else is dropped silently (the import
then asks which fighter, as for a chat without a pick). /status serves the same
roster as `import_fighters`, so the picker offers exactly what is accepted.

No model request runs: engine.start is a stand-in that records the context.
"""
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask

from randall.assistant import engine, live_runs, store
from randall.routes import assistant_bp as routes
from shared.modellab.fighter_catalog import _CHAR_TO_CODE


@pytest.fixture
def client(vault):
    app = Flask(__name__)
    app.register_blueprint(routes.assistant_bp)
    return app.test_client()


@pytest.fixture
def started(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, 'start', lambda chat_id, message, context, **_: seen.append(context)
                        or SimpleNamespace())
    monkeypatch.setattr(live_runs, 'stream', lambda run: iter(()))
    return seen


def test_the_import_roster_is_the_catalog_without_the_ice_climbers():
    roster = routes.import_fighters()
    assert roster == sorted(roster)
    assert 'Ice Climbers' not in roster and 'Nana' not in roster
    assert set(roster) == set(_CHAR_TO_CODE) - {'Ice Climbers'}
    assert len(roster) == 25 and {'Fox', 'Mr. Game & Watch', 'Sheik', 'C. Falcon'} <= set(roster)


def test_status_serves_the_import_roster(client):
    assert client.get('/api/assistant/status').get_json()['import_fighters'] == routes.import_fighters()


@pytest.mark.parametrize('fighter,kept', [
    ('Fox', 'Fox'), ('fox', 'Fox'), ('  mr. game &  watch ', 'Mr. Game & Watch'),
    ('Captain Falcon', 'C. Falcon'), ('Donkey Kong', 'DK'), ('Young Link', 'Young Link'),
    # Not a model-import target, not a fighter, or not a name at all.
    ('Ice Climbers', None), ('Nana', None), ('Popo', None), ('Goku', None), ('', None),
    (None, None), (7, None), (['Fox'], None), ({'name': 'Fox'}, None), ('Fox' * 20, None),
])
def test_chat_keeps_a_model_import_fighter_and_drops_anything_else(client, started, fighter, kept):
    response = client.post('/api/assistant/chat', json={
        'message': 'here is my model', 'api_key': 'k',
        'context': {'page': 'vault', 'task': 'model_import', 'fighter': fighter}})
    assert response.status_code == 200, 'an unknown fighter is dropped silently, never refused'
    assert started == [{'page': 'vault', 'task': 'model_import', **({'fighter': kept} if kept else {})}]


def test_queued_input_keeps_the_fighter_under_the_same_rule(client):
    chat_id = store.save(None, [{'role': 'user', 'content': 'import this', 'context': {}}])
    for fighter, kept in (('marth', 'Marth'), ('Ice Climbers', None)):
        response = client.post(f'/api/assistant/chats/{chat_id}/inputs', json={
            'id': uuid.uuid4().hex, 'message': 'it goes on him', 'context': {'fighter': fighter}})
        assert response.status_code == 200
        assert store.pending_inputs(chat_id)[-1]['context'] == ({'fighter': kept} if kept else {})


def test_a_picked_costume_rides_the_existing_selection_unchanged(client, started):
    """The costume picker adds no field: its pick is a `selection` item, the
    shape a Vault selection already sends (vault) or the stock shape
    (character, vanilla: true, color)."""
    selection = [{'id': 'fox-blue-1', 'character': 'Fox', 'name': 'Blue Hoodie'}]
    client.post('/api/assistant/chat', json={'message': 'make it lava', 'api_key': 'k',
                                              'context': {'task': 'recolor_part', 'selection': selection}})
    stock = [{'character': 'Fox', 'vanilla': True, 'color': 'Or', 'name': 'Orange (stock)'}]
    client.post('/api/assistant/chat', json={'message': 'make it lava', 'api_key': 'k',
                                              'context': {'task': 'recolor_part', 'selection': stock}})
    assert started == [{'task': 'recolor_part', 'selection': selection},
                       {'task': 'recolor_part', 'selection': stock}]
