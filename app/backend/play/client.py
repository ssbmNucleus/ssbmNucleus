"""
The client install Play starts games with, shared by every game on the shelf: the Nucleus
client Play installed and keeps up to date itself (play/managed.py, its signed feed in
play/client_feed.py), or, as a developer option that wins when it is set, one folder the user
picks in Play's Settings (``clientFolder``). ``require``, ``configured`` and ``status`` answer
for whichever of the two is in use; ``status()['source']`` says which ('folder' or 'managed').

A folder is used only once it is verified: it holds melee_source.exe and
melee_game.dll (the Source Port) and a Sys folder. The program started is always
one of two fixed names inside the verified folder (``executable``), never a path a
request names. melee_port.exe beside them is the compatibility engine (the Static
Recomp), which plays fighters that have no native code; a folder without it still
plays everything else.

Verifying a folder also reads the client's facts (``facts``): ``melee_source.exe
--print-info`` prints one JSON object (version, engine, CPU baseline and whether this
computer has it, the plugin format and ABI id, which launch options it has) and exits
without a window. It is run as an argument list, never through a shell, with Nucleus's
settings and secrets left out of its environment, no console window and a short
timeout, and only when the program's file names the option (an older one stops on an
unknown option, with a message box). The answer is cached in Play's client-info.json
under the program's file stamp (modified time and size), so it is read again only when
the program changes. A client without ``fighters_dir`` and ``no_dialogs`` is too old and is
refused with a sentence saying so.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from core import path_safety
from core.child_env import child_environment
from play import shelf

SOURCE_EXE = 'melee_source.exe'
GAME_DLL = 'melee_game.dll'
COMPAT_EXE = 'melee_port.exe'
SYS_DIR = 'Sys'
SYS_PLAYBACK_DIR = 'SysPlayback'

#: Options Play passes when the client supports them: the one folder of
#: installed fighters and plugins for that run (or `none`), no record of the disc in
#: %LOCALAPPDATA%\MeleeUnlocked\launcher.ini, and no message boxes (a refusal, fatal error or
#: crash is logged and written to a file, and the game exits with its code).
FIGHTERS_DIR_OPTION = '--fighters-dir'
NO_REMEMBER_ISO_OPTION = '--no-remember-iso'
NO_DIALOGS_OPTION = '--no-dialogs'
LAUNCH_OPTIONS = (FIGHTERS_DIR_OPTION, NO_REMEMBER_ISO_OPTION, NO_DIALOGS_OPTION)

_options_cache = {}
_SCAN_CHUNK = 4 * 1024 * 1024

INFO_OPTION = '--print-info'
INFO_TIMEOUT = 10                      # seconds; the answer takes well under one
INFO_DIR = '_info'                     # its working folder, under Play's data folder
INFO_CACHE_FILE = 'client-info.json'   # the cached answers, in Play's folder
_INFO_CACHE_KEEP = 4
_INFO_RETRY = 300          # seconds a failed --print-info is believed before asking again
_INFO_MAX_BYTES = 64 * 1024
#: What a client must have for Play: one fighters folder per launch, and no message boxes.
REQUIRED_FEATURES = ('fighters_dir', 'no_dialogs')
_FEATURES = ('fighters_dir', 'no_remember_iso', 'no_crash_dialog', 'no_dialogs')
#: A release build says both are true (the client's NUCLEUS_PUBLIC_BUILD, client_release.py packages
#: nothing else). The installed Nucleus must be one; a hand-picked developer folder need not be.
PUBLIC_BUILD_FIELDS = ('public_build', 'game_public_build')
NOT_RELEASE_BUILD = ('This is a development build of Nucleus Unlocked, not a release: it does not say public_build and '
                     'game_public_build are true. Only a client folder you pick yourself may be a development '
                     'build.')
_info_lock = threading.RLock()


class ClientError(Exception):
    """Why a folder is not a Nucleus client folder, in a sentence that says what to do."""


def supported() -> bool:
    """Play starts games on Windows only for now."""
    return sys.platform == 'win32'


def local_path(value, *, what='folder') -> Path:
    """A path on this computer, as a drive-letter absolute path (C:\\...): the app's one
    request-path gate (core/path_safety.local_path), drive letters only since Play runs on
    Windows. Anything else is refused with ClientError: another computer's share
    (\\\\host\\share, //host, file://host), a device or raw path (\\\\?\\, \\\\.\\, \\??\\), a
    relative path. Shared by every Play route that takes a path from a request."""
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ClientError(f'No {what} was given.')
    try:
        text = path_safety.local_path(value, field=what, posix=False)
    except path_safety.NotLocalPath as refused:
        if refused.reason == 'network':
            raise ClientError(f'That {what} is not on this computer, or is not a plain path. '
                              f'Choose a {what} on one of your drives.')
        raise ClientError(f'Choose a {what} on one of your drives (a path such as C:\\Games\\...).')
    return Path(text)


def _resolved_local(path: Path, what) -> Path:
    """`path` resolved (junctions and links followed), still a drive-letter path on this computer."""
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ClientError(f'That {what} does not exist.')
    local_path(str(resolved), what=what)     # a junction to a share or a device is refused too
    return resolved


def is_release_build(info) -> bool:
    """True when a client's facts say it is a release build (PUBLIC_BUILD_FIELDS all true)."""
    return isinstance(info, dict) and all(info.get(name) is True for name in PUBLIC_BUILD_FIELDS)


def check_folder(value, *, release=False) -> Path:
    """The verified, resolved Nucleus client folder `value` names. Raises ClientError.
    With `release` (the installed Nucleus, never a hand-picked folder) it must be a release build too."""
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ClientError('Choose the Nucleus Unlocked folder (the one that holds melee_source.exe).')
    folder = _resolved_local(local_path(value), 'folder')
    if not folder.is_dir():
        raise ClientError('That is a file, not a folder. Choose the Nucleus Unlocked folder (the one that holds '
                          'melee_source.exe).')
    missing = [name for name, ok in (
        (SOURCE_EXE, (folder / SOURCE_EXE).is_file()),
        (GAME_DLL, (folder / GAME_DLL).is_file()),
        (SYS_DIR + '\\', (folder / SYS_DIR).is_dir()),
    ) if not ok]
    if missing:
        raise ClientError(f'This is not a Nucleus Unlocked folder: it has no {", ".join(missing)}. '
                          'Choose the folder that holds melee_source.exe.')
    play = shelf.play_root().resolve()
    if folder == play or play in folder.parents or folder in play.parents:
        # The game refuses a data folder inside its own folder, and Play keeps its games' saves in its own.
        raise ClientError("Choose the Nucleus Unlocked folder itself, not a folder that holds SSBM Nucleus's own data.")
    info = facts(folder)
    lacking = [name for name in REQUIRED_FEATURES if not info.get(name)]
    if lacking:
        version = info.get('version') or 'this version'
        raise ClientError(f'This Nucleus Unlocked ({version}) is too old for SSBM Nucleus: it cannot start each game with '
                          'its own fighters and without message boxes. Update Nucleus Unlocked and try again.')
    if release and not is_release_build(info):
        raise ClientError(NOT_RELEASE_BUILD)
    return folder


NOT_INSTALLED = 'Nucleus Unlocked is not installed yet. Press Install on its card.'


def _managed_folder():
    """The active managed client's folder (play/managed.py), not yet verified, or None."""
    from play import managed
    return managed.active_folder()


def require():
    """The verified client folder games start from: the hand-picked one when it is set (it wins, even
    when it is broken), else the managed one. Raises ClientError saying what to do."""
    value = shelf.read_settings().get('clientFolder')
    if value:
        try:
            return check_folder(value)
        except ClientError as e:
            raise ClientError(f"Your Nucleus Unlocked folder can't be used: {e} Check it in Unlocked, Settings.")
    folder = _managed_folder()
    if folder is None:
        raise ClientError(NOT_INSTALLED)
    try:
        return check_folder(folder, release=True)
    except ClientError as e:
        raise ClientError(f"The installed Nucleus Unlocked can't be used: {e} Install it again from its card.")


# --------------------------------------------------------------------------- the client's facts

def _clean_text(value, limit):
    if not isinstance(value, str):
        return None
    text = ''.join(ch for ch in value if ch >= ' ').strip()
    return text[:limit] or None


def clean_info(raw) -> dict:
    """The facts Play keeps from a --print-info answer: known keys, checked types, short strings."""
    if not isinstance(raw, dict):
        raise ClientError('Nucleus Unlocked did not say what it is.')
    abi = raw.get('plugin_abi')
    abi = abi.lower() if isinstance(abi, str) and 0 < len(abi) <= 64 and all(
        c in '0123456789abcdefABCDEF' for c in abi) else None
    fmt = raw.get('plugin_format')
    linked = raw.get('linked_fighters')
    info = {
        'version': _clean_text(raw.get('version'), 40),
        'engine': _clean_text(raw.get('engine'), 20),
        'cpu_baseline': _clean_text(raw.get('cpu_baseline'), 20),
        'cpu_supported': raw.get('cpu_supported') if isinstance(raw.get('cpu_supported'), bool) else None,
        'game_library': _clean_text(raw.get('game_library'), 80),
        'plugin_format': fmt if isinstance(fmt, int) and not isinstance(fmt, bool) and 0 <= fmt < 1 << 16 else None,
        'plugin_abi': abi,
        'linked_fighters': [t for t in (_clean_text(x, 64) for x in linked[:64]) if t]
        if isinstance(linked, list) else [],
    }
    for name in _FEATURES:
        info[name] = raw.get(name) is True
    for name in PUBLIC_BUILD_FIELDS:      # true, false, or None when the client does not say
        info[name] = raw.get(name) if isinstance(raw.get(name), bool) else None
    return info


def read_info(exe: Path, *, cwd: Path) -> dict:
    """What `exe --print-info` says about itself, as clean_info keeps it. Raises ClientError.

    An argument list (never a shell), Nucleus's settings and secrets out of the environment
    (core/child_env.py), no console window, INFO_TIMEOUT seconds at most (then the process is
    ended through its own handle), and only for a program whose file names the option."""
    exe = Path(exe)
    if INFO_OPTION not in mentions(exe, (INFO_OPTION,)):
        raise ClientError('This Nucleus Unlocked is too old for SSBM Nucleus: it cannot say which version it is. '
                          'Update Nucleus Unlocked and try again.')
    Path(cwd).mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    try:
        done = subprocess.run([str(exe), INFO_OPTION], cwd=str(cwd), env=child_environment(), shell=False,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=INFO_TIMEOUT, creationflags=flags)
    except subprocess.TimeoutExpired:
        raise ClientError(f'Nucleus Unlocked did not answer within {INFO_TIMEOUT} seconds when asked which version '
                          'it is.')
    except OSError as e:
        raise ClientError(f'Nucleus Unlocked could not be started to ask which version it is ({e.strerror or e}).')
    text = (done.stdout or b'')[:_INFO_MAX_BYTES].decode('utf-8', 'replace').strip()
    raw = None
    for candidate in [text, *reversed(text.splitlines())]:
        try:
            raw = json.loads(candidate)
            break
        except ValueError:
            continue
    if isinstance(raw, dict) and raw.get('error'):
        raise ClientError(f"Nucleus Unlocked could not say which version it is: {_clean_text(str(raw['error']), 200)}")
    if done.returncode != 0 or not isinstance(raw, dict):
        raise ClientError(f'Nucleus Unlocked did not say which version it is (exit code {done.returncode}).')
    return clean_info(raw)


def _recent(stamp, seconds) -> bool:
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    return 0 <= (datetime.now(timezone.utc) - when).total_seconds() < seconds


def facts(folder: Path) -> dict:
    """The facts of the client in a folder (read_info), cached under its program's file stamp:
    read again only when melee_source.exe changes. A failure is kept for _INFO_RETRY seconds,
    so a program that does not answer is not started again on every look. Raises ClientError."""
    exe = Path(folder) / SOURCE_EXE
    stamp = file_stamp(exe)
    cache_file = shelf.play_root() / INFO_CACHE_FILE
    with _info_lock:
        cache = shelf.read_json(cache_file, {})
        cached = cache.get(str(exe))
        if isinstance(cached, dict) and cached.get('stamp') == stamp and stamp is not None:
            # An answer kept before Play read the public-build fields is asked again.
            if isinstance(cached.get('info'), dict) and all(k in cached['info'] for k in PUBLIC_BUILD_FIELDS):
                return cached['info']
            if isinstance(cached.get('error'), str) and _recent(cached.get('readAt'), _INFO_RETRY):
                raise ClientError(cached['error'])
        record = {'stamp': stamp, 'readAt': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        try:
            record['info'] = read_info(exe, cwd=shelf.play_root() / shelf.DATA_DIR / INFO_DIR)
        except ClientError as e:
            record['error'] = str(e)
        # The newest few programs asked; one folder is normally all there is.
        kept = {k: v for k, v in cache.items() if k != str(exe) and isinstance(v, dict)}
        kept = dict(sorted(kept.items(), key=lambda kv: str(kv[1].get('readAt')))[-(_INFO_CACHE_KEEP - 1):])
        kept[str(exe)] = record
        shelf.write_json(cache_file, kept)
        if 'error' in record:
            raise ClientError(record['error'])
        return record['info']


def known_facts(folder):
    """facts(folder), or None when there is no folder or it cannot say (never raises)."""
    if folder is None:
        return None
    try:
        return facts(folder)
    except ClientError:
        return None


def executable(folder: Path, engine: str) -> Path:
    """The program to start in a folder `check_folder` verified: always one of two fixed names."""
    name = COMPAT_EXE if engine == shelf.ENGINE_COMPAT else SOURCE_EXE
    exe = Path(folder) / name
    if not exe.is_file():
        if engine == shelf.ENGINE_COMPAT:
            raise ClientError('This game needs the compatibility engine (melee_port.exe), '
                              'and your Nucleus Unlocked folder does not have it.')
        raise ClientError('melee_source.exe is missing from your Nucleus Unlocked folder.')
    return exe


def file_stamp(path: Path):
    """(modified time in ns, size) of a file, the key its cached facts are kept under, or None."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return [stat.st_mtime_ns, stat.st_size]


def mentions(path: Path, needles) -> frozenset:
    """Which of `needles` (text) a program file contains, read once per file stamp.

    A Melee Unlocked program matches each option by its exact text, so a program whose file does
    not hold an option's text cannot accept it: such an option is never passed to it (the
    compatibility engine of a 1.0.6 install predates the launch options and stops on an unknown
    one). Reading the file runs nothing."""
    stamp = file_stamp(path)
    if stamp is None:
        return frozenset()
    key = (str(path), tuple(stamp), tuple(needles))
    cached = _options_cache.get(key)
    if cached is not None:
        return cached
    wanted = {n: n.encode('ascii') for n in needles}
    found = set()
    overlap = max(len(b) for b in wanted.values()) if wanted else 0
    tail = b''
    try:
        with open(path, 'rb') as stream:
            while len(found) < len(wanted):
                chunk = stream.read(_SCAN_CHUNK)
                if not chunk:
                    break
                window = tail + chunk
                found.update(n for n, b in wanted.items() if n not in found and b in window)
                tail = window[-overlap:]
    except OSError:
        return frozenset()
    result = frozenset(found)
    _options_cache[key] = result
    return result


def launch_options(exe: Path) -> frozenset:
    """Which of LAUNCH_OPTIONS the program `exe` accepts (``mentions``)."""
    return mentions(exe, LAUNCH_OPTIONS)


def describe(folder: Path) -> dict:
    """What a verified folder offers: its version and facts (--print-info), which engines are
    there, and whether it can play replays (SysPlayback)."""
    info = known_facts(folder) or {}
    return {
        'folder': str(folder),
        'version': info.get('version') or file_version(Path(folder) / SOURCE_EXE),
        'engines': {shelf.ENGINE_SOURCE: True,
                    shelf.ENGINE_COMPAT: (Path(folder) / COMPAT_EXE).is_file()},
        'engine': info.get('engine'),
        'cpuBaseline': info.get('cpu_baseline'),
        'cpuSupported': info.get('cpu_supported'),
        'pluginFormat': info.get('plugin_format'),
        'pluginAbi': info.get('plugin_abi'),
        'linkedFighters': info.get('linked_fighters') or [],
        'features': {name: bool(info.get(name)) for name in _FEATURES},
        'playback': (Path(folder) / SYS_PLAYBACK_DIR).is_dir(),
    }


def verify(value, *, release=False) -> dict:
    """{valid, error} plus describe() for a folder that is one (check_folder). Never raises."""
    try:
        return {'valid': True, 'error': None, **describe(check_folder(value, release=release))}
    except ClientError as e:
        return {'valid': False, 'error': str(e), 'folder': str(value or '')}


def configured():
    """The client folder games start from (``require``), verified now, or None."""
    try:
        return require()
    except ClientError:
        return None


def status() -> dict:
    """The client games start from, as the Play page shows it: {set, source, valid, error, folder, version,
    engines, ...}. `source` is 'folder' (the hand-picked one, which wins), 'managed' (the installed Nucleus)
    or None (neither: set is False)."""
    value = shelf.read_settings().get('clientFolder')
    if value:
        return {'set': True, 'source': 'folder', **verify(value)}
    folder = _managed_folder()
    if folder is not None:
        return {'set': True, 'source': 'managed', **verify(folder, release=True)}
    return {'set': False, 'source': None, 'valid': False, 'error': None, 'folder': ''}


def save(value) -> dict:
    """Verify and keep a folder (an empty value forgets it). Raises ClientError."""
    if value is None or not str(value).strip():
        shelf.write_settings(clientFolder=None)
        return status()
    folder = check_folder(value)
    shelf.write_settings(clientFolder=str(folder))
    return status()


def file_version(path: Path):
    """The file version in a Windows program's version resource ('1.2.3.4'), or None."""
    if os.name != 'nt' or not Path(path).is_file():
        return None
    try:
        import ctypes
        from ctypes import wintypes
        version = ctypes.WinDLL('version', use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                           ctypes.POINTER(wintypes.UINT)]
        version.VerQueryValueW.restype = wintypes.BOOL
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        block = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, block):
            return None
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not version.VerQueryValueW(block, '\\', ctypes.byref(pointer), ctypes.byref(length)) or not length.value:
            return None

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [(name, wintypes.DWORD) for name in (
                'signature', 'struc_version', 'file_ms', 'file_ls', 'product_ms', 'product_ls',
                'flags_mask', 'flags', 'os', 'type', 'subtype', 'date_ms', 'date_ls')]

        info = FixedFileInfo.from_address(pointer.value)
        if info.signature != 0xFEEF04BD:
            return None
        return (f'{info.file_ms >> 16}.{info.file_ms & 0xFFFF}.'
                f'{info.file_ls >> 16}.{info.file_ls & 0xFFFF}')
    except (OSError, AttributeError, ValueError):
        return None
