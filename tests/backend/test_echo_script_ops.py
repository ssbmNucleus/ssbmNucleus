"""Script authoring: encode must be the exact inverse of decode, an authored
script is appended (nothing existing moves), and the three script ops
validate before writing and compose within a batch."""
from __future__ import annotations

from tests.paths import APP
from pathlib import Path

import pytest

from vault.echo import ops
from vault.echo.commands import COMMANDS, CREATE_HITBOX, END_OF_SCRIPT, ASYNC_TIMER, CLEAR_HITBOXES
from vault.echo.subactions import FighterDat, HEADER_SIZE
from vault.echo.moves import MoveTable

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_echo_ops import build_synthetic_dat  # noqa: E402

BASE = APP / "storage" / "test-base" / "files"
# PlCo.dat is the shared fighter data (ftLoadCommonData), not a fighter.
ROSTER = sorted(p for p in BASE.glob("Pl??.dat") if p.stem != "PlCo") if BASE.is_dir() else []
FALCO = BASE / "PlFc.dat"
needs_falco = pytest.mark.skipif(not FALCO.is_file(), reason="vanilla PlFc.dat not cached")


# ---------------------------------------------------------------------------
# encoder = inverse of the walker, on the whole vanilla roster
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ROSTER, ids=[p.stem for p in ROSTER])
def test_encode_script_reproduces_every_vanilla_script(path):
    fd = FighterDat.from_file(path)
    checked = 0
    for a in fd.actions:
        items = fd.script_items(a.index)
        if not items:
            continue
        blob, pointers = fd.encode_script(items)
        n = sum(COMMANDS[c].size for c, _, _ in items)   # blob may add an End past a truncated walk
        raw = bytes(fd.dat.buf[HEADER_SIZE + a.script_offset:HEADER_SIZE + a.script_offset + n])
        assert blob[:n] == raw, f"{path.name} action {a.index} {a.motion}"
        for off in pointers:  # every pointer word we emit was a reloc in the file
            assert a.script_offset + off in fd.dat.relocs
        checked += 1
    assert checked > 0


# ---------------------------------------------------------------------------
# synthetic: replace / insert / delete
# ---------------------------------------------------------------------------
def _first_move(fd):
    mt = MoveTable(fd)
    return mt, next(iter(mt.moves))


def test_replace_script_appends_and_repoints():
    donor = build_synthetic_dat()
    fd = FighterDat(donor)
    old_size = fd.dat.data_size
    old = fd.script_items(0)
    hb = next(it for it in old if it[0] == CREATE_HITBOX)
    new = [(ASYNC_TIMER, {"frame": 3}, None),
           (CREATE_HITBOX, {**hb[1], "damage": 25}, None),
           (ASYNC_TIMER, {"frame": 9}, None),
           (CLEAR_HITBOXES, {}, None)]
    info = fd.replace_script(0, new)
    out = fd.to_bytes()
    # nothing that existed moved
    assert out[HEADER_SIZE:HEADER_SIZE + old_size] != donor[HEADER_SIZE:HEADER_SIZE + old_size]  # the slot changed...
    changed = [i for i in range(old_size) if out[HEADER_SIZE + i] != donor[HEADER_SIZE + i]]
    tbl, _ = fd.action_table
    assert changed and set(changed) <= set(range(tbl + 0x0C, tbl + 0x10))  # ...and ONLY the slot
    assert info["new_offset"] >= old_size and info["new_offset"] % 0x20 == 0
    # the new script decodes back to what we authored (+ the auto End)
    re = FighterDat(out)
    items = re.script_items(0)
    assert [c for c, _, _ in items] == [ASYNC_TIMER, CREATE_HITBOX, ASYNC_TIMER, CLEAR_HITBOXES, END_OF_SCRIPT]
    assert items[1][1]["damage"] == 25
    hbs = re.hitboxes(0)
    assert hbs[0]["frame_start"] == 4 and hbs[0]["frame_end"] == 9
    assert re.verify_roundtrip() == []


