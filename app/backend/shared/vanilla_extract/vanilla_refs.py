"""
vanilla_refs.py -- vanilla reference DATs for the extras system on USER installs.

The extras write-safety machinery (vault/extras/texture_recolor.py,
relocate.py, helpers.make_write_safety) reads pristine vanilla DATs from
STORAGE_PATH/test-base/files/. On the dev machine that folder is a full
extracted vanilla project, but nothing in the shipped app ever created it --
so every texture_recolor extra hard-failed for end users ("no vanilla
reference for EfMrData.dat") and the relocation / context-guard second chance
silently degraded into the "N layer(s) could not be safely written and kept
their previous colors" notice when installing over a previous extra.

This module closes the gap without shipping game files:

  * record_vanilla_iso(path) -- remember the user's validated vanilla ISO.
    Called from /setup/health (every app boot posts the viewer's saved ISO
    path) and on setup start, and persisted to STORAGE_PATH/vanilla_iso.json,
    so existing installs self-heal on their first boot after updating.
  * ensure_vanilla_ref(target_file) -- return the reference DAT's path,
    extracting the single file straight out of the recorded vanilla ISO into
    test-base/files/ the first time it is needed.

GameCube discs are unencrypted: header words 0x424/0x428 hold the FST
offset/size; the FST is 12-byte entries (flags+name-offset, file-offset,
length) followed by a string table -- so extracting one file is two seeks and
one bounded read, cheap enough to do lazily at extras-install time.
"""

import json
import logging
import struct
import threading
from pathlib import Path

import file_retry
from core.config import STORAGE_PATH

logger = logging.getLogger(__name__)

# Where the validated vanilla ISO path is remembered across restarts.
ISO_RECORD_PATH = STORAGE_PATH / "vanilla_iso.json"

_MELEE_GAME_ID = b"GALE01"

# A GC FST is tiny (Melee's is ~50 KB); anything huge means we misread the
# header of a non-disc file -- refuse rather than allocate.
_FST_SIZE_LIMIT = 16 * 1024 * 1024

_extract_lock = threading.Lock()


def _refs_dir(storage_path=None) -> Path:
    return Path(storage_path or STORAGE_PATH) / "test-base" / "files"


def record_vanilla_iso(iso_path) -> None:
    """Persist `iso_path` as the known vanilla ISO if it looks like a GC Melee
    disc (6-byte game-id check only -- callers have already done the real
    validation). Never raises: this is opportunistic bookkeeping on hot paths
    like the boot health check."""
    try:
        iso_file = Path(iso_path)
        with open(iso_file, "rb") as f:
            if f.read(6) != _MELEE_GAME_ID:
                return
        known = known_vanilla_iso()
        if known is not None and str(known) == str(iso_file):
            return
        ISO_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ISO_RECORD_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"path": str(iso_file)}), encoding="utf-8")
        file_retry.replace(tmp, ISO_RECORD_PATH)
        logger.info(f"[vanilla_refs] recorded vanilla ISO: {iso_file}")
    except Exception as e:
        logger.debug(f"[vanilla_refs] could not record vanilla ISO {iso_path}: {e}")


def known_vanilla_iso() -> Path | None:
    """The recorded vanilla ISO path, or None if never recorded / since moved."""
    try:
        data = json.loads(ISO_RECORD_PATH.read_text(encoding="utf-8"))
        iso_file = Path(data["path"])
        return iso_file if iso_file.is_file() else None
    except Exception:
        return None


