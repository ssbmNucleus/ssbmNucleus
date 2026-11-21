r"""The Tracker store (``storage/nucleome.db``) in a Vault backup.

A backup carries a sanitized snapshot of the store: the replay index, combos, deep stats, clips, rank history,
coach chats and Tracker settings. It never carries this computer's sign-ins, the cloud-account state bound to
them, or its folder settings, and a restore never takes those from a backup: after a restore they are this
computer's own, or absent if it had none (security review 11-19, M2: a shared backup handed over the account, a
crafted one swapped it). Nor does a restore take a network path (``\\server\share``) from a backup anywhere: the
app opens the paths it stores, and opening one on a stranger's server hands it this computer's Windows sign-in.

* :func:`snapshot` copies the live store for a backup (SQLite's backup API: a consistent read, WAL included,
  that never writes the live store) and sanitizes the copy.
* :func:`clean_incoming` sanitizes the store a backup brought, an old 0.8.x backup's raw file and WAL included.
* :func:`carry_sign_in` puts this computer's sign-in and folder rows into a store a replace restore publishes.
* :func:`merge_into` adds a backup's Tracker data to this computer's store for a merge restore.

Sanitizing drops every trigger, view and virtual table (the app makes none: a trigger could rewrite the token
the app stores later), the cloud ledgers (:data:`SYNC_TABLES`), and rebuilds ``kv`` with the app's own definition
without :data:`LOCAL_KV_KEYS`; then VACUUM, so no deleted row is left in a free page. A store a backup brought
also loses every row that names a network path, and every Combo Video song whose file name is not one the app
makes (:func:`_drop_foreign_paths`).

Standard library only: ``vault/routes/vault_backup.py`` calls it, and its restore tests load it on its own.
"""
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)

DB_NAME = 'nucleome.db'

#: The sign-ins in the store's kv: never in a backup, never taken from one, and a replace restore keeps this
#: computer's. tests/backend/test_vault_backup_local_state.py checks the names against their owners.
SECRET_KV_KEYS = (
    'vault_app_token',   # tracker/cloud/vault_jobs.TOKEN_KEY: the Patreon app token, the key to the cloud library
    'friends_session',   # shared/account/session.SESSION_KEY: the Discord sign-in (Supabase access + refresh token)
)
#: Kept per sign-in beside it, so they follow it the same way.
ACCOUNT_KV_KEYS = (
    'vault_pledge_active',          # vault_jobs.PLEDGE_KEY: the linked Patreon's pledge, mirrored for the token
    'vault_paid_defaults_applied',  # vault_jobs.PAID_DEFAULTS_KEY: once per install
)
#: The cloud ledger and its checkpoints, which the app itself clears on any sign-in change
#: (vault_jobs.clear_account_sync_state). They name the account's cloud copies by this store's game ids, so no
#: backup carries them and a replace restore starts them empty: the next sync rebuilds them from the account.
#: Then this computer's own bookkeeping against the cloud copy: Slippi codes removed here before the first agreed
#: list (vault_client.CODES_REMOVED_KEY, read against vault_codes_base) and the day-long pause after the server
#: refused raw uploads (vault_client.RAW_RETRY_AFTER_KEY). Both start empty again, as on a new install.
SYNC_KV_KEYS = ('vault_last_sync_at', 'combos_wire_refresh', 'combos_wire_refresh_pos', 'vault_codes_base',
                'vault_codes_removed', 'vault_raw_retry_after')
SYNC_TABLES = ('vault_objects', 'vault_upload_history', 'vault_shared_links',
               'vault_raw', 'vault_raw_conv', 'vault_raw_combos')
#: Folders on this computer (storage_relocation.TRACKER_PATH_KEYS, which a data-folder move rewrites): they mean
#: nothing on another PC, and one from a crafted backup could name a stranger's server.
PATH_KV_KEYS = ('replay_root_override', 'recording_dir')

#: Never in a backup, never taken from one.
LOCAL_KV_KEYS = SECRET_KV_KEYS + ACCOUNT_KV_KEYS + SYNC_KV_KEYS + PATH_KV_KEYS
#: What a replace restore carries from this computer's store into the restored one.
CARRIED_KV_KEYS = SECRET_KV_KEYS + ACCOUNT_KV_KEYS + PATH_KV_KEYS

