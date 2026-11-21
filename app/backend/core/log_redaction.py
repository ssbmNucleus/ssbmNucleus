"""
Log redaction for anything that leaves the machine.

Text logs get this pass before they go out (the user-facing logs zip, the
in-app bug report and Randall's "Report this chat" bundle): the OS username
in absolute paths, and anything token-shaped. Path *structure* survives so
logs stay debuggable. Pure: no Flask, no IO.

Secrets in a URL's query string are blanked earlier, as every log line is
written (``SecretQueryFilter`` on app.py's handlers): the 0.9.0 smoke test
found the session token (``?_nucleus_token=``, which media URLs carry) in
every request line of mex_api_<date>.log.
"""
import logging
import re
from pathlib import Path

# Any Windows/mac/Linux home path — not just this machine's — gets its username
# component masked, so paths copied into logs from elsewhere are covered too.
# Backslash runs of any depth count as one separator: JSON-encoded paths carry
# \\, and JSON-in-JSON (electron stdout echoes of log lines) carries \\\\.
# Case-insensitive: Windows paths keep whatever case they were typed in
# (c:\users\...), and /HOME or /users are the same leak.
_HOME_DIR_RE = re.compile(r'(?:[A-Za-z]:(?:\\+|/)Users(?:\\+|/)|/home/|/Users/)([^\\/\s"\'<>|]+)',
                          re.IGNORECASE)
_GENERIC_ACCOUNT_NAMES = frozenset({
    'user', 'users', 'admin', 'administrator', 'owner', 'guest', 'default',
    'public', 'home', 'windows', 'pc', 'player', 'gamer', 'test',
})
# A query-string parameter whose name says it is a secret: the app's own
# _nucleus_token, and any name ending in token, key, secret, password, sig,
# signature, auth, jwt or credential(s) (access_token, api_key, apikey,
# X-Amz-Signature, ...), plus an OAuth code. Its value is blanked up to the
# next separator; the name stays, so the line still says what was sent.
_SECRET_QUERY_RE = re.compile(
    r'([?&;](?:[A-Za-z0-9_.\-]*(?:token|key|secret|password|passwd|sig|signature|auth|jwt|credential)s?|code)=)'
    r'[^&;\s"\'#<>]+', re.IGNORECASE)
_TOKEN_RES = (
    re.compile(r'(token=)[^&\s"\']+', re.IGNORECASE),
    _SECRET_QUERY_RE,
    re.compile(r'(Bearer\s+)[A-Za-z0-9._+/=-]{8,}'),
    re.compile(r'("(?:access_token|refresh_token|device_token|token|api_key|apikey)"\s*:\s*")[^"]+',
               re.IGNORECASE),
    # Vault pairing tokens: the pair URL's #t= fragment (charset as the phone
    # parses it) and the bare nvt_ device-token shape wherever else it lands.
    re.compile(r'([#&]t=)[A-Za-z0-9_-]{16,}'),
    re.compile(r'(nvt_)[A-Za-z0-9_-]{16,}'),
    # Provider keys that can surface in text without a label: OpenRouter's
    # per-user keys (sk-or-v1-<64 hex>) and other sk- style API keys.
    re.compile(r'(sk-or-v\d+-)[A-Za-z0-9]{16,}'),
    re.compile(r'(sk-(?:ant-|proj-)?)[A-Za-z0-9_-]{20,}'),
    # Bare JWTs (Supabase/Patreon session tokens): keep the header, blank the rest.
    re.compile(r'(eyJ[A-Za-z0-9_-]{8,}\.)[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'),
)


def redact_log_text(text: str) -> str:
    """Mask the OS username in absolute paths and blank token-shaped values.
    Path *structure* survives (`C:/Users/<user>/...`) so logs stay debuggable."""
    home = str(Path.home())
    for variant in (home, home.replace('\\', '/'), home.replace('\\', '\\\\')):
        if variant:
            text = text.replace(variant, '~')
    text = _HOME_DIR_RE.sub(lambda m: m.group(0)[: -len(m.group(1))] + '<user>', text)
    # The username also leaks outside home paths (pytest-of-<user>, tool temp
    # dirs, ...). Scrub standalone occurrences of the literal local username;
    # short names are skipped so a user called e.g. "log" can't mangle logs.
    # Generic account names ("user", "admin", ...) identify nobody and are
    # ordinary words: masking them everywhere rewrote chat roles and report
    # keys ("user" -> "<user>") and crashed a tester's chat report. Their home
    # paths are still masked above.
    username = Path.home().name
    if len(username) >= 3 and username.lower() not in _GENERIC_ACCOUNT_NAMES:
        # Lookarounds instead of \b so `_` counts as a separator too
        # (tool temp dirs like torchinductor_<user> / hsperfdata_<user>).
        text = re.sub(rf'(?<![A-Za-z0-9]){re.escape(username)}(?![A-Za-z0-9])',
                      '<user>', text, flags=re.IGNORECASE)
    for pattern in _TOKEN_RES:
        text = pattern.sub(lambda m: m.group(1) + '***', text)
    return text


def redact_query_secrets(text: str) -> str:
    """``text`` with the values of secret query-string parameters blanked
    (``?preview=1&_nucleus_token=***``); everything else as it was."""
    return _SECRET_QUERY_RE.sub(lambda m: m.group(1) + '***', text)


class SecretQueryFilter(logging.Filter):
    """A handler filter that blanks secret query-string values in every record
    it writes (werkzeug's request lines among them). Installed on each of
    app.py's root handlers: a logger's own filters skip the records its
    children propagate."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:       # a record that cannot be formatted is the handler's to report
            return True
        cleaned = redact_query_secrets(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True
