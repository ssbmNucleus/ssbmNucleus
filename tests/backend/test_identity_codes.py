"""Which connect codes are "me": logins, removals, and the cloud merge.

Bug report 0f4cdd4d84df (APP_REPORT_TRACKER item 26): a friend logged into
Slippi once on the reporter's computer, and their code was "you" for good,
locked in the UI with no way to remove it. Only the ACTIVE login stays locked
now; a past login can be removed, and the removal reaches the cloud vault
instead of coming back from it on the next sync.

Real sqlite through the indexer (conftest gives each test its own database)
and a real netplay user.json on disk. Only the vault's edge function is faked.
"""
import json
import uuid

import pytest
from flask import Flask

import tracker.routes.nucleome as bp_module
from tracker.cloud import vault_client, vault_jobs
from tracker.routes import replays
from tracker.store import identity, indexer


@pytest.fixture
def slippi(tmp_path_factory, monkeypatch):
    """The netplay user.json, which Slippi rewrites when you switch login."""
    root = tmp_path_factory.getbasetemp() / "slippi-user" / uuid.uuid4().hex
    root.mkdir(parents=True)
    user_json = root / "user.json"
    monkeypatch.setattr(identity, "_netplay_user_json_candidates",
                        lambda: [str(user_json)])

    def login_as(code):
        user_json.write_text(json.dumps({
            "uid": f"uid-{code}", "displayName": code.split("#")[0].lower(),
            "connectCode": code, "playKey": "secret"}), encoding="utf-8")

    return login_as


class FakeVault:
    """vault-read's prefs-get / prefs-set, nothing else."""

    def __init__(self, user_codes=None):
        self.user_codes = user_codes
        self.sets = []

    def __call__(self, url, payload, timeout=120):
        assert url == vault_client.FN_READ
        if payload["action"] == "prefs-get":
            return {} if self.user_codes is None else {"user_codes": list(self.user_codes)}
        assert payload["action"] == "prefs-set"
        self.user_codes = list(payload["user_codes"])
        self.sets.append(self.user_codes)
        return {"ok": True}


