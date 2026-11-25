"""CspRenderPool -- a pool of persistent HSDRawViewer `--csp-server` workers.

Bulk CSP generation otherwise spawns a fresh `HSDRawViewer.exe --csp` process
per costume; ~4s of every ~6s is fixed process + OpenGL startup, paid every time.
Each worker here keeps ONE process + GL context alive and renders costume after
costume off a shared queue, so that startup is paid once per worker instead of
once per costume (measured ~0.2s/job vs ~3.6s one-shot).
Workers start on first use; ready workers render while others initialize, so
there is no batch-wide startup barrier. Idle warm workers are reused first.

Crash-safe by design: a job that errors, times out, or a worker that dies makes
`render()` return False so the caller falls back to a one-shot `generate_csp`
(a single bad DAT never blocks the batch). Dead workers respawn on next use, and
every worker is recycled after N jobs to bound GPU/memory creep.

`render()` also verifies the output is a real portrait: under GPU/GL pressure
HSDRawViewer can enter a blank/T-pose failure mode where it keeps reporting
DONE while writing tiny fully-transparent PNGs (observed 2026-07-30: a 416-
costume batch produced 400+ blank ~179-byte portraits, all DONE). A blank
output returns False (one-shot fallback) and recycles the worker, since a
worker that blanked once keeps blanking until its process is replaced.

Protocol (see HSDRawViewer Program.cs RunCspServer): a worker prints "READY",
then per job we write a TAB-joined argv line ("--csp\t<dat>\t<output>\t...") and
read until "DONE\t<output>" / "ERR..." / "FATAL...".

Each worker process also writes csp_server_<pid>.log into the temp folder (the app's
data scratch) and holds it open while it runs. When a worker exits, the log is deleted
if every job it ran rendered, and kept as evidence if one failed (see processor/csp_logs.py;
0.9.0 smoke test: these logs were never removed).
"""
import contextlib
import logging
import os
import queue
import subprocess

from core.child_procs import own
from core.child_env import child_environment
from core.deadline_lines import DeadlineLineReader
import threading
import time

from shared.rendering.csp_concurrency import csp_workers, staggered_launch
from .render_checks import file_looks_blank

_CREATE_NO_WINDOW = 0x08000000
_READY_TIMEOUT = 60.0
_DEFAULT_JOB_TIMEOUT = 90.0


def _logs():
    """processor/csp_logs.py. The processor folder is on sys.path wherever this pool runs:
    core.config puts it there, and the standalone regression adds it before generate_csp."""
    import csp_logs
    return csp_logs


def _output_looks_blank(job_args):
    """True when a DONE render's output PNG is missing, tiny, or fully
    transparent -- HSDRawViewer's blank/T-pose failure mode. job_args is the
    `--csp` argv: ['--csp', <dat>, <output>, ...]. The rule itself is shared
    with the vault retake — see shared/rendering/render_checks.py."""
    try:
        out = job_args[2] if len(job_args) > 2 else None
        if not out:
            return False
        return file_looks_blank(out)
    except Exception:
        return False


class _Worker:
    def __init__(self, exe, idx, *, lazy=False):
        self.exe = str(exe)
        self.idx = idx
        self.proc = None
        self._reader = None
        self.jobs = 0
        self.lazy = lazy
        self.failed = False    # a job of the current process failed: keep its log
        self.log_dir = None    # where the current process writes csp_server_<pid>.log
        if not lazy:
            self._spawn()

    def _spawn(self):
        started = time.monotonic()
        flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
        self.failed = False
        self.log_dir = _logs().temp_dir()
        # Pool installation no longer means every worker is already warm.
        # Space actual starts, then wait for READY outside the launch guard so
        # other workers can initialize and ready workers can render meanwhile.
        with staggered_launch(force=True):
            self.proc = own(subprocess.Popen(
                [self.exe, "--csp-server"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, bufsize=1, creationflags=flags, env=child_environment(),
            ))
        self._reader = DeadlineLineReader(self.proc.stdout)
        deadline = time.monotonic() + _READY_TIMEOUT
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"csp worker {self.idx} did not become READY in time")
                line = self._reader.readline(remaining)
                if line is None:
                    raise RuntimeError(f"csp worker {self.idx} did not become READY in time")
                if not line:
                    raise RuntimeError(f"csp worker {self.idx} exited during startup")
                if line.strip() == "READY":
                    logging.getLogger(__name__).info(
                        "csp worker %s ready in %.2fs", self.idx, time.monotonic() - started)
                    return
        except Exception:
            self.failed = True
            self._kill_owned()
            raise

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def render(self, job_args, timeout):
        """job_args = the argv `--csp` takes (['--csp', dat, output, ...]).
        Returns True on DONE, False on ERR/FATAL/timeout/dead worker."""
        ok = self._render(job_args, timeout)
        if not ok:
            self.failed = True
        return ok

    def _render(self, job_args, timeout):
        if not self.alive():
            try:
                self._spawn()
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "csp worker %s startup failed: %s", self.idx, exc)
                return False
        try:
            self.proc.stdin.write("\t".join(job_args) + "\n")
            self.proc.stdin.flush()
        except Exception:
            self._kill_owned()
            return False
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill_owned()
                return False
            line = self._reader.readline(remaining)
            if line is None:
                self._kill_owned()
                return False
            if not line:
                return False  # worker died mid-job
            line = line.rstrip("\n")
            if line.startswith("DONE\t"):
                self.jobs += 1
                return True
            if line.startswith("ERR") or line.startswith("FATAL"):
                self.jobs += 1
                return False
            # ignore any stray line the worker might emit
    def _kill_owned(self):
        try:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass

    def recycle(self):
        self.close()
        self.jobs = 0
        if not self.lazy:
            self._spawn()

    def quit(self):
        """Ask the worker to exit (QUIT) without waiting. -> whether it was asked (``close(asked=...)``)."""
        try:
            if self.alive():
                self.proc.stdin.write("QUIT\n")
                self.proc.stdin.flush()
                return True
        except Exception:
            pass
        return False

    def close(self, asked=False):
        try:
            if self.alive():
                if not asked:
                    self.proc.stdin.write("QUIT\n")
                    self.proc.stdin.flush()
                self.proc.wait(timeout=3)
        except Exception:
            pass
        try:
            if self.alive():
                self.proc.kill()
        except Exception:
            pass
        self._reader = None
        self._drop_log()

    def _drop_log(self):
        """Once the worker process has exited: delete its csp_server_<pid>.log if every job
        it ran rendered, or keep it and say where if one failed. A process not yet gone (a
        kill still finishing) keeps its log for the backend's start sweep (csp_logs)."""
        proc, folder = self.proc, getattr(self, "log_dir", None)
        if proc is None or folder is None or proc.poll() is None:
            return
        self.log_dir = None   # this process's log is handled once
        logs = _logs()
        if getattr(self, "failed", False):
            logging.getLogger(__name__).warning(
                "csp worker %s had a failed job; its log is kept: %s",
                self.idx, logs.log_path(logs.SERVER, proc.pid, folder))
        else:
            logs.drop(logs.SERVER, proc.pid, folder)


