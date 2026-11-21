"""Vault endpoint + autorun contract tests (temp DB, no network).

vault_client is stubbed in every test that could reach it: a test that hit the
real edge functions would need a live Patreon token and would push whatever the
developer's library happened to hold.
"""
import json
import threading
import uuid
from pathlib import Path

import pytest
from flask import Flask

import tracker.routes.nucleome as bp_module
from core import jobs
from tracker.combos import combo_index
from tracker.store import indexer
from tracker.cloud import vault_client, vault_jobs, vault_sync


@pytest.fixture
def client(monkeypatch):
    # pytest's Windows tmp_path forces mode 0700, which is unusable on this
    # workspace. A normal mkdir-backed fixture keeps these endpoint tests local.
    test_dir = Path(__file__).parent / ".vault-blueprint-tmp"
    test_dir.mkdir(exist_ok=True)
    db_path = test_dir / f"{uuid.uuid4().hex}.db"
    monkeypatch.setattr(indexer, "DB_PATH", db_path)
    monkeypatch.setattr(jobs, "_jobs", {})
    # the gate is read at import time from the environment, so a dev shell with
    # NUCLEUS_VAULT=0 would otherwise 404 every assertion below
    monkeypatch.setattr(bp_module, "VAULT_ENABLED", True)
    monkeypatch.setattr(vault_client, "list_devices", lambda _token: [])
    # A paid pledge starts the autorun chain; record that instead of spawning
    # threads that would index and upload for real.
    kicks = []
    monkeypatch.setattr(vault_jobs, "kick_autorun", lambda: kicks.append(True))
    app = Flask(__name__)
    app.register_blueprint(bp_module.nucleome_bp)
    test_client = app.test_client()
    test_client.kicks = kicks
    yield test_client
    indexer._initialized_paths.discard(str(db_path))
    db_path.unlink(missing_ok=True)
    try:
        test_dir.rmdir()  # only succeeds for this fixture's empty directory
    except OSError:
        pass  # another concurrently running test still owns a unique DB


def _set_token(client, token="tok-abc"):
    assert client.post("/api/nucleome/vault/token",
                       json={"token": token}).status_code == 200


# --- settings ---------------------------------------------------------------

def test_settings_default_false(client):
    body = client.get("/api/nucleome/vault/settings").get_json()
    assert body == {"auto_scan": False, "auto_sync": False}


def test_settings_round_trip_through_kv(client):
    body = client.post("/api/nucleome/vault/settings",
                       json={"auto_scan": True}).get_json()
    assert body == {"auto_scan": True, "auto_sync": False}

    conn = indexer.connect()
    try:
        assert indexer.kv_get(conn, vault_jobs.AUTO_SCAN_KEY) is True
    finally:
        conn.close()

    # a partial POST must not reset the key it omits
    body = client.post("/api/nucleome/vault/settings",
                       json={"auto_sync": True}).get_json()
    assert body == {"auto_scan": True, "auto_sync": True}
    assert client.get("/api/nucleome/vault/settings").get_json() == body


# --- token ------------------------------------------------------------------

def test_token_is_stored_but_never_returned(client):
    body = client.post("/api/nucleome/vault/token",
                       json={"token": "  secret-token  "}).get_json()
    assert body == {"configured": True}
    assert "secret-token" not in str(body)

    conn = indexer.connect()
    try:
        assert indexer.kv_get(conn, vault_jobs.TOKEN_KEY) == "secret-token"
    finally:
        conn.close()

    assert client.post("/api/nucleome/vault/token",
                       json={"token": None}).get_json() == {"configured": False}


def test_invalid_replacement_is_rejected_without_overwriting_token(client, monkeypatch):
    _set_token(client, "working-token")
    monkeypatch.setattr(
        vault_client, "list_devices",
        lambda _token: (_ for _ in ()).throw(vault_client.VaultError("invalid_token")))
    resp = client.post("/api/nucleome/vault/token", json={"token": "bad-token"})
    assert resp.status_code == 401
    conn = indexer.connect()
    try:
        assert indexer.kv_get(conn, vault_jobs.TOKEN_KEY) == "working-token"
    finally:
        conn.close()


