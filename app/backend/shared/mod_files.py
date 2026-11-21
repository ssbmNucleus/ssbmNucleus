"""Opaque handles for attached files and Randall's derived working copies.

Lives in shared/ (moved from randall/assistant/ for 0.8.16) because shipped code uses it too: the
stage editor, the viewer's texture hand-off and Echo cloning read DAT roots and file handles
here, and a stable build carries no randall package. Opening a vault costume as a chat file
(``open_vault_file``) is assistant-only and lives in ``randall/assistant/vault_items.py``.
"""
import collections
import difflib
import hashlib
import io
import json
import re
import shutil
import struct
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import file_retry
from core import config
from core.hashing import sha256_file as digest  # also read as mod_files.digest

MAX_FILE = 128 * 1024 * 1024
# A ZIP is never unpacked whole: model intake chooses the model inside it first
# and extracts only what that model links (source_intake.prepare_input), held
# to MAX_FILE. So an archive may be far bigger than anything it yields -- a
# Kingdom Hearts 3 Rapunzel is 159 MB of zip (462 MB expanded: several outfits,
# each as DAE, FBX and a UV-split copy) around one 66 MB model. Uploads are
# stored chunk by chunk (`register_stream`), never held in memory whole.
MAX_ARCHIVE = 1024 * 1024 * 1024
STREAM_CHUNK = 1 << 20
# The one list of what a chat (and the app MCP's attach_file) takes. The chat's file input mirrors it
# (AssistantPanel.jsx `accept`; tests/backend/test_assistant_mod_files.py holds the two together).
EXTENSIONS = {'.dat', '.usd', '.lat', '.rat', '.pat', '.sat', '.mat', '.cat', '.fat', '.wat', '.aj', '.png', '.zip', '.smd', '.anim', '.dae', '.glb', '.gltf', '.obj', '.fbx'}


def root():
    path = config.STORAGE_PATH.resolve() / 'assistant' / 'files'
    if not path.resolve().is_relative_to(config.STORAGE_PATH.resolve()):
        raise ValueError('Assistant file storage is outside the vault.')
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def resolve(file_id):
    if not isinstance(file_id, str) or not re.fullmatch(r'[a-f0-9]{32}', file_id):
        raise ValueError(f'file_id {_shown(file_id)} is not a file ID. Use a file ID from an attachment or tool '
                         'result: 32 lowercase hex characters such as "b48bc6325cad448ab8a1c497c88a00e7", '
                         'never a file name or a path.')
    directory = root() / file_id
    if not directory.resolve().is_relative_to(root()):
        raise ValueError('Invalid file location.')
    try:
        metadata_path = directory / 'metadata.json'
        if not metadata_path.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Invalid file metadata location.')
        if not metadata_path.is_file():
            raise ValueError(f'file_id "{file_id}" is unavailable: no attached or generated file has that ID. '
                             'Use a file ID from an attachment or tool result.')
        info = json.loads(metadata_path.read_text(encoding='utf-8'))
        path = directory / 'content'
        if not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError('The attached file is unavailable.')
        if path.stat().st_size > size_limit(info.get('extension')) or digest(path) != info['sha256']:
            raise ValueError('The working file changed. Attach or open it again.')
        return path, info
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('The attached file is unavailable.') from exc


def _shown(value, limit=80):
    """An argument as an error quotes it: short, and never a whole pasted blob."""
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + '...'


def describe(info):
    return {key: info[key] for key in ('file_id', 'name', 'size', 'extension', 'sha256')}


def origin_of(info):
    """A file's origin as a dict. Some callers record a plain label (a string) as the origin."""
    origin = info.get('origin')
    if isinstance(origin, dict):
        return dict(origin)
    return {'source': origin} if origin else {}


def size_limit(extension):
    return MAX_ARCHIVE if extension == '.zip' else MAX_FILE


def _too_large(extension):
    if extension == '.zip':
        return ('ZIP files must be nonempty and no larger than 1 GB. Make a smaller ZIP with only the model you '
                'want (its .dae, .fbx, .smd, .obj or .glb file) and the textures and material files beside it, '
                'leaving out the other outfits and formats.')
    return ('Files must be nonempty and no larger than 128 MB. A model with its textures can be attached as a ZIP '
            'of up to 1 GB.')


def _checked_name(name):
    name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', '_', name)[:160]
    extension = Path(name).suffix.lower()
    if not name or extension not in EXTENSIONS:
        raise ValueError('Attach a DAT, ZIP, PNG, GLB, glTF, FBX, OBJ, SMD, DAE or animation file. Put model companion files in a ZIP.')
    return name, extension


