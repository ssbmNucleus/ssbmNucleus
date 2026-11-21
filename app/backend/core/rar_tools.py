"""Reading .rar archives through the bundled UnRAR tool.

Python has no RAR reader and there is no usable pure-Python one, so .rar
support leans on RARLAB's UnRAR binary in `utility/unrar*` (freeware, may be
redistributed inside other software packages -- see THIRD_PARTY_NOTICES.md).
The `rarfile` package is only a driver for it.

Nothing downstream of the import entry point ever sees a .rar:
`rar_to_temp_zip()` repacks one into a temp zip exactly as
`_convert_7z_to_temp_zip()` does for .7z, so detection, the Slippi pre-check
and every installer keep working on plain zips.
"""

import importlib.util
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from core.config import RESOURCES_DIR
from core.safe_archive import ArchiveLimits, DEFAULT_LIMITS, safe_extract_rar

logger = logging.getLogger(__name__)

# rarfile is imported lazily so a build without it degrades to "RAR not
# supported" instead of failing at startup, matching how py7zr is handled.
HAS_RARFILE = importlib.util.find_spec("rarfile") is not None


def _bundled_unrar():
    """Where this platform's UnRAR ships, mirroring utility/xdelta*."""
    if os.name == "nt":
        return "unrar", "UnRAR.exe"
    return ("unrar-mac" if sys.platform == "darwin" else "unrar-linux"), "unrar"


def get_unrar_exe():
    """The bundled UnRAR path, or the bare name to try on PATH.

    Tools live under RESOURCES_DIR in every layout (dev, frozen, packaged);
    PROJECT_ROOT can be redirected to a separate data root and is not it.
    """
    sub, name = _bundled_unrar()
    executable = RESOURCES_DIR / "utility" / sub / name
    if executable.exists():
        # electron-builder and the tarball/zip round trips can drop the
        # execute bit; restoring it here beats failing the first import.
        if os.name != "nt" and not os.access(executable, os.X_OK):
            try:
                executable.chmod(executable.stat().st_mode | 0o111)
            except OSError:
                pass
        return executable
    return "unrar"


def rar_available():
    """True when a .rar can actually be opened on this machine."""
    if not HAS_RARFILE:
        return False
    executable = get_unrar_exe()
    return isinstance(executable, Path) or bool(shutil.which(str(executable)))


def _rarfile():
    """Import rarfile on demand, pointed at our UnRAR."""
    import rarfile
    rarfile.UNRAR_TOOL = str(get_unrar_exe())
    return rarfile


def rar_to_temp_zip(archive_path, *, limits: ArchiveLimits = DEFAULT_LIMITS):
    """Repack a .rar into a temp zip. Returns the zip path (caller owns it),
    or None when RAR support is unavailable or the archive can't be read --
    callers keep the original path and fall through to the normal
    "could not detect" handling."""
    if not rar_available():
        return None
    zip_path = None
    try:
        rarfile = _rarfile()
        with tempfile.TemporaryDirectory(prefix="rar_convert_") as tmp_dir:
            with rarfile.RarFile(archive_path) as rf:
                # rarfile stops quietly at a header it can't parse, so a RAR
                # signature over garbage reads as an EMPTY archive. With nothing
                # read there is nothing to salvage: refuse it rather than repack
                # an empty zip that surfaces as "could not detect mod type".
                # Encrypted headers read the same way: no error, no members.
                if not rf.infolist() and (rf.strerror() or rf.needs_password()):
                    raise rarfile.BadRarFile(rf.strerror() or "archive headers are encrypted")
                safe_extract_rar(rf, tmp_dir, limits=limits)
            fd, zip_path = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            root = Path(tmp_dir)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                for p in sorted(root.rglob("*")):
                    if p.is_file():
                        zf.write(p, p.relative_to(root).as_posix())
        return zip_path
    except Exception as e:
        logger.warning(f"RAR conversion failed for {archive_path}: {e}")
        if zip_path:
            try:
                os.unlink(zip_path)
            except OSError:
                pass
        return None
