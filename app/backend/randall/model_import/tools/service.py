"""The model import tools in the app: where they are, what state they are in, and the download job.

* **The manifest** is the installer's ``utility/model_import_tools.json`` (``RESOURCES_DIR``; the checkout's in a
  source run): one entry per platform (``platform_key``: ``win-x64``, ``linux-x64``, ``osx-arm64``, the keys
  ``hsdlib.manifest.json`` uses). A computer whose key it does not name gets ``unsupported``.
* **The install** is ``<data>/tools/model-import`` (``tools_root``: the data folder, ``core.config.PROJECT_ROOT``,
  where ``storage/`` and ``scratch/`` live; ``NUCLEUS_MODEL_IMPORT_TOOLS`` moves it for a test). ``assemble.py``
  builds it.
* **The download** is one app job (``core/jobs.py``, kind ``KIND``, one at a time): its progress, Cancel and the
  cleanup of a staging folder or disk image a dead process left are the job system's. ``start``, ``cancel``,
  ``remove`` and ``status`` are what the routes (``randall/routes/model_import_tools.py``) call.
* **The import** asks ``installed()`` for rigswap's Python and Blender (``import_job._defaults``) and ``status()``
  for what is missing (``import_job.tools_needed``).
"""
from __future__ import annotations

import json
import logging
import os
import platform as _platform
import shutil
import sys
import threading
from pathlib import Path

from core import jobs

from . import assemble

KIND = 'model_import_tools'
ROOT_ENV = 'NUCLEUS_MODEL_IMPORT_TOOLS'
MANIFEST = 'utility/model_import_tools.json'
SOURCES = {'blender': 'download.blender.org', 'embeddable': 'python.org',
           'standalone': 'python-build-standalone (GitHub)', 'wheels': 'PyPI (files.pythonhosted.org)'}
_log = logging.getLogger(__name__)
_lock = threading.Lock()


class Unsupported(Exception):
    """This computer's platform has no entry in the manifest."""


class Busy(Exception):
    """The tools cannot be changed now (a download or an import is running)."""


def _clean(name, value):
    """What a download job still owned when it ended or its process died: a staging folder, a mounted image."""
    if name == 'mount':
        assemble.detach(value)
    else:
        shutil.rmtree(value, ignore_errors=True)
        shutil.rmtree(f'{value}.raw', ignore_errors=True)
    return None


jobs.register_kind(KIND, label='Model import tools', cleanup=_clean)


# ------------------------------------------------------------------ where

def platform_key():
    """This computer as the manifest names platforms."""
    machine = (_platform.machine() or '').lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, machine or 'unknown')
    system = 'win' if sys.platform == 'win32' else 'osx' if sys.platform == 'darwin' else \
        'linux' if sys.platform.startswith('linux') else sys.platform
    return f'{system}-{arch}'


def manifest_path():
    from core.config import RESOURCES_DIR
    return Path(RESOURCES_DIR) / MANIFEST


def load_manifest(path=None):
    return json.loads(Path(path or manifest_path()).read_text(encoding='utf-8'))


def tools_root():
    override = (os.environ.get(ROOT_ENV) or '').strip()
    if override:
        return Path(override)
    from core.config import PROJECT_ROOT
    return Path(PROJECT_ROOT) / 'tools' / 'model-import'


def entry(manifest=None):
    """This platform's manifest entry, or None."""
    try:
        manifest = manifest or load_manifest()
    except (OSError, ValueError):
        _log.warning('model import tools: no readable %s', manifest_path(), exc_info=True)
        return None
    return (manifest.get('platforms') or {}).get(platform_key())


def installed():
    """{'python': path, 'blender': path} of the tools the manifest pins, installed here; else None."""
    pinned = entry()
    root = tools_root()
    if not pinned or not (assemble.blender_current(root, pinned) and assemble.runtime_current(root, pinned)):
        return None
    return {'python': assemble.python_exe(root, pinned), 'blender': assemble.blender_exe(root, pinned)}


# ------------------------------------------------------------------ state

def _pieces(pinned, found):
    wheels = pinned['wheels']
    first = [w for w in wheels if w['name'] in ('bpy', 'numpy')] or wheels[:2]
    named = ', '.join(f"{w['name']} {w['version']}" for w in first)
    more = len(wheels) - len(first)
    return [
        {'name': 'blender', 'label': f"Blender {pinned['blender']['version']}", 'source': SOURCES['blender'],
         'size': int(pinned['blender']['size']), 'installed': found['blender']},
        {'name': 'python', 'label': f"Python {pinned['python']['version']}",
         'source': SOURCES.get(pinned['python'].get('kind'), 'python.org'),
         'size': int(pinned['python']['size']), 'installed': found['runtime']},
        {'name': 'wheels', 'label': named + (f' and {more} more' if more > 0 else ''), 'source': SOURCES['wheels'],
         'size': sum(int(w['size']) for w in wheels), 'installed': found['runtime']},
    ]


def _job_view(record):
    if not record:
        return None
    return {'id': record['id'], 'status': record.get('status'), 'progress': record.get('progress'),
            'detail': record.get('detail') or '', 'error': record.get('error')}


