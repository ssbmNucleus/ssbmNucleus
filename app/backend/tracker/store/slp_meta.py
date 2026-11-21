"""Dependency-free .slp metadata reader for the nucleOME replay browser.

Reads ONLY the cheap parts of a Slippi replay — no frame data, no external
parser: a few KB per file instead of the whole thing.

  - GameStart event (fixed offsets per the Slippi spec / slippi-js):
    stage, per-player external character id, costume, player type, teams.
  - UBJSON `metadata` footer: startAt, lastFrame, netplay names + connect
    codes, playedOn.
  - GameEnd event (last event in the raw block): end method, LRAS initiator,
    placements (game version >= 3.13).

File layout (UBJSON):
  {U\\x03raw[$U#l <i32 raw_len> <raw events> U\\x08metadata{...}}
"""
import io
import json
import os
import struct

HEADER = b"{U\x03raw[$U#l"
RAW_START = 15  # len(HEADER) + 4-byte raw length

CMD_EVENT_PAYLOADS = 0x35
CMD_GAME_START = 0x36
CMD_POST_FRAME = 0x38
CMD_GAME_END = 0x39

# offset of "stocks remaining" (u8) inside the Post-Frame Update payload
POST_FRAME_STOCKS_OFF = 0x20
# offset of "percent" (f32) inside the Post-Frame Update payload
POST_FRAME_PERCENT_OFF = 0x15

PLAYER_TYPE_HUMAN = 0
PLAYER_TYPE_CPU = 1
PLAYER_TYPE_EMPTY = 3


class SlpParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Minimal UBJSON decoder (only the types Slippi metadata uses, plus the
# optimized-array form for safety).
# ---------------------------------------------------------------------------

def _ub_read_length(buf, marker=None):
    m = marker if marker is not None else buf.read(1)
    if m == b"i":
        return struct.unpack(">b", buf.read(1))[0]
    if m == b"U":
        return struct.unpack(">B", buf.read(1))[0]
    if m == b"I":
        return struct.unpack(">h", buf.read(2))[0]
    if m == b"l":
        return struct.unpack(">i", buf.read(4))[0]
    if m == b"L":
        return struct.unpack(">q", buf.read(8))[0]
    raise SlpParseError(f"unsupported UBJSON length marker {m!r}")


def _ub_read_value(buf, marker=None):
    m = marker if marker is not None else buf.read(1)
    if not m:
        raise SlpParseError("unexpected EOF in metadata")
    if m == b"{":
        obj = {}
        while True:
            key_marker = buf.read(1)
            if key_marker == b"}":
                return obj
            key_len = _ub_read_length(buf, key_marker)
            key = buf.read(key_len).decode("utf-8", errors="replace")
            obj[key] = _ub_read_value(buf)
    if m == b"[":
        arr = []
        item_type = None
        count = None
        peek = buf.read(1)
        if peek == b"$":
            item_type = buf.read(1)
            peek = buf.read(1)
        if peek == b"#":
            count = _ub_read_length(buf)
            for _ in range(count):
                arr.append(_ub_read_value(buf, item_type))
            return arr
        # non-optimized array
        while peek != b"]":
            arr.append(_ub_read_value(buf, peek))
            peek = buf.read(1)
        return arr
    if m == b"S":
        return buf.read(_ub_read_length(buf)).decode("utf-8", errors="replace")
    if m in (b"i", b"U", b"I", b"l", b"L"):
        return _ub_read_length(buf, m)
    if m == b"d":
        return struct.unpack(">f", buf.read(4))[0]
    if m == b"D":
        return struct.unpack(">d", buf.read(8))[0]
    if m == b"T":
        return True
    if m == b"F":
        return False
    if m == b"Z":
        return None
    raise SlpParseError(f"unsupported UBJSON marker {m!r}")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_payload_sizes(head):
    """Event Payloads is the first raw event; returns {cmd: payload_size}."""
    if head[RAW_START] != CMD_EVENT_PAYLOADS:
        raise SlpParseError("first raw event is not Event Payloads")
    table_size = head[RAW_START + 1]  # includes the size byte itself
    sizes = {}
    pos = RAW_START + 2
    end = RAW_START + 1 + table_size
    while pos + 3 <= end:
        cmd = head[pos]
        sizes[cmd] = struct.unpack(">H", head[pos + 1:pos + 3])[0]
        pos += 3
    return sizes, end  # end = offset of the first real event (GameStart)


def _parse_game_start(ev):
    """ev = GameStart event bytes starting at the 0x36 command byte."""
    if ev[0] != CMD_GAME_START:
        raise SlpParseError("expected GameStart event")
    version = (ev[1], ev[2], ev[3])
    is_teams = bool(ev[0x0D])
    stage = struct.unpack(">H", ev[0x13:0x15])[0]
    players = []
    for i in range(4):
        base = 0x65 + 0x24 * i
        ptype = ev[base + 1]
        if ptype == PLAYER_TYPE_EMPTY:
            continue
        players.append({
            "port": i + 1,
            "type": ptype,  # 0 human, 1 cpu, 2 demo
            "character": ev[base],       # external character id
            "costume": ev[base + 3],
            "team": ev[base + 9] if is_teams else None,
        })
    return {
        "version": ".".join(str(v) for v in version),
        "is_teams": is_teams,
        "stage": stage,
        "players": players,
    }


def _parse_game_end(ev, version_tuple):
    if not ev or ev[0] != CMD_GAME_END:
        return {}
    out = {"end_method": ev[1] if len(ev) > 1 else None}
    if len(ev) > 2:
        lras = struct.unpack(">b", ev[2:3])[0]
        out["lras_initiator"] = lras if lras >= 0 else None
    if len(ev) >= 7 and version_tuple >= (3, 13):
        placements = list(struct.unpack(">4b", ev[3:7]))
        out["placements"] = placements  # index = port-1, value 0 = 1st place
    return out


def parse_slp(path):
    """Parse one .slp file's cheap metadata. Raises SlpParseError on files
    that are corrupt, truncated, or still being written."""
    size = os.path.getsize(path)
    if size < RAW_START + 2:
        raise SlpParseError("file too small")

    with open(path, "rb") as f:
        head = f.read(4096)
        if not head.startswith(HEADER):
            raise SlpParseError("not a slp file (bad header)")
        raw_len = struct.unpack(">i", head[len(HEADER):len(HEADER) + 4])[0]
        if raw_len <= 0:
            # Dolphin backfills the raw length on clean close; killed sessions
            # leave it 0. Fall back to locating the metadata marker from the
            # file tail — raw then spans [RAW_START, metadata marker).
            with open(path, "rb") as tf:
                tf.seek(max(0, size - 65536))
                tail_chunk = tf.read()
            idx = tail_chunk.rfind(b"U\x08metadata{")
            if idx < 0:
                raise SlpParseError("raw length 0 and no metadata footer (unfinished file)")
            raw_len = (max(0, size - 65536) + idx) - RAW_START
            if raw_len <= 0:
                raise SlpParseError("metadata marker before raw start (corrupt)")
        if RAW_START + raw_len > size:
            raise SlpParseError("raw block extends past EOF (truncated)")

        sizes, gs_off = _parse_payload_sizes(head)
        gs_size = sizes.get(CMD_GAME_START)
        if not gs_size:
            raise SlpParseError("no GameStart payload size")
        if gs_off + 1 + gs_size > len(head):
            f.seek(gs_off)
            gs_bytes = f.read(1 + gs_size)
        else:
            gs_bytes = head[gs_off:gs_off + 1 + gs_size]
        start = _parse_game_start(gs_bytes)
        vparts = tuple(int(x) for x in start["version"].split("."))[:2]

        # GameEnd: last event in the raw block (when the game ended cleanly)
        end = {}
        ge_size = sizes.get(CMD_GAME_END)
        if ge_size:
            ge_off = RAW_START + raw_len - (1 + ge_size)
            if ge_off > gs_off:
                f.seek(ge_off)
                ge_bytes = f.read(1 + ge_size)
                if ge_bytes and ge_bytes[0] == CMD_GAME_END:
                    end = _parse_game_end(ge_bytes, vparts)

        # UBJSON metadata footer
        meta = {}
        meta_off = RAW_START + raw_len
        f.seek(meta_off)
        tail = f.read()
        if tail.startswith(b"U\x08metadata"):
            try:
                meta = _ub_read_value(io.BytesIO(tail[10:]))
            except SlpParseError:
                meta = {}

    # merge metadata names/codes into players
    meta_players = (meta or {}).get("players") or {}
    for p in start["players"]:
        mp = meta_players.get(str(p["port"] - 1)) or {}
        names = mp.get("names") or {}
        p["name"] = (names.get("netplay") or "").strip() or None
        p["code"] = (names.get("code") or "").strip() or None

    last_frame = (meta or {}).get("lastFrame")
    return {
        "version": start["version"],
        "is_teams": start["is_teams"],
        "stage": start["stage"],
        "players": start["players"],
        "start_at": (meta or {}).get("startAt"),
        "played_on": (meta or {}).get("playedOn"),
        "last_frame": last_frame,
        "duration_s": round((last_frame + 123) / 60.0, 1) if isinstance(last_frame, int) and last_frame >= -123 else None,
        "end_method": end.get("end_method"),
        "lras_initiator": end.get("lras_initiator"),
        "placements": end.get("placements"),
    }


def read_final_stocks(path):
    """{port: stocks_remaining} at the last recorded frame — the winner's
    stock count for the row summary.

    Cheap: walks the raw event stream skipping each event by its fixed size
    from the payloads table (no frame decode), tracking the last Post-Frame
    stock value per leader (followers/Nana ignored). ~5ms even on long games.
    Returns {} on any parse problem — this is a nice-to-have, never fatal."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
            if not head.startswith(HEADER):
                return {}
            raw_len = struct.unpack(">i", head[len(HEADER):len(HEADER) + 4])[0]
            if raw_len <= 0:
                return {}  # unfinished file; skip the summary
            sizes, gs_off = _parse_payload_sizes(head)
            if CMD_POST_FRAME not in sizes:
                return {}
            f.seek(0)
            data = f.read(RAW_START + raw_len)
    except (OSError, SlpParseError):
        return {}

    end = RAW_START + raw_len
    pf_size = sizes[CMD_POST_FRAME]
    stocks = {}
    pos = gs_off
    while pos < end:
        cmd = data[pos]
        sz = sizes.get(cmd)
        if sz is None:
            break  # unknown event = can't safely skip; bail with what we have
        if cmd == CMD_POST_FRAME and pos + 1 + pf_size <= end:
            p = data[pos + 1:pos + 1 + pf_size]
            if not p[5]:  # is_follower == 0 (ignore Nana)
                port = p[4] + 1
                val = p[POST_FRAME_STOCKS_OFF]
                if val <= 4:
                    stocks[port] = val
        pos += 1 + sz
    return stocks


def read_final_state(path, expected_last_frame=None):
    """{port: {"stocks": int, "percent": float}} at the last recorded frame,
    reading ONLY the tail of the raw block (~8KB) — cheap enough to run
    during a full scan, unlike read_final_stocks' whole-file walk.

    Purpose: placements only exist in .slp >= 3.13 (late 2022). For older
    games this end-state is the only way to score a winner — including LRAS
    quits, where "quitter loses" is wrong whenever the quitter was ahead.

    Works by scanning the tail chunk for Post-Frame events validated by
    field sanity (player index, stocks, percent, frame number near the
    metadata lastFrame when known) and keeping each port's latest frame.
    Returns {} on any problem — callers treat it as optional."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(4096)
            if not head.startswith(HEADER):
                return {}
            raw_len = struct.unpack(">i", head[len(HEADER):len(HEADER) + 4])[0]
            if raw_len <= 0:
                # unfinished file: locate the metadata footer like parse_slp
                f.seek(max(0, size - 65536))
                tail_chunk = f.read()
                idx = tail_chunk.rfind(b"U\x08metadata{")
                if idx < 0:
                    return {}
                raw_len = (max(0, size - 65536) + idx) - RAW_START
            sizes, _ = _parse_payload_sizes(head)
            pf_size = sizes.get(CMD_POST_FRAME)
            if not pf_size or pf_size < POST_FRAME_STOCKS_OFF + 1:
                return {}
            raw_end = min(RAW_START + raw_len, size)
            chunk_start = max(RAW_START, raw_end - 8192)
            f.seek(chunk_start)
            chunk = f.read(raw_end - chunk_start)
    except (OSError, SlpParseError, struct.error):
        return {}

    best = {}  # port -> (frame, stocks, percent)
    for i in range(len(chunk) - 1 - pf_size, -1, -1):
        if chunk[i] != CMD_POST_FRAME:
            continue
        p = chunk[i + 1:i + 1 + pf_size]
        frame = struct.unpack(">i", p[0:4])[0]
        if frame < -123 or frame > 8 * 60 * 60 * 60:  # > 8h = garbage
            continue
        if expected_last_frame is not None and not (
                expected_last_frame - 120 <= frame <= expected_last_frame + 1):
            continue
        port_idx, follower = p[4], p[5]
        stocks = p[POST_FRAME_STOCKS_OFF]
        if port_idx >= 4 or follower > 1 or stocks > 4:
            continue
        if follower:  # ignore Nana
            continue
        percent = struct.unpack(
            ">f", p[POST_FRAME_PERCENT_OFF:POST_FRAME_PERCENT_OFF + 4])[0]
        if not (0.0 <= percent < 1000.0):
            continue
        cur = best.get(port_idx + 1)
        if cur is None or frame > cur[0]:
            best[port_idx + 1] = (frame, stocks, percent)
    return {port: {"stocks": s, "percent": round(pct, 1)}
            for port, (_f, s, pct) in best.items()}


if __name__ == "__main__":
    import sys
    print(json.dumps(parse_slp(sys.argv[1]), indent=2))
    print("final stocks:", read_final_stocks(sys.argv[1]))
    print("final state:", read_final_state(sys.argv[1]))
