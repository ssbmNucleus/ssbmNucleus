"""
Tests for the "Retake CSP" endpoint (generate-csp): active-portrait resolution
and the apply (save) routing.

The headless render itself needs HSDRawViewer, so the preview render is verified
in-app; here we cover the pure metadata logic and the file/zip/metadata writes
the apply step performs (these mirror the proven update-csp / generate-stock
write paths). Also pins alternate-portrait numbering for the retake and the
CSP manager's add (shared with vault/routes/poses.py).
"""
from tests.paths import BACKEND
import base64
import io
import sys
import zipfile
import uuid
import shutil
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from core import jobs
from shared.rendering import job_previews
import vault.routes.storage_costumes.csp as sc  # the portrait routes (generate-csp, batch retake)


@pytest.fixture
def tmp_path():
    root = Path(__file__).parent / '.tmp-vault-consistency'
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    assert path.parent.resolve() == root.resolve()
    shutil.rmtree(path)


def _client():
    app = Flask(__name__)
    app.register_blueprint(sc.storage_costumes_bp)
    return app.test_client()


def _png_data_uri(w, h, color=(200, 80, 80, 255)):
    img = Image.new('RGBA', (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def _make_costume_zip(path):
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('PlPkBkMod.dat', b'\x00' * 32)  # stand-in costume archive
        zf.writestr('csp.png', b'OLDCSP')


def _patch_meta(monkeypatch, tmp_path, meta):
    monkeypatch.setattr(sc, 'load_metadata', lambda: meta)
    monkeypatch.setattr(sc, 'save_metadata', lambda m: None)
    monkeypatch.setattr(sc, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(sc, 'get_char_data', lambda m, c: m['characters'].get(c))


# ---- _resolve_active_portrait ------------------------------------------------

def test_resolve_default_when_no_active():
    assert sc._resolve_active_portrait({}) == (None, None)
    assert sc._resolve_active_portrait({'active_csp_id': None}) == (None, None)


def test_resolve_alt_pose():
    skin = {'active_csp_id': 'a1', 'alternate_csps': [
        {'id': 'a1', 'filename': 'x_csp_alt_1.png', 'pose_name': 'jump', 'is_hd': False},
        {'id': 'a1_hd', 'filename': 'x_csp_alt_1_hd.png', 'pose_name': 'jump', 'is_hd': True},
    ]}
    alt, pose = sc._resolve_active_portrait(skin)
    assert pose == 'jump'
    assert alt['id'] == 'a1'


def test_resolve_folds_hd_pointer_to_sd_sibling():
    skin = {'active_csp_id': 'a1_hd', 'alternate_csps': [
        {'id': 'a1', 'filename': 'x.png', 'pose_name': 'jump', 'is_hd': False},
        {'id': 'a1_hd', 'filename': 'x_hd.png', 'pose_name': 'jump', 'is_hd': True},
    ]}
    alt, pose = sc._resolve_active_portrait(skin)
    assert alt['id'] == 'a1'  # folded to the SD member
    assert pose == 'jump'


# ---- apply: original/default portrait ----------------------------------------

def test_apply_default_writes_csp_sd_hd_and_metadata(tmp_path, monkeypatch):
    character, skin_id = 'Pikachu', 'plpkbk'
    char_dir = tmp_path / character
    char_dir.mkdir(parents=True)
    zip_path = char_dir / f'{skin_id}.zip'
    _make_costume_zip(zip_path)

    meta = {'characters': {character: {'skins': [{'id': skin_id}]}}}
    _patch_meta(monkeypatch, tmp_path, meta)

    resp = _client().post('/api/mex/storage/costumes/generate-csp', json={
        'character': character, 'skinId': skin_id, 'apply': True,
        'imageData': _png_data_uri(544, 752),
    })
    data = resp.get_json()
    assert resp.status_code == 200 and data['success'] is True
    assert data['hasHd'] is True

    # SD standalone + HD standalone written; zip csp.png replaced; others kept
    assert (char_dir / f'{skin_id}_csp.png').exists()
    assert (char_dir / f'{skin_id}_csp_hd.png').exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.read('csp.png') != b'OLDCSP'
        assert 'PlPkBkMod.dat' in zf.namelist()

    skin = meta['characters'][character]['skins'][0]
    assert skin['has_csp'] and skin['csp_source'] == 'generated'
    assert skin['has_hd_csp'] and skin['hd_csp_source'] == 'generated'


# ---- apply: active pose alternate --------------------------------------------

def test_apply_alt_overwrites_alt_files_in_place(tmp_path, monkeypatch):
    character, skin_id = 'Pikachu', 'plpkbk'
    char_dir = tmp_path / character
    char_dir.mkdir(parents=True)
    _make_costume_zip(char_dir / f'{skin_id}.zip')
    sd_name = f'{skin_id}_csp_alt_1.png'
    hd_name = f'{skin_id}_csp_alt_1_hd.png'
    (char_dir / sd_name).write_bytes(b'OLDSD')
    (char_dir / hd_name).write_bytes(b'OLDHD')

    skin = {'id': skin_id, 'active_csp_id': 'a1', 'alternate_csps': [
        {'id': 'a1', 'filename': sd_name, 'pose_name': 'jump', 'is_hd': False},
        {'id': 'a1_hd', 'filename': hd_name, 'pose_name': 'jump', 'is_hd': True},
    ]}
    meta = {'characters': {character: {'skins': [skin]}}}
    _patch_meta(monkeypatch, tmp_path, meta)

    resp = _client().post('/api/mex/storage/costumes/generate-csp', json={
        'character': character, 'skinId': skin_id, 'apply': True,
        'imageData': _png_data_uri(544, 752),
    })
    data = resp.get_json()
    assert resp.status_code == 200 and data['success'] is True
    assert data['cspUrl'].endswith(sd_name)            # original CSP untouched
    assert not (char_dir / f'{skin_id}_csp.png').exists()
    assert (char_dir / sd_name).read_bytes() != b'OLDSD'   # alt SD overwritten
    assert (char_dir / hd_name).read_bytes() != b'OLDHD'   # alt HD overwritten


# ---- new alternates never overwrite a surviving one --------------------------
#
# Alternate files are <skin>_csp_alt_<N>[_hd]. Once an older alternate has been
# removed in the CSP manager, len(alternate_csps)+1 is a surviving alternate's
# N, so a new file numbered that way overwrote that portrait.

def test_apply_alt_new_hd_never_overwrites_a_surviving_alternate(tmp_path, monkeypatch):
    character, skin_id = 'Pikachu', 'plpkbk'
    char_dir = tmp_path / character
    char_dir.mkdir(parents=True)
    _make_costume_zip(char_dir / f'{skin_id}.zip')
    # active 'jump' (#1) lost its HD; 'wave' (#3) kept only its HD; #2 removed
    jump_sd = f'{skin_id}_csp_alt_1.png'
    wave_hd = f'{skin_id}_csp_alt_3_hd.png'
    (char_dir / jump_sd).write_bytes(b'OLDSD')
    (char_dir / wave_hd).write_bytes(b'WAVE-HD')

    skin = {'id': skin_id, 'active_csp_id': 'j', 'alternate_csps': [
        {'id': 'j', 'filename': jump_sd, 'pose_name': 'jump', 'is_hd': False},
        {'id': 'w_hd', 'filename': wave_hd, 'pose_name': 'wave', 'is_hd': True},
    ]}
    _patch_meta(monkeypatch, tmp_path, {'characters': {character: {'skins': [skin]}}})

    resp = _client().post('/api/mex/storage/costumes/generate-csp', json={
        'character': character, 'skinId': skin_id, 'apply': True,
        'imageData': _png_data_uri(544, 752),
    })
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    assert (char_dir / wave_hd).read_bytes() == b'WAVE-HD'
    files = [a['filename'] for a in skin['alternate_csps']]
    assert len(files) == 3 and len(files) == len(set(files)), 'two alternates share one portrait file'


@pytest.mark.parametrize('form', [{}, {'isHd': 'true'}, {'auto': 'true'}],
                         ids=['sd-upload', 'hd-upload', 'auto-sd-hd-pair'])
def test_csp_manager_add_never_overwrites_a_surviving_alternate(tmp_path, monkeypatch, form):
    character, skin_id = 'Pikachu', 'plpkbk'
    char_dir = tmp_path / character
    char_dir.mkdir(parents=True)
    # 'wave' was added as #3; #1 and #2 were later removed
    survivors = {f'{skin_id}_csp_alt_3.png': b'WAVE-SD', f'{skin_id}_csp_alt_3_hd.png': b'WAVE-HD'}
    for name, data in survivors.items():
        (char_dir / name).write_bytes(data)
    skin = {'id': skin_id, 'alternate_csps': [
        {'id': 'w', 'filename': f'{skin_id}_csp_alt_3.png', 'pose_name': 'wave', 'is_hd': False},
        {'id': 'w_hd', 'filename': f'{skin_id}_csp_alt_3_hd.png', 'pose_name': 'wave', 'is_hd': True},
    ]}
    _patch_meta(monkeypatch, tmp_path, {'characters': {character: {'skins': [skin]}}})

    png = base64.b64decode(_png_data_uri(544, 752).split(',', 1)[1])
    resp = _client().post(f'/api/mex/storage/costumes/{character}/{skin_id}/csp/manage', data={
        'action': 'add', 'file': (io.BytesIO(png), 'pose.png'), **form,
    }, content_type='multipart/form-data')
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    for name, data in survivors.items():
        assert (char_dir / name).read_bytes() == data, f'{name} was overwritten'
    files = [a['filename'] for a in skin['alternate_csps']]
    assert len(files) > 2 and len(files) == len(set(files)), 'two alternates share one portrait file'


# ---- a pose named in the request ---------------------------------------------
#
# The skin's own menu can take the portrait with any of the character's poses.
# The named pose is the one rendered, and applying it makes it the portrait the
# skin shows: a pose picture that is only filed as a spare leaves the old one
# on screen.

GENERATE = '/api/mex/storage/costumes/generate-csp'


def _pose_library(monkeypatch, tmp_path, character, *names):
    root = tmp_path / 'pose-library'
    (root / character).mkdir(parents=True)
    for name in names:
        (root / character / f'{name}.yml').write_text('frame: 0\n', encoding='utf-8')
    monkeypatch.setattr(sc, '_poses_root', lambda: root)
    return root


def _pikachu(tmp_path, monkeypatch, skin):
    char_dir = tmp_path / 'Pikachu'
    char_dir.mkdir(parents=True)
    _make_costume_zip(char_dir / f"{skin['id']}.zip")
    _patch_meta(monkeypatch, tmp_path, {'characters': {'Pikachu': {'skins': [skin]}}})
    _pose_library(monkeypatch, tmp_path, 'Pikachu', 'jump', 'wave')
    return char_dir


def test_apply_named_pose_files_it_and_shows_it(tmp_path, monkeypatch):
    skin = {'id': 'plpkbk'}
    char_dir = _pikachu(tmp_path, monkeypatch, skin)

    resp = _client().post(GENERATE, json={
        'character': 'Pikachu', 'skinId': 'plpkbk', 'apply': True, 'poseName': 'jump',
        'imageData': _png_data_uri(544, 752)})
    data = resp.get_json()
    assert resp.status_code == 200 and data['success'] is True

    alts = skin['alternate_csps']
    assert sorted((a['filename'], a['pose_name'], a['is_hd']) for a in alts) == [
        ('plpkbk_csp_alt_1.png', 'jump', False), ('plpkbk_csp_alt_1_hd.png', 'jump', True)]
    assert all((char_dir / a['filename']).exists() for a in alts)
    sd = next(a for a in alts if not a['is_hd'])
    assert skin['active_csp_id'] == sd['id'] == data['activeCspId']
    # the original portrait is not what was asked for: untouched
    assert not (char_dir / 'plpkbk_csp.png').exists()
    with zipfile.ZipFile(char_dir / 'plpkbk.zip') as zf:
        assert zf.read('csp.png') == b'OLDCSP'


def test_apply_named_pose_replaces_that_poses_picture(tmp_path, monkeypatch):
    """One portrait per pose, also when another portrait is the one showing."""
    skin = {'id': 'plpkbk', 'active_csp_id': 'w', 'alternate_csps': [
        {'id': 'w', 'filename': 'plpkbk_csp_alt_1.png', 'pose_name': 'wave', 'is_hd': False},
        {'id': 'j', 'filename': 'plpkbk_csp_alt_2.png', 'pose_name': 'jump', 'is_hd': False},
        {'id': 'j_hd', 'filename': 'plpkbk_csp_alt_2_hd.png', 'pose_name': 'jump', 'is_hd': True},
    ]}
    char_dir = _pikachu(tmp_path, monkeypatch, skin)
    for a in skin['alternate_csps']:
        (char_dir / a['filename']).write_bytes(b'OLD')

    resp = _client().post(GENERATE, json={
        'character': 'Pikachu', 'skinId': 'plpkbk', 'apply': True, 'poseName': 'jump',
        'imageData': _png_data_uri(544, 752)})
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    assert [a['id'] for a in skin['alternate_csps']] == ['w', 'j', 'j_hd']
    assert (char_dir / 'plpkbk_csp_alt_1.png').read_bytes() == b'OLD'       # 'wave' untouched
    assert (char_dir / 'plpkbk_csp_alt_2.png').read_bytes() != b'OLD'
    assert (char_dir / 'plpkbk_csp_alt_2_hd.png').read_bytes() != b'OLD'
    assert skin['active_csp_id'] == 'j'


def test_apply_default_pose_by_name_shows_the_original_again(tmp_path, monkeypatch):
    skin = {'id': 'plpkbk', 'active_csp_id': 'j', 'alternate_csps': [
        {'id': 'j', 'filename': 'plpkbk_csp_alt_1.png', 'pose_name': 'jump', 'is_hd': False}]}
    char_dir = _pikachu(tmp_path, monkeypatch, skin)
    (char_dir / 'plpkbk_csp_alt_1.png').write_bytes(b'JUMP')

    resp = _client().post(GENERATE, json={
        'character': 'Pikachu', 'skinId': 'plpkbk', 'apply': True, 'poseName': None,
        'imageData': _png_data_uri(544, 752)})
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    assert (char_dir / 'plpkbk_csp.png').exists()
    assert (char_dir / 'plpkbk_csp_alt_1.png').read_bytes() == b'JUMP'      # kept as a spare
    assert skin['active_csp_id'] is None


@pytest.mark.parametrize('pose,status', [('ghost', 404), ('../Fox/jump', 400)])
def test_named_pose_must_be_one_of_the_characters_own(tmp_path, monkeypatch, pose, status):
    skin = {'id': 'plpkbk'}
    char_dir = _pikachu(tmp_path, monkeypatch, skin)
    (tmp_path / 'pose-library' / 'Fox').mkdir()
    (tmp_path / 'pose-library' / 'Fox' / 'jump.yml').write_text('frame: 0\n', encoding='utf-8')
    monkeypatch.setattr(sc, '_render_costume_preview',
                        lambda *a, **k: pytest.fail('rendered a pose that is not the character\'s'))

    for extra in ({}, {'apply': True, 'imageData': _png_data_uri(544, 752)}):
        resp = _client().post(GENERATE, json={
            'character': 'Pikachu', 'skinId': 'plpkbk', 'poseName': pose, **extra})
        assert resp.status_code == status and resp.get_json()['success'] is False
    assert 'alternate_csps' not in skin and 'active_csp_id' not in skin
    assert sorted(p.name for p in char_dir.iterdir()) == ['plpkbk.zip']


def test_preview_takes_the_named_pose_not_the_one_showing(tmp_path, monkeypatch):
    skin = {'id': 'plpkbk', 'active_csp_id': 'w', 'alternate_csps': [
        {'id': 'w', 'filename': 'plpkbk_csp_alt_1.png', 'pose_name': 'wave', 'is_hd': False}]}
    _pikachu(tmp_path, monkeypatch, skin)
    monkeypatch.setattr(sc, '_paired_nana_zip', lambda *a, **k: None)
    asked = []

    def render(character, zip_path, pose_name, nana_zip_path=None):
        asked.append(pose_name)
        return b'PNG', (pose_name or 'Default')
    monkeypatch.setattr(sc, '_render_costume_preview', render)

    for pose, label in (('jump', 'jump'), (None, 'Default')):
        resp = _client().post(GENERATE, json={
            'character': 'Pikachu', 'skinId': 'plpkbk', 'poseName': pose})
        data = resp.get_json()
        assert resp.status_code == 200 and data['poseName'] == label
    # with no pose named, the retake is of what is showing
    _client().post(GENERATE, json={'character': 'Pikachu', 'skinId': 'plpkbk'})
    assert asked == ['jump', None, 'wave']
    assert skin['active_csp_id'] == 'w'                                    # a preview writes nothing


def test_preview_of_a_named_pose_never_answers_with_the_default(tmp_path, monkeypatch):
    """The renderer falls back to the default pose when a pose is lost; a pose
    asked for by name must fail instead of handing back a picture of another."""
    skin = {'id': 'plpkbk'}
    _pikachu(tmp_path, monkeypatch, skin)
    monkeypatch.setattr(sc, '_paired_nana_zip', lambda *a, **k: None)
    monkeypatch.setattr(sc, '_render_costume_preview', lambda *a, **k: (b'PNG', 'Default'))

    resp = _client().post(GENERATE, json={
        'character': 'Pikachu', 'skinId': 'plpkbk', 'poseName': 'jump'})
    data = resp.get_json()
    assert resp.status_code == 500 and data['success'] is False and 'jump' in data['error']
    assert 'dataUri' not in data


# ---- guards ------------------------------------------------------------------

def test_missing_params_400(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, 'STORAGE_PATH', tmp_path)
    resp = _client().post('/api/mex/storage/costumes/generate-csp',
                          json={'character': 'Pikachu'})
    assert resp.status_code == 400


def test_missing_zip_404(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, 'STORAGE_PATH', tmp_path)
    (tmp_path / 'Pikachu').mkdir()
    resp = _client().post('/api/mex/storage/costumes/generate-csp',
                          json={'character': 'Pikachu', 'skinId': 'nope'})
    assert resp.status_code == 404


# ---- batch-retake-csp (vault-wide) --------------------------------------------
#
# The worker thread is run synchronously (Thread stub), the render is mocked, and
# socket.io emits are recorded, so these cover the request-shape handling, the
# per-item character routing and the event payloads -- not the render itself.

class _SyncThread:
    """threading.Thread stand-in: start() runs the target on the calling thread."""
    def __init__(self, target=None, daemon=None, **kw):
        self._target = target
        self._args = kw.get('args', ())

    def start(self):
        self._target(*self._args)


class _Recorder:
    def __init__(self):
        self.events = []

    def emit(self, name, payload):
        self.events.append((name, payload))


import contextlib


@contextlib.contextmanager
def _noop_pool(*a, **kw):
    yield None


def _patch_batch(monkeypatch, tmp_path, meta, render=None):
    import core.state as core_state
    import shared.rendering.csp_pool as csp_pool
    _patch_meta(monkeypatch, tmp_path, meta)
    rec = _Recorder()
    monkeypatch.setattr(core_state, 'get_socketio', lambda: rec)
    monkeypatch.setattr(csp_pool, 'active_pool', _noop_pool)
    monkeypatch.setattr(jobs.threading, 'Thread', _SyncThread)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(job_previews, 'OUTPUT_PATH', tmp_path)
    monkeypatch.setattr(sc, '_paired_nana_zip', lambda meta, skin: None)
    monkeypatch.setattr(sc, '_render_costume_preview',
                        render or (lambda character, zip_path, pose_name, nana_zip_path=None, **kw:
                                   (b'PNGBYTES-' + character.encode(), 'Default')))
    return rec


def _two_char_vault(tmp_path):
    for character, skin_id in (('Fox', 'fox1'), ('Marth', 'marth1')):
        d = tmp_path / character
        d.mkdir()
        _make_costume_zip(d / f'{skin_id}.zip')
    return {'characters': {
        'Fox': {'skins': [{'id': 'fox1', 'name': 'Blue'}]},
        'Marth': {'skins': [{'id': 'marth1', 'name': 'Red'}]},
    }}


def test_batch_items_span_characters(tmp_path, monkeypatch):
    rec = _patch_batch(monkeypatch, tmp_path, _two_char_vault(tmp_path))
    resp = _client().post('/api/mex/storage/costumes/batch-retake-csp', json={
        'items': [{'character': 'Fox', 'skinId': 'fox1'},
                  {'character': 'Marth', 'skinId': 'marth1'}]})
    assert resp.status_code == 200
    assert resp.get_json()['count'] == 2
    assert jobs.active_job(sc.RETAKE_KIND) is None

    items = rec.events[-1][1]['result']['items']
    assert [(p['character'], p['skinId'], p['done'], p['total']) for p in items] == [
        ('Fox', 'fox1', 1, 2), ('Marth', 'marth1', 2, 2)]
    assert all(p['ok'] and p['previewUrl'].endswith('.png') for p in items)
    # each item was rendered for ITS character (zip resolved per character)
    assert _preview_bytes(items[0]) == b'PNGBYTES-Fox'
    assert _preview_bytes(items[1]) == b'PNGBYTES-Marth'
    assert rec.events[-1][0] == 'job'
    assert rec.events[-1][1]['status'] == 'done'
    assert rec.events[-1][1]['result'] == {'total': 2, 'rendered': 2, 'items': items}


def test_batch_legacy_single_character_shape(tmp_path, monkeypatch):
    rec = _patch_batch(monkeypatch, tmp_path, _two_char_vault(tmp_path))
    resp = _client().post('/api/mex/storage/costumes/batch-retake-csp', json={
        'character': 'Marth', 'skinIds': ['marth1']})
    assert resp.status_code == 200
    items = rec.events[-1][1]['result']['items']
    assert [(p['character'], p['skinId']) for p in items] == [('Marth', 'marth1')]
    assert rec.events[-1][0] == 'job'
    assert rec.events[-1][1]['status'] == 'done'
    assert rec.events[-1][1]['result'] == {'total': 1, 'rendered': 1, 'items': items}


def test_batch_unknown_skin_is_reported_not_fatal(tmp_path, monkeypatch):
    rec = _patch_batch(monkeypatch, tmp_path, _two_char_vault(tmp_path))
    resp = _client().post('/api/mex/storage/costumes/batch-retake-csp', json={
        'items': [{'character': 'Fox', 'skinId': 'nope'},
                  {'character': 'Fox', 'skinId': 'fox1'}]})
    assert resp.status_code == 200
    items = rec.events[-1][1]['result']['items']
    assert items[0]['ok'] is False and 'not found' in items[0]['error'].lower()
    assert items[1]['ok'] is True
    assert rec.events[-1][0] == 'job'
    assert rec.events[-1][1]['status'] == 'done'
    assert rec.events[-1][1]['result'] == {'total': 2, 'rendered': 1, 'items': items}


def test_batch_empty_body_400(tmp_path, monkeypatch):
    _patch_batch(monkeypatch, tmp_path, {'characters': {}})
    c = _client()
    assert c.post('/api/mex/storage/costumes/batch-retake-csp', json={}).status_code == 400
    assert c.post('/api/mex/storage/costumes/batch-retake-csp',
                  json={'items': []}).status_code == 400
    assert c.post('/api/mex/storage/costumes/batch-retake-csp',
                  json={'character': 'Fox'}).status_code == 400


def test_batch_409_while_running(tmp_path, monkeypatch):
    _patch_batch(monkeypatch, tmp_path, _two_char_vault(tmp_path))
    active = jobs.Job(sc.RETAKE_KIND)
    jobs._jobs[active.id] = active
    resp = _client().post('/api/mex/storage/costumes/batch-retake-csp', json={
        'items': [{'character': 'Fox', 'skinId': 'fox1'}]})
    assert resp.status_code == 409
    assert resp.json['job_id'] == active.id


def _preview_bytes(item):
    response = _client().get(item['previewUrl'])
    try:
        assert response.status_code == 200
        return response.data
    finally:
        response.close()


def test_retake_recovery_removes_extraction_and_preview_files(tmp_path, monkeypatch):
    _patch_batch(monkeypatch, tmp_path, {'characters': {}})
    job = jobs.Job(sc.RETAKE_KIND, job_id='dead-retake')
    work = job_previews.prepare_previews(job)
    (work / 'costume.dat').write_bytes(b'partial')
    (work / '0.png').write_bytes(b'preview')
    record = job.snapshot()
    record.update(status='running', owner=None)
    jobs._write(record)
    [recovered] = jobs.recover_interrupted()
    assert recovered['status'] == 'interrupted' and recovered['owned'] == {}
    assert not work.exists()


def test_retake_cancel_stops_before_next_costume_and_cleans(tmp_path, monkeypatch):
    called = []
    def render(character, *args, **kwargs):
        called.append(character)
        jobs.cancel(jobs.active_job(sc.RETAKE_KIND).id)
        return b'preview', 'Default'
    rec = _patch_batch(monkeypatch, tmp_path, _two_char_vault(tmp_path), render)
    response = _client().post('/api/mex/storage/costumes/batch-retake-csp', json={
        'items': [{'character': 'Fox', 'skinId': 'fox1'}, {'character': 'Marth', 'skinId': 'marth1'}]})
    assert jobs.get(response.json['job_id'])['status'] == 'cancelled'
    assert called == ['Fox']
    assert not job_previews.preview_dir(response.json['job_id']).exists()


def test_retake_previews_survive_resync_and_delete_after_review(tmp_path, monkeypatch):
    _patch_batch(monkeypatch, tmp_path, _two_char_vault(tmp_path))
    client = _client()
    response = client.post('/api/mex/storage/costumes/batch-retake-csp', json={
        'items': [{'character': 'Fox', 'skinId': 'fox1'}]})
    job_id = response.json['job_id']
    jobs._jobs.clear()
    record = jobs.get(job_id)
    assert record['status'] == 'done'
    assert _preview_bytes(record['result']['items'][0]) == b'PNGBYTES-Fox'
    assert 'dataUri' not in str(record)
    assert client.delete(f'/api/mex/storage/costumes/batch-retake-csp/{job_id}').status_code == 200
    assert not job_previews.preview_dir(job_id).exists()
