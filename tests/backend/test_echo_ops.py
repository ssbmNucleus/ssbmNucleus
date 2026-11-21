"""
Echo op surface: the subaction codec must be byte-exact, in-place edits must
move nothing, and the op layer must validate before writing.

Vanilla-DAT tests use the cached reference files under storage/test-base
(pulled from the recorded vanilla ISO by vanilla_refs.ensure_vanilla_ref) and
skip when they are absent, so CI without an ISO still runs the synthetic
tests below.
"""
from __future__ import annotations

from tests.paths import APP
import struct
from pathlib import Path

import pytest

from vault.echo import ops
from vault.echo.commands import COMMANDS, CREATE_HITBOX, BY_KEY
from vault.echo.subactions import (FighterDat, HEADER_SIZE, read_bits, write_bits,
                             motion_from_symbol, fighter_name_from_symbol)
from vault.echo.moves import MoveTable, classify
from vault.echo.attributes import Attributes, ATTRIBUTES, SIZE as ATTR_SIZE

BASE = APP / "storage" / "test-base" / "files"
FALCO = BASE / "PlFc.dat"
# PlCo.dat is the shared fighter data (ftLoadCommonData), not a fighter.
ROSTER = sorted(p for p in BASE.glob("Pl??.dat") if p.stem != "PlCo") if BASE.is_dir() else []

needs_falco = pytest.mark.skipif(not FALCO.is_file(), reason="vanilla PlFc.dat not cached")


# ---------------------------------------------------------------------------
# spec sanity
# ---------------------------------------------------------------------------
def test_command_table_is_contiguous_and_byte_aligned():
    assert sorted(COMMANDS) == list(range(len(COMMANDS)))
    for c in COMMANDS.values():
        assert c.bits % 8 == 0 and c.size >= 4
    hb = COMMANDS[CREATE_HITBOX]
    assert hb.size == 20
    assert hb.param("damage").bits == 10 and hb.param("bone").bits == 8
    assert hb.param("element").bit_offset == 6 + 3 + 3 + 1 + 8 + 1 + 10 + 16 * 4 + 9 * 3 + 5 + 9
    assert BY_KEY["throw"].size == 12


def test_bit_helpers_roundtrip():
    buf = bytearray(8)
    write_bits(buf, 3, 10, 0x2AB)
    assert read_bits(buf, 3, 10) == 0x2AB
    write_bits(buf, 3, 10, 0)
    assert bytes(buf) == bytes(8)
    write_bits(buf, 20, 9, 0x1FF)
    assert read_bits(buf, 20, 9) == 0x1FF and read_bits(buf, 19, 1) == 0 and read_bits(buf, 29, 1) == 0


def test_symbol_parsing():
    s = "PlyFalco5K_Share_ACTION_AttackS3S_figatree"
    assert motion_from_symbol(s) == "AttackS3S"
    assert fighter_name_from_symbol(s) == "Falco"
    assert motion_from_symbol(None) is None
    assert classify("AttackS3S", 0) == ("ftilt", "mid")
    assert classify("SpecialAirNStart", 0) == ("airneutralb", "start")
    assert classify("SpecialLwHit", 0) == ("downb", "hit")
    assert classify(None, 7) == ("action7", None)


# ---------------------------------------------------------------------------
# synthetic DAT: one action, one script, an attributes block
# ---------------------------------------------------------------------------
def _hitbox(**over) -> bytes:
    spec = COMMANDS[CREATE_HITBOX]
    fields = {p.key: 0 for p in spec.params}
    fields.update(damage=9, size=700, angle=361, knockback_growth=100, bone=13,
                  hit_grounded_fighters=1, hit_aerial_fighters=1, clank=1, rebound=1)
    fields.update(over)
    out = bytearray(spec.size)
    write_bits(out, 0, 6, CREATE_HITBOX)
    for p in spec.params:
        write_bits(out, p.bit_offset, p.bits, fields[p.key])
    return bytes(out)


def _cmd(code: int, **fields) -> bytes:
    spec = COMMANDS[code]
    out = bytearray(spec.size)
    write_bits(out, 0, 6, code)
    for p in spec.params:
        write_bits(out, p.bit_offset, p.bits, fields.get(p.key, 0))
    return bytes(out)


