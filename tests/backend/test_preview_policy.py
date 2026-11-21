"""The 0.9.0 preview policy — the packaged injection.

`tests/backend/test_gates.py` covers the gate table. This covers the contract that
matters on the second PC: what a packaged preview build actually puts in the
backend's environment. Since 0.9.0 the assistant ships in every package, so a
preview package's policy is the stable one; the preview opt-in is kept for a
build that holds the assistant back again.

The review (`backend/artifacts/harness-experiment-20260922/ASTRA-INTEGRATION.md`)
names four switches by hand. They are asserted literally here on purpose — a
test that derives the expected values from the same table it is checking would
pass no matter what that table said.
"""
from tests.paths import APP
import re
import sys
from pathlib import Path

import pytest

from core import gates

NUCLEUS = APP
MAIN_JS = NUCLEUS / "electron" / "main.js"
PREVIEW_DOC = NUCLEUS.parent / "docs" / "dev" / "PREVIEW-0.9.0.md"
BUILD_BAT = NUCLEUS.parent / 'tools' / 'build' / "build.bat"

#: The review's list, spelled out. Do not replace with a comprehension.
REVIEW_PREVIEW_POLICY = {
    "NUCLEUS_BUILD_COMMIT": "0",
    "NUCLEUS_DELIVERY": "0",
    "NUCLEUS_WISH_SUBMIT": "0",
}


# --------------------------------------------------------------------------
# the three write paths are gates, and they are packaged OFF
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,env", [
    ("build_commit", "NUCLEUS_BUILD_COMMIT"),
    ("delivery", "NUCLEUS_DELIVERY"),
    ("wish_submit", "NUCLEUS_WISH_SUBMIT"),
])
def test_the_write_paths_are_in_the_gate_table_and_packaged_off(name, env):
    assert gates.GATES[name].env == env
    assert gates.GATES[name].packaged_off is True
    assert env in gates.packaged_off_env()


@pytest.mark.parametrize("name,env", [
    ("build_commit", "NUCLEUS_BUILD_COMMIT"),
    ("delivery", "NUCLEUS_DELIVERY"),
    ("wish_submit", "NUCLEUS_WISH_SUBMIT"),
])
def test_write_path_gates_read_the_environment(monkeypatch, name, env):
    monkeypatch.delenv(env, raising=False)
    assert gates.enabled(name) is True    # dev sees everything
    monkeypatch.setenv(env, "0")
    assert gates.enabled(name) is False
    monkeypatch.setenv(env, "1")
    assert gates.enabled(name) is True


# --------------------------------------------------------------------------
# the packaged preview policy
# --------------------------------------------------------------------------

def test_the_packaged_preview_policy_is_exactly_the_reviewed_values():
    env = gates.preview_policy_env()
    for key, expected in REVIEW_PREVIEW_POLICY.items():
        assert env[key] == expected, f"{key} is {env[key]!r}, the review requires {expected!r}"


def test_every_package_has_the_assistant_since_0_9_0():
    """The assistant shipped in 0.9.0: no package forces NUCLEUS_ASSISTANT off, so the
    backend's default (on) applies in stable and preview packages alike."""
    assert gates.GATES["assistant"].packaged_off is False
    for preview in (True, False):
        assert "NUCLEUS_ASSISTANT" not in gates.policy_env(preview=preview)


def test_a_preview_package_opens_nothing_a_stable_one_keeps_shut():
    """With the assistant shipped, a preview package's policy is the stable one."""
    assert gates.preview_policy_env() == gates.policy_env(preview=False)
    open_gates = {k for k, v in gates.preview_policy_env().items() if v == "1"}
    assert open_gates == set()


def test_a_held_back_assistant_is_opened_by_a_preview_package_alone(monkeypatch):
    """The mechanism the 0.9.0 previews used still works if the assistant is held back again."""
    monkeypatch.setitem(gates.GATES, "assistant", gates.GATES["assistant"]._replace(packaged_off=True))
    assert gates.policy_env(preview=True)["NUCLEUS_ASSISTANT"] == "1"
    assert gates.policy_env(preview=False)["NUCLEUS_ASSISTANT"] == "0"
    open_gates = {k for k, v in gates.policy_env(preview=True).items() if v == "1"}
    assert open_gates == {"NUCLEUS_ASSISTANT"}


