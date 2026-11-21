import math
from types import SimpleNamespace as NS

import pytest

from echo_slapcity.gamedata import deep_fields, transform_fields


def node(name, t=(0, 0, 0), q=(0, 0, 0, 1), s=(1, 1, 1)):
    return dict(name=name, t=list(t), q=list(q), s=list(s))


def test_reader_follows_pointer_arrays_boundedly_and_retains_missing_slots():
    objects = {i: NS(type=NS(name='MonoBehaviour'), assets_file='asset', path_id=i) for i in range(1, 4)}
    data = {1: dict(rate=1/60, proxyFor=[dict(m_PathID=2), dict(m_PathID=0)]),
            2: dict(tweenScale1=dict(x=3, y=1, z=1), cycle=dict(m_PathID=1))}
    game = NS(deref=lambda owner, p: objects.get(p.get('m_PathID', 0)), mono=lambda o: data[o.path_id],
              script=lambda o: {1: 'ProxyUpdater', 2: 'TwScaleFX'}[o.path_id])
    got = deep_fields(game, 'asset', dict(updateTogether=[dict(m_PathID=1)]), depth=2)
    updater = got['updateTogether'][0]
    assert updater['rate'] == 1/60 and updater['proxyFor'][1] is None
    assert updater['proxyFor'][0]['tweenScale1'] == [3, 1, 1]
    assert 'cycle' not in updater['proxyFor'][0]


def test_transform_reader_preserves_nonuniform_parent_scale_rotation_and_bounds_cycles():
    def transform(name, t, q, s, parent=None):
        return NS(m_GameObject=NS(read=lambda: NS(m_Name=name)), m_LocalPosition=NS(**dict(zip('xyz', t))),
                  m_LocalRotation=NS(**dict(zip('xyzw', q))), m_LocalScale=NS(**dict(zip('xyz', s))),
                  m_Father=NS(path_id=1 if parent else 0, read=lambda: parent))
    q = (0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    root = transform('root', (50, 60, 70), q, (2, 3, 1))
    child = transform('track', (1, 2, 0), (0, 0, 0, 1), (1, 1, 1), root)
    fields = transform_fields(child)
    assert fields['at'] == pytest.approx([-6, 2, 0])
    assert fields['path'] == 'root/track'
    root.m_Father = NS(path_id=1, read=lambda: child)
    with pytest.raises(ValueError, match='cyclic or too deep'):
        transform_fields(child)


