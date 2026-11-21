"""A face of part swaps as Melee's model states (fighter_port/own_faces.py).

The first tests need no game files: made-up clips, a made-up script. The last read Duck Hunt's own clips and model
and the donor's fighter data, and run only where those are.

    python -m pytest tests/test_own_faces.py -q
"""
import json
import os
import struct
from pathlib import Path

import pytest

from fighter_port import compat

compat.install()
from fighter_port import own_faces as F                           # noqa: E402
from fighter_port.own_faces import AGAIN, CALL, END, GOTO, LOOP, MODEL, RETURN, UNTIL, WAIT, WRAP   # noqa: E402

T, N = True, False


def clip(end, **tracks):
    return {'end': end, 'tracks': {node: list(track) for node, track in tracks.items()}}


def toy():
    """An eye that is open, half shut or shut; a mouth shut or open; brows that go with the open eye; a hat no
    clip ever takes off, and a spare nothing ever shows. The resting clip blinks on frames 3 to 5; `stand` names
    the mouth alone (the eye is left to the resting clip); `bite` names everything."""
    still = dict(Hat=[T], Spare=[N])
    return {
        'rest': clip(8, Open=[T, T, T, N, N, N, T, T, T], Brow=[T, T, T, N, N, N, T, T, T], Half=[N, N, N, T, N, T, N, N, N],
                     Shut=[N, N, N, N, T, N, N, N, N], MouthN=[T], MouthA=[N], **still),
        'stand': clip(5, MouthN=[T], MouthA=[N], **still),
        'bite': clip(4, Open=[T, T, N, N, T], Brow=[T, T, N, N, T], Half=[N], Shut=[N, N, T, T, N],
                     MouthN=[T, N, N, T, T], MouthA=[N, T, T, N, N], **still),
    }


def toy_plan():
    return F.plan(toy(), 'rest')


def group_of(plan, node):
    return next(g for g, group in enumerate(plan['groups']) if any(node in unit for unit in group['choices']))


# ---- the plan --------------------------------------------------------------------------------------------------------
def test_parts_never_drawn_together_are_choices_of_one_group_and_the_resting_one_is_first():
    plan = toy_plan()
    assert plan['always'] == ['Hat'] and plan['never'] == ['Spare']
    assert plan['shown_at_rest'] == ['Brow', 'MouthN', 'Open'] and not plan['joined']
    eye, mouth = plan['groups'][group_of(plan, 'Open')], plan['groups'][group_of(plan, 'MouthN')]
    assert len(plan['groups']) == 2
    assert eye['choices'][0] == ['Brow', 'Open']                 # always drawn together: one choice
    assert sorted(map(tuple, eye['choices'][1:])) == [('Half',), ('Shut',)] and eye['rest'] == 0
    assert mouth['choices'] == [['MouthN'], ['MouthA']] and mouth['rest'] == 0 and not mouth['clock']
    for group in plan['groups']:                                 # the more a choice is seen, the earlier it stands
        assert group['seen'][1:] == sorted(group['seen'][1:], reverse=True)


def test_the_resting_clips_own_switches_are_a_groups_clock():
    plan = toy_plan()
    eye = plan['groups'][group_of(plan, 'Open')]
    half, shut = eye['choices'].index(['Half']), eye['choices'].index(['Shut'])
    assert eye['moving'] == ['Brow', 'Half', 'Open', 'Shut']
    assert eye['clock'] == [[3, half], [4, shut], [5, half], [6, 0]] and plan['clock_end'] == 8


def test_a_clip_that_leaves_a_part_to_the_resting_clip_can_meet_any_of_its_pictures():
    clips = toy()
    # `stand` opens its mouth on a frame of its own: the open mouth can then meet the shut eye
    clips['stand'] = clip(5, MouthN=[T, T, N, T, T, T], MouthA=[N, N, T, N, N, N], Hat=[T], Spare=[N])
    seen = F.pictures(clips, 'rest')
    assert frozenset({'Hat', 'MouthA', 'Shut'}) in seen and frozenset({'Hat', 'MouthA', 'Half'}) in seen
    assert abs(sum(seen.values()) - (9 + 6 + 5)) < 1e-9          # every frame of every clip counts once


