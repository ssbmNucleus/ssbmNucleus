#!/usr/bin/env python3
"""
Clear Storage Script - Removes all storage data

This script will:
- Delete all character folders in storage/
- Delete all stage variant folders in storage/das/
- Delete extracted preview images (CSP/stock icons)
- Reset storage metadata.json to default structure
- Delete the SQLite vault DB (vault.db + WAL/SHM) so a cleared vault
  stays cleared when the DB backend is active
- Clear Python cache directories
- Optionally clear intake folder
- Optionally clear logs

Note: No longer clears frontend/public/storage/ as the frontend now uses
      a proxy to serve files directly from storage/ folder.

Usage:
    python app/utility/clear_storage.py                # Clear storage only
    python app/utility/clear_storage.py --clear-intake # Also clear intake folder
    python app/utility/clear_storage.py --clear-logs   # Also clear logs
    python app/utility/clear_storage.py --all          # Clear everything
"""

import sys
import shutil
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
STORAGE_DIR = SCRIPT_DIR / "storage"
DAS_DIR = STORAGE_DIR / "das"
INTAKE_DIR = SCRIPT_DIR / "intake"
LOGS_DIR = SCRIPT_DIR / "logs"
METADATA_FILE = STORAGE_DIR / "metadata.json"

# The SQLite vault backend's on-disk artifacts (mirrors
# backend/vault/routes/vault_backup.py:_DB_ARTIFACTS). Resetting metadata.json
# alone leaves these behind, and the app "un-clears" itself on next launch by
# reading the stale DB.
DB_ARTIFACTS = ("vault.db", "vault.db-wal", "vault.db-shm")

# Default metadata structure
DEFAULT_METADATA = {
    "version": "1.0",
    "characters": {},
    "stages": {}
}


def clear_storage():
    """Clear all storage data"""
    print("Clearing storage...")

    removed_count = 0

    # Remove character folders in storage (excluding 'das' folder)
    if STORAGE_DIR.exists():
        for item in STORAGE_DIR.iterdir():
            if item.is_dir() and item.name != "das":
                print(f"  Removing: {item.name}/")
                shutil.rmtree(item)
                removed_count += 1

    # Remove stage variant folders in storage/das/
    if DAS_DIR.exists():
        for stage_folder in DAS_DIR.iterdir():
            if stage_folder.is_dir():
                # Clear contents of each stage folder
                variant_count = 0
                for variant_item in stage_folder.iterdir():
                    variant_item.unlink() if variant_item.is_file() else shutil.rmtree(variant_item)
                    variant_count += 1
                if variant_count > 0:
                    print(f"  Removing: das/{stage_folder.name}/ ({variant_count} items)")
                    removed_count += 1

    # Clear Python cache directories
    cache_count = clear_cache()
    if cache_count > 0:
        removed_count += cache_count

    # Reset metadata.json to default structure
    if METADATA_FILE.exists() or STORAGE_DIR.exists():
        print(f"  Resetting: metadata.json")
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(METADATA_FILE, 'w') as f:
            json.dump(DEFAULT_METADATA, f, indent=2)
        removed_count += 1

    # Remove the SQLite vault DB. Without this the DB backend reloads the old
    # vault on next launch and the "cleared" storage comes right back.
    for artifact in DB_ARTIFACTS:
        db_file = STORAGE_DIR / artifact
        if db_file.exists():
            print(f"  Removing: {artifact}")
            db_file.unlink()
            removed_count += 1

    if removed_count > 0:
        print(f"[OK] Cleared {removed_count} items from storage")
    else:
        print("[INFO] Storage is already empty")


def clear_intake():
    """Clear all files in intake folder"""
    print("\nClearing intake...")

    removed_count = 0

    if INTAKE_DIR.exists():
        for item in INTAKE_DIR.iterdir():
            if item.is_file():
                print(f"  Removing: {item.name}")
                item.unlink()
                removed_count += 1

    if removed_count > 0:
        print(f"[OK] Cleared {removed_count} files from intake")
    else:
        print("[INFO] Intake is already empty")


def clear_cache():
    """Clear Python cache directories"""
    removed_count = 0

    # Find and remove all __pycache__ directories
    for cache_dir in SCRIPT_DIR.rglob("__pycache__"):
        if cache_dir.is_dir():
            print(f"  Removing: {cache_dir.relative_to(SCRIPT_DIR)}")
            shutil.rmtree(cache_dir)
            removed_count += 1

    return removed_count


def clear_logs():
    """Clear all log files"""
    print("\nClearing logs...")

    removed_count = 0

    if LOGS_DIR.exists():
        for item in LOGS_DIR.iterdir():
            if item.is_file() and item.suffix == '.log':
                print(f"  Removing: {item.name}")
                item.unlink()
                removed_count += 1

    if removed_count > 0:
        print(f"[OK] Cleared {removed_count} log files")
    else:
        print("[INFO] No log files to clear")


def main():
    print("="*60)
    print("Clear Storage Script")
    print("="*60)

    # Parse arguments
    clear_intake_flag = "--clear-intake" in sys.argv or "--all" in sys.argv
    clear_logs_flag = "--clear-logs" in sys.argv or "--all" in sys.argv

    # Always clear storage
    clear_storage()

    # Optionally clear intake
    if clear_intake_flag:
        clear_intake()

    # Optionally clear logs
    if clear_logs_flag:
        clear_logs()

    print("\n" + "="*60)
    print("Done!")
    print("="*60)

    if not clear_intake_flag:
        print("\nNote: Intake folder was not cleared.")
        print("      Use --clear-intake or --all to clear it.")


if __name__ == "__main__":
    main()
