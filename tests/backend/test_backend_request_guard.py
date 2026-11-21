"""The file routes outside /api, and the Host check, as app.py installs them.

/storage used to serve every file under the vault with no token, nucleome.db
(the Patreon vault token lives in its kv table), vault.db and metadata.json
included, to any local process and to any web page that reached the port
through DNS rebinding or a sandboxed (Origin: null) iframe. These tests run the
real guard (shared/request_guard.py) in front of the real /storage route.
"""
from tests.paths import BACKEND
import sqlite3

import pytest
from flask import Flask

from shared import request_guard
from shared.routes import assets

TOKEN = 'synthetic-guard-token'
PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
                    '0000000d49444154789c6360000002000100e221bc330000000049454e44ae426082')


@pytest.fixture
def client(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    (storage / 'Fox').mkdir(parents=True)
    (storage / 'Fox' / 'skin-1_csp.png').write_bytes(PNG)
    (storage / 'metadata.json').write_text('{"characters": {}}')
    conn = sqlite3.connect(storage / 'nucleome.db')
    conn.execute('CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)')
    conn.execute("INSERT INTO kv VALUES ('vault_app_token', 'synthetic-secret')")
    conn.commit()
    conn.close()
    (storage / 'nucleome.db-wal').write_bytes(b'synthetic wal')
    monkeypatch.setattr(assets, 'STORAGE_PATH', storage)

    app = Flask('request-guard-test')
    app.register_blueprint(assets.assets_bp)
    request_guard.install(app, lambda candidate: candidate == TOKEN)
    assert not app.testing  # exercise real enforcement, not the testing bypass
    return app.test_client()


def test_databases_are_never_served(client):
    for path in ('/storage/nucleome.db', '/storage/nucleome.db-wal', '/storage/NUCLEOME.DB',
                 '/storage/nucleome.db.', '/storage/NUCLEO~1.DB'):
        assert client.get(path).status_code == 404, path
        assert client.get(path, headers={'X-Nucleus-Token': TOKEN}).status_code == 404, path
        assert client.get(path, query_string={'_nucleus_token': TOKEN}).status_code == 404, path


def test_non_media_files_need_the_token(client):
    assert client.get('/storage/metadata.json').status_code == 401
    assert client.get('/storage/metadata.json', query_string={'_nucleus_token': 'wrong'}).status_code == 401
    ok = client.get('/storage/metadata.json', headers={'X-Nucleus-Token': TOKEN})
    assert ok.status_code == 200 and ok.data == b'{"characters": {}}'
    assert client.get('/storage/metadata.json', query_string={'_nucleus_token': TOKEN}).status_code == 200


def test_media_loads_the_way_the_frontend_loads_it(client):
    # The backend hands out bare cspUrl/stockUrl values like this one, and
    # backendMediaUrl() leaves /storage URLs without a token (config.test.js),
    # so an <img src> arrives with no header and a cache-bust query only.
    resp = client.get('/storage/Fox/skin-1_csp.png', query_string={'t': '1791488565409'},
                      headers={'Host': '127.0.0.1:51234', 'Origin': 'null'})
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png' and resp.data == PNG


def test_foreign_host_is_rejected_before_any_route(client):
    for host in ('attacker.example', 'attacker.example:5000', '127.0.0.1.attacker.example',
                 'localhost.attacker.example:5000', '127.0.0.1:5000@attacker.example', ''):
        resp = client.get('/storage/Fox/skin-1_csp.png', headers={'Host': host})
        assert resp.status_code == 403, host
    for host in ('127.0.0.1:5000', 'localhost:51234', 'LOCALHOST', '[::1]:5000', '127.0.0.1'):
        assert client.get('/storage/Fox/skin-1_csp.png', headers={'Host': host}).status_code == 200, host


@pytest.mark.parametrize('path, access', [
    ('/storage/Fox/a_csp.png', 'public'),
    ('/vanilla/sounds/tick.wav', 'public'),
    ('/utility/buttons/A.svg', 'public'),
    ('/assets/csp/csp_038.png', 'public'),
    ('/storage/Fox/a.zip', 'token'),
    ('/storage/poses/Fox/idle.yml', 'token'),
    ('/storage/metadata.json', 'token'),
    ('/storage/vault.db', 'deny'),
    ('/storage/vault.sqlite3', 'deny'),
    ('/storage/nucleome.db-shm', 'deny'),
    ('/storage/nucleome.db-journal', 'deny'),
    ('/storage/nucleome.db::$DATA', 'deny'),
    ('/storage/Fox\\..\\nucleome.db', 'deny'),
    ('/api/mex/storage/metadata', None),
    ('/socket.io/', None),
])
def test_static_file_access_table(path, access):
    assert request_guard.static_file_access(path) == access


def test_app_installs_the_guard_after_socketio():
    """The Host check must wrap the Socket.IO middleware too, so app.py has to
    install it after SocketIO(app) replaces app.wsgi_app."""
    source = (BACKEND / 'app.py').read_text(encoding='utf-8')
    socket_at = source.index('socketio = SocketIO(app')
    install_at = source.index('_request_guard.install(app, _valid_backend_token)')
    assert install_at > socket_at
