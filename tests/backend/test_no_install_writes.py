"""At run time the app writes nothing inside its own install (0.9.0 build 3 Mac smoke test).

After first-run setup and a model import, ``codesign --verify --deep --strict`` failed on the .app: 29 files had
been added inside the bundle. 27 were vanilla ``Pl*Nr.dat`` that setup copied into the shipped
``resources/utility/tools/processor/csp_data`` (nothing ever read them; the renderer's vanilla DATs are the
reference bank in the data folder). Two were ``__pycache__`` files rigswap's Python wrote beside the loose sources
of its shipped package. The same writes fail on the read-only Linux AppImage and are lost on every Windows update.
"""
import json
import sys
from pathlib import Path

import pytest

import core.config
import generate_csp
from shared.vanilla_extract.first_run_setup import FirstRunSetup


def _snapshot(root):
    """Every path under ``root`` with its size and mtime: any file added, changed or removed shows."""
    out = []
    for path in sorted(root.rglob('*')):
        stat = path.stat()
        out.append((path.relative_to(root).as_posix(), path.is_dir(), stat.st_size if path.is_file() else 0,
                    stat.st_mtime_ns if path.is_file() else 0))
    return out


def _install(tmp_path):
    """A packaged app's resources folder as the installer lays it out: the backend exe, the shipped CSP recipe
    tree (scenes only, no DATs), the bundled Sheik art and menu sounds. -> resources dir"""
    resources = tmp_path / 'install' / 'resources'
    (resources / 'backend').mkdir(parents=True)
    (resources / 'backend' / 'mex_backend.exe').write_bytes(b'MZ')
    for folder in ('Bowser', 'Fox', 'Ice Climbers', 'Ice Climbers (Popo)', 'Ice Climbers (Nana)', 'G&W'):
        scene = resources / 'utility' / 'tools' / 'processor' / 'csp_data' / folder / 'scene.yml'
        scene.parent.mkdir(parents=True)
        scene.write_text('frame: 0\n', encoding='utf-8')
    sheik = resources / 'utility' / 'assets' / 'vanilla' / 'Sheik' / 'PlSkNr' / 'csp.png'
    sheik.parent.mkdir(parents=True)
    sheik.write_bytes(b'png')
    sound = resources / 'utility' / 'assets' / 'vanilla' / 'sounds' / 'click.wav'
    sound.parent.mkdir(parents=True)
    sound.write_bytes(b'RIFF')
    return resources


def test_first_run_setup_writes_nothing_inside_the_install(tmp_path, monkeypatch):
    """A frozen setup, its ISO-reading phases stood in for, leaves the install byte for byte as it was, while the
    vanilla costume DATs the old phase 4 copied from are right there in the data folder to tempt it."""
    from shared.vanilla_extract import bone_refs, menu_refs, vanilla_refs
    from tracker.video import anim_fetch, sprites
    from vault.importing import sound_banks

    # Stand-ins first, while sys.frozen is still unset: each module is imported here, in a normal state.
    monkeypatch.setattr(bone_refs, 'ensure_bone_refs', lambda iso=None: None)
    monkeypatch.setattr(menu_refs, 'derive_menu_refs', lambda temp_dir, progress=None: None)
    monkeypatch.setattr(sound_banks, 'seed_original_banks', lambda temp_dir: 0)
    monkeypatch.setattr(vanilla_refs, 'record_vanilla_iso', lambda iso: None)
    monkeypatch.setattr(sprites, 'ensure_sprites', lambda: None)
    monkeypatch.setattr(anim_fetch, 'ensure_anim_zips', lambda progress_cb=None: {})
    monkeypatch.setenv('NUCLEUS_HD_CSP_PRESEED', '0')
    import tempfile
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path / 'temp'))
    (tmp_path / 'temp').mkdir()

    resources = _install(tmp_path)
    data = tmp_path / 'data'
    for character, code in (('Bowser', 'PlKpNr'), ('Ice Climbers', 'PlPpNr'), ('Nana', 'PlNnNr'),
                            ('Mr. Game & Watch', 'PlGwNr')):
        dat = data / 'utility' / 'assets' / 'vanilla' / character / code / f'{code}.dat'
        dat.parent.mkdir(parents=True)
        dat.write_bytes(b'vanilla costume')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(resources / 'backend' / 'mex_backend.exe'))

    setup = FirstRunSetup(data, resources / 'utility' / 'mex' / 'mexcli.exe', storage_path=data / 'storage')
    assert setup.bundled_resources_dir == resources
    ok = {'success': True}
    monkeypatch.setattr(setup, '_extract_iso', lambda iso, temp_dir, progress=None: ok)
    monkeypatch.setattr(setup, '_copy_character_assets', lambda temp_dir, progress=None: ok)
    monkeypatch.setattr(setup, '_copy_csp_reference_dats', lambda temp_dir, progress=None: ok)
    monkeypatch.setattr(setup, 'stage_builtin_giga_bowser', lambda temp_dir: ok)
    monkeypatch.setattr(setup, '_copy_stage_images', lambda temp_dir, progress=None: ok)
    monkeypatch.setattr(setup, '_extract_menu_sounds', lambda temp_dir, progress=None: ok)
    before = _snapshot(resources)
    phases = []

    result = setup.run_setup('vanilla.iso', progress_callback=lambda phase, *rest: phases.append(phase))

    assert result['success'], result
    assert _snapshot(resources) == before, 'setup wrote inside the install'
    assert 'copying_csp_data' not in phases
    # It still reads the install: the bundled Sheik art and menu sounds land in the data folder.
    assert (data / 'utility' / 'assets' / 'vanilla' / 'Sheik' / 'PlSkNr' / 'csp.png').read_bytes() == b'png'
    assert (data / 'utility' / 'assets' / 'vanilla' / 'sounds' / 'click.wav').read_bytes() == b'RIFF'


