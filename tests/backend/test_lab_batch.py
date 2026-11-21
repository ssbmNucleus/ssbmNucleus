"""The labs' `apply` batch, materials that replace, the inferred action and the three-view identify.

* One `apply` call takes edits of mixed kinds (recolor, recolor_vertex, set_material, material,
  reset_texture, ...), applies them in order with one render, one checkpoint and one viewer_update,
  reports every edit that failed with its reason, and is an error only when none applies
  (recolor/lab_common.apply_batch). Its edits are covered by resume and reset like any other.
* A material replaces the colour by default (alpha cut-outs kept; vertex colours that would tint it
  neutralised) and blends only with blend=mix (recolor/texture_material.compose_material).
* A lab call without `action` runs the one action its arguments name (tools.infer_action).
* identify without a camera returns three views in one picture with one legend and a merged table,
  and puts the renderer back exactly (recolor/texture_inspection._identify_views).

No renderer process runs: stand-ins serve textures, materials, frames and the DAT.
"""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from core import config
from randall.assistant import tools
from shared import mod_files
from randall.recolor import lab_common, skin_lab, stage_colours, stage_lab, texture_inspection as ti, texture_material
from shared.rendering import dat_colours as dc
from tests.backend import test_stage_colours as colours
from tests.backend.test_lab_resume import Clock, costume, stage  # noqa: F401  (fixtures)


def png(rgba, size=(8, 8)):
    out = io.BytesIO()
    Image.new('RGBA', size, rgba).save(out, format='PNG')
    return out.getvalue()


def pixels(raw):
    return np.array(Image.open(io.BytesIO(raw)).convert('RGBA'))


def run(tool, **args):
    return tools.execute(tools.prepare(tool, args))


def swatch(rgb=(250, 120, 180)):
    return mod_files.register(png((*rgb, 255), (16, 16)), 'Generated material.png')['file_id']


# --------------------------------------------------------------------------- #
# a stage renderer with textures, materials and vertex colours taken in place  #
# --------------------------------------------------------------------------- #
class MixedRenderer(colours.Renderer):
    """test_stage_colours' renderer (the DAT it was started on), with textures and materials it keeps and
    the protocol-2 in-place colour messages; it counts frames and texture batches."""
    def __init__(self, exe, port, dat_file, **kwargs):
        super().__init__(exe, port, dat_file, **kwargs)
        self.pixels = {0: png((200, 40, 40, 255))}
        self.materials = {('Group 0:0', 'diffuse'): '#808080ff'}
        self.grabs, self.batches, self.messages = 0, [], []

    def get_full_texture(self, index): return self.pixels[index]
    def update_texture(self, index, data): self.pixels[index] = data
    def update_textures(self, updated):
        self.batches.append(sorted(updated))
        self.pixels.update(updated)
    def grab_frame(self):
        self.grabs += 1
        return png((10, 10, 10, 255), (16, 16))
    def supports(self, message): return message in ('setVertexColors', 'setAnimationColors', 'setLightColors')
    def apply_colour_messages(self, messages): self.messages += messages

    def material_command(self, command):
        if command['type'] == 'setMaterialColors':
            for edit in command['edits']:
                self.materials[(edit['id'], edit['field'])] = edit['value']
        elif command['type'] == 'setMaterial':
            self.materials[(command['id'], command['field'])] = command['value']
        return {'success': True, 'materials': [{'id': mid, 'fields': [{'key': key, 'kind': 'color', 'value': value}]}
                                               for (mid, key), value in self.materials.items()]}


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    renderers = []

    def make(*args, **kwargs):
        renderers.append(MixedRenderer(*args, **kwargs))
        return renderers[-1]
    monkeypatch.setattr(stage_lab, 'ViewerSession', make)
    monkeypatch.setattr(stage_colours, 'ViewerSession', make)
    (tmp_path / 'skinlab_stages').mkdir()
    from shared.rendering import stage_ops
    monkeypatch.setattr(stage_ops, 'STAGE_DATS_DIR', tmp_path / 'skinlab_stages')
    (tmp_path / 'skinlab_stages' / 'GrNLa.dat').write_bytes(colours.stage(fmt=5))
    opened = run('stage_lab_open', stage_code='GrNLa')
    yield SimpleNamespace(renderers=renderers, sid=opened['session_id'], opened=opened)
    for key in list(stage_lab._sessions):
        stage_lab._sessions.pop(key)['viewer'].close()


