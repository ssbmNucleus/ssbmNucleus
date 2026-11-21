"""A skeleton over the engine's joint limit (own_skeleton, "a skeleton over the engine's joint limit"): Incineroar,
2026-11-13, 143 bones and 40 helpers asked for. The bones that cost no pose are folded into the bone above, a scale
helper is owed only for an uneven scale, and a folded bone's skin and script names go to the bone it went into."""
import copy
from types import SimpleNamespace as NS

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from fighter_port import native_port as core
from fighter_port import own_route as route
from fighter_port import own_skeleton as S


def toy_source():
    """Trans > Rot > Hip > (Offset > Face), Hip > Arm > Hand; `Offset` a fixed turn and step between Hip and Face."""
    order = ['Trans', 'Rot', 'Hip', 'Offset', 'Face', 'Arm', 'Hand']
    parent = dict(Trans=None, Rot='Trans', Hip='Rot', Offset='Hip', Face='Offset', Arm='Hip', Hand='Arm')
    r = dict(Trans=[0, 0, 0], Rot=[0, 0, 0], Hip=[0, 0.3, 0], Offset=[0.4, 0, 0.2], Face=[0, 0, 0.5], Arm=[0, 0, 0],
             Hand=[0.1, 0, 0])
    t = dict(Trans=[0, 0, 0], Rot=[0, 0, 0], Hip=[0, 10, 0], Offset=[0, 2, 0], Face=[0, 1, 1], Arm=[3, 0, 0],
             Hand=[2, 0, 0])
    rest = {j: dict(r=[float(v) for v in r[j]], t=[float(v) for v in t[j]], s=[1.0, 1.0, 1.0]) for j in order}
    return core.rig_from_meta(dict(order=order, parent=parent, rest=rest))


def still_track(bind, frames=3, moved=False, scale=None):
    size = np.linalg.norm(bind[:3, :3], axis=0)
    q = Rotation.from_matrix(bind[:3, :3] / size).as_quat()
    t = np.tile(bind[:3, 3], (frames, 1))
    if moved:
        t = t + np.array([[0, 0, 0], [0, 0.5, 0], [0, 1, 0]])[:frames]
    s = np.tile(size if scale is None else scale, (frames, 1)).astype(float)
    return NS(t=t, q=np.tile(q, (frames, 1)), s=s, compensate_scale=False)


def toy_raws(source, moves=(), uneven=()):
    bind = {j: source.local[j] for j in source.order}
    tracks = {j: still_track(bind[j], moved=j in moves, scale=np.array([1.0, 1.3, 1.0]) if j in uneven else None)
              for j in source.order}
    return {'clip': NS(tracks=tracks, bind=bind, parent=dict(source.parent))}


def test_a_source_within_room_for_its_helpers_is_left_alone():
    assert S.tight(143) and not S.tight(100)
    # its own copies of the engine's numbers (not imported: the rig's key would take in the later steps' code)
    from fighter_port import own_data, preflight
    assert S.MAX_PARTS == own_data.MAX_PARTS and S.ENGINE_JOINTS == len(preflight.ENGINE_JOINTS)


def test_a_folded_bone_leaves_every_kept_bone_where_it_rests():
    source = toy_source()
    rig = S.fold_rig(source, {'Offset': 'Hip'})
    assert 'Offset' not in rig.order and rig.parent['Face'] == 'Hip'
    for j in rig.order:
        assert np.allclose(rig.world[j], source.world[j], atol=1e-6)
    assert S.fold_rig(source, {}) is source


def test_the_bones_that_cost_no_pose_are_folded_and_the_rest_kept(monkeypatch):
    source = toy_source()
    # the skin uses Hip, Face, Arm and Hand; Offset carries none. Face never moves; Arm and Hand do.
    monkeypatch.setattr(S, '_skinned', lambda fighter, root: {'Hip', 'Face', 'Arm', 'Hand'})
    raws = toy_raws(source, moves={'Hip', 'Arm', 'Hand'})
    assert S.fold_plan('toy', '.', source, raws, bound={'Hip'}) == {'Offset': 'Hip', 'Face': 'Hip'}
    # a bone the engine binds a place to is kept however still it is
    assert 'Face' not in S.fold_plan('toy', '.', source, raws, bound={'Hip', 'Face'})
    # a bone with children whose own size is uneven is kept, unskinned or not: its children would lean under it
    monkeypatch.setattr(S, '_skinned', lambda fighter, root: {'Hip', 'Face', 'Hand'})
    raws = toy_raws(source, moves={'Hip', 'Hand'}, uneven={'Arm'})
    assert 'Arm' not in S.fold_plan('toy', '.', source, raws, bound={'Hip'})


