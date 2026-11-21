"""The texture files a model names, looked for before an import runs (model_import/chat/textures.py).

0.9.0 smoke test (2026-11-19): a bare Clank.obj was attached without its Clank.mtl and PNGs, imported all white, and
nobody said so. The check reads what each kind of model file names (OBJ mtllib + map_Kd, DAE image init_from, FBX
Texture/Video file names less what a Video carries inside, glTF buffers and images) and looks for it where rigswap
will: beside a bare file, anywhere in a ZIP.
"""
import json
import os
import posixpath
import struct
import zipfile

import pytest

from randall.model_import.chat import textures


# ------------------------------------------------------------------ a binary FBX, just the nodes the check reads

def _prop(value):
    if isinstance(value, str):
        data = value.encode('utf-8')
        return b'S' + struct.pack('<I', len(data)) + data
    return b'R' + struct.pack('<I', len(value)) + value


def _nodes(nodes, at, wide):
    head = struct.Struct('<QQQB' if wide else '<IIIB')
    out = b''
    for name, props, children in nodes:
        name = name.encode('ascii')
        encoded = b''.join(_prop(p) for p in props)
        inner = at + head.size + len(name) + len(encoded)
        kids = _nodes(children, inner, wide) + bytes(head.size) if children else b''
        end = inner + len(kids)
        out += head.pack(end, len(props), len(encoded), len(name)) + name + encoded + kids
        at = end
    return out


def _fbx(objects, version=7400):
    head = b'Kaydara FBX Binary  \x00\x1a\x00' + struct.pack('<I', version)
    wide = version >= 7500
    body = _nodes([('FBXHeaderExtension', (), [('FBXVersion', (), [])]), ('Objects', (), objects)], len(head), wide)
    return head + body + bytes(25 if wide else 13)


def _video(file_name, content=b''):
    return ('Video', ('Video::Face', 'Clip'), [('Type', ('Clip',), []), ('FileName', (file_name,), []),
                                                ('RelativeFilename', (file_name.split('\\')[-1],), []),
                                                ('Content', (content,), [])])


def _texture(file_name, relative=None):
    return ('Texture', ('Texture::t', ''), [('FileName', (file_name,), []),
                                            ('RelativeFilename', (relative or file_name,), [])])


# ------------------------------------------------------------------ a bare model file: beside it, in its folder

def test_the_smoke_tests_bare_obj_is_named_with_what_it_lacks(tmp_path):
    model = tmp_path / 'Clank.obj'
    model.write_bytes(b'# Blender\r\nmtllib Clank.mtl\r\no Clank\r\nv 0 0 0\r\n')
    gap = textures.missing(model)
    assert gap == dict(model='Clank.obj', missing=['Clank.mtl'], source='Clank.obj', archive=False)
    # 0.9.0 smoke: Randall said Clank.obj "names a texture file that didn't come with it, Clank.mtl". The .mtl is the
    # model's materials file, and the warning says so.
    assert textures.warning(gap) == ('Clank.obj came without the materials file Clank.mtl. Without it the model '
                                     'would import with no textures (all white).')


def test_an_obj_with_its_materials_is_read_on_to_their_textures(tmp_path):
    (tmp_path / 'Goku.obj').write_text('mtllib ./Goku.mtl\nusemtl body\nv 0 0 0\n')
    (tmp_path / 'goku.MTL').write_text('newmtl body\nmap_Kd -s 1 1 1 -bm 0.5 C:\\rip\\tex\\Body.png\n'
                                       'map_Kd textures/Face Front.png\nmap_Bump normal.png\n')
    (tmp_path / 'body.png').write_bytes(b'png')
    gap = textures.missing(tmp_path / 'Goku.obj')
    assert gap['missing'] == ['Face Front.png'], 'names compare without case or folders; only colour maps count'
    (tmp_path / 'Face Front.png').write_bytes(b'png')
    assert textures.missing(tmp_path / 'Goku.obj') is None


