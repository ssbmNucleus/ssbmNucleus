"""What a body's skin costs the game each frame, the simpler weights, the low-detail copy, and the lists of pieces
the fighter's data names them in.

The first tests need no game files. The last run only when Duck Hunt's work folder is on this machine.
"""
import json
import os
import struct
from pathlib import Path

import pytest

from fighter_port import compat

compat.install()
from fighter_port import own_data as od, skin_cost   # noqa: E402
from shared.modellab import smd                      # noqa: E402


def test_simpler_keeps_the_heaviest_joints_and_all_of_the_weight():
    assert skin_cost.simpler([(4, 0.55), (7, 0.30), (9, 0.10), (2, 0.05)], 3, 10) == ((4, 6), (7, 3), (9, 1))
    assert skin_cost.simpler([(4, 0.55), (7, 0.30), (9, 0.10), (2, 0.05)], 2, 4) == ((4, 3), (7, 1))
    assert skin_cost.simpler([(1, 0.96), (2, 0.04)], 3, 10) == ((1, 10),)          # a share too small to keep goes
    assert skin_cost.simpler([(3, 1.0)], 3, 10) == ((3, 10),)
    for links in ([(0, 0.34), (1, 0.33), (2, 0.33)], [(5, 0.5), (6, 0.5)], [(1, 0.26), (2, 0.25), (3, 0.25), (4, 0.24)]):
        for most, steps in ((3, 10), (2, 8), (4, 20)):
            assert sum(p for _j, p in skin_cost.simpler(links, most, steps)) == steps


def vertex(*links):
    return smd.Vertex(pos=(0.0, 0.0, 0.0), normal=(0.0, 1.0, 0.0), uv=(0.0, 0.0), weights=list(links))


def toy_model():
    model = smd.SMD()
    model.triangles.append(smd.Triangle('skin', (vertex((1, 0.52), (2, 0.31), (3, 0.17)), vertex((1, 0.49), (2, 0.33), (3, 0.18)),
                                                 vertex((2, 1.0)))))
    model.triangles.append(smd.Triangle('eye', (vertex((5, 1.0)), vertex((5, 0.9), (6, 0.1)), vertex((5, 1.0)))))
    return model


def test_lighten_makes_near_weightings_the_same_one():
    model = toy_model()
    got = skin_cost.lighten(model, 3, 10)
    a, b, c = model.triangles[0].verts
    assert a.weights == b.weights == [(1, 0.5), (2, 0.3), (3, 0.2)] and c.weights == [(2, 1.0)]
    assert got['weightings_before'] == 5 and got['weightings_after'] == 4 and got['furthest_share_moved'] <= 0.05


def test_the_low_detail_copy_is_every_triangle_again_on_one_joint_a_vertex():
    model = toy_model()
    made = skin_cost.low_detail(model)
    assert made == {'zlow_skin': 'skin', 'zlow_eye': 'eye'}
    assert model.materials == ['skin', 'eye', 'zlow_skin', 'zlow_eye']            # the copy comes after the whole body
    assert [v.weights for v in model.triangles[2].verts] == [[(1, 1.0)], [(1, 1.0)], [(2, 1.0)]]
    assert [v.weights for v in model.triangles[0].verts][0] == [(1, 0.52), (2, 0.31), (3, 0.17)]   # the body is left


def costume(pieces):
    """A costume file with one joint and the given pieces; a piece is a list of groups, a group a list of
    weightings, a weighting a list of (joint, share). Only what `skin_cost.objects` reads is filled in."""
    data = bytearray(0x40)                                   # the joint
    struct.pack_into('>I', data, 4, 0x8E)

    def add(blob):
        at = len(data)
        data.extend(blob)
        return at

    last_piece = None
    for groups in pieces:
        piece = add(bytes(0x10))
        if last_piece is None:
            struct.pack_into('>I', data, 0x10, piece)
        else:
            struct.pack_into('>I', data, last_piece + 4, piece)
        last_piece, last_group = piece, None
        for weightings in groups:
            ones = []
            for links in weightings:
                blob = b''.join(struct.pack('>If', 0x1 + j, w) for j, w in links) + bytes(8)
                ones.append(add(blob))
            named = add(b''.join(struct.pack('>I', o) for o in ones) + bytes(4))
            group = add(struct.pack('>IIIHHII', 0, 0, 0, 0x2000, 3, 0, named))
            if last_group is None:
                struct.pack_into('>I', data, piece + 0xC, group)
            else:
                struct.pack_into('>I', data, last_group + 4, group)
            last_group = group
    name = b'Toy_Share_joint\0'
    head = struct.pack('>5I', 0x20 + len(data) + 8 + len(name), len(data), 0, 1, 0) + bytes(12)
    return bytes(head + data + struct.pack('>II', 0, 0) + name)