def test_a_group_with_nothing_up_at_rest_rests_on_none_and_comes_after_the_others():
    clips = {'rest': clip(2, Body=[T], Wing=[N], Eye=[T]),
             'jump': clip(2, Body=[T], Wing=[N, T, T], Eye=[T, T, N])}
    plan = F.plan(clips, 'rest')
    assert [g['choices'] for g in plan['groups']] == [[['Eye']], [['Wing']]]
    assert [g['rest'] for g in plan['groups']] == [0, -1]


def test_more_groups_than_the_engine_holds_are_joined_and_said():
    # three parts, each seen alone and each pair seen together: three groups; with room for two, the pair seen
    # together least is made one group, and where both would show the one seen more often does
    clips = {'rest': clip(0, A=[N], B=[N], C=[N]),
             'x': clip(9, A=[T] * 10, B=[T] * 9 + [N], C=[N] * 9 + [T]),
             'y': clip(5, A=[N] * 6, B=[T] * 6, C=[T, N, N, N, N, N])}
    assert len(F.plan(clips, 'rest')['groups']) == 3
    plan = F.plan(clips, 'rest', most=2)
    assert len(plan['groups']) == 2 and len(plan['joined']) == 1
    assert plan['joined'][0]['frames_seen_together'] == 1.0       # A and C: one frame of `x`
    both = plan['groups'][group_of(plan, 'A')]
    assert group_of(plan, 'C') == group_of(plan, 'A') != group_of(plan, 'B')
    assert both['choices'][F.choice_of(both, {'A', 'C'})] == ['A']    # A is seen on ten frames, C on two


def test_over_the_limit_a_part_up_at_rest_is_drawn_always_before_two_resting_groups_are_joined():
    """Incineroar: claws up at rest, each hidden on a few frames, made more groups than the engine holds; joining a
    claw with the eye would leave the resting face undrawable. The part hidden on the fewest frames is drawn always."""
    clips = {'rest': clip(0, Eye=[T], Blink=[N], C1=[T], C2=[T]),
             'blink': clip(3, Eye=[T, N, N, T], Blink=[N, T, T, N], C1=[T], C2=[T]),
             'claw': clip(3, Eye=[T], Blink=[N], C1=[T, N, T, T], C2=[N, N, N, T])}
    assert len(F.plan(clips, 'rest')['groups']) == 3
    plan = F.plan(clips, 'rest', most=2)
    assert len(plan['groups']) == 2 and 'C1' in plan['always']          # hidden on one frame; Eye two, C2 three
    assert plan['joined'] == [dict(groups=[[['C1']]], frames_seen_together=0, frames_hidden=1.0,
                                   how='drawn always: it is up at rest, and hidden on these frames only')]
    assert all(g['rest'] == 0 for g in plan['groups'])                  # the resting picture can still be drawn


def test_over_the_limit_a_join_wrong_on_fewer_frames_than_drawing_a_part_always_is_taken():
    clips = {'rest': clip(0, Eye=[T], C1=[T], X=[N], Y=[N]),
             'a': clip(9, Eye=[T], C1=[T] * 5 + [N] * 5, X=[T, T] + [N] * 8, Y=[N, T, T] + [N] * 7)}
    plan = F.plan(clips, 'rest', most=2)
    assert len(plan['groups']) == 2 and 'C1' not in plan['always']
    assert plan['joined'][0]['frames_seen_together'] == 1.0 and group_of(plan, 'X') == group_of(plan, 'Y')


def test_fewest_is_exact_on_a_ring_of_five():
    ring = {i: {(i - 1) % 5, (i + 1) % 5} for i in range(5)}      # an odd ring needs three sets, never two
    sets = F.fewest(list(ring), ring)
    assert len(sets) == 3 and sorted(x for s in sets for x in s) == [0, 1, 2, 3, 4]
    assert all(b not in ring[a] for s in sets for a in s for b in s)


# ---- the costume -----------------------------------------------------------------------------------------------------
OBJECTS = [('HatShape', 0), ('Open_VIS_O_OBJShape', 0), ('Open_VIS_O_OBJShape', 1), ('Brow_VIS_O_OBJShape', 0),
           ('Half_VIS_O_OBJShape', 0), ('Shut_VIS_O_OBJShape', 0), ('Spare_VIS_O_OBJShape', 0),
           ('MouthN_VIS_O_OBJ_O_NOSORT_FARShape', 0), ('MouthA_VIS_O_OBJShape', 0), ('TailShape', 0)]


