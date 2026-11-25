"""GameTrace — the parse-once frame trace every deep-stats / coach / clip
consumer reads (tracker/store/game_trace.py).

Pins the three time bases a trace hands out and how they line up:

    row index      0-based position in the per-port arrays
    slippi_frame   raw Slippi frame id (first recorded frame = -123, GO = 0)
    elapsed        seconds since GO (countdown clamps to 0)

plus rollback re-emissions (extra rows: index != frame - start), per-port
alignment, clean failure on unparseable files, and the parse-once cache.

Fixtures are tiny .slp files generated in-test (Slippi spec layout, ~20 KB)
and parsed by the REAL peppi_py — no binary files are checked in.
"""
import os
import struct

import peppi_py
import pytest

from tracker.store import game_trace
from tracker.store.game_trace import GameTrace, TimeCoord, load_trace

# ---------------------------------------------------------------------------
# Minimal Slippi replay builder (offsets per the Slippi SPEC, which counts the
# command byte as 0x0 — payload offsets below are spec offset - 1).
# ---------------------------------------------------------------------------
HEADER = b"{U\x03raw[$U#l"
CMD_PAYLOADS, CMD_GAME_START, CMD_PRE, CMD_POST = 0x35, 0x36, 0x37, 0x38
CMD_GAME_END, CMD_FRAME_START, CMD_ITEM, CMD_BOOKEND = 0x39, 0x3A, 0x3B, 0x3C

V3_9 = (3, 9, 0)    # modern: connect codes, frame bookends, items
V1_0 = (1, 0, 0)    # 2018-era: no airborne / l_cancel in post-frame

_SIZES = {
    V3_9: {CMD_GAME_START: 0x248, CMD_PRE: 0x3F, CMD_POST: 0x4C,
           CMD_GAME_END: 2, CMD_FRAME_START: 8, CMD_ITEM: 0x2A,
           CMD_BOOKEND: 8},
    V1_0: {CMD_GAME_START: 0x160, CMD_PRE: 0x3A, CMD_POST: 0x25,
           CMD_GAME_END: 1},
}

# external character ids (GameStart) and internal ids (post-frame)
FOX, FALCO, ICS, ZELDA, MARTH = 2, 20, 14, 18, 9
INT_FOX, INT_FALCO, INT_POPO, INT_NANA = 1, 22, 10, 11
INT_SHEIK, INT_ZELDA, INT_MARTH = 7, 19, 18

FOX_VS_FALCO = [
    {"char": FOX, "code": "AAA#111", "name": "alpha"},
    {"char": FALCO, "code": "BBB#222", "name": "bravo"},
]


def _game_start(version, players, size, stage=31, teams=False):
    ev = bytearray(size)
    ev[0:3] = bytes(version)
    ev[0xD - 1] = 1 if teams else 0
    struct.pack_into(">H", ev, 0x13 - 1, stage)
    for i in range(4):
        p = players[i] if i < len(players) else None
        base = 0x65 + 0x24 * i - 1
        if p is None:
            ev[base + 1] = 3                      # empty slot
            continue
        ev[base] = p["char"]
        ev[base + 1] = 0                          # human
        ev[base + 2] = 4                          # stocks
        if size >= 0x248:
            name = p.get("name", "").encode()
            code = p.get("code", "").encode()
            off = 0x1A5 + 0x1F * i - 1
            ev[off:off + len(name)] = name
            off = 0x221 + 0xA * i - 1
            ev[off:off + len(code)] = code
    return bytes([CMD_GAME_START]) + bytes(ev)


def _pre(frame, port, size, nana=False):
    ev = bytearray(size)
    struct.pack_into(">i", ev, 0, frame)
    ev[4], ev[5] = port, int(nana)
    return bytes([CMD_PRE]) + bytes(ev)


