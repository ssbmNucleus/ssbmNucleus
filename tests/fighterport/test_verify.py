"""The file checker: the marks cover the checklist, and a check says FAULT when the files say so."""
import json
import zipfile

from fighter_port import port, verify


def test_every_checklist_line_has_a_mark_and_no_mark_is_left_over():
    lines = {row['id'] for row in port.lines()}
    marks = verify.marks()
    assert lines == set(marks)
    assert {m['mark'] for m in marks.values()} <= {'rule', 'files', 'files+boot', 'boot', 'code'}


def test_every_check_is_tied_to_a_line_of_the_checklist():
    assert set(verify.CHECKS) <= {row['id'] for row in port.lines()}


def _work(tmp_path, kirby=0, groups=11, costume_bytes=1000):
    """The least a work folder needs for the checks below."""
    (tmp_path / 'port').mkdir(parents=True)
    (tmp_path / 'data').mkdir()
    (tmp_path / 'package' / 'costumes').mkdir(parents=True)
    (tmp_path / 'port' / 'report.json').write_text(json.dumps({'route': 'own skeleton', 'faces': {'groups': groups, 'commands': 9, 'actions': 3}}), 'utf-8')
    (tmp_path / 'data' / 'report.json').write_text(json.dumps({'model_tables': {'groups_now': groups, 'pieces_named_now': 20}}), 'utf-8')
    (tmp_path / 'package' / 'costumes' / 'costumes.json').write_text(json.dumps([{'file': 'PlMsNr.dat', 'folder': 'body', 'name': 'first'}]), 'utf-8')
    (tmp_path / 'package' / 'costumes' / 'PlMsNr.dat').write_bytes(bytes(costume_bytes))
    with zipfile.ZipFile(tmp_path / 'package' / 'Fighter.zip', 'w') as z:
        z.writestr('fighter.json', json.dumps({'name': 'Fighter', 'functions': {'kirbyOnSwallow': kirby, 'onLoad': 5}}))
    return tmp_path


def test_a_donors_kirby_entry_left_in_is_a_fault(tmp_path):
    assert verify.run(_work(tmp_path, kirby=0x800F081C))['answers']['12.13']['verdict'] == 'FAULT'


def test_no_kirby_entry_is_said_not_passed_over(tmp_path):
    row = verify.run(_work(tmp_path))['answers']['12.13']
    assert row['verdict'] == 'say' and 'Kirby gets nothing' in row['how']


def test_the_one_player_line_is_not_answered_by_the_kirby_check(tmp_path):
    row = verify.run(_work(tmp_path))['answers']['12.12']
    assert 'Kirby' not in row['how']


def test_a_twelfth_face_group_is_a_fault(tmp_path):
    assert verify.run(_work(tmp_path, groups=12))['answers']['11.21']['verdict'] == 'FAULT'


def test_eleven_face_groups_fit(tmp_path):
    assert verify.run(_work(tmp_path))['answers']['11.21']['verdict'] == 'ok'


def test_the_artwork_is_not_asked_for_before_the_round_has_made_it(tmp_path):
    work = _work(tmp_path)
    assert verify.run(work)['answers']['7.5']['verdict'] == 'FAULT'
    assert '7.5' not in verify.run(work, art_later=True)['answers']


def test_a_check_that_cannot_read_its_receipt_is_not_an_answer_of_ok(tmp_path):
    answers = verify.run(_work(tmp_path))['answers']
    assert all(row['verdict'] != 'ok' or row['how'] for row in answers.values())
    assert answers['7.1']['verdict'] == 'FAULT'            # no sound receipt in this folder
    # ... and a check with no receipt of its own to read gives no answer at all: none of these says ok
    for line in ('2.2', '2.8', '3.1', '4.1', '4.8', '5.5', '6.22', '6.28', '6.34', '7.6', '7.13', '9.2', '9.4', '11.1', '12.14'):
        assert line not in answers, line


