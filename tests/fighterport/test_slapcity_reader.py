"""Slap City, a Unity game, carried on the fighter's own skeleton by writing it out in Ultimate's shapes first
(`echo_slapcity`, `fighter_port/source_game.py`), and what the route needed to read such a game.

The last tests read the game itself (small samples: one fighter's prefab, its moveset, one sound) and run only when
SLAP names the game's data folder and UNITY_PYDEPS the folder UnityPy is installed in."""
import io
import json
import os
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from echo_slapcity import gamedata, sounds
from fighter_port import source_game


def test_landmarks_use_the_fighters_shortcuts_when_its_bones_have_other_names():
    from echo_slapcity.transcode import landmark_names
    got = landmark_names(['superbody', 'r_arm', 'r_arm2', 'r_hand', 'l_hand', 'r_leg'],
                         {'shoulder_r': 'r_arm', 'elbow_r': 'r_arm2', 'hand_r': 'r_hand',
                          'hand_l': 'l_hand', 'leg_r': 'r_leg'})
    assert got == {'superbody': 'Hip', 'r_arm': 'ShoulderR', 'r_arm2': 'ArmR', 'r_hand': 'HandR',
                   'l_hand': 'HandL', 'r_leg': 'LegR'}
    # Jenny Fox's hands are the axe bones: the shortcut, not a list of guessed bone names, resolves them.
    assert landmark_names(['r_axe'], {'r_hand': 'r_axe'}) == {'r_axe': 'HandR'}


def test_landmark_shortcuts_keep_the_first_two_fighters_existing_joints():
    from echo_slapcity.transcode import landmark_names, NAMES
    bones = list(NAMES) + ['midhead', 'r_hand', 'l_hand']
    assert landmark_names(bones, {'head': 'midhead', 'hand_r': 'r_hand', 'hand_l': 'l_hand'}) == \
        {name: NAMES.get(name, name) for name in bones}


def test_landmark_shortcuts_cannot_take_another_landmark_or_an_unkept_helper():
    from echo_slapcity.transcode import landmark_names
    assert landmark_names(['r_arm2'], {'r_hand': 'effect', 'hand_r': 'r_arm2'}) == {'r_arm2': 'ArmR'}
    with pytest.raises(ValueError, match='HandR: conflicting bone shortcuts'):
        landmark_names(['hand_a', 'hand_b'], {'r_hand': 'hand_a', 'hand_r': 'hand_b'})


def test_one_starting_clip_is_written_for_both_ground_and_air_specials():
    from echo_slapcity.transcode import clip_stems
    moves = {'spf': {'tl': [{'af': 0, 'a': {'t': 'SAPA', 'a': 'specialforward'}}]},
             'spu': {'tl': [{'af': 0, 'a': {'t': 'SAPA', 'a': 'specialup'}}]}}
    stems = clip_stems(['specialforward', 'specialup'], moves, {'spF': 'spf', 'spU': 'spu'})
    assert stems['specialforward'] == ['d01specials', 'd01specialairs']
    assert stems['specialup'] == ['d02specialhi', 'd02specialairhi']


def test_shared_clip_aliases_keep_distinct_air_clips_and_do_not_guess_conditional_starts():
    from echo_slapcity.transcode import clip_stems
    start = {'t': 'SAPA', 'a': 'specialforward'}
    moves = {'spf': {'tl': [{'af': 0, 'a': start}]}}
    stems = clip_stems(['specialforward', 'specialforwardair'], moves, {'spF': 'spf'})
    assert stems['specialforward'] == ['d01specials'] and stems['specialforwardair'] == ['d01specialairs']
    moves['spf']['tl'][0]['a'] = {'t': 'SACT', 'a': start}
    assert clip_stems(['specialforward'], moves, {'spF': 'spf'})['specialforward'] == ['d01specials']


def test_clip_aliases_can_serve_several_inputs_without_changing_global_stems():
    from echo_slapcity.transcode import clip_stems, STEMS
    before = list(STEMS['specialneutral'])
    moves = {'spn': {'tl': [{'af': 0, 'a': {'t': 'SAPA', 'a': 'specialneutral'}}]}}
    stems = clip_stems(['specialneutral'], moves, {'spN': 'spn', 'spF': 'spn'})
    assert set(stems['specialneutral']) == {'d00specialn', 'd00specialairn', 'd01specials', 'd01specialairs'}
    assert STEMS['specialneutral'] == before


def test_roster_lists_input_tables_and_missing_moves_without_exporting(monkeypatch):
    from echo_slapcity import roster
    container = {'smash/characters/tester/tester': None, 'smash/characters/tester/skins/default': None,
                 'smash/characters/broken/broken': None, 'smash/characters/tester/projectile': None}
    def fighter(_game, name):
        if name == 'broken':
            raise KeyError('no character component')
        return SimpleNamespace(character={'standardSCinputTrigger': {'spN': 'burst', 'spF': 'burst',
                                'jumps': ['squat', 'jump'], 'spU': 'missing'}},
                               moveset=lambda: {'burst': {}, 'squat': {}, 'jump': {}})
    monkeypatch.setattr(roster, 'Fighter', fighter)
    rows = roster.roster(SimpleNamespace(container=lambda: container))
    assert [r['fighter'] for r in rows] == ['broken', 'tester']
    assert 'KeyError' in rows[0]['error']
    assert rows[1]['moves'] == 3 and rows[1]['missing_moves'] == ['missing']
    assert rows[1]['inputs']['spN'] == rows[1]['inputs']['spF'] == 'burst'


def test_roster_cli_accepts_a_game_folder_without_a_fighter_or_output(monkeypatch, capsys):
    from echo_slapcity import __main__, roster
    game = object()
    monkeypatch.setattr(__main__, 'Game', lambda path: game)
    monkeypatch.setattr(roster, 'roster', lambda g: [{'fighter': 'tester', 'inputs': {}}] if g is game else [])
    assert __main__.main(['install', '--list']) == 0
    assert json.loads(capsys.readouterr().out) == [{'fighter': 'tester', 'inputs': {}}]
    monkeypatch.setattr(roster, 'roster', lambda g: [{'fighter': 'broken', 'error': 'unreadable'}])
    assert __main__.main(['install', '--list']) == 1


