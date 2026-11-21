"""Focused tests for the frozen backend build-smoke entry point."""

from tests.paths import BACKEND
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

pytestmark = pytest.mark.slow


NUCLEUS = BACKEND.parent
APP_PY = BACKEND / "app.py"


def _pythonpath(*entries):
    existing = os.environ.get("PYTHONPATH", "")
    return os.pathsep.join([*(str(entry) for entry in entries), existing])


def test_frozen_build_smoke_imports_tools_before_flask(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    (blocker / "flask.py").write_text(
        "raise RuntimeError('build smoke reached Flask')\n",
        encoding="utf-8",
    )
    smoke_root = tmp_path / "smoke-profile"
    # Deliberately NOT frozen. The strict "every import resolved inside
    # sys._MEIPASS" rule only means anything against a real bundle, and all
    # three build scripts run exactly that against the packaged binary
    # (build.bat:116, build-linux.sh:105, build-macos.sh:85). Simulating it
    # here required the DEV interpreter's site-packages to sit under a fake
    # bundle root -- true only by accident on Windows, where the venv lives
    # inside app/, and false on every other machine. What this test is
    # actually for is the import ORDER: tools before Flask.
    wrapper = "\n".join((
        "import runpy, sys",
        f"sys._MEIPASS = {str(NUCLEUS)!r}",
        f"sys.executable = {str(NUCLEUS / 'backend' / 'mex_backend.exe')!r}",
        f"sys.argv = [{str(APP_PY)!r}, '--build-smoke-test']",
        f"runpy.run_path({str(APP_PY)!r}, run_name='__main__')",
    ))
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath(
        blocker,
        BACKEND,
    )
    env["NUCLEUS_BUILD_SMOKE_ROOT"] = str(smoke_root)

    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Build smoke test passed: numpy, core.config" in result.stdout
    assert "Native runtime: Python" in result.stdout
    assert "NumPy" in result.stdout
    assert "7z runtime: py7zr" in result.stdout
    assert "py7zr" in result.stdout.split("Build smoke test passed: ", 1)[1]
    for module_name in (
        "generate_csp",
        "detect_character",
        "costume_validator",
        "bone_tables",
        "dat_processor",
        "falcon_neutralize",
    ):
        assert module_name in result.stdout
    # the model import's app side: the chat job and the vault save
    assert "Model import: import_model and the vault save" in result.stdout, result.stdout
    for module_name in ("randall.model_import.chat.studio_import", "randall.model_import.chat.import_job",
                        "randall.model_import.studio.finish"):
        assert module_name in result.stdout
    assert "windows_capture" not in result.stdout, "the installer no longer carries it"
    assert "build smoke reached Flask" not in result.stderr


def test_numpy_dll_failure_stops_build_smoke_before_backend_startup(tmp_path):
    (tmp_path / "numpy.py").write_text(
        "raise ImportError('DLL load failed while importing _multiarray_umath')\n",
        encoding="utf-8",
    )
    (tmp_path / "flask.py").write_text(
        "raise RuntimeError('build smoke reached Flask')\n", encoding="utf-8",
    )
    # backend/ is importable, as it is in the bundle (the smoke routine is
    # core/build_smoke.py); the broken numpy and the Flask blocker come first.
    wrapper = "\n".join((
        "import runpy, sys",
        f"sys.path.insert(0, {str(BACKEND)!r})",
        f"sys.path.insert(0, {str(tmp_path)!r})",
        f"sys.argv = [{str(APP_PY)!r}, '--build-smoke-test']",
        f"runpy.run_path({str(APP_PY)!r}, run_name='__main__')",
    ))
    result = subprocess.run(
        [sys.executable, "-c", wrapper], cwd=tmp_path,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "Build smoke test failed: DLL load failed" in result.stderr
    assert "build smoke reached Flask" not in result.stderr
    assert "Build smoke test passed" not in result.stdout


def test_frozen_config_uses_build_smoke_root(tmp_path):
    smoke_root = tmp_path / "isolated-profile"
    local_app_data = tmp_path / "must-not-be-used"
    script = "\n".join((
        "import json, sys",
        "from pathlib import Path",
        "sys.frozen = True",
        f"sys._MEIPASS = {str(NUCLEUS)!r}",
        f"sys.executable = {str(NUCLEUS / 'backend' / 'mex_backend.exe')!r}",
        "sys.argv.append('--build-smoke-test')",
        "import core.config as config",
        "print(json.dumps({",
        "    'project_root': str(config.PROJECT_ROOT),",
        "    'storage_path': str(config.STORAGE_PATH),",
        "    'logs_path': str(config.LOGS_PATH),",
        "}))",
    ))
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath(
        BACKEND,
    )
    env["NUCLEUS_BUILD_SMOKE_ROOT"] = str(smoke_root)
    env["LOCALAPPDATA"] = str(local_app_data)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    paths = json.loads(result.stdout.strip().splitlines()[-1])

    assert Path(paths["project_root"]) == smoke_root.resolve()
    assert Path(paths["storage_path"]) == smoke_root / "storage"
    assert Path(paths["logs_path"]) == smoke_root / "logs"
    assert not local_app_data.exists()


def test_frozen_config_ignores_build_smoke_root_without_flag(tmp_path):
    smoke_root = tmp_path / "must-not-be-used"
    local_app_data = tmp_path / "local-app-data"
    script = "\n".join((
        "import json, sys",
        "sys.frozen = True",
        f"sys._MEIPASS = {str(NUCLEUS)!r}",
        f"sys.executable = {str(NUCLEUS / 'backend' / 'mex_backend.exe')!r}",
        "import core.config as config",
        "print(json.dumps({'project_root': str(config.PROJECT_ROOT)}))",
    ))
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath(BACKEND)
    env["NUCLEUS_BUILD_SMOKE_ROOT"] = str(smoke_root)
    env["LOCALAPPDATA"] = str(local_app_data)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    paths = json.loads(result.stdout.strip().splitlines()[-1])

    # core/config.py picks a per-OS user-data dir when frozen: LOCALAPPDATA on
    # Windows, ~/Library/Application Support on macOS, ~/.melee-nexus on Linux.
    if sys.platform == "win32":
        expected_root = local_app_data / "SSBM Nucleus"
    elif sys.platform == "darwin":
        expected_root = Path.home() / "Library" / "Application Support" / "SSBM Nucleus"
    else:
        expected_root = Path.home() / ".melee-nexus"
    assert Path(paths["project_root"]) == expected_root
    assert not smoke_root.exists()
