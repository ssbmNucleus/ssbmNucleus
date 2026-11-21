#!/usr/bin/env python3
"""
Slippi costume validation -- thin wrapper over the pure-Python validator.

Previously this shelled out to SlippiCostumeValidator.exe with shell=True, which
made validation Windows-only: on Linux/macOS every costume came back "unsafe"
and auto-fix was unavailable. See costume_validator.py for the reimplementation
and how it was differential-tested against the original binary.

Two side effects of dropping the subprocess, both improvements:
  * `auto_fix=False` no longer rewrites the file. The old exe always fixed in
    place, so every caller had to hand it a throwaway copy first.
  * No 10-second timeout / no console handshake ("Press enter to exit").
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import costume_validator  # noqa: E402


def _result(is_valid=False, needs_fix=False, fix_applied=False,
            backup_path=None, output=""):
    return {
        'is_valid': is_valid,
        'needs_fix': needs_fix,
        'fix_applied': fix_applied,
        'backup_path': backup_path,
        'output': output,
    }


def validate_dat_file(dat_path, auto_fix=False, create_backup=True):
    """
    Validate a DAT file for Slippi compatibility.

    Args:
        dat_path: Path to the DAT file to validate
        auto_fix: If True, write the corrected file. If False, only report.
        create_backup: If True and auto_fix is True, back up before writing

    Returns:
        dict with keys:
            - is_valid: True if the file is Slippi-safe (or was made safe)
            - needs_fix: True if the file needed fixes
            - fix_applied: True if fixes were written
            - backup_path: Path to backup if created
            - output: Validator notes
    """
    dat_path = Path(dat_path).resolve()
    if not dat_path.exists():
        return _result(output=f"Error: File {dat_path} not found")

    # Same gate the original applied: Pl-prefixed .dat/.usd, excluding AJ.
    if not costume_validator.is_costume_file(dat_path):
        return _result(output=f"{dat_path.name} is not a costume DAT -- skipped")

    try:
        buf = bytearray(dat_path.read_bytes())
        needs_fix, notes = costume_validator.check_bytes(buf, apply_fix=True)
    except Exception as e:  # noqa: BLE001 - callers treat any failure as "error"
        return _result(output=f"ERROR: validator exception: {type(e).__name__}: {e}")

    result = _result(is_valid=not needs_fix, needs_fix=needs_fix,
                     output="\n".join(notes))

    if needs_fix and auto_fix:
        if create_backup:
            backup_path = dat_path.with_suffix('.dat.backup')
            counter = 1
            while backup_path.exists():
                backup_path = dat_path.with_suffix(f'.dat.backup{counter}')
                counter += 1
            shutil.copy2(dat_path, backup_path)
            result['backup_path'] = backup_path
            print(f"Created backup: {backup_path}")

        dat_path.write_bytes(buf)
        result['fix_applied'] = True
        result['is_valid'] = True

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_costume.py <dat_file> [options]")
        print("\nOptions:")
        print("  --check-only    Only check if file is Slippi-safe, don't fix")
        print("  --auto-fix      Automatically fix issues (default: ask)")
        print("  --no-backup     Don't create backup when fixing")
        sys.exit(1)

    dat_file = sys.argv[1]
    check_only = "--check-only" in sys.argv
    auto_fix = "--auto-fix" in sys.argv
    create_backup = "--no-backup" not in sys.argv

    print(f"Validating: {dat_file}")
    print("-" * 50)

    # A plain check never touches the file, so no temp copy is needed.
    check = validate_dat_file(dat_file, auto_fix=False)

    if not check['needs_fix'] and check['is_valid']:
        print("File is Slippi-safe!")
        print(check['output'])
        return
    if not check['needs_fix']:
        print(check['output'])
        return

    print("File needs fixes to be Slippi-safe")
    print(check['output'])
    if check_only:
        return

    if not auto_fix:
        print("\nOptions:")
        print("1. Apply fixes (original will be backed up)")
        print("2. Apply fixes without backup")
        print("3. Cancel (keep original)")
        choice = input("\nEnter choice (1/2/3): ").strip()
        if choice == "1":
            auto_fix, create_backup = True, True
        elif choice == "2":
            auto_fix, create_backup = True, False
        else:
            print("Cancelled. File unchanged.")
            return

    fixed = validate_dat_file(dat_file, auto_fix=True, create_backup=create_backup)
    if fixed['fix_applied']:
        print("Fixes applied.")
        if fixed['backup_path']:
            print(f"Backup: {fixed['backup_path']}")
    else:
        print("No fixes applied.")
        print(fixed['output'])


if __name__ == "__main__":
    main()
