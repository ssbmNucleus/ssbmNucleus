"""Crafted replays against the readers that run in the serving process
(security review item 4).

slp_meta (the replay list's own reader) must stay fast and small on any
bytes: its metadata reader once recursed without a bound (RecursionError on
200,000 nested '[') and trusted counts (a 2^62-item array of nulls ran until
killed), and read_final_stocks allocated whatever raw length a file declared.
peppi_py only sees a file through slp_guard: the byte preflight
(slp_meta.peppi_refusal) and, outside the scan worker, a first parse in the
worker. The files here are built in the test; the biggest is ~100 KB.
"""
import os
import struct
import time
import tracemalloc

import pytest

from tracker.store import game_trace, scan_pool, slp_guard, slp_meta
from tracker.store.slp_meta import SlpParseError

SIZES = {0x36: 0x400, 0x37: 0x60, 0x38: 0x90, 0x39: 0x10, 0x3a: 0x20, 0x3c: 0x10}


def key(text):
    data = text.encode()
    return b"U" + bytes([len(data)]) + data


def text(value):
    return b"S" + key(value)


def metadata(netplay="Opp", code="OPP#123"):
    return (b"{" + key("startAt") + text("2026-01-01T00:00:00Z")
            + key("lastFrame") + b"l" + struct.pack(">i", 3)
            + key("players") + b"{"
            + key("0") + b"{" + key("names") + b"{" + key("netplay") + text(netplay)
            + key("code") + text(code) + b"}}"
            + key("1") + b"{" + key("names") + b"{" + key("netplay") + text("Me")
            + key("code") + text("ME#1") + b"}}"
            + b"}" + key("playedOn") + text("dolphin") + b"}")


def nested(depth):
    return b"{" + (key("a") + b"{") * depth + b"}" * depth + b"}"


def build(meta=None, sizes=SIZES, frames=4, raw_len=None, extra=b"", tail=b""):
    """A two-player .slp peppi_py parses whole (the security review's mkslp
    layout): payload table, GameStart, `frames` frames of frame start, pre,
    post and bookend, then `extra` raw bytes, GameEnd and the metadata."""
    table = bytes([0x35, 1 + 3 * len(sizes)])
    for cmd, size in sizes.items():
        table += bytes([cmd]) + struct.pack(">H", size)

    def event(cmd, fid=None, port=None):
        ev = bytearray(max(sizes[cmd] + 1, 0x200))
        ev[0] = cmd
        if fid is not None:
            struct.pack_into(">i", ev, 1, fid)
        if port is not None:
            ev[5] = port
        return ev

    def cut(cmd, ev):
        return bytes(ev[:sizes[cmd] + 1])

    start = event(0x36)
    start[1:4] = bytes([3, 18, 0])
    struct.pack_into(">H", start, 0x13, 31)
    for port in range(4):
        start[0x65 + port * 0x24] = (2, 9)[port] if port < 2 else 0
        start[0x66 + port * 0x24] = 0 if port < 2 else 3
    events = [table, cut(0x36, start)]
    for i in range(frames):
        fid = -123 + i
        events.append(cut(0x3a, event(0x3a, fid)))
        events += [cut(0x37, event(0x37, fid, port)) for port in range(2)]
        for port in range(2):
            post = event(0x38, fid, port)
            post[7] = (2, 9)[port]
            post[0x21] = 4                      # stocks
            events.append(cut(0x38, post))
        bookend = event(0x3c, fid)
        struct.pack_into(">i", bookend, 5, fid)
        events.append(cut(0x3c, bookend))
    end = event(0x39)
    end[1], end[2] = 2, 0xFF
    raw = b"".join(events) + extra + cut(0x39, end)
    header = b"{U\x03raw[$U#l" + struct.pack(">i", len(raw) if raw_len is None else raw_len)
    return header + raw + b"U\x08metadata" + (metadata() if meta is None else meta) + b"}" + tail