def test_a_mesh_object_belongs_to_the_longest_node_that_fits_its_name():
    nodes = ['Duck_FaceN', 'Duck_FaceN_Head', 'Gamemodel']
    assert F.node_of('Duck_FaceN_Head_VIS_O_OBJShape', nodes) == 'Duck_FaceN_Head'
    assert F.node_of('Duck_FaceN_VIS_O_OBJShape', nodes) == 'Duck_FaceN'
    assert F.node_of('GamemodelShape', nodes) == 'Gamemodel' and F.node_of('TailShape', nodes) is None


def test_the_costume_carries_every_part_some_picture_draws_and_the_plan_in_piece_numbers():
    plan = toy_plan()
    carried = F.selection(OBJECTS, plan)
    assert carried == [o for o in OBJECTS if o[0] != 'Spare_VIS_O_OBJShape']     # never drawn: left out
    named = F.pieces(carried, plan)
    assert named['high'] == [0, 8]                                # the hat, and the tail no node names
    eye, mouth = group_of(plan, 'Open'), group_of(plan, 'MouthN')
    assert named['groups'][eye][0] == [1, 2, 3]                   # the open eye's two objects and the brows
    assert sorted(named['groups'][eye][1:]) == [[4], [5]] and named['groups'][mouth] == [[6], [7]]
    assert named['rest'] == [0, 0] and F.drawn_at_rest(named) == [0, 1, 2, 3, 6, 8]
    with pytest.raises(ValueError):                               # a choice the model has no mesh for
        F.pieces([o for o in carried if not o[0].startswith('Shut')], plan)


# ---- an action's frames ----------------------------------------------------------------------------------------------
def test_frames_are_laid_as_the_bank_lays_them():
    end = {'a': 4, 'b': 2, 'one': 0}.get
    assert F.frames_of([('a', None)], end) == [(0, 0.0), (0, 1.0), (0, 2.0), (0, 3.0), (0, 4.0)]
    assert F.frames_of([('a', [[0, 0.0], [2, 4.0], [3, 4.0]])], end) == [(0, 0.0), (0, 2.0), (0, 4.0), (0, 4.0)]
    assert F.frames_of([('a', [[0, 1.0], [1, 2.0]]), ('b', None)], end) == [(0, 1.0), (0, 2.0), (1, 0.0), (1, 1.0), (1, 2.0)]
    assert F.frames_of([('one', None)], end) == [(0, 0.0), (0, 0.0)]            # a clip has to last
    from fighter_port import own_bank
    for parts in ([('a', None)], [('a', [[0, 0.0], [2, 4.0], [3, 4.0]])], [('a', [[0, 1.0], [1, 2.0]]), ('b', None)],
                  [('one', None)]):
        maps = [own_bank.part_keys({'stem': s, 'keys': k}, end(s)) for s, k in parts]
        _frames, which, shows, _last = own_bank.timeline(maps, 1)
        assert F.frames_of(parts, end) == [(int(p), float(t)) for p, t in zip(which, shows)]


def test_a_script_says_each_change_of_a_group_and_where_it_starts_other_than_at_rest():
    plan, clips = toy_plan(), toy()
    eye, mouth = group_of(plan, 'Open') + 1, group_of(plan, 'MouthN') + 1       # the engine's groups: the body is 0
    shut = plan['groups'][eye - 1]['choices'].index(['Shut'])
    got, left, notes = F.events(plan, clips, [('bite', None)])
    assert got == sorted([(1, mouth, 1), (3, mouth, 0), (2, eye, shut), (4, eye, 0)]) and not left and not notes
    # played from its third frame: it starts with the eye shut and the mouth open, and says so at once
    late, _left, _notes = F.events(plan, clips, [('bite', [[0, 2.0], [2, 4.0]])])
    assert late == sorted([(0, eye, shut), (0, mouth, 1), (1, mouth, 0), (2, eye, 0)])


def test_a_group_the_clip_leaves_alone_is_left_to_the_resting_clip():
    plan, clips = toy_plan(), toy()
    eye = group_of(plan, 'Open') + 1
    got, left, _notes = F.events(plan, clips, [('stand', None)])
    assert got == [] and left == [eye]
    assert F.events(plan, clips, [('stand', None)], clock=False)[1] == []       # no code to run the clock: not left
    assert F.events(plan, clips, [('stand', None), ('bite', None)])[1] == []    # one of its clips names the eye
    # a clip that names the shut eye and not the half shut one: said, and the rest held as at rest
    clips['odd'] = clip(1, Shut=[N, T], Open=[T, N], Brow=[T, N])
    _got, left, notes = F.events(plan, clips, [('odd', None)])
    assert left == [] and len(notes) == 1 and 'Half' in notes[0]


