import io
import struct
import zipfile
from pathlib import Path

import pytest
from randall.assistant import tools, vault_items
from shared import mod_files
from randall.assistant.hsdraw import hsdraw
from core import config


def dat():
    symbol = b'PlyMarth5K_Share_joint\0'
    body = bytes(64)
    return struct.pack('>5I', 32 + len(body) + 8 + len(symbol), len(body), 0, 1, 0) + bytes(12) + body + struct.pack('>II', 0, 0) + symbol


def seed(vault):
    vault.write({'characters': {'Marth': {'skins': [
        {'id': 'original', 'name': 'Original Marth', 'filename': 'original.zip', 'costume_code': 'PlMsGr'}]}}})
    path = vault.path('Marth', 'original.zip')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('PlMsGr.dat', dat())
        archive.writestr('readme.txt', 'keep me')
    return path


def test_vault_opens_independent_archive_and_dat(vault):
    original = seed(vault)
    before = original.read_bytes()
    result = vault_items.open_vault_file('Marth', 'original')
    assert len(result['files']) == 2
    dat_file = result['files'][1]
    assert mod_files.inspect_mod_file(dat_file['file_id'])['roots'] == ['PlyMarth5K_Share_joint']
    original.write_bytes(b'changed later')
    assert mod_files.resolve(dat_file['file_id'])[0].read_bytes() == dat()
    assert mod_files.resolve(result['files'][0]['file_id'])[0].read_bytes() == before


@pytest.mark.parametrize('file_id', ['../metadata.json', 'C:/Users/me/file.dat', 'a' * 31, None, True])
def test_file_ids_cannot_be_paths(vault, file_id):
    with pytest.raises(ValueError):
        mod_files.resolve(file_id)


def test_zip_member_paths_are_bytes_not_extracted(vault):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('../../escape.dat', dat())
    handle = mod_files.register(buffer.getvalue(), 'pack.zip')
    result = mod_files.unpack_file(handle['file_id'], '../../escape.dat')
    assert result['files'][0]['name'] == 'escape.dat'
    assert not (vault.storage / 'escape.dat').exists()
    with pytest.raises(ValueError):
        mod_files.unpack_file(handle['file_id'], '/unlisted.dat')


def test_tampered_copy_and_malformed_dat_fail(vault):
    file = mod_files.register(dat(), 'test.dat')
    path, _ = mod_files.resolve(file['file_id'])
    path.write_bytes(b'bad')
    with pytest.raises(ValueError, match='changed'):
        mod_files.resolve(file['file_id'])
    bad = mod_files.register(b'not a DAT', 'bad.dat')
    with pytest.raises(ValueError, match='header'):
        mod_files.inspect_mod_file(bad['file_id'])


def test_headless_arguments_fixed_and_edits_chain_copies(vault, monkeypatch):
    import importlib
    module = importlib.import_module('randall.assistant.hsdraw')
    original = seed(vault)
    before = original.read_bytes()
    file = vault_items.open_vault_file('Marth', 'original')['files'][1]
    calls = []
    def run(argv, directory):
        calls.append(argv)
        assert argv[0] == '--remove-dobjs'
        assert Path(argv[1]).is_relative_to(directory)
        Path(argv[-1]).write_bytes(Path(argv[1]).read_bytes())
        return 'SUCCESS: wrote a working copy'
    monkeypatch.setattr(module, '_run', run)
    first = hsdraw('remove_meshes', file['file_id'], node='GrNKr_joint', indices=[0])['files'][0]
    second = hsdraw('remove_meshes', first['file_id'], node='GrNKr_joint', indices=[0])['files'][0]
    # A fighter costume's meshes are addressed by position in the game's model
    # tables: deleting one would show the wrong pieces in game.
    with pytest.raises(ValueError, match='shifts the mesh indices'):
        hsdraw('remove_meshes', file['file_id'], node='PlyMarth5K_Share_joint', indices=[0])
    assert len({file['file_id'], first['file_id'], second['file_id']}) == 3
    assert original.read_bytes() == before
    assert mod_files.resolve(file['file_id'])[0].read_bytes() == dat()
    assert all(Path(call[-1]).name == 'result.dat' for call in calls)
    for kwargs in [{'node': '../../outside', 'indices': [0]}, {'node': 'root', 'indices': [-1]},
                   {'node': 'root', 'indices': [True]}, {'node': 'root', 'indices': [], 'mesh_index': 1}]:
        with pytest.raises(ValueError):
            hsdraw('remove_meshes', file['file_id'], **kwargs)
    with pytest.raises(ValueError):
        hsdraw('--stream', file['file_id'])


