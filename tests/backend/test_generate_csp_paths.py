"""
Regression test for HSDRawViewer path resolution in generate_csp.

In a packaged build HSDRawViewer ships via electron-builder extraResources to
<install>/resources/utility/HSDRawViewer — NOT inside the PyInstaller bundle.
generate_csp must resolve it from the exe location, not relative to its own
(_MEIPASS) path, or every CSP render fails (the "230 preview failures" bug).
"""
from tests.paths import BACKEND
import sys
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
PROCESSOR_DIR = BACKEND_DIR.parent / 'utility' / 'tools' / 'processor'
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROCESSOR_DIR))

generate_csp = pytest.importorskip('generate_csp')


def test_frozen_resolves_to_resources_not_meipass(monkeypatch, tmp_path):
    # Simulate the packaged layout: resources/backend/mex_backend.exe.
    # Deliberately NOT patching os.name: `generate_csp.os` IS the shared os
    # module, so setting .name='nt' leaks process-wide and makes pathlib hand
    # back a WindowsPath, which cannot be instantiated on Linux. The function
    # under test never reads os.name anyway.
    exe = tmp_path / 'resources' / 'backend' / 'mex_backend.exe'
    exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))

    resolved = Path(generate_csp._resolve_hsdraw_dir())
    # -> resources/utility/HSDRawViewer  (sibling of backend/, under resources/)
    assert resolved == tmp_path / 'resources' / 'utility' / 'HSDRawViewer'
    # must NOT be relative to the bundled script dir
    assert 'tools' not in resolved.parts


@pytest.mark.parametrize('platform, relative', [
    ('nt', 'win-x64/HSDRawViewer.exe'),
    ('posix', 'linux-x64/hsdrawviewer'),
    ('darwin', 'osx-arm64/hsdrawviewer'),
])
def test_dev_uses_the_fetched_prebuilt_renderer(monkeypatch, tmp_path, platform, relative):
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(generate_csp, 'HSDRAW_DEV_DIR', tmp_path / 'hsdraw')
    expected = tmp_path / 'hsdraw' / relative
    assert Path(generate_csp._resolve_hsdraw_exe(platform)) == expected
    if platform == 'nt':
        assert Path(generate_csp._resolve_hsdraw_dir()) == expected.parent


def test_frozen_linux_resolves_native_renderer(monkeypatch, tmp_path):
    exe = tmp_path / 'resources' / 'backend' / 'mex_backend'
    renderer = tmp_path / 'resources' / 'utility' / 'hsdraw-linux' / 'hsdrawviewer'
    renderer.parent.mkdir(parents=True)
    renderer.touch()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))

    assert Path(generate_csp._resolve_hsdraw_exe('posix')) == renderer


def test_native_linux_renderer_does_not_use_wine(monkeypatch):
    monkeypatch.setattr(generate_csp, 'HSDRAW_EXE', '/app/hsdrawviewer')

    assert generate_csp._renderer_command('posix') == ['/app/hsdrawviewer']


def test_windows_renderer_on_linux_keeps_wine_fallback(monkeypatch):
    monkeypatch.setattr(generate_csp, 'HSDRAW_EXE', '/mnt/c/tools/HSDRawViewer.exe')

    assert generate_csp._renderer_command('posix') == [
        'wine',
        r'C:\tools\HSDRawViewer.exe',
    ]
