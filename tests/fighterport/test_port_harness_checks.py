"""What the harness scripts decide without the game: whether a match loaded (the heap probe), where a fighter's head
is in its portrait and whether a picture is still of the body on the disc (the art stage).

None of these starts the game: each script's deciding is a plain function, given what was read.
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

HARNESS = Path(__file__).resolve().parents[2] / 'tools' / 'fighterport' / 'fighter_port' / 'harness'


def _load(name):
    sys.path.insert(0, str(HARNESS))
    spec = importlib.util.spec_from_file_location(name, HARNESS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


heap = _load('heap_probe')
art = _load('game_art')
identity = _load('own_identity')


# ---------------------------------------------------------------------------------------------------- the heap probe
def memory(heaps):
    """The game's heap table as `heap_rows` reads it: {heap number: (lo, hi, [(place, size), ...])}."""
    words, at = {}, 0x81000000
    for i, (lo, hi, held) in heaps.items():
        h = heap.ALLOC + 0x638 + 0x10 * i
        entries = [at + 0x20 * k for k in range(len(held))]
        at += 0x20 * len(held)
        words.update({h + 4: lo, h + 8: hi, h + 0xC: entries[0] if entries else 0})
        for k, (place, size) in enumerate(held):
            words.update({entries[k]: entries[k + 1] if k + 1 < len(entries) else 0, entries[k] + 4: place,
                          entries[k] + 8: size})
    return lambda address: words.get(address, 0)


def test_a_match_is_loaded_when_its_fighters_exist_and_its_frames_run():
    both = [dict(port=0, ft=0x80C00000, state=14), dict(port=1, ft=0x80D00000, state=14)]
    ok, why = heap.loaded(both, (1200, 1230))
    assert ok and '2 fighters exist' in why
    # the second costume did not fit: the game made one fighter and stopped loading. Its wait still came back.
    ok, why = heap.loaded([both[0], dict(port=1, ft=None, state=None)], (1200, 1230))
    assert not ok and 'no fighter for player 2' in why
    ok, why = heap.loaded([dict(port=0, ft=None, state=None), dict(port=1, ft=None, state=None)], (1200, 1230))
    assert not ok and 'player 1 and 2' in why
    # the fighters are there and the game has stopped
    assert not heap.loaded(both, (1200, 1200))[0] and not heap.loaded(both, (None, None))[0]
    # the game never got to a match at all
    ok, why = heap.loaded(both, (1200, 1230), scene=False)
    assert not ok and 'not in a match' in why


def test_the_probe_never_says_loaded_because_its_wait_came_back():
    text = (HARNESS / 'heap_probe.py').read_text('utf-8')
    said = text[text.index('scene = wait_in_game'):]
    # the one place it says IN THE MATCH is under what `loaded` found, and a match that did not load is an exit code
    assert said.index('ok, why = loaded(') < said.index('IN THE MATCH') < said.index('THE MATCH DID NOT LOAD')
    assert 'code = 2' in said and said.count('IN THE MATCH') == 1


def test_each_heap_is_read_with_the_size_of_every_file_it_holds():
    u32 = memory({0: (0x80500000, 0x80500000 + 6_599_680, [(0x80500000, 268_352), (0x80500000 + 268_352, 1_813_824),
                                                           (0x80500000 + 2_200_000, 611_136)]),
                  1: (0, 0, []),                                    # a heap the game has not set up
                  3: (0x81200000, 0x81200000 + 4096, [])})
    rows = heap.heap_rows(u32)
    assert [r['heap'] for r in rows] == [0, 3]
    files = rows[0]
    assert files['held'] == [268_352, 1_813_824, 611_136]
    # what is free is every gap; the largest run is the room one more file could take
    assert files['free'] == 6_599_680 - sum(files['held'])
    assert files['largest_run'] == 6_599_680 - 2_200_000 - 611_136
    assert rows[1]['held'] == [] and rows[1]['free'] == 4096


