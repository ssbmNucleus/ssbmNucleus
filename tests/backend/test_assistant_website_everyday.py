"""Review MM: the ordinary downloads a tester actually makes, with the gate OFF.

The any-mod download gate ships closed, so these are the flows the preview has
to get right: the Download button on a costume card, "Download all" over a page
of them, a costume published as a nested export, a second download of something
already in the vault, and the Slippi fix prompt.

They are driven through the endpoints the viewer calls -- `POST
/api/assistant/website/download` and the approval routes -- with a real engine
run, the real preparation path, the real safety preflight and the real
classifier. Only the website RPC and the network fetch are doubles.
"""
import io
import re
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from randall.assistant import approvals, engine, live_runs, tools
from randall.website import website, website_posts
from tests.backend import website_site
from tests.backend.website_site import media
from randall.routes.assistant_bp import assistant_bp
from core import gates
from tests.backend.window_key import WINDOW, as_the_window  # noqa: F401

pytestmark = pytest.mark.usefixtures('as_the_window')


def _zip(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def _costume_file(file_id, filename, color):
    return {'id': file_id, 'filename': filename, 'character': 'Marth', 'color': color,
            'file_type': 'character_dat', 'file_url': media(f'posts/123/{filename}')}


@pytest.fixture
def site(monkeypatch, vault):
    """A post with one published costume export, and the gate closed."""
    monkeypatch.setenv(gates.GATES['any_mod_download'].env, '0')
    record = {'id': 123, 'title': 'Blue Marth',
              'author': 'Artist', 'description': 'A costume',
              'tags': ['Marth'], 'updated_at': 'v1',
              'zip_url': media('posts/123/files.zip'), 'screenshots': [],
              'files': [_costume_file(42, 'PlMsBu.dat', 'Blue')]}
    website_site.install(monkeypatch, record)
    monkeypatch.setattr(website, '_download',
                        lambda url, path, **kw: Path(path).write_bytes(
                            _zip({'PlMsBu.dat': bytes(64)})))
    monkeypatch.setattr(engine, '_provider',
                        lambda *a, **k: pytest.fail('a download button must not call the LLM'))
    return record


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    return app.test_client()


def _approval(run):
    while True:
        event = run.events.get(timeout=10)
        if event['type'] == 'approval_requested':
            return event['tool']['approval']
        if event['type'] == 'done':
            last = (event.get('message') or {}).get('tools') or [{}]
            pytest.fail(f'no approval was offered: {last[-1].get("result")}')


def _finish(run, client, approval, choice=None):
    body = {'decision': 'approve'}
    if choice is not None:
        body['choice'] = choice
    route = f'/api/assistant/chats/{run.chat_id}/approvals/{approval["id"]}'
    response = client.post(route, headers=WINDOW, json=body)
    assert response.status_code == 200, response.get_json()
    list(live_runs.stream(run))
    from randall.assistant import store
    return store.get(run.chat_id)['messages'][-1]['tools'][0]['result']


# ── 1. the Download button on a single-export costume card ─────────────────

def test_the_download_button_on_a_costume_card_works_with_the_gate_off(site, client, monkeypatch):
    """The card submits the post id alone; that used to read as a whole archive.

    With whole-archive fetching closed the backend refused it, so an ordinary
    costume could not be downloaded at all (2026-09-22 review MM, 1).
    """
    imported = []
    monkeypatch.setattr(website, '_import_archive', lambda path, title, **kwargs: (
        imported.append(kwargs.get('expected_url'))
        or ({'success': True, 'type': 'character', 'imported_count': 1,
             'costumes': [{'character': 'Marth', 'id': 'blue'}],
             'message': 'Imported 1 costume'}, 200)))

    started = client.post('/api/assistant/website/download', json={'post_id': 123})
    assert started.status_code == 200, started.get_json()
    run = live_runs.active_run(started.get_json()['chat_id'])
    try:
        approval = _approval(run)
        # It resolved to the published export, not the forbidden whole archive.
        assert approval['declared_types'] == ['character_dat']
        assert approval['destinations'] == ['Vault > Characters (costumes)']
        result = _finish(run, client, approval)
        assert result['imported_count'] == 1 and not result.get('error')
        assert imported == ['https://ssbmnucleus.net/api/posts/123/export-nucleus/42']
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run():
            list(live_runs.stream(run))


def test_a_colour_family_resolves_to_its_default_colour(site, monkeypatch):
    site['files'] = [_costume_file(50, 'PlMsNr.dat', 'Default'),
                     _costume_file(51, 'PlMsBu.dat', 'Blue'),
                     _costume_file(52, 'PlMsRe.dat', 'Red')]
    plan, preview = website.prepare_download({'post_id': 123})
    assert plan['file_id'] == 50
    assert preview['declared_types'] == ['character_dat']
    from randall.website import website_quarantine
    website_quarantine.release(plan['quarantine']['token'])


def test_several_unrelated_exports_ask_instead_of_guessing(site, monkeypatch):
    site['files'] = [_costume_file(50, 'PlMsNr.dat', 'Default'),
                     {'id': 60, 'filename': 'GrOp.dat', 'character': None, 'color': None,
                      'file_type': 'stage_dat', 'file_url': media('posts/123/GrOp.dat')}]
    monkeypatch.setattr(website, '_download',
                        lambda *a, **k: pytest.fail('must not fetch before it is decided'))
    with pytest.raises(ValueError, match=r'file_id 50.*file_id 60'):
        website.prepare_download({'post_id': 123})


def test_a_post_with_nothing_downloadable_still_refuses_with_the_gate_message(site, monkeypatch):
    site['files'] = [{'id': 70, 'filename': 'Halo3CSS.dat', 'file_type': 'other',
                      'character': None, 'color': None,
                      'file_url': media('posts/123/Halo3CSS.dat')}]
    monkeypatch.setattr(website, '_download',
                        lambda *a, **k: pytest.fail('the gate is closed'))
    with pytest.raises(ValueError, match='ssbmnucleus.net'):
        website.prepare_download({'post_id': 123})


# ── 2. "Download all" over a page of costume posts ─────────────────────────

def test_download_all_builds_export_only_plans(site, client, monkeypatch):
    """"Download all" submits post ids alone, and failed the same way."""
    fetched, imported = [], []
    monkeypatch.setattr(website, '_download', lambda url, path, **kw: (
        fetched.append(url), Path(path).write_bytes(_zip({'PlMsBu.dat': bytes(64)}))))
    monkeypatch.setattr(website, '_import_archive', lambda path, title, **kwargs: (
        imported.append(kwargs.get('expected_url'))
        or ({'success': True, 'type': 'character', 'imported_count': 1,
             'costumes': [{'character': 'Marth', 'id': 'blue'}], 'message': 'ok'}, 200)))

    started = client.post('/api/assistant/website/download',
                          json={'items': [{'post_id': 123}]})
    assert started.status_code == 200, started.get_json()
    run = live_runs.active_run(started.get_json()['chat_id'])
    try:
        approval = _approval(run)
        assert approval['bulk_download'] is True
        result = _finish(run, client, approval, choice='fix')
        assert result['imported_count'] == 1, result
        assert not result.get('error')
        assert imported == ['https://ssbmnucleus.net/api/posts/123/export-nucleus/42']
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run():
            list(live_runs.stream(run))


def test_download_all_with_variants_all_expands_to_every_export(site, monkeypatch):
    from randall.website import website_bulk
    site['files'] = [_costume_file(50, 'PlMsNr.dat', 'Default'),
                     _costume_file(51, 'PlMsBu.dat', 'Blue')]
    plan, _ = website_bulk.prepare_batch({'items': [{'post_id': 123, 'variants': 'all'}]})
    assert [p['file_id'] for p in plan['plans']] == [50, 51]


def test_a_batch_that_would_explode_is_refused_with_a_number(site, monkeypatch):
    from randall.website import website_bulk
    site['files'] = [_costume_file(100 + i, f'PlMs{i:02d}.dat', f'C{i}') for i in range(70)]
    monkeypatch.setattr(website, '_download',
                        lambda *a, **k: pytest.fail('must not fetch a refused batch'))
    with pytest.raises(ValueError, match='more than the 60'):
        website_bulk.prepare_batch({'items': [{'post_id': 123, 'variants': 'all'}]})


# ── 3. a costume published as a NESTED export ──────────────────────────────

def test_a_nested_costume_export_is_charged_once_across_every_pass(site, monkeypatch):
    """The same nested archive was charged again on each pass.

    Safety recursion built occurrence ids from temporary extraction paths while
    normalization kept the original ancestry, so a leaf was paid for by safety,
    by a repeated safety pass and by the description -- and a real nested
    costume export got an approval and then failed at execution with the
    safety-limit error (2026-09-22 review MM, 2).
    """
    from randall.website import website_safety
    from vault.importing.unified.normalize import describe_import_target

    leaf = bytes(200_000)
    nested = _zip({'inner.zip': _zip({'PlMsBu.dat': leaf})})
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / 'export.zip'
        archive.write_bytes(nested)
        budget = website_safety.download_budget()

        website_safety.inspect_archive(archive, budget=budget)
        after_first = budget.used_bytes
        website_safety.inspect_archive(archive, budget=budget)
        describe_import_target(str(archive), 'export.zip', budget=budget)
        from vault.importing.unified.detection import detect_content_type
        detect_content_type(str(archive), 'export.zip', deep=True, budget=budget)

        assert budget.used_bytes == after_first, (
            f'{after_first} charged once, {budget.used_bytes} after three more passes')
        assert after_first >= len(leaf)


def test_a_nested_costume_export_downloads_end_to_end(site, client, monkeypatch):
    """The reviewer's shape: leaf expansion just under the allowance."""
    from randall.website import website_safety
    leaf = bytes(595_148)
    monkeypatch.setattr(website, '_download', lambda url, path, **kw: Path(path).write_bytes(
        _zip({'inner.zip': _zip({'PlMsBu.dat': leaf})})))
    original = website_safety.download_budget

    def tight_budget():
        budget = original()
        budget.max_bytes = 892_722          # the reviewer's reduced allowance
        return budget
    monkeypatch.setattr(website_safety, 'download_budget', tight_budget)
    monkeypatch.setattr(website, '_import_archive',
                        lambda path, title, **kwargs: ({'success': True, 'type': 'character',
                                                        'imported_count': 1,
                                                        'message': 'ok'}, 200))
    started = client.post('/api/assistant/website/download', json={'post_id': 123})
    run = live_runs.active_run(started.get_json()['chat_id'])
    try:
        approval = _approval(run)
        result = _finish(run, client, approval)
        assert result['imported_count'] == 1 and not result.get('error'), result
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run():
            list(live_runs.stream(run))


# ── 4. downloading something already in the vault ──────────────────────────

def test_a_costume_already_owned_is_a_skip_not_a_failure(vault, monkeypatch):
    """The real importer, with every costume in the archive already owned."""
    import vault.routes.import_unified.routes as routes
    import vault.importing.unified.archive as unified_archive
    from vault.routes.import_unified import import_bp
    from vault.importing.unified.helpers import compute_dat_hash

    marth = vault.storage / 'Marth'
    marth.mkdir()
    with zipfile.ZipFile(marth / 'owned.zip', 'w') as zf:
        zf.writestr('PlMsBu.dat', b'the costume')
    vault.write({'characters': {'Marth': {'skins': [{
        'id': 'owned', 'color': 'Blue', 'filename': 'owned.zip',
        'dat_hash': compute_dat_hash(b'the costume')}]}}, 'stages': {}})

    monkeypatch.setattr(unified_archive, 'detect_character_from_zip', lambda _p: [
        {'character': 'Marth', 'color': 'Blue', 'costume_code': 'PlMsBu',
         'dat_file': 'PlMsBu.dat'}])
    monkeypatch.setattr(unified_archive, 'validate_for_slippi',
                        lambda _p, auto_fix=False: {'slippi_safe': True})
    monkeypatch.setattr(unified_archive, 'import_character_costume',
                        lambda *a, **k: pytest.fail('a duplicate must not be imported'))

    app = Flask(__name__)
    app.register_blueprint(import_bp)
    client = app.test_client()
    response = client.post('/api/mex/import/file', data={
        'file': (io.BytesIO(_zip({'PlMsBu.dat': b'the costume'})), 'costume.zip'),
        'duplicate_action': 'skip'}, content_type='multipart/form-data')
    body = response.get_json()
    assert response.status_code == 200, body
    assert body['success'] is True, body
    assert body['imported_count'] == 0 and body['skipped_count'] == 1
    assert body['skipped_duplicates'][0]['existing_skin']['id'] == 'owned'
    assert 'Already in your vault' in body['message']


def test_a_retry_of_an_owned_costume_reports_the_skip_through_the_chat(site, client, monkeypatch):
    monkeypatch.setattr(website, '_import_archive', lambda path, title, **kwargs: (
        {'success': True, 'type': 'character', 'imported_count': 0, 'skipped_count': 1,
         'skipped_duplicates': [{'character': 'Marth',
                                 'existing_skin': {'id': 'owned'}}],
         'message': 'Already in your vault, so nothing was added: Marth Blue'}, 200))
    started = client.post('/api/assistant/website/download', json={'post_id': 123})
    run = live_runs.active_run(started.get_json()['chat_id'])
    try:
        result = _finish(run, client, _approval(run))
        assert result['skipped_count'] == 1 and result['imported_count'] == 0
        assert 'error' not in result, result
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run():
            list(live_runs.stream(run))


# ── 5. the Slippi fix prompt ───────────────────────────────────────────────

def test_an_unsafe_costume_asks_before_fixing_and_the_answer_reaches_the_import(
        site, client, monkeypatch):
    from randall.website import website_safety
    monkeypatch.setattr(website_safety, 'inspect_archive', lambda path, *a, **k: {
        'unsafe_costumes': [{'name': 'PlMsBu.dat', 'character': 'Marth', 'color': 'Blue'}],
        'checked_count': 1,
        'archive_hash': __import__('hashlib').sha256(Path(path).read_bytes()).hexdigest()})
    actions = []
    monkeypatch.setattr(website, '_import_archive', lambda path, title, **kwargs: (
        actions.append(kwargs.get('slippi_action'))
        or ({'success': True, 'type': 'character', 'imported_count': 1,
             'fixed_count': 1, 'message': 'Imported 1 costume'}, 200)))

    started = client.post('/api/assistant/website/download', json={'post_id': 123})
    run = live_runs.active_run(started.get_json()['chat_id'])
    try:
        first = _approval(run)
        route = f'/api/assistant/chats/{run.chat_id}/approvals/{first["id"]}'
        assert client.post(route, headers=WINDOW, json={'decision': 'approve'}).status_code == 200
        safety = _approval(run)
        assert safety['slippi_review'] and safety['default_choice'] == 'fix'
        assert [option['id'] for option in safety['choices']] == ['fix', 'import_as_is']
        result = _finish(run, client, safety, choice='fix')
        assert actions == ['fix']
        assert result['imported_count'] == 1 and result['fixed_count'] == 1
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run():
            list(live_runs.stream(run))
