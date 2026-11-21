"""The reader check (`fighter_port/reader_check.py`, READERS.md): a small fighter written in Ultimate's shapes as a
reader would, then broken one way at a time. Each way is one the cold trials met only later, in a port or in the
game."""
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ssbh = pytest.importorskip('ssbh_data_py')

from fighter_port import reader_check, source_game  # noqa: E402

F = 'tester'
# joint: (parent, where it stands from its parent): Y up, facing +Z, Ultimate's way
JOINTS = {'Trans': (None, (0, 0, 0)), 'Rot': ('Trans', (0, 0, 0)), 'Throw': ('Trans', (0, 8, 0)),
          'Hip': ('Rot', (0, 8, 0)), 'Head': ('Hip', (0, 6, 0)), 'HandL': ('Hip', (3, 3, 0)), 'HandR': ('Hip', (-3, 3, 0)),
          'FootL': ('Hip', (1, -7, 0)), 'FootR': ('Hip', (-1, -7, 0)), 'ToeL': ('FootL', (0, 0, 1)),
          'ToeR': ('FootR', (0, 0, 1))}


def _skeleton(path, joints):
    skel = ssbh.skel_data.SkelData()
    names = list(joints)
    bones = []
    for name, (parent, t) in joints.items():
        m = np.eye(4, dtype=np.float32)
        m[:3, 3] = t
        bones.append(ssbh.skel_data.BoneData(name, np.ascontiguousarray(m.T), None if parent is None else names.index(parent)))
    skel.bones = bones
    skel.save(str(path))


def _clip(path, joints, travel=0.0, frames=30):
    anim = ssbh.anim_data.AnimData()
    anim.final_frame_index = float(frames - 1)
    group = ssbh.anim_data.GroupData(ssbh.anim_data.GroupType.Transform)
    nodes = []
    for name in joints:
        moves = name == 'Trans'
        values = [ssbh.anim_data.Transform([1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 1.0],
                                           [0.0, 0.0, travel * f / (frames - 1) if moves else 0.0]) for f in range(frames)]
        nodes.append(ssbh.anim_data.NodeData(name, [ssbh.anim_data.TrackData('Transform', values=values)]))
    group.nodes = nodes
    anim.groups = [group]
    anim.save(str(path))


def _wav(path):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(32000)
        w.writeframes(np.zeros(320, '<i2').tobytes())


def write(root, joints=JOINTS, clips=None, game=None, sounds=None):
    """A fighter as a reader writes one (source_game.py). -> its folder"""
    folder = source_game.folder(root, F)
    body = folder / 'model' / 'body' / 'c00'
    body.mkdir(parents=True)
    _skeleton(body / 'model.nusktb', joints)
    for n in ('model.numshb', 'model.numdlb', 'model.numatb', 'body_col.nutexb'):
        (body / n).write_bytes(b'x')
    motion = folder / 'motion' / 'body' / 'c00'
    motion.mkdir(parents=True)
    for stem, travel in (clips or {'a00wait1': 0.0, 'c00attack11': 0.0, 'd00specialn': 0.0,
                                   'b02escapef': 30.0, 'b02escapeb': -30.0}).items():
        _clip(motion / f'{stem}.nuanmb', joints, travel)
    base = {'fighter': F, 'game': 'slapcity',
            'melee_attributes': [{'op': 'set_attribute', 'name': 'gravity', 'value': 0.1}],
            'moves': {'game_attack11': {'animation': 'c00attack11.nuanmb', 'time_keys': [[0, 0.0], [20, 20.0]],
                                        'cancel_frame_real': 21,
                                        'hitboxes': [{'id': 0, 'bone': 'HandR', 'first': 4, 'last': 5, 'size': 3.0}],
                                        'sounds': [{'name': f'se_{F}_swing'}]},
                      'game_specialn': {'animation': 'd00specialn.nuanmb', 'time_keys': [[0, 0.0], [29, 29.0]],
                                        'cancel_frame_real': 21, 'hitboxes': []}},
            'source_tables': {'hurt': [{'bone': 'Hip', 'radius': 3.0}], 'ecb': [{'bone': 'Hip'}]}}
    (folder / 'game.json').write_text(json.dumps(dict(base, **(game or {}))), 'utf-8')
    (folder / 'sound').mkdir()
    index = sounds or {f'se_{F}_swing': {'file': 'swing.wav'}, f'vc_{F}_attack01': {'file': 'attack.wav', 'also': []}}
    for row in index.values():
        _wav(folder / 'sound' / row['file'])
    (folder / 'sound' / 'sounds.json').write_text(json.dumps(index), 'utf-8')
    ident = folder / 'identity'
    ident.mkdir()
    from PIL import Image
    Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(ident / 'series_icon.png')
    _wav(ident / 'victory.wav')
    (ident / 'identity.json').write_text('{}', 'utf-8')
    return folder


