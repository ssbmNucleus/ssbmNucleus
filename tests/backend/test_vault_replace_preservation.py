"""Portable restore failure tests: actual helpers, no Flask/app startup.

Run directly with Python or collect with pytest. The blueprint helpers are
isolated from server configuration so these tests can also run on clean nodes.
The existing blueprint suite separately tests their real route integration.
"""
from tests.paths import BACKEND
import ast
from contextlib import closing
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
import uuid
import zipfile


spec = importlib.util.spec_from_file_location('audit_safe_archive', BACKEND / 'core/safe_archive.py')
archive_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = archive_module
spec.loader.exec_module(archive_module)
path_spec = importlib.util.spec_from_file_location('audit_path_safety', BACKEND / 'core/path_safety.py')
path_module = importlib.util.module_from_spec(path_spec)
sys.modules[path_spec.name] = path_module
path_spec.loader.exec_module(path_module)
tracker_spec = importlib.util.spec_from_file_location('audit_tracker_backup', BACKEND / 'tracker/store/backup.py')
tracker_module = importlib.util.module_from_spec(tracker_spec)
sys.modules[tracker_spec.name] = tracker_module
tracker_spec.loader.exec_module(tracker_module)


def restore_helpers(storage):
    names = {'_extract_zip_with_progress', '_validate_restore_catalog', '_replace_restore', '_rename_aside',
             '_local_only', '_local_only_members', '_carry_local_state', '_validate_catalog_names',
             '_incoming_tracker_store', '_stage_tracker_store', '_carry_sign_in',
             '_settle_sqlite_journals', '_companion_database', '_is_sqlite'}
    constants = {'_SKIN_FILE_FIELDS', '_VARIANT_FILE_FIELDS', '_EXTRA_PATH_FIELDS', '_TRACKER_MEMBERS',
                 '_LOCAL_FILES', '_LOCAL_FOLDERS', '_SQLITE_HEADER', '_SQLITE_COMPANIONS', '_SQLITE_SUFFIXES'}
    tree = ast.parse((BACKEND / 'vault/routes/vault_backup.py').read_text(encoding='utf-8'))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(selected) == len(names)
    fields = [n for n in tree.body if isinstance(n, ast.Assign)
              and {getattr(t, 'id', None) for t in n.targets} & constants]
    assert len(fields) == len(constants)
    selected = fields + selected
    scope = dict(Path=Path, json=json, shutil=shutil, uuid=uuid, zipfile=zipfile, tempfile=tempfile,
                 time=time, sqlite3=sqlite3, closing=closing, tracker_backup=tracker_module,
                 storage_handles=types.SimpleNamespace(close_all=lambda: None),
                 STORAGE_PATH=storage, metadata_lock=threading.RLock(),
                 _DB_ARTIFACTS={'vault.db', 'vault.db-wal', 'vault.db-shm'},
                 safe_extract_zip=archive_module.safe_extract_zip,
                 validate_path_segment=path_module.validate_path_segment,
                 portable_path_parts=path_module.portable_path_parts,
                 _prepare_restore_db=lambda *args: None,
                 logger=logging.getLogger('test_vault_replace_preservation'))
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(BACKEND / 'vault/routes/vault_backup.py'), 'exec'), scope)
    return scope


class _Job:
    """Stands in for a core.jobs Job: records what the restore owns."""
    def __init__(self):
        self.owned = {}

    def progress(self, *args, **kwargs):
        pass

    def own(self, name, value):
        self.owned[name] = value

    def release(self, name):
        self.owned.pop(name, None)


