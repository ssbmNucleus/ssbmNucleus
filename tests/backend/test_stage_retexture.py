"""The stage retexture: evidence on open, batched exact edits, greyscale slots, reset,
generated materials through the shared material tool, the stage turn's budget, the
saved variant's metadata, workspace retention and the workbench's texture swap.

No viewer process and no model request runs: the renderer is a stand-in with the
protocol's own replies, the provider records what it was given.
"""
import io
import json
import os
import struct
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from core import config
from shared.aiengine import decisions
from shared.rendering import stage_editor
from randall.assistant import compaction, continuity, engine, live_runs, tools
from shared import mod_files
from randall.recolor import lab_common, stage_lab, texture_material


def png(rgba, size=(8, 8)):
    out = io.BytesIO()
    Image.new('RGBA', size, rgba).save(out, format='PNG')
    return out.getvalue()


def pixels(raw):
    return np.array(Image.open(io.BytesIO(raw)).convert('RGBA'))


def stage_dat(value=0):
    body = bytes([value]) * 32
    name = b'map_head\0'
    return struct.pack('>5I', 32 + len(body) + 8 + len(name), len(body), 0, 1, 0) + bytes(12) + body \
        + struct.pack('>2I', 0, 0) + name


class Renderer:
    """A Stage Lab renderer: texture 0 colour, 1 greyscale (an intensity slot), 2 a frame animating 0."""
    camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}

    def __init__(self, *args, **kwargs):
        self.textures = [{'index': 0, 'name': 'Group 1 / Texture_0', 'width': 8, 'height': 8, 'matAnim': False,
                          'animates': -1, 'extra': False},
                         {'index': 1, 'name': 'Group 1 / Texture_1', 'width': 8, 'height': 8, 'matAnim': False,
                          'animates': -1, 'extra': False},
                         {'index': 2, 'name': 'Group 1 / MatAnim_0', 'width': 8, 'height': 8, 'matAnim': True,
                          'animates': 0, 'extra': False}]
        self.pixels = {0: png((200, 40, 40, 255)), 1: png((120, 120, 120, 255)), 2: png((40, 200, 40, 255))}
        self.material_colors = {('Group 1:0', 'diffuse'): '#808080ff'}
        self.sent = []
        self.closed = False

    def get_full_texture(self, index): return self.pixels[index]
    def update_texture(self, index, data): self.pixels[index] = data; self.sent.append(index)
    def grab_frame(self):
        """The stage as drawn: texture 0 on the left half (its material lightens it 1.4x), texture 1 on the right."""
        frame = np.zeros((48, 64, 3), np.uint8)
        frame[:, :32] = np.clip(pixels(self.pixels[0])[0, 0, :3] * 1.4, 0, 255)
        frame[:, 32:] = pixels(self.pixels[1])[0, 0, :3]
        out = io.BytesIO()
        Image.fromarray(frame).save(out, format='PNG')
        return out.getvalue()
    def export_dat(self): return stage_dat(len(self.sent) % 200)
    def get_uv_layout(self): return [{'index': 0, 'triangles': [[0] * 15] * 12}, {'index': 1, 'triangles': [[0] * 15] * 2}]
    def set_camera(self, **kwargs): return dict(self.camera)
    def alive(self): return not self.closed
    def close(self): self.closed = True

    def material_command(self, command):
        if command['type'] == 'setMaterialColors':
            for edit in command['edits']:
                self.material_colors[(edit['id'], edit['field'])] = edit['value']
        elif command['type'] == 'setMaterial':
            self.material_colors[(command['id'], command['field'])] = command.get('value', '#808080ff')
        materials = [{'id': mid, 'fields': [{'key': key, 'kind': 'color', 'value': value}]}
                     for (mid, key), value in self.material_colors.items()]
        return {'success': True, 'materials': materials}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A real stage_lab_open over the stand-in renderer and a workspace in a temp vault."""
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    renderers = []

    def make(*args, **kwargs):
        renderers.append(Renderer())
        return renderers[-1]
    monkeypatch.setattr(stage_lab, 'ViewerSession', make)
    (tmp_path / 'skinlab_stages').mkdir()
    (tmp_path / 'skinlab_stages' / 'GrNBa.dat').write_bytes(stage_dat())
    from shared.rendering import stage_ops
    monkeypatch.setattr(stage_ops, 'STAGE_DATS_DIR', tmp_path / 'skinlab_stages')
    yield SimpleNamespace(renderers=renderers, root=tmp_path)
    for key in list(stage_lab._sessions):
        stage_lab._sessions.pop(key)['viewer'].close()


def run(tool, **args):
    return tools.execute(tools.prepare(tool, args))


# ------------------------------------------------------------------ the open is the evidence

def test_the_open_returns_the_first_picture_texture_sheet_and_rows(lab):
    opened = run('stage_lab_open', stage_code='GrNBa')
    names = [file['name'] for file in opened['files']]
    assert names == ['Stage preview.png', 'Stage identify map.png', 'Live texture sheet 0.png']
    assert opened['sheet_pages'] == 1
    rows = {row['index']: row for row in opened['textures']}
    assert rows[1]['greyscale'] is True and 'greyscale' not in rows[0]
    assert rows[0]['triangles'] == 12 and rows[2]['animates'] == 0 and rows[2]['triangles'] == 12
    assert 'matAnim' not in rows[0] and 'extra' not in rows[0], 'rows stay compact'
    # The workbench gets the source as its first checkpoint; the vision layer keeps the render by action.
    assert opened['checkpoint_file'] and opened['action'] == 'open'
    from randall.assistant.vision import tool_images
    assert sum(block['type'] == 'image_url' for block in tool_images('stage_lab_open', opened)) == 3


# ------------------------------------------------------------------ batched exact edits, greyscale, reset

def test_one_call_recolors_several_textures_exactly_with_masks_and_lightness(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = lab.renderers[0]
    result = run('stage_lab', session_id=sid, action='recolor', edits=[
        {'texture_index': 0, 'set_hue': 280, 'set_saturation': 60},
        {'texture_index': 2, 'hue_shift': 30, 'mask': {'hue_min': 200, 'hue_max': 260}},   # matches nothing
        {'texture_index': 1, 'lightness_scale': 0.5}])
    assert sorted(result['changed']) == [0, 1] and result['unchanged'] == [2]
    assert result['revision'] == 2 and result['checkpoint_file']          # one checkpoint for the batch
    purple = pixels(viewer.pixels[0])[0, 0]
    assert purple[2] > purple[1] and purple[0] > purple[1]                 # violet
    assert pixels(viewer.pixels[1])[0, 0, 0] == 60                         # greyscale slot darkened
    assert pixels(viewer.pixels[2])[0, 0].tolist() == [40, 200, 40, 255]


def test_greyscale_slots_refuse_colour_but_keep_lightness(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = lab.renderers[0]
    viewer.sent.clear()                              # the open's identify render put its textures back
    for edit in ({'texture_index': 1, 'set_hue': 10, 'set_saturation': 50}, {'texture_index': 1, 'saturation_shift': 20}):
        refused = run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 40}, edit])
        assert 'greyscale' in refused['error'] and 'set_material' in refused['error']
    assert viewer.sent == [], 'a refused batch writes nothing'
    swatch = mod_files.register(png((0, 0, 255, 255)), 'Blue.png')['file_id']
    assert 'greyscale' in run('stage_lab', session_id=sid, action='replace_texture', texture_index=1,
                              file_id=swatch)['error']
    # The whole-stage shift moves every colour texture and keeps greyscale slots grey.
    whole = run('stage_lab', session_id=sid, action='recolor', hue_shift=90, saturation_shift=20)
    assert 1 not in whole['changed'] and whole['greyscale_kept'] == [1]
    assert lab_common.greyscale(pixels(viewer.pixels[1]))


def test_replace_keeps_the_slot_size_and_reset_restores_textures_then_everything(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = lab.renderers[0]
    big = mod_files.register(png((0, 0, 255, 255), (64, 32)), 'Big.png')['file_id']
    replaced = run('stage_lab', session_id=sid, action='replace_texture', texture_index=0, file_id=big)
    assert replaced['changed'] == [0] and pixels(viewer.pixels[0]).shape == (8, 8, 4)
    run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 2, 'set_hue': 0, 'set_saturation': 90}])
    run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse', value='#ff0000ff')
    one = run('stage_lab', session_id=sid, action='reset_texture', texture_indices=[0])
    assert one['restored'] == [0] and one['restored_material_colors'] == 0
    assert pixels(viewer.pixels[0])[0, 0].tolist() == [200, 40, 40, 255]
    assert viewer.material_colors[('Group 1:0', 'diffuse')] == '#ff0000ff'
    everything = run('stage_lab', session_id=sid, action='reset_texture')
    assert everything['restored'] == [2] and everything['restored_material_colors'] == 1
    assert viewer.material_colors[('Group 1:0', 'diffuse')] == '#808080ff'
    assert pixels(viewer.pixels[2])[0, 0].tolist() == [40, 200, 40, 255]


# ------------------------------------------------------------------ a generated material on a stage

def test_a_generated_material_applies_to_a_stage_texture_through_the_shared_tool(lab, monkeypatch):
    def sheet(prompts, *, key=None, style='swatch'):
        assert key == 'request-key'                      # no provider call: the image API is stubbed
        tile = np.zeros((32, 32, 4), np.uint8); tile[..., 3] = 255; tile[::4, :, 0] = 255; tile[:, ::4, 2] = 255
        out = io.BytesIO(); Image.fromarray(tile).save(out, format='PNG')
        return [out.getvalue()] * len(prompts), {'cost_usd': 0.01, 'model': 'stub'}
    monkeypatch.setattr(texture_material, 'generate_material_sheet', sheet)
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = lab.renderers[0]
    viewer.sent.clear()                              # the open's identify render put its textures back
    generated = tools.execute(tools.prepare('generate_material', {'prompts': ['red and blue tiles']}),
                              image_key='request-key')
    swatch = generated['materials'][0]['file_id']
    # Greyscale slots cannot hold it; a colour slot can, at its own size, tiled by default.
    assert 'greyscale' in run('skin_material', session_id=sid, action='preview', texture_indices=[1],
                              material_file_id=swatch)['error']
    preview = run('skin_material', session_id=sid, action='preview', texture_indices=[0], material_file_id=swatch,
                  minimum_size=256)
    assert preview['controls']['mode'] == 'tile'
    assert preview['dimensions'] == {'0': {'original': [8, 8], 'proposed': [8, 8]}}
    applied = run('skin_material', session_id=sid, action='apply', preview_id=preview['preview_id'])
    assert applied['updated_textures'] == [0] and viewer.sent == [0]
    # It checkpoints as a stage (the workbench keeps showing the stage) and offers no skin reopen.
    assert applied['stage_target']['stage_code'] == 'GrNBa' and applied['checkpoint_file']
    state = continuity.working_context([{'name': 'skin_material', 'arguments': {'session_id': sid},
                                         'result': applied}])
    assert state['skin_sessions'] == []
    reset = run('skin_material', session_id=sid, action='reset', preview_id=preview['preview_id'])
    assert pixels(viewer.pixels[0])[0, 0].tolist() == [200, 40, 40, 255] and reset['checkpoint_file']


# ------------------------------------------------------------------ the workbench swaps textures in place

def test_an_edit_names_its_textures_and_materials_for_the_view_and_the_model_never_sees_them(lab):
    opened = run('stage_lab_open', stage_code='GrNBa')
    sid = opened['session_id']
    edited = run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 120}])
    update = edited['viewer_update']
    assert update['from'] == opened['checkpoint_file']['file_id'] and [t['index'] for t in update['textures']] == [0]
    path, info = mod_files.resolve(update['textures'][0]['file_id'])
    assert info['extension'] == '.png' and path.read_bytes() == lab.renderers[0].pixels[0]
    assert 'viewer_update' not in compaction.fit_fresh(edited)
    assert 'viewer_update' not in compaction.compact_result(edited)
    again = run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 2, 'set_hue': 200}])
    assert again['viewer_update']['from'] == edited['checkpoint_file']['file_id']
    # Material values ride along with their new absolute value (a reset in the view would restore the view's own).
    material = run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse',
                   value='#00ff00ff')
    assert material['viewer_update'] == {'from': again['checkpoint_file']['file_id'], 'textures': [],
                                         'materials': [{'id': 'Group 1:0', 'field': 'diffuse', 'value': '#00ff00ff'}]}
    reset = run('stage_lab', session_id=sid, action='reset_material', material_id='Group 1:0', field='diffuse')
    assert reset['viewer_update']['materials'][0]['value'] == lab.renderers[0].material_colors[('Group 1:0', 'diffuse')]
    whole = run('stage_lab', session_id=sid, action='recolor', hue_shift=30)
    assert whole['viewer_update']['materials'] and sorted(t['index'] for t in whole['viewer_update']['textures'])         == sorted(whole['changed'])
    # Anything the backend cannot name (a scenery change; here a stale checkpoint) reloads the view instead.
    stage_lab._sessions[sid]['viewer_stale'] = True
    assert 'viewer_update' not in run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 5}])
    assert 'viewer_update' in run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 5}])


# ------------------------------------------------------------------ save, retention

def test_a_saved_variant_carries_its_picture_and_date(lab, monkeypatch):
    metadata = {}

    from contextlib import contextmanager

    @contextmanager
    def transaction(**kwargs):
        yield metadata
    monkeypatch.setattr(stage_editor, 'metadata_transaction', transaction)
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    saved = run('stage_lab', session_id=sid, action='save', name='Purple Field')
    variant = metadata['stages']['battlefield']['variants'][0]
    assert variant['id'] == saved['variantId'] and variant['has_screenshot'] is True
    assert variant['screenshot_filename'] == saved['variantId'] + '_screenshot.png'
    assert variant['filename'] == saved['variantId'] + '.zip' and variant['date_added']
    assert (lab.root / 'das' / 'battlefield' / variant['screenshot_filename']).is_file()


def test_old_stage_workspaces_are_pruned_and_the_new_and_recent_ones_kept(lab):
    root = lab.root / 'stage_editor'
    root.mkdir(exist_ok=True)
    for n in range(14):
        folder = root / f'{n:032x}'
        folder.mkdir()
        (folder / 'workspace.json').write_text('{}')
        if n < 6:                                   # six days-old workspaces, eight from today
            stamp = time.time() - (10 + n) * 86400
            os.utime(folder, (stamp, stamp))
    (root / 'not-a-workspace').mkdir()
    opened = stage_editor.open_stage('GrNBa')
    left = {entry.name for entry in root.iterdir()}
    assert opened['id'] in left and 'not-a-workspace' in left
    # Kept: the new one, the eight recent ones and the two newest old ones (the newest ten);
    # removed: the four that are both old and outside the newest ten.
    assert {f'{n:032x}' for n in (0, 1)} <= left and not ({f'{n:032x}' for n in (2, 3, 4, 5)} & left)
    assert len([name for name in left if len(name) == 32]) == 11
    assert stage_editor.prune_workspaces(protect=(opened['id'],)) == []


# ------------------------------------------------------------------ the stage turn

def emit(text='', calls=None):
    yield {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
           'message': {'role': 'assistant', 'content': text or None, **({'tool_calls': calls} if calls else {})}}


@pytest.fixture
def stage_turn(vault, lab, monkeypatch):
    from randall.assistant.tasks import coordinator, store as taskstore
    taskstore.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    monkeypatch.setattr(tools, 'vanilla_assets_ready', lambda: False)

    def go(text, reply):
        seen = []

        def provider(messages, schemas, key, cancelled, *args, **kwargs):
            seen.append(SimpleNamespace(systems=[m['content'] for m in messages if m['role'] == 'system'],
                                        names=[s['function']['name'] for s in schemas],
                                        images=sum(1 for m in messages if isinstance(m.get('content'), list)
                                                   for b in m['content'] if b.get('type') == 'image_url')))
            yield from reply(len(seen), messages)
        monkeypatch.setattr(engine, '_provider', provider)
        stock = {'kind': 'stage', 'stage': 'GrNBa', 'vanilla': True, 'name': 'Battlefield (stock)'}
        turn = engine.start(None, text, {'task': 'recolor_stage', 'selection': [stock]}, request_key='k')
        list(live_runs.stream(turn))
        return turn, seen
    return go


def test_turn_one_starts_the_model_with_the_evidence_and_a_stage_roster(stage_turn):
    turn, seen = stage_turn('make it purple', lambda n, messages: emit('Looks good.'))
    opened = turn.answer['tools'][0]
    assert opened['name'] == 'stage_lab_open' and opened['workflow']['requested_by'] == 'code'
    assert len(opened['result']['files']) == 3 and opened['result']['textures'] and opened['result']['identify']
    first = seen[0]
    assert first.images == 3, 'the model sees the stage, its identify map and its texture sheet before its first round'
    assert set(first.names) <= engine.STAGE_TOOLS and {'stage_lab', 'skin_material', 'generate_material'} <= set(first.names)
    assert turn.answer['round_limit'] == engine.SKIN_MAX_ROUNDS and turn.answer['model_rounds'] == 1
    note = next(text for text in first.systems if text.startswith('Code workflow state: '))
    assert 'labelled texture sheets' in note and 'do not open it again' in note


def test_a_stage_turn_stops_at_the_round_budget_with_its_work_kept(stage_turn):
    def forever(n, messages):
        yield from emit(calls=[{'id': f'c{n}', 'type': 'function', 'function': {
            'name': 'stage_lab', 'arguments': json.dumps({'session_id': stage_lab_session(), 'action': 'frame'})}}])
    turn, seen = stage_turn('make it purple', forever)
    assert turn.answer['stop_reason'] == 'round_budget'
    assert 'stage edit' in turn.answer['error'] and 'changes are kept' in turn.answer['error']
    assert turn.answer['model_rounds'] == engine.SKIN_MAX_ROUNDS
    assert any(engine.STAGE_WRAP_UP_NOTE in s for s in seen[engine.SKIN_WRAP_UP].systems)
    assert not any(engine.STAGE_WRAP_UP_NOTE in s for s in seen[engine.SKIN_WRAP_UP - 1].systems)


def stage_lab_session():
    return next(iter(stage_lab._sessions))


# ------------------------------------------------------------------ the workbench's checkpoint copies

def test_checkpoint_paths_take_a_usd_stage_and_prune_old_copies(lab, monkeypatch, tmp_path):
    from flask import Flask
    from shared.routes import viewer as viewer_routes
    scratch = tmp_path / 'temp'
    scratch.mkdir()
    monkeypatch.setattr(viewer_routes.tempfile, 'gettempdir', lambda: str(scratch))
    monkeypatch.setattr(viewer_routes.tempfile, 'tempdir', str(scratch))
    old = scratch / (viewer_routes.CHECKPOINT_COPY_PREFIX + 'old')
    old.mkdir()
    (old / 'GrPs.usd').write_bytes(b'x')
    stamp = time.time() - 2 * viewer_routes.CHECKPOINT_COPY_SECONDS
    os.utime(old, (stamp, stamp))
    app = Flask(__name__)
    app.register_blueprint(viewer_routes.viewer_bp)
    file = mod_files.register(stage_dat(3), 'GrPs.usd')
    response = app.test_client().post('/api/mex/viewer/paths-checkpoint', json={'stageCode': 'GrPs', 'fileId': file['file_id']})
    assert response.status_code == 200 and Path(response.json['datFile']).read_bytes() == stage_dat(3)
    assert not old.exists()


def test_checkpoint_copies_go_with_the_backend_and_an_earlier_runs_at_the_next_start(lab, monkeypatch, tmp_path):
    """0.9.0 smoke test: viewer_checkpoint_* folders were left in the data scratch after the app quit. The backend
    removes its own copies as it shuts down (the shutdown route ends with os._exit, which runs no atexit), and a
    start removes every copy an earlier run left, however new."""
    from flask import Flask
    from projects.routes import project as project_routes
    from shared.routes import viewer as viewer_routes
    scratch = tmp_path / 'temp'
    scratch.mkdir()
    monkeypatch.setattr(viewer_routes.tempfile, 'gettempdir', lambda: str(scratch))
    monkeypatch.setattr(viewer_routes.tempfile, 'tempdir', str(scratch))
    monkeypatch.setattr(viewer_routes, '_made', set())
    earlier = scratch / (viewer_routes.CHECKPOINT_COPY_PREFIX + 'earlier')     # a minute old: not this run's
    earlier.mkdir()
    (earlier / 'GrPs.usd').write_bytes(b'x')
    app = Flask(__name__)
    app.register_blueprint(viewer_routes.viewer_bp)
    file = mod_files.register(stage_dat(3), 'GrPs.usd')
    made = [Path(app.test_client().post('/api/mex/viewer/paths-checkpoint', json={
        'stageCode': 'GrPs', 'fileId': file['file_id']}).json['tempDir']) for _ in range(2)]
    assert all(folder.is_dir() for folder in made) and earlier.is_dir()
    exits = []
    monkeypatch.setattr(project_routes.os, '_exit', exits.append)
    project_routes._exit_now()
    assert exits == [0] and not any(folder.exists() for folder in made)
    assert earlier.is_dir(), 'only its own copies: one an earlier run left waits for the next start'
    assert viewer_routes.sweep_viewer_folders() == 1 and not earlier.exists()
    from tests.paths import BACKEND
    source = (BACKEND / 'app.py').read_text(encoding='utf-8')
    assert 'sweep_viewer_folders()' in source and 'remove_own_viewer_folders()' in source


def test_the_render_kept_for_later_rounds_is_the_stage_not_a_texture_sheet(lab):
    from randall.assistant.vision import context_images
    opened = run('stage_lab_open', stage_code='GrNBa')
    sheet = run('stage_lab', session_id=opened['session_id'], action='texture_sheet', page=0)
    receipts = [{'name': 'stage_lab_open', 'result': opened}, {'name': 'stage_lab', 'result': sheet}]
    seen = []
    context_images(receipts, loader=lambda name, result: seen.append(result['files'][0]['file_id']) or [],
                   fresh_receipts=receipts[1:], latest_only=True)
    # The fresh sheet, plus the stage as it renders: the open's first picture, not its texture sheet.
    assert seen == [opened['files'][0]['file_id'], sheet['files'][0]['file_id']]


# ------------------------------------------------------------------ identify: what is drawn HERE

def test_the_identify_map_names_every_surface_and_puts_everything_back(lab):
    opened = run('stage_lab_open', stage_code='GrNBa')
    rows = {row['id']: row for row in opened['identify']['surfaces']}
    assert set(rows) == {0, 1} and set(opened['identify']['major']) == {0, 1}
    # Three views in one picture (this stand-in looks the same from every camera, has nothing small to zoom
    # on, and cannot be panned, so two): each id's share of each, its box where the picture first shows it.
    assert opened['identify']['views'] == ['game camera', 'raised three-quarter']
    assert rows[0]['area'] == pytest.approx(0.5, abs=0.02) and rows[0]['views'] == [rows[0]['area']] * 2
    assert rows[0]['box'][0] < rows[1]['box'][0] and rows[1]['greyscale'] is True
    assert rows[0]['size'] == '8x8'
    path, _ = mod_files.resolve(opened['files'][1]['file_id'])
    with Image.open(path) as picture:
        assert picture.width == 1024 and picture.height <= 1024              # the model sees it unscaled
    viewer = lab.renderers[0]
    sid, before, sent = opened['session_id'], dict(viewer.pixels), len(viewer.sent)
    looked = run('stage_lab', session_id=sid, action='identify', points=[[0.2, 0.5], [0.8, 0.4]],
                 camera={'rot_y': 30})
    assert [(a['id'], a['texture_index']) for a in looked['at']] == [(0, 0), (1, 1)]
    # A look, not an edit: every texture back byte for byte, no checkpoint, nothing for the workbench.
    assert viewer.pixels == before and len(viewer.sent) > sent
    assert looked['checkpoint_file'] == opened['checkpoint_file'] and 'viewer_update' not in looked
    assert stage_lab._sessions[sid]['viewer'].camera == {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}
    assert 'Invalid' not in json.dumps(looked) and looked['files'][0]['preview_only'] is True


def test_id_colours_stay_apart_and_read_back_through_a_material_gain():
    from randall.recolor import texture_inspection as ti
    for count in (2, 12, 40, 70):
        palette = ti.id_palette(count)
        assert len({tuple(c) for c in palette.tolist()}) == count and palette.max() <= ti.DECODE_LEVEL
        assert ti.palette_spacing(palette) > (0.12 if count <= 40 else 0.085)
        for gain in (0.7, 1.0, 1.5):
            shown = np.clip(palette.astype(float) * gain, 0, 255).astype(np.uint8)[None]
            assert ti.decode(shown, palette)[0].tolist() == list(range(count)), (count, gain)
    assert ti.decode(np.array([[[3, 2, 1], [90, 90, 90]]], np.uint8), ti.id_palette(12)).tolist() == [[-1, -1]]


def test_the_picture_numbers_regions_lists_specks_and_keeps_neighbours_apart():
    from randall.recolor import texture_inspection as ti
    ids = np.zeros((768, 1024), np.int32)
    ids[200:600, 100:500] = 1
    ids[700:703, 900:903] = 2                                   # a speck: listed, not numbered
    keys = [8, 'Group 5:16', 3]
    rows = [{'id': 8, 'area': 0.79, 'size': '512x256', 'colour_from': 'texture'},
            {'id': 'Group 5:16', 'area': 0.2, 'colour_from': 'vertex'},
            {'id': 3, 'area': 0.00001, 'size': '16x16'}]
    too_small = [3]
    data = ti._picture(ids, keys, None, rows, too_small, ['Group 7:7'], [])
    with Image.open(io.BytesIO(data)) as picture:
        assert picture.width == 1024 and 768 < picture.height <= 1024
    assert too_small == [3]
    colours = ti.display_colours(ids)
    assert len({colours[0], colours[1], colours[2]}) == 3
    assert [ti.label(k) for k in keys] == ['8', '5:16', '3'] and ti.label('Model:4') == 'm4'


def test_a_theme_hears_which_major_surfaces_are_still_vanilla(stage_turn):
    def edit_one(n, messages):
        if n == 1:
            yield from emit(calls=[{'id': 'c1', 'type': 'function', 'function': {'name': 'stage_lab', 'arguments': json.dumps(
                {'session_id': stage_lab_session(), 'action': 'recolor',
                 'edits': [{'texture_index': 0, 'set_hue': 10, 'set_saturation': 90}]})}}])
        else:
            yield from emit('Done.')
    turn, seen = stage_turn('make a lava retexture of this stage', edit_one)
    recolor = next(t for t in turn.answer['tools'] if t['name'] == 'stage_lab')
    assert recolor['result']['coverage'].startswith('Major surfaces not yet edited: ids 1 (')
    item = stage_lab._sessions[stage_lab_session()]
    assert item['edited_ids'] == {0}
    stored = json.loads((stage_lab._workspace(stage_lab_session()) / lab_common.RECORD).read_text())
    assert stored['coverage']['edited'] == [0], 'the edits so far survive a resume'


def test_a_request_that_names_a_surface_gets_no_coverage_line(stage_turn):
    def edit_one(n, messages):
        if n == 1:
            yield from emit(calls=[{'id': 'c1', 'type': 'function', 'function': {'name': 'stage_lab', 'arguments': json.dumps(
                {'session_id': stage_lab_session(), 'action': 'recolor', 'edits': [{'texture_index': 0, 'hue_shift': 40}]})}}])
        else:
            yield from emit('Done.')
    turn, seen = stage_turn('make the platforms gold', edit_one)
    recolor = next(t for t in turn.answer['tools'] if t['name'] == 'stage_lab')
    assert 'coverage' not in recolor['result']
    assert stage_lab.whole_stage_request('make a marijuana themed version of this stage')
    assert stage_lab.whole_stage_request('make it night') and stage_lab.whole_stage_request('purple please')
    assert not stage_lab.whole_stage_request('make the tree pink and the grass blue')


def test_coverage_counts_edits_by_texture_and_object_and_forgets_resets():
    from randall.recolor import texture_inspection as ti
    item = {'identify': {'major': [8, 'Group 5:16', 25], 'area': {8: 0.7, 'Group 5:16': 0.05, 25: 0.02},
                         'keys': [8, 'Group 5:16', 'Group 5:17', 25], 'drawn_by': {29: ['Group 5:16', 'Group 5:17'],
                                                                                    25: ['Group 5:4']}}}
    assert ti.coverage(item).startswith('Major surfaces not yet edited: ids 8 (70%), 5:16 (5%), 25 (2%)')
    ti.mark_edited(item, textures=[29])                  # a texture recolor reaches every object drawing it
    ti.mark_edited(item, objects=['Group 5:4'])          # an object edit reaches the texture id it draws
    assert ti.coverage(item).startswith('Major surfaces not yet edited: ids 8 (70%).')
    ti.mark_edited(item, clear=[25])
    assert '25 (2%)' in ti.coverage(item)
    ti.mark_edited(item, every=True)
    assert ti.coverage(item) == 'Every major surface of the identify map has been edited.'


def test_coverage_goes_on_past_the_major_surfaces_to_every_texture_the_stage_has():
    """Dream Land: the ends of the ground under the walkway (11) are 0.09% of one view, so a theme that gave every
    major surface its part saved them vanilla. Every surface counts; one texture in two slots counts once."""
    from randall.recolor import texture_inspection as ti
    item = {'identify': {
        'major': [8, 27], 'area': {8: 0.7, 27: 0.02, 11: 0.0009, 30: 0.0007},
        'keys': [0, 8, 11, 20, 27, 30, 'Group 6:2'], 'drawn_by': {11: ['Group 4:2'], 20: ['Group 4:24'],
                                                                  27: ['Group 5:11'], 30: ['Group 5:19'],
                                                                  4: ['Group 2:0'], 5: ['Group 2:0']},
        'units': [0, 8, 11, 20, 27, 30, 'Group 6:2', 5, 39],
        'frames': [39], 'extra': [0], 'aliases': [[20, 27]]}}
    ti.mark_edited(item, textures=[8, 27])
    line = ti.coverage(item)
    assert line.startswith('Every major surface is edited; still vanilla: ids 11, 30, 6:2 (small, or side and '
                           'back faces')
    assert '5 (second layers)' in line and '39 (animation frames)' in line and '0 (parts only a stage animation' in line
    assert ' 20' not in line and 20 in item['edited_ids'], 'the front strip and the side faces are one texture'
    ti.mark_edited(item, clear=[20])
    line = ti.coverage(item)
    assert 27 not in item['edited_ids'] and 'Major surfaces not yet edited: ids 27 (2%).' in line and ' 20' not in line
    ti.mark_edited(item, objects=['Group 5:11'])         # the front strip's object alone: its alias still shows
    assert 27 in item['edited_ids'] and ', 20, ' in ti.coverage(item)
    ti.mark_edited(item, textures=[20, 11, 30, 5, 39, 0], objects=['Group 6:2'])
    assert ti.coverage(item) == 'Every surface of the identify map has been edited.'
    again = {}
    ti.restore_coverage(again, json.loads(json.dumps(ti.coverage_record(item))))
    assert again['identify']['units'] == item['identify']['units'] and again['identify']['aliases'] == [[20, 27]]
    # An identify map that read nothing (too many ids to tell apart) still leaves the theme a list.
    blind = {'identify': {'major': [], 'area': {}, 'keys': [3, 4], 'drawn_by': {}, 'units': [3, 4]}}
    assert ti.coverage(blind).startswith('Still vanilla: ids 3, 4. A whole-stage theme')


def test_slots_the_renderer_writes_as_one_are_one_texture():
    """Its own rule: one group's slots with the same encoded bytes (a picture under two palettes too), and two
    groups' slots drawing one buffer. Animation frames are not slots: they never alias their base."""
    from randall.recolor import texture_inspection as ti
    data = bytes(range(32)) * 2 + bytes(32) + bytes(range(32)) + bytes(32)       # CI4 8x8 = 32 bytes a picture
    names = ['Group 4 / Texture_0', 'Group 4 / Texture_1', 'Group 5 / Texture_0', 'Group 5 / Texture_1',
             'Group 6 / Texture_0', 'Group 4 / MatAnim_0']
    viewer = SimpleNamespace(textures=[{'index': i, 'name': n, 'matAnim': 'MatAnim' in n} for i, n in enumerate(names)])
    row = lambda name, buffer: {'name': name, 'buffer': buffer, 'format': 8, 'size': (8, 8)}     # noqa: E731
    inventory = SimpleNamespace(dat=SimpleNamespace(raw=lambda offset, size: data[offset:offset + size]), objects=[
        SimpleNamespace(textures=[row(names[0], 0), row(names[1], 32), row(names[5], 0)]),   # same bytes, one group
        # (5, an animation frame of the same bytes, is no slot of its own)
        SimpleNamespace(textures=[row(names[2], 96), row(names[3], 64)]),       # 2: same bytes, another group
        SimpleNamespace(textures=[row(names[4], 64)])])                         # 3 and 4: one buffer
    assert sorted(ti._one_texture(viewer, inventory)) == [[0, 1], [3, 4]]


