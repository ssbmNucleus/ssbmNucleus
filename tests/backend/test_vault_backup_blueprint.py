"""Tests for the vault backup/restore/clear blueprint.

Focus is the *merge* restore mode, which previously let ``zipf.extractall``
overwrite ``metadata.json`` -- wiping the current vault index instead of merging.
These tests pin the merge semantics (current items kept, backup items added,
no duplicates) and cover backup, replace-restore, and clear for good measure.

All filesystem state is redirected to ``tmp_path`` via monkeypatch, so the real
vault under ``storage/`` is never touched.
"""

from tests.paths import BACKEND
import io
import json
import sqlite3
import sys
import time
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from flask import Flask


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.routes import vault_backup  # noqa: E402
from core import jobs  # noqa: E402
import core.state as core_state  # noqa: E402
from shared.routes.jobs import jobs_bp  # noqa: E402
import core.config as core_config  # noqa: E402
import core.vault as vaultmod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _RecordingSocket:
    """Captures socketio.emit calls so tests can read the restore job's events."""
    def __init__(self):
        self.events = []

    def emit(self, event, data=None):
        self.events.append((event, data))


class _SyncThread:
    """Stand-in for threading.Thread that runs the target inline on start(), so
    the restore worker completes synchronously within the request under test."""
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    """Redirect the blueprint's storage/project/logs paths into tmp_path and
    return a Flask test client plus the patched paths. The restore job runs
    synchronously, its records go under tmp_path, and its events are captured."""
    project_root = tmp_path / 'project'
    storage_path = project_root / 'storage'
    logs_path = project_root / 'logs'
    for p in (storage_path, logs_path):
        p.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(vault_backup, 'PROJECT_ROOT', project_root)
    monkeypatch.setattr(vault_backup, 'STORAGE_PATH', storage_path)
    monkeypatch.setattr(vault_backup, 'LOGS_PATH', logs_path)

    sock = _RecordingSocket()
    monkeypatch.setattr(core_state, 'get_socketio', lambda: sock)
    monkeypatch.setattr(jobs.threading, 'Thread', _SyncThread)
    monkeypatch.setattr(jobs, '_root_override', tmp_path / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})

    app = Flask(__name__)
    app.register_blueprint(vault_backup.vault_backup_bp)
    app.register_blueprint(jobs_bp)
    client = app.test_client()

    return type('VaultEnv', (), {
        'client': client,
        'project_root': project_root,
        'storage_path': storage_path,
        'logs_path': logs_path,
        'socket': sock,
    })


def _restore_records(env):
    return [d for e, d in env.socket.events if e == 'job' and d['kind'] == vault_backup.RESTORE_KIND]


def _restore_job(env):
    """The final record of the most recent restore job, from its `job` events."""
    return next((d for d in reversed(_restore_records(env)) if d['status'] in jobs.FINAL), None)


def _restore_done(env):
    """The finished restore's result (plus its id), or None if it did not finish."""
    job = _restore_job(env)
    return {**job['result'], 'restore_id': job['id']} if job and job['status'] == 'done' else None


def _restore_failed(env):
    job = _restore_job(env)
    return {'error': job['error'], 'restore_id': job['id']} if job and job['status'] == 'failed' else None


def _write_metadata(storage_path, metadata):
    (storage_path / 'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')


def _read_metadata(storage_path):
    return json.loads((storage_path / 'metadata.json').read_text(encoding='utf-8'))


