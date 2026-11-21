"""The library passes do their CPU work in ONE worker process, never in the
process that serves requests.

The replay index, the combo extraction and the vault derive all walk .slp
files in pure Python. Run in the serving process they hold the GIL and the
disk for as long as the pass lasts, and every API call the UI makes queues
behind them -- measured on the live app during a vault sync: /stats went from
0.2s to 10-18s for the whole multi-hour run. It is worse than it sounds,
because the Tracker pages poll on 2s timers: once a poll takes longer than its
interval the requests pile up, and Chromium's six-connections-per-origin cap
means the NEXT thing the user clicks is not slow, it is not sent at all. That
is what made "Watch" sit on "Loading..." (the options call itself measures
~0ms). The combo pass is the one that bites now: combos._ensure_frame_basis
re-queues the whole library the first time a new build runs.

One worker, not a pool: pass throughput matters much less than the app staying
usable, and a single child keeps the memory cost of the spawn re-import to one
copy. The worker also drops to below-normal priority, so even on a busy
machine a background pass never outranks a request someone is waiting on.

Spawn-safe for the frozen build: app.py calls freeze_support() first thing
and skips its launch side effects under __mp_main__ (the py7zr fork-bomb and
the ~90-runaway-backends lessons). If the pool cannot start or dies, work
falls back inline -- a slower app, but the pass still completes.

    result = scan_pool.run(module_level_fn, *args)

`fn` must be importable by name in a spawned child and its arguments and
result must pickle. Prefer functions that RETURN their errors: an exception
raised in the child crosses back intact, but the infrastructure errors this
module latches on (BrokenProcessPool/OSError/RuntimeError) are ones a task
could plausibly raise too, and a task that raises OSError would wrongly
condemn the pool.

Set NUCLEUS_SCAN_INPROC=1 to keep everything inline (tests, debugging).
"""
import atexit
import logging
import multiprocessing
import os
import threading

logger = logging.getLogger(__name__)

_pool = None
_broken = False          # latched: one spawn failure, no retry storm
_lock = threading.Lock()


# One class DOWN from whatever the backend itself is running at — not a fixed
# BELOW_NORMAL. Measured 2026-09-11: the backend is already BELOW_NORMAL when
# launched from run.bat (the class is inherited, and the worker inherits it
# too), so pinning the worker to BELOW_NORMAL would have left it exactly level
# with the requests it is supposed to yield to.
_NEXT_PRIORITY_DOWN = {
    0x00000080: 0x00000020,   # HIGH          -> NORMAL
    0x00000020: 0x00004000,   # NORMAL        -> BELOW_NORMAL
    0x00004000: 0x00000040,   # BELOW_NORMAL  -> IDLE
    0x00000040: 0x00000040,   # IDLE          -> IDLE
}


def _deprioritise():
    """Drop the worker below the backend in the OS scheduler."""
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
            k32.GetPriorityClass.restype = ctypes.c_uint
            k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.SetPriorityClass.restype = ctypes.c_int
            me = k32.GetCurrentProcess()
            # inherited from the backend, so this IS the backend's class
            want = _NEXT_PRIORITY_DOWN.get(k32.GetPriorityClass(me), 0x00000040)
            k32.SetPriorityClass(me, want)
        else:
            # nice is relative and inherited, so this is already "below the
            # parent" on POSIX
            os.nice(10)
    except Exception:                                         # noqa: BLE001
        logger.debug("scan_pool: could not lower worker priority", exc_info=True)


def _init_worker(ppid):
    """ProcessPoolExecutor initializer, run once in the child."""
    from core.child_procs import worker_watchdog
    # the watchdog is the worker's only tie to us: a dead backend otherwise
    # leaves it blocked on the call queue forever
    worker_watchdog(ppid)
    _deprioritise()


