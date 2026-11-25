"""Patch, bundle and HD texture-pack work runs as jobs (core/jobs.py): each
attempt has its own id, writes only into files named by it, and owns its temp
folder and half-written output until it ends, so a failure leaves neither
behind and one attempt's outcome is never read as another's."""
import configparser
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest
from flask import Flask

import core.state as core_state
from core import jobs
from projects.routes import bundles as project_bundles
from projects.routes import xdelta as xdelta_routes
from shared.routes.jobs import jobs_bp


class _RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None):
        self.events.append((event, data))


class _SyncThread:
    """Runs the job inline on start(), so it has ended before the route returns:
    the order in which an event-only UI lost a fast failure (F-G-2)."""
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _Xdelta:
    """Stands in for xdelta3: writes `output` to the command's last argument and
    exits with `code`."""
    def __init__(self, monkeypatch):
        self.runs = []
        self.code = 0
        self.output = b'patched disc'
        monkeypatch.setattr(project_bundles.subprocess, 'Popen', self._popen)

    def _popen(self, command, **kwargs):
        self.runs.append(list(command))
        Path(command[-1]).write_bytes(self.output)
        runner = self

        class Process:
            returncode = runner.code

            def poll(self):
                return self.returncode

            def communicate(self):
                return b'', (b'bad patch data' if self.returncode else b'')

        return Process()


@pytest.fixture
def env(tmp_path, monkeypatch):
    temp = tmp_path / 'tmp'
    temp.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(temp))
    sock = _RecordingSocket()
    monkeypatch.setattr(core_state, 'get_socketio', lambda: sock)
    monkeypatch.setattr(jobs.threading, 'Thread', _SyncThread)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})

    output = tmp_path / 'output'
    output.mkdir()
    bundles = tmp_path / 'bundles'
    bundles.mkdir()
    patches = tmp_path / 'patches'
    patches.mkdir()
    user = tmp_path / 'dolphin' / 'User'
    isos = tmp_path / 'isos'
    isos.mkdir()
    vanilla = tmp_path / 'vanilla.iso'
    vanilla.write_bytes(b'vanilla disc')
    for module in (project_bundles, xdelta_routes):
        monkeypatch.setattr(module, 'OUTPUT_PATH', output)
    monkeypatch.setattr(project_bundles, 'BUNDLE_PATH', bundles)
    monkeypatch.setattr(project_bundles, 'slippi_user_dir', lambda path: user)
    monkeypatch.setattr(project_bundles, 'parse_dolphin_ini_iso_path', lambda ini: str(isos))
    monkeypatch.setattr(project_bundles, 'require_xdelta_exe', lambda: 'xdelta3')
    monkeypatch.setattr(xdelta_routes, 'require_xdelta_exe', lambda: 'xdelta3')
    monkeypatch.setattr(xdelta_routes, 'XDELTA_PATH', patches)
    appended = []
    monkeypatch.setattr(project_bundles, '_append_bundle', appended.append)
    index = [{'id': 'p1', 'name': 'My Patch'}]
    monkeypatch.setattr(xdelta_routes, 'load_xdelta_metadata', lambda: list(index))
    monkeypatch.setattr(xdelta_routes, 'save_xdelta_metadata', lambda rows: index.__init__(rows))
    (patches / 'p1.xdelta').write_bytes(b'patch')

    app = Flask(__name__)
    app.register_blueprint(project_bundles.bundles_bp)
    app.register_blueprint(xdelta_routes.xdelta_bp)
    app.register_blueprint(jobs_bp)

    class Env:
        pass
    e = Env()
    e.client = app.test_client()
    e.events = sock.events
    e.temp, e.output, e.bundles, e.patches = temp, output, bundles, patches
    e.user, e.isos, e.vanilla = user, isos, vanilla
    e.appended, e.index = appended, index
    e.xdelta = _Xdelta(monkeypatch)
    return e


