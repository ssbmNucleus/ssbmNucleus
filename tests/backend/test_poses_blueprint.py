"""
Pose library + pose portraits (vault/routes/poses.py).

The Vault's pose editor saves camera/animation "poses" per character and
re-renders portraits (CSPs) with them: for selected vault skins, or for every
costume installed in the open MEX project. A regression here can silently
overwrite or corrupt portraits across a whole character, so these tests pin the
user-visible contract on a temp vault + temp vanilla-assets tree:

  * pose library CRUD (save / list / thumbnail / start-from / delete)
  * which skins a bulk render touches (only the selected ones of ONE character)
  * what a failed render leaves behind (nothing; originals keep their bytes)
  * names from the client cannot escape their folders

The native renderer (HSDRawViewer behind shared.rendering.portrait) and MexCLI are
replaced at the blueprint's seams, so nothing here needs Dolphin,
HSDRawViewer, an ISO, network access or real game files.
"""
import hashlib
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import vault.routes.poses as poses
import core.state as core_state
import shared.rendering.portrait as portrait

API = '/api/mex/storage/poses'
SD = (136, 188)  # vanilla CSP size the project PNGs must end up at

SYMBOL_POSE = """frame: 12
cSPMode: true
showGrid: false
showBackdrop: false
animSymbol: PlyFox5K_Share_ACTION_Wait1_figatree
camera:
  x: 1
  y: 10
  z: -80
  scale: 1
  fovRadians: 0.5236
  rotationXRadians: 0
  rotationYRadians: 0
"""

SCENE_POSE = SYMBOL_POSE.replace(
    'animSymbol: PlyFox5K_Share_ACTION_Wait1_figatree', 'useSceneAnimation: true')

BAKED_SCENE = """settings:
  lighting: default
camera:
  x: 0
  y: 10
  z: -80
  farClipPlane: 100000
  nearClipPlane: 10
animation:
  name: baked-scene-pose
  frames: 3
"""


# ============= image helpers =============

def _color_for(dat: bytes):
    h = hashlib.sha1(dat).digest()
    return (h[0], h[1], h[2], 255)


