import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from tests.paths import REPO

sys.path[:0] = [str(REPO / "tools"), str(REPO / "tools/harness"), str(REPO / "app/backend")]
from creation import jobs, workflows as w
import harness_mcp as h


def test_creation_tools_are_discoverable_with_current_options():
    assert len(h.TOOL_DEFS) == len(h.HANDLERS) == 45
    assert {"native_port", "rigswap", "stage_workbench"} <= h.HANDLERS.keys()
    assert {"own", "only", "from", "to", "calibrate", "forms_from"} <= w.PORT_SCHEMA["properties"].keys()
    assert h.HANDLERS["native_port"]({"op": "info"}, print)["engine"] == str(REPO / "tools/fighterport")


def test_current_cli_options_and_no_implicit_calibration(tmp_path):
    root = tmp_path / "source files"
    root.mkdir()
    a = dict(game="rivals2", fighter="ranno", name="Ranno port", root=str(root),
             work=str(tmp_path / "work files"), only="preflight", forms_from="driver")
    argv = w.port_argv(a)
    assert "--own" in argv
    assert "--calibrate" not in argv and "--iso" not in argv
    assert argv[argv.index("--name") + 1] == "Ranno port"
    assert argv[argv.index("--only") + 1] == "preflight"
    assert argv[argv.index("--forms-from") + 1] == "driver"
    with pytest.raises(ValueError, match="own-skeleton"):
        w.port_argv(dict(a, own=False))
    with pytest.raises(ValueError, match="contain the source"):
        w.port_argv(dict(a, work=str(tmp_path)))


def test_source_export_preserves_existing_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "start", lambda *a, **k: pytest.fail("must validate before starting"))
    with pytest.raises(ValueError, match="new reader output"):
        w.native_port(dict(op="read_source", game="rivals2", fighter="Ranno",
                           game_dir=str(tmp_path), root=str(tmp_path)), print)


def test_environment_uses_nucleus_copy_and_keeps_configured_dependencies(tmp_path, monkeypatch):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"fighterport": {"SSBH_DATA_PY": "from-settings", "SECRET": "not-forwarded"}}))
    monkeypatch.setattr(w, "SETTINGS", config)
    monkeypatch.setenv("SSBH_DATA_PY", "from-environment")
    monkeypatch.delenv("SECRET", raising=False)
    _, env = w.environment("native_port")
    assert env["SSBH_DATA_PY"] == "from-environment"
    assert env["NUCLEUS_REPO"] == str(REPO)
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(REPO / "tools/fighterport")
    assert "SECRET" not in env


def wait_job(job, tool):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = jobs.status(job, tool)
        if result["state"] not in jobs.ACTIVE:
            return result
        time.sleep(0.1)
    jobs.cancel(job, tool)
    pytest.fail("creation worker did not finish")


