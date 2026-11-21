"""A Skin Lab or Stage Lab session that closed (15 idle minutes, `close`, a restart) carries on.

The next call naming it reopens it from its last checkpoint under the same
session id, with what a checkpoint cannot hold kept in its workspace: the
originals a reset returns to, the palette analysis, the scope choice and the
material values before the first edit. Also here: a stage checkpoint failure is
reported like a costume's, a stage result's checkpoint keys stay out of the
model's view, an ordinary chat that opens a lab gets the lab's roster for the
rest of that turn only, and the renderer's texture readback is read once.

No renderer process and no model request runs. The stand-in renderers load what
they exported when started on that file, as a real one does, and keep the real
renderer's reset rule (reset_material returns to the value it loaded with).
"""
import hashlib
import io
import json
import struct
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from core import config
from shared.aiengine import decisions
from shared.rendering.session import ViewerSession
from randall.assistant import compaction, continuity, engine, live_runs, tools
from shared import mod_files
from randall.recolor import lab_common, skin_lab, stage_lab
from tests.backend.test_stage_retexture import Renderer, stage_dat

SNAPSHOTS = {}        # sha256 of an exported file -> the renderer state it holds


def png(rgba, size=(8, 8)):
    out = io.BytesIO()
    Image.new('RGBA', size, rgba).save(out, format='PNG')
    return out.getvalue()


def pixels(raw):
    return np.array(Image.open(io.BytesIO(raw)).convert('RGBA'))


def run(tool, **args):
    return tools.execute(tools.prepare(tool, args))


def _exported(data, state):
    SNAPSHOTS[hashlib.sha256(data).hexdigest()] = state
    return data


def _loaded(path):
    return SNAPSHOTS.get(hashlib.sha256(Path(path).read_bytes()).hexdigest())


class Clock:
    """time.monotonic, moved by hand."""
    def __init__(self, monkeypatch):
        self.now = time.monotonic()
        monkeypatch.setattr(time, 'monotonic', lambda: self.now)

    def advance(self, seconds):
        self.now += seconds


class StageRenderer(Renderer):
    """test_stage_retexture's renderer, started on a file: an exported one comes back as it was."""
    exports = 0

    def __init__(self, exe=None, port=None, path=None, **kwargs):
        super().__init__()
        state = _loaded(path) if path else None
        if state:
            self.pixels, self.material_colors = dict(state['pixels']), dict(state['materials'])
        self.path = Path(path) if path else None
        self.loaded = dict(self.material_colors)

    def export_dat(self):
        StageRenderer.exports += 1
        return _exported(stage_dat(0) + struct.pack('>Q', StageRenderer.exports),
                         {'pixels': dict(self.pixels), 'materials': dict(self.material_colors)})

    def material_command(self, command):
        if command['type'] == 'setMaterial' and 'value' not in command:     # reset: the value it loaded with
            command = {**command, 'value': self.loaded[(command['id'], command['field'])]}
        return super().material_command(command)


@pytest.fixture
def stage(vault, monkeypatch):
    renderers = []

    def make(*args, **kwargs):
        renderers.append(StageRenderer(*args, **kwargs))
        return renderers[-1]
    monkeypatch.setattr(stage_lab, 'ViewerSession', make)
    stages = config.STORAGE_PATH / 'skinlab_stages'
    stages.mkdir()
    (stages / 'GrNBa.dat').write_bytes(stage_dat())
    from shared.rendering import stage_ops
    monkeypatch.setattr(stage_ops, 'STAGE_DATS_DIR', stages)
    yield SimpleNamespace(renderers=renderers)
    for key in list(stage_lab._sessions):
        stage_lab._sessions.pop(key)['viewer'].close()


def costume_dat():
    name = b'PlyFox5K_Share_joint\0'
    return struct.pack('>5I', 72 + len(name), 32, 0, 1, 0) + bytes(12) + bytes(32) + struct.pack('>2I', 0, 0) + name


