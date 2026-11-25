"""
Starting a game from the shelf, and watching it until it closes.

The command line follows Melee Unlocked's launch contract: every path the game
writes goes to the entry's own data folder (``shelf.data_dir``), which is also
its working folder (the Mods folder and the crash files follow the working
folder, not a flag), except

  * the game's settings: one port-settings.ini in the Play folder, shared by every
    game on the shelf (the first game copies the Melee Unlocked folder's own one into it,
    once: ``shelf.seed_game_settings``), and one shared shader cache;
  * the built-in "Nucleus Unlocked" entry (id retail), which uses the Slippi folders the user already
    has: the netplay Dolphin's User/Slippi folder (their account) and the replay folder
    Tracker indexes (Tracker's own choice, else the Slippi Launcher's), so Tracker keeps
    seeing its replays;
  * the built-in "Vanilla" entry, whose replays go to that same Tracker folder (its
    User/Slippi folder stays its own: no account).

Every game brings its own fighters: ``--fighters-dir`` is the added entry's own
``games/<id>/fighters`` folder when it has one, else ``none`` (the built-in Nucleus and
Vanilla always ``none``), so fighters installed in the Melee Unlocked folder never show
up in a game that did not bring them. ``--no-remember-iso`` keeps the game from
recording the disc in %LOCALAPPDATA%\\MeleeUnlocked\\launcher.ini, and ``--no-dialogs``
turns its message boxes off: a refusal, fatal error or crash is logged, written to a
file and ends the game with its code, and the card says what happened in words
(``describe_exit``, with the useful line from the game's console output, log or crash
file). A program that predates these options (client.launch_options) does not get them.

The program is always ``client.executable`` inside the verified Melee Unlocked
folder, started from an argument list (never a shell), detached, and never put in
Nucleus's kill-on-close job (core/child_procs.py): the game restarts itself after
some settings changes by starting a new copy and exiting 0, and the copy must
outlive the old one. The watcher follows such a copy (same program, started by the
one that exited) and reports how the session ended: the exit code, mapped to a
plain sentence, and whether a crash file newer than the launch appeared in the
working folder. The game's console output goes to ``melee_port_console.txt`` in the
working folder (some refusals are printed there and not logged).

A replay from Tracker (``watch_replay``) runs the same program as a replay viewer:
``--replay <file> --sys-dir <Melee Unlocked>\\SysPlayback`` with the user's disc, no
installed fighters, no dialogs, and everything it writes in Play's own ``data/_replay``
folder (the viewer records what it shows: that recording goes to ``_replay/Replays``,
cleared before each replay, never to the user's Slippi replay folder). The file must be a
replay Tracker has indexed, on this computer, and pass slp_meta's size and shape checks.

Job kind ``play_launch`` (one at a time, kept in memory only): its ``extra.phase``
is 'launching' then 'running' (with ``extra.pid``), and its result says how the game
closed ({outcome, exitCode, message, crashed, relaunched}).

Surviving a restart of Nucleus. The job is in memory, but the game outlives Nucleus, so while
a game runs Play keeps ``<data>/play/running.json``: which session it is (entry id, or the
replay viewer or settings window) and the process: its pid, start time and program, read
from the live process (and rewritten when the game restarts itself). It is removed when the
watch ends. At the next start ``reattach`` looks for that process: only when the pid is alive
with the same start time and the same program is it the game (a pid Windows gave to another
program never is), and a new play_launch job (``params.reattached``) watches it, so the card
shows it playing again and notices when it ends. The end is read as usual: the exit code
(Windows answers it for a process Nucleus did not start, as long as the watch is waiting on
it), the crash file and the game's log and console output, which the game still writes in
its working folder. What a restart loses: the restarts counted before it, and anything about
a game that ended while Nucleus was closed (its record is just dropped). Dolphin is never
watched, so never re-attached.
"""

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from core import jobs
from core.child_env import child_environment
from play import client, shelf

logger = logging.getLogger(__name__)

LAUNCH_KIND = 'play_launch'
jobs.register_kind(LAUNCH_KIND, label='Play', keep=10)

CRASH_FILE = 'melee_port_crash.txt'
CRASH_DUMP = 'melee_port_crash.dmp'
LOG_FILE = 'melee_port.log'
CONSOLE_FILE = 'melee_port_console.txt'
SETTINGS_LOG_FILE = 'melee_settings.log'
SETTINGS_WINDOW_DIR = '_settings'     # the settings window's working folder (not an entry id)
REPLAY_WORK_DIR = '_replay'           # the replay viewer's working folder (not an entry id)
NO_FIGHTERS = 'none'                  # --fighters-dir none: no installed fighters, no plugins

#: The variable older games read plugins from. Never set by Play (--fighters-dir names the
#: one folder), and never inherited either.
PLUGINS_ENV = 'MELEE_FIGHTER_PLUGINS'

EXIT_QUIT = 0
EXIT_CANNOT_OPEN = 1
EXIT_REFUSED = 2
EXIT_NO_AVX2 = 3
EXIT_REPLAY_CLOSED = 4
EXIT_FATAL = 70


