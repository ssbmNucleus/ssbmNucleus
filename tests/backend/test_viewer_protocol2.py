"""Viewer stream protocol 2 (docs/dev/VIEWER_STREAMING.md): capability detection, the in-place colour
messages and their payloads, the texture batch, loadDat, and the fallback to today's restart on an
older viewer or a failed update.

The session tests run the real shared/rendering/session.ViewerSession against a fake stream server
(a scripted WebSocket: no process, no GL). The lab tests use test_stage_colours' synthetic stages and
stand-in renderer, here with a protocol-2 one that applies the messages it is sent to its file the way
the native viewer does (vertex colours, key streams, material and light colours).
"""
import base64
import json
import queue
import struct
from pathlib import Path

import pytest

from shared.rendering import dat_colours as dc
from shared.rendering import session as session_module
from shared.rendering.session import ViewerSession, ViewerSessionError
from randall.assistant import continuity
from randall.recolor import lab_common, model_colours as mc, stage_lab
from tests.backend.test_stage_colours import Renderer, keys, png, run, stage, vertex, lab  # noqa: F401

V2_MESSAGES = ['hello', 'getTextures', 'updateTexture', 'updateTextures', 'loadDat', 'setVertexColors',
               'setAnimationColors', 'setLightColors', 'exportDat']


# --------------------------------------------------------------------------- #
# a fake stream server                                                         #
# --------------------------------------------------------------------------- #
class FakeServer:
    """What the native viewer says on connect and how it answers (one scripted reply per command)."""

    def __init__(self, protocol=2, messages=V2_MESSAGES, fail=()):
        self.protocol, self.messages, self.fail = protocol, list(messages), set(fail)
        self.sent = []
        self.textures = [{'index': 0, 'name': 'Texture_0', 'width': 8, 'height': 8},
                         {'index': 1, 'name': 'Texture_1', 'width': 8, 'height': 8}]

    def greeting(self):
        caps = {'type': 'capabilities', 'protocolVersion': self.protocol, 'animationTicks': True}
        if self.protocol >= 2:
            caps['messages'] = self.messages
        return [caps, {'type': 'info', 'camera': {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 10}}]

    def answer(self, msg):
        self.sent.append(msg)
        kind, rid = msg['type'], msg.get('requestId')
        if kind == 'getTextures':
            return {'type': 'textureList', 'textures': self.textures}
        if kind == 'updateTexture':
            return {'type': 'textureUpdated', 'index': msg['index'], 'success': True}
        replies = {'updateTextures': 'texturesUpdated', 'setVertexColors': 'vertexColorsSet',
                   'setAnimationColors': 'animationColorsSet', 'setLightColors': 'lightColorsSet',
                   'loadDat': 'datLoaded'}
        if kind in replies:
            if kind in self.fail:
                return {'type': replies[kind], 'requestId': rid, 'success': False, 'error': f'{kind} refused'}
            reply = {'type': replies[kind], 'requestId': rid, 'success': True}
            if kind == 'loadDat':
                reply.update(textures=[{'index': 0, 'name': 'Texture_0', 'width': 16, 'height': 16, 'thumbnail': 'x'}],
                             reframed=True, camera={'rotX': 5, 'rotY': 0, 'scale': 2, 'x': 1, 'y': 2})
            return reply
        return None


class FakeSocket:
    def __init__(self, server):
        self.server, self.inbox = server, queue.Queue()
        for message in server.greeting():
            self.inbox.put(json.dumps(message))

    def settimeout(self, value):
        pass

    def send(self, text):
        reply = self.server.answer(json.loads(text))
        if reply is not None:
            self.inbox.put(json.dumps(reply))

    def recv_data(self):
        try:
            return session_module.websocket.ABNF.OPCODE_TEXT, self.inbox.get(timeout=0.05)
        except queue.Empty:
            raise session_module.websocket.WebSocketTimeoutException()

    def close(self):
        pass


class FakeProcess:
    pid, returncode = 4242, None

    def poll(self): return None
    def terminate(self): self.returncode = 0
    def wait(self, timeout=None): return 0
    def kill(self): pass


