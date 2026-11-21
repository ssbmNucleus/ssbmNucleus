"""Paired editor sources must preserve custom Nana bytes and canonical colors."""
import base64
from pathlib import Path
import shutil
import uuid
import zipfile

from flask import Flask
import pytest

import shared.routes.viewer as viewer
import core.metadata as metadata_module
import core.viewer_tools as viewer_tools
from shared.rendering.paint_pair import find_paint_partner, nana_from_zip
from tests.left_out import require


@pytest.fixture
def tmp_path():
    # Ordinary mkdir also works with the Windows workspace ACL (mode 0700 does not).
    root = Path(__file__).parent / ('.tmp-paint-pair-' + uuid.uuid4().hex)
    root.mkdir()
    yield root
    assert root.parent.resolve() == Path(__file__).parent.resolve()
    shutil.rmtree(root)


@pytest.fixture
def editor(tmp_path, monkeypatch):
    vanilla, storage = tmp_path / 'vanilla', tmp_path / 'storage'
    vanilla.mkdir()
    storage.mkdir()
    # The routes read these in the blueprint; the costume/AJ/data lookups they
    # call read them in core.viewer_tools.
    for module in (viewer, viewer_tools):
        monkeypatch.setattr(module, 'VANILLA_ASSETS_DIR', vanilla)
        monkeypatch.setattr(module, 'STORAGE_PATH', storage)
    monkeypatch.setattr(viewer, 'find_scene_file', lambda _: None)
    monkeypatch.setattr(viewer, 'find_aj_file', lambda _: None)
    monkeypatch.setattr(viewer, 'find_fighter_data_file', lambda _: None)
    monkeypatch.setattr(metadata_module, 'load_metadata', lambda **_: {})

    def make_temp(**_):
        path = tmp_path / uuid.uuid4().hex
        path.mkdir()
        return str(path)
    monkeypatch.setattr(viewer.tempfile, 'mkdtemp', make_temp)
    app = Flask(__name__)
    app.register_blueprint(viewer.viewer_bp)
    return app.test_client(), vanilla, storage


def _vanilla(root, character, code, content):
    folder = root / character / code
    folder.mkdir(parents=True)
    path = folder / (code + '.dat')
    path.write_bytes(content)
    return path


def _archive(root, filename, dat_name, content):
    path = root / 'Ice Climbers' / filename
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(dat_name, content)
    return path


@pytest.mark.parametrize('popo,nana', [('Nr', 'Nr'), ('Re', 'Wh'), ('Or', 'Aq'), ('Gr', 'Ye')])
def test_vanilla_editor_resolves_correct_color_pair(editor, popo, nana):
    client, vanilla, _ = editor
    _vanilla(vanilla, 'Ice Climbers', 'PlPp' + popo, b'popo')
    _vanilla(vanilla, 'Nana', 'PlNn' + nana, b'nana')
    response = client.post('/api/mex/viewer/paths-vanilla', json={
        'character': 'Ice Climbers', 'costumeCode': 'PlPp' + popo, 'paintPair': True})
    assert response.status_code == 200
    members = response.json['members']
    assert [member['memberId'] for member in members] == ['popo', 'nana']
    assert [member['name'] for member in members] == ['Popo', 'Nana']
    assert [member['datName'] for member in members] == ['PlPp' + popo + '.dat', 'PlNn' + nana + '.dat']
    assert [base64.b64decode(member['datBase64']) for member in members] == [b'popo', b'nana']


def test_vault_editor_preserves_custom_partner_over_vanilla(editor, monkeypatch):
    client, vanilla, storage = editor
    _archive(storage, 'popo.zip', 'PlPpRe.dat', b'custom-popo')
    _archive(storage, 'nana.zip', 'nested/PlNnWh.dat', b'custom-nana')
    _vanilla(vanilla, 'Nana', 'PlNnWh', b'vanilla-nana')
    monkeypatch.setattr(metadata_module, 'load_metadata', lambda **_: {'characters': {
        'Ice Climbers': {'skins': [
            {'id': 'popo', 'paired_nana_id': 'nana'},
            {'id': 'nana', 'filename': 'nana.zip'}]}}})
    response = client.post('/api/mex/viewer/paths-vault', json={
        'character': 'Ice Climbers', 'costumeId': 'popo', 'paintPair': True})
    assert response.status_code == 200
    member = response.json['members'][1]
    assert member['memberId'] == 'nana'
    assert base64.b64decode(member['datBase64']) == b'custom-nana'
    assert Path(member['datFile']).read_bytes() == b'custom-nana'


