import io
import subprocess
import sys
from contextlib import nullcontext
import threading
import time

import pytest

import shared.rendering.csp_pool as csp_pool
from core.deadline_lines import DeadlineLineReader


class SilentPipe:
    def __init__(self):
        self.released = threading.Event()

    def readline(self):
        self.released.wait()
        return ''


class OneLineThenSilent(SilentPipe):
    def __init__(self, line):
        super().__init__()
        self.line = line

    def readline(self):
        if self.line is not None:
            line, self.line = self.line, None
            return line
        return super().readline()


class FakeProcess:
    def __init__(self, pipe=None):
        self.stdout = pipe or SilentPipe()
        self.stdin = io.StringIO()
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.released.set()

    def wait(self, timeout=None):
        return self.returncode


def test_silent_worker_startup_obeys_deadline_and_kills_owned_child(monkeypatch):
    proc = FakeProcess()
    monkeypatch.setattr(csp_pool, '_READY_TIMEOUT', 0.02)
    monkeypatch.setattr(csp_pool.subprocess, 'Popen', lambda *args, **kwargs: proc)
    monkeypatch.setattr(csp_pool, 'own', lambda child: child)
    monkeypatch.setattr(csp_pool, 'staggered_launch', lambda **_: nullcontext())
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='READY in time'):
        csp_pool._Worker('fake-viewer', 0)
    assert time.monotonic() - started < 0.5
    assert proc.killed is True


def test_silent_mid_job_obeys_deadline_and_retires_worker():
    proc = FakeProcess()
    worker = csp_pool._Worker.__new__(csp_pool._Worker)
    worker.proc = proc
    worker._reader = DeadlineLineReader(proc.stdout)
    worker.jobs = 0
    worker.idx = 0
    assert worker.render(['--csp', 'in.dat', 'out.png'], 0.02) is False
    assert proc.killed is True


def test_stray_worker_output_does_not_extend_job_deadline():
    proc = FakeProcess(OneLineThenSilent('diagnostic noise\n'))
    worker = csp_pool._Worker.__new__(csp_pool._Worker)
    worker.proc = proc
    worker._reader = DeadlineLineReader(proc.stdout)
    worker.jobs = 0
    worker.idx = 0
    assert worker.render(['--csp', 'in.dat', 'out.png'], 0.02) is False
    assert proc.killed is True


def test_silent_child_obeys_deadline_and_kills_only_its_child():
    """A wedged subprocess is bounded by DeadlineLineReader and only its own child dies."""
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             stdout=subprocess.PIPE, text=True)
    reader = DeadlineLineReader(child.stdout)
    try:
        started = time.monotonic()
        assert reader.readline(0.05) is None
        assert time.monotonic() - started < 5
    finally:
        child.kill()
        child.wait(timeout=10)
    assert child.returncode is not None
