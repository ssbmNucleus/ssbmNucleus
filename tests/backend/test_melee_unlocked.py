"""Melee Unlocked export (projects/install/melee_unlocked.py): which fighters get a plugin, how
their source is staged for the kit, and what a kit or compiler problem reports. The kit here is a
stand-in whose driver writes the manifest it was given into the plugin file; the real kit and a
real compiler are exercised by the slow test at the end when both are on this machine."""
from tests.paths import BACKEND
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(BACKEND))

from projects.install import fighter_source  # noqa: E402
from projects.install import melee_unlocked as mu  # noqa: E402

FAKE_DRIVER = '''\
import argparse, os
ap = argparse.ArgumentParser()
for a in ('--kit', '--gcc-bin', '--fighter', '--out', '--work'):
    ap.add_argument(a)
a = ap.parse_args()
manifest = open(os.path.join(a.fighter, 'mexft.txt'), encoding='utf-8').read()
names = sorted(os.listdir(os.path.join(a.fighter, 'code')))
if 'broken.c' in names:
    raise SystemExit('fighter.c:3: error: this port does not compile')
edits = os.path.exists(os.path.join(a.fighter, 'native.edits'))
open(a.out, 'w', encoding='utf-8').write(manifest + '|'.join(names) + ('|edits' if edits else ''))
'''


def _kit(tmp_path):
    kit = tmp_path / 'kit'
    (kit / 'tools').mkdir(parents=True)
    (kit / 'tools' / 'mexft_build.py').write_text(FAKE_DRIVER, encoding='utf-8')
    (kit / 'flags.json').write_text('{}', encoding='utf-8')
    (kit / 'abi.txt').write_text('0123abcd\n', encoding='utf-8')
    return kit


def _compiler(tmp_path):
    folder = tmp_path / 'gcc' / 'bin'
    folder.mkdir(parents=True)
    exe = '.exe' if os.name == 'nt' else ''
    for tool in ('gcc', 'ld', 'nm', 'objcopy'):
        (folder / (tool + exe)).write_bytes(b'')
    return folder


def _project(tmp_path, names):
    root = tmp_path / 'project'
    (root / 'data' / 'fighters').mkdir(parents=True)
    paths = []
    for i, name in enumerate(names):
        rel = f'{i:03d}.json'
        (root / 'data' / 'fighters' / rel).write_text(json.dumps({'name': name}), encoding='utf-8')
        paths.append(rel)
    proj = root / 'build.mexproj'
    proj.write_text(json.dumps({'fighterSaveMap': {'filePaths': paths}}), encoding='utf-8')
    return proj


def _vault_char(vault, slug, name, dat, sources=(), edits=False, attached=True):
    """A Vault custom character. Its source counts as attached by the user unless ``attached`` is False
    (then it is like source from before the records, or from a package: untrusted)."""
    folder = vault / slug
    folder.mkdir(parents=True)
    (folder / 'fighter.json').write_text(json.dumps({'name': name, 'files': {'fighterDataPath': dat}}),
                                         encoding='utf-8')
    if sources:
        (folder / 'code').mkdir()
        for s in sources:
            (folder / 'code' / s).write_text('/* %s */\n' % s, encoding='utf-8')
        if edits:
            (folder / 'code' / 'native.edits').write_text('# why\n', encoding='utf-8')
        if attached:
            mu._record(folder, fighter_source.ATTACHED, 'a folder the test attached')
    return folder


def test_plugin_ident_is_a_c_identifier():
    assert mu.plugin_ident('Ultra Fishbunjin 3000') == 'ultra_fishbunjin_3000'
    assert mu.plugin_ident('Shulk') == 'shulk'
    assert mu.plugin_ident('2B') == 'f_2b'
    assert mu.plugin_ident('!!!') == 'fighter'


