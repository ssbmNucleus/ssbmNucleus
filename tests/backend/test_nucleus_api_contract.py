"""The facade's docs ARE its contract, so the contract is executed here.

API.md is generated from these docstrings. A docstring that promises a key the
function does not return, or an example that passes a dict where a path belongs,
is a bug the reader only finds at runtime -- which is exactly how the first
experiment run lost six minutes to probe scripts. These tests run the offline
examples and check the documented shapes.
"""
from tests.paths import BACKEND
import inspect
import pathlib
import json
import re
import zipfile

import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(tmp_path))
    import nucleus_api
    return nucleus_api


def _public(module):
    return [(name, value) for name, value in vars(module).items()
            if not name.startswith('_') and inspect.isfunction(value)
            and value.__module__ == module.__name__]


def test_every_public_function_documents_args_returns_and_an_example(api):
    missing = []
    for name in api.__all__:
        module = getattr(api, name)
        if not inspect.ismodule(module):
            continue
        for function_name, function in _public(module):
            doc = inspect.getdoc(function) or ''
            label = f'{name}.{function_name}'
            if not doc.strip():
                missing.append(f'{label}: no docstring')
                continue
            if 'Returns:' not in doc:
                missing.append(f'{label}: no Returns section')
            takes_arguments = bool([p for p in inspect.signature(function).parameters])
            if takes_arguments and 'Args:' not in doc:
                missing.append(f'{label}: no Args section')
            if 'Example' not in doc:
                missing.append(f'{label}: no Example')
    assert not missing, 'Undocumented public API:\n' + '\n'.join(missing)


def test_module_docstrings_do_not_pass_a_dict_where_a_path_belongs(api):
    """The convention is "pass the PATH"; an example that passes the whole dict
    taught the reader the wrong call. Catch the shape in the text itself."""
    offenders = []
    for name in api.__all__:
        module = getattr(api, name)
        if not inspect.ismodule(module):
            continue
        for block in [module.__doc__ or ''] + [inspect.getdoc(f) or '' for _, f in _public(module)]:
            for line in block.splitlines():
                match = re.search(r'^\s*(\w+)\s*=\s*\w+\.(extract_background|build_costume_iso|'
                                  r'export|costume_preview|capture_moves)\(', line)
                if match and "['path']" not in line and "['" not in line.split('=')[0]:
                    variable = match.group(1)
                    used_bare = re.search(rf'\(\s*{variable}\s*[,)]', block)
                    if used_bare:
                        offenders.append(line.strip())
    assert not offenders, 'These examples pass a result dict where a path is expected:\n' + '\n'.join(offenders)


def test_workspace_refuses_to_write_outside_itself(api, tmp_path):
    assert api.workspace() == tmp_path.resolve()
    assert api.out_path('out/x.png').parent == (tmp_path / 'out').resolve()
    with pytest.raises(api.WorkspaceError):
        api.out_path(tmp_path.parent / 'escape.png')
    with pytest.raises(api.WorkspaceError):
        api.in_path(tmp_path.parent / 'escape.png')


def test_codes_round_trip_matches_its_documented_example(api, tmp_path):
    text = '$Disable Hardcoded CSS Animations\n04263384 48000010'
    parsed = api.codes.parse(text)
    assert parsed['codes'] and parsed['codes'][0]['name'] == 'Disable Hardcoded CSS Animations'
    assert parsed['codes'][0]['valid'] is True
    written = api.codes.write_code_list(parsed['codes'], 'out/codes.ini')
    assert written.endswith('codes.ini')
    read_back = api.codes.read_code_list('out/codes.ini')
    assert read_back[0]['name'] == 'Disable Hardcoded CSS Animations'
    assert '04263384 48000010' in read_back[0]['source']


def test_write_code_list_accepts_what_list_vault_codes_returns(api, monkeypatch):
    """The documented pipeline is list -> write; it needs `source` to survive it."""
    monkeypatch.setattr(api.codes, 'list_vault_codes', lambda: [
        {'id': 'a1', 'name': 'Demo', 'creator': 'x', 'category': 'CUSTOM',
         'description': '', 'source': '04263384 48000010'}])
    entries = api.codes.list_vault_codes()
    assert 'source' in entries[0]
    assert api.codes.write_code_list(entries, 'out/vault-codes.ini')


def test_pack_costume_makes_an_archive_with_the_member_name_it_was_given(api, tmp_path):
    (tmp_path / 'out').mkdir()
    dat = tmp_path / 'out' / 'PlFxNr-blue.dat'
    dat.write_bytes(b'\x00' * 64)
    archive = api.modfile.pack_costume('out/PlFxNr-blue.dat', 'out/blue.zip', 'PlFxNr.dat')
    with zipfile.ZipFile(archive) as opened:
        assert opened.namelist() == ['PlFxNr.dat']


BACKEND_DIR = BACKEND


