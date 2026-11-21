"""
Regression test: deleting a vault costume must remove EVERY file it owns —
the zip, SD/HD CSP, stock, and all alternate-pose CSPs. Older deletes only
removed _csp.png/_stc.png, orphaning _csp_hd.png and _csp_alt_*.png in the
character folder (loose PNGs the user could never clean up from the UI).
"""
from tests.paths import BACKEND
import sys
import zipfile
from pathlib import Path

from flask import Flask

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import vault.routes.storage_costumes.library as sc  # the delete route


def _client():
    app = Flask(__name__)
    app.register_blueprint(sc.storage_costumes_bp)
    return app.test_client()


def test_delete_removes_zip_csp_stock_hd_and_alts(tmp_path, monkeypatch):
    character, skin_id = 'Pikachu', 'plpkbk'
    char_dir = tmp_path / character
    char_dir.mkdir(parents=True)

    # The full on-disk footprint of a skin with an HD CSP + one pose alternate.
    files = [
        f'{skin_id}.zip',
        f'{skin_id}_csp.png',
        f'{skin_id}_stc.png',
        f'{skin_id}_csp_hd.png',
        f'{skin_id}_csp_alt_1.png',
        f'{skin_id}_csp_alt_1_hd.png',
    ]
    for f in files:
        (char_dir / f).write_bytes(b'x')

    # A DIFFERENT skin whose id shares this one as a prefix — must be untouched.
    (char_dir / f'{skin_id}2.zip').write_bytes(b'x')
    (char_dir / f'{skin_id}2_csp_hd.png').write_bytes(b'x')

    skin = {
        'id': skin_id, 'filename': f'{skin_id}.zip',
        'hd_csp_filename': f'{skin_id}_csp_hd.png',
        'alternate_csps': [
            {'id': 'a1', 'filename': f'{skin_id}_csp_alt_1.png', 'pose_name': 'jump', 'is_hd': False},
            {'id': 'a1_hd', 'filename': f'{skin_id}_csp_alt_1_hd.png', 'pose_name': 'jump', 'is_hd': True},
        ],
    }
    meta = {'characters': {character: {'skins': [skin]}}}
    monkeypatch.setattr(sc, 'load_metadata', lambda: meta)
    monkeypatch.setattr(sc, 'save_metadata', lambda m: None)
    monkeypatch.setattr(sc, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(sc, 'get_char_data', lambda m, c: m['characters'].get(c))

    resp = _client().post('/api/mex/storage/costumes/delete',
                          json={'character': character, 'skinId': skin_id})

    assert resp.status_code == 200 and resp.get_json()['success'] is True
    for f in files:
        assert not (char_dir / f).exists(), f'{f} should have been deleted'
    assert meta['characters'][character]['skins'] == []
    # Prefix-sibling skin left intact
    assert (char_dir / f'{skin_id}2.zip').exists()
    assert (char_dir / f'{skin_id}2_csp_hd.png').exists()


def test_delete_sweeps_untracked_alt_png(tmp_path, monkeypatch):
    """An alternate PNG present on disk but missing from metadata (partial
    earlier state) is still swept by the id glob."""
    character, skin_id = 'Falco', 'gamer-gang'
    char_dir = tmp_path / character
    char_dir.mkdir(parents=True)
    (char_dir / f'{skin_id}.zip').write_bytes(b'x')
    (char_dir / f'{skin_id}_csp_alt_9.png').write_bytes(b'x')  # untracked

    meta = {'characters': {character: {'skins': [{'id': skin_id, 'filename': f'{skin_id}.zip'}]}}}
    monkeypatch.setattr(sc, 'load_metadata', lambda: meta)
    monkeypatch.setattr(sc, 'save_metadata', lambda m: None)
    monkeypatch.setattr(sc, 'STORAGE_PATH', tmp_path)
    monkeypatch.setattr(sc, 'get_char_data', lambda m, c: m['characters'].get(c))

    resp = _client().post('/api/mex/storage/costumes/delete',
                          json={'character': character, 'skinId': skin_id})

    assert resp.status_code == 200 and resp.get_json()['success'] is True
    assert not (char_dir / f'{skin_id}_csp_alt_9.png').exists()
