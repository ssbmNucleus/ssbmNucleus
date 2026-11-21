"""The readers for a fighter's swing bones and its effect file, and the swing chains as Melee can hold them.

The first tests need no game files. The rest run only when ULTIMATE_DUMP points at a dump whose `gamedata` holds
Duck Hunt (fighter/duckhunt and effect/fighter/duckhunt).
"""
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_ultimate import effects
from echo_ultimate.gamedata import swing

DUMP = os.environ.get('ULTIMATE_DUMP')
DUCK = Path(DUMP) / 'gamedata' / 'fighter' / 'duckhunt' if DUMP else None
needs_duck = pytest.mark.skipif(not (DUCK and (DUCK / 'motion' / 'body' / 'c00' / 'swing.prc').exists()),
                                reason='needs ULTIMATE_DUMP with Duck Hunt fetched')


def section(magic, binary=b'', children=b'', count=0, last=True):
    """One section of the particle tree: header, its own block, then its children."""
    size = len(binary) + len(children)
    head = magic + struct.pack('<IIIIIIHH', size, 0x20 + len(binary) if count else effects.NONE,
                               effects.NONE if last else 0x20 + size, effects.NONE,
                               0x20 if binary else effects.NONE, 0, count, 0)
    return head + binary + children


def named(name, size=0x60):
    return (b'\0' * 16 + name.encode() + b'\0' * 64)[:size]


def test_the_tree_gives_sets_and_their_emitters_by_name():
    emitters = section(b'EMTR', named('smoke1'), last=False) + section(b'EMTR', named('flash1'))
    sets = section(b'ESET', named('P_TestHit'), emitters, count=2)
    tree = section(b'ESTA', b'', sets, count=1)
    v = b'VFXB' + b'\0' * 0x12 + struct.pack('<H', 0x40) + b'\0' * (0x40 - 0x18) + tree
    assert [r['magic'] for r in effects.sections(v)] == ['ESTA', 'ESET', 'EMTR', 'EMTR']
    got = effects.effects(v)
    assert list(got) == ['P_TestHit']
    assert [e['name'] for e in got['P_TestHit']] == ['smoke1', 'flash1']


def rig(rows):
    """rows: (name, parent, rest turn, offset from the parent)"""
    return SimpleNamespace(order=[r[0] for r in rows], parent={r[0]: r[1] for r in rows},
                           rest={r[0]: dict(r=list(r[2]), t=list(r[3]), s=[1., 1., 1.]) for r in rows})


def chain(start, end, goals):
    return dict(name=start, start=start, end=end, joints=[dict(goalstrength=g) for g in goals])


def plan(rows, chains):
    from fighter_port import compat
    compat.install()
    from fighter_port import own_skeleton
    return own_skeleton.swing_plan(rig(rows), dict(chains=chains, spheres=[], ellipsoids=[], capsules=[]))['chains']


def test_a_chain_ends_on_the_first_child_of_its_last_joint_and_skips_a_stiff_head():
    rows = [('Head', None, (0, 0, 0), (0, 0, 0)), ('Ear1', 'Head', (0, 0, .4), (1, 0, 0)),
            ('Ear2', 'Ear1', (0, .3, -1.9), (2, 0, 0)), ('Ear3', 'Ear2', (0, 0, -.2), (2, 0, 0)),
            ('Ear4_null', 'Ear3', (0, 0, 0), (2, 0, 0))]
    got = plan(rows, [chain('Ear1', 'Ear3', [500.0, 10.0, 10.0])])
    assert [c['joints'] for c in got] == [['Ear2', 'Ear3', 'Ear4_null']]       # Ear1 is held to its clip
    assert [n['goalstrength'] for n in got[0]['numbers']] == [10.0, 10.0]
    assert got[0]['on_helper'] is False


def test_a_joint_twisted_about_its_own_length_stands_on_a_helper():
    rows = [('Head', None, (0, 0, 0), (0, 0, 0)), ('Puff1', 'Head', (1.57, 0, 1.57), (1, 0, 0)),
            ('Puff2_null', 'Puff1', (0, 0, 0), (1.5, 0, 0))]
    got = plan(rows, [chain('Puff1', 'Puff1', [0.5])])
    assert got == [dict(joints=['Puff1', 'Puff2_null'], numbers=[dict(goalstrength=0.5)], on_helper=True)]


