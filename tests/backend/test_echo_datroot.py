"""vault.echo.datroot.merge keeps the target DAT byte-exact and relocates the appended root."""
import os
import struct
import sys

from tests.paths import BACKEND
sys.path.insert(0, str(BACKEND))
from vault.echo.datroot import build, merge, merge_bytes, parse  # noqa: E402


def _dat(data, relocs, roots):
    return build(data, relocs, roots, [])


def test_merge_preserves_target_and_shifts_source(tmp_path):
    # target: 40 bytes of data, one pointer at 0 -> 8, root 'ftDataX' at 8
    tdata = bytearray(40)
    struct.pack_into('>I', tdata, 0, 8)
    t = _dat(bytes(tdata), [0], [(8, 'ftDataX')])
    # source: 16 bytes, pointer at 4 -> 12, root 'ftFunction' at 0
    sdata = bytearray(16)
    struct.pack_into('>I', sdata, 4, 12)
    s = _dat(bytes(sdata), [4], [(0, 'ftFunction')])
    tp, sp, op = tmp_path / 't.dat', tmp_path / 's.dat', tmp_path / 'o.dat'
    tp.write_bytes(t)
    sp.write_bytes(s)
    merge(str(tp), str(sp), str(op))
    out = op.read_bytes()
    od, orl, oroots, ox = parse(out)
    base = 64  # 40 rounded up to 0x20
    assert od[:40] == bytes(tdata)  # target data untouched
    assert orl[0] == 0  # target reloc untouched
    assert orl[1] == base + 4  # source reloc shifted
    assert struct.unpack('>I', od[base + 4:base + 8])[0] == base + 12  # pointer value shifted
    assert oroots == [(8, 'ftDataX'), (base, 'ftFunction')]
    assert ox == []
    assert len(out) % 0x20 == 0


def test_merge_is_idempotent_on_content():
    data = bytes(range(64))
    d = _dat(data, [0, 8], [(0, 'a'), (32, 'b')])
    assert parse(d)[0] == data and parse(d)[1] == [0, 8]
    twice = merge_bytes(merge_bytes(d, d), d)
    assert [n for _, n in parse(twice)[2]] == ['a', 'b'] * 3