def game_environment(base=None):
    """The environment a game started from Play gets: Nucleus's own, minus its settings and secrets
    (core/child_env.py: every NUCLEUS_*, a frozen Python's variables, and credentials such as *_API_KEY)."""
    return child_environment(base)

class PlayError(Exception):
    """Why a game cannot start, in a sentence that says what to do. `status` is the HTTP answer."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class LaunchCommand:
    args: list
    cwd: Path
    env_set: dict = field(default_factory=dict)     # variables the game gets on top of the environment
    env_unset: tuple = (PLUGINS_ENV,)               # variables it must not inherit
    make_dirs: tuple = ()
    console: Path = None                            # where its console output goes (None: nowhere)
    replay: bool = False                            # a replay viewer: exit 1 means the replay

    def environment(self, base=None):
        env = game_environment(base)
        for name in self.env_unset:
            env.pop(name, None)
        env.update(self.env_set)
        return env


# --------------------------------------------------------------------------- the command line

def _launch_flags(options, fighters_dir):
    """The launch options a program that knows `options` gets (client.LAUNCH_OPTIONS)."""
    flags = []
    if client.FIGHTERS_DIR_OPTION in options:
        flags += [client.FIGHTERS_DIR_OPTION, str(fighters_dir) if fighters_dir is not None else NO_FIGHTERS]
    if client.NO_REMEMBER_ISO_OPTION in options:
        flags.append(client.NO_REMEMBER_ISO_OPTION)
    if client.NO_DIALOGS_OPTION in options:
        flags.append(client.NO_DIALOGS_OPTION)
    return flags


def build_command(*, client_folder, entry, retail_iso, play_root, data_dir, engine=None,
                  slippi_user_dir=None, replay_dir=None, entry_disc=None, fighters_dir=None,
                  options=client.LAUNCH_OPTIONS, extra_args=()):
    """The command that starts `entry`. Every path is given: this only arranges them.

    `client_folder` must be one client.check_folder verified. `slippi_user_dir` and
    `replay_dir` are the user's own Slippi folders for the built-in Nucleus entry (None:
    the entry's own). `entry_disc` is an added entry's disc, played as a mod disc on the
    Source Port or as the disc itself on the compatibility engine, with the retail disc
    as its base. `fighters_dir` is the entry's own fighters folder (None: ``none``, no
    installed fighters and no plugins). `options` are the launch options the program
    accepts (client.launch_options). `extra_args` is for tests only (``--hidden --frames 600``)."""
    engine = engine or entry.get('engine') or shelf.ENGINE_SOURCE
    if entry.get('builtin') or entry.get('id') in shelf.BUILTIN_IDS:
        engine = shelf.ENGINE_SOURCE    # Nucleus and Vanilla never use the retired compatibility engine
    folder, play_root, data = Path(client_folder), Path(play_root), Path(data_dir)
    exe = client.executable(folder, engine)
    if (entry.get('options') or {}).get('vanilla') or entry.get('builtin') or entry.get('id') in shelf.BUILTIN_IDS:
        fighters_dir = None             # the built-in games never have installed fighters
    vanilla = bool((entry.get('options') or {}).get('vanilla'))
    if vanilla and entry_disc is not None:
        raise PlayError('Vanilla plays your own disc only.')
    if entry_disc is not None:
        card_dir = data / 'User' / 'GC' / 'Mods' / entry['id']
    else:
        card_dir = data / 'User' / 'GC' / 'CardA'      # --vanilla-only adds VanillaOnly itself
    user_dir = Path(slippi_user_dir) if slippi_user_dir else data / 'User' / 'Slippi'
    replays = Path(replay_dir) if replay_dir else data / 'Replays'

    if entry_disc is not None and engine == shelf.ENGINE_COMPAT:
        disc_args = ['--iso', str(entry_disc), '--mod-base-iso', str(retail_iso)]
    elif entry_disc is not None:
        disc_args = ['--iso', str(retail_iso), '--mod-iso', str(entry_disc)]
    else:
        disc_args = ['--iso', str(retail_iso)]
    args = [str(exe), *disc_args,
            '--threaded-renderer',
            '--settings-path', str(play_root / shelf.GAME_SETTINGS_FILE),
            '--sys-dir', str(folder / client.SYS_DIR),
            '--user-dir', str(user_dir),
            '--sysgen-data-dir', str(data),
            '--card-dir', str(card_dir),
            '--replay-dir', str(replays),
            '--log-file', str(data / LOG_FILE),
            '--shader-cache', str(play_root / shelf.SHADER_CACHE_DIR),
            *_launch_flags(options, fighters_dir)]
    if vanilla:
        args.append('--vanilla-only')
    args.extend(str(a) for a in extra_args)
    dirs = [data, card_dir, play_root / shelf.SHADER_CACHE_DIR]
    if not slippi_user_dir:
        dirs.append(user_dir)
    if not replay_dir:
        dirs.append(replays)
    return LaunchCommand(args=args, cwd=data, make_dirs=tuple(dirs), console=data / CONSOLE_FILE)


def settings_window_command(*, client_folder, play_root, options=client.LAUNCH_OPTIONS):
    """The game's own settings window, on its own: no disc, the shared settings file."""
    folder, play_root = Path(client_folder), Path(play_root)
    work = play_root / shelf.DATA_DIR / SETTINGS_WINDOW_DIR
    args = [str(client.executable(folder, shelf.ENGINE_SOURCE)), '--settings-window',
            '--settings-path', str(play_root / shelf.GAME_SETTINGS_FILE),
            '--sys-dir', str(folder / client.SYS_DIR),
            '--log-file', str(work / SETTINGS_LOG_FILE)]
    if client.NO_DIALOGS_OPTION in options:
        args.append(client.NO_DIALOGS_OPTION)
    return LaunchCommand(args=args, cwd=work, make_dirs=(work,), console=work / CONSOLE_FILE)


