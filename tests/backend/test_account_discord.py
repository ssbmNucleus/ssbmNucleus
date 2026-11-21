"""The Discord sign-in the backend holds (shared/account): sign-in and sign-out change the
stored session in a fixed order, and the account summary reads Discord's own name and avatar."""
import flask
import pytest

from shared.account import discord, session as account_session
from shared.routes import account as account_routes


class FakeSession:
    def __init__(self, calls, value=None):
        self.calls = calls
        self.value = value
        self.gen = 0

    def get(self):
        return self.value

    def generation(self):
        return self.gen

    def store_tokens(self, payload, expected_generation=None):
        self.calls.append("store")
        self.gen += 1
        self.value = {"user_id": payload["user"]["id"], "access_token": payload["access_token"]}
        return self.value

    def clear(self, expected_generation=None):
        self.calls.append("clear")
        self.gen += 1
        self.value = None
        return True

    def token(self, min_left_s=120):
        return (self.value or {}).get("access_token")


class RunNow:
    def __init__(self, target=None, **_kwargs):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A fake session on both modules that read it and a throwaway index, so nothing can
    touch the machine's real Discord session."""
    from tracker.store import indexer
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    calls = []
    sess = FakeSession(calls, {"user_id": "old", "access_token": "old-at"})
    monkeypatch.setattr(discord, "_session", sess)
    monkeypatch.setattr(account_session, "_session", sess)
    monkeypatch.setattr(discord, "_profiles", {})
    monkeypatch.setattr(discord.threading, "Thread", RunNow)
    monkeypatch.setattr(discord, "_fetch_user", lambda token: pytest.fail("fetched the user"))
    return sess


def _payload(user_id, meta=None):
    return {"access_token": f"{user_id}-at", "user": {"id": user_id, "user_metadata": meta or {}}}


def test_sign_in_stores_the_new_session(fake):
    flow = discord._AuthFlow()
    flow.state = "pending"
    assert flow._finish(_payload("new")) is True
    assert fake.calls == ["store"]
    assert fake.value["user_id"] == "new"
    assert flow.status()["state"] == "done"


def test_sign_out_clears_the_session_before_logging_out(fake, monkeypatch):
    monkeypatch.setattr(discord.requests, "post", lambda *a, **k: fake.calls.append("logout"))
    discord.sign_out()
    assert fake.calls == ["clear", "logout"]
    assert discord.auth_status()["state"] == "idle"


def test_summary_uses_the_discord_details_kept_from_sign_in(fake):
    flow = discord._AuthFlow()
    flow.state = "pending"
    flow._finish(_payload("new", {"name": "player#0", "custom_claims": {"global_name": "Player"},
                                  "avatar_url": "a.png"}))
    assert discord.account_summary() == {"user_id": "new", "username": "Player",
                                         "discord_username": "player", "avatar_url": "a.png",
                                         "source": "discord"}


def test_summary_fetches_an_older_session_once(fake, monkeypatch):
    fetched = []
    monkeypatch.setattr(discord, "_fetch_user", lambda token: fetched.append(token) or {
        "id": "old", "user_metadata": {"full_name": "Old Name", "picture": "p.png"}})
    for _ in range(2):
        assert discord.account_summary() == {"user_id": "old", "username": "Old Name",
                                             "discord_username": "Old Name", "avatar_url": "p.png",
                                             "source": "discord"}
    assert fetched == ["old-at"]


def test_summary_is_none_when_signed_out(fake):
    fake.value = None
    assert discord.account_summary() is None


def test_session_token_never_raises(fake, monkeypatch):
    assert discord.session_token() == "old-at"
    monkeypatch.setattr(fake, "token", lambda min_left_s=120: (_ for _ in ()).throw(RuntimeError("refresh")))
    assert discord.session_token() is None