def test_missing_output_is_not_success(vault, monkeypatch):
    import importlib
    module = importlib.import_module('randall.assistant.hsdraw')
    monkeypatch.setattr(module, '_run', lambda *args: 'Usage: something')
    file = mod_files.register(dat(), 'test.dat')
    with pytest.raises(ValueError, match='did not produce'):
        hsdraw('export_texture', file['file_id'], node='root', texture_index=0)


@pytest.mark.parametrize('vanilla_source', [False, True])
def test_save_copy_cannot_overwrite_existing_vault_file(vault, monkeypatch, vanilla_source):
    import importlib
    module = importlib.import_module('randall.assistant.hsdraw')
    from vault.importing.unified import characters
    from core.metadata import metadata_transaction
    original = seed(vault)
    before = original.read_bytes()
    file = vault_items.open_vault_file('Marth', 'original')['files'][1]
    source, info = mod_files.resolve(file['file_id'])
    origin = ({'character': 'Marth', 'vanilla_color': 'Gr', 'costume_code': 'PlMsGr'} if vanilla_source else info['origin'])
    edited = mod_files.register(source.read_bytes(), 'edited.dat', origin=origin, edited=True)
    names = []
    def importer(path, char_info, filename, **kwargs):
        names.append(kwargs['custom_name'])
        assert kwargs['auto_fix'] is False
        assert Path(path) != original
        with zipfile.ZipFile(path) as archive:
            assert archive.namelist() == ['PlMsGr.dat']
        with metadata_transaction() as metadata:
            metadata['characters']['Marth']['skins'].append({'id': f'copy{len(names)}', 'name': kwargs['custom_name']})
        return {'success': True, 'skin_id': f'copy{len(names)}'}
    monkeypatch.setattr(characters, 'import_character_costume', importer)
    for _ in range(2):
        result = module.save_mod_copy(edited['file_id'], 'Edited Marth')
        assert result['vault_changed']
    assert names[0] != names[1]
    assert original.read_bytes() == before
    assert vault.read()['characters']['Marth']['skins'][0]['name'] == 'Original Marth'
    assert 'save_mod_edit' not in tools.REGISTRY
    assert tools.prepare('save_mod_copy', {'file_id': edited['file_id'], 'name': 'Copy'}).policy == 'automatic'
    with pytest.raises(ValueError):
        module.save_mod_copy(file['file_id'], 'Not an edit')


def test_upload_download_api_uses_owned_file_ids(vault, monkeypatch):
    import importlib
    assistant_bp = importlib.import_module('randall.routes.assistant_bp')
    monkeypatch.setattr(assistant_bp.gates, 'enabled', lambda name: True)
    client = vault.client(assistant_bp, 'assistant_bp')
    result = client.post('/api/assistant/files', data={'file': (io.BytesIO(dat()), '../../sample.dat')})
    assert result.status_code == 200
    file = result.json['file']
    assert file['name'] == 'sample.dat'
    response = client.get('/api/assistant/files/' + file['file_id'])
    assert response.data == dat()
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert client.post('/api/assistant/files', data={'file': (io.BytesIO(b'bad'), 'run.exe')}).status_code == 400


