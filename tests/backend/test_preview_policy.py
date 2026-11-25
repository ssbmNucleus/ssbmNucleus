"""The 0.9.0 preview policy — the packaged injection.

`tests/backend/test_gates.py` covers the gate table. This covers the contract that
matters on the second PC: what a packaged preview build actually puts in the
backend's environment. The assistant ships in every package since 0.9.0.
Since 0.10.0 the Windows stable manifest opens Play through releaseFeatures.

The review (`backend/artifacts/harness-experiment-20260922/ASTRA-INTEGRATION.md`)
names four switches by hand. They are asserted literally here on purpose — a
test that derives the expected values from the same table it is checking would
pass no matter what that table said.
"""
from tests.paths import APP
import re
import shutil
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


def test_the_original_assistant_preview_preserves_the_default_policy():
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


def test_a_package_without_feature_metadata_closes_packaged_off_gates():
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

#: What a packaged manifest's previewFeatures can hold, and what each opens.
FEATURE_CASES = [None, "", "assistant", "play", "assistant,play", " Play ", "display",
                 "playground", ["play"], ["assistant", "play"], 7]


def _main_js_preview_opens(src):
    block = re.search(r"const PREVIEW_OPENS = \{(.*?)\};", src, re.S)
    assert block, "PREVIEW_OPENS not found in electron/main.js"
    return dict(re.findall(r"(NUCLEUS_[A-Z_]+): '([a-z_]+)'", block.group(1)))


def test_the_injected_environment_is_exactly_policy_env():
    """Reconstruct what main.js produces and compare it to the one table."""
    src = MAIN_JS.read_text(encoding="utf-8")
    block = re.search(r"const PACKAGED_OFF_GATES = \[(.*?)\];", src, re.S)
    packaged_off = re.findall(r"'(NUCLEUS_[A-Z_]+)'", block.group(1))
    opens = _main_js_preview_opens(src)
    assert opens == gates.PREVIEW_OPENS
    assert "const previewFeatures = packagedPreviewFeatures(packaged.previewFeatures);" in src
    assert "const releaseFeatures = packagedPreviewFeatures(packaged.releaseFeatures);" in src
    assert "const feature = PREVIEW_OPENS[gate];" in src
    assert ("backendEnv[gate] = previewFeatures.has(feature) || releaseFeatures.has(feature) "
            "? '1' : '0';") in src
    for features in FEATURE_CASES:
        for release in (None, "", "play", ["play"], "display"):
            wanted = gates.preview_features(features) | gates.preview_features(release or ())
            built = {g: ("1" if opens.get(g) in wanted else "0") for g in packaged_off}
            assert built == gates.policy_env(features=features, release=release), \
                f"previewFeatures={features!r} releaseFeatures={release!r}"
    # The 0.9.0 spelling: preview=True is previewFeatures=assistant.
    assert gates.policy_env(preview=True) == gates.policy_env(features="assistant")
    assert gates.policy_env(preview=False) == gates.policy_env(features=None)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run main.js's parser")
