"""stage_lab takes the argument shapes an AI client sends one step from its own, and says its shape when it refuses.

While filming 0.9.0 an MCP client's three stage_lab recolor calls were all refused for their shape, with nothing
saying which shape the tool wants. Now the cheap, unambiguous repairs are made before the call is checked
(tools.reshape: a JSON string for an object or list, one item for a list; stage_lab.recolor_args: a recolor's
top-level colour for several textures), and a refusal that is left names the shape with an example.

No viewer process runs: the Stage Lab renderer is test_stage_retexture's stand-in.
"""
import json

import pytest

from randall.assistant import tools
from randall.mcp import randall_tools
from randall.recolor import stage_lab
from tests.backend.test_stage_retexture import lab, pixels, run  # noqa: F401  (fixture)

SCHEMA = next(s['function']['parameters'] for s in tools.SCHEMAS if s['function']['name'] == 'stage_lab')


def prepared(**args):
    return json.loads(tools.prepare('stage_lab', {'session_id': 's', **args}).arguments)


# ------------------------------------------------------------------ the schema's own shapes (tools.reshape)

@pytest.mark.parametrize('sent,meant', [
    ({'edits': '[{"texture_index": 3, "set_hue": 270}]'}, {'edits': [{'texture_index': 3, 'set_hue': 270}]}),
    ({'edits': {'texture_index': 3, 'set_hue': 270}}, {'edits': [{'texture_index': 3, 'set_hue': 270}]}),
    ({'edits': '{"texture_index": 3, "set_hue": 270}'}, {'edits': [{'texture_index': 3, 'set_hue': 270}]}),
    ({'edits': [{'texture_index': '3', 'set_hue': '270', 'mask': '{"hue_min": 200}'}]},
     {'edits': [{'texture_index': 3, 'set_hue': 270, 'mask': {'hue_min': 200}}]}),
    ({'texture_indices': 4}, {'texture_indices': [4]}),
    ({'texture_indices': '[4, 5]'}, {'texture_indices': [4, 5]}),
    ({'texture_index': [3]}, {'texture_index': 3}),
    ({'points': [0.5, 0.25]}, {'points': [[0.5, 0.25]]}),
    ({'camera': '{"rot_y": "10"}'}, {'camera': {'rot_y': 10}}),
    ({'material_ids': 'Group 1:0'}, {'material_ids': ['Group 1:0']}),
    ({'playing': 'true'}, {'playing': True}),
    # Text where text goes, and what cannot be read, stay as they came, for the tool to say.
    ({'value': '#ff0000', 'name': '[1]'}, {'value': '#ff0000', 'name': '[1]'}),
    ({'texture_indices': '4, 5', 'page': '1.5'}, {'texture_indices': '4, 5', 'page': '1.5'}),
])
def test_a_shape_one_step_from_the_schemas_is_put_in_it(sent, meant):
    assert tools.reshape({'action': 'x', **sent}, SCHEMA) == {'action': 'x', **meant}


def test_only_the_tools_that_ask_are_reshaped():
    assert set(tools.RESHAPE) == {'stage_lab'}
    other = tools.prepare('present_vault_skins', {'items': '[{"character": "Fox", "skin_id": "x"}]'})
    assert json.loads(other.arguments)['items'] == '[{"character": "Fox", "skin_id": "x"}]'


# ------------------------------------------------------------------ recolor's own (stage_lab.recolor_args)

def test_a_recolor_colour_for_several_textures_is_one_edit_per_texture():
    assert prepared(action='recolor', texture_indices=[3, 5], hue_shift=30)['edits'] == [
        {'texture_index': 3, 'hue_shift': 30}, {'texture_index': 5, 'hue_shift': 30}]
    assert prepared(action='recolor', texture_index=[3, 5], set_hue=270)['edits'] == [
        {'texture_index': 3, 'set_hue': 270}, {'texture_index': 5, 'set_hue': 270}]
    # An edit's own fields beside one texture_index are that one edit.
    assert prepared(action='recolor', texture_index=3, set_hue=270, set_saturation=60,
                    mask={'hue_min': 0, 'hue_max': 40}) == {
        'session_id': 's', 'action': 'recolor',
        'edits': [{'texture_index': 3, 'set_hue': 270, 'set_saturation': 60, 'mask': {'hue_min': 0, 'hue_max': 40}}]}
    # One edit naming several textures is one per texture.
    assert prepared(action='recolor', edits=[{'texture_indices': [1, 2], 'set_hue': 10}, {'texture_index': 4,
                    'hue_shift': 5}])['edits'] == [{'texture_index': 1, 'set_hue': 10},
                                                   {'texture_index': 2, 'set_hue': 10}, {'texture_index': 4, 'hue_shift': 5}]


def test_the_shapes_recolor_already_takes_are_left_as_they_are():
    for args in ({'texture_index': 3, 'hue_shift': 20, 'lightness_scale': 0.8},       # the top-level single form
                 {'hue_shift': 90, 'include_materials': False},                     # the whole stage
                 {'texture_indices': [3, 5], 'hue_shift': 30, 'include_materials': True},   # refused by the tool
                 {'edits': [{'texture_index': 3, 'set_hue': 1}], 'hue_shift': 4}):  # refused by the tool
        assert prepared(action='recolor', **args) == {'session_id': 's', 'action': 'recolor', **args}
    assert prepared(action='highlight', texture_indices=[3, 5]) == {'session_id': 's', 'action': 'highlight',
                                                                    'texture_indices': [3, 5]}


