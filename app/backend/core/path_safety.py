"""Portable path validation for caller-controlled file and directory names, and the gate every path a request or
a tool argument names goes through before it is opened or run (:func:`local_path`)."""

import os
import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath


_WINDOWS_RESERVED_STEMS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def portable_path_parts(value, *, field="path"):
    """Return normalized relative parts, rejecting POSIX and Windows escapes."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{field} must be a nonempty string")

    windows_path = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    parts = tuple(part for part in posix_path.parts if part not in ("", "."))
    has_nonportable_component = any(
        part.endswith((" ", "."))
        or any(ord(char) < 32 for char in part)
        or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_STEMS
        for part in parts
    )
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or posix_path.is_absolute()
        or not parts
        or ".." in parts
        or any(":" in part for part in parts)
        or has_nonportable_component
    ):
        raise ValueError(f"{field} must be a relative path")
    return parts


def validate_path_segment(value, *, field="name"):
    """Validate and return one portable filename/directory segment."""
    parts = portable_path_parts(value, field=field)
    if len(parts) != 1 or parts[0] != value:
        raise ValueError(f"{field} must be a single path segment")
    return value


def resolve_under_root(root, relative_path, *, field="path"):
    """Resolve a portable relative path and enforce filesystem confinement."""
    root = Path(root).resolve()
    target = root.joinpath(*portable_path_parts(relative_path, field=field)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes its allowed root") from exc
    return target


def is_network_path(value):
    r"""True when ``value`` names a file on another computer (or a raw device), not one on this computer.

    Opening such a path makes Windows connect to that host and offer the user's NTLM credentials, and running a
    program from one runs the host's code. Caught: ``\\host\share``, ``\\host@SSL\...`` (WebDAV),
    ``\\?\UNC\host\...``, ``\\.\device``, the NT namespace ``\??\`` (``\??\UNC\host\...`` reaches a share and
    ``\??\C:\...`` a raw path, and neither looks absolute to ``pathlib``), ``//host/share`` and
    ``file://host/...``, with either slash. A mapped drive letter is the user's own choice and is not refused here.
    """
    if isinstance(value, PurePath):
        value = str(value)
    if not isinstance(value, str):
        return False
    text = value.strip().strip('"\'').strip()
    flat = text.replace("\\", "/")
    if flat.startswith("//") or flat.startswith("/??/"):
        return True
    if flat[:5].lower() == "file:":
        rest = flat[5:]
        if rest.startswith("//"):
            host = rest[2:].split("/", 1)[0]
            return host.lower() not in ("", "localhost")
    return False


def refuse_network_path(value, *, field="path"):
    """Raise ValueError when ``value`` is a network or device path (:func:`is_network_path`); else return it."""
    if is_network_path(value):
        raise ValueError(f"{field} is a network path ({str(value).strip()[:200]}). Nucleus only opens files and "
                         "folders on this computer: copy it here first.")
    return value


# ---------------------------------------------------------------- the request-path gate

class NotLocalPath(ValueError):
    """A path from a request or a tool argument that is not a plain absolute path on this computer.

    ``reason`` is ``'network'`` (another computer, a device or the NT namespace, a ``file:`` URL) or ``'form'``
    (empty, relative, drive-relative, a control character, too long).
    """

    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


MAX_REQUEST_PATH = 4096
_DRIVE_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/]")

#: Request keys that always carry a path on this computer that the backend later opens, writes or runs. app.py
#: refuses a request whose JSON body, form or query string has one of these that fails :func:`local_path` (an
#: empty value is left to the route), so no route can forget the check; routes that run something still check
#: again themselves.
REQUEST_PATH_KEYS = ("slippiPath", "slippiDolphinPath", "vanillaIsoPath", "isoPath", "exportedIsoPath",
                     "moddedIsoPath", "texturePackPath", "kitPath", "gccBin", "tablePath", "destination")


def local_path(value, *, field="path", posix=None):
    r"""The one gate for a path a request or a tool argument names: its text, or :class:`NotLocalPath`.

    Accepted: a drive-letter absolute path (``C:\...`` or ``C:/...``), on every platform (a WSL dev backend
    converts one); where ``posix`` (by default: not Windows) also a POSIX absolute path (``/...``, never ``//``).
    Refused: ``\\host\share`` and ``//host`` (another computer), the device and NT namespaces ``\\?\``,
    ``\\.\`` and ``\??\`` (``\??\UNC\host@SSL\DavWWWRoot\x.iso`` reaches a WebDAV share past a plain UNC check),
    any ``file:`` URL, relative and drive-relative paths (``x``, ``\x``, ``C:x``), NUL and other control
    characters, and anything over :data:`MAX_REQUEST_PATH` characters. Slashes are normalised first, so mixed
    forms (``\/host``, ``/??/``) are caught the same way. Surrounding whitespace and one pair of double quotes
    (Explorer's "Copy as path") are dropped from the text returned.
    """
    if posix is None:
        posix = os.name != "nt"
    if isinstance(value, PurePath):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise NotLocalPath(f"{field} must be a path on this computer.", "form")
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    if len(text) > MAX_REQUEST_PATH or any(ord(char) < 32 for char in text):
        raise NotLocalPath(f"{field} is not a usable path.", "form")
    flat = text.replace("\\", "/")
    if is_network_path(text) or flat[:5].lower() == "file:":
        raise NotLocalPath(f"{field} is a network path or a device path ({text[:200]}). Nucleus only opens files "
                           "and folders on this computer: copy it here first.", "network")
    if _DRIVE_ABSOLUTE.match(text):
        return text
    if posix and text.startswith("/"):
        return text
    raise NotLocalPath(f"{field} must be a full path on this computer, such as C:\\Games\\... ({text[:200]}).",
                       "form")


def resolve_local(value, *, field="path", posix=None, strict=False):
    """``value`` through :func:`local_path`, resolved (junctions and links followed), and the result checked
    again: a local folder that is a junction to a share or a device is refused too, and so is a mapped network
    drive (it resolves to its share). Returns a Path."""
    resolved = Path(local_path(value, field=field, posix=posix)).resolve(strict=strict)
    local_path(str(resolved), field=field, posix=posix)
    return resolved


def request_path_refusal(*sources):
    """The first value under a :data:`REQUEST_PATH_KEYS` key in these mappings (a JSON body, the query string)
    that :func:`local_path` refuses, as ``(key, NotLocalPath)``; None when there is none. Empty values and
    non-mappings are skipped: whether a path is required is the route's business."""
    for source in sources:
        if not hasattr(source, "get"):
            continue
        for key in REQUEST_PATH_KEYS:
            value = source.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            try:
                local_path(value, field=key)
            except NotLocalPath as refused:
                return key, refused
    return None
