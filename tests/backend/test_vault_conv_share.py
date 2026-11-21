"""C9: conversions and raw-replay sharing, entirely offline."""
import ast
import gzip
import hashlib
import io
import json
import sqlite3
import types
import urllib.error
import uuid

import pytest
from flask import Flask, jsonify, request

from tests.paths import BACKEND
from core import jobs
from tracker.cloud import vault_client, vault_jobs, vault_raw, vault_sync
from tracker.store import game_trace, indexer
from tracker.video import interactions, viz_export


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / f"conv-share-{uuid.uuid4().hex}.db")
    monkeypatch.setattr(vault_client, "_call", lambda *a, **kw: pytest.fail("unexpected network"))
    monkeypatch.setattr(vault_client, "_put", lambda *a, **kw: pytest.fail("unexpected PUT"))
    conn = indexer.connect()
    vault_raw.ensure_raw_schema(conn)
    indexer.kv_set(conn, vault_jobs.TOKEN_KEY, "token")
    yield conn
    conn.close()


def game(db, tmp_path, gid=1, players=2, body=None):
    path = tmp_path / f"{gid}.slp"
    path.write_bytes(body or f"synthetic replay {gid}".encode())
    stat = path.stat()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    db.execute("INSERT INTO games(id,path,mtime,size,parse_ok,start_at) VALUES(?,?,?,?,1,?)",
               (gid, str(path), stat.st_mtime, stat.st_size, f"2026-10-{gid:02}"))
    db.executemany("INSERT INTO game_players(game_id,port,type) VALUES(?,?,0)",
                   [(gid, p) for p in range(players)])
    db.execute("INSERT INTO vault_raw VALUES(?,?,'gz1',25,'now')", (gid, sha))
    db.commit()
    return path, sha


def trace_stub(monkeypatch, players=2):
    trace = types.SimpleNamespace(data=[{}] * players)
    calls = []
    monkeypatch.setattr(game_trace, "load_trace", lambda p: calls.append(p) or trace)
    monkeypatch.setattr(interactions, "detect_conversions", lambda t, p: [
        {"start_frame": -120 + p, "end_frame": 62 + p, "hits": 4, "damage": 40.5}])
    return trace, calls


def transport(monkeypatch, echo="conv"):
    calls, puts = [], []
    def call(url, payload):
        assert url == vault_client.FN_SYNC
        calls.append(payload)
        if payload["action"] == "mint":
            return {"kind": echo, "urls": {r["content_hash"]: "mock://conv/" + r["content_hash"]
                                           for r in payload["items"]}}
        assert payload["action"] == "commit"
        return {"saved": len(payload["games"])}
    monkeypatch.setattr(vault_client, "_call", call)
    monkeypatch.setattr(vault_client, "_put", lambda u, b: puts.append((u, b)))
    return calls, puts


def test_sidecar_true_frames_deterministic_gzip_and_exact_payload(db, tmp_path, monkeypatch):
    path, sha = game(db, tmp_path)
    _, parses = trace_stub(monkeypatch)
    calls, puts = transport(monkeypatch)
    result = vault_client.commit_pending_conversions("token", conn=db)
    assert result == {"pushed": 1, "skipped": 0, "failed": []}
    assert len(parses) == 1
    body = puts[0][1]
    assert body == vault_raw.build_conversions(str(path))
    assert body[4:8] == b"\0\0\0\0" and not body[3] & 8
    assert b" " not in gzip.decompress(body)
    assert json.loads(gzip.decompress(body)) == {
        "0": [{"start_frame": -120, "end_frame": 62, "hits": 4, "damage": 40.5}],
        "1": [{"start_frame": -119, "end_frame": 63, "hits": 4, "damage": 40.5}]}
    assert calls[0]["items"] == [{"content_hash": sha, "bytes": 1, "codec": "json-gz1"}]
    assert calls[1]["items"] == [{"content_hash": sha, "bytes": len(body), "codec": "json-gz1"}]
    assert calls[2]["games"] == [{"content_hash": sha, "conv_bytes": len(body)}]
    assert vault_client.commit_pending_conversions("token", conn=db)["pushed"] == 0
    assert len(calls) == 3