def register_stream(stream, name, *, origin=None, edited=False):
    """`register` for an upload stream: a ZIP goes to disk a chunk at a time, held to MAX_ARCHIVE."""
    name, extension = _checked_name(name)
    if extension != '.zip':
        return register(stream.read(MAX_FILE + 1), name, origin=origin, edited=edited)
    file_id = uuid.uuid4().hex
    directory = root() / file_id
    directory.mkdir()
    partial, hasher, size = directory / 'content.part', hashlib.sha256(), 0
    try:
        with open(partial, 'xb') as out:
            while True:
                chunk = stream.read(STREAM_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise ValueError(_too_large(extension))
                hasher.update(chunk)
                out.write(chunk)
        if not size:
            raise ValueError(_too_large(extension))
        file_retry.replace(partial, directory / 'content')
        info = {'file_id': file_id, 'name': name, 'size': size, 'extension': extension,
                'sha256': hasher.hexdigest(), 'origin': origin, 'edited': edited}
        # inside the cleanup: a metadata write that fails must not orphan the upload
        (directory / 'metadata.json').write_text(json.dumps(info), encoding='utf-8')
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return describe(info)


def register(data, name, *, origin=None, edited=False):
    name, extension = _checked_name(name)
    if not data or len(data) > size_limit(extension):
        raise ValueError(_too_large(extension))
    if extension == '.png':
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(data)) as picture:
                if picture.format != 'PNG' or picture.width * picture.height > 16_777_216:
                    raise ValueError('Use a PNG up to 16 megapixels.')
                picture.verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise ValueError('Use a valid PNG up to 16 megapixels.') from exc
    file_id = uuid.uuid4().hex
    directory = root() / file_id
    directory.mkdir()
    info = {'file_id': file_id, 'name': name, 'size': len(data), 'extension': extension,
            'sha256': hashlib.sha256(data).hexdigest(), 'origin': origin, 'edited': edited}
    try:
        (directory / 'content').write_bytes(data)
        (directory / 'metadata.json').write_text(json.dumps(info), encoding='utf-8')
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return describe(info)


def attachment_context(values):
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError('Attach up to eight files per message.')
    return [describe(resolve(value['file_id'] if isinstance(value, dict) else value)[1]) for value in values]


def archive_entries(path):
    try:
        archive_file = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError('This file is not a readable ZIP archive.') from exc
    with archive_file as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 512 * 1024 * 1024:
            raise ValueError('This archive is too large to inspect. Attach individual files instead.')
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError('The archive contains ambiguous duplicate filenames.')
        if any(entry.flag_bits & 1 for entry in entries):
            raise ValueError('Attach an unencrypted ZIP or its individual files.')
        return [entry for entry in entries if not entry.is_dir() and
                Path(entry.filename).suffix.lower() in EXTENSIONS and entry.file_size <= MAX_FILE]


# The 3D model files among EXTENSIONS (the model import reads all but .smd).
MODEL_SUFFIXES = {'.dae', '.glb', '.gltf', '.obj', '.smd', '.fbx'}
LISTED_MEMBERS = 200


def _listing_rank(entry):
    """Models first, then other files (DATs, animations), then images: a pack with hundreds of
    textures must not push its models out of a capped listing."""
    suffix = Path(entry.filename).suffix.lower()
    return 0 if suffix in MODEL_SUFFIXES else 2 if suffix == '.png' else 1


def _quoted(names):
    return ', '.join(f'"{name}"' for name in names)


def _example_member(entries):
    ranked = sorted(entries, key=_listing_rank)
    return ranked[0].filename if ranked else 'folder/model.dae'


def _member_error(member, entries, path, info):
    """Why `member` cannot be opened, naming the argument and the valid form."""
    usage = ("Pass member = one exact name from inspect_mod_file's members list for this ZIP, "
             f'e.g. {{"file_id": "{info["file_id"]}", "member": "{_example_member(entries)}"}}.')
    if not isinstance(member, str) or not member.strip():
        return f'member must be one member name as a string; got {_shown(member)}. {usage}'
    names = [entry.filename for entry in entries]
    with zipfile.ZipFile(path) as archive:
        raw = {entry.filename: entry for entry in archive.infolist()}
    entry = raw.get(member)
    if entry is not None and entry.is_dir():
        inside = [name for name in names if name.startswith(member)]
        return (f'member {_shown(member)} is a folder in this ZIP, not a file. Name one file inside it'
                + (', e.g. ' + _quoted(sorted(inside, key=lambda n: _listing_rank(raw[n]))[:3]) if inside else '')
                + '.')
    if entry is not None:
        suffix = Path(member).suffix.lower() or '(no extension)'
        stem = str(PurePosixPath(member).with_suffix(''))
        beside = [name for name in names if str(PurePosixPath(name).with_suffix('')) == stem]
        if suffix not in EXTENSIONS:
            return (f'member {_shown(member)} is in this ZIP, but {suffix} files cannot be opened here. '
                    + (f'Open the same model as {_quoted(beside)} instead.' if beside
                       else f'Openable kinds: {", ".join(sorted(EXTENSIONS))}.'))
        return f'member {_shown(member)} is larger than {MAX_FILE // (1024 * 1024)} MB, too large to open on its own.'
    wanted = member.replace('\\', '/').strip('/')
    base = PurePosixPath(wanted).name.casefold()
    close = [name for name in names if name.casefold() == wanted.casefold()]
    close += [name for name in names if PurePosixPath(name).name.casefold() == base and name not in close]
    close += [name for name in difflib.get_close_matches(wanted, names, n=5, cutoff=0.6) if name not in close]
    if close:
        return (f'member {_shown(member)} is not in this ZIP ({info["name"]}). Member names are exact, with '
                f'their folders and forward slashes. Closest: {_quoted(close[:5])}.')
    return f'member {_shown(member)} is not in this ZIP ({info["name"]}). {usage}'


