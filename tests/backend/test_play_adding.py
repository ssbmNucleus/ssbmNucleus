"""Adding a finished export, or a Vault patch or bundle, to the Play shelf (play/adding.py, the
shelf_add job): which exports and Vault items are taken, the disc linked, copied or built into
the entry, its hash, the cover (a chosen one, else the source's picture or the disc's banner), a
bundle's textures for Dolphin, the reserved folder removed when an add fails, is cancelled or is
cut off by a restart, and replacing a game with a new build of it (same id, saves, cover and place;
the old one untouched when the replace fails; never while it runs). Everything runs in temporary
folders with a small stand-in disc and a stand-in xdelta3."""
from tests.paths import BACKEND
import hashlib
import io
import json
import os
import struct
import sys
import time
import zipfile
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(BACKEND))

from core import jobs  # noqa: E402
from play import adding, routing, shelf  # noqa: E402
from tests.backend.test_play_shelf import fake_plugin, stub_info  # noqa: E402
from projects.install import export_job  # noqa: E402

UI_KEY = 'window-only-key'
WINDOW = {'X-Nucleus-UI-Key': UI_KEY}
RED = 0xFC00            # RGB5A3, opaque: r=31 g=0 b=0


def _disc(path: Path, *, game_id=b'GALE01', banner=True):
    """A tiny GameCube disc: header, a two-entry FST, and opening.bnr when `banner`."""
    names = b'opening.bnr\0'
    bnr = b'BNR1' + b'\0' * 0x1C + struct.pack('>H', RED) * (96 * 32) + b'\0' * 0x140
    fst_off = 0x2000
    fst = bytearray()
    fst += struct.pack('>BxxxII', 1, 0, 2)                      # root: 2 entries
    file_off = 0x3000
    fst += struct.pack('>I', 0)[0:1] + (0).to_bytes(3, 'big') + struct.pack('>II', file_off, len(bnr))
    fst += names
    data = bytearray(file_off + len(bnr))
    data[0:6] = game_id
    if banner:
        struct.pack_into('>II', data, 0x424, fst_off, len(fst))
        data[fst_off:fst_off + len(fst)] = fst
        data[file_off:file_off + len(bnr)] = bnr
    path.write_bytes(bytes(data))
    return path


@pytest.fixture
def play(tmp_path, monkeypatch):
    root = tmp_path / 'play'
    monkeypatch.setattr(shelf, 'play_root', lambda: root)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    stub_info(monkeypatch)
    return root


@pytest.fixture
def export(tmp_path, monkeypatch):
    """A finished export: its ISO in a stand-in artifacts folder, found by its job id."""
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    found = {}

    def make(job_id='abc123', *, texture_pack=False, **disc):
        iso = _disc(artifacts / f'{job_id}.iso', **disc)
        found[job_id] = {'kind': export_job.EXPORT_KIND, 'status': 'done', 'result': {'path': str(iso)},
                         'params': {'filename': 'My Mod.iso', 'texturePackMode': texture_pack}}
        return job_id, iso

    monkeypatch.setattr(export_job, '_resolve_completed_artifact',
                        lambda job_id: Path(found[job_id]['result']['path']) if job_id in found else None)
    monkeypatch.setattr(export_job, 'export_job', lambda job_id: found.get(job_id))
    return make