def _make_backup_zip(metadata, extra_files=None):
    """Build an in-memory backup zip with metadata.json + optional data files.

    ``extra_files`` maps archive-relative posix paths to bytes.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('metadata.json', json.dumps(metadata))
        for arcname, content in (extra_files or {}).items():
            zf.writestr(arcname, content)
    buf.seek(0)
    return buf


def _skin(skin_id, color=None):
    return {'id': skin_id, 'color': color or skin_id, 'filename': f'{skin_id}.zip'}


def _variant(variant_id, name=None):
    return {'id': variant_id, 'name': name or variant_id, 'filename': f'{variant_id}.zip'}


# ---------------------------------------------------------------------------
# Pure merge function: merge_vault_metadata
# ---------------------------------------------------------------------------

def test_merge_keeps_current_and_adds_new_skins():
    current = {'characters': {'Fox': {'skins': [_skin('fox-red')]}}}
    incoming = {'characters': {'Fox': {'skins': [_skin('fox-blue')]}}}

    merged, stats = vault_backup.merge_vault_metadata(current, incoming)

    ids = [s['id'] for s in merged['characters']['Fox']['skins']]
    assert ids == ['fox-red', 'fox-blue']  # current first, backup appended
    assert stats['characters'] == 1


def test_merge_does_not_duplicate_shared_skins():
    current = {'characters': {'Fox': {'skins': [_skin('fox-red'), _skin('fox-blue')]}}}
    incoming = {'characters': {'Fox': {'skins': [_skin('fox-blue'), _skin('fox-green')]}}}

    merged, stats = vault_backup.merge_vault_metadata(current, incoming)

    ids = [s['id'] for s in merged['characters']['Fox']['skins']]
    assert ids == ['fox-red', 'fox-blue', 'fox-green']  # blue not duplicated
    assert stats['characters'] == 1


def test_merge_adds_character_absent_from_current():
    current = {'characters': {'Fox': {'skins': [_skin('fox-red')]}}}
    incoming = {'characters': {'Marth': {'skins': [_skin('marth-black'), _skin('marth-white')]}}}

    merged, stats = vault_backup.merge_vault_metadata(current, incoming)

    assert set(merged['characters']) == {'Fox', 'Marth'}
    assert [s['id'] for s in merged['characters']['Marth']['skins']] == ['marth-black', 'marth-white']
    assert stats['characters'] == 2  # whole new character's skins counted


def test_merge_handles_stage_variants():
    current = {'stages': {'battlefield': {'variants': [_variant('bf-a')]}}}
    incoming = {'stages': {
        'battlefield': {'variants': [_variant('bf-a'), _variant('bf-b')]},
        'dreamland': {'variants': [_variant('dl-a')]},
    }}

    merged, stats = vault_backup.merge_vault_metadata(current, incoming)

    assert [v['id'] for v in merged['stages']['battlefield']['variants']] == ['bf-a', 'bf-b']
    assert [v['id'] for v in merged['stages']['dreamland']['variants']] == ['dl-a']
    assert stats['stages'] == 2  # bf-b + dreamland's dl-a


def test_merge_dedupes_skin_folder_markers_by_id():
    folder = {'type': 'folder', 'id': 'folder_abc', 'name': 'Animelee', 'expanded': True}
    current = {'characters': {'Peach': {'skins': [folder, _skin('peach-a')]}}}
    incoming = {'characters': {'Peach': {'skins': [folder, _skin('peach-b')]}}}

    merged, stats = vault_backup.merge_vault_metadata(current, incoming)

    ids = [s['id'] for s in merged['characters']['Peach']['skins']]
    assert ids == ['folder_abc', 'peach-a', 'peach-b']  # folder not duplicated
    assert stats['characters'] == 1


def test_merge_top_level_lists_by_identity_key():
    current = {
        'xdelta': [{'id': 'x1', 'name': 'patch one'}],
        'custom_characters': [{'slug': 'wolf-2', 'name': 'Wolf'}],
        'bundles': [{'id': 'b1', 'name': 'Bundle One'}],
    }
    incoming = {
        'xdelta': [{'id': 'x1', 'name': 'patch one'}, {'id': 'x2', 'name': 'patch two'}],
        'custom_characters': [{'slug': 'roy-2', 'name': 'Roy'}],
        'custom_stages': [{'slug': 'castle-64', 'name': "Peach's Castle"}],
        'bundles': [{'id': 'b1', 'name': 'Bundle One'}],
    }

    merged, stats = vault_backup.merge_vault_metadata(current, incoming)

    assert [x['id'] for x in merged['xdelta']] == ['x1', 'x2']
    assert {c['slug'] for c in merged['custom_characters']} == {'wolf-2', 'roy-2'}
    assert [s['slug'] for s in merged['custom_stages']] == ['castle-64']
    assert [b['id'] for b in merged['bundles']] == ['b1']  # no dupe
    assert stats == {'characters': 0, 'stages': 0, 'xdelta': 1,
                     'custom_characters': 1, 'custom_stages': 1, 'bundles': 0, 'extras': 0}


def test_merge_does_not_mutate_inputs():
    current = {'characters': {'Fox': {'skins': [_skin('fox-red')]}}}
    incoming = {'characters': {'Fox': {'skins': [_skin('fox-blue')]}}}

    vault_backup.merge_vault_metadata(current, incoming)

    assert [s['id'] for s in current['characters']['Fox']['skins']] == ['fox-red']
    assert [s['id'] for s in incoming['characters']['Fox']['skins']] == ['fox-blue']


def test_merge_preserves_unknown_top_level_keys():
    current = {'version': '1.0', 'characters': {}}
    incoming = {'version': '1.0', 'menus': {'foo': 'bar'}, 'characters': {}}

    merged, _ = vault_backup.merge_vault_metadata(current, incoming)

    assert merged['version'] == '1.0'
    assert merged['menus'] == {'foo': 'bar'}  # carried over from incoming


def test_merge_into_empty_current():
    incoming = {'characters': {'Fox': {'skins': [_skin('fox-red')]}}}

    merged, stats = vault_backup.merge_vault_metadata({}, incoming)

    assert [s['id'] for s in merged['characters']['Fox']['skins']] == ['fox-red']
    assert stats['characters'] == 1


# ---------------------------------------------------------------------------
# Restore endpoint -- merge mode (the regression under test)
# ---------------------------------------------------------------------------

def test_restore_merge_keeps_current_vault_items(vault_env):
    # Current vault has Fox; backup has Marth + an extra Fox skin.
    _write_metadata(vault_env.storage_path, {
        'characters': {'Fox': {'skins': [_skin('fox-red')]}},
    })
    backup = _make_backup_zip({
        'characters': {
            'Fox': {'skins': [_skin('fox-blue')]},
            'Marth': {'skins': [_skin('marth-black')]},
        },
    }, extra_files={'Marth/marth-black.zip': b'marth-data'})

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['mode'] == 'merge'

    meta = _read_metadata(vault_env.storage_path)
    # Current Fox skin is NOT wiped; backup items added.
    assert [s['id'] for s in meta['characters']['Fox']['skins']] == ['fox-red', 'fox-blue']
    assert 'Marth' in meta['characters']
    # Backup data file landed on disk.
    assert (vault_env.storage_path / 'Marth' / 'marth-black.zip').read_bytes() == b'marth-data'


def test_restore_merge_does_not_overwrite_existing_data_files(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (vault_env.storage_path / 'Fox').mkdir()
    (vault_env.storage_path / 'Fox' / 'fox-red.zip').write_bytes(b'current-data')

    backup = _make_backup_zip(
        {'characters': {'Fox': {'skins': [_skin('fox-red')]}}},
        extra_files={'Fox/fox-red.zip': b'backup-data'},
    )

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    # Existing file preserved (current wins), not clobbered by the backup copy.
    assert (vault_env.storage_path / 'Fox' / 'fox-red.zip').read_bytes() == b'current-data'


def test_restore_merge_reports_added_count(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    backup = _make_backup_zip({'characters': {'Fox': {'skins': [_skin('fox-blue'), _skin('fox-green')]}}})

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    # The route returns a restore_id immediately; the added count + message land
    # in the vault_restore_complete socket event.
    assert resp.status_code == 200
    assert resp.get_json()['restore_id']
    done = _restore_done(vault_env)
    assert done['added']['characters'] == 2
    assert '2 new item' in done['message']


def test_restore_merge_does_not_leak_backup_files_into_kept_custom_character(vault_env):
    # The vault has custom character 'wolf' with 2 costumes; the backup has a
    # DIFFERENT 'wolf' build with extra costume files. Merge must keep ours
    # ATOMICALLY -- the backup's extra files must NOT leak into wolf's folder.
    _write_metadata(vault_env.storage_path, {
        'characters': {}, 'stages': {},
        'custom_characters': [{'slug': 'wolf', 'name': 'Wolf', 'costume_count': 2}],
    })
    wolf = vault_env.storage_path / 'custom_characters' / 'wolf'
    (wolf / 'costumes').mkdir(parents=True)
    (wolf / 'fighter.dat').write_bytes(b'CURRENT')
    (wolf / 'costumes' / 'red.png').write_bytes(b'cur-red')

    backup = _make_backup_zip(
        {'custom_characters': [
            {'slug': 'wolf', 'name': 'Wolf', 'costume_count': 4},
            {'slug': 'fawful', 'name': 'Fawful'},
        ]},
        extra_files={
            'custom_characters/wolf/fighter.dat': b'BACKUP',         # conflict -> skip
            'custom_characters/wolf/costumes/green.png': b'bak-green',  # would leak
            'custom_characters/wolf/costumes/yellow.png': b'bak-yel',   # would leak
            'custom_characters/fawful/fighter.dat': b'new-fawful',      # new -> copy
        },
    )

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 200

    # Wolf is untouched: original files only, no backup leakage.
    assert (wolf / 'fighter.dat').read_bytes() == b'CURRENT'
    assert sorted(p.name for p in (wolf / 'costumes').iterdir()) == ['red.png']
    # The genuinely-new character came in whole.
    assert (vault_env.storage_path / 'custom_characters' / 'fawful' / 'fighter.dat').exists()

    done = _restore_done(vault_env)
    assert done['report']['kept']['custom_characters'] == ['Wolf']
    assert done['report']['added']['custom_characters'] == ['Fawful']


def test_merge_plan_classifies_added_vs_kept_per_type():
    current = {
        'custom_characters': [{'slug': 'wolf', 'name': 'Wolf'}],
        'characters': {'Fox': {'skins': [{'id': 'fox-a', 'color': 'red'}]}},
        'stages': {'dreamland': {'variants': [{'id': 'dl-a', 'name': 'Cotton'}]}},
    }
    incoming = {
        'custom_characters': [{'slug': 'wolf', 'name': 'Wolf'},
                              {'slug': 'geno', 'name': 'Geno'}],
        'characters': {'Fox': {'skins': [{'id': 'fox-a', 'color': 'red'}, {'id': 'fox-b', 'color': 'blue'}]}},
        'stages': {'dreamland': {'variants': [{'id': 'dl-a', 'name': 'Cotton'}, {'id': 'dl-b', 'name': 'Neon'}]}},
    }

    report, skip = vault_backup.merge_plan(current, incoming)

    assert report['added']['custom_characters'] == ['Geno']
    assert report['kept']['custom_characters'] == ['Wolf']
    assert report['added']['skins'] == ['Fox blue']
    assert report['kept']['skins'] == ['Fox red']
    assert report['added']['variants'] == ['dreamland: Neon']
    assert report['kept']['variants'] == ['dreamland: Cotton']
    # Conflicting items contribute skip prefixes; new ones do not.
    assert 'custom_characters/wolf/' in skip
    assert 'custom_characters/geno/' not in skip
    assert 'Fox/fox-a.' in skip and 'Fox/fox-a_' in skip
    assert 'das/dreamland/dl-a.' in skip


def test_restore_emits_progress_and_completion_events(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Marth': {'skins': [_skin('marth-black')]}}})
    backup = _make_backup_zip(
        {'characters': {'Fox': {'skins': [_skin('fox-red')]}}},
        extra_files={f'Fox/file{i}.bin': b'x' * 8 for i in range(5)},
    )

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'replace', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    records = _restore_records(vault_env)
    progress = [d for d in records if d['status'] == 'running' and d['progress'] is not None]
    assert progress, 'expected progress events'
    # Progress is non-decreasing and bounded, and every step says what it is doing.
    fractions = [d['progress'] for d in progress]
    assert fractions == sorted(fractions)
    assert all(0 <= f <= 1 for f in fractions)
    assert all(d['detail'] for d in progress)
    # Ends done, never failed.
    assert records[-1]['status'] == 'done'
    assert not [d for d in records if d['status'] == 'failed']


# ---------------------------------------------------------------------------
# Restore endpoint -- replace mode
# ---------------------------------------------------------------------------

def test_restore_replace_wipes_current_and_extracts_backup(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (vault_env.storage_path / 'Fox').mkdir()
    (vault_env.storage_path / 'Fox' / 'fox-red.zip').write_bytes(b'current-data')

    backup = _make_backup_zip(
        {'characters': {'Marth': {'skins': [_skin('marth-black')]}}},
        extra_files={'Marth/marth-black.zip': b'marth-data'},
    )

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'replace', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    meta = _read_metadata(vault_env.storage_path)
    assert 'Fox' not in meta['characters']  # wiped
    assert 'Marth' in meta['characters']
    assert not (vault_env.storage_path / 'Fox').exists()
    assert (vault_env.storage_path / 'Marth' / 'marth-black.zip').exists()


def test_restore_defaults_to_replace_mode(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    backup = _make_backup_zip({'characters': {'Marth': {'skins': [_skin('marth-black')]}}})

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'file': (backup, 'backup.zip')},  # no mode -> replace
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    assert resp.get_json()['mode'] == 'replace'
    meta = _read_metadata(vault_env.storage_path)
    assert 'Fox' not in meta['characters']


# ---------------------------------------------------------------------------
# Restore endpoint -- validation / error paths
# ---------------------------------------------------------------------------

def test_restore_rejects_missing_file(vault_env):
    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge'},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


def test_restore_rejects_non_zip(vault_env):
    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (io.BytesIO(b'nope'), 'backup.txt')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 400
    assert 'ZIP' in resp.get_json()['error']


def test_restore_echoes_client_id_in_early_events(vault_env):
    restore_id = 'a42b1234-1111-4222-8333-987654321abc'
    response = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'restore_id': restore_id,
              'file': (_make_backup_zip({}), 'backup.zip')},
        content_type='multipart/form-data')
    assert response.status_code == 200
    assert response.get_json()['restore_id'] == restore_id
    # The synchronous worker emits completion before the route returns.
    assert _restore_done(vault_env)['restore_id'] == restore_id


def test_restore_rejects_unknown_mode_without_changing_storage(vault_env):
    original = {'characters': {'Fox': {'skins': [_skin('keep')]}}}
    _write_metadata(vault_env.storage_path, original)
    response = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'typo', 'file': (_make_backup_zip({}), 'backup.zip')},
        content_type='multipart/form-data')
    assert response.status_code == 400
    assert _read_metadata(vault_env.storage_path) == original
    assert vault_env.socket.events == []


def test_replace_restore_verifies_db_before_publishing(vault_env, monkeypatch):
    original = {'bundles': [{'id': 'keep'}]}
    _write_metadata(vault_env.storage_path, original)
    _use_db(monkeypatch, vault_env.storage_path)
    vaultmod.save_blob(original)
    response = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'replace', 'file': (_make_backup_zip({'bundles': [{'id': 'new'}]}), 'backup.zip')},
        content_type='multipart/form-data')
    assert response.status_code == 200
    done = _restore_done(vault_env)
    assert vaultmod.load_blob() == {'bundles': [{'id': 'new'}]}
    previous = Path(done['recovery_path'])
    assert vaultmod.load_blob(path=previous / 'vault.db') == original
    assert json.loads((previous / 'metadata.json').read_text()) == original


def test_replace_db_failure_preserves_active_catalog(vault_env, monkeypatch):
    original = {'bundles': [{'id': 'keep'}]}
    _write_metadata(vault_env.storage_path, original)
    _use_db(monkeypatch, vault_env.storage_path)
    vaultmod.save_blob(original)
    def fail_save(*args, **kwargs):
        raise OSError('cannot build replacement database')
    monkeypatch.setattr(vaultmod, 'save_blob', fail_save)
    response = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'replace', 'file': (_make_backup_zip({'bundles': []}), 'backup.zip')},
        content_type='multipart/form-data')
    assert response.status_code == 200  # worker error is delivered as an event
    assert 'cannot build' in _restore_failed(vault_env)['error']
    assert _read_metadata(vault_env.storage_path) == original
    assert vaultmod.load_blob() == original
    assert not list(vault_env.project_root.glob('.vault-previous-*'))


def test_restore_rejects_zip_without_metadata(vault_env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('Fox/fox-red.zip', b'data')  # no metadata.json
    buf.seek(0)

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (buf, 'backup.zip')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 400
    assert 'metadata.json' in resp.get_json()['error']


def test_restore_merge_leaves_vault_intact_when_backup_invalid(vault_env):
    # An invalid backup must not have already wiped/altered the vault.
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (io.BytesIO(b'not a zip'), 'backup.txt')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 400
    meta = _read_metadata(vault_env.storage_path)
    assert [s['id'] for s in meta['characters']['Fox']['skins']] == ['fox-red']


# ---------------------------------------------------------------------------
# Backup endpoint + round-trip
# ---------------------------------------------------------------------------

def test_backup_creates_zip_with_all_files(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (vault_env.storage_path / 'Fox').mkdir()
    (vault_env.storage_path / 'Fox' / 'fox-red.zip').write_bytes(b'fox-data')

    resp = vault_env.client.post('/api/mex/storage/backup')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True

    backup_path = Path(body['path'])
    assert backup_path.exists()
    with zipfile.ZipFile(backup_path, 'r') as zf:
        names = set(zf.namelist())
    # Paths are stored relative to STORAGE_PATH (posix separators in zip).
    assert 'metadata.json' in names
    assert 'Fox/fox-red.zip' in names


def test_backup_then_restore_merge_round_trip(vault_env):
    # Build a vault, back it up, mutate, then merge the backup back in.
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (vault_env.storage_path / 'Fox').mkdir()
    (vault_env.storage_path / 'Fox' / 'fox-red.zip').write_bytes(b'fox-data')

    backup_resp = vault_env.client.post('/api/mex/storage/backup').get_json()
    backup_path = Path(backup_resp['path'])

    # Replace current vault with a different character.
    _write_metadata(vault_env.storage_path, {'characters': {'Marth': {'skins': [_skin('marth-black')]}}})

    with open(backup_path, 'rb') as f:
        backup_bytes = io.BytesIO(f.read())

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (backup_bytes, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    meta = _read_metadata(vault_env.storage_path)
    # Both the current Marth and the restored Fox are present.
    assert set(meta['characters']) == {'Fox', 'Marth'}
    assert (vault_env.storage_path / 'Fox' / 'fox-red.zip').read_bytes() == b'fox-data'


# ---------------------------------------------------------------------------
# Clear endpoint
# ---------------------------------------------------------------------------

def test_clear_storage_removes_character_folders_and_resets_metadata(vault_env):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (vault_env.storage_path / 'Fox').mkdir()
    (vault_env.storage_path / 'Fox' / 'fox-red.zip').write_bytes(b'fox-data')
    # 'das' folder should be preserved structurally (stage root), its variants cleared.
    das = vault_env.storage_path / 'das'
    das.mkdir()

    resp = vault_env.client.post('/api/mex/storage/clear', json={})

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert not (vault_env.storage_path / 'Fox').exists()
    assert das.exists()  # das root kept
    meta = _read_metadata(vault_env.storage_path)
    assert meta == {'version': '1.0', 'characters': {}, 'stages': {}}


def test_clear_storage_optionally_clears_logs(vault_env):
    (vault_env.logs_path / 'app.log').write_text('log line', encoding='utf-8')
    (vault_env.logs_path / 'keep.txt').write_text('keep', encoding='utf-8')

    resp = vault_env.client.post('/api/mex/storage/clear', json={'clearLogs': True})

    assert resp.status_code == 200
    assert not (vault_env.logs_path / 'app.log').exists()  # .log removed
    assert (vault_env.logs_path / 'keep.txt').exists()      # non-log kept


# ---------------------------------------------------------------------------
# SQLite backend interaction: vault.db is a rebuildable cache, excluded from
# backups and rebuilt from the restored metadata.json (docs/VAULT_SQLITE_MIGRATION.md)
# ---------------------------------------------------------------------------

def _use_db(monkeypatch, storage_path):
    monkeypatch.setattr(core_config, 'VAULT_BACKEND', 'db')
    monkeypatch.setattr(core_config, 'VAULT_DB_PATH', storage_path / 'vault.db')
    monkeypatch.setattr(core_config, 'VAULT_DUAL_WRITE', False)


def test_backup_excludes_vault_db(vault_env):
    _write_metadata(vault_env.storage_path, {'bundles': [{'id': 'a'}]})
    # a stray SQLite cache + its WAL sidecars must NOT be in the portable backup
    (vault_env.storage_path / 'vault.db').write_bytes(b'SQLITECACHE')
    (vault_env.storage_path / 'vault.db-wal').write_bytes(b'WAL')

    resp = vault_env.client.post('/api/mex/storage/backup')

    assert resp.status_code == 200
    with zipfile.ZipFile(Path(resp.get_json()['path'])) as zf:
        names = set(zf.namelist())
    assert 'metadata.json' in names
    assert 'vault.db' not in names and 'vault.db-wal' not in names


def test_clear_storage_rebuilds_db(vault_env, monkeypatch):
    _use_db(monkeypatch, vault_env.storage_path)
    vaultmod.save_blob({'characters': {'Fox': {'skins': [_skin('fox-red')]}}})

    resp = vault_env.client.post('/api/mex/storage/clear', json={})

    assert resp.status_code == 200
    assert vaultmod.load_blob() == {'version': '1.0', 'characters': {}, 'stages': {}}


def test_replace_restore_rebuilds_db(vault_env, monkeypatch):
    _use_db(monkeypatch, vault_env.storage_path)
    backup = _make_backup_zip({'bundles': [{'id': 'restored'}]})

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'replace', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    # DB rebuilt from the restored metadata.json, so DB-mode reads see the restore
    assert vaultmod.db_to_blob(vault_env.storage_path / 'vault.db') == {'bundles': [{'id': 'restored'}]}


def test_merge_restore_rebuilds_db(vault_env, monkeypatch):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    _use_db(monkeypatch, vault_env.storage_path)
    backup = _make_backup_zip({'characters': {'Fox': {'skins': [_skin('fox-blue')]}}})

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'merge', 'file': (backup, 'backup.zip')},
        content_type='multipart/form-data',
    )

    assert resp.status_code == 200
    rebuilt = vaultmod.db_to_blob(vault_env.storage_path / 'vault.db')
    ids = {s['id'] for s in rebuilt['characters']['Fox']['skins']}
    assert ids == {'fox-red', 'fox-blue'}      # DB reflects the merged catalog


@pytest.mark.parametrize('existing_character', [False, True])
def test_merge_includes_effects_and_side_catalogs(vault_env, existing_character):
    root = vault_env.storage_path
    current = {'characters': {'Fox': {'skins': [], 'extras': {'effects': [{'id': 'keep', 'name': 'Ours'}]}}}} if existing_character else {}
    _write_metadata(root, current)
    incoming = {'characters': {'Fox': {'skins': [], 'extras': {'effects': [
        {'id': 'keep', 'name': 'Theirs'}, {'id': 'new', 'name': 'New'}]}}}}
    files = {'Fox/models/keep.dat': b'theirs', 'Fox/models/keep_preview.png': b'preview', 'Fox/models/new.dat': b'new'}
    for relative, key, _family in vault_backup._SIDE_CATALOGS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        ours = [{'id': 'keep', 'name': 'Ours'}]
        theirs = [{'id': 'keep', 'name': 'Theirs'}, {'id': 'new', 'name': 'New'}]
        path.write_text(json.dumps({key: ours} if key else ours), encoding='utf-8')
        files[relative] = json.dumps({key: theirs} if key else theirs)
        directory = Path(relative).parent.as_posix()
        files[f'{directory}/keep/extra.dat'] = b'must not leak'
        files[f'{directory}/new/new.dat'] = b'new item'
    if existing_character:
        (root / 'Fox/models').mkdir(parents=True)
        (root / 'Fox/models/keep.dat').write_bytes(b'ours')
    response = vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'merge', 'file': (_make_backup_zip(incoming, files), 'backup.zip')})
    assert response.status_code == 200
    complete = _restore_done(vault_env)
    assert complete is not None, vault_env.socket.events
    assert complete['added']['extras'] == (1 if existing_character else 2)
    assert complete['added']['menu_mods'] == 5
    assert complete['added']['codes'] == 1
    assert (root / 'Fox/models/new.dat').read_bytes() == b'new'
    if existing_character:
        assert (root / 'Fox/models/keep.dat').read_bytes() == b'ours'
        assert not (root / 'Fox/models/keep_preview.png').exists()
    for relative, key, _family in vault_backup._SIDE_CATALOGS:
        merged = json.loads((root / relative).read_text())
        entries = merged[key] if key else merged
        assert [item['name'] for item in entries] == ['Ours', 'New']
        directory = (root / relative).parent
        assert not (directory / 'keep/extra.dat').exists()
        assert (directory / 'new/new.dat').read_bytes() == b'new item'


def test_invalid_side_catalog_rejected_before_any_copy(vault_env):
    root = vault_env.storage_path
    _write_metadata(root, {'version': 'ours'})
    before = (root / 'metadata.json').read_bytes()
    vault_env.client.post('/api/mex/storage/restore', data={'mode': 'merge', 'file': (
        _make_backup_zip({}, {'codes/metadata.json': '[{"id":"duplicate"},{"id":"duplicate"}]', 'new.dat': b'new'}), 'backup.zip')})
    assert _restore_failed(vault_env)
    assert (root / 'metadata.json').read_bytes() == before
    assert not (root / 'new.dat').exists()


def test_backup_and_merge_read_authoritative_db_without_mirror(vault_env, monkeypatch):
    root = vault_env.storage_path
    _use_db(monkeypatch, root)
    _write_metadata(root, {'bundles': [{'id': 'stale'}]})
    vaultmod.save_blob({'bundles': [{'id': 'current'}]})
    response = vault_env.client.post('/api/mex/storage/backup')
    assert response.status_code == 200
    with zipfile.ZipFile(response.get_json()['path']) as archive:
        assert json.loads(archive.read('metadata.json')) == {'bundles': [{'id': 'current'}]}
    vault_env.client.post('/api/mex/storage/restore', data={'mode': 'merge', 'file': (
        _make_backup_zip({'bundles': [{'id': 'new'}]}), 'backup.zip')})
    assert _restore_done(vault_env)
    assert [item['id'] for item in vaultmod.load_blob()['bundles']] == ['current', 'new']


@pytest.mark.parametrize('mutation', ['asset', 'catalog'])
def test_backup_rejects_concurrent_changes(vault_env, monkeypatch, mutation):
    root = vault_env.storage_path
    _write_metadata(root, {})
    (root / 'asset.dat').write_bytes(b'original')
    original_write = zipfile.ZipFile.write
    def change_after_copy(archive, filename, *args, **kwargs):
        result = original_write(archive, filename, *args, **kwargs)
        if mutation == 'asset':
            (root / 'asset.dat').write_bytes(b'changed longer bytes')
        else:
            _write_metadata(root, {'changed': True})
        return result
    monkeypatch.setattr(zipfile.ZipFile, 'write', change_after_copy)
    response = vault_env.client.post('/api/mex/storage/backup')
    assert response.status_code == 500
    assert 'changed during backup' in response.get_json()['error']
    assert list((vault_env.project_root / 'output/vault_backups').iterdir()) == []


def test_backup_names_are_unique(vault_env):
    _write_metadata(vault_env.storage_path, {})
    first = vault_env.client.post('/api/mex/storage/backup').get_json()
    second = vault_env.client.post('/api/mex/storage/backup').get_json()
    assert first['filename'] != second['filename']
    assert Path(first['path']).is_file() and Path(second['path']).is_file()


# Export Vault (tester B8, 0.9.0 build 8): the app's save dialog picks the file and the backup is saved there. It was a
# Chromium download whose Save As dialog showed the URL with the backend token, and whose Cancel deleted the backup.

def _exports(env):
    return list((env.project_root / 'output' / 'vault_backups').iterdir())


def test_export_saves_the_backup_where_the_user_chose_and_leaves_nothing_behind(vault_env, tmp_path):
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})
    (vault_env.storage_path / 'Fox').mkdir()
    (vault_env.storage_path / 'Fox' / 'fox-red.zip').write_bytes(b'fox-data')
    chosen = tmp_path / 'My Backups' / 'SSBM-Nucleus-Vault-2026-11-20.zip'
    chosen.parent.mkdir()

    resp = vault_env.client.post('/api/mex/storage/backup', json={'destination': str(chosen)})

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['path'] == str(chosen) and body['filename'] == chosen.name and body['size'] == chosen.stat().st_size
    with zipfile.ZipFile(chosen) as zf:
        assert {'metadata.json', 'Fox/fox-red.zip'} <= set(zf.namelist())
    assert _exports(vault_env) == []                                   # no copy left in output/
    assert sorted(p.name for p in chosen.parent.iterdir()) == [chosen.name]   # and no part file beside it


def test_export_replaces_the_file_the_user_chose_to_replace(vault_env, tmp_path):
    _write_metadata(vault_env.storage_path, {'bundles': [{'id': 'new'}]})
    chosen = tmp_path / 'vault.zip'
    chosen.write_bytes(b'last week')
    resp = vault_env.client.post('/api/mex/storage/backup', json={'destination': str(chosen)})
    assert resp.status_code == 200, resp.get_json()
    with zipfile.ZipFile(chosen) as zf:
        assert json.loads(zf.read('metadata.json')) == {'bundles': [{'id': 'new'}]}


@pytest.mark.parametrize('destination, error', [
    ('relative/vault.zip', 'full path'),
    ('{tmp}/vault.txt', '.zip'),
    ('{tmp}/missing folder/vault.zip', 'Folder does not exist'),
    ('{tmp}/folder.zip', 'is a folder'),
    ('{vault}/Fox/vault.zip', 'outside the Vault'),
    (7, 'No destination'),
])
def test_export_refuses_a_bad_destination_before_making_anything(vault_env, tmp_path, destination, error):
    _write_metadata(vault_env.storage_path, {})
    (vault_env.storage_path / 'Fox').mkdir()
    (tmp_path / 'folder.zip').mkdir()
    if isinstance(destination, str):
        destination = destination.format(tmp=tmp_path, vault=vault_env.storage_path)
    resp = vault_env.client.post('/api/mex/storage/backup', json={'destination': destination})
    assert resp.status_code == 400
    assert error in resp.get_json()['error']
    assert not (vault_env.project_root / 'output' / 'vault_backups').exists()
    assert not (vault_env.storage_path / 'Fox' / 'vault.zip').exists()


@pytest.mark.parametrize('step', ['copy', 'replace'])
def test_a_failed_export_keeps_the_file_there_and_leaves_no_part_file(vault_env, tmp_path, monkeypatch, step):
    import errno
    _write_metadata(vault_env.storage_path, {'bundles': [{'id': 'new'}]})
    chosen = tmp_path / 'vault.zip'
    chosen.write_bytes(b'last week')
    disk_full = OSError(errno.ENOSPC, 'No space left on device')
    if step == 'copy':
        def copyfile(source, target, *args, **kwargs):
            Path(target).write_bytes(b'half')
            raise disk_full
        monkeypatch.setattr(vault_backup.shutil, 'copyfile', copyfile)
    else:
        real_replace = vault_backup.file_retry.replace
        def replace(source, target, **kwargs):
            if Path(target) == chosen:
                raise disk_full
            return real_replace(source, target, **kwargs)
        monkeypatch.setattr(vault_backup.file_retry, 'replace', replace)

    resp = vault_env.client.post('/api/mex/storage/backup', json={'destination': str(chosen)})

    assert resp.status_code == 500
    assert 'Could not save the backup' in resp.get_json()['error']
    assert chosen.read_bytes() == b'last week'
    assert [p.name for p in tmp_path.iterdir() if p.name != 'project'] == ['vault.zip']
    assert _exports(vault_env) == []



def test_restore_status_survives_missed_socket_and_duplicate_start(vault_env, monkeypatch):
    monkeypatch.setattr(core_state, 'get_socketio', lambda: None)
    started = vault_env.client.post('/api/mex/storage/restore', data={'mode': 'merge', 'file': (
        _make_backup_zip({'bundles': [{'id': 'new'}]}), 'backup.zip')}).get_json()
    restore_id = started['restore_id']
    status = vault_env.client.get(f'/api/jobs/{restore_id}')
    assert status.status_code == 200
    job = status.get_json()['job']
    assert job['status'] == 'done'
    assert job['result']['report']['added']['bundles'] == ['new']
    duplicate = vault_env.client.post('/api/mex/storage/restore', data={
        'restore_id': restore_id, 'mode': 'replace', 'file': (_make_backup_zip({}), 'backup.zip')})
    assert duplicate.status_code == 409
    assert _read_metadata(vault_env.storage_path)['bundles'] == [{'id': 'new'}]


class _DeferredThread:
    """A job thread that never runs: the restore stays queued, as if Nucleus
    died before it started."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        pass


