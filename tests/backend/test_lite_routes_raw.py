"""Local Watch Lite raw routes: synthetic files, a private index, no network."""
import gzip
import json
from types import SimpleNamespace

import pytest
from flask import Flask

from tracker.store import game_trace, indexer
from tracker.video import anim_fetch, clip_refs, clip_render, interactions


@pytest.fixture
def raw_lite(tmp_path, monkeypatch):
    # Importing the blueprint normally starts an optional geometry downloader.
    monkeypatch.setattr(anim_fetch, "ensure_anim_zips", lambda: None)
    from tracker.routes import lite, nucleome

    monkeypatch.setattr(nucleome, "NUCLEOME_ENABLED", True)
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "index.db")
    # Pytest can recycle a deleted parametrized tmp_path; schema caches must
    # belong to this fixture's database, not a prior incarnation of that path.
    monkeypatch.setattr(indexer, "_initialized_paths", set())
    monkeypatch.setattr(lite, "_pack_cache", {})
    replay = tmp_path / "synthetic.slp"
    replay.write_bytes(b"\x7b\x55\x03raw\x00synthetic\xff")
    directory = tmp_path / "directory.slp"
    directory.mkdir()
    conn = indexer.connect()
    for gid, path, parse_ok in [(1, replay, 1), (2, tmp_path / "missing.slp", 1),
                                (3, directory, 1), (4, replay, 0)]:
        # The index requires unique paths; the rejected entry need not exist.
        if gid == 4:
            path = tmp_path / "rejected.slp"
            path.write_bytes(b"not a replay")
        conn.execute("INSERT INTO games(id,path,mtime,size,parse_ok,last_frame) "
                     "VALUES (?,?,?,?,?,?)", (gid, str(path), 0, 16, parse_ok, 601))
    conn.execute("INSERT INTO game_players(game_id,port,type) VALUES (1,0,0),(1,1,0)")
    conn.commit()
    conn.close()
    trace = SimpleNamespace(n=4, data=[{}, {}],
                            at=lambda i: SimpleNamespace(slippi_frame=[-123, -122, 600, 601][i]))
    monkeypatch.setattr(game_trace, "load_trace", lambda path: trace)
    app = Flask(__name__)
    app.register_blueprint(nucleome.nucleome_bp)
    return SimpleNamespace(client=app.test_client(), replay=replay, trace=trace,
                           lite=lite, nucleome=nucleome)


def test_slp_streams_only_the_indexed_file(raw_lite, tmp_path):
    other = tmp_path / "private.txt"
    other.write_bytes(b"must not be served")
    response = raw_lite.client.get("/api/nucleome/lite/slp/1", query_string={"path": str(other)})
    assert response.status_code == 200
    assert response.mimetype == "application/octet-stream"
    assert response.data == raw_lite.replay.read_bytes()
    assert response.cache_control.private
    response.close()


@pytest.mark.parametrize("suffix", ["0", "2", "3", "4", "999", "-1", "private.txt",
                                    "..%2fprivate.txt", "%2e%2e%5cprivate.txt"])
def test_slp_missing_or_non_id_paths_are_404(raw_lite, suffix):
    assert raw_lite.client.get(f"/api/nucleome/lite/slp/{suffix}").status_code == 404


def test_slp_missing_after_lookup_is_404(raw_lite, monkeypatch):
    def gone(*args, **kwargs):
        raise FileNotFoundError
    monkeypatch.setattr(raw_lite.lite, "send_file", gone)
    assert raw_lite.client.get("/api/nucleome/lite/slp/1").status_code == 404


def test_resolve_preserves_true_frames(raw_lite):
    ref = clip_refs.mint(1, 500, 600)
    response = raw_lite.client.get(f"/api/nucleome/lite/clip-ref/{ref}/resolve")
    assert response.status_code == 200
    # Only four synthetic trace rows: using start_frame+n would reject this.
    assert response.json == {"game_id": 1, "start_frame": 500, "end_frame": 600}


@pytest.mark.parametrize("window", [(700, 800), (-500, -200), (600, 500), (500, 500)])
def test_resolve_recovers_invalid_window(raw_lite, window):
    conn = indexer.connect()
    conn.execute("INSERT INTO combos(game_id,port,opp_port,start_frame,end_frame,damage) "
                 "VALUES (1,0,1,10,20,5),(1,0,1,500,550,90)")
    conn.commit()
    conn.close()
    ref = clip_refs.mint(1, *window)
    assert raw_lite.client.get(f"/api/nucleome/lite/clip-ref/{ref}/resolve").json == {
        "game_id": 1, "start_frame": 500, "end_frame": 550}


def test_resolve_without_combos_selects_uncapped_whole_game(raw_lite):
    ref = clip_refs.mint(1, 700, 800)
    assert raw_lite.client.get(f"/api/nucleome/lite/clip-ref/{ref}/resolve").json == {
        "game_id": 1, "start_frame": None, "end_frame": None}


def test_resolve_unknown_ref_or_missing_replay(raw_lite):
    for ref in ["fabricated", "'OR'1'='1", clip_refs.mint(2, 0, 50), clip_refs.mint(4, 0, 50)]:
        assert raw_lite.client.get(f"/api/nucleome/lite/clip-ref/{ref}/resolve").status_code == 404


