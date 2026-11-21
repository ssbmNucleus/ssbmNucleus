"""`nucleus_api/API.md` must BE `nucleus_api.gendocs.build()`, character for character.

The review
(`backend/artifacts/harness-experiment-20260922/ASTRA-INTEGRATION.md` §4)
found `a31bb42c`'s committed `API.md` advertising `codes.address_conflicts`,
`codes.write_targets` and a third `merge()` argument that the committed
`codes.py` did not have. The existing contract test
(`tests/backend/test_nucleus_api_contract.py`) regenerates the document and inspects
what it generated — so it agreed with itself and never looked at the file on
disk. That file is what a scripting model reads, and it was fiction.

This is the missing half: regenerate, and compare to the checked-in bytes.
"""
from tests.paths import BACKEND
import difflib
from pathlib import Path

import pytest

API_MD = BACKEND / "nucleus_api" / "API.md"


def _gendocs():
    """Imported inside the tests on purpose.

    `nucleus_api/__init__` imports every submodule, so importing it at module
    scope turns another builder's half-saved file into a COLLECTION error that
    takes the whole run down. Here it is one failing test in one file.
    """
    from nucleus_api import gendocs
    return gendocs


def _drift():
    committed = API_MD.read_text(encoding="utf-8")
    generated = _gendocs().build()
    if committed == generated:
        return None
    return "\n".join(difflib.unified_diff(
        committed.splitlines(), generated.splitlines(),
        fromfile="nucleus_api/API.md (committed)",
        tofile="nucleus_api.gendocs.build() (regenerated)",
        lineterm="", n=2))


def test_api_md_exists_and_is_not_empty():
    assert API_MD.is_file(), API_MD
    assert len(API_MD.read_text(encoding="utf-8")) > 1000


def test_gendocs_build_is_deterministic():
    """Equality is only meaningful if the generator does not wobble."""
    gendocs = _gendocs()
    assert gendocs.build() == gendocs.build()


def test_api_md_equals_the_regenerated_document():
    drift = _drift()
    assert drift is None, (
        "nucleus_api/API.md is not what gendocs.build() produces. The file is "
        "what a scripting model reads, so a stale one advertises functions "
        "that do not exist. Regenerate it:\n\n" + drift)
