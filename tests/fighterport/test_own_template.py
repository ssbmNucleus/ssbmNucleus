"""The template a fighter's own specials are started from (`fighter_port/own_template.py`): the route takes it as it
takes a fighter's module. Everything the route calls on a module is called here, without the game."""
import json
import os
from pathlib import Path
import re

import pytest

from fighter_port import code, fighters, own, own_template, states

ENTRIES = ('SpecialN', 'SpecialAirN', 'SpecialS', 'SpecialAirS', 'SpecialHi', 'SpecialAirHi', 'SpecialLw', 'SpecialAirLw')
# Marth's special actions (the donor's fighter data, actions 295 on)
DONOR_ACTIONS = ('SpecialNStart', 'SpecialNLoop', 'SpecialNEnd', 'SpecialAirNStart', 'SpecialAirNLoop', 'SpecialAirNEnd',
                 'SpecialS1', 'SpecialS2Hi', 'SpecialS2Lw', 'SpecialS3Hi', 'SpecialS3S', 'SpecialS3Lw', 'SpecialS4Hi',
                 'SpecialS4S', 'SpecialS4Lw', 'SpecialAirS1', 'SpecialAirS2Hi', 'SpecialAirS2Lw', 'SpecialAirS3Hi',
                 'SpecialAirS3S', 'SpecialAirS3Lw', 'SpecialAirS4Hi', 'SpecialAirS4S', 'SpecialAirS4Lw', 'SpecialHi',
                 'SpecialAirHi', 'SpecialLw', 'SpecialLwHit', 'SpecialAirLw', 'SpecialAirLwHit')
ROW = lambda flags, move: {'flags': flags, 'move': move}
# the donor's own rows for the states its specials start in (flags and move numbers as its table has them)
ROWS = {'SpecialNStart': ROW(0x340211, 0x12), 'SpecialAirNStart': ROW(0x340611, 0x12), 'SpecialS1': ROW(0x340212, 0x13),
        'SpecialAirS1': ROW(0x340612, 0x13), 'SpecialHi': ROW(0x340213, 0x14), 'SpecialAirHi': ROW(0x340613, 0x14),
        'SpecialLw': ROW(0x340214, 0x15), 'SpecialAirLw': ROW(0x340614, 0x15)}
MOVES = {'game_specialn': {'cancel_frame_real': 53, 'flashes': [[5, [255, 0, 0, 128], 3]]},
         'game_specialairn': {'cancel_frame_real': 50}, 'game_specials': {'cancel_frame_real': 40},
         'game_specialairs': {}, 'game_specialhi': {}, 'game_speciallw': {'cancel_frame_real': 31},
         'game_specialairlw': {'cancel_frame_real': 31}}


def a_ctx(without=(), **more):
    """What `own_route.run` hands a module, as far as the template reads it: every one of its actions holds a clip
    of 40 frames but the ones named in `without`."""
    actions = own_template.HIT_ACTIONS
    return dict({'first': 373, 'action': {m: 300 + i for i, m in enumerate(actions)},
                 'total': {m: 40 for m in actions if m not in without}, 'moves': MOVES, 'row': ROWS}, **more)


def donor_rows(count=32):
    return [dict(action=295 + i, flags=0x340211, move=0x12, bits=0, anim=0x80136844, iasa=0, phys=0x8013691C,
                 coll=0x801369A4, camera=0x800761C8) for i in range(count)]


def test_the_route_finds_it_as_it_finds_a_fighters_module_and_it_gives_every_name_the_route_reads():
    assert fighters.specials('template') is own_template            # by its name, and it has a build
    for name in fighters.MODULE_NAMES:
        assert hasattr(own_template, name), name
    assert 'template' in own.BUILD and own.BUILD['template'] is own_template.build
    assert own.OWN_CLIPS['template'] == own_template.CLIPS and own.SPECIAL_HITS['template'] == own_template.HIT_ACTIONS
    assert own.code_sounds('template') == [] and own.names('template') == []


