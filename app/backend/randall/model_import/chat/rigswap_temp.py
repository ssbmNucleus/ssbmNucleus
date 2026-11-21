"""rigswap's temp folder: one per run, removed when the run ends, and the start's sweep of what earlier runs left.

rigswap and the tools it runs (Blender 4, HSDRawViewer) put their temp files wherever TMPDIR, TEMP and TMP point, and
in the app those name the data folder's scratch (core/config.py), every feature's temp folder. A run that ends by
itself cleans up after itself; one that is stopped (the user's Stop or Cancel, the watchdog) cannot, since rigswap and
Blender are ended by PID or process group. 0.9.0 build 4 smoke (macOS): each cancelled import left an empty Blender
session folder (``blender_<6>``), rigswap's Blender script (``tmp<8>.py``, its plugins/melee/export/write.py
``_blender4``) and ``tmpctx*`` folders in the scratch. Now:

* ``make``: each run gets a folder of its own, ``<scratch>/rigswap-tmp-<8>``, and rigswap's TMPDIR, TEMP and TMP name
  it (``import_job._environment``), as rigswap's own loop does for its runs. ``remove`` deletes it once rigswap has
  ended, however it ended (done, failed, stopped), trying again for a few seconds while a stopped process still holds
  a file (Windows will not delete an open one). The import's project folder (its work files and job log) is a record
  and stays. rigswap's send turns (rigswap/ai.py ``TURNS_DIR``, under the temp folder) are then each run's own.
* ``sweep``: the backend's start removes what earlier runs left in the scratch, matched by exact shape only, never a
  plain ``tmp*`` (other features' temp files have that shape): a run folder that is not live in this process (a
  backend that died mid-import), and the loose leftovers of runs from before run folders: an empty Blender session
  folder, a ``tmp<8>.py`` that is a Blender script (it imports bpy), and a ``tmpctx*`` folder.
"""
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

PREFIX = 'rigswap-tmp-'
REMOVE_WAIT = 5.0      # seconds ``remove`` keeps trying while a stopped run's processes let go of their files
REMOVE_GAP = 0.25
# The shapes ``sweep`` removes. A run folder: tempfile.mkdtemp's eight characters after PREFIX. Blender's session
# folder: blender_XXXXXX through mkdtemp (macOS, Linux) or _mktemp_s (Windows: a letter and five digits), removed only
# when empty. rigswap's Blender script: NamedTemporaryFile(suffix='.py'), its first lines import bpy.
_RUN = re.compile(r'^rigswap-tmp-[a-z0-9_]{8}$')
_BLENDER = re.compile(r'^blender_[A-Za-z0-9]{6}$')
_SCRIPT = re.compile(r'^tmp[a-z0-9_]{8}\.py$')
_CONTEXT = re.compile(r'^tmpctx[A-Za-z0-9_]*$')
_SCRIPT_HEAD = 512     # bytes of a tmp<8>.py read for its ``import bpy``

_live = set()          # names of this process's run folders while their runs go
_lock = threading.Lock()
_log = logging.getLogger(__name__)


def make(parent=None):
    """A fresh run folder in ``parent`` (default: the data scratch), live until ``remove``. None when it cannot be
    made: rigswap then uses the app's temp folder, as before."""
    try:
        folder = Path(tempfile.mkdtemp(prefix=PREFIX, dir=parent))
    except OSError:
        _log.warning('rigswap: no temp folder of its own for this run', exc_info=True)
        return None
    with _lock:
        _live.add(folder.name)
    return folder


def remove(folder, wait=REMOVE_WAIT):
    """Delete a run folder once its run has ended. -> whether it is gone (one that is not stays for the next
    start's ``sweep``)."""
    if folder is None:
        return True
    folder = Path(folder)
    deadline = time.monotonic() + wait
    while True:
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists() or time.monotonic() >= deadline:
            break
        time.sleep(REMOVE_GAP)
    with _lock:
        _live.discard(folder.name)
    gone = not folder.exists()
    if not gone:
        _log.warning('rigswap: its temp folder %s could not be removed yet; the next start removes it', folder)
    return gone


def _is_link(entry):
    isjunction = getattr(entry, 'is_junction', None)      # os.DirEntry.is_junction: Python 3.12+
    return entry.is_symlink() or bool(isjunction and isjunction())


def _blender_script(path):
    try:
        with open(path, 'rb') as stream:
            return b'import bpy' in stream.read(_SCRIPT_HEAD)
    except OSError:
        return False


def sweep(folder=None):
    """At the backend's start: what earlier model imports left in ``folder`` (default: the data scratch), by exact
    shape (the module's docstring). A run folder live in this process is never touched. -> how many went."""
    root = Path(folder) if folder is not None else Path(tempfile.gettempdir())
    with _lock:
        live = set(_live)
    try:
        with os.scandir(root) as listing:
            entries = list(listing)
    except OSError:
        return 0
    gone = 0
    for entry in entries:
        name = entry.name
        try:
            if _is_link(entry):
                continue
            if _RUN.match(name) and entry.is_dir() and name not in live:
                shutil.rmtree(entry.path, ignore_errors=True)
            elif _BLENDER.match(name) and entry.is_dir():
                os.rmdir(entry.path)                # only when empty: a session folder with files in it stays
            elif _SCRIPT.match(name) and entry.is_file() and _blender_script(entry.path):
                os.unlink(entry.path)
            elif _CONTEXT.match(name) and entry.is_dir():
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                continue
        except OSError:
            continue                                # held open, not empty, or gone meanwhile
        gone += not os.path.lexists(entry.path)
    return gone