@pytest.fixture
def slp(tmp_path):
    def write(data, name="game.slp"):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)
    return write


def quick(fn, *args, limit=2.0):
    started = time.monotonic()
    out = fn(*args)
    assert time.monotonic() - started < limit
    return out


# --- slp_meta -----------------------------------------------------------------

def test_real_metadata_still_reads(slp):
    got = slp_meta.parse_slp(slp(build()))
    assert [(p["name"], p["code"]) for p in got["players"]] == [("Opp", "OPP#123"), ("Me", "ME#1")]
    assert (got["start_at"], got["played_on"], got["last_frame"]) == (
        "2026-01-01T00:00:00Z", "dolphin", 3)
    assert slp_meta.read_final_stocks(slp(build(), "s.slp")) == {1: 4, 2: 4}


@pytest.mark.parametrize("meta", [
    pytest.param(b"{" + key("x") + b"[" * 200_000 + b"]" * 200_000 + b"}", id="deep-arrays"),
    pytest.param(nested(200_000), id="deep-objects"),
    pytest.param(b"{" + key("x") + b"[$Z#L" + struct.pack(">q", 2 ** 62) + b"}", id="2^62-nulls"),
    pytest.param(b"{" + key("x") + b"[$i#L" + struct.pack(">q", 2 ** 40) + b"\x01}", id="2^40-ints"),
    pytest.param(b"{" + key("x") + b"SL" + struct.pack(">q", 2 ** 40) + b"abc}", id="2^40-string"),
    pytest.param(b"{L" + struct.pack(">q", 2 ** 40) + b"abc}", id="2^40-key"),
    pytest.param(b"{" + key("x") + b"Si\xff" + b"A" * 50 + b"}", id="negative-length"),
    pytest.param(b"{" + key("x") + b"[#l" + struct.pack(">i", 2 ** 31 - 1) + b"}", id="count-past-end"),
])
def test_crafted_metadata_is_dropped_quickly(slp, meta):
    got = quick(slp_meta.parse_slp, slp(build(meta=meta)))
    assert [p["name"] for p in got["players"]] == [None, None]
    assert got["start_at"] is None and got["last_frame"] is None


@pytest.mark.parametrize("meta", [
    pytest.param(text("abc"), id="metadata-a-string"),
    pytest.param(b"{" + key("players") + b"[" + text("a") + b"]}", id="players-a-list"),
    pytest.param(b"{" + key("players") + b"{" + key("0") + b"{" + key("names") + b"{"
                 + key("netplay") + b"i\x05}}}" + key("lastFrame") + b"[i\x01]"
                 + key("startAt") + b"i\x01}", id="numbers-for-names"),
])
def test_metadata_of_the_wrong_shape_is_ignored_not_stored(slp, meta):
    got = slp_meta.parse_slp(slp(build(meta=meta)))
    assert [p["name"] for p in got["players"]] == [None, None]
    assert got["last_frame"] is None and got["start_at"] is None


def test_the_reader_has_its_own_depth_and_value_limits():
    with pytest.raises(SlpParseError, match="nested too deeply"):
        slp_meta.read_metadata(b"[" * 65 + b"]" * 65)
    assert slp_meta.read_metadata(b"[" * 63 + b"]" * 63) is not None
    with pytest.raises(SlpParseError, match="too many values"):
        slp_meta.read_metadata(b"[$Z#l" + struct.pack(">i", 200_000))


def test_final_stocks_never_allocates_the_declared_raw_length(slp):
    path = slp(build(raw_len=0x7FFFFFF0))
    tracemalloc.start()
    try:
        # it walks what the file actually holds
        assert slp_meta.read_final_stocks(path) == {1: 4, 2: 4}
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024