# ------------------------------------------------------------------------------------------ the move scripts
def test_a_moves_timeline_is_read_to_leaf_actions_on_their_frames():
    move = {'tl': [
        {'af': 0, 'a': {'t': 'SAOS', 'ac': [{'t': 'SAPA', 'a': 'jab0', 'cfg': {'rt': 1}},
                                            {'t': 'SAT', 'f': {'f': 3}, 'a': {'t': 'SAPSFX', 's': 'smallwhiff'}}]}},
        {'af': 5, 'a': {'t': 'SACT', 'a': {'t': 'SACH', 'h': 0}, 'e': True, 'ea': {'t': 'SAEA'}}},
        {'af': 9, 'a': {'t': 'SAOL', 'a': {'t': 'SACH', 'h': 1}}},           # a loop: not read
    ]}
    got = [(f, cond, a['t']) for f, cond, a in gamedata.events(move)]
    assert got == [(0.0, 0, 'SAPA'), (3.0, 0, 'SAPSFX'), (5.0, 1, 'SACH'), (5.0, 1, 'SAEA')]


def test_time_keys_follow_the_clips_rate_and_a_hold():
    # the clip from the first frame, held still from frame 6 (a smash's charge), then on at its own pace
    keys = gamedata.time_keys([(1, 1.0, 'fsmash', True), (6, 0.0, 'fsmash', False), (9, 1.0, 'fsmash', False)],
                              'fsmash', 1, 14)
    assert keys == [[0, 0.0], [5, 5.0], [8, 5.0], [13, 10.0]]


def test_an_offset_on_a_bone_is_mirrored_and_scaled_into_the_ports_joint_space():
    rd = gamedata.Reader(None, {}, {'unit': 2.0, 'armature_scale': 10.0, 'shortcuts': {}}, 1.0)
    assert rd.offset([0.1, 0.2, -0.3]) == pytest.approx([-2.0, 4.0, -6.0])


# ---------------------------------------------------------------------------------------------- the sounds
def _wav(path, pcm, rate=22050, channels=1):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(pcm, '<i2').tobytes())


def test_a_sound_is_named_in_ultimates_words():
    assert sounds.name_of('ittledew', 'smallwhiff') == 'se_ittledew_smallwhiff'
    assert sounds.name_of('ittledew', 'holler') == 'vc_ittledew_holler'          # her one voice
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(np.array([100, 300, -50, -150], '<i2').tobytes())
    got = sounds.mono(buf.getvalue())
    assert got['rate'] == 44100 and got['pcm'].tolist() == [200, -100]          # the channels averaged


def _written_root(tmp_path):
    folder = tmp_path / 'gamedata' / 'fighter' / 'ittledew' / 'sound'
    folder.mkdir(parents=True)
    _wav(folder / 'se_ittledew_smallwhiff.wav', [1, 2, 3, 4], channels=2)
    _wav(folder / 'vc_ittledew_holler.wav', [5, 6])
    (folder / 'sounds.json').write_text(json.dumps({
        'se_ittledew_smallwhiff': {'file': 'se_ittledew_smallwhiff.wav', 'also': ['se_ittledew_swing_s']},
        'vc_ittledew_holler': {'file': 'vc_ittledew_holler.wav', 'also': ['vc_ittledew_knockout']}}), 'utf-8')
    return tmp_path


def test_a_written_games_sounds_are_read_as_a_bank_under_their_names_and_their_other_words(tmp_path):
    from fighter_port import voice
    root = _written_root(tmp_path)
    banks = voice._banks(root, 'ittledew', 'slapcity')
    assert set(banks['se']) == {'se_ittledew_smallwhiff', 'se_ittledew_swing_s'}
    assert set(banks['vc']) == {'vc_ittledew_holler', 'vc_ittledew_knockout'} and banks['cheer'] == {}
    # the other word is the same sound under its own name: a row that finds it places the sound once
    assert banks['se']['se_ittledew_swing_s'] is banks['se']['se_ittledew_smallwhiff']
    name, sound = banks['se']['se_ittledew_swing_s']
    assert name == 'se_ittledew_smallwhiff' and sound['rate'] == 22050 and sound['pcm'].tolist() == [2, 4]
    # a written game has no announcer call, and nothing opens an archive for one
    assert voice.announcer(root, 'ittledew', 'slapcity') is None
    assert source_game.sounds(tmp_path / 'nothing', 'ittledew') == {'se': {}, 'vc': {}, 'cheer': {}}


# ----------------------------------------------------------------------------- what the route reads instead
def test_a_written_games_files_stand_in_for_the_archive(tmp_path):
    from echo_ultimate.gamedata import arc
    from fighter_port import recolors
    assert source_game.written('slapcity') and not source_game.written('ultimate') and not source_game.written('brawl')
    with pytest.raises(SystemExit, match='python -m echo_'):
        source_game.game_data(tmp_path, 'ittledew')
    body = tmp_path / 'gamedata' / 'fighter' / 'ittledew' / 'model' / 'body'
    for c, mesh in (('c00', b'one'), ('c01', b'one'), ('c04', b'another')):
        (body / c).mkdir(parents=True)
        (body / c / 'model.numshb').write_bytes(mesh)
        for n in ('ittle_ramps_col', 'ittle_eyes_col'):
            (body / c / f'{n}.nutexb').write_bytes(b'x')
    (body.parent.parent / 'game.json').write_text(json.dumps({'moves': {}, 'source_tables': {'hurt': [1], 'ecb': [2]}}))
    # no Hashes_FullPath: the files on the disk are what there is
    assert arc.fetch_fighter(tmp_path, 'ittledew') == (10, 10)
    assert recolors.costume_folders(tmp_path, 'ittledew') == {c: ['ittle_eyes_col', 'ittle_ramps_col'] for c in ('c00', 'c01', 'c04')}
    # a costume under the same pictures' names may still be a model of its own (Slap City's other outfits)
    assert not recolors.own_model(tmp_path, 'ittledew', 'c01') and recolors.own_model(tmp_path, 'ittledew', 'c04')
    assert source_game.tables(tmp_path, 'ittledew') == {'hurt': [1], 'ecb': [2]}


def test_preflight_names_each_file_a_written_game_lacks(tmp_path):
    from fighter_port import preflight
    said = {'problem': [], 'ok': [], 'note': []}
    lines = SimpleNamespace(problem=lambda *a: said['problem'].append(a), ok=lambda *a: said['ok'].append(a),
                            note=lambda *a: said['note'].append(a))
    a = SimpleNamespace(root=tmp_path, fighter='ittledew', game='slapcity')
    assert preflight.written_files(lines, a) is None
    assert len(said['problem']) == 6                    # four model files, game.json, the clips
    assert all('echo_slapcity' in p[1] for p in said['problem'][:5])
    folder = source_game.folder(tmp_path, 'ittledew')
    (folder / 'model' / 'body' / 'c00').mkdir(parents=True)
    for n in ('model.nusktb', 'model.numshb', 'model.numdlb', 'model.numatb'):
        (folder / 'model' / 'body' / 'c00' / n).write_bytes(b'x')
    (folder / 'game.json').write_text('{}')
    (folder / 'motion' / 'body' / 'c00').mkdir(parents=True)
    (folder / 'motion' / 'body' / 'c00' / 'a00wait1.nuanmb').write_bytes(b'x')
    said['problem'].clear()
    # every file there: the stages can read them, and what is IN them is the reader check's to say (here, all wrong)
    assert preflight.written_files(lines, a) == folder
    assert {p[0] for p in said['problem']} >= {"the reader's game.json"}


