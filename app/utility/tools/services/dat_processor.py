"""Slippi safety check for a costume DAT (validate_for_slippi), wrapping the processor's validate_costume."""
import sys
import logging
from pathlib import Path

# Add the sibling processor tools to path
TOOLS_DIR = Path(__file__).parent.parent / 'processor'
sys.path.insert(0, str(TOOLS_DIR))

from detect_character import DATParser
from validate_costume import validate_dat_file

logger = logging.getLogger(__name__)


def validate_for_slippi(file_path, auto_fix=False):
    """
    Validate .dat file for Slippi compatibility using copy→test→replace workflow.

    Args:
        file_path: Path to the .dat file
        auto_fix: If True, apply fixes to the original file. If False, only check.

    Returns: dict with validation results
    """
    import shutil
    import tempfile

    try:
        import hashlib
        file_path = Path(file_path)

        # Get hash of original file BEFORE any processing
        with open(file_path, 'rb') as f:
            original_hash = hashlib.md5(f.read()).hexdigest()

        # CRITICAL: Validator needs proper Melee character filename (e.g., PlFxGr.dat)
        # Get the proper filename based on detected character + color
        parser = DATParser(str(file_path))
        parser.read_dat()
        proper_filename = parser.get_character_filename()

        if not proper_filename:
            logger.warning(f"Slippi validation skipped for {file_path}: could not determine character filename")
            return {
                'is_valid': False,
                'needs_fix': False,
                'fix_applied': False,
                'slippi_safe': False,
                'error': 'Could not determine proper character filename for validation',
                'output': 'Could not determine proper character filename for validation'
            }

        # Always use copy→test workflow with proper character code filename.
        # The copy goes in its own temp dir so it can keep that name verbatim:
        # the validator's gate only accepts Pl-prefixed non-AJ stems, so a
        # disambiguating prefix like `_temp_PlMsNr.dat` gets silently skipped.
        temp_dir = Path(tempfile.mkdtemp(prefix='slippi_check_'))
        temp_check_file = temp_dir / f"{proper_filename}.dat"

        shutil.copy2(file_path, temp_check_file)

        try:
            # Fix the copy, never the original. auto_fix MUST be forwarded:
            # validate_dat_file only writes the corrected bytes when it is set,
            # so hardcoding False here left the copy untouched and made every
            # "Fix" a silent no-op that still reported success.
            result = validate_dat_file(temp_check_file, auto_fix=auto_fix, create_backup=False)

            is_valid = result.get('is_valid', False)
            needs_fix = result.get('needs_fix', False)
            fix_applied = result.get('fix_applied', False)

            # Verify original was not modified
            with open(file_path, 'rb') as f:
                original_hash_after = hashlib.md5(f.read()).hexdigest()

            if original_hash != original_hash_after:
                logger.error(f"ORIGINAL FILE WAS MODIFIED! Before: {original_hash}, After: {original_hash_after}")
                return {
                    'is_valid': False,
                    'needs_fix': False,
                    'fix_applied': False,
                    'slippi_safe': False,
                    'error': 'Original file was modified during validation',
                    'output': f"ERROR: Original file was modified during validation!\nBefore: {original_hash}\nAfter: {original_hash_after}"
                }

            # Only claim a fix when the validator actually wrote one. It reports
            # fix_applied=False when the skeleton diverges too far to correct
            # bone-for-bone, and copying back then would be a no-op sold as a fix.
            if fix_applied:
                # Copy the fixed version back to the original file
                shutil.copy2(temp_check_file, file_path)
                logger.info(f"Copied fixed DAT from {temp_check_file} to {file_path}")

                return {
                    'is_valid': True,  # It's now valid after fixing
                    'needs_fix': needs_fix,  # It did need fixes
                    'fix_applied': True,
                    'slippi_safe': True,
                    'output': result.get('output', '')
                }
            else:
                # A validator that never reached a verdict reports neither valid
                # nor needing a fix (file unreadable, symbol unmatched, crashed).
                # That is NOT the same as "unsafe", but it used to be reported
                # identically -- so the UI offered a Fix that could not do
                # anything, and clicking it changed nothing and said nothing.
                # Name the state so callers can tell the user what went wrong.
                error = None
                if not is_valid and not needs_fix:
                    error = (result.get('output') or 'Validation did not complete').strip()
                    logger.warning(f"Slippi validation reached no verdict for {file_path}: {error}")

                # Just return check results without modifying original
                return {
                    'is_valid': is_valid,
                    'needs_fix': needs_fix,
                    'fix_applied': False,
                    'slippi_safe': is_valid and not needs_fix,
                    'error': error,
                    'output': result.get('output', '')
                }
        finally:
            # Clean up temp check file (and the dir it lived in)
            shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        import traceback
        logger.error(f"Slippi validation failed for {file_path}: {e}\n{traceback.format_exc()}")
        return {
            'is_valid': False,
            'needs_fix': False,
            'fix_applied': False,
            'slippi_safe': False,
            'error': str(e),
            'output': str(e)
        }
