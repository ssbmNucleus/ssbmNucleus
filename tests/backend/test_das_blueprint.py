from tests.paths import BACKEND
import sys
import zipfile
from pathlib import Path

from flask import Flask


BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

import projects.install.das as das_engine
import projects.routes.das as das_project_routes
from vault.routes.das import das_bp
from projects.install.das import (
    add_button_indicator,
    direct_variant_child,
    get_variant_match_key,
    migrate_das_folder_extensions,
    migrate_stadium_variant_stems,
    normalize_variant_name,
    sanitize_filename,
    select_stage_archive_member,
    stage_code_from_archive_member,
    stadium_runtime_variant_name,
    stadium_variant_hashed_match_key,
    stadium_variant_match_key,
    strip_button_indicator,
)


def test_button_helpers_normalize_spacing():
    assert strip_button_indicator('tabuu-batt(B)') == 'tabuu-batt'
    assert strip_button_indicator('tabuu-batt (B)') == 'tabuu-batt'
    assert strip_button_indicator('tabuu   batt   (B)') == 'tabuu batt'
    assert add_button_indicator('TabuuBatt', 'x') == 'TabuuBatt(X)'
    assert sanitize_filename('tabuu   batt\t(B)') == 'tabuu batt (B)'
    assert normalize_variant_name('tabuu batt') == 'TabuuBatt'
    assert normalize_variant_name('tabuu batt (b)') == 'TabuuBatt(B)'
    assert get_variant_match_key('tabuu batt') == 'tabuubatt'
    assert get_variant_match_key('TabuuBatt(B)') == 'tabuubatt'


def test_stadium_runtime_name_is_bounded_stable_and_preserves_button():
    original = 'WatercolorStadium(X)'
    safe = stadium_runtime_variant_name(original)

    assert len(safe) == 17
    assert safe.endswith('(X)')
    assert safe == stadium_runtime_variant_name(original)
    assert safe == stadium_runtime_variant_name(safe)
    assert stadium_variant_match_key(safe) == (
        stadium_variant_hashed_match_key('WatercolorStadium'))

    without_button = stadium_runtime_variant_name(strip_button_indicator(safe))
    assert len(without_button) <= 17
    assert stadium_variant_match_key(without_button) == stadium_variant_match_key(safe)


def test_stadium_short_name_collision_salts_produce_distinct_bounded_names():
    names = [stadium_runtime_variant_name('NightSky(X)', salt=f'collision-{i}')
             for i in range(1, 4)]
    assert len(set(names + ['NightSky(X)'])) == 4
    assert all(len(name) <= 17 and name.endswith('(X)') for name in names)
    assert all(stadium_runtime_variant_name(name) == name for name in names)


def test_direct_variant_child_rejects_path_traversal(tmp_path):
    import pytest

    assert direct_variant_child(tmp_path, 'BattleCity') == (
        tmp_path / 'BattleCity').resolve()
    for unsafe in ('..', '../outside', '..\\outside', 'folder/name'):
        with pytest.raises(ValueError, match='Invalid DAS variant name'):
            direct_variant_child(tmp_path, unsafe)


def test_rename_route_trims_stray_space_when_removing_button(tmp_path, open_project):
    project_dir = tmp_path / 'project'
    files_dir = project_dir / 'files' / 'GrNBa'
    files_dir.mkdir(parents=True)
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    (files_dir / 'TabuuBatt(B).dat').write_bytes(b'test')
    sidecars = files_dir / 'TabuuBatt(B)'
    sidecars.mkdir()
    sidecars.joinpath('GrPs1.dat').write_bytes(b'form')

    open_project(project_dir / 'project.mexproj')

    app = Flask(__name__)
    app.register_blueprint(das_bp)
    client = app.test_client()

    response = client.post('/api/mex/das/rename', json={
        'stageCode': 'GrNBa',
        'oldName': 'TabuuBatt(B)',
        'newName': 'tabuu batt '
    })

    assert response.status_code == 200
    assert (files_dir / 'TabuuBatt.dat').exists()
    assert not (files_dir / 'tabuu batt .dat').exists()
    assert (files_dir / 'TabuuBatt' / 'GrPs1.dat').read_bytes() == b'form'
    assert not sidecars.exists()


