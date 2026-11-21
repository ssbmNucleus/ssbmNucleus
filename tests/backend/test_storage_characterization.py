"""
Characterization tests for the vault storage endpoints (costumes + stages).

These pin down the CURRENT observable behavior (API response shapes + the
resulting persisted state) of the read/reorder/folder endpoints so the
metadata.json -> SQLite migration can be proven behavior-preserving. They go
through real load_metadata/save_metadata IO via the `vault` fixture, so the same
assertions will run unchanged against the future DB backend.

Reference: docs/VAULT_SQLITE_MIGRATION.md (Phase 0 safety net).
"""
import threading
from pathlib import Path
import uuid
import shutil
import pytest
import vault.routes.storage_costumes as sc
import vault.catalog.costume_folders as costume_folders
import vault.routes.storage_stages as ss


@pytest.fixture
def tmp_path():
    root = Path(__file__).parent / '.tmp-vault-consistency'
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    assert path.parent.resolve() == root.resolve()
    shutil.rmtree(path)


def _skin(skin_id, color='Custom', **extra):
    s = {'id': skin_id, 'color': color, 'filename': f'{skin_id}.zip'}
    s.update(extra)
    return s


def _variant(variant_id, name=None, **extra):
    v = {'id': variant_id, 'name': name or variant_id, 'filename': f'{variant_id}.zip'}
    v.update(extra)
    return v


# ───────────────────────────── costumes: read ──────────────────────────────

def test_get_metadata_returns_full_blob(vault):
    blob = {'characters': {'Fox': {'skins': [_skin('a')]}}, 'stages': {}, 'version': '1.0'}
    vault.write(blob)
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.get('/api/mex/storage/metadata')
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['metadata'] == blob


def test_list_costumes_includes_only_on_disk_and_skips_folders(vault):
    vault.write({'characters': {'Fox': {'skins': [
        {'type': 'folder', 'id': 'folder_1', 'name': 'F', 'expanded': True},
        _skin('present', has_csp=True, has_stock=True),
        _skin('missing'),  # no zip on disk → excluded
    ]}}})
    vault.add_costume_files('Fox', 'present', csp=True, stock=True)
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.get('/api/mex/storage/costumes?character=Fox')
    body = resp.get_json()

    assert resp.status_code == 200 and body['success'] is True
    ids = [c['folder'] for c in body['costumes']]
    assert ids == ['present']          # folder entry skipped, missing-zip skipped
    c = body['costumes'][0]
    assert c['character'] == 'Fox'
    assert c['cspUrl'] == '/storage/Fox/present_csp.png'
    assert c['stockUrl'] == '/storage/Fox/present_stc.png'


def test_list_costumes_orders_folder_members_like_vault(vault):
    # Members m1/m2 are scattered among root skins, with the folder entry sitting
    # at the END -- exactly the real-world "Animelee folder" shape. The vault
    # (storage tab) groups members under the folder wherever it sits; the flat
    # "Available to Import" list must match that order so the two screens agree:
    # root skins in place, then the folder's members grouped together.
    vault.write({'characters': {'Fox': {'skins': [
        _skin('r1'),
        _skin('m1', folder_id='folder_a'),
        _skin('r2'),
        _skin('m2', folder_id='folder_a'),
        {'type': 'folder', 'id': 'folder_a', 'name': 'Animelee', 'expanded': True},
    ]}}})
    for sid in ('r1', 'm1', 'r2', 'm2'):
        vault.add_costume_files('Fox', sid)
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.get('/api/mex/storage/costumes?character=Fox')

    assert resp.status_code == 200
    ids = [c['folder'] for c in resp.get_json()['costumes']]
    assert ids == ['r1', 'r2', 'm1', 'm2']   # grouped at the folder's position


