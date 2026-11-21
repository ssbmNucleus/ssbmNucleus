"""The workspace boundary, tested as a boundary rather than as a spelling rule.

Astra's facade review, findings 1 and 2 (both P0):

* the guard was bypassable through public facade calls -- `dat_integrity()` and
  `menu_graph_check()` read `Path(path)` straight, `install_background(menu_file=)`
  took any host path, and `_resolve_input()` exempted EVERY existing absolute
  file. The reviewer confirmed it accepted this repository's own CLAUDE.md;
* and the check was validation, not containment: the root came from a mutable
  environment and the current directory, relative paths therefore resolved
  against the CWD rather than the workspace, and `resolve()` followed by
  `is_relative_to()` is answered before the file is opened, so a junction
  swapped in between decides where the open actually lands.

So these tests do not check that a path LOOKS contained. They plant a real
junction (and a real symlink where the machine allows one), hand the facade an
absolute path to a file that exists outside the workspace, and take the
workspace root away.
"""
from tests.paths import REPO
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from nucleus_api import _workspace
from nucleus_api._workspace import WorkspaceError

REPO_CLAUDE_MD = REPO / 'CLAUDE.md'


def _make_junction(link, target):
    """A real Windows junction, or skip. Junctions need no privilege."""
    if os.name != 'nt':
        try:
            link.symlink_to(target, target_is_directory=True)
            return
        except (OSError, NotImplementedError):
            pytest.skip('this machine does not allow creating links')
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not link.exists():
        pytest.skip(f'could not create a junction here: {result.stdout} {result.stderr}')


def menu_dat(root_symbol='MnSelectChrDataTable', background=b'background-model'):
    root_struct = bytearray(0x20)
    struct.pack_into('>I', root_struct, 0x10, 0x20)
    payload = bytes(root_struct) + background
    body = (struct.pack('>5I', 0, len(payload), 1, 1, 0) + b'\x00' * 12 + payload
            + struct.pack('>I', 0x10) + struct.pack('>II', 0, 0)
            + root_symbol.encode('ascii') + b'\x00')
    return struct.pack('>I', len(body)) + body[4:]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    (root / 'out').mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.usd').write_bytes(menu_dat(background=b'not yours'))
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(root))
    _workspace.reset_workspace()
    (root / 'out' / 'MnSlChr.usd').write_bytes(menu_dat())
    yield root, outside
    _workspace.reset_workspace()


# ---------------------------------------------------------------------------
# The root
# ---------------------------------------------------------------------------

def test_there_is_no_fallback_to_the_current_directory(tmp_path, monkeypatch):
    """A boundary that moves with chdir is not a boundary."""
    monkeypatch.delenv('NUCLEUS_API_WORKSPACE', raising=False)
    _workspace.reset_workspace()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceError) as caught:
        _workspace.workspace()
    assert 'current directory' in str(caught.value)
    _workspace.reset_workspace()


def test_a_relative_path_resolves_against_the_workspace_not_the_cwd(ws, tmp_path, monkeypatch):
    root, outside = ws
    decoy = outside / 'out'
    decoy.mkdir()
    (decoy / 'MnSlChr.usd').write_bytes(menu_dat(background=b'the decoy'))
    monkeypatch.chdir(outside)

    assert _workspace.in_path('out/MnSlChr.usd') == (root / 'out' / 'MnSlChr.usd').resolve()
    assert _workspace.read_input('out/MnSlChr.usd') == (root / 'out' / 'MnSlChr.usd').read_bytes()


def test_the_root_is_fixed_for_the_task_and_moves_only_when_it_is_installed(ws, tmp_path):
    root, _ = ws
    first = _workspace.workspace()
    assert _workspace.workspace() is first, 'resolved once, not per call'
    other = tmp_path / 'second-task'
    installed = _workspace.use_workspace(other)
    assert _workspace.workspace() == installed != first


def test_the_root_must_be_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', 'relative/workspace')
    _workspace.reset_workspace()
    with pytest.raises(WorkspaceError, match='absolute'):
        _workspace.workspace()
    _workspace.reset_workspace()