def test_collect_splits_custom_fighters_by_source(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat', ['fighter.c'])
    _vault_char(vault, 'wolf', 'Wolf', 'PlWf.dat', ['fighter.c', 'item_0.c'])
    _vault_char(vault, 'clone', 'Clone Marth', 'PlCm.dat')
    _vault_char(vault, 'unused', 'Not In Project', 'PlNo.dat', ['fighter.c'])
    proj = _project(tmp_path, ['Mario', 'Fox', 'Wolf', 'Clone Marth', 'Shulk'])
    buildable, without = mu.collect_fighters(proj, vault)
    assert [(r['name'], r['ident'], r['dat']) for r in buildable] == [
        ('Wolf', 'wolf', 'PlWf.dat'), ('Shulk', 'shulk', 'PlSk.dat')]
    assert [s.name for s in buildable[0]['sources']] == ['fighter.c', 'item_0.c']
    assert [r['name'] for r in without] == ['Clone Marth']


def test_names_that_reduce_to_one_identifier_get_their_own_files(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'a', 'Mega Man', 'PlMa.dat', ['fighter.c'])
    _vault_char(vault, 'b', 'Mega-Man', 'PlMb.dat', ['fighter.c'])
    proj = _project(tmp_path, ['Mega Man', 'Mega-Man'])
    buildable, _ = mu.collect_fighters(proj, vault)
    assert [r['ident'] for r in buildable] == ['mega_man', 'mega_man_2']


def test_export_builds_into_fighters_folder_and_reports_the_rest(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat', ['fighter.c'], edits=True)
    _vault_char(vault, 'bad', 'Bad Port', 'PlBd.dat', ['broken.c'])
    _vault_char(vault, 'clone', 'Clone Marth', 'PlCm.dat')
    proj = _project(tmp_path, ['Mario', 'Shulk', 'Bad Port', 'Clone Marth'])
    result = mu.export_plugins(proj, vault, _kit(tmp_path), _compiler(tmp_path), tmp_path / 'out',
                               tmp_path / 'work')
    assert result['abi'] == '0123abcd'
    assert [b['file'] for b in result['built']] == ['shulk.mufighter']
    assert Path(result['folder']) == tmp_path / 'out' / 'fighters'
    text = (tmp_path / 'out' / 'fighters' / 'shulk.mufighter').read_text(encoding='utf-8')
    # The manifest names the fighter as the disc does, so the plugin follows it to any slot.
    assert text == 'name Shulk\nfile PlSk.dat\nmex-name Shulk\nfighter.c|edits'
    assert [f['name'] for f in result['failed']] == ['Bad Port']
    assert 'does not compile' in result['failed'][0]['error']
    assert not (tmp_path / 'out' / 'fighters' / 'bad_port.mufighter').exists()
    assert result['withoutSource'] == [{'name': 'Clone Marth', 'slug': 'clone'}]


def test_nothing_to_build_still_checks_the_kit(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'clone', 'Clone Marth', 'PlCm.dat')
    proj = _project(tmp_path, ['Clone Marth'])
    result = mu.export_plugins(proj, vault, _kit(tmp_path), None, tmp_path / 'out', tmp_path / 'work')
    assert result['built'] == [] and result['withoutSource'][0]['name'] == 'Clone Marth'
    with pytest.raises(mu.MeleeUnlockedError, match='not a Melee Unlocked fighter kit'):
        mu.export_plugins(proj, vault, tmp_path / 'nokit', None, tmp_path / 'out', tmp_path / 'work')


def test_kit_and_compiler_problems_say_what_is_missing(tmp_path):
    with pytest.raises(mu.MeleeUnlockedError, match='No Melee Unlocked fighter kit'):
        mu.read_kit('')
    (tmp_path / 'half' / 'tools').mkdir(parents=True)
    (tmp_path / 'half' / 'tools' / 'mexft_build.py').write_text('', encoding='utf-8')
    with pytest.raises(mu.MeleeUnlockedError, match='flags.json'):
        mu.read_kit(tmp_path / 'half')
    with pytest.raises(mu.MeleeUnlockedError, match='No MinGW-w64 GCC'):
        mu.check_compiler(None)
    (tmp_path / 'empty').mkdir()
    with pytest.raises(mu.MeleeUnlockedError, match='not a GCC bin folder'):
        mu.check_compiler(tmp_path / 'empty')


def test_source_is_kept_from_a_folder_and_only_source(tmp_path):
    char = tmp_path / 'vault' / 'shulk'
    char.mkdir(parents=True)
    port = tmp_path / 'port' / 'code'
    port.mkdir(parents=True)
    (port / 'fighter.c').write_text('int x;')
    (port / 'item_0.c').write_text('int y;')
    (port / 'shared.h').write_text('#define Z 1')
    (port / 'native.edits').write_text('# why')
    (port / 'notes.txt').write_text('not source')
    (port / 'fighter.o').write_bytes(b'\x00')
    kept = mu.save_source(char, mu.source_from_folder(tmp_path / 'port'))
    assert kept == ['fighter.c', 'item_0.c', 'native.edits', 'shared.h']
    assert sorted(p.name for p in (char / 'code').iterdir()) == kept
    # A second save replaces the folder, it does not add to it.
    mu.save_source(char, {'fighter.c': b'int x;'})
    assert [p.name for p in (char / 'code').iterdir()] == ['fighter.c']
    with pytest.raises(mu.MeleeUnlockedError, match='No C source'):
        mu.save_source(char, {'shared.h': b''})


def test_source_names_cannot_leave_the_code_folder(tmp_path):
    char = tmp_path / 'vault' / 'x'
    char.mkdir(parents=True)
    kept = mu.save_source(char, {'../../evil.c': b'int e;', 'sub/dir/fighter.c': b'int f;', '.hidden.c': b''})
    assert kept == ['evil.c', 'fighter.c']
    assert sorted(p.name for p in (char / 'code').iterdir()) == ['evil.c', 'fighter.c']
    assert not (tmp_path / 'evil.c').exists()


def test_source_in_a_fighter_zip_is_found_in_its_code_folder(tmp_path):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('fighter.json', '{}')
        zf.writestr('code/fighter.c', 'int x;')
        zf.writestr('pkg/code/item_0.c', 'int y;')
        zf.writestr('code/native.edits', '# why')
        zf.writestr('other/fighter.c', 'not in code')
        zf.writestr('code/readme.md', 'no')
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        found = mu.source_from_zip_members(zf, zf.namelist())
    assert sorted(found) == ['fighter.c', 'item_0.c', 'native.edits']
    assert found['fighter.c'] == b'int x;'


# ---- the kit runs in a child of its own (11-22 review, item 2) ----

ARGS = '''\
import argparse, json, os, subprocess, sys, time
ap = argparse.ArgumentParser()
for a in ('--kit', '--gcc-bin', '--fighter', '--out', '--work'):
    ap.add_argument(a)
a = ap.parse_args()
'''
SPY_DRIVER = ARGS + '''\
json.dump({'pid': os.getpid(), 'env': sorted(os.environ), 'cwd': os.getcwd(),
           'booted': sorted(m for m in ('flask', 'core', 'core.config') if m in sys.modules)},
          open(a.out, 'w', encoding='utf-8'))
'''
HANG_DRIVER = ARGS + '''\
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
open(a.out + '.pid', 'w').write(str(child.pid))
print('still compiling', flush=True)
time.sleep(120)
'''
CRASH_DRIVER = ARGS + '''\
raise RuntimeError('the kit exploded on this port')
'''


def _kit_with(tmp_path, driver):
    kit = _kit(tmp_path)
    (kit / 'tools' / 'mexft_build.py').write_text(driver, encoding='utf-8')
    return kit


def _one_fighter(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat', ['fighter.c'])
    return _project(tmp_path, ['Shulk']), vault


def test_the_kit_runs_in_a_child_without_the_apps_secrets(tmp_path, monkeypatch):
    """Before: runpy in the backend itself, with the backend token and the window's key in reach of the kit's
    Python and of anything the fighter's C made it do. Now: a child process, scrubbed environment."""
    monkeypatch.setenv('NUCLEUS_BACKEND_TOKEN', 'backend-secret')
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', 'window-secret')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'provider-secret')
    proj, vault = _one_fighter(tmp_path)
    result = mu.export_plugins(proj, vault, _kit_with(tmp_path, SPY_DRIVER), _compiler(tmp_path),
                               tmp_path / 'out', tmp_path / 'work')
    assert [b['name'] for b in result['built']] == ['Shulk'], result
    seen = json.loads((tmp_path / 'out' / 'fighters' / 'shulk.mufighter').read_text(encoding='utf-8'))
    assert seen['pid'] != os.getpid()
    assert not [k for k in seen['env'] if k.upper().startswith('NUCLEUS_')], seen['env']
    assert 'OPENROUTER_API_KEY' not in [k.upper() for k in seen['env']]
    assert seen['booted'] == []                       # app.py handed over before importing Flask or core
    assert Path(seen['cwd']).resolve() == (tmp_path / 'work').resolve()


def test_a_kit_that_hangs_is_stopped_with_what_it_started(tmp_path, monkeypatch):
    import time
    psutil = pytest.importorskip('psutil')
    monkeypatch.setattr(mu, 'KIT_TIMEOUT', 4)
    proj, vault = _one_fighter(tmp_path)
    began = time.monotonic()
    result = mu.export_plugins(proj, vault, _kit_with(tmp_path, HANG_DRIVER), _compiler(tmp_path),
                               tmp_path / 'out', tmp_path / 'work')
    assert time.monotonic() - began < 60
    assert result['built'] == []
    error = result['failed'][0]['error']
    assert 'took longer than 4 seconds' in error and 'still compiling' in error
    grandchild = int((tmp_path / 'out' / 'fighters' / 'shulk.mufighter.pid').read_text())
    deadline = time.monotonic() + 10
    while psutil.pid_exists(grandchild) and time.monotonic() < deadline:
        try:
            if psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(0.2)
    alive = psutil.pid_exists(grandchild)
    if alive:
        try:
            alive = psutil.Process(grandchild).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            alive = False
    assert not alive, 'the compiler the kit started outlived the timeout'


def test_a_kit_that_crashes_fails_that_fighter_only(tmp_path):
    proj, vault = _one_fighter(tmp_path)
    progress = []
    result = mu.export_plugins(proj, vault, _kit_with(tmp_path, CRASH_DRIVER), _compiler(tmp_path),
                               tmp_path / 'out', tmp_path / 'work', progress=lambda f, d: progress.append((f, d)))
    assert result['built'] == []
    assert 'the kit exploded on this port' in result['failed'][0]['error']
    assert progress == [(0.0, 'Building Shulk (1 of 1)'), (1.0, 'Fighter plugins built')]


def test_progress_is_reported_per_fighter(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat', ['fighter.c'])
    _vault_char(vault, 'wolf', 'Wolf', 'PlWf.dat', ['fighter.c'])
    proj = _project(tmp_path, ['Shulk', 'Wolf'])
    progress = []
    result = mu.export_plugins(proj, vault, _kit(tmp_path), _compiler(tmp_path), tmp_path / 'out',
                               tmp_path / 'work', progress=lambda f, d: progress.append((f, d)))
    assert [b['name'] for b in result['built']] == ['Shulk', 'Wolf']
    assert progress == [(0.0, 'Building Shulk (1 of 2)'), (0.5, 'Building Wolf (2 of 2)'),
                        (1.0, 'Fighter plugins built')]


B = chr(92)
SHARE = B + '??' + B + 'UNC' + B + 'host@SSL' + B + 'DavWWWRoot' + B + 'kit'


@pytest.mark.parametrize('value', [SHARE, B * 2 + 'host' + B + 'share' + B + 'kit', '//host/share/kit',
                                   B * 2 + '?' + B + 'UNC' + B + 'host' + B + 'kit', 'relative' + B + 'kit'])
def test_the_kit_compiler_and_destination_are_folders_on_this_computer(tmp_path, value):
    with pytest.raises(mu.MeleeUnlockedError):
        mu.read_kit(value)
    with pytest.raises(mu.MeleeUnlockedError):
        mu.check_compiler(value)
    proj, vault = _one_fighter(tmp_path)
    with pytest.raises(mu.MeleeUnlockedError):
        mu.export_plugins(proj, vault, _kit(tmp_path), _compiler(tmp_path), value, tmp_path / 'work')
    assert not (tmp_path / 'work').exists()


def test_the_kit_mode_of_the_backend_does_not_boot_it(tmp_path):
    import subprocess
    done = subprocess.run([sys.executable, str(BACKEND / 'app.py'), '--mu-kit'], capture_output=True, text=True,
                          timeout=60, cwd=str(tmp_path))
    assert done.returncode == 2 and 'usage: --mu-kit' in done.stderr
    assert 'BACKEND_PORT' not in done.stdout


# ---- the routes: the window's own key, and folders on this computer ----

UI_KEY = 'window-only-key'
WINDOW = {'X-Nucleus-UI-Key': UI_KEY}


@pytest.fixture
def web(tmp_path, monkeypatch):
    from flask import Flask
    from projects.routes import melee_unlocked as routes
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    proj, vault = _one_fighter(tmp_path)
    monkeypatch.setattr(routes, 'get_current_project_path', lambda: str(proj))
    monkeypatch.setattr(routes, 'CUSTOM_CHARACTERS_PATH', str(vault))
    app = Flask(__name__)
    app.register_blueprint(routes.melee_unlocked_bp)
    return app.test_client()


def _wait(job_id):
    import time
    from core import jobs
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        record = jobs.get(job_id)
        if record and record['status'] in ('done', 'failed', 'cancelled', 'succeeded', 'error'):
            return record
        time.sleep(0.1)
    raise AssertionError(f'job {job_id} did not end')


def test_the_export_and_verify_need_the_window(web, tmp_path, monkeypatch):
    kit, gcc = _kit(tmp_path), _compiler(tmp_path)
    body = {'destination': str(tmp_path / 'out'), 'kitPath': str(kit), 'gccBin': str(gcc)}
    for url in ('/api/mex/melee-unlocked/export', '/api/mex/melee-unlocked/verify'):
        refused = web.post(url, json=body)
        assert refused.status_code == 403 and refused.get_json()['code'] == 'not_the_app_window'
        assert web.post(url, json=body, headers={'X-Nucleus-UI-Key': 'wrong'}).status_code == 403
        agent = web.post(url, json=body, headers={**WINDOW, 'X-Nucleus-Agent': 'codex'})
        assert agent.status_code == 403 and agent.get_json()['code'] == 'automation_caller'
    assert not (tmp_path / 'out').exists()
    monkeypatch.delenv('NUCLEUS_UI_APPROVAL_KEY')
    closed = web.post('/api/mex/melee-unlocked/export', json=body, headers=WINDOW)
    assert closed.status_code == 503 and closed.get_json()['code'] == 'ui_approval_channel_unavailable'


def test_the_window_verifies_and_exports(web, tmp_path):
    kit, gcc = _kit(tmp_path), _compiler(tmp_path)
    checked = web.post('/api/mex/melee-unlocked/verify', json={'kitPath': str(kit), 'gccBin': str(gcc)},
                       headers=WINDOW).get_json()
    assert checked['kit'] == {'valid': True, 'abi': '0123abcd'} and checked['compiler'] == {'valid': True}
    started = web.post('/api/mex/melee-unlocked/export', headers=WINDOW, json={
        'destination': str(tmp_path / 'out'), 'kitPath': str(kit), 'gccBin': str(gcc)})
    assert started.status_code == 200, started.get_json()
    record = _wait(started.get_json()['job_id'])
    assert [b['name'] for b in record['result']['built']] == ['Shulk'], record
    assert (tmp_path / 'out' / 'fighters' / 'shulk.mufighter').is_file()


def test_the_export_refuses_folders_on_another_computer(web, tmp_path):
    kit, gcc = _kit(tmp_path), _compiler(tmp_path)
    for body in ({'destination': SHARE, 'kitPath': str(kit), 'gccBin': str(gcc)},
                 {'destination': str(tmp_path / 'out'), 'kitPath': SHARE, 'gccBin': str(gcc)},
                 {'destination': str(tmp_path / 'out'), 'kitPath': str(kit), 'gccBin': '//host/share/bin'}):
        refused = web.post('/api/mex/melee-unlocked/export', json=body, headers=WINDOW)
        assert refused.status_code == 400, refused.get_json()
        assert 'network path' in refused.get_json()['error']
    assert not (tmp_path / 'out').exists()


# ---- imported fighter source is untrusted until the window confirms it (11-22 review, item 1) ----

PACKAGE_URL = 'https://mods.invalid/post/42/wolf.zip'


def _wolf_package(extra=None):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('fighter.json', json.dumps({'name': 'Wolf', 'seriesID': 0, 'costumes': [],
                                                'files': {'fighterDataPath': 'PlWf.dat'}}))
        zf.writestr('code/fighter.c', 'int wolf;\n')
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """A scratch Vault wired into the real importer (as test_audio_upload_hardening does)."""
    from core import metadata as core_metadata
    from vault.catalog import custom_characters as cc_catalog
    from vault.importing import custom_character_zip as cc_zip
    root = tmp_path / 'storage' / 'custom_characters'
    root.mkdir(parents=True)
    metadata_file = tmp_path / 'storage' / 'metadata.json'
    metadata_file.write_text(json.dumps({'custom_characters': []}), encoding='utf-8')
    for module in (cc_zip, cc_catalog):
        monkeypatch.setattr(module, 'CUSTOM_CHARACTERS_PATH', root)
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', metadata_file)
    return root


def _import(tmp_path, data, origin):
    from vault.importing.unified.protocol import import_handoff
    package = tmp_path / 'wolf.zip'
    package.write_bytes(data)
    payload, status = import_handoff(str(package), 'wolf.zip', origin=origin)
    assert status == 200 and payload.get('type') == 'custom_character', payload
    return payload['character']['slug']


def test_source_in_a_downloaded_package_is_kept_as_untrusted_with_its_origin(storage, tmp_path):
    """Before: a package's code/ was saved like attached source, and the next export compiled it into a native
    plugin. Now it is recorded as untrusted, with where the package came from, and not built."""
    slug = _import(tmp_path, _wolf_package(), f'a download from {PACKAGE_URL}')
    assert (storage / slug / 'code' / 'fighter.c').is_file()
    record = json.loads(fighter_source.store_path(storage).read_text(encoding='utf-8'))['fighters'][slug]
    assert record['state'] == 'untrusted' and PACKAGE_URL in record['origin'] and record['recordedAt']
    proj = _project(tmp_path, ['Wolf'])
    result = mu.export_plugins(proj, storage, _kit_with(tmp_path, SPY_DRIVER), _compiler(tmp_path),
                               tmp_path / 'out', tmp_path / 'work')
    assert result['built'] == [] and result['failed'] == []
    [row] = result['unconfirmed']
    assert row['name'] == 'Wolf' and PACKAGE_URL in row['origin'] and PACKAGE_URL in row['reason']
    assert 'Wolf' in row['confirmText'] and PACKAGE_URL in row['confirmText']
    assert not (tmp_path / 'out' / 'fighters' / 'wolf.mufighter').exists()


def test_every_import_entry_point_says_where_the_package_came_from():
    from vault.importing.unified.protocol import describe_import
    assert describe_import(protocol_url='nucleus://import?url=' + PACKAGE_URL) == \
        'a nucleus://import link to ' + PACKAGE_URL
    assert describe_import(filename='wolf.zip') == 'the file wolf.zip'
    assert describe_import(origin='the mod website (x), downloaded by the assistant', filename='w.zip') == \
        'the mod website (x), downloaded by the assistant'
    from vault.routes.import_unified.routes import _upload_origin

    class Upload:
        filename = 'C:/Users/me/Downloads/wolf.zip'
    assert _upload_origin(PACKAGE_URL, [Upload()]) == 'a download from ' + PACKAGE_URL
    assert _upload_origin(None, [Upload()]) == 'the file wolf.zip, imported from this computer'
    assert _upload_origin('javascript:alert(1)', [Upload()]).startswith('the file wolf.zip')
    with fighter_source.import_origin('line one\nname Evil\x00'):
        assert fighter_source.current_origin() == 'line one name Evil'
    assert fighter_source.current_origin() == fighter_source.UNKNOWN_ORIGIN


def test_a_package_cannot_vouch_for_its_own_source(storage, tmp_path):
    forged = json.dumps({'version': 1, 'fighters': {'wolf': {'state': 'attached', 'sha256': 'x', 'origin': 'me'}}})
    slug = _import(tmp_path, _wolf_package({'fighter_source_trust.json': forged,
                                            'code/fighter_source_trust.json': forged}), 'a test package')
    assert not (storage / slug / 'code' / 'fighter_source_trust.json').exists()
    buildable, _ = mu.collect_fighters(_project(tmp_path, ['Wolf']), storage)
    assert buildable[0]['trust']['trusted'] is False


def test_source_from_before_the_records_is_untrusted(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat', ['fighter.c'], attached=False)
    result = mu.export_plugins(_project(tmp_path, ['Shulk']), vault, _kit(tmp_path), _compiler(tmp_path),
                               tmp_path / 'out', tmp_path / 'work')
    assert result['built'] == []
    assert result['unconfirmed'][0]['origin'] == fighter_source.BEFORE_RECORDS


def test_attached_source_builds(tmp_path):
    vault = tmp_path / 'vault'
    char = _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat')
    port = tmp_path / 'port'
    port.mkdir()
    (port / 'fighter.c').write_text('int shulk;')
    (port / 'shared.h').write_text('#define S 1')
    assert mu.attach_source(char, port) == ['fighter.c', 'shared.h']
    result = mu.export_plugins(_project(tmp_path, ['Shulk']), vault, _kit(tmp_path), _compiler(tmp_path),
                               tmp_path / 'out', tmp_path / 'work')
    assert [b['name'] for b in result['built']] == ['Shulk'] and result['unconfirmed'] == []
    # The headers are staged with the C now (the kit compiles code/ as a unit).
    assert (tmp_path / 'out' / 'fighters' / 'shulk.mufighter').read_text().endswith('fighter.c|shared.h')


def test_a_confirmation_covers_the_source_that_was_shown_and_nothing_else(storage, tmp_path):
    slug = _import(tmp_path, _wolf_package(), f'a download from {PACKAGE_URL}')
    char = storage / slug
    proj = _project(tmp_path, ['Wolf'])
    [row] = mu.collect_fighters(proj, storage)[0]
    shown = row['trust']['sha256']
    with pytest.raises(mu.MeleeUnlockedError, match='changed after it was shown'):
        mu.confirm_source(char, 'f' * 64)
    assert mu.collect_fighters(proj, storage)[0][0]['trust']['trusted'] is False
    record = mu.confirm_source(char, shown)
    assert record['state'] == 'confirmed' and PACKAGE_URL in record['origin']
    kit, gcc = _kit(tmp_path), _compiler(tmp_path)
    result = mu.export_plugins(proj, storage, kit, gcc, tmp_path / 'out', tmp_path / 'work')
    assert [b['name'] for b in result['built']] == ['Wolf']
    # The bytes change after the confirmation: untrusted again, and not built.
    (char / 'code' / 'fighter.c').write_text('int wolf; /* and something else */\n')
    result = mu.export_plugins(proj, storage, kit, gcc, tmp_path / 'out2', tmp_path / 'work2')
    assert result['built'] == [] and result['unconfirmed'][0]['origin'] == fighter_source.CHANGED_SINCE


def test_source_that_changes_between_the_list_and_the_build_is_not_compiled(tmp_path):
    vault = tmp_path / 'vault'
    char = _vault_char(vault, 'shulk', 'Shulk', 'PlSk.dat', ['fighter.c'])
    rows, _ = mu.collect_fighters(_project(tmp_path, ['Shulk']), vault)
    assert rows[0]['trust']['trusted']
    (char / 'code' / 'fighter.c').write_text('/* swapped after the check */')
    result = mu.build_plugins(rows, _kit_with(tmp_path, CRASH_DRIVER), _compiler(tmp_path), tmp_path / 'out',
                              tmp_path / 'work')
    assert result['built'] == [] and result['failed'] == []      # the driver never ran
    assert result['unconfirmed'][0]['name'] == 'Shulk'


@pytest.mark.parametrize('name', ['Wolf\nfile PlEvil.dat', 'Wolf\r', 'Wolf\x00', 'Wolf' + chr(0x2028) + 'x',
                                  'Wolf' + chr(0x85), '  '])
def test_a_name_that_could_add_a_manifest_line_is_refused(name):
    with pytest.raises(mu.MeleeUnlockedError):
        mu.manifest_lines({'name': name, 'dat': 'PlWf.dat', 'ident': 'wolf'})


@pytest.mark.parametrize('dat', ['evil.dll', 'PlWf.dat\nfile x', '../PlWf.dat', 'PlWf.dat.exe', 'Pl.dat',
                                 'Pl' + chr(0xe9) + 'f.dat', 'C:/PlWf.dat', 'plwf.dat'])
def test_a_data_file_that_is_not_the_games_is_refused(dat):
    with pytest.raises(mu.MeleeUnlockedError):
        mu.manifest_lines({'name': 'Wolf', 'dat': dat, 'ident': 'wolf'})


@pytest.mark.parametrize('dat', ['PlWf.dat', 'PlMs_001.dat', 'PlSk.usd', ''])
def test_the_games_own_data_file_names_pass(dat):
    lines = mu.manifest_lines({'name': 'Mega Man (Ver. 2)', 'dat': dat, 'ident': 'mega_man'})
    assert lines == ['name Mega Man (Ver. 2)', f'file {dat or "Plmega_man.dat"}', 'mex-name Mega Man (Ver. 2)']


def test_a_bad_manifest_fails_that_fighter_before_the_kit_runs(tmp_path):
    vault = tmp_path / 'vault'
    _vault_char(vault, 'evil', 'Evil', 'evil.dll', ['fighter.c'])
    result = mu.export_plugins(_project(tmp_path, ['Evil']), vault, _kit_with(tmp_path, CRASH_DRIVER),
                               _compiler(tmp_path), tmp_path / 'out', tmp_path / 'work')
    assert result['built'] == [] and 'PlXx.dat' in result['failed'][0]['error']


@pytest.fixture
def web_storage(storage, tmp_path, monkeypatch):
    from flask import Flask
    from projects.routes import melee_unlocked as routes
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    project = _project(tmp_path, ['Wolf', 'Clone'])
    monkeypatch.setattr(routes, 'get_current_project_path', lambda: str(project))
    monkeypatch.setattr(routes, 'CUSTOM_CHARACTERS_PATH', str(storage))
    app = Flask(__name__)
    app.register_blueprint(routes.melee_unlocked_bp)
    return app.test_client(), storage


def test_the_window_lists_confirms_and_attaches(web_storage, tmp_path):
    web, storage = web_storage
    slug = _import(tmp_path, _wolf_package(), f'a download from {PACKAGE_URL}')
    _vault_char(storage, 'clone', 'Clone', 'PlCl.dat')
    listed = web.get('/api/mex/melee-unlocked/fighters').get_json()
    assert listed['buildable'] == [] and [f['name'] for f in listed['withoutSource']] == ['Clone']
    [wolf] = listed['unconfirmed']
    assert wolf['slug'] == slug and PACKAGE_URL in wolf['origin'] and len(wolf['sha256']) == 64
    assert 'Wolf' in wolf['confirmText'] and PACKAGE_URL in wolf['confirmText']
    confirm = f'/api/mex/melee-unlocked/source/{slug}/confirm'
    # Only the window may vouch for it.
    assert web.post(confirm, json={'sha256': wolf['sha256']}).status_code == 403
    agent = web.post(confirm, json={'sha256': wolf['sha256']}, headers={**WINDOW, 'X-Nucleus-Agent-Session': 's'})
    assert agent.status_code == 403 and agent.get_json()['code'] == 'automation_caller'
    stale = web.post(confirm, json={'sha256': '0' * 64}, headers=WINDOW)
    assert stale.status_code == 409 and stale.get_json()['code'] == 'source_changed'
    assert web.get('/api/mex/melee-unlocked/fighters').get_json()['buildable'] == []
    done = web.post(confirm, json={'sha256': wolf['sha256']}, headers=WINDOW)
    assert done.status_code == 200 and done.get_json()['source']['state'] == 'confirmed'
    listed = web.get('/api/mex/melee-unlocked/fighters').get_json()
    assert [f['name'] for f in listed['buildable']] == ['Wolf'] and listed['unconfirmed'] == []
    # Attaching is the window's too, and what it attaches is built without a question.
    port = tmp_path / 'clone-port'
    port.mkdir()
    (port / 'fighter.c').write_text('int clone;')
    attach = '/api/mex/melee-unlocked/source/clone'
    assert web.post(attach, json={'folder': str(port)}).status_code == 403
    assert not (storage / 'clone' / 'code').exists()
    assert web.post(attach, json={'folder': SHARE}, headers=WINDOW).status_code == 400
    attached = web.post(attach, json={'folder': str(port)}, headers=WINDOW)
    assert attached.status_code == 200 and attached.get_json()['files'] == ['fighter.c']
    listed = web.get('/api/mex/melee-unlocked/fighters').get_json()
    assert sorted(f['name'] for f in listed['buildable']) == ['Clone', 'Wolf']
    assert web.delete(attach).status_code == 403
    assert web.delete(attach, headers=WINDOW).status_code == 200
    assert not (storage / 'clone' / 'code').exists()
    assert 'clone' not in json.loads(fighter_source.store_path(storage).read_text())['fighters']