def test_an_action_that_plays_round_and_round_says_where_its_groups_begin():
    plan, clips = toy_plan(), toy()
    mouth = group_of(plan, 'MouthN') + 1
    clips['chew'] = clip(3, MouthN=[T, N, T, N], MouthA=[N, T, N, T], Open=[T], Brow=[T], Half=[N], Shut=[N])
    once, _l, _n = F.events(plan, clips, [('chew', None)])
    again, _l, _n = F.events(plan, clips, [('chew', None)], loop=True)
    assert once == [(1, mouth, 1), (2, mouth, 0), (3, mouth, 1)]
    assert again == [(0, mouth, 0)] + once                        # it comes back to its start with the mouth open


# ---- the scripts -----------------------------------------------------------------------------------------------------
SFX, GFX = (17, {'sfx_id': 5}, None), (10, {'gfx_id': 7}, None)
ON = lambda g, c: F.command(g, c)                                 # noqa: E731


def test_a_command_holds_minus_one_as_the_engine_reads_it():
    from vault.echo.subactions import FighterDat
    blob, _pointers = FighterDat.encode_script([ON(7, -1), ON(3, 2), (END, {}, None)])
    none, two = struct.unpack_from('>II', blob, 0)
    assert none >> 26 == MODEL and (none >> 19) & 0x7F == 7 and none & 0x7FFFF == 0x7FFFF     # nineteen bits, all set
    assert two >> 26 == MODEL and (two >> 19) & 0x7F == 3 and two & 0x7FFFF == 2


def test_commands_go_in_at_their_frames_and_a_wait_they_fall_inside_is_cut():
    items = [SFX, (UNTIL, {'frame': 10}, None), GFX, (END, {}, None)]
    got, lost = F.lay(items, [(0, 1, 1), (4, 2, 0), (10, 1, 0), (15, 2, -1)])
    assert not lost and got == [ON(1, 1), SFX, (UNTIL, {'frame': 4}, None), ON(2, 0), (UNTIL, {'frame': 10}, None), ON(1, 0),
                                GFX, (UNTIL, {'frame': 15}, None), ON(2, -1), (END, {}, None)]
    counted = [(WAIT, {'frame': 6}, None), SFX, (WAIT, {'frame': 6}, None), GFX, (END, {}, None)]
    got, lost = F.lay(counted, [(2, 1, 1), (6, 1, 2), (8, 1, 0)])
    assert not lost and got == [(WAIT, {'frame': 2}, None), ON(1, 1), (WAIT, {'frame': 4}, None), ON(1, 2), SFX,
                                (WAIT, {'frame': 2}, None), ON(1, 0), (WAIT, {'frame': 4}, None), GFX, (END, {}, None)]


def test_the_donors_own_model_commands_come_out():
    donor = [(MODEL, {'struct_id': 1, 'extrabitnonsense': 0, 'object_id': 1}, None), SFX, (32, {'unknown': 0}, None),
             (33, {'unknown': 0}, None), (END, {}, None)]
    assert F.lay(donor, []) == ([SFX, (END, {}, None)], [])


def test_a_script_that_waits_for_its_clip_to_come_round_keeps_its_own_loop():
    start = 0x4000
    items = [(UNTIL, {'frame': 3}, None), SFX, (WRAP, {'unknown': 0}, None), (GOTO, {'target': 0, 'pointer': start}, start)]
    got, lost = F.lay(items, [(0, 1, 1), (9, 1, 0)], loops=True, start=start)
    assert not lost and got == [ON(1, 1), (UNTIL, {'frame': 3}, None), SFX, (UNTIL, {'frame': 9}, None), ON(1, 0),
                                (WRAP, {'unknown': 0}, None), (GOTO, {'target': 0, 'pointer': start}, start)]


def test_an_action_that_loops_under_a_script_that_ends_is_given_a_loop():
    got, _lost = F.lay([SFX, (END, {}, None)], [(0, 1, 0), (5, 1, 1)], loops=True, start=0x40)
    assert got == [ON(1, 0), SFX, (UNTIL, {'frame': 5}, None), ON(1, 1), (WRAP, {'unknown': 0}, None),
                   (GOTO, {'target': 0, 'pointer': 0x40}, 0x40), (END, {}, None)]
    # ... but not when it has nothing to say after its first frame
    assert F.lay([SFX, (END, {}, None)], [(0, 1, 1)], loops=True, start=0x40)[0] == [ON(1, 1), SFX, (END, {}, None)]