def hue(rgb):
    from shared.rendering.palette import rgb_to_hsl
    return float(rgb_to_hsl(np.array([rgb[:3]], float))[0][0])


def vertex_colours(item, object_id):
    data = item['colour_data'][1]
    inv = dc.scan(data)
    return [c for v in inv.object(object_id).vertex for _, c in dc.vertex_values(inv.dat, v)]


def test_one_apply_mixes_kinds_in_order_with_one_render_checkpoint_and_viewer_update(mixed):
    viewer = mixed.renderers[0]
    grabs, uploads = viewer.grabs, len(viewer.batches)
    result = run('stage_lab', session_id=mixed.sid, action='apply', edits=[
        {'kind': 'recolor', 'texture_index': 0, 'set_hue': 120, 'set_saturation': 70},             # red -> green
        # only green pixels: matches because the edit before ran first
        {'kind': 'recolor', 'texture_index': 0, 'set_hue': 240, 'set_saturation': 70, 'mask': {'hue_min': 100, 'hue_max': 140}},
        {'kind': 'set_material', 'material_id': 'Group 0:0', 'field': 'diffuse', 'value': '#ff0000ff'},
        {'kind': 'recolor_vertex', 'material_ids': ['Group 0:1'], 'set_hue': 30, 'set_saturation': 80}])
    assert result['applied'] == 4 and result['failed'] == []
    assert abs(hue(pixels(viewer.pixels[0])[0, 0]) - 240) < 3, 'blue: the masked edit saw the first one'
    assert viewer.materials[('Group 0:0', 'diffuse')] == '#ff0000ff'
    assert result['changed_textures'] == [0] and result['changed_objects'] == ['Group 0:1']
    assert viewer.batches[uploads:] == [[0]], 'one texture upload'
    assert viewer.grabs - grabs == 1 and len(result['files']) == 1, 'one render'
    assert result['revision'] == 2 and result['checkpoint_file'], 'one checkpoint'
    update = result['viewer_update']
    assert [t['index'] for t in update['textures']] == [0]
    assert update['materials'] == [{'id': 'Group 0:0', 'field': 'diffuse', 'value': '#ff0000ff'}]
    assert update['colours']['types'] == ['setVertexColors'] and update['from'] == mixed.opened['checkpoint_file']['file_id']
    assert all(abs(hue(c) - 30) < 12 for c in vertex_colours(stage_lab._sessions[mixed.sid], 'Group 0:1')[:2])


def test_a_batch_applies_what_works_and_says_why_the_rest_failed(mixed):
    viewer = mixed.renderers[0]
    result = run('stage_lab', session_id=mixed.sid, action='apply', edits=[
        {'kind': 'recolor', 'texture_index': 0, 'set_hue': 200, 'set_saturation': 60},
        {'kind': 'recolor', 'texture_index': 99, 'set_hue': 10},
        {'kind': 'recolor_vertex', 'material_ids': ['Group 7:3'], 'set_hue': 10},
        {'kind': 'set_material', 'material_id': 'Group 0:0', 'field': 'diffuse', 'value': 'red'},
        {'kind': 'paint', 'texture_index': 0},
        {'kind': 'recolor', 'texture_index': 0, 'set_hue': 10, 'mask': {'hue_min': 300, 'hue_max': 310}}])
    assert result['applied'] == 1
    failed = {row['index']: row for row in result['failed']}
    assert sorted(failed) == [1, 2, 3, 4, 5]
    assert 'not a live texture index' in failed[1]['reason'] and failed[1]['kind'] == 'recolor'
    assert 'Group 7:3' in failed[2]['reason'] and failed[2]['kind'] == 'recolor_vertex'
    assert 'eight-digit' in failed[3]['reason']
    assert 'unknown kind' in failed[4]['reason']
    assert 'changed nothing' in failed[5]['reason']
    assert abs(hue(pixels(viewer.pixels[0])[0, 0]) - 200) < 3


def test_a_batch_where_nothing_applies_is_an_error_and_changes_nothing(mixed):
    viewer = mixed.renderers[0]
    before, uploads = dict(viewer.pixels), len(viewer.batches)
    result = run('stage_lab', session_id=mixed.sid, action='apply',
                 edits=[{'kind': 'recolor', 'texture_index': 42, 'set_hue': 1}, {'texture_indices': [0]}])
    assert result['error'].startswith('No edit applied.') and 'Edit 0:' in result['error'] and 'Edit 1:' in result['error']
    assert viewer.pixels == before and len(viewer.batches) == uploads
    assert 'checkpoint_file' not in result