# ---- the folders the checks below read: the least of each receipt, made up ---------------------------------------
def _receipts(work, report=None, game=None, sound=None, clips=None):
    """Lay receipts into a `_work` folder: the driver's report and its reading of the game, the bank's, the clips'."""
    path = work / 'port' / 'report.json'
    path.write_text(json.dumps(dict(json.loads(path.read_text('utf-8')), fighter='fox', donor='Marth', **(report or {}))), 'utf-8')
    if game is not None:
        (work / 'port' / 'game.json').write_text(json.dumps(dict({'fighter': 'fox'}, **game)), 'utf-8')
    if sound is not None:
        (work / 'package' / 'sound.json').write_text(json.dumps(dict({'bank_bytes': 1000, 'left': []}, **sound)), 'utf-8')
    if clips is not None:
        (work / 'port' / 'spec').mkdir(exist_ok=True)
        (work / 'port' / 'spec' / 'moveset.json').write_text(json.dumps(
            {'clips': [{'source': f'motion/body/c00/{stem}.nuanmb', 'target_motion': motion} for stem, motion in clips.items()]}), 'utf-8')
    return work


def _plays(frame, name, cmd='PLAY_SE'):
    return {'cmd': cmd, 'real': frame, 'name': name, 'args': [name]}


def _sound_work(tmp_path, bank=('se_fox_special_n01',), swapped=None, dressed=None, more_moves=None, left=()):
    """A fighter whose neutral special's script plays two sounds, on frames 9 and 40, and whose roll plays one."""
    moves = {'game_specialn': {'hitboxes': [{'first': 9}], 'sounds': [_plays(9, 'se_fox_special_n01'), _plays(40, 'se_fox_special_n02')]},
             'game_escapef': {'hitboxes': [], 'sounds': [_plays(5, 'se_fox_escape'), _plays(19, 'se_fox_step_left_m')]},
             'game_finalstart': {'hitboxes': [{'first': 1}], 'sounds': [_plays(1, 'se_fox_final01')]}}
    moves.update(more_moves or {})
    swapped = swapped if swapped is not None else [{'sample': 'se_mars_sbreak', 'sound': 'se_fox_special_N01'}]
    return _receipts(_work(tmp_path), report={'own_sounds': sorted(bank), 'own_states': ['Blaster'],
                                              'dressed': dressed if dressed is not None else {'SpecialNEnd': ['swing 9 (its own: se_fox_special_n01)']}},
                     game={'moves': moves}, sound={'swapped': swapped, 'added': [], 'left': list(left)})


# ---- sounds are two lists ------------------------------------------------------------------------------------------
def test_a_sound_a_special_plays_that_the_bank_cannot_is_a_fault_and_says_where_it_is(tmp_path):
    work = _sound_work(tmp_path, swapped=[{'sample': 'se_mars_sbreak', 'sound': 'se_fox_special_N01'},
                                          {'sample': 'se_mars_sbreak_tame', 'sound': 'se_fox_special_N02'}])   # held, on a place that loops
    row = verify.run(work)['answers']['7.1']
    assert row['verdict'] == 'FAULT'
    assert 'se_fox_special_n02 (game_specialn frame 40; in the bank on se_mars_sbreak_tame' in row['how']
    assert 'played by no script or code of the port: se_fox_special_n02 (on se_mars_sbreak_tame)' in row['how']    # the second list
    assert 'se_fox_escape' not in row['how'] and '2 more in scripts the port does not write' in row['how']
    assert '1 of the final smash' in row['how']
    assert verify.run(work)['answers']['9.11'] == row                  # the listening by machine starts from the same lists


def test_a_bank_that_can_play_what_the_written_scripts_play_is_said_not_faulted(tmp_path):
    work = _sound_work(tmp_path, bank=('se_fox_special_n01', 'se_fox_special_n02'),
                       swapped=[{'sample': 'se_mars_sbreak', 'sound': 'se_fox_special_N01'}, {'sample': 'se_mars_dolphin', 'sound': 'se_fox_special_N02'}],
                       dressed={'SpecialNEnd': ['swing 9 (its own: se_fox_special_n01)', 'swing 40 (its own: se_fox_special_n02)']})
    answers = verify.run(work)['answers']
    assert answers['7.1']['verdict'] == 'say' and 'SILENT' not in answers['7.1']['how']
    assert 'played by no script' not in answers['7.1']['how']
    # the roll's own sound and its step are not the bank's to play: listed for the list given with the port
    assert answers['7.13']['verdict'] == 'say'
    assert 'se_fox_escape (game_escapef frame 5)' in answers['7.13']['how'] and 'se_fox_step_left_m' in answers['7.13']['how']
    assert 'final' not in answers['7.13']['how']