# ---------------------------------------------------------------------------
# Absolute is not a licence
# ---------------------------------------------------------------------------

def test_an_absolute_path_outside_the_workspace_is_refused(ws):
    _, outside = ws
    for call in (_workspace.in_path, _workspace.read_input, _workspace.open_input):
        with pytest.raises(WorkspaceError, match='must live in the workspace'):
            call(str(outside / 'secret.usd'))
    with pytest.raises(WorkspaceError, match='must live in the workspace'):
        _workspace.out_path(str(outside / 'written.dat'))


@pytest.mark.skipif(not REPO_CLAUDE_MD.is_file(), reason='not a checkout')
def test_the_file_the_reviewer_reached_is_refused_now(ws):
    """Astra confirmed _resolve_input() accepted this repository's CLAUDE.md."""
    from nucleus_api import menus
    with pytest.raises(WorkspaceError):
        menus._resolve_input(str(REPO_CLAUDE_MD))
    with pytest.raises(WorkspaceError):
        menus.dat_integrity(str(REPO_CLAUDE_MD))
    with pytest.raises(WorkspaceError):
        menus.identify_package(str(REPO_CLAUDE_MD))


def test_traversal_out_of_the_workspace_is_refused(ws):
    _, outside = ws
    escape = os.path.join('..', 'outside', 'secret.usd')
    with pytest.raises(WorkspaceError):
        _workspace.in_path(escape)
    with pytest.raises(WorkspaceError):
        _workspace.out_path(os.path.join('..', 'outside', 'written.dat'))


def test_only_the_library_can_name_a_path_outside_the_workspace(ws):
    """The exemption is a TYPE, so no argument can reach it."""
    root, outside = ws
    from nucleus_api import menus
    secret = outside / 'secret.usd'
    with pytest.raises(WorkspaceError):
        menus.dat_integrity(str(secret))
    trusted = _workspace.library_path(secret, why='a test standing in for the library')
    assert menus.dat_integrity(trusted)['status'] == 'pass'
    assert not isinstance(str(secret), _workspace.TrustedPath)


# ---------------------------------------------------------------------------
# Links and junctions
# ---------------------------------------------------------------------------

def test_a_junction_planted_in_the_workspace_cannot_redirect_a_read(ws):
    root, outside = ws
    _make_junction(root / 'out' / 'elsewhere', outside)
    assert (root / 'out' / 'elsewhere' / 'secret.usd').is_file(), 'the junction works'

    with pytest.raises(WorkspaceError, match='link or junction'):
        _workspace.in_path('out/elsewhere/secret.usd')
    with pytest.raises(WorkspaceError, match='link or junction'):
        _workspace.read_input('out/elsewhere/secret.usd')


def test_a_junction_planted_in_the_workspace_cannot_redirect_a_write(ws):
    root, outside = ws
    _make_junction(root / 'out' / 'elsewhere', outside)
    with pytest.raises(WorkspaceError, match='link or junction'):
        _workspace.out_path('out/elsewhere/written.dat')
    assert not (outside / 'written.dat').exists()


def test_a_junction_cannot_redirect_a_public_facade_call(ws):
    root, outside = ws
    from nucleus_api import menus
    _make_junction(root / 'out' / 'elsewhere', outside)
    for call in (lambda p: menus.dat_integrity(p),
                 lambda p: menus.menu_graph_check(p, 'css'),
                 lambda p: menus.identify_package(p),
                 lambda p: menus.check_compatibility(p, 'css')):
        with pytest.raises(WorkspaceError, match='link or junction'):
            call('out/elsewhere/secret.usd')


def test_a_symlinked_file_inside_the_workspace_is_refused(ws):
    root, outside = ws
    link = root / 'out' / 'linked.usd'
    try:
        link.symlink_to(outside / 'secret.usd')
    except (OSError, NotImplementedError):
        pytest.skip('this machine does not allow creating symlinks')
    with pytest.raises(WorkspaceError, match='link or junction'):
        _workspace.in_path('out/linked.usd')


