"""
Backend-equivalence tests: the same storage operations run against BOTH the
JSON and SQLite backends (via the `dual_backend` fixture) and must produce
identical results. This is the transparency proof for the migration — the DB
backend is a drop-in for metadata.json behind the flag.
"""
import vault.routes.storage_costumes as sc
import vault.routes.storage_stages as ss
import vault.catalog.bundles as b
import vault.routes.custom_characters as cc
import vault.importing.custom_character_zip as cc_zip


def test_reorder_costumes_equivalent(dual_backend):
    v = dual_backend
    v.write({'characters': {'Fox': {'skins': [
        {'id': 'a', 'color': 'R', 'filename': 'a.zip'},
        {'id': 'b', 'color': 'B', 'filename': 'b.zip'},
        {'id': 'c', 'color': 'G', 'filename': 'c.zip'},
    ]}}})
    client = v.client(sc, 'storage_costumes_bp')

    r = client.post('/api/mex/storage/costumes/reorder',
                    json={'character': 'Fox', 'fromIndex': 0, 'toIndex': 2})

    assert r.status_code == 200
    assert [s['id'] for s in v.read()['characters']['Fox']['skins']] == ['b', 'c', 'a']


def test_costume_folder_assignment_equivalent(dual_backend):
    v = dual_backend
    v.write({'characters': {'Fox': {'skins': [{'id': 'a', 'filename': 'a.zip'}]}}})
    client = v.client(sc, 'storage_costumes_bp')

    fid = client.post('/api/mex/storage/folders/create',
                      json={'character': 'Fox', 'name': 'Reds'}).get_json()['folder']['id']
    client.post('/api/mex/storage/skins/set-folder',
                json={'character': 'Fox', 'skinId': 'a', 'folderId': fid})

    a = next(s for s in v.read()['characters']['Fox']['skins'] if s.get('id') == 'a')
    assert a['folder_id'] == fid


def test_stage_reorder_equivalent(dual_backend):
    v = dual_backend
    v.write({'stages': {'battlefield': {'variants': [
        {'id': 'v1', 'filename': 'v1.zip'}, {'id': 'v2', 'filename': 'v2.zip'}]}}})
    for x in ('v1', 'v2'):
        v.add_stage_variant_zip('battlefield', x)
    client = v.client(ss, 'storage_stages_bp')

    r = client.post('/api/mex/storage/stages/reorder',
                    json={'stageFolder': 'battlefield', 'fromIndex': 0, 'toIndex': 1})

    assert r.status_code == 200
    assert [x['id'] for x in v.read()['stages']['battlefield']['variants']] == ['v2', 'v1']


def test_bundle_append_preserves_siblings_equivalent(dual_backend):
    v = dual_backend
    v.write({'bundles': [], 'custom_characters': [{'slug': 'keep'}]})

    b._append_bundle({'id': 'x'})

    data = v.read()
    assert [x['id'] for x in data['bundles']] == ['x']
    assert data['custom_characters'] == [{'slug': 'keep'}]      # sibling key intact


def test_custom_character_append_equivalent(dual_backend):
    v = dual_backend
    v.write({'characters': {}, 'stages': {}, 'custom_stages': [], 'custom_characters': []})

    cc_zip._append_custom_character({'slug': 'wolf', 'name': 'Wolf', 'source': 'zip'})

    assert [c['slug'] for c in v.read()['custom_characters']] == ['wolf']


def test_get_metadata_endpoint_equivalent(dual_backend):
    v = dual_backend
    # Complete skin entry: a partial one (no color) would be healed by
    # sanitize_skin_metadata on serve and no longer round-trip verbatim.
    blob = {'characters': {'Fox': {'skins': [
        {'id': 'a', 'color': 'a', 'filename': 'a.zip', 'has_csp': False,
         'has_stock': False, 'date_added': '2026-01-01T00:00:00'}]}},
        'stages': {}, 'version': '1.0'}
    v.write(blob)
    client = v.client(sc, 'storage_costumes_bp')

    body = client.get('/api/mex/storage/metadata').get_json()

    assert body['success'] is True
    assert body['metadata'] == blob