def test_a_sound_the_bank_receipt_lists_as_left_for_want_of_room_is_not_a_silent_fault(tmp_path):
    work = _sound_work(tmp_path, left=['se_fox_special_n02: its scripts play it, and the bank has no room for it'])
    row = verify.run(work)['answers']['7.1']
    assert row['verdict'] == 'say' and 'Left for want of room' in row['how']


def test_a_sample_on_a_voice_place_the_engine_plays_is_not_called_unplayed(tmp_path):
    work = _sound_work(tmp_path, bank=('se_fox_special_n01', 'se_fox_special_n02', 'vc_fox_jump01', 'vc_fox_win01'),
                       swapped=[{'sample': 'se_mars_sbreak', 'sound': 'se_fox_special_N01'}, {'sample': 'se_mars_dolphin', 'sound': 'se_fox_special_N02'},
                                {'sample': 'v_mars_jump', 'sound': 'vc_fox_jump01'},        # the engine plays this place as he jumps
                                {'sample': 'v_mars_bokuwa', 'sound': 'vc_fox_win01'}],      # nothing plays this one on the route
                       dressed={'SpecialNEnd': ['swing 9 (its own: se_fox_special_n01)', 'swing 40 (its own: se_fox_special_n02)']})
    report = work / 'port' / 'report.json'
    report.write_text(json.dumps(dict(json.loads(report.read_text('utf-8')), route='own skeleton')), 'utf-8')
    how = verify.run(work)['answers']['7.1']['how']
    assert 'vc_fox_win01 (on v_mars_bokuwa)' in how and 'vc_fox_jump01' not in how


def test_a_sound_the_code_plays_with_no_place_code_can_call_is_a_fault(tmp_path):
    code = {'port_code': {'hitboxes': [], 'code_plays': True, 'sounds': [_plays(1, 'se_fox_special_n03')]}}
    lost = verify.run(_sound_work(tmp_path / 'a', more_moves=code))['answers']
    assert lost['6.28']['verdict'] == lost['6.22']['verdict'] == 'FAULT' and 'se_fox_special_n03' in lost['6.28']['how']
    held = verify.run(_sound_work(tmp_path / 'b', bank=('se_fox_special_n01', 'se_fox_special_n03'), more_moves=code))['answers']
    assert held['6.28']['verdict'] == 'ok'
    none = verify.run(_sound_work(tmp_path / 'c'))['answers']['6.28']          # states of its own, and no sound named for its code
    assert none['verdict'] == 'say'


# ---- room is a sum of file sizes -----------------------------------------------------------------------------------
def _room_work(tmp_path, costume, data=268_336, effect=245_726):
    """A fighter whose data and effect file are where the build puts them (sizes as Wolf's were)."""
    work = _work(tmp_path, costume_bytes=costume)
    (work / 'port' / 'final').mkdir()
    (work / 'port' / 'final' / 'PlMs.dat').write_bytes(bytes(data))
    (work / 'port' / 'final' / 'EfFoxData.dat').write_bytes(bytes(effect))
    with zipfile.ZipFile(work / 'package' / 'Fighter.zip', 'w') as z:
        z.writestr('fighter.json', json.dumps({'name': 'Fighter', 'functions': {}, 'files': {'fighterDataPath': 'PlMs.dat', 'effectFile': 'EfFoxData.dat'}}))
    return work