def test_stadium_rename_shortens_button_assignment_and_moves_sidecars(tmp_path, open_project):
    project_dir = tmp_path / 'project'
    files_dir = project_dir / 'files' / 'GrPs'
    forms = files_dir / 'WatercolorStadium'
    forms.mkdir(parents=True)
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    files_dir.joinpath('WatercolorStadium.dat').write_bytes(b'normal')
    forms.joinpath('GrPs3.dat').write_bytes(b'water')
    open_project(project_dir / 'project.mexproj')

    app = Flask(__name__)
    app.register_blueprint(das_bp)
    response = app.test_client().post('/api/mex/das/rename', json={
        'stageCode': 'GrPs',
        'oldName': 'WatercolorStadium',
        'newName': 'WatercolorStadium(X)',
    })

    assert response.status_code == 200
    safe_name = stadium_runtime_variant_name('WatercolorStadium(X)')
    assert files_dir.joinpath(f'{safe_name}.dat').read_bytes() == b'normal'
    assert files_dir.joinpath(safe_name, 'GrPs3.dat').read_bytes() == b'water'


def test_remove_route_deletes_variant_transformation_sidecars(tmp_path, open_project):
    project_dir = tmp_path / 'project'
    files_dir = project_dir / 'files' / 'GrPs'
    forms_dir = files_dir / 'BattleCity'
    forms_dir.mkdir(parents=True)
    (project_dir / 'project.mexproj').write_text('', encoding='utf-8')
    (files_dir / 'BattleCity.dat').write_bytes(b'stage')
    forms_dir.joinpath('GrPs1.dat').write_bytes(b'form')
    open_project(project_dir / 'project.mexproj')

    app = Flask(__name__)
    app.register_blueprint(das_bp)
    response = app.test_client().post('/api/mex/das/remove', json={
        'stageCode': 'GrPs',
        'variantName': 'BattleCity',
    })

    assert response.status_code == 200
    assert not (files_dir / 'BattleCity.dat').exists()
    assert not forms_dir.exists()


def test_migrate_das_extensions_heals_legacy_usd_stadium(tmp_path):
    """Legacy versions wrote Stadium alts as .usd, which the m-ex loader rejects
    ('no valid alts found' -> crash). Migration renames them to .dat."""
    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    grps.mkdir(parents=True)
    grps.joinpath('vanilla.usd').write_bytes(b'base')
    grps.joinpath('AllBlack.usd').write_bytes(b'allblack')
    grps.joinpath('TransStad.usd').write_bytes(b'transstad')

    result = migrate_das_folder_extensions(files_dir)

    # Every .usd alt is now a valid .dat alt; nothing left for the loader to reject.
    assert sorted(p.name for p in grps.glob('*.usd')) == []
    assert (grps / 'vanilla.dat').read_bytes() == b'base'
    assert (grps / 'AllBlack.dat').read_bytes() == b'allblack'
    assert (grps / 'TransStad.dat').read_bytes() == b'transstad'
    assert len(result['renamed']) == 3

    # Idempotent: a second pass is a clean no-op.
    again = migrate_das_folder_extensions(files_dir)
    assert again == {'renamed': [], 'removed': []}


def test_migrate_das_extensions_collision_handling(tmp_path):
    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    grps.mkdir(parents=True)
    # vanilla present in both extensions -> the redundant .usd base is dropped.
    grps.joinpath('vanilla.dat').write_bytes(b'base')
    grps.joinpath('vanilla.usd').write_bytes(b'stale-base-differs')
    # A variant present as identical .dat + .usd -> the duplicate .usd is dropped.
    grps.joinpath('Dup.dat').write_bytes(b'same')
    grps.joinpath('Dup.usd').write_bytes(b'same')
    # A variant whose .usd differs from an existing .dat of the same stem -> kept.
    grps.joinpath('Keep.dat').write_bytes(b'one')
    grps.joinpath('Keep.usd').write_bytes(b'two')

    result = migrate_das_folder_extensions(files_dir)

    assert list(grps.glob('*.usd')) == []
    assert (grps / 'vanilla.dat').read_bytes() == b'base'        # original kept
    assert (grps / 'Dup.dat').read_bytes() == b'same'
    assert (grps / 'Keep.dat').read_bytes() == b'one'            # original kept
    assert (grps / 'Keep_1.dat').read_bytes() == b'two'          # distinct .usd preserved
    assert sorted(result['removed']) == ['Dup.usd', 'vanilla.usd']