def unpack_file(file_id, member):
    path, info = resolve(file_id)
    if info['extension'] != '.zip':
        raise ValueError(f'file_id "{file_id}" is {info["name"]} ({info["extension"]}), not a ZIP: unpack_mod_file '
                         'opens one member of a ZIP. Pass the ZIP\'s own file_id, and the member name from '
                         'inspect_mod_file, e.g. {"file_id": "<zip file ID>", "member": "folder/model.dae"}.')
    entries = archive_entries(path)
    if not isinstance(member, str) or member not in [entry.filename for entry in entries]:
        raise ValueError(_member_error(member, entries, path, info))
    # Read this entry as bytes, never extract paths supplied by the archive.
    with zipfile.ZipFile(path) as archive:
        data = archive.read(member)
    # Always record where a member came from: a model unpacked on its own
    # leaves its textures behind in the archive, and the fitter needs to be
    # able to name the ZIP to go back to. The ZIP's own origin may be a plain
    # label rather than a dict (an upload tagged by where it came from).
    origin = {**origin_of(info), 'archive_file_id': file_id, 'member': member}
    return {'files': [register(data, PurePosixPath(member).name, origin=origin)]}


def dat_roots(path):
    # never read an attachment past the DAT limit whole: a ZIP attachment may be 1 GB
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Not a valid HSD DAT header.')
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError('Not a valid HSD DAT header.')
    size, data_size, relocs, roots, refs = struct.unpack_from('>5I', data)
    table = 32 + data_size + relocs * 4
    strings = table + (roots + refs) * 8
    if size != len(data) or roots > 4096 or refs > 4096 or strings > len(data):
        raise ValueError('Not a valid HSD DAT header or root table.')
    names = []
    for index in range(roots):
        offset, name_offset = struct.unpack_from('>II', data, table + index * 8)
        start = strings + name_offset
        end = data.find(b'\0', start, start + 512)
        if offset >= data_size or start >= len(data) or end < 0:
            raise ValueError('Invalid DAT root entry.')
        names.append(data[start:end].decode('ascii', errors='replace'))
    return names


def _model_rig(archive, entry):
    """Whether a model member carries its own skeleton and skin weights. A
    Gabite ZIP held a rigged model.dae beside a bare model.obj; nothing in the
    listing said which was which, and the import bound the OBJ with guessed
    weights three times."""
    suffix = Path(entry.filename).suffix.lower()
    if suffix == '.obj':
        return {'rig': 'none'}
    if suffix not in {'.dae', '.glb', '.gltf', '.smd'} or entry.file_size > 64 * 1024 * 1024:
        return {}
    try:
        data = archive.read(entry)
        if suffix == '.dae':
            bones, skinned = data.count(b'type="JOINT"'), b'<skin' in data
            animated = re.search(rb'<library_animations>\s*<animation', data) is not None
        elif suffix == '.smd':
            text = data.decode('latin-1')
            nodes = text.split('nodes', 1)[1].split('end', 1)[0] if 'nodes' in text else ''
            bones = sum(1 for line in nodes.splitlines() if line.strip())
            skinned, animated = bones > 1 and 'triangles' in text, text.count('time ') > 1
        else:
            if suffix == '.glb':
                length = struct.unpack_from('<I', data, 12)[0]
                data = data[20:20 + length]
            document = json.loads(data)
            skins = document.get('skins', [])
            bones, skinned = sum(len(skin.get('joints', [])) for skin in skins), bool(skins)
            animated = bool(document.get('animations'))
    except (ValueError, KeyError, IndexError, struct.error, zipfile.BadZipFile):
        return {}
    return {'rig': f'{bones} bones, skin weights' if skinned and bones else 'none',
            **({'animations': True} if animated else {})}


