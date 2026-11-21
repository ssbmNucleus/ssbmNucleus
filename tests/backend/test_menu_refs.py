"""
Guards the menu-editor reference art derived from the user's own game.

The GmPause textures, the IfAll glyph previews and the m-ex series emblems are
retail imagery, so none of them ships or is tracked (owner, 2026-11-19).
`menu_refs.derive_menu_refs` exports them from a `mexcli create` project
(docs/dev/VANILLA_ASSET_POLICY.md). Only the two IfAll slot manifests still
ship, in backend/assets/hud_vanilla: no pictures, the install path's map.

The two properties worth pinning:

  * resolution -- pause and series answer from the derived copy only; HUD
    falls back to the shipped manifests. All resolved per call so a
    derivation landing mid-session is picked up. A stale module-level constant
    here would send the pause editor at a read-only _MEIPASS path forever.
  * fidelity -- the derived HUD manifests match the shipped ones. They carry
    the *global* texture indices `percent._build_replacement_spec` injects
    against, so "close enough" writes a mod's glyphs into the wrong slots.

The fidelity test needs a real MEX project and HSDRawViewer, so it skips where
neither is available -- which is every CI box without a copy of the game.
"""
from tests.paths import BACKEND
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

menu_refs = pytest.importorskip('shared.vanilla_extract.menu_refs')
from core.config import BACKEND_ASSETS_DIR  # noqa: E402
from tests.left_out import HUD_MANIFEST, require  # noqa: E402

def test_hud_falls_back_to_the_shipped_manifests(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')

    # Nothing derived yet -> the shipped manifests (and no pictures).
    assert menu_refs.hud_dir() == BACKEND_ASSETS_DIR / 'hud_vanilla'

    # The marker appearing mid-session must flip the answer, with no restart.
    derived = tmp_path / 'menu_refs' / 'hud_vanilla'
    derived.mkdir(parents=True)
    (derived / 'manifest_usd.json').write_bytes(b'x')
    assert menu_refs.hud_dir() == derived


@pytest.mark.parametrize('subdir,resolver', [
    ('pause_vanilla', menu_refs.pause_dir),
    ('series', menu_refs.series_dir),
])
def test_pause_and_series_answer_only_from_the_derived_copy(subdir, resolver,
                                                            tmp_path, monkeypatch):
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    assert resolver() == tmp_path / 'menu_refs' / subdir


def test_no_retail_pictures_are_tracked():
    # Only the HUD slot manifests may stay (they hold no imagery).
    for subdir in ('hud_vanilla', 'pause_vanilla', 'series', 'vanilla_stages'):
        pictures = [p.name for p in (BACKEND_ASSETS_DIR / subdir).glob('*')
                    if p.suffix.lower() in ('.png', '.tga', '.dds', '.jpg')]
        assert pictures == [], subdir
    require('app/backend/assets/hud_vanilla/manifest_dat.json', HUD_MANIFEST,
            why='vanilla HUD slot manifests; a clone derives them at first-run setup')
    assert sorted(p.name for p in (BACKEND_ASSETS_DIR / 'hud_vanilla').glob('*')) == [
        'manifest_dat.json', 'manifest_usd.json']


def test_status_reports_each_set(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    status = menu_refs.menu_ref_status()
    assert status == {'path': str(tmp_path / 'menu_refs'),
                      'hud': False, 'pause': False, 'series': False, 'stages': False}
    assert menu_refs.missing_sets() == ['pause', 'hud', 'series', 'stages']


def _a_project():
    """Any mexcli project in this checkout that has the files derivation needs."""
    projects = BACKEND_DIR.parent / 'projects'
    if not projects.is_dir():
        return None
    for candidate in sorted(projects.iterdir()):
        if not candidate.is_dir():
            continue
        if ((candidate / 'files' / 'IfAll.usd').is_file()
                and (candidate / 'files' / 'GmPause.usd').is_file()
                and (candidate / 'data' / 'series.json').is_file()):
            return candidate
    return None


@pytest.mark.skipif(_a_project() is None, reason='no MEX project in this checkout')
def test_derived_sets_match_the_shipped_manifests(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    counts = menu_refs.derive_menu_refs(_a_project())
    assert counts['pause'] == 11, counts
    assert counts['hud'] == 2, counts
    assert counts['series'] >= 16, counts
    assert counts['stages'] >= 46, counts
    assert menu_refs.missing_sets() == []

    for subdir in ('hud_vanilla',):
        derived, bundled = menu_refs.hud_dir(), BACKEND_ASSETS_DIR / subdir
        assert derived != bundled, f'{subdir} did not resolve to the derived copy'
        assert sorted(p.name for p in derived.glob('glyph_*.png'))
        for reference in sorted(bundled.glob('*')):
            produced = derived / reference.name
            assert produced.is_file(), f'{subdir}/{reference.name} was not derived'
            if reference.suffix == '.json':
                # Byte-compare would only be testing json.dumps' whitespace.
                actual = json.loads(produced.read_text(encoding='utf-8'))
                expected = json.loads(reference.read_text(encoding='utf-8'))
                if reference.name.startswith('manifest_') and subdir == 'hud_vanilla':
                    # MEX projects can append different series emblems. All
                    # shared slots must match exactly, including their indices;
                    # only additional emblem frames at the end may differ.
                    actual_slots = actual.pop('textures')
                    expected_slots = expected.pop('textures')
                    shared = min(len(actual_slots), len(expected_slots))
                    assert actual_slots[:shared] == expected_slots[:shared], reference.name
                    assert all(slot['root'] == 'Eblm_matanim_joint'
                               for slot in actual_slots[shared:] + expected_slots[shared:]), reference.name
                assert actual == expected, reference.name
            else:
                assert produced.read_bytes() == reference.read_bytes(), reference.name
