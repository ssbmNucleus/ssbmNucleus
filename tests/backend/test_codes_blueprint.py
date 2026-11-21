"""Tests for the codes blueprint: vault Codes catalog (vault/routes/codes.py,
vault/catalog/codes.py) + project code sync (projects/routes/codes.py)."""
from tests.paths import BACKEND
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import vault.routes.codes as codes_module
import vault.catalog.codes as codes_catalog
import projects.routes.codes as project_codes
from core.gecko import parse_ini
from core.state import clear_project_path
from projects.install.required_codes import REQUIRED_GECKO_CODES

KELLZ_HEADER, KELLZ_SOURCE = REQUIRED_GECKO_CODES[0]

LIBRARY_INI = (
    "$!QOL | Better Camera [Achilles,UnclePunch]\n"
    "*Removes camera restrictions\n"
    "04452C68 C0A00000\n"
    "$!DEBUG | Unlock Everything []\n"
    "04263384 48000010\n"
)


@pytest.fixture
def client(vault, monkeypatch, tmp_path):
    """Flask client for codes_bp with the codes catalog under the temp vault
    and the bundled library pointed at a temp ini."""
    lib = tmp_path / 'bundled_codes.ini'
    lib.write_text(LIBRARY_INI, encoding='utf-8')
    monkeypatch.setattr(codes_catalog, 'BUNDLED_CODES_INI', lib)
    monkeypatch.setattr(codes_catalog, 'STORAGE_PATH', vault.storage)
    clear_project_path()
    yield vault.client(codes_module, 'codes_bp')
    clear_project_path()


def _catalog(vault):
    return json.loads((vault.storage / 'codes' / 'metadata.json').read_text())


# ------------------------------------------------------------------- seeding

def test_vault_list_seeds_from_library(client, vault):
    resp = client.get('/api/mex/codes/vault/list')
    data = resp.get_json()
    assert data['success']
    assert {c['name'] for c in data['codes']} == {'Better Camera', 'Unlock Everything'}
    cam = next(c for c in data['codes'] if c['name'] == 'Better Camera')
    assert cam['category'] == 'QOL'
    assert cam['creator'] == 'Achilles,UnclePunch'
    assert cam['builtin'] is True
    assert set(data['categories']) == {'QOL', 'DEBUG'}


def test_deleted_builtin_never_resurrects(client, vault):
    codes = client.get('/api/mex/codes/vault/list').get_json()['codes']
    cam = next(c for c in codes if c['name'] == 'Better Camera')
    assert client.post(f"/api/mex/codes/vault/delete/{cam['id']}").get_json()['success']
    # list again — seeder must not re-insert the deleted builtin
    names = {c['name'] for c in client.get('/api/mex/codes/vault/list').get_json()['codes']}
    assert 'Better Camera' not in names


def test_library_update_adds_only_new_codes(client, vault, monkeypatch):
    client.get('/api/mex/codes/vault/list')  # initial seed
    lib = codes_catalog.BUNDLED_CODES_INI
    lib.write_text(LIBRARY_INI + "$!GAMEPLAY | New Code [x]\n04000000 00000000\n",
                   encoding='utf-8')
    codes = client.get('/api/mex/codes/vault/list').get_json()['codes']
    assert sum(1 for c in codes if c['name'] == 'Better Camera') == 1  # no dupes
    assert any(c['name'] == 'New Code' and c['category'] == 'GAMEPLAY' for c in codes)


def test_list_heals_legacy_bracket_names(client, vault):
    """Entries seeded before names were cleaned carried a literal '[]'."""
    codes_dir = vault.storage / 'codes'
    codes_dir.mkdir(parents=True, exist_ok=True)
    (codes_dir / 'metadata.json').write_text(json.dumps([{
        'id': 'aaaa1111', 'name': 'Skip Memcard Prompt []', 'creator': '',
        'category': 'ADDITIONAL', 'description': '', 'source': '04000000 00000000',
        'builtin': True, 'created': 'x',
    }]))
    codes = client.get('/api/mex/codes/vault/list').get_json()['codes']
    healed = next(c for c in codes if c['id'] == 'aaaa1111')
    assert healed['name'] == 'Skip Memcard Prompt'
    on_disk = json.loads((codes_dir / 'metadata.json').read_text())
    assert any(e['name'] == 'Skip Memcard Prompt' for e in on_disk)


