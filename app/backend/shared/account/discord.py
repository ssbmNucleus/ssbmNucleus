"""Discord sign-in through Supabase Auth (PKCE and the local callback catcher), signing out, and
the account summary the rest of the app shows."""

import base64
import hashlib
import http.server
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

from .session import HTTP_TIMEOUT, SUPABASE_ANON_KEY, SUPABASE_URL, logger, _session


AUTH_CALLBACK_PORT = 17427
AUTH_REDIRECT = f"http://localhost:{AUTH_CALLBACK_PORT}/auth-callback"
AUTH_FLOW_TTL_S = 10 * 60


# ---------------------------------------------------------------------------
# Discord sign-in (Supabase Auth, PKCE, local callback)
# ---------------------------------------------------------------------------

_CALLBACK_HTML = """<!doctype html><meta charset="utf-8"><title>SSBM Nucleus</title>
<body style="background:#0b1a12;color:#e6f2ea;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;max-width:420px">%s</div>
<script>
// Implicit-flow fallback: tokens in the URL fragment never reach the server,
// so hand them over from here. The PKCE path (?code=) never runs this.
if (location.hash && location.hash.includes('access_token')) {
  fetch('/auth-complete', {method:'POST', headers:{'Content-Type':'text/plain'}, body: location.hash.slice(1)})
    .then(r => { document.body.innerHTML = r.ok
      ? '<div style="text-align:center"><h2 style="color:#4ade80">Signed in</h2><p>You can close this tab and go back to Nucleus.</p></div>'
      : '<p style="color:#f87171">Sign-in failed. Go back to Nucleus and try again.</p>'; });
}
</script>"""


class SignInUnavailable(Exception):
    """The sign-in could not start (its callback port is taken); the message is for the user."""