def test_a_landmark_the_body_has_no_bone_for_stands_at_the_next_one_up_the_chain():
    from fighter_port.oneshot import stand_in_landmarks
    marks = {'pelvis': 'Hip', 'spine': 'Waist', 'chest': 'Bust', 'neck': 'Neck', 'head': 'Head',
             'l_collar': 'ClavicleL', 'r_collar': 'ClavicleR', 'l_wrist': 'HandL'}
    said = []
    got = stand_in_landmarks(dict(marks), {'Hip', 'Bust', 'Head', 'HandL'}, said.append)
    # one spine bone (Bust): the spine stands at the hips, the neck and collars at the chest
    assert got['spine'] == 'Hip' and got['neck'] == 'Bust' and got['l_collar'] == got['r_collar'] == 'Bust'
    assert got['chest'] == 'Bust' and got['head'] == 'Head' and len(said) == 4
    # a body that lacks a bone the chain cannot stand in for keeps the missing name, for the caller to refuse
    assert stand_in_landmarks(dict(marks), {'Bust'}, said.append)['pelvis'] == 'Hip'


def test_a_picture_written_as_nutexb_reads_back_the_same(tmp_path):
    from PIL import Image
    from echo_ultimate import nutexb
    rng = np.random.default_rng(1)
    image = Image.fromarray(rng.integers(0, 256, (64, 32, 4), dtype=np.uint8), 'RGBA')
    nutexb.write(tmp_path / 'p_col.nutexb', image)
    back, header = nutexb.read(tmp_path / 'p_col.nutexb')
    assert header['width'] == 32 and header['height'] == 64
    assert np.array_equal(np.asarray(back), np.asarray(image))


def test_the_costume_stage_lets_only_a_model_of_its_own_cost_otherwise():
    text = (Path(source_game.__file__).parent / 'harness' / 'own_costumes.py').read_text('utf-8')
    assert "same[:2] != first[:2] or (same[2] != first[2] and not recolors.own_model(root, fighter, folder))" in text


def test_the_identity_of_a_written_game_comes_from_its_files():
    text = (Path(source_game.__file__).parent / 'harness' / 'own_identity.py').read_text('utf-8')
    assert "if not (root / 'Hashes_FullPath').exists() and written.is_dir():" in text and 'def from_written(' in text


# ------------------------------------------------------------------------------------------- the game itself
SLAP = os.environ.get('SLAP')
needs_game = pytest.mark.skipif(not (SLAP and Path(SLAP, 'globalgamemanagers').is_file() and os.environ.get('UNITY_PYDEPS')),
                                reason='SLAP (the game data folder) and UNITY_PYDEPS (UnityPy) are not set')


@pytest.fixture(scope='module')
def ittle():
    from echo_slapcity.fighter import Fighter
    from echo_slapcity.unity import Game
    return Fighter(Game(SLAP), 'ittledew')


@needs_game
def test_the_fighters_prefab_bones_and_shortcuts(ittle):
    nodes = ittle.nodes()
    names = [n['name'] for n in nodes]
    assert names[0] == 'IttleDew' and 'Armature' in names and 'superbody' in names
    # what the moveset calls a bone is a shortcut to one
    short = ittle.shortcuts()
    assert short['l_foot'] == 'l_foot_end' and short['r_elbow'] == 'r_arm2'
    holder, clips = ittle.animation()
    assert names[holder] == 'ittle_use_10' and len(clips) == 86 and 'idle' in clips


@needs_game
def test_the_moveset_and_the_attack_properties(ittle):
    moves, props = ittle.moveset(), ittle.props()
    assert {'jab0', 'fsmash', 'fsmash1', 'nspecial_v1', 'uspecial', 'dspecial'} <= set(moves)
    boxes = [a for _f, _c, a in gamedata.events(moves['jab0']) if a.get('t') == 'SACH']
    assert boxes and all(b.get('p') in props for b in boxes)


@needs_game
def test_a_sound_decodes_to_mono_pcm(ittle):
    from echo_slapcity.unity import audio
    entry = next(e for e in ittle.sound_bank()['entries'] if e['id'] == 'jump')
    clip = ittle.ref(ittle.game.mono(ittle.ref(entry['sfx']))['sfx'][0]['clip']).read()
    got = sounds.mono(audio(clip))
    assert got['rate'] == 44100 and 0.2 < len(got['pcm']) / got['rate'] < 0.3


@needs_game
def test_the_skeleton_has_ultimates_throw_bone_for_the_shield_and_the_held_fighter(ittle):
    # without it the shield hung from the engine's YRot and Melee scaled her whole body to the shield's size
    from echo_slapcity import transcode
    sk = transcode.Skeleton(ittle)
    assert sk.names[-1] == 'Throw' and sk.parent['Throw'] == 'Trans'
    assert sk.rest['Throw'][1, 3] == pytest.approx(transcode.HEIGHT * transcode.THROW_MIDDLE)
    held = sk.joint_worlds(sk.pose(sk.clips['grab'], 8), hold=True)
    assert np.allclose(held['Throw'][:3, 3], held[sk.grab_joint][:3, 3]) and np.allclose(held['Throw'][:3, :3], np.eye(3))


def test_a_box_made_and_taken_down_on_one_frame_strikes_on_that_frame():
    rd = gamedata.Reader(SimpleNamespace(name='ittledew'), {'dslap': {'dmg': 16}},
                         {'unit': 1.0, 'armature_scale': 1.0, 'shortcuts': {'head': 'Head'}}, 1.0)
    evs = [(5.0, 0, {'t': 'SASHC', 'h': 1}), (5.0, 0, {'t': 'SACH', 'h': 0, 'p': 'dslap', 'b': 'head', 'r': 2.3}),
           (5.0, 0, {'t': 'SARA'}), (5.0, 0, {'t': 'SAEA'})]
    box = rd.part(evs, 0, 'dsmash')['hitboxes'][0]
    assert box['first'] == box['last'] == 6 and box['bone'] == 'head' and box['damage'] == 16