def _wait(job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record and record['status'] in ('done', 'failed', 'cancelled'):
            return record
        time.sleep(0.05)
    raise AssertionError(f'job {job_id} did not end')


def _games(play):
    folder = play / shelf.GAMES_DIR
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


# --------------------------------------------------------------------------- which exports

def test_only_a_finished_melee_export_is_taken(play, export):
    with pytest.raises(shelf.ShelfError) as unknown:
        adding.finished_export('nope')
    assert unknown.value.status == 404
    with pytest.raises(shelf.ShelfError):
        adding.finished_export(None)
    job_id, _ = export('texture', texture_pack=True)
    with pytest.raises(shelf.ShelfError, match='texture-pack'):
        adding.finished_export(job_id)
    job_id, _ = export('notmelee', game_id=b'GZLE01')
    with pytest.raises(shelf.ShelfError, match='not a Melee disc'):
        adding.finished_export(job_id)
    job_id, iso = export('good')
    assert adding.finished_export(job_id)[0] == iso


# --------------------------------------------------------------------------- the job

def test_adding_links_hashes_and_makes_a_cover(play, export):
    job_id, iso = export()
    record = _wait(adding.start(job_id, name='  My Mod \x07', description='Made in Nucleus.\nTwo lines.'))
    assert record['status'] == 'done', record.get('error')
    entry = shelf.get(record['result']['entryId'])
    assert entry['name'] == 'My Mod' and entry['description'] == 'Made in Nucleus.\nTwo lines.'
    assert entry['origin'] == {'kind': 'export', 'filename': 'My Mod.iso'}
    assert entry['engine'] == shelf.ENGINE_SOURCE
    assert entry['targets'][shelf.TARGET_MU]['available'] and entry['targets'][shelf.TARGET_DOLPHIN]['available']

    disc = shelf.disc_path(entry)
    assert disc.read_bytes() == iso.read_bytes()
    assert entry['disc']['sha256'] == hashlib.sha256(iso.read_bytes()).hexdigest()
    assert entry['disc']['size'] == iso.stat().st_size
    assert entry['disc']['how'] == record['result']['how'] == 'linked'
    assert os.stat(disc).st_nlink == 2               # the export's file and the shelf's: one disc

    from PIL import Image
    with Image.open(shelf.cover_path(entry)) as cover:
        assert cover.size == (96 * adding.BANNER_SCALE, 32 * adding.BANNER_SCALE)
        assert cover.convert('RGBA').getpixel((10, 10)) == (255, 0, 0, 255)
    assert sorted(p.name for p in shelf.game_dir(entry).iterdir()) == [shelf.COVER_FILE, shelf.DISC_FILE]

    public = shelf.public(entry)
    assert public['hasCover'] is True and public['disc']['kind'] == 'owned'
    assert str(play) not in repr(public)             # no paths go to the page

    # Adding the same game again (the same name) is not a second card: the window is asked to replace it.
    with pytest.raises(shelf.ShelfError) as same:
        adding.start(job_id, name='my mod')
    assert same.value.status == 409 and same.value.details() == {
        'code': shelf.SAME_GAME, 'existing': {'id': entry['id'], 'name': 'My Mod'}}
    # Under another name it is a game of its own, with saves of its own.
    again = _wait(adding.start(job_id, name='My Mod, second copy'))
    assert again['result']['entryId'] != entry['id'] and again['result']['name'] == 'My Mod, second copy'


def test_a_disc_on_another_drive_is_copied(play, export, monkeypatch):
    job_id, iso = export()

    def no_link(*_args):
        raise OSError('different drives')
    monkeypatch.setattr(shelf.os, 'link', no_link)
    record = _wait(adding.start(job_id, name='Copied'))
    assert record['status'] == 'done', record.get('error')
    entry = shelf.get(record['result']['entryId'])
    assert entry['disc']['how'] == 'copied'
    assert shelf.disc_path(entry).read_bytes() == iso.read_bytes()
    assert not list(shelf.game_dir(entry).glob('*.part'))


def test_a_copy_needs_room(play, export, monkeypatch):
    job_id, _ = export()
    monkeypatch.setattr(shelf.os, 'link', lambda *_a: (_ for _ in ()).throw(OSError('no')))
    monkeypatch.setattr(shelf.shutil, 'disk_usage', lambda _p: type('U', (), {'free': 10})())
    record = _wait(adding.start(job_id))
    assert record['status'] == 'failed' and 'Not enough free space' in record['error']
    assert _games(play) == [] and [e['id'] for e in shelf.entries()] == ['retail', 'vanilla']


def test_a_failed_add_leaves_nothing(play, export, monkeypatch):
    job_id, _ = export()

    def broken(_disc):
        raise RuntimeError('boom')
    monkeypatch.setattr(routing, 'decide', broken)
    record = _wait(adding.start(job_id))
    assert record['status'] == 'failed'
    assert _games(play) == [] and len(shelf.entries()) == 2


def test_a_cancelled_add_leaves_nothing(play, export, monkeypatch):
    job_id, _ = export()

    def cancelled(*_a, **_k):
        raise jobs.Cancelled()
    monkeypatch.setattr(adding, 'sha256_file', cancelled)
    record = _wait(adding.start(job_id))
    assert record['status'] == 'cancelled'
    assert _games(play) == [] and len(shelf.entries()) == 2


def test_a_disc_without_a_banner_has_no_cover(play, export):
    job_id, _ = export(banner=False)
    record = _wait(adding.start(job_id))
    assert record['status'] == 'done', record.get('error')
    entry = shelf.get(record['result']['entryId'])
    assert shelf.cover_path(entry) is None and not entry.get('cover')


def test_cleanup_removes_only_a_reserved_folder(play):
    entry_id, folder = shelf.reserve()
    (folder / shelf.DISC_FILE).write_bytes(b'half')
    assert adding._clean_add('reserved', entry_id) is None
    assert not folder.exists()
    stored_id, stored_folder = shelf.reserve()
    shelf.add({'id': stored_id, 'name': 'Kept', 'disc': {'kind': 'owned'}})
    adding._clean_add('reserved', stored_id)         # stored after all: kept
    assert stored_folder.is_dir()
    adding._clean_add('reserved', '../../escape')    # not an id this store makes: ignored


def test_banner_picture_refuses_other_files():
    assert adding.banner_picture(b'') is None
    assert adding.banner_picture(b'XXXX' + b'\0' * 0x2000) is None


# --------------------------------------------------------------------------- the route

@pytest.fixture
def web(play):
    from play.routes.play import play_bp
    app = Flask(__name__)
    app.register_blueprint(play_bp)
    return app.test_client()


def test_vanilla_shows_the_banner_of_your_own_disc(web, tmp_path, monkeypatch):
    from PIL import Image
    from play import launch
    monkeypatch.setattr(launch, 'retail_iso', lambda: None)
    vanilla = {e['id']: e for e in web.get('/api/play/shelf').get_json()['entries']}['vanilla']
    assert vanilla['hasCover'] is False                                   # no disc yet: the page draws one
    assert web.get('/api/play/shelf/vanilla/cover').status_code == 404
    disc = _disc(tmp_path / 'melee.iso')
    monkeypatch.setattr(launch, 'retail_iso', lambda: str(disc))
    data = web.get('/api/play/shelf').get_json()
    entries = {e['id']: e for e in data['entries']}
    assert entries['vanilla']['hasCover'] is True and entries['retail']['hasCover'] is False
    assert [e['name'] for e in data['entries']] == ['Nucleus Unlocked', 'Vanilla']
    assert not list(shelf.play_root().glob(adding.DISC_BANNER_GLOB))     # read only when asked for

    def cover():
        reply = web.get('/api/play/shelf/vanilla/cover')
        status, mimetype, data = reply.status_code, reply.mimetype, reply.data
        reply.close()                                    # send_file's handle: Windows keeps an open file
        return status, mimetype, data

    status, mimetype, served = cover()
    assert status == 200 and mimetype == 'image/png'
    with Image.open(io.BytesIO(served)) as picture:
        # Its own 96x32: the page scales it by whole pixels (an added game's banner cover is 6x).
        assert picture.size == (96, 32) and picture.convert('RGB').getpixel((1, 1)) == (255, 0, 0)
    kept = list(shelf.play_root().glob(adding.DISC_BANNER_GLOB))
    assert len(kept) == 1 and [p.name for p in shelf.play_root().iterdir()] == [kept[0].name]
    assert cover()[2] == served                                                 # kept, not read again
    os.utime(disc, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))       # another disc: made again
    assert cover()[0] == 200
    assert len(list(shelf.play_root().glob(adding.DISC_BANNER_GLOB))) == 1 and not kept[0].exists()
    monkeypatch.setattr(launch, 'retail_iso', lambda: str(_disc(tmp_path / 'none.iso', banner=False)))
    assert web.get('/api/play/shelf/vanilla/cover').status_code == 404       # a disc without a banner
    assert web.get('/api/play/shelf/retail/cover').status_code == 404        # Nucleus Unlocked: drawn by the page


