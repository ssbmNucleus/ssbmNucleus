"""
Tests for the raw vanilla-stage mod import path (vanilla_stage_import.py):
a lone GrXx.dat for a NON-tournament stage (Green Greens, Peach's Castle,
Big Blue...) wraps into an added m-ex custom-stage package, while the 6
tournament-legal codes keep routing to the DAS stage-skin path.
"""
import io
import json
import zipfile

import pytest

from vault.importing.vanilla_stage_import import (
    build_vanilla_stage_package,
    default_stage_mod_name,
    detect_vanilla_stage_dats,
    find_vanilla_stage_code,
    import_vanilla_stage_dats,
)
from vault.importing.vanilla_stage_specs import VANILLA_STAGE_SPECS


# ---------- code matching ----------

@pytest.mark.parametrize('filename,expected', [
    ('GrGr.dat', 'grgr'),                    # bare canonical name
    ('grbb.DAT', 'grbb'),                    # case-insensitive
    ('Legal Big Blue GrBb.dat', 'grbb'),     # code as token in a longer name
    ('GrCn.usd', 'grcn'),                    # English-language variant file
    ('folder/GrSh.dat', 'grsh'),             # nested path
    ('GrI2.dat', 'gri2'),                    # digit-final code stays exact
    ('GrOt_hyrule.usd', 'grot'),             # code followed by separator
])
def test_find_code_matches(filename, expected):
    assert find_vanilla_stage_code(filename) == expected


@pytest.mark.parametrize('filename', [
    'GrNBa.dat', 'GrNLa.dat', 'GrSt.dat', 'GrOp.dat', 'GrIz.dat', 'GrPs.usd',
])
def test_legal_codes_not_claimed(filename):
    """The 6 tournament-legal stages keep going to the DAS skin path."""
    assert find_vanilla_stage_code(filename) is None


@pytest.mark.parametrize('filename', [
    'GrGreatPlateau.dat',   # GrGr must not match as a prefix of a longer word
    'GrPs1.dat',            # Stadium transformation file, not a stage
    'GrGr.png',             # not a dat
    'GrTzd.dat',            # unknown custom-stage code
    'PlFxNr.dat',           # costume
])
def test_non_stage_files_not_claimed(filename):
    assert find_vanilla_stage_code(filename) is None


def test_detect_skips_directories_and_macosx():
    names = ['mod/', '__MACOSX/GrGr.dat', 'mod/GrGr.dat', 'readme.txt']
    found = detect_vanilla_stage_dats(names)
    assert [f['member'] for f in found] == ['mod/GrGr.dat']
    assert found[0]['spec']['name'] == 'Green Greens'


def test_every_spec_has_required_fields():
    for key, spec in VANILLA_STAGE_SPECS.items():
        assert spec['code'].lower() == key
        assert spec['playlist'], f'{key} needs at least one vanilla track'
        for f in ('soundBank', 'collisionMaterials', 'mapDescPointer',
                  'onStageInit', 'onStageLoad', 'vanillaInternalID'):
            assert f in spec, f'{key} missing {f}'
        # function pointers are vanilla main.dol addresses
        assert spec['mapDescPointer'] > 0x80000000
        assert spec['onStageInit'] > 0x80000000


# ---------- naming ----------

def test_default_name_prefers_custom_title():
    spec = VANILLA_STAGE_SPECS['grgr']
    assert default_stage_mod_name(spec, 'whatever', custom_title='Winter Greens') == 'Winter Greens'


def test_default_name_strips_code_token():
    spec = VANILLA_STAGE_SPECS['grbb']
    assert default_stage_mod_name(spec, 'Legal Big Blue GrBb') == 'Legal Big Blue'


def test_default_name_falls_back_to_stage_name():
    spec = VANILLA_STAGE_SPECS['grgr']
    assert default_stage_mod_name(spec, 'GrGr') == 'Green Greens (Mod)'


# ---------- package synthesis ----------