def test_an_fbx_attaches_like_every_other_model(vault, monkeypatch):
    """0.9.0 smoke test: the chat refused Scorpion.fbx with a 400 while the import itself reads FBX."""
    import importlib
    assistant_bp = importlib.import_module('randall.routes.assistant_bp')
    monkeypatch.setattr(assistant_bp.gates, 'enabled', lambda name: True)
    client = vault.client(assistant_bp, 'assistant_bp')
    result = client.post('/api/assistant/files', data={'file': (io.BytesIO(b'Kaydara FBX Binary  \0'), 'Scorpion.FBX')})
    assert result.status_code == 200, result.json
    assert result.json['file']['extension'] == '.fbx'
    assert mod_files.inspect_mod_file(result.json['file']['file_id'])['note'].startswith('Model or animation asset')
    refused = client.post('/api/assistant/files', data={'file': (io.BytesIO(b'bad'), 'run.exe')})
    assert 'FBX' in refused.json['error']


def test_the_chat_file_input_takes_exactly_the_attachable_kinds():
    """mod_files.EXTENSIONS is the one list: the chat's file picker offers the same kinds, no more and no fewer."""
    import re
    from tests.paths import APP
    panel = (APP / 'frontend' / 'src' / 'randall' / 'assistant' / 'AssistantPanel.jsx').read_text(encoding='utf-8')
    accept = re.search(r'<input ref=\{fileInput\} type="file"[^>]*?accept="([^"]+)"', panel).group(1)
    assert set(accept.split(',')) == mod_files.EXTENSIONS


def test_real_hsdraw_mesh_inspection(vault):
    if not Path(config.HSDRAW_EXE).is_file():
        pytest.skip('HSDRaw executable not installed')
    file = mod_files.register(dat(), 'empty-model.dat')
    result = hsdraw('meshes', file['file_id'], node='PlyMarth5K_Share_joint')
    assert '[]' in result['log']
    assert mod_files.resolve(file['file_id'])[0].read_bytes() == dat()


def test_real_texture_export_replace_and_original_preservation(vault):
    if not Path(config.HSDRAW_EXE).is_file():
        pytest.skip('HSDRaw executable not installed')
    from PIL import Image
    body = bytearray(288)
    pointers = {0x10: 64, 64 + 8: 80, 80 + 8: 104, 104 + 0x4c: 200, 200: 224}
    for offset, value in pointers.items():
        struct.pack_into('>I', body, offset, value)
    struct.pack_into('>HHI', body, 204, 4, 4, 6)
    body[224:] = b'\xff' * 64
    symbol = b'PlyMarth5K_Share_joint\0'
    relocs = b''.join(struct.pack('>I', offset) for offset in pointers)
    raw = struct.pack('>5I', 32 + len(body) + len(relocs) + 8 + len(symbol), len(body), len(pointers), 1, 0) + bytes(12) + body + relocs + struct.pack('>II', 0, 0) + symbol
    source = mod_files.register(raw, 'textured.dat')
    inspection = mod_files.inspect_mod_file(source['file_id'])
    assert inspection['textures'] == [{'node': 'PlyMarth5K_Share_joint', 'texture_index': 0, 'width': 4, 'height': 4, 'format': 'RGBA8'}]
    exported = hsdraw('export_texture', source['file_id'], node=inspection['roots'][0], texture_index=0)['files'][0]
    with Image.open(mod_files.resolve(exported['file_id'])[0]) as image:
        assert image.convert('RGBA').getpixel((0, 0)) == (255, 255, 255, 255)
    buffer = io.BytesIO()
    Image.new('RGBA', (4, 4), (255, 0, 0, 255)).save(buffer, format='PNG')
    replacement = mod_files.register(buffer.getvalue(), 'red.png')
    changed = hsdraw('replace_texture', source['file_id'], node=inspection['roots'][0], texture_index=0,
                     replacement_file_id=replacement['file_id'])['files'][0]
    rendered = hsdraw('export_texture', changed['file_id'], node=inspection['roots'][0], texture_index=0)['files'][0]
    with Image.open(mod_files.resolve(rendered['file_id'])[0]) as image:
        assert image.convert('RGBA').getpixel((0, 0)) == (255, 0, 0, 255)
    assert mod_files.resolve(source['file_id'])[0].read_bytes() == raw


