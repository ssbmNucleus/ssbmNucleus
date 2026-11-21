"""projects/routes/project.py -- /project/strip ("Free space") and /project/disc-usage.

As of 0.8.11 Free space stubs vanilla movies instead of deleting them (deleting
crashes the build after every 1P clear, on the title attract loop, and in
Data -> Movies; Tracker #92). These tests exercise the Flask routes end-to-end
against a fake project directory, checking the HTTP contract and that an added
fighter's own movie is never touched.
"""
from tests.paths import BACKEND
import struct
import sys
from pathlib import Path

from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from projects.routes.project import project_bp
from core import movie_stubs


def _frame(payload, next_size):
    body = struct.pack('>I', next_size) + payload
    pad = (-len(body)) % movie_stubs._FRAME_ALIGN
    return body + b'\x00' * pad


def _make_mth(num_frames, payload=b'JPEGDATA'):
    frame_bytes = _frame(payload, 0)
    frame_size = len(frame_bytes)
    frames = b''.join(_frame(payload, frame_size) for _ in range(num_frames))
    header = bytearray(movie_stubs.HEADER_SIZE)
    header[:4] = movie_stubs.MTH_MAGIC
    struct.pack_into('>10I', header, 4,
                      0x80000, 2, frame_size, 640, 480, 30, num_frames,
                      movie_stubs.HEADER_SIZE, 0, frame_size)
    return bytes(header) + frames


def _client():
    app = Flask(__name__)
    app.register_blueprint(project_bp)
    return app.test_client()


def _open_project(tmp_path, open_project):
    project_dir = tmp_path / 'MyProject'
    files_dir = project_dir / 'files'
    files_dir.mkdir(parents=True)
    open_project(project_dir / 'MyProject.mexproj')
    return files_dir


def test_strip_stubs_vanilla_movies_and_spares_added_fighters(tmp_path, open_project):
    files_dir = _open_project(tmp_path, open_project)
    (files_dir / 'MvEndMario.mth').write_bytes(_make_mth(200))
    added_fighter_movie = _make_mth(200, payload=b'WOLFDATA')
    (files_dir / 'MvEndWolf.mth').write_bytes(added_fighter_movie)

    resp = _client().post('/api/mex/project/strip', json={'targets': ['video']})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    assert body['stubbed'] == ['MvEndMario.mth']
    assert body['freedBytes'] > 0
    # Never touches a file that isn't one of the 28 vanilla movie names, even
    # though it also starts with "Mv" and ends ".mth".
    assert (files_dir / 'MvEndWolf.mth').read_bytes() == added_fighter_movie

    stubbed = (files_dir / 'MvEndMario.mth').read_bytes()
    info = movie_stubs.parse_header(stubbed[:movie_stubs.HEADER_SIZE])
    assert info['isStub'] is True


def test_strip_is_idempotent_over_http(tmp_path, open_project):
    files_dir = _open_project(tmp_path, open_project)
    (files_dir / 'MvEndMario.mth').write_bytes(_make_mth(200))
    client = _client()

    first = client.post('/api/mex/project/strip', json={'targets': ['video']}).get_json()
    assert first['stubbed'] == ['MvEndMario.mth']

    second = client.post('/api/mex/project/strip', json={'targets': ['video']}).get_json()
    assert second['stubbed'] == []
    assert second['freedBytes'] == 0


def test_strip_rejects_unknown_targets(tmp_path, open_project):
    _open_project(tmp_path, open_project)
    resp = _client().post('/api/mex/project/strip', json={'targets': ['trophies']})
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


def test_disc_usage_reports_reclaimable_video_smaller_than_full_breakdown(tmp_path, open_project):
    files_dir = _open_project(tmp_path, open_project)
    (files_dir / 'MvEndMario.mth').write_bytes(_make_mth(200))
    (files_dir / 'MvEndWolf.mth').write_bytes(_make_mth(200, payload=b'WOLFDATA'))

    resp = _client().get('/api/mex/project/disc-usage')
    body = resp.get_json()

    assert resp.status_code == 200
    assert body['success'] is True
    # breakdown['video'] counts both mv* files; reclaimable.video only what
    # strip would actually free (the vanilla one, minus its stub size) --
    # Wolf's own movie isn't a strip target, so it isn't reclaimable.
    assert body['breakdown']['video'] > body['reclaimable']['video'] > 0
