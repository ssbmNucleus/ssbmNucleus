"""Security review 11-19, M2: a Vault backup never carries this computer's sign-ins and setup, a restore never
takes them from one, a restored catalog may only name files inside the Vault, and a skin delete never removes a
file outside its character folder. The Tracker data itself travels.

* ``nucleome.db`` is the Tracker store: replays index, combos, stats, chats, settings, and in its kv the sign-ins
  (the cloud vault's Patreon app token, the Discord session). A backup carries a sanitized copy without them; a
  restore brings the Tracker data back and keeps this computer's sign-ins (tracker/store/backup.py). A shared
  backup used to hand over the account, and a crafted one swapped it.
* ``assistant/mcp.json`` names the creation toolkit folder the app runs a Python from: a crafted backup planted it.
* Folders are this computer's own: the Tracker's replay and recording folders, "My game" (``assistant/settings.json``:
  project, game copies, Slippi Launcher or Dolphin), the clean ISO (``vanilla_iso.json``) and the delivery receipts
  (``assistant/deliveries/``: undoing a delivery writes the game back to the paths they record). A restore keeps this
  computer's, and never takes a network path (``\\\\server\\share``) from a backup: the app opens the paths it
  stores, and a stranger's server learns this computer's Windows sign-in from the attempt.
* A catalog filename of ``..`` or an absolute path made the skin delete remove files anywhere.
"""
import ast
import io
import json
import re
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from flask import Flask

from tests.backend.test_vault_backup_blueprint import (  # noqa: F401 - the fixture
    _make_backup_zip, _read_metadata, _restore_done, _restore_failed, _skin, _write_metadata, vault_env)
from tests.gated import present
from tests.paths import BACKEND
from tracker.cloud import vault_raw, vault_sync
from tracker.stats import deep_stats
from tracker.store import backup as tracker_backup
from tracker.store import indexer
from vault.routes import vault_backup

LOCAL = {'nucleome.db': b'REAL-DB', 'nucleome.db-wal': b'REAL-WAL', 'assistant/mcp.json': b'{"real": 1}'}
PLANTED = {'nucleome.db': b'ATTACKER-DB', 'nucleome.db-wal': b'ATTACKER-WAL', 'nucleome.db-shm': b'X',
           'NUCLEOME.DB.bak': b'X', 'assistant/mcp.json': b'{"creation_toolkit": "C:/evil"}'}

# This computer's Tracker settings and sign-ins.
MINE = {'vault_app_token': 'LOCAL-TOKEN-7c1f', 'vault_pledge_active': False, 'vault_paid_defaults_applied': True,
        'friends_session': {'access_token': 'LOCAL-ACCESS-55', 'refresh_token': 'LOCAL-REFRESH-55', 'user_id': 'me'},
        'vault_last_sync_at': '2026-11-18T10:00:00Z', 'vault_codes_base': ['MINE#1'],
        'user_codes': ['MINE#1'], 'auto_sync_on_launch': True}
# Another account's, in a backup.
THEIRS = {'vault_app_token': 'ATTACKER-TOKEN-9e2d', 'vault_pledge_active': True,
          'friends_session': {'access_token': 'ATTACKER-ACCESS', 'refresh_token': 'ATTACKER-REFRESH', 'user_id': 'x'},
          'vault_last_sync_at': '2020-01-01T00:00:00Z', 'vault_codes_base': ['THEM#9'],
          'user_codes': ['THEM#9'], 'coach_profile': {'main': 'Fox'}, 'replay_root_override': 'C:/their-replays'}
SECRETS = ('LOCAL-TOKEN-7c1f', 'LOCAL-ACCESS-55', 'LOCAL-REFRESH-55', 'ATTACKER-TOKEN-9e2d', 'ATTACKER-ACCESS',
           'ATTACKER-REFRESH')

# This computer's folders, and a crafted backup's (network paths: opening one sends this PC's Windows sign-in there).
MY_FOLDERS = {'replay_root_override': 'E:/My Replays', 'recording_dir': 'E:/Clips'}
THEIR_FOLDERS = {'replay_root_override': r'\\evil-host\share\replays', 'recording_dir': '//evil-host/share/clips'}
MY_SETUP = {
    'assistant/settings.json': json.dumps({'destinations': {'dest_1': {
        'player_ref': {'kind': 'dolphin', 'path': 'E:/Slippi/Dolphin.exe'},
        'output_iso_ref': {'path': 'E:/Games/My Melee (Nucleus).iso'}}}}).encode(),
    'vanilla_iso.json': json.dumps({'path': 'E:/Games/melee.iso'}).encode(),
    'assistant/deliveries/proj_1/delivery_aaa111.json': json.dumps({
        'receipt_id': 'delivery_aaa111', 'project': {'id': 'proj_1', 'path': 'E:/Projects/mine/project.mexproj'},
        'status': 'completed'}).encode(),
}
THEIR_SETUP = {
    'assistant/settings.json': json.dumps({'default_destination_id': 'dest_x', 'destinations': {'dest_x': {
        'player_ref': {'kind': 'dolphin', 'path': r'\\evil-host\share\Dolphin.exe'},
        'output_iso_ref': {'path': '//evil-host/share/out.iso'}}}}).encode(),
    'vanilla_iso.json': json.dumps({'path': r'\\evil-host\share\melee.iso'}).encode(),
    'ai_studio.json': json.dumps({'hfCacheDir': r'\\evil-host\share\hf'}).encode(),
    'assistant/deliveries/proj_1/delivery_aaa111.json': json.dumps({
        'receipt_id': 'delivery_aaa111', 'project': {'id': 'proj_1', 'path': 'C:/Windows/System32/project.mexproj'},
        'status': 'completed'}).encode(),
    'assistant/deliveries/proj_x/delivery_bbb222.json': json.dumps({
        'receipt_id': 'delivery_bbb222', 'project': {'id': 'proj_x', 'path': r'\\evil-host\share\project.mexproj'},
        'status': 'completed'}).encode(),
}