class CostumeRenderer:
    textures = [{'index': i, 'width': 16, 'height': 16} for i in range(3)]
    exports = 0

    def __init__(self, exe=None, port=None, path=None, **kwargs):
        state = _loaded(path) if path else None
        self.pixels = dict(state['pixels']) if state else {
            0: png((220, 30, 30, 200), (16, 16)), 1: png('blue', (16, 16)), 2: png('gray', (16, 16))}
        self.materials = dict(state['materials']) if state else {('Model:0', 'diffuse'): '#ff000044',
                                                                 ('Model:1', 'diffuse'): '#0000ffff'}
        self.loaded = dict(self.materials)
        self.camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}
        self.updates, self.closed = [], False

    def material_command(self, command):
        if command['type'] == 'setMaterialColors':
            for edit in command['edits']:
                self.materials[(edit['id'], edit['field'])] = edit['value']
        elif command['type'] == 'setMaterial':
            key = (command['id'], command['field'])
            self.materials[key] = self.loaded[key] if command.get('reset') else command['value']
        return {'success': True, 'materials': [{'id': mid, 'fields': [{'key': key, 'kind': 'color', 'value': value}]}
                                               for (mid, key), value in self.materials.items()]}

    def get_full_texture(self, index): return self.pixels[index]
    def update_texture(self, index, data): self.pixels[index] = data; self.updates.append(index)
    def grab_frame(self): return self.pixels[0]
    def get_uv_layout(self): return []
    def close(self): self.closed = True
    def alive(self): return not self.closed

    def export_dat(self):
        CostumeRenderer.exports += 1
        return _exported(costume_dat() + struct.pack('>Q', CostumeRenderer.exports),
                         {'pixels': dict(self.pixels), 'materials': dict(self.materials)})


@pytest.fixture
def costume(vault, monkeypatch):
    from core import viewer_tools
    renderers = []

    def make(*args, **kwargs):
        renderers.append(CostumeRenderer(*args, **kwargs))
        return renderers[-1]
    monkeypatch.setattr(skin_lab, 'ViewerSession', make)
    for name in ('find_scene_file', 'find_aj_file', 'find_fighter_data_file'):
        monkeypatch.setattr(viewer_tools, name, lambda character: None)
    monkeypatch.setattr(viewer_tools, 'find_available_port', lambda: 12345)
    source = mod_files.register(costume_dat(), 'PlFxNr.dat', origin={'character': 'Fox', 'member': 'PlFxNr.dat'})
    yield SimpleNamespace(renderers=renderers, source=source)
    with skin_lab._lock:
        for key in list(skin_lab._sessions):
            skin_lab._close(key)


# ------------------------------------------------------------------ the Stage Lab

def test_an_expired_stage_session_carries_on_from_its_checkpoint_and_still_resets_to_the_original(stage, monkeypatch):
    clock = Clock(monkeypatch)
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    first = stage.renderers[0]
    run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'set_hue': 280, 'set_saturation': 60}])
    run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse', value='#ff0000ff')
    edited = pixels(first.pixels[0])

    clock.advance(lab_common.IDLE_SECONDS + 1)
    stage_lab._expire(sid)                          # what the idle timer calls
    assert sid not in stage_lab._sessions and first.closed

    # Another edit: code reopens the session from its last checkpoint and carries on.
    again = run('stage_lab', session_id=sid, action='recolor',
                edits=[{'texture_index': 2, 'set_hue': 200, 'set_saturation': 50}])
    assert 'error' not in again and again['changed'] == [2] and again['session_id'] == sid
    second = stage.renderers[1]
    assert stage_lab._sessions[sid]['viewer'] is second and second.path.name.startswith('resumed-')
    assert (pixels(second.pixels[0]) == edited).all(), 'the earlier edit is in the reopened copy'
    assert second.material_colors[('Group 1:0', 'diffuse')] == '#ff0000ff'
    assert second.loaded[('Group 1:0', 'diffuse')] == '#ff0000ff', "the renderer's own reset would stop here"

    # Reset still returns to the TRUE original, not to the checkpoint the renderer loaded.
    run('stage_lab', session_id=sid, action='reset_material', material_id='Group 1:0', field='diffuse')
    assert second.material_colors[('Group 1:0', 'diffuse')] == '#808080ff'
    run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse', value='#00ff00ff')
    everything = run('stage_lab', session_id=sid, action='reset_texture')
    assert sorted(everything['restored']) == [0, 2] and everything['restored_material_colors'] == 1
    assert pixels(second.pixels[0])[0, 0].tolist() == [200, 40, 40, 255]
    assert pixels(second.pixels[2])[0, 0].tolist() == [40, 200, 40, 255]
    assert second.material_colors[('Group 1:0', 'diffuse')] == '#808080ff'