def _job(env, job_id):
    response = env.client.get(f'/api/jobs/{job_id}')
    assert response.status_code == 200
    return response.get_json()['job']


def _store_bundle(env, bundle_id='b1', name='My Mod', textures=('tex1.png',)):
    with zipfile.ZipFile(env.bundles / f'{bundle_id}.ssbm', 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'name': name, 'build_name': 'build_b1'}))
        archive.writestr('patch.xdelta', b'patch')
        for texture in textures:
            archive.writestr(f'textures/{texture}', b'png')


def _install(env, bundle_id='b1'):
    response = env.client.post(f'/api/mex/bundle/install/{bundle_id}', json={
        'slippiPath': 'slippi', 'vanillaIsoPath': str(env.vanilla)})
    assert response.status_code == 200
    return response.get_json()['job_id']


# ---- bundle install -------------------------------------------------------

def test_bundle_install_replaces_the_iso_only_when_everything_worked(env):
    _store_bundle(env)
    (env.isos / 'My_Mod.iso').write_bytes(b'last week')

    record = _job(env, _install(env))
    assert record['kind'] == 'bundle_install'
    assert record['status'] == 'done', record
    assert record['result']['iso_path'] == str(env.isos / 'My_Mod.iso')
    assert record['result']['texture_count'] == 1
    assert (env.isos / 'My_Mod.iso').read_bytes() == b'patched disc'
    # the decoder never wrote the destination itself, nor with -f
    decode = env.xdelta.runs[0]
    assert '-f' not in decode
    assert decode[-1] != str(env.isos / 'My_Mod.iso')
    assert 'hirestextures = true' in (env.user / 'Config' / 'GFX.ini').read_text().lower()
    assert list(env.isos.glob('*.part.iso')) == []
    assert list(env.temp.iterdir()) == []
    assert record['owned'] == {}


def test_failed_bundle_decode_leaves_the_old_iso_untouched(env):
    # F-G-5: the old install of the same bundle stays playable; F-G-6: the
    # extraction folder and the half-written ISO go with the failed job.
    _store_bundle(env)
    (env.isos / 'My_Mod.iso').write_bytes(b'last week')
    env.xdelta.code = 1
    env.xdelta.output = b'half a disc'

    record = _job(env, _install(env))
    assert record['status'] == 'failed'
    assert 'bad patch data' in record['error']
    assert (env.isos / 'My_Mod.iso').read_bytes() == b'last week'
    assert list(env.isos.glob('*.part.iso')) == []
    assert list(env.temp.iterdir()) == []
    assert record['owned'] == {}


def test_bundle_install_fails_when_hd_textures_cannot_be_turned_on(env):
    # F-G-7: GFX.ini that cannot be written is a failed install, not "ready".
    _store_bundle(env)
    (env.isos / 'My_Mod.iso').write_bytes(b'last week')
    (env.user / 'Config' / 'GFX.ini').mkdir(parents=True)   # a folder: not writable as a file

    record = _job(env, _install(env))
    assert record['status'] == 'failed'
    assert 'HD textures' in record['error']
    assert (env.isos / 'My_Mod.iso').read_bytes() == b'last week'
    assert list(env.isos.glob('*.part.iso')) == []
    assert list(env.temp.iterdir()) == []


def test_invalid_bundle_install_removes_its_extraction(env):
    with zipfile.ZipFile(env.bundles / 'bad.ssbm', 'w') as archive:
        archive.writestr('manifest.json', '{not json')
        archive.writestr('patch.xdelta', b'patch')

    record = _job(env, _install(env, 'bad'))
    assert record['status'] == 'failed'
    assert list(env.temp.iterdir()) == []


# ---- bundle export --------------------------------------------------------

