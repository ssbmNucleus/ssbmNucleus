"""The app's MCP server: the JSON-RPC 2.0 messages POST /api/mcp receives (shared/routes/mcp.py), answered here.

Methods: ``initialize``, ``ping``, ``tools/list``, ``tools/call``; a notification (``notifications/initialized``,
``notifications/cancelled``, ...) or a client's response gets no answer (the route says 202). The tools:

* Randall's own (randall_tools.py): the chat's tool registry through the chat's own prepare/execute, approval tools
  run in one call (the client's ask is the approval), plus ``undo_organization`` and ``attach_file``.
* The model import (model_jobs.py): ``import_model``, ``fix_import`` start an app job; ``job_status`` polls it,
  ``answer_import`` answers its asks and ``cancel_import`` stops it.
* Collection and builds (build_tools.py): import any mod file into the vault, put stage skins, custom characters,
  custom stages and extras into a build, its music playlists, and export it as an ISO (``export_build``, followed
  with ``job_status``, saved with ``save_build_iso``).
* The creation toolkit gateway (toolkit.py): ``native_port`` and ``stage_workbench`` forwarded to a source
  checkout, ``connect_creation_toolkit`` and ``creation_toolkit_status``.
* Problem reports (report_tools.py): ``report_problem`` assembles a report for the developer that only the user can
  send, from the window; ``problem_report_status`` says whether they did. The call itself sends nothing.

A call that is still running after a while answers with a job id (calls.py), so no request runs for minutes. A tool
failure is an isError result with its message, never an HTTP error. No argument of any tool may name a network path
(a UNC path such as //host/share): it is refused here before the tool runs (core/path_safety.py).
"""
import logging

from core.path_safety import is_network_path

from . import build_tools, calls, content, model_jobs, randall_tools, report_tools, toolkit

SERVER_NAME = 'ssbm-nucleus'
PROTOCOL = '2025-06-18'
PROTOCOLS = ('2024-11-05', '2025-03-26', '2025-06-18')
INSTRUCTIONS = (
    "SSBM Nucleus is the user's Super Smash Bros. Melee mod manager. These are the tools of Randall, its built-in "
    'assistant: the vault (the mod library on this computer: search_vault, present_vault_skins), the website '
    '(search_website_mods, download_website_mod), game builds (list_projects, deliver_to_game), costume and stage '
    "retexturing (skin_lab, stage_lab), model import (import_model) and in-game tests; plus the app's own buttons for "
    'a mod collection and builds: import_to_vault (any mod file), install_stage_skin, install_custom_characters, '
    'install_custom_stages, install_extra, the music playlists and export_build (an ISO). Tools that change things run '
    "as soon as they are called: your client's approval prompt is the user's approval, so describe the action "
    'first. A call that takes long answers with a job_id: poll job_status. Pictures in results are renders you can '
    'look at. native_port and stage_workbench need the creation toolkit (creation_toolkit_status). When something '
    'in Nucleus goes wrong, report_problem writes a report the user can send to the developer from the Nucleus '
    'window; the call itself sends nothing.')

_log = logging.getLogger(__name__)


def _version():
    import os
    return os.environ.get('NUCLEUS_APP_VERSION') or 'dev'


def tool_list():
    return (randall_tools.listed() + model_jobs.TOOLS + build_tools.TOOLS + toolkit.TOOLS
            + toolkit.GATEWAY_TOOLS + report_tools.TOOLS)


def _network_argument(value, key=''):
    """The first argument (its key path) holding a network path, else None."""
    if isinstance(value, dict):
        for name, item in value.items():
            found = _network_argument(item, f'{key}.{name}' if key else str(name))
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _network_argument(item, f'{key}[{index}]')
            if found:
                return found
    elif is_network_path(value):
        return key or 'argument'
    return None


def call_tool(name, arguments, *, app):
    """One tools/call. -> its MCP result."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return content.error('Tool arguments must be an object.')
    network = _network_argument(arguments)
    if network:
        # Opening a UNC path makes Windows offer the user's credentials to that host, and running a program
        # from one runs the host's code: no tool takes one (security review 11-19, M1).
        return content.error(f'{network} is a network path. Nucleus only opens files and folders on this '
                             'computer: copy it here first.')
    if name == 'job_status' and build_tools.is_export_job(arguments):
        return build_tools.job_status(arguments)         # an export_build job (an app iso_export job)
    if name == 'job_status' and randall_tools.is_game_session(arguments):
        return randall_tools.game_status(arguments, app=app)   # a test_in_game play session: wait until it plays
    if name in model_jobs.NAMES:
        return model_jobs.call(name, arguments)          # quick: an import only starts its job here
    if name in report_tools.NAMES:
        return report_tools.call(name, arguments)        # assembles or reads a report here; never sends one
    if name == 'creation_toolkit_status':
        return toolkit.status(arguments)
    if name == 'connect_creation_toolkit':
        return calls.run(name, lambda: toolkit.connect(arguments))
    if name in toolkit.FORWARDED:
        return calls.run(name, lambda: toolkit.forward(name, arguments))
    if name == 'toolkit_tools':
        return calls.run(name, lambda: toolkit.toolkit_tools(arguments))
    if name == 'toolkit_call':
        return calls.run(name, lambda: toolkit.toolkit_call(arguments))
    if name in build_tools.NAMES:
        return calls.run(name, lambda: build_tools.call(name, arguments, app=app))
    if name in randall_tools.names():
        return calls.run(name, lambda: randall_tools.call(name, arguments, app=app))
    return content.error(f'Unknown tool {name!r}. tools/list names the tools this app offers.')


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def handle(message, *, app):
    """One JSON-RPC message. -> the response object, or None for a notification or a client response."""
    if not isinstance(message, dict):
        return _error(None, -32600, 'Invalid Request: send one JSON-RPC object (batches are not supported).')
    method = message.get('method')
    if not isinstance(method, str):
        if 'result' in message or 'error' in message:
            return None
        return _error(message.get('id'), -32600, 'Invalid Request: no method.')
    if 'id' not in message:
        return None
    request_id = message['id']
    params = message.get('params')
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(request_id, -32602, 'Invalid params: params must be an object.')
    try:
        if method == 'initialize':
            asked = params.get('protocolVersion')
            result = {'protocolVersion': asked if asked in PROTOCOLS else PROTOCOL,
                      'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': SERVER_NAME, 'title': 'SSBM Nucleus', 'version': _version()},
                      'instructions': INSTRUCTIONS}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': tool_list()}
        elif method == 'tools/call':
            name = params.get('name')
            if not isinstance(name, str) or not name:
                return _error(request_id, -32602, 'Invalid params: tools/call needs the tool name.')
            result = call_tool(name, params.get('arguments'), app=app)
        else:
            return _error(request_id, -32601, f'Method not found: {method}')
    except Exception as exc:  # noqa: BLE001 - a fault here is an answer, never a 500
        _log.exception('MCP %s failed', method)
        if method == 'tools/call':
            result = content.error(f'The call failed unexpectedly: {type(exc).__name__}: {str(exc)[:400]}')
        else:
            return _error(request_id, -32603, f'Internal error: {type(exc).__name__}: {str(exc)[:400]}')
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}
