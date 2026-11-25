"""
The Nucleus game client Play installs and keeps up to date itself (the managed client).

Where it lives::

    <data>/nucleus-client/          beside <data>/play, never inside it: client.check_folder refuses a client
                                    folder inside Play's data (the game keeps its saves there)
      state.json                    the active version, one verified and waiting for the game to close, and
                                    the last failure, in plain words
      versions/<version>-<8 hex>/   one verified client each; the active one is what every game starts
      staging/<32 hex>/             an unpack in progress (owned by its job: removed on a failure, a Cancel
                                    or a crash, see core/jobs.py cleanup)
      downloads/<32 hex>.zip        a download in progress (likewise)

Nothing here reads or writes Play's saves, its settings (play/port-settings.ini) or the player's disc.

Install and update are one job (kind ``play_client_install``, one at a time), in order:

  1. read the signed feed (play/client_feed.py) and check its signature, schema and trusted origin;
     refuse when this SSBM Nucleus is older than the feed's ``minAppVersion``;
  2. download the sidecar file list (length and SHA-256 pinned by the feed) and the ZIP into a
     temporary file, never more bytes than the feed names, its SHA-256 checked at the end;
  3. unpack into a staging folder, every entry path-checked and bounded, every file compared with
     the file list as it is written, and no file missing or extra;
  4. move the staged folder into versions/, then ask its melee_source.exe ``--print-info`` as a
     hand-picked folder is asked (client.check_folder), but also require a release build
     (``public_build`` and ``game_public_build`` true; a hand-picked folder need not be one), and
     compare the version it reports;
  5. switch: state.json names the new folder as active, in one atomic write. While a game, a replay
     or the game's settings window is running, the verified folder waits as ``pending`` and is
     switched to as soon as nothing runs (``settle``, called on every status read and launch).

A failure anywhere before step 5 leaves the active version as it was and records the reason. The
previous version stays on disk until a later job or the next start of Nucleus finds that no game
runs from it (``purge``). A hand-picked client folder (Play settings, developer option) still wins
over the managed one (client.require).
"""

import logging
import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from core import jobs
from play import client, client_feed, shelf

logger = logging.getLogger(__name__)

KIND = 'play_client_install'
LAUNCH_KIND = 'play_launch'           # play/launch.py LAUNCH_KIND (not imported: launch imports client)
ROOT_NAME = 'nucleus-client'
STATE_FILE = 'state.json'
VERSIONS_DIR, STAGING_DIR, DOWNLOADS_DIR = 'versions', 'staging', 'downloads'
CHECK_EVERY = 30 * 60                 # seconds a feed check is believed before the page asks again
SPACE_MARGIN = 256 * 1024 * 1024      # left free after an install

_VERSION_DIR = re.compile(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})-[0-9a-f]{8}')
_TOKEN = re.compile(r'[0-9a-f]{32}')
_lock = threading.RLock()
_check_lock = threading.Lock()
_checked = {'at': None, 'offer': None, 'error': None}      # the last feed check (memory only)


class InstallError(Exception):
    """Why an install or update cannot start or did not finish, in plain words."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def managed_root() -> Path:
    """<data>/nucleus-client, the sibling of Play's own folder (shelf.play_root, <data>/play). Read at call
    time from play_root, so a test that points Play at a temporary folder moves this with it."""
    return Path(shelf.play_root()).parent / ROOT_NAME


def make_fetcher(src):
    """The network side (tests hand in a stand-in)."""
    return client_feed.Fetcher(src)


def app_version():
    """This SSBM Nucleus's version (electron/main.js hands it to the backend), or None."""
    return os.environ.get('NUCLEUS_APP_VERSION') or None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# --------------------------------------------------------------------------- state.json

def _read():
    root = managed_root()
    if not (root / STATE_FILE).exists():
        return {}
    try:
        return shelf.read_json(root / STATE_FILE, {})
    except shelf.ShelfError:
        return {}


def _write(state):
    shelf.write_json(managed_root() / STATE_FILE, state)


def _folder_of(record):
    """The versions/ folder a state record names, when it is one of ours and is there; else None."""
    if not isinstance(record, dict):
        return None
    name = record.get('dir')
    if not isinstance(name, str) or not _VERSION_DIR.fullmatch(name):
        return None
    if client_feed.parse_version(record.get('version')) is None or not name.startswith(record['version'] + '-'):
        return None
    folder = managed_root() / VERSIONS_DIR / name
    try:
        if folder.is_symlink() or not folder.is_dir():
            return None
    except OSError:
        return None
    return folder


