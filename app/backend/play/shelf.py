"""
The Play shelf: the games Play lists, and the folders each one owns.

    <data>/play/
      shelf.json          the added games, and what the two built-in ones remember
      settings.json       Play's own settings (the Melee Unlocked folder, client.py)
      client-info.json    what that Melee Unlocked said about itself (--print-info), cached
      port-settings.ini   the game's settings: one file every game on the shelf shares
      shadercache/        one graphics cache for every game
      running.json        the game Play is watching now, so a restarted Nucleus finds it again (launch.py)
      disc-banner-<stamp>.png   your disc's banner, the built-in Vanilla's picture (adding.disc_banner)
      games/<id>/        an added game's files: disc.iso, fighters/, cover.png
      data/<id>/          a game's saves, log and crash files (its working folder)

A shelf entry is a finished, standalone game. Nothing in it points back at the
project it came from (``origin`` is only shown, never used), so an entry keeps
working after that project changes or is deleted.

Replacing an entry with a new build of the same game (``replace``) keeps its id, so its
saves in data/<id> stay, and its place on the shelf. The new build is made in a folder of
its own beside the old one (``reserve``); the entry then records that folder as ``files``
(games/<files>/ instead of games/<id>/) in one atomic write of shelf.json, which is the
swap. Until that write the old entry is untouched; after it the old folder is no longer
referenced and is removed (``discard``).

Which entry a new game replaces is the user's answer to "replace it?", asked when an added
entry already has the new game's name (``same_game``: the name as stored, ignoring case).

Two entries are built in and always there: "Nucleus Unlocked" (id ``retail``: your own disc in the
Melee Unlocked folder's client with everything it has, its Mods menu, online lobbies and
training, with your Slippi account and replay folder) and "Vanilla" (the same client and
disc with ``--vanilla-only``: your saved gameplay mods and those features turned off, a
memory card of its own). They cannot be renamed or removed. Vanilla's picture is your
disc's own banner (adding.disc_banner); Nucleus Unlocked's is drawn by the Play page.

Every id a request names is looked up among the stored entries; a folder path is
only ever made from an entry this module stored, and every stored id is one it
generated (``_new_id``). Names and descriptions are plain text, stored as given
(trimmed and capped) and shown as text. A cover is decoded and re-encoded as a PNG
before it is kept (``encode_cover``).

Writes are atomic: a temporary file beside shelf.json, flushed, then replaced, so a
crash leaves the old shelf or the new one, never half of one.
"""

import copy
import io
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import file_retry
from core import config

logger = logging.getLogger(__name__)

SHELF_FILE = 'shelf.json'
SETTINGS_FILE = 'settings.json'
GAME_SETTINGS_FILE = 'port-settings.ini'
SHADER_CACHE_DIR = 'shadercache'
GAMES_DIR = 'games'
DATA_DIR = 'data'
DISC_FILE = 'disc.iso'
COVER_FILE = 'cover.png'
FIGHTERS_DIR = 'fighters'
TEXTURES_DIR = 'textures'                # a bundle's HD textures, for the Dolphin target

RETAIL_ID = 'retail'
VANILLA_ID = 'vanilla'

TARGET_MU = 'mu'            # Melee Unlocked (the decomp client)
TARGET_DOLPHIN = 'dolphin'  # the user's Slippi Dolphin
TARGETS = (TARGET_MU, TARGET_DOLPHIN)

ENGINE_SOURCE = 'source'    # melee_source.exe with melee_game.dll
ENGINE_COMPAT = 'compat'    # melee_port.exe, the compatibility engine (Static Recomp)
ENGINES = (ENGINE_SOURCE, ENGINE_COMPAT)

MAX_NAME = 80
MAX_DESCRIPTION = 1000
MAX_COVER_BYTES = 8 * 1024 * 1024        # what an upload may be before it is decoded
MAX_COVER_PIXELS = 6000 * 6000           # what a decoded picture may be
COVER_SIZE = 1024                        # the longest side a stored cover keeps

_ADDED_ID = re.compile(r'^[0-9a-f]{12}$')
_COPY_CHUNK = 4 * 1024 * 1024
_SPACE_MARGIN = 256 * 1024 * 1024        # left free after copying a disc