def replay_command(*, client_folder, replay, retail_iso, play_root, options=client.LAUNCH_OPTIONS, extra_args=()):
    """The replay viewer for `replay`: the Source Port with the SysPlayback folder, the user's
    disc, no installed fighters, and its log, recording and saves in Play's own _replay folder.
    Every path is given: this only arranges them."""
    folder, play_root = Path(client_folder), Path(play_root)
    work = play_root / shelf.DATA_DIR / REPLAY_WORK_DIR
    args = [str(client.executable(folder, shelf.ENGINE_SOURCE)),
            '--iso', str(retail_iso),
            '--replay', str(replay),
            '--sys-dir', str(folder / client.SYS_PLAYBACK_DIR),
            '--threaded-renderer',
            '--settings-path', str(play_root / shelf.GAME_SETTINGS_FILE),
            '--user-dir', str(work / 'User' / 'Slippi'),
            '--sysgen-data-dir', str(work),
            '--replay-dir', str(work / 'Replays'),
            '--log-file', str(work / LOG_FILE),
            '--shader-cache', str(play_root / shelf.SHADER_CACHE_DIR),
            *_launch_flags(options, None)]
    args.extend(str(a) for a in extra_args)
    return LaunchCommand(args=args, cwd=work, console=work / CONSOLE_FILE, replay=True,
                         make_dirs=(work, work / 'Replays', work / 'User' / 'Slippi',
                                    play_root / shelf.SHADER_CACHE_DIR))


