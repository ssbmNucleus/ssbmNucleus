"""`prepare` keeps the rig and the body while what they are made from is the same (GAPS G6: every failure after them
cost both again, four runs of Wolf's trial): what each step's note covers, what it leaves out, and when the files
on disk are kept.

Needs the app's backend on the path (the body's note names the HSDRaw program from its config); nothing is built.
"""
import ast
import json
from pathlib import Path

import pytest

from fighter_port import compat

compat.install()
from fighter_port import fighters, own_skeleton  # noqa: E402


def test_a_relative_import_is_read_against_its_package():
    tree = ast.parse('from . import a\nfrom .b import c\nfrom .. import d\nimport e.f\n'
                     'def g():\n    from .h import i\n')
    got = own_skeleton._imports(tree, 'pkg.sub')
    for name in ('pkg.sub', 'pkg.sub.a', 'pkg.sub.b', 'pkg.sub.b.c', 'pkg', 'pkg.d', 'e.f', 'pkg.sub.h'):
        assert name in got                              # (an import inside a function counts too)


def test_the_rig_and_the_body_are_keyed_on_their_own_code_and_not_on_the_later_steps():
    rig = own_skeleton._code(own_skeleton.AFTER_THE_BODY + own_skeleton.THE_BODYS_OWN)
    body = own_skeleton._code(own_skeleton.AFTER_THE_BODY)
    for code in (rig, body):
        assert 'fighter_port.native_port' in code and 'fighter_port.scale_helpers' in code
        # the steps after the body, and the place a fighter's bindings and lopsided pairs are written, are not in it
        assert not {'fighter_port.own_data', 'fighter_port.own_route', 'fighter_port.fighters',
                    'fighter_port.preflight', 'fighter_port.port'} & set(code)
    assert 'fighter_port.own_faces' in body and 'fighter_port.own_faces' not in rig
    assert 'fighter_port.compat.smd' in body            # a helper module the body calls is read from its file
    # this file is read without the functions of the later steps: the rig's leaves out the body's as well
    assert rig['fighter_port.own_skeleton'] != body['fighter_port.own_skeleton']


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A made-up fighter's files, a donor's costume and a rig, and a row of values for it in fighters.py."""
    root, work, donor = tmp_path / 'root', tmp_path / 'work', tmp_path / 'donor'
    src = own_skeleton.source_dir(root, 'nobody')
    for f, data in (('model/body/c00/model.nusktb', b'bones'), ('model/body/c00/model.numshb', b'mesh'),
                    ('motion/body/c00/a00wait1.nuanmb', b'clip'), ('model/gun/c00/model.numshb', b'gun')):
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        (src / f).write_bytes(data)
    donor.mkdir()
    (donor / own_skeleton.DONOR['Marth']['costume']).write_bytes(b'costume')
    (work / 'rig').mkdir(parents=True)
    (work / 'rig' / 'rig-nobody.json').write_text('{}', 'utf-8')
    monkeypatch.setitem(fighters.FIGHTERS, 'nobody', {'taunt': 'appealhi'})
    return dict(root=root, work=work, donor=donor, src=src)


def body_note(g):
    return own_skeleton.made_from('body', 'nobody', g['root'], g['work'], 'Marth', g['donor'])


def test_the_bodys_note_changes_with_what_it_reads_and_not_with_what_it_does_not(game):
    before = body_note(game)
    # a value only a later step reads: the same note
    fighters.FIGHTERS['nobody'].update(lopsided=(('a', 'b'),), bindings={'HipN': 'Hip'})
    assert body_note(game) == before
    # a value the body reads: another
    fighters.FIGHTERS['nobody']['code_shown'] = {'rest': {'gun': False}}
    shown = body_note(game)
    assert shown['values'] != before['values']
    # a weapon carried from a second model: that model's files are read too
    fighters.FIGHTERS['nobody']['article_parts'] = [{'folder': 'gun', 'node': 'gun', 'joint': 'HandR', 'held_at': 'Have'}]
    carried = body_note(game)
    (game['src'] / 'model' / 'gun' / 'c00' / 'model.numshb').write_bytes(b'another gun')
    assert body_note(game)['game files'] != carried['game files']
    # the rig it stands on, the donor's costume, a clip
    for f in (game['work'] / 'rig' / 'rig-nobody.json', game['donor'] / 'PlMsNr.dat',
              game['src'] / 'motion' / 'body' / 'c00' / 'a00wait1.nuanmb'):
        was = body_note(game)
        f.write_bytes(f.read_bytes() + b' ')
        assert body_note(game) != was, f.name


def test_the_rigs_note_is_the_skeleton_and_the_clips(game):
    note = own_skeleton.made_from('rig', 'nobody', game['root'], game['work'])
    assert set(note) >= {'game files', 'code'} and 'rig' not in note and 'donor' not in note
    (game['src'] / 'model' / 'body' / 'c00' / 'model.numshb').write_bytes(b'another mesh')  # the body's, not the rig's
    assert own_skeleton.made_from('rig', 'nobody', game['root'], game['work']) == note
    (game['src'] / 'motion' / 'body' / 'c00' / 'a00attack11.nuanmb').write_bytes(b'a new clip')
    assert own_skeleton.made_from('rig', 'nobody', game['root'], game['work'])['game files'] != note['game files']


def test_a_step_is_kept_only_with_its_note_the_same_and_its_files_there(tmp_path):
    said = []
    out = tmp_path / 'body'
    made = out / 'nobody.dat'
    note = {'game files': 'a', 'code': {'fighter_port.skin_cost': '1', 'fighter_port.own_faces': '2'}}
    assert not own_skeleton._kept('body', out, [made], note, said.append)
    assert 'no note' in said[-1]
    own_skeleton._note(out, note)
    assert not own_skeleton._kept('body', out, [made], note, said.append)       # its file is not there
    assert 'gone' in said[-1]
    made.write_bytes(b'x')
    assert own_skeleton._kept('body', out, [made], note, said.append)
    assert 'kept' in said[-1]
    other = json.loads(json.dumps(note))
    other['code']['fighter_port.skin_cost'] = '3'
    assert not own_skeleton._kept('body', out, [made], other, said.append)
    assert said[-1].endswith('made again: code: fighter_port.skin_cost')        # says what changed


def test_prepare_writes_the_note_only_after_the_step_is_made():
    """A step stopped half way must not leave the note of a whole one: the old note goes before the step runs,
    the new one is written after it returns."""
    text = Path(own_skeleton.__file__).read_text('utf-8')
    prepare = text[text.index('\ndef prepare('):]
    for step, call in (('rig', 'freeze('), ('body', 'body(fighter')):
        gone = prepare.index(f"(work / '{step}' / 'made-from.json').unlink(")
        made = prepare.index(call, gone)
        noted = prepare.index(f"_note(work / '{step}', note)", made)
        assert gone < made < noted


def test_the_first_costume_is_copied_only_when_its_bytes_are_new(tmp_path):
    """The art stage refuses pictures older than the costume files. Ittle Dew's prepare, run again for a receipt,
    wrote the same costume over itself and made a round's pictures stale: the same bytes keep the file as it is."""
    import os
    made, dest = tmp_path / 'body' / 'static.dat', tmp_path / 'package' / 'costumes' / 'PlMsNr.dat'
    made.parent.mkdir(parents=True)
    made.write_bytes(b'the body')
    assert own_skeleton.put_costume(made, dest) and dest.read_bytes() == b'the body'
    os.utime(dest, (1_000_000, 1_000_000))
    assert not own_skeleton.put_costume(made, dest) and dest.stat().st_mtime == 1_000_000
    made.write_bytes(b'another body')
    assert own_skeleton.put_costume(made, dest) and dest.read_bytes() == b'another body'


def test_opacity_binding_changes_rebuild_only_the_body(game):
    before = body_note(game)
    rig = own_skeleton.made_from('rig', 'nobody', game['root'], game['work'])
    data = dict(material_opacity=dict(version=1, bindings=[dict(mesh='CapeShape', default=1.0)], clips={}))
    (game['src'] / 'game.json').write_text(json.dumps(data), encoding='utf-8')
    assert body_note(game) != before
    assert own_skeleton.made_from('rig', 'nobody', game['root'], game['work']) == rig
    after = body_note(game)
    data['unrelated'] = 'a move report does not change the costume'
    (game['src'] / 'game.json').write_text(json.dumps(data), encoding='utf-8')
    assert body_note(game) == after
