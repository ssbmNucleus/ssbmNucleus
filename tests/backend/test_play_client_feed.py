"""The Nucleus game client feed (play/client_feed.py, play/ed25519.py): the signature, the schema,
the trusted origin, the download and the unpack, each refusing what it must. No network: a
stand-in session serves the bytes, and every key here is a throwaway made by the test."""
from tests.paths import APP, BACKEND
import ast
import base64
import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from tests.left_out import left_out

sys.path.insert(0, str(BACKEND))

from play import client_feed, ed25519  # noqa: E402

eddsa = pytest.importorskip('Cryptodome.Signature.eddsa')
ECC = pytest.importorskip('Cryptodome.PublicKey.ECC')

HOST = 'https://releases.ssbmnucleus.net/client/windows'
CLIENT_FILES = {
    'melee_source.exe': b'MZ source port',
    'melee_game.dll': b'MZ game',
    'Sys/codes.ini': b'[codes]\n',
    'README.txt': b'Nucleus\n',
}


# --------------------------------------------------------------------------- a release, as client_release.py makes one

#: The packaged program's --print-info answer, as a release build gives it (the client's early_start.cpp).
PRINT_INFO = {'version': '1.0.7', 'product': 'Nucleus', 'upstream': 'Melee Unlocked', 'engine': 'source',
              'cpu_baseline': 'AVX2', 'cpu_supported': True, 'game_library': 'melee_game.dll', 'plugin_format': 2,
              'plugin_abi': '5893c5d6ceb0ce7ae2ed556efdcfba98', 'linked_fighters': [],
              'fighters_folder': '<release>\\fighters', 'fighters_dir': True, 'no_crash_dialog': True,
              'no_dialogs': True, 'public_build': True, 'game_public_build': True, 'plugin_signing_keys': 1,
              'plugin_test_key': False, 'plugins_blocked': []}
NAME = client_feed.PACKAGE_NAME.format(version='1.0.7')        # NucleusClient-1.0.7-win64


