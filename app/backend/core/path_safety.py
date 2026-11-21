"""Portable path validation for caller-controlled file and directory names."""

from pathlib import Path, PurePosixPath, PureWindowsPath


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
    ``\\?\UNC\host\...``, ``\\.\device``, ``//host/share`` and ``file://host/...``. A mapped drive letter is
    the user's own choice and is not refused here.
    """
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str):
        return False
    text = value.strip().strip('"\'').strip()
    flat = text.replace("\\", "/")
    if flat.startswith("//"):
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
