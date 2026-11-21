"""Repo path constants shared by every Python test (the one place the depth is computed).

This file lives at <repo>/tests/paths.py. conftest.py in tests/backend re-exports
these and provides the `repo_paths` fixture.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / 'app'
BACKEND = APP / 'backend'
