"""Ghost-entry regression for duplicate detection.

The vault listings (costumes and DAS stage variants) only show entries whose
zip exists on disk. The duplicate checks used to consult metadata hashes only,
so a metadata entry that lost its zip ("ghost") blocked re-imports as
"already owned" while being invisible in the UI — reported in the field as
"23 skipped because you already have them / my stages don't show any of them".
Duplicate checks must ignore entries not backed by a stored zip.
"""

from tests.paths import BACKEND
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import vault.importing.unified.helpers as helpers
from vault.importing.unified.helpers import check_duplicate_skin, check_duplicate_stage, compute_dat_hash

DAT = b'stage bytes'
HASH = compute_dat_hash(DAT)


def _stage_metadata(**variant_extra):
    variant = {'id': 'grop-haunt', 'name': 'grop-haunt', 'dat_hash': HASH}
    variant.update(variant_extra)
    return {'stages': {'dreamland': {'variants': [variant]}}}


def test_stage_ghost_variant_is_not_a_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.config, 'STORAGE_PATH', tmp_path)
    # metadata entry exists, but no zip anywhere under storage/das/
    assert check_duplicate_stage('dreamland', HASH, _stage_metadata()) is None


def test_stage_variant_with_zip_still_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.config, 'STORAGE_PATH', tmp_path)
    das = tmp_path / 'das' / 'dreamland'
    das.mkdir(parents=True)
    (das / 'grop-haunt.zip').write_bytes(b'ZIP')  # <id>.zip convention

    existing = check_duplicate_stage('dreamland', HASH, _stage_metadata())
    assert existing is not None and existing['id'] == 'grop-haunt'


def test_stage_variant_filename_key_is_respected(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.config, 'STORAGE_PATH', tmp_path)
    das = tmp_path / 'das' / 'dreamland'
    das.mkdir(parents=True)
    (das / 'custom-name.zip').write_bytes(b'ZIP')

    meta = _stage_metadata(filename='custom-name.zip')
    assert check_duplicate_stage('dreamland', HASH, meta) is not None


def _skin_metadata():
    return {'characters': {'Fox': {'skins': [{
        'id': 'lasered', 'color': 'Red', 'filename': 'lasered.zip',
        'dat_hash': HASH,
    }]}}}


def test_skin_ghost_entry_is_not_a_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.config, 'STORAGE_PATH', tmp_path)
    # cached dat_hash matches, but the stored zip is gone
    assert check_duplicate_skin('Fox', HASH, _skin_metadata()) is None


def test_skin_with_zip_still_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.config, 'STORAGE_PATH', tmp_path)
    char_dir = tmp_path / 'Fox'
    char_dir.mkdir()
    with zipfile.ZipFile(char_dir / 'lasered.zip', 'w') as zf:
        zf.writestr('PlFxRe.dat', DAT)

    existing = check_duplicate_skin('Fox', HASH, _skin_metadata())
    assert existing is not None and existing['id'] == 'lasered'