def test_seed_survives_missing_library(client, vault, monkeypatch):
    monkeypatch.setattr(codes_catalog, 'BUNDLED_CODES_INI', Path('does/not/exist.ini'))
    data = client.get('/api/mex/codes/vault/list').get_json()
    assert data['success'] and data['codes'] == []


# ---------------------------------------------------------------- vault CRUD

def test_parse_and_save_round_trip(client, vault):
    parsed = client.post('/api/mex/codes/vault/parse', json={
        'text': 'My Cool Code (me)\n04263384 48000010\n'
    }).get_json()
    assert parsed['success'] and len(parsed['codes']) == 1
    assert parsed['codes'][0]['name'] == 'My Cool Code'
    assert parsed['codes'][0]['valid'] is True

    saved = client.post('/api/mex/codes/vault/save',
                        json={'codes': parsed['codes']}).get_json()
    assert saved['success'] and len(saved['added']) == 1
    assert saved['added'][0]['category'] == 'CUSTOM'
    assert saved['added'][0]['builtin'] is False

    # saving again dedupes by header
    saved2 = client.post('/api/mex/codes/vault/save',
                         json={'codes': parsed['codes']}).get_json()
    assert saved2['added'] == []
    assert saved2['skipped'][0]['reason'] == 'already in vault'


def test_save_rejects_invalid_source(client, vault):
    saved = client.post('/api/mex/codes/vault/save', json={'codes': [
        {'name': 'Bad', 'source': '06263384 00000004\n48000010 00000000'},
    ]}).get_json()
    assert saved['success'] and saved['added'] == []
    assert '0x06' in saved['skipped'][0]['reason']


def test_update_vault_code(client, vault):
    client.get('/api/mex/codes/vault/list')
    code = client.get('/api/mex/codes/vault/list').get_json()['codes'][0]
    updated = client.post(f"/api/mex/codes/vault/update/{code['id']}",
                          json={'name': 'Renamed', 'source': 'zz not hex'}).get_json()
    assert updated == {'success': False, 'error': updated['error']}
    assert 'line 1' in updated['error']
    ok = client.post(f"/api/mex/codes/vault/update/{code['id']}",
                     json={'name': 'Renamed'}).get_json()
    assert ok['success'] and ok['code']['name'] == 'Renamed'


# ------------------------------------------------------------ project routes

@pytest.fixture
def project(tmp_path, open_project):
    project_dir = tmp_path / 'proj'
    files_dir = project_dir / 'files'
    files_dir.mkdir(parents=True)
    mexproj = project_dir / 'project.mexproj'
    mexproj.write_text('', encoding='utf-8')
    open_project(mexproj)
    yield {'dir': project_dir, 'files': files_dir, 'mexproj': mexproj}
    clear_project_path()


def test_project_codes_requires_project(client):
    clear_project_path()
    assert client.get('/api/mex/codes/project').status_code == 400
    assert client.post('/api/mex/codes/project/sync', json={'codes': []}).status_code == 400


def test_project_codes_lists_and_collapses_duplicates(client, project):
    kellz_block = f"$!{KELLZ_HEADER}\n{KELLZ_SOURCE}\n"
    (project['files'] / 'codes.ini').write_text(
        kellz_block * 3 + "$Custom Thing [me]\n04263384 48000010\n",
        encoding='utf-8')
    data = client.get('/api/mex/codes/project').get_json()
    assert data['success']
    assert data['duplicatesCollapsed'] == 2
    by_name = {c['name']: c for c in data['codes']}
    assert by_name['Skip Slippi SSS']['default'] is True
    assert by_name['Custom Thing']['default'] is False
    assert by_name['Custom Thing']['enabled'] is False


