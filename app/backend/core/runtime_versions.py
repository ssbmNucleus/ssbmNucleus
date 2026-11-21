"""Release runtime floors; shared by build preflight and the frozen smoke test."""
import re
import sys

WINDOWS_PYTHON_MIN = (3, 13, 17)
# macOS (Homebrew python@3.12) and Linux (CPython built into the runner's tool
# cache, since Ubuntu's 3.12.3 lacks it) freeze 3.12. 3.12.15 and 3.13.17 carry
# the zipfile decompression bound (CVE-2026-15310) and the other October fixes.
UNIX_PYTHON_MIN = {(3, 12): (3, 12, 15), (3, 13): (3, 13, 17)}
# 44.10.2: Node 24.22.2 (Node2Shell, CVE-2026-111497, fixed in 24.22.1). 44.11.5: the
# Chromium, V8, ANGLE, Dawn, Skia, PDFium, FFmpeg and WebRTC backports of 2026-11-10 to 11-19.
ELECTRON_MIN = (44, 11, 5)


def check_windows_python(version=None, platform=None):
    version = tuple(sys.version_info[:3] if version is None else version)
    platform = sys.platform if platform is None else platform
    if platform == "win32" and (version[:2] != (3, 13) or version < WINDOWS_PYTHON_MIN):
        raise RuntimeError(
            "Windows release builds require Python 3.13.17 or newer 3.13.x; "
            f"got {'.'.join(map(str, version))}. Recreate the build venv with the patched interpreter."
        )


def check_unix_python(version=None, platform=None):
    version = tuple(sys.version_info[:3] if version is None else version)
    platform = sys.platform if platform is None else platform
    floor = UNIX_PYTHON_MIN.get(version[:2])
    if platform in ("darwin", "linux") and (floor is None or version < floor):
        raise RuntimeError(
            "macOS/Linux release builds require Python 3.12.15+ or 3.13.17+; "
            f"got {'.'.join(map(str, version))}. Build from the patched interpreter, not the system one."
        )


def check_electron(version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeError(f"A stable Electron 44.x runtime is required; got {version!r}")
    parts = tuple(map(int, version.split(".")))
    if parts[0] != 44 or parts < ELECTRON_MIN:
        raise RuntimeError(f"Electron 44.11.5 or newer 44.x is required; got {version}")