def tracker_replay_folder():
    """The folder Tracker indexes, so a game's replays show up there: the replay folder chosen in
    Tracker itself when it still exists, else the Slippi Launcher's (tracker identity.replay_root).
    None when there is none (the game then keeps its replays in its own folder)."""
    try:
        from tracker.store import identity, indexer
    except Exception:  # noqa: BLE001 - Tracker not in this build
        logger.debug('Play: Tracker is not available', exc_info=True)
        return None
    try:
        conn = indexer.connect()
        try:
            found = identity.replay_root(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - its store unreadable: the Slippi Launcher's folder
        logger.debug('Play: Tracker\'s replay folder could not be read', exc_info=True)
        try:
            found = identity.get_replay_root()
        except Exception:  # noqa: BLE001
            logger.debug('Play: no Slippi replay folder', exc_info=True)
            found = None
    return found if found and os.path.isdir(found) else None


def slippi_folders():
    """(user dir, replay dir) of the user's own Slippi setup, each None when not found: the netplay
    Dolphin's User/Slippi folder (their account) and the folder Tracker indexes."""
    user_dir = None
    try:
        from shared.ingame.boot import launcher_dir
        found = launcher_dir('netplay', 'User', 'Slippi')
        if found and os.path.isdir(found):
            user_dir = found
    except Exception:  # noqa: BLE001 - no Slippi Launcher: the entry's own folder
        logger.debug('Play: no Slippi user folder', exc_info=True)
    return user_dir, tracker_replay_folder()


def retail_iso():
    """The user's Melee disc as Nucleus recorded it at setup, or None."""
    from shared.vanilla_extract.vanilla_refs import known_vanilla_iso
    return known_vanilla_iso()


NEEDS_ISO = 'Nucleus Unlocked needs your Melee ISO. Choose it in Settings, Setup.'


def recorded_iso():
    """The disc path Nucleus recorded at setup even when its file is gone, or None (never recorded)."""
    from shared.vanilla_extract.vanilla_refs import recorded_vanilla_iso
    return recorded_vanilla_iso()


def missing_iso():
    """The recorded disc's path when its file is no longer there (moved, renamed, a drive not
    connected), else None."""
    try:
        path = recorded_iso()
        return path if path is not None and not path.is_file() else None
    except (OSError, ValueError):
        return None


def no_iso_message():
    """Why no game can start without a disc: where the recorded one was, when it is gone, else that
    none is set."""
    gone = missing_iso()
    if gone is not None:
        return f'Your Melee ISO was not found at {gone}. Choose it in Settings, Setup.'
    return NEEDS_ISO


def check_retail_iso(iso):
    """Raise PlayError unless `iso` is the unmodified NTSC 1.02 disc (MD5, cached per file)."""
    # verify_iso_file's checks live with the setup routes; imported here, at use, so the rule
    # stays one rule.
    from shared.routes.setup import check_vanilla_iso
    verdict = check_vanilla_iso(iso)
    if not verdict.get('valid'):
        raise PlayError(f"Your Melee ISO can't be used: {verdict.get('message') or 'it is not the original disc.'} "
                        'Choose it again in Settings, Setup.')


CPU_MESSAGE = "This computer's processor cannot run Nucleus Unlocked: it needs a processor with AVX2."


def ready_client():
    """The verified Melee Unlocked folder a launch starts from, once its facts say this
    computer can run it. Raises PlayError saying what to do."""
    if not client.supported():
        raise PlayError('Nucleus Unlocked is Windows only for now.')
    try:
        folder = client.require()
    except client.ClientError as e:
        raise PlayError(str(e))
    if (client.known_facts(folder) or {}).get('cpu_supported') is False:
        raise PlayError(CPU_MESSAGE)
    return folder


def _seed_settings(folder):
    """The Melee Unlocked folder's own settings, copied into Play's once (shelf.seed_game_settings). A copy
    that fails never stops a game: it then starts with the game's defaults."""
    try:
        shelf.seed_game_settings(folder)
    except OSError:
        logger.warning('Play: the Melee Unlocked settings could not be copied', exc_info=True)


def plan(entry, *, extra_args=()):
    """The command for an entry, from the shelf, the saved Melee Unlocked folder and the
    user's disc. Raises PlayError for what the user has to fix first."""
    folder = ready_client()
    iso = retail_iso()
    if iso is None:
        raise PlayError(no_iso_message())
    disc = shelf.disc_path(entry)
    if disc is not None and not disc.is_file():
        raise PlayError("This game's disc is missing from its folder. Remove it and add it to the shelf again.")
    user_dir = replays = None
    if entry['id'] == shelf.RETAIL_ID:
        user_dir, replays = slippi_folders()
    elif entry['id'] in shelf.BUILTIN_IDS:
        replays = tracker_replay_folder()     # Vanilla: the replays Tracker sees, never the user's account
    _seed_settings(folder)
    from play import routing
    engine, _reason = routing.effective_engine(entry, folder)
    try:
        options = client.launch_options(client.executable(folder, engine))
        return build_command(
            client_folder=folder, entry=entry, retail_iso=iso, play_root=shelf.play_root(),
            data_dir=shelf.data_dir(entry), engine=engine, slippi_user_dir=user_dir, replay_dir=replays,
            entry_disc=disc, fighters_dir=routing.own_fighters(entry), options=options,
            extra_args=extra_args)
    except client.ClientError as e:
        raise PlayError(str(e))


# --------------------------------------------------------------------------- start and watch

def start(command: LaunchCommand):
    """Start the game: detached, from an argument list, never owned (module docstring). Its
    console output goes to `command.console` (written anew each launch) when there is one."""
    for folder in command.make_dirs:
        Path(folder).mkdir(parents=True, exist_ok=True)
    from shared.ingame.boot import start_detached
    if command.console is None:
        return start_detached(command.args, cwd=str(command.cwd), env=command.environment(),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(command.console).parent.mkdir(parents=True, exist_ok=True)
    with open(command.console, 'wb') as console:      # the game keeps its own handle
        return start_detached(command.args, cwd=str(command.cwd), env=command.environment(),
                              stdin=subprocess.DEVNULL, stdout=console, stderr=subprocess.STDOUT)


def crash_file(working_dir: Path, since: float):
    """The crash report the game left in its working folder after `since`, or None."""
    for name in (CRASH_FILE, CRASH_DUMP):
        path = Path(working_dir) / name
        try:
            if path.stat().st_mtime >= since - 1.0:
                return path
        except OSError:
            continue
    return None


_TAIL_BYTES = 64 * 1024
_MAX_DETAIL = 300
#: Lines the game writes at every start, never the reason it stopped.
_ROUTINE = re.compile(r'^(melee unlocked \d|memory:|cpu \(|timing:|dialogs:|gecko:|discord:|slippi:|stack +\d+:|'
                      r'gameplay:|in the launcher|exit codes:|\[|melee_port |usage)', re.IGNORECASE)
_TROUBLE = re.compile(r"fail|cannot|can't|could not|couldn't|refus|not verified|modded|error|fatal|"
                      r'missing|not found|needs|unknown option|invalid|denied', re.IGNORECASE)


def _tail_lines(path):
    """The last lines of a text file the game wrote (at most _TAIL_BYTES), or []."""
    if path is None:
        return []
    try:
        with open(path, 'rb') as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - _TAIL_BYTES))
            text = stream.read().decode('utf-8', 'replace')
    except OSError:
        return []
    return [line.strip() for line in text.splitlines()]


def _clean_detail(line):
    line = ''.join(ch for ch in line if ch >= ' ').strip().rstrip('.')
    line = re.sub(r',? version [0-9][\w.\-]*$', '', line)          # "FATAL: ..., version 1.0.6"
    if line.upper().startswith('FATAL:'):
        line = line[6:].strip()
    return line[:_MAX_DETAIL] or None


