"""
XDelta patches, build side: turn a vault patch into a playable ISO.

Builds an ISO from a patch and the vanilla ISO, plays it in the user's Slippi,
serves the built ISO for download, and creates a new patch from a modded ISO.
Each runs as a job (core/jobs.py: `xdelta_build`, `patch_play`,
`xdelta_create`) whose record carries its progress, error and result. A job
writes only into a file named by its own id and owns it until it is finished,
so a failed or killed attempt leaves nothing behind and one attempt's result can
never be read as another's. These routes register on `xdelta_bp` from
vault/routes/xdelta.py (the vault's patch list), so URLs and endpoint names are
unchanged; patch storage and the xdelta3 resolver are projects/install/xdelta.py.
"""

import re
import time
import uuid
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from flask import request, jsonify, send_file, after_this_request

import file_retry
from core import jobs
from core.child_procs import own
from core.config import OUTPUT_PATH, get_subprocess_args
from projects.install.xdelta import (
    XDELTA_PATH, clean_job_files, load_xdelta_metadata, require_xdelta_exe,
    run_xdelta_play, save_xdelta_metadata,
)
from vault.routes.xdelta import xdelta_bp

logger = logging.getLogger(__name__)

BUILD_KIND = 'xdelta_build'
CREATE_KIND = 'xdelta_create'
PLAY_KIND = 'patch_play'
jobs.register_kind(BUILD_KIND, label='Patch build', cleanup=clean_job_files)
jobs.register_kind(CREATE_KIND, label='Patch creation', cleanup=clean_job_files)
jobs.register_kind(PLAY_KIND, label='Patch play', cleanup=clean_job_files)


def _artifacts_dir():
    return OUTPUT_PATH / 'artifacts'


def run_xdelta_build(job, patch_name, vanilla_iso_path, xdelta_path, expected_size):
    """The `xdelta_build` job: decode the patch into output/artifacts/<job id>.iso.
    Returns { patch_id, filename (the download name), path }."""
    xdelta_exe = require_xdelta_exe()
    artifacts = _artifacts_dir()
    artifacts.mkdir(parents=True, exist_ok=True)
    partial = artifacts / f'{job.id}.part.iso'
    output_path = artifacts / f'{job.id}.iso'
    job.own('partial', str(partial))

    cmd = [
        str(xdelta_exe),
        '-d',  # Decode/decompress
        '-s', str(vanilla_iso_path),
        str(xdelta_path),
        str(partial)
    ]

    # Start the process
    process = own(subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **get_subprocess_args()
    ))

    # Monitor progress by checking output file size
    last_progress = 0
    while process.poll() is None:
        time.sleep(0.3)
        try:
            if partial.exists():
                current_size = partial.stat().st_size
                progress = min(int((current_size / expected_size) * 100), 99)
                if progress != last_progress:
                    job.progress(progress / 100, f'Patching... {progress}%')
                    last_progress = progress
        except Exception:
            pass

    # Process finished - check result
    stdout, stderr = process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode() if stderr else stdout.decode() if stdout else 'Unknown xdelta error'
        logger.error(f"xdelta3 failed: {error_msg}")
        raise RuntimeError(f'Failed to apply patch: {error_msg}')

    file_retry.replace(partial, output_path)
    job.release('partial')
    logger.info(f"[OK] Successfully built ISO: {output_path.name}")
    safe_name = re.sub(r'[^\w\-_]', '_', patch_name)
    return {
        'patch_id': job.params.get('patchId'),
        'filename': f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.iso",
        'path': str(output_path),
    }


