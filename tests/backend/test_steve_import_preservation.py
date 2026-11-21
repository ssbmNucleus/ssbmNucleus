"""Opt-in Steve v1.20 scanner/package/build preservation regression.

No game data ships in this test. Set NUCLEUS_STEVE_SOURCE_PROJECT to a scratch
project imported from the author's v1.20 xdelta release, and
NUCLEUS_STEVE_CLEAN_ISO to the user's own NTSC 1.02 ISO. The test creates its
own vault and minimal project; supplied assets are only read.

This proves the jump-relevant data survives the import pipeline. It does not
replace the separate ground/air X, Y and tap-jump gameplay controls.
"""
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest

from core import iso_reads
from core.config import MEXCLI_PATH
import mexcli.commands
from vault.catalog import custom_characters as catalog
from vault.importing import custom_character_scan as scan


STEVE_DAT_SHA256 = '0a5069d6a7a262a8f3af8f236307eb526c6e645fa81ef67273b7e78fef72cda4'
STEVE_ANIM_SHA256 = '1b6130571b6a7adb2c255a7bee1fd8b2d1819837a204452e34322081d8d1f8ac'
JUMP_DATA = ('files', 'functions', 'moveLogic', 'boneDefinitions', 'items')


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@pytest.mark.slow
def test_steve_v120_scan_package_and_built_disc_preserve_jump_data(vault, tmp_path, monkeypatch):
    source_setting = os.environ.get('NUCLEUS_STEVE_SOURCE_PROJECT')
    iso_setting = os.environ.get('NUCLEUS_STEVE_CLEAN_ISO')
    if not source_setting or not iso_setting:
        pytest.skip('requires opt-in Steve v1.20 source project and user-owned clean ISO')
    source = Path(source_setting).resolve()
    clean_iso = Path(iso_setting).resolve()
    assert source.is_dir() and clean_iso.is_file()
    assert Path(MEXCLI_PATH).is_file(), 'requires the pinned native MexCLI runtime'
    with clean_iso.open('rb') as stream:
        assert hashlib.file_digest(stream, 'md5').hexdigest() == '0e63d4223b01d9aba596259dc155a174'
    assert _sha(source / 'files/PlSv.dat') == STEVE_DAT_SHA256
    assert _sha(source / 'files/PlSvAJ.dat') == STEVE_ANIM_SHA256

    project_meta = json.loads((source / 'project.mexproj').read_text())
    source_fighters = [json.loads((source / 'data/fighters' / name).read_text())
                       for name in project_meta['fighterSaveMap']['filePaths']]
    source_fighter = next(f for f in source_fighters if f['name'] == 'Steve')
    custom_root = vault.storage / 'custom_characters'
    custom_root.mkdir()
    monkeypatch.setattr(catalog, 'CUSTOM_CHARACTERS_PATH', custom_root)
    monkeypatch.setattr(scan, 'CUSTOM_CHARACTERS_PATH', custom_root)
    imported, skipped = scan._extract_custom_characters_from_project(source, 'Steve v1.20 regression')
    assert imported == ['Steve'] and skipped == []
    package_path = custom_root / 'steve/fighter.zip'
    with zipfile.ZipFile(package_path) as package:
        fighter = json.loads(package.read('fighter.json'))
        for field in JUMP_DATA:
            assert fighter[field] == source_fighter[field], field
        expected = {
            name: _sha(source / 'files' / name)
            for name in source_fighter['files'].values()
            if isinstance(name, str) and (source / 'files' / name).is_file()
        }
        assert len(expected) == 7
        for name, digest in expected.items():
            assert hashlib.sha256(package.read(name)).hexdigest() == digest, name

    # Existing-entry refresh must preserve compiled character code and actions.
    assert scan._extract_custom_characters_from_project(source, 'Steve v1.20 regression') == ([], ['Steve'])
    with zipfile.ZipFile(package_path) as package:
        for name, digest in expected.items():
            assert hashlib.sha256(package.read(name)).hexdigest() == digest, name
        refreshed = json.loads(package.read('fighter.json'))
        for field in JUMP_DATA:
            assert refreshed[field] == source_fighter[field], field

    target = tmp_path / 'minimal'
    created = mexcli.commands.run_json(['create', clean_iso, target, 'Steve preservation'], timeout=300)
    assert created.get('success'), created
    project = target / 'project.mexproj'
    added = mexcli.commands.run_json(['add-fighter', project, package_path], timeout=300)
    assert added.get('success'), added
    internal_id = added['internalId']
    assert isinstance(internal_id, int)
    target_meta = json.loads(project.read_text())
    installed = json.loads((target / 'data/fighters' /
                            target_meta['fighterSaveMap']['filePaths'][internal_id]).read_text())
    for field in JUMP_DATA:
        assert installed[field] == source_fighter[field], field
    for name, digest in expected.items():
        assert _sha(target / 'files' / name) == digest, name

    output = tmp_path / 'steve.iso'
    exported = mexcli.commands.run_json(['export', project, output], timeout=600)
    assert exported.get('success'), exported
    entries = iso_reads.fst_entries(output)
    for name, digest in expected.items():
        assert iso_reads.file_digest(output, name, entries) == digest, name