def test_the_add_route(web, export):
    job_id, _ = export()
    assert web.post('/api/play/shelf/add', json={'artifactId': job_id}).status_code == 403
    assert web.post('/api/play/shelf/add', json={'artifactId': job_id},
                    headers={**WINDOW, 'X-Nucleus-Agent': 'mcp'}).status_code == 403
    assert web.post('/api/play/shelf/add', json={'artifactId': 'missing'}, headers=WINDOW).status_code == 404
    assert web.post('/api/play/shelf/add', json={'artifactId': job_id, 'name': 5}, headers=WINDOW).status_code == 400
    answer = web.post('/api/play/shelf/add', json={'artifactId': job_id, 'name': 'From the route'}, headers=WINDOW)
    assert answer.status_code == 200
    record = _wait(answer.get_json()['job_id'])
    assert record['status'] == 'done' and shelf.get(record['result']['entryId'])['name'] == 'From the route'


# --------------------------------------------------------------------------- from the Vault

class _Xdelta:
    """Stands in for xdelta3 (projects/install/xdelta.decode_patch): writes `disc` to the
    command's last argument and exits with `code`; with `hang`, runs until it is killed."""
    def __init__(self, monkeypatch, tmp_path):
        from projects.install import xdelta
        self.runs, self.code, self.hang, self.killed = [], 0, False, []
        self.disc = _disc(tmp_path / 'built.iso')
        self.disc.write_bytes(self.disc.read_bytes()[:6].replace(b'GALE01', b'GALE01') + self.disc.read_bytes()[6:]
                              + b'modded')
        monkeypatch.setattr(xdelta, 'require_xdelta_exe', lambda: 'xdelta3')
        monkeypatch.setattr(xdelta, 'own', lambda proc: proc)
        monkeypatch.setattr(xdelta.subprocess, 'Popen', self._popen)

    def _popen(self, command, **kwargs):
        self.runs.append([str(c) for c in command])
        assert Path(command[-3]).is_file() and Path(command[-2]).is_file()   # the disc and the patch are there
        Path(command[-1]).write_bytes(self.disc.read_bytes())
        runner = self

        class Process:
            returncode = None

            def poll(self):
                if runner.hang and not runner.killed:
                    return None
                self.returncode = runner.code if not runner.killed else 1
                return self.returncode

            def communicate(self):
                return b'', (b'bad patch data' if self.returncode else b'')

            def kill(self):
                runner.killed.append(True)

            def wait(self, timeout=None):
                return 1
        return Process()


def _png(path: Path, size=(64, 48)):
    from PIL import Image
    Image.new('RGBA', size, (0, 255, 0, 255)).save(path, format='PNG')
    return path


@pytest.fixture
def vault(tmp_path, monkeypatch, play):
    """A stand-in Vault (its patch and bundle folders and index), the user's disc, and xdelta3."""
    from projects.install import xdelta
    from vault.catalog import bundles
    from play import launch
    patches, bundle_dir = tmp_path / 'vault-xdelta', tmp_path / 'vault-bundles'
    patches.mkdir()
    bundle_dir.mkdir()
    index = {'patch': [], 'bundle': []}
    monkeypatch.setattr(xdelta, 'XDELTA_PATH', patches)
    monkeypatch.setattr(bundles, 'BUNDLE_PATH', bundle_dir)
    monkeypatch.setattr(xdelta, 'load_xdelta_metadata', lambda: list(index['patch']))
    monkeypatch.setattr(bundles, 'load_bundle_metadata', lambda: list(index['bundle']))
    retail = _disc(tmp_path / 'retail.iso')
    monkeypatch.setattr(launch, 'retail_iso', lambda: retail)
    checked = []
    monkeypatch.setattr(launch, 'check_retail_iso', lambda iso: checked.append(Path(iso)))

    class Vault:
        pass
    v = Vault()
    v.patches, v.bundles, v.index, v.retail, v.checked = patches, bundle_dir, index, retail, checked
    v.xdelta = _Xdelta(monkeypatch, tmp_path)

    def patch(item_id='a1b2c3d4', name='Akaneia Lite', description='A smaller Akaneia.', picture=True):
        (patches / f'{item_id}.xdelta').write_bytes(b'VCD patch')
        if picture:
            _png(patches / f'{item_id}.png')
        index['patch'].append({'id': item_id, 'name': name, 'description': description})
        return item_id

    def bundle(item_id='b5e6f7a8', name='Diet Melee', textures=('tex1.png', 'tex2.png'), members=None,
               manifest=None):
        with zipfile.ZipFile(bundle_dir / f'{item_id}.ssbm', 'w') as archive:
            if members is None:
                archive.writestr('manifest.json', json.dumps(manifest or {'name': name, 'build_name': 'diet_build'}))
                archive.writestr('patch.xdelta', b'VCD patch')
                for texture in textures:
                    archive.writestr(f'textures/{texture}', b'png bytes ' + texture.encode())
            else:
                for member, data in members.items():
                    archive.writestr(member, data)
        index['bundle'].append({'id': item_id, 'name': name, 'description': 'Bundle description.'})
        return item_id
    v.patch, v.bundle = patch, bundle
    return v


