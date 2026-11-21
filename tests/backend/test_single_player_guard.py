"""
Runs the C# single-player guard checks (tools/ingame/single-player-guard) against the
mexLib.dll of the dev MexCLI build.

The guards live in mexLib (SinglePlayerGuard / MexFighter.ToMxDt): they repair
a blank ViWait symbol (Adventure Brinstar crash) and point a fighter's ending
movie / congratulations images at files that exist (post-credits crash). They
are pure helpers, so the checks need no project or ISO.

Skipped when dotnet or the MexCLI Release build (mexLib.dll beside mexcli) is
missing.
"""
from tests.paths import BACKEND
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.config import MEXCLI_PATH  # noqa: E402

NUCLEUS_DIR = BACKEND_DIR.parent
PROJECT = NUCLEUS_DIR.parent / "tools" / "ingame" / "single-player-guard" / "SinglePlayerGuardSmoke.csproj"
MEX_BIN = Path(MEXCLI_PATH).parent
DOTNET = shutil.which("dotnet")

pytestmark = [pytest.mark.skipif(
    DOTNET is None or not (MEX_BIN / "mexLib.dll").exists() or not (MEX_BIN / "HSDRaw.dll").exists(),
    reason="dotnet or the MexCLI Release build (mexLib.dll) not present"), pytest.mark.slow]


def test_single_player_guard_checks(tmp_path):
    build = subprocess.run(
        [DOTNET, "build", str(PROJECT), "-c", "Release",
         "--artifacts-path", str(tmp_path),
         f"-p:MexBin={MEX_BIN}", "-p:NuGetAudit=false", "--verbosity", "quiet"],
        capture_output=True, text=True, timeout=600)
    assert build.returncode == 0, build.stdout[-2000:] + build.stderr[-2000:]

    dll = tmp_path / "bin" / "SinglePlayerGuardSmoke" / "release" / "SinglePlayerGuardSmoke.dll"
    run = subprocess.run([DOTNET, str(dll)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "FAIL" not in run.stdout
