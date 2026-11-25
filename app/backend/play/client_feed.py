"""
The Nucleus game client's release feed: where Play learns which client to install, and every
check a download passes before anything in it runs.

The feed is one signed JSON file, ``CLIENT_FEED_URL``. It is signed exactly as the app's own
update feed is (electron/updates/updater.js, tools/build/release_to_r2.py): Ed25519 with the
app's update key over the canonical JSON of the feed without its ``signature`` (keys sorted,
no spaces, UTF-8), and the signature is ``{"algorithm": "ed25519", "value": <base64>}``. The
public key is the one in electron/updates/update-public-key.pem (``PRODUCTION_PUBLIC_KEY_PEM``
is that file, and tests/backend/test_play_client_feed.py fails when the two differ).

The feed (format 1; docs/dev/PLAY_CLIENT_FEED.md has it in prose)::

    {
      "schema": "nucleus-client-feed",
      "format": 1,
      "version": "0.1.0",                   the client's own version (melee_source.exe --print-info)
      "minAppVersion": "0.10.0",             the oldest SSBM Nucleus that may install it
      "commit": "81447d35...",              optional: the client's git commit, shown only
      "notes": "...",                       optional, shown only
      "pub_date": "2026-11-25T08:00:00Z",   optional, shown only
      "platforms": {
        "windows-x86_64": {
          "url": "https://releases.ssbmnucleus.net/client/windows/<name>.zip",
          "size": 123456789,                the ZIP's exact length
          "sha256": "<64 hex>",              the ZIP's SHA-256
          "manifest": {                     the packager's sidecar (<name>.manifest.json)
            "url": "https://releases.ssbmnucleus.net/client/windows/<name>.manifest.json",
            "size": 45678,
            "sha256": "<64 hex>"
          }
        }
      },
      "signature": {"algorithm": "ed25519", "value": "<base64 of 64 bytes>"}
    }

The sidecar is what the client's windows-build/client_release.py writes beside the ZIP: format 1,
kind ``nucleus-client`` (nothing else, the older ``melee-unlocked-source-port-client`` included),
``name`` ``NucleusClient-<version>-win64``, the version, commit and build facts (its ``print_info``
is the packaged program's own --print-info answer), every file's path, size and SHA-256, and
``zip``: the ZIP's own name (``<name>.zip``), size and SHA-256. The feed pins it by length and
hash, so the per-file list is as trusted as the feed. The ZIP holds exactly one folder, ``<name>/``,
with every listed file and ``<name>/release-manifest.json`` (the sidecar without ``zip``).

Trust: every URL is HTTPS on releases.ssbmnucleus.net under /client/windows/, redirects
included. A development backend (never a frozen one) can be pointed at a local stand-in with
``NUCLEUS_CLIENT_FEED_URL=http://127.0.0.1:<port>/...``, and only then does it take
``NUCLEUS_CLIENT_FEED_PUBLIC_KEY`` (a PEM file) as the key, and only URLs on that same
address and port (``source``). A packaged build reads neither variable.
"""

import base64
import hashlib
import json
import logging
import os
import queue
import re
import sys
import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from play import ed25519

logger = logging.getLogger(__name__)

#: The one place the client feed lives (production).
CLIENT_FEED_URL = 'https://releases.ssbmnucleus.net/client/windows/latest.json'
RELEASES_HOST = 'releases.ssbmnucleus.net'
CLIENT_PATH_PREFIX = '/client/windows/'
PLATFORM_KEY = 'windows-x86_64'

FEED_SCHEMA = 'nucleus-client-feed'
FEED_FORMAT = 1
MANIFEST_FORMAT = 1
MANIFEST_KIND = 'nucleus-client'
#: The packager's folder name, also the stem of the ZIP and its sidecar (client_release.py NAME).
PACKAGE_NAME = 'NucleusClient-{version}-win64'
INNER_MANIFEST = 'release-manifest.json'

