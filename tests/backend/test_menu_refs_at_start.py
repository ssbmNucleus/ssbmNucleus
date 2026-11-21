"""App start derives the menu-reference sets still missing from the known
vanilla ISO, so an install upgraded to a version with a new set (the stage
icons, 0.9.0) has it without opening a project. Same rule as a project open:
only the missing sets, never one that exists. Synthetic projects and a fake
`mexcli create`; no ISO, no MexCLI, no game files."""
import json
import threading
from pathlib import Path

import pytest

import core.config as config
import projects.install.pristine_base as pristine
import projects.install.test_build as builds
from core import file_lock
from shared.vanilla_extract import menu_refs

PNG = b'\x89PNG\r\n\x1a\n'


def _synthetic_project(root):
    """What `mexcli create` writes that the stage set reads: Peach's Castle at
    internal id 2 with its icon and banner."""
    stages, assets = root / 'data' / 'stages', root / 'assets' / 'sss'
    stages.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    (stages / '002.json').write_text(json.dumps({
        'name': 'x', 'fileName': '/GrCs.dat',
        'assets': {'icon': 'sss\\icon', 'banner': 'sss\\icon_001'}}), encoding='utf-8')
    (assets / 'icon.png').write_bytes(PNG + b'castle icon')
    (assets / 'icon_001.png').write_bytes(PNG + b'castle banner')
    (root / 'files').mkdir(exist_ok=True)
    return root


@pytest.fixture
def refs(tmp_path, monkeypatch):
    """A menu_refs home where only the stage set is missing (an install set up
    before 0.9.0), a known ISO, and a MexCLI that must not run unless a test
    says so."""
    home = tmp_path / 'menu_refs'
    monkeypatch.setattr(menu_refs, 'MENU_REF_DIR', home)
    for key in ('hud', 'pause', 'series'):
        subdir, marker = menu_refs._MARKERS[key]
        (home / subdir).mkdir(parents=True)
        (home / subdir / marker).write_bytes(b'derived earlier')
    iso = tmp_path / 'melee.iso'
    iso.write_bytes(b'GALE01' + b'\0' * 4096)
    mexcli = tmp_path / 'mex' / 'mexcli.exe'
    mexcli.parent.mkdir()
    mexcli.write_bytes(b'synthetic mexcli')
    monkeypatch.setattr(config, 'MEXCLI_PATH', mexcli)
    monkeypatch.setattr(builds, 'PRISTINE_BASE_DIR', tmp_path / 'pristine-base')
    monkeypatch.setattr(menu_refs, 'TEMP_PREFIX', f'nucleus_menu_refs_test_{tmp_path.name}_')
    monkeypatch.setattr(menu_refs.shutil, 'disk_usage',
                        lambda _path: type('U', (), {'free': 10 * 1024 ** 3})())
    creates = []

    def no_create(iso_path, dest):
        creates.append(dest)
        pytest.fail('mexcli create must not run here')

    monkeypatch.setattr(menu_refs, '_mexcli_create', no_create)
    return {'home': home, 'iso': iso, 'mexcli': mexcli, 'creates': creates}


def _stage_files(home):
    return sorted(p.name for p in (home / menu_refs.STAGES_SUBDIR).glob('*.png'))


def _pristine_base(refs):
    key, _identity = pristine.base_key(refs['iso'], refs['mexcli'])
    base = builds.PRISTINE_BASE_DIR / f'base-{key}'
    _synthetic_project(base)
    (base / 'project.mexproj').write_text('{}', encoding='utf-8')
    (base / pristine.RECORD).write_text(json.dumps({'key': key}), encoding='utf-8')
    return base


def test_a_built_pristine_base_gives_the_missing_set_without_a_create(refs):
    base = _pristine_base(refs)
    before = sorted(p.relative_to(base) for p in base.rglob('*'))
    counts = menu_refs.derive_missing_from_iso(refs['iso'])
    assert counts['stages'] == 2
    assert _stage_files(refs['home']) == ['GrCs_banner.png', 'GrCs_icon.png']
    assert menu_refs.missing_sets() == []
    # the base is only read
    assert sorted(p.relative_to(base) for p in base.rglob('*')) == before
    # the sets that existed were not touched
    assert (refs['home'] / 'series' / 'icon_0.png').read_bytes() == b'derived earlier'
    assert not (refs['home'] / menu_refs.ISO_ATTEMPT_NAME).exists()


def test_without_a_base_a_temporary_project_is_made_and_deleted(refs, monkeypatch):
    made = []

    def create(iso_path, dest):
        assert iso_path == refs['iso'] and dest.name.startswith(menu_refs.TEMP_PREFIX)
        made.append(dest)
        _synthetic_project(dest)
        return True

    monkeypatch.setattr(menu_refs, '_mexcli_create', create)
    counts = menu_refs.derive_missing_from_iso(refs['iso'])
    assert counts['stages'] == 2 and menu_refs.missing_sets() == []
    assert len(made) == 1 and not made[0].exists()


def test_the_known_iso_is_the_default_and_nothing_runs_without_one(refs, monkeypatch):
    from shared.vanilla_extract import vanilla_refs
    monkeypatch.setattr(vanilla_refs, 'known_vanilla_iso', lambda: None)
    assert menu_refs.derive_missing_from_iso() is None
    _pristine_base(refs)
    monkeypatch.setattr(vanilla_refs, 'known_vanilla_iso', lambda: refs['iso'])
    assert menu_refs.derive_missing_from_iso()['stages'] == 2


