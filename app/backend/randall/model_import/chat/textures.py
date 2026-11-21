"""The files a model names beside itself, checked before an import runs (``import_job.start``, and the app MCP's
``import_model`` before it starts a job).

0.9.0 smoke test (2026-11-19): a bare Clank.obj came without its .mtl and PNGs, was saved all white, and nobody said
so. A model file names what it needs beside it:

* an OBJ its materials files (``mtllib``), and each of those its colour textures (``map_Kd``: the only map a Melee
  costume draws);
* a DAE its images (``<image><init_from>``; a ``data:`` URI is carried inside);
* an FBX the texture files of its ``Texture`` and ``Video`` objects (``FileName``, ``RelativeFilename``), except
  those a ``Video`` carries inside (a non-empty ``Content``: embedded media);
* a glTF its buffers and images (``uri``, except ``data:`` URIs). A GLB carries everything and is not read.

What counts as brought is what rigswap finds (rigswap ``load/open.py`` ``unpack``): a bare model file is copied with
the files of its own folder, and a ZIP is extracted whole. So a named file is there when a file of that name sits in
the model's folder, or anywhere in the ZIP. Names compare without case and without the folders the model file
recorded (a rip records the ripper's own ``C:\\Users\\...`` path; the importers look a texture up by its name). A ZIP's
own folders split on ``\\`` as well as ``/`` (``entry_path``: a ZIP made by Windows PowerShell), as rigswap extracts it.

``missing(path)`` -> None, or what is missing (``warning`` says it, naming each file for what it is: an OBJ's .mtl is
its materials file, a .bin a glTF's data, the rest textures). A file this cannot read is never reported: the check only
speaks when it is sure, and never stops an import the importer could run.
"""
import html
import json
import re
import struct
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

READ_CAP = 128 * 1024 * 1024        # bytes of one model or materials file read (mod_files.MAX_FILE)
ZIP_CAP = 256 * 1024 * 1024         # bytes read from one ZIP's model files in all
ZIP_MODELS = 24                     # model files looked at in one ZIP
LISTED = 6                          # names the warning lists; the rest are counted
READ = ('.obj', '.dae', '.fbx', '.gltf')
# A missing one of these means the model cannot be read at all, not only that it has no textures.
DATA = ('.bin',)
# An OBJ's materials file (``mtllib``): it names the textures, it is not one (0.9.0 smoke: Randall called a missing
# Clank.mtl "a texture file").
MATERIALS = ('.mtl',)
# What ``warning`` calls each missing file (singular, plural), by kind; everything else a model names is an image.
KINDS = (('materials', 'materials file', 'materials files'), ('data', 'data file', 'data files'),
         ('texture', 'texture', 'textures'))


# ------------------------------------------------------------------ names

def _name(ref, uri=False):
    """The file name of a path as a model file wrote it ('C:\\rip\\tex\\Body.png', 'textures/Body%20A.png')."""
    text = html.unescape(str(ref)).strip().strip('"').strip()
    if uri or text.lower().startswith('file:'):
        text = urllib.parse.unquote(re.sub(r'(?i)^file:/*', '', text))
    return PureWindowsPath(text).name           # splits on / and \ alike


def _unique(names):
    """``names`` without blanks and case duplicates, in order."""
    seen, kept = set(), []
    for name in names:
        if name and name.lower() not in seen:
            seen.add(name.lower())
            kept.append(name)
    return kept


# ------------------------------------------------------------------ OBJ

_MTLLIB = re.compile(rb'^[ \t]*mtllib[ \t]+([^\r\n]+?)[ \t]*\r?$', re.M | re.I)     # CRLF too (3ds Max writes it)
_MAP_KD = re.compile(rb'^[ \t]*map_Kd[ \t]+([^\r\n]+?)[ \t]*\r?$', re.M | re.I)
# map_Kd's options and how many values each takes at most (-o/-s/-t take one to three).
_OPTIONS = {'-blendu': 1, '-blendv': 1, '-boost': 1, '-cc': 1, '-clamp': 1, '-imfchan': 1, '-texres': 1, '-bm': 1,
            '-mm': 2, '-o': 3, '-s': 3, '-t': 3, '-type': 1}
_VALUE = re.compile(r'[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?|on|off|[rgbmlz]|sphere|cube_\w+', re.I)


def _map_file(rest):
    """map_Kd's file after its options: '-s 1 1 1 -bm 0.5 body.png' -> 'body.png'."""
    words = rest.split()
    at = 0
    while at < len(words) - 1 and words[at].lower() in _OPTIONS:
        values = _OPTIONS[words[at].lower()]
        at += 1
        while values and at < len(words) - 1 and _VALUE.fullmatch(words[at]):
            values, at = values - 1, at + 1
    return ' '.join(words[at:])


def _text(data):
    return data.decode('utf-8', 'replace').strip()


