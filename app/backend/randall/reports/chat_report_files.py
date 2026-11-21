"""Files for "Report this chat": what the user attached, and what the model import made.

A report that said "it couldn't find the textures in the zip" arrived with the
transcript only. The zip was not in it, so the failure could not be reproduced.
This module finds, for one mods conversation:

* **attachments** -- every file the user attached (the `context.files` of their
  messages), plus source files the model tools were handed that are the user's
  own (a model unpacked from an attached ZIP, a source attached elsewhere);
* **review images** -- the PNG previews the `model_*` tools made (pose pages,
  placement, renders, review sheets);
* **records** -- per model candidate touched: the candidate record (fit, review
  and export receipts), the fit sidecar (`<rigged>.fit.json`), the fit's own
  `assistant-result.json` and `fit.log`, and the alignment record.

and plans them into the report ZIP under one compressed budget: records first,
then review images, then attachments smallest first. Whatever does not fit is
listed instead (name, size, sha256 and, for an archive, up to 200 member names).

Never collected:

* anything outside `storage/assistant/{files,models}` -- every allowed root and
  every file is resolved and must lie inside the RESOLVED storage root, so a
  junction or symlink at a root or a file contributes nothing;
* any file whose origin marks it as a vanilla game file or a vault item
  (Randall's `open_vanilla_file`/`open_vault_file` copies, and draft DAT exports,
  which are built on the vanilla costume);
* any file byte-identical to a game file this app extracted from the user's ISO
  (`VANILLA_ASSETS_DIR`) or built from it (the model lab rig kits), whatever its
  name or extension -- matched by size, then sha256;
* a ZIP with such a file inside it, or a disc image inside it: the whole ZIP is
  left out ("contains game files from your ISO"), never repacked;
* disc images by extension.

If the reference game files are not on this machine the byte check has nothing
to compare against and passes; the origin and extension checks still apply.

Text records are scrubbed with the report scrubber, and absolute drive paths in
them are cut to `<path>/<file name>`. Binary files and the user's own
attachments are sent exactly as they are: each is hashed as it is written, and a
file whose bytes changed since it was screened aborts the build
(`FilesChanged`) rather than send unscreened bytes.
"""
import hashlib
import io
import json
import re
import zipfile
import zlib
from pathlib import Path

from core import config
from core.hashing import sha256_file

