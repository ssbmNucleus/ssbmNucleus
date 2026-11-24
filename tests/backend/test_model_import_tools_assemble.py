"""The model import tools' assembly (randall/model_import/tools/assemble.py) against a local HTTP server and tiny
fake archives: Range resume, checksums, path safety, cancel, the atomic rename and the update cleanup. No real
download: every file is a few KB served from memory on 127.0.0.1."""
import hashlib
import http.server
import io
import json
import os
import re
import ssl
import stat
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from randall.model_import.tools import assemble


# ------------------------------------------------------------------ a local server that serves bytes from memory

class _State:
    def __init__(self):
        self.files = {}
        self.requests = []          # (name, Range header or None)
        self.ignore_range = False   # answer a Range request with the whole file (200)
        self.fail_once = set()      # names whose next reply stops half way through its body
        self.status = {}            # name: an HTTP error code it always answers (403: a host that turns us away)


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        state = self.server.state
        name = self.path.lstrip('/')
        ranged = self.headers.get('Range')
        state.requests.append((name, ranged))
        if name in state.status:
            self.send_error(state.status[name])
            return
        data = state.files.get(name)
        if data is None:
            self.send_error(404)
            return
        try:
            if name in state.fail_once:
                state.fail_once.discard(name)
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data[:len(data) // 2])
                self.wfile.flush()
                self.close_connection = True
                return
            start = 0
            if ranged and not state.ignore_range:
                start = int(re.match(r'bytes=(\d+)-', ranged).group(1))
                if start >= len(data):
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{len(data)}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{len(data) - 1}/{len(data)}')
            else:
                self.send_response(200)
            self.send_header('Content-Length', str(len(data) - start))
            self.end_headers()
            self.wfile.write(data[start:])
        except OSError:
            pass                    # the client hung up (a Cancel)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # urllib would take a system proxy from the Windows registry; these requests go to 127.0.0.1 only
    monkeypatch.setenv('NO_PROXY', '*')


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    srv.daemon_threads = True
    srv.state = _State()
    thread = threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _serve(server, path, data, **extra):
    server.state.files[path] = data
    return {'url': f'http://127.0.0.1:{server.server_address[1]}/{path}',
            'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), **extra}


def _zip(members):
    """{name: bytes or None (a folder)} -> zip bytes, the same bytes on every call: each entry has a fixed date
    (writestr(name, data) stamps the current time, so two calls a second apart made a different Blender zip, and
    test_an_update_of_only_the_wheels_keeps_blender saw Blender's sha256 move and download it again)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as bundle:
        for name, data in members.items():
            if data is None:
                bundle.writestr(zipfile.ZipInfo(name), b'')
            else:
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 19, 0, 0, 0))
                info.external_attr = 0o600 << 16          # what writestr(name, data) gives a file
                bundle.writestr(info, data)
    return buffer.getvalue()


def _tar(members):
    """[(name, bytes) or (name, ('symlink', target))] -> tar.gz bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as bundle:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, data[1]
                bundle.addfile(info)
            else:
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _noise(size, seed=1):
    out, block = bytearray(), str(seed).encode()
    while len(out) < size:
        block = hashlib.sha256(block).digest()
        out += block
    return bytes(out[:size])


# ------------------------------------------------------------------ a fake platform entry (win-x64's shape)

def _blender_zip(version):
    top = f'blender-{version}-windows-x64/'
    return _zip({
        top: None,
        top + 'blender.exe': b'MZ fake blender ' + version.encode(),
        top + 'blender.pdb': b'debug symbols',
        top + '4.3/datafiles/locale/de.mo': b'locale',
        top + '4.3/datafiles/colormanagement/config.ocio': b'ocio',
        top + '4.3/datafiles/studiolights/world.exr': b'exr',
        top + '4.3/scripts/addons_core/io_scene_gltf2/__init__.py': b'# gltf',
        top + '4.3/python/lib/site-packages/numpy/__init__.py': b'# numpy',
        top + '4.3/python/bin/python.exe': b'MZ blender python',
    })


def _python_zip():
    return _zip({'python.exe': b'MZ fake python', 'python313.dll': b'dll', 'python313.zip': b'PK stdlib',
                 'python313._pth': b'python313.zip\n.\n#import site\n'})


def _wheels(tiny='1.0'):
    return {
        'tinypkg': _zip({'tinypkg/__init__.py': f'VERSION = {tiny!r}\n'.encode(),
                         f'tinypkg-{tiny}.dist-info/METADATA': b'Name: tinypkg\n',
                         f'tinypkg-{tiny}.data/scripts/evil.py': b'raise SystemExit("ran a script")\n',
                         f'tinypkg-{tiny}.data/headers/tiny.h': b'/* header */'}),
        'purepkg': _zip({'purepkg-2.0.data/purelib/purepkg/__init__.py': b'PURE = True\n',
                         'purepkg-2.0.data/platlib/purepkg/_speed.pyd': b'MZ ext',
                         'purepkg-2.0.dist-info/RECORD': b''}),
    }


def _entry(server, version='4.3.2', tiny='1.0'):
    blender = _serve(server, f'blender-{version}-windows-x64.zip', _blender_zip(version),
                     version=version, format='zip', root=f'blender-{version}-windows-x64', entrypoint='blender.exe',
                     trim=['blender.pdb', '4.3/datafiles/locale', '4.3/scripts/addons_core/cycles', '4.3/python/bin'],
                     verify=['4.3/python/lib/site-packages/numpy/__init__.py',
                             '4.3/scripts/addons_core/io_scene_gltf2/__init__.py',
                             '4.3/datafiles/colormanagement/config.ocio', '4.3/datafiles/studiolights'])
    python = _serve(server, 'python-3.13.17-embed-amd64.zip', _python_zip(),
                    version='3.13.17', format='zip', kind='embeddable', root='', entrypoint='python.exe',
                    site_packages='Lib/site-packages', verify=['python313.zip', 'python313._pth'],
                    wheel_verify=['tinypkg/__init__.py', 'purepkg/__init__.py'])
    versions = {'tinypkg': tiny, 'purepkg': '2.0'}
    wheels = [_serve(server, f'{name}-{versions[name]}-py3-none-any.whl', data, name=name,
                     version=versions[name], filename=f'{name}-{versions[name]}-py3-none-any.whl')
              for name, data in _wheels(tiny).items()]
    return {'blender': blender, 'python': python, 'wheels': wheels}


@pytest.fixture
def nothing_runs(monkeypatch):
    """Fail on any attempt to start a process: nothing from the downloads may run."""
    def refuse(*args, **_kwargs):
        raise AssertionError(f'assembly tried to run {args[:1]!r}')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    monkeypatch.setattr(os, 'system', refuse)
    if hasattr(os, 'startfile'):
        monkeypatch.setattr(os, 'startfile', refuse)


def _root(tmp_path):
    return tmp_path / 'tools' / 'model-import'


BIG = 10 ** 13      # free bytes handed to assemble, so the test does not read the real disk


# ------------------------------------------------------------------ fetch

def test_fetch_downloads_and_checks_a_fresh_file(server, tmp_path):
    data = _noise(5000)
    item = _serve(server, 'piece.bin', data)
    counted = []
    final = assemble.fetch(tmp_path, 'Piece', item, on_bytes=counted.append)
    assert final.read_bytes() == data
    assert final.parent == tmp_path / assemble.DOWNLOADS and final.name.startswith(item['sha256'][:16])
    assert not final.with_name(final.name + '.part').exists()
    assert sum(counted) == len(data)
    assert server.state.requests == [('piece.bin', None)]


def test_fetch_resumes_a_part_with_a_range_request(server, tmp_path):
    data = _noise(5000)
    item = _serve(server, 'piece.bin', data)
    part = assemble._download_path(tmp_path, item)
    part = part.with_name(part.name + '.part')
    part.parent.mkdir(parents=True)
    part.write_bytes(data[:2000])
    counted = []
    final = assemble.fetch(tmp_path, 'Piece', item, on_bytes=counted.append)
    assert server.state.requests == [('piece.bin', 'bytes=2000-')]
    assert assemble.sha256_of(final) == item['sha256']
    assert sum(counted) == 3000


def test_fetch_starts_over_when_the_server_ignores_range(server, tmp_path):
    data = _noise(5000)
    item = _serve(server, 'piece.bin', data)
    server.state.ignore_range = True
    part = assemble._download_path(tmp_path, item)
    part = part.with_name(part.name + '.part')
    part.parent.mkdir(parents=True)
    part.write_bytes(data[:2000])
    counted = []
    final = assemble.fetch(tmp_path, 'Piece', item, on_bytes=counted.append)
    assert server.state.requests == [('piece.bin', 'bytes=2000-')]
    assert final.read_bytes() == data                     # not the part with the whole file appended
    assert sum(counted) == 3000                           # -2000 for the dropped part, +5000


def test_fetch_carries_on_after_a_connection_drops_mid_body(server, tmp_path):
    data = _noise(5000)
    item = _serve(server, 'piece.bin', data)
    server.state.fail_once.add('piece.bin')
    waits = []
    final = assemble.fetch(tmp_path, 'Piece', item, sleep=waits.append)
    assert final.read_bytes() == data
    assert server.state.requests == [('piece.bin', None), ('piece.bin', 'bytes=2500-')]
    assert waits == []                                    # it moved, so no wait before the retry


def test_fetch_refuses_a_bad_checksum_and_deletes_the_part(server, tmp_path):
    item = dict(_serve(server, 'piece.bin', _noise(3000)), sha256='0' * 64)
    with pytest.raises(assemble.Refused, match='checksum'):
        assemble.fetch(tmp_path, 'Piece', item)
    assert list((tmp_path / assemble.DOWNLOADS).iterdir()) == []


def test_fetch_refuses_a_part_that_is_not_this_file(server, tmp_path):
    data = _noise(5000)
    item = _serve(server, 'piece.bin', data)
    part = assemble._download_path(tmp_path, item)
    part = part.with_name(part.name + '.part')
    part.parent.mkdir(parents=True)
    part.write_bytes(b'x' * 2000)                         # resumed onto junk: the sha256 catches it
    with pytest.raises(assemble.Refused, match='checksum'):
        assemble.fetch(tmp_path, 'Piece', item)
    assert not part.exists()


def test_fetch_refuses_a_file_longer_than_its_pin(server, tmp_path):
    data = _noise(5000)
    item = dict(_serve(server, 'piece.bin', data), size=4000)
    with pytest.raises(assemble.Refused, match='4000 are pinned'):
        assemble.fetch(tmp_path, 'Piece', item)
    assert list((tmp_path / assemble.DOWNLOADS).iterdir()) == []


def test_fetch_refuses_a_file_shorter_than_its_pin_without_looping(server, tmp_path):
    # Each try downloads all 4000 bytes, then a 416 on the rest deletes the part: progress that never gets further.
    data = _noise(4000)
    item = dict(_serve(server, 'piece.bin', data), size=5000)
    result = {}

    def run():
        try:
            assemble.fetch(tmp_path, 'Piece', item, sleep=lambda _s: None)
        except Exception as error:      # noqa: BLE001 - handed to the main thread
            result['error'] = error
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(30)
    assert not worker.is_alive(), 'fetch kept retrying a file shorter than its pin'
    assert isinstance(result.get('error'), assemble.Refused)
    assert len(server.state.requests) <= 2 * assemble.RETRIES + 2
    assert list((tmp_path / assemble.DOWNLOADS).iterdir()) == []


def test_fetch_refuses_a_missing_file_at_once(server, tmp_path):
    item = {'url': f'http://127.0.0.1:{server.server_address[1]}/gone.bin', 'sha256': '0' * 64, 'size': 10}
    with pytest.raises(assemble.Refused, match='no longer at'):
        assemble.fetch(tmp_path, 'Gone', item, sleep=lambda _s: pytest.fail('a 404 is not retried'))
    assert server.state.requests == [('gone.bin', None)]


def _mirrored(server, data, *, blocked=(), part=0, tmp_path=None):
    """``data`` on the main site and two mirrors (``site/``, ``m1/``, ``m2/``); ``blocked`` answer 403."""
    base = f'http://127.0.0.1:{server.server_address[1]}/'
    for host in ('site', 'm1', 'm2'):
        server.state.files[f'{host}/piece.bin'] = data
    for host in blocked:
        server.state.status[f'{host}/piece.bin'] = 403
    item = {'url': base + 'site/piece.bin', 'mirrors': [base + 'm1/piece.bin', base + 'm2/piece.bin'],
            'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    if part:
        path = assemble._download_path(tmp_path, item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_name(path.name + '.part').write_bytes(data[:part])
    return item


def test_fetch_goes_to_a_mirror_when_the_site_turns_it_away(server, tmp_path):
    data = _noise(5000)
    item = _mirrored(server, data, blocked=('site',))
    final = assemble.fetch(tmp_path, 'Piece', item, sleep=lambda _s: pytest.fail('a 403 is not waited on'))
    assert final.read_bytes() == data
    assert server.state.requests == [('site/piece.bin', None), ('m1/piece.bin', None)]


def test_fetch_carries_the_part_over_to_the_next_mirror(server, tmp_path):
    data = _noise(5000)
    item = _mirrored(server, data, blocked=('site', 'm1'), part=2000, tmp_path=tmp_path)
    counted = []
    final = assemble.fetch(tmp_path, 'Piece', item, on_bytes=counted.append)
    assert final.read_bytes() == data and sum(counted) == 3000
    assert server.state.requests == [('site/piece.bin', 'bytes=2000-'), ('m1/piece.bin', 'bytes=2000-'),
                                      ('m2/piece.bin', 'bytes=2000-')]


def test_fetch_turned_away_everywhere_says_why_and_how_to_get_it_by_hand(server, tmp_path):
    data = _noise(5000)
    item = _mirrored(server, data, blocked=('site', 'm1', 'm2'), part=2000, tmp_path=tmp_path)
    with pytest.raises(assemble.Refused) as refused:
        assemble.fetch(tmp_path, 'Blender 4.3.2', item, sleep=lambda _s: pytest.fail('a 403 is not waited on'))
    message = str(refused.value)
    assert 'turned this computer away' in message and 'VPN' in message and 'no longer at' not in message
    assert message.count('HTTP 403') == 3 and str(tmp_path / assemble.DOWNLOADS) in message
    assert len(server.state.requests) == 3
    part = assemble._download_path(tmp_path, item)
    assert part.with_name(part.name + '.part').stat().st_size == 2000      # kept for the next press


def test_fetch_missing_everywhere_says_the_tools_list_is_old(server, tmp_path):
    item = _mirrored(server, b'x')
    for name in list(server.state.files):
        server.state.status[name] = 404
    with pytest.raises(assemble.Refused, match='no longer at .*needs an update of its tools list'):
        assemble.fetch(tmp_path, 'Gone', item)
    assert len(server.state.requests) == 3


def test_fetch_takes_a_file_saved_by_hand_under_its_own_name(server, tmp_path):
    data = _noise(5000)
    item = _mirrored(server, data, blocked=('site', 'm1', 'm2'))
    downloads = tmp_path / assemble.DOWNLOADS
    downloads.mkdir()
    (downloads / 'piece.bin').write_bytes(data)                             # what a browser saves
    final = assemble.fetch(tmp_path, 'Piece', item)
    assert final == assemble._download_path(tmp_path, item) and final.read_bytes() == data
    assert not (downloads / 'piece.bin').exists() and server.state.requests == []


def test_fetch_ignores_a_file_by_hand_that_is_not_the_pinned_one(server, tmp_path):
    data = _noise(5000)
    item = _mirrored(server, data)
    downloads = tmp_path / assemble.DOWNLOADS
    downloads.mkdir()
    (downloads / 'piece.bin').write_bytes(b'y' * 5000)
    final = assemble.fetch(tmp_path, 'Piece', item)
    assert final.read_bytes() == data and (downloads / 'piece.bin').read_bytes() == b'y' * 5000
    assert server.state.requests == [('site/piece.bin', None)]


def test_fetch_reuses_a_finished_download_and_replaces_a_bad_one(server, tmp_path):
    data = _noise(3000)
    item = _serve(server, 'piece.bin', data)
    final = assemble.fetch(tmp_path, 'Piece', item)
    assert assemble.fetch(tmp_path, 'Piece', item) == final
    assert len(server.state.requests) == 1
    final.write_bytes(b'y' * 3000)                        # damaged on disk: fetched again
    assert assemble.fetch(tmp_path, 'Piece', item).read_bytes() == data
    assert len(server.state.requests) == 2


def test_fetch_cancel_mid_download_keeps_the_part_for_a_resume(server, tmp_path, monkeypatch):
    monkeypatch.setattr(assemble, 'CHUNK', 1024)
    data = _noise(8000)
    item = _serve(server, 'piece.bin', data)
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) >= 4                            # the loop top, two blocks, then Cancel
    with pytest.raises(assemble.Cancelled):
        assemble.fetch(tmp_path, 'Piece', item, cancelled=cancelled)
    final = assemble._download_path(tmp_path, item)
    part = final.with_name(final.name + '.part')
    assert not final.exists()
    assert part.stat().st_size == 2048
    assert assemble.fetch(tmp_path, 'Piece', item).read_bytes() == data
    assert server.state.requests[-1] == ('piece.bin', 'bytes=2048-')


def _expired():
    return urllib.error.URLError(ssl.SSLCertVerificationError(
        1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1032)'))


def test_fetch_retries_a_certificate_failure_on_roots_only(server, tmp_path, monkeypatch):
    # The 0.9.1 report: Windows' cached expired ISRG Root X2 cross-sign failed download.blender.org.
    data = _noise(3000)
    item = _serve(server, 'piece.bin', data)
    real, contexts = urllib.request.urlopen, []

    def urlopen(request, *, timeout, context=None):
        contexts.append(context)
        if context is None:
            raise _expired()
        return real(request, timeout=timeout)
    monkeypatch.setattr(assemble.urllib.request, 'urlopen', urlopen)
    final = assemble.fetch(tmp_path, 'Piece', item, sleep=lambda _s: pytest.fail('no wait before the switch'))
    assert final.read_bytes() == data
    assert len(contexts) == 2 and contexts[0] is None and isinstance(contexts[1], ssl.SSLContext)


def test_fetch_gives_up_on_a_lasting_certificate_failure_with_a_hint(tmp_path, monkeypatch):
    contexts = []

    def urlopen(_request, *, timeout, context=None):
        contexts.append(context)
        raise _expired()
    monkeypatch.setattr(assemble.urllib.request, 'urlopen', urlopen)
    item = {'url': 'https://download.blender.org/x.zip', 'sha256': '0' * 64, 'size': 10}
    with pytest.raises(assemble.Refused, match='date and time'):
        assemble.fetch(tmp_path, 'Blender', item, sleep=lambda _s: None)
    assert contexts[0] is None and len(contexts) == assemble.RETRIES + 1      # one switch, then the usual tries
    assert all(isinstance(context, ssl.SSLContext) for context in contexts[1:])


def test_roots_only_context_trusts_roots_and_no_cached_intermediates():
    context = assemble.roots_only_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    cas = context.get_ca_certs()
    assert cas, 'no roots loaded'
    assert all(ca['subject'] == ca['issuer'] for ca in cas), 'an intermediate got in as a trust anchor'


@pytest.mark.parametrize('url, allowed', [
    ('https://download.blender.org/x.zip', True),
    ('http://127.0.0.1:8000/x.zip', True),
    ('http://localhost/x.zip', True),
    ('http://mirror.test/x.zip', False),
    ('http://download.blender.org/x.zip', False),
    ('ftp://download.blender.org/x.zip', False),
    ('file:///C:/x.zip', False),
])
def test_check_url_takes_https_or_loopback_http(url, allowed):
    if allowed:
        assemble._check_url(url)
    else:
        with pytest.raises(assemble.Refused, match='not https'):
            assemble._check_url(url)


def test_check_url_takes_an_allowed_http_host(tmp_path):
    assemble._check_url('http://mirror.test/x.zip', allow_hosts=('mirror.test',))
    with pytest.raises(assemble.Refused):
        assemble.fetch(tmp_path, 'Plain', {'url': 'http://mirror.test/x.zip', 'sha256': '0' * 64, 'size': 1})
    assert not (tmp_path / assemble.DOWNLOADS).exists()   # refused before anything was made or asked for


# ------------------------------------------------------------------ disk space

def test_check_space_refuses_a_small_disk_and_counts_parts(tmp_path):
    item = {'url': 'https://example.org/b.zip', 'sha256': 'a' * 64, 'size': 1000}
    files = [('Blender', item, 'zip')]
    with pytest.raises(assemble.Refused, match='not enough free disk space'):
        assemble.check_space(tmp_path, files, free=1000)
    needed = assemble.check_space(tmp_path, files, free=BIG)
    assert needed == 1000 + int(1000 * assemble.ON_DISK['zip'] * assemble.PEAK) + assemble.MARGIN
    part = assemble._download_path(tmp_path, item)
    part.parent.mkdir(parents=True)
    part.with_name(part.name + '.part').write_bytes(b'x' * 400)
    assert assemble.remaining(tmp_path, files) == 600
    assert assemble.check_space(tmp_path, files, free=BIG) == needed - 400


def _measured_entry():
    """A platform entry (linux-x64's shape, no server) with what its install measured on disk."""
    entry = {'blender': {'version': '4.3.2', 'url': 'https://example.org/b.tar.xz', 'sha256': 'b' * 64,
                         'size': 368_852_356, 'format': 'tar.xz'},
             'python': {'version': '3.13.18', 'url': 'https://example.org/p.tar.gz', 'sha256': 'c' * 64,
                        'size': 35_596_130, 'format': 'tar.gz'},
             'wheels': [{'name': 'bpy', 'version': '5.2.2', 'url': 'https://example.org/bpy.whl', 'sha256': 'd' * 64,
                         'size': 401_697_653}]}
    entry['on_disk'] = {'blender': {'sha256': 'b' * 64, 'bytes': 1_206_851_569},
                        'runtime': {'key': assemble.runtime_key(entry), 'bytes': 1_113_277_867}}
    return entry


def test_the_estimate_is_each_pieces_measured_size_where_the_manifest_has_one():
    """0.9.0 build 3 Linux smoke: the card said about 2 GB (2,023,595,923 B, Blender's tar.xz at 2.6x) and
    2,320,129,436 B landed. A piece measured from these very downloads is that size."""
    entry = _measured_entry()
    assert assemble.measured(entry) == {'blender': 1_206_851_569, 'runtime': 1_113_277_867}
    assert assemble.estimate(assemble.files_for(entry)) == 2_320_129_436
    assert assemble.estimate(assemble.files_for(entry, runtime=False)) == 1_206_851_569
    assert assemble.estimate(assemble.files_for(entry, blender=False)) == 1_113_277_867
    assert assemble.estimate(assemble.files_for(entry, blender=False, runtime=False)) == 0
    assert assemble.runtime_key(entry) == assemble.runtime_key({k: v for k, v in entry.items() if k != 'on_disk'}), \
        'the measured sizes are no part of the runtime key: recording them downloads nothing again'


def test_a_piece_whose_downloads_moved_falls_back_to_the_ratio():
    entry = _measured_entry()
    entry['wheels'][0] = dict(entry['wheels'][0], version='5.2.3', sha256='e' * 64)     # a new runtime key
    assert assemble.measured(entry) == {'blender': 1_206_851_569}
    python, wheel = 35_596_130 * assemble.ON_DISK['tar.gz'], 401_697_653 * assemble.ON_DISK['whl']
    assert assemble.estimate(assemble.files_for(entry)) == int(1_206_851_569 + python + wheel)
    entry['blender'] = dict(entry['blender'], sha256='f' * 64)                          # a new Blender file
    assert assemble.measured(entry) == {}
    ratios = int(368_852_356 * assemble.ON_DISK['tar.xz'] + python + wheel)
    assert assemble.estimate(assemble.files_for(entry)) == ratios
    del entry['on_disk']
    assert assemble.measured(entry) == {}
    # a plain list of the same files (not files_for's Files) is estimated by ratio, as before
    assert assemble.estimate(list(assemble.files_for(_measured_entry()))) == ratios


def test_check_space_counts_a_measured_piece_at_its_size(tmp_path):
    entry = _measured_entry()
    files = assemble.files_for(entry, blender=False)
    needed = assemble.check_space(tmp_path, files, free=BIG)
    assert needed == 35_596_130 + 401_697_653 + int(1_113_277_867 * assemble.PEAK) + assemble.MARGIN


# ------------------------------------------------------------------ path-safe unpacking

@pytest.mark.parametrize('name', ['/abs.txt', '../evil.txt', 'a/../../evil.txt', 'C:/evil.txt', 'C:evil.txt',
                                  'a//b.txt'])
def test_unzip_refuses_unsafe_member_names(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    archive.write_bytes(_zip({'fine.txt': b'ok', name: b'bad'}))
    with pytest.raises(assemble.Refused, match='unsafe path'):
        assemble.unzip(archive, tmp_path / 'out')
    assert not (tmp_path / 'evil.txt').exists() and not (tmp_path / 'abs.txt').exists()


def test_unzip_refuses_a_symbolic_link(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as bundle:
        info = zipfile.ZipInfo('link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, '../../outside')
    archive = tmp_path / 'link.zip'
    archive.write_bytes(buffer.getvalue())
    with pytest.raises(assemble.Refused, match='symbolic link'):
        assemble.unzip(archive, tmp_path / 'out')
    assert not os.path.lexists(tmp_path / 'out' / 'link')


def test_unzip_writes_normal_members_and_maps_them(tmp_path):
    archive = tmp_path / 'ok.zip'
    archive.write_bytes(_zip({'top/': None, 'top/a.txt': b'a', 'top/sub/b.txt': b'b', 'top/empty/': None}))
    assert assemble.unzip(archive, tmp_path / 'plain') == 2
    assert (tmp_path / 'plain/top/sub/b.txt').read_bytes() == b'b'
    assert assemble.unzip(archive, tmp_path / 'lifted', mapper=assemble._strip('top')) == 2
    assert (tmp_path / 'lifted/a.txt').read_bytes() == b'a' and (tmp_path / 'lifted/empty').is_dir()
    stray = tmp_path / 'stray.zip'
    stray.write_bytes(_zip({'top/a.txt': b'a', 'other/x.txt': b'x'}))
    with pytest.raises(assemble.Refused, match='outside top/'):
        assemble.unzip(stray, tmp_path / 'stray', mapper=assemble._strip('top'))


def test_unzip_stops_on_cancel(tmp_path):
    archive = tmp_path / 'ok.zip'
    archive.write_bytes(_zip({'a.txt': b'a', 'b.txt': b'b'}))
    with pytest.raises(assemble.Cancelled):
        assemble.unzip(archive, tmp_path / 'out', cancelled=lambda: True)
    assert not (tmp_path / 'out' / 'a.txt').exists()


@pytest.mark.parametrize('members', [
    [('fine.txt', b'ok'), ('../evil.txt', b'bad')],
    [('fine.txt', b'ok'), ('link', ('symlink', '../../evil.txt'))],
    [('link', ('symlink', '/etc/passwd'))],
], ids=['dotdot', 'link-out', 'absolute-link'])
def test_untar_refuses_unsafe_entries(tmp_path, members):
    archive = tmp_path / 'bad.tar.gz'
    archive.write_bytes(_tar(members))
    with pytest.raises(assemble.Refused, match='unsafe entry'):
        assemble.untar(archive, tmp_path / 'out')
    assert not (tmp_path / 'evil.txt').exists()


def test_untar_writes_normal_members_and_refuses_a_broken_archive(tmp_path):
    archive = tmp_path / 'ok.tar.gz'
    archive.write_bytes(_tar([('python/bin/python3', b'elf'), ('python/lib/x.py', b'x')]))
    assert assemble.untar(archive, tmp_path / 'out') == 2
    assert (tmp_path / 'out/python/lib/x.py').read_bytes() == b'x'
    with pytest.raises(assemble.Cancelled):
        assemble.untar(archive, tmp_path / 'cancelled', cancelled=lambda: True)
    broken = tmp_path / 'broken.tar.gz'
    broken.write_bytes(archive.read_bytes()[:40])
    with pytest.raises(assemble.Refused, match='could not be unpacked'):
        assemble.untar(broken, tmp_path / 'broken')


def test_build_runtime_from_a_standalone_tar(tmp_path):
    """python-build-standalone's layout (Linux, macOS): one top folder lifted into place, no ._pth."""
    archive = tmp_path / 'cpython.tar.gz'
    archive.write_bytes(_tar([('python/bin/python3', b'elf'),
                              ('python/lib/python3.13/site-packages/README.txt', b'site')]))
    wheel = tmp_path / 'tiny.whl'
    wheel.write_bytes(_wheels()['tinypkg'])
    entry = {'python': {'version': '3.13.18', 'format': 'tar.gz', 'kind': 'standalone', 'root': 'python',
                        'entrypoint': 'bin/python3', 'site_packages': 'lib/python3.13/site-packages',
                        'wheel_verify': ['tinypkg/__init__.py']},
             'wheels': [{'name': 'tinypkg', 'version': '1.0'}]}
    stage = tmp_path / 'stage'
    assemble.build_runtime(stage, entry, {'python': archive, 'tinypkg': wheel})
    site = stage / 'lib/python3.13/site-packages'
    assert (stage / 'bin/python3').read_bytes() == b'elf'
    assert (site / 'tinypkg/__init__.py').exists() and (site / assemble.HOME_PTH).exists()
    assert not (tmp_path / 'stage.raw').exists()
    extra = tmp_path / 'extra.tar.gz'
    extra.write_bytes(_tar([('python/bin/python3', b'elf'), ('README', b'stray')]))
    with pytest.raises(assemble.Refused, match='expected to hold only python/'):
        assemble.build_runtime(tmp_path / 'stage2', entry, {'python': extra, 'tinypkg': wheel})


def test_home_line_is_one_import_line_that_adds_rigswap_home(monkeypatch):
    # site.py runs a .pth line only when it starts with "import"; everything must be on that one line
    assert assemble.HOME_LINE.startswith('import ') and assemble.HOME_LINE.count('\n') == 1
    path = ['stdlib']
    monkeypatch.setattr('sys.path', path)
    monkeypatch.setenv('RIGSWAP_HOME', 'C:/resources/utility/rigswap/app')
    exec(assemble.HOME_LINE, {})
    exec(assemble.HOME_LINE, {})
    assert path == ['C:/resources/utility/rigswap/app', 'stdlib']
    monkeypatch.delenv('RIGSWAP_HOME')
    exec(assemble.HOME_LINE, {})
    assert path == ['C:/resources/utility/rigswap/app', 'stdlib']


# ------------------------------------------------------------------ the whole install

def test_assemble_end_to_end(server, tmp_path, nothing_runs):
    entry = _entry(server)
    root = _root(tmp_path)
    steps, owned = [], []
    receipt = assemble.assemble(root, entry, platform='win-x64', free=BIG,
                                progress=lambda fraction, detail, **extra: steps.append((fraction, extra.get('phase'))),
                                own=lambda name, path: owned.append(('own', name)),
                                release=lambda name: owned.append(('release', name)))

    assert json.loads((root / assemble.RECEIPT).read_text(encoding='utf-8')) == receipt
    assert receipt['platform'] == 'win-x64'
    assert receipt['blender']['version'] == '4.3.2' and receipt['runtime']['key'] == assemble.runtime_key(entry)
    assert receipt['runtime']['wheels'] == ['tinypkg==1.0', 'purepkg==2.0']
    assert receipt['download_bytes'] == sum(f[1]['size'] for f in assemble.files_for(entry))
    assert receipt['bytes_on_disk'] > 0

    blender = assemble.blender_dir(root, entry)
    assert assemble.blender_exe(root, entry).read_bytes() == b'MZ fake blender 4.3.2'
    assert not (blender / 'blender.pdb').exists() and not (blender / '4.3/datafiles/locale').exists()
    assert not (blender / '4.3/python/bin').exists()
    assert (blender / '4.3/datafiles/studiolights/world.exr').exists()

    runtime = assemble.runtime_dir(root, entry)
    assert assemble.python_exe(root, entry).read_bytes() == b'MZ fake python'
    assert (runtime / 'python313._pth').read_text(encoding='utf-8') == \
        'python313.zip\n.\nLib\\site-packages\nimport site\n'
    site = runtime / 'Lib/site-packages'
    assert (site / assemble.HOME_PTH).read_text(encoding='utf-8') == assemble.HOME_LINE
    assert (site / 'tinypkg/__init__.py').exists() and (site / 'tinypkg-1.0.dist-info/METADATA').exists()
    assert (site / 'purepkg/__init__.py').read_bytes() == b'PURE = True\n'      # lifted out of .data/purelib
    assert (site / 'purepkg/_speed.pyd').exists()                               # and .data/platlib
    assert not (site / 'purepkg-2.0.data').exists() and not (site / 'tinypkg-1.0.data').exists()
    assert not list(site.glob('**/evil.py')) and not list(site.glob('**/tiny.h'))

    state = assemble.inspect(root, entry)
    assert (state['blender'], state['runtime'], state['other'], state['any']) == (True, True, [], True)
    assert state['receipt'] == receipt
    assert not (root / assemble.DOWNLOADS).exists()
    assert not list(root.glob('.staging-*')) and not list(root.glob('*/.old-*'))

    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions) and fractions[-1] == 0.98
    assert {'download', 'unpack', 'finish'} <= {phase for _, phase in steps}
    assert owned == [('own', 'staging-blender'), ('release', 'staging-blender'),
                     ('own', 'staging-runtime'), ('release', 'staging-runtime')]

    asked = len(server.state.requests)
    again = assemble.assemble(root, entry, platform='win-x64', free=BIG)
    assert len(server.state.requests) == asked                                  # nothing to download again
    assert again['download_bytes'] == 0


def test_cancel_during_unpack_leaves_nothing_half_made(server, tmp_path, nothing_runs):
    entry = _entry(server)
    root = _root(tmp_path)
    unpacking = []
    with pytest.raises(assemble.Cancelled):
        assemble.assemble(root, entry, free=BIG, cancelled=lambda: bool(unpacking),
                          progress=lambda _f, _d, **extra: extra.get('phase') == 'unpack' and unpacking.append(1))
    assert not assemble.blender_dir(root, entry).exists() and not assemble.runtime_dir(root, entry).exists()
    assert not list(root.glob('.staging-*')) and not list(root.glob('.staging-*.raw'))
    assert not (root / assemble.RECEIPT).exists()
    assert len(list((root / assemble.DOWNLOADS).iterdir())) == 4                # kept for the next try
    state = assemble.inspect(root, entry)
    assert (state['blender'], state['runtime'], state['any']) == (False, False, False)

    asked = len(server.state.requests)
    assemble.assemble(root, entry, free=BIG)
    assert len(server.state.requests) == asked                                  # the downloads were reused
    assert assemble.inspect(root, entry)['runtime']


def test_a_failed_piece_is_never_renamed_into_place(server, tmp_path, monkeypatch, nothing_runs):
    entry = _entry(server)
    root = _root(tmp_path)

    def broken(stage, *_args, **_kwargs):
        Path(stage, 'python.exe').parent.mkdir(parents=True, exist_ok=True)
        Path(stage, 'python.exe').write_bytes(b'half')
        raise RuntimeError('the disk filled up')
    real = assemble.build_runtime
    monkeypatch.setattr(assemble, 'build_runtime', broken)
    with pytest.raises(RuntimeError, match='disk filled up'):
        assemble.assemble(root, entry, free=BIG)
    assert assemble.blender_current(root, entry)                               # the finished piece stays
    assert not assemble.runtime_dir(root, entry).exists()
    assert not list(root.glob('.staging-*'))
    piece = (assemble.blender_dir(root, entry) / assemble.PIECE).read_text(encoding='utf-8')

    monkeypatch.setattr(assemble, 'build_runtime', real)
    assemble.assemble(root, entry, free=BIG)
    assert assemble.runtime_current(root, entry)
    assert (assemble.blender_dir(root, entry) / assemble.PIECE).read_text(encoding='utf-8') == piece


def test_a_blender_missing_a_needed_file_is_refused(server, tmp_path, nothing_runs):
    entry = _entry(server)
    entry['blender']['verify'] = [*entry['blender']['verify'], '4.3/scripts/addons_core/cycles/__init__.py']
    root = _root(tmp_path)
    with pytest.raises(assemble.Refused, match='missing files'):
        assemble.assemble(root, entry, free=BIG)
    assert not assemble.blender_dir(root, entry).exists() and not list(root.glob('.staging-*'))


def test_an_update_cleans_up_what_the_manifest_no_longer_names(server, tmp_path, nothing_runs):
    root = _root(tmp_path)
    old = _entry(server)
    assemble.assemble(root, old, free=BIG)
    new = _entry(server, version='4.3.3', tiny='1.1')
    assert assemble.runtime_key(new) != assemble.runtime_key(old)
    (root / '.staging-blender-dead').mkdir()                                     # a crashed earlier run
    (root / 'blender' / '.old-4.3.1-deadbeef').mkdir()
    (root / assemble.DOWNLOADS).mkdir()
    (root / assemble.DOWNLOADS / 'stale.zip.part').write_bytes(b'stale')
    (root.parent / '.model-import-removing-dead').mkdir()                        # a Remove that could not finish

    receipt = assemble.assemble(root, new, free=BIG)
    assert receipt['blender']['version'] == '4.3.3' and receipt['runtime']['wheels'][0] == 'tinypkg==1.1'
    assert not assemble.blender_dir(root, old).exists() and not assemble.runtime_dir(root, old).exists()
    assert assemble.inspect(root, new)['other'] == []
    assert sorted(p.name for p in (root / 'blender').iterdir()) == ['4.3.3']
    assert [p.name for p in (root / 'runtime').iterdir()] == [assemble.runtime_key(new)]
    assert not (root / assemble.DOWNLOADS).exists()
    assert not list(root.glob('.staging-*')) and not list(root.parent.glob('.model-import-removing-*'))
    site = assemble.runtime_dir(root, new) / 'Lib/site-packages'
    assert (site / 'tinypkg/__init__.py').read_text(encoding='utf-8') == "VERSION = '1.1'\n"


def test_an_update_of_only_the_wheels_keeps_blender(server, tmp_path, nothing_runs):
    root = _root(tmp_path)
    assemble.assemble(root, _entry(server), free=BIG)
    piece = (assemble.blender_dir(root, _entry(server)) / assemble.PIECE).read_text(encoding='utf-8')
    server.state.requests.clear()
    new = _entry(server, tiny='1.1')
    assemble.assemble(root, new, free=BIG)
    assert all(not name.startswith('blender') for name, _ in server.state.requests)
    assert (assemble.blender_dir(root, new) / assemble.PIECE).read_text(encoding='utf-8') == piece
    # The old runtime goes in the update's cleanup; a folder Windows will not rename at that moment (a virus scan of
    # the files just written, under a loaded test run) stays for the next one, as service.status runs it.
    if assemble.inspect(root, new)['other']:
        time.sleep(0.5)
        assemble.cleanup(root, new)
    assert assemble.inspect(root, new)['other'] == []


def test_remove_deletes_everything(server, tmp_path, nothing_runs):
    root = _root(tmp_path)
    entry = _entry(server)
    assemble.assemble(root, entry, free=BIG)
    assert assemble.remove(root) is True
    assert not root.exists() and not list(root.parent.glob('.model-import-removing-*'))
    assert assemble.remove(root) is False
    assert assemble.inspect(root, entry)['any'] is False
