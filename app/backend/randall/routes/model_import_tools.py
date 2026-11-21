"""The model import tools over HTTP: the Settings card and Randall's import card (docs/dev/MODEL_IMPORT_TOOLS.md).

    GET  /api/assistant/model-import-tools          -> {success, tools: service.status()} (state: not_installed,
                                                       downloading, paused, installed, update_needed, failed or
                                                       unsupported; sizes download/needed/downloaded/disk_bytes)
    POST /api/assistant/model-import-tools/start    -> {success, job_id}; 409 with the running job_id; 400 unsupported
    POST /api/assistant/model-import-tools/cancel   -> {success, cancelled}
    POST /api/assistant/model-import-tools/remove   -> {success, removed, tools}; 409 while a download or import runs

The download is an app job (kind ``service.KIND``): its progress reaches the window through the job store (the
``job`` socket event, GET /api/jobs), like every other long job. Not Patreon-gated: model import over the MCP is free.
"""
from flask import Blueprint, jsonify

from core import jobs
from randall.model_import.tools import service

model_import_tools_bp = Blueprint('model_import_tools', __name__, url_prefix='/api/assistant/model-import-tools')


def _fail(error, code, **extra):
    return jsonify(success=False, ok=False, error=error, **extra), code


@model_import_tools_bp.route('', methods=['GET'])
def tools_status():
    return jsonify(success=True, ok=True, tools=service.status())


@model_import_tools_bp.route('/start', methods=['POST'])
def tools_start():
    try:
        job_id = service.start()
    except service.Unsupported as unsupported:
        return _fail(str(unsupported), 400)
    except jobs.JobBusy as busy:
        return _fail('The model import tools are already downloading.', 409, job_id=busy.job_id)
    return jsonify(success=True, ok=True, job_id=job_id)


@model_import_tools_bp.route('/cancel', methods=['POST'])
def tools_cancel():
    return jsonify(success=True, ok=True, cancelled=service.cancel())


@model_import_tools_bp.route('/remove', methods=['POST'])
def tools_remove():
    try:
        removed = service.remove()
    except service.Busy as busy:
        return _fail(str(busy), 409)
    return jsonify(success=True, ok=True, removed=removed, tools=service.status())
