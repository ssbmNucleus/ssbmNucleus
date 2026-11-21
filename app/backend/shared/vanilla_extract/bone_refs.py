"""
bone_refs.py -- Slippi bone-reference tables, derived from the user's own ISO.

`costume_validator.py` needs a per-symbol reference skeleton for every vanilla
costume before it can tell whether a modded one is netplay-safe. Those tables
used to ship with the app: 159 `.bin` files lifted out of retail `Pl*.dat`, or
1.3 MB of Nintendo game data in the installer (docs/dev/VANILLA_ASSET_POLICY.md).

They are now generated here instead, straight out of the vanilla ISO the user
already had to supply. A GC disc is unencrypted and `vanilla_refs` already
walks its FST, so this reads each costume file at its recorded offset and
hands the bytes to `bone_tables` -- no extraction to disk, no mexcli, ~1 s for
the whole disc (59 MB of costume DATs). The output is byte-identical to the
tables that used to ship, which tests/backend/test_bone_tables.py asserts
against the in-tree copies.

Two callers:

  * first_run_setup, right after ISO extraction, with the ISO in hand.
  * costume_validator, lazily, through the provider registered in core.config
    -- so an install that predates this change generates its tables the first
    time a costume is validated rather than silently passing everything.

Never raises: a failure leaves the validator on its bundled/dev fallback, and
`costume_validator` already reports "Could not match symbol" for what it
cannot resolve.
"""

import json
import logging
import threading
from pathlib import Path

import file_retry
from core.config import STORAGE_PATH

import bone_tables
import costume_validator
from shared.vanilla_extract import vanilla_refs

logger = logging.getLogger(__name__)

# Bumped when the table format or the source-file selection changes, so an
# existing directory is regenerated rather than trusted.
MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"

# A retail 1.02 disc yields 159 tables. Accept a little slack (a user's disc
# revision could differ) but treat a much smaller set as a failed generation
# worth retrying rather than a finished one worth trusting.
EXPECTED_TABLE_COUNT = 159
MIN_TABLE_COUNT = 140

_lock = threading.Lock()

# The validator asks for the directory once per skeleton root, so a bulk import
# hits this hundreds of times. Remember a directory we have already validated
# rather than re-reading the manifest and re-globbing 159 files each time; the
# path never changes within a session, only whether it is populated yet.
_resolved: dict = {}


def bone_ref_dir(storage_path=None) -> Path:
    """Where the derived tables live. Sits under test-base/ with the other
    user-derived vanilla reference data, not in the vault proper."""
    return Path(storage_path or STORAGE_PATH) / "test-base" / "bone-refs"


def _manifest_ok(out_dir: Path) -> bool:
    try:
        manifest = json.loads((out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if manifest.get("version") != MANIFEST_VERSION:
        return False
    count = manifest.get("tables", 0)
    if not isinstance(count, int) or count < MIN_TABLE_COUNT:
        return False
    # Cheap sanity check that the files themselves are still there.
    return sum(1 for _ in out_dir.glob("*.bin")) >= MIN_TABLE_COUNT


def _tables_from_iso(iso_path) -> dict:
    """{symbol: table} read straight out of the disc image.

    `list_files_in_iso` gives an offset and size per FST entry, so each costume
    DAT is one seek and one bounded read -- nothing is written to disk.
    """
    entries = [e for e in vanilla_refs.list_files_in_iso(iso_path, contains="Pl")
               if costume_validator.is_costume_file(e["name"])]
    tables = {}
    with open(iso_path, "rb") as f:
        for entry in entries:
            f.seek(entry["offset"])
            buf = f.read(entry["size"])
            if len(buf) != entry["size"]:
                continue
            for symbol, data in bone_tables.tables_from_bytes(buf).items():
                tables.setdefault(symbol, data)
    return tables


def _write(out_dir: Path, tables: dict) -> None:
    bone_tables.write_tables(tables, out_dir)
    manifest = {
        "version": MANIFEST_VERSION,
        "source": "user-verified-iso",
        "tables": len(tables),
    }
    temporary = out_dir / (MANIFEST_NAME + ".tmp")
    try:
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        file_retry.replace(temporary, out_dir / MANIFEST_NAME)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_bone_refs(iso_path=None, storage_path=None, force=False):
    """Return the derived reference directory, generating it if needed.

    `iso_path` is the ISO to read; without one the ISO recorded by
    `vanilla_refs.record_vanilla_iso` is used. Returns None when the tables
    could not be produced (no ISO on record, unreadable disc) -- callers fall
    back to whatever `costume_validator.ref_dir()` finds next.
    """
    out_dir = bone_ref_dir(storage_path)
    key = str(out_dir)
    if not force and _resolved.get(key):
        return out_dir
    if not force and _manifest_ok(out_dir):
        _resolved[key] = True
        return out_dir

    with _lock:
        if not force and _manifest_ok(out_dir):
            _resolved[key] = True
            return out_dir  # lost the race to another thread

        iso_file = Path(iso_path) if iso_path else vanilla_refs.known_vanilla_iso()
        if iso_file is None or not Path(iso_file).is_file():
            logger.debug("[bone_refs] no vanilla ISO on record; cannot derive tables")
            return None

        try:
            tables = _tables_from_iso(iso_file)
        except Exception as e:
            logger.warning("[bone_refs] reading %s failed: %s", iso_file, e)
            return None

        if len(tables) < MIN_TABLE_COUNT:
            logger.warning(
                "[bone_refs] %s produced only %d bone tables (expected ~%d); "
                "not publishing a partial set",
                iso_file, len(tables), EXPECTED_TABLE_COUNT)
            return None

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            _write(out_dir, tables)
        except OSError as e:
            logger.warning("[bone_refs] writing %s failed: %s", out_dir, e)
            return None

        logger.info("[bone_refs] derived %d bone reference tables from %s",
                    len(tables), iso_file)
        _resolved[key] = True
        return out_dir