def test_final_stocks_stops_on_empty_events_short_payloads_and_its_event_limit(slp, monkeypatch):
    empty = {**SIZES, 0x37: 0}
    assert quick(slp_meta.read_final_stocks,
                 slp(build(sizes=empty, frames=0, extra=b"\x37" * 2_000_000), "e.slp")) == {}
    short = {**SIZES, 0x38: 6}
    assert slp_meta.read_final_stocks(slp(build(sizes=short), "s.slp")) == {}
    # GameStart, frame start, two pre-frames, then the first post-frame
    monkeypatch.setattr(slp_meta, "MAX_EVENTS", 5)
    assert slp_meta.read_final_stocks(slp(build(frames=10), "m.slp")) == {1: 4}


def test_nothing_reads_a_file_over_the_size_limit(slp, monkeypatch):
    path = slp(build())
    monkeypatch.setattr(slp_meta, "MAX_SLP_BYTES", 1000)
    with pytest.raises(SlpParseError, match="too large"):
        slp_meta.parse_slp(path)
    assert slp_meta.read_final_stocks(path) == {}
    assert slp_meta.read_final_state(path) == {}
    assert "larger than" in slp_meta.peppi_refusal(path)


def test_a_short_game_start_is_a_parse_error(slp):
    with pytest.raises(SlpParseError, match="GameStart"):
        slp_meta.parse_slp(slp(build(sizes={**SIZES, 0x36: 0x20}, frames=0)))


# --- the byte check before peppi ----------------------------------------------

def test_the_preflight_passes_real_files_finished_or_not(slp):
    assert slp_meta.peppi_refusal(slp(build())) is None
    assert slp_meta.peppi_refusal(slp(build(raw_len=0), "killed.slp")) is None


@pytest.mark.parametrize("data, why", [
    pytest.param(build(raw_len=0x7FFFFFFF), "past the end", id="raw-past-eof"),
    pytest.param(build(raw_len=-5), "negative", id="raw-negative"),
    pytest.param(build(meta=nested(5000)), "nested too deeply", id="deep-footer"),
    # raw length 0: peppi walks the events and reads what follows them, not
    # the last metadata marker in the file
    pytest.param(build(meta=nested(5000), raw_len=0, tail=b"U\x08metadata{}"),
                 "nested too deeply", id="raw0-deep-then-decoy"),
    pytest.param(build(sizes={**SIZES, 0x37: 0}, frames=0, raw_len=0, extra=b"\x37" * 10),
                 "no payload", id="raw0-empty-event"),
    pytest.param(b"tiny", "too small", id="tiny"),
    pytest.param(b"x" * 4096, "not a Slippi replay", id="garbage"),
])
def test_the_preflight_refuses_what_kills_peppi(slp, data, why):
    assert why in slp_meta.peppi_refusal(slp(data))


def test_the_preflight_bounds_the_footer_and_the_event_walk(slp, monkeypatch):
    big = slp(build(tail=b"Z" * 3000))
    monkeypatch.setattr(slp_meta, "MAX_METADATA_BYTES", 2000)
    assert "too large" in slp_meta.peppi_refusal(big)
    monkeypatch.setattr(slp_meta, "MAX_EVENTS", 5)
    assert "too many events" in slp_meta.peppi_refusal(slp(build(raw_len=0, frames=10), "w.slp"))


# --- peppi only behind the guard -----------------------------------------------

@pytest.fixture
def guarded(tmp_path, monkeypatch):
    monkeypatch.delenv("NUCLEUS_SCAN_INPROC", raising=False)
    monkeypatch.setattr(scan_pool, "QUARANTINE_PATH", tmp_path / "scan_quarantine.json")
    monkeypatch.setattr(scan_pool, "_unavailable_until", 0.0)
    monkeypatch.setattr(slp_guard, "_good", type(slp_guard._good)())
    monkeypatch.setattr(game_trace, "_CACHE", {})
    monkeypatch.setattr(game_trace, "_CACHE_ORDER", [])
    return tmp_path


