"""The shared color-editor save contract updates a recipe without replacing its identity."""
from copy import deepcopy

import pytest

from vault.routes.extras import colors


@pytest.mark.parametrize('character', ['Fox', 'Falco'])
def test_edit_updates_owner_recipe_and_preserves_identity(vault, character):
    original = {'id': 'shine_saved', 'name': 'Old', 'active': True,
                'source': 'nucleus', 'date_added': '2026-01-01T00:00:00',
                'model_file': 'models/original.dat', 'screenshot': 'models/preview.png',
                'file_hash': 'original-source-hash',
                'modifications': {'primary': {'color': 'FC00'}, 'flash1': {'color': '03FF'}}}
    untouched = {'id': 'shine_other', 'name': 'Other', 'modifications': {}}
    vault.write({'characters': {'Fox': {'extras': {'shine': [original, untouched]}}}})
    client = vault.client(colors, 'extras_bp')
    recipe = {'primary': {'color': 'FC1F'}, 'secondary': {'color': '03FF'}}

    response = client.post('/api/mex/storage/extras/create', json={
        'character': character, 'extraType': 'shine', 'modId': 'shine_saved',
        'name': 'Updated', 'modifications': recipe})

    assert response.status_code == 200
    expected = dict(original, name='Updated', modifications=recipe)
    assert response.get_json()['mod'] == expected
    saved = vault.read()
    assert saved['characters']['Fox']['extras']['shine'] == [expected, untouched]
    assert 'Falco' not in saved['characters']


def test_edit_missing_id_does_not_create_duplicate(vault):
    metadata = {'characters': {'Fox': {'extras': {'shine': []}}}}
    vault.write(metadata)
    client = vault.client(colors, 'extras_bp')

    response = client.post('/api/mex/storage/extras/create', json={
        'character': 'Fox', 'extraType': 'shine', 'modId': 'deleted_recipe',
        'name': 'Edited', 'modifications': {'primary': {'color': 'FC00'}}})

    assert response.status_code == 404
    assert vault.read() == metadata


def test_color_edit_cannot_overwrite_image_recipe(vault):
    image = {'id': 'shine_image', 'name': 'Image', 'format': 'effect_model',
             'image_file': 'models/image.png', 'modifications': {'image': {'width': 256}}}
    metadata = {'characters': {'Fox': {'extras': {'shine': [image]}}}}
    vault.write(deepcopy(metadata))
    client = vault.client(colors, 'extras_bp')

    response = client.post('/api/mex/storage/extras/create', json={
        'character': 'Fox', 'extraType': 'shine', 'modId': image['id'],
        'name': 'Colors', 'modifications': {'primary': {'color': 'FC00'}}})

    assert response.status_code == 400
    assert vault.read() == metadata

    # The Image -> Colors editor switch saves without modId, retaining both
    # independently editable source formats in the same Shine vault list.
    response = client.post('/api/mex/storage/extras/create', json={
        'character': 'Fox', 'extraType': 'shine', 'name': 'Colors',
        'modifications': {'primary': {'color': 'FC00'}}})
    assert response.status_code == 200
    saved = vault.read()['characters']['Fox']['extras']['shine']
    assert saved[0] == image
    assert len(saved) == 2 and saved[1]['id'] != image['id']


def test_delete_image_recipe_removes_source_and_preview_from_shared_owner(vault, monkeypatch):
    monkeypatch.setattr(colors.helpers, 'STORAGE_PATH', vault.storage)
    image = vault.touch('Fox', 'models/image.png', data=b'image')
    preview = vault.touch('Fox', 'models/preview.png', data=b'preview')
    other = vault.touch('Fox', 'models/other.png', data=b'keep')
    vault.write({'characters': {'Fox': {'extras': {'shine': [{
        'id': 'shine_image', 'format': 'effect_model',
        'image_file': 'models/image.png', 'screenshot': 'models/preview.png',
    }]}}}})
    client = vault.client(colors, 'extras_bp')

    response = client.post('/api/mex/storage/extras/delete', json={
        'character': 'Falco', 'extraType': 'shine', 'modId': 'shine_image'})

    assert response.status_code == 200
    assert not image.exists() and not preview.exists()
    assert other.read_bytes() == b'keep'
    assert vault.read()['characters']['Fox']['extras']['shine'] == []