def test_a_dae_names_its_images_and_carries_data_uris_itself(tmp_path):
    model = tmp_path / 'Isabelle.dae'
    model.write_text('<COLLADA><library_images>'
                     '<image id="a"><init_from>file:///C:/rip/Isabelle%20Body.png</init_from></image>'
                     '<image id="b"><init_from><ref>eyes.png</ref></init_from></image>'
                     '<image id="c"><init_from>data:image/png;base64,AAAA</init_from></image>'
                     '</library_images></COLLADA>')
    assert textures.missing(model)['missing'] == ['Isabelle Body.png', 'eyes.png']
    (tmp_path / 'isabelle body.png').write_bytes(b'png')
    (tmp_path / 'EYES.PNG').write_bytes(b'png')
    assert textures.missing(model) is None


@pytest.mark.parametrize('version', [7400, 7500])
def test_an_fbx_is_flagged_only_for_textures_it_does_not_carry(tmp_path, version):
    model = tmp_path / 'Scorpion.fbx'
    model.write_bytes(_fbx([_video('C:\\rip\\Face.png', content=b'\x89PNG embedded'),
                            _texture('C:\\rip\\Face.png', 'Face.png'), _texture('E:\\work\\Body.tga')], version))
    gap = textures.missing(model)
    assert gap['missing'] == ['Body.tga'], 'Face.png is embedded media (a Video with Content)'
    (tmp_path / 'Body.tga').write_bytes(b'tga')
    assert textures.missing(model) is None
    embedded = tmp_path / 'all' / 'Embedded.fbx'
    embedded.parent.mkdir()
    embedded.write_bytes(_fbx([_video('Body.tga', content=b'tga bytes'), _texture('Body.tga')], version))
    assert textures.missing(embedded) is None


def test_an_ascii_fbx_is_read_too(tmp_path):
    model = tmp_path / 'Kritter.fbx'
    model.write_text('; FBX 7.3.0 project file\nObjects:  {\n'
                     '\tVideo: 1, "Video::a", "Clip" {\n\t\tFileName: "C:\\\\rip\\\\inside.png"\n'
                     '\t\tContent: , "iVBORw0KGgo="\n\t}\n'
                     '\tTexture: 2, "Texture::b", "" {\n\t\tFileName: "C:\\\\rip\\\\outside.png"\n\t}\n}\n')
    assert textures.missing(model)['missing'] == ['outside.png']


def test_a_gltf_without_its_buffer_cannot_be_read_at_all(tmp_path):
    model = tmp_path / 'Barbarian.gltf'
    model.write_text(json.dumps({'buffers': [{'uri': 'Barbarian.bin', 'byteLength': 4}],
                                 'images': [{'uri': 'tex%20a.png'}, {'uri': 'data:image/png;base64,AA'}]}))
    gap = textures.missing(model)
    assert gap['missing'] == ['Barbarian.bin', 'tex a.png']
    assert textures.warning(gap) == ('Barbarian.gltf came without the data file Barbarian.bin and the texture '
                                     'tex a.png. Without them the model cannot be read.')


@pytest.mark.parametrize('name', ['model.glb', 'model.smd', 'broken.fbx', 'broken.dae'])
def test_what_the_check_cannot_read_or_that_carries_everything_is_never_flagged(tmp_path, name):
    model = tmp_path / name
    model.write_bytes(b'Kaydara FBX Binary  \x00\x1a\x00\xff\xff\xff\xff garbage' if name.endswith('.fbx')
                      else b'glTF\x02\x00\x00\x00' if name.endswith('.glb') else b'\x00\x01 not a model')
    assert textures.missing(model) is None


# ------------------------------------------------------------------ a ZIP: anywhere inside it

def test_a_zip_is_looked_into_by_name_in_any_folder(tmp_path):
    archive = tmp_path / 'Golduck.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('Golduck/golduck.obj', 'mtllib golduck.mtl\nv 0 0 0\n')
        z.writestr('Golduck/golduck.mtl', 'newmtl a\nmap_Kd body.png\nnewmtl b\nmap_Kd eyes.png\n')
        z.writestr('Golduck/textures/body.png', b'png')
    gap = textures.missing(archive)
    assert gap == dict(model='Golduck/golduck.obj', missing=['eyes.png'], source='Golduck.zip', archive=True)
    assert textures.warning(gap) == ('Golduck/golduck.obj in Golduck.zip came without the texture eyes.png: the ZIP '
                                     'does not hold it. Without it the model would import with no textures '
                                     '(all white).')
    with zipfile.ZipFile(archive, 'a') as z:
        z.writestr('eyes.png', b'png')
    assert textures.missing(archive) is None


