"""Frame Speed Modifier (FSM) engine patcher.

Bakes Magus420's FSM engine (the "(DOL) FSM Engine" patch from Crazy Hand)
directly into a project's sys/main.dol, so legacy moveset mods that ship a
Crazy Hand FSM .txt work in Nucleus/m-ex builds with zero Gecko code-space
cost.

How the engine works (NTSC 1.02):
  - A ~224-byte PPC routine is written into the debug-menu strings region of
    the DOL (file 0x4088B0, RAM 0x8040B8A8). That region only holds
    "PUSH START BUTTON" / "MEM DUMP" debug-screen text and is the same spot
    Crazy Hand has used for years; m-ex leaves it untouched.
  - An entry table follows at file 0x4089B0 (RAM 0x8040B9A8): up to 150
    entries of 8 bytes each, zero-terminated.
  - One instruction in the animation-advance epilogue (file 0x6FF18,
    RAM 0x80073330, vanilla `lmw r27,0x14(r1)` = BB610014) is replaced with a
    branch into the engine. The engine re-executes the displaced instruction
    and branches back.

Entry format (matches Crazy Hand's FSM .txt lines `b0,b1,b2,b3,float`):
  b0    character ID (EXTERNAL id - rewritten at build time for added chars)
  b1    starting frame
  b2/b3 flags + subaction/action id (0x80 bit = subaction, low bit of b2 is
        bit 8 of the subaction id)
  float animation speed multiplier (big endian)

The engine matches entries against the external character ID read from the
static player blocks, so added m-ex fighters work as long as the entry's ID
byte equals their external slot id - and vanilla characters are unaffected
unless explicitly listed.
"""

import json
import logging
import struct
from pathlib import Path

import file_retry

logger = logging.getLogger(__name__)

# DOL file offsets (NTSC 1.02 / m-ex base)
ENGINE_FILE_OFFSET = 0x4088B0
TABLE_FILE_OFFSET = 0x4089B0
HOOK_FILE_OFFSET = 0x6FF18

# RAM addresses (for reference / runtime verification), from the 1.02 DOL
# section table: file 0x4088B0 -> 0x8040B8B0 etc. Note the engine's hardcoded
# table base 0x8040B9A8 is TABLE_RAM - 8: its loop reads entries with
# `lwzu r29, 8(r31)` (pre-increment), so the first entry sits at TABLE_RAM.
ENGINE_RAM = 0x8040B8B0
TABLE_RAM = 0x8040B9B0
HOOK_RAM = 0x80073338

HOOK_VANILLA = bytes.fromhex("BB610014")  # lmw r27, 0x14(r1)
HOOK_PATCHED = bytes.fromhex("48398578")  # b ENGINE_RAM

ENTRY_SIZE = 8
MAX_ENTRIES = 150
ENGINE_REGION_SIZE = TABLE_FILE_OFFSET - ENGINE_FILE_OFFSET  # 0x100
TABLE_REGION_SIZE = MAX_ENTRIES * ENTRY_SIZE  # 1200 bytes

# Magus420's FSM engine from Crazy Hand's injectCode(), with one change for
# Slippi-rollback safety: the original used `stfd f1, 0(r2)` as float->int
# conversion scratch, writing 8 bytes/frame at 0x804DF9E0 -- PAST the end of
# .sdata2, in BSS we don't own. This build redirects the scratch to
# 0x8040B9A8 (the table-base pointer target inside OUR region; the scan
# reads table entries from +8 onward, so those 8 bytes are never read).
# Inserted `lis/ori r29` + rebased stfd/lwz; all internal branches are
# relative so the 8-byte shift is safe; the final branch-back is re-encoded
# for the new tail position (verified by _check_engine_integrity).
# (position-dependent: must live at ENGINE_RAM, table at TABLE_RAM).
ENGINE_CODE = bytes.fromhex(
    "7F63DB788BE3006C3FA0804563BD30841FFF0E907FFDFA14809F00008BFF0008"
    "2C0400134182001C2C04001240A200202C1F000140A200183880001348000010"
    "2C1F000140A2000838800012C03E0894FC20081E3FA0804063BDB9A8D83D0000"
    "80BD000480C3007080E3007460E780003FE0804063FFB9A887BF00082C1D0000"
    "4182006057BC463E2C1C00FF418200147C1C20004182000C418100484BFFFFDC"
    "57BC863E7C1C280041A1FFD057BC043E7C1C30004182000C7C1C38004082FFBC"
    "839F00042C1CFFFF41820018C03F00043FE0800663FFF1907FE803A64E800021"
    "BB6100144BC679A8"
)

SIDECAR_SUFFIX = ".fsm_orig.bin"


class FsmError(Exception):
    pass


