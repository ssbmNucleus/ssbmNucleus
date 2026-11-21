"""Phone pairing: the security contract.

The app's path is POST /api/nucleome/vault/pair -> vault_client.pair_device ->
the vault-sync edge function, which mints the device token server-side and
stores only a hash. The phone ends up holding a bearer token for the user's
whole replay library, so what is pinned here is: the token travels only in a
URL fragment the phone's parser recovers exactly, the route refuses
before touching the network when it should, and neither the token nor the
desktop's own app token lands in a response, a log, or the local database.

Every network edge is faked. `urllib.request.urlopen` is replaced per test and
an autouse guard fails any real socket connect. The "tokens" are throwaway
strings minted in the test; no real account is involved.
"""
import base64
import io
import json
import logging
import re
import secrets
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest
from flask import Flask

from tracker.video import anim_fetch
from tracker.store import indexer
from tracker.cloud import vault_client, vault_jobs


def _import_blueprint_quietly():
    """Import the nucleOME blueprint without its import-time Watch Lite
    geometry fetch reaching the network (it runs on a daemon thread)."""
    name = "tracker.routes.nucleome"
    if name in sys.modules:
        return sys.modules[name]
    original = anim_fetch.ensure_anim_zips
    anim_fetch.ensure_anim_zips = lambda *a, **k: None
    try:
        import tracker.routes.nucleome as module
        for t in threading.enumerate():
            if t.name == "nucleome-anim-fetch":
                t.join(timeout=10)
    finally:
        anim_fetch.ensure_anim_zips = original
    return module


bp_module = _import_blueprint_quietly()

PAIR = "/api/nucleome/vault/pair"
REVOKE = "/api/nucleome/vault/revoke"
# Throwaway stand-in for the desktop's Patreon app token (never a real one).
APP_TOKEN = "fake-app-token-" + "q" * 24

# The phone's parsers, ported verbatim:
#   services/mobile/src/account-generation.js claimTokenFromHash (runs on location.hash)
#   services/mobile/src/scan.js tokenFromScan (runs on the scanned QR text)
PHONE_HASH_RE = re.compile(r"[#&]t=([A-Za-z0-9_-]{16,})")
PHONE_SCAN_RE = re.compile(r"[#&?]t=([A-Za-z0-9_-]{16,})")
PHONE_BARE_RE = re.compile(r"^[A-Za-z0-9_-]{16,}$")

PAIR_URL_BUILDERS = [
    pytest.param(vault_client.pair_url, id="app-vault_client"),
]


def _sample_token():
    """A device token in the vault-sync function's shape: nvt_ + 24 random bytes, url-safe base64."""
    return "nvt_" + base64.urlsafe_b64encode(secrets.token_bytes(24)).decode().rstrip("=")


# --- fixtures ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Any test that slips past its fake fails loudly instead of going online."""
    def refuse(*_a, **_k):
        raise AssertionError("test attempted a real network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "nucleome.db"
    monkeypatch.setattr(indexer, "DB_PATH", db_path)
    monkeypatch.setattr(bp_module, "VAULT_ENABLED", True)
    monkeypatch.setattr(bp_module, "NUCLEOME_ENABLED", True)
    app = Flask(__name__)
    app.register_blueprint(bp_module.nucleome_bp)
    yield app.test_client()
    indexer._initialized_paths.discard(str(db_path))


class FakeVault:
    """The Supabase edge functions, at the urlopen boundary. `reply` maps the
    decoded request payload to a dict (sent as a 200 body) or an exception."""

    def __init__(self, reply=None):
        self.reply = reply or self.mint
        self.requests = []
        self.minted = []

    def mint(self, payload):
        if payload.get("action") == "pair":
            token = "nvt_" + secrets.token_urlsafe(24)
            self.minted.append(token)
            return {"device_token": token, "device_id": len(self.minted),
                    "label": payload.get("label")}
        if payload.get("action") == "revoke":
            return {"ok": True}
        return {}

    def urlopen(self, req, timeout=None):
        self.requests.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(req.header_items()),
            "payload": json.loads(req.data),
        })
        out = self.reply(self.requests[-1]["payload"])
        if isinstance(out, BaseException):
            raise out
        return io.BytesIO(json.dumps(out).encode())