def build_synthetic_dat() -> bytes:
    """Layout (data-section offsets):
      0x000 attributes (0x184)          0x184 script
      script_end  symbol string         then action table (1 x 0x18)
      then ftData root (0x60)
    """
    attrs = bytearray(ATTR_SIZE)
    struct.pack_into(">f", attrs, 0x088, 80.0)       # weight
    struct.pack_into(">f", attrs, 0x05C, 0.17)       # gravity
    struct.pack_into(">i", attrs, 0x058, 2)          # jumps
    script = (_cmd(0x02, frame=5) + _hitbox() + _hitbox(id=1, size=800)
              + _cmd(0x01, frame=5) + _cmd(0x10) + _cmd(0x17) + _cmd(0x00))
    sym = b"PlyTest5K_Share_ACTION_AttackS3S_figatree\0"
    sym += b"\0" * (-len(sym) % 4)

    data = bytearray()
    off_attrs = 0
    data += attrs
    off_script = len(data)
    data += script
    off_sym = len(data)
    data += sym
    off_table = len(data)
    table = bytearray(0x18)
    struct.pack_into(">I", table, 0x00, off_sym)
    struct.pack_into(">I", table, 0x0C, off_script)
    data += table
    off_root = len(data)
    root = bytearray(0x60)
    struct.pack_into(">I", root, 0x00, off_attrs)
    struct.pack_into(">I", root, 0x0C, off_table)
    data += root

    relocs = [off_table + 0x00, off_table + 0x0C, off_root + 0x00, off_root + 0x0C]
    root_name = b"ftDataTest\0"
    file = bytearray(HEADER_SIZE)
    file += data
    for r in relocs:
        file += struct.pack(">I", r)
    file += struct.pack(">II", off_root, 0)
    file += root_name
    struct.pack_into(">IIIII", file, 0, len(file), len(data), len(relocs), 1, 0)
    return bytes(file)


def test_throw_mask_uses_first_byte_and_preserves_padding():
    fd = FighterDat(build_synthetic_dat())
    attrs = Attributes(fd)
    fd.dat.set_u32(attrs.base + 0x180, 0x02AABBCC)
    assert attrs.get('weight_dependent_throw_flags') == 2
    attrs.set('weight_dependent_throw_flags', 15)
    assert fd.dat.u32(attrs.base + 0x180) == 0x0FAABBCC
    before = fd.to_bytes()
    with pytest.raises(ValueError):
        attrs.set('weight_dependent_throw_flags', 256)
    assert fd.to_bytes() == before


def test_synthetic_decode_and_edit():
    dat = build_synthetic_dat()
    fd = FighterDat(dat)
    assert fd.fighter_name == "Test"
    assert len(fd.actions) == 1 and fd.actions[0].motion == "AttackS3S"
    s = fd.script(0)
    assert [c.key for c in s.commands] == ["asynchronous_timer", "create_hitbox", "create_hitbox",
                                           "synchronous_timer", "clear_hitboxes", "allow_interrupt",
                                           "end_of_script"]
    assert fd.verify_roundtrip() == []
    hbs = fd.hitboxes(0)
    assert [(h["frame_start"], h["frame_end"], h["damage"]) for h in hbs] == [(6.0, 10.0, 9), (6.0, 10.0, 9)]

    r = fd.set_field(0, 1, "damage", 14)
    assert r["before"] == 9 and fd.get_field(0, 1, "damage") == 14
    assert len(fd.to_bytes()) == len(dat)
    # only the hitbox's bytes changed
    changed = [i for i, (x, y) in enumerate(zip(dat, fd.to_bytes())) if x != y]
    off = HEADER_SIZE + s.commands[1].offset
    assert changed and all(off <= i < off + 20 for i in changed)

    with pytest.raises(ValueError):
        fd.set_field(0, 1, "damage", 1024)
    with pytest.raises(ValueError):
        fd.set_field(0, 1, "z_offset", 40000)
    fd.set_field(0, 1, "z_offset", -300)
    assert fd.get_field(0, 1, "z_offset") == -300