def test_resending_the_stored_token_is_a_no_op_without_the_network(client, monkeypatch):
    """The app re-sends the token on every launch (vaultTokenMirror). The same
    token must neither need the vault (offline launch) nor count as an
    account change, which would cancel a sync and wipe the ledger."""
    _set_token(client, "same-token")
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        conn.execute(
            "INSERT INTO games(id, path, mtime, size) VALUES(1, 'one.slp', 1, 1)")
        conn.execute(
            "INSERT INTO vault_objects(game_id, content_hash, deriver, bytes) "
            "VALUES(1, 'hash-a', ?, 10)", (vault_sync.DERIVER,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(
        vault_client, "list_devices",
        lambda _token: (_ for _ in ()).throw(vault_client.VaultError("vault-sync: unreachable")))
    cancelled = []
    monkeypatch.setattr(vault_jobs, "cancel_sync", lambda: cancelled.append(True))

    resp = client.post("/api/nucleome/vault/token",
                       json={"token": "same-token", "active": True})
    assert resp.status_code == 200
    assert cancelled == []
    conn = indexer.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 1
        assert indexer.kv_get(conn, vault_jobs.PLEDGE_KEY) is True
    finally:
        conn.close()


# --- paying switches automatic upload on, once -------------------------------

def _flags():
    conn = indexer.connect()
    try:
        return (indexer.kv_get(conn, vault_jobs.AUTO_SCAN_KEY),
                indexer.kv_get(conn, vault_jobs.AUTO_SYNC_KEY))
    finally:
        conn.close()


def _pledge(client, active, token="tok-abc"):
    assert client.post("/api/nucleome/vault/token",
                       json={"token": token, "active": active}).status_code == 200


def test_first_paid_pledge_turns_upload_on_and_starts_it(client):
    _set_token(client)
    _pledge(client, True)
    assert _flags() == (True, True)
    assert client.kicks == [True]


def test_a_free_account_changes_no_toggle(client):
    _set_token(client)
    _pledge(client, False)
    assert _flags() == (None, None)
    assert client.kicks == []


def test_the_paid_defaults_keep_a_choice_made_before_paying(client):
    client.post("/api/nucleome/vault/settings", json={"auto_sync": False})
    _set_token(client)
    _pledge(client, True)
    assert _flags() == (True, False)
    assert client.kicks == []      # nothing to upload automatically


def test_turning_upload_off_after_paying_sticks_through_a_lapse(client):
    _set_token(client)
    _pledge(client, True)
    client.post("/api/nucleome/vault/settings", json={"auto_sync": False})
    _pledge(client, False)
    _pledge(client, True)
    assert _flags() == (True, False)
    assert client.kicks == [True]


def test_every_launch_resending_a_paid_pledge_starts_nothing_new(client):
    _set_token(client)
    _pledge(client, True)
    _pledge(client, True)
    _pledge(client, True)
    assert client.kicks == [True]


def test_a_pledge_back_after_a_lapse_starts_the_upload_again(client):
    _set_token(client)
    _pledge(client, True)
    _pledge(client, False)
    _pledge(client, True)
    assert client.kicks == [True, True]


def test_a_payer_from_before_this_build_keeps_their_toggles(client):
    _set_token(client)
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, vault_jobs.PLEDGE_KEY, True)     # mirrored by 0.8.x
    finally:
        conn.close()
    _pledge(client, True)
    assert _flags() == (None, None)
    assert client.kicks == []
    _pledge(client, False)
    _pledge(client, True)                  # a renewal later changes nothing either
    assert _flags() == (None, None)


def test_a_new_account_does_not_inherit_the_previous_pledge(client):
    _set_token(client, "paid-account")
    _pledge(client, True, token="paid-account")
    _set_token(client, "free-account")     # re-link: token first, pledge later
    conn = indexer.connect()
    try:
        assert indexer.kv_get(conn, vault_jobs.PLEDGE_KEY) is False
    finally:
        conn.close()
    _pledge(client, False, token="free-account")
    assert client.kicks == [True]          # only the paid account's first pledge


def test_token_replacement_cancels_work_using_previous_credential(client, monkeypatch):
    _set_token(client, "account-a")
    cancelled = []
    monkeypatch.setattr(vault_jobs, "cancel_sync", lambda: cancelled.append(True))
    assert client.post("/api/nucleome/vault/token",
                       json={"token": "account-b"}).status_code == 200
    assert cancelled == [True]


def test_token_replacement_clears_cloud_derived_local_state(client):
    _set_token(client, "account-a")
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        conn.execute(
            "INSERT INTO games(id, path, mtime, size) VALUES(1, 'one.slp', 1, 1)")
        conn.execute(
            "INSERT INTO vault_objects(game_id, content_hash, deriver, bytes) "
            "VALUES(1, 'hash-a', ?, 10)", (vault_sync.DERIVER,))
        indexer.kv_set(conn, vault_jobs.LAST_SYNC_KEY, "old-stamp")
        indexer.kv_set(conn, "combos_wire_refresh", "old-basis")
        indexer.kv_set(conn, "combos_wire_refresh_pos", "hash-a")
        conn.commit()
    finally:
        conn.close()

    assert client.post("/api/nucleome/vault/token",
                       json={"token": "account-b"}).status_code == 200

    conn = indexer.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM vault_objects").fetchone()[0] == 0
        for key in vault_jobs._ACCOUNT_STATE_KEYS:
            assert indexer.kv_get(conn, key) is None
    finally:
        conn.close()


def test_status_shape(client):
    body = client.get("/api/nucleome/vault/status").get_json()
    assert body["configured"] is False
    assert body["synced"] == 0 and body["pending"] == 0
    assert body["last_sync_at"] is None
    assert "sync" not in body           # a running sync is its cloud_sync job


def test_a_sign_out_during_a_slower_sign_in_stays_signed_out(client, monkeypatch):
    """F-E-6: a token still being checked with the vault must not be stored
    after a sign-out that was sent later."""
    checking = threading.Event()
    release = threading.Event()

    def slow_check(token):
        checking.set()
        release.wait(5)
        return []

    def post(body):
        # a client per thread: two requests at once on one test client share state
        return lambda: client.application.test_client().post(
            "/api/nucleome/vault/token", json=body)

    monkeypatch.setattr(vault_client, "list_devices", slow_check)
    sign_in = threading.Thread(target=post({"token": "account-a", "active": True}))
    sign_in.start()
    assert checking.wait(5)
    sign_out = threading.Thread(target=post({"token": None}))
    sign_out.start()
    sign_out.join(0.5)          # unordered, the sign-out finishes here, first
    release.set()
    sign_in.join(5)
    sign_out.join(5)
    conn = indexer.connect()
    try:
        assert indexer.kv_get(conn, vault_jobs.TOKEN_KEY) is None
        assert indexer.kv_get(conn, vault_jobs.PLEDGE_KEY) is None
    finally:
        conn.close()


# --- no token ---------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("post", "/api/nucleome/vault/sync"),
    ("post", "/api/nucleome/vault/pair"),
    ("get", "/api/nucleome/vault/devices"),
    ("post", "/api/nucleome/vault/revoke"),
])
def test_not_configured_without_a_token(client, method, path):
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "not_configured"}


