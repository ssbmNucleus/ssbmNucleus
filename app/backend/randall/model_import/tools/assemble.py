"""Assemble the model import's tools on this computer from the official downloads (docs/dev/MODEL_IMPORT_TOOLS.md).

One platform entry of ``utility/model_import_tools.json`` (``blender``, ``python``, ``wheels``: each file by URL,
sha256 and size) becomes two folders under ``root`` (the user's ``<data>/tools/model-import``):

    blender/<version>/   Blender 4, unpacked and trimmed (rigswap's RIGSWAP_BLENDER4)
    runtime/<key>/       a CPython 3.13 with the wheels unpacked into its site-packages (rigswap's RIGSWAP_PYTHON)
    receipt.json         what is installed, written last

``key`` (``runtime_key``) is a hash of the python entry and the wheels list, so an app whose manifest changes
neither keeps its runtime; Blender is keyed by its version.

The rules, in order: free disk space is checked first (``check_space``); each file is downloaded into
``downloads/`` with HTTP Range resume (``fetch``: a Cancel or a dropped connection keeps the part) and its sha256
checked before anything is unpacked; archives are unpacked path-safe into a staging folder beside the target
(zip members checked one by one, tar with ``filter='data'``, a .dmg attached read-only with ``hdiutil`` and its
app copied out on macOS); wheels are unpacked straight into site-packages (``.data/purelib|platlib`` moved in, no
pip, nothing from the downloads is run); the trim list is applied and the paths that must survive are checked; then
the staging folder is renamed into place and ``receipt.json`` written. After that, the folders the manifest no
longer names are removed (``cleanup``).

Only the standard library: the app runs it in its job (``service.py``) and the dev tests and a real assembly run it
directly:

    python -m randall.model_import.tools.assemble --root <folder> [--platform win-x64]     (from app/backend)
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

try:                    # tar.xz (Blender for Linux); named here so a frozen build carries it
    import lzma  # noqa: F401
except ImportError:     # pragma: no cover - a Python built without it cannot unpack Linux Blender
    lzma = None

ASSEMBLY = 1            # this module's own layout of a runtime (the .pth below): part of the runtime key
CHUNK = 1 << 20
TIMEOUT = 60            # seconds a download may stall before it is retried from where it is
RETRIES = 5             # tries per file, each resuming where the last one stopped
RETRY_WAIT = 2.0
AGENT = 'SSBM-Nucleus'
DOWNLOADS = 'downloads'
RECEIPT = 'receipt.json'
PIECE = '.piece.json'   # inside each finished folder: what it was made from
MARGIN = 300 * 10**6    # bytes kept free beyond the estimate
# The size on disk before a download is a piece's measured size, from the manifest (``on_disk``: a real install's
# receipt.json, recorded by pin_model_import_tools.py --measured), for the very downloads it was measured from
# (``measured``). Only a piece with none falls back to these bytes on disk per downloaded byte, by format. They are
# rough: Linux Blender's tar.xz unpacks to 3.27x, not 2.6x (0.9.0 build 3: the card said about 2.0 GB, 2.32 GB landed).
ON_DISK = {'zip': 1.8, 'whl': 2.2, 'tar.gz': 3.0, 'tar.xz': 2.6, 'dmg': 3.0}
PEAK = 1.4              # the unpack before the trim, and the archives still beside it
# rigswap's package is not in the runtime: it ships in the installer (resources/utility/rigswap/app), and the app
# names it in RIGSWAP_HOME for every run. This .pth puts it on the path (the embeddable Python's ._pth would ignore
# PYTHONPATH and the current folder), so the runtime does not depend on where the app is installed.
HOME_PTH = 'nucleus_rigswap_home.pth'
HOME_LINE = ("import os, sys; _home = os.environ.get('RIGSWAP_HOME'); "
             "_home and _home not in sys.path and sys.path.insert(0, _home)\n")
LOOPBACK = frozenset({'127.0.0.1', 'localhost', '::1'})


class Refused(Exception):
    """The tools cannot be installed for a reason the user can read (a checksum, the disk, an unsafe archive)."""


class Cancelled(Exception):
    """The user pressed Cancel."""


# ------------------------------------------------------------------ where things go

def runtime_key(entry):
    """A short hash of the python entry and the wheels list (and this module's ``ASSEMBLY``)."""
    shape = {'assembly': ASSEMBLY, 'python': entry['python'],
             'wheels': sorted(entry['wheels'], key=lambda w: w['name'].lower())}
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def blender_dir(root, entry):
    return Path(root) / 'blender' / entry['blender']['version']


def runtime_dir(root, entry):
    return Path(root) / 'runtime' / runtime_key(entry)


def blender_exe(root, entry):
    return blender_dir(root, entry) / entry['blender']['entrypoint']


def python_exe(root, entry):
    return runtime_dir(root, entry) / entry['python']['entrypoint']


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path, value):
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def blender_current(root, entry):
    """Whether ``blender/<version>`` is the one the manifest pins, finished."""
    folder = blender_dir(root, entry)
    piece = _read_json(folder / PIECE) or {}
    return piece.get('sha256') == entry['blender']['sha256'] and (folder / entry['blender']['entrypoint']).exists()


