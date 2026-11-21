"""The clips a fighter on its own skeleton plays outside a match (fighter_port/own_demo.py): the results screen's
and the cut scenes'. The last test reads the donor's package, the frozen rig and the source fighter's clips, and
runs only where those are.

    python -m pytest tests/test_own_demo.py -q
"""
import io
import json
import os
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from fighter_port import own_bank as ob
from fighter_port import own_demo as od
from fighter_port import own_dynamics
from fighter_port.evaluation import Key

PREFIX = 'PlyTest5K_Share'
SYMBOL = PREFIX + '_ACTION_%s_figatree'
# the donor's fourteen rows, by the names its own symbols give them (row 4 has no clip)
MOTIONS = ['Win1', 'Win1Wait', 'Win2', 'Win2Wait', None, 'Win3', 'Win3Wait', 'Selected', 'SelectedWait', 'Lose',
           'IntroL', 'IntroR', 'Ending', 'Wait1']
LOOPED = {'Win1Wait', 'Win2Wait', 'Win3Wait', 'Lose', 'Ending', 'Wait1'}
FILES = dict(demoFile='PlTsDViWaitAj.dat', demoWait='ftDemoViWaitMotionFileTest', demoResult='ftDemoResultMotionFileTest',
             demoIntro='ftDemoIntroMotionFileTest', demoEnding='ftDemoEndingMotionFileTest', rstAnimFile='GmRstMTs.dat',
             rstAnimCount=14)


def clip(symbol, frames=10.0, joints=3, value=1.0):
    """A clip of `joints` joints with one curve, on its second joint."""
    nodes = [[] for _ in range(joints)]
    nodes[1] = [(5, *ob.pack_curve([Key(0., 0., 'linear'), Key(float(frames), value, 'linear')]))]
    return ob.write_figatree(symbol, frames, nodes)


def little_fighter(noisy=(0, 2, 5, 10), shared=None):
    """A fighter data file with nothing in it but a demo table of the donor's fourteen rows, their byte pairs and
    their scripts (the rows in `noisy` with a script that does something), and the two demo files the package
    carries. -> (the fighter data, {file name: bytes}). `shared`: a dict to fill with the game's two archives
    that hold the intro's and the ending's clips (the rows then point into them, as the donor's do)."""
    from vault.echo import datroot
    from vault.echo.subactions import COMMANDS, FighterDat
    sound = next(code for code, spec in COMMANDS.items() if spec.key == 'sound_effect')
    result = [(SYMBOL % m, clip(SYMBOL % m, 20 + i)) for i, m in enumerate(MOTIONS[:10]) if m]
    wait = [(SYMBOL % 'Wait1', clip(SYMBOL % 'Wait1', 30))]
    spans = {}
    files = {}
    for root, name, entries in ((FILES['demoResult'], FILES['rstAnimFile'], result),
                                (FILES['demoWait'], FILES['demoFile'], wait)):
        files[name], made = od.pack_file(root, entries)
        spans.update(made)
    spans[SYMBOL % 'IntroL'], spans[SYMBOL % 'IntroR'], spans[SYMBOL % 'Ending'] = (0, 0x116B), (0x1180, 0x118B), (0, 0x1553)
    if shared is not None:
        for root, name, motions in ((FILES['demoIntro'], 'IrAls.dat', ('IntroL', 'IntroR')),
                                    (FILES['demoEnding'], 'GmRegEnd.dat', ('Ending',))):
            shared[name], made = od.pack_file(root, [(SYMBOL % m, clip(SYMBOL % m, 10 if 'Intro' in m else 30))
                                                     for m in motions])
            spans.update(made)
    table = 0x40
    pairs = table + od.ROW * len(MOTIONS)
    data = bytearray(pairs + 2 * len(MOTIONS))
    data += bytes(-len(data) % 4)
    struct.pack_into('>II', data, 0x14, table, pairs)
    relocations = [0x14, 0x18]
    for i, motion in enumerate(MOTIONS):
        row = table + od.ROW * i
        script = len(data)
        data += FighterDat.encode_script([(sound, {}, None)] if i in noisy else [])[0]
        start, length, flags = 0, 0, 0x12
        if motion:
            symbol = SYMBOL % motion
            struct.pack_into('>I', data, row, len(data))
            relocations.append(row)
            data += symbol.encode() + b'\0'
            data += bytes(-len(data) % 4)
            start, length = spans[symbol]
            flags |= ob.LOOPS if motion in LOOPED else own_dynamics.FOLLOW_CLIP
        struct.pack_into('>IIIII', data, row + 4, start, length, script, flags, 0)
        relocations.append(row + 0x0C)
    return datroot.build(bytes(data), relocations, [(0, 'ftDataTest')], []), files