def test_cost_counts_weightings_group_by_group():
    blend, one = [(3, 0.5), (4, 0.5)], [(3, 1.0)]
    file = costume([[[blend, one], [blend]], [[one]]])
    rows = skin_cost.objects(file)
    assert rows.pop() == 1
    assert [(r['groups'], r['matrices'], r['weights'], r['most_joints']) for r in rows] == [(2, 3, 5, 2), (1, 1, 1, 1)]
    assert skin_cost.cost(file) == dict(joints=1, objects=2, groups=3, matrices=4, weights=6, most_in_a_group=2,
                                        list_bytes=3 * 96)
    assert skin_cost.cost(file, only=[1])['matrices'] == 1


def test_pieces_are_the_body_then_its_copy_and_a_copy_that_blends_is_refused():
    blend, one = [(3, 0.5), (4, 0.5)], [(3, 1.0)]
    assert skin_cost.pieces(costume([[[blend]], [[one]]]), 1) == dict(high=[0], low=[1])
    with pytest.raises(ValueError):
        skin_cost.pieces(costume([[[one]], [[blend]]]), 1)             # the halves are the wrong way round
    with pytest.raises(ValueError):
        skin_cost.pieces(costume([[[blend]], [[one]], [[one]]]), 1)    # not a body and one copy
    # a body that carries parts it shows and hides copies only what it draws at rest
    three = costume([[[blend]], [[blend]], [[blend]], [[one]], [[one]]])
    assert skin_cost.pieces(three, 3, [0, 2]) == dict(high=[0, 1, 2], low=[3, 4])
    with pytest.raises(ValueError):
        skin_cost.pieces(three, 3, [0])                               # two copies came out, one was asked for


def test_pictures_only_hidden_parts_use_are_made_small_and_soft_edges_cut(tmp_path):
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(1)
    plain = rng.integers(0, 255, (256, 256, 4), dtype=np.uint8)
    plain[..., 3] = 255
    soft = plain.copy()
    soft[:, :128, 3] = np.linspace(0, 255, 128, dtype=np.uint8)[None, :]          # a soft edge across its left half
    tiny = plain[:64, :64].copy()
    for name, pixels in (('rest', plain), ('same', plain), ('eye', plain[::-1].copy()), ('wing', soft), ('dot', tiny)):
        Image.fromarray(pixels, 'RGBA').save(tmp_path / f'{name}.png')
    done = skin_cost.small_pictures(tmp_path, ['same', 'eye', 'wing', 'dot'], ['rest'])
    assert done == {'eye': {'size': [[256, 256], [128, 128]]}, 'wing': {'cutout': True, 'size': [[256, 256], [128, 128]]}}
    size = lambda name: Image.open(tmp_path / f'{name}.png').size     # noqa: E731
    assert size('rest') == size('same') == (256, 256)             # a picture a resting part uses too is not touched
    assert size('eye') == size('wing') == (128, 128) and size('dot') == (64, 64)
    alpha = np.asarray(Image.open(tmp_path / 'wing.png'))[..., 3]
    assert set(np.unique(alpha)) == {0, 255} and 0.2 < (alpha == 0).mean() < 0.3     # all or nothing, cut at the middle