def _check_engine_integrity():
    """Internal consistency checks on the engine blob and addresses."""
    assert len(ENGINE_CODE) <= ENGINE_REGION_SIZE, "engine exceeds region"
    # hook branch: b from HOOK_RAM must land on ENGINE_RAM
    li = int.from_bytes(HOOK_PATCHED, "big") & 0x03FFFFFC
    assert HOOK_RAM + li == ENGINE_RAM, "hook branch target mismatch"
    # return branch: engine ends with displaced instr + b back to HOOK_RAM+4
    assert ENGINE_CODE.endswith(HOOK_VANILLA + bytes.fromhex("4BC679A8"))
    ret_at = ENGINE_RAM + len(ENGINE_CODE) - 4
    ret_li = 0x4BC679A8 & 0x03FFFFFC
    if ret_li & 0x02000000:
        ret_li -= 0x04000000
    assert ret_at + ret_li == HOOK_RAM + 4, "return branch target mismatch"
    # scratch redirect: the engine must reference its in-region scratch slot
    # (lis r29, 0x8040 / ori r29, 0xB9A8 = TABLE_RAM - 8, never read by the
    # entry scan which starts at TABLE_RAM via lwzu +8)
    assert bytes.fromhex("3FA0804063BDB9A8") in ENGINE_CODE, "scratch redirect missing"
    assert bytes.fromhex("D8220000") not in ENGINE_CODE, "r2 scratch write still present"


_check_engine_integrity()


def parse_fsm_txt(text):
    """Parse Crazy Hand FSM .txt lines into (b0, b1, b2, b3, multiplier).

    Lines look like `10,0,128,11,2.0`. Blank lines and lines starting with
    '#' or '//' are ignored.
    """
    entries = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            raise FsmError(f"line {lineno}: expected 5 fields, got {len(parts)}: {raw!r}")
        try:
            b = [int(p) for p in parts[:4]]
            mult = float(parts[4])
        except ValueError as e:
            raise FsmError(f"line {lineno}: {e}")
        for v in b:
            if not 0 <= v <= 255:
                raise FsmError(f"line {lineno}: byte value {v} out of range")
        entries.append((b[0], b[1], b[2], b[3], mult))
    return entries


def build_table(entries):
    """Pack entries into the zero-terminated table region (full size)."""
    if len(entries) > MAX_ENTRIES:
        raise FsmError(f"{len(entries)} FSM entries exceed engine cap of {MAX_ENTRIES}")
    table = bytearray()
    for b0, b1, b2, b3, mult in entries:
        table += bytes([b0, b1, b2, b3]) + struct.pack(">f", mult)
    table += b"\x00" * (TABLE_REGION_SIZE - len(table))
    return bytes(table)


def retarget_entries(entries, external_id):
    """Return entries with the character-ID byte rewritten to external_id."""
    return [(external_id, b1, b2, b3, m) for _b0, b1, b2, b3, m in entries]


def get_patch_state(dol_path):
    """Return 'vanilla', 'patched', or 'unknown' for the dol's hook site."""
    with open(dol_path, "rb") as f:
        f.seek(HOOK_FILE_OFFSET)
        hook = f.read(4)
    if hook == HOOK_VANILLA:
        return "vanilla"
    if hook == HOOK_PATCHED:
        return "patched"
    return "unknown"


def _sidecar_path(dol_path):
    return Path(str(dol_path) + SIDECAR_SUFFIX)


def apply_fsm_patch(dol_path, entries):
    """Write the FSM engine + entry table + hook into main.dol.

    Idempotent: safe to call repeatedly with different entries; the engine
    region is rewritten from scratch each time. The original bytes are saved
    to a sidecar file the first time so the patch can be reverted.
    """
    dol_path = Path(dol_path)
    state = get_patch_state(dol_path)
    if state == "unknown":
        raise FsmError(
            f"{dol_path}: unexpected bytes at hook site 0x{HOOK_FILE_OFFSET:X}; "
            "DOL is not a known NTSC 1.02 / m-ex layout - refusing to patch"
        )

    with file_retry.retry_locked(open, dol_path, "r+b") as f:
        if state == "vanilla":
            # preserve originals for revert
            f.seek(ENGINE_FILE_OFFSET)
            region = f.read(ENGINE_REGION_SIZE + TABLE_REGION_SIZE)
            _sidecar_path(dol_path).write_bytes(HOOK_VANILLA + region)

        f.seek(ENGINE_FILE_OFFSET)
        f.write(ENGINE_CODE)
        f.write(b"\x00" * (ENGINE_REGION_SIZE - len(ENGINE_CODE)))
        f.write(build_table(entries))
        f.seek(HOOK_FILE_OFFSET)
        f.write(HOOK_PATCHED)

    logger.info(
        f"FSM patch applied to {dol_path}: {len(entries)} entries "
        f"(engine@0x{ENGINE_FILE_OFFSET:X}, hook@0x{HOOK_FILE_OFFSET:X})"
    )


def remove_fsm_patch(dol_path):
    """Restore the original bytes from the sidecar. No-op if not patched."""
    dol_path = Path(dol_path)
    if get_patch_state(dol_path) != "patched":
        return False
    sidecar = _sidecar_path(dol_path)
    if not sidecar.exists():
        raise FsmError(f"{dol_path} is FSM-patched but sidecar {sidecar} is missing")
    data = sidecar.read_bytes()
    hook, region = data[:4], data[4:]
    with file_retry.retry_locked(open, dol_path, "r+b") as f:
        f.seek(ENGINE_FILE_OFFSET)
        f.write(region)
        f.seek(HOOK_FILE_OFFSET)
        f.write(hook)
    sidecar.unlink()
    logger.info(f"FSM patch removed from {dol_path}")
    return True