def test_a_closed_stage_session_reopens_too_and_a_close_never_reopens_one(stage):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 90}])
    assert run('stage_lab', session_id=sid, action='close') == {'closed': True}
    assert run('stage_lab', session_id=sid, action='close') == {'closed': True}
    assert len(stage.renderers) == 1, 'closing a closed session starts nothing'
    frame = run('stage_lab', session_id=sid, action='frame')
    assert frame['files'] and len(stage.renderers) == 2
    # skin_material reaches it too, and checkpoints it as a stage.
    assert lab_common.is_stage(sid)
    run('stage_lab', session_id=sid, action='close')
    assert lab_common.is_stage(sid), 'a closed session is still a stage session'
    coverage = run('skin_material', session_id=sid, action='coverage', mask={'hue_min': 0, 'hue_max': 360})
    assert 'error' not in coverage and coverage['stage_target']['stage_code'] == 'GrNBa'


def test_a_full_lab_makes_room_and_the_session_it_closed_carries_on(stage, monkeypatch):
    """An open with every slot in use closes the session used longest ago instead of refusing: an AI whose
    earlier run left sessions open no longer knows their ids (0.9.0 MCP filming). That session carries on from
    its checkpoint on its next call."""
    clock = Clock(monkeypatch)
    oldest = run('stage_lab_open', stage_code='GrNBa')['session_id']
    run('stage_lab', session_id=oldest, action='recolor', edits=[{'texture_index': 0, 'set_hue': 280, 'set_saturation': 60}])
    others = []
    for _ in range(lab_common.MAX_SESSIONS - 1):
        clock.advance(5)
        others.append(run('stage_lab_open', stage_code='GrNBa')['session_id'])
    clock.advance(5)
    newest = run('stage_lab_open', stage_code='GrNBa')
    assert 'error' not in newest
    assert oldest not in stage_lab._sessions and stage.renderers[0].closed
    assert set(stage_lab._sessions) == {*others, newest['session_id']}

    clock.advance(5)
    again = run('stage_lab', session_id=oldest, action='recolor',
                edits=[{'texture_index': 2, 'set_hue': 200, 'set_saturation': 50}])
    assert 'error' not in again and again['session_id'] == oldest
    assert len(stage_lab._sessions) == lab_common.MAX_SESSIONS and newest['session_id'] in stage_lab._sessions


def test_a_checkpoint_that_reopens_with_other_textures_is_not_resumed(stage):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 90}])
    run('stage_lab', session_id=sid, action='close')
    workspace = stage_lab._workspace(sid)
    record = json.loads((workspace / lab_common.RECORD).read_text())
    record['textures'] = record['textures'][:2]      # as if export and reload renumbered them
    (workspace / lab_common.RECORD).write_text(json.dumps(record))
    refused = run('stage_lab', session_id=sid, action='frame')
    assert refused['error'] == stage_lab.MISSING
    assert sid not in stage_lab._sessions and stage.renderers[-1].closed


# ------------------------------------------------------------------ the Skin Lab, the same way

