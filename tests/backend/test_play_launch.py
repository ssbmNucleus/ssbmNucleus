"""Starting a game from Play (play/launch.py): the exact command line for each kind of entry, the
environment the game gets, how a session's end is read (exit codes, crash files, the game
restarting itself), the play_launch job, and a game that outlives Nucleus found again after a
restart (running.json: only the same pid, start time and program). The "game" here is a stand-in
Python script; the real Melee Unlocked is exercised by app/scratch/play_e2e.py, not by this suite."""
from tests.paths import BACKEND
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(BACKEND))

from core import jobs  # noqa: E402
from play import client, launch, shelf  # noqa: E402
from tests.backend.test_play_shelf import fake_client, fake_plugin, stub_info  # noqa: E402


@pytest.fixture
def play(tmp_path, monkeypatch):
    root = tmp_path / 'play'
    monkeypatch.setattr(shelf, 'play_root', lambda: root)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    stub_info(monkeypatch)
    return root


@pytest.fixture
def game(tmp_path):
    return fake_client(tmp_path / 'MeleeUnlocked').resolve()


def _cmd(game, play, entry, **kw):
    return launch.build_command(client_folder=game, entry=entry, retail_iso=Path('C:/Melee.iso'),
                                play_root=play, data_dir=play / 'data' / entry['id'], **kw)


# --------------------------------------------------------------------------- command lines

def test_the_melee_card_uses_the_slippi_folders(game, play):
    entry = shelf.get('retail')
    cmd = _cmd(game, play, entry, slippi_user_dir='C:/Slippi/netplay/User/Slippi', replay_dir='C:/Replays')
    data = play / 'data' / 'retail'
    assert cmd.args == [
        str(game / 'melee_source.exe'), '--iso', str(Path('C:/Melee.iso')), '--threaded-renderer',
        '--settings-path', str(play / 'port-settings.ini'), '--sys-dir', str(game / 'Sys'),
        '--user-dir', str(Path('C:/Slippi/netplay/User/Slippi')), '--sysgen-data-dir', str(data),
        '--card-dir', str(data / 'User' / 'GC' / 'CardA'), '--replay-dir', str(Path('C:/Replays')),
        '--log-file', str(data / 'melee_port.log'), '--shader-cache', str(play / 'shadercache'),
        '--fighters-dir', 'none', '--no-remember-iso', '--no-dialogs']
    assert cmd.cwd == data
    assert cmd.env_set == {} and 'MELEE_FIGHTER_PLUGINS' in cmd.env_unset
    assert cmd.console == data / 'melee_port_console.txt'
    # The user's own Slippi folders are used, never made.
    assert Path('C:/Slippi/netplay/User/Slippi') not in cmd.make_dirs


def test_the_melee_card_without_slippi_keeps_its_own_folders(game, play):
    cmd = _cmd(game, play, shelf.get('retail'))
    data = play / 'data' / 'retail'
    assert cmd.args[cmd.args.index('--user-dir') + 1] == str(data / 'User' / 'Slippi')
    assert cmd.args[cmd.args.index('--replay-dir') + 1] == str(data / 'Replays')
    assert data / 'User' / 'Slippi' in cmd.make_dirs and data / 'Replays' in cmd.make_dirs


def test_vanilla(game, play):
    cmd = _cmd(game, play, shelf.get('vanilla'))
    data = play / 'data' / 'vanilla'
    assert cmd.args == [
        str(game / 'melee_source.exe'), '--iso', str(Path('C:/Melee.iso')), '--threaded-renderer',
        '--settings-path', str(play / 'port-settings.ini'), '--sys-dir', str(game / 'Sys'),
        '--user-dir', str(data / 'User' / 'Slippi'), '--sysgen-data-dir', str(data),
        '--card-dir', str(data / 'User' / 'GC' / 'CardA'), '--replay-dir', str(data / 'Replays'),
        '--log-file', str(data / 'melee_port.log'), '--shader-cache', str(play / 'shadercache'),
        '--fighters-dir', 'none', '--no-remember-iso', '--no-dialogs', '--vanilla-only']
    # A built-in game never gets a fighters folder, whatever it is handed.
    assert _cmd(game, play, shelf.get('vanilla'), fighters_dir=play / 'x').args[-5:-3] == ['--fighters-dir', 'none']
    assert _cmd(game, play, shelf.get('retail'), fighters_dir=play / 'x').args[-4:-2] == ['--fighters-dir', 'none']
    # Never with a mod disc.
    with pytest.raises(launch.PlayError):
        _cmd(game, play, shelf.get('vanilla'), entry_disc=Path('X:/mod.iso'))


def _owned(entry_id='0123456789ab', engine='source'):
    return {'id': entry_id, 'name': 'PokeMelee', 'disc': {'kind': 'owned'}, 'engine': engine,
            'targets': {'mu': {'available': True}}}