def little_source(joints=5, stems=('a00wait1', 'j02lose', 'j02win1', 'j02win1wait', 'j02win2', 'j02win2wait', 'j02win3',
                                   'j02win3wait', 'c00attack11')):
    """What `build` asks of a source, for a rig of `joints` joints whose first is the engine's own."""
    order = ['Top', 'Trans'] + [f'J{i}' for i in range(joints - 2)]
    return SimpleNamespace(target=SimpleNamespace(order=order), above=['Top'], stems=lambda: sorted(stems),
                           hash=lambda stem: f'hash of {stem}')


@pytest.fixture
def made_by_hand(monkeypatch):
    """The bank's clip makers, standing in: a clip of the rig's joints with one curve, as long as its source says."""
    lengths = {'a00wait1': 120, 'j02lose': 60, 'j02win1': 146, 'j02win1wait': 66, 'j02win2': 130, 'j02win2wait': 126,
               'j02win3': 164, 'j02win3wait': 60}
    calls = []

    def row(blob, frames, stems):
        return dict(budget=ob.BUDGETS[0], bytes=len(blob), tried=[dict(budget=ob.BUDGETS[0], bytes=len(blob))],
                    frames=frames, stems=stems, error=dict(whole=0.0, between=0.0))

    def make_clip(source, symbol, job, keep, capacity, reducer=None):
        stem = job['parts'][0]['stem']
        calls.append((symbol, stem, keep, capacity))
        blob = clip(symbol, lengths[stem], len(source.target.order))
        return blob, row(blob, lengths[stem], [stem])

    def make_hold(source, symbol, frames, pose, capacity):
        calls.append((symbol, None, '', capacity))
        blob = clip(symbol, frames, len(source.target.order), value=0.5)
        return blob, row(blob, frames, [])

    monkeypatch.setattr(ob, 'make_clip', make_clip)
    monkeypatch.setattr(ob, 'make_hold', make_hold)
    monkeypatch.setattr(ob, 'job_travel', lambda source, job: ({}, None))
    monkeypatch.setattr(ob, 'hold_pose', lambda source, stem: 'the standing pose')
    monkeypatch.setattr(od, '_shares', lambda source: {None: {}, 'j02win1': {'Ear1': 0.0}, 'j02lose': {'Ear1': 0.0}})
    return calls


FROZEN = dict(order=['Top', 'Trans', 'J0', 'Ear1', 'Ear2'], parent={}, rest={}, provenance={},
              swing=dict(chains=[dict(joints=['Ear1', 'Ear2'])]))


# ---- what the engine does with the table -----------------------------------------------------------------------------
def test_the_screens_take_the_rows_the_engine_gives_them():
    assert [(s['name'], s['first'], s['last']) for s in od.SCENES] == [
        ('results', 0, 9), ('intro', 10, 11), ('ending', 12, 12), ('cut scenes', 13, 13)]
    assert [od.scene_of(i)['name'] for i in (0, 9, 10, 11, 12, 13)] == [
        'results', 'results', 'intro', 'intro', 'ending', 'cut scenes']
    assert od.scene_of(14) is None and od.ROWS == 14
    # the rows a demo fighter is started in; the waits, the empty row and the two "selected" rows are never entered
    assert sorted(od.ENTERED) == [0, 2, 5, 9, 10, 11, 12, 13]
    assert od.DEMO_CAPACITY == 0xB000 and od.CAPACITY <= od.DEMO_CAPACITY
    # only the results screen's file and the cut scenes' are in a fighter's package; the intro's and the ending's
    # clips are in two archives of the game's that hold every fighter's
    assert [s.get('shared') for s in od.SCENES] == [None, 'IrAls.dat', 'GmRegEnd.dat', None]


