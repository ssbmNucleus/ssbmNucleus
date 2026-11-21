"""The ship guard's embedded_roots are a hand-maintained PROXY for what
mex_backend.spec actually freezes into the exe. A proxy that drifts is worse
than none: it either hides a real leak or reports source-only leftovers (stale
__pycache__, scratch files) as shipped content, which trains people to ignore
the report.

These tests pin the one root whose include list can drift silently --
backend/data, where the spec names files one by one -- and prove the filter
does what the rules claim.
"""

from tests.paths import APP
import ast
import importlib.util
import json
from pathlib import Path

import pytest

NUCLEUS_ROOT = APP
SPEC = NUCLEUS_ROOT.parent / 'tools' / 'build' / "mex_backend.spec"
RULES = NUCLEUS_ROOT.parent / 'tools' / 'build' / "ship_rules.json"
GUARD = NUCLEUS_ROOT.parent / 'tools' / 'build' / "ship_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("ship_guard_under_test", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spec_expected_backend_data():
    """Read mex_backend.spec's `expected_backend_data` tuple without executing it.

    The spec imports PyInstaller at module scope, so it cannot simply be
    imported here.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "expected_backend_data" in targets:
            return tuple(ast.literal_eval(node.value))
    pytest.fail("expected_backend_data not found in mex_backend.spec")


def _backend_data_rule():
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    for ent in rules["embedded_roots"]["roots"]:
        if ent["src"] == "backend/data":
            return ent
    pytest.fail("ship_rules.json has no embedded root for backend/data")


def test_backend_data_include_matches_the_spec():
    """The guard must claim exactly the files the spec freezes -- no more, no less."""
    rule = _backend_data_rule()
    from_rules = sorted(rule.get("include") or [])
    from_spec = sorted(f"backend/data/{name}" for name in _spec_expected_backend_data())
    assert from_rules == from_spec, (
        "ship_rules.json embedded_roots backend/data include has drifted from "
        "mex_backend.spec's expected_backend_data. Update both together."
    )


def test_include_filter_drops_source_only_leftovers(tmp_path):
    """A stale .pyc beside the bundled JSON must not be reported as shipped."""
    guard = _load_guard()
    rule = _backend_data_rule()

    root = tmp_path / "data"
    (root / "__pycache__").mkdir(parents=True)
    (root / "texture_filename_table_seed.json").write_text("{}", encoding="utf-8")
    (root / "vanilla_geom_hashes.json").write_text("{}", encoding="utf-8")
    (root / "__pycache__" / "vanilla_geom_hashes.cpython-313.pyc").write_bytes(b"\x00" * 16)
    (root / "scratch_notes.txt").write_text("dev scratch", encoding="utf-8")

    inventory = {}
    guard._scan_tree(
        root,
        "inside mex_backend: backend/data",
        [],
        {},
        inventory,
        prefix="backend/data",
        exclude=rule.get("exclude"),
        include=rule.get("include"),
    )

    label = "inside mex_backend: backend/data"
    counted = sum(count for (lbl, _top), (count, _size) in inventory.items() if lbl == label)
    assert counted == 2, f"expected only the two bundled JSON files, got {counted}"


def test_include_filter_still_sees_the_files_that_do_ship(tmp_path):
    """The filter must not be able to quiet the tree entirely."""
    guard = _load_guard()
    rule = _backend_data_rule()

    root = tmp_path / "data"
    root.mkdir(parents=True)
    for name in _spec_expected_backend_data():
        # The tuple carries nested paths too (menus/compatibility_manifest.json),
        # so make the subfolder before writing into it.
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("{}", encoding="utf-8")

    inventory = {}
    guard._scan_tree(
        root,
        "inside mex_backend: backend/data",
        [],
        {},
        inventory,
        prefix="backend/data",
        exclude=rule.get("exclude"),
        include=rule.get("include"),
    )

    label = "inside mex_backend: backend/data"
    counted = sum(count for (lbl, _top), (count, _size) in inventory.items() if lbl == label)
    assert counted == len(_spec_expected_backend_data())