# ------------------------------------------------------------------ Tracker stores made with the app's own schema

def _store(path, games=(), kv=None):
    """A Tracker store as the app makes it (WAL, indexer + cloud ledger + deep stats tables): each game with a
    player, a combo, a deep stats row and a cloud ledger row. Returned open, so its rows are still in the WAL."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    indexer._init_schema(conn)
    conn.executescript(vault_sync.SCHEMA)
    conn.executescript(vault_raw.SCHEMA)
    deep_stats.ensure_schema(conn)
    for game in games:
        gid = conn.execute("INSERT INTO games (path, mtime, size, start_at, stage, combos_at) "
                           "VALUES (?, 1, 2, '2026-11-01', 31, 1)", (game,)).lastrowid
        conn.execute("INSERT INTO game_players (game_id, port, type, character, code) VALUES (?, 0, 0, 2, 'MINE#1')",
                     (gid,))
        conn.execute("INSERT INTO combos (game_id, port, opp_port, start_frame, end_frame, code, damage) "
                     "VALUES (?, 0, 1, 10, 50, 'MINE#1', 42.0)", (gid,))
        conn.execute("INSERT INTO deep_rows (game_id, character, analyzer_version, row) VALUES (?, 2, 1, ?)",
                     (gid, json.dumps({'game': game})))
        conn.execute("INSERT INTO vault_objects (game_id, content_hash, deriver, bytes) VALUES (?, ?, 'd', 1)",
                     (gid, f'hash:{game}'))
    conn.execute("INSERT INTO rank_samples (code, at, rating) VALUES ('MINE#1', ?, 1500)", (f'at-{len(games)}',))
    conn.commit()
    for key, value in (kv or {}).items():
        indexer.kv_set(conn, key, value)
    return conn


def _query(path, sql, *args):
    with closing(sqlite3.connect(str(path))) as conn:
        return conn.execute(sql, args).fetchall()


def _kv(path):
    return {key: json.loads(value) for key, value in _query(path, 'SELECT key, value FROM kv')}


def _games(path):
    return {path_ for (path_,) in _query(path, 'SELECT path FROM games')}


def _schema_objects(path):
    return {(kind, name) for kind, name in _query(path, 'SELECT type, name FROM sqlite_master')}


def _rows_per_game(path, table):
    """{replay path: rows of ``table`` under that game's id}: the rows follow their game."""
    return dict(_query(path, f'SELECT g.path, count(t.game_id) FROM games g LEFT JOIN {table} t ON t.game_id = g.id '
                             'GROUP BY g.path'))


def _restore(env, backup, mode):
    return env.client.post('/api/mex/storage/restore', data={'mode': mode, 'file': (backup, 'backup.zip')},
                           content_type='multipart/form-data')


def _backup(env):
    response = env.client.post('/api/mex/storage/backup')
    assert response.status_code == 200, response.get_json()
    return Path(response.get_json()['path'])


def _seed_local_state(storage):
    for relative, data in LOCAL.items():
        target = storage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _crafted_store(folder):
    """An old (0.8.x) or crafted backup's raw store: another account's sign-in and ledger, plus a trigger that would
    put that token back whenever the app writes its own, and a view. Copied while open, as 0.8.x did: rows in the
    WAL."""
    folder.mkdir()
    db = folder / 'nucleome.db'
    conn = _store(db, games=['C:/replays/theirs.slp'], kv=THEIRS)
    conn.executescript("""
        CREATE TRIGGER swap_on_update AFTER UPDATE ON kv BEGIN
            UPDATE kv SET value = '"ATTACKER-TOKEN-9e2d"' WHERE key = 'vault_app_token'; END;
        CREATE TRIGGER swap_on_insert AFTER INSERT ON kv BEGIN
            INSERT OR REPLACE INTO kv (key, value) VALUES ('friends_session', '{"access_token": "ATTACKER-ACCESS"}');
        END;
        CREATE VIEW everything AS SELECT * FROM kv;
    """)
    try:
        return {'nucleome.db': db.read_bytes(), 'nucleome.db-wal': Path(str(db) + '-wal').read_bytes()}
    finally:
        conn.close()


# ------------------------------------------------------------------ backup

def test_a_backup_carries_the_tracker_data_but_not_the_sign_ins_or_the_mcp_settings(vault_env, tmp_path):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (storage / 'Fox').mkdir()
    (storage / 'Fox' / 'fox-red.zip').write_bytes(b'fox')
    (storage / 'assistant').mkdir()
    (storage / 'assistant' / 'mcp.json').write_bytes(LOCAL['assistant/mcp.json'])
    (storage / 'assistant' / 'chats.json').write_text('{}')
    live = storage / 'nucleome.db'
    conn = _store(live, games=['C:/replays/a.slp', 'C:/replays/b.slp'], kv=MINE)   # open: its rows sit in the WAL
    try:
        before = live.read_bytes(), Path(str(live) + '-wal').read_bytes()
        path = _backup(vault_env)
        assert (live.read_bytes(), Path(str(live) + '-wal').read_bytes()) == before, 'the live store is never written'
    finally:
        conn.close()
    assert _kv(live)['vault_app_token'] == MINE['vault_app_token']
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        data = zf.read('nucleome.db')
    assert {'metadata.json', 'Fox/fox-red.zip', 'assistant/chats.json', 'nucleome.db'} <= names
    assert not {'nucleome.db-wal', 'nucleome.db-shm', 'assistant/mcp.json'} & names
    for secret in SECRETS:
        assert secret.encode() not in data, f'{secret} left in the backup, deleted rows included'
    copy = tmp_path / 'copy.db'
    copy.write_bytes(data)
    assert _games(copy) == {'C:/replays/a.slp', 'C:/replays/b.slp'}
    for table in ('game_players', 'combos', 'deep_rows'):
        assert _rows_per_game(copy, table) == {'C:/replays/a.slp': 1, 'C:/replays/b.slp': 1}, table
    assert _query(copy, 'SELECT code, rating FROM rank_samples') == [('MINE#1', 1500.0)]
    assert _kv(copy) == {'user_codes': ['MINE#1'], 'auto_sync_on_launch': True}
    assert not {name for _kind, name in _schema_objects(copy)} & set(tracker_backup.SYNC_TABLES)


def test_a_backup_without_a_tracker_store_has_none(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    with zipfile.ZipFile(_backup(vault_env)) as zf:
        assert 'nucleome.db' not in zf.namelist()


def test_a_tracker_store_that_cannot_be_read_fails_the_backup(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    (vault_env.storage_path / 'nucleome.db').write_bytes(b'not a database')
    response = vault_env.client.post('/api/mex/storage/backup')
    assert response.status_code == 500
    assert 'Could not back up the Tracker data' in response.get_json()['error']
    assert not list((vault_env.project_root / 'output' / 'vault_backups').glob('*.zip'))


# ------------------------------------------------------------------ restore

@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_a_restore_brings_the_tracker_data_back_and_keeps_this_computers_sign_in(vault_env, mode):
    storage = vault_env.storage_path
    live = storage / 'nucleome.db'
    _write_metadata(storage, {'characters': {}})
    _store(live, games=['C:/replays/old-1.slp', 'C:/replays/old-2.slp'],
           kv=dict(THEIRS, vault_app_token='OLD-PC-TOKEN')).close()
    backup = _backup(vault_env).read_bytes()
    # This computer now: another sign-in, its own games and settings.
    live.unlink()
    _store(live, games=['C:/replays/new.slp'], kv=MINE).close()

    assert _restore(vault_env, io.BytesIO(backup), mode).status_code == 200
    done = _restore_done(vault_env)
    assert done, _restore_failed(vault_env)
    kv = _kv(live)
    for key in tracker_backup.CARRIED_KV_KEYS:
        assert kv.get(key) == MINE.get(key), key
    assert 'OLD-PC-TOKEN' not in json.dumps(kv) and 'ATTACKER' not in json.dumps(kv)
    assert kv['coach_profile'] == {'main': 'Fox'}                    # the backup's Tracker settings came back
    if mode == 'replace':
        assert done['tracker'] == {'status': 'restored'}
        assert _games(live) == {'C:/replays/old-1.slp', 'C:/replays/old-2.slp'}
        assert kv['user_codes'] == ['THEM#9']
        # The cloud ledger named another store's games: it starts empty, as after any sign-in change.
        assert not {'vault_last_sync_at', 'vault_codes_base'} & set(kv)
        assert not {name for _kind, name in _schema_objects(live)} & set(tracker_backup.SYNC_TABLES)
    else:
        assert done['tracker'] == {'status': 'merged', 'games': 2}
        assert 'Tracker: added 2 game(s)' in done['message']
        assert _games(live) == {'C:/replays/old-1.slp', 'C:/replays/old-2.slp', 'C:/replays/new.slp'}
        assert kv['user_codes'] == ['MINE#1'] and kv['vault_codes_base'] == ['MINE#1']   # this computer's settings stay
        assert _query(live, 'SELECT content_hash FROM vault_objects') == [('hash:C:/replays/new.slp',)]
        assert sorted(at for (at,) in _query(live, 'SELECT at FROM rank_samples')) == ['at-1', 'at-2']
    for table in ('game_players', 'combos', 'deep_rows'):
        assert set(_rows_per_game(live, table).values()) == {1}, table   # every game's rows came with it
    assert json.loads(_query(live, "SELECT d.row FROM deep_rows d JOIN games g ON g.id = d.game_id "
                                   "WHERE g.path = 'C:/replays/old-2.slp'")[0][0]) == {'game': 'C:/replays/old-2.slp'}


@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_an_old_or_crafted_backup_never_plants_its_sign_in(vault_env, tmp_path, mode):
    storage = vault_env.storage_path
    live = storage / 'nucleome.db'
    _write_metadata(storage, {'characters': {}})
    _store(live, games=['C:/replays/mine.slp'], kv=MINE).close()
    files = dict(_crafted_store(tmp_path / 'crafted'), **{'nucleome.db-shm': b'X', 'NUCLEOME.DB.bak': b'X'})
    assert _restore(vault_env, _make_backup_zip({'characters': {}}, extra_files=files), mode).status_code == 200
    done = _restore_done(vault_env)
    assert done, _restore_failed(vault_env)
    assert not (storage / 'NUCLEOME.DB.bak').exists()
    assert not (storage / 'nucleome.db-shm').exists() or (storage / 'nucleome.db-shm').read_bytes() != b'X'
    kv = _kv(live)
    for key in tracker_backup.CARRIED_KV_KEYS:
        assert kv.get(key) == MINE.get(key), key
    assert 'ATTACKER' not in json.dumps(kv)
    assert not {kind for kind, _name in _schema_objects(live)} & {'trigger', 'view'}
    assert 'C:/replays/theirs.slp' in _games(live)                    # their Tracker data is just data
    assert ('C:/replays/mine.slp' in _games(live)) == (mode == 'merge')
    if mode == 'merge':
        assert _query(live, 'SELECT content_hash FROM vault_objects') == [('hash:C:/replays/mine.slp',)]
    # The app signs in again later: nothing in the store puts the other account back.
    with closing(sqlite3.connect(str(live))) as conn:
        indexer.kv_set(conn, 'vault_app_token', 'LOCAL-TOKEN-NEW')
        indexer.kv_set(conn, 'friends_session', {'access_token': 'LOCAL-ACCESS-NEW'})
    assert _kv(live)['vault_app_token'] == 'LOCAL-TOKEN-NEW'
    assert _kv(live)['friends_session'] == {'access_token': 'LOCAL-ACCESS-NEW'}


def test_a_merge_onto_a_computer_without_tracker_data_brings_it_without_a_sign_in(vault_env, tmp_path):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    files = _crafted_store(tmp_path / 'crafted')
    assert _restore(vault_env, _make_backup_zip({'characters': {}}, extra_files=files), 'merge').status_code == 200
    done = _restore_done(vault_env)
    assert done and done['tracker'] == {'status': 'merged', 'games': 1}, done or _restore_failed(vault_env)
    live = storage / 'nucleome.db'
    assert _games(live) == {'C:/replays/theirs.slp'}
    assert not set(_kv(live)) & set(tracker_backup.LOCAL_KV_KEYS)
    assert not {kind for kind, _name in _schema_objects(live)} & {'trigger', 'view'}


@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_a_restore_never_takes_them_from_a_backup_and_keeps_this_computers(vault_env, mode):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    _seed_local_state(vault_env.storage_path)
    backup = _make_backup_zip({'characters': {'Marth': {'skins': [_skin('marth-black')]}}},
                              extra_files=dict(PLANTED, **{'Marth/marth-black.zip': b'marth'}))
    assert _restore(vault_env, backup, mode).status_code == 200
    done = _restore_done(vault_env)
    assert done, _restore_failed(vault_env)
    assert done['tracker'] == {'status': 'unreadable'} and 'could not be read' in done['message']
    storage = vault_env.storage_path
    assert (storage / 'Marth' / 'marth-black.zip').read_bytes() == b'marth'
    for relative, data in LOCAL.items():
        assert (storage / relative).read_bytes() == data, relative       # this computer's own, carried over
    assert not (storage / 'nucleome.db-shm').exists() and not (storage / 'NUCLEOME.DB.bak').exists()


def test_a_merge_into_a_vault_without_them_does_not_plant_them(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    backup = _make_backup_zip({'characters': {}}, extra_files=PLANTED)
    assert _restore(vault_env, backup, 'merge').status_code == 200
    assert _restore_done(vault_env), _restore_failed(vault_env)
    assert not (vault_env.storage_path / 'nucleome.db').exists()
    assert not (vault_env.storage_path / 'assistant' / 'mcp.json').exists()


# ------------------------------------------------------------------ folders and network paths

def _write(storage, files):
    for relative, data in files.items():
        target = storage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def test_a_backup_leaves_out_this_computers_folders(vault_env, tmp_path):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    _write(storage, MY_SETUP)
    _store(storage / 'nucleome.db', games=['C:/replays/a.slp'],
           kv=dict(MINE, vault_codes_removed=['OLD#1'], vault_raw_retry_after=9e12, **MY_FOLDERS)).close()
    with zipfile.ZipFile(_backup(vault_env)) as zf:
        assert not set(MY_SETUP) & set(zf.namelist())
        (tmp_path / 'copy.db').write_bytes(zf.read('nucleome.db'))
    assert _kv(tmp_path / 'copy.db') == {'user_codes': ['MINE#1'], 'auto_sync_on_launch': True}


@pytest.mark.parametrize('has_own', [True, False], ids=['this-computer-has-its-own', 'this-computer-has-none'])
@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_a_restore_keeps_this_computers_folders_and_never_takes_a_backups(vault_env, tmp_path, mode, has_own):
    storage = vault_env.storage_path
    live = storage / 'nucleome.db'
    _write_metadata(storage, {'characters': {}})
    if has_own:
        _write(storage, MY_SETUP)
    _store(live, games=['C:/replays/mine.slp'], kv=dict(MINE, **(MY_FOLDERS if has_own else {}))).close()
    (tmp_path / 'crafted').mkdir()
    crafted = tmp_path / 'crafted' / 'nucleome.db'
    _store(crafted, games=['C:/replays/theirs.slp'],
           kv=dict(THEIRS, vault_codes_removed=['MINE#1'], vault_raw_retry_after=9e12, **THEIR_FOLDERS)).close()
    backup = _make_backup_zip({'characters': {}}, extra_files=dict(THEIR_SETUP, **{'nucleome.db': crafted.read_bytes()}))
    assert _restore(vault_env, backup, mode).status_code == 200
    done = _restore_done(vault_env)
    assert done and done['tracker']['status'] in ('restored', 'merged'), done or _restore_failed(vault_env)
    kv = _kv(live)
    for key in tracker_backup.PATH_KV_KEYS:
        assert kv.get(key) == (MY_FOLDERS[key] if has_own else None), key
    assert not {'vault_codes_removed', 'vault_raw_retry_after'} & set(kv)    # the cloud bookkeeping stays this PC's
    for relative in THEIR_SETUP:
        target = storage / relative
        assert (target.read_bytes() == MY_SETUP[relative]) if has_own and relative in MY_SETUP else not target.exists()
    receipts = storage / 'assistant' / 'deliveries'
    assert ({p.relative_to(storage).as_posix() for p in receipts.rglob('*') if p.is_file()} if receipts.exists()
            else set()) == ({'assistant/deliveries/proj_1/delivery_aaa111.json'} if has_own else set())
    assert 'evil-host' not in json.dumps(kv)
    assert 'C:/replays/theirs.slp' in _games(live)                      # the Tracker data still came


def _song_tables(conn):
    """Combo Video's song tables, where this checkout has Combo Video (a public one leaves it out)."""
    if present('combo_video'):
        from tracker.video.combo_video import store as combo_video_store
        conn.executescript(combo_video_store.SCHEMA)
        return True
    return False


@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_a_restore_never_takes_a_network_path_from_a_backup(vault_env, tmp_path, mode):
    storage = vault_env.storage_path
    live = storage / 'nucleome.db'
    _write_metadata(storage, {'characters': {}})
    _store(live, games=['C:/replays/mine.slp'], kv=MINE).close()
    (tmp_path / 'crafted').mkdir()
    crafted = tmp_path / 'crafted' / 'nucleome.db'
    network = [r'\\evil-host\share\a.slp', '//evil-host/share/b.slp', r'\\?\UNC\evil-host\share\c.slp']
    conn = _store(crafted, games=['C:/replays/ok.slp', *network],
                  kv={'user_codes': ['THEM#9'], 'coach_profile': {'main': 'Fox', 'clips': [r'\\evil-host\x']},
                      r'\\evil-host\key': 1})
    conn.executemany('INSERT INTO vault_hashes (path, mtime, size, sha) VALUES (?, 1, 2, ?)',
                     [(path, f'sha:{path}') for path in ('C:/replays/ok.slp', *network)])
    songs = _song_tables(conn)
    for song_id, ext in ((1, '.mp3'), (2, r'\..\..\..\Windows\win.ini'), (3, '.MP3')) if songs else ():
        conn.execute('INSERT INTO cv_songs (id, name, ext, created_at) VALUES (?, ?, ?, 1)',
                     (song_id, f'song {song_id}', ext))
        conn.execute("INSERT INTO cv_timelines (song_id, timeline_json, created_at, updated_at) VALUES (?, '[]', 1, 1)",
                     (song_id,))
    conn.commit()
    conn.close()
    backup = _make_backup_zip({'characters': {}}, extra_files={'nucleome.db': crafted.read_bytes()})
    assert _restore(vault_env, backup, mode).status_code == 200
    done = _restore_done(vault_env)
    assert done, _restore_failed(vault_env)
    expected = {'C:/replays/ok.slp'} | ({'C:/replays/mine.slp'} if mode == 'merge' else set())
    assert _games(live) == expected
    assert done['tracker'] == ({'status': 'merged', 'games': 1} if mode == 'merge' else {'status': 'restored'})
    for table in ('game_players', 'combos', 'deep_rows'):
        assert _rows_per_game(live, table) == dict.fromkeys(expected, 1), table
        assert _query(live, f'SELECT count(*) FROM {table} WHERE game_id NOT IN (SELECT id FROM games)') == [(0,)]
    assert {path for (path,) in _query(live, 'SELECT path FROM vault_hashes')} == {'C:/replays/ok.slp'}
    kv = _kv(live)
    assert 'evil-host' not in json.dumps(kv) and 'coach_profile' not in kv
    if mode == 'replace':
        assert kv['user_codes'] == ['THEM#9']
    if mode == 'replace' and songs:
        assert _query(live, 'SELECT id, ext FROM cv_songs') == [(1, '.mp3')]
        assert _query(live, 'SELECT song_id FROM cv_timelines') == [(1,)]


def test_a_store_that_still_names_a_network_path_is_not_restored(tmp_path, monkeypatch):
    db = tmp_path / 'nucleome.db'
    _store(db, games=[r'\\evil-host\share\a.slp']).close()
    monkeypatch.setattr(tracker_backup, '_drop_foreign_paths', lambda conn: None)
    with pytest.raises(tracker_backup.TrackerStoreError, match='network path'):
        tracker_backup.clean_incoming(db)


@pytest.mark.parametrize('value, network', [
    (r'\\server\share\x.slp', True), ('//server/share/x.slp', True), (r'\\?\UNC\server\share', True),
    (r'\\?\GLOBALROOT\Device\Mup\server', True), (r'\\.\pipe\x', True), (r' \\server\share', True),
    (r'\/server/share', True),
    (r'\\?\C:\replays\x.slp', False), (r'\\.\E:\x', False), ('C:/replays/x.slp', False),
    (r'C:\replays\x.slp', False), ('/home/me/x.slp', False), ('https://example.com/x', False), ('', False),
])
def test_what_counts_as_a_network_path(value, network):
    assert tracker_backup.network_path(value) is network


# ------------------------------------------------------------------ the lists stay the owners'

def test_the_left_out_keys_and_tables_are_the_ones_their_owners_name():
    from shared.account import session
    from tracker.cloud import vault_jobs
    assert set(tracker_backup.SECRET_KV_KEYS) == {vault_jobs.TOKEN_KEY, session.SESSION_KEY}
    assert set(tracker_backup.ACCOUNT_KV_KEYS) == {vault_jobs.PLEDGE_KEY, vault_jobs.PAID_DEFAULTS_KEY}
    from tracker.cloud import vault_client
    assert set(tracker_backup.SYNC_KV_KEYS) == set(vault_jobs._ACCOUNT_STATE_KEYS) | {
        vault_client.CODES_REMOVED_KEY, vault_client.RAW_RETRY_AFTER_KEY}
    # The tables are the ones the app empties itself when the sign-in changes.
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.executescript(indexer.SCHEMA)
        conn.executescript(vault_raw.SCHEMA)
        statements = []
        conn.set_trace_callback(statements.append)
        vault_jobs.clear_account_sync_state(conn)
    cleared = {m.group(1) for m in (re.match(r'\s*DELETE FROM (\w+)\s*$', s) for s in statements) if m}
    assert cleared == set(tracker_backup.SYNC_TABLES)


# The kv keys a backup carries and a restore takes: Tracker settings and caches with no path or account in them.
# (``stocks:<game id>`` is built at run time; the merge keeps this computer's, see tracker/store/backup.py.)
TRAVELS = {'auto_scan_on_launch', 'auto_sync_on_launch', 'coach_profile', 'combos_frame_basis', 'deep_mine_secs_per_game',
           'rank:', 'rank_history:', 'seen_login_codes', 'user_codes', 'vault_raw_upload'}


def test_every_kv_key_the_app_uses_has_a_restore_rule():
    """A new kv key needs a decision: it travels (:data:`TRAVELS`), or it is this computer's own
    (tracker/store/backup.py LOCAL_KV_KEYS: a sign-in, account or cloud state, or a folder)."""
    call = re.compile(r'''kv_(?:get|set|del)\(\s*\w+\s*,\s*f?["']([^"'{]+)''')
    sql = re.compile(r'''INTO kv\s*\(\s*key\s*,\s*value\s*\)\s*VALUES\s*\(\s*["']([^"']+)["']''')
    constant = re.compile(r'''^\s*_?[A-Z][A-Z0-9_]*KEY[A-Z0-9_]*\s*=\s*["']([^"']+)["']''', re.M)
    found = set()
    for path in BACKEND.rglob('*.py'):
        if {'devtools', 'probes'} & set(path.relative_to(BACKEND).parts):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if 'kv_get' in text or 'kv_set' in text or 'INTO kv' in text:
            for pattern in (call, sql, constant):
                found |= set(pattern.findall(text))
    # Keys only the coach uses: a public source checkout leaves it out, and a backup can still carry them.
    if not present('randall'):
        found |= COACH_ONLY_KV_KEYS
    assert found == set(tracker_backup.LOCAL_KV_KEYS) | TRAVELS


#: The kv keys only the Tracker coach (randall/coach, left out of the public source drop) reads or writes.
COACH_ONLY_KV_KEYS = {'coach_profile'}


def test_the_coach_only_kv_keys_are_the_coachs():
    """COACH_ONLY_KV_KEYS stays true where the coach is in the checkout."""
    if not present('randall'):
        pytest.skip('this checkout leaves out the randall code (public source drop)')
    call = re.compile(r'''kv_(?:get|set|del)\(\s*\w+\s*,\s*f?["']([^"'{]+)''')
    constant = re.compile(r'''^\s*_?[A-Z][A-Z0-9_]*KEY[A-Z0-9_]*\s*=\s*["']([^"']+)["']''', re.M)
    coach, rest = set(), set()
    for path in BACKEND.rglob('*.py'):
        rel = path.relative_to(BACKEND).as_posix()
        if {'devtools', 'probes'} & set(path.relative_to(BACKEND).parts):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if 'kv_get' in text or 'kv_set' in text or 'INTO kv' in text:
            keys = set(call.findall(text)) | set(constant.findall(text))
            (coach if rel.startswith(('randall/coach/', 'randall/routes/coach.py')) else rest).update(keys)
    assert coach - rest == COACH_ONLY_KV_KEYS
    assert not any(re.search(r'(^|_)(dir|path|root|folder|file|iso|exe|override)(_|$)', key) for key in TRAVELS)


def test_the_path_settings_are_the_ones_a_data_move_rewrites():
    """storage_relocation lists every stored setting that holds a path on this computer: none travels."""
    import storage_relocation
    from core import config
    from randall.delivery import destination
    from randall.mcp import toolkit
    from shared.vanilla_extract import vanilla_refs
    assert set(storage_relocation.TRACKER_PATH_KEYS) == set(tracker_backup.PATH_KV_KEYS)
    assert set(storage_relocation.TRACKER_PATH_TABLES) == set(tracker_backup.PATH_COLUMNS)
    for name, _fields in storage_relocation.PATH_SETTINGS_FILES:
        assert name.startswith('storage/') and vault_backup._local_only(name[len('storage/'):]), name
    storage = Path(config.STORAGE_PATH)
    for path in (destination.settings_path(), toolkit._settings_path(), vanilla_refs.ISO_RECORD_PATH):
        assert vault_backup._local_only(Path(path).relative_to(storage).as_posix()), path
    if present('combo_video'):
        source = (BACKEND / 'tracker/video/combo_video/store.py').read_text(encoding='utf-8')
        assert ast.literal_eval(re.search(r'ALLOWED_EXTS = (\([^)]*\))', source).group(1)) == tracker_backup.SONG_EXTS


def test_the_delivery_receipts_are_this_computers_own():
    """Undoing a delivery writes the game back to the paths its receipt records: the folder receipts are written to
    and read from (randall/delivery/deliver_receipts.py) never travels."""
    from core import config
    from randall.delivery import deliver_receipts
    folder = Path(deliver_receipts._receipt_root()).relative_to(Path(config.STORAGE_PATH)).as_posix()
    assert tuple(folder.lower().split('/')) in vault_backup._LOCAL_FOLDERS
    for name in (folder, f'{folder}/', f'{folder}/proj_1/delivery_aaa111.json', f'{folder.upper()}/x/y.json',
                 folder.replace('/', '\\') + '\\x\\y.json'):
        assert vault_backup._local_only(name), name
    for name in ('assistant/deliveries.json', 'assistant/deliveries-old/x.json', 'assistant/tasks/x.json'):
        assert not vault_backup._local_only(name), name


# Watch Lite's animation zips: about 90 MB of a 175 MB 0.9.0 backup (tester B8), downloaded again whenever missing.
MY_ANIM_ZIPS = {'nucleome/anim_zips/fox.zip': b'MY-FOX', 'nucleome/anim_zips/kirby.zip': b'MY-KIRBY'}


def test_the_animation_zips_left_out_are_the_ones_the_app_downloads(monkeypatch):
    """The folder a backup leaves out is the one anim_fetch downloads into, and the app fetches it again at every
    start (tracker/routes/lite.py), not only in first-run setup."""
    from core import config
    from tracker.video import anim_fetch, clip_render
    called = []
    # Before lite is imported: its import starts the download at backend start, and a test never downloads.
    monkeypatch.setattr(anim_fetch, 'ensure_anim_zips', lambda *args, **kwargs: called.append(args))
    from tracker.routes import lite
    folder = Path(clip_render.user_zips_dir()).relative_to(Path(config.STORAGE_PATH)).as_posix()
    assert tuple(folder.lower().split('/')) in vault_backup._LOCAL_FOLDERS
    assert vault_backup._local_only(f'{folder}/fox.zip') and vault_backup._local_only(f'{folder}/fox.zip.part')
    assert not vault_backup._local_only('nucleome/other.json')
    lite._ensure_anim_zips_bg()
    assert () in called


def test_a_backup_leaves_out_the_animation_zips(vault_env):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    _write(storage, dict(MY_ANIM_ZIPS, **{'nucleome/other.json': b'{}'}))
    with zipfile.ZipFile(_backup(vault_env)) as zf:
        names = set(zf.namelist())
    assert 'nucleome/other.json' in names
    assert not [name for name in names if 'anim_zips' in name]


@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_a_restore_keeps_this_computers_animation_zips_and_never_takes_a_backups(vault_env, mode):
    """A 0.9.0 build 8 backup still carries them: a restore never writes them, and a replace keeps this computer's."""
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    _write(storage, MY_ANIM_ZIPS)
    old = _make_backup_zip({'characters': {'Marth': {'skins': [_skin('marth-black')]}}}, extra_files={
        'Marth/marth-black.zip': b'marth',
        'nucleome/anim_zips/fox.zip': b'OLD-FOX', 'nucleome/anim_zips/marth.zip': b'OLD-MARTH'})
    assert _restore(vault_env, old, mode).status_code == 200
    assert _restore_done(vault_env), _restore_failed(vault_env)
    assert (storage / 'Marth' / 'marth-black.zip').read_bytes() == b'marth'
    zips = storage / 'nucleome' / 'anim_zips'
    assert {p.name: p.read_bytes() for p in zips.iterdir()} == {'fox.zip': b'MY-FOX', 'kirby.zip': b'MY-KIRBY'}


def test_a_replace_onto_a_computer_without_animation_zips_leaves_them_to_the_download(vault_env):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    old = _make_backup_zip({'characters': {}}, extra_files={'nucleome/anim_zips/fox.zip': b'OLD-FOX'})
    assert _restore(vault_env, old, 'replace').status_code == 200
    assert _restore_done(vault_env), _restore_failed(vault_env)
    assert not (storage / 'nucleome' / 'anim_zips' / 'fox.zip').exists()


def test_every_tracker_table_has_a_restore_rule():
    """A new table in nucleome.db needs a line in tracker/store/backup.py: merged, restored by a replace only, or
    left out with the sign-in."""
    owners = ('tracker/store/indexer.py', 'tracker/cloud/vault_sync.py', 'tracker/cloud/vault_raw.py',
              'tracker/stats/deep_stats.py', *GATED_TABLE_OWNERS)
    tables = set()
    for owner in owners:
        gate, own = GATED_TABLE_OWNERS.get(owner, (None, None))
        if gate and not present(gate):
            tables |= own              # left out of this checkout (public source drop): its tables as named
            continue
        found = set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', (BACKEND / owner).read_text(encoding='utf-8')))
        assert gate is None or found == own, f'{owner} makes {found}; update GATED_TABLE_OWNERS'
        tables |= found
    for path in BACKEND.rglob('*.py'):
        text = path.read_text(encoding='utf-8', errors='replace')
        if 'indexer.connect()' in text and 'CREATE TABLE' in text:
            assert path.relative_to(BACKEND).as_posix() in owners, f'{path} makes tables in nucleome.db'
    assert tables == set(tracker_backup.MERGED_TABLES) | set(tracker_backup.NOT_MERGED) | set(
        tracker_backup.SYNC_TABLES)


#: The nucleome.db tables of code a public source checkout leaves out (tools/public_drop.py): the restore rules
#: still name them, since a backup from an app that has them can carry them. Checked against the code where it is.
GATED_TABLE_OWNERS = {
    'randall/coach/coach_store.py': ('randall', {'coach_chats'}),
    'tracker/video/combo_video/store.py': ('combo_video', {'cv_songs', 'cv_timelines'}),
}


# ------------------------------------------------------------------ catalog names

@pytest.mark.parametrize('bad', [
    {'characters': {'Fox': {'skins': [dict(_skin('a'), filename='../../outside.txt')]}}},
    {'characters': {'Fox': {'skins': [dict(_skin('a'), csp_filename='C:/Windows/win.ini')]}}},
    {'characters': {'Fox': {'skins': [dict(_skin('a'), alternate_csps=[{'filename': '..\\x.png'}])]}}},
    {'characters': {'Fox': {'skins': [_skin('../a')]}}},
    {'characters': {'../Fox': {'skins': []}}},
    {'characters': {'Fox': {'extras': {'laser': [{'id': 'm', 'model_file': '../../x.dat'}]}}}},
    {'stages': {'GrNBa': {'variants': [{'id': 'v', 'filename': '/etc/passwd'}]}}},
    {'custom_characters': [{'slug': '..'}]},
])
@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_a_catalog_naming_a_file_outside_the_vault_is_refused(vault_env, bad, mode):
    _write_metadata(vault_env.storage_path, {'characters': {'Marth': {'skins': [_skin('kept')]}}})
    assert _restore(vault_env, _make_backup_zip(bad), mode).status_code == 200
    failed = _restore_failed(vault_env)
    assert failed and 'Invalid backup catalog' in failed['error'], failed
    assert _read_metadata(vault_env.storage_path)['characters'] == {'Marth': {'skins': [_skin('kept')]}}


def test_a_good_catalog_with_nested_extra_paths_still_restores(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    good = {'characters': {'C. Falcon': {
        'skins': [dict(_skin('cf-a'), csp_filename='cf-a_csp.png', alternate_csps=[{'filename': 'cf-a_csp_alt_1.png'}])],
        'extras': {'punch': [{'id': 'p1', 'model_file': 'models/p1.dat', 'screenshot': 'models/p1_preview.png'}]}}}}
    assert _restore(vault_env, _make_backup_zip(good), 'replace').status_code == 200
    assert _restore_done(vault_env), _restore_failed(vault_env)


# ------------------------------------------------------------------ the skin delete

@pytest.fixture
def costumes(tmp_path, monkeypatch):
    from core import config, metadata as metadata_module
    from vault.routes.storage_costumes import library, storage_costumes_bp
    storage = tmp_path / 'storage'
    (storage / 'Fox').mkdir(parents=True)
    monkeypatch.setattr(library, 'STORAGE_PATH', storage)
    monkeypatch.setattr(config, 'STORAGE_PATH', storage)
    monkeypatch.setattr(metadata_module, 'STORAGE_PATH', storage, raising=False)
    monkeypatch.setattr(metadata_module, 'METADATA_FILE', storage / 'metadata.json', raising=False)
    app = Flask(__name__)
    app.register_blueprint(storage_costumes_bp)
    return app.test_client(), storage


def test_a_skin_delete_refuses_files_outside_its_character_folder(costumes, tmp_path):
    from core.metadata import load_metadata, save_metadata
    client, storage = costumes
    victim = tmp_path / 'victim.txt'
    victim.write_text('keep me')
    outside = storage / 'outside.png'
    outside.write_text('keep me too')
    (storage / 'Fox' / 'a.zip').write_bytes(b'zip')
    (storage / 'Fox' / 'a_csp.png').write_bytes(b'png')
    save_metadata({'characters': {'Fox': {'skins': [dict(
        _skin('a'), csp_filename='../outside.png', hd_csp_filename=str(victim),
        alternate_csps=[{'filename': '..\\..\\victim.txt'}])]}}})
    assert load_metadata()['characters']['Fox']['skins'], 'the test writes the vault the route reads'
    answer = client.post('/api/mex/storage/costumes/delete', json={'character': 'Fox', 'skinId': 'a'}).get_json()
    assert answer['success'] is True
    assert victim.read_text() == 'keep me' and outside.read_text() == 'keep me too'
    assert set(answer['refused_files']) == {'../outside.png', str(victim), '..\\..\\victim.txt'}
    assert not (storage / 'Fox' / 'a.zip').exists() and not (storage / 'Fox' / 'a_csp.png').exists()
    assert load_metadata()['characters']['Fox']['skins'] == []
    for body in ({'character': '../Fox', 'skinId': 'a'}, {'character': 'Fox', 'skinId': '../a'}):
        assert client.post('/api/mex/storage/costumes/delete', json=body).status_code == 400, body