def _as_dead_backend(job_id):
    """Make the job's record look like it was left by a backend that died."""
    jobs._jobs.clear()
    record = jobs.get(job_id)
    record['owner'] = {'pid': 999999999, 'created': 1.0}
    jobs._write(record)


def test_a_restore_nucleus_died_in_is_interrupted_and_its_upload_removed(vault_env, monkeypatch):
    monkeypatch.setattr(jobs.threading, 'Thread', _DeferredThread)
    started = vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'replace', 'file': (_make_backup_zip({}), 'backup.zip')}).get_json()
    restore_id = started['restore_id']
    upload = Path(jobs.get(restore_id)['owned']['upload'])
    assert upload.exists()
    assert jobs.get(restore_id)['status'] == 'queued'
    second = vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'replace', 'file': (_make_backup_zip({}), 'backup.zip')})
    assert second.status_code == 409

    _as_dead_backend(restore_id)
    assert [r['id'] for r in jobs.recover_interrupted()] == [restore_id]
    record = vault_env.client.get(f'/api/jobs/{restore_id}').get_json()['job']
    assert record['status'] == 'interrupted'
    assert 'closed while this was running' in record['error']
    assert record['owned'] == {}
    assert not upload.exists()
    listed = vault_env.client.get('/api/jobs').get_json()['jobs']
    assert [r['id'] for r in listed] == [restore_id]


