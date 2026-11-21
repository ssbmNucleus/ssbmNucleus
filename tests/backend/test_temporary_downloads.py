"""Real HTTP transfer/close coverage for the desktop's threaded WSGI server."""
import hashlib
import io
import logging
import os
import socket
import struct
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from flask import Flask
from flask_socketio import SocketIO
from werkzeug.serving import make_server

from projects.routes import mod_export
from vault.routes import vault_backup
from core import temporary_download


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    root = tmp_path / 'downloads'
    backups = root / 'output' / 'vault_backups'
    exports = root / 'output' / 'mod_exports'
    backups.mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(vault_backup, 'PROJECT_ROOT', root)
    monkeypatch.setattr(mod_export, 'OUTPUT_PATH', root / 'output')
    app = Flask(__name__)
    app.register_blueprint(vault_backup.vault_backup_bp)
    app.register_blueprint(mod_export.mod_export_bp)
    # Production uses Socket.IO's threading mode, which runs Werkzeug's
    # threaded WSGI server. Bind port 0 without touching any existing service.
    SocketIO(app, async_mode='threading', manage_session=False)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield SimpleNamespace(root=root, backups=backups, exports=exports,
                          base=f'http://127.0.0.1:{server.server_port}', app=app)
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)
    assert not worker.is_alive()


def archive(path, size):
    payload = os.urandom(size)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as output:
        output.writestr('metadata.json', '{"controlled": true}')
        output.writestr('payload.dat', payload)
    return hashlib.sha256(path.read_bytes()).hexdigest(), payload


def wait_removed(path):
    deadline = time.monotonic() + 5
    while path.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert not path.exists(), f'Temporary download survived response close: {path}'


def check_archive(data, digest, payload):
    assert hashlib.sha256(data).hexdigest() == digest
    with zipfile.ZipFile(io.BytesIO(data)) as output:
        assert output.testzip() is None
        assert output.read('payload.dat') == payload


def location(downloads, kind, name):
    if kind == 'backup':
        return downloads.backups / name, downloads.base + '/api/mex/storage/backup/download/' + name
    return downloads.exports / name, downloads.base + '/api/mex/export/mod/' + name


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['backup', 'mod'])
@pytest.mark.parametrize('size', [128, 8 * 1024 * 1024])
def test_real_http_download_complete_then_removed(downloads, kind, size, caplog):
    path, url = location(downloads, kind, 'complete.zip')
    digest, payload = archive(path, size)
    with caplog.at_level(logging.ERROR):
        response = requests.get(url, timeout=10)
        assert response.status_code == 200
        assert len(response.content) == int(response.headers['Content-Length'])
        check_archive(response.content, digest, payload)
        wait_removed(path)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['backup', 'mod'])
def test_real_http_slow_and_interrupted_consumers(downloads, kind, caplog):
    for interrupted in (False, 'shutdown', 'reset'):
        path, url = location(downloads, kind, f'slow-{interrupted}.zip')
        digest, payload = archive(path, 16 * 1024 * 1024)
        if interrupted:
            target = urlsplit(url)
            # Own the socket directly to exercise both shutdown and an abrupt
            # reset without depending on a client's pooling/iterator behavior.
            with socket.create_connection((target.hostname, target.port), timeout=10) as consumer:
                consumer.sendall(f'GET {target.path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
                assert b'200 OK' in consumer.recv(1024)
                assert path.exists()
                if interrupted == 'reset':
                    linger = struct.pack('hh' if os.name == 'nt' else 'ii', 1, 0)
                    consumer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
                else:
                    consumer.shutdown(socket.SHUT_RDWR)
        else:
            with requests.get(url, stream=True, timeout=10) as response:
                assert response.status_code == 200
                chunks = response.iter_content(64 * 1024)
                received = [next(chunks)]
                # Enough data remains to exceed the socket buffers. The file
                # must still exist while the server owns this active reader.
                assert path.exists()
                for chunk in chunks:
                    received.append(chunk)
                    time.sleep(.002)
                check_archive(b''.join(received), digest, payload)
        wait_removed(path)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['backup', 'mod'])
def test_real_http_overlapping_readers_keep_archive_until_last_close(downloads, kind, caplog):
    path, url = location(downloads, kind, 'shared.zip')
    digest, payload = archive(path, 16 * 1024 * 1024)
    with requests.get(url, stream=True, timeout=10) as first:
        with requests.get(url, stream=True, timeout=10) as second:
            assert first.status_code == second.status_code == 200
            check_archive(first.content, digest, payload)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with temporary_download._lock:
                    counts = [v[0] for k, v in temporary_download._readers.items() if k[0] == path.resolve()]
                if counts == [1]:
                    break
                time.sleep(.01)
            assert counts == [1]
            assert path.exists()
            check_archive(second.content, digest, payload)
    wait_removed(path)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['backup', 'mod'])
def test_real_http_head_does_not_consume_and_range_get_sends_full_archive(downloads, kind):
    path, url = location(downloads, kind, 'inspect.zip')
    digest, payload = archive(path, 1024)
    response = requests.head(url, timeout=10)
    assert response.status_code == 200
    assert not response.content
    assert path.exists()
    response = requests.get(url, headers={'Range': 'bytes=0-99'}, timeout=10)
    assert response.status_code == 200
    check_archive(response.content, digest, payload)
    wait_removed(path)


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['backup', 'mod'])
def test_real_http_parallel_distinct_files(downloads, kind):
    expected = []
    for index in range(4):
        path, url = location(downloads, kind, f'parallel-{index}.zip')
        digest, payload = archive(path, 1024 * 1024)
        expected.append((path, url, digest, payload))
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda item: requests.get(item[1], timeout=10), expected))
    for response, (path, _, digest, payload) in zip(results, expected):
        assert response.status_code == 200
        check_archive(response.content, digest, payload)
        wait_removed(path)


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['costume', 'stage'])
def test_parallel_exports_with_same_display_name_are_independent(downloads, monkeypatch, kind):
    storage = downloads.root / 'storage'
    monkeypatch.setattr(mod_export, 'STORAGE_PATH', storage)
    monkeypatch.setattr(mod_export, 'load_metadata', lambda default=None: default)
    if kind == 'costume':
        folder = storage / 'Fox'
        endpoint = '/api/mex/storage/costumes/export'
        base = {'character': 'Fox', 'colorName': 'Same name'}
        id_key, member = 'skinId', 'PlFxNr.dat'
    else:
        folder = storage / 'das' / 'battlefield'
        endpoint = '/api/mex/storage/stages/export'
        base = {'stageCode': 'GrNBa', 'stageName': 'BF', 'variantName': 'Same name'}
        id_key, member = 'variantId', 'GrNBa.dat'
    folder.mkdir(parents=True)
    for index in range(2):
        with zipfile.ZipFile(folder / f'{index}.zip', 'w') as output:
            output.writestr(member, f'original-{index}')
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda index: requests.post(
            downloads.base + endpoint, json={**base, id_key: str(index)}, timeout=10), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    names = [r.json()['filename'] for r in responses]
    assert names[0] != names[1]
    for index, name in enumerate(names):
        path, url = location(downloads, 'mod', name)
        response = requests.get(url, timeout=10)
        assert name[-36:-4] not in response.headers['Content-Disposition']
        with zipfile.ZipFile(io.BytesIO(response.content)) as result:
            assert result.read(member) == f'original-{index}'.encode()
        wait_removed(path)
