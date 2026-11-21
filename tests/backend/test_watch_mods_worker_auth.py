"""The build worker has to authenticate to itself.

app.py's require_backend_token() 401s every /api route that arrives without a
matching X-Nucleus-Token, and _Worker drives its worker entirely over /api. It
sent no header at all, so watch-with-mods died on its own readiness probe: the
worker booted and served, the parent got 401 once a second for 60 seconds, and
the job failed with "build worker REST never became ready". Reported from the
wild against 0.8.4 (report f51b6ce8: "unable to play a replay when I choose any
custom skin"); the gate landed in 0.8.0, so every release since had it. A plain
watch with no selections never spawns a worker, which is why unmodded replays
kept working and hid it.

Inheriting the env is NOT enough: this process may have been handed its token
by Electron or generated its own, and a worker left to generate its own would
pick a different one. The worker is therefore given a token we choose.
"""
import threading
import time

import pytest

from tracker.replays import watch_mods


class _Resp:
    """Enough of a requests.Response for _Worker.api()."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"success": True}


class _FakeStdout:
    """The worker's piped stdout: yields `lines`, then optionally blocks.

    Blocking matters — _await_port reads on a thread precisely because a real
    `for line in stdout` never returns for a child that prints nothing.
    """

    def __init__(self, lines, block_s=0):
        self._lines = list(lines)
        self._block_s = block_s

    def __iter__(self):
        for line in self._lines:
            yield line
        if self._block_s:
            threading.Event().wait(self._block_s)


class _FakeProc:
    def __init__(self, lines, block_s=0):
        self.stdout = _FakeStdout(lines, block_s)
        self.killed = False

    def poll(self):
        return -9 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return -9


@pytest.fixture
def spawned(monkeypatch):
    """Capture the Popen kwargs and every request _Worker makes."""
    captured = {"popen": None, "requests": []}

    def fake_popen(cmd, **kwargs):
        captured["popen"] = kwargs
        return _FakeProc(["BACKEND_PORT:51234\n"])

    def fake_request(method, url, **kwargs):
        captured["requests"].append({"method": method, "url": url, **kwargs})
        return _Resp()

    monkeypatch.setattr(watch_mods.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(watch_mods.requests, "request", fake_request)
    return captured


def test_api_sends_the_backend_token(spawned):
    worker = watch_mods._Worker()
    worker.port = 51234
    worker.api("POST", "/api/mex/project/open", {"projectPath": "x"})

    sent = spawned["requests"][-1]
    assert sent["headers"]["X-Nucleus-Token"] == worker.token
    assert worker.token, "a worker without a token would 401 on every call"


def test_start_hands_the_worker_that_same_token(spawned):
    worker = watch_mods._Worker()
    worker.start()

    env = spawned["popen"]["env"]
    assert env["NUCLEUS_BACKEND_TOKEN"] == worker.token
    # the worker must not run the startup sweep: it empties output/artifacts,
    # where a finished export in the MAIN app is waiting to be saved
    assert env["NUCLEUS_WORKER"] == "1"
    # the readiness probe is the call that used to 401 forever
    probe = spawned["requests"][0]
    assert probe["url"].endswith("/api/mex/status")
    assert probe["headers"]["X-Nucleus-Token"] == worker.token


def test_each_worker_gets_its_own_token():
    assert watch_mods._Worker().token != watch_mods._Worker().token


def test_await_port_gives_up_on_a_silent_worker(monkeypatch):
    """A worker that prints nothing must time out, not hang forever.

    The elapsed-time assertion is the point: returning None *eventually* is
    what the old inline loop did too (it blocked until the pipe closed), so a
    test that only checked the value would pass without the timed join.
    """
    monkeypatch.setattr(watch_mods, "WORKER_BOOT_TIMEOUT_S", 0.2)
    worker = watch_mods._Worker()
    worker.proc = _FakeProc([], block_s=30)

    started = time.monotonic()
    port, error = worker._await_port()
    elapsed = time.monotonic() - started

    assert port is None
    assert elapsed < 5, f"waited {elapsed:.1f}s on a silent worker"
    assert error is None


def test_await_port_reads_the_announced_port(monkeypatch):
    monkeypatch.setattr(watch_mods, "WORKER_BOOT_TIMEOUT_S", 5)
    worker = watch_mods._Worker()
    worker.proc = _FakeProc(["Checking for legacy character names...\n",
                             "BACKEND_PORT:51234\n"], block_s=30)

    assert worker._await_port() == (51234, None)


def test_await_port_carries_back_a_reader_failure(monkeypatch):
    """A malformed port line must name itself, not vanish in the thread."""
    monkeypatch.setattr(watch_mods, "WORKER_BOOT_TIMEOUT_S", 5)
    worker = watch_mods._Worker()
    worker.proc = _FakeProc(["BACKEND_PORT:not-a-number\n"])

    port, error = worker._await_port()
    assert port is None
    assert "ValueError" in error


def test_readiness_probe_is_not_given_the_five_minute_default(spawned):
    """A worker that accepts the connection then stalls must not hold the job
    for 300 s per attempt — the probe needs its own short timeout."""
    worker = watch_mods._Worker()
    worker.start()

    probe = spawned["requests"][0]
    assert probe["url"].endswith("/api/mex/status")
    assert probe["timeout"] <= 10


def test_start_ties_the_worker_to_this_backend(spawned, monkeypatch):
    """A backend crash must not leave a second backend building into the data
    folder: the worker is owned (core.child_procs)."""
    tied = []
    monkeypatch.setattr(watch_mods, "own", lambda proc: tied.append(proc) or proc)
    worker = watch_mods._Worker()
    worker.start()
    assert tied == [worker.proc]