#: The columns that hold a replay's path (storage_relocation.TRACKER_PATH_TABLES).
PATH_COLUMNS = {'games': 'path', 'vault_hashes': 'path'}
#: A Combo Video song's file is ``<id><ext>`` in the Vault (tracker/video/combo_video/store.py, ALLOWED_EXTS).
SONG_EXTS = ('.mp3', '.wav', '.ogg', '.m4a', '.flac')
#: Two slashes first is a network path (``\\server\share``, ``//server/share``, ``\\?\UNC\...``), except the long
#: and device forms of a drive (``\\?\C:\``, ``\\.\C:\``).
_NETWORK_PATH = re.compile(r'\s*[\\/]{2}(?![?.][\\/][A-Za-z]:)')

#: tracker/store/indexer.py's kv, the one table sanitizing rebuilds from the app's own definition.
KV_SCHEMA = 'CREATE TABLE {name} (key TEXT PRIMARY KEY, value TEXT)'

# How a merge restore adds a backup's rows; nothing else in this computer's store changes.
_GAMES = 'games'                                       # by replay path; the backup's ids are renumbered
_GAME_ROWS = ('game_players', 'combos', 'clip_refs', 'deep_rows', 'vault_skips', 'vault_raw_skips')
_NEW_ROWS = {'rank_samples': ('code', 'at'), 'coach_chats': ('created_at',)}    # rows this store lacks, by key
_CACHE_ROWS = ('vault_hashes',)                        # by primary key, this computer's row first
#: Every table a merge adds rows to.
MERGED_TABLES = (_GAMES, *_GAME_ROWS, *_NEW_ROWS, *_CACHE_ROWS, 'kv')
#: Not merged (a replace restores them): Combo Video's songs and timelines name their files in the Vault by row id.
NOT_MERGED = ('cv_songs', 'cv_timelines')
#: kv rows about this store's own rows, so a merge keeps this computer's: the combo frame basis
#: (tracker/combos/combo_index.py) and the end-of-game stock caches, keyed by game id (tracker/routes/replays.py).
_STORE_KV_KEYS = ('combos_frame_basis',)
_STORE_KV_PREFIX = 'stocks:'


class TrackerStoreError(ValueError):
    """A Tracker store that cannot be read or sanitized."""


def _ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def _marks(values):
    return ', '.join('?' for _ in values)


def _rollback(conn):
    """Roll back, unless SQLite already did (it does on some errors, and a second ROLLBACK would hide the first)."""
    if conn.in_transaction:
        conn.execute('ROLLBACK')


def _private(path):
    """A connection to a store copy only this restore or backup uses. The copy may come from a crafted backup,
    so SQLite's defensive settings are on and its schema is not trusted to call functions."""
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        if hasattr(sqlite3, 'SQLITE_DBCONFIG_DEFENSIVE'):
            conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.execute('PRAGMA cell_size_check=ON')
    except BaseException:
        conn.close()            # an open handle would pin the file on Windows
        raise
    return conn


def _read_only(path):
    """Read a live store without writing it: a WAL reader sees every committed row and never checkpoints."""
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)


def _tables(conn, schema='main'):
    return {name for (name,) in conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def _columns(conn, table, schema='main'):
    """[(name, declared type, primary-key position)] of a table."""
    return [(row[1], (row[2] or '').upper(), row[5])
            for row in conn.execute(f'PRAGMA {schema}.table_info({_ident(table)})')]


def _rowid_alias(columns):
    keys = [(name, kind) for name, kind, pk in columns if pk]
    return keys[0][0] if len(keys) == 1 and keys[0][1] == 'INTEGER' else None


def _sanitize(path, incoming=False):
    """Make a private store copy fit to leave or enter this computer (module docstring), in place. ``incoming``:
    a backup brought it, so its foreign paths go too."""
    path = Path(path)
    with closing(_private(path)) as conn:
        if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise TrackerStoreError('Tracker data failed its integrity check')
        if (conn.execute('PRAGMA journal_mode=DELETE').fetchone() or [''])[0].lower() != 'delete':
            raise TrackerStoreError('Tracker data could not be made a single file')
        conn.execute('BEGIN IMMEDIATE')
        try:
            for kind, name in conn.execute(
                    "SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view') "
                    "OR (type = 'table' AND sql LIKE 'CREATE VIRTUAL TABLE%')").fetchall():
                conn.execute(f'DROP {"TABLE" if kind == "table" else kind.upper()} IF EXISTS {_ident(name)}')
            for table in SYNC_TABLES:
                conn.execute(f'DROP TABLE IF EXISTS {_ident(table)}')
            _rebuild_kv(conn)
            if incoming:
                _drop_foreign_paths(conn)
            conn.execute('COMMIT')
        except BaseException:
            _rollback(conn)
            raise
        conn.execute('VACUUM')          # no deleted row stays behind in a free page
        _verify_sanitized(conn, incoming)
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(path) + suffix).exists():
            raise TrackerStoreError('Tracker data copy still has journal files')
    return path