def test_a_scale_helper_is_owed_only_for_an_uneven_parent_scale():
    def raw(parent_scale):
        tracks = dict(Arm=NS(s=np.array([parent_scale] * 2, float), compensate_scale=False),
                      Hand=NS(s=np.ones((2, 3)), compensate_scale=True))
        return NS(tracks=tracks, parent=dict(Hand='Arm', Arm=None))
    assert S.even_scale({'a': raw([1.2, 1.2, 1.2])}, {'Hand'}) == {'Hand'}
    assert S.even_scale({'a': raw([1.2, 1.2, 1.2]), 'b': raw([1.0, 1.4, 1.0])}, {'Hand'}) == set()


def test_a_script_naming_a_folded_bone_gets_the_bone_it_went_into():
    names = route.joint_names(['Trans', 'Hip', 'Face'], folded={'Offset': 'Hip', 'Gone': 'Nowhere'})
    assert names['offset'] == 1 and names['hip'] == 1 and 'gone' not in names


def test_a_folded_bones_skin_goes_to_the_bone_it_went_into():
    from fighter_port.source_mesh_handoff import prepare

    def rest(t):
        return dict(r=[0., 0., 0.], t=t, s=[1., 1., 1.])
    source = dict(order=['Root', 'Mid', 'Tip'], parent=dict(Root=None, Mid='Root', Tip='Mid'),
                  rest=dict(Root=rest([0., 0., 0.]), Mid=rest([0., 1., 0.]), Tip=rest([0., 1., 0.])))
    target = dict(order=['Root', 'Tip'], parent=dict(Root=None, Tip='Root'),
                  rest=dict(Root=rest([0., 0., 0.]), Tip=rest([0., 2., 0.])))
    o = NS(name='Body', subindex=0, positions=[NS(data=np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]))],
           normals=[NS(data=np.array([[0., 0., 1.]] * 3))],
           texture_coordinates=[NS(name='map1', data=np.zeros((3, 2)))],
           parent_bone_name='', vertex_indices=np.array([0, 1, 2]),
           bone_influences=[NS(bone_name='Mid', vertex_weights=[NS(vertex_index=i, vertex_weight=0.25) for i in range(3)]),
                            NS(bone_name='Root', vertex_weights=[NS(vertex_index=i, vertex_weight=0.75) for i in range(3)])])
    selection = dict(meshes=[dict(name='Body', subindex=0)])
    with pytest.raises(ValueError):
        prepare(NS(objects=[o]), source, copy.deepcopy(target), selection)
    model, _ = prepare(NS(objects=[o]), source, target, selection, fold={'Mid': 'Root'})
    assert model.triangles[0].verts[0].weights == [(0, 1.0)]       # Mid's quarter joined Root's three quarters


def test_a_hurtbox_on_a_folded_bone_rides_the_bone_it_went_into():
    """Rivals 2's Zetterburn, 2026-11-13: half his capsules are on twist bones the rig folds; each is carried into
    the kept bone's space at rest, so it stands where it stood (own_data.rehome_folded)."""
    from fighter_port import own_data
    src = toy_source()
    rows = [dict(bone='Face', a=[0.0, 0.0, 0.0], b=[0.0, 1.0, 0.0], radius=1.0, height='hit_height_high', part='p'),
            dict(bone='Arm', a=[0.0, 0.0, 0.0], b=[1.0, 0.0, 0.0], radius=1.0, height='hit_height_center', part='p')]
    got, said = own_data.rehome_folded(rows, {'Face': 'Hip', 'Offset': 'Hip'}, src.world)
    assert said == ['Face -> Hip'] and got[1] == rows[1]
    assert got[0]['bone'] == 'Hip' and got[0]['folded_from'] == 'Face'
    for end in ('a', 'b'):
        was = src.world['Face'] @ np.array([*rows[0][end], 1.0])
        now = src.world['Hip'] @ np.array([*got[0][end], 1.0])
        assert np.allclose(was, now)
