"""Tasks the scan_pool tests send to a real worker process. A spawned worker
imports them by name, so they live in a module of their own (not collected:
the name does not start with test_)."""
import os
import time


def pid(path):
    return os.getpid()


def echo(path, delay=0.0):
    time.sleep(delay)
    return os.path.basename(path)


def touch_then(path, marker):
    """Leaves `marker` behind, so a test can tell the task never ran."""
    with open(marker, "w") as f:
        f.write(str(os.getpid()))
    return "ran"


def crash(path):
    """Dies like peppi_py does on a crafted replay: no exception, no cleanup."""
    os._exit(0xC00000FD & 0xFF)


def crash_if_bad(path):
    if os.path.basename(path).startswith("bad"):
        crash(path)
    return os.path.basename(path)


def hang(path):
    with open(path + ".pid", "w") as f:
        f.write(str(os.getpid()))
    time.sleep(600)


def raise_oserror(path):
    raise OSError(f"the task's own error for {os.path.basename(path)}")
