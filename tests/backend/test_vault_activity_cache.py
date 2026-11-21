"""Activity cost bounds: cache, single-flight, owner isolation and pagination."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import pytest

from tracker.cloud import vault_client as vc


@pytest.fixture
def activity(monkeypatch):
    now, calls = [0], []
    monkeypatch.setattr(vc, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(vc, "_activity_cache", vc.OrderedDict())
    def call(url, body, **kwargs):
        calls.append(body.copy())
        return {"rows": [], "next": None}
    monkeypatch.setattr(vc, "_call", call)
    return now, calls


def test_reopening_is_cached_and_manual_refresh_has_a_floor(activity):
    now, calls = activity
    vc.account_activity("A")
    for _ in range(10):
        vc.account_activity("A")
        vc.account_activity("A", refresh=True)
    assert len(calls) == 2
    now[0] = 30
    vc.account_activity("A", refresh=True)
    assert len(calls) == 4
    now[0] = 329
    vc.account_activity("A")
    assert len(calls) == 4
    now[0] = 330
    vc.account_activity("A")
    assert len(calls) == 6


def test_accounts_and_pages_have_separate_bounded_cache_entries(activity):
    _, calls = activity
    vc.account_activity("A")
    vc.account_activity("B")
    vc.account_activity("A", kind="uploads", cursor="2026-08-01")
    vc.account_activity("A", kind="uploads", cursor="2026-08-01")
    assert len(calls) == 5
    assert calls[-1]["cursor"] == "2026-08-01"
    for i in range(70):
        vc.account_activity(f"account-{i}", kind="shares")
    assert len(vc._activity_cache) == vc._ACTIVITY_CACHE_SIZE
    assert all(key[0] != "A" for key in vc._activity_cache)


def test_simultaneous_mounts_share_cloud_reads(activity):
    _, calls = activity
    barrier = threading.Barrier(8)
    def read(_):
        barrier.wait(timeout=5)
        return vc.account_activity("A")
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(read, range(8)))
    assert len(calls) == 2
    assert all(result == results[0] for result in results)
    results[0]["upload_history"].append({"games": 5})
    assert vc.account_activity("A")["upload_history"] == []


def test_failures_are_throttled_without_legacy_fallback(activity, monkeypatch):
    now, calls = activity
    def fail(url, body, **kwargs):
        calls.append(body)
        raise vc.VaultError("deployment unavailable")
    monkeypatch.setattr(vc, "_call", fail)
    for _ in range(3):
        with pytest.raises(vc.VaultError):
            vc.account_activity("A", refresh=True)
    assert len(calls) == 1
    now[0] = 30
    with pytest.raises(vc.VaultError):
        vc.account_activity("A")
    assert len(calls) == 2
    assert all(call["action"] == "activity-page" for call in calls)


@pytest.mark.parametrize("page", [
    {"rows": [{}] * 31, "next": None},
    {"rows": [], "next": "2026-08-01"},
    {"rows": [{}], "next": "2026-08-01"},
    {"rows": [{}], "next": "2026-09-01"},
    {"rows": [{}], "next": "bad"},
])
def test_invalid_or_nonadvancing_pages_are_rejected(activity, monkeypatch, page):
    monkeypatch.setattr(vc, "_call", lambda *a, **kw: page)
    with pytest.raises(vc.VaultError):
        vc.account_activity("A", kind="uploads", cursor="2026-08-01")