def _rebuild_kv(conn):
    """kv again with the app's own definition, holding every row but :data:`LOCAL_KV_KEYS`."""
    clean = f'kv_{uuid.uuid4().hex}'
    conn.execute(KV_SCHEMA.format(name=_ident(clean)))
    if {'key', 'value'} <= {name for name, _kind, _pk in _columns(conn, 'kv')}:
        conn.execute(f"INSERT OR IGNORE INTO {_ident(clean)} (key, value) SELECT key, value FROM kv "
                     f"WHERE typeof(key) = 'text' AND lower(key) NOT IN ({_marks(LOCAL_KV_KEYS)})", LOCAL_KV_KEYS)
    conn.execute('DROP TABLE IF EXISTS kv')
    conn.execute(f'ALTER TABLE {_ident(clean)} RENAME TO kv')


def network_path(value):
    """True for a string that names a network location (:data:`_NETWORK_PATH`)."""
    return isinstance(value, str) and _NETWORK_PATH.match(value) is not None


def _names_network_path(value):
    """True when a kv value (JSON) holds a network path anywhere inside it, a dict key included."""
    try:
        stack = [json.loads(value)] if isinstance(value, str) else [value]
    except ValueError:
        stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif network_path(item):
            return True
    return False


def _foreign_rows(conn):
    """[(table, rowid)] of the rows a store from a backup may not bring (:func:`_drop_foreign_paths`)."""
    tables, rows = _tables(conn), []
    for table, column in PATH_COLUMNS.items():
        if table in tables and column in {name for name, _kind, _pk in _columns(conn, table)}:
            rows += [(table, rowid) for rowid, value in conn.execute(
                f'SELECT rowid, {_ident(column)} FROM {_ident(table)}') if network_path(value)]
    rows += [('kv', rowid) for rowid, key, value in conn.execute('SELECT rowid, key, value FROM kv')
             if network_path(key) or _names_network_path(value)]
    if 'cv_songs' in tables and 'ext' in {name for name, _kind, _pk in _columns(conn, 'cv_songs')}:
        rows += [('cv_songs', rowid) for (rowid,) in conn.execute(
            f'SELECT rowid FROM cv_songs WHERE ext IS NULL OR ext NOT IN ({_marks(SONG_EXTS)})', SONG_EXTS)]
    return rows


def _drop_foreign_paths(conn):
    """Take out of a store a backup brought what would make this computer open a path it never chose: a game or
    replay hash on a network path (the app reads replays at their path; a game's own rows go with it), a kv value
    holding a network path, and a Combo Video song whose extension is not one the app makes (its file is
    ``<id><ext>``: a crafted extension pointed out of the Vault, and deleting the song removed that file)."""
    tables = _tables(conn)
    for table, rowid in _foreign_rows(conn):
        conn.execute(f'DELETE FROM {_ident(table)} WHERE rowid = ?', (rowid,))
    if _GAMES in tables:
        for table in _GAME_ROWS:
            if table in tables and 'game_id' in {name for name, _kind, _pk in _columns(conn, table)}:
                conn.execute(f'DELETE FROM {_ident(table)} WHERE game_id NOT IN (SELECT id FROM games)')
    if {'cv_songs', 'cv_timelines'} <= tables:
        conn.execute('DELETE FROM cv_timelines WHERE song_id NOT IN (SELECT id FROM cv_songs)')


def _verify_sanitized(conn, incoming=False):
    kinds = {kind for (kind,) in conn.execute('SELECT DISTINCT type FROM sqlite_master')}
    left = conn.execute(f'SELECT count(*) FROM kv WHERE lower(key) IN ({_marks(LOCAL_KV_KEYS)})',
                        LOCAL_KV_KEYS).fetchone()[0]
    if left or kinds & {'trigger', 'view'} or _tables(conn) & set(SYNC_TABLES):
        raise TrackerStoreError('Tracker data copy still holds account state')
    if incoming and _foreign_rows(conn):
        raise TrackerStoreError('Tracker data copy still names a network path')


def snapshot(live, workdir):
    """A sanitized copy of the live store for a backup, in ``workdir``, or None when there is no store."""
    live = Path(live)
    if not live.is_file():
        return None
    copy = Path(workdir) / DB_NAME
    with closing(_read_only(live)) as reader, closing(sqlite3.connect(str(copy))) as writer:
        reader.backup(writer)
    return _sanitize(copy)


