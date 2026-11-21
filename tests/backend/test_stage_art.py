"""
Stage-select icons and banners, derived from the user's own game.

They used to ship as backend/assets/vanilla_stages inside the backend exe. Now
menu_refs copies them out of an m-ex project (first-run setup's fresh one, or
the project the user opens while they are missing), and the three readers --
Tracker's stage icons, the stage-slot panel's art route and the vanilla stage
importer -- use only that copy. Synthetic projects only; no game files.
"""
import io
import json
import threading
import zipfile

import pytest
from flask import Flask

from shared.vanilla_extract import menu_refs

PNG = b'\x89PNG\r\n\x1a\n'


def _stage_json(stage_dir, internal_id, file_name, icon=None, banner=None):
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / f'{internal_id:03d}.json').write_text(json.dumps({
        'name': 'x', 'fileName': file_name,
        'assets': {'icon': icon, 'banner': banner}}), encoding='utf-8')


def _picture(assets, ref, payload):
    path = assets / (ref.replace('\\', '/') + '.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG + payload)


def _project(tmp_path):
    """An m-ex project shaped like `mexcli create`'s: stage jsons at their
    internal id, Windows-style asset refs, pictures under assets/sss."""
    root = tmp_path / 'project'
    stages, assets = root / 'data' / 'stages', root / 'assets'
    # Peach's Castle (internal id 2) and Stadium (16, extensionless root name).
    _stage_json(stages, 2, '/GrCs.dat', 'sss\\icon', 'sss\\icon_001')
    _stage_json(stages, 16, '/GrPs', 'sss\\icon_036', 'sss\\icon_037')
    # Green Greens' slot (13) holds some other stage now: not vanilla art.
    _stage_json(stages, 13, '/GrXx.dat', 'sss\\icon_018', 'sss\\icon_019')
    # An added custom stage reusing a vanilla code sits at a new id.
    _stage_json(stages, 71, '/GrCs_001.dat', 'sss\\icon_058', 'sss\\icon_059')
    for ref, payload in (('sss\\icon', b'castle icon'), ('sss\\icon_001', b'castle banner'),
                         ('sss\\icon_036', b'stadium icon'), ('sss\\icon_037', b'stadium banner'),
                         ('sss\\icon_018', b'not greens'), ('sss\\icon_058', b'custom')):
        _picture(assets, ref, payload)
    (root / 'files').mkdir()
    return root


@pytest.fixture
def refs(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', tmp_path / 'menu_refs')
    return tmp_path / 'menu_refs' / 'vanilla_stages'


def test_derives_each_vanilla_stage_from_its_own_slot(refs, tmp_path):
    counts = menu_refs.derive_menu_refs(_project(tmp_path), only=['stages'])
    assert counts['stages'] == 4
    assert sorted(p.name for p in refs.glob('*.png')) == [
        'GrCs_banner.png', 'GrCs_icon.png', 'GrPs_banner.png', 'GrPs_icon.png']
    assert (refs / 'GrCs_icon.png').read_bytes() == PNG + b'castle icon'
    assert (refs / 'GrPs_banner.png').read_bytes() == PNG + b'stadium banner'
    manifest = json.loads((refs / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest == {'stages': {'GrCs': ['icon', 'banner'], 'GrPs': ['icon', 'banner']}}


def test_stage_art_path_answers_only_from_the_derived_copy(refs, tmp_path):
    assert menu_refs.stage_art_path('GrCs', 'icon') is None
    assert menu_refs.menu_ref_status()['stages'] is False
    assert 'stages' in menu_refs.missing_sets()

    menu_refs.derive_menu_refs(_project(tmp_path), only=['stages'])
    assert menu_refs.stage_art_path('GrCs', 'icon') == refs / 'GrCs_icon.png'
    assert menu_refs.stage_art_path('GrGr', 'icon') is None
    assert menu_refs.menu_ref_status()['stages'] is True
    assert 'stages' not in menu_refs.missing_sets()
    # Only stage codes and the two kinds; nothing path-shaped.
    for code, kind in (('GrCs', 'poster'), ('../GrCs', 'icon'), ('GrCs/..', 'icon'),
                       ('', 'icon'), (None, 'icon')):
        assert menu_refs.stage_art_path(code, kind) is None


def test_a_pass_that_finds_nothing_leaves_the_set_missing(refs, tmp_path):
    empty = tmp_path / 'empty'
    (empty / 'files').mkdir(parents=True)
    assert menu_refs.derive_menu_refs(empty, only=['stages'])['stages'] == 0
    assert 'stages' in menu_refs.missing_sets()  # retried on the next project open


def test_only_limits_the_pass_to_the_named_sets(refs, tmp_path, monkeypatch):
    for name in ('_derive_pause', '_derive_hud', '_derive_series'):
        monkeypatch.setattr(menu_refs, name,
                            lambda *a, _n=name: pytest.fail(f'{_n} must not run'))
    assert menu_refs.derive_menu_refs(_project(tmp_path), only=['stages'])['stages'] == 4


def test_opening_a_project_derives_only_the_missing_sets(tmp_path, monkeypatch):
    from core import state
    calls = []
    monkeypatch.setattr(state, '_publish', lambda path, manager=None: 7)
    monkeypatch.setattr(state, '_current_project_path', tmp_path / 'p' / 'p.mexproj')
    monkeypatch.setattr(menu_refs, 'missing_sets', lambda: ['stages'])
    monkeypatch.setattr(menu_refs, 'derive_menu_refs',
                        lambda project_dir, progress_callback=None, only=None:
                        calls.append((project_dir, only)))
    assert state.set_project_path(tmp_path / 'p' / 'p.mexproj') == 7
    for thread in [t for t in threading.enumerate() if t.name == 'menu-refs-derive']:
        thread.join(timeout=10)
    assert calls == [(tmp_path / 'p', ['stages'])]

    calls.clear()
    monkeypatch.setattr(menu_refs, 'missing_sets', lambda: [])
    state.set_project_path(tmp_path / 'p' / 'p.mexproj')
    assert calls == []  # nothing missing, nothing re-derived from this project


# --------------------------------------------------------------------------
# the three readers
# --------------------------------------------------------------------------

@pytest.fixture
def derived(refs, tmp_path):
    menu_refs.derive_menu_refs(_project(tmp_path), only=['stages'])
    return refs


def test_tracker_stage_icon_serves_the_derived_icon(derived):
    import tracker.routes.icons  # noqa: F401 - attaches /stage-icon to nucleome_bp
    from tracker.routes import nucleome
    from tracker.store.games import STAGE_GR_CODES
    app = Flask(__name__)
    app.register_blueprint(nucleome.nucleome_bp)
    client = app.test_client()
    castle = next(sid for sid, code in STAGE_GR_CODES.items() if code == 'Cs')
    greens = next(sid for sid, code in STAGE_GR_CODES.items() if code == 'Gr')
    response = client.get(f'/api/nucleome/stage-icon/{castle}')
    assert response.status_code == 200
    assert response.data == PNG + b'castle icon'
    response.close()
    assert client.get(f'/api/nucleome/stage-icon/{greens}').status_code == 404


def test_stage_slot_art_route_serves_the_derived_copy(derived, vault):
    import projects.routes.stage_slots as stage_slots
    client = vault.client(stage_slots, 'stage_slots_bp')
    response = client.get('/api/mex/stages/GrCs/art/banner')
    assert response.status_code == 200
    assert response.data == PNG + b'castle banner'
    response.close()
    assert client.get('/api/mex/stages/GrGr/art/icon').status_code == 404


def test_vanilla_stage_import_packs_the_derived_art(derived):
    from vault.importing.vanilla_stage_import import build_vanilla_stage_package
    package, _ = build_vanilla_stage_package(b'\x01', 'grcs', 'Castle Mod')
    with zipfile.ZipFile(io.BytesIO(package)) as zf:
        assert zf.read('icon.png') == PNG + b'castle icon'
        assert zf.read('banner.png') == PNG + b'castle banner'


def test_vanilla_stage_import_without_art_has_no_icon(refs):
    from vault.importing.vanilla_stage_import import build_vanilla_stage_package
    package, _ = build_vanilla_stage_package(b'\x01', 'grgr', 'Greens Mod')
    with zipfile.ZipFile(io.BytesIO(package)) as zf:
        names = set(zf.namelist())
    assert 'icon.png' not in names and 'banner.png' not in names
    assert 'stage.json' in names and 'GrGr.dat' in names