def test_an_added_game_is_a_mod_disc(game, play):
    entry = _owned()
    games = play / 'games' / entry['id']
    cmd = _cmd(game, play, entry, entry_disc=games / 'disc.iso', fighters_dir=games / 'fighters')
    data = play / 'data' / entry['id']
    assert cmd.args == [
        str(game / 'melee_source.exe'), '--iso', str(Path('C:/Melee.iso')), '--mod-iso', str(games / 'disc.iso'),
        '--threaded-renderer',
        '--settings-path', str(play / 'port-settings.ini'), '--sys-dir', str(game / 'Sys'),
        '--user-dir', str(data / 'User' / 'Slippi'), '--sysgen-data-dir', str(data),
        '--card-dir', str(data / 'User' / 'GC' / 'Mods' / entry['id']), '--replay-dir', str(data / 'Replays'),
        '--log-file', str(data / 'melee_port.log'), '--shader-cache', str(play / 'shadercache'),
        '--fighters-dir', str(games / 'fighters'), '--no-remember-iso', '--no-dialogs']
    # Its own fighters folder, named by the option; the environment variable is never set.
    assert cmd.env_set == {} and 'MELEE_FIGHTER_PLUGINS' in cmd.env_unset
    assert '--vanilla-only' not in cmd.args
    # Without a folder of its own: no installed fighters and no plugins.
    bare = _cmd(game, play, entry, entry_disc=games / 'disc.iso')
    assert bare.args[bare.args.index('--fighters-dir') + 1] == 'none'


def test_a_program_that_predates_the_launch_options_does_not_get_them(game, play):
    entry = _owned(engine='compat')
    games = play / 'games' / entry['id']
    old = _cmd(game, play, entry, entry_disc=games / 'disc.iso', options=frozenset())
    assert not {'--fighters-dir', '--no-remember-iso', '--no-dialogs'} & set(old.args)
    assert client.launch_options(game / 'melee_port.exe') == frozenset()       # the stand-in names none
    assert client.launch_options(game / 'melee_source.exe') == frozenset(client.LAUNCH_OPTIONS)
    some = _cmd(game, play, entry, entry_disc=games / 'disc.iso', options=frozenset({'--no-dialogs'}))
    assert '--no-dialogs' in some.args and '--fighters-dir' not in some.args


def test_an_added_game_on_the_compatibility_engine(game, play):
    entry = _owned(engine='compat')
    games = play / 'games' / entry['id']
    cmd = _cmd(game, play, entry, entry_disc=games / 'disc.iso', fighters_dir=games / 'fighters')
    assert cmd.args[:5] == [str(game / 'melee_port.exe'), '--iso', str(games / 'disc.iso'),
                            '--mod-base-iso', str(Path('C:/Melee.iso'))]
    assert '--mod-iso' not in cmd.args
    assert cmd.args[cmd.args.index('--card-dir') + 1] == str(play / 'data' / entry['id'] / 'User' / 'GC' / 'Mods'
                                                             / entry['id'])
    (game / 'melee_port.exe').unlink()
    with pytest.raises(client.ClientError):
        _cmd(game, play, entry, entry_disc=games / 'disc.iso')


def test_test_flags_go_last(game, play):
    cmd = _cmd(game, play, shelf.get('retail'), extra_args=('--hidden', '--frames', 600))
    assert cmd.args[-3:] == ['--hidden', '--frames', '600']


def test_the_settings_window(game, play):
    cmd = launch.settings_window_command(client_folder=game, play_root=play)
    work = play / 'data' / '_settings'
    assert cmd.args == [str(game / 'melee_source.exe'), '--settings-window',
                        '--settings-path', str(play / 'port-settings.ini'), '--sys-dir', str(game / 'Sys'),
                        '--log-file', str(work / 'melee_settings.log'), '--no-dialogs']
    assert cmd.cwd == work
    assert '_settings' not in {e['id'] for e in shelf.entries()}


def test_the_game_gets_no_nucleus_secrets():
    base = {'PATH': 'C:/Windows', 'NUCLEUS_BACKEND_TOKEN': 't', 'NUCLEUS_UI_APPROVAL_KEY': 'k',
            'nucleus_data_root': 'x', '_MEIPASS2': 'y', '_PYI_ARCHIVE_FILE': 'z', 'PYTHONPATH': 'p',
            'MELEE_FIGHTER_PLUGINS': 'C:/old', 'APPDATA': 'C:/Users/me/AppData/Roaming'}
    cmd = launch.LaunchCommand(args=['x'], cwd=Path('.'), env_set={'MELEE_FIGHTER_PLUGINS': 'C:/new'})
    assert cmd.environment(base) == {'PATH': 'C:/Windows', 'APPDATA': 'C:/Users/me/AppData/Roaming',
                                     'MELEE_FIGHTER_PLUGINS': 'C:/new'}
    plain = launch.LaunchCommand(args=['x'], cwd=Path('.'))
    assert 'MELEE_FIGHTER_PLUGINS' not in plain.environment(base)


def test_plan_says_what_is_missing(play, game, monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'supported', lambda: True)
    monkeypatch.setattr(launch, 'retail_iso', lambda: None)
    monkeypatch.setattr(launch, 'recorded_iso', lambda: None)
    with pytest.raises(launch.PlayError, match='Nucleus Unlocked is not installed yet'):
        launch.plan(shelf.get('retail'))
    client.save(str(game))
    with pytest.raises(launch.PlayError) as caught:
        launch.plan(shelf.get('retail'))
    assert str(caught.value) == 'Nucleus Unlocked needs your Melee ISO. Choose it in Settings, Setup.'
    # A recorded disc whose file is gone: the message says where it was.
    gone = tmp_path / 'moved' / 'Melee.iso'
    monkeypatch.setattr(launch, 'recorded_iso', lambda: gone)
    with pytest.raises(launch.PlayError) as caught:
        launch.plan(shelf.get('retail'))
    assert str(caught.value) == f'Your Melee ISO was not found at {gone}. Choose it in Settings, Setup.'
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'')
    monkeypatch.setattr(launch, 'retail_iso', lambda: iso)
    monkeypatch.setattr(launch, 'slippi_folders', lambda: (None, None))
    monkeypatch.setattr(launch, 'tracker_replay_folder', lambda: None)
    cmd = launch.plan(shelf.get('vanilla'))
    assert cmd.args[0] == str(game / 'melee_source.exe') and cmd.args[-1] == '--vanilla-only'
    assert cmd.args[cmd.args.index('--fighters-dir') + 1] == 'none' and '--no-dialogs' in cmd.args
    monkeypatch.setattr(client, 'supported', lambda: False)
    with pytest.raises(launch.PlayError, match='Windows only'):
        launch.plan(shelf.get('retail'))



