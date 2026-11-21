"""Everything the installer CLAIMS to ship must actually import, alone.

The build smoke test in `core/build_smoke.py` imports six modules. The review
(`backend/artifacts/harness-experiment-20260922/ASTRA-INTEGRATION.md`) found
that it covers none of the surfaces the 0.9.0 preview opens: the task store,
part identity, the release gate, the in-game verifier, and the scripting facade
— which has **no production import path at all**, so nothing but the spec's
`hiddenimports` puts it in the executable.

An import that only works because the developer's checkout is on `sys.path`,
or because `conftest.py` arranged something, is exactly the import that fails
on the second PC. So this runs in a SUBPROCESS whose path is the frozen layout
as closely as a source tree allows:

  * `-I` — isolated: no `PYTHONPATH`, no user site-packages, no script dir
  * `sys.path` reset to `[backend, *stdlib/site-packages]`, nothing else
  * cwd is a scratch directory, not `backend/`, so a module that reads a
    relative path is not rescued by the working directory

It cannot reproduce `sys._MEIPASS`, the archive importer or the absence of
source files; what it does reproduce is the part that broke every time — a
module named in the spec that nothing can import.
"""
from tests.paths import BACKEND
import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

NUCLEUS = BACKEND.parent
SPEC = NUCLEUS.parent / 'tools' / 'build' / "mex_backend.spec"

#: Packages that reach a user's machine inside `mex_backend`. Used by the
#: static checks below; the import check names its modules explicitly.
SHIPPED_PACKAGES = ("randall/assistant", "shared/ingame", "shared/modellab", "shared/rendering", "nucleus_api",
                    "core", "vault/routes", "projects/routes", "upload/routes", "shared/routes", "randall/routes",
                    "tracker", "randall/coach", "shared/aiengine", "shared/vanilla_extract", "randall/model_import",
                    "file_retry", "mexcli", "vault/menus", "vault/extras", "vault/importing", "vault/catalog",
                    "projects/install", "randall/recolor", "randall/website", "randall/delivery", "randall/reports")


# --------------------------------------------------------------------------
# what must import
# --------------------------------------------------------------------------

def _package_modules(package: str, *, private: bool = False) -> list[str]:
    folder = BACKEND.joinpath(*package.split("."))
    assert (folder / "__init__.py").is_file(), f"{package} is not a package"
    out = [package]
    for path in sorted(folder.glob("*.py")):
        if path.stem == "__init__":
            continue
        if not private and path.stem.startswith("_"):
            continue
        out.append(f"{package}.{path.stem}")
    # A module split into a package by purpose (2026-10-03) is still one of this package's
    # modules: it and every module in it must import.
    for path in sorted(folder.glob("*/__init__.py")):
        if private or not path.parent.name.startswith("_"):
            out.extend(_package_modules(f"{package}.{path.parent.name}", private=private))
    return out


def _required_modules() -> list[str]:
    modules = [
        # the review's list, in its order (the wishes it covered inside tasks/ moved to randall/reports/)
        *_package_modules("randall.assistant.tasks"),
        *_package_modules("randall.reports"),
        "shared.rendering.part_identity",
        "shared.ingame.verify_costume",
        # every public module of the facade — `_workspace` is private but is
        # what the public ones stand on, so it is included deliberately.
        *_package_modules("nucleus_api", private=True),
        "core.safe_extract",
        "core.build_transaction",
        # the retried atomic swap every vault/build write goes through
        "file_retry",
        # the preview policy itself: if this cannot import, the packaged build
        # has no gate table and every switch reads as "on".
        "core.gates",
        # the model import: import_model's job (model_import.chat.import_job, reached only lazily) runs rigswap
        # as a subprocess and saves through studio.finish, so the spec collects the package and its fighter table.
        *_package_modules("randall.model_import"),
        *_package_modules("shared.modellab"),
    ]
    return list(dict.fromkeys(modules))


REQUIRED_MODULES = _required_modules()


