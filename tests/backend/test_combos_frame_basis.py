"""Row-frame basis on rollback replays (the misaligned-clip fix).

Rollback netplay re-emits corrected frames as EXTRA post-frame events, and the
derived bundle keeps every one as a row — so `true_frame - start_frame` lands a
viewer earlier and earlier as re-emissions accumulate. extract_combos() now
records, next to the TRUE Slippi frames Dolphin seeks by, the row-frame basis
(first_frame + the port's post-frame ordinal, last occurrence wins) that bundle
viewers index by. On a clean replay the two are identical; each re-emission
before a combo shifts its row basis forward by one.
"""
import struct

import pytest

from tracker.combos import combo_index
from tracker.combos.combo_index import extract_combos
from tracker.store.slp_meta import HEADER, CMD_POST_FRAME

# Damage states per combos.py: _is_damaged = 0x4B..0x5B
DMG_STATE = 0x50
IDLE_STATE = 0x0E   # Wait


def _post_frame(frame, port, state, percent, last_attack, stocks, size):
    ev = bytearray(size)
    struct.pack_into(">i", ev, 0x0, frame)
    ev[0x4] = port
    ev[0x5] = 0  # leader
    struct.pack_into(">H", ev, 0x7, state)
    struct.pack_into(">f", ev, 0x15, percent)
    ev[0x1D] = last_attack
    ev[0x20] = stocks
    return bytes([CMD_POST_FRAME]) + bytes(ev)


def _build_slp(events, pf_size=0x21):
    """Minimal .slp: header + Event Payloads declaring only post-frame."""
    payloads = bytes([0x35, 4, CMD_POST_FRAME]) + struct.pack(">H", pf_size)
    raw = payloads + b"".join(events)
    return HEADER + struct.pack(">i", len(raw)) + raw


def _game(tmp_path, frames_spec, pf_size=0x21):
    """frames_spec: list of (frame, p0_percent, p1_state, p1_percent).
    Emits one post-frame per port per entry, in order — a repeated frame id
    models a rollback re-emission."""
    events = []
    for frame, p0_pct, p1_state, p1_pct in frames_spec:
        events.append(_post_frame(frame, 0, IDLE_STATE, p0_pct, 1, 4, pf_size))
        events.append(_post_frame(frame, 1, p1_state, p1_pct, 0, 4, pf_size))
    path = tmp_path / "g.slp"
    path.write_bytes(_build_slp(events, pf_size))
    return str(path)


def _spec_with_combo(start=-123):
    """Quiet lead-in, then a 3-hit combo on port 2 at frames 10..14."""
    spec = [(f, 0.0, IDLE_STATE, 0.0) for f in range(start, 10)]
    spec += [
        (10, 0.0, DMG_STATE, 10.0),
        (11, 0.0, DMG_STATE, 10.0),
        (12, 0.0, DMG_STATE, 22.0),
        (13, 0.0, DMG_STATE, 22.0),
        (14, 0.0, DMG_STATE, 31.0),
    ]
    # victim recovers; > COMBO_RESET_FRAMES of freedom closes the combo
    spec += [(f, 0.0, IDLE_STATE, 31.0)
             for f in range(15, 15 + combo_index.COMBO_RESET_FRAMES + 2)]
    return spec


def test_clean_replay_row_basis_equals_true_frames(tmp_path):
    path = _game(tmp_path, _spec_with_combo())
    out = extract_combos(path, [1, 2])
    assert len(out) == 1
    c = out[0]
    assert c["start_frame"] == 10
    assert c["start_rf"] == c["start_frame"]
    assert c["end_rf"] == c["end_frame"]


def test_rollback_reemissions_shift_row_basis_only(tmp_path):
    spec = _spec_with_combo()
    # three rollback re-emissions before the combo: frames 3,4,5 re-emitted
    # (corrected values, same content here) right after their originals
    for i, f in enumerate((3, 4, 5)):
        idx = spec.index((f, 0.0, IDLE_STATE, 0.0))
        spec.insert(idx + 1, (f, 0.0, IDLE_STATE, 0.0))
    path = _game(tmp_path, spec)
    out = extract_combos(path, [1, 2])
    assert len(out) == 1
    c = out[0]
    # TRUE frames are untouched — Dolphin seeking must not move
    assert c["start_frame"] == 10
    # the viewer basis absorbs the three extra rows
    assert c["start_rf"] == c["start_frame"] + 3
    assert c["end_rf"] == c["end_frame"] + 3


def test_upload_prefers_row_basis(tmp_path):
    """_combos_for ships start_rf/end_rf as the wire start/end_frame."""
    import sqlite3
    from tracker.cloud import vault_client

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE combos (
        game_id INTEGER, port INTEGER, character INTEGER, code TEXT,
        opp_character INTEGER, opp_code TEXT, start_frame INTEGER,
        end_frame INTEGER, hits INTEGER, damage REAL, did_kill INTEGER,
        moves_json TEXT, start_percent REAL, end_percent REAL,
        true_combo INTEGER, name TEXT, opp_name TEXT,
        start_rf INTEGER, end_rf INTEGER)""")
    # four moves: passes _worth_uploading's >= MIN_UPLOAD_MOVES(4) floor
    moves = ('[{"frame": 10, "move_id": 1, "hits": 1, "damage": 8.0},'
             ' {"frame": 20, "move_id": 2, "hits": 1, "damage": 8.0},'
             ' {"frame": 30, "move_id": 3, "hits": 1, "damage": 7.0},'
             ' {"frame": 40, "move_id": 4, "hits": 1, "damage": 7.0}]')
    conn.execute(
        "INSERT INTO combos VALUES (1,1,2,'A#1',9,'B#2',10,60,4,30.0,1,?,"
        "0.0,30.0,1,'a','b',13,63)", (moves,))
    conn.execute(
        "INSERT INTO combos VALUES (1,1,2,'A#1',9,'B#2',100,160,4,30.0,1,?,"
        "0.0,30.0,1,'a','b',NULL,NULL)", (moves,))
    out = vault_client._combos_for(conn, 1)
    assert [(c["start_frame"], c["end_frame"]) for c in out] == [
        (13, 63),      # row basis preferred
        (100, 160),    # pre-migration row falls back to true frames
    ]