def failure_detail(*, console=None, log=None, crash=None):
    """The one line worth showing about why the game stopped: the crash file's first line,
    else the last line of trouble the game printed (its console output, then its log) after
    its start-up lines. None when there is nothing better than the exit code."""
    if crash is not None and Path(crash).suffix == '.txt':
        for line in _tail_lines(crash):
            if line and not line.lower().startswith('stack'):
                return _clean_detail(line)
    for source in (console, log):
        lines = _tail_lines(source)
        unknown = [line for line in lines if line.lower().startswith('unknown option')]
        if unknown:
            return _clean_detail(unknown[-1])
        marks = [i for i, line in enumerate(lines) if line.lower().startswith('dialogs:')]
        after = lines[marks[-1] + 1:] if marks else lines
        useful = [line for line in after if line and not _ROUTINE.match(line)]
        trouble = [line for line in useful if _TROUBLE.search(line)]
        if trouble:
            return _clean_detail(trouble[-1])
    return None


def describe_exit(code, crashed=False, *, detail=None, folder=None, replay=False):
    """(outcome, message) for how a session ended. `detail` is failure_detail's line, `folder`
    the working folder the log and crash files are in, `replay` true for the replay viewer."""
    where = f'in {folder}' if folder else 'in its data folder'
    said = f': {detail}' if detail else ''
    if code == EXIT_FATAL:
        return 'fatal', f'The game stopped on an error{said}. The log is {where}.'
    if crashed:
        return 'crashed', f'The game crashed{said}. Its crash report is {where}.'
    if code is None:
        return 'quit', 'Closed.'
    if code < 0 or code >= 0xC0000000:
        return 'crashed', (f'The game stopped unexpectedly (code 0x{code & 0xFFFFFFFF:08X}){said}. '
                           f'Its log is {where}.')
    if code in (EXIT_QUIT, EXIT_REPLAY_CLOSED):
        return 'quit', 'Closed.'
    if code == EXIT_CANNOT_OPEN:
        if replay:
            return 'disc_error', f'The game could not open the replay{said}.'
        return 'disc_error', (f'The game could not open the disc{said}. Check that your Melee ISO is still '
                              'where Nucleus expects it (Settings, Setup).')
    if code == EXIT_REFUSED:
        if detail and detail.lower().startswith('unknown option'):
            return 'refused', (f'The game did not accept how Nucleus started it ({detail}). '
                               'This Nucleus Unlocked may be older than this SSBM Nucleus: update it.')
        if detail:
            return 'refused', f'The game refused to start this disc{said}.'
        return 'refused', f'The game refused to start this disc. The log {where} says why.'
    if code == EXIT_NO_AVX2:
        return 'cpu', CPU_MESSAGE
    return 'stopped', f'The game stopped with code {code}{said}. Its log is {where}.'


def find_successor(pid, exe_name, since):
    """The copy of the game a closing one started (a restart): same program, its parent
    the closing process, started after the session began. None when there is none."""
    import psutil
    for process in psutil.process_iter(['pid', 'ppid', 'name', 'create_time']):
        info = process.info
        if info.get('ppid') == pid and (info.get('name') or '').lower() == exe_name.lower() \
                and (info.get('create_time') or 0) >= since - 1.0:
            return process
    return None


def _wait_popen(proc, should_stop, poll):
    while True:
        code = proc.poll()
        if code is not None:
            return code
        if should_stop():
            return None
        time.sleep(poll)


def _wait_psutil(process, should_stop, poll):
    """Wait for a process Nucleus did not start (psutil): its exit code, or None when that is
    not known (it ended between two waits, or its pid now names another process)."""
    import psutil
    while True:
        try:
            return process.wait(timeout=poll)
        except psutil.TimeoutExpired:
            if should_stop():
                return None
            still = getattr(process, 'is_running', None)     # also false once the pid is reused
            if still is not None and not still():
                return None
        except psutil.NoSuchProcess:
            return None


def watch(proc, *, exe_name, working_dir, since, on_running=None, should_stop=lambda: False,
          poll=0.5, successor=None, successor_grace=1.5):
    """Wait for a session to end, following the game across its own restarts. `proc` is the
    Popen that started it, or a psutil process found again after a restart of Nucleus.
    Returns {exitCode, relaunched, crashFile, stoppedWatching}. `successor` defaults to
    find_successor, looked up when called (so a stand-in for it is the one used)."""
    successor = successor or find_successor
    relaunched = 0
    pid = proc.pid
    if hasattr(proc, 'poll'):
        code = _wait_popen(proc, should_stop, poll)
    else:
        code = _wait_psutil(proc, should_stop, poll)
    while code == 0:
        # A restart: the closing game started its copy before it exited.
        deadline = time.time() + successor_grace
        follow = successor(pid, exe_name, since)
        while follow is None and time.time() < deadline:
            time.sleep(0.25)
            follow = successor(pid, exe_name, since)
        if follow is None:
            break
        relaunched += 1
        pid = follow.pid
        logger.info('Play: the game restarted itself (pid %s)', pid)
        if on_running is not None:
            on_running(pid)
        code = _wait_psutil(follow, should_stop, poll)
    stopped = should_stop()
    found = crash_file(working_dir, since)
    return {'exitCode': code, 'relaunched': relaunched, 'crashFile': found, 'stoppedWatching': stopped}


def run_session(job, command: LaunchCommand, *, entry_id, check_disc=None):
    """The play_launch job: check the disc, start the game, watch it, say how it ended."""
    job.progress(None, 'Starting...', phase='launching', entryId=entry_id)
    if check_disc is not None:
        job.progress(None, 'Checking your Melee disc...', phase='launching')
        check_disc()
    since = time.time()
    proc = start(command)
    logger.info('Play: started %s (pid %s) for %s', Path(command.args[0]).name, proc.pid, entry_id or 'settings')
    return follow_session(job, proc, command, entry_id=entry_id, since=since)