def clean_incoming(path):
    """Sanitize the store a backup brought (extracted with its WAL, if it had one), in place."""
    path = Path(path)
    if not path.is_file():
        raise TrackerStoreError('Tracker data in the backup is not a file')
    try:
        return _sanitize(path, incoming=True)
    except sqlite3.DatabaseError as exc:
        raise TrackerStoreError(f'Tracker data in the backup is unreadable: {exc}') from None


def carry_sign_in(live, restored):
    """Put this computer's sign-in and folder rows (:data:`CARRIED_KV_KEYS`) from its live store into a sanitized
    store a replace restore is about to publish. Returns how many rows it carried (none when this computer had
    none)."""
    live = Path(live)
    rows = []
    if live.is_file():
        with closing(_read_only(live)) as source:
            if 'kv' in _tables(source):
                rows = source.execute(f'SELECT key, value FROM kv WHERE key IN ({_marks(CARRIED_KV_KEYS)})',
                                      CARRIED_KV_KEYS).fetchall()
    with closing(_private(restored)) as target:
        target.execute('BEGIN IMMEDIATE')
        try:
            target.execute(f'DELETE FROM kv WHERE lower(key) IN ({_marks(LOCAL_KV_KEYS)})', LOCAL_KV_KEYS)
            target.executemany('INSERT INTO kv (key, value) VALUES (?, ?)', rows)
            target.execute('COMMIT')
        except BaseException:
            _rollback(target)
            raise
    return len(rows)


def merge_into(incoming, live):
    """Add a sanitized backup store's Tracker data that this computer's store lacks; every row already here stays
    as it is, its sign-in and cloud ledger included. Games match by replay path; a game this store has keeps all
    of its own rows. With no store here, the backup's becomes it. Returns the number of games added."""
    incoming, live = Path(incoming), Path(live)
    with closing(_private(incoming)) as conn:
        games = conn.execute('SELECT count(*) FROM games').fetchone()[0] if _GAMES in _tables(conn) else 0
    if _install_new(incoming, live):
        return games
    with closing(sqlite3.connect(str(live), timeout=30, isolation_level=None)) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.execute('ATTACH DATABASE ? AS bk', (str(incoming),))       # closing the connection lets it go
        conn.execute('BEGIN IMMEDIATE')
        try:
            added = _merge(conn)
            conn.execute('COMMIT')
        except BaseException:
            _rollback(conn)
            raise
    return added