def test_each_special_names_two_clips_two_donor_actions_and_the_donor_rows_it_is_like():
    assert [sp['key'] for sp in own_template.SPECIALS] == ['neutral', 'side', 'up', 'down']
    assert [f"Special{sp['c']}" for sp in own_template.SPECIALS] == list(ENTRIES[0::2])
    assert len(own_template.CLIPS) == 8 and set(own_template.CLIPS.values()) == set(own_template.HIT_ACTIONS)
    assert all(m in DONOR_ACTIONS for m in own_template.HIT_ACTIONS + own_template.FREE_ACTIONS)
    assert all(m in ROWS for sp in own_template.SPECIALS for m in sp['like'])
    # the neutral special's clip is whole on an action of its own: the driver cuts it in three over the donor's
    assert own_template.CLIPS['specialn'] == 'SpecialS3Hi' and own_template.CLIPS['specialairn'] == 'SpecialAirS3Hi'
    # an action left free is one the driver's own rule never fills
    assert not set(own_template.FREE_ACTIONS) & {'SpecialNStart', 'SpecialNLoop', 'SpecialNEnd', 'SpecialS1', 'SpecialHi',
                                                 'SpecialLw', 'SpecialAirS1', 'SpecialAirHi', 'SpecialAirLw'}
    assert [sp['key'] for sp in own_template.SPECIALS if sp['helpless']] == ['up']


def test_it_builds_four_specials_each_with_a_ground_and_an_air_state():
    mine, why = own.build('template', a_ctx())
    assert why is None
    for key in ('source', 'rows', 'load', 'frame', 'entries', 'provides'):          # what `code.source` reads of it
        assert mine[key], key
    text = '\n'.join(mine['source'])
    assert '@' not in text                              # every value of the build is filled in
    for name in ENTRIES:
        assert f'void {name}(GOBJ *gobj)' in text
    assert len(mine['rows']) == 8 and mine['entries'] == list(range(373, 381))
    # a ground state and then its air state, on their own actions, with the donor's flags for each
    assert [r['action'] for r in mine['rows']] == [300, 301, 302, 303, 304, 305, 306, 307]
    assert [r['flags'] for r in mine['rows'][:2]] == [0x340211, 0x340611] and mine['rows'][4]['move'] == 0x14
    assert all(r['phys'] == 'Plain_Phys' and r['coll'] == 'Plain_Coll' for r in mine['rows'])
    assert [r['anim'] for r in mine['rows'][0::2]] == ['N_Anim', 'S_Anim', 'Hi_Anim', 'Lw_Anim']
    # every call a row names is a function of the text
    for r in mine['rows']:
        for call in (r['anim'], r['iasa'], r['phys'], r['coll']):
            assert re.search(rf'^void {call}\(GOBJ \*gobj\)$', text, re.M), call
    # the frames are the scripts' own: where a script frees him, and the clip's end where it names no frame
    assert '#define ST_N 373' in text and '#define ST_N_AIR 374' in text and '#define ST_LW_AIR 380' in text
    assert '#define N_END 30000' in text and '#define N_END_AIR 30000' in text and '#define LW_END 30000' in text
    assert 't_frame[fd->ply] >= 53' in text and 't_frame[fd->ply] >= 50' in text
    assert '#define S_END_AIR 30000' in text and '#define HI_END 30000' in text
    # only the up special leaves him helpless, with the landing the game's list of motions gives (29 when unread)
    assert '#define HI_LANDING 29.0f' in text and text.count('Leave(gobj, 1, HI_LANDING);') == 1
    assert text.count('Leave(gobj, 0, 0);') == 3
    # a state is entered with the step, and its two forms hand over on the frame the clip is at
    assert 'ActionStateChange(0, 1, 0, gobj, state, 0, 0);\n    Fighter_AdvanceScript(gobj);' in text
    assert 'ActionStateChange(fd->state.frame, 1, 0, gobj, state, 0x5000, 0);' in text
    # each state's other form is listed both ways round, by name
    assert 'static int Other_Form(int state);' in text and text.count('static int Other_Form(int state)\n{') == 1
    for c in ('N', 'S', 'HI', 'LW'):
        assert f'    case ST_{c}: return ST_{c}_AIR;\n    case ST_{c}_AIR: return ST_{c};' in text
    # in the air, gravity with fast fall (which drifts him itself) and nothing more
    assert 'Fighter_PhysAir_ApplyGravityFastfall(gobj);' in text and 'ApplyAerialDrift(fd);' not in text
    # what it is, said where a reader of the build's report looks
    assert all(any(n['what'] == 'PLAIN' for n in mine['numbers'][key]) for key in ('neutral', 'side', 'up', 'down'))
    assert len(mine['provides']) == 4 and all('plain' in p for p in mine['provides'])
    # the colour a special's script lays over the body is handed to the route, on the action the state plays
    assert mine['flash'] == [(300, 5, 3, [255, 0, 0, 0], [255, 0, 0, 128])]


