"""The parts a fighter swings by physics, written into Melee's fighter data.

The first tests need no game files. The last runs only when Duck Hunt's work folder and the donor's files are here.
"""
import json
import math
import os
from pathlib import Path

import pytest

from fighter_port import compat

compat.install()
from fighter_port import own_dynamics as dyn   # noqa: E402


def test_a_joints_numbers_keep_what_each_is_for_inside_melees_own_range():
    stiff = dyn.joint_numbers(dict(goalstrength=500.0, airresistance=1.0, minangley=-20, maxangley=30, minanglez=-10,
                                   maxanglez=10), (0.0, 0.2, -0.4))
    loose = dyn.joint_numbers(dict(goalstrength=0.0, airresistance=40.0), (0.0, 0.0, 0.0))
    assert len(stiff) == 15 and stiff[0] == 1.0
    assert stiff[1] == dyn.SPRING[2] and loose[1] == 0.0                 # pulled back hard; not pulled back at all
    assert stiff[2:5] == (0.0, 0.2, -0.4) and stiff[5] == 0.0            # the rest turn it swings about
    assert stiff[6] == pytest.approx(math.radians(30)) and loose[6] == dyn.CONE[1]    # its widest angle; none given
    assert stiff[7:13] == dyn.FILL
    assert stiff[13] == pytest.approx(dyn.DAMPING[0]) and loose[13] == dyn.DAMPING[2]  # air resistance, capped
    assert stiff[14] == dyn.STEP


def test_a_chains_gravity_is_the_mean_of_its_joints_inside_the_range():
    assert dyn.chain_gravity([dict(localgravity=1.0), dict(localgravity=1.0)]) == pytest.approx(dyn.GRAVITY)
    assert dyn.chain_gravity([dict(localgravity=50.0)]) == dyn.GRAVITY_RANGE[1]
    assert dyn.chain_gravity([dict(localgravity=0.0)]) == dyn.GRAVITY_RANGE[0]
    assert dyn.chain_gravity([dict(localgravity=2.0, fallspeedscale=0.5)]) == pytest.approx(dyn.GRAVITY)


def swing(spheres=(), ellipsoids=(), uses=()):
    return dict(chains=[dict(joints=['Ear1', 'Ear2', 'Ear3'], numbers=[dict(collisions=list(uses)), dict(collisions=list(uses))])],
                spheres=list(spheres), ellipsoids=list(ellipsoids))


def test_shapes_become_spheres_and_the_least_used_are_left_out():
    order = ['Top', 'Head', 'Ear1', 'Ear2', 'Ear3']
    ball = dict(name='ball', bonename='Head', cx=1.0, cy=2.0, cz=3.0, radius=4.0)
    egg = dict(name='egg', bonename='Head', cx=0.0, cy=0.0, cz=0.0, sx=1.0, sy=3.0, sz=2.0)
    stray = dict(name='stray', bonename='Head', cx=0.0, cy=0.0, cz=0.0, radius=9.0)        # no joint names it
    gone = dict(name='gone', bonename='NoSuchBone', cx=0.0, cy=0.0, cz=0.0, radius=1.0)    # its bone is not on the rig
    made, left = dyn.spheres(swing([ball, stray, gone], [egg], uses=['ball', 'egg', 'gone']), order)
    assert made == [(1, 1.0, 2.0, 3.0, 4.0), (1, 0.0, 0.0, 0.0, 2.0)] and left == []      # an egg: its middle radius
    many = [dict(ball, name=f'b{i}') for i in range(13)]
    chains = swing(many, uses=[f'b{i}' for i in range(13)])
    chains['chains'][0]['numbers'][0]['collisions'] = ['b0', 'b1']                         # b0 and b1 are named twice
    made, left = dyn.spheres(chains, order)
    assert len(made) == dyn.MOST_SPHERES and len(left) == 2 and 'b0' not in left and 'b1' not in left


def test_an_actions_row_says_how_many_joints_at_each_chains_head_follow_the_clip():
    chains = [dict(joints=['A1', 'A2', 'A3']), dict(joints=['B1', 'B2'])]
    assert dyn.row_for(chains, {}) == (0, 0)                                       # nothing said: all of it swings
    assert dyn.row_for(chains, {'A1': 0.0, 'A2': 1.0}) == (1, 0)                   # the first joint is the clip's
    assert dyn.row_for(chains, {'A1': 0.0, 'A2': 0.4, 'B1': 0.0}) == (dyn.OFF, dyn.OFF)   # every swung joint is
    assert dyn.row_for(chains, {'A1': 1.0, 'A2': 0.0}) == (0, 0)                   # a later joint cannot be held alone


REPO = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2])
WORK = REPO / 'app/scratch/duckhunt-native'
HAVE = (WORK / 'data/PlMs.dat').exists() and (WORK / 'rig/rig-duckhunt.json').exists()


@pytest.mark.skipif(not HAVE, reason='Duck Hunt\'s work folder is not here')
def test_duck_hunts_chains_are_written_and_read_back():
    from vault.echo.subactions import FighterDat
    pl = (WORK / 'data/PlMs.dat').read_bytes()
    frozen = json.loads((WORK / 'rig/rig-duckhunt.json').read_text('utf-8'))
    order = frozen['order']
    assert dyn.read(pl)['chains'] == []                                            # the data stage leaves them off
    out, report = dyn.apply(pl, frozen)
    back = dyn.read(out)
    assert [order[c['first']] for c in back['chains']] == [c['joints'][0] for c in frozen['swing']['chains']]
    assert len(back['chains']) == 7 <= dyn.MOST_CHAINS and len(back['spheres']) <= dyn.MOST_SPHERES
    for chain, plan in zip(back['chains'], frozen['swing']['chains']):
        assert chain['joints'] == len(plan['joints'])
        assert dyn.GRAVITY_RANGE[0] <= chain['gravity'] <= dyn.GRAVITY_RANGE[1]
        # a swung joint is not turned about its own length at rest (the game would unwind it frame by frame)
        assert all(abs(numbers[2]) < 1e-3 for numbers in chain['numbers'][:-1])
    assert back['flags'] == {'swings': len(FighterDat(out).actions)} and report['actions'] == {'swings': len(FighterDat(out).actions)}
    assert not FighterDat(out).verify_roundtrip()
    # with what the game says of each action's clip: an action whose clip holds every swung joint follows the clip
    held = {None: {}, 'pose': {j: 0.0 for c in frozen['swing']['chains'] for j in c['joints']}}
    out2, report2 = dyn.apply(pl, frozen, {0: 'pose'}, held)
    assert report2['actions']['follows the clip'] == 1 and dyn.read(out2)['flags']['follows the clip'] == 1
