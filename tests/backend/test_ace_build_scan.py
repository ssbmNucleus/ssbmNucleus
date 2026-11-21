"""ISO/patch scans of the ACE Build (community reports #31 and #62).

- #31: announcer name-calls are covered in test_narrator_calls.py.
- #62: ACE's playable Giga Bowser (PlGkp.dat) is named "Giga Bowser" and the
  vanilla-name filter silently dropped it from the scan.
"""
from tests.paths import BACKEND
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from vault.catalog import custom_characters as cc_catalog
from vault.importing import custom_character_scan as cc_scan
from vault.routes.custom_characters import skins as cc_skins
import vault.catalog.custom_character_skins as cc_skin_store
from projects.routes import custom_characters as cc_install
from core import metadata as core_metadata


def _fighter(name, data_file, call=540000):
    return {'name': name, 'announcerCall': call,
            'files': {'fighterDataPath': data_file}, 'costumes': [], 'assets': {}}


def test_vanilla_detection_uses_the_fighter_data_file():
    assert cc_scan._is_vanilla_fighter(_fighter('Giga Bowser', 'PlGk.dat'))
    assert cc_scan._is_vanilla_fighter(_fighter('NONE', ''))
    assert cc_scan._is_vanilla_fighter(_fighter('Mario', 'PlMr.dat'))
    # an added fighter reusing a vanilla name ships its own ftData
    assert not cc_scan._is_vanilla_fighter(_fighter('Giga Bowser', 'PlGkp.dat'))
    assert not cc_scan._is_vanilla_fighter(_fighter('Metal Mario', 'PlMM.dat'))


def test_scan_imports_an_added_fighter_with_a_vanilla_name(tmp_path, monkeypatch):
    storage = tmp_path / 'storage'
    custom = storage / 'custom_characters'
    custom.mkdir(parents=True)
    monkeypatch.setattr(cc_catalog, 'STORAGE_PATH', storage)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', custom)
    monkeypatch.setattr(cc_scan, 'CUSTOM_CHARACTERS_PATH', custom)
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', storage / 'metadata.json')
    monkeypatch.setattr(cc_scan, 'MEXCLI_PATH', tmp_path / 'no-mexcli.exe')
    # Nucleus's own built-in Giga Bowser is already in the vault
    (custom / 'giga-bowser').mkdir()
    (storage / 'metadata.json').write_text(json.dumps({
        'characters': {}, 'stages': {},
        'custom_characters': [{'slug': 'giga-bowser', 'name': 'Giga Bowser',
                               'source': 'builtin', 'builtin': True}]}))

    proj = tmp_path / 'scan'
    fighters_dir = proj / 'data' / 'fighters'
    fighters_dir.mkdir(parents=True)
    roster = [_fighter('Mario', 'PlMr.dat'), _fighter('Giga Bowser', 'PlGkp.dat'),
              _fighter('Giga Bowser', 'PlGk.dat')]
    for i, fd in enumerate(roster):
        (fighters_dir / f'{i:03d}.json').write_text(json.dumps(fd))
    (proj / 'project.mexproj').write_text(json.dumps({
        'build': {'shortName': 'ACE Build'},
        'fighterSaveMap': {'filePaths': [f'{i:03d}.json' for i in range(len(roster))]}}))

    imported, skipped = cc_scan._extract_custom_characters_from_project(proj, 'iso-scan')
    assert imported == ['Giga Bowser (ACE Build)']
    assert skipped == []

    names = [c['name'] for c in json.loads((storage / 'metadata.json').read_text())['custom_characters']]
    assert names == ['Giga Bowser', 'Giga Bowser (ACE Build)']
    # special-fighter skins keep routing to the built-in
    meta = json.loads((storage / 'metadata.json').read_text())
    assert cc_skin_store.find_custom_character_for_fighter(meta, 'Giga Bowser')['slug'] == 'giga-bowser'

    # a rescan recognises it instead of importing a second copy
    imported, skipped = cc_scan._extract_custom_characters_from_project(proj, 'iso-scan')
    assert imported == [] and skipped == ['Giga Bowser (ACE Build)']


