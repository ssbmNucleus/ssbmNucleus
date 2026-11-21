"""
projects/routes/stage_slots.py -- the replace-slot stages (every versus stage that
is not one of the six DAS stages).

Exercises the real filesystem shape: a temp project with files/GrXx.dat, a temp
vault whose skins live in storage/das/<folder>/<id>.zip with metadata under
stages.<folder>.variants (exactly like DAS variants), and a stubbed vanilla
reference so slot state can be derived by hash.
"""
import io
import json
import zipfile

import pytest

import projects.routes.stage_slots as stage_slots
from core.state import clear_project_path


VANILLA = b'VANILLA-GR-BYTES'
MODDED = b'MODDED-GR-BYTES!!'


def _make_project(tmp_path, root_files):
    project_dir = tmp_path / 'project'
    files_dir = project_dir / 'files'
    files_dir.mkdir(parents=True)
    for name, data in root_files.items():
        (files_dir / name).write_bytes(data)
    (project_dir / 'data' / 'stages').mkdir(parents=True)
    proj = {'stageSaveMap': {'filePaths': [f'stage_{i}.json' for i in range(71)]}}
    (project_dir / 'project.mexproj').write_text(json.dumps(proj), encoding='utf-8')
    return project_dir


def _add_vault_skin(vault, folder, variant_id, name, dat_name, data, screenshot=False):
    """A vault stage skin exactly as import_stage_mod writes it."""
    zip_path = vault.path('das', folder, f'{variant_id}.zip')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(dat_name, data)
    zip_path.write_bytes(buf.getvalue())
    if screenshot:
        vault.touch('das', folder, f'{variant_id}_screenshot.png', data=b'png')
    return {'id': variant_id, 'name': name, 'filename': f'{variant_id}.zip',
            'has_screenshot': screenshot}


@pytest.fixture
def slot_env(vault, tmp_path, monkeypatch):
    """Project + vault + stubbed vanilla refs; yields (client, vault)."""
    refs_dir = tmp_path / 'refs'
    refs_dir.mkdir()

    def fake_ensure_vanilla_ref(filename, storage_path=None):
        ref = refs_dir / filename
        if not ref.exists():
            ref.write_bytes(VANILLA)
        return ref

    monkeypatch.setattr(stage_slots.vanilla_refs, 'ensure_vanilla_ref', fake_ensure_vanilla_ref)
    stage_slots._MD5_CACHE.clear()

    client = vault.client(stage_slots, 'stage_slots_bp')
    yield client, vault
    clear_project_path()


def test_catalog_lists_all_29_with_modes(slot_env):
    client, _ = slot_env
    body = client.get('/api/mex/stages/catalog').get_json()
    assert body['success']
    by_code = {s['code']: s for s in body['stages']}
    assert len(by_code) == 29
    assert by_code['GrNBa']['mode'] == 'das'
    assert by_code['GrGr']['mode'] == 'replace'
    assert body['legal'] == ['GrNBa', 'GrNLa', 'GrSt', 'GrOp', 'GrPs', 'GrIz']
    assert len(body['more']) == 23


def test_slot_install_then_restore_round_trip(slot_env, tmp_path, open_project):
    client, vault = slot_env
    project_dir = _make_project(tmp_path, {'GrGr.dat': VANILLA})
    open_project(project_dir / 'project.mexproj')
    entry = _add_vault_skin(vault, 'green_greens', 'neon', 'Neon Greens', 'GrGr.dat', MODDED,
                            screenshot=True)
    vault.write({'characters': {}, 'stages': {'green_greens': {'variants': [entry]}},
                 'custom_stages': []})

    body = client.get('/api/mex/stages/GrGr/slot').get_json()
    assert body['success']
    assert body['slot']['state'] == 'vanilla'
    assert [s['id'] for s in body['available']] == ['neon']
    assert body['available'][0]['screenshotUrl'] == '/storage/das/green_greens/neon_screenshot.png'
    assert 'zipPath' not in body['available'][0]
    assert body['added'] == []

    resp = client.post('/api/mex/stages/GrGr/slot/install', json={'variantId': 'neon'})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['slot']['state'] == 'installed'
    assert resp.get_json()['slot']['installed']['id'] == 'neon'
    assert resp.get_json()['slot']['installed']['name'] == 'Neon Greens'
    assert (project_dir / 'files' / 'GrGr.dat').read_bytes() == MODDED
    assert not (project_dir / 'files' / 'GrGr.dat.tmp').exists()

    overview = client.get('/api/mex/stages/slots').get_json()['slots']
    assert overview['GrGr']['state'] == 'installed'
    assert overview['GrGr']['installed']['id'] == 'neon'
    assert overview['GrGr']['availableCount'] == 1
    assert overview['GrCs']['state'] == 'missing'

    resp = client.post('/api/mex/stages/GrGr/slot/restore-vanilla')
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['slot']['state'] == 'vanilla'
    assert (project_dir / 'files' / 'GrGr.dat').read_bytes() == VANILLA


