"""Telling a request from the app's own window apart from anything else that holds the backend token.

The backend token does not separate callers: the window, the dev harness and the user's own AI (MCP, through the
discovery file) all send it, and it is printed to stdout at startup. Electron gives the window a SECOND secret,
``NUCLEUS_UI_APPROVAL_KEY`` (never printed, never served), and the window sends it as ``X-Nucleus-UI-Key`` on the
requests that record a person's decision: the build-change approval card (projects/routes/menus/build_changes.py)
and the confirmations the MCP asks for in the window (randall/mcp/window.py).
"""
import hmac
import os

UI_KEY_ENV = 'NUCLEUS_UI_APPROVAL_KEY'
UI_KEY_HEADER = 'X-Nucleus-UI-Key'

#: Markers that say a request came from automation rather than the window.
AGENT_HEADERS = ('X-Nucleus-Agent-Session', 'X-Nucleus-Agent')


def ui_key():
    return (os.environ.get(UI_KEY_ENV) or '').strip()


def window_refusal(headers):
    """Why a request with these headers is not the window's, as (code, http status), or None when it is.

    ``automation_caller`` (403): it says it is an agent. ``ui_approval_channel_unavailable`` (503): this process has
    no key to check, so nothing can be attributed to the window (fail closed). ``not_the_app_window`` (403): the
    key is missing or wrong.
    """
    for header in AGENT_HEADERS:
        if headers.get(header):
            return 'automation_caller', 403
    expected = ui_key()
    if not expected:
        return 'ui_approval_channel_unavailable', 503
    supplied = headers.get(UI_KEY_HEADER) or ''
    if not hmac.compare_digest(supplied, expected):
        return 'not_the_app_window', 403
    return None