def test_layout_editor_icon_lists_carry_the_backend_token():
    """#30: the CSS/SSS editors' side lists load icons through <img>, which
    can't send X-Nucleus-Token; a hand-built URL 401s and draws a blank tile."""
    storage_ui = BACKEND_DIR.parent / 'frontend' / 'src' / 'projects' / 'menus'
    for name in ('CssLayoutEditor.jsx', 'SssLayoutEditor.jsx'):
        src = (storage_ui / name).read_text(encoding='utf-8')
        start = src.index('getIconUrl=')
        prop = src[start:start + 250]
        helper = re.match(r'getIconUrl=\{(\w+)\}', prop)
        if helper:  # a named helper: its definition must build the URL
            definition = src.index(f'const {helper.group(1)} =')
            prop = src[definition:definition + 250]
        assert 'backendMediaUrl(' in prop, name


# --- item-only clone_engine for clones (ACE Metal Mario side-B, #31) --------

def test_items_patch_keeps_only_the_item_hooks():
    import struct
    from core import clone_patch
    from vault.climbers.engine_code import hsd_root_names
    data = clone_patch.items_patch_bytes()
    assert hsd_root_names(data) == [clone_patch.ITEMS_ROOT]
    fs, dsz, rc, rtc, xc = struct.unpack('>5I', data[:20])
    assert fs == len(data)
    body = data[0x20:0x20 + dsz]
    root = struct.unpack('>I', data[0x20 + dsz + rc * 4:0x20 + dsz + rc * 4 + 4])[0]
    table, count = struct.unpack('>II', body[root + 0x0C:root + 0x14])
    assert count == 4
    hooks = [struct.unpack('>I', body[table + i * 8:table + i * 8 + 4])[0] for i in range(count)]
    assert tuple(hooks) == clone_patch.KEEP_HOOKS
    # the code, relocations and debug table are the bundled patch's, untouched
    src = clone_patch.CLONE_ENGINE_DAT.read_bytes()
    assert body[:root + 0x10] == src[0x20:0x20 + root + 0x10]


def test_items_patch_refuses_an_unexpected_layout():
    from core import clone_patch
    with pytest.raises(ValueError):
        clone_patch.items_patch_bytes(b'\x00' * 0x40)


def test_which_fighters_get_the_item_patch():
    from core.clone_patch import fighter_needs_items_patch
    clone = {'functions': {'specialS': 0x800E0F10}, 'items': [{'name': 'cape'}]}
    assert fighter_needs_items_patch(clone)
    assert not fighter_needs_items_patch({**clone, 'items': []})         # no item slots
    assert not fighter_needs_items_patch({'functions': {'specialS': 0}, 'items': [{}]})  # own code
    assert not fighter_needs_items_patch({})


def test_install_zip_gets_the_item_patch(tmp_path):
    import zipfile
    from core.clone_patch import PATCH_ENTRY
    def make(name, fighter, extra=()):
        p = tmp_path / name
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('fighter.json', json.dumps(fighter))
            for n in extra:
                zf.writestr(n, b'x')
        return p
    clone = {'functions': {'specialS': 0x800E0F10}, 'items': [{}]}
    entries = cc_install._clone_patch_entries(make('a.zip', clone))
    assert list(entries) == [PATCH_ENTRY] and entries[PATCH_ENTRY][:4] != b'\0\0\0\0'
    # a package that ships its own patches keeps them
    assert cc_install._clone_patch_entries(make('b.zip', clone, ['patches/clone_engine.dat'])) == {}
    assert cc_install._clone_patch_entries(make('c.zip', {'functions': {}, 'items': []})) == {}