def test_migrate_das_extensions_leaves_dat_only_folders_untouched(tmp_path):
    files_dir = tmp_path / 'files'
    grop = files_dir / 'GrOp'
    grop.mkdir(parents=True)
    grop.joinpath('vanilla.dat').write_bytes(b'a')
    grop.joinpath('AutumnDreamland.dat').write_bytes(b'b')

    result = migrate_das_folder_extensions(files_dir)

    assert result == {'renamed': [], 'removed': []}
    assert sorted(p.name for p in grop.glob('*.dat')) == ['AutumnDreamland.dat', 'vanilla.dat']


def test_migrate_stadium_stems_moves_normal_archive_and_sidecars(tmp_path):
    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    forms = grps / 'WatercolorStadium(X)'
    forms.mkdir(parents=True)
    grps.joinpath('WatercolorStadium(X).dat').write_bytes(b'normal')
    forms.joinpath('GrPs3.dat').write_bytes(b'water')

    result = migrate_stadium_variant_stems(files_dir)

    assert len(result['renamed']) == 1
    old_name, safe_name = result['renamed'][0]
    assert old_name == 'WatercolorStadium(X)'
    assert len(safe_name) == 17
    assert safe_name.endswith('(X)')
    assert grps.joinpath(f'{safe_name}.dat').read_bytes() == b'normal'
    assert grps.joinpath(safe_name, 'GrPs3.dat').read_bytes() == b'water'
    assert migrate_stadium_variant_stems(files_dir) == {'renamed': []}

def test_migrate_stadium_keeps_safe_lowercase_stems(tmp_path, monkeypatch):
    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    forms = grps / 'vanilla'
    forms.mkdir(parents=True)
    grps.joinpath('vanilla.dat').write_bytes(b'normal')
    forms.joinpath('GrPs1.dat').write_bytes(b'fire')

    # A regression must fail promptly, rather than hang the suite on Windows.
    real_name = stadium_runtime_variant_name
    probes = []

    def guarded_name(name, salt=''):
        probes.append(salt)
        assert len(probes) <= 10, 'case-only migration did not terminate'
        return real_name(name, salt)

    monkeypatch.setattr(das_engine, 'stadium_runtime_variant_name', guarded_name)
    assert migrate_stadium_variant_stems(files_dir) == {'renamed': []}
    assert migrate_stadium_variant_stems(files_dir) == {'renamed': []}
    assert sorted(p.name for p in grps.iterdir()) == ['vanilla', 'vanilla.dat']
    assert grps.joinpath('vanilla.dat').read_bytes() == b'normal'
    assert forms.joinpath('GrPs1.dat').read_bytes() == b'fire'


def test_migrate_stadium_preserves_short_name_and_sidecar_collisions(tmp_path):
    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    forms = grps / 'night-sky'
    forms.mkdir(parents=True)
    grps.joinpath('night-sky.dat').write_bytes(b'new normal')
    forms.joinpath('GrPs1.dat').write_bytes(b'new fire')
    grps.joinpath('NightSky.dat').write_bytes(b'existing normal')
    blocked_stem = stadium_runtime_variant_name('night-sky', salt='collision-1')
    blocked_forms = grps / blocked_stem
    blocked_forms.mkdir()
    blocked_forms.joinpath('GrPs1.dat').write_bytes(b'existing fire')

    result = migrate_stadium_variant_stems(files_dir)

    assert len(result['renamed']) == 1
    old_name, new_name = result['renamed'][0]
    assert old_name == 'night-sky'
    assert new_name not in ('NightSky', blocked_stem)
    assert len(new_name) <= 17
    assert grps.joinpath(f'{new_name}.dat').read_bytes() == b'new normal'
    assert grps.joinpath(new_name, 'GrPs1.dat').read_bytes() == b'new fire'
    assert grps.joinpath('NightSky.dat').read_bytes() == b'existing normal'
    assert blocked_forms.joinpath('GrPs1.dat').read_bytes() == b'existing fire'
    assert migrate_stadium_variant_stems(files_dir) == {'renamed': []}


def test_migrate_stadium_collision_exhaustion_preserves_original(tmp_path, monkeypatch):
    import pytest

    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    grps.mkdir(parents=True)
    source = grps / 'night-sky.dat'
    source.write_bytes(b'normal')
    real_name = stadium_runtime_variant_name
    probes = 0

    def guarded_name(name, salt=''):
        nonlocal probes
        probes += 1
        assert probes <= 1001, 'collision exhaustion did not terminate'
        return real_name(name, salt)

    with monkeypatch.context() as patch:
        patch.setattr(das_engine, 'stadium_runtime_variant_name', guarded_name)
        patch.setattr(Path, 'exists', lambda self: True)
        with pytest.raises(FileExistsError, match='Stadium variant'):
            migrate_stadium_variant_stems(files_dir)
    assert source.read_bytes() == b'normal'
    assert list(grps.iterdir()) == [source]


