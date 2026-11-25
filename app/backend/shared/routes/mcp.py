"""POST /api/mcp: Nucleus as an MCP server for the user's own AI (docs/dev/APP_MCP.md).

MCP JSON-RPC 2.0 over streamable HTTP, answered as plain JSON (no SSE stream). It
sits under /api/, so app.py's backend-token check guards it like every other route;
an MCP client reaches it through the app's `--mcp` stdio relay
(electron/mcp/relay.js), which reads the port and token from the discovery file the
app writes.

Always registered, even in a build without the assistant: there it answers every
request with one JSON-RPC error that says so, instead of a 404 the relay could only
report as "something went wrong". The tools themselves live in randall/mcp, which a
stable build does not carry, so it is imported only behind the gate.

POST /api/mcp/account is the window's half of who pays for MCP AI calls (randall/mcp/credits.py), and
POST /api/mcp/window what the window tells MCP calls (randall/mcp/window.py). /api/mcp/window/confirmations are the
questions an MCP call asks the person in the window. /api/mcp/window/problem-reports are the problem reports the
user's AI wrote with report_problem (randall/reports/problem_report.py), waiting for the person to send or discard
them; sending is the chat report's own submit (POST /api/mex/chat-reports/submit). Only the window can send or answer
any of these (its own key, core/ui_channel.py): the MCP client holds the backend token too, and must not choose whose
account pays, which folder counts as the user's Slippi Dolphin, or what leaves the computer.
"""
from flask import Blueprint, Response, current_app, jsonify, request

from core import gates

mcp_bp = Blueprint('mcp', __name__)

ASSISTANT_OFF = -32001
ASSISTANT_OFF_MESSAGE = ('This build of SSBM Nucleus has the assistant switched off, so it has no MCP tools. '
                         'Install a Nucleus build with the assistant (Randall) to connect your own AI.')


def _accepted():
    """A notification or a client response: nothing to answer."""
    return Response(status=202)


@mcp_bp.route('/api/mcp', methods=['POST'])
def mcp_post():
    message = request.get_json(silent=True)
    if message is None:
        return jsonify({'jsonrpc': '2.0', 'id': None,
                        'error': {'code': -32700, 'message': 'Parse error: the body is not JSON.'}})
    if gates.enabled('assistant'):
        from randall.mcp import server
        answer = server.handle(message, app=current_app._get_current_object())
        return _accepted() if answer is None else jsonify(answer)
    if isinstance(message, dict) and not (message.get('method') and 'id' in message):
        return _accepted()
    return jsonify({'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                    'error': {'code': ASSISTANT_OFF, 'message': ASSISTANT_OFF_MESSAGE}})


@mcp_bp.route('/api/mcp/account', methods=['POST'])
def mcp_account():
    """The window's Patreon app token, so MCP AI calls spend the signed-in person's usage as the chat does
    (randall/mcp/credits.py): {"token": "<token>"} after a link and at launch, {"token": null} on sign-out. Kept in
    memory only; never answered back, written or logged."""
    if gates.enabled('assistant'):
        refused = _window_only('Only the Nucleus window can set the account MCP calls use.')
        if refused:
            return refused
        from randall.mcp import credits
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'token'}:
            return jsonify(error='Send {"token": <token or null>}.'), 400
        try:
            credits.set_token(body['token'])
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(signed_in=credits.signed_in())
    return jsonify(error='Not available in this build.'), 404


@mcp_bp.route('/api/mcp/window', methods=['POST'])
def mcp_window():
    """What the window knows that MCP calls need (randall/mcp/window.py): {"slippi_dolphin_path": "<folder>" or
    null}, at launch and when Settings changes it. Kept in memory only."""
    if gates.enabled('assistant'):
        refused = _window_only('Only the Nucleus window can tell MCP calls where Slippi Dolphin is.')
        if refused:
            return refused
        from randall.mcp import window
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'slippi_dolphin_path'}:
            return jsonify(error='Send {"slippi_dolphin_path": <folder or null>}.'), 400
        try:
            window.set_slippi_dolphin_path(body['slippi_dolphin_path'])
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True)
    return jsonify(error='Not available in this build.'), 404


def _window_only(error='Only the Nucleus window can answer this.'):
    """A refusal for anything that is not the app's window (core/ui_channel.py), or None."""
    from core import ui_channel
    refusal = ui_channel.window_refusal(request.headers)
    if refusal is None:
        return None
    code, status = refusal
    return jsonify(error=error, code=code), status