def _png(path: Path, size=SD, color=(10, 20, 30, 255), tag=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngInfo()
    if tag:
        info.add_text('src', tag)
    Image.new('RGBA', size, color).save(path, pnginfo=info)
    return path


def _pixel_and_size(path: Path):
    with Image.open(path) as im:
        return im.convert('RGBA').getpixel((0, 0)), im.size


def _tag(path):
    """Which DAT (and scale) the fake renderer produced this PNG (path or stream) from."""
    with Image.open(path) as im:
        return im.info.get('src')


def _tree(root: Path):
    """Every file under root (minus the metadata store) -> bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob('*')
            if p.is_file() and p.name not in ('metadata.json', 'vault.db')}


# ============= fakes at the native seams =============

class FakeRenderer:
    """Stands in for shared.rendering.portrait's renders. Like the real generator it
    writes its PNG next to the input DAT and returns that path. The PNG's
    colour + text tag identify the DAT it was rendered from."""

    def __init__(self):
        self.calls = []
        self.layer_calls = []
        self.outcome = lambda call: 'ok'   # -> 'ok' | 'none' | 'raise'

    def _run(self, call, dat_file, scale):
        self.calls.append(call)
        outcome = self.outcome(call)
        if outcome == 'raise':
            raise RuntimeError('renderer crashed')
        if outcome == 'none':
            return None
        out = Path(dat_file).with_name(f'{Path(dat_file).stem}_render_{scale}x.png')
        _png(out, size=(SD[0] * scale, SD[1] * scale), color=_color_for(call['dat']),
             tag=f"{call['dat'].decode(errors='replace')}@{scale}")
        return str(out)

    def render_pose(self, dat_file, character, pose_path, aj_file, scale, *args, **kwargs):
        call = {'kind': 'pose', 'dat': Path(dat_file).read_bytes(), 'character': character,
                'pose': Path(pose_path).stem, 'aj': aj_file, 'scale': scale}
        return self._run(call, dat_file, scale)

    def render_default(self, dat_file, character, *, scale=1, **kwargs):
        call = {'kind': 'default', 'dat': Path(dat_file).read_bytes(), 'character': character,
                'pose': None, 'aj': None, 'scale': scale}
        return portrait.Portrait(self._run(call, dat_file, scale), False)

    def layers(self, csp_path, character, scale):
        self.layer_calls.append((character, scale))

    def rendered(self):
        """[(dat bytes, scale)] in call order."""
        return [(c['dat'], c['scale']) for c in self.calls]


class FakeMex:
    """The open MEX project, with MexCLI answered in-process."""

    def __init__(self, root: Path, costumes=(), recompile=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / 'assets').mkdir(exist_ok=True)
        (root / 'files').mkdir(exist_ok=True)
        self.project_path = root / 'project.mexproj'
        self.project_path.write_text('{}', encoding='utf-8')
        self.costumes = list(costumes)
        self.recompile = recompile or {'success': True, 'recompiledCount': 3}
        self.commands = []

    def _run_command(self, cmd, *args):
        self.commands.append((cmd,) + args)
        if cmd == 'get-costumes':
            return {'success': True, 'costumes': self.costumes}
        if cmd == 'recompile-csps':
            return self.recompile
        raise AssertionError(f'unexpected MexCLI command: {cmd}')

    @property
    def root(self):
        return self.project_path.parent


# ============= fixtures =============

@pytest.fixture
def env(vault, tmp_path, monkeypatch):
    """Temp vault + temp vanilla assets + faked renderer, wired to a client."""
    vanilla = tmp_path / 'vanilla'
    processor = tmp_path / 'processor'
    vanilla.mkdir()
    processor.mkdir()
    # poses.py and shared.rendering.portrait both bound these at import time
    monkeypatch.setattr(poses, 'VANILLA_ASSETS_DIR', vanilla)
    monkeypatch.setattr(portrait, 'VANILLA_ASSETS_DIR', vanilla)
    monkeypatch.setattr(portrait, 'PROCESSOR_DIR', processor)

    renderer = FakeRenderer()
    monkeypatch.setattr(poses, '_render_pose_csp', renderer.render_pose)
    monkeypatch.setattr(poses, '_render_portrait', renderer.render_default)
    monkeypatch.setattr(poses, 'apply_character_specific_layers', renderer.layers)

    client = vault.client(poses, 'poses_bp')

    def poses_dir(character):
        return vanilla / 'custom_poses' / portrait.pose_character_key(character)

    def write_pose(character, name, text=SYMBOL_POSE, thumb=False):
        d = poses_dir(character)
        d.mkdir(parents=True, exist_ok=True)
        (d / f'{name}.yml').write_text(text, encoding='utf-8')
        if thumb:
            _png(d / f'{name}_thumb.png')
        return d / f'{name}.yml'

    def add_skin(key, skin_id, *, dat_name='PlFxNr.dat', dat=None, **extra):
        """A vault skin zip under storage/<key>/; returns its metadata entry."""
        dat = dat if dat is not None else f'DAT:{key}:{skin_id}'.encode()
        zp = vault.path(*key.split('/'), f'{skin_id}.zip')
        with zipfile.ZipFile(zp, 'w') as zf:
            if dat_name:
                zf.writestr(dat_name, dat)
            else:
                zf.writestr('readme.txt', 'no costume archive in here')
        return {'id': skin_id, 'filename': f'{skin_id}.zip', **extra}

    def add_scene(character):
        p = processor / 'csp_data' / character / 'scene.yml'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(BAKED_SCENE, encoding='utf-8')
        return p

    return SimpleNamespace(client=client, vault=vault, vanilla=vanilla, renderer=renderer,
                           poses_dir=poses_dir, write_pose=write_pose, add_skin=add_skin,
                           add_scene=add_scene, tmp=tmp_path)


@pytest.fixture
def project(env, monkeypatch):
    """An open MEX project (fake MexCLI) the apply-to-costume flow writes into."""
    mex = FakeMex(env.tmp / 'project')
    reloads = []
    monkeypatch.setattr(poses, 'get_mex_manager', lambda: mex)
    monkeypatch.setattr(poses, 'reload_mex_manager', lambda: reloads.append(True))
    mex.reloads = reloads
    return mex


def _post(env, route, body):
    resp = env.client.post(f'{API}/{route}', json=body)
    return resp.status_code, resp.get_json()


def _save(env, character='Fox', name='jump', **scene):
    scene_data = {'animSymbol': 'PlyFox5K_Share_ACTION_Wait1_figatree', 'frame': 12,
                  'camera': {'x': 5, 'y': 11, 'z': -70}, **scene}
    return _post(env, 'save', {'character': character, 'poseName': name, 'sceneData': scene_data})


def _list(env, character='Fox'):
    resp = env.client.get(f'{API}/list/{character}')
    assert resp.status_code == 200
    return resp.get_json()['poses']


# ============= save =============

@pytest.mark.parametrize('missing', ['character', 'poseName', 'sceneData'])
def test_save_rejects_incomplete_request(env, missing):
    """A save without character, name or scene data is refused and writes nothing."""
    body = {'character': 'Fox', 'poseName': 'jump',
            'sceneData': {'animSymbol': 'PlyFox5K_Share_ACTION_Wait1_figatree'}}
    body.pop(missing)
    status, data = _post(env, 'save', body)
    assert status == 400 and data['success'] is False
    assert not (env.vanilla / 'custom_poses').exists()


@pytest.mark.parametrize('symbol', [None, '', 'none', 'NULL', '  None  '])
def test_save_refuses_bind_pose_without_animation(env, symbol):
    """A pose with no animation (would render as a T-pose) is refused for non-scene characters."""
    status, data = _save(env, animSymbol=symbol)
    assert status == 400 and data['success'] is False
    assert _list(env) == []


def test_saved_pose_appears_in_library_with_thumbnail(env):
    """Saving renders a thumbnail from the vanilla base costume and the pose shows up in the library."""
    base = env.vanilla / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'
    base.parent.mkdir(parents=True)
    base.write_bytes(b'VANILLA-FOX')

    status, data = _save(env)
    assert status == 200 and data['success'] is True and data['hasThumbnail'] is True

    (call,) = env.renderer.calls
    assert call['dat'] == b'VANILLA-FOX' and call['character'] == 'Fox'
    assert call['pose'] == 'jump' and call['scale'] == 1
    assert Path(call['aj']) == env.vanilla / 'Fox' / 'PlFxAJ.dat'  # animations come from the AJ archive

    (pose,) = _list(env)
    assert pose['name'] == 'jump' and pose['hasThumbnail'] is True
    thumb = env.client.get(pose['thumbnailUrl'])
    assert thumb.status_code == 200 and thumb.mimetype == 'image/png'
    assert _tag(BytesIO(thumb.data)) == 'VANILLA-FOX@1'


@pytest.mark.parametrize('outcome', ['none', 'raise'])
def test_save_keeps_pose_when_thumbnail_render_fails(env, outcome):
    """A failed or crashing thumbnail render still saves the pose (just without a thumbnail)."""
    base = env.vanilla / 'Fox' / 'PlFxNr' / 'PlFxNr.dat'
    base.parent.mkdir(parents=True)
    base.write_bytes(b'VANILLA-FOX')
    env.renderer.outcome = lambda call: outcome

    status, data = _save(env)
    assert status == 200 and data['success'] is True and data['hasThumbnail'] is False
    (pose,) = _list(env)
    assert pose['name'] == 'jump' and pose['hasThumbnail'] is False and pose['thumbnailUrl'] is None


def test_save_then_start_from_pose_restores_animation_frame_and_camera(env):
    """'Start from existing pose' gives the viewer back the saved animation, frame, camera and hidden parts."""
    status, data = _save(env, frame=12.0, hiddenNodes=[3, 7])
    assert status == 200 and data['success'] is True

    resp = env.client.get(f"{API}/scene-file/Fox/{data['poseName']}")
    assert resp.status_code == 200
    out = resp.get_json()
    assert out['success'] is True
    assert out['animSymbol'] == 'PlyFox5K_Share_ACTION_Wait1_figatree'
    assert out['frame'] == 12

    viewer_scene = portrait.parse_pose_yaml(Path(out['sceneFile']).read_text(encoding='utf-8'))
    assert viewer_scene['camera']['x'] == '5' and viewer_scene['camera']['z'] == '-70'
    assert viewer_scene['hiddenNodes'] == [3, 7]

    # the viewer's scratch scene file is not a pose the user saved
    assert [p['name'] for p in _list(env)] == ['jump']


def test_scene_mode_character_saves_baked_pose_without_animation(env):
    """Scene-mode characters (e.g. DK) can save a pose on their baked animation, and start-from restores it."""
    env.add_scene('DK')
    status, data = _save(env, character='DK', name='baked', animSymbol=None)
    assert status == 200 and data['success'] is True

    out = env.client.get(f'{API}/scene-file/DK/baked').get_json()
    assert out['success'] is True and out['animSymbol'] is None
    merged = Path(out['sceneFile']).read_text(encoding='utf-8')
    assert 'name: baked-scene-pose' in merged       # baked animation carried over
    assert 'x: 5' in merged                          # the pose's own camera applied


@pytest.mark.parametrize('name', ['../../escape', '..\\..\\escape', 'sub/dir', 'C:evil', '..'])
def test_pose_name_cannot_escape_character_library(env, name):
    """A hostile pose name is sanitized into one file inside the character's library, and can be deleted by its returned name."""
    status, data = _save(env, name=name)
    assert status == 200 and data['success'] is True
    safe = data['poseName']
    assert '/' not in safe and '\\' not in safe

    library = env.poses_dir('Fox').resolve()
    for f in env.vanilla.rglob('*'):
        if f.is_file():
            assert library in f.resolve().parents, f'{f} written outside the pose library'
    assert [p['name'] for p in _list(env)] == [safe]

    status, data = _post(env, 'delete', {'character': 'Fox', 'poseName': safe})
    assert status == 200 and data['success'] is True
    assert _list(env) == []


def test_save_rejects_blank_name(env):
    """A name that is blank after trimming is refused instead of creating '.yml'."""
    status, data = _save(env, name='   ')
    assert status == 400 and data['success'] is False
    assert not env.poses_dir('Fox').exists() or not any(env.poses_dir('Fox').iterdir())


# ============= list / thumbnails / scene-file =============

def test_list_is_empty_for_character_without_library(env):
    """A character nobody has posed yet lists no poses (not an error)."""
    assert _list(env, 'Marth') == []


def test_list_is_sorted_and_flags_thumbnails(env):
    """The library lists every pose by name, with a thumbnail URL only where one exists."""
    env.write_pose('Fox', 'zap')
    env.write_pose('Fox', 'aerial', thumb=True)
    env.write_pose('Falco', 'other-character', thumb=True)

    listed = _list(env)
    assert [p['name'] for p in listed] == ['aerial', 'zap']
    assert listed[0]['hasThumbnail'] is True and listed[0]['thumbnailUrl']
    assert listed[1]['hasThumbnail'] is False and listed[1]['thumbnailUrl'] is None


@pytest.mark.parametrize('character', ['Fox', 'custom_characters/sonic/skins'])
def test_listed_thumbnail_url_serves_the_image(env, character):
    """The thumbnail URL the library returns actually serves that pose's PNG."""
    env.write_pose(character, 'spin', thumb=True)
    (pose,) = _list(env, character)
    resp = env.client.get(pose['thumbnailUrl'])
    assert resp.status_code == 200
    assert resp.data == (env.poses_dir(character) / 'spin_thumb.png').read_bytes()


def test_thumbnail_url_changes_when_the_pose_is_saved_again(env):
    """Saving a pose again rewrites the same thumbnail file, so its URL carries a version that changes with it:
    the pose list and Generate CSPs showed the browser's cached old picture (0.9.0 hand-check)."""
    env.write_pose('Fox', 'spin', thumb=True)
    thumb = env.poses_dir('Fox') / 'spin_thumb.png'
    os.utime(thumb, ns=(1_000_000_000, 1_000_000_000))
    (before,) = _list(env)
    assert before['thumbnailUrl'].startswith('/storage/poses/Fox/spin_thumb.png?v=')
    os.utime(thumb, ns=(2_000_000_000, 2_000_000_000))
    (after,) = _list(env)
    assert after['thumbnailUrl'] != before['thumbnailUrl']
    assert env.client.get(after['thumbnailUrl']).data == thumb.read_bytes()


def test_missing_thumbnail_is_404(env):
    """Requesting a thumbnail that does not exist is a clean 404."""
    env.write_pose('Fox', 'jump')
    assert env.client.get('/storage/poses/Fox/jump_thumb.png').status_code == 404


def test_custom_character_skins_and_costumes_share_one_library(env, monkeypatch):
    """A pose saved on a custom character's bundled costume is offered for its added skins too."""
    monkeypatch.setattr(poses, '_character_aj_file', lambda character: None)
    status, data = _save(env, character='custom_characters/sonic/costumes', name='run')
    assert status == 200 and data['success'] is True
    assert [p['name'] for p in _list(env, 'custom_characters/sonic/skins')] == ['run']
    assert _list(env, 'Sonic') == []


def test_scene_file_for_unknown_pose_is_404(env):
    """Starting from a pose that does not exist fails cleanly."""
    resp = env.client.get(f'{API}/scene-file/Fox/ghost')
    assert resp.status_code == 404 and resp.get_json()['success'] is False


def test_scene_pose_without_baked_scene_is_404(env):
    """A baked-scene pose for a character with no baked scene is reported, not half-loaded."""
    env.write_pose('Fox', 'baked', text=SCENE_POSE)
    resp = env.client.get(f'{API}/scene-file/Fox/baked')
    assert resp.status_code == 404 and resp.get_json()['success'] is False


@pytest.mark.parametrize('where', [
    'dotdot',
    # A drive-letter path routes straight into <path:character>. (A POSIX '/abs' would
    # become '//abs', which werkzeug redirects, so this case is Windows-only.)
    pytest.param('absolute', marks=pytest.mark.skipif(
        sys.platform != 'win32', reason='drive-letter absolute URL path is Windows-only')),
])
def test_thumbnail_route_cannot_read_outside_pose_library(env, where):
    """The thumbnail route only serves files from the pose library, never arbitrary files."""
    env.write_pose('Fox', 'jump', thumb=True)
    if where == 'dotdot':
        (env.vanilla / 'secret.png').write_bytes(b'NOT-A-POSE-THUMBNAIL')
        url = '/storage/poses/Fox/../../secret.png'
    else:
        secret = env.tmp / 'elsewhere' / 'secret.png'   # outside the vanilla tree entirely
        secret.parent.mkdir()
        secret.write_bytes(b'NOT-A-POSE-THUMBNAIL')
        url = f'/storage/poses/{secret.parent.as_posix()}/secret.png'   # no '..' anywhere
        assert '..' not in url
    resp = env.client.get(url)
    assert resp.status_code in (400, 403, 404)
    assert b'NOT-A-POSE-THUMBNAIL' not in resp.data


# ============= delete =============

@pytest.mark.parametrize('missing', ['character', 'poseName'])
def test_delete_rejects_incomplete_request(env, missing):
    """Delete without a character or pose name is refused and deletes nothing."""
    env.write_pose('Fox', 'jump')
    body = {'character': 'Fox', 'poseName': 'jump'}
    body.pop(missing)
    status, data = _post(env, 'delete', body)
    assert status == 400 and data['success'] is False
    assert [p['name'] for p in _list(env)] == ['jump']


def test_delete_unknown_pose_is_404(env):
    """Deleting a pose that does not exist reports 404 and leaves the library alone."""
    env.write_pose('Fox', 'jump')
    status, data = _post(env, 'delete', {'character': 'Fox', 'poseName': 'ghost'})
    assert status == 404 and data['success'] is False
    assert [p['name'] for p in _list(env)] == ['jump']


def test_delete_removes_only_that_pose_and_its_thumbnail(env):
    """Deleting a pose removes its file + thumbnail only: other poses, other characters and rendered portraits stay."""
    env.write_pose('Fox', 'jump', thumb=True)
    env.write_pose('Fox', 'jumpy', thumb=True)
    env.write_pose('Falco', 'jump', thumb=True)
    alt = _png(env.vault.path('Fox', 'blue_csp_alt_1.png'))
    meta = env.vault.write({'characters': {'Fox': {'skins': [
        {'id': 'blue', 'filename': 'blue.zip', 'alternate_csps': [
            {'id': 'a1', 'filename': 'blue_csp_alt_1.png', 'pose_name': 'jump', 'is_hd': False}]}]}}})
    alt_bytes = alt.read_bytes()

    status, data = _post(env, 'delete', {'character': 'Fox', 'poseName': 'jump'})
    assert status == 200 and data['success'] is True

    assert not (env.poses_dir('Fox') / 'jump.yml').exists()
    assert not (env.poses_dir('Fox') / 'jump_thumb.png').exists()
    assert [p['name'] for p in _list(env)] == ['jumpy']
    assert [p['name'] for p in _list(env, 'Falco')] == ['jump']
    # portraits already rendered with the pose are the user's art, not library files
    assert alt.read_bytes() == alt_bytes
    assert env.vault.read() == meta


@pytest.mark.parametrize('make_request', [
    pytest.param(lambda victim: ('Fox', '../../Fox/PlFxNr/settings'), id='dotdot-name'),
    pytest.param(lambda victim: ('../Fox/PlFxNr', 'settings'), id='dotdot-character'),
    # absolute paths contain no '..' at all, so a '..'-only fix must not flip these
    pytest.param(lambda victim: ('Fox', str(victim.with_suffix(''))), id='absolute-name'),
    pytest.param(lambda victim: (str(victim.parent), 'settings'), id='absolute-character'),
])
def test_delete_cannot_remove_files_outside_pose_library(env, make_request):
    """Deleting a 'pose' can never remove files outside the pose library (e.g. shipped vanilla assets)."""
    victim = env.vanilla / 'Fox' / 'PlFxNr' / 'settings.yml'
    victim.parent.mkdir(parents=True)
    victim.write_text('shipped asset', encoding='utf-8')
    character, pose_name = make_request(victim)

    status, data = _post(env, 'delete', {'character': character, 'poseName': pose_name})
    assert victim.exists(), 'a file outside the pose library was deleted'
    assert data['success'] is False


# ============= batch-generate-csp (apply a pose to selected vault skins) =============

def _batch(env, **body):
    body = {'character': 'Fox', 'poseName': 'jump', **body}
    return _post(env, 'batch-generate-csp', body)


def _alts(meta, character, skin_id):
    skins = meta['characters'][character]['skins']
    return next(s for s in skins if s['id'] == skin_id).get('alternate_csps', [])


@pytest.mark.parametrize('body', [
    {'character': None},
    {'poseName': None},
    {'skinIds': []},
])
def test_batch_rejects_incomplete_request(env, body):
    """A bulk render without character, pose or skins is refused and renders nothing."""
    env.write_pose('Fox', 'jump')
    meta = env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue')]}}})
    status, data = _batch(env, **{'skinIds': ['blue'], **body})
    assert status == 400 and data['success'] is False
    assert env.renderer.calls == [] and env.vault.read() == meta


def test_batch_unknown_pose_is_404(env):
    """Applying a pose that is not in the library fails before touching any skin."""
    meta = env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue')]}}})
    status, data = _batch(env, poseName='ghost', skinIds=['blue'])
    assert status == 404 and data['success'] is False
    assert env.renderer.calls == [] and env.vault.read() == meta


def test_batch_unknown_character_is_400(env):
    """A character with no animation archive (not vanilla, not custom) is refused."""
    env.write_pose('Nobody', 'jump')
    status, data = _batch(env, character='Nobody', skinIds=['x'])
    assert status == 400 and data['success'] is False
    assert env.renderer.calls == []


def test_batch_without_vault_metadata_is_404(env):
    """With no vault metadata at all, the bulk render reports it instead of crashing."""
    env.write_pose('Fox', 'jump')
    status, data = _batch(env, skinIds=['blue'])
    assert status == 404 and data['success'] is False
    assert env.renderer.calls == []


def test_batch_renders_only_the_selected_skins_of_that_character(env):
    """A bulk apply renders exactly the selected skins; unselected skins and other characters are untouched."""
    env.write_pose('Fox', 'jump')
    fox = [env.add_skin('Fox', sid, dat=f'fox-{sid}'.encode()) for sid in ('a', 'b', 'c')]
    for sid in ('a', 'b', 'c'):
        _png(env.vault.path('Fox', f'{sid}_csp.png'), color=(1, 1, 1, 255))
    falco = env.add_skin('Falco', 'a', dat_name='PlFcNr.dat', dat=b'falco-a')
    env.vault.write({'characters': {'Fox': {'skins': fox}, 'Falco': {'skins': [falco]}}})
    before = _tree(env.vault.storage)

    status, data = _batch(env, skinIds=['a', 'c'])
    assert status == 200 and data['success'] is True
    assert data['generated'] == 2 and data['failed'] == 0
    assert {r['skinId'] for r in data['results'] if r['success']} == {'a', 'c'}

    # renderer only ever saw the selected skins' DATs, HD (4x default) then SD
    assert env.renderer.rendered() == [(b'fox-a', 4), (b'fox-a', 1), (b'fox-c', 4), (b'fox-c', 1)]
    assert env.renderer.layer_calls == [('Fox', 4), ('Fox', 1)] * 2  # Fox gun etc. once per render

    after = _tree(env.vault.storage)
    assert {k: after.get(k) for k in before} == before, 'an existing vault file was modified'
    new = set(after) - set(before)
    assert len(new) == 4 and all(n.startswith(('Fox/a_', 'Fox/c_')) for n in new)

    meta = env.vault.read()
    for sid in ('a', 'c'):
        alts = _alts(meta, 'Fox', sid)
        assert sorted(a['is_hd'] for a in alts) == [False, True]
        for a in alts:
            assert a['pose_name'] == 'jump'
            src = env.vault.storage / 'Fox' / a['filename']
            assert _tag(src) == f"fox-{sid}@{4 if a['is_hd'] else 1}"  # each skin got ITS render
    assert _alts(meta, 'Fox', 'b') == []
    assert _alts(meta, 'Falco', 'a') == []


def test_batch_makes_the_pose_the_portrait_the_skin_shows(env):
    """The pose was picked for that skin: its picture is the one on show from then on, not a spare filed in Portraits."""
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'a'), env.add_skin('Fox', 'b')]}}})

    status, data = _batch(env, skinIds=['a'])
    assert status == 200 and data['generated'] == 1

    a, b = env.vault.read()['characters']['Fox']['skins']
    sd = next(alt for alt in a['alternate_csps'] if not alt['is_hd'])
    assert a['active_csp_id'] == sd['id']
    assert data['results'][0]['altCspPath'] == f"/storage/Fox/{sd['filename']}"
    assert not b.get('active_csp_id')


