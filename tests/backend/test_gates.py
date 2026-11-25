"""The release-gate table is the one switch — these tests keep the halves honest.

Gates live in three places by necessity (Python backend, Electron main process,
Vite viewer). `core/gates.py` is the authority; this asserts the others agree.
"""
from tests.paths import APP
import re
from pathlib import Path

import pytest

from core import gates

NUCLEUS = APP
MAIN_JS = NUCLEUS / "electron" / "main.js"
FEATURES_JS = NUCLEUS / "frontend" / "src" / "shared" / "config" / "features.js"
ARCHITECTURE = NUCLEUS.parent / "docs" / "dev" / "ARCHITECTURE.md"


@pytest.fixture
def code_present(monkeypatch):
    """The environment half on its own: every gate's code counts as in the checkout
    (a public source checkout leaves some out; test_a_gate_without_its_code_is_closed)."""
    monkeypatch.setattr(gates, "present", lambda name: True)


def test_every_gate_defaults_on(monkeypatch, code_present):
    for name, gate in gates.GATES.items():
        monkeypatch.delenv(gate.env, raising=False)
        assert gates.enabled(name) is True, name


@pytest.mark.parametrize("value,expected", [
    ("0", False),      # the ONLY disabling value
    ("1", True),
    ("", True),
    ("false", True),   # historical semantics: not '0' means on
    ("00", True),
])
def test_gate_semantics(monkeypatch, code_present, value, expected):
    for name, gate in gates.GATES.items():
        monkeypatch.setenv(gate.env, value)
        assert gates.enabled(name) is expected, f"{name}={value!r}"


BACKEND_DIR = NUCLEUS / "backend"


def _fake_backend(root, modules):
    """A backend folder holding exactly `modules`, each as a package (an __init__.py)."""
    for module in modules:
        path = root.joinpath(*module.split("."))
        path.mkdir(parents=True, exist_ok=True)
        (path / "__init__.py").write_text("", encoding="utf-8")
    return root


def test_a_gate_without_its_code_is_closed(monkeypatch, tmp_path):
    """The public source drop leaves the coach and Combo Video out, and a clone of it is a
    dev checkout: there those gates read closed, whatever the environment says, while the
    gates whose code is there still follow the environment."""
    from core.build_smoke import _GATED_PACKAGES
    everything_but_the_coach = [p for name, packages in _GATED_PACKAGES.items() if name != "randall"
                                for p in packages]
    monkeypatch.setattr(gates, "_BACKEND", _fake_backend(tmp_path, everything_but_the_coach))
    for name, gate in gates.GATES.items():
        monkeypatch.setenv(gate.env, "1")
    assert gates.present("randall") is False and gates.enabled("randall") is False
    assert gates.present("assistant") is True and gates.enabled("assistant") is True
    assert gates.present("combo_video") is True and gates.enabled("combo_video") is True
    # A gate with no code of its own is always present.
    assert gates.present("delivery") is True and gates.enabled("delivery") is True
    # One package of a gate missing is enough to close it.
    (tmp_path / "tracker" / "routes" / "combo_video" / "__init__.py").unlink()
    assert gates.enabled("combo_video") is False
    # A module counts as a file too, but a folder left with no source (a __pycache__
    # after a pull) is not the package.
    (tmp_path / "randall" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "randall" / "routes" / "coach.py").write_text("", encoding="utf-8")
    (tmp_path / "randall" / "coach" / "__pycache__").mkdir(parents=True)
    assert gates.present("randall") is False
    (tmp_path / "randall" / "coach" / "__init__.py").write_text("", encoding="utf-8")
    assert gates.present("randall") is True
    # The environment still closes a gate whose code is there.
    monkeypatch.setenv(gates.GATES["assistant"].env, "0")
    assert gates.enabled("assistant") is False


def test_a_frozen_build_is_not_judged_by_the_disk(monkeypatch, tmp_path):
    """A frozen build's code is in its archive, not in folders: the spec decided what went in
    and electron/main.js closes what it left out."""
    import sys
    monkeypatch.setattr(gates, "_BACKEND", tmp_path)       # nothing on disk at all
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert all(gates.present(name) for name in gates.GATES)


