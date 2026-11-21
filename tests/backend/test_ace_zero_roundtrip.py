"""Opt-in ACE 2.0 Zero import regression, without redistributing game assets.

Set NUCLEUS_ZERO_SOURCE_PROJECT to a project extracted from the verified ACE
v2.0.0 patch and NUCLEUS_ZERO_VANILLA_PROJECT to a clean, unmodified m-ex base.
Both are read-only inputs; the target is a full copy under pytest's temp root.

This checks the native export/package/install/save boundary. The separate
grounded/aerial up-special gameplay investigation is recorded in CUSTOM_CONTENT.
Passing this test alone does not establish gameplay or resolve a crash report.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

import pytest

from core.config import MEXCLI_PATH
from mexcli import commands
from vault.importing.custom_character_scan import _bake_clone_patch


ZERO_ASSETS = {
    'PlZx.dat': '09e485b94334c24fd53a37d3999d2e453a3bd4c2dfae0219892a10872df80f95',
    'PlZxAJ.dat': 'b39e7f9814cbc31b3efba1483f8688540091f942fd0893a22dcec4d6f8c4a586',
    'EfZxData.dat': '0a9cc0e01b59f6ca1378018b0ef24c970bec81e4cb47648e0b8d78c1b8813a24',
    'PlZxNr.dat': 'd1f3033a3ab013f45b6799208910573988209db6b2f4c3faaa901f802504b2bd',
}


def _input_project(variable):
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f'{variable} is required for the local ACE 2.0 fixture')
    path = Path(value).resolve()
    assert (path / 'project.mexproj').is_file(), f'Invalid {variable}: {path}'
    return path


def _run(*args):
    result = commands.run(args, check=False, timeout=600)
    output = commands.parse_json(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.get('success'), output
    return output


def _fighters(project):
    manifest = json.loads((project / 'project.mexproj').read_text(encoding='utf-8'))
    return [json.loads((project / 'data/fighters' / name).read_text(encoding='utf-8'))
            for name in manifest['fighterSaveMap']['filePaths']]


def _asset_bytes(package, name):
    if name == 'PlZxNr.dat':
        import io
        with zipfile.ZipFile(io.BytesIO(package.read('PlZxNr.zip'))) as costume:
            return costume.read(name)
    return package.read(name)


@pytest.mark.slow
def test_ace2_zero_native_roundtrip_preserves_move_dependencies(tmp_path):
    source = _input_project('NUCLEUS_ZERO_SOURCE_PROJECT')
    base = _input_project('NUCLEUS_ZERO_VANILLA_PROJECT')
    if not Path(MEXCLI_PATH).is_file():
        pytest.skip('Pinned MexCLI is unavailable')
    source_fighters = _fighters(source)
    source_id = next(i for i, fighter in enumerate(source_fighters)
                     if fighter.get('name') == 'Zero')
    assert source_id == 51, 'The fixture must be the ACE 2.0 release roster'
    zero = source_fighters[source_id]
    for name, expected in ZERO_ASSETS.items():
        assert hashlib.sha256((source / 'files' / name).read_bytes()).hexdigest() == expected
    base_fighters = _fighters(base)
    assert len(base_fighters) == 33 and not any(f.get('name') == 'Zero' for f in base_fighters)

    char_dir = tmp_path / 'vault-zero'
    char_dir.mkdir()
    package_path = char_dir / 'fighter.zip'
    _run('export-fighter', source / 'project.mexproj', source_id, package_path)
    with zipfile.ZipFile(package_path) as package:
        before = {name: package.read(name) for name in package.namelist()}
        for name, expected in ZERO_ASSETS.items():
            assert hashlib.sha256(_asset_bytes(package, name)).hexdigest() == expected
    assert _bake_clone_patch(char_dir, zero)
    assert not _bake_clone_patch(char_dir, zero), 'Repeated scanning must be idempotent'
    with zipfile.ZipFile(package_path) as package:
        assert set(package.namelist()) - set(before) == {'patches/clone_engine_items.dat'}
        assert all(package.read(name) == raw for name, raw in before.items())
        # The existing bounded item patch must not regress into global effect
        # routing, which breaks Kirby's copied specials in unrelated fighters.
        from core.clone_patch import _roots
        import struct
        patch = package.read('patches/clone_engine_items.dat')
        *_, roots = _roots(patch)
        body = patch[32:]
        table, count = struct.unpack_from('>II', body, roots[0][0] + 12)
        hooks = tuple(struct.unpack_from('>I', body, table + i * 8)[0] for i in range(count))
        assert hooks == (0x40267AF0, 0x800E0F58, 0x400EA30C, 0x400EA3BC)

    target = tmp_path / 'minimal-target'
    shutil.copytree(base, target)
    installed = _run('add-fighter', target / 'project.mexproj', package_path)
    target_id = installed['internalId']
    assert target_id == 27 and target_id != source_id
    _run('save', target / 'project.mexproj')
    _run('open', target / 'project.mexproj')
    installed_zero = _fighters(target)[target_id]
    for key in ('functions', 'moveLogic', 'items', 'boneDefinitions', 'files'):
        assert installed_zero[key] == zero[key], key
    for name, expected in ZERO_ASSETS.items():
        assert hashlib.sha256((target / 'files' / name).read_bytes()).hexdigest() == expected
    reopened = tmp_path / 'reopened-zero.zip'
    _run('export-fighter', target / 'project.mexproj', target_id, reopened)
    with zipfile.ZipFile(reopened) as package:
        for name, expected in ZERO_ASSETS.items():
            assert hashlib.sha256(_asset_bytes(package, name)).hexdigest() == expected
