"""
Characterization tests for the character-"extras" metadata endpoints
(create / list / delete). These lock in current behavior before extras IO is
routed through the core.metadata DAL, and keep guarding it afterwards.

They pin both seams to the same temp vault: the runtime-set
extras.helpers.STORAGE_PATH (current path) AND core.metadata.METADATA_FILE
(the DAL path the migration moves to), so the assertions hold before and after.
"""
import vault.routes.extras.colors as colors
import vault.extras.helpers as extras_helpers


def _client(vault, monkeypatch):
    monkeypatch.setattr(extras_helpers, 'STORAGE_PATH', vault.storage)
    return vault.client(colors, 'extras_bp')


def test_extras_list_empty(vault, monkeypatch):
    vault.write({'characters': {}})
    client = _client(vault, monkeypatch)

    r = client.get('/api/mex/storage/extras/list/Fox')

    assert r.status_code == 200
    assert r.get_json()['extras'] == {}


def test_extras_create_persists_and_lists(vault, monkeypatch):
    vault.write({'characters': {}})
    client = _client(vault, monkeypatch)

    r = client.post('/api/mex/storage/extras/create', json={
        'character': 'Fox', 'extraType': 'laser', 'name': 'Red Laser',
        'modifications': {'wide': {'color': 'FC00'}},
    })
    assert r.status_code == 200 and r.get_json()['success'] is True

    # persisted under characters.Fox.extras.laser
    laser = vault.read()['characters']['Fox']['extras']['laser']
    assert len(laser) == 1 and laser[0]['name'] == 'Red Laser'

    # and surfaced by the list endpoint
    r = client.get('/api/mex/storage/extras/list/Fox')
    assert r.get_json()['extras']['laser'][0]['name'] == 'Red Laser'


def test_extras_delete_removes_mod(vault, monkeypatch):
    vault.write({'characters': {'Fox': {'skins': [], 'extras': {'laser': [
        {'id': 'laser_1', 'name': 'X', 'modifications': {}},
    ]}}}})
    client = _client(vault, monkeypatch)

    r = client.post('/api/mex/storage/extras/delete', json={
        'character': 'Fox', 'extraType': 'laser', 'modId': 'laser_1'})

    assert r.status_code == 200 and r.get_json()['success'] is True
    assert vault.read()['characters']['Fox']['extras']['laser'] == []


def test_extras_delete_missing_mod_is_404(vault, monkeypatch):
    vault.write({'characters': {'Fox': {'skins': [], 'extras': {'laser': []}}}})
    client = _client(vault, monkeypatch)

    r = client.post('/api/mex/storage/extras/delete', json={
        'character': 'Fox', 'extraType': 'laser', 'modId': 'nope'})

    assert r.status_code == 404