# --- sync -------------------------------------------------------------------

def test_sync_409_when_already_running(client, monkeypatch):
    _pledge(client, True)       # a linked token is unpaid until told
    release = threading.Event()
    running = jobs.start(vault_jobs.SYNC_KIND, lambda job: release.wait(5), single=True)
    try:
        resp = client.post("/api/nucleome/vault/sync")
    finally:
        release.set()
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "a sync is already running", "job_id": running}


def test_sync_starts_a_job(client, monkeypatch):
    _pledge(client, True)       # a linked token is unpaid until told
    started = []
    monkeypatch.setattr(vault_jobs, "start_sync",
                        lambda token: started.append(token) or "job-1")
    assert client.post("/api/nucleome/vault/sync").get_json() == {
        "started": True, "job_id": "job-1"}
    assert started == ["tok-abc"]


# --- pairing (stubbed transport) --------------------------------------------

def test_pair_returns_the_client_result_verbatim(client, monkeypatch):
    _set_token(client)
    minted = {"device_token": "dev-1", "device_id": 7, "label": "Pixel",
              "created_at": "2026-08-15T00:00:00Z",
              "pair_url": "https://tracker.ssbmnucleus.net/#t=dev-1"}
    monkeypatch.setattr(vault_client, "pair_device",
                        lambda token, label: dict(minted, label=label))
    body = client.post("/api/nucleome/vault/pair",
                       json={"label": "Pixel"}).get_json()
    assert body == minted