def _post(frame, port, size, nana=False, state=14, x=0.0, y=0.0, pct=0.0,
          stocks=4, internal=INT_FOX, lastatk=0, facing=1.0):
    ev = bytearray(size)
    struct.pack_into(">i", ev, 0, frame)
    ev[4], ev[5], ev[6] = port, int(nana), internal
    struct.pack_into(">H", ev, 0x8 - 1, state)
    struct.pack_into(">f", ev, 0xA - 1, x)
    struct.pack_into(">f", ev, 0xE - 1, y)
    struct.pack_into(">f", ev, 0x12 - 1, facing)
    struct.pack_into(">f", ev, 0x16 - 1, pct)
    ev[0x1E - 1] = lastatk
    ev[0x21 - 1] = stocks
    return bytes([CMD_POST]) + bytes(ev)


def _item(frame, spawn, x, owner=0, typ=0x36, size=0x2A):
    ev = bytearray(size)
    struct.pack_into(">i", ev, 0x0, frame)
    struct.pack_into(">H", ev, 0x4, typ)
    struct.pack_into(">f", ev, 0x7, 1.0)
    struct.pack_into(">f", ev, 0x13, x)
    struct.pack_into(">I", ev, 0x21, spawn)
    ev[0x29] = owner
    return bytes([CMD_ITEM]) + bytes(ev)


def build_slp(frames, players=FOX_VS_FALCO, version=V3_9, teams=False,
              items=None):
    """frames: [(frame_id, {port: post_kwargs})] in EMISSION order — a repeated
    frame id is a rollback re-emission. A port's kwargs may carry "nana":
    {post_kwargs} for an Ice Climbers follower row. items: {frame_id:
    [item_kwargs]} emitted after that frame's fighter events."""
    sizes = _SIZES[version]
    items = items or {}
    out = [bytes([CMD_PAYLOADS, 3 * len(sizes) + 1])]
    out += [bytes([c]) + struct.pack(">H", s) for c, s in sizes.items()]
    out.append(_game_start(version, players, sizes[CMD_GAME_START],
                           teams=teams))
    for fid, per_port in frames:
        if CMD_FRAME_START in sizes:
            out.append(bytes([CMD_FRAME_START]) + struct.pack(">iI", fid, 0))
        for port, kw in per_port.items():
            kw = dict(kw)
            nana = kw.pop("nana", None)
            out.append(_pre(fid, port, sizes[CMD_PRE]))
            out.append(_post(fid, port, sizes[CMD_POST], **kw))
            if nana is not None:
                out.append(_pre(fid, port, sizes[CMD_PRE], nana=True))
                out.append(_post(fid, port, sizes[CMD_POST], nana=True,
                                 **nana))
        for it in items.get(fid, ()):
            out.append(_item(fid, **it))
        if CMD_BOOKEND in sizes:
            out.append(bytes([CMD_BOOKEND]) + struct.pack(">ii", fid, fid))
    out.append(bytes([CMD_GAME_END, 2, 0xFF][:1 + sizes[CMD_GAME_END]]))
    raw = b"".join(out)
    return HEADER + struct.pack(">i", len(raw)) + raw + b"U\x08metadata{}}"


def tagged(fid, ports=(0, 1)):
    """Per-port kwargs whose x encodes (port, frame) — x = 1000*port + frame —
    so any row can be checked for the frame AND port it came from."""
    return {p: {"x": 1000.0 * p + fid, "internal": (INT_FOX, INT_FALCO)[p % 2]}
            for p in ports}


def clean_frames(start=-123, end=200):
    return [(f, tagged(f)) for f in range(start, end)]