def follow_session(job, proc, command: LaunchCommand, *, entry_id, since):
    """Watch a started (or re-attached) game until it ends, with running.json naming it all the
    while, and say how it ended."""
    def running(pid):
        job.progress(None, 'Running', phase='running', pid=pid)
        remember_running(job.params, pid)

    running(proc.pid)
    try:
        ended = watch(proc, exe_name=Path(command.args[0]).name, working_dir=command.cwd, since=since,
                      on_running=running, should_stop=job.should_stop)
    finally:
        forget_running()
    if ended['stoppedWatching']:
        return {'outcome': 'unwatched', 'exitCode': None, 'crashed': False, 'relaunched': ended['relaunched'],
                'message': 'Nucleus stopped watching the game; it keeps running.'}
    return session_result(command, ended, entry_id=entry_id)


def session_result(command: LaunchCommand, ended, *, entry_id):
    """The play_launch result for a session `watch` saw end."""
    code = ended['exitCode']
    crashed = ended['crashFile'] is not None
    detail = None
    if code not in (None, EXIT_QUIT, EXIT_REPLAY_CLOSED, EXIT_NO_AVX2) or crashed:
        log = _log_file(command)
        detail = failure_detail(console=command.console, log=log,
                                crash=command.cwd / CRASH_FILE if crashed or code == EXIT_FATAL else None)
    outcome, message = describe_exit(code, crashed, detail=detail, folder=str(command.cwd), replay=command.replay)
    logger.info('Play: %s ended: %s (exit %s)', entry_id or 'settings', outcome, code)
    return {'outcome': outcome, 'exitCode': code, 'message': message, 'crashed': outcome == 'crashed',
            'relaunched': ended['relaunched'], 'detail': detail}


def _log_file(command: LaunchCommand):
    """The --log-file a command names, or None."""
    args = list(command.args)
    if '--log-file' in args and args.index('--log-file') + 1 < len(args):
        return Path(args[args.index('--log-file') + 1])
    return None


# --------------------------------------------------------------------------- across a restart of Nucleus

RUNNING_FILE = 'running.json'
#: The session keys running.json keeps: which card's game it is (entryId), or which other window.
_SESSION_KEYS = ('entryId', 'replay', 'settingsWindow')
#: How far apart two readings of one process's start time may be (psutil reads the same number each time).
SAME_START = 0.01


def running_file() -> Path:
    return shelf.play_root() / RUNNING_FILE


def _program(path):
    return os.path.normcase(os.path.normpath(str(path)))


def process_facts(pid):
    """(start time, program) of the live process `pid`, or None when it cannot be read."""
    import psutil
    try:
        process = psutil.Process(pid)
        return process.create_time(), process.exe()
    except (psutil.Error, OSError, ValueError):
        return None


def remember_running(params, pid):
    """Write running.json for the game a play_launch job watches now: the session (`params`'
    entryId, or replay / settingsWindow) and the process: pid, start time and program, read
    from the live process. Never stops the watch: a record that cannot be written is logged."""
    try:
        facts = process_facts(pid)
        if facts is None:
            return None
        record = {key: params.get(key) for key in _SESSION_KEYS if params.get(key) is not None}
        record.update(pid=int(pid), created=facts[0], exe=facts[1])
        shelf.write_json(running_file(), record)
        return record
    except Exception:  # noqa: BLE001 - the game plays on; only a restart of Nucleus would lose it
        logger.warning('Play: could not note the running game for a restart', exc_info=True)
        return None


def forget_running():
    """Remove running.json (the watch ended, or what it named is not running any more)."""
    try:
        with shelf.locked():
            running_file().unlink(missing_ok=True)
    except OSError:
        logger.warning('Play: could not remove %s', RUNNING_FILE, exc_info=True)


def same_process(pid, created, exe):
    """The live process `pid` when it is the one recorded: the same start time and the same
    program. None otherwise (it ended, or Windows gave its pid to another program since)."""
    import psutil
    try:
        process = psutil.Process(int(pid))
        if abs(process.create_time() - float(created)) > SAME_START:
            return None
        if _program(process.exe()) != _program(exe):
            return None
        return process if process.is_running() else None
    except (psutil.Error, OSError, ValueError, TypeError):
        return None


