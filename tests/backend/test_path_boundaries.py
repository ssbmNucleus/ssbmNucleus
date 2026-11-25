from tests.paths import BACKEND
import io
import importlib.util
import json
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from core.path_safety import resolve_under_root, validate_path_segment
from core.helpers import _cleanup_managed_output_directory
from projects.install import xdelta as xdelta_tools
from projects.routes import bundles as project_bundles
from vault.importing import custom_stage_package as stage_package


def _load_blueprint_module(relpath):
    path = BACKEND / f'{relpath}.py'
    name = relpath.rsplit('/', 1)[-1]
    spec = importlib.util.spec_from_file_location(f'path_boundary_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assets = _load_blueprint_module('shared/routes/assets')
bundles = _load_blueprint_module('vault/routes/bundles')
custom_stages = _load_blueprint_module('vault/routes/custom_stages')
export = _load_blueprint_module('projects/routes/export')
# The export routes read the export's job record (core/jobs.py).
from projects.install import export_job  # noqa: E402
from core import jobs  # noqa: E402


TEST_TEMP_ROOT = Path(__file__).parent / '.path-boundary-tmp'


@pytest.fixture
def safe_temp_dir():
    TEST_TEMP_ROOT.mkdir(exist_ok=True)
    directory = TEST_TEMP_ROOT / uuid.uuid4().hex
    directory.mkdir(mode=0o777)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            TEST_TEMP_ROOT.rmdir()
        except OSError:
            pass


@pytest.mark.parametrize('value', [
    '../outside.png', '..\\outside.png', '/outside.png',
    'C:/outside.png', 'C:\\outside.png', '\\\\server\\share\\outside.png',
    'images/portrait.png:secret',
    'images/.. /secret.png', 'images/trailing. /secret.png',
    'images/CON.png', 'images/nul.txt', 'images/COM9',
    'images/control\x1f.png',
])
def test_root_resolver_rejects_portable_escape_forms(safe_temp_dir, value):
    with pytest.raises(ValueError):
        resolve_under_root(safe_temp_dir, value)


def test_root_resolver_allows_nested_names_and_blocks_symlink_escape(safe_temp_dir):
    root = safe_temp_dir / 'root'
    outside = safe_temp_dir / 'outside'
    (root / 'folder with spaces').mkdir(parents=True)
    outside.mkdir()
    assert resolve_under_root(root, 'folder with spaces/image.png') == (
        root / 'folder with spaces' / 'image.png').resolve()
    try:
        (root / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation is unavailable')
    with pytest.raises(ValueError):
        resolve_under_root(root, 'link/secret.png')


def test_storage_route_rejects_decoded_windows_escape(safe_temp_dir, monkeypatch):
    monkeypatch.setattr(assets, 'STORAGE_PATH', safe_temp_dir)
    app = Flask(__name__)
    app.register_blueprint(assets.assets_bp)
    response = app.test_client().get('/storage/C:%5Coutside%5Caudit.txt')
    assert response.status_code == 404
    assert 'relative path' in response.get_json()['error']


@pytest.mark.parametrize('value', [
    '../build', '..\\build', '/build', 'C:/build', 'C:\\build',
    '\\\\server\\share', 'folder/build', 'folder\\build', 42, '',
    'build:secret',
    'build. ', 'NUL', 'con.txt', 'LPT1.log', 'bad\x07name',
])
def test_single_segment_rejects_paths(value):
    with pytest.raises(ValueError):
        validate_path_segment(value)


def test_single_segment_preserves_spaces():
    assert validate_path_segment('My Build 2') == 'My Build 2'


def test_export_rejects_non_iso_paths_before_queue(monkeypatch):
    started = []
    monkeypatch.setattr(jobs.threading.Thread, 'start', lambda self: started.append(self))
    app = Flask(__name__)
    app.register_blueprint(export.export_bp)
    client = app.test_client()
    for filename in ('../game.iso', '..\\game.iso', 'C:/game.iso', 'game.zip', 7, '.iso'):
        response = client.post('/api/mex/export/start', json={'filename': filename})
        assert response.status_code == 400
    assert started == []


def _zip_bytes(stage_meta):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('stage.json', json.dumps(stage_meta))
        archive.writestr('Normal Stage.dat', b'dat')
    return output.getvalue()


def test_custom_stage_rejects_escaping_reference_before_vault_write(
        safe_temp_dir, monkeypatch):
    vault = safe_temp_dir / 'custom-stages'
    monkeypatch.setattr(stage_package, 'CUSTOM_STAGES_PATH', vault)
    payload = _zip_bytes({'name': 'Bad', 'fileName': '..\\outside.dat'})
    with pytest.raises(ValueError, match='stage file reference'):
        stage_package.import_custom_stage_zip_bytes(payload, 'Bad')
    assert not vault.exists()


def test_custom_stage_accepts_file_names_with_spaces(safe_temp_dir, monkeypatch):
    vault = safe_temp_dir / 'custom-stages'
    monkeypatch.setattr(stage_package, 'CUSTOM_STAGES_PATH', vault)
    monkeypatch.setattr(stage_package, 'metadata_transaction', _NoopMetadataTransaction)
    entry = stage_package.import_custom_stage_zip_bytes(
        _zip_bytes({'name': 'Normal', 'fileName': 'Normal Stage.dat'}), 'Normal')
    assert entry['name'] == 'Normal'


class _NoopMetadataTransaction:
    def __init__(self, **kwargs):
        self.data = {'custom_stages': []}

    def __enter__(self):
        return self.data

    def __exit__(self, *args):
        return False


def test_bundle_import_rejects_bad_build_name_before_copy(safe_temp_dir, monkeypatch):
    source = safe_temp_dir / 'bad.ssbm'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'build_name': 'C:/outside'}))
    destination = safe_temp_dir / 'bundles'
    destination.mkdir()
    monkeypatch.setattr(bundles, 'BUNDLE_PATH', destination)
    with pytest.raises(ValueError, match='build_name'):
        bundles.import_bundle_file(source, 'Bad')
    assert list(destination.iterdir()) == []