def _export(env, **extra):
    exported = env.output / 'artifacts' / 'build_1.iso'
    exported.parent.mkdir(exist_ok=True)
    exported.write_bytes(b'exported disc')
    textures = env.output / 'textures'
    textures.mkdir(exist_ok=True)
    (textures / 'tex1.png').write_bytes(b'png')
    data = {'name': 'Pack', 'buildName': 'build_1', 'vanillaIsoPath': str(env.vanilla),
            'exportedIsoPath': str(exported), 'texturePackPath': str(textures),
            'image': (io.BytesIO(b'png'), 'cover.png'), **extra}
    response = env.client.post('/api/mex/bundle/export', data=data,
                               content_type='multipart/form-data')
    assert response.status_code == 200
    body = response.get_json()
    return body['job_id'], body['bundle_id']


def test_bundle_export_writes_its_bundle_and_owns_nothing_after(env):
    job_id, bundle_id = _export(env)
    record = _job(env, job_id)
    assert record['status'] == 'done', record
    assert record['result']['bundle_id'] == bundle_id
    assert record['result']['texture_count'] == 1
    with zipfile.ZipFile(env.bundles / f'{bundle_id}.ssbm') as archive:
        assert {'manifest.json', 'patch.xdelta', 'textures/tex1.png', 'image.png'} <= set(archive.namelist())
    assert (env.bundles / f'{bundle_id}.png').exists()
    assert [row['id'] for row in env.appended] == [bundle_id]
    assert list(env.bundles.glob('*.part')) == []
    assert list(env.output.glob('temp_bundle_image_*')) == []
    assert list(env.temp.iterdir()) == []


def test_failed_bundle_export_leaves_no_temp_folder_or_upload(env, monkeypatch):
    # F-G-6: a missing xdelta3 used to strand the bundle's temp folder.
    def missing():
        raise FileNotFoundError('xdelta3 executable was not found')
    monkeypatch.setattr(project_bundles, 'require_xdelta_exe', missing)

    job_id, bundle_id = _export(env)
    record = _job(env, job_id)
    assert record['status'] == 'failed'
    assert 'xdelta3' in record['error']
    assert list(env.temp.iterdir()) == []
    assert list(env.output.glob('temp_bundle_image_*')) == []
    assert not (env.bundles / f'{bundle_id}.ssbm').exists()
    assert env.appended == []


def test_bundle_export_nucleus_died_in_is_cleaned_at_the_next_start(env, monkeypatch):
    class _Never:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass
    monkeypatch.setattr(jobs.threading, 'Thread', _Never)
    job_id, _bundle_id = _export(env)
    image = Path(jobs.get(job_id)['owned']['image'])
    assert image.exists()

    jobs._jobs.clear()
    record = jobs.get(job_id)
    record['owner'] = {'pid': 999999999, 'created': 1.0}
    jobs._write(record)
    assert [r['id'] for r in jobs.recover_interrupted()] == [job_id]
    assert not image.exists()
    assert jobs.get(job_id)['status'] == 'interrupted'


# ---- patch build and create ----------------------------------------------

def _build(env):
    response = env.client.post('/api/mex/xdelta/build/p1',
                               json={'vanillaIsoPath': str(env.vanilla)})
    assert response.status_code == 200
    return response.get_json()['job_id']


def test_each_patch_build_attempt_has_its_own_outcome_and_output(env):
    # F-G-4: two attempts on the same patch never share a result; F-G-2: an
    # attempt that ended before the window had its id is still answered.
    env.xdelta.code = 1
    first = _build(env)
    env.xdelta.code = 0
    second = _build(env)
    assert first != second

    failed, done = _job(env, first), _job(env, second)
    assert failed['status'] == 'failed'
    assert 'bad patch data' in failed['error']
    assert done['status'] == 'done'
    assert done['result']['patch_id'] == 'p1'
    assert Path(done['result']['path']) == env.output / 'artifacts' / f'{second}.iso'
    assert done['result']['filename'].startswith('My_Patch_')
    assert list((env.output / 'artifacts').glob('*.part.iso')) == []
    assert not (env.output / 'artifacts' / f'{first}.iso').exists()
    assert {data['id'] for name, data in env.events} == {first, second}
    assert {name for name, _data in env.events} == {'job'}