def _import_in_frozen_like_subprocess(modules, cwd):
    """Import each module in one isolated child; return {module: error or None}."""
    script = textwrap.dedent("""
        import json, sys, traceback
        backend = sys.argv[1]
        modules = json.loads(sys.argv[2])
        # The frozen layout has exactly one place for application code. Keep the
        # interpreter's own path (stdlib + site-packages, which PyInstaller
        # bundles) and drop everything else -- notably '' and the script dir.
        keep = [p for p in sys.path if p and (
            'site-packages' in p.replace('\\\\', '/') or
            p.rstrip('/\\\\').endswith(('DLLs', 'lib', 'Lib', 'python312.zip')) or
            'python3' in p.replace('\\\\', '/').rsplit('/', 1)[-1].lower())]
        sys.path[:] = [backend] + keep
        result = {}
        for name in modules:
            try:
                __import__(name)
                result[name] = None
            except BaseException:
                result[name] = traceback.format_exc(limit=6).strip().splitlines()[-1]
        print('<<<RESULT>>>' + json.dumps(result))
    """)
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(BACKEND), json.dumps(list(modules))],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900,
        # -I already ignores PYTHONPATH; the empty env makes that visible and
        # strips anything else a developer shell exported into the run.
        env={k: v for k, v in os.environ.items()
             if k.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
                              "COMSPEC", "PATHEXT", "HOME", "USERPROFILE",
                              "LOCALAPPDATA", "APPDATA", "NUMBER_OF_PROCESSORS")},
    )
    marker = proc.stdout.rfind("<<<RESULT>>>")
    assert marker != -1, (
        "the import child produced no result — it died before it could report.\n"
        f"exit={proc.returncode}\nstdout tail:\n{proc.stdout[-3000:]}\n"
        f"stderr tail:\n{proc.stderr[-3000:]}")
    return json.loads(proc.stdout[marker + len("<<<RESULT>>>"):].splitlines()[0])


@pytest.fixture(scope="module")
def frozen_import_results(tmp_path_factory):
    cwd = tmp_path_factory.mktemp("not-the-backend")
    return _import_in_frozen_like_subprocess(REQUIRED_MODULES, cwd)


def test_the_module_list_is_not_empty():
    """A globbing bug that produced an empty list would make this file a no-op."""
    assert len(REQUIRED_MODULES) >= 15, REQUIRED_MODULES
    for expected in ("randall.assistant.tasks", "shared.rendering.part_identity",
                     "shared.ingame.verify_costume",
                     "nucleus_api", "nucleus_api.builds", "nucleus_api.game",
                     "core.safe_extract", "core.build_transaction"):
        assert expected in REQUIRED_MODULES, expected


@pytest.mark.parametrize("module", REQUIRED_MODULES)
def test_module_imports_with_a_frozen_like_path(frozen_import_results, module):
    error = frozen_import_results[module]
    assert error is None, f"{module} does not import on a frozen-like path: {error}"


# --------------------------------------------------------------------------
# what the spec claims, versus what is there
# --------------------------------------------------------------------------

def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_the_spec_collects_the_facade_explicitly():
    """`nucleus_api` has no production import path — only the spec ships it."""
    spec = _spec_text()
    assert "nucleus_api_modules" in spec, (
        "mex_backend.spec no longer collects nucleus_api; a preview build that "
        "exposes the facade would ship without it")
    assert "hiddenimports += ['nucleus_api']" in spec
    assert "nucleus_api/API.md" in spec or "'API.md'" in spec


def test_the_spec_keeps_the_menus_manifest():
    """Verified correct by the review; it may not quietly regress."""
    spec = _spec_text()
    assert "menus/compatibility_manifest.json" in spec
    assert (BACKEND / "data" / "menus" / "compatibility_manifest.json").is_file()


def test_the_spec_collects_the_model_import_with_backend_on_the_path():
    """The app reaches import_model's job and the vault save only lazily: the spec collects the package, fails an
    empty collection, and puts backend/ on sys.path before its first collect_submodules (without it every
    collection comes back empty without a word)."""
    spec = _spec_text()
    assert "collect_submodules('randall.model_import')" in spec and "collect_submodules('shared.modellab')" in spec
    assert "'randall.model_import.chat.import_job', 'randall.model_import.studio.finish'" in spec
    first_collect = min(spec.index(f"collect_submodules('{p}')") for p in ('shared.ingame', 'randall.model_import'))
    assert spec.index('sys.path.append(additional_paths[0])') < first_collect


# --------------------------------------------------------------------------
# the frozen-subprocess assumption
# --------------------------------------------------------------------------
# In a frozen build `sys.executable` is the backend BOOTLOADER, not a Python
# interpreter, and `devtools/` is not on disk at all. Spawning
# `[sys.executable, 'devtools/<something>.py']` therefore re-enters the backend
# with a nonsense argument instead of running the script. The in-process
# capture path is the fix.