def test_real_worker_checklist_survives_caller_return(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    _, env = w.environment("native_port")
    started = jobs.start("native_port", {"op": "checklist"}, python=sys.executable, env=env)
    result = wait_job(started["job"], "native_port")
    assert result["state"] == "succeeded", result
    receipt = jobs.read(result["result_file"])
    assert receipt["ok"] is True and receipt["lines"]
    assert "Optional" in receipt["rule"]


def test_worker_failure_is_not_success_and_job_is_owned(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    _, env = w.environment("native_port")
    result = jobs.start("native_port", {"op": "unknown"}, python=sys.executable, env=env)
    result = wait_job(result["job"], "native_port")
    assert result["state"] == "failed" and result["ok"] is False
    assert "Unknown worker operation" in result["result"]["error"]
    with pytest.raises(ValueError, match="other creation tool"):
        jobs.cancel(result["job"], "rigswap")
    with pytest.raises(ValueError):
        jobs.status("../anything", "native_port")


def test_output_lock_refuses_a_second_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    resource = str(tmp_path / "port-work")
    lease = jobs.lock_resource(tmp_path, resource)
    try:
        _, env = w.environment("native_port")
        result = jobs.start("native_port", {"op": "checklist"}, python=sys.executable,
                            env=env, resource=resource)
        result = wait_job(result["job"], "native_port")
        assert result["state"] == "failed"
        assert "Another creation job" in result["error"]
    finally:
        lease.close()


def test_cancel_before_launch_and_interrupted_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    folder = tmp_path / ("a" * 32)
    folder.mkdir()
    jobs.write(folder / "request.json", {"tool": "native_port", "args": {"op": "checklist"}})
    jobs.write(folder / "status.json", {"state": "queued", "heartbeat": time.time()})
    jobs.cancel(folder.name, "native_port")
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: pytest.fail("cancelled job must not launch"))
    jobs.supervise(folder)
    assert jobs.status(folder.name, "native_port")["state"] == "cancelled"
    jobs.write(folder / "status.json", {"state": "running", "heartbeat": time.time() - 60})
    assert jobs.status(folder.name, "native_port")["state"] == "interrupted"


def test_status_write_retries_windows_sharing_violation(tmp_path, monkeypatch):
    replace = Path.replace
    calls = []
    def busy_once(path, target):
        calls.append(target)
        if len(calls) == 1:
            raise PermissionError("reader holds status.json")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", busy_once)
    jobs.write(tmp_path / "status.json", {"state": "running"})
    assert jobs.read(tmp_path / "status.json")["state"] == "running"
    assert len(calls) == 2


def test_rigswap_reuses_importer_and_preserves_failure(tmp_path, monkeypatch):
    from randall.model_import.chat import import_job
    seen = {}
    def run(args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        return {"status": "failed", "error": "bad model"}
    monkeypatch.setattr(import_job, "run", run)
    result = w.execute("rigswap", {"op": "fix", "project": "sample", "change": "smaller head", "said": "head's too big"}, tmp_path)
    assert result["ok"] is False
    assert seen["args"]["said"] == "head's too big"
    assert not seen["kwargs"]["cancelled"]()
    (tmp_path / "cancel").touch()
    assert seen["kwargs"]["cancelled"]()


def test_real_stdio_lists_and_routes_all_creation_tools():
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        *[{"jsonrpc": "2.0", "id": i + 3, "method": "tools/call",
           "params": {"name": name, "arguments": {"op": op}}}
          for i, (name, op) in enumerate((("native_port", "info"), ("rigswap", "info"), ("stage_workbench", "guide")))],
    ]
    result = subprocess.run([sys.executable, str(REPO / "tools/harness/harness_mcp.py")],
                            input="\n".join(json.dumps(r) for r in requests) + "\n", capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    responses = {row["id"]: row["result"] for line in result.stdout.splitlines() if (row := json.loads(line)).get("id")}
    assert len(responses[2]["tools"]) == 45
    assert all(not responses[i]["isError"] for i in (3, 4, 5)), responses


def test_status_waits_for_an_active_job_to_end(tmp_path, monkeypatch):
    """An AI that polled a 26-minute port without sleeping made 584 calls (0.9.0 launch video): status waits."""
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    folder = tmp_path / ("b" * 32)
    folder.mkdir()
    jobs.write(folder / "request.json", {"tool": "native_port", "args": {"op": "port"}})
    jobs.write(folder / "status.json", {"state": "running", "heartbeat": time.time()})

    def finish():
        time.sleep(1.5)
        jobs.write(folder / "status.json", {"state": "done", "ok": True, "heartbeat": time.time()})
    worker = threading.Thread(target=finish)
    worker.start()
    started = time.monotonic()
    assert jobs.status(folder.name, "native_port", wait=10)["state"] == "done"
    assert time.monotonic() - started < 6, "it answers when the job ends, not when the wait runs out"
    worker.join()
    jobs.write(folder / "status.json", {"state": "running", "heartbeat": time.time()})
    started = time.monotonic()
    assert jobs.status(folder.name, "native_port", wait=1)["state"] == "running"
    assert 0.9 <= time.monotonic() - started < 4
    assert jobs.status(folder.name, "native_port")["state"] == "running"
    for bad in (-1, jobs.STATUS_WAIT_MAX + 1, 2.5, True, "5"):
        with pytest.raises(ValueError):
            jobs.status(folder.name, "native_port", wait=bad)
    seen = []
    monkeypatch.setattr(jobs, "status", lambda job, tool, wait=0: seen.append((tool, wait)) or {})
    w.native_port({"op": "status", "job": folder.name}, None)
    w.native_port({"op": "status", "job": folder.name, "wait_seconds": 0}, None)
    w.rigswap({"op": "status", "job": folder.name}, None)
    assert seen == [("native_port", jobs.STATUS_WAIT_DEFAULT), ("native_port", 0), ("rigswap", jobs.STATUS_WAIT_DEFAULT)]
