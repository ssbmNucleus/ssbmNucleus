"""Background jobs over HTTP (core/jobs.py). The window's job store asks these on
load and on every socket reconnect, so it never has to remember a job itself."""
from flask import Blueprint, jsonify, request

from core import jobs

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('/api/jobs', methods=['GET'])
def list_jobs():
    """?kind=<kind> narrows; ?active=1 only queued/running. Without active, ended
    jobs the user has not seen yet are included (one interrupted last session).
    ``owner`` is this backend process, so a window can end the running jobs of a
    process that died without a record on disk."""
    return jsonify({'success': True, 'owner': jobs.process_owner(), 'jobs': jobs.list_jobs(
        kind=request.args.get('kind') or None,
        active=request.args.get('active') == '1')})


@jobs_bp.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    record = jobs.get(job_id)
    if record is None:
        return jsonify({'success': False, 'error': 'Job not found'}), 404
    return jsonify({'success': True, 'job': record})


@jobs_bp.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    return jsonify({'success': True, 'stopping': jobs.cancel(job_id)})


@jobs_bp.route('/api/jobs/<job_id>/seen', methods=['POST'])
def seen_job(job_id):
    return jsonify({'success': True, 'seen': jobs.mark_seen(job_id)})