def test_a_held_size_is_named_when_the_disc_has_a_file_of_that_size():
    costumes = [dict(name=f'PlMs{c}.dat', size=1_813_808) for c in ('Nr', 'Re', 'Bu', 'Gr', 'Ye')]
    names = heap.names_by_size(costumes + [dict(name='GrNLa.dat', size=611_136), dict(name='LbRf.dat', size=96),
                                           dict(name='PlMs_001.dat', size=268_340)])
    assert len(names[1_813_824]) == 5 and names[611_136] == ['GrNLa.dat']        # held in a place rounded up to 32
    assert names[268_352] == ['PlMs_001.dat']
    lines = heap.heap_lines([dict(heap=4, lo=0x811de3e0, hi=0x811de3e0 + 6_599_680,
                                  held=[611_136, 1_813_824, 1_813_824, 268_352, 9_999, 96],
                                  free=2_000_000, largest_run=2_000_000)], names)
    assert '6 things held' in lines[0] and 'free 2.00 MB' in lines[0]
    # largest first; a fighter's costumes are all one size, so each is said as one of them
    assert lines[1].strip() == lines[2].strip() == '1,813,824 bytes  one of 5 files of that size (PlMsNr.dat, PlMsRe.dat, PlMsBu.dat ...)'
    assert lines[3].strip() == '611,136 bytes  GrNLa.dat' and lines[4].strip() == '268,352 bytes  PlMs_001.dat'
    assert lines[5].strip() == '9,999 bytes'                           # no file of that size: the size alone
    assert lines[6].strip() == '96 bytes'                              # the game's own bookkeeping: not named for a file that small


# --------------------------------------------------------------------------------------------------- the art stage
def body_points():
    """A made-up fighter as it stands: a body one wide (its left is +x), two tall, and a head stuck out ahead of it
    (+z) at the top. -> (points, which follow the head)"""
    body = np.array([[x, y, z] for x in (-0.5, 0.5) for y in (0.0, 2.0) for z in (-0.5, 0.5)], float)
    head = np.array([[x, y, z] for x in (-0.25, 0.25) for y in (1.5, 2.0) for z in (0.5, 1.5)], float)
    return np.r_[body, head], np.r_[np.zeros(len(body), bool), np.ones(len(head), bool)]


def test_the_head_is_found_from_the_fighters_own_head_and_the_cameras_side():
    points, is_head = body_points()
    # from the fighter's own front (the camera at the stage's +x, the way it faces): the head is in the middle
    left, top, right, bottom = art.head_fractions(points, is_head, 90.0)
    assert (left, right) == pytest.approx((0.25, 0.75)) and (top, bottom) == pytest.approx((0.0, 0.25))
    # from the front of the stage (the fighter seen from its right side): the head is ahead of the body, to the right
    left, top, right, bottom = art.head_fractions(points, is_head, 0.0)
    assert (left, right) == pytest.approx((0.5, 1.0)) and (top, bottom) == pytest.approx((0.0, 0.25))
    # ... and from behind the stage it is on the left: the side follows the camera, it is not a fixed corner
    left, top, right, bottom = art.head_fractions(points, is_head, 180.0)
    assert (left, right) == pytest.approx((0.0, 0.5))
    # a head lower on the body (a dog's is not at the top of a tall body) is lower in the picture
    points[is_head, 1] -= 1.0
    assert art.head_fractions(points, is_head, 0.0)[1] == pytest.approx(0.5)


