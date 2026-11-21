"""
Regression test for the DAS vault delete bug: variants imported via ISO scan
have no 'filename' key, so delete_storage_stage KeyError'd with
"Delete failed: 'filename'". Delete must fall back to the <id>.zip convention.
"""
from tests.paths import BACKEND
import sys
from pathlib import Path

from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import vault.routes.storage_stages as ss


def _client():
    app = Flask(__name__)
    app.register_blueprint(ss.storage_stages_bp)
    return app.test_client()


def test_delete_variant_without_filename_key(tmp_path, monkeypatch):
    # ISO-scan-style entry: id/name/source/md5 but NO 'filename'
    meta = {'stages': {'battlefield': {'variants': [
        {'id': 'bf0', 'name': 'BF 0', 'source': 'iso-scan:20xx', 'md5': 'abc'},
    ]}}}
    monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
    monkeypatch.setattr(ss, 'save_metadata', lambda m: None)
    monkeypatch.setattr(ss, 'STORAGE_PATH', tmp_path)

    das = tmp_path / 'das' / 'battlefield'
    das.mkdir(parents=True)
    (das / 'bf0.zip').write_bytes(b'ZIP')               # <id>.zip convention
    (das / 'bf0_screenshot.png').write_bytes(b'PNG')

    resp = _client().post('/api/mex/storage/stages/delete',
                          json={'stageFolder': 'battlefield', 'variantId': 'bf0'})

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert not (das / 'bf0.zip').exists()
    assert not (das / 'bf0_screenshot.png').exists()
    assert meta['stages']['battlefield']['variants'] == []


def test_delete_variant_with_filename_key(tmp_path, monkeypatch):
    """The normal path (entry has 'filename') still works."""
    meta = {'stages': {'yoshisstory': {'variants': [
        {'id': 'ys1', 'name': 'YS 1', 'filename': 'custom_name.zip'},
    ]}}}
    monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
    monkeypatch.setattr(ss, 'save_metadata', lambda m: None)
    monkeypatch.setattr(ss, 'STORAGE_PATH', tmp_path)

    das = tmp_path / 'das' / 'yoshisstory'
    das.mkdir(parents=True)
    (das / 'custom_name.zip').write_bytes(b'ZIP')

    resp = _client().post('/api/mex/storage/stages/delete',
                          json={'stageFolder': 'yoshisstory', 'variantId': 'ys1'})

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert not (das / 'custom_name.zip').exists()


def test_reorder_with_disk_only_variants(tmp_path, monkeypatch):
    """Regression for "Invalid fromIndex or toIndex": the DAS variants endpoint
    shows metadata variants present on disk PLUS on-disk zips that have no
    metadata entry, so the frontend can send an index past the raw metadata list.
    Reorder must operate on that same display order (and persist a moved
    disk-only variant so its position sticks)."""
    meta = {'stages': {'battlefield': {'variants': [{'id': 'A', 'name': 'A'}]}}}
    monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
    monkeypatch.setattr(ss, 'save_metadata', lambda m: None)
    monkeypatch.setattr(ss, 'STORAGE_PATH', tmp_path)
    das = tmp_path / 'das' / 'battlefield'
    das.mkdir(parents=True)
    for v in ('A', 'D', 'E'):          # D, E are disk-only (no metadata entry)
        (das / f'{v}.zip').write_bytes(b'ZIP')

    # display order = [A, D, E]; move E (idx 2) to front. Old code validated the
    # index against len(metadata variants)=1 -> 2 >= 1 -> 400.
    resp = _client().post('/api/mex/storage/stages/reorder',
                          json={'stageFolder': 'battlefield', 'fromIndex': 2, 'toIndex': 0})
    assert resp.status_code == 200, resp.get_json()
    assert [v['id'] for v in resp.get_json()['variants']] == ['E', 'A', 'D']
    # moved disk-only variants are now persisted in metadata
    assert {'D', 'E'} <= {v['id'] for v in meta['stages']['battlefield']['variants']}


def test_reorder_normal_metadata_only(tmp_path, monkeypatch):
    """Healthy vault (every variant in metadata + on disk) reorders normally."""
    meta = {'stages': {'battlefield': {'variants': [
        {'id': 'A', 'name': 'A'}, {'id': 'B', 'name': 'B'}, {'id': 'C', 'name': 'C'},
    ]}}}
    monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
    monkeypatch.setattr(ss, 'save_metadata', lambda m: None)
    monkeypatch.setattr(ss, 'STORAGE_PATH', tmp_path)
    das = tmp_path / 'das' / 'battlefield'
    das.mkdir(parents=True)
    for v in ('A', 'B', 'C'):
        (das / f'{v}.zip').write_bytes(b'ZIP')

    resp = _client().post('/api/mex/storage/stages/reorder',
                          json={'stageFolder': 'battlefield', 'fromIndex': 0, 'toIndex': 2})
    assert resp.status_code == 200, resp.get_json()
    assert [v['id'] for v in resp.get_json()['variants']] == ['B', 'C', 'A']


def test_reorder_genuinely_out_of_range_rejected(tmp_path, monkeypatch):
    """An index past the display list still 400s (the guard isn't just removed)."""
    meta = {'stages': {'battlefield': {'variants': [{'id': 'A', 'name': 'A'}]}}}
    monkeypatch.setattr(ss, 'load_metadata', lambda: meta)
    monkeypatch.setattr(ss, 'save_metadata', lambda m: None)
    monkeypatch.setattr(ss, 'STORAGE_PATH', tmp_path)
    das = tmp_path / 'das' / 'battlefield'
    das.mkdir(parents=True)
    (das / 'A.zip').write_bytes(b'ZIP')
    resp = _client().post('/api/mex/storage/stages/reorder',
                          json={'stageFolder': 'battlefield', 'fromIndex': 5, 'toIndex': 0})
    assert resp.status_code == 400
