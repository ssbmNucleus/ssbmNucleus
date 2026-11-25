"""Dependency-free .slp metadata reader for the nucleOME replay browser.

Reads ONLY the cheap parts of a Slippi replay — no frame data, no external
parser: a few KB per file instead of the whole thing.

  - GameStart event (fixed offsets per the Slippi spec / slippi-js):
    stage, per-player external character id, costume, player type, teams,
    and (3.9.0+) each port's online display name and connect code.
  - UBJSON `metadata` footer: startAt, lastFrame, netplay names + connect
    codes, playedOn. A name or code the footer gives wins; Game Start's
    fills in where the footer has none (the Nucleus client wrote online
    replays with empty footer `names` until 2026-11).
  - GameEnd event (last event in the raw block): end method, LRAS initiator,
    placements (game version >= 3.13).

File layout (UBJSON):
  {U\\x03raw[$U#l <i32 raw_len> <raw events> U\\x08metadata{...}}

Replays come from anywhere (a downloaded folder, a vault pull), so every read
here is bounded by the bytes actually there: the metadata reader refuses a
count or length larger than what is left, nesting deeper than
MAX_METADATA_DEPTH and more than MAX_METADATA_VALUES values, and nothing reads
a file over MAX_SLP_BYTES. peppi_refusal() is the byte check the backend runs
before handing a file to peppi_py (tracker/store/slp_guard.py), which a crafted
file can otherwise crash outright.
"""
import json
import os
import re
import struct
import unicodedata

HEADER = b"{U\x03raw[$U#l"
RAW_START = 15  # len(HEADER) + 4-byte raw length

# A real replay is a few MB (an hour-long four-player game with items is about
# 200 MB). Anything bigger is not read at all.
MAX_SLP_BYTES = 256 * 1024 * 1024
# The metadata footer is a few hundred bytes; only this much of it is read.
MAX_METADATA_BYTES = 1024 * 1024
MAX_METADATA_DEPTH = 64          # real metadata nests 4 deep
MAX_METADATA_VALUES = 100_000    # real metadata holds a few dozen
# Event walks stop here; an hour of four players with items is ~3M events.
MAX_EVENTS = 5_000_000
# peppi_py parses the metadata footer recursively and overflows its stack
# (the process dies) somewhere past 2,000 levels. Real metadata has under 20
# '{' / '[' bytes in it, counting stray ones inside numbers.
MAX_FOOTER_NESTING = 256

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

# Online identity in GameStart (Slippi replay spec, project-slippi/slippi-wiki
# SPEC.md; offsets from the command byte like the rest of _parse_game_start).
# Since 3.9.0, per port i: a Shift-JIS display name (15 chars + NUL) and a
# Shift-JIS connect code whose '#' is full width (0x81 0x94). Offline games
# leave both zeroed. (The Slippi UID at 0x249 and, from 3.14.0, the session
# id / game number / tiebreak number are not read: nothing here uses them.)
GS_NAMES_VERSION = (3, 9)
GS_NAME_OFF, GS_NAME_LEN = 0x1A5, 0x1F
GS_CODE_OFF, GS_CODE_LEN = 0x221, 0x0A
# A connect code as Slippi issues it: tag, '#', digits (8 ASCII chars at most,
# which the 10-byte field enforces).
_CODE_SHAPE = re.compile(r"[0-9A-Za-z]+#[0-9]+")


class SlpParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Minimal UBJSON decoder (only the types Slippi metadata uses, plus the
# optimized-array form for safety). Bounded: see the module docstring.
# ---------------------------------------------------------------------------

# typed-array item types that carry no payload byte, so their count is not
# bounded by the bytes left (only by MAX_METADATA_VALUES)
_NO_PAYLOAD = (b"Z", b"T", b"F", b"N")
_INT_FORMATS = {b"i": ">b", b"U": ">B", b"I": ">h", b"l": ">i", b"L": ">q"}


class _Reader:
    """The metadata bytes, read forward. Never reads past the end: a length
    longer than what is left is a corrupt (or crafted) file."""
    __slots__ = ("data", "pos", "values")

    def __init__(self, data):
        self.data, self.pos, self.values = data, 0, 0

    def remaining(self):
        return len(self.data) - self.pos

    def read(self, n):
        if n < 0 or n > len(self.data) - self.pos:
            raise SlpParseError("metadata runs past its end")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out


def _ub_read_length(buf, marker=None):
    """A UBJSON integer (the marker given, or read first)."""
    m = marker if marker is not None else buf.read(1)
    fmt = _INT_FORMATS.get(m)
    if fmt is None:
        raise SlpParseError(f"unsupported UBJSON length marker {m!r}")
    return struct.unpack(fmt, buf.read(struct.calcsize(fmt)))[0]


def _ub_read_count(buf, marker=None):
    """A length or count: an integer that may not be negative."""
    n = _ub_read_length(buf, marker)
    if n < 0:
        raise SlpParseError("negative length in metadata")
    return n


def _ub_read_value(buf, marker=None, depth=0):
    """One UBJSON value from a _Reader."""
    buf.values += 1
    if buf.values > MAX_METADATA_VALUES:
        raise SlpParseError("too many values in metadata")
    m = marker if marker is not None else buf.read(1)
    if m in (b"{", b"[") and depth >= MAX_METADATA_DEPTH:
        raise SlpParseError("metadata nested too deeply")
    if m == b"{":
        obj = {}
        while True:
            key_marker = buf.read(1)
            if key_marker == b"}":
                return obj
            key = buf.read(_ub_read_count(buf, key_marker)).decode("utf-8", errors="replace")
            obj[key] = _ub_read_value(buf, None, depth + 1)
    if m == b"[":
        arr = []
        item_type = None
        peek = buf.read(1)
        if peek == b"$":
            item_type = buf.read(1)
            peek = buf.read(1)
            if peek != b"#":
                raise SlpParseError("typed array without a count")
        if peek == b"#":
            count = _ub_read_count(buf)
            # every item but a marker-only one takes at least a byte
            if item_type not in _NO_PAYLOAD and count > buf.remaining():
                raise SlpParseError("array count larger than the metadata")
            if buf.values + count > MAX_METADATA_VALUES:
                raise SlpParseError("too many values in metadata")
            for _ in range(count):
                arr.append(_ub_read_value(buf, item_type, depth + 1))
            return arr
        # non-optimized array
        while peek != b"]":
            arr.append(_ub_read_value(buf, peek, depth + 1))
            peek = buf.read(1)
        return arr
    if m == b"S":
        return buf.read(_ub_read_count(buf)).decode("utf-8", errors="replace")
    if m in _INT_FORMATS:
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


def read_metadata(data):
    """Decode UBJSON metadata bytes (what follows the `U\\x08metadata` key).
    Raises SlpParseError on anything malformed or over the bounds."""
    return _ub_read_value(_Reader(data))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_payload_sizes(head):
    """Event Payloads is the first raw event; returns {cmd: payload_size}."""
    if len(head) < RAW_START + 2:
        raise SlpParseError("file too small")
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


def _game_start_bytes(f, head):
    """(payload sizes, GameStart offset, GameStart event bytes) of an open
    replay whose first 4 KB are `head`."""
    sizes, gs_off = _parse_payload_sizes(head)
    gs_size = sizes.get(CMD_GAME_START)
    if not gs_size:
        raise SlpParseError("no GameStart payload size")
    if gs_off + 1 + gs_size > len(head):
        f.seek(gs_off)
        return sizes, gs_off, f.read(1 + gs_size)
    return sizes, gs_off, head[gs_off:gs_off + 1 + gs_size]


def _sjis_field(raw):
    """A NUL-terminated Shift-JIS field as text, or None when it is empty or
    not clean text: undecodable bytes, or a control, private-use or
    unassigned character. A bad field is simply absent."""
    raw = raw.split(b"\0", 1)[0]
    if not raw:
        return None
    try:
        # cp932 is Windows' Shift-JIS, what Dolphin encodes with there; it
        # decodes everything plain Shift-JIS does
        text = raw.decode("cp932")
    except UnicodeDecodeError:
        return None
    if any(unicodedata.category(c)[0] == "C" for c in text):
        return None
    return text.strip() or None


def _half_width(text):
    """Full-width ASCII forms (U+FF01..U+FF5E, such as the code's '＃') as ASCII."""
    return "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c
                   for c in text)


def _gs_name(ev, i):
    off = GS_NAME_OFF + GS_NAME_LEN * i
    return _sjis_field(ev[off:off + GS_NAME_LEN])


def _gs_code(ev, i):
    off = GS_CODE_OFF + GS_CODE_LEN * i
    code = _sjis_field(ev[off:off + GS_CODE_LEN])
    code = code and _half_width(code)
    return code if code and _CODE_SHAPE.fullmatch(code) else None


