"""Small preview links in job records; PNGs stay on disk until review is closed."""
import logging
import shutil
import time
from pathlib import Path

from core import jobs
from core.config import OUTPUT_PATH

logger = logging.getLogger(__name__)

# A review the window never closed (the app quit on the review grid) leaves its
# previews behind; the next preview job sweeps any that are this old.
STALE_SECONDS = 24 * 3600


def preview_dir(job_id):
    return OUTPUT_PATH / 'job_previews' / job_id


def clean_previews(name, value):
    path = Path(value)
    if (name == 'previews' and path.resolve().parent == (OUTPUT_PATH / 'job_previews').resolve()
            and path.exists()):
        shutil.rmtree(path)


def _sweep_stale(keep_id):
    root = OUTPUT_PATH / 'job_previews'
    if not root.is_dir():
        return
    now = time.time()
    for child in root.iterdir():
        if child.name == keep_id or not child.is_dir():
            continue
        record = jobs.get(child.name)
        if record and record['status'] in jobs.ACTIVE:
            continue
        try:
            if now - child.stat().st_mtime >= STALE_SECONDS:
                shutil.rmtree(child)
        except OSError as e:
            logger.warning('Could not remove stale previews %s: %s', child, e)


def prepare_previews(job):
    _sweep_stale(job.id)
    path = preview_dir(job.id)
    job.own('previews', str(path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def preview_file(job_id, index, kind):
    record = jobs.get(job_id)
    if not record or record['kind'] != kind:
        return None
    path = preview_dir(job_id) / f'{index}.png'
    return path if path.is_file() else None


def delete_previews(job_id, kind):
    record = jobs.get(job_id)
    if not record or record['kind'] != kind or record['status'] in jobs.ACTIVE:
        return False
    clean_previews('previews', str(preview_dir(job_id)))
    return True