def test_this_checkout_reads_each_gate_from_its_own_folders():
    """present() looks where the code is: app/backend, one folder up from core/."""
    from core.build_smoke import _GATED_PACKAGES
    assert gates._BACKEND == BACKEND_DIR.resolve()
    for name, packages in _GATED_PACKAGES.items():
        on_disk = all((BACKEND_DIR.joinpath(*p.split(".")) / "__init__.py").is_file()
                      or BACKEND_DIR.joinpath(*p.split(".")).with_suffix(".py").is_file() for p in packages)
        assert gates.present(name) is on_disk, name


def test_env_names_are_unique_and_prefixed():
    envs = [g.env for g in gates.GATES.values()]
    assert len(envs) == len(set(envs))
    assert all(e.startswith("NUCLEUS_") for e in envs)


def test_electron_matches_the_table():
    """electron/main.js must force off exactly the gates marked packaged_off."""
    src = MAIN_JS.read_text(encoding="utf-8")
    block = re.search(r"const PACKAGED_OFF_GATES = \[(.*?)\];", src, re.S)
    assert block, "PACKAGED_OFF_GATES list not found in electron/main.js"
    in_js = set(re.findall(r"'(NUCLEUS_[A-Z_]+)'", block.group(1)))
    assert in_js == set(gates.packaged_off_env()), (
        f"electron/main.js and core/gates.py disagree: "
        f"only in main.js={in_js - set(gates.packaged_off_env())}, "
        f"only in gates.py={set(gates.packaged_off_env()) - in_js}")


def test_electron_sets_no_other_nucleus_gate():
    """A gate assigned outside the loop would bypass the table."""
    src = MAIN_JS.read_text(encoding="utf-8")
    assigned = set(re.findall(r"backendEnv\.(NUCLEUS_[A-Z_]+)\s*=", src))
    # Not release gates: NUCLEUS_VAULT_DB is the storage-backend switch,
    # NUCLEUS_APP_VERSION identifies the spawning app, NUCLEUS_BACKEND_TOKEN
    # authenticates the app's private backend process, and
    # NUCLEUS_UI_APPROVAL_KEY is the second secret that tells the app's own
    # window apart from everything else holding that token (it is never printed
    # and never served; see projects/routes/menus/build_changes.py).
    infrastructure = {
        "NUCLEUS_VAULT_DB",
        "NUCLEUS_APP_VERSION",
        "NUCLEUS_BACKEND_TOKEN",
        "NUCLEUS_UI_APPROVAL_KEY",
    }
    assert assigned <= infrastructure, f"gate assigned outside the table: {assigned}"


def test_no_blueprint_reads_a_gate_env_directly():
    """Every gate read goes through core.gates so the table stays the truth."""
    offenders = []
    # whole-name match: NUCLEUS_VAULT_DUAL_WRITE / NUCLEUS_VAULT_DB merely start
    # with a gate name and are storage switches, not release gates
    pattern = re.compile(r"\b(" + "|".join(g.env for g in gates.GATES.values()) + r")\b")
    for py in (NUCLEUS / "backend").rglob("*.py"):
        if py.name == "gates.py" or "devtools" in py.parts:
            continue
        for line in py.read_text(encoding="utf-8").splitlines():
            if "os.environ" in line and pattern.search(line):
                offenders.append(f"{py.relative_to(NUCLEUS)}: {line.strip()}")
    assert not offenders, "read core.gates instead:\n" + "\n".join(offenders)


def test_viewer_flags_documented_in_the_table():
    """The gates the viewer decides on its own must name their UI half."""
    features = FEATURES_JS.read_text(encoding="utf-8")
    for name in ("combo_video", "randall", "play"):
        flag = gates.GATES[name].ui.split()[0]
        assert flag in features, f"{flag} (gates.py {name}.ui) missing from features.js"


def test_architecture_documents_every_gate():
    doc = ARCHITECTURE.read_text(encoding="utf-8")
    for name, gate in gates.GATES.items():
        assert gate.env in doc, f"{gate.env} ({name}) missing from ARCHITECTURE.md §7"
