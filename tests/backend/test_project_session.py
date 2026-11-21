"""The open project as one checked, pinned thing (core/state.py, projects/routes/project.py).

Audit findings F-O-1 to F-O-7: a project was published before it was checked,
every request read the global whenever it ran, and nothing told a request it was
made for a project the window had already switched away from.
"""
from tests.paths import BACKEND
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask, jsonify

sys.path.insert(0, str(BACKEND))

from core import state
from core.state import PROJECT_HEADER
import projects.routes.project as project_routes


class FakeMex:
    """MexManager stand-in: get_info succeeds unless the project is named broken."""

    def __init__(self, cli_path=None, project_path=None):
        self.project_path = Path(project_path).resolve()

    def get_info(self):
        if 'broken' in self.project_path.parent.name:
            raise RuntimeError('MexCLI could not read this project')
        return {'build': {'name': self.project_path.parent.name, 'majorVersion': 1,
                          'minorVersion': 0, 'patchVersion': 0},
                'counts': {}}


def _project(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    project = folder / 'project.mexproj'
    project.write_text('{}')
    return project


def _app(extra=None):
    """The project blueprint with app.py's project hooks."""
    app = Flask(__name__)
    app.register_blueprint(project_routes.project_bp)
    app.before_request(state.pin_request_project)
    app.after_request(state.finish_project_check)
    app.register_error_handler(state.ProjectChanged, lambda error: (
        jsonify({'success': False, 'code': 'project_changed', 'error': str(error)}), 409))
    if extra:
        extra(app)
    return app


@pytest.fixture
def projects(tmp_path, monkeypatch):
    monkeypatch.setattr(project_routes, 'MexManager', FakeMex)
    monkeypatch.setattr(state, 'MexManager', FakeMex)
    from core import build_access
    health = {'status': 'clean', 'actions': [], 'problems': [], 'message': ''}
    monkeypatch.setattr(build_access, 'recover_on_open', lambda folder: dict(health))
    monkeypatch.setattr(state, '_generation', state._generation)
    # set_project_path also derives menu reference art; not wanted here.
    import shared.vanilla_extract.menu_refs as menu_refs
    monkeypatch.setattr(menu_refs, 'missing_sets', lambda: [])
    state.clear_project_path()
    yield {'a': _project(tmp_path, 'alpha'), 'b': _project(tmp_path, 'beta'),
           'broken': _project(tmp_path, 'broken'), 'health': health}
    state.clear_project_path()


def _open(client, project):
    return client.post('/api/mex/project/open', json={'projectPath': str(project)})


def test_a_failed_open_leaves_the_open_project_open(projects):
    client = _app().test_client()
    opened = _open(client, projects['a']).get_json()
    assert opened['success']

    refused = _open(client, projects['broken'])
    assert refused.status_code == 500
    assert state.get_current_project_path() == projects['a']
    status = client.get('/api/mex/status').get_json()
    assert status['project']['name'] == 'alpha'
    assert status['generation'] == opened['generation']


def test_a_quarantined_open_no_longer_closes_the_open_project(projects):
    client = _app().test_client()
    _open(client, projects['a'])
    projects['health'].update(status='quarantined', message='unaccounted change')
    refused = _open(client, projects['b'])
    assert refused.status_code == 409
    assert state.get_current_project_path() == projects['a']


def test_a_busy_recovery_refuses_instead_of_opening_unchecked(projects):
    client = _app().test_client()
    projects['health'].update(status='busy', message='lock timeout')
    refused = _open(client, projects['a'])
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'busy'
    assert state.get_current_project_path() is None


def test_a_request_for_a_switched_away_project_is_refused(projects):
    def add_route(app):
        @app.route('/api/test/uses-project', methods=['POST'])
        def uses_project():
            try:
                state.get_mex_manager()
            except Exception as e:
                # Routes report their own 500; the 409 must win regardless.
                return jsonify({'success': False, 'error': str(e)}), 500
            return jsonify({'success': True})

    client = _app(add_route).test_client()
    first = _open(client, projects['a']).get_json()['generation']
    second = _open(client, projects['b']).get_json()['generation']
    assert second == first + 1

    stale = client.post('/api/test/uses-project', headers={PROJECT_HEADER: str(first)})
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'project_changed'
    current = client.post('/api/test/uses-project', headers={PROJECT_HEADER: str(second)})
    assert current.get_json()['success']
    # Status is how the window learns the new generation, so a stale header never refuses it.
    status = client.get('/api/mex/status', headers={PROJECT_HEADER: str(first)})
    assert status.status_code == 200
    assert status.get_json()['generation'] == second


def test_a_request_keeps_its_project_while_another_is_opened(projects):
    app = _app()
    state.set_project_path(projects['a'])
    with app.test_request_context('/api/mex/fighters'):
        state.pin_request_project()
        switcher = threading.Thread(target=state.set_project_path, args=(projects['b'],))
        switcher.start()
        switcher.join()
        assert state._current_project_path == projects['b']
        # Still A for this request, and its manager is A's.
        assert state.get_current_project_path() == projects['a']
        manager = state.get_mex_manager()
        assert manager.project_path == projects['a'].resolve()
    # A's manager, built after the switch, was not cached as the open project's.
    assert state._mex_manager is None or state._mex_manager.project_path == projects['b'].resolve()


def test_a_failed_delete_still_reports_the_close(projects, monkeypatch):
    monkeypatch.setattr(project_routes, 'is_managed_project_directory', lambda folder: True)
    monkeypatch.setattr(project_routes, 'PROJECTS_PATH', projects['a'].parent.parent / 'managed-root')

    def refuse(path):
        raise PermissionError('file in use')
    monkeypatch.setattr(project_routes.shutil, 'rmtree', refuse)

    client = _app().test_client()
    _open(client, projects['a'])
    response = client.post('/api/mex/project/delete', json={'projectPath': str(projects['a'])})
    assert response.status_code == 500
    body = response.get_json()
    assert body['currentProjectClosed'] is True
    assert state.get_current_project_path() is None


def test_run_json_protects_the_project_its_command_writes(tmp_path, monkeypatch):
    import mexcli.commands as commands
    from core import build_access
    sessions = []

    class Session:
        def __init__(self, folder):
            self.folder = folder

        def __enter__(self):
            sessions.append(self.folder)
            return self

        def __exit__(self, *exc):
            return False

        def external_save(self, label):
            return Session(self.folder)

    monkeypatch.setattr(build_access, 'build_session', lambda folder, timeout=None: Session(folder))
    monkeypatch.setattr(commands, 'run', lambda args, **kw: type('R', (), {'stdout': '{}', 'returncode': 0})())
    installing = tmp_path / 'installing' / 'project.mexproj'
    monkeypatch.setattr(state, '_current_project_path', tmp_path / 'switched-to' / 'project.mexproj')
    commands.run_json(['add-music', installing, 'theme.hps', 'Theme'])
    assert sessions[0] == installing.parent


def test_open_close_list_and_delete_answer_a_window_on_an_old_generation(projects, monkeypatch):
    """They are how the window catches up after a switch, so a stale header
    never refuses them (project_check_exempt)."""
    managed = projects['a'].parent.parent
    monkeypatch.setattr(project_routes, 'PROJECTS_PATH', managed)
    monkeypatch.setattr(project_routes, 'is_managed_project_directory', lambda folder: True)
    removed = []
    monkeypatch.setattr(project_routes.shutil, 'rmtree', removed.append)
    client = _app().test_client()
    first = _open(client, projects['a']).get_json()['generation']
    _open(client, projects['b'])
    stale = {PROJECT_HEADER: str(first)}

    listed = client.get('/api/mex/project/list', headers=stale)
    assert listed.status_code == 200 and listed.get_json()['success']
    reopened = client.post('/api/mex/project/open', headers=stale,
                           json={'projectPath': str(projects['a'])})
    assert reopened.status_code == 200 and reopened.get_json()['success']
    stale = {PROJECT_HEADER: str(first)}          # still the old one
    closed = client.post('/api/mex/project/close', headers=stale)
    assert closed.status_code == 200 and closed.get_json()['closed'] is True
    deleted = client.post('/api/mex/project/delete', headers=stale,
                          json={'projectPath': str(projects['b'])})
    assert deleted.status_code == 200 and deleted.get_json()['success']
    assert removed == [projects['b'].parent.resolve()]