def test_a_large_piece_s_low_detail_copy_keeps_a_fifth_of_its_triangles_on_one_joint_a_vertex():
    """A grid of 20 by 20 squares (800 triangles) whose left half is held by joint 1 and right half by joint 2."""
    model = smd.SMD()
    n = 20

    def corner(i, j):
        joint = 1 if i < n / 2 else 2
        return smd.Vertex(pos=(float(i), float(j), 0.1 * ((i * j) % 3)), normal=(0.0, 0.0, 1.0),
                          uv=(i / n, j / n), weights=[(joint, 0.7), (3, 0.3)])
    for i in range(n):
        for j in range(n):
            model.triangles.append(smd.Triangle('skin', (corner(i, j), corner(i + 1, j), corner(i + 1, j + 1))))
            model.triangles.append(smd.Triangle('skin', (corner(i, j), corner(i + 1, j + 1), corner(i, j + 1))))
    made = skin_cost.low_detail(model)
    low = [t for t in model.triangles if t.material == 'zlow_skin']
    assert made == {'zlow_skin': 'skin'} and len(model.triangles) - len(low) == 800
    assert 100 <= len(low) <= 240                                  # about a fifth
    assert all(len(v.weights) == 1 and v.weights[0][1] == 1.0 and v.weights[0][0] in (1, 2) for t in low for v in t.verts)
    xs = [v.pos[0] for t in low for v in t.verts]
    assert min(xs) == 0.0 and max(xs) == float(n)                  # the open edges are kept where they are
    whole = skin_cost.low_detail(model, {'skin'}, share=1.0)        # share 1.0: every triangle again
    assert len([t for t in model.triangles if t.material == 'zlow_skin']) == len(low) + 800 and whole == made


def test_a_part_hidden_at_rest_keeps_half_its_triangles_and_its_picture_seams():
    """Two grids of 20 by 20 squares: 'wing' (hidden at rest) has a seam of its picture down its middle (the two
    halves' picture coordinates do not meet), 'body' is shown at rest; 'eye' is hidden but small."""
    model = smd.SMD()
    n = 20

    def corner(i, j, half):
        return smd.Vertex(pos=(float(i), float(j), 0.1 * ((i * j) % 3)), normal=(0.0, 0.0, 1.0),
                          uv=(i / n + (0.5 if half else 0.0), j / n), weights=[(1, 1.0)])
    for material in ('body', 'wing'):
        for i in range(n):
            for j in range(n):
                h = material == 'wing' and i >= n / 2
                model.triangles.append(smd.Triangle(material, (corner(i, j, h), corner(i + 1, j, h), corner(i + 1, j + 1, h))))
                model.triangles.append(smd.Triangle(material, (corner(i, j, h), corner(i + 1, j + 1, h), corner(i, j + 1, h))))
    model.triangles.append(smd.Triangle('eye', (corner(0, 0, 0), corner(1, 0, 0), corner(1, 1, 0))))
    done = skin_cost.fewer_hidden(model, {'wing', 'eye'})
    count = lambda m: sum(t.material == m for t in model.triangles)              # noqa: E731
    assert list(done) == ['wing'] and done['wing'][0] == 800 and 300 <= done['wing'][1] <= 480
    assert count('body') == 800 and count('wing') == done['wing'][1] and count('eye') == 1
    assert model.materials == ['body', 'wing', 'eye']                            # the parts keep their order
    seam = sorted({v.pos[1] for t in model.triangles if t.material == 'wing' for v in t.verts if v.pos[0] == n / 2})
    assert seam == [float(j) for j in range(n + 1)]                              # the seam is kept, every corner of it
    for t in model.triangles:                                                    # and no corner took the other side's picture
        if t.material == 'wing':
            assert len({v.uv[0] > 0.75 for v in t.verts}) == 1                  # (left 0 to 0.5, right 1 to 1.5)
            for v in t.verts:                                                    # nor does the picture slide: each corner's
                side = 0.5 if v.uv[0] > 0.75 else 0.0                            # coordinate is where it now lies
                assert abs(v.uv[0] - side - v.pos[0] / n) < 0.02 and abs(v.uv[1] - v.pos[1] / n) < 0.02