@mcp_bp.route('/api/mcp/window/confirmations', methods=['GET'])
def mcp_confirmations():
    """The MCP's open questions for the person at the window: {"pending": [{id, kind, title, message, detail,
    confirm_text, asked_at}]}."""
    if gates.enabled('assistant'):
        refused = _window_only()
        if refused:
            return refused
        from randall.mcp import window
        return jsonify(pending=window.pending())
    return jsonify(error='Not available in this build.'), 404


@mcp_bp.route('/api/mcp/window/confirmations/<confirmation_id>', methods=['POST'])
def mcp_confirmation_answer(confirmation_id):
    """The person's answer: {"allowed": true | false}. 404 when that question is no longer open."""
    if gates.enabled('assistant'):
        refused = _window_only()
        if refused:
            return refused
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'allowed'} or not isinstance(body['allowed'], bool):
            return jsonify(error='Send {"allowed": true or false}.'), 400
        from randall.mcp import window
        if not window.answer(confirmation_id, body['allowed']):
            return jsonify(error='That question is no longer open.'), 404
        return jsonify(ok=True)
    return jsonify(error='Not available in this build.'), 404


@mcp_bp.route('/api/mcp/window/problem-reports', methods=['GET'])
def mcp_problem_reports():
    """The problem reports the user's AI wrote, waiting for the person: {"pending": [{id, title, markdown,
    created_at, reported_by, refs, attachments: [{name, label, kind, bytes, optional, include, too_large}]}]}."""
    if gates.enabled('assistant'):
        refused = _window_only('Only the Nucleus window can read the reports waiting for you.')
        if refused:
            return refused
        from randall.reports import problem_report
        return jsonify(pending=problem_report.pending())
    return jsonify(error='Not available in this build.'), 404


_PROBLEM_REPORT_STATUS = {'unknown_report': 404, 'report_sent': 409, 'report_discarded': 409, 'report_expired': 409,
                          'unknown_attachment': 400, 'bad_include': 400, 'app_version_unknown': 400,
                          'bundle_changed': 409, 'bundle_missing': 409}


@mcp_bp.route('/api/mcp/window/problem-reports/<report_id>/review', methods=['POST'])
def mcp_problem_report_review(report_id):
    """Send, step one: {"include": [names of the optional parts the person ticked], "app_version"?} freezes the
    report as a chat report submission and answers {submission_id, approval_hash, manifest, meta}. Nothing is sent
    here; the window then posts those to /api/mex/chat-reports/submit with consent."""
    if gates.enabled('assistant'):
        refused = _window_only('Only the Nucleus window can send a report.')
        if refused:
            return refused
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not set(body) <= {'include', 'app_version'}                 or not isinstance(body.get('include'), list):
            return jsonify(error='Send {"include": [<attachment names>], "app_version": <version>}.'), 400
        from randall.reports import chat_report, problem_report
        try:
            frozen = problem_report.review(report_id, include=body['include'],
                                           app_version=str(body.get('app_version') or ''))
        except chat_report.ReportError as exc:
            return jsonify(error=str(exc)), _PROBLEM_REPORT_STATUS.get(str(exc), 400)
        return jsonify(success=True, **frozen)
    return jsonify(error='Not available in this build.'), 404


@mcp_bp.route('/api/mcp/window/problem-reports/<report_id>/discard', methods=['POST'])
def mcp_problem_report_discard(report_id):
    """Discard: nothing is sent and the report's parts are deleted. 404 for an unknown report, 409 for an ended one."""
    if gates.enabled('assistant'):
        refused = _window_only('Only the Nucleus window can discard a report.')
        if refused:
            return refused
        from randall.reports import chat_report, problem_report
        try:
            problem_report.discard(report_id)
        except chat_report.ReportError as exc:
            return jsonify(error=str(exc)), _PROBLEM_REPORT_STATUS.get(str(exc), 400)
        return jsonify(ok=True)
    return jsonify(error='Not available in this build.'), 404


@mcp_bp.route('/api/mcp', methods=['GET', 'DELETE'])
def mcp_other():
    # Streamable HTTP: a server that offers no SSE stream and keeps no session answers 405 here.
    return Response(status=405, headers={'Allow': 'POST'})
