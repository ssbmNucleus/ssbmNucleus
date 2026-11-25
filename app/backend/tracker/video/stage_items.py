"""stage_items — projectiles/items + stage-state events from the raw .slp stream.

peppi_py's high-level API hands us fighter frames but (in the builds we ship)
no Item Update frames and none of the 3.18+ stage events, so Falco lasers,
needles, turnips, and Pokemon Stadium transformations were simply invisible in
Watch Lite. This module walks the raw UBJSON event block itself — the same
fixed-size-event walk slp_meta.read_final_stocks does — and pulls out:

  - Item Update (0x3B, slp >= 3.0.0 — present in every replay back to 2020):
    one "track" per contiguous life of a spawn id, with per-frame position,
    facing and state. Spawn ids are recycled by the game, so a frame gap or a
    type change under the same id starts a new track.
  - Fountain of Dreams platform heights (0x3F) and Pokemon Stadium
    transformations (0x41), both declared from slp 3.18.0 (2024+) — older
    files just yield empty lists.

Rollbacks: netplay replays re-emit events for rolled-back frames, so per spawn
id the frame sequence can repeat or step backwards. We treat a re-emitted frame
as authoritative (truncate the track back to it and continue), matching how the
fighter frame parsers resolve rollbacks — last write wins.

Everything here mirrors read_final_stocks' defensive stance: any malformed,
truncated, or still-being-written file returns empty structures, never raises.
"""
import struct

from ..store.slp_meta import (HEADER, MAX_SLP_BYTES, RAW_START, SlpParseError,
                              _parse_payload_sizes)

CMD_ITEM_UPDATE = 0x3B
CMD_FOD_PLATFORM = 0x3F
CMD_STADIUM_TRANSFORM = 0x41

# Item Update payload offsets (relative to the byte AFTER the command byte;
# the SPEC.md table counts the command byte at 0x0, so these are spec - 1).
_ITEM_FRAME_OFF = 0x00      # int32  frame number
_ITEM_TYPE_OFF = 0x04       # uint16 item type id
_ITEM_STATE_OFF = 0x06      # uint8  item state
_ITEM_FACING_OFF = 0x07     # float  facing direction (-1/+1, NaN for some)
_ITEM_XPOS_OFF = 0x13       # float  x position
_ITEM_YPOS_OFF = 0x17       # float  y position
_ITEM_SPAWN_OFF = 0x21      # uint32 spawn id
_ITEM_OWNER_OFF = 0x29      # int8   owner port index, -1 = none (slp >= 3.6)
_ITEM_MIN_SIZE = _ITEM_SPAWN_OFF + 4   # enough for everything through spawn id

# Hard cap on distinct item tracks kept in memory. A pathological / corrupt
# file that "spawns" garbage every event must not balloon a library sync; a
# real game is a few hundred tracks at most (an 18k-event laser game is ~1.5k).
MAX_ITEM_TRACKS = 5000


def _read_raw_block(path):
    """(data, sizes, first_event_off, raw_end) for the raw event block, or
    None on any structural problem. `data` is the file's bytes from offset 0
    through the end of the raw block — event offsets index into it directly."""
    import os
    try:
        size = os.path.getsize(path)
        if size > MAX_SLP_BYTES:
            return None
        with open(path, "rb") as f:
            head = f.read(4096)
            if not head.startswith(HEADER):
                return None
            raw_len = struct.unpack(
                ">i", head[len(HEADER):len(HEADER) + 4])[0]
            if raw_len <= 0:
                # Killed sessions leave the raw length 0; locate the metadata
                # footer from the tail instead (same recovery as parse_slp).
                f.seek(max(0, size - 65536))
                tail_chunk = f.read()
                idx = tail_chunk.rfind(b"U\x08metadata{")
                if idx < 0:
                    return None
                raw_len = (max(0, size - 65536) + idx) - RAW_START
                if raw_len <= 0:
                    return None
            sizes, first_off = _parse_payload_sizes(head)
            raw_end = min(RAW_START + raw_len, size)
            f.seek(0)
            data = f.read(raw_end)
    except (OSError, SlpParseError, struct.error, IndexError):
        return None
    if first_off >= len(data):
        return None
    return data, sizes, first_off, raw_end