def test_patch_create_moves_its_own_partial_into_the_vault(env):
    modded = env.output / 'modded.iso'
    modded.write_bytes(b'modded')
    response = env.client.post('/api/mex/xdelta/create', json={
        'vanillaIsoPath': str(env.vanilla), 'moddedIsoPath': str(modded), 'name': 'New'})
    record = _job(env, response.get_json()['job_id'])
    assert record['status'] == 'done', record
    patch_id = record['result']['patch_id']
    assert (env.patches / f'{patch_id}.xdelta').read_bytes() == b'patched disc'
    assert any(row['id'] == patch_id for row in env.index)
    assert list(env.output.glob('*.part.xdelta')) == []

    env.xdelta.code = 1
    response = env.client.post('/api/mex/xdelta/create', json={
        'vanillaIsoPath': str(env.vanilla), 'moddedIsoPath': str(modded), 'name': 'Broken'})
    record = _job(env, response.get_json()['job_id'])
    assert record['status'] == 'failed'
    assert list(env.output.glob('*.part.xdelta')) == []
    assert not any(row['name'] == 'Broken' for row in env.index)


def test_patch_and_bundle_helpers_die_with_the_backend(env, monkeypatch):
    # A backend crash must not leave xdelta3 writing a file the next start has
    # already recovered: each helper is tied to the backend (core.child_procs).
    tied = []
    for module in (project_bundles, xdelta_routes):
        monkeypatch.setattr(module, 'own', lambda proc: tied.append(proc) or proc)
    modded = env.output / 'modded.iso'
    modded.write_bytes(b'modded')
    env.client.post('/api/mex/xdelta/create', json={
        'vanillaIsoPath': str(env.vanilla), 'moddedIsoPath': str(modded), 'name': 'New'})
    _build(env)
    _store_bundle(env)
    _install(env)
    assert len(env.xdelta.runs) == 3
    assert len(tied) == 3


# ---- HD texture pack (the bundle pipeline's middle step) -------------------

def _texture_env(env, monkeypatch, costumes):
    from shared.routes import slippi
    from projects.install import texture_filename_table, texture_pack
    monkeypatch.setattr(slippi, 'OUTPUT_PATH', env.output)
    monkeypatch.setattr(slippi, 'slippi_user_dir', lambda path: env.user)
    gfx = []
    monkeypatch.setattr(slippi, 'set_dolphin_texture_settings',
                        lambda path, **kwargs: gfx.append(kwargs) or env.gfx_ok)
    monkeypatch.setattr(texture_filename_table, 'ensure_table_covers',
                        lambda indices, progress: ({i: f'tex{i}.png' for i in indices}, []))
    monkeypatch.setattr(texture_pack, 'apply_offline_texture_pack',
                        lambda mapping, entries, load_path, storage: {
                            'matched': len(entries), 'total': len(entries),
                            'missingFromTable': [], 'copyFailed': [],
                            'texturePackPath': str(load_path / mapping.build_name)})
    for build_id in ('build_a', 'build_b'):
        (env.output / f'{build_id}_texture_mapping.json').write_text(json.dumps({
            'build_id': build_id, 'build_name': build_id, 'created_at': 'now',
            'costumes': [{'index': i} for i in range(costumes)]}))
    app = Flask(__name__)
    app.register_blueprint(slippi.slippi_bp)
    app.register_blueprint(jobs_bp)
    env.client = app.test_client()
    env.gfx_ok = True
    return gfx


def _apply(env, build_id):
    response = env.client.post('/api/mex/texture-pack/auto-apply',
                               json={'buildId': build_id, 'slippiPath': 'slippi'})
    assert response.status_code == 200
    return response.get_json()['job_id']


