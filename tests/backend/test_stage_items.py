"""stage_items — items + stage events walked straight off the raw .slp stream.

Pins the contract Watch Lite relies on: item tracks carry TRUE Slippi frames
(`start`), rollback re-emissions rewind a track (last write wins), recycled
spawn ids become separate lives, stage events are deduped last-wins in frame
order, and nothing malformed ever raises.

Fixtures are tiny raw event streams built in-test (no peppi needed; the
GameTrace alignment of item frames is pinned in test_game_trace.py).
"""
import math
import struct

import pytest

from tracker.video import stage_items
from tracker.video.stage_items import (read_items, read_items_and_stage,
                                          read_stage_events)

HEADER = b"{U\x03raw[$U#l"
FOOTER = b"U\x08metadata{}}"
CMD_PAYLOADS, CMD_GAME_START, CMD_POST = 0x35, 0x36, 0x38
CMD_ITEM, CMD_FOD, CMD_STADIUM = 0x3B, 0x3F, 0x41

GS_SIZE, POST_SIZE = 0x20, 0x21       # contents irrelevant to stage_items
ITEM_SIZE = 0x2A                       # slp 3.6+: through the owner byte
ITEM_SIZE_PRE_OWNER = 0x25             # slp 3.0-3.1: through spawn id
LASER, NEEDLE = 0x36, 0x37


def item(frame, spawn, x=0.0, y=0.0, typ=LASER, state=1, facing=1.0,
         owner=0, size=ITEM_SIZE):
    ev = bytearray(size)
    struct.pack_into(">i", ev, 0x00, frame)
    struct.pack_into(">H", ev, 0x04, typ)
    ev[0x06] = state
    struct.pack_into(">f", ev, 0x07, facing)
    struct.pack_into(">f", ev, 0x13, x)
    struct.pack_into(">f", ev, 0x17, y)
    struct.pack_into(">I", ev, 0x21, spawn)
    if size > 0x29:
        struct.pack_into(">b", ev, 0x29, owner)
    return bytes([CMD_ITEM]) + bytes(ev)


def fod(frame, platform, height):
    return bytes([CMD_FOD]) + struct.pack(">iBf", frame, platform, height)


def stadium(frame, event, tid):
    return bytes([CMD_STADIUM]) + struct.pack(">iHH", frame, event, tid)


def post(frame, port=0):
    ev = bytearray(POST_SIZE)
    struct.pack_into(">i", ev, 0, frame)
    ev[4] = port
    return bytes([CMD_POST]) + bytes(ev)


def build(events, item_size=ITEM_SIZE, stage_events=True, raw_len=None,
          footer=True):
    sizes = {CMD_GAME_START: GS_SIZE, CMD_POST: POST_SIZE, CMD_ITEM: item_size}
    if stage_events:
        sizes.update({CMD_FOD: 9, CMD_STADIUM: 8})
    table = bytes([CMD_PAYLOADS, 3 * len(sizes) + 1])
    table += b"".join(bytes([c]) + struct.pack(">H", s)
                      for c, s in sizes.items())
    raw = table + bytes([CMD_GAME_START]) + bytes(GS_SIZE) + b"".join(events)
    n = len(raw) if raw_len is None else raw_len
    return HEADER + struct.pack(">i", n) + raw + (FOOTER if footer else b"")