@pytest.fixture
def connect(monkeypatch, tmp_path):
    monkeypatch.setattr(session_module, 'own', lambda proc: proc)
    monkeypatch.setattr(session_module.subprocess, 'Popen', lambda *a, **k: FakeProcess())
    monkeypatch.setattr(ViewerSession, '_wait_http_ready', lambda self, timeout: None)
    sessions = []

    def make(server):
        monkeypatch.setattr(session_module.websocket, 'create_connection', lambda *a, **k: FakeSocket(server))
        viewer = ViewerSession('viewer.exe', 1, tmp_path / 'a.dat', scene_file='scene.yml', aj_file='aj.dat',
                               data_file='data.dat')
        sessions.append(viewer)
        return viewer
    yield make
    for viewer in sessions:
        viewer.close()


# --------------------------------------------------------------------------- #
# the session                                                                  #
# --------------------------------------------------------------------------- #
def test_a_protocol_2_viewer_is_told_from_an_older_one(connect):
    new = connect(FakeServer())
    assert new.capabilities['protocolVersion'] == 2
    assert new.supports('setVertexColors') and new.supports('loadDat') and not new.supports('nothingLikeThis')
    old = connect(FakeServer(protocol=1))
    assert old.capabilities['protocolVersion'] == 1
    assert not old.supports('setVertexColors') and not old.supports('updateTextures')
    partial = connect(FakeServer(messages=['updateTextures']))
    assert partial.supports('updateTextures') and not partial.supports('setLightColors')


def test_texture_writes_are_one_batch_on_a_new_viewer_and_one_by_one_on_an_old(connect, monkeypatch):
    pngs = {0: png((255, 0, 0, 255), (16, 8)), 1: png((0, 255, 0, 255))}
    server = FakeServer()
    new = connect(server)
    new._readback = {0: b'stale', 1: b'stale'}
    new.update_textures(pngs)
    batches = [m for m in server.sent if m['type'] == 'updateTextures']
    assert len(batches) == 1 and [t['index'] for t in batches[0]['textures']] == [0, 1]
    assert base64.b64decode(batches[0]['textures'][0]['data']) == pngs[0] and batches[0]['requestId']
    assert new._readback == {}, 'a written texture is read from the renderer again'
    assert new.textures[0]['width'] == 16, 'the sizes follow what was sent'
    # A batch larger than BATCH_BYTES goes as several messages, in order.
    monkeypatch.setattr(session_module, 'BATCH_BYTES', 10)
    new.update_textures(pngs)
    assert [[t['index'] for t in m['textures']] for m in server.sent if m['type'] == 'updateTextures'][1:] == [[0], [1]]
    old_server = FakeServer(protocol=1)
    old = connect(old_server)
    old.update_textures(pngs)
    assert [m['type'] for m in old_server.sent if m['type'].startswith('update')] == ['updateTexture', 'updateTexture']


def test_a_refused_batch_raises(connect):
    viewer = connect(FakeServer(fail={'updateTextures'}))
    with pytest.raises(ViewerSessionError, match='refused'):
        viewer.update_textures({0: png((1, 2, 3, 255))})


def test_colour_messages_go_in_order_with_request_ids_and_fail_loudly(connect):
    server = FakeServer()
    viewer = connect(server)
    messages = [{'type': 'setVertexColors', 'objects': [{'id': 'Group 0:0', 'colors': []}]},
                {'type': 'setLightColors', 'lights': [{'name': 'Group 0 light 0', 'rgba': '#ff0000ff'}], 'tracks': []}]
    viewer.apply_colour_messages(messages)
    sent = [m for m in server.sent if m['type'].startswith('set')]
    assert [m['type'] for m in sent] == ['setVertexColors', 'setLightColors']
    assert sent[0]['objects'] == messages[0]['objects'] and all(m['requestId'] for m in sent)
    refusing = connect(FakeServer(fail={'setLightColors'}))
    with pytest.raises(ViewerSessionError, match='setLightColors refused'):
        refusing.apply_colour_messages(messages)
    with pytest.raises(ViewerSessionError, match='cannot take'):
        connect(FakeServer(protocol=1)).apply_colour_messages(messages)


