"""Whose AI usage the app's MCP server spends: the same as the in-app chat's, the signed-in person's.

In the app the window holds the Patreon app token (the identity) and, before every chat turn, asks the website's
``ai-entitlement`` function for that person's provider key and what is left of their usage
(frontend randall/assistant/access.js ``assistantAccess``). The turn runs on that key only when the answer allows
it. The MCP server does the same: the window hands its Patreon token to the backend (``POST /api/mcp/account``,
shared/routes/mcp.py), which keeps it in memory only, and every MCP tool that sends an AI request
(``AI_TOOLS``) first asks ``ai-entitlement`` with it and applies the same rules. The provider key it answers is used
for that call alone and never kept. The token is replaced whenever the window's changes, cleared on sign-out, and
gone when the app quits (it never reaches disk or a log).

With no token (no window, or nobody signed in) the machine's own OpenRouter key is the developer fallback
(``import_job.openrouter_key``: OPENROUTER_API_KEY, else ~/.nucleus-secrets/openrouter.key). A signed-in person's
verdict is final: when their usage is used up, the call is refused, not sent on another key.
"""
import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime

from core import config

ENTITLEMENT_URL = f'{config.SUPABASE_URL}/functions/v1/ai-entitlement'
TIMEOUT_SECONDS = 20
MAX_TOKEN = 4096
# The MCP tools that send AI requests (the chat hands these its turn's key: assistant/engine.py ``image_key``).
# import_model and fix_import are not here: over MCP the client AI answers the importer's asks (model_jobs.py).
AI_TOOLS = frozenset({'generate_material'})
WITHOUT_AI = 'Searching, the vault, builds and the labs still work without it.'
SIGN_IN = ('The AI parts of Nucleus need you signed in: open SSBM Nucleus and connect Patreon in Settings, then try '
           f'again. {WITHOUT_AI}')

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_token = None


class NoCredits(ValueError):
    """No usage this call may spend; the message says why in the app's own words."""


def set_token(token):
    """The window's Patreon app token, or None to forget it (sign-out)."""
    global _token
    if token is not None and (not isinstance(token, str) or not token.strip() or len(token) > MAX_TOKEN
                              or any(ch.isspace() for ch in token)):
        raise ValueError('Invalid account token.')
    with _lock:
        _token = token or None


def clear():
    set_token(None)


def signed_in():
    with _lock:
        return _token is not None


def _forget(token):
    global _token
    with _lock:
        if _token == token:
            _token = None


def _entitlement(token):
    """ai-entitlement's answer for ``token`` (as the window's ``getEntitlement`` asks it)."""
    request = urllib.request.Request(ENTITLEMENT_URL, data=json.dumps({'token': token}).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'apikey': config.SUPABASE_ANON_KEY,
                                              'Authorization': f'Bearer {config.SUPABASE_ANON_KEY}'})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        answer = json.loads(response.read())
    if not isinstance(answer, dict):
        raise ValueError('ai-entitlement answered something other than an object')
    return answer


def _machine_key():
    from randall.model_import.chat.import_job import openrouter_key
    return openrouter_key(None)


def _number(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%b %d').replace(' 0', ' ')
    except ValueError:
        return None


def _used_up(entitlement):
    # access.js refillLabel: a free-only person (monthly_budget 0) waits for the free refill, anyone else for the
    # monthly reset.
    if _number(entitlement.get('monthly_budget')) == 0 and entitlement.get('free_refills_at'):
        when = _day(entitlement['free_refills_at'])
        return (f"You've used up your free Randall usage. It refills {f'on {when}' if when else 'soon'}. "
                + WITHOUT_AI)
    when = _day(entitlement.get('resets_at')) if entitlement.get('resets_at') else None
    return f"You've reached this month's Randall limit. It resets {f'on {when}' if when else 'on the 1st'}. " + WITHOUT_AI


def key_from(entitlement):
    """The provider key an entitlement allows, or NoCredits: access.js ``assistantAccess``, rule for rule."""
    if entitlement.get('active'):
        remaining = _number(entitlement.get('remaining'))
        if entitlement.get('remaining') is not None and (remaining is None or remaining <= 0):
            raise NoCredits(_used_up(entitlement))
        key = entitlement.get('api_key')
        if not isinstance(key, str) or not key.strip():
            raise NoCredits('Your Randall access is not ready yet: open SSBM Nucleus and check again in Settings.')
        return key
    if entitlement.get('paused'):
        raise NoCredits(f'Randall is paused right now. {WITHOUT_AI} Check back soon.')
    if entitlement.get('reason') == 'campaign_membership_required':
        raise NoCredits('Join sc00p on Patreon for free (not just Follow), then press Check again in SSBM Nucleus.')
    if entitlement.get('linked'):
        raise NoCredits(f'This Patreon account does not have Randall access right now. {WITHOUT_AI}')
    raise NoCredits(SIGN_IN)


def ai_key():
    """The provider key for one MCP AI call, checked now (like the chat before each turn), or NoCredits."""
    with _lock:
        token = _token
    if token:
        try:
            entitlement = _entitlement(token)
        except (OSError, ValueError) as exc:      # offline, refused, timed out, a broken answer
            _log.warning('MCP: could not check the AI entitlement (%s)', type(exc).__name__)
            raise NoCredits('Could not check your Patreon link, so nothing was sent. Try again in a moment.') from None
        if entitlement.get('invalid_token'):
            _forget(token)
            raise NoCredits('Your Patreon link is no longer valid: open SSBM Nucleus and connect Patreon again in '
                            f'Settings. {WITHOUT_AI}')
        return key_from(entitlement)
    key = _machine_key()
    if key:
        return key
    raise NoCredits(SIGN_IN)