@pytest.fixture
def bank(tmp_path, monkeypatch):
    """The data folder's CSP reference bank (storage/test-base/files), the one STORAGE_PATH names."""
    storage = tmp_path / 'data' / 'storage'
    files = storage / 'test-base' / 'files'
    files.mkdir(parents=True)
    monkeypatch.setattr(core.config, 'STORAGE_PATH', storage)
    return files


def test_the_renderer_takes_its_vanilla_dats_from_the_data_folder(tmp_path, bank):
    """ftData (low-poly hiding, G&W's colour), the bind-pose skeleton and Fox's gun all come from the reference
    bank in the data folder: first in the search, and the shipped csp_data is never a candidate."""
    for name in ('PlKp.dat', 'PlKpNr.dat', 'PlFx.dat'):
        (bank / name).write_bytes(b'vanilla reference')
    model = tmp_path / 'imports' / 'costume.dat'
    model.parent.mkdir()
    model.write_bytes(b'a model import')

    dirs = generate_csp._test_base_files_dirs()
    assert dirs[0] == bank
    assert not any('csp_data' in Path(d).parts for d in dirs)
    assert generate_csp._find_ftdata(model, 'Bowser') == bank / 'PlKp.dat'
    assert generate_csp._vanilla_skeleton_ref('Bowser') == bank / 'PlKpNr.dat'
    gun = generate_csp._fox_gun_args()
    assert Path(gun[1]) == (bank / 'PlFx.dat').resolve()


def test_a_missing_reference_is_an_error_in_the_log_once(tmp_path, bank, monkeypatch):
    """A bank damaged after setup's check renders portraits without what the file gives (a visibly wrong
    portrait). That is said at ERROR, once per file, naming where it looked."""
    monkeypatch.setattr(generate_csp, '_test_base_files_dirs', lambda: [bank])
    monkeypatch.setattr(generate_csp, '_REPORTED_MISSING_REFS', set())
    errors = []
    monkeypatch.setattr(generate_csp.logger, 'error', lambda message, *a, **k: errors.append(message))
    model = tmp_path / 'costume.dat'
    model.write_bytes(b'a model import')

    assert generate_csp._find_ftdata(model, 'Bowser') is None
    assert generate_csp._find_ftdata(model, 'Bowser') is None
    assert len(errors) == 1 and 'PlKp.dat' in errors[0] and str(bank) in errors[0]
    assert generate_csp._find_ftdata(model, 'Some Custom Fighter') is None
    assert len(errors) == 1, 'a fighter with no vanilla code has no reference to miss'


def _set_up_data_folder(data, storage):
    """A data folder as an earlier version's finished setup left it (scaled down: one fighter, a 3-file bank)."""
    setup = FirstRunSetup(data, data / 'mexcli.exe', storage_path=storage)
    setup.VANILLA_FIGHTER_COUNT = 1
    setup.CSP_REFERENCE_EXPECTED_FILE_COUNT = 3
    costume = setup.vanilla_dir / 'Bowser' / 'PlKpNr'
    costume.mkdir(parents=True)
    (costume / 'csp.png').write_bytes(b'png')
    (costume / 'PlKpNr.dat').write_bytes(b'vanilla costume')
    setup.stages_dir.mkdir(parents=True)
    for name in setup.STAGE_ICONS.values():
        (setup.stages_dir / name).write_bytes(b'png')
    names = ['PlKp.dat', 'PlKpNr.dat', 'PlKpRe.dat']
    setup.csp_reference_dir.mkdir(parents=True)
    for name in names:
        (setup.csp_reference_dir / name).write_bytes(b'vanilla reference')
    setup.csp_reference_manifest.write_text(json.dumps(
        {'version': setup.CSP_REFERENCE_MANIFEST_VERSION, 'source': 'user-verified-iso', 'files': names}),
        encoding='utf-8')
    return setup