def test_batch_again_replaces_the_pose_picture_instead_of_adding_a_second(env):
    """One portrait per pose: every reader takes one entry by the pose's name, so a second pair is a picture nobody sees."""
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'a', dat=b'first')]}}})
    assert _batch(env, skinIds=['a'])[1]['generated'] == 1
    first = [(alt['id'], alt['filename']) for alt in _alts(env.vault.read(), 'Fox', 'a')]

    # the costume changed (a texture edit, say) and the pose is taken again
    with zipfile.ZipFile(env.vault.path('Fox', 'a.zip'), 'w') as zf:
        zf.writestr('PlFxNr.dat', b'second')
    status, data = _batch(env, skinIds=['a'])
    assert status == 200 and data['generated'] == 1

    again = _alts(env.vault.read(), 'Fox', 'a')
    assert [(alt['id'], alt['filename']) for alt in again] == first
    for alt in again:
        assert _tag(env.vault.storage / 'Fox' / alt['filename']) == f"second@{4 if alt['is_hd'] else 1}"


@pytest.mark.parametrize('resolution,scales', [
    (None, [4, 1]),
    ('4x', [4, 1]),
    ('2X', [2, 1]),
    ('1x', [1]),
    ('garbage', [4, 1]),
])
def test_batch_hd_resolution_controls_extra_hd_render(env, resolution, scales):
    """'1x' renders only the in-game portrait; anything else also renders an HD copy (4x by default)."""
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue')]}}})
    body = {'skinIds': ['blue']}
    if resolution is not None:
        body['hdResolution'] = resolution
    status, data = _batch(env, **body)
    assert status == 200 and data['generated'] == 1
    assert [s for _, s in env.renderer.rendered()] == scales
    alts = _alts(env.vault.read(), 'Fox', 'blue')
    assert sorted(a['is_hd'] for a in alts) == sorted(s > 1 for s in scales)