# --------------------------------------------------------------------------- where the built-in games' replays go

def test_both_built_in_games_save_replays_where_tracker_looks(monkeypatch, play, game, tmp_path):
    monkeypatch.setattr(client, 'supported', lambda: True)
    client.save(str(game))
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'')
    monkeypatch.setattr(launch, 'retail_iso', lambda: iso)
    tracker, account = tmp_path / 'Slippi Replays', tmp_path / 'netplay' / 'User' / 'Slippi'
    monkeypatch.setattr(launch, 'slippi_folders', lambda: (str(account), str(tracker)))
    monkeypatch.setattr(launch, 'tracker_replay_folder', lambda: str(tracker))
    nucleus, vanilla = launch.plan(shelf.get('retail')), launch.plan(shelf.get('vanilla'))
    for cmd in (nucleus, vanilla):
        assert cmd.args[cmd.args.index('--replay-dir') + 1] == str(tracker)
        assert tracker not in cmd.make_dirs              # the user's folder is used, never made
    # Only Nucleus plays with the user's Slippi account; Vanilla keeps its own User/Slippi folder.
    assert nucleus.args[nucleus.args.index('--user-dir') + 1] == str(account)
    assert vanilla.args[vanilla.args.index('--user-dir') + 1] == str(play / 'data' / 'vanilla' / 'User' / 'Slippi')
    # With no Tracker folder each keeps its replays in its own folder.
    monkeypatch.setattr(launch, 'slippi_folders', lambda: (None, None))
    monkeypatch.setattr(launch, 'tracker_replay_folder', lambda: None)
    cmd = launch.plan(shelf.get('vanilla'))
    assert cmd.args[cmd.args.index('--replay-dir') + 1] == str(play / 'data' / 'vanilla' / 'Replays')


def test_the_tracker_folder_is_the_one_tracker_indexes(monkeypatch, tmp_path):
    from tracker.store import identity, indexer
    monkeypatch.setattr(indexer, 'DB_PATH', tmp_path / 'nucleome.db')
    launcher, chosen = tmp_path / 'launcher-replays', tmp_path / 'chosen-in-tracker'
    launcher.mkdir()
    monkeypatch.setattr(identity, 'get_replay_root', lambda: str(launcher))
    assert launch.tracker_replay_folder() == str(launcher)
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, 'replay_root_override', str(chosen))
        conn.commit()
    finally:
        conn.close()
    assert launch.tracker_replay_folder() == str(launcher)       # a chosen folder that is gone is not used
    chosen.mkdir()
    assert launch.tracker_replay_folder() == str(chosen)
    monkeypatch.setattr(identity, 'get_replay_root', lambda: None)
    monkeypatch.setattr(indexer, 'DB_PATH', tmp_path / 'other.db')
    assert launch.tracker_replay_folder() is None

# --------------------------------------------------------------------------- how a session ended

@pytest.mark.parametrize('code,outcome', [
    (0, 'quit'), (1, 'disc_error'), (2, 'refused'), (3, 'cpu'), (4, 'quit'), (70, 'fatal'), (7, 'stopped'),
    (0xC0000005, 'crashed'), (-1073741819, 'crashed'), (None, 'quit')])
def test_exit_codes(code, outcome):
    got, message = launch.describe_exit(code)
    assert got == outcome and message


def test_a_crash_file_means_a_crash_whatever_the_code():
    assert launch.describe_exit(0, crashed=True)[0] == 'crashed'
    # ...except the game's own fatal stop, which writes the crash file too.
    assert launch.describe_exit(70, crashed=True)[0] == 'fatal'


def test_each_failure_is_said_in_words():
    folder = 'C:\\Nucleus\\play\\data\\0123456789ab'
    assert launch.describe_exit(3)[1] == ("This computer's processor cannot run Nucleus Unlocked: it needs a "
                                          'processor with AVX2.')
    fatal = launch.describe_exit(70, detail='the stage file is missing', folder=folder)[1]
    assert fatal == f'The game stopped on an error: the stage file is missing. The log is in {folder}.'
    refused = launch.describe_exit(
        2, detail='This Melee disc is modded, so Melee Unlocked cannot build its online menus from it')[1]
    assert refused == ('The game refused to start this disc: This Melee disc is modded, so Melee Unlocked cannot '
                       'build its online menus from it.')
    assert 'This Nucleus Unlocked may be older than this SSBM Nucleus' in launch.describe_exit(2, detail='unknown option --fighters-dir')[1]
    crashed = launch.describe_exit(0xC0000005, crashed=True, detail='Unhandled exception', folder=folder)[1]
    assert crashed == f'The game crashed: Unhandled exception. Its crash report is in {folder}.'
    assert 'replay' in launch.describe_exit(1, replay=True)[1]
    assert 'Melee ISO' in launch.describe_exit(1, detail='cannot open ISO C:\\x.iso')[1]