def test_clone_patch_is_baked_into_the_vault_zip(tmp_path):
    import zipfile
    from core.clone_patch import PATCH_ENTRY
    clone = {'name': 'Metal Mario', 'functions': {'specialS': 0x800E0F10}, 'items': [{}]}
    char_dir = tmp_path / 'metal-mario'
    char_dir.mkdir()
    with zipfile.ZipFile(char_dir / 'fighter.zip', 'w') as zf:
        zf.writestr('fighter.json', json.dumps(clone))
        zf.writestr('PlMM.dat', b'dat')
    assert cc_scan._bake_clone_patch(char_dir, clone)
    with zipfile.ZipFile(char_dir / 'fighter.zip') as zf:
        names = zf.namelist()
    assert PATCH_ENTRY in names and 'PlMM.dat' in names and 'fighter.json' in names
    # idempotent: a re-scan does not add a second copy
    assert not cc_scan._bake_clone_patch(char_dir, clone)
    with zipfile.ZipFile(char_dir / 'fighter.zip') as zf:
        assert zf.namelist().count(PATCH_ENTRY) == 1
    # and the install-time fallback sees it and adds nothing
    assert cc_install._clone_patch_entries(char_dir / 'fighter.zip') == {}
    # a fighter with its own code is left untouched
    other = tmp_path / 'wolf'
    other.mkdir()
    with zipfile.ZipFile(other / 'fighter.zip', 'w') as zf:
        zf.writestr('fighter.json', '{}')
    assert not cc_scan._bake_clone_patch(other, {'functions': {'specialS': 0}, 'items': [{}]})


def test_scan_bakes_the_patch_for_new_and_existing_entries(tmp_path, monkeypatch):
    import zipfile
    from core.clone_patch import PATCH_ENTRY
    storage = tmp_path / 'storage'
    custom = storage / 'custom_characters'
    custom.mkdir(parents=True)
    monkeypatch.setattr(cc_catalog, 'STORAGE_PATH', storage)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', custom)
    monkeypatch.setattr(cc_scan, 'CUSTOM_CHARACTERS_PATH', custom)
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', storage / 'metadata.json')
    fake_cli = tmp_path / 'mexcli.exe'
    fake_cli.write_bytes(b'')
    monkeypatch.setattr(cc_scan, 'MEXCLI_PATH', fake_cli)
    clone = {'name': 'Metal Mario', 'functions': {'specialS': 0x800E0F10}, 'items': [{}],
             'files': {'fighterDataPath': 'PlMM.dat'}, 'costumes': [], 'assets': {}}

    class _Done:
        returncode = 0
        stdout = stderr = ''

    def fake_run(cmd, **_k):             # mexcli export-fighter <proj> <idx> <zip>
        with zipfile.ZipFile(cmd[4], 'w') as zf:
            zf.writestr('fighter.json', json.dumps(clone))
        return _Done()
    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(cc_scan, '_build_ssm_index', lambda _p: [])

    (storage / 'metadata.json').write_text(json.dumps({'custom_characters': []}))
    proj = tmp_path / 'scan'
    (proj / 'data' / 'fighters').mkdir(parents=True)
    (proj / 'data' / 'fighters' / '000.json').write_text(json.dumps(clone))
    (proj / 'project.mexproj').write_text(json.dumps({'fighterSaveMap': {'filePaths': ['000.json']}}))

    imported, _ = cc_scan._extract_custom_characters_from_project(proj, 'iso-scan')
    assert imported == ['Metal Mario']
    zp = custom / 'metal-mario' / 'fighter.zip'
    with zipfile.ZipFile(zp) as zf:
        assert PATCH_ENTRY in zf.namelist()

    # an entry scanned before this existed (no patch) is updated on re-scan
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr('fighter.json', json.dumps(clone))
    _, skipped = cc_scan._extract_custom_characters_from_project(proj, 'iso-scan')
    assert skipped == ['Metal Mario']
    with zipfile.ZipFile(zp) as zf:
        assert zf.namelist().count(PATCH_ENTRY) == 1