def test_a_vault_patch_is_built_onto_the_users_disc(play, vault):
    patch_id = vault.patch()
    record = _wait(adding.start_from_vault('patch', patch_id))
    assert record['status'] == 'done', record.get('error')
    assert record['params'] == {'name': 'Akaneia Lite', 'from': 'patch'}
    entry = shelf.get(record['result']['entryId'])
    assert entry['name'] == 'Akaneia Lite' and entry['description'] == 'A smaller Akaneia.'
    assert entry['origin'] == {'kind': 'patch', 'name': 'Akaneia Lite'}
    assert entry['disc']['how'] == record['result']['how'] == 'built'
    disc = shelf.disc_path(entry)
    assert disc.read_bytes() == vault.xdelta.disc.read_bytes()
    assert entry['disc']['sha256'] == hashlib.sha256(disc.read_bytes()).hexdigest()
    assert vault.checked == [vault.retail]                    # the user's disc is checked first
    [run] = vault.xdelta.runs
    assert run[:5] == ['xdelta3', '-d', '-f', '-s', str(vault.retail)]
    assert run[5] == str(vault.patches / f'{patch_id}.xdelta')
    assert Path(run[6]).parent == shelf.game_dir(entry) and Path(run[6]).name == adding.DISC_PART
    # The Vault's picture is the cover (not the disc's banner).
    from PIL import Image
    with Image.open(shelf.cover_path(entry)) as cover:
        assert cover.size == (64, 48)
    assert sorted(p.name for p in shelf.game_dir(entry).iterdir()) == [shelf.COVER_FILE, shelf.DISC_FILE]
    # Nothing points back at the Vault: removing the patch there leaves the game as it is.
    assert patch_id not in json.dumps(entry)
    (vault.patches / f'{patch_id}.xdelta').unlink()
    vault.index['patch'].clear()
    assert shelf.get(entry['id'])['disc'] == entry['disc'] and disc.is_file()


def test_a_name_and_description_given_replace_the_vaults(play, vault):
    patch_id = vault.patch(picture=False)
    record = _wait(adding.start_from_vault('patch', patch_id, name='My copy', description=''))
    entry = shelf.get(record['result']['entryId'])
    assert entry['name'] == 'My copy' and entry['description'] == ''
    with Image_open(shelf.cover_path(entry)) as cover:          # no picture: the disc's banner
        assert cover.size == (96 * adding.BANNER_SCALE, 32 * adding.BANNER_SCALE)


def Image_open(path):
    from PIL import Image
    return Image.open(path)


def test_a_vault_bundle_keeps_its_textures_for_dolphin(play, vault):
    bundle_id = vault.bundle()
    _png(vault.bundles / f'{bundle_id}.png', size=(30, 40))
    record = _wait(adding.start_from_vault('bundle', bundle_id))
    assert record['status'] == 'done', record.get('error')
    entry = shelf.get(record['result']['entryId'])
    assert entry['name'] == 'Diet Melee' and entry['origin'] == {'kind': 'bundle', 'name': 'Diet Melee'}
    assert entry['texturePack'] == {'buildName': 'diet_build', 'count': 2}
    textures = shelf.textures_dir(entry)
    assert sorted(p.name for p in textures.iterdir()) == ['tex1.png', 'tex2.png']
    assert (textures / 'tex1.png').read_bytes() == b'png bytes tex1.png'
    # The bundle's patch was decoded from a copy in the reserved folder, removed afterwards.
    [run] = vault.xdelta.runs
    assert Path(run[5]).name == adding.PATCH_PART and Path(run[5]).parent == shelf.game_dir(entry)
    assert sorted(p.name for p in shelf.game_dir(entry).iterdir()) == [
        shelf.COVER_FILE, shelf.DISC_FILE, shelf.TEXTURES_DIR]
    public = shelf.public(entry)
    assert public['textures'] == 2 and 'diet_build' not in json.dumps(public) and str(play) not in repr(public)
    assert bundle_id not in json.dumps(entry)