def run_xdelta_create(job, name, description, vanilla_iso_path, modded_iso_path):
    """The `xdelta_create` job: encode a patch into output/<job id>.part.xdelta,
    then move it into the Vault and index it.
    Returns { patch_id, name, size, size_mb }."""
    xdelta_exe = require_xdelta_exe()
    partial = OUTPUT_PATH / f'{job.id}.part.xdelta'
    job.own('partial', str(partial))

    cmd = [
        str(xdelta_exe),
        '-e',  # Encode (create patch)
        '-1',  # Fast compression
        # Source window must cover the whole vanilla ISO: the default 64MB
        # window misses long-range matches on rebuilt ISOs and the patch
        # degenerates to ~the full image size.
        '-B', '1810000000',
        '-s', str(vanilla_iso_path),
        str(modded_iso_path),
        str(partial)
    ]

    logger.info(f"Creating xdelta patch: {' '.join(cmd)}")

    # Start the process
    process = own(subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **get_subprocess_args()
    ))

    # xdelta3 doesn't output progress, so we just show current output size
    last_size_mb = 0

    while process.poll() is None:
        time.sleep(1)
        try:
            if partial.exists():
                current_size_mb = partial.stat().st_size / (1024 * 1024)
                if int(current_size_mb) != int(last_size_mb):
                    job.progress(None, f'Creating patch... ({current_size_mb:.1f} MB so far)')
                    last_size_mb = current_size_mb
        except Exception:
            pass

    # Process finished - check result
    stdout, stderr = process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode() if stderr else stdout.decode() if stdout else 'Unknown xdelta error'
        logger.error(f"xdelta3 create failed: {error_msg}")
        raise RuntimeError(f'Failed to create patch: {error_msg}')

    # Success - move to storage
    patch_id = str(uuid.uuid4())[:8]
    final_path = XDELTA_PATH / f"{patch_id}.xdelta"
    shutil.move(str(partial), str(final_path))
    job.release('partial')

    # Get patch file size for display
    patch_size = final_path.stat().st_size
    patch_size_mb = patch_size / (1024 * 1024)

    # Add to metadata
    patches = load_xdelta_metadata()
    patches.append({
        'id': patch_id,
        'name': name,
        'description': description,
        'filename': f"{name}.xdelta",
        'size': patch_size,
        'created': datetime.now().isoformat()
    })
    save_xdelta_metadata(patches)

    logger.info(f"[OK] Created xdelta patch: {name} ({patch_id}) - {patch_size_mb:.2f} MB")
    return {
        'patch_id': patch_id,
        'name': name,
        'size': patch_size,
        'size_mb': round(patch_size_mb, 2)
    }