def test_an_expired_costume_session_carries_on_with_its_analysis_and_originals(costume, monkeypatch):
    clock = Clock(monkeypatch)
    opened = run('skin_lab_open', file_id=costume.source['file_id'])
    sid = opened['session_id']
    first = costume.renderers[0]
    original = pixels(first.pixels[0])
    run('skin_lab', session_id=sid, action='analyze_palette', texture_indices=[0], max_groups=1)
    recolored = run('skin_lab', session_id=sid, action='recolor', adjustments=[{'index': 0, 'hue_shift': 120}])
    run('skin_lab', session_id=sid, action='set_material', material_id='Model:0', field='diffuse', value='#00ff0044')
    edited = pixels(first.pixels[0])
    receipts = [{'name': 'skin_lab_open', 'arguments': {'file_id': costume.source['file_id']}, 'result': opened},
                {'name': 'skin_lab', 'arguments': {'session_id': sid, 'action': 'recolor'}, 'result': recolored}]

    clock.advance(lab_common.IDLE_SECONDS + 1)
    skin_lab._expire(sid)
    assert sid not in skin_lab._sessions and first.closed
    # To the model it is as usable as a live session: it keeps using the session id.
    assert continuity.working_context(receipts)['skin_sessions'][0]['status'] == 'active'

    # Another edit: the reopened copy carries the earlier recolor and material edit.
    material = run('skin_lab', session_id=sid, action='set_material', material_id='Model:1', field='diffuse',
                   value='#123456ff')
    assert 'error' not in material and material['session_id'] == sid
    second = costume.renderers[1]
    assert (pixels(second.pixels[0]) == edited).all() and second.materials[('Model:0', 'diffuse')] == '#00ff0044'
    assert second.loaded[('Model:0', 'diffuse')] == '#00ff0044', "the renderer's own reset would stop here"
    item = skin_lab._sessions[sid]
    assert item['source']['file_id'] == costume.source['file_id'] and item['edited']

    # The analysis came back: a recolor is still absolute from the ORIGINAL snapshot...
    run('skin_lab', session_id=sid, action='recolor', adjustments=[{'index': 0, 'hue_shift': 120}])
    assert (pixels(second.pixels[0]) == edited).all(), 'not shifted twice'
    # ...and reset returns to the true original, not to the checkpoint.
    run('skin_lab', session_id=sid, action='reset_palette')
    assert (pixels(second.pixels[0]) == original).all()
    run('skin_lab', session_id=sid, action='reset_material', material_id='Model:0', field='diffuse')
    assert second.materials[('Model:0', 'diffuse')] == '#ff000044'
    export = run('skin_lab', session_id=sid, action='export')
    assert mod_files.resolve(export['files'][0]['file_id'])[1]['origin']['member'] == 'PlFxNr.dat'


def test_a_texture_that_left_the_analysis_stays_out_of_it_after_a_resume(costume):
    """A material applied over a texture takes it out of the palette analysis (texture_material._write):
    a resumed analysis must not bring it back, or the next recolor would paint over the material."""
    from randall.recolor import texture_material
    sid = run('skin_lab_open', file_id=costume.source['file_id'])['session_id']
    run('skin_lab', session_id=sid, action='analyze_palette', texture_indices=[0, 1], max_groups=2)
    item, viewer = skin_lab._sessions[sid], costume.renderers[0]
    material = np.full((16, 16, 4), 255, np.uint8)
    texture_material._write(viewer, {0: material}, {0: pixels(viewer.pixels[0])}, item)
    assert set(item['palette']['originals']) == {1}
    run('skin_lab', session_id=sid, action='set_material', material_id='Model:0', field='diffuse', value='#00ff0044')
    run('skin_lab', session_id=sid, action='close')
    run('skin_lab', session_id=sid, action='inspect')
    resumed = skin_lab._sessions[sid]['palette']
    assert set(resumed['originals']) == {1} and set(resumed['maps']) == {1}


def test_a_costume_session_without_a_record_is_still_unavailable(costume):
    """Sessions made outside skin_lab_open (no workspace) behave as before."""
    skin_lab._sessions['plain'] = {'viewer': CostumeRenderer(), 'scratch': SimpleNamespace(cleanup=lambda: None),
                                   'used': time.monotonic(), 'palette': None, 'edited': False,
                                   'source': mod_files.resolve(costume.source['file_id'])[1]}
    skin_lab.skin_lab('plain', 'close')
    with pytest.raises(ValueError, match='expired or closed'):
        skin_lab.skin_lab('plain', 'frame')


# ------------------------------------------------------------------ what the model sees of a stage result

def test_a_stage_checkpoint_failure_is_reported_like_a_costume_one(stage):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = stage.renderers[0]
    real = viewer.export_dat

    def fail():
        raise RuntimeError('disk unavailable')
    viewer.export_dat = fail
    edited = run('stage_lab', session_id=sid, action='recolor', edits=[{'texture_index': 0, 'hue_shift': 90}])
    assert edited['changed'] == [0] and edited['checkpoint_error'] == continuity.CHECKPOINT_ERROR
    assert run('stage_lab', session_id=sid, action='frame')['checkpoint_error'] == continuity.CHECKPOINT_ERROR
    assert 'checkpoint_error' in compaction.fit_fresh(edited), 'the model is told'
    viewer.export_dat = real
    assert 'checkpoint_error' not in run('stage_lab', session_id=sid, action='recolor',
                                         edits=[{'texture_index': 0, 'hue_shift': 10}])


