"""HSDRawViewer's per-process debug logs, and keeping them from piling up.

Our HSDRawViewer fork (Program.cs) opens one log per process in GetTempPath(). The app points
that at its data scratch: core/config.py sets TMP/TEMP/TMPDIR, which every child inherits.

    a one-shot ``--csp`` render     csp_debug_<pid>.log    (the same lines it prints to stdout)
    a ``--csp-server`` pool worker  csp_server_<pid>.log   (held open while the worker runs)

Nothing removed them. The 0.9.0 smoke test found 195 csp_debug and 211 csp_server logs
(150 MB) going back to 09-10 in the data scratch, and a few more every session. Now:

  - ``drop``: once a process that rendered cleanly has exited, its log is deleted
    (generate_csp's one-shot renders, csp_pool's workers). A failed render keeps its log as
    the evidence for a bug report, and the caller logs where it is.
  - ``sweep``: the backend's start deletes logs older than ``MAX_AGE_DAYS`` and all but the
    newest ``KEEP``: failed renders' logs, and those of workers killed when the app closed.

A log that a running renderer still holds is never deleted. Windows refuses to delete an
open file (that error is ignored); on other systems a log whose pid is alive is skipped.
Stdlib only: the standalone processor tools import this too.
"""
import os
import re
import tempfile
import time
from pathlib import Path

DEBUG = 'csp_debug_'     # one-shot --csp render
SERVER = 'csp_server_'   # --csp-server pool worker
MAX_AGE_DAYS = 3
KEEP = 50
_NAME = re.compile(r'^csp_(?:debug|server)_(\d+)\.log$', re.IGNORECASE)


def temp_dir(environ=None):
    """The folder a renderer started now resolves GetTempPath() to. .NET reads TMP, TEMP, then
    USERPROFILE on Windows, and TMPDIR (else /tmp) elsewhere."""
    env = os.environ if environ is None else environ
    for key in (('TMP', 'TEMP', 'USERPROFILE') if os.name == 'nt' else ('TMPDIR',)):
        if env.get(key):
            return Path(env[key])
    return Path(tempfile.gettempdir()) if os.name == 'nt' else Path('/tmp')


def log_path(prefix, pid, folder):
    """Where the renderer process ``pid`` writes its log (``prefix`` is DEBUG or SERVER)."""
    return Path(folder) / f'{prefix}{pid}.log'


def drop(prefix, pid, folder):
    """Delete the log of a renderer process that has exited. -> whether it is gone. Never
    raises: a log that cannot go now (still held open) is left for ``sweep``."""
    try:
        log_path(prefix, pid, folder).unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _pid_alive(pid):
    """POSIX only. On Windows os.kill would TERMINATE the process, and the open-file
    refusal already protects a running renderer's log there."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # alive, owned by someone else
    except OSError:
        return False
    return True


def sweep(folder=None, max_age_days=MAX_AGE_DAYS, keep=KEEP, now=None):
    """Delete renderer logs in ``folder`` (default: the renderer temp folder) older than
    ``max_age_days`` and all but the newest ``keep``. -> how many went."""
    root = Path(folder) if folder is not None else temp_dir()
    logs = []
    try:
        candidates = list(root.glob('csp_*.log'))
    except OSError:
        return 0
    for entry in candidates:
        match = _NAME.match(entry.name)
        if not match:
            continue
        try:
            logs.append((entry.stat().st_mtime, int(match.group(1)), entry))
        except OSError:
            continue   # gone meanwhile
    logs.sort(key=lambda item: item[0], reverse=True)
    cutoff = (time.time() if now is None else now) - max_age_days * 86400
    gone = 0
    for index, (mtime, pid, entry) in enumerate(logs):
        if index < keep and mtime > cutoff:
            continue
        if os.name != 'nt' and _pid_alive(pid):
            continue
        try:
            entry.unlink()
        except OSError:
            continue   # held open by a running renderer (Windows), or already gone
        gone += 1
    return gone