class _PosixOs:
    """The os module as zipfile sees it on Linux and macOS: '/' its only separator."""
    sep, altsep, path = '/', None, posixpath

    def __getattr__(self, name):
        return getattr(os, name)


def _compress_archive_zip(path, entries):
    """A ZIP as Windows PowerShell's Compress-Archive writes one: folders split by backslashes. Each name is written
    as given (zipfile itself would turn the backslash into '/' on Windows)."""
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo('entry')
            info.filename = name
            z.writestr(info, data)
    return path


def test_a_zip_with_backslash_folders_is_read_as_on_windows_on_every_platform(tmp_path, monkeypatch):
    """0.9.0 build 3 Linux smoke: Clank.zip from Compress-Archive (Clank\\Clank.obj, Clank\\Clank.mtl) got
    "names files the ZIP does not hold: Clank.mtl". zipfile keeps a backslash in a name where os.sep is '/', so
    this reads the ZIP with zipfile as it is on Linux and macOS, on any platform."""
    monkeypatch.setattr(zipfile, 'os', _PosixOs())
    archive = _compress_archive_zip(tmp_path / 'Clank.zip', {
        'Clank\\': b'', 'Clank\\Clank.obj': b'mtllib Clank.mtl\r\no Clank\r\nv 0 0 0\r\n',
        'Clank\\Clank.mtl': b'newmtl a\r\nmap_Kd tex\\Clank_D.png\r\n', 'Clank\\tex\\Clank_D.png': b'png'})
    with zipfile.ZipFile(archive) as z:
        assert 'Clank\\Clank.obj' in z.namelist(), 'zipfile kept the backslash, as on Linux'
    assert textures.missing(archive) is None
    lacking = _compress_archive_zip(tmp_path / 'Lacking.zip', {
        'Clank\\Clank.obj': b'mtllib Clank.mtl\nv 0 0 0\n', 'Clank\\Clank.mtl': b'newmtl a\nmap_Kd Clank_D.png\n'})
    assert textures.missing(lacking) == dict(model='Clank/Clank.obj', missing=['Clank_D.png'], source='Lacking.zip',
                                             archive=True)


def test_an_entry_path_splits_on_either_slash():
    assert textures.entry_path('Clank\\tex\\body.png').parts == ('Clank', 'tex', 'body.png')
    assert textures.entry_path('Clank/tex/body.png').name == 'body.png'
    assert str(textures.entry_path('Clank\\Clank.obj').parent) == 'Clank'


def test_the_warning_lists_a_few_names_and_counts_the_rest():
    gap = dict(model='Sonic.dae', missing=[f'tex{n}.png' for n in range(9)], source='Sonic.dae', archive=False)
    assert textures.warning(gap).startswith('Sonic.dae came without the textures tex0.png, tex1.png, ')
    assert 'tex5.png and 3 more. Without them' in textures.warning(gap)


def test_the_warning_names_each_missing_file_for_what_it_is():
    """An OBJ's .mtl is its materials file and a glTF's .bin its data, never "a texture" (0.9.0 smoke)."""
    assert [textures.kind(n) for n in ('Clank.mtl', 'CLANK.MTL', 'scene.bin', 'Body.png', 'face.TGA', 'skin')] == \
        ['materials', 'materials', 'data', 'texture', 'texture', 'texture']
    two = dict(model='Mech.obj', missing=['body.mtl', 'arms.mtl'], source='Mech.obj', archive=False)
    assert textures.warning(two) == ('Mech.obj came without the materials files body.mtl, arms.mtl. Without them the '
                                     'model would import with no textures (all white).')
    # A ZIP whose model has one materials file and lacks another's textures: both named, materials first.
    mixed = dict(model='Goku/goku.obj', missing=['eyes.png', 'hair.mtl', 'face.png'], source='Goku.zip', archive=True)
    assert textures.warning(mixed) == ('Goku/goku.obj in Goku.zip came without the materials file hair.mtl and the '
                                       'textures eyes.png, face.png: the ZIP does not hold them. Without them the '
                                       'model would import with no textures (all white).')
    assert 'texture file' not in textures.warning(dict(model='Clank.obj', missing=['Clank.mtl'], source='Clank.obj'))
