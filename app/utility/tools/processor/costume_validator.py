#!/usr/bin/env python3
"""
Slippi costume validator -- pure Python, cross-platform.

Replaces the bundled SlippiCostumeValidator.exe, which was a Windows apphost
around a tiny netcoreapp3.1 assembly. That binary made costume validation
Windows-only: on Linux/macOS every costume came back "unsafe" and auto-fix was
unavailable. There is no source for it, so this is a behaviour-for-behaviour
reimplementation of its decompiled logic, differential-tested against the
original over the costume corpus (see tests/backend/test_costume_validator.py).

What it does
------------
Slippi requires a costume's skeleton to match vanilla exactly, or online play
desyncs. For each `Pl*.dat`/`.usd` costume (excluding `*AJ` animation files) it
walks the DAT root table to every `*_joint` root, looks up the matching vanilla
reference in `CostumeValidator/bin/<symbol>.bin`, then walks the joint tree
depth-first (child, then sibling) and rewrites any bone whose 36-byte transform
block (rotation/scale/translation, 9 big-endian floats) differs from vanilla.

Reference `.bin` layout, one record per bone in the same DFS order:
    int32 LE parent id, int32 LE bone id, 36 raw transform bytes,
    1 flag byte, and 48 more bytes when that flag is 1 (inverse-bind matrix,
    read past but never compared).

Where the references come from
-----------------------------
They are retail game data, so the app does not ship them: `bone_tables.py`
derives them from the user's own ISO and writes them into writable storage
(backend/shared/vanilla_extract/bone_refs.py, first-run setup). `ref_dir()` finds that directory via
`NUCLEUS_BONE_REF_DIR`, or via a provider the backend registers with
`set_ref_dir_provider()` so a legacy install can generate them on first use.
`BUNDLED_REF_DIR` is the last resort and exists only for dev checkouts, which
still carry the tables in-tree.
"""
import os
import re
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLED_REF_DIR = HERE / "CostumeValidator" / "bin"

# Backwards-compatible alias. Prefer ref_dir(); this constant cannot see the
# user-derived directory.
REF_DIR = BUNDLED_REF_DIR

_ref_dir_provider = None


def set_ref_dir_provider(provider):
    """Register a callable returning the user-derived reference directory (or
    None). The backend points this at bone_refs.ensure_bone_refs so the tables
    are generated on first use by installs that predate first-run generation."""
    global _ref_dir_provider
    _ref_dir_provider = provider


def _usable(path):
    try:
        return path is not None and Path(path).is_dir() and any(Path(path).glob("*.bin"))
    except OSError:
        return False


def ref_dir():
    """The directory to read reference tables from.

    Order: an explicit env override, then whatever the backend's provider
    produces (which may generate the tables), then the in-tree bundled copy.
    Resolved per call so a directory that appears mid-session is picked up.
    """
    override = os.environ.get("NUCLEUS_BONE_REF_DIR", "").strip()
    if override and _usable(override):
        return Path(override)
    if _ref_dir_provider is not None:
        try:
            provided = _ref_dir_provider()
        except Exception:
            provided = None
        if _usable(provided):
            return Path(provided)
    return BUNDLED_REF_DIR

# DAT header is 32 bytes; every stored pointer is relative to the end of it.
DAT_HEADER_SIZE = 32
TRANSFORM_BYTES = 36
INVERSE_BIND_BYTES = 48


class JointTreeMismatch(Exception):
    """The costume's joint tree does not have the same shape as vanilla's, so
    it cannot be corrected bone-for-bone."""


def _u32(buf, off):
    """Big-endian uint32 -- the GameCube's byte order, used for everything in
    the DAT itself."""
    return struct.unpack_from(">I", buf, off)[0]


def _u32le(buf, off):
    """Little-endian uint32 -- used only inside the reference .bin files, which
    were written on a PC."""
    return struct.unpack_from("<I", buf, off)[0]


def _pointer(buf, off, file_start):
    """A DAT pointer: 0 and 0xFFFFFFFF both mean null; anything else is an
    offset past the header, relative to where this DAT starts in the stream."""
    raw = _u32(buf, off)
    if raw in (0, 0xFFFFFFFF):
        return 0
    return raw + DAT_HEADER_SIZE + file_start


def _string_at(buf, off):
    end = buf.find(b"\0", off)
    if end < 0:
        end = len(buf)
    return buf[off:end].decode("ascii", "replace")


def is_costume_file(path):
    """Costume DATs only: Pl-prefixed .dat/.usd, excluding the AJ animation
    archives. Mirrors the original's ValidateFile()."""
    p = Path(path)
    stem = p.stem
    return (p.suffix.lower() in (".dat", ".usd")
            and len(stem) > 4
            and stem.startswith("Pl")
            and not stem.endswith("AJ"))