def test_build_package_shape():
    dat = b'\x00' * 64
    pkg, spec = build_vanilla_stage_package(dat, 'grcs', "Castle Mod")
    with zipfile.ZipFile(io.BytesIO(pkg)) as zf:
        names = set(zf.namelist())
        assert 'stage.json' in names
        assert 'GrCs.dat' in names
        assert zf.read('GrCs.dat') == dat
        sj = json.loads(zf.read('stage.json'))

    # identity + vanilla DOL tables carried verbatim
    assert sj['name'] == 'Castle Mod'
    assert sj['fileName'] == 'GrCs.dat'
    assert sj['seriesID'] == spec['seriesID']
    for f in ('collisionMaterials', 'mapDescPointer', 'onStageInit',
              'onStageLoad', 'onStageGo', 'movingCollisionPointer',
              'movingCollisionCount', 'soundBank'):
        assert sj[f] == spec[f], f
    # embedded tables stay empty -- the pointer form is used
    assert sj['mapGOBJs'] == []
    assert sj['movingCollisions'] == []
    # install-time fixup sidecar
    vs = sj['nucleusVanillaStage']
    assert vs['code'] == 'GrCs'
    assert vs['soundBank'] == spec['soundBank']
    assert vs['playlist'] == spec['playlist']
    assert sj['playlist'] == {'entries': spec['playlist']}


def test_build_package_preserves_usd_extension():
    pkg, _ = build_vanilla_stage_package(b'\x01', 'grcn', 'Corneria Mod', dat_ext='.usd')
    with zipfile.ZipFile(io.BytesIO(pkg)) as zf:
        sj = json.loads(zf.read('stage.json'))
        assert sj['fileName'] == 'GrCn.usd'
        assert 'GrCn.usd' in zf.namelist()


def test_build_package_includes_vanilla_sss_assets(tmp_path, monkeypatch):
    # The icon/banner come from the copy derived from the user's own game
    # (menu_refs); nothing is bundled. tests/backend/test_stage_art.py covers
    # the derivation and the no-art case.
    from shared.vanilla_extract import menu_refs
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path)
    art = tmp_path / 'vanilla_stages'
    art.mkdir()
    (art / 'GrGr_icon.png').write_bytes(b'icon')
    (art / 'GrGr_banner.png').write_bytes(b'banner')
    pkg, _ = build_vanilla_stage_package(b'\x01', 'grgr', 'X')
    with zipfile.ZipFile(io.BytesIO(pkg)) as zf:
        assert zf.read('icon.png') == b'icon'
        assert zf.read('banner.png') == b'banner'


# ---------- end-to-end into the vault ----------

def _upload_zip(tmp_path, members):
    p = tmp_path / 'upload.zip'
    with zipfile.ZipFile(p, 'w') as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return p


def test_import_into_vault(vault, tmp_path, monkeypatch):
    from vault.importing import custom_stage_package
    from shared.vanilla_extract import menu_refs
    monkeypatch.setattr(custom_stage_package, 'CUSTOM_STAGES_PATH',
                        vault.storage / 'custom_stages')
    # Stage art derived from the user's own game (nothing is bundled).
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    art = tmp_path / 'menu_refs' / 'vanilla_stages'
    art.mkdir(parents=True)
    for kind in ('icon', 'banner'):
        (art / f'GrGr_{kind}.png').write_bytes(b'\x89PNG\r\n\x1a\n' + kind.encode())

    up = _upload_zip(tmp_path, {'GrGr.dat': b'\x00' * 32})
    entries = import_vanilla_stage_dats(str(up), 'Winter Greens')
    assert len(entries) == 1
    e = entries[0]
    assert e['name'] == 'Winter Greens'
    assert e['vanilla_stage']['code'] == 'GrGr'
    assert e['vanilla_stage']['soundBank'] == VANILLA_STAGE_SPECS['grgr']['soundBank']
    assert e['sound_bank'] == VANILLA_STAGE_SPECS['grgr']['soundBank']
    assert e['has_icon'] and e['has_banner']

    # persisted in vault metadata + on disk
    meta = vault.read()
    assert [s['slug'] for s in meta['custom_stages']] == [e['slug']]
    stage_dir = vault.storage / 'custom_stages' / e['slug']
    assert (stage_dir / 'stage.zip').exists()
    assert (stage_dir / 'stage.json').exists()
    saved = json.loads((stage_dir / 'stage.json').read_text())
    assert saved['nucleusVanillaStage']['code'] == 'GrGr'


