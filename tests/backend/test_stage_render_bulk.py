"""The vault's BULK stage-screenshot flow
(/api/mex/storage/stages/render-screenshots).

Previews are rendered OFFLINE from each variant's vault zip through the CSP
render host -- no test ISO build and no Dolphin boot. These pin the parts a
user notices when they go wrong:

  * every selected variant reports exactly once, with its image or a reason;
  * Stadium renders its NORMAL root model, never a GrPs1..4 transformation;
  * one bad variant (missing zip, renderer failure, half-written PNG) never
    stops the batch;
  * stages with no calibrated camera are refused instead of being drawn from
    an arbitrary viewpoint;
  * Stop abandons what has not started; a second batch is refused.

The native renderer is faked; this exercises the orchestration + zip handling.
"""
from tests.paths import BACKEND
import base64
import io
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from core import jobs, state
from shared.rendering import job_previews
from vault.routes import das, storage_stages          # noqa: E402
from vault.importing import stage_previews         # noqa: E402


class FakePool:
    """Stands in for CspRenderPool: records the argv it was handed and writes
    a PNG of the right size unless the variant is told to fail."""
    calls = []
    rendered = []         # the stage bytes handed to each render (temp dir is
                          # gone by the time a test can look)
    fail = set()          # stage bytes whose render returns False
    corrupt = set()       # stage bytes that "succeed" with a half-written PNG

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def render(self, args):
        FakePool.calls.append(list(args))
        dat = Path(args[1])
        FakePool.rendered.append(dat.read_bytes())
        if dat.read_bytes() in FakePool.fail:
            return False
        if dat.read_bytes() in FakePool.corrupt:
            Path(args[2]).write_bytes(b'half a PNG')
            return True
        Image.new('RGB', stage_previews.PREVIEW_SIZE, 'green').save(args[2])
        return True


class FakeSocketIO:
    def __init__(self):
        self.events = []
        self.done = threading.Event()

    def emit(self, name, payload=None):
        self.events.append((name, payload))
        if name == 'job' and payload['status'] in jobs.FINAL:
            self.done.set()

    def items(self):
        return self.events[-1][1]['extra'].get('items', [])

    def complete(self):
        return self.events[-1][1]['result'] or self.events[-1][1]['extra'].get('summary')