def test_bundle_cache_identity_includes_id_and_content(safe_temp_dir):
    iso_dir = safe_temp_dir / 'isos'
    iso_dir.mkdir()
    first = safe_temp_dir / 'first.ssbm'
    second = safe_temp_dir / 'second.ssbm'
    first.write_bytes(b'first bundle')
    second.write_bytes(b'second bundle')
    one = project_bundles._bundle_play_artifacts('id-one', first, iso_dir, 'Same Name')
    other_id = project_bundles._bundle_play_artifacts('id-two', first, iso_dir, 'Same Name')
    other_content = project_bundles._bundle_play_artifacts('id-one', second, iso_dir, 'Same Name')
    assert one[1] != other_id[1]
    assert one[1] != other_content[1]


def test_bundle_cache_requires_matching_completion_marker(safe_temp_dir):
    iso = safe_temp_dir / 'bundle.iso'
    marker = safe_temp_dir / 'bundle.complete.json'
    iso.write_bytes(b'finished')
    assert not project_bundles._bundle_cache_is_complete(marker, iso, 'abc', 'digest')
    marker.write_text(json.dumps({'bundle_id': 'abc', 'sha256': 'other'}))
    assert not project_bundles._bundle_cache_is_complete(marker, iso, 'abc', 'digest')
    marker.write_text(json.dumps({'bundle_id': 'abc', 'sha256': 'digest'}))
    assert project_bundles._bundle_cache_is_complete(marker, iso, 'abc', 'digest')