def extract_file_from_iso(iso_path, filename, dest_path) -> bool:
    """Extract the FST entry named `filename` (case-insensitive, files only)
    from the GC disc at `iso_path` into `dest_path` (written atomically).
    Returns whether the file was found and written. Raises on I/O errors and
    malformed discs -- callers decide how loudly to fail."""
    filename_l = str(filename).lower()
    with open(iso_path, "rb") as f:
        f.seek(0x424)
        fst_off, fst_size = struct.unpack(">II", f.read(8))
        if not (0 < fst_size <= _FST_SIZE_LIMIT):
            raise ValueError(f"implausible FST size 0x{fst_size:X} -- not a GC disc?")
        f.seek(fst_off)
        fst = f.read(fst_size)
        num_entries = struct.unpack(">I", fst[8:12])[0]
        if num_entries * 12 > len(fst):
            raise ValueError("FST entry count exceeds FST size")
        str_table = fst[num_entries * 12:]
        for i in range(1, num_entries):
            entry = fst[i * 12:(i + 1) * 12]
            if entry[0] != 0:  # directory
                continue
            name_off = int.from_bytes(entry[1:4], "big")
            end = str_table.find(b"\0", name_off)
            if end < 0:
                continue
            name = str_table[name_off:end].decode("ascii", "replace")
            if name.lower() != filename_l:
                continue
            file_off, length = struct.unpack(">II", entry[4:12])
            f.seek(file_off)
            data = f.read(length)
            if len(data) != length:
                raise ValueError(f"truncated read for {name} (wanted {length} bytes)")
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(data)
            file_retry.replace(tmp, dest)
            return True
    return False


def list_files_in_iso(iso_path, contains=None):
    """Enumerate the FST's file entries (no directories) as
    [{"name", "offset", "size"}], optionally filtered to names containing
    `contains` (case-insensitive). Raises on I/O errors and malformed discs."""
    contains_l = str(contains).lower() if contains else None
    out = []
    with open(iso_path, "rb") as f:
        f.seek(0x424)
        fst_off, fst_size = struct.unpack(">II", f.read(8))
        if not (0 < fst_size <= _FST_SIZE_LIMIT):
            raise ValueError(f"implausible FST size 0x{fst_size:X} -- not a GC disc?")
        f.seek(fst_off)
        fst = f.read(fst_size)
        num_entries = struct.unpack(">I", fst[8:12])[0]
        if num_entries * 12 > len(fst):
            raise ValueError("FST entry count exceeds FST size")
        str_table = fst[num_entries * 12:]
        for i in range(1, num_entries):
            entry = fst[i * 12:(i + 1) * 12]
            if entry[0] != 0:  # directory
                continue
            name_off = int.from_bytes(entry[1:4], "big")
            end = str_table.find(b"\0", name_off)
            if end < 0:
                continue
            name = str_table[name_off:end].decode("ascii", "replace")
            if contains_l and contains_l not in name.lower():
                continue
            file_off, length = struct.unpack(">II", entry[4:12])
            out.append({"name": name, "offset": file_off, "size": length})
    return out


def _dol_size(f, dol_off) -> int:
    """Size of the DOL at `dol_off`, from its own section table: the end of the
    furthest text/data section. (7 text + 11 data sections; offsets at 0x00,
    sizes at 0x90.)"""
    f.seek(dol_off)
    header = f.read(0xE0)
    if len(header) < 0xE0:
        raise ValueError("truncated DOL header")
    end = 0
    for i in range(18):
        off = struct.unpack_from(">I", header, i * 4)[0]
        size = struct.unpack_from(">I", header, 0x90 + i * 4)[0]
        if off and size:
            end = max(end, off + size)
    return end


def _extract_sys_block(iso_path, sys_dir) -> int:
    """Write the disc's system files (boot.bin, bi2.bin, apploader.img,
    main.dol, fst.bin) -- the parts of a GC disc that are NOT in the FST and
    which a full-disc extraction also emits."""
    sys_dir = Path(sys_dir)
    sys_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(iso_path, "rb") as f:
        f.seek(0x420)
        dol_off = struct.unpack(">I", f.read(4))[0]
        fst_off, fst_size = struct.unpack(">II", f.read(8))

        def dump(name, off, size):
            nonlocal written
            if not size:
                return
            f.seek(off)
            data = f.read(size)
            if len(data) != size:
                raise ValueError(f"truncated read for {name}")
            (sys_dir / name).write_bytes(data)
            written += 1

        dump("boot.bin", 0, 0x440)
        dump("bi2.bin", 0x440, 0x2000)
        # The apploader runs from 0x2440 up to the DOL.
        if dol_off > 0x2440:
            dump("apploader.img", 0x2440, dol_off - 0x2440)
        dump("main.dol", dol_off, _dol_size(f, dol_off))
        dump("fst.bin", fst_off, fst_size)
    return written


