"""Keep the Any Climbers engine code in any project that needs it.

Pairing two fighters is pure data (m-ex's `subCharacter`), but the partner only
*behaves* like Nana once the Gecko code in `engine/any_climbers.ini` is applied
-- without it the partner spawns as an ordinary free-roaming CPU. So the code is
injected at export time, the same way `export.py` injects its other required
codes, but only for projects that actually contain a pair.
"""
from __future__ import annotations

import logging
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from core.config import BACKEND_DATA_DIR, MEXCLI_PATH, get_subprocess_args
from core.gecko import parse_ini, serialize_ini

logger = logging.getLogger(__name__)

# Bundled data, so it must resolve through BACKEND_DATA_DIR (sys._MEIPASS in a
# frozen build) -- a Path(__file__)-relative lookup silently vanishes when
# packaged, and the only symptom would be pairs building without their engine
# code. `engine/gen_engine_code.py` regenerates the file in place.
_INI_PATH = BACKEND_DATA_DIR / "any_climbers.ini"

# Popo already selects the follower AI by fighter kind, so a vanilla-only
# project (Ice Climbers, Zelda/Sheik) does not need the code.
_VANILLA_PAIR_LEADERS = {"ice climbers", "popo", "zelda", "sheik"}


def code_entry() -> tuple[str, str]:
    """(name, hex source) for the bundled, project-independent Any Climbers code."""
    codes = parse_ini(_INI_PATH.read_text(encoding="utf-8"))
    if not codes:
        raise RuntimeError(f"no code found in {_INI_PATH}")
    return codes[0]["name"], codes[0]["source"]


def project_aliases(fighters: list[dict]) -> dict[int, int]:
    """{clone internal id: donor internal id} for every Any Climbers pair leader.

    A pair's leader is a duplicate that still names its donor's data symbol
    (`files.fighterDataSymbol`, e.g. `ftDataCaptain` -- MexFighter.Duplicate
    shares the fighter DAT rather than copying it), so the donor is the
    lowest-numbered fighter carrying the same symbol. Only climbers pairs are
    aliased: transform pairs and vanilla pairings are left alone, as is any
    clone the app did not build as a pair (Echo characters keep their kind).
    """
    by_symbol: dict[str, int] = {}
    for internal_id, fighter in enumerate(fighters):
        sym = ((fighter.get("files") or {}).get("fighterDataSymbol") or "").strip()
        if sym and sym not in by_symbol:
            by_symbol[sym] = internal_id
    out: dict[int, int] = {}
    for internal_id, fighter in enumerate(fighters):
        sub = fighter.get("subCharacter", -1)
        if sub in (-1, 255) or fighter.get("subCharacterBehavior", 0) != 0:
            continue
        if fighter.get("name", "").strip().lower() in _VANILLA_PAIR_LEADERS:
            continue
        sym = ((fighter.get("files") or {}).get("fighterDataSymbol") or "").strip()
        donor = by_symbol.get(sym)
        if donor is None or donor == internal_id:
            continue
        out[internal_id] = donor
    return out


# --- clone_engine cleanup ------------------------------------------------------
#
# Pairs built before 0.8.7 also carried m-ex's `clone_engine` function patch:
# `mexcli add-fighter` merged the package's `patches/clone_engine.dat` into the
# project's MxPt.dat, where it stays for every later export. The kind alias
# made it redundant for pairs, and it breaks Kirby's copied specials for EVERY
# fighter in the build: the patch's effect hook resolves each effect through
# the spawning fighter's own effect bank, so a Kirby wearing a hat draws Kirby's
# effects (Falcon Punch showed the Final Cutter slash, Warlock Punch crashed at
# its end). Vanilla, a build without pairs, and a pair build with the patch
# removed all render the copied moves correctly.
#
# Only Nucleus's pairs ever added the patch, but a project can also hold clones
# from other packages that still rely on it, so it is stripped only when every
# clone in the project is a pair leader the alias table covers.
CLONE_ENGINE_ROOT = "clone_engine"
_HSD_HEADER = 0x20


def hsd_root_names(data: bytes) -> list[str]:
    """Root symbol names of an HSD archive (the MxPt.dat layout)."""
    file_size, data_size, reloc_count, root_count, ref_count = struct.unpack(
        ">5I", data[:0x14])
    if file_size != len(data):
        raise ValueError(f"HSD size field {file_size} != {len(data)} bytes")
    roots_at = _HSD_HEADER + data_size + reloc_count * 4
    strings_at = roots_at + (root_count + ref_count) * 8
    names = []
    for i in range(root_count):
        _, str_off = struct.unpack(">II", data[roots_at + i * 8: roots_at + i * 8 + 8])
        end = data.index(b"\x00", strings_at + str_off)
        names.append(data[strings_at + str_off:end].decode("ascii", "replace"))
    return names