_lock = threading.RLock()

BUILTINS = (
    {
        'id': RETAIL_ID,
        'name': 'Nucleus Unlocked',
        'description': 'Mods, online lobbies and training, built in.',
        'disc': {'kind': 'retail'},
        'targets': {TARGET_MU: {'available': True}, TARGET_DOLPHIN: {'available': True}},
        'defaultTarget': TARGET_MU,
        'engine': ENGINE_SOURCE,
        'options': {},
    },
    {
        'id': VANILLA_ID,
        'name': 'Vanilla',
        'description': 'Melee with nothing changed.',
        'disc': {'kind': 'retail'},
        'targets': {TARGET_MU: {'available': True},
                    TARGET_DOLPHIN: {'available': False, 'reason': 'Vanilla runs on Melee Unlocked only.'}},
        'defaultTarget': TARGET_MU,
        'engine': ENGINE_SOURCE,
        'options': {'vanilla': True},
    },
)
BUILTIN_IDS = tuple(b['id'] for b in BUILTINS)


class ShelfError(Exception):
    """Something the user can fix, in a sentence that says how. `status` is the HTTP answer;
    `code` and `extra` ride along in the answer for the window to act on (``details``)."""

    def __init__(self, message, status=400, *, code=None, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra

    def details(self):
        return {**({'code': self.code} if self.code else {}), **self.extra}


#: ShelfError code: an added entry already has the new game's name (``existing`` names it).
SAME_GAME = 'already_on_shelf'


# --------------------------------------------------------------------------- folders

def play_root() -> Path:
    """<data>/play. Read at call time, so tests can point it at a temporary folder."""
    return Path(config.PROJECT_ROOT) / 'play'


def game_settings_file() -> Path:
    return play_root() / GAME_SETTINGS_FILE


#: settings.json key: when Play's port-settings.ini was copied from the Melee Unlocked folder's own (once).
SETTINGS_SEEDED = 'gameSettingsSeeded'
#: A port-settings.ini larger than this is not a settings file; it is not copied.
SETTINGS_SEED_MAX = 1024 * 1024


def _client_settings(client_folder):
    """The Melee Unlocked folder's own port-settings.ini, when it is a plain file inside that folder."""
    if client_folder is None:
        return None
    folder = Path(client_folder)
    source = folder / GAME_SETTINGS_FILE
    try:
        if source.is_symlink() or not source.is_file() or source.stat().st_size > SETTINGS_SEED_MAX:
            return None
        if source.resolve().parent != folder.resolve():
            return None
    except OSError:
        return None
    return source


def seed_game_settings(client_folder) -> bool:
    """Once: Play has no port-settings.ini of its own yet and never copied one, so the Melee Unlocked
    folder's own one is copied in, and the first game starts with the graphics, controls and audio the user
    already set there. Recorded in settings.json (``SETTINGS_SEEDED``); never again after that, even if Play's
    file is deleted (the game then writes its defaults). Returns whether it copied."""
    with _lock:
        target = game_settings_file()
        if target.exists() or read_settings().get(SETTINGS_SEEDED):
            return False
        source = _client_settings(client_folder)
        if source is None:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.part')
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
        write_settings(**{SETTINGS_SEEDED: {'at': time.time()}})
    logger.info('Play: copied the Melee Unlocked folder\'s own %s into the Play folder (once)', GAME_SETTINGS_FILE)
    return True


def game_settings_status(client_folder=None) -> dict:
    """For Play's settings page: {exists, seededAt, canSeed}. ``canSeed``: the first game will copy the Melee
    Unlocked folder's own settings."""
    exists = game_settings_file().is_file()
    seeded = read_settings().get(SETTINGS_SEEDED)
    seeded_at = seeded.get('at') if isinstance(seeded, dict) else None
    return {'exists': exists, 'seededAt': seeded_at,
            'canSeed': not exists and not seeded and _client_settings(client_folder) is not None}


def shader_cache_dir() -> Path:
    return play_root() / SHADER_CACHE_DIR


def _checked_id(entry):
    """The id of an entry this module stored: a built-in one, or one it generated."""
    entry_id = entry.get('id') if isinstance(entry, dict) else None
    if entry_id in BUILTIN_IDS or (isinstance(entry_id, str) and _ADDED_ID.match(entry_id)):
        return entry_id
    raise ShelfError('That game is not on the shelf.', 404)


def _files_of(entry):
    """The games/ folder name an added entry's files are in: its id, or the folder a replace
    built (``files``), which this module generated too. None for one it did not write."""
    files = entry.get('files') if isinstance(entry, dict) else None
    if files is None:
        entry_id = entry.get('id') if isinstance(entry, dict) else None
        return entry_id if isinstance(entry_id, str) and _ADDED_ID.match(entry_id) else None
    return files if isinstance(files, str) and _ADDED_ID.match(files) else None


def game_dir(entry) -> Path:
    """An added entry's own files (disc, fighters, cover). Built-in entries have none."""
    entry_id = _checked_id(entry)
    if entry_id in BUILTIN_IDS:
        raise ShelfError('That game has no files of its own.', 400)
    files = _files_of(entry)
    if files is None:
        raise ShelfError('That game is not on the shelf.', 404)
    return play_root() / GAMES_DIR / files


def confined(folder: Path) -> Path:
    """`folder` (one game_dir made), once it is checked to resolve inside Play's games folder
    (core.path_safety.resolve_under_root): a link or junction there that leads anywhere else is
    refused, so nothing is written outside an entry's own folder."""
    from core.path_safety import resolve_under_root
    root = play_root() / GAMES_DIR
    try:
        resolve_under_root(root, Path(folder).relative_to(root).as_posix(), field='game folder')
    except ValueError:
        raise ShelfError("That game's folder is not inside the Play folder.", 500)
    return Path(folder)


def data_dir(entry) -> Path:
    """An entry's saves, log and crash files: the game's working folder."""
    return play_root() / DATA_DIR / _checked_id(entry)


def disc_path(entry):
    """The disc an added entry owns, or None for one that plays the user's own disc."""
    disc = entry.get('disc') or {}
    if disc.get('kind') != 'owned':
        return None
    return game_dir(entry) / DISC_FILE


def fighters_dir(entry):
    """An added entry's fighter plugins folder, or None for a built-in entry."""
    if entry.get('id') in BUILTIN_IDS:
        return None
    return game_dir(entry) / FIGHTERS_DIR


def textures_dir(entry):
    """An added entry's texture pack folder (a game added from a bundle), or None for a
    built-in entry."""
    if entry.get('id') in BUILTIN_IDS:
        return None
    return game_dir(entry) / TEXTURES_DIR


def cover_path(entry):
    """An entry's cover picture when it has one, else None."""
    if not entry.get('cover') or entry.get('id') in BUILTIN_IDS:
        return None
    path = game_dir(entry) / COVER_FILE
    return path if path.is_file() else None


# --------------------------------------------------------------------------- json files

def _write_json(path: Path, payload):
    """Atomic: a sibling temporary file, flushed to disk, then replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        file_retry.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_json(path: Path, empty):
    """A json file's contents, or `empty` when there is none. One that cannot be read is
    kept aside (never overwritten) and the store starts again from `empty`."""
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return copy.deepcopy(empty)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        raise ValueError('not an object')
    except ValueError as e:
        aside = path.with_name(f'{path.stem}.unreadable-{int(time.time())}{path.suffix}')
        logger.warning('Play: %s could not be read (%s); kept as %s', path, e, aside.name)
        try:
            os.replace(path, aside)
        except OSError:
            logger.exception('Play: could not keep %s aside', path)
            raise ShelfError(f'{path.name} in the Play folder could not be read.', 500)
        return copy.deepcopy(empty)


def read_json(path: Path, empty):
    """A json object file in the Play folder (another module's own store), or `empty`."""
    with _lock:
        return _read_json(Path(path), empty)


def write_json(path: Path, payload):
    """Write a json object file in the Play folder atomically."""
    with _lock:
        _write_json(Path(path), payload)


_EMPTY_SHELF = {'version': 1, 'entries': [], 'builtins': {}}


def _load():
    data = _read_json(play_root() / SHELF_FILE, _EMPTY_SHELF)
    entries = [e for e in data.get('entries') or [] if isinstance(e, dict)
               and isinstance(e.get('id'), str) and _ADDED_ID.match(e['id'])]
    builtins = data.get('builtins') if isinstance(data.get('builtins'), dict) else {}
    return {'version': 1, 'entries': entries,
            'builtins': {k: v for k, v in builtins.items() if k in BUILTIN_IDS and isinstance(v, dict)}}


def _save(data):
    _write_json(play_root() / SHELF_FILE, data)


def read_settings() -> dict:
    with _lock:
        return _read_json(play_root() / SETTINGS_FILE, {})


def write_settings(**changes) -> dict:
    with _lock:
        settings = _read_json(play_root() / SETTINGS_FILE, {})
        for key, value in changes.items():
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value
        _write_json(play_root() / SETTINGS_FILE, settings)
        return settings


# --------------------------------------------------------------------------- entries

def _builtin(entry_id, remembered):
    base = copy.deepcopy(next(b for b in BUILTINS if b['id'] == entry_id))
    base['builtin'] = True
    base['cover'] = False
    last = (remembered or {}).get('lastTarget')
    if last in base['targets'] and base['targets'][last].get('available'):
        base['lastTarget'] = last
    return base


def entries():
    """Every entry on the shelf, the built-in ones first, as copies."""
    with _lock:
        data = _load()
        out = [_builtin(entry_id, data['builtins'].get(entry_id)) for entry_id in BUILTIN_IDS]
        for entry in data['entries']:
            entry = copy.deepcopy(entry)
            entry['builtin'] = False
            out.append(entry)
        return out


def find(entry_id):
    """The entry with this id, or None. `entry_id` is only compared, never used as a path."""
    if not isinstance(entry_id, str):
        return None
    return next((e for e in entries() if e['id'] == entry_id), None)


def get(entry_id):
    """The entry with this id, or ShelfError 404."""
    entry = find(entry_id)
    if entry is None:
        raise ShelfError('That game is not on the shelf.', 404)
    return entry


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def clean_text(value, limit, *, field):
    """A name or description as stored: a string, trimmed, control characters dropped
    (a newline stays in a description), at most `limit` characters."""
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ShelfError(f'The {field} must be text.')
    keep_newlines = field == 'description'
    text = ''.join(ch for ch in value if ch >= ' ' or (keep_newlines and ch == '\n'))
    return text.strip()[:limit]


def _new_id(data):
    taken = {e['id'] for e in data['entries']} | {_files_of(e) for e in data['entries']}
    while True:
        entry_id = secrets.token_hex(6)
        if entry_id not in taken and not (play_root() / GAMES_DIR / entry_id).exists() \
                and not (play_root() / DATA_DIR / entry_id).exists():
            return entry_id


def reserve():
    """A new entry id and its games folder, made empty and exclusively for it. The entry
    is not on the shelf until ``add`` stores it; ``discard`` drops a reserved one."""
    with _lock:
        data = _load()
        entry_id = _new_id(data)
        folder = play_root() / GAMES_DIR / entry_id
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.mkdir()      # exclusive: an existing folder is never reused
        return entry_id, folder


def discard(folder_id):
    """Remove a games/ folder no entry uses: a reserved one (an add that failed or was
    cancelled) or the one a replaced entry stopped using."""
    if not (isinstance(folder_id, str) and _ADDED_ID.match(folder_id)):
        return
    with _lock:
        if any(_files_of(e) == folder_id for e in _load()['entries']):
            return          # an entry's files: not ours to remove here
        _remove_tree(play_root() / GAMES_DIR / folder_id)


def add(entry):
    """Store a new entry whose folder ``reserve`` made. Returns the stored entry."""
    entry_id = entry.get('id')
    if not (isinstance(entry_id, str) and _ADDED_ID.match(entry_id)):
        raise ShelfError('That game was not reserved on the shelf.', 500)
    stored = copy.deepcopy(entry)
    stored.pop('builtin', None)
    stored.pop('files', None)               # a new entry's files are in games/<id>
    stored['name'] = clean_text(stored.get('name'), MAX_NAME, field='name') or 'Untitled game'
    stored['description'] = clean_text(stored.get('description'), MAX_DESCRIPTION, field='description')
    stored.setdefault('createdAt', _now())
    with _lock:
        data = _load()
        if any(e['id'] == entry_id or _files_of(e) == entry_id for e in data['entries']):
            raise ShelfError('That game is already on the shelf.', 409)
        if not (play_root() / GAMES_DIR / entry_id).is_dir():
            raise ShelfError('That game was not reserved on the shelf.', 500)
        data['entries'].append(stored)
        _save(data)
    stored['builtin'] = False
    return stored


def locked():
    """The shelf's lock, for a caller that must read the shelf and act before it changes
    (launch.py starts a game only while its files are the ones it planned with)."""
    return _lock


def _identity(name):
    """What makes two added games the same game: the name as stored, ignoring case."""
    return (clean_text(name, MAX_NAME, field='name') or 'Untitled game').casefold()


def same_game(name):
    """The added entry a new game called `name` would duplicate ({id, name}), or None. The
    built-in games are never matched: they cannot be replaced."""
    if name is not None and not isinstance(name, str):
        return None
    key = _identity(name)
    with _lock:
        for entry in _load()['entries']:
            stored = entry.get('name') if isinstance(entry.get('name'), str) else ''
            if _identity(stored) == key:
                return {'id': entry['id'], 'name': stored}
    return None


def folder_of(entry_id):
    """The games/ folder name an added entry's files are in now, or None (a built-in or unknown id)."""
    entry = find(entry_id)
    return None if entry is None else files_folder(entry)


def files_folder(entry):
    """The games/ folder name the entry `entry` (a copy read earlier) had its files in, or None
    for a built-in one."""
    if entry.get('builtin') or entry.get('id') in BUILTIN_IDS:
        return None
    return _files_of(entry)


#: What a replace keeps from the entry it replaces (the rest comes from the new build).
_KEPT_ON_REPLACE = ('id', 'name', 'description', 'createdAt')


def replace(entry_id, built, *, files, description=None, keep_cover=True, busy=None):
    """Make the added entry `entry_id` the new build `built` (what the add job found out about
    it), whose files are in the reserved folder games/<files>. Kept: the entry's id (so its saves
    in data/<id>), name, description (unless a new one is given), engine choice, last target
    (while the build still offers it), its place on the shelf, and, with `keep_cover`, its cover
    (copied into the new folder; without one there, the build's own stays). Its fighters folder
    (plugins the user put there) is copied across. The shelf.json write is the swap; nothing of
    the old entry changes before it. `busy()` is asked under the shelf lock just before: true
    (the game is running) refuses. Returns (the stored entry, the folder it no longer uses)."""
    if not (isinstance(files, str) and _ADDED_ID.match(files)):
        raise ShelfError('The new build was not reserved on the shelf.', 500)
    with _lock:
        data = _load()
        index = next((i for i, e in enumerate(data['entries']) if e['id'] == entry_id), None) \
            if isinstance(entry_id, str) else None
        if index is None:
            raise ShelfError('That game is not on the shelf any more.', 404)
        if busy is not None and busy():
            raise ShelfError('That game is running. Close it first.', 409)
        old = data['entries'][index]
        old_files = _files_of(old)
        if old_files is None or files == old_files or any(_files_of(e) == files or e['id'] == files
                                                             for e in data['entries']):
            raise ShelfError('The new build was not reserved on the shelf.', 500)
        old_dir = play_root() / GAMES_DIR / old_files
        new_dir = confined(play_root() / GAMES_DIR / files)
        if not new_dir.is_dir():
            raise ShelfError('The new build was not reserved on the shelf.', 500)

        if keep_cover and old.get('cover') and (old_dir / COVER_FILE).is_file():
            write_cover({'id': files}, (old_dir / COVER_FILE).read_bytes())
        if (old_dir / FIGHTERS_DIR).is_dir() and not (new_dir / FIGHTERS_DIR).exists():
            shutil.copytree(old_dir / FIGHTERS_DIR, new_dir / FIGHTERS_DIR, symlinks=True)

        stored = {k: v for k, v in copy.deepcopy(built).items()
                  if k not in ('builtin', 'files', 'lastTarget', 'cover', *_KEPT_ON_REPLACE)}
        stored.update({k: copy.deepcopy(old[k]) for k in _KEPT_ON_REPLACE if k in old})
        new_description = clean_text(description, MAX_DESCRIPTION, field='description')
        if new_description:
            stored['description'] = new_description
        choice = (old.get('options') or {}).get('engine')
        if choice in ENGINE_CHOICES:
            stored['options'] = {**(stored.get('options') or {}), 'engine': choice}
        last, targets = old.get('lastTarget'), stored.get('targets') or {}
        if last in targets and (targets.get(last) or {}).get('available'):
            stored['lastTarget'] = last
        stored['cover'] = (new_dir / COVER_FILE).is_file()
        stored['files'] = files
        stored['replacedAt'] = _now()
        data['entries'][index] = stored
        _save(data)
    out = copy.deepcopy(stored)
    out['builtin'] = False
    return out, old_files


ENGINE_CHOICES = ('auto', ENGINE_SOURCE, ENGINE_COMPAT)


def update(entry_id, *, name=None, description=None, last_target=None, cover=None, engine_choice=None):
    """Change what may change: an added entry's name, description, cover flag and engine
    choice ('auto', 'source', 'compat'), and any entry's last-used target. Returns the entry as
    stored."""
    if engine_choice is not None and engine_choice not in ENGINE_CHOICES:
        raise ShelfError('That is not an engine Melee Unlocked has.')
    with _lock:
        data = _load()
        if entry_id in BUILTIN_IDS:
            if name is not None or description is not None or cover is not None or engine_choice is not None:
                raise ShelfError('The built-in games cannot be renamed or changed.')
            if last_target is not None:
                entry = _builtin(entry_id, None)
                if last_target not in entry['targets'] or not entry['targets'][last_target].get('available'):
                    raise ShelfError('That game cannot be played there.')
                data['builtins'].setdefault(entry_id, {})['lastTarget'] = last_target
                _save(data)
            return _builtin(entry_id, data['builtins'].get(entry_id))
        entry = next((e for e in data['entries'] if e['id'] == entry_id), None) \
            if isinstance(entry_id, str) else None
        if entry is None:
            raise ShelfError('That game is not on the shelf.', 404)
        if name is not None:
            cleaned = clean_text(name, MAX_NAME, field='name')
            if not cleaned:
                raise ShelfError('A game needs a name.')
            entry['name'] = cleaned
        if description is not None:
            entry['description'] = clean_text(description, MAX_DESCRIPTION, field='description')
        if last_target is not None:
            targets = entry.get('targets') or {}
            if last_target not in targets or not targets[last_target].get('available'):
                raise ShelfError('That game cannot be played there.')
            entry['lastTarget'] = last_target
        if cover is not None:
            entry['cover'] = bool(cover)
        if engine_choice is not None:
            entry['options'] = {**(entry.get('options') or {}), 'engine': engine_choice}
        _save(data)
        out = copy.deepcopy(entry)
        out['builtin'] = False
        return out


def remove(entry_id):
    """Take an added entry off the shelf and delete its files and saves."""
    if entry_id in BUILTIN_IDS:
        raise ShelfError('The built-in games cannot be removed.')
    with _lock:
        data = _load()
        entry = next((e for e in data['entries'] if e['id'] == entry_id), None) \
            if isinstance(entry_id, str) else None
        if entry is None:
            raise ShelfError('That game is not on the shelf.', 404)
        games, saves = game_dir(entry), data_dir(entry)
        data['entries'] = [e for e in data['entries'] if e['id'] != entry_id]
        _save(data)
    # Off the shelf first: a file Windows still holds open is left for later, never a
    # shelf entry pointing at half a folder.
    for folder in (games, saves):
        _remove_tree(folder)
    return entry


def _remove_tree(folder: Path):
    def retry_writable(func, path, _exc):
        try:
            os.chmod(path, 0o666)
            func(path)
        except OSError:
            logger.warning('Play: could not remove %s', path)
    if folder.exists():
        shutil.rmtree(folder, onexc=retry_writable)


# --------------------------------------------------------------------------- files

def link_or_copy(source: Path, destination: Path, *, progress=None, should_stop=None):
    """Put `source` at `destination` (which must not exist): a hard link when both are on
    one drive and the file system allows it (instant, no extra space), else a copy made
    beside it and renamed into place when complete. Returns 'linked' or 'copied'."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ShelfError(f'{destination.name} is already there.', 500)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return 'linked'
    except OSError as e:
        logger.info('Play: hard link %s -> %s not possible (%s); copying', source, destination, e)
    total = source.stat().st_size or 1
    free = shutil.disk_usage(destination.parent).free
    if free < total + _SPACE_MARGIN:
        raise ShelfError(f'Not enough free space for the disc: it needs {total / 1e9:.1f} GB '
                         f'and the drive Nucleus keeps its data on has {free / 1e9:.1f} GB free.', 507)
    partial = destination.with_name(destination.name + '.part')
    done = 0
    try:
        with open(source, 'rb') as reader, open(partial, 'xb') as writer:
            while True:
                if should_stop is not None and should_stop():
                    raise ShelfError('Cancelled.', 409)
                chunk = reader.read(_COPY_CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done / total)
            writer.flush()
            os.fsync(writer.fileno())
        file_retry.replace(partial, destination)
    except BaseException:
        try:
            partial.unlink()
        except OSError:
            pass
        raise
    return 'copied'


def encode_cover(raw: bytes) -> bytes:
    """An uploaded picture as the PNG the shelf keeps: size-checked before it is decoded,
    decoded, at most COVER_SIZE on its longest side, re-encoded. Raises ShelfError."""
    if not raw:
        raise ShelfError('No picture was sent.')
    if len(raw) > MAX_COVER_BYTES:
        raise ShelfError(f'That picture is too large. The limit is {MAX_COVER_BYTES // (1024 * 1024)} MB.', 413)
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > MAX_COVER_PIXELS:
                raise ShelfError('That picture is too large. Use one under 6000 by 6000 pixels.', 413)
            image.load()
            picture = image.convert('RGBA')
    except ShelfError:
        raise
    except Exception as e:  # noqa: BLE001 - any decoder failure means "not a picture we read"
        logger.info('Play: cover upload not decoded: %s', e)
        raise ShelfError('That file is not a picture Nucleus can read. Use a PNG, JPEG, GIF or WebP.')
    picture.thumbnail((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    picture.save(out, format='PNG')
    return out.getvalue()


def write_cover(entry, png: bytes):
    """Keep `png` (from encode_cover) as an added entry's cover, in its own folder only. Atomic."""
    folder = confined(game_dir(entry))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / COVER_FILE
    handle, temporary = tempfile.mkstemp(dir=str(folder), prefix=COVER_FILE + '.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(png)
            stream.flush()
            os.fsync(stream.fileno())
        file_retry.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def set_cover(entry_id, raw: bytes):
    """Decode and keep an uploaded cover for an added entry. Returns the entry."""
    if entry_id in BUILTIN_IDS:
        raise ShelfError('The built-in games keep their own pictures.')
    png = encode_cover(raw)
    with _lock:             # into the folder the entry uses now, not one a replace just retired
        entry = get(entry_id)
        write_cover(entry, png)
        return update(entry_id, cover=True)


def public(entry):
    """An entry as the Play page reads it: what it shows and what it can do, no paths."""
    out = {key: copy.deepcopy(entry.get(key)) for key in (
        'id', 'name', 'description', 'createdAt', 'origin', 'disc', 'plugins', 'engine',
        'engineReason', 'targets', 'defaultTarget', 'lastTarget', 'options', 'builtin')
        if entry.get(key) is not None}
    disc = out.get('disc')
    if isinstance(disc, dict):
        out['disc'] = {k: v for k, v in disc.items() if k in ('kind', 'size', 'sha256', 'how')}
    if isinstance(entry.get('fighters'), list):
        out['fighters'] = [{k: f.get(k) for k in ('name', 'file', 'code', 'why')}
                           for f in entry['fighters'] if isinstance(f, dict)]
    pack = entry.get('texturePack')
    if isinstance(pack, dict) and isinstance(pack.get('count'), int):
        out['textures'] = pack['count']
    out['hasCover'] = cover_path(entry) is not None
    out['removable'] = not entry.get('builtin')
    return out
