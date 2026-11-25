"""xdelta patches outside the routes: where the Vault keeps them, their index
entries, the xdelta3 resolver, the build-and-launch worker behind "Play", and
the cleanup the patch and bundle job kinds share (core/jobs.py).

The patch routes (vault/routes/xdelta.py), bundles and the unified importer
all use these, so none of them has to import a route module to reach them.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import file_retry
from core.child_procs import own
from core.config import PROJECT_ROOT, RESOURCES_DIR, STORAGE_PATH, get_subprocess_args
from core.metadata import load_metadata, metadata_transaction

logger = logging.getLogger(__name__)

# XDelta storage path
XDELTA_PATH = STORAGE_PATH / "xdelta"
XDELTA_PATH.mkdir(parents=True, exist_ok=True)


def _xdelta_play_artifacts(patch_id, patch_path, iso_folder, patch_name):
    digest = hashlib.sha256(Path(patch_path).read_bytes()).hexdigest()
    safe_name = re.sub(r'[^\w\-_]', '_', patch_name)
    stem = f'{safe_name}-{patch_id}-{digest[:12]}'
    return (
        digest,
        Path(iso_folder) / f'{stem}.iso',
        Path(iso_folder) / f'{stem}.complete.json',
    )


def _xdelta_cache_is_complete(marker_path, iso_path, patch_id, digest):
    if not iso_path.is_file() or iso_path.stat().st_size == 0 or not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return marker == {'patch_id': patch_id, 'sha256': digest}


def _publish_xdelta_artifact(staging_path, iso_path, marker_path, patch_id, digest):
    if not staging_path.is_file() or staging_path.stat().st_size == 0:
        raise RuntimeError('Patch build produced no ISO file')
    file_retry.replace(staging_path, iso_path)
    marker_tmp = marker_path.with_name(f'{marker_path.name}.{uuid.uuid4().hex}.part')
    marker_tmp.write_text(
        json.dumps({'patch_id': patch_id, 'sha256': digest}), encoding='utf-8')
    file_retry.replace(marker_tmp, marker_path)


# What a patch or bundle job may own while it runs: a half-written output, a
# temp folder, an uploaded image. Only names of these shapes are ever deleted.
_PARTIAL_SUFFIXES = ('.part.iso', '.part.xdelta', '.ssbm.part')


def clean_job_files(name, value):
    """Job cleanup for the patch and bundle kinds: delete what a job still owned
    when it ended or Nucleus died. A failure raises, so the item stays owned and
    the next start tries again."""
    path = Path(value)
    if path.name.endswith(_PARTIAL_SUFFIXES) or path.name.startswith('temp_bundle_image_'):
        path.unlink(missing_ok=True)
    elif path.name.startswith('bundle_') and path.is_dir():
        shutil.rmtree(path)
    return None


def load_xdelta_metadata():
    """Load xdelta metadata from the vault index (metadata.json or the DB)."""
    return (load_metadata(default={}) or {}).get('xdelta', [])


def save_xdelta_metadata(xdelta_list):
    """Save xdelta metadata to the vault index (metadata.json or the DB)."""
    with metadata_transaction(default={'version': '1.0', 'characters': {},
                                       'stages': {}}) as metadata:
        metadata['xdelta'] = xdelta_list


def get_xdelta_exe():
    """Get the path to xdelta3 executable."""
    if os.name == 'nt':
        sub, name = "xdelta", "xdelta3.exe"
    else:
        # A statically-linked xdelta3 3.1.0 now ships for Linux too. Before
        # this, the non-Windows branch returned a bare "xdelta3" and every
        # patch operation died with FileNotFoundError unless the user happened
        # to have the distro package installed.
        # macOS gets its own dir; it is not Windows, but the Linux ELF is no
        # use to it either.
        sub = "xdelta-mac" if sys.platform == "darwin" else "xdelta-linux"
        name = "xdelta3"
    root = RESOURCES_DIR if getattr(sys, 'frozen', False) else PROJECT_ROOT
    xdelta_exe = root / "utility" / sub / name
    if not xdelta_exe.exists():
        xdelta_exe = "xdelta3"   # last resort: whatever is on PATH
    return xdelta_exe


def require_xdelta_exe():
    """Resolve xdelta3 or raise a stable, user-facing missing-tool error."""
    executable = get_xdelta_exe()
    if isinstance(executable, Path) or shutil.which(str(executable)):
        return executable
    platform_name = 'macOS' if sys.platform == 'darwin' else (
        'Windows' if os.name == 'nt' else 'Linux')
    raise FileNotFoundError(
        f'xdelta3 executable was not found for {platform_name}; '
        'the bundled tool is missing and xdelta3 is not on PATH')


def building_progress(report, *, start, span):
    """A decode_patch progress callback saying 'Building ISO... N%' through `report(fraction,
    detail)` as whole percents from `start` to `start + span`, each step once."""
    last = [None]

    def progress(fraction):
        p = min(int(fraction * span) + start, start + span)
        if p != last[0]:
            last[0] = p
            report(p / 100, f'Building ISO... {p - start}%')
    return progress


def decode_patch(source_iso, patch, output, *, progress=None, should_stop=None):
    """Build `output` from the vanilla disc `source_iso` and an xdelta `patch`
    (xdelta3 -d -f -s), the one decode every "build this patch" path uses: Play in
    Dolphin for a patch and a bundle, and adding one to Play's shelf (play/adding.py).

    xdelta3 is resolved by require_xdelta_exe, run from an argument list and owned
    (core/child_procs.py), so it ends with Nucleus. `progress(fraction)` hears how much
    of the output is written (its size against the source disc's, 0..1);
    `should_stop()` true ends xdelta3 through its own handle and raises
    core.jobs.Cancelled. The caller owns `output` and removes it on failure.
    Raises RuntimeError saying what xdelta3 printed when the build fails."""
    cmd = [str(require_xdelta_exe()), '-d', '-f', '-s', str(source_iso), str(patch), str(output)]
    proc = own(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **get_subprocess_args()))
    expected = max(Path(source_iso).stat().st_size, 1)
    output = Path(output)
    try:
        while proc.poll() is None:
            if should_stop is not None and should_stop():
                from core import jobs
                proc.kill()
                proc.wait(timeout=10)
                raise jobs.Cancelled()
            time.sleep(0.3)
            if progress is not None:
                try:
                    if output.exists():
                        progress(min(output.stat().st_size / expected, 1.0))
                except OSError:
                    pass
        out, errout = proc.communicate()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    if proc.returncode != 0:
        msg = (errout or out or b'').decode(errors='replace') or 'xdelta error'
        raise RuntimeError(f'Failed to build ISO: {msg}')


def run_xdelta_play(patch_id, patch_name, slippi_path, vanilla_iso_path, job=None):
    """'Play' on a patch: build the ISO into the user's Dolphin ISO folder if it's
    missing, then boot it in the user's REAL Slippi Dolphin (no texture pack).
    Raises on failure. Given a job (core/jobs.py, the `patch_play` kind) it
    reports progress there and owns its staging file. Returns { iso_path }."""
    def report(fraction, detail):
        if job is not None:
            job.progress(fraction, detail)

    from shared.ingame.boot import launch_real, iso_dir_from_slippi

    report(0.05, 'Preparing...')
    iso_folder = iso_dir_from_slippi(slippi_path)
    xdelta_path = XDELTA_PATH / f"{patch_id}.xdelta"
    if not xdelta_path.exists():
        raise RuntimeError('Xdelta file not found')
    digest, iso_path, marker_path = _xdelta_play_artifacts(
        patch_id, xdelta_path, iso_folder, patch_name)

    if _xdelta_cache_is_complete(marker_path, iso_path, patch_id, digest):
        report(0.85, 'ISO already built - skipping build')
    else:
        if not vanilla_iso_path:
            raise RuntimeError('ISO not built yet and no vanilla ISO path is set (Settings).')
        report(0.1, 'Building ISO from patch...')
        staging_path = iso_path.with_name(
            f'{iso_path.stem}.{uuid.uuid4().hex}.part.iso')
        if job is not None:
            job.own('staging', str(staging_path))
        try:
            decode_patch(vanilla_iso_path, xdelta_path, staging_path,
                         progress=building_progress(report, start=10, span=80))
            _publish_xdelta_artifact(
                staging_path, iso_path, marker_path, patch_id, digest)
        finally:
            try:
                staging_path.unlink(missing_ok=True)
                if job is not None:
                    job.release('staging')
            except OSError:
                logger.warning(f"Could not remove patch staging file: {staging_path}")

    report(0.95, 'Launching Slippi...')
    launch_real(slippi_path, iso_path)
    logger.info(f"[PLAY] patch '{patch_name}': launched {iso_path}")
    return {'iso_path': str(iso_path)}