# What the real game printed (Melee Unlocked 1.0.6, --hidden --no-dialogs), trimmed.
REFUSED_CONSOLE = '''Melee Unlocked 1.0.6, melee_source.exe
gameplay: vanilla-only session; saved gameplay mods are suspended
timing: timeBeginPeriod(1) ok
dialogs: none in this run; a refusal, fatal error or crash is logged and reported in a file (--no-dialogs)
warning: disc id is not GALE01
Sys generation failed: GameSetup_gui.dat: disc is not verified retail Melee NTSC 1.02
This Melee disc is modded, so Melee Unlocked cannot build its online menus from it.

In the launcher, Browse to an unmodified Melee NTSC 1.02 ISO. A modded disc can go into Mods instead.
'''
REFUSED_LOG = '''Melee Unlocked 1.0.6, melee_source.exe
dialogs: none in this run; a refusal, fatal error or crash is logged and reported in a file (--no-dialogs)
warning: disc id is not GALE01
Sys generation failed: GameSetup_gui.dat: disc is not verified retail Melee NTSC 1.02
'''
CRASH_TEXT = '''FATAL: the game stopped itself (abort), version 1.0.6
stack  0: melee_source.exe+0x1A881
'''


def test_the_useful_line_comes_from_the_console_the_log_or_the_crash_file(tmp_path):
    console, log, crash = tmp_path / 'console.txt', tmp_path / 'melee_port.log', tmp_path / 'melee_port_crash.txt'
    console.write_text(REFUSED_CONSOLE, encoding='utf-8')
    log.write_text(REFUSED_LOG, encoding='utf-8')
    crash.write_text(CRASH_TEXT, encoding='utf-8')
    assert launch.failure_detail(console=console, log=log) == \
        'This Melee disc is modded, so Melee Unlocked cannot build its online menus from it'
    assert launch.failure_detail(console=tmp_path / 'none.txt', log=log) == \
        'Sys generation failed: GameSetup_gui.dat: disc is not verified retail Melee NTSC 1.02'
    assert launch.failure_detail(console=console, log=log, crash=crash) == 'the game stopped itself (abort)'
    console.write_text('timing: ok\ndialogs: none\ncannot open ISO C:\\nope.iso\n', encoding='utf-8')
    assert launch.failure_detail(console=console) == 'cannot open ISO C:\\nope.iso'
    console.write_text('unknown option --frobnicate\nmelee_port --iso <path>\nExit codes: 0 ended\n', encoding='utf-8')
    assert launch.failure_detail(console=console) == 'unknown option --frobnicate'
    console.write_text('timing: ok\ndialogs: none\n', encoding='utf-8')
    assert launch.failure_detail(console=console, log=tmp_path / 'missing.log') is None


def test_only_a_crash_file_newer_than_the_launch_counts(tmp_path):
    crash = tmp_path / 'melee_port_crash.txt'
    crash.write_text('old crash', encoding='utf-8')
    old = time.time() - 3600
    os.utime(crash, (old, old))
    assert launch.crash_file(tmp_path, time.time()) is None
    crash.write_text('new crash', encoding='utf-8')
    assert launch.crash_file(tmp_path, time.time() - 5) == crash
    crash.unlink()
    (tmp_path / 'melee_port_crash.dmp').write_bytes(b'MDMP')
    assert launch.crash_file(tmp_path, time.time() - 5).name == 'melee_port_crash.dmp'


class FakeProc:
    def __init__(self, pid, code):
        self.pid, self.code = pid, code

    def poll(self):
        return self.code


class FakeFollower:
    def __init__(self, pid, code):
        self.pid, self.code = pid, code

    def wait(self, timeout=None):
        return self.code


def test_the_watcher_follows_a_restart(tmp_path):
    chain = {100: FakeFollower(200, 0), 200: FakeFollower(300, 3)}
    running = []
    ended = launch.watch(FakeProc(100, 0), exe_name='melee_source.exe', working_dir=tmp_path, since=time.time(),
                         on_running=running.append, successor=lambda pid, exe, since: chain.get(pid),
                         successor_grace=0)
    assert ended == {'exitCode': 3, 'relaunched': 2, 'crashFile': None, 'stoppedWatching': False}
    assert running == [200, 300]


def test_an_error_exit_is_not_followed(tmp_path):
    asked = []
    ended = launch.watch(FakeProc(100, 2), exe_name='melee_source.exe', working_dir=tmp_path, since=time.time(),
                         successor=lambda *a: asked.append(a), successor_grace=0)
    assert ended['exitCode'] == 2 and ended['relaunched'] == 0 and asked == []