def test_a_box_struck_again_or_given_another_property_goes_on_as_a_box_of_its_own():
    """Checklist 9.6 for Ittle Dew. Her forward air makes its three boxes once and strikes again twice (SARA on
    frames 11 and 16), the last time harder (SASATP: every box out takes `fair2`); her down air's later frames take
    `dair2` and `dair3` without striking again. Read as one box all the way, the forward air struck once, with
    `fair1`'s numbers throughout."""
    from fighter_port import oneshot
    rd = gamedata.Reader(SimpleNamespace(name='ittledew'), {'fair1': {'dmg': 3, 'basekb': 120}, 'fair2': {'dmg': 3, 'basekb': 135},
                                                            'dair1': {'dmg': 8}, 'dair2': {'dmg': 6}, 'dair3': {'dmg': 4}},
                         {'unit': 1.0, 'armature_scale': 1.0, 'shortcuts': {}}, 1.0)
    make = [(6.0, 0, {'t': 'SASHC', 'h': 3})] + [(6.0, 0, {'t': 'SACH', 'h': h, 'p': 'fair1', 'r': 1.0}) for h in range(3)]
    fair = make + [(11.0, 0, {'t': 'SARA'}), (16.0, 0, {'t': 'SARA'}), (16.0, 0, {'t': 'SASATP', 'h': -1, 'p': 'fair2'}),
                   (17.0, 0, {'t': 'SAEA'})]
    rows = rd.part(fair, 0, 'fair')['hitboxes']
    assert [(r['first'], r['last'], r['bkb']) for r in rows if r['id'] == 0] == [(7, 11, 48.0), (12, 16, 48.0), (17, 17, 54.0)]
    assert [(s, e, again) for s, e, _, again in oneshot.stretches(rows, 40)] == [(7, 11, False), (12, 16, False), (17, 17, False)]
    dair = [(f, c, dict(a, p='dair1') if a['t'] == 'SACH' else a) for f, c, a in make] + [
        (6.0, 0, {'t': 'SARA'}), (7.0, 0, {'t': 'SASATP', 'h': -1, 'p': 'dair2'}), (8.0, 0, {'t': 'SASATP', 'h': -1, 'p': 'dair3'}),
        (10.0, 0, {'t': 'SAEA'})]
    rows = rd.part(dair, 0, 'dair')['hitboxes']
    assert [(r['first'], r['last'], r['damage']) for r in rows if r['id'] == 2] == [(7, 7, 8.0), (8, 8, 6.0), (9, 10, 4.0)]
    assert [(s, e, again) for s, e, _, again in oneshot.stretches(rows, 40)] == [(7, 7, False), (8, 8, True), (9, 10, True)]


def test_the_clips_frame_on_a_frame_of_the_move():
    keys = [[0, 0.0], [5, 5.0], [8, 5.0], [13, 10.0]]
    assert [gamedata.clip_frame(keys, r) for r in (1, 4, 7, 10, 20)] == [0.0, 3.0, 5.0, 6.0, 16.0]


def test_a_grab_box_on_a_bone_is_put_in_the_fighters_own_space():
    move = {'clip': 'grab', 'time_keys': [[0, 0.0]], 'other': [
        {'cmd': 'CATCH', 'real': 8, 'args': [0, 'handr', 2.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0, None]}]}
    hand = np.eye(4)
    hand[:3, 3] = [0.5, 6.0, 3.0]
    travel = np.eye(4)
    travel[:3, 3] = [0.0, 0.0, 1.0]
    sk = SimpleNamespace(names=['Trans', 'Hip', 'HandR'], clips={'grab': 'the clip'},
                         pose=lambda clip, frame: (clip, frame), joint_worlds=lambda w: {'HandR': hand, 'Trans': travel})
    gamedata.grabs_on_top({'game_catch': move}, sk)
    a = move['other'][0]['args']
    # the hand's place, one up the hand, less the clip's travel along the ground
    assert a[1] == 'top' and a[2] == 2.0 and a[3:9] == pytest.approx([0.5, 7.0, 2.0] * 2) and move['other'][0]['from_bone'] == 'handr'


def test_the_fighters_numbers_steer_as_the_game_does_and_squat_until_its_jump():
    """Checklist 5.5 for Ittle Dew. The game steers in the air by one step toward airspeed x stick (`airacc`, the same
    however far the stick leans: all of it Melee's flat +0x68, none of it the stick's +0x64) and slows a fighter that is
    not steering by `airdecay` (`airbrake` is not read for a fighter: the first port took it, three times hers). Her
    squat asks on its frame 5 whether jump is held, both sides a jump (the reader found no end, and left the donor's 4)."""
    base = {'floordashspeed': 16.0, 'floorrunspeed': 11.0, 'floorbrake': 50.0, 'floorfriction': 0.5, 'gravity': 50.0,
            'fallSpeed': 20.0, 'fastFallSpeed': 40.0, 'airspeed': 12.0, 'airacc': 60.0, 'airbrake': 15.0, 'airdecay': 5.0,
            'weight': 100.0}
    held = {'t': 'CTI', 'i': {'t': 'Jump', 'c': 'DownOrHeld'}, 'f': 1, 'b': 'None'}
    kneebend = {'tl': [{'at': 0, 'af': 0, 'a': {'t': 'SASF', 's': []}},
                       {'at': 0.0833333358, 'af': 5, 'a': {'t': 'SACT', 'ct': held, 'a': {'t': 'SACTM', 'tm': 'jump0', 's': 0},
                                                         'e': True, 'ea': {'t': 'SACTM', 'tm': 'shjump', 's': 0}}}]}
    out, _ = gamedata.attributes(base, {'kneebend': kneebend}, 2.0, 0.5, lambda h, g: 0.0, {})
    per2 = 1.0 / 3600.0
    assert out['aerial_speed'] == 0.0 and out['aerial_friction'] == pytest.approx(60 * per2)
    assert out['air_friction'] == pytest.approx(5 * per2) and out['friction'] == pytest.approx(25 * per2)
    assert out['max_aerial_horizontal_speed'] == pytest.approx(12 / 60.0) and out['jump_startup_lag'] == 5.0
    assert gamedata.jump_frame(gamedata.events({'tl': []})) is None


# ------------------------------------------------------------------------------ the specials and what they make
def test_the_specials_are_the_moves_the_games_input_table_starts():
    # (a moveset keeps leftovers nothing starts: Ittle Dew's nspecial_v1 is not her neutral special)
    table = gamedata.move_table({'spN': 'nspecial', 'spF': 'fspecial', 'spU': 'uspecial', 'spD': 'dspecial', 'atkN': 'jab0'})
    assert table['nspecial'] == ['d00specialn'] and table['dspecial'] == ['d03speciallw'] and 'nspecial_v1' not in table
    assert gamedata.move_table({})['jab0'] == ['c00attack11'] and 'nspecial' not in gamedata.move_table({})