def test_list_costumes_keeps_hidden_and_orphaned_skins(vault):
    # Hidden Nana entries (visible=False) and a member whose folder was deleted
    # (orphaned folder_id) are never shown by the vault, but the endpoint must
    # still RETURN them: the Ice Climbers install path finds Nana by id, and
    # silently dropping a skin here would break that. Ordering aside, the SET of
    # returned skins must be unchanged by the vault-order reshuffle.
    vault.write({'characters': {'Ice Climbers': {'skins': [
        _skin('popo', is_popo=True),
        _skin('nana', is_nana=True, visible=False),
        _skin('orphan', folder_id='folder_gone'),
    ]}}})
    for sid in ('popo', 'nana', 'orphan'):
        vault.add_costume_files('Ice Climbers', sid)
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.get('/api/mex/storage/costumes?character=Ice Climbers')

    assert resp.status_code == 200
    ids = sorted(c['folder'] for c in resp.get_json()['costumes'])
    assert ids == ['nana', 'orphan', 'popo']   # nothing dropped


def test_order_skins_like_vault_groups_members_and_drops_headers():
    # Unit-level: folder header dropped, members pulled to the folder position,
    # every real skin returned exactly once (folder in the MIDDLE this time).
    skins = [
        {'id': 'r1'},
        {'id': 'm1', 'folder_id': 'F'},
        {'type': 'folder', 'id': 'F'},
        {'id': 'm2', 'folder_id': 'F'},
        {'id': 'r2'},
    ]
    ordered = costume_folders.order_skins_like_vault(skins)
    assert [s['id'] for s in ordered] == ['r1', 'm1', 'm2', 'r2']
    assert all(s.get('type') != 'folder' for s in ordered)


# ──────────────────────────── costumes: reorder ────────────────────────────

