"""Filesystem boundary checks runnable on clean nodes without Flask or pytest."""
from tests.paths import BACKEND
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
import zipfile



def load_helper(name):
    # Loaded by path, not as core.<name>, so core/__init__ (configuration, the
    # data-root lease) never runs. backend/ goes on sys.path only so these
    # modules find the side-effect-free top-level helpers they import
    # (file_retry), whatever directory this file is run from.
    if str(BACKEND) not in sys.path:
        sys.path.append(str(BACKEND))
    path = BACKEND / 'core' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


archives = load_helper('atomic_archive')
paths = load_helper('path_safety')


class PortableStorageTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(tempfile.gettempdir()) / f'nucleus-storage-test-{uuid.uuid4().hex}').resolve()
        self.root.mkdir()

    def tearDown(self):
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith('nucleus-storage-test-'))
        shutil.rmtree(self.root)

    def test_portable_names_and_symlink_confinement(self):
        for name in ('../outside', '/outside', 'C:\\outside', '\\\\host\\share',
                     'dir\\..\\outside', 'dir/file:stream', '.. /outside',
                     'folder./file', 'NUL.txt', 'dir/COM1.dat'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                paths.resolve_under_root(self.root, name)
        self.assertEqual(paths.resolve_under_root(self.root, 'folder/name with spaces.iso'), self.root / 'folder/name with spaces.iso')
        vault = self.root / 'vault'
        vault.mkdir()
        try:
            (vault / 'link').symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is unavailable for this user')
        with self.assertRaises(ValueError):
            paths.resolve_under_root(vault, 'link/private.dat')

    def test_failed_archive_publication_preserves_bytes(self):
        archive = self.root / 'costume.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('fighter.dat', b'original')
        before = archive.read_bytes()
        with patch.object(archives.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                archives.rewrite_zip_atomic(archive, lambda source, target: target.writestr('fighter.dat', b'changed'))
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [archive])

    def test_concurrent_archive_edits_preserve_both_changes(self):
        archive = self.root / 'costume.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('fighter.dat', b'original')
        barrier = threading.Barrier(2)
        errors = []
        def edit(name):
            try:
                barrier.wait(timeout=5)
                def rewrite(source, target):
                    for item in source.infolist():
                        target.writestr(item, source.read(item))
                    target.writestr(name, name.encode())
                archives.rewrite_zip_atomic(archive, rewrite)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=edit, args=(name,)) for name in ('csp.png', 'stock.png')]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        with zipfile.ZipFile(archive) as result:
            self.assertEqual(set(result.namelist()), {'fighter.dat', 'csp.png', 'stock.png'})
            self.assertIsNone(result.testzip())


if __name__ == '__main__':
    unittest.main()