#: electron/updates/update-public-key.pem, the app's update key (the test keeps them equal).
PRODUCTION_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA1y57FuWugafPgwVZ4poKBZYQCpkcq3Y9Gv3hYM8nPYA=
-----END PUBLIC KEY-----"""

#: Development only (never read by a frozen build): a local stand-in feed and its throwaway key.
TEST_FEED_ENV = 'NUCLEUS_CLIENT_FEED_URL'
TEST_KEY_ENV = 'NUCLEUS_CLIENT_FEED_PUBLIC_KEY'
LOOPBACK = '127.0.0.1'

MAX_FEED_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ZIP_BYTES = 4 * 1024 * 1024 * 1024
MAX_FILES = 50_000
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_PATH_CHARS = 200
MAX_NOTES = 20_000

_VERSION = re.compile(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_COMMIT = re.compile(r'[0-9a-f]{7,64}')
_BASE64 = re.compile(r'[A-Za-z0-9+/]+={0,2}')
_RESERVED = re.compile(r'(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?', re.IGNORECASE)
_BAD_CHARS = set('<>:"|?*\\') | {chr(c) for c in range(32)} | {'\x7f'}


class FeedError(Exception):
    """Why a feed, a manifest or a download cannot be used, in plain words."""


# --------------------------------------------------------------------------- versions

def parse_version(text):
    """(major, minor, patch) of a plain X.Y.Z version, or None."""
    if not isinstance(text, str):
        return None
    match = _VERSION.fullmatch(text)
    return tuple(int(part) for part in match.groups()) if match else None


def app_version_tuple(text):
    """(major, minor, patch) of an app version, prerelease tag ignored ('0.9.2-play-preview.1'), or None."""
    if not isinstance(text, str):
        return None
    match = _VERSION.match(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


# --------------------------------------------------------------------------- where, and whose key

@dataclass(frozen=True)
class Source:
    """Where the feed is read and the key it must be signed with."""
    feed_url: str
    public_key: bytes
    scheme: str
    host: str
    port: int
    path_prefix: str
    test: bool = False


def production_source() -> Source:
    return Source(CLIENT_FEED_URL, ed25519.public_key_from_pem(PRODUCTION_PUBLIC_KEY_PEM),
                  'https', RELEASES_HOST, 443, CLIENT_PATH_PREFIX, False)


def _frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def source(env=None) -> Source:
    """The production feed, unless this is a development backend whose TEST_FEED_ENV names a feed on
    127.0.0.1 and whose TEST_KEY_ENV names a readable Ed25519 key: then that stand-in and its key, and
    nothing else. A frozen (packaged) backend never reads either variable."""
    if _frozen():
        return production_source()
    env = os.environ if env is None else env
    url = (env.get(TEST_FEED_ENV) or '').strip()
    key_path = (env.get(TEST_KEY_ENV) or '').strip()
    if not url and not key_path:
        return production_source()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        parts, port = None, None
    if (parts is None or parts.scheme != 'http' or parts.hostname != LOOPBACK or not port
            or parts.username or parts.password or parts.fragment):
        logger.warning('Play: %s is not a feed on http://%s:<port>; the real client feed is used', TEST_FEED_ENV,
                       LOOPBACK)
        return production_source()
    try:
        key = ed25519.public_key_from_pem(Path(key_path).read_text(encoding='ascii'))
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning('Play: %s is not a readable Ed25519 public key; the real client feed is used', TEST_KEY_ENV)
        return production_source()
    if url not in _warned:
        _warned.add(url)
        logger.warning('Play: the client feed is the local stand-in %s, signed with a test key', url)
    return Source(url, key, 'http', LOOPBACK, port, '/', True)


_warned = set()


def checked_url(url, src: Source, *, suffix=None) -> str:
    """`url` when it is on the trusted origin of `src` (HTTPS on releases.ssbmnucleus.net under
    /client/windows/, or the stand-in's own address and port), else FeedError."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise FeedError('The client feed names a download address Nucleus does not trust.')
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == 'https' else 80 if parts.scheme == 'http' else None)
    except ValueError:
        raise FeedError('The client feed names a download address Nucleus does not trust.')
    path = parts.path
    trusted = (parts.scheme == src.scheme and (parts.hostname or '').lower() == src.host and port == src.port
               and not parts.username and not parts.password and not parts.fragment
               and path.startswith(src.path_prefix) and '\\' not in path and '%' not in path
               and '..' not in path.split('/'))
    if not trusted:
        raise FeedError('The client feed names a download address Nucleus does not trust.')
    if suffix and not path.lower().endswith(suffix):
        raise FeedError('The client feed names a download of the wrong kind.')
    return url


