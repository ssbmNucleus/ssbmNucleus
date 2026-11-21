"""
DAS loaders (projects/install/das_loaders.py).

Every loader keeps much of the game's own stage file (Stadium's carries the
transformation models), so the installer ships an xdelta patch per stage
against the user's own vanilla root instead of the file. The properties pinned
here:

  * only a source whose bytes are the vanilla root is ever patched, and only a
    result whose bytes are the loader is ever installed -- a modded root must
    not turn into a broken loader;
  * the project's own copies are tried before the recorded ISO, and a rebuilt
    loader is cached so a later install needs no source;
  * every patch that ships is registered, every legal stage has one, and no
    plain loader ships.

The fast tests stand in for xdelta3; the slow ones run the real tool, once on
synthetic bytes and once per shipped patch against its vanilla root.
"""
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from core import stages
from projects.install import das_loaders
from tests.left_out import left_out


def _sha(data):
    return hashlib.sha256(data).hexdigest()


VANILLA = b'vanilla stadium root ' * 64
LOADER = b'das stadium loader ' * 16


@pytest.fixture
def framework(tmp_path, monkeypatch):
    """A loader dir holding one patched loader (GrPs) and one plain one (GrNBa),
    a cache dir, and no recorded ISO."""
    loaders = tmp_path / 'DynamicAlternateStages'
    loaders.mkdir()
    (loaders / 'GrNBa.dat').write_bytes(b'plain battlefield loader')
    (loaders / 'GrPs.usd.xdelta').write_bytes(b'synthetic patch')
    monkeypatch.setattr(das_loaders, 'DERIVED_LOADER_DIR', tmp_path / 'cache')
    monkeypatch.setattr(das_loaders, 'PATCHED_LOADERS', {
        'GrPs.usd': {'source_sha256': _sha(VANILLA), 'target_sha256': _sha(LOADER)}})
    iso_reads = []
    monkeypatch.setattr(das_loaders, '_vanilla_from_iso',
                        lambda name: iso_reads.append(name) or None)
    decoded = []

    def fake_apply(source, patch, target_sha256, out_path):
        # xdelta3 stand-in: the synthetic patch maps VANILLA to LOADER.
        decoded.append(Path(source))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(LOADER)
        return _sha(LOADER) == target_sha256

    monkeypatch.setattr(das_loaders, '_apply_patch', fake_apply)
    return {'dir': loaders, 'decoded': decoded, 'iso_reads': iso_reads,
            'cache': tmp_path / 'cache'}


def _project(tmp_path, root_bytes, vanilla_copy=None):
    files = tmp_path / 'project' / 'files'
    (files / 'GrPs').mkdir(parents=True)
    (files / 'GrPs.usd').write_bytes(root_bytes)
    if vanilla_copy is not None:
        (files / 'GrPs' / 'vanilla.dat').write_bytes(vanilla_copy)
    return files


def test_a_shipped_loader_file_is_used_as_is(framework, tmp_path):
    files = tmp_path / 'files'
    files.mkdir()
    (files / 'GrNBa.dat').write_bytes(b'vanilla battlefield')
    loader = das_loaders.install_das_loader('GrNBa', files, loader_dir=framework['dir'])
    assert loader == framework['dir'] / 'GrNBa.dat'
    assert (files / 'GrNBa.dat').read_bytes() == b'plain battlefield loader'
    assert framework['decoded'] == []


def test_stadium_is_rebuilt_from_the_projects_own_root_and_cached(framework, tmp_path):
    files = _project(tmp_path, VANILLA)
    loader = das_loaders.install_das_loader('GrPs', files, loader_dir=framework['dir'])
    assert loader == framework['cache'] / 'GrPs.usd'
    assert (files / 'GrPs.usd').read_bytes() == LOADER
    assert framework['decoded'] == [files / 'GrPs.usd']
    assert framework['iso_reads'] == []  # a project copy fitted; the disc was not read

    # A second project needs no source: the cache answers.
    other = tmp_path / 'other'
    other.mkdir()
    assert das_loaders.install_das_loader('GrPs', other, loader_dir=framework['dir'])
    assert (other / 'GrPs.usd').read_bytes() == LOADER
    assert len(framework['decoded']) == 1