STAND_IN = textwrap.dedent('''\
    import os, subprocess, sys, time
    mode = sys.argv[1]
    time.sleep(0.3)
    if mode == 'restart':
        # Start a new copy, as the game does after a settings change, and quit.
        subprocess.Popen([sys.executable, __file__, 'then-fatal'], cwd=os.getcwd(),
                         creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
        time.sleep(0.2)
        sys.exit(0)
    if mode == 'then-fatal':
        time.sleep(0.5)
        print('FATAL: the stage file is missing')
        open('melee_port_crash.txt', 'w').write('FATAL: the stage file is missing, version 1.0.6')
        sys.exit(70)
    if mode == 'crash':
        open('melee_port_crash.txt', 'w').write('Unhandled exception')
        sys.exit(0xC0000005 if os.name == 'nt' else 139)
    if mode == 'env':
        open('env.txt', 'w').write('\\n'.join(sorted(os.environ)))
    if mode == 'refuse':
        print('dialogs: none in this run')
        print('This Melee disc is modded, so Melee Unlocked cannot build its online menus from it.')
        sys.stdout.flush()
        sys.exit(2)
    if mode == 'linger':
        time.sleep(2.0)
        sys.exit(0)
    if mode == 'spawn':
        # A game some earlier Nucleus started: a detached process this one is not the parent of.
        child = subprocess.Popen([sys.executable, __file__, 'linger-fatal'], cwd=os.getcwd(),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
        open('child.pid', 'w').write(str(child.pid))
        sys.exit(0)
    if mode == 'linger-fatal':
        time.sleep(4.0)
        open('melee_port_crash.txt', 'w').write('FATAL: the stage file is missing, version 1.0.6')
        sys.exit(70)
    sys.exit(int(mode) if mode.isdigit() else 0)
''')


@pytest.fixture
def stand_in(tmp_path, play):
    # `play`: a session notes the running game in the Play folder (running.json); keep it in tmp_path.
    script = tmp_path / 'stand_in.py'
    script.write_text(STAND_IN, encoding='utf-8')
    # The real interpreter, not a venv's launcher stub: the stand-in's restart must be the
    # watched process's own child, as the game's is.
    python = getattr(sys, '_base_executable', None) or sys.executable
    work = tmp_path / 'work'

    def command(mode):
        return launch.LaunchCommand(args=[python, '-I', str(script), mode], cwd=work, make_dirs=(work,),
                                    console=work / 'melee_port_console.txt')
    return command


def _wait(job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = jobs.get(job_id)
        if record and record['status'] in ('done', 'failed', 'cancelled'):
            return record
        time.sleep(0.1)
    raise AssertionError(f'job {job_id} did not end')


def _session(command, **kw):
    job_id = jobs.start(launch.LAUNCH_KIND, lambda job: launch.run_session(job, command, entry_id='retail', **kw),
                        params={'entryId': 'retail'})
    return _wait(job_id)


def test_a_session_that_quits(stand_in):
    record = _session(stand_in('0'))
    assert record['status'] == 'done'
    assert record['result']['outcome'] == 'quit' and record['result']['exitCode'] == 0
    assert record['extra']['phase'] == 'running' and record['extra']['pid']


def test_a_session_that_crashes(stand_in):
    result = _session(stand_in('crash'))['result']
    assert result['outcome'] == 'crashed' and result['crashed'] is True


def test_a_refused_disc(stand_in):
    result = _session(stand_in('2'))['result']
    assert result['outcome'] == 'refused' and 'log' in result['message']


def test_a_refusal_shows_what_the_game_printed(stand_in):
    result = _session(stand_in('refuse'))['result']
    assert result['outcome'] == 'refused'
    assert result['message'] == ('The game refused to start this disc: This Melee disc is modded, so Melee '
                                 'Unlocked cannot build its online menus from it.')


def test_a_session_that_restarts_itself(stand_in):
    command = stand_in('restart')
    result = _session(command)['result']
    assert result['relaunched'] == 1
    assert result['exitCode'] == 70 and result['outcome'] == 'fatal'
    assert result['message'] == (f'The game stopped on an error: the stage file is missing. '
                                 f'The log is in {command.cwd}.')


def test_the_game_is_started_without_nucleus_secrets(stand_in, monkeypatch):
    monkeypatch.setenv('NUCLEUS_BACKEND_TOKEN', 'secret-token')
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', 'secret-key')
    command = stand_in('env')
    _session(command)
    names = (command.cwd / 'env.txt').read_text().split('\n')
    assert 'PATH' in {n.upper() for n in names}
    assert not [n for n in names if n.upper().startswith('NUCLEUS_')]


def test_a_disc_that_fails_its_check_starts_nothing(stand_in):
    command = stand_in('0')

    def bad_disc():
        raise launch.PlayError("Your Melee ISO can't be used.")
    record = _session(command, check_disc=bad_disc)
    assert record['status'] == 'failed' and "can't be used" in record['error']
    assert not command.cwd.exists()


def test_the_game_is_never_owned_by_nucleus(monkeypatch, stand_in):
    from core import child_procs
    owned = []
    monkeypatch.setattr(child_procs, 'own', lambda proc, *a, **k: owned.append(proc))
    _session(stand_in('0'))
    assert owned == []


def test_one_game_at_a_time(monkeypatch, play, game, tmp_path):
    monkeypatch.setattr(client, 'supported', lambda: True)
    client.save(str(game))
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'')
    monkeypatch.setattr(launch, 'retail_iso', lambda: iso)
    monkeypatch.setattr(launch, 'slippi_folders', lambda: (None, None))
    monkeypatch.setattr(launch, 'tracker_replay_folder', lambda: None)
    gate = __import__('threading').Event()
    started = []

    def fake_session(job, command, *, entry_id, check_disc=None):
        started.append(command.args)
        job.progress(None, 'Running', phase='running', pid=1)
        gate.wait(10)
        return {'outcome': 'quit'}
    monkeypatch.setattr(launch, 'run_session', fake_session)
    first = launch.launch('vanilla')
    try:
        with pytest.raises(jobs.JobBusy):
            launch.launch('retail')
        with pytest.raises(jobs.JobBusy):
            launch.open_settings_window()
        deadline = time.time() + 5
        while launch.running_entry() != 'vanilla' and time.time() < deadline:
            time.sleep(0.05)
        assert launch.running_entry() == 'vanilla'
    finally:
        gate.set()
        _wait(first)
    assert started[0][-1] == '--vanilla-only'
    assert shelf.get('vanilla')['lastTarget'] == 'mu'


