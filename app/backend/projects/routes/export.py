"""
Export Blueprint - ISO export routes with progress tracking.

Starts the ISO export job, saves and downloads its finished ISO. Progress and
the outcome are the job's record (`job` events, `GET /api/jobs/<artifactId>`).
The export job itself (`run_export_job`, `copy_artifact_to`) is the engine
projects/install/export_job.py, which Randall's delivery also runs.
"""

import logging
from flask import Blueprint, request, jsonify

from core import critical_ops, jobs, playable_iso
from projects.install.export_job import (
    ExportRequestError, _resolve_completed_artifact, _validate_iso_filename,
    copy_artifact_to, export_job, run_export_job,
)

logger = logging.getLogger(__name__)

export_bp = Blueprint('export', __name__)


@export_bp.route('/api/mex/export/start', methods=['POST'])
def start_export():
    """
    Start the ISO export job. Returns at once; `artifactId` is the job's id.

    Body:
    {
        "filename": "modded_game.iso",  // optional
        "cspCompression": 1.0,  // optional, 0.1-1.0, default 1.0
        "useColorSmash": false,  // optional, boolean, default false
        "texturePackMode": false,  // optional, boolean, default false
        "slippiDolphinPath": "..."  // required if texturePackMode is true
    }
    """
    try:
        return jsonify(run_export_job(request.json or {}))
    except ExportRequestError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_bp.route('/api/mex/export/save', methods=['POST'])
def save_iso():
    """Copy an exported ISO from output/ to a user-chosen destination.

    The Electron viewer picks the destination with a native save dialog and
    calls this instead of streaming /export/download through Chromium: a
    server-side copy shows up complete or not at all (critical_op defers
    shutdown), whereas the streamed download died truncated when the user
    closed the app seconds after clicking it -- and a partial ISO boots to a
    black screen. Body: {artifactId, filename, destination}.
    """
    try:
        data = request.json or {}
        filename = data.get('filename', '')
        artifact_id = data.get('artifactId', '')
        _validate_iso_filename(filename)

        # Only a finished export job identifies completed bytes. A display
        # filename or an orphan remaining after restart is not proof.
        record = export_job(artifact_id)
        if record and record['status'] in jobs.ACTIVE:
            return jsonify({
                'success': False, 'status': record['status'],
                'error': 'This ISO is still building. Wait for the export to '
                         'finish, then save it.',
            }), 409
        if record and record['status'] != 'done':
            return jsonify({
                'success': False, 'status': record['status'],
                'error': 'The ISO build failed, so there is nothing to save: '
                         f"{record.get('error') or 'unknown error'}",
            }), 409

        file_path = _resolve_completed_artifact(artifact_id)
        if file_path is None:
            return jsonify({
                'success': False,
                'error': 'No finished ISO with that name exists — the export '
                         'may have failed or its output was cleaned up. Run '
                         'the export again.',
            }), 404

        destination = (data.get('destination') or '').strip()
        if not destination:
            return jsonify({'success': False, 'error': 'No destination given'}), 400
        from pathlib import Path
        dest = Path(destination)
        if not dest.is_absolute() or not dest.parent.is_dir():
            return jsonify({'success': False,
                            'error': f'Destination folder does not exist: {dest.parent}'}), 400

        last_err = copy_artifact_to(file_path, dest)
        if isinstance(last_err, playable_iso.ProtectedPath):
            # Not a failure to retry: a file this app may not write over. The
            # message is the one sentence the user can act on.
            return jsonify({'success': False, 'error': str(last_err)}), 400
        if last_err is not None:
            if not file_path.is_file():
                return jsonify({
                    'success': False,
                    'error': 'The exported ISO disappeared from the output '
                             'folder mid-save (was the export restarted?). '
                             'Run the export again.',
                }), 500
            if isinstance(last_err, (FileNotFoundError, PermissionError)):
                return jsonify({
                    'success': False,
                    'error': f'Could not write to {dest.parent} — the folder '
                             'may be blocked by antivirus or Windows '
                             'Controlled Folder Access. Try saving to a '
                             'different folder.',
                }), 500
            raise last_err

        size = dest.stat().st_size
        logger.info(f"Saved ISO to {dest} ({size / 1024 / 1024:.1f} MB)")
        return jsonify({'success': True, 'path': str(dest), 'bytes': size})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"ISO save failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@export_bp.route('/api/mex/export/download/<artifact_id>/<filename>', methods=['GET'])
def download_iso(artifact_id, filename):
    """Download exported ISO file (browser fallback; Electron uses /export/save).

    No delete-after-request: on Windows the file is still open while it
    streams, so the delete never succeeded anyway (WinError 32 every export).
    Startup cleanup owns leftover output/ files.
    """
    try:
        _validate_iso_filename(filename)
        file_path = _resolve_completed_artifact(artifact_id)
        if file_path is None:
            return jsonify({
                'success': False,
                'error': 'File not found'
            }), 404

        # Keep the process alive until the stream finishes: shutdown mid-send
        # truncated the ISO (the black-screen bug this replaced). A generator
        # with try/finally, NOT send_file + call_on_close: the WSGI server is
        # required to close() the iterator (success or disconnect), whereas
        # call_on_close never fired on send_file's passthrough file wrapper
        # and the op stayed registered forever, wedging shutdown.
        from flask import Response

        op = critical_ops.begin('ISO download')

        def stream_and_release():
            try:
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk
            finally:
                critical_ops.end(op)

        return Response(
            stream_and_release(),
            mimetype='application/octet-stream',
            headers={
                'Content-Length': str(file_path.stat().st_size),
                'Content-Disposition': f'attachment; filename="{filename}"',
            },
        )
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