def test_synthetic_ops_plan_apply_diff():
    dat = build_synthetic_dat()
    desc = ops.describe(dat)
    assert desc["fighter"] == "Test"
    assert [m["id"] for m in desc["moves"]] == ["ftilt"]
    assert desc["moves"][0]["parts"][0]["hitboxes"] == 2

    OPS = [{"op": "set_hitbox", "move": "forward tilt", "hitbox": "all", "field": "dmg", "value": 14},
           {"op": "set_hitbox", "move": "ftilt", "hitbox": 1, "field": "kbg", "delta": 20},
           {"op": "set_attribute", "name": "gravity", "value": 0.13},
           {"op": "set_attribute", "name": "jumps", "value": 3}]
    pl = ops.plan(dat, OPS)
    assert pl.ok, pl.errors
    assert [(s.key, s.before, s.after) for s in pl.steps] == [
        ("damage", 9, 14), ("damage", 9, 14), ("knockback_growth", 100, 120),
        ("gravity", pytest.approx(0.17), 0.13), ("number_of_jumps", 2, 3)]

    r = ops.apply(dat, OPS)
    assert r.changed == 5 and len(r.data) == len(dat)
    back = ops.diff(dat, r.data)
    assert {"op": "set_hitbox", "hitbox": 0, "move": "ftilt", "part": "mid", "field": "damage", "value": 14} in back
    assert {"op": "set_attribute", "name": "number_of_jumps", "value": 3} in back
    assert ops.apply(dat, back).data == r.data          # diff is a faithful re-creation

    im = ops.inspect_move(r.data, "ftilt", donor_ref=dat)
    assert im["hitboxes"][1]["donor"]["knockback_growth"] == 100
    assert im["hitboxes"][1]["knockback_growth"] == 120
    assert im["hitboxes"][0]["size_units"] == pytest.approx(700 / 256, rel=1e-3)


def test_ops_validation_is_all_or_nothing():
    dat = build_synthetic_dat()
    bad = [{"op": "set_hitbox", "move": "ftilt", "hitbox": 0, "field": "damage", "value": 14},
           {"op": "set_hitbox", "move": "ftilt", "hitbox": 5, "field": "damage", "value": 1},
           {"op": "set_hitbox", "move": "usmash", "hitbox": 0, "field": "damage", "value": 1},
           {"op": "set_hitbox", "move": "ftilt", "hitbox": 0, "field": "damage", "value": 5000},
           {"op": "nope"}]
    pl = ops.plan(dat, bad)
    assert not pl.ok and len(pl.errors) == 4
    with pytest.raises(ops.OpError):
        ops.apply(dat, bad)
    # nothing written: a fresh apply of only the good op differs from donor,
    # but the failed apply raised before producing anything
    assert ops.apply(dat, bad[:1]).changed == 1


# ---------------------------------------------------------------------------
# vanilla
# ---------------------------------------------------------------------------
@needs_falco
def test_falco_ftilt_matches_known_frame_data():
    fd = FighterDat.from_file(FALCO)
    assert fd.fighter_name == "Falco" and len(fd.actions) == 327
    mt = MoveTable(fd)
    idx = mt.action_index("ftilt")
    assert fd.actions[idx].motion == "AttackS3S"
    hbs = fd.hitboxes(idx)
    assert len(hbs) == 3
    assert all(h["damage"] == 9 and h["angle"] == 361 for h in hbs)   # Sakurai angle
    assert all(h["frame_start"] == 6.0 and h["frame_end"] == 10.0 for h in hbs)
    at = Attributes(fd)
    assert at.get("weight") == 80.0 and at.get("number_of_jumps") == 2


@pytest.mark.skipif(not ROSTER, reason="vanilla fighter DATs not cached")
@pytest.mark.parametrize("path", ROSTER, ids=[p.stem for p in ROSTER])
def test_vanilla_roster_roundtrips_byte_exact(path):
    fd = FighterDat.from_file(path)
    assert fd.verify_roundtrip() == []
    orig = fd.to_bytes()
    for a in fd.actions:
        s = fd.script(a.index)
        if not s:
            continue
        for c in s.commands:
            for p in c.spec.params:
                if not p.is_padding:
                    fd.set_field(a.index, c.index, p.key, c.fields[p.key])
    assert fd.to_bytes() == orig
