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

POST /api/mcp/account is the window's half of who pays for MCP AI calls (randall/mcp/credits.py).
/api/mcp/window/confirmations are the questions an MCP call asks the person in the window (randall/mcp/window.py);
only the window can read or answer them (its own key, core/ui_channel.py).
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


def _window_only():
    """A refusal for anything that is not the app's window (core/ui_channel.py), or None."""
    from core import ui_channel
    refusal = ui_channel.window_refusal(request.headers)
    if refusal is None:
        return None
    code, status = refusal
    return jsonify(error='Only the Nucleus window can answer this.', code=code), status


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


@mcp_bp.route('/api/mcp', methods=['GET', 'DELETE'])
def mcp_other():
    # Streamable HTTP: a server that offers no SSE stream and keeps no session answers 405 here.
    return Response(status=405, headers={'Allow': 'POST'})