def make_release(version='1.0.7', files=None, *, name=None, extra_entries=(), skip=(), inner=None,
                 mode=0o644, commit='81447d35c0ffee81447d35c0ffee81447d35c0f', with_inner=True, print_info=None):
    """(zip_bytes, sidecar_bytes, sidecar) for a client release laid out exactly as the client's
    windows-build/client_release.py lays it out (package, make_zip): one folder NucleusClient-<v>-win64/,
    the files sorted, release-manifest.json last, and beside the ZIP the same manifest plus `zip`.
    `extra_entries` (path, bytes) are added to the ZIP only, `skip` leaves listed files out of it,
    `inner` replaces release-manifest.json's contents and `with_inner=False` leaves it out."""
    files = dict(CLIENT_FILES if files is None else files)
    name = name or client_feed.PACKAGE_NAME.format(version=version)
    sidecar = {
        'format': 1, 'kind': client_feed.MANIFEST_KIND, 'name': name, 'version': version,
        'git_commit': commit, 'git_dirty': False, 'created': '2026-11-25T08:00:00Z',
        'toolchains': {'host': 'MSVC 19.42.34435.0', 'game': 'GNU 14.2.0'},
        'plugin_format': 2, 'plugin_abi': PRINT_INFO['plugin_abi'],
        'notes': ['no DLSS runtime: the host was built without Streamline'],
        'print_info': {**PRINT_INFO, 'version': version, **(print_info or {})},
        'files': [{'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for path, data in sorted(files.items())],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, data in sorted(files.items()):
            if path in skip:
                continue
            info = zipfile.ZipInfo(f'{name}/{path}', date_time=(2026, 11, 25, 8, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = mode << 16
            archive.writestr(info, data)
        if with_inner:
            info = zipfile.ZipInfo(f'{name}/{client_feed.INNER_MANIFEST}', date_time=(2026, 11, 25, 8, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, inner if inner is not None else (json.dumps(sidecar, indent=2) + '\n').encode())
        for path, data in extra_entries:
            info = zipfile.ZipInfo(path, date_time=(2026, 11, 25, 8, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    data = buffer.getvalue()
    sidecar['zip'] = {'name': f'{name}.zip', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return data, json.dumps(sidecar, indent=2).encode(), sidecar


def make_feed(zip_bytes, sidecar_bytes, sidecar, *, base=HOST, min_app='0.9.3', **changes):
    feed = {
        'schema': client_feed.FEED_SCHEMA, 'format': 1, 'version': sidecar['version'], 'minAppVersion': min_app,
        'notes': f'Nucleus {sidecar["version"]}', 'pub_date': '2026-11-26T08:00:00Z', 'commit': sidecar['git_commit'],
        'platforms': {client_feed.PLATFORM_KEY: {
            'url': f'{base}/{sidecar["name"]}.zip', 'size': len(zip_bytes),
            'sha256': hashlib.sha256(zip_bytes).hexdigest(),
            'manifest': {'url': f'{base}/{sidecar["name"]}.manifest.json', 'size': len(sidecar_bytes),
                         'sha256': hashlib.sha256(sidecar_bytes).hexdigest()},
        }},
    }
    feed.update(changes)
    return feed


class Key:
    """A throwaway Ed25519 key, signing the way tools/build/release_to_r2.py does."""

    def __init__(self):
        self.key = ECC.generate(curve='Ed25519')
        self.public = self.key.public_key().export_key(format='raw')
        self.pem = self.key.public_key().export_key(format='PEM')

    def sign(self, feed):
        value = eddsa.new(self.key, 'rfc8032').sign(client_feed.canonical_bytes(feed))
        return {**feed, 'signature': {'algorithm': 'ed25519', 'value': base64.b64encode(value).decode()}}

    def source(self):
        return client_feed.Source(client_feed.CLIENT_FEED_URL, self.public, 'https', client_feed.RELEASES_HOST,
                                  443, client_feed.CLIENT_PATH_PREFIX, False)


def encoded(feed):
    return json.dumps(feed).encode()


class Reply:
    def __init__(self, status=200, body=b'', headers=None, chunk=7, on_chunk=None):
        self.status_code, self.body, self.headers = status, body, dict(headers or {})
        self.chunk, self.on_chunk, self.closed = chunk, on_chunk, False

    def iter_content(self, size):
        step = min(size, self.chunk)
        for at in range(0, len(self.body), step):
            if self.on_chunk:
                self.on_chunk(at)
            yield self.body[at:at + step]

    def close(self):
        self.closed = True


class Session:
    """requests.Session's get, answering from `routes` (url without query -> Reply | bytes)."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def get(self, url, **kw):
        assert kw.get('allow_redirects') is False and kw.get('stream') is True
        self.asked.append(url)
        answer = self.routes.get(url.split('?')[0])
        if answer is None:
            return Reply(404)
        return answer if isinstance(answer, Reply) else Reply(200, answer, {'Content-Length': str(len(answer))})


# --------------------------------------------------------------------------- the signature

RFC8032 = [
    ('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', '',
     'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'),
    ('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c', '72',
     '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00'),
]


@pytest.mark.parametrize('public, message, signature', RFC8032)
def test_the_verifier_passes_rfc8032_and_refuses_any_changed_bit(public, message, signature):
    public, message, signature = bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)
    assert ed25519.verify(public, message, signature) is True
    for at in (0, 31, 32, 63):
        bad = bytearray(signature)
        bad[at] ^= 0x01
        assert ed25519.verify(public, message, bytes(bad)) is False
    assert ed25519.verify(public, message + b'x', signature) is False
    assert ed25519.verify(public[:31] + bytes([public[31] ^ 1]), message, signature) is False
    assert ed25519.verify(public, message, signature[:63]) is False


def test_the_verifier_agrees_with_a_second_implementation():
    for size in (0, 1, 64, 1000):
        key = Key()
        message = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
        signature = eddsa.new(key.key, 'rfc8032').sign(message)
        assert ed25519.verify(key.public, message, signature) is True
        assert ed25519.verify(Key().public, message, signature) is False
        assert ed25519.public_key_from_pem(key.pem) == key.public


def test_a_signature_whose_s_is_not_reduced_is_refused():
    """S + L verifies the same equation; RFC 8032 (and OpenSSL) refuse it, so must this."""
    public, _, signature = (bytes.fromhex(part) for part in RFC8032[0])
    s = int.from_bytes(signature[32:], 'little') + ed25519._L
    assert ed25519.verify(public, b'', signature[:32] + s.to_bytes(32, 'little')) is False


def test_the_embedded_key_is_the_app_update_key():
    """One trust scheme: the client feed is checked with the key electron/updates/updater.js uses."""
    pem = (APP / 'electron' / 'updates' / 'update-public-key.pem').read_text(encoding='ascii')
    assert ed25519.public_key_from_pem(pem) == ed25519.public_key_from_pem(client_feed.PRODUCTION_PUBLIC_KEY_PEM)
    assert client_feed.production_source().public_key == ed25519.public_key_from_pem(pem)


def _function_from(path, name):
    """A top-level function of a script, without importing the script (release_to_r2 reads credentials
    files at import's neighbors; nothing here may)."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    space = {'json': json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), space)
    return space[name]


@left_out('tools/build/release_to_r2.py', why='owner-only release publisher')
def test_the_signed_bytes_are_the_signers_bytes():
    tools = APP.parent / 'tools' / 'build'
    release = _function_from(tools / 'release_to_r2.py', 'canonical_manifest_bytes')
    helper = _function_from(tools / 'client_feed.py', 'canonical_manifest_bytes')
    zip_bytes, sidecar_bytes, sidecar = make_release()
    feed = make_feed(zip_bytes, sidecar_bytes, sidecar, notes='Nucleus 1.0.7 — “quotes”, ünïcode')
    assert client_feed.canonical_bytes(feed) == release(feed) == helper(feed)


# --------------------------------------------------------------------------- the feed

@pytest.fixture
def release():
    zip_bytes, sidecar_bytes, sidecar = make_release()
    return zip_bytes, sidecar_bytes, sidecar


def test_a_good_feed_is_read():
    key = Key()
    release = make_release('0.1.0')
    feed = make_feed(*release, min_app='0.10.0')
    offer = client_feed.read_feed(encoded(key.sign(feed)), key.source())
    assert offer.version == '0.1.0' and offer.min_app_version == '0.10.0'
    assert offer.url == f'{HOST}/NucleusClient-0.1.0-win64.zip'
    assert offer.size == len(release[0]) and offer.sha256 == hashlib.sha256(release[0]).hexdigest()
    assert offer.public('0.10.0')['appTooOld'] is False
    assert offer.public('0.10.0-play-preview.1')['appTooOld'] is False
    assert offer.public('0.9.2')['appTooOld'] is True


def test_a_bad_signature_wrong_key_or_none_is_refused(release):
    key = Key()
    signed = key.sign(make_feed(*release))
    flipped = json.loads(json.dumps(signed))
    raw = bytearray(base64.b64decode(flipped['signature']['value']))
    raw[5] ^= 0x10
    flipped['signature']['value'] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(client_feed.FeedError, match='not signed by Nucleus'):
        client_feed.read_feed(encoded(flipped), key.source())
    with pytest.raises(client_feed.FeedError, match='not signed by Nucleus'):
        client_feed.read_feed(encoded(signed), Key().source())
    # A field changed after signing (a bigger ZIP, another address) is not what was signed.
    for field, value in (('version', '1.0.8'), ('minAppVersion', '0.0.1')):
        with pytest.raises(client_feed.FeedError, match='not signed by Nucleus'):
            client_feed.read_feed(encoded({**signed, field: value}), key.source())
    unsigned = {k: v for k, v in signed.items() if k != 'signature'}
    with pytest.raises(client_feed.FeedError, match='not signed'):
        client_feed.read_feed(encoded(unsigned), key.source())
    with pytest.raises(client_feed.FeedError, match='not signed'):
        client_feed.read_feed(encoded({**signed, 'signature': {'algorithm': 'rsa', 'value': 'AAAA'}}), key.source())
    # The production key is not a throwaway one: a test-signed feed never passes the real source.
    with pytest.raises(client_feed.FeedError, match='not signed by Nucleus'):
        client_feed.read_feed(encoded(signed), client_feed.production_source())


@pytest.mark.parametrize('url', [
    'http://releases.ssbmnucleus.net/client/windows/x.zip',
    'https://releases.ssbmnucleus.net.evil.example/client/windows/x.zip',
    'https://evil.example/client/windows/x.zip',
    'https://releases.ssbmnucleus.net/windows/x.zip',                 # the app's own folder, not the client's
    'https://releases.ssbmnucleus.net/client/windows/../x.zip',
    'https://releases.ssbmnucleus.net/client/windows/%2e%2e/x.zip',
    'https://user:pw@releases.ssbmnucleus.net/client/windows/x.zip',
    'https://releases.ssbmnucleus.net:8443/client/windows/x.zip',
    'https://releases.ssbmnucleus.net/client/windows/x.exe',
    'file:///C:/client/windows/x.zip',
])
def test_a_download_on_another_origin_is_refused_even_when_signed(release, url):
    key = Key()
    feed = make_feed(*release)
    feed['platforms'][client_feed.PLATFORM_KEY]['url'] = url
    with pytest.raises(client_feed.FeedError, match='does not trust|wrong kind'):
        client_feed.read_feed(encoded(key.sign(feed)), key.source())


@pytest.mark.parametrize('change, why', [
    ({'schema': 'something-else'}, 'format 1'),
    ({'format': 2}, 'format 1'),
    ({'version': '1.0'}, 'X.Y.Z'),
    ({'version': '1.0.7-beta'}, 'X.Y.Z'),
    ({'minAppVersion': None}, 'minimum app version'),
    ({'platforms': {}}, 'no Windows client'),
])
def test_a_feed_off_its_schema_is_refused(release, change, why):
    key = Key()
    with pytest.raises(client_feed.FeedError, match=why):
        client_feed.read_feed(encoded(key.sign(make_feed(*release, **change))), key.source())


def test_sizes_and_hashes_must_be_there(release):
    key = Key()
    for field, value in (('size', 0), ('size', -1), ('size', 1.5), ('size', True), ('sha256', 'ABC'), ('size', 2 ** 40)):
        feed = make_feed(*release)
        feed['platforms'][client_feed.PLATFORM_KEY][field] = value
        if isinstance(value, float):
            with pytest.raises(client_feed.FeedError):
                client_feed.read_feed(encoded(key.sign(feed)), key.source())
            continue
        with pytest.raises(client_feed.FeedError, match='size or SHA-256'):
            client_feed.read_feed(encoded(key.sign(feed)), key.source())


def test_duplicate_keys_and_floats_are_not_json_the_signer_wrote(release):
    key = Key()
    text = json.dumps(key.sign(make_feed(*release)))
    with pytest.raises(client_feed.FeedError, match='not valid JSON'):
        client_feed.read_feed(('{"version": "9.9.9", ' + text[1:]).encode(), key.source())
    with pytest.raises(client_feed.FeedError, match='not valid JSON'):
        client_feed.read_feed(b'{"format": 1.0}', key.source())
    with pytest.raises(client_feed.FeedError, match='too large'):
        client_feed.read_feed(b' ' * (client_feed.MAX_FEED_BYTES + 1), key.source())


# --------------------------------------------------------------------------- where the feed is read

def test_the_production_feed_is_the_default(monkeypatch):
    monkeypatch.delenv(client_feed.TEST_FEED_ENV, raising=False)
    monkeypatch.delenv(client_feed.TEST_KEY_ENV, raising=False)
    src = client_feed.source()
    assert src.feed_url == 'https://releases.ssbmnucleus.net/client/windows/latest.json' and src.test is False


def test_a_test_feed_needs_loopback_and_a_key_and_never_in_a_packaged_build(tmp_path, monkeypatch):
    key = Key()
    pem = tmp_path / 'test-key.pem'
    pem.write_bytes(key.pem.encode() if isinstance(key.pem, str) else key.pem)
    good = {client_feed.TEST_FEED_ENV: 'http://127.0.0.1:8765/client/windows/latest.json',
            client_feed.TEST_KEY_ENV: str(pem)}
    src = client_feed.source(good)
    assert src.test is True and src.public_key == key.public and src.port == 8765
    for url in ('https://127.0.0.1:8765/x.json', 'http://localhost:8765/x.json', 'http://127.0.0.2:8765/x.json',
                'http://evil.example/x.json', 'http://127.0.0.1/x.json', 'http://u:p@127.0.0.1:8765/x.json'):
        assert client_feed.source({**good, client_feed.TEST_FEED_ENV: url}).test is False, url
    assert client_feed.source({**good, client_feed.TEST_KEY_ENV: str(tmp_path / 'missing.pem')}).test is False
    assert client_feed.source({client_feed.TEST_FEED_ENV: good[client_feed.TEST_FEED_ENV]}).test is False
    # A frozen (packaged) backend never reads either variable.
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert client_feed.source(good) == client_feed.production_source()
    # And a stand-in's own origin is the only one its feed may name.
    monkeypatch.delattr(sys, 'frozen')
    assert client_feed.checked_url('http://127.0.0.1:8765/a.zip', src) == 'http://127.0.0.1:8765/a.zip'
    with pytest.raises(client_feed.FeedError):
        client_feed.checked_url(f'{HOST}/a.zip', src)
    with pytest.raises(client_feed.FeedError):
        client_feed.checked_url('http://127.0.0.1:8766/a.zip', src)


# --------------------------------------------------------------------------- the download

def test_a_download_is_checked_for_length_and_hash(release, tmp_path):
    key = Key()
    zip_bytes = release[0]
    url = f'{HOST}/c.zip'
    sha = hashlib.sha256(zip_bytes).hexdigest()
    fetcher = client_feed.Fetcher(key.source(), session=Session({url: zip_bytes}))
    assert fetcher.download(url, tmp_path / 'ok.zip', size=len(zip_bytes), sha256=sha, suffix='.zip') is True
    assert (tmp_path / 'ok.zip').read_bytes() == zip_bytes
    with pytest.raises(client_feed.FeedError, match='SHA-256'):
        fetcher.download(url, tmp_path / 'hash.zip', size=len(zip_bytes), sha256='0' * 64, suffix='.zip')
    with pytest.raises(client_feed.FeedError, match='size'):
        fetcher.download(url, tmp_path / 'short.zip', size=len(zip_bytes) - 1, sha256=sha, suffix='.zip')
    longer = client_feed.Fetcher(key.source(), session=Session({url: Reply(200, zip_bytes + b'x')}))
    with pytest.raises(client_feed.FeedError, match='larger'):
        longer.download(url, tmp_path / 'long.zip', size=len(zip_bytes), sha256=sha, suffix='.zip')
    early = client_feed.Fetcher(key.source(), session=Session({url: Reply(200, zip_bytes[:-3])}))
    with pytest.raises(client_feed.FeedError, match='stopped early'):
        early.download(url, tmp_path / 'early.zip', size=len(zip_bytes), sha256=sha, suffix='.zip')
    # A Cancel between chunks stops it (the caller removes the partial file).
    stop = client_feed.Fetcher(key.source(), session=Session({url: zip_bytes}))
    asked = []
    assert stop.download(url, tmp_path / 'stop.zip', size=len(zip_bytes), sha256=sha, suffix='.zip',
                         should_stop=lambda: asked.append(1) or len(asked) > 2) is False


def test_a_connection_that_drops_partway_is_said_plainly(release, tmp_path):
    # The real releases server closing the connection after its Content-Length was sent: requests
    # raises ChunkedEncodingError (IncompleteRead) from inside iter_content, not a FeedError.
    requests = pytest.importorskip('requests')
    key = Key()
    zip_bytes = release[0]
    url = f'{HOST}/c.zip'
    sha = hashlib.sha256(zip_bytes).hexdigest()

    def drop(at):
        if at >= 21:
            raise requests.exceptions.ChunkedEncodingError('Connection broken: IncompleteRead(21 bytes read)')

    reply = Reply(200, zip_bytes, {'Content-Length': str(len(zip_bytes))}, on_chunk=drop)
    fetcher = client_feed.Fetcher(key.source(), session=Session({url: reply}))
    with pytest.raises(client_feed.FeedError, match=r'interrupted.*Try again\. \(ChunkedEncodingError\)'):
        fetcher.download(url, tmp_path / 'dropped.zip', size=len(zip_bytes), sha256=sha, suffix='.zip')
    assert reply.closed
    # The feed and the file list are read the same way.
    feed = Reply(200, b'{"schema": "nucleus-client-feed"}' * 4, on_chunk=drop)
    fetcher = client_feed.Fetcher(key.source(), session=Session({f'{HOST}/latest.json': feed}))
    with pytest.raises(client_feed.FeedError, match='interrupted'):
        fetcher.get_bytes(f'{HOST}/latest.json', limit=client_feed.MAX_FEED_BYTES)
    assert feed.closed


def test_a_cancel_ends_the_download_at_once_while_the_server_sends_nothing(release, tmp_path, monkeypatch):
    # A real loopback server that sends half the ZIP and then stalls. The read is blocked in the socket,
    # which another thread cannot wake on Windows: the body is read on a helper thread, so the Cancel is
    # noticed within a fraction of a second, the partial file is already closed (it can be removed at
    # once), and the abandoned reader ends on its own at the read timeout.
    pytest.importorskip('requests')
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    zip_bytes = release[0]
    half = len(zip_bytes) // 2
    stalled, release_server = threading.Event(), threading.Event()

    class Stalls(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes[:half])
            self.wfile.flush()
            stalled.set()
            release_server.wait(20)
            try:
                self.wfile.write(zip_bytes[half:])
            except OSError:
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Stalls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        src = client_feed.Source(f'http://127.0.0.1:{port}/latest.json', Key().public, 'http', '127.0.0.1',
                                 port, '/', True)
        monkeypatch.setattr(client_feed.Fetcher, 'TIMEOUT', (5, 1.5))      # the read timeout, made short
        stop, stopped_at = threading.Event(), []

        def cancel_once_stalled():
            stalled.wait(10)
            time.sleep(0.3)
            stopped_at.append(time.monotonic())
            stop.set()
        threading.Thread(target=cancel_once_stalled, daemon=True).start()
        target = tmp_path / 'stalled.zip'
        done = client_feed.Fetcher(src).download(f'http://127.0.0.1:{port}/c.zip', target, size=len(zip_bytes),
                                                 sha256=hashlib.sha256(zip_bytes).hexdigest(), suffix='.zip',
                                                 should_stop=stop.is_set)
        assert done is False
        assert time.monotonic() - stopped_at[0] < 1.0
        target.unlink()                                  # closed already: removable at once, even on Windows
        readers = [t for t in threading.enumerate() if t.name == 'client-download-reader']
        assert readers                                   # still blocked on the stalled server
        for reader in readers:
            reader.join(1.5 + 3)
            assert not reader.is_alive()                 # ended on its own at the read timeout
        assert not target.exists()
    finally:
        release_server.set()
        server.shutdown()
        server.server_close()


def test_redirects_stay_on_the_trusted_origin(release, tmp_path):
    key = Key()
    zip_bytes = release[0]
    sha = hashlib.sha256(zip_bytes).hexdigest()
    url = f'{HOST}/c.zip'
    inside = Session({url: Reply(302, headers={'Location': '/client/windows/mirror/c.zip'}),
                      f'{HOST}/mirror/c.zip': zip_bytes})
    fetcher = client_feed.Fetcher(key.source(), session=inside)
    assert fetcher.download(url, tmp_path / 'in.zip', size=len(zip_bytes), sha256=sha, suffix='.zip') is True
    for target in ('https://evil.example/client/windows/c.zip', 'http://releases.ssbmnucleus.net/client/windows/c.zip',
                   '/somewhere/else.zip'):
        away = Session({url: Reply(302, headers={'Location': target})})
        with pytest.raises(client_feed.FeedError, match='does not trust'):
            client_feed.Fetcher(key.source(), session=away).download(
                url, tmp_path / 'away.zip', size=len(zip_bytes), sha256=sha, suffix='.zip')
        assert away.asked == [url]
    loop = Session({url: Reply(302, headers={'Location': url})})
    with pytest.raises(client_feed.FeedError, match='too many'):
        client_feed.Fetcher(key.source(), session=loop).get_bytes(url, limit=10, suffix='.zip')


# --------------------------------------------------------------------------- the file list and the unpack

def _offer_for(release):
    key = Key()
    return client_feed.read_feed(encoded(key.sign(make_feed(*release))), key.source())


def _unpack(tmp_path, zip_bytes, sidecar_bytes, offer):
    files = client_feed.read_manifest(sidecar_bytes, offer)
    path = tmp_path / 'download.zip'
    path.write_bytes(zip_bytes)
    return client_feed.extract(path, tmp_path / 'out', files)


def test_a_good_release_unpacks_file_for_file(release, tmp_path):
    zip_bytes, sidecar_bytes, sidecar = release
    written = _unpack(tmp_path, zip_bytes, sidecar_bytes, _offer_for(release))
    assert written == sum(len(data) for data in CLIENT_FILES.values())
    for path, data in CLIENT_FILES.items():
        assert (tmp_path / 'out' / path).read_bytes() == data
    inner = json.loads((tmp_path / 'out' / client_feed.INNER_MANIFEST).read_text(encoding='utf-8'))
    assert inner == {k: v for k, v in sidecar.items() if k != 'zip'}


def _refused(tmp_path, release, match, *, sidecar_bytes=None, offer=None):
    zip_bytes, listed, _ = release
    offer = offer or _offer_for(release)
    with pytest.raises(client_feed.FeedError, match=match):
        _unpack(tmp_path, zip_bytes, sidecar_bytes or listed, offer)
    escaped = [p for p in tmp_path.rglob('*') if p.is_file() and 'out' not in p.relative_to(tmp_path).parts
               and p.name != 'download.zip']
    assert escaped == [], escaped


@pytest.mark.parametrize('entry', [
    f'{NAME}/../evil.txt',
    f'{NAME}/Sys/../../evil.txt',
    '../evil.txt',
    '/evil.txt',
    'C:/evil.txt',
    f'{NAME}/C:evil.txt',
    f'{NAME}/CON',
    f'{NAME}/nul.txt',
    f'{NAME}/trailing. ',
    f'{NAME}\\..\\evil.txt',
    'MeleeUnlocked-1.0.7-client-win64/melee_source.exe',    # the old folder name
])
def test_a_path_that_leaves_the_folder_is_refused(tmp_path, entry):
    release = make_release(extra_entries=[(entry, b'evil')])
    _refused(tmp_path, release, 'outside its folder|path Nucleus refuses|does not name')
    assert not (tmp_path / 'evil.txt').exists()


def test_an_extra_file_is_refused(tmp_path):
    release = make_release(extra_entries=[(f'{NAME}/extra.dll', b'MZ')])
    _refused(tmp_path, release, 'does not name')
    # Nor a batch file the packager no longer ships.
    work = tmp_path / 'bat'
    work.mkdir()
    _refused(work, make_release(extra_entries=[(f'{NAME}/MeleeUnlocked.bat', b'@echo off\r\n')]), 'does not name')


def test_a_zip_without_its_release_manifest_is_refused(tmp_path):
    _refused(tmp_path, make_release(with_inner=False), 'no release-manifest.json')


def test_a_missing_file_is_refused(tmp_path):
    release = make_release(skip={'README.txt'})
    _refused(tmp_path, release, "lacks 1 file.*'README.txt'")


def test_a_file_twice_is_refused(tmp_path):
    release = make_release(extra_entries=[(f'{NAME}/readme.TXT', b'Nucleus\n')])
    _refused(tmp_path, release, 'twice|does not name')


def test_a_file_that_differs_from_its_list_is_refused(tmp_path):
    zip_bytes, sidecar_bytes, sidecar = make_release()
    for change, match in (({'size': 999}, 'not the size'), ({'sha256': '0' * 64}, 'not the file its file list names')):
        listed = json.loads(sidecar_bytes)
        entry = next(e for e in listed['files'] if e['path'] == 'melee_game.dll')
        entry.update(change)
        changed = json.dumps(listed).encode()
        work = tmp_path / change.popitem()[0]
        work.mkdir()
        _refused(work, (zip_bytes, changed, listed), match)


def test_links_and_encrypted_entries_are_refused(tmp_path):
    release = make_release(mode=stat.S_IFLNK | 0o777)
    _refused(tmp_path, release, 'link or special file')


def test_the_inner_manifest_must_say_what_the_list_says(tmp_path):
    release = make_release(inner=b'{"format": 1, "version": "6.6.6"}')
    _refused(tmp_path, release, 'differs from the file list')


def test_the_file_list_must_be_for_this_release(release):
    zip_bytes, sidecar_bytes, sidecar = release
    offer = _offer_for(release)
    zip_facts = sidecar['zip']
    for change, match in (({'version': '1.0.6'}, 'version'), ({'kind': 'other'}, 'format 1 nucleus-client'),
                          ({'kind': 'melee-unlocked-source-port-client'}, 'format 1 nucleus-client'),
                          ({'format': 2}, 'format 1 nucleus-client'),
                          ({'zip': {**zip_facts, 'size': 1}}, 'different download'),
                          ({'zip': {**zip_facts, 'sha256': '0' * 64}}, 'different download'),
                          ({'zip': {**zip_facts, 'name': 'MeleeUnlocked-1.0.7-client-win64.zip'}}, 'different download'),
                          ({'zip': None}, 'different download'),
                          ({'files': []}, 'lists no files'), ({'name': '../x'}, 'names its folder'),
                          ({'name': 'MeleeUnlocked-1.0.7-client-win64'}, 'names its folder')):
        with pytest.raises(client_feed.FeedError, match=match):
            client_feed.read_manifest(json.dumps({**sidecar, **change}).encode(), offer)
    with pytest.raises(client_feed.FeedError, match='different download'):
        client_feed.read_manifest(json.dumps({k: v for k, v in sidecar.items() if k != 'zip'}).encode(), offer)
    for path in ('../x.dll', 'a//b', 'Sys\\x', 'aux', 'x:y', client_feed.INNER_MANIFEST):
        files = sidecar['files'] + [{'path': path, 'size': 1, 'sha256': '0' * 64}]
        with pytest.raises(client_feed.FeedError, match='refuses'):
            client_feed.read_manifest(json.dumps({**sidecar, 'files': files}).encode(), offer)
    without = [e for e in sidecar['files'] if e['path'] != 'melee_game.dll']
    with pytest.raises(client_feed.FeedError, match='no melee_game.dll'):
        client_feed.read_manifest(json.dumps({**sidecar, 'files': without}).encode(), offer)


def test_the_feed_must_name_the_packagers_files(release):
    zip_bytes, sidecar_bytes, sidecar = release
    key = Key()
    for field, url in (('url', f'{HOST}/renamed.zip'), ('manifest', f'{HOST}/renamed.manifest.json')):
        feed = make_feed(*release)
        platform = feed['platforms'][client_feed.PLATFORM_KEY]
        if field == 'url':
            platform['url'] = url
        else:
            platform['manifest']['url'] = url
        offer = client_feed.read_feed(encoded(key.sign(feed)), key.source())
        with pytest.raises(client_feed.FeedError, match=f'does not name the files {NAME}.zip'):
            client_feed.read_manifest(sidecar_bytes, offer)


def test_the_sidecar_may_carry_any_print_info_number(tmp_path):
    # print_info is the program's own answer; a fractional number in it must not refuse the release,
    # though the signed feed itself stays whole numbers only.
    release = make_release(print_info={'frame_ms': 16.67})
    assert b'16.67' in release[1]
    assert _unpack(tmp_path, release[0], release[1], _offer_for(release)) > 0
    with pytest.raises(client_feed.FeedError, match='not valid JSON'):
        client_feed.strict_json(b'{"size": 1.5}')
    with pytest.raises(client_feed.FeedError, match='not valid JSON'):
        client_feed.strict_json(b'{"size": NaN}', floats=True)


def test_the_file_list_download_is_pinned_by_the_feed(release):
    zip_bytes, sidecar_bytes, sidecar = release
    key = Key()
    offer = client_feed.read_feed(encoded(key.sign(make_feed(*release))), key.source())
    good = client_feed.Fetcher(key.source(), session=Session({offer.manifest_url: sidecar_bytes}))
    assert client_feed.fetch_file_list(good, offer).version == '1.0.7'
    swapped = sidecar_bytes.replace(b'"git_dirty": false', b'"git_dirty": true ')
    bad = client_feed.Fetcher(key.source(), session=Session({offer.manifest_url: swapped}))
    with pytest.raises(client_feed.FeedError, match='SHA-256'):
        client_feed.fetch_file_list(bad, offer)


# --------------------------------------------------------------------------- the publisher's helper

def test_the_publisher_helper_writes_the_feed_the_app_reads(release, tmp_path):
    sys.path.insert(0, str(APP.parent / 'tools' / 'build'))
    try:
        import client_feed as helper
    finally:
        sys.path.pop(0)
    zip_bytes, sidecar_bytes, sidecar = release
    zip_path, sidecar_path = tmp_path / f'{NAME}.zip', tmp_path / f'{NAME}.manifest.json'
    zip_path.write_bytes(zip_bytes)
    sidecar_path.write_bytes(sidecar_bytes)
    feed = helper.build_feed(zip_path, sidecar_path, min_app_version='0.9.3', pub_date='2026-11-26T08:00:00Z')
    key = Key()
    offer = client_feed.read_feed(encoded(key.sign(feed)), key.source())
    assert offer.version == '1.0.7' and offer.size == len(zip_bytes)
    assert offer.url == f'{HOST}/NucleusClient-1.0.7-win64.zip'
    assert offer.manifest_url == f'{HOST}/NucleusClient-1.0.7-win64.manifest.json'
    # A ZIP that is not the sidecar's, or files under other names, are refused before anything is written.
    other = tmp_path / 'other'
    other.mkdir()
    (other / f'{NAME}.zip').write_bytes(zip_bytes + b'x')
    with pytest.raises(SystemExit, match='not the ZIP'):
        helper.build_feed(other / f'{NAME}.zip', sidecar_path, min_app_version='0.9.3')
    (other / 'MeleeUnlocked-1.0.7-client-win64.zip').write_bytes(zip_bytes)
    with pytest.raises(SystemExit, match=f'must be named {NAME}.zip'):
        helper.build_feed(other / 'MeleeUnlocked-1.0.7-client-win64.zip', sidecar_path, min_app_version='0.9.3')

    def refused(change, match):
        work = tmp_path / f'case{len(list(tmp_path.iterdir()))}'
        work.mkdir()
        (work / f'{NAME}.zip').write_bytes(zip_bytes)
        (work / f'{NAME}.manifest.json').write_text(json.dumps({**json.loads(sidecar_bytes), **change}),
                                                     encoding='utf-8')
        with pytest.raises(SystemExit, match=match):
            helper.build_feed(work / f'{NAME}.zip', work / f'{NAME}.manifest.json', min_app_version='0.9.3')
    refused({'git_dirty': True}, 'git_dirty')
    refused({'kind': 'melee-unlocked-source-port-client'}, "not 'nucleus-client'")
    refused({'print_info': {**PRINT_INFO, 'public_build': False}}, 'not a release build')
    refused({'print_info': {**PRINT_INFO, 'game_public_build': None}}, 'not a release build')
    refused({'zip': {**sidecar['zip'], 'name': 'other.zip'}}, "names 'other.zip'")
    # The command it prints is the release tool's client mode, never run here.
    assert '--client-zip' in helper.release_command(Path('a.zip'), Path('a.manifest.json'), '0.9.3', '', True)