def test_the_low_detail_copy_can_be_of_some_materials_only():
    model = toy_model()
    made = skin_cost.low_detail(model, {'eye'})
    assert made == {skin_cost.LOW + 'eye': 'eye'}
    assert [t.material for t in model.triangles] == ['skin', 'eye', skin_cost.LOW + 'eye']


REPO = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2])
DONOR_DIR = REPO / 'app/scratch/brawl-oneshot/port/donor'
WORK = REPO / 'app/scratch/duckhunt-native'
SOURCE = Path(os.environ.get('ULTIMATE_DUMP') or Path.home() / 'shulk-calibration-20260904')
HAVE = all(p.exists() for p in (DONOR_DIR / 'PlMs.dat', WORK / 'rig/rig-duckhunt.json', WORK / 'rig/lookup.json',
                                WORK / 'body/duckhunt.dat', WORK / 'body/receipt.json',
                                SOURCE / 'gamedata/fighter/duckhunt/param/vl.prc'))
real = pytest.mark.skipif(not HAVE, reason='Duck Hunt\'s work folder or the donor is not here')


@real
def test_duck_hunts_body_is_within_what_the_game_can_skin():
    body = (WORK / 'body/duckhunt.dat').read_bytes()
    receipt = json.loads((WORK / 'body/receipt.json').read_text('utf-8'))
    named = receipt['pieces']
    # (a body made since its switched parts are carried names them in groups: what is drawn at rest is the pieces
    # that are always drawn and each group's resting choice, and the low-detail copy is of those)
    switched = named.get('groups') or []
    at_rest = sorted(named['high'] + [p for g, r in zip(switched, named.get('rest') or []) if r >= 0 for p in g[r]])
    count = len(named['high']) + sum(len(choice) for g in switched for choice in g)
    got = skin_cost.pieces(body, count, at_rest if switched else None)
    assert got['low'] == named['low'] and got['high'] == list(range(count))
    high, low = skin_cost.cost(body, at_rest), skin_cost.cost(body, got['low'])
    assert high['matrices'] < 3200                 # as imported from the source's own weights it was 8,156
    assert low['matrices'] < 200 and low['weights'] == low['matrices']
    marth = skin_cost.cost((DONOR_DIR / 'PlMsNr.dat').read_bytes())
    assert (marth['objects'], marth['matrices'], marth['weights']) == (85, 387, 497)


@real
def test_the_fighter_data_names_the_body_and_its_low_detail_copy():
    pl = (DONOR_DIR / 'PlMs.dat').read_bytes()
    frozen = json.loads((WORK / 'rig/rig-duckhunt.json').read_text('utf-8'))
    lookup = json.loads((WORK / 'rig/lookup.json').read_text('utf-8'))
    body = (WORK / 'body/duckhunt.dat').read_bytes()
    pieces = json.loads((WORK / 'body/receipt.json').read_text('utf-8'))['pieces']
    out, report = od.build(pl, frozen, lookup, SOURCE, 'duckhunt', 'Marth', body, pieces=pieces)
    assert report['verify']['ok'], report['verify']['problems']
    shown = [r for r in od.census(out, 'ftDataMars', joints=102)['facts']['visibility'] if r['pieces']]
    by_mode = {r['mode']: r['pieces'] for r in shown if r['group'] == 0}
    assert by_mode[0] == pieces['high'] == by_mode[3] and by_mode[1] == pieces['low']
    # (a body that carries switched parts has a group for each set of them, drawn in the high-detail pass and
    # while metal: tests/test_own_faces.py holds those against the plan)
    switched = pieces.get('groups') or []
    assert {(r['mode'], r['group'], r['variant']) for r in shown} == {(0, 0, 0), (1, 0, 0), (3, 0, 0)} | {
        (mode, g + 1, k) for mode in (0, 3) for g, choices in enumerate(switched) for k in range(len(choices))}
    # without the pieces nothing is named: every piece is drawn in every pass (the body twice a frame)
    _plain, quiet = od.build(pl, frozen, lookup, SOURCE, 'duckhunt', 'Marth', body)
    assert quiet['verify']['ok'] and quiet['model_tables']['pieces_named_now'] == 0