def test_batch_reports_unknown_ids_and_folders_without_stopping(env):
    """Unknown skin ids and folder entries are reported as failures while the real skins still render."""
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [
        {'id': 'folder-1', 'type': 'folder', 'name': 'Favourites'},
        env.add_skin('Fox', 'blue'),
    ]}}})
    status, data = _batch(env, skinIds=['ghost', 'folder-1', 'blue'])
    assert status == 200
    assert data['generated'] == 1 and data['failed'] == 2
    by_id = {r['skinId']: r['success'] for r in data['results']}
    assert by_id == {'ghost': False, 'folder-1': False, 'blue': True}


@pytest.mark.parametrize('broken', ['none', 'raise'])
def test_failed_render_leaves_that_skin_untouched_and_others_continue(env, broken):
    """A skin whose render fails or crashes keeps its portraits and metadata exactly; the rest of the batch still renders."""
    env.write_pose('Fox', 'jump')
    old_alt = {'id': 'old', 'filename': 'b_csp_alt_1.png', 'pose_name': 'wave', 'is_hd': False}
    skins = [env.add_skin('Fox', 'a', dat=b'fox-a'),
             env.add_skin('Fox', 'b', dat=b'fox-b', alternate_csps=[old_alt]),
             env.add_skin('Fox', 'c', dat=b'fox-c')]
    _png(env.vault.path('Fox', 'b_csp.png'), color=(9, 9, 9, 255))
    _png(env.vault.path('Fox', 'b_csp_alt_1.png'), color=(8, 8, 8, 255))
    env.vault.write({'characters': {'Fox': {'skins': skins}}})
    before_b = {k: v for k, v in _tree(env.vault.storage).items() if k.startswith('Fox/b')}

    env.renderer.outcome = lambda call: broken if call['dat'] == b'fox-b' else 'ok'
    status, data = _batch(env, skinIds=['a', 'b', 'c'])

    assert status == 200 and data['generated'] == 2 and data['failed'] == 1
    assert {r['skinId']: r['success'] for r in data['results']} == {'a': True, 'b': False, 'c': True}
    after_b = {k: v for k, v in _tree(env.vault.storage).items() if k.startswith('Fox/b')}
    assert after_b == before_b, 'failed skin gained or lost portrait files'
    meta = env.vault.read()
    assert _alts(meta, 'Fox', 'b') == [old_alt]
    assert len(_alts(meta, 'Fox', 'a')) == 2 and len(_alts(meta, 'Fox', 'c')) == 2


