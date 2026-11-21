from types import SimpleNamespace
import numpy as np
import pytest
from echo_rivals2 import materials, palettes


def info(name):
    return dict(Name=name, Association='EMaterialParameterAssociation::GlobalParameter', Index=-1)


def color(r, g, b):
    return dict(R=r, G=g, B=b, A=1)


def test_material_defaults_inherit_with_nearest_overrides_and_static_override_flags():
    records = {
        'Child': [dict(Type='MaterialInstanceConstant', Properties=dict(
            Parent=dict(ObjectPath='Parent.0'),
            VectorParameterValues=[dict(ParameterInfo=info('Tint'), ParameterValue=color(.2, .3, .4))],
            StaticParametersRuntime=dict(StaticSwitchParameters=[
                dict(ParameterInfo=info('Enabled'), Value=False, bOverride=False)])))],
        'Parent': [dict(Type='MaterialInstanceConstant', Properties=dict(
            Parent=dict(ObjectPath='Master.0'),
            ScalarParameterValues=[dict(ParameterInfo=info('Clock'), ParameterValue=.24)],
            StaticParametersRuntime=dict(StaticSwitchParameters=[
                dict(ParameterInfo=info('Enabled'), Value=True, bOverride=True)])))],
        'Master': [dict(Type='Material', CachedExpressionData={
            'RuntimeEntries': dict(ParameterInfoSet=[info('Clock')]), 'ScalarValues': [.2],
            'RuntimeEntries[1]': dict(ParameterInfoSet=[info('Tint'), info('Inherited')]),
            'VectorValues': [color(1, 1, 1), color(0, 1, 0)],
            'RuntimeEntries[3]': dict(ParameterInfoSet=[info('ColorRegionMask')]),
            'TextureValues': [dict(AssetPathName='/Game/Mask.Mask')],
            'RuntimeEntries[8]': dict(ParameterInfoSet=[info('Enabled')]), 'StaticSwitchValues': [False]})]
    }
    pak = SimpleNamespace(props=lambda p: records[p])
    got = materials.read(pak, 'Child')
    assert got['chain'] == ['Child', 'Parent', 'Master']
    assert got['scalar']['Clock'] == .24 and got['switch']['Enabled'] is True
    assert got['vector']['Tint'] == color(.2, .3, .4)
    assert got['vector']['Inherited'] == color(0, 1, 0)
    assert got['texture'] == {'ColorRegionMask': 'Rivals2/Content/Mask'}
    records['Child'][0]['Properties']['StaticParametersRuntime']['StaticSwitchParameters'][0]['bOverride'] = True
    assert materials.read(pak, 'Child')['switch']['Enabled'] is False


def test_material_read_refuses_cycles_and_mismatched_typed_defaults():
    pak = SimpleNamespace(props=lambda p: [dict(Type='MaterialInstanceConstant', Properties=dict(Parent=dict(ObjectPath='Loop.0')))])
    with pytest.raises(ValueError, match='cyclic'):
        materials.read(pak, 'Loop')
    pak.props = lambda p: [dict(Type='Material', CachedExpressionData={'ScalarValues': [1]})]
    with pytest.raises(ValueError, match='incomplete scalar'):
        materials.read(pak, 'Master')


def test_elemental_adaptation_interpolates_linear_values_before_display_encoding():
    data = dict(switch={'UseElementalCustomColors': True},
        scalar={'ElementalLerpCount': 2., 'CustomColorSampleTimeX': 0.,
                'CustomColorSampleTime0': .25, 'CustomColorSampleTime1': 1.},
        vector={'ElementColor0': color(0, 0, 0), 'ElementColor1': color(0, 1, 0), 'ElementColor2': color(1, 1, 1)})
    got, receipt = materials.elemental_colors(data)
    assert got['CustomColor0'] == pytest.approx([0, .73535698, 0])
    assert got['CustomColor1'] == pytest.approx([1, 1, 1])
    assert got['CustomColorX'] == pytest.approx([0, 0, 0])
    assert receipt['kind'] == 'static elemental ramp approximation'
    assert 'shader curve remapping' in receipt['not_carried']
    data['switch']['UseElementalCustomColors'] = False
    assert materials.elemental_colors(data) == ({}, None)


@pytest.mark.parametrize('mutate', [
    lambda d: d['scalar'].update(ElementalLerpCount=2.5),
    lambda d: d['scalar'].update(CustomColorSampleTime0=float('nan')),
    lambda d: d['vector'].pop('ElementColor2')])
def test_incomplete_elemental_data_does_not_silently_bake_gray(mutate):
    data = dict(switch={'UseElementalCustomColors': True},
        scalar={'ElementalLerpCount': 2., 'CustomColorSampleTime0': .24},
        vector={f'ElementColor{i}': color(0, i / 2, 0) for i in range(3)})
    mutate(data)
    with pytest.raises(ValueError):
        materials.elemental_colors(data)


def test_missing_first_mask_does_not_renumber_second_mask_colors(monkeypatch, tmp_path):
    from PIL import Image
    data = dict(texture={'ColorRegionMask2': 'SecondMask'}, scalar={}, switch={}, chain=['SecondOnly'],
        vector={'CustomColor0': color(1, 0, 0), 'CustomColor3': color(0, 1, 0)})
    monkeypatch.setattr(materials, 'read', lambda *a: data)
    monkeypatch.setattr(palettes, 'SIDE', 2)
    monkeypatch.setattr(palettes, 'load_picture', lambda *a: Image.new('RGBA', (2, 2), (255, 0, 0, 0)))
    receipt = []
    img, _ = palettes.picture(None, 'SecondOnly', 'Body', {}, {}, tmp_path, receipt)
    assert np.array(img)[0, 0].tolist() == [0, 255, 0, 255]
    assert receipt[0]['source']['texture'] == {'ColorRegionMask2': 'SecondMask'}