def test_each_texture_job_reports_its_own_builds_pack(env, monkeypatch):
    # F-G-3: the result names the build it placed, under that job's id.
    gfx = _texture_env(env, monkeypatch, costumes=2)
    first, second = _apply(env, 'build_a'), _apply(env, 'build_b')
    a, b = _job(env, first), _job(env, second)
    assert a['kind'] == b['kind'] == 'texture_pack'
    assert a['status'] == b['status'] == 'done'
    assert (a['result']['buildId'], b['result']['buildId']) == ('build_a', 'build_b')
    assert a['result']['texturePackPath'].endswith('build_a')
    assert b['result']['texturePackPath'].endswith('build_b')
    assert gfx == [{'dump_textures': False, 'hires_textures': True}] * 2


def test_texture_job_fails_when_it_has_nothing_to_name_or_cannot_enable_textures(env, monkeypatch):
    _texture_env(env, monkeypatch, costumes=0)
    record = _job(env, _apply(env, 'build_a'))
    assert record['status'] == 'failed'
    assert 'no costume CSPs' in record['error']

    _texture_env(env, monkeypatch, costumes=1)
    env.gfx_ok = False
    record = _job(env, _apply(env, 'build_a'))
    assert record['status'] == 'failed'
    assert 'HD textures' in record['error']


# ---- Play: a bundle or a patch in the user's own Slippi ---------------------

@pytest.fixture
def launched(env, monkeypatch):
    """The user's Dolphin ISO folder is env.isos; a launch is recorded, never run."""
    from projects.install import xdelta as xdelta_tools
    from shared.ingame import boot
    started = []
    monkeypatch.setattr(boot, 'iso_dir_from_slippi', lambda path: env.isos)
    monkeypatch.setattr(boot, 'launch_real', lambda slippi, iso: started.append(Path(iso)))
    monkeypatch.setattr(xdelta_tools, 'XDELTA_PATH', env.patches)
    monkeypatch.setattr(xdelta_tools, 'require_xdelta_exe', lambda: 'xdelta3')
    return started


def _play_bundle(env, bundle_id='b1'):
    response = env.client.post(f'/api/mex/bundle/play/{bundle_id}', json={
        'slippiPath': 'slippi', 'vanillaIsoPath': str(env.vanilla)})
    assert response.status_code == 200
    return _job(env, response.get_json()['job_id'])


def _play_patch(env, patch_id='p1'):
    response = env.client.post(f'/api/mex/xdelta/play/{patch_id}', json={
        'slippiPath': 'slippi', 'vanillaIsoPath': str(env.vanilla)})
    assert response.status_code == 200
    return _job(env, response.get_json()['job_id'])


def test_bundle_play_builds_loads_its_textures_turns_them_on_and_launches(env, launched):
    _store_bundle(env, textures=('tex1.png', 'tex2.png'))
    record = _play_bundle(env)
    assert record['status'] == 'done', record
    assert record['kind'] == 'bundle_play' and record['params'] == {'bundleId': 'b1'}
    iso = Path(record['result']['iso_path'])
    assert iso.parent == env.isos and iso.read_bytes() == b'patched disc'
    assert record['result']['texture_count'] == 2
    loaded = env.user / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus' / 'build_b1'
    assert sorted(path.name for path in loaded.iterdir()) == ['tex1.png', 'tex2.png']
    gfx = configparser.ConfigParser()
    gfx.read(env.user / 'Config' / 'GFX.ini')
    assert gfx['Settings']['HiresTextures'] == 'True'
    assert launched == [iso]
    assert list(env.isos.glob('*.part.iso')) == []
    assert list(env.temp.iterdir()) == []          # its temp folder went with it

    again = _play_bundle(env)                       # the finished ISO is reused
    assert again['status'] == 'done'
    assert len(env.xdelta.runs) == 1 and launched == [iso, iso]