def test_a_look_reads_the_true_material_values_before_it_paints(lab, monkeypatch):
    """The look paints untextured objects through their materials; the session's baseline (what a reset goes
    back to once the reloaded renderer forgets its own) is read before that, never the paint."""
    from randall.recolor import texture_inspection as ti
    monkeypatch.setattr(stage_lab, 'ViewerSession',
                        lambda *a, **k: lab.renderers.append(CopyingRenderer(lab.root / 'renderer')) or lab.renderers[-1])
    item = stage_lab._sessions[run('stage_lab_open', stage_code='GrNBa')['session_id']]
    item['material_baseline'], item['resumed'] = None, False
    snapshot = ti._snapshot(item)
    item['viewer'].material_command({'type': 'setMaterialColors',
                                     'edits': [{'id': 'Group 1:0', 'field': 'diffuse', 'value': '#00ff00ff'}]})
    assert ti._take_back(item, snapshot) and item['resumed'] is True
    assert item['material_baseline'] == {'Group 1:0\ndiffuse': '#808080ff'}


class CopyingRenderer(Renderer):
    """HSDRawViewer's texture write: the new pixels go into every slot whose encoded bytes equal the written
    slot's. In a palette format those bytes are the index layout alone, so a flat paint of one size encodes
    alike in every slot whatever its colour. `saved` is what an export holds; it loads a file back (loadDat)."""

    def __init__(self, folder):
        super().__init__()
        def art(a, b, stripe):
            pixels_ = np.zeros((8, 8, 4), np.uint8); pixels_[...] = a
            pixels_[::stripe] = b
            return png_of(pixels_)
        self.pixels = {0: art((200, 40, 40, 255), (150, 30, 30, 255), 2),
                       1: art((120, 120, 120, 255), (90, 90, 90, 255), 3),
                       2: art((40, 200, 40, 255), (30, 150, 30, 255), 4)}
        self.saved = dict(self.pixels)
        folder.mkdir(exist_ok=True)
        self.dat_file = folder / 'shown.dat'

    @staticmethod
    def layout(data):
        order = {}
        return [order.setdefault(tuple(p), len(order)) for p in pixels(data).reshape(-1, 4).tolist()]

    def update_texture(self, index, data):
        old = self.layout(self.saved[index])
        for slot in self.saved:
            if self.layout(self.saved[slot]) == old:
                self.saved[slot] = data
        super().update_texture(index, data)

    def supports(self, message):
        return message == 'loadDat'

    def export_dat(self):
        return json.dumps({slot: data.hex() for slot, data in self.saved.items()}).encode()

    def reopen(self, path):
        self.saved = {int(slot): bytes.fromhex(data) for slot, data in json.loads(Path(path).read_bytes()).items()}
        self.pixels, self.dat_file = dict(self.saved), path