def test_a_modded_root_is_skipped_for_the_vanilla_copy(framework, tmp_path):
    # Reinstalling: the root is already a loader (or a skin); DAS kept the
    # original as GrPs/vanilla.dat.
    files = _project(tmp_path, b'modded stadium', vanilla_copy=VANILLA)
    assert das_loaders.install_das_loader('GrPs', files, loader_dir=framework['dir'])
    assert framework['decoded'] == [files / 'GrPs' / 'vanilla.dat']
    assert (files / 'GrPs.usd').read_bytes() == LOADER


def test_no_vanilla_source_leaves_the_root_untouched(framework, tmp_path):
    files = _project(tmp_path, b'modded stadium', vanilla_copy=b'also modded')
    assert das_loaders.install_das_loader('GrPs', files, loader_dir=framework['dir']) is None
    assert (files / 'GrPs.usd').read_bytes() == b'modded stadium'
    assert framework['decoded'] == []
    assert framework['iso_reads'] == ['GrPs.usd']  # the last resort was asked


def test_a_stale_cache_is_rebuilt(framework, tmp_path):
    framework['cache'].mkdir()
    (framework['cache'] / 'GrPs.usd').write_bytes(b'half-written')
    files = _project(tmp_path, VANILLA)
    assert das_loaders.install_das_loader('GrPs', files, loader_dir=framework['dir'])
    assert (framework['cache'] / 'GrPs.usd').read_bytes() == LOADER


def test_only_the_loader_itself_counts_as_installed(framework, tmp_path):
    files = _project(tmp_path, VANILLA)
    assert not das_loaders.has_das_loader('GrPs', files, loader_dir=framework['dir'])  # still vanilla
    assert das_loaders.install_das_loader('GrPs', files, loader_dir=framework['dir'])
    assert das_loaders.has_das_loader('GrPs', files, loader_dir=framework['dir'])
    # A plain loader counts when the root is byte for byte that file.
    (files / 'GrNBa.dat').write_bytes(b'vanilla battlefield')
    assert not das_loaders.has_das_loader('GrNBa', files, loader_dir=framework['dir'])
    assert das_loaders.install_das_loader('GrNBa', files, loader_dir=framework['dir'])
    assert das_loaders.has_das_loader('GrNBa', files, loader_dir=framework['dir'])
    # No root at all (GrPs.dat is the Japanese file, never the loader).
    assert not das_loaders.has_das_loader('GrOp', files, loader_dir=framework['dir'])


def test_status_reports_a_partial_install_and_install_says_why(framework, tmp_path, monkeypatch,
                                                               open_project):
    """Stadium has no vanilla source: install sets up the other five, its
    warning names Stadium, and /das/status keeps offering the install for it
    instead of counting the bare GrPs/ folder as installed."""
    from flask import Flask
    import projects.routes.das as das_routes
    from vault.routes.das import das_bp

    base = tmp_path / 'base'
    loaders = base / 'utility' / 'DynamicAlternateStages'
    loaders.mkdir(parents=True)
    for code in ('GrIz', 'GrNBa', 'GrNLa', 'GrOp', 'GrSt'):
        (loaders / f'{code}.dat').write_bytes(f'{code} loader'.encode())
    (loaders / 'GrPs.usd.xdelta').write_bytes(b'synthetic patch')
    monkeypatch.setattr(das_routes, 'BASE_PATH', base)
    monkeypatch.setattr(das_routes, 'PROJECT_ROOT', tmp_path / 'root')
    monkeypatch.setattr(das_routes, 'STORAGE_PATH', tmp_path / 'storage')

    files = _project(tmp_path, b'modded stadium')
    files.joinpath('GrPs').rmdir()
    for code in ('GrIz', 'GrNBa', 'GrNLa', 'GrOp', 'GrSt'):
        (files / f'{code}.dat').write_bytes(f'vanilla {code}'.encode())
    (files / 'GrPs.dat').write_bytes(b'japanese stadium')
    (files.parent / 'project.mexproj').write_text('', encoding='utf-8')
    open_project(files.parent / 'project.mexproj')
    app = Flask(__name__)
    app.register_blueprint(das_bp)
    client = app.test_client()

    status = client.get('/api/mex/das/status').get_json()
    assert status['installed'] is False and status['installedStages'] == [] and status['missingStages'] == []

    result = client.post('/api/mex/das/install').get_json()
    assert result['success'] is True
    assert 'Pokemon Stadium' in result['warning']
    assert (files / 'GrPs.usd').read_bytes() == b'modded stadium'

    status = client.get('/api/mex/das/status').get_json()
    assert status['installed'] is True
    assert sorted(status['installedStages']) == ['GrIz', 'GrNBa', 'GrNLa', 'GrOp', 'GrSt']
    assert status['missingStages'] == ['GrPs']


