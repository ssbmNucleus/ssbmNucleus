"""The app MCP's collection and build tools (randall/mcp/build_tools.py, docs/dev/APP_MCP.md "Collection and builds").

Each tool calls the app's own route handler in-process, pinned to the build the AI named. The route runs behind the
real backend-token check (test_app_mcp.guarded_app). Handlers that need MexCLI are stubbed with recorders that also
note which build the request saw; the importer, the DAS and replace-slot stage installs, the export save and the
project listing run for real on a temp vault and temp builds.
"""
import hashlib
import io
import json
import re
import subprocess
import threading
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from flask import jsonify, request

from tests.backend.test_app_mcp import _no_network, guarded_app, payload, rpc
from tests.paths import APP, REPO
from tests.left_out import left_out

from core import config, jobs, playable_iso, state
from randall.delivery import projects
from randall.mcp import build_tools, credits, menu_grid, toolkit, window


@pytest.fixture
def client(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(config, 'LOGS_PATH', tmp_path / 'logs')
    monkeypatch.delenv('NUCLEUS_ASSISTANT', raising=False)
    credits.clear()
    monkeypatch.setattr(credits, '_machine_key', lambda: None)
    monkeypatch.setattr(credits, '_entitlement', _no_network)
    app = guarded_app()
    yield app.test_client()
    toolkit.stop()
    credits.clear()
    window.clear()


def call(client, name, arguments=None):
    response = rpc(client, 'tools/call', {'name': name, 'arguments': arguments or {}})
    assert response.status_code == 200
    answer = response.get_json()
    assert 'error' not in answer, answer
    return answer['result']


def ok(client, name, arguments=None):
    result = call(client, name, arguments)
    assert result['isError'] is False, result['content'][0]['text']
    return payload(result)


def refused(client, name, arguments=None):
    result = call(client, name, arguments)
    assert result['isError'] is True, result['content'][0]['text']
    return result['content'][0]['text']


@pytest.fixture
def builds(vault, monkeypatch):
    """Two builds under PROJECTS_PATH; the window has Build B open."""
    root = vault.project_root / 'projects'
    paths = {}
    for name in ('Build A', 'Build B'):
        target = root / name / 'project.mexproj'
        (target.parent / 'files').mkdir(parents=True)
        (target.parent / 'data' / 'stages').mkdir(parents=True)
        target.write_text(json.dumps({'build': {'name': name},
                                      'stageSaveMap': {'filePaths': [f'stage_{i}.json' for i in range(71)]}}))
        paths[name] = target.resolve()
    monkeypatch.setattr(config, 'PROJECTS_PATH', root)
    monkeypatch.setattr(state, '_current_project_path', paths['Build B'])
    monkeypatch.setattr(state, '_mex_manager', None)
    ids = {p['name']: p['id'] for p in projects.list_projects()['projects']}
    return SimpleNamespace(paths=paths, ids=ids, a=ids['Build A'], files=paths['Build A'].parent / 'files')


def stub(monkeypatch, module, name, answer=None, status=200):
    """Replace a route handler with a recorder. -> the list of requests it saw (with the build it acted on)."""
    seen = []

    def view(**kwargs):
        seen.append({'project': state.get_current_project_path(), 'json': request.get_json(silent=True),
                     'form': request.form.to_dict(), 'args': request.args.to_dict(), 'kwargs': kwargs,
                     'files': [(f.filename, f.read()) for f in request.files.getlist('file')]})
        body = answer(seen[-1]) if callable(answer) else answer
        return jsonify(body if body is not None else {'success': True}), status
    monkeypatch.setattr(module, name, view)
    return seen


def zip_bytes(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


# ------------------------------------------------------------------ tools/list

def test_tools_list_has_the_build_tools_with_honest_annotations(client):
    listed = rpc(client, 'tools/list').get_json()['result']['tools']
    by_name = {tool['name']: tool for tool in listed}
    assert len(by_name) == len(listed)
    assert set(build_tools.NAMES) <= set(by_name)
    for name in build_tools.NAMES:
        tool = by_name[name]
        jsonschema.Draft202012Validator.check_schema(tool['inputSchema'])
        assert tool['inputSchema']['additionalProperties'] is False
        assert tool['description'].strip() and tool['annotations']['openWorldHint'] is False
    read_only = {'search_vault_mods', 'inspect_project_stages', 'get_music_playlist'}
    destructive = {'install_stage_skin', 'install_custom_characters', 'install_custom_stages', 'install_extra',
                   'set_music_playlist', 'save_build_iso'}
    for name in build_tools.NAMES:
        hints = by_name[name]['annotations']
        assert hints['readOnlyHint'] is (name in read_only), name
        if name not in read_only:
            assert hints['destructiveHint'] is (name in destructive), name
    for name in destructive - {'save_build_iso'}:
        assert 'project_id' in by_name[name]['inputSchema']['required']
        assert 'that is the approval' in by_name[name]['description'], name
    assert 'job_status' in by_name['export_build']['description']
    assert 'export_build' in by_name['job_status']['description']


def test_the_doc_states_the_tool_count():
    from randall.mcp import server
    text = (REPO / 'docs' / 'dev' / 'APP_MCP.md').read_text(encoding='utf-8')
    assert f'`tools/list` gives {len(server.tool_list())} tools' in text
    for name in build_tools.NAMES:
        assert f'`{name}' in text, name


def test_build_tools_need_a_project_id_list_projects_gave(client, builds):
    for name, arguments in (('install_stage_skin', {'stage_code': 'GrNBa', 'variant_id': 'x'}),
                            ('get_music_playlist', {'playlist': 'menu'}),
                            ('export_build', {})):
        assert 'list_projects' in refused(client, name, dict(arguments, project_id='nope'))
    assert 'Unknown arguments: extra' in refused(client, 'inspect_project_stages', {'project_id': builds.a,
                                                                                   'extra': 1})


# ------------------------------------------------------------------ import_to_vault

@pytest.fixture
def handoff(monkeypatch):
    """The importer engine behind POST /api/mex/import/file, scripted: each call gets the next answer."""
    from vault.importing.unified import protocol
    script, seen = [], []

    def fake(temp_path, upload_name, **kwargs):
        seen.append(dict(kwargs, upload_name=upload_name, data=Path(temp_path).read_bytes()))
        answer = script.pop(0)
        return (answer if isinstance(answer, tuple) else (answer, 200))
    monkeypatch.setattr(protocol, 'import_handoff', fake)
    return SimpleNamespace(script=script, seen=seen)


def test_import_answers_the_importers_questions_as_the_app_does(client, vault, tmp_path, handoff):
    source = tmp_path / 'fox pack.zip'
    source.write_bytes(b'PK fox pack')
    handoff.script.extend([
        {'success': False, 'type': 'slippi_dialog', 'unsafe_costumes': [{'character': 'Fox', 'color': 'Red'}]},
        {'success': False, 'type': 'duplicate_dialog', 'message': '1 costume is already in your vault'},
        {'success': True, 'type': 'character', 'imported_count': 1, 'skipped_count': 1, 'fixed_count': 1,
         'costumes': [{'character': 'Fox', 'id': 'fox-red-1', 'color': 'Red'}],
         'skipped_duplicates': [{'character': 'Fox', 'color': 'Neutral',
                                 'existing_skin': {'id': 'owned', 'name': 'Neutral Fox'}}],
         'message': 'Imported 1 costume'},
    ])
    result = ok(client, 'import_to_vault', {'path': str(source)})
    assert [s['slippi_action'] for s in handoff.seen] == [None, 'fix', 'fix']
    assert [s['duplicate_action'] for s in handoff.seen] == [None, None, 'skip']
    assert all(s['data'] == b'PK fox pack' and s['upload_name'] == 'fox pack.zip' for s in handoff.seen)
    assert result['answered']['slippi']['answer'] == 'fix' and result['answered']['slippi']['unsafe'] == ['Fox Red']
    assert result['answered']['duplicates']['answer'] == 'skip'
    assert result['added'] == {'costumes': [{'character': 'Fox', 'skin_id': 'fox-red-1', 'color': 'Red'}]}
    assert result['already_in_vault'] == [{'of': 'Fox', 'existing_id': 'owned', 'name': 'Neutral Fox'}]
    assert result['vault_changed'] is True and 'install_project_mods' in result['next']

    handoff.script.extend([{'success': False, 'type': 'slippi_dialog', 'unsafe_costumes': []},
                           {'success': True, 'type': 'character', 'imported_count': 1,
                            'costumes': [{'character': 'Fox', 'id': 'fox-2', 'color': 'Red'}]}])
    ok(client, 'import_to_vault', {'path': str(source), 'slippi': 'import_as_is', 'duplicates': 'import_anyway',
                                   'title': 'My Fox'})
    assert handoff.seen[-1]['slippi_action'] == 'import_as_is'
    assert handoff.seen[-1]['custom_title'] == 'My Fox'


def test_import_takes_the_importers_default_kind_or_the_one_asked(client, vault, tmp_path, handoff):
    source = tmp_path / 'MnSlChr.dat'
    source.write_bytes(b'css')
    question = {'success': False, 'type': 'choice_dialog', 'question': 'Import it as:', 'default': 'css_icon_grid',
                'options': [{'key': 'css_icon_grid', 'label': 'Icon grid', 'hints': {'mod_type': 'css_icon_grid'}},
                            {'key': 'css_background', 'label': 'CSS background',
                             'hints': {'mod_type': 'css_background'}}]}
    done = {'success': True, 'type': 'menu_mod', 'menu_mod_type': 'css_icon_grid', 'imported_count': 1,
            'mods': [{'id': 'grid-1', 'name': 'Halo grid'}]}
    handoff.script.extend([question, done])
    result = ok(client, 'import_to_vault', {'path': str(source)})
    assert handoff.seen[-1]['mod_type'] == 'css_icon_grid'
    assert result['answered']['kind']['answer'] == 'css_icon_grid'
    assert [o['key'] for o in result['answered']['kind']['options']] == ['css_icon_grid', 'css_background']
    assert result['added'] == {'menu_mods': [{'id': 'grid-1', 'name': 'Halo grid'}]}

    handoff.script.extend([question, dict(done, menu_mod_type='css_background')])
    ok(client, 'import_to_vault', {'path': str(source), 'kind': 'css_background'})
    assert handoff.seen[-1]['mod_type'] == 'css_background'

    calls_before = len(handoff.seen)
    handoff.script.append(question)
    text = refused(client, 'import_to_vault', {'path': str(source), 'kind': 'stage'})
    assert 'not one of the options' in text and len(handoff.seen) == calls_before + 1


def test_pictures_picked_together_are_one_import_and_other_files_one_each(client, vault, tmp_path, handoff):
    digits = [tmp_path / f'digit{i}.png' for i in range(2)]
    for i, path in enumerate(digits):
        path.write_bytes(b'png %d' % i)
    handoff.script.append({'success': True, 'type': 'menu_mod', 'imported_count': 1, 'mods': []})
    ok(client, 'import_to_vault', {'paths': [str(p) for p in digits]})
    assert len(handoff.seen) == 1
    with zipfile.ZipFile(io.BytesIO(handoff.seen[0]['data'])) as packed:
        assert sorted(packed.namelist()) == ['digit0.png', 'digit1.png']

    archives = [tmp_path / 'a.zip', tmp_path / 'b.zip']
    for path in archives:
        path.write_bytes(b'PK')
    handoff.script.extend([
        {'success': True, 'type': 'bundle', 'bundle_id': 'b1', 'name': 'Pack'},
        ({'success': False, 'error': 'Could not detect any mods in this file'}, 400)])
    result = ok(client, 'import_to_vault', {'paths': [str(p) for p in archives]})
    assert len(handoff.seen) == 3 and result['imported_count'] == 1 and result['vault_changed'] is True
    assert result['results'][0]['added'] == {'bundles': [{'bundle_id': 'b1', 'name': 'Pack'}]}
    assert result['results'][1]['error'] == 'Could not detect any mods in this file'


def test_import_refuses_what_it_cannot_send(client, vault, tmp_path):
    (tmp_path / 'x.zip').write_bytes(b'PK')
    assert 'absolute' in refused(client, 'import_to_vault', {'path': 'x.zip'})
    assert 'No file' in refused(client, 'import_to_vault', {'path': str(tmp_path / 'missing.zip')})
    assert 'not both' in refused(client, 'import_to_vault', {'path': str(tmp_path / 'x.zip'), 'paths': []})
    assert 'slippi must be' in refused(client, 'import_to_vault', {'path': str(tmp_path / 'x.zip'),
                                                                   'slippi': 'yes'})
    notes = tmp_path / 'notes.txt'
    notes.write_text('hi')
    assert 'supported' in refused(client, 'import_to_vault', {'path': str(notes)})      # the route's own check


def test_import_runs_the_real_importer_and_names_stage_skins_by_their_ids(client, vault, tmp_path, monkeypatch):
    """test_import_container_recursion's stage case through MCP: a duplicate question answered "skip"."""
    import vault.importing.unified.archive as unified_archive
    from vault.importing.unified.helpers import compute_dat_hash
    owned = vault.path('das', 'battlefield', 'owned-bf.zip')
    owned.write_bytes(zip_bytes({'GrNBa.dat': b'owned stage'}))
    vault.write({'characters': {}, 'stages': {'battlefield': {'variants': [
        {'id': 'owned-bf', 'name': 'Owned BF', 'dat_hash': compute_dat_hash(b'owned stage')}]}}})

    def detect_stages(zip_path):
        with zipfile.ZipFile(zip_path) as archive:
            return [{'stage_name': 'Battlefield', 'folder': 'battlefield', 'stage_file': name}
                    for name in archive.namelist() if name.endswith('.dat')]
    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', lambda _p: [])
    monkeypatch.setattr(unified_archive, 'detect_stage_from_zip', detect_stages)
    monkeypatch.setattr(unified_archive, 'import_vanilla_stage_dats', lambda *_a, **_k: [])
    imported = []

    def import_stage(_zip_path, stage_info, _filename, **_kwargs):
        imported.append(stage_info['stage_file'])
        return {'success': True, 'variant_id': 'neon-bf'}
    monkeypatch.setattr(unified_archive, 'import_stage_mod', import_stage)

    source = tmp_path / 'stages.zip'
    source.write_bytes(zip_bytes({'GrNBa owned.dat': b'owned stage', 'GrNBa new.dat': b'new stage'}))
    result = ok(client, 'import_to_vault', {'path': str(source)})
    assert imported == ['GrNBa new.dat']
    assert result['answered']['duplicates']['answer'] == 'skip'
    assert result['added'] == {'stage_skins': [{'stage': 'Battlefield', 'stage_code': 'GrNBa',
                                                'variant_id': 'neon-bf'}]}
    assert result['already_in_vault'][0]['existing_id'] == 'owned-bf'
    assert 'install_stage_skin' in result['next']


# ------------------------------------------------------------------ search_vault_mods

def test_search_vault_mods_lists_what_the_install_tools_take(client, vault):
    vault.write({
        'custom_characters': [{'slug': 'wario', 'name': 'Wario', 'costume_count': 6,
                               'victory_theme': {'name': 'Wario Ware'}, 'has_announcer': True},
                              {'type': 'folder', 'id': 'f', 'name': 'Old'}],
        'custom_stages': [{'slug': 'delfino', 'name': 'Delfino Plaza', 'playlist': [{}, {}]}],
        'characters': {'Falco': {'extras': {'gun': [{'id': 'gun_1', 'name': 'Gold Gun'}],
                                            'laser': [{'id': 'laser_1', 'name': 'Red Laser'}]}}}})
    found = ok(client, 'search_vault_mods', {'kind': 'custom_characters'})
    assert found['custom_characters'] == [{'slug': 'wario', 'name': 'Wario', 'costumes': 6,
                                           'victory_theme': 'Wario Ware', 'has_announcer': True,
                                           'date_added': None}]
    assert ok(client, 'search_vault_mods', {'kind': 'custom_stages', 'query': 'delf'})['custom_stages'][0][
        'music_tracks'] == 2
    assert ok(client, 'search_vault_mods', {'kind': 'custom_stages', 'query': 'zzz'})['total'] == 0
    extras = ok(client, 'search_vault_mods', {'kind': 'extras', 'character': 'falco'})
    assert extras['character'] == 'Falco'
    by_type = {t['extra_type']: t for t in extras['extra_types']}
    assert by_type['gun']['kind'] == 'model' and by_type['gun']['saved'] == [{'extra_id': 'gun_1',
                                                                              'name': 'Gold Gun'}]
    assert by_type['laser']['saved'][0]['extra_id'] == 'laser_1'
    assert ok(client, 'search_vault_mods', {'kind': 'extras', 'character': 'Nobody'})['extra_types'] == []
    assert 'kind must be' in refused(client, 'search_vault_mods', {'kind': 'costumes'})


# ------------------------------------------------------------------ stage skins

@pytest.fixture
def stage_vault(vault, builds, tmp_path, monkeypatch):
    """The DAS and replace-slot handlers' module paths at the temp vault, and a stand-in clean stage file."""
    from projects.routes import das as das_routes, stage_slots
    from vault.routes import das as vault_das
    for module in (das_routes, vault_das, stage_slots):
        monkeypatch.setattr(module, 'STORAGE_PATH', vault.storage)
        monkeypatch.setattr(module, 'PROJECT_ROOT', vault.project_root, raising=False)
    refs = tmp_path / 'refs'
    refs.mkdir()

    def vanilla_ref(filename, storage_path=None):
        ref = refs / filename
        if not ref.exists():
            ref.write_bytes(b'VANILLA')
        return ref
    monkeypatch.setattr(stage_slots.vanilla_refs, 'ensure_vanilla_ref', vanilla_ref)
    stage_slots._MD5_CACHE.clear()
    return vault


@left_out('app/utility/DynamicAlternateStages', why='the DAS loader patches, made from Melee stage files')
def test_a_tournament_stage_skin_becomes_an_alternate_in_the_named_build_only(client, stage_vault, builds,
                                                                              tmp_path, monkeypatch):
    from projects.install import das_loaders
    # Every DAS loader is rebuilt from the user's own vanilla root by a shipped patch
    # (das_loaders.py); a synthetic loader stands in, so no game file is needed.
    synthetic = tmp_path / 'das-loaders'
    synthetic.mkdir()

    def synthetic_bytes(code):
        return f'SYNTHETIC {code} LOADER'.encode()

    def resolve(code, *, loader_dir=None, sources=()):
        loader = synthetic / das_loaders.loader_name(code)
        loader.write_bytes(synthetic_bytes(code))
        return loader

    monkeypatch.setattr(das_loaders, 'resolve_das_loader', resolve)
    # /das/status counts a stage only when its root is the loader the patch makes.
    monkeypatch.setattr(das_loaders, 'PATCHED_LOADERS', {
        das_loaders.loader_name(code): {'source_sha256': '',
                                        'target_sha256': hashlib.sha256(synthetic_bytes(code)).hexdigest()}
        for code in ('GrIz', 'GrNBa', 'GrNLa', 'GrOp', 'GrPs', 'GrSt')})
    vault = stage_vault
    (builds.files / 'GrNBa.dat').write_bytes(b'VANILLA BF')
    vault.path('das', 'battlefield', 'neon-bf.zip').write_bytes(zip_bytes({'GrNBa.dat': b'NEON BF'}))
    vault.write({'characters': {}, 'stages': {'battlefield': {'variants': [{'id': 'neon-bf', 'name': 'Neon BF'}]}}})

    result = ok(client, 'install_stage_skin', {'project_id': builds.a, 'stage_code': 'grnba',
                                               'variant_id': 'neon-bf'})
    assert result['mode'] == 'alternate' and result['dynamic_alternate_stages_set_up_now'] is True
    assert (builds.files / 'GrNBa' / result['file']).read_bytes() == b'NEON BF'
    assert (builds.files / 'GrNBa' / 'vanilla.dat').read_bytes() == b'VANILLA BF'
    assert (builds.files / 'GrNBa.dat').read_bytes() == b'SYNTHETIC GrNBa LOADER'
    # The window's own build is untouched and still the open one.
    assert state.get_current_project_path() == builds.paths['Build B']
    assert not (builds.paths['Build B'].parent / 'files' / 'GrNBa').exists()

    again = ok(client, 'install_stage_skin', {'project_id': builds.a, 'stage_code': 'GrNBa',
                                              'variant_id': 'neon-bf'})
    assert again['dynamic_alternate_stages_set_up_now'] is False and again['file'] != result['file']

    seen = ok(client, 'inspect_project_stages', {'project_id': builds.a})
    battlefield = next(s for s in seen['tournament_stages'] if s['stage_code'] == 'GrNBa')
    assert battlefield['dynamic_alternate_stages'] is True
    assert sorted(a['file'] for a in battlefield['alternates']) == sorted(['vanilla.dat', result['file'],
                                                                          again['file']])
    assert seen['other_stages'] == {'changed': [], 'counts': {'missing': 23}}
    assert seen['custom_stages'] == []

    assert 'not a Battlefield skin' in refused(client, 'install_stage_skin', {
        'project_id': builds.a, 'stage_code': 'GrNBa', 'variant_id': 'nope'})
    assert 'not a stage code' in refused(client, 'install_stage_skin', {
        'project_id': builds.a, 'stage_code': 'GrZZ', 'variant_id': 'neon-bf'})


def test_another_stage_skin_replaces_the_stage_in_the_build(client, stage_vault, builds):
    vault = stage_vault
    (builds.files / 'GrGr.dat').write_bytes(b'VANILLA')
    vault.path('das', 'green_greens', 'neon.zip').write_bytes(zip_bytes({'GrGr.dat': b'NEON GREENS'}))
    vault.write({'characters': {}, 'stages': {'green_greens': {'variants': [{'id': 'neon', 'name': 'Neon'}]}}})
    result = ok(client, 'install_stage_skin', {'project_id': builds.a, 'stage_code': 'GrGr', 'variant_id': 'neon'})
    assert result['mode'] == 'replace' and result['slot']['state'] == 'installed'
    assert (builds.files / 'GrGr.dat').read_bytes() == b'NEON GREENS'
    seen = ok(client, 'inspect_project_stages', {'project_id': builds.a})
    assert seen['other_stages']['changed'] == [{'stage': 'Green Greens', 'stage_code': 'GrGr', 'state': 'installed',
                                                'skin': {'variant_id': 'neon', 'name': 'Neon'}}]
    assert seen['other_stages']['counts'] == {'installed': 1, 'missing': 22}
    assert 'not a Green Greens skin' in refused(client, 'install_stage_skin', {
        'project_id': builds.a, 'stage_code': 'GrGr', 'variant_id': 'other'})


# ------------------------------------------------------------------ custom characters, custom stages, extras

def _css(count):
    icons = [{'fighter': i, 'x': 0, 'y': 0, 'z': 0, 'scaleX': 1, 'scaleY': 1} for i in range(count)]
    template = {'iconsPerRow': 9, 'scaleX': 1, 'scaleY': 1, 'centerX': 0, 'centerY': 0, 'iconWidth': 7.05,
                'iconHeight': 7.2, 'iconSideDropX': 0.5, 'iconSideDropY': 0.25, 'iconSideDropZ': 1}
    return icons, template


def test_custom_characters_are_added_then_the_select_grid_is_refitted(client, vault, builds, monkeypatch):
    from projects.routes import custom_characters
    from projects.routes.menus import layout
    vault.write({'custom_characters': [{'slug': 'wario', 'name': 'Wario'}]})
    added = stub(monkeypatch, custom_characters, 'install_custom_characters_batch', {
        'success': True, 'message': 'Added 1 character(s) to project', 'totalAdded': 1,
        'fighters': [{'name': 'Wario', 'success': True, 'internalId': 33}], 'failed': [],
        'warnings': ['Wario: announcer name-call not set']})
    icons, template = _css(28)
    fighters = [{'externalId': i, 'name': f'F{i}'} for i in range(26)] + [{'externalId': 27, 'name': 'Alt'},
                                                                           {'externalId': 26, 'name': 'Wario'}]
    read = stub(monkeypatch, layout, 'get_css_layout', {'icons': icons, 'template': template, 'fighters': fighters,
                                                        'lload': {'altExternalIds': [27]}})
    saved = stub(monkeypatch, layout, 'set_css_layout', {'success': True})
    result = ok(client, 'install_custom_characters', {'project_id': builds.a, 'slugs': ['wario', 'wario']})
    assert added[0]['json'] == {'slugs': ['wario']}
    assert {r['project'] for r in added + read + saved} == {builds.paths['Build A']}
    expected = json.loads(json.dumps(menu_grid.auto_css_layout(icons, template, [27])))
    assert saved[0]['json'] == expected
    grid = result['character_select_grid']
    assert (grid['refitted'], grid['icons'], grid['columns']) == (True, 27, 9)
    assert grid['rows'][0] == [f'F{i}' for i in range(9)] and grid['rows'][2][-1] == 'Wario'
    assert 'Alt' not in sum(grid['rows'], [])                      # a tucked L-load alternate takes no slot
    assert grid['added_at'] == {'Wario': {'row': 3, 'column': 9, 'icons_in_row': 9}}
    assert result['added'] == 1 and result['warnings'] == ['Wario: announcer name-call not set']
    assert state.get_current_project_path() == builds.paths['Build B']

    assert 'search_vault_mods' in refused(client, 'install_custom_characters', {'project_id': builds.a,
                                                                                 'slugs': ['toad']})
    assert len(added) == 1
    stub(monkeypatch, custom_characters, 'install_custom_characters_batch',
         {'success': False, 'error': 'No installable characters', 'failed': [{'slug': 'wario', 'error': 'bad zip'}]},
         status=400)
    assert 'wario: bad zip' in refused(client, 'install_custom_characters', {'project_id': builds.a,
                                                                              'slugs': ['wario']})
    assert len(saved) == 1


def test_custom_stages_are_added_then_the_extra_stage_pages_are_refitted(client, vault, builds, monkeypatch):
    from projects.routes import custom_stages
    from projects.routes.menus import sss
    vault.write({'custom_stages': [{'slug': 'delfino', 'name': 'Delfino Plaza'}]})
    stub(monkeypatch, custom_stages, 'install_custom_stages_batch', {
        'success': True, 'totalAdded': 1, 'stages': [{'name': 'Delfino Plaza', 'success': True}], 'failed': [],
        'warnings': []})
    vanilla_page = {'icons': [{'x': 3, 'y': 4, 'z': 1, 'scaleX': 2, 'scaleY': 2}]}
    pages = [vanilla_page, {'icons': [{'stage': i, 'x': 0, 'y': 0} for i in range(7)]}, {'icons': []}]
    stub(monkeypatch, sss, 'get_sss_layout', {'pages': pages})
    saved = stub(monkeypatch, sss, 'set_sss_layout', {'success': True})
    result = ok(client, 'install_custom_stages', {'project_id': builds.a, 'slugs': ['delfino']})
    posted = saved[0]['json']['pages']
    assert posted[0] == vanilla_page and posted[2] == {'icons': []}
    assert posted == json.loads(json.dumps(menu_grid.auto_sss_pages(pages)))
    first, seventh = posted[1]['icons'][0], posted[1]['icons'][6]
    assert first['x'] == pytest.approx(-6 * 6.75 / 2 + 0.8 / 2 + 5.95 / 2)
    assert seventh['x'] == first['x'] and seventh['y'] < first['y']
    assert result['stage_select_grid'] == {'refitted': True, 'pages': 3}


def test_install_extra_goes_to_the_model_or_the_colour_installer(client, vault, builds, monkeypatch):
    from projects.routes import extras
    from vault.routes.extras import models
    colours = stub(monkeypatch, extras, 'install_extra', {'success': True})
    model = stub(monkeypatch, models, 'install_model_extra', {'success': True})
    ok(client, 'install_extra', {'project_id': builds.a, 'character': 'Falco', 'extra_type': 'laser',
                                 'extra_id': 'laser_1'})
    ok(client, 'install_extra', {'project_id': builds.a, 'character': 'Falco', 'extra_type': 'gun',
                                 'extra_id': 'gun_1'})
    assert colours[0]['json'] == {'character': 'Falco', 'extraType': 'laser', 'modId': 'laser_1'}
    assert model[0]['json'] == {'character': 'Falco', 'extraType': 'gun', 'modId': 'gun_1'}
    assert colours[0]['project'] == model[0]['project'] == builds.paths['Build A']
    text = refused(client, 'install_extra', {'project_id': builds.a, 'character': 'Falco', 'extra_type': 'cape',
                                             'extra_id': 'x'})
    assert 'laser' in text and len(colours) == len(model) == 1


# ------------------------------------------------------------------ music

def test_music_playlists_go_through_the_music_editors_handlers(client, builds, tmp_path, monkeypatch):
    from projects.routes import music_playlists as music
    tracks = [{'index': 0, 'music_id': 4, 'name': 'Battlefield', 'chance': 100, 'has_file': True}]
    read = stub(monkeypatch, music, 'get_stage_music', {'success': True, 'vanilla': True, 'tracks': tracks})
    menu_set = stub(monkeypatch, music, 'set_menu_music', {'success': True, 'tracks': tracks})
    added = stub(monkeypatch, music, 'add_stage_track', {'success': True, 'vanilla': False, 'tracks': tracks})
    got = ok(client, 'get_music_playlist', {'project_id': builds.a, 'playlist': 'grnba'})
    assert read[0]['kwargs'] == {'stage': 'GrNBa'} and read[0]['project'] == builds.paths['Build A']
    assert got['stage'] == 'Battlefield' and got['vanilla'] is True
    assert got['tracks'] == [{'music_id': 4, 'name': 'Battlefield', 'chance': 100, 'has_file': True}]
    ok(client, 'set_music_playlist', {'project_id': builds.a, 'playlist': 'menu',
                                      'entries': [{'music_id': 4, 'chance': 70}, {'music_id': 9, 'chance': 30}]})
    assert menu_set[0]['json'] == {'entries': [{'music_id': 4, 'chance': 70}, {'music_id': 9, 'chance': 30}]}
    song = tmp_path / 'theme.mp3'
    song.write_bytes(b'ID3 song')
    result = ok(client, 'add_music_track', {'project_id': builds.a, 'playlist': 'GrNBa', 'path': str(song),
                                            'name': 'My Theme'})
    assert added[0]['files'] == [('theme.mp3', b'ID3 song')] and added[0]['form'] == {'name': 'My Theme'}
    assert result['added'] == 'My Theme' and result['vanilla'] is False


def test_music_arguments_are_checked_before_anything_runs(client, builds, tmp_path, monkeypatch):
    from projects.routes import music_playlists as music
    stage_set = stub(monkeypatch, music, 'set_stage_music')
    menu_add = stub(monkeypatch, music, 'add_menu_track')
    assert 'tournament stage codes' in refused(client, 'get_music_playlist', {'project_id': builds.a,
                                                                             'playlist': 'GrMc'})
    for entries in ([{'music_id': 'x', 'chance': 10}], [{'music_id': 1, 'chance': 101}],
                    [{'music_id': 1}], 'all'):
        refused(client, 'set_music_playlist', {'project_id': builds.a, 'playlist': 'GrNBa', 'entries': entries})
    notes = tmp_path / 'notes.txt'
    notes.write_text('la la')
    assert '.mp3' in refused(client, 'add_music_track', {'project_id': builds.a, 'playlist': 'menu',
                                                         'path': str(notes)})
    assert stage_set == [] and menu_add == []


# ------------------------------------------------------------------ export

@pytest.fixture
def exports(builds, tmp_path, monkeypatch):
    """run_export_job stands in for MexCLI: it starts a real iso_export app job that waits on ``gate``."""
    import mexcli.project
    from projects.install import export_job
    from projects.routes import project as project_routes
    output = tmp_path / 'output'
    (output / 'artifacts').mkdir(parents=True)
    monkeypatch.setattr(export_job, 'OUTPUT_PATH', output)
    monkeypatch.setattr(mexcli.project, 'MexManager', lambda cli, path: SimpleNamespace(project_path=path))
    monkeypatch.setattr(playable_iso, 'launcher_iso', lambda: None)
    monkeypatch.setattr(playable_iso, 'clean_sources', set)
    monkeypatch.setattr(playable_iso, 'designated_outputs', set)
    stub(monkeypatch, project_routes, 'get_recommended_compression', {'success': True, 'ratio': 0.62})
    gate, progressed, seen = threading.Event(), threading.Event(), []

    def run(options, *, background, project_path, mex_manager):
        seen.append({'options': options, 'background': background, 'project': project_path})
        build_id = f'build_{uuid.uuid4().hex}'
        out = output / 'artifacts' / f'{build_id}.iso'

        def work(job):
            job.progress(0.5, 'Building the ISO')
            progressed.set()
            if not gate.wait(10):
                raise RuntimeError('gate never opened')
            out.write_bytes(b'ISO BYTES')
            return {'filename': options['filename'], 'path': str(out), 'warnings': ['one warning'],
                    'cspCompression': options['cspCompression'], 'costumeCount': 3}
        jobs.start(export_job.EXPORT_KIND, work, label='ISO export', job_id=build_id,
                   params={'filename': options['filename']})
        return {'filename': options['filename'], 'artifactId': build_id}
    monkeypatch.setattr(export_job, 'run_export_job', run)
    return SimpleNamespace(gate=gate, progressed=progressed, seen=seen)


def test_export_build_starts_the_apps_export_job_and_job_status_follows_it(client, builds, exports, tmp_path):
    started = ok(client, 'export_build', {'project_id': builds.a})
    job_id = started['job_id']
    assert exports.seen[0]['background'] is True and exports.seen[0]['project'] == builds.paths['Build A']
    options = exports.seen[0]['options']
    assert options['cspCompression'] == 0.62 and options['useColorSmash'] is False
    assert re.fullmatch(r'Build_A_\d{4}-\d\d-\d\d_\d\d-\d\d\.iso', options['filename'])

    assert 'still building' in refused(client, 'save_build_iso', {'job_id': job_id, 'destination': str(tmp_path)})
    assert exports.progressed.wait(10)
    running = ok(client, 'job_status', {'job_id': job_id, 'wait_seconds': 0})
    assert running['status'] == 'running' and running['percent'] == 50 and running['detail'] == 'Building the ISO'
    exports.gate.set()
    done = ok(client, 'job_status', {'job_id': job_id, 'wait_seconds': 10})
    assert done['status'] == 'done' and 'save_build_iso' in done['next']
    assert done['result'] == {'filename': options['filename'], 'bytes': 9, 'csp_compression': 0.62, 'costumes': 3,
                              'warnings': ['one warning']}

    games = tmp_path / 'games'
    games.mkdir()
    saved = ok(client, 'save_build_iso', {'job_id': job_id, 'destination': str(games)})
    target = games / options['filename']
    assert Path(saved['path']) == target and target.read_bytes() == b'ISO BYTES' and saved['bytes'] == 9
    assert (games / (options['filename'] + playable_iso.MARKER_SUFFIX)).is_file()
    named = ok(client, 'save_build_iso', {'job_id': job_id, 'destination': str(games / 'mine.iso')})
    assert Path(named['path']).read_bytes() == b'ISO BYTES'


def test_export_and_save_refuse_what_they_cannot_do(client, builds, exports, tmp_path):
    assert 'csp_compression' in refused(client, 'export_build', {'project_id': builds.a, 'csp_compression': 2})
    assert 'color_smash' in refused(client, 'export_build', {'project_id': builds.a, 'color_smash': 'yes'})
    assert exports.seen == []
    started = ok(client, 'export_build', {'project_id': builds.a, 'filename': 'My Game!.iso', 'csp_compression': 1,
                                          'color_smash': True})
    assert exports.seen[0]['options']['filename'] == 'My_Game.iso'
    assert exports.seen[0]['options']['useColorSmash'] is True
    exports.gate.set()
    ok(client, 'job_status', {'job_id': started['job_id'], 'wait_seconds': 10})
    assert 'existing folder' in refused(client, 'save_build_iso', {'job_id': started['job_id'],
                                                                   'destination': str(tmp_path / 'nope')})
    assert 'absolute' in refused(client, 'save_build_iso', {'job_id': started['job_id'], 'destination': 'x.iso'})
    assert 'No ISO export' in refused(client, 'save_build_iso', {'job_id': 'build_0', 'destination': str(tmp_path)})
    assert refused(client, 'job_status', {'job_id': 'build_0'}) == 'No job build_0.'     # model_jobs answers


# ------------------------------------------------------------------ menu_grid (the window's grid math)

def _js_constants(path, pattern):
    return {name: float(value) for name, value in re.findall(pattern, path.read_text(encoding='utf-8'))}


def test_menu_grid_constants_are_the_windows():
    css = _js_constants(APP / 'frontend/src/projects/menus/cssGridLayout.js',
                        r'export const (CSS_\w+) = ([\d.]+)')
    assert css == {name: getattr(menu_grid, name) for name in css} and len(css) == 6
    hook = (APP / 'frontend/src/projects/stages/useCustomStages.js').read_text(encoding='utf-8')
    assert 'const cols = 6' in hook
    found = re.search(r'const baseW = ([\d.]+), baseH = ([\d.]+), spacingX = ([\d.]+), spacingY = ([\d.]+), '
                      r'centerX = ([\d.]+), centerY = ([\d.]+)', hook)
    assert found, 'autoApplySssGrid changed: update menu_grid.auto_sss_pages to match'
    assert [float(v) for v in found.groups()] == [menu_grid.SSS_BASE_W, menu_grid.SSS_BASE_H, menu_grid.SSS_SPACING_X,
                                                  menu_grid.SSS_SPACING_Y, menu_grid.SSS_CENTER_X,
                                                  menu_grid.SSS_CENTER_Y]


def test_menu_grid_picks_the_vanilla_grid_for_27_and_widens_after():
    assert menu_grid.pick_auto_columns(27) == 9
    assert menu_grid.pick_auto_columns(28) == 10 and menu_grid.pick_auto_columns(30) == 10
    icons, template = _css(27)
    layout = menu_grid.auto_css_layout(icons, template)
    assert layout['template']['scaleX'] == pytest.approx(1) and layout['template']['scaleY'] == pytest.approx(1)
    edge, middle = layout['icons'][0], layout['icons'][1]
    assert edge['collisionOffsetX'] == -0.5 and edge['z'] == 1 and middle['z'] == 0
    tucked = menu_grid.auto_css_layout(icons, template, [3])['icons'][3]
    assert tucked == icons[3]


@pytest.mark.slow
def test_menu_grid_matches_the_windows_own_code_run_by_node(tmp_path):
    script = tmp_path / 'grid.mjs'
    module = (APP / 'frontend/src/projects/menus/cssGridLayout.js').resolve().as_uri()
    script.write_text(
        f"import {{ computeAutoCssLayout }} from '{module}'\n"
        "const cases = JSON.parse(process.argv[2])\n"
        "console.log(JSON.stringify(cases.map(([icons, template, alts]) => "
        "computeAutoCssLayout(icons, template, alts))))\n", encoding='utf-8')
    cases = []
    for count, alts in ((1, []), (9, []), (26, []), (27, []), (28, [2]), (41, [0, 40]), (64, [])):
        icons, template = _css(count)
        cases.append([icons, template, alts])
    out = subprocess.run(['node', str(script), json.dumps(cases)], capture_output=True, text=True, timeout=60,
                         check=True)
    for (icons, template, alts), js in zip(cases, json.loads(out.stdout)):
        py = menu_grid.auto_css_layout(icons, template, alts)
        assert py['template'] == pytest.approx(js['template'], rel=1e-12)
        assert len(py['icons']) == len(js['icons'])
        for a, b in zip(py['icons'], js['icons']):
            assert a == pytest.approx(b, rel=1e-12, abs=1e-12)