def png_of(pixels_):
    out = io.BytesIO()
    Image.fromarray(pixels_).save(out, format='PNG')
    return out.getvalue()


def test_a_look_leaves_the_file_as_it_found_it(lab, monkeypatch):
    """Dream Land was saved with its side faces wearing the front strip's grass and its platform tops the platform
    sides': the open's identify painted two same-size palette textures flat, which encode alike, and putting one back
    wrote both. A look now reloads the file exported before it instead of putting each texture back."""
    monkeypatch.setattr(stage_lab, 'ViewerSession',
                        lambda *a, **k: lab.renderers.append(CopyingRenderer(lab.root / 'renderer')) or lab.renderers[-1])
    original = {slot: pixels(data).tolist() for slot, data in CopyingRenderer(lab.root / 'renderer').saved.items()}
    opened = run('stage_lab_open', stage_code='GrNBa')
    viewer = lab.renderers[0]
    assert opened['identify']['surfaces'], 'the look itself still worked'
    held = lambda: {slot: pixels(data).tolist() for slot, data in viewer.saved.items()}    # noqa: E731
    assert held() == original
    run('stage_lab', session_id=opened['session_id'], action='highlight', texture_indices=[0, 1])
    assert held() == original
    run('stage_lab', session_id=opened['session_id'], action='identify')
    assert held() == original and {slot: pixels(viewer.pixels[slot]).tolist() for slot in viewer.pixels} == original
    # The file it reloads is in the session's workspace, one at a time.
    item = stage_lab._sessions[opened['session_id']]
    workspace = Path(item['source']['datFile']).parent
    assert [p.name for p in workspace.glob('look-*.dat')] == [Path(viewer.dat_file).name]
    # The reloaded renderer's own material originals are the file's: resets go to the session's baseline.
    assert item['resumed'] is True and item['material_baseline']


def test_a_call_without_an_action_is_told_only_the_actions():
    for args in ({'session_id': 'x', 'texture_indices': [1]}, {'session_id': 'x', 'action': 'look_here'}):
        with pytest.raises(ValueError) as refused:
            tools.prepare('stage_lab', args)
        message = str(refused.value)
        assert "'action' is" in message and 'use one of' in message and 'identify' in message
        assert 'Accepted parameters' not in message and 'object_ids' not in message


def test_only_the_open_and_an_explicit_identify_render_the_map(lab, monkeypatch):
    """Coverage comes from the open's table and the edit history: no edit renders the identify map again."""
    from randall.recolor import texture_inspection as ti
    renders = []
    real = ti._render_ids
    monkeypatch.setattr(ti, '_render_ids', lambda *a, **k: renders.append(1) or real(*a, **k))
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    assert len(renders) == 1
    run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 90}])
    run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse', value='#ff0000ff')
    run('stage_lab', session_id=sid, action='reset_texture', texture_indices=[0])
    assert len(renders) == 1 and ti.coverage(stage_lab._sessions[sid])
    run('stage_lab', session_id=sid, action='identify')
    assert len(renders) == 2
