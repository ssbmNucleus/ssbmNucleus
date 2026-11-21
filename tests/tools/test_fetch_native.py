"""tools/build/fetch_native.py fetches the pinned MexCLI / HSDRawViewer release archives.

The public source copy's manifests pin the public repos, so the creation toolkit's setup (tools/creation/setup.ps1)
must download them with no GitHub login: after gh and a token, it takes the release's plain link. A real local HTTP
server stands in for GitHub, redirect included, as github.com sends release downloads on to its storage host.
"""
import http.server
import importlib.util
import threading
import urllib.error

import pytest

from tests.paths import REPO

_spec = importlib.util.spec_from_file_location('fetch_native_under_test', REPO / 'tools' / 'build' / 'fetch_native.py')
fn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fn)

ASSET = 'hsdrawviewer-win-x64.zip'
RELEASE_PATH = f'/ssbmNucleus/HSDLib/releases/download/nucleus-v0.9.0/{ASSET}'
BODY = b'PK\x05\x06' + b'\0' * 18


@pytest.fixture
def github():
    """A local stand-in for github.com: the release link redirects to the file; anything else is 404."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get('Authorization')))
            if self.path == RELEASE_PATH:
                self.send_response(302)
                self.send_header('Location', '/storage/blob')
                self.end_headers()
            elif self.path == '/storage/blob':
                self.send_response(200)
                self.send_header('Content-Length', str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY)
            else:
                self.send_error(404)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}', seen
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def no_login(monkeypatch):
    monkeypatch.setattr(fn, '_gh_ready', lambda: False)
    for name in (*fn.TOKEN_VARS, fn.ARCHIVES_VAR):
        monkeypatch.delenv(name, raising=False)


def _spec_for(base, path=RELEASE_PATH):
    return {'repo': 'ssbmNucleus/HSDLib', 'tag': 'nucleus-v0.9.0', 'asset': ASSET, 'url': base + path}


def test_with_no_login_a_public_release_downloads_from_its_plain_link(github, no_login, tmp_path):
    base, seen = github
    archive = fn.fetch_archive(_spec_for(base), tmp_path)
    assert archive == tmp_path / ASSET
    assert archive.read_bytes() == BODY
    assert seen == [(RELEASE_PATH, None), ('/storage/blob', None)]


def test_with_no_login_a_missing_or_private_release_says_how_to_log_in(github, no_login, tmp_path):
    base, _ = github
    with pytest.raises(SystemExit) as stop:
        fn.fetch_archive(_spec_for(base, '/ssbmNucleus/HSDLib/releases/download/nucleus-v0.9.0/missing.zip'), tmp_path)
    text = str(stop.value)
    assert 'ssbmNucleus/HSDLib release nucleus-v0.9.0 has no' in text
    assert '`gh auth login`' in text and 'NUCLEUS_FETCH_TOKEN' in text


def test_a_refused_token_falls_back_to_the_public_link(github, no_login, monkeypatch, tmp_path, capsys):
    base, seen = github
    monkeypatch.setenv('NUCLEUS_FETCH_TOKEN', 'not-a-real-token')

    def refuse(repo, tag, asset, destination, token):
        raise urllib.error.HTTPError('https://api.github.com/x', 401, 'Unauthorized', {}, None)

    monkeypatch.setattr(fn, '_download_with_token', refuse)
    archive = fn.fetch_archive(_spec_for(base), tmp_path)
    assert archive.read_bytes() == BODY
    assert all(auth is None for _, auth in seen), 'the token must never reach the public link'
    assert 'GitHub refused the token (401 Unauthorized)' in capsys.readouterr().out


def test_a_working_token_is_used_and_the_public_link_is_not_tried(no_login, monkeypatch, tmp_path):
    monkeypatch.setenv('NUCLEUS_FETCH_TOKEN', 'token')
    monkeypatch.setattr(fn, '_download_with_token',
                        lambda repo, tag, asset, destination, token: destination.write_bytes(BODY))
    monkeypatch.setattr(fn.fetch_common, 'download',
                        lambda *a, **k: pytest.fail('the public link was tried after the token worked'))
    assert fn.fetch_archive(_spec_for('http://unused'), tmp_path).read_bytes() == BODY


def test_the_manifest_url_is_the_release_link_the_fallback_takes():
    spec = fn.load_tool('hsdlib', 'win-x64')
    assert spec['url'] == f'https://github.com/{spec["repo"]}/releases/download/{spec["tag"]}/{spec["asset"]}'
