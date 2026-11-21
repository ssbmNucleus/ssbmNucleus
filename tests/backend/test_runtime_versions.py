"""Prevent a release from silently reverting to a known vulnerable runtime."""
import pytest
from core.runtime_versions import check_electron, check_unix_python, check_windows_python


@pytest.mark.parametrize("version", [(3, 12, 4), (3, 13, 16), (3, 14, 9)])
def test_windows_requires_patched_validated_python_series(version):
    with pytest.raises(RuntimeError, match="3.13.17"):
        check_windows_python(version, "win32")


@pytest.mark.parametrize("version", [(3, 13, 17), (3, 13, 18)])
def test_patched_python_accepted(version):
    check_windows_python(version, "win32")


def test_windows_floor_does_not_change_other_platform_policy():
    check_windows_python((3, 12, 15), "darwin")
    check_windows_python((3, 12, 3), "linux")


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("version", [(3, 12, 3), (3, 12, 14), (3, 13, 15), (3, 11, 14), (3, 14, 9)])
def test_unix_requires_patched_python(version, platform):
    with pytest.raises(RuntimeError, match="3.12.15"):
        check_unix_python(version, platform)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("version", [(3, 12, 15), (3, 12, 16), (3, 13, 17)])
def test_unix_patched_python_accepted(version, platform):
    check_unix_python(version, platform)


def test_unix_floor_does_not_change_windows_policy():
    check_unix_python((3, 12, 4), "win32")


@pytest.mark.parametrize("version", ["44.0.0", "44.9.3", "44.10.2", "44.11.4", "43.9.9", "45.0.0", "44.11.5-beta.1"])
def test_old_or_unvalidated_electron_rejected(version):
    with pytest.raises(RuntimeError):
        check_electron(version)


@pytest.mark.parametrize("version", ["44.11.5", "44.12.0"])
def test_patched_electron_accepted(version):
    check_electron(version)
