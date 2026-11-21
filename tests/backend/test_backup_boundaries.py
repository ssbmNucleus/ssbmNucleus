from tests.paths import BACKEND
import importlib.util
import uuid
import zipfile
from pathlib import Path

import pytest
from flask import Flask


def _load_module():
    path = BACKEND / 'vault' / 'routes' / 'vault_backup.py'
    spec = importlib.util.spec_from_file_location('backup_boundary_module', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vault_backup = _load_module()
TEST_ROOT = Path(__file__).parent / '.backup-boundary-tmp'


@pytest.fixture
def boundary_dir():
    root = TEST_ROOT / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o777)
    try:
        yield root
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)
        try:
            TEST_ROOT.rmdir()
        except OSError:
            pass


def test_backup_snapshot_rejects_file_symlink(boundary_dir, monkeypatch):
    storage = boundary_dir / 'storage'
    outside = boundary_dir / 'outside.txt'
    storage.mkdir()
    outside.write_text('private outside bytes')
    try:
        (storage / 'linked.txt').symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation is unavailable')
    monkeypatch.setattr(vault_backup, 'STORAGE_PATH', storage)
    with pytest.raises(ValueError, match='does not allow symlinks'):
        vault_backup._backup_files()


def test_backup_rechecks_source_identity_before_zip_write(boundary_dir, monkeypatch):
    storage = boundary_dir / 'storage'
    output = boundary_dir / 'output'
    storage.mkdir()
    output.mkdir()
    source = storage / 'asset.dat'
    source.write_bytes(b'first')
    monkeypatch.setattr(vault_backup, 'STORAGE_PATH', storage)
    monkeypatch.setattr(vault_backup, 'PROJECT_ROOT', boundary_dir)
    monkeypatch.setattr(vault_backup, '_read_vault_catalog', lambda: {})
    real_snapshot = vault_backup._backup_files
    calls = {'count': 0}

    def changing_snapshot():
        calls['count'] += 1
        result = real_snapshot()
        if calls['count'] == 1:
            source.write_bytes(b'changed size')
        return result

    monkeypatch.setattr(vault_backup, '_backup_files', changing_snapshot)
    app = Flask(__name__)
    app.register_blueprint(vault_backup.vault_backup_bp)
    response = app.test_client().post('/api/mex/storage/backup')
    assert response.status_code == 500
    assert 'Vault changed during backup' in response.get_json()['error']
    assert list((output / 'vault_backups').glob('*.zip')) == []
    assert list((output / 'vault_backups').glob('*.part')) == []


def test_download_accepts_legacy_zip_and_rejects_windows_escape(boundary_dir, monkeypatch):
    backups = boundary_dir / 'output' / 'vault_backups'
    backups.mkdir(parents=True)
    legacy = backups / 'my old backup.zip'
    with zipfile.ZipFile(legacy, 'w') as archive:
        archive.writestr('metadata.json', '{}')
    monkeypatch.setattr(vault_backup, 'PROJECT_ROOT', boundary_dir)
    app = Flask(__name__)
    app.register_blueprint(vault_backup.vault_backup_bp)
    client = app.test_client()
    response = client.get('/api/mex/storage/backup/download/my%20old%20backup.zip')
    assert response.status_code == 200
    response.close()

    response = client.get('/api/mex/storage/backup/download/C:%5Coutside.zip')
    assert response.status_code in (400, 404)


def test_download_rejects_symlinked_zip(boundary_dir, monkeypatch):
    backups = boundary_dir / 'output' / 'vault_backups'
    backups.mkdir(parents=True)
    outside = boundary_dir / 'outside.zip'
    outside.write_bytes(b'outside')
    try:
        (backups / 'linked.zip').symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation is unavailable')
    monkeypatch.setattr(vault_backup, 'PROJECT_ROOT', boundary_dir)
    app = Flask(__name__)
    app.register_blueprint(vault_backup.vault_backup_bp)
    response = app.test_client().get(
        '/api/mex/storage/backup/download/linked.zip')
    assert response.status_code == 404
