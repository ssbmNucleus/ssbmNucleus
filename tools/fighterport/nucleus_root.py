"""Locations for Nucleus's developer-only fighter-port engine."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("NUCLEUS_REPO") or HERE.parents[1]).resolve()
APP = REPO / "app"
BACKEND = APP / "backend"
if not BACKEND.is_dir():
    raise FileNotFoundError(f"NUCLEUS_REPO has no app/backend: {REPO}")
