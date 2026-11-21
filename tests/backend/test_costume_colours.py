"""Costume colours outside textures (randall/recolor/costume_colours.py over model_colours.py and
shared/rendering/dat_colours.py): where each part's colour comes from on a Skin Lab open, vertex
colour and colour animation edits named by part or material id, the scope gate when a store
cannot be separated, reset, resume, and the saved costume carrying the edit.

The costumes are small synthetic HSD archives built here (one `_joint` root, DOBJs with
POBJ vertex colours, optional textures and a `_matanim_joint` colour animation), with
test_stage_colours' builder. No renderer runs: the stand-in serves the file it was started
on, as the real one exports it, and lists its textures as the renderer names them.
"""
import json
import struct
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from randall.assistant import continuity, tools
from shared import mod_files
from randall.recolor import costume_colours, skin_lab
from shared.rendering import dat_colours as dc
from shared.rendering import lowpoly
from tests.backend.test_stage_colours import Builder, colour_bytes, hue, keys, png

RED, BLUE = (200, 30, 30, 255), (30, 60, 200, 255)
SHIRT_AND_OVERALLS = [RED, BLUE, RED]


# --------------------------------------------------------------------------- #
# a synthetic costume                                                          #
# --------------------------------------------------------------------------- #
def costume(specs, animated=None, shared_aobj=False):
    """A costume DAT: one DOBJ per spec on the root joint, each a triangle with CLR0 colours.

    spec keys: `colours` (three RGBA), `texture` (an image number: objects naming the same one
    draw the same image), `kind` 'direct' | 'index', `shared_array` / `shared_desc` (a key:
    index colours in one array, or one vertex descriptor list, for every spec with that key),
    `flags` (render flags, default vertex source), `texture_format` (GX format of its image: I8,
    a greyscale one, by default; 6 is RGBA8, a colour one). `animated`: DOBJ indices whose material
    diffuse R/G/B animate (white -> dark red over 100 frames, as Yoshi's egg does); with
    `shared_aobj` they all read ONE AOBJ.
    """
    b = Builder()
    joint = b.alloc(0x40)
    positions = b.blob(struct.pack('>9f', 0, 0, 0, 10, 0, 0, 0, 10, 0))
    images, arrays, descs = {}, {}, {}
    previous = joint + 0x10
    for spec in specs:
        dobj, mobj, material, pobj = b.alloc(0x10), b.alloc(0x18), b.alloc(0x14), b.alloc(0x18)
        b.ptr(previous, dobj)
        previous = dobj + 0x04
        b.ptr(dobj + 0x08, mobj)
        b.ptr(dobj + 0x0C, pobj)
        texture = spec.get('texture')
        b.put(mobj + 0x04, 'I', spec.get('flags', 0x2) | (0x10 if texture is not None else 0))
        b.ptr(mobj + 0x0C, material)
        b.put(material, '12Bff', 128, 128, 128, 255, 255, 255, 255, 255, 255, 255, 255, 255, 1.0, 50.0)
        if texture is not None:
            tobj = b.alloc(0x5C)
            b.ptr(mobj + 0x08, tobj)
            b.put(tobj + 0x40, 'I', 4 << 16)                          # colour map MODULATE
            if texture not in images:
                fmt = spec.get('texture_format', 1)
                images[texture] = b.alloc(0x18)
                b.ptr(images[texture], b.blob(bytes((texture * 7 + i) % 256 for i in range(64 * (4 if fmt == 6 else 1)))))
                b.put(images[texture] + 4, 'HHI', 8, 8, fmt)           # 8x8
            b.ptr(tobj + 0x4C, images[texture])
        colours, kind = spec.get('colours', SHIRT_AND_OVERALLS), spec.get('kind', 'direct')
        key = spec.get('shared_desc')
        if key in descs:
            attrs = descs[key]
        else:
            attrs = b.alloc(0x18 * 3)
            b.put(attrs, 'IIIIBBH', 9, 2, 1, 4, 0, 0, 12)
            b.ptr(attrs + 0x14, positions)
            b.put(attrs + 0x18, 'IIIIBBH', 11, 1 if kind == 'direct' else 2, 1, 1, 0, 0, 3)
            if kind == 'index':
                array = arrays.get(spec.get('shared_array'))
                if array is None:
                    array = b.blob(b''.join(colour_bytes(1, c) for c in colours))
                    if spec.get('shared_array'):
                        arrays[spec['shared_array']] = array
                b.ptr(attrs + 0x18 + 0x14, array)
            b.put(attrs + 0x30, 'I', 0xFF)
            if key:
                descs[key] = attrs
        b.ptr(pobj + 0x08, attrs)
        stream = bytearray(b'\x90' + struct.pack('>H', 3))
        for v in range(3):
            stream += bytes((v,)) + (colour_bytes(1, colours[v]) if kind == 'direct' else bytes((v,)))
        stream += bytes(-len(stream) % 32)
        b.put(pobj + 0x0E, 'H', len(stream) // 32)
        b.ptr(pobj + 0x10, b.blob(bytes(stream)))
    roots = [('PlyFox5K_Share_joint', joint)]
    if animated:
        node = b.alloc(0x0C)
        shared, last = None, node + 0x08
        for index in range(max(animated) + 1):
            matanim = b.alloc(0x10)
            b.ptr(last, matanim)
            last = matanim
            if index not in animated:
                continue
            if shared is None or not shared_aobj:
                aobj = b.alloc(0x10)
                b.put(aobj, 'If', 0, 100.0)
                descriptor = aobj + 0x08
                for kind_, values in ((4, [1.0, 0.31]), (5, [1.0, 0.16]), (6, [1.0, 0.16])):
                    raw = dc.encode_keys(keys(2, [0, 100], values), 0x88, 0)
                    desc = b.alloc(0x14)
                    b.ptr(descriptor, desc)
                    descriptor = desc
                    b.put(desc + 0x04, 'IfBBB', len(raw), 0.0, kind_, 0x88, 0)
                    b.ptr(desc + 0x10, b.blob(raw))
                shared = aobj
            b.ptr(matanim + 0x04, shared)
        roots.append(('PlyFox5K_Share_matanim_joint', node))
    return b.build(roots)


class Renderer:
    """The live renderer's protocol over the file it was started on (exportDat returns it); its
    textures are listed as HSDRawViewer lists a costume's (Texture_<n>, first use of an image)."""
    camera = {'rotX': 0, 'rotY': 0, 'scale': 1, 'x': 0, 'y': 0}

    def __init__(self, exe=None, port=None, dat_file=None, **kwargs):
        self.data = Path(dat_file).read_bytes()
        self.kwargs = kwargs
        names = sorted({t['name'] for o in dc.scan(self.data).objects for t in o.textures if t.get('name')},
                       key=lambda name: int(name.split('_')[1]))
        self.textures = [{'index': int(name.split('_')[1]), 'name': name, 'width': 8, 'height': 8,
                          'matAnim': False, 'animates': -1, 'extra': False} for name in names]
        self.closed = False

    def get_full_texture(self, index): return png((90, 90, 90, 255))
    def grab_frame(self): return png((10, 10, 10, 255), (16, 16))
    def export_dat(self): return self.data
    def get_uv_layout(self): return []
    def set_camera(self, **kwargs): return dict(self.camera)
    def alive(self): return not self.closed
    def close(self): self.closed = True
    def update_texture(self, index, data): pass
    def material_command(self, command): return {'success': True, 'materials': []}


def run(tool, **args):
    return tools.execute(tools.prepare(tool, args))


@pytest.fixture
def lab(vault, monkeypatch, tmp_path):
    """A Skin Lab whose renderers are stand-ins; `parts` (live texture index lists) is the part map
    and `hidden` ({DObj index: kind}) the fighter's model tables."""
    from core import viewer_tools
    from shared.rendering import part_map
    renderers, state = [], SimpleNamespace(parts=None, hidden={})

    def make(*args, **kwargs):
        renderers.append(Renderer(*args, **kwargs))
        return renderers[-1]
    monkeypatch.setattr(skin_lab, 'ViewerSession', make)
    for name in ('find_scene_file', 'find_aj_file'):
        monkeypatch.setattr(viewer_tools, name, lambda character: None)
    fighter = tmp_path / 'PlFx.dat'
    fighter.write_bytes(b'')
    monkeypatch.setattr(viewer_tools, 'find_fighter_data_file', lambda character: fighter)
    monkeypatch.setattr(viewer_tools, 'find_available_port', lambda: 12345)
    monkeypatch.setattr(lowpoly, 'hidden_objects', lambda path, slot: dict(state.hidden))
    monkeypatch.setattr(part_map, 'describe', lambda textures, origin=None, geometry=None: (
        {'parts': dict(state.parts), 'source': 'vanilla', 'note': 'test map'} if state.parts else None))

    def open_(data):
        source = mod_files.register(data, 'PlFxNr.dat', origin={'character': 'Fox', 'member': 'PlFxNr.dat',
                                                                 'costume_code': 'PlFxNr'})
        opened = run('skin_lab_open', file_id=source['file_id'])
        assert 'error' not in opened, opened
        return opened
    yield SimpleNamespace(renderers=renderers, state=state, open=open_)
    with skin_lab._lock:
        for key in list(skin_lab._sessions):
            skin_lab._close(key)


def colours(data, object_id):
    inv = dc.scan(data)
    return [c for v in inv.object(object_id).vertex for _, c in dc.vertex_values(inv.dat, v)]


def green(rgba):
    return abs(hue(rgba) - 120) < 15


# --------------------------------------------------------------------------- #
# evidence                                                                     #
# --------------------------------------------------------------------------- #
def test_a_costume_is_read_with_the_renderers_own_names():
    data = costume([{'texture': 0}, {}, {'texture': 1, 'texture_format': 6, 'colours': [(255, 255, 255, 255)] * 3}],
                   animated=[1])
    inv = dc.scan(data)
    assert [o.id for o in inv.objects] == ['Model:0', 'Model:1', 'Model:2']
    assert [t['name'] for o in inv.objects for t in o.textures] == ['Texture_0', 'Texture_1']
    kinds = [dc.colour_from(o, inv.dat)[0] for o in inv.objects]
    # hued vertex colours over a greyscale texture, alone, and white ones under a colour texture
    assert kinds == ['vertex', 'vertex', 'texture']
    plain = dc.scan(costume([{'flags': 0x1}], animated=[0]))
    assert dc.colour_from(plain.objects[0], plain.dat)[0] == 'animation'


def test_the_open_says_where_each_parts_colour_comes_from(lab):
    lab.state.parts = {'shirt': [0], 'gloves': [1]}
    lab.state.hidden = {3: 'low-poly', 4: 'alternate'}
    opened = lab.open(costume([
        {'texture': 0},                                                    # the shirt, vertex coloured
        {'texture': 1, 'texture_format': 6, 'colours': [(255, 255, 255, 255)] * 3},   # gloves: a colour texture
        {'colours': [BLUE] * 3},                                           # no texture: no known part
        {'texture': 0},                                                    # the shirt's low-poly copy
        {'colours': [RED] * 3, 'flags': 0x1}], animated=[4]))              # an animated alternate piece
    rows = {row['index']: row['colour_from'] for row in opened['textures']}
    assert rows == {0: 'vertex', 1: 'texture'}
    assert opened['known_parts']['colour_from'] == {'shirt': 'vertex', 'gloves': 'texture'}
    sources = opened['colour_sources']
    assert sources['by_part'] == {'shirt': 'vertex 0,3', 'no known part': 'animation 4; vertex 2'}
    assert sources['hidden'] == 'alternate 4; low-poly 3'
    assert sources['vertex_colours'] == '#c81e1e #1e3cc8 0,3; #1e3cc8 2'
    assert 'recolor_vertex' in opened['colour_note']
    usage = run('skin_lab', session_id=opened['session_id'], action='texture_usage')
    assert usage['colour_sources'] == sources and usage['known_parts']['colour_from'] == {'shirt': 'vertex',
                                                                                          'gloves': 'texture'}
    assert [row['colour_from'] for row in usage['textures']] == ['vertex', 'texture']
    again = run('skin_lab', session_id=opened['session_id'], action='color_sources')
    assert again['colour_sources'] == sources and again['parts'] == {'shirt': 'vertex', 'gloves': 'texture'}


def test_a_costume_coloured_by_textures_alone_carries_no_extra_note(lab):
    opened = lab.open(costume([{'texture': 0, 'texture_format': 6, 'colours': [(255, 255, 255, 255)] * 3}]))
    assert opened['textures'][0]['colour_from'] == 'texture'
    assert 'colour_sources' not in opened and 'colour_note' not in opened


# --------------------------------------------------------------------------- #
# edits                                                                        #
# --------------------------------------------------------------------------- #
def test_a_mask_turns_the_shirt_green_and_leaves_the_overalls_blue(lab):
    source = costume([{}, {'colours': [BLUE] * 3}])
    sid = lab.open(source)['session_id']
    result = run('skin_lab', session_id=sid, action='recolor_vertex', edits=[
        {'material_ids': ['Model:0'], 'set_hue': 120, 'set_saturation': 70,
         'mask': {'hue_min': 340, 'hue_max': 20, 'sat_min': 30}}])
    assert result['changed'] == {'Model:0': 2} and result['checkpoint_file'] and 'viewer_update' not in result
    assert len(lab.renderers) == 2 and lab.renderers[0].closed, 'the session reloaded the edited file'
    assert skin_lab._sessions[sid]['viewer'] is lab.renderers[1] and skin_lab._sessions[sid]['edited']
    edited = lab.renderers[-1].data
    shirt = colours(edited, 'Model:0')
    assert green(shirt[0]) and green(shirt[2]) and shirt[1][:3] == BLUE[:3], 'the overalls in the same mesh stay blue'
    assert colours(edited, 'Model:1') == colours(source, 'Model:1')
    assert len(edited) == len(source), 'no buffer grew'
    # the checkpoint the workbench reloads is the edited file
    checkpoint, _ = mod_files.resolve(result['checkpoint_file']['file_id'])
    assert colours(checkpoint.read_bytes(), 'Model:0') == shirt


def test_an_edit_by_part_reaches_the_parts_hidden_copies(lab):
    lab.state.parts = {'shirt': [0], 'overalls': [1]}
    lab.state.hidden = {2: 'low-poly'}
    sid = lab.open(costume([{'texture': 0}, {'texture': 1, 'colours': [BLUE] * 3}, {'texture': 0}]))['session_id']
    result = run('skin_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'part': 'shirt', 'set_hue': 120, 'set_saturation': 70}])
    assert set(result['changed']) == {'Model:0', 'Model:2'}
    edited = lab.renderers[-1].data
    assert all(green(c) for c in colours(edited, 'Model:2') if max(c[:3]) != min(c[:3]))
    assert colours(edited, 'Model:1') == [BLUE] * 3
    assert 'Unknown part' in run('skin_lab', session_id=sid, action='recolor_vertex',
                                 edits=[{'part': 'cape', 'hue_shift': 10}])['error']


def test_hidden_copies_left_out_of_an_edit_are_named(lab):
    lab.state.hidden = {1: 'low-poly'}
    sid = lab.open(costume([{'colours': [RED] * 3}, {'colours': [RED] * 3}]))['session_id']
    result = run('skin_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'material_ids': ['Model:0'], 'set_hue': 120, 'set_saturation': 70}])
    assert result['hidden_unchanged'] == ['Model:1'] and 'hidden_unchanged' in result['note']


def test_an_animated_colour_is_rekeyed_in_its_own_timing(lab):
    source = costume([{'flags': 0x1}], animated=[0])
    sid = lab.open(source)['session_id']
    result = run('skin_lab', session_id=sid, action='recolor_animated',
                 edits=[{'material_ids': ['Model:0'], 'set_hue': 200, 'set_saturation': 60, 'lightness_scale': 0.6}])
    assert result['changed'] == {'Model:0': 6} and 'viewer_update' not in result
    old = {t.channel: t for t in dc.scan(source).tracks}
    new = {t.channel: t for t in dc.scan(lab.renderers[-1].data).tracks}
    for channel, track in old.items():
        assert [(k['frame'], k['op']) for k in new[channel].keys] == [(k['frame'], k['op']) for k in track.keys]
    start = [dc.sample(new[('diffuse', c)].keys, 0) for c in range(3)]
    assert start[2] > start[1] > start[0], f'blue at frame 0: {start}'


# --------------------------------------------------------------------------- #
# the scope gate                                                               #
# --------------------------------------------------------------------------- #
def test_a_shared_colour_array_is_copied_so_one_part_changes_alone(lab):
    lab.state.parts = {'shirt': [0], 'overalls': [1]}
    source = costume([{'texture': 0, 'kind': 'index', 'shared_array': 'a'},
                      {'texture': 1, 'kind': 'index', 'shared_array': 'a'}])
    sid = lab.open(source)['session_id']
    result = run('skin_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'part': 'shirt', 'set_hue': 120, 'set_saturation': 70}])
    assert result['changed'] == {'Model:0': 3} and 'also_changed' not in result
    edited = lab.renderers[-1].data
    assert len(edited) > len(source) and dc.Dat(edited).reloc_count == dc.Dat(source).reloc_count
    assert colours(edited, 'Model:1') == colours(source, 'Model:1'), 'the overalls kept the original array'


def test_a_store_two_parts_read_through_one_pointer_is_edited_and_the_result_names_both(lab):
    lab.state.parts = {'shirt': [0], 'overalls': [1]}
    source = costume([{'texture': 0, 'kind': 'index', 'shared_desc': 'd'},
                      {'texture': 1, 'kind': 'index', 'shared_desc': 'd'}])
    sid = lab.open(source)['session_id']
    edited = run('skin_lab', session_id=sid, action='recolor_vertex',
                 edits=[{'part': 'shirt', 'set_hue': 120, 'set_saturation': 70}])
    # Never refused, never a question for the user: done, and what else it reached is said.
    assert 'error' not in edited and edited['changed'] == {'Model:0': 3} and edited['also_changed'] == ['Model:1']
    assert any('Model:1 (overalls)' in line for line in edited['also_changed_parts'])
    assert 'choose_scope' not in json.dumps(edited)
    assert all(green(c) for c in colours(lab.renderers[-1].data, 'Model:1') if max(c[:3]) != min(c[:3]))


def test_an_object_that_draws_two_parts_is_edited_and_said_to_be_more_than_one_part(lab):
    lab.state.parts = {'shirt': [0], 'overalls': [1]}
    sid = lab.open(costume([{'texture': 0}, {'texture': 1}]))['session_id']
    skin_lab._sessions[sid]['colour_scan']['parts_of']['Model:0'] = ['shirt', 'overalls']   # as a mod's mesh can
    edited = run('skin_lab', session_id=sid, action='recolor_vertex', edits=[{'part': 'shirt', 'hue_shift': 120}])
    assert edited['changed'] == {'Model:0': 3}
    assert edited['also_changed_parts'] == ["Model:0 ('overalls'): also draws 'shirt', so it changed whole"]
    named = run('skin_lab', session_id=sid, action='recolor_vertex',
                edits=[{'material_ids': ['Model:0'], 'hue_shift': 120}])
    assert named['changed'] == {'Model:0': 3} and 'also_changed_parts' not in named, 'naming the object claims no part'


def test_an_animation_two_objects_share_is_edited_and_reported(lab):
    sid = lab.open(costume([{'flags': 0x1}, {'flags': 0x1}], animated=[0, 1], shared_aobj=True))['session_id']
    edited = run('skin_lab', session_id=sid, action='recolor_animated',
                 edits=[{'material_ids': ['Model:0'], 'hue_shift': 120}])
    assert 'error' not in edited and edited['also_changed'] == ['Model:1']
    assert edited['also_changed_parts'][0].startswith('Model:1 (')
    with pytest.raises(ValueError, match="'action' is unknown: use one of"):
        run('skin_lab', session_id=sid, action='choose_scope', value='yes please do it')   # the user-answer action is gone


def test_a_costume_gets_the_identify_map_through_the_stage_labs_code(lab):
    sid = lab.open(costume([{'texture': 0}, {'texture': 1}]))['session_id']
    viewer = skin_lab._sessions[sid]['viewer']
    before = {t['index']: viewer.get_full_texture(t['index']) for t in viewer.textures}
    looked = run('skin_lab', session_id=sid, action='identify', points=[[0.5, 0.5]])
    assert looked['files'][0]['name'] == 'Skin identify map.png' and looked['files'][0]['preview_only'] is True
    # This stand-in draws nothing of the textures, so every id is reported unseen, and nothing changed.
    assert looked['surfaces'] == [] and set(looked['not_visible']) >= {0, 1} and looked['at'][0]['id'] is None
    assert {t['index']: viewer.get_full_texture(t['index']) for t in viewer.textures} == before


# --------------------------------------------------------------------------- #
# reset, resume, save                                                          #
# --------------------------------------------------------------------------- #
def test_reset_and_resume_return_to_the_costume_as_opened(lab):
    source = costume([{}, {'colours': [BLUE] * 3}, {'flags': 0x1}], animated=[2])
    sid = lab.open(source)['session_id']
    run('skin_lab', session_id=sid, action='recolor_vertex', edits=[{'material_ids': ['Model'], 'hue_shift': 120}])
    run('skin_lab', session_id=sid, action='recolor_animated',
        edits=[{'material_ids': ['Model:2'], 'set_hue': 200, 'set_saturation': 60, 'lightness_scale': 0.5}])
    edited = lab.renderers[-1].data
    assert colours(edited, 'Model:1') != colours(source, 'Model:1')
    # The session closes; its next call reopens it from the last checkpoint, which carries both edits.
    assert run('skin_lab', session_id=sid, action='close')['closed'] and sid not in skin_lab._sessions
    one = run('skin_lab', session_id=sid, action='reset_colors', material_ids=['Model:1'])
    assert 'error' not in one and one['restored'] == {'Model:1': 3} and 'viewer_update' not in one
    reopened = lab.renderers[-2]
    assert reopened.data == edited, 'the resume reopened the checkpoint'
    now = lab.renderers[-1].data
    assert colours(now, 'Model:1') == colours(source, 'Model:1')
    assert colours(now, 'Model:0') == colours(edited, 'Model:0'), 'only the named object was reset'
    everything = run('skin_lab', session_id=sid, action='reset_colors')
    assert set(everything['restored']) == {'Model:0', 'Model:2'}
    restored = dc.scan(lab.renderers[-1].data)
    original = dc.scan(source)
    for object_id in ('Model:0', 'Model:1'):
        assert colours(lab.renderers[-1].data, object_id) == colours(source, object_id)
    assert [[k['value'] for k in t.keys] for t in restored.tracks] == [[k['value'] for k in t.keys]
                                                                         for t in original.tracks]
    assert restored.dat.raw(restored.objects[2].material, dc.MATERIAL_SIZE) == \
        original.dat.raw(original.objects[2].material, dc.MATERIAL_SIZE)


def test_the_saved_costume_carries_the_edit(lab, monkeypatch):
    from core.metadata import metadata_transaction
    from vault.importing.unified import characters
    sid = lab.open(costume([{}, {'colours': [BLUE] * 3}]))['session_id']
    run('skin_lab', session_id=sid, action='recolor_vertex', edits=[
        {'material_ids': ['Model:0'], 'set_hue': 120, 'set_saturation': 70, 'mask': {'hue_min': 340, 'hue_max': 20}}])
    exported = run('skin_lab', session_id=sid, action='export')['files'][0]
    imported = {}

    def importer(path, char_info, filename, **kwargs):
        with zipfile.ZipFile(path) as archive:
            imported['dat'] = archive.read(char_info['dat_file'])
        with metadata_transaction(default={}) as metadata:
            metadata.setdefault('characters', {}).setdefault('Fox', {}).setdefault('skins', []).append(
                {'id': 'green-shirt', 'name': kwargs['custom_name']})
        return {'success': True, 'skin_id': 'green-shirt'}
    monkeypatch.setattr(characters, 'import_character_costume', importer)
    saved = run('save_mod_copy', file_id=exported['file_id'], name='Green shirt')
    assert saved['vault_changed']
    shirt = colours(imported['dat'], 'Model:0')
    assert green(shirt[0]) and shirt[1][:3] == BLUE[:3]
    assert colours(imported['dat'], 'Model:1') == [BLUE] * 3


def test_edits_are_validated_before_anything_changes(lab):
    sid = lab.open(costume([{}]))['session_id']
    for edits, message in (([{'hue_shift': 10}], 'a part, material_ids or a texture_index'),
                           ([{'material_ids': ['Model:0'], 'part': 'shirt', 'hue_shift': 1}], 'a part, material_ids'),
                           ([{'material_ids': ['Model:9'], 'hue_shift': 1}], 'Unknown material_ids'),
                           ([{'material_ids': ['Model:0'], 'hue_shift': 1, 'mask': {'surrounding': True}}], 'mask')):
        assert message in run('skin_lab', session_id=sid, action='recolor_vertex', edits=edits)['error']
    assert 'belong to recolor_vertex' in run('skin_lab', session_id=sid, action='frame', edits=[{}])['error']
    assert len(lab.renderers) == 1


def test_colour_edits_checkpoint_and_name_no_textures():
    """Their viewer_update comes from the in-place path alone (continuity._colour_update), never textures."""
    assert {'recolor_vertex', 'recolor_animated', 'reset_colors'} <= continuity.EDIT_ACTIONS
    assert continuity._swap_textures({}, 'skin_lab', {'action': 'recolor_vertex'}, {}) is None


def test_a_protocol_2_renderer_takes_the_edit_in_place(lab, monkeypatch):
    from tests.backend.test_viewer_protocol2 import Protocol2

    class InPlace(Protocol2, Renderer):
        pass
    monkeypatch.setattr(sys.modules[__name__], 'Renderer', InPlace)
    source = costume([{}, {'colours': [BLUE] * 3}])
    sid = lab.open(source)['session_id']
    result = run('skin_lab', session_id=sid, action='recolor_vertex', edits=[
        {'material_ids': ['Model:0'], 'set_hue': 120, 'set_saturation': 70,
         'mask': {'hue_min': 340, 'hue_max': 20, 'sat_min': 30}}])
    viewer = lab.renderers[0]
    assert len(lab.renderers) == 1 and not viewer.closed and not viewer.loaded, 'no reload'
    shirt = colours(viewer.data, 'Model:0')
    assert green(shirt[0]) and shirt[1][:3] == BLUE[:3]
    assert result['viewer_update']['colours']['types'] == ['setVertexColors']
    reset = run('skin_lab', session_id=sid, action='reset_colors')
    assert colours(viewer.data, 'Model:0') == colours(source, 'Model:0') and reset['viewer_update']['colours']


# --------------------------------------------------------------------------- #
# the fighter's model tables                                                   #
# --------------------------------------------------------------------------- #
FIGHTER = Path(__file__).resolve().parents[2] / 'app' / 'storage' / 'test-base' / 'files' / 'PlGw.dat'


@pytest.mark.skipif(not FIGHTER.is_file(), reason='no vanilla PlGw.dat here')
def test_the_model_tables_name_low_poly_and_alternate_objects():
    hidden = lowpoly.hidden_objects(FIGHTER, 0)
    assert {i for i, kind in hidden.items() if kind == 'low-poly'} >= set(range(23, 36))
    assert {hidden[i] for i in (16, 42, 108)} == {'alternate'}, "Game & Watch's other heads"
    assert 0 not in hidden and 17 not in hidden, 'the body and the default head show'
    assert lowpoly.hidden_objects(FIGHTER.with_name('missing.dat'), 0) is None