# --------------------------------------------------------------------------- the signed form

def canonical_bytes(value) -> bytes:
    """The bytes the signature covers: tools/build/release_to_r2.py canonical_manifest_bytes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f'duplicate key {key!r}')
        out[key] = value
    return out


def _no_float(text):
    raise ValueError(f'number {text!r} is not a whole number')


def strict_json(data: bytes, *, floats=False):
    """JSON as the signer wrote it: UTF-8, no duplicate keys, no NaN or Infinity, and whole numbers only
    unless `floats` (the sidecar: pinned by the signed feed, and its print_info is whatever the packaged
    program answered, so a fractional number there must not refuse the release)."""
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_no_duplicates,
                          parse_float=None if floats else _no_float, parse_constant=_no_float)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise FeedError('The client feed is not valid JSON.')


def verify_signed(raw, public_key: bytes) -> dict:
    """The feed without its signature, once the signature checks out with `public_key`. FeedError otherwise."""
    if not isinstance(raw, dict):
        raise FeedError('The client feed is not a feed.')
    signature = raw.get('signature')
    if (not isinstance(signature, dict) or signature.get('algorithm') != 'ed25519'
            or not isinstance(signature.get('value'), str) or not _BASE64.fullmatch(signature['value'])):
        raise FeedError('The client feed is not signed.')
    try:
        value = base64.b64decode(signature['value'], validate=True)
    except ValueError:
        raise FeedError('The client feed is not signed.')
    unsigned = {key: item for key, item in raw.items() if key != 'signature'}
    if len(value) != ed25519.SIGNATURE_BYTES or not ed25519.verify(public_key, canonical_bytes(unsigned), value):
        raise FeedError('The client feed is not signed by Nucleus. Nothing was downloaded.')
    return unsigned


# --------------------------------------------------------------------------- the feed

@dataclass(frozen=True)
class Offer:
    version: str
    min_app_version: str
    url: str
    size: int
    sha256: str
    manifest_url: str
    manifest_size: int
    manifest_sha256: str
    commit: str = None
    notes: str = ''
    pub_date: str = None

    def public(self, app_version=None) -> dict:
        """What the Play page is told about it."""
        have = app_version_tuple(app_version)
        need = parse_version(self.min_app_version)
        return {'version': self.version, 'size': self.size, 'notes': self.notes, 'pubDate': self.pub_date,
                'minAppVersion': self.min_app_version,
                'appTooOld': bool(have and need and have < need)}


def _size(value, limit):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= limit else None


def parse_feed(unsigned: dict, src: Source) -> Offer:
    """The offer in a feed whose signature verify_signed checked. FeedError for anything off-schema."""
    def bad(why):
        return FeedError(f'The client feed cannot be used: {why}.')
    if unsigned.get('schema') != FEED_SCHEMA or unsigned.get('format') != FEED_FORMAT:
        raise bad('it is not a format 1 Nucleus Unlocked feed')
    version = unsigned.get('version')
    if parse_version(version) is None:
        raise bad('its version is not X.Y.Z')
    min_app = unsigned.get('minAppVersion')
    if parse_version(min_app) is None:
        raise bad('its minimum app version is not X.Y.Z')
    platform = (unsigned.get('platforms') or {}).get(PLATFORM_KEY) if isinstance(unsigned.get('platforms'), dict) \
        else None
    if not isinstance(platform, dict):
        raise bad('it has no Windows client')
    size = _size(platform.get('size'), MAX_ZIP_BYTES)
    sha = platform.get('sha256')
    manifest = platform.get('manifest')
    if size is None or not isinstance(sha, str) or not _SHA256.fullmatch(sha):
        raise bad('the download has no size or SHA-256')
    if not isinstance(manifest, dict):
        raise bad('it does not name the file list')
    manifest_size = _size(manifest.get('size'), MAX_MANIFEST_BYTES)
    manifest_sha = manifest.get('sha256')
    if manifest_size is None or not isinstance(manifest_sha, str) or not _SHA256.fullmatch(manifest_sha):
        raise bad('the file list has no size or SHA-256')
    url = checked_url(platform.get('url'), src, suffix='.zip')
    manifest_url = checked_url(manifest.get('url'), src, suffix='.json')
    commit = unsigned.get('commit')
    notes = unsigned.get('notes')
    pub_date = unsigned.get('pub_date')
    return Offer(version=version, min_app_version=min_app, url=url, size=size, sha256=sha,
                 manifest_url=manifest_url, manifest_size=manifest_size, manifest_sha256=manifest_sha,
                 commit=commit if isinstance(commit, str) and _COMMIT.fullmatch(commit) else None,
                 notes=notes[:MAX_NOTES] if isinstance(notes, str) else '',
                 pub_date=pub_date[:64] if isinstance(pub_date, str) else None)


def read_feed(data: bytes, src: Source) -> Offer:
    """The offer in the feed bytes `data`: parsed strictly, signature checked, schema checked."""
    if len(data) > MAX_FEED_BYTES:
        raise FeedError('The client feed is too large.')
    return parse_feed(verify_signed(strict_json(data), src.public_key), src)


# --------------------------------------------------------------------------- the file list

def safe_member_path(path) -> bool:
    """A path a client file may have: relative, forward slashes, every part a plain Windows file name
    (no '.', '..', drive, device name, trailing dot or space, or character Windows refuses)."""
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS or path != path.strip():
        return False
    if unicodedata.normalize('NFC', path) != path or any(ch in _BAD_CHARS for ch in path):
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute() or path.startswith('/') or path.endswith('/') or '//' in path:
        return False
    for part in path.split('/'):
        if part in ('', '.', '..') or part.endswith(('.', ' ')) or _RESERVED.fullmatch(part):
            return False
    return True


def _basename(url) -> str:
    return urlsplit(url).path.rsplit('/', 1)[-1]


@dataclass(frozen=True)
class FileList:
    name: str                 # the ZIP's top folder
    version: str
    files: dict               # path -> (size, sha256)
    total: int
    commit: str = None
    inner: dict = None        # the sidecar without 'zip': what release-manifest.json in the ZIP must say

    def folded(self):
        return {path.casefold() for path in self.files}


def read_manifest(data: bytes, offer: Offer) -> FileList:
    """The sidecar's file list, once its bytes are the ones the feed pinned (size and SHA-256 checked by the
    caller) and it describes the offer's version and ZIP. FeedError otherwise."""
    def bad(why):
        return FeedError(f"The client's file list cannot be used: {why}.")
    try:
        raw = strict_json(data, floats=True)
    except FeedError:
        raise bad('it is not valid JSON')
    if not isinstance(raw, dict) or raw.get('format') != MANIFEST_FORMAT or raw.get('kind') != MANIFEST_KIND:
        raise bad(f'it is not a format {MANIFEST_FORMAT} {MANIFEST_KIND} manifest')
    if raw.get('version') != offer.version:
        raise bad(f"it is for version {raw.get('version')!r}, the feed offers {offer.version}")
    name = PACKAGE_NAME.format(version=offer.version)
    if raw.get('name') != name:
        raise bad(f'it names its folder {str(raw.get("name"))[:80]!r}, not {name!r}')
    zip_facts = raw.get('zip')
    if (not isinstance(zip_facts, dict) or zip_facts.get('name') != f'{name}.zip'
            or zip_facts.get('size') != offer.size or zip_facts.get('sha256') != offer.sha256):
        raise bad('it describes a different download')
    if (_basename(offer.url) != f'{name}.zip' or _basename(offer.manifest_url) != f'{name}.manifest.json'):
        raise bad(f'the feed does not name the files {name}.zip and {name}.manifest.json')
    entries = raw.get('files')
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise bad('it lists no files')
    files, folded, total = {}, set(), 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise bad('a file entry is not one')
        path, size, sha = entry.get('path'), entry.get('size'), entry.get('sha256')
        if not safe_member_path(path) or path == INNER_MANIFEST:
            raise bad(f'it lists a file path Nucleus refuses ({str(path)[:80]!r})')
        if path.casefold() in folded:
            raise bad(f'it lists {path!r} twice')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_ZIP_BYTES * 2:
            raise bad(f'{path!r} has no size')
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise bad(f'{path!r} has no SHA-256')
        files[path] = (size, sha)
        folded.add(path.casefold())
        total += size
    if total > MAX_TOTAL_BYTES:
        raise bad('the client is larger than Nucleus installs')
    for required in ('melee_source.exe', 'melee_game.dll'):
        if required not in files:
            raise bad(f'it has no {required}')
    inner = {key: value for key, value in raw.items() if key != 'zip'}
    commit = raw.get('git_commit')
    return FileList(name=name, version=raw['version'], files=files, total=total, inner=inner,
                    commit=commit if isinstance(commit, str) and _COMMIT.fullmatch(commit) else None)