def test_partial_render_failure_records_only_portraits_that_exist(env):
    """If the HD render works but the SD one fails, metadata never points at a portrait that was not written."""
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue')]}}})
    env.renderer.outcome = lambda call: 'none' if call['scale'] == 1 else 'ok'

    _batch(env, skinIds=['blue'])

    alts = _alts(env.vault.read(), 'Fox', 'blue')
    assert len(alts) == 1, alts   # only the HD render was written, so only it may be recorded
    for alt in alts:
        assert (env.vault.storage / 'Fox' / alt['filename']).exists(), alt


@pytest.mark.parametrize('zip_kind', ['missing', 'no_costume_dat'])
def test_skin_without_usable_costume_fails_cleanly(env, zip_kind):
    """A skin whose zip is gone or holds no costume DAT is reported failed and gains no portraits."""
    env.write_pose('Fox', 'jump')
    skin = env.add_skin('Fox', 'blue', dat_name=None)
    if zip_kind == 'missing':
        (env.vault.storage / 'Fox' / 'blue.zip').unlink()
    env.vault.write({'characters': {'Fox': {'skins': [skin]}}})

    status, data = _batch(env, skinIds=['blue'])
    assert status == 200 and data['generated'] == 0 and data['failed'] == 1
    assert env.renderer.calls == []
    assert _alts(env.vault.read(), 'Fox', 'blue') == []


def test_default_pose_renders_builtin_portrait_without_a_pose_file(env):
    """The built-in default pose needs no library file and is not layered twice (it renders its own layers)."""
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue', dat=b'fox-blue')]}}})
    status, data = _batch(env, poseName=poses.DEFAULT_POSE_NAME, skinIds=['blue'], hdResolution='1x')
    assert status == 200 and data['generated'] == 1
    assert [c['kind'] for c in env.renderer.calls] == ['default']
    assert env.renderer.layer_calls == []
    (alt,) = _alts(env.vault.read(), 'Fox', 'blue')
    assert alt['pose_name'] == poses.DEFAULT_POSE_LABEL  # how the CSP manager groups it
    assert _tag(env.vault.storage / 'Fox' / alt['filename']) == 'fox-blue@1'


def test_batch_on_custom_character_writes_into_its_own_vault_entry(env, monkeypatch):
    """Custom-character skins get their pose portraits in their own folder and metadata entry."""
    monkeypatch.setattr(poses, '_character_aj_file', lambda character: None)
    key = 'custom_characters/sonic/skins'
    env.write_pose(key, 'jump')
    skin = env.add_skin(key, 'blue', dat=b'sonic-blue')
    env.vault.write({'characters': {'Fox': {'skins': []}},
                     'custom_characters': [{'slug': 'sonic', 'name': 'Sonic', 'added_skins': [skin]}]})

    status, data = _batch(env, character=key, skinIds=['blue'], hdResolution='1x')
    assert status == 200 and data['generated'] == 1
    meta = env.vault.read()
    (alt,) = meta['custom_characters'][0]['added_skins'][0]['alternate_csps']
    assert _tag(env.vault.storage / key / alt['filename']) == 'sonic-blue@1'
    assert meta['characters'] == {'Fox': {'skins': []}}


def test_new_pose_render_never_overwrites_a_surviving_alternate(env):
    """Rendering a new pose never overwrites a portrait the skin already has (e.g. after an older alternate was removed)."""
    env.write_pose('Fox', 'jump')
    # pose 'wave' was rendered as alt #3; alt #1 was later removed in the CSP manager
    survivors = [
        {'id': 'w_hd', 'filename': 'blue_csp_alt_3_hd.png', 'pose_name': 'wave', 'is_hd': True},
        {'id': 'w', 'filename': 'blue_csp_alt_3.png', 'pose_name': 'wave', 'is_hd': False},
    ]
    env.vault.write({'characters': {'Fox': {'skins': [
        env.add_skin('Fox', 'blue', alternate_csps=survivors)]}}})
    wave_sd = _png(env.vault.path('Fox', 'blue_csp_alt_3.png'), color=(7, 7, 7, 255))
    wave_hd = _png(env.vault.path('Fox', 'blue_csp_alt_3_hd.png'), size=(544, 752), color=(7, 7, 7, 255))
    before = (wave_sd.read_bytes(), wave_hd.read_bytes())

    status, data = _batch(env, skinIds=['blue'])
    assert status == 200 and data['generated'] == 1
    assert (wave_sd.read_bytes(), wave_hd.read_bytes()) == before
    files = [a['filename'] for a in _alts(env.vault.read(), 'Fox', 'blue')]
    assert len(files) == len(set(files)), 'two alternates share one portrait file'