def test_the_demo_table_is_read_with_its_names():
    pl, _files = little_fighter()
    rows = od.demo_rows(pl)
    assert [r['motion'] for r in rows] == MOTIONS and len(rows) == od.ROWS
    assert rows[4]['symbol'] is None and (rows[4]['start'], rows[4]['size']) == (0, 0)
    assert rows[0]['symbol'] == SYMBOL % 'Win1' and rows[0]['pair'] == (0, 0)
    assert all(bool(r['flags'] & ob.LOOPS) == (r['motion'] in LOOPED) for r in rows if r['motion'])


# ---- which clip ------------------------------------------------------------------------------------------------------
def test_each_row_takes_the_fighters_clip_of_its_own_name():
    pl, _files = little_fighter()
    rows = od.demo_rows(pl)
    jobs, without = od.jobs_for('nobody', rows[:10] + rows[13:], little_source().stems())
    got = {r['motion']: jobs[r['symbol']]['parts'] for r in rows if r['symbol'] in jobs}
    assert got == {'Win1': [dict(stem='j02win1')], 'Win1Wait': [dict(stem='j02win1wait')],
                   'Win2': [dict(stem='j02win2')], 'Win2Wait': [dict(stem='j02win2wait')],
                   'Win3': [dict(stem='j02win3')], 'Win3Wait': [dict(stem='j02win3wait')],
                   'Lose': [dict(stem='j02lose')], 'Wait1': [dict(stem='a00wait1')]}
    # the source has nothing called "selected": those rows have no job, and the reason is kept
    assert set(without) == {SYMBOL % 'Selected', SYMBOL % 'SelectedWait'}
    assert jobs[SYMBOL % 'Lose']['loop'] and not jobs[SYMBOL % 'Win1']['loop']


def test_a_rows_swing_flags_come_from_the_clip_it_plays():
    chains = [dict(joints=['Ear1', 'Ear2', 'Ear3']), dict(joints=['Tail1', 'Tail2'])]
    shares = {None: {}, 'by hand': {'Ear1': 0.0, 'Ear2': 0.0, 'Tail1': 0.0}, 'ears only': {'Ear1': 0.0}}
    assert od.swing_word(chains, shares, 'by hand', []) == (own_dynamics.FOLLOW_CLIP, 0, 'every chain follows the clip')
    assert od.swing_word(chains, shares, 'not named', []) == (0, 0, 'every chain swings')
    assert od.swing_word(chains, shares, None, []) == (0, 0, 'every chain swings')
    assert od.swing_word(chains, shares, 'ears only', [[9, 9], [1, 0]])[:2] == (own_dynamics.USE_ROW, 1)
    bits, which, words = od.swing_word(chains, shares, 'ears only', [[9, 9]])      # a row the data does not hold
    assert (bits, which) == (0, 0) and 'does not hold' in words
    assert od.swing_word([], shares, 'by hand', []) == (0, 0, 'every chain swings')
    assert od.swing_word(chains, None, 'by hand', []) == (0, 0, 'every chain swings')   # no swing-blend file