@xdelta_bp.route('/api/mex/xdelta/build/<patch_id>', methods=['POST'])
def build_xdelta_iso(patch_id):
    """Start an `xdelta_build` job that builds an ISO from a patch and the
    vanilla ISO. Returns { success, job_id }."""
    try:
        data = request.json or {}
        vanilla_iso_path = data.get('vanillaIsoPath')

        if not vanilla_iso_path:
            return jsonify({
                'success': False,
                'error': 'No vanilla ISO path provided. Please set it in Settings.'
            }), 400

        vanilla_iso = Path(vanilla_iso_path)
        if not vanilla_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Vanilla ISO not found: {vanilla_iso_path}'
            }), 404

        # Get expected output size from vanilla ISO
        expected_size = vanilla_iso.stat().st_size

        # Get patch info
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)

        if not patch:
            return jsonify({
                'success': False,
                'error': 'Patch not found'
            }), 404

        xdelta_path = XDELTA_PATH / f"{patch_id}.xdelta"
        if not xdelta_path.exists():
            return jsonify({
                'success': False,
                'error': 'Xdelta file not found'
            }), 404

        logger.info(f"Building ISO from xdelta patch: {patch['name']}")
        logger.info(f"  Vanilla ISO: {vanilla_iso_path} ({expected_size} bytes)")
        logger.info(f"  Patch: {xdelta_path}")

        job_id = jobs.start(
            BUILD_KIND,
            lambda job: run_xdelta_build(job, patch['name'], vanilla_iso_path,
                                         xdelta_path, expected_size),
            label='Patch build', params={'patchId': patch_id, 'name': patch['name']})
        return jsonify({'success': True, 'job_id': job_id})
    except Exception as e:
        logger.error(f"Build xdelta ISO error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/play/<patch_id>', methods=['POST'])
def play_xdelta(patch_id):
    """Start a `patch_play` job: build the patch's ISO if missing and launch it
    in the user's real Slippi.

    Body: { slippiPath, vanillaIsoPath }. Returns { success, job_id }.
    """
    try:
        data = request.json or {}
        slippi_path = data.get('slippiPath')
        vanilla_iso_path = data.get('vanillaIsoPath')
        if not slippi_path:
            return jsonify({'success': False, 'error': 'slippiPath is required'}), 400
        patches = load_xdelta_metadata()
        patch = next((p for p in patches if p['id'] == patch_id), None)
        if not patch:
            return jsonify({'success': False, 'error': 'Patch not found'}), 404
        job_id = jobs.start(
            PLAY_KIND,
            lambda job: run_xdelta_play(patch_id, patch['name'], slippi_path,
                                        vanilla_iso_path, job=job),
            label='Patch play', params={'patchId': patch_id, 'name': patch['name']})
        return jsonify({'success': True, 'job_id': job_id})
    except Exception as e:
        logger.error(f"Play xdelta start error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@xdelta_bp.route('/api/mex/xdelta/download/<job_id>', methods=['GET'])
def download_xdelta_iso(job_id):
    """Download the ISO a finished `xdelta_build` job built; it is deleted once sent."""
    try:
        record = jobs.get(job_id) or {}
        result = record.get('result') or {}
        file_path = Path(result.get('path') or '')
        if (record.get('kind') != BUILD_KIND or record.get('status') != 'done'
                or not file_path.is_file()
                or file_path.resolve().parent != _artifacts_dir().resolve()):
            return jsonify({
                'success': False,
                'error': 'ISO file not found'
            }), 404

        # Delete after download
        @after_this_request
        def cleanup(response):
            try:
                file_path.unlink()
                logger.info(f"Deleted ISO file after download: {file_path.name}")
            except Exception as error:
                logger.error(f"Error deleting ISO file {file_path.name}: {str(error)}")
            return response

        return send_file(
            file_path,
            as_attachment=True,
            download_name=result.get('filename') or file_path.name,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Download xdelta ISO error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@xdelta_bp.route('/api/mex/xdelta/create', methods=['POST'])
def create_xdelta_patch():
    """Start an `xdelta_create` job that makes a new patch from a modded ISO.
    Returns { success, job_id }."""
    try:
        data = request.json or {}
        vanilla_iso_path = data.get('vanillaIsoPath')
        modded_iso_path = data.get('moddedIsoPath')
        name = data.get('name', 'New Patch')
        description = data.get('description', '')

        if not vanilla_iso_path:
            return jsonify({
                'success': False,
                'error': 'No vanilla ISO path provided. Please set it in Settings.'
            }), 400

        if not modded_iso_path:
            return jsonify({
                'success': False,
                'error': 'No modded ISO path provided.'
            }), 400

        vanilla_iso = Path(vanilla_iso_path)
        modded_iso = Path(modded_iso_path)

        if not vanilla_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Vanilla ISO not found: {vanilla_iso_path}'
            }), 404

        if not modded_iso.exists():
            return jsonify({
                'success': False,
                'error': f'Modded ISO not found: {modded_iso_path}'
            }), 404

        logger.info(f"Creating xdelta patch: {name}")
        logger.info(f"  Vanilla ISO: {vanilla_iso_path}")
        logger.info(f"  Modded ISO: {modded_iso_path}")

        job_id = jobs.start(
            CREATE_KIND,
            lambda job: run_xdelta_create(job, name, description,
                                          vanilla_iso_path, modded_iso_path),
            label='Patch creation', params={'name': name})
        return jsonify({'success': True, 'job_id': job_id})
    except Exception as e:
        logger.error(f"Create xdelta patch error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
