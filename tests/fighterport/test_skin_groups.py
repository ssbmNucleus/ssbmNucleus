"""A costume's polygon groups made again: the grouping, the cutting of strips, the file without its unused parts,
and that what is drawn stays the same.

The first tests need no game files. The last run only when the donor's costume is on this machine.
"""
import json
import os
import random
import struct
from pathlib import Path

import pytest

from fighter_port import compat

compat.install()
from fighter_port import skin_cost   # noqa: E402


def test_groups_hold_every_primitive_and_share_as_little_as_they_can():
    # two regions of ten weightings each, their primitives given turn and turn about (the importer's first-fit
    # would put half of each region in each group and name all twenty weightings twice)
    a, b = list(range(0, 10)), list(range(100, 110))
    needs = []
    for i in range(9):
        needs += [frozenset(a[i:i + 2]), frozenset(b[i:i + 2])]
    got = skin_cost.group(needs)
    assert all(len(g) <= 10 for g in got) and all(any(n <= g for g in got) for n in needs)
    assert sorted(sorted(g) for g in got) == [a, b]
    # weightings that cannot share a group are still each named once
    lone = [frozenset({k}) for k in range(25)]
    assert sum(len(g) for g in skin_cost.group(lone)) == 25 and len(skin_cost.group(lone)) == 3
    with pytest.raises(ValueError):
        skin_cost.group([frozenset(range(11))])


def test_a_cut_strip_draws_the_same_triangles_the_same_way_round():
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(3, 40)
        verts = [bytes([rng.randint(0, 255), rng.randint(0, 255)]) for _ in range(n)]
        which = [rng.randint(0, 5) for _ in range(n)]
        whole = sorted(skin_cost.triangles(0x98, list(zip(verts, which))))
        for most in (1, 2, 3, 4):
            parts = skin_cost.cut(verts, which, most)
            again = sorted(t for v, w in parts for t in skin_cost.triangles(0x98, list(zip(v, w))))
            assert again == whole
            assert all(len(set(w)) <= max(most, 3) for _v, w in parts)


def test_triangles_start_from_their_least_corner_and_keep_their_turn():
    a, b, c, d = (b'\1', 5), (b'\2', 5), (b'\3', 6), (b'\4', 6)
    assert skin_cost.triangles('triangle', [b, c, a]) == [(a, b, c)]
    assert skin_cost.triangles('triangle', [b, a, c]) == [(a, c, b)]             # the other way round is another
    assert skin_cost.triangles(0x98, [a, b, c, d]) == [(a, b, c), (b, d, c)]     # a strip's second triangle is turned
    assert skin_cost.triangles(0x98, [a, a, b, c]) == [(a, c, b)]                # two corners the same draw nothing


class File:
    """A small file of the game's kind: data, the places in it that are pointers, and one named root."""

    def __init__(self):
        self.data, self.slots = bytearray(), []

    def add(self, blob, pointers=(), align=4):
        self.data.extend(bytes(-len(self.data) % align))
        at = len(self.data)
        self.data.extend(blob)
        self.slots += [at + o for o in pointers]
        return at

    def point(self, slot, target):
        struct.pack_into('>I', self.data, slot, target)
        if slot not in self.slots:
            self.slots.append(slot)

    def bytes(self, root, name=b'Toy_Share_joint\0'):
        body = bytes(self.data) + struct.pack(f'>{len(self.slots)}I', *sorted(self.slots)) + struct.pack('>II', root, 0) + name
        return struct.pack('>5I', 0x20 + len(body), len(self.data), len(self.slots), 1, 0) + bytes(12) + body