def blocks(table):
    return lambda pointer: table[pointer]


def test_what_stands_in_the_way_of_counting_is_written_out():
    # a counted loop, a call that waits and a jump to another block, each as the same commands in the same order
    table = {0x100: [GFX, (WAIT, {'frame': 2}, None), GFX, (RETURN, {}, None)],
             0x200: [SFX, (WAIT, {'frame': 3}, None), (END, {}, None)],
             0x300: [GFX, (RETURN, {}, None), SFX]}
    items = [(LOOP, {'count': 2}, None), SFX, (WAIT, {'frame': 4}, None), (AGAIN, {}, None),
             (CALL, {'target': 0, 'pointer': 0x300}, 0x300), (CALL, {'target': 0, 'pointer': 0x100}, 0x100),
             (GOTO, {'target': 0, 'pointer': 0x200}, 0x200)]
    got, lost = F.lay(items, [(6, 1, 1), (9, 1, 2), (12, 1, 0)], start=0x40, block=blocks(table))
    assert not lost and got == [
        SFX, (WAIT, {'frame': 4}, None), SFX, (WAIT, {'frame': 2}, None), ON(1, 1), (WAIT, {'frame': 2}, None),
        (CALL, {'target': 0, 'pointer': 0x300}, 0x300),          # it waits for nothing: left as a call
        GFX, (WAIT, {'frame': 1}, None), ON(1, 2), (WAIT, {'frame': 1}, None), GFX,
        SFX, (WAIT, {'frame': 2}, None), ON(1, 0), (WAIT, {'frame': 1}, None), (END, {}, None)]
    # with nothing left to place the rest of a script is not touched
    left = [SFX, (LOOP, {'count': 2}, None), GFX, (WAIT, {'frame': 4}, None), (AGAIN, {}, None), (END, {}, None)]
    assert F.lay(left, [(0, 1, 1)], block=blocks(table))[0] == [ON(1, 1)] + left


def test_what_cannot_be_counted_is_said():
    forever = [SFX, (CALL, {'target': 0, 'pointer': 0x500}, 0x500), (END, {}, None)]     # a call that never comes back
    got, lost = F.lay(forever, [(0, 1, 1), (7, 1, 0)], block=blocks({0x500: [GFX, (WAIT, {'frame': 9}, None), (END, {}, None)]}))
    assert lost == [(7, 1, 0)] and got == [ON(1, 1)] + forever


# ---- the code --------------------------------------------------------------------------------------------------------
def test_the_code_sets_the_defaults_and_runs_the_resting_clips_clock():
    plan = toy_plan()
    eye = group_of(plan, 'Open') + 1
    own = F.code(None, plan, {'2': [eye], 7: [eye], 3: []}, {1: [eye]})
    text = '\n'.join(own['source'])
    assert '#define FACE_GROUPS 3' in text and 'static const s8 face_rest[FACE_GROUPS] = {0, 0, 0};' in text
    half, shut = (plan['groups'][eye - 1]['choices'].index([n]) for n in ('Half', 'Shut'))
    for row in (f'{{3, {eye}, {half}}},', f'{{4, {eye}, {shut}}},', f'{{5, {eye}, {half}}},', f'{{6, {eye}, 0}},'):
        assert row in text
    assert '#define FACE_CLOCK_END 8' in text
    bit = 1 << eye
    assert f'face_left[] = {{0, 0, {bit}, 0, 0, 0, 0, {bit}}};' in text and f'face_left_other[] = {{0, {bit}}};' in text
    assert own['load'] == ['FacesLoad(gobj);'] and own['frame'] == ['FacesFrame(fd, gobj);'] and own['table'] == []
    # a port with code of its own keeps it
    mine = dict(source=['// mine'], frame=['OwnFrame(fd, gobj);'], provides=['a thing'], load=['OwnLoad(fd);'], table=['T'])
    both = F.code(mine, plan, {})
    assert both['source'][0] == '// mine' and both['load'] == ['OwnLoad(fd);', 'FacesLoad(gobj);']
    assert both['frame'] == ['OwnFrame(fd, gobj);', 'FacesFrame(fd, gobj);'] and both['table'] == ['T']
    assert mine['load'] == ['OwnLoad(fd);']                       # ... and is not changed where it lies


