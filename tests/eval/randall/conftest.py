"""Put eval/randall (the harness modules these tests import by bare name) and the backend on sys.path.

The tests moved out of eval/randall, so pytest no longer inserts that folder itself.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # <repo>/tests/eval/randall/conftest.py
for folder in (REPO / 'eval' / 'randall', REPO / 'app' / 'backend'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
