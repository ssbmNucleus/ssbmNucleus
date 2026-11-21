import io
import json
import struct
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from randall.assistant import engine, live_runs, store, tools
from shared import mod_files
from randall.recolor import skin_lab as lab
from randall.assistant.vision import tool_images
from core import config


def png(color):
    out = io.BytesIO()
    Image.new('RGBA', (16, 16), color).save(out, format='PNG')
    return out.getvalue()


def dat():
    name = b'PlyFox5K_Share_joint\0'
    return struct.pack('>5I', 72 + len(name), 32, 0, 1, 0) + bytes(12) + bytes(32) + struct.pack('>2I', 0, 0) + name


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path)
    class Viewer:
        textures = [{'index': i, 'width': 16, 'height': 16} for i in range(3)]
        camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}
        def __init__(self):
            self.pixels = {0: png((220, 30, 30, 200)), 1: png('blue'), 2: png('gray')}
            self.updates = []
            self.closed = False
        def material_command(self, command): return {'materials': []}
        def get_full_texture(self, i): return self.pixels[i]
        def update_texture(self, i, value): self.pixels[i] = value; self.updates.append(i)
        def grab_frame(self): return self.pixels[0]
        def export_dat(self): return dat()
        def close(self): self.closed = True
        def alive(self): return not self.closed
    viewer = Viewer()
    source = mod_files.register(dat(), 'PlFxNr.dat', origin={'character': 'Fox', 'member': 'PlFxNr.dat'})
    info = mod_files.resolve(source['file_id'])[1]
    lab._sessions['test'] = {'viewer': viewer, 'scratch': SimpleNamespace(cleanup=lambda: None),
                            'used': time.monotonic(), 'palette': None, 'edited': False, 'source': info}
    yield viewer, source
    if 'test' in lab._sessions: lab.skin_lab('test', 'close')


def test_recolor_is_absolute_scoped_and_resettable(session):
    viewer, source = session
    original = dict(viewer.pixels)
    result = lab.skin_lab('test', 'analyze_palette', texture_indices=[0], max_groups=1)
    assert len(result['groups']) == 1
    args = [{'index': 0, 'hue_shift': 120}]
    lab.skin_lab('test', 'recolor', adjustments=args)
    edited = viewer.pixels[0]
    assert edited != original[0]
    pixels = np.array(Image.open(io.BytesIO(edited)))
    assert pixels[0, 0, 1] > pixels[0, 0, 0] and pixels[0, 0, 3] == 200
    lab.skin_lab('test', 'recolor', adjustments=args)
    assert viewer.pixels[0] == edited  # no accumulated hue shift
    assert viewer.pixels[1] == original[1] and viewer.pixels[2] == original[2]
    lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'hue_shift': 0}])
    assert viewer.pixels[0] == original[0]
    lab.skin_lab('test', 'recolor', adjustments=args)
    lab.skin_lab('test', 'reset_palette')
    assert viewer.pixels == original
    exported = lab.skin_lab('test', 'export')['files'][0]
    assert exported['file_id'] != source['file_id']
    assert mod_files.resolve(source['file_id'])[0].read_bytes() == dat()
    assert mod_files.resolve(exported['file_id'])[1]['edited']
    assert mod_files.resolve(exported['file_id'])[1]['origin']['member'] == 'PlFxNr.dat'


def test_material_only_edit_is_exportable_and_preview_is_view_only(session):
    viewer, source = session
    from tests.backend.test_assistant_materials import Viewer
    viewer.material_command = Viewer().material_command
    lab.skin_lab('test', 'preview_base_colors', enabled=True)
    assert not lab._sessions['test']['edited']
    result = lab.skin_lab('test', 'set_material', material_id='Group 0:2', field='diffuse', value='#22cc88ff')
    assert result['files'] and lab._sessions['test']['edited']
    exported = lab.skin_lab('test', 'export')['files'][0]
    assert exported['file_id'] != source['file_id']
    assert mod_files.resolve(exported['file_id'])[1]['edited']
    assert mod_files.resolve(source['file_id'])[0].read_bytes() == dat()


def test_palette_includes_materials_and_can_scope_or_restore_them(session):
    viewer, _ = session
    color = '#ff000044'
    commands = []
    def material_command(command):
        nonlocal color
        commands.append(command['type'])
        if command['type'] == 'setMaterialColors': color = command['edits'][0]['value']
        return {'materials': [{'id': 'mesh', 'fields': [{'key': 'diffuse', 'kind': 'color', 'value': color}]}]}
    viewer.material_command = material_command
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    assert not commands, 'Selected textures must not implicitly recolor all materials'
    result = lab.skin_lab('test', 'analyze_palette', texture_indices=[], include_materials=True)
    assert result['material_colors'] == 1 and result['texture_indices'] == []
    lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'hue_shift': 120}])
    assert color == '#00ff0044' and not viewer.updates
    lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'hue_shift': 120}])
    assert color == '#00ff0044'
    lab.skin_lab('test', 'reset_palette')
    assert color == '#ff000044'
    assert lab.skin_lab('test', 'analyze_palette')['material_colors'] == 1