def test_nothing_missing_does_nothing(refs):
    _synthetic_project(refs['home'].parent / 'unused')
    subdir, marker = menu_refs._MARKERS['stages']
    (refs['home'] / subdir).mkdir()
    (refs['home'] / subdir / marker).write_text('{}', encoding='utf-8')
    assert menu_refs.derive_missing_from_iso(refs['iso']) is None
    assert menu_refs.derive_missing_at_start(delay=0) is None
    assert refs['creates'] == []


def test_a_failed_pass_is_not_repeated_at_every_start(refs, monkeypatch):
    calls = []

    def failing_create(iso_path, dest):
        calls.append(dest)
        return False

    monkeypatch.setattr(menu_refs, '_mexcli_create', failing_create)
    assert menu_refs.derive_missing_from_iso(refs['iso'])['stages'] == 0
    assert menu_refs.missing_sets() == ['stages']
    assert menu_refs.derive_missing_from_iso(refs['iso']) is None
    assert len(calls) == 1
    # a different ISO (or another set going missing) is tried again
    refs['iso'].write_bytes(b'GALE01' + b'\1' * 8192)
    assert menu_refs.derive_missing_from_iso(refs['iso']) is not None
    assert len(calls) == 2


def test_no_room_for_a_temporary_project_waits_for_the_next_start(refs, monkeypatch):
    monkeypatch.setattr(menu_refs.shutil, 'disk_usage',
                        lambda _path: type('U', (), {'free': 512 * 1024 ** 2})())
    assert menu_refs.derive_missing_from_iso(refs['iso']) is None
    assert not (refs['home'] / menu_refs.ISO_ATTEMPT_NAME).exists()
    assert refs['creates'] == []


def test_a_base_held_by_a_test_build_is_not_waited_for(refs, monkeypatch):
    _pristine_base(refs)
    with file_lock.exclusive(builds.PRISTINE_BASE_DIR, timeout=1):
        result = {}
        thread = threading.Thread(target=lambda: result.update(
            base=pristine.ready_base(refs['iso'], root=builds.PRISTINE_BASE_DIR,
                                     mexcli=refs['mexcli'], wait=0.1).__enter__()))
        thread.start()
        thread.join(timeout=10)
        assert result == {'base': None}


def test_ready_base_answers_only_a_finished_base_for_this_iso(refs, tmp_path):
    with pristine.ready_base(refs['iso'], root=tmp_path / 'nowhere', mexcli=refs['mexcli']) as base:
        assert base is None
    built = _pristine_base(refs)
    with pristine.ready_base(refs['iso'], root=builds.PRISTINE_BASE_DIR, mexcli=refs['mexcli']) as base:
        assert base == built
    other = tmp_path / 'other.iso'
    other.write_bytes(b'GALE01' + b'\2' * 4096)
    with pristine.ready_base(other, root=builds.PRISTINE_BASE_DIR, mexcli=refs['mexcli']) as base:
        assert base is None


def test_a_set_derived_meanwhile_is_never_overwritten(refs, tmp_path):
    """A project open and the app-start pass can both see 'stages' missing; the
    one that gets the lock second must not overwrite the first one's set."""
    menu_refs.derive_menu_refs(_synthetic_project(tmp_path / 'first'), only=['stages'])
    first = (refs['home'] / menu_refs.STAGES_SUBDIR / 'GrCs_icon.png').read_bytes()
    modded = _synthetic_project(tmp_path / 'modded')
    (modded / 'assets' / 'sss' / 'icon.png').write_bytes(PNG + b'a modded icon')
    assert menu_refs.derive_menu_refs(modded, only=['stages'])['stages'] == 0
    assert (refs['home'] / menu_refs.STAGES_SUBDIR / 'GrCs_icon.png').read_bytes() == first


def test_leftover_temporary_projects_are_swept(refs, tmp_path, monkeypatch):
    import os
    import tempfile
    old = Path(tempfile.gettempdir()) / f'{menu_refs.TEMP_PREFIX}old'
    fresh = Path(tempfile.gettempdir()) / f'{menu_refs.TEMP_PREFIX}fresh'
    for path in (old, fresh):
        (path / 'files').mkdir(parents=True, exist_ok=True)
    try:
        stale = menu_refs.time.time() - menu_refs.STALE_TEMP_SECONDS - 60
        os.utime(old, (stale, stale))
        menu_refs._sweep_temp_projects()
        assert not old.exists() and fresh.exists()
    finally:
        for path in (old, fresh):
            menu_refs.shutil.rmtree(path, ignore_errors=True)


def test_app_start_runs_the_pass_in_the_background(refs, monkeypatch):
    ran = threading.Event()
    monkeypatch.setattr(menu_refs, 'derive_missing_from_iso', lambda iso=None: ran.set())
    thread = menu_refs.derive_missing_at_start(delay=0)
    assert thread is not None and thread.daemon
    thread.join(timeout=10)
    assert ran.is_set()


def test_app_start_starts_it_outside_worker_children():
    source = (Path(config.__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    worker_block = source.index('if os.environ.get("NUCLEUS_WORKER") != "1":\n        from core import jobs')
    call = source.index('derive_missing_at_start()')
    assert worker_block < call < source.index('# No auto-loading - user must select a project')
