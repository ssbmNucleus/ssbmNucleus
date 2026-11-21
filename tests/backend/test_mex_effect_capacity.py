"""Real pinned MexCLI effect-slot and roster-map boundaries, without game assets.

Fetch the pinned tool first, or point MEX_CAPACITY_TEST_DIR at its DLL folder.
This intentionally does not test a supposed universal 64-character limit.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.paths import APP


@pytest.mark.slow
def test_shipped_effect_allocator_preserves_shared_effects_and_refuses_overflow(tmp_path):
    native = Path(os.environ.get('MEX_CAPACITY_TEST_DIR', APP / 'utility/mex/win-x64'))
    required = ('mexLib.dll', 'HSDRaw.dll', 'GCILib.dll')
    if not all((native / name).is_file() for name in required):
        pytest.skip('Fetch complete pinned MexCLI or set MEX_CAPACITY_TEST_DIR')
    dotnet = shutil.which('dotnet')
    if not dotnet:
        pytest.skip('Native capacity regression requires the .NET 8 SDK')
    harness = tmp_path / 'harness'
    shutil.copytree(Path(__file__).with_name('mex_capacity'), harness)
    build = subprocess.run(
        [dotnet, 'build', str(harness / 'CapacityChecks.csproj'),
         '-c', 'Release', f'-p:MexDir={native.resolve()}', '-p:NuGetAudit=false',
         '--nologo', '--verbosity', 'quiet'],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run(
        [dotnet, str(harness / 'bin/Release/net8.0/CapacityChecks.dll'), str(tmp_path / 'workspace')],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report['success'] and report['slots'] == 64
    assert report['usable'] == 63 and report['reserved'] == 30
    assert report['sharedReferences'] == 100
    assert report['rosterRoundTrips'] == [63, 64, 65, 72]