def test_room_is_the_sum_the_game_read_for_wolf(tmp_path):
    # Wolf's last costume: the game's own readings were 1.85, 0.05 and 0.77 MB free (heap_two_fd, heap_two_ps, heap_peach_ps)
    row = verify.run(_room_work(tmp_path, 1_813_808))['answers']['11.26']
    assert row['verdict'] == 'say'                      # all three load, the tightest with 0.05 MB to spare
    assert 'Final Destination +1.85 MB' in row['how'] and 'the same on Pokemon Stadium +0.05 MB' in row['how']
    assert 'beside Peach on Pokemon Stadium +0.77 MB' in row['how']
    held = lambda *sizes: sum((n + 31) // 32 * 32 for n in sizes)
    assert verify.HEAP == 6_599_680
    assert verify.HEAP - held(268_336, 245_726, 1_813_808, 1_813_808) - 611_136 - 5 * 96 == 1_846_336    # the heap's own list, to the byte


def test_a_costume_that_does_not_fit_twice_on_the_largest_stage_is_a_fault(tmp_path):
    # Wolf's first costume: the game hung after stage select in all three matches, and a probe had called two of them passes
    row = verify.run(_room_work(tmp_path, 3_386_672))['answers']['11.26']
    assert row['verdict'] == 'FAULT' and row['how'].count('-') >= 3 and 'DOES NOT FIT' in row['how']
    small = verify.run(_room_work(tmp_path / 'small', 900_000))['answers']['11.26']
    assert small['verdict'] == 'ok'


def test_room_counts_the_fighters_own_data_file(tmp_path):
    # Duck Hunt's data file holds the things his specials make (691,276 bytes): two of him do not fit on Pokemon Stadium
    row = verify.run(_room_work(tmp_path, 1_811_988, data=691_276, effect=256_706))['answers']['11.26']
    assert row['verdict'] == 'FAULT' and 'the same on Pokemon Stadium -0.38 MB' in row['how']
    assert 'beside Peach on Pokemon Stadium +0.34 MB' in row['how']         # the figure read in the game for him


def test_room_without_the_fighters_data_file_gives_no_answer_unless_it_already_does_not_fit(tmp_path):
    assert '11.26' not in verify.run(_work(tmp_path / 'a', costume_bytes=1_000_000))['answers']
    assert verify.run(_work(tmp_path / 'b', costume_bytes=2_300_000))['answers']['11.26']['verdict'] == 'FAULT'


# ---- facing left is a list of clip names ---------------------------------------------------------------------------
def test_a_clip_kept_in_a_second_copy_for_facing_left_and_not_carried_is_said(tmp_path):
    motions = {name: {} for name in ('d03speciallwstart', 'd03speciallwstartl', 'a00wait1', 'a02runbrakel', 'a02runbraker', 'a04fall')}
    work = _receipts(_work(tmp_path / 'a'), game={'motions': motions}, clips={'d03speciallwstart': 'SpecialLw', 'a00wait1': 'Wait1', 'a02runbrakel': 'RunBrake'})
    row = verify.run(work)['answers']['2.8']
    assert row['verdict'] == 'say' and 'not d03speciallwstartl' in row['how'] and 'a04fall' not in row['how']
    assert 'a02runbrakel' in row['how']                 # told, and not judged
    both = _receipts(_work(tmp_path / 'b'), game={'motions': motions},
                     clips={'d03speciallwstart': 'SpecialLw', 'd03speciallwstartl': 'SpecialS4S', 'a00wait1': 'Wait1'})
    assert verify.run(both)['answers']['2.8']['verdict'] == 'ok'
    none = _receipts(_work(tmp_path / 'c'), game={'motions': {'a00wait1': {}, 'a04fall': {}}}, clips={'a00wait1': 'Wait1'})
    assert verify.run(none)['answers']['2.8']['verdict'] == 'ok'


# ---- frames and damage are in the route's own table ----------------------------------------------------------------
def _row(action, **more):
    return dict({'move': 'x', 'action': action, 'clip': 'c00' + action.lower(), 'frames': 30}, **more)


def _moves_work(tmp_path, rows, grabs=None, untouchable=None, params=None):
    shared = {'grabs': grabs if grabs is not None else {}, 'untouchable': untouchable if untouchable is not None else {'EscapeN': [3, 17]}, 'unread': []}
    return _receipts(_work(tmp_path), report={'moves': rows, 'scripts': {'written': len(rows), 'failed': [], 'no_hitboxes': []}, 'shared': shared},
                     game={'motion_params': params or {'escape_n_hit_xlu_frame': 3.0, 'escape_n_hit_normal_frame': 15.0}})


JAB = dict(first=4, boxes=['Top(2)', 'Top(2)'], damage=[2], acts=22, game_first=4, game_boxes=['top(1.5)'], game_damage=[1.5], game_acts=22)
GRAB = dict(first=5, boxes=['Top(grab)'] * 4, damage=[], acts=None, game_first=6, game_boxes=['top(grab)'] * 2, game_acts=31)
THROW = dict(acts=30, throw='8% at 44', game_throw='8.5% at 44', game_acts=30)


def test_the_drivers_own_rules_are_not_faults(tmp_path):
    # a drawn-out hitbox as two balls, 1.5 as 2, a grab a frame early with no frame to act on (it ends with its clip)
    work = _moves_work(tmp_path, [_row('Attack11', **JAB), _row('Catch', **GRAB), _row('ThrowLw', **THROW)],
                       grabs={'Catch': {'first': 6, 'end': 8, 'boxes': 4}})
    answers = verify.run(work)['answers']
    assert answers['2.2']['verdict'] == answers['9.2']['verdict'] == 'ok' and '1 end with their clip' in answers['2.2']['how']
    assert answers['4.1']['verdict'] == 'say' and 'ThrowLw' in answers['4.1']['how']        # (a throw has no hitbox of its own)
    assert answers['4.8']['verdict'] == 'say' and '8.5% at 44 is written 8% at 44' in answers['4.8']['how']
    assert answers['3.1']['verdict'] == 'ok' and 'EscapeN 3 to 17' in answers['3.1']['how']


def test_a_free_frame_that_is_not_the_games_is_a_fault(tmp_path):
    row = verify.run(_moves_work(tmp_path, [_row('Attack11', **dict(JAB, acts=25))]))['answers']['2.2']
    assert row['verdict'] == 'FAULT' and "Attack11 frees him on 25 for the game's 22" in row['how']


def test_a_first_hit_frame_or_a_damage_that_is_not_the_games_is_a_fault(tmp_path):
    late = verify.run(_moves_work(tmp_path / 'a', [_row('Attack11', **dict(JAB, first=5))]))['answers']['4.1']
    assert late['verdict'] == 'FAULT' and "first hits on 5 for the game's 4" in late['how']
    weak = verify.run(_moves_work(tmp_path / 'b', [_row('Attack11', **dict(JAB, damage=[1]))]))['answers']['9.4']
    assert weak['verdict'] == 'FAULT' and 'does [1]' in weak['how']
    grab = verify.run(_moves_work(tmp_path / 'c', [_row('Catch', **dict(GRAB, first=6))]))['answers']['4.1']
    assert grab['verdict'] == 'FAULT' and 'a grab is written 1 early' in grab['how']


def test_a_grab_or_a_throw_that_is_not_the_games_is_a_fault(tmp_path):
    late = _moves_work(tmp_path / 'a', [_row('Catch', **GRAB)], grabs={'Catch': {'first': 8, 'end': 10, 'boxes': 4}})
    assert verify.run(late)['answers']['4.8']['verdict'] == 'FAULT'
    turned = _moves_work(tmp_path / 'b', [_row('Catch', **GRAB), _row('ThrowLw', **dict(THROW, throw='8% at 60'))],
                         grabs={'Catch': {'first': 6, 'end': 8, 'boxes': 4}})
    row = verify.run(turned)['answers']['4.8']
    assert row['verdict'] == 'FAULT' and 'ThrowLw throws for 8% at 60' in row['how']


def test_dodge_frames_that_are_not_the_dodge_tables_are_said_and_none_written_is_a_fault(tmp_path):
    off = verify.run(_moves_work(tmp_path / 'a', [_row('Attack11', **JAB)], untouchable={'EscapeN': [3, 20]}))['answers']['3.1']
    assert off['verdict'] == 'say' and "EscapeN 3 to 20 for the table's 3 to 17" in off['how']
    none = verify.run(_moves_work(tmp_path / 'b', [_row('Attack11', **JAB)], untouchable={}))['answers']['3.1']
    assert none['verdict'] == 'FAULT'


def test_no_dodge_frames_is_said_not_a_fault_when_the_reader_says_the_game_keeps_none(tmp_path):
    # Rivals 2 runs its dodges as engine code: no file holds their frames, and the donor's stay (checklist 3.10)
    work = _receipts(_work(tmp_path), report={'moves': [_row('Attack11', **JAB)], 'shared': {'grabs': {}, 'untouchable': {}, 'unread': []},
                                              'scripts': {'written': 1, 'failed': [], 'no_hitboxes': []}},
                     game={'motion_params': {}, 'no_dodge_frames': 'the game keeps them in code'})
    row = verify.run(work)['answers']['3.1']
    assert row['verdict'] == 'say' and 'the game keeps them in code' in row['how']


def test_the_fighters_numbers_are_never_passed_on_a_count(tmp_path):
    some = verify.run(_receipts(_work(tmp_path / 'a'), report={'attributes': {'set': 31, 'notes': []}}))['answers']['5.5']
    assert some['verdict'] == 'say' and 'count only' in some['how']
    none = verify.run(_receipts(_work(tmp_path / 'b'), report={'attributes': {'set': 0, 'notes': []}}))['answers']['5.5']
    assert none['verdict'] == 'FAULT'


# ---- what else the trial showed the receipts hold ------------------------------------------------------------------
def test_scripts_that_flash_the_body_with_no_flash_played_is_a_fault(tmp_path):
    game = {'moves': {'game_speciallwhit': {'flashes': [[1, [255, 153, 204, 178], 0]]}, 'game_attack11': {}}}
    assert verify.run(_receipts(_work(tmp_path / 'a'), game=game))['answers']['7.6']['verdict'] == 'FAULT'
    played = verify.run(_receipts(_work(tmp_path / 'b'), report={'own_flashes': [311]}, game=game))['answers']['7.6']
    assert played['verdict'] == 'ok' and 'game_speciallwhit' in played['how']
    assert '7.6' not in verify.run(_receipts(_work(tmp_path / 'c'), game={'moves': {'game_attack11': {}}}))['answers']


def test_a_specials_hitboxes_that_were_written_nowhere_are_said(tmp_path):
    note = 'game_specialn: 3 hitboxes in the script the reader keeps for d00specialn; not written (nothing is built for a special)'
    kept = verify.run(_receipts(_work(tmp_path / 'a'), report={'scripts': {'written': 1, 'notes': [note]}}))['answers']['6.34']
    assert kept['verdict'] == 'say'
    done = verify.run(_receipts(_work(tmp_path / 'b'), report={'special_hits': {'written': ['SpecialLw'], 'failed': []}}))['answers']['6.34']
    assert done['verdict'] == 'ok'
    bad = verify.run(_receipts(_work(tmp_path / 'c'), report={'special_hits': {'written': [], 'failed': ['speciallw']}}))['answers']['6.34']
    assert bad['verdict'] == 'FAULT'


def test_win_poses_with_no_sound_of_their_own_are_said(tmp_path):
    quiet = verify.run(_receipts(_work(tmp_path / 'a'), report={'demo': {'scripts': {'voiced': {}}}}))['answers']['12.14']
    assert quiet['verdict'] == 'say'
    voiced = verify.run(_receipts(_work(tmp_path / 'b'), report={'demo': {'scripts': {'voiced': {'0': 'j02win1'}}}}))['answers']['12.14']
    assert voiced['verdict'] == 'ok' and 'j02win1' in voiced['how']


def test_joints_too_deep_are_a_fault(tmp_path):
    work = _receipts(_work(tmp_path), report={'own': {'joints': 100}, 'check': {'ok': True, 'largest_clip': {'motion': 'Wait1', 'bytes': 2000}}})
    (work / 'rig').mkdir()
    (work / 'rig' / 'rig-fox.json').write_text(json.dumps({'provenance': {'depth': 30}}), 'utf-8')
    row = verify.run(work)['answers']['11.1']
    assert row['verdict'] == 'FAULT' and 'joints 30 deep (limit 29)' in row['how']
    (work / 'rig' / 'rig-fox.json').write_text(json.dumps({'provenance': {'depth': 20}}), 'utf-8')
    assert 'joints 20 deep of 29' in verify.run(work)['answers']['11.1']['how']


def _effect_work(tmp_path, behaviours, follow=None, cmds=('EFFECT_FOLLOW',)):
    """A fighter whose up special's script calls one effect of its own (`cmds`: how the game's scripts call it),
    built into generators of these behaviours; `follow`: what the receipt says of the call (None: an older receipt
    that says nothing of it)."""
    from fighter_port import own_effects as oe
    blocks = [oe.generator([(oe.WAIT, [2]), (oe.END, [])], life=2) for _ in behaviours]
    groups = [dict(format=oe.I8, width=8, height=8, images=[bytes(oe.image_bytes(oe.I8, 8, 8))])]
    data = oe.effect_file('effFoxDataTable', blocks, list(behaviours), groups)
    row = dict(action='SpecialHi', frame=2, bone='rot', size=1.1, generators=[[0, n, 3] for n in range(len(behaviours))])
    if follow is not None:
        row['follow'] = follow
    work = _receipts(_work(tmp_path), report={'effect_file': {'file': 'EfFoxData.dat', 'uses': {'fox_fire': [row]}}},
                     game={'moves': {'game_specialhi': {'effects': [{'cmd': c, 'real': 2, 'name': 'fox_fire'} for c in cmds]
                                                        + [{'cmd': 'EFFECT_OFF_KIND', 'real': 9, 'name': 'fox_fire'}]}}})
    with zipfile.ZipFile(work / 'package' / 'Fighter.zip', 'a') as z:
        z.writestr('EfFoxData.dat', data)
    return work


def test_an_effect_that_follows_a_bone_given_off_once_where_the_move_began_is_a_fault(tmp_path):
    # Wolf's Fire Wolf, 2026-11-13: the receipt said 3 for every generator, and so did the built file
    row = verify.run(_effect_work(tmp_path / 'a', [3, 6], follow=True))['answers']['7.17']
    assert row['verdict'] == 'FAULT' and 'fox_fire (SpecialHi frame 2 on rot: 1 of 2' in row['how'] and 'EfFoxData.dat' in row['how']
    held = verify.run(_effect_work(tmp_path / 'b', [6, 6], follow=True))['answers']['7.17']
    assert held['verdict'] == 'ok' and '1 calls that follow a bone' in held['how']
    # an older receipt says nothing of the call: the game's scripts say it follows (switching it off is no call)
    old = verify.run(_effect_work(tmp_path / 'c', [3], follow=None))['answers']['7.17']
    assert old['verdict'] == 'FAULT'
    # a burst the game gives off once is right as it is
    once = verify.run(_effect_work(tmp_path / 'd', [3], follow=None, cmds=('EFFECT', 'EFFECT_FOLLOW')))['answers']['7.17']
    assert once['verdict'] == 'ok' and 'no effect' in once['how']
    assert verify.run(_effect_work(tmp_path / 'e', [3], follow=False))['answers']['7.17']['verdict'] == 'ok'
    assert '7.17' not in verify.run(_work(tmp_path / 'f'))['answers']          # no effect receipt: no answer


def test_the_effect_file_is_read_from_the_zip_this_run_wrote_not_one_an_earlier_run_left(tmp_path):
    # the Trainer, 2026-11-13: a Squirtle.zip from an earlier run beside the Pokemon Trainer.zip the run wrote;
    # 7.17 read the old one (the last by name) and called held generators given off once
    import os
    from fighter_port import own_effects as oe
    work = _effect_work(tmp_path, [6, 6], follow=True)
    blocks = [oe.generator([(oe.WAIT, [2]), (oe.END, [])], life=2) for _ in range(2)]
    groups = [dict(format=oe.I8, width=8, height=8, images=[bytes(oe.image_bytes(oe.I8, 8, 8))])]
    old = work / 'package' / 'Squirtle.zip'
    with zipfile.ZipFile(old, 'w') as z:
        z.writestr('EfFoxData.dat', oe.effect_file('effFoxDataTable', blocks, [3, 3], groups))
    os.utime(old, (1_000_000_000, 1_000_000_000))
    row = verify.run(work)['answers']['7.17']
    assert row['verdict'] == 'ok' and 'Fighter.zip/EfFoxData.dat' in row['how']


def test_the_particles_line_counts_flattened_shapes_apart_from_refused_ones(tmp_path):
    e = dict(file='EfFoxData.dat', generators=12, bytes=40000, uses={}, not_carried={'P_FoxRing': [dict(emitter='bend', why=['x'])]},
             shapes=dict(carried=5, refused=2, why={'it only bends what is behind it (a refraction): it has nothing of its own to draw': 2}),
             pictures={'combined': 3, 'stand-in': 1, 'left out': 2})
    row = verify.run(_receipts(_work(tmp_path / 'a'), report={'effect_file': e}))['answers']['7.10']
    assert row['verdict'] == 'say' and '3D shapes: 5 carried as flattened STAND-INS, 2 refused (2 it only bends' in row['how']
    assert 'emitters of several pictures: 3 combined, 2 left out, 1 stand-in' in row['how']
    e['fitted'] = ['ring with ef_ring 1x1 flattened (billboard)']
    fitted = verify.run(_receipts(_work(tmp_path / 'c'), report={'effect_file': e}))['answers']['7.10']['how']
    assert '1 pictures made smaller to fit the texture bank' in fitted
    older = {k: v for k, v in e.items() if k not in ('shapes', 'pictures', 'fitted')}  # a receipt from before: no counts
    assert '3D shapes' not in verify.run(_receipts(_work(tmp_path / 'b'), report={'effect_file': older}))['answers']['7.10']['how']


def test_a_damage_the_four_hitbox_rule_left_out_is_said_not_a_fault(tmp_path):
    # the game's down smash has five hitboxes out at once; Melee holds four and the driver kept the strongest four
    row = _row('AttackLw4', first=13, boxes=['Top(10)', 'Top(12)'], damage=[10, 12], acts=46, game_first=13,
               game_boxes=['top(8)', 'top(10)', 'top(12)'], game_damage=[8.0, 10.0, 12.0], game_acts=46)
    shared = {'grabs': {}, 'untouchable': {'EscapeN': [3, 17]}, 'unread': []}
    note = 'game_attacklw4: 5 hitboxes at frame 13; Melee holds 4, kept the strongest'
    said = _receipts(_work(tmp_path / 'a'), report={'moves': [row], 'shared': shared, 'scripts': {
        'written': 1, 'failed': [], 'no_hitboxes': [], 'notes': [note]}},
        game={'motion_params': {'escape_n_hit_xlu_frame': 3.0, 'escape_n_hit_normal_frame': 15.0}})
    got = verify.run(said)['answers']['4.1']
    assert got['verdict'] == 'say' and 'the strongest four kept' in got['how'] and 'AttackLw4' in got['how']
    # without the driver's note it is a fault
    bare = verify.run(_moves_work(tmp_path / 'b', [row]))['answers']['4.1']
    assert bare['verdict'] == 'FAULT'


def test_costumes_of_another_model_are_held_only_against_that_model(tmp_path):
    work = _work(tmp_path)
    rows = [{'file': f'PlMs{c}.dat', 'folder': f, 'name': f, 'model': m}
            for c, f, m in (('Nr', 'c00', 'c00'), ('Re', 'c01', 'c00'), ('Ye', 'c04', 'c04'), ('Pi', 'c07', 'c04'))]
    (work / 'package' / 'costumes' / 'costumes.json').write_text(json.dumps(rows), 'utf-8')
    for r, size in zip(rows, (1000, 1000, 1200, 1200)):
        (work / 'package' / 'costumes' / r['file']).write_bytes(bytes(size))
    row = verify.run(work)['answers']['1.2']
    assert row['verdict'] == 'ok' and 'of 2 models' in row['how']
    (work / 'package' / 'costumes' / 'PlMsPi.dat').write_bytes(bytes(1300))       # one of c04's model differs
    assert verify.run(work)['answers']['1.2']['verdict'] == 'FAULT'


def test_a_shield_joint_with_joints_under_it_is_a_fault(tmp_path):
    """Melee scales the shield's joint to the shield's size: Ittle Dew's fell to YRot, and the whole body grew six
    times behind a full shield while every check said ok. Only the round's picture showed it."""
    work = _work(tmp_path)
    assert '11.42' not in verify.run(work)['answers']               # no receipt: no answer
    data = json.loads((work / 'data' / 'report.json').read_text('utf-8'))
    for under, verdict in ((['Hip', 'Waist', 'LegL'], 'FAULT'), ([], 'ok')):
        data['shield'] = dict(joint=3 if under else 58, name='__engine_YRot' if under else 'Throw', under=under)
        (work / 'data' / 'report.json').write_text(json.dumps(data), 'utf-8')
        row = verify.run(work)['answers']['11.42']
        assert row['verdict'] == verdict, row


def test_missing_source_sfx_id_is_reported_but_a_failed_export_still_faults(tmp_path):
    work=_sound_work(tmp_path)
    path=work/'port/game.json'
    game=json.loads(path.read_text())
    game['game']='slapcity'
    event=game['moves']['game_specialn']['sounds'][1]
    event['source_sound']={'bank':'fighter','id':'missing','exists':False}
    path.write_text(json.dumps(game))
    got=verify.run(work)['answers']['7.1']
    assert got['verdict']=='say' and 'Silent in the source game' in got['how']
    event['source_sound']['exists']=True
    path.write_text(json.dumps(game))
    assert verify.run(work)['answers']['7.1']['verdict']=='FAULT'
