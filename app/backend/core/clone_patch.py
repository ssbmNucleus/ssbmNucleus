"""Item-only cut of m-ex's `clone_engine` function patch, for clone fighters.

A clone that reuses a vanilla fighter's special-move code spawns that fighter's
vanilla item kinds: ACE's Metal Mario runs `ftMr_SpecialS_CreateCape`, which
creates item kind "Mario cape". Unless Mario himself is in the match that kind
was never registered, and m-ex stops with "error: item not initialized" (the
game freezes on side-B frame 1). m-ex's `clone_engine` patch (MxPt.dat) remaps
those spawns to the clone's own item slots, which is why the ACE Build ships it.

The full patch also routes every fighter's effect spawns through the spawning
fighter's own effect bank, which breaks Kirby's copied specials for the whole
build (see vault/climbers/engine_code.py). Its hooks are independent entries in the
patch's function table, and the first four are the item/article ones:

    Item_80267AA8+0x48            item create -> clone's own item slot
    ftMr_SpecialN_ItemFireSpawn   Mario's fireball kind check
    ftFx_SpecialS_Anim / AirS     Fox illusion

Keeping only those (count 13 -> 4) fixed Metal Mario's cape and fireball on a
vanilla-based build and left Kirby's copied Falcon Punch correct (verified in
game 2026-09-21). The root is renamed so this copy never collides with, or is
stripped as, a full `clone_engine` another package brings.
"""
from __future__ import annotations

import struct

from core.config import BACKEND_DATA_DIR

CLONE_ENGINE_DAT = BACKEND_DATA_DIR / "clone_engine.dat"
SOURCE_ROOT = "clone_engine"
ITEMS_ROOT = "clone_engine_items"
PATCH_ENTRY = "patches/clone_engine_items.dat"

# Function-table entries to keep, in order (0x40 prefix = "replace the bl here").
KEEP_HOOKS = (0x40267AF0, 0x800E0F58, 0x400EA30C, 0x400EA3BC)

_HEADER = 0x20
_FUNC_TABLE = 0x0C      # HSDFunctionDat: function table pointer
_FUNC_COUNT = 0x10      # HSDFunctionDat: function table count

# Vanilla DOL .text: a function pointer in here is the donor's own code.
_DOL_TEXT = (0x80003100, 0x803B7240)
_SPECIALS = ("specialN", "specialNAir", "specialS", "specialSAir",
             "specialHi", "specialHiAir", "specialLw", "specialLwAir")


def _roots(data: bytes):
    file_size, data_size, reloc_count, root_count, ref_count = struct.unpack(">5I", data[:0x14])
    if file_size != len(data):
        raise ValueError(f"HSD size field {file_size} != {len(data)} bytes")
    roots_at = _HEADER + data_size + reloc_count * 4
    strings_at = roots_at + (root_count + ref_count) * 8
    out = []
    for i in range(root_count):
        off, str_off = struct.unpack(">II", data[roots_at + i * 8: roots_at + i * 8 + 8])
        end = data.index(b"\x00", strings_at + str_off)
        out.append((off, data[strings_at + str_off:end].decode("ascii", "replace")))
    return data_size, reloc_count, root_count, ref_count, roots_at, out


def items_patch_bytes(source: bytes | None = None) -> bytes:
    """The item-only patch, derived from the bundled clone_engine.dat. Raises
    ValueError if the source isn't the layout this was verified against."""
    data = source if source is not None else CLONE_ENGINE_DAT.read_bytes()
    data_size, reloc_count, root_count, ref_count, roots_at, roots = _roots(data)
    if root_count != 1 or ref_count != 0 or roots[0][1] != SOURCE_ROOT:
        raise ValueError(f"unexpected clone_engine roots: {roots}")
    root = roots[0][0]
    body = bytearray(data[_HEADER:_HEADER + data_size])
    table, count = struct.unpack(">II", body[root + _FUNC_TABLE: root + _FUNC_COUNT + 4])
    hooks = [struct.unpack(">I", body[table + i * 8: table + i * 8 + 4])[0] for i in range(count)]
    if tuple(hooks[:len(KEEP_HOOKS)]) != KEEP_HOOKS:
        raise ValueError(f"clone_engine hook table changed: {[hex(h) for h in hooks]}")
    struct.pack_into(">I", body, root + _FUNC_COUNT, len(KEEP_HOOKS))

    relocs = data[_HEADER + data_size: roots_at]
    strings = ITEMS_ROOT.encode("ascii") + b"\x00"
    tail = struct.pack(">II", root, 0) + strings
    out = bytearray(struct.pack(">5I", 0, data_size, reloc_count, 1, 0))
    out += bytes(_HEADER - 0x14)
    out += body + relocs + tail
    struct.pack_into(">I", out, 0, len(out))
    return bytes(out)


def fighter_needs_items_patch(fighter: dict) -> bool:
    """A clone whose specials run a vanilla fighter's code and that owns item
    slots of its own -- the shape whose article spawns need remapping."""
    functions = fighter.get("functions") if isinstance(fighter.get("functions"), dict) else {}
    runs_donor_code = any(
        isinstance(functions.get(k), int) and _DOL_TEXT[0] <= functions[k] < _DOL_TEXT[1]
        for k in _SPECIALS)
    return runs_donor_code and bool(fighter.get("items"))