def test_code_referenced_archives_are_baked_into_the_vault_zip(tmp_path):
    """#33-class freeze: ACE 2.0's Raichu code loads largetrailrc.dat by name;
    without it the match crashed on load on any other disc."""
    import zipfile
    proj = tmp_path / 'scan'
    files = proj / 'files'
    files.mkdir(parents=True)
    (files / 'PlRc.dat').write_bytes(b'\x00code\x00largetrailrc.dat\x00PlRcAJ.dat\x00missing.dat\x00')
    (files / 'LargeTrailRc.dat').write_bytes(b'trail')
    (files / 'PlRcAJ.dat').write_bytes(b'anim')
    fighter = {'files': {'fighterDataPath': 'PlRc.dat', 'animFile': 'PlRcAJ.dat'}}
    assert set(cc_scan._code_referenced_files(proj, fighter)) == {'LargeTrailRc.dat'}

    char_dir = tmp_path / 'raichu'
    char_dir.mkdir()
    with zipfile.ZipFile(char_dir / 'fighter.zip', 'w') as zf:
        zf.writestr('fighter.json', '{}')
        zf.writestr('PlRc.dat', b'x')
    assert cc_scan._bake_referenced_files(char_dir, fighter, proj) == ['LargeTrailRc.dat']
    with zipfile.ZipFile(char_dir / 'fighter.zip') as zf:
        assert zf.read('LargeTrailRc.dat') == b'trail'
    # a re-scan does not add it twice
    assert cc_scan._bake_referenced_files(char_dir, fighter, proj) == []


def test_rescan_restores_a_truncated_bone_count(tmp_path):
    """ACE 2.0 Meta Knight: an old MexCLI packed boneCount 82 instead of 84."""
    import zipfile
    char_dir = tmp_path / 'meta-knight'
    char_dir.mkdir()
    packed = {'name': 'Meta Knight', 'boneDefinitions': {'lookup': {'boneCount': 82, 'top': 0}, 'ext': []}}
    with zipfile.ZipFile(char_dir / 'fighter.zip', 'w') as zf:
        zf.writestr('fighter.json', json.dumps(packed))
    scanned = {'boneDefinitions': {'lookup': {'boneCount': 84, 'top': 0}, 'ext': []}}
    assert cc_scan._repair_truncated_bone_count(char_dir, scanned)
    with zipfile.ZipFile(char_dir / 'fighter.zip') as zf:
        meta = json.loads(zf.read('fighter.json'))
    assert meta['boneDefinitions']['lookup']['boneCount'] == 84 and meta['name'] == 'Meta Knight'
    assert not cc_scan._repair_truncated_bone_count(char_dir, scanned)     # idempotent
    # a zip that is not short is left alone
    assert not cc_scan._repair_truncated_bone_count(
        char_dir, {'boneDefinitions': {'lookup': {'boneCount': 60}}})


