"""Dev-only Python beside the Dolphin harness (nothing here ships, and the app never imports it).

The RAM evidence readers ``contacts`` (hit and hurt capsules, hit victims) and ``input_evidence``
(the fighter's pad and stick state), ``owned_session`` (closing only the Dolphin a capture started)
and the memory-input parity worker ``verify_memory_input.py``. They stand on the app's in-game
engine (``shared.ingame``), so importing the package puts ``app/backend`` on sys.path. See README.md.
"""
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[2] / 'app' / 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