@pytest.fixture
def vault(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    return fake


def _link_patreon(token=APP_TOKEN):
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, token)
    finally:
        conn.close()


@pytest.mark.parametrize("build", PAIR_URL_BUILDERS)
def test_phone_parsers_recover_the_exact_token(build):
    """Both phone parsers extract the whole token: none is truncated by its charset."""
    for _ in range(500):
        token = _sample_token()
        url = build(token)
        fragment = "#" + urllib.parse.urlsplit(url).fragment
        assert PHONE_HASH_RE.search(fragment).group(1) == token
        assert PHONE_SCAN_RE.search(url).group(1) == token
        assert PHONE_BARE_RE.match(token)


# --- the pairing URL --------------------------------------------------------

@pytest.mark.parametrize("build", PAIR_URL_BUILDERS)
def test_pair_url_carries_the_token_only_in_the_fragment(build):
    """Token is the https URL's #t= fragment, never its path/query/request line."""
    token = _sample_token()
    url = build(token)
    parts = urllib.parse.urlsplit(url)

    assert parts.scheme == "https"
    assert parts.fragment == f"t={token}"
    assert parts.query == ""
    assert token not in parts.netloc and token not in parts.path
    # What an HTTP client actually puts on the request line when it opens it.
    assert token not in urllib.request.Request(url).selector


# --- the route: refusals ----------------------------------------------------

@pytest.mark.parametrize("gate_off,linked,status,error", [
    pytest.param("VAULT_ENABLED", True, 404,
                 "the vault is not available in this build", id="vault-gate-off"),
    pytest.param("NUCLEOME_ENABLED", True, 404,
                 "Nucleus Stats is not available in this build", id="nucleome-gate-off"),
    pytest.param(None, False, 400, "not_configured", id="patreon-not-linked"),
])
def test_pair_refusals_happen_before_any_network(
        client, vault, monkeypatch, gate_off, linked, status, error):
    """Gated-off builds and unlinked accounts are refused without contacting the vault."""
    if gate_off:
        monkeypatch.setattr(bp_module, gate_off, False)
    if linked:
        _link_patreon()
    resp = client.post(PAIR, json={"label": "Pixel"})
    assert resp.status_code == status
    assert resp.get_json() == {"error": error}
    assert vault.requests == []


@pytest.mark.parametrize("reply,error", [
    pytest.param(lambda: {"error": "pledge_required"}, "pledge_required", id="free-tier"),
    pytest.param(lambda: {"error": "invalid_token"}, "invalid_token", id="dead-app-token"),
    pytest.param(lambda: urllib.error.HTTPError(
        vault_client.FN_SYNC, 401, "Unauthorized", None,
        io.BytesIO(b'{"message":"unauthorized"}')), None, id="http-401"),
])
def test_vault_refusal_is_502_and_carries_no_secret(client, vault, reply, error):
    """An entitlement/auth refusal from the vault returns 502 with no token in it."""
    _link_patreon()
    vault.reply = lambda _payload: reply()
    resp = client.post(PAIR, json={"label": "Pixel"})
    body = resp.get_json()

    assert resp.status_code == 502
    assert set(body) == {"error"}
    if error:
        assert body["error"] == error
    else:
        assert body["error"].startswith("vault-sync: HTTP 401")
    assert APP_TOKEN not in resp.get_data(as_text=True)


@pytest.mark.parametrize("exc", [
    pytest.param(urllib.error.URLError("getaddrinfo failed"), id="offline"),
    pytest.param(TimeoutError("timed out"), id="timeout"),
])
def test_offline_vault_is_502_not_500(client, vault, exc):
    """An unreachable vault is the remote's verdict: 502 JSON, not a crash."""
    _link_patreon()
    vault.reply = lambda _payload: exc
    resp = client.post(PAIR, json={})
    assert resp.status_code == 502
    assert "error" in (resp.get_json(silent=True) or {})


