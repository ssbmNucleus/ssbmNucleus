"""The FOBJ track reader (dev only: nothing here ships, and the app never imports it).

``fobj_reader`` decodes figatree tracks; the Watch Lite audit in ``tools/liteaudit/`` reads it. The
fighter-rig readers that used to sit beside it live in ``tools/fighterport/fighter_port/compat/``.
See README.md.

It reads DATs with the app's ``vault.echo``, so importing the package puts ``app/backend`` on sys.path.
"""
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[2] / 'app' / 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