#: Known, unfixed instances. Each entry is a promise that someone owns it, not
#: permission for the next one. `test_no_new_frozen_subprocess_assumptions`
#: fails on anything NOT listed; `test_the_known_debt_is_empty` keeps the
#: list empty now that it is.
# Empty on purpose. `nucleus_api/game.py` was the last entry: `capture_moves`
# spawned `[sys.executable, 'devtools/frameshot.py']`, which in a frozen build
# runs the PyInstaller bootloader against a script that is not shipped. It now
# calls the capture engine in-process (`_capture_in_process`), which also keeps
# the machine-wide Dolphin lock with one pid for the whole run.
KNOWN_FROZEN_SUBPROCESS_DEBT = {}


def _frozen_subprocess_hits():
    """`sys.executable` used within two lines of a `devtools/` path."""
    hits = {}
    for package in SHIPPED_PACKAGES:
        for path in (BACKEND / package).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for number, line in enumerate(lines):
                if "sys.executable" not in line:
                    continue
                window = "\n".join(lines[max(0, number - 2):number + 3])
                if "devtools/" in window or "devtools\\" in window:
                    rel = path.relative_to(BACKEND).as_posix()
                    hits.setdefault(rel, []).append(number + 1)
    return hits


def test_no_new_frozen_subprocess_assumptions():
    hits = _frozen_subprocess_hits()
    new = {rel: lines for rel, lines in hits.items()
           if rel not in KNOWN_FROZEN_SUBPROCESS_DEBT}
    assert not new, (
        "sys.executable is the bootloader in a frozen build and devtools/ is "
        "not shipped — use the in-process path:\n  "
        + "\n  ".join(f"{rel}:{lines}" for rel, lines in new.items()))


def test_the_allow_list_has_no_stale_entries():
    """An entry that no longer matches anything hides the next real one."""
    hits = _frozen_subprocess_hits()
    stale = sorted(set(KNOWN_FROZEN_SUBPROCESS_DEBT) - set(hits))
    assert not stale, f"fixed — delete from KNOWN_FROZEN_SUBPROCESS_DEBT: {stale}"


def test_the_known_debt_is_empty():
    assert not KNOWN_FROZEN_SUBPROCESS_DEBT, KNOWN_FROZEN_SUBPROCESS_DEBT


# --------------------------------------------------------------------------
# the verifier's engine digest (review §packaging)
# --------------------------------------------------------------------------

def test_the_spec_carries_the_engine_digest_hook():
    """Generated or not, the spec must have somewhere for the manifest to land.

    `shared.ingame.verify_costume.engine_version()` hashes its own SOURCE files. In a
    onefile build those paths are absent and every hash collapses to `None`, so
    two different engines share a cache key. Until a generator lands under
    `tools/build/`, the spec carries the marked TODO and the conditional
    `datas` entry; this keeps both from being quietly dropped.
    """
    spec = _spec_text()
    assert "engine_digest.json" in spec
    assert "TODO(S3/verification)" in spec
    generated = BACKEND / "shared" / "ingame" / "engine_digest.json"
    if generated.is_file():
        payload = json.loads(generated.read_text(encoding="utf-8"))
        assert payload.get("sources"), "a generated digest with no sources is worse than none"


def test_engine_version_still_reads_sources_we_can_name():
    """If the digest ever lands, it has to cover what engine_version() hashes."""
    source = (BACKEND / "shared" / "ingame" / "verify_costume.py").read_text(encoding="utf-8")
    block = re.search(r"_ENGINE_SOURCES = \((.*?)\)", source, re.S)
    assert block, "_ENGINE_SOURCES vanished from shared/ingame/verify_costume.py"
    names = re.findall(r'"([A-Za-z0-9_]+\.py)"', block.group(1))
    assert "frameshot.py" in names, (
        "the verifier no longer hashes devtools/frameshot.py — re-check the "
        "engine digest TODO in mex_backend.spec")


# --------------------------------------------------------------------------
# a spec that cannot be parsed is a build that fails at 3am
# --------------------------------------------------------------------------

def test_the_spec_is_syntactically_valid_python():
    ast.parse(_spec_text(), filename=str(SPEC))