# ---- the files -------------------------------------------------------------------------------------------------------
def test_a_demo_file_is_clips_end_to_end_behind_one_root():
    from vault.echo import datroot
    entries = [(SYMBOL % 'Win1', clip(SYMBOL % 'Win1', 12)), (SYMBOL % 'Lose', clip(SYMBOL % 'Lose', 7, joints=6))]
    blob, spans = od.pack_file('ftDemoResultMotionFileTest', entries)
    data, relocations, roots, extern = datroot.parse(blob)
    assert roots == [(0, 'ftDemoResultMotionFileTest')] and not relocations and not extern
    assert struct.unpack_from('>I', blob)[0] == len(blob)
    data, at = od.root_data(blob, 'ftDemoResultMotionFileTest')
    for symbol, made in entries:
        start, length = spans[symbol]
        assert start % 0x20 == 0 and od.cut(data, at, dict(start=start, size=length)) == made
        assert od.holds(made, symbol) and not od.holds(made, 'another name') and not od.holds(made[:len(made) // 2], symbol)
    with pytest.raises(ValueError):
        od.root_data(blob, 'ftDemoViWaitMotionFileTest')


def test_the_files_are_made_again_and_the_table_pointed_at_them(made_by_hand):
    pl, donor = little_fighter()
    before = od.demo_rows(pl)
    new_pl, files, report = od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, donor, source=little_source(), log=lambda *a: None)
    rows = od.demo_rows(new_pl)
    assert sorted(files) == sorted(donor) and report['verify']['ok'], report['verify']['problems']
    assert report['verify']['rows'] == 10 and report['verify']['clips'] == 10

    # every row of the two screens reads back as its own clip on the rig's five joints, the clip of its own name
    played = {r['motion']: (r['kind'], r['stem'], r['frames']) for r in report['rows'] if r.get('kind') in ('SOURCE', 'HELD')}
    assert played == {'Win1': ('SOURCE', 'j02win1', 146), 'Win1Wait': ('SOURCE', 'j02win1wait', 66),
                      'Win2': ('SOURCE', 'j02win2', 130), 'Win2Wait': ('SOURCE', 'j02win2wait', 126),
                      'Win3': ('SOURCE', 'j02win3', 164), 'Win3Wait': ('SOURCE', 'j02win3wait', 60),
                      'Selected': ('HELD', None, 27.0), 'SelectedWait': ('HELD', None, 28.0),   # the donor clips' lengths
                      'Lose': ('SOURCE', 'j02lose', 60), 'Wait1': ('SOURCE', 'a00wait1', 120)}
    assert sorted(report['held']) == ['Selected', 'SelectedWait']
    for scene, name, root in (('results', FILES['rstAnimFile'], FILES['demoResult']),
                              ('cut scenes', FILES['demoFile'], FILES['demoWait'])):
        data, at = od.root_data(files[name], root)
        s = next(s for s in od.SCENES if s['name'] == scene)
        for row in rows[s['first']:s['last'] + 1]:
            if row['symbol']:
                piece = od.cut(data, at, row)
                assert od.holds(piece, row['symbol']) and ob.node_count(piece) == 5
                assert ob.read_clip(piece)['frames'] == played[row['motion']][2]
        assert report['files'][name]['root'] == root and report['files'][name]['bytes'] == len(files[name])
    assert (rows[4]['start'], rows[4]['size']) == (0, 0)
    assert all(call[3] == od.CAPACITY for call in made_by_hand) and len(made_by_hand) == 10

    # the rows whose files the package does not carry keep their starts and lengths, and are named
    for i in (10, 11, 12):
        assert (rows[i]['start'], rows[i]['size']) == (before[i]['start'], before[i]['size'])
        assert report['rows'][i]['kind'] == 'DONOR'
    assert sorted(report['not_carried']) == ['ending', 'intro']
    assert report['not_carried']['intro']['root'] == FILES['demoIntro'] and report['not_carried']['intro']['rows'] == [10, 11]

    # swing chains: a clip the source poses by hand follows the clip, the rest swing; nothing else in the flags moved
    follows = {r['motion'] for r in rows if r['flags'] & own_dynamics.FOLLOW_CLIP}
    assert follows == {'Win1', 'Lose', 'IntroL', 'IntroR'}                     # the last two are the donor's own, untouched
    assert all(r['flags'] & ~own_dynamics.BOTH == b['flags'] & ~own_dynamics.BOTH for r, b in zip(rows, before))
    assert report['rows'][0]['swing'] == 'every chain follows the clip' and report['rows'][2]['swing'] == 'every chain swings'

    # no demo row's script does anything any more, and the report says what was in the ones that did
    from vault.echo.subactions import FighterDat
    ft = FighterDat(new_pl)
    assert all([c.key for c in ft.decode_script(r['script']).commands] == ['end_of_script'] for r in rows)
    assert report['scripts']['emptied'] == {i: ['sound_effect'] for i in (0, 2, 5, 10)}

    # a second time gives the same bytes
    again_pl, again, _ = od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, donor, source=little_source(), log=lambda *a: None)
    assert (again_pl, again) == (new_pl, files)