def test_an_unpacked_member_records_the_archive_it_came_from(vault):
    """A model unpacked alone leaves its textures behind; the fitter has to be
    able to name the ZIP to go back to."""
    import io, zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('rig/model.dae', '<COLLADA/>')
        archive.writestr('rig/skin.png', 'x')
    zipped = mod_files.register(buffer.getvalue(), 'rip.zip')
    member = mod_files.unpack_file(zipped['file_id'], 'rig/model.dae')['files'][0]
    _, info = mod_files.resolve(member['file_id'])
    assert info['origin']['archive_file_id'] == zipped['file_id']
    assert info['origin']['member'] == 'rig/model.dae'


def _pack(members, *, origin=None):
    """A ZIP attachment holding `members` ({name: bytes}, in that order), registered the way uploads are."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    buffer.seek(0)
    return mod_files.register_stream(buffer, 'pack.zip', origin=origin)


RIGGED_DAE = b'<COLLADA><node type="JOINT"/><node type="JOINT"/><skin/></COLLADA>'


def test_a_member_unpacks_from_a_zip_whose_origin_is_a_plain_label(vault):
    """GLM smoke run: unpack_mod_file on an upload tagged origin='studio_randall_run' failed with
    "'str' object is not a mapping", twice, and the model gave up on the archive."""
    zipped = _pack({'Pack/Female/Body.dae': RIGGED_DAE, 'Pack/Female/images/skin.png': b'x'},
                   origin='studio_randall_run')
    result = tools.REGISTRY['unpack_mod_file'].run(file_id=zipped['file_id'], member='Pack/Female/Body.dae')
    unpacked = result['files'][0]
    assert unpacked['name'] == 'Body.dae'
    path, info = mod_files.resolve(unpacked['file_id'])
    assert path.read_bytes() == RIGGED_DAE
    assert info['origin'] == {'source': 'studio_randall_run', 'archive_file_id': zipped['file_id'],
                              'member': 'Pack/Female/Body.dae'}


def test_origin_of_is_always_a_dict():
    assert mod_files.origin_of({'origin': {'character': 'Fox'}}) == {'character': 'Fox'}
    assert mod_files.origin_of({'origin': 'model_import_v2'}) == {'source': 'model_import_v2'}
    assert mod_files.origin_of({'origin': None}) == {} == mod_files.origin_of({})


def test_the_zip_listing_puts_models_first_and_counts_what_the_cap_leaves_out(vault):
    """A game-rip pack: hundreds of textures in archive order before the models, plus an .fbx copy
    of a model (a model like the others since 0.9.0's smoke test) and a .blend no tool here opens.
    The 200-member cap used to cut the listing inside the textures, so the body models never showed."""
    members = {f'Pack/Clothes/images/t{i:03d}.png': b'x' for i in range(150)}
    members.update({f'Pack/Masks/m{i:03d}.png': b'x' for i in range(100)})
    members.update({'Pack/Female/Body.dae': RIGGED_DAE, 'Pack/Female/Body.fbx': b'fbx', 'Pack/readme.txt': b'hi',
                    'Pack/Female/Body.blend': b'BLENDER', 'Pack/Female/Hair.obj': b'v 0 0 0'})
    listing = tools.REGISTRY['inspect_mod_file'].run(file_id=_pack(members)['file_id'])
    names = [m['name'] for m in listing['members']]
    assert names[:3] == ['Pack/Female/Body.dae', 'Pack/Female/Body.fbx', 'Pack/Female/Hair.obj']
    assert listing['members'][0]['rig'] == '2 bones, skin weights' and listing['members'][2]['rig'] == 'none'
    assert len(names) == mod_files.LISTED_MEMBERS and listing['truncated'] is True
    assert listing['total_members'] == 253 and listing['models'] == 3
    assert names[3] == 'Pack/Clothes/images/t000.png'                     # then the rest, in archive order
    assert listing['unlisted_by_folder'] == {'Pack/Masks': 53}
    assert listing['not_openable'] == {'.blend': 1, '.txt': 1}
    assert 'unlisted_by_folder' in listing['note'] and 'not_openable' in listing['note']


def test_a_short_zip_listing_has_no_counts_or_note(vault):
    listing = mod_files.inspect_mod_file(_pack({'a/model.dae': RIGGED_DAE, 'a/skin.png': b'x'})['file_id'])
    assert [m['name'] for m in listing['members']] == ['a/model.dae', 'a/skin.png']
    assert listing['truncated'] is False and listing['models'] == 1
    assert not {'unlisted_by_folder', 'not_openable', 'note'} & set(listing)


@pytest.mark.parametrize('member, says', [
    ('Pack\\Female\\Body.dae', ['member', 'forward slashes', 'Closest: "Pack/Female/Body.dae"']),
    ('pack/female/body.dae', ['member', 'Closest: "Pack/Female/Body.dae"']),
    ('Body.dae', ['member', 'Closest: "Pack/Female/Body.dae"']),
    ('Pack/Female/Body.blend', ['member', '.blend files cannot be opened', '"Pack/Female/Body.dae"']),
    ('Pack/Female/', ['member', 'is a folder', '"Pack/Female/Body.dae"']),
    ('nothing-like-it.xyz', ['member', "inspect_mod_file's members", '"member": "Pack/Female/Body.dae"']),
    (['Pack/Female/Body.dae'], ['member must be one member name as a string', '"member": "Pack/Female/Body.dae"']),
    (None, ['member must be one member name as a string']),
])
def test_a_member_that_cannot_open_names_the_argument_and_the_valid_form(vault, member, says):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('Pack/Female/', b'')                   # an explicit folder entry, as many packers write
        archive.writestr('Pack/Female/Body.dae', RIGGED_DAE)
        archive.writestr('Pack/Female/Body.blend', b'BLENDER')
        archive.writestr('Pack/Female/images/skin.png', b'x')
    zipped = mod_files.register(buffer.getvalue(), 'pack.zip', origin='studio_randall_run')
    with pytest.raises(ValueError) as error:
        tools.REGISTRY['unpack_mod_file'].run(file_id=zipped['file_id'], member=member)
    for text in says:
        assert text in str(error.value)


def test_a_file_id_that_is_not_a_zip_or_not_an_id_is_named(vault):
    model = mod_files.register(RIGGED_DAE, 'Body.dae')
    with pytest.raises(ValueError, match=r'file_id "[0-9a-f]{32}" is Body.dae \(.dae\), not a ZIP.*"member"'):
        mod_files.unpack_file(model['file_id'], 'Body.dae')
    with pytest.raises(ValueError, match=r"file_id 'pack.zip' is not a file ID.*32 lowercase hex"):
        mod_files.unpack_file('pack.zip', 'Body.dae')
    with pytest.raises(ValueError, match=r'file_id "a{32}" is unavailable'):
        mod_files.inspect_mod_file('a' * 32)


def test_a_plain_label_dat_edits_and_is_refused_in_the_tools_own_words(vault, monkeypatch):
    """A model import's costume is registered with a plain label as its origin ('model_import_v2'), not the
    vault's dict. An HSDRaw edit of it is a working copy like any other (it used to be saved, then reported
    as a failure), and the clone and in-game test tools refuse it with their own sentence."""
    import shutil
    from PIL import Image
    from randall.assistant import clone_character, hsdraw as hsdraw_module
    from randall.delivery import game_tests
    def fake_hsdraw(argv, directory):
        shutil.copyfile(argv[2], argv[-1])        # --texture import <input> <node> <index> <png> <output>
        return 'imported'
    monkeypatch.setattr(hsdraw_module, '_run', fake_hsdraw)
    plain = mod_files.register(dat(), 'PlMsGr.dat', origin='model_import_v2')
    buffer = io.BytesIO()
    Image.new('RGBA', (4, 4), (255, 0, 0, 255)).save(buffer, format='PNG')
    red = mod_files.register(buffer.getvalue(), 'red.png')
    result = tools.execute(tools.prepare('hsdraw', {'operation': 'replace_texture', 'file_id': plain['file_id'],
        'node': 'PlyMarth5K_Share_joint', 'texture_index': 0, 'replacement_file_id': red['file_id']}))
    assert 'error' not in result, result
    assert result['can_save_to_vault'] is False
    edited = mod_files.resolve(result['files'][0]['file_id'])[1]
    assert edited['edited'] and edited['origin'] == 'model_import_v2'
    with pytest.raises(ValueError, match='Export the fitted model'):
        clone_character._source(plain['file_id'])
    with pytest.raises(ValueError, match='known target fighter'):
        game_tests._target('file', file_id=plain['file_id'])


# --- archives over 128 MB (Rapunzel, 2026-09): moved from the old intake round-16 tests ---------------

def test_a_zip_over_the_file_limit_is_stored_by_stream_and_resolves(vault, monkeypatch):
    monkeypatch.setattr(mod_files, 'MAX_FILE', 1000)
    monkeypatch.setattr(mod_files, 'MAX_ARCHIVE', 50_000)
    monkeypatch.setattr(mod_files, 'STREAM_CHUNK', 4096)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('model/big.dae', b'x' * 20_000)
    data = buffer.getvalue()
    assert mod_files.MAX_FILE < len(data) < mod_files.MAX_ARCHIVE
    stored = mod_files.register_stream(io.BytesIO(data), 'Rapunzel.zip')
    path, info = mod_files.resolve(stored['file_id'])
    assert path.read_bytes() == data and info['size'] == len(data)
    assert mod_files.register(data, 'again.zip')['size'] == len(data)
    # anything else keeps the file limit
    with pytest.raises(ValueError, match='128 MB'):
        mod_files.register_stream(io.BytesIO(b'y' * 2000), 'model.dae')
    # ...and a ZIP over the archive limit is refused mid-stream, says what to re-zip, leaves nothing behind
    before = set(mod_files.root().iterdir())
    with pytest.raises(ValueError, match='only the model you want'):
        mod_files.register_stream(io.BytesIO(b'z' * 60_000), 'huge.zip')
    assert set(mod_files.root().iterdir()) == before


def test_the_upload_route_streams_a_big_zip(vault, monkeypatch):
    import importlib
    assistant_bp = importlib.import_module('randall.routes.assistant_bp')
    monkeypatch.setattr(assistant_bp.gates, 'enabled', lambda name: True)
    monkeypatch.setattr(mod_files, 'MAX_FILE', 1000)
    client = vault.client(assistant_bp, 'assistant_bp')
    result = client.post('/api/assistant/files', data={'file': (io.BytesIO(b'PK' + b'x' * 5000), 'rip.zip')})
    assert result.status_code == 200, result.json
    assert result.json['file']['size'] == 5002



def test_a_failed_metadata_write_leaves_no_upload_behind(vault, monkeypatch):
    # Astra [P2]: up to 1 GB orphaned when metadata.json could not be written

    class Broken:
        @staticmethod
        def dumps(*a, **k):
            raise OSError('disk full')
    before = set(mod_files.root().iterdir())
    monkeypatch.setattr(mod_files, 'json', Broken)
    with pytest.raises(OSError):
        mod_files.register_stream(io.BytesIO(b'PK' + b'x' * 5000), 'rip.zip')
    with pytest.raises(OSError):
        mod_files.register(b'PK' + b'x' * 5000, 'rip.zip')
    assert set(mod_files.root().iterdir()) == before


def test_a_dat_read_never_takes_more_than_the_dat_limit(tmp_path, monkeypatch):
    # a ZIP attachment may now be 1 GB; hsdraw/stage_scene call dat_roots on any file ID
    path = tmp_path / "costume.dat"
    path.write_bytes(dat())
    assert mod_files.dat_roots(path)
    monkeypatch.setattr(mod_files, "MAX_FILE", len(dat()) - 1)
    with pytest.raises(ValueError):
        mod_files.dat_roots(path)