def test_a_refused_call_names_the_shape_its_action_takes():
    for action, shape in (('recolor', stage_lab.RECOLOR_SHAPE), ('apply', stage_lab.APPLY_SHAPE)):
        with pytest.raises(ValueError) as refused:
            prepared(action=action, color='#8040c0')
        message = str(refused.value)
        assert "'color' is not a parameter" in message and shape in message and 'Accepted parameters' in message
    assert '"set_hue": 270' in stage_lab.RECOLOR_SHAPE and '"kind": "recolor"' in stage_lab.APPLY_SHAPE
    # set_hue for the whole stage has no form (only shifts do): refused, with the shape.
    with pytest.raises(ValueError, match='recolor takes edits'):
        prepared(action='recolor', set_hue=270)
    with pytest.raises(ValueError) as other:
        prepared(action='texture', color='x')
    assert 'recolor takes' not in str(other.value)


# ------------------------------------------------------------------ through the lab

def test_the_filmed_shapes_now_recolor(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = lab.renderers[0]
    green = pixels(viewer.pixels[2])[0, 0].tolist()
    as_text = run('stage_lab', session_id=sid, action='recolor',
                  edits=json.dumps([{'texture_index': 0, 'set_hue': 280, 'set_saturation': 60}]))
    assert as_text['changed'] == [0] and 'error' not in as_text
    one = run('stage_lab', session_id=sid, action='recolor', edits={'texture_index': 0, 'hue_shift': 20})
    assert one['changed'] == [0]
    # Several textures with one top-level shift change those textures, never the whole stage.
    several = run('stage_lab', session_id=sid, action='recolor', texture_indices=[0], hue_shift=90)
    assert several['changed'] == [0] and 'updated_material_colors' not in several
    assert pixels(viewer.pixels[2])[0, 0].tolist() == green
    assert viewer.material_colors[('Group 1:0', 'diffuse')] == '#808080ff'


def test_what_is_still_wrong_is_refused_with_the_shape(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    for args, said in (({'edits': 'purple please'}, 'edits takes a list of 1..64 changes, not a string.'),
                       ({'edits': [{'texture_index': 0, 'colour': '#8040c0'}]},
                        'Edit 0 has colour, which a recolor edit does not take.'),
                       ({'edits': [{'set_hue': 10}]}, 'Edit 0 has no texture_index.'),
                       ({'texture_indices': [0], 'hue_shift': 10, 'include_materials': True},
                        'recolor names several textures in edits'),
                       ({'edits': [{'texture_index': 0, 'set_hue': 1}], 'hue_shift': 4}, 'Send edits alone')):
        refused = run('stage_lab', session_id=sid, action='recolor', **args)
        assert said in refused['error'] and stage_lab.RECOLOR_SHAPE in refused['error'], args
    apply = run('stage_lab', session_id=sid, action='apply', texture_index=0, edits=[{'kind': 'recolor'}])
    assert stage_lab.APPLY_SHAPE in apply['error']


def test_a_material_colour_takes_rrggbb_and_an_rgb_list(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    viewer = lab.renderers[0]
    for value, stored in (('#ff0000', '#ff0000ff'), ([0, 0, 255], '#0000ffff'), ([0, 255, 0, 128], '#00ff0080')):
        result = run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse',
                     value=value)
        assert 'error' not in result and viewer.material_colors[('Group 1:0', 'diffuse')] == stored
    batch = run('stage_lab', session_id=sid, action='apply',
                edits=[{'kind': 'set_material', 'material_id': 'Group 1:0', 'field': 'diffuse', 'value': [16, 32, 48]}])
    assert batch['applied'] == 1 and viewer.material_colors[('Group 1:0', 'diffuse')] == '#10203080', 'alpha 80 kept'
    # Three channels keep the field's own alpha, as a palette recolor does; a fourth sets it.
    viewer.material_colors[('Group 1:0', 'diffuse')] = '#80808040'
    run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse', value='#ff0000')
    assert viewer.material_colors[('Group 1:0', 'diffuse')] == '#ff000040'
    run('stage_lab', session_id=sid, action='apply',
        edits=[{'kind': 'set_material', 'material_id': 'Group 1:0', 'field': 'diffuse', 'value': [0, 0, 255]}])
    assert viewer.material_colors[('Group 1:0', 'diffuse')] == '#0000ff40'
    refused = run('stage_lab', session_id=sid, action='set_material', material_id='Group 1:0', field='diffuse',
                  value=[1.0, 0.5, 0.0])
    assert '#ff0000ff' in refused['error'] and '[255, 0, 0]' in refused['error']


def test_over_mcp_a_json_string_edit_list_recolors_and_the_schema_says_the_shape(lab):
    sid = run('stage_lab_open', stage_code='GrNBa')['session_id']
    answer = randall_tools.call('stage_lab', {'session_id': sid, 'action': 'recolor',
                                              'edits': '[{"texture_index": 0, "set_hue": 200, "set_saturation": 70}]'},
                                app=None)
    assert answer['isError'] is False
    refused = randall_tools.call('stage_lab', {'session_id': sid, 'action': 'recolor', 'colour': 'purple'}, app=None)
    assert refused['isError'] is True and stage_lab.RECOLOR_SHAPE in refused['content'][0]['text']
    listed = {tool['name']: tool for tool in randall_tools.listed()}['stage_lab']
    params = listed['inputSchema']['properties']
    assert '"set_hue": 270' in listed['description']
    assert '[{"kind": "recolor", "texture_index": 3' in params['edits']['description']
    assert 'several go in edits' in params['texture_index']['description']
    assert '#8040c0ff' in params['value']['description']
