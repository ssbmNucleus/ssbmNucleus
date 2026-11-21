"""Where this library may read and write, and how that is actually enforced.

Every public function that names a file routes it through :func:`in_path` or
:func:`out_path`. Four rules, and the reasons each one exists:

1. **The root is explicit.** It comes from ``NUCLEUS_API_WORKSPACE`` or an
   installed root (:func:`use_workspace`), never from the current directory.
   A root that changes when the process happens to ``chdir`` is not a boundary,
   and a relative path that resolves against the CWD is not inside it.

2. **The root is fixed for the task.** It is resolved once per configured
   value and cached, so two calls in one operation cannot disagree about where
   the workspace is. Changing the configured value starts a new task.

3. **Absolute is not a licence.** An absolute path is accepted only when it is
   inside the workspace, and it is checked exactly as a relative one is. There
   is no "the caller gave an absolute path, so the library must have located
   it" exemption: a path this library located itself is carried as a
   :class:`TrustedPath`, an object a caller cannot produce by passing a string.

4. **Containment is verified against the open file, not the name.** The file is
   opened first, then ``fstat`` identity is compared with an independent stat
   of the resolved path, and every component between the root and the file is
   rejected if it is a symlink, junction or other reparse point - while the
   handle is held. Resolving a name and opening it afterwards are two
   operations, and a junction swapped in between would turn the second one into
   a write outside the workspace. :func:`open_input` and :func:`read_input`
   hand back the verified handle so there is no second open at all.

The vault (``app/storage``) is read-only from here as a consequence: a
caller cannot name a vault path as an input or an output even by accident.
"""
import os
from pathlib import Path


class WorkspaceError(ValueError):
    """A path was outside the workspace, or the workspace is not configured."""


#: The resolved root and the configured value it came from. Recomputed only
#: when that value changes, which is what starting a new task looks like.
_INSTALLED = {'source': None, 'root': None, 'identity': None}

_ENV = 'NUCLEUS_API_WORKSPACE'


# ---------------------------------------------------------------------------
# A path this library located itself
# ---------------------------------------------------------------------------

class TrustedPath(os.PathLike):
    """An absolute path the LIBRARY located, not one a caller named.

    The sealed copy inside a build's journal, the menu file the app itself
    found: real inputs that legitimately live outside the workspace. They are
    carried as this object rather than as a string, because a caller who passes
    a string can never turn it into one. That is the whole point - an "absolute
    means trusted" rule written as a condition is reachable from any argument;
    written as a type it is not.
    """

    __slots__ = ('_path', 'why')

    def __init__(self, path, *, why):
        candidate = Path(path)
        if not candidate.is_absolute():
            raise WorkspaceError(f'A library path must be absolute: {path}')
        if not why:
            raise WorkspaceError('Say where this path came from.')
        self._path = candidate
        self.why = why

    def __fspath__(self):
        return str(self._path)

    def __str__(self):
        return str(self._path)

    def __repr__(self):
        return f'TrustedPath({str(self._path)!r}, why={self.why!r})'

    @property
    def path(self):
        return self._path


def library_path(path, *, why):
    """Mark a path this library located as usable where a caller path is not.

    Args:
        path: the absolute path.
        why: where it came from, e.g. ``'sealed copy in the build journal'``.

    Returns:
        TrustedPath: pass it where a public function takes a path.

    Example:
        >>> library_path(sealed, why='sealed copy in the build journal')
        TrustedPath('C:/.../MnSlChr.usd', why='sealed copy in the build journal')
    """
    return TrustedPath(path, why=why)


# ---------------------------------------------------------------------------
# The root
# ---------------------------------------------------------------------------

def use_workspace(root, *, create=True):
    """Install the workspace root explicitly, for this process.

    The host calls this when it starts a task. It replaces whatever was
    installed, so it is the one supported way to move the boundary.

    Args:
        root: an absolute directory.
        create: create it when it does not exist.

    Returns:
        pathlib.Path: the resolved root.

    Raises:
        WorkspaceError: the path is not absolute, or is not a directory.

    Example:
        >>> use_workspace('C:/work/task-1')
        WindowsPath('C:/work/task-1')
    """
    resolved = _install(str(root), create=create)
    os.environ[_ENV] = str(resolved)
    _INSTALLED['source'] = str(resolved)
    return resolved


