"""Where the harness scripts find what they need. Each is run as a script from the app's backend folder.

NUCLEUS_REPO   the app checkout (its app/backend is imported from)
ULTIMATE_DUMP  the Ultimate game files, for a fighter from Ultimate
SSBH_DATA_PY   the folder ssbh_data_py is importable from, when it is not installed
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT_REPO = HERE.parents[1]
if not os.environ.get('NUCLEUS_REPO'):
    raise SystemExit('NUCLEUS_REPO must name the app checkout')
BACKEND = Path(os.environ['NUCLEUS_REPO']) / 'app' / 'backend'
ULTIMATE = Path(os.environ.get('ULTIMATE_DUMP') or '.')
SSBH = Path(os.environ.get('SSBH_DATA_PY') or ULTIMATE / 'pydeps' / 'ssbh_data_py-0.9.1')