def _iter_roots(buf, file_start=0, file_length=None):
    """Yield (symbol, root_offset) for each root in the DAT's symbol table."""
    if len(buf) - file_start < DAT_HEADER_SIZE:
        return
    if file_length is None:
        file_length = len(buf)
    # A DAT starts with its own total size; if that doesn't match, this isn't
    # one (the original bails the same way rather than guessing).
    if _u32(buf, file_start) != file_length:
        return

    data_end = _pointer(buf, file_start + 4, file_start)
    reloc_count = _u32(buf, file_start + 8)
    root_count = _u32(buf, file_start + 12)

    root_table = data_end + reloc_count * 4
    string_table = root_table + root_count * 8

    for i in range(root_count):
        entry = root_table + i * 8
        if entry + 8 > len(buf):
            return
        root_off = _pointer(buf, entry, file_start)
        name_off = _u32(buf, entry + 4)
        yield _string_at(buf, string_table + name_off), root_off


def _is_skeleton_root(symbol):
    return (symbol.endswith("_joint")
            and "matanim" not in symbol
            and "animjoint" not in symbol)


def _reference_for(symbol):
    """The vanilla reference for a symbol, falling back to the base costume's
    (PlyFox5KGr_Share_joint -> PlyFox5K_Share_joint) exactly as the original
    did, so recolours match their base skeleton."""
    directory = ref_dir()
    exact = directory / f"{symbol}.bin"
    if exact.is_file():
        return exact
    generic = directory / f"{re.sub('5K.._', '5K_', symbol)}.bin"
    if generic.is_file():
        return generic
    return None


def _walk(buf, ref, joint_off, parent, state, file_start, apply_fix):
    """Depth-first over the joint tree (child first, then sibling), consuming
    the reference stream in lockstep. Raises JointTreeMismatch if the shapes
    diverge. Returns True if any transform was rewritten."""
    child = _pointer(buf, joint_off + 8, file_start)
    sibling = _pointer(buf, joint_off + 12, file_start)

    r = state["ref_pos"]
    if _u32le(ref, r) != (parent & 0xFFFFFFFF) or _u32le(ref, r + 4) != state["id"]:
        raise JointTreeMismatch(f"bone id {state['id']} does not match vanilla")
    r += 8

    changed = False
    # joint layout: 8 bytes header, child ptr, sibling ptr, 4 skipped, transform
    transform_off = joint_off + 20
    if buf[transform_off:transform_off + TRANSFORM_BYTES] != ref[r:r + TRANSFORM_BYTES]:
        if apply_fix:
            buf[transform_off:transform_off + TRANSFORM_BYTES] = ref[r:r + TRANSFORM_BYTES]
        changed = True
    r += TRANSFORM_BYTES

    has_inverse_bind = ref[r]
    r += 1
    if has_inverse_bind == 1:
        r += INVERSE_BIND_BYTES
    state["ref_pos"] = r

    my_id = state["id"]
    state["id"] += 1

    if child:
        changed |= _walk(buf, ref, child, my_id, state, file_start, apply_fix)
    if sibling:
        changed |= _walk(buf, ref, sibling, my_id, state, file_start, apply_fix)
    return changed


def check_bytes(buf, apply_fix=True, file_start=0, file_length=None):
    """Validate (and optionally correct) a costume DAT held in a bytearray.

    Returns (changed, notes). `changed` is True when at least one bone's
    transform differed from vanilla -- i.e. the costume was NOT Slippi-safe.
    """
    notes = []
    changed = False
    for symbol, root_off in _iter_roots(buf, file_start, file_length):
        if not _is_skeleton_root(symbol):
            continue
        ref_path = _reference_for(symbol)
        if ref_path is None:
            notes.append(f"Could not match symbol {symbol}")
            continue
        ref = ref_path.read_bytes()
        # TWO passes, like the original: prove the whole tree lines up with
        # vanilla BEFORE writing anything. A single validate-and-fix pass
        # corrupts files whose tree diverges partway through -- it rewrites the
        # bones it already walked, then discovers the mismatch too late.
        try:
            _walk(buf, ref, root_off, -1, {"ref_pos": 0, "id": 0},
                  file_start, apply_fix=False)
        except (JointTreeMismatch, IndexError, struct.error) as e:
            notes.append(f"Skeleton could not be corrected for {symbol}: {e}")
            continue
        if _walk(buf, ref, root_off, -1, {"ref_pos": 0, "id": 0},
                 file_start, apply_fix):
            changed = True
            notes.append(f"Corrected {symbol}")
        else:
            notes.append(f"{symbol} already correct")
    return changed, notes


def check_file(path, apply_fix=True):
    """Validate a costume DAT on disk. Writes it back only when a fix is both
    needed and requested. Returns (changed, notes)."""
    path = Path(path)
    if not is_costume_file(path):
        return False, [f"{path.name} is not a costume DAT -- skipped"]
    buf = bytearray(path.read_bytes())
    changed, notes = check_bytes(buf, apply_fix=apply_fix)
    if changed and apply_fix:
        path.write_bytes(buf)
    return changed, notes


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    paths = sorted(target.iterdir()) if target.is_dir() else [target]
    for p in paths:
        if p.is_file() and is_costume_file(p):
            was_changed, msgs = check_file(p, apply_fix="--check-only" not in sys.argv)
            print(f"{p.name}: {'FIXED' if was_changed else 'ok'}")
            for m in msgs:
                print(f"  {m}")
