from copy import deepcopy
import pytest
from randall.recolor.materials import material_action


class Viewer:
    def __init__(self): self.commands = []
    def material_command(self, command):
        self.commands.append(command)
        return deepcopy({'requestId': 'private', 'materials': [{'id': 'Group 0:2', 'fields': [
            {'key': 'diffuse', 'kind': 'color', 'value': '#ffffffff'},
            {'key': 'alpha', 'kind': 'number', 'value': 1},
            {'key': 'shininess', 'kind': 'number', 'value': 0},
            {'key': 'texture:0:constant', 'kind': 'color', 'value': '#000000ff'},
        ]}]})


@pytest.mark.parametrize('field,value', [('diffuse', '#ff0080ff'), ('texture:0:constant', '#00cc11aa'), ('alpha', 0.5), ('shininess', 128)])
def test_edits_use_discovered_material_fields(field, value):
    viewer = Viewer()
    result = material_action(viewer, 'set_material', 'Group 0:2', field, value)
    assert viewer.commands == [{'type': 'getMaterials'}, {'type': 'setMaterial', 'id': 'Group 0:2', 'field': field, 'value': value}]
    assert 'requestId' not in result


@pytest.mark.parametrize('field,value,sent', [('diffuse', '#ff0080', '#ff0080ff'), ('texture:0:constant', '#00cc11', '#00cc11ff'),
                                              ('diffuse', [255, 0, 128], '#ff0080ff'), ('texture:0:constant', [0, 204, 17, 170], '#00cc11aa')])
def test_a_colour_also_takes_rrggbb_and_an_rgb_list_keeping_the_fields_alpha(field, value, sent):
    viewer = Viewer()
    material_action(viewer, 'set_material', 'Group 0:2', field, value)
    assert viewer.commands[-1] == {'type': 'setMaterial', 'id': 'Group 0:2', 'field': field, 'value': sent}


@pytest.mark.parametrize('field,value', [('diffuse', '#fffff'), ('diffuse', 'ffffff'), ('diffuse', [1.0, 0.5, 0.0]), ('diffuse', [256, 0, 0]), ('diffuse', 123), ('alpha', True), ('alpha', 1.01), ('alpha', float('nan')), ('shininess', 129), ('shininess', -1), ('missing', '#ffffffff')])
def test_invalid_values_never_reach_mutation(field, value):
    viewer = Viewer()
    with pytest.raises(ValueError): material_action(viewer, 'set_material', 'Group 0:2', field, value)
    assert viewer.commands == [{'type': 'getMaterials'}]


def test_reset_and_preview_do_not_send_fabricated_values():
    viewer = Viewer()
    material_action(viewer, 'reset_material', 'Group 0:2', 'diffuse')
    assert viewer.commands[-1] == {'type': 'setMaterial', 'id': 'Group 0:2', 'field': 'diffuse', 'reset': True}
    result = material_action(viewer, 'preview_base_colors', enabled=True)
    assert viewer.commands[-1] == {'type': 'previewBaseColors', 'enabled': True}
    assert 'view-only' in result['note']
    with pytest.raises(ValueError): material_action(viewer, 'preview_base_colors', enabled='true')


def test_unknown_material_cannot_be_edited():
    viewer = Viewer()
    with pytest.raises(ValueError): material_action(viewer, 'set_material', 'guessed', 'diffuse', '#ffffffff')
    assert len(viewer.commands) == 1


def test_material_palette_preserves_alpha_and_absolute_reset():
    from randall.recolor.materials import palette_snapshot, palette_edits
    from shared.rendering import palette
    class ColoredViewer:
        def material_command(self, command):
            return {'materials': [{'id': 'mesh', 'fields': [
                {'key': 'diffuse', 'kind': 'color', 'value': '#ff000000'},
                {'key': 'texture:0:constant', 'kind': 'color', 'value': '#00ff0044'},
                {'key': 'alpha', 'kind': 'number', 'value': 0.4},
            ]}]}
    originals, fields = palette_snapshot(ColoredViewer())
    groups, maps = palette.analyze(originals, 8)
    assert len(groups) == 2
    shifts = {i: (120, 0) for i in range(len(groups))}
    edits = palette_edits(originals, fields, maps, shifts)
    assert [e['value'] for e in edits] == ['#00ff0000', '#0000ff44']
    assert palette_edits(originals, fields, maps, shifts) == edits
    assert [e['value'] for e in palette_edits(originals, fields, maps, {})] == ['#ff000000', '#00ff0044']


def test_the_inventory_groups_identical_materials_and_drops_labels():
    class Many:
        def material_command(self, command):
            same = [{'key': 'diffuse', 'label': 'Diffuse', 'kind': 'color', 'value': '#b3b3b3ff'},
                    {'key': 'alpha', 'label': 'Opacity', 'kind': 'number', 'value': 1}]
            return {'materials': [{'id': f'Model:{i}', 'name': f'Mesh {i}', 'fields': deepcopy(same)} for i in range(40)]
                    + [{'id': 'Visor:0', 'name': 'Visor', 'animated': True,
                        'fields': [{'key': 'diffuse', 'label': 'Diffuse', 'kind': 'color', 'value': '#00ff00ff'}]}]}
    result = material_action(Many(), 'materials')
    assert result['material_count'] == 41 and len(result['materials']) == 2
    assert result['materials'][0] == {'ids': [f'Model:{i}' for i in range(40)],
                                      'fields': {'diffuse': '#b3b3b3ff', 'alpha': 1}}
    assert result['materials'][1] == {'ids': ['Visor:0'], 'animated': True, 'fields': {'diffuse': '#00ff00ff'}}


def test_an_edit_returns_only_the_material_it_changed():
    viewer = Viewer()
    result = material_action(viewer, 'set_material', 'Group 0:2', 'diffuse', '#ff0080ff')
    assert 'materials' not in result and result['material']['ids'] == ['Group 0:2']