def test_vault_error_is_502_not_500(client, monkeypatch):
    _set_token(client)

    def boom(token):
        raise vault_client.VaultError("invalid token")

    monkeypatch.setattr(vault_client, "list_devices", boom)
    resp = client.get("/api/nucleome/vault/devices")
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "invalid token"}


def test_revoke_requires_a_device_id(client, monkeypatch):
    _set_token(client)
    monkeypatch.setattr(vault_client, "revoke_device",
                        lambda token, device_id: {"ok": True})
    assert client.post("/api/nucleome/vault/revoke",
                       json={}).status_code == 400
    assert client.post("/api/nucleome/vault/revoke",
                       json={"device_id": 7}).get_json() == {"revoked": 7}


# --- share links -------------------------------------------------------------

HASH = "a" * 64


def _seed_game(game_id=1, synced=True, content_hash=HASH):
    conn = indexer.connect()
    try:
        vault_sync.ensure_schema(conn)
        conn.execute(
            "INSERT INTO games(id, path, mtime, size, players, start_at, "
            "stage) VALUES(?,?,?,?,?,?,?)",
            (game_id, f"C:/slp/{game_id}.slp", 1.0, 100,
             json.dumps([{"port": 1, "character": 2, "costume": 0, "code": "AA#1"},
                         {"port": 2, "character": 9, "costume": 1, "code": "BB#2"}]),
             "2026-08-01T00:00:00", 31))  # a legal stage — the browse filter drops the rest
        # the browse list resolves "me" through game_players (launcher login
        # codes count too, so the kv claim only ADDS a code)
        conn.execute(
            "INSERT INTO game_players(game_id, port, type, character, "
            "costume, code) VALUES(?,?,?,?,?,?)",
            (game_id, 1, 0, 2, 0, "AA#1"))
        conn.execute(
            "INSERT INTO game_players(game_id, port, type, character, "
            "costume, code) VALUES(?,?,?,?,?,?)",
            (game_id, 2, 0, 9, 1, "BB#2"))
        indexer.kv_set(conn, "user_codes", ["AA#1"])
        if synced:
            conn.execute(
                "INSERT INTO vault_objects(game_id, content_hash, deriver, "
                "bytes, pushed_at) VALUES(?,?,?,?,?)",
                (game_id, content_hash, "frames-v4", 10,
                 "2026-08-01T00:00:00Z"))
        conn.commit()
    finally:
        conn.close()


def _seed_combo(combo_id, game_id, start_frame, n_moves):
    conn = indexer.connect()
    try:
        conn.execute(
            "INSERT INTO combos(id, game_id, port, opp_port, character, "
            "opp_character, stage, start_at, start_frame, end_frame, damage, "
            "moves, hits, did_kill, moves_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (combo_id, game_id, 1, 2, 2, 9, 31, "2026-08-01T00:00:00",
             start_frame, start_frame + 120, 40.0, n_moves, n_moves, 0,
             json.dumps([{"move_id": 15, "hits": 1}] * n_moves)))
        conn.commit()
    finally:
        conn.close()