def test_a_bundle_s_textures_go_to_dolphin_with_it(play, vault, tmp_path, monkeypatch):
    from play import launch
    from projects.routes import bundles as project_bundles
    record = _wait(adding.start_from_vault('bundle', vault.bundle()))
    entry = shelf.get(record['result']['entryId'])
    user = tmp_path / 'slippi-user'
    stale = user / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus' / 'another_build'
    stale.mkdir(parents=True)
    (stale / 'old.png').write_bytes(b'old')
    monkeypatch.setattr(project_bundles, 'slippi_user_dir', lambda path: user)
    started = []
    monkeypatch.setattr(launch, 'dolphin_command',
                        lambda slippi, disc: launch.LaunchCommand(args=['dolphin', '-e', str(disc)], cwd=tmp_path))
    monkeypatch.setattr(launch, 'start', lambda command: started.append(command))
    done = _wait(launch.launch(entry['id'], target=shelf.TARGET_DOLPHIN, slippi_path=str(tmp_path / 'Slippi')))
    assert done['status'] == 'done', done.get('error')
    loaded = user / 'Load' / 'Textures' / 'GALE01' / 'ssbm-nucleus'
    assert [p.name for p in loaded.iterdir()] == ['diet_build']
    assert sorted(p.name for p in (loaded / 'diet_build').iterdir()) == ['tex1.png', 'tex2.png']
    import configparser
    gfx = configparser.ConfigParser()
    gfx.read(user / 'Config' / 'GFX.ini')
    assert gfx['Settings']['HiresTextures'] == 'True'
    assert started and started[0].args[-1] == str(shelf.disc_path(entry))


def test_vault_items_are_found_by_their_indexed_id_only(play, vault):
    vault.patch()
    for kind, item_id, status in (('patch', 'nope', 404), ('patch', '../a1b2c3d4', 404), ('patch', None, 404),
                                  ('patch', 'a1b2c3d4\\x', 404), ('iso', 'a1b2c3d4', 400),
                                  ('bundle', 'a1b2c3d4', 404)):
        with pytest.raises(shelf.ShelfError) as caught:
            adding.vault_item(kind, item_id)
        assert caught.value.status == status, (kind, item_id)
    vault.index['patch'].append({'id': 'deadbeef', 'name': 'Gone'})      # indexed, file deleted
    with pytest.raises(shelf.ShelfError, match='missing from your Vault'):
        adding.vault_item('patch', 'deadbeef')
    vault.index['patch'].append({'id': '..', 'name': 'Odd'})
    with pytest.raises(shelf.ShelfError):
        adding.vault_item('patch', '..')
    item = adding.vault_item('patch', 'a1b2c3d4')
    assert item['file'] == vault.patches / 'a1b2c3d4.xdelta' and item['picture'] == vault.patches / 'a1b2c3d4.png'


@pytest.mark.parametrize('members, words', [
    ({'manifest.json': '{"name": "x", "build_name": "b"}'}, 'no patch.xdelta'),
    ({'patch.xdelta': b'p'}, 'manifest.json missing'),
    ({'manifest.json': '{"name": "x", "build_name": "../up"}', 'patch.xdelta': b'p'}, 'cannot be used'),
    ({'manifest.json': '{"name": "x", "build_name": "b"}', 'patch.xdelta': b'p', '../escape.png': b'x'},
     'cannot be used'),
    ({'manifest.json': '{"name": "x", "build_name": "b"}', 'patch.xdelta': b'p', 'C:/evil.png': b'x'},
     'cannot be used'),
])
def test_a_bundle_that_fails_the_vaults_checks_is_refused(play, vault, members, words):
    bundle_id = vault.bundle(members=members)
    with pytest.raises(shelf.ShelfError, match=words.replace('.', '\\.')):
        adding.start_from_vault('bundle', bundle_id)
    assert _games(play) == [] and vault.xdelta.runs == []


def test_a_build_that_fails_leaves_nothing(play, vault):
    vault.xdelta.code = 1
    record = _wait(adding.start_from_vault('patch', vault.patch()))
    assert record['status'] == 'failed'
    assert 'could not be built onto your Melee disc' in record['error'] and 'bad patch data' in record['error']
    assert _games(play) == [] and len(shelf.entries()) == 2


def test_a_build_that_is_not_melee_leaves_nothing(play, vault):
    _disc(vault.xdelta.disc, game_id=b'GZLE01')
    record = _wait(adding.start_from_vault('bundle', vault.bundle()))
    assert record['status'] == 'failed' and 'did not build a Melee disc' in record['error']
    assert _games(play) == []


def test_cancelling_a_build_ends_xdelta(play, vault):
    vault.xdelta.hang = True
    job_id = adding.start_from_vault('patch', vault.patch())
    deadline = time.time() + 10
    while not vault.xdelta.runs and time.time() < deadline:
        time.sleep(0.02)
    jobs.cancel(job_id)
    record = _wait(job_id)
    assert record['status'] == 'cancelled'
    assert vault.xdelta.killed and _games(play) == []


def test_without_the_users_disc_nothing_is_built(play, vault, monkeypatch):
    from play import launch
    monkeypatch.setattr(launch, 'retail_iso', lambda: None)
    with pytest.raises(shelf.ShelfError, match='needs your Melee ISO'):
        adding.start_from_vault('patch', vault.patch())
    monkeypatch.setattr(launch, 'retail_iso', lambda: vault.retail)

    def refuse(iso):
        raise launch.PlayError("Your Melee ISO can't be used: it is modded.")
    monkeypatch.setattr(launch, 'check_retail_iso', refuse)
    record = _wait(adding.start_from_vault('patch', 'a1b2c3d4'))
    assert record['status'] == 'failed' and 'is modded' in record['error']
    assert _games(play) == [] and vault.xdelta.runs == []