def test_disk_only_zip_counts_as_a_skin(slot_env, tmp_path):
    """A zip with no metadata entry (same rule as the DAS storage listing)."""
    client, vault = slot_env
    _add_vault_skin(vault, 'big_blue', 'loose', 'ignored', 'GrBb.dat', MODDED)
    vault.write({'characters': {}, 'stages': {}, 'custom_stages': []})
    body = client.get('/api/mex/stages/GrBb/slot').get_json()
    assert [s['id'] for s in body['available']] == ['loose']
    assert body['available'][0]['name'] == 'loose'


def test_dual_language_stage_writes_both_roots(slot_env, tmp_path, open_project):
    client, vault = slot_env
    project_dir = _make_project(tmp_path, {'GrCn.dat': VANILLA, 'GrCn.usd': VANILLA})
    open_project(project_dir / 'project.mexproj')
    entry = _add_vault_skin(vault, 'corneria', 'cornx', 'Corneria X', 'GrCn.usd', MODDED)
    vault.write({'characters': {}, 'stages': {'corneria': {'variants': [entry]}},
                 'custom_stages': []})

    resp = client.post('/api/mex/stages/GrCn/slot/install', json={'variantId': 'cornx'})
    assert resp.status_code == 200, resp.get_json()
    assert (project_dir / 'files' / 'GrCn.dat').read_bytes() == MODDED
    assert (project_dir / 'files' / 'GrCn.usd').read_bytes() == MODDED
    files = {f['name']: f for f in resp.get_json()['slot']['files']}
    assert set(files) == {'GrCn.dat', 'GrCn.usd'}

    resp = client.post('/api/mex/stages/GrCn/slot/restore-vanilla')
    assert resp.status_code == 200
    assert (project_dir / 'files' / 'GrCn.usd').read_bytes() == VANILLA


def test_hand_edited_root_reports_modified(slot_env, tmp_path, open_project):
    client, vault = slot_env
    project_dir = _make_project(tmp_path, {'GrGr.dat': b'something the user dropped in'})
    open_project(project_dir / 'project.mexproj')
    vault.write({'characters': {}, 'stages': {}, 'custom_stages': []})
    body = client.get('/api/mex/stages/GrGr/slot').get_json()
    assert body['slot']['state'] == 'modified'
    assert body['slot']['installed'] is None


def test_added_stages_from_this_base_are_listed(slot_env, tmp_path, open_project):
    client, vault = slot_env
    project_dir = _make_project(tmp_path, {'GrGr.dat': VANILLA})
    proj_path = project_dir / 'project.mexproj'
    proj = json.loads(proj_path.read_text(encoding='utf-8'))
    proj['stageSaveMap']['filePaths'].append('stage_71.json')
    proj['stageSaveMap']['filePaths'].append('stage_72.json')
    proj_path.write_text(json.dumps(proj), encoding='utf-8')
    (project_dir / 'data' / 'stages' / 'stage_71.json').write_text(
        json.dumps({'name': 'Neon Greens', 'fileName': 'GrGr_001.dat', 'assets': {}}))
    (project_dir / 'data' / 'stages' / 'stage_72.json').write_text(
        json.dumps({'name': 'Some Other Stage', 'fileName': 'GrGreatPlateau.dat', 'assets': {}}))
    open_project(proj_path)
    vault.write({'characters': {}, 'stages': {}, 'custom_stages': []})

    body = client.get('/api/mex/stages/GrGr/slot').get_json()
    assert [a['name'] for a in body['added']] == ['Neon Greens']
    assert body['added'][0]['index'] == 71