class VaultReplacePreservationTests(unittest.TestCase):
    def setUp(self):
        # Ordinary mkdir permissions also work in the Windows restricted runner.
        self.root = (Path(tempfile.gettempdir()) / ('nucleus-restore-test-' + uuid.uuid4().hex)).resolve()
        self.root.mkdir()
        self.storage = self.root / 'storage'
        self.storage.mkdir()
        (self.storage / 'metadata.json').write_text('{"characters": {}}', encoding='utf-8')
        (self.storage / 'keep.bin').write_bytes(b'healthy original')
        self.scope = restore_helpers(self.storage)
        self.job = _Job()

    def tearDown(self):
        target = self.root.resolve()
        self.assertEqual(target.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(target.name.startswith('nucleus-restore-test-'))
        shutil.rmtree(target)

    def backup(self, metadata='{"bundles": [{"id": "new"}]}', extra=None):
        path = self.root / 'input.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('metadata.json', metadata)
            archive.writestr('new.bin', b'CRC_PAYLOAD_ORIGINAL')
            for name, value in (extra or {}).items():
                archive.writestr(name, value)
        return path

    def assert_original(self):
        self.assertEqual((self.storage / 'keep.bin').read_bytes(), b'healthy original')
        self.assertEqual(json.loads((self.storage / 'metadata.json').read_text()), {'characters': {}})
        self.assertFalse((self.storage / 'new.bin').exists())
        self.assertFalse(list(self.root.glob('.vault-restore-*')))

    def test_success_retains_previous_vault_for_recovery(self):
        recovery, tracker = self.scope['_replace_restore'](self.backup(), self.job)
        recovery = Path(recovery)
        self.assertEqual(tracker, {'status': 'none'})
        self.assertEqual(recovery.parent, self.root)
        self.assertEqual((recovery / 'keep.bin').read_bytes(), b'healthy original')
        self.assertFalse((self.storage / 'keep.bin').exists())
        self.assertEqual((self.storage / 'new.bin').read_bytes(), b'CRC_PAYLOAD_ORIGINAL')
        self.assertEqual(json.loads((self.storage / 'metadata.json').read_text()), {'bundles': [{'id': 'new'}]})
        self.assertEqual(self.job.owned, {})

    def test_invalid_catalog_shapes_preserve_original(self):
        for metadata in ('{broken', '[]', '{"characters": []}',
                         '{"characters": {"Fox": {"skins": [null]}}}',
                         '{"bundles": {}}'):
            with self.subTest(metadata=metadata):
                with self.assertRaises(ValueError):
                    self.scope['_replace_restore'](self.backup(metadata), self.job)
                self.assert_original()

    def test_rejected_archive_member_preserves_original(self):
        with self.assertRaises(ValueError):
            self.scope['_replace_restore'](self.backup(extra={'../outside': b'bad'}), self.job)
        self.assert_original()
        self.assertFalse((self.root / 'outside').exists())

    def test_corrupt_crc_preserves_original(self):
        path = self.backup()
        path.write_bytes(path.read_bytes().replace(b'CRC_PAYLOAD_ORIGINAL', b'CRC_PAYLOAD_DAMAGED!'))
        with self.assertRaises(zipfile.BadZipFile):
            self.scope['_replace_restore'](path, self.job)
        self.assert_original()

    def test_disk_full_and_db_preparation_failure_preserve_original(self):
        path = self.backup()
        def disk_full(archive, destination, *args, **kwargs):
            (destination / 'partial.bin').write_bytes(b'partial')
            raise OSError('disk full')
        with patch.dict(self.scope, _extract_zip_with_progress=disk_full):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.scope['_replace_restore'](path, self.job)
        self.assert_original()
        def db_failure(*args):
            raise OSError('database preparation failed')
        with patch.dict(self.scope, _prepare_restore_db=db_failure):
            with self.assertRaisesRegex(OSError, 'database preparation failed'):
                self.scope['_replace_restore'](path, self.job)
        self.assert_original()

    def test_failed_publish_rolls_back_directory(self):
        path = self.backup()
        original_rename = Path.rename
        def fail_publish(source, target):
            if source.name.startswith('.vault-restore-'):
                raise OSError('publish failed')
            return original_rename(source, target)
        with patch.object(Path, 'rename', fail_publish):
            with self.assertRaisesRegex(OSError, 'publish failed'):
                self.scope['_replace_restore'](path, self.job)
        self.assert_original()
        self.assertFalse(list(self.root.glob('.vault-previous-*')))

    def test_failed_rollback_retains_and_reports_previous_directory(self):
        path = self.backup()
        original_rename = Path.rename
        def fail_publish_and_rollback(source, target):
            if source != self.storage:
                raise OSError('destination unavailable')
            return original_rename(source, target)
        with patch.object(Path, 'rename', fail_publish_and_rollback):
            with self.assertRaisesRegex(RuntimeError, 'previous Vault is preserved at') as caught:
                self.scope['_replace_restore'](path, self.job)
        previous, = self.root.glob('.vault-previous-*')
        self.assertIn(str(previous), str(caught.exception))
        self.assertEqual((previous / 'keep.bin').read_bytes(), b'healthy original')
        self.assertFalse(list(self.root.glob('.vault-restore-*')))
        # Still owned, so the job's cleanup (or the next start) puts it back.
        self.assertEqual(self.job.owned, {'previous': {'path': str(previous), 'vault': str(self.storage.resolve())}})


if __name__ == '__main__':
    unittest.main()