class CspRenderPool:
    def __init__(self, exe, workers=None, recycle_after=50,
                 job_timeout=_DEFAULT_JOB_TIMEOUT):
        self.exe = str(exe)
        self.recycle_after = recycle_after
        self.job_timeout = job_timeout
        n = workers or csp_workers()
        # Prefer the last-used (warm) slot for small/sequential batches.
        self._idle = queue.LifoQueue()
        self._all = []
        for i in range(n):
            # Reserve slots without starting native processes. The first job
            # assigned to each slot starts it; no batch-wide READY barrier.
            # Batches that reuse ISO portraits never start a renderer at all.
            w = _Worker(self.exe, i, lazy=True)
            self._all.append(w)
            self._idle.put(w)

    @property
    def size(self):
        return len(self._all)

    def render(self, job_args) -> bool:
        """Render one costume. job_args is the argv `--csp` takes:
        ['--csp', <dat>, <output>, ...flags...]. Blocks until a worker is free
        (natural backpressure at `size` concurrent renders). Returns True only
        on a confirmed DONE; on any failure the caller should fall back."""
        w = self._idle.get()
        try:
            ok = w.render(list(job_args), self.job_timeout)
            blank = ok and _output_looks_blank(job_args)
            if blank:
                logging.getLogger(__name__).warning(
                    f"csp worker {w.idx}: DONE but output is blank -- "
                    "recycling worker, caller falls back to one-shot")
                ok = False
                w.failed = True   # its log is evidence of the blank failure mode
            if blank or (not w.alive()) or w.jobs >= self.recycle_after:
                try:
                    w.recycle()
                except Exception:
                    pass
            return ok
        finally:
            self._idle.put(w)

    def close(self):
        # Every worker asked to quit first, then each waited for: they shut down together, not one after another.
        asked = [w.quit() for w in self._all]
        for w, was in zip(self._all, asked):
            w.close(asked=was)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@contextlib.contextmanager
def active_pool(workers=None, enabled=None):
    """Stand up a CspRenderPool and install it as generate_csp's active pool for
    the duration of the block, so every costume rendered inside routes through a
    reused --csp-server worker instead of a one-shot process. Yields the pool (or
    None when disabled / unavailable -- callers then transparently get the
    one-shot path). Kill switch: MEX_CSP_SERVER=0.

    Wrap BATCH render loops in this (iso scan, texture-pack export, vanilla HD
    preseed) to reuse each worker across costumes. Single-costume renders
    (Retake CSP, one pose, an install endpoint) can keep their one-shot path.

    Worker slots are cheap and start on first use. Each actual process launch
    explicitly observes csp_concurrency's stagger even while the pool is active;
    warm workers can render immediately without waiting for the other slots.
    """
    # Lazy import: generate_csp pulls in the heavy HSDRaw stack, and it's on the
    # path in every backend caller of this module.
    import generate_csp

    if enabled is None:
        enabled = os.environ.get("MEX_CSP_SERVER", "1") != "0"

    pool = None
    if enabled:
        try:
            pool = CspRenderPool(generate_csp.HSDRAW_EXE, workers=workers)
            generate_csp.set_active_pool(pool)
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"CSP render pool unavailable ({e}); using one-shot renders")
            pool = None
    try:
        yield pool
    finally:
        if pool is not None:
            try:
                generate_csp.set_active_pool(None)
            except Exception:
                pass
            pool.close()