def write_variant(vault, folder, variant_id, members):
    """A vault variant zip: storage/das/<folder>/<id>.zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return vault.touch('das', folder, f'{variant_id}.zip', data=buf.getvalue())


@pytest.fixture
def bulk(vault, monkeypatch, tmp_path):
    FakePool.calls = []
    FakePool.rendered = []
    FakePool.fail = set()
    FakePool.corrupt = set()
    monkeypatch.setattr(stage_previews, 'CspRenderPool', FakePool)
    socketio = FakeSocketIO()
    monkeypatch.setattr(state, 'get_socketio', lambda: socketio)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(job_previews, 'OUTPUT_PATH', tmp_path)
    client = vault.client(storage_stages, 'storage_stages_bp')
    return client, socketio


def run_batch(client, socketio, variants, timeout=10):
    resp = client.post('/api/mex/storage/stages/render-screenshots',
                       json={'variants': variants})
    assert socketio.done.wait(timeout), 'render batch never finished'
    return resp


def test_renders_each_selected_variant_from_its_vault_zip(vault, bulk):
    client, socketio = bulk
    write_variant(vault, 'battlefield', 'blue', {'GrNBa.dat': b'BATTLEFIELD'})
    write_variant(vault, 'final_destination', 'neon', {'GrNLa.dat': b'FD'})

    resp = run_batch(client, socketio, [
        {'stageCode': 'GrNBa', 'variantId': 'blue', 'name': 'Blue'},
        {'stageCode': 'GrNLa', 'variantId': 'neon', 'name': 'Neon'},
    ])
    assert resp.get_json()['success'] is True

    items = socketio.items()
    assert [i['variantId'] for i in items] == ['blue', 'neon']
    assert all(i['ok'] for i in items)
    # The folder is echoed back so the review grid can save without a lookup.
    assert [i['stageFolder'] for i in items] == ['battlefield', 'final_destination']
    assert [i['done'] for i in items] == [1, 2] and items[0]['total'] == 2
    for item in items:
        response = client.get(item['previewUrl'])
        try:
            png = response.data
        finally:
            response.close()
        with Image.open(io.BytesIO(png)) as image:
            assert image.size == stage_previews.PREVIEW_SIZE
    assert socketio.complete() == {'total': 2, 'rendered': 2, 'stopped': False,
                                   'failures': [], 'items': items}
    # Rendered from the zip's own stage file, with that stage's framing.
    assert [Path(c[1]).name for c in FakePool.calls] == ['GrNBa.dat', 'GrNLa.dat']
    assert '--eye' in FakePool.calls[0]


def test_stadium_renders_the_normal_form_not_a_transformation(vault, bulk):
    client, socketio = bulk
    write_variant(vault, 'pokemon_stadium', 'meow', {
        'GrPs.dat': b'NORMAL',
        'GrPs/GrPs1.dat': b'FIRE', 'GrPs/GrPs2.dat': b'GRASS',
        'GrPs/GrPs3.dat': b'WATER', 'GrPs/GrPs4.dat': b'ROCK',
    })
    # The vault also holds hand-named sets, where the form is only in the stem.
    write_variant(vault, 'pokemon_stadium', 'retro', {
        'Standard Stadium GrPs.dat': b'RETRO NORMAL',
        'Fire Trans GrPs1.dat': b'RETRO FIRE',
    })

    run_batch(client, socketio, [
        {'stageCode': 'GrPs', 'variantId': 'meow', 'name': 'Meoweekly'},
        {'stageCode': 'GrPs', 'variantId': 'retro', 'name': 'Retro'}])

    assert [i['ok'] for i in socketio.items()] == [True, True]
    assert FakePool.rendered == [b'NORMAL', b'RETRO NORMAL']


def test_a_transformation_stored_as_its_own_variant_says_why(vault, bulk):
    """Stadium transformations get imported as standalone vault variants. They
    are not stages -- at the stage camera they render an empty frame, so the
    user must be told that rather than "the renderer failed"."""
    client, socketio = bulk
    write_variant(vault, 'pokemon_stadium', 'grass-only',
                  {'Grass Trans GrPs2.dat': b'GRASS'})

    run_batch(client, socketio, [
        {'stageCode': 'GrPs', 'variantId': 'grass-only', 'name': 'Grass'}])

    item = socketio.items()[0]
    assert item['ok'] is False
    assert 'transformation form' in item['error']
    assert FakePool.rendered == []


def test_one_bad_variant_never_stops_the_batch(vault, bulk):
    client, socketio = bulk
    write_variant(vault, 'battlefield', 'dead', {'GrNBa.dat': b'CRASHER'})
    write_variant(vault, 'battlefield', 'torn', {'GrNBa.dat': b'TRUNCATED'})
    write_variant(vault, 'battlefield', 'empty', {'readme.txt': b'no stage here'})
    write_variant(vault, 'battlefield', 'good', {'GrNBa.dat': b'FINE'})
    FakePool.fail = {b'CRASHER'}
    FakePool.corrupt = {b'TRUNCATED'}

    run_batch(client, socketio, [
        {'stageCode': 'GrNBa', 'variantId': 'dead', 'name': 'Dead'},
        {'stageCode': 'GrNBa', 'variantId': 'torn', 'name': 'Torn'},
        {'stageCode': 'GrNBa', 'variantId': 'empty', 'name': 'Empty'},
        {'stageCode': 'GrNBa', 'variantId': 'gone', 'name': 'Gone'},
        {'stageCode': 'GrNBa', 'variantId': 'good', 'name': 'Good'},
    ])

    items = {i['variantId']: i for i in socketio.items()}
    assert set(items) == {'dead', 'torn', 'empty', 'gone', 'good'}
    assert items['good']['ok'] is True
    assert [items[v]['ok'] for v in ('dead', 'torn', 'empty', 'gone')] == [False] * 4
    # A half-written native PNG must never reach the review grid as a preview.
    assert 'previewUrl' not in items['torn']
    assert 'missing from the vault' in items['gone']['error']
    assert 'no stage file' in items['empty']['error']
    complete = socketio.complete()
    assert (complete['rendered'], complete['total']) == (1, 5)
    assert len(complete['failures']) == 4


def test_stage_without_a_calibrated_camera_is_refused(vault, bulk):
    client, socketio = bulk
    write_variant(vault, 'corneria', 'chrome', {'GrCn.dat': b'CORNERIA'})

    resp = run_batch(client, socketio, [
        {'stageCode': 'GrCn', 'variantId': 'chrome', 'name': 'Chrome'}])

    assert resp.get_json()['unsupportedStages'] == ['GrCn']
    item = socketio.items()[0]
    assert item['ok'] is False and 'no camera calibrated' in item['error']
    assert item['stageFolder'] == 'corneria'
    assert FakePool.calls == []       # nothing was drawn from a guessed viewpoint


def test_stop_abandons_the_rest_of_the_batch(vault, bulk):
    client, socketio = bulk
    for vid in ('one', 'two', 'three'):
        write_variant(vault, 'battlefield', vid, {'GrNBa.dat': vid.encode()})

    # Stop as soon as the first variant has been drawn.
    original = FakePool.render

    def render_then_stop(self, args):
        result = original(self, args)
        jobs.cancel(jobs.active_job(storage_stages.RENDER_KIND).id)
        return result

    FakePool.render = render_then_stop
    try:
        run_batch(client, socketio, [
            {'stageCode': 'GrNBa', 'variantId': v, 'name': v}
            for v in ('one', 'two', 'three')])
    finally:
        FakePool.render = original

    items = socketio.items()
    assert items[0]['ok'] is True
    assert len(items) == 1
    assert socketio.events[-1][1]['status'] == 'cancelled'
    response = client.get(items[0]['previewUrl'])
    try:
        assert response.status_code == 200
    finally:
        response.close()
    assert socketio.complete()['stopped'] is True


def test_second_batch_is_refused_while_one_runs(vault, bulk, monkeypatch):
    client, socketio = bulk
    write_variant(vault, 'battlefield', 'blue', {'GrNBa.dat': b'BATTLEFIELD'})
    holding = threading.Event()
    release = threading.Event()
    original = FakePool.render

    def blocking_render(self, args):
        holding.set()
        release.wait(10)
        return original(self, args)

    monkeypatch.setattr(FakePool, 'render', blocking_render, raising=False)
    variants = [{'stageCode': 'GrNBa', 'variantId': 'blue', 'name': 'Blue'}]
    client.post('/api/mex/storage/stages/render-screenshots', json={'variants': variants})
    assert holding.wait(10)
    try:
        second = client.post('/api/mex/storage/stages/render-screenshots',
                             json={'variants': variants})
        assert second.status_code == 409
        assert 'already running' in second.get_json()['error']
    finally:
        release.set()
    assert socketio.done.wait(10)


def test_empty_selection_is_rejected(bulk):
    client, _socketio = bulk
    resp = client.post('/api/mex/storage/stages/render-screenshots',
                       json={'variants': [{'stageCode': 'GrNBa'}]})
    assert resp.status_code == 400


def test_variant_listing_flags_which_stages_can_be_rendered(vault, monkeypatch):
    """The picker greys out variants the renderer has no camera for, so the
    flag has to travel with each variant."""
    write_variant(vault, 'battlefield', 'blue', {'GrNBa.dat': b'BATTLEFIELD'})
    write_variant(vault, 'corneria', 'chrome', {'GrCn.dat': b'CORNERIA'})
    vault.write({'stages': {}})
    client = vault.client(das, 'das_bp')

    variants = client.get('/api/mex/das/storage/variants').get_json()['variants']
    by_id = {v['id']: v for v in variants}
    assert by_id['blue']['canRender'] is True
    assert by_id['chrome']['canRender'] is False


def test_stage_render_recovery_removes_owned_extraction_and_previews(bulk):
    job = jobs.Job(storage_stages.RENDER_KIND, job_id='dead-stage')
    work = job_previews.prepare_previews(job)
    (work / 'GrNBa.dat').write_bytes(b'partial')
    (work / '0.png').write_bytes(b'preview')
    record = job.snapshot()
    record.update(status='running', owner=None)
    jobs._write(record)
    [recovered] = jobs.recover_interrupted()
    assert recovered['status'] == 'interrupted' and recovered['owned'] == {}
    assert not work.exists()


def test_a_new_preview_job_sweeps_reviews_left_open_for_a_day(bulk):
    import os
    root = job_previews.OUTPUT_PATH / 'job_previews'
    stale, recent = root / 'left-open', root / 'still-reviewing'
    for path in (stale, recent):
        path.mkdir(parents=True)
        (path / '0.png').write_bytes(b'preview')
    old = time.time() - job_previews.STALE_SECONDS - 60
    os.utime(stale, (old, old))
    job_previews.prepare_previews(jobs.Job(storage_stages.RENDER_KIND, job_id='next-render'))
    assert not stale.exists()
    assert (recent / '0.png').exists()
    assert job_previews.preview_dir('next-render').is_dir()


def test_stage_previews_survive_record_reload_and_delete_after_review(vault, bulk):
    client, socketio = bulk
    write_variant(vault, 'battlefield', 'blue', {'GrNBa.dat': b'BATTLEFIELD'})
    response = run_batch(client, socketio, [{'stageCode': 'GrNBa', 'variantId': 'blue'}])
    job_id = response.json['job_id']
    jobs._jobs.clear()
    record = jobs.get(job_id)
    assert record['status'] == 'done' and 'dataUri' not in str(record)
    preview = client.get(record['result']['items'][0]['previewUrl'])
    try:
        assert preview.status_code == 200
    finally:
        preview.close()
    assert client.delete(f'/api/mex/storage/stages/render-screenshots/{job_id}').status_code == 200
    assert not job_previews.preview_dir(job_id).exists()
    assert client.post('/api/mex/storage/stages/render-screenshots/stop').status_code == 405