@pytest.mark.parametrize('inputs, expected', [
    ({'spN': 'spn', 'spF': 'spn', 'spU': 'spn', 'spD': 'spn'},
     ['d00specialn', 'd00specialairn', 'd01specials', 'd01specialairs',
      'd02specialhi', 'd02specialairhi', 'd03speciallw', 'd03specialairlw']),
    ({'atkN': 'spn', 'airN': 'spn'}, ['c00attack11', 'c05attackairn']),
])
def test_shared_source_moves_keep_every_control_and_its_script(inputs, expected):
    # Asha shares all four specials; Goddess shares jab/nair. Neither may collapse to the last input.
    moveset = {'spn': {'tl': [
        {'af': 0, 'a': {'t': 'SAPA', 'a': 'sharedclip'}},
        {'af': 2, 'a': {'t': 'SACH', 'h': 0, 'p': 'strike'}},
        {'af': 4, 'a': {'t': 'SAEA'}},
        {'af': 8, 'a': {'t': 'SASI'}},
    ]}}
    rd = gamedata.Reader(SimpleNamespace(name='shared'), {'strike': {'dmg': 7}},
                         {'unit': 1, 'armature_scale': 1, 'shortcuts': {}}, 1)
    moves, motions = gamedata.read_moves(rd, moveset, inputs)
    for stem in expected:
        entry = moves['game_' + stem[3:]]
        assert entry['slapcity_move'] == 'spn' and entry['animation'] == stem + '.nuanmb'
        assert [(h['damage'], h['first'], h['last']) for h in entry['hitboxes']] == [(7, 3, 4)]
        assert motions[stem]['cancel_frame'] == 9


def test_remapping_one_control_does_not_remove_another_use_of_its_default_move():
    table = gamedata.move_table({'atkN': 'otherjab', 'airN': 'jab0', 'spN': 'jab0'})
    assert table['otherjab'] == ['c00attack11']
    assert table['jab0'] == ['c05attackairn', 'd00specialn']
    assert 'nair' not in table
    assigned = [stem for stems in table.values() for stem in stems]
    assert len(assigned) == len(set(assigned))


def test_follow_on_cannot_take_a_shared_moves_other_control_slot():
    play = lambda clip: {'af': 0, 'a': {'t': 'SAPA', 'a': clip}}
    moveset = {'shared': {'tl': [play('specialneutral'),
                               {'af': 3, 'a': {'t': 'SACTM', 'tm': 'follow'}}]},
               'follow': {'tl': [play('specialforward'), play('specialdownair')]}}
    inputs = {'spN': 'shared', 'spF': 'shared'}
    got = gamedata.follow_ons(moveset, inputs, gamedata.move_table(inputs))
    assert got == {'follow': ['d03specialairlw']}


COUNTED = {'t': 'CTC', 'w': 'EOLarger', 'a': {'t': 'FSD', 'i': 'spn_charge'}, 'b': {'f': 15.0}}


def _held_neutral():
    """Ittle Dew's neutral special as the game writes it: the clip stops on frame 6 and a count runs; B up or 15
    counted starts the partial move that swings and shoots, a choice on the count picking the big swing and the slow
    fireball or the plain ones."""
    check = {'t': 'SACT', 'ct': {'t': 'CTOR', 'c': [{'t': 'CTB', 'b': 'special', 'w': 'Up'}, COUNTED]},
             'a': {'t': 'SAPM', 'm': 'p_nspecial'}}
    rate0 = {'w': 'Set', 'g': {'t': 'FSAN', 'a': 'specialn', 'r': 'rate'}, 's': {'f': 0.0}}
    return {
        'nspecial': {'tl': [{'af': 0, 'a': {'t': 'SAPA', 'a': 'specialn', 'cfg': {'rt': 1}}},
                            {'af': 5, 'a': {'t': 'SASF', 's': [rate0]}},
                            {'af': 5, 'a': {'t': 'SAAA', 'a': check}}]},
        'p_nspecial': {'tl': [
            {'af': 3, 'a': {'t': 'SACT', 'ct': COUNTED, 'e': True,
                            'a': {'t': 'SAOS', 'ac': [{'t': 'SACH', 'h': 0, 'b': 'mace', 'r': 0.8},
                                                      {'t': 'SAPSFX', 's': 'strongwhiff'}]},
                            'ea': {'t': 'SAOS', 'ac': [{'t': 'SACH', 'h': 0, 'b': 'mace', 'r': 0.5},
                                                       {'t': 'SAPSFX', 's': 'mediumwhoosh'}]}}},
            {'af': 7, 'a': {'t': 'SACT', 'ct': COUNTED, 'e': True,
                            'a': {'t': 'SASA', 'id': 'fireball2', 'bn': 'mace', 'g': {}},
                            'ea': {'t': 'SASA', 'id': 'fireball', 'bn': 'mace', 'g': {}}}},
            {'af': 7, 'a': {'t': 'SAEA'}},
            {'af': 30, 'a': {'t': 'SACTM', 'tm': 'neutral'}}]}}


def test_a_charge_that_starts_a_partial_move_goes_on_in_it_from_the_charges_own_frame():
    moveset = _held_neutral()
    rd = gamedata.Reader(SimpleNamespace(name='ittledew'), {}, {'unit': 1.0, 'armature_scale': 1.0, 'shortcuts': {}}, 1.0)
    evs = gamedata.events(moveset['nspecial'])
    assert gamedata.charge_frame(evs, 'nspecial') == 5.0
    assert gamedata.charge_release(evs, moveset, 'nspecial', 5.0) == ('p_nspecial', 5)
    assert gamedata.charge_most(moveset['nspecial'], 'p_nspecial') == 15.0
    e = gamedata.move_entry(rd, moveset, 'nspecial', 'd00specialn')
    # tapped, it strikes on 9, shoots on 13 and ends on 36: the clip stops on 6 only while held (its rate 0 then 1)
    assert e['charge'] == {'from': 6, 'release': 'p_nspecial', 'most': 15.0} and e['end'] == 36
    assert e['time_keys'] == [[0, 0.0], [5, 5.0], [35, 35.0]]
    plain = [h for h in e['hitboxes'] if not h.get('alternative')]
    assert [(h['first'], h['last'], h['size']) for h in plain] == [(9, 12, 0.5)]
    assert [s['name'] for s in e['sounds']] == ['se_ittledew_mediumwhoosh']