def test_a_material_applies_in_the_batch_without_a_preview_and_shows_its_own_colours(mixed):
    viewer = mixed.renderers[0]
    item = stage_lab._sessions[mixed.sid]
    viewer.pixels[0] = png((40, 160, 40, 255))
    result = run('stage_lab', session_id=mixed.sid, action='apply', edits=[
        {'kind': 'material', 'texture_indices': [0], 'material_file_id': swatch(), 'keep_shading': 0}])
    assert result['applied'] == 1 and result['changed_textures'] == [0]
    assert pixels(viewer.pixels[0])[0, 0, :3].tolist() == [250, 120, 180], 'the swatch colour, no green left'
    # Object 0 draws the texture and multiplies it by purple vertex colours: they turn grey, lightness kept.
    assert result['vertex_neutralised'] == ['Group 0:0'] and 'vertex_neutralised' in result['note']
    greys = vertex_colours(item, 'Group 0:0')
    assert all(max(c[:3]) - min(c[:3]) <= 17 for c in greys)
    assert [c[3] for c in greys] == [c[3] for c in colours.PURPLE], 'alpha kept'
    assert 'texture_material_plans' not in item or not item['texture_material_plans'], 'no preview was needed'
    # keep_vertex_colours leaves them; an object a vertex edit of the batch names is never neutralised.
    kept = run('stage_lab', session_id=mixed.sid, action='apply', edits=[
        {'kind': 'reset_texture', 'texture_indices': [0]},
        {'kind': 'material', 'texture_indices': [0], 'material_file_id': swatch((10, 200, 220)), 'keep_vertex_colours': True}])
    assert kept['applied'] == 2 and 'vertex_neutralised' not in kept


def test_replace_is_the_default_keeps_cut_outs_and_mix_still_blends():
    texture = np.zeros((8, 8, 4), np.uint8)
    texture[..., :3] = (40, 160, 40)
    texture[..., 3] = 255
    texture[:, :3, 3] = 0                                           # a cut-out: three transparent columns
    viewer = SimpleNamespace(textures=[{'index': 0, 'width': 8, 'height': 8}])
    item = {'viewer': viewer}
    material = np.zeros((16, 16, 3), np.uint8) + np.array([250, 120, 180], np.uint8)
    controls = texture_material.default_controls(stage=True)
    replaced = texture_material.compose_material(item, True, {0: texture}, material, {**controls, 'keep_shading': 0})
    out = replaced['candidate'][0]
    assert replaced['controls']['blend'] == 'replace' and replaced['controls']['strength'] == 1.0
    assert (out[..., 3] == texture[..., 3]).all(), 'alpha untouched'
    assert (out[..., :3] == [250, 120, 180]).all(), 'the colour channel is the material, under the cut-out too'
    default = texture_material.compose_material(item, True, {0: texture}, material, dict(controls))
    assert default['controls']['keep_shading'] == texture_material.KEEP_SHADING == 0.25
    mixed_ = texture_material.compose_material(item, True, {0: texture}, material, {**controls, 'blend': 'mix'})
    blend = mixed_['candidate'][0]
    assert mixed_['controls']['strength'] == 0.75 and mixed_['controls']['keep_shading'] == 1.0
    assert blend[4, 4, 1] > 120 and (blend[:, :3, :3] == texture[:, :3, :3]).all(), 'mix keeps the green in'
    with pytest.raises(ValueError, match='blend must be'):
        texture_material.compose_material(item, True, {0: texture}, material, {**controls, 'blend': 'overlay'})


def test_skin_material_apply_takes_the_material_in_one_call(mixed):
    viewer = mixed.renderers[0]
    viewer.pixels[0] = png((40, 160, 40, 255))
    applied = run('skin_material', session_id=mixed.sid, action='apply', texture_indices=[0],
                  material_file_id=swatch(), keep_shading=0)
    assert applied['action'] == 'apply' and applied['updated_textures'] == [0] and 'error' not in applied
    assert pixels(viewer.pixels[0])[0, 0, :3].tolist() == [250, 120, 180]
    assert applied['controls']['blend'] == 'replace' and 'preview_id' in applied