def test_concurrent_costume_renames_preserve_both_edits(vault):
    vault.write({'characters': {'Fox': {'skins': [_skin('a'), _skin('b')]}}})
    barrier = threading.Barrier(2)
    responses = []

    def rename(skin_id, name):
        client = vault.client(sc, 'storage_costumes_bp')
        barrier.wait(timeout=5)
        responses.append(client.post('/api/mex/storage/costumes/rename', json={
            'character': 'Fox', 'skinId': skin_id, 'newName': name,
        }))

    threads = [threading.Thread(target=rename, args=('a', 'Alpha')),
               threading.Thread(target=rename, args=('b', 'Beta'))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert [response.status_code for response in responses] == [200, 200]
    skins = {skin['id']: skin for skin in vault.read()['characters']['Fox']['skins']}
    assert skins['a']['color'] == 'Alpha'
    assert skins['b']['color'] == 'Beta'


def test_folder_create_does_not_replace_corrupt_existing_catalog(vault):
    broken = b'{"characters":'
    (vault.storage / 'metadata.json').write_bytes(broken)
    client = vault.client(sc, 'storage_costumes_bp')
    response = client.post('/api/mex/storage/folders/create', json={
        'character': 'Fox', 'name': 'Favorites',
    })
    assert response.status_code == 500
    assert b'unreadable' in response.data
    assert (vault.storage / 'metadata.json').read_bytes() == broken

def test_reorder_costumes_happy_path(vault):
    vault.write({'characters': {'Fox': {'skins': [_skin('a'), _skin('b'), _skin('c')]}}})
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.post('/api/mex/storage/costumes/reorder',
                       json={'character': 'Fox', 'fromIndex': 0, 'toIndex': 2})

    assert resp.status_code == 200
    assert [s['id'] for s in resp.get_json()['skins']] == ['b', 'c', 'a']
    assert [s['id'] for s in vault.read()['characters']['Fox']['skins']] == ['b', 'c', 'a']


def test_reorder_costumes_invalid_index_is_400(vault):
    vault.write({'characters': {'Fox': {'skins': [_skin('a')]}}})
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.post('/api/mex/storage/costumes/reorder',
                       json={'character': 'Fox', 'fromIndex': 0, 'toIndex': 9})

    assert resp.status_code == 400
    assert 'Invalid fromIndex or toIndex' in resp.get_json()['error']


def test_reorder_costume_into_folder_assigns_folder_id(vault):
    # [folder, A(in folder), B(top-level)]; move B to just after the folder.
    vault.write({'characters': {'Fox': {'skins': [
        {'type': 'folder', 'id': 'folder_x', 'name': 'F', 'expanded': True},
        _skin('a', folder_id='folder_x'),
        _skin('b'),
    ]}}})
    client = vault.client(sc, 'storage_costumes_bp')

    resp = client.post('/api/mex/storage/costumes/reorder',
                       json={'character': 'Fox', 'fromIndex': 2, 'toIndex': 1})

    assert resp.status_code == 200
    skins = {s.get('id'): s for s in vault.read()['characters']['Fox']['skins'] if s.get('type') != 'folder'}
    assert skins['b'].get('folder_id') == 'folder_x'   # adopted the folder it landed in


def test_move_costume_to_top_and_bottom(vault):
    vault.write({'characters': {'Fox': {'skins': [_skin('a'), _skin('b'), _skin('c')]}}})
    client = vault.client(sc, 'storage_costumes_bp')

    client.post('/api/mex/storage/costumes/move-to-top',
                json={'character': 'Fox', 'skinId': 'c'})
    assert [s['id'] for s in vault.read()['characters']['Fox']['skins']] == ['c', 'a', 'b']

    client.post('/api/mex/storage/costumes/move-to-bottom',
                json={'character': 'Fox', 'skinId': 'c'})
    assert [s['id'] for s in vault.read()['characters']['Fox']['skins']] == ['a', 'b', 'c']


# ──────────────────────────── costumes: folders ────────────────────────────

def test_costume_folder_lifecycle(vault):
    vault.write({'characters': {'Fox': {'skins': [_skin('a')]}}})
    client = vault.client(sc, 'storage_costumes_bp')

    # create
    r = client.post('/api/mex/storage/folders/create',
                    json={'character': 'Fox', 'name': 'Reds'})
    fid = r.get_json()['folder']['id']
    assert r.get_json()['folder']['name'] == 'Reds'

    # assign a skin to it
    client.post('/api/mex/storage/skins/set-folder',
                json={'character': 'Fox', 'skinId': 'a', 'folderId': fid})
    a = next(s for s in vault.read()['characters']['Fox']['skins'] if s.get('id') == 'a')
    assert a['folder_id'] == fid

    # toggle expanded
    r = client.post('/api/mex/storage/folders/toggle',
                    json={'character': 'Fox', 'folderId': fid})
    assert r.get_json()['expanded'] is False

    # rename
    client.post('/api/mex/storage/folders/rename',
                json={'character': 'Fox', 'folderId': fid, 'newName': 'Blues'})
    folder = next(s for s in vault.read()['characters']['Fox']['skins'] if s.get('id') == fid)
    assert folder['name'] == 'Blues'

    # delete frees member skins (folder removed, skin kept w/o folder_id)
    client.post('/api/mex/storage/folders/delete',
                json={'character': 'Fox', 'folderId': fid})
    remaining = vault.read()['characters']['Fox']['skins']
    assert all(s.get('id') != fid for s in remaining)
    a = next(s for s in remaining if s.get('id') == 'a')
    assert 'folder_id' not in a


def test_set_skin_folder_unassign(vault):
    vault.write({'characters': {'Fox': {'skins': [
        {'type': 'folder', 'id': 'folder_x', 'name': 'F', 'expanded': True},
        _skin('a', folder_id='folder_x'),
    ]}}})
    client = vault.client(sc, 'storage_costumes_bp')

    client.post('/api/mex/storage/skins/set-folder',
                json={'character': 'Fox', 'skinId': 'a', 'folderId': None})

    a = next(s for s in vault.read()['characters']['Fox']['skins'] if s.get('id') == 'a')
    assert 'folder_id' not in a


# ───────────────────────────── stages: reorder ─────────────────────────────

def test_reorder_stage_variants_happy_path(vault):
    vault.write({'stages': {'battlefield': {'variants': [
        _variant('v1'), _variant('v2'), _variant('v3')]}}})
    for v in ('v1', 'v2', 'v3'):
        vault.add_stage_variant_zip('battlefield', v)
    client = vault.client(ss, 'storage_stages_bp')

    resp = client.post('/api/mex/storage/stages/reorder',
                       json={'stageFolder': 'battlefield', 'fromIndex': 0, 'toIndex': 2})

    assert resp.status_code == 200
    assert [v['id'] for v in resp.get_json()['variants']] == ['v2', 'v3', 'v1']


def test_reorder_stage_promotes_disk_only_variant(vault):
    """The historical 'Invalid fromIndex or toIndex' bug class: the displayed
    list appends on-disk zips with no metadata entry, so reorder must index
    against that display order and persist a moved disk-only entry as real
    metadata (not 400). This is the exact behavior the SQLite migration must
    preserve via sort_order."""
    vault.write({'stages': {'battlefield': {'variants': [_variant('v1')]}}})
    vault.add_stage_variant_zip('battlefield', 'v1')
    vault.add_stage_variant_zip('battlefield', 'diskonly')  # zip only, not in metadata
    client = vault.client(ss, 'storage_stages_bp')

    # display order is [v1, diskonly]; drag diskonly (index 1) to the top.
    resp = client.post('/api/mex/storage/stages/reorder',
                       json={'stageFolder': 'battlefield', 'fromIndex': 1, 'toIndex': 0})

    assert resp.status_code == 200, resp.get_json()
    persisted = [v['id'] for v in vault.read()['stages']['battlefield']['variants']]
    assert persisted == ['diskonly', 'v1']     # promoted + ordered, no 400


def test_move_stage_variant_to_top_and_bottom(vault):
    vault.write({'stages': {'battlefield': {'variants': [
        _variant('v1'), _variant('v2'), _variant('v3')]}}})
    client = vault.client(ss, 'storage_stages_bp')

    client.post('/api/mex/storage/stages/move-to-top',
                json={'stageFolder': 'battlefield', 'variantId': 'v3'})
    assert [v['id'] for v in vault.read()['stages']['battlefield']['variants']] == ['v3', 'v1', 'v2']

    client.post('/api/mex/storage/stages/move-to-bottom',
                json={'stageFolder': 'battlefield', 'variantId': 'v3'})
    assert [v['id'] for v in vault.read()['stages']['battlefield']['variants']] == ['v1', 'v2', 'v3']


# ───────────────────────────── stages: folders ─────────────────────────────

def test_stage_folder_lifecycle(vault):
    vault.write({'stages': {'battlefield': {'variants': [_variant('v1')]}}})
    client = vault.client(ss, 'storage_stages_bp')

    r = client.post('/api/mex/storage/stage-folders/create',
                    json={'stageFolder': 'battlefield', 'name': 'Comp'})
    fid = r.get_json()['folder']['id']

    client.post('/api/mex/storage/stage-variants/set-folder',
                json={'stageFolder': 'battlefield', 'variantId': 'v1', 'folderId': fid})
    v1 = next(v for v in vault.read()['stages']['battlefield']['variants'] if v.get('id') == 'v1')
    assert v1['folder_id'] == fid

    client.post('/api/mex/storage/stage-folders/rename',
                json={'stageFolder': 'battlefield', 'folderId': fid, 'newName': 'Legal'})
    folder = next(v for v in vault.read()['stages']['battlefield']['variants'] if v.get('id') == fid)
    assert folder['name'] == 'Legal'

    client.post('/api/mex/storage/stage-folders/delete',
                json={'stageFolder': 'battlefield', 'folderId': fid})
    remaining = vault.read()['stages']['battlefield']['variants']
    assert all(v.get('id') != fid for v in remaining)
    v1 = next(v for v in remaining if v.get('id') == 'v1')
    assert 'folder_id' not in v1