def drop_hsd_root(data: bytes, name: str) -> bytes:
    """The archive without the root called `name` (its data is left in place,
    unreferenced). A root-less archive collapses to a bare header, the shape
    verified in game."""
    names = hsd_root_names(data)
    if name not in names:
        return data
    file_size, data_size, reloc_count, root_count, ref_count = struct.unpack(
        ">5I", data[:0x14])
    if root_count == 1 and ref_count == 0:
        return struct.pack(">5I", _HSD_HEADER, 0, 0, 0, 0) + bytes(12)
    roots_at = _HSD_HEADER + data_size + reloc_count * 4
    idx = names.index(name)
    out = bytearray(data)
    del out[roots_at + idx * 8: roots_at + idx * 8 + 8]
    out[0:0x10] = struct.pack(">4I", len(out), data_size, reloc_count, root_count - 1)
    return bytes(out)


def _clone_ids(fighters: list[dict]) -> list[int]:
    """Internal ids that reuse another fighter's data symbol -- duplicates."""
    seen: set[str] = set()
    out = []
    for internal_id, fighter in enumerate(fighters):
        sym = ((fighter.get("files") or {}).get("fighterDataSymbol") or "").strip()
        if not sym:
            continue
        if sym in seen:
            out.append(internal_id)
        seen.add(sym)
    return out


def clone_engine_removable(fighters: list[dict]) -> bool:
    """True when every clone in the project is an aliased pair leader."""
    aliased = project_aliases(fighters)
    return all(clone in aliased for clone in _clone_ids(fighters))


def strip_clone_engine(project_path, fighters: list[dict]) -> bool:
    """Drop a stale `clone_engine` patch from the project's patch tables.

    Returns True if a file was rewritten. Both MxPt.dat (enabled patches) and
    MxPt_.dat (disabled ones) are checked; MexCLI reads them back as an empty
    patch list and leaves the files alone, and the ISO build ships them as-is.
    """
    files = Path(project_path).parent / "files"
    removable = None
    changed = False
    for fname in ("MxPt.dat", "MxPt_.dat"):
        path = files / fname
        if not path.exists():
            continue
        data = path.read_bytes()
        try:
            names = hsd_root_names(data)
        except Exception as e:
            logger.warning(f"{fname} not parsed, clone_engine left alone: {e}")
            continue
        if CLONE_ENGINE_ROOT not in names:
            continue
        if removable is None:
            removable = clone_engine_removable(fighters)
        if not removable:
            logger.info("clone_engine kept in %s: the project has clones the "
                        "pair alias does not cover", fname)
            return False
        path.write_bytes(drop_hsd_root(data, CLONE_ENGINE_ROOT))
        logger.info("clone_engine patch removed from %s (superseded by the kind alias)", fname)
        changed = True
    return changed


def desired_source(fighters: list[dict], no_swap=()) -> tuple[str, str]:
    """(name, source) the project SHOULD carry: the bundled engine code plus
    this project's clone->donor alias block. `no_swap` names the pairs that keep
    their leader (`pairs.no_swap_pairs`)."""
    from vault.climbers.engine.gen_engine_code import alias_ini_lines
    name, source = code_entry()
    aliases = project_aliases(fighters)
    locked = {clone for clone in aliases if fighters[clone].get("name") in no_swap}
    lines = alias_ini_lines(aliases, locked)
    if lines:
        source = source.rstrip("\n") + "\n" + "\n".join(lines)
    return name, source


def project_has_pair(fighters: list[dict]) -> bool:
    """True if any fighter spawns a sub-fighter that isn't a vanilla pairing."""
    for fighter in fighters:
        sub = fighter.get("subCharacter", -1)
        if sub in (-1, 255):
            continue
        if fighter.get("subCharacterBehavior", 0) != 0:
            continue  # transform pair (Zelda/Sheik), not a climbers pair
        if fighter.get("name", "").strip().lower() in _VANILLA_PAIR_LEADERS:
            continue
        return True
    return False


def _normalized(source: str) -> str:
    """Hex words only, so cosmetic differences (labels, spacing) don't count."""
    words = []
    for line in source.splitlines():
        line = line.split("#", 1)[0].strip()   # drop inline labels first
        if line:
            words.append("".join(ch for ch in line if ch in "0123456789abcdefABCDEF"))
    return " ".join(words).upper()