def test_the_stock_icons_square_is_round_the_head_and_inside_the_cut_out():
    box = (10, 20, 210, 420)                                # the cut-out: 200 wide, 400 tall
    left, top, right, bottom = art.head_square(box, (0.25, 0.0, 0.75, 0.25))
    side = right - left
    assert side == bottom - top == round(100 * (1 + art.HEAD_ROOM))             # as large as the head's longer side, and a little
    assert (left + right) / 2 == pytest.approx(110, abs=1) and top == 20        # round its middle; not above the cut-out
    # a head at the very bottom: the square is kept inside the cut-out's height
    assert art.head_square(box, (0.25, 0.9, 0.75, 1.0))[3] <= 420
    # a wide, flat head: the square takes the longer side
    left, top, right, bottom = art.head_square(box, (0.0, 0.1, 1.0, 0.3))
    assert right - left == round(200 * (1 + art.HEAD_ROOM))


def test_a_picture_taken_before_its_costume_file_was_written_is_stale(tmp_path):
    work, shots = tmp_path / 'work', tmp_path / 'shots'
    (work / 'package' / 'costumes').mkdir(parents=True)
    shots.mkdir()
    rows = [dict(file='PlMsNr.dat', name='c00'), dict(file='PlMsRe.dat', name='c01'), dict(file='PlMsBu.dat', name='c02')]
    for row in rows:
        (work / 'package' / 'costumes' / row['file']).write_bytes(b'costume')
    for name in ('look_portrait-body.png', 'look_portrait-c1-body.png'):          # (costume 2 has no picture at all)
        (shots / name).write_bytes(b'picture')
    now = time.time()
    for path, when in ((work / 'package' / 'costumes' / 'PlMsNr.dat', now - 100), (shots / 'look_portrait-body.png', now - 50),
                       (shots / 'look_portrait-c1-body.png', now - 50), (work / 'package' / 'costumes' / 'PlMsRe.dat', now - 10),
                       (work / 'package' / 'costumes' / 'PlMsBu.dat', now - 10)):
        os.utime(path, (when, when))
    old = art.stale(work, rows, shots)
    # the first costume's picture is newer than its file; the second's file was written after its picture
    assert [(n, f) for n, f, _shot in old] == [(1, 'PlMsRe.dat')]
    assert art.picture(shots, 2) is None


def test_the_round_s_pictures_are_refused_when_they_are_of_an_older_body(tmp_path):
    import json
    work, shots = tmp_path / 'work', tmp_path / 'shots'
    (work / 'package' / 'costumes').mkdir(parents=True)
    shots.mkdir()
    (shots / 'look_portrait-body.png').write_bytes(b'picture')
    time.sleep(0.05)
    (work / 'package' / 'costumes' / 'PlMsNr.dat').write_bytes(b'a body made after the picture')
    (work / 'package' / 'costumes' / 'costumes.json').write_text(json.dumps([dict(file='PlMsNr.dat', name='c00')]), 'utf-8')
    os.utime(shots / 'look_portrait-body.png', (time.time() - 60, time.time() - 60))
    with pytest.raises(SystemExit, match='taken before the costume files were written'):
        art.main([str(work), '--shots', str(shots)])
    assert not (work / 'package' / 'art').exists()          # nothing was cut from them


# ------------------------------------------------------------------------------------------------- the look probe
def test_the_look_probes_tests_are_each_written_once():
    """Its table of tests had whole blocks pasted two and three times (the last copy of a name is the one that runs,
    so an edit to the first did nothing): every name is written once."""
    import ast
    source = (HARNESS / 'look_probe.py').read_text('utf-8')
    table = next(node.value for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'MOVES' for t in node.targets))
    names = [k.value for k in table.keys if isinstance(k, ast.Constant)]
    assert len(names) > 200 and not sorted({n for n in names if names.count(n) > 1})


def test_a_fighters_own_special_tests_name_their_scripts_for_the_sound_check():
    """The sound check listens only for the scripts named for a test (`audio_check.SCRIPTS`): Incineroar's round 1
    looked for his jump alone, and Ittle Dew's round 2 (13 tests of her own) listened for nothing. Each fighter's own
    tests name the scripts their states play."""
    import ast

    def table(name, var):
        source = (HARNESS / name).read_text('utf-8')
        node = next(n.value for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == var for t in n.targets))
        return {k.value for k in node.keys if isinstance(k, ast.Constant)}
    for prefix in ('ig_', 'id_'):               # Incineroar's, Ittle Dew's
        mine = {n for n in table('look_probe.py', 'MOVES') if n.startswith(prefix)}
        assert mine and mine <= table('audio_check.py', 'SCRIPTS'), prefix