def test_resolve_unparseable_replay(raw_lite, monkeypatch):
    monkeypatch.setattr(game_trace, "load_trace", lambda path: None)
    ref = clip_refs.mint(1, 0, 50)
    assert raw_lite.client.get(f"/api/nucleome/lite/clip-ref/{ref}/resolve").status_code == 422


def test_pack_full_shape_gzip_negotiation_and_cache(raw_lite, monkeypatch):
    calls = []
    pack = {"Wait": ["M0 0", "M1 1"], "AttackAirF": ["M2 2"]}
    def load(cid):
        calls.append(cid)
        return pack
    monkeypatch.setattr(clip_render, "_load_char", load)
    url = "/api/nucleome/lite/pack/11"
    plain = raw_lite.client.get(url)
    assert plain.status_code == 200 and plain.json == pack
    assert "Content-Encoding" not in plain.headers
    assert plain.cache_control.max_age > 0 and plain.cache_control.private
    assert "Accept-Encoding" in plain.vary
    zipped = raw_lite.client.get(url, headers={"Accept-Encoding": "br, gzip;q=0.5"})
    assert zipped.mimetype == "application/json"
    assert zipped.headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(zipped.data)) == pack
    refused = raw_lite.client.get(url, headers={"Accept-Encoding": "gzip;q=0, *;q=1"})
    assert "Content-Encoding" not in refused.headers and refused.json == pack
    assert calls == [11]
    assert raw_lite.client.get(url, headers={"If-None-Match": plain.headers["ETag"]}).status_code == 304


def test_a_character_downloaded_after_a_miss_loads(tmp_path, monkeypatch):
    """Lite asked before the background download had this zip: the miss must
    not stick for the rest of the session."""
    import zipfile
    monkeypatch.setattr(clip_render, "_anim_cache", {})
    found = {}
    monkeypatch.setattr(clip_render, "zip_path", lambda name: found.get(name))
    assert clip_render._load_char(1) == {}
    path = tmp_path / "fox.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Wait.json", json.dumps(["M0 0"]))
    found["fox"] = str(path)
    assert clip_render._load_char(1) == {"Wait": ["M0 0"]}


def test_pack_missing_or_invalid_character(raw_lite, monkeypatch):
    monkeypatch.setattr(clip_render, "_load_char", lambda cid: {})
    for cid in [1, 27, 999, -1, "..%2fprivate"]:
        assert raw_lite.client.get(f"/api/nucleome/lite/pack/{cid}").status_code == 404
    # A failed fetch is not cached by the route.
    monkeypatch.setattr(clip_render, "_load_char", lambda cid: {"Wait": ["M0 0"]})
    assert raw_lite.client.get("/api/nucleome/lite/pack/1").status_code == 200


def test_conversions_returns_both_ports_without_rebasing(raw_lite, monkeypatch):
    calls = []
    def detect(trace, port):
        assert trace is raw_lite.trace
        calls.append(port)
        return [{"start_frame": 500 + port, "end_frame": 600,
                 "start": {"slippi_frame": 500 + port}, "evidence": {"hits": 2}}]
    monkeypatch.setattr(interactions, "detect_conversions", detect)
    response = raw_lite.client.get("/api/nucleome/lite/conversions/1?conversions=1")
    assert response.status_code == 200 and calls == [0, 1]
    assert response.json["0"][0]["start_frame"] == 500
    assert response.json["1"][0]["start"]["slippi_frame"] == 501
    assert response.json["0"][0]["evidence"] == {"hits": 2}


@pytest.mark.parametrize("ports", [1, 3, 4])
def test_conversions_only_for_two_players(raw_lite, monkeypatch, ports):
    conn = indexer.connect()
    conn.execute("DELETE FROM game_players WHERE game_id=1")
    conn.executemany("INSERT INTO game_players(game_id,port,type) VALUES (1,?,0)",
                     [(port,) for port in range(ports)])
    conn.commit()
    conn.close()
    def unexpected(*args):
        pytest.fail("conversion parsing must not run outside two-player games")
    monkeypatch.setattr(game_trace, "load_trace", unexpected)
    monkeypatch.setattr(interactions, "detect_conversions", unexpected)
    assert raw_lite.client.get("/api/nucleome/lite/conversions/1?conversions=1").json == {}


def test_conversions_missing_and_unparseable(raw_lite, monkeypatch):
    for gid in [2, 3, 4, 999]:
        assert raw_lite.client.get(f"/api/nucleome/lite/conversions/{gid}").status_code == 404
    monkeypatch.setattr(game_trace, "load_trace", lambda path: None)
    assert raw_lite.client.get("/api/nucleome/lite/conversions/1").status_code == 422


@pytest.mark.parametrize("path", ["slp/1", "clip-ref/any/resolve", "pack/1", "conversions/1"])
def test_raw_routes_share_the_nucleome_gate(raw_lite, monkeypatch, path):
    monkeypatch.setattr(raw_lite.nucleome, "NUCLEOME_ENABLED", False)
    response = raw_lite.client.get(f"/api/nucleome/lite/{path}")
    assert response.status_code == 404
    assert "not available in this build" in response.json["error"]