def _same_code(code: dict, name: str) -> bool:
    """`parse_ini` splits "Name [Creator]" into name + creator (like mexcli's
    CodeLoader), so match the bundled header against both forms."""
    wanted = name.strip().lower()
    bare = code["name"].strip().lower()
    full = (f"{code['name']} [{code['creator']}]".strip().lower()
            if code.get("creator") else bare)
    return wanted in (bare, full)


def stale_block(project_path, name: str, source: str) -> bool | None:
    """True if the project carries an OLDER copy of the engine code under
    `name`, False if it matches the bundled one, None if it has no copy."""
    ini = Path(project_path).parent / "files" / "codes.ini"
    if not ini.exists():
        return None
    for code in parse_ini(ini.read_text(encoding="utf-8", errors="replace")):
        if _same_code(code, name):
            return _normalized(code["source"]) != _normalized(source)
    return None


def _refresh_block(project_path, name: str, source: str) -> bool:
    """Replace the project's copy of the engine code with the bundled one.

    `mexcli add-code` skips a code whose NAME already exists, so a project
    that was first exported on an older app kept that app's engine code on
    every later export -- the 0.8.6 swap guard never reached projects created
    on 0.8.5, which is exactly what the "still softlocks on 0.8.6" report was.
    `sync-codes` rewrites codes.ini AND codes.gct from a complete ini, so the
    project's other codes (and their enabled flags) are carried over verbatim.
    """
    ini = Path(project_path).parent / "files" / "codes.ini"
    codes = parse_ini(ini.read_text(encoding="utf-8", errors="replace"))
    for code in codes:
        if _same_code(code, name):
            code["source"] = source
            code["enabled"] = True
    desired = Path(tempfile.mkdtemp(prefix="anyclimbers_")) / "codes.ini"
    desired.write_text(serialize_ini(codes), encoding="utf-8")
    try:
        result = subprocess.run(
            [str(MEXCLI_PATH), "sync-codes", str(project_path), str(desired)],
            capture_output=True, text=True, timeout=120, **get_subprocess_args())
        if result.returncode != 0:
            logger.warning(f"Any Climbers code not refreshed: {result.stdout or result.stderr}")
            return False
        logger.info("Any Climbers engine code refreshed to the bundled version")
        return True
    finally:
        shutil.rmtree(desired.parent, ignore_errors=True)


def ensure_code(project_path) -> bool:
    """Add the code to the project if missing, or refresh it if the project's
    copy is older than the bundled one. Returns True if it's present. Also
    drops the superseded `clone_engine` patch (see `strip_clone_engine`).

    Best-effort, matching `_ensure_required_gecko_codes`: a failure here is
    logged and the build continues (the pair still spawns, the partner just
    won't follow) rather than blocking an export.
    """
    if not MEXCLI_PATH.exists():
        logger.warning("MexCLI not found; skipping Any Climbers code")
        return False
    fighters: list[dict] = []
    try:
        from vault.climbers.pairs import load_fighters, no_swap_pairs
        fighters = load_fighters(project_path)
        name, source = desired_source(fighters, no_swap_pairs(project_path))
    except Exception as e:  # never let alias inference block a build
        logger.warning(f"Any Climbers alias table skipped: {e}")
        name, source = code_entry()
    try:
        if fighters:
            strip_clone_engine(project_path, fighters)
    except Exception as e:  # cosmetic for the build: the pair still works
        logger.warning(f"clone_engine cleanup skipped: {e}")
    try:
        if stale_block(project_path, name, source):
            return _refresh_block(project_path, name, source)
        result = subprocess.run(
            [str(MEXCLI_PATH), "add-code", str(project_path), name, source],
            capture_output=True, text=True, timeout=120, **get_subprocess_args())
        if result.returncode != 0:
            logger.warning(f"Any Climbers code not added: {result.stdout or result.stderr}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Any Climbers code injection failed: {e}")
        return False


def ensure_for_export(project_path) -> None:
    """`ensure_code` for a project that holds a pair, and nothing otherwise.

    Every export runs this, the app's and a test build's alike: a pair spawns
    its partner from plain m-ex data, but without the code the partner is an
    ordinary free-roaming CPU and a clone leader keeps its own kind. Best-effort
    like `ensure_code`.
    """
    try:
        from vault.climbers.pairs import load_fighters
        if project_has_pair(load_fighters(project_path)) and ensure_code(project_path):
            logger.info("Any Climbers engine code present for this build")
    except Exception as e:
        logger.warning(f"Any Climbers code check skipped: {e}")