def test_unavailable_targets_are_refused(play):
    with pytest.raises(launch.PlayError, match='Melee Unlocked only'):
        launch.launch('vanilla', target='dolphin')
    with pytest.raises(launch.PlayError):
        launch.launch('retail', target='switch')
    with pytest.raises(shelf.ShelfError):
        launch.launch('../retail')


def test_a_computer_whose_processor_cannot_run_it_is_told_so(play, tmp_path, monkeypatch):
    from tests.backend.test_play_shelf import fake_client
    folder = fake_client(tmp_path / 'MU')
    monkeypatch.setattr(launch.client, 'supported', lambda: True)
    stub_info(monkeypatch, cpu_supported=False)
    shelf.write_settings(clientFolder=str(folder))
    with pytest.raises(launch.PlayError) as caught:
        launch.plan(shelf.get('vanilla'))
    assert str(caught.value) == launch.CPU_MESSAGE
    with pytest.raises(launch.PlayError):
        launch.open_settings_window()
    assert launch.describe_exit(3)[1] == launch.CPU_MESSAGE


def test_launching_without_a_usable_folder_says_where_to_fix_it(play, tmp_path, monkeypatch):
    monkeypatch.setattr(launch.client, 'supported', lambda: True)
    with pytest.raises(launch.PlayError, match='Nucleus Unlocked is not installed yet. Press Install on its card.'):
        launch.plan(shelf.get('vanilla'))
    shelf.write_settings(clientFolder=str(tmp_path / 'gone'))
    with pytest.raises(launch.PlayError, match="can't be used: .* Check it in Unlocked, Settings."):
        launch.plan(shelf.get('vanilla'))


def test_the_replay_viewer_command(tmp_path):
    folder = fake_client(tmp_path / 'MU')
    play_root = tmp_path / 'play'
    command = launch.replay_command(client_folder=folder, replay=tmp_path / 'Game.slp', retail_iso=tmp_path / 'm.iso',
                                    play_root=play_root, extra_args=('--hidden', '--frames', '600'))
    work = play_root / 'data' / '_replay'
    assert command.args == [
        str(folder / 'melee_source.exe'), '--iso', str(tmp_path / 'm.iso'), '--replay', str(tmp_path / 'Game.slp'),
        '--sys-dir', str(folder / 'SysPlayback'), '--threaded-renderer',
        '--settings-path', str(play_root / 'port-settings.ini'), '--user-dir', str(work / 'User' / 'Slippi'),
        '--sysgen-data-dir', str(work), '--replay-dir', str(work / 'Replays'), '--log-file', str(work / 'melee_port.log'),
        '--shader-cache', str(play_root / 'shadercache'), '--fighters-dir', 'none', '--no-remember-iso', '--no-dialogs',
        '--hidden', '--frames', '600']
    assert command.cwd == work and command.console == work / launch.CONSOLE_FILE and command.replay is True
    assert work / 'Replays' in command.make_dirs
    old = launch.replay_command(client_folder=folder, replay=tmp_path / 'Game.slp', retail_iso=tmp_path / 'm.iso',
                                play_root=play_root, options=frozenset())
    assert '--no-dialogs' not in old.args and '--fighters-dir' not in old.args
    # Exit 1 from the viewer is the replay, not the disc.
    assert launch.describe_exit(1, replay=True) == ('disc_error', 'The game could not open the replay.')
    assert launch.describe_exit(4, replay=True)[0] == 'quit'


def test_replays_need_a_folder_that_can_play_them(play, tmp_path, monkeypatch):
    monkeypatch.setattr(launch.client, 'supported', lambda: True)
    assert launch.replay_status() == {'available': False, 'reason': client.NOT_INSTALLED}
    folder = fake_client(tmp_path / 'MU')
    shelf.write_settings(clientFolder=str(folder))
    assert launch.replay_status() == {'available': False, 'reason': launch.REPLAY_NO_PLAYBACK}
    with pytest.raises(launch.PlayError, match='SysPlayback'):
        launch.watch_replay('C:\\Replays\\Game.slp')
    (folder / 'SysPlayback').mkdir()
    monkeypatch.setattr(launch, 'retail_iso', lambda: None)
    monkeypatch.setattr(launch, 'recorded_iso', lambda: None)
    assert launch.replay_status()['reason'] == launch.NEEDS_ISO
    monkeypatch.setattr(launch, 'retail_iso', lambda: tmp_path / 'm.iso')
    assert launch.replay_status() == {'available': True, 'reason': None}
    stub_info(monkeypatch, cpu_supported=False)
    (play / 'client-info.json').unlink()
    assert launch.replay_status() == {'available': False, 'reason': launch.CPU_MESSAGE}


