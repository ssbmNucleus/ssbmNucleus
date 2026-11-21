"""What the data folder's scratch keeps after a run: the 3D viewer's folders (shared/routes/viewer.py) and a model
import's temp files (randall/model_import/chat/rigswap_temp.py, import_job.rigswap).

0.9.0 build 4 smoke (macOS): quitting with the 3D viewer open left its ``viewer_<8>`` folder, and a restart did not
clear it; every cancelled model import left Blender's session folder, rigswap's Blender script and ``tmpctx*``
folders. The scratch is every feature's temp folder, so the sweeps match exact shapes and keep everything else.
"""
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from randall.model_import.chat import import_job, rigswap_temp
from shared.routes import viewer as viewer_routes


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """The data scratch: tempfile's folder, as core/config.py makes it in the app."""
    folder = tmp_path / 'scratch'
    folder.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(folder))
    return folder


def _names(folder):
    return sorted(entry.name for entry in folder.iterdir())


def _costume_zip(path):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('PlFxNrMod.dat', b'HSD costume stand-in')
    return path


# ------------------------------------------------------------------ the 3D viewer's folders

def test_the_start_sweeps_the_viewer_folders_an_earlier_run_left_and_keeps_a_live_viewers(scratch, tmp_path,
                                                                                        monkeypatch):
    monkeypatch.setattr(viewer_routes, '_made', set())
    # an earlier run's: the costume viewer's folder the build 4 smoke found, a vault editor's, a workbench copy
    earlier = ['viewer_w_0czxgc', 'viewer_vault_k2j4h6g8', 'viewer_checkpoint_e4rl1er8']
    for name in earlier:
        (scratch / name).mkdir()
        (scratch / name / 'PlFxNrMod.dat').write_bytes(b'x')
    # other features' and the user's scratch entries, some of them close to a viewer folder's shape
    unrelated = ['viewer_notes', 'viewer_toolong12', 'hdcsp_xzg17bko', 'tmpabcdefgh', 'nucleus-import-asks-k3j2h1g0']
    for name in unrelated:
        (scratch / name).mkdir()
    (scratch / 'viewer_settings.json').write_text('{}', encoding='utf-8')
    # this run's live viewers: one the vault editor's route opened, one a costume viewer opened
    storage = tmp_path / 'storage'
    (storage / 'Fox').mkdir(parents=True)
    _costume_zip(storage / 'Fox' / 'skin-1.zip')
    monkeypatch.setattr(viewer_routes, 'STORAGE_PATH', storage)
    for name in ('find_scene_file', 'find_aj_file', 'find_fighter_data_file'):
        monkeypatch.setattr(viewer_routes, name, lambda _: None)
    app = Flask(__name__)
    app.register_blueprint(viewer_routes.viewer_bp)
    opened = app.test_client().post('/api/mex/viewer/paths-vault', json={'character': 'Fox', 'costumeId': 'skin-1'})
    assert opened.status_code == 200, opened.json
    vault_live = Path(opened.json['tempDir'])
    costume_live, dat = viewer_routes.extract_costume_archive(storage / 'Fox' / 'skin-1.zip',
                                                              viewer_routes.VIEWER_PREFIX)
    assert vault_live.parent == costume_live.parent == scratch and dat.is_file()
    assert vault_live.name.startswith('viewer_vault_') and len(costume_live.name) == len('viewer_') + 8

    assert viewer_routes.sweep_viewer_folders() == len(earlier)
    assert _names(scratch) == sorted(unrelated + ['viewer_settings.json', vault_live.name, costume_live.name]), \
        "an earlier run's folders went; this run's live viewers' and everything else stayed"
    assert dat.read_bytes() == b'HSD costume stand-in'
    # The app closes: this backend's own folders go with it (the shutdown route, cleanup_on_exit).
    viewer_routes.remove_own_viewer_folders()
    assert _names(scratch) == sorted(unrelated + ['viewer_settings.json'])


# ------------------------------------------------------------------ the model import's temp files

def test_the_start_sweeps_model_import_leftovers_by_exact_shape_only(scratch):
    # Gone: a run folder a dead backend left, Blender's empty session folders (macOS/Linux and Windows names),
    # rigswap's Blender script, a tmpctx folder.
    (scratch / 'rigswap-tmp-ab12cd34' / 'blender_ab12cd').mkdir(parents=True)
    (scratch / 'rigswap-tmp-ab12cd34' / 'tmpq1w2e3r4.py').write_text('import bpy\n', encoding='utf-8')
    (scratch / 'blender_Qx7pLm').mkdir()
    (scratch / 'blender_a01234').mkdir()
    (scratch / 'tmpab12cd34.py').write_text('\nimport bpy, math, os, re, sys\nfrom mathutils import Matrix\n',
                                            encoding='utf-8')
    (scratch / 'tmpctxq1w2e3').mkdir()
    (scratch / 'tmpctxq1w2e3' / 'context.bin').write_bytes(b'x')
    gone = ['rigswap-tmp-ab12cd34', 'blender_Qx7pLm', 'blender_a01234', 'tmpab12cd34.py', 'tmpctxq1w2e3']
    # Kept: this run's live import, a Blender session folder still holding files, a tmp*.py that is not a Blender
    # script, and other features' temp files of the plain tmp* shape, with the rest of the scratch.
    live = rigswap_temp.make()
    (live / 'blender_zz99yy').mkdir()
    (scratch / 'blender_a05678').mkdir()
    (scratch / 'blender_a05678' / 'quit.blend').write_bytes(b'x')
    (scratch / 'tmpzz99yy88.py').write_text("print('not Blender')\n", encoding='utf-8')
    (scratch / 'tmpabcdefgh').mkdir()
    (scratch / 'tmpabcdefgh.dat').write_bytes(b'x')
    (scratch / 'blender_serve.log').write_text('log', encoding='utf-8')
    for name in ('hdcsp_x8e8witv', 'nucleus-import-asks-k3j2h1g0', 'viewer_w_0czxgc', 'rigswap-tmp-notours'):
        (scratch / name).mkdir()
    kept = sorted(set(_names(scratch)) - set(gone))

    assert live.parent == scratch and live.name.startswith(rigswap_temp.PREFIX)
    assert rigswap_temp.sweep(scratch) == len(gone)
    assert _names(scratch) == kept and (live / 'blender_zz99yy').is_dir()
    assert rigswap_temp.remove(live) and not live.exists()


