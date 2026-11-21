"""Tests that read data the public source drop leaves out.

The public copy (tools/public_drop.py: NUCLEUS_EXCLUDES plus ship_rules.json's scrub rules)
leaves out Melee-derived and third-party data: the vanilla HUD manifests, the DAS loader
patches, csp_data, the stage simulation tables and more. A test that reads
such data is marked here with the exact path it reads and skips where that path is not on
disk, so a public clone's test run passes. The private checkout has the data and runs the test
exactly as before. Mark the data, never "is this the public repo".

Data a clone gets later, from `python tools/build/fetch_native.py all` or at first-run setup
(a vanilla ISO, Slippi Dolphin), is not on the drop's exclude list; such tests skip with their
own reason. The drop's own tests (kept private with the drop tooling) check that every path
named here is tracked there, so the private checkout runs the test, and left out by the drop,
so the reason is true.
"""
from __future__ import annotations

import pytest

from tests.paths import BACKEND, REPO

#: The vanilla HUD slot manifest the Menus tab's percent/Ready-Go code reads before the
#: first-run derivation (shared/vanilla_extract/menu_refs.py hud_dir()).
HUD_MANIFEST = 'app/backend/assets/hud_vanilla/manifest_usd.json'


def missing(*paths: str) -> list[str]:
    """The repo-relative `paths` that are not on disk."""
    return [p for p in paths if not (REPO / p).exists()]


def _reason(paths, why: str) -> str:
    return f"needs {', '.join(paths)}, which the public source drop leaves out ({why})"


def left_out(*paths: str, why: str):
    """Mark a test that reads repo-relative `paths`: it skips where any is not on disk."""
    gone = missing(*paths)
    return pytest.mark.skipif(bool(gone), reason=_reason(gone or paths, why))


def require(*paths: str, why: str):
    """Inside a test: skip from here on where any of `paths` is not on disk (what the test
    checked before this line still ran)."""
    __tracebackhide__ = True        # the skip report names the test's line, not this one
    gone = missing(*paths)
    if gone:
        pytest.skip(_reason(gone, why))


def hud_manifest_present() -> bool:
    """Whether the HUD manifest the menus code reads is on disk: the first-run derived set
    when it exists, else the tracked HUD_MANIFEST."""
    import sys
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from shared.vanilla_extract.menu_refs import hud_dir
    return (hud_dir() / 'manifest_usd.json').is_file()


def needs_hud_manifest():
    """Mark a test whose HUD mod handling reads the vanilla slot manifest (which slots are
    digits and which are the READY/GO words). Without one, as in a public clone before the
    first-run derivation, every slot reads as a percent slot."""
    return pytest.mark.skipif(
        not hud_manifest_present(),
        reason=_reason([HUD_MANIFEST], 'vanilla HUD slot manifest; a clone derives one at first-run setup'))