def test_share_409_when_not_synced(client):
    _set_token(client)
    _seed_game(synced=False)
    resp = client.post("/api/nucleome/share", json={"game_id": 1})
    assert resp.status_code == 409


def test_share_requires_a_game_id(client):
    _set_token(client)
    assert client.post("/api/nucleome/share", json={}).status_code == 400


def test_share_mints_the_game_url(client, monkeypatch):
    _set_token(client)
    _seed_game()
    calls = []
    monkeypatch.setattr(vault_client, "mint_share",
                        lambda token, h: calls.append((token, h))
                        or {"id": "abc123def456", "created": True})
    body = client.post("/api/nucleome/share", json={"game_id": 1}).get_json()
    assert body == {"id": "abc123def456",
                    "url": "https://ssbmnucleus.net/replay/abc123def456",
                    "combo": None}
    assert calls == [("tok-abc", HASH)]


def test_share_combo_ordinal_skips_short_combos(client, monkeypatch):
    """/combo/N indexes the PUBLIC list (>=4 moves, play order) — a short
    combo before the target must not shift the ordinal, and a short combo
    itself has no public page at all."""
    _set_token(client)
    _seed_game()
    _seed_combo(10, 1, start_frame=100, n_moves=2)   # never uploaded
    _seed_combo(11, 1, start_frame=200, n_moves=5)   # public ordinal 1
    _seed_combo(12, 1, start_frame=300, n_moves=4)   # public ordinal 2
    monkeypatch.setattr(vault_client, "mint_share",
                        lambda token, h: {"id": "abc123def456"})

    body = client.post("/api/nucleome/share",
                       json={"game_id": 1, "combo_id": 12}).get_json()
    assert body["url"] == "https://ssbmnucleus.net/replay/abc123def456/combo/2"
    assert body["combo"] == 2

    assert client.post("/api/nucleome/share",
                       json={"game_id": 1, "combo_id": 10}).status_code == 404


def test_share_thumb_forwards_to_the_vault(client, monkeypatch):
    _set_token(client)
    sent = []
    monkeypatch.setattr(vault_client, "push_share_thumb",
                        lambda token, sid, b64: sent.append((token, sid, b64))
                        or {"ok": True})
    assert client.post("/api/nucleome/share/thumb",
                       json={"id": "abc123def456", "png_b64": "AAAA"}
                       ).get_json() == {"ok": True}
    assert sent == [("tok-abc", "abc123def456", "AAAA")]
    assert client.post("/api/nucleome/share/thumb",
                       json={"id": "abc123def456"}).status_code == 400


def test_lists_annotate_synced(client):
    """The row's share button renders off `synced` — games flag straight from
    vault_objects, combos additionally through the upload length rule."""
    _seed_game(game_id=1, synced=True)
    _seed_game(game_id=2, synced=False, content_hash="b" * 64)
    _seed_combo(10, 1, start_frame=100, n_moves=5)   # synced game, public
    _seed_combo(11, 1, start_frame=200, n_moves=2)   # synced game, too short
    _seed_combo(12, 2, start_frame=100, n_moves=5)   # unsynced game

    games = client.get("/api/nucleome/replays").get_json()["games"]
    assert {g["id"]: g["synced"] for g in games} == {1: True, 2: False}

    rows = client.get("/api/nucleome/combos?min_moves=0").get_json()["combos"]
    assert {c["id"]: c["synced"] for c in rows} == {
        10: True, 11: False, 12: False}


# --- feature gate -----------------------------------------------------------

def test_routes_404_when_gated_off(client, monkeypatch):
    monkeypatch.setattr(bp_module, "VAULT_ENABLED", False)
    assert client.get("/api/nucleome/vault/status").status_code == 404
    assert client.post("/api/nucleome/vault/sync").status_code == 404
    assert client.post("/api/nucleome/share", json={"game_id": 1}).status_code == 404
    assert client.post("/api/nucleome/share/thumb", json={}).status_code == 404