# ============= project-costume-map (match installed costumes to vault skins) =============

def _costume(index, file_name, csp=None):
    return {'index': index, 'name': f'costume {index}', 'fileName': file_name,
            'csp': csp or f'csp/{Path(file_name).stem}'}


def _map(env, **body):
    return _post(env, 'project-costume-map', {'fighter': 'Fox', **body})


def test_costume_map_requires_fighter(env, project):
    """Matching costumes without naming a fighter is refused."""
    status, data = _post(env, 'project-costume-map', {'fighter': '  '})
    assert status == 400 and data['success'] is False
    assert project.commands == []


@pytest.mark.parametrize('route,body', [
    ('project-costume-map', {'fighter': 'Fox'}),
    ('apply-to-costume', {'character': 'Fox', 'skinId': 'blue', 'poseName': 'jump', 'cspAsset': 'csp/x'}),
    ('apply-finish', {}),
])
def test_project_routes_fail_cleanly_without_open_project(env, monkeypatch, route, body):
    """With no MEX project open, the install-page pose flow reports an error instead of writing anything."""
    monkeypatch.setattr(core_state, '_current_project_path', None)
    monkeypatch.setattr(core_state, '_mex_manager', None)
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue')]}}})
    before = _tree(env.tmp)

    status, data = _post(env, route, body)
    assert status >= 400 and data['success'] is False
    assert _tree(env.tmp) == before
    assert env.renderer.calls == []


def test_costume_map_matches_by_dat_name_import_suffix_and_vanilla(env, project):
    """Installed costumes map to the vault skin they came from (incl. _NNN import suffix) or to the shipped vanilla costume."""
    env.vault.write({'characters': {'Fox': {'skins': [
        env.add_skin('Fox', 'blue', dat_name='PlFxBu.dat'),
        env.add_skin('Fox', 'red', dat_name='PlFxRe.dat'),
    ]}}})
    van = env.vanilla / 'Fox' / 'PlFxGr' / 'PlFxGr.dat'
    van.parent.mkdir(parents=True)
    van.write_bytes(b'vanilla green')
    project.costumes = [_costume(0, 'PlFxBu.dat'), _costume(1, 'PlFxRe_001.dat'),
                        _costume(2, 'PlFxGr.dat'), _costume(3, 'PlFxZz.dat')]

    status, data = _map(env)
    assert status == 200 and data['success'] is True
    got = [(c['index'], c['skinId'], c['skinCharacter'], c['vanillaCode']) for c in data['costumes']]
    assert got == [(0, 'blue', 'Fox', None), (1, 'red', 'Fox', None),
                   (2, None, 'Fox', 'PlFxGr'), (3, None, None, None)]
    assert [c['cspAsset'] for c in data['costumes']] == [c['csp'] for c in project.costumes]


def test_costume_map_tells_same_named_recolors_apart_by_bytes(env, project):
    """Two vault recolors that both ship PlFxNr.dat are told apart by the installed file's bytes."""
    env.vault.write({'characters': {'Fox': {'skins': [
        env.add_skin('Fox', 'first', dat_name='PlFxNr.dat', dat=b'first recolor'),
        env.add_skin('Fox', 'second', dat_name='PlFxNr.dat', dat=b'second recolor'),
    ]}}})
    (project.root / 'files' / 'PlFxNr.dat').write_bytes(b'second recolor')
    (project.root / 'files' / 'PlFxNr_001.dat').write_bytes(b'first recolor')
    project.costumes = [_costume(0, 'PlFxNr.dat'), _costume(1, 'PlFxNr_001.dat')]

    data = _map(env)[1]
    assert [c['skinId'] for c in data['costumes']] == ['second', 'first']


def test_costume_map_never_matches_another_characters_skins(env, project):
    """Only the fighter's own vault skins are candidates, even if another character holds a same-named DAT."""
    env.vault.write({'characters': {'Fox': {'skins': []}, 'Falco': {'skins': [
        env.add_skin('Falco', 'misfiled', dat_name='PlFxBu.dat')]}}})
    project.costumes = [_costume(0, 'PlFxBu.dat')]
    (costume,) = _map(env)[1]['costumes']
    assert costume['skinId'] is None and costume['skinCharacter'] is None


def test_costume_map_red_falcon_region_resolved_name_uses_vanilla(env, project):
    """Red Falcon's region-resolved 'PlCaRe.' maps to its vanilla costume even though only its portrait ships."""
    _png(env.vanilla / 'C. Falcon' / 'PlCaRe' / 'csp.png')
    project.costumes = [_costume(0, 'PlCaRe.', csp='csp/PlCaRe')]
    env.vault.write({'characters': {'C. Falcon': {'skins': []}}})
    (costume,) = _map(env, fighter='C. Falcon')[1]['costumes']
    assert costume['vanillaCode'] == 'PlCaRe' and costume['skinCharacter'] == 'C. Falcon'


def test_costume_map_custom_character_searches_its_costumes_and_skins(env, project):
    """A custom fighter's installed costumes match its bundled costumes and added skins in the vault."""
    bundled = env.add_skin('custom_characters/sonic/costumes', 'base', dat_name='PlSoNr.dat')
    added = env.add_skin('custom_characters/sonic/skins', 'dark', dat_name='PlSoBk.dat')
    env.vault.write({'characters': {}, 'custom_characters': [
        {'slug': 'sonic', 'name': 'Sonic', 'costume_meta': [bundled], 'added_skins': [added]}]})
    project.costumes = [_costume(0, 'PlSoNr.dat'), _costume(1, 'PlSoBk.dat')]

    got = [(c['skinId'], c['skinCharacter']) for c in _map(env, fighter='Sonic')[1]['costumes']]
    assert got == [('base', 'custom_characters/sonic/costumes'),
                   ('dark', 'custom_characters/sonic/skins')]


# ============= apply-to-costume (overwrite one installed costume's portrait) =============

def _apply(env, **body):
    body = {'character': 'Fox', 'poseName': 'jump', 'cspAsset': 'csp/PlFxBu', **body}
    return _post(env, 'apply-to-costume', body)


def _target(project, asset='csp/PlFxBu'):
    return project.root / 'assets' / f'{asset}.png'


@pytest.fixture
def fox_skin(env, project):
    """Vault Fox skin 'blue' + the project's current portrait for its costume."""
    env.write_pose('Fox', 'jump')
    env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue', dat=b'fox-blue')]}}})
    target = _png(_target(project), color=(50, 50, 50, 255))
    return SimpleNamespace(target=target, original=target.read_bytes())