def test_a_bundle_play_that_cannot_build_leaves_nothing_and_launches_nothing(env, launched):
    _store_bundle(env)
    env.xdelta.code = 1                             # xdelta3 wrote half an ISO, then failed
    record = _play_bundle(env)
    assert record['status'] == 'failed'
    assert 'bad patch data' in record['error']
    assert launched == []
    assert list(env.isos.iterdir()) == []           # no staging file, ISO or marker
    assert list(env.temp.iterdir()) == []


def test_a_bundle_play_that_cannot_turn_on_hd_textures_fails_before_launching(env, launched):
    _store_bundle(env)
    (env.user / 'Config' / 'GFX.ini').mkdir(parents=True)     # unwritable as a file
    record = _play_bundle(env)
    assert record['status'] == 'failed'
    assert 'HD textures' in record['error']
    assert launched == []


# ---- a crafted bundle: every member is checked before any is read or written (vault/catalog/bundles.py)

def _no_such_drive():
    """A drive letter this computer does not have: should the check ever stop working, the drive-relative name
    fails to open instead of writing onto a real drive."""
    return next((f'{letter}:' for letter in 'QRSTUVWXYZ' if not os.path.exists(f'{letter}:/')), 'Q:')


@pytest.mark.parametrize('texture', [f'{_no_such_drive()}evil.png', 'ok.png:hidden.png', '../../escape.png',
                                     'CON.png'], ids=['drive', 'stream', 'dotdot', 'device'])
def test_a_bundle_play_refuses_a_texture_name_that_leaves_its_folder(env, launched, texture):
    """Before, textures/D:evil.png was written to D:evil.png (the current folder of drive D:) and
    textures/ok.png:hidden.png into an alternate data stream of ok.png."""
    _store_bundle(env, textures=('tex1.png', texture))
    record = _play_bundle(env)
    assert record['status'] == 'failed' and 'Invalid bundle' in record['error'], record
    assert launched == [] and env.xdelta.runs == []
    assert not (env.user / 'Load').exists() and list(env.isos.iterdir()) == []


def test_a_bundle_play_or_install_refuses_an_oversized_texture_or_manifest(env, launched, monkeypatch):
    from vault.catalog import bundles as catalog
    _store_bundle(env)
    monkeypatch.setattr(catalog, 'TEXTURE_MAX_BYTES', 2)        # each texture here is 3 bytes
    record = _play_bundle(env)
    assert record['status'] == 'failed' and 'textures/tex1.png is larger than' in record['error'], record
    assert _job(env, _install(env))['status'] == 'failed'
    monkeypatch.setattr(catalog, 'TEXTURE_MAX_BYTES', 1024)
    monkeypatch.setattr(catalog, 'MANIFEST_MAX_BYTES', 8)
    record = _play_bundle(env)
    assert record['status'] == 'failed' and 'manifest.json is larger than' in record['error'], record
    assert launched == [] and env.xdelta.runs == [] and not (env.user / 'Load').exists()


def test_bundle_import_checks_every_member_and_leaves_out_an_oversized_image(tmp_path, monkeypatch):
    from vault.catalog import bundles as catalog
    store = tmp_path / 'store'
    store.mkdir()
    saved = []
    monkeypatch.setattr(catalog, 'BUNDLE_PATH', store)
    monkeypatch.setattr(catalog, 'load_bundle_metadata', lambda: [])
    monkeypatch.setattr(catalog, 'save_bundle_metadata', saved.append)

    def bundle(name, **members):
        path = tmp_path / f'{name}.ssbm'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'name': name, 'build_name': 'b'}))
            for member, data in members.items():
                archive.writestr(member.replace('__', '/'), data)
        return path

    with pytest.raises(ValueError, match='Invalid bundle'):
        catalog.import_bundle_file(bundle('bad', **{'textures__a.png:s.png': b'x'}), 'bad')
    assert list(store.iterdir()) == [] and saved == []

    monkeypatch.setattr(catalog, 'IMAGE_MAX_BYTES', 4)
    result = catalog.import_bundle_file(bundle('ok', **{'textures__t.png': b'png', 'image.png': b'12345678'}), 'ok')
    assert [p.suffix for p in store.iterdir()] == ['.ssbm'], 'the bundle, without its oversized image'
    assert saved[0][0]['id'] == result['bundle_id'] and saved[0][0]['texture_count'] == 1

    monkeypatch.setattr(catalog, 'MANIFEST_MAX_BYTES', 8)
    with pytest.raises(ValueError, match='manifest.json is larger than'):
        catalog.import_bundle_file(bundle('big'), 'big')