def test_bundle_publish_preserves_existing_good_iso_until_replace(safe_temp_dir):
    iso = safe_temp_dir / 'bundle.iso'
    marker = safe_temp_dir / 'bundle.complete.json'
    iso.write_bytes(b'old good bytes')
    missing_staging = safe_temp_dir / 'failed.part'
    with pytest.raises(RuntimeError, match='produced no ISO'):
        project_bundles._publish_bundle_artifact(
            missing_staging, iso, marker, 'abc', 'digest')
    assert iso.read_bytes() == b'old good bytes'

    staging = safe_temp_dir / 'success.part'
    staging.write_bytes(b'new good bytes')
    project_bundles._publish_bundle_artifact(staging, iso, marker, 'abc', 'digest')
    assert iso.read_bytes() == b'new good bytes'
    assert project_bundles._bundle_cache_is_complete(marker, iso, 'abc', 'digest')


def test_save_uses_immutable_artifact_id(safe_temp_dir, monkeypatch):
    output = safe_temp_dir / 'output'
    artifacts = output / 'artifacts'
    destination_dir = safe_temp_dir / 'saved'
    artifacts.mkdir(parents=True)
    destination_dir.mkdir()
    old = artifacts / 'old.iso'
    new = artifacts / 'new.iso'
    old.write_bytes(b'first generation')
    new.write_bytes(b'second generation')
    monkeypatch.setattr(export_job, 'OUTPUT_PATH', output)
    _isolate_jobs(safe_temp_dir, monkeypatch)
    for artifact_id, path in (('old', old), ('new', new)):
        jobs.run_inline(export_job.EXPORT_KIND, lambda job, path=path: {
            'path': str(path), 'filename': 'same.iso'}, job_id=artifact_id)
    app = Flask(__name__)
    app.register_blueprint(export.export_bp)
    response = app.test_client().post('/api/mex/export/save', json={
        'artifactId': 'old', 'filename': 'same.iso',
        'destination': str(destination_dir / 'same.iso'),
    })
    assert response.status_code == 200
    assert (destination_dir / 'same.iso').read_bytes() == b'first generation'
    assert list(destination_dir.glob('*.part')) == []


def test_download_rejects_unowned_file_after_registry_loss(safe_temp_dir, monkeypatch):
    output = safe_temp_dir / 'output'
    artifacts = output / 'artifacts'
    artifacts.mkdir(parents=True)
    (artifacts / 'orphan.iso').write_bytes(b'orphaned partial or old bytes')
    monkeypatch.setattr(export_job, 'OUTPUT_PATH', output)
    _isolate_jobs(safe_temp_dir, monkeypatch)
    app = Flask(__name__)
    app.register_blueprint(export.export_bp)
    response = app.test_client().get(
        '/api/mex/export/download/orphan/game.iso')
    assert response.status_code == 404


def _isolate_jobs(directory, monkeypatch):
    import core.state as core_state
    monkeypatch.setattr(jobs, '_root_override', directory / 'jobs')
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(core_state, 'get_socketio', lambda: None)


def test_xdelta_download_serves_only_a_finished_build_jobs_artifact(safe_temp_dir, monkeypatch):
    from projects.routes import xdelta as xdelta_routes
    output = safe_temp_dir / 'output'
    artifacts = output / 'artifacts'
    artifacts.mkdir(parents=True)
    built = artifacts / 'job-1.iso'
    built.write_bytes(b'patched disc')
    outside = safe_temp_dir / 'keep.iso'
    outside.write_bytes(b'keep')
    monkeypatch.setattr(xdelta_routes, 'OUTPUT_PATH', output)
    _isolate_jobs(safe_temp_dir, monkeypatch)
    jobs.run_inline(xdelta_routes.BUILD_KIND, lambda job: {
        'path': str(built), 'filename': 'My_Patch_1.iso'}, job_id='job-1')
    jobs.run_inline(xdelta_routes.BUILD_KIND, lambda job: {
        'path': str(outside), 'filename': 'keep.iso'}, job_id='job-2')
    app = Flask(__name__)
    app.register_blueprint(xdelta_routes.xdelta_bp)
    client = app.test_client()

    for job_id in ('job-2', '..%5Ckeep.iso', 'C:%5Ckeep.iso', 'missing'):
        assert client.get(f'/api/mex/xdelta/download/{job_id}').status_code == 404
    assert outside.read_bytes() == b'keep'

    response = client.get('/api/mex/xdelta/download/job-1')
    assert response.status_code == 200
    assert response.data == b'patched disc'
    assert 'My_Patch_1.iso' in response.headers['Content-Disposition']
    response.close()