def test_lists_omit_synced_when_gated_off(client, monkeypatch):
    """No share affordance in a build without the vault: every row reads
    unsynced rather than the endpoint erroring or leaking the flag."""
    monkeypatch.setattr(bp_module, "VAULT_ENABLED", False)
    _seed_game(game_id=1, synced=True)
    games = client.get("/api/nucleome/replays").get_json()["games"]
    assert games and all(g["synced"] is False for g in games)


# --- launch autorun ---------------------------------------------------------

@pytest.fixture
def no_work(monkeypatch):
    """Fail loudly if the autorun starts anything. Every pass it can trigger is
    replaced, so a regression that ignores the flags cannot quietly index the
    developer's library instead of failing the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("autorun started work it was not asked to")

    monkeypatch.setattr(indexer, "start_scan", refuse)
    monkeypatch.setattr(combo_index, "start_scan", refuse)
    monkeypatch.setattr(vault_jobs, "start_sync", refuse)
    monkeypatch.setattr(vault_client, "sync", refuse)


def test_autostart_noop_when_flags_are_false(tmp_path, monkeypatch, no_work):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(vault_jobs, "VAULT_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "NUCLEOME_ENABLED", True)
    assert vault_jobs.maybe_autostart() is False


def test_autostart_noop_when_sync_wanted_but_no_token(tmp_path, monkeypatch,
                                                     no_work):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(vault_jobs, "VAULT_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "NUCLEOME_ENABLED", True)
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, vault_jobs.AUTO_SYNC_KEY, True)
    finally:
        conn.close()
    assert vault_jobs.maybe_autostart() is False


def test_autostart_noop_when_gated_off(tmp_path, monkeypatch, no_work):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(vault_jobs, "VAULT_ENABLED", False)
    monkeypatch.setattr(vault_jobs, "NUCLEOME_ENABLED", True)
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, vault_jobs.AUTO_SCAN_KEY, True)
        indexer.kv_set(conn, vault_jobs.AUTO_SYNC_KEY, True)
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "tok")
    finally:
        conn.close()
    assert vault_jobs.maybe_autostart() is False


def test_autostart_runs_the_chain_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(vault_jobs, "VAULT_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "NUCLEOME_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "_POLL_S", 0.01)

    replay_dir = tmp_path / "slp"
    replay_dir.mkdir()
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, "replay_root_override", str(replay_dir))
        indexer.kv_set(conn, vault_jobs.AUTO_SCAN_KEY, True)
        indexer.kv_set(conn, vault_jobs.AUTO_SYNC_KEY, True)
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "tok")
    finally:
        conn.close()

    order = []
    monkeypatch.setattr(indexer, "start_scan", lambda d: order.append("scan"))
    monkeypatch.setattr(combo_index, "start_scan", lambda: order.append("combos"))
    # Raw upload is the default chain: raw push, combos, then their metadata.
    monkeypatch.setattr(vault_jobs, "start_sync", lambda token, **kw: order.append(
        f"metadata:{token}" if kw.get("combos_only") else f"{'raw' if kw.get('raw') else 'sync'}:{token}"))

    # the chain runs inline; maybe_autostart's own thread is what we skip
    record = jobs.run_inline(vault_jobs.AUTORUN_KIND, lambda job: vault_jobs._autorun(
        job, True, True, "tok", str(replay_dir)))
    assert record["status"] == "done"
    assert order == ["scan", "raw:tok", "combos", "metadata:tok"]


# --- open-app loop ----------------------------------------------------------

def test_autostart_starts_the_loop_even_with_flags_off(tmp_path, monkeypatch,
                                                       no_work):
    """The loop must exist while both toggles are off: each cycle re-reads the
    kv, which is what lets a toggle flipped mid-session take effect without a
    restart."""
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(vault_jobs, "VAULT_ENABLED", True)
    monkeypatch.setattr(vault_jobs, "NUCLEOME_ENABLED", True)
    ensured = []
    monkeypatch.setattr(vault_jobs, "_ensure_loop", lambda: ensured.append(1))
    assert vault_jobs.maybe_autostart() is False
    assert ensured == [1]


def test_loop_cycle_noop_when_flags_off(tmp_path, monkeypatch, no_work):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    assert vault_jobs._loop_cycle() is False


def test_loop_cycle_skips_while_a_pass_runs(tmp_path, monkeypatch, no_work):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(jobs, "_jobs", {})
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, vault_jobs.AUTO_SYNC_KEY, True)
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "tok")
    finally:
        conn.close()
    release = threading.Event()
    jobs.start(vault_jobs.SYNC_KIND, lambda job: release.wait(5), single=True)
    try:
        assert vault_jobs._loop_cycle() is False
    finally:
        release.set()


def test_loop_cycle_runs_the_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(vault_jobs, "_POLL_S", 0.01)

    replay_dir = tmp_path / "slp"
    replay_dir.mkdir()
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, "replay_root_override", str(replay_dir))
        indexer.kv_set(conn, vault_jobs.AUTO_SCAN_KEY, True)
        indexer.kv_set(conn, vault_jobs.AUTO_SYNC_KEY, True)
        indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "tok")
    finally:
        conn.close()

    order = []
    monkeypatch.setattr(indexer, "start_scan", lambda d: order.append("scan"))
    monkeypatch.setattr(combo_index, "start_scan", lambda: order.append("combos"))
    # Raw upload is the default chain: raw push, combos, then their metadata.
    monkeypatch.setattr(vault_jobs, "start_sync", lambda token, **kw: order.append(
        f"metadata:{token}" if kw.get("combos_only") else f"{'raw' if kw.get('raw') else 'sync'}:{token}"))

    assert vault_jobs._loop_cycle() is True
    assert order == ["scan", "raw:tok", "combos", "metadata:tok"]
    [record] = jobs.list_jobs(kind=vault_jobs.AUTORUN_KIND)
    assert record["status"] == "done"


def test_cloud_activity_persists_and_clears_on_account_change(client, monkeypatch):
    _set_token(client)
    _seed_game()
    monkeypatch.setattr(vault_client, "mint_share", lambda *_: {"id": "saved-link"})
    for _ in range(2):
        assert client.post("/api/nucleome/share", json={"game_id": 1}).status_code == 200
    conn = indexer.connect()
    with conn:
        conn.executemany("INSERT INTO vault_upload_history(uploaded_at,games) VALUES(?,?)",
                         [("2026-09-06T10:00:00Z", 2), ("2026-09-06T11:00:00Z", 3)])
    conn.close()
    status = client.get("/api/nucleome/vault/status").get_json()
    assert len(status["shared_links"]) == 1
    assert status["upload_history"][0]["games"] == 5
    replay = client.get("/api/nucleome/replays").get_json()["games"][0]
    assert replay["synced"] is True
    assert replay["share_url"].endswith("/saved-link")
    _set_token(client, "different-account")
    status = client.get("/api/nucleome/vault/status").get_json()
    assert status["shared_links"] == []
    assert status["upload_history"] == []
    replay = client.get("/api/nucleome/replays").get_json()["games"][0]
    assert replay["share_url"] is None
    assert replay["synced"] is False


def test_share_account_change_in_flight_does_not_save_link(client, monkeypatch):
    _set_token(client)
    _seed_game()
    def mint(*_):
        _set_token(client, "replacement")
        return {"id": "old-account-link"}
    monkeypatch.setattr(vault_client, "mint_share", mint)
    assert client.post("/api/nucleome/share", json={"game_id": 1}).status_code == 409
    assert client.get("/api/nucleome/vault/status").get_json()["shared_links"] == []


def test_share_upload_stops_when_the_account_changes_mid_upload(client, monkeypatch):
    """F-E-7: sharing uploads one game for account A; once B replaced A, that
    upload must not settle into B's ledger."""
    _set_token(client)
    _seed_game(synced=False)
    asked = []

    def sync(token, conn=None, game_ids=None, should_cancel=None):
        _set_token(client, "replacement")
        asked.append(should_cancel is not None and should_cancel())
        raise vault_sync.SyncCancelled("vault sync cancelled")

    monkeypatch.setattr(vault_client, "sync", sync)
    resp = client.post("/api/nucleome/share", json={"game_id": 1})
    assert resp.status_code == 409
    assert asked == [True]