@pytest.fixture
def vault(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(vault_client, "_call", fake)
    return fake


@pytest.fixture
def client(monkeypatch):
    # off unless a test turns it on: a stored token would otherwise start a
    # background publish thread
    monkeypatch.setattr(bp_module, "VAULT_ENABLED", False)
    app = Flask(__name__)
    app.register_blueprint(bp_module.nucleome_bp)
    return app.test_client()


def _identity(client):
    return client.get("/api/nucleome/identity").get_json()


def _set_codes(client, codes):
    resp = client.post("/api/nucleome/identity/codes", json={"codes": codes})
    assert resp.status_code == 200
    return resp.get_json()["user_codes"]


def _kv(key):
    conn = indexer.connect()
    try:
        return indexer.kv_get(conn, key)
    finally:
        conn.close()


def _sync(token="tok"):
    conn = indexer.connect()
    try:
        return vault_client.sync_codes(conn, token)
    finally:
        conn.close()


def _friend_logged_in_once(client, slippi):
    """The report: the friend signs in once, then the owner signs back in."""
    slippi("BYRD#644")
    _identity(client)
    slippi("ME#1")
    body = _identity(client)
    assert body["login_codes"] == ["BYRD#644", "ME#1"]
    assert body["active_login_code"] == "ME#1"
    return body


# --- the desktop list ---------------------------------------------------------

def test_a_past_login_can_be_removed(client, slippi):
    body = _friend_logged_in_once(client, slippi)
    assert sorted(body["user_codes"]) == ["BYRD#644", "ME#1"]

    assert _set_codes(client, ["ME#1"]) == ["ME#1"]

    body = _identity(client)
    assert body["user_codes"] == ["ME#1"]
    assert body["login_codes"] == ["ME#1"]
    conn = indexer.connect()
    try:
        assert identity.known_user_codes(conn) == ["ME#1"]
    finally:
        conn.close()


def test_the_active_login_stays_whatever_the_list_says(client, slippi):
    _friend_logged_in_once(client, slippi)

    assert _set_codes(client, []) == ["ME#1"]
    assert _set_codes(client, ["alt#9"]) == ["ME#1", "ALT#9"]

    body = _identity(client)
    assert body["login_codes"] == ["ME#1"]
    assert body["user_codes"] == ["ME#1", "ALT#9"]
    assert _kv("user_codes") == ["ALT#9"]


def test_a_past_login_left_in_the_list_stays_a_login(client, slippi):
    _friend_logged_in_once(client, slippi)

    assert _set_codes(client, ["ME#1", "BYRD#644", "ALT#9"]) == ["BYRD#644", "ME#1", "ALT#9"]
    assert _kv("seen_login_codes") == ["BYRD#644", "ME#1"]
    assert _kv("user_codes") == ["ALT#9"]


def test_a_removed_login_comes_back_only_as_the_active_login(client, slippi):
    _friend_logged_in_once(client, slippi)
    _set_codes(client, ["ME#1"])
    assert "BYRD#644" not in _identity(client)["user_codes"]

    slippi("BYRD#644")
    body = _identity(client)
    assert body["active_login_code"] == "BYRD#644"
    assert "BYRD#644" in body["login_codes"]
    assert "BYRD#644" in body["user_codes"]


# --- the cloud merge ------------------------------------------------------------

def test_a_removal_made_before_the_first_merge_is_not_resurrected(client, slippi, vault):
    """The upgrade path. The older sync pushed every login it had seen, so
    the vault holds the friend's code, and there is no agreed list yet."""
    _friend_logged_in_once(client, slippi)
    vault.user_codes = ["BYRD#644", "ME#1"]

    _set_codes(client, ["ME#1"])
    assert _sync() == ["ME#1"]
    assert vault.user_codes == ["ME#1"]
    assert _identity(client)["user_codes"] == ["ME#1"]

    # and it stays gone
    assert _sync() == ["ME#1"]
    assert vault.sets == [["ME#1"]]


def test_a_removal_after_a_merge_is_not_resurrected(client, slippi, vault):
    _friend_logged_in_once(client, slippi)
    _set_codes(client, ["ME#1", "BYRD#644", "ALT#9"])
    assert _sync() == ["ALT#9", "BYRD#644", "ME#1"]
    assert vault.user_codes == ["ALT#9", "BYRD#644", "ME#1"]

    # a past login and a manual extra, both removed on the desktop only
    _set_codes(client, ["ME#1"])
    assert _sync() == ["ME#1"]
    assert vault.user_codes == ["ME#1"]
    assert _identity(client)["user_codes"] == ["ME#1"]
    assert _kv("seen_login_codes") == ["ME#1"]


def test_a_code_added_on_the_desktop_reaches_the_vault(client, slippi, vault):
    slippi("ME#1")
    vault.user_codes = ["ME#1", "PHONE#2"]
    assert _sync() == ["ME#1", "PHONE#2"]

    _set_codes(client, ["ME#1", "PHONE#2", "ALT#9"])
    assert _sync() == ["ALT#9", "ME#1", "PHONE#2"]
    assert vault.user_codes == ["ALT#9", "ME#1", "PHONE#2"]


def test_an_untick_on_the_phone_still_removes_the_code_here(client, slippi, vault):
    _friend_logged_in_once(client, slippi)
    _set_codes(client, ["ME#1", "BYRD#644", "ALT#9"])
    _sync()

    # the phone unticks everything: the extra, the past login, the active one
    vault.user_codes = []
    assert _sync() == ["ME#1"]
    assert vault.user_codes == ["ME#1"]
    body = _identity(client)
    assert body["user_codes"] == ["ME#1"]
    assert body["login_codes"] == ["ME#1"]


def test_a_tick_on_the_phone_becomes_an_extra_here(client, slippi, vault):
    slippi("ME#1")
    _sync()
    vault.user_codes = ["ME#1", "PHONE#2"]

    assert _sync() == ["ME#1", "PHONE#2"]
    assert _kv("user_codes") == ["PHONE#2"]
    assert vault.sets == [["ME#1"]]  # nothing to push back


def test_edits_on_both_sides_merge(client, slippi, vault):
    slippi("ME#1")
    _set_codes(client, ["ME#1", "A#1", "B#2"])
    _sync()

    _set_codes(client, ["ME#1", "B#2", "DESK#3"])        # desktop: -A, +DESK
    vault.user_codes = ["A#1", "ME#1", "PHONE#4"]       # phone: -B, +PHONE
    assert _sync() == ["DESK#3", "ME#1", "PHONE#4"]
    assert vault.user_codes == ["DESK#3", "ME#1", "PHONE#4"]


def test_another_account_starts_from_the_union_again(client, slippi, vault):
    """The agreed list belongs to one account's vault: compared with another
    account's copy, every difference would read as a removal there."""
    assert vault_client.CODES_BASE_KEY in vault_jobs._ACCOUNT_STATE_KEYS
    slippi("ME#1")
    _set_codes(client, ["ME#1", "ALT#9"])
    _sync()
    assert _kv(vault_client.CODES_BASE_KEY) == ["ALT#9", "ME#1"]

    conn = indexer.connect()
    try:
        vault_jobs.clear_account_sync_state(conn)
    finally:
        conn.close()
    vault.user_codes = ["OTHER#5"]
    assert _sync() == ["ALT#9", "ME#1", "OTHER#5"]


def test_a_failed_push_leaves_the_agreed_list_alone(client, slippi, vault, monkeypatch):
    slippi("ME#1")
    _set_codes(client, ["ME#1", "ALT#9"])
    _sync()
    _set_codes(client, ["ME#1"])

    def offline(url, payload, timeout=120):
        if payload["action"] == "prefs-set":
            raise vault_client.VaultError("offline")
        return {"user_codes": ["ALT#9", "ME#1"]}

    monkeypatch.setattr(vault_client, "_call", offline)
    with pytest.raises(vault_client.VaultError):
        _sync()
    assert _kv(vault_client.CODES_BASE_KEY) == ["ALT#9", "ME#1"]

    monkeypatch.setattr(vault_client, "_call", vault)
    assert _sync() == ["ME#1"]
    assert vault.user_codes == ["ME#1"]


def test_a_removal_is_published_right_away_when_signed_in(client, slippi, vault, monkeypatch):
    """The phone should not keep counting the friend's games until the next
    game is synced, so the route reconciles in the background."""
    monkeypatch.setattr(bp_module, "VAULT_ENABLED", True)
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "tok")
    finally:
        conn.close()
    threads = []

    class Inline:
        def __init__(self, target, **kwargs):
            threads.append(kwargs.get("name"))
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(replays.threading, "Thread", Inline)
    _friend_logged_in_once(client, slippi)
    vault.user_codes = ["BYRD#644", "ME#1"]

    _set_codes(client, ["ME#1"])
    assert threads == ["identity-codes-publish"]
    assert vault.user_codes == ["ME#1"]

    # an unchanged list publishes nothing
    _set_codes(client, ["ME#1"])
    assert threads == ["identity-codes-publish"]