def test_load_dat_swaps_the_model_and_keeps_the_companions(connect, tmp_path):
    server = FakeServer()
    viewer = connect(server)
    viewer._readback = {0: b'old'}
    viewer.reopen(tmp_path / 'b.dat')
    message = next(m for m in server.sent if m['type'] == 'loadDat')
    assert message['datFile'].endswith('b.dat')
    assert (message['sceneFile'], message['ajFile'], message['dataFile']) == ('scene.yml', 'aj.dat', 'data.dat')
    assert 'reframe' not in message, 'the viewer decides: kept unless the kind of model changes'
    assert viewer.textures == [{'index': 0, 'name': 'Texture_0', 'width': 16, 'height': 16, 'matAnim': False,
                                'animates': -1, 'extra': False}]
    assert viewer._readback == {} and viewer.camera['scale'] == 2, 'a reframed view reseeds the tracked camera'
    with pytest.raises(ViewerSessionError):
        connect(FakeServer(fail={'loadDat'})).load_dat(tmp_path / 'c.dat')


# --------------------------------------------------------------------------- #
# the messages an edit becomes                                                 #
# --------------------------------------------------------------------------- #
def test_colour_messages_name_only_what_changed():
    source = dc.scan(stage(fmt=4, kind='direct'))
    assert dc.colour_messages(source, dc.scan(source.dat.data())) == []
    edited = dc.scan(source.dat.data())
    plans = mc.plans([{'material_ids': ['Group 0:1'], 'set_hue': 120, 'set_saturation': 80}],
                     lambda change: [edited.object('Group 0:1')], animated=False)
    mc.recolor_vertex(edited, plans)
    (message,) = dc.colour_messages(source, dc.scan(edited.dat.data()))
    assert message['type'] == 'setVertexColors'
    (entry,) = message['objects']
    assert entry['id'] == 'Group 0:1' and [(c['pobj'], c['attr']) for c in entry['colors']] == [(0, dc.GX_VA_CLR0)]
    rgba = base64.b64decode(entry['colors'][0]['rgba'])
    after = dc.scan(edited.dat.data())
    assert [tuple(rgba[i:i + 4]) for i in range(0, len(rgba), 4)] == \
        [c for v in after.object('Group 0:1').vertex for _, c in dc.vertex_values(after.dat, v)]


def test_animated_and_light_edits_become_key_streams_and_colours():
    red = [(t, 0x87, dc.encode_keys(keys(2, [0, 30, 60], v), 0x87, 0))
           for t, v in ((4, [1.0, 0.2, 1.0]), (5, [0.0, 0.1, 0.0]), (6, [0.0, 0.1, 0.0]))]
    light = ((255, 40, 40, 255), [(t, 0x87, dc.encode_keys(keys(2, [0, 50], v), 0x87, 0))
                                  for t, v in ((9, [1.0, 0.5]), (10, [0.1, 0.2]), (11, [0.1, 0.2]))])
    source = dc.scan(stage(render_flags=0x01, tracks=red, light=light))
    edited = dc.scan(source.dat.data())
    plans = mc.plans([{'material_ids': ['Group 0:0'], 'set_hue': 120, 'set_saturation': 60}],
                     lambda change: [edited.object('Group 0:0')], animated=True)
    mc.recolor_animated(edited, plans)
    (message,) = dc.colour_messages(source, dc.scan(edited.dat.data()))
    assert message['type'] == 'setAnimationColors'
    after = dc.scan(edited.dat.data())
    streams = {tuple(t['key']): base64.b64decode(t['data']) for t in message['tracks']}
    colour_tracks = [t for t in after.object('Group 0:0').tracks if t.channel[0] == 'diffuse']
    assert {t.key for t in colour_tracks} == set(streams), 'every recoloured channel, and nothing else (alpha)'
    for track in colour_tracks:
        assert streams[track.key] == after.dat.raw(track.buffer, track.length)
    (material,) = message['materials']
    assert material['id'] == 'Group 0:0' and material['diffuse'] == '#' + after.dat.raw(
        after.object('Group 0:0').material + 4, 4).hex()
    # A light edit: its colour and its keys.
    lit = dc.scan(source.dat.data())
    lit.dat.put(lit.lights[0]['offset'], bytes((40, 255, 40, 255)))
    (message,) = dc.colour_messages(source, dc.scan(lit.dat.data()))
    assert message == {'type': 'setLightColors', 'lights': [{'name': 'Group 0 light 0', 'rgba': '#28ff28ff'}],
                       'tracks': []}