def problems(root):
    return [(what, text) for level, what, text in reader_check.check(root, F).rows if level == 'problem']


def test_what_a_reader_writes_right_has_no_problem(tmp_path):
    write(tmp_path)
    said = reader_check.check(tmp_path, F).rows
    assert [r for r in said if r[0] != 'ok'] == []
    assert any(w == 'upright' and 'facing +Z' in t for _l, w, t in said)


def test_a_number_under_a_name_the_app_does_not_know_is_a_problem_that_names_the_near_one(tmp_path):
    if reader_check.attribute_names() is None:
        pytest.skip('the app (NUCLEUS_REPO) is not found')
    write(tmp_path, game={'melee_attributes': [{'op': 'set_attribute', 'name': 'gravitty', 'value': 0.1}]})
    (what, text), = problems(tmp_path)
    assert what == "the fighter's numbers" and "'gravitty' (perhaps gravity)" in text and 'without a word' in text


def test_a_roll_that_leaves_him_where_he_started_is_a_problem(tmp_path):
    write(tmp_path, clips={'a00wait1': 0.0, 'c00attack11': 0.0, 'd00specialn': 0.0, 'b02escapef': 0.0,
                           'b02escapeb': -30.0})
    (what, text), = problems(tmp_path)
    assert what == 'travel' and 'b02escapef' in text and 'b02escapeb' not in text


def test_time_keys_past_an_ordinary_moves_cancel_frame_are_a_problem_and_a_specials_are_the_modules(tmp_path):
    write(tmp_path, game={'moves': {'game_attack11': {'animation': 'c00attack11.nuanmb', 'cancel_frame_real': 21,
                                                      'time_keys': [[0, 0.0], [29, 29.0]], 'hitboxes': []},
                                    'game_specialn': {'animation': 'd00specialn.nuanmb', 'cancel_frame_real': 21,
                                                      'time_keys': [[0, 0.0], [29, 29.0]], 'hitboxes': []}}})
    (what, text), = problems(tmp_path)
    assert what == 'time keys' and 'game_attack11 (keys to 29, free on 21)' in text and 'specialn' not in text


def test_an_also_name_the_donors_table_takes_by_number_needs_its_number(tmp_path):
    write(tmp_path, sounds={f'vc_{F}_hya': {'file': 'hya.wav', 'also': [f'vc_{F}_attack']},
                            f'vc_{F}_hup': {'file': 'hup.wav', 'also': [f'vc_{F}_attack02']}})
    (what, text), = problems(tmp_path)
    assert what == 'sounds' and f'vc_{F}_attack' in text and 'attack02' not in text


def test_a_skeleton_with_no_throw_joint_is_a_problem(tmp_path):
    write(tmp_path, joints={k: v for k, v in JOINTS.items() if k != 'Throw'})
    (what, text), = problems(tmp_path)
    assert 'Throw' in text and 'shield' in text


def test_a_body_lying_down_or_facing_away_is_a_problem(tmp_path):
    # the game's Z up taken as it is: the head is ahead of the hip, not above it
    lying = {k: (p, (t[0], t[2], t[1])) for k, (p, t) in JOINTS.items()}
    write(tmp_path / 'lying', joints=lying)
    assert [w for w, _t in problems(tmp_path / 'lying')] == ['upright']
    away = {k: (p, (t[0], t[1], -t[2])) for k, (p, t) in JOINTS.items()}
    write(tmp_path / 'away', joints=away)
    assert [w for w, _t in problems(tmp_path / 'away')] == ['facing']