def test_staging_names_keep_iso_as_final_suffix(safe_temp_dir):
    build_id = 'build_abc'
    export_staging = safe_temp_dir / f'{build_id}.part.iso'
    assert export_staging.suffix == '.iso'
    patch_staging = (safe_temp_dir / 'patch.iso').with_name(
        'patch.unique.part.iso')
    assert patch_staging.suffix == '.iso'


def test_xdelta_cache_identity_and_marker(safe_temp_dir):
    iso_dir = safe_temp_dir / 'isos'
    iso_dir.mkdir()
    first = safe_temp_dir / 'first.xdelta'
    second = safe_temp_dir / 'second.xdelta'
    first.write_bytes(b'first patch')
    second.write_bytes(b'second patch')
    one = xdelta_tools._xdelta_play_artifacts('id-one', first, iso_dir, 'Same Name')
    other_id = xdelta_tools._xdelta_play_artifacts('id-two', first, iso_dir, 'Same Name')
    other_content = xdelta_tools._xdelta_play_artifacts('id-one', second, iso_dir, 'Same Name')
    assert one[1] != other_id[1]
    assert one[1] != other_content[1]

    digest, iso, marker = one
    iso.write_bytes(b'finished')
    assert not xdelta_tools._xdelta_cache_is_complete(
        marker, iso, 'id-one', digest)
    marker.write_text(json.dumps({'patch_id': 'id-one', 'sha256': digest}))
    assert xdelta_tools._xdelta_cache_is_complete(
        marker, iso, 'id-one', digest)


def test_xdelta_failed_publish_preserves_good_iso(safe_temp_dir):
    iso = safe_temp_dir / 'patch.iso'
    marker = safe_temp_dir / 'patch.complete.json'
    iso.write_bytes(b'old good bytes')
    with pytest.raises(RuntimeError, match='produced no ISO'):
        xdelta_tools._publish_xdelta_artifact(
            safe_temp_dir / 'failed.part.iso', iso, marker, 'abc', 'digest')
    assert iso.read_bytes() == b'old good bytes'


def test_xdelta_play_retries_after_partial_failure(safe_temp_dir, monkeypatch):
    patch_dir = safe_temp_dir / 'patches'
    iso_dir = safe_temp_dir / 'isos'
    patch_dir.mkdir()
    iso_dir.mkdir()
    (patch_dir / 'abc.xdelta').write_bytes(b'patch bytes')
    vanilla = safe_temp_dir / 'vanilla.iso'
    vanilla.write_bytes(b'vanilla')
    launched = []
    outcomes = [1, 0]

    class Process:
        def __init__(self, command):
            self.returncode = outcomes.pop(0)
            Path(command[-1]).write_bytes(
                b'partial' if self.returncode else b'complete iso')

        def poll(self):
            return self.returncode

        def communicate(self):
            return b'', b'bad patch' if self.returncode else b''

    boot = sys.modules['shared.ingame.boot']
    monkeypatch.setattr(xdelta_tools, 'XDELTA_PATH', patch_dir)
    monkeypatch.setattr(xdelta_tools, 'require_xdelta_exe', lambda: 'xdelta3')
    monkeypatch.setattr(xdelta_tools.subprocess, 'Popen', lambda command, **kwargs: Process(command))
    monkeypatch.setattr(boot, 'iso_dir_from_slippi', lambda path: iso_dir)
    monkeypatch.setattr(boot, 'launch_real', lambda slippi, iso: launched.append(Path(iso)))

    with pytest.raises(RuntimeError, match='bad patch'):
        xdelta_tools.run_xdelta_play('abc', 'Same Name', 'slippi', str(vanilla))
    assert launched == []
    assert list(iso_dir.glob('*.part.iso')) == []

    xdelta_tools.run_xdelta_play('abc', 'Same Name', 'slippi', str(vanilla))
    assert len(launched) == 1
    assert launched[0].read_bytes() == b'complete iso'
    assert list(iso_dir.glob('*.complete.json'))