def _obj_names(data, read_beside):
    """The materials files an OBJ names, and the colour textures each of them names (when it is there to read)."""
    names = []
    for found in _MTLLIB.finditer(data):
        whole = _name(_text(found.group(1)))
        libs = [whole]
        parts = [_name(p) for p in _text(found.group(1)).split()]
        if read_beside(whole) is None and len(parts) > 1 and all(read_beside(p) is not None for p in parts):
            libs = parts                        # "mtllib a.mtl b.mtl": several files on one line
        for lib in libs:
            names.append(lib)
            materials = read_beside(lib)
            if materials is not None:
                names += [_name(_map_file(_text(m.group(1)))) for m in _MAP_KD.finditer(materials)]
    return names


# ------------------------------------------------------------------ DAE

_IMAGE = re.compile(rb'<image\b[^>]*?(?<!/)>(.*?)</image>', re.S)
_INIT_FROM = re.compile(rb'<init_from\b[^>]*>\s*(?:<ref>\s*)?([^<]*?)\s*(?:</ref>\s*)?</init_from>', re.S)


def _dae_names(data):
    names = []
    for image in _IMAGE.finditer(data):
        found = _INIT_FROM.search(image.group(1))
        ref = _text(found.group(1)) if found else ''
        if ref and not ref.lower().startswith('data:'):
            names.append(_name(ref, uri=True))
    return names


# ------------------------------------------------------------------ FBX

_FBX_BINARY = b'Kaydara FBX Binary  \x00'
_FILE_FIELDS = (b'FileName', b'Filename', b'RelativeFilename')


def _fbx_binary(data):
    """(names, carried) of a binary FBX: the file names its Texture and Video objects record, and those of them a
    Video carries inside (its Content)."""
    version = struct.unpack_from('<I', data, 23)[0]
    head = struct.Struct('<QQQB' if version >= 7500 else '<IIIB')

    def nodes(start, stop):
        """(name, first property offset, children offset, end) of each node from ``start`` to its list's end."""
        at = start
        while at + head.size <= stop:
            end, _count, length, size = head.unpack_from(data, at)
            if end == 0:                        # the null record that closes a list
                return
            if end <= at or end > len(data):
                raise ValueError('not an FBX node')
            props = at + head.size + size
            yield bytes(data[at + head.size:props]), props, props + length, end
            at = end

    def first(props):
        """(type code, length) of a node's first property, for a string (S) or raw bytes (R)."""
        code = data[props:props + 1]
        return (code, struct.unpack_from('<I', data, props + 1)[0]) if code in (b'S', b'R') else (code, 0)

    names, carried = [], set()
    for name, _props, children, end in nodes(27, len(data)):
        if name != b'Objects':
            continue
        for kind, _p, inner, stop in nodes(children, end):
            if kind not in (b'Video', b'Texture'):
                continue
            own, embedded = [], False
            for field, props, _c, _e in nodes(inner, stop):
                code, length = first(props)
                if field in _FILE_FIELDS and code == b'S' and length:
                    own.append(_name(_text(data[props + 5:props + 5 + length])))
                elif field == b'Content' and length:
                    embedded = True
            names += own
            if embedded:
                carried.update(n.lower() for n in own)
    return names, carried


_ASCII_OBJECT = re.compile(r'^[ \t]*(?:Video|Texture):[^\n{]*\{', re.M)
_ASCII_FILE = re.compile(r'^[ \t]*(?:FileName|Filename|RelativeFilename):[ \t]*"([^"]*)"', re.M)
_ASCII_CONTENT = re.compile(r'^[ \t]*Content:[ \t]*(?:,[ \t]*)?(?:"[^"]|\*[1-9])', re.M)
_BRACE = re.compile(r'[{}]')


def _fbx_ascii(text):
    names, carried = [], set()
    for head in _ASCII_OBJECT.finditer(text):
        depth, end = 1, len(text)
        for brace in _BRACE.finditer(text, head.end()):
            depth += 1 if brace.group() == '{' else -1
            if not depth:
                end = brace.start()
                break
        body = text[head.end():end]
        own = [_name(m.group(1)) for m in _ASCII_FILE.finditer(body)]
        names += own
        if _ASCII_CONTENT.search(body):
            carried.update(n.lower() for n in own)
    return names, carried


def _fbx_names(data):
    names, carried = (_fbx_binary(data) if data.startswith(_FBX_BINARY)
                      else _fbx_ascii(data.decode('utf-8', 'replace')))
    return [n for n in names if n.lower() not in carried]


# ------------------------------------------------------------------ glTF

def _gltf_names(data):
    document = json.loads(data)
    names = []
    for key in ('buffers', 'images'):
        for item in document.get(key) or []:
            uri = item.get('uri') if isinstance(item, dict) else None
            if isinstance(uri, str) and uri.strip() and not uri.startswith('data:'):
                names.append(_name(uri, uri=True))
    return names


# ------------------------------------------------------------------ the check