def _zip_listing(path):
    """A ZIP's members for inspect_mod_file: models first (with their rig), capped at LISTED_MEMBERS.

    Game-rip packs carry hundreds of textures beside a few dozen models; in
    archive order the cap cut the listing off inside the textures and left
    most models out. What the cap drops is counted by folder, and members no
    tool here can open (.blend, .txt and the like) are counted by extension.
    """
    entries = archive_entries(path)
    ranked = sorted(entries, key=_listing_rank)
    shown, rest = ranked[:LISTED_MEMBERS], ranked[LISTED_MEMBERS:]
    with zipfile.ZipFile(path) as archive:
        members = [{'name': e.filename, 'size': e.file_size, **_model_rig(archive, e)} for e in shown]
        everything = [e for e in archive.infolist() if not e.is_dir()]
    result = dict(members=members, total_members=len(entries), truncated=bool(rest),
                  models=sum(_listing_rank(e) == 0 for e in entries))
    notes = []
    if rest:
        folders = (str(PurePosixPath(e.filename).parent) for e in rest)
        result['unlisted_by_folder'] = dict(collections.Counter('(top level)' if f == '.' else f for f in folders))
        notes.append(f'{len(rest)} members are not listed by name (counted per folder in unlisted_by_folder); '
                     'models are listed first, so these are textures or other files. unpack_mod_file still opens '
                     'any of them by exact name.')
    openable = {e.filename for e in entries}
    skipped = collections.Counter(Path(e.filename).suffix.lower() or '(no extension)'
                                  for e in everything if e.filename not in openable)
    if skipped:
        result['not_openable'] = dict(skipped)
        notes.append('Members counted in not_openable (by extension) are left out: these tools cannot open that '
                     'kind, or the member is over 128 MB. For a model, use a .fbx/.dae/.glb/.gltf/.obj/.smd copy of it '
                     'when the ZIP has one.')
    if notes:
        result['note'] = ' '.join(notes)
    return result


def inspect_mod_file(file_id):
    path, info = resolve(file_id)
    result = {'file': describe(info)}
    if info['extension'] == '.zip':
        result.update(_zip_listing(path))
    elif info['extension'] == '.png':
        from PIL import Image
        with Image.open(path) as picture:
            result.update(width=picture.width, height=picture.height)
        result['files'] = [describe(info)]
    elif info['extension'] in MODEL_SUFFIXES | {'.anim'}:
        result['note'] = 'Model or animation asset. A model import (import_model) takes the attached file itself. Models with external textures/materials/buffers need a ZIP containing those companion files.'
    else:
        result['roots'] = dat_roots(path)
        result['textures'] = texture_inventory(path)
        result['note'] = 'Root symbols from the actual file. Use a model joint root with HSDRaw mesh/texture operations; a DAT parse is not a gameplay or Slippi test.'
    return result


def texture_inventory(path):
    """Bounded JOBJ/DOBJ/TOBJ walk in the CLI's depth-first texture order."""
    from shared.rendering.datprobe import DatFile, TEX_FMT
    dat = DatFile(path)
    textures = []
    steps = 0
    def pointer(offset):
        nonlocal steps
        steps += 1
        if steps > 50000 or not 0 <= offset <= dat.data_size - 4:
            raise ValueError('The DAT texture tree is invalid or too large to inspect.')
        value = dat.ptr(offset)
        if value is not None and not 0 <= value < dat.data_size:
            raise ValueError('The DAT texture tree contains an invalid pointer.')
        return value
    for name, root_offset in dat.roots:
        if not name.endswith('_joint') or 'matanim' in name or 'shapeanim' in name:
            continue
        pending, seen, index = [root_offset], set(), 0
        while pending:
            joint = pending.pop()
            if joint is None or joint in seen:
                continue
            seen.add(joint)
            pending.extend([pointer(joint + 0x0c), pointer(joint + 0x08)])
            if dat.u32(joint + 4) & ((1 << 14) | (1 << 5)):
                continue
            dobj = pointer(joint + 0x10)
            seen_dobjs = set()
            while dobj is not None:
                if dobj in seen_dobjs:
                    raise ValueError('The DAT has a cyclic mesh list.')
                seen_dobjs.add(dobj)
                material = pointer(dobj + 8)
                texture = pointer(material + 8) if material is not None else None
                seen_textures = set()
                while texture is not None:
                    if texture in seen_textures:
                        raise ValueError('The DAT has a cyclic texture list.')
                    seen_textures.add(texture)
                    image = pointer(texture + 0x4c)
                    if image is not None:
                        if image + 12 > dat.data_size or len(textures) >= 1000:
                            raise ValueError('The DAT has invalid or too many textures.')
                        textures.append({'node': name, 'texture_index': index,
                            'width': dat.u16(image + 4), 'height': dat.u16(image + 6),
                            'format': TEX_FMT.get(dat.u32(image + 8), 'unknown')})
                        index += 1
                    texture = pointer(texture + 4)
                dobj = pointer(dobj + 4)
    return textures
