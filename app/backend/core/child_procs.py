"""Children that must not outlive the backend.

The backend spawns long-lived helpers — the persistent CSP
render pool, HSDRawViewer sessions, the vault-sync derive worker, and the
xdelta3 and MexCLI export processes jobs run (a job's recovery at the next
start must not race a helper still writing its files). On
2026-08-23 a derive worker and another helper were found
still running a day after the backend that spawned them had died: they held
log files and a cwd inside the repo. Nothing tied them to their parent.

    own(proc)               tie a subprocess.Popen child to this process
    worker_watchdog(ppid)   ProcessPoolExecutor initializer: the worker exits
                            when its parent dies (use with os.getpid())
    sweep()                 terminate every owned child (runs at atexit)
    own_group(), stop_tree(proc)   end one child and what it started (a
                            timeout), by its PID or its own process group

How the tie works:
  Windows  a Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The only handle
           lives in this process, so when it dies for ANY reason — crash,
           ``taskkill /F``, normal exit — the OS closes the job and kills every
           process assigned to it, grandchildren included. This is the case that actually leaked.
  POSIX    the atexit sweep (app.py's SIGTERM/SIGINT handlers sys.exit, which runs it). A SIGKILLed backend still leaks on macOS
           and Linux; prctl(PR_SET_PDEATHSIG) would close that on Linux but it
           needs ``preexec_fn``, which is documented unsafe in a threaded
           process (this one), so it is deliberately not used.
  workers  a daemon thread in the child waits on the parent (handle wait on
           Windows, getppid poll elsewhere) and ``os._exit``s. This is the only
           tie a ``multiprocessing`` spawn worker gets: ProcessPoolExecutor has
           no parent-death handling of its own.

Dolphin is deliberately NEVER owned. Nucleus shares one Dolphin with the
harness and with the user's own launches (docs: "Dolphin sharing lock");
killing it with the backend would be wrong every time.
"""
import atexit
import logging
import os
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_owned = []                 # Popen objects, for the sweep
_job = None                 # Windows job handle; stays open for our lifetime
_job_failed = False         # latched: warn once, don't retry per spawn


# --- Windows job object -----------------------------------------------------

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JobObjectExtendedLimitInformation = 9
    _SYNCHRONIZE = 0x00100000
    _INFINITE = 0xFFFFFFFF

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _get_job():
        """The one kill-on-close job for this process, created on first use."""
        global _job, _job_failed
        if _job is not None or _job_failed:
            return _job
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            _job_failed = True
            logger.warning("child_procs: CreateJobObject failed (%d); children will only be swept on clean exit",
                           ctypes.get_last_error())
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info)):
            _job_failed = True
            logger.warning("child_procs: SetInformationJobObject failed (%d)", ctypes.get_last_error())
            return None
        _job = job
        return job

    def _assign(proc):
        job = _get_job()
        if job is None:
            return False
        handle = getattr(proc, "_handle", None)
        if handle is None:
            return False
        if not _k32.AssignProcessToJobObject(job, int(handle)):
            # ERROR_ACCESS_DENIED (5) = the child is already in a job that
            # forbids nesting (pre-Win8 hosts). Nothing to do about it here.
            logger.warning("child_procs: could not assign pid %s to the job (%d)",
                           proc.pid, ctypes.get_last_error())
            return False
        return True

    def _wait_for_parent(ppid):
        handle = _k32.OpenProcess(_SYNCHRONIZE, False, ppid)
        if handle:
            _k32.WaitForSingleObject(handle, _INFINITE)
            return
        _poll_parent(ppid)

else:
    def _assign(proc):
        return False

    def _wait_for_parent(ppid):
        _poll_parent(ppid)


def _poll_parent(ppid):
    """Fallback parent wait: the parent is gone once getppid() changes (POSIX
    reparents orphans) or, on Windows without a handle, once nothing answers."""
    import time
    while True:
        time.sleep(1.0)
        if os.name == "nt":
            try:
                h = _k32.OpenProcess(_SYNCHRONIZE, False, ppid)
            except Exception:
                return
            if not h:
                return
            signaled = _k32.WaitForSingleObject(h, 0) == 0   # WAIT_OBJECT_0 = exited
            _k32.CloseHandle(h)
            if signaled:
                return
        elif os.getppid() != ppid:
            return


# --- public API ------------------------------------------------------------

def own(proc):
    """Tie a subprocess.Popen child to this process's lifetime. Returns proc.

    Never call this on Dolphin.
    """
    with _lock:
        # Forget children that have been waited on, so one per job does not pile up.
        _owned[:] = [p for p in _owned if getattr(p, "returncode", None) is None]
        _owned.append(proc)
    tied = _assign(proc)
    logger.debug("child_procs: owning pid %s (%s)", getattr(proc, "pid", None), "job" if tied else "sweep-only")
    return proc


def worker_watchdog(ppid):
    """ProcessPoolExecutor/multiprocessing initializer: exit this worker as soon
    as the parent (``ppid``) is gone. Pass ``initargs=(os.getpid(),)``."""
    def _run():
        _wait_for_parent(ppid)
        os._exit(0)
    threading.Thread(target=_run, name="parent-watchdog", daemon=True).start()


def sweep(grace=2.0):
    """Terminate every owned child that is still running (kill after ``grace``)."""
    with _lock:
        procs = list(_owned)
        _owned.clear()
    live = [p for p in procs if p.poll() is None]
    for p in live:
        try:
            p.terminate()
        except Exception:
            pass
    for p in live:
        try:
            p.wait(timeout=grace)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def own_group():
    """Popen arguments for a child whose whole tree :func:`stop_tree` may have to end: on macOS and Linux it
    leads a session of its own (so its process group is its tree); Windows ends the tree by the child's PID."""
    return {} if os.name == "nt" else {"start_new_session": True}


def stop_tree(proc):
    """End ``proc`` and everything it started, by its own PID (Windows ``taskkill /PID <pid> /T /F``) or its own
    process group (started with :func:`own_group`). Never by image name. Safe on a child that has already ended."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception as e:  # noqa: BLE001 - the kill below still runs
        logger.warning("child_procs: could not stop the tree of pid %s: %s", proc.pid, e)
    try:
        proc.kill()
    except Exception:
        pass


def owned_pids():
    """Pids of owned children still running (diagnostics / tests)."""
    with _lock:
        return [p.pid for p in _owned if p.poll() is None]


atexit.register(sweep)