def with_reemissions(frames, reemit, corrected_x=-1.0):
    """Insert a rollback re-emission (corrected values) right after each
    frame id in `reemit` — exactly how netplay writes a resimulated frame."""
    out = []
    for fid, kw in frames:
        out.append((fid, kw))
        if fid in reemit:
            out.append((fid, {p: dict(v, x=corrected_x - p)
                              for p, v in kw.items()}))
    return out


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Each test gets an empty parse cache (it is module-global)."""
    monkeypatch.setattr(game_trace, "_CACHE", {})
    monkeypatch.setattr(game_trace, "_CACHE_ORDER", [])


@pytest.fixture
def parse_spy(monkeypatch):
    """Counts real peppi parses (load_trace imports read_slippi per call)."""
    calls = []
    real = peppi_py.read_slippi

    def spy(path, *a, **kw):
        calls.append(path)
        return real(path, *a, **kw)

    monkeypatch.setattr(peppi_py, "read_slippi", spy)
    return calls


# ---------------------------------------------------------------------------
# Frame basis on a clean (no-rollback) replay
# ---------------------------------------------------------------------------

def test_row_zero_is_raw_frame_minus_123_on_a_clean_replay(tmp_path):
    """Row i holds raw Slippi frame -123+i; start_frame/frame_ids/n agree."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 200))))
    assert t.start_frame == -123
    assert t.frame_ids == list(range(-123, 200))
    assert t.n == len(t.frame_ids) == 323
    for i in (0, 122, 123, 200, t.n - 1):
        assert t.data[0]["x"][i] == t.frame_ids[i]          # P1 row i = frame
        assert t.data[1]["x"][i] == 1000 + t.frame_ids[i]   # P2 same row


def test_at_maps_row_to_raw_frame_and_elapsed_since_go(tmp_path):
    """at(row) -> slippi_frame = start+row; elapsed counts from GO, not row 0."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 400))))
    c0 = t.at(0)
    assert (c0.index, c0.slippi_frame, c0.elapsed) == (0, -123, 0.0)
    assert t.at(60).elapsed == 0.0                     # still in the countdown
    go = t.at(123)
    assert (go.slippi_frame, go.elapsed) == (0, 0.0)
    later = t.at(123 + 90)
    assert later.slippi_frame == 90
    assert later.elapsed == pytest.approx(1.5)
    d = later.as_dict()
    assert d == {"slippi_frame": 90, "elapsed": 1.5, "elapsed_str": "0:01.5"}


def test_index_of_frame_inverts_at_on_a_clean_replay(tmp_path):
    """index_of_frame(at(i).slippi_frame) == i for every row; GO is row 123."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 100))))
    assert t.index_of_frame(0) == 123
    assert t.index_of_frame(-123) == 0
    assert all(t.index_of_frame(t.at(i).slippi_frame) == i for i in range(t.n))


def test_at_and_index_of_frame_clamp_to_the_game(tmp_path):
    """Out-of-range rows/frames clamp to [0, n-1] instead of raising."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 50))))
    assert t.at(-5).index == 0 and t.at(-5).slippi_frame == -123
    assert t.at(t.n + 100).index == t.n - 1
    assert t.at(t.n + 100).slippi_frame == 49
    assert t.index_of_frame(-10_000) == 0
    assert t.index_of_frame(10_000) == t.n - 1


def test_start_frame_comes_from_the_file_not_the_constant(tmp_path):
    """A replay whose first id isn't -123 is still mapped from its real ids."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-100, 50))))
    assert t.start_frame == -100
    assert t.at(100).slippi_frame == 0
    assert t.index_of_frame(0) == 100
    assert t.data[0]["x"][t.index_of_frame(0)] == 0.0


def test_missing_frame_ids_fall_back_to_minus_123(tmp_path):
    """Without peppi frame ids the trace assumes the -123 start, naive mapping."""
    path = write(tmp_path, "g.slp", build_slp(clean_frames(-123, 30)))
    game = peppi_py.read_slippi(path)
    game.frames = type(game.frames)(id=_EmptyIds(), ports=game.frames.ports)
    t = GameTrace(path, game)
    assert t.frame_ids is None
    assert t.start_frame == game_trace.DEFAULT_START_FRAME == -123
    assert t.index_of_frame(0) == 123
    assert t.at(123).slippi_frame == 0


class _EmptyIds:
    def to_pylist(self):
        return []