def runtime_current(root, entry):
    folder = runtime_dir(root, entry)
    piece = _read_json(folder / PIECE) or {}
    return piece.get('key') == runtime_key(entry) and (folder / entry['python']['entrypoint']).exists()


def inspect(root, entry):
    """What is in ``root`` against ``entry``: {blender, runtime: current?, other: folders the manifest does not name,
    any: whether anything is installed at all, receipt}."""
    root = Path(root)
    named = {blender_dir(root, entry), runtime_dir(root, entry)}
    other = [p for kind in ('blender', 'runtime') if (root / kind).is_dir()
             for p in sorted((root / kind).iterdir()) if p.is_dir() and p not in named]
    blender, runtime = blender_current(root, entry), runtime_current(root, entry)
    return {'blender': blender, 'runtime': runtime, 'other': other,
            'any': blender or runtime or bool(other), 'receipt': _read_json(root / RECEIPT)}


# ------------------------------------------------------------------ what a download needs

class Files(list):
    """``files_for``'s [(label, file entry, format)], plus what ``estimate`` needs: ``pieces``, the piece each file
    is part of ('blender' or 'runtime'), and ``measured``, {piece: bytes on disk} for those of its pieces the manifest
    measured (``measured``). A plain list of the same tuples estimates every file by ``ON_DISK``."""

    def __init__(self, files=(), pieces=(), measured=None):
        super().__init__(files)
        self.pieces = list(pieces)
        self.measured = dict(measured or {})


def files_for(entry, *, blender=True, runtime=True):
    """[(label, file entry, format)] to download for the pieces asked for (a ``Files``)."""
    files, pieces = [], []
    if blender:
        files.append((f"Blender {entry['blender']['version']}", entry['blender'], entry['blender']['format']))
        pieces.append('blender')
    if runtime:
        files.append((f"Python {entry['python']['version']}", entry['python'], entry['python']['format']))
        files += [(f"{w['name']} {w['version']}", w, 'whl') for w in entry['wheels']]
        pieces += ['runtime'] * (1 + len(entry['wheels']))
    known = measured(entry)
    return Files(files, pieces, {piece: known[piece] for piece in dict.fromkeys(pieces) if piece in known})


def measured(entry):
    """{piece: bytes on disk} the manifest's ``on_disk`` gives for ``entry``'s pieces, each only for the downloads it
    was measured from: Blender's by its sha256, the runtime's by its key (the same Python and wheels). A piece whose
    pin moved since has none, and is estimated by ``ON_DISK`` until a new install is measured."""
    on_disk = entry.get('on_disk') or {}
    blender, runtime = on_disk.get('blender') or {}, on_disk.get('runtime') or {}
    found = {}
    if blender.get('sha256') == entry['blender']['sha256'] and isinstance(blender.get('bytes'), int):
        found['blender'] = blender['bytes']
    if runtime.get('key') == runtime_key(entry) and isinstance(runtime.get('bytes'), int):
        found['runtime'] = runtime['bytes']
    return found


def _file_name(item):
    """The file's own name, as its URL ends (and as a browser saves it)."""
    return re.sub(r'[^A-Za-z0-9._+-]', '_', PurePosixPath(urllib.parse.urlparse(item['url']).path).name) or 'file'


def _download_path(root, item):
    return Path(root) / DOWNLOADS / f"{item['sha256'][:16]}-{_file_name(item)}"