def test_a_two_sided_choice_is_written_as_its_plain_side_and_keeps_the_other_apart():
    moveset = _held_neutral()
    rd = gamedata.Reader(SimpleNamespace(name='ittledew'), {}, {'unit': 1.0, 'armature_scale': 1.0, 'shortcuts': {}}, 1.0)
    e = gamedata.move_entry(rd, moveset, 'nspecial', 'd00specialn')
    # the side asked first: a hitbox that ends before it begins (the driver drops it) and a sound not played
    alt = [x for x in e['alternatives'] if x['what'] == 'hitbox']
    assert len(alt) == 1 and alt[0]['hitbox']['size'] == 0.8 and alt[0]['hitbox']['last'] < alt[0]['hitbox']['first'] == 9
    assert {'what': 'sound', 'real': 9, 'name': 'se_ittledew_strongwhiff'} in e['alternatives']
    # both articles are kept, each with what its choice asks
    arts = {a['id']: a for a in e['articles']}
    asked = {'compare': 'EOLarger', 'of': 'FSD spn_charge', 'with': 15.0}
    assert arts['fireball2']['alt'] and arts['fireball2']['when'] == asked and arts['fireball2']['real'] == 13
    assert not arts['fireball']['alt'] and arts['fireball']['when'] == {'not': asked}
    assert gamedata.condition({'t': 'CTB', 'b': 'special'}) == {'t': 'CTB', 'b': 'special'}


def test_what_a_move_sets_itself_plainly_is_kept_and_a_spawn_reads_the_stick():
    rd = gamedata.Reader(SimpleNamespace(name='ittledew'), {}, {'unit': 1.0, 'armature_scale': 1.0, 'shortcuts': {}}, 1.0)
    sets = {'t': 'SASF', 's': [{'w': 'Set', 'g': {'t': 'FSM', 'a': 'gravity'}, 's': {'f': 10.0}},
                               {'w': 'Set', 'g': {'t': 'FSD', 'i': 'grabedge'}, 's': {'f': 0.0}},
                               {'w': 'Add', 'g': {'t': 'FSD', 'i': 'spn_charge'}, 's': {'f': 1.0}}]}
    chosen = {'t': 'SASF', 's': [{'w': 'Set', 'g': {'t': 'FSM', 'a': 'x_vel'}, 's': {'f': 0.0}}]}
    got = rd.part([(0.0, 0, sets), (39.0, 0, sets), (40.0, 1, chosen)], 0, 'specialhi')['sets']
    assert got == [[1, 'gravity', 10.0], [1, 'grabedge', 0.0], [40, 'gravity', 10.0], [40, 'grabedge', 0.0]]
    # Ittle Dew's bomb: 5 the way she faces plus 7.5 the stick across; 15 up plus 5 the stick up
    def mult(a, b):
        return {'t': 'FSF', 'fw': 'Mult', 'fa': a, 'fb': b}

    def add(a, b):
        return {'t': 'FSF', 'fw': 'Add', 'fa': a, 'fb': b}
    g = {'md': [{'i': 'Velocity', 'o': {'t': 'OSV2',
                                        'x': add(mult({'t': 'FSM', 'a': 'forwarddir'}, {'f': 5.0}), mult({'f': 7.5}, {'t': 'FSI', 'i': 'ctrlXRaw'})),
                                        'y': add({'f': 15.0}, mult({'t': 'FSI', 'i': 'ctrlY'}, {'f': 5.0}))}}]}
    assert gamedata.spawn_terms(g) == {'Velocity': [{'forwarddir': 5.0, 'ctrlXRaw': 7.5}, {'1': 15.0, 'ctrlY': 5.0}]}
    assert gamedata.spawn_numbers(g) == {'Velocity': [None, None]}


@needs_game
def test_roster_inputs_keep_every_script_slot(ittle):
    from echo_slapcity.fighter import Fighter
    from echo_slapcity.roster import roster
    for row in roster(ittle.game):
        assert 'error' not in row, row
        assert not row['missing_moves'], row
        fighter = Fighter(ittle.game, row['fighter'])
        # Script selection only: unit scale avoids claiming a mesh/physics calibration.
        rd = gamedata.Reader(fighter, fighter.props(),
                             {'unit': 1, 'armature_scale': 1, 'shortcuts': fighter.shortcuts()}, 1)
        moves, _motions = gamedata.read_moves(rd, fighter.moveset(), row['inputs'])
        for key, stem in {**gamedata.ATTACK_INPUTS, **gamedata.SPECIAL_INPUTS}.items():
            source = row['inputs'].get(key)
            if not isinstance(source, str) or not source:
                continue
            assert moves.get('game_' + stem[3:], {}).get('slapcity_move') == source, (row['fighter'], key)
            for alias in gamedata.ALSO.get(stem, []):
                # Air specials may have their own follow-on script; the slot must still exist.
                assert 'game_' + alias[3:] in moves, (row['fighter'], key, alias)


@needs_game
def test_her_specials_things_are_read_from_the_game(ittle, tmp_path):
    table = gamedata.move_table(ittle.character.get('standardSCinputTrigger') or {})
    assert table['nspecial'] == ['d00specialn'] and table['fspecial'] == ['d01specials'] and 'nspecial_v1' not in table
    bomb = gamedata.article_numbers(ittle)['bomb']
    assert bomb['fuselength'] == 90.0 and bomb['atkprop']['dmg'] == 18.0 and bomb['places']['hitbox'] == pytest.approx([0.0, 0.5])
    assert gamedata.projectiles(ittle)['fireball2']['refreshAtkFrames'] == 1.0
    cc = gamedata.custom_calls(ittle)['IttleDewTeleportCC']
    assert cc['speed'] == 35.0 and cc['defaultDir'] == [1.0, 1.0] and (cc['width'], cc['height']) == (1.0, 2.5)
    from echo_slapcity import transcode
    ssbh = pytest.importorskip('ssbh_data_py')
    made = next(bank['bomb'] for bank in ittle.articles().values() if 'bomb' in bank)
    rows = transcode.write_article(ssbh, ittle, 'bomb', made, 1.0, tmp_path / 'bomb')
    assert sum(r['triangles'] for r in rows) == 618 and (tmp_path / 'bomb' / 'model.numshb').is_file()
    ball = transcode.call_pictures(ittle, ittle.game, 1.0, tmp_path / 'pictures')['IttleDewTeleportCC.teleportObject']
    assert ball['texture'] == 'portalwarp_bkg' and ball['size'] == pytest.approx([2.3, 2.3], abs=1e-3)
    assert ball['at'][1] == pytest.approx(1.5, abs=1e-3) and (tmp_path / 'pictures' / ball['picture']).is_file()


# ---------------------------------------------------------------------------------------- her own specials


def test_single_influence_mesh_preserves_each_vertices_source_bone():
    from echo_slapcity.transcode import skin_influences
    h = SimpleNamespace(m_BoneIndices=[(2,), (0,), (1,)], m_BoneWeights=None)
    indices, weights = skin_influences(h, 3, 3)
    assert indices.tolist() == [[2], [0], [1]]
    assert weights.tolist() == [[1.0], [1.0], [1.0]]