#: The whole report ZIP stays under this (the worker's cap is 64 MB).
FILES_BUDGET = 45 * 1024 * 1024
#: One text record, before scrubbing. A bigger one is listed, not sent.
RECORD_MAX = 4 * 1024 * 1024
#: One review image. They are small; a big one is listed, not sent.
IMAGE_MAX = 4 * 1024 * 1024
MAX_CANDIDATES = 40
MAX_IMAGES = 80
#: A too-large archive is listed by at most this many member names, each cut to NAME_MAX.
LISTING_MAX = 200
NAME_MAX = 200
#: A nested archive is screened in memory up to this size; a bigger one cannot
#: be screened, so its outer archive is left out.
NESTED_MAX = 64 * 1024 * 1024
#: Already compressed: stored, never deflated again.
STORED = frozenset(('.png', '.zip', '.jpg', '.jpeg', '.webp', '.glb'))
#: Disc images are never sent, whatever else is true of them.
DISC_IMAGES = frozenset(('.iso', '.gcm', '.ciso', '.rvz', '.wbfs', '.wia', '.gcz', '.nkit', '.dol'))
GAME_FILES_INSIDE = 'contains game files from your ISO'
GAME_FILE = 'a game file from your ISO'
DISC_IMAGE = 'a game disc image'
FROM_VAULT = 'from your vault'
OUTSIDE = "outside the app's own folder"
UNREADABLE = 'could not be read'
# Per member: local header (30) + central directory (46) + the name twice,
# plus a data descriptor and slack.
_MEMBER_OVERHEAD = 30 + 46 + 16 + 64
_ID = re.compile(r'^[a-f0-9]{32}$')
_FILE_KEYS = ('file_id', 'source_file_id', 'archive_file_id', 'alternates_sheet_file_id')
_CANDIDATE_KEYS = ('candidate_id', 'parent_candidate_id', 'child_candidate_id', 'revised_candidate_id')
#: An absolute drive path's folders: `C:\Users\Alice\proj\` (any separator run).
_DRIVE_DIRS = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:(?:\\+|/)(?:[^\\/\r\n\t"\'<>|*?:]+(?:\\+|/))+')
#: A UNC path's server, share and folders: `\\nas\Users\Alice\secret\`.
_UNC_DIRS = re.compile(r'(?<![^\s"\'(=,\[{])\\{2,}(?:[^\\/\r\n\t"\'<>|*?:]+(?:\\+|/))+')
#: A POSIX absolute path's folders: `/mnt/team/Alice/private/`, `//server/share/`,
#: `~/models/`. Not a URL (`https://host/a/`: every slash there follows ':',
#: '/' or a name character).
_POSIX_DIRS = re.compile(r'(?:(?<![\w.:/\\~-])/{1,2}|(?<![\w.:/\\-])~/)(?:[^/\\\r\n\t"\'<>|*?:]+/)+')

_packed_cache = {}
_sha_cache = {}


class FilesChanged(RuntimeError):
    """A file's bytes changed between screening and writing."""


# ---------------------------------------------------------------------------
# where files may come from
# ---------------------------------------------------------------------------

def _resolve(path):
    """Path.resolve, in one place (tests stand in for a junction here)."""
    return Path(path).resolve()


def _storage_root():
    return _resolve(config.STORAGE_PATH)


def _allowed_root(*parts):
    """A storage sub-root, resolved; None when it resolves outside the resolved
    storage root (a junction or symlink): such a root contributes nothing."""
    storage = _storage_root()
    root = _resolve(Path(config.STORAGE_PATH).joinpath(*parts))
    return root if root.is_relative_to(storage) else None


def _files_root():
    return _allowed_root('assistant', 'files')


def _models_root():
    return _allowed_root('assistant', 'models')


def _inside(path, root):
    """True when `path` resolves inside the (already resolved) `root` AND the
    resolved storage root."""
    if root is None:
        return False
    try:
        target = _resolve(path)
        return target.is_relative_to(root) and target.is_relative_to(_storage_root())
    except (OSError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# finding ids in a conversation
# ---------------------------------------------------------------------------

def _decoded(value):
    """Tool arguments/results may be JSON text."""
    if isinstance(value, str) and value.lstrip()[:1] in ('{', '['):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _walk(value, keys, found, depth=0):
    """Every 32-hex value under one of `keys`, in order, anywhere in `value`."""
    if depth > 12:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and _ID.match(item):
                found.append(item)
            elif key in keys and isinstance(item, list):
                found.extend(v for v in item if isinstance(v, str) and _ID.match(v))
            else:
                _walk(item, keys, found, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _walk(item, keys, found, depth + 1)


def references(chat):
    """(attached file ids, file ids the model tools used or made, candidate ids,
    alignment ids) -- each ordered, without repeats."""
    attached, used, candidates, alignments = [], [], [], []
    for message in chat.get('messages') or []:
        if not isinstance(message, dict):
            continue
        if message.get('role') == 'user':
            context = message.get('context')
            files = context.get('files') if isinstance(context, dict) else None
            for item in files if isinstance(files, list) else []:
                file_id = item.get('file_id') if isinstance(item, dict) else item
                if isinstance(file_id, str) and _ID.match(file_id):
                    attached.append(file_id)
            continue
        tools = message.get('tools')
        for tool in tools if isinstance(tools, list) else []:
            if not isinstance(tool, dict) or not str(tool.get('name') or '').startswith('model_'):
                continue
            for part in (_decoded(tool.get('arguments')), _decoded(tool.get('result'))):
                _walk(part, _FILE_KEYS, used)
                _walk(part, _CANDIDATE_KEYS, candidates)
                _walk(part, ('alignment_id',), alignments)
    unique = lambda items: list(dict.fromkeys(items))
    return unique(attached), unique(used), unique(candidates), unique(alignments)


# ---------------------------------------------------------------------------
# game files: what this app extracted from the user's ISO or built from it
# ---------------------------------------------------------------------------

def _sha256_file(path):
    """sha256 of a file, remembered while its size and mtime are unchanged. Used
    to SCREEN and to plan; what is sent is hashed again as it is written."""
    stat = Path(path).stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _sha_cache:
        _sha_cache[key] = sha256_file(path)
    return _sha_cache[key]


def _sha256_stream(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


#: How long one scan of the reference folders is trusted (the extracted assets
#: change only when the user re-extracts them).
GAME_FILES_TTL = 600
_game_files_cache = {}


class GameFiles:
    """Every file under the vanilla assets and the rig kits, indexed by size.

    A candidate is hashed only when its size equals one of theirs. Each size
    bucket is hashed once into a set, so a candidate or archive member costs
    one hash and one set lookup however many reference files share its size.
    One scan is shared by every review for `GAME_FILES_TTL` seconds.
    """

    def __init__(self, roots=None):
        self.by_size = {}
        self._hashes = {}
        roots = roots if roots is not None else self.roots()
        for root in roots:
            try:
                if not root or not Path(root).is_dir():
                    continue
                for path in Path(root).rglob('*'):
                    if path.is_file():
                        size = path.stat().st_size
                        if size:
                            self.by_size.setdefault(size, []).append(path)
            except OSError:
                continue

    @staticmethod
    def roots():
        return (getattr(config, 'VANILLA_ASSETS_DIR', None),
                Path(config.STORAGE_PATH) / 'modellab' / 'rigkits')

    @staticmethod
    def _signature(roots):
        """The folders and their first level's mtimes: a new character or rig
        kit folder invalidates the scan at once."""
        out = []
        for root in roots:
            try:
                root = Path(root)
                out.append((str(root), root.stat().st_mtime_ns,
                            tuple(sorted((c.name, c.stat().st_mtime_ns) for c in root.iterdir() if c.is_dir()))))
            except (OSError, TypeError):
                out.append((str(root), None, ()))
        return tuple(out)

    @classmethod
    def shared(cls, now=None):
        """The cached scan for the current reference folders."""
        import time
        now = time.time() if now is None else now
        key = cls._signature(cls.roots())
        cached = _game_files_cache.get(key)
        if cached is None or now - cached[0] > GAME_FILES_TTL:
            cached = (now, cls())
            _game_files_cache.clear()
            _game_files_cache[key] = cached
        return cached[1]

    def available(self):
        return bool(self.by_size)

    def _bucket(self, size):
        """sha256 of every reference file of this size, computed once."""
        if size not in self._hashes:
            hashes = set()
            for path in self.by_size.get(size, ()):
                try:
                    with open(path, 'rb') as stream:
                        hashes.add(_sha256_stream(stream))
                except OSError:
                    continue
            self._hashes[size] = hashes
        return self._hashes[size]

    def matches(self, size, digest):
        """`digest` is a callable, so nothing is hashed unless a size matches."""
        if size not in self.by_size:
            return False
        return digest() in self._bucket(size)

    def file_is_game_file(self, path):
        return self.matches(Path(path).stat().st_size, lambda: _sha256_file(path))

    def archive_reason(self, source, depth=0):
        """GAME_FILES_INSIDE when an archive holds a disc image or a game file
        (nested archives too), else None. An unreadable archive is left to the
        whole-file check."""
        try:
            archive = zipfile.ZipFile(source)
        except (zipfile.BadZipFile, OSError, ValueError):
            return None
        with archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                suffix = Path(info.filename).suffix.lower()
                if suffix in DISC_IMAGES:
                    return GAME_FILES_INSIDE
                encrypted = bool(info.flag_bits & 1)
                if info.file_size in self.by_size:
                    if encrypted:
                        return GAME_FILES_INSIDE        # same size as a game file, cannot be checked
                    try:
                        with archive.open(info) as member:
                            if self.matches(info.file_size, lambda: _sha256_stream(member)):
                                return GAME_FILES_INSIDE
                    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, EOFError):
                        return GAME_FILES_INSIDE        # cannot be checked
                if suffix == '.zip' and not encrypted:
                    if depth >= 2 or info.file_size > NESTED_MAX:
                        return GAME_FILES_INSIDE        # too deep or too big to check
                    try:
                        nested = io.BytesIO(archive.read(info))
                    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, EOFError):
                        continue
                    reason = self.archive_reason(nested, depth + 1)
                    if reason:
                        return reason
        return None


def excluded_reason(path, info, game_files=None, screen=True):
    """Why a stored file must never leave, or None. `screen=False` (the files
    are not being sent) skips the byte and archive checks: only what the file
    says about itself is looked at."""
    origin = info.get('origin') if isinstance(info.get('origin'), dict) else {}
    extension = str(info.get('extension') or Path(str(info.get('name') or '')).suffix).lower()
    if extension in DISC_IMAGES:
        return DISC_IMAGE
    if origin.get('vanilla_color') or origin.get('model_candidate_id'):
        return GAME_FILE
    if origin.get('skin_id') or origin.get('character'):
        return FROM_VAULT
    if not screen:
        return None
    game_files = game_files if game_files is not None else GameFiles.shared()
    if game_files.file_is_game_file(path):
        return GAME_FILE
    if extension == '.zip' or zipfile.is_zipfile(path):
        return game_files.archive_reason(path)
    return None


# ---------------------------------------------------------------------------
# collecting
# ---------------------------------------------------------------------------

def _stored_file(file_id):
    """(path, info) for an attachment handle, or None when it is gone. Raises
    ValueError for a handle that exists but is malformed or points elsewhere."""
    root = _files_root()
    if root is None:
        return None
    directory = root / file_id
    metadata = directory / 'metadata.json'
    path = directory / 'content'
    if not metadata.is_file() or not path.is_file():
        return None
    if not _inside(metadata, root) or not _inside(path, root):
        raise ValueError(OUTSIDE)
    info = json.loads(metadata.read_text(encoding='utf-8'))
    if not isinstance(info, dict):
        raise ValueError('malformed metadata')
    return path, info


def _safe_name(name, fallback):
    name = str(name or '').replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', '_', name).strip()[:120]
    return name or fallback


def _cut(name):
    name = str(name)
    return name if len(name) <= NAME_MAX else name[:NAME_MAX] + '…'


def _archive_listing(path):
    """A too-large attachment ZIP's first members (name, size), for the manifest."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = [e for e in archive.infolist() if not e.is_dir()]
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return {'unreadable': f'{type(exc).__name__}'}
    listing = {'members': [{'name': _cut(e.filename), 'bytes': e.file_size} for e in entries[:LISTING_MAX]],
               'total_members': len(entries)}
    if len(entries) > LISTING_MAX:
        listing['more'] = f'+{len(entries) - LISTING_MAX} more'
    return listing


def _file_entry(role, file_id, path, info):
    name = _safe_name(info.get('name'), f'{file_id}{info.get("extension") or ""}')
    folder = {'attachment': 'attached', 'image': 'images'}[role]
    origin = info.get('origin') if isinstance(info.get('origin'), dict) else {}
    derived = origin.get('archive_file_id')
    return {'role': role, 'file_id': file_id, 'name': name,
            'path': f'files/{folder}/{file_id[:8]}-{name}',
            'source': path, 'bytes': path.stat().st_size,
            'store': Path(name).suffix.lower() in STORED,
            'derived_from': derived if isinstance(derived, str) else None}


def collapse_paths(text):
    """`C:\\Users\\Alice\\proj\\rigged.smd`, `\\\\nas\\share\\Alice\\body.smd` and
    `/mnt/team/Alice/model.dae` -> `<path>/<file name>`: the folders go, the
    file name stays."""
    if not isinstance(text, str):
        return text
    for pattern in (_DRIVE_DIRS, _UNC_DIRS, _POSIX_DIRS):
        text = pattern.sub('<path>/', text)
    return text


def _collapse(value, depth=0):
    if isinstance(value, str):
        return collapse_paths(value)
    if depth > 64:
        return value
    if isinstance(value, dict):
        return {collapse_paths(k) if isinstance(k, str) else k: _collapse(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_collapse(v, depth + 1) for v in value]
    return value


def _record_entry(label, data, scrub):
    """A text record: folders collapsed, then scrubbed. `data` is the raw bytes
    read from app storage, or a (size, sha256) pair for one too big to send."""
    if isinstance(data, tuple):
        return {'role': 'record', 'name': label, 'path': f'files/records/{label}', 'bytes': data[0],
                'sha256': data[1], 'status': 'too_large', 'oversize': True}
    text = data.decode('utf-8', errors='replace')
    try:
        text = json.dumps(scrub(_collapse(json.loads(text))), indent=1, ensure_ascii=False, default=str)
    except (ValueError, RecursionError):
        text = scrub(collapse_paths(text))
    body = text.encode('utf-8')
    return {'role': 'record', 'name': label, 'path': f'files/records/{label}', 'data': body,
            'bytes': len(body), 'store': False}


def _read_owned(path, root):
    """Bytes of a record inside `root`; (size, sha256) when it is over RECORD_MAX."""
    if not _inside(path, root) or not Path(path).is_file():
        return None
    size = Path(path).stat().st_size
    return Path(path).read_bytes() if size <= RECORD_MAX else (size, _sha256_file(path))


def _one_candidate(candidate_id, models, scrub):
    """(record entries, parent id, alignment id, image file ids, skipped notes) for one candidate."""
    data = _read_owned(models / f'{candidate_id}.json', models)
    if data is None:
        return [], None, None, [], []
    record = json.loads(data.decode('utf-8')) if isinstance(data, bytes) else {}
    if not isinstance(record, dict):
        raise ValueError('malformed record')
    records, images, skipped = [_record_entry(f'candidate-{candidate_id}.json', data, scrub)], [], []
    parent = record.get('parent_candidate_id')
    parent = parent if isinstance(parent, str) and _ID.match(parent) else None
    context = record.get('fit_context')
    alignment = context.get('alignment_id') if isinstance(context, dict) else None
    for group in (record.get('files'), record.get('source_preview')):
        for item in group if isinstance(group, list) else []:
            if isinstance(item, dict) and isinstance(item.get('file_id'), str):
                images.append(item['file_id'])
    directory = record.get('directory')
    if not isinstance(directory, str) or not _inside(directory, models):
        if directory:
            skipped.append({'name': f'candidate-{candidate_id} working folder', 'reason': OUTSIDE})
        return records, parent, alignment, images, skipped
    directory = _resolve(directory)
    candidate = record.get('candidate')
    rigged = candidate.get('rigged_smd') if isinstance(candidate, dict) else None
    wanted = []
    if isinstance(rigged, str) and rigged:
        wanted.append((f'candidate-{candidate_id}.fit.json', Path(rigged + '.fit.json')))
    if not parent:
        wanted += [(f'fit-{candidate_id}.assistant-result.json', directory / 'assistant-result.json'),
                   (f'fit-{candidate_id}.log', directory / 'fit.log')]
    for label, path in wanted:
        # The rig kit, vanilla assets and anything a record points at
        # outside its own working folder are never followed.
        if not _inside(path, directory) or not _inside(path, models):
            if path.exists():
                skipped.append({'name': label, 'reason': OUTSIDE})
            continue
        data = _read_owned(path, models)
        if data is not None:
            records.append(_record_entry(label, data, scrub))
    return records, parent, alignment, images, skipped


def _candidate_records(candidate_ids, alignment_ids, scrub):
    """(record entries, review image file ids named by the records, skipped, unavailable)."""
    models = _models_root()
    records, images, skipped, unavailable = [], [], [], []
    if models is None:
        if candidate_ids or alignment_ids:
            skipped.append({'name': 'model import records', 'reason': OUTSIDE})
        return records, images, skipped, unavailable
    seen, pending = set(), list(candidate_ids)
    alignments = list(alignment_ids)
    while pending and len(seen) < MAX_CANDIDATES:
        candidate_id = pending.pop(0)
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        try:
            found, parent, alignment, named, notes = _one_candidate(candidate_id, models, scrub)
        except Exception:                                       # noqa: BLE001 -- one bad record never blocks a report
            unavailable.append({'name': f'candidate-{candidate_id}', 'reason': UNREADABLE})
            continue
        records += found
        images += named
        skipped += notes
        if parent:
            pending.append(parent)
        if isinstance(alignment, str) and _ID.match(alignment):
            alignments.append(alignment)
    for alignment_id in dict.fromkeys(a for a in alignments if _ID.match(a)):
        try:
            data = _read_owned(models / f'{alignment_id}.alignment.json', models)
            if data is not None:
                records.append(_record_entry(f'alignment-{alignment_id}.json', data, scrub))
        except Exception:                                       # noqa: BLE001
            unavailable.append({'name': f'alignment-{alignment_id}', 'reason': UNREADABLE})
    return records, images, skipped, unavailable


def collect(chat, scrub, screen=True):
    """Everything this conversation could carry, classified. Nothing is packed yet.

    `screen` is whether the attachments and images will be sent (the toggle):
    when they will not, the game-file byte and archive checks are skipped.

    Returns {'records': [...], 'images': [...], 'attachments': [...],
             'excluded': [{name, reason}], 'unavailable': [{name, reason}]}.
    One unreadable record or attachment becomes an `unavailable` entry.
    """
    attached, used, candidate_ids, alignment_ids = references(chat)
    records, record_images, skipped, unavailable = _candidate_records(candidate_ids, alignment_ids, scrub)
    out = {'records': records, 'images': [], 'attachments': [], 'excluded': list(skipped),
           'unavailable': list(unavailable)}
    if _files_root() is None and (attached or used or record_images):
        out['excluded'].append({'name': 'attached files', 'reason': OUTSIDE})
    names = {}
    for message in chat.get('messages') or []:
        context = message.get('context') if isinstance(message, dict) else None
        files = context.get('files') if isinstance(context, dict) else None
        for item in files if isinstance(files, list) else []:
            if isinstance(item, dict) and isinstance(item.get('file_id'), str):
                names[item['file_id']] = item.get('name')
    attached_set = set(attached)
    game_files = GameFiles.shared() if screen else None
    seen = set()
    for file_id in [*attached, *used, *record_images]:
        if file_id in seen:
            continue
        seen.add(file_id)
        try:
            _classify(file_id, file_id in attached_set, names.get(file_id), game_files, out, screen)
        except Exception as exc:                                # noqa: BLE001
            reason = OUTSIDE if str(exc) == OUTSIDE else UNREADABLE
            target = out['excluded'] if reason == OUTSIDE else out['unavailable']
            target.append({'name': _safe_name(names.get(file_id), file_id), 'reason': reason})
    out['game_files_checked'] = bool(game_files and game_files.available())
    return out


def _classify(file_id, attached, known_name, game_files, out, screen=True):
    stored = _stored_file(file_id)
    if stored is None:
        if attached:
            out['unavailable'].append({'name': _safe_name(known_name, file_id),
                                       'reason': 'no longer on this computer'})
        return
    path, info = stored
    reason = excluded_reason(path, info, game_files, screen)
    if reason:
        out['excluded'].append({'name': _safe_name(info.get('name'), file_id), 'reason': reason})
        return
    extension = str(info.get('extension') or '').lower()
    origin = info.get('origin') if isinstance(info.get('origin'), dict) else None
    if not attached and extension == '.png' and not origin:
        if len(out['images']) < MAX_IMAGES:
            out['images'].append(_file_entry('image', file_id, path, info))
        return
    if attached or not info.get('edited'):
        # The user's own file: attached here, unpacked from an attachment,
        # or a source the model tools were handed.
        out['attachments'].append(_file_entry('attachment', file_id, path, info))


# ---------------------------------------------------------------------------
# the budget
# ---------------------------------------------------------------------------

def _deflated_size(entry):
    """Exactly what zipfile's default DEFLATE writes for this member's data."""
    compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    size = 0
    if 'data' in entry:
        return len(compressor.compress(entry['data'])) + len(compressor.flush())
    with open(entry['source'], 'rb') as stream:
        while chunk := stream.read(1 << 20):
            size += len(compressor.compress(chunk))
    return size + len(compressor.flush())


def packed_size(entry):
    """Bytes this member adds to the ZIP. Stores it when deflate would not help."""
    key = entry.get('sha256') or (entry['path'], entry['bytes'])
    if key not in _packed_cache:
        if entry.get('store'):
            _packed_cache[key] = (entry['bytes'], True)
        else:
            deflated = _deflated_size(entry)
            # Nothing gained: store it as it is.
            _packed_cache[key] = ((entry['bytes'], True) if deflated >= entry['bytes'] * 0.97
                                  else (deflated, False))
    size, stored = _packed_cache[key]
    entry['store'] = stored
    return size + _MEMBER_OVERHEAD + 2 * len(entry['path'].encode('utf-8'))


def _describe_file(entry):
    out = {'role': entry['role'], 'name': entry['name'], 'bytes': entry['bytes']}
    if entry.get('status') != 'not_selected':
        out['sha256'] = entry.get('sha256')
    out['status'] = entry.get('status')
    if entry.get('status') == 'included':
        out['path'] = entry['path']
    if entry.get('derived_from'):
        out['unpacked_from'] = entry['derived_from']
    if entry.get('listing'):
        out['archive'] = entry['listing']
    return out


def plan(collected, *, base_bytes, include_files, budget=FILES_BUDGET):
    """Choose what goes in. Returns (members to write, manifest).

    `base_bytes` is what the report members already take in the ZIP. Records go
    first, then (when the user leaves the toggle on) review images, then the
    attachments smallest first. Anything that does not fit is listed. Safe to
    call again on the same `collected` with less room.
    """
    used = base_bytes
    chosen = []
    for entry in [*collected['records'], *collected['images'], *collected['attachments']]:
        if not entry.get('oversize'):
            entry.pop('status', None)
        entry.pop('listing', None)

    def fit(entry, limit=None):
        nonlocal used
        if entry.get('status') == 'too_large':
            return
        try:
            if 'data' in entry:
                entry['sha256'] = hashlib.sha256(entry['data']).hexdigest()
            else:
                entry['bytes'] = Path(entry['source']).stat().st_size
                entry['sha256'] = _sha256_file(entry['source'])
            if limit is not None and entry['bytes'] > limit:
                entry['status'] = 'too_large'
                return
            # A store-only file bigger than the room left cannot fit however it is packed.
            if entry.get('store') and entry['bytes'] > budget - used:
                entry['status'] = 'too_large'
                return
            size = packed_size(entry)
        except OSError:
            entry['status'] = 'unavailable'
            return
        if used + size > budget:
            entry['status'] = 'too_large'
            return
        used += size
        entry['status'] = 'included'
        chosen.append(entry)

    for entry in collected['records']:
        fit(entry)
    images = list(collected['images'])
    attachments = sorted(collected['attachments'], key=lambda e: (e['bytes'], e['name']))
    if include_files:
        for entry in images:
            fit(entry, IMAGE_MAX)
        # A file unpacked from an attached archive is already inside it: only
        # send the unpacked copy when its archive could not go.
        direct = [e for e in attachments if not e.get('derived_from')]
        for entry in direct:
            fit(entry)
        sent = {e['file_id'] for e in direct if e.get('status') == 'included'}
        for entry in attachments:
            if entry.get('derived_from'):
                if entry['derived_from'] in sent:
                    entry['status'] = 'inside_attached_archive'
                else:
                    fit(entry)
        for entry in attachments:
            if entry.get('status') == 'too_large' and entry['name'].lower().endswith('.zip'):
                entry['listing'] = _archive_listing(entry['source'])
    else:
        for entry in [*images, *attachments]:
            entry['status'] = 'not_selected'
    entries = [*collected['records'], *images, *attachments]
    manifest = {
        'include_files': bool(include_files),
        'budget_bytes': budget,
        # What the toggle is about: the user's attachments and Randall's previews.
        'offer_count': sum(1 for e in [*images, *attachments] if not e.get('derived_from')),
        'game_files_checked': bool(collected.get('game_files_checked')),
        'files': [_describe_file(e) for e in entries],
        'excluded': list(collected['excluded']),
        'unavailable': [*collected['unavailable'],
                        *({'name': e['name'], 'reason': UNREADABLE} for e in entries
                          if e.get('status') == 'unavailable')],
    }
    return chosen, manifest


def summary_from_manifest(manifest):
    """What the preview says, read back from a manifest -- the same for a fresh
    freeze and for one that reuses a previewed freeze's files."""
    if not manifest:
        return None
    files = manifest.get('files') or []

    def pick(role):
        return [{'name': f['name'], 'bytes': f['bytes']} for f in files
                if f.get('role') == role and f.get('status') == 'included']
    return {
        'include_files': bool(manifest.get('include_files')),
        'offer_count': int(manifest.get('offer_count') or 0),
        'records': pick('record'), 'images': pick('image'), 'attachments': pick('attachment'),
        'too_large': [{'name': f['name'], 'bytes': f['bytes']} for f in files if f.get('status') == 'too_large'],
        'excluded': list(manifest.get('excluded') or []),
        'unavailable': list(manifest.get('unavailable') or []),
    }


def write_member(archive, entry, stamp):
    """Write one member and return the sha256 of the bytes written. A file is
    streamed from disk and hashed as it goes; if those bytes are not the ones
    screened and planned, `FilesChanged` is raised."""
    info = zipfile.ZipInfo(entry['path'], date_time=stamp)
    info.compress_type = zipfile.ZIP_STORED if entry.get('store') else zipfile.ZIP_DEFLATED
    if 'data' in entry:
        archive.writestr(info, entry['data'])
        return hashlib.sha256(entry['data']).hexdigest()
    info.file_size = entry['bytes']
    hasher, size = hashlib.sha256(), 0
    try:
        if 'zip_source' in entry:
            # A member of a previewed freeze (Send): streamed across, never held whole.
            holder = zipfile.ZipFile(entry['zip_source'])
            source = holder.open(entry['member'])
        else:
            holder, source = None, open(entry['source'], 'rb')
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise FilesChanged(entry['name']) from exc              # gone since it was screened
    try:
        with source, archive.open(info, 'w') as target:
            while chunk := source.read(1 << 20):
                hasher.update(chunk)
                size += len(chunk)
                target.write(chunk)
    finally:
        if holder is not None:
            holder.close()
    written = hasher.hexdigest()
    if written != entry.get('sha256') or size != entry['bytes']:
        raise FilesChanged(entry['name'])
    return written


def forget_hashes():
    """After `FilesChanged`: hash everything again from the bytes on disk."""
    _sha_cache.clear()
    _packed_cache.clear()


def mb(n):
    return f'{n / (1024 * 1024):.1f} MB'
