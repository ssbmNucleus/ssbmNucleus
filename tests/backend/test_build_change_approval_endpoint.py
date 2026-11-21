"""The approval endpoint is the only place a build change is authorized.

Astra's re-review, findings 2, 3 and 6:

* knowing a proposal's digest proves the proposal, not that anybody was shown
  it - a replayed digest minted a second authorization;
* an authenticated foreign-Origin request succeeded;
* the endpoint accepted caller-selected task fields, so an approval could be
  recorded against a request the user never made;
* and the commit gate did not cover approval at all, so an authorization could
  be banked while writing was switched off and spent the moment it opened.

The backend token separates nothing here: the window, the harness and the agent
bridge all send the same one, and it is printed to the backend's stdout at
startup. So the endpoint requires a SECOND secret that Electron gives only the
renderer (`NUCLEUS_UI_APPROVAL_KEY`), never prints and never serves - and
refuses outright when there is none configured.

What these tests still do NOT claim: that this endpoint proves WHO clicked. It
proves the request came from the window; the OS account is audit context.
"""
from tests.paths import APP
import json
import struct
from pathlib import Path

import pytest
from flask import Flask

from core import build_authorization as auth_module, build_transaction as bt
from tests.backend.test_build_commit_transaction import (fake_code_compiler, fake_native_reader,
                                                 make_build, menu_dat, CSS_CODE)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from vault.routes.menus import menus_bp
    from nucleus_api import builds, menus

    builds_root = tmp_path / 'builds'
    builds_root.mkdir()
    build_dir = make_build(builds_root, 'Played')
    workspace = tmp_path / 'workspace'
    (workspace / 'out').mkdir(parents=True)
    (workspace / 'out' / 'MnSlChr.usd').write_bytes(menu_dat(background=b'new'))

    monkeypatch.setenv('NUCLEUS_API_WORKSPACE', str(workspace))
    monkeypatch.setenv('NUCLEUS_API_BUILDS', json.dumps([str(build_dir)]))
    monkeypatch.setenv('NUCLEUS_BUILD_TRUST_ROOT', str(tmp_path / 'trust'))
    monkeypatch.setenv('NUCLEUS_UI_APPROVAL_KEY', UI_KEY)
    monkeypatch.setattr(bt, 'CODE_COMPILER', fake_code_compiler)
    monkeypatch.setattr(menus, 'NATIVE_MENU_READER', fake_native_reader)

    app = Flask(__name__)
    app.register_blueprint(menus_bp)

    build = builds.list_builds()[0]
    artifact = builds.register_artifact('out/MnSlChr.usd', 'css_menu_file')
    change = builds.prepare_change(build['id'], build['revision'], [artifact['id']],
                                   code_changes={'add': [CSS_CODE]},
                                   task_id='task_ui', task_revision=1)
    assert change['status'] == 'prepared', change.get('error')
    return app.test_client(), change, builds


UI_KEY = 'a-key-only-the-window-has'
UI_HEADERS = {'X-Nucleus-UI-Key': UI_KEY}


def _card(client, change_id):
    response = client.get(f'/api/mex/builds/changes/{change_id}', headers=UI_HEADERS)
    assert response.status_code == 200, response.get_json()
    return response.get_json()['change']


def test_the_card_carries_a_challenge_and_the_approval_spends_it(client):
    http, change, _ = client
    card = _card(http, change['prepared_change_id'])
    assert card['challenge'] and card['expires_utc']
    # The card states what it establishes and what it does not.
    assert 'only the window is given' in card['approvalChannel']
    assert 'does not prove WHO clicked' in card['approvalChannel']

    body = {'confirmed': True, 'subjectDigest': card['subjectDigest'],
            'challenge': card['challenge'],
            'acceptedUnknown': card['unknown_dimensions']}
    granted = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                        json=body, headers=UI_HEADERS)
    assert granted.status_code == 200, granted.get_json()
    assert granted.get_json()['authorizationId'].startswith('auth_')

    # Replaying the same card mints nothing: knowing the digest is not a click.
    again = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                      json=body, headers=UI_HEADERS)
    assert again.status_code == 409
    assert again.get_json()['code'] == 'challenge_spent'


def test_a_digest_without_the_card_approves_nothing(client):
    http, change, _ = client
    card = _card(http, change['prepared_change_id'])
    response = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                         json={'confirmed': True, 'subjectDigest': card['subjectDigest'],
                               'acceptedUnknown': card['unknown_dimensions']},
                         headers=UI_HEADERS)
    assert response.status_code == 409
    assert response.get_json()['code'] == 'challenge_mismatch'


