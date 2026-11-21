"""Configuration-only checks; no core package imports or real profile writes."""
from tests.paths import BACKEND
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid


CONFIG = BACKEND / 'core' / 'config.py'


class StorageLocationConfigTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.gettempdir()).resolve()
        self.root = self.parent / f'nucleus-config-test-{uuid.uuid4().hex}'
        self.root.mkdir()
        self.data = self.root / 'other drive 日本'
        self.data.mkdir()
        self.paths = sys.path[:]
        sys.path.insert(0, str(CONFIG.parent.parent))
        self.tempdir = tempfile.tempdir
        self.env = patch.dict(os.environ, {
            'NUCLEUS_DATA_ROOT': str(self.data),
            'NUCLEUS_ALLOW_DEV_DATA_ROOT': '1',
            'NUCLEUS_STORAGE_DIR': '',
            'NUCLEUS_SCRATCH_DIR': '',
            'NUCLEUS_BUILD_SMOKE_ROOT': '',
            'NUCLEUS_MANAGED_DATA_ROOT': '0',
        })
        self.env.start()
        self.validator = patch.dict(sys.modules, {'costume_validator': types.SimpleNamespace(set_ref_dir_provider=lambda _: None)})
        self.validator.start()

    def tearDown(self):
        self.validator.stop()
        self.env.stop()
        sys.path[:] = self.paths
        tempfile.tempdir = self.tempdir
        self.assertEqual(self.root.parent, self.parent)
        self.assertTrue(self.root.name.startswith('nucleus-config-test-'))
        shutil.rmtree(self.root)

    def test_dev_opt_in_moves_owned_data_and_scratch_but_keeps_tools_in_source(self):
        config = runpy.run_path(str(CONFIG))
        self.assertEqual(config['PROJECT_ROOT'], self.data)
        for key in ('STORAGE_PATH', 'OUTPUT_PATH', 'PROJECTS_PATH', 'LOGS_PATH', 'VANILLA_ASSETS_DIR', 'MEX_PROJECT_PATH'):
            self.assertTrue(config[key].is_relative_to(self.data), key)
        for key in ('MEXCLI_PATH', 'HSDRAW_EXE', 'PROCESSOR_DIR', 'SERVICES_DIR', 'BUNDLED_CODES_INI', 'BASE_PATH'):
            self.assertFalse(config[key].is_relative_to(self.data), key)
        self.assertEqual(tempfile.gettempdir(), str(self.data / 'scratch'))
        for key in ('TMP', 'TEMP', 'TMPDIR'):
            self.assertEqual(os.environ[key], str(self.data / 'scratch'))
        self.assertEqual(os.environ['NUCLEUS_LOGS_DIR'], str(self.data / 'logs'))

    def test_development_override_requires_explicit_opt_in(self):
        os.environ['NUCLEUS_ALLOW_DEV_DATA_ROOT'] = ''
        with self.assertRaisesRegex(RuntimeError, 'requires'):
            runpy.run_path(str(CONFIG))

    def test_unavailable_selected_root_is_not_created(self):
        missing = self.root / 'missing'
        os.environ['NUCLEUS_DATA_ROOT'] = str(missing)
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            runpy.run_path(str(CONFIG))
        self.assertFalse(missing.exists())

    def test_legacy_vault_only_override_cannot_mix_with_managed_root(self):
        os.environ['NUCLEUS_STORAGE_DIR'] = str(self.root / 'other-vault')
        with self.assertRaisesRegex(RuntimeError, 'cannot be combined'):
            runpy.run_path(str(CONFIG))

    def test_scratch_cannot_escape_chosen_root(self):
        os.environ['NUCLEUS_SCRATCH_DIR'] = str(self.root / 'outside')
        with self.assertRaisesRegex(RuntimeError, 'scratch'):
            runpy.run_path(str(CONFIG))
        self.assertFalse((self.root / 'outside').exists())

    def test_frozen_override_keeps_resources_and_leaves_default_profile_absent(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, '_MEIPASS', str(self.root / 'bundle'), create=True), \
             patch.object(sys, 'executable', str(self.root / 'install' / 'backend' / 'mex_backend.exe')), \
             patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'profile')}):
            config = runpy.run_path(str(CONFIG))
            config['_DATA_ROOT_LEASE'].close()
        self.assertEqual(config['PROJECT_ROOT'], self.data)
        self.assertEqual(config['RESOURCES_DIR'], self.root / 'install')
        self.assertFalse((self.root / 'profile').exists())

    def test_build_smoke_overrides_real_selection_and_scratch(self):
        smoke = self.root / 'smoke'
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, '_MEIPASS', str(self.root / 'bundle'), create=True), \
             patch.object(sys, 'argv', ['mex_backend', '--build-smoke-test']), \
             patch.dict(os.environ, {'NUCLEUS_BUILD_SMOKE_ROOT': str(smoke), 'NUCLEUS_SCRATCH_DIR': 'Z:/unavailable'}):
            config = runpy.run_path(str(CONFIG))
        self.assertEqual(config['PROJECT_ROOT'], smoke)
        self.assertEqual(config['SCRATCH_PATH'], smoke / 'scratch')


if __name__ == '__main__':
    unittest.main()