def test_dolphin_gets_a_checked_folder(play, tmp_path):
    for bad in ('', None, '\\\\host\\share\\Slippi', '\\\\?\\C:\\Slippi', 'Slippi'):
        with pytest.raises(launch.PlayError):
            launch.dolphin_command(bad, Path('C:/Melee.iso'))


# --------------------------------------------------------------------------- across a restart of Nucleus

def _noted():
    return json.loads(launch.running_file().read_text(encoding='utf-8'))


def test_a_running_game_is_noted_until_it_ends(stand_in, monkeypatch):
    # running.json names the game while it runs, follows it across its own restart, and is
    # gone once the session ends. It holds only what finds the game again: pid, start time, program.
    noted = []
    remember = launch.remember_running

    def spy(params, pid):
        record = remember(params, pid)
        noted.append((record, _noted()))
        return record
    monkeypatch.setattr(launch, 'remember_running', spy)
    record = _session(stand_in('restart'))
    assert record['result']['relaunched'] == 1 and record['result']['exitCode'] == 70
    assert len(noted) == 2
    (first, on_disk_first), (second, on_disk_second) = noted
    assert first == on_disk_first and second == on_disk_second
    assert first['pid'] != second['pid'] and second['pid'] == record['extra']['pid']
    for written in (first, second):
        assert set(written) == {'entryId', 'pid', 'created', 'exe'} and written['entryId'] == 'retail'
        assert isinstance(written['created'], float) and Path(written['exe']).name.lower().startswith('python')
    assert not launch.running_file().exists()


