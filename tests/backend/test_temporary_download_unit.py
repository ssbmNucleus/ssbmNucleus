"""Focused ownership/error/boundary tests alongside real Windows HTTP tests."""
import os
import threading
import weakref

import pytest
from flask import Flask

from core import temporary_download
from projects.routes import mod_export
from vault.routes import vault_backup


def test_setup_failure_closes_handle_and_keeps_archive_for_retry(tmp_path, monkeypatch):
    path = tmp_path / 'retry.zip'
    path.write_bytes(b'archive')
    opened = []
    def fail_send(source, **kwargs):
        opened.append(source)
        raise RuntimeError('injected response setup failure')
    monkeypatch.setattr(temporary_download, 'send_file', fail_send)
    app = Flask(__name__)
    with app.test_request_context('/'):
        with pytest.raises(RuntimeError, match='injected'):
            temporary_download.send_temporary_zip(path, download_name=path.name)
    assert opened[0].closed
    assert path.read_bytes() == b'archive'
    assert not temporary_download._readers


def test_close_never_removes_replacement_and_is_idempotent(tmp_path):
    path = tmp_path / 'replaced.zip'
    path.write_bytes(b'first')
    app = Flask(__name__)
    with app.test_request_context('/'):
        response = temporary_download.send_temporary_zip(path, download_name=path.name)
    # Windows prevents replacing an open file; put a newer archive at the same
    # path in the interval between releasing the stream and its cleanup callback.
    original_close = response.response.body.close
    def publish_replacement():
        original_close()
        path.unlink()
        path.write_bytes(b'newer archive')
    response.response.body.close = publish_replacement
    response.close()
    response.close()
    assert path.read_bytes() == b'newer archive'
    assert not temporary_download._readers


def test_read_error_still_releases_archive_on_close(tmp_path):
    path = tmp_path / 'error.zip'
    path.write_bytes(b'archive')
    app = Flask(__name__)
    with app.test_request_context('/'):
        response = temporary_download.send_temporary_zip(path, download_name=path.name)
    response.response.source.close()  # simulate read failure
    with pytest.raises(ValueError):
        next(response.response)
    response.close()
    assert not path.exists()
    assert not temporary_download._readers


def test_abandoned_body_finalizes_without_cycle_or_explicit_collection(tmp_path):
    path = tmp_path / 'abandoned.zip'
    path.write_bytes(b'archive')
    app = Flask(__name__)
    with app.test_request_context('/'):
        response = temporary_download.send_temporary_zip(path, download_name=path.name)
    reference = weakref.ref(response.response)
    source = response.response.source
    del response  # model a WSGI server skipping close after a socket reset
    assert reference() is None
    assert source.closed
    assert not path.exists()
    assert not temporary_download._readers


def test_body_close_error_still_closes_owned_handle_and_releases_reader(tmp_path):
    path = tmp_path / 'close-error.zip'
    path.write_bytes(b'archive')
    app = Flask(__name__)
    with app.test_request_context('/'):
        response = temporary_download.send_temporary_zip(path, download_name=path.name)
    def fail_close():
        raise OSError('injected wrapper close failure')
    response.response.body.close = fail_close
    with pytest.raises(OSError, match='injected'):
        response.close()
    assert response.response.source.closed
    assert not path.exists()
    response.close()  # cleanup is idempotent even after a wrapper error
    assert not temporary_download._readers


@pytest.mark.skipif(os.name != 'nt', reason='real Windows sharing semantics')
def test_external_transient_lock_is_retried_after_stream_close(tmp_path):
    path = tmp_path / 'scanner.zip'
    path.write_bytes(b'archive')
    app = Flask(__name__)
    with app.test_request_context('/'):
        response = temporary_download.send_temporary_zip(path, download_name=path.name)
    scanner = path.open('rb')
    release = threading.Timer(.1, scanner.close)
    release.start()
    try:
        response.close()
        assert not path.exists()
    finally:
        scanner.close()
        release.join(timeout=2)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(vault_backup, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(mod_export, 'OUTPUT_PATH', tmp_path / 'output')
    monkeypatch.setattr(mod_export, 'STORAGE_PATH', tmp_path / 'storage')
    monkeypatch.setattr(mod_export, 'load_metadata', lambda default=None: default)
    app = Flask(__name__)
    app.register_blueprint(vault_backup.vault_backup_bp)
    app.register_blueprint(mod_export.mod_export_bp)
    return app.test_client()


@pytest.mark.parametrize('prefix', ['/api/mex/export/mod/', '/api/mex/storage/backup/download/'])
@pytest.mark.parametrize('name', ['C:%5Coutside.zip', '..%5Coutside.zip', 'CON.zip', 'bad.txt', '.zip'])
def test_download_path_boundaries(client, tmp_path, prefix, name):
    outside = tmp_path / 'outside.zip'
    outside.write_bytes(b'keep')
    assert client.get(prefix + name).status_code in (400, 404)
    assert outside.read_bytes() == b'keep'


@pytest.mark.parametrize('kind', ['mod', 'backup'])
def test_download_rejects_symlink_and_missing_file(client, tmp_path, kind):
    prefix, folder = ('/api/mex/export/mod/', 'mod_exports') if kind == 'mod' else (
        '/api/mex/storage/backup/download/', 'vault_backups')
    assert client.get(prefix + 'missing.zip').status_code == 404
    outside = tmp_path / 'outside.zip'
    outside.write_bytes(b'keep')
    directory = tmp_path / 'output' / folder
    directory.mkdir(parents=True)
    try:
        (directory / 'linked.zip').symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation unavailable')
    assert client.get(prefix + 'linked.zip').status_code == 404
    assert outside.read_bytes() == b'keep'


@pytest.mark.parametrize('kind', ['costume', 'stage'])
def test_failed_export_does_not_leave_partial_zip(client, tmp_path, kind):
    if kind == 'costume':
        folder = tmp_path / 'storage' / 'Fox'
        endpoint = '/api/mex/storage/costumes/export'
        body = {'character': 'Fox', 'skinId': 'broken'}
    else:
        folder = tmp_path / 'storage' / 'das' / 'battlefield'
        endpoint = '/api/mex/storage/stages/export'
        body = {'stageCode': 'GrNBa', 'variantId': 'broken'}
    folder.mkdir(parents=True)
    (folder / 'broken.zip').write_bytes(b'invalid ZIP')
    assert client.post(endpoint, json=body).status_code == 500
    assert list((tmp_path / 'output' / 'mod_exports').iterdir()) == []