@pytest.mark.parametrize('indices,weights,reason', [
    ([(0, 1)], None, 'multi-influence'),
    ([(3,)], None, 'outside'),
    ([(0,)], [(0,)], 'positive'),
    ([(0,)], [(float('nan'),)], 'malformed'),
])
def test_skinning_rejects_missing_or_invalid_weights(indices, weights, reason):
    from echo_slapcity.transcode import skin_influences
    h = SimpleNamespace(m_BoneIndices=indices, m_BoneWeights=weights)
    with pytest.raises(ValueError, match=reason):
        skin_influences(h, 1, 3)


@needs_game
@pytest.mark.parametrize('name', ['ruby', 'tetron'])
def test_nonhuman_and_single_influence_skeletons_use_the_sources_grab_point(name):
    from echo_slapcity.unity import Game
    from echo_slapcity.fighter import Fighter
    from echo_slapcity.transcode import Skeleton
    f = Fighter(Game(SLAP), name)
    sk = Skeleton(f)
    assert sk.grab_joint == sk.joint_of[f.grab_point()]
    assert len(sk.names) == len(set(sk.names))
    assert sk.tall > 0
    held = sk.joint_worlds(sk.pose(sk.clips['grab'], 8), hold=True)
    assert np.allclose(held['Throw'][:3, 3], held[sk.grab_joint][:3, 3])
    if name == 'ruby':
        assert 'HandR' not in sk.names


def test_body_without_a_pelvis_uses_its_explicit_body_landmark():
    from echo_slapcity.transcode import landmark_names
    assert landmark_names(['body', 'hat', 'grab'], {'body': 'body'}) == {'body': 'Hip', 'hat': 'hat', 'grab': 'grab'}
    assert landmark_names(['body', 'superbody'], {'body': 'body'})['body'] == 'Bust'


def test_a_hurtbox_without_a_second_track_is_a_sphere_at_its_first_offset():
    rd = gamedata.Reader(None, {}, {'unit': 1, 'armature_scale': 1, 'shortcuts': {'chest': 'Bust'}}, 1)
    row = dict(ba='chest', bb='', loa=[1,2,3], lob=[9,9,9], r=0.8)
    moves = {'p_def_hrt': {'tl': [{'af': 0, 'a': {'t': 'SASH', 'h': {'h': [row]}}}]}}
    got = gamedata.hurtboxes(rd, moves, {'Bust': np.eye(4)})
    assert got[0]['a'] == got[0]['b'] == [-1,2,3]
    row['bb'] = 'missing'
    with pytest.raises(ValueError, match='end bone'):
        gamedata.hurtboxes(rd, moves, {'Bust': np.eye(4)})


def test_active_entry_clip_aliases_ground_slot_when_parallel_clip_is_dormant():
    from echo_slapcity.transcode import clip_stems
    move = {'tl': [{'af': 0, 'a': {'t': 'SAOS', 'ac': [
        {'t':'SAPA', 'a':'specialforwardair', 'cfg':{'wg':1}},
        {'t':'SAPA', 'a':'specialforwardair2', 'cfg':{'wg':0}}]}}]}
    got = clip_stems(['specialforwardair','specialforwardair2'], {'sp_f':move}, {'spF':'sp_f'})
    assert {'d01specials','d01specialairs'} <= set(got['specialforwardair'])
    assert 'd01specials' not in got['specialforwardair2']
    move['tl'][0]['a']['ac'][1]['cfg']['wg'] = 1
    assert 'd01specials' not in clip_stems(got, {'sp_f':move}, {'spF':'sp_f'})['specialforwardair']


def test_jab_slots_follow_attack_transitions_instead_of_source_suffixes():
    def move(clip, target=None):
        actions=[{'t':'SAPA','a':clip}]
        if target:
            actions += [{'t':'SAAA','a':{'t':'SACT','ct':{'t':'CTI','i':{'t':'Attack','c':'Down'}},
                                         'a':{'t':'SACTM','tm':target}}}]
        return {'tl':[{'af':0,'a':{'t':'SAOS','ac':actions}}]}
    source={'jab':move('jab','jab2'),'jab2':move('jab2'),'jab1':move('unused')}
    table=gamedata.move_table({'atkN':'jab'},source)
    assert table['jab']==['c00attack11'] and table['jab2']==['c00attack12']
    assert not any('c00attack13' in stems for stems in table.values())
    from echo_slapcity.transcode import clip_stems
    assert 'c00attack12' in clip_stems(['jab','jab2'],source,{'atkN':'jab'})['jab2']
    source['jab']=move('jab')
    assert gamedata.jab_chain(source,'jab')==['jab']


def test_nested_move_choices_keep_all_guards_for_hits_and_clip_selection():
    outer={'t':'CTC','w':'EOLarger','a':{'t':'FSD','i':'cashOnHand'},'b':{'f':200}}
    inner={'t':'CTI','i':{'t':'CtrlAttack'},'f':1,'b':'None'}
    move={'tl':[{'af':12,'a':{'t':'SACT','ct':outer,'a':{'t':'SACT','ct':inner,
        'a':{'t':'SACH','h':0,'b':'hip','p':'cashhit'},'e':True,
        'ea':{'t':'SAPA','a':'recovery'}},'e':True,'ea':{'t':'SACTM','tm':'neutral'}}}]}
    ev=gamedata.events(move)
    assert ev[0][2]['when']=={'all':[outer,inner]}
    assert ev[1][2]['when']=={'all':[outer,{'not':inner}]}
    assert ev[2][2]['when']=={'not':outer}
    described=gamedata.condition(ev[0][2]['when'])
    assert described['all'][0]=={'compare':'EOLarger','of':'FSD cashOnHand','with':200.}
    assert described['all'][1]==inner


def test_conditional_tween_clip_retains_its_guard():
    guard={'t':'CTC','w':'Equal','a':{'t':'FSD','i':'form'},'b':{'f':1}}
    move={'tl':[{'af':0,'a':{'t':'SACT','ct':guard,'a':{'t':'SATTW','a':'alternate','c':{'wg':1}}}}]}
    event=gamedata.events(move)[0]
    assert event[2]['when']==guard and event[2]['t']=='SAPA'