def test_a_changed_layout_is_no_message():
    one, two = dc.scan(stage(objects=1)), dc.scan(stage(objects=2))
    with pytest.raises(dc.DatError):
        dc.colour_messages(one, two)


# --------------------------------------------------------------------------- #
# the labs: in place on a protocol-2 renderer, else as before                 #
# --------------------------------------------------------------------------- #
class Protocol2(object):
    """Mixin for a lab's stand-in renderer: announces protocol 2 and applies what it is sent to its file
    (`data`) as the native viewer applies it to its loaded model."""
    refuse = set()
    loads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received, self.batches, self.loaded = [], [], []

    def supports(self, message):
        return message in V2_MESSAGES and not (message == 'loadDat' and not self.loads)

    def apply_colour_messages(self, messages):
        inv = dc.scan(self.data)
        for message in messages:
            if message['type'] in self.refuse:
                raise ViewerSessionError(f"{message['type']} refused")
            self.received.append(message)
            for entry in message.get('objects', ()):
                obj = inv.object(entry['id'])
                for colour in entry['colors']:
                    attr = next(a for a in obj.vertex if (a.key[3], a.key[4]) == (colour['pobj'], colour['attr']))
                    dc.private_vertex(inv.dat, [attr])        # a buffer another field reads is copied first
                    raw = base64.b64decode(colour['rgba'])
                    for i, off in enumerate(attr.offsets()):
                        old = inv.dat.raw(off, attr.size)
                        inv.dat.put(off, dc.encode_colour(attr.fmt, raw[i * 4:i * 4 + 3], old))
            for track in message.get('tracks', ()):
                found = next(t for t in inv.tracks if list(t.key) == track['key'])
                dc.replace_track(inv.dat, found, base64.b64decode(track['data']), track['valueFlag'], track['tanFlag'])
            for entry in message.get('materials', ()):
                obj = inv.object(entry['id'])
                for field, at in dc.MATERIAL_FIELDS.items():
                    inv.dat.put(obj.material + at, bytes.fromhex(entry[field][1:]))
            for light in message.get('lights', ()):
                found = next(item for item in inv.lights if item['where'] == light['name'])
                inv.dat.put(found['offset'], bytes.fromhex(light['rgba'][1:]))
        self.data = inv.dat.data()

    def update_textures(self, updated):
        self.batches.append(list(updated))

    def reopen(self, path):
        self.loaded.append(path)
        from pathlib import Path
        self.data = Path(path).read_bytes()

    def load_dat(self, path, **kwargs):
        self.reopen(path)


class Protocol2Renderer(Protocol2, Renderer):
    pass


@pytest.fixture
def lab2(lab, monkeypatch):
    def make(*args, **kwargs):
        lab.renderers.append(Protocol2Renderer(*args, **kwargs))
        return lab.renderers[-1]
    monkeypatch.setattr(stage_lab, 'ViewerSession', make)
    from randall.recolor import stage_colours
    monkeypatch.setattr(stage_colours, 'ViewerSession', make)
    Protocol2Renderer.refuse, Protocol2Renderer.loads = set(), True
    return lab


def _same_colours(a, b):
    left, right = dc.scan(a), dc.scan(b)
    return all(vertex(a, o.id) == vertex(b, o.id) for o in left.objects) and \
        [bytes(light['rgba']) for light in left.lights] == [bytes(light['rgba']) for light in right.lights]