def test_combo_header_excludes_short_sequences(client):
    _seed_game()
    for i, moves in enumerate([1, 2, 3, 4, 5], 1):
        _seed_combo(i, 1, i * 100, moves)
    response = client.get("/api/nucleome/combos/status").get_json()
    assert response["counts"]["combos"] == 2


def test_activity_backfills_existing_share_without_minting(client, monkeypatch):
    _set_token(client)
    _seed_game()
    activity = {"upload_history": [{"day": "2026-08-01", "uploaded_at": "2026-08-01T12:00:00Z", "games": 7}],
                "shared_links": [{"url": "https://ssbmnucleus.net/replay/abc123def456", "content_hash": HASH,
                                  "start_at": None, "players": []}]}
    monkeypatch.setattr(vault_client, "account_activity", lambda _, **kwargs: activity)
    monkeypatch.setattr(vault_client, "mint_share", lambda *_: pytest.fail("backfill must not mint shares"))
    for _ in range(2):
        assert client.get("/api/nucleome/vault/activity").get_json() == activity
    game = client.get("/api/nucleome/replays").get_json()["games"][0]
    assert game["share_url"] == activity["shared_links"][0]["url"]
    conn = indexer.connect()
    assert conn.execute("SELECT COUNT(*) FROM vault_shared_links").fetchone()[0] == 1
    conn.close()