def _found_again(record):
    """(process, command, params, label) for the session running.json names when its game is
    still running, else None. The command only says where the game's log, console output and
    crash files are (made from the entry id, never from the record) and the program's name
    (to follow a restart); it is never started."""
    pid, created, exe = record.get('pid'), record.get('created'), record.get('exe')
    if not (type(pid) is int and pid > 0 and type(created) in (int, float) and isinstance(exe, str) and exe):
        return None
    if not client.supported():
        return None
    entry_id = record.get('entryId')
    if entry_id is not None:
        entry = shelf.find(entry_id)
        if entry is None:
            return None
        work = shelf.data_dir(entry)
        log, replay, label = work / LOG_FILE, False, f"Play {entry['name']}"
        params = {'entryId': entry['id'], 'target': shelf.TARGET_MU}
    elif record.get('replay') is True:
        work = shelf.play_root() / shelf.DATA_DIR / REPLAY_WORK_DIR
        log, replay, label = work / LOG_FILE, True, 'Watch a replay'
        params = {'entryId': None, 'replay': True}
    elif record.get('settingsWindow') is True:
        work = shelf.play_root() / shelf.DATA_DIR / SETTINGS_WINDOW_DIR
        log, replay, label = work / SETTINGS_LOG_FILE, False, 'Game settings'
        params = {'entryId': None, 'settingsWindow': True}
    else:
        return None
    process = same_process(pid, created, exe)
    if process is None:
        return None
    command = LaunchCommand(args=[exe, '--log-file', str(log)], cwd=work, console=work / CONSOLE_FILE,
                            replay=replay)
    return process, command, {**params, 'reattached': True}, label


def reattach():
    """At startup (app.py, after the job recovery): when the game an earlier run of Nucleus was
    watching is still running, a play_launch job watches it again (module docstring). Returns
    that job's id, or None, and then running.json is dropped."""
    record = shelf.read_json(running_file(), {}) if running_file().exists() else {}
    if not record:
        return None
    try:
        found = _found_again(record)
    except Exception:  # noqa: BLE001 - never blocks startup: the record is dropped
        logger.warning('Play: the game left running could not be checked', exc_info=True)
        found = None
    if found is None:
        logger.info('Play: the game the last run was watching is not running any more')
        forget_running()
        return None
    process, command, params, label = found
    since = float(record['created'])
    logger.info('Play: %s is still running (pid %s); watching it again', label, process.pid)

    def run(job):
        result = follow_session(job, process, command, entry_id=params['entryId'], since=since)
        return {**result, 'reattached': True}
    return jobs.start(LAUNCH_KIND, run, label=label, single=True, params=params)


def launch(entry_id, *, target=None, slippi_path=None):
    """Start a play_launch job for a shelf entry. Returns the job id. Raises PlayError, jobs.JobBusy."""
    entry = shelf.get(entry_id)
    target = target or entry.get('lastTarget') or entry.get('defaultTarget') or shelf.TARGET_MU
    targets = entry.get('targets') or {}
    if target not in targets:
        raise PlayError('That game cannot be played there.')
    if not targets[target].get('available'):
        raise PlayError(targets[target].get('reason') or 'That game cannot be played there.')
    if target == shelf.TARGET_DOLPHIN:
        return _launch_dolphin(entry, slippi_path)
    command = plan(entry)
    iso = retail_iso()
    with shelf.locked():
        _still_the_same_files(entry)
        job_id = jobs.start(LAUNCH_KIND, lambda job: run_session(job, command, entry_id=entry['id'],
                                                                 check_disc=lambda: check_retail_iso(iso)),
                            label=f"Play {entry['name']}", single=True,
                            params={'entryId': entry['id'], 'target': target})
    shelf.update(entry['id'], last_target=target)
    return job_id


def _still_the_same_files(entry):
    """Under the shelf lock, just before a game starts: refuse when a replace swapped the
    entry's files since its command was made (shelf.replace refuses, under the same lock, once
    the game is running, so the two never cross)."""
    if shelf.folder_of(entry['id']) != shelf.files_folder(entry):
        raise PlayError('This game changed on the shelf just now. Press Play again.', 409)


def dolphin_command(slippi_path, disc):
    """The user's own Slippi Dolphin booting `disc`: the same program and arguments as the
    Dolphin play Nucleus already has (shared.ingame.boot.launch_real), started with the
    game environment."""
    if not slippi_path:
        raise PlayError('Set your Slippi Dolphin folder in Settings, Setup to play in Dolphin.')
    try:
        folder = client.local_path(slippi_path)
    except client.ClientError as e:
        raise PlayError(f'Your Slippi Dolphin folder cannot be used: {e}')
    from shared.ingame.boot import resolve_dolphin
    try:
        exe, _ = resolve_dolphin(str(folder))
    except Exception as e:  # noqa: BLE001 - resolve_dolphin says what is missing
        raise PlayError(f'Slippi Dolphin was not found there: {e}')
    exe = Path(exe)
    return LaunchCommand(args=[str(exe), '-e', str(disc)], cwd=exe.parent, env_unset=(), console=None)


def _launch_dolphin(entry, slippi_path):
    """Hand the entry's disc to the user's own Slippi Dolphin."""
    disc = shelf.disc_path(entry)
    if disc is None:
        disc = retail_iso()
        if disc is None:
            raise PlayError(no_iso_message())
    elif not disc.is_file():
        raise PlayError("This game's disc is missing from its folder. Remove it and add it to the shelf again.")
    command = dolphin_command(slippi_path, disc)
    pack = entry.get('texturePack') if isinstance(entry.get('texturePack'), dict) else None

    def run(job):
        if pack:
            job.progress(None, 'Loading its HD textures...', phase='launching', entryId=entry['id'])
            load_textures(entry, pack, str(client.local_path(slippi_path)))
        job.progress(None, 'Starting Dolphin...', phase='launching', entryId=entry['id'])
        start(command)
        return {'outcome': 'started', 'exitCode': None, 'crashed': False, 'relaunched': 0,
                'message': 'Started in Dolphin.'}

    with shelf.locked():
        _still_the_same_files(entry)
        job_id = jobs.start(LAUNCH_KIND, run, label=f"Play {entry['name']} in Dolphin", single=True,
                            params={'entryId': entry['id'], 'target': shelf.TARGET_DOLPHIN})
    shelf.update(entry['id'], last_target=shelf.TARGET_DOLPHIN)
    return job_id