def test_a_vertex_edit_goes_in_place_and_rides_to_the_workbench(lab2):
    source = stage(fmt=1, kind='index', shared=True)
    sid = lab2.open(source)['session_id']
    viewer = lab2.renderers[0]
    # The open's identify map loads its id copy (materials, blending, fog neutral), paints the vertex colours
    # flat, then reloads the file it found (one message, two loadDats): the colours as opened afterwards, and
    # nothing else (texture_inspection.identify). Edits never render it.
    assert [m['type'] for m in viewer.received] == ['setVertexColors']
    assert [Path(p).name.startswith('look-ids-') for p in viewer.loaded] == [True, False]
    assert all(vertex(viewer.data, o.id) == vertex(source, o.id) for o in dc.scan(source).objects)
    viewer.received.clear()
    viewer.loaded.clear()
    result = run('stage_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'material_ids': ['Group 0:1'], 'set_hue': 120, 'set_saturation': 80}])
    assert len(lab2.renderers) == 1 and not viewer.closed and not viewer.loaded, 'nothing restarted or reloaded'
    assert [m['type'] for m in viewer.received] == ['setVertexColors']
    item = stage_lab._sessions[sid]
    assert item['colour_data'][0] is viewer and _same_colours(viewer.data, item['colour_data'][1])
    assert vertex(viewer.data, 'Group 0:0') == vertex(source, 'Group 0:0'), 'the other reader of the array kept its colours'
    update = result['viewer_update']
    assert update['textures'] == [] and update['colours']['types'] == ['setVertexColors']
    assert json.loads(continuity.colours_file(update['colours']['id']).read_text()) == viewer.received
    assert 'viewer_colours' not in item, 'consumed by the checkpoint'
    # Nothing changed: an empty swap, no messages.
    again = run('stage_lab', session_id=sid, action='recolor_vertex',
                edits=[{'material_ids': ['Group 0:1'], 'set_hue': 120, 'set_saturation': 0, 'mask': {'hue_min': 0,
                                                                                                  'hue_max': 1}}])
    assert again['viewer_update'] == {'from': result['checkpoint_file']['file_id'], 'textures': []}


def test_animated_light_and_reset_edits_go_in_place(lab2):
    red = [(t, 0x87, dc.encode_keys(keys(2, [0, 30, 60], v), 0x87, 0))
           for t, v in ((4, [1.0, 0.2, 1.0]), (5, [0.0, 0.1, 0.0]), (6, [0.0, 0.1, 0.0]))]
    light = ((255, 40, 40, 255), [(t, 0x87, dc.encode_keys(keys(2, [0, 50], v), 0x87, 0))
                                  for t, v in ((9, [1.0, 0.5]), (10, [0.1, 0.2]), (11, [0.1, 0.2]))])
    sid = lab2.open(stage(render_flags=0x01, tracks=red, light=light))['session_id']
    viewer = lab2.renderers[0]
    viewer.loaded.clear()                    # the open's identify map reloads the file it looked at
    animated = run('stage_lab', session_id=sid, action='recolor_animated',
                   edits=[{'material_ids': ['Group 0:0'], 'set_hue': 120, 'set_saturation': 60}])
    lights = run('stage_lab', session_id=sid, action='recolor_lights', edits=[{'set_hue': 200, 'set_saturation': 70}])
    reset = run('stage_lab', session_id=sid, action='reset_colors')
    assert len(lab2.renderers) == 1 and not viewer.loaded
    assert [m['type'] for m in viewer.received] == ['setAnimationColors', 'setLightColors',
                                                    'setAnimationColors', 'setLightColors']
    assert animated['viewer_update']['colours']['objects'] == ['Group 0:0']
    assert lights['viewer_update']['colours']['types'] == ['setLightColors']
    assert reset['viewer_update']['colours']['types'] == ['setAnimationColors', 'setLightColors']
    item = stage_lab._sessions[sid]
    assert dc.colour_messages(dc.scan(viewer.data), dc.scan(item['colour_data'][1])) == [], \
        'the renderer holds exactly the edited file'


def test_a_failed_in_place_update_loads_the_file_and_an_old_viewer_restarts(lab2):
    source = stage(fmt=5, kind='direct')
    Protocol2Renderer.refuse = {'setVertexColors'}
    sid = lab2.open(source)['session_id']
    viewer = lab2.renderers[0]
    viewer.loaded.clear()                    # the open's identify map reloads the file it looked at
    result = run('stage_lab', session_id=sid, action='recolor_vertex', edits=[{'material_ids': ['Group 0:0'],
                                                                               'hue_shift': 90}])
    assert len(lab2.renderers) == 1 and len(viewer.loaded) == 1, 'loadDat into the running renderer'
    assert 'colours' not in (result.get('viewer_update') or {}) and result.get('viewer_update') is None, \
        'the view reloads too'
    assert vertex(viewer.data, 'Group 0:0') != vertex(source, 'Group 0:0')
    # Neither in place nor loadDat: a fresh renderer, as before.
    Protocol2Renderer.loads = False
    run('stage_lab', session_id=sid, action='recolor_vertex', edits=[{'material_ids': ['Group 0:0'], 'hue_shift': 90}])
    assert len(lab2.renderers) == 2 and viewer.closed


def test_lab_texture_writes_use_the_batch():
    class Old:
        def __init__(self): self.sent = []
        def update_texture(self, index, data): self.sent.append(index)

    class New(Old):
        def update_textures(self, updated): self.sent.append(list(updated))
    old, new = Old(), New()
    lab_common.write_textures(old, {3: b'a', 1: b'b'})
    lab_common.write_textures(new, {3: b'a', 1: b'b'})
    lab_common.write_textures(new, {})
    assert old.sent == [3, 1] and new.sent == [[3, 1]]
    assert lab_common.supports(new, 'loadDat') is False, 'no capabilities: an older viewer'


def test_the_view_fetches_stored_colour_messages(tmp_path, monkeypatch):
    from core import config
    from flask import Flask
    from randall.routes.assistant_bp import assistant_bp
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    messages = [{'type': 'setVertexColors', 'objects': []}]
    update_id = continuity.keep_colours(messages)
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    client = app.test_client()
    assert client.get(f'/api/assistant/viewer-updates/{update_id}').get_json() == messages
    assert client.get('/api/assistant/viewer-updates/' + 'f' * 32).status_code == 404
    assert client.get('/api/assistant/viewer-updates/..%2Fsecrets').status_code == 404
    assert continuity.colours_file('not-an-id') is None
    for _ in range(3):
        continuity.keep_colours(messages)
    monkeypatch.setattr(continuity, 'KEEP_COLOURS', 2)
    continuity.keep_colours(messages)
    assert len(list((tmp_path / 'assistant' / 'viewer_updates').glob('*.json'))) == 2


def test_scenery_edits_load_into_the_running_renderer():
    class Viewer:
        camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}

        def __init__(self, fails=False):
            self.loaded, self.fails = [], fails

        def supports(self, message): return message == 'loadDat'

        def load_dat(self, path):
            if self.fails:
                raise ViewerSessionError('no')
            self.loaded.append(path)
    viewer = Viewer()
    assert stage_lab._scenery_viewer(viewer, 'edited.dat') is viewer and viewer.loaded == ['edited.dat']


