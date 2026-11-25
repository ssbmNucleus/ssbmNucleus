import hashlib
import io
import time
import zipfile
from pathlib import Path

import pytest

from randall.assistant import approvals, engine, live_runs, store, tools
from randall.website import website, website_safety
from tests.backend.test_assistant_website import catalog
from tests.backend.window_key import WINDOW, as_the_window  # noqa: F401

pytestmark = pytest.mark.usefixtures('as_the_window')


@pytest.fixture
def unsafe_download(catalog, monkeypatch):
    """A download that is a REAL archive and a safety verdict about its bytes.

    `paths` collects the archive the preflight was actually handed -- the
    staged object the import will use -- so a test can change it underneath
    the review and see the binding refuse.
    """
    downloads, imports, paths = [], [], []

    def download(url, path, **kwargs):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('PlMsBu.dat', b'unsafe costume')
        path.write_bytes(buffer.getvalue())
        downloads.append(url)
    monkeypatch.setattr(website, '_download', download)

    def inspect(path, *args, **kwargs):
        paths.append(Path(path))
        return {'unsafe_costumes': [{'name': 'PlMsBu.dat', 'character': 'Marth', 'color': 'Blue'}],
                'checked_count': 1,
                'archive_hash': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    monkeypatch.setattr(website_safety, 'inspect_archive', inspect)

    def importer(path, title, slippi_action, protocol_url, expected_url, **kwargs):
        from vault.importing.unified.protocol import parse_import_link
        assert parse_import_link(protocol_url)['url'] == expected_url
        imports.append(slippi_action)
        return {'success': True, 'imported_count': 1, 'fixed_count': int(slippi_action == 'fix')}, 200
    monkeypatch.setattr(website, '_import_archive', importer)
    return downloads, imports, paths


@pytest.mark.parametrize('decision', ['fix', 'import_as_is', 'deny', 'cancel', 'expire'])
def test_download_pauses_before_import_for_exact_safety_choice(vault, unsafe_download, monkeypatch, decision):
    downloads, imports, paths = unsafe_download
    monkeypatch.setattr(engine, '_provider', lambda *args: pytest.fail('No LLM for download or safety review'))
    run = engine.start_download(None, 123)
    def next_approval():
        while True:
            event = run.events.get(timeout=5)
            if event['type'] == 'approval_requested': return event['tool']['approval']
    try:
        initial = next_approval()
        # The object is fetched into quarantine to build the card; the import
        # still waits for the approval.
        assert len(downloads) == 1 and not imports
        live_runs.decide_approval(run.chat_id, initial['id'], 'approve')
        safety = next_approval()
        assert len(downloads) == 1 and not imports   # the held bytes were used
        assert safety['slippi_review'] and safety['default_choice'] == 'fix'
        assert paths[0].exists()
        # The original approval remains independently retryable.
        live_runs.decide_approval(run.chat_id, initial['id'], 'approve')
        with pytest.raises(ValueError):
            live_runs.decide_approval(run.chat_id, safety['id'], 'approve', 'all')
        if decision in ('fix', 'import_as_is'):
            from flask import Flask
            from randall.routes.assistant_bp import assistant_bp
            app = Flask(__name__); app.register_blueprint(assistant_bp)
            response = app.test_client().post(f"/api/assistant/chats/{run.chat_id}/approvals/{safety['id']}",
                                             headers=WINDOW, json={'decision': 'approve', 'choice': decision})
            assert response.status_code == 200, response.get_json()
        elif decision == 'cancel':
            live_runs.cancel(run.id)
        elif decision == 'expire':
            with run.condition:
                run.messages[-1]['tools'][-1]['approval']['expires_at'] = time.time() - 1
                run.condition.notify_all()
        else:
            live_runs.decide_approval(run.chat_id, safety['id'], 'deny')
        list(live_runs.stream(run))
        assert imports == ([decision] if decision in ('fix', 'import_as_is') else [])
        assert not paths[0].parent.exists()
        if imports:
            result = store.get(run.chat_id)['messages'][-1]['tools'][0]['result']
            assert result['slippi_action'] == decision and result['imported_count'] == 1
            live_runs.decide_approval(run.chat_id, safety['id'], 'approve', decision)
            assert len(imports) == 1
    finally:
        live_runs.cancel(run.id)
        if live_runs.active_run(): list(live_runs.stream(run))


def test_unsafe_download_cannot_silently_fix_without_review(unsafe_download):
    call = tools.prepare('download_website_mod', {'post_id': 123})
    result = tools.execute(call, approvals.Grant(call.fingerprint))
    assert 'Slippi safety approval' in result['error']
    assert not unsafe_download[1]


def test_changed_download_after_safety_review_never_imports(unsafe_download):
    def review(*args):
        unsafe_download[2][0].write_bytes(b'changed')
        return {'action': 'fix'}
    call = tools.prepare('download_website_mod', {'post_id': 123})
    result = tools.execute(call, approvals.Grant(call.fingerprint), safety_review=review)
    assert 'changed during safety review' in result['error']
    assert not unsafe_download[1]


def test_nested_archive_preflight_checks_all_before_any_mutation(tmp_path, monkeypatch):
    import dat_processor
    from vault.importing.unified import detection
    from vault.importing import character_detector
    def make_zip(entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as z:
            for name, content in entries.items(): z.writestr(name, content)
        return output.getvalue()
    path = tmp_path / 'pack.zip'
    original = make_zip({'safe.dat': b'safe', 'inner.zip': make_zip({'unsafe.dat': b'unsafe'})})
    path.write_bytes(original)
    def detect(p):
        with zipfile.ZipFile(p) as z:
            return [{'dat_file': name, 'character': 'Fox', 'color': 'Green'} for name in z.namelist() if name.endswith('.dat')]
    checks = []
    def validate(p, auto_fix):
        checks.append(Path(p).read_bytes()); assert auto_fix is False
        return {'slippi_safe': checks[-1] == b'safe'}
    from pathlib import Path
    monkeypatch.setattr(character_detector, 'detect_character_from_zip', detect)
    monkeypatch.setattr(dat_processor, 'validate_for_slippi', validate)
    monkeypatch.setattr(detection, 'detect_content_type', lambda *args, **kwargs: {'type': 'unknown'})
    result = website_safety.inspect_archive(path)
    assert result['checked_count'] == 2 and len(checks) == 2
    assert result['unsafe_costumes'][0]['name'] == 'inner.zip / unsafe.dat'
    assert path.read_bytes() == original


def test_preflight_cancellation_does_not_check_files(tmp_path):
    with pytest.raises(ValueError, match='cancelled'):
        website_safety.inspect_archive(tmp_path / 'never-opened.zip', lambda: True)
