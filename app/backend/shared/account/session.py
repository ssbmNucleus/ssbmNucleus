"""The Supabase session the backend owns for the Discord sign-in: stored, refreshed when it is
about to expire, and cleared."""

import base64
import json
import logging
import os
import threading
import time

import requests

from core import config
from tracker.store import indexer


logger = logging.getLogger(__name__)

# The public project ssbmnucleus.net and the renderer's account service use. The anon key
# ships in the website bundle; RLS protects the data.
SUPABASE_URL = os.environ.get("NUCLEUS_SUPABASE_URL", config.SUPABASE_URL)
SUPABASE_ANON_KEY = os.environ.get("NUCLEUS_SUPABASE_ANON_KEY", config.SUPABASE_ANON_KEY)
HTTP_TIMEOUT = 15

# kv in the Tracker index: {access_token, refresh_token, expires_at, user_id, signed_in_at}.
# The key keeps its name from when Friends (removed in 0.8.16) owned the sign-in, so a session
# stored before the move still signs you in.
SESSION_KEY = "friends_session"


def _with_conn(fn):
    conn = indexer.connect()
    try:
        return fn(conn)
    finally:
        conn.close()


class _Session:
    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0
        # Set by discord.py: signs out with the account listeners told, instead
        # of a bare clear that leaves a listener holding the old account's data.
        self.on_refresh_rejected = None

    def generation(self):
        with self._lock:
            return self._generation

    def get(self):
        with self._lock:
            return _with_conn(lambda c: indexer.kv_get(c, SESSION_KEY)) or None

    def _save(self, s):
        _with_conn(lambda c: indexer.kv_set(c, SESSION_KEY, s))

    def clear(self, expected_generation=None):
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return False
            self._generation += 1
            _with_conn(lambda c: indexer.kv_set(c, SESSION_KEY, None))
            return True

    def store_tokens(self, payload, expected_generation=None):
        """From an auth/v1/token response."""
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return None
            now = int(time.time())
            s = {
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token"),
                "expires_at": int(payload.get("expires_at") or (now + int(payload.get("expires_in") or 3600))),
                "user_id": ((payload.get("user") or {}).get("id")
                            or _jwt_user_id(payload["access_token"])),
                "signed_in_at": now,
            }
            if expected_generation is None:
                self._generation += 1
            self._save(s)
            return s

    def token(self, min_left_s=120):
        """A valid access token, refreshing when it is about to expire.
        None when signed out (or the refresh token was rejected)."""
        with self._lock:
            generation = self._generation
            s = self.get()
            if not s or not s.get("access_token"):
                return None
            if s.get("expires_at", 0) - time.time() > min_left_s:
                return s["access_token"]
            if not s.get("refresh_token"):
                return None
        try:
            r = requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                json={"refresh_token": s["refresh_token"]},
                headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            logger.info("account: token refresh failed (network): %s", e)
            return (s["access_token"] if generation == self.generation()
                    and s.get("expires_at", 0) > time.time() else None)
        if r.status_code in (400, 401, 403):
            logger.info("account: refresh token rejected; signing out")
            if self.on_refresh_rejected is not None:
                self.on_refresh_rejected(generation)
            else:
                self.clear(expected_generation=generation)
            return None
        if not r.ok:
            return (s["access_token"] if generation == self.generation()
                    and s.get("expires_at", 0) > time.time() else None)
        refreshed = self.store_tokens(r.json(), expected_generation=generation)
        return refreshed["access_token"] if refreshed else None

    def credential(self, min_left_s=120):
        token = self.token(min_left_s=min_left_s)
        with self._lock:
            current = self.get() or {}
            if token and current.get("access_token") == token:
                return token, self._generation
            return None, self._generation


_session = _Session()


def _jwt_user_id(token):
    """Best-effort Supabase JWT subject for implicit-flow token payloads."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        body = json.loads(base64.urlsafe_b64decode(part).decode("utf-8"))
        return body.get("sub") if isinstance(body.get("sub"), str) else None
    except (AttributeError, IndexError, ValueError, UnicodeError):
        return None
