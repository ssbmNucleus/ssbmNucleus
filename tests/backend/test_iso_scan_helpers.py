"""
Tests for the ISO-scan error helpers (core.helpers): classifying a non-vanilla/
m-ex build as an expected incompatibility (bulk scans skip it silently) vs. a
real failure, and the concise user-facing message.
"""
from tests.paths import BACKEND
import sys
from pathlib import Path

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from core.helpers import is_incompatible_iso_error, friendly_iso_open_error

# Realistic MexCLI import-iso output for a 20XX disc: progress block + error
# block with a stack trace (multiple pretty-printed JSON objects).
INCOMPAT_OUTPUT = '''{
  "status": "extracting",
  "message": "Extracting ISO... (this may take 1-2 minutes)"
}
{
  "success": false,
  "error": "Failed to import ISO: ISO is not vanilla (DOL patch failed) and has no MxDt.dat (not a m-ex build). Original error: Failed to apply DOL Patch",
  "stackTrace": "   at MexCLI.Commands.ImportIsoCommand.Execute(String[] args)"
}'''

GENERIC_OUTPUT = '{"success": false, "error": "Disc read error: bad sector"}'

# mexLib NullReferenceException on a build it can't parse (e.g. MEME builds) —
# should be treated as an incompatible ISO (quiet skip), not a red error.
NRE_OUTPUT = ('{"success": false, "error": "Failed to import ISO: '
              'Object reference not set to an instance of an object."}')


def test_incompatible_build_is_detected():
    assert is_incompatible_iso_error(INCOMPAT_OUTPUT) is True


def test_null_reference_crash_is_treated_as_incompatible():
    assert is_incompatible_iso_error(NRE_OUTPUT) is True


def test_generic_error_is_not_incompatible():
    assert is_incompatible_iso_error(GENERIC_OUTPUT) is False


def test_empty_output_is_not_incompatible():
    assert is_incompatible_iso_error('') is False


def test_friendly_message_for_incompatible_points_to_other_targets():
    msg = friendly_iso_open_error(INCOMPAT_OUTPUT)
    assert 'vanilla or m-ex' in msg
    assert 'Character skins' in msg and 'DAS stage variants' in msg
    assert 'stackTrace' not in msg  # never leak the raw stack trace


def test_friendly_message_for_generic_error_is_concise():
    msg = friendly_iso_open_error(GENERIC_OUTPUT)
    assert msg == 'Disc read error: bad sector'


def test_friendly_message_fallback_when_unparseable():
    assert friendly_iso_open_error('') == 'Failed to open ISO.'