def test_add_as_stage_wraps_the_skin_as_a_custom_stage_package(slot_env, tmp_path, monkeypatch):
    client, vault = slot_env
    entry = _add_vault_skin(vault, 'green_greens', 'neon', 'Neon Greens', 'GrGr.dat', MODDED)
    vault.write({'characters': {}, 'stages': {'green_greens': {'variants': [entry]}},
                 'custom_stages': []})

    captured = {}

    def fake_import(package_bytes, name):
        captured['name'] = name
        with zipfile.ZipFile(io.BytesIO(package_bytes)) as zf:
            captured['members'] = sorted(zf.namelist())
            captured['stage_json'] = json.loads(zf.read('stage.json'))
            captured['dat'] = zf.read('GrGr.dat')
        return {'slug': 'neon-greens', 'name': name}

    monkeypatch.setattr(stage_slots, '_import_custom_stage_package', fake_import)

    resp = client.post('/api/mex/stages/GrGr/slot/add-as-stage', json={'variantId': 'neon'})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['slug'] == 'neon-greens'
    assert captured['name'] == 'Neon Greens'
    assert captured['dat'] == MODDED
    assert 'stage.json' in captured['members']
    sidecar = captured['stage_json']['nucleusVanillaStage']
    assert sidecar['code'] == 'GrGr'
    assert sidecar['vanillaInternalID'] == 13


def test_guards(slot_env, tmp_path, open_project):
    client, vault = slot_env
    vault.write({'characters': {}, 'stages': {}, 'custom_stages': []})

    # unknown code
    assert client.get('/api/mex/stages/GrZZ/slot').status_code == 404
    # legal (DAS) stages are not replace slots
    resp = client.post('/api/mex/stages/GrNBa/slot/install', json={'variantId': 'x'})
    assert resp.status_code == 400
    assert resp.get_json()['reason'] == 'das_stage'
    # no project loaded
    clear_project_path()
    resp = client.post('/api/mex/stages/GrGr/slot/install', json={'variantId': 'x'})
    assert resp.status_code == 400
    body = client.get('/api/mex/stages/GrGr/slot').get_json()
    assert body['slot']['state'] == 'no-project'
    # unknown variant against a loaded project
    project_dir = _make_project(tmp_path, {'GrGr.dat': VANILLA})
    open_project(project_dir / 'project.mexproj')
    resp = client.post('/api/mex/stages/GrGr/slot/install', json={'variantId': 'nope'})
    assert resp.status_code == 404
    # path-ish id is rejected before touching the vault
    resp = client.post('/api/mex/stages/GrGr/slot/install', json={'variantId': '../x'})
    assert resp.status_code == 400
    # art: unknown kind / code
    assert client.get('/api/mex/stages/GrGr/art/poster').status_code == 404
    assert client.get('/api/mex/stages/GrZZ/art/icon').status_code == 404


def test_restore_without_recorded_iso_is_a_409(slot_env, tmp_path, monkeypatch, open_project):
    client, vault = slot_env
    project_dir = _make_project(tmp_path, {'GrGr.dat': MODDED})
    open_project(project_dir / 'project.mexproj')
    vault.write({'characters': {}, 'stages': {}, 'custom_stages': []})
    monkeypatch.setattr(stage_slots.vanilla_refs, 'ensure_vanilla_ref', lambda *a, **k: None)
    stage_slots._MD5_CACHE.clear()

    body = client.get('/api/mex/stages/GrGr/slot').get_json()
    assert body['slot']['state'] == 'unknown'
    resp = client.post('/api/mex/stages/GrGr/slot/restore-vanilla')
    assert resp.status_code == 409
    assert resp.get_json()['reason'] == 'no_vanilla_reference'
    assert (project_dir / 'files' / 'GrGr.dat').read_bytes() == MODDED