def test_what_is_written_is_read_back_the_way_the_game_reads_it(made_by_hand):
    pl, donor = little_fighter()
    new_pl, files, _report = od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, donor, source=little_source(), log=lambda *a: None)

    def problems(pl=new_pl, made=files, nodes=5, engine=(0,), capacity=od.CAPACITY):
        return ' '.join(od.verify(pl, made, FILES, nodes, engine, capacity)['problems'])
    assert problems() == ''
    assert 'the rig has 6' in problems(nodes=6)                                    # the wrong count of joints
    assert "engine's own joints" in problems(engine=(1,))                          # a curve on a joint the engine owns
    assert 'the limit is 64' in problems(capacity=0x40)                            # a clip too long
    assert 'still does something' in problems(pl=pl, made=donor, nodes=3)          # the donor's scripts
    # a table one clip off still points at good clips, only the wrong ones
    from vault.echo.subactions import FighterDat
    ft = FighterDat(new_pl)
    table = ft.dat.ptr(ft.ft_root + 0x14)
    rows = od.demo_rows(new_pl)
    for at, other in ((0, rows[2]), (2, rows[0])):
        ft.dat.set_u32(table + at * od.ROW + 4, other['start'])
        ft.dat.set_u32(table + at * od.ROW + 8, other['size'])
    assert 'not one archive rooted' in problems(pl=ft.dat.to_bytes())
    # a file without the root the screen asks for
    renamed = dict(files)
    renamed[FILES['demoFile']] = od.pack_file('some other root', [(SYMBOL % 'Wait1', clip(SYMBOL % 'Wait1', 9, 5))])[0]
    assert 'has no root' in problems(made=renamed)


def test_a_donor_file_that_is_not_the_donors_own_is_refused(made_by_hand):
    pl, donor = little_fighter()
    wrong = dict(donor)
    wrong[FILES['rstAnimFile']] = od.pack_file(FILES['demoResult'], [(SYMBOL % 'Lose', clip(SYMBOL % 'Lose', 9))])[0]
    with pytest.raises(ValueError, match='does not hold this clip'):
        od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, wrong, source=little_source(), log=lambda *a: None)


def test_only_the_screens_whose_file_is_given_are_made(made_by_hand):
    pl, donor = little_fighter()
    only = {FILES['demoFile']: donor[FILES['demoFile']]}
    new_pl, files, report = od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, only, source=little_source(), log=lambda *a: None)
    assert list(files) == [FILES['demoFile']] and sorted(report['not_carried']) == ['ending', 'intro', 'results']
    rows, before = od.demo_rows(new_pl), od.demo_rows(pl)
    assert all((r['start'], r['size']) == (b['start'], b['size']) for r, b in zip(rows[:13], before[:13]))
    assert [call[1] for call in made_by_hand] == ['a00wait1']