def test_a_sound_only_a_ports_own_code_plays_is_listened_for_under_its_test():
    """The sound check listens for what the game's scripts play; no script plays a sound a port's own code plays (Ittle
    Dew's bomb as it bursts), so nothing listened for it: `audio_check.ENGINE` names it under the test that makes it."""
    import ast
    source = (HARNESS / 'audio_check.py').read_text('utf-8')
    node = next(n.value for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == 'ENGINE' for t in n.targets))
    engine = {k.value: [ast.unparse(e) for e in v.elts] for k, v in zip(node.keys, node.values)}
    assert "f'se_{fighter}_explosion'" in engine['id_side']


# ---------------------------------------------------------------------------------------------- the victory fanfare
def test_a_fanfare_is_looked_for_under_the_fighter_then_the_series_then_the_series_fighters():
    """A series' fanfare is named for the series' first fighter, not the series: Wolf's is Star Fox's, `..._f_fox`.
    The archive lists no stream paths, so the names are tried in an order, and the order is the rule."""
    names = identity.fanfare_names('wolf', 'starfox', ['fox', 'falco', 'wolf'])
    assert names == ['wolf', 'starfox', 'fox', 'falco']                # each once; the fighter's own first
    streams = identity.fanfare_streams(names)
    assert len(streams) == 400 and streams[0] == 'stream:/sound/bgm/bgm_z00_f_wolf.nus3audio'
    assert streams[99] == 'stream:/sound/bgm/bgm_z99_f_wolf.nus3audio' and streams[100].endswith('bgm_z00_f_starfox.nus3audio')
    assert streams.index('stream:/sound/bgm/bgm_z07_f_fox.nus3audio') == 207
    assert identity.named_for('stream:/sound/bgm/bgm_z07_f_fox.nus3audio') == 'fox'
    # a fighter whose series has no one else: its own name and the series', and nothing more
    assert identity.fanfare_names('duckhunt', 'duckhunt', []) == ['duckhunt']


DUMP = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
archive = pytest.mark.skipif(not all((DUMP / p).exists() for p in ('romfs/data.arc', 'Hashes_FullPath', 'ArcExplorer/smash_arc.dll')),
                             reason="the game's archive is not on this machine")


@archive
def test_wolfs_fanfare_is_found_under_his_series_first_fighter():
    assert identity.series_of(DUMP, 'wolf') == 'starfox'
    mates = identity.series_mates(DUMP, 'starfox')
    assert mates[0] == 'fox' and {'falco', 'wolf'} <= set(mates)       # the roster table's order: Fox first
    streams = identity.fanfare_streams(identity.fanfare_names('wolf', 'starfox', mates))
    got = identity.found(DUMP, streams)
    taken = next(s for s in streams if s in got)
    # nothing under his own name or the series': the first the archive holds is Fox's
    assert taken == 'stream:/sound/bgm/bgm_z07_f_fox.nus3audio' and identity.named_for(taken) == 'fox'


SCRATCH = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2]) / 'app' / 'scratch'
WOLF, DUCK = SCRATCH / 'wolf-cold', SCRATCH / 'duckhunt-native' / 'oneshot'
finished = pytest.mark.skipif(not all((w / 'data' / 'report.json').exists() and (w / 'body' / 'selection.json').exists()
                                      for w in (WOLF, DUCK)), reason="Wolf's and Duck Hunt's work folders are not here")