def test_activity_account_change_discards_response(client, monkeypatch):
    _set_token(client)
    def read(_, **kwargs):
        _set_token(client, "replacement")
        return {"upload_history": [], "shared_links": []}
    monkeypatch.setattr(vault_client, "account_activity", read)
    assert client.get("/api/nucleome/vault/activity").status_code == 409


def test_account_activity_returns_one_summary_page_without_following_cursors(monkeypatch):
    monkeypatch.setattr(vault_client, "_activity_cache", vault_client.OrderedDict())
    calls = []
    def call(url, body, **kwargs):
        calls.append(body.copy())
        assert body["token"] == "owner-token"
        assert body["action"] == "activity-page"
        if body["kind"] == "uploads":
            return {"rows": [{"day": "2026-08-01", "uploaded_at": "2026-08-01T12:00:00Z", "games": 100000}],
                    "next": "2026-08-01"}
        return {"rows": [{"id": "abc123def456", "content_hash": HASH}], "next": None}
    monkeypatch.setattr(vault_client, "_call", call)
    result = vault_client.account_activity("owner-token")
    assert result["upload_history"][0]["games"] == 100000
    assert result["next_uploads"] == "2026-08-01"
    assert result["shared_links"][0]["url"].endswith("abc123def456")
    assert len(calls) == 2


def test_activity_endpoint_forwards_pagination_and_refresh(client, monkeypatch):
    _set_token(client)
    seen = []
    def read(token, **kwargs):
        seen.append(kwargs)
        return {"upload_history": [], "shared_links": [], "next_shares": None}
    monkeypatch.setattr(vault_client, "account_activity", read)
    assert client.get("/api/nucleome/vault/activity?kind=shares&cursor=abc123def456&refresh=1").status_code == 200
    assert seen == [{"kind": "shares", "cursor": "abc123def456", "refresh": True}]


def test_activity_bad_cursor_does_not_reach_cloud(client, monkeypatch):
    _set_token(client)
    monkeypatch.setattr(vault_client, "_call", lambda *a, **kw: pytest.fail("invalid input reached cloud"))
    assert client.get("/api/nucleome/vault/activity?kind=uploads&cursor=2026-02-30").status_code == 400