def test_the_moved_aside_vault_is_owned_on_disk_while_the_new_one_goes_live(vault_env, monkeypatch):
    _write_metadata(vault_env.storage_path, {'bundles': [{'id': 'mine'}]})
    owned_at_publish = []
    original_rename = Path.rename

    def read_record_then_rename(source, target):
        if Path(source).name.startswith('.vault-restore-'):
            record_path, = (vault_env.project_root.parent / 'jobs').glob('*.json')
            owned_at_publish.append(json.loads(record_path.read_text(encoding='utf-8'))['owned'])
        return original_rename(source, target)
    monkeypatch.setattr(Path, 'rename', read_record_then_rename)
    vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'replace', 'file': (_make_backup_zip({'bundles': [{'id': 'theirs'}]}), 'backup.zip')})
    assert set(owned_at_publish[0]) == {'upload', 'staging', 'previous'}
    assert _restore_done(vault_env)
    assert _restore_job(vault_env)['owned'] == {}


def test_recovery_puts_back_a_vault_a_dead_replace_had_moved_aside(vault_env):
    _write_metadata(vault_env.storage_path, {'bundles': [{'id': 'mine'}]})
    previous = vault_env.project_root / '.vault-previous-dead'
    vault_env.storage_path.rename(previous)
    staging = vault_env.project_root / '.vault-restore-dead'
    staging.mkdir()
    jobs._write({
        'id': 'dead-restore', 'kind': vault_backup.RESTORE_KIND, 'label': 'Vault restore',
        'status': 'running', 'notes': [], 'created_at': time.time(),
        'owner': {'pid': 999999999, 'created': 1.0},
        'owned': {'staging': str(staging),
                  'previous': {'path': str(previous), 'vault': str(vault_env.storage_path.resolve())}},
    })
    jobs.recover_interrupted()
    record = jobs.get('dead-restore')
    assert record['status'] == 'interrupted'
    assert record['notes'] == ['Your vault was put back.']
    assert _read_metadata(vault_env.storage_path)['bundles'] == [{'id': 'mine'}]
    assert not previous.exists()
    assert not staging.exists()