def _public(record):
    folder = _folder_of(record)
    if folder is None:
        return None
    return {'version': record['version'], 'folder': str(folder), 'installedAt': record.get('installedAt'),
            'commit': record.get('commit')}


def _session_running():
    """Whether Play has a game, a replay or the game's settings window running (a play_launch job)."""
    return jobs.active_job(LAUNCH_KIND) is not None


def _activate(record):
    """Make `record` the active version now, or keep it as pending while a session runs. -> 'active' | 'pending'."""
    with _lock:
        state = _read()
        if _session_running():
            state['pending'] = record
            _write(state)
            logger.info('Play: Nucleus %s is ready; it is used once the game closes', record['version'])
            return 'pending'
        state['active'] = record
        state.pop('pending', None)
        _write(state)
    logger.info('Play: Nucleus %s is now the active client', record['version'])
    return 'active'


def settle():
    """Switch to a verified pending version once nothing runs. Never raises."""
    try:
        with _lock:
            state = _read()
            pending = state.get('pending')
            if pending is None:
                return
            if _folder_of(pending) is None:
                state.pop('pending', None)
                _write(state)
                return
            if _session_running():
                return
            state['active'] = pending
            state.pop('pending', None)
            _write(state)
        logger.info('Play: the game closed; Nucleus %s is now the active client', pending['version'])
    except Exception:  # noqa: BLE001 - a status read or a launch never fails on this
        logger.warning('Play: the waiting Nucleus version could not be switched to', exc_info=True)


def active_folder():
    """The active managed client's folder (not yet probed: client.check_folder does that), or None."""
    settle()
    return _folder_of(_read().get('active'))


def _set_error(message, *, action=None, version=None):
    with _lock:
        state = _read()
        if message is None:
            if 'lastError' not in state:
                return
            state.pop('lastError', None)
        else:
            state['lastError'] = {'message': str(message)[:500], 'action': action, 'version': version, 'at': _now()}
        _write(state)


# --------------------------------------------------------------------------- what the page reads

def status() -> dict:
    """The managed client as the Play page shows it.

    state: 'not_installed' | 'installing' | 'installed' | 'failed' (a first install that did not finish).
    installed: {version, folder, installedAt, commit} or None; pending: the same for a verified version
    waiting for the game to close; available: the newest offer the last feed check saw (version, size,
    notes, minAppVersion, appTooOld) or None; updateAvailable: it is newer than the installed one;
    job: {id, action, progress, detail, phase} while installing; error: the last failure in plain words
    (errorAction 'install' | 'update'); checkError: why the last feed check failed."""
    settle()
    state = _read()
    installed = _public(state.get('active'))
    pending = _public(state.get('pending'))
    offer = _checked['offer']
    available = offer.public(app_version()) if offer is not None else None
    have = client_feed.parse_version((pending or installed or {}).get('version'))
    update = bool(installed and offer is not None and have is not None
                  and client_feed.parse_version(offer.version) > have)
    job = jobs.active_job(KIND)
    error = state.get('lastError') if isinstance(state.get('lastError'), dict) else None
    if job is not None:
        name = 'installing'
    elif installed:
        name = 'installed'
    elif error:
        name = 'failed'
    else:
        name = 'not_installed'
    out = {
        'state': name, 'installed': installed, 'pending': pending, 'available': available,
        'updateAvailable': update, 'job': None,
        'error': error.get('message') if error and job is None else None,
        'errorAction': error.get('action') if error and job is None else None,
        'checkError': _checked['error'], 'checkedAt': _checked['at'],
        'testFeed': client_feed.source().test,
    }
    if job is not None:
        snap = job.snapshot()
        out['job'] = {'id': snap['id'], 'action': snap['params'].get('action'), 'progress': snap['progress'],
                      'detail': snap['detail'], 'phase': snap['extra'].get('phase')}
    return out


def check(force=False) -> dict:
    """Read the feed (at most every CHECK_EVERY seconds unless `force`) and return status(). Never raises:
    a feed that cannot be read is reported as checkError."""
    with _check_lock:
        at = _checked['at']
        fresh = at is not None and 0 <= time.time() - at < CHECK_EVERY
        if force or not fresh:
            try:
                offer = client_feed.fetch_offer(make_fetcher(client_feed.source()))
                _checked.update(offer=offer, error=None)
            except client_feed.FeedError as e:
                _checked.update(error=str(e))
            except Exception as e:  # noqa: BLE001 - said plainly, logged in full
                logger.warning('Play: the client feed could not be checked', exc_info=True)
                _checked.update(error=f'The client feed could not be checked ({type(e).__name__}).')
            _checked['at'] = time.time()
    return status()