@pytest.mark.parametrize("echo", [None, "slp", "frames", "CONV"])
def test_old_server_refused_before_parse_put_or_commit(db, tmp_path, monkeypatch, echo):
    game(db, tmp_path)
    _, parses = trace_stub(monkeypatch)
    calls, puts = transport(monkeypatch, echo)
    with pytest.raises(vault_client.ConversionsUnsupported):
        vault_client.commit_pending_conversions("token", conn=db)
    assert len(calls) == 1 and not parses and not puts
    assert not indexer.kv_get(db, vault_client.RAW_RETRY_AFTER_KEY)


def test_probe_once_per_pass_and_every_upload_echo_guarded(db, tmp_path, monkeypatch):
    for gid in (1, 2, 3):
        game(db, tmp_path, gid)
    trace_stub(monkeypatch)
    monkeypatch.setattr(vault_client, "COMMIT_CHUNK", 1)
    calls, puts = transport(monkeypatch)
    assert vault_client.commit_pending_conversions("token", conn=db)["pushed"] == 3
    mints = [c for c in calls if c["action"] == "mint"]
    assert len(mints) == 4 and sum(c["items"][0]["bytes"] == 1 for c in mints) == 1
    db.execute("DELETE FROM vault_raw_conv")
    db.commit()
    original = vault_client._call
    def rollback(url, payload):
        out = original(url, payload)
        if payload["action"] == "mint" and payload["items"][0]["bytes"] != 1:
            out.pop("kind")
        return out
    monkeypatch.setattr(vault_client, "_call", rollback)
    with pytest.raises(vault_client.ConversionsUnsupported):
        vault_client.commit_pending_conversions("token", conn=db)
    assert len(puts) == 3  # no unsafe PUT after rollback


@pytest.mark.parametrize("players", [0, 1, 3, 4])
def test_only_two_indexed_players_eligible(db, tmp_path, monkeypatch, players):
    game(db, tmp_path, players=players)
    _, parses = trace_stub(monkeypatch)
    assert vault_client.commit_pending_conversions("token", conn=db)["pushed"] == 0
    assert not parses


def test_trace_roster_is_also_checked(db, tmp_path, monkeypatch):
    game(db, tmp_path)
    trace_stub(monkeypatch, 4)
    calls, puts = transport(monkeypatch)
    assert vault_client.commit_pending_conversions("token", conn=db)["skipped"] == 1
    assert len(calls) == 1 and not puts


def test_ack_only_duplicate_hash_ledger_and_account_reset(db, tmp_path, monkeypatch):
    for gid in (1, 2, 3):
        game(db, tmp_path, gid, body=b"same" if gid < 3 else b"other")
    trace_stub(monkeypatch)
    calls, puts = transport(monkeypatch)
    monkeypatch.setattr(vault_client, "_commit_games", lambda t, g: [g[-1]["content_hash"]])
    result = vault_client.commit_pending_conversions("token", conn=db)
    assert result["pushed"] == 2 and len(result["failed"]) == 1 and len(puts) == 2
    assert [r[0] for r in db.execute("SELECT game_id FROM vault_raw_conv ORDER BY game_id")] == [1, 2]
    vault_jobs.clear_account_sync_state(db)
    assert not db.execute("SELECT 1 FROM vault_raw_conv").fetchone()


@pytest.mark.parametrize("phase", ["before", "probe", "parse", "put", "commit"])
def test_conversion_cancellation_never_ledgers(db, tmp_path, monkeypatch, phase):
    game(db, tmp_path)
    trace_stub(monkeypatch)
    calls, puts = transport(monkeypatch)
    cancelled = phase == "before"
    def wrap(module, name, stage):
        original = getattr(module, name)
        def run(*args, **kwargs):
            nonlocal cancelled
            out = original(*args, **kwargs)
            if phase == stage:
                cancelled = True
            return out
        monkeypatch.setattr(module, name, run)
    wrap(vault_client, "_call", "probe")
    wrap(vault_raw, "build_conversions", "parse")
    wrap(vault_client, "_put", "put")
    wrap(vault_client, "_commit_games", "commit")
    with pytest.raises(vault_sync.SyncCancelled):
        vault_client.commit_pending_conversions("token", conn=db, should_cancel=lambda: cancelled)
    assert not db.execute("SELECT 1 FROM vault_raw_conv").fetchone()