def test_a_non_preview_package_is_strict_everywhere():
    env = gates.policy_env(preview=False)
    assert set(env.values()) == {"0"}
    # The Tracker coach and Combo Video stay off in every package.
    assert env["NUCLEUS_RANDALL"] == "0" and env["NUCLEUS_COMBO_VIDEO"] == "0"
    assert gates.preview_policy_env()["NUCLEUS_RANDALL"] == "0"


def test_policy_env_covers_every_packaged_off_gate():
    for preview in (True, False):
        env = gates.policy_env(preview=preview)
        assert set(env) == set(gates.packaged_off_env())


def test_startup_log_line_names_the_switches_a_preview_moves(monkeypatch):
    for key, value in REVIEW_PREVIEW_POLICY.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NUCLEUS_ASSISTANT", "1")
    line = gates.policy_log_line()
    for key, value in REVIEW_PREVIEW_POLICY.items():
        assert f"{key}={value}" in line, line
    assert "\n" not in line, "the startup policy must be ONE line"


# --------------------------------------------------------------------------
# electron/main.js is the injector — it must agree with the table
# --------------------------------------------------------------------------

def test_the_injected_environment_is_exactly_policy_env():
    """Reconstruct what main.js produces and compare it to the one table."""
    src = MAIN_JS.read_text(encoding="utf-8")
    block = re.search(r"const PACKAGED_OFF_GATES = \[(.*?)\];", src, re.S)
    packaged_off = re.findall(r"'(NUCLEUS_[A-Z_]+)'", block.group(1))
    for preview in (True, False):
        built = {g: ("1" if preview and g == "NUCLEUS_ASSISTANT" else "0")
                 for g in packaged_off}
        assert built == gates.policy_env(preview=preview), f"preview={preview}"


# --------------------------------------------------------------------------
# the build half and the document
# --------------------------------------------------------------------------

def test_build_bat_still_drives_the_preview_through_previewFeatures():
    """The selector the review chose: NUCLEUS_PREVIEW_FEATURES=assistant. Since 0.9.0 the
    frontend flag follows the gate (`ship_guard.py gate assistant`), which honours it."""
    src = BUILD_BAT.read_text(encoding="utf-8", errors="replace")
    assert "NUCLEUS_PREVIEW_FEATURES" in src
    assert "VITE_ASSISTANT_PREVIEW=1" in src
    assert 'ship_guard.py" gate assistant' in src
    assert "--config.extraMetadata.previewFeatures=" in src


def test_build_bat_bakes_the_secret_preview_channel_only_into_preview_builds():
    """NUCLEUS_PREVIEW_CHANNEL becomes the packaged previewChannel token that
    electron/updates/updater.js turns into <platform>/preview/<token>/latest.json. It is
    refused without NUCLEUS_PREVIEW_FEATURES, format-checked before the build,
    and the packaged manifest is verified after it."""
    src = BUILD_BAT.read_text(encoding="utf-8", errors="replace")
    assert "--config.extraMetadata.previewChannel=%NUCLEUS_PREVIEW_CHANNEL%" in src
    assert ("if defined NUCLEUS_PREVIEW_CHANNEL if not defined NUCLEUS_PREVIEW_FEATURES ("
            in src)
    assert "[A-Za-z0-9_-]{16,64}" in src
    assert "check_preview_channel.js" in src
    # Validation happens before the first expensive stage.
    assert src.index("PREVIEW_CHANNEL_INVALID") < src.index("[1/5]")


def test_the_tree_manifest_is_release_clean():
    """previewFeatures is injected into the PACKAGED manifest, never committed.

    A committed `previewFeatures` would make every developer build — and, far
    worse, the next release build off this tree — a preview package.
    """
    import json
    manifest = json.loads((NUCLEUS / "package.json").read_text(encoding="utf-8"))
    assert "previewChannel" not in manifest, (
        "the secret preview channel token must only ever be packaged by build.bat")
    assert "previewFeatures" not in manifest, (
        "package.json in the tree must stay release-clean; build.bat injects "
        "previewFeatures with --config.extraMetadata.previewFeatures")