def test_routes_answer_with_account_and_sign_in_state(monkeypatch):
    calls = []
    monkeypatch.setattr(discord, "account_summary", lambda: {"user_id": "u", "username": "Me"})
    monkeypatch.setattr(discord, "auth_status", lambda: {"state": "idle", "error": None})
    monkeypatch.setattr(discord, "start_sign_in", lambda: calls.append("start") or "https://auth")
    monkeypatch.setattr(discord, "sign_out", lambda: calls.append("signout"))
    app = flask.Flask(__name__)
    app.register_blueprint(account_routes.account_bp)
    c = app.test_client()

    state = {"account": {"user_id": "u", "username": "Me"}, "auth": {"state": "idle", "error": None}}
    assert c.get("/api/account/discord").get_json() == state
    assert c.post("/api/account/discord/start").get_json() == {"url": "https://auth", **state}
    assert c.post("/api/account/discord/signout").get_json() == state
    assert calls == ["start", "signout"]


def test_a_taken_callback_port_fails_the_start_instead_of_leaving_it_pending(monkeypatch):
    flow = discord._AuthFlow()

    def port_taken():
        raise OSError(10048, "address already in use")
    monkeypatch.setattr(flow, "_ensure_server", port_taken)
    monkeypatch.setattr(discord.webbrowser, "open", lambda url: pytest.fail("opened the browser"))
    with pytest.raises(discord.SignInUnavailable):
        flow.start()
    assert flow.status()["state"] == "error"

    monkeypatch.setattr(discord, "start_sign_in", flow.start)
    app = flask.Flask(__name__)
    app.register_blueprint(account_routes.account_bp)
    response = app.test_client().post("/api/account/discord/start")
    assert response.status_code == 409
    assert "port" in response.get_json()["error"]


def test_an_older_attempt_can_neither_finish_nor_fail_the_newer_one(fake, monkeypatch):
    flow = discord._AuthFlow()
    monkeypatch.setattr(flow, "_ensure_server", lambda: None)
    monkeypatch.setattr(discord.webbrowser, "open", lambda url: None)
    flow.start()
    older = flow._attempt
    flow.start()
    flow._fail("access_denied", older)
    assert flow.status()["state"] == "pending"
    assert flow._finish(_payload("stale"), older) is False
    assert flow._exchange("code", older) == (False, "A newer sign-in replaced this one.")
    assert flow._finish(_payload("new"), flow._attempt) is True
    assert fake.value["user_id"] == "new"


def test_a_rejected_refresh_signs_out(fake):
    discord._refresh_rejected(fake.generation())
    assert fake.calls == ["clear"]
    assert fake.value is None


def test_a_rejected_refresh_leaves_a_newer_sign_in_alone(fake):
    stale = fake.generation()
    fake.store_tokens(_payload("new"))
    discord._refresh_rejected(stale)
    assert fake.value["user_id"] == "new"


def test_summary_never_answers_for_a_session_replaced_during_the_profile_fetch(fake, monkeypatch):
    def slow_profile(user_id):
        fake.clear()          # signed out while the profile was being read
        return {"display_name": "Old"}
    monkeypatch.setattr(discord, "_profile", slow_profile)
    assert discord.account_summary() is None


class _Rejected:
    status_code = 401
    ok = False

    def json(self):
        return {"error": "invalid_grant"}


def test_a_rejected_refresh_token_signs_out_through_the_account_not_a_bare_clear(monkeypatch):
    """F-K-3: the session asks discord.py to sign out, under the sign-in lock and only
    if no newer sign-in replaced it; it never just clears the stored tokens itself."""
    assert account_session._session.on_refresh_rejected is discord._refresh_rejected
    session = account_session._Session()
    stored = {"access_token": "old-at", "refresh_token": "old-rt", "expires_at": 0, "user_id": "old"}
    monkeypatch.setattr(session, "get", lambda: stored)
    monkeypatch.setattr(session, "clear", lambda **_kw: pytest.fail("a bare clear skips the sign-in lock"))
    monkeypatch.setattr(account_session.requests, "post", lambda *a, **k: _Rejected())
    rejected = []
    session.on_refresh_rejected = rejected.append
    assert session.token() is None
    assert rejected == [session.generation()]