def test_import_returns_empty_for_non_matching_zip(vault, tmp_path, monkeypatch):
    from vault.importing import custom_stage_package
    monkeypatch.setattr(custom_stage_package, 'CUSTOM_STAGES_PATH',
                        vault.storage / 'custom_stages')
    up = _upload_zip(tmp_path, {'GrNBa.dat': b'\x00', 'readme.txt': b'hi'})
    assert import_vanilla_stage_dats(str(up), 'X') == []


def test_import_multiple_dats(vault, tmp_path, monkeypatch):
    from vault.importing import custom_stage_package
    monkeypatch.setattr(custom_stage_package, 'CUSTOM_STAGES_PATH',
                        vault.storage / 'custom_stages')
    up = _upload_zip(tmp_path, {'GrGr.dat': b'\x00', 'GrCs.dat': b'\x01'})
    entries = import_vanilla_stage_dats(str(up), 'pack')
    names = sorted(e['name'] for e in entries)
    # multi-dat archives name each stage from its own member/vanilla name
    assert names == ['Green Greens (Mod)', "Princess Peach's Castle (Mod)"]


# ---------- install-time fixups ----------

def test_apply_vanilla_stage_fixups(tmp_path):
    from projects.routes.custom_stages import _apply_vanilla_stage_fixups

    proj_dir = tmp_path / 'proj'
    (proj_dir / 'data' / 'stages').mkdir(parents=True)
    project_path = proj_dir / 'project.mexproj'
    # the added stage landed at internal id 71
    file_paths = [f'{i:03d}.json' for i in range(72)]
    project_path.write_text(json.dumps({'stageSaveMap': {'filePaths': file_paths}}))
    stage_json = proj_dir / 'data' / 'stages' / '071.json'
    stage_json.write_text(json.dumps({
        'name': 'Green Greens (Mod)',
        'soundBank': 55,
        'playlist': {'entries': [{'musicID': 0, 'chanceToPlay': 50}]},
    }))

    vs = VANILLA_STAGE_SPECS['grgr']
    ok = _apply_vanilla_stage_fixups(project_path, 71, {
        'code': 'GrGr', 'soundBank': vs['soundBank'], 'playlist': vs['playlist']})
    assert ok

    patched = json.loads(stage_json.read_text())
    assert patched['soundBank'] == vs['soundBank']
    assert patched['playlist']['entries'] == vs['playlist']


def test_apply_fixups_rejects_bad_internal_id(tmp_path):
    from projects.routes.custom_stages import _apply_vanilla_stage_fixups
    proj_dir = tmp_path / 'proj'
    proj_dir.mkdir()
    project_path = proj_dir / 'project.mexproj'
    project_path.write_text(json.dumps({'stageSaveMap': {'filePaths': ['000.json']}}))
    assert not _apply_vanilla_stage_fixups(project_path, 5, {'soundBank': 1})
    assert not _apply_vanilla_stage_fixups(project_path, None, {'soundBank': 1})


# ---------- unified-import classification ----------

def test_detect_content_type_classifies_non_tournament_dat_as_stage_skin(tmp_path):
    """A raw GrBb.dat is a vault stage skin like any DAS skin (stage_detector
    covers every versus stage); the custom-stage detour is gone from detection."""
    from vault.importing.unified.detection import detect_content_type
    p = _upload_zip(tmp_path, {'GrBb.dat': b'\x00' * 16})
    verdict = detect_content_type(str(p), 'legal_big_blue.zip')
    assert verdict['type'] == 'stage'
    assert verdict['detail']['stages'] == ['Big Blue']
    assert 'vanilla_stage' not in verdict['candidates']


def test_detect_content_type_legal_stage_still_wins(tmp_path):
    from vault.importing.unified.detection import detect_content_type
    p = _upload_zip(tmp_path, {'GrNBa.dat': b'\x00' * 16})
    verdict = detect_content_type(str(p), 'bf_skin.zip')
    assert verdict['type'] == 'stage'
    assert 'vanilla_stage' not in verdict['candidates']
