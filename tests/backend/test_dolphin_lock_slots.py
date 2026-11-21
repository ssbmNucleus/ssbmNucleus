"""Harness Dolphin lock slots: one slot by default, N on a machine that opts in."""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from shared.ingame import boot, dolphin_lock


@pytest.fixture
def lock(tmp_path, monkeypatch):
    monkeypatch.setattr(dolphin_lock, "LOCK_PATH", tmp_path / "harness-dolphin.lock")
    monkeypatch.setitem(dolphin_lock._state, "depth", 0)
    monkeypatch.setitem(dolphin_lock._state, "token", None)
    monkeypatch.setitem(dolphin_lock._state, "slot", None)
    monkeypatch.delenv("NUCLEUS_DOLPHIN_SLOTS", raising=False)
    yield dolphin_lock
    while dolphin_lock._state["depth"] > 0:
        dolphin_lock.release()


@pytest.fixture
def other_process():
    """A live pid that is not ours, to own slots."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc.pid
    proc.kill()
    proc.wait()


def _own(path, pid):
    path.write_text(json.dumps({"pid": pid, "purpose": "sibling", "token": "x"}), encoding="utf-8")


def test_default_is_one_slot_at_lock_path(lock):
    assert lock.slot_count() == 1
    payload = lock.acquire("test")
    assert payload["slot"] == 0 and lock.current_slot() == 0
    assert lock.LOCK_PATH.exists()
    state = lock.status()
    assert state["locked"] and state["owner"]["pid"] == os.getpid()
    assert state["slot_count"] == 1 and state["free_slots"] == 0
    assert lock.release() is True
    assert not lock.LOCK_PATH.exists() and lock.current_slot() is None


def test_single_slot_busy_when_held_elsewhere(lock, other_process):
    _own(lock.LOCK_PATH, other_process)
    with pytest.raises(lock.BusyError) as error:
        lock.acquire("test", wait=0)
    assert error.value.owner["pid"] == other_process


def test_a_lease_file_a_failed_unlink_left_is_removed_by_the_next_release(lock, monkeypatch):
    payload = lock.acquire("test")
    real_unlink = type(lock.LOCK_PATH).unlink

    def held_by_scanner(path, missing_ok=False):
        raise PermissionError(13, "in use")
    monkeypatch.setattr(type(lock.LOCK_PATH), "unlink", held_by_scanner)
    monkeypatch.setattr(lock.file_retry, "retry_locked", lambda fn, *a, **k: fn(*a, **k))
    assert lock.release(token=payload["token"]) is True
    assert json.loads(lock.LOCK_PATH.read_text())["token"] == payload["token"]

    monkeypatch.setattr(type(lock.LOCK_PATH), "unlink", real_unlink)
    assert lock.release() is False
    assert not lock.LOCK_PATH.exists()


def test_takes_first_free_slot(lock, other_process, monkeypatch):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "3")
    _own(lock.slot_path(0), other_process)
    _own(lock.slot_path(1), other_process)
    payload = lock.acquire("test", wait=0)
    assert payload["slot"] == 2 and lock.current_slot() == 2
    assert lock.slot_path(2).name == "harness-dolphin.2.lock"
    assert lock.status()["free_slots"] == 0
    lock.release()
    assert not lock.slot_path(2).exists()
    assert lock.slot_path(0).exists() and lock.slot_path(1).exists()


def test_all_slots_busy(lock, other_process, monkeypatch):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "2")
    _own(lock.slot_path(0), other_process)
    _own(lock.slot_path(1), other_process)
    with pytest.raises(lock.BusyError):
        lock.acquire("test", wait=0)


def test_dead_owner_is_reclaimed(lock, monkeypatch):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "2")
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    _own(lock.slot_path(0), proc.pid)
    assert lock.acquire("test", wait=0)["slot"] == 0


def test_nesting_keeps_the_slot(lock, other_process, monkeypatch):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "2")
    _own(lock.slot_path(0), other_process)
    outer = lock.acquire("outer", wait=0)
    inner = lock.acquire("inner", wait=0)
    assert outer["slot"] == inner["slot"] == 1
    assert lock.release() is False and lock.slot_path(1).exists()
    assert lock.release() is True and not lock.slot_path(1).exists()


@pytest.mark.parametrize("value, expected", [("0", 1), ("4", 4), ("99", 8), ("junk", 1), ("", 1)])
def test_slot_count_is_clamped(lock, monkeypatch, value, expected):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", value)
    assert lock.slot_count() == expected


def test_slot_pipes_are_distinct():
    assert [dolphin_lock.slot_pipe(i) for i in range(dolphin_lock.MAX_SLOTS)] == list(range(1, 9))


def _booted(tmp_path, monkeypatch):
    monkeypatch.setattr(boot, "resolve_dolphin", lambda slippi: ("dolphin.exe", None))
    monkeypatch.setattr(boot, "pick_pipe_index", lambda max_index=8: 1)
    return boot.DolphinBoot("melee.iso", None, tmp_path / "runs")


def test_run_dirs_are_unique_within_one_second(lock, tmp_path, monkeypatch):
    frozen = boot.datetime(2026, 9, 26, 12, 0, 0)
    monkeypatch.setattr(boot, "datetime", type("Frozen", (), {"now": staticmethod(lambda: frozen)}))
    first = _booted(tmp_path, monkeypatch).prepare()
    second = _booted(tmp_path, monkeypatch).prepare()
    assert first.run_dir != second.run_dir
    assert first.run_dir.name == "test-20260926_120000"
    assert second.run_dir.name == "test-20260926_120000-1"


def test_held_slot_chooses_the_pipe(lock, tmp_path, monkeypatch, other_process):
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "3")
    _own(lock.slot_path(0), other_process)
    lock.acquire("frameshot", wait=0)
    prepared = _booted(tmp_path, monkeypatch).prepare()
    assert prepared.pipe_index == 2


def test_single_slot_keeps_picked_pipe(lock, tmp_path, monkeypatch):
    lock.acquire("frameshot", wait=0)
    assert _booted(tmp_path, monkeypatch).prepare().pipe_index == 1


def test_multi_slot_skips_waiting_for_other_dolphins(lock, monkeypatch):
    monkeypatch.setattr(boot, "dolphin_running", lambda: [1234])
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "2")
    assert boot.wait_until_no_dolphin(timeout=0.01) is True
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "1")
    start = time.time()
    assert boot.wait_until_no_dolphin(timeout=0.01) is False
    assert time.time() - start < 5


def test_a_stop_ends_the_wait_for_another_dolphin_at_once(lock, monkeypatch):
    """A cancelled job must not sit out the five-minute wait for the user's Dolphin."""
    monkeypatch.setattr(boot, "dolphin_running", lambda: [1234])
    monkeypatch.setenv("NUCLEUS_DOLPHIN_SLOTS", "1")
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    start = time.time()
    assert boot.wait_until_no_dolphin(timeout=60, stop_event=stop) is False
    assert time.time() - start < 5


def test_a_boot_releases_only_the_depth_it_took_and_only_once(lock):
    """F-A-2: verify_costume holds an outer depth and closes its boot twice; the second close must not spend the
    outer depth, and a boot that never acquired (prepare failed) releases nothing."""
    lock.acquire("verify costume", wait=0)
    never_launched = boot.DolphinBoot.__new__(boot.DolphinBoot)
    never_launched._memory_input, never_launched.proc, never_launched._holds_lock = None, None, False
    never_launched.terminate()
    assert lock._state["depth"] == 1
    lock.acquire("DolphinBoot fake.iso", wait=0)
    launched = boot.DolphinBoot.__new__(boot.DolphinBoot)
    launched._memory_input, launched.proc, launched._holds_lock = None, None, True
    launched.terminate()
    launched.terminate()
    assert lock._state["depth"] == 1 and lock.LOCK_PATH.exists(), "the outer holder still has the slot"