def check_bytes(data: bytes, size: int, sha256: str, what: str):
    if len(data) != size:
        raise FeedError(f'The {what} is not the size the client feed names. Nothing was installed.')
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FeedError(f'The {what} is not the one the client feed names (its SHA-256 differs). '
                        'Nothing was installed.')


# --------------------------------------------------------------------------- unpacking

_CHUNK = 1024 * 1024


def _inside(folder: Path, target: Path) -> bool:
    base = os.path.normcase(os.path.realpath(folder))
    path = os.path.normcase(os.path.realpath(target))
    return os.path.commonpath([base, path]) == base and path != base


def extract(zip_path: Path, dest: Path, files: FileList, *, should_stop=lambda: False, progress=None):
    """Unpack the downloaded client into the empty folder `dest`, checking as it goes.

    Every entry must sit in the one folder the file list names, have a path ``safe_member_path``
    allows, be a plain file (not a link, not encrypted) and be listed with exactly its size; it is
    written by streaming, never more bytes than listed, and its SHA-256 is compared as it is written.
    release-manifest.json must be there and say what the sidecar says. A file the list does not name,
    one named twice, or one the list names that the ZIP lacks fails the whole unpack (FeedError). `should_stop`
    is asked between chunks (a Cancel); `progress(done_bytes, total_bytes)` is told as it goes."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise FeedError('The folder Nucleus unpacks into is not empty.')
    prefix = files.name + '/'
    seen, written = set(), 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile):
        raise FeedError('The download is not a ZIP file. Nothing was installed.')
    with archive:
        infos = archive.infolist()
        if len(infos) > 2 * len(files.files) + 1000:
            raise FeedError('The download holds far more entries than the client has. Nothing was installed.')
        for info in infos:
            if should_stop():
                return None
            name = info.filename
            if info.flag_bits & 0x1:
                raise FeedError('The download holds an encrypted file. Nothing was installed.')
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000, 0o040000):
                raise FeedError(f'The download holds a link or special file ({name[:80]!r}). Nothing was installed.')
            if name == prefix:
                continue
            if not name.startswith(prefix):
                raise FeedError(f'The download holds {name[:80]!r} outside its folder. Nothing was installed.')
            rel = name[len(prefix):]
            if info.is_dir():
                folder = rel.rstrip('/')
                if not safe_member_path(folder):
                    raise FeedError(f'The download holds a folder path Nucleus refuses ({name[:80]!r}). '
                                    'Nothing was installed.')
                continue
            if not safe_member_path(rel):
                raise FeedError(f'The download holds a file path Nucleus refuses ({name[:80]!r}). '
                                'Nothing was installed.')
            key = rel.casefold()
            if key in seen:
                raise FeedError(f'The download holds {rel!r} twice. Nothing was installed.')
            seen.add(key)
            if rel == INNER_MANIFEST:
                if info.file_size > MAX_MANIFEST_BYTES:
                    raise FeedError('The release manifest inside the download is too large. Nothing was installed.')
                with archive.open(info) as stream:
                    inner = stream.read(MAX_MANIFEST_BYTES + 1)
                try:
                    said = strict_json(inner, floats=True)
                except FeedError:
                    raise FeedError('The release manifest inside the download is not valid. Nothing was installed.')
                if said != files.inner:
                    raise FeedError('The release manifest inside the download differs from the file list. '
                                    'Nothing was installed.')
                target = dest / rel
                with open(target, 'xb') as out:
                    out.write(inner)
                continue
            expected = files.files.get(rel)
            if expected is None:
                raise FeedError(f'The download holds {rel!r}, which its file list does not name. '
                                'Nothing was installed.')
            size, sha = expected
            if info.file_size != size:
                raise FeedError(f'{rel!r} in the download is not the size its file list names. Nothing was installed.')
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not _inside(dest, target.parent / '_') or not _inside(dest, target):
                raise FeedError(f'{rel!r} would be written outside the client folder. Nothing was installed.')
            digest, count = hashlib.sha256(), 0
            with archive.open(info) as stream, open(target, 'xb') as out:
                while True:
                    if should_stop():
                        return None
                    chunk = stream.read(_CHUNK)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > size:
                        raise FeedError(f'{rel!r} in the download is larger than its file list says. '
                                        'Nothing was installed.')
                    digest.update(chunk)
                    out.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, files.total)
            if count != size or digest.hexdigest() != sha:
                raise FeedError(f'{rel!r} in the download is not the file its file list names. Nothing was installed.')
    if INNER_MANIFEST.casefold() not in seen:
        raise FeedError(f'The download has no {INNER_MANIFEST} in its folder. Nothing was installed.')
    missing = sorted(path for path in files.files if path.casefold() not in seen)
    if missing:
        raise FeedError(f'The download lacks {len(missing)} file(s) its file list names, such as {missing[0]!r}. '
                        'Nothing was installed.')
    return written


# --------------------------------------------------------------------------- the network

_STOP_POLL = 0.25          # seconds between looks at a Cancel while the download waits for the server
_AHEAD = 8                 # chunks the reader may hold before the writer takes them
_END = object()


class _BodyReader(threading.Thread):
    """Reads a reply's body on its own thread into a short queue, so the download notices a Cancel
    within _STOP_POLL even while the server sends nothing (a read blocked on a stalled connection
    cannot be woken from another thread on Windows). Once abandoned it reads no further: it ends when
    its blocked read returns (data, or the read timeout) and closes the reply itself. It never touches
    the file: the download closes that at once and its caller removes it."""

    def __init__(self, chunks):
        super().__init__(name='client-download-reader', daemon=True)
        self.chunks, self.reply = chunks, None
        self.items = queue.Queue(maxsize=_AHEAD)
        self.abandoned = threading.Event()

    def run(self):
        last = _END
        try:
            for chunk in self.chunks:
                if not self._hand(chunk):
                    return
        except BaseException as e:  # noqa: BLE001 - handed to the download, which raises it
            last = e
        finally:
            if self.reply is not None:           # closed before the end is handed over
                try:
                    self.reply.close()
                except Exception:  # noqa: BLE001 - closing a dead connection
                    pass
        self._hand(last)

    def _hand(self, item):
        while not self.abandoned.is_set():
            try:
                self.items.put(item, timeout=_STOP_POLL)
                return True
            except queue.Full:
                continue
        return False

    def next(self, should_stop):
        """The next chunk, _END, or the exception the read raised; None once `should_stop` says so."""
        while not should_stop():
            try:
                return self.items.get(timeout=_STOP_POLL)
            except queue.Empty:
                continue
        return None


class Fetcher:
    """HTTP GETs that stay on the trusted origin: redirects are followed by hand (three at most), each one
    checked like the first address. `session` is a requests.Session (tests hand in a stand-in)."""

    TIMEOUT = (15, 60)

    def __init__(self, src: Source, session=None):
        self.src = src
        if session is None:
            import requests
            session = requests.Session()
            if src.test:
                session.trust_env = False        # a proxy must not see the loopback stand-in
        self.session = session

    def _open(self, url, *, suffix):
        target = checked_url(url, self.src, suffix=suffix)
        for _ in range(4):
            try:
                reply = self.session.get(target, stream=True, allow_redirects=False, timeout=self.TIMEOUT,
                                         headers={'Cache-Control': 'no-cache'})
            except Exception as e:  # noqa: BLE001 - requests' errors, said plainly
                raise FeedError('Nucleus could not reach the download server. Check your internet connection '
                                f'and try again. ({type(e).__name__})')
            if reply.status_code in (301, 302, 303, 307, 308) and reply.headers.get('Location'):
                from urllib.parse import urljoin
                location = urljoin(target, reply.headers['Location'])
                reply.close()
                target = checked_url(location, self.src, suffix=suffix)
                continue
            if reply.status_code != 200:
                reply.close()
                raise FeedError(f'The download server answered HTTP {reply.status_code}. Try again later.')
            return reply
        raise FeedError('The download server redirected too many times.')

    @staticmethod
    def _chunks(reply, size):
        """The body of `reply` in chunks of `size`. A connection that drops or stalls partway (requests'
        ChunkedEncodingError, ConnectionError, a read timeout) is a FeedError that says to try again."""
        body = reply.iter_content(size)
        while True:
            try:
                chunk = next(body)
            except StopIteration:
                return
            except Exception as e:  # noqa: BLE001 - requests' errors, said plainly
                raise FeedError('The download was interrupted: the connection to the download server dropped. '
                                f'Try again. ({type(e).__name__})') from e
            yield chunk

    def get_bytes(self, url, *, limit, suffix=None) -> bytes:
        """The body of `url`, at most `limit` bytes (FeedError beyond)."""
        reply = self._open(url, suffix=suffix)
        try:
            data = bytearray()
            for chunk in self._chunks(reply, 64 * 1024):
                data += chunk
                if len(data) > limit:
                    raise FeedError('The download server sent more than the client feed allows.')
            return bytes(data)
        finally:
            reply.close()

    def download(self, url, path: Path, *, size, sha256, should_stop=lambda: False, progress=None, suffix=None):
        """Stream `url` into the new file `path`: never more than `size` bytes, its SHA-256 compared at the
        end. Returns False when `should_stop` said so, within _STOP_POLL even while the server sends
        nothing (the body is read on a _BodyReader thread; the partial file is closed and left for the
        caller). FeedError when the length or hash is not the feed's."""
        reply = self._open(url, suffix=suffix)
        reader = None
        try:
            declared = reply.headers.get('Content-Length')
            if declared is not None and declared.isdigit() and int(declared) != size:
                raise FeedError('The download is not the size the client feed names. Nothing was installed.')
            digest, count = hashlib.sha256(), 0
            with open(path, 'xb') as out:
                reader = _BodyReader(self._chunks(reply, _CHUNK))
                reader.reply = reply             # from here on the reader closes it, on its own thread
                reader.start()
                while True:
                    chunk = reader.next(should_stop)
                    if chunk is None:
                        return False
                    if chunk is _END:
                        break
                    if isinstance(chunk, BaseException):
                        raise chunk
                    count += len(chunk)
                    if count > size:
                        raise FeedError('The download is larger than the client feed says. Nothing was installed.')
                    digest.update(chunk)
                    out.write(chunk)
                    if progress:
                        progress(count, size)
            if count != size:
                raise FeedError(f'The download stopped early ({count} of {size} bytes). Try again.')
            if digest.hexdigest() != sha256:
                raise FeedError('The download is not the one the client feed names (its SHA-256 differs). '
                                'Nothing was installed.')
            return True
        finally:
            if reader is None:
                reply.close()
            else:
                reader.abandoned.set()           # it stops at its next chunk or read timeout


def fetch_offer(fetcher: Fetcher) -> Offer:
    """The signed, checked offer of the feed `fetcher` reads."""
    import time
    url = fetcher.src.feed_url
    sep = '&' if '?' in url else '?'
    data = fetcher.get_bytes(f'{url}{sep}t={int(time.time())}', limit=MAX_FEED_BYTES)   # past any cache
    return read_feed(data, fetcher.src)


def fetch_file_list(fetcher: Fetcher, offer: Offer) -> FileList:
    data = fetcher.get_bytes(offer.manifest_url, limit=offer.manifest_size, suffix='.json')
    check_bytes(data, offer.manifest_size, offer.manifest_sha256, 'file list')
    return read_manifest(data, offer)
