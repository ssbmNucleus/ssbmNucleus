"""The existing native effect limit must reach the caller as a failed install."""
import json
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import pytest

from projects.routes import custom_characters as route


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_batch_capacity_failure_is_not_announced_as_success(tmp_path, monkeypatch, stream):
    # The native command's top-level exception and its handled errors use
    # different streams. Both must preserve the actionable capacity message.
    error = ("Effect table is full (m-ex caps effects at 64 slots): no room for "
             "'EfRcData.dat' (effRaichuDataTable). The roster has too many distinct "
             "effect files. Remove unneeded characters or share effect files between clones.")
    payload = json.dumps({'success': False, 'error': error, 'stackTrace': 'native save'}, indent=2)
    binary = tmp_path / 'mexcli.exe'
    binary.touch()
    project = tmp_path / 'project.mexproj'
    project.write_text('{}')
    events = []
    monkeypatch.setattr(route, 'MEXCLI_PATH', binary)
    monkeypatch.setattr(route, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(route, 'get_current_project_path', lambda: project)
    monkeypatch.setattr(route, 'get_socketio', lambda: SimpleNamespace(
        emit=lambda name, data: events.append((name, data))))
    monkeypatch.setattr(route, '_prepare_fighter_for_batch', lambda *a: {
        'ok': True, 'manifest': {'zip': str(tmp_path / 'fixture.zip')}, 'warnings': []})
    monkeypatch.setattr(route, '_plan_batch_announcers', lambda prepared: ({}, []))
    manifests = []
    def fail_native(args, **kwargs):
        manifest = Path(args[-1])
        assert manifest.is_file()
        manifests.append(manifest)
        return SimpleNamespace(returncode=1, stdout=payload if stream == 'stdout' else '',
                               stderr=payload if stream == 'stderr' else '')
    monkeypatch.setattr(route.subprocess, 'run', fail_native)
    monkeypatch.setattr(route, 'reload_mex_manager', lambda: pytest.fail('Failed batch reloaded as success'))
    app = Flask(__name__)
    with app.test_request_context(json={'slugs': ['raichu']}):
        response, status = route.install_custom_characters_batch()
    result = response.get_json()
    assert status == 500 and result['success'] is False
    assert '64 slots' in result['error'] and 'EfRcData.dat' in result['error']
    assert 'distinct effect files' in result['error']
    assert not any(data['phase'] == 'done' for _, data in events)
    assert manifests and all(not path.exists() for path in manifests)