@pytest.mark.parametrize(('platform_name', 'subdirectory'), [
    ('linux', 'xdelta-linux'),
    ('darwin', 'xdelta-mac'),
])
def test_xdelta_resolver_selects_portable_packaged_tool(
        safe_temp_dir, monkeypatch, platform_name, subdirectory):
    resources_root = safe_temp_dir / 'packaged-resources'
    executable = resources_root / 'utility' / subdirectory / 'xdelta3'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'tool')
    monkeypatch.setattr(xdelta_tools, 'RESOURCES_DIR', resources_root)
    monkeypatch.setattr(xdelta_tools.sys, 'platform', platform_name)
    monkeypatch.setattr(xdelta_tools.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(xdelta_tools.os, 'name', 'posix')
    assert xdelta_tools.get_xdelta_exe() == executable
    assert xdelta_tools.require_xdelta_exe() == executable


@pytest.mark.parametrize('platform_name', ['linux', 'darwin'])
def test_xdelta_resolver_reports_missing_portable_tool(
        safe_temp_dir, monkeypatch, platform_name):
    monkeypatch.setattr(xdelta_tools, 'RESOURCES_DIR', safe_temp_dir / 'missing')
    monkeypatch.setattr(xdelta_tools.sys, 'platform', platform_name)
    monkeypatch.setattr(xdelta_tools.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(xdelta_tools.os, 'name', 'posix')
    monkeypatch.setattr(xdelta_tools.shutil, 'which', lambda name: None)
    with pytest.raises(FileNotFoundError, match='bundled tool is missing'):
        xdelta_tools.require_xdelta_exe()


def test_bundle_workers_share_xdelta_resolver():
    import inspect
    source = inspect.getsource(project_bundles)
    assert 'def _resolve_xdelta_exe' not in source
    # export and install run xdelta3 themselves; play decodes through the shared decode_patch.
    assert source.count('require_xdelta_exe()') == 2
    assert source.count('decode_patch(') == 1
    assert 'require_xdelta_exe()' in inspect.getsource(xdelta_tools.decode_patch)


def test_other_python_xdelta_callers_use_required_resolver():
    backend_root = BACKEND
    project_source = (backend_root / 'projects' / 'routes' / 'project.py').read_text()

    assert 'get_xdelta_exe()' not in project_source
    assert 'require_xdelta_exe()' in project_source


def test_managed_output_cleanup_does_not_follow_directory_symlink(safe_temp_dir):
    output = safe_temp_dir / 'output'
    artifacts = output / 'artifacts'
    outside = safe_temp_dir / 'outside'
    artifacts.mkdir(parents=True)
    outside.mkdir()
    secret = outside / 'keep.iso'
    secret.write_bytes(b'keep')
    try:
        (artifacts / 'linked.iso').symlink_to(secret)
        linked_directory = output / 'linked-artifacts'
        linked_directory.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation is unavailable')

    count, size = _cleanup_managed_output_directory(artifacts, output)
    assert (count, size) == (0, 0)
    assert secret.read_bytes() == b'keep'
    count, size = _cleanup_managed_output_directory(linked_directory, output)
    assert (count, size) == (0, 0)
    assert secret.read_bytes() == b'keep'