def test_bundle_preview_reads_the_manifest_within_its_cap(env, monkeypatch):
    from vault.catalog import bundles as catalog
    _store_bundle(env)
    data = (env.bundles / 'b1.ssbm').read_bytes()

    def preview():
        return env.client.post('/api/mex/bundle/preview', data={'file': (io.BytesIO(data), 'b1.ssbm')},
                               content_type='multipart/form-data')
    assert preview().get_json()['manifest']['build_name'] == 'build_b1'
    monkeypatch.setattr(catalog, 'MANIFEST_MAX_BYTES', 8)
    refused = preview()
    assert refused.status_code == 400 and 'manifest.json is larger than' in refused.get_json()['error']


def test_patch_play_is_a_job_that_fails_with_the_build_error_or_launches(env, launched):
    env.xdelta.code = 1
    failed = _play_patch(env)
    assert failed['status'] == 'failed', failed
    assert failed['kind'] == 'patch_play'
    assert failed['params'] == {'patchId': 'p1', 'name': 'My Patch'}
    assert 'bad patch data' in failed['error']
    assert launched == [] and list(env.isos.iterdir()) == []

    env.xdelta.code = 0
    done = _play_patch(env)
    assert done['status'] == 'done', done
    iso = Path(done['result']['iso_path'])
    assert launched == [iso] and iso.read_bytes() == b'patched disc'
    assert list(env.isos.glob('*.part.iso')) == []


def test_play_of_an_unknown_patch_or_bundle_or_without_slippi_starts_no_job(env, launched):
    assert env.client.post('/api/mex/xdelta/play/nope', json={'slippiPath': 's'}).status_code == 404
    assert env.client.post('/api/mex/bundle/play/nope', json={'slippiPath': 's'}).status_code == 404
    assert env.client.post('/api/mex/xdelta/play/p1', json={}).status_code == 400
    _store_bundle(env)
    assert env.client.post('/api/mex/bundle/play/b1', json={}).status_code == 400
    assert jobs.list_jobs() == [] and launched == []


def test_job_cleanup_deletes_only_partial_outputs_and_job_folders(tmp_path):
    """What a patch or bundle job owned is deleted by name shape only, so a
    record naming anything else can never delete it."""
    from projects.install.xdelta import clean_job_files
    partials = [tmp_path / name for name in (
        'Mod.1a2b.part.iso', 'p1.part.xdelta', 'b1.ssbm.part', 'temp_bundle_image_x.png')]
    for path in partials:
        path.write_bytes(b'half')
    job_dir = tmp_path / 'bundle_play_abc'
    job_dir.mkdir()
    (job_dir / 'patch.xdelta').write_bytes(b'patch')
    kept = [tmp_path / 'Mod.iso', tmp_path / 'bundle_notes.txt', tmp_path / 'isos']
    kept[0].write_bytes(b'finished')
    kept[1].write_bytes(b'a file named like a job folder')
    kept[2].mkdir()
    (kept[2] / 'game.iso').write_bytes(b'game')

    for path in partials + [job_dir] + kept:
        assert clean_job_files('item', str(path)) is None
    clean_job_files('item', str(tmp_path / 'already-gone.part.iso'))

    assert not any(path.exists() for path in partials) and not job_dir.exists()
    assert all(path.exists() for path in kept)
    assert (kept[2] / 'game.iso').exists()
