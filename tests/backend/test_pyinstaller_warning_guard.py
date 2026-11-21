from tests.paths import APP
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


SCRIPT = APP.parent / 'tools' / 'build' / "check_pyinstaller_warnings.py"
SPEC = spec_from_file_location("check_pyinstaller_warnings", SCRIPT)
guard = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(guard)


def test_ignores_third_party_optional_imports():
    lines = [
        "missing module named trio - imported by httpx._client (optional)",
        "missing module named pwd - imported by pathlib (optional)",
    ]
    assert guard.unexpected_project_missing(lines) == []


def test_allows_documented_loose_runtime_module():
    lines = [
        "missing module named generate_csp - imported by shared.rendering.portrait (top-level)",
    ]
    assert guard.unexpected_project_missing(lines) == []


def test_flags_new_project_dependency():
    line = "missing module named new_codec - imported by projects.routes.export (top-level)"
    assert guard.unexpected_project_missing([line]) == [("new_codec", line)]


def test_flags_absolute_backend_importer():
    line = (
        "missing module named new_codec - imported by "
        r"C:\repo\nucleus\backend\app.py (top-level)"
    )
    assert guard.unexpected_project_missing([line]) == [("new_codec", line)]


@pytest.mark.parametrize(
    "importer",
    ["app", "mexcli.project", "mexcli.commands", *sorted(guard.LOOSE_RUNTIME_MODULES)],
)
def test_flags_dependencies_missing_from_top_level_project_importers(importer):
    line = f"missing module named new_codec - imported by {importer} (top-level)"
    assert guard.unexpected_project_missing([line]) == [("new_codec", line)]


def test_still_ignores_same_missing_dependency_from_third_party():
    line = "missing module named new_codec - imported by scipy._lib (optional)"
    assert guard.unexpected_project_missing([line]) == []


# ----------------------------------------------------------- the model import studio

def test_flags_a_dependency_missing_from_the_studio():
    line = "missing module named new_codec - imported by randall.model_import.studio.stages (delayed)"
    assert guard.unexpected_project_missing([line]) == [("new_codec", line)]


def test_flags_a_deleted_project_module_the_studio_still_imports():
    """The Switch deletes old modellab modules: a lazy import left behind must fail the build."""
    line = "missing module named shared.modellab.fit_story - imported by randall.model_import.studio.look (delayed)"
    assert guard.unexpected_project_missing([line]) == [("shared.modellab.fit_story", line)]


def test_flags_a_deleted_studio_module_under_its_nested_package():
    line = "missing module named randall.model_import.studio.gone - imported by randall.model_import.studio.look (delayed)"
    assert guard.unexpected_project_missing([line]) == [("randall.model_import.studio.gone", line)]


def test_flags_a_dependency_missing_from_the_coach():
    line = "missing module named new_codec - imported by randall.coach.coach_api (delayed)"
    assert guard.unexpected_project_missing([line]) == [("new_codec", line)]


def test_a_function_imported_from_a_present_package_is_not_a_missing_module():
    # measured in a real analysis: `from scipy.optimize import minimize` in studio/lineup.py
    line = ("missing module named scipy.optimize.minimize - imported by scipy.optimize (delayed), "
            "randall.model_import.studio.lineup (delayed)")
    assert guard.unexpected_project_missing([line]) == []
    # ...but not when the package it comes from is itself missing
    absent = "missing module named cv3 - imported by randall.model_import.studio.lineup (delayed)"
    assert [name for name, _ in guard.unexpected_project_missing([line.replace('scipy.optimize', 'cv3'), absent])]         == ["cv3.minimize", "cv3"]


def test_windows_capture_is_optional():
    """Only the developer's WGC capture switch (NUCLEUS_DOLPHIN_CAPTURE=wgc) imports it; the installer does not
    carry it."""
    line = "missing module named windows_capture - imported by shared.ingame.screenshot_wgc (delayed)"
    for platform in ("win32", "linux"):
        assert guard.unexpected_project_missing([line], platform=platform) == []