def _have(root, item):
    """Bytes of ``item`` already on disk (a finished download or its part)."""
    final = _download_path(root, item)
    if final.is_file():
        return final.stat().st_size
    part = final.with_name(final.name + '.part')
    return min(part.stat().st_size, int(item['size'])) if part.is_file() else 0


def estimate(files):
    """Bytes on disk once ``files`` are unpacked: each piece's measured size where ``files`` carries one
    (``files_for``), else ``ON_DISK``'s ratio for each of its files."""
    sizes = getattr(files, 'measured', {})
    pieces = getattr(files, 'pieces', ())
    total = sum(sizes.values())
    for at, (_, item, fmt) in enumerate(files):
        if not (at < len(pieces) and pieces[at] in sizes):
            total += int(item['size']) * ON_DISK.get(fmt, 3.0)
    return int(total)


def remaining(root, files):
    return sum(max(0, int(item['size']) - _have(root, item)) for _, item, _ in files)


def _free(path):
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free


def check_space(root, files, *, free=None):
    """Refused when the disk under ``root`` has too little room for what is left to download and the unpack."""
    needed = remaining(root, files) + int(estimate(files) * PEAK) + MARGIN
    free = _free(root) if free is None else free
    if free < needed:
        raise Refused(f'There is not enough free disk space for the model import tools: they need about '
                      f'{_gb(needed)} and {_gb(free)} is free on the drive that holds {Path(root)}.')
    return needed


def _gb(value):
    return f'{value / 1e9:.1f} GB' if value >= 1e9 else f'{value / 1e6:.0f} MB'


# ------------------------------------------------------------------ downloads

def _check_url(url, allow_hosts=()):
    parts = urllib.parse.urlparse(url)
    if parts.scheme == 'https' or (parts.scheme == 'http' and parts.hostname in (LOOPBACK | set(allow_hosts))):
        return
    raise Refused(f'The manifest names a download that is not https: {url}')


