#!/usr/bin/env python3
"""
Derive the Slippi bone-reference tables from vanilla costume DATs.

`costume_validator.py` compares a costume's skeleton against a per-symbol
reference table (`<symbol>.bin`) and rewrites any bone whose transform drifted
from vanilla. Those tables used to ship with the app -- 159 files lifted out of
retail `Pl*.dat`, i.e. Nintendo game data in the installer (see
docs/dev/VANILLA_ASSET_POLICY.md). This module is the other half: it *writes* the
same tables from the user's own copy of the game, so nothing has to be bundled.

It is the exact inverse of `costume_validator._walk`. Same depth-first order
(child, then sibling), same record layout:

    int32 LE parent id, int32 LE bone id, 36 raw transform bytes,
    1 flag byte, and -- when that flag is 1 -- the 48-byte inverse-bind matrix.

Output is byte-identical to the tables the old C# tool produced: generating
from a retail 1.02 disc reproduces all 159 shipped `.bin` files exactly, which
is what `tests/backend/test_bone_tables.py` asserts.

Standalone use (dev):

    python bone_tables.py <dir-of-vanilla-Pl-dats> <out-dir>
"""
import struct
from pathlib import Path

import costume_validator as cv

# HSD_JObj field offsets. costume_validator reads the first two; the inverse
# bind matrix pointer is only needed on the write side.
JOBJ_CHILD = 8
JOBJ_NEXT = 12
JOBJ_TRANSFORM = 20            # 9 big-endian floats: rotation, scale, translation
JOBJ_INVERSE_BIND = 56         # HSD_Matrix* -- 48 bytes when present

TRANSFORM_BYTES = cv.TRANSFORM_BYTES
INVERSE_BIND_BYTES = cv.INVERSE_BIND_BYTES

# A retail skeleton is a few hundred bones; anything past this means the walk
# followed garbage pointers, so bail instead of recursing forever.
MAX_BONES = 4096


class BoneTableError(Exception):
    """The joint tree could not be walked -- not a skeleton, or corrupt."""


def _emit(buf, joint_off, parent_id, state, out, file_start):
    if state["id"] >= MAX_BONES:
        raise BoneTableError("bone count exceeds the sane limit")
    if joint_off in state["seen"]:
        raise BoneTableError("joint tree contains a cycle")
    state["seen"].add(joint_off)

    child = cv._pointer(buf, joint_off + JOBJ_CHILD, file_start)
    sibling = cv._pointer(buf, joint_off + JOBJ_NEXT, file_start)

    out += struct.pack("<ii", parent_id, state["id"])

    transform = buf[joint_off + JOBJ_TRANSFORM:
                    joint_off + JOBJ_TRANSFORM + TRANSFORM_BYTES]
    if len(transform) != TRANSFORM_BYTES:
        raise BoneTableError("transform block runs past the end of the file")
    out += transform

    inverse_bind = cv._pointer(buf, joint_off + JOBJ_INVERSE_BIND, file_start)
    if inverse_bind:
        matrix = buf[inverse_bind:inverse_bind + INVERSE_BIND_BYTES]
        if len(matrix) != INVERSE_BIND_BYTES:
            raise BoneTableError("inverse bind matrix runs past the end of the file")
        out += b"\x01" + matrix
    else:
        out += b"\x00"

    my_id = state["id"]
    state["id"] += 1
    if child:
        _emit(buf, child, my_id, state, out, file_start)
    if sibling:
        _emit(buf, sibling, my_id, state, out, file_start)
    return out


def table_for_root(buf, root_off, file_start=0):
    """The reference table for one skeleton root. Raises BoneTableError."""
    try:
        return bytes(_emit(buf, root_off, -1, {"id": 0, "seen": set()},
                           bytearray(), file_start))
    except (IndexError, struct.error) as e:
        raise BoneTableError(str(e)) from e


def tables_from_bytes(buf):
    """{symbol: table} for every skeleton root in one costume DAT's bytes.

    Roots that cannot be walked are skipped rather than failing the file: a
    single odd root must not cost the rest of the disc its references.
    """
    tables = {}
    for symbol, root_off in cv._iter_roots(buf):
        if not cv._is_skeleton_root(symbol):
            continue
        try:
            tables[symbol] = table_for_root(buf, root_off)
        except BoneTableError:
            continue
    return tables


def write_tables(tables, out_dir):
    """Write {symbol: table} as <out_dir>/<symbol>.bin. Returns the count.

    Each file is written to a temp name and renamed, so a reader that races the
    generation sees either the old table or the new one, never a partial file.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for symbol, data in tables.items():
        # Symbols come from a DAT string table; refuse anything that could
        # escape out_dir rather than trusting the file.
        if "/" in symbol or "\\" in symbol or symbol in ("", ".", ".."):
            continue
        destination = out_dir / f"{symbol}.bin"
        temporary = destination.with_name(destination.name + ".tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return len(tables)


def tables_from_dir(files_dir):
    """{symbol: table} for every vanilla costume DAT in a directory.

    `files_dir` is expected to hold vanilla game files only (a `mexcli create`
    extraction, or the user-derived CSP reference bank). A modded costume in
    there would poison its own symbol's reference, so callers that cannot
    guarantee the contents should filter first.
    """
    tables = {}
    for path in sorted(Path(files_dir).iterdir()):
        if not path.is_file() or not cv.is_costume_file(path):
            continue
        try:
            buf = path.read_bytes()
        except OSError:
            continue
        for symbol, data in tables_from_bytes(buf).items():
            tables.setdefault(symbol, data)
    return tables


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    generated = tables_from_dir(sys.argv[1])
    write_tables(generated, sys.argv[2])
    print(f"wrote {len(generated)} bone reference tables to {sys.argv[2]}")