def test_the_preview_document_names_every_key_and_value():
    doc = PREVIEW_DOC.read_text(encoding="utf-8")
    for key, value in REVIEW_PREVIEW_POLICY.items():
        assert key in doc, f"{key} missing from docs/PREVIEW-0.9.0.md"
        assert f"{key}={value}" in doc or f"`{value}`" in doc, key


def _preview_channel_gate_bat(tmp_path):
    """The preview-channel checks from the top of build.bat, run on their own:
    from the first NUCLEUS_PREVIEW_CHANNEL check through its third refusal
    block, followed by a PASSED marker."""
    lines = BUILD_BAT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("if defined NUCLEUS_PREVIEW_CHANNEL if not defined"))
    closes, end = 0, start
    for end in range(start, len(lines)):
        if lines[end] == ")":
            closes += 1
            if closes == 3:
                break
    script = ["@echo off", "set NUCLEUS_BUILD_NONINTERACTIVE=1",
              *lines[start:end + 1], "echo PASSED"]
    path = tmp_path / "preview_channel_gate.bat"
    path.write_text("\r\n".join(script) + "\r\n", encoding="utf-8")
    return path


TOKEN = "tEsT-channel_Token-0123"


@pytest.mark.skipif(sys.platform != "win32", reason="runs build.bat's cmd/PowerShell checks")
@pytest.mark.parametrize("features, channel, version, ok", [
    ("assistant", TOKEN, "0.9.0-preview.8", True),
    ("assistant", "", "0.9.0", True),            # a preview without the channel
    ("", "", "", True),                          # a release build
    ("", TOKEN, "0.9.0-preview.8", False),       # channel without previewFeatures
    ("assistant", "short", "0.9.0-preview.8", False),
    ("assistant", "1234567890123456", "0.9.0-preview.8", False),
    ("assistant", TOKEN + "\n", "0.9.0-preview.8", False),   # trailing LF
    ("assistant", TOKEN + "\r\n", "0.9.0-preview.8", False),
    ("assistant", TOKEN, "0.9.0", False),        # plain version: testers could never leave
    ("assistant", TOKEN, "", False),
    ("assistant", TOKEN, "0.9.0-preview.8\n", False),
    ("assistant", TOKEN, "0.9.0-preview.08", False),
])
def test_build_bat_preview_channel_gate_really_refuses(tmp_path, features, channel, version, ok):
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items()
           if k not in ("NUCLEUS_PREVIEW_FEATURES", "NUCLEUS_PREVIEW_CHANNEL",
                        "NUCLEUS_BUILD_VERSION")}
    for key, value in (("NUCLEUS_PREVIEW_FEATURES", features),
                       ("NUCLEUS_PREVIEW_CHANNEL", channel),
                       ("NUCLEUS_BUILD_VERSION", version)):
        if value:
            env[key] = value
    # `cmd /c build.bat` is how ci.py runs it: the exit code must survive that.
    result = subprocess.run(["cmd", "/c", str(_preview_channel_gate_bat(tmp_path))],
                            capture_output=True, text=True, env=env, timeout=120)
    if ok:
        assert result.returncode == 0 and "PASSED" in result.stdout, result.stdout
    else:
        assert result.returncode == 1, result.stdout
        assert "PASSED" not in result.stdout and "ERROR:" in result.stdout, result.stdout


def test_build_bat_anchors_are_newline_proof():
    src = BUILD_BAT.read_text(encoding="utf-8", errors="replace")
    gate = src[src.index("if defined NUCLEUS_PREVIEW_CHANNEL if not"):src.index("[1/5]")]
    assert "-cmatch '^" not in gate and "$')" not in gate
    assert gate.count("-cmatch '\\A") == 2 and gate.count("\\z')") == 2