def test_the_routes_hook_writes_the_files_and_names_them(made_by_hand, tmp_path, monkeypatch):
    pl, donor = little_fighter()
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as z:
        z.writestr('fighter.json', json.dumps(dict(files=FILES)))
        for name, blob in donor.items():
            z.writestr(name, blob)
    package.seek(0)
    monkeypatch.setattr(ob, 'Source', lambda root, fighter, frozen: little_source())
    monkeypatch.setattr(od, 'shared', lambda log=print: {})         # the original disc is not to hand
    (tmp_path / 'replace.json').write_text(json.dumps({'EfTsData.dat': 'EfOwnData.dat'}), 'utf-8')
    said = []
    new_pl, report = od.write(tmp_path, pl, FROZEN, 'nowhere', 'nobody', package, log=said.append)
    listed = json.loads((tmp_path / 'replace.json').read_text('utf-8'))
    assert listed == {'EfTsData.dat': 'EfOwnData.dat', FILES['rstAnimFile']: FILES['rstAnimFile'],
                      FILES['demoFile']: FILES['demoFile']}
    made = {name: (tmp_path / name).read_bytes() for name in donor}
    assert od.verify(new_pl, made, FILES, 5, (0,))['ok'] and sorted(report['written']) == sorted(donor)
    assert 'not carried: intro, ending' in said[-1] and '8 rows' in said[-1]
    assert json.loads((tmp_path / 'extra.json').read_text('utf-8')) == {'files': [], 'fighter_files': {}}


def test_the_intro_card_and_the_ending_get_files_of_the_fighters_own(made_by_hand, tmp_path, monkeypatch):
    """Their clips are in two archives of the game's, under the donor's roots. m-ex asks first for a file named
    after the fighter's root: each screen gets one under a root of the fighter's own, a held pose as long as the
    donor's clip, and the package's entry is told the new names."""
    archives = {}
    pl, donor = little_fighter(shared=archives)
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as z:
        z.writestr('fighter.json', json.dumps(dict(files=FILES)))
        for name, blob in donor.items():
            z.writestr(name, blob)
    package.seek(0)
    monkeypatch.setattr(ob, 'Source', lambda root, fighter, frozen: little_source())
    monkeypatch.setattr(od, 'shared', lambda log=print: archives)
    said = []
    new_pl, report = od.write(tmp_path, pl, FROZEN, 'nowhere', 'nobody', package, log=said.append)
    block = {'demoIntro': 'ftDemoIntroMotionFileNobody', 'demoIntroFile': 'ftDemoIntroMotionFileNobody.dat',
             'demoEnding': 'ftDemoEndingMotionFileNobod', 'demoEndingFile': 'ftDemoEndingMotionFileNobod.dat'}
    assert report['files_block'] == block and report['not_carried'] == {}
    extra = json.loads((tmp_path / 'extra.json').read_text('utf-8'))
    assert extra == {'files': ['ftDemoEndingMotionFileNobod.dat', 'ftDemoIntroMotionFileNobody.dat'],
                     'fighter_files': {'demoIntro': block['demoIntro'], 'demoEnding': block['demoEnding']}}
    # they are not in the package, so nothing of the package's is replaced by them
    assert set(json.loads((tmp_path / 'replace.json').read_text('utf-8'))) == {FILES['rstAnimFile'], FILES['demoFile']}
    rows = od.demo_rows(new_pl)
    for name, root, wanted in ((block['demoIntroFile'], block['demoIntro'], (10, 11)),
                               (block['demoEndingFile'], block['demoEnding'], (12,))):
        data, at = od.root_data((tmp_path / name).read_bytes(), root)
        for i in wanted:
            piece = od.cut(data, at, rows[i])
            assert od.holds(piece, rows[i]['symbol']) and ob.node_count(piece) == 5      # the rig's joints, not the donor's 3
            assert ob.read_clip(piece)['frames'] == (30 if i == 12 else 10)             # as long as the donor's clip
    held = {r['motion']: r['kind'] for r in report['rows'] if r['index'] in (10, 11, 12)}
    assert held == {'IntroL': 'HELD', 'IntroR': 'HELD', 'Ending': 'HELD'}
    made = {n: (tmp_path / n).read_bytes() for n in list(donor) + extra['files']}
    assert od.verify(new_pl, made, dict(FILES, **block), 5, (0,))['ok']
    assert 'not carried: nothing' in said[-1]