class _AuthFlow:
    """One sign-in attempt at a time. start() opens the browser; the callback
    handler finishes the PKCE exchange and stores the session.

    The local listener is created on the first sign-in and kept for the
    backend's lifetime: tearing it down and re-binding the same port left a
    half-closed socket that ate the next attempt's callback."""

    def __init__(self):
        self._lock = threading.RLock()
        self._server = None
        self._verifier = None
        # Which start() the state belongs to: a callback or exchange from an
        # older attempt must not finish or fail a newer one.
        self._attempt = None
        self.started_at = 0
        self.state = "idle"     # idle | pending | done | error
        self.error = None

    def start(self):
        with self._lock:
            self._verifier = secrets.token_urlsafe(64)
            self._attempt = secrets.token_hex(8)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(self._verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            url = f"{SUPABASE_URL}/auth/v1/authorize?" + urllib.parse.urlencode({
                "provider": "discord",
                "redirect_to": AUTH_REDIRECT,
                "code_challenge": challenge,
                "code_challenge_method": "s256",
            })
            # Listen first: pending means "waiting for the callback", and with no
            # listener that callback can never arrive.
            try:
                self._ensure_server()
            except OSError as e:
                self._verifier = None
                self._fail(f"Port {AUTH_CALLBACK_PORT} is in use by another program ({e})", self._attempt)
                raise SignInUnavailable(
                    f"Could not start the sign-in: port {AUTH_CALLBACK_PORT} is in use by another program.") from e
            self.state = "pending"
            self.error = None
            self.started_at = time.time()
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            logger.debug("account: webbrowser.open failed", exc_info=True)
        return url

    def _ensure_server(self):
        if self._server:
            return
        flow = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _html(self, status, inner):
                body = (_CALLBACK_HTML % inner).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path != "/auth-callback":
                    self._html(404, "<p>Not found.</p>")
                    return
                attempt = flow._attempt
                if flow.state != "pending":
                    self._html(409, "<p>No sign-in in progress. Start it again from Nucleus.</p>")
                    return
                q = urllib.parse.parse_qs(u.query)
                if q.get("error"):
                    flow._fail(q.get("error_description", q["error"])[0], attempt)
                    self._html(400, "<h2 style='color:#f87171'>Sign-in cancelled</h2><p>Go back to Nucleus to try again.</p>")
                    return
                code = (q.get("code") or [None])[0]
                if not code:
                    # Implicit flow: the fragment carries the tokens; the page's
                    # script posts them to /auth-complete.
                    self._html(200, "<p>Finishing sign-in…</p>")
                    return
                ok, err = flow._exchange(code, attempt)
                if ok:
                    self._html(200, "<h2 style='color:#4ade80'>Signed in</h2><p>You can close this tab and go back to Nucleus.</p>")
                else:
                    self._html(500, f"<h2 style='color:#f87171'>Sign-in failed</h2><p>{err}</p>")

            def do_POST(self):
                attempt = flow._attempt
                if self.path != "/auth-complete" or flow.state != "pending":
                    self.send_response(404); self.end_headers(); return
                n = int(self.headers.get("Content-Length") or 0)
                frag = self.rfile.read(n).decode("utf-8", "replace") if n else ""
                q = urllib.parse.parse_qs(frag)
                at, rt = (q.get("access_token") or [None])[0], (q.get("refresh_token") or [None])[0]
                if not at:
                    flow._fail("no tokens in callback", attempt)
                    self.send_response(400); self.end_headers(); return
                accepted = flow._finish({"access_token": at, "refresh_token": rt,
                                         "expires_in": int((q.get("expires_in") or ["3600"])[0])}, attempt)
                self.send_response(204 if accepted else 409); self.end_headers()

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", AUTH_CALLBACK_PORT), Handler)
        srv.daemon_threads = True
        self._server = srv
        threading.Thread(target=srv.serve_forever, name="account-discord-auth", daemon=True).start()

    def _exchange(self, code, attempt):
        with self._lock:
            if attempt != self._attempt:
                return False, "A newer sign-in replaced this one."
            verifier = self._verifier
        try:
            r = requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
                json={"auth_code": code, "code_verifier": verifier},
                headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            self._fail(f"network: {e}", attempt)
            return False, "Could not reach the sign-in service."
        if not r.ok:
            try:
                msg = r.json().get("error_description") or r.json().get("msg") or r.text[:200]
            except ValueError:
                msg = r.text[:200]
            self._fail(msg, attempt)
            return False, msg
        if not self._finish(r.json(), attempt):
            return False, "Sign-in was cancelled."
        return True, None

    def _finish(self, payload, attempt=None):
        with self._lock:
            if self.state != "pending" or attempt != self._attempt:
                return False
            _session.store_tokens(payload)
            _remember_profile(payload.get("user"))
            self.state = "done"
            self.error = None
        return True

    def _fail(self, msg, attempt=None):
        """End the attempt in error; with `attempt`, only if it is still the current one."""
        with self._lock:
            if attempt is not None and attempt != self._attempt:
                return
            self.state = "error"
            self.error = str(msg)[:200]

    def cancel(self):
        with self._lock:
            self._verifier = None
            self._attempt = None
            self.started_at = 0
            self.state = "idle"
            self.error = None

    def status(self):
        if self.state == "pending" and time.time() - self.started_at > AUTH_FLOW_TTL_S:
            self._fail("timed out")
        return {"state": self.state, "error": self.error}


_auth = _AuthFlow()


def sign_out():
    # Serialize the stored-session snapshot and transition with callback
    # completion so legacy ownership never comes from a mixed identity.
    with _auth._lock:
        tok = _session.get()
        # Local identity changes first. A slow logout request for the former
        # account must not delay clearing it or erase a newer sign-in.
        _auth.cancel()
        _session.clear()
    if tok and tok.get("access_token"):
        try:
            requests.post(f"{SUPABASE_URL}/auth/v1/logout",
                          headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {tok['access_token']}"},
                          timeout=HTTP_TIMEOUT)
        except requests.RequestException:
            pass


def _refresh_rejected(generation):
    """The stored refresh token was rejected: clear the session under the sign-in
    lock, unless a newer sign-in replaced it."""
    with _auth._lock:
        if _session.generation() != generation:
            return
        _session.clear(expected_generation=generation)


_session.on_refresh_rejected = _refresh_rejected


def start_sign_in():
    return _auth.start()


def auth_status():
    """{state: idle | pending | done | error, error} for the sign-in in flight."""
    return _auth.status()


def session_token():
    """The Discord (Supabase) session's access token, refreshed if it is
    about to expire; None when nobody is signed in. Lets the publish flow
    upload as this account when there is no ssbmnucleus.net login."""
    try:
        return _session.token()
    except Exception:  # noqa: BLE001 — a refresh hiccup must not break publishing
        return None


# ---------------------------------------------------------------------------
# Account summary
# ---------------------------------------------------------------------------

_profiles = {}  # user_id -> {display_name, discord_username, avatar_url}


def _discord_profile(meta):
    """Name and avatar from the Discord details Supabase keeps on the user."""
    meta = meta if isinstance(meta, dict) else {}
    claims = meta.get("custom_claims") if isinstance(meta.get("custom_claims"), dict) else {}
    handle = re.sub(r"#0$", "", str(meta.get("name") or meta.get("full_name") or meta.get("username") or ""))[:40]
    display = str(claims.get("global_name") or meta.get("full_name") or handle or "")[:40]
    return {
        "display_name": display or None,
        "discord_username": handle or None,
        "avatar_url": meta.get("avatar_url") or meta.get("picture"),
    }


def _remember_profile(user):
    if isinstance(user, dict) and isinstance(user.get("id"), str) and isinstance(user.get("user_metadata"), dict):
        _profiles[user["id"]] = _discord_profile(user["user_metadata"])


def _fetch_user(token):
    """The signed-in Supabase user (auth/v1/user), or None."""
    try:
        r = requests.get(f"{SUPABASE_URL}/auth/v1/user",
                         headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
                         timeout=HTTP_TIMEOUT)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def _profile(user_id):
    """The account's Discord name and avatar: kept from the sign-in, else fetched once per
    account. Empty when it can't be read (offline); the next call tries again."""
    if user_id not in _profiles:
        token = session_token()
        user = _fetch_user(token) if token else None
        if isinstance(user, dict) and user.get("id") == user_id:
            _remember_profile(user)
    return _profiles.get(user_id) or {}


def account_summary():
    """Card-sized view of the signed-in Discord account for the rest of the
    app (Settings, Upload tab gating): {user_id, username, discord_username,
    avatar_url, source} or None."""
    for _ in range(3):
        generation = _session.generation()
        sess = _session.get()
        if not sess:
            return None
        user_id = sess.get("user_id")
        prof = _profile(user_id)
        # A profile fetch can take a while; never answer with the account of a
        # session that was signed out or replaced meanwhile.
        if _session.generation() == generation:
            break
    else:
        return None
    return {
        "user_id": user_id,
        "username": prof.get("display_name") or prof.get("discord_username"),
        "discord_username": prof.get("discord_username"),
        "avatar_url": prof.get("avatar_url"),
        "source": "discord",
    }