def _scan(path, sizes=None, want_items=True, want_stage=True):
    """One pass over the raw event stream collecting item tracks and stage
    events. Returns (items, stage) — empty structures on any failure.

    `sizes` may be a pre-parsed {cmd: payload_size} table (callers that
    already walked the header can pass it); the file's own table is
    authoritative when None.
    """
    items = {}
    stage = {"fod": [], "stadium": []}
    blk = _read_raw_block(path)
    if blk is None:
        return items, stage
    data, file_sizes, pos, end = blk
    sizes = file_sizes if sizes is None else sizes

    item_size = sizes.get(CMD_ITEM_UPDATE)
    parse_items = (want_items and item_size is not None
                   and item_size >= _ITEM_MIN_SIZE)
    has_owner = parse_items and item_size >= _ITEM_OWNER_OFF + 1
    fod_size = sizes.get(CMD_FOD_PLATFORM)
    std_size = sizes.get(CMD_STADIUM_TRANSFORM)

    # live[spawn_id] = the currently-open track dict for that spawn id.
    # A track closes when its spawn id jumps (frame gap / rewind past its
    # start / type change) — the id was recycled for a new item.
    live = {}
    n_tracks = 0
    unpack_i32 = struct.Struct(">i").unpack_from
    unpack_u16 = struct.Struct(">H").unpack_from
    unpack_u32 = struct.Struct(">I").unpack_from
    unpack_f32 = struct.Struct(">f").unpack_from

    try:
        while pos < end:
            cmd = data[pos]
            sz = sizes.get(cmd)
            if not sz:
                break   # unknown (or empty) event = can't safely skip; keep what we have
            p = pos + 1
            if p + sz > end:
                break   # truncated final event
            if parse_items and cmd == CMD_ITEM_UPDATE:
                frame = unpack_i32(data, p + _ITEM_FRAME_OFF)[0]
                spawn = unpack_u32(data, p + _ITEM_SPAWN_OFF)[0]
                typ = unpack_u16(data, p + _ITEM_TYPE_OFF)[0]
                tr = live.get(spawn)
                if tr is not None and (tr["type"] != typ
                                       or frame < tr["start"]
                                       or frame > tr["start"] + len(tr["x"])):
                    # id recycled for a different item, or a frame gap: the
                    # old item died off-camera. Close it; open a new life.
                    tr = None
                if tr is None:
                    if n_tracks >= MAX_ITEM_TRACKS:
                        pos += 1 + sz
                        continue        # memory cap: ignore further new items
                    owner = -1
                    if has_owner:
                        owner = struct.unpack_from(
                            ">b", data, p + _ITEM_OWNER_OFF)[0]
                    tr = {"type": typ, "owner": owner, "start": frame,
                          "x": [], "y": [], "dir": [], "state": []}
                    live[spawn] = tr
                    items.setdefault(spawn, []).append(tr)
                    n_tracks += 1
                idx = frame - tr["start"]
                if idx < len(tr["x"]):
                    # rollback re-emit: the new timeline is authoritative —
                    # rewind the track to this frame and re-append.
                    del tr["x"][idx:]
                    del tr["y"][idx:]
                    del tr["dir"][idx:]
                    del tr["state"][idx:]
                facing = unpack_f32(data, p + _ITEM_FACING_OFF)[0]
                d = 1 if facing > 0 else (-1 if facing < 0 else 0)  # NaN -> 0
                tr["x"].append(round(unpack_f32(data, p + _ITEM_XPOS_OFF)[0], 1))
                tr["y"].append(round(unpack_f32(data, p + _ITEM_YPOS_OFF)[0], 1))
                tr["dir"].append(d)
                tr["state"].append(data[p + _ITEM_STATE_OFF])
            elif want_stage and cmd == CMD_FOD_PLATFORM and sz >= 9:
                # payload: frame i32 @0, platform u8 @4 (0=right 1=left),
                # height f32 @5 (spec offsets minus the command byte)
                stage["fod"].append((unpack_i32(data, p)[0],
                                     data[p + 4],
                                     round(unpack_f32(data, p + 5)[0], 2)))
            elif want_stage and cmd == CMD_STADIUM_TRANSFORM and sz >= 8:
                # payload: frame i32 @0, transformation event u16 @4,
                # transformation id u16 @6
                stage["stadium"].append((unpack_i32(data, p)[0],
                                         unpack_u16(data, p + 4)[0],
                                         unpack_u16(data, p + 6)[0]))
            pos += 1 + sz
    except (struct.error, IndexError):
        pass    # keep whatever parsed cleanly before the corruption

    # Rollbacks can re-emit stage events too: keep the LAST occurrence per
    # (frame, platform) / per frame, in frame order, so consumers can replay
    # the lists as a simple monotone timeline.
    if stage["fod"]:
        dedup = {}
        for frame, plat, height in stage["fod"]:
            dedup[(frame, plat)] = (frame, plat, height)
        stage["fod"] = sorted(dedup.values())
    if stage["stadium"]:
        dedup = {}
        for frame, ev, tid in stage["stadium"]:
            dedup[frame] = (frame, ev, tid)
        stage["stadium"] = sorted(dedup.values())
    return items, stage