def test_project_codes_empty_ini_still_shows_default(client, project):
    """Default codes land in every export of a project that doesn't list them
    (export.py adds them), so a never-exported project must list them (on)
    rather than claim 'no codes'."""
    for setup in (None, b''):  # missing ini, then 0-byte ini (exists in the wild)
        if setup is not None:
            (project['files'] / 'codes.ini').write_bytes(setup)
        data = client.get('/api/mex/codes/project').get_json()
        assert data['success']
        assert [c['name'] for c in data['codes']] == ['Skip Slippi SSS']
        row = data['codes'][0]
        assert row['default'] is True and row['enabled'] is True


def test_project_codes_default_not_duplicated_when_present(client, project):
    (project['files'] / 'codes.ini').write_text(
        f"$!{KELLZ_HEADER}\n{KELLZ_SOURCE}\n", encoding='utf-8')
    data = client.get('/api/mex/codes/project').get_json()
    names = [c['name'] for c in data['codes']]
    assert names.count('Skip Slippi SSS') == 1


def test_sync_keeps_omitted_default_code_as_disabled_and_shells_mexcli(client, project, monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls['cmd'] = cmd
        calls['ini_text'] = Path(cmd[3]).read_text(encoding='utf-8')

        class R:
            returncode = 0
            stdout = json.dumps({'success': True, 'count': 2, 'enabled': 2,
                                 'gctBytes': 64360})
            stderr = ''
        return R()

    monkeypatch.setattr(project_codes.subprocess, 'run', fake_run)
    monkeypatch.setattr(project_codes, 'MEXCLI_PATH', project['mexproj'])  # exists()

    resp = client.post('/api/mex/codes/project/sync', json={'codes': [
        {'name': 'Custom Thing', 'creator': 'me',
         'source': '04263384 48000010', 'enabled': True},
    ]}).get_json()
    assert resp['success'] and resp['applied'] == 2

    assert calls['cmd'][1] == 'sync-codes'
    assert calls['cmd'][2] == str(project['mexproj'])
    synced = parse_ini(calls['ini_text'])
    headers = {f"{c['name']} [{c['creator']}]" for c in synced}
    # An omitted default code is kept as a DISABLED entry, so export's
    # add-code (skips existing names) doesn't silently re-add it enabled.
    assert KELLZ_HEADER in headers
    kellz = next(c for c in synced if c['creator'] == 'KELLZ')
    assert kellz['enabled'] is False


def test_sync_can_disable_default_code(client, project, monkeypatch):
    def fake_run(cmd, **kwargs):
        fake_run.ini = Path(cmd[3]).read_text(encoding='utf-8')

        class R:
            returncode = 0
            stdout = json.dumps({'success': True, 'count': 1, 'enabled': 1,
                                 'gctBytes': 64352})
            stderr = ''
        return R()

    monkeypatch.setattr(project_codes.subprocess, 'run', fake_run)
    monkeypatch.setattr(project_codes, 'MEXCLI_PATH', project['mexproj'])

    name, creator = 'Skip Slippi SSS', 'KELLZ'
    resp = client.post('/api/mex/codes/project/sync', json={'codes': [
        {'name': name, 'creator': creator, 'source': KELLZ_SOURCE, 'enabled': False},
    ]}).get_json()
    assert resp['success']
    kellz = parse_ini(fake_run.ini)[0]
    assert kellz['enabled'] is False  # user's off choice persists (tracker #89)
    # and it reads back as a default code that is off
    (project['files'] / 'codes.ini').write_text(fake_run.ini, encoding='utf-8')
    rows = client.get('/api/mex/codes/project').get_json()['codes']
    assert [(r['name'], r['default'], r['enabled']) for r in rows] == [
        ('Skip Slippi SSS', True, False)]


def test_sync_rejects_invalid_without_touching_project(client, project, monkeypatch):
    def fail_run(cmd, **kwargs):  # pragma: no cover
        raise AssertionError('mexcli must not be invoked for invalid input')

    monkeypatch.setattr(project_codes.subprocess, 'run', fail_run)
    monkeypatch.setattr(project_codes, 'MEXCLI_PATH', project['mexproj'])

    resp = client.post('/api/mex/codes/project/sync', json={'codes': [
        {'name': 'Bad', 'source': '06263384 00000004\n48000010 00000000',
         'enabled': True},
    ]})
    assert resp.status_code == 400
    body = resp.get_json()
    assert '0x06' in body['codes'][0]['error']


def test_sync_surfaces_mexcli_failure(client, project, monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
            stdout = json.dumps({'success': False, 'error': 'workspace corrupt'})
            stderr = ''
        return R()

    monkeypatch.setattr(project_codes.subprocess, 'run', fake_run)
    monkeypatch.setattr(project_codes, 'MEXCLI_PATH', project['mexproj'])

    resp = client.post('/api/mex/codes/project/sync', json={'codes': []})
    assert resp.status_code == 500
    assert 'workspace corrupt' in resp.get_json()['error']


# ------------------------------------------------- Slippi-applied (runtime)

def test_dolphin_gecko_names_parses_layers(tmp_path):
    ini = tmp_path / 'GALE01r2.ini'
    ini.write_text(
        "[Gecko]\n"
        "$Optional: Show Player Names [Fizzi]\n"
        "0422D638 38000006\n"
        "$Required: General Codes\n"
        "04000000 00000000\n"
        "[Gecko_Enabled]\n"
        "$Required: General Codes\n"
        "[Gecko_Disabled]\n"
        "$Optional: Show Player Names [Fizzi]\n",
        encoding='utf-8')
    defined, enabled, disabled = project_codes._dolphin_gecko_names(ini)
    assert defined == {'Optional: Show Player Names [Fizzi]', 'Required: General Codes'}
    assert enabled == {'Required: General Codes'}
    assert disabled == {'Optional: Show Player Names [Fizzi]'}


def test_dolphin_gecko_names_missing_file(tmp_path):
    defined, enabled, disabled = project_codes._dolphin_gecko_names(tmp_path / 'nope.ini')
    assert defined == enabled == disabled == set()


def test_dolphin_endpoint_unavailable_is_graceful(client, monkeypatch, tmp_path):
    # No Slippi anywhere -> available:false, never an error. The dev machine
    # has a real Slippi install, so point the APPDATA fallback at an empty dir.
    monkeypatch.setenv('APPDATA', str(tmp_path))
    resp = client.get('/api/mex/codes/dolphin')
    data = resp.get_json()
    assert data['success']
    assert data['available'] is False
    assert data['codes'] == []


# ------------------------------------------------------------ nucleus codes

def test_nucleus_codes_offers_now_playing_with_its_ini_header(client, project):
    """An existing build adds Now Playing from the Codes modal under the same
    codes.ini header new projects start with, so it is recognised as present."""
    from projects.nowplaying import code as now_playing
    data = client.get('/api/mex/codes/nucleus').get_json()
    assert data['success']
    [np] = data['codes']
    assert f"{np['iniName']} [{np['creator']}]" == now_playing.CODE_HEADER
    assert np['source'] == now_playing.source() and np['title'] == 'Now Playing'
    assert np['conflict'] is None


def test_nucleus_codes_flags_a_build_that_already_shows_the_song(client, project):
    plugins = project['files'] / 'plugins'
    plugins.mkdir()
    (plugins / 'bgm_display.dat').write_bytes(b'\0')
    [np] = client.get('/api/mex/codes/nucleus').get_json()['codes']
    assert np['conflict']
