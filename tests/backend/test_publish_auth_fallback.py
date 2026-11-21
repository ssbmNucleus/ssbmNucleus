"""Publishing signs the intake RPCs with the ssbmnucleus.net login's token, or
with the backend's Discord session (shared/account) when there is no site
login (both are Supabase Auth users of the website project)."""
import json
import time

import flask
import pytest

import upload.routes.publish as publish_mod


@pytest.fixture
def client(monkeypatch):
    # Stop right after the auth gate: item resolution is the next step.
    monkeypatch.setattr(publish_mod, "load_metadata", lambda: {})
    monkeypatch.setattr(publish_mod, "_resolve_items",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("stopped after auth")))
    app = flask.Flask(__name__)
    app.register_blueprint(publish_mod.publish_bp)
    return app.test_client()


def _post(client, **payload):
    body = {"title": "t", "description": "d", "items": [], **payload}
    return client.post("/api/mex/publish", data={"payload": json.dumps(body)})


def test_no_login_anywhere_is_401(client, monkeypatch):
    monkeypatch.setattr(publish_mod, "_discord_session_token", lambda: None)
    r = _post(client)
    assert r.status_code == 401 and "Discord" in r.get_json()["error"]


def test_discord_session_stands_in_for_the_site_login(client, monkeypatch):
    monkeypatch.setattr(publish_mod, "_discord_session_token", lambda: "discord-jwt")
    r = _post(client)
    assert r.status_code == 400 and r.get_json()["error"] == "stopped after auth"


def test_site_token_wins_when_both_exist(client, monkeypatch):
    calls = []
    monkeypatch.setattr(publish_mod, "_discord_session_token", lambda: calls.append("asked") or "discord-jwt")
    r = _post(client, accessToken="site-jwt")
    assert r.status_code == 400 and calls == []


@pytest.fixture
def discord_signed_in(tmp_path, monkeypatch):
    """A synthetic Discord session in a throwaway nucleome.db.

    The Discord session lives in the kv table of storage/nucleome.db, which on a
    developer machine holds a real Discord session. Point the replay index at
    tmp_path so nothing here can read (or print) the machine's credentials."""
    from tracker.store import indexer
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, "friends_session", {
            "access_token": "fake-friends-access", "refresh_token": "fake-friends-refresh",
            "expires_at": int(time.time()) + 3600, "user_id": "fake-user"})
    finally:
        conn.close()
    return "fake-friends-access"


def test_discord_session_is_the_fallback(discord_signed_in):
    assert publish_mod._discord_session_token() == discord_signed_in