@pytest.mark.parametrize('adjustments', [[{'index': 2}], [{'index': 0, 'hue_shift': float('nan')}],
    [{'index': 0, 'saturation_shift': 101}], [{'index': True}], [{'index': 0, 'path': '../x'}]])
def test_invalid_adjustments_do_not_write(session, adjustments):
    viewer, _ = session
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    with pytest.raises(ValueError): lab.skin_lab('test', 'recolor', adjustments=adjustments)
    assert not viewer.updates


def test_model_receives_real_bounded_images_only_from_lab_tools(session):
    preview = lab.skin_lab('test', 'frame')
    content = tool_images('skin_lab', preview)
    assert content[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert tool_images('search_vault', preview) == []
    assert tool_images('skin_lab', {'files': [{'extension': '.png', 'file_id': '../secret'}]})[0]['type'] == 'text'


def test_open_uses_private_copy_and_close_releases_it(session, monkeypatch):
    from core import viewer_tools
    fake, source = session
    opened = []
    def factory(exe, port, path, **kwargs):
        opened.append(path)
        assert path.read_bytes() == dat()
        assert path != mod_files.resolve(source['file_id'])[0]
        return fake
    monkeypatch.setattr(lab, 'ViewerSession', factory)
    for name in ('find_scene_file', 'find_aj_file', 'find_fighter_data_file'):
        monkeypatch.setattr(viewer_tools, name, lambda character: None)
    monkeypatch.setattr(viewer_tools, 'find_available_port', lambda: 12345)
    result = lab.skin_lab_open(source['file_id'])
    assert result['files'][0]['extension'] == '.png'
    lab.skin_lab(result['session_id'], 'close')
    assert not opened[0].exists() and fake.closed
    assert mod_files.resolve(source['file_id'])[0].exists()
    with pytest.raises(ValueError): lab.skin_lab_open('../unrelated.dat')


def test_images_follow_all_tool_responses_and_are_not_persisted(vault, monkeypatch):
    count = 0
    def provider(messages, *args):
        nonlocal count
        count += 1
        if count == 1:
            calls = [{'id': str(i), 'function': {'name': 'skin_lab', 'arguments': '{}'}} for i in range(2)]
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}
        else:
            assert [m['role'] for m in messages[-3:]] == ['tool', 'tool', 'user']
            assert messages[-1]['content'][0]['type'] == 'image_url'
            yield {'type': 'completion', 'message': {'role': 'assistant', 'content': 'Checked.'}}
    monkeypatch.setattr(engine, '_provider', provider)
    monkeypatch.setattr(tools, 'prepare', lambda *a: SimpleNamespace(name='skin_lab', arguments='{}', policy='automatic'))
    monkeypatch.setattr(tools, 'execute', lambda *a, **kw: {'files': []})
    monkeypatch.setattr(engine, 'tool_images', lambda *a: [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,test'}}])
    run = engine.start(None, 'Recolor this skin', {}, request_key='test')
    list(live_runs.stream(run))
    assert count == 2 and run.answer['status'] == 'done'
    assert 'data:image' not in json.dumps(store.get(run.chat_id))


def test_a_shared_texture_listed_under_a_part_is_still_only_borrowed(session, monkeypatch):
    """Measured: GLM read masked_parts and put Mario's emblem texture straight
    into `cap`, so the whole emblem -- its red M included -- went black with the
    cap. A shared texture is borrowed through the surrounding-field rule however
    it is listed; recolouring the M means naming the emblem as its own part."""
    from shared.rendering import part_map
    viewer, _ = session
    emblem = np.tile(np.array([200, 30, 30, 255], np.uint8), (32, 32, 1))   # cap red to the edges
    yy, xx = np.mgrid[:32, :32]
    emblem[np.hypot(yy - 15.5, xx - 15.5) <= 10] = (235, 235, 235, 255)      # the white disc
    emblem[12:20, 13:19] = (200, 30, 30, 255)                                  # the red M inside it
    out = io.BytesIO(); Image.fromarray(emblem).save(out, format='PNG')
    viewer.pixels[1] = out.getvalue()
    monkeypatch.setattr(part_map, 'describe', lambda textures, origin=None, geometry=None: {
        'parts': {'cap': [0], 'cap emblem': [1]}, 'masked_parts': {'cap': [1]}})
    result = lab.skin_lab('test', 'analyze_palette', parts={'cap': [0, 1]})    # the model's exact call
    assert result['borrowed_textures'] == {'cap': [1]}
    cap = [g['index'] for g in result['groups'] if g['part'] == 'cap' and g.get('kind') != 'neutral']
    lab.skin_lab('test', 'recolor', adjustments=[
        {'index': g, 'set_hue': 0, 'set_saturation': 0, 'lightness_scale': 0.1} for g in cap])
    after = np.array(Image.open(io.BytesIO(viewer.pixels[1])).convert('RGBA'))
    assert after[0, 0, :3].max() < 40, 'the field around the emblem follows the cap'
    assert tuple(after[15, 15, :3]) == (200, 30, 30), 'the M keeps its red'


def test_camera_settings_sent_at_the_top_level_are_moved_into_camera():
    from randall.assistant import tools
    prepared = tools.prepare('skin_lab', {'session_id': 'a' * 32, 'action': 'camera', 'rot_y': 90, 'scale': 1.5})
    args = json.loads(prepared.arguments)
    assert args['camera'] == {'rot_y': 90, 'scale': 1.5} and 'rot_y' not in args
    # Merged with a camera that is already there, never overwriting its keys.
    prepared = tools.prepare('skin_lab', {'session_id': 'a' * 32, 'action': 'camera',
                                          'camera': {'rot_x': 10}, 'rot_y': 45})
    assert json.loads(prepared.arguments)['camera'] == {'rot_x': 10, 'rot_y': 45}
    # A key that belongs nowhere is still rejected with a reason.
    with pytest.raises(ValueError, match="'spin' is not a parameter"):
        tools.prepare('skin_lab', {'session_id': 'a' * 32, 'action': 'camera', 'spin': 3})


def test_a_set_hue_with_a_saturation_shift_starts_from_the_group_average(session, monkeypatch):
    groups = lab.skin_lab('test', 'analyze_palette', texture_indices=[0])['groups']
    hued = next(g for g in groups if g.get('centerHue') is not None)
    applied = []
    real = lab.palette.apply_adjustments
    monkeypatch.setattr(lab.palette, 'apply_adjustments',
                        lambda original, pixel_map, values: applied.append(dict(values)) or real(original, pixel_map, values))
    lab.skin_lab('test', 'recolor', adjustments=[{'index': hued['index'], 'set_hue': 265, 'saturation_shift': 10}])
    hue, saturation, kind, _ = applied[-1][hued['index']]
    assert (hue, kind) == (265, 'set')
    assert saturation == pytest.approx(min(100, hued['avgSaturation'] + 10))
    with pytest.raises(ValueError, match='not both'):
        lab.skin_lab('test', 'recolor', adjustments=[{'index': hued['index'], 'set_hue': 265, 'hue_shift': 10}])


def test_frame_with_a_camera_turns_the_camera_instead_of_ignoring_it(session, monkeypatch):
    viewer, _ = session
    seen = {}
    monkeypatch.setattr(viewer, 'set_camera', lambda **kw: seen.update(kw), raising=False)
    monkeypatch.setattr(viewer, 'camera', seen, raising=False)
    lab.skin_lab('test', 'frame', camera={'rot_x': 8, 'rot_y': 180})
    assert seen == {'rot_x': 8, 'rot_y': 180}
    seen.clear()
    lab.skin_lab('test', 'frame')
    assert seen == {}, 'a plain frame leaves the camera alone'


def _recorded_adjustments(monkeypatch):
    applied = []
    real = lab.palette.apply_adjustments
    monkeypatch.setattr(lab.palette, 'apply_adjustments',
                        lambda original, pixel_map, values: applied.append(dict(values)) or real(original, pixel_map, values))
    return applied


def test_one_adjustment_without_an_index_covers_every_group(session, monkeypatch):
    groups = lab.skin_lab('test', 'analyze_palette', texture_indices=[0, 1, 2])['groups']
    applied = _recorded_adjustments(monkeypatch)
    lab.skin_lab('test', 'recolor', adjustments=[{'set_hue': 220, 'set_saturation': 20, 'lightness_scale': 0.4}])
    assert set(applied[-1]) == set(range(len(groups)))
    # Limited to the groups actually present in the named textures.
    maps = lab._sessions['test']['palette']['maps']
    only = {int(g) for g in np.unique(maps[0]) if g != 255}
    lab.skin_lab('test', 'recolor', texture_indices=[0], adjustments=[{'set_hue': 300, 'set_saturation': 80}])
    assert {g for g, v in applied[-1].items() if v[0] == 300} == only
    with pytest.raises(ValueError, match='ONE adjustment without'):
        lab.skin_lab('test', 'recolor', adjustments=[{'set_hue': 1}, {'index': 0, 'hue_shift': 5}])


def test_zero_shifts_never_conflict_with_a_set(session, monkeypatch):
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    applied = _recorded_adjustments(monkeypatch)
    lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'set_hue': 205, 'set_saturation': 12,
                                                    'hue_shift': 0, 'saturation_shift': 0}])
    assert applied[-1][0][:3] == (205, 12, 'set')


def test_a_hue_shift_past_half_a_turn_wraps_around_the_circle(session, monkeypatch):
    lab.skin_lab('test', 'analyze_palette', texture_indices=[0])
    applied = _recorded_adjustments(monkeypatch)
    lab.skin_lab('test', 'recolor', adjustments=[{'index': 0, 'hue_shift': 242}])
    assert applied[-1][0][0] == -118