def toy_costume(groups, flags=0xA000):
    """One joint, one piece; `groups`: [(weightings, primitives)], a weighting a list of (joint number, share), a
    primitive ('triangle' or 'strip', [(the weighting's place in its group, a vertex number)])."""
    f = File()
    f.add(bytes(8))                                              # nothing sits at place 0 (a zero is no pointer)
    joint = f.add(struct.pack('>II', 0, 0x8E) + bytes(0x38))
    piece = f.add(bytes(0x10))
    f.point(joint + 0x10, piece)
    buffer = f.add(bytes(64), align=32)
    desc = f.add(struct.pack('>6I', 0, 1, 0, 0, 0, 0) + struct.pack('>5I', 9, 3, 1, 3, 0) + struct.pack('>I', buffer)
                 + struct.pack('>I', 0xFF) + bytes(20), pointers=[0x18 + 20])
    last = None
    for weightings, primitives in groups:
        ones = []
        for links in weightings:
            blob = b''.join(struct.pack('>If', joint, share) for _j, share in links) + bytes(8)
            ones.append(f.add(blob, pointers=[8 * k for k in range(len(links))]))
        named = f.add(b''.join(struct.pack('>I', o) for o in ones) + bytes(4), pointers=[4 * k for k in range(len(ones))])
        lists = bytearray()
        for kind, corners in primitives:
            lists += bytes([0x90 if kind == 'triangle' else 0x98]) + struct.pack('>H', len(corners))
            lists += b''.join(bytes([3 * slot]) + struct.pack('>H', vertex) for slot, vertex in corners)
        lists += bytes(-len(lists) % 32)
        at = f.add(lists, align=32)
        group = f.add(struct.pack('>IIIHHII', 0, 0, desc, flags, len(lists) // 32, at, named), pointers=[8, 0x10, 0x14])
        f.point(piece + 0xC if last is None else last + 4, group)
        last = group
    return f.bytes(joint)


def scattered():
    """Two regions of four weightings, the importer's way: each group a strip from each region."""
    w = [[(0, 0.1 * (k + 1)), (0, 1 - 0.1 * (k + 1))] for k in range(8)]
    groups = []
    for k in range(3):
        left = ('strip', [(0, 10 + k), (1, 20 + k), (0, 30 + k), (1, 40 + k), (1, 50 + k)])
        right = ('triangle', [(2, 60 + k), (3, 70 + k), (2, 80 + k)])
        groups.append(([w[k], w[k + 1], w[4 + k], w[5 + k]], [left, right]))
    return toy_costume(groups)


def test_regrouping_names_each_weighting_less_and_draws_the_same():
    before = scattered()
    assert skin_cost.cost(before)['matrices'] == 12 and skin_cost.cost(before)['groups'] == 3
    after, report = skin_cost.regroup(before)
    assert skin_cost.drawn(after) == skin_cost.drawn(before) and None not in skin_cost.drawn(before)
    assert report['after']['matrices'] == 8 and report['after']['groups'] == 1       # eight weightings, each once
    assert report['pieces'] == [dict(piece=0, weightings=8, groups=1, matrices=8)]
    assert len(after) < len(before)                                                   # the old groups are gone
    again, second = skin_cost.regroup(after)
    assert second['after'] == report['after'] and skin_cost.drawn(again) == skin_cost.drawn(before)


def test_a_piece_that_cannot_be_taken_apart_is_left_as_it_is():
    rigid = toy_costume([([[(0, 1.0)]], [('triangle', [(0, 1), (0, 2), (0, 3)])])], flags=0x8000)
    out, report = skin_cost.regroup(rigid)
    assert out == rigid and report['pieces'] == [dict(piece=0, left='a group that is not skinned by weightings')]
    assert skin_cost.drawn(rigid) == [None]


def test_compacting_drops_what_nothing_points_to_and_keeps_places_in_32():
    f = File()
    f.add(bytes(8))
    root = f.add(bytes(16))
    dead = f.add(b'DEAD' * 16, align=32)
    picture = f.add(b'PICT' * 8, align=32)
    f.point(root, picture)
    tail = f.add(b'TAIL' * 2)
    f.point(root + 4, tail)
    old = f.bytes(root)
    new, dropped = skin_cost.compact(old, also={dead})
    assert dropped > 0 and b'DEAD' not in new and b'PICT' * 8 in new and b'TAIL' * 2 in new
    data_size, relocs = struct.unpack_from('>II', new, 4)
    slots = struct.unpack_from(f'>{relocs}I', new, 0x20 + data_size)
    places = [struct.unpack_from('>I', new, 0x20 + s)[0] for s in slots]
    assert new[0x20 + places[0]:0x20 + places[0] + 4] == b'PICT' and places[0] % 32 == 0
    assert new[0x20 + places[1]:0x20 + places[1] + 4] == b'TAIL'
    # without being told where the dead part began, it counts as the tail of the part before it and stays
    kept, none = skin_cost.compact(old)
    assert none == 0 and b'DEAD' in kept


REPO = Path(os.environ.get('NUCLEUS_REPO') or Path(__file__).resolve().parents[2])
MARTH = REPO / 'app/scratch/brawl-oneshot/port/donor/PlMsNr.dat'
DUCK = REPO / 'app/scratch/duckhunt-native/body/duckhunt.dat'


@pytest.mark.skipif(not MARTH.exists(), reason='the donor\'s costume is not here')
def test_the_games_own_costume_survives_both():
    b = MARTH.read_bytes()
    same, dropped = skin_cost.compact(b)
    assert dropped == 0 and same == b                       # the game's own file has nothing unused
    out, report = skin_cost.regroup(b)
    assert skin_cost.drawn(out) == skin_cost.drawn(b)
    assert report['after']['matrices'] <= report['before']['matrices'] == 387
    assert report['after']['objects'] == 85 and report['after']['joints'] == 90


@pytest.mark.skipif(not DUCK.exists(), reason='Duck Hunt\'s body is not here')
def test_duck_hunts_body_is_grouped_with_care():
    b = DUCK.read_bytes()
    got = skin_cost.cost(b)
    receipt = json.loads((DUCK.parent / 'receipt.json').read_text('utf-8')) if (DUCK.parent / 'receipt.json').exists() else {}
    if 'faces' in receipt:
        # the body carries every part its face switches (hidden ones cost no frame time): what is drawn at rest
        # and its low-detail copy are what the engine blends each frame
        assert receipt['skin']['body']['matrices'] < 1600 and receipt['skin']['low_detail']['matrices'] < 100
        assert got['matrices'] < 2600
    else:
        assert got['matrices'] < 1600 and got['objects'] == 30
    out, report = skin_cost.regroup(b)                      # made again, it gets no better
    assert report['after']['matrices'] >= got['matrices'] - 20 and skin_cost.drawn(out) == skin_cost.drawn(b)


def test_a_blend_that_comes_down_to_one_joint_stays_a_blend():
    """The engine reads a vertex held by one joint at full weight in that joint's own space and a blended vertex
    in the model's. `simpler` may leave a blended vertex one joint: `regroup` writes that as the joint twice, half
    and half, never as one joint (the vertex would be read in the wrong space)."""
    from fighter_port import skin_cost
    assert skin_cost.simpler([(7, 0.5), (7, 0.5)], 3, 10) == ((7, 10),)          # a joint named twice is one joint
    assert skin_cost.simpler([(7, 0.97), (9, 0.03)], 3, 10) == ((7, 10),)
