"""fighter_port.weapons: which move holds which weapon, and the add-on's place in a costume."""
import struct

import numpy as np

from fighter_port import weapons
from fighter_port.oneshot import source_time, weapon_for
from vault.echo import datroot
from vault.echo.subactions import Dat


def model(lo, hi):
    return {'min': np.array(lo, float), 'max': np.array(hi, float), 'parts': [], 'root': 'HaveR', 'triangles': 0}


MODELS = {'spear': model([-0.5, -2, -2], [0.5, 27, 2]), 'axe': model([-0.7, -4, -4], [0.7, 18, 6]),
          'bow': model([-0.5, -9, -3], [0.5, 9, 3])}


def move(points=(), articles=()):
    return {'hitboxes': [{'bone': 'haver', 'x': x, 'y': y, 'z': z} for x, y, z in points], 'articles': list(articles)}


def test_a_move_takes_the_smallest_weapon_that_holds_its_hitboxes():
    game = {'moves': {'game_attacks4': move([(0, 24, 0), (0, 3, 0)], ['A']),      # only the spear is that long
                      'game_attackairb': move([], ['A']),                         # names the article, no hold hitboxes
                      'game_attacklw4': move([(0, 14, 1)], ['B']),                # too long for the bow: the axe
                      'game_speciallw': move([(0, 14, 1)]),
                      'game_speciallwhit': move([(0, 0, 0)]),                     # fits every model: keeps its move's
                      'game_attackairn': move([(-4, 1.3, 0)], ['C']),             # spun: fits none, one model left
                      'game_attackhi4': move([], ['W']),                          # an article that is no held weapon
                      'game_attack11': {'hitboxes': [{'bone': 'top', 'x': 0, 'y': 9, 'z': 2}], 'articles': []}}}
    by, notes = weapons.assign(game, MODELS)
    assert by == {'game_attacks4': 'spear', 'game_attackairb': 'spear', 'game_attacklw4': 'axe',
                  'game_speciallw': 'axe', 'game_speciallwhit': 'axe', 'game_attackairn': 'bow'}
    assert any('by elimination' in n for n in notes)


def test_parts_of_one_move_share_its_weapon():
    by = {'game_attacks4': 'spear', 'game_specialnstart': 'bow'}
    assert weapon_for('game_attacks4charge', by) == 'spear'      # continues it
    assert weapon_for('game_specialn', by) == 'bow'              # begins it
    assert weapon_for('game_attack11', by) is None


def test_source_time_follows_the_keys():
    keys = [[0, 0.0], [2, 4.0], [33, 35.0]]
    assert source_time(keys, 1) == 2.0 and source_time(keys, 2) == 4.0 and source_time(keys, 40) == 35.0
    assert source_time(None, 7) == 7.0


def dat(structs, roots):
    """structs: [(bytes, [pointer offsets])] laid end to end; a pointer holds a struct index."""
    offsets, pos = [], 0
    for blob, _ in structs:
        offsets.append(pos)
        pos += len(blob)
    data, relocs = bytearray(), []
    for (blob, ptrs), base in zip(structs, offsets):
        blob = bytearray(blob)
        for p in ptrs:
            struct.pack_into('>I', blob, p, offsets[struct.unpack_from('>I', blob, p)[0]])
            relocs.append(base + p)
        data += blob
    return datroot.build(bytes(data), relocs, [(offsets[i], name) for i, name in roots], [])


def joint(dobjs):
    """A JObj (0x40 bytes) and its DObj chain; returns structs with the JObj first."""
    out = [(bytearray(0x40), [])]
    for k in range(dobjs):
        out.append((bytearray(0x10), []))
    if dobjs:
        struct.pack_into('>I', out[0][0], 0x10, 1)
        out[0] = (out[0][0], [0x10])
        for k in range(1, dobjs):
            struct.pack_into('>I', out[k][0], 4, k + 1)
            out[k] = (out[k][0], [4])
    return out


def addon_file(dobjs, shift=0):
    """mexCostume symbol -> one add-on whose root joint carries `dobjs` meshes. `shift` offsets struct indices."""
    j = joint(dobjs)
    n = len(j)
    structs = [(b, [p for p in ptrs]) for b, ptrs in j]
    for b, ptrs in structs:                       # joint-local indices are already relative to 0
        for p in ptrs:
            struct.pack_into('>I', b, p, struct.unpack_from('>I', b, p)[0] + shift)
    acc = bytearray(0x2C)
    struct.pack_into('>II', acc, 0, shift, 75)    # root joint, attach bone
    array = struct.pack('>I', shift + n)
    sym = struct.pack('>IIII', 0, 0, 1, shift + n + 1)
    return structs + [(acc, [0]), (bytearray(array), [0]), (bytearray(sym), [0xC])], shift + n + 2


def test_an_add_on_joins_the_costumes_own_and_shows_on_its_variant_only():
    body = [(bytearray(0x40), [])]                                    # the costume's model root
    existing, sym_index = addon_file(1, shift=1)                      # the costume already carries one add-on
    costume = dat(body + existing, [(0, 'PlyTest5K_Share_joint'), (sym_index, 'mexCostume')])
    new, new_sym = addon_file(2)
    addon = dat([(bytes(4), [])] + [(b, p) for b, p in addon_file(2, shift=1)[0]],
                [(0, 'stub'), (new_sym + 1, 'mexCostume')])

    out, report = weapons.add_to_costume(costume, addon, 3, datroot, Dat)
    assert report == {'meshes': 2, 'addons_before': 1, 'variant': 3}
    assert out[0x20:0x20 + len(costume) - 0x20 - 64][:0x40] == costume[0x20:0x60]      # body bytes untouched
    d = Dat(out)
    assert [n for n, _ in d.roots] == ['PlyTest5K_Share_joint', 'mexCostume']
    sym = dict(d.roots)['mexCostume']
    assert d.u32(sym + 8) == 2
    array = d.ptr(sym + 0xC)
    acc = d.u32(array + 4)
    assert d.u32(acc + 4) == 75 and d.u32(acc + 0x10) == 2            # still on bone 75; two slots
    for which in (0, 4, 8):                                           # high, low and metal lists alike
        slots = d.ptr(d.ptr(acc + 0x14) + which)
        assert d.u32(slots) == 0                                      # slot 0: nothing of the weapon's
        assert d.u32(slots + 8) == 4                                  # slot 1: variants 0..3
        entries = d.ptr(slots + 12)
        assert [d.u32(entries + 8 * k) for k in range(4)] == [0, 0, 0, 2]
        listed = d.ptr(entries + 8 * 3 + 4)
        assert bytes(d.buf[0x20 + listed:0x20 + listed + 2]) == bytes([0, 1])
