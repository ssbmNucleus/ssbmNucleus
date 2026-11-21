"""Full-game playlist entries (Replays tab multi-select -> Watch / record as
playlist). A `full: true` clip plays the WHOLE game: -123 to the indexed
last_frame, unpadded, with the frames taken from the index rather than the
client. Combo clips keep their 60-in / 90-out padding. Temp DB, no Dolphin.
"""
import json
import uuid
from pathlib import Path

import pytest
from flask import Flask

import tracker.routes.nucleome as bp_module
import tracker.routes.watch as watch_routes
from tracker.replays import watch_options
from tracker.store import indexer
from tracker.replays import watch_mods


@pytest.fixture
def env(monkeypatch):
    # pytest's Windows tmp_path forces mode 0700 (unusable here) — same local
    # mkdir-backed pattern as test_vault_blueprint.py
    test_dir = Path(__file__).parent / f".playlist-full-tmp-{uuid.uuid4().hex[:8]}"
    test_dir.mkdir()
    db_path = test_dir / "nucleome.db"
    monkeypatch.setattr(indexer, "DB_PATH", db_path)
    app = Flask(__name__)
    app.register_blueprint(bp_module.nucleome_bp)
    yield app.test_client(), test_dir
    indexer._initialized_paths.discard(str(db_path))
    for p in test_dir.iterdir():
        p.unlink(missing_ok=True)
    test_dir.rmdir()


def _add_game(test_dir, gid, last_frame, stage=31, players=None):
    slp = test_dir / f"game{gid}.slp"
    slp.write_bytes(b"x")
    players = players or [{"port": 0, "character": 2, "costume": 1},
                          {"port": 1, "character": 20, "costume": 0}]
    conn = indexer.connect()
    try:
        conn.execute(
            "INSERT INTO games (id, path, mtime, size, parse_ok, start_at, stage,"
            " is_teams, last_frame, duration_s, players) VALUES"
            " (?, ?, 0, 1, 1, '2026-09-01T10:00:00', ?, 0, ?, ?, ?)",
            (gid, str(slp), stage, last_frame,
             None if last_frame is None else (last_frame + 123) / 60.0,
             json.dumps(players)))
        conn.commit()
    finally:
        conn.close()


def _resolve(clips):
    conn = indexer.connect()
    try:
        return watch_options._resolve_clip_entries(conn, clips)
    finally:
        conn.close()


def test_full_game_uses_index_frames_unpadded(env):
    _client, d = env
    _add_game(d, 1, 8000)
    _add_game(d, 2, 5400)
    # the client's frames are ignored for a full game: the index is the truth
    _rows, entries = _resolve([
        {"game_id": 2, "full": True, "start_frame": 0, "end_frame": 99},
        {"game_id": 1, "full": True},
    ])
    assert [(e["game_id"], e["startFrame"], e["endFrame"]) for e in entries] == [
        (2, -123, 5400), (1, -123, 8000)]


def test_full_game_falls_back_to_client_end_without_last_frame(env):
    _client, d = env
    _add_game(d, 1, None)
    _add_game(d, 2, None)
    _rows, entries = _resolve([
        {"game_id": 1, "full": True, "start_frame": -123, "end_frame": 3000},
        {"game_id": 2, "full": True},  # nothing to go on -> dropped
    ])
    assert [(e["game_id"], e["startFrame"], e["endFrame"]) for e in entries] == [
        (1, -123, 3000)]


def test_combo_clips_keep_padding(env):
    _client, d = env
    _add_game(d, 1, 8000)
    _rows, entries = _resolve([{"game_id": 1, "start_frame": 500, "end_frame": 700},
                               {"game_id": 1, "start_frame": -100, "end_frame": 50}])
    assert [(e["startFrame"], e["endFrame"]) for e in entries] == [
        (440, 790), (-123, 140)]


def test_full_games_respect_the_playlist_cap(env, monkeypatch):
    _client, d = env
    _add_game(d, 1, 8000)
    monkeypatch.setattr(watch_options, "PLAYLIST_CLIP_CAP", 3)
    _rows, entries = _resolve([{"game_id": 1, "full": True}] * 10)
    assert len(entries) == 3


def test_playlist_start_passes_full_games_to_the_job(env, monkeypatch):
    client, d = env
    _add_game(d, 1, 8000)
    _add_game(d, 2, 5400, stage=8)
    iso = d / "vanilla.iso"
    iso.write_bytes(b"x")
    monkeypatch.setattr(watch_routes, "_launcher_vanilla_iso", lambda: str(iso))
    monkeypatch.setattr(watch_routes, "load_metadata", lambda: {})
    seen = {}

    def fake_start(path, vanilla, selections, **kw):
        seen.update(path=path, selections=selections, **kw)
        return "watch-1"

    monkeypatch.setattr(watch_mods, "start_job", fake_start)
    r = client.post("/api/nucleome/watch-mods/playlist-start", json={
        "clips": [{"game_id": 1, "full": True, "start_frame": -123, "end_frame": 8000},
                  {"game_id": 2, "full": True, "start_frame": -123, "end_frame": 5400}],
        "record": True, "widescreen": True, "no_music": True,
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["clip_count"] == 2
    assert seen["record"] is True and seen["widescreen"] is True
    assert seen["no_music"] is True
    assert [(c["startFrame"], c["endFrame"]) for c in seen["clip"]] == [
        (-123, 8000), (-123, 5400)]


def test_query_games_exposes_last_frame(env):
    _client, d = env
    _add_game(d, 1, 8000)
    conn = indexer.connect()
    try:
        games = indexer.query_games(conn, [])
    finally:
        conn.close()
    assert games["games"][0]["last_frame"] == 8000
