"""Release packaging must exercise the staged audio helper on every platform."""
from tests.paths import APP
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

BUILD = APP.parent / 'tools' / 'build'
sys.path.insert(0, str(BUILD))
import music_tools_smoke as smoke
import ship_guard


@pytest.mark.parametrize('stdout,code', [
    ('MexCLI help: unknown command', 1),
    (json.dumps({'success': False, 'error': 'unknown command'}), 1),
    (json.dumps({'success': True}), 1),
    ('[]', 0),
])
def test_old_or_failed_helper_blocks_packaging(tmp_path, monkeypatch, stdout, code):
    cli = tmp_path / 'mexcli.exe'
    cli.write_bytes(b'placeholder')
    monkeypatch.setattr(smoke.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, code, stdout, ''))
    with pytest.raises(smoke.MusicToolsError):
        smoke.verify_music_tools(cli, scratch=tmp_path)
    assert list(tmp_path.iterdir()) == [cli], 'smoke audio must not reach the package'


@pytest.mark.parametrize('platform,relative', [
    ('win', 'dist-backend/mex/mexcli.exe'),
    ('linux', 'dist-backend/mex-linux/mexcli'),
    ('mac', 'dist-backend/mex-mac/mexcli'),
])
def test_gate_uses_staged_helper_even_with_inventory_verification_disabled(tmp_path, monkeypatch, platform, relative):
    stage = tmp_path / 'package-stage'
    monkeypatch.setattr(ship_guard, 'load_rules', lambda: {
        'stage_marker': '.nucleus-package-stage', 'stage': {},
    })
    monkeypatch.setattr(ship_guard, '_install_production_dependencies', lambda *a: 0)
    monkeypatch.setattr(ship_guard, '_scrub', lambda *a: 0)
    calls = []

    def failed(executable, scratch):
        calls.append((executable, scratch))
        raise smoke.MusicToolsError('hps-loop-info unsupported')

    monkeypatch.setattr(smoke, 'verify_music_tools', failed)
    args = SimpleNamespace(project_root=tmp_path, stage=stage, platform=platform,
                           keep=False, rehearse=False, no_verify=True)
    assert ship_guard.cmd_stage(args) == 1
    assert calls == [(stage / relative, stage)]


def test_all_release_builders_fetch_mexcli_before_staging():
    for filename, platform in [('build.bat', 'win'), ('build-linux.sh', 'linux'), ('build-macos.sh', 'mac')]:
        source = (BUILD / filename).read_text(encoding='utf-8')
        assert source.index('fetch_native.py') < source.index(f'stage --platform {platform}')
        package = 'call "%PROJECT_ROOT%\\node_modules\\.bin\\electron-builder.cmd"' if platform == 'win' else './node_modules/.bin/electron-builder --'
        assert source.index(f'stage --platform {platform}') < source.index(package)
