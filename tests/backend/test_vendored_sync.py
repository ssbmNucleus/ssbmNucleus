"""Pin the vendored-from-monorepo modules to their upstreams (register item 6).

``tracker/stats/analyzer.py`` is a straight copy of
``tools/rank-baselines/analyzer_v2.py`` plus a vendoring header, and
``pack_math.py`` carries the aggregation functions out of
``build_packs_v2.py``. The shipped Stats page and the committed baseline packs
must agree on every stat definition, so a change to either side has to land on
both. Comparison is on the AST (docstrings dropped), so line endings and the
header text are free; anything else is drift.

Skips when the monorepo half isn't checked out (public shell, packaged build).
"""
from tests.paths import BACKEND, REPO
import ast
from pathlib import Path

import pytest

PIPELINE = REPO / "tools" / "rank-baselines"

# Thresholds the app sets lower on purpose: the player's own corpus is small,
# the bundled baselines are not (pack_math.py says so inline).
PACK_MATH_INTENTIONAL = {"MIN_GAMES_MATCHUP", "MIN_GAMES_STAGE"}


def _module(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
        and isinstance(node.value.value, str)


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and _is_docstring(body[0]):
            body.pop(0)
    return tree


def _top_level(tree):
    """name -> dump for every top-level def/class/simple assignment."""
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = ast.dump(node.value)
    return out


pytestmark = pytest.mark.skipif(not PIPELINE.is_dir(), reason="tools/rank-baselines/ not checked out")


def test_analyzer_is_a_straight_copy():
    ours = _strip_docstrings(_module(BACKEND / "tracker" / "stats" / "analyzer.py"))
    theirs = _strip_docstrings(_module(PIPELINE / "analyzer_v2.py"))
    assert ast.dump(ours) == ast.dump(theirs), \
        "tracker/stats/analyzer.py drifted from tools/rank-baselines/analyzer_v2.py — re-copy and bump ANALYZER_VERSION"


def test_pack_math_matches_build_packs():
    ours = _top_level(_strip_docstrings(_module(BACKEND / "tracker" / "stats" / "pack_math.py")))
    theirs = _top_level(_strip_docstrings(_module(PIPELINE / "build_packs_v2.py")))
    drifted = sorted(name for name, dump in ours.items()
                     if name not in PACK_MATH_INTENTIONAL and theirs.get(name) != dump)
    assert not drifted, f"pack_math.py drifted from build_packs_v2.py in: {drifted}"
    # every name pack_math vendors must still exist upstream
    missing = sorted(name for name in ours if name not in theirs)
    assert not missing, f"pack_math.py defines names build_packs_v2.py no longer has: {missing}"
