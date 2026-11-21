"""POST /ranks under overlapping requests (the Replays list opening months).

get_ranks serializes slippi.gg fetches behind one lock. A request that queued
there used to fetch again every code the request ahead of it had just fetched,
and a request whose codes were all cached still waited for the lock. Each
POST then sat open for tens of seconds, the browser's six connections to the
backend filled with them, and the month's own list request could not be sent.
"""
import sys
import threading

import pytest

from tests.paths import BACKEND

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tracker.store import indexer, slippi_rank  # noqa: E402


class _SpyLock:
    """The fetch lock, noting when a caller has to wait for it."""

    def __init__(self):
        self._lock = threading.Lock()
        self.contended = threading.Event()

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            self.contended.set()
            self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self._lock.release()


@pytest.fixture
def slow_slippi(tmp_path, monkeypatch):
    """A temp index DB and a slippi.gg stand-in that blocks until released."""
    monkeypatch.setattr(indexer, "DB_PATH", tmp_path / "nucleome.db")
    lock = _SpyLock()
    monkeypatch.setattr(slippi_rank, "_inflight_lock", lock)
    fetched = []
    entered = threading.Event()
    release = threading.Event()

    def fetch_one(code):
        fetched.append(code)
        entered.set()
        assert release.wait(10), "test never released the fake fetch"
        return {"exists": True, "ranked": False}

    monkeypatch.setattr(slippi_rank, "_fetch_one", fetch_one)
    yield fetched, entered, release, lock
    release.set()


def _in_thread(fn, *args):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn(*args)), daemon=True)
    t.start()
    return t, out


def test_a_queued_request_does_not_refetch_codes_the_one_ahead_just_fetched(slow_slippi):
    fetched, entered, release, lock = slow_slippi
    first, first_out = _in_thread(slippi_rank.get_ranks, ["ABC#123"])
    assert entered.wait(5)
    # the same page's codes again (a re-render while the first POST is out)
    second, second_out = _in_thread(slippi_rank.get_ranks, ["abc#123"])
    assert lock.contended.wait(5)  # it missed the cache and queued for the lock
    release.set()
    first.join(5)
    second.join(5)
    assert fetched == ["ABC#123"]
    assert first_out["r"] == second_out["r"] == {"ABC#123": {"exists": True, "ranked": False}}


def test_a_fully_cached_request_never_waits_behind_another_callers_fetches(slow_slippi):
    fetched, entered, release, _lock = slow_slippi
    conn = indexer.connect()
    try:
        indexer.kv_set(conn, "rank:OLD#1", {"at": slippi_rank.time.time(), "rank": {"exists": False}})
    finally:
        conn.close()
    busy, _ = _in_thread(slippi_rank.get_ranks, ["NEW#1"])
    assert entered.wait(5)  # NEW#1 is mid-fetch, holding the fetch lock

    cached, cached_out = _in_thread(slippi_rank.get_ranks, ["OLD#1"])
    cached.join(3)
    blocked = cached.is_alive()
    release.set()
    busy.join(5)
    cached.join(5)
    assert not blocked, "a cache-only /ranks request queued behind an unrelated fetch"
    assert cached_out["r"] == {"OLD#1": {"exists": False}}
    assert fetched == ["NEW#1"]
