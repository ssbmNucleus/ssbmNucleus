"""Durable developer jobs, independent of the MCP server's lifetime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "app" / "scratch" / "creation" / "jobs"
WORKER = Path(__file__).with_name("worker.py")
ACTIVE = {"queued", "running", "cancelling"}
# op=status waits for an active job to end, so a caller looks a few times a minute instead of spinning: an AI
# that polled a 26-minute port without sleeping made 584 calls (0.9.0 launch video, 11-19). The most stays under
# the app MCP's inline limit (app/backend/randall/mcp/calls.INLINE_SECONDS, 45 s), past which a call becomes a
# job of its own.
STATUS_WAIT_DEFAULT = 30
STATUS_WAIT_MAX = 40


def write(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    try:
        # Windows readers/AV can briefly deny replacement even after a small read.
        for attempt in range(40):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.025)
    finally:
        tmp.unlink(missing_ok=True)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def hidden():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def tail(path, limit=12000):
    if not Path(path).is_file():
        return ""
    with open(path, "rb") as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - limit))
        return stream.read().decode("utf-8", errors="replace")


def folder_for(job, tool):
    if not isinstance(job, str) or not re.fullmatch(r"[a-f0-9]{32}", job):
        raise ValueError("Use the job id returned by this tool")
    folder = ROOT / job
    if not (folder / "request.json").is_file():
        raise ValueError(f"Unknown creation job: {job}")
    if read(folder / "request.json")["tool"] != tool:
        raise ValueError("This job belongs to the other creation tool")
    return folder


def status(job, tool, wait=0):
    """The job's state. With `wait` seconds (whole, at most STATUS_WAIT_MAX), an active job is looked at again
    every second until it ends, its worker stops answering, or the time is up."""
    if type(wait) is not int or not 0 <= wait <= STATUS_WAIT_MAX:
        raise ValueError(f"wait_seconds is a whole number of seconds from 0 to {STATUS_WAIT_MAX}")
    folder = folder_for(job, tool)
    deadline = time.monotonic() + wait
    while True:
        result = read(folder / "status.json")
        stale = result["state"] in ACTIVE and time.time() - result["heartbeat"] > 30
        left = deadline - time.monotonic()
        if result["state"] not in ACTIVE or stale or left <= 0:
            break
        time.sleep(min(1.0, left))
    if stale:
        result.update(state="interrupted", ok=False,
                      error="Worker heartbeat stopped; inspect the log before resuming the work")
    result.update(job=job, tool=tool, log=str(folder / "job.log"),
                  log_tail=tail(folder / "job.log"), result_file=str(folder / "result.json"))
    if (folder / "result.json").is_file() and result["state"] not in ACTIVE:
        value = read(folder / "result.json")
        if len(json.dumps(value)) <= 24000:
            result["result"] = value
        else:
            result["result_note"] = "Full result exceeds the response budget; read result_file"
    return result


def cancel(job, tool):
    folder = folder_for(job, tool)
    result = status(job, tool)
    if result["state"] in ACTIVE:
        (folder / "cancel").touch()
        result["cancellation_requested"] = True
    return result


def start(tool, args, *, python, env, resource=None):
    job = uuid.uuid4().hex
    folder = ROOT / job
    folder.mkdir(parents=True)
    write(folder / "request.json", dict(tool=tool, args=args, resource=resource))
    write(folder / "status.json", dict(state="queued", ok=None, heartbeat=time.time()))
    try:
        with (folder / "job.log").open("ab", buffering=0) as log:
            subprocess.Popen([str(python), "-u", str(WORKER), str(folder)],
                             cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, **hidden())
    except OSError as exc:
        write(folder / "status.json", dict(state="failed", ok=False, heartbeat=time.time(), error=str(exc)))
    return status(job, tool)


def lock_resource(root, resource):
    """OS releases the lock even if a worker dies; no stale PID may be killed."""
    key = hashlib.sha256(os.path.normcase(str(Path(resource).resolve())).encode()).hexdigest()
    locks = root / ".locks"
    locks.mkdir(exist_ok=True)
    stream = (locks / key).open("a+b")
    stream.write(b"0")
    stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise ValueError(f"Another creation job is writing to {resource}") from None
    return stream


def stop_child(child):
    if child.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                       capture_output=True, timeout=15, **hidden())
    else:
        os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=15)


def supervise(folder):
    folder = Path(folder)
    request = read(folder / "request.json")
    lease, child = None, None
    state = dict(state="running", ok=None, pid=os.getpid(), started=time.time())
    try:
        if request.get("resource"):
            lease = lock_resource(folder.parent, request["resource"])
        if (folder / "cancel").exists():
            state.update(state="cancelled", ok=False)
            return
        child = subprocess.Popen([sys.executable, "-u", str(WORKER), "--execute", str(folder)],
                                 stdin=subprocess.DEVNULL, start_new_session=os.name != "nt", **hidden())
        cancelled_at = None
        while child.poll() is None:
            if (folder / "cancel").exists():
                cancelled_at = cancelled_at or time.monotonic()
                state["state"] = "cancelling"
                # The existing rigswap importer gets a chance to cancel and skip its vault save.
                if request["tool"] != "rigswap" or time.monotonic() - cancelled_at > 8:
                    stop_child(child)
            state["heartbeat"] = time.time()
            write(folder / "status.json", state)
            time.sleep(0.2)
        result = read(folder / "result.json") if (folder / "result.json").is_file() else {}
        ok = child.returncode == 0 and result.get("ok") is True
        state.update(state="cancelled" if cancelled_at else "succeeded" if ok else "failed",
                     ok=ok and not cancelled_at, exit_code=child.returncode)
    except Exception as exc:
        state.update(state="failed", ok=False, error=str(exc))
    finally:
        if child is not None and child.poll() is None:
            stop_child(child)
        if lease is not None:
            lease.close()
        state.update(heartbeat=time.time(), finished=time.time())
        write(folder / "status.json", state)