# ---- Duck Hunt's own files -------------------------------------------------------------------------------------------
REPO = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2])
SOURCE = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
DONOR_DIR = REPO / 'app/scratch/brawl-oneshot/port/donor'
WORK = REPO / 'app/scratch/duckhunt-native'
MODEL_FILE = SOURCE / 'gamedata/fighter/duckhunt/model/body/c00/model.numshb'
real = pytest.mark.skipif(not (MODEL_FILE.exists() and (SOURCE / 'gamedata/fighter/duckhunt/motion/body/c00').is_dir()),
                          reason="Duck Hunt's own clips and model are not here")
donor = pytest.mark.skipif(not all(p.exists() for p in (MODEL_FILE, DONOR_DIR / 'PlMs.dat', WORK / 'rig/rig-duckhunt.json',
                                                        WORK / 'rig/lookup.json')),
                           reason='the donor or the frozen rig is not here')


@pytest.fixture(scope='module')
def duckhunt():
    got = F.read(SOURCE, 'duckhunt')
    return got['clips'], F.plan(got['clips'], got['rest'])


@pytest.fixture(scope='module')
def carried(duckhunt):
    import ssbh_data_py as ssbh
    mesh = ssbh.mesh_data.read_mesh(str(MODEL_FILE))
    objects = F.selection([(o.name, o.subindex) for o in mesh.objects], duckhunt[1])
    return objects, F.pieces(objects, duckhunt[1])


@real
def test_duck_hunts_parts_fit_the_engines_groups_with_nothing_joined(duckhunt):
    clips, plan = duckhunt
    assert len(plan['groups']) + 1 == F.MOST_GROUPS and not plan['joined']     # ten, and the body: all the engine has
    assert plan['always'] == ['Gamemodel'] and not plan['never']
    seen = F.pictures(clips, plan['rest_clip'])
    for picture in seen:                                          # no picture draws two choices of one group
        for group in plan['groups']:
            assert sum(1 for unit in group['choices'] if unit[0] in picture) <= 1
    lids = plan['groups'][group_of(plan, 'Duckhunt_Openblink')]
    assert sorted(n for unit in lids['choices'] for n in unit) == ['Duckhunt_Blink', 'Duckhunt_Halfblink', 'Duckhunt_Openblink']
    half, shut = lids['choices'].index(['Duckhunt_Halfblink']), lids['choices'].index(['Duckhunt_Blink'])
    assert lids['clock'][:4] == [[121, half], [122, shut], [123, half], [124, 0]]      # the dog's first blink


@real
def test_what_the_plan_draws_at_rest_is_what_the_resting_clip_shows(duckhunt, carried):
    import ssbh_data_py as ssbh
    from fighter_port import own_skeleton
    objects, named = carried
    rest = own_skeleton.shown_at_rest(SOURCE, 'duckhunt', ssbh.mesh_data.read_mesh(str(MODEL_FILE)))
    assert [objects[i] for i in F.drawn_at_rest(named)] == [(r['name'], r['subindex']) for r in rest['meshes']]
    assert len(objects) + len(rest['meshes']) <= F.MOST_PIECES    # every part, and the low-detail copy of the resting ones


@real
def test_the_standing_clip_leaves_the_dogs_eyelids_to_the_resting_clip_and_a_smash_names_its_own(duckhunt):
    clips, plan = duckhunt
    lids = group_of(plan, 'Duckhunt_Openblink') + 1
    got, left, notes = F.events(plan, clips, [('a00wait1', None)])
    assert got == [] and left == [lids] and not notes
    got, left, _notes = F.events(plan, clips, [('c03attacks4s', None)])
    assert left == []
    ouch = group_of(plan, 'Duck_Ouch') + 1
    at = [(f, c) for f, g, c in got if g == ouch]
    assert at == [(16, plan['groups'][ouch - 1]['choices'].index(['Duck_Ouch'])), (29, 0)]      # the duck's hurt face
    wing = group_of(plan, 'wing') + 1
    spread = plan['groups'][wing - 1]['choices'].index(['wing'])
    assert (0, wing, spread) in F.events(plan, clips, [('a03jumpf', None)])[0]         # the wings are out in the jump
    assert all(g != wing for _f, g, _c in F.events(plan, clips, [('a01walkslow', None)])[0])