def test_countdown_reads_the_match_clock(tmp_path):
    """as_dict(match_frames) adds the match clock; countdown frames read full."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 200))))
    eight_min = 8 * 60 * 60
    assert t.at(0).as_dict(match_frames=eight_min)["countdown_str"] == "8:00.0"
    assert t.at(123).as_dict(match_frames=eight_min)["countdown_str"] == "8:00.0"
    assert (t.at(123 + 90).as_dict(match_frames=eight_min)["countdown_str"]
            == "7:58.5")
    assert "countdown_str" not in t.at(123).as_dict()


def test_fmt_elapsed_is_minutes_and_tenths():
    """fmt_elapsed renders m:ss.s and clamps negatives to zero."""
    assert TimeCoord.fmt_elapsed(151.6) == "2:31.6"
    assert TimeCoord.fmt_elapsed(125.5) == "2:05.5"
    assert TimeCoord.fmt_elapsed(0) == "0:00.0"
    assert TimeCoord.fmt_elapsed(-3) == "0:00.0"


def test_timestamps_never_read_sixty_seconds():
    """The seconds field of a rendered stamp is always < 60 (rolls the minute)."""
    for frame in (3597, 3598, 3599):
        assert TimeCoord(frame + 123, -123).as_dict()["elapsed_str"] == "1:00.0"
    stamp = TimeCoord(123 + 1, -123).as_dict(match_frames=8 * 3600)
    assert stamp["countdown_str"] == "8:00.0"


# ---------------------------------------------------------------------------
# Rollback re-emissions: extra rows, so row != frame - start
# ---------------------------------------------------------------------------

def test_rollback_reemission_adds_a_row_and_last_occurrence_wins(tmp_path):
    """A re-emitted frame is an extra row; index_of_frame picks the corrected one."""
    frames = with_reemissions(clean_frames(-123, 100), reemit={3, 4, 5})
    t = load_trace(write(tmp_path, "rb.slp", build_slp(frames)))
    assert t.n == len(t.frame_ids) == 223 + 3
    assert t.frame_ids.count(4) == 2
    r4 = t.index_of_frame(4)
    assert t.frame_ids[r4] == 4
    assert t.data[0]["x"][r4] == -1.0          # the corrected (last) row
    assert t.data[1]["x"][r4] == -2.0          # same row on the other port
    # every later frame sits 3 rows past the naive frame - start_frame
    for f in (6, 50, 99):
        row = t.index_of_frame(f)
        assert row == f - t.start_frame + 3
        assert t.frame_ids[row] == f
        assert t.data[0]["x"][row] == f


def test_index_of_frame_never_inverts_a_window(tmp_path):
    """Absent ids map to the nearest id below, so lo <= hi for any lo <= hi."""
    frames = [(f, tagged(f)) for f in range(-123, 40) if f not in (10, 11)]
    frames = with_reemissions(frames, reemit={20, 21})
    t = load_trace(write(tmp_path, "gap.slp", build_slp(frames)))
    assert t.index_of_frame(10) == t.index_of_frame(9)    # absent -> below
    assert t.index_of_frame(11) == t.index_of_frame(9)
    rows = [t.index_of_frame(f) for f in range(-200, 100)]
    assert rows == sorted(rows)
    assert rows[0] == 0 and rows[-1] == t.n - 1


def test_at_reports_the_true_frame_on_rollback_replays(tmp_path):
    """at(row).slippi_frame is the frame id stored at that row, even after rollbacks."""
    frames = with_reemissions(clean_frames(-123, 100), reemit={3, 4, 5})
    t = load_trace(write(tmp_path, "rb.slp", build_slp(frames)))
    for f in (6, 50, 99):
        assert t.at(t.index_of_frame(f)).slippi_frame == f
    assert t.at(t.n - 1).slippi_frame == t.frame_ids[-1] == 99


def test_an_interaction_straddling_a_rewind_still_ends_after_it_starts(tmp_path):
    """Frame ids ...19, 20, 16, 17... : a window whose last row is the rewound
    16 must end on 20, not before its own start (the clip route would read
    end <= start as a hallucinated window and swap in a different combo)."""
    from tracker.video import interactions
    frames = ([(f, tagged(f)) for f in range(-123, 21)]
              + [(f, tagged(f)) for f in range(16, 60)])
    t = load_trace(write(tmp_path, "rewind.slp", build_slp(frames)))
    start_i = t.frame_ids.index(19)
    assert t.frame_ids[start_i:start_i + 3] == [19, 20, 16]
    hit = interactions._make_interaction(t, "hit", 0, 1, start_i, start_i + 2,
                                         evidence={}, certainty="detected")
    assert (hit["start_frame"], hit["end_frame"]) == (19, 20)


def test_combo_row_basis_matches_trace_rows_on_rollback(tmp_path):
    """combos' start_rf/end_rf (viewer basis) index the same rows as the trace."""
    from tracker.combos.combo_index import COMBO_RESET_FRAMES, extract_combos
    dmg, idle = 0x50, 0x0E
    pct = {10: 10.0, 11: 10.0, 12: 22.0, 13: 22.0, 14: 31.0}
    frames = []
    for f in range(-123, 15 + COMBO_RESET_FRAMES + 2):
        hit = f in pct
        frames.append((f, {
            0: {"state": idle, "lastatk": 1, "x": float(f)},
            1: {"state": dmg if hit else idle, "internal": INT_FALCO,
                "pct": pct.get(f, 0.0 if f < 10 else 31.0)}}))
    frames = with_reemissions(frames, reemit={3, 4, 5})
    path = write(tmp_path, "combo.slp", build_slp(frames))
    t = load_trace(path)
    (c,) = extract_combos(path, [1, 2])
    assert c["start_frame"] == 10                     # TRUE frame (Dolphin)
    row = t.index_of_frame(c["start_frame"])
    assert t.frame_ids[row] == 10
    assert c["start_rf"] - t.start_frame == row       # viewer row basis
    assert c["end_rf"] - t.start_frame == t.index_of_frame(c["end_frame"])


