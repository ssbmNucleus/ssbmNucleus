"""fighter_port.chain_weapon: a weapon that bends, as joints added after the donor's own."""
import importlib.util
import struct
from pathlib import Path

import pytest

from fighter_port import chain_weapon as cw
from fighter_port.oneshot import at_frame
from vault.echo import datroot
from vault.echo.subactions import Dat

_spec = importlib.util.spec_from_file_location('weapon_files', Path(__file__).with_name('test_oneshot_weapons.py'))
files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(files)


def test_thinning_keeps_the_corners():
    assert cw._thin([0, 1, 2, 3, 4], 0.01) == [0, 4]                  # a straight line needs its two ends
    assert cw._thin([0, 1, 2, 1, 0], 0.01) == [0, 2, 4]               # and one more key at the corner
    assert cw._thin([0, 0.004, 0, -0.004, 0], 0.01) == [0, 4]         # wobble inside the tolerance is dropped


def test_a_command_goes_in_at_its_frame():
    switch = (31, {'struct_id': 1, 'extrabitnonsense': 0, 'object_id': 5}, None)
    script = [(2, {'frame': 7}, None), (11, {}, None), (2, {'frame': 13}, None), (16, {}, None), (0, {}, None)]
    assert at_frame(script, 0, switch)[0] == switch
    assert at_frame(script, 2, switch)[:3] == [(2, {'frame': 2}, None), switch, script[0]]
    assert at_frame(script, 7, switch)[:4] == [script[0], script[1], switch, script[2]]      # shares the frame-7 wait
    assert at_frame(script, 20, switch)[-3:] == [(2, {'frame': 20}, None), switch, (0, {}, None)]
    looping = [(3, {'count': 2}, None)] + script
    assert at_frame(looping, 9, switch)[0] == switch                  # a script that loops: at its start


def clip(symbol, joints):
    table = bytes(joints) + b'\xff'
    table += bytes(-len(table) % 4)
    head = struct.pack('>IIfII', 1, 0, 40.0, 0x14, 0x14 + len(table))
    return datroot.build(head + table + bytes(12), [0xC, 0x10], [(0, symbol)], [])


def bank(*clips):
    return b''.join(c + b'\xff' * (-len(c) % 0x20) for c in clips)


def test_one_clip_is_widened_and_the_rest_left_alone():
    a, b = clip('A_figatree', 90), clip('B_figatree', 90)
    out = cw.widen_clip(bank(a, b), 'B_figatree', 128, datroot)
    first, second = [blob for _, blob in cw._clips(out)]
    assert first == a
    data, _, roots, _ = datroot.parse(second)
    assert roots[0][1] == 'B_figatree'
    nodes = struct.unpack_from('>I', data, roots[0][0] + 0xC)[0]
    assert data[nodes:nodes + 129] == bytes(128) + b'\xff'
    assert struct.unpack_from('>f', data, roots[0][0] + 8)[0] == 40.0        # the frame count is kept
    with pytest.raises(ValueError):
        cw.widen_clip(bank(a, b), 'C_figatree', 128, datroot)


def costume_and_addon(extra_joints=0):
    """A costume of root -> A, then B beside A (three joints, B the last under the root), and an
    add-on file of two joints whose root carries one mesh."""
    root, a, b = bytearray(0x40), bytearray(0x40), bytearray(0x40)
    struct.pack_into('>I', root, 8, 1)
    struct.pack_into('>I', a, 0xC, 2)
    costume = files.dat([(root, [8]), (a, [0xC]), (b, [])], [(0, 'PlyTest5K_Share_joint')])
    r, s, mesh = bytearray(0x40), bytearray(0x40), bytearray(0x10)
    struct.pack_into('>I', r, 4, 1 << 18)                            # the add-on root draws in the opaque pass
    struct.pack_into('>II', r, 8, 2, 0)                              # child s
    struct.pack_into('>I', r, 0x10, 3)                               # its mesh
    acc = bytearray(0x2C)
    struct.pack_into('>I', acc, 0, 1)
    structs = [(bytes(4), []), (r, [8, 0x10]), (s, []), (mesh, []), (acc, [0]),
               (bytearray(struct.pack('>I', 4)), [0]), (bytearray(struct.pack('>IIII', 0, 0, 1, 5)), [0xC])]
    addon = files.dat(structs, [(0, 'stub'), (6, 'mexCostume')])
    return costume, addon


def test_grafted_joints_come_after_the_costumes_own():
    costume, addon = costume_and_addon()
    out, report = cw.graft(costume, addon, datroot, Dat)
    assert report['first_joint'] == 3 and report['joints'] == 2 and report['meshes'] == [0]
    d = Dat(out)
    assert [n for n, _ in d.roots] == ['PlyTest5K_Share_joint']       # the add-on's own roots are gone
    body = d.roots[0][1]
    tree = cw._tree(d, body)
    assert len(tree) == 5
    assert d.ptr(tree[2] + 0xC) == tree[3]                            # hung beside the costume's last joint
    assert d.u32(body + 4) & (1 << 28)                                # the root is flagged so the walk reaches it


def test_too_many_joints_is_refused(monkeypatch):
    costume, addon = costume_and_addon()
    monkeypatch.setattr(cw, 'MAX_JOINTS', 4)
    with pytest.raises(ValueError, match='game limit'):
        cw.graft(costume, addon, datroot, Dat)


def test_the_meshes_get_their_own_variant_of_the_slot():
    # ftData -> +8 look {2 slots, array} -> one costume table -> high list only -> slot 1 has two variants
    lists = (bytes([78, 79, 83, 0]), bytes([73, 74, 0, 0]))
    structs = [(bytearray(struct.pack('>III', 0, 0, 1)), [8]),                         # 0 ftData
               (bytearray(struct.pack('>II', 2, 2) + bytes(0x10)), [4]),               # 1 look
               (bytearray(struct.pack('>IIII', 3, 0, 0, 0)), [0]),                     # 2 the costume's table
               (bytearray(struct.pack('>IIII', 0, 0, 2, 4)), [12]),                    # 3 slots: slot 0 empty, slot 1
               (bytearray(struct.pack('>IIII', 3, 5, 2, 6)), [4, 12]),                 # 4 slot 1's two variants
               (bytearray(lists[0]), []), (bytearray(lists[1]), [])]
    pl = files.dat(structs, [(0, 'ftDataTest')])
    out, edited = cw.list_meshes(pl, 1, 5, [85, 86], Dat, tables=1)
    assert edited == 1
    d = Dat(out)
    slots = d.ptr(d.ptr(d.ptr(d.roots[0][1] + 8) + 4))               # look -> the costume's table -> its high list
    assert d.u32(slots + 8) == 6
    entries = d.ptr(slots + 12)
    assert [d.u32(entries + 8 * k) for k in range(6)] == [3, 2, 0, 0, 0, 2]
    for k, want in ((0, lists[0][:3]), (1, lists[1][:2]), (5, bytes([85, 86]))):
        at = d.ptr(entries + 8 * k + 4)
        assert bytes(d.buf[0x20 + at:0x20 + at + len(want)]) == want
    with pytest.raises(ValueError, match='already has'):
        cw.list_meshes(out, 1, 5, [85], Dat, tables=1)