@pytest.mark.parametrize('body', [
    {'character': None},
    {'poseName': None},
    {'skinId': None, 'vanillaCode': None},
])
def test_apply_rejects_incomplete_request(env, fox_skin, body):
    """Applying without character, pose, or which costume is refused and leaves the portrait alone."""
    status, data = _apply(env, **{'skinId': 'blue', **body})
    assert status == 400 and data['success'] is False
    assert fox_skin.target.read_bytes() == fox_skin.original


def test_apply_without_portrait_asset_is_skipped(env, fox_skin):
    """A costume with no portrait asset is skipped as a success, with nothing rendered."""
    status, data = _apply(env, skinId='blue', cspAsset=None)
    assert status == 200 and data['success'] is True and data['status'] == 'no_csp_asset'
    assert env.renderer.calls == []


@pytest.mark.parametrize('asset', ['../../evil', '../files/PlFxBu', '..\\..\\evil'])
def test_apply_refuses_portrait_path_outside_project_assets(env, fox_skin, project, asset):
    """A portrait path that escapes the project's assets folder is refused before anything renders or is written."""
    before = _tree(env.tmp)
    status, data = _apply(env, skinId='blue', cspAsset=asset)
    assert status == 403 and data['success'] is False
    assert env.renderer.calls == []
    assert _tree(env.tmp) == before


def test_apply_refuses_sibling_folder_sharing_the_assets_prefix(env, fox_skin, project):
    """A portrait path into a sibling folder like 'assets_old' is refused too."""
    _png(env.vault.path('Fox', 'blue_csp.png'))
    status, data = _apply(env, skinId='blue', poseName=poses.ORIGINAL_POSE_NAME,
                          cspAsset='../assets_old/PlFxBu')
    assert status == 403 and data['success'] is False
    assert not (project.root / 'assets_old').exists()


def test_apply_reuses_existing_pose_render_without_rendering(env, fox_skin, project):
    """If the skin already has an SD render of the pose, that exact portrait is installed and nothing re-renders."""
    meta = env.vault.read()
    meta['characters']['Fox']['skins'][0]['alternate_csps'] = [
        {'id': 'h', 'filename': 'blue_csp_alt_1_hd.png', 'pose_name': 'jump', 'is_hd': True},
        {'id': 's', 'filename': 'blue_csp_alt_1.png', 'pose_name': 'jump', 'is_hd': False},
    ]
    env.vault.write(meta)
    _png(env.vault.path('Fox', 'blue_csp_alt_1_hd.png'), size=(544, 752), color=(1, 2, 3, 255))
    _png(env.vault.path('Fox', 'blue_csp_alt_1.png'), color=(4, 5, 6, 255))

    status, data = _apply(env, skinId='blue')
    assert status == 200 and data['success'] is True and data['status'] == 'applied'
    assert env.renderer.calls == []
    assert _pixel_and_size(fox_skin.target) == ((4, 5, 6, 255), SD)
    assert env.vault.read() == meta


def test_apply_renders_missing_pose_and_saves_it_to_the_vault(env, fox_skin):
    """A skin without that pose is rendered now, installed, and kept in the vault as SD+HD alternates."""
    status, data = _apply(env, skinId='blue')
    assert status == 200 and data['success'] is True and data['status'] == 'generated'
    assert env.renderer.rendered() == [(b'fox-blue', 4), (b'fox-blue', 1)]
    assert _pixel_and_size(fox_skin.target) == (_color_for(b'fox-blue'), SD)
    alts = _alts(env.vault.read(), 'Fox', 'blue')
    assert sorted(a['is_hd'] for a in alts) == [False, True]
    assert all(a['pose_name'] == 'jump' for a in alts)
    # posing a project's costume is not a choice about the vault's own picture
    assert not env.vault.read()['characters']['Fox']['skins'][0].get('active_csp_id')


@pytest.mark.parametrize('broken', ['none', 'raise'])
def test_apply_render_failure_keeps_installed_portrait(env, fox_skin, broken):
    """When the render fails, the project's current portrait is left exactly as it was and the vault gains nothing."""
    env.renderer.outcome = lambda call: broken
    status, data = _apply(env, skinId='blue')
    assert status >= 400 and data['success'] is False
    assert fox_skin.target.read_bytes() == fox_skin.original
    assert _alts(env.vault.read(), 'Fox', 'blue') == []


def test_apply_unknown_pose_keeps_installed_portrait(env, fox_skin):
    """Applying a pose that is not in the library is a 404 and changes nothing."""
    status, data = _apply(env, skinId='blue', poseName='ghost')
    assert status == 404 and data['success'] is False
    assert fox_skin.target.read_bytes() == fox_skin.original


def test_apply_skin_from_another_character_is_404(env, fox_skin):
    """A skin id that belongs to a different character is not found, and nothing is written."""
    meta = env.vault.read()
    meta['characters']['Falco'] = {'skins': [env.add_skin('Falco', 'bird', dat_name='PlFcNr.dat')]}
    env.vault.write(meta)
    status, data = _apply(env, skinId='bird')
    assert status == 404 and data['success'] is False
    assert fox_skin.target.read_bytes() == fox_skin.original
    assert env.renderer.calls == []


def test_restore_original_installs_vault_main_portrait_at_vanilla_size(env, fox_skin):
    """'Original' puts back the skin's own main portrait, scaled down to the in-game portrait size."""
    _png(env.vault.path('Fox', 'blue_csp.png'), size=(272, 376), color=(200, 100, 0, 255))
    status, data = _apply(env, skinId='blue', poseName=poses.ORIGINAL_POSE_NAME)
    assert status == 200 and data['success'] is True
    assert env.renderer.calls == []
    assert _pixel_and_size(fox_skin.target) == ((200, 100, 0, 255), SD)


def test_restore_original_without_main_portrait_is_skipped(env, fox_skin):
    """A skin with no main portrait to restore is skipped and its installed portrait left alone."""
    status, data = _apply(env, skinId='blue', poseName=poses.ORIGINAL_POSE_NAME)
    assert status == 200 and data['status'] == 'no_csp_asset'
    assert fox_skin.target.read_bytes() == fox_skin.original


def _vanilla_costume(env, character='Fox', code='PlFxGr', dat=b'vanilla-green', csp=True):
    d = env.vanilla / character / code
    d.mkdir(parents=True, exist_ok=True)
    if dat is not None:
        (d / f'{code}.dat').write_bytes(dat)
    if csp:
        _png(d / 'csp.png', color=(0, 128, 0, 255))
    return d


def test_vanilla_costume_renders_once_then_reuses_cache(env, project):
    """A vanilla costume is rendered from its shipped DAT once; re-applying reuses that render."""
    env.write_pose('Fox', 'jump')
    _vanilla_costume(env)
    target = _target(project, 'csp/PlFxGr')

    status, data = _apply(env, vanillaCode='PlFxGr', cspAsset='csp/PlFxGr')
    assert status == 200 and data['status'] == 'generated'
    assert env.renderer.rendered() == [(b'vanilla-green', 1)]
    assert env.renderer.layer_calls == [('Fox', 1)]
    assert _pixel_and_size(target) == (_color_for(b'vanilla-green'), SD)

    target.unlink()
    status, data = _apply(env, vanillaCode='PlFxGr', cspAsset='csp/PlFxGr')
    assert status == 200 and data['status'] == 'applied'
    assert len(env.renderer.calls) == 1
    assert _pixel_and_size(target) == (_color_for(b'vanilla-green'), SD)