def _install_new(incoming, live):
    """With no store here, publish the backup's as it; never over a store that appeared meanwhile."""
    if live.exists():
        return False
    if any(Path(str(live) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise TrackerStoreError('Tracker data here has journal files without its database')
    live.parent.mkdir(parents=True, exist_ok=True)
    part = live.with_name(f'.{live.name}.{uuid.uuid4().hex}.part')
    try:
        shutil.copyfile(incoming, part)
        try:
            if os.name == 'nt':
                os.rename(part, live)          # Windows refuses an existing target
            else:
                os.link(part, live)
        except FileExistsError:
            return False
        return True
    finally:
        part.unlink(missing_ok=True)


def _shared_columns(conn, table, keep=('game_id',)):
    """The columns both stores have, in this store's order, less this store's rowid alias (a new row gets a new
    id) unless it is one of ``keep``."""
    mine = _columns(conn, table)
    theirs = {name for name, _kind, _pk in _columns(conn, table, 'bk')}
    alias = _rowid_alias(mine)
    return [name for name, _kind, _pk in mine if name in theirs and (name != alias or name in keep)]


def _create_like(conn, table):
    """A known Tracker table this store has never made: make it as the backup's store made it."""
    row = conn.execute("SELECT sql FROM bk.sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    sql = (row[0] or '').strip() if row else ''
    if not re.match(rf'CREATE TABLE\s+(?:"{table}"|`{table}`|\[{table}\]|{table})\s*\(', sql, re.IGNORECASE):
        raise TrackerStoreError(f'Tracker data in the backup has an unexpected {table} table')
    conn.execute(sql)


def _merge(conn):
    mine, theirs = _tables(conn), _tables(conn, 'bk')
    for table in (_GAMES, *_GAME_ROWS, *_NEW_ROWS, *_CACHE_ROWS):
        if table in theirs and table not in mine:
            _create_like(conn, table)
    if 'kv' not in mine:
        conn.execute(KV_SCHEMA.format(name='kv'))
    games = _merge_games(conn) if _GAMES in theirs else {}
    conn.execute('CREATE TEMP TABLE merged_games (old INTEGER PRIMARY KEY, new INTEGER NOT NULL)')
    conn.executemany('INSERT INTO temp.merged_games (old, new) VALUES (?, ?)', games.items())
    for table in _GAME_ROWS:
        if table in theirs:
            _merge_game_rows(conn, table)
    for table, key in _NEW_ROWS.items():
        if table in theirs:
            _merge_new_rows(conn, table, key)
    for table in _CACHE_ROWS:
        if table in theirs:
            columns = ', '.join(_ident(c) for c in _shared_columns(conn, table))
            conn.execute(f'INSERT OR IGNORE INTO main.{_ident(table)} ({columns}) '
                         f'SELECT {columns} FROM bk.{_ident(table)}')
    if 'kv' in theirs:
        _merge_kv(conn)
    conn.execute('DROP TABLE temp.merged_games')
    skipped = theirs - set(MERGED_TABLES)
    if skipped:
        logger.info('Vault merge left these Tracker tables as they are here: %s', ', '.join(sorted(skipped)))
    return len(games)


def _merge_games(conn):
    """The backup's games whose replay path this store lacks, added; {backup id: new id}."""
    columns = _shared_columns(conn, _GAMES, keep=())
    if 'path' not in columns or 'id' not in {name for name, _kind, _pk in _columns(conn, _GAMES, 'bk')}:
        return {}
    names = ', '.join(_ident(c) for c in columns)
    insert = f'INSERT OR IGNORE INTO main.games ({names}) VALUES ({_marks(columns)})'
    added = {}
    for old, *values in conn.execute(
            f'SELECT b.id, {", ".join("b." + _ident(c) for c in columns)} FROM bk.games AS b '
            'WHERE b.path IS NOT NULL AND b.path NOT IN (SELECT path FROM main.games WHERE path IS NOT NULL)'
            ).fetchall():
        cursor = conn.execute(insert, values)
        if cursor.rowcount == 1:
            added[old] = cursor.lastrowid
    return added


def _merge_game_rows(conn, table):
    """A table keyed by game: the added games' rows, under their new ids."""
    columns = _shared_columns(conn, table)
    if 'game_id' not in columns:
        return
    names = ', '.join(_ident(c) for c in columns)
    values = ', '.join('m.new' if c == 'game_id' else f'b.{_ident(c)}' for c in columns)
    conn.execute(f'INSERT OR IGNORE INTO main.{_ident(table)} ({names}) SELECT {values} '
                 f'FROM bk.{_ident(table)} AS b JOIN temp.merged_games AS m ON m.old = b.game_id')


def _merge_new_rows(conn, table, key):
    """Rows whose key this store does not have yet (a rank sample, a coach chat)."""
    columns = _shared_columns(conn, table, keep=())
    if not set(key) <= set(columns):
        return
    names = ', '.join(_ident(c) for c in columns)
    match = ' AND '.join(f'm.{_ident(c)} IS b.{_ident(c)}' for c in key)
    conn.execute(f'INSERT OR IGNORE INTO main.{_ident(table)} ({names}) '
                 f'SELECT {", ".join("b." + _ident(c) for c in columns)} '
                 f'FROM bk.{_ident(table)} AS b '
                 f'WHERE NOT EXISTS (SELECT 1 FROM main.{_ident(table)} AS m WHERE {match})')


def _merge_kv(conn):
    """Settings and caches this store lacks; this computer's own rows and the ones about its rows stay."""
    left_out = LOCAL_KV_KEYS + _STORE_KV_KEYS
    conn.execute(f"INSERT OR IGNORE INTO main.kv (key, value) SELECT key, value FROM bk.kv "
                 f"WHERE typeof(key) = 'text' AND lower(key) NOT IN ({_marks(left_out)}) "
                 f"AND substr(key, 1, {len(_STORE_KV_PREFIX)}) != ?", (*left_out, _STORE_KV_PREFIX))
    # Combos extracted under another frame basis than this store's are extracted again (combo_index re-reads a
    # game whose combos_at is NULL, replacing its rows).
    basis = "SELECT value FROM {}.kv WHERE key = 'combos_frame_basis'"
    if ('combos_at' in {name for name, _kind, _pk in _columns(conn, _GAMES)}
            and conn.execute(basis.format('main')).fetchone() != conn.execute(basis.format('bk')).fetchone()):
        conn.execute('UPDATE main.games SET combos_at = NULL WHERE id IN (SELECT new FROM temp.merged_games)')


def forget_schema_caches():
    """After a restore put another store in place, the Tracker modules set up its schema again on their next
    connection (each remembers the stores it has set up, per process)."""
    for module, attribute in (('tracker.store.indexer', '_initialized_paths'),
                              ('tracker.cloud.vault_sync', '_ensured_paths'),
                              ('tracker.cloud.vault_raw', '_ensured_paths')):
        cache = getattr(sys.modules.get(module), attribute, None)
        if cache is not None:
            cache.clear()