def test_job_lookup_rejects_unknown_and_path_like_ids(vault_env):
    assert vault_env.client.get('/api/jobs/11111111-1111-1111-1111-111111111111').status_code == 404
    assert vault_env.client.get('/api/jobs/..%5C..%5Csecret').status_code == 404
    assert vault_env.client.post('/api/mex/storage/restore', data={
        'restore_id': 'not-a-uuid', 'file': (_make_backup_zip({}), 'backup.zip')}).status_code == 400


def test_record_write_failure_does_not_change_successful_restore(vault_env, monkeypatch):
    original_write = jobs._write

    def fail_final_record(record):
        if record.get('status') == 'done':
            raise OSError('injected record disk failure')
        return original_write(record)
    monkeypatch.setattr(jobs, '_write', fail_final_record)
    started = vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'merge', 'file': (_make_backup_zip({'bundles': [{'id': 'new'}]}), 'backup.zip')}).get_json()
    assert _restore_done(vault_env)
    assert not _restore_failed(vault_env)
    assert jobs.get(started['restore_id'])['status'] == 'done'
    assert _read_metadata(vault_env.storage_path)['bundles'] == [{'id': 'new'}]


def test_a_corrupt_job_record_is_ignored(vault_env):
    restore_id = '22222222-2222-2222-2222-222222222222'
    root = vault_env.project_root.parent / 'jobs'
    root.mkdir(parents=True, exist_ok=True)
    (root / f'{restore_id}.json').write_text('{broken', encoding='utf-8')
    assert vault_env.client.get(f'/api/jobs/{restore_id}').status_code == 404
    assert jobs.recover_interrupted() == []
    assert vault_env.client.get('/api/jobs').get_json()['jobs'] == []


