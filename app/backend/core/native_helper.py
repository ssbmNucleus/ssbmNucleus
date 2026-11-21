"""One bounded run of the headless HSDRaw helper (``config.HSDRAW_EXE``).

Moved here from the retired ``assistant/model_import.py``; the clone recolors
(``vault/echo/clone.py``) use it.
"""
import os
import subprocess
from pathlib import Path


def native_run(args):
    """Bounded headless import; timeout cleanup can only target our own child."""
    import psutil
    from core import config
    executable = Path(config.HSDRAW_EXE).resolve()
    proc = subprocess.Popen([str(executable), *map(str, args)], stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', **config.get_subprocess_args())
    def identity():
        child = psutil.Process(proc.pid)
        return child.pid, child.create_time(), child.ppid(), Path(child.exe()).resolve()
    try:
        owned = identity()
    except psutil.NoSuchProcess:
        output, _ = proc.communicate()
        return proc.returncode, output
    if owned[2:] != (os.getpid(), executable):
        raise RuntimeError('Native helper identity could not be verified; no cleanup attempted.')
    try:
        output, _ = proc.communicate(timeout=90)
    except subprocess.TimeoutExpired as exc:
        if proc.poll() is None:
            if identity() != owned:
                raise RuntimeError('Native helper identity changed; no cleanup attempted.') from exc
            proc.kill()
        proc.communicate()
        raise ValueError('Native draft export exceeded 90 seconds. The fitted previews are retained; no DAT was reported as exported.') from exc
    return proc.returncode, output