def status(*, housekeeping=True):
    """What the Settings card and the import card show (docs: the routes' GET). ``housekeeping``: remove folders an
    earlier update could not (a running import held them), when nothing runs now.

    Sizes: ``download_bytes`` is every file the manifest pins; of the files still to install, ``needed_bytes`` is what
    is left to download and ``downloaded_bytes`` what is already on disk (finished files and parts, ``downloads/``).
    State ``paused``: nothing runs, the last download did not fail, and part of it is kept (a Cancel, or an app closed
    mid-download); Download carries on from it (``assemble.fetch``). ``need()`` reads it as not installed or update
    needed, so the import's ``needs_tools`` reply keeps its states."""
    key, root = platform_key(), tools_root()
    base = {'platform': key, 'path': str(root), 'job': None, 'error': None, 'pieces': [],
            'download_bytes': 0, 'needed_bytes': 0, 'downloaded_bytes': 0, 'disk_bytes': 0, 'disk_estimated': True}
    pinned = entry()
    if not pinned:
        return dict(base, supported=False, state='unsupported')
    found = assemble.inspect(root, pinned)
    every = assemble.files_for(pinned)
    needed = assemble.files_for(pinned, blender=not found['blender'], runtime=not found['runtime'])
    left = assemble.remaining(root, needed)
    receipt = found['receipt'] or {}
    current = found['blender'] and found['runtime']
    measured = receipt.get('bytes_on_disk') if current and receipt.get('runtime', {}).get('key') == \
        assemble.runtime_key(pinned) else None
    view = dict(base, supported=True, pieces=_pieces(pinned, found),
                download_bytes=sum(int(item['size']) for _, item, _ in every), needed_bytes=left,
                downloaded_bytes=sum(int(item['size']) for _, item, _ in needed) - left,
                disk_bytes=int(measured or assemble.estimate(every)), disk_estimated=not measured)
    running = jobs.active_job(KIND)
    if running is not None:
        return dict(view, state='downloading', job=_job_view(running.snapshot()))
    last = next(iter(jobs.list_jobs(kind=KIND)), None)
    if current:
        if housekeeping and found['other'] and not import_running():
            try:
                assemble.cleanup(root, pinned)
            except OSError:
                _log.debug('model import tools: cleanup deferred', exc_info=True)
        return dict(view, state='installed')
    if last and last.get('status') in ('failed', 'interrupted'):
        return dict(view, state='failed', job=_job_view(last), error=last.get('error') or 'The download stopped.')
    if view['downloaded_bytes'] > 0:
        return dict(view, state='paused')
    return dict(view, state='update_needed' if found['any'] else 'not_installed')


def sources(pieces):
    """Where a platform's pieces come from, each named once, in order: ``SOURCES`` by what the manifest pins (the
    Settings card's "Blender 4.3.2 from download.blender.org" lines, without the labels)."""
    return list(dict.fromkeys(str(p['source']) for p in pieces or () if p.get('source')))


def need():
    """None when the tools the manifest pins are installed; else what the import says about them:
    {state: 'not_installed'|'update_needed'|'downloading'|'unsupported', download_bytes, needed_bytes, disk_bytes,
    sources}. A failed or paused download is 'not_installed' or 'update_needed' here (whether any piece is
    installed): ``needed_bytes`` is what is left of it. ``sources``: where the files come from (``sources``), so the
    import's words name this platform's (python-build-standalone on macOS and Linux, python.org on Windows)."""
    found = status(housekeeping=False)
    if found['state'] == 'installed':
        return None
    state = found['state'] if found['state'] not in ('failed', 'paused') else ('update_needed' if any(
        p['installed'] for p in found['pieces']) else 'not_installed')
    return ({key: found[key] for key in ('download_bytes', 'needed_bytes', 'disk_bytes')}
            | {'state': state, 'sources': sources(found['pieces'])})


# ------------------------------------------------------------------ the imports that use them

_imports = 0


def import_started():
    """An import is running rigswap on the installed tools (import_job.rigswap): Remove waits for it."""
    global _imports
    with _lock:
        _imports += 1


def import_ended():
    global _imports
    with _lock:
        _imports = max(0, _imports - 1)


def import_running():
    with _lock:
        return _imports > 0 or jobs.active_job('mcp_model_import') is not None


# ------------------------------------------------------------------ the job

def _run(job, pinned, key):
    try:
        receipt = assemble.assemble(tools_root(), pinned, platform=key, progress=job.progress,
                                    cancelled=job.should_stop, own=job.own, release=job.release)
    except assemble.Cancelled:
        raise jobs.Cancelled()
    except assemble.Refused as refused:
        raise RuntimeError(str(refused)) from refused
    return {'message': 'The model import tools are installed.', 'bytes_on_disk': receipt.get('bytes_on_disk'),
            'download_bytes': receipt.get('download_bytes'), 'seconds': receipt.get('seconds')}


def start():
    """Start the download (or the update) as a job. -> its id. Unsupported, or jobs.JobBusy with the running one."""
    pinned, key = entry(), platform_key()
    if not pinned:
        raise Unsupported(f'Model import is not available on this computer ({key}).')
    return jobs.start(KIND, lambda job: _run(job, pinned, key), label='Model import tools', params={'platform': key},
                      single=True, thread_name='model-import-tools')


def cancel():
    running = jobs.active_job(KIND)
    return jobs.cancel(running.id) if running is not None else False


def remove():
    """Delete the installed tools. Busy while a download or an import runs. -> whether anything was there."""
    if jobs.active_job(KIND) is not None:
        raise Busy('The model import tools are downloading; cancel the download first.')
    if import_running():
        raise Busy('A model import is running on these tools; remove them when it has finished.')
    try:
        return assemble.remove(tools_root())
    except assemble.Refused as refused:
        raise Busy(str(refused)) from refused