def test_a_failed_merge_takes_back_the_files_it_added(vault_env, monkeypatch):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    files = {'Fox/a.dat': b'first', 'Fox/b.dat': b'second'}
    real_replace = vault_backup.file_retry.replace
    published = []

    def disk_full_on_second(src, dst, **kwargs):
        if vault_env.storage_path not in Path(dst).parents:
            return real_replace(src, dst, **kwargs)   # the job's own record
        if published:
            raise OSError(28, 'No space left on device')
        real_replace(src, dst, **kwargs)
        published.append(dst)
    monkeypatch.setattr(vault_backup.file_retry, 'replace', disk_full_on_second)
    vault_env.client.post('/api/mex/storage/restore', data={'mode': 'merge', 'file': (
        _make_backup_zip({'characters': {'Fox': {'skins': [_skin('fox-a')]}}}, files), 'backup.zip')})
    assert 'No space' in _restore_failed(vault_env)['error']
    assert published and not any(Path(p).exists() for p in published)
    assert _read_metadata(vault_env.storage_path) == {'characters': {}}


def test_clear_storage_waits_for_a_running_restore(vault_env, monkeypatch):
    _write_metadata(vault_env.storage_path, {'characters': {}})
    (vault_env.storage_path / 'Fox').mkdir()
    monkeypatch.setattr(jobs.threading, 'Thread', _DeferredThread)
    vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'merge', 'file': (_make_backup_zip({}), 'backup.zip')})
    response = vault_env.client.post('/api/mex/storage/clear', json={})
    assert response.status_code == 409
    assert (vault_env.storage_path / 'Fox').exists()