def write(tmp_path, data, name="g.slp"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


EMPTY_STAGE = {"fod": [], "stadium": []}


def test_item_track_carries_true_frames_position_facing_and_owner(tmp_path):
    """One laser over 4 frames -> one track keyed by spawn id, TRUE start frame."""
    evs = []
    for f in range(10, 14):
        evs += [post(f), item(f, spawn=7, x=1.26 + f, y=-2.0, facing=-1.0,
                              owner=1, state=3)]
    tracks = read_items(write(tmp_path, build(evs)))
    assert list(tracks) == [7]
    tr = tracks[7]
    assert tr["start"] == 10 and tr["type"] == LASER and tr["owner"] == 1
    assert tr["x"] == [11.3, 12.3, 13.3, 14.3]          # rounded to 0.1
    assert tr["y"] == [-2.0] * 4
    assert tr["dir"] == [-1] * 4 and tr["state"] == [3] * 4


def test_nan_facing_maps_to_zero(tmp_path):
    """Items with NaN facing (some projectiles) get dir 0, not a crash."""
    path = write(tmp_path, build([item(5, spawn=1, facing=math.nan)]))
    assert read_items(path)[1]["dir"] == [0]


def test_rollback_reemit_rewinds_the_track_last_write_wins(tmp_path):
    """Re-emitted frames overwrite in place: one row per frame, corrected values."""
    evs = [item(f, spawn=3, x=float(f)) for f in (10, 11, 12)]
    evs += [item(f, spawn=3, x=100.0 + f) for f in (11, 12)]   # resimulated
    evs += [item(13, spawn=3, x=113.0)]
    tr = read_items(write(tmp_path, build(evs)))[3]
    assert tr["start"] == 10
    assert tr["x"] == [10.0, 111.0, 112.0, 113.0]
    assert len(tr["x"]) == len(tr["y"]) == len(tr["dir"]) == len(tr["state"])


def test_recycled_spawn_id_yields_separate_lives(tmp_path):
    """Type change or frame gap under one spawn id starts a new keyed life."""
    evs = [item(f, spawn=9, typ=LASER) for f in (10, 11)]
    evs += [item(f, spawn=9, typ=NEEDLE) for f in (12, 13)]      # type change
    evs += [item(f, spawn=9, typ=NEEDLE) for f in (40, 41, 42)]  # frame gap
    tracks = read_items(write(tmp_path, build(evs)))
    assert sorted(tracks, key=str) == [9, "9#1", "9#2"]
    assert (tracks[9]["start"], tracks[9]["type"], len(tracks[9]["x"])) == (
        10, LASER, 2)
    assert (tracks["9#1"]["start"], tracks["9#1"]["type"]) == (12, NEEDLE)
    assert (tracks["9#2"]["start"], len(tracks["9#2"]["x"])) == (40, 3)


def test_old_item_payload_without_owner_reports_minus_one(tmp_path):
    """Pre-3.6 item payloads (no owner byte) still parse, owner = -1."""
    evs = [item(f, spawn=2, x=float(f), size=ITEM_SIZE_PRE_OWNER)
           for f in (0, 1)]
    tr = read_items(write(tmp_path, build(evs,
                                          item_size=ITEM_SIZE_PRE_OWNER)))[2]
    assert tr["owner"] == -1 and tr["x"] == [0.0, 1.0]


def test_item_payload_too_small_is_skipped_not_misread(tmp_path):
    """An item payload shorter than the spawn-id field yields no tracks."""
    small = 0x20
    evs = [bytes([CMD_ITEM]) + bytes(small)] * 3 + [stadium(5, 2, 4)]
    path = write(tmp_path, build(evs, item_size=small))
    assert read_items(path) == {}
    assert read_stage_events(path)["stadium"] == [(5, 2, 4)]   # walk continues


def test_stage_events_dedup_last_wins_in_frame_order(tmp_path):
    """Stadium/FoD events re-emitted by rollback keep the LAST, sorted by frame."""
    evs = [stadium(300, 2, 5), stadium(100, 2, 3), stadium(100, 2, 4),
           fod(50, 1, 10.0), fod(20, 0, 5.5), fod(50, 1, 12.25),
           fod(50, 0, 1.0)]
    stage = read_stage_events(write(tmp_path, build(evs)))
    assert stage["stadium"] == [(100, 2, 4), (300, 2, 5)]
    assert stage["fod"] == [(20, 0, 5.5), (50, 0, 1.0), (50, 1, 12.25)]


def test_files_without_stage_event_payloads_yield_empty_lists(tmp_path):
    """Pre-3.18 replays (no 0x3F/0x41 declared) give the empty structure."""
    path = write(tmp_path, build([item(1, spawn=1)], stage_events=False))
    assert read_stage_events(path) == EMPTY_STAGE
    assert list(read_items(path)) == [1]


def test_combined_walk_matches_separate_reads(tmp_path):
    """read_items_and_stage == (read_items, read_stage_events) in one pass."""
    evs = [item(f, spawn=4, x=float(f)) for f in range(3)]
    evs += [stadium(2, 1, 1), fod(1, 0, 3.0)]
    path = write(tmp_path, build(evs))
    assert read_items_and_stage(path) == (read_items(path),
                                          read_stage_events(path))


def test_unfinished_file_recovers_raw_block_from_metadata_footer(tmp_path):
    """raw length 0 (killed session) -> raw block ends at the metadata footer."""
    evs = [item(f, spawn=1, x=float(f)) for f in range(4)] + [stadium(3, 1, 2)]
    items, stage = read_items_and_stage(write(tmp_path, build(evs, raw_len=0)))
    assert items[1]["x"] == [0.0, 1.0, 2.0, 3.0]
    assert stage["stadium"] == [(3, 1, 2)]


def test_truncated_final_event_keeps_everything_before_it(tmp_path):
    """A replay cut mid-event (still being written) keeps the clean prefix."""
    evs = [item(f, spawn=1, x=float(f)) for f in range(5)]
    data = build(evs)
    cut = data[:-len(FOOTER) - 10]                     # last item half-written
    tr = read_items(write(tmp_path, cut))[1]
    assert tr["x"] == [0.0, 1.0, 2.0, 3.0]


def test_unknown_event_stops_the_walk_but_keeps_the_prefix(tmp_path):
    """An undeclared command can't be skipped safely: stop, keep prior events."""
    evs = [item(0, spawn=1), item(1, spawn=1), bytes([0x77]) + bytes(40),
           item(2, spawn=1)]
    tr = read_items(write(tmp_path, build(evs)))[1]
    assert len(tr["x"]) == 2


def test_item_track_count_is_capped(tmp_path, monkeypatch):
    """A garbage-spawning file can't grow tracks past MAX_ITEM_TRACKS."""
    monkeypatch.setattr(stage_items, "MAX_ITEM_TRACKS", 3)
    evs = [item(0, spawn=s) for s in range(10)]
    assert len(read_items(write(tmp_path, build(evs)))) == 3


@pytest.mark.parametrize("data", [
    b"",
    b"not a replay at all" * 50,
    HEADER,
    HEADER + struct.pack(">i", 0),                    # raw len 0, no footer
    HEADER + struct.pack(">i", 500) + b"\x35",        # payload table cut off
    HEADER + struct.pack(">i", 40) + bytes([0x36, 4]) + bytes(60),  # no 0x35
], ids=["empty", "garbage", "header_only", "rawlen0_no_footer",
        "cut_payload_table", "first_event_not_payloads"])
def test_malformed_files_never_raise(tmp_path, data):
    """Corrupt input yields empty structures from every reader."""
    path = write(tmp_path, data)
    assert read_items(path) == {}
    assert read_stage_events(path) == EMPTY_STAGE
    assert read_items_and_stage(path) == ({}, EMPTY_STAGE)


def test_missing_file_never_raises(tmp_path):
    """A replay deleted between index and read gives empty structures."""
    path = str(tmp_path / "gone.slp")
    assert read_items(path) == {}
    assert read_stage_events(path) == EMPTY_STAGE