def test_a_record_that_cannot_be_written_never_stops_the_game(stand_in, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError('in use')
    monkeypatch.setattr(shelf, 'write_json', refuse)
    record = _session(stand_in('0'))
    assert record['status'] == 'done' and record['result']['outcome'] == 'quit'


def _web():
    from flask import Flask
    from play.routes.play import play_bp
    app = Flask(__name__)
    app.register_blueprint(play_bp)
    return app.test_client()


def test_a_game_left_running_is_watched_again_after_a_restart(play, tmp_path, monkeypatch):
    # Nucleus closed while the game ran: the game is a process this Nucleus did not start.
    monkeypatch.setattr(client, 'supported', lambda: True)
    script = tmp_path / 'stand_in.py'
    script.write_text(STAND_IN, encoding='utf-8')
    python = getattr(sys, '_base_executable', None) or sys.executable
    work = shelf.data_dir(shelf.get('retail'))
    work.mkdir(parents=True)
    subprocess.run([python, '-I', str(script), 'spawn'], cwd=work, check=True, timeout=30)
    pid = int((work / 'child.pid').read_text())
    facts = launch.process_facts(pid)
    assert facts is not None
    created, exe = facts
    shelf.write_json(launch.running_file(), {'entryId': 'retail', 'pid': pid, 'created': created, 'exe': exe})
    try:
        job_id = launch.reattach()
        assert job_id
        assert jobs.get(job_id)['params'] == {'entryId': 'retail', 'target': 'mu', 'reattached': True}
        assert launch.running_entry() == 'retail'
        assert _web().get('/api/play/shelf').get_json()['running'] == 'retail'
        # The same game is noted again, for the next restart.
        assert _noted() == {'entryId': 'retail', 'pid': pid, 'created': created, 'exe': exe}
        record = _wait(job_id)
    finally:
        left = launch.same_process(pid, created, exe)
        if left is not None:            # only the stand-in this test started, by pid and start time
            left.kill()
    assert record['status'] == 'done'
    result = record['result']
    assert result['reattached'] is True and result['outcome'] == 'fatal' and result['exitCode'] == 70
    assert result['message'] == f'The game stopped on an error: the stage file is missing. The log is in {work}.'
    assert not launch.running_file().exists() and launch.running_entry() is None


def test_a_reused_pid_is_never_taken_for_the_game(play, tmp_path, monkeypatch):
    monkeypatch.setattr(client, 'supported', lambda: True)
    started = []
    monkeypatch.setattr(launch.jobs, 'start', lambda *a, **k: started.append(a) or 'job')
    # A live process (this test's own) stands for whatever Windows gave the game's pid to.
    me = os.getpid()
    created, exe = launch.process_facts(me)
    assert launch.same_process(me, created, exe) is not None
    python = getattr(sys, '_base_executable', None) or sys.executable
    gone = subprocess.Popen([python, '-I', '-c', 'import time; time.sleep(0.5)'])
    gone_facts = launch.process_facts(gone.pid)
    gone.wait(timeout=30)
    assert gone_facts is not None and launch.same_process(gone.pid, *gone_facts) is None
    right ={'entryId': 'retail', 'pid': me, 'created': created, 'exe': exe}
    records = [
        {**right, 'created': created - 30},                         # another process with that pid
        {**right, 'created': created + 1},
        {**right, 'exe': str(tmp_path / 'melee_source.exe')},       # another program
        {'entryId': 'retail', 'pid': gone.pid, 'created': gone_facts[0], 'exe': gone_facts[1]},   # ended
        {**right, 'entryId': '0123456789ab'},                       # that game is not on the shelf now
        {'pid': me, 'created': created, 'exe': exe},                # no session named
        {**right, 'pid': str(me)}, {**right, 'pid': True}, {**right, 'pid': -1},
        {**right, 'created': 'yesterday'}, {**right, 'created': None}, {**right, 'exe': ''}, {**right, 'exe': 7},
    ]
    for record in records:
        shelf.write_json(launch.running_file(), record)
        assert launch.reattach() is None, record
        assert not launch.running_file().exists()
    launch.running_file().write_text('not json', encoding='utf-8')
    assert launch.reattach() is None and not launch.running_file().exists()
    assert launch.reattach() is None                                # nothing noted at all
    monkeypatch.setattr(client, 'supported', lambda: False)        # not on this platform
    shelf.write_json(launch.running_file(), right)
    assert launch.reattach() is None and not launch.running_file().exists()
    assert started == []


def test_the_replay_viewer_and_the_settings_window_are_found_again(play, monkeypatch):
    monkeypatch.setattr(client, 'supported', lambda: True)
    me = os.getpid()
    created, exe = launch.process_facts(me)
    process, command, params, label = launch._found_again({'replay': True, 'pid': me, 'created': created, 'exe': exe})
    assert process.pid == me and params == {'entryId': None, 'replay': True, 'reattached': True}
    work = play / 'data' / '_replay'
    assert command.cwd == work and command.replay is True and label == 'Watch a replay'
    assert command.args == [exe, '--log-file', str(work / launch.LOG_FILE)]
    process, command, params, label = launch._found_again(
        {'settingsWindow': True, 'pid': me, 'created': created, 'exe': exe})
    assert params == {'entryId': None, 'settingsWindow': True, 'reattached': True}
    work = play / 'data' / '_settings'
    assert command.cwd == work and command.replay is False and label == 'Game settings'
    assert command.args == [exe, '--log-file', str(work / launch.SETTINGS_LOG_FILE)]
    # The folders come from the session, never from the record.
    found = launch._found_again({'entryId': 'retail', 'pid': me, 'created': created, 'exe': exe,
                                 'cwd': 'C:\\Windows', 'log': 'C:\\Windows\\x.log'})
    assert found[1].cwd == shelf.data_dir(shelf.get('retail'))
    assert found[2] == {'entryId': 'retail', 'target': 'mu', 'reattached': True} and found[3] == 'Play Nucleus Unlocked'


# --------------------------------------------------------------------------- the game's settings, seeded once

def _ready(game, tmp_path, monkeypatch):
    monkeypatch.setattr(launch.client, 'supported', lambda: True)
    monkeypatch.setattr(launch, 'retail_iso', lambda: tmp_path / 'melee.iso')
    shelf.write_settings(clientFolder=str(game))


def test_the_melee_unlocked_settings_are_copied_into_play_once(play, game, tmp_path, monkeypatch):
    _ready(game, tmp_path, monkeypatch)
    assert shelf.game_settings_status(game) == {'exists': False, 'seededAt': None, 'canSeed': False}   # none there
    (game / 'port-settings.ini').write_text('[Graphics]\nresolution=4\n', encoding='utf-8')
    assert shelf.game_settings_status(game) == {'exists': False, 'seededAt': None, 'canSeed': True}
    command = launch.plan(shelf.get('vanilla'))
    target = play / 'port-settings.ini'
    assert command.args[command.args.index('--settings-path') + 1] == str(target)
    assert target.read_text(encoding='utf-8') == '[Graphics]\nresolution=4\n'
    status = shelf.game_settings_status(game)
    assert status['exists'] is True and status['canSeed'] is False and isinstance(status['seededAt'], float)
    # Play's copy is its own from then on: a change in the folder is not copied again, nor once Play's is gone.
    (game / 'port-settings.ini').write_text('[Graphics]\nresolution=1\n', encoding='utf-8')
    launch.plan(shelf.get('vanilla'))
    assert target.read_text(encoding='utf-8') == '[Graphics]\nresolution=4\n'
    target.unlink()
    launch.plan(shelf.get('retail'))
    assert not target.exists() and shelf.game_settings_status(game)['canSeed'] is False
    assert (game / 'port-settings.ini').read_text(encoding='utf-8') == '[Graphics]\nresolution=1\n'   # untouched


def test_settings_play_has_are_kept_and_a_failed_copy_never_stops_a_game(play, game, tmp_path, monkeypatch):
    _ready(game, tmp_path, monkeypatch)
    (game / 'port-settings.ini').write_text('theirs', encoding='utf-8')
    play.mkdir(parents=True, exist_ok=True)
    (play / 'port-settings.ini').write_text('mine', encoding='utf-8')
    launch.plan(shelf.get('vanilla'))
    assert (play / 'port-settings.ini').read_text(encoding='utf-8') == 'mine'
    assert shelf.game_settings_status(game) == {'exists': True, 'seededAt': None, 'canSeed': False}
    (play / 'port-settings.ini').unlink()

    def refuse(*args, **kwargs):
        raise PermissionError('in use')
    monkeypatch.setattr(shelf.shutil, 'copyfile', refuse)
    launch.plan(shelf.get('vanilla'))                     # starts with the game's defaults
    assert not (play / 'port-settings.ini').exists() and shelf.game_settings_status(game)['seededAt'] is None
    monkeypatch.undo()
    _ready(game, tmp_path, monkeypatch)
    monkeypatch.setattr(shelf, 'play_root', lambda: play)
    stub_info(monkeypatch)
    (game / 'port-settings.ini').write_bytes(b'x' * (shelf.SETTINGS_SEED_MAX + 1))       # not a settings file
    assert shelf.game_settings_status(game)['canSeed'] is False
    assert shelf.seed_game_settings(game) is False and not list(play.glob('port-settings.ini*'))