# A stand-in for rigswap's costume entry point: what its tools leave in the temp folder while they run (Blender's
# session folder, rigswap's Blender script), the temp folder it was given to seen.json, then done, or (hang) it
# waits to be stopped.
FAKE_COSTUME = r'''
import json, os, sys, tempfile, time
from pathlib import Path
args = sys.argv[1:]
download, fighter, out = args[0], args[1], Path(args[2])
out.mkdir(parents=True, exist_ok=True)
temp = Path(tempfile.gettempdir())
(temp / 'blender_ab12cd').mkdir()
handle, script = tempfile.mkstemp(suffix='.py')
os.write(handle, b'import bpy\n')
os.close(handle)
seen = {name: os.environ.get(name) for name in ('TMPDIR', 'TEMP', 'TMP')}
(out / 'seen.json').write_text(json.dumps(dict(seen, gettempdir=str(temp))), encoding='utf-8')
print(f'loading {Path(download).name}', flush=True)
if os.environ.get('FAKE_RIGSWAP') == 'hang':
    time.sleep(120)
dat = out / f'{fighter}.dat'
dat.write_bytes(b'HSD costume stand-in')
(out / 'result.json').write_text(json.dumps(dict(status='done', fighter=fighter, dat=str(dat), seconds=1.0,
                                                 cost_usd=0.0)), encoding='utf-8')
'''


@pytest.fixture
def fake_rigswap(tmp_path, monkeypatch):
    home = tmp_path / 'rigswap-home'
    package = home / 'rigswap' / 'plugins' / 'melee'
    package.mkdir(parents=True)
    for folder in (home / 'rigswap', home / 'rigswap' / 'plugins', package):
        (folder / '__init__.py').write_text('', encoding='utf-8')
    (package / 'costume.py').write_text(FAKE_COSTUME, encoding='utf-8')
    monkeypatch.setenv(import_job.PYTHON_ENV, sys.executable)
    monkeypatch.setenv(import_job.HOME_ENV, str(home))
    monkeypatch.setenv(import_job.FILES_ENV, str(tmp_path / 'vanilla'))
    monkeypatch.delenv(import_job.CACHE_ENV, raising=False)
    monkeypatch.setenv('FAKE_RIGSWAP', 'done')
    return home


def _seen_temp(out, scratch):
    """The temp folder the run was given: TMPDIR, TEMP and TMP all name it, a run folder of its own in the scratch."""
    seen = json.loads((out / 'seen.json').read_text(encoding='utf-8'))
    temp = Path(seen['TMPDIR'])
    assert seen['TEMP'] == seen['TMP'] == seen['TMPDIR'] and Path(seen['gettempdir']) == temp
    assert temp.parent == scratch and temp.name.startswith(rigswap_temp.PREFIX)
    return temp


def test_each_rigswap_run_has_a_temp_folder_of_its_own_removed_when_it_is_done(scratch, fake_rigswap, tmp_path):
    out = tmp_path / 'imports' / 'neos-1' / import_job.OUT
    result = import_job.rigswap(sys.executable, fake_rigswap, tmp_path / 'neos.zip', 'Marth', out,
                                cache=tmp_path / 'cache', log=lambda _: None)
    assert result['status'] == 'done', result
    temp = _seen_temp(out, scratch)
    assert not temp.exists() and _names(scratch) == [], 'the run folder went, and nothing was left in the scratch'
    assert Path(result['dat']).is_file(), "rigswap's output is the project's, not the temp folder's"
    assert temp.name not in rigswap_temp._live, 'no longer live once the run has ended'


def test_a_cancelled_import_removes_its_temp_folder_and_keeps_its_project(scratch, fake_rigswap, tmp_path,
                                                                         monkeypatch):
    monkeypatch.setenv('FAKE_RIGSWAP', 'hang')
    root = tmp_path / 'imports'
    source = tmp_path / 'neos.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('model.obj', 'v 0 0 0\n')
    started = time.monotonic()

    def cancelled():                # the user's Stop, once rigswap's tools have left their temp files
        return any(root.glob(f'*/{import_job.OUT}/seen.json')) or time.monotonic() - started > 20

    reply = import_job.start(source, fighter='Marth', root=root, cancelled=cancelled)
    assert reply['status'] == 'cancelled' and reply['saved'] is None, reply
    assert time.monotonic() - started < 30, 'ended by the Stop, not by the timeout'
    project = root / reply['project']
    temp = _seen_temp(project / import_job.OUT, scratch)
    assert not temp.exists() and _names(scratch) == [], "a stopped run's temp files went with its folder"
    log = (project / 'workflow' / import_job.LOG).read_text(encoding='utf-8')
    assert 'stopped by the user' in log and (project / 'workflow' / import_job.JOB).is_file(), \
        'the project folder (its job and log) is a record and stays'