# --------------------------------------------------------------------------- #
# the action a call names                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize('tool,args,action', [
    ('stage_lab', {'edits': [{'kind': 'recolor'}]}, 'apply'),
    ('skin_lab', {'edits': [{'kind': 'recolor'}]}, 'apply'),
    ('stage_lab', {'points': [[0.5, 0.5]]}, 'identify'),
    ('stage_lab', {'points': [[0.5, 0.5]], 'camera': {'rot_y': 10}}, 'identify'),
    ('stage_lab', {'texture_index': 3, 'hue_shift': 20, 'lightness_scale': 0.8}, 'recolor'),
    ('stage_lab', {'texture_index': 3}, 'texture'),
    ('stage_lab', {'texture_index': 3, 'file_id': 'x'}, 'replace_texture'),
    ('skin_lab', {'adjustments': [{'index': 0, 'hue_shift': 10}]}, 'recolor'),
    ('skin_lab', {'parts': {'cap': [1]}}, 'analyze_palette'),
    ('stage_lab', {'material_id': 'Group 1:0', 'field': 'diffuse', 'value': '#ff0000ff'}, 'set_material'),
    ('stage_lab', {'page': 1}, 'texture_sheet'),
    ('stage_lab', {'camera': {'rot_y': 10}}, 'camera'),
    ('stage_lab', {'frame': 30}, 'animation'),
    # ambiguous or unknown: the short "use one of" error stays
    ('stage_lab', {'edits': [], 'points': [[0, 0]]}, None),
    ('stage_lab', {'texture_indices': [1, 2]}, None),
    ('skin_lab', {'texture_index': 3, 'hue_shift': 20}, None),
    ('skin_lab', {'frame': 30}, None),
    ('stage_lab', {'material_id': 'Group 1:0', 'field': 'diffuse'}, None),
    ('generate_material', {'prompts': ['x']}, None),
])
def test_the_inferred_action_table(tool, args, action):
    schema = next(s['function']['parameters'] for s in tools.SCHEMAS if s['function']['name'] == tool)
    assert tools.infer_action(tool, {'session_id': 's', **args}, (schema['properties'].get('action') or {}).get('enum') or ()) == action


def test_a_call_without_action_runs_the_one_it_names_and_says_so(mixed):
    prepared = tools.prepare('stage_lab', {'session_id': mixed.sid, 'edits': [
        {'kind': 'recolor', 'texture_index': 0, 'set_hue': 60, 'set_saturation': 50}]})
    assert json.loads(prepared.arguments)['action'] == 'apply'
    result = tools.execute(prepared)
    assert result['action_inferred'] == 'apply' and result['applied'] == 1 and result['action'] == 'apply'
    with pytest.raises(ValueError, match="'action' is required: use one of"):
        tools.prepare('stage_lab', {'session_id': mixed.sid, 'texture_indices': [0]})


def test_a_single_action_takes_edits_that_carry_its_own_kind(mixed):
    result = run('stage_lab', session_id=mixed.sid, action='recolor',
                 edits=[{'kind': 'recolor', 'texture_index': 0, 'set_hue': 60, 'set_saturation': 50}])
    assert result['changed'] == [0]
    other = run('stage_lab', session_id=mixed.sid, action='recolor',
                edits=[{'kind': 'material', 'texture_indices': [0], 'material_file_id': 'x'}])
    assert 'action=apply' in other['error']


# --------------------------------------------------------------------------- #
# resume and reset cover a batch                                               #
# --------------------------------------------------------------------------- #
def test_a_stage_batch_survives_a_resume_and_resets_to_the_original(stage, monkeypatch):
    clock = Clock(monkeypatch)
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    first = stage.renderers[0]
    original = pixels(first.pixels[0])
    applied = run('stage_lab', session_id=sid, action='apply', edits=[
        {'kind': 'recolor', 'texture_index': 0, 'set_hue': 120, 'set_saturation': 60},
        {'kind': 'set_material', 'material_id': 'Group 1:0', 'field': 'diffuse', 'value': '#00ff00ff'}])
    assert applied['applied'] == 2
    edited = pixels(first.pixels[0])
    clock.advance(lab_common.IDLE_SECONDS + 1)
    stage_lab._expire(sid)
    assert sid not in stage_lab._sessions
    reset = run('stage_lab', session_id=sid, action='apply', edits=[{'kind': 'reset_texture', 'texture_indices': [0]}])
    second = stage.renderers[-1]
    assert second is not first and (pixels(second.pixels[0]) == original).all() and not (edited == original).all()
    assert reset['restored_textures'] == [0]
    run('stage_lab', session_id=sid, action='reset_material', material_id='Group 1:0', field='diffuse')
    assert second.material_colors[('Group 1:0', 'diffuse')] == '#808080ff'