def named(suffix, data, read_beside=lambda name: None):
    """The files a model file of kind ``suffix`` names beside itself (``read_beside(name)``: the bytes of a file of
    that name beside it, or None; an OBJ's materials file is read for its textures)."""
    if suffix == '.obj':
        return _unique(_obj_names(data, read_beside))
    if suffix == '.dae':
        return _unique(_dae_names(data))
    if suffix == '.fbx':
        return _unique(_fbx_names(data))
    if suffix == '.gltf':
        return _unique(_gltf_names(data))
    return []


def _beside(path):
    """A bare model file: what it names that is not in its own folder."""
    files = {p.name.lower(): p for p in path.parent.iterdir() if p.is_file()}

    def read_beside(name):
        found = files.get(name.lower())
        return found.read_bytes() if found is not None and found.stat().st_size <= READ_CAP else None
    if path.stat().st_size > READ_CAP:
        return None
    missing = [n for n in named(path.suffix.lower(), path.read_bytes(), read_beside) if n.lower() not in files]
    return dict(model=path.name, missing=missing, source=path.name, archive=False) if missing else None


def entry_path(name):
    """A ZIP entry's name as a path, its folders split on ``\\`` as well as ``/``. A ZIP made on Windows (PowerShell's
    Compress-Archive: ``Clank\\Clank.obj``) separates folders with a backslash, and Python's zipfile turns that into
    ``/`` only where ``os.sep`` is ``\\``: on Linux and macOS the entry was one file named ``Clank\\Clank.obj``, and the
    Clank.mtl beside it "not in the ZIP" (0.9.0 build 3 Linux smoke). rigswap extracts the ZIP the same way
    (rigswap ``load/open.py`` ``_extract``)."""
    return PurePosixPath(str(name).replace('\\', '/'))


def _in_zip(path):
    """A ZIP: what its model files name that the ZIP does not hold (by name, in any folder)."""
    with zipfile.ZipFile(path) as archive:
        entries = [e for e in archive.infolist() if not e.is_dir() and not e.filename.endswith('\\')]
        by_name = {}
        for entry in entries:
            by_name.setdefault(entry_path(entry.filename).name.lower(), []).append(entry)
        models = [e for e in entries if entry_path(e.filename).suffix.lower() in READ
                  and e.file_size <= READ_CAP][:ZIP_MODELS]
        gaps, read = {}, 0
        for model in models:
            read += model.file_size
            if read > ZIP_CAP:
                break
            where = entry_path(model.filename)

            def read_beside(name, folder=where.parent):
                found = by_name.get(name.lower()) or []
                pick = next((e for e in found if entry_path(e.filename).parent == folder), found[0] if found else None)
                return archive.read(pick) if pick is not None and pick.file_size <= READ_CAP else None
            names = named(where.suffix.lower(), archive.read(model), read_beside)
            missing = [n for n in names if n.lower() not in by_name]
            if missing:
                gaps[where.as_posix()] = missing
    if not gaps:
        return None
    return dict(model=', '.join(list(gaps)[:3]) + (f' and {len(gaps) - 3} more' if len(gaps) > 3 else ''),
                missing=_unique([n for names in gaps.values() for n in names]), source=Path(path).name, archive=True)


def missing(path):
    """What the model at ``path`` (a ZIP, or a model file) names beside itself that did not come with it:
    {model, missing: [file names], source, archive}, else None. None too for anything this cannot read."""
    path = Path(path)
    try:
        if path.suffix.lower() == '.zip':
            return _in_zip(path)
        if path.suffix.lower() in READ:
            return _beside(path)
    except Exception:       # a file this cannot read (bad FBX, encrypted ZIP...): the importer says what it makes of it
        return None
    return None


def kind(name):
    """What a file a model names is: 'materials' (an OBJ's .mtl), 'data' (a glTF's .bin) or 'texture' (an image)."""
    suffix = Path(name).suffix.lower()
    return 'materials' if suffix in MATERIALS else 'data' if suffix in DATA else 'texture'


def _listed(names):
    return ', '.join(names[:LISTED]) + (f' and {len(names) - LISTED} more' if len(names) > LISTED else '')


def warning(gap):
    """``missing``'s finding in a sentence or two, in the app's words, each file named for what it is: "Clank.obj
    came without the materials file Clank.mtl." (an OBJ's .mtl is not a texture). "the", not "its": a ZIP's finding
    can be about several model files."""
    names = gap['missing']
    groups = []
    for key, one, many in KINDS:
        found = [n for n in names if kind(n) == key]
        if found:
            groups.append(f"the {one if len(found) == 1 else many} {_listed(found)}")
    what = groups[0] if len(groups) == 1 else ', '.join(groups[:-1]) + ' and ' + groups[-1]
    them = 'it' if len(names) == 1 else 'them'
    effect = 'cannot be read' if any(kind(n) == 'data' for n in names) else \
        'would import with no textures (all white)'
    where = f": the ZIP does not hold {them}" if gap.get('archive') else ''
    model = f"{gap['model']} in {gap['source']}" if gap.get('archive') else gap['model']
    return f"{model} came without {what}{where}. Without {them} the model {effect}."