# ---- with the game's files -------------------------------------------------------------------------------------------
SCRATCH = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2]) / 'app' / 'scratch'
OWN = SCRATCH / 'duckhunt-native'
ROOT = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
has_source = ((OWN / 'rig' / 'rig-duckhunt.json').exists() and (OWN / 'data' / 'PlMs.dat').exists()
              and (OWN / 'Marth.zip').exists()
              and (ROOT / 'gamedata' / 'fighter' / 'duckhunt' / 'motion' / 'body' / 'c00').exists())


@pytest.mark.skipif(not has_source, reason="needs the donor's package, the frozen rig and the source fighter's clips")
def test_duck_hunts_results_screen_is_built_and_reads_back(tmp_path):
    from fighter_port import compat
    compat.install()
    from vault.echo.subactions import FighterDat
    frozen = json.loads((OWN / 'rig' / 'rig-duckhunt.json').read_text('utf-8'))
    pl = (OWN / 'data' / 'PlMs.dat').read_bytes()
    with zipfile.ZipFile(OWN / 'Marth.zip') as z:
        files = json.loads(z.read('fighter.json'))['files']
        donor = {files[k]: z.read(files[k]) for k in ('rstAnimFile', 'demoFile')}
    # the clips are kept where the route keeps them, so this is quick once the route has run; else they are made here
    shared = OWN / 'bank' / 'cache'
    cache = shared if shared.is_dir() else tmp_path
    new_pl, made, report = od.build(pl, frozen, ROOT, 'duckhunt', files, donor, cache=cache, log=lambda *a: None)

    assert sorted(made) == ['GmRstMMs.dat', 'PlMsDViWaitAj.dat'] and report['verify']['ok']
    assert od.root_data(made['GmRstMMs.dat'], 'ftDemoResultMotionFileMars')[1] == 0
    assert od.root_data(made['PlMsDViWaitAj.dat'], 'ftDemoViWaitMotionFileMars')[1] == 0
    rows = od.demo_rows(new_pl)
    assert len(rows) == files['rstAnimCount'] == 14
    took = {r['motion']: (r['kind'], r.get('stem')) for r in report['rows'] if r.get('motion')}
    assert took == {'Win1': ('SOURCE', 'j02win1'), 'Win1Wait': ('SOURCE', 'j02win1wait'), 'Win2': ('SOURCE', 'j02win2'),
                    'Win2Wait': ('SOURCE', 'j02win2wait'), 'Win3': ('SOURCE', 'j02win3'),
                    'Win3Wait': ('SOURCE', 'j02win3wait'), 'Selected': ('HELD', None), 'SelectedWait': ('HELD', None),
                    'Lose': ('SOURCE', 'j02lose'), 'IntroL': ('DONOR', None), 'IntroR': ('DONOR', None),
                    'Ending': ('DONOR', None), 'Wait1': ('SOURCE', 'a00wait1')}
    by_motion = {r['motion']: r for r in report['rows'] if r.get('motion')}
    # a clip is the game's own, frame for frame; a held row lasts as long as the donor's clip did
    assert [by_motion[m]['frames'] for m in ('Win1', 'Win2', 'Win3', 'Lose', 'Wait1')] == [146, 130, 164, 60, 120]
    assert by_motion['Selected']['frames'] == by_motion['Selected']['donor_frames'] == 120
    # every clip is the rig's 102 joints, under the engine's limit for a demo row, and no worse than the bank's
    engine = [i for i, j in enumerate(frozen['order']) if j not in ob.under(frozen['parent'], ob.ROOT)]
    checked = od.verify(new_pl, made, files, 102, engine)
    assert checked['ok'] and checked['rows'] == checked['clips'] == 10
    assert 0x8000 < checked['largest']['bytes'] <= od.DEMO_CAPACITY           # a victory clip is past the bank's limit
    assert sorted(report['thinned']) == ['Win1', 'Win2', 'Win3']
    assert all(by_motion[m]['whole'] < 0.02 for m in took if took[m][0] in ('SOURCE', 'HELD'))
    # the victory clips and the clap pose the ears by hand; the standing clip leaves them to swing
    for row in rows:
        follows = bool(row['flags'] & own_dynamics.FOLLOW_CLIP)
        if row['motion'] in ('Win1', 'Win1Wait', 'Win2', 'Win2Wait', 'Win3', 'Win3Wait', 'Lose'):
            assert follows and not row['flags'] & own_dynamics.USE_ROW
        elif row['motion'] in ('Selected', 'SelectedWait', 'Wait1'):
            assert not row['flags'] & own_dynamics.BOTH
    # nothing of the donor's is left in a demo row's script, and the fighter's own actions are as they were
    ft, was = FighterDat(new_pl), FighterDat(pl)
    assert all([c.key for c in ft.decode_script(r['script']).commands] == ['end_of_script'] for r in rows)
    assert sorted(report['scripts']['emptied']) == [0, 2, 5, 10]
    assert [(a.symbol, a.anim_offset, a.anim_size, a.flags, a.script_offset) for a in ft.actions] == \
           [(a.symbol, a.anim_offset, a.anim_size, a.flags, a.script_offset) for a in was.actions]
    # the intro's and the ending's rows still point where the donor's did
    before = od.demo_rows(pl)
    assert all((rows[i]['start'], rows[i]['size']) == (before[i]['start'], before[i]['size']) for i in (10, 11, 12))