def test_missing_explicit_partner_does_not_silently_replace_custom_nana(editor, monkeypatch):
    client, vanilla, storage = editor
    _archive(storage, 'popo.zip', 'PlPpRe.dat', b'custom-popo')
    _vanilla(vanilla, 'Nana', 'PlNnWh', b'vanilla-nana')
    monkeypatch.setattr(metadata_module, 'load_metadata', lambda **_: {'characters': {
        'Ice Climbers': {'skins': [{'id': 'popo', 'paired_nana_id': 'missing'}]}}})
    response = client.post('/api/mex/viewer/paths-vault', json={
        'character': 'Ice Climbers', 'costumeId': 'popo', 'paintPair': True})
    assert response.status_code != 200
    assert 'paired Nana costume is missing' in response.json['error']


def test_unpaired_popo_uses_correct_vanilla_partner(editor):
    client, vanilla, storage = editor
    _archive(storage, 'popo.zip', 'PlPpGrMod.dat', b'custom-popo')
    _vanilla(vanilla, 'Nana', 'PlNnYe', b'vanilla-yellow-nana')
    response = client.post('/api/mex/viewer/paths-vault', json={
        'character': 'Ice Climbers', 'costumeId': 'popo', 'paintPair': True})
    assert response.status_code == 200
    assert base64.b64decode(response.json['members'][1]['datBase64']) == b'vanilla-yellow-nana'


def test_regular_viewer_requires_both_climbers(editor):
    client, vanilla, _ = editor
    _vanilla(vanilla, 'Ice Climbers', 'PlPpRe', b'popo')
    response = client.post('/api/mex/viewer/paths-vanilla', json={
        'character': 'Ice Climbers', 'costumeCode': 'PlPpRe'})
    assert response.status_code == 500
    assert 'No paired Nana' in response.json['error']


def test_combined_sources_keep_member_specific_scene_and_fighter_data(editor, monkeypatch):
    client, vanilla, _ = editor
    popo = _vanilla(vanilla, 'Ice Climbers', 'PlPpNr', b'popo')
    nana = _vanilla(vanilla, 'Nana', 'PlNnNr', b'nana')
    scenes = {name: vanilla / (name + '.yml')
              for name in ['Ice Climbers (Popo)', 'Ice Climbers (Nana)']}
    monkeypatch.setattr(viewer, 'find_scene_file', scenes.get)
    monkeypatch.setattr(viewer, 'find_fighter_data_file',
                        lambda name: vanilla / ('PlNn.dat' if name == 'Nana' else 'PlPp.dat'))
    response = client.post('/api/mex/viewer/paths-vanilla', json={
        'character': 'Ice Climbers', 'costumeCode': 'PlPpNr', 'paintPair': True})
    assert response.status_code == 200
    members = response.json['members']
    assert [m['memberId'] for m in members] == ['popo', 'nana']
    assert [m['datFile'] for m in members] == [viewer.to_windows_path(popo), viewer.to_windows_path(nana)]
    assert [m['sceneFile'] for m in members] == [viewer.to_windows_path(p) for p in scenes.values()]
    assert [Path(m['dataFile']).name for m in members] == ['PlPp.dat', 'PlNn.dat']


def test_partner_zip_path_is_flattened(tmp_path):
    archive = _archive(tmp_path, 'nana.zip', '../outside/PlNnWh.dat', b'nana')
    output = tmp_path / 'output'
    output.mkdir()
    result = nana_from_zip(archive, output)
    assert result == output / 'PlNnWh.dat'
    assert result.read_bytes() == b'nana'
    assert not (tmp_path / 'outside').exists()


def test_ambiguous_partner_archive_rejected(tmp_path):
    archive = _archive(tmp_path, 'nana.zip', 'PlNnWh.dat', b'nana')
    with zipfile.ZipFile(archive, 'a') as output:
        output.writestr('PlNnYe.dat', b'other-nana')
    with pytest.raises(ValueError, match='exactly one'):
        nana_from_zip(archive, tmp_path)


def test_partner_metadata_cannot_escape_vault(tmp_path):
    outside = _archive(tmp_path, 'nana.zip', 'PlNnWh.dat', b'outside')
    storage = tmp_path / 'storage'
    storage.mkdir()
    metadata = {'characters': {'Ice Climbers': {'skins': [
        {'id': 'popo', 'paired_nana_id': 'nana'},
        {'id': 'nana', 'filename': str(outside)}]}}}
    with pytest.raises(ValueError, match='missing'):
        find_paint_partner(Path('PlPpRe.dat'), find_vanilla=lambda *_: None,
                           storage_root=storage, costume_id='popo', metadata=metadata,
                           output_dir=tmp_path)