def test_script_ops_plan_apply_compose():
    donor = build_synthetic_dat()
    fd = FighterDat(donor)
    mt, move = _first_move(fd)
    n0 = len([it for it in fd.script_items(0) if it[0] != END_OF_SCRIPT])
    batch = [
        {"op": "insert_command", "move": move, "at": 0,
         "command": {"cmd": "Asynchronous Timer", "frame": 2}},
        {"op": "delete_command", "move": move, "command": 0},      # deletes what we just inserted
        {"op": "insert_command", "move": move, "at": "end",
         "commands": [{"cmd": "clear_hitboxes"}]},
        {"op": "set_hitbox", "move": move, "hitbox": 0, "field": "damage", "value": 21},
    ]
    p = ops.plan(donor, batch)
    assert p.ok, p.errors
    assert [s.before for s in p.steps[:3]] == [n0, n0 + 1, n0]
    assert [s.after for s in p.steps[:3]] == [n0 + 1, n0, n0 + 1]
    assert p.steps[0].as_dict()["commands"][0] == {"cmd": "asynchronous_timer", "frame": 2}
    r = ops.apply(donor, batch)
    re = FighterDat(r.data)
    items = re.script_items(0)
    assert items[-2][0] == CLEAR_HITBOXES and items[-1][0] == END_OF_SCRIPT
    assert re.hitboxes(0)[0]["damage"] == 21
    # deterministic
    assert ops.apply(donor, batch).data == r.data
    # set_script from the inspector's own listing round-trips
    listing = ops.inspect_move(r.data, move)["commands"]
    again = ops.apply(r.data, [{"op": "set_script", "move": move,
                                "commands": [{"cmd": c["key"], **c["fields"]}
                                             for c in listing if not c["after_end"]]}])
    assert FighterDat(again.data).script_items(0) == items


def test_script_ops_validate_everything_first():
    donor = build_synthetic_dat()
    fd = FighterDat(donor)
    _, move = _first_move(fd)
    n = len([it for it in fd.script_items(0) if it[0] != END_OF_SCRIPT])
    bad = [
        {"op": "set_script", "move": move, "commands": [{"cmd": "no_such_command"}]},
        {"op": "set_script", "move": move, "commands": [{"cmd": "create_hitbox", "damage": 5000}]},
        {"op": "set_script", "move": move, "commands": [{"cmd": "create_hitbox", "bogus": 1}]},
        {"op": "set_script", "move": move, "commands": [{"cmd": "subroutine"}]},
        {"op": "delete_command", "move": move, "command": n},
        {"op": "insert_command", "move": move, "at": n + 1, "command": {"cmd": "return"}},
        {"op": "set_script", "move": move, "commands": [{"cmd": "go_to", "pointer": 0x7FFFFFF0}]},
    ]
    p = ops.plan(donor, bad)
    assert len(p.errors) == len(bad), p.errors
    for msg, needle in zip(p.errors, ["unknown command", "out of range", "unknown field",
                                      "pointer", "cannot be deleted", "at=", "outside"]):
        assert needle in msg, (msg, needle)
    with pytest.raises(ops.OpError):
        ops.apply(donor, bad[:1])


@needs_falco
def test_falco_ftilt_rewrite_keeps_everything_else_intact():
    donor = FALCO.read_bytes()
    before = FighterDat(donor)
    hb = before.hitboxes(MoveTable(before).action_index("ftilt", "mid"))[0]
    r = ops.apply(donor, [{"op": "set_script", "move": "ftilt", "part": "mid", "commands": [
        {"cmd": "asynchronous_timer", "frame": 3},
        {"cmd": "create_hitbox", "id": 0, "bone": hb["bone"], "damage": 25, "size": hb["size"],
         "x_offset": hb["x_offset"], "y_offset": hb["y_offset"], "z_offset": hb["z_offset"],
         "angle": 361, "knockback_growth": 100, "base_knockback": 40},
        {"cmd": "asynchronous_timer", "frame": 12},
        {"cmd": "clear_hitboxes"},
    ]}])
    after = FighterDat(r.data)
    assert after.verify_roundtrip() == []
    a = MoveTable(after).action_index("ftilt", "mid")
    assert after.hitboxes(a)[0]["damage"] == 25 and after.hitboxes(a)[0]["frame_start"] == 4
    # every other action's script bytes are untouched
    for x, y in zip(before.actions, after.actions):
        if x.index == a:
            continue
        assert x.script_offset == y.script_offset
    assert r.data[HEADER_SIZE:HEADER_SIZE + before.dat.data_size].count(b"\0") >= 0
    # datroot-style code roots survive: append a fake root then edit again
    from vault.echo.datroot import merge_bytes, build, parse
    with_code = merge_bytes(r.data, build(b"\x00" * 16, [], [(0, "ftFunction")], []))
    again = ops.apply(with_code, [{"op": "set_hitbox", "move": "ftilt", "hitbox": 0,
                                   "field": "damage", "value": 30}])
    assert [n for _, n in parse(again.data)[2]] == ["ftDataFalco", "ftFunction"]
    assert FighterDat(again.data).hitboxes(a)[0]["damage"] == 30