@left_out('app/utility/DynamicAlternateStages', why='the DAS loader patches, made from Melee stage files')
def test_every_shipped_patch_is_registered_and_every_legal_stage_has_a_loader():
    shipped = sorted(p.name for p in stages.DAS_LOADER_DIR.glob('*' + das_loaders.PATCH_SUFFIX))
    assert shipped == [name + das_loaders.PATCH_SUFFIX for name in sorted(das_loaders.PATCHED_LOADERS)]
    for name in das_loaders.PATCHED_LOADERS:
        # The game's own file must never ship beside its patch.
        assert not (stages.DAS_LOADER_DIR / name).exists(), name
    for code in stages.LEGAL_STAGE_CODES:
        assert stages.das_loader_path(code) is not None, code
        # every legal stage's loader is a patch; no plain loader ships (11-19)
        assert das_loaders.loader_name(code) in das_loaders.PATCHED_LOADERS, code
    assert sorted(p.name for p in stages.DAS_LOADER_DIR.iterdir()) == shipped


# --------------------------------------------------------------------------
# the real tool
# --------------------------------------------------------------------------

def _xdelta3():
    from projects.install.xdelta import get_xdelta_exe
    exe = get_xdelta_exe()
    return exe if isinstance(exe, Path) or shutil.which(str(exe)) else None


@pytest.mark.slow
@pytest.mark.skipif(_xdelta3() is None, reason='xdelta3 is not available')
def test_a_real_xdelta3_patch_round_trips(tmp_path, monkeypatch):
    source = tmp_path / 'vanilla.usd'
    target = tmp_path / 'loader.usd'
    source.write_bytes(bytes(range(256)) * 300)
    target.write_bytes(bytes(range(256)) * 150 + b'DAS function table' * 40)
    loaders = tmp_path / 'DynamicAlternateStages'
    loaders.mkdir()
    subprocess.run([str(_xdelta3()), '-e', '-9', '-S', 'none', '-A=', '-s', str(source),
                    str(target), str(loaders / 'GrPs.usd.xdelta')], check=True)
    monkeypatch.setattr(das_loaders, 'DERIVED_LOADER_DIR', tmp_path / 'cache')
    monkeypatch.setattr(das_loaders, '_vanilla_from_iso', lambda name: None)
    monkeypatch.setattr(das_loaders, 'PATCHED_LOADERS', {'GrPs.usd': {
        'source_sha256': _sha(source.read_bytes()),
        'target_sha256': _sha(target.read_bytes())}})
    files = tmp_path / 'files'
    files.mkdir()
    shutil.copy(source, files / 'GrPs.usd')
    assert das_loaders.install_das_loader('GrPs', files, loader_dir=loaders)
    assert (files / 'GrPs.usd').read_bytes() == target.read_bytes()


@pytest.mark.slow
@pytest.mark.skipif(_xdelta3() is None, reason='xdelta3 is not available')
@pytest.mark.parametrize('code', sorted(stages.LEGAL_STAGE_CODES))
def test_every_shipped_patch_rebuilds_its_loader(tmp_path, monkeypatch, code):
    from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
    name = das_loaders.loader_name(code)
    vanilla = ensure_vanilla_ref(name)
    if vanilla is None:
        pytest.skip(f'no vanilla {name} (no recorded ISO)')
    monkeypatch.setattr(das_loaders, 'DERIVED_LOADER_DIR', tmp_path / 'cache')
    loader = das_loaders.resolve_das_loader(code, sources=(vanilla,))
    assert loader is not None and loader.parent == tmp_path / 'cache'
    assert _sha(loader.read_bytes()) == das_loaders.PATCHED_LOADERS[name]['target_sha256']