def test_describe_parts_answers_its_documented_example(api, tmp_path):
    """The example says a ported costume's hair comes back unresolved. Run it on one."""
    from tests.backend.test_part_identity import PORT_MESHES, write_unmapped_port
    write_unmapped_port(tmp_path / 'out' / 'PlFxNrMod.dat')

    report = api.modfile.describe_parts('out/PlFxNrMod.dat', part='hair',
                                        character='Fox', viewer=False)
    assert report['requested_part']['scope'] == 'unresolved'
    widest = report['requested_part']['candidates'][0]
    assert ((widest['confirmed'], widest['shared_storage'], widest['meshes'])
            == (False, True, len(PORT_MESHES)))
    assert (sorted(f['texture_index'] for f in widest['facade_indices'])
            == [0] * len(PORT_MESHES))                # the shared image, once per mesh

    documented = {'mapping_version', 'source', 'viewer', 'textures', 'parts', 'shared_texels',
                  'shared_palettes', 'shared_descriptors', 'multi_palette_images',
                  'duplicate_content', 'uv_masks', 'unresolved'}
    assert documented <= set(report)
    assert {'texture_id', 'facade', 'nodes', 'viewer_index', 'width', 'height', 'format',
            'descriptor', 'palettes', 'usages', 'shares_texels_with', 'shares_palette_with',
            'duplicate_content_of', 'parts', 'uv_mask'} <= set(report['textures'][0])
    assert {'node', 'texture_index'} == set(report['textures'][0]['facade'][0])


@pytest.mark.skipif(not (BACKEND_DIR.parent / 'utility' / 'assets' / 'vanilla' / 'Mario'
                         / 'PlMrBk' / 'PlMrBk.dat').is_file(),
                    reason='vanilla Mario costume not extracted on this machine')
def test_describe_parts_documents_shared_scope_where_two_parts_share_a_texture(api, tmp_path):
    """The other documented scope value, on a costume the part map does place."""
    source = (BACKEND_DIR.parent / 'utility' / 'assets' / 'vanilla' / 'Mario' / 'PlMrBk'
              / 'PlMrBk.dat')
    (tmp_path / 'out').mkdir(exist_ok=True)
    (tmp_path / 'out' / 'PlMrBk.dat').write_bytes(source.read_bytes())
    report = api.modfile.describe_parts('out/PlMrBk.dat', character='Mario', viewer=False)
    cap = report['parts']['cap']
    assert cap['scope'] == 'shared'
    assert cap['co_owned_with'] == ['cap emblem']
    assert cap['required_mask']['required'] is True
    assert cap['overlapping_texels'].startswith('unmeasured')


def test_game_module_reports_the_dolphin_slot_without_starting_anything(api):
    state = api.game.status()
    assert set(state) == {'busy', 'owner', 'pid'}
    assert isinstance(state['busy'], bool)


def test_generated_docs_cover_every_module_and_function(api, tmp_path):
    from nucleus_api import gendocs
    text = gendocs.build()
    for name in gendocs.MODULES:
        assert f'## `nucleus_api.{name}`' in text
        for function_name, value in _public(getattr(api, name)):
            if value.__name__ != function_name:
                # A seam alias (menus.NATIVE_MENU_READER) is the same function
                # under a second name; it is documented once, where it is defined.
                assert f'### `{name}.{value.__name__}(' in text
                continue
            assert f'### `{name}.{function_name}(' in text, f'{name}.{function_name} missing from API.md'


def test_codes_merge_preserves_and_dedupes_the_way_its_docstring_says(api):
    """codes.merge is the rule a build change has to follow; run its example."""
    merged = api.codes.merge(
        [{'name': 'UCF', 'source': '04001234 60000000', 'enabled': True}],
        [{'name': 'Disable Hardcoded CSS Animations', 'source': '04263384 48000010'}])
    assert api.codes.write_targets('04263384 48000010')['writes'][0]['address'] == '0x80263384'
    assert api.codes.address_conflicts(
        [{'name': 'A', 'source': '04263384 48000010'},
         {'name': 'B', 'source': '04263384 60000000'}])['conflicts']
    assert merged['added'][0]['identity'] == 'Disable Hardcoded CSS Animations'
    assert merged['preserved'][0]['identity'] == 'UCF'
    assert merged['ok'] is True
    again = api.codes.merge(merged['merged'],
                            [{'name': 'Disable Hardcoded CSS Animations',
                              'source': '04263384 48000010  # relabelled'}])
    assert again['added'] == [] and again['duplicates'][0]['reason'] == 'already_present'
    clash = api.codes.merge(merged['merged'],
                            [{'name': 'UCF', 'source': '04009999 60000000'}])
    assert clash['ok'] is False
    assert clash['conflicts'][0]['reason'] == 'same_identifier_different_bytes'
    assert api.codes.content_hash('04263384 48000010') == \
        api.codes.content_hash('04263384 48000010 # x')


def test_a_published_description_supplies_codes_without_authorizing_them(api):
    found = api.codes.from_published_description(
        '$Disable Hardcoded CSS Animations\n04263384 48000010',
        'ssbmnucleus.net post 14063')
    assert found['authorizes_install'] is False
    assert found['codes'][0]['status'] == 'valid'
    assert found['codes'][0]['origin'] == 'ssbmnucleus.net post 14063'