def test_jab_listener_uses_registration_and_explicit_removal_frames():
    attack = {'t':'CTI','i':{'t':'Attack','c':'Down'}}
    listener = {'t':'SAAA','f':{'f':0},'p':'PreMoveUpd','i':'nextjab',
                'a':{'t':'SACT','ct':attack,'a':{'t':'SACTM','tm':'second'}}}
    move = {'tl':[{'af':9,'a':listener},
                  {'af':20,'a':{'t':'SADA','i':0,'d':'nextjab'}},
                  {'af':32,'a':{'t':'SACTM','tm':'neutral'}}]}
    got = gamedata.jab_windows(move, 'second')
    assert [(w['start'],w['end']) for w in got] == [(10,21)]
    assert got[0]['target']=='second' and got[0]['when']==attack
    assert gamedata.jab_windows(move,'third')==[]
    move['tl'].pop(1)
    assert gamedata.jab_windows(move,'second')[0]['end']==33
    # Neither a held/released button nor a cash-gated listener is an ordinary jab press.
    attack['i']['c']='NotOrUp'
    assert gamedata.jab_windows(move,'second')==[]
    attack['i']['c']='Down'
    listener['a']['ct']={'t':'CTM','m':'All','c':[attack,{'t':'CTC','a':{'t':'FSD','i':'cash'},'b':{'f':200}}]}
    assert gamedata.jab_windows(move,'second')==[]


@needs_game
@pytest.mark.parametrize('name,move,target,start,end', [
    ('ittledew','jab0','jab1',11,21),
    ('tetron','jab','jab2',10,21),
])
def test_installed_game_jab_windows_match_source_listener_lifetime(name,move,target,start,end):
    from echo_slapcity.unity import Game
    from echo_slapcity.fighter import Fighter
    source=Fighter(Game(SLAP),name).moveset()
    windows=gamedata.jab_windows(source[move],target)
    assert [(w['start'],w['end']) for w in windows]==[(start,end)]


def test_guarded_hitbox_mutations_keep_the_ordinary_path_and_the_full_conditional_operation():
    rd=gamedata.Reader(SimpleNamespace(name='bcman'),{'base':{'dmg':8},'sell':{'dmg':16}},
                       {'unit':1.,'armature_scale':1.,'shortcuts':{}},1.)
    guard={'t':'CTC','w':'EOLarger','a':{'t':'FSD','i':'cashOnHand'},'b':{'f':400}}
    evs=[(5.,0,{'t':'SACH','h':0,'p':'base','r':1.}),
         (5.,1,{'t':'SASATP','h':-1,'p':'sell','when':guard}),
         (6.,1,{'t':'SARA','when':guard}),
         (7.,1,{'t':'SAEA','when':guard}),
         (9.,0,{'t':'SAEA'})]
    result=rd.part(evs,0,'fsmash')
    assert len(result['hitboxes'])==1
    box=result['hitboxes'][0]
    assert (box['first'],box['last'],box['damage'],box['prop'])==(6,9,8.,'base')
    branches=[t for t in result['source_terms'] if not t['carried_by_script']]
    assert [t['real'] for t in branches]==[6,7,8]
    assert all(t['when']==guard for t in branches)
    assert branches[0]['properties']['damage']==16 and branches[0]['action']['h']==-1


def test_resource_expressions_and_custom_call_guards_keep_order_and_shifted_frames():
    rd=gamedata.Reader(SimpleNamespace(name='bcman'),{},
                       {'unit':1.,'armature_scale':1.,'shortcuts':{}},1.)
    guard={'t':'CTC','w':'EOLarger','a':{'t':'FSD','i':'cashOnHand'},'b':{'f':400}}
    expr={'t':'FSF','fw':'Mult','fa':{'f':20},'fb':{'t':'FSD','i':'charge'}}
    assign={'g':{'t':'FSD','i':'cashTransaction'},'s':expr,'w':'Set'}
    result=rd.part([(6.,1,{'t':'SASF','s':[assign],'when':guard}),
                    (6.,1,{'t':'SACC','c':'bc_sellhit','when':guard})],11,'fsmash')
    assert result['sets']==[]  # no invented constant for a guarded dynamic expression
    a,b=result['source_terms']
    assert [a['kind'],b['kind']]==['float','call'] and a['real']==b['real']==18
    assert a['value']==expr and a['target']==assign['g'] and a['operation']=='Set'
    assert a['when']==b['when']==guard and b['name']=='bc_sellhit'


def test_guarded_replacement_does_not_truncate_the_base_or_create_a_second_hit():
    rd=gamedata.Reader(SimpleNamespace(name='bcman'),{'base':{'dmg':8},'sell':{'dmg':16}},
                       {'unit':1.,'armature_scale':1.,'shortcuts':{}},1.)
    guard={'t':'CTC','w':'EOLarger','a':{'t':'FSD','i':'cashOnHand'},'b':{'f':200}}
    got=rd.part([(4.,0,{'t':'SACH','h':0,'p':'base','r':1.}),
                 (4.,1,{'t':'SACH','h':0,'p':'sell','r':2.,'when':guard}),
                 (9.,0,{'t':'SAEA'})],0,'fair')
    assert len(got['hitboxes'])==1
    assert (got['hitboxes'][0]['first'],got['hitboxes'][0]['last'],got['hitboxes'][0]['damage'])==(5,9,8)
    replacement=got['source_terms'][0]
    assert replacement['when']==guard and replacement['hitbox']['damage']==16
    assert not replacement['carried_by_script'] and replacement['action']['r']==2.


def test_source_sound_lookup_is_case_sensitive_and_distinct_from_export_success():
    moves={'m':{'sounds':[{'source_sfx_id':s,'name':'se_test_'+s.lower()} for s in ('charge','Charge','absent')]}}
    gamedata.source_sound_receipts(moves,[{'id':'charge','sfx':None}])
    assert [e['source_sound']['exists'] for e in moves['m']['sounds']]==[True,False,False]
    assert all(e['source_sound']['bank']=='fighter' for e in moves['m']['sounds'])


def test_callback_only_specials_retain_data_without_stealing_slots_or_inventing_transitions():
    play=lambda clip: dict(af=0,a=dict(t='SAPA',a=clip))
    moveset={'spf':dict(tl=[play('specialforward')]),
             'spf2':dict(tl=[play('specialforward2'),dict(af=20,a=dict(t='SACTM',tm='spfrecover'))]),
             'spfrecover':dict(tl=[play('recoverpose')]),
             'unused_idle':dict(tl=[play('idleunused')]),
             'p_visual':dict(tl=[play('specialeffect')])}
    inputs={'spF':'spf'}
    table=gamedata.move_table(inputs,moveset)
    got=gamedata.follow_ons(moveset,inputs,table)
    assert got=={'spf2':['z00specialforward2'],'spfrecover':['z00recoverpose']}
    rd=gamedata.Reader(SimpleNamespace(name='callback'),{},
        {'unit':1,'armature_scale':1,'shortcuts':{}},1)
    moves,_=gamedata.read_moves(rd,moveset,inputs)
    assert moves['game_specials']['slapcity_move']=='spf'
    assert moves['game_specialforward2']['slapcity_move']=='spf2'
    assert moveset['spf']['tl']==[play('specialforward')]
