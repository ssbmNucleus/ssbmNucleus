"""Stage Creator source and copy-save API; rendering uses the owned live viewer."""
import base64
import zipfile
from flask import Blueprint, jsonify, request
from shared.rendering.stage_editor import open_stage, save_copy

stage_editor_bp = Blueprint('stage_editor', __name__)

@stage_editor_bp.post('/api/mex/stage-editor/open')
def stage_editor_open():
    try:
        body = request.get_json() or {}
        return jsonify(open_stage(body.get('stageCode'), body.get('variantId')))
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        return jsonify(error=str(error)), 400

@stage_editor_bp.post('/api/mex/stage-editor/save')
def stage_editor_save():
    try:
        body = request.get_json() or {}
        data = base64.b64decode(body.get('data', ''), validate=True)
        screenshot = base64.b64decode(body['screenshot'], validate=True) if body.get('screenshot') else None
        return jsonify(save_copy(body.get('workspaceId'), data, body.get('name', ''), screenshot))
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        return jsonify(error=str(error)), 400
