"""Fetch slippilab's per-character animation zips — Watch Lite's geometry.

Installer builds bundle these into the backend exe (mex_backend.spec), and a
dev checkout keeps them git-untracked in tools/anim_zips — so both can be
missing them (fresh clone, or a build made without the zips staged). First-run
setup calls ensure_anim_zips() to download any missing characters from the
slippilab GitHub repo (MIT-licensed project; the same files the bundle ships)
into the user-writable STORAGE_PATH/nucleome/anim_zips.

Non-fatal by design: with no zips Watch Lite falls back to dot mode, so a
failed/offline download never blocks setup.
"""
import logging
import os
import zipfile

import requests

import file_retry
from . import clip_render

logger = logging.getLogger(__name__)

_RAW_URL = ("https://raw.githubusercontent.com/frankborden/slippilab/"
            "{branch}/public/zips/{name}.zip")
_BRANCHES = ("main", "master")   # repo default first, fallback second
_TIMEOUT_S = 120                 # per file; the biggest zips are ~5 MB


def char_names():
    """The distinct zip basenames (iceClimbers covers two internal ids)."""
    return list(dict.fromkeys(clip_render._INT_TO_ZIP))


def _download_one(name, dest, branches):
    """Download one character zip to `dest` (atomic: .part then rename).
    Returns the branch that worked, or None. Mutates nothing on failure."""
    part = dest + ".part"
    for branch in branches:
        url = _RAW_URL.format(branch=branch, name=name)
        try:
            resp = requests.get(url, timeout=_TIMEOUT_S)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            with open(part, "wb") as f:
                f.write(resp.content)
            if not zipfile.is_zipfile(part):
                raise ValueError("downloaded file is not a zip")
            file_retry.replace(part, dest)
            return branch
        except Exception as e:
            logger.warning("anim zip %s (%s): %s", name, branch, e)
            try:
                os.remove(part)
            except OSError:
                pass
    return None


def ensure_anim_zips(progress_cb=None):
    """Make Watch Lite's character geometry available, downloading whatever is
    missing. progress_cb(done, total, name) fires per character. Returns
    {'success', 'dir', 'present', 'downloaded', 'failed'} — success means every
    character is available afterwards."""
    names = char_names()
    if all(clip_render.zip_path(n) for n in names):
        return {"success": True, "dir": clip_render.zips_dir(),
                "present": len(names), "downloaded": 0, "failed": 0}

    # Download into the writable user dir (the bundled dir may be read-only
    # inside the PyInstaller onefile bundle). A partial bundled/dev set still
    # counts — only truly missing characters are fetched.
    target = clip_render.user_zips_dir()
    os.makedirs(target, exist_ok=True)
    branches = list(_BRANCHES)
    present = downloaded = failed = 0
    for i, name in enumerate(names):
        if progress_cb:
            progress_cb(i, len(names), name)
        if clip_render.zip_path(name):
            present += 1
            continue
        ok_branch = _download_one(name, os.path.join(target, name + ".zip"),
                                  branches)
        if ok_branch:
            downloaded += 1
            # stick with the branch that worked (skip 404 round-trips)
            branches = [ok_branch]
        else:
            failed += 1
    if progress_cb:
        progress_cb(len(names), len(names), "done")
    if downloaded:
        logger.info("Downloaded %d Watch Lite animation zips to %s",
                    downloaded, target)
    return {"success": failed == 0, "dir": clip_render.zips_dir(),
            "present": present, "downloaded": downloaded, "failed": failed}