# ---------------------------------------------------------------------------
# Open-then-verify
# ---------------------------------------------------------------------------

def test_the_file_is_verified_through_the_handle_that_reads_it(ws, monkeypatch):
    """A name checked and then opened is two operations; this is one."""
    root, outside = ws
    _workspace.workspace()          # install the root before os.stat is swapped
    real = _workspace.os.stat

    def swapped(path, *args, **kwargs):
        # Whatever a second stat of the NAME would say, the handle wins.
        info = real(str(outside / 'secret.usd'), *args, **kwargs)
        return info
    monkeypatch.setattr(_workspace.os, 'stat', swapped)
    with pytest.raises(WorkspaceError, match='not the file it was a moment ago'):
        _workspace.read_input('out/MnSlChr.usd')


def test_reading_happens_through_the_verified_handle(ws):
    root, _ = ws
    with _workspace.open_input('out/MnSlChr.usd') as source:
        assert source.path == (root / 'out' / 'MnSlChr.usd').resolve()
        assert source.read() == (root / 'out' / 'MnSlChr.usd').read_bytes()


# ---------------------------------------------------------------------------
# Derived outputs
# ---------------------------------------------------------------------------

def test_a_derived_output_is_checked_in_its_own_right(ws):
    root, outside = ws
    zipped = _workspace.out_path('out/model.zip')
    derived = _workspace.derived_output(zipped, '.dat')
    assert derived == (root / 'out' / 'model.dat').resolve()

    _make_junction(root / 'out' / 'elsewhere', outside)
    through_link = _workspace.out_path('out/model.zip')
    with pytest.raises(WorkspaceError):
        _workspace.derived_output(through_link.parent / 'elsewhere' / 'model.zip', '.dat')


def test_a_library_path_is_not_a_destination(ws):
    _, outside = ws
    trusted = _workspace.library_path(outside / 'secret.usd', why='a test')
    with pytest.raises(WorkspaceError, match='input, not a destination'):
        _workspace.out_path(trusted)


# ---------------------------------------------------------------------------
# install_background selects, it does not name a file
# ---------------------------------------------------------------------------

def test_install_background_refuses_a_host_path_for_the_menu_file(ws, monkeypatch):
    root, outside = ws
    from nucleus_api import menus
    monkeypatch.setattr(menus, 'list_menu_files', lambda: [
        {'id': 'menu_abc123', 'menu_type': 'css', 'name': 'MnSlChr.usd',
         'path': str(root / 'out' / 'MnSlChr.usd'), 'source': 'test'}])
    with pytest.raises(ValueError, match='not one of the MnSlChr files'):
        menus.install_background('out/MnSlChr.usd', 'out/new.usd', 'css',
                                 menu_file=str(outside / 'secret.usd'))


def test_list_menu_files_gives_the_id_install_background_takes(ws, monkeypatch):
    root, _ = ws
    from nucleus_api import menus
    rows = [{'id': 'menu_abc123', 'menu_type': 'css', 'name': 'MnSlChr.usd',
             'path': str(root / 'out' / 'MnSlChr.usd'), 'source': 'test'}]
    monkeypatch.setattr(menus, 'list_menu_files', lambda: rows)
    calls = []
    monkeypatch.setattr(menus, '_hsdraw', lambda args, timeout=180: calls.append(args))
    with pytest.raises(ValueError, match='produced no menu file'):
        menus.install_background('out/MnSlChr.usd', 'out/new.usd', 'css',
                                 menu_file='menu_abc123')
    assert calls and str(rows[0]['path']) in [str(a) for a in calls[0]]


# ---------------------------------------------------------------------------
# JSON-native results
# ---------------------------------------------------------------------------

def test_every_integrity_result_survives_json(ws):
    from nucleus_api import menus
    report = menus.dat_integrity('out/MnSlChr.usd')
    json.dumps(report)
    json.dumps(menus.menu_graph_check('out/MnSlChr.usd', 'css'))
    assert isinstance(report['relocated_offsets'], list)