def test_an_approval_from_another_origin_is_refused(client):
    http, change, _ = client
    card = _card(http, change['prepared_change_id'])
    body = {'confirmed': True, 'subjectDigest': card['subjectDigest'],
            'challenge': card['challenge'], 'acceptedUnknown': card['unknown_dimensions']}
    response = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                         json=body, headers={**UI_HEADERS, 'Origin': 'https://example.invalid'})
    assert response.status_code == 403
    assert response.get_json()['code'] == 'foreign_origin'

    cross = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                      json=body, headers={**UI_HEADERS, 'Sec-Fetch-Site': 'cross-site'})
    assert cross.status_code == 403


def test_the_task_comes_from_the_proposal_not_the_request(client):
    http, change, _ = client
    card = _card(http, change['prepared_change_id'])
    response = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                         json={'confirmed': True, 'subjectDigest': card['subjectDigest'],
                               'challenge': card['challenge'],
                               'taskId': 'a_task_the_user_never_made',
                               'taskRevision': 99,
                               'acceptedUnknown': card['unknown_dimensions']},
                         headers=UI_HEADERS)
    assert response.status_code == 200, response.get_json()
    record = auth_module.load(response.get_json()['authorizationId'])
    assert record['task_id'] == 'task_ui' and record['task_revision'] == 1


def test_an_unconfirmed_request_approves_nothing(client):
    http, change, _ = client
    card = _card(http, change['prepared_change_id'])
    response = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                         json={'subjectDigest': card['subjectDigest'],
                               'challenge': card['challenge']},
                         headers=UI_HEADERS)
    assert response.status_code == 400
    assert response.get_json()['code'] == 'not_confirmed'


def test_nothing_is_approved_while_build_writing_is_switched_off(client, monkeypatch):
    """A banked approval would be spendable the moment the gate opened."""
    http, change, _ = client
    card = _card(http, change['prepared_change_id'])
    monkeypatch.setenv('NUCLEUS_BUILD_COMMIT', '0')
    response = http.post(f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
                         json={'confirmed': True, 'subjectDigest': card['subjectDigest'],
                               'challenge': card['challenge'],
                               'acceptedUnknown': card['unknown_dimensions']},
                         headers=UI_HEADERS)
    assert response.status_code == 409
    assert response.get_json()['code'] == 'build_commit_disabled'


def test_the_compatibility_manifest_is_served_read_only(client):
    http, _, _ = client
    response = http.get('/api/mex/menus/compatibility')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['manifestVersion'] >= 2
    assert any(p['package_id'] == 'halo3-matchmaking-lobby' for p in payload['packages'])


def test_the_backend_token_alone_does_not_reach_this_endpoint(client):
    """The harness holds that token: it is printed to stdout at startup."""
    http, change, _ = client
    card = http.get(f'/api/mex/builds/changes/{change["prepared_change_id"]}')
    assert card.status_code == 403
    assert card.get_json()['code'] == 'not_the_app_window'

    approve = http.post(
        f'/api/mex/builds/changes/{change["prepared_change_id"]}/approve',
        json={'confirmed': True, 'subjectDigest': 'x', 'challenge': 'y'})
    assert approve.status_code == 403
    assert approve.get_json()['code'] == 'not_the_app_window'


def test_an_agent_session_cannot_approve_even_with_the_window_key(client):
    http, change, _ = client
    response = http.get(f'/api/mex/builds/changes/{change["prepared_change_id"]}',
                        headers={**UI_HEADERS, 'X-Nucleus-Agent-Session': 'randall'})
    assert response.status_code == 403
    assert response.get_json()['code'] == 'automation_caller'


def test_without_a_configured_channel_the_endpoint_refuses_outright(client, monkeypatch):
    """Fail closed: an approval nobody can attribute is worse than none."""
    http, change, _ = client
    monkeypatch.delenv('NUCLEUS_UI_APPROVAL_KEY', raising=False)
    response = http.get(f'/api/mex/builds/changes/{change["prepared_change_id"]}',
                        headers=UI_HEADERS)
    assert response.status_code == 503
    assert response.get_json()['code'] == 'ui_approval_channel_unavailable'


def test_electron_hands_the_window_a_key_it_never_prints():
    """The backend half is useless unless the window is actually given one."""
    electron = APP / 'electron'
    main = (electron / 'main.js').read_text(encoding='utf-8')
    preload = (electron / 'preload.js').read_text(encoding='utf-8')
    assert 'const uiApprovalKey = crypto.randomBytes' in main
    assert 'backendEnv.NUCLEUS_UI_APPROVAL_KEY = uiApprovalKey;' in main
    # over IPC, to the app's own page only; never on the renderer's command line (security review 11-19, L1)
    assert "event.returnValue = { backendToken, uiApprovalKey };" in main
    assert '--ui-approval-key=' not in main and '--backend-token=' not in main
    # and it is redacted from anything the app reports back
    assert 'secrets: [backendToken, uiApprovalKey]' in main
    assert "ipcRenderer.sendSync('renderer:secrets')" in preload and 'uiApprovalKey,' in preload
    assert '--ui-approval-key=' not in preload and '--backend-token=' not in preload
