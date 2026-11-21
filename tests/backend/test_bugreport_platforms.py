"""Bug reports must be fileable from every platform we ship.

Every report that has ever reached the Discord channel came from Windows.
Nothing was found to be broken on macOS or Linux -- the worker accepts all
three (its CHANNELS is {windows, mac, linux}, verified against production
2026-09-13) and the data root is per-platform -- but nothing pinned it either,
so a regression on the two platforms nobody files from would be silent.
"""
from tests.paths import BACKEND
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = BACKEND
sys.path.insert(0, str(BACKEND_DIR))

from shared.diagnostics import bug_report  # noqa: E402
from core.config import bugreport_channel  # noqa: E402


# The set the worker validates against; anything else loses the report.
WORKER_CHANNELS = {'windows', 'mac', 'linux'}


@pytest.mark.parametrize('platform,expected', [
    ('win32', 'windows'),
    ('darwin', 'mac'),
    ('linux', 'linux'),
    ('linux2', 'linux'),
    ('freebsd13', 'linux'),   # anything unix-ish reports as linux, not as itself
])
def test_channel_is_one_the_worker_accepts(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, 'platform', platform)
    channel = bugreport_channel()
    assert channel == expected
    assert channel in WORKER_CHANNELS


def test_the_log_zip_builds_on_this_platform():
    """The other half that varies per OS: zipping a per-platform data root."""
    buf, _added, _slippi, _truncated = bug_report._build_logs_zip(
        extra_files={'report.json': '{"probe": true}'}, budget_bytes=1 << 20)
    with zipfile.ZipFile(buf) as zf:
        assert zf.testzip() is None, 'log zip is corrupt'
        assert 'report.json' in zf.namelist()
        assert zf.read('report.json') == b'{"probe": true}'