@finished
def test_wolfs_head_and_the_dogs_are_each_found_from_their_own_files():
    pytest.importorskip('ssbh_data_py')
    wolf, how = art.head_box(WOLF)
    dog, _how = art.head_box(DUCK)
    assert 'Head' in how and wolf is not None and dog is not None
    # both heads are at the top of their bodies; the dog's reaches the right edge of his picture (the old square,
    # the top right 0.62 of the width, was drawn round it), Wolf's stands over the middle of a taller body
    assert wolf[1] == dog[1] == 0.0 and dog[2] > 0.95 and wolf[2] < 0.9 and wolf[0] < 0.2
    assert 0.25 < wolf[3] < 0.35 and 0.4 < dog[3] < 0.5
    # the camera for a picture of the head alone is level with each one's own head (it was fixed at 13.5 for both;
    # the height found by hand for Wolf's face in his cold trial was 11.6)
    wolf_cam, dog_cam = (art.head_camera(w).split() for w in (WOLF, DUCK))
    assert float(wolf_cam[1]) == pytest.approx(11.7, abs=0.5) and float(dog_cam[1]) == pytest.approx(9.0, abs=0.7)
    # a work folder that cannot answer says why, and the stage then cuts the old way and says so
    box, why = art.head_box(SCRATCH / 'no-such-port')
    assert box is None and 'report.json' in why and art.head_camera(SCRATCH / 'no-such-port') is None


def test_the_emulators_words_over_a_picture_are_not_cut_out_with_the_fighter():
    """A close camera puts the head near the top, where the emulator writes its messages ("Wrote memory card A ...")
    letter by letter: specks not joined to the fighter are not his; a detached piece of some size (a flame) is."""
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (400, 500), (art.BG,) * 3)
    d = ImageDraw.Draw(im)
    d.ellipse((150, 40, 250, 380), fill=(90, 160, 220))                    # the fighter, his head at the top
    d.rectangle((100, 360, 300, 380), fill=(90, 160, 220))                 # his feet, wide
    d.rectangle((260, 150, 290, 200), fill=(250, 120, 20))                 # a flame of his, apart from him
    for i in range(12):                                                    # the words: letters a few pixels each
        d.rectangle((120 + 12 * i, 30, 126 + 12 * i, 38), fill=(255, 255, 0))
    cut = art.subject(im)
    alpha = np.asarray(cut.getchannel('A'))
    rgb = np.asarray(cut.convert('RGB')).astype(int)
    yellow = (rgb[..., 0] > 200) & (rgb[..., 1] > 200) & (rgb[..., 2] < 80) & (alpha > 128)
    assert not yellow.any()
    orange = (rgb[..., 0] > 200) & (rgb[..., 1] > 90) & (rgb[..., 1] < 150) & (alpha > 128)
    assert orange.sum() > 500


def test_the_portrait_camera_takes_the_body_when_it_is_taller_than_its_tallest_joint(tmp_path, monkeypatch):
    import json as _json
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'report.json').write_text(_json.dumps({'scale': {'drawn_height': 8.0}}), 'utf-8')
    head_above_the_jaw = np.array([[0.0, 0.0, 0.0], [0.0, 11.0, 0.0]])
    monkeypatch.setattr(art, 'standing', lambda work, frames=3: ([head_above_the_jaw], None, 'Head', 1.0))
    assert art.drawn_height(tmp_path) == pytest.approx(11.0)
    assert art.camera(tmp_path).split()[:2] == ['31.9', '4.6']
    monkeypatch.setattr(art, 'standing', lambda work, frames=3: (_ for _ in ()).throw(FileNotFoundError('no rig')))
    assert art.drawn_height(tmp_path) == pytest.approx(8.0)


