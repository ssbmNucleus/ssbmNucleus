"""The Any Climbers engine code must be REFRESHED on export, not just added.

`mexcli add-code` skips a code whose name already exists, so a project first
exported on 0.8.5 kept 0.8.5's engine code on every later export -- the 0.8.6
swap guard never reached it, which is exactly the "still softlocks on 0.8.6"
report. `ensure_code` now compares the project's block with the bundled one
and rewrites it through `sync-codes` when they differ.
"""
import json
from pathlib import Path

from vault.climbers import engine_code
from core.gecko import parse_ini, serialize_ini

NAME = "Any Climbers - Generic Follower AI [SSBM Nucleus]"
OLD = "C2006B84 00000002\n38600001 60000000\n60000000 00000000"
NEW = "C2006B84 00000002\n38600002 60000000\n60000000 00000000"
OTHER = "$!Skip Slippi SSS [KELLZ]\n04263384 48000010\n"


def _project(tmp_path, block):
    proj = tmp_path / "proj"
    (proj / "files").mkdir(parents=True)
    (proj / "files" / "codes.ini").write_text(
        OTHER + f"$!{NAME}\n{block}\n", encoding="utf-8")
    return proj / "project.mexproj"


def test_stale_block_detects_an_older_copy(tmp_path):
    proj = _project(tmp_path, OLD)
    assert engine_code.stale_block(proj, NAME, NEW) is True
    assert engine_code.stale_block(proj, NAME, OLD) is False


def test_stale_block_ignores_labels_and_spacing(tmp_path):
    proj = _project(tmp_path, OLD.replace("38600001 60000000", "38600001 60000000 #label"))
    assert engine_code.stale_block(proj, NAME, OLD) is False


def test_stale_block_is_none_without_a_copy(tmp_path):
    proj = tmp_path / "proj"
    (proj / "files").mkdir(parents=True)
    (proj / "files" / "codes.ini").write_text(OTHER, encoding="utf-8")
    assert engine_code.stale_block(proj / "project.mexproj", NAME, NEW) is None


def test_ensure_code_refreshes_a_stale_block_via_sync_codes(tmp_path, monkeypatch):
    # Keep the desired-INI scratch file in the test's disposable workspace.
    monkeypatch.setattr(engine_code.tempfile, "tempdir", str(tmp_path))
    proj = _project(tmp_path, OLD)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "sync-codes":
            # mexcli rewrites codes.ini from the desired ini; mimic that.
            desired = Path(cmd[3]).read_text(encoding="utf-8")
            (proj.parent / "files" / "codes.ini").write_text(desired, encoding="utf-8")
        class R:
            returncode = 0
            stdout = json.dumps({"success": True})
            stderr = ""
        return R()

    monkeypatch.setattr(engine_code, "code_entry", lambda: (NAME, NEW))
    monkeypatch.setattr(engine_code.subprocess, "run", fake_run)
    monkeypatch.setattr(engine_code, "MEXCLI_PATH", tmp_path / "mexcli.exe")
    (tmp_path / "mexcli.exe").write_bytes(b"")

    assert engine_code.ensure_code(proj) is True
    assert [c[1] for c in calls] == ["sync-codes"]

    # parse_ini splits "Name [Creator]" the way mexcli does; key by the header.
    codes = {(f"{c['name']} [{c['creator']}]" if c["creator"] else c["name"]): c
             for c in parse_ini((proj.parent / "files" / "codes.ini").read_text())}
    assert codes[NAME]["source"].strip() == NEW
    assert codes[NAME]["enabled"] is True
    assert "Skip Slippi SSS [KELLZ]" in codes  # the project's other codes survive
    assert engine_code.stale_block(proj, NAME, NEW) is False


def test_ensure_code_adds_when_missing(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / "files").mkdir(parents=True)
    (proj / "files" / "codes.ini").write_text(OTHER, encoding="utf-8")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = "{}"
            stderr = ""
        return R()

    monkeypatch.setattr(engine_code, "code_entry", lambda: (NAME, NEW))
    monkeypatch.setattr(engine_code.subprocess, "run", fake_run)
    monkeypatch.setattr(engine_code, "MEXCLI_PATH", tmp_path / "mexcli.exe")
    (tmp_path / "mexcli.exe").write_bytes(b"")

    assert engine_code.ensure_code(proj / "project.mexproj") is True
    assert [c[1] for c in calls] == ["add-code"]
