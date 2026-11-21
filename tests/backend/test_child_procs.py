"""core.child_procs — owned children die with the backend.

Each test spawns a throwaway *parent* python process that owns a child, kills
the parent hard (TerminateProcess / SIGKILL — no atexit, no handlers), and
asserts the child is gone shortly after. That is the exact failure of
2026-08-23: a derive worker and another helper outliving a dead backend by a day.
"""
from tests.paths import BACKEND
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow



def _alive(pid):
    if os.name == "nt":
        from core import child_procs as cp
        h = cp._k32.OpenProcess(cp._SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return cp._k32.WaitForSingleObject(h, 0) != 0     # not signaled = still running
        finally:
            cp._k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # reparented to init and reaped -> ProcessLookupError above; a zombie that
    # init hasn't reaped yet still answers kill(0), so also check /proc state
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def _wait_gone(pid, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.2)
    return not _alive(pid)


def _run_parent(tmp_path, body):
    """Write a parent script, start it, return (proc, first stdout line)."""
    script = tmp_path / "parent.py"
    script.write_text(textwrap.dedent(f"""
        import os, sys, subprocess, time
        sys.path.insert(0, {str(BACKEND)!r})
        {textwrap.indent(textwrap.dedent(body), '        ').lstrip()}
    """), encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline().strip()
    assert line, f"parent produced no pid (rc={proc.poll()})"
    return proc, int(line)


def _kill_hard(proc):
    proc.kill()           # TerminateProcess on Windows, SIGKILL elsewhere
    proc.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="the job-object tie is Windows-only; POSIX relies on the atexit sweep")
def test_owned_child_dies_with_hard_killed_parent(tmp_path):
    parent, child_pid = _run_parent(tmp_path, """
        from core.child_procs import own
        child = own(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"]))
        print(child.pid, flush=True)
        time.sleep(120)
    """)
    try:
        assert _alive(child_pid)
        _kill_hard(parent)
        assert _wait_gone(child_pid, timeout=5), f"child {child_pid} outlived its parent"
    finally:
        if _alive(child_pid):
            subprocess.run(["taskkill", "/F", "/PID", str(child_pid)], capture_output=True)


@pytest.mark.skipif(os.name != "nt", reason="job-object tie is Windows-only")
def test_grandchildren_die_too(tmp_path):
    """a helper's runner processes are grandchildren; the job covers them."""
    parent, grandchild_pid = _run_parent(tmp_path, """
        from core.child_procs import own
        child = own(subprocess.Popen([sys.executable, "-c",
            "import subprocess, sys, time; g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); print(g.pid, flush=True); time.sleep(120)"],
            stdout=subprocess.PIPE, text=True))
        print(child.stdout.readline().strip(), flush=True)
        time.sleep(120)
    """)
    try:
        assert _alive(grandchild_pid)
        _kill_hard(parent)
        assert _wait_gone(grandchild_pid, timeout=5), f"grandchild {grandchild_pid} outlived the backend"
    finally:
        if _alive(grandchild_pid):
            subprocess.run(["taskkill", "/F", "/PID", str(grandchild_pid)], capture_output=True)


def test_pool_worker_exits_when_parent_dies(tmp_path):
    """The vault-sync derive worker: a multiprocessing spawn child with the
    watchdog initializer. Works on every platform (no job object involved)."""
    parent, worker_pid = _run_parent(tmp_path, """
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing
        from core.child_procs import worker_watchdog
        if __name__ == "__main__":
            pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                                       initializer=worker_watchdog, initargs=(os.getpid(),))
            print(pool.submit(os.getpid).result(), flush=True)
            time.sleep(120)
    """)
    try:
        assert _alive(worker_pid)
        _kill_hard(parent)
        # Windows: handle wait fires at once. POSIX: getppid poll, 1s period.
        assert _wait_gone(worker_pid, timeout=8), f"pool worker {worker_pid} outlived its parent"
    finally:
        if _alive(worker_pid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(worker_pid)], capture_output=True)
            else:
                os.kill(worker_pid, 9)


def test_sweep_terminates_owned_children():
    from core import child_procs as cp
    child = cp.own(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"]))
    assert child.pid in cp.owned_pids()
    cp.sweep(grace=3.0)
    assert child.poll() is not None
    assert child.pid not in cp.owned_pids()