def test_a_special_whose_clip_is_not_there_is_left_out_and_said():
    mine, why = own.build('template', a_ctx(without=('SpecialLw', 'SpecialAirLw')))
    text = '\n'.join(mine['source'])
    assert why is None and len(mine['rows']) == 6 and mine['entries'] == list(range(373, 379))
    assert 'void SpecialLw(' not in text and 'void SpecialAirLw(' not in text and 'void SpecialHi(' in text
    assert mine['numbers']['down'][0]['what'] == 'NOT BUILT' and any(p.startswith('NOT BUILT') for p in mine['provides'])
    # (and the other forms name only the states there are: a state left out is never handed over to)
    assert 'ST_LW' not in text and 'case ST_HI_AIR: return ST_HI;' in text
    # a special left out before others: the states after it still find their other forms
    mine, why = own.build('template', a_ctx(without=('SpecialS1', 'SpecialAirS1')))
    text = '\n'.join(mine['source'])
    assert '#define ST_HI 375' in text and '#define ST_HI_AIR 376' in text and 'case ST_HI: return ST_HI_AIR;' in text
    assert 'ST_S ' not in text and 'ST_S_AIR' not in text
    # no clip for the air: the air state plays the ground's
    mine, why = own.build('template', a_ctx(without=('SpecialAirHi',)))
    up = [r for r in mine['rows'] if 'up special' in r['name']]
    assert why is None and len(mine['rows']) == 8 and up[0]['action'] == up[1]['action'] == 304
    assert (up[0]['flags'], up[1]['flags']) == (0x340213, 0x340613)
    # nothing at all: it builds nothing and says why
    mine, why = own.build('template', a_ctx(without=own_template.HIT_ACTIONS))
    assert mine is None and 'none of the four specials' in why


def test_a_clip_that_lost_its_action_to_the_drivers_own_row_stops_the_build(tmp_path, monkeypatch):
    spec = tmp_path / 'spec'
    spec.mkdir()
    clips = [{'source': f'motion/body/c00/{stem}.nuanmb', 'target_motion': motion}
             for stem, motion in (('d00specialn', 'SpecialS3Hi'), ('d01specials', 'SpecialS1'), ('d03speciallw1', 'SpecialLw'))]
    (spec / 'moveset.json').write_text(json.dumps({'clips': clips}), 'utf-8')
    # (a row the driver lists twice for one clip is no loss)
    (spec / 'skipped.json').write_text(json.dumps([['d01specials', 'SpecialS1', 'already filled by d01specials']]), 'utf-8')
    mine, why = own.build('template', a_ctx(work=tmp_path))
    assert why is None and len(mine['rows']) == 8
    # the clip on an action is not the one named, and the fighter has none of that name: it is played, and said
    assert any(n['what'] == 'on the ground it plays the clip' and n['value'] == 'speciallw1' for n in mine['numbers']['down'])
    # the side special is told to play its start clip, which the driver's own `specials` kept off SpecialS1
    side = dict(own_template.SPECIALS[1], clips=('specialsstart', 'specialairs'))
    monkeypatch.setattr(own_template, 'SPECIALS', (own_template.SPECIALS[0], side) + own_template.SPECIALS[2:])
    (spec / 'skipped.json').write_text(json.dumps([['d01specialsstart', 'SpecialS1', 'already filled by d01specials']]), 'utf-8')
    mine, why = own.build('template', a_ctx(work=tmp_path))
    assert mine is None and 'specialsstart' in why and 'SpecialS1' in why and 'd01specials had it first' in why
    assert 'SpecialS2Hi' in why                         # ... and where it can go