# ---------------------------------------------------------------------------
# Project integration: gather FSM data for installed custom characters
# ---------------------------------------------------------------------------

# Vanilla internal->external id table (from mexLib MexFighterIDConverter)
_INTERNAL_TO_EXTERNAL = [
    0x08, 0x02, 0x00, 0x01, 0x04, 0x05, 0x06,
    0x13, 0x0B, 0x0C, 0x0E, 0x20, 0x0D, 0x10,
    0x11, 0x0F, 0x0A, 0x07, 0x09, 0x12, 0x15,
    0x16, 0x14, 0x18, 0x03, 0x19, 0x17, 0x1A,
    0x1E, 0x1B, 0x1C, 0x1D, 0x1F,
]
_BASE_CHARACTER_COUNT = 0x21
_INTERNAL_SPECIAL_COUNT = 6
_EXTERNAL_SPECIAL_COUNT = 7


def to_external_id(internal_id, character_count):
    """Port of mexLib MexFighterIDConverter.ToExternalID."""
    added = character_count - _BASE_CHARACTER_COUNT
    is_special = internal_id >= character_count - _INTERNAL_SPECIAL_COUNT

    if (internal_id >= character_count - _INTERNAL_SPECIAL_COUNT - added
            and not is_special):
        # added (m-ex) fighter
        return ((_BASE_CHARACTER_COUNT - _EXTERNAL_SPECIAL_COUNT)
                + (internal_id - (_BASE_CHARACTER_COUNT - _INTERNAL_SPECIAL_COUNT)))

    external = internal_id + (-added if is_special else 0)
    if external < len(_INTERNAL_TO_EXTERNAL):
        external = _INTERNAL_TO_EXTERNAL[external]
    if is_special:
        external += added
    if internal_id == 11:  # POPO special case
        external = character_count - 1
    return external


def load_project_fighters(project_path):
    """Return ordered [(internal_id, name)] from a .mexproj's fighter data."""
    project_path = Path(project_path)
    project_dir = project_path.parent
    with open(project_path, "r", encoding="utf-8") as f:
        proj = json.load(f)
    file_paths = proj.get("fighterSaveMap", {}).get("filePaths", [])
    fighters = []
    for idx, rel in enumerate(file_paths):
        fighter_file = project_dir / "data" / "fighters" / rel
        name = None
        if fighter_file.exists():
            try:
                with open(fighter_file, "r", encoding="utf-8") as f:
                    name = json.load(f).get("name")
            except Exception as e:
                logger.warning(f"Could not read fighter file {fighter_file}: {e}")
        fighters.append((idx, name))
    return fighters


def collect_fsm_entries(project_path, custom_characters_dir):
    """Gather retargeted FSM entries for every installed custom character
    whose vault folder contains an fsm.txt.

    Matches project fighters to vault characters by fighter name
    (fighter.json "name" == project fighter name).
    """
    custom_characters_dir = Path(custom_characters_dir)

    # vault name -> parsed entries
    vault_fsm = {}
    if custom_characters_dir.is_dir():
        for char_dir in custom_characters_dir.iterdir():
            fsm_file = char_dir / "fsm.txt"
            fighter_json = char_dir / "fighter.json"
            if not fsm_file.is_file() or not fighter_json.is_file():
                continue
            try:
                with open(fighter_json, "r", encoding="utf-8") as f:
                    name = json.load(f).get("name")
                entries = parse_fsm_txt(fsm_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Skipping FSM data in {char_dir.name}: {e}")
                continue
            if name and entries:
                vault_fsm[name] = entries

    if not vault_fsm:
        return []

    fighters = load_project_fighters(project_path)
    count = len(fighters)
    merged = []
    for internal_id, name in fighters:
        if name in vault_fsm:
            ext = to_external_id(internal_id, count)
            entries = retarget_entries(vault_fsm[name], ext)
            merged.extend(entries)
            logger.info(
                f"FSM: {name} (internal {internal_id} -> external 0x{ext:02X}): "
                f"{len(entries)} entries"
            )
    return merged


def apply_project_fsm(project_path, custom_characters_dir):
    """Entry point for the export pipeline.

    Collects FSM data for the project's installed custom characters and
    patches (or un-patches) the project's sys/main.dol accordingly.
    Returns the number of FSM entries applied.
    """
    project_path = Path(project_path)
    dol_path = project_path.parent / "sys" / "main.dol"
    if not dol_path.is_file():
        raise FsmError(f"main.dol not found at {dol_path}")

    entries = collect_fsm_entries(project_path, custom_characters_dir)
    if entries:
        apply_fsm_patch(dol_path, entries)
    else:
        if remove_fsm_patch(dol_path):
            logger.info("FSM: no FSM characters installed; restored vanilla dol bytes")
    return len(entries)