def test_a_file_the_preflight_refuses_never_reaches_peppi(guarded, slp, monkeypatch):
    import peppi_py
    calls = []
    monkeypatch.setattr(peppi_py, "read_slippi", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(scan_pool, "run", lambda *a, **k: calls.append(("worker",) + a))
    deep = slp(build(meta=nested(20_000)))
    assert game_trace.load_trace(deep) is None
    assert calls == []
    with pytest.raises(slp_guard.UnsafeReplay, match="nested too deeply"):
        slp_guard.read_slippi(deep)


def test_peppi_is_only_reached_through_the_guard_or_the_worker():
    """A static check over the shipped backend: peppi_py is imported by the
    guard and by the stats analyzer, a straight copy of the rank pipeline's
    (tests/backend/test_vendored_sync.py), which is only ever run in the
    scan worker. Devtools (command-line tools on the developer's own files)
    are left out."""
    import re
    import subprocess
    from tests.paths import BACKEND, REPO
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", "app/backend/*.py"],
                             capture_output=True, text=True, check=True).stdout.split()
    importers, analyzer_calls = set(), []
    for rel in tracked:
        rel_backend = rel[len("app/backend/"):]
        if rel_backend.startswith("devtools/"):
            continue
        source = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*(from peppi_py import|import peppi_py)", source, re.M):
            importers.add(rel_backend)
        analyzer_calls += [(rel_backend, line.strip()) for line in source.splitlines()
                           if re.search(r"\banalyze_game\(", line)
                           and not line.lstrip().startswith(("def ", "#", "for r in analyze_game"))]
    assert importers <= {"tracker/store/slp_guard.py", "tracker/stats/analyzer.py",
                         "tracker/stats/deep_stats.py"}, importers
    # deep_stats only checks that peppi_py is installed
    deep_stats = (BACKEND / "tracker" / "stats" / "deep_stats.py").read_text(encoding="utf-8")
    assert "read_slippi" not in deep_stats
    assert analyzer_calls == [], analyzer_calls        # only scan_pool.run(analyze_game, ...)


def test_this_process_parses_only_what_a_worker_parsed_first(guarded, slp, monkeypatch):
    path = slp(build())
    probes = []
    monkeypatch.setattr(scan_pool, "run",
                        lambda fn, p, timeout=None: probes.append((fn, p, timeout)) or True)
    assert slp_guard.refusal(path) is None
    assert slp_guard.refusal(path) is None                   # remembered: once per file
    assert probes == [(slp_guard.probe, path, slp_guard.PROBE_TIMEOUT)]
    with open(path, "ab") as f:                              # changed: probed again
        f.write(b"\0")
    assert slp_guard.refusal(path) is None and len(probes) == 2


def test_a_file_that_killed_the_worker_or_no_worker_is_refused_here(guarded, slp, monkeypatch):
    path = slp(build())

    def killed(fn, p, timeout=None):
        raise scan_pool.ScanFailed("game.slp crashed the replay worker", p)

    monkeypatch.setattr(scan_pool, "run", killed)
    assert slp_guard.refusal(path) == "game.slp crashed the replay worker"
    assert game_trace.load_trace(path) is None

    def none(fn, p, timeout=None):
        raise scan_pool.WorkerUnavailable("the replay worker could not start")

    monkeypatch.setattr(scan_pool, "run", none)
    assert "could not start" in slp_guard.refusal(path)


def test_a_real_peppi_crash_is_contained_in_the_worker(guarded, slp, monkeypatch):
    """The real thing: with the byte check out of the way (here only; the
    worker does not run it), peppi_py overflows its stack on 20,000 nested
    objects. It does so in the worker, which dies; the file is quarantined
    and this process gets None, and is still here to say so."""
    deep = slp(build(meta=nested(20_000)))
    monkeypatch.setattr(slp_meta, "MAX_FOOTER_NESTING", 10 ** 9)
    assert game_trace.load_trace(deep) is None
    entry = scan_pool.quarantined(scan_pool.file_key(deep))
    assert entry["what"] == "crashed the replay worker" and entry["task"] == "probe"
    assert "crashed the replay worker before" in slp_guard.refusal(deep)
