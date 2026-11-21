"""The MexCLI-side contract the backend's export reader depends on.

`mexcli.project.MexManager.export_iso` reads MexCLI's stdout one line at a time, so a result
MexCLI does not put on one line is a result the app cannot read. In 0.8.7 that
turned "the ISO is locked by another process" into a dialog full of [DEBUG]
portrait-compression lines.

This is the fast half of `tools/build/export_smoke.py`; the slow half (an
actual ISO export) runs as a release gate in `ci.py`, which cannot skip it.
"""
from tests.paths import APP
import sys
from pathlib import Path

import pytest

BUILD_DIR = APP.parent / 'tools' / 'build'
sys.path.insert(0, str(BUILD_DIR))


@pytest.fixture(scope='module')
def smoke():
    module = pytest.importorskip('export_smoke')
    try:
        module.mexcli_path()
    except module.SmokeFailure as exc:
        pytest.skip(str(exc))
    return module


def test_a_failed_export_reports_on_one_line(smoke):
    error = smoke.check_error_is_one_line()
    assert error and '[DEBUG]' not in error


def test_result_line_ignores_pretty_printed_json(smoke):
    """The reader must not claim to have found a result it cannot parse."""
    indented = '{\n  "success": false,\n  "error": "boom"\n}'
    assert smoke.result_line(indented) is None
    assert smoke.result_line('{"success": false, "error": "boom"}')['error'] == 'boom'


def test_result_line_skips_progress_and_takes_the_result(smoke):
    stdout = ('{"status":"progress","percentage":50,"message":"Writing..."}\n'
              '{"status":"completed","success":true,"outputPath":"out.iso"}\n')
    assert smoke.result_line(stdout)['outputPath'] == 'out.iso'
