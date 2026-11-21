"""Offline relocation tests. All data uses ordinary mkdir, never pytest tmp_path.

Run: python -m unittest discover -s tests/backend -p test_storage_relocation.py
"""
from tests.paths import BACKEND
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
from contextlib import closing, redirect_stdout
import pytest

pytestmark = pytest.mark.slow


_SPEC = importlib.util.spec_from_file_location(
    'isolated_storage_relocation', BACKEND / 'storage_relocation.py')
worker = importlib.util.module_from_spec(_SPEC)
sys.path.insert(0, str(BACKEND))
try:
    _SPEC.loader.exec_module(worker)
finally:
    sys.path.pop(0)


class StorageRelocationTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()).resolve()
        self.fixture = self.base / ('nucleus-relocation-test-' + uuid.uuid4().hex)
        self.fixture.mkdir()  # ordinary inherited permissions on Windows
        self.source = self.fixture / 'original library'
        self.source.mkdir()
        self.stage = self.fixture / 'staging'
        self.target = self.fixture / '新しい library'
        self.events = []

    def tearDown(self):
        # Verify exactly the uniquely created fixture, not a computed broad path.
        resolved = self.fixture.resolve()
        self.assertEqual(resolved.parent, self.base)
        self.assertTrue(resolved.name.startswith('nucleus-relocation-test-'))
        shutil.rmtree(resolved)

    def write(self, name, value=b'preserved content'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            value = value.encode('utf-8')
        path.write_bytes(value)
        return path

    def run_move(self, **kwargs):
        return worker.relocate(self.source, self.stage, self.target,
                               emit=kwargs.pop('emit', self.events.append), **kwargs)

    def db(self, name='storage/nucleome.db', wal=False):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        if wal:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA wal_autocheckpoint=0')
        return connection

    def test_full_copy_preserves_source_unknown_json_and_scratch_is_empty(self):
        content = self.write('storage/fox/blue.zip', b'z' * 1000)
        self.write('projects/empty-parent/.keep', b'')
        self.write('utility/assets/vanilla/a.dat')
        self.write('aiengine/python/runtime')
        metadata = json.dumps({'name': str(content), 'filename': 'fox/blue.zip'})
        self.write('storage/metadata.json', metadata)
        self.write('scratch/stale-upload.zip', b'not copied')
        result = self.run_move()
        self.assertEqual(result['phase'], 'verified')
        self.assertEqual(result['files'], 5)
        self.assertEqual((self.stage / 'storage/metadata.json').read_text(), metadata)
        self.assertEqual(content.read_bytes(), b'z' * 1000)
        self.assertEqual(list((self.stage / 'scratch').iterdir()), [])
        self.assertFalse(self.target.exists())

    def test_model_import_tools_are_left_behind(self):
        # A download the app can repeat; on macOS/Linux it holds symlinks this worker refuses.
        self.write('tools/model-import/blender/4.3.2/blender.exe', b'big')
        self.write('tools/other/kept.txt', b'kept')
        if hasattr(os, 'symlink'):
            try:
                os.symlink('blender.exe', self.source / 'tools/model-import/blender/4.3.2/link')
            except OSError:
                pass  # Windows without the symlink privilege: the skip is still checked
        result = self.run_move()
        self.assertEqual(result['phase'], 'verified')
        self.assertEqual((self.stage / 'tools/other/kept.txt').read_bytes(), b'kept')
        self.assertFalse((self.stage / 'tools/model-import').exists())
        self.assertTrue((self.source / 'tools/model-import/blender/4.3.2/blender.exe').exists())

    def test_sqlite_wal_snapshot_includes_committed_rows_without_companions(self):
        connection = self.db(wal=True)
        try:
            connection.executescript('CREATE TABLE history(id INTEGER PRIMARY KEY, body TEXT);'
                                     "INSERT INTO history VALUES(7, 'private history');")
            source_wal = self.source / 'storage/nucleome.db-wal'
            source_wal_bytes = source_wal.read_bytes()
            self.assertGreater(len(source_wal_bytes), 0)
            self.run_move()
            # Assert the worker's output before a test connection could change
            # its journal lifecycle. The copy must stand alone in DELETE mode.
            destination = self.stage / 'storage/nucleome.db'
            self.assertEqual(destination.read_bytes()[18:20], b'\x01\x01')
            for suffix in ('-wal', '-shm', '-journal'):
                self.assertFalse(Path(str(destination) + suffix).exists(), suffix)
            with closing(sqlite3.connect(self.stage / 'storage/nucleome.db')) as copied:
                self.assertEqual(copied.execute('PRAGMA journal_mode').fetchone(), ('delete',))
                self.assertEqual(copied.execute('SELECT * FROM history').fetchall(),
                                 [(7, 'private history')])
                self.assertEqual(copied.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertFalse((self.stage / 'storage/nucleome.db-wal').exists())
            self.assertFalse((self.stage / 'storage/nucleome.db-shm').exists())
            self.assertEqual(source_wal.read_bytes(), source_wal_bytes)
            self.assertEqual(connection.execute('SELECT count(*) FROM history').fetchone(), (1,))
        finally:
            connection.close()

    def test_snapshot_refuses_failed_standalone_mode_transition(self):
        real_connect = sqlite3.connect

        class RefuseDelete(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if sql == 'PRAGMA journal_mode=DELETE':
                    return super().execute("SELECT 'wal'")
                return super().execute(sql, *args, **kwargs)

        def connect(*args, **kwargs):
            return real_connect(*args, factory=RefuseDelete, **kwargs)

        with closing(self.db(wal=True)) as source:
            source.executescript('CREATE TABLE items(id INTEGER); INSERT INTO items VALUES(7);')
            with patch.object(worker.sqlite3, 'connect', side_effect=connect):
                with self.assertRaisesRegex(worker.RelocationError, 'standalone mode'):
                    self.run_move()
            self.assertEqual(source.execute('SELECT * FROM items').fetchall(), [(7,)])
            self.assertNotIn('verified', [event['phase'] for event in self.events])
            self.assertFalse(self.target.exists())

    def test_snapshot_retains_unexpected_companion_and_refuses_activation(self):
        self.write('storage/fixture.txt')
        with closing(self.db(wal=True)) as source:
            source.executescript('CREATE TABLE items(id INTEGER); INSERT INTO items VALUES(7);')
            original_integrity = worker._integrity
            leftover = self.stage / 'storage/nucleome.db-shm'

            def leave_companion(connection):
                original_integrity(connection)
                filename = connection.execute('PRAGMA database_list').fetchone()[2]
                if Path(filename) == self.stage / 'storage/nucleome.db':
                    # Simulate a platform retaining a file outside SQLite's
                    # private in-memory WAL index. It must not be blindly removed.
                    leftover.write_bytes(b'preserve unexpected companion')

            with patch.object(worker, '_integrity', side_effect=leave_companion):
                with self.assertRaisesRegex(worker.RelocationError, 'journal files'):
                    self.run_move()
            self.assertEqual(leftover.read_bytes(), b'preserve unexpected companion')
            self.assertEqual(source.execute('SELECT * FROM items').fetchall(), [(7,)])
            self.assertNotIn('verified', [event['phase'] for event in self.events])
            self.assertFalse(self.target.exists())

    def test_busy_sqlite_writer_fails_before_stage_creation(self):
        connection = self.db(wal=True)
        try:
            connection.execute('CREATE TABLE items(id INTEGER)')
            connection.commit()
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('INSERT INTO items VALUES(1)')
            with self.assertRaises(sqlite3.OperationalError):
                self.run_move()
            self.assertFalse(self.stage.exists())
            connection.rollback()
            self.assertEqual(connection.execute('SELECT count(*) FROM items').fetchone(), (0,))
        finally:
            connection.close()

    def test_data_root_lock_refuses_backend_consumer_and_releases(self):
        from storage_data_lock import acquire_data_root_lock, DataRootBusyError, LOCK_FILENAME
        self.write('storage/item')
        lock = acquire_data_root_lock(self.source)
        try:
            with self.assertRaises(DataRootBusyError):
                self.run_move()
            self.assertFalse(self.stage.exists())
        finally:
            lock.close()
            lock.close()  # idempotent
        self.run_move()
        self.assertTrue((self.source / LOCK_FILENAME).exists())
        self.assertFalse((self.stage / LOCK_FILENAME).exists())
        with acquire_data_root_lock(self.source):
            pass

    def test_data_root_lock_released_after_copy_failure(self):
        from storage_data_lock import acquire_data_root_lock
        self.write('storage/item')
        with patch.object(worker, '_copy_file', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_move()
        with acquire_data_root_lock(self.source):
            pass

    def test_data_root_lock_is_visible_to_another_process(self):
        from storage_data_lock import acquire_data_root_lock
        script = (
            'import sys\n'
            'from storage_data_lock import acquire_data_root_lock, DataRootBusyError\n'
            'try:\n'
            '    lock = acquire_data_root_lock(sys.argv[1])\n'
            'except DataRootBusyError:\n'
            '    sys.exit(12)\n'
            'else:\n'
            '    lock.close()\n'
        )
        arguments = [sys.executable, '-c', script, str(self.source)]
        backend = str(BACKEND)
        with acquire_data_root_lock(self.source):
            process = subprocess.run(arguments, cwd=backend, capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 12, process.stderr)
        process = subprocess.run(arguments, cwd=backend, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_shared_backend_leases_coexist_and_block_migration_until_all_exit(self):
        from storage_data_lock import acquire_data_root_lock, DataRootBusyError
        first = acquire_data_root_lock(self.source, exclusive=False)
        second = acquire_data_root_lock(self.source, exclusive=False)
        try:
            with self.assertRaises(DataRootBusyError):
                acquire_data_root_lock(self.source)
            first.close()
            with self.assertRaises(DataRootBusyError):
                acquire_data_root_lock(self.source)
        finally:
            first.close()
            second.close()
        with acquire_data_root_lock(self.source):
            with self.assertRaises(DataRootBusyError):
                acquire_data_root_lock(self.source, exclusive=False)
        with acquire_data_root_lock(self.source, exclusive=False):
            pass

    def test_cli_activation_handshake_holds_root_and_sqlite_locks_until_ack(self):
        from storage_data_lock import acquire_data_root_lock, DataRootBusyError
        connection = self.db()
        connection.executescript('CREATE TABLE history(id INTEGER PRIMARY KEY);'
                                 'INSERT INTO history VALUES(7);')
        connection.close()
        backend = BACKEND
        arguments = [sys.executable, str(backend / 'storage_relocation.py'),
                     '--source', str(self.source), '--stage', str(self.stage),
                     '--target', str(self.target), '--await-activation']
        process = subprocess.Popen(arguments, cwd=backend, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        events = queue.Queue()
        def read_events():
            for line in process.stdout:
                events.put(json.loads(line))
        reader = threading.Thread(target=read_events, daemon=True)
        reader.start()
        try:
            while events.get(timeout=10)['phase'] != 'verified':
                pass
            self.assertIsNone(process.poll())
            with self.assertRaises(DataRootBusyError):
                acquire_data_root_lock(self.source, exclusive=False)
            with closing(sqlite3.connect(self.source / 'storage/nucleome.db', timeout=0.05)) as contender:
                with self.assertRaises(sqlite3.OperationalError):
                    contender.execute('BEGIN IMMEDIATE')
            process.stdin.write('activate\n')
            process.stdin.flush()
            self.assertEqual(process.wait(timeout=10), 0)
            with acquire_data_root_lock(self.source, exclusive=False):
                pass
        finally:
            if process.poll() is None:
                try:
                    process.stdin.write('abort\n')
                    process.stdin.flush()
                except BrokenPipeError:
                    pass
            process.stdin.close()
            process.wait(timeout=10)
            reader.join(timeout=10)
            process.stdout.close()
            process.stderr.close()

    def test_activation_eof_and_abort_fail_without_removing_files(self):
        self.write('storage/file')
        for signal in ('', 'abort\n'):
            with self.subTest(signal=signal):
                with patch.object(worker.sys, 'stdin', io.StringIO(signal)):
                    with self.assertRaisesRegex(worker.RelocationError, 'not activated'):
                        self.run_move(await_activation=worker._await_activation)
                self.assertTrue((self.stage / 'storage/file').is_file())
                self.assertTrue((self.source / 'storage/file').is_file())
                self.assertFalse(self.target.exists())
                # Each retained stage gets its own name; never discard a failed move.
                self.stage = self.fixture / ('next-stage-' + uuid.uuid4().hex)

    def test_sqlite_header_detection_without_extension_and_vault_identity(self):
        connection = self.db('storage/catalog')
        connection.executescript('CREATE TABLE kv(key TEXT PRIMARY KEY, value_json TEXT);'
                                 '''INSERT INTO kv VALUES('__skeleton__', '{"private":"value"}');''')
        connection.close()
        self.run_move()
        with closing(sqlite3.connect(self.stage / 'storage/catalog')) as copied:
            self.assertEqual(copied.execute('SELECT * FROM kv').fetchall(),
                             [('__skeleton__', '{"private":"value"}')])

    def test_corrupt_database_is_not_copied_as_ordinary_bytes(self):
        self.write('storage/vault.db', b'broken database')
        with self.assertRaisesRegex(worker.RelocationError, 'invalid SQLite header'):
            self.run_move()
        self.assertFalse(self.stage.exists())

    def test_corrupt_sqlite_with_valid_header_fails_integrity(self):
        self.write('storage/vault.db', worker.SQLITE_HEADER + b'\x00' * 100)
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_move()
        self.assertFalse(self.stage.exists())

    def test_rebase_only_known_owned_existing_paths_preserves_ids_and_secrets(self):
        replay = self.write('storage/replays/game.slp')
        recordings = self.source / 'output/recordings'
        recordings.mkdir(parents=True)
        external = self.fixture / 'outside.slp'
        external.write_bytes(b'external')
        self.write('storage/vanilla_iso.json', json.dumps({'path': str(replay),
                                                       'note': str(replay)}))
        self.write('storage/ai_studio.json', json.dumps({'hfCacheDir': str(external)}))
        connection = self.db()
        connection.executescript('CREATE TABLE games(id INTEGER PRIMARY KEY, path TEXT UNIQUE);'
                                 'CREATE TABLE vault_hashes(path TEXT PRIMARY KEY, sha TEXT);'
                                 'CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT);'
                                 'CREATE TABLE friends_messages(id TEXT PRIMARY KEY, payload TEXT);')
        connection.executemany('INSERT INTO games VALUES(?, ?)', [(31, str(replay)), (41, str(external))])
        connection.execute('INSERT INTO vault_hashes VALUES(?, ?)', (str(replay), 'content identity'))
        kv = [('recording_dir', json.dumps(str(recordings))),
              ('replay_root_override', json.dumps(str(replay.parent))),
              ('session', json.dumps({'token': 'private-token', 'text': str(replay)}))]
        connection.executemany('INSERT INTO kv VALUES(?, ?)', kv)
        connection.execute("INSERT INTO friends_messages VALUES('message-id', 'private history')")
        connection.commit()
        connection.close()
        self.run_move()
        with closing(sqlite3.connect(self.stage / 'storage/nucleome.db')) as copied:
            self.assertEqual(copied.execute('SELECT * FROM games ORDER BY id').fetchall(),
                             [(31, str(self.target / 'storage/replays/game.slp')), (41, str(external))])
            self.assertEqual(copied.execute('SELECT * FROM vault_hashes').fetchone(),
                             (str(self.target / 'storage/replays/game.slp'), 'content identity'))
            result = dict(copied.execute('SELECT * FROM kv'))
            self.assertEqual(json.loads(result['recording_dir']), str(self.target / 'output/recordings'))
            self.assertEqual(json.loads(result['replay_root_override']), str(self.target / 'storage/replays'))
            self.assertEqual(result['session'], kv[2][1])
            self.assertEqual(copied.execute('SELECT * FROM friends_messages').fetchall(),
                             [('message-id', 'private history')])
        updated = json.loads((self.stage / 'storage/vanilla_iso.json').read_text(encoding='utf-8'))
        self.assertEqual(updated['path'], str(self.target / 'storage/replays/game.slp'))
        self.assertEqual(updated['note'], str(replay))
        self.assertEqual(json.loads((self.stage / 'storage/ai_studio.json').read_text())['hfCacheDir'],
                         str(external))
        self.assertNotIn('private-token', json.dumps(self.events))
        self.assertEqual(json.loads((self.source / 'storage/vanilla_iso.json').read_text())['path'], str(replay))

    def test_absent_and_scratch_paths_are_not_rebased(self):
        self.write('scratch/model', b'temp')
        self.write('storage/ai_studio.json', json.dumps({'hfCacheDir': str(self.source / 'scratch')}))
        absent = str(self.source / 'missing.iso')
        self.write('storage/vanilla_iso.json', json.dumps({'path': absent}))
        self.run_move()
        self.assertEqual(json.loads((self.stage / 'storage/vanilla_iso.json').read_text())['path'], absent)
        self.assertEqual(json.loads((self.stage / 'storage/ai_studio.json').read_text())['hfCacheDir'],
                         str(self.source / 'scratch'))

    def test_owned_texture_mapping_paths_are_rebased_without_changing_other_fields(self):
        portrait = self.write('storage/portraits/fox.png')
        external = self.fixture / 'external.png'
        external.write_bytes(b'portrait')
        mapping = {'build_id': 'unchanged-id', 'costumes': [
            {'real_csp_path': str(portrait), 'hd_csp_path': str(external), 'name': str(portrait)}]}
        self.write('output/test_texture_mapping.json', json.dumps(mapping))
        self.run_move()
        updated = json.loads((self.stage / 'output/test_texture_mapping.json').read_text(encoding='utf-8'))
        self.assertEqual(updated['build_id'], 'unchanged-id')
        self.assertEqual(updated['costumes'][0], {
            'real_csp_path': str(self.target / 'storage/portraits/fox.png'),
            'hd_csp_path': str(external), 'name': str(portrait)})

    def test_path_uniqueness_conflict_fails_without_rebuilding_history(self):
        replay = self.write('storage/game.slp')
        connection = self.db()
        connection.execute('CREATE TABLE games(id INTEGER PRIMARY KEY, path TEXT UNIQUE)')
        rows = [(12, str(replay)), (24, str(self.target / 'storage/game.slp'))]
        connection.executemany('INSERT INTO games VALUES(?, ?)', rows)
        connection.commit()
        connection.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_move()
        with closing(sqlite3.connect(self.source / 'storage/nucleome.db')) as original:
            self.assertEqual(original.execute('SELECT * FROM games ORDER BY id').fetchall(), rows)
        self.assertFalse(self.target.exists())

    def test_selected_root_reference_and_relative_values(self):
        self.write('storage/ai_studio.json', json.dumps({'hfCacheDir': str(self.source)}))
        self.write('storage/vanilla_iso.json', json.dumps({'path': 'storage/game.iso'}))
        self.run_move()
        self.assertEqual(json.loads((self.stage / 'storage/ai_studio.json').read_text())['hfCacheDir'],
                         str(self.target))
        self.assertEqual(json.loads((self.stage / 'storage/vanilla_iso.json').read_text())['path'],
                         'storage/game.iso')

    def test_mutated_file_rejects_stage_and_preserves_original(self):
        path = self.write('storage/file', b'old')
        def emit(event):
            self.events.append(event)
            if event['phase'] == 'verifying':
                path.write_bytes(b'new')
        with self.assertRaisesRegex(worker.RelocationError, 'Source data changed'):
            self.run_move(emit=emit)
        self.assertEqual(path.read_bytes(), b'new')
        self.assertTrue(self.stage.exists())
        self.assertFalse(self.target.exists())

    def test_new_file_during_copy_rejects_inventory(self):
        self.write('storage/file')
        def emit(event):
            if event['phase'] == 'verifying':
                self.write('storage/new-file')
        with self.assertRaisesRegex(worker.RelocationError, 'inventory changed'):
            self.run_move(emit=emit)
        self.assertFalse(self.target.exists())

    def test_disk_capacity_fails_before_stage(self):
        self.write('storage/file')
        with patch.object(worker.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaisesRegex(worker.RelocationError, 'enough free space'):
                self.run_move()
        self.assertFalse(self.stage.exists())

    def test_mid_copy_disk_full_retains_stage_and_original(self):
        path = self.write('storage/file', b'original')
        def failure(source, destination, progress):
            destination.write_bytes(b'partial')
            raise OSError(errno.ENOSPC, 'No space left')
        with patch.object(worker, '_copy_file', side_effect=failure):
            with self.assertRaises(OSError):
                self.run_move()
        self.assertEqual(path.read_bytes(), b'original')
        self.assertEqual((self.stage / 'storage/file').read_bytes(), b'partial')
        self.assertFalse(self.target.exists())

    def test_unwritable_destination_retains_original(self):
        path = self.write('storage/file')
        with patch.object(worker.os, 'fsync', side_effect=PermissionError('unwritable')):
            with self.assertRaises(PermissionError):
                self.run_move()
        self.assertEqual(path.read_bytes(), b'preserved content')
        self.assertFalse(self.stage.exists())

    def test_same_nested_missing_and_nonempty_destinations(self):
        self.write('storage/file')
        for target in (self.source, self.source / 'nested', self.fixture,
                       self.fixture / 'missing-drive' / 'data'):
            with self.subTest(target=target):
                with self.assertRaises(worker.RelocationError):
                    worker.relocate(self.source, self.stage, target, emit=self.events.append)
        self.target.mkdir()
        (self.target / 'unrelated').write_bytes(b'do not overwrite')
        with self.assertRaisesRegex(worker.RelocationError, 'absent or empty'):
            self.run_move()
        self.assertEqual((self.target / 'unrelated').read_bytes(), b'do not overwrite')
        self.assertFalse(self.stage.exists())

    def test_existing_stage_and_source_checkout_are_refused(self):
        self.stage.mkdir()
        with self.assertRaises(worker.RelocationError):
            self.run_move()
        self.stage.rmdir()
        (self.source / 'backend').mkdir()
        with self.assertRaisesRegex(worker.RelocationError, 'source checkout'):
            self.run_move()

    def test_symlink_is_refused_without_following(self):
        external = self.fixture / 'external'
        external.mkdir()
        link = self.source / 'link'
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest('This Windows session cannot create symlinks.')
        with self.assertRaisesRegex(worker.RelocationError, 'reparse points'):
            self.run_move()
        self.assertFalse(self.stage.exists())

    def test_cli_failure_is_json_and_does_not_leak_exception_values(self):
        stdout = io.StringIO()
        with patch.object(worker, 'relocate', side_effect=OSError('private account token')):
            with redirect_stdout(stdout):
                code = worker.main(['--source', str(self.source), '--stage', str(self.stage),
                                    '--target', str(self.target)])
        self.assertEqual(code, 1)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['phase'], 'error')
        self.assertNotIn('private account token', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