def a_code_file(without=()):
    mine, _ = own.build('template', a_ctx(without))
    rows = donor_rows()
    mine['table'] = states.table_text(rows, mine['rows'])       # (as `own_route.run` does before the code file)
    return code.source('Marth', None, None, None, None, [], mine, 0x801364AC, list(mine['entries']), None, None,
                       mine['flash'], state_rows=(rows, mine['rows']))


def test_the_code_file_takes_it_with_the_donors_states_before_its_own():
    files, provides = a_code_file()
    text = files['fighter.c']
    assert list(files) == ['fighter.c']                 # no items: nothing but the fighter's own file
    assert provides[:4] == [f'the {k} special, plain: its clip and the hits of its script' + tail
                            for k, tail in (('neutral', ''), ('side', ''), ('up', ', helpless after it in the air'), ('down', ''))]
    assert 'specials that can be turned around as they start' in provides
    # the donor's load is called first, then the module's own; its per-frame call is in the fighter's
    assert re.search(r'void OnLoad\(GOBJ \*gobj\)\n\{\n.*\n.*0x801364ac.*\n    OwnLoad\(fd\);', text)
    assert re.search(r'void OnFrame\(GOBJ \*gobj\)\n\{\n.*\n    OwnFrame\(fd, gobj\);', text)
    # the state table: the donor's 32 rows by their addresses, then the eight of its own from state 373
    table = text[text.index('static struct FtState move_logic[]'):]
    assert table.count('(void *)0x80136844') == 32
    assert '{300, 0x340211, 0x12, 0x0, N_Anim, Reverse_IASA_373, Plain_Phys, Plain_Coll, Fighter_UpdateCameraBox},    // 373:' in table
    assert '{305, 0x340613, 0x14, 0x0, Hi_Anim, Reverse_IASA_378, Plain_Phys, Plain_Coll, Fighter_UpdateCameraBox},    // 378:' in table
    # the states its specials start in are the ones the stick can turn round, and its flash is played
    assert 's == 373 || s == 374' in text and '{300, 5, 3, {255, 0, 0, 0}, {255, 0, 0, 128}},' in text


def test_its_c_compiles_with_the_kit_the_route_builds_with():
    kit = code.toolkit(os.environ.get('MEXTK_DIR') or str(Path.home() / 'projects' / 'm-ex' / 'MexTK'))
    if kit is None:
        pytest.skip('MexTK is not on this machine (MEXTK_DIR)')
    tier2 = pytest.importorskip('vault.echo.tier2.build')           # the app's own builder, which `code.build` calls
    files, _ = a_code_file()
    got = tier2.check_files(files, mextk_dir=str(kit))
    assert got.get('ok'), got.get('error')
    assert got['bytes'] > 2000
    # and with a special left out (its names are nowhere in the text)
    got = tier2.check_files(a_code_file(without=('SpecialS1', 'SpecialAirS1'))[0], mextk_dir=str(kit))
    assert got.get('ok'), got.get('error')


def test_template_preserves_recovery_after_iasa_without_input():
    moves=dict(MOVES, game_specials={'cancel_frame_real':36,'end':47})
    mine, why=own.build('template',a_ctx(moves=moves))
    assert why is None
    source='\n'.join(mine['source'])
    assert '#define S_END 47' in source
    row=next(r for r in mine['rows'] if r['anim']=='S_Anim')
    assert row['iasa']=='S_IASA'
    iasa=source.split('void S_IASA(GOBJ *gobj)',1)[1].split('void SpecialHi',1)[0]
    assert '>= 36' in iasa and 'Fighter_IASACheck_AllGrounded(gobj);' in iasa
    assert 'Leave(gobj' not in iasa and 'Tick(gobj)' not in iasa
    # A helpless recovery must not gain ordinary aerial actions from the common template.
    up=source.split('void Hi_IASA(GOBJ *gobj)',1)[1].split('void SpecialLw',1)[0]
    assert 'Fighter_IASACheck_AllAerial' not in up