def test_stage_checkpoint_keys_are_the_workbenchs_not_the_models(stage):
    opened = run('stage_lab_open', stage_code='GrNBa')
    frame = run('stage_lab', session_id=opened['session_id'], action='frame')
    for result in (opened, frame):
        assert result['checkpoint_file'] and result['revision'] and result['stage_target']    # the transcript keeps them
        for seen in (compaction.fit_fresh(result), compaction.compact_result(result)):
            assert not {'checkpoint_file', 'revision', 'stage_target'} & set(seen)
            assert seen['session_id'] == opened['session_id']
    # A costume's checkpoint stays visible: its tool description names it for recovery.
    costume = {'session_id': 's', 'checkpoint_file': {'file_id': 'f' * 32}, 'revision': 2}
    assert compaction.fit_fresh(costume) == costume


# ------------------------------------------------------------------ the roster of an ordinary chat that opens a lab

def emit(text='', calls=None):
    yield {'type': 'completion', 'finish_reason': 'tool_calls' if calls else 'stop',
           'message': {'role': 'assistant', 'content': text or None, **({'tool_calls': calls} if calls else {})}}


@pytest.fixture
def ordinary_chat(monkeypatch):
    from randall.assistant.tasks import coordinator, store as taskstore
    taskstore.close()
    coordinator.CURRENT.set(None)
    monkeypatch.setattr(decisions, 'enabled', lambda: False)
    monkeypatch.setattr(tools, 'vanilla_assets_ready', lambda: False)

    def go(text, first_call=None, chat_id=None):
        seen = []

        def provider(messages, schemas, key, cancelled, *args, **kwargs):
            seen.append({s['function']['name'] for s in schemas})
            if len(seen) == 1 and first_call:
                yield from emit(calls=[{'id': 'c1', 'type': 'function', 'function': {
                    'name': first_call[0], 'arguments': json.dumps(first_call[1])}}])
            else:
                yield from emit('Done.')
        monkeypatch.setattr(engine, '_provider', provider)
        turn = engine.start(chat_id, text, {}, request_key='k')
        list(live_runs.stream(turn))
        return turn, seen
    return go


@pytest.mark.parametrize('kind', ['stage', 'costume'])
def test_an_ordinary_chat_that_opens_a_lab_gets_its_roster_for_that_turn_only(request, ordinary_chat, kind):
    if kind == 'stage':
        request.getfixturevalue('stage')
        call, roster = ('stage_lab_open', {'stage_code': 'GrNBa'}), engine.STAGE_TOOLS
    else:
        fixture = request.getfixturevalue('costume')
        call, roster = ('skin_lab_open', {'file_id': fixture.source['file_id']}), engine.SKIN_TOOLS
    turn, seen = ordinary_chat('open it in the lab', call)
    assert turn.answer['tools'][0]['status'] == 'done', turn.answer['tools'][0]
    assert 'search_website_mods' in seen[0], 'an ordinary chat starts with the whole roster'
    assert seen[1] <= roster and call[0] in seen[1], 'once its lab session is open, the lab roster'
    assert turn.answer['round_limit'] == engine.SKIN_MAX_ROUNDS
    assert turn.task.cost_budget_usd == engine.SKIN_MAX_COST
    # The escape, as on a workflow turn: the user's next message gets the whole roster back.
    _, later = ordinary_chat('now find me a Falco costume on the website', chat_id=turn.chat_id)
    assert 'search_website_mods' in later[0]


def test_no_family_budget_is_keyed_to_a_family_that_never_occurs():
    assert set(engine.FAMILY_COST_BUDGET) == {'model_import'}


# ------------------------------------------------------------------ the renderer's readback, read once

def test_a_texture_is_read_from_the_renderer_once_until_it_is_written():
    session = ViewerSession.__new__(ViewerSession)
    session._readback, session.textures, sent = {}, [{'index': 0, 'width': 1, 'height': 1}], []

    def request(message, reply_type, timeout=None):
        sent.append(message['type'])
        if message['type'] == 'getFullTexture':
            return {'data': __import__('base64').b64encode(b'png%d' % len(sent)).decode()}
        return {'success': True}
    session._request = request
    first = session.get_full_texture(0)
    assert session.get_full_texture(0) == first and sent == ['getFullTexture']
    session.update_texture(0, png((1, 2, 3, 255), (1, 1)))
    assert session.get_full_texture(0) != first
    assert sent == ['getFullTexture', 'updateTexture', 'getFullTexture']