def _parse_game_start(ev):
    """ev = GameStart event bytes starting at the 0x36 command byte."""
    if not ev or ev[0] != CMD_GAME_START:
        raise SlpParseError("expected GameStart event")
    if len(ev) < 0x65 + 0x24 * 4:
        raise SlpParseError("GameStart event too short")
    version = (ev[1], ev[2], ev[3])
    is_teams = bool(ev[0x0D])
    stage = struct.unpack(">H", ev[0x13:0x15])[0]
    # the identity block is only there in 3.9.0+ files whose payload holds it
    named = (version[:2] >= GS_NAMES_VERSION
             and len(ev) >= GS_CODE_OFF + GS_CODE_LEN * 4)
    players = []
    identity = {}
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
        identity[i + 1] = (_gs_name(ev, i), _gs_code(ev, i)) if named else (None, None)
    return {
        "version": ".".join(str(v) for v in version),
        "is_teams": is_teams,
        "stage": stage,
        "players": players,
        "identity": identity,  # {port: (name, code)}, for parse_slp's merge
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


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else None


def _text(value):
    return (value.strip() or None) if isinstance(value, str) else None


def parse_slp(path):
    """Parse one .slp file's cheap metadata. Raises SlpParseError on files
    that are corrupt, truncated, or still being written."""
    size = os.path.getsize(path)
    if size < RAW_START + 2:
        raise SlpParseError("file too small")
    if size > MAX_SLP_BYTES:
        raise SlpParseError("file too large for a replay")

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

        sizes, gs_off, gs_bytes = _game_start_bytes(f, head)
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
        tail = f.read(MAX_METADATA_BYTES)
        if tail.startswith(b"U\x08metadata"):
            try:
                meta = read_metadata(tail[10:])
            except SlpParseError:
                meta = {}

    # The footer is the file's word, not ours: anything of the wrong type is
    # dropped rather than stored (a list in an INTEGER column fails the scan).
    meta = _dict(meta)
    # merge names/codes into players: the metadata footer's when it has them,
    # else GameStart's (each field on its own)
    meta_players = _dict(meta.get("players"))
    for p in start["players"]:
        names = _dict(_dict(meta_players.get(str(p["port"] - 1))).get("names"))
        gs_name, gs_code = start["identity"].get(p["port"], (None, None))
        p["name"] = _text(names.get("netplay")) or gs_name
        p["code"] = _text(names.get("code")) or gs_code

    last_frame = meta.get("lastFrame")
    if isinstance(last_frame, bool) or not isinstance(last_frame, int):
        last_frame = None
    return {
        "version": start["version"],
        "is_teams": start["is_teams"],
        "stage": start["stage"],
        "players": start["players"],
        "start_at": _str(meta.get("startAt")),
        "played_on": _str(meta.get("playedOn")),
        "last_frame": last_frame,
        "duration_s": round((last_frame + 123) / 60.0, 1) if isinstance(last_frame, int) and last_frame >= -123 else None,
        "end_method": end.get("end_method"),
        "lras_initiator": end.get("lras_initiator"),
        "placements": end.get("placements"),
    }


def game_start_names(path):
    """{port: (name, code)} from GameStart alone: the first few KB of the
    file, no metadata. The indexer's re-parse asks this first so a game with
    no online names (every offline game) costs one small read. Returns {} on
    any problem, like the readers below."""
    try:
        if os.path.getsize(path) > MAX_SLP_BYTES:
            return {}
        with open(path, "rb") as f:
            head = f.read(4096)
            if not head.startswith(HEADER):
                return {}
            _sizes, _off, gs_bytes = _game_start_bytes(f, head)
        return _parse_game_start(gs_bytes)["identity"]
    except (OSError, SlpParseError, struct.error):
        return {}


def read_final_stocks(path):
    """{port: stocks_remaining} at the last recorded frame — the winner's
    stock count for the row summary.

    Cheap: walks the raw event stream skipping each event by its fixed size
    from the payloads table (no frame decode), tracking the last Post-Frame
    stock value per leader (followers/Nana ignored). ~5ms even on long games.
    Returns {} on any parse problem — this is a nice-to-have, never fatal.
    It runs in the serving process (the replay list), so it reads no file
    over MAX_SLP_BYTES and walks no more than MAX_EVENTS events."""
    try:
        size = os.path.getsize(path)
        if size > MAX_SLP_BYTES:
            return {}
        with open(path, "rb") as f:
            head = f.read(4096)
            if not head.startswith(HEADER):
                return {}
            raw_len = struct.unpack(">i", head[len(HEADER):len(HEADER) + 4])[0]
            if raw_len <= 0:
                return {}  # unfinished file; skip the summary
            sizes, gs_off = _parse_payload_sizes(head)
            if (sizes.get(CMD_POST_FRAME) or 0) <= POST_FRAME_STOCKS_OFF:
                return {}
            f.seek(0)
            # never more than the file: read(n) allocates n bytes up front,
            # and a crafted raw length is 2 GB
            data = f.read(min(RAW_START + raw_len, size))
    except (OSError, SlpParseError, struct.error):
        return {}

    end = min(RAW_START + raw_len, len(data))
    pf_size = sizes[CMD_POST_FRAME]
    stocks = {}
    pos = gs_off
    events = 0
    while pos < end:
        cmd = data[pos]
        sz = sizes.get(cmd)
        if not sz:
            break  # unknown (or empty) event = can't safely skip; bail with what we have
        events += 1
        if events > MAX_EVENTS:
            break
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
        if size > MAX_SLP_BYTES:
            return {}
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


# ---------------------------------------------------------------------------
# Before peppi_py
# ---------------------------------------------------------------------------

def _events_end(f, head, size):
    """Where peppi_py stops reading events in a file whose raw length is 0 (a
    session that was killed): it walks them by the payload table, and the
    metadata follows. The walk stops at GameEnd, at a byte that is not an
    event, or at the end of the file, so the footer counted from here covers
    whatever peppi reads as metadata. Returns (offset, None) or (None, why)."""
    try:
        sizes, pos = _parse_payload_sizes(head)
    except SlpParseError as e:
        return None, str(e)
    block_start, block = pos, b""
    events = 0
    while pos < size:
        if not block_start <= pos < block_start + len(block):
            f.seek(pos)
            block, block_start = f.read(1 << 22), pos
            if not block:
                break
        cmd = block[pos - block_start]
        sz = sizes.get(cmd)
        if sz is None:
            break
        if sz == 0:
            return None, "an event with no payload"
        events += 1
        if events > MAX_EVENTS:
            return None, "too many events"
        pos += 1 + sz
        if cmd == CMD_GAME_END:
            break
    return min(pos, size), None


def peppi_refusal(path):
    """Why peppi_py must not parse `path`, or None. Byte checks only (a few KB
    read for a normal file): peppi_py is Rust and a crafted .slp makes it
    overflow its stack or allocate gigabytes, which kills the process rather
    than raising. Refused here:

      - a file over MAX_SLP_BYTES, or one too short to be a replay
      - a raw length past the end of the file (peppi allocates it up front;
        0x7fffffff took 1.7 GB in the security review) or below zero
      - a metadata footer over MAX_METADATA_BYTES, or with more than
        MAX_FOOTER_NESTING '{' / '[' bytes in it: peppi parses it recursively,
        so this bounds its depth whatever it makes of the bytes
    Everything else is peppi's to accept or refuse (with an exception)."""
    try:
        size = os.path.getsize(path)
        if size < RAW_START + 2:
            return "the file is too small to be a replay"
        if size > MAX_SLP_BYTES:
            return f"the file is larger than {MAX_SLP_BYTES // (1024 * 1024)} MB"
        with open(path, "rb") as f:
            head = f.read(4096)
            if not head.startswith(HEADER):
                return "the file is not a Slippi replay"
            raw_len = struct.unpack(">i", head[len(HEADER):len(HEADER) + 4])[0]
            if raw_len < 0:
                return "the raw event length is negative"
            if raw_len:
                end = RAW_START + raw_len
                if end > size:
                    return "the raw event block runs past the end of the file"
            else:
                end, why = _events_end(f, head, size)
                if why:
                    return why
            if size - end > MAX_METADATA_BYTES:
                return "the metadata is too large"
            f.seek(end)
            footer = f.read()
    except OSError as e:
        return f"the file could not be read ({e.strerror or e})"
    if footer.count(b"{") + footer.count(b"[") > MAX_FOOTER_NESTING:
        return "the metadata is nested too deeply"
    return None


if __name__ == "__main__":
    import sys
    print(json.dumps(parse_slp(sys.argv[1]), indent=2))
    print("final stocks:", read_final_stocks(sys.argv[1]))
    print("final state:", read_final_state(sys.argv[1]))