@donor
def test_the_fighter_data_names_every_group_and_the_scripts_switch_them(duckhunt, carried):
    from vault.echo.subactions import FighterDat
    from fighter_port import own_bank, own_data as od
    clips, plan = duckhunt
    objects, named = carried
    low = list(range(len(objects), len(objects) + len(F.drawn_at_rest(named))))
    pieces = dict(high=named['high'], low=low, groups=named['groups'], rest=named['rest'])
    pl = (DONOR_DIR / 'PlMs.dat').read_bytes()
    frozen = json.loads((WORK / 'rig/rig-duckhunt.json').read_text('utf-8'))
    lookup = json.loads((WORK / 'rig/lookup.json').read_text('utf-8'))
    out, report = od.build(pl, frozen, lookup, SOURCE, 'duckhunt', 'Marth', pieces=pieces)
    assert report['verify']['ok'], report['verify']['problems']
    facts = od.census(out, 'ftDataMars', joints=len(frozen['order']))['facts']
    assert facts['visibility_groups'] == 11
    drawn = {(r['mode'], r['group'], r['variant']): r['pieces'] for r in facts['visibility']}
    assert drawn[0, 0, 0] == named['high'] == drawn[3, 0, 0] and drawn[1, 0, 0] == low
    for g, choices in enumerate(named['groups'], 1):
        for k, numbers in enumerate(choices):
            assert drawn[0, g, k] == numbers == drawn[3, g, k]
    assert not [key for key in drawn if key[0] in (1, 2) and key[1] > 0]       # the shadow and the metal body: none
    assert od.build(pl, frozen, lookup, SOURCE, 'duckhunt', 'Marth', pieces=pieces)[0] == out

    # the scripts of three actions, from their own clips
    fd = FighterDat(out)
    index = {}
    for act in fd.actions:
        index.setdefault(act.motion, act.index)
    jobs = [{'motion': 'Wait1', 'parts': [{'stem': 'a00wait1'}], 'loop': False},
            {'motion': 'AttackS4', 'parts': [{'stem': 'c03attacks4s'}], 'loop': False},
            {'motion': 'JumpF', 'parts': [{'stem': 'a03jumpf'}], 'loop': False}]
    rows = {m: {'kind': 'SOURCE', 'motion': m, 'actions': [index[m]]} for m in ('Wait1', 'AttackS4', 'JumpF')}
    rows['held'] = {'kind': 'HELD', 'motion': 'ItemBlind', 'actions': [index['ItemBlind']]}
    new, said = F.scripts(out, plan, clips, jobs, rows, own_bank.HOLD_STEM, log=lambda *a: None)
    lids, ouch, wing = (group_of(plan, n) + 1 for n in ('Duckhunt_Openblink', 'Duck_Ouch', 'wing'))
    assert said['left'] == {index['Wait1']: [lids], index['ItemBlind']: [lids]} and not said['not_placed']
    assert said['donor_commands_removed'] > 0 and said['groups'] == 11
    fd = FighterDat(new)
    assert not fd.verify_roundtrip()

    def run(offset, seen=()):
        """The commands a script can reach: its own up to a jump, the blocks it jumps on to and the ones it calls."""
        own = F.live([(c.code, dict(c.fields), c.pointer) for c in fd.decode_script(offset).commands if not c.after_end])
        return own + [x for code, _f, p in own if code in (CALL, GOTO) and p and p not in seen
                      for x in run(p, tuple(seen) + (offset, p))]

    donors_left = [(act.motion, c) for act in fd.actions if act.script_offset is not None
                   and act.motion not in ('AttackS4', 'JumpF') for c in run(act.script_offset) if c[0] in (MODEL, 32, 33)]
    assert not donors_left                                        # nothing of the donor's switches a group any more

    def at_frames(motion):
        frame, got = 0, []
        for code, fields, _p in fd.script_items(index[motion]):
            if code == UNTIL:
                frame = max(frame, fields['frame'])
            elif code == WAIT:
                frame += fields['frame']
            elif code == MODEL:
                got.append((frame, fields['struct_id'], -1 if fields['extrabitnonsense'] else fields['object_id']))
        return got

    assert sorted(at_frames('AttackS4')) == F.events(plan, clips, [('c03attacks4s', None)])[0]
    assert (16, ouch, 1) in at_frames('AttackS4')
    assert (0, wing, plan['groups'][wing - 1]['choices'].index(['wing'])) in at_frames('JumpF')
    assert at_frames('Wait1') == []                               # the standing blink is the clock's, in the code