def test_failed_upload_removes_its_partial_archive(vault_env, monkeypatch):
    from werkzeug.datastructures import FileStorage
    created = []
    def fail_save(upload, destination, *args, **kwargs):
        created.append(Path(destination.name))
        destination.write(b'partial upload')
        raise OSError('injected upload failure')
    monkeypatch.setattr(FileStorage, 'save', fail_save)
    response = vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'replace', 'file': (_make_backup_zip({}), 'backup.zip')})
    assert response.status_code == 500
    assert created and all(not path.exists() for path in created)



def test_a_restore_holds_shutdown_while_it_runs_and_lets_go_after(vault_env, monkeypatch):
    """Quitting mid-restore must wait: a replace killed half-way leaves the
    Vault moved aside."""
    from core import critical_ops
    held = []

    def restore(job, upload, mode):
        held.append(critical_ops.active_ops())
        return {}
    monkeypatch.setattr(vault_backup, 'run_vault_restore', restore)
    response = vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'replace', 'file': (_make_backup_zip({}), 'backup.zip')})
    assert response.status_code == 200
    assert held == [['Vault restore']]
    assert critical_ops.active_ops() == []


# ---------------------------------------------------------------------------
# Replace All with the assistant's task journal open (hand check 11-20: every
# Windows replace restore failed with "Access is denied", because tasks.db sat
# open on the backend's threads while the storage folder was renamed)
# ---------------------------------------------------------------------------

def test_replace_restore_closes_the_open_task_journal_and_it_reopens(vault_env, monkeypatch):
    import threading
    from core import storage_handles
    from randall.assistant.tasks import store as task_store
    from randall.reports import wish_ledger

    monkeypatch.setattr(core_config, 'STORAGE_PATH', vault_env.storage_path)
    task_store.close_all()
    wish_ledger.close_all()
    _write_metadata(vault_env.storage_path, {'characters': {'Fox': {'skins': [_skin('fox-red')]}}})

    # The journal open on this thread, the wish ledger beside it, and the journal on a second live thread.
    task_store.connect().execute('SELECT 1')
    wish_ledger.connection().execute('SELECT 1')
    ask, answer = threading.Event(), {}
    opened, finished = threading.Event(), threading.Event()

    def worker():
        task_store.connect().execute('SELECT 1')
        opened.set()
        ask.wait(30)
        try:
            row = task_store.connect().execute('PRAGMA database_list').fetchone()
            answer['file'] = row['file']
        except Exception as error:  # noqa: BLE001 - reported below
            answer['error'] = repr(error)
        finished.set()

    # vault_env makes threading.Thread run inline (jobs run synchronously): a real OS thread holds its own handle.
    import _thread
    _thread.start_new_thread(worker, ())
    assert opened.wait(30)
    closed = []
    monkeypatch.setattr(storage_handles, '_closers', [*storage_handles._closers, lambda: closed.append(1)])

    resp = vault_env.client.post(
        '/api/mex/storage/restore',
        data={'mode': 'replace', 'file': (_make_backup_zip(
            {'characters': {'Marth': {'skins': [_skin('marth-black')]}}},
            extra_files={'Marth/marth-black.zip': b'marth-data'}), 'backup.zip')},
        content_type='multipart/form-data')

    assert resp.status_code == 200
    done = _restore_done(vault_env)
    assert done is not None, _restore_failed(vault_env)
    assert closed, 'the restore never closed the storage handles'
    assert 'Marth' in _read_metadata(vault_env.storage_path)['characters']
    # Both threads and the ledger use the journal again, now in the restored folder.
    journal = vault_env.storage_path / 'assistant' / 'tasks' / 'tasks.db'
    assert Path(task_store.connect().execute('PRAGMA database_list').fetchone()['file']) == journal
    assert wish_ledger.connection().execute('SELECT COUNT(*) FROM wish_meta').fetchone()[0] >= 1
    ask.set()
    assert finished.wait(30)
    assert Path(answer.get('file', '')) == journal, answer
    task_store.close_all()
    wish_ledger.close_all()