def test_the_add_route_takes_one_vault_item(web, vault):
    patch_id, bundle_id = vault.patch(), vault.bundle()
    assert web.post('/api/play/shelf/add', json={'patchId': patch_id}).status_code == 403
    assert web.post('/api/play/shelf/add', json={'patchId': patch_id},
                    headers={**WINDOW, 'X-Nucleus-Agent': 'mcp'}).status_code == 403
    assert web.post('/api/play/shelf/add', json={}, headers=WINDOW).status_code == 400
    assert web.post('/api/play/shelf/add', json={'patchId': patch_id, 'bundleId': bundle_id},
                    headers=WINDOW).status_code == 400
    assert web.post('/api/play/shelf/add', json={'patchId': 'C:\\Windows\\x'}, headers=WINDOW).status_code == 404
    answer = web.post('/api/play/shelf/add', json={'bundleId': bundle_id, 'name': 'Via route'}, headers=WINDOW)
    assert answer.status_code == 200
    record = _wait(answer.get_json()['job_id'])
    assert record['status'] == 'done' and shelf.get(record['result']['entryId'])['name'] == 'Via route'


def test_decode_patch_reports_progress_and_stops(tmp_path, monkeypatch):
    from projects.install import xdelta
    fake = _Xdelta(monkeypatch, tmp_path)
    source, patch = _disc(tmp_path / 'source.iso'), tmp_path / 'p.xdelta'
    patch.write_bytes(b'p')
    seen = []
    report = xdelta.building_progress(lambda f, d: seen.append((round(f, 2), d)), start=10, span=80)
    xdelta.decode_patch(source, patch, tmp_path / 'out.iso', progress=report)
    assert (tmp_path / 'out.iso').is_file()
    fake.hang = True
    with pytest.raises(jobs.Cancelled):
        xdelta.decode_patch(source, patch, tmp_path / 'out2.iso', should_stop=lambda: True)
    assert fake.killed
    fake.hang, fake.killed[:], fake.code = False, [], 3
    with pytest.raises(RuntimeError, match='Failed to build ISO: bad patch data'):
        xdelta.decode_patch(source, patch, tmp_path / 'out3.iso')
    report(0.5)
    report(0.5)
    assert seen[-1] == (0.5, 'Building ISO... 40%') and seen.count((0.5, 'Building ISO... 40%')) == 1


# --------------------------------------------------------------------------- the cover chosen when adding

def _picture(size=(300, 200), color=(0, 0, 255), fmt='PNG'):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format=fmt)
    return out.getvalue()


def _cover_of(entry):
    """(size, colour at 1,1) of an entry's stored cover."""
    from PIL import Image
    with Image.open(shelf.cover_path(entry)) as cover:
        return cover.size, cover.convert('RGB').getpixel((1, 1))


def test_a_chosen_cover_is_used_instead_of_the_banner(play, export):
    job_id, _ = export()
    record = _wait(adding.start(job_id, cover=shelf.encode_cover(_picture())))
    assert record['status'] == 'done', record.get('error')
    entry = shelf.get(record['result']['entryId'])
    assert _cover_of(entry) == ((300, 200), (0, 0, 255))
    assert entry['cover'] is True and shelf.public(entry)['hasCover'] is True


def test_a_chosen_cover_is_used_instead_of_the_vault_picture(play, vault):
    record = _wait(adding.start_from_vault('patch', vault.patch(), cover=shelf.encode_cover(_picture(size=(20, 10)))))
    assert record['status'] == 'done', record.get('error')
    assert _cover_of(shelf.get(record['result']['entryId']))[0] == (20, 10)          # not the Vault's 64x48