def _shutdown():
    """Registered when the pool is first built, so it runs BEFORE
    concurrent.futures' own atexit join (atexit is LIFO) and the backend does
    not wait on a queue of work it is about to abandon."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def inproc():
    return os.environ.get("NUCLEUS_SCAN_INPROC") == "1"


class _Inline:
    """A burst that has no pool of its own: every job goes through run(),
    i.e. the shared worker (or inline). Same interface as _Burst."""

    workers = 1

    def submit(self, fn, *args):
        return _Done(run, fn, *args)


class _Done:
    """Deferred run(): computed on .result(), so an inline burst still does
    its work lazily and in the order it is consumed."""

    def __init__(self, runner, fn, *args):
        self._call = (runner, fn, args)

    def result(self):
        runner, fn, args = self._call
        return runner(fn, *args)

    def cancel(self):
        return True


class _Job:
    def __init__(self, future, fn, args):
        self._future, self._fn, self._args = future, fn, args

    def result(self):
        global _broken
        from concurrent.futures.process import BrokenProcessPool
        try:
            return self._future.result()
        except (BrokenProcessPool, OSError, RuntimeError):
            # Same latch and same caveat as run(): a burst worker dying (or a
            # child that cannot start) must cost speed, never the pass.
            _broken = True
            logger.warning("scan_pool: burst worker unavailable, running %s inline",
                           getattr(self._fn, "__name__", self._fn), exc_info=True)
            return self._fn(*self._args)

    def cancel(self):
        return self._future.cancel()


class _Burst:
    def __init__(self, pool, workers):
        self._pool, self.workers = pool, workers

    def submit(self, fn, *args):
        if _broken:
            return _Done(lambda f, *a: f(*a), fn, *args)
        try:
            return _Job(self._pool.submit(fn, *args), fn, args)
        except RuntimeError:
            # submit after a broken pool raises BrokenProcessPool (a
            # RuntimeError); fall back per job like _Job.result does
            return _Done(lambda f, *a: f(*a), fn, *args)


class burst:
    """A TEMPORARY pool of `workers` processes for one throughput-bound pass.

        with scan_pool.burst(4) as pool:
            jobs = [pool.submit(fn, path) for path in paths]
            for job in jobs:
                value = job.result()

    Exists for the vault upload (bug-report: a 44k-game library took ~15h at
    ~1.1 s/game, almost all of it deriving one game at a time in the single
    shared worker). It keeps every rule the shared worker has -- spawn
    context, the parent watchdog, one priority class BELOW the backend, and
    NOTHING runs in the serving process -- it only runs more than one child,
    and only for as long as the `with` block lasts: on exit the children are
    shut down, so the app's steady state is still one worker.

    workers <= 1, NUCLEUS_SCAN_INPROC=1 or a latched-broken pool degrade to the
    shared worker via run(), so callers need no second code path.
    """

    def __init__(self, workers):
        self.workers = max(1, int(workers or 1))
        self._pool = None

    def __enter__(self):
        if self.workers <= 1 or _broken or inproc():
            return _Inline()
        from concurrent.futures import ProcessPoolExecutor
        try:
            self._pool = ProcessPoolExecutor(
                max_workers=self.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_init_worker, initargs=(os.getpid(),))
        except (OSError, RuntimeError, ValueError):
            logger.warning("scan_pool: burst pool unavailable", exc_info=True)
            return _Inline()
        return _Burst(self._pool, self.workers)

    def __exit__(self, *exc):
        pool, self._pool = self._pool, None
        if pool is not None:
            # never wait on derives nobody will read (a cancelled sync); the
            # watchdog covers a backend that exits before these do
            pool.shutdown(wait=False, cancel_futures=True)
        return False


def run(fn, *args):
    """Run `fn(*args)` in the shared worker process; inline if unavailable."""
    global _pool, _broken
    if _broken or inproc():
        return fn(*args)
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool
    try:
        with _lock:
            if _pool is None:
                _pool = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_init_worker, initargs=(os.getpid(),))
                atexit.register(_shutdown)
            pool = _pool
        return pool.submit(fn, *args).result()
    except (BrokenProcessPool, OSError, RuntimeError):
        # e.g. a __main__ that cannot be re-imported under spawn. Latch it:
        # retrying would fail once per file, each attempt leaking a doomed
        # child.
        _broken = True
        _shutdown()
        logger.warning("scan_pool: worker unavailable, running %s inline",
                       getattr(fn, "__name__", fn), exc_info=True)
        return fn(*args)