def test_menus_says_a_menu_preview_is_unavailable_rather_than_offering_a_screenshot(api,
                                                                                    tmp_path,
                                                                                    monkeypatch):
    from core import config
    from randall.assistant.tasks import store
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'shot.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    answer = api.menus.preview(reference_image='out/shot.png')
    assert answer['status'] == 'unavailable'
    assert answer['previewed'] is False
    assert answer['artifacts'][0]['role'] == 'reference'
    # An incidental unavailable preview is a status line, not demand.
    assert answer['wish'] is None and answer['wish_recorded']['stored'] is False

    store.close()
    monkeypatch.setattr(config, 'STORAGE_PATH', tmp_path / 'wish-storage')
    try:
        asked = api.menus.preview('out/shot.png', task_id='t', required=True, chat_id='c')
        assert asked['wish']['capability'] == 'menu_output_preview'
        assert asked['wish_recorded']['stored'] is True
    finally:
        store.close()


def test_the_compatibility_manifest_is_readable_and_versioned(api):
    manifest = api.menus.compatibility_manifest()
    assert manifest['manifest_version'] >= 1
    assert 'halo3-matchmaking-lobby' in [p['package_id'] for p in manifest['packages']]


def test_builds_documented_change_flow_runs_end_to_end(api, tmp_path, monkeypatch):
    """The module docstring's flow, executed against a real build layout."""
    from core import build_transaction as bt, build_authorization as auth_module
    from nucleus_api import menus
    from tests.backend.test_build_commit_transaction import (fake_code_compiler, fake_native_reader,
                                                     make_build, menu_dat)

    builds_root = tmp_path / 'builds'
    builds_root.mkdir()
    build_dir = make_build(builds_root, 'Played')
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(build_dir)]))
    monkeypatch.setenv('NUCLEUS_BUILD_TRUST_ROOT', str(tmp_path / 'trust'))
    monkeypatch.setattr(bt, 'CODE_COMPILER', fake_code_compiler)
    monkeypatch.setattr(menus, 'NATIVE_MENU_READER', fake_native_reader)
    (tmp_path / 'out').mkdir(exist_ok=True)
    (tmp_path / 'out' / 'MnSlChr.usd').write_bytes(menu_dat(background=b'new-css'))

    build = api.builds.list_builds()[0]
    assert build['committable'] is True and build['format'] == 'mex_project'
    assert api.builds.target_signature(build['id'])['game_code'] == 'GALE01'

    artifact = api.builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    assert artifact['role'] == 'install' and artifact['destination'] == 'files/MnSlChr.usd'

    change = api.builds.prepare_change(
        build['id'], build['revision'], [artifact['id']],
        code_changes={'add': [{'name': 'Disable Hardcoded CSS Animations',
                               'source': '04263384 48000010'}]},
        task_id='task_doc')
    assert change['status'] == 'prepared'
    assert change['preview']['status'] == 'unavailable'
    card = api.builds.authorization_request(change['prepared_change_id'])
    assert card['granted_by'] == 'the user, through the approval endpoint'

    # The facade cannot grant this; the backend does, once the user has clicked.
    auth = auth_module.grant(change, granted_by='user', task_id='task_doc', task_revision=1,
                             accepted_unknown=change['unknown_dimensions'])
    assert auth['used'] is False

    receipt = api.builds.commit_change(change['prepared_change_id'], auth['authorization_id'])
    assert receipt['outcome'] == 'partial'
    assert receipt['achieved'] == {'prepared': True, 'build_inputs_updated': True,
                                   'exported': False, 'installed': False, 'previewed': False}
    assert api.builds.receipt(receipt['receipt_id'])['journal_id'] == receipt['journal_id']
    assert api.builds.rollback(receipt['receipt_id'])['after_revision'] == build['revision']


def test_builds_takes_registered_ids_and_never_a_destination_path(api, tmp_path, monkeypatch):
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(tmp_path / 'nope')]))
    signature = inspect.signature(api.builds.prepare_change)
    assert list(signature.parameters)[:4] == ['build_id', 'expected_revision', 'artifacts',
                                              'code_changes']
    assert list(inspect.signature(api.builds.commit_change).parameters) == [
        'prepared_change_id', 'authorization_id']
    with pytest.raises(api.builds.BuildChangeRejected) as caught:
        api.builds.prepare_change('bdoesnotexist', 'rev-x', [])
    assert caught.value.code == 'malformed_id', 'an id that is not an id never becomes a path'
    with pytest.raises(api.builds.BuildChangeRejected) as caught:
        api.builds.prepare_change('b0123456789ab', 'rev-x', [])
    assert caught.value.code == 'unknown_build'
    (tmp_path / 'out').mkdir(exist_ok=True)
    (tmp_path / 'out' / 'x.usd').write_bytes(b'\x00' * 64)
    with pytest.raises(api.builds.BuildChangeRejected) as caught:
        api.builds.register_artifact('out/x.usd', 'files/main.dol')
    assert caught.value.code == 'unknown_artifact_kind'
