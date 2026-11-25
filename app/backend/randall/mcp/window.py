"""What the app's window knows that the user's own AI (MCP) needs, and what only the person at the window decides.

**The Slippi Dolphin folder set in Settings.**
The chat sends it with every request (AssistantPanel, ``slippi_dolphin_path`` in localStorage); an MCP client has no
window, so the window mirrors it here instead, at launch and whenever Settings changes it (``POST /api/mcp/window``,
App.jsx, randall/assistant/mcpAccount.js). Kept in memory only. test_in_game over MCP falls back to it, then to
Slippi Launcher's own Dolphin folder, so the AI does not have to ask for (or go looking for) a path the app has.
The AI cannot name another one (no MCP argument does), and a network path is refused.

**Confirmations.** A few MCP calls must be agreed to by the person in the app, not only by the AI client's own
prompt (which a prompt-injected AI can talk its user past): connecting a creation toolkit folder runs that folder's
Python. ``confirm`` posts a question, tells the window over Socket.IO (``mcp_confirm``) and waits for the answer.
The window lists open questions (``GET /api/mcp/window/confirmations``) and answers one
(``POST /api/mcp/window/confirmations/<id>``); both need the window-only key (core/ui_channel.py), so neither the
AI nor anything else holding the backend token can answer for the person.
"""
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from core.path_safety import NotLocalPath, local_path

MAX_PATH = 1024

_lock = threading.Lock()
_state = {}


def set_slippi_dolphin_path(value):
    if value is not None and (not isinstance(value, str) or len(value) > MAX_PATH):
        raise ValueError(f'slippi_dolphin_path must be a folder path of at most {MAX_PATH} characters, or null.')
    if value is not None and value.strip():
        try:
            value = local_path(value, field='slippi_dolphin_path')      # the request-path gate
        except NotLocalPath as refused:
            if refused.reason == 'network':
                raise ValueError('slippi_dolphin_path must be a folder on this computer, not a network path.')
            raise ValueError('slippi_dolphin_path must be a full folder path on this computer.')
    with _lock:
        _state['slippi_dolphin_path'] = (value or '').strip() or None


def clear():
    with _lock:
        _state.clear()
        for record in _confirmations.values():
            record['event'].set()
        _confirmations.clear()


def launcher_dolphin():
    """Slippi Launcher's own netplay Dolphin folder on this computer, when it exists."""
    if os.name == 'nt':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    folder = base / 'Slippi Launcher' / 'netplay'
    return str(folder) if folder.is_dir() else None


def slippi_dolphin_path():
    """The folder set in Nucleus Settings (as the window last said), else Slippi Launcher's, else None."""
    with _lock:
        mirrored = _state.get('slippi_dolphin_path')
    return mirrored or launcher_dolphin()


# ------------------------------------------------------------------ the vault changed

VAULT_EVENT = 'mcp_vault_changed'


def vault_changed(tool, result):
    """A tool the user's AI ran saved to the vault (its reply says ``vault_changed``: a Stage Lab or Skin Lab save,
    a website download, an imported file): tell the window, which reads the vault again as it does after the same
    tool in Randall's chat (AssistantPanel's onRefresh). MCP model imports say so through their job's end instead."""
    if not (isinstance(result, dict) and result.get('vault_changed')):
        return
    try:
        from core.state import get_socketio
        socketio = get_socketio()
        if socketio is not None:
            socketio.emit(VAULT_EVENT, {'tool': tool})
    except Exception:  # noqa: BLE001 - the vault still shows it on the next read
        pass


# ------------------------------------------------------------------ confirmations in the window

CONFIRM_EVENT = 'mcp_confirm'
_confirmations = {}     # id -> record


def _public(record):
    return {key: record[key] for key in ('id', 'kind', 'title', 'message', 'detail', 'confirm_text', 'asked_at')}


def _notify():
    try:
        from core.state import get_socketio
        socketio = get_socketio()
        if socketio is not None:
            socketio.emit(CONFIRM_EVENT, {'pending': pending()})
    except Exception:  # noqa: BLE001 - the window also reads the list when it (re)connects
        pass


def confirm(kind, *, title, message, detail=None, confirm_text='Allow', timeout):
    """Ask the person at the window. -> True (allowed), False (declined), or None (no answer within ``timeout``
    seconds; the question is withdrawn)."""
    record = {'id': uuid.uuid4().hex, 'kind': kind, 'title': title, 'message': message, 'detail': detail or {},
              'confirm_text': confirm_text, 'asked_at': time.time(), 'event': threading.Event(), 'answer': None}
    with _lock:
        _confirmations[record['id']] = record
    _notify()
    try:
        record['event'].wait(timeout)
    finally:
        with _lock:
            _confirmations.pop(record['id'], None)
        _notify()
    return record['answer']


def pending():
    """The questions waiting for the window, oldest first."""
    with _lock:
        return [_public(r) for r in sorted(_confirmations.values(), key=lambda r: r['asked_at'])]


def answer(confirmation_id, allowed):
    """The window's answer. -> False when no such question is open (answered, withdrawn or never asked)."""
    with _lock:
        record = _confirmations.get(confirmation_id)
        if record is None or record['event'].is_set():
            return False
        record['answer'] = bool(allowed)
        record['event'].set()
    return True