def test_scan_preserves_standalone_demo_archives_and_backfills_rescans(tmp_path, monkeypatch):
    """Classic loads <demoIntro/demoEnding>.dat when the source ships it.

    export-fighter omits these archives, and the fallback archives do not
    necessarily contain a custom fighter's animation roots (ACE Wolf).
    """
    import zipfile
    storage = tmp_path / 'storage'
    custom = storage / 'custom_characters'
    custom.mkdir(parents=True)
    monkeypatch.setattr(cc_catalog, 'STORAGE_PATH', storage)
    monkeypatch.setattr(cc_catalog, 'CUSTOM_CHARACTERS_PATH', custom)
    monkeypatch.setattr(cc_scan, 'CUSTOM_CHARACTERS_PATH', custom)
    monkeypatch.setattr(core_metadata, 'METADATA_FILE', storage / 'metadata.json')
    fake_cli = tmp_path / 'mexcli.exe'
    fake_cli.touch()
    monkeypatch.setattr(cc_scan, 'MEXCLI_PATH', fake_cli)
    monkeypatch.setattr(cc_scan, '_build_ssm_index', lambda _p: [])
    fighter = _fighter('Wolf', 'PlWf.dat')
    fighter['files'].update(demoIntro='ftDemoIntroWolf', demoEnding='ftDemoEndingWolf')
    archives = {'ftDemoIntroWolf.dat': b'source intro',
                'ftDemoEndingWolf.dat': b'source ending'}

    def export_without_standalone_demos(cmd, **_kwargs):
        with zipfile.ZipFile(cmd[4], 'w') as zf:
            zf.writestr('fighter.json', json.dumps(fighter))
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(subprocess, 'run', export_without_standalone_demos)
    (storage / 'metadata.json').write_text(json.dumps({'custom_characters': []}))
    proj = tmp_path / 'scan'
    (proj / 'data' / 'fighters').mkdir(parents=True)
    (proj / 'files').mkdir()
    for name, data in archives.items():
        (proj / 'files' / name).write_bytes(data)
    (proj / 'data' / 'fighters' / '000.json').write_text(json.dumps(fighter))
    (proj / 'project.mexproj').write_text(json.dumps({'fighterSaveMap': {'filePaths': ['000.json']}}))

    assert cc_scan._extract_custom_characters_from_project(proj, 'iso-scan') == (['Wolf'], [])
    zp = custom / 'wolf' / 'fighter.zip'
    with zipfile.ZipFile(zp) as zf:
        for name, data in archives.items():
            assert zf.read(name) == data

    # Emulate a vault entry from the old scanner; re-scan repairs the package.
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr('fighter.json', json.dumps(fighter))
    assert cc_scan._extract_custom_characters_from_project(proj, 'iso-scan') == ([], ['Wolf'])
    with zipfile.ZipFile(zp) as zf:
        for name, data in archives.items():
            assert zf.namelist().count(name) == 1
            assert zf.read(name) == data
    assert cc_scan._bake_referenced_files(zp.parent, fighter, proj) == []


def test_demo_archives_leave_existing_zip_entries_and_embedded_demos_alone(tmp_path):
    import zipfile
    files = tmp_path / 'scan' / 'files'
    files.mkdir(parents=True)
    (files / 'ftDemoIntroWolf.dat').write_bytes(b'source intro')
    char_dir = tmp_path / 'wolf'
    char_dir.mkdir()
    zp = char_dir / 'fighter.zip'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr('fighter.json', '{}')
        zf.writestr('FTDEMOINTROWOLF.DAT', b'existing custom intro')
    fighter = {'files': {'demoIntro': 'ftDemoIntroWolf', 'demoEnding': 'ftDemoEndingFox'}}
    before = zp.read_bytes()
    # Fox's ending lives in GmRegEnd.dat, not a standalone archive. Do not
    # invent a file, require standalone archives, or replace a packaged edit.
    assert cc_scan._bake_referenced_files(char_dir, fighter, files.parent) == []
    assert zp.read_bytes() == before


@pytest.mark.parametrize('symbol', [None, 123, '', '../outside', r'..\outside',
                                  '/outside', r'C:\outside', 'outside:stream',
                                  'outside\0', 'outside.', 'outside '])
def test_demo_archive_names_cannot_escape_the_source_files(tmp_path, symbol):
    import zipfile
    files = tmp_path / 'scan' / 'files'
    files.mkdir(parents=True)
    (files.parent / 'outside.dat').write_bytes(b'not a game archive')
    char_dir = tmp_path / 'wolf'
    char_dir.mkdir()
    zp = char_dir / 'fighter.zip'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr('fighter.json', '{}')
    before = zp.read_bytes()
    assert cc_scan._bake_referenced_files(
        char_dir, {'files': {'demoIntro': symbol}}, files.parent) == []
    assert zp.read_bytes() == before