def test_a_costume_batch_keeps_its_originals_through_a_resume_for_reset_texture(costume, monkeypatch):
    clock = Clock(monkeypatch)
    sid = run('skin_lab_open', file_id=costume.source['file_id'])['session_id']
    first = costume.renderers[0]
    original = pixels(first.pixels[1])
    applied = run('skin_lab', session_id=sid, action='apply', edits=[
        {'kind': 'recolor', 'texture_index': 1, 'set_hue': 0, 'set_saturation': 80},
        {'kind': 'material', 'texture_indices': [2], 'material_file_id': swatch(), 'keep_shading': 0, 'mode': 'tile',
         'minimum_size': 1}])
    assert applied['applied'] == 2 and applied['changed_textures'] == [1, 2] and applied['checkpoint_file']
    assert pixels(first.pixels[2])[0, 0, :3].tolist() == [250, 120, 180]
    clock.advance(lab_common.IDLE_SECONDS + 1)
    skin_lab._expire(sid)
    assert sid not in skin_lab._sessions
    reset = run('skin_lab', session_id=sid, action='reset_texture', texture_indices=[1])
    second = costume.renderers[-1]
    assert second is not first and reset['restored'] == [1] and (pixels(second.pixels[1]) == original).all()
    assert run('skin_lab', session_id=sid, action='reset_texture', texture_indices=[0])['error'].startswith('Textures [0]')