def test_a_long_name_is_set_tighter_and_one_too_long_for_the_plate_is_left_to_the_plain_crop():
    """Incineroar, 2026-11-13: "INCINEROAR" is 61 pixels set at 0, and the plate holds 58; the first disc stopped."""
    tile = _load('roster_tile')

    class Pres:
        tried = []

        @staticmethod
        def css_cell(pane, css_dir, word, tracking):
            Pres.tried.append(tracking)
            width = 6 * len(word) + tracking * (len(word) - 1)
            if width > 58:
                raise ValueError('too wide')
            return ('cell', tracking)
    assert tile.name_cell(Pres, None, '.', 'INCINEROAR') == ('cell', -1) and Pres.tried == [2, 1, 0, -1]
    assert tile.name_cell(Pres, None, '.', 'INCINEROARINCI') is None
    assert tile.name_cell(Pres, None, '.', 'WOLF') == ('cell', 2)


def test_particle_check_finds_a_loop_and_a_live_particle_in_free_memory():
    # Greninja's Substitute (2026-11-13): the game hung in particleSort, drawing a list of particles that looped; a
    # stop dumps the lists and the heap they come from (particle_check), and PROBE_PARTICLES=1 reads them each step
    import struct
    pc = _load('particle_check')
    mem = bytearray(0x01800000)

    def w(a, v):
        struct.pack_into('>I', mem, a - 0x80000000, v)
    w(pc.HEAP_ARRAY, 0x80100000)
    w(pc.HEAP_HANDLE, 0)
    w(0x80100000 + 4, 0x80200000)                   # the free cells: one
    w(0x80100000 + 8, 0x80300000)                   # the allocated: one
    w(0x80200000 + 8, 0x1000)
    w(0x80300000 + 8, 0x1000)
    w(pc.LINK_HEADS, 0x80300040)                    # link 0: one particle in each
    w(0x80300040, 0x80200100)
    assert pc.faults(bytes(mem)) == [pc.faults(bytes(mem))[0]]
    assert 'lies in a FREE heap cell 0x80200000' in pc.faults(bytes(mem))[0]
    w(0x80200100, 0x80300040)                       # ... and now they loop
    assert pc.faults(bytes(mem))[0].startswith('link 0: 2 particles, then a loop back to 0x80300040')
    w(0x80200100, 0)
    w(0x80100000 + 4, 0)                            # nothing free: nothing wrong
    assert pc.faults(bytes(mem)) == []
    assert pc.summary(bytes(mem)).startswith('particles {0: 2}')
    # a frame later: a free particle is handed out and put at the head, and the old tail's next closes a loop
    before = pc.state(bytes(mem))
    w(pc.LINK_HEADS, 0x80300200)
    w(0x80300200, 0x80300040)
    w(0x80200100, 0x80300200)
    after = pc.state(bytes(mem))
    said = pc.changes(before, after)
    assert any(s.startswith('link 0: came 0x80300200 (node 0) next 0x80300040') for s in said), said
    assert any('0x80200100 (node 1 -> 2) next 0x0 -> 0x80300200' in s for s in said), said
    assert any(s.startswith('link 0: now a loop back to 0x80300200 (node 0)') for s in said), said
    lines = pc.listing(bytes(mem))
    assert lines[0] == 'link 0, 3 particles, then a loop back to 0x80300200 (node 0)' and len(lines) == 4


def test_the_probes_take_out_the_stage_particles_only_with_the_game_frozen():
    # G19 (checklist 9.22): the kill relinks the particle lists from outside; with the game running it races the game's
    # own particle update (unfrozen: a loop in 2 of 6 boots, particles lost in 2 more; frozen: never)
    for name in ('look_probe.py', 'sheet_probe.py'):
        lines = (HARNESS / name).read_text('utf-8').splitlines()
        calls = [i for i, line in enumerate(lines) if 'fs.kill_stage_particles(' in line]
        assert calls, f'{name} no longer takes out the stage particles: move this test with it'
        for i in calls:
            assert 'framestep.freeze(' in '\n'.join(lines[max(0, i - 15):i]), f'{name}:{i + 1} kills with the game running'
            assert 'framestep.unfreeze(' in '\n'.join(lines[i:i + 15]), f'{name}:{i + 1} leaves the game frozen'
