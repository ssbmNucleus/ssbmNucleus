import json
import subprocess
from pathlib import Path

import pytest
from randall.assistant import approvals, tools
from randall.delivery import projects
from core import config, state


@pytest.fixture
def setup(vault, monkeypatch):
    root = vault.project_root / 'projects'
    target = root / 'Test' / 'project.mexproj'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'build': {'name': 'Test'}}))
    fighters = target.parent / 'data/fighters'
    fighters.mkdir(parents=True)
    for fid, name in [(6, 'Link'), (10, 'Ice Climbers'), (11, 'Nana')]:
        (fighters / f'{fid:03}.json').write_text(json.dumps({'name': name, 'costumes': [{'name': 'Normal'}]}))
    monkeypatch.setattr(config, 'PROJECTS_PATH', root)
    # Installs are mocked below; no native executable is required on CI.
    cli = vault.project_root / 'mexcli'
    cli.write_bytes(b'test executable placeholder')
    monkeypatch.setattr(config, 'MEXCLI_PATH', cli)
    monkeypatch.setattr(state, '_current_project_path', target)
    monkeypatch.setattr(state, 'reload_mex_manager', lambda: None)
    iso = vault.project_root / 'vanilla.iso'
    iso.write_bytes(b'GALE01 test ISO')
    monkeypatch.setattr(projects, 'known_vanilla_iso', lambda: iso)
    vault.write({'characters': {'Link': {'skins': [{'id': 'cdi', 'name': 'CDI Link', 'filename': 'cdi.zip'}]}}})
    vault.touch('Link', 'cdi.zip', data=b'test costume')
    args = {'project_id': projects.list_projects()['projects'][0]['id'],
            'items': [{'character': 'Link', 'skin_id': 'cdi'}]}
    return target, args


def execute(call):
    return tools.execute(call, approvals.Grant(call.fingerprint))


def test_discovery_and_no_export_surface(setup):
    target, args = setup
    assert projects.list_projects()['can_create']
    result = projects.inspect_project(args['project_id'])
    assert result['projects'][0]['current']
    assert result['fighters'][0] == {'id': 6, 'name': 'Link', 'costume_count': 1}
    assert projects.inspect_project(args['project_id'], 'Link')['costumes'] == [
        {'slot': 1, 'name': 'Normal', 'filename': ''}]
    assert not any('export' in name for name in tools.REGISTRY)
    with pytest.raises(ValueError, match='not found'):
        projects.inspect_project(str(target))


def test_create_requires_approval_and_exact_source(setup, monkeypatch):
    invoked = []
    monkeypatch.setattr(projects.subprocess, 'run', lambda *a, **kw: invoked.append(a))
    call = tools.prepare('create_project', {'name': 'My project'})
    assert 'approval' in tools.execute(call)['error']
    projects.known_vanilla_iso().write_bytes(b'changed ISO')
    assert 'changed' in execute(call)['error']
    assert not invoked


def test_create_uses_existing_command_without_export_or_activation(setup, monkeypatch):
    target, _ = setup
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[1] == 'create':
            created = Path(command[3]) / 'project.mexproj'
            created.write_text(json.dumps({'build': {'name': command[4]}}))
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(projects.subprocess, 'run', run)
    call = tools.prepare('create_project', {'name': 'My project'})
    grant = approvals.Grant(call.fingerprint)
    result = tools.execute(call, grant)
    assert result['project']['name'] == 'My project'
    assert calls[0][1] == 'create' and len(calls[0]) == 5
    # the codes a new project starts with, the same as the Install page's
    from projects.install.required_codes import new_project_gecko_codes
    assert [c[1:4] for c in calls[1:]] == [
        ['add-code', str(Path(calls[0][3]) / 'project.mexproj'), name]
        for name, _ in new_project_gecko_codes()]
    assert state.get_current_project_path() == target
    assert 'approval' in tools.execute(call, grant)['error']
    assert len(calls) == 1 + len(new_project_gecko_codes())


def test_create_refuses_new_destination_collision(setup):
    call = tools.prepare('create_project', {'name': 'Another'})
    Path(json.loads(call.plan)['directory']).mkdir()
    assert 'changed' in execute(call)['error']