def test_migrate_stadium_rolls_back_archive_if_sidecar_move_fails(tmp_path, monkeypatch):
    import pytest

    files_dir = tmp_path / 'files'
    grps = files_dir / 'GrPs'
    forms = grps / 'night-sky'
    forms.mkdir(parents=True)
    source = grps / 'night-sky.dat'
    source.write_bytes(b'normal')
    forms.joinpath('GrPs1.dat').write_bytes(b'fire')
    real_rename = Path.rename

    def fail_sidecar(self, target):
        if self == forms:
            raise OSError('simulated sidecar failure')
        return real_rename(self, target)

    monkeypatch.setattr(Path, 'rename', fail_sidecar)
    with pytest.raises(OSError, match='simulated sidecar failure'):
        migrate_stadium_variant_stems(files_dir)
    assert source.read_bytes() == b'normal'
    assert forms.joinpath('GrPs1.dat').read_bytes() == b'fire'
    assert not grps.joinpath('NightSky.dat').exists()


def _stadium_import_client(tmp_path, monkeypatch):
    """Isolate the endpoint from the user's configured MEX project."""
    project_files = tmp_path / 'project' / 'files'
    project_files.mkdir(parents=True)
    monkeypatch.setattr(das_project_routes, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(das_project_routes, 'get_project_files_dir', lambda: project_files)
    monkeypatch.setattr(das_project_routes, 'load_metadata', lambda default=None: {})

    app = Flask(__name__)
    app.register_blueprint(das_bp)
    return app.test_client(), project_files


def _write_stage_zip(path, stage_data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('GrPs.dat', stage_data)


def test_archive_member_stage_code_guard():
    assert stage_code_from_archive_member(
        'stages/GrNLa-PEGASUS-ARENA.dat') == 'GrNLa'
    assert stage_code_from_archive_member('Battle City.dat') is None

    selected, conflicts = select_stage_archive_member(
        ['GrNLa-Pegasus.dat', 'GrPs-Battle-City.dat'], 'GrPs')
    assert selected == 'GrPs-Battle-City.dat'
    assert conflicts == []

    selected, conflicts = select_stage_archive_member(
        ['GrNLa-Pegasus.dat'], 'GrPs')
    assert selected is None
    assert conflicts == ['GrNLa']


def test_stadium_import_rejects_explicit_final_destination_archive(
        tmp_path, monkeypatch):
    archive = tmp_path / 'storage' / 'pegasus-arena.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as stage_zip:
        stage_zip.writestr('GrNLa-PEGASUS-ARENA.dat', b'not-a-stadium')
    client, project_files = _stadium_import_client(tmp_path, monkeypatch)

    response = client.post('/api/mex/das/import', json={
        'stageCode': 'GrPs',
        'variantPath': 'storage/pegasus-arena.zip',
    })

    assert response.status_code == 400
    result = response.get_json()
    assert result['reason'] == 'stage_code_mismatch'
    assert result['requestedStageCode'] == 'GrPs'
    assert result['detectedStageCode'] == 'GrNLa'
    assert 'Final Destination' in result['error']
    assert not (project_files / 'GrPs').exists()


def test_stadium_import_endpoint_applies_and_reports_transform_fix(
        tmp_path, monkeypatch):
    """The HTTP product path must write repaired bytes and return its report."""
    from tests.backend.test_stadium_transform_fix import build_variant
    from vault.importing.stadium_transform_fix import repair_stadium_variant

    raw, _ = build_variant(with_duplicate=True)
    expected, expected_report = repair_stadium_variant(raw)
    archive = tmp_path / 'storage' / 'sky-high.zip'
    _write_stage_zip(archive, raw)
    client, project_files = _stadium_import_client(tmp_path, monkeypatch)

    response = client.post('/api/mex/das/import', json={
        'stageCode': 'GrPs',
        'variantPath': 'storage/sky-high.zip',
    })

    assert response.status_code == 200
    result = response.get_json()
    assert result['success'] is True
    assert result['transformFix'] == expected_report
    assert result['transformFix']['status'] == 'repaired'
    assert len(result['transformFix']['actions']) == 1
    installed = project_files / 'GrPs' / 'SkyHigh.dat'
    assert installed.read_bytes() == expected
    assert archive.exists()  # the vault source was not mutated

    # The exact installed file is idempotently clean on a second repair pass.
    again, report = repair_stadium_variant(installed.read_bytes())
    assert again is None
    assert report['status'] == 'clean'


def test_stadium_import_endpoint_reports_clean_without_rewriting_geometry(
        tmp_path, monkeypatch):
    """Clean Stadium variants still return the UI contract and retain bytes."""
    from tests.backend.test_stadium_transform_fix import build_variant

    raw, _ = build_variant(with_duplicate=False)
    archive = tmp_path / 'storage' / 'texture-stadium.zip'
    _write_stage_zip(archive, raw)
    client, project_files = _stadium_import_client(tmp_path, monkeypatch)

    response = client.post('/api/mex/das/import', json={
        'stageCode': 'GrPs',
        'variantPath': 'storage/texture-stadium.zip',
    })

    assert response.status_code == 200
    result = response.get_json()
    assert result['transformFix']['status'] == 'clean'
    assert result['transformFix']['actions'] == []
    assert (project_files / 'GrPs' / 'TextureStadium.dat').read_bytes() == raw


def test_stadium_import_installs_complete_per_variant_transformations(
        tmp_path, monkeypatch):
    from tests.backend.test_stadium_transform_fix import build_variant

    raw, _ = build_variant(with_duplicate=False)
    archive = tmp_path / 'storage' / 'battle-city.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as stage_zip:
        stage_zip.writestr('Battle City.dat', raw)
        for index in range(1, 5):
            stage_zip.writestr(
                f'transformations/GrPs{index}.dat',
                f'battle-city-form-{index}'.encode())
    client, project_files = _stadium_import_client(tmp_path, monkeypatch)

    response = client.post('/api/mex/das/import', json={
        'stageCode': 'GrPs',
        'variantPath': 'storage/battle-city.zip',
    })

    assert response.status_code == 200
    result = response.get_json()
    assert result['transformationSkins']['status'] == 'installed'
    assert result['transformationSkins']['count'] == 4
    assert (project_files / 'GrPs' / 'BattleCity.dat').read_bytes() == raw
    sidecars = project_files / 'GrPs' / 'BattleCity'
    for index in range(1, 5):
        assert (sidecars / f'GrPs{index}.dat').read_bytes() == (
            f'battle-city-form-{index}'.encode())


def test_stadium_import_shortens_long_runtime_stem_with_sidecars(
        tmp_path, monkeypatch):
    from tests.backend.test_stadium_transform_fix import build_variant

    raw, _ = build_variant(with_duplicate=False)
    archive = tmp_path / 'storage' / 'watercolor-stadium-extra-long.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as stage_zip:
        stage_zip.writestr('GrPs.dat', raw)
        for index in range(1, 5):
            stage_zip.writestr(f'GrPs{index}.dat', f'form-{index}'.encode())
    client, project_files = _stadium_import_client(tmp_path, monkeypatch)

    response = client.post('/api/mex/das/import', json={
        'stageCode': 'GrPs',
        'variantPath': 'storage/watercolor-stadium-extra-long.zip',
    })

    assert response.status_code == 200
    safe_name = stadium_runtime_variant_name('watercolor-stadium-extra-long')
    assert len(safe_name) == 17
    assert (project_files / 'GrPs' / f'{safe_name}.dat').read_bytes() == raw
    for index in range(1, 5):
        assert (project_files / 'GrPs' / safe_name / f'GrPs{index}.dat').read_bytes() == (
            f'form-{index}'.encode())


def test_stadium_import_rejects_partial_transformation_set_without_writing(
        tmp_path, monkeypatch):
    archive = tmp_path / 'storage' / 'battle-city.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as stage_zip:
        stage_zip.writestr('Battle City.dat', b'stage')
        stage_zip.writestr('GrPs1.dat', b'fire')
        stage_zip.writestr('GrPs3.dat', b'water')
    client, project_files = _stadium_import_client(tmp_path, monkeypatch)

    response = client.post('/api/mex/das/import', json={
        'stageCode': 'GrPs',
        'variantPath': 'storage/battle-city.zip',
    })

    assert response.status_code == 400
    result = response.get_json()
    assert result['reason'] == 'incomplete_stadium_transformations'
    assert result['missing'] == ['GrPs2.dat', 'GrPs4.dat']
    assert not (project_files / 'GrPs').exists()