def load_textures(entry, pack, slippi_path):
    """Make a game's own texture pack (kept when it was added from a bundle) the one Slippi
    Dolphin loads, as Play in Dolphin does for the bundle (projects/routes/bundles.py)."""
    from projects.routes.bundles import load_texture_pack
    from core.path_safety import validate_path_segment
    folder = shelf.textures_dir(entry)
    build_name = validate_path_segment(pack.get('buildName'), field='texture pack')
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.png') \
        if folder is not None and folder.is_dir() else []
    return load_texture_pack(slippi_path, build_name, ((p.name, lambda p=p: open(p, 'rb')) for p in files))


REPLAY_NO_PLAYBACK = ('This Nucleus Unlocked cannot play replays: its folder has no SysPlayback folder. '
                      'Update Nucleus Unlocked.')


def replay_status():
    """{available, reason} for "Watch in Melee Unlocked": whether a replay could start now
    (the folder, its SysPlayback, the processor, the user's disc), and if not, why."""
    try:
        folder = ready_client()
    except PlayError as e:
        return {'available': False, 'reason': str(e)}
    if not (folder / client.SYS_PLAYBACK_DIR).is_dir():
        return {'available': False, 'reason': REPLAY_NO_PLAYBACK}
    if retail_iso() is None:
        return {'available': False, 'reason': no_iso_message()}
    return {'available': True, 'reason': None}


def checked_replay(path) -> Path:
    """The replay `path` names, once it is one Tracker indexed (the rule /replays/watch uses),
    on this computer, a .slp file, and within slp_meta's size and shape checks (slp_guard's
    first step). Raises PlayError."""
    if not isinstance(path, str) or not path.strip():
        raise PlayError('Say which replay to watch.')
    from tracker.store import indexer, slp_meta
    from tracker.store.games import _validate_indexed_path
    conn = indexer.connect()
    try:
        indexed = _validate_indexed_path(conn, path)
    finally:
        conn.close()
    if not indexed:
        raise PlayError('That replay is not in Tracker.', 404)
    try:
        replay = client.local_path(indexed, what='replay')
    except client.ClientError as e:
        raise PlayError(f"That replay can't be opened here: {e}")
    if replay.suffix.lower() != '.slp' or not replay.is_file():
        raise PlayError('That is not a replay file.')
    why = slp_meta.peppi_refusal(str(replay))
    if why:
        raise PlayError(f'That replay cannot be played: {why}.')
    return replay


def _clear_recordings(folder: Path):
    """The viewer's own recordings from earlier replays (only .slp files in _replay/Replays)."""
    if not folder.is_dir():
        return
    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() == '.slp':
            try:
                item.unlink()
            except OSError:
                pass


def watch_replay(path, *, extra_args=()):
    """Start a play_launch job that plays a Tracker replay in Melee Unlocked's replay viewer.
    Returns the job id. Raises PlayError, jobs.JobBusy."""
    folder = ready_client()
    if not (folder / client.SYS_PLAYBACK_DIR).is_dir():
        raise PlayError(REPLAY_NO_PLAYBACK)
    iso = retail_iso()
    if iso is None:
        raise PlayError(no_iso_message())
    replay = checked_replay(path)
    _seed_settings(folder)
    try:
        command = replay_command(client_folder=folder, replay=replay, retail_iso=iso, play_root=shelf.play_root(),
                                 options=client.launch_options(client.executable(folder, shelf.ENGINE_SOURCE)),
                                 extra_args=extra_args)
    except client.ClientError as e:
        raise PlayError(str(e))

    def run(job):
        _clear_recordings(command.cwd / 'Replays')
        return run_session(job, command, entry_id=None, check_disc=lambda: check_retail_iso(iso))
    return jobs.start(LAUNCH_KIND, run, label=f'Watch {replay.name}', single=True,
                      params={'entryId': None, 'replay': True, 'file': replay.name})


def open_settings_window():
    """Start a play_launch job that shows the game's own settings window. Returns the job id."""
    folder = ready_client()
    _seed_settings(folder)
    try:
        command = settings_window_command(
            client_folder=folder, play_root=shelf.play_root(),
            options=client.launch_options(client.executable(folder, shelf.ENGINE_SOURCE)))
    except client.ClientError as e:
        raise PlayError(str(e))
    return jobs.start(LAUNCH_KIND, lambda job: run_session(job, command, entry_id=None),
                      label='Game settings', single=True, params={'entryId': None, 'settingsWindow': True})


def running_entry():
    """The entry id of the game running now (None when the settings window or nothing is)."""
    job = jobs.active_job(LAUNCH_KIND)
    return None if job is None else job.params.get('entryId')