def sha256_of(path, cancelled=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            if cancelled is not None and cancelled():
                raise Cancelled()
            digest.update(block)
    return digest.hexdigest()


SERVER_AUTH = '1.3.6.1.5.5.7.3.1'


def roots_only_context():
    """A TLS context that trusts root certificates only: certifi's bundle (when this Python has it) plus, on
    Windows, the system's trusted roots.

    Python's default context on Windows also loads Windows' intermediate store, where Windows keeps old
    intermediates it has seen, and OpenSSL takes a cached expired one over the valid one the server sends. On
    2026-11-21 download.blender.org moved to Let's Encrypt's YE1 -> Root YE -> ISRG Root X2 -> X1 chain, and a PC
    that still had the X2-by-X1 cross-sign that expired 2025-09-15 failed with "certificate has expired". Every file
    is checked against its pinned sha256, so which roots vouch for the host never decides what gets installed."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)      # checks the chain and the host name, as the default does
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    if sys.platform == 'win32':
        roots = b''.join(cert for cert, encoding, trust in ssl.enum_certificates('ROOT')
                         if encoding == 'x509_asn' and (trust is True or SERVER_AUTH in trust))
        if roots:
            context.load_verify_locations(cadata=roots)
    else:
        context.set_default_verify_paths()
    return context


def _certificate_failure(error):
    return isinstance(getattr(error, 'reason', error), ssl.SSLCertVerificationError)


BLOCKED = frozenset({401, 403, 451})    # this host turns this computer away (a Cloudflare challenge is a 403)
GONE = frozenset({404, 410})


def _host(url):
    return urllib.parse.urlparse(url).hostname


def _turned_down(label, item, final, refused):
    """The Refused for a file every source turned down; ``refused`` is [(host, HTTP code)], one per source."""
    told = '; '.join(f'{host}: HTTP {code}' for host, code in refused)
    if all(code in GONE for _, code in refused):
        return Refused(f'{label} is no longer at {item["url"]} ({told}). This app version needs an update of its '
                       'tools list.')
    return Refused(f'{label} could not be downloaded: the download site and its mirrors turned this computer away '
                   f'({told}). A VPN or proxy usually causes this; turn it off and press Download again. Or open '
                   f'{item["url"]} in a web browser, put the downloaded {_file_name(item)} in {final.parent} and '
                   'press Download again: the app checks the file and uses it.')


def fetch(root, label, item, *, on_bytes=None, cancelled=None, allow_hosts=(), sleep=time.sleep):
    """``item`` (url, sha256, size, optional mirrors) into ``root/downloads``, resuming a part left by an earlier
    try; refused (and the part deleted) when its sha256 is not the pinned one. When a source turns the download
    down (``BLOCKED`` or ``GONE``) the next of ``mirrors`` carries on from the same part. A certificate failure
    switches, once, to ``roots_only_context``. The file saved by hand under its own name in ``downloads/`` (a
    browser download) is taken when its sha256 is the pinned one. -> the finished file."""
    sources = [item['url'], *(item.get('mirrors') or ())]
    for url in sources:
        _check_url(url, allow_hosts)
    size, final = int(item['size']), _download_path(root, item)
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + '.part')
    if final.is_file():
        if final.stat().st_size == size and sha256_of(final, cancelled) == item['sha256']:
            return final
        final.unlink()
    by_hand = final.with_name(_file_name(item))
    if by_hand.is_file() and by_hand.stat().st_size == size and sha256_of(by_hand, cancelled) == item['sha256']:
        os.replace(by_hand, final)
        return final
    report = on_bytes or (lambda _bytes: None)
    have = part.stat().st_size if part.is_file() else 0
    if have > size:
        part.unlink()
        report(-have)
        have = 0
    # ``best``: the furthest any try got. Only beating it earns fresh tries: a file shorter than its pin otherwise
    # cycles forever (download it all, 416 on the rest, start over, ...).
    tries, last, best = 0, None, have
    context = None                                  # Python's default, until a certificate failure
    source, refused = 0, []                         # refused: (host, HTTP code) of each source that turned it down
    while have < size:
        if cancelled is not None and cancelled():
            raise Cancelled()
        url = sources[source]
        if tries >= RETRIES:
            hint = (" If it is about a certificate, check that this computer's date and time are right; an "
                    'antivirus or proxy that inspects secure connections can cause it too.'
                    if 'CERTIFICATE' in str(last).upper() else '')
            raise Refused(f'{label} could not be downloaded from {_host(url)}: {last}. Check the connection and '
                          f'press Download again; it carries on where it stopped.{hint}')
        tries += 1
        headers = {'User-Agent': AGENT, 'Accept-Encoding': 'identity'}
        if have:
            headers['Range'] = f'bytes={have}-'
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=TIMEOUT, context=context) as response:
                if have:
                    start = re.match(r'bytes (\d+)-', response.headers.get('Content-Range') or '')
                    if response.status != 206 or not start or int(start.group(1)) != have:
                        report(-have)               # not the rest of the file: start it over
                        have = 0
                with part.open('ab' if have else 'wb') as out:
                    while have <= size:
                        if cancelled is not None and cancelled():
                            raise Cancelled()
                        block = response.read(CHUNK)
                        if not block:
                            break
                        out.write(block)
                        have += len(block)
                        report(len(block))
            last = 'the connection closed early'
        except urllib.error.HTTPError as error:
            last = f'HTTP {error.code}'
            if error.code == 416 and have == size:
                break
            if error.code == 416:                   # the part is not a start of this file
                part.unlink(missing_ok=True)
                report(-have)
                have = 0
            elif error.code in BLOCKED | GONE:      # not this host: the next source carries on from the part
                refused.append((_host(url), error.code))
                source += 1
                if source == len(sources):
                    raise _turned_down(label, item, final, refused) from error
                tries, best = 0, have
                continue
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            last = f'{type(error).__name__}: {error}'
            if context is None and _certificate_failure(error):
                context = roots_only_context()      # nothing was read: go again at once, on a fresh try
                tries -= 1
                continue
        if have > size:
            break
        if have > best:
            best, tries = have, 0                   # it got further than ever: the next stall gets fresh tries
        elif have < size:
            sleep(RETRY_WAIT)
    if have != size:
        part.unlink(missing_ok=True)
        report(-have)
        raise Refused(f'{label} came down as {have} bytes, but {size} are pinned. Nothing was installed; press '
                      'Download to try again.')
    digest = sha256_of(part, cancelled)
    if digest != item['sha256']:
        part.unlink(missing_ok=True)
        report(-have)
        raise Refused(f'{label} did not match its pinned checksum, so it was not installed (sha256 {digest}, '
                      f'expected {item["sha256"]}). Press Download to try again.')
    os.replace(part, final)
    return final


# ------------------------------------------------------------------ unpacking, path-safe

def _inside(base, target):
    base, target = os.path.realpath(base), os.path.realpath(target)
    return target == base or target.startswith(base.rstrip(os.sep) + os.sep)


def _member(name, archive):
    """A zip member's name as a safe relative POSIX path, else Refused."""
    clean = name.replace('\\', '/')
    path = PurePosixPath(clean)
    if (clean.startswith('/') or re.match(r'^[A-Za-z]:', clean) or '..' in path.parts
            or any(part in ('', '.') for part in clean.rstrip('/').split('/')[1:])):
        raise Refused(f'{Path(archive).name} holds an unsafe path ({name!r}); it was not unpacked.')
    return clean


def unzip(archive, dest, *, mapper=None, cancelled=None):
    """Unpack the zip ``archive`` into ``dest``. ``mapper(name)`` -> the member's path under ``dest``, or None to
    leave it out. Absolute paths, ``..``, drive letters and symbolic links are refused. -> files written."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if cancelled is not None and cancelled():
                raise Cancelled()
            name = _member(info.filename, archive)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise Refused(f'{Path(archive).name} holds a symbolic link ({info.filename!r}); it was not '
                              'unpacked.')
            relative = mapper(name) if mapper else name
            if not relative:
                continue
            out = dest / relative
            if not _inside(dest, out):
                raise Refused(f'{Path(archive).name} holds an unsafe path ({info.filename!r}); it was not unpacked.')
            if name.endswith('/'):
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, out.open('wb') as target:
                shutil.copyfileobj(source, target, CHUNK)
            if mode & 0o111:
                out.chmod(out.stat().st_mode | 0o111)
            written += 1
    return written


def _strip(root):
    """A mapper that keeps only what lives under ``root/`` and drops that prefix (no root: everything as is)."""
    prefix = root.strip('/') + '/' if root else ''

    def mapper(name):
        if not prefix:
            return name
        if not name.startswith(prefix):
            if name.rstrip('/') == prefix.rstrip('/'):
                return None
            raise Refused(f'the archive holds {name!r}, outside {prefix}')
        return name[len(prefix):] or None
    return mapper


def untar(archive, dest, *, cancelled=None):
    """Unpack the tar ``archive`` into ``dest`` with the 'data' filter (no absolute paths, no links out, no device
    files, no setuid bits), member by member so a Cancel stops it."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with tarfile.open(archive, 'r:*') as bundle:
            for member in bundle:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                bundle.extract(member, dest, filter='data')
                count += 1
    except tarfile.FilterError as error:
        raise Refused(f'{Path(archive).name} holds an unsafe entry ({error}); it was not unpacked.') from error
    except (tarfile.TarError, EOFError, OSError) as error:
        if isinstance(error, (PermissionError,)):
            raise
        raise Refused(f'{Path(archive).name} could not be unpacked: {error}') from error
    return count


def undmg(archive, dest, item, *, own=None, release=None, run=subprocess.run):
    """Copy ``item`` (Blender.app) out of the disk image ``archive`` into ``dest/item``: attached read-only and
    unbrowsed with hdiutil, copied with ditto (links and signatures kept), always detached. macOS only."""
    if sys.platform != 'darwin':
        raise Refused('A .dmg can only be opened on macOS.')
    mount = Path(dest).parent / f'.mount-{uuid.uuid4().hex[:8]}'
    mount.mkdir(parents=True)
    attached = run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', str(mount),
                    str(archive)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
    if attached.returncode:
        mount.rmdir()
        raise Refused(f'The Blender disk image could not be opened: {(attached.stderr or attached.stdout).strip()}')
    if own:
        own('mount', str(mount))
    try:
        source = mount / item
        if not source.is_dir():
            raise Refused(f'The Blender disk image holds no {item}.')
        Path(dest).mkdir(parents=True, exist_ok=True)
        copied = run(['ditto', str(source), str(Path(dest) / item)], capture_output=True, text=True, timeout=1800)
        if copied.returncode:
            raise Refused(f'{item} could not be copied out of its disk image: {copied.stderr.strip()}')
    finally:
        detach(mount, run=run)
        if release:
            release('mount')


def detach(mount, *, run=subprocess.run):
    """Detach the disk image at ``mount`` (forced when it will not go), and remove the empty mount point."""
    for force in ([], ['-force']):
        done = run(['hdiutil', 'detach', str(mount), *force], capture_output=True, text=True, timeout=300)
        if done.returncode == 0:
            break
    try:
        Path(mount).rmdir()
    except OSError:
        pass


def trim(tree, paths, *, log=None):
    """Delete each of ``paths`` (files or folders, relative to ``tree``) that is there. -> bytes removed."""
    removed = 0
    for relative in paths or ():
        victim = Path(tree) / relative
        if not _inside(tree, victim) or victim == Path(tree):
            raise Refused(f'The trim list names a path outside the unpack: {relative}')
        if victim.is_dir() and not victim.is_symlink():
            removed += measure(victim)
            shutil.rmtree(victim)
        elif victim.exists() or victim.is_symlink():
            removed += victim.lstat().st_size
            victim.unlink()
        elif log:
            log(f'trim: {relative} is not in this build')
    return removed


def measure(root):
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


def _verify(tree, paths, what):
    missing = [p for p in paths if not os.path.lexists(Path(tree) / p)]
    if missing:
        raise Refused(f'{what} is missing files the import needs after unpacking ({", ".join(missing[:4])}).')


# ------------------------------------------------------------------ the two pieces

def _wheel_mapper(name):
    """A wheel member's place in site-packages: ``<dist>.data/purelib|platlib/x`` -> ``x``; the wheel's scripts,
    headers and data files are left out (rigswap runs none of them)."""
    first, _, rest = name.partition('/')
    if first.endswith('.data'):
        kind, _, inner = rest.partition('/')
        return inner or None if kind in ('purelib', 'platlib') else None
    return name


def build_blender(stage, item, archive, *, cancelled=None, own=None, release=None, log=None):
    """Blender unpacked into ``stage`` (the folder that becomes ``blender/<version>``), trimmed and checked."""
    stage = Path(stage)
    fmt = item['format']
    if fmt == 'zip':
        unzip(archive, stage, mapper=_strip(item.get('root') or ''), cancelled=cancelled)
    elif fmt in ('tar.xz', 'tar.gz'):
        raw = stage.parent / f'{stage.name}.raw'
        untar(archive, raw, cancelled=cancelled)
        _lift(raw, item.get('root') or '', stage)
    elif fmt == 'dmg':
        undmg(archive, stage, item['root'], own=own, release=release)
    else:
        raise Refused(f"The tools list names a Blender format this app cannot unpack: {fmt}")
    trim(stage, item.get('trim'), log=log)
    _verify(stage, [item['entrypoint'], *(item.get('verify') or ())], f"Blender {item['version']}")
    _executable(stage / item['entrypoint'])


def _lift(raw, root, stage):
    """Move ``raw/root`` (an archive's one top folder) to ``stage``; anything else in the archive is refused."""
    raw = Path(raw)
    names = [p.name for p in raw.iterdir()]
    if root:
        if names != [root] or not (raw / root).is_dir():
            raise Refused(f'The archive was expected to hold only {root}/, not {sorted(names)[:4]}.')
        os.replace(raw / root, stage)
        raw.rmdir()
    else:
        os.replace(raw, stage)


def _executable(path):
    if os.name != 'nt' and Path(path).is_file():
        Path(path).chmod(Path(path).stat().st_mode | 0o755)


def _embeddable_pth(stage):
    """The embeddable CPython's ``python3XY._pth`` rewritten: its stdlib zip, its own folder, site-packages, and
    ``import site`` (so the .pth files in site-packages run)."""
    found = sorted(Path(stage).glob('python3*._pth'))
    if not found:
        raise Refused('The embeddable Python has no ._pth file.')
    pth = found[0]
    pth.write_text('\n'.join([pth.stem + '.zip', '.', r'Lib\site-packages', 'import site']) + '\n', encoding='utf-8')


def build_runtime(stage, entry, archives, *, cancelled=None, log=None):
    """The CPython and its wheels into ``stage`` (the folder that becomes ``runtime/<key>``), checked."""
    stage = Path(stage)
    python = entry['python']
    fmt = python['format']
    if fmt == 'zip':
        unzip(archives['python'], stage, mapper=_strip(python.get('root') or ''), cancelled=cancelled)
    elif fmt in ('tar.gz', 'tar.xz'):
        raw = stage.parent / f'{stage.name}.raw'
        untar(archives['python'], raw, cancelled=cancelled)
        _lift(raw, python.get('root') or '', stage)
    else:
        raise Refused(f'The tools list names a Python format this app cannot unpack: {fmt}')
    if python.get('kind') == 'embeddable':
        _embeddable_pth(stage)
    _verify(stage, [python['entrypoint'], *(python.get('verify') or ())], f"Python {python['version']}")
    _executable(stage / python['entrypoint'])
    site = stage / python['site_packages']
    site.mkdir(parents=True, exist_ok=True)
    for wheel in entry['wheels']:
        unzip(archives[wheel['name']], site, mapper=_wheel_mapper, cancelled=cancelled)
    (site / HOME_PTH).write_text(HOME_LINE, encoding='utf-8')
    _verify(site, python.get('wheel_verify') or (), 'The Python packages')


def _swap(stage, final):
    """``stage`` renamed to ``final`` (an older folder there is moved aside first, then deleted)."""
    final = Path(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    old = None
    if final.exists():
        old = final.with_name(f'.old-{final.name}-{uuid.uuid4().hex[:8]}')
        try:
            os.replace(final, old)
        except OSError as error:
            raise Refused(f'{final} is in use (a model import may be running), so it was not replaced. Try '
                          'again when no import is running.') from error
    os.replace(stage, final)
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


# ------------------------------------------------------------------ the whole install

class _Meter:
    """Bytes downloaded across every file, as one fraction of the download phase."""

    def __init__(self, total, done, progress, start=0.0, span=0.8):
        self.total, self.done, self.progress, self.start, self.span = max(1, total), done, progress, start, span
        self.label = ''
        self._last = 0.0

    def add(self, count):
        self.done = max(0, self.done + count)
        now = time.monotonic()
        if self.progress and (now - self._last >= 0.25 or self.done >= self.total):
            self._last = now
            self.progress(self.start + self.span * min(1.0, self.done / self.total),
                          f'Downloading {self.label} ({self.done / 1e6:.0f} of {self.total / 1e6:.0f} MB)',
                          phase='download', done_bytes=self.done, total_bytes=self.total)


def assemble(root, entry, *, platform=None, progress=None, cancelled=None, own=None, release=None,
             allow_hosts=(), log=None, free=None):
    """Install what ``entry`` (one platform of the manifest) pins and is not installed yet under ``root``; clean up
    what it no longer names. -> the receipt. Raises Refused (in words for the user) or Cancelled; nothing half-made
    is ever renamed into place. ``own(name, path)``/``release(name)``: the caller's record of what to clean up if the
    process dies (the staging folders, a mounted disk image)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    say = progress or (lambda *_a, **_k: None)
    need_blender, need_runtime = not blender_current(root, entry), not runtime_current(root, entry)
    files = files_for(entry, blender=need_blender, runtime=need_runtime)
    downloaded = 0
    if files:
        check_space(root, files, free=free)
        total = sum(int(item['size']) for _, item, _ in files)
        meter = _Meter(total, sum(_have(root, item) for _, item, _ in files), say)
        archives = {}
        for label, item, fmt in files:
            meter.label = label
            meter.add(0)
            archives[item.get('name') or ('blender' if item is entry['blender'] else 'python')] = fetch(
                root, label, item, on_bytes=meter.add, cancelled=cancelled, allow_hosts=allow_hosts)
        downloaded = total
        if need_blender:
            say(0.82, f"Unpacking Blender {entry['blender']['version']}", phase='unpack')
            _build(root, 'blender', blender_dir(root, entry),
                   lambda stage: build_blender(stage, entry['blender'], archives['blender'], cancelled=cancelled,
                                               own=own, release=release, log=log),
                   {'piece': 'blender', 'version': entry['blender']['version'], 'sha256': entry['blender']['sha256'],
                    'url': entry['blender']['url']}, own=own, release=release)
        if need_runtime:
            say(0.92, f"Unpacking Python {entry['python']['version']} and its packages", phase='unpack')
            _build(root, 'runtime', runtime_dir(root, entry),
                   lambda stage: build_runtime(stage, entry, archives, cancelled=cancelled, log=log),
                   {'piece': 'runtime', 'key': runtime_key(entry), 'python': entry['python']['version'],
                    'wheels': [f"{w['name']}=={w['version']}" for w in entry['wheels']]}, own=own, release=release)
    say(0.98, 'Finishing', phase='finish')
    receipt = write_receipt(root, entry, platform=platform, seconds=time.monotonic() - started,
                            downloaded=downloaded)
    cleanup(root, entry)
    return receipt


def _build(root, kind, final, make, piece, *, own=None, release=None):
    stage = Path(root) / f'.staging-{kind}-{uuid.uuid4().hex[:8]}'
    if own:
        own(f'staging-{kind}', str(stage))
    try:
        make(stage)
        piece = dict(piece, bytes_on_disk=measure(stage), made_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        _write_json(stage / PIECE, piece)
        _swap(stage, final)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(stage.parent / f'{stage.name}.raw', ignore_errors=True)
        if release:
            release(f'staging-{kind}')


def write_receipt(root, entry, *, platform=None, seconds=None, downloaded=0):
    root = Path(root)
    blender, runtime = _read_json(blender_dir(root, entry) / PIECE) or {}, _read_json(runtime_dir(root, entry) / PIECE) or {}
    receipt = {
        'schema': 1, 'platform': platform, 'made_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'blender': {'version': entry['blender']['version'], 'sha256': entry['blender']['sha256'],
                    'path': blender_dir(root, entry).relative_to(root).as_posix(),
                    'entrypoint': entry['blender']['entrypoint'], 'bytes_on_disk': blender.get('bytes_on_disk')},
        'runtime': {'key': runtime_key(entry), 'python': entry['python']['version'],
                    'path': runtime_dir(root, entry).relative_to(root).as_posix(),
                    'entrypoint': entry['python']['entrypoint'],
                    'wheels': [f"{w['name']}=={w['version']}" for w in entry['wheels']],
                    'bytes_on_disk': runtime.get('bytes_on_disk')},
        'download_bytes': downloaded,
        'bytes_on_disk': (blender.get('bytes_on_disk') or 0) + (runtime.get('bytes_on_disk') or 0),
    }
    if seconds is not None:
        receipt['seconds'] = round(seconds, 1)
    _write_json(root / RECEIPT, receipt)
    return receipt


def cleanup(root, entry):
    """Remove what the manifest no longer names: older Blender and runtime folders, staging leftovers and the
    downloads. A folder in use (a running import on Windows) stays and goes at the next cleanup. -> removed paths."""
    root = Path(root)
    removed = []
    for path in inspect(root, entry)['other'] + sorted(root.glob('.staging-*')):
        aside = path
        if not path.name.startswith('.old-'):
            aside = path.with_name(f'.old-{path.name.lstrip(".")}-{uuid.uuid4().hex[:8]}')
            try:
                os.replace(path, aside)         # refused while a running import holds a file in it
            except OSError:
                continue
        shutil.rmtree(aside, ignore_errors=True)
        if not aside.exists():
            removed.append(path)
    shutil.rmtree(root / DOWNLOADS, ignore_errors=True)
    for leftover in root.parent.glob(f'.{root.name}-removing-*'):       # a Remove that could not finish deleting
        shutil.rmtree(leftover, ignore_errors=True)
    return removed


def remove(root):
    """Remove every installed tool under ``root``: renamed aside first (refused while a running import holds it),
    then deleted."""
    root = Path(root)
    if not root.exists():
        return False
    aside = root.with_name(f'.{root.name}-removing-{uuid.uuid4().hex[:8]}')
    try:
        os.replace(root, aside)
    except OSError as error:
        raise Refused('The model import tools are in use (a model import may be running). Try again when it has '
                      'finished.') from error
    shutil.rmtree(aside, ignore_errors=True)
    return True


# ------------------------------------------------------------------ a real assembly from a checkout

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, required=True, help='where to install (a scratch folder)')
    parser.add_argument('--platform', default=None, help='a platform key of the manifest (default: this one)')
    parser.add_argument('--manifest', type=Path, default=None)
    args = parser.parse_args(argv)
    from . import service
    manifest = service.load_manifest(args.manifest) if args.manifest else service.load_manifest()
    platform = args.platform or service.platform_key()
    entry = manifest['platforms'][platform]
    started = time.monotonic()

    def progress(fraction, detail, **_extra):
        print(f'{fraction * 100:5.1f}%  {detail}', flush=True)
    receipt = assemble(args.root, entry, platform=platform, progress=progress, log=print)
    print(json.dumps(receipt, indent=2))
    print(f'{time.monotonic() - started:.0f} s; python {python_exe(args.root, entry)}; '
          f'blender {blender_exe(args.root, entry)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