def test_the_add_route_takes_a_chosen_cover(web, export, play):
    job_id, _ = export()

    def send(cover, **fields):
        return web.post('/api/play/shelf/add', headers=WINDOW, content_type='multipart/form-data',
                        data={'artifactId': job_id, **fields, 'cover': (io.BytesIO(cover), 'cover.jpg')})
    bad = send(b'<html>not a picture</html>', name='Bad')
    assert bad.status_code == 400 and 'not a picture Nucleus can read' in bad.get_json()['error']
    assert send(b'\0' * (shelf.MAX_COVER_BYTES + 1), name='Huge').status_code == 413
    assert _games(play) == [] and len(shelf.entries()) == 2          # refused before anything was reserved

    answer = send(_picture(size=(2048, 1024), color=(255, 255, 0), fmt='JPEG'), name='With a cover',
                  description='Picked.')
    assert answer.status_code == 200, answer.get_json()
    record = _wait(answer.get_json()['job_id'])
    assert record['status'] == 'done', record.get('error')
    entry = shelf.get(record['result']['entryId'])
    assert entry['name'] == 'With a cover' and entry['description'] == 'Picked.'
    size, colour = _cover_of(entry)
    assert size == (shelf.COVER_SIZE, shelf.COVER_SIZE // 2)            # scaled to the shelf's limit
    assert colour[0] > 240 and colour[1] > 240 and colour[2] < 20
    assert shelf.cover_path(entry).read_bytes().startswith(b'\x89PNG')    # kept re-encoded as PNG
    assert shelf.cover_path(entry).parent == shelf.game_dir(entry)        # in the entry's own folder


def test_a_cover_is_never_written_outside_the_entry_folder(play, tmp_path):
    winapi = pytest.importorskip('_winapi')
    entry_id, folder = shelf.reserve()
    outside = tmp_path / 'outside'
    outside.mkdir()
    folder.rmdir()
    winapi.CreateJunction(str(outside), str(folder))           # games/<id> now leads somewhere else
    try:
        with pytest.raises(shelf.ShelfError, match='not inside the Play folder'):
            shelf.write_cover({'id': entry_id}, shelf.encode_cover(_picture()))
        assert list(outside.iterdir()) == []
    finally:
        os.rmdir(folder)


# --------------------------------------------------------------------------- replacing a game with a new build

def _two_games(export):
    first, _ = export('abc123')
    a = shelf.get(_wait(adding.start(first, name='My Mod'))['result']['entryId'])
    other, _ = export('other1')
    b = shelf.get(_wait(adding.start(other, name='Other game'))['result']['entryId'])
    return a, b


def _rebuild(export, job_id='def456', change=b'a newer build'):
    """A later export of the same game: another disc."""
    job_id, iso = export(job_id)
    iso.write_bytes(iso.read_bytes() + change)
    return job_id, iso


def test_replacing_keeps_the_game_s_id_saves_cover_and_place(play, export):
    a, b = _two_games(export)
    saves = shelf.data_dir(a) / 'User' / 'GC'
    saves.mkdir(parents=True)
    (saves / 'card.raw').write_bytes(b'my saves')
    shelf.set_cover(a['id'], _picture(color=(0, 0, 255)))
    shelf.update(a['id'], description='Mine.', engine_choice='compat', last_target=shelf.TARGET_DOLPHIN)
    plugins = shelf.fighters_dir(a)
    plugins.mkdir()
    (plugins / 'wolf.mufighter').write_bytes(b'plugin')
    old_folder = shelf.game_dir(a)

    job_id, iso = _rebuild(export)
    with pytest.raises(shelf.ShelfError) as same:                 # the same name, in any case
        adding.start(job_id, name='MY MOD')
    assert same.value.details()['existing'] == {'id': a['id'], 'name': 'My Mod'}
    record = _wait(adding.start(job_id, name='MY MOD', replace=a['id']))
    assert record['status'] == 'done', record.get('error')
    assert record['result'] == {'entryId': a['id'], 'how': 'linked', 'name': 'My Mod', 'replaced': True}
    assert record['params']['replace'] == a['id'] and record['label'] == 'Replace MY MOD on the shelf'

    entry = shelf.get(a['id'])
    assert [e['id'] for e in shelf.entries()] == ['retail', 'vanilla', a['id'], b['id']]       # its place
    assert entry['name'] == 'My Mod' and entry['description'] == 'Mine.' and entry['createdAt'] == a['createdAt']
    assert entry['replacedAt'] and entry['origin'] == a['origin']
    assert entry['disc']['sha256'] == hashlib.sha256(iso.read_bytes()).hexdigest() != a['disc']['sha256']
    assert shelf.disc_path(entry).read_bytes() == iso.read_bytes()
    assert entry['options']['engine'] == 'compat' and entry['lastTarget'] == shelf.TARGET_DOLPHIN
    assert _cover_of(entry)[1] == (0, 0, 255)                         # its own cover, not the new banner
    assert (shelf.fighters_dir(entry) / 'wolf.mufighter').read_bytes() == b'plugin'
    assert shelf.data_dir(entry) == shelf.data_dir(a) and (saves / 'card.raw').read_bytes() == b'my saves'
    # The new build was made beside the old folder; the old one goes once nothing uses it.
    assert shelf.game_dir(entry) != old_folder and not old_folder.exists()
    assert _games(play) == sorted([shelf.game_dir(entry).name, shelf.game_dir(b).name])
    public = shelf.public(entry)
    assert 'files' not in public and str(play) not in repr(public) and public['hasCover'] is True

    # Replaced again: the folder it used before goes the same way.
    again_id, again_iso = _rebuild(export, 'ghi789', change=b'the build after that')
    second = _wait(adding.start(again_id, name='My Mod', replace=a['id']))
    assert second['status'] == 'done', second.get('error')
    assert shelf.disc_path(shelf.get(a['id'])).read_bytes() == again_iso.read_bytes()
    assert len(_games(play)) == 2 and _cover_of(shelf.get(a['id']))[1] == (0, 0, 255)


def test_a_cover_chosen_with_a_replace_is_the_new_cover(play, export):
    a, _ = _two_games(export)
    job_id, _ = _rebuild(export)
    record = _wait(adding.start(job_id, name='My Mod', replace=a['id'],
                                cover=shelf.encode_cover(_picture(size=(40, 30)))))
    assert record['status'] == 'done', record.get('error')
    assert _cover_of(shelf.get(a['id']))[0] == (40, 30)


def test_a_replace_that_fails_or_is_cancelled_leaves_the_old_game(play, export, monkeypatch):
    a, _ = _two_games(export)
    before = shelf.get(a['id'])
    files = sorted(p.name for p in shelf.game_dir(a).iterdir())
    disc = shelf.disc_path(a).read_bytes()
    job_id, _ = _rebuild(export)

    real_decide = routing.decide

    def broken(_disc):
        raise RuntimeError('boom')
    monkeypatch.setattr(routing, 'decide', broken)
    assert _wait(adding.start(job_id, name='My Mod', replace=a['id']))['status'] == 'failed'
    monkeypatch.setattr(routing, 'decide', real_decide)

    def cancelled(*_a, **_k):
        raise jobs.Cancelled()
    monkeypatch.setattr(adding, 'sha256_file', cancelled)
    assert _wait(adding.start(job_id, name='My Mod', replace=a['id']))['status'] == 'cancelled'

    after = shelf.get(a['id'])
    assert after == before and sorted(p.name for p in shelf.game_dir(after).iterdir()) == files
    assert shelf.disc_path(after).read_bytes() == disc
    assert len(_games(play)) == 2                     # nothing left of either attempt


def test_a_running_game_is_not_replaced(play, export, monkeypatch):
    from play import launch
    a, _ = _two_games(export)
    job_id, _ = _rebuild(export)
    monkeypatch.setattr(launch, 'running_entry', lambda: a['id'])
    with pytest.raises(shelf.ShelfError) as refused:
        adding.start(job_id, name='My Mod', replace=a['id'])
    assert refused.value.status == 409 and 'running' in str(refused.value)

    # Started while the new build was being made: the swap refuses it, and the old game stays.
    asked = []

    def running_by_the_swap():
        asked.append(True)
        return a['id'] if len(asked) > 1 else None
    monkeypatch.setattr(launch, 'running_entry', running_by_the_swap)
    before = shelf.get(a['id'])
    record = _wait(adding.start(job_id, name='My Mod', replace=a['id']))
    assert record['status'] == 'failed' and 'running' in record['error'] and len(asked) == 2
    assert shelf.get(a['id']) == before and len(_games(play)) == 2


def test_only_an_added_game_can_be_replaced(play, export):
    job_id, _ = export()
    with pytest.raises(shelf.ShelfError, match='built-in'):
        adding.start(job_id, replace='retail')
    for unknown in ('0123456789ab', '../../escape', 5):
        with pytest.raises(shelf.ShelfError) as caught:
            adding.start(job_id, replace=unknown)
        assert caught.value.status == 404
    # A game named like a built-in one is a game of its own: the built-in games are never replaced.
    record = _wait(adding.start(job_id, name='Melee'))
    assert record['status'] == 'done' and 'replaced' not in record['result']
    assert _games(play) == [record['result']['entryId']]


def test_a_game_planned_before_a_replace_does_not_start_on_the_old_files(play, export):
    from play import launch
    a, _ = _two_games(export)
    planned = shelf.get(a['id'])
    job_id, _ = _rebuild(export)
    assert _wait(adding.start(job_id, name='My Mod', replace=a['id']))['status'] == 'done'
    with pytest.raises(launch.PlayError) as refused:
        launch._still_the_same_files(planned)
    assert refused.value.status == 409
    launch._still_the_same_files(shelf.get(a['id']))
    launch._still_the_same_files(shelf.get('retail'))


def test_what_a_replace_owned_is_cleaned_up_after_a_crash(play, export):
    a, _ = _two_games(export)
    new_id, new_folder = shelf.reserve()                 # a replace that died before its swap
    old = shelf.folder_of(a['id'])
    adding._clean_add('retired', old)                    # still the entry's files: kept
    adding._clean_add('reserved', new_id)                # never used: removed
    assert (play / shelf.GAMES_DIR / old).is_dir() and not new_folder.exists()


def test_a_vault_patch_replaces_the_game_it_made(play, vault):
    patch_id = vault.patch()
    first = shelf.get(_wait(adding.start_from_vault('patch', patch_id))['result']['entryId'])
    shelf.update(first['id'], description='My notes.')
    with pytest.raises(shelf.ShelfError) as same:
        adding.start_from_vault('patch', patch_id)
    assert same.value.details()['code'] == shelf.SAME_GAME
    vault.xdelta.disc.write_bytes(vault.xdelta.disc.read_bytes() + b'v2')
    record = _wait(adding.start_from_vault('patch', patch_id, replace=first['id']))
    assert record['status'] == 'done', record.get('error')
    assert record['params'] == {'name': 'Akaneia Lite', 'from': 'patch', 'replace': first['id']}
    entry = shelf.get(first['id'])
    assert entry['description'] == 'My notes.'                       # its own, not the Vault's again
    assert entry['disc']['sha256'] != first['disc']['sha256']
    assert len(_games(play)) == 1


def test_the_add_route_offers_and_does_a_replace(web, export, play):
    job_id, _ = export()
    first = _wait(web.post('/api/play/shelf/add', json={'artifactId': job_id, 'name': 'Routed'},
                           headers=WINDOW).get_json()['job_id'])
    entry_id = first['result']['entryId']
    same = web.get('/api/play/shelf/same', query_string={'name': ' routed '}).get_json()
    assert same == {'success': True, 'existing': {'id': entry_id, 'name': 'Routed', 'running': False}}
    assert web.get('/api/play/shelf/same', query_string={'name': 'Something else'}).get_json()['existing'] is None
    assert web.get('/api/play/shelf/same', query_string={'name': 'Melee'}).get_json()['existing'] is None

    again = web.post('/api/play/shelf/add', json={'artifactId': job_id, 'name': 'Routed'}, headers=WINDOW)
    assert again.status_code == 409
    assert again.get_json() == {'success': False, 'error': '"Routed" is already on your Unlocked shelf.',
                                'code': 'already_on_shelf', 'existing': {'id': entry_id, 'name': 'Routed'}}
    second_id, _ = _rebuild(export)
    answer = web.post('/api/play/shelf/add', headers=WINDOW, content_type='multipart/form-data',
                      data={'artifactId': second_id, 'name': 'Routed', 'replace': entry_id,
                            'cover': (io.BytesIO(_picture(size=(50, 50))), 'c.png')})
    assert answer.status_code == 200, answer.get_json()
    record = _wait(answer.get_json()['job_id'])
    assert record['status'] == 'done', record.get('error')
    assert record['result']['replaced'] is True and record['result']['entryId'] == entry_id
    assert _cover_of(shelf.get(entry_id))[0] == (50, 50)
    assert web.post('/api/play/shelf/add', json={'artifactId': second_id, 'replace': 'vanilla'},
                    headers=WINDOW).status_code == 400