# --------------------------------------------------------------------------- the job

def _inside_root(value):
    """`value` as a path when it is inside managed_root() (an owned item from a job record), else None."""
    try:
        path = Path(value)
        root = managed_root().resolve()
        resolved = path.resolve()
    except (OSError, TypeError, ValueError):
        return None
    return path if root in resolved.parents else None


def _remove(path: Path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _cleanup(name, value):
    """core/jobs cleanup: what an install job still held when it ended or the process died."""
    path = _inside_root(value)
    if path is None or not path.exists():
        return None
    if name == 'version':
        state = _read()
        if path.name in {(state.get(k) or {}).get('dir') for k in ('active', 'pending')}:
            return None                      # it was switched to after all
    _remove(path)
    return None


jobs.register_kind(KIND, label='Install Nucleus Unlocked', cleanup=_cleanup)


class _Ticker:
    """job.progress at most every 0.2 s (each call is a socket event)."""

    def __init__(self, job):
        self.job, self.last = job, 0.0

    def __call__(self, fraction, detail, phase, force=False):
        now = time.monotonic()
        if force or now - self.last >= 0.2:
            self.last = now
            self.job.progress(fraction, detail, phase=phase)


def _megabytes(count):
    return f'{count / (1024 * 1024):.0f} MB'


def _need_space(root: Path, need: int):
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        return
    if free < need + SPACE_MARGIN:
        drive = os.path.splitdrive(str(root.resolve()))[0] or str(root)
        raise InstallError(f'There is not enough free space on {drive} to install Nucleus Unlocked: it needs about '
                           f'{(need + SPACE_MARGIN) / 1e9:.1f} GB free.')


def _run(job, action):
    try:
        return _install(job, action)
    except jobs.Cancelled:
        raise
    except (InstallError, client_feed.FeedError) as e:
        _set_error(str(e), action=action, version=job.params.get('version'))
        raise
    except Exception as e:  # noqa: BLE001 - every failure leaves a plain reason
        logger.exception('Play: installing Nucleus failed')
        message = f'Installing Nucleus Unlocked failed: {e}'
        _set_error(message, action=action, version=job.params.get('version'))
        raise InstallError(message) from e


def _install(job, action):
    root = managed_root()
    for sub in (VERSIONS_DIR, STAGING_DIR, DOWNLOADS_DIR):
        (root / sub).mkdir(parents=True, exist_ok=True)
    purge(own_job=True)
    _set_error(None)
    tick = _Ticker(job)
    tick(0.0, 'Checking the latest Nucleus Unlocked...', 'checking', force=True)
    fetcher = make_fetcher(client_feed.source())
    offer = client_feed.fetch_offer(fetcher)
    _checked.update(offer=offer, error=None, at=time.time())
    job.params['version'] = offer.version
    if offer.public(app_version())['appTooOld']:
        raise InstallError(f'Nucleus Unlocked {offer.version} needs SSBM Nucleus {offer.min_app_version} or newer. '
                           'Update SSBM Nucleus first (Settings, Updates), then install again.')
    installed = _read().get('active')
    have = client_feed.parse_version((installed or {}).get('version')) if _folder_of(installed) else None
    if action == 'update' and have is not None and client_feed.parse_version(offer.version) <= have:
        return {'outcome': 'current', 'version': installed['version']}
    job.check_stop()

    files = client_feed.fetch_file_list(fetcher, offer)
    _need_space(root, offer.size + files.total)
    token = secrets.token_hex(16)
    download = root / DOWNLOADS_DIR / f'{token}.zip'
    staging = root / STAGING_DIR / token
    job.own('download', str(download))
    tick(0.02, f'Downloading Nucleus Unlocked {offer.version}...', 'downloading', force=True)
    done = fetcher.download(offer.url, download, size=offer.size, sha256=offer.sha256, suffix='.zip',
                            should_stop=job.should_stop,
                            progress=lambda got, size: tick(0.02 + 0.78 * got / size,
                                                            f'Downloading {_megabytes(got)} of {_megabytes(size)}...',
                                                            'downloading'))
    if not done:
        raise jobs.Cancelled()
    job.own('staging', str(staging))
    tick(0.8, 'Unpacking and checking every file...', 'unpacking', force=True)
    written = client_feed.extract(download, staging, files, should_stop=job.should_stop,
                                  progress=lambda got, total: tick(0.8 + 0.15 * got / max(total, 1),
                                                                   'Unpacking and checking every file...',
                                                                   'unpacking'))
    if written is None:
        raise jobs.Cancelled()
    _remove(download)
    job.release('download')
    job.check_stop()

    final = root / VERSIONS_DIR / f'{offer.version}-{token[:8]}'
    os.replace(staging, final)
    job.own('version', str(final))
    job.release('staging')
    tick(0.96, 'Starting the new Nucleus Unlocked once to check it...', 'checking', force=True)
    try:
        folder = client.check_folder(final, release=True)
    except client.ClientError as e:
        raise InstallError(f'The new Nucleus Unlocked did not pass its check: {e} Your installed version was kept.')
    said = (client.known_facts(folder) or {}).get('version')
    if said != offer.version:
        raise InstallError(f'The new Nucleus Unlocked says it is version {said or "unknown"}, not {offer.version}. '
                           'Your installed version was kept.')
    record = {'version': offer.version, 'dir': final.name, 'installedAt': _now(),
              'commit': files.commit or offer.commit, 'sha256': offer.sha256}
    outcome = _activate(record)
    job.release('version')
    tick(1.0, f'Nucleus Unlocked {offer.version} is installed.' if outcome == 'active'
         else f'Nucleus Unlocked {offer.version} is ready: it is used once the game closes.', 'done', force=True)
    return {'outcome': 'installed' if outcome == 'active' else 'pending', 'version': offer.version}


def start(action='install') -> str:
    """Start the install (or update) job. Returns its id. Raises InstallError, jobs.JobBusy."""
    if action not in ('install', 'update'):
        raise InstallError('That is not something Nucleus can do to its client.')
    if not client.supported():
        raise InstallError('Nucleus Unlocked is Windows only for now.')
    if action == 'update' and _folder_of(_read().get('active')) is None:
        raise InstallError('Nucleus Unlocked is not installed yet. Install it first.')
    label = 'Update Nucleus Unlocked' if action == 'update' else 'Install Nucleus Unlocked'
    return jobs.start(KIND, lambda job: _run(job, action), label=label, single=True, params={'action': action})


def cancel() -> bool:
    """Ask the running install or update to stop; what it downloaded is removed. False when none runs."""
    job = jobs.active_job(KIND)
    return job is not None and jobs.cancel(job.id)


# --------------------------------------------------------------------------- tidying

def _in_use(folder: Path) -> bool:
    """Whether a running program was started from inside `folder`."""
    try:
        import psutil
    except ImportError:
        return False
    base = os.path.normcase(os.path.realpath(folder)) + os.sep
    for process in psutil.process_iter(['exe']):
        exe = process.info.get('exe')
        if exe and os.path.normcase(os.path.realpath(exe)).startswith(base):
            return True
    return False


def purge(*, own_job=False):
    """Remove what no longer serves: versions that are neither active nor pending and that nothing runs
    from (only while Play runs no session), and staging folders and downloads no job holds. Never raises."""
    try:
        root = managed_root()
        if not root.is_dir() or (not own_job and jobs.active_job(KIND) is not None):
            return
        for sub, pattern in ((STAGING_DIR, _TOKEN), (DOWNLOADS_DIR, None)):
            folder = root / sub
            if not folder.is_dir():
                continue
            for item in folder.iterdir():
                if pattern is None or pattern.fullmatch(item.name):
                    _remove(item)
        with _lock:
            state = _read()
            keep = {(state.get(k) or {}).get('dir') for k in ('active', 'pending')}
            versions = root / VERSIONS_DIR
            if not versions.is_dir() or _session_running():
                return
            for item in versions.iterdir():
                if item.name in keep or not _VERSION_DIR.fullmatch(item.name) or _in_use(item):
                    continue
                logger.info('Play: removing the earlier Nucleus %s', item.name)
                _remove(item)
    except Exception:  # noqa: BLE001 - tidying never stops anything
        logger.warning('Play: the earlier Nucleus versions could not be tidied', exc_info=True)


def startup():
    """At Nucleus's start (app.py): tidy what an earlier run left (purge)."""
    purge()
