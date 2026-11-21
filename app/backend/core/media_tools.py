"""Finding ffmpeg for recordings and video exports.

Windows installers ship a pinned GPL ffmpeg under `utility/ffmpeg/bin/`
(utility/ffmpeg.manifest.json; reproduce it with
`python tools/build/fetch_ffmpeg.py`). It is an unmodified upstream binary
run as a separate process, the same posture as the model import's Blender. Mac and
Linux builds do not bundle one yet, so there it is whatever is on PATH.

ffprobe is not shipped and nothing calls it: a recording's length comes from
the game or its audio dump (tracker/replays/recording.py), so the app runs
the same with or without one on PATH.
"""

import os
import shutil

from core.config import RESOURCES_DIR


def _bundled(name):
    """This platform's bundled copy of `name`, or None."""
    if os.name != "nt":
        return None
    executable = RESOURCES_DIR / "utility" / "ffmpeg" / "bin" / f"{name}.exe"
    return executable if executable.is_file() else None


def get_ffmpeg():
    """Path to an ffmpeg to run: the bundled one, else PATH, else None."""
    bundled = _bundled("ffmpeg")
    return str(bundled) if bundled else shutil.which("ffmpeg")
