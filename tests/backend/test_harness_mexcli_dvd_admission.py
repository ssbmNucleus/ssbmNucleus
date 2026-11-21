from tests.paths import REPO
import json
import sys
from pathlib import Path

sys.path.insert(0, str(REPO / "tools" / "harness"))

import harness_mcp  # noqa: E402
from core import iso_reads


def test_relative_export_output_is_admitted_from_mexcli_working_directory(tmp_path, monkeypatch):
    cli = tmp_path / 'mexcli.exe'
    cli.write_bytes(b'cli')
    output = tmp_path / 'exports' / 'candidate.iso'
    output.parent.mkdir()
    output.write_bytes(b'iso')
    calls = {}

    def run(command, log, **kwargs):
        calls['command'] = command
        calls['cwd'] = kwargs['cwd']
        return 0, [json.dumps({'success': True,
                               'outputPath': 'exports/candidate.iso'})]

    def admit(path):
        calls['admitted'] = path
        return {'status': 'PASS_ROUNDED_DVD_READS'}

    monkeypatch.setattr(harness_mcp, 'MEXCLI_PATH', cli)
    monkeypatch.setattr(harness_mcp, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(harness_mcp, '_run_cli', run)
    monkeypatch.setattr(iso_reads, 'ensure_padding', admit)

    result = harness_mcp.t_mexcli(
        {'args': ['export', 'project.mexproj', 'exports/candidate.iso']},
        lambda _message: None)

    assert calls['cwd'] == tmp_path
    assert calls['admitted'] == output
    assert result['dvd_read_admission']['status'] == 'PASS_ROUNDED_DVD_READS'