def test_missing_iso_is_actionable(setup, monkeypatch):
    monkeypatch.setattr(projects, 'known_vanilla_iso', lambda: None)
    with pytest.raises(ValueError, match='Settings'):
        tools.prepare('create_project', {'name': 'Test'})


@pytest.mark.parametrize('change', ['project', 'archive', 'metadata'])
def test_install_revalidates_approved_inputs(setup, vault, change):
    target, args = setup
    call = tools.prepare('install_project_mods', args)
    if change == 'project':
        target.write_text('{"build":{"name":"Changed"}}')
    elif change == 'archive':
        vault.touch('Link', 'cdi.zip', data=b'changed')
    else:
        data = vault.read()
        data['characters']['Link']['skins'][0]['name'] = 'Another skin'
        vault.write(data)
    assert 'changed' in execute(call)['error']


def test_install_needs_approval_and_stays_on_target(setup, vault, monkeypatch):
    from mexcli.project import MexManager
    target, args = setup
    call = tools.prepare('install_project_mods', args)
    assert 'approval' in tools.execute(call)['error']
    other = config.PROJECTS_PATH / 'Other/project.mexproj'
    other.parent.mkdir()
    other.write_text('{"build":{"name":"Other"}}')
    monkeypatch.setattr(state, '_current_project_path', other)
    seen = []
    def install(self, manifest):
        seen.append((self.project_path, manifest))
        assert Path(manifest['6'][0]).read_bytes() == b'test costume'
        return {'totalImported': 1, 'totalFailed': 0, 'perFighter': {'Link': {'imported': 1}}}
    monkeypatch.setattr(MexManager, 'import_costumes', install)
    result = execute(call)
    assert result['installed_count'] == 1, result
    assert seen[0][0] == target.resolve()
    assert state.get_current_project_path() == other
    assert (vault.storage / 'Link/cdi.zip').read_bytes() == b'test costume'
    assert not Path(seen[0][1]['6'][0]).exists()


def test_partial_install_does_not_claim_all_items(setup, monkeypatch):
    from mexcli.project import MexManager
    monkeypatch.setattr(MexManager, 'import_costumes', lambda *a: {'totalImported': 1, 'totalFailed': 1})
    result = execute(tools.prepare('install_project_mods', setup[1]))
    assert result['installed_count'] == 1 and result['failed_count'] == 1
    assert result['installed_items'] == [] and result['error']


def test_pairs_nana_once_and_rejects_missing_pair(setup, vault):
    _, args = setup
    vault.write({'characters': {'Ice Climbers': {'skins': [
        {'id': 'popo', 'paired_nana_id': 'nana'}, {'id': 'nana', 'is_nana': True, 'visible': False}]}}})
    vault.touch('Ice Climbers', 'popo.zip')
    vault.touch('Ice Climbers', 'nana.zip')
    args['items'] = [{'character': 'Ice Climbers', 'skin_id': 'popo'}] * 2
    plan, preview = projects.prepare_install(args)
    assert [s['fighter'] for s in plan['sources']] == [10, 11]
    assert len(preview['items']) == 2
    (vault.storage / 'Ice Climbers/nana.zip').unlink()
    with pytest.raises(ValueError, match='unavailable'):
        projects.prepare_install(args)


def test_rejects_archive_outside_vault(setup, vault):
    data = vault.read()
    data['characters']['Link']['skins'][0]['filename'] = '../../vanilla.iso'
    vault.write(data)
    with pytest.raises(ValueError, match='unavailable'):
        projects.prepare_install(setup[1])


def test_install_rejects_unknown_fields_and_empty_batch(setup):
    args = dict(setup[1])
    args['items'] = []
    with pytest.raises(ValueError, match='between'):
        tools.prepare('install_project_mods', args)
    args['items'] = [{'character': 'Link', 'skin_id': 'cdi', 'path': 'arbitrary'}]
    with pytest.raises(ValueError, match='exact'):
        tools.prepare('install_project_mods', args)