def workspace():
    r"""The folder this library reads from and writes into, and nowhere else.

    Read once from ``NUCLEUS_API_WORKSPACE`` (or :func:`use_workspace`) and
    cached until that value changes. There is deliberately no fall back to the
    current working directory: a boundary that moves with ``chdir`` is not one,
    and relative paths that resolve against the CWD are outside it by
    construction.

    Returns:
        pathlib.Path: absolute path to the workspace root.

    Raises:
        WorkspaceError: no workspace is configured.

    Example:
        >>> from nucleus_api import workspace
        >>> print(workspace())
        C:\...\workspace
    """
    source = os.environ.get(_ENV, '').strip()
    if _INSTALLED['root'] is not None and _INSTALLED['source'] == source:
        return _INSTALLED['root']
    if not source:
        raise WorkspaceError(
            f'No workspace is configured. Set {_ENV} to an absolute directory, or call '
            'nucleus_api.use_workspace(root). This library will not fall back to the '
            'current directory: that would put the boundary wherever the process happens '
            'to be.')
    root = _install(source, create=True)
    _INSTALLED['source'] = source
    return root


def _install(source, *, create):
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        raise WorkspaceError(f'The workspace must be an absolute directory: {source}')
    candidate = Path(os.path.normpath(str(candidate)))
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    if not candidate.is_dir():
        raise WorkspaceError(f'The workspace is not a directory: {candidate}')
    root = candidate.resolve()
    _INSTALLED['root'] = root
    _INSTALLED['identity'] = _identity(root)
    return root


def _identity(path):
    info = os.stat(str(path))
    return (info.st_dev, info.st_ino)


def reset_workspace():
    """Forget the installed root. For tests that move between workspaces."""
    _INSTALLED.update({'source': None, 'root': None, 'identity': None})


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

def is_reparse_point(path):
    """True when this path is a symlink, junction or other reparse point.

    A Windows junction is not a symlink and ``is_symlink()`` misses it, so the
    file attribute is read directly.
    """
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    import stat as stat_module
    if stat_module.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, 'st_file_attributes', 0) & 0x400)   # REPARSE_POINT


