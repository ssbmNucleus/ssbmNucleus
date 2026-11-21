"""Preflight: everything that can be known before a port's first long stage, said at once.

The first tests need nothing but the code. The rest run it against the game's own files and Wolf's (a fighter the
route had never met when he was ported cold); each is skipped on a machine without them.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fighter_port import fighters, preflight


def ask(**more):
    return SimpleNamespace(**dict(dict(fighter='wolf', game='ultimate', donor='Marth', own=True, work='W', root='R',
                                       mextk=None, iso=None, no_extract=True, allow_large=False), **more))


def test_every_line_is_kept_and_a_check_that_falls_over_does_not_stop_the_rest():
    said = []
    lines = preflight.Lines(said.append)
    lines.section('the machine')
    lines.ok('a tool', 'there')
    lines.note('MexTK', 'none')

    def broken(_lines):
        raise KeyError('wolf')
    assert preflight.guarded(lines, 'bindings', broken) is None
    assert preflight.guarded(lines, 'after it', lambda l: l.ok('costumes', '8') or 'ran') == 'ran'
    assert [r['level'] for r in lines.rows] == ['ok', 'note', 'PROBLEM', 'ok']
    assert len(lines.problems()) == 1 and "KeyError: 'wolf'" in lines.problems()[0]['text'] and len(lines.notes()) == 1
    assert all(r['section'] == 'the machine' for r in lines.rows) and any('PROBLEM' in line for line in said)


def test_depth_is_the_most_joints_above_any_one():
    order = ['Trans', 'Rot', 'Hip', 'LegL', 'KneeL', 'Bust']
    parent = dict(Trans=None, Rot='Trans', Hip='Rot', LegL='Hip', KneeL='LegL', Bust='Hip')
    assert preflight.depth(order, parent) == 4 and preflight.depth(['Trans'], {'Trans': None}) == 0


def test_source_rig_can_use_existing_leaf_folding_but_final_overflow_stops(tmp_path,
                                                                                                     monkeypatch):
    """Prepare can fold weighted leaves too; the actual frozen rig still must fit."""
    from fighter_port import own_skeleton
    order = ['Trans', 'Rot'] + [f'B{i}' for i in range(141)]
    rig = SimpleNamespace(order=order, parent={j: (None if i == 0 else order[i - 1]) for i, j in enumerate(order)})

    def said(skinned):
        monkeypatch.setattr(own_skeleton, '_skinned', lambda fighter, root: skinned)
        lines = preflight.Lines(lambda _m: None)
        preflight.limits(lines, ask(work=str(tmp_path)), rig)
        return {r['what']: r for r in lines.rows}['joints']
    row = said(set(order[:120]))
    assert row['level'] == 'note' and 'folds the bones that cost no pose' in row['text']
    row = said(set(order))
    assert row['level'] == 'note' and 'Animated leaf bones' in row['text']
    (tmp_path/'rig').mkdir()
    (tmp_path/'rig/rig-wolf.json').write_text(json.dumps(dict(order=order,parent=rig.parent)))
    assert said(set(order))['level'] == 'PROBLEM'


def test_a_donor_the_route_does_not_know_is_a_problem_that_names_the_tables(tmp_path, monkeypatch):
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)
    monkeypatch.delenv('MEXTK_DIR', raising=False)      # the checklist has it set: then MexTK is found, not a prerequisite error
    lines = preflight.Lines(lambda _m: None)
    preflight.machine(lines, ask(donor='Fox', work=str(tmp_path), iso=str(tmp_path / 'no' / 'such' / 'out.iso')))
    said = {r['what']: r for r in lines.rows}
    assert said['the donor']['level'] == 'PROBLEM' and 'own_data.DONOR' in said['the donor']['text']
    # ... and it is not the only thing said: the checkout, the tools and the disc's folder are asked in the same go
    assert said['the app checkout']['level'] == 'PROBLEM' and 'NUCLEUS_REPO' in said['the app checkout']['text']
    assert said['the disc to write']['level'] == 'PROBLEM' and said['MexTK']['level'] == 'PROBLEM'
    assert said["the donor's package"]['level'] == 'note'          # the project stage makes it


def test_the_donors_package_is_looked_into(tmp_path, monkeypatch):
    import zipfile
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)
    with zipfile.ZipFile(tmp_path / 'Marth.zip', 'w') as z:
        z.writestr('fighter.json', json.dumps({'files': {'fighterDataPath': 'PlMs.dat', 'animFile': 'PlMsAJ.dat'}}))
        z.writestr('PlMs.dat', b'x')                    # (the animation bank is missing)
    lines = preflight.Lines(lambda _m: None)
    preflight.machine(lines, ask(work=str(tmp_path)))
    row = next(r for r in lines.rows if r['what'] == "the donor's package")
    assert row['level'] == 'PROBLEM' and 'PlMsAJ.dat' in row['text']


def test_a_root_that_is_not_a_dump_says_what_a_dump_holds(tmp_path):
    lines = preflight.Lines(lambda _m: None)
    assert preflight.files(lines, ask(root=str(tmp_path))) is None
    texts = ' '.join(r['text'] for r in lines.problems())
    assert 'romfs' in texts and 'Hashes_FullPath' in texts and 'smash_arc.dll' in texts and len(lines.problems()) == 3


def test_a_route_that_cannot_carry_the_game_is_said(tmp_path, monkeypatch):
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)
    lines = preflight.run(ask(game='brawl', own=True, root=str(tmp_path), work=str(tmp_path)), out=lambda _m: None)
    assert any(r['what'] == 'the route' and r['level'] == 'PROBLEM' for r in lines.rows)


# ------------------------------------------------------------------------------------------------ the game's files
ROOT = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
HAVE = (ROOT / 'Hashes_FullPath').exists() and (ROOT / 'gamedata/fighter/wolf/model/body/c00/model.nusktb').exists()
real = pytest.mark.skipif(not HAVE, reason="the game's files, with Wolf's out of the archive, are not on this machine")


@real
def test_the_files_a_port_reads_are_named_before_any_stage_reads_them():
    pytest.importorskip('ssbh_data_py')
    own, more = preflight.wanted(ROOT, 'wolf')
    assert any(p.endswith('model/body/c00/model.nusktb') for p in own) and any(p.endswith('param/vl.prc') for p in own)
    assert 'prebuilt:/nro/release/lua2cpp_wolf.nro' in more and 'effect/fighter/wolf/ef_wolf.eff' in more
    lines = preflight.Lines(lambda _m: None)
    folder = preflight.files(lines, ask(root=str(ROOT)))
    assert folder == ROOT / 'gamedata' / 'fighter' / 'wolf' and not lines.problems()


@real
def test_a_fighter_the_archive_does_not_have_is_named_with_the_ones_near_it():
    lines = preflight.Lines(lambda _m: None)
    assert preflight.files(lines, ask(fighter='wolff', root=str(ROOT))) is None
    assert len(lines.problems()) == 1 and "'wolff'" in lines.problems()[0]['text'] and 'wolf' in lines.problems()[0]['text']


@real
def test_wolf_cold_meets_no_problem_and_what_stopped_him_is_said(tmp_path, monkeypatch):
    """The four things that stopped Wolf's first runs one at a time, asked at once in an empty work folder: his files,
    a table of which joint is which, his lopsided knees, a picture format of his effect file."""
    pytest.importorskip('ssbh_data_py')
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)   # (the machine's own lines are another test's)
    lines = preflight.run(ask(root=str(ROOT), work=str(tmp_path)), out=lambda _m: None)
    said = {}
    for r in lines.rows:
        said.setdefault(r['what'], []).append(r)
    problems = [r for r in lines.problems() if r['section'] != 'the machine']
    assert not problems, problems
    assert said['bindings'][0]['level'] == 'ok' and 'by bone name' in said['bindings'][0]['text']
    assert 'digit 5 is the thumb' in said['bindings'][0]['text']
    assert said['its specials'][0]['level'] == 'note' and 'no fighter_port/own_wolf.py' in said['its specials'][0]['text']
    knees = said['hurtboxes, left and right'][0]
    assert knees['level'] == 'note' and 'KneeR' in knees['text'] and 'lopsided' in knees['text']
    assert said['hurtboxes'][0]['level'] == 'ok' and '13 in' in said['hurtboxes'][0]['text']
    assert said['effect pictures'][0]['level'] == 'ok' and '49' in said['effect pictures'][0]['text']
    assert said['joints'][0]['level'] == 'ok' and '105 bones' in said['joints'][0]['text']
    assert said['joint depth'][0]['level'] == 'ok' and said['clip bytes'][0]['level'] == 'note'
    assert said['taunt'][0]['level'] == 'ok' and said['costumes'][0]['level'] == 'ok'


@real
def test_a_fighter_nobody_wrote_anything_for_is_told_what_stands_in(tmp_path, monkeypatch):
    pytest.importorskip('ssbh_data_py')
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)
    monkeypatch.delitem(fighters.FIGHTERS, 'wolf')
    monkeypatch.setattr(fighters, 'specials_name', lambda fighter: 'own_nobody_wrote_this')     # (no such module)
    lines = preflight.run(ask(root=str(ROOT), work=str(tmp_path)), out=lambda _m: None)
    said = {r['what']: r for r in lines.rows}
    assert not [r for r in lines.problems() if r['section'] != 'the machine']
    assert said['its entry']['level'] == 'note' and 'nothing has to be written' in said['its entry']['text']
    assert said['taunt']['level'] == 'note' and 'down taunt' in said['taunt']['text'] and 'appealhir' in said['taunt']['text']
    assert said['item_hold']['level'] == 'note' and 'HaveR' in said['item_hold']['text']
    assert said['its specials']['level'] == 'note' and 'shared template' in said['its specials']['text']
    assert said['article_parts']['level'] == 'note' and 'blaster' in said['article_parts']['text']     # his second models are listed


@real
def test_what_is_written_wrong_for_a_fighter_is_said_with_the_file_to_change(tmp_path, monkeypatch):
    pytest.importorskip('ssbh_data_py')
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)
    monkeypatch.setitem(fighters.FIGHTERS, 'wolf', dict(taunt='appealdance', item_hold='Beak', taunts='x',
                                                        code_shown={'clips': {'d00nosuchclip': {}}},
                                                        article_parts=[dict(folder='sword', node='n', joint='HaveR', held_at='Have')]))
    lines = preflight.run(ask(root=str(ROOT), work=str(tmp_path)), out=lambda _m: None)
    wrong = {r['what']: r['text'] for r in lines.problems() if r['section'] != 'the machine'}
    # all five at once, each with what it should have been held against
    assert set(wrong) == {'its entry', 'taunt', 'item_hold', 'code_shown', 'article_parts'}
    assert 'taunts' in wrong['its entry'] and 'appealhir' in wrong['taunt'] and "'Beak'" in wrong['item_hold']
    assert 'd00nosuchclip' in wrong['code_shown'] and "'sword'" in wrong['article_parts']
    assert all('fighters.py' in text for text in wrong.values())


@real
def test_the_command_line_ends_with_the_count_and_leaves_its_lines_in_the_work_folder(tmp_path, monkeypatch, capsys):
    pytest.importorskip('ssbh_data_py')
    monkeypatch.delenv('NUCLEUS_REPO', raising=False)
    code = preflight.main(['wolf', '--own', '--work', str(tmp_path), '--root', str(ROOT), '--no-extract'])
    out = capsys.readouterr().out
    kept = json.loads((tmp_path / 'preflight.json').read_text('utf-8'))
    # (with no app checkout named, that is the one problem: it is said, counted, and makes the stage fail)
    assert code == 1 and kept['problems'] == 1 and f"preflight: 1 problem, {kept['notes']} notes:" in out
    assert [r for r in kept['lines'] if r['level'] == 'PROBLEM'][0]['what'] == 'the app checkout'
    assert out.rstrip().splitlines()[-1].startswith('  PROBLEM  the app checkout')


@pytest.mark.parametrize('own,level', [(True,'PROBLEM'),(False,'note')])
def test_native_compiler_is_required_for_own_skeleton_gameplay(tmp_path,monkeypatch,own,level):
    from fighter_port import code
    monkeypatch.delenv('NUCLEUS_REPO',raising=False)
    monkeypatch.delenv('MEXTK_DIR',raising=False)
    monkeypatch.setattr(code,'toolkit',lambda _:None)
    lines=preflight.Lines(lambda _:None)
    preflight.machine(lines,ask(own=own,work=str(tmp_path)))
    row=next(r for r in lines.rows if r['what']=='MexTK')
    assert row['level']==level
    assert '--mextk or MEXTK_DIR' in row['text']
    if own: assert 'specials inert' in row['text']