def test_main_js_reads_previewFeatures_the_way_gates_py_does():
    """Run main.js's own packagedPreviewFeatures on every case: whole names only."""
    import json
    import subprocess
    src = MAIN_JS.read_text(encoding="utf-8")
    fn = re.search(r"function packagedPreviewFeatures\(value\) \{.*?\n\}", src, re.S)
    assert fn, "packagedPreviewFeatures not found in electron/main.js"
    cases = [c for c in FEATURE_CASES if c is not None]
    script = (fn.group(0) + "\nconst cases = " + json.dumps(cases) + ";\n"
              "process.stdout.write(JSON.stringify(cases.map((c) => [...packagedPreviewFeatures(c)].sort())));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    for case, got in zip(cases, json.loads(out.stdout)):
        assert set(got) == gates.preview_features(case), case


def test_play_opens_only_in_a_package_that_asks_for_it_by_name():
    assert gates.GATES["play"].packaged_off is True
    assert gates.policy_env(features="play")["NUCLEUS_PLAY"] == "1"
    assert gates.policy_env(features="assistant,play")["NUCLEUS_PLAY"] == "1"
    for features in (None, "", "assistant", "display", "playground", "play-preview"):
        assert gates.policy_env(features=features)["NUCLEUS_PLAY"] == "0", features
    assert gates.policy_env(preview=True)["NUCLEUS_PLAY"] == "0"
    # A Play test build opens Play and nothing else: the coach and the write paths stay shut.
    open_gates = {k for k, v in gates.policy_env(features="assistant,play").items() if v == "1"}
    assert open_gates == {"NUCLEUS_PLAY"}
    for key, value in REVIEW_PREVIEW_POLICY.items():
        assert gates.policy_env(features="play")[key] == value


# --------------------------------------------------------------------------
# Play in stable builds
# --------------------------------------------------------------------------

def test_the_release_opens_play_on_windows_only():
    assert gates.PLAY_IN_STABLE is True
    assert gates.GATES["play"].packaged_off is True
    assert gates.release_features("win32") == {"play"}
    assert gates.release_features("linux") == set() and gates.release_features("darwin") == set()
    # A stable Windows package then opens Play and nothing else.
    env = gates.policy_env(release=gates.release_features("win32"))
    assert {k for k, v in env.items() if v == "1"} == {"NUCLEUS_PLAY"}
    for key, value in REVIEW_PREVIEW_POLICY.items():
        assert env[key] == value


def test_holding_play_back_reaches_every_layer(monkeypatch):
    """The packaging checks and frozen smoke also follow the switch when it closes."""
    sys.path.insert(0, str(NUCLEUS.parent / "tools" / "build"))
    try:
        import ship_guard
    finally:
        sys.path.pop(0)
    monkeypatch.delenv("NUCLEUS_PREVIEW_FEATURES", raising=False)
    assert ship_guard.gate_ships_in_stable("play") is (sys.platform == "win32")
    real = ship_guard._gates_table

    def held_back():
        table = real()
        table.PLAY_IN_STABLE = False
        return table

    monkeypatch.setattr(ship_guard, "_gates_table", held_back)
    assert ship_guard.gate_ships("play") is False
    assert ship_guard.gate_ships_in_stable("play") is False

    from core import build_smoke
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(gates, "PLAY_IN_STABLE", False)
    assert build_smoke._feature_ships("play") is False


def test_build_bat_writes_releaseFeatures_only_for_the_stable_switch():
    src = BUILD_BAT.read_text(encoding="utf-8", errors="replace")
    assert 'set "PLAY_STABLE="' in src
    assert src.index('set "PLAY_STABLE="') < src.index('ship_guard.py" gate play --stable')
    assert src.index('ship_guard.py" gate play --stable') < src.index("npm run build")
    assert ('if defined PLAY_STABLE set "RELEASE_FEATURES_OVERRIDE='
            '--config.extraMetadata.releaseFeatures=play"') in src
    assert "%RELEASE_FEATURES_OVERRIDE%" in src
    import json
    assert "releaseFeatures" not in json.loads((NUCLEUS / "package.json").read_text(encoding="utf-8"))


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


def test_build_bat_builds_play_when_the_gate_ships():
    """The frontend flag follows the ship guard. Prerelease validation runs before the build."""
    src = BUILD_BAT.read_text(encoding="utf-8", errors="replace")
    assert 'set "VITE_PLAY_PREVIEW="' in src
    assert src.index('set "VITE_PLAY_PREVIEW="') < src.index('ship_guard.py" gate play')
    assert "VITE_PLAY_PREVIEW=1" in src
    assert src.index('ship_guard.py" gate play') < src.index("npm run build")
    assert src.index("PLAY_VERSION_INVALID") < src.index("[1/5]")


def test_the_play_flag_is_dev_or_set_by_the_windows_build():
    """Play is on in dev or when build.bat sets VITE_PLAY_PREVIEW=1."""
    text = (NUCLEUS / "frontend" / "src" / "shared" / "config" / "features.js").read_text(encoding="utf-8")
    assert "const PLAY_PREVIEW = import.meta.env.VITE_PLAY_PREVIEW === '1'" in text
    expr = re.search(r"export const PLAY_ENABLED = (.+?)\n\n|export const PLAY_ENABLED = (.+)$", text, re.S)
    expr = (expr.group(1) or expr.group(2)) if expr else ""
    assert expr.startswith("(import.meta.env.DEV || PLAY_PREVIEW) && !SHIP_GATES"), expr
    app = (NUCLEUS / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    assert ("const loadPlay = (import.meta.env.DEV || import.meta.env.VITE_PLAY_PREVIEW === '1') "
            "&& PLAY_ENABLED") in app


def _play_gate_bat(tmp_path):
    """build.bat's Play test build check, run on its own, followed by a PASSED marker."""
    lines = BUILD_BAT.read_text(encoding="utf-8").splitlines()
    start = lines.index('set "PLAY_PREVIEW="')
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("if defined PLAY_PREVIEW echo"))
    script = ["@echo off", "set NUCLEUS_BUILD_NONINTERACTIVE=1", *lines[start:end + 1], "echo PASSED"]
    path = tmp_path / "play_gate.bat"
    path.write_text("\r\n".join(script) + "\r\n", encoding="utf-8")
    return path


@pytest.mark.skipif(sys.platform != "win32", reason="runs build.bat's cmd/PowerShell checks")
@pytest.mark.parametrize("features, version, ok", [
    ("play", "0.9.2-play-preview.1", True),
    ("assistant, Play", "0.9.2-play-preview.1", True),
    ("", "", True),                              # a release build
    ("assistant", "0.9.1", True),                # not a Play build: no version rule here
    ("display", "0.9.1", True),                  # whole names only
    ("play", "", False),                         # the release stage's plain tree version
    ("play", "0.9.1", False),
    ("assistant,play", "0.9.1", False),
    ("play", "0.9.2-play-preview.1\n", False),
])
def test_build_bat_play_gate_really_refuses(tmp_path, features, version, ok):
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items()
           if k not in ("NUCLEUS_PREVIEW_FEATURES", "NUCLEUS_PREVIEW_CHANNEL", "NUCLEUS_BUILD_VERSION")}
    for key, value in (("NUCLEUS_PREVIEW_FEATURES", features), ("NUCLEUS_BUILD_VERSION", version)):
        if value:
            env[key] = value
    result = subprocess.run(["cmd", "/c", str(_play_gate_bat(tmp_path))],
                            capture_output=True, text=True, env=env, timeout=120)
    if ok:
        assert result.returncode == 0 and "PASSED" in result.stdout, result.stdout
    else:
        assert result.returncode == 1, result.stdout
        assert "PASSED" not in result.stdout and "ERROR:" in result.stdout, result.stdout


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
    # The preview channel's two checks and the Play test build's version check.
    assert gate.count("-cmatch '\\A") == 3 and gate.count("\\z')") == 3