@pytest.mark.parametrize("failure", ["missing", "changed", "parse", "put", "unacked"])
def test_sidecar_failures_remain_pending(db, tmp_path, monkeypatch, failure):
    path, _ = game(db, tmp_path)
    trace_stub(monkeypatch)
    transport(monkeypatch)
    if failure == "missing":
        path.unlink()
    elif failure == "changed":
        path.write_bytes(b"different replay length")
    elif failure == "parse":
        monkeypatch.setattr(game_trace, "load_trace", lambda p: None)
    elif failure == "put":
        monkeypatch.setattr(vault_client, "_put", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    else:
        monkeypatch.setattr(vault_client, "_commit_games", lambda *a: [])
    result = vault_client.commit_pending_conversions("token", conn=db)
    assert not result["pushed"] and (result["skipped"] or result["failed"])
    assert not db.execute("SELECT 1 FROM vault_raw_conv").fetchone()
    assert len(vault_raw.plan_conversions(db)) == 1


def test_share_mint_is_one_call_and_builds_nothing(db, tmp_path, monkeypatch):
    # A link is one database row: the page plays the game's own file.
    _, sha = game(db, tmp_path)
    monkeypatch.setattr(viz_export, "build_viz_bundle",
                        lambda *a, **kw: pytest.fail("built a share snapshot"))
    calls, response = [], {"id": "0123456789ab", "created": True}
    monkeypatch.setattr(vault_client, "_call",
                        lambda url, payload: calls.append((url, payload)) or response)
    assert vault_client.mint_share("token", sha) is response
    assert calls == [(vault_client.FN_PUBLIC,
                      {"action": "mint", "token": "token", "content_hash": sha})]


def test_share_mint_honours_cancellation(monkeypatch):
    cancelled = False

    def call(*a):
        nonlocal cancelled
        cancelled = True
        return {"id": "0123456789ab"}
    monkeypatch.setattr(vault_client, "_call", call)
    with pytest.raises(vault_sync.SyncCancelled):
        vault_client.mint_share("token", "hash", should_cancel=lambda: cancelled)


def test_raw_share_route_skips_frames_sync(db, tmp_path, monkeypatch):
    _, sha = game(db, tmp_path)
    calls = []
    monkeypatch.setattr(vault_client, "sync", lambda *a, **kw: pytest.fail("frames sync called"))
    def mint(token, content_hash, **kwargs):
        assert content_hash == sha and "conn" not in kwargs and not kwargs["should_cancel"]()
        calls.append(content_hash)
        return {"id": "0123456789ab"}
    monkeypatch.setattr(vault_client, "mint_share", mint)
    nodes = [n for n in ast.parse((BACKEND / "tracker/routes/share.py").read_text(encoding="utf8")).body
             if isinstance(n, ast.FunctionDef) and n.name == "share_link"]
    nodes[0].decorator_list = []
    ns = dict(request=request, jsonify=jsonify, sqlite3=sqlite3, indexer=indexer,
              vault_client=vault_client, vault_sync=vault_sync,
              _token_or_error=lambda: ("token", None), _stored_token=lambda c: "token")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "share-route", "exec"), ns)
    app = Flask(__name__)
    app.add_url_rule("/share", view_func=ns["share_link"], methods=["POST"])
    response = app.test_client().post("/share", json={"game_id": 1})
    assert response.status_code == 200 and response.json["url"].endswith("/0123456789ab")
    assert calls == [sha]


def test_worker_orders_combo_metadata_before_conversions_and_checks_credential(db, monkeypatch):
    order = []
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(vault_client, "commit_pending_combos",
                        lambda *a, **kw: order.append("combos") or {"refreshed": 2})
    def conversions(*a, **kw):
        order.append("conversions")
        assert not kw["should_cancel"]()
        indexer.kv_set(kw["conn"], vault_jobs.TOKEN_KEY, "new-token")
        assert kw["should_cancel"]()
        return {"pushed": 1, "failed": []}
    monkeypatch.setattr(vault_client, "commit_pending_conversions", conversions)
    generation = vault_jobs._credential_generation
    record = jobs.run_inline(vault_jobs.SYNC_KIND, lambda job: vault_jobs._sync(
        job, "token", generation, raw=True, combos_only=True))
    assert order == ["combos", "conversions"]
    assert record["result"]["conversions"] == 1