def test_item_frames_align_to_trace_rows_through_frame_ids(tmp_path):
    """stage_items reports TRUE frames; index_of_frame lands on that frame's row."""
    from tracker.video.stage_items import read_items
    frames = with_reemissions(clean_frames(-123, 60), reemit={0, 1, 2, 3})
    items = {f: [{"spawn": 5, "x": float(f), "owner": 1}] for f in range(20, 25)}
    path = write(tmp_path, "items.slp", build_slp(frames, items=items))
    t = load_trace(path)
    (tr,) = read_items(path).values()
    assert tr["start"] == 20 and tr["owner"] == 1
    row = t.index_of_frame(tr["start"])
    assert t.frame_ids[row] == 20 and t.data[0]["x"][row] == 20.0
    # the naive subtraction would land 4 frames early
    assert t.frame_ids[tr["start"] - t.start_frame] == 16


# ---------------------------------------------------------------------------
# Ports: order, alignment, characters, codes
# ---------------------------------------------------------------------------

def test_ports_are_in_port_order_with_equal_length_arrays(tmp_path):
    """data[0]/data[1] are P1/P2; every per-frame field has exactly n rows."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 80))))
    assert len(t.data) == 2
    assert [d["char"] for d in t.data] == [FOX, FALCO]
    assert t.stage == 31 and t.is_teams is False
    for port, d in enumerate(t.data):
        for key, val in d.items():
            if key in ("char", "team"):
                continue
            assert val is not None, f"port {port} field {key} not loaded"
            assert len(val) == t.n, f"port {port} field {key}"
        assert d["x"][t.index_of_frame(42)] == 1000 * port + 42
    assert t.data[0]["form"][0] == INT_FOX and t.data[1]["form"][0] == INT_FALCO
    assert t.followers == []                  # no Ice Climbers, no Nana rows


def test_empty_low_ports_compact_to_indices_0_and_1(tmp_path):
    """P2 vs P4 (P1/P3 empty) -> data[0] is P2, data[1] is P4."""
    players = [None, {"char": MARTH, "code": "CCC#3", "name": "c"},
               None, {"char": FALCO, "code": "DDD#4", "name": "d"}]
    frames = [(f, {1: {"x": 1000.0 + f, "internal": INT_MARTH},
                   3: {"x": 3000.0 + f, "internal": INT_FALCO}})
              for f in range(-123, 20)]
    t = load_trace(write(tmp_path, "g.slp", build_slp(frames, players=players)))
    assert [d["char"] for d in t.data] == [MARTH, FALCO]
    assert t.data[0]["x"][123] == 1000.0 and t.data[1]["x"][123] == 3000.0
    assert t.port_of_code({"DDD#4"}) == 1


def test_four_ports_trace_and_teams_flag(tmp_path):
    """Doubles/FFA (up to 4 ports) still trace for Watch Lite; teams flag kept."""
    players = [{"char": c} for c in (FOX, FALCO, MARTH, ZELDA)]
    frames = [(f, tagged(f, ports=(0, 1, 2, 3))) for f in range(-123, 10)]
    t = load_trace(write(tmp_path, "g.slp",
                         build_slp(frames, players=players, teams=True)))
    assert len(t.data) == 4
    assert t.is_teams is True
    assert [d["x"][0] for d in t.data] == [-123.0, 877.0, 1877.0, 2877.0]


def test_port_of_code_and_describe_ports(tmp_path):
    """Connect-code lookup is case-insensitive; port cards carry code + tag."""
    t = load_trace(write(tmp_path, "g.slp", build_slp(clean_frames(-123, 10))))
    assert t.port_of_code(["bbb#222"]) == 1
    assert t.port_of_code({"AAA#111", "ZZZ#9"}) == 0
    assert t.port_of_code({"ZZZ#9"}) is None
    assert t.port_of_code([None, ""]) is None
    assert t.describe_ports() == [
        {"port_index": 0, "character": "Fox", "code": "AAA#111", "tag": "alpha"},
        {"port_index": 1, "character": "Falco", "code": "BBB#222",
         "tag": "bravo"},
    ]


def test_zelda_sheik_transform_reads_the_in_game_form(tmp_path):
    """Per-frame internal ids track Zelda<->Sheik; display_char = dominant form."""
    players = [{"char": ZELDA, "code": "ZZ#1"}, {"char": FALCO, "code": "FF#2"}]
    frames = []
    for f in range(-123, 77):                        # 200 rows: 80 Zelda, 120 Sheik
        form = INT_ZELDA if f < -43 else INT_SHEIK
        frames.append((f, {0: {"internal": form},
                           1: {"internal": INT_FALCO}}))
    t = load_trace(write(tmp_path, "g.slp", build_slp(frames, players=players)))
    forms = t.form_series(0)
    assert len(forms) == t.n
    assert forms[0] == "Zelda" and forms[-1] == "Sheik"
    assert forms.count("Zelda") == 80 and forms.count("Sheik") == 120
    assert t.display_char(0) == "Sheik"              # not the CSS pick (Zelda)
    assert t.form_series(1) is None
    assert t.display_char(1) == "Falco"


def test_ice_climbers_nana_is_a_render_only_follower(tmp_path):
    """Nana rides in followers (n rows, None once dead), never in data."""
    players = [{"char": ICS, "code": "IC#1"}, {"char": FALCO, "code": "FF#2"}]
    frames = []
    for f in range(-123, 30):
        p0 = {"x": float(f), "internal": INT_POPO}
        if f < 0:                                      # Nana dies at GO
            p0["nana"] = {"x": -500.0 + f, "internal": INT_NANA}
        frames.append((f, {0: p0, 1: {"internal": INT_FALCO}}))
    t = load_trace(write(tmp_path, "g.slp", build_slp(frames, players=players)))
    assert len(t.data) == 2                            # 1v1 indexing intact
    (nana,) = t.followers
    assert nana["port"] == 0
    for key in ("state", "x", "y", "air", "form"):
        assert len(nana[key]) == t.n, key
    assert nana["x"][0] == -623.0 and nana["form"][0] == INT_NANA
    go = t.index_of_frame(0)
    assert nana["x"][go - 1] == -501.0
    assert nana["x"][go] is None and nana["state"][-1] is None


# ---------------------------------------------------------------------------
# Robustness: unparseable input -> None, nothing cached
# ---------------------------------------------------------------------------

def _truncated(tmp_path):
    full = build_slp(clean_frames(-123, 60))
    return write(tmp_path, "cut.slp", full[:len(full) // 2])


def _live_partial(tmp_path):
    # a replay still being written: raw length 0, no metadata footer yet,
    # last event cut mid-payload
    full = build_slp(clean_frames(-123, 60))
    body = full[len(HEADER) + 4:-len(b"U\x08metadata{}}")]
    return write(tmp_path, "live.slp",
                 HEADER + struct.pack(">i", 0) + body[:-37])


def _one_player(tmp_path):
    frames = [(f, {0: {}}) for f in range(-123, 20)]
    return write(tmp_path, "solo.slp",
                 build_slp(frames, players=[{"char": FOX}]))


BAD_INPUTS = {
    "none": lambda tmp: None,
    "empty_string": lambda tmp: "",
    "missing": lambda tmp: str(tmp / "nope.slp"),
    "directory": lambda tmp: str(tmp),
    "empty_file": lambda tmp: write(tmp, "e.slp", b""),
    "garbage": lambda tmp: write(tmp, "x.slp", bytes(range(256)) * 16),
    "header_only": lambda tmp: write(tmp, "h.slp", HEADER + b"\0\0\0\0"),
    "truncated": _truncated,
    "live_partial": _live_partial,
    "one_player": _one_player,
}


@pytest.mark.parametrize("kind", sorted(BAD_INPUTS))
def test_unparseable_input_returns_none_and_caches_nothing(tmp_path, kind):
    """Corrupt/short/missing replays give None — never a partial trace."""
    path = BAD_INPUTS[kind](tmp_path)
    assert load_trace(path) is None
    assert game_trace._CACHE == {} and game_trace._CACHE_ORDER == []


def test_failed_parse_is_retried_once_the_file_is_complete(tmp_path, parse_spy):
    """A failed parse is not negatively cached: the finished file loads."""
    full = build_slp(clean_frames(-123, 60))
    # still being written: raw length 0 and the last event cut, which peppi
    # refuses (a file cut short of its declared raw length never reaches
    # peppi at all: slp_meta.peppi_refusal)
    body = full[len(HEADER) + 4:-len(b"U\x08metadata{}}")]
    p = write(tmp_path, "g.slp", HEADER + struct.pack(">i", 0) + body[:len(body) // 2 - 3])
    assert load_trace(p) is None
    assert load_trace(p) is None
    assert len(parse_spy) == 2                         # retried, not cached
    write(tmp_path, "g.slp", full)
    t = load_trace(p)
    assert t is not None and t.n == 183


class _PyO3Panic(BaseException):
    """Stand-in for pyo3_runtime.PanicException, which derives from
    BaseException (a Rust panic inside peppi surfaces as this)."""


_PyO3Panic.__name__ = _PyO3Panic.__qualname__ = "PanicException"
_PyO3Panic.__module__ = "pyo3_runtime"


def test_peppi_panic_returns_none(tmp_path, monkeypatch):
    """A Rust panic inside peppi is a corrupt replay: None, nothing cached."""
    p = write(tmp_path, "g.slp", build_slp(clean_frames(-123, 10)))

    def panics(path, *a, **kw):
        raise _PyO3Panic("called `Result::unwrap()` on an `Err` value")

    monkeypatch.setattr(peppi_py, "read_slippi", panics)
    assert load_trace(p) is None
    assert game_trace._CACHE == {}


def test_peppi_panic_guard_at_the_other_parse_sites(tmp_path, monkeypatch):
    """analyze_game catches the panic; Ctrl-C still escapes."""
    from tracker.stats.analyzer import analyze_game
    p = write(tmp_path, "g.slp", build_slp(clean_frames(-123, 10)))

    def panics(path, *a, **kw):
        raise _PyO3Panic("called `Result::unwrap()` on an `Err` value")

    monkeypatch.setattr(peppi_py, "read_slippi", panics)
    assert analyze_game(p) == []

    def interrupted(path, *a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(peppi_py, "read_slippi", interrupted)
    with pytest.raises(KeyboardInterrupt):
        load_trace(p)


def test_pre_2_0_replay_does_not_raise(tmp_path):
    """An old (slp 1.0) replay loads or cleanly returns None — never raises."""
    p = write(tmp_path, "old.slp", build_slp(clean_frames(-123, 30),
                                             version=V1_0))
    t = load_trace(p)
    assert t is None or t.n == 153


def test_pre_2_0_replay_analyze_game_returns_no_rows(tmp_path):
    """analyze_game skips an slp 1.0 replay (no airborne/l_cancel) — no raise."""
    from tracker.stats.analyzer import analyze_game
    frames = clean_frames(-123, 30)
    old = write(tmp_path, "old.slp", build_slp(frames, version=V1_0))
    assert analyze_game(old, min_frames=1) == []
    new = write(tmp_path, "new.slp", build_slp(frames))
    assert len(analyze_game(new, min_frames=1)) == 2     # guard isn't vacuous


# ---------------------------------------------------------------------------
# Parse-once cache
# ---------------------------------------------------------------------------

def test_second_load_is_served_from_cache(tmp_path, parse_spy, monkeypatch):
    """Repeat loads (abs or relative path) return the same trace, one parse."""
    p = write(tmp_path, "g.slp", build_slp(clean_frames(-123, 40)))
    t1 = load_trace(p)
    t2 = load_trace(p)
    monkeypatch.chdir(tmp_path)
    t3 = load_trace("g.slp")
    assert t1 is not None and t1 is t2 is t3
    assert len(parse_spy) == 1


def test_changed_file_is_reparsed(tmp_path, parse_spy):
    """A grown/replaced file (size or mtime change) gets a fresh trace."""
    p = write(tmp_path, "g.slp", build_slp(clean_frames(-123, 40)))
    t1 = load_trace(p)
    write(tmp_path, "g.slp", build_slp(clean_frames(-123, 90)))   # grew
    t2 = load_trace(p)
    assert t2 is not t1 and (t1.n, t2.n) == (163, 213)
    # same size, different content: only the mtime moves
    frames = [(f, {0: {"x": 7.0}, 1: {"x": 8.0}}) for f in range(-123, 90)]
    write(tmp_path, "g.slp", build_slp(frames))
    st = os.stat(p)
    os.utime(p, (st.st_atime, st.st_mtime + 10))
    t3 = load_trace(p)
    assert t3 is not t2 and t3.data[0]["x"][5] == 7.0
    assert len(parse_spy) == 3


def test_cache_is_a_bounded_lru(tmp_path, parse_spy, monkeypatch):
    """Oldest-used trace is evicted past _CACHE_MAX; a touched one survives."""
    monkeypatch.setattr(game_trace, "_CACHE_MAX", 2)
    a, b, c = (write(tmp_path, f"{n}.slp", build_slp(clean_frames(-123, 10)))
               for n in "abc")
    ta = load_trace(a)
    load_trace(b)
    assert load_trace(a) is ta          # touch a -> b is now least recent
    load_trace(c)                       # evicts b
    assert len(game_trace._CACHE) == 2
    assert load_trace(a) is ta
    assert len(parse_spy) == 3
    load_trace(b)                       # re-parse
    assert len(parse_spy) == 4