# --------------------------------------------------------------------------- #
# three views in one picture                                                   #
# --------------------------------------------------------------------------- #
class ViewRenderer:
    """A small world seen through a camera: zoomed about the frame's centre by scale, shifted 6 px a unit
    of x/y pan whatever the zoom (as the real renderer), tilted down by rot_x (a top shows), turned by
    rot_y (mirrored past 90 degrees). Every texture draws as its own pixel colour. It starts panned, as the
    real one does (Mario at y 8.2): a zoom then pivots off the frame's centre unless the pan grows with it."""
    PAN = 6.0
    HOME = {'rotX': 0.0, 'rotY': 0.0, 'scale': 1.0, 'x': -2.0, 'y': 2.0}

    def __init__(self, figure=False):
        self.figure = figure
        colours_ = [(60, 60, 200), (60, 160, 60), (200, 60, 60), (200, 200, 60), (160, 60, 160)]
        self.textures = [{'index': i, 'name': f'Texture_{i}', 'width': 8, 'height': 8} for i in range(5)]
        self.pixels = {i: png((*c, 255)) for i, c in enumerate(colours_)}
        self.camera = dict(self.HOME)
        self.grabs = 0

    def colour(self, index): return tuple(int(v) for v in pixels(self.pixels[index])[0, 0, :3])
    def get_full_texture(self, index): return self.pixels[index]
    def update_texture(self, index, data): self.pixels[index] = data
    def export_dat(self): raise ValueError('no file')
    def material_command(self, command): return {'success': True, 'materials': []}

    def set_camera(self, rot_x=None, rot_y=None, scale=None, x=None, y=None):
        for key, value in (('rotX', rot_x), ('rotY', rot_y), ('scale', scale), ('x', x), ('y', y)):
            if value is not None:
                self.camera[key] = float(value)
        return dict(self.camera)

    def world(self):
        w, h = 256, 192
        image = Image.new('RGB', (w, h), (0, 0, 0) if self.figure else self.colour(0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        if self.figure:                           # a standing figure: body (1), head (2) with an eye (3)
            draw.rectangle((110, 70, 146, 170), fill=self.colour(1))
            draw.rectangle((112, 30, 144, 66), fill=self.colour(2))
            draw.rectangle((120, 40, 126, 46), fill=self.colour(3))
        else:
            draw.rectangle((0, 140, w, h), fill=self.colour(1))                    # the ground
            draw.rectangle((60, 90, 72, 140), fill=self.colour(1))                 # a post
            if self.camera['rotX'] > 10:
                draw.rectangle((0, 128, w, 140), fill=self.colour(4))              # its top, seen from above
            for left in (190, 202, 214):                                           # small scenery
                draw.rectangle((left, 130, left + 5, 139), fill=self.colour(2 if left != 202 else 3))
        if abs(self.camera['rotY']) > 90:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        # Shading, as a render has: darker specks keep each colour's id and give a pan something to follow.
        rgb = np.array(image, np.float32)
        rng = np.random.default_rng(7)
        rgb *= np.where(rng.random(rgb.shape[:2]) < 0.15, 0.8, 1.0)[..., None]
        return Image.fromarray(rgb.astype(np.uint8))

    def grab_frame(self):
        self.grabs += 1
        image = self.world()
        k, cx, cy = self.camera['scale'], 128.0, 96.0
        sx, sy = self.camera['x'] * self.PAN, self.camera['y'] * self.PAN
        # screen = centre + k * (world - centre) + shift  ->  world = centre + (screen - centre - shift) / k
        data = (1 / k, 0, cx - (cx + sx) / k, 0, 1 / k, cy - (cy + sy) / k)
        frame = image.transform(image.size, Image.Transform.AFFINE, data, Image.Resampling.NEAREST,
                                fillcolor=(0, 0, 0) if self.figure else self.colour(0))
        out = io.BytesIO()
        frame.save(out, format='PNG')
        return out.getvalue()


def test_identify_without_a_camera_shows_three_views_with_one_legend_and_puts_everything_back(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    viewer = ViewRenderer()
    item = {'viewer': viewer}
    before = dict(viewer.pixels)
    result = ti.identify(item, views='stage', name='Stage identify map.png')
    assert result['views'] == ['game camera', 'raised three-quarter', 'zoom on small scenery']
    assert len(result['files']) == 1, 'one picture'
    rows = {row['id']: row for row in result['surfaces']}
    # The top is only seen from the raised view; the small scenery is biggest in the zoom.
    assert rows[4]['views'][0] == 0 and rows[4]['views'][1] > 0
    assert rows[3]['views'][2] > 4 * rows[3]['views'][0] > 0
    assert 4 in result['major'] and 0 in result['major'] and 1 in result['major']
    assert 2 not in result.get('too_small', []) and 3 not in result.get('too_small', []), 'numbered in the zoom'
    assert item['pan_scale'][1] == pytest.approx(ViewRenderer.PAN, rel=0.05), 'the pan was measured'
    # Everything back exactly: textures and camera.
    assert viewer.pixels == before and viewer.camera == ViewRenderer.HOME
    path, _ = mod_files.resolve(result['files'][0]['file_id'])
    with Image.open(path) as picture:
        assert picture.width == 1024 and picture.height <= 1024
    assert 'same colour and number in every view' in result['note']
    # A point on the picture says what is there; a camera still gives one view.
    looked = ti.identify(item, views='stage', points=[[rows[1]['box'][0] + 0.01, rows[1]['box'][3] - 0.01]])
    assert looked['at'][0]['id'] == 1
    one = ti.identify(item, views='stage', camera={'rot_y': 10})
    assert 'views' not in one and one['surfaces'][0]['id'] == 0


def test_a_costume_gets_front_back_and_a_head_zoom(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    viewer = ViewRenderer(figure=True)
    item = {'viewer': viewer}
    result = ti.identify(item, views='costume', name='Skin identify map.png')
    assert result['views'] == ['front', 'back', 'head zoom']
    rows = {row['id']: row for row in result['surfaces']}
    assert rows[2]['views'][2] > 3 * rows[2]['views'][0], 'the head fills the zoom'
    assert rows[3]['views'][2] > 0 and 3 not in result.get('too_small', []), 'the eye gets its number there'
    assert viewer.camera == ViewRenderer.HOME


def test_the_busiest_window_and_the_head_window():
    ids = np.full((192, 256), 0, np.int32)
    ids[140:] = 1
    for n, left in enumerate((200, 210, 220)):
        ids[130:139, left:left + 5] = 2 + n
    left, top, width, height = ti._busiest(ids, zoom=2.5)
    assert left <= 200 and left + width >= 225 and top <= 130 and top + height >= 139
    figure = np.full((192, 256), -1, np.int32)
    figure[70:170, 110:146] = 1
    figure[30:66, 112:144] = 2
    left, top, width, height = ti._head(figure)
    assert top <= 30 and top + height <= 110 and left <= 112 and left + width >= 144