def test_saved_pair_roundtrips_through_real_import_and_metadata(dual_backend, monkeypatch, tmp_path):
    """Native validation/rendering are stubbed; ZIP writes and pair linking are real."""
    import vault.importing.unified.characters as characters
    import vault.importing.unified.archive as archive_engine

    vault = dual_backend
    vault.write({'characters': {}, 'stages': {}})
    monkeypatch.setattr(characters, 'STORAGE_PATH', vault.storage)
    monkeypatch.setattr(characters, 'validate_for_slippi', lambda *a, **k: {'slippi_safe': True})
    monkeypatch.setattr(characters, '_maybe_diet_fix', lambda data, *a, **k: (data, False))
    monkeypatch.setattr(characters, 'build_csp_and_stock', lambda *a, **k: {
        'csp': None, 'stock': None, 'csp_source': 'missing', 'stock_source': 'missing'})
    monkeypatch.setattr(archive_engine, 'detect_content_type', lambda *a, **k: {'type': 'character'})
    infos = [
        {'character': 'Ice Climbers', 'color': color, 'costume_code': code,
         'dat_file': code + '.dat', 'csp_file': None, 'stock_file': None,
         'is_popo': popo, 'is_nana': not popo,
         'pair_costume_code': partner, 'pair_dat_file': partner + '.dat'}
        for color, code, popo, partner in [
            ('Red', 'PlPpRe', True, 'PlNnWh'), ('White', 'PlNnWh', False, 'PlPpRe')]]
    monkeypatch.setattr(archive_engine, 'detect_character_from_zip', lambda _: infos)
    monkeypatch.setattr(characters.tempfile, 'tempdir', str(tmp_path))

    archive = tmp_path / 'pair.zip'
    def save_pair(nana_bytes):
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('PlPpRe.dat', b'unchanged-popo')
            output.writestr('PlNnWh.dat', nana_bytes)
        result, status = archive_engine._import_single_archive(
            str(archive), 'Painted pair.zip', slippi_action='keep',
            duplicate_action='import_anyway', custom_title='Painted pair', recurse_containers=False)
        assert status == 200
        assert result['imported_count'] == 2
        assert result['pairing_complete'] is True

    save_pair(b'original-nana')
    original_ids = {skin['id'] for skin in vault.read()['characters']['Ice Climbers']['skins']}
    save_pair(b'painted-nana')
    skins = vault.read()['characters']['Ice Climbers']['skins']
    added = [skin for skin in skins if skin['id'] not in original_ids]
    popo = next(skin for skin in added if skin.get('is_popo'))
    nana = next(skin for skin in added if skin.get('is_nana'))
    assert popo['paired_nana_id'] == nana['id']
    assert nana['paired_popo_id'] == popo['id']
    assert len(skins) == 4  # The source pair still exists independently.
    output = tmp_path / 'reopened'
    output.mkdir()
    partner = find_paint_partner(
        Path('PlPpReMod.dat'), find_vanilla=lambda *_: None,
        storage_root=vault.storage, costume_id=popo['id'],
        metadata=vault.read(), output_dir=output)
    assert partner.read_bytes() == b'painted-nana'
    with zipfile.ZipFile(vault.storage / 'Ice Climbers' / popo['filename']) as saved:
        assert saved.read('PlPpReMod.dat') == b'unchanged-popo'

    # A linking failure after file import must be visible to the editor even
    # though the generic importer keeps its historical partial-success shape.
    monkeypatch.setattr(archive_engine, 'fix_ice_climbers_pairing', lambda *a: False)
    result, status = archive_engine._import_single_archive(
        str(archive), 'Failed links.zip', slippi_action='keep',
        duplicate_action='import_anyway', custom_title='Failed links', recurse_containers=False)
    assert status == 200 and result['imported_count'] == 2
    assert result['pairing_complete'] is False