def _under_root(path, root, *, what):
    """Normalize ``path`` under ``root`` WITHOUT following links, or refuse.

    ``resolve()`` is not used here on purpose: it follows a junction and then
    reports where it landed, so a link pointing outside can be made to look
    like a contained path. The name is normalized textually, checked against
    the root, and every component is then examined for a reparse point.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.normpath(str(candidate)))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise WorkspaceError(
            f'{what} must live in the workspace ({root}): {candidate}') from None
    _reject_links(root, relative, what=what)
    return candidate


def _reject_links(root, relative, *, what):
    walk = root
    for part in relative.parts:
        walk = walk / part
        if is_reparse_point(walk):
            raise WorkspaceError(
                f'{what} passes through {walk}, which is a link or junction. Where it '
                'really points is not what the workspace contains, so it is refused.')


def _verify_open(handle, candidate, root, relative, *, what):
    """Confirm, with the file already open, that it IS the contained file.

    Checking a name and then opening it are two operations; between them a
    junction can be swapped in. Here the handle exists first, and the check is
    that the handle's own identity matches an independent stat of the same
    contained path, with no link anywhere along it at this instant.
    """
    opened = os.fstat(handle.fileno())
    _reject_links(root, relative, what=what)
    try:
        live = os.stat(str(candidate))
    except OSError as exc:
        raise WorkspaceError(f'{what} disappeared while it was being checked: '
                             f'{candidate}') from exc
    if (live.st_dev, live.st_ino) != (opened.st_dev, opened.st_ino):
        raise WorkspaceError(
            f'{what} is not the file it was a moment ago ({candidate}); something replaced '
            'it between the check and the open. Nothing was read.')
    if _INSTALLED['identity'] is not None and _identity(root) != _INSTALLED['identity']:
        raise WorkspaceError('The workspace directory itself was replaced while this '
                             'operation was running. Nothing was read.')


class _VerifiedInput:
    """An open, verified input file plus the path it was verified as."""

    def __init__(self, handle, path):
        self.handle = handle
        self.path = path

    def read(self):
        return self.handle.read()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.handle.close()


def open_input(path):
    """Open a caller-named input, verified through the handle.

    Prefer this over :func:`in_path` wherever the bytes are what matter: the
    file is opened once and read through that handle, so there is no window in
    which the name could come to mean a different file.

    Args:
        path: a workspace-relative path, an absolute path inside the workspace,
            or a :class:`TrustedPath` this library located.

    Returns:
        A context manager with ``.handle`` (an open binary file) and ``.path``.

    Raises:
        WorkspaceError: outside the workspace, missing, or reached through a
            link.

    Example:
        >>> with open_input('out/MnSlChr.usd') as source:
        ...     header = source.handle.read(32)
    """
    if isinstance(path, TrustedPath):
        resolved = path.path
        if not resolved.is_file():
            raise WorkspaceError(f'No such file: {resolved}')
        return _VerifiedInput(open(resolved, 'rb'), resolved)

    root = workspace()
    candidate = _under_root(path, root, what='An input')
    relative = candidate.relative_to(root)
    if not candidate.is_file():
        raise WorkspaceError(f'No such file: {candidate}')
    handle = open(candidate, 'rb')
    try:
        _verify_open(handle, candidate, root, relative, what='An input')
    except BaseException:
        handle.close()
        raise
    return _VerifiedInput(handle, candidate)


def read_input(path):
    """The bytes of a caller-named input, read through the verified handle.

    Args:
        path: as :func:`open_input`.

    Returns:
        bytes: the file's contents.

    Example:
        >>> read_input('out/MnSlChr.usd')[:4]
        b'\\x00?\\x1f\\xc5'
    """
    with open_input(path) as source:
        return source.read()


def in_path(path):
    """Resolve an input path the caller names, which must be in the workspace.

    A relative path resolves against the WORKSPACE, never the current
    directory. An absolute path is accepted only when it is inside the
    workspace, and is checked the same way. There is no exemption for paths
    that merely happen to be absolute and to exist - a path this library
    located is passed as a :class:`TrustedPath` instead.

    The file is opened and verified through its handle before this returns, so
    the answer is true at that instant; a caller that must be immune to a
    substitution afterwards should read through :func:`open_input` rather than
    opening the returned path a second time.

    Args:
        path: a workspace-relative path, an absolute path inside the workspace,
            or a :class:`TrustedPath`.

    Returns:
        pathlib.Path: the absolute existing path.

    Raises:
        WorkspaceError: missing, outside the workspace, or reached through a
            link or junction.

    Example:
        >>> in_path('out/fox.png')
        WindowsPath('C:/.../workspace/out/fox.png')
    """
    with open_input(path) as source:
        return source.path


def out_path(path, *, default_name=None, make_parents=True):
    """Resolve a caller-supplied output path inside the workspace.

    A relative path resolves against the workspace. Every component that
    already exists is checked for a link or junction, so a planted reparse
    point cannot redirect the write out of the workspace.

    Args:
        path: a workspace-relative path, or an absolute path inside the
            workspace. ``None`` uses ``default_name`` under ``out/``.
        default_name: filename used when ``path`` is None.
        make_parents: create the parent folder.

    Returns:
        pathlib.Path: the absolute, validated destination.

    Raises:
        WorkspaceError: the destination is outside the workspace, or is reached
            through a link.

    Example:
        >>> out_path('out/fox.png')
        WindowsPath('C:/.../workspace/out/fox.png')
    """
    if isinstance(path, TrustedPath):
        raise WorkspaceError('A library path is an input, not a destination.')
    root = workspace()
    if path is None:
        if not default_name:
            raise WorkspaceError('Give an output path.')
        path = Path('out') / default_name
    candidate = _under_root(path, root, what='An output')
    if make_parents:
        parent = candidate.parent
        _reject_links(root, parent.relative_to(root), what='An output')
        parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists() and is_reparse_point(candidate):
        raise WorkspaceError(f'Refusing to write through {candidate}, which is a link.')
    return candidate


def derived_output(path, suffix, *, make_parents=True):
    """A second output derived from a checked one - checked in its own right.

    An operation that validates ``out/model.zip`` and then writes
    ``out/model.dat`` beside it has written a path nothing checked. Deriving it
    here runs the same containment rules over the real destination.

    Args:
        path: the output already resolved by :func:`out_path`, or a path that
            will be.
        suffix: the new suffix, e.g. ``'.dat'``, or a full replacement name
            when it contains no leading dot.
        make_parents: create the parent folder.

    Returns:
        pathlib.Path: the absolute, validated derived destination.

    Raises:
        WorkspaceError: the derived destination escapes the workspace.

    Example:
        >>> derived_output(out_path('out/model.zip'), '.dat')
        WindowsPath('C:/.../workspace/out/model.dat')
    """
    base = Path(path)
    derived = base.with_suffix(suffix) if suffix.startswith('.') else base.with_name(suffix)
    return out_path(derived, make_parents=make_parents)
