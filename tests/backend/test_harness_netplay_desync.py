"""The harness's netplay_desync tool (backend/devtools/netrig.py behind it): it says what the two-client rig needs
before it boots anything, and turns netrig's log into a verdict. No Dolphin, no Slippi here."""
import json
import sys

from tests.paths import REPO

sys.path.insert(0, str(REPO / "tools" / "harness"))
import harness_mcp as h


def _login(user_dir, code):
    (user_dir / "Slippi").mkdir(parents=True)
    (user_dir / "Slippi" / "user.json").write_text(json.dumps({"connectCode": code}), encoding="utf-8")


def _rig(tmp_path, monkeypatch, code_a, code_b, vgamepad=True):
    root, appdata = tmp_path / "rig", tmp_path / "appdata"
    (root / "instance-a").mkdir(parents=True)
    (root / "instance-a" / "Slippi Dolphin.exe").write_bytes(b"")
    if code_a:
        _login(root / "instance-a" / "User", code_a)
    if code_b:
        _login(appdata / "Slippi Launcher" / "netplay" / "User", code_b)
    monkeypatch.setenv("NETRIG_ROOT", str(root))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(h, "_rig_python", lambda: sys.executable)
    monkeypatch.setattr(h, "_has_module", lambda python, name: vgamepad)
    return root


def test_registered():
    assert "netplay_desync" in h.HANDLERS
    schema = next(t for t in h.TOOL_DEFS if t["name"] == "netplay_desync")["inputSchema"]
    assert schema["properties"]["op"]["enum"] == ["check", "play", "status", "kill"]


def test_check_says_what_the_rig_needs(tmp_path, monkeypatch):
    monkeypatch.setenv("NETRIG_ROOT", str(tmp_path / "none"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(h, "_has_module", lambda python, name: False)
    report = h.HANDLERS["netplay_desync"]({}, lambda _: None)
    assert report["ready"] is False and len(report["problems"]) == 3
    assert "SECOND Slippi account" in report["problems"][0]
    _rig(tmp_path, monkeypatch, "AAA#1", "AAA#1")
    same = h.HANDLERS["netplay_desync"]({"op": "check"}, lambda _: None)
    assert len(same["problems"]) == 1 and same["problems"][0].startswith("Both clients are the same account (AAA#1)")
    assert "sign Slippi Launcher into a different Slippi account" in same["problems"][0]
    _rig(tmp_path / "ok", monkeypatch, "AAA#1", "BBB#2")
    ready = h.HANDLERS["netplay_desync"]({"op": "check"}, lambda _: None)
    assert ready["ready"] is True and (ready["client_a"], ready["client_b"]) == ("AAA#1", "BBB#2")


def test_play_refuses_before_the_rig_is_ready_and_boots_nothing(tmp_path, monkeypatch):
    _rig(tmp_path, monkeypatch, "AAA#1", "AAA#1")
    monkeypatch.setattr(h, "_run_cli", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    result = h.HANDLERS["netplay_desync"]({"op": "play"}, lambda _: None)
    assert result["ok"] is False and result["verdict"] is None and result["problems"]


def test_play_reads_the_verdict_and_diffs_the_two_replays(tmp_path, monkeypatch):
    _rig(tmp_path, monkeypatch, "AAA#1", "BBB#2")
    iso = tmp_path / "mod.iso"
    iso.write_bytes(b"iso")
    ra, rb = tmp_path / "a.slp", tmp_path / "b.slp"
    ra.write_bytes(b"a")
    rb.write_bytes(b"b")
    monkeypatch.setattr(h, "_no_session", lambda what: None)
    ran = []

    def run_cli(cmd, log, tail=120, **kw):
        ran.append(cmd)
        if cmd[1].endswith("netrig.py"):
            return 0, ["...", "=== VERDICT: CLEAN ===", "  game end: LRAS", f"replay a: {ra}", f"replay b: {rb}"]
        return 0, ["identical over 4000 frames"]
    monkeypatch.setattr(h, "_run_cli", run_cli)
    result = h.HANDLERS["netplay_desync"]({"op": "play", "iso": str(iso), "char_a": "marth", "stage": "battlefield"},
                                          lambda _: None)
    assert result["verdict"] == "CLEAN" and result["ok"] is True
    assert result["replays"] == [str(ra), str(rb)] and result["replay_diff"]["identical"] is True
    play = ran[0]
    assert play[2] == "play" and play[play.index("--iso-a") + 1] == play[play.index("--iso-b") + 1] == str(iso)
    assert play[play.index("--char-a") + 1] == "marth" and "--require-stage" in play
    assert ran[1][1].endswith("slpdiff.py")