# --- the route: what goes out, what comes back ------------------------------

def test_pair_sends_app_token_only_in_the_post_body(client, vault):
    """The app token rides in the POST body to vault-sync, never the URL or headers."""
    _link_patreon()
    resp = client.post(PAIR, json={"label": "Pixel"})
    assert resp.status_code == 200

    [req] = vault.requests
    assert req["url"] == vault_client.FN_SYNC
    assert req["method"] == "POST"
    assert req["payload"] == {"action": "pair", "token": APP_TOKEN, "label": "Pixel"}
    assert all(APP_TOKEN not in str(v) for v in req["headers"].values())
    assert req["headers"]["Authorization"] == f"Bearer {vault_client.SUPABASE_ANON_KEY}"


def test_pair_returns_a_device_token_never_the_app_token(client, vault):
    """The phone gets the vault's fresh device token in a fragment URL, not the desktop's."""
    _link_patreon()
    resp = client.post(PAIR, json={"label": "Pixel"})
    body = resp.get_json()
    [minted] = vault.minted

    assert body["device_token"] == minted != APP_TOKEN
    assert body["pair_url"] == vault_client.pair_url(minted)
    assert urllib.parse.urlsplit(body["pair_url"]).fragment == f"t={minted}"
    assert APP_TOKEN not in resp.get_data(as_text=True)


def test_every_pair_request_mints_anew(client, vault):
    """No local cache: each POST is a fresh server mint with a distinct token."""
    _link_patreon()
    first = client.post(PAIR, json={}).get_json()
    second = client.post(PAIR, json={}).get_json()

    assert len(vault.requests) == 2
    assert first["device_token"] != second["device_token"]
    assert [first["device_token"], second["device_token"]] == vault.minted


def test_pair_leaves_no_device_token_in_local_storage(client, vault, tmp_path):
    """After pairing, no file in the storage dir (db, -wal, -shm) holds the device token."""
    _link_patreon()
    body = client.post(PAIR, json={"label": "Pixel"}).get_json()
    token = body["device_token"].encode()

    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files, "the route should have touched the temp database"
    for p in files:
        assert token not in p.read_bytes(), p.name


def test_pair_logs_no_token_on_success_or_failure(client, vault, caplog):
    """Neither the app token nor the device token reaches any log record."""
    caplog.set_level(logging.DEBUG)
    _link_patreon()
    ok = client.post(PAIR, json={"label": "Pixel"}).get_json()
    vault.reply = lambda _p: {"error": "pledge_required"}
    client.post(PAIR, json={})
    vault.reply = lambda _p: urllib.error.URLError("offline")
    client.post(PAIR, json={})  # the unhandled path logs a traceback

    text = caplog.text + "".join(repr(r.args) for r in caplog.records)
    assert APP_TOKEN not in text
    assert ok["device_token"] not in text


# --- revocation -------------------------------------------------------------

def test_revoke_forwards_the_exact_device_and_rejects_junk_offline(client, vault):
    """Revoke sends {revoke, app token, int id}; a non-integer id never leaves the box."""
    _link_patreon()
    assert client.post(REVOKE, json={"device_id": "7 or 1=1"}).status_code == 400
    assert vault.requests == []

    assert client.post(REVOKE, json={"device_id": 7}).get_json() == {"revoked": 7}
    [req] = vault.requests
    assert req["url"] == vault_client.FN_SYNC
    assert req["payload"] == {"action": "revoke", "token": APP_TOKEN, "device_id": 7}


# --- bug-report redaction ---------------------------------------------------

def test_bug_report_redaction_blanks_pairing_secrets():
    """Log text leaving the machine has the pairing token blanked in every shape."""
    from core.log_redaction import redact_log_text as _redact_log_text

    token = _sample_token()
    for line in (vault_client.pair_url(token),
                 json.dumps({"device_token": token}),
                 json.dumps({"action": "pair", "token": token})):
        assert token not in _redact_log_text(line), line