def test_a_twist_in_the_middle_cuts_the_chain_in_two():
    rows = [('Hip', None, (0, 0, 0), (0, 0, 0)), ('Tail1', 'Hip', (0, 0, .5), (1, 0, 0)),
            ('Tail2', 'Tail1', (0.8, 0, .2), (2, 0, 0)), ('Tail3', 'Tail2', (0, 0, .1), (2, 0, 0)),
            ('Tail4', 'Tail3', (0, 0, 0), (2, 0, 0))]
    got = plan(rows, [chain('Tail1', 'Tail3', [1.0, 1.0, 1.0])])
    assert [c['joints'] for c in got] == [['Tail1', '__chart_before_Tail2'], ['Tail2', 'Tail3', 'Tail4']]
    assert [c['on_helper'] for c in got] == [False, True]


def test_a_chain_with_nothing_below_it_gives_up_its_last_joint():
    rows = [('Head', None, (0, 0, 0), (0, 0, 0)), ('Hair1', 'Head', (0, 0, 0), (1, 0, 0)),
            ('Hair2', 'Hair1', (0, 0, 0), (1, 0, 0))]
    assert [c['joints'] for c in plan(rows, [chain('Hair1', 'Hair2', [1.0, 1.0])])] == [['Hair1', 'Hair2']]
    assert plan(rows[:2], [chain('Hair1', 'Hair1', [1.0])]) == []               # one joint and nothing below: no chain


@needs_duck
def test_duck_hunts_swing_files():
    import ssbh_data_py as ssbh
    bones = [b.name for b in ssbh.skel_data.read_skel(str(DUCK / 'model' / 'body' / 'c00' / 'model.nusktb')).bones]
    motion = DUCK / 'motion' / 'body' / 'c00'
    got = swing.read(motion, bones)
    assert [(c['start'], c['end'], len(c['joints'])) for c in got['chains']] == [
        ('S_DownearL1', 'S_DownearL3', 3), ('S_DownearR1', 'S_DownearR3', 3), ('S_PuffL1', 'S_PuffL1', 1),
        ('S_PuffR1', 'S_PuffR1', 1), ('S_Tongue1', 'S_Tongue1', 1), ('S_UpearL1', 'S_UpearL2', 2),
        ('S_UpearR1', 'S_UpearR2', 2)]
    assert got['chains'][0]['joints'][0]['goalstrength'] == 500.0
    assert [(s['bonename'], s['radius']) for s in got['spheres']] == [('DuckHead', 4.0), ('DuckNeck', 2.0),
                                                                    ('Bust', pytest.approx(2.6))]
    assert len(got['ellipsoids']) == 11
    shares = swing.blend(motion, bones, [p.stem for p in motion.glob('*.nuanmb')])
    assert shares[None]['S_DownearL2'] == 1.0                                   # the default leaves the ears to physics
    assert all(v == 0.0 for v in shares['j02win1'].values())                    # the victory poses the ears by hand
    # shares are graded: dropping the shield leaves the up ears mostly to the clip, the down ears to the physics
    assert shares['b00guardoff']['S_UpearL1'] == pytest.approx(0.4) and shares['b00guardoff']['S_DownearL2'] == 1.0


@needs_duck
def test_duck_hunts_effect_file():
    path = Path(DUMP) / 'gamedata' / 'effect' / 'fighter' / 'duckhunt' / 'ef_duckhunt.eff'
    if not path.exists():
        pytest.skip('the effect file has not been fetched')
    v = effects.particle_data(path.read_bytes())
    sets = effects.effects(v)
    assert len(sets) == 50 and sum(len(rows) for rows in sets.values()) == 163
    assert [e['name'] for e in sets['P_DuckhuntFeather']] == ['feather1', 'feather2']
    names = effects.texture_names(v)
    feather = effects.emitter(v, sets['P_DuckhuntFeather'][0]['binary'])
    assert [names[t] for t in feather['textures']] == ['ef_duckhunt_feather00']
    assert feather['life'] == 44 and feather['blend'] == 'normal' and not feather['one_time']
    assert feather['gravity_direction'] == (0.0, -1.0, 0.0)                     # feathers fall
    assert [round(k['time'], 2) for k in feather['alpha_keys']] == [0.0, 0.65, 1.0]
    smoke = effects.emitter(v, next(e for e in sets['P_DuckhuntAtkSmokeR'] if e['name'] == 'smoke1')['binary'])
    assert smoke['gravity_direction'] == (0.0, 1.0, 0.0) and smoke['one_time']  # smoke rises, in one burst
    add = {e['name']: effects.emitter(v, e['binary'])['blend'] for e in sets['P_DuckhuntAttack100']}
    assert add['line1_add'] == 'add' and add['line1_alpha'] == 'normal'
    pictures = effects.textures(effects.texture_archive(v))
    assert len(pictures) == 47 and pictures[0][0] == 'ef_duckhunt_feather00' and pictures[0][1].size == (64, 64)