def test_vanilla_restore_original_installs_shipped_portrait(env, project):
    """'Original' on a vanilla costume reinstalls the shipped vanilla portrait."""
    _vanilla_costume(env)
    status, data = _apply(env, vanillaCode='PlFxGr', cspAsset='csp/PlFxGr',
                          poseName=poses.ORIGINAL_POSE_NAME)
    assert status == 200 and data['success'] is True
    assert _pixel_and_size(_target(project, 'csp/PlFxGr')) == ((0, 128, 0, 255), SD)
    assert env.renderer.calls == []


def test_vanilla_code_cannot_reach_another_characters_assets(env, project):
    """A crafted vanilla code cannot make the render read another character's (or any other) DAT."""
    env.write_pose('Fox', 'jump')
    _vanilla_costume(env, character='Falco', code='PlFcNr', dat=b'falco-normal')
    status, data = _apply(env, vanillaCode='../Falco/PlFcNr', cspAsset='csp/PlFxGr')
    assert status == 404 and data['success'] is False
    assert env.renderer.calls == []
    assert not _target(project, 'csp/PlFxGr').exists()


def test_red_falcon_renders_from_the_installed_project_file(env, project):
    """Red Falcon (no shipped model) is rendered from the project's own installed PlCaRe.usd."""
    env.write_pose('C. Falcon', 'jump')
    _vanilla_costume(env, character='C. Falcon', code='PlCaRe', dat=None)
    (project.root / 'files' / 'PlCaRe.usd').write_bytes(b'installed red falcon')

    status, data = _apply(env, character='C. Falcon', vanillaCode='PlCaRe',
                          fileName='PlCaRe.', cspAsset='csp/PlCaRe')
    assert status == 200 and data['status'] == 'generated'
    assert env.renderer.rendered() == [(b'installed red falcon', 1)]


def test_installed_file_fallback_stays_inside_project_files(env, project):
    """The installed-file fallback cannot be pointed at files outside the project's files folder."""
    env.write_pose('C. Falcon', 'jump')
    _vanilla_costume(env, character='C. Falcon', code='PlCaRe', dat=None)
    (project.root.parent / 'outside.dat').write_bytes(b'not a project file')

    status, data = _apply(env, character='C. Falcon', vanillaCode='PlCaRe',
                          fileName='../../outside.dat', cspAsset='csp/PlCaRe')
    assert status == 404 and data['success'] is False
    assert env.renderer.calls == []


# ============= apply-finish =============

def test_finish_recompiles_project_portraits_and_reloads(env, project):
    """Finishing an apply recompiles the open project's portrait textures so the next ISO build uses them."""
    status, data = _post(env, 'apply-finish', {})
    assert status == 200 and data['success'] is True and data['recompiled'] == 3
    assert project.commands == [('recompile-csps', str(project.project_path))]
    assert project.reloads == [True]


def test_finish_reports_recompile_failure(env, project):
    """A failed recompile is reported as a failure, not a silent success."""
    project.recompile = {'success': False, 'error': 'texture encode failed'}
    status, data = _post(env, 'apply-finish', {})
    assert status == 500 and data['success'] is False


# ============= client names never leave the pose library (every route) =============

# A drive-letter path in a URL routes straight into <path:character>; a POSIX
# '/abs' would become '//abs', which werkzeug redirects.
_WINDOWS_URL = pytest.mark.skipif(sys.platform != 'win32',
                                  reason='drive-letter absolute URL path is Windows-only')


@pytest.mark.parametrize('route,make_names', [
    pytest.param('save', lambda v: ('../Fox/PlFxNr', 'stolen'), id='save-dotdot-character'),
    pytest.param('save', lambda v: (str(v.parent), 'stolen'), id='save-absolute-character'),
    pytest.param('list', lambda v: ('../Fox/PlFxNr', None), id='list-dotdot-character'),
    pytest.param('list', lambda v: (str(v.parent), None), id='list-absolute-character',
                 marks=_WINDOWS_URL),
    pytest.param('scene-file', lambda v: ('../Fox/PlFxNr', 'victim'), id='scene-file-dotdot-character'),
    pytest.param('scene-file', lambda v: (str(v.parent), 'victim'), id='scene-file-absolute-character',
                 marks=_WINDOWS_URL),
    pytest.param('scene-file', lambda v: ('Fox', '..\\..\\Fox\\PlFxNr\\victim'), id='scene-file-dotdot-name'),
    pytest.param('batch-generate-csp', lambda v: ('Fox', '../../Fox/PlFxNr/victim'), id='batch-dotdot-name'),
    pytest.param('batch-generate-csp', lambda v: ('Fox', str(v.with_suffix(''))), id='batch-absolute-name'),
    pytest.param('apply-to-costume', lambda v: ('Fox', '../../Fox/PlFxNr/victim'), id='apply-dotdot-name'),
    pytest.param('apply-to-costume', lambda v: ('Fox', str(v.with_suffix(''))), id='apply-absolute-name'),
])
def test_pose_routes_never_use_a_pose_outside_the_library(env, project, route, make_names):
    """No route reads, renders from or writes a 'pose' outside the pose library, whatever character or pose name the client sends."""
    victim = env.vanilla / 'Fox' / 'PlFxNr' / 'victim.yml'   # a pose-shaped file outside the library
    victim.parent.mkdir(parents=True)
    victim.write_text(SYMBOL_POSE.replace('PlyFox5K_Share_ACTION_Wait1_figatree', 'OUTSIDE_LIBRARY'),
                      encoding='utf-8')
    _vanilla_costume(env)   # something for apply-to-costume to render
    meta = env.vault.write({'characters': {'Fox': {'skins': [env.add_skin('Fox', 'blue')]}}})
    before = _tree(env.tmp)
    character, pose_name = make_names(victim)

    url_character = quote(character.replace('\\', '/'), safe='/:')
    if route == 'list':
        resp = env.client.get(f'{API}/list/{url_character}')
    elif route == 'scene-file':
        resp = env.client.get(f"{API}/scene-file/{url_character}/{quote(pose_name, safe='')}")
    else:
        resp = env.client.post(f'{API}/{route}', json={
            'character': character, 'poseName': pose_name, 'skinIds': ['blue'],
            'vanillaCode': 'PlFxGr', 'cspAsset': 'csp/PlFxGr',
            'sceneData': {'animSymbol': 'PlyFox5K_Share_ACTION_Wait1_figatree'}})

    assert resp.status_code in (400, 404) and resp.get_json()['success'] is False
    assert b'OUTSIDE_LIBRARY' not in resp.data and b'victim' not in resp.data
    assert env.renderer.calls == []
    assert _tree(env.tmp) == before and env.vault.read() == meta