def _flatten_items(items):
    """{spawn_id: [track, ...]} -> {spawn_id: track} for the single-life case,
    keeping the public contract of one dict entry per contiguous life. Recycled
    ids get synthetic keys "id#n" so no life is silently dropped."""
    out = {}
    for spawn, tracks in items.items():
        for n, tr in enumerate(tracks):
            out[spawn if n == 0 else f"{spawn}#{n}"] = tr
    return out


def read_items(path, sizes=None):
    """All item lives in a replay:

        {spawn_id: {"type": int, "owner": int (port index, -1 = none),
                    "start": first Slippi frame, "x": [...], "y": [...],
                    "dir": [...], "state": [...]}}

    x/y rounded to 1 decimal; arrays are per-frame from "start". Recycled
    spawn ids yield one entry per life (later lives keyed "id#n"). Returns {}
    for files with no items or on any parse problem — never raises."""
    items, _ = _scan(path, sizes=sizes, want_stage=False)
    return _flatten_items(items)


def read_stage_events(path):
    """Dynamic-stage events (slp >= 3.18, 2024+ replays; empty lists before):

        {"fod":     [(frame, platform, height), ...],   # platform 0=right 1=left
         "stadium": [(frame, transformation_event, transformation_id), ...]}

    Never raises; malformed files return the empty structure."""
    _, stage = _scan(path, want_items=False)
    return stage


def read_items_and_stage(path):
    """Both of the above from a single walk of the file — what the viz bundle
    exporter calls, since it always wants both."""
    items, stage = _scan(path)
    return _flatten_items(items), stage


if __name__ == "__main__":
    import json
    import sys
    items, stage = read_items_and_stage(sys.argv[1])
    print(f"{len(items)} item tracks")
    by_type = {}
    for tr in items.values():
        by_type.setdefault(tr["type"], []).append(len(tr["x"]))
    for t, lens in sorted(by_type.items()):
        print(f"  type {t:3d}: {len(lens)} tracks, avg life "
              f"{sum(lens) / len(lens):.0f} frames")
    print("fod events:", len(stage["fod"]),
          "stadium events:", len(stage["stadium"]))
    if stage["stadium"]:
        print(json.dumps(stage["stadium"][:10]))