@pytest.mark.parametrize('scenario', ['complete', 'missing_partner', 'commit_failure'])
def test_pair_link_acknowledgement_requires_reciprocal_records_and_commit(monkeypatch, scenario):
    from contextlib import contextmanager
    import vault.importing.unified.characters as characters

    infos = [
        {'costume_code': 'PlPpRe', 'pair_costume_code': 'PlNnWh', 'is_popo': True},
        {'costume_code': 'PlNnWh', 'pair_costume_code': 'PlPpRe', 'is_nana': True},
    ]
    skins = [{'id': 'p', 'costume_code': 'PlPpRe'}, {'id': 'n', 'costume_code': 'PlNnWh'}]
    if scenario == 'missing_partner':
        skins.pop()

    @contextmanager
    def transaction():
        yield {'characters': {'Ice Climbers': {'skins': skins}}}
        if scenario == 'commit_failure':
            raise OSError('Synthetic metadata commit failure')

    monkeypatch.setattr(characters, 'metadata_transaction', transaction)
    assert characters.fix_ice_climbers_pairing(infos, {'PlPpRe': 'p', 'PlNnWh': 'n'}) is (scenario == 'complete')


@pytest.mark.parametrize('popo,nana', [('Nr', 'Nr'), ('Re', 'Wh'), ('Or', 'Aq'), ('Gr', 'Ye')])
def test_nana_preview_resolves_popo_without_copying_dat_bytes(editor, popo, nana):
    client, vanilla, _ = editor
    _vanilla(vanilla, 'Ice Climbers', 'PlPp' + popo, b'popo')
    _vanilla(vanilla, 'Nana', 'PlNn' + nana, b'nana')
    response = client.post('/api/mex/viewer/paths-vanilla', json={
        'character': 'Nana', 'costumeCode': 'PlNn' + nana})
    assert response.status_code == 200
    members = response.json['members']
    assert [m['datName'] for m in members] == ['PlPp' + popo + '.dat', 'PlNn' + nana + '.dat']
    assert all('datBase64' not in member for member in members)


@pytest.mark.parametrize('reverse_only', [False, True])
def test_generic_vault_nana_preview_keeps_custom_popo(editor, monkeypatch, reverse_only):
    client, vanilla, storage = editor
    _archive(storage, 'popo.zip', 'PlPpRe.dat', b'custom-popo')
    _archive(storage, 'nana.zip', 'PlNnWh.dat', b'custom-nana')
    _vanilla(vanilla, 'Ice Climbers', 'PlPpRe', b'vanilla-popo')
    monkeypatch.setattr(metadata_module, 'load_metadata', lambda **_: {'characters': {
        'Ice Climbers': {'skins': [
            {'id': 'popo', 'filename': 'popo.zip', 'paired_nana_id': 'nana'},
            {'id': 'nana', 'filename': 'nana.zip', **({} if reverse_only else {'paired_popo_id': 'popo'})}]}}})
    response = client.post('/api/viewer/paths', json={'character': 'Ice Climbers', 'skinId': 'nana'})
    assert response.status_code == 200
    assert [Path(m['datFile']).read_bytes() for m in response.json['members']] == [b'custom-popo', b'custom-nana']
    assert all('datBase64' not in member for member in response.json['members'])


def test_missing_explicit_popo_does_not_replace_custom_partner(editor, monkeypatch):
    client, vanilla, storage = editor
    _archive(storage, 'nana.zip', 'PlNnWh.dat', b'custom-nana')
    _vanilla(vanilla, 'Ice Climbers', 'PlPpRe', b'vanilla-popo')
    monkeypatch.setattr(metadata_module, 'load_metadata', lambda **_: {'characters': {
        'Ice Climbers': {'skins': [{'id': 'nana', 'filename': 'nana.zip', 'paired_popo_id': 'missing'}]}}})
    response = client.post('/api/viewer/paths', json={'character': 'Ice Climbers', 'skinId': 'nana'})
    assert response.status_code == 500
    assert 'paired Popo costume is missing' in response.json['error']


def test_non_ic_preview_stays_single(editor):
    client, vanilla, _ = editor
    _vanilla(vanilla, 'Fox', 'PlFxNr', b'fox')
    response = client.post('/api/mex/viewer/paths-vanilla', json={'character': 'Fox', 'costumeCode': 'PlFxNr'})
    assert response.status_code == 200
    assert 'members' not in response.json


def test_game_and_watch_resolves_under_his_vault_name():
    """The vault and pose manager say "Mr. Game & Watch"; csp_data keeps his
    scene under G&W/. Both names must find the same scene and AJ prefix."""
    assert viewer_tools.VIEWER_CHAR_PREFIXES['Mr. Game & Watch'] == viewer_tools.VIEWER_CHAR_PREFIXES['G&W'] == 'PlGw'
    require('app/utility/tools/processor/csp_data/G&W/scene.yml', why='retail CSP scenes and pose data')
    scene = viewer_tools.find_scene_file('Mr. Game & Watch')
    assert scene is not None and scene == viewer_tools.find_scene_file('G&W')