def test_an_updated_install_renders_from_its_data_folder_without_running_setup_again(tmp_path, monkeypatch):
    """Upgrade path (0.8.17 -> 0.9.0). The update replaces the install, and the 27 csp_data copies an older setup
    put there go with it. Nothing needs them back: the bytes the renderer reads have been in the data folder's
    reference bank since 0.6.3, so the setup check passes (no re-run) and the renderer finds them. A bank that has
    lost a file is the one case that needs setup, and the check says so (never a silently wrong portrait)."""
    data = tmp_path / 'data'
    storage = data / 'storage'
    setup = _set_up_data_folder(data, storage)
    old_install = _install(tmp_path)
    left_over = old_install / 'utility' / 'tools' / 'processor' / 'csp_data' / 'Bowser' / 'PlKpNr.dat'
    left_over.write_bytes(b'what an older setup copied here')
    monkeypatch.setattr(core.config, 'STORAGE_PATH', storage)

    assert setup.check_setup_needed() == {'complete': True, 'details': 'All vanilla assets present'}
    model = tmp_path / 'imports' / 'costume.dat'
    model.parent.mkdir()
    model.write_bytes(b'a model import')
    assert generate_csp._find_ftdata(model, 'Bowser') == setup.csp_reference_dir / 'PlKp.dat'
    assert generate_csp._vanilla_skeleton_ref('Bowser') == setup.csp_reference_dir / 'PlKpNr.dat'

    (setup.csp_reference_dir / 'PlKp.dat').unlink()
    check = setup.check_setup_needed()
    assert check['complete'] is False and check['reason'] == 'csp_references_missing'
    assert 'PlKp.dat' in check['details']


FAKE_RIGSWAP = r'''
import json, sys
from pathlib import Path
import rigswap.load.convert          # a plain module beside the package's loose sources, as load/convert.py ships
args = sys.argv[1:]
out = Path(args[2])
out.mkdir(parents=True, exist_ok=True)
(out / 'result.json').write_text(json.dumps(dict(
    status='failed', failed=dict(stage='load', cause='a stand-in'), seconds=0.0, cost_usd=0.0,
    dont_write_bytecode=bool(sys.flags.dont_write_bytecode))), encoding='utf-8')
'''


def test_rigswap_runs_without_writing_bytecode_beside_its_package(tmp_path, monkeypatch):
    """rigswap's package lives in the install (utility/rigswap/app); the downloaded Python must not write
    __pycache__ beside it. The spawn's environment says so, and a real run leaves the package as it was."""
    from randall.model_import.chat import import_job
    monkeypatch.setattr(import_job, 'openrouter_key', lambda key=None: None)
    monkeypatch.delenv('PYTHONDONTWRITEBYTECODE', raising=False)
    assert import_job._environment(None)['PYTHONDONTWRITEBYTECODE'] == '1'
    assert import_job._environment(None, relay=tmp_path / 'asks')['PYTHONDONTWRITEBYTECODE'] == '1'

    home = tmp_path / 'resources' / 'utility' / 'rigswap' / 'app'
    package = home / 'rigswap' / 'plugins' / 'melee'
    package.mkdir(parents=True)
    (home / 'rigswap' / 'load').mkdir()
    for folder in (home / 'rigswap', home / 'rigswap' / 'plugins', package, home / 'rigswap' / 'load'):
        (folder / '__init__.py').write_text('', encoding='utf-8')
    (home / 'rigswap' / 'load' / 'convert.py').write_text('X = 1\n', encoding='utf-8')
    (package / 'costume.py').write_text(FAKE_RIGSWAP, encoding='utf-8')
    before = _snapshot(home)

    result = import_job.rigswap(sys.executable, home, tmp_path / 'model.zip', 'Fox', tmp_path / 'out',
                                cache=tmp_path / 'cache', log=lambda line: None)

    assert result['dont_write_bytecode'] is True, result
    assert _snapshot(home) == before, 'rigswap wrote inside its package'