def test_boxes_are_held_to_the_skeleton_but_his_origin_alternatives_and_open_boxes_are_not_faults(tmp_path):
    boxes = [{'id': 0, 'bone': 'top', 'first': 4, 'last': 5, 'size': 3.0},          # from his origin
             {'id': 1, 'bone': 'handr', 'first': 9, 'last': 8, 'size': 3.0},        # made and made again on frame 9
             {'id': 2, 'bone': 'Head', 'first': 9, 'last': None, 'size': 3.0},      # never ended: to the clip's end
             {'id': 3, 'bone': 'Sword', 'first': 4, 'last': 5, 'size': 3.0}]
    write(tmp_path, game={'moves': {'game_attack11': {'animation': 'c00attack11.nuanmb', 'time_keys': [],
                                                      'hitboxes': boxes}}})
    (what, text), = problems(tmp_path)
    assert what == 'hitboxes' and text.endswith('Sword')


def test_a_move_playing_a_clip_that_was_not_written_and_a_game_not_named_are_problems(tmp_path):
    write(tmp_path, game={'game': 'newgame', 'moves': {'game_attack11': {'animation': 'c00attack99.nuanmb',
                                                                         'hitboxes': []}}})
    said = problems(tmp_path)
    assert any('newgame' in t and 'source_game.GAMES' in t for _w, t in said)
    assert any(w == 'moves without their clip' and 'c00attack99' in t for w, t in said)


def test_preflight_says_the_reader_checks_problems_with_the_files_a_stage_reads(tmp_path):
    from fighter_port import preflight
    said = {'problem': [], 'ok': [], 'note': []}
    lines = SimpleNamespace(**{k: (lambda k: lambda *a: said[k].append(a))(k) for k in said})
    write(tmp_path, game={'melee_attributes': [{'op': 'set_attribute', 'name': 'gravity', 'value': 'heavy'}]})
    a = SimpleNamespace(root=tmp_path, fighter=F, game='slapcity')
    assert preflight.written_files(lines, a) == source_game.folder(tmp_path, F)
    if reader_check.attribute_names() is not None:
        assert [p[0] for p in said['problem']] == ["the reader's the fighter's numbers"]


def test_verify_answers_the_reader_line_from_preflights_record(tmp_path):
    from fighter_port import verify
    check = verify.CHECKS['10.14']
    row = lambda level, what, text='t': {'level': level, 'section': 'the fighter', 'what': what, 'text': text}
    def answer(game, lines):
        (tmp_path / 'preflight.json').write_text(json.dumps({'game': game, 'lines': lines}), 'utf-8')
        return check(verify.Work(tmp_path))
    assert answer('ultimate', []) is None                       # not a written game: not its line
    assert answer('slapcity', [])[0] == 'say'                   # preflight from before the check
    assert answer('slapcity', [row('note', "the reader's identity"), row('ok', "the reader's output")]) == \
        ('ok', "preflight held the reader's output against what the stages read: nothing wrong; notes: identity")
    verdict, how = answer('slapcity', [row('PROBLEM', "the reader's travel", 'b02escapef (+0.0)')])
    assert verdict == 'FAULT' and 'travel: b02escapef (+0.0)' in how


def test_conditional_branch_retains_recovery_but_still_requires_ordered_keys():
    move=dict(conditional_only=True,rivals2_attack='Fstrong',cancel_frame_real=32,
              end=46,time_keys=[[0,0.0],[45,45.0]],hitboxes=[])
    said=reader_check.Said()
    reader_check.moves(said,{'game_branch_fstrong_consume':move},{},{},{})
    assert not [r for r in said.rows if r[0]=='problem']
    said=reader_check.Said()
    reader_check.moves(said,{'game_branch_fstrong_consume':dict(move,time_keys=[[2,2.0],[1,1.0]])},{},{},{})
    assert any(r[0]=='problem' and r[1]=='time keys' for r in said.rows)