def test_a_scenery_edit_loaded_in_place_drops_the_old_colour_evidence(lab2, monkeypatch):
    from shared import mod_files
    sid = lab2.open(stage(fmt=1))['session_id']
    item = stage_lab._sessions[sid]
    lab2.renderers[0].loaded.clear()         # the open's identify map reloads the file it looked at
    run('stage_lab', session_id=sid, action='color_sources')
    assert item['colour_scan'] is not None
    edited = stage(fmt=1, objects=3)

    def scene(action, file_id, **kwargs):
        return {'files': [mod_files.register(edited, 'GrNLa.dat', origin={'scene_instances': {'x': 1}})]}
    monkeypatch.setattr(stage_lab, 'run_scene', scene)
    run('stage_lab', session_id=sid, action='hide_objects', object_ids=['Group 0:0'])
    viewer = lab2.renderers[0]
    assert len(lab2.renderers) == 1 and len(viewer.loaded) == 1, 'loaded into the running renderer'
    assert item['colour_scan'] is None and 'colour_data' not in item
    listed = run('stage_lab', session_id=sid, action='color_sources')
    assert '0-2' in listed['colour_sources']['Group 0'], 'read from the new file (three objects)'


def test_struct_layout_used_by_the_fake_matches_the_scan():
    """The synthetic stage carries a light record the way dat_colours reads it (guards the fixtures above)."""
    data = stage(light=((10, 20, 30, 255), []))
    inv = dc.scan(data)
    assert inv.lights[0]['where'] == 'Group 0 light 0' and inv.lights[0]['rgba'] == (10, 20, 30, 255)
    assert struct.calcsize('>I') == 4