def extract_iso_files(iso_path, dest_dir, name_glob=None, chunk=8 * 1024 * 1024,
                      include_matching_dirs=False) -> int:
    """Extract a GC disc's FST into `dest_dir/files/...`, optionally limited to
    entries whose basename matches `name_glob` (fnmatch, case-insensitive).
    With `include_matching_dirs`, also extract descendants of matching folders
    (DAS uses GrPs/<arbitrary variant name>.dat and transformation sidecars).

    Pure Python, so it works on every platform with no external binary.

    Files land under a `files/` directory (callers rglob for 'files'). Directory entries are honoured, so nested paths like
    `audio/1padv.ssm` are preserved. Returns the number of files written.
    """
    import fnmatch

    pattern = name_glob.lower() if name_glob else None
    root = Path(dest_dir) / "files"
    root.mkdir(parents=True, exist_ok=True)
    written = 0

    # The sys/ block lives OUTSIDE the FST, and callers need main.dol from it
    # (stock-icon ordering reads the DOL). Only write it for a full extract --
    # a filtered one is asking for specific game files.
    if pattern is None:
        written += _extract_sys_block(iso_path, Path(dest_dir) / "sys")

    with open(iso_path, "rb") as f:
        f.seek(0x424)
        fst_off, fst_size = struct.unpack(">II", f.read(8))
        if not (0 < fst_size <= _FST_SIZE_LIMIT):
            raise ValueError(f"implausible FST size 0x{fst_size:X} -- not a GC disc?")
        f.seek(fst_off)
        fst = f.read(fst_size)
        num_entries = struct.unpack(">I", fst[8:12])[0]
        if num_entries * 12 > len(fst):
            raise ValueError("FST entry count exceeds FST size")
        str_table = fst[num_entries * 12:]

        def name_of(i):
            off = int.from_bytes(fst[i * 12 + 1:i * 12 + 4], "big")
            end = str_table.find(b"\0", off)
            return str_table[off:end if end >= 0 else None].decode("ascii", "replace")

        # A GC directory entry stores the index one PAST its last child, so a
        # stack of those bounds reconstructs the path of every file.
        dir_stack = [(num_entries, "")]
        for i in range(1, num_entries):
            while len(dir_stack) > 1 and i >= dir_stack[-1][0]:
                dir_stack.pop()
            entry = fst[i * 12:(i + 1) * 12]
            if entry[0] != 0:  # directory: push its extent
                next_idx = struct.unpack(">I", entry[8:12])[0]
                dir_stack.append((next_idx, str(Path(dir_stack[-1][1]) / name_of(i))))
                continue
            name = name_of(i)
            parent_matches = include_matching_dirs and pattern and any(
                fnmatch.fnmatch(part.lower(), pattern)
                for part in Path(dir_stack[-1][1]).parts)
            if pattern and not fnmatch.fnmatch(name.lower(), pattern) and not parent_matches:
                continue
            file_off, length = struct.unpack(">II", entry[4:12])
            dest = root / dir_stack[-1][1] / name if dir_stack[-1][1] else root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.seek(file_off)
            remaining = length
            with open(dest, "wb") as out:
                while remaining > 0:
                    buf = f.read(min(chunk, remaining))
                    if not buf:
                        raise ValueError(f"truncated read for {name}")
                    out.write(buf)
                    remaining -= len(buf)
            written += 1
    return written


def ensure_vanilla_ref(target_file, storage_path=None) -> Path | None:
    """Resolve the vanilla reference DAT for `target_file`, extracting it from
    the recorded vanilla ISO into <storage>/test-base/files/ if it is not
    already on disk. Returns the path, or None when unavailable (no ISO
    recorded, file not on the disc, extraction failed). Never raises."""
    target_file = str(target_file)
    if Path(target_file).name != target_file:
        return None  # reference names are bare filenames; refuse path segments
    dest = _refs_dir(storage_path) / target_file
    if dest.exists():
        return dest
    iso_file = known_vanilla_iso()
    if iso_file is None:
        return None
    with _extract_lock:
        if dest.exists():  # lost the race to another install thread
            return dest
        try:
            if extract_file_from_iso(iso_file, target_file, dest):
                logger.info(f"[vanilla_refs] extracted {target_file} from {iso_file}")
                return dest
            logger.warning(f"[vanilla_refs] {target_file} not found on {iso_file}")
        except Exception as e:
            logger.warning(f"[vanilla_refs] extracting {target_file} from {iso_file} failed: {e}")
    return None