def test_storage_handles_runs_every_closer_even_after_one_fails(monkeypatch):
    from core import storage_handles
    ran = []

    def broken():
        raise OSError('handle already gone')

    monkeypatch.setattr(storage_handles, '_closers', [])
    storage_handles.register(broken)
    storage_handles.register(lambda: ran.append('second'))
    storage_handles.register(broken)        # registered once only
    assert len(storage_handles._closers) == 2
    storage_handles.close_all()
    assert ran == ['second']


# ---------------------------------------------------------------------------
# Live SQLite databases in the Vault (Randall's chats.db, the task journal tasks.db): a backup carries a consistent
# snapshot of each, never a raw file with its -wal/-shm, and a restore still takes an old backup's raw ones.
# ---------------------------------------------------------------------------

_COMPANIONS = ('-wal', '-shm', '-journal')


def _live_journal(path, rows):
    """A WAL database like tasks.db while the app runs: open, its newest rows only in the -wal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA wal_autocheckpoint=0')
    conn.execute('CREATE TABLE IF NOT EXISTS tasks (name TEXT)')
    conn.executemany('INSERT INTO tasks VALUES (?)', [(row,) for row in rows])
    return conn


def _task_names(path):
    with closing(sqlite3.connect(str(path))) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        return sorted(name for (name,) in conn.execute('SELECT name FROM tasks'))


def _old_backup_with_raw_journal(scratch, rows, metadata=None):
    """A backup as 0.8.x made it: tasks.db copied raw beside its -wal (rows only there) and a stale -shm."""
    conn = _live_journal(scratch / 'tasks.db', rows)
    try:
        assert (scratch / 'tasks.db-wal').stat().st_size > 0
        raw = {'assistant/tasks/tasks.db': (scratch / 'tasks.db').read_bytes(),
               'assistant/tasks/tasks.db-wal': (scratch / 'tasks.db-wal').read_bytes(),
               'assistant/tasks/tasks.db-shm': b'\0' * 32768}
    finally:
        conn.close()
    return _make_backup_zip(metadata or {'characters': {}}, extra_files=raw)


def test_backup_carries_a_snapshot_of_each_live_database_never_its_companions(vault_env, tmp_path, monkeypatch):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    journal = _live_journal(storage / 'assistant' / 'tasks' / 'tasks.db', ['first', 'second'])
    with closing(sqlite3.connect(str(storage / 'assistant' / 'chats.db'), isolation_level=None)) as chats:
        chats.execute('CREATE TABLE chats (id TEXT)')                # chats.db keeps SQLite's rollback journal
        chats.execute("INSERT INTO chats VALUES ('hello')")
    (storage / 'Fox').mkdir()
    (storage / 'Fox' / 'sonic-wal').write_bytes(b'a mod file, not a companion')
    real_snapshot = vault_backup._sqlite_snapshot

    def journal_writes_meanwhile(source, workdir):
        copied = real_snapshot(source, workdir)
        if Path(source).name == 'tasks.db':
            journal.execute("INSERT INTO tasks VALUES ('during')")   # the app keeps writing; the backup goes on
        return copied
    monkeypatch.setattr(vault_backup, '_sqlite_snapshot', journal_writes_meanwhile)
    try:
        assert (storage / 'assistant' / 'tasks' / 'tasks.db-wal').exists()
        resp = vault_env.client.post('/api/mex/storage/backup')
        assert resp.status_code == 200, resp.get_json()
        with zipfile.ZipFile(resp.get_json()['path']) as archive:
            names = set(archive.namelist())
            archive.extract('assistant/tasks/tasks.db', tmp_path / 'out')
            archive.extract('assistant/chats.db', tmp_path / 'out')
    finally:
        journal.close()
    assert {'assistant/tasks/tasks.db', 'assistant/chats.db', 'Fox/sonic-wal'} <= names
    assert [name for name in names if name.endswith(_COMPANIONS)] == ['Fox/sonic-wal']
    copied = tmp_path / 'out' / 'assistant' / 'tasks' / 'tasks.db'
    assert _task_names(copied) == ['first', 'second']            # the rows that were only in the WAL came too
    with closing(sqlite3.connect(str(copied))) as conn:
        assert conn.execute('PRAGMA journal_mode').fetchone() == ('delete',)
    with closing(sqlite3.connect(str(tmp_path / 'out' / 'assistant' / 'chats.db'))) as conn:
        assert conn.execute('SELECT id FROM chats').fetchall() == [('hello',)]


def test_a_backup_then_replace_restores_the_live_databases(vault_env):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    _live_journal(storage / 'assistant' / 'tasks' / 'tasks.db', ['kept']).close()
    backup = Path(vault_env.client.post('/api/mex/storage/backup').get_json()['path']).read_bytes()
    _live_journal(storage / 'assistant' / 'tasks' / 'tasks.db', ['later']).close()

    vault_env.client.post('/api/mex/storage/restore', data={
        'mode': 'replace', 'file': (io.BytesIO(backup), 'backup.zip')}, content_type='multipart/form-data')
    assert _restore_done(vault_env), _restore_failed(vault_env)
    assert _task_names(storage / 'assistant' / 'tasks' / 'tasks.db') == ['kept']


@pytest.mark.parametrize('mode', ['replace', 'merge'])
def test_an_old_backups_raw_database_restores_with_its_wal_taken_in(vault_env, tmp_path, mode):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    backup = _old_backup_with_raw_journal(tmp_path, ['old-1', 'old-2'])

    vault_env.client.post('/api/mex/storage/restore', data={'mode': mode, 'file': (backup, 'backup.zip')},
                          content_type='multipart/form-data')
    assert _restore_done(vault_env), _restore_failed(vault_env)
    tasks = storage / 'assistant' / 'tasks'
    assert not [path.name for path in tasks.iterdir() if path.name.endswith(_COMPANIONS)]
    assert _task_names(tasks / 'tasks.db') == ['old-1', 'old-2']


def test_a_merge_never_puts_an_old_backups_wal_beside_this_computers_database(vault_env, tmp_path):
    storage = vault_env.storage_path
    _write_metadata(storage, {'characters': {}})
    _live_journal(storage / 'assistant' / 'tasks' / 'tasks.db', ['mine']).close()   # closed: no -wal of its own
    backup = _old_backup_with_raw_journal(tmp_path, ['theirs'])

    vault_env.client.post('/api/mex/storage/restore', data={'mode': 'merge', 'file': (backup, 'backup.zip')},
                          content_type='multipart/form-data')
    assert _restore_done(vault_env), _restore_failed(vault_env)
    tasks = storage / 'assistant' / 'tasks'
    assert sorted(path.name for path in tasks.iterdir()) == ['tasks.db']
    assert _task_names(tasks / 'tasks.db') == ['mine']
