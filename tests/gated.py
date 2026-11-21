"""Tests that also cover code a checkout can leave out.

The public source drop (tools/public_drop.py) leaves the unreleased features' code out
(core/build_smoke.py ``_GATED_PACKAGES``: the Tracker coach and Combo Video), and their
gates then read closed (core.gates.present). Test files that only test that code are left
out with it; a test of shipped code that also touches it is marked ``@needs('<gate>')``
and skips there, so a public clone's test run passes.
"""
import sys

import pytest

from tests.paths import BACKEND

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core import gates  # noqa: E402


def present(gate: str) -> bool:
    """Whether gate `gate`'s code is in this checkout."""
    return gates.present(gate)


def needs(gate: str):
    """Skip the test where this checkout leaves gate `gate`'s code out."""
    return pytest.mark.skipif(not gates.present(gate),
                              reason=f'this checkout leaves out the {gate} code (public source drop)')