def test_a_win_pose_plays_the_sounds_the_route_gives_it(made_by_hand, monkeypatch):
    """Every demo row's script of the donor's is taken out; a row that plays the fighter's own clip may be given one
    of waits and sounds (the source game's sounds for a win pose), and nothing else gets through."""
    from vault.echo.subactions import COMMANDS, FighterDat
    sound = next(code for code, spec in COMMANDS.items() if spec.key == 'sound_effect')
    other = next(code for code, spec in COMMANDS.items() if spec.key == 'graphic_effect')
    pl, donor = little_fighter()
    monkeypatch.setattr(ob, 'Source', lambda root, fighter, frozen: little_source())
    asked = []

    def script_for(line):
        asked.append((line['motion'], line['stem'], line['kind']))
        return FighterDat.encode_script([(sound, {}, None)])[0] if line['motion'] == 'Win1' else None

    new_pl, files, report = od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, donor, script_for=script_for)
    assert report['scripts']['voiced'] == {0: 'j02win1'}
    # only rows that play the fighter's own clip are asked about (a held pose has no script of the game's)
    assert all(kind == 'SOURCE' for _, _, kind in asked) and ('Win1', 'j02win1', 'SOURCE') in asked
    ft = FighterDat(new_pl)
    rows = od.demo_rows(new_pl)
    assert [c.key for c in ft.decode_script(rows[0]['script']).commands if c.key != 'end_of_script'] == ['sound_effect']
    assert all(c.key == 'end_of_script' for c in ft.decode_script(rows[2]['script']).commands)
    # a script that does more than wait and play sounds is refused
    with pytest.raises(ValueError):
        od.build(pl, FROZEN, 'nowhere', 'nobody', FILES, donor,
                 script_for=lambda line: FighterDat.encode_script([(other, {}, None)])[0])


def test_a_made_files_name_fits_the_games_buffer_or_the_one_player_intro_stops_the_game():
    """lbfile.c builds a file's name in 0x20 bytes: "ftDemoIntroMotionFileZetterburn.dat" stopped Classic mode
    ("Error : file name too long", lbfile.c line 153) as the versus card loaded."""
    for scene in od.SCENES:
        if 'made_root' in scene:
            for fighter in ('zetterburn', 'duckhunt', 'ike', 'x'):
                name = od.made_root(scene, fighter) + '.dat'
                assert len(name) + 1 <= 0x20 and name.startswith(scene['made_root'].format(Fighter=''))
    intro = next(s for s in od.SCENES if s['name'] == 'intro')
    assert od.made_root(intro, 'zetterburn') == 'ftDemoIntroMotionFileZetter'
    assert od.made_root(intro, 'ike') == 'ftDemoIntroMotionFileIke'

